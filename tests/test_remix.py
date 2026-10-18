"""Remixing: import_model (mesh -> solid, units, repairs, limits, paths, cache), to-step, getting the
original onto the server (refs.store, SSH push, HTTP upload links), inherited findings, before/after."""

import io
import os
import re
import subprocess
import sys
import zipfile
from pathlib import Path

import numpy as np
import pytest
from build123d import Align, Box, Cylinder, Pos, Rot, export_step

from b123d_print import checks as ck, refs, remix, ssh
from b123d_print.compare import mesh_from_shape

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "src" / "b123d_print" / "examples" / "remix_bracket"
FAKE_SSH = f"{sys.executable} {ROOT / 'tests' / 'fake_ssh.py'}"


def write_stl(path: Path, tris: np.ndarray) -> Path:
    """Binary float32 STL, like a download."""
    rec = np.zeros(len(tris), dtype=[("n", "<f4", 3), ("v", "<f4", (3, 3)), ("a", "<u2")])
    rec["v"] = tris
    path.write_bytes(b"\0" * 80 + np.uint32(len(tris)).tobytes() + rec.tobytes())
    return path


def shape_stl(path: Path, shape, tol=0.01) -> Path:
    return write_stl(path, mesh_from_shape(shape, tol).triangles)


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    w = tmp_path / "ws"
    (w / "parts" / "rx" / "ref").mkdir(parents=True)
    (w / "b123d-print.toml").write_text("", encoding="utf-8")
    return w


# --- mesh -> solid -------------------------------------------------------------------------------


def test_box_merges_to_six_faces(tmp_path):
    part, info = remix.load(shape_stl(tmp_path / "box.stl", Box(20, 10, 5)))
    assert info.triangles == 12 and info.faces_after == 6 and info.planar_faces == 6
    assert part.is_valid and abs(part.volume - 1000) < 1e-3
    assert not info.faceted["faces"] and not info.warnings


def test_box_with_hole_keeps_volume_and_merges_planar_faces(tmp_path):
    shape = Box(30, 20, 8) - Cylinder(4, 10)
    part, info = remix.load(shape_stl(tmp_path / "boxhole.stl", shape))
    facets = info.faceted["faces"]
    assert facets > 12  # the hole stays faceted
    assert info.faces_after == 6 + facets  # top and bottom are one face each, with the hole as an inner loop
    assert part.is_valid and len(part.solids()) == 1
    mesh_volume = mesh_from_shape(shape, 0.01).volume
    assert abs(part.volume - mesh_volume) / mesh_volume < 1e-6
    top = [f for f in part.faces() if f.geom_type.name == "PLANE" and abs(f.center().Z - 4) < 1e-6]
    assert len(top) == 1 and len(top[0].inner_wires()) == 1
    assert any("faceted" in n for n in info.notes)


def test_inch_file_flagged_and_scaled(tmp_path):
    f = shape_stl(tmp_path / "inch.stl", Box(2, 1, 0.5))
    _, info = remix.load(f)
    assert any("inches" in w for w in info.warnings)
    part, info = remix.load(f, scale="inch")
    assert not info.warnings and abs(part.bounding_box().size.X - 50.8) < 1e-3


def test_step_units(tmp_path):
    f = tmp_path / "inch.step"
    export_step(Box(1, 1, 1), f)  # then make its length unit the inch, as an inch-based CAD writes it
    text = f.read_text(encoding="latin-1")
    text, n = re.subn(r"#(\d+) = \( LENGTH_UNIT\(\) NAMED_UNIT\(\*\) SI_UNIT\(\.MILLI\.,\.METRE\.\) \);",
                      r"#\1 = ( CONVERSION_BASED_UNIT('INCH',#99001) LENGTH_UNIT() NAMED_UNIT(#99002) );\n"
                      r"#99001 = LENGTH_MEASURE_WITH_UNIT(LENGTH_MEASURE(25.4),#99003);\n"
                      r"#99002 = DIMENSIONAL_EXPONENTS(1.,0.,0.,0.,0.,0.,0.);\n"
                      r"#99003 = ( LENGTH_UNIT() NAMED_UNIT(*) SI_UNIT(.MILLI.,.METRE.) );", text)
    assert n == 1
    f.write_text(text, encoding="latin-1")
    assert remix.step_units(f) == "inch"
    part, info = remix.load(f)
    assert abs(part.bounding_box().size.X - 25.4) < 1e-3 and info.format == "step"
    assert any("inch" in n for n in info.notes) and not info.warnings


