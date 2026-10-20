"""Remote file handoff (download_part, zip links, pull --tree) and workspace retention."""

import io
import os
import time
import zipfile
from pathlib import Path

import anyio
import pytest

from b123d_print import handoff, links, tokens

SCRIPT = '''VARIANTS = {"": {}, "140": dict(W=140.0), "140_tall": dict(W=140.0, H=9.0)}
def build(d): ...
'''


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A workspace with one part: its script, out/ files of three variants, a reference model."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    w = tmp_path / "ws"
    part = w / "parts" / "box"
    (part / "out").mkdir(parents=True)
    (part / "ref").mkdir()
    (w / "b123d-print.toml").write_text("", encoding="utf-8")
    (part / "box.py").write_text(SCRIPT, encoding="utf-8", newline="")
    files = {"box.3mf": b"std-3mf", "box.stl": b"std-stl", "box_xz0.png": b"std-png", "box_lid.stl": b"std-lid",
             "box_140.3mf": b"140-3mf", "box_140_xz0.png": b"140-png",
             "box_140_tall.3mf": b"tall-3mf", ".hidden.stl": b"no"}
    for n, data in files.items():
        (part / "out" / n).write_bytes(data)
    (part / "ref" / "orig.stl").write_bytes(b"solid ref")
    (part / "out" / "sub").mkdir()
    (part / "out" / "sub" / "deep.stl").write_bytes(b"deep")
    (tmp_path / "secret.stl").write_bytes(b"outside")
    try:
        os.symlink(tmp_path / "secret.stl", part / "out" / "link.stl")
        os.symlink(tmp_path / "secret.stl", part / "ref" / "link.stl")
    except OSError:  # Windows without symlink rights: nothing to refuse
        pass
    return w


def rels(files):
    return sorted(r for r, _ in files)


def test_part_files_layout_and_filters(ws):
    everything = handoff.part_files(ws, "parts", "box")
    assert rels(everything) == ["box.py", "out/box.3mf", "out/box.stl", "out/box_140.3mf", "out/box_140_tall.3mf",
                                "out/box_140_xz0.png", "out/box_lid.stl", "out/box_xz0.png", "ref/orig.stl"]
    assert rels(handoff.part_files(ws, "parts", "box", formats=["3mf"])) == [
        "box.py", "out/box.3mf", "out/box_140.3mf", "out/box_140_tall.3mf", "ref/orig.stl"]
    assert rels(handoff.part_files(ws, "parts", "box", variant="standard")) == [
        "box.py", "out/box.3mf", "out/box.stl", "out/box_lid.stl", "out/box_xz0.png", "ref/orig.stl"]
    assert rels(handoff.part_files(ws, "parts", "box", variant="140")) == [
        "box.py", "out/box_140.3mf", "out/box_140_xz0.png", "ref/orig.stl"]  # not 140_tall: the longest key wins
    assert rels(handoff.part_files(ws, "parts", "box", variant="140_tall", formats=["3mf"])) == [
        "box.py", "out/box_140_tall.3mf", "ref/orig.stl"]
    with pytest.raises(handoff.HandoffError, match="no variant 'big'"):
        handoff.part_files(ws, "parts", "box", variant="big")
    with pytest.raises(handoff.HandoffError, match="no part"):
        handoff.part_files(ws, "parts", "nosuch")
    with pytest.raises(handoff.HandoffError, match="no part"):
        handoff.part_files(ws, "parts", "../ws")


def test_variants_must_be_literal(ws):
    (ws / "parts/box/box.py").write_text("VARIANTS = {k: {} for k in 'ab'}\n", encoding="utf-8", newline="")
    with pytest.raises(handoff.HandoffError, match="leave variant out"):
        handoff.part_files(ws, "parts", "box", variant="a")
    assert handoff.part_files(ws, "parts", "box")  # unfiltered still works
    (ws / "parts/box/box.py").write_text("x = 1\n", encoding="utf-8", newline="")  # no VARIANTS: just the standard one
    assert handoff.variant_keys(ws / "parts/box/box.py") == [""]


def test_zip_has_the_local_layout(ws):
    data = handoff.zip_bytes(handoff.part_files(ws, "parts", "box"), "parts/box")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        got = {n: zf.read(n) for n in zf.namelist()}
    assert got["parts/box/box.py"] == SCRIPT.encode()
    assert got["parts/box/out/box_140.3mf"] == b"140-3mf" and got["parts/box/ref/orig.stl"] == b"solid ref"
    assert all(n.startswith("parts/box/") and ".." not in n and "/." not in n for n in got)
    assert not any("link" in n or "deep" in n or "hidden" in n for n in got)


