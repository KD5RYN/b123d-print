"""`b123d-print` command line: init, new, build, check, compare, config, list."""

from __future__ import annotations

import argparse
import json
import re
import sys
from importlib.resources import files
from pathlib import Path

from . import checks as ck
from .config import CALIBRATED, FORMATS, WORKSPACE_FILE, find_workspace, load_settings, parse_formats, user_config_path

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def data(name: str) -> str:
    return files("b123d_print").joinpath("data", name).read_text(encoding="utf-8")


def workspace(root: str | None) -> tuple[Path, str]:
    """(root, parts_dir) from --root, else the nearest b123d-print.toml, else the cwd."""
    r = Path(root).resolve() if root else (find_workspace() or Path.cwd())
    return r, load_settings(r).parts_dir


def init_workspace(root: Path, update_agents: bool = False) -> list[Path]:
    """Create b123d-print.toml, AGENTS.md and parts/ (existing files are left alone, except
    AGENTS.md with update_agents: replaced by this version's workflow text)."""
    root.mkdir(parents=True, exist_ok=True)
    made = []
    for fname, content in ((WORKSPACE_FILE, data("b123d-print.toml")), ("AGENTS.md", data("AGENTS.md"))):
        p = root / fname
        if not p.exists() or (update_agents and fname == "AGENTS.md" and p.read_text(encoding="utf-8") != content):
            p.write_text(content, encoding="utf-8")
            made.append(p)
    (root / "parts").mkdir(exist_ok=True)
    return made


def examples() -> list[str]:
    base = files("b123d_print").joinpath("examples")
    return sorted(d.name for d in base.iterdir() if d.joinpath(f"{d.name}.py").is_file())


def new_part(root: Path, parts_dir: str, name: str, description: str = "", example: str | None = None) -> Path:
    """Scaffold <parts_dir>/<name>/<name>.py from the template, or copy a bundled example."""
    if example and example not in examples():
        raise ValueError(f"no example {example!r}; examples: {examples()}")
    if not NAME_RE.match(name):
        raise ValueError(f"part name {name!r}: use lower_snake_case (letters, digits, _), starting with a letter")
    p = root / parts_dir / name / f"{name}.py"
    if p.exists():
        raise FileExistsError(f"{p} already exists")
    p.parent.mkdir(parents=True)
    if example:
        p.write_text(files("b123d_print").joinpath("examples", example, f"{example}.py").read_text(encoding="utf-8"))
        return p
    title = name.replace("_", " ").capitalize()
    p.write_text(data("part_template.py").format(name=name, title=title, description=description or "TODO: what it is, what it mates with."), encoding="utf-8")
    return p


def _targets(args) -> list[Path]:
    from .project import find_parts, resolve_part

    root, parts_dir = workspace(args.root)
    if args.parts:
        return [resolve_part(s, root, parts_dir) for s in args.parts]
    found = find_parts(root, parts_dir)
    if not found:
        sys.exit(f"no parts under {root / parts_dir} (expected <name>/<name>.py)")
    return found


def cmd_check(args) -> int:
    from .project import load, run_checks, variant_key, variants

    worst = 0
    report = []
    nudged = False  # setup reminders (hole_comp unset) once per run
    for script in _targets(args):
        settings = load_settings(script)
        try:
            mod = load(script)
            keys = list(variants(mod))
        except Exception as e:
            f = ck.Finding(ck.FAIL, "error", script.stem, f"script failed to load: {e!r}")
            report.append({"part": script.stem, "variant": None, "findings": [f.__dict__]})
            print(f"{script.stem}\n  {f.line()}")
            worst = 1
            continue
        for key in keys:
            if args.variant and variant_key(args.variant) != key:
                continue
            findings = run_checks(mod, key, settings, nudge=not nudged)
            nudged |= any(f.check == "hole_comp" for f in findings)
            report.append({"part": script.stem, "variant": key or "standard", "findings": [f.__dict__ for f in findings]})
            if not args.json:
                n = {lvl: sum(f.level == lvl for f in findings) for lvl in (ck.OK, ck.WARN, ck.FAIL)}
                print(f"{script.stem}{'[' + key + ']' if key else ''}: {n['ok']} ok, {n['warn']} warn, {n['fail']} fail")
                for f in findings:
                    if args.verbose or f.level != ck.OK:
                        print("  " + f.line())
            if any(f.level == ck.FAIL for f in findings):
                worst = 1
    if args.json:
        json.dump(report, sys.stdout, indent=1, default=str)
        print()
    else:
        print("FAILED" if worst else "all checks passed")
    return worst


