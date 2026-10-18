"""End-to-end smoke test of b123d-print-mcp, as an MCP client would use it.

    uv run python tests/mcp_smoke.py [--keep]          # stdio: starts the server itself
    uv run python tests/mcp_smoke.py --http [--keep]   # starts it with --transport http, a token and named tokens
    uv run python tests/mcp_smoke.py --split [--keep]  # the same with builds in a separate `worker` process
    uv run python tests/mcp_smoke.py --ssh [--keep]    # through the SSH forced command (`ssh-serve`),
                                                       # with sshd simulated by tests/fake_ssh.py
    B123D_PRINT_SMOKE_SSH="ssh -p 2222 me@host" B123D_PRINT_SMOKE_WORKSPACE_DIR=... uv run python tests/mcp_smoke.py --ssh
                                                       # over real ssh, to a key set up with setup-ssh
    B123D_PRINT_SMOKE_URL=https://host/mcp B123D_PRINT_SMOKE_TOKEN=... uv run python tests/mcp_smoke.py
                                                       # a running server (e.g. the Docker image)

Drives every tool, prompt and resource on a fresh workspace and exits non-zero on any failure.
Over HTTP it also checks that a missing or wrong token is refused, that two clients in different
workspaces don't see each other's parts, and that their builds run in parallel.
Images are saved next to the workspace for a look.
"""

import asyncio
import json
import base64
import os
import re
import secrets
import shutil
import signal
import socket
import subprocess
import time
import sys
import tempfile
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

BOX = '''"""Box with a counterbored hole."""
from dataclasses import dataclass
from build123d import Align, Box, Cylinder, Mode, Part, Pos
from b123d_print import Wall, View, hole_comp

BED = (Align.CENTER, Align.CENTER, Align.MIN)

@dataclass(frozen=True)
class Dims:
    W: float = 30.0
    H: float = 8.0
    HOLE_D: float = 3.4
    CBORE_D: float = 6.5
    CBORE_DEPTH: float = 3.0
    HOLE_COMP: float = hole_comp(__file__)

VARIANTS = {"": {}, "thin": dict(W=7.0)}

def build(d: Dims) -> Part:
    p = Box(d.W, d.W, d.H, align=BED)
    p -= Cylinder((d.HOLE_D + d.HOLE_COMP) / 2, 50, mode=Mode.PRIVATE)
    p -= Cylinder((d.CBORE_D + d.HOLE_COMP) / 2, d.CBORE_DEPTH, align=BED, mode=Mode.PRIVATE)
    return p

def views(d):
    return [View("XZ", 0.0, "through the hole")]

def checks(d):
    return [Wall("", "XY", d.CBORE_DEPTH / 2, near=(0, 0), radius=d.W, min=1.0, label="around the counterbore")]
'''


def text(res) -> str:
    return "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")


def images(res):
    return [c for c in res.content if getattr(c, "type", "") == "image"]


