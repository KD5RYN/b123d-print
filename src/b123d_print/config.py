"""Per-user and per-workspace settings.

Lookup order, later wins:
  1. built-in defaults (below)
  2. user config:      $XDG_CONFIG_HOME/b123d-print/config.toml (~/.config/b123d-print/config.toml)
  3. workspace config: the nearest b123d-print.toml at or above the part script (or the cwd)
  4. environment:      B123D_PRINT_HOLE_COMP, B123D_PRINT_CLEARANCE, ... (one per number, see
                       _ENV), B123D_PRINT_FORMATS (e.g. "step,3mf"), B123D_PRINT_REVIEW (warn,
                       required, off: a shared server's operator can require the design review)

Clearances are per side. With a printer profile set, values measured with the calibration
coupons replace the defaults: per printer + material, in calibration.toml next to the user
config, and in the workspace config's [calibration."<printer>/<material>"] tables (shared
servers keep them there; they win over calibration.toml key by key). A flat workspace value
still beats both. A printer can have a nickname ([printers] p2s_garage = "<profile>"), so two of
the same model keep their own calibration: calibration is keyed by the nickname.

Hole compensation is a property of *your* printer + material, so it normally lives in the user
config. It defaults to 0: measure it with examples/hole_coupon before trusting any value.
"""

from __future__ import annotations

import os
import sys
import tomllib
from dataclasses import dataclass, fields, replace
from pathlib import Path

WORKSPACE_FILE = "b123d-print.toml"
FORMATS = ("step", "stl", "3mf", "png", "glb", "print", "hardware", "bom", "bom_csv")  # every export format; `formats` picks a subset
DEFAULT_FORMATS = ("step", "stl", "3mf", "png")  # what export writes unless told otherwise (not glb, print, hardware, bom or bom_csv)
SUFFIX = {"step": ".step", "stl": ".stl", "3mf": ".3mf", "png": ".png", "glb": ".glb"}  # out/ files of a format, by suffix
TAGGED = {"print": "_print.md", "hardware": "_hardware.json", "bom": "_bom.md", "bom_csv": "_bom.csv"}  # ... and by name end


def out_file_wanted(filename: str, formats) -> bool:
    """Is out/<filename> a file of one of `formats` (the download and pull filters)? The text
    formats share suffixes (.md, .json), so they are told apart by the end of the name."""
    name = filename.lower()
    return any(name.endswith(TAGGED[f]) if f in TAGGED else name.endswith(SUFFIX[f]) for f in formats)


IMAGE_SIZES = ("normal", "small")  # render size: "small" is about 800 px wide (cheaper to send to a model)


@dataclass(frozen=True)
class Settings:
    hole_comp: float = 0.0  # mm added to hole *diameters* when cutting (printed holes come out small)
    hole_comp_h: float | None = None  # the same for horizontal holes (axis in XY); default: hole_comp
    clearance: float = 0.2  # mm per side between mating parts that slide (the default fit)
    press_fit: float = 0.05  # mm per side for parts pressed together
    free_fit: float = 0.3  # mm per side for parts that turn or move freely
    pip_clearance: float = 0.3  # mm between parts printed in place; the gap check fails below it
    min_wall: float = 0.8  # mm; wall checks fail below this unless a check sets its own minimum
    max_overhang: float = 45.0  # deg from vertical; steeper downward faces are flagged
    max_bridge: float = 10.0  # mm; longer bridges (flat ceilings between two walls) warn
    max_triangles: int = 50_000  # import_model refuses meshes with more triangles (simplify them first)
    printer: str = ""  # optional printer profile (`b123d-print printer list`); "" = generic
    material: str = ""  # optional material profile: pla, petg, asa, abs, tpu or your own
    formats: tuple = DEFAULT_FORMATS  # what export writes: step (other CAD), stl / 3mf (slicer), png (previews), glb (web/3D apps), print (the print sheet), hardware (declared BOM JSON), bom / bom_csv (the shopping list as Markdown / CSV)
    style: str = ""  # design style for parts without STYLE: functional (default), modern, least_cost, rugged, soft, structural or your own
    filament_price: float | None = None  # price per kg; design_metrics shows a cost when set
    print_flow: float = 10.0  # mm^3/s for the rough print-time estimate (standard hotend 8-12, high-flow 20+)
    tip_speed: float = 200.0  # mm/s, the slicer's fastest print speed: the tip-over check scales with it; 0 = off
    supports: str = ""  # your default support style for the print sheet: none, auto, build_plate_only, tree; "" = suggest from the geometry
    walls: int = 0  # your default wall count (perimeters) for the print sheet and estimates; 0 = the slicer default (2)
    infill: float | None = None  # your default infill percent for the print sheet and estimates; none = 15
    review: str = "warn"  # export's review mode (#146): warn (export, say what was skipped), required (refuse until the review steps are done, or skip_review="<reason>"), off
    parts_dir: str = "parts"  # workspace-relative folder holding <name>/<name>.py
    root: Path | None = None  # workspace root (folder of b123d-print.toml), if one was found
    nickname: str = ""  # the printer's nickname when `printer` was set to one ([printers] table); printer is then its profile

    @property
    def calibration_key(self) -> str:
        """The name calibration is stored under: the nickname, else the printer profile."""
        return self.nickname or self.printer


