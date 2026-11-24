"""Gemini backend (Google AI Studio REST API, ``generateContent``)."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from typing import Any, cast

from postloom.adapters.llm.base import (
    EmbeddingKind,
    EmbeddingReply,
    HttpApi,
    Image,
    InvalidRequestError,
    JsonReply,
    OutputTruncatedError,
    ProviderText,
    TextReply,
    Turn,
    Usage,
    as_int,
    parse_json_object,
)
from postloom.adapters.llm.http import HttpTransport, JsonObject, UrllibTransport
from postloom.application.errors import ExtractionError, ProviderAuthError, ProviderError

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
THINKING_LEVELS = {"low": "low", "high": "medium"}
"""postloom's effort -> Gemini's ``thinkingLevel``. "minimal" is never sent: some models
(3.8 Flash) refuse it."""
TEXT = ProviderText(
    label="Gemini",
    key_help="Check it in Settings, or create a new one at aistudio.google.com/apikey.",
)


class GeminiBackend:
    provider = "gemini"
    free = False

    def __init__(
        self,
        api_key: str,
        *,
        transport: HttpTransport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 300.0,
        max_retries: int = 2,
        sleep: Callable[[float], None] | None = None,
    ) -> None:
        if not api_key.strip():
            raise ProviderAuthError("No Gemini API key configured.")
        # The key goes in a header, never the URL, so it can't leak into logs or proxies.
        self._api = HttpApi(
            base_url=base_url,
            headers={"x-goog-api-key": api_key.strip()},
            text=TEXT,
            transport=transport or UrllibTransport(),
            timeout=timeout,
            max_retries=max_retries,
            sleep=sleep or time.sleep,
        )
        self._no_thinking_level: set[str] = set()
        """Models that refused a thinking level (learned from their 400)."""

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
        images: Sequence[Image] = (),
    ) -> JsonReply:
        payload: JsonObject = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {
                    "role": "user",
                    "parts": [
                        *(
                            {"inline_data": {"mime_type": i.mime, "data": i.base64()}}
                            for i in images
                        ),
                        {"text": prompt},
                    ],
                }
            ],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": to_gemini_schema(schema),
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        body = self._generate(model, payload, effort)
        text = _candidate_text(body, allow_truncation=False)
        return JsonReply(parse_json_object(text, "Gemini"), _usage(body))

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
        payload: JsonObject = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [
                {"role": "model" if role == "assistant" else "user", "parts": [{"text": text}]}
                for role, text in turns
            ],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_output_tokens},
        }
        body = self._generate(model, payload, effort)
        text = _candidate_text(body, allow_truncation=True).strip()
        if not text:
            raise OutputTruncatedError(
                "Gemini used its whole output limit thinking and wrote no answer. Try again, "
                "or choose a model that thinks less in Settings."
            )
        return TextReply(text, _usage(body))

    def _generate(self, model: str, payload: JsonObject, effort: str) -> JsonObject:
        """Send a generateContent request with a thinking level that matches ``effort``.

        Gemini 3 models think before answering, and how much is set by ``thinkingLevel``.
        Left unset, each model uses its own default, which differs per model (3.8 Flash
        thinks at "medium") and changes between releases, so postloom always says what
        it wants: "low" for routine work, "medium" for reply drafts. Thinking also counts
        against ``maxOutputTokens``, so less of it leaves more room for the answer.
        Models that don't accept a thinking level (older ones) refuse with a 400 that
        names it; that is learned once per model and the request is sent without it.
        """
        url = f"models/{model}:generateContent"
        if model in self._no_thinking_level:
            return self._api.post(url, payload)
        config = cast(JsonObject, payload["generationConfig"])
        level = THINKING_LEVELS.get(effort, "low")
        thinking: JsonObject = {"thinkingLevel": level}
        with_level: JsonObject = {
            **payload,
            "generationConfig": {**config, "thinkingConfig": thinking},
        }
        try:
            return self._api.post(url, with_level)
        except InvalidRequestError as error:
            if "thinking" not in error.detail.lower():
                raise
            self._no_thinking_level.add(model)
            return self._api.post(url, payload)

    def embed(
        self, model: str, texts: Sequence[str], *, kind: EmbeddingKind, dimensions: int | None
    ) -> EmbeddingReply:
        # gemini-embedding-2 takes the task inside the text (see embeddings.py); older
        # models take it as a field.
        task = None
        if not model.startswith("gemini-embedding-2"):
            task = "RETRIEVAL_QUERY" if kind is EmbeddingKind.QUERY else "RETRIEVAL_DOCUMENT"
        requests: list[JsonObject] = []
        for text in texts:
            item: JsonObject = {"model": f"models/{model}", "content": {"parts": [{"text": text}]}}
            if dimensions:
                item["outputDimensionality"] = dimensions
            if task:
                item["taskType"] = task
            requests.append(item)
        body = self._api.post(f"models/{model}:batchEmbedContents", {"requests": requests})
        vectors = _vectors(body, expected=len(texts), dimensions=dimensions)
        # Gemini doesn't report embedding tokens; ~4 characters per token is its own rule.
        return EmbeddingReply(vectors, Usage(input_tokens=sum(len(t) for t in texts) // 4))

    def list_models(self) -> list[str]:
        body = self._api.get("models?pageSize=200")
        models = body.get("models")
        names: list[str] = []
        for item in cast(list[Any], models) if isinstance(models, list) else []:
            name = cast(dict[str, Any], item).get("name") if isinstance(item, dict) else None
            if isinstance(name, str):
                names.append(name.removeprefix("models/"))
        return sorted(names)


def to_gemini_schema(schema: JsonObject) -> JsonObject:
    """JSON Schema -> Gemini's OpenAPI subset: upper-case types, ``nullable``, and an
    explicit ``propertyOrdering`` so the model writes fields in the order given."""
    out: JsonObject = {}
    kind: object = schema.get("type")
    if isinstance(kind, list):
        kinds = [str(k) for k in cast(list[Any], kind)]
        concrete = [k for k in kinds if k != "null"]
        out["type"] = concrete[0].upper() if concrete else "STRING"
        if "null" in kinds:
            out["nullable"] = True
    elif isinstance(kind, str):
        out["type"] = kind.upper()
    for key in ("enum", "description", "required"):
        if key in schema:
            out[key] = schema[key]
    properties = schema.get("properties")
    if isinstance(properties, dict):
        props = cast(dict[str, JsonObject], properties)
        out["properties"] = {name: to_gemini_schema(sub) for name, sub in props.items()}
        out["propertyOrdering"] = list(props)
    items = schema.get("items")
    if isinstance(items, dict):
        out["items"] = to_gemini_schema(cast(JsonObject, items))
    return out


def _usage(body: JsonObject) -> Usage:
    meta = body.get("usageMetadata")
    if not isinstance(meta, dict):
        return Usage()
    data = cast(dict[str, Any], meta)
    # Thinking tokens are billed as output.
    output = as_int(data.get("candidatesTokenCount")) + as_int(data.get("thoughtsTokenCount"))
    return Usage(input_tokens=as_int(data.get("promptTokenCount")), output_tokens=output)


def _candidate_text(body: JsonObject, *, allow_truncation: bool) -> str:
    candidates = body.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        feedback = body.get("promptFeedback")
        reason = (
            cast(dict[str, Any], feedback).get("blockReason")
            if isinstance(feedback, dict)
            else None
        )
        raise ExtractionError(f"Gemini returned no answer (blocked: {reason or 'unknown'}).")
    first = cast(dict[str, Any], cast(list[Any], candidates)[0])
    finish = first.get("finishReason")
    if finish == "MAX_TOKENS" and not allow_truncation:
        raise OutputTruncatedError("Gemini's answer was cut off at its output limit.")
    if finish not in (None, "STOP", "MAX_TOKENS"):
        raise ExtractionError(f"Gemini stopped early (reason: {finish}).")
    parts = cast(list[dict[str, Any]], first.get("content", {}).get("parts", []))
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _vectors(body: JsonObject, *, expected: int, dimensions: int | None) -> list[list[float]]:
    embeddings = body.get("embeddings")
    if not isinstance(embeddings, list) or len(cast(list[Any], embeddings)) != expected:
        raise ProviderError("Gemini returned an unexpected embedding response.")
    vectors: list[list[float]] = []
    for item in cast(list[Any], embeddings):
        values = cast(dict[str, Any], item).get("values") if isinstance(item, dict) else None
        if not isinstance(values, list) or (
            dimensions and len(cast(list[Any], values)) != dimensions
        ):
            raise ProviderError("Gemini returned an embedding with the wrong size.")
        vectors.append([float(v) for v in cast(list[Any], values)])
    return vectors
