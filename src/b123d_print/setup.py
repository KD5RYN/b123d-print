"""First-run setup: the printer, material, export formats, default style and measured hole
compensation, written to the user config or a workspace's b123d-print.toml.

Used by `b123d-print setup` (asks, or takes flags) and the MCP tool `save_setup` (the AI asks the
questions through the `setup_workspace` prompt). A value already in the target file is never
replaced unless the caller says so: `plan` lists it as a conflict, `apply` skips it.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .config import CALIBRATED, parse_formats, set_user_setting

KEYS = ("printer", "material", "formats", "style", *CALIBRATED)
COUPONS = (  # in the order to print them: example, what it measures, how to store the result
    ("hole_coupon", "how much small holes print undersize",
     "enter half the diameter error in the slicer's X-Y hole compensation (per side), then record "
     "b123d-print printer calibrate hole_comp 0"),
    ("fit_coupon", "the press, sliding and free fits, printed with the same slicer settings as real parts",
     "b123d-print printer calibrate clearance <value> (press_fit, free_fit, pip_clearance)"),
    ("overhang_bridge_coupon", "the overhang angle and bridge length that print cleanly",
     "b123d-print printer calibrate max_overhang <value> (max_bridge)"),
)


@dataclass(frozen=True)
class Change:
    key: str
    old: str | None  # the value there now, None if there is none
    new: str
    where: Path  # the file it goes to (calibration values with a printer: calibration.toml, or the workspace file)
    scope: str = ""  # "<printer>/<material>" for a calibration value (calibration.toml or the workspace's [calibration])

    @property
    def conflict(self) -> bool:
        return self.old is not None and self.old != self.new

    @property
    def same(self) -> bool:
        return self.old == self.new


def _current(path: Path) -> dict[str, str]:
    """The settings the TOML file sets itself, as text (none for a missing file)."""
    if not path.is_file():
        return {}
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    flat = {**raw.get("workspace", {}), **raw.get("print", {})}
    return {k: ",".join(map(str, v)) if isinstance(v, list) else str(v) for k, v in flat.items()}


def normalize(answers: dict, nicknames: dict | None = None) -> dict[str, str]:
    """Check each answer and give its stored text; raises ValueError (KeyError for an unknown
    printer or material) naming the bad one. Empty answers, and printer "generic" (the mode
    without a profile), are dropped. A printer may be one of `nicknames`."""
    from .profiles import load_material, load_printer
    from .styles import StyleError, load_style, normalize as style_name

    out = {}
    for k, v in answers.items():
        if k not in KEYS:
            raise ValueError(f"unknown setup key {k!r}; known: {list(KEYS)}")
        v = "" if v is None else str(v).strip()
        if not v or (k == "printer" and v in ("generic", "none")):
            continue
        if k == "printer":
            load_printer((nicknames or {}).get(v, v))
        elif k == "material":
            v = v.lower()
            load_material(v)
        elif k == "formats":
            v = ",".join(parse_formats(v))
        elif k == "style":
            try:
                v = style_name(v)
                load_style(v)
            except StyleError as e:
                raise ValueError(str(e)) from None
        else:
            try:
                v = f"{float(v):g}"
            except ValueError:
                raise ValueError(f"{k} must be a number (mm), got {v!r}") from None
        out[k] = v
    return out


def plan(answers: dict, path: Path, overwrite: bool = False) -> list[Change]:
    """What writing `answers` to `path` (the user config or a workspace's b123d-print.toml) would
    change. With a printer in effect, the measured values (CALIBRATED) go to that printer +
    material: in calibration.toml for the user config, where `b123d-print printer calibrate`
    keeps them, and in the file's [calibration."<printer>/<material>"] table for a workspace. The
    printer in effect is the new one unless it conflicts and overwrite is False; for a workspace
    file that sets none, the one in effect there (its nickname if it has one)."""
    from .config import load_settings, printer_nicknames, user_config_path
    from .profiles import calibrated, calibration_path, workspace_calibrated

    user = path.resolve() == user_config_path().resolve()
    new = normalize(answers, printer_nicknames(path.parent))
    cur = _current(path)

    def effective(k: str) -> str:
        if k in new and (k not in cur or overwrite):
            return new[k]
        return cur.get(k, "")

    printer, material = effective("printer"), effective("material")
    if not user and not printer:
        s = load_settings(path.parent)
        printer, material = s.calibration_key, material or s.material
    out = []
    for k, v in new.items():
        if k in CALIBRATED and printer:
            old = (calibrated(printer, material) if user else workspace_calibrated(path, printer, material)).get(k)
            out.append(Change(k, None if old is None else f"{old:g}", v, calibration_path() if user else path,
                              f"{printer}/{material or 'any'}"))
        else:
            out.append(Change(k, cur.get(k), v, path))
    return out


def apply(changes: list[Change], overwrite: bool = False) -> list[Change]:
    """Write the changes; a conflict only with overwrite=True. Returns what was written."""
    from .profiles import calibration_path, save_calibration

    done = []
    for c in changes:
        if c.same or (c.conflict and not overwrite):
            continue
        if c.scope:
            printer, material = c.scope.split("/")
            save_calibration(printer, "" if material == "any" else material, c.key, float(c.new),
                             None if c.where == calibration_path() else c.where)
        else:
            set_user_setting(c.key, c.new, c.where)
        done.append(c)
    return done


def report(changes: list[Change], written: list[Change]) -> str:
    """One line per answer: written, unchanged, or kept (a conflict that was not overwritten)."""
    lines = []
    for c in changes:
        if c in written:
            lines.append(f"  {c.key} = {c.new}" + (f" (was {c.old})" if c.old is not None else "") + f"  -> {c.where}")
        elif c.same:
            lines.append(f"  {c.key} = {c.new} (already set)")
        else:
            lines.append(f"  {c.key}: kept {c.old} (not replaced by {c.new}; confirm to overwrite)")
    return "\n".join(lines)


def flat_calibration(path: Path) -> dict[str, str]:
    """Measured values set flat in a workspace file ([print] hole_comp = ...): they win over every
    printer's calibration there, so switching printers keeps them. move_flat moves them."""
    return {k: v for k, v in _current(path).items() if k in CALIBRATED}


def move_flat(path: Path, printer: str) -> dict[str, str]:
    """Move the flat measured values of workspace file `path` under `printer` (its calibration
    key) for any material, [calibration."<printer>/any"], so they no longer follow other printers.
    The values in effect for that printer stay the same. Returns what was moved."""
    from .profiles import save_calibration

    flat = flat_calibration(path)
    for k, v in flat.items():
        save_calibration(printer, "", k, float(v), path)
        set_user_setting(k, None, path)
    return flat


SLICER_HOLE_COMP = "OrcaSlicer and Bambu Studio: X-Y hole compensation (Precision); Cura: Hole Horizontal Expansion"


def slicer_note(hole_comp: float, hole_comp_h: float | None = None, printer: str = "") -> str:
    """Where holes are corrected. By default the slicer does it and the model is true to size;
    an opt-in hole_comp is built into the files, for that printer only, and the slicer's must be 0."""
    h = hole_comp if hole_comp_h is None else hole_comp_h
    if hole_comp or h:
        both = f"{hole_comp:g} mm" + (f" ({h:g} mm for holes lying on their side)" if h != hole_comp else "")
        return (f"HOLE COMPENSATION BUILT IN: every hole is cut {both} larger than drawn (hole_comp), for "
                f"{printer or 'this printer'} only. Print these files with the slicer's X-Y hole compensation at 0 "
                "(or the holes are corrected twice), and not on another printer.")
    return ("Holes are modeled true to size. The slicer corrects them: set its X-Y hole compensation "
            f"({SLICER_HOLE_COMP}) to the hole_coupon's result, half the diameter error (per side).")


def hole_note(s) -> str:
    """slicer_note for the settings `s` in effect, naming the printer (or nickname) and material."""
    return slicer_note(s.hole_comp, s.hole_comp_h, f"{s.calibration_key}/{s.material or 'any'}" if s.printer else "")


def next_steps(hole_comp_set: bool) -> str:
    """The calibration coupons to print next, in order."""
    lines = ["Calibrate (first the slicer's own XYZ cube for shrinkage, if you use one; then print each coupon, "
             "measure, store the result; `b123d-print new <name> --from <example>`; the hole coupon with the slicer's "
             "X-Y hole compensation at 0, the others with your usual settings; redo them when the slicer's "
             "compensation or the filament changes):"]
    todo = [c for c in COUPONS if not (c[0] == "hole_coupon" and hole_comp_set)]
    lines += [f"  {i}. {ex}: {what} -> {store}" for i, (ex, what, store) in enumerate(todo, 1)]
    return "\n".join(lines)