_ENV = {
    "hole_comp": "B123D_PRINT_HOLE_COMP",
    "hole_comp_h": "B123D_PRINT_HOLE_COMP_H",
    "clearance": "B123D_PRINT_CLEARANCE",
    "press_fit": "B123D_PRINT_PRESS_FIT",
    "free_fit": "B123D_PRINT_FREE_FIT",
    "pip_clearance": "B123D_PRINT_PIP_CLEARANCE",
    "min_wall": "B123D_PRINT_MIN_WALL",
    "max_overhang": "B123D_PRINT_MAX_OVERHANG",
    "max_bridge": "B123D_PRINT_MAX_BRIDGE",
    "max_triangles": "B123D_PRINT_MAX_TRIANGLES",
}
NUMBERS = (*_ENV, "filament_price", "print_flow", "tip_speed")  # the numeric settings
# measured per printer + material (calibration.toml, or the workspace's [calibration] tables): a
# calibration for the active printer beats the same key in the user config, but not a flat
# workspace value or the environment
CALIBRATED = ("hole_comp", "hole_comp_h", "clearance", "press_fit", "free_fit", "pip_clearance", "max_overhang", "max_bridge")


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
    names = {f.name for f in fields(Settings)} - {"root", "nickname"}
    unknown = set(flat) - names
    if unknown:
        raise ValueError(f"{path}: unknown setting(s) {sorted(unknown)}; known: {sorted(names)}")
    if "formats" in flat:
        flat["formats"] = parse_formats(flat["formats"], str(path))
    for k in NUMBERS:
        if k in flat:
            try:
                flat[k] = float(flat[k])
            except (TypeError, ValueError):
                raise ValueError(f"{path}: {k} must be a number, got {flat[k]!r}") from None
    for k in ("printer", "material", "parts_dir", "style", "review"):
        if k in flat:
            flat[k] = str(flat[k])
    if "review" in flat:
        flat["review"] = flat["review"].strip().lower()
        if flat["review"] not in ("warn", "required", "off"):
            raise ValueError(f"{path}: review must be warn, required or off, got {flat['review']!r}")
    if flat.get("supports") or flat.get("walls") or "infill" in flat:  # the same vocabulary as a part's PRINT
        from .intent import validate

        given = {k: flat[k] for k in ("supports", "walls", "infill") if flat.get(k) not in (None, "", 0)}
        flat.update({k: v for k, v in validate({**given, "why": "settings"}, str(path)).items() if k != "why"})
    if flat.get("style"):
        from .styles import normalize

        try:
            flat["style"] = normalize(flat["style"])
        except ValueError as e:
            raise ValueError(f"{path}: {e}") from None
    return flat


