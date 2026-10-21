"""The 3D view: signed /view/ links (tampering, expiry, other workspaces, traversal), the page's CSP
and headers, the offline HTML, the GLB, and the vendored three.js (its license and provenance)."""

import base64
import hashlib
import json
import os
import re
import struct
import time
from pathlib import Path

import pytest

from b123d_print import links, tokens, viewer
from b123d_print.cli import init_workspace

TOKEN = "s3cret-token-0123456789"
SECRET = links.derive_secret(TOKEN)
DATA = Path(viewer.__file__).parent / "data" / "viewer"
GLB = b"glTF\x02\x00\x00\x00" + b"\x00" * 64  # the routes serve bytes; they never parse the model


@pytest.fixture
def server(tmp_path, monkeypatch):
    """The HTTP app (TokenAuth + routes) over a root workspace and two named ones, a and b,
    each with parts/p/out/p_view.glb."""
    from starlette.testclient import TestClient

    from b123d_print import mcp_server as ms

    for ws in (tmp_path, tmp_path / "workspaces" / "a", tmp_path / "workspaces" / "b"):
        init_workspace(ws)
        (ws / "parts/p/out").mkdir(parents=True)
        (ws / "parts/p/p.py").write_text("# script\n", encoding="utf-8")
        (ws / "parts/p/out/p_view.glb").write_bytes(GLB + ws.name.encode())
    monkeypatch.setitem(ms.STATE, "root", tmp_path)
    monkeypatch.setitem(ms.STATE, "transport", "http")
    monkeypatch.setitem(ms.STATE, "link_secret", SECRET)
    app = ms.http_app("127.0.0.1", tokens.Store(None, TOKEN))
    return TestClient(app), tmp_path


def view(ws="a", part="p", stem="p_view", ttl=600.0, now=None):
    return links.sign_view(SECRET, ws, part, stem, ttl, now)[0]


def test_view_link_page_and_model(server):
    client, root = server
    url = view()
    r = client.get(url)  # no Authorization header: the signature is the credential
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert r.content == viewer.served_page()
    g = client.get(url + ".glb")
    assert g.status_code == 200 and g.headers["content-type"] == "model/gltf-binary"
    assert g.content == (root / "workspaces/a/parts/p/out/p_view.glb").read_bytes()
    assert g.headers["x-content-type-options"] == "nosniff" and "attachment" in g.headers["content-disposition"]
    # the root workspace has its own links ("_")
    assert client.get(view("_") + ".glb").content == (root / "parts/p/out/p_view.glb").read_bytes()


def test_view_page_headers_and_csp(server):
    client, _ = server
    h = client.get(view()).headers
    csp = {d.split()[0]: d.split()[1:] for d in (x.strip() for x in h["content-security-policy"].split(";"))}
    assert csp["default-src"] == ["'none'"] and csp["script-src"] == ["'self'"] and csp["connect-src"] == ["'self'"]
    assert csp["style-src"] == ["'self'"] and csp["frame-ancestors"] == ["'none'"] and csp["base-uri"] == ["'none'"]
    assert "unsafe" not in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "no-referrer"
    assert h["x-frame-options"] == "DENY" and "no-store" in h["cache-control"]


def test_view_page_runs_no_inline_code():
    page = viewer.served_page().decode()
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", page, re.S)
    assert scripts and all('src="' in attrs and not body.strip() for attrs, body in scripts)
    assert not re.search(r"\son\w+=", page), "no inline event handlers"
    assert "{{" not in page
    for ref in re.findall(r'(?:src|href)="([^"]+)"', page):
        assert ref.startswith(viewer.ASSET_PREFIX) and ref[len(viewer.ASSET_PREFIX):] in viewer.ASSETS


def test_viewer_js_never_turns_model_data_into_markup_or_code():
    js = (DATA / "viewer.js").read_text(encoding="utf-8")
    for bad in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "setAttribute(\"on"):
        assert bad not in js, bad
    assert "textContent = p.name" in js


@pytest.mark.parametrize("what", ["tampered", "longer expiry", "other workspace", "other stem", "other part",
                                  "files signature", "zip signature", "bad part name", "traversal"])
