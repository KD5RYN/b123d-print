"""Signed-link uploads (/upload/, #132): streamed to a hidden temp file and renamed into place,
nothing left behind when too large, refused or cut off, and a cap on uploads at once."""

import asyncio
import os
import re
import time
from urllib.parse import urlsplit

import pytest

from b123d_print import links, refs

SECRET = b"k" * 32


def stl(triangles: int) -> bytes:
    """A binary STL of `triangles` (zero) triangles: right size and header, nothing to build."""
    return b"\0" * 80 + triangles.to_bytes(4, "little") + b"\0" * (50 * triangles)


@pytest.fixture
def srv(tmp_path, monkeypatch):
    from b123d_print import mcp_server as srv

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    ws = tmp_path / "ws"
    (ws / "parts" / "rx" / "ref").mkdir(parents=True)
    (ws / "b123d-print.toml").write_text("", encoding="utf-8")
    monkeypatch.setitem(srv.STATE, "root", ws)
    monkeypatch.setitem(srv.STATE, "transport", "http")
    monkeypatch.setitem(srv.STATE, "link_secret", SECRET)
    monkeypatch.setitem(srv.STATE, "uploads", __import__("collections").Counter())
    srv.ws = ws
    srv.ref = ws / "parts" / "rx" / "ref"
    srv.app = srv.http_app("127.0.0.1", None)
    return srv


def link(name: str, overwrite: bool = False, by: str = "") -> str:
    return links.sign_upload(SECRET, "_", f"parts/rx/ref/{name}", 60, overwrite, by=by)[0]


def leftovers(d) -> list[str]:
    return sorted(n for n in os.listdir(d) if n.startswith("."))


async def put(app, url, chunks, *, content_length=True, disconnect_after=None, gate=None, seen=None):
    """PUT `chunks` to `url` through the whole ASGI app (TokenAuth and its body guard included).
    content_length=False sends it chunked (no Content-Length). disconnect_after=n: the client
    goes away after n chunks. gate: an asyncio.Event the body waits for after its first chunk.
    seen(n): called before chunk n is handed over. Returns (status, body text)."""
    body = list(chunks)
    sent, start, out = [0], {}, []
    u = urlsplit(url)
    headers = [(b"host", b"127.0.0.1")]
    headers.append((b"content-length", str(sum(map(len, body))).encode()) if content_length
                   else (b"transfer-encoding", b"chunked"))

    async def receive():
        n = sent[0]
        if seen:
            seen(n)
        if n == 1 and gate is not None:
            await gate.wait()
        if (disconnect_after is not None and n >= disconnect_after) or n >= len(body):
            return {"type": "http.disconnect"}
        sent[0] += 1
        return {"type": "http.request", "body": body[n], "more_body": n + 1 < len(body)}

    async def send(msg):
        if msg["type"] == "http.response.start":
            start.update(msg)
        elif msg["type"] == "http.response.body":
            out.append(msg.get("body", b""))

    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "PUT", "scheme": "http",
             "path": u.path, "raw_path": u.path.encode(), "query_string": u.query.encode(), "root_path": "",
             "headers": headers, "client": ("127.0.0.1", 1), "server": ("127.0.0.1", 8000)}
    await app(scope, receive, send)
    return start.get("status"), b"".join(out).decode()


def run(coro):
    return asyncio.run(coro)


def pieces(data: bytes, size: int) -> list[bytes]:
    return [data[i:i + size] for i in range(0, len(data), size)]


def test_streamed_upload_goes_to_a_hidden_temp_file_first(srv, monkeypatch):
    monkeypatch.setattr(srv, "UPLOAD_FLUSH", 64 * 1024)
    data = stl(40_000)  # 2 MB
    during = []

    def seen(n):  # mid-body: part of the file is on disk under a hidden name, nothing under the real one
        if n == 20:
            tmp = leftovers(srv.ref)
            during.append((tmp, os.path.getsize(srv.ref / tmp[0]) if tmp else 0, (srv.ref / "s.stl").exists()))

    for chunked in (False, True):
        name = f"s{int(chunked)}.stl"
        st, msg = run(put(srv.app, link(name), pieces(data, 32 * 1024), content_length=not chunked, seen=seen))
        assert st == 201 and f"stored parts/rx/ref/{name} ({len(data)} bytes)" in msg
        assert (srv.ref / name).read_bytes() == data
        assert leftovers(srv.ref) == []  # the temp file was renamed, nothing else stays
    assert len(during) == 2
    for tmp, size, final in during:
        assert re.fullmatch(r"\.s[01]\.stl\.[0-9a-f]{8}\.part", tmp[0]) and size >= 64 * 1024 and not final
    assert refs.listing(srv.ws, "parts", "rx") == ["s0.stl", "s1.stl"]  # temp files never listed
    assert not srv.STATE["uploads"]  # the slots are given back


