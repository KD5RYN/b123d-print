"""out/'s folders (#124): which file goes where, the old flat layout, and that every reader
(download, pull, signed links) stays inside the part's out/ folder."""

import io
import os
import sys
import tarfile
import zipfile
from pathlib import Path

import pytest

from b123d_print import handoff, links, outdir, ssh

ROOT = Path(__file__).resolve().parents[1]
FAKE_SSH = f"{sys.executable} {ROOT / 'tests' / 'fake_ssh.py'}"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKCbiyMIpQvcOhoPsC6yzJoIhRkkG7wuIPlTJDRKILTV laptop"

NESTED = {"print/box.3mf": b"3mf", "print/box.stl": b"stl", "print/box_print.md": b"sheet",
          "print/templates/box_template_a.3mf": b"tpl", "cad/box.step": b"step", "cad/box_view.glb": b"glb",
          "images/box.png": b"png", "images/box_xz0.png": b"sec", "docs/box_bom.md": b"bom", "docs/box_bom.csv": b"csv",
          "docs/box_hardware.json": b"{}", "docs/box_view.html": b"<html>", "README.md": b"# box"}


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A workspace with one part exported in the new layout, plus things that must never be served."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    w = tmp_path / "ws"
    part = w / "parts" / "box"
    out = part / "out"
    out.mkdir(parents=True)
    (w / "b123d-print.toml").write_text("", encoding="utf-8")
    (part / "box.py").write_text("def build(d): ...\n", encoding="utf-8", newline="")
    for rel, data in NESTED.items():
        (out / rel).parent.mkdir(parents=True, exist_ok=True)
        (out / rel).write_bytes(data)
    (out / ".cache").mkdir()
    (out / ".cache" / "x.stl").write_bytes(b"cache")
    (out / "print" / ".hidden.stl").write_bytes(b"no")
    (out / "other").mkdir()
    (out / "other" / "x.stl").write_bytes(b"not a folder of the layout")
    (out / "print" / "deep").mkdir()
    (out / "print" / "deep" / "x.stl").write_bytes(b"too deep")
    (tmp_path / "secret.stl").write_bytes(b"outside")
    return w


def rels(files):
    return sorted(r for r, _ in files)


# --- which file goes where -------------------------------------------------------------------------


@pytest.mark.parametrize("name,template,folder", [
    ("box.3mf", False, "print"), ("box.STL", False, "print"), ("box_print.md", False, "print"),
    ("box_template_a.3mf", True, "print/templates"), ("box_template_a.stl", True, "print/templates"),
    ("box_template_a.step", True, "cad"), ("box_template_a_where.png", True, "images"),
    ("box.step", False, "cad"), ("box_view.glb", False, "cad"), ("box_assembly_view.glb", False, "cad"),
    ("box.png", False, "images"), ("box_xy3_small.png", False, "images"), ("box_vs_original.png", False, "images"),
    ("box_bom.md", False, "docs"), ("box_bom.csv", False, "docs"), ("box_hardware.json", False, "docs"),
    ("box_view.html", False, "docs"), ("scan_outline.json", False, "docs"), ("scan_outline.py", False, "docs")])
def test_folder(name, template, folder):
    assert outdir.folder(name, template) == folder


def test_path_makes_the_folder(tmp_path):
    p = outdir.path(tmp_path / "out", "box.3mf")
    assert p == tmp_path / "out" / "print" / "box.3mf" and p.parent.is_dir()
    assert outdir.path(tmp_path / "out", "box.3mf", template=True) == tmp_path / "out" / "print" / "templates" / "box.3mf"


def test_out_of(tmp_path):
    out = tmp_path / "parts" / "box" / "out"
    for f in ("box.3mf", "print/box.3mf", "print/templates/t.stl", "cad/box_view.glb", "docs/x.html"):
        assert outdir.out_of(out / f) == out, f
    for f in (tmp_path / "x.glb", out / "other" / "x.glb", out / "print" / "deep" / "x.stl", tmp_path / "cad" / "x.glb"):
        assert outdir.out_of(f) is None, f