def test_view_link_refusals(server, what):
    client, _ = server
    url = view()
    _, _, ws, tok, part, stem = url.split("/")
    exp, sig = tok.split(".")
    bad = {
        "tampered": f"/view/{ws}/{exp}.{sig[:-2]}AA/{part}/{stem}",
        "longer expiry": f"/view/{ws}/{int(exp) + 3600}.{sig}/{part}/{stem}.glb",
        "other workspace": f"/view/b/{tok}/{part}/{stem}.glb",  # b has the same file: the link is bound to a
        "other stem": f"/view/{ws}/{tok}/{part}/p.glb",
        "other part": f"/view/{ws}/{tok}/q/{stem}.glb",
        # a download signature for the same path never opens a view (purposes differ), nor the other way round
        "files signature": f"/view/{ws}/{links.sign(SECRET, 'a', 'p/p_view', 600)[0].split('/')[3]}/{part}/{stem}",
        "zip signature": f"/view/{ws}/{links.sign_zip(SECRET, 'a', 'p', '', 600)[0].split('/')[3]}/{part}/{stem}",
        "bad part name": f"/view/{ws}/{tok}/..%2f..%2fp/{stem}.glb",
        "traversal": f"/view/{ws}/{tok}/{part}/..%2f..%2fp.glb",
    }[what]
    r = client.get(bad)
    assert r.status_code == 404, (what, r.status_code, r.text)
    if r.text != "Not Found":  # refused by the route, not unmatched by the router
        assert r.headers["x-content-type-options"] == "nosniff"


def test_view_signature_does_not_open_downloads(server):
    client, _ = server
    tok = view().split("/")[3]
    assert client.get(f"/files/a/{tok}/parts/p/out/p_view.glb").status_code == 404


def test_view_link_expiry(server):
    client, _ = server
    old = view(ttl=60, now=time.time() - 3600)
    for u in (old, old + ".glb"):
        r = client.get(u)
        assert r.status_code == 410 and "expired" in r.text


def test_view_link_serves_only_a_regular_glb_in_out(server):
    client, root = server
    out = root / "workspaces/a/parts/p/out"
    secret = root / "workspaces/a/b123d-print.toml"
    try:
        os.symlink(secret, out / "evil_view.glb")
    except (OSError, NotImplementedError):
        pytest.skip("no symlinks here")
    assert client.get(view(stem="evil_view") + ".glb").status_code == 404
    assert client.get(view(stem="evil_view")).status_code == 404  # no page for a model that is not servable
    (out / "p_view.glb").unlink()
    assert client.get(view()).status_code == 404


def test_view_assets(server):
    client, _ = server
    for name, mime in viewer.ASSETS.items():
        r = client.get(f"/view-assets/{name}")
        assert r.status_code == 200 and r.headers["content-type"] == mime and r.headers["x-content-type-options"] == "nosniff"
        assert r.content == (DATA / name).read_bytes()
    for name in ("vendor.json", "viewer.html", "..%2fviewer.py", "%2e%2e%2f%2e%2e%2fmcp_server.py"):
        assert client.get(f"/view-assets/{name}").status_code == 404, name


def test_view_needs_no_bearer_but_mcp_still_does(server):
    client, _ = server
    assert client.get(view()).status_code == 200
    assert client.post("/mcp", json={}).status_code == 401


def test_view_signature_never_logged(server, capsys):
    client, _ = server
    url = view()
    client.get(url)
    err = capsys.readouterr().err
    sig = url.split("/")[3].split(".")[1]
    assert "/view/a/.../p/p_view" in err and sig not in err


