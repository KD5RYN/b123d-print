import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("release_notes", Path(__file__).resolve().parents[1] / "tools/release_notes.py")
rn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rn)

LOG = """# Changelog

## 0.3.0 — unreleased

- new thing

## 0.2.1 — 2026-10-18

**Windows.**
- fixed

## 0.2.0 — 2026-10-17

- first
"""


def test_notes_for_a_dated_version():
    out = rn.notes("v0.2.1", LOG)
    assert out.startswith("**Windows.**") and "- fixed" in out and "first" not in out
    assert "pypi.org/project/b123d-print/0.2.1/" in out


def test_unreleased_or_missing_section_refuses():
    with pytest.raises(SystemExit, match="unreleased"):
        rn.notes("0.3.0", LOG)
    with pytest.raises(SystemExit, match="no section"):
        rn.notes("9.9.9", LOG)


def test_every_released_version_has_notes():
    """Each version in the real CHANGELOG.md that has a date produces notes."""
    for v, (date, _) in rn.sections(rn.CHANGELOG.read_text(encoding="utf-8")).items():
        if "unreleased" not in date.lower():
            assert rn.notes(v)
