"""Eval runner dry run: the fake agent (no model) through the real MCP server on a local
reference, then compare + reports. No network, no API key."""

import json

import anyio
import pytest
from build123d import Box, Cylinder, Pos, export_stl

from b123d_print.compare import Criteria
from b123d_print.evals import corpus
from b123d_print.evals.agents import Limits
from b123d_print.evals.runner import Endpoint, run_eval

MANIFEST = """
[[part]]
id = "test_bracket"
title = "Test bracket"
format = "stl"
file = "bracket.stl"
sha256 = "{sha}"
license = "MIT"
description = "A 40 x 30 x 10 mm block with a 6 mm hole."
dimensions = ["overall 40 x 30 x 10 mm", "6 mm through hole at (8, 5)"]
"""


def test_bundled_manifest_is_valid():
    items = corpus.load_manifest()
    assert 10 <= len(items) <= 20
    for it in items:
        assert it.url.startswith("https://") and len(it.sha256) == 64, it.id
        assert it.author and it.license and it.description and it.dimensions, it.id
        assert "NC" not in it.license.upper().split("-") and "ND" not in it.license.upper().split("-"), it.id


def test_fetch_verifies_hash(tmp_path):
    (tmp_path / "x.stl").write_bytes(b"solid x\nendsolid x\n")
    (tmp_path / "m.toml").write_text(MANIFEST.replace("bracket.stl", "x.stl").format(sha="0" * 64), encoding="utf-8")
    (it,) = corpus.load_manifest(tmp_path / "m.toml")
    with pytest.raises(ValueError, match="sha256"):
        corpus.fetch(it, tmp_path / "cache")


def test_dry_run_fake_agent(tmp_path):
    export_stl(Box(40, 30, 10) - Pos(8, 5, 0) * Cylinder(3, 20), tmp_path / "bracket.stl")
    (tmp_path / "m.toml").write_text(MANIFEST.format(sha=corpus.sha256(tmp_path / "bracket.stl")), encoding="utf-8")
    items = corpus.load_manifest(tmp_path / "m.toml")
    out = tmp_path / "run"
    s = anyio.run(lambda: run_eval(items, "fake", Endpoint.from_args(None, None, None, 60), out,
                                   Limits(timeout_s=300), Criteria(), tmp_path / "cache"))
    (r,) = s["results"]
    assert r["result"] == "compared", r
    assert r["agent_run"]["stop"] == "done" and r["agent_run"]["tool_calls"] == 5
    m = r["comparison"]["metrics"]
    assert m["bbox_diff_mm"] == pytest.approx([0, 0, 0], abs=1e-3)  # the fake models the bounding box
    assert m["hausdorff_ref_to_cand_mm"] == pytest.approx(5.0, abs=0.1)  # ... without the hole
    assert r["failures"] == ["hausdorff_mm"] and not r["passed"]
    for f in ("results.json", "report.md", "report.html", "test_bracket/reference.png", "test_bracket/candidate.png",
              "test_bracket/deviation.png", "test_bracket/candidate.py", "test_bracket/transcript.json", "test_bracket/prompt.txt"):
        assert (out / f).is_file(), f
    assert json.loads((out / "results.json").read_text(encoding="utf-8"))["passed"] == 0
    assert "test_bracket" in (out / "report.html").read_text(encoding="utf-8")