def _tables(path: Path | None) -> dict:
    """The whole TOML file (empty for none or a missing file): for its [printers] and
    [calibration] tables, which _read leaves out."""
    if path is None or not path.is_file():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def printer_nicknames(start: str | Path | None = None) -> dict[str, str]:
    """Printer nicknames -> profile names, from the user config's and the workspace config's
    [printers] tables (the workspace wins)."""
    ws = find_workspace(start)
    out = {}
    for path in (user_config_path(), ws / WORKSPACE_FILE if ws else None):
        out.update({str(k): str(v) for k, v in _tables(path).get("printers", {}).items()})
    return out


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

    With a printer profile set, min_wall, max_overhang and max_bridge come from it unless set
    explicitly, and the CALIBRATED values from the calibration for that printer + material unless
    the workspace or the environment sets them. hole_comp_h defaults to hole_comp."""
    s = Settings()
    explicit: set[str] = set()
    user = user_config_path()
    if user.is_file():
        u = _read(user)
        s = replace(s, **u)
        explicit |= set(u) - set(CALIBRATED)  # a calibration for the active printer beats the global value
    ws = find_workspace(start)
    if ws is not None:
        w = _read(ws / WORKSPACE_FILE)
        s = replace(s, root=ws, **w)
        explicit |= set(w)
    if os.environ.get("B123D_PRINT_PRINTER") is not None:
        s = replace(s, printer=os.environ["B123D_PRINT_PRINTER"])
    nick = printer_nicknames(start).get(s.printer) if s.printer else None
    if nick:
        s = replace(s, nickname=s.printer, printer=nick)
    for name, var in _ENV.items():
        if os.environ.get(var):
            explicit.add(name)
    if s.printer:
        from .profiles import load_printer

        p = load_printer(s.printer)
        for k in ("min_wall", "max_overhang", "max_bridge"):
            if k not in explicit:
                s = replace(s, **{k: getattr(p, k)})
    if s.material and "clearance" not in explicit:
        from .profiles import load_material

        m = load_material(s.material)
        if m.clearance is not None:
            s = replace(s, clearance=m.clearance)
    if s.printer:
        from .profiles import calibrated

        cal = {k: v for k, v in calibrated(s.calibration_key, s.material, ws).items() if k not in explicit}
        if cal:
            s = replace(s, **cal)
    for name, var in _ENV.items():
        if os.environ.get(var):
            s = replace(s, **{name: float(os.environ[var])})
    if s.hole_comp_h is None:
        s = replace(s, hole_comp_h=s.hole_comp)
    if os.environ.get("B123D_PRINT_FORMATS"):
        s = replace(s, formats=parse_formats(os.environ["B123D_PRINT_FORMATS"], "B123D_PRINT_FORMATS"))
    if os.environ.get("B123D_PRINT_REVIEW"):
        r = os.environ["B123D_PRINT_REVIEW"].strip().lower()
        if r not in ("warn", "required", "off"):
            raise ValueError(f"B123D_PRINT_REVIEW must be warn, required or off, got {r!r}")
        s = replace(s, review=r)
    return s


def hole_comp_source(start: str | Path | None = None) -> str | None:
    """Where hole_comp comes from for a part script or folder: "environment", "workspace config",
    "workspace calibration" or "calibration" (for the active printer + material), "user config",
    or None when it was never set and holes are cut at their nominal size."""
    if os.environ.get(_ENV["hole_comp"]):
        return "environment"
    ws = find_workspace(start)
    if ws is not None and "hole_comp" in _read(ws / WORKSPACE_FILE):
        return "workspace config"
    s = load_settings(start)
    if s.printer:
        from .profiles import calibrated, workspace_calibrated

        if ws is not None and "hole_comp" in workspace_calibrated(ws / WORKSPACE_FILE, s.calibration_key, s.material):
            return "workspace calibration"
        if "hole_comp" in calibrated(s.calibration_key, s.material):
            return "calibration"
    user = user_config_path()
    if user.is_file() and "hole_comp" in _read(user):
        return "user config"
    return None


def formats_configured(start: str | Path | None = None) -> bool:
    """True if the user, the workspace or the environment chose export formats (False: the built-in four, step, stl, 3mf and png)."""
    if os.environ.get("B123D_PRINT_FORMATS"):
        return True
    user = user_config_path()
    if user.is_file() and "formats" in _read(user):
        return True
    ws = find_workspace(start)
    return ws is not None and "formats" in _read(ws / WORKSPACE_FILE)


def hole_comp(script_file: str | Path | None = None, horizontal: bool = False) -> float:
    """HOLE_COMP for a part script: `HOLE_COMP: float = hole_comp(__file__)`; with
    horizontal=True the value for holes whose axis lies in XY (hole_comp_h)."""
    s = load_settings(script_file)
    return s.hole_comp_h if horizontal else s.hole_comp


def printer(script_file: str | Path | None = None):
    """The active printer profile, or None in generic mode: `p = printer(__file__)`."""
    from .profiles import load_printer

    name = load_settings(script_file).printer
    return load_printer(name) if name else None


def set_user_setting(key: str, value: str | None, path: Path | None = None, table: str = "print",
                     raw: bool = False) -> Path:
    """Set (or with None remove) `key` under [print] in the user config (or the TOML file
    `path`, e.g. a workspace's b123d-print.toml), keeping the rest. `table` names another table
    (e.g. 'printers' or 'calibration."<printer>/<material>"'); raw=True writes the value as is
    (a number) instead of as a string."""
    path = path or user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    want = _table_path(table)
    entry = f"{key} = {value}" if raw else f'{key} = "{value}"'
    out, here, done = [], False, False
    for line in lines:
        st = line.strip()
        if st.startswith("[") and st.endswith("]") and not st.startswith("[["):
            if here and not done and value is not None:
                while out and not out[-1].strip():  # before the blank lines that end the table
                    out.pop()
                out += [entry, ""]
                done = True
            here = _table_path(st[1:-1]) == want
        elif here and st.split("=")[0].strip().strip('"') == key:
            if value is not None and not done:
                out.append(entry)
                done = True
            continue
        out.append(line)
    if not done and value is not None:
        if not here:
            out += ["", f"[{table}]"] if out else [f"[{table}]"]
        out.append(entry)
    path.write_text("\n".join(out).strip() + "\n", encoding="utf-8")
    return path


def _table_path(header: str) -> tuple:
    """A table header's key path, however it is quoted: 'calibration."a/b"' -> ('calibration', 'a/b')."""
    try:
        d, keys = tomllib.loads(f"[{header}]\n"), []
    except tomllib.TOMLDecodeError:
        return (header.strip(),)
    while isinstance(d, dict) and len(d) == 1:
        k = next(iter(d))
        keys.append(k)
        d = d[k]
    return tuple(keys)


def clearance(script_file: str | Path | None = None) -> float:
    """Default mating clearance: `CLEARANCE: float = clearance(__file__)`."""
    return load_settings(script_file).clearance


def safe_console() -> None:
    """Print, don't crash, on a console that is not UTF-8 (Windows pipes default to cp1252): a
    character it cannot show (in a part name, a path) comes out as "?"."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure") and (stream.encoding or "").lower().replace("-", "") != "utf8":
            stream.reconfigure(errors="replace")
