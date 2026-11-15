"""What every model provider backend offers, and the HTTP plumbing they share.

A *backend* speaks one provider's wire protocol (Gemini, OpenAI-compatible, Anthropic,
Ollama) and nothing else: no prompts, no domain types. The provider-neutral adapters in
this package (extractor, thread parser, chat, embeddings) build on any backend through
:class:`~postloom.adapters.llm.gateway.LlmGateway`, which also meters usage. Adding a
provider therefore means writing one backend and registering it in ``providers.py``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol, cast

from postloom.adapters.llm.http import CertificateError, HttpResponse, HttpTransport, JsonObject
from postloom.application.errors import (
    ExtractionError,
    ProviderAuthError,
    ProviderError,
    ProviderUnavailableError,
)

Turn = tuple[Literal["user", "assistant"], str]
"""One conversation message: who said it and what they said."""

Effort = Literal["low", "high"]
"""How hard a reasoning model should think: routine work, or the reply drafts."""

log = logging.getLogger("postloom.llm")
"""Retries are logged here, so a slow answer can be explained (``postloom doctor``)."""
RETRYABLE = frozenset({408, 429, 500, 502, 503, 504, 529})
"""Timeouts, rate limits and overload (529 is Anthropic's "overloaded")."""


class EmbeddingKind(StrEnum):
    DOCUMENT = "document"
    QUERY = "query"


@dataclass(frozen=True, slots=True)
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float | None = None
    """Exact cost when the provider reports it (OpenRouter does); otherwise estimated."""


@dataclass(frozen=True, slots=True)
class JsonReply:
    data: JsonObject
    usage: Usage


@dataclass(frozen=True, slots=True)
class TextReply:
    text: str
    usage: Usage


@dataclass(frozen=True, slots=True)
class EmbeddingReply:
    vectors: list[list[float]]
    usage: Usage


class InvalidOutputError(ExtractionError):
    """The model answered, but not with JSON matching the schema. Worth one retry."""


class OutputTruncatedError(ExtractionError):
    """The answer hit the output limit. Retrying the same request won't help."""


class InvalidRequestError(ProviderError):
    """HTTP 400: the provider refused a parameter. Carries its explanation."""

    def __init__(self, message: str, detail: str) -> None:
        super().__init__(message)
        self.detail = detail


class LlmBackend(Protocol):
    @property
    def provider(self) -> str:
        """Provider id, e.g. ``"anthropic"``; recorded with usage."""
        ...

    @property
    def free(self) -> bool:
        """True for models running on this computer: no cost, no budget."""
        ...

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
        effort: Effort = "low",
    ) -> JsonReply:
        """Return a JSON object for ``schema`` (parsed, not validated)."""
        ...

    def complete_text(
        self,
        model: str,
        *,
        system: str,
        turns: Sequence[Turn],
        temperature: float,
        max_output_tokens: int,
        effort: Effort = "low",
    ) -> TextReply:
        """Continue a conversation and return the next message."""
        ...

    def embed(
        self, model: str, texts: Sequence[str], *, kind: EmbeddingKind, dimensions: int | None
    ) -> EmbeddingReply:
        """Embed texts in one request; vectors in input order (not normalized)."""
        ...

    def list_models(self) -> list[str]:
        """Model ids this key can use, for setup screens. May be empty."""
        ...


# -- HTTP --------------------------------------------------------------------------
@dataclass(frozen=True, slots=True)
class ProviderText:
    """Wording for one provider's errors, so users know exactly what to fix."""

    label: str
    """Shown in messages, e.g. "Anthropic"."""
    key_help: str
    """Where to get or check a key, e.g. "Create one at console.anthropic.com."."""
    unreachable_help: str = "Check your internet connection."
    missing_model_help: str = "Pick another model in Settings."


