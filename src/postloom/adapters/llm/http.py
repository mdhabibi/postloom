"""A tiny JSON-over-HTTPS transport on the standard library.

Provider adapters talk to this interface instead of an SDK: fewer dependencies for users
to install, and tests can swap in a fake transport without touching the network.
"""

from __future__ import annotations

import json
import ssl
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

    def get_json(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        """GET a JSON document. Raises ``OSError`` only when nothing came back."""
        ...


class CertificateError(OSError):
    """The server's TLS certificate could not be verified. Retrying won't help."""


def system_ssl_context() -> ssl.SSLContext:
    """TLS context that trusts the operating system's certificate store.

    Python builds installed by uv/pyenv ship OpenSSL without access to the macOS keychain
    or the Windows store, so the default context fails with CERTIFICATE_VERIFY_FAILED.
    ``truststore`` makes Python use the OS store, which also covers corporate proxies
    whose root certificate IT installed system-wide.
    """
    try:
        import truststore
    except ImportError:  # pragma: no cover - truststore is a declared dependency
        return ssl.create_default_context()
    return truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


class UrllibTransport:
    """Real transport. Honours HTTPS_PROXY and the operating system's certificates."""

    def __init__(self, context: ssl.SSLContext | None = None) -> None:
        self._context = context or system_ssl_context()

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
        return self._send(request, timeout)

    def get_json(self, url: str, headers: dict[str, str], timeout: float) -> HttpResponse:
        request = urllib.request.Request(url, method="GET", headers=headers)
        return self._send(request, timeout)

    def _send(self, request: urllib.request.Request, timeout: float) -> HttpResponse:
        try:
            with urllib.request.urlopen(request, timeout=timeout, context=self._context) as reply:
                return HttpResponse(reply.status, _parse(reply.read()))
        except urllib.error.HTTPError as error:
            retry_after = error.headers.get("Retry-After") if error.headers else None
            return HttpResponse(error.code, _parse(error.read()), _seconds(retry_after))
        except urllib.error.URLError as error:
            if isinstance(error.reason, ssl.SSLCertVerificationError):
                raise CertificateError(str(error.reason)) from error
            raise


def _parse(raw: bytes) -> JsonObject:
    try:
        parsed: object = json.loads(raw.decode("utf-8")) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return cast(JsonObject, parsed) if isinstance(parsed, dict) else {}


def _seconds(value: str | None) -> float | None:
    try:
        return float(value) if value else None
    except ValueError:
        return None
