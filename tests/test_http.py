"""HTTP mode: startup refusals and the token wrapper (the full flow is in tests/mcp_smoke.py --http)."""

import asyncio
import os
import subprocess
import sys

from b123d_print import tokens
from b123d_print.mcp_server import TokenAuth


def run_server(*args, **env):
    e = {k: v for k, v in os.environ.items() if not k.startswith("B123D_PRINT_TOKEN")}
    return subprocess.run([sys.executable, "-m", "b123d_print.mcp_server", "--transport", "http", "--port", "1", *args],
                          env={**e, **env}, capture_output=True, text=True, encoding="utf-8", timeout=60)


def test_http_needs_a_token():
    r = run_server()
    assert r.returncode != 0 and "needs a token" in r.stderr


def test_http_refuses_a_short_token():
    r = run_server(B123D_PRINT_TOKEN="short")
    assert r.returncode != 0 and "too short" in r.stderr


SEEN = {}


async def inner(scope, receive, send):
    SEEN.clear()
    SEEN.update(scope.get("state", {}))
    await send({"type": "http.response.start", "status": 200, "headers": []})


def call(app, path, headers=(), query=b""):
    sent = []

    async def go():
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(msg):
            sent.append(msg)

        await app({"type": "http", "method": "POST", "path": path, "query_string": query, "headers": list(headers),
                   "client": ("127.0.0.1", 1)}, receive, send)

    asyncio.run(go())
    return sent[0].get("status") if sent else None


def bearer(t):
    return [(b"authorization", b"Bearer " + t.encode())]


def test_token_wrapper():
    app = TokenAuth(inner, tokens.Store(None, "s3cret-token-0123456789"))
    assert call(app, "/mcp") == 401
    assert call(app, "/mcp", [(b"authorization", b"Bearer wrong")]) == 401
    assert call(app, "/mcp", [(b"authorization", b"Basic s3cret-token-0123456789")]) == 401
    assert call(app, "/mcp", bearer("s3cret-token-0123456789")) == 200 and SEEN["b123d_token"] == "default"
    assert call(app, "/mcp", [(b"authorization", b"bearer s3cret-token-0123456789")]) == 200
    assert call(app, "/health") == 200


def test_named_tokens_and_workspaces(tmp_path, capsys):
    p = tmp_path / "tokens.toml"
    grok, mac = tokens.generate(), tokens.generate()
    tokens.write(p, {"grok": tokens.Token("grok", tokens.digest(grok), ["grok-*"]),
                     "mac": tokens.Token("mac", tokens.digest(mac), ["mac-jon"])}, "s")
    app = TokenAuth(inner, tokens.Store(p))
    assert call(app, "/mcp", bearer(grok), b"workspace=grok-1") == 200 and SEEN["b123d_token"] == "grok"
    assert call(app, "/mcp", bearer(grok), b"workspace=penguin-jon") == 403
    assert call(app, "/mcp", bearer(grok) + [(b"x-b123d-workspace", b"penguin-jon")]) == 403
    assert call(app, "/mcp", bearer(grok)) == 403  # a pattern: no default, and no root workspace
    assert call(app, "/mcp", bearer(mac)) == 200 and SEEN["b123d_workspace"] == "mac-jon"  # its one workspace
    assert call(app, "/mcp", bearer(mac), b"workspace=grok-1") == 403
    err = capsys.readouterr().err
    assert "grok POST /mcp ws=grok-1 -> 200" in err and "grok POST /mcp ws=penguin-jon -> 403" in err
    assert grok not in err and mac not in err


class FakeRequest:
    def __init__(self, headers, scheme="http", netloc="10.0.0.5:8000"):
        from types import SimpleNamespace

        self.headers = {k.lower(): v for k, v in headers.items()}
        self.url = SimpleNamespace(scheme=scheme, netloc=netloc)


def base_url(headers, public_url=None, allowed=()):
    from b123d_print import mcp_server as m

    old = dict(m.STATE)
    m.STATE.update(public_url=public_url, allowed_hosts=list(allowed))
    tok = m._REQUEST.set(FakeRequest(headers))
    try:
        return m._base_url()
    finally:
        m._REQUEST.reset(tok)
        m.STATE.clear()
        m.STATE.update(old)


def test_link_base_url():
    proxied = {"Host": "cad.example.com", "X-Forwarded-Host": "cad.example.com", "X-Forwarded-Proto": "https"}
    assert base_url(proxied, public_url="https://files.example.com") == "https://files.example.com"
    assert base_url({"Host": "10.0.0.5:8000"}) == "http://10.0.0.5:8000"  # direct: the address the client used
    assert base_url(proxied) == "http://cad.example.com"  # proxy headers ignored unless the host is allowed
    assert base_url(proxied, allowed=["cad.example.com"]) == "https://cad.example.com"
    assert base_url({**proxied, "X-Forwarded-Host": "evil.example"}, allowed=["cad.example.com"]) == "http://cad.example.com"
    assert base_url({**proxied, "X-Forwarded-Proto": "javascript"}, allowed=["cad.example.com"]) == "http://cad.example.com"


def test_bad_public_url_refused():
    r = run_server("--public-url", "cad.example.com", B123D_PRINT_TOKEN="a-long-enough-token-123")
    assert r.returncode != 0 and "--public-url must look like" in r.stderr


