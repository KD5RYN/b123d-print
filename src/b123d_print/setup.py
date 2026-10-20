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

KEYS = ("printer", "material", "formats", "style", "hole_comp", "hole_comp_h")
COUPONS = (  # in the order to print them: example, what it measures, how to store the result
    ("hole_coupon", "hole compensation, vertical and horizontal holes",
     "b123d-print printer calibrate hole_comp <value> (and hole_comp_h)"),
    ("fit_coupon", "the press, sliding and free fits", "b123d-print printer calibrate clearance <value> (press_fit, free_fit)"),
    ("overhang_bridge_coupon", "the overhang angle and bridge length that print cleanly",
     "b123d-print printer calibrate max_overhang <value> (max_bridge)"),
)


@dataclass(frozen=True)
class Change:
    key: str
    old: str | None  # the value there now, None if there is none
    new: str
    where: Path  # the file it goes to (calibration values with a printer: calibration.toml)
    scope: str = ""  # "<printer>/<material>" for a value that goes to calibration.toml

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


def normalize(answers: dict) -> dict[str, str]:
    """Check each answer and give its stored text; raises ValueError (KeyError for an unknown
    printer or material) naming the bad one. Empty answers, and printer "generic" (the mode
    without a profile), are dropped."""
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
            load_printer(v)
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
    change. With a printer in effect and `path` the user config, hole_comp and hole_comp_h go to
    calibration.toml for that printer + material, where `b123d-print printer calibrate` keeps
    them; the printer in effect is the new one unless it conflicts and overwrite is False."""
    from .config import user_config_path
    from .profiles import calibrated, calibration_path

    new = normalize(answers)
    cur = _current(path)

    def effective(k: str) -> str:
        if k in new and (k not in cur or overwrite):
            return new[k]
        return cur.get(k, "")

    printer, material = effective("printer"), effective("material")
    to_cal = bool(printer) and path.resolve() == user_config_path().resolve()
    out = []
    for k, v in new.items():
        if k in CALIBRATED and to_cal:
            old = calibrated(printer, material).get(k)
            out.append(Change(k, None if old is None else f"{old:g}", v, calibration_path(), f"{printer}/{material or 'any'}"))
        else:
            out.append(Change(k, cur.get(k), v, path))
    return out


def apply(changes: list[Change], overwrite: bool = False) -> list[Change]:
    """Write the changes; a conflict only with overwrite=True. Returns what was written."""
    from .profiles import save_calibration

    done = []
    for c in changes:
        if c.same or (c.conflict and not overwrite):
            continue
        if c.scope:
            printer, material = c.scope.split("/")
            save_calibration(printer, "" if material == "any" else material, c.key, float(c.new))
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


def next_steps(hole_comp_set: bool) -> str:
    """The calibration coupons to print next, in order."""
    lines = ["Calibrate (print each, measure, store the result; `b123d-print new <name> --from <example>`):"]
    todo = [c for c in COUPONS if not (c[0] == "hole_coupon" and hole_comp_set)]
    lines += [f"  {i}. {ex}: {what} -> {store}" for i, (ex, what, store) in enumerate(todo, 1)]
    return "\n".join(lines)