async def flow(c, pw, expect) -> None:
    """The whole tool tour. pw: the server's workspace folder as seen from here (None: remote, skip file checks)."""

    def on_disk(rel):  # True when the file exists, or when we cannot look (remote server)
        return pw is None or (pw / rel).exists()

    tools = {t.name for t in (await c.list_tools()).tools}
    expect(tools >= {"use_printer", "list_parts", "new_part", "read_part", "write_part", "build_part", "render_preview", "section", "check",
                     "export", "compare", "upload_reference", "describe_model", "before_after"}, f"tools: {sorted(tools)}")
    prompts = {p.name for p in (await c.list_prompts()).prompts}
    expect(prompts >= {"design_part_from_photos", "modify_part", "verify_part", "calibrate_hole_comp", "remix_part"},
           f"prompts: {sorted(prompts)}")
    g = await c.get_prompt("design_part_from_photos", {"description": "a bracket"})
    expect("LIST EVERY DIMENSION" in g.messages[0].content.text, "prompt carries the confirm-dimensions rule")
    r = await c.read_resource("b123d-print://guide")
    expect("Verify before reporting" in r.contents[0].text, "guide resource")

    res = await c.call_tool("new_part", {"name": "box"})
    expect("Created" in text(res) and on_disk("parts/box/box.py"), "new_part scaffolds parts/box/box.py")
    res = await c.call_tool("build_part", {"name": "box"})
    expect('"valid": true' in text(res), "template builds")
    res = await c.call_tool("write_part", {"name": "box", "code": "def build(:\n"})
    expect("NOT SAVED" in text(res), "write_part rejects a syntax error")
    res = await c.call_tool("write_part", {"name": "box", "code": BOX})
    expect("Saved" in text(res), "write_part saves")
    res = await c.call_tool("build_part", {"name": "box"})
    t = text(res)
    expect('"standard"' in t and '"thin"' in t and '"x": 30.0' in t, "build_part reports both variants and bbox")
    res = await c.call_tool("render_preview", {"name": "box"})
    im = images(res)
    expect(im and im[0].mime_type == "image/png" and len(base64.b64decode(im[0].data)) > 10_000, "render_preview returns a PNG")
    if im:
        (SAVE / "preview.png").write_bytes(base64.b64decode(im[0].data))
    res = await c.call_tool("section", {"name": "box", "plane": "XZ", "at": 0.0})
    im = images(res)
    expect(im and im[0].mime_type == "image/png", "section returns a PNG")
    if im:
        (SAVE / "section.png").write_bytes(base64.b64decode(im[0].data))
    res = await c.call_tool("check", {"name": "box", "variant": "standard"})
    expect(text(res).startswith("PASSED") and "min wall" in text(res), "check passes on the standard box")
    res = await c.call_tool("check", {"name": "box", "variant": "thin"})
    expect(text(res).startswith("FAILED") and "[FAIL] wall" in text(res), "check catches the thin wall in the 'thin' variant")
    res = await c.call_tool("export", {"name": "box"})
    expect("box.stl" in text(res) and on_disk("parts/box/out/box_thin.3mf"), "export writes STEP/STL/3MF/PNG for each variant")
    if pw is not None:
        shutil.rmtree(pw / "parts/box/out")
    res = await c.call_tool("export", {"name": "box", "variant": "standard", "formats": "3mf"})
    files = [x.split()[0] for x in text(res).splitlines() if x.strip().startswith("parts/")]  # over HTTP a link follows
    expect(files == ["parts/box/out/box.3mf"] and (pw is None or [p.name for p in (pw / "parts/box/out").iterdir()] == ["box.3mf"]),
           "export honors formats='3mf'")
    res = await c.call_tool("export", {"name": "box", "variant": "standard", "formats": "3mf", "embed": True})
    emb = blobs(res)
    got = next((v for k, v in emb.items() if k.endswith("/parts/box/out/box.3mf")), None)
    expect(got and (pw is None or got == (pw / "parts/box/out/box.3mf").read_bytes()),
           f"export embed=True puts the file into the result ({len(emb)} embedded)")
    res = await c.call_tool("export", {"name": "box", "formats": "obj"})
    expect(res.is_error and "unknown format" in text(res), "unknown format is refused with the choices")

    # compare parses the files in the sandbox, like a build
    res = await c.call_tool("compare", {"reference": "parts/box/out/box.3mf", "candidate": "parts/box/out/box.3mf", "image": True})
    ok_cmp = "PASS" in text(res) and bool(images(res))
    expect(ok_cmp, "compare: a part matches itself, with a deviation image" + ("" if ok_cmp else f"\n{text(res)[:3000]}"))
    res = await c.call_tool("compare", {"reference": "../outside.stl", "candidate": "parts/box/out/box.3mf"})
    expect(res.is_error and "outside the workspace" in text(res), "compare refuses files outside the workspace")
    if pw is not None:
        (pw / "junk.stl").write_bytes(b"\x00" * 80 + b"\xff\xff\xff\x7f" + b"garbage")
        res = await c.call_tool("compare", {"reference": "junk.stl", "candidate": "parts/box/out/box.3mf"})
        expect("ERROR" in text(res), "compare reports a corrupt file as an error (parsed in the sandbox)")

    # sandbox: a script that tries to reach the network / escape gets a clear error
    evil = BOX + "\nimport urllib.request\nurllib.request.urlopen('http://example.com')\n"
    await c.call_tool("write_part", {"name": "box", "code": evil})
    res = await c.call_tool("build_part", {"name": "box"})
    expect("ERROR" in text(res) and ("blocked" in text(res) or "not known" in text(res)), "network access from a part script is blocked")
    evil = BOX + "\nopen('" + str(Path.home() / "b123d_print_smoke_escape.txt") + "', 'w').write('x')\n"
    await c.call_tool("write_part", {"name": "box", "code": evil})
    res = await c.call_tool("build_part", {"name": "box"})
    expect("ERROR" in text(res) and not (Path.home() / "b123d_print_smoke_escape.txt").exists(), "writing outside the workspace is blocked")
    await c.call_tool("write_part", {"name": "box", "code": "import time\nwhile True: time.sleep(0.1)\n"})
    res = await c.call_tool("build_part", {"name": "box"})
    expect("timed out" in text(res), "runaway script is killed at the timeout")

    res = await c.call_tool("new_part", {"name": "coupon", "example": "hole_coupon"})
    expect("Created" in text(res), "new_part from a bundled example")
    res = await c.call_tool("check", {"name": "coupon"})
    expect(text(res).startswith("PASSED"), "example passes its checks")
    res = await c.call_tool("list_parts", {})
    expect('"box"' in text(res) and '"coupon"' in text(res), "list_parts")
    sb = json.loads(text(res))["sandbox"]
    print(f"     sandbox: {sb}")
    want = os.environ.get("B123D_PRINT_EXPECT_SANDBOX")  # e.g. "bubblewrap" in CI on Linux
    if want:
        expect(want.lower() in sb.lower(), f"sandbox in use is {want}")
    res = await c.call_tool("use_printer", {"search": "bambu a1 mini"})
    expect("bambu_lab_a1_mini" in text(res), "use_printer finds printers")
    res = await c.call_tool("use_printer", {"name": "bambu_lab_a1_mini", "material": "petg"})
    expect('"bed_x": 180' in text(res) and "PETG" in text(res), "use_printer sets printer + material")
    big = BOX.replace("W: float = 30.0", "W: float = 200.0")
    await c.call_tool("write_part", {"name": "box", "code": big})
    res = await c.call_tool("check", {"name": "box", "variant": "standard"})
    expect("[FAIL] fit" in text(res) and "A1 mini" in text(res), "fit check fails a 200 mm part on a 180 mm bed")
    res = await c.call_tool("use_printer", {"name": "generic"})
    res = await c.call_tool("check", {"name": "box", "variant": "standard"})
    expect(" fit " not in text(res), "generic mode has no fit check")
    res = await c.call_tool("read_part", {"name": "../../etc"})
    expect(res.is_error and "bad part name" in text(res), "path traversal in a part name is refused, with a reason")
    res = await c.call_tool("render_preview", {"name": "nosuch"})
    expect(res.is_error and "Parts:" in text(res), "unknown part: error lists the parts")
    await multipart_checks(c, expect)
    await remix_checks(c, pw, expect)


