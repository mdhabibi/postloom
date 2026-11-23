"""A tiny stand-in for Ollama's HTTP API: lists models and streams a download."""

from __future__ import annotations

import json
import threading
from collections.abc import Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


@contextmanager
def fake_ollama(models: list[str], *, fail: str | None = None) -> Generator[str]:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            pass

        def do_GET(self) -> None:
            body = json.dumps({"models": [{"name": m} for m in models]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            events: list[dict[str, str | int]] = [{"status": "pulling manifest"}]
            if fail:
                events.append({"error": fail})
            else:
                events.append({"status": "pulling abc", "total": 100, "completed": 40})
                events.append({"status": "pulling abc", "total": 100, "completed": 100})
                events.append({"status": "success"})
                models.append(request["model"])
            for event in events:
                self.wfile.write(json.dumps(event).encode() + b"\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
