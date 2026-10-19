"""`b123d-print` command line: init, new, build, check, metrics, styles, faces, template, view, compare, to-step, config, list,
and MCP over SSH (setup-ssh, ssh-serve, pull, push)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from importlib.resources import files
from pathlib import Path

from . import checks as ck
from .config import CALIBRATED, FORMATS, WORKSPACE_FILE, find_workspace, load_settings, parse_formats, safe_console, user_config_path

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
            p.write_text(content, encoding="utf-8", newline="")
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
    p.parent.mkdir(parents=True, exist_ok=True)  # it may exist already: a reference file was uploaded first
    if example:
        src = files("b123d_print").joinpath("examples", example)
        p.write_text(src.joinpath(f"{example}.py").read_text(encoding="utf-8"), encoding="utf-8", newline="")
        if src.joinpath("ref").is_dir():  # a remix example's original model
            (p.parent / "ref").mkdir(exist_ok=True)
            for f in src.joinpath("ref").iterdir():
                if f.is_file() and not (p.parent / "ref" / f.name).exists():
                    (p.parent / "ref" / f.name).write_bytes(f.read_bytes())
        return p
    title = name.replace("_", " ").capitalize()
    p.write_text(data("part_template.py").format(name=name, title=title, description=description or "TODO: what it is, what it mates with."), encoding="utf-8", newline="")
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


def cmd_metrics(args) -> int:
    """Design metrics and the style's findings for each part (rough estimates; never fails)."""
    from . import metrics
    from .project import dims, load, printables, variant_key, variants

    out = []
    for script in _targets(args):
        settings = load_settings(script)
        mod = load(script)
        for key in variants(mod):
            if args.variant and variant_key(args.variant) != key:
                continue
            d = dims(mod, key)
            res = metrics.design_metrics(mod, d, printables(mod, d), settings, style=args.style, up=args.up)
            out.append({"part": script.stem, "variant": key or "standard", **res})
            if not args.json:
                print(f"{script.stem}{'[' + key + ']' if key else ''}\n{metrics.text(res)}\n")
    if args.json:
        json.dump(out, sys.stdout, indent=1, default=str)
        print()
    return 0


def cmd_styles(args) -> int:
    """List the design styles (workspace, user, built-in), or show one with based_on applied."""
    from dataclasses import fields

    from . import styles

    root, _ = workspace(args.root)
    if not args.name:
        for n, src in styles.available(root).items():
            print(f"{n:16} {src}")
        return 0
    st = styles.load_style(args.name, root)
    print(f"# {st.name}: {st.source}" + (f" (based on {st.based_on})" if st.based_on else ""))
    for f in fields(st):
        v = getattr(st, f.name)
        if f.name in ("name", "source", "based_on") or v is None or v is False or v == "":
            continue
        print(f'{f.name} = """{v.strip()}\n"""' if f.name == "review" else f"{f.name} = {json.dumps(v)}")
    return 0


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


def _one_variant(mod, want: str | None) -> str:
    from .project import variant_key, variants

    keys = list(variants(mod))
    key = variant_key(want) if want is not None else keys[0]
    if key not in keys:
        sys.exit(f"no variant {want!r}; variants: {[k or 'standard' for k in keys]}")
    return key


def cmd_faces(args) -> int:
    """The flat faces of a part with their ids, for a face template; --highlight draws one."""
    from . import templates as tp
    from .project import dims, load, printables, resolve_part

    root, parts_dir = workspace(args.root)
    script = resolve_part(args.part, root, parts_dir)
    mod = load(script)
    key = _one_variant(mod, args.variant)
    pname, part = tp.pick_part(printables(mod, dims(mod, key)), args.only)
    res = tp.list_faces(part)
    if args.json:
        json.dump(res, sys.stdout, indent=1)
        print()
    else:
        print(f"{script.stem}{'[' + key + ']' if key else ''} {pname}: {len(res['planar'])} flat faces of {res['faces']}")
        for f in res["planar"]:
            holes = ", ".join(f"d {h['d']:g} at {tuple(h['center'])}" for h in f["holes"])
            print(f"  {f['id']:3}  {f.get('side', ''):6} normal {tuple(f['normal'])}  area {f['area']:g} mm^2  "
                  f"center {tuple(f['center'])}" + (f"  holes: {holes}" if holes else "")
                  + (f"  +{f['other_openings']} other opening(s)" if f.get("other_openings") else ""))
        if res["curved"]:
            print("  curved: " + ", ".join(f"{n} {k}" for k, n in res["curved"].items()))
    if args.highlight is not None:
        face, fid = tp.find_face(part, args.highlight)
        out = script.parent / "out"
        out.mkdir(exist_ok=True)
        img = tp.highlight(part, [face], out / f"{script.stem}{'_' + key if key else ''}_face{fid}.png",
                           f"{script.stem}: face {fid} (red)")
        print(f"-> {img}")
    return 0


