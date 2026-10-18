"""Part-script convention and the runner behind `b123d-print build` / `b123d-print check` / the MCP tools.

A part script lives at <parts_dir>/<name>/<name>.py and defines:

    @dataclass(frozen=True)
    class Dims: ...                  # UPPER_CASE fields in mm; derived values as properties
    VARIANTS = {"": {}, "big": dict(WIDTH=80.0)}   # overrides only; "" is the standard part
    def build(d) -> Part | dict[str, Part]          # printable parts, in PRINT orientation

and optionally:

    def assembly(d) -> list[(Part, color, label)]   # assembled position, incl. stand-ins for
                                                    # the things it mates with -> overlap check
    def views(d) -> list[View]                      # section views saved on export
    def checks(d) -> list[Wall | Overhang | Gap | ...]  # automatic per part: Overhang, ThinFeature,
                                                    # Holes, BedEdge, Gap, Fit
    def original(d) -> Part                         # remixes: the original as placed in the remix
                                                    # (default: what build() loaded with import_model)

    if __name__ == "__main__":
        from b123d_print import run
        run(__file__)

Scripts with only a module-level `part = ...` (no Dims) also work.
"""

from __future__ import annotations

import argparse
import importlib.util
import sys
import traceback
from dataclasses import dataclass, is_dataclass, replace
from pathlib import Path
from types import ModuleType

from build123d import Part

from . import checks as ck
from .config import Settings, hole_comp_source, load_settings, parse_formats, safe_console
from .render import export_files, render, report, section_view


@dataclass
class View:
    """A cross-section saved with the exports. plane 'XY' (at=Z), 'XZ' (at=Y) or 'YZ' (at=X).
    parts: names from build() to include; default the assembly if there is one, else all parts."""

    plane: str
    at: float
    title: str = ""
    parts: tuple | None = None


def load(path: str | Path) -> ModuleType:
    path = Path(path).resolve()
    sys.path.insert(0, str(path.parent))  # sibling helper modules
    name = f"b123d_print_part_{path.stem}"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def variants(mod: ModuleType) -> dict[str, dict]:
    return dict(getattr(mod, "VARIANTS", None) or {"": {}})


def variant_key(name: str | None) -> str | None:
    return None if name is None else ("" if name in ("", "standard") else name)


def dims(mod: ModuleType, key: str):
    D = getattr(mod, "Dims", None)
    if D is None:
        return None
    overrides = variants(mod)[key]
    return replace(D(), **overrides) if is_dataclass(D) else D(**overrides)


def printables(mod: ModuleType, d) -> dict[str, Part]:
    if hasattr(mod, "build"):
        r = mod.build(d) if d is not None else mod.build()
    elif hasattr(mod, "part"):
        r = mod.part
    else:
        raise AttributeError("script defines neither build(d) nor a module-level `part`")
    return dict(r) if isinstance(r, dict) else {"": r}


def built(mod: ModuleType, d) -> tuple[dict[str, Part], Part | None, list]:
    """printables() plus the remix's original: what `original(d)` returns, else what build() loaded
    with import_model (None for a part that is not a remix), and the import records."""
    from . import remix

    remix.reset_imports()
    parts = printables(mod, d)
    imports = list(remix.IMPORTED)
    f = getattr(mod, "original", None)
    if f is not None:
        orig = f(d) if d is not None else f()
        imports += remix.IMPORTED[len(imports):]
    elif imports:
        from build123d import Compound

        orig = imports[0][0] if len(imports) == 1 else Part(Compound([s for p, _ in imports for s in p.solids()]).wrapped)
    else:
        orig = None
    remix.reset_imports()
    return parts, orig, [info for _, info in imports]


def assembly(mod: ModuleType, d) -> list[tuple[Part, str, str]] | None:
    f = getattr(mod, "assembly", None)
    return f(d) if f else None


def out_name(stem: str, key: str, part: str) -> str:
    return "_".join(x for x in (stem, key, part) if x)


