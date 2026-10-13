"""A tiny JSON-over-HTTPS transport on the standard library.

Provider adapters talk to this interface instead of an SDK: fewer dependencies for users
to install, and tests can swap in a fake transport without touching the network.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol, cast

JsonObject = dict[str, Any]


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int
    body: JsonObject
    """Parsed JSON body; ``{}`` when the body was empty or not JSON."""
    retry_after: float | None = None


class HttpTransport(Protocol):
    def post_json(
        self, url: str, payload: JsonObject, headers: dict[str, str], timeout: float
    ) -> HttpResponse:
        """POST ``payload`` as JSON. Raises ``OSError`` only when nothing came back."""
        ...


class UrllibTransport:
    """Real transport. Honours HTTPS_PROXY and the system certificate store."""

    def post_json(
        self, url: str, payload: JsonObject, headers: dict[str, str], timeout: float
    ) -> HttpResponse:
        data = json.dumps(payload).encode("utf-8")
        request = urllib.request.Request(
            url,
            data=data,
            method="POST",
            headers={"Content-Type": "application/json", **headers},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return HttpResponse(response.status, _parse(response.read()))
        except urllib.error.HTTPError as error:
            retry_after = error.headers.get("Retry-After") if error.headers else None
            return HttpResponse(error.code, _parse(error.read()), _seconds(retry_after))


def _parse(raw: bytes) -> JsonObject:
    try:
        parsed = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return cast(JsonObject, parsed) if isinstance(parsed, dict) else {}


def _seconds(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None
