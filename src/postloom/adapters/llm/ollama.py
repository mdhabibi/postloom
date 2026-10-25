"""Ollama backend: models running on this computer, through Ollama's native API.

The native API (not Ollama's OpenAI-compatible one) is used because it accepts
``num_ctx``. Ollama's default context is a few thousand tokens and it silently drops
whatever doesn't fit, which would quietly cut articles in half. postloom sizes the
context for every request, and refuses with a clear message when the text cannot fit in
the context limit the user allows (memory use grows with it).
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, cast

from postloom.adapters.llm.base import (
    EmbeddingKind,
    EmbeddingReply,
    HttpApi,
    JsonReply,
    OutputTruncatedError,
    ProviderText,
    TextReply,
    Turn,
    Usage,
    as_int,
    dicts,
    parse_json_object,
    strip_thinking,
)
from postloom.adapters.llm.http import HttpTransport, JsonObject, UrllibTransport
from postloom.application.errors import ExtractionError, ProviderError

DEFAULT_BASE_URL = "http://localhost:11434"
DEFAULT_CONTEXT_LIMIT = 32_768
MIN_CONTEXT = 8_192
CHARS_PER_TOKEN = 3
"""Deliberately pessimistic (English averages ~4), so the context is never too small."""

TEXT = ProviderText(
    label="Ollama",
    key_help="Ollama doesn't need a key; check the server address in Settings.",
    unreachable_help="Is Ollama running? Open the Ollama app, or run `ollama serve`.",
    missing_model_help="Download it with `ollama pull <model>`, or pick an installed one.",
)


class OllamaBackend:
    provider = "ollama"
    free = True

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        context_limit: int = DEFAULT_CONTEXT_LIMIT,
        transport: HttpTransport | None = None,
        timeout: float = 1800.0,
        max_retries: int = 1,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if context_limit < MIN_CONTEXT:
            raise ValueError(f"The Ollama context limit must be at least {MIN_CONTEXT} tokens.")
        self._context_limit = context_limit
        # Local generation is slow: a long article can take many minutes on a laptop.
        self._api = HttpApi(
            base_url=base_url,
            headers={},
            text=TEXT,
            transport=transport or UrllibTransport(),
            timeout=timeout,
            max_retries=max_retries,
            sleep=sleep or time.sleep,
        )

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
        turns: list[Turn] = [("user", prompt)]
        payload = self._payload(model, system, turns, temperature, max_output_tokens, json=True)
        payload["format"] = schema
        body = self._api.post("api/chat", payload)
        text = _content(body)
        if body.get("done_reason") == "length":
            raise OutputTruncatedError(
                "The local model's answer was cut off. Raise the Ollama context limit in "
                "Settings, or use a model with a longer context."
            )
        return JsonReply(parse_json_object(text, "The local model"), _usage(body))

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
        payload = self._payload(model, system, turns, temperature, max_output_tokens, json=False)
        body = self._api.post("api/chat", payload)
        return TextReply(strip_thinking(_content(body)), _usage(body))

    def embed(
        self, model: str, texts: Sequence[str], *, kind: EmbeddingKind, dimensions: int | None
    ) -> EmbeddingReply:
        body = self._api.post("api/embed", {"model": model, "input": list(texts)})
        embeddings = body.get("embeddings")
        if not isinstance(embeddings, list) or len(cast(list[Any], embeddings)) != len(texts):
            raise ProviderError("Ollama returned an unexpected embedding response.")
        vectors = [
            [float(v) for v in cast(list[Any], row)]
            for row in cast(list[Any], embeddings)
            if isinstance(row, list)
        ]
        if len(vectors) != len(texts):
            raise ProviderError("Ollama returned an embedding without values.")
        return EmbeddingReply(vectors, Usage(input_tokens=as_int(body.get("prompt_eval_count"))))

    def list_models(self) -> list[str]:
        body = self._api.get("api/tags")
        models = body.get("models")
        names = [m.get("name") for m in dicts(models)]
        return sorted(n for n in names if isinstance(n, str))

    # -------------------------------------------------------------------------------
    def _payload(
        self,
        model: str,
        system: str,
        turns: Sequence[Turn],
        temperature: float,
        max_output_tokens: int,
        *,
        json: bool,
    ) -> JsonObject:
        input_tokens = (len(system) + sum(len(text) for _, text in turns)) // CHARS_PER_TOKEN + 64
        # A restored article is about as long as the pasted one; chat answers are short.
        output = (
            min(max_output_tokens, max(2_048, input_tokens + input_tokens // 5 + 512))
            if json
            else max_output_tokens
        )
        needed = input_tokens + output
        if needed > self._context_limit:
            raise ProviderError(
                f"This needs about {needed:,} tokens of context, more than the "
                f"{self._context_limit:,} allowed for local models. Raise the Ollama context "
                "limit in Settings (it uses more memory), or use a hosted model for long texts."
            )
        context = MIN_CONTEXT
        while context < needed:
            context *= 2
        messages: list[JsonObject] = [{"role": "system", "content": system}]
        messages += [{"role": role, "content": text} for role, text in turns]
        return {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_ctx": min(context, self._context_limit),
                "num_predict": output,
            },
        }


def _content(body: JsonObject) -> str:
    message = body.get("message")
    content = cast(dict[str, Any], message).get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise ExtractionError("The local model returned an empty answer.")
    return content


def _usage(body: JsonObject) -> Usage:
    return Usage(
        input_tokens=as_int(body.get("prompt_eval_count")),
        output_tokens=as_int(body.get("eval_count")),
    )
