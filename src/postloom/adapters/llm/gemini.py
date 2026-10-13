"""Gemini via its REST API (``models.generateContent``).

The model is a setting, not a constant: Google retires model versions often, and users
choose their own price/quality trade-off.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable, Sequence
from typing import Any, cast

from postloom.adapters.llm.http import (
    CertificateError,
    HttpTransport,
    JsonObject,
    UrllibTransport,
)
from postloom.application.errors import (
    ExtractionError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

DEFAULT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_EXTRACTION_MODEL = "gemini-3.5-flash-lite"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"
DEFAULT_CHAT_MODEL = "gemini-3.8-flash"

_RETRYABLE = frozenset({429, 500, 502, 503, 504})


class GeminiClient:
    def __init__(
        self,
        api_key: str,
        *,
        transport: HttpTransport | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 120.0,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not api_key.strip():
            raise ProviderAuthError("No Gemini API key configured.")
        self._api_key = api_key.strip()
        self._transport = transport or UrllibTransport()
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep = sleep

    def generate_json(
        self,
        model: str,
        *,
        system: str,
        prompt: str,
        schema: JsonObject,
        temperature: float = 0.2,
        max_output_tokens: int = 32768,
    ) -> JsonObject:
        """Ask for a JSON object matching ``schema`` and return it parsed (not validated)."""
        payload: JsonObject = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": schema,
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        body = self._post(f"{self._base_url}/models/{model}:generateContent", payload)
        return _json_from_candidate(body)

    def generate_text(
        self,
        model: str,
        *,
        system: str,
        turns: Sequence[tuple[str, str]],
        temperature: float = 0.3,
        max_output_tokens: int = 4096,
    ) -> str:
        """Continue a conversation. ``turns`` are (role, text) with role "user" or "model"."""
        payload: JsonObject = {
            "systemInstruction": {"parts": [{"text": system}]},
            "contents": [{"role": role, "parts": [{"text": text}]} for role, text in turns],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_output_tokens,
            },
        }
        body = self._post(f"{self._base_url}/models/{model}:generateContent", payload)
        return _text_from_candidate(body, allow_truncation=True)

    def embed_texts(
        self,
        model: str,
        texts: Sequence[str],
        *,
        dimensions: int,
        task_type: str | None = None,
    ) -> list[list[float]]:
        """Embed ``texts`` in one batch request. Returns raw vectors in input order."""
        requests: list[JsonObject] = []
        for text in texts:
            item: JsonObject = {
                "model": f"models/{model}",
                "content": {"parts": [{"text": text}]},
                "outputDimensionality": dimensions,
            }
            if task_type:
                item["taskType"] = task_type
            requests.append(item)
        body = self._post(
            f"{self._base_url}/models/{model}:batchEmbedContents", {"requests": requests}
        )
        return _vectors_from(body, expected=len(texts), dimensions=dimensions)

    def _post(self, url: str, payload: JsonObject) -> JsonObject:
        # The key goes in a header, never the URL, so it can't leak into logs or proxies.
        headers = {"x-goog-api-key": self._api_key}
        for attempt in range(self._max_retries + 1):
            try:
                response = self._transport.post_json(url, payload, headers, self._timeout)
            except CertificateError as error:
                raise ProviderUnavailableError(
                    "Couldn't verify Gemini's security certificate, so the connection was "
                    "refused. If you're on a company network or VPN, ask IT to install its "
                    f"root certificate in your system keychain. ({error})"
                ) from error
            except OSError as error:
                if attempt == self._max_retries:
                    raise ProviderUnavailableError(
                        f"Could not reach Gemini ({error}). Check your internet connection."
                    ) from error
                self._sleep(_backoff(attempt, None))
                continue
            if response.status == 200:
                return response.body
            if response.status in _RETRYABLE and attempt < self._max_retries:
                self._sleep(_backoff(attempt, response.retry_after))
                continue
            raise _error_for(response.status, response.body)
        raise AssertionError("unreachable")  # pragma: no cover


def _backoff(attempt: int, retry_after: float | None) -> float:
    return min(retry_after, 30.0) if retry_after else 2.0 * (2**attempt)


def _error_message(body: JsonObject) -> str:
    error = body.get("error")
    if isinstance(error, dict):
        message = cast(dict[str, Any], error).get("message")
        if isinstance(message, str):
            return message
    return ""


def _error_for(status: int, body: JsonObject) -> ProviderError:
    detail = _error_message(body)
    if status in (401, 403) or (status == 400 and "api key" in detail.lower()):
        return ProviderAuthError(
            "Gemini rejected the API key. Check it in setup, or create a new one at "
            f"aistudio.google.com. ({detail or status})"
        )
    if status == 404:
        return ProviderError(
            "Gemini doesn't know this model; it may have been retired. Pick another "
            f"model in setup. ({detail or status})"
        )
    if status in _RETRYABLE:
        return ProviderUnavailableError(
            f"Gemini is busy or rate-limiting this key; try again in a minute. ({detail or status})"
        )
    return ProviderError(f"Gemini request failed with HTTP {status}. {detail}".strip())


def _text_from_candidate(body: JsonObject, *, allow_truncation: bool = False) -> str:
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
        raise ExtractionError("The article is too long for one extraction call.")
    if finish not in (None, "STOP", "MAX_TOKENS"):
        raise ExtractionError(f"Gemini stopped early (reason: {finish}).")
    parts = cast(list[dict[str, Any]], first.get("content", {}).get("parts", []))
    return "".join(p.get("text", "") for p in parts if not p.get("thought"))


def _json_from_candidate(body: JsonObject) -> JsonObject:
    text = _text_from_candidate(body)
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ExtractionError("Gemini's answer was not valid JSON.") from error
    if not isinstance(parsed, dict):
        raise ExtractionError("Gemini's answer was not a JSON object.")
    return cast(JsonObject, parsed)


def _vectors_from(body: JsonObject, *, expected: int, dimensions: int) -> list[list[float]]:
    embeddings = body.get("embeddings")
    if not isinstance(embeddings, list) or len(cast(list[Any], embeddings)) != expected:
        raise ProviderError("Gemini returned an unexpected embedding response.")
    vectors: list[list[float]] = []
    for item in cast(list[Any], embeddings):
        values = cast(dict[str, Any], item).get("values") if isinstance(item, dict) else None
        if not isinstance(values, list) or len(cast(list[Any], values)) != dimensions:
            raise ProviderError("Gemini returned an embedding with the wrong size.")
        vectors.append([float(v) for v in cast(list[Any], values)])
    return vectors
