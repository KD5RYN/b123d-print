"""The shopping list of declared hardware: bom.md, bom.csv, hardware_list and `b123d-print bom`."""

import csv
import io
import re

import anyio
import pytest

from b123d_print import Hardware, handoff, hardware, project, ssh
from b123d_print.config import DEFAULT_FORMATS, out_file_wanted, parse_formats

from test_hardware import HOOK
from test_printsheet import SCRIPT, _part

SCREW = dict(specification="M3 x 10 mm ISO 4762", source_url="https://example.invalid/m3")


def squash(text: str) -> str:
    return re.sub(" +", " ", text)  # the table is padded into columns


def rows(*groups, count=1):
    return hardware.bom_rows(list(groups), count)


def test_identical_items_merge_and_sum():
    got = rows(("", [Hardware("lid", "Lid screw", 4, location="lid", **SCREW),
                     Hardware("lid2", "lid  SCREW", 2, location="hinge", specification="m3 x 10 mm iso 4762"),
                     Hardware("nut", "Nut", 2, specification="M3 hex DIN 934")]))
    assert [(r["qty"], r["item"]) for r in got] == [(6, "Lid screw"), (2, "Nut")]
    assert got[0]["used_for"] == "lid; hinge" and got[0]["link"] == "https://example.invalid/m3"
    assert all(r["status"] == hardware.CONFIRMED for r in got)
    # Different specifications stay apart, even with one description.
    got = rows(("", [Hardware("a", "Screw", 1, specification="M3 x 10"), Hardware("b", "Screw", 1, specification="M3 x 12")]))
    assert [r["specification"] for r in got] == ["M3 x 10", "M3 x 12"]


def test_unconfirmed_items_are_flagged_and_never_merged():
    got = rows(("a", [Hardware("insert", "Insert", 2, note="Confirm maker")]), ("b", [Hardware("insert", "Insert", 3)]),
               ("c", [Hardware("s", "Screw", 1, specification="M3, length unknown", needs_confirmation=True),
                      Hardware("t", "Screw", 1, specification="M3, length unknown")]))
    inserts = [r for r in got if r["item"] == "Insert"]
    assert [(r["qty"], r["used_for"]) for r in inserts] == [(2, "a"), (3, "b")]  # nothing says they are one thing
    assert inserts[0]["specification"] == "not specified; Confirm maker"
    screw = [r for r in got if r["item"] == "Screw"]
    assert len(screw) == 1 and screw[0]["qty"] == 2 and screw[0]["status"] == hardware.CHECK  # one unconfirmed taints the line
    table = hardware.bom_markdown(got, "x")
    assert table.count("**check before ordering**") == 3
    assert "Total: 7 items on 3 lines, 3 to check before ordering." in table


def test_count_multiplies():
    items = [Hardware("lid", "Lid screw", 4, **SCREW)]
    assert rows(("", items), count=4)[0]["qty"] == 16
    for bad in (0, -1, 1.5, True):
        with pytest.raises(ValueError, match="count"):
            rows(("", items), count=bad)


def test_markdown_is_plain_text_and_safe():
    items = [Hardware("lid", "Lid screw", 4, location="lid_corner", **SCREW),
             Hardware("evil", "<script>x</script> | [a](javascript:alert(1)) *b*", 1, specification="a\nb",
                      source_url="javascript:alert(1)")]
    text = hardware.bom_markdown(rows(("", items)), "Hardware for wall_bracket")
    lines = text.splitlines()
    assert lines[0] == "# Hardware for wall_bracket"  # snake_case stays readable
    table = [x for x in lines if x.startswith("|")]
    assert len(table) == 4 and len({len(x) for x in table}) == 1  # padded into columns
    assert all(x.count("|") - x.count("\\|") == 7 for x in table)  # data adds no cells
    assert "<https://example.invalid/m3>" in text and "lid_corner" in text
    assert "<script>" not in text and "\\<script\\>" in text and "\\[a\\]" in text and "\\*b\\*" in text
    assert "<javascript" not in text  # only http(s) becomes a link
    assert "a b" in text  # a line break is a space, not a new row