async def remix_checks(c, pw, expect) -> None:
    """Remix: the example's reference comes along, describe_model, inherited findings, before_after, upload."""
    res = await c.call_tool("new_part", {"name": "rb", "example": "remix_bracket"})
    expect("Created" in text(res) and (pw is None or (pw / "parts/rb/ref/l_bracket.stl").is_file()),
           "new_part from the remix example copies its reference mesh")
    res = await c.call_tool("describe_model", {"part": "rb", "file": "l_bracket.stl", "size": "small"})
    t = text(res)
    ok = '"faces_after": 134' in t and '"d": 6.0' in t and images(res)
    expect(ok, "describe_model: faces after merging, the faceted holes, a render" + ("" if ok else f"\n{t[:2000]}"))
    res = await c.call_tool("describe_model", {"part": "rb", "file": "../../../etc/passwd"})
    expect(res.is_error, "describe_model refuses a path out of the workspace")
    res = await c.call_tool("check", {"name": "rb"})
    t = text(res)
    expect(t.startswith("PASSED") and "inherited from the original" in t and "[OK  ] import" in t,
           "check labels the original's overhang as inherited" + ("" if t.startswith("PASSED") else f"\n{t[:2000]}"))
    res = await c.call_tool("before_after", {"name": "rb", "size": "small"})
    expect(len(images(res)) == 2 and "score" in text(res).lower(), "before_after returns the side-by-side and the deviation view")
    stl = (Path(__file__).resolve().parents[1] / "src/b123d_print/examples/remix_bracket/ref/l_bracket.stl").read_bytes()
    res = await c.call_tool("upload_reference", {"part": "up", "filename": "small.stl",
                                                 "data_base64": base64.b64encode(stl).decode()})
    expect("Stored parts/up/ref/small.stl" in text(res) and (pw is None or (pw / "parts/up/ref/small.stl").read_bytes() == stl),
           "upload_reference stores a base64 file")
    res = await c.call_tool("upload_reference", {"part": "up", "filename": "../x.stl", "data_base64": "AAAA"})
    expect(res.is_error and "bad file name" in text(res), "upload_reference refuses a path in the file name")
    res = await c.call_tool("upload_reference", {"part": "up", "filename": "big.stl"})
    t = text(res)
    link = re.search(r"'(https?://\S+/upload/\S+)'", t)
    if link:  # over HTTP: a signed upload link, no token
        async with create_mcp_http_client() as h:
            r = await h.put(link.group(1), content=stl)
            expect(r.status_code == 201 and (pw is None or (pw / "parts/up/ref/big.stl").read_bytes() == stl),
                   f"the signed upload link stores the file without a token ({r.status_code})")
            r = await h.put(link.group(1), content=stl)
            expect(r.status_code == 409, f"... once: the same link does not overwrite ({r.status_code})")
    else:
        expect("b123d-print push" in t or "copy the file to" in t, "upload_reference says how to copy the file (SSH / local)")


TWO = '''"""Base and lid, both in print orientation at the origin."""
from dataclasses import dataclass
from build123d import Align, Box, Part, Pos

BED = (Align.CENTER, Align.CENTER, Align.MIN)

@dataclass(frozen=True)
class Dims:
    W: float = 40.0
    H: float = 12.0
    LID_T: float = 3.0

def build(d: Dims) -> dict:
    return {"base": Box(d.W, d.W, d.H, align=BED), "lid": Box(d.W - 4, d.W - 4, d.LID_T, align=BED)}
'''

ASSEMBLY = '''
def assembly(d):
    parts = build(d)
    return [(parts["base"], "steelblue", "base"), (Pos(0, 0, d.H) * parts["lid"], "orange", "lid")]
'''


def summary(res) -> dict:
    """The JSON at the start of a render_preview result (a download line may follow over HTTP)."""
    try:
        return json.JSONDecoder().raw_decode(text(res))[0]
    except ValueError:
        print(f"     not a render_preview summary: {text(res)[:600]}")
        return {}


def png_width(img) -> int:
    return int.from_bytes(base64.b64decode(img.data)[16:20], "big")