def cmd_view(args) -> int:
    """A self-contained HTML 3D view of a part (viewer and model inline: opens from file://, offline)."""
    from . import viewer
    from .project import dims, load, resolve_part

    root, parts_dir = workspace(args.root)
    script = resolve_part(args.part, root, parts_dir)
    mod = load(script)
    key = _one_variant(mod, args.variant)
    layout = "assembly" if args.assembly else "print"
    only = [n.strip() for n in args.only.split(",") if n.strip()] if args.only else None
    try:
        glb = viewer.write_view(mod, dims(mod, key), "_".join(x for x in (script.stem, key) if x),
                                script.parent / "out", layout, only)
    except (KeyError, ValueError) as e:
        sys.exit(f"view: {str(e).strip(chr(34))}")
    page = viewer.write_offline(glb)
    print(f"{script.stem}{'[' + key + ']' if key else ''}: {page}  ({page.stat().st_size / 1e6:.1f} MB, works offline)")
    if args.open:
        import webbrowser

        webbrowser.open(page.resolve().as_uri())
    return 0


def _triple(text: str, what: str) -> tuple[float, float, float]:
    try:
        v = tuple(float(x) for x in text.split(","))
    except ValueError:
        v = ()
    if len(v) != 3:
        sys.exit(f"{what}: three numbers x,y,z")
    return v


def cmd_template(args) -> int:
    """Make a fit-test template from a part (--slice, --face or --crop), write it and check it."""
    from . import templates as tp
    from .project import dims, load, printables, resolve_part, write_template

    root, parts_dir = workspace(args.root)
    script = resolve_part(args.part, root, parts_dir)
    common = dict(thickness=args.thickness, label=not args.no_label, base=not args.no_base, part=args.only,
                  name=args.name or "")
    if args.slice:
        plane, _, at = args.slice.partition(":")
        try:
            spec = tp.Template.slice(plane.upper(), float(at), **common)
        except ValueError:
            sys.exit("--slice PLANE:AT, e.g. XY:3 (XY at Z, XZ at Y, YZ at X)")
    elif args.face:
        f = args.face
        spec = tp.Template.face_of(int(f) if f.isdigit() else (_triple(f, "--face") if "," in f else f), **common)
    else:
        c, _, sz = args.crop.partition(":")
        spec = tp.Template.crop(_triple(c, "--crop center"), _triple(sz, "--crop size"), **common)
    mod = load(script)
    key = _one_variant(mod, args.variant)
    settings = load_settings(script)
    try:
        r = write_template(script, key, printables(mod, dims(mod, key)), spec, script.parent / "out",
                           parse_formats(args.formats) if args.formats else settings.formats, settings)
    except tp.TemplateError as e:
        sys.exit(f"template: {e}")
    rep, info = r["report"], r["info"]
    print(f"{r['name']}: {rep['x']:.2f} x {rep['y']:.2f} x {rep['z']:.2f} mm, valid={rep['valid']}, "
          f"{info['pieces']} piece(s), {info['down']} side down"
          + (" (print orientation)" if info["print_orientation"] else ""))
    lab = info.get("label")
    print(f"  label: {lab['text']!r}" if lab else "  label: none")
    for n in info.get("notes", []):
        print(f"  note: {n}")
    worst = 0
    for f in r["findings"]:
        if f["level"] != ck.OK:
            print("  " + ck.Finding(**f).line())
        worst = max(worst, f["level"] == ck.FAIL)
    print(f"  -> {len(r['files'])} files in {script.parent / 'out'}")
    return worst


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


def cmd_to_step(args) -> int:
    from build123d import export_step

    from . import remix

    src = Path(args.input)
    try:
        part, info = remix.load(src, remix.UNITS[args.scale] if args.scale in remix.UNITS else float(args.scale),
                                args.max_triangles, merge=not args.no_merge)
    except (OSError, ValueError) as e:
        sys.exit(f"to-step: {e}")
    out = Path(args.output) if args.output else src.with_suffix(".step")
    if out.resolve() == src.resolve():
        sys.exit("to-step: the output would overwrite the input; pass -o")
    export_step(part, out)
    print(f"{src.name}: {info.units}; {info.triangles if info.triangles is not None else '-'} triangles -> "
          f"{info.faces_after} faces ({info.planar_faces} planar)")
    print(f"  faces before merging: {info.faces_before}, after: {info.faces_after}")
    print(f"  {' x '.join(f'{x:.2f}' for x in info.size)} mm, volume {info.volume:.1f} mm^3, {info.solids} solid(s), "
          f"{info.seconds:g} s")
    if info.faceted.get("faces"):
        print(f"  curves stay faceted: {info.faceted['faces']} faces ({info.faceted['area_share']:.0%} of the surface) "
              "are facets of curved surfaces (no curve fitting)")
    else:
        print("  no curved (faceted) surfaces")
    for line in info.repairs + info.warnings:
        print(f"  {line}")
    print(f"-> {out}")
    return 0