def test_csv_quoting_and_formula_guard():
    items = [Hardware("f", '=HYPERLINK("http://x","click")', 1, specification="+1, then -2", location="@SUM(A1)"),
             Hardware("w", "＠wide", 2, specification="-3", source_url="https://example.invalid/a,b"),
             Hardware("ok", "Washer", 3, specification="M3 DIN 125, \"A2\"")]
    text = hardware.bom_csv(rows(("", items)))
    assert text.endswith("\r\n") and "\r\n" in text.rstrip("\r\n") and "\n" not in text.replace("\r\n", "")
    table = list(csv.reader(io.StringIO(text, newline="")))
    assert table[0] == list(hardware.BOM_COLUMNS)
    by_qty = {r[0]: r for r in table[1:]}
    assert by_qty["1"][1] == "'=HYPERLINK(\"http://x\",\"click\")" and by_qty["1"][2] == "'+1, then -2"
    assert by_qty["1"][3] == "'@SUM(A1)" and by_qty["1"][5] == "confirmed"
    assert by_qty["2"][1] == "'＠wide" and by_qty["2"][2] == "'-3" and by_qty["2"][4] == "https://example.invalid/a,b"
    assert by_qty["3"][2] == 'M3 DIN 125, "A2"'
    assert all(not c.startswith(hardware.FORMULA_START) for r in table for c in r)
    assert '"M3 DIN 125, ""A2"""' in text  # RFC 4180 quoting


def entry(part, items, variant="standard", variants=("standard",), declared=True):
    return {"part": part, "variant": variant, "variants": list(variants), "declared": declared,
            "items": [i.record() for i in items]}


def test_multi_part_totals():
    a = entry("lid_box", [Hardware("s", "Lid screw", 4, location="corners", **SCREW)], variants=("standard", "wide"))
    b = entry("bracket", [Hardware("m3", "Lid screw", 2, **SCREW), Hardware("mag", "Magnet", 2, specification="6x3 mm N52")],
              variant="tall", variants=("standard", "tall"))
    c = entry("plain", [], declared=False)
    text = hardware.shopping_list([a, b, c, {"part": "broken", "error": "SyntaxError: bad"}], count=3)
    assert text.startswith("# Hardware for lid_box, bracket (tall), plain\n")
    assert "Quantities for **3** of each assembly." in text
    assert "lid_box also has variant(s) wide" in text and "No `hardware(d)` declared in: plain." in text
    assert "Could not read broken: SyntaxError: bad" in text
    line = next(x for x in text.splitlines() if "Lid screw" in x)
    assert line.startswith("|  18 |") and "lid_box: corners; bracket (tall)" in line
    assert "Total: 24 items on 2 lines, all confirmed." in text
    data = list(csv.reader(io.StringIO(hardware.shopping_list([a, b], 1, "csv"), newline="")))
    assert sorted((r[0], r[1]) for r in data[1:]) == [("2", "Magnet"), ("6", "Lid screw")]
    with pytest.raises(ValueError, match="format"):
        hardware.shopping_list([a], 1, "xlsx")


def test_formats_are_opt_in_and_filtered_by_name():
    assert not {"bom", "bom_csv"} & set(DEFAULT_FORMATS)
    assert {"bom", "bom_csv"} <= set(parse_formats("all"))
    assert out_file_wanted("p_bom.md", ["bom"]) and not out_file_wanted("p_print.md", ["bom"])
    assert out_file_wanted("p_print.md", ["print"]) and not out_file_wanted("p_bom.md", ["print"])
    assert out_file_wanted("p_wide_bom.csv", ["bom_csv"]) and not out_file_wanted("other.csv", ["bom_csv"])
    assert not out_file_wanted("p_bom.csv", ["bom"]) and not out_file_wanted("p_trace.json", ["hardware"])
    assert out_file_wanted("p.3mf", ["3mf"])


def test_export_bom_files_variants_and_handoff(tmp_path):
    script = _part(tmp_path)
    script.write_text(SCRIPT + HOOK, encoding="utf-8")
    mod = project.load(script)
    project.export_variant(mod, script, "wide", formats=("bom", "bom_csv", "print"), only="pin")
    project.export_variant(mod, script, "", formats=("bom", "bom_csv"), only="pin")
    out = script.parent / "out"
    md = squash((out / "duo_wide_bom.md").read_text(encoding="utf-8"))
    assert md.startswith("# Hardware for duo (wide)\n") and "Variant: wide · exported 20" in md
    assert "| 6 | Lid screw | M3 x 10 mm ISO 4762 stainless A2 | lid corners | <https://example.invalid/spec> | confirmed" in md
    assert "| 2 | Insert" in md and "**check before ordering**" in md  # W=60: 6 screws, independent of only=
    assert "| 4 | Lid screw" in squash((out / "duo_bom.md").read_text(encoding="utf-8"))
    raw = (out / "duo_wide_bom.csv").read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf") and b"\r\n" in raw and b"\r\r\n" not in raw
    table = list(csv.reader(io.StringIO(raw.decode("utf-8-sig"), newline="")))
    assert table[0] == list(hardware.BOM_COLUMNS) and ["6", "Lid screw"] == table[2][:2]
    sheet = (out / "duo_wide_print.md").read_text(encoding="utf-8")
    assert "Full list to order from: the `bom`" in sheet and "hardware_list" in sheet
    (out / "unrelated.csv").write_text("x", encoding="utf-8")
    files = dict(handoff.part_files(tmp_path, "parts", "duo", variant="wide", formats=["bom", "bom_csv"]))
    assert set(files) == {"duo.py", "out/duo_wide_bom.md", "out/duo_wide_bom.csv"}
    files = dict(handoff.part_files(tmp_path, "parts", "duo", formats=["print"]))
    assert set(files) == {"duo.py", "out/duo_wide_print.md"}  # the print filter no longer brings the BOM
    files = dict(handoff.part_files(tmp_path, "parts", "duo", formats=["bom"]))
    assert set(files) == {"duo.py", "out/duo_bom.md", "out/duo_wide_bom.md"}
    assert {p.name for p in ssh.out_files(tmp_path, "duo", ["bom_csv"])} == {"duo_bom.csv", "duo_wide_bom.csv"}