def cmd_build(args) -> int:
    from .project import export_variant, load, variant_key, variants

    for script in _targets(args):
        mod = load(script)
        for key in variants(mod):
            if args.variant and variant_key(args.variant) != key:
                continue
            s = export_variant(mod, script, key, formats=parse_formats(args.formats) if args.formats else None)
            for pname, r in s["parts"].items():
                print(f"{script.stem}{'[' + key + ']' if key else ''} {pname}: {r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, "
                      f"volume {r['volume']:.1f} mm^3, valid={r['valid']}")
            print(f"  -> {len(s['files'])} files in {script.parent / 'out'}")
    return 0


def cmd_printer(args) -> int:
    from . import profiles as pf
    from .config import set_user_setting

    if args.pcmd == "list":
        hits = pf.search("printers", " ".join(args.query))
        print("\n".join(hits[:200]) or "no match")
        if len(hits) > 200:
            print(f"... {len(hits) - 200} more; add words to narrow it")
        return 0
    if args.pcmd == "show":
        s = load_settings()
        name = args.name or s.printer
        if not name:
            print("generic (no printer profile): min wall 0.8, overhang 45 deg, no fit check")
            return 0
        print(pf.load_printer(name).summary())
        if not args.name and s.material:
            print(pf.load_material(s.material).summary())
        return 0
    if args.pcmd == "use":
        if args.name in ("generic", "none", ""):
            set_user_setting("printer", None)
            path = set_user_setting("material", None)
            print(f"generic mode ({path})")
            return 0
        pr = pf.load_printer(args.name)  # raises with suggestions if unknown
        path = set_user_setting("printer", args.name)
        if args.material:
            print(pf.load_material(args.material).summary())
            set_user_setting("material", args.material)
        print(f"{pr.summary()}\nsaved to {path}")
        return 0
    if args.pcmd in ("hole-comp", "calibrate"):
        key = "hole_comp" if args.pcmd == "hole-comp" else args.key
        s = load_settings()
        if not s.printer:
            sys.exit(f"set a printer first (b123d-print printer use <name>), or put {key} in your config")
        print(f"{key} {args.value:g} for {s.printer}/{s.material or 'any'} -> {pf.save_calibration(s.printer, s.material, key, args.value)}")
        return 0
    return 1


def cmd_compare(args) -> int:
    from .compare import Criteria, compare, render_comparison

    try:
        crit = Criteria.from_pairs(args.threshold)
        r = compare(args.reference, args.candidate, criteria=crit, samples=args.samples, icp=not args.no_icp, seed=args.seed)
    except (OSError, ValueError) as e:
        sys.exit(f"compare: {e}")
    if args.image:
        render_comparison(args.reference, args.candidate, r, args.image)
    if args.json:
        json.dump(r.as_dict(), sys.stdout, indent=1)
        print()
    else:
        print(r.text())
        if args.image:
            print(f"deviation view: {args.image}")
    return 0 if r.passed else 1


def _version() -> str:
    from importlib.metadata import version

    return version("b123d-print")