async def multipart_checks(c, expect) -> None:
    """Issue #11: multi-part previews, image size and inline, export parts= and the formats note."""
    await c.call_tool("new_part", {"name": "two"})
    await c.call_tool("write_part", {"name": "two", "code": TWO})
    res = await c.call_tool("render_preview", {"name": "two"})
    info = summary(res)
    expect(info["layout"] == "side by side" and info["drawn"] == ["base", "lid"] and images(res),
           "two printable parts, no assembly(): drawn side by side")
    expect(info["parts"]["lid"]["min"][0] < 0, "the reported parts keep their own coordinates (print orientation)")
    await c.call_tool("write_part", {"name": "two", "code": TWO + ASSEMBLY})
    res = await c.call_tool("render_preview", {"name": "two"})
    expect(summary(res)["layout"] == "assembly", "with assembly(): the assembly is drawn")
    res = await c.call_tool("render_preview", {"name": "two", "parts": "base,lid"})
    expect(summary(res)["layout"] == "side by side", "parts='base,lid': side by side")
    res = await c.call_tool("render_preview", {"name": "two", "parts": "lid"})
    expect(summary(res)["layout"] == "single", "parts='lid': just the lid")
    big = images(await c.call_tool("render_preview", {"name": "two", "parts": "lid"}))[0]
    small = images(await c.call_tool("render_preview", {"name": "two", "parts": "lid", "size": "small"}))[0]
    expect(700 <= png_width(small) <= 900 and png_width(big) > 1500,
           f"size='small' renders ~800 px wide ({png_width(small)} vs {png_width(big)} px)")
    res = await c.call_tool("section", {"name": "two", "plane": "XZ", "at": 0, "size": "small"})
    expect(images(res) and png_width(images(res)[0]) <= 900, f"section size='small' ({png_width(images(res)[0])} px)")
    res = await c.call_tool("render_preview", {"name": "two", "inline": False})
    expect(not images(res) and ("Image file:" in text(res) or links_in(res)), "inline=False: the file or its link, no image bytes")
    res = await c.call_tool("render_preview", {"name": "two", "size": "huge"})
    expect(res.is_error and "size must be" in text(res), "a bad size is refused")
    res = await c.call_tool("export", {"name": "two", "parts": "lid", "formats": "3mf"})
    lines = [x.split()[0] for x in text(res).splitlines() if x.strip().startswith("parts/")]
    expect(lines == ["parts/two/out/two_lid.3mf"] and "Exported 1 file(s)" in text(res),
           f"export parts='lid' formats='3mf': one file, counted ({lines})")
    expect("default formats" not in text(res), "no formats note when formats= is given")
    res = await c.call_tool("export", {"name": "two"})
    n = len([x for x in text(res).splitlines() if x.strip().startswith("parts/")])
    expect(f"Exported {n} file(s)" in text(res) and re.search(r" [0-9.]+ (B|KB|MB) in all", text(res)) and "default formats" in text(res)
           and "3MF for Bambu" in text(res), f"bare export: {n} files counted, with the note to narrow formats")
    res = await c.call_tool("export", {"name": "two", "parts": "nope"})
    expect(res.is_error or "no part(s) ['nope']" in text(res), "export parts= with an unknown part is refused")


SAVE = Path(tempfile.mkdtemp(prefix="b123d-print-smoke-img-"))


