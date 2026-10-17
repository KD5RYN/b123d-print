"""`cadkit` command line: init, new, build, check, config, list."""

from __future__ import annotations

import argparse
import json
import re
import sys
from importlib.resources import files
from pathlib import Path

from . import checks as ck
from .config import WORKSPACE_FILE, find_workspace, load_settings, user_config_path

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


def data(name: str) -> str:
    return files("cadkit").joinpath("data", name).read_text()


def workspace(root: str | None) -> tuple[Path, str]:
    """(root, parts_dir) from --root, else the nearest cadkit.toml, else the cwd."""
    r = Path(root).resolve() if root else (find_workspace() or Path.cwd())
    return r, load_settings(r).parts_dir


def init_workspace(root: Path) -> list[Path]:
    """Create cadkit.toml, AGENTS.md and parts/ (existing files are left alone)."""
    root.mkdir(parents=True, exist_ok=True)
    made = []
    for fname, content in ((WORKSPACE_FILE, data("cadkit.toml")), ("AGENTS.md", data("AGENTS.md"))):
        p = root / fname
        if not p.exists():
            p.write_text(content)
            made.append(p)
    (root / "parts").mkdir(exist_ok=True)
    return made


def examples() -> list[str]:
    base = files("cadkit").joinpath("examples")
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
        p.write_text(files("cadkit").joinpath("examples", example, f"{example}.py").read_text())
        return p
    title = name.replace("_", " ").capitalize()
    p.write_text(data("part_template.py").format(name=name, title=title, description=description or "TODO: what it is, what it mates with."))
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
            findings = run_checks(mod, key, settings)
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
            s = export_variant(mod, script, key)
            for pname, r in s["parts"].items():
                print(f"{script.stem}{'[' + key + ']' if key else ''} {pname}: {r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, "
                      f"volume {r['volume']:.1f} mm^3, valid={r['valid']}")
            print(f"  -> {len(s['files'])} files in {script.parent / 'out'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="cadkit", description="build123d part workflow: scaffold, build, check")
    ap.add_argument("--root", help="workspace root (default: nearest cadkit.toml, else the cwd)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("init", help="create a workspace (cadkit.toml, AGENTS.md, parts/)")
    p.add_argument("dir", nargs="?", default=".")
    p = sub.add_parser("new", help="scaffold parts/<name>/<name>.py from the template")
    p.add_argument("name")
    p.add_argument("-d", "--description", default="")
    p.add_argument("--from", dest="example", help="start from a bundled example (see `cadkit examples`)")
    for name, hlp in (("build", "export STEP/STL/PNG + section views"), ("check", "run checks; exit 1 on failure")):
        p = sub.add_parser(name, help=hlp)
        p.add_argument("parts", nargs="*", help="part names or script paths (default: all)")
        p.add_argument("--variant")
        if name == "check":
            p.add_argument("--json", action="store_true")
            p.add_argument("-v", "--verbose", action="store_true", help="also list passing checks")
    sub.add_parser("config", help="show the settings in effect")
    sub.add_parser("list", help="list parts in the workspace")
    sub.add_parser("examples", help="list the bundled example parts")
    args = ap.parse_args(argv)

    if args.cmd == "init":
        made = init_workspace(Path(args.dir).resolve())
        print("\n".join(f"created {m}" for m in made) or "workspace already set up")
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
    if args.cmd == "examples":
        print("\n".join(examples()))
        return 0
    if args.cmd == "list":
        from .project import find_parts

        root, parts_dir = workspace(args.root)
        for p in find_parts(root, parts_dir):
            print(p.relative_to(root))
        return 0
    return {"build": cmd_build, "check": cmd_check}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
