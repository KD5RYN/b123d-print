"""The print sheet (`print` export format): what it says, and that it stays out of the defaults."""

from __future__ import annotations

from b123d_print import handoff, links, printsheet, project
from b123d_print.config import DEFAULT_FORMATS, load_settings, parse_formats

SCRIPT = '''
from dataclasses import dataclass
from build123d import Align, Box, Cylinder, Pos

A = (Align.CENTER, Align.CENTER, Align.MIN)
from b123d_print import Wall

@dataclass(frozen=True)
class Dims:
    W: float = 40.0  # test
    H: float = 30.0  # test
    STYLE: str = "structural"  # test
    PRINT_NOTES: tuple = ("Press the pin into the base before gluing.",)  # test

def base(d):
    b = Box(d.W, d.W, 6, align=A) - Pos(0, 0, 3) * Cylinder(1.3, 6)  # an M3 pilot
    return b + Pos(0, 0, 6) * Box(10, d.W, 4, align=A) + Pos(0, 0, 10) * Box(d.W, 4, 2, align=A)

def pin(d):
    return Pos(60, 0, 0) * Box(4, 4, d.H, align=A)

def build(d):
    return {"base": lambda: base(d), "pin": lambda: pin(d)}

def checks(d):
    return [Wall("base", "XY", 3, near=(0, 0), radius=4, label="pilot boss")]

VARIANTS = {"": {}, "wide": dict(W=60.0)}
'''


def init_workspace(root):
    (root / "b123d-print.toml").write_text("", encoding="utf-8")  # isolates the test from the user's config


def _part(tmp_path):
    init_workspace(tmp_path)
    folder = tmp_path / "parts" / "duo"
    folder.mkdir(parents=True)
    script = folder / "duo.py"
    script.write_text(SCRIPT, encoding="utf-8")
    return script


def test_format_is_opt_in():
    assert "print" not in DEFAULT_FORMATS and "print" in parse_formats("all")
    assert parse_formats("3mf,print") == ("3mf", "print")
    assert links.content_type("parts/p/out/p_print.md").startswith("text/markdown")


def test_export_writes_the_sheet(tmp_path):
    script = _part(tmp_path)
    mod = project.load(script)
    s = project.export_variant(mod, script, "wide", formats=("print",))
    sheet = tmp_path / "parts/duo/out/duo_wide_print.md"
    assert [str(sheet)] == s["files"]
    text = sheet.read_text(encoding="utf-8")
    assert text.startswith("# duo_wide: print sheet")
    assert "| base | 60 × 60 × 12 |" in text and "| pin | 4 × 4 × 30 |" in text and "| **all** |" in text
    assert "print orientation" in text and "Z = 0" in text
    assert "**pin**: tip-over risk" in text  # 30 mm tall on 4 x 4
    assert "would need supports" in text and "**Supports: on, suggested from the geometry/style**" in text  # the bar at Z 10 has no wall under its ends
    assert "4-6 walls" in text and "along the layers" in text  # structural style
    assert "M3" in text and "pilot boss (base" in text
    assert "Press the pin into the base before gluing." in text
    assert "hole_comp was 0" in text and "per side" in text


def test_sheet_goes_home(tmp_path):
    script = _part(tmp_path)
    project.export_variant(project.load(script), script, "", formats=("print", "stl"))
    got = [rel for rel, _ in handoff.part_files(tmp_path, "parts", "duo", formats=["print"])]
    assert "out/duo_print.md" in got and not any(r.endswith(".stl") for r in got)
    assert [rel for rel, _ in handoff.part_files(tmp_path, "parts", "duo", variant="standard")
            if rel.endswith(".md")] == ["out/duo_print.md"]


def test_single_part_sheet_is_short(tmp_path):
    init_workspace(tmp_path)
    folder = tmp_path / "parts" / "blk"
    folder.mkdir(parents=True)
    script = folder / "blk.py"
    script.write_text("from dataclasses import dataclass\nfrom build123d import Box\n\n@dataclass(frozen=True)\n"
                      "class Dims:\n    W: float = 20.0  # test\n\ndef build(d):\n    return Box(d.W, d.W, 5).translate((0, 0, 2.5))\n",
                      encoding="utf-8")
    mod = project.load(script)
    d = project.dims(mod, "")
    text = printsheet.sheet(mod, d, {"": mod.build(d)}, load_settings(script), "blk")
    assert "| part | 20 × 20 × 5 |" in text and "no supports needed" in text
    assert "Assembly" not in text and "tip-over" not in text and "Hole compensation" not in text
    assert "functional style" in text