def test_view_link_from_export_text(monkeypatch, tmp_path):
    """export over HTTP: one link per variant, under --public-url, with the expiry."""
    from b123d_print import mcp_server as ms

    init_workspace(tmp_path)
    monkeypatch.setitem(ms.STATE, "root", tmp_path)
    monkeypatch.setitem(ms.STATE, "transport", "http")
    monkeypatch.setitem(ms.STATE, "public_url", "https://cad.example.com/pre")
    monkeypatch.setitem(ms.STATE, "link_secret", SECRET)
    (tmp_path / "parts/p/out/cad").mkdir(parents=True)
    (tmp_path / "parts/p/out/cad/p_view.glb").write_bytes(GLB)
    lines = ms._view_lines("p", [{"variant": "standard", "view": str(tmp_path / "parts/p/out/cad/p_view.glb")},
                                 {"variant": "big", "view_error": "this script has no assembly(d)"}])
    text = "\n".join(lines)
    m = re.search(r"\[standard\] (https://cad\.example\.com/pre/view/_/(\d+)\.[\w-]+/p/p_view)$", text, re.M)
    assert m and "no token" in text and "[big] no 3D view: this script has no assembly(d)" in text
    links.verify_view(SECRET, "_", m.group(1).split("/")[-3], "p", "p_view")


def test_export_trusts_no_view_path_from_the_build(monkeypatch, tmp_path):
    """stdio: export writes the offline HTML next to the GLB the build reports. That report comes
    from the process that ran the script, so a path outside the part's out/ is ignored: nothing
    outside it is read or written."""
    from b123d_print import mcp_server as ms

    init_workspace(tmp_path)
    (tmp_path / "parts/p/out/cad").mkdir(parents=True)
    (tmp_path / "parts/p/out/p_view.glb").write_bytes(GLB)  # the flat layout: not what export writes now
    good = tmp_path / "parts/p/out/cad/p_view.glb"
    viewer.write_glb([(__import__("build123d").Box(5, 5, 5), None, "p")], good)
    outside = tmp_path.parent / f"{tmp_path.name}-secret_view.glb"
    outside.write_bytes(GLB)
    (tmp_path / "parts/q/out").mkdir(parents=True)
    (tmp_path / "parts/q/out/q_view.glb").write_bytes(GLB)
    monkeypatch.setitem(ms.STATE, "root", tmp_path)
    monkeypatch.setitem(ms.STATE, "transport", "stdio")
    forged = [str(outside), str(tmp_path / "parts/q/out/q_view.glb"), str(tmp_path / "b123d-print.toml"),
              str(tmp_path / "parts/p/out/../../../b123d-print.toml"), str(tmp_path / "parts/p/out/p_view.glb"),
              str(tmp_path / "parts/p/out/cad/../../../q/out/q_view.glb")]
    lines = ms._view_lines("p", [{"variant": f"v{i}", "view": f} for i, f in enumerate(forged)]
                           + [{"variant": "standard", "view": str(good)}])
    assert len(lines) == 2 and lines[1].endswith("p_view.html") and (tmp_path / "parts/p/out/docs/p_view.html").is_file()
    assert not outside.with_suffix(".html").exists() and not (tmp_path / "parts/q/out/q_view.html").exists()
    outside.unlink()


# --- the offline page -----------------------------------------------------------------------


def _csp_hashes(page: str, directive: str) -> set[str]:
    csp = re.search(r'<meta http-equiv="Content-Security-Policy" content="([^"]+)">', page).group(1).replace("&#x27;", "'")
    d = next(x.strip() for x in csp.split(";") if x.strip().startswith(directive + " "))
    return set(re.findall(r"'sha256-([^']+)'", d))


def _sha(s: str) -> str:
    return base64.b64encode(hashlib.sha256(s.encode()).digest()).decode()


def test_offline_html_is_self_contained_and_strict():
    glb = GLB + b"<script>alert(1)</script>"
    page = viewer.offline_html(glb, 'bad "<name>" & co')
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", page, re.S)
    code = [body for attrs, body in scripts if "type=" not in attrs]
    data = [body for attrs, body in scripts if 'type="application/octet-stream"' in attrs]
    assert len(code) == 2 and len(data) == 1 and "<script src=" not in page and "<link" not in page
    assert {_sha(c) for c in code} == _csp_hashes(page, "script-src"), "the CSP allows exactly the inline scripts"
    css = re.search(r"<style>(.*?)</style>", page, re.S).group(1)
    assert _csp_hashes(page, "style-src") == {_sha(css)}
    assert "connect-src 'none'" in page.replace("&#x27;", "'") and "unsafe" not in page.split("</head>")[0]
    assert base64.b64decode(data[0]) == glb  # the model is inert data
    assert "<name>" not in page and "bad &quot;&lt;name&gt;&quot; &amp; co" in page  # the title is text
    assert "Permission is hereby granted" in code[0], "three.js's license notice travels with every copy"


