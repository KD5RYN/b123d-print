"""Declared assembly hardware, optional JSON export, and explicit nonprintable stand-ins."""

import json
from types import SimpleNamespace

import pytest

from b123d_print import Hardware, fit, handoff, hardware, project
from b123d_print.config import DEFAULT_FORMATS, load_settings, parse_formats

from test_export_cache import times
from test_printsheet import SCRIPT, _part

HOOK = '''
from b123d_print import Hardware

def hardware(d):
    return [Hardware("z-insert", "Insert", 2, note="Confirm manufacturer"),
            Hardware("a-screw", "Lid screw", int(d.W / 10),
                     specification="M3 x 10 mm ISO 4762 stainless A2", location="lid corners",
                     source_url="https://example.invalid/spec")]
'''


def test_records_are_validated_and_sorted():
    entries = [Hardware("z", "Magnet", 2), {"id": "a", "description": "Screw", "quantity": 4,
                                           "specification": "M3 x 10 mm ISO 4762"}]
    items = hardware.declared(SimpleNamespace(hardware=lambda d: iter(entries)), None)
    assert [v.id for v in items] == ["a", "z"]
    assert [v.record()["needs_confirmation"] for v in items] == [False, True]
    assert hardware.declared(SimpleNamespace(), None) is None
    assert hardware.document(None, "")["declared"] is False
    assert hardware.document([], "")["declared"] is True
    incomplete = Hardware("partial", "Screw", 2, specification="M3, length/head unknown", needs_confirmation=True)
    assert incomplete.record()["needs_confirmation"] is True
    assert "M3, length/head unknown &#40;needs confirmation&#41;" in "\n".join(hardware.markdown([incomplete], ""))


@pytest.mark.parametrize("entry", [
    dict(id="bad id", description="Screw", quantity=1),
    dict(id="screw", description="", quantity=1),
    dict(id="screw", description="Screw", quantity=0),
    dict(id="screw", description="Screw", quantity=-1),
    dict(id="screw", description="Screw", quantity=True),
    dict(id="screw", description="Screw", quantity=1.5),
    dict(id="screw", description="Screw", quantity="2"),
    dict(id="screw", description="Screw", quantity=2, source_url=42),
    dict(id="screw", description="Screw", quantity=2, needs_confirmation="yes"),
    dict(id="screw", description="Screw", quantity=2, surprise="unknown"),
    dict(id="screw", description="Screw"),
    "M3 screws",
])
def test_malformed_entries(entry):
    with pytest.raises(ValueError, match="hardware"):
        hardware.declared(SimpleNamespace(hardware=lambda d: [entry]), None)


@pytest.mark.parametrize("entries", [None, "screws", {"id": "screw"}, 123])
def test_malformed_hook(entries):
    with pytest.raises(ValueError, match=r"hardware\(d\)"):
        hardware.declared(SimpleNamespace(hardware=lambda d: entries), None)
    with pytest.raises(ValueError, match="callable"):
        hardware.declared(SimpleNamespace(hardware=[]), None)


@pytest.mark.parametrize("specification", ["M3 x 10", "M4 x 12"])
def test_duplicate_and_conflicting_ids_are_rejected(specification):
    entries = [Hardware("screw", "Screw", 2, specification="M3 x 10"),
               Hardware("screw", "Screw", 4, specification=specification)]
    with pytest.raises(ValueError, match="duplicate hardware id 'screw'"):
        hardware.declared(SimpleNamespace(hardware=lambda d: entries), None)


def test_export_variant_subset_and_handoff(tmp_path):
    script = _part(tmp_path)
    script.write_text(SCRIPT + HOOK, encoding="utf-8")
    mod = project.load(script)
    result = project.export_variant(mod, script, "wide", formats=("print", "hardware", "stl"), only="pin")
    assert set(result["parts"]) == {"pin"}
    out = script.parent / "out"
    sheet = (out / "duo_wide_print.md").read_text(encoding="utf-8")
    raw = (out / "duo_wide_hardware.json").read_text(encoding="utf-8")
    bom = json.loads(raw)
    assert bom["schema_version"] == 1 and bom["variant"] == "wide" and bom["scope"] == "whole_assembly"
    assert bom["declared"] is True
    assert [item["id"] for item in bom["items"]] == ["a-screw", "z-insert"]
    assert bom["items"][0]["quantity"] == 6  # variant W=60, independent of only='pin'
    assert "whole assembly of variant wide" in sheet and "not scaled by piece selection" in sheet
    assert "inferred and is not a shopping list" in sheet
    assert "| a-screw | Lid screw | M3 x 10 mm ISO 4762 stainless A2 | 6 | lid corners |" in sheet
    assert "| z-insert | Insert | Needs confirmation | 2 |" in sheet
    assert bom["items"][1]["needs_confirmation"] is True
    assert hardware.json_text(hardware.declared(mod, project.dims(mod, "wide")), "wide") == raw
    # The default variant gets its own quantities and files.
    project.export_variant(mod, script, "", formats=("hardware",), only="pin")
    assert json.loads((out / "duo_hardware.json").read_text())["items"][0]["quantity"] == 4
    for filename in ("duo_trace.json", "duo_wide_trace.json", "unrelated.json"):
        (out / filename).write_text("{}", encoding="utf-8")
    files = dict(handoff.part_files(tmp_path, "parts", "duo", variant="wide", formats=["print", "hardware"]))
    assert set(files) == {"duo.py", "out/duo_wide_print.md", "out/duo_wide_hardware.json"}
    files = dict(handoff.part_files(tmp_path, "parts", "duo", formats=["hardware"]))
    assert set(files) == {"duo.py", "out/duo_hardware.json", "out/duo_wide_hardware.json"}
    files = dict(handoff.part_files(tmp_path, "parts", "duo", variant="standard", formats=["hardware"]))
    assert set(files) == {"duo.py", "out/duo_hardware.json"}
    # Omitting the filter retains the existing whole-folder handoff behavior.
    assert "out/unrelated.json" in dict(handoff.part_files(tmp_path, "parts", "duo"))