def http_client(url: str, token: str | None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    return Client(streamable_http_client(url, http_client=create_mcp_http_client(headers=headers)))


def with_workspace(url: str, name: str) -> str:
    return f"{url}{'&' if '?' in url else '?'}workspace={name}"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def links_in(res) -> list[str]:
    return re.findall(r"https?://\S+/files/\S+", text(res))


def blobs(res) -> dict[str, bytes]:
    return {c.resource.uri: base64.b64decode(c.resource.blob) for c in res.content
            if getattr(c, "type", "") == "resource" and getattr(c.resource, "blob", None)}


async def link_checks(ca, cb, a: str, b: str, token: str, wsroot: Path | None, expect) -> None:
    """Export over HTTP, then fetch every file by its link with no token and compare it with the file on
    the server (on disk when visible from here, and always with the MCP resource); refuse what must fail."""
    from urllib.parse import quote

    from b123d_print import links

    res = await ca.call_tool("export", {"name": "only_in_a", "variant": "standard"})
    urls = links_in(res)
    rlinks = [c for c in res.content if getattr(c, "type", "") == "resource_link"]
    expect(len(urls) >= 4 and len(rlinks) == len(urls) and "expire" in text(res),
           f"export returns a download link and a resource link per file ({len(urls)} links)")
    async with create_mcp_http_client() as h:  # no Authorization header
        same = True
        for u, rl in zip(urls, rlinks):
            r = await h.get(u)
            rel = rl.uri.split(f"b123d-print://files/{a}/", 1)[1]
            disk = (wsroot / "workspaces" / a / rel).read_bytes() if wsroot else None
            via_mcp = (await ca.read_resource(rl.uri)).contents[0]
            mcp_bytes = base64.b64decode(via_mcp.blob)
            ok = r.status_code == 200 and r.content == mcp_bytes and (disk is None or r.content == disk)
            if not ok:
                print(f"     mismatch for {u}: {r.status_code}")
            same &= ok
        expect(same, "every link downloads without a token, byte-identical to the server's file and its MCP resource")
        u3 = next(u for u in urls if u.endswith(".3mf"))
        r = await h.get(u3)
        expect(r.headers.get("content-type", "").startswith("model/3mf") and "attachment" in r.headers.get("content-disposition", "")
               and "only_in_a.3mf" in r.headers.get("content-disposition", ""), "3MF link: Content-Type model/3mf, attachment with the file name")
        head, ws_, tok, path = re.match(r"(https?://[^/]+(?:/.*?)?)/files/([^/]+)/([^/]+)/(.+)$", u3).groups()
        exp, sig = tok.split(".")
        bad = {
            "tampered signature": f"{head}/files/{ws_}/{exp}.{sig[:-3]}AAA/{path}",
            "longer expiry": f"{head}/files/{ws_}/{int(exp) + 86400}.{sig}/{path}",
            "other file, same signature": f"{head}/files/{ws_}/{tok}/{path.replace('.3mf', '.stl')}",
            "workspace A's link pointed at workspace B": f"{head}/files/{b}/{tok}/{path.replace('only_in_a', 'only_in_b')}",
            "traversal": f"{head}/files/{ws_}/{tok}/parts/only_in_a/out/%2e%2e/%2e%2e/%2e%2e/b123d-print.toml",
            "the part script": f"{head}/files/{ws_}/{tok}/parts/only_in_a/only_in_a.py",
        }
        for what, u in bad.items():
            r = await h.get(u)
            expect(r.status_code == 404, f"refused: {what} ({r.status_code})")
        # forge an expired link with the server's key: B123D_PRINT_LINK_SECRET, else the tokens file's
        # link_secret (when that file is visible from here), else derived from the token
        from b123d_print import tokens as tk

        tf = Path(os.environ.get("B123D_PRINT_TOKENS_FILE", "/nonexistent"))
        file_secret = tk.read(tf)[1] if tf.is_file() else None
        legacy_only = not os.environ.get("B123D_PRINT_TOKENS_FILE") and not os.environ.get("B123D_PRINT_SMOKE_URL")
        if not (os.environ.get("B123D_PRINT_LINK_SECRET") or file_secret or legacy_only):
            print("     (expired-link check skipped: the server's link key is not known here)")
        if os.environ.get("B123D_PRINT_LINK_SECRET") or file_secret or legacy_only:
            secret = links.derive_secret(token, os.environ.get("B123D_PRINT_LINK_SECRET") or file_secret)
            old, _ = links.sign(secret, ws_, path, -60)
            r = await h.get(head + old)
            expect(r.status_code == 410 and "expired" in r.text, f"an expired link is refused with 410 ({r.status_code})")
        r = await h.get(head + f"/files/{ws_}/{tok}/{quote(path)}", headers={"Authorization": "Bearer nonsense"})
        expect(r.status_code == 200, "a link works whatever Authorization header comes with it")
    try:
        await cb.read_resource(f"b123d-print://files/{a}/{path}")
        expect(False, "workspace B cannot read workspace A's file as a resource")
    except Exception:
        expect(True, "workspace B cannot read workspace A's file as a resource")
    res = await ca.call_tool("export", {"name": "only_in_a", "variant": "standard", "formats": "3mf,png", "embed": True})
    emb = blobs(res)
    want = (wsroot / "workspaces" / a / "parts/only_in_a/out/only_in_a.3mf").read_bytes() if wsroot else None
    got = next((v for k, v in emb.items() if k.endswith(".3mf")), None)
    expect(got and (want is None or got == want), f"embed=True puts the files into the result ({len(emb)} embedded)")
    res = await ca.call_tool("render_preview", {"name": "only_in_a"})
    expect(images(res) and links_in(res) and any(getattr(c, "type", "") == "resource_link" for c in res.content),
           "render_preview over HTTP: the image, plus a download link and a resource link")


async def http_checks(url: str, token: str, expect, wsroot: Path | None = None) -> None:
    """Auth refusals, workspace isolation and parallel builds."""
    base = url.split("?")[0]
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}}}
    hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    async with create_mcp_http_client() as h:
        r = await h.post(base, json=init, headers=hdr)
        expect(r.status_code == 401, f"no token -> 401 (got {r.status_code})")
        r = await h.post(base, json=init, headers={**hdr, "Authorization": "Bearer wrong-token-0123456789"})
        expect(r.status_code == 401, f"wrong token -> 401 (got {r.status_code})")
        r = await h.post(with_workspace(base, "smoke-check"), json=init, headers={**hdr, "Authorization": f"Bearer {token}"})
        expect(r.status_code == 200, f"right token -> 200 (got {r.status_code})")
        r = await h.get(base.rsplit("/", 1)[0] + "/health")
        expect(r.status_code == 200 and r.json().get("status") == "ok", "/health answers without a token")
    try:
        async with http_client(url, "wrong-token-0123456789") as c:
            await c.list_tools()
        expect(False, "MCP client with a wrong token is refused")
    except Exception:
        expect(True, "MCP client with a wrong token is refused")

    tag = secrets.token_hex(3)
    a, b = f"smoke-{tag}-a", f"smoke-{tag}-b"
    async with http_client(with_workspace(url, a), token) as ca, http_client(with_workspace(url, b), token) as cb:
        await ca.call_tool("new_part", {"name": "only_in_a"})
        res = await cb.call_tool("list_parts", {})
        expect('"only_in_a"' not in text(res) and f"workspaces/{b}" in json.loads(text(res))["workspace"],
               "workspaces are separate (b does not see a's part)")
        await cb.call_tool("new_part", {"name": "only_in_b"})
        await ca.call_tool("write_part", {"name": "only_in_a", "code": BOX})
        await cb.call_tool("write_part", {"name": "only_in_b", "code": BOX})
        t0 = time.monotonic()
        await ca.call_tool("build_part", {"name": "only_in_a", "variant": "standard"})
        one = time.monotonic() - t0
        t0 = time.monotonic()
        ra, rb = await asyncio.gather(ca.call_tool("render_preview", {"name": "only_in_a"}),
                                      cb.call_tool("render_preview", {"name": "only_in_b"}))
        both = time.monotonic() - t0
        expect(images(ra) and images(rb), f"two clients render at the same time ({both:.1f} s; one build {one:.1f} s)")
        res = await ca.call_tool("list_parts", {})
        mx = json.loads(text(res)).get("max_concurrent_builds")
        print(f"     max_concurrent_builds: {mx}")
        await link_checks(ca, cb, a, b, token, wsroot, expect)
    if await post_status(url, token, "..%2Fetc") == 403:  # a named token's workspace patterns refuse it first
        expect(True, "bad workspace name is refused (403: outside the token's workspaces)")
    else:
        async with http_client(with_workspace(url, "..%2Fetc"), token) as c:
            res = await c.call_tool("list_parts", {})
            expect(res.is_error and "bad workspace name" in text(res), "bad workspace name is refused")