def test_too_large_leaves_nothing(srv, monkeypatch):
    monkeypatch.setattr(refs, "MAX_BYTES", 100_000)
    monkeypatch.setattr(srv, "UPLOAD_FLUSH", 16 * 1024)
    data = stl(4000)  # 200 kB
    # Content-Length over the limit: refused before any of the body is stored
    st, msg = run(put(srv.app, link("big.stl"), pieces(data, 8192)))
    assert st == 413 and "too large" in msg
    # chunked (no Content-Length): refused when the limit is passed, after some of it was on disk
    st, msg = run(put(srv.app, link("big.stl"), pieces(data, 8192), content_length=False))
    assert st == 413 and "too large" in msg
    assert os.listdir(srv.ref) == []
    assert not srv.STATE["uploads"]


def test_interrupted_upload_leaves_nothing(srv, monkeypatch):
    monkeypatch.setattr(srv, "UPLOAD_FLUSH", 16 * 1024)
    data = stl(4000)
    for chunked in (False, True):
        st, _ = run(put(srv.app, link("cut.stl"), pieces(data, 8192), content_length=not chunked, disconnect_after=10))
        assert st in (None, 400)  # nobody is left to read a reply
        assert os.listdir(srv.ref) == []
    assert not srv.STATE["uploads"]
    # the same link still works afterwards
    st, _ = run(put(srv.app, link("cut.stl"), pieces(data, 8192)))
    assert st == 201 and (srv.ref / "cut.stl").read_bytes() == data


def test_bad_content_leaves_nothing(srv):
    st, msg = run(put(srv.app, link("x.stl"), [b"#!/bin/sh\n", b"rm -rf /\n"]))
    assert st == 400 and "not an STL" in msg
    st, msg = run(put(srv.app, link("e.stl"), [b""]))
    assert st == 400 and "empty" in msg
    assert os.listdir(srv.ref) == []


def test_upload_caps_per_client_and_in_total(srv, monkeypatch):
    monkeypatch.setitem(srv.STATE, "client_uploads", 2)
    monkeypatch.setitem(srv.STATE, "max_uploads", 3)
    data = stl(1000)
    body = pieces(data, 10_000)

    async def go():
        gate = asyncio.Event()
        held = [asyncio.create_task(put(srv.app, link(f"a{i}.stl", by="alice"), body, gate=gate)) for i in range(2)]
        await asyncio.sleep(0.2)
        assert srv.STATE["uploads"] == {"token:alice": 2}
        alice3 = await put(srv.app, link("a3.stl", by="alice"), body)  # her third: refused at once
        held.append(asyncio.create_task(put(srv.app, link("b0.stl", by="bob"), body, gate=gate)))
        await asyncio.sleep(0.2)
        bob2 = await put(srv.app, link("b1.stl", by="bob"), body)  # bob has room, the server has not
        gate.set()
        return alice3, bob2, await asyncio.gather(*held)

    (st3, msg3), (stb, msgb), done = run(go())
    assert st3 == 429 and "server busy: you have 2 uploads running" in msg3 and "at most 2 per client" in msg3
    assert stb == 503 and "server busy: 3 uploads are running" in msgb
    assert [s for s, _ in done] == [201, 201, 201]
    assert sorted(os.listdir(srv.ref)) == ["a0.stl", "a1.stl", "b0.stl"]  # nothing of the refused ones
    assert not srv.STATE["uploads"]
    monkeypatch.setitem(srv.STATE, "client_uploads", 0)  # 0 = no cap
    monkeypatch.setitem(srv.STATE, "max_uploads", 0)
    srv.STATE["uploads"]["token:alice"] = 50
    assert run(put(srv.app, link("a9.stl", by="alice"), body))[0] == 201


def test_cap_counts_only_signed_links(srv, monkeypatch):
    """A refused link takes no slot, and the token name in a link is covered by its signature."""
    monkeypatch.setitem(srv.STATE, "client_uploads", 1)
    srv.STATE["uploads"]["token:alice"] = 1
    data = stl(10)
    url = link("x.stl", by="alice")
    assert run(put(srv.app, url, [data]))[0] == 429
    for forged in (url.replace("by=alice", "by=bob"), url.split("?")[0], url + "x", link("x.stl") + "?by=bob",
                   url.replace("by=alice", "by=../x")):
        assert run(put(srv.app, forged, [data]))[0] == 404, forged
    assert srv.STATE["uploads"] == {"token:alice": 1} and os.listdir(srv.ref) == []
    # a link from before 0.3.12 (no name) still works, counted against its workspace
    old = links.sign(SECRET, "_", "parts/rx/ref/old.stl", 60, purpose="put")[0]
    assert run(put(srv.app, old, [data]))[0] == 201


