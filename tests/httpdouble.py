"""A local HTTP test double.

Tests must not depend on live publisher responses, so every acquisition case in
the plan's gate — 403, 404, 429 with Retry-After, timeout, truncation, wrong
media type, oversized body, redirect loop, HTML login served as PDF — is served
from here.
"""

from __future__ import annotations

import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

WWW = Path(__file__).resolve().parent / "fixtures" / "demo" / "www"

LOGIN_PAGE = (
    b"<!DOCTYPE html><html><head><title>Sign in</title></head><body>"
    b"<h1>Sign in to continue</h1><form method=post><input name=user>"
    b"</form>" + b"<p>Institutional access required.</p>" * 30 + b"</body></html>"
)

ROBOTS = b"""User-agent: *
Disallow: /blocked/
Allow: /
"""


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "bibgraph-test-double"

    def log_message(self, *args):  # silence the default stderr logging
        pass

    def _send(self, status, body=b"", content_type="text/html; charset=utf-8",
              extra_headers=None, content_length=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length",
                         str(content_length if content_length is not None else len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if body:
            try:
                self.wfile.write(body)
            except (BrokenPipeError, ConnectionResetError):
                # Expected when a test aborts mid-body, e.g. the byte-cap case.
                pass

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler API
        path = self.path.split("?", 1)[0]
        counters = self.server.counters
        counters[path] = counters.get(path, 0) + 1

        if path == "/robots.txt":
            return self._send(200, ROBOTS, "text/plain")
        if path.startswith("/blocked/"):
            return self._send(200, b"<html><body>blocked by robots</body></html>")

        if path == "/forbidden.pdf":
            return self._send(403, b"Forbidden", "text/plain")
        if path == "/notfound.pdf":
            return self._send(404, b"Not Found", "text/plain")
        if path == "/servererror.pdf":
            return self._send(500, b"Server Error", "text/plain")

        if path == "/ratelimited.pdf":
            # 429 twice with Retry-After, then the real document.
            if counters[path] <= 2:
                return self._send(429, b"Slow down", "text/plain",
                                  {"Retry-After": "1"})
            return self._send(200, (WWW / "paper.pdf").read_bytes(), "application/pdf")

        if path == "/slow.pdf":
            time.sleep(self.server.slow_seconds)
            return self._send(200, (WWW / "paper.pdf").read_bytes(), "application/pdf")

        if path == "/login-as-pdf.pdf":
            # Declared as a PDF, actually an HTML login page.
            return self._send(200, LOGIN_PAGE, "application/pdf")

        if path == "/mislabeled.pdf":
            return self._send(200, b"x" * 2000, "application/pdf")

        if path == "/truncated.pdf":
            body = (WWW / "paper.pdf").read_bytes()
            self._send(200, body[: len(body) // 2], "application/pdf",
                       content_length=len(body))
            return

        if path == "/tiny.pdf":
            return self._send(200, b"%PDF-1.4\n", "application/pdf")

        if path == "/huge.pdf":
            body = b"%PDF-1.4\n" + b"0" * (2 * 1024 * 1024)
            return self._send(200, body, "application/pdf")

        if path == "/redirect-ok":
            return self._send(302, b"", extra_headers={"Location": "/paper.pdf"})
        if path == "/redirect-loop":
            return self._send(302, b"", extra_headers={"Location": "/redirect-loop-2"})
        if path == "/redirect-loop-2":
            return self._send(302, b"", extra_headers={"Location": "/redirect-loop"})
        if path == "/redirect-no-location":
            return self._send(302, b"")

        candidate = WWW / path.lstrip("/")
        if candidate.is_file() and candidate.parent == WWW:
            media = ("application/pdf" if candidate.suffix == ".pdf"
                     else "text/html; charset=utf-8")
            return self._send(200, candidate.read_bytes(), media)
        return self._send(404, b"Not Found", "text/plain")


class TestServer:
    """Context manager yielding the base URL of a throwaway local server."""

    def __init__(self, slow_seconds: float = 5.0):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.counters = {}
        self.httpd.slow_seconds = slow_seconds
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    @property
    def base_url(self) -> str:
        host, port = self.httpd.server_address[:2]
        return f"http://{host}:{port}"

    @property
    def counters(self) -> dict:
        return self.httpd.counters

    def __enter__(self) -> "TestServer":
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