def check_specs(mod: ModuleType, d, parts: dict, asm) -> list:
    f = getattr(mod, "checks", None)
    specs = list(f(d) if f else [])
    covered = {s.part or "part" for s in specs if isinstance(s, ck.Overhang)}
    specs += [ck.Overhang(p) for p in parts if p not in covered]  # always report overhangs
    if asm and not any(isinstance(s, ck.Overlap) for s in specs):
        specs.append(ck.Overlap())
    fitted = {s.part or "part" for s in specs if isinstance(s, ck.Fit)}
    specs += [ck.Fit(p) for p in parts if p not in fitted]  # no-op without a printer profile
    # automatic per-part checks; a script lists one itself to change its arguments
    for cls in (ck.ThinFeature, ck.Holes, ck.BedEdge):
        listed = {s.part or "part" for s in specs if isinstance(s, cls)}
        specs += [cls(p) for p in parts if p not in listed]
    gapped = {s.part or "part" for s in specs if isinstance(s, ck.Gap) and s.other is None}
    specs += [ck.Gap(p) for p in parts if p not in gapped]  # no-op for a single solid
    return specs


def run_checks(mod: ModuleType, key: str, settings: Settings, nudge: bool = True) -> list[ck.Finding]:
    """Build one variant and run every check. Never raises: errors become findings.
    nudge: also add the setup reminders (hole_comp never measured); callers pass it for the
    first variant only, so a check run says it once."""
    tag = key or "standard"
    try:
        d = dims(mod, key)
        parts, orig, imports = built(mod, d)
        asm = assembly(mod, d)
    except Exception as e:
        return [ck.Finding(ck.FAIL, "error", tag, f"build failed: {e!r}", {"traceback": traceback.format_exc()})]
    out = [import_finding(i) for i in imports]
    for name, p in parts.items():
        valid = bool(p.is_valid) and p.volume > 0
        out.append(ck.Finding(ck.OK if valid else ck.FAIL, "valid", name or "part",
                              "valid solid" if valid else f"is_valid={p.is_valid}, volume={p.volume:.3f}", report(p)))
    named = {(k or "part"): v for k, v in parts.items()}
    lookup = dict(named)
    if list(parts) == [""]:  # a bare Part from build(): also findable by the script's own name
        lookup.setdefault(Path(getattr(mod, "__file__", "part")).stem, named["part"])
    on_original: dict = {}  # the same checks on the original, for telling inherited findings from new ones
    for spec in check_specs(mod, d, named, asm):
        try:
            found = spec.run(lookup, asm, settings)
            if orig is not None and isinstance(spec, INHERITABLE) and getattr(spec, "other", None) is None:
                twin = replace(spec, part=ORIGINAL)
                k = repr(twin)
                if k not in on_original:
                    on_original[k] = twin.run({ORIGINAL: orig}, None, settings)
                from .remix import mark_inherited

                found = mark_inherited(found, on_original[k])
            out.extend(found)
        except Exception as e:
            out.append(ck.Finding(ck.FAIL, "error", getattr(spec, "part", type(spec).__name__), repr(e),
                                  {"traceback": traceback.format_exc()}))
    if nudge:
        out.extend(setup_findings(mod, out))
    return out


INHERITABLE = (ck.Overhang, ck.ThinFeature, ck.Holes, ck.BedEdge, ck.Gap)  # automatic checks also run on the original
ORIGINAL = "original"


def import_finding(info) -> ck.Finding:
    """What import_model did with a reference file: a WARN when its units look wrong."""
    msg = info.summary()
    extra = info.repairs + info.notes + info.warnings
    if extra:
        msg += ". " + ". ".join(extra)
    return ck.Finding(ck.WARN if info.warnings else ck.OK, "import", Path(info.file).name, msg,
                      {k: v for k, v in info.__dict__.items() if k != "metadata"} | {"metadata": info.metadata})


def setup_findings(mod: ModuleType, findings: list[ck.Finding]) -> list[ck.Finding]:
    """Reminders about settings the part depends on but nobody has set: hole_comp is 0 until it
    is measured, so a part with holes gets them at nominal size, which prints small (BP-H1)."""
    n = sum(len(f.data.get("holes", [])) for f in findings if f.check == "holes")
    if not n or hole_comp_source(getattr(mod, "__file__", None)) is not None:
        return []
    return [ck.Finding(ck.WARN, "hole_comp", "settings",
                       f"this part has {n} round hole(s) and hole_comp has never been set (user config, workspace, "
                       "calibration or environment), so they are cut at nominal size and print small. Print the "
                       "hole_coupon example (`b123d-print new coupon --from hole_coupon`), then store the result with "
                       "`b123d-print printer hole-comp <value>` or `hole_comp = <value>` in your user config",
                       {"holes": n})]


