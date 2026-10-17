"""Per-user and per-workspace settings.

Lookup order, later wins:
  1. built-in defaults (below)
  2. user config:      $XDG_CONFIG_HOME/b123d-print/config.toml (~/.config/b123d-print/config.toml)
  3. workspace config: the nearest b123d-print.toml at or above the part script (or the cwd)
  4. environment:      B123D_PRINT_HOLE_COMP, B123D_PRINT_CLEARANCE, B123D_PRINT_MIN_WALL,
                       B123D_PRINT_MAX_OVERHANG, B123D_PRINT_FORMATS (e.g. "step,3mf")

Hole compensation is a property of *your* printer + material, so it normally lives in the user
config. It defaults to 0: measure it with examples/hole_coupon before trusting any value.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

WORKSPACE_FILE = "b123d-print.toml"
FORMATS = ("step", "stl", "3mf", "png")  # every export format; `formats` picks a subset


@dataclass(frozen=True)
class Settings:
    hole_comp: float = 0.0  # mm added to hole *diameters* when cutting (printed holes come out small)
    clearance: float = 0.2  # mm default gap between mating parts
    min_wall: float = 0.8  # mm; wall checks fail below this unless a check sets its own minimum
    max_overhang: float = 45.0  # deg from vertical; steeper downward faces are flagged
    formats: tuple = FORMATS  # what export writes: step (other CAD), stl / 3mf (slicer), png (previews)
    parts_dir: str = "parts"  # workspace-relative folder holding <name>/<name>.py
    root: Path | None = None  # workspace root (folder of b123d-print.toml), if one was found


_ENV = {
    "hole_comp": "B123D_PRINT_HOLE_COMP",
    "clearance": "B123D_PRINT_CLEARANCE",
    "min_wall": "B123D_PRINT_MIN_WALL",
    "max_overhang": "B123D_PRINT_MAX_OVERHANG",
}


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "b123d-print" / "config.toml"


def find_workspace(start: str | Path | None = None) -> Path | None:
    """Nearest folder at or above `start` (a file or folder; default cwd) that has a b123d-print.toml."""
    p = Path(start or Path.cwd()).resolve()
    if p.is_file() or not p.exists():
        p = p.parent
    for d in (p, *p.parents):
        if (d / WORKSPACE_FILE).is_file():
            return d
    return None


def _read(path: Path) -> dict:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    flat = {}
    for section in ("print", "workspace"):
        flat.update(raw.get(section, {}))
    names = {f.name for f in fields(Settings)} - {"root"}
    unknown = set(flat) - names
    if unknown:
        raise ValueError(f"{path}: unknown setting(s) {sorted(unknown)}; known: {sorted(names)}")
    if "formats" in flat:
        flat["formats"] = parse_formats(flat["formats"], str(path))
    return flat


def parse_formats(value, where: str = "formats") -> tuple:
    """'step,3mf' or ["step", "3mf"] -> ("step", "3mf"); 'all' -> every format."""
    items = value.split(",") if isinstance(value, str) else list(value)
    items = [str(x).strip().lower().lstrip(".") for x in items if str(x).strip()]
    if items == ["all"]:
        return FORMATS
    bad = [x for x in items if x not in FORMATS]
    if bad or not items:
        raise ValueError(f"{where}: unknown format(s) {bad or 'none given'}; choose from {list(FORMATS)} or 'all'")
    return tuple(x for x in FORMATS if x in items)


def load_settings(start: str | Path | None = None) -> Settings:
    """Settings for a part script (pass its __file__) or a folder."""
    s = Settings()
    user = user_config_path()
    if user.is_file():
        s = replace(s, **_read(user))
    ws = find_workspace(start)
    if ws is not None:
        s = replace(s, root=ws, **_read(ws / WORKSPACE_FILE))
    for name, var in _ENV.items():
        if os.environ.get(var):
            s = replace(s, **{name: float(os.environ[var])})
    if os.environ.get("B123D_PRINT_FORMATS"):
        s = replace(s, formats=parse_formats(os.environ["B123D_PRINT_FORMATS"], "B123D_PRINT_FORMATS"))
    return s


def hole_comp(script_file: str | Path | None = None) -> float:
    """HOLE_COMP for a part script: `HOLE_COMP: float = hole_comp(__file__)`."""
    return load_settings(script_file).hole_comp


def clearance(script_file: str | Path | None = None) -> float:
    """Default mating clearance: `CLEARANCE: float = clearance(__file__)`."""
    return load_settings(script_file).clearance
