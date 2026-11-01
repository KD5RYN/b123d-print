"""The replication spec (#165): MEASURE.md parsed, joined with the Dims, and its flags."""

import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest

from b123d_print import replicate as rp

ROOT = Path(__file__).resolve().parents[1]
HEADER = ("| Feature | Value | Method | Accuracy | Status | Class | Source | Field | Why changed |\n"
          "| --- | --- | --- | --- | --- | --- | --- | --- | --- |\n")


@dataclass(frozen=True)
class D:
    HOLE_D: float = 4.2
    SPACING: float = 83.3
    W: float = 125.0
    RIM: float = 2.35
    WALL: float = 2.4
    HOLES: tuple = ((0, 1), (2, 3))

    @property
    def INSIDE(self):
        return self.W - 2 * self.RIM


def run(rows: str, d=D(), **kw) -> dict:
    parsed, cols = rp.parse(HEADER + rows)
    return rp.spec(parsed, cols, d, **kw)


def messages(res: dict, level: str = "WARN") -> list[str]:
    return [f"{f['feature']}: {f['message']}" for f in res["flags"] if f["level"] == level]


def test_readings_average_inches_and_notes():
    assert rp.readings("4.21, 4.19; 4.22") == ([4.21, 4.19, 4.22], False)
    assert rp.readings("83.3 (3-9/32 in, NEMA WD-6)") == ([83.3], False)  # the note is not a reading
    v, inch = rp.readings("3-9/32 in")
    assert inch and v == [pytest.approx(83.34375)]
    assert rp.readings('1.5"')[0] == [pytest.approx(38.1)]
    assert rp.readings("") == ([], False) and rp.readings("TBD") == ([], False)


def test_parse_columns_by_name_and_only_feature_tables():
    text = ("## Offsets\n| Station | Height |\n| --- | --- |\n| 0 | 12 |\n\n"
            "| Field | Feature | Value | Tol | Class |\n|---|---|---|---|---|\n| HOLE_D | hole | ~4.2 | ±0.05 | Critical |\n")
    rows, cols = rp.parse(text)
    assert [r.feature for r in rows] == ["hole"]  # the offsets table has no Feature column
    r = rows[0]
    assert (r.field, r.klass, r.tol, r.source) == ("HOLE_D", "critical", 0.05, "estimate")
    assert r.estimated and "klass" in cols


def test_matching_spec_has_no_flags_and_a_table():
    res = run("| hole | 4.21, 4.19, 4.20 | calipers | ±0.05 | CONFIRMED | critical | measured | HOLE_D | |\n"
              "| inside | 120.3 | calipers | ±0.1 | CONFIRMED | free | measured | W - 2 * RIM | |\n"
              "| spacing | 3-9/32 in | standard | ±0.2 | | critical | standard | SPACING | |\n")
    assert res["flags"] == [] and res["counts"] == {"critical": 2, "free": 1}
    md = rp.text(res, "plate")
    assert "| hole | `HOLE_D` | critical | measured | 4.2 (×3, spread 0.02) | ±0.05 | 4.2 | +0.00 |  |" in md
    assert "(from in)" in md and "No flags" in md


def test_critical_estimate_unmeasured_and_untraced_are_warned():
    res = run("| notch | ~4 | photo | ±1 | estimated | critical | | HOLE_D | |\n"
              "| boss | | calipers, depth rod | | | critical | | | |\n")
    w = messages(res)
    assert w[0].startswith("notch: critical but an estimate: measure it (photo)")
    assert w[1] == "boss: critical and not measured yet (calipers, depth rod)"
    assert w[2].startswith("boss: critical with no Field")


def test_spread_wider_than_accuracy_suggests_draft():
    res = run("| wall | 2.1, 2.4, 2.6 | calipers | ±0.05 | CONFIRMED | critical | measured | WALL | |\n"
              "| rib | 1.0, 1.3 | calipers | ±0.05 | | free | measured | | |\n")
    assert len(messages(res)) == 1 and "spread 0.50 mm" in messages(res)[0] and "draft" in messages(res)[0]
    assert messages(res, "NOTE")[0].startswith("rib: readings spread 0.30 mm")  # free: a note, not a warning


def test_changed_value_needs_a_reason_and_default_tolerance():
    res = run("| hole | 4.0 | calipers | | CONFIRMED | critical | measured | HOLE_D | |\n"
              "| wall | 1.8 | calipers | ±0.05 | | free | changed | WALL | thicker for FDM: 6 lines |\n"
              "| width | 125.05 | calipers | | | free | measured | W | |\n")
    w = messages(res)
    assert len(w) == 1 and w[0].startswith("hole: modeled 4.2 differs from measured 4 by +0.20 mm (more than ±0.1)")
    wall = next(e for e in res["rows"] if e["feature"] == "wall")
    assert wall.get("changed") and wall["delta"] == pytest.approx(0.6)
    assert messages(res, "NOTE") == []  # 0.05 is inside the default ±0.1


def test_unknown_field_bad_expression_and_non_numbers():
    res = run("| a | 1 | | | | free | | NOPE | |\n| b | 1 | | | | free | | W ** 2 | |\n"
              "| c | 1 | | | | free | | HOLES | |\n| d | 1 | | | | free | | _private | |\n"
              "| e | 1 | | | | free | | W / 0 | |\n| f | 1 | | | | free | | HOLES * W | |\n")
    w = messages(res)
    assert w[0] == "a: Field 'NOPE': no Dims field NOPE" and "W ** 2" in w[1] and "_private" in w[2]
    assert w[3] == "e: Field 'W / 0': division by zero" and w[4].startswith("f: Field 'HOLES * W': cannot compute it")
    c = next(e for e in res["rows"] if e["feature"] == "c")
    assert c["modeled"].startswith("((0, 1)") and "delta" not in c


