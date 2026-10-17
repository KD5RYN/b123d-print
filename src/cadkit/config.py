"""Per-user and per-workspace settings.

Lookup order, later wins:
  1. built-in defaults (below)
  2. user config:      $XDG_CONFIG_HOME/cadkit/config.toml (~/.config/cadkit/config.toml)
  3. workspace config: the nearest cadkit.toml at or above the part script (or the cwd)
  4. environment:      CADKIT_HOLE_COMP, CADKIT_CLEARANCE, CADKIT_MIN_WALL, CADKIT_MAX_OVERHANG

Hole compensation is a property of *your* printer + material, so it normally lives in the user
config. It defaults to 0: measure it with examples/hole_coupon before trusting any value.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

WORKSPACE_FILE = "cadkit.toml"


@dataclass(frozen=True)
class Settings:
    hole_comp: float = 0.0  # mm added to hole *diameters* when cutting (printed holes come out small)
    clearance: float = 0.2  # mm default gap between mating parts
    min_wall: float = 0.8  # mm; wall checks fail below this unless a check sets its own minimum
    max_overhang: float = 45.0  # deg from vertical; steeper downward faces are flagged
    parts_dir: str = "parts"  # workspace-relative folder holding <name>/<name>.py
    root: Path | None = None  # workspace root (folder of cadkit.toml), if one was found


_ENV = {
    "hole_comp": "CADKIT_HOLE_COMP",
    "clearance": "CADKIT_CLEARANCE",
    "min_wall": "CADKIT_MIN_WALL",
    "max_overhang": "CADKIT_MAX_OVERHANG",
}


def user_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    return Path(base) / "cadkit" / "config.toml"


def find_workspace(start: str | Path | None = None) -> Path | None:
    """Nearest folder at or above `start` (a file or folder; default cwd) that has a cadkit.toml."""
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
    return flat


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
    return s


def hole_comp(script_file: str | Path | None = None) -> float:
    """HOLE_COMP for a part script: `HOLE_COMP: float = hole_comp(__file__)`."""
    return load_settings(script_file).hole_comp


def clearance(script_file: str | Path | None = None) -> float:
    """Default mating clearance: `CLEARANCE: float = clearance(__file__)`."""
    return load_settings(script_file).clearance
