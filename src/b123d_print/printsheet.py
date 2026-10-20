"""The print sheet: a short Markdown summary written next to the exports, for the slicer.

`export` with the `print` format writes out/<name>[_<variant>]_print.md: per piece the size,
volume, filament and time (rough estimates, design_metrics' rules), the supports and bridges the
overhang rule finds, tip-over advice (the tip-over check's measure), then the settings the part
was designed for (material, printer, clearance, hole compensation), walls and infill (the style's
guidance), screw holes that want more perimeters, the Wall checks the script declares, and the
script's PRINT_NOTES (assembly order, glue, inserts). It uses only the cheap metrics, not the full
design review, so the format costs a second or two per piece. Off by default (not in
DEFAULT_FORMATS); `all` includes it. Nothing here changes the part.
"""

from __future__ import annotations

from pathlib import Path

from build123d import Part

from . import checks as ck
from . import metrics as mt

STRUCTURAL_WALLS = "4-6 walls, 15-30 % gyroid infill"  # structural style review, DS-T2 / DS-T4
SCREW_WALLS = "3-4 or more walls"  # around screw holes and bosses, BP-W3 / DS-T6
NEAR_BED = 1.0  # mm: overhangs centred lower than this over the bed are bed-edge flares, listed apart


def piece_numbers(part: Part, p: mt.Params, speed: float) -> dict:
    """Size, volume, filament, time, supports, tip-over and holes of one printable piece. Screw
    sizes are guessed from the holes as printed (the cut diameter less hole_comp)."""
    mesh = mt.Mesh(part)
    m = {"size": mt.size(part), "volume": round(part.volume, 1), "mass": mt.mass(part, mesh, p)}
    m["supports"] = mt.supports(part, mesh, p)
    m["time"] = mt.print_time(part, m["mass"]["extruded_mm3"] + m["supports"].get("volume_mm3", 0), p)
    m["tip"] = None
    if speed:
        fp = ck.bed_footprint(part, speed)
        why = ck.tip_risk(fp)
        m["tip"] = {"why": why, **fp} if why else None
    hs = ck.holes(part)
    m["holes"] = len(hs)
    m["horizontal_holes"] = sum(1 for h in hs if not h.get("vertical"))
    m["screw_holes"] = sorted({c[0] for h in hs
                               if (c := mt.fastener_class(h["d"] - (p.hole_comp if h.get("vertical") else p.hole_comp_h)))})
    return m


def _grams(g: float) -> str:
    return "<0.1 g" if g < 0.1 else f"~{g:g} g"


def _minutes(m: float) -> str:
    return f"{m:.0f} min" if m < 90 else f"{m / 60:.1f} h"


def _walls(mod, d, min_wall: float) -> list[str]:
    """Labels of the Wall checks the script declares (features the designer worried about)."""
    f = getattr(mod, "checks", None)
    try:
        specs = list(f(d)) if f else []
    except Exception:  # noqa: BLE001 - a broken checks(d) is the check run's to report, not the sheet's
        return []
    out = []
    for s in specs:
        if isinstance(s, ck.Wall):
            piece = s.part if isinstance(s.part, str) and s.part else "part"
            out.append(f"{s.label or f'{s.plane} @ {s.at:g}'} ({piece}, min {s.min if s.min is not None else 'min_wall'} mm)")
    return out


def _notes(mod, d) -> list[str]:
    v = mt.script_attr(mod, d, "PRINT_NOTES", None)
    if not v:
        return []
    return [str(v)] if isinstance(v, str) else [str(x) for x in v]


