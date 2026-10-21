"""Export reuses what did not change (#75): output files stamped in out/.cache/out-*.json, fit-test
templates in out/.cache/template-*/, small template PNGs, no assembly without png."""

from pathlib import Path

import pytest

from b123d_print import project
from b123d_print import templates as tp
from b123d_print.config import load_settings
from b123d_print.project import CacheConfig, ReadLog, load

from test_build_cache import LAZY, write_part

EXPORT = LAZY + '''

def templates(d):
    from b123d_print import Template

    return [Template.slice("XY", 2.0, part="b")]


def views(d):
    from b123d_print import View

    return [View("XZ", 0.0, "middle")]
'''

FORMATS = ("stl", "3mf", "png")


def export(script: Path, formats=FORMATS, fresh: bool = False, cache: bool = True, only=None) -> tuple[dict, object]:
    """One export as the worker runs it: a fresh load, through the build cache."""
    mod = load(script)
    cfg = CacheConfig(script.parents[2], ReadLog(), fresh) if cache else None
    return project.export_variant(mod, script, "", formats=list(formats), cache=cfg, only=only), mod


def times(files) -> dict:
    return {Path(f).name: Path(f).stat().st_mtime_ns for f in files}


@pytest.fixture
def made(monkeypatch):
    """How many templates templates.make made."""
    count = []
    orig = tp.make

    def spy(*a, **kw):
        count.append(1)
        return orig(*a, **kw)

    monkeypatch.setattr(tp, "make", spy)
    return count


def test_second_export_writes_nothing(tmp_path, made):
    script = write_part(tmp_path, code=EXPORT)
    first, _ = export(script)
    names = sorted(Path(f).name for f in first["files"])
    assert "trim_assembly.png" in names and "trim_xz0.png" in names
    assert {"trim_b_template_xy2.stl", "trim_b_template_xy2.png", "trim_b_template_xy2_where.png"} <= set(names)
    assert len(made) == 1
    before = times(first["files"])
    second, mod = export(script)
    assert second["files"] == first["files"] and second["templates"] == first["templates"]
    assert second["parts"] == first["parts"]
    assert times(second["files"]) == before  # nothing rewritten
    assert len(made) == 1 and "assembly" not in mod.CALLS  # the template and the assembly came from the cache
    # the template's PNGs are small (about 800 px wide), the parts' previews normal
    from PIL import Image

    out = script.parent / "out"
    assert Image.open(out / "images/trim_b_template_xy2_where.png").width < 1000
    assert Image.open(out / "images/trim_a.png").width > 1500


def test_changed_piece_edited_and_removed_files(tmp_path, made):
    script = write_part(tmp_path, code=EXPORT)
    first, _ = export(script)
    before = times(first["files"])
    out = script.parent / "out"
    # piece c changes: its files and the renders that show it (assembly: no, it has no c) again
    script.write_text(EXPORT.replace('make("c", 5, 5, 5)', 'make("c", 5, 5, 6.25)'), encoding="utf-8")  # another size: no stale .pyc
    second, _ = export(script)
    after = times(second["files"])
    changed = {n for n in after if after[n] != before[n]}
    assert {"trim_c.stl", "trim_c.3mf", "trim_c.png"} <= changed
    assert not any(n.startswith(("trim_a.", "trim_b.", "trim_b_template")) for n in changed)
    assert len(made) == 1  # b did not change: its template is read back
    # a file edited or removed after the export is written again
    (out / "print/trim_a.stl").write_bytes(b"solid broken\n")
    (out / "print/trim_b.3mf").unlink()
    third, _ = export(script)
    assert (out / "print/trim_b.3mf").is_file() and (out / "print/trim_a.stl").stat().st_size > 100
    assert len(third["files"]) == len(first["files"])
    # a corrupt template entry: made again
    (entry,) = (out / ".cache").glob("template-*")
    (entry / "part.brep").write_text("broken", encoding="utf-8")
    (out / "print/templates/trim_b_template_xy2.stl").unlink()
    export(script)
    assert len(made) == 2 and (out / "print/templates/trim_b_template_xy2.stl").stat().st_size > 100


def test_fresh_no_cache_and_formats(tmp_path, made):
    script = write_part(tmp_path, code=EXPORT)
    first, _ = export(script)
    before = times(first["files"])
    again, _ = export(script, fresh=True)
    assert all(t != before[n] for n, t in times(again["files"]).items())
    assert len(made) == 2
    # in-process (the CLI, no worker): writes everything, keeps no stamps
    other = write_part(tmp_path / "other", code=EXPORT)
    export(other, cache=False)
    assert not list((other.parent / "out").glob(".cache/out-*.json"))
    # no png: no assembly built, no renders
    third = write_part(tmp_path / "third", code=EXPORT)
    res, mod = export(third, formats=("3mf",))
    assert "assembly" not in mod.CALLS
    assert sorted(Path(f).name for f in res["files"]) == ["trim_a.3mf", "trim_b.3mf", "trim_b_template_xy2.3mf",
                                                           "trim_c.3mf"]
    # then png: the 3mf files stay, the PNGs are made
    before = times(res["files"])
    res, _ = export(third, formats=("3mf", "png"))
    after = times(res["files"])
    assert all(after[n] == t for n, t in before.items())
    assert "trim_a.png" in after and "trim_assembly.png" in after
