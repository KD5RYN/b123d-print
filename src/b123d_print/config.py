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
    printer: str = ""  # optional printer profile (`b123d-print printer list`); "" = generic
    material: str = ""  # optional material profile: pla, petg, asa, abs, tpu or your own
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
    for k in ("hole_comp", "clearance", "min_wall", "max_overhang"):
        if k in flat:
            try:
                flat[k] = float(flat[k])
            except (TypeError, ValueError):
                raise ValueError(f"{path}: {k} must be a number, got {flat[k]!r}") from None
    for k in ("printer", "material", "parts_dir"):
        if k in flat:
            flat[k] = str(flat[k])
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
    """Settings for a part script (pass its __file__) or a folder.

    With a printer profile set, min_wall and max_overhang come from it unless set explicitly, and
    hole_comp comes from the calibration for that printer + material unless the workspace or
    the environment sets it."""
    s = Settings()
    explicit: set[str] = set()
    user = user_config_path()
    if user.is_file():
        u = _read(user)
        s = replace(s, **u)
        explicit |= set(u) - {"hole_comp"}  # a calibration for the active printer beats the global value
    ws = find_workspace(start)
    if ws is not None:
        w = _read(ws / WORKSPACE_FILE)
        s = replace(s, root=ws, **w)
        explicit |= set(w)
    if os.environ.get("B123D_PRINT_PRINTER") is not None:
        s = replace(s, printer=os.environ["B123D_PRINT_PRINTER"])
    for name, var in _ENV.items():
        if os.environ.get(var):
            explicit.add(name)
    if s.printer:
        from .profiles import calibrated_hole_comp, load_printer

        p = load_printer(s.printer)
        if "min_wall" not in explicit:
            s = replace(s, min_wall=p.min_wall)
        if "max_overhang" not in explicit:
            s = replace(s, max_overhang=p.max_overhang)
        if "hole_comp" not in explicit:
            hc = calibrated_hole_comp(s.printer, s.material)
            if hc is not None:
                s = replace(s, hole_comp=hc)
    if s.material and "clearance" not in explicit:
        from .profiles import load_material

        m = load_material(s.material)
        if m.clearance is not None:
            s = replace(s, clearance=m.clearance)
    for name, var in _ENV.items():
        if os.environ.get(var):
            s = replace(s, **{name: float(os.environ[var])})
    if os.environ.get("B123D_PRINT_FORMATS"):
        s = replace(s, formats=parse_formats(os.environ["B123D_PRINT_FORMATS"], "B123D_PRINT_FORMATS"))
    return s


def hole_comp(script_file: str | Path | None = None) -> float:
    """HOLE_COMP for a part script: `HOLE_COMP: float = hole_comp(__file__)`."""
    return load_settings(script_file).hole_comp


def printer(script_file: str | Path | None = None):
    """The active printer profile, or None in generic mode: `p = printer(__file__)`."""
    from .profiles import load_printer

    name = load_settings(script_file).printer
    return load_printer(name) if name else None


def set_user_setting(key: str, value: str | None, path: Path | None = None) -> Path:
    """Set (or with None remove) `key` under [print] in the user config (or the TOML file
    `path`, e.g. a workspace's b123d-print.toml), keeping the rest."""
    path = path or user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    out, section, done = [], None, False
    for line in lines:
        st = line.strip()
        if st.startswith("[") and st.endswith("]"):
            if section == "print" and not done and value is not None:
                out.append(f'{key} = "{value}"')
                done = True
            section = st[1:-1].strip()
        elif section == "print" and st.split("=")[0].strip() == key:
            if value is not None and not done:
                out.append(f'{key} = "{value}"')
                done = True
            continue
        out.append(line)
    if not done and value is not None:
        if section != "print" and "[print]" not in (x.strip() for x in out):
            out += ["", "[print]"] if out else ["[print]"]
            out.append(f'{key} = "{value}"')
        else:
            out.append(f'{key} = "{value}"')
    path.write_text("\n".join(out).strip() + "\n", encoding="utf-8")
    return path


def clearance(script_file: str | Path | None = None) -> float:
    """Default mating clearance: `CLEARANCE: float = clearance(__file__)`."""
    return load_settings(script_file).clearance