# a build that never ends and keeps writing a heartbeat (a PID would be meaningless from here:
# bubblewrap runs the worker in its own PID namespace)
SPIN = """import pathlib, time
beat = pathlib.Path(__file__).parent / "out" / "beat"
beat.parent.mkdir(exist_ok=True)
while True:
    beat.write_text(repr(time.monotonic()))
    time.sleep(0.05)
"""


def beating(path: Path) -> bool:
    """True while something keeps rewriting the heartbeat file."""
    try:
        first = path.read_text()
        time.sleep(0.6)
        return path.read_text() != first
    except OSError:
        return False


async def shutdown_check(server, url: str, token: str, ws: Path, expect) -> None:
    """SIGTERM while a build runs: the server waits --shutdown-grace, kills the build, exits 0."""
    beat = ws / "workspaces/shutdown/parts/spin/out/beat"
    async with http_client(with_workspace(url, "shutdown"), token) as c:
        await c.call_tool("new_part", {"name": "spin"})
        await c.call_tool("write_part", {"name": "spin", "code": SPIN})
        call = asyncio.ensure_future(c.call_tool("build_part", {"name": "spin"}))
        for _ in range(150):
            await asyncio.sleep(0.2)
            if beat.exists():
                break
        expect(await asyncio.to_thread(beating, beat), "a build is running before shutdown")
        t0 = time.monotonic()
        if sys.platform == "win32":  # no SIGTERM there (terminate() is TerminateProcess): Ctrl+Break to its group
            server.send_signal(signal.CTRL_BREAK_EVENT)
        else:
            server.terminate()
        code = await asyncio.to_thread(server.wait, 30)
        took = time.monotonic() - t0
        try:
            await asyncio.wait_for(call, 10)
        except BaseException:
            pass
    expect(code == 0 and took < 15, f"SIGTERM: server exits cleanly after the grace period (code {code}, {took:.1f} s)")
    expect(not beating(beat), "no build process left behind")


def mcp_cli(cmd, env, *args) -> subprocess.CompletedProcess:
    return subprocess.run(cmd + list(args), env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)


async def post_status(url: str, token: str, workspace: str | None = None) -> int:
    init = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "smoke", "version": "0"}}}
    u = with_workspace(url, workspace) if workspace else url
    async with create_mcp_http_client() as h:
        r = await h.post(u, json=init, headers={"Content-Type": "application/json", "Accept": "application/json, text/event-stream",
                                                "Authorization": f"Bearer {token}"})
        return r.status_code


