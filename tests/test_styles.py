"""Style files: built-ins, user and workspace styles, based_on, replacing, errors."""

import pytest

from b123d_print import metrics as M
from b123d_print import styles as S
from b123d_print.config import Settings


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    user = tmp_path / "cfg" / "b123d-print" / "styles"
    ws = tmp_path / "ws"
    user.mkdir(parents=True)
    (ws / "styles").mkdir(parents=True)
    return user, ws


def write(folder, name, text):
    (folder / f"{name}.toml").write_text(text, encoding="utf-8")


def test_builtins_load_and_cover_every_threshold():
    names = S.available()
    assert set(names) == {"functional", "modern", "least_cost", "rugged", "soft", "structural"} and set(names.values()) == {"built-in"}
    used = set()
    for n in names:
        st = S.load_style(n)
        assert st.label and st.description and st.review.strip(), n
        used |= {k for k in S.THRESHOLDS if getattr(st, k) not in (None, False)}
    assert used == set(S.THRESHOLDS), "every threshold is used by some built-in style"
    assert S.load_style("rugged").max_sharp_edge_share == 0.0
    st = S.load_style("structural")
    assert st.min_inside_radius_ratio == 0.5 and st.min_wall_lines == 3 and st.max_screw_sizes is None
    assert S.load_style("").name == "functional"


def test_user_style_based_on(dirs):
    user, _ = dirs
    write(user, "shop_jig", 'label = "Shop jig"\nbased_on = "functional"\nedges = "chamfer"\nmax_screw_sizes = 1\n'
                            "max_shallow_slope_share = false\n")
    st = S.load_style("shop_jig")
    assert st.max_screw_sizes == 1 and st.edges == "chamfer" and st.seam_note  # inherited
    assert st.max_shallow_slope_share is None and st.based_on == "functional"
    assert S.available()["shop_jig"].endswith("shop_jig.toml")


def test_workspace_beats_user_and_replaces_builtin(dirs):
    user, ws = dirs
    write(user, "modern", 'label = "My modern"\nmin_treated_edge_share = 0.5\n')
    assert S.load_style("modern").label == "My modern" and S.load_style("modern").max_chamfer_sizes is None
    write(ws / "styles", "modern", 'label = "Shop modern"\nbased_on = "modern"\nmax_chamfer_sizes = 3\n')
    st = S.load_style("modern", ws)
    assert st.label == "Shop modern" and st.max_chamfer_sizes == 3
    assert st.min_treated_edge_share == 0.5  # based on the next "modern": the user's file
    assert S.available(ws)["modern"] == str(ws / "styles" / "modern.toml")


def test_errors(dirs):
    user, _ = dirs
    write(user, "typo", "max_scrw_sizes = 2\n")
    with pytest.raises(S.StyleError, match=r"typo.toml: unknown field\(s\) \['max_scrw_sizes'\]; known:"):
        S.load_style("typo")
    write(user, "badtype", 'max_screw_sizes = "two"\n')
    with pytest.raises(S.StyleError, match="max_screw_sizes must be a number"):
        S.load_style("badtype")
    write(user, "frac", "max_screw_sizes = 1.5\n")
    with pytest.raises(S.StyleError, match="whole number"):
        S.load_style("frac")
    write(user, "flag", "seam_note = 1\n")
    with pytest.raises(S.StyleError, match="true or false"):
        S.load_style("flag")
    write(user, "edgy", 'edges = "round"\n')
    with pytest.raises(S.StyleError, match="edges must be"):
        S.load_style("edgy")
    write(user, "orphan", 'based_on = "nope"\n')
    with pytest.raises(S.StyleError, match="no style 'nope'; styles: .*functional"):
        S.load_style("orphan")
    write(user, "a", 'based_on = "b"\n')
    write(user, "b", 'based_on = "a"\n')
    with pytest.raises(S.StyleError, match="loops"):
        S.load_style("a")
    write(user, "broken", "label = \n")
    with pytest.raises(S.StyleError, match="not valid TOML"):
        S.load_style("broken")
    with pytest.raises(S.StyleError, match="no style 'baroque'"):
        S.load_style("baroque")


def test_custom_style_drives_the_findings(dirs):
    from build123d import Align, Box, Cylinder, Location

    user, _ = dirs
    write(user, "one_screw", 'based_on = "functional"\nmax_screw_sizes = 1\nreview = "Check the screws."\n')
    plate = Box(60, 40, 4, align=(Align.CENTER, Align.CENTER, Align.MIN))
    plate -= Cylinder(1.7, 10).moved(Location((-20, 0, 0)))
    plate -= Cylinder(2.25, 10).moved(Location((20, 0, 0)))
    res = M.design_metrics(None, None, {"": plate}, Settings(), style="one_screw")
    assert any(f["rule"] == "DS-G3" and f["level"] == "suggest" for f in res["findings"])
    assert res["style_review"] == "Check the screws." and "Check the screws." in M.text(res)
    assert not any(f["rule"] == "DS-G3" for f in M.design_metrics(None, None, {"": plate}, Settings())["findings"])


def test_aliases():
    assert S.normalize("Modern/Minimal") == "modern" and S.normalize("industrial") == "functional"
    assert S.normalize("least cost") == "least_cost"
    assert {S.normalize(n) for n in ("strong", "load_bearing", "Load-Bearing", "heavy_duty", "heavy duty")} == {"structural"}
    with pytest.raises(S.StyleError):
        S.normalize("../etc/passwd")


def test_style_setting_in_the_workspace_config(tmp_path, monkeypatch):
    from b123d_print.config import load_settings

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    (tmp_path / "b123d-print.toml").write_text('[workspace]\nstyle = "Outdoor"\n', encoding="utf-8")
    assert load_settings(tmp_path).style == "rugged"
    (tmp_path / "b123d-print.toml").write_text('[workspace]\nstyle = "no good!"\n', encoding="utf-8")
    with pytest.raises(ValueError, match="lower_snake_case"):
        load_settings(tmp_path)


def test_docs_example_style_loads(dirs):
    """The copyable example on design-review.md is a valid style file."""
    import re
    from pathlib import Path

    page = (Path(__file__).resolve().parents[1] / "docs/using/design-review.md").read_text(encoding="utf-8")
    m = re.search(r"```toml\n# ~/.config/b123d-print/styles/(\w+)\.toml\n(.*?)```", page, re.S)
    user, _ = dirs
    write(user, m.group(1), m.group(2))
    st = S.load_style(m.group(1))
    assert st.based_on == "modern" and st.min_treated_edge_share == 1.0 and st.max_chamfer_sizes is None
    assert st.min_symmetry == 0.98  # inherited