def test_export_without_hook(tmp_path):
    script = _part(tmp_path)
    project.export_variant(project.load(script), script, "", formats=("bom", "bom_csv"), only="pin")
    md = (script.parent / "out/duo_bom.md").read_text(encoding="utf-8")
    assert "The script declares no hardware: it has no `hardware(d)`." in md and "| Qty" not in md
    assert (script.parent / "out/duo_bom.csv").read_bytes() == "\ufeffQty,Item,Specification,Used for,Source/link,Status\r\n".encode()


def test_cli_bom(tmp_path, capsys):
    from b123d_print.cli import main

    script = _part(tmp_path)
    script.write_text(SCRIPT + HOOK, encoding="utf-8")
    assert main(["--root", str(tmp_path), "bom", "duo", "--count", "2", "--variant", "wide"]) == 0
    out = squash(capsys.readouterr().out)
    assert out.startswith("# Hardware for duo (wide)") and "| 12 | Lid screw" in out and "Quantities for **2**" in out
    assert main(["--root", str(tmp_path), "bom", "--csv"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "Qty,Item,Specification,Used for,Source/link,Status"
    with pytest.raises(SystemExit, match="count"):
        main(["--root", str(tmp_path), "bom", "duo", "--count", "0"])
    with pytest.raises(SystemExit, match="no variant"):
        main(["--root", str(tmp_path), "bom", "duo", "--variant", "nope"])


PLATE = '''
from dataclasses import dataclass
from b123d_print import Hardware

@dataclass(frozen=True)
class Dims:
    N: int = 4  # test

VARIANTS = {"": {}, "big": dict(N=6)}

def build(d):
    raise RuntimeError("hardware_list must not build")

def hardware(d):
    return [Hardware("screw", "Lid screw", d.N, specification="M3 x 10 mm ISO 4762"),
            Hardware("insert", "Insert", 2)]
'''


def test_hardware_list_tool(tmp_path, monkeypatch):
    from mcp.server.mcpserver.exceptions import ToolError

    from b123d_print import mcp_server as m, sandbox

    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    monkeypatch.setitem(m.STATE, "root", tmp_path)
    monkeypatch.setitem(m.STATE, "queue", None)
    monkeypatch.setitem(m.STATE, "limiter", None)
    (tmp_path / "b123d-print.toml").write_text("", encoding="utf-8")
    for name, code in (("plate", PLATE), ("lid", PLATE.replace('"Insert", 2', '"Insert", 1'))):
        (tmp_path / "parts" / name).mkdir(parents=True)
        (tmp_path / "parts" / name / f"{name}.py").write_text(code, encoding="utf-8")

    def call(**kw):
        return anyio.run(lambda: m.hardware_list(**kw))

    text = squash(call(name="plate", count=2))
    assert text.startswith("# Hardware for plate\n") and "plate also has variant(s) big" in text
    assert "| 8 | Lid screw | M3 x 10 mm ISO 4762 |" in text and "| 4 | Insert" in text
    assert "Total: 12 items on 2 lines, 1 to check before ordering." in text
    text = squash(call(parts="plate:big,lid"))
    assert text.startswith("# Hardware for plate (big), lid\n")
    assert "| 10 | Lid screw" in text and "plate (big); lid" in text
    assert "| 2 | Insert" in text and "| 1 | Insert" in text  # unspecified: listed per part
    assert call() == call(parts="lid,plate")  # every part in the workspace
    assert call(name="plate", format="csv").splitlines()[0] == "Qty,Item,Specification,Used for,Source/link,Status"
    assert call(name="plate", variant="nope").startswith("ERROR: ")
    for bad in (dict(name="plate", count=0), dict(name="plate", format="xlsx"), dict(name="nosuch")):
        with pytest.raises(ToolError):
            call(**bad)