@pytest.mark.parametrize("rel,ok", [("box.py", True), ("out/a.stl", True), ("ref/b.stl", True), ("out/sub/x", False),
                                    ("../x", False), ("/etc/x", False), ("other/x", False), (".x", False),
                                    ("out/.x", False), ("out\\x", False), ("C:x", False), ("", False)])
def test_safe_rel(rel, ok):
    assert handoff.safe_rel(rel) is ok


# --- the zip link, through the HTTP app -------------------------------------------------------------


@pytest.fixture
def http(tmp_path, monkeypatch):
    """The HTTP app over a server root with two workspaces, each with a part."""
    from b123d_print import mcp_server as m

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    root = tmp_path / "srv"
    for ws in ("alice", "bob"):
        part = root / "workspaces" / ws / "parts" / "box"
        (part / "out").mkdir(parents=True)
        (root / "workspaces" / ws / "b123d-print.toml").write_text("", encoding="utf-8")
        (part / "box.py").write_text(SCRIPT, encoding="utf-8", newline="")
        (part / "out" / "box.3mf").write_bytes(f"{ws}-3mf".encode())
        (part / "out" / "box_140.3mf").write_bytes(f"{ws}-140".encode())
    old = dict(m.STATE)
    m.STATE.update(root=root, transport="http", link_secret=b"k" * 32, link_ttl=60.0)
    from starlette.testclient import TestClient

    yield TestClient(m.http_app("127.0.0.1", tokens.Store(None, "s3cret-token-0123456789"))), root
    m.STATE.clear()
    m.STATE.update(old)