def test_data_stays_data_and_models_are_lazy():
    def forbidden():
        pytest.fail("BOM must not construct a model or fetch anything")

    item = Hardware("custom", "<script>bad</script> | [link](file:///tmp/x)\nnext", 1,
                    source_url="javascript:alert(1)", source="ref/custom.stl", units="inch", model=forbidden)
    text = "\n".join(hardware.markdown([item], "wide"))
    assert "<script>" not in text and "[link]" not in text and "&#124;" in text and "<br>" in text
    assert "javascript:alert&#40;1&#41;" in text
    record = json.loads(hardware.json_text([item], "wide"))["items"][0]
    assert record["description"] == item.description and record["source_url"] == item.source_url
    assert "model" not in record


def test_bd_warehouse_metadata_and_standin():
    from bd_warehouse.fastener import HeatSetNut, HexNut, PlainWasher, SocketHeadCapScrew

    for fastener in (SocketHeadCapScrew("M3-0.5", 10), HeatSetNut("M4-0.7-8.1", "CNCKitchen"),
                     PlainWasher("M3", "iso7089"), HexNut("M3-0.5", "iso4032", hand="left")):
        item = Hardware.from_bd_warehouse("fastener", fastener, 4, location="corners")
        assert item.specification.startswith(fastener.info) and not item.record()["needs_confirmation"]
        if isinstance(fastener, HeatSetNut):
            assert "M4-0.7-8.1" in item.specification  # info alone loses the insert-length selector
        if getattr(fastener, "hand", "right") == "left":
            assert "left hand thread" in item.specification
        assert item.units == "mm" and item.source.endswith(type(fastener).__name__)
        shape, _, label = item.standin()
        assert shape is fastener and label == "fastener (stand-in)"
        assert fit.is_standin(label, {"base"})
    with pytest.raises(ValueError, match="bd_warehouse"):
        Hardware.from_bd_warehouse("mesh", object(), 1)


def test_imported_stl_is_hardware_not_printable(tmp_path):
    from build123d import Box, export_stl

    script = _part(tmp_path)
    ref = script.parent / "ref"
    ref.mkdir()
    export_stl(Box(1, 1, 1), ref / "sensor.stl")  # source is explicitly inches
    script.write_text(SCRIPT + '''
from b123d_print import Hardware, import_model

def hardware(d):
    return [Hardware("sensor", "Supplier sensor", 1, specification="ABC-123 rev B",
                     source="ref/sensor.stl", units="inch",
                     model=lambda: import_model("ref/sensor.stl", scale="inch"))]

def assembly(d):
    item = hardware(d)[0]
    return [(base(d), "orange", "base"), item.standin(label="board")]
''', encoding="utf-8")
    mod = project.load(script)
    result = project.export_variant(mod, script, "", formats=("hardware", "stl"), only="pin")
    assert set(result["parts"]) == {"pin"}
    assert not list((script.parent / "out").glob("*sensor.stl"))
    # BOM-only metadata did not import the model, but assembly uses the existing conversion.
    pc = project.Pieces(mod, project.dims(mod, ""))
    asm = pc.assembly()
    assert tuple(asm[1][0].bounding_box().size) == pytest.approx((25.4, 25.4, 25.4), abs=1e-6)
    assert asm[1][2] == "sensor: board (stand-in)" and pc.imports
    report = fit.run_fit(mod, "", load_settings(script))
    assert ["sensor: board (stand-in)", True] in report["items"]
    assert any(f.level == "fail" and "sensor" in f.target for f in report["findings"])
    checked = project.check_share(mod, "", load_settings(script))
    assert any(f["check"] == "import" and f["target"] == "sensor.stl" for f in checked["pre"])
    files = dict(handoff.part_files(tmp_path, "parts", "duo", formats=["hardware"]))
    assert set(files) == {"duo.py", "out/duo_hardware.json", "ref/sensor.stl"}
    entry = json.loads(files["out/duo_hardware.json"].read_text())["items"][0]
    assert entry["source"] == "ref/sensor.stl" and entry["units"] == "inch"