def test_files_lists_only_the_layout(ws):
    got = rels(outdir.files(ws / "parts/box/out"))
    assert got == sorted(NESTED)  # no .cache/, hidden files, other/ or print/deep/


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need rights on Windows")
def test_files_never_follow_a_symlink(ws, tmp_path):
    out = ws / "parts/box/out"
    os.symlink(tmp_path / "secret.stl", out / "print" / "link.stl")
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "x.png").write_bytes(b"outside")
    import shutil

    shutil.rmtree(out / "images")
    os.symlink(tmp_path / "elsewhere", out / "images")
    got = rels(outdir.files(out))
    assert "print/link.stl" not in got and not any(r.startswith("images/") for r in got)


# --- the old flat layout --------------------------------------------------------------------------


def test_tidy_moves_old_flat_files(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    for n in ("box.3mf", "box.step", "box.png", "box_bom.md", "box_template_a.stl", "README.md"):
        (out / n).write_bytes(b"old " + n.encode())
    (out / "print").mkdir()
    (out / "print" / "box.3mf").write_bytes(b"new")  # already exported in the new layout: the flat one goes
    done = outdir.tidy(out)
    assert sorted(done) == ["box.3mf", "box.png", "box.step", "box_bom.md", "box_template_a.stl"]
    assert sorted(p.name for p in out.iterdir() if p.is_file()) == ["README.md"]
    assert (out / "print" / "box.3mf").read_bytes() == b"new"
    assert (out / "cad" / "box.step").read_bytes() == b"old box.step"
    assert (out / "images" / "box.png").exists() and (out / "docs" / "box_bom.md").exists()
    assert (out / "print" / "templates" / "box_template_a.stl").exists()
    assert outdir.tidy(out) == []
    assert outdir.tidy(tmp_path / "nothing") == []


def test_readme(tmp_path):
    out = tmp_path / "out"
    for rel in ("print/box.3mf", "print/box.stl", "print/templates/box_template_a.3mf", "cad/box.step"):
        outdir.path(out, Path(rel).name, "templates" in rel).write_bytes(b"x")
    f = outdir.readme(out, "box")
    text = f.read_text(encoding="utf-8")
    assert "- `print/box.3mf`" in text and "print/box.stl`" not in text  # 3MF when there is one
    assert "- `print/templates/box_template_a.3mf`" in text and "`../box.py`" in text
    mtime = f.stat().st_mtime_ns
    os.utime(f, ns=(mtime - 10**9, mtime - 10**9))
    outdir.readme(out, "box")  # the same text: not written again
    assert f.stat().st_mtime_ns == mtime - 10**9


# --- download and pull ----------------------------------------------------------------------------


def test_part_files_nested_and_filtered(ws):
    got = rels(handoff.part_files(ws, "parts", "box"))
    assert got == sorted(["box.py"] + [f"out/{r}" for r in NESTED])
    assert rels(handoff.part_files(ws, "parts", "box", formats=["3mf"])) == [
        "box.py", "out/README.md", "out/print/box.3mf", "out/print/templates/box_template_a.3mf"]
    assert rels(handoff.part_files(ws, "parts", "box", formats=["print", "bom", "glb"])) == [
        "box.py", "out/README.md", "out/cad/box_view.glb", "out/docs/box_bom.md", "out/print/box_print.md"]
    assert rels(handoff.part_files(ws, "parts", "box", formats=["png"], variant="standard")) == [
        "box.py", "out/README.md", "out/images/box.png", "out/images/box_xz0.png"]


def test_part_files_of_an_old_flat_part(ws):
    out = ws / "parts" / "old" / "out"
    out.mkdir(parents=True)
    (ws / "parts/old/old.py").write_text("", encoding="utf-8")
    (out / "old.3mf").write_bytes(b"flat")
    (out / "old.png").write_bytes(b"flat")
    assert rels(handoff.part_files(ws, "parts", "old")) == ["old.py", "out/old.3mf", "out/old.png"]
    assert rels(handoff.part_files(ws, "parts", "old", formats=["3mf"])) == ["old.py", "out/old.3mf"]


def test_zip_has_the_nested_layout(ws):
    data = handoff.zip_bytes(handoff.part_files(ws, "parts", "box", formats=["3mf"]), "parts/box")
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        assert sorted(zf.namelist()) == ["parts/box/box.py", "parts/box/out/README.md", "parts/box/out/print/box.3mf",
                                         "parts/box/out/print/templates/box_template_a.3mf"]


@pytest.mark.parametrize("rel,ok", [
    ("box.py", True), ("ref/a.stl", True), ("out/a.stl", True), ("out/README.md", True),
    ("out/print/a.3mf", True), ("out/print/templates/a.3mf", True), ("out/cad/a.step", True),
    ("out/images/a.png", True), ("out/docs/a.md", True),
    ("out/other/a.stl", False), ("out/print/deep/a.stl", False), ("out/templates/a.stl", False),
    ("ref/print/a.stl", False), ("print/a.3mf", False), ("out/../a.stl", False), ("out/print/../../a.stl", False),
    ("../a.stl", False), ("/etc/passwd", False), ("out//a.stl", False), ("out/./a.stl", False),
    ("out/print/.a.stl", False), ("out/.cache/a.stl", False), ("out\\print\\a.stl", False), ("C:/a.stl", False),
    ("out/print/", False)])
def test_safe_rel(rel, ok):
    assert handoff.safe_rel(rel) is ok


@pytest.mark.parametrize("path,ok", [
    ("parts/box/out/print/box.3mf", True), ("parts/box/out/print/templates/box_template_a.3mf", True),
    ("parts/box/out/cad/box.step", True), ("parts/box/out/images/box.png", True),
    ("parts/box/out/docs/box_bom.md", True), ("parts/box/out/README.md", True),
    ("parts/box/out/other/x.stl", False), ("parts/box/out/print/deep/x.stl", False),
    ("parts/box/out/.cache/x.stl", False), ("parts/box/out/print/.hidden.stl", False),
    ("parts/box/box.py", False), ("parts/box/out/print", False), ("parts/box/out/print/templates", False),
    ("parts/box/out/../box.py", False), ("parts/box/out/print/../../box.py", False),
    ("parts/box/out/print/../print/box.3mf", False), ("/parts/box/out/print/box.3mf", False),
    ("../ws/parts/box/out/print/box.3mf", False), ("parts/../../secret.stl", False),
    ("other/box/out/print/box.3mf", False), ("parts/box/ref/print/box.3mf", False)])
def test_servable_stays_in_out(ws, path, ok):
    if ok:
        assert links.servable(ws, "parts", path).read_bytes() == NESTED[path.split("/out/", 1)[1]]
    else:
        with pytest.raises(links.LinkError):
            links.servable(ws, "parts", path)


@pytest.mark.skipif(sys.platform == "win32", reason="symlinks need rights on Windows")
def test_servable_refuses_a_symlinked_folder(ws, tmp_path):
    out = ws / "parts/box/out"
    (tmp_path / "elsewhere").mkdir()
    (tmp_path / "elsewhere" / "x.step").write_bytes(b"outside")
    import shutil

    shutil.rmtree(out / "cad")
    os.symlink(tmp_path / "elsewhere", out / "cad")
    with pytest.raises(links.LinkError):
        links.servable(ws, "parts", "parts/box/out/cad/x.step")


def run_serve(ws: Path, original: str):
    out, err = io.BytesIO(), io.StringIO()
    code = ssh.serve(str(ws), "me@cad", None, original, stdout=out, stderr=err)
    with tarfile.open(fileobj=io.BytesIO(out.getvalue())) as tf:
        return code, sorted(m.name for m in tf), err.getvalue()


def test_ssh_pull_tree(ws):
    code, names, err = run_serve(ws, "pull box --tree --nested --formats 3mf")
    assert code == 0 and names == ["box.py", "out/README.md", "out/print/box.3mf",
                                   "out/print/templates/box_template_a.3mf"], err
    code, names, err = run_serve(ws, "pull box --tree --formats 3mf")  # a 0.3.1-0.3.10 client: flat
    assert code == 0 and names == ["box.py", "out/README.md", "out/box.3mf", "out/box_template_a.3mf"], err
    assert all(handoff.safe_rel(n) and n.count("/") <= 1 for n in names)
    code, names, err = run_serve(ws, "pull box --formats 3mf,png")  # a 0.3.0 client: file names
    assert code == 0 and names == ["box.3mf", "box.png", "box_template_a.3mf", "box_xz0.png"], err


def test_ssh_pull_nested_needs_tree():
    with pytest.raises(ssh.Refused, match="--nested"):
        ssh.parse_request("pull box --nested")


def forced(ws: Path) -> str:
    return ssh.line_command(ssh.key_line(KEY, ws, "me@cad", prog=[sys.executable, "-m", "b123d_print.cli"]))


def test_pull_writes_the_nested_layout_and_tidies_a_flat_copy(ws, tmp_path, monkeypatch):
    monkeypatch.setenv("B123D_PRINT_FAKE_SSH_FORCED", forced(ws))
    dest = tmp_path / "got"
    old = dest / "parts" / "box" / "out"
    old.mkdir(parents=True)
    (old / "box.3mf").write_bytes(b"old flat")  # an older pull, before 0.3.11
    (old / "box_xy1.png").write_bytes(b"old picture")
    files = ssh.pull("box", "me@cad", dest, "3mf", ssh=FAKE_SSH)
    assert sorted(p.relative_to(dest).as_posix() for p in files) == [
        "parts/box/box.py", "parts/box/out/README.md", "parts/box/out/print/box.3mf",
        "parts/box/out/print/templates/box_template_a.3mf"]
    assert (dest / "parts/box/out/print/box.3mf").read_bytes() == b"3mf"
    assert sorted(p.name for p in old.iterdir() if p.is_file()) == ["README.md"]
    assert (old / "images" / "box_xy1.png").read_bytes() == b"old picture"


def test_pull_from_an_older_server(ws, tmp_path, monkeypatch):
    """A server before 0.3.11 refuses --nested: pull asks again without it and sorts the flat files here."""
    fake = tmp_path / "oldssh.py"
    fake.write_text(
        "import io, sys, tarfile\n"
        "cmd = sys.argv[-1]\n"
        "if '--nested' in cmd:\n"
        "    sys.stderr.write(\"b123d-print: refused: pull: unexpected '--nested'\\n\"); sys.exit(1)\n"
        "tf = tarfile.open(fileobj=sys.stdout.buffer, mode='w|')\n"
        "for name, data in (('box.py', b'x'), ('out/box.3mf', b'flat3mf')):\n"
        "    info = tarfile.TarInfo(name); info.size = len(data); tf.addfile(info, io.BytesIO(data))\n"
        "tf.close()\n", encoding="utf-8")
    files = ssh.pull("box", "me@cad", tmp_path / "dest", ssh=f'"{sys.executable}" "{fake}"')
    assert sorted(p.relative_to(tmp_path / "dest").as_posix() for p in files) == [
        "parts/box/box.py", "parts/box/out/print/box.3mf"]
    assert (tmp_path / "dest/parts/box/out/print/box.3mf").read_bytes() == b"flat3mf"


def test_pull_refuses_an_escape_through_a_folder(tmp_path):
    evil = io.BytesIO()
    with tarfile.open(fileobj=evil, mode="w") as tf:
        info = tarfile.TarInfo("out/print/../../../escape.txt")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    blob = tmp_path / "evil.tar"
    blob.write_bytes(evil.getvalue())
    fake = tmp_path / "evilssh.py"
    fake.write_text(f"import sys\nsys.stdout.buffer.write(open({str(blob)!r}, 'rb').read())\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected entry"):
        ssh.pull("box", "me@cad", tmp_path / "dest", ssh=f'"{sys.executable}" "{fake}"')
    assert not (tmp_path / "escape.txt").exists()