def test_open_mesh_refused_small_gap_closed(tmp_path):
    tris = mesh_from_shape(Box(20, 20, 20) - Cylinder(5, 30), 0.01).triangles
    _, info = remix.load(write_stl(tmp_path / "gap.stl", tris[1:]))  # one triangle missing: closed
    assert any("closed 1 small hole" in r for r in info.repairs)
    c = tris.mean(1)
    keep = ~((np.abs(c[:, 2] - 10) < 1e-6) & (np.hypot(c[:, 0], c[:, 1]) > 5))  # the whole top face gone
    with pytest.raises(remix.MeshError, match="open mesh"):
        remix.load(write_stl(tmp_path / "open.stl", tris[keep]))


def test_non_manifold_refused(tmp_path):
    a = mesh_from_shape(Box(10, 10, 10), 0.01).triangles
    b = mesh_from_shape(Pos(10, 0, 0) * Box(10, 10, 10), 0.01).triangles  # shares a whole face: 4 triangles per edge there
    fin = np.array([[[5, -5, 5], [5, 5, 5], [5, 0, 15]]])
    with pytest.raises(remix.MeshError, match="non-manifold"):
        remix.load(write_stl(tmp_path / "nm.stl", np.concatenate([a, b, fin])))


def test_flipped_triangles_are_turned(tmp_path):
    tris = mesh_from_shape(Box(10, 10, 10), 0.01).triangles.copy()
    tris[:3] = tris[:3, ::-1]
    part, info = remix.load(write_stl(tmp_path / "flip.stl", tris))
    assert part.is_valid and abs(part.volume - 1000) < 1e-3 and any("turned" in r for r in info.repairs)


def test_triangle_limit(tmp_path):
    with pytest.raises(remix.MeshError, match="simplify it first"):
        remix.load(shape_stl(tmp_path / "s.stl", Box(10, 10, 10) - Cylinder(3, 20)), max_triangles=20)


def test_3mf_units_and_metadata(tmp_path):
    f = tmp_path / "m.3mf"
    model = ('<?xml version="1.0"?><model unit="inch" xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             '<metadata name="Designer">Ada</metadata><metadata name="LicenseTerms">CC-BY-4.0</metadata>'
             '<resources><object id="1" type="model"><mesh><vertices>'
             + "".join(f'<vertex x="{x}" y="{y}" z="{z}"/>' for x, y, z in
                       [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1)])
             + '</vertices><triangles><triangle v1="0" v2="2" v3="1"/><triangle v1="0" v2="1" v3="3"/>'
             '<triangle v1="0" v2="3" v3="2"/><triangle v1="1" v2="2" v3="3"/></triangles></mesh></object></resources>'
             '<build><item objectid="1"/></build></model>')
    with zipfile.ZipFile(f, "w") as z:
        z.writestr("3D/3dmodel.model", model)
    part, info = remix.load(f)
    assert info.units == "inch" and info.metadata == {"Designer": "Ada", "LicenseTerms": "CC-BY-4.0"}
    assert abs(part.bounding_box().size.X - 25.4) < 1e-3 and not info.warnings


def test_describe_finds_faceted_holes():
    s, _ = remix.describe(EXAMPLE / "ref" / "l_bracket.stl")
    got = sorted((h["d"], tuple(h["axis"])) for h in s["holes"])
    assert got == [(4.5, (0, 0, 1)), (4.5, (0, 0, 1)), (6.0, (0, 1, 0))]
    assert s["suggestion"]["path"] == "modify or redraw"


