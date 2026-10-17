"""Part-script convention and the runner behind `cadkit build` / `cadkit check` / the MCP tools.

A part script lives at <parts_dir>/<name>/<name>.py and defines:

    @dataclass(frozen=True)
    class Dims: ...                  # UPPER_CASE fields in mm; derived values as properties
    VARIANTS = {"": {}, "big": dict(WIDTH=80.0)}   # overrides only; "" is the standard part
    def build(d) -> Part | dict[str, Part]          # printable parts, in PRINT orientation

and optionally:

    def assembly(d) -> list[(Part, color, label)]   # assembled position, incl. stand-ins for
                                                    # the things it mates with -> overlap check
    def views(d) -> list[View]                      # section views saved on export
    def checks(d) -> list[Overhang | Wall | Overlap]  # default: Overhang (report) per part

    if __name__ == "__main__":
        from cadkit import run
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
from .config import Settings, load_settings
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
    name = f"cadkit_part_{path.stem}"
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


def assembly(mod: ModuleType, d) -> list[tuple[Part, str, str]] | None:
    f = getattr(mod, "assembly", None)
    return f(d) if f else None


def out_name(stem: str, key: str, part: str) -> str:
    return "_".join(x for x in (stem, key, part) if x)


def check_specs(mod: ModuleType, d, parts: dict, asm) -> list:
    f = getattr(mod, "checks", None)
    specs = list(f(d) if f else [])
    covered = {s.part for s in specs if isinstance(s, ck.Overhang)}
    specs += [ck.Overhang(p) for p in parts if p not in covered]  # always report overhangs
    if asm and not any(isinstance(s, ck.Overlap) for s in specs):
        specs.append(ck.Overlap())
    return specs


def run_checks(mod: ModuleType, key: str, settings: Settings) -> list[ck.Finding]:
    """Build one variant and run every check. Never raises: errors become findings."""
    tag = key or "standard"
    try:
        d = dims(mod, key)
        parts = printables(mod, d)
        asm = assembly(mod, d)
    except Exception as e:
        return [ck.Finding(ck.FAIL, "error", tag, f"build failed: {e!r}", {"traceback": traceback.format_exc()})]
    out = []
    for name, p in parts.items():
        valid = bool(p.is_valid) and p.volume > 0
        out.append(ck.Finding(ck.OK if valid else ck.FAIL, "valid", name or "part",
                              "valid solid" if valid else f"is_valid={p.is_valid}, volume={p.volume:.3f}", report(p)))
    for spec in check_specs(mod, d, {(k or "part"): v for k, v in parts.items()}, asm):
        try:
            out.extend(spec.run({(k or "part"): v for k, v in parts.items()}, asm, settings))
        except Exception as e:
            out.append(ck.Finding(ck.FAIL, "error", getattr(spec, "part", type(spec).__name__), repr(e),
                                  {"traceback": traceback.format_exc()}))
    return out


def export_variant(mod: ModuleType, script: Path, key: str, out: Path | None = None) -> dict:
    """Export STEP/STL/PNG of every printable part, plus the views. Returns a summary."""
    out = out or script.parent / "out"
    out.mkdir(parents=True, exist_ok=True)
    d = dims(mod, key)
    parts = printables(mod, d)
    asm = assembly(mod, d)
    summary = {"variant": key or "standard", "parts": {}, "files": []}
    for pname, p in parts.items():
        name = out_name(script.stem, key, pname)
        files = export_files(p, out, name)
        summary["parts"][pname or "part"] = report(p)
        summary["files"] += [str(f) for f in files]
    if asm:
        f = render(asm, out / f"{out_name(script.stem, key, 'assembly')}.png", f"{out_name(script.stem, key, '')} assembly")
        summary["files"].append(str(f))
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


def run(script_file: str, argv: list[str] | None = None) -> None:
    """`__main__` entry for part scripts: export every variant (or --variant), then run checks."""
    script = Path(script_file).resolve()
    mod = sys.modules.get("__main__")
    if mod is None or Path(getattr(mod, "__file__", "")).resolve() != script:
        mod = load(script)
    ap = argparse.ArgumentParser(description=f"Build {script.stem}")
    ap.add_argument("--variant", choices=[v or "standard" for v in variants(mod)], help="default: all")
    ap.add_argument("--no-check", action="store_true")
    args = ap.parse_args(argv)
    settings = load_settings(script)
    worst = 0
    for key in variants(mod):
        if args.variant and variant_key(args.variant) != key:
            continue
        s = export_variant(mod, script, key)
        for pname, r in s["parts"].items():
            print(f"{out_name(script.stem, key, '' if pname == 'part' else pname)}: "
                  f"{r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, volume {r['volume']:.1f} mm^3, valid={r['valid']}")
        print(f"  -> {len(s['files'])} files in {script.parent / 'out'}")
        if not args.no_check:
            for f in run_checks(mod, key, settings):
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