class HttpApi:
    """JSON over HTTPS with retries, backoff and provider-neutral errors."""

    def __init__(
        self,
        *,
        base_url: str,
        headers: dict[str, str],
        text: ProviderText,
        transport: HttpTransport,
        timeout: float,
        max_retries: int = 2,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._headers = headers
        self._text = text
        self._transport = transport
        self._timeout = timeout
        self._max_retries = max_retries
        self._sleep = sleep

    def post(self, path: str, payload: JsonObject) -> JsonObject:
        url = self._url(path)
        return self._call(
            lambda: self._transport.post_json(url, payload, self._headers, self._timeout)
        )

    def get(self, path: str) -> JsonObject:
        url = self._url(path)
        return self._call(lambda: self._transport.get_json(url, self._headers, self._timeout))

    def _url(self, path: str) -> str:
        return path if path.startswith("http") else f"{self.base_url}/{path.lstrip('/')}"

    def _call(self, send: Callable[[], HttpResponse]) -> JsonObject:
        label = self._text.label
        for attempt in range(self._max_retries + 1):
            try:
                response = send()
            except CertificateError as error:
                raise ProviderUnavailableError(
                    f"Couldn't verify {label}'s security certificate, so the connection was "
                    "refused. On a company network or VPN, ask IT to install its root "
                    f"certificate in your system keychain. ({error})"
                ) from error
            except OSError as error:
                if attempt == self._max_retries:
                    raise ProviderUnavailableError(
                        f"Could not reach {label} at {self.base_url} ({error}). "
                        f"{self._text.unreachable_help}"
                    ) from error
                wait = backoff(attempt, None)
                log.warning("%s could not be reached (%s); retrying in %.0fs", label, error, wait)
                self._sleep(wait)
                continue
            if 200 <= response.status < 300:
                return response.body
            if response.status in RETRYABLE and attempt < self._max_retries:
                wait = backoff(attempt, response.retry_after)
                log.warning(
                    "%s answered HTTP %s (%s); retrying in %.0fs",
                    label,
                    response.status,
                    error_detail(response.body) or "busy",
                    wait,
                )
                self._sleep(wait)
                continue
            raise self._error(response.status, error_detail(response.body))
        raise AssertionError("unreachable")  # pragma: no cover

    def _error(self, status: int, detail: str) -> ProviderError:
        label, why = self._text.label, detail or f"HTTP {status}"
        lowered = detail.lower()
        if status in (401, 403) or (status == 400 and "api key" in lowered):
            return ProviderAuthError(f"{label} rejected the API key. {self._text.key_help} ({why})")
        if status == 402 or ("insufficient" in lowered and "credit" in lowered):
            return ProviderError(f"Your {label} account is out of credits. ({why})")
        if status == 404 or ("model" in lowered and "not found" in lowered):
            return ProviderError(
                f"{label} doesn't know this model; it may be misspelled or retired. "
                f"{self._text.missing_model_help} ({why})"
            )
        if status in RETRYABLE:
            return ProviderUnavailableError(
                f"{label} is busy or rate-limiting this key; try again in a minute. ({why})"
            )
        if status in (400, 422):
            return InvalidRequestError(f"{label} refused the request: {why}", detail)
        return ProviderError(f"{label} request failed with HTTP {status}. {detail}".strip())


def backoff(attempt: int, retry_after: float | None) -> float:
    return min(retry_after, 30.0) if retry_after else 2.0 * (2**attempt)


def error_detail(body: JsonObject) -> str:
    """The human message inside an error body, across providers' shapes."""
    error: object = body.get("error", body.get("message"))
    if isinstance(error, str):
        return error
    if isinstance(error, dict):
        message = cast(dict[str, Any], error).get("message")
        if isinstance(message, str):
            return message
    return ""


# -- parsing helpers ---------------------------------------------------------------
_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)
_THINKING = re.compile(r"<think>.*?</think>", re.DOTALL)


def parse_json_object(text: str, label: str) -> JsonObject:
    """Parse a model's JSON answer, tolerating code fences and stray prose around it."""
    cleaned = strip_thinking(text).strip()
    fenced = _FENCE.match(cleaned)
    if fenced:
        cleaned = fenced.group(1)
    try:
        parsed: object = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        try:
            parsed = json.loads(cleaned[start : end + 1]) if 0 <= start < end else None
        except json.JSONDecodeError:
            parsed = None
    if not isinstance(parsed, dict):
        raise InvalidOutputError(f"{label}'s answer was not a JSON object.")
    return cast(JsonObject, parsed)


def strip_thinking(text: str) -> str:
    """Remove ``<think>`` blocks some local reasoning models put in their answer."""
    return _THINKING.sub("", text).strip() if "<think>" in text else text


def dicts(value: object) -> list[dict[str, Any]]:
    """The JSON objects in a list (skipping anything else); [] if it isn't a list."""
    if not isinstance(value, list):
        return []
    return [cast(dict[str, Any], item) for item in cast(list[Any], value) if isinstance(item, dict)]


def as_int(value: object) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def json_instruction(schema: JsonObject) -> str:
    """For providers without native structured output: describe the schema in words."""
    return (
        "\n\nAnswer with one JSON object and nothing else (no Markdown fences, no prose). "
        f"It must match this JSON Schema:\n{json.dumps(schema, ensure_ascii=False)}"
    )