def test_upload_reference_names_the_token(srv, monkeypatch):
    monkeypatch.setattr(srv, "_token_name", lambda: "alice")
    url = re.search(r"'(?:http://[^/]+)?(/upload/\S+)'", srv.upload_reference("rx", "t.stl")).group(1)
    assert url.endswith("/parts/rx/ref/t.stl?by=alice")
    seen = {}
    real = srv._upload_refusal
    monkeypatch.setattr(srv, "_upload_refusal", lambda c: seen.setdefault("client", c) and real(c))
    assert run(put(srv.app, url, [stl(10)]))[0] == 201 and seen["client"] == "token:alice"


def test_overwrite_only_with_a_put_overwrite_link(srv):
    old, new = stl(10), stl(20)
    (srv.ref / "o.stl").write_bytes(old)
    st, msg = run(put(srv.app, link("o.stl"), pieces(new, 100)))
    assert st == 409 and "already exists" in msg
    assert (srv.ref / "o.stl").read_bytes() == old and leftovers(srv.ref) == []
    st, _ = run(put(srv.app, link("o.stl", overwrite=True), pieces(new, 100)))
    assert st == 201 and (srv.ref / "o.stl").read_bytes() == new and leftovers(srv.ref) == []


def test_symlinks_refused(srv, tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    (srv.ref / "l.stl").symlink_to(outside / "t.stl")
    assert run(put(srv.app, link("l.stl", overwrite=True), [stl(10)]))[0] == 400
    assert not (outside / "t.stl").exists()
    (srv.ref / "l.stl").unlink()
    os.rmdir(srv.ref)
    (srv.ws / "parts" / "rx" / "ref").symlink_to(outside)
    assert run(put(srv.app, link("x.stl"), [stl(10)]))[0] == 400
    assert os.listdir(outside) == []


# --- refs.Staged ---------------------------------------------------------------------------------


def test_staged_commit_never_replaces_a_file_that_appeared(tmp_path):
    ws = tmp_path / "ws"
    s = refs.Staged(ws, "parts", "rx", "r.stl")
    s.write(stl(10))
    (ws / "parts" / "rx" / "ref" / "r.stl").write_bytes(b"theirs")  # another upload finished first
    with pytest.raises(refs.RefError, match="already exists"):
        s.commit()
    assert (ws / "parts" / "rx" / "ref" / "r.stl").read_bytes() == b"theirs"
    assert leftovers(ws / "parts" / "rx" / "ref") == []


def test_staged_without_commit_leaves_nothing(tmp_path):
    ws = tmp_path / "ws"
    with pytest.raises(RuntimeError):
        with refs.Staged(ws, "parts", "rx", "r.stl") as s:
            s.write(b"solid x\n")
            assert len(leftovers(ws / "parts" / "rx" / "ref")) == 1
            raise RuntimeError("cut off")
    assert os.listdir(ws / "parts" / "rx" / "ref") == []


def test_staged_sniffs_the_whole_file(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    data = stl(30)
    with refs.Staged(ws, "parts", "rx", "w.stl") as s:  # in pieces smaller than the header
        for p in pieces(data, 7):
            s.write(p)
        s.commit()
    assert (ws / "parts" / "rx" / "ref" / "w.stl").read_bytes() == data
    with refs.Staged(ws, "parts", "rx", "short.stl") as s:  # a binary STL cut short is not one
        s.write(data[:-50])
        with pytest.raises(refs.RefError, match="not an STL"):
            s.commit()
    monkeypatch.setattr(refs, "MAX_BYTES", 100)
    with refs.Staged(ws, "parts", "rx", "big.stl") as s:
        s.write(b"solid " + b"x" * 90)
        with pytest.raises(refs.TooLarge):
            s.write(b"y" * 10)
    assert sorted(os.listdir(ws / "parts" / "rx" / "ref")) == ["w.stl"]


def test_stale_temp_files_are_swept(tmp_path):
    ref = tmp_path / "ws" / "parts" / "rx" / "ref"
    ref.mkdir(parents=True)
    stale, fresh, other = ref / ".a.stl.00000000.part", ref / ".b.stl.11111111.part", ref / ".keep"
    for p in (stale, fresh, other):
        p.write_bytes(b"x")
    old = time.time() - refs.STALE_TMP_S - 60
    os.utime(stale, (old, old))
    os.utime(other, (old, old))
    with refs.Staged(tmp_path / "ws", "parts", "rx", "n.stl"):
        pass
    assert sorted(os.listdir(ref)) == [".b.stl.11111111.part", ".keep"]