def sheet(mod, d, parts: dict, settings, title: str) -> str:
    """The Markdown text of the print sheet for the built pieces `parts` ({name: Part})."""
    p = mt.Params.from_settings(settings)
    style, _ = mt.resolve_style(mod, d, settings)
    named = {(k or "part"): v for k, v in parts.items()}
    per = {n: piece_numbers(v, p, settings.tip_speed) for n, v in named.items()}
    for n, m in per.items():  # supports right at the bed are bed-edge flares, listed apart
        zmin = named[n].bounding_box().min.Z
        m["high"] = [f for f in m["supports"]["faces"] if f["center"][2] >= zmin + NEAR_BED]
        m["low"] = [f for f in m["supports"]["faces"] if f["center"][2] < zmin + NEAR_BED]
    many = len(per) > 1
    L = [f"# {title}: print sheet", "",
         ("Written by `b123d-print` export (the `print` format) from the part as built. Filament is a "
          "simple estimate (roughly ±20 %), time and supports are rough estimates: compare versions "
          "with them, the slicer has the real numbers."), "",
         "## Pieces", "",
         "| Piece | Size X × Y × Z (mm) | Volume (cm³) | Filament (g) | Time | Supports |",
         "| --- | --- | --- | --- | --- | --- |"]
    for n, m in per.items():
        s, sup = m["size"], m["supports"]
        up = m["high"]
        L.append(f"| {n} | {s['x']:g} × {s['y']:g} × {s['z']:g} | {m['volume'] / 1000:.1f} | {m['mass']['grams']:g} "
                 f"| {_minutes(m['time']['minutes'])} | {f'{len(up)} face(s), ' + _grams(sup['grams']) if up else 'none'} |")
    if many:
        g = sum(m["mass"]["grams"] for m in per.values())
        t = sum(m["time"]["minutes"] for m in per.values())
        L.append(f"| **all** | | {sum(m['volume'] for m in per.values()) / 1000:.1f} | {g:.1f} | {_minutes(t)} | |")
    L += ["", "## Orientation", "",
          "Exported in print orientation: the face on Z = 0 goes on the bed, as the file opens. Don't "
          "auto-orient or lay it on another face in the slicer; if a piece lands off the plate, use "
          "Arrange." + (" Each piece is its own file (or object): print them together or one at a time." if many else "")
          + (" Structural style: the main load should run along the layers (in XY); `suggest_orientation` with "
             "`load=` checks it." if style == "structural" else "")]
    for n, m in per.items():
        sup, tip, who = m["supports"], m["tip"], (f"**{n}**: " if many else "")
        high, low = m["high"], m["low"]
        if high:
            where = "; ".join(f"{f['area']:g} mm² at ({', '.join(f'{x:g}' for x in f['center'])})" for f in high[:4])
            more = f" and {len(high) - 4} more" if len(high) > 4 else ""
            L.append(f"- {who}supports needed under {len(high)} face(s), ~{sum(f['area'] for f in high):.1f} mm² "
                     f"({_grams(sup['grams'])}): {where}{more}. Supported faces come out rough; `check` and "
                     "`suggest_orientation` say whether turning the part avoids them.")
        else:
            L.append(f"- {who}no supports needed (overhangs within {p.max_overhang:g}° from vertical, "
                     f"bridges up to {p.max_bridge:g} mm). Turn slicer supports off, or set them to \"on build plate only\".")
        if low:
            L.append(f"- {who}{len(low)} small overhang(s) within {NEAR_BED:g} mm of the bed (~{sum(f['area'] for f in low):.1f} mm²), "
                     "usually a fillet or rounded edge on the bed (the `bed edge` check): the slicer seldom supports them, "
                     "they print with a slight flare.")
        long = [b for b in sup.get("bridges", []) if b > p.max_bridge]
        if long:
            L.append(f"- {who}bridges over {p.max_bridge:g} mm: {', '.join(f'{b:g} mm' for b in long)} (counted as supported above).")
        if tip:
            L.append(f"- {who}tip-over risk ({'; '.join(tip['why'])}): use a brim of 5-10 mm or mouse ears.")
        if m["horizontal_holes"]:
            L.append(f"- {who}{m['horizontal_holes']} hole(s) lie on their side (axis in XY): with a teardrop or flat "
                     "roof (the `holes` check says) they need no supports; keep slicer supports out of them.")
    from .profiles import load_material, load_printer

    mat = load_material(settings.material) if settings.material else None  # load_settings loaded both already
    printer = load_printer(settings.printer) if settings.printer else None
    L += ["", "## Slicer settings the part assumes", ""]
    L.append(f"- **Material:** {mat.summary() if mat else (settings.material or 'not set; the estimates assume PLA')}")
    if printer:
        L.append(f"- **Printer:** {printer.label or printer.name}, {printer.nozzle:g} mm nozzle, "
                 f"{printer.layer_height:g} mm layers")
    else:
        L.append(f"- **Printer:** generic profile; the estimates assume a {p.nozzle:g} mm nozzle and {p.layer:g} mm layers")
    if style == "structural":
        L.append(f"- **Walls and infill:** structural style: {STRUCTURAL_WALLS} (strength comes from the walls); "
                 "nozzle temperature near the top of the material's range.")
    else:
        L.append(f"- **Walls and infill:** {style} style; the estimates assume {p.walls} walls and {p.infill:.0%} infill "
                 "(slicer defaults). Use more walls, not more infill, where the part carries load.")
    screws = sorted({s for m in per.values() for s in m["screw_holes"]})
    if screws:
        L.append(f"- **Screw holes** ({', '.join(screws)}): {SCREW_WALLS} around them (a height-range or "
                 "per-object modifier in the slicer, or more walls for the whole part).")
    for w in _walls(mod, d, settings.min_wall):
        L.append(f"- **Wall checked by the script:** {w}")
    hc, hch = p.hole_comp, p.hole_comp_h
    if any(m["holes"] for m in per.values()):
        comp = (f"{hc:g} mm" + (f" ({hch:g} mm on holes lying on their side)" if hch != hc else "")) if hc or hch else \
            "none (hole_comp was 0, so holes may print small)"
        L.append(f"- **Hole compensation applied in the CAD:** {comp}. Leave the slicer's own hole or X-Y "
                 "compensation off, or the holes are corrected twice.")
    L.append(f"- **Fits:** clearance {settings.clearance:g} mm per side (sliding), press fit {settings.press_fit:g}, "
             f"free fit {settings.free_fit:g}, print-in-place {settings.pip_clearance:g}. They assume the "
             "slicer's flow and elephant's-foot compensation are tuned; the CAD is at nominal size.")
    notes = _notes(mod, d)
    if many or notes or hasattr(mod, "assembly"):
        L += ["", "## Assembly and notes", ""]
        if many:
            L.append(f"- {len(per)} pieces: {', '.join(per)}.")
        if hasattr(mod, "assembly"):
            L.append("- The script has an `assembly(d)`: `check_fit` (CLI `b123d-print fit`) checks how the pieces mate.")
        L += [f"- {n}" for n in notes]
    return "\n".join(L) + "\n"


def write(mod, d, parts: dict, settings, out: Path, name: str, title: str) -> Path:
    path = out / f"{name}.md"
    path.write_text(sheet(mod, d, parts, settings, title), encoding="utf-8")
    return path