def build_parser() -> argparse.ArgumentParser:
    """The whole command line; the docs' CLI reference is generated from it."""
    ap = argparse.ArgumentParser(prog="b123d-print", description="build123d part workflow: scaffold, build, check")
    ap.add_argument("--root", help="workspace root (default: nearest b123d-print.toml, else the cwd)")
    ap.add_argument("--version", action="version", version=f"b123d-print {_version()}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a workspace (b123d-print.toml, AGENTS.md, parts/)")
    p.add_argument("dir", nargs="?", default=".")
    p.add_argument("--update-agents", action="store_true", help="replace AGENTS.md with this version's text")
    p = sub.add_parser("new", help="scaffold parts/<name>/<name>.py from the template")
    p.add_argument("name")
    p.add_argument("-d", "--description", default="")
    p.add_argument("--from", dest="example", help="start from a bundled example (see `b123d-print examples`)")
    for name, hlp in (("build", "export STEP/STL/3MF/PNG + section views"), ("check", "run checks; exit 1 on failure")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("parts", nargs="*", help="part names or script paths (default: all)")
        p.add_argument("--variant")
        if name == "build":
            p.add_argument("--formats", help=f"comma-separated, from {','.join(FORMATS)} or all (default: the formats setting)")
        if name == "check":
            p.add_argument("--json", action="store_true")
            p.add_argument("-v", "--verbose", action="store_true", help="also list passing checks")
    p = sub.add_parser("printer", help="optional printer/material profile (default: generic)")
    psub = p.add_subparsers(dest="pcmd", required=True)
    q = psub.add_parser("list", help="search the printer profiles (from OrcaSlicer's library + yours)")
    q.add_argument("query", nargs="*")
    q = psub.add_parser("show", help="show a printer (default: the active one)")
    q.add_argument("name", nargs="?")
    q = psub.add_parser("use", help="set the active printer in your user config; 'generic' clears it")
    q.add_argument("name")
    q.add_argument("--material", help="pla, petg, asa, abs, tpu or your own")
    q = psub.add_parser("hole-comp", help="store a measured hole compensation for the active printer + material")
    q.add_argument("value", type=float)
    q = psub.add_parser("calibrate", help="store a value measured with a calibration coupon for the active printer + material")
    q.add_argument("key", choices=CALIBRATED)
    q.add_argument("value", type=float)
    p = sub.add_parser("compare", help="compare a part with a reference (STL/3MF/STEP); exit 1 if it fails the thresholds")
    p.add_argument("reference")
    p.add_argument("candidate")
    p.add_argument("--json", action="store_true")
    p.add_argument("--threshold", action="append", metavar="NAME=VALUE",
                   help="override a pass/fail threshold, e.g. hausdorff_mm=2 (repeatable; see b123d_print.compare.Criteria)")
    p.add_argument("--samples", type=int, default=20_000, help="surface points per part (default 20000)")
    p.add_argument("--no-icp", action="store_true", help="skip the ICP refinement after the axis search")
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--image", help="also write a deviation view (PNG) here")
    sub.add_parser("config", help="show the settings in effect")
    sub.add_parser("list", help="list parts in the workspace")
    sub.add_parser("examples", help="list the bundled example parts")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "init":
        made = init_workspace(Path(args.dir).resolve(), args.update_agents)
        print("\n".join(f"wrote {m}" for m in made) or "workspace already set up (AGENTS.md unchanged)")
        return 0
    if args.cmd == "new":
        root, parts_dir = workspace(args.root)
        print(f"created {new_part(root, parts_dir, args.name, args.description, args.example)}")
        return 0
    if args.cmd == "config":
        root, _ = workspace(args.root)
        s = load_settings(root)
        print(f"user config:      {user_config_path()} ({'found' if user_config_path().is_file() else 'none'})")
        print(f"workspace config: {s.root / WORKSPACE_FILE if s.root else 'none'}")
        for k, v in s.__dict__.items():
            print(f"  {k} = {v}")
        return 0
    if args.cmd == "printer":
        try:
            return cmd_printer(args)
        except (KeyError, ValueError) as e:
            sys.exit(str(e).strip('"'))
    if args.cmd == "examples":
        print("\n".join(examples()))
        return 0
    if args.cmd == "list":
        from .project import find_parts

        root, parts_dir = workspace(args.root)
        for p in find_parts(root, parts_dir):
            print(p.relative_to(root))
        return 0
    return {"build": cmd_build, "check": cmd_check, "compare": cmd_compare}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