def guarded_call(app, path, chunks, headers=(), method="POST"):
    """Run app with a body arriving in `chunks`; returns the event order and the response start."""
    events, start = [], {}
    body = list(chunks)
    cl = sum(len(c) for c in body)

    async def go():
        async def receive():
            if not body:
                events.append("receive-after-end")
                return {"type": "http.disconnect"}
            c = body.pop(0)
            events.append(f"read {len(c)}")
            return {"type": "http.request", "body": c, "more_body": bool(body)}

        async def send(msg):
            if msg["type"] == "http.response.start":
                events.append("reply")
                start.update(msg)

        await app({"type": "http", "method": method, "path": path, "query_string": b"",
                   "headers": [(b"content-length", str(cl).encode()), *headers], "client": ("127.0.0.1", 1)},
                  receive, send)

    asyncio.run(go())
    return events, start


def test_early_replies_wait_for_the_body():
    """A reply that does not read the body (401, 403, a refused link) still drains it first:
    behind a proxy, replying mid-body made it drop the connection (about every other request)."""
    tok = "s3cret-token-0123456789"
    app = TokenAuth(inner, tokens.Store(None, tok))
    for headers in ([], bearer("wrong")):  # 401
        events, start = guarded_call(app, "/mcp", [b"x" * 10, b"y" * 10, b"z" * 10], headers)
        assert start["status"] == 401 and events == ["read 10", "read 10", "read 10", "reply"], events
    events, start = guarded_call(app, "/upload/ws/1.bad/up/x.stl", [b"a" * 5, b"b" * 5],
                                 method="PUT")  # the app (`inner`) answers without reading: the guard reads
    assert events == ["read 5", "read 5", "reply"] and start["status"] == 200, events


def test_drain_gives_up_on_a_big_body():
    from b123d_print import mcp_server as m

    app = TokenAuth(inner, tokens.Store(None, "s3cret-token-0123456789"))
    events, start = guarded_call(app, "/mcp", [b"x" * (m.DRAIN_LIMIT + 1)])  # announced too big: not read at all
    assert events == ["reply"] and (b"connection", b"close") in start["headers"], events


def test_no_reply_before_the_body_over_a_real_socket():
    """The failure as a proxy saw it, against uvicorn and the real app: the 401 (and a refused upload
    link) must not come back while the body is still on its way, and the connection stays usable."""
    import socket
    import threading
    import time

    import uvicorn

    from b123d_print.mcp_server import http_app

    srv = uvicorn.Server(uvicorn.Config(http_app("127.0.0.1", tokens.Store(None, "s3cret-token-0123456789")),
                                        host="127.0.0.1", port=0, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    try:
        for _ in range(500):
            if srv.started:
                break
            time.sleep(0.01)
        port = srv.servers[0].sockets[0].getsockname()[1]
        body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
        for head in (b"POST /mcp HTTP/1.1\r\nHost: 127.0.0.1\r\nAuthorization: Bearer wrong\r\n"
                     b"Content-Type: application/json\r\n",
                     b"PUT /upload/ws/1.bad/up/x.stl HTTP/1.1\r\nHost: 127.0.0.1\r\n"):
            with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
                s.sendall(head + b"Content-Length: %d\r\n\r\n" % len(body))
                s.settimeout(0.5)
                try:
                    early = s.recv(65536)
                except TimeoutError:
                    early = b""
                assert early == b"", f"replied before the body arrived: {early[:60]!r}"
                s.settimeout(5)
                s.sendall(body + b"GET /health HTTP/1.1\r\nHost: 127.0.0.1\r\n\r\n")
                data = b""
                while b'"status"' not in data:
                    c = s.recv(65536)
                    assert c, f"connection closed after the early reply: {data[:200]!r}"
                    data += c
                assert data.startswith((b"HTTP/1.1 401", b"HTTP/1.1 404")) and b"HTTP/1.1 200" in data, data[:300]
    finally:
        srv.should_exit = True
        t.join(10)


def test_workspace_named_once_and_used_as_authorized(tmp_path):
    """The workspace is resolved once, in TokenAuth, and the tools use exactly that one: a request
    naming it twice (or differently in the query and the header) is refused, so a token for one
    workspace can never run in another (a repeated ?workspace= used to pass auth on the first value
    and run in the last)."""
    from types import SimpleNamespace

    from b123d_print import mcp_server as m

    p = tmp_path / "tokens.toml"
    alice, bob = tokens.generate(), tokens.generate()
    tokens.write(p, {"alice": tokens.Token("alice", tokens.digest(alice), ["alice"]),
                     "bob": tokens.Token("bob", tokens.digest(bob), ["bob"])}, "s")
    app = TokenAuth(inner, tokens.Store(p))
    assert call(app, "/mcp", bearer(alice), b"workspace=alice") == 200 and SEEN["b123d_workspace"] == "alice"
    assert call(app, "/mcp", bearer(alice), b"workspace=alice&workspace=bob") == 400
    assert call(app, "/mcp", bearer(alice), b"workspace=alice&workspace=") == 400
    assert call(app, "/mcp", bearer(alice), b"workspace=bob&workspace=alice") == 400
    assert call(app, "/mcp", bearer(alice) + [(b"x-b123d-workspace", b"bob")], b"workspace=alice") == 400
    assert call(app, "/mcp", bearer(alice) + [(b"x-b123d-workspace", b"alice")] * 2) == 400
    assert call(app, "/mcp", bearer(alice) + [(b"x-b123d-workspace", b"alice")], b"workspace=alice") == 200
    assert call(app, "/mcp", bearer(alice)) == 200 and SEEN["b123d_workspace"] == "alice"  # its one workspace

    # the tools read the workspace TokenAuth put in the scope, never the query string again
    seen = {}

    async def call_next(ctx):
        seen["ws"] = m._WORKSPACE.get()
        return {}

    req = SimpleNamespace(query_params={"workspace": "bob"}, headers={}, scope={"state": {"b123d_workspace": "alice"}})
    asyncio.run(m._request_workspace(SimpleNamespace(request=req), call_next))
    assert seen["ws"] == "alice"