def unzip(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def test_zip_link(http):
    client, root = http
    url, _ = links.sign_zip(b"k" * 32, "alice", "box", "", 60)
    r = client.get(url)  # no bearer token
    assert r.status_code == 200 and r.headers["content-type"] == "application/zip"
    assert 'filename="box.zip"' in r.headers["content-disposition"]
    assert unzip(r.content) == {"parts/box/box.py": SCRIPT.encode(), "parts/box/out/box.3mf": b"alice-3mf",
                                "parts/box/out/box_140.3mf": b"alice-140"}
    url, _ = links.sign_zip(b"k" * 32, "alice", "box", links.zip_query("140", "3mf"), 60)
    assert set(unzip(client.get(url).content)) == {"parts/box/box.py", "parts/box/out/box_140.3mf"}
    tok = url.split("/")[3]
    refused = {
        "workspace alice's link pointed at bob": url.replace("/zip/alice/", "/zip/bob/"),
        "the filter changed": url.replace("variant=140", "variant=standard"),
        "the filter dropped": url.split("?")[0],
        "another part": url.replace("/box.zip", "/other.zip"),
        "a download link's signature": f"/zip/alice/{links.sign(b'k' * 32, 'alice', 'box.zip', 60)[0].split('/')[3]}/box.zip",
        "tampered": url.replace(tok, tok[:-3] + "AAA"),
        "not a zip": url.replace("/box.zip", "/box.tar"),
    }
    for what, u in refused.items():
        assert client.get(u).status_code == 404, what
    expired, _ = links.sign_zip(b"k" * 32, "alice", "box", "", -60)
    r = client.get(expired)
    assert r.status_code == 410 and "expired" in r.text
    assert (root / "workspaces/alice" / handoff.LAST_USE).exists()  # a download counts as a use


# --- tool descriptions and results -------------------------------------------------------------------


def test_descriptions_carry_the_remote_guidance():
    from b123d_print.mcp_server import INSTRUCTIONS, mcp

    tools = {t.name: t.description for t in anyio.run(mcp.list_tools)}
    for name in ("export", "download_part", "render_preview", "section", "compare"):
        d = tools[name]
        assert "download_part" in d and "ssh" in d and "scp" in d and "temporary" in d, name
    assert "download_part" in tools["check"]
    assert "download_part" in INSTRUCTIONS and "scp" in INSTRUCTIONS and "parts/<name>/out/" in INSTRUCTIONS


def call(m, tool: str, ws: str | None, **kw):
    from b123d_print.mcp_server import _WORKSPACE

    tok = _WORKSPACE.set(ws)
    try:
        return getattr(m, tool)(**kw)
    finally:
        _WORKSPACE.reset(tok)


def test_download_part_results(http, monkeypatch):
    from b123d_print import mcp_server as m

    _, root = http
    monkeypatch.setitem(m.STATE, "public_url", "https://cad.example.com")
    res = call(m, "download_part", "alice", name="box", variant="140")
    t = res[0]
    assert "curl -fLo box.zip 'https://cad.example.com/zip/alice/" in t and "variant=140" in t
    assert "parts/box/box.py" in t and "parts/box/out/box_140.3mf" in t and "parts/box/out/box.3mf " not in t
    assert "deleted after 30 days unused" in t and "Do not use ssh/scp" in t and "unzip" in t
    assert str(root) not in t and "/work" not in t
    assert res[1].uri == "b123d-print://download/alice/box"
    emb = call(m, "download_part", "alice", name="box", embed=True)[2]
    import base64

    assert set(unzip(base64.b64decode(emb.resource.blob))) == {"parts/box/box.py", "parts/box/out/box.3mf",
                                                               "parts/box/out/box_140.3mf"}
    t = call(m, "download_part", "alice", name="box", embed=True)[0]
    assert "EMBEDDED" in t and "unzip -o <saved zip> -d <project folder>" in t
    monkeypatch.setattr(m, "EMBED_TOTAL", 10)
    res = call(m, "download_part", "alice", name="box", embed=True)
    assert len(res) == 2 and "not embedded" in res[0] and "formats=" in res[0]
    monkeypatch.setattr(m, "EMBED_TOTAL", 8_000_000)
    monkeypatch.setitem(m.STATE, "retention_days", 0.0)
    assert "not your copy" in call(m, "download_part", "alice", name="box")[0]
    monkeypatch.setitem(m.STATE, "transport", "stdio")
    monkeypatch.setitem(m.STATE, "root", root / "workspaces" / "alice")
    t = call(m, "download_part", None, name="box")[0]
    assert "already in the project folder" in t and "curl" not in t and "ssh/scp" not in t
    monkeypatch.setitem(m.STATE, "ssh_dest", "me@cad")
    t = call(m, "download_part", None, name="box", formats="3mf")[0]
    assert "b123d-print pull box --formats 3mf --from me@cad" in t and "parts/box/ref/" in t and "Do not use ssh/scp" in t
    assert str(root) not in t
    res = call(m, "download_part", None, name="box", embed=True)  # over SSH too: a sandboxed shell can't run pull
    assert "b123d-print pull box --from me@cad" in res[0] and "EMBEDDED" in res[0]
    assert set(unzip(base64.b64decode(res[1].resource.blob))) == {"parts/box/box.py", "parts/box/out/box.3mf",
                                                                  "parts/box/out/box_140.3mf"}


def test_next_step(http, monkeypatch):
    """Remote results that wrote the user's files end with the NEXT STEP: download_part, embed=True
    when the shell has no network; nothing over stdio."""
    from b123d_print import mcp_server as m

    _, root = http
    t = call(m, "_next_step", "alice", name="box")
    assert t.startswith("NEXT STEP: a part is not done until its files are on the user's machine")
    assert "download_part('box')" in t and "download_part('box', embed=True)" in t and "under the 8 MB" in t
    assert "curl" in t and "leave the files on the server" in t
    monkeypatch.setattr(m, "EMBED_TOTAL", 10)
    t = call(m, "_next_step", "alice", name="box")
    assert "over the" in t and "download_part('box', formats='3mf', embed=True)" in t
    monkeypatch.setitem(m.STATE, "ssh_dest", "me@cad")
    monkeypatch.setitem(m.STATE, "transport", "stdio")
    assert "b123d-print pull" in call(m, "_next_step", "alice", name="box")
    monkeypatch.setitem(m.STATE, "ssh_dest", None)
    assert call(m, "_next_step", "alice", name="box") == ""


def test_error_text_hides_server_paths(http):
    from b123d_print import mcp_server as m

    _, root = http
    tb = f'File "{root}/workspaces/alice/parts/box/box.py", line 3\nFile "{root}/x.py"'
    t = call(m, "_error_text", "alice", res={"error": "boom", "traceback": tb})
    assert str(root) not in t and 'File "parts/box/box.py"' in t


@pytest.mark.parametrize("windows", [False, True])
def test_hide_paths(windows):
    if windows:  # Windows-style paths, checked on every OS
        srv, ws = r"C:\Users\Runner\srv", r"C:\Users\Runner\srv\workspaces\alice"
        text = (r'File "C:\Users\Runner\srv/workspaces/alice/parts/box/box.py", line 3' "\n"
                r'File "c:\users\runner\SRV\workspaces\alice\parts\box\box.py"' "\n"
                r'File "\\?\C:\Users\Runner\srv\x.py"' "\n"
                r"use a path relative to C:\Users\Runner\srv\workspaces\alice" "\n"
                r"C:\Users\Runner\srvother\y.py")
        want = ('File "parts/box/box.py", line 3\n'
                r'File "parts\box\box.py"' "\n"
                'File "x.py"\nuse a path relative to .\n'
                r"C:\Users\Runner\srvother\y.py")
    else:
        srv, ws = "/work", "/work/workspaces/alice"
        text = ('File "/work/workspaces/alice/parts/box/box.py", line 3\nFile "/work/x.py"\n'
                "relative to /work/workspaces/alice\n/workshop/y.py /WORK/z.py")
        want = 'File "parts/box/box.py", line 3\nFile "x.py"\nrelative to .\n/workshop/y.py /WORK/z.py'
    assert handoff.hide_paths(text, [srv, ws], windows=windows) == want


def test_part_zip_resource_is_scoped(http):
    from mcp.server.mcpserver.exceptions import ResourceError

    from b123d_print import mcp_server as m

    data = call(m, "part_zip", "alice", workspace="alice", part="box")
    assert unzip(data)["parts/box/out/box.3mf"] == b"alice-3mf"
    with pytest.raises(ResourceError):
        call(m, "part_zip", "alice", workspace="bob", part="box")


# --- retention --------------------------------------------------------------------------------------


def make_ws(root: Path, name: str, age_days: float, now: float) -> Path:
    w = root / "workspaces" / name
    (w / "parts" / "p").mkdir(parents=True)
    (w / "parts" / "p" / "p.py").write_text("x", encoding="utf-8", newline="")
    t = now - age_days * 86400
    for dirpath, dirnames, filenames in os.walk(w):
        for n in dirnames + filenames:
            os.utime(os.path.join(dirpath, n), (t, t))
    os.utime(w, (t, t))
    return w


def test_retention(tmp_path):
    now = time.time()
    root = tmp_path / "srv"
    (root / "parts").mkdir(parents=True)
    old, recent, busy = (make_ws(root, n, a, now) for n, a in (("old", 31), ("recent", 2), ("busy", 40)))
    touched = make_ws(root, "touched", 45, now)
    handoff.touch(touched)  # used just now, though every file in it is old
    (root / "workspaces" / ".trash-gone-1234").mkdir()  # a removal cut short
    logged = []
    r = handoff.Retention(root, 30, log=logged.append)
    r.enter("busy")
    assert r.sweep(now) == ["old"]
    assert not old.exists() and recent.exists() and busy.exists() and touched.exists() and (root / "parts").exists()
    assert not (root / "workspaces" / ".trash-gone-1234").exists()
    assert any("removed workspace old" in m for m in logged)
    r.leave("busy")
    assert r.sweep(now) == ["busy"]
    assert handoff.Retention(root, 0).sweep(now + 1e9) == []  # 0: never
    assert recent.exists()


def test_retention_through_requests(http):
    """A request marks its workspace used and holds it while it runs; the root workspace is never swept."""
    from b123d_print import mcp_server as m

    _, root = http
    now = time.time() + 40 * 86400
    m.STATE["retention"] = r = handoff.Retention(root, 30, log=lambda _: None)
    m._in_use("alice", True)
    assert r.sweep(now) == ["bob"]  # alice: a request is in flight
    m._in_use("alice", False)
    assert (root / "workspaces/alice" / handoff.LAST_USE).exists()
    assert r.sweep(now) == ["alice"] and root.exists()


def test_write_part_stores_the_script_exactly(http):
    """What the agent sends is what is stored, served and brought home, on every OS (no CRLF added on Windows)."""
    from b123d_print import mcp_server as m

    _, root = http
    code = "x = 1\ny = 2\r\nz = 3\n"
    assert "Saved" in call(m, "write_part", "alice", name="box", code=code)
    p = root / "workspaces/alice/parts/box/box.py"
    assert p.read_bytes() == code.encode() and call(m, "read_part", "alice", name="box") == code
    assert unzip(call(m, "part_zip", "alice", workspace="alice", part="box"))["parts/box/box.py"] == code.encode()