async def named_token_checks(url: str, cmd, env, scoped: str, single: str, log: Path, expect) -> None:
    """Tokens from the tokens file: workspace patterns (403 outside them), a single-workspace token's
    default, revocation without a restart, and the token's name in the server log."""
    async with http_client(with_workspace(url, "scoped-a"), scoped) as c:
        res = await c.call_tool("list_parts", {})
        expect(json.loads(text(res)).get("token") == "scoped", "a named token works in its workspace and list_parts names it")
        await c.call_tool("new_part", {"name": "tok"})
        res = await c.call_tool("export", {"name": "tok", "formats": "3mf"})
        u = links_in(res)[0]
        async with create_mcp_http_client() as h:
            expect((await h.get(u)).status_code == 200, "download links work for a named token's workspace")
    expect(await post_status(url, scoped, "penguin-jon") == 403, "a named token outside its workspaces gets 403")
    expect(await post_status(url, scoped) == 403, "a token with only a pattern cannot use the shared root workspace")
    async with http_client(url, single) as c:  # no ?workspace=
        ws = json.loads(text(await c.call_tool("list_parts", {})))["workspace"]
        expect(ws.endswith("workspaces/only-one"), f"a token with one workspace uses it when none is given ({ws})")
    r = mcp_cli(cmd, env, "token", "revoke", "scoped")
    expect(r.returncode == 0, "token revoke")
    expect(await post_status(url, scoped, "scoped-a") == 401, "a revoked token is refused at once, no restart")
    r = mcp_cli(cmd, env, "token", "add", "late", "--workspace", "late-*")
    expect(await post_status(url, r.stdout.strip(), "late-1") == 200, "a token added while the server runs works at once")
    logged = log.read_text(encoding="utf-8", errors="replace")
    expect("scoped POST /mcp ws=scoped-a -> 200" in logged and "scoped POST /mcp ws=penguin-jon -> 403" in logged
           and "(bad token)" in logged, "the server log names the token of every request")
    expect(scoped not in logged and single not in logged and "/files/" in logged and ".3mf" in logged
           and not re.search(r"/files/[^/ ]+/\d+\.", logged), "the log holds no token and no working link")


async def worker_down_check(url: str, token: str, worker, expect) -> None:
    worker.terminate()
    worker.wait(20)
    async with create_mcp_http_client() as h:
        r = await h.get(url.rsplit("/", 1)[0] + "/health")
        expect(r.status_code == 503 and r.json().get("worker") == "down", f"/health says 503 'degraded' without the worker ({r.status_code})")
    async with http_client(with_workspace(url, "down"), token) as c:
        await c.call_tool("new_part", {"name": "x"})
        res = await c.call_tool("build_part", {"name": "x"})
        expect("worker is not running" in text(res), "a build without a worker fails at once, saying why")


async def ssh_checks(c, ssh_cmd: list[str], dest: str, pw: Path | None, expect) -> None:
    """After the tool tour over SSH: export names the pull command, pull fetches the files, and the
    key gives nothing but the MCP server, pull and version."""
    await c.call_tool("write_part", {"name": "box", "code": BOX})
    res = await c.call_tool("export", {"name": "box", "variant": "standard", "formats": "3mf,stl"})
    expect(f"b123d-print pull box --formats 3mf,stl --from {dest}" in text(res), "export over SSH gives the exact pull command")
    got = Path(tempfile.mkdtemp(prefix="b123d-print-smoke-pull-"))
    r = subprocess.run([sys.executable, "-m", "b123d_print.cli", "pull", "box", "--from", dest, "--formats", "3mf,stl",
                        "-o", str(got), "--ssh", " ".join(ssh_cmd)], capture_output=True, text=True, timeout=120)
    names = sorted(p.name for p in got.iterdir())
    same = pw is None or all((got / n).read_bytes() == (pw / "parts/box/out" / n).read_bytes() for n in names)
    expect(r.returncode == 0 and names == ["box.3mf", "box.stl"] and same,
           f"b123d-print pull copies the files byte for byte ({names}{'' if r.returncode == 0 else ': ' + r.stderr[-500:]})")
    shutil.rmtree(got, ignore_errors=True)
    r = subprocess.run(ssh_cmd + [dest, "version"], capture_output=True, text=True, timeout=60)
    expect(r.returncode == 0 and "workspace:" in r.stdout, "ssh <dest> version answers")
    for bad in ("bash", "sh -c id", "internal-sftp", "scp -f parts/box/out/box.3mf", "b123d-print-mcp --workspace /tmp",
                "pull ../../etc", "pull box; id"):
        r = subprocess.run(ssh_cmd + [dest, bad], capture_output=True, text=True, timeout=60)
        expect(r.returncode != 0 and "refused" in r.stderr and not r.stdout, f"refused over SSH: {bad!r}")


