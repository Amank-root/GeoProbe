"""Shared pytest fixtures.

Two hard constraints shape this file: **no network** and **no API key**. Anything
that needs a socket gets an in-process one on localhost, and anything that needs
an LLM gets a recorded cassette.
"""

from __future__ import annotations

import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent))

from fixtures.site import FixtureSite

FIXTURE_DIR = Path(__file__).parent / "fixtures"


class _Handler(BaseHTTPRequestHandler):
    site: FixtureSite

    def do_GET(self) -> None:
        host = self.headers.get("Host", "127.0.0.1")
        origin = f"http://{host}"
        status, headers, body = self.site.get(
            self.path, self.headers.get("User-Agent", ""), origin=origin
        )
        self.send_response(status)
        for key, value in headers.items():
            self.send_header(key, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # keep pytest output clean


@pytest.fixture
def serve_site(serve):  # type: ignore[no-untyped-def]
    """Serve a named FixtureSite and yield its base URL."""
    return serve


@pytest.fixture
def serve():  # type: ignore[no-untyped-def]
    """Serve any FixtureSite on localhost and yield its base URL."""
    sites: list[FixtureSite] = []

    def _serve(site: FixtureSite) -> str:
        sites.append(site)
        handler = type("BoundHandler", (_Handler,), {"site": site})
        server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        host, port = server.server_address[:2]
        servers.append(server)
        return f"http://{host}:{port}"

    servers: list[ThreadingHTTPServer] = []
    try:
        yield _serve
    finally:
        for server in servers:
            server.shutdown()
            server.server_close()


@pytest.fixture
def allow_private_config():  # type: ignore[no-untyped-def]
    """A Config that permits localhost targets, for tests that use the real
    fetch client against the in-process fixture server."""
    from geoctl.config import Config

    config = Config()
    config.fetch.allow_private = True
    config.fetch.timeout = 5.0
    return config


@pytest.fixture
def cache(tmp_path: Path):  # type: ignore[no-untyped-def]
    from geoctl.cache import Cache

    store = Cache(tmp_path / "cache")
    yield store
    store.close()