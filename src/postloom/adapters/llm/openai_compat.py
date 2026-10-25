"""Backend for the OpenAI API and every server that speaks its format.

That covers OpenAI, OpenRouter, Groq, Mistral, DeepSeek, Together, LM Studio, vLLM and
many more. They agree on ``/chat/completions`` but not on every parameter: OpenAI's
reasoning models reject ``temperature`` and ``max_tokens``, some servers lack JSON Schema
output, others don't know ``reasoning_effort``. Rather than a table of quirks that goes
stale, the backend reacts to the server's own 400 message: it drops or swaps the named
parameter, retries, and remembers the fix for that model.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, cast

from postloom.adapters.llm.base import (
    EmbeddingKind,
    EmbeddingReply,
    HttpApi,
    InvalidRequestError,
    JsonReply,
    OutputTruncatedError,
    ProviderText,
    TextReply,
    Turn,
    Usage,
    as_int,
    dicts,
    json_instruction,
    parse_json_object,
    strip_thinking,
)
from postloom.adapters.llm.http import HttpTransport, JsonObject, UrllibTransport
from postloom.application.errors import ExtractionError, ProviderError

JsonMode = Literal["schema", "object", "prompt"]
"""``response_format`` json_schema, then json_object, then instructions only."""

MAX_ADAPTATIONS = 4


@dataclass(frozen=True, slots=True)
class Quirks:
    """How to talk to one model. Starts from the provider's defaults, adapts on 400s."""

    token_param: Literal["max_completion_tokens", "max_tokens"] = "max_tokens"
    temperature: bool = True
    reasoning_effort: bool = False
    json_mode: JsonMode = "schema"
    max_output_cap: int | None = None
    """The server's own output limit, learned from its error message."""


@dataclass(frozen=True, slots=True)
class OpenAICompatibleConfig:
    provider: str
    """Recorded with usage, e.g. "openai", "openrouter", "custom"."""
    label: str
    base_url: str
    api_key: str | None
    key_help: str
    defaults: Quirks = field(default_factory=Quirks)
    headers: dict[str, str] = field(default_factory=dict[str, str])
    report_cost: bool = False
    """Ask for exact per-call cost in the response (OpenRouter's usage accounting)."""
    free: bool = False
    """True for servers on this computer, like LM Studio."""
    unreachable_help: str = "Check your internet connection."