async def main(keep: bool, http: bool, split: bool = False, over_ssh: bool = False) -> None:
    ws = Path(tempfile.mkdtemp(prefix="b123d-print-smoke-"))
    # B123D_PRINT_SMOKE_CMD runs another launcher, e.g. "uvx --from dist/b123d_print-0.1.0-py3-none-any.whl b123d-print-mcp"
    cmd = os.environ.get("B123D_PRINT_SMOKE_CMD", f"{sys.executable} -m b123d_print.mcp_server").split()
    # a private user config, so use_printer never touches the real one; tokens outside the workspace
    tokfile = ws.parent / f"{ws.name}-tokens.toml"
    env = {**os.environ, "XDG_CONFIG_HOME": str(ws / ".config"), "B123D_PRINT_TOKENS_FILE": str(tokfile)}
    url = os.environ.get("B123D_PRINT_SMOKE_URL")
    token = os.environ.get("B123D_PRINT_SMOKE_TOKEN") or os.environ.get("B123D_PRINT_TOKEN")
    ok = True

    def expect(cond, what):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + what)
        ok &= bool(cond)

    server = worker = None
    if url or http:
        name = f"smoke-{secrets.token_hex(3)}"
        if not url:  # start our own HTTP server on a free port (and, with --split, a separate worker)
            port, token = free_port(), secrets.token_urlsafe(24)
            scoped = mcp_cli(cmd, env, "token", "add", "scoped", "--workspace", "scoped-*").stdout.strip()
            single = mcp_cli(cmd, env, "token", "add", "single", "--workspace", "only-one").stdout.strip()
            os.environ["B123D_PRINT_TOKENS_FILE"] = str(tokfile)  # link_checks signs with its link_secret
            extra = []
            if split:
                queue = ws / ".b123d-print/jobs"
                worker = subprocess.Popen(cmd + ["--max-builds", "2", "worker", "--queue", str(queue)], env=env)
                extra = ["--job-queue", str(queue)]
            log = ws.parent / f"{ws.name}-server.log"
            server = subprocess.Popen(cmd + ["--workspace", str(ws), "--timeout", "60", "--transport", "http", "--port", str(port),
                                             "--shutdown-grace", "3", *extra],
                                      env={**env, "B123D_PRINT_TOKEN": token}, stderr=open(log, "w"),
                                      creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
            url = f"http://127.0.0.1:{port}/mcp"
            for _ in range(300):  # first start can be slow (imports, bytecode)
                try:
                    socket.create_connection(("127.0.0.1", port), 0.2).close()
                    break
                except OSError:
                    if server.poll() is not None:
                        sys.exit(f"server exited with {server.returncode}:\n{log.read_text()}")
                    time.sleep(0.2)
            pw = ws / "workspaces" / name
        else:  # a running server; B123D_PRINT_SMOKE_WORKSPACE_DIR: its workspace folder, if visible from here
            wd = os.environ.get("B123D_PRINT_SMOKE_WORKSPACE_DIR")
            pw = Path(wd) / "workspaces" / name if wd else None
        print(f"     http: {url}  workspace {name}{'  (separate build worker)' if split else ''}")
        try:
            if not token:
                sys.exit("B123D_PRINT_SMOKE_URL needs B123D_PRINT_SMOKE_TOKEN")
            await http_checks(url, token, expect, pw.parent.parent if pw else None)
            async with http_client(with_workspace(url, name), token) as c:
                await flow(c, pw, expect)
                if split or os.environ.get("B123D_PRINT_SMOKE_SPLIT"):
                    bw = json.loads(text(await c.call_tool("list_parts", {}))).get("build_worker", "")
                    expect(bw.startswith("separate"), f"builds run in the separate worker ({bw})")
            if server:
                await named_token_checks(url, cmd, env, scoped, single, log, expect)
                if worker:
                    await worker_down_check(url, token, worker, expect)
                    worker = subprocess.Popen(cmd + ["--max-builds", "2", "worker", "--queue", str(queue)], env=env)
                    for _ in range(100):
                        if (queue / "worker.alive").exists():
                            break
                        time.sleep(0.1)
                await shutdown_check(server, url, token, ws, expect)
                server = None
        finally:
            for p in (server, worker):
                if p:
                    p.terminate()
                    p.wait(20)
    elif over_ssh:
        real = os.environ.get("B123D_PRINT_SMOKE_SSH")  # e.g. "ssh -p 2222 -i key me@127.0.0.1"
        if real:
            words = real.split()
            ssh_cmd, dest = words[:-1], words[-1]
            wd = os.environ.get("B123D_PRINT_SMOKE_WORKSPACE_DIR")
            pw = Path(wd) if wd else None
        else:  # the line setup-ssh writes, run the way sshd runs it
            from b123d_print import ssh

            key = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKCbiyMIpQvcOhoPsC6yzJoIhRkkG7wuIPlTJDRKILTV smoke"
            dest, pw = "smoke@cad.example", ws
            line = ssh.key_line(key, ws, dest, prog=[sys.executable, "-m", "b123d_print.cli"])
            env["B123D_PRINT_FAKE_SSH_FORCED"] = ssh.line_command(line) + " --timeout 60"
            os.environ["B123D_PRINT_FAKE_SSH_FORCED"] = env["B123D_PRINT_FAKE_SSH_FORCED"]
            ssh_cmd = [sys.executable, str(Path(__file__).with_name("fake_ssh.py"))]
        print(f"     ssh: {' '.join(ssh_cmd)} {dest}")
        async with Client(StdioServerParameters(command=ssh_cmd[0], args=ssh_cmd[1:] + [dest], env=env)) as c:
            await flow(c, pw, expect)
            await ssh_checks(c, ssh_cmd, dest, pw, expect)
    else:
        params = StdioServerParameters(command=cmd[0], args=cmd[1:] + ["--workspace", str(ws), "--timeout", "60"], env=env)
        async with Client(params) as c:
            await flow(c, ws, expect)

    print(f"\nworkspace: {ws}\nimages: {SAVE}")
    if not keep and ok:
        shutil.rmtree(ws, ignore_errors=True)
        tokfile.unlink(missing_ok=True)
    print("ALL PASSED" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main("--keep" in sys.argv, "--http" in sys.argv or "--split" in sys.argv, "--split" in sys.argv,
                     "--ssh" in sys.argv))