def test_to_step_cli(tmp_path):
    src = shape_stl(tmp_path / "b.stl", Box(20, 10, 5) - Cylinder(2, 10))
    r = subprocess.run([sys.executable, "-m", "b123d_print.cli", "to-step", str(src)], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert "faces before merging" in r.stdout and "curves stay faceted" in r.stdout
    assert (tmp_path / "b.step").stat().st_size > 1000


# --- import_model: paths, cache -------------------------------------------------------------------


def test_import_model_paths_and_cache(ws, tmp_path):
    shape_stl(ws / "parts" / "rx" / "ref" / "b.stl", Box(10, 10, 10))
    script = ws / "parts" / "rx" / "rx.py"
    remix.reset_imports()
    p = remix.import_model("ref/b.stl", script=script)
    assert abs(p.volume - 1000) < 1e-3 and remix.IMPORTED[-1][1].cached is False
    assert list((ws / "parts" / "rx" / "out" / ".cache").glob("*.brep"))
    remix.import_model("ref/b.stl", script=script)
    assert remix.IMPORTED[-1][1].cached is True
    (ws / "refs").mkdir()
    shape_stl(ws / "refs" / "shared.stl", Box(5, 5, 5))
    assert abs(remix.import_model("refs/shared.stl", script=script).volume - 125) < 1e-3  # workspace refs/
    shape_stl(tmp_path / "outside.stl", Box(5, 5, 5))
    with pytest.raises(ValueError, match="outside the workspace"):
        remix.import_model(str(tmp_path / "outside.stl"), script=script)
    with pytest.raises(ValueError, match="outside the workspace"):
        remix.import_model("../../../outside.stl", script=script)
    os.symlink(tmp_path / "outside.stl", ws / "parts" / "rx" / "ref" / "link.stl")
    with pytest.raises(ValueError, match="symlink"):
        remix.import_model("ref/link.stl", script=script)
    with pytest.raises(FileNotFoundError, match="upload_reference"):
        remix.import_model("ref/nope.stl", script=script)
    remix.reset_imports()


# --- refs.store, SSH push, HTTP upload -------------------------------------------------------------


def stl_bytes(tmp_path) -> bytes:
    return shape_stl(tmp_path / "x.stl", Box(10, 10, 10)).read_bytes()


@pytest.mark.parametrize("name", ["../x.stl", "a/b.stl", ".hidden.stl", "x.py", "x.stl.py", "", "x..stl", "x.stl ", "-x.stl"])
def test_store_refuses_bad_names(ws, tmp_path, name):
    with pytest.raises(refs.RefError):
        refs.store(ws, "parts", "rx", name, stl_bytes(tmp_path))


def test_store_rules(ws, tmp_path, monkeypatch):
    data = stl_bytes(tmp_path)
    p = refs.store(ws, "parts", "new_part", "Bracket v2 (1).stl", data)  # the part folder may not exist yet
    assert p == ws / "parts" / "new_part" / "ref" / "Bracket v2 (1).stl" and p.read_bytes() == data
    with pytest.raises(refs.RefError, match="already exists"):
        refs.store(ws, "parts", "new_part", "Bracket v2 (1).stl", data)
    refs.store(ws, "parts", "new_part", "Bracket v2 (1).stl", data, overwrite=True)
    with pytest.raises(refs.RefError, match="not an STL"):
        refs.store(ws, "parts", "rx", "x.stl", b"<html>error</html>")
    with pytest.raises(refs.RefError, match="not a STEP"):
        refs.store(ws, "parts", "rx", "x.step", b"import os")
    with pytest.raises(refs.RefError, match="bad part name"):
        refs.store(ws, "parts", "../rx", "x.stl", data)
    monkeypatch.setattr(refs, "MAX_BYTES", 100)
    with pytest.raises(refs.RefError, match="limit"):
        refs.store(ws, "parts", "rx", "big.stl", data)


def test_store_refuses_symlinks(ws, tmp_path):
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", ws / "parts" / "linked")
    with pytest.raises(refs.RefError, match="symlink"):
        refs.store(ws, "parts", "linked", "x.stl", stl_bytes(tmp_path))
    os.symlink(tmp_path / "elsewhere" / "t.stl", ws / "parts" / "rx" / "ref" / "t.stl")
    with pytest.raises(refs.RefError, match="symlink"):
        refs.store(ws, "parts", "rx", "t.stl", stl_bytes(tmp_path), overwrite=True)
    assert not list((tmp_path / "elsewhere").iterdir())


def test_ssh_push(ws, tmp_path):
    assert ssh.parse_request("push rx 'my part.stl' --overwrite") == ("push", {"part": "rx", "file": "my part.stl",
                                                                               "overwrite": True})
    for bad in ("push rx ../x.stl", "push ../rx x.stl", "push rx x.sh", "push rx", "push rx x.stl --evil"):
        with pytest.raises(ssh.Refused):
            ssh.parse_request(bad)
    data = stl_bytes(tmp_path)
    out, err = io.BytesIO(), io.StringIO()
    assert ssh.serve(str(ws), "me@cad", None, "push rx x.stl", stdout=out, stderr=err, stdin=io.BytesIO(data)) == 0
    assert (ws / "parts" / "rx" / "ref" / "x.stl").read_bytes() == data and b"stored" in out.getvalue()
    err = io.StringIO()
    assert ssh.serve(str(ws), "me@cad", None, "push rx y.stl", stdout=io.BytesIO(), stderr=err,
                     stdin=io.BytesIO(b"#!/bin/sh")) == 1 and "not an STL" in err.getvalue()


def test_ssh_push_end_to_end(ws, tmp_path, monkeypatch):
    forced = ssh.line_command(ssh.key_line(
        "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKCbiyMIpQvcOhoPsC6yzJoIhRkkG7wuIPlTJDRKILTV laptop", ws, "me@cad",
        prog=[sys.executable, "-m", "b123d_print.cli"]))
    monkeypatch.setenv("B123D_PRINT_FAKE_SSH_FORCED", forced)
    src = shape_stl(tmp_path / "Bracket v2.stl", Box(10, 10, 10))
    assert "stored parts/rx/ref/Bracket v2.stl" in ssh.push(src, "rx", "me@cad", ssh=FAKE_SSH)
    with pytest.raises(RuntimeError, match="already exists"):
        ssh.push(src, "rx", "me@cad", ssh=FAKE_SSH)
    r = subprocess.run([sys.executable, "-m", "b123d_print.cli", "push", str(src), "--part", "rx", "--to", "me@cad",
                        "--name", "copy.stl", "--ssh", FAKE_SSH], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (ws / "parts" / "rx" / "ref" / "copy.stl").read_bytes() == src.read_bytes()


def test_http_upload_link(ws, tmp_path, monkeypatch):
    from starlette.testclient import TestClient

    from b123d_print import links, mcp_server as srv

    monkeypatch.setitem(srv.STATE, "root", ws)
    monkeypatch.setitem(srv.STATE, "transport", "http")
    monkeypatch.setitem(srv.STATE, "link_secret", b"k" * 32)
    data = stl_bytes(tmp_path)
    text = srv.upload_reference("rx", "orig.stl")
    url = re.search(r"'(/upload/\S+)'", text).group(1)
    client = TestClient(srv.http_app("127.0.0.1", None))
    assert client.put(url, content=data).status_code == 201
    assert (ws / "parts" / "rx" / "ref" / "orig.stl").read_bytes() == data
    assert client.put(url, content=data).status_code == 409  # no overwrite on this link
    assert client.put(url.replace("orig.stl", "other.stl"), content=data).status_code == 404  # signed for one path
    dl, _ = links.sign(b"k" * 32, "_", "parts/rx/ref/x.stl", 60)  # a download signature is not an upload one
    assert client.put(dl.replace("/files/", "/upload/"), content=data).status_code == 404
    up, _ = links.sign(b"k" * 32, "_", "parts/rx/x.stl", 60, purpose="put")  # only into ref/
    assert client.put(up, content=data).status_code == 404
    up, _ = links.sign(b"k" * 32, "_", "parts/rx/ref/e.stl", -1, purpose="put")
    assert client.put(up, content=data).status_code == 410
    up, _ = links.sign(b"k" * 32, "_", "parts/rx/ref/big.stl", 60, purpose="put")
    monkeypatch.setattr(refs, "MAX_BYTES", 100)
    assert client.put(up, content=data).status_code == 413
    import base64

    monkeypatch.setattr(refs, "MAX_BYTES", 50_000_000)
    assert "Stored" in srv.upload_reference("rx", "b64.stl", base64.b64encode(data).decode())
    from mcp.server.mcpserver.exceptions import ToolError

    with pytest.raises(ToolError):
        srv.upload_reference("rx", "../b64.stl", "AAAA")


# --- inherited vs new findings, before/after, the example ----------------------------------------------


def F(level, check, items, key="spots", msg="m"):
    return ck.Finding(level, check, "part", msg, {key: [{"at" if key == "spots" else "center": list(p)} for p in items]})


def test_mark_inherited():
    orig = [F(ck.FAIL, "thin", [(0, 0, 0), (10, 0, 0)]), F(ck.WARN, "overhang", [(5, 5, 5)], "faces")]
    got = remix.mark_inherited([F(ck.FAIL, "thin", [(0.3, 0, 0)]), F(ck.WARN, "overhang", [(5, 5, 5), (30, 0, 0)], "faces"),
                                F(ck.WARN, "bed edge", [(1, 1, 0)], "faces"), F(ck.OK, "holes", [])], orig)
    thin, over, bed, ok = got
    assert thin.level == ck.WARN and thin.message.startswith("inherited from the original (a FAIL on the original too)")
    assert over.level == ck.WARN and "1 of 2" in over.message and "(30, 0, 0)" in over.message
    assert bed.message == "m" and not bed.data.get("inherited")  # the original had none
    assert ok.level == ck.OK


def test_inherited_and_new_findings_in_a_script(ws):
    """The original's faceted horizontal hole is an inherited overhang; a ledge the remix adds is new."""
    ref = ws / "parts" / "rx" / "ref" / "o.stl"
    shape_stl(ref, Box(30, 10, 30, align=(Align.CENTER, Align.CENTER, Align.MIN)) - Pos(0, 0, 15) * Rot(90, 0, 0) * Cylinder(4, 20),
              tol=0.05)
    (ws / "parts" / "rx" / "rx.py").write_text('''
from build123d import Box, Pos
from b123d_print import import_model


def build(d=None):
    return import_model("ref/o.stl") + Pos(-25, 0, 27) * Box(20, 10, 2)   # a ledge hanging off the side
''', encoding="utf-8")
    from b123d_print.config import load_settings
    from b123d_print.project import load, run_checks

    script = ws / "parts" / "rx" / "rx.py"
    found = run_checks(load(script), "", load_settings(script))
    imp = [f for f in found if f.check == "import"]
    assert len(imp) == 1 and "o.stl" in imp[0].target
    over = [f for f in found if f.check == "overhang"]
    assert len(over) == 1 and "inherited from the original" in over[0].message and "new in the remix" in over[0].message
    assert "-25" in over[0].message.split("new in the remix")[1]


def test_example_checks_and_before_after(tmp_path):
    from b123d_print.config import load_settings
    from b123d_print.project import before_after, built, dims, load, run_checks

    script = EXAMPLE / "remix_bracket.py"
    mod = load(script)
    found = run_checks(mod, "", load_settings(script))
    assert not [f for f in found if f.level == ck.FAIL], [f.line() for f in found]
    assert any(f.check == "overhang" and f.data.get("inherited") is True for f in found)
    parts, orig, imports = built(mod, dims(mod, ""))
    assert orig is not None and imports[0].format == "stl"
    r = before_after(orig, parts, tmp_path, "rb", size="small")
    assert all(Path(f).is_file() for f in r["files"]) and 0 < r["score"] < 100


def test_new_part_from_example_copies_the_reference(tmp_path):
    from b123d_print.cli import new_part

    p = new_part(tmp_path, "parts", "my_bracket", example="remix_bracket")
    assert (p.parent / "ref" / "l_bracket.stl").read_bytes() == (EXAMPLE / "ref" / "l_bracket.stl").read_bytes()