class OpenAICompatibleBackend:
    def __init__(
        self,
        config: OpenAICompatibleConfig,
        *,
        transport: HttpTransport | None = None,
        timeout: float = 300.0,
        max_retries: int = 2,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        self._config = config
        headers = dict(config.headers)
        if config.api_key:
            headers["Authorization"] = f"Bearer {config.api_key.strip()}"
        self._api = HttpApi(
            base_url=config.base_url,
            headers=headers,
            text=ProviderText(config.label, config.key_help, config.unreachable_help),
            transport=transport or UrllibTransport(),
            timeout=timeout,
            max_retries=max_retries,
            sleep=sleep or time.sleep,
        )
        self._quirks: dict[str, Quirks] = {}

    @property
    def provider(self) -> str:
        return self._config.provider

    @property
    def free(self) -> bool:
        return self._config.free

    def quirks(self, model: str) -> Quirks:
        return self._quirks.get(model, self._config.defaults)

    # -- generation -----------------------------------------------------------------
    def complete_json(
        self,
        model: str,
        *,
        system: str,
        prompt: str,
        schema: JsonObject,
        schema_name: str,
        temperature: float,
        max_output_tokens: int,
        effort: str = "low",
    ) -> JsonReply:
        def build(quirks: Quirks) -> JsonObject:
            instructions = system
            if quirks.json_mode != "schema":
                instructions += json_instruction(schema)
            payload = self._base(
                model, quirks, instructions, [("user", prompt)], temperature, max_output_tokens
            )
            self._effort(payload, quirks, effort)
            if quirks.json_mode == "schema":
                payload["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": schema_name, "schema": schema, "strict": False},
                }
            elif quirks.json_mode == "object":
                payload["response_format"] = {"type": "json_object"}
            return payload

        body = self._post_adapting(model, "chat/completions", build)
        text, finish = _message(body, self._config.label)
        if finish == "length":
            raise OutputTruncatedError(f"{self._config.label}'s answer was cut off at its limit.")
        return JsonReply(parse_json_object(text, self._config.label), self._usage(body))

    def complete_text(
        self,
        model: str,
        *,
        system: str,
        turns: Sequence[Turn],
        temperature: float,
        max_output_tokens: int,
        effort: str = "low",
    ) -> TextReply:
        def build(quirks: Quirks) -> JsonObject:
            payload = self._base(model, quirks, system, turns, temperature, max_output_tokens)
            self._effort(payload, quirks, effort)
            return payload

        body = self._post_adapting(model, "chat/completions", build)
        text, _ = _message(body, self._config.label)
        return TextReply(strip_thinking(text), self._usage(body))

    def embed(
        self, model: str, texts: Sequence[str], *, kind: EmbeddingKind, dimensions: int | None
    ) -> EmbeddingReply:
        payload: JsonObject = {"model": model, "input": list(texts)}
        if dimensions:
            payload["dimensions"] = dimensions
        body = self._api.post("embeddings", payload)
        data = body.get("data")
        if not isinstance(data, list) or len(cast(list[Any], data)) != len(texts):
            raise ProviderError(f"{self._config.label} returned an unexpected embedding response.")
        rows = sorted(
            (
                cast(dict[str, Any], item)
                for item in cast(list[Any], data)
                if isinstance(item, dict)
            ),
            key=lambda item: as_int(item.get("index")),
        )
        vectors: list[list[float]] = []
        for row in rows:
            values = row.get("embedding")
            if not isinstance(values, list):
                raise ProviderError(f"{self._config.label} returned an embedding without values.")
            vectors.append([float(v) for v in cast(list[Any], values)])
        if len(vectors) != len(texts):
            raise ProviderError(f"{self._config.label} returned the wrong number of embeddings.")
        return EmbeddingReply(vectors, self._usage(body))

    def list_models(self) -> list[str]:
        body = self._api.get("models")
        data = body.get("data")
        ids = [item.get("id") for item in dicts(data)]
        return sorted(i for i in ids if isinstance(i, str))

    # -- request building -------------------------------------------------------------
    def _base(
        self,
        model: str,
        quirks: Quirks,
        system: str,
        turns: Sequence[Turn],
        temperature: float,
        max_output_tokens: int,
    ) -> JsonObject:
        messages: list[JsonObject] = [{"role": "system", "content": system}]
        messages += [{"role": role, "content": text} for role, text in turns]
        payload: JsonObject = {"model": model, "messages": messages}
        cap = quirks.max_output_cap
        payload[quirks.token_param] = min(max_output_tokens, cap) if cap else max_output_tokens
        if quirks.temperature:
            payload["temperature"] = temperature
        if self._config.report_cost:
            payload["usage"] = {"include": True}
        return payload

    @staticmethod
    def _effort(payload: JsonObject, quirks: Quirks, effort: str) -> None:
        if quirks.reasoning_effort:
            payload["reasoning_effort"] = "medium" if effort == "high" else "low"

    def _post_adapting(
        self, model: str, path: str, build: Callable[[Quirks], JsonObject]
    ) -> JsonObject:
        quirks = self.quirks(model)
        last = InvalidRequestError("", "")
        for _ in range(MAX_ADAPTATIONS + 1):
            payload = build(quirks)
            try:
                body = self._api.post(path, payload)
            except InvalidRequestError as error:
                if _context_overflow(error.detail):
                    raise ProviderError(
                        f"This text is too long for {model}'s context window. Choose a model "
                        f"with a larger context in Settings. ({error.detail})"
                    ) from error
                adapted = adapt(quirks, error.detail, as_int(payload.get(quirks.token_param)))
                if adapted is None:
                    raise
                quirks = adapted
                last = error
                continue
            self._quirks[model] = quirks
            return body
        raise ProviderError(
            f"{self._config.label} kept refusing the request after {MAX_ADAPTATIONS} "
            f"adjustments. ({last.detail})"
        )

    def _usage(self, body: JsonObject) -> Usage:
        usage = body.get("usage")
        if not isinstance(usage, dict):
            return Usage()
        data = cast(dict[str, Any], usage)
        cost = data.get("cost")
        reported = (
            float(cost) if self._config.report_cost and isinstance(cost, int | float) else None
        )
        return Usage(
            input_tokens=as_int(data.get("prompt_tokens")),
            output_tokens=as_int(data.get("completion_tokens")),
            cost_usd=reported,
        )


_NUMBER = re.compile(r"\d[\d,]*")
_LIMIT_WORDS = ("too large", "exceed", "maximum", "at most", "less than", "<=", "up to")


def adapt(quirks: Quirks, detail: str, requested_tokens: int = 0) -> Quirks | None:
    """The next thing to try after a 400 that names a parameter, or None if none applies."""
    text = detail.lower()
    if "token" in text and any(word in text for word in _LIMIT_WORDS):
        limits = [int(n.replace(",", "")) for n in _NUMBER.findall(text)]
        usable = [n for n in limits if 256 <= n < requested_tokens]
        if usable:
            return replace(quirks, max_output_cap=max(usable))
    if "max_tokens" in text and quirks.token_param == "max_tokens":
        return replace(quirks, token_param="max_completion_tokens")
    if "max_completion_tokens" in text and quirks.token_param == "max_completion_tokens":
        return replace(quirks, token_param="max_tokens")
    if "temperature" in text and quirks.temperature:
        return replace(quirks, temperature=False)
    if "reasoning" in text and quirks.reasoning_effort:
        return replace(quirks, reasoning_effort=False)
    if any(word in text for word in ("response_format", "json_schema", "json schema")):
        if quirks.json_mode == "schema":
            return replace(quirks, json_mode="object")
        if quirks.json_mode == "object":
            return replace(quirks, json_mode="prompt")
    return None


def _context_overflow(detail: str) -> bool:
    text = detail.lower()
    return "context length" in text or "context window" in text or "context_length" in text


def _message(body: JsonObject, label: str) -> tuple[str, str | None]:
    choices = body.get("choices")
    if not isinstance(choices, list) or not choices:
        raise ExtractionError(f"{label} returned no answer.")
    first = cast(dict[str, Any], cast(list[Any], choices)[0])
    message = first.get("message")
    content = cast(dict[str, Any], message).get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        refusal = (
            cast(dict[str, Any], message).get("refusal") if isinstance(message, dict) else None
        )
        reason = refusal if isinstance(refusal, str) and refusal else first.get("finish_reason")
        raise ExtractionError(f"{label} returned an empty answer ({reason or 'no reason given'}).")
    finish = first.get("finish_reason")
    return content, finish if isinstance(finish, str) else None
