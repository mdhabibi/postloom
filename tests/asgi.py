"""A minimal synchronous client for ASGI apps (no network, no extra dependency)."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

Message = dict[str, Any]


@dataclass
class Reply:
    status: int
    headers: dict[str, str]
    body: bytes

    @property
    def json(self) -> Any:
        return json.loads(self.body)

    @property
    def text(self) -> str:
        return self.body.decode("utf-8")


@dataclass
class AsgiClient:
    app: Any
    host: str = "127.0.0.1:8765"
    default_headers: dict[str, str] = field(default_factory=lambda: {"x-postloom": "1"})

    def get(self, path: str, **kwargs: Any) -> Reply:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Reply:
        return self.request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Reply:
        return self.request("PUT", path, **kwargs)

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        raw_body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> Reply:
        return asyncio.run(self._request(method, path, json_body, raw_body, headers))

    async def _request(
        self,
        method: str,
        path: str,
        json_body: Any,
        raw_body: bytes | None,
        headers: dict[str, str] | None,
    ) -> Reply:
        url = urlsplit(path)
        body = raw_body if raw_body is not None else b""
        merged = {"host": self.host, **self.default_headers, **(headers or {})}
        if json_body is not None:
            body = json.dumps(json_body).encode("utf-8")
            merged["content-type"] = "application/json"
        scope: Message = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": url.path,
            "raw_path": url.path.encode(),
            "query_string": url.query.encode(),
            "root_path": "",
            "headers": [(k.lower().encode(), v.encode()) for k, v in merged.items()],
            "client": ("127.0.0.1", 50000),
            "server": ("127.0.0.1", 8765),
        }
        sent = False

        async def receive() -> Message:
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            await asyncio.sleep(3600)
            return {"type": "http.disconnect"}

        status = 500
        reply_headers: dict[str, str] = {}
        chunks: list[bytes] = []

        async def send(message: Message) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                for key, value in message.get("headers", []):
                    reply_headers[key.decode()] = value.decode()
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))

        await self.app(scope, receive, send)
        return Reply(status, reply_headers, b"".join(chunks))
