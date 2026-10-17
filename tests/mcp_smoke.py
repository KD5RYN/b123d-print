"""End-to-end smoke test of b123d-print-mcp, as an MCP client would use it.

    uv run python tests/mcp_smoke.py [--keep]          # stdio: starts the server itself
    uv run python tests/mcp_smoke.py --http [--keep]   # starts it with --transport http and a token
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
import secrets
import shutil
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
    expect(tools >= {"use_printer", "list_parts", "new_part", "read_part", "write_part", "build_part", "render_preview", "section", "check", "export"}, f"tools: {sorted(tools)}")
    prompts = {p.name for p in (await c.list_prompts()).prompts}
    expect(prompts >= {"design_part_from_photos", "modify_part", "verify_part", "calibrate_hole_comp"}, f"prompts: {sorted(prompts)}")
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
    files = [x.strip() for x in text(res).splitlines() if x.strip().startswith("parts/")]
    expect(files == ["parts/box/out/box.3mf"] and (pw is None or [p.name for p in (pw / "parts/box/out").iterdir()] == ["box.3mf"]),
           "export honors formats='3mf'")
    res = await c.call_tool("export", {"name": "box", "formats": "obj"})
    expect(res.is_error and "unknown format" in text(res), "unknown format is refused with the choices")

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


async def http_checks(url: str, token: str, expect) -> None:
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
        r = await h.post(base, json=init, headers={**hdr, "Authorization": f"Bearer {token}"})
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
        server.terminate()
        code = await asyncio.to_thread(server.wait, 30)
        took = time.monotonic() - t0
        try:
            await asyncio.wait_for(call, 10)
        except BaseException:
            pass
    expect(code == 0 and took < 15, f"SIGTERM: server exits cleanly after the grace period (code {code}, {took:.1f} s)")
    expect(not beating(beat), "no build process left behind")


async def main(keep: bool, http: bool) -> None:
    ws = Path(tempfile.mkdtemp(prefix="b123d-print-smoke-"))
    # B123D_PRINT_SMOKE_CMD runs another launcher, e.g. "uvx --from dist/b123d_print-0.1.0-py3-none-any.whl b123d-print-mcp"
    cmd = os.environ.get("B123D_PRINT_SMOKE_CMD", f"{sys.executable} -m b123d_print.mcp_server").split()
    # a private user config, so use_printer never touches the real one
    env = {**os.environ, "XDG_CONFIG_HOME": str(ws / ".config")}
    url = os.environ.get("B123D_PRINT_SMOKE_URL")
    token = os.environ.get("B123D_PRINT_SMOKE_TOKEN") or os.environ.get("B123D_PRINT_TOKEN")
    ok = True

    def expect(cond, what):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + what)
        ok &= bool(cond)

    server = None
    if url or http:
        name = f"smoke-{secrets.token_hex(3)}"
        if not url:  # start our own HTTP server on a free port
            port, token = free_port(), secrets.token_urlsafe(24)
            server = subprocess.Popen(cmd + ["--workspace", str(ws), "--timeout", "60", "--transport", "http", "--port", str(port), "--shutdown-grace", "3"],
                                      env={**env, "B123D_PRINT_TOKEN": token})
            url = f"http://127.0.0.1:{port}/mcp"
            for _ in range(300):  # first start can be slow (imports, bytecode)
                try:
                    socket.create_connection(("127.0.0.1", port), 0.2).close()
                    break
                except OSError:
                    if server.poll() is not None:
                        sys.exit(f"server exited with {server.returncode}")
                    time.sleep(0.2)
            pw = ws / "workspaces" / name
        else:  # a running server; B123D_PRINT_SMOKE_WORKSPACE_DIR: its workspace folder, if visible from here
            wd = os.environ.get("B123D_PRINT_SMOKE_WORKSPACE_DIR")
            pw = Path(wd) / "workspaces" / name if wd else None
        print(f"     http: {url}  workspace {name}")
        try:
            if not token:
                sys.exit("B123D_PRINT_SMOKE_URL needs B123D_PRINT_SMOKE_TOKEN")
            await http_checks(url, token, expect)
            async with http_client(with_workspace(url, name), token) as c:
                await flow(c, pw, expect)
            if server:
                await shutdown_check(server, url, token, ws, expect)
                server = None
        finally:
            if server:
                server.terminate()
                server.wait(10)
    else:
        params = StdioServerParameters(command=cmd[0], args=cmd[1:] + ["--workspace", str(ws), "--timeout", "60"], env=env)
        async with Client(params) as c:
            await flow(c, ws, expect)

    print(f"\nworkspace: {ws}\nimages: {SAVE}")
    if not keep and ok:
        shutil.rmtree(ws, ignore_errors=True)
    print("ALL PASSED" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main("--keep" in sys.argv, "--http" in sys.argv))