def test_plain_measurement_sheet_gets_a_hint_and_unclassified_rows_a_note():
    rows, cols = rp.parse("| Feature | Value | Method | Accuracy | Status |\n| --- | --- | --- | --- | --- |\n"
                          "| length | 182.4 | calipers | ±0.1 | CONFIRMED |\n")
    res = rp.spec(rows, cols, None)
    assert not res["replication"] and "plain measurement sheet" in messages(res, "NOTE")[0]
    res = run("| a | 1 | | | | | | | |\n| b | 2 | | | | important | | | |\n")
    notes = messages(res, "NOTE")
    assert any("class 'important'" in n for n in notes) and any("1 row(s) without a Class: a" in n for n in notes)


def test_variant_differences_are_the_variants_own():
    std = D()
    big = D(W=140.0)
    res = run("| width | 125 | calipers | ±0.1 | | free | measured | W | |\n"
              "| inside | 120.3 | calipers | ±0.1 | | free | measured | INSIDE | |\n"
              "| hole | 4.0 | calipers | | | critical | measured | HOLE_D | |\n", d=big, base=std, variant="140")
    by = {e["feature"]: e for e in res["rows"]}
    assert by["width"]["why"] == by["inside"]["why"] == "(variant 140)"  # a derived value follows its field
    assert [m.split(":")[0] for m in messages(res)] == ["hole"]  # the same in every variant: still flagged


def _cli(*args, cwd):
    return subprocess.run([sys.executable, "-m", "b123d_print.cli", *args], cwd=cwd, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env={**os.environ, "PYTHONIOENCODING": "ascii"})  # an ASCII runner


def test_example_and_cli(tmp_path):
    from b123d_print.cli import init_workspace, new_part

    init_workspace(tmp_path)
    p = new_part(tmp_path, "parts", "plate", example="plate_2gang_to_1gang")
    assert (p.parent / "MEASURE.md").is_file() and (p.parent / "ref/original_drawing.png").is_file()
    r = _cli("spec", "plate", "--strict", cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    assert "9 critical, 13 free" in r.stdout and "No flags" in r.stdout
    assert "| Δ |" in r.stdout and "±0.05" in r.stdout  # piped: UTF-8 even on an ASCII console
    r = _cli("spec", "plate", "--variant", "140", cwd=tmp_path)
    assert r.stdout.count("(variant 140)") == 5
    (p.parent / "MEASURE.md").write_text((p.parent / "MEASURE.md").read_text(encoding="utf-8").replace(
        "| 3.7 | calipers", "| 3.4, 3.5, 3.9 | calipers"), encoding="utf-8")
    r = _cli("spec", "plate", "--strict", cwd=tmp_path)
    assert r.returncode == 1 and "Box screw hole Ø (MEASURE.md line 22): readings spread 0.50 mm" in r.stdout
    (p.parent / "MEASURE.md").unlink()
    r = _cli("spec", "plate", cwd=tmp_path)
    assert r.returncode != 0 and "does not exist" in r.stderr


def test_spec_export_format(tmp_path):
    from b123d_print.cli import init_workspace, new_part
    from b123d_print.project import export_variant, load

    init_workspace(tmp_path)
    p = new_part(tmp_path, "parts", "blk")
    p.write_text(
        "from dataclasses import dataclass\nfrom build123d import Box, Align\n\n"
        "@dataclass(frozen=True)\nclass Dims:\n    W: float = 20.0  # MEASURE.md\n\n"
        "VARIANTS = {'': {}}\n\ndef build(d):\n    return Box(d.W, 10, 5, align=(Align.CENTER, Align.CENTER, Align.MIN))\n",
        encoding="utf-8")
    res = export_variant(load(p), p, "", formats=("spec",))
    assert "spec" not in res and not any(f.endswith("_spec.md") for f in res["files"])  # no MEASURE.md: nothing
    (p.parent / "MEASURE.md").write_text(HEADER + "| width | 20.4 | calipers | ±0.1 | | critical | measured | W | |\n",
                                         encoding="utf-8")
    res = export_variant(load(p), p, "", formats=("spec",))
    f = p.parent / "out/docs/blk_spec.md"
    assert str(f) in res["files"] and res["spec"].startswith("replication spec: 1 critical, 0 free; 1 warning")
    assert "differs from measured 20.4" in f.read_text(encoding="utf-8")


def test_prompt_carries_the_phases_and_the_molded_rules():
    from b123d_print import mcp_server as m

    fn = getattr(m.replicate_part, "fn", m.replicate_part)
    text = fn("clip", "a molded cable clip")
    order = [text.index(k) for k in ("1. IDENTIFY", "2. MEASUREMENT PLAN", "3. CLASSIFY AND DECIDE", "4. MODEL",
                                     "5. VERIFY", "| Draft", "| Living hinge", "The full rules")]
    assert order == sorted(order)
    assert "parts/clip/MEASURE.md" in text and "replication_spec('clip')" in text and "STOP" in text
    assert set(f"C{i}" for i in range(1, 13)) <= set(re.findall(r"C\d+", text))
