"""HTTP mode: startup refusals and the token wrapper (the full flow is in tests/mcp_smoke.py --http)."""

import asyncio
import os
import subprocess
import sys

from b123d_print.mcp_server import RequireToken


def run_server(*args, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("B123D_PRINT_TOKEN")}
    return subprocess.run([sys.executable, "-m", "b123d_print.mcp_server", "--transport", "http", "--port", "1", *args],
                          env={**e, **env}, capture_output=True, text=True, timeout=60)


def test_http_needs_a_token():
    r = run_server()
    assert r.returncode != 0 and "needs a token" in r.stderr


def test_http_refuses_a_short_token():
    r = run_server(B123D_PRINT_TOKEN="short")
    assert r.returncode != 0 and "too short" in r.stderr


def call(app, path, headers=()):
    sent = []

    async def go():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            sent.append(msg)

        await app({"type": "http", "path": path, "headers": list(headers)}, receive, send)

    asyncio.run(go())
    return sent[0].get("status") if sent else None


def test_token_wrapper():
    async def inner(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})

    app = RequireToken(inner, "s3cret-token-0123456789")
    assert call(app, "/mcp") == 401
    assert call(app, "/mcp", [(b"authorization", b"Bearer wrong")]) == 401
    assert call(app, "/mcp", [(b"authorization", b"Basic s3cret-token-0123456789")]) == 401
    assert call(app, "/mcp", [(b"authorization", b"Bearer s3cret-token-0123456789")]) == 200
    assert call(app, "/mcp", [(b"authorization", b"bearer s3cret-token-0123456789")]) == 200
    assert call(app, "/health") == 200
