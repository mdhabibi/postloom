"""The real urllib transport against a throwaway local HTTP server."""

import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, HTTPServer

from postloom.adapters.llm.http import UrllibTransport


class Handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        received = json.loads(self.rfile.read(length))
        if self.path == "/ok":
            self._send(200, {"echo": received, "key": self.headers.get("x-goog-api-key")})
        elif self.path == "/limited":
            self._send(429, {"error": {"message": "slow down"}}, retry_after="7")
        else:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(b"<html>oops</html>")

    def _send(self, status: int, body: object, retry_after: str | None = None) -> None:
        raw = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        if retry_after:
            self.send_header("Retry-After", retry_after)
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, format: str, *args: object) -> None:  # keep test output quiet
        pass


@contextmanager
def server() -> Iterator[str]:
    httpd = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_posts_json_and_parses_the_reply() -> None:
    with server() as base:
        response = UrllibTransport().post_json(f"{base}/ok", {"a": 1}, {"x-goog-api-key": "k"}, 5)
    assert response.status == 200
    assert response.body == {"echo": {"a": 1}, "key": "k"}


def test_error_status_is_returned_with_body_and_retry_after() -> None:
    with server() as base:
        response = UrllibTransport().post_json(f"{base}/limited", {}, {}, 5)
    assert response.status == 429
    assert response.body == {"error": {"message": "slow down"}}
    assert response.retry_after == 7.0


def test_non_json_error_bodies_become_empty() -> None:
    with server() as base:
        response = UrllibTransport().post_json(f"{base}/broken", {}, {}, 5)
    assert response.status == 500
    assert response.body == {}
