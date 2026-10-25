"""Anthropic backend (Claude, Messages API).

Structured output uses forced tool use: the schema is the input schema of a single tool
the model must call, a mechanism every Claude model supports. Anthropic has no embedding
API, so with Claude postloom embeds locally.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, cast

from postloom.adapters.llm.base import (
    EmbeddingKind,
    EmbeddingReply,
    HttpApi,
    InvalidOutputError,
    InvalidRequestError,
    JsonReply,
    OutputTruncatedError,
    ProviderText,
    TextReply,
    Turn,
    Usage,
    as_int,
    dicts,
)
from postloom.adapters.llm.http import HttpTransport, JsonObject, UrllibTransport
from postloom.application.errors import ExtractionError, ProviderAuthError, ProviderError

DEFAULT_BASE_URL = "https://api.anthropic.com/v1"
API_VERSION = "2023-06-01"
TEXT = ProviderText(
    label="Anthropic",
    key_help="Check it in Settings, or create one at console.anthropic.com.",
)


class AnthropicBackend:
    provider = "anthropic"
    free = False

    def __init__(
        self,
        api_key: str,
        *,
        transport: HttpTransport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 600.0,
        max_retries: int = 2,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ProviderAuthError("No Anthropic API key configured.")
        self._api = HttpApi(
            base_url=base_url,
            headers={"x-api-key": api_key.strip(), "anthropic-version": API_VERSION},
            text=TEXT,
            transport=transport or UrllibTransport(),
            timeout=timeout,
            max_retries=max_retries,
            sleep=sleep or time.sleep,
        )
        self._no_temperature: set[str] = set()
        """Models that refused a temperature setting (learned from their 400)."""

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
        payload = self._payload(model, system, [("user", prompt)], temperature, max_output_tokens)
        payload["tools"] = [
            {
                "name": schema_name,
                "description": "Record the result. Fill every field as the instructions say.",
                "input_schema": schema,
            }
        ]
        payload["tool_choice"] = {"type": "tool", "name": schema_name}
        body = self._post(model, payload)
        _raise_if_truncated(body)
        for block in _blocks(body):
            if block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
                return JsonReply(cast(JsonObject, block["input"]), _usage(body))
        raise InvalidOutputError("Claude didn't return the structured result.")

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
        body = self._post(
            model, self._payload(model, system, turns, temperature, max_output_tokens)
        )
        text = "".join(
            str(b.get("text", "")) for b in _blocks(body) if b.get("type") == "text"
        ).strip()
        if not text:
            raise ExtractionError(f"Claude returned an empty answer ({body.get('stop_reason')}).")
        return TextReply(text, _usage(body))

    def embed(
        self, model: str, texts: Sequence[str], *, kind: EmbeddingKind, dimensions: int | None
    ) -> EmbeddingReply:
        raise ProviderError(
            "Anthropic doesn't offer embeddings. Use local embeddings in Settings (the default)."
        )

    def list_models(self) -> list[str]:
        body = self._api.get("models?limit=100")
        data = body.get("data")
        ids = [item.get("id") for item in dicts(data)]
        return sorted(i for i in ids if isinstance(i, str))

    # -------------------------------------------------------------------------------
    def _payload(
        self,
        model: str,
        system: str,
        turns: Sequence[Turn],
        temperature: float,
        max_output_tokens: int,
    ) -> JsonObject:
        payload: JsonObject = {
            "model": model,
            "system": system,
            "max_tokens": max_output_tokens,
            "messages": [{"role": role, "content": text} for role, text in turns],
        }
        if model not in self._no_temperature:
            payload["temperature"] = temperature
        return payload

    def _post(self, model: str, payload: JsonObject) -> JsonObject:
        try:
            return self._api.post("messages", payload)
        except InvalidRequestError as error:
            if "temperature" not in error.detail.lower() or "temperature" not in payload:
                raise
            self._no_temperature.add(model)
            retry = {k: v for k, v in payload.items() if k != "temperature"}
            return self._api.post("messages", retry)


def _blocks(body: JsonObject) -> list[dict[str, Any]]:
    content = body.get("content")
    if not isinstance(content, list):
        return []
    return [cast(dict[str, Any], b) for b in cast(list[Any], content) if isinstance(b, dict)]


def _raise_if_truncated(body: JsonObject) -> None:
    if body.get("stop_reason") == "max_tokens":
        raise OutputTruncatedError("Claude's answer was cut off at its output limit.")


def _usage(body: JsonObject) -> Usage:
    usage = body.get("usage")
    if not isinstance(usage, dict):
        return Usage()
    data = cast(dict[str, Any], usage)
    cached = as_int(data.get("cache_creation_input_tokens")) + as_int(
        data.get("cache_read_input_tokens")
    )
    return Usage(
        input_tokens=as_int(data.get("input_tokens")) + cached,
        output_tokens=as_int(data.get("output_tokens")),
    )