def export_variant(mod: ModuleType, script: Path, key: str, out: Path | None = None, formats=None) -> dict:
    """Export every printable part in `formats` (default: the `formats` setting), plus the
    assembly render and section views when png is among them. Returns a summary."""
    formats = formats or load_settings(script).formats
    out = out or script.parent / "out"
    out.mkdir(parents=True, exist_ok=True)
    d = dims(mod, key)
    parts, orig, _ = built(mod, d)
    asm = assembly(mod, d)
    summary = {"variant": key or "standard", "parts": {}, "files": []}
    for pname, p in parts.items():
        name = out_name(script.stem, key, pname)
        files = export_files(p, out, name, formats)
        summary["parts"][pname or "part"] = report(p)
        summary["files"] += [str(f) for f in files]
    if "png" not in formats:
        return summary
    if asm:
        f = render(asm, out / f"{out_name(script.stem, key, 'assembly')}.png", f"{out_name(script.stem, key, '')} assembly")
        summary["files"].append(str(f))
    if orig is not None:
        r = before_after(orig, parts, out, out_name(script.stem, key, ""))
        summary["files"] += r["files"]
        summary["original"] = {"score": r["score"], "text": r["text"]}
    vf = getattr(mod, "views", None)
    for i, v in enumerate(vf(d) if vf else []):
        if v.parts:
            sel = [(parts[n], None, n or "part") for n in v.parts]
        else:
            sel = asm or [(p, None, n or "part") for n, p in parts.items()]
        title = out_name(script.stem, key, "")
        f = section_view(sel, v.plane, v.at, out / f"{title}_{v.plane.lower()}{round(v.at, 3):g}.png",
                         f"{title}{', ' + v.title if v.title else ''}")
        summary["files"].append(str(f))
    return summary


def before_after(orig: Part, parts: dict, out: Path, stem: str, size: str = "normal") -> dict:
    """A remix next to its original (<stem>_before_after.png) and the original colored by how far
    the remix is from it (<stem>_vs_original.png, compare's deviation view), with compare's score."""
    from build123d import Compound

    from . import compare as cmp
    from .render import side_by_side

    remix_part = next(iter(parts.values())) if len(parts) == 1 else Part(Compound(
        [s for p in parts.values() for s in p.solids()]).wrapped)
    small = "_small" if size == "small" else ""
    a = render(side_by_side([(orig, "original"), (remix_part, "remix")]), out / f"{stem}_before_after{small}.png",
               f"{stem}: original (left) and remix (right)", size=size)
    r = cmp.compare(orig, remix_part)
    b = cmp.render_comparison(orig, remix_part, r, out / f"{stem}_vs_original{small}.png",
                              f"{stem}: original, red where the remix differs (score {r.score:.1f})", size=size)
    return {"files": [str(a), str(b)], "score": r.score, "text": r.text(), "metrics": r.metrics}


def run(script_file: str, argv: list[str] | None = None) -> None:
    """`__main__` entry for part scripts: export every variant (or --variant), then run checks."""
    safe_console()
    script = Path(script_file).resolve()
    mod = sys.modules.get("__main__")
    if mod is None or Path(getattr(mod, "__file__", "")).resolve() != script:
        mod = load(script)
    ap = argparse.ArgumentParser(description=f"Build {script.stem}")
    ap.add_argument("--variant", choices=[v or "standard" for v in variants(mod)], help="default: all")
    ap.add_argument("--no-check", action="store_true")
    ap.add_argument("--formats", help="comma-separated: step,stl,3mf,png or all (default: the formats setting)")
    args = ap.parse_args(argv)
    settings = load_settings(script)
    worst = 0
    nudged = False
    for key in variants(mod):
        if args.variant and variant_key(args.variant) != key:
            continue
        s = export_variant(mod, script, key, formats=parse_formats(args.formats) if args.formats else None)
        for pname, r in s["parts"].items():
            print(f"{out_name(script.stem, key, '' if pname == 'part' else pname)}: "
                  f"{r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, volume {r['volume']:.1f} mm^3, valid={r['valid']}")
        print(f"  -> {len(s['files'])} files in {script.parent / 'out'}")
        if not args.no_check:
            for f in run_checks(mod, key, settings, nudge=not nudged):
                nudged |= f.check == "hole_comp"
                if f.level != ck.OK:
                    print("  " + f.line())
                worst = max(worst, {"ok": 0, "warn": 0, "fail": 1}[f.level])
    sys.exit(worst)


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