def test_assembly_import_notices_deduplicate_but_preserve_scale(tmp_path):
    from build123d import Box, export_stl

    script = _part(tmp_path)
    ref = script.parent / "ref"
    ref.mkdir()
    export_stl(Box(5, 5, 5), ref / "original.stl")
    script.write_text('''
from b123d_print import Hardware, import_model

def build():
    return import_model("ref/original.stl", scale="mm")

def assembly(d):
    same = Hardware("same", "Same model", 1, source="ref/original.stl", units="mm",
                    model=lambda: import_model("ref/original.stl", scale="mm"))
    other = Hardware("other", "Other scale", 1, source="ref/original.stl", units="cm",
                     model=lambda: import_model("ref/original.stl", scale="cm"))
    return [same.standin(), other.standin()]
''', encoding="utf-8")
    mod = project.load(script)
    checked = project.check_share(mod, "", load_settings(script))
    notices = [f for f in checked["pre"] if f["check"] == "import"]
    assert [f["data"]["scale"] for f in notices] == [1.0, 10.0]
    # built() still assigns only the printable import as the original, never the assembly one.
    _, original, imports = project.built(mod, None)
    assert original.volume == pytest.approx(125.0)
    assert len(imports) == 1 and imports[0].scale == 1.0


def test_model_requires_explicit_provenance_and_units():
    for extra in ({}, {"source": "ref/sensor.stl"}, {"units": "mm"}):
        with pytest.raises(ValueError, match="explicit source and units"):
            Hardware("sensor", "Sensor", 1, model=lambda: None, **extra)
    with pytest.raises(ValueError, match="model shape"):
        Hardware("sensor", "Sensor", 1, source="measured envelope", units="mm").standin()


def test_legacy_and_optional_format(tmp_path):
    script = _part(tmp_path)
    result = project.export_variant(project.load(script), script, "", formats=("print", "hardware"), only="pin")
    assert "hardware" not in DEFAULT_FORMATS and "hardware" in parse_formats("all")
    assert len(result["files"]) == 2
    sheet = (script.parent / "out/duo_print.md").read_text(encoding="utf-8")
    assert "Declared hardware" not in sheet
    bom = json.loads((script.parent / "out/duo_hardware.json").read_text())
    assert bom["items"] == [] and bom["declared"] is False


def test_hardware_export_in_worker(tmp_path, monkeypatch):
    from b123d_print import sandbox

    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    (tmp_path / "b123d-print.toml").write_text("", encoding="utf-8")
    script = tmp_path / "parts/plate/plate.py"
    script.parent.mkdir(parents=True)
    script.write_text('''
from build123d import Box
from b123d_print import Hardware

def build():
    return Box(10, 10, 5).translate((0, 0, 2.5))

def hardware(d):
    return [Hardware("screw", "Screw", 2, specification="M3, confirm length", needs_confirmation=True)]
''', encoding="utf-8")
    result = sandbox.run_job({"op": "export", "script": str(script), "formats": "print,hardware"},
                             tmp_path, script.parent / "out", timeout=120)
    assert result["ok"], result
    assert {p.rsplit("/", 1)[-1] for p in result["variants"][0]["files"]} == {"plate_print.md", "plate_hardware.json"}
    assert json.loads((script.parent / "out/plate_hardware.json").read_text())["items"][0]["needs_confirmation"] is True


def test_cache_tracks_declaration_and_variant_dims(tmp_path):
    script = _part(tmp_path)
    script.write_text(SCRIPT + HOOK, encoding="utf-8")

    def export(key=""):
        cfg = project.CacheConfig(tmp_path, project.ReadLog())
        return project.export_variant(project.load(script), script, key, formats=("print", "hardware"),
                                      only="pin", cache=cfg)

    first = export()
    before = times(first["files"])
    assert times(export()["files"]) == before
    script.write_text((SCRIPT + HOOK).replace('int(d.W / 10)', 'int(d.W / 10) + 1'), encoding="utf-8")
    after = times(export()["files"])
    assert all(after[name] != before[name] for name in before)
    assert json.loads((script.parent / "out/duo_hardware.json").read_text())["items"][0]["quantity"] == 5
    # Changing a dimension used only by hardware still invalidates both artifacts.
    code = script.read_text().replace('W: float = 40.0', 'W: float = 80.00')  # avoid same-size .pyc reuse
    script.write_text(code, encoding="utf-8")
    final = times(export()["files"])
    assert all(final[name] != after[name] for name in final)
    assert json.loads((script.parent / "out/duo_hardware.json").read_text())["items"][0]["quantity"] == 9