def cmd_ssh(args) -> int:
    import os

    from . import ssh

    if args.cmd == "ssh-serve":
        return ssh.serve(args.workspace, args.dest, args.timeout, os.environ.get("SSH_ORIGINAL_COMMAND"),
                         check_timeout=args.check_timeout)
    if args.cmd == "setup-ssh":
        try:
            return ssh.setup(args.key, args.workspace, args.host, args.add,
                             Path(args.authorized_keys).expanduser() if args.authorized_keys else None)
        except (OSError, ValueError) as e:
            sys.exit(f"setup-ssh: {e}")
    if args.cmd == "push":
        try:
            print(ssh.push(Path(args.file), args.part, args.dest, args.name, args.overwrite, args.ssh))
        except RuntimeError as e:
            sys.exit(f"push: {e}")
        return 0
    try:
        got = ssh.pull(args.part, args.source, Path(args.out), args.formats, args.ssh, args.variant)
    except (RuntimeError, ValueError) as e:
        sys.exit(f"pull: {e}")
    print("\n".join(str(p) for p in got))
    return 0


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
    p = sub.add_parser("metrics", help="design metrics and the style's suggestions (filament, time, edges, ...)")
    p.add_argument("parts", nargs="*", help="part names or script paths (default: all)")
    p.add_argument("--variant")
    p.add_argument("--style", help="override the part's STYLE: functional, modern, least_cost, rugged, soft, structural")
    p.add_argument("--up", help="the side that points up in use, for water traps: +X, -Y, ... (default: UP, else +Z)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("faces", help="list a part's flat faces with their ids (for a face template)")
    p.add_argument("part", help="part name or script path")
    p.add_argument("--variant")
    p.add_argument("--part", dest="only", metavar="NAME", help="which printable part (default: the only one)")
    p.add_argument("--highlight", metavar="ID", help="also draw the part with this face (id or side) in red")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("template", help="a fit-test template: a thin print cut from the part to check size, holes and fits")
    p.add_argument("part", help="part name or script path")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--slice", metavar="PLANE:AT", help="the part between two planes around AT: XY:3 (Z=3), XZ:0 (Y), YZ:-5 (X)")
    g.add_argument("--face", metavar="ID", help="one flat face as a plate: an id from `faces`, a side (bottom, top, ...) "
                                                "or a point x,y,z on it")
    g.add_argument("--crop", metavar="X,Y,Z:SX,SY,SZ", help="the part inside a box: center and size in mm")
    p.add_argument("--thickness", type=float, default=1.2, help="mm (default 1.2)")
    p.add_argument("--no-label", action="store_true", help="no engraved label")
    p.add_argument("--no-base", action="store_true", help="never add the thin base plate (slice, crop)")
    p.add_argument("--name", help="the template id in file names (default: from the arguments, e.g. xy3)")
    p.add_argument("--variant", help="default: the first variant")
    p.add_argument("--part", dest="only", metavar="NAME", help="which printable part (default: the only one)")
    p.add_argument("--formats", help=f"comma-separated, from {','.join(FORMATS)} or all (default: the formats setting)")
    p = sub.add_parser("view", help="write a self-contained HTML 3D view of a part (rotate it in a browser, offline)")
    p.add_argument("part", help="part name or script path")
    p.add_argument("--variant", help="one variant (default: the first)")
    p.add_argument("--parts", dest="only", help="comma-separated printable parts to show (default: all)")
    p.add_argument("--assembly", action="store_true", help="show assembly(d), stand-ins included, instead of the "
                                                            "printable parts on the bed")
    p.add_argument("--open", action="store_true", help="also open it in the default browser")
    p = sub.add_parser("styles", help="list the design styles (yours and the built-in ones), or show one")
    p.add_argument("name", nargs="?", help="a style to show, with based_on applied")
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
    p = sub.add_parser("to-step", help="convert an STL/3MF mesh to a STEP solid (coplanar triangles merged into faces; "
                                       "curves stay faceted) and report what changed")
    p.add_argument("input", help="the .stl or .3mf (or .step, to check it)")
    p.add_argument("-o", "--output", help="the .step to write (default: next to the input)")
    p.add_argument("--scale", default="1", help="a factor or the unit the file is in: inch, cm, m, ... (default 1: mm)")
    p.add_argument("--max-triangles", type=int, help="refuse bigger meshes (default: the max_triangles setting)")
    p.add_argument("--no-merge", action="store_true", help="keep one face per triangle")
    p = sub.add_parser("setup-ssh", help="on the server: the authorized_keys line that gives one client key the MCP server "
                                         "in one workspace, and the client config to match")
    p.add_argument("--key", required=True, help="the client's public key file (.pub), or - for stdin")
    p.add_argument("--workspace", required=True, help="a name (-> ~/parts/<name>) or a folder path")
    p.add_argument("--host", help="the name clients reach this machine by (default: its FQDN)")
    p.add_argument("--add", action="store_true", help="also put the line into authorized_keys (replaces this key's earlier b123d-print line)")
    p.add_argument("--authorized-keys", help="file to add it to (default: ~/.ssh/authorized_keys)")
    p = sub.add_parser("ssh-serve", help="the forced command in authorized_keys (written by setup-ssh): runs the MCP "
                                         "server, `pull` or `version` for $SSH_ORIGINAL_COMMAND, refuses anything else")
    p.add_argument("--workspace", required=True, help="the workspace this key is pinned to")
    p.add_argument("--dest", help="user@host as clients see it, for the pull command export suggests")
    p.add_argument("--timeout", type=float, help="seconds per build (default 120)")
    p.add_argument("--check-timeout", type=float, help="seconds per check run (default 300, or --timeout if longer)")
    p = sub.add_parser("pull", help="on the client: copy a part (script, out/, ref/) from an SSH server into "
                                    "parts/<part>/ of the project folder")
    p.add_argument("part")
    p.add_argument("--from", dest="source", required=True, metavar="USER@HOST", help="the server, as in your MCP config")
    p.add_argument("--formats", help=f"only these out/ files, comma-separated, from {','.join(FORMATS)} (default: every file in out/)")
    p.add_argument("--variant", help="only this variant's out/ files ('standard' for the default one)")
    p.add_argument("-o", "--out", default=".", help="the project folder; the part goes to <it>/parts/<part>/ (default: the current folder)")
    p.add_argument("--ssh", default="ssh", help="ssh command and options, e.g. 'ssh -i ~/.ssh/b123d_print -p 2222' (default: ssh)")
    p = sub.add_parser("push", help="on the client: copy a model to remix (STL/3MF/STEP) to an SSH server, into "
                                    "parts/<part>/ref/")
    p.add_argument("file")
    p.add_argument("--part", required=True, help="the part it is for (the folder is created if needed)")
    p.add_argument("--to", dest="dest", required=True, metavar="USER@HOST", help="the server, as in your MCP config")
    p.add_argument("--name", help="file name on the server (default: the file's own name)")
    p.add_argument("--overwrite", action="store_true", help="replace a reference file of the same name")
    p.add_argument("--ssh", default="ssh", help="ssh command and options (default: ssh)")
    sub.add_parser("config", help="show the settings in effect")
    sub.add_parser("list", help="list parts in the workspace")
    sub.add_parser("examples", help="list the bundled example parts")
    p = sub.add_parser("mcp", add_help=False,
                       help="run the MCP server: the same as b123d-print-mcp, with all its options "
                            "(b123d-print mcp --help); lets `uvx b123d-print mcp` start it")
    p.add_argument("args", nargs=argparse.REMAINDER)
    return ap


def main(argv: list[str] | None = None) -> int:
    safe_console()
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw[:1] == ["mcp"]:  # hand everything after `mcp` to the MCP server untouched
        from .mcp_server import main as mcp_main

        mcp_main(raw[1:])
        return 0
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
    if args.cmd in ("setup-ssh", "ssh-serve", "pull", "push"):
        return cmd_ssh(args)
    if args.cmd == "examples":
        print("\n".join(examples()))
        return 0
    if args.cmd == "list":
        from .project import find_parts

        root, parts_dir = workspace(args.root)
        for p in find_parts(root, parts_dir):
            print(p.relative_to(root))
        return 0
    if args.cmd in ("metrics", "styles"):
        try:
            return cmd_metrics(args) if args.cmd == "metrics" else cmd_styles(args)
        except ValueError as e:
            sys.exit(str(e))
    if args.cmd in ("faces", "template"):
        from .templates import TemplateError

        try:
            return cmd_faces(args) if args.cmd == "faces" else cmd_template(args)
        except (TemplateError, FileNotFoundError) as e:
            sys.exit(f"{args.cmd}: {e}")
    return {"build": cmd_build, "check": cmd_check, "compare": cmd_compare, "to-step": cmd_to_step,
            "view": cmd_view}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
