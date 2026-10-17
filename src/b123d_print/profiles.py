"""Printer and material profiles: the few facts about your printer and filament that change how a
part is modeled (build volume, nozzle, layer height, overhang limit; material notes). Not slicer
tuning.

Built-in profiles ship in b123d_print/data/{printers,materials}/<name>.toml; your own go in
~/.config/b123d-print/{printers,materials}/<name>.toml and win over a built-in of the same name.
Hole compensation per printer + material lives in ~/.config/b123d-print/calibration.toml.
"""

from __future__ import annotations

import json
import re
import tomllib
from dataclasses import asdict, dataclass, fields
from importlib.resources import files
from pathlib import Path

from .config import user_config_path

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class Printer:
    name: str
    label: str = ""
    bed_x: float = 220.0  # mm; for a round bed, its diameter
    bed_y: float = 220.0
    height: float = 250.0
    round_bed: bool = False
    nozzle: float = 0.4
    layer_height: float = 0.2
    max_overhang: float = 45.0  # deg from vertical that prints cleanly without supports
    source: str = ""  # where the numbers came from

    @property
    def line_width(self) -> float:
        return round(self.nozzle * 1.125, 3)

    @property
    def min_wall(self) -> float:  # two perimeters
        return round(2 * self.line_width, 2)

    def summary(self) -> str:
        bed = f"Ø{self.bed_x:g}" if self.round_bed else f"{self.bed_x:g} x {self.bed_y:g}"
        return (f"{self.label or self.name}: build {bed} x {self.height:g} mm, nozzle {self.nozzle:g}, "
                f"layer {self.layer_height:g}, line ~{self.line_width:g}, min wall {self.min_wall:g}, "
                f"overhang <= {self.max_overhang:g} deg")

    def as_dict(self) -> dict:
        return {**asdict(self), "line_width": self.line_width, "min_wall": self.min_wall}


@dataclass(frozen=True)
class Material:
    name: str
    label: str = ""
    clearance: float | None = None  # overrides the default mating clearance when set
    notes: str = ""

    def summary(self) -> str:
        return f"{self.label or self.name}" + (f": {self.notes}" if self.notes else "")

    def as_dict(self) -> dict:
        return asdict(self)


def _user_dir(kind: str) -> Path:
    return user_config_path().parent / kind


def _orca() -> dict[str, dict]:
    raw = json.loads(files("b123d_print").joinpath("data", "printers_orca.json").read_text(encoding="utf-8"))
    src = f"OrcaSlicer profiles @ {raw['commit'][:12]}"
    return {k: {kk: vv for kk, vv in v.items() if kk != "vendor"} | {"source": src} for k, v in raw["printers"].items()}


def _builtin(kind: str) -> dict[str, dict]:
    if kind == "printers":
        return _orca()
    base = files("b123d_print").joinpath("data", kind)
    return {f.name[:-5]: tomllib.loads(f.read_text(encoding="utf-8")) for f in base.iterdir() if f.name.endswith(".toml")}


def _load(cls, kind: str, name: str):
    user = _user_dir(kind) / f"{name}.toml"
    if user.is_file():
        raw, where = tomllib.loads(user.read_text(encoding="utf-8")), str(user)
    else:
        raw, where = _builtin(kind).get(name), f"built-in {kind}/{name}"
    if raw is None:
        close = search(kind, name)[:8]
        raise KeyError(f"no {kind[:-1]} profile {name!r}" + (f"; did you mean {close}?" if close else ""))
    known = {f.name for f in fields(cls)}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"{where}: unknown field(s) {sorted(unknown)}; known: {sorted(known - {'name'})}")
    return cls(**{**raw, "name": name})


def load_printer(name: str) -> Printer:
    return _load(Printer, "printers", name)


def load_material(name: str) -> Material:
    return _load(Material, "materials", name)


def search(kind: str, query: str = "") -> list[str]:
    """Profile names matching every word of `query` (in the name or label)."""
    words = [w for w in re.split(r"[^a-z0-9]+", query.lower()) if w]
    out = []
    builtin = _builtin(kind)
    for n in available(kind):
        hay = n + " " + str(builtin.get(n, {}).get("label", "")).lower()
        if all(w in hay for w in words):
            out.append(n)
    return out


def available(kind: str) -> list[str]:
    names = set(_builtin(kind))
    d = _user_dir(kind)
    if d.is_dir():
        names |= {p.stem for p in d.glob("*.toml")}
    return sorted(names)


def to_toml(obj) -> str:
    """A profile as TOML (for saving an imported or edited profile)."""
    lines = []
    for f in fields(obj):
        if f.name == "name":
            continue
        v = getattr(obj, f.name)
        if v is None:
            continue
        if isinstance(v, bool):
            lines.append(f"{f.name} = {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            lines.append(f"{f.name} = {v:g}")
        else:
            lines.append(f'{f.name} = "{str(v).replace(chr(92), chr(92) * 2).replace(chr(34), chr(92) + chr(34))}"')
    return "\n".join(lines) + "\n"


def save_user(obj, kind: str) -> Path:
    if not NAME_RE.match(obj.name):
        raise ValueError(f"profile name {obj.name!r}: lower_snake_case")
    d = _user_dir(kind)
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{obj.name}.toml"
    p.write_text(to_toml(obj), encoding="utf-8")
    return p


# --- calibration: hole compensation per printer + material ------------------------------------


def calibration_path() -> Path:
    return user_config_path().parent / "calibration.toml"


def calibrated_hole_comp(printer: str, material: str) -> float | None:
    p = calibration_path()
    if not (printer and p.is_file()):
        return None
    raw = tomllib.loads(p.read_text(encoding="utf-8"))
    entry = raw.get(f"{printer}/{material or 'any'}") or raw.get(f"{printer}/any")
    return float(entry["hole_comp"]) if entry and "hole_comp" in entry else None


def save_hole_comp(printer: str, material: str, value: float) -> Path:
    p = calibration_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    raw = tomllib.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    raw[f"{printer}/{material or 'any'}"] = {"hole_comp": float(value)}
    out = ["# Hole compensation per printer/material, measured with the hole_coupon example.\n"]
    for k in sorted(raw):
        out.append(f'["{k}"]\nhole_comp = {raw[k]["hole_comp"]:g}\n')
    p.write_text("\n".join(out), encoding="utf-8")
    return p


# --- fit in the build volume --------------------------------------------------------------------


def fits(printer: Printer, size: tuple[float, float, float], margin: float = 0.0) -> tuple[bool, str]:
    """Does a part of bounding box `size` (print orientation) fit? Returns (ok, explanation)."""
    x, y, z = size
    if z > printer.height:
        return False, f"{z:.1f} mm tall, build height {printer.height:g}"
    if printer.round_bed:
        d = (x * x + y * y) ** 0.5
        ok = d <= printer.bed_x - 2 * margin
        return ok, f"footprint diagonal {d:.1f} mm vs bed Ø{printer.bed_x:g}"
    bx, by = printer.bed_x - 2 * margin, printer.bed_y - 2 * margin
    if x <= bx and y <= by:
        return True, f"{x:.1f} x {y:.1f} x {z:.1f} fits {printer.bed_x:g} x {printer.bed_y:g} x {printer.height:g}"
    if y <= bx and x <= by:
        return True, f"fits only turned 90 deg on the bed ({x:.1f} x {y:.1f} on {printer.bed_x:g} x {printer.bed_y:g})"
    return False, f"{x:.1f} x {y:.1f} mm footprint, bed {printer.bed_x:g} x {printer.bed_y:g}"
