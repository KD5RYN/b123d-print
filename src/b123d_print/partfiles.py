"""Finding part scripts and printing the build timing report: what the MCP server and the CLI
need without building anything, so importing them does not load build123d (project.py does)."""

from __future__ import annotations

from pathlib import Path


def timing_lines(timing: dict) -> list[str]:
    """The timing report (Pieces.timing) as text lines: one per piece, then the hints."""
    out = []
    for name, st in timing["pieces"].items():
        secs = (f"{st['seconds']:.1f} s" if st.get("seconds") is not None else "built by build(d)")
        out.append(f"{name}: {st['faces']} faces, {secs}" + (" (cached)" if st.get("cached") else ""))
    if timing.get("build_seconds") is not None:
        out.append(f"build(d): {timing['build_seconds']:.1f} s")
    return out + [f"hint: {h}" for h in timing["hints"]]


def find_parts(root: Path, parts_dir: str) -> list[Path]:
    base = root / parts_dir
    return sorted(p / f"{p.name}.py" for p in base.iterdir() if (p / f"{p.name}.py").is_file()) if base.is_dir() else []


def resolve_part(spec: str, root: Path, parts_dir: str) -> Path:
    """A part name (folder under parts_dir) or a path to a script."""
    p = Path(spec)
    if p.suffix == ".py" and p.is_file():
        return p.resolve()
    cand = root / parts_dir / spec / f"{spec}.py"
    if cand.is_file():
        return cand.resolve()
    raise FileNotFoundError(f"no part '{spec}' (looked for {cand})")
