"""Design styles: small TOML files that say what the design review looks for.

The built-in styles (functional, modern, least_cost, rugged, soft, structural) ship as the same
kind of file a user writes. Lookup, first found wins:

  1. the workspace:  <workspace>/styles/<name>.toml
  2. the user:       ~/.config/b123d-print/styles/<name>.toml
  3. built-in:       b123d_print/data/styles/<name>.toml

So a file with a built-in's name replaces it. `based_on = "modern"` starts from another style
(found the same way) and changes only what the file sets. A threshold set to `false` is off.
The rules each threshold cites are in docs/DESIGN_GUIDE.md (DS-*).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, fields
from importlib.resources import files
from pathlib import Path

from .config import user_config_path

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
ALIASES = {"minimal": "modern", "modern/minimal": "modern", "least cost": "least_cost", "cost": "least_cost",
           "outdoor": "rugged", "rugged/outdoor": "rugged", "handheld": "soft", "soft/handheld": "soft",
           "industrial": "functional",  # industrial = functional with EDGES = "chamfer"
           "strong": "structural", "load_bearing": "structural", "load-bearing": "structural",
           "load bearing": "structural",
           "heavy_duty": "structural", "heavy-duty": "structural", "heavy duty": "structural", "structural/load-bearing": "structural"}
EDGE_PREFS = ("", "chamfer", "fillet")


@dataclass(frozen=True)
class Style:
    """A design style. Thresholds are None when off; each one that a part crosses becomes a
    finding citing its rule (level and rule per field in THRESHOLDS)."""

    name: str
    label: str = ""
    description: str = ""
    based_on: str = ""
    edges: str = ""  # the edge language parts of this style use unless their script sets EDGES
    review: str = ""  # what the reviewer looks for: rubric text shown with the metrics
    max_shallow_slope_share: float | None = None
    supports_on_visible: bool = False
    seam_note: bool = False
    max_screw_sizes: int | None = None
    min_treated_edge_share: float | None = None
    max_edge_break_sizes: int | None = None
    max_styling_radii: int | None = None
    max_chamfer_sizes: int | None = None
    max_sharp_edge_share: float | None = None
    min_symmetry: float | None = None
    hidden_screws_note: bool = False
    max_support_share: float | None = None
    max_infill_share: float | None = None
    max_layer_time_share: float | None = None
    outdoor_material: bool = False
    max_water_cm3: float | None = None
    curved_supports_note: bool = False
    max_sharp_inside_share: float | None = None
    min_inside_radius_ratio: float | None = None
    min_wall_lines: float | None = None
    max_z_slenderness: float | None = None
    source: str = ""  # where it was loaded from (not a file field)


# field -> (level, rule, what it means): the docs' style-file reference is checked against this
THRESHOLDS = {
    "max_shallow_slope_share": ("suggest", "DS-S1", "share of the up-facing (or SHOW) area tilted 1-30 deg from flat"),
    "supports_on_visible": ("suggest", "DS-S2", "supports under a side listed in SHOW"),
    "seam_note": ("note", "DS-S3", "no sharp contour corner for the seam to hide in"),
    "max_screw_sizes": ("suggest", "DS-G3", "distinct screw sizes guessed from the holes"),
    "min_treated_edge_share": ("suggest", "DS-G1", "share of outside edge length rounded or chamfered (bed edges apart)"),
    "max_edge_break_sizes": ("suggest", "DS-G1", "distinct fillet radii up to 1 mm"),
    "max_styling_radii": ("suggest", "DS-G1", "distinct fillet radii over 1 mm"),
    "max_chamfer_sizes": ("suggest", "DS-G1", "distinct chamfer sizes"),
    "max_sharp_edge_share": ("suggest", "DS-G8", "share of outside edge length left sharp"),
    "min_symmetry": ("note", "DS-G7", "best mirror symmetry (x or y)"),
    "hidden_screws_note": ("note", "DS-G3", "screw holes on a part that has SHOW sides"),
    "max_support_share": ("suggest", "DS-C4", "support filament / part filament"),
    "max_infill_share": ("suggest", "DS-C5", "infill share of the filament"),
    "max_layer_time_share": ("suggest", "DS-C7", "per-layer share of the print time"),
    "outdoor_material": ("suggest", "DS-R1", "material PLA or not set"),
    "max_water_cm3": ("suggest", "DS-R3", "water the part holds with UP up, cm3"),
    "curved_supports_note": ("note", "DS-H2", "supports on a part (curved faces scar)"),
    "max_sharp_inside_share": ("suggest", "DS-T3", "share of inside (concave) edge length left sharp"),
    "min_inside_radius_ratio": ("suggest", "DS-T3", "smallest inside fillet radius / the thinner wall it joins"),
    "min_wall_lines": ("suggest", "DS-T4", "thinnest wall in line widths (knife edges apart)"),
    "max_z_slenderness": ("note", "DS-T1", "run standing on a small XY section / sqrt(its area)"),
}
_TEXT = ("label", "description", "based_on", "edges", "review")
_BOOLS = {f.name for f in fields(Style) if f.type == "bool"}
_INTS = {f.name for f in fields(Style) if f.type == "int | None"}
FILE_FIELDS = {f.name for f in fields(Style)} - {"name", "source"}


class StyleError(ValueError):
    pass


def style_dirs(root: Path | None = None) -> list[tuple[str, Path | None]]:
    """(label, folder) in lookup order; the built-ins have folder None."""
    out = []
    if root is not None:
        out.append(("workspace", Path(root) / "styles"))
    out.append(("user", user_config_path().parent / "styles"))
    out.append(("built-in", None))
    return out


def _builtin_names() -> list[str]:
    base = files("b123d_print").joinpath("data", "styles")
    return sorted(f.name[:-5] for f in base.iterdir() if f.name.endswith(".toml"))


def available(root: Path | None = None) -> dict[str, str]:
    """name -> where it comes from (the first folder that has it)."""
    out: dict[str, str] = {}
    for label, d in style_dirs(root):
        names = _builtin_names() if d is None else sorted(p.stem for p in d.glob("*.toml")) if d.is_dir() else []
        for n in names:
            out.setdefault(n, label if d is None else str(d / f"{n}.toml"))
    return out


def _find(name: str, root: Path | None, skip: set = frozenset()) -> tuple[dict, str]:
    """The raw TOML of `name` and where it came from, looking past the sources in `skip` (a file
    based on the style it replaces)."""
    for label, d in style_dirs(root):
        if d is None:
            if name in _builtin_names():
                where = f"built-in style {name}"
                if where not in skip:
                    text = files("b123d_print").joinpath("data", "styles", f"{name}.toml").read_text(encoding="utf-8")
                    return _parse(text, where), where
            continue
        p = d / f"{name}.toml"
        if p.is_file() and str(p) not in skip:
            return _parse(p.read_text(encoding="utf-8"), str(p)), str(p)
    have = sorted(available(root))
    raise StyleError(f"no style {name!r}; styles: {', '.join(have)} (add your own in "
                     f"{style_dirs(root)[0][1] if root else user_config_path().parent / 'styles'})")


def _parse(text: str, where: str) -> dict:
    try:
        raw = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise StyleError(f"{where}: not valid TOML: {e}") from None
    unknown = set(raw) - FILE_FIELDS
    if unknown:
        raise StyleError(f"{where}: unknown field(s) {sorted(unknown)}; known: {sorted(FILE_FIELDS)}")
    out = {}
    for k, v in raw.items():
        if k in _TEXT:
            if not isinstance(v, str):
                raise StyleError(f"{where}: {k} must be text, got {v!r}")
        elif k in _BOOLS:
            if not isinstance(v, bool):
                raise StyleError(f"{where}: {k} must be true or false, got {v!r}")
        elif v is False:
            v = None  # a threshold switched off
        elif isinstance(v, bool) or not isinstance(v, (int, float)):
            raise StyleError(f"{where}: {k} must be a number (or false to switch it off), got {v!r}")
        elif k in _INTS and float(v) != int(v):
            raise StyleError(f"{where}: {k} must be a whole number, got {v!r}")
        else:
            v = int(v) if k in _INTS else float(v)
        out[k] = v
    if out.get("edges", "") not in EDGE_PREFS:
        raise StyleError(f"{where}: edges must be 'chamfer', 'fillet' or empty, got {out['edges']!r}")
    return out


def normalize(name: str | None) -> str:
    s = (name or "").strip().lower()
    s = ALIASES.get(s, s).replace("-", "_").replace(" ", "_")
    if s and not NAME_RE.match(s):
        raise StyleError(f"style name {name!r}: lower_snake_case")
    return s


def load_style(name: str, root: Path | None = None) -> Style:
    """The style `name` with its based_on chain applied."""
    n = normalize(name) or "functional"
    chain: list[tuple[dict, str]] = []
    seen: list[str] = []
    cur, skip = n, set()
    while True:
        raw, where = _find(cur, root, skip)
        if where in {w for _, w in chain}:
            raise StyleError(f"style {n!r}: based_on loops ({' -> '.join(seen + [cur])})")
        chain.append((raw, where))
        seen.append(cur)
        base = normalize(raw.get("based_on", ""))
        if not base:
            break
        skip = skip | {where} if base == cur else set()  # based on the style it replaces: look past it
        cur = base
    merged: dict = {}
    for raw, _ in reversed(chain):
        merged.update({k: v for k, v in raw.items() if k != "based_on"})
    return Style(name=n, based_on=normalize(chain[0][0].get("based_on", "")), source=chain[0][1], **merged)
