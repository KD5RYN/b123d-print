"""End-to-end smoke test of b123d-print-mcp over stdio, as an MCP client would use it.

    uv run python tests/mcp_smoke.py [--keep]

Starts the server on a fresh temporary workspace, then drives every tool, prompt and resource.
Exits non-zero on the first failure. Images are saved next to the workspace for a look.
"""

import asyncio
import json
import base64
import os
import shutil
import sys
import tempfile
from pathlib import Path

from mcp import Client
from mcp.client.stdio import StdioServerParameters

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


async def main(keep: bool) -> None:
    ws = Path(tempfile.mkdtemp(prefix="b123d-print-smoke-"))
    # B123D_PRINT_SMOKE_CMD runs another launcher, e.g. "uvx --from dist/b123d_print-0.1.0-py3-none-any.whl b123d-print-mcp"
    cmd = os.environ.get("B123D_PRINT_SMOKE_CMD", f"{sys.executable} -m b123d_print.mcp_server").split()
    # a private user config, so use_printer never touches the real one
    env = {**os.environ, "XDG_CONFIG_HOME": str(ws / ".config")}
    params = StdioServerParameters(command=cmd[0], args=cmd[1:] + ["--workspace", str(ws), "--timeout", "60"], env=env)
    ok = True

    def expect(cond, what):
        nonlocal ok
        print(("PASS " if cond else "FAIL ") + what)
        ok &= bool(cond)

    async with Client(params) as c:
        tools = {t.name for t in (await c.list_tools()).tools}
        expect(tools >= {"use_printer", "list_parts", "new_part", "read_part", "write_part", "build_part", "render_preview", "section", "check", "export"}, f"tools: {sorted(tools)}")
        prompts = {p.name for p in (await c.list_prompts()).prompts}
        expect(prompts >= {"design_part_from_photos", "modify_part", "verify_part", "calibrate_hole_comp"}, f"prompts: {sorted(prompts)}")
        g = await c.get_prompt("design_part_from_photos", {"description": "a bracket"})
        expect("LIST EVERY DIMENSION" in g.messages[0].content.text, "prompt carries the confirm-dimensions rule")
        r = await c.read_resource("b123d-print://guide")
        expect("Verify before reporting" in r.contents[0].text, "guide resource")

        res = await c.call_tool("new_part", {"name": "box"})
        expect("Created" in text(res) and (ws / "parts/box/box.py").exists(), "new_part scaffolds parts/box/box.py")
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
            (ws / "preview.png").write_bytes(base64.b64decode(im[0].data))
        res = await c.call_tool("section", {"name": "box", "plane": "XZ", "at": 0.0})
        im = images(res)
        expect(im and im[0].mime_type == "image/png", "section returns a PNG")
        if im:
            (ws / "section.png").write_bytes(base64.b64decode(im[0].data))
        res = await c.call_tool("check", {"name": "box", "variant": "standard"})
        expect(text(res).startswith("PASSED") and "min wall" in text(res), "check passes on the standard box")
        res = await c.call_tool("check", {"name": "box", "variant": "thin"})
        expect(text(res).startswith("FAILED") and "[FAIL] wall" in text(res), "check catches the thin wall in the 'thin' variant")
        res = await c.call_tool("export", {"name": "box"})
        expect("box.stl" in text(res) and (ws / "parts/box/out/box_thin.3mf").exists(), "export writes STEP/STL/3MF/PNG for each variant")
        shutil.rmtree(ws / "parts/box/out")
        res = await c.call_tool("export", {"name": "box", "variant": "standard", "formats": "3mf"})
        expect(sorted(p.name for p in (ws / "parts/box/out").iterdir()) == ["box.3mf"], "export honors formats='3mf'")
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

    print(f"\nworkspace: {ws}")
    if not keep and ok:
        shutil.rmtree(ws)
    print("ALL PASSED" if ok else "SOME CHECKS FAILED")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main("--keep" in sys.argv))