def test_offline_html_refuses_code_that_would_escape_its_script():
    with pytest.raises(ValueError):
        viewer._inline_safe("var s = '</script><script>alert(1)'", "x")


# --- the vendored library -------------------------------------------------------------------


def test_vendored_three_matches_its_manifest_and_license():
    meta = viewer.vendor()
    bundle = (DATA / meta["file"]).read_bytes()
    assert hashlib.sha256(bundle).hexdigest() == meta["sha256"] and len(bundle) == meta["bytes"]
    assert meta["license"] == "MIT" and meta["integrity"].startswith("sha512-")
    lic = (DATA / "three-LICENSE.txt").read_text(encoding="utf-8")
    assert "The MIT License" in lic and "three.js authors" in lic
    head = bundle.decode()[:3000]
    assert head.startswith("/*!") and lic.strip() in head, "the full MIT notice heads the bundle"
    import tomllib

    pyproject = tomllib.loads((Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8"))
    assert "src/b123d_print/data/viewer/three-LICENSE.txt" in pyproject["project"]["license-files"]
    third = (Path(__file__).resolve().parents[1] / "THIRD_PARTY.md").read_text(encoding="utf-8")
    assert meta["package"].replace("@", " ") in third, "THIRD_PARTY.md names the vendored version"


def test_vendored_three_exports_what_viewer_js_uses():
    import importlib.util

    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("vendor_viewer", root / "tools" / "vendor_viewer.py")
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    meta = viewer.vendor()
    assert meta["exports"] == tool.EXPORTS and meta["package"] == f"three@{tool.THREE_VERSION}"
    exported = {n for names in tool.EXPORTS.values() for n in names}
    used = set(re.findall(r"\bT\.([A-Za-z]\w*)", (DATA / "viewer.js").read_text(encoding="utf-8")))
    assert used <= exported, f"viewer.js uses {used - exported}: add them to EXPORTS and run tools/vendor_viewer.py"


# --- the model ------------------------------------------------------------------------------


def _glb_json(path: Path) -> dict:
    data = path.read_bytes()
    assert data[:4] == b"glTF"
    n = struct.unpack("<I", data[12:16])[0]
    return json.loads(data[20:20 + n])


def test_write_glb_one_named_colored_node_per_piece(tmp_path):
    from build123d import Box, Cylinder, Pos

    items = [(Box(20, 10, 5), None, "base <b>"), (Pos(30, 0, 0) * Cylinder(4, 10), "#e0a030", "lid")]
    j = _glb_json(viewer.write_glb(items, tmp_path / "x_view.glb"))
    names = [n.get("name") for n in j["nodes"] if "mesh" in n]
    assert names == ["base <b>", "lid"]  # names are stored as data; the page shows them as text
    colors = {tuple(round(c, 3) for c in m["pbrMetallicRoughness"]["baseColorFactor"]) for m in j["materials"]}
    assert len(colors) == 2
    assert items[0][0].label == "" and items[0][0].color is None, "the script's own shapes are left untouched"


def test_parse_layout():
    assert viewer.parse_layout("print") == "print" and viewer.parse_layout("Assembly") == "assembly"
    assert viewer.parse_layout("none") is None and viewer.parse_layout("") is None and viewer.parse_layout(True) == "print"
    with pytest.raises(ValueError):
        viewer.parse_layout("sideways")


def test_glb_format():
    from b123d_print.config import DEFAULT_FORMATS, Settings, parse_formats

    assert "glb" in parse_formats("all") and parse_formats("glb,3mf") == ("3mf", "glb")
    assert "glb" not in DEFAULT_FORMATS and Settings().formats == DEFAULT_FORMATS
    assert links.content_type("parts/p/out/p.glb") == "model/gltf-binary"
