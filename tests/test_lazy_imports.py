"""The MCP server front and the light CLI commands import no CAD or plotting library (#76): every
build runs in a worker, so the front would hold ~400 MB and pay ~4 s at start for nothing."""

import subprocess
import sys

import pytest

HEAVY = ("build123d", "OCP", "matplotlib", "scipy")


def _loaded(code: str) -> list[str]:
    probe = f"{code}\nimport sys\nprint(','.join(m for m in {HEAVY!r} if m in sys.modules))"
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=120, check=True)
    return [m for m in out.stdout.strip().splitlines()[-1].split(",") if m] if out.stdout.strip() else []


@pytest.mark.parametrize("code", [
    "import b123d_print.mcp_server",
    "import b123d_print",
    "import b123d_print.cli",
    "from b123d_print.partfiles import find_parts, resolve_part, timing_lines",
])
def test_no_heavy_import(code):
    assert _loaded(code) == []


def test_public_names_still_import():
    """A part script's `from b123d_print import ...` gets the same objects as before, and
    b123d_print.render stays the function even after the render module was imported."""
    import b123d_print
    from b123d_print import checks, project, render as render_fn

    from b123d_print.render import render

    assert render_fn is render and b123d_print.render is render
    import b123d_print.render as again

    assert again is render
    assert b123d_print.Wall is checks.Wall and b123d_print.View is project.View
    for name in b123d_print.__all__:
        assert getattr(b123d_print, name) is not None
    assert set(b123d_print.__all__) <= set(dir(b123d_print))
    with pytest.raises(AttributeError):
        b123d_print.no_such_name  # noqa: B018
