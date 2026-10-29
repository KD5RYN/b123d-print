"""`b123d-print` command line: init, setup, new, build, check, bom, metrics, orient, styles, faces, edges, template, view, compare, to-step, config, list,
version history (save, versions, restore) and MCP over SSH (setup-ssh, ssh-serve, pull, push)."""

from __future__ import annotations

import argparse
import json
import re
import sys
from importlib.resources import files
from pathlib import Path

from . import outdir
from .config import CALIBRATED, FORMATS, WORKSPACE_FILE, find_workspace, hole_comp_source, load_settings, parse_formats, safe_console, user_config_path

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
    from .partfiles import find_parts, resolve_part

    root, parts_dir = workspace(args.root)
    if args.parts:
        return [resolve_part(s, root, parts_dir) for s in args.parts]
    found = find_parts(root, parts_dir)
    if not found:
        sys.exit(f"no parts under {root / parts_dir} (expected <name>/<name>.py)")
    return found


def cmd_check(args) -> int:
    from . import checks as ck
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
                    if args.verbose or f.level != ck.OK or f.data.get("accepted"):  # accepted: PRINT intent, shown
                        print("  " + f.line())
            if any(f.level == ck.FAIL for f in findings):
                worst = 1
    if args.json:
        json.dump(report, sys.stdout, indent=1, default=str)
        print()
    else:
        print("FAILED" if worst else "all checks passed")
    return worst


def cmd_fit(args) -> int:
    """Fit between the pieces of each part's assembly(d): interference and hole alignment."""
    from . import checks as ck, fit
    from .project import load, variant_key, variants

    worst, out = 0, []
    for script in _targets(args):
        settings = load_settings(script)
        mod = load(script)
        if not hasattr(mod, "assembly"):
            if args.parts:
                print(f"{script.stem}: no assembly(d), nothing to fit")
            continue
        for key in variants(mod):
            if args.variant and variant_key(args.variant) != key:
                continue
            r = fit.run_fit(mod, key, settings, hole_tol=args.hole_tol)
            out.append({"part": script.stem, "variant": r["variant"], "findings": [f.__dict__ for f in r["findings"]]})
            if not args.json:
                print(fit.text(r, script.stem, args.verbose))
            if any(f.level == ck.FAIL for f in r["findings"]):
                worst = 1
    if args.json:
        json.dump(out, sys.stdout, indent=1, default=str)
        print()
    elif not out:
        print("no part with an assembly(d)")
    return worst


def cmd_trace(args) -> int:
    """Trace a flat object in a scan or photo into an outline in mm (the same as trace_outline)."""
    from . import trace as tr

    def nums(v, n, what):
        if v is None:
            return None
        vals = [float(x) for x in v.split(",")]
        if len(vals) != n:
            sys.exit(f"trace: {what} takes {n} comma-separated numbers")
        return vals

    ref = args.reference
    if ref and "," in ref:
        ref = nums(ref, 2, "--reference")
    scale = tr.Scale(dpi=args.dpi, grid=args.grid, reference=ref, points=nums(args.points, 4, "--points"),
                     distance=args.distance)
    image = Path(args.image)
    try:
        res = tr.trace(image, scale, tolerance=args.tolerance, smooth=args.smooth, threshold=args.threshold,
                       invert=True if args.invert else None, pick=nums(args.pick, 2, "--pick"))
    except tr.TraceError as e:
        sys.exit(f"trace: {e}")
    out = Path(args.out) if args.out else image.parent
    tr.write(res, out, image.stem, title=image.name)
    if args.json:
        json.dump(res.as_dict(), sys.stdout, indent=1, default=str)
        print()
    else:
        print(tr.text(res))
        for f in res.files.values():
            print(f"  -> {f}")
    return 0


def cmd_recipes(args) -> int:
    """List the recipes, or print one (code, example, printing notes, sources)."""
    from . import recipes

    if not args.name:
        for r in recipes.RECIPES.values():
            print(f"{r.name:15} {r.title}")
        return 0
    try:
        print(recipes.get(args.name).text())
    except KeyError as e:
        sys.exit(e.args[0])
    return 0


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


def cmd_orient(args) -> int:
    """Rank the print orientations of each part (never changes the script)."""
    from . import orient
    from .project import Pieces, dims, load, out_name, variant_key, variants
    from .render import render

    out = []
    for script in _targets(args):
        settings = load_settings(script)
        mod = load(script)
        for key in variants(mod):
            if args.variant and variant_key(args.variant) != key:
                continue
            d = dims(mod, key)
            ranked, best = orient.for_script(mod, d, Pieces(mod, d).parts(args.piece), settings, args.piece, args.load)
            for n, r in ranked.items():
                tag = out_name(script.stem, key, "" if n == "part" else n)
                if args.image:
                    img = outdir.path(script.parent / "out", f"{tag}_orient.png")
                    rows = r["candidates"]
                    r["image"] = str(render(best[n], img, f"{tag}: {orient._fmt_rot(rows[0]['rot'])}, {rows[0]['down']} "
                                                          "side on the bed"))
                out.append({"part": script.stem, "variant": key or "standard", "piece": n, **r})
                if not args.json:
                    print(orient.text(tag, r) + (f"\nimage: {r['image']}" if args.image else "") + "\n")
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
    from .project import export_variant, load, timing_lines, variant_key, variants

    for script in _targets(args):
        mod = load(script)
        for key in variants(mod):
            if args.variant and variant_key(args.variant) != key:
                continue
            try:
                s = export_variant(mod, script, key, formats=parse_formats(args.formats) if args.formats else None,
                                   only=args.only)
            except KeyError as e:
                sys.exit(f"build: {e.args[0]}")
            for pname, r in s["parts"].items():
                print(f"{script.stem}{'[' + key + ']' if key else ''} {pname}: {r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, "
                      f"volume {r['volume']:.1f} mm^3, valid={r['valid']}")
            for line in timing_lines(s["timing"]):
                print(f"  {line}")
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
        img = tp.highlight(part, [face], outdir.path(script.parent / "out", f"{script.stem}{'_' + key if key else ''}_face{fid}.png"),
                           f"{script.stem}: face {fid} (red)")
        print(f"-> {img}")
    return 0


def cmd_edges(args) -> int:
    """The edges of a part with their ids, for a fillet or chamfer; --highlight draws chosen ones
    and prints a selector for them."""
    from . import edges as ed, templates as tp
    from .project import dims, load, printables, resolve_part

    root, parts_dir = workspace(args.root)
    script = resolve_part(args.part, root, parts_dir)
    mod = load(script)
    key = _one_variant(mod, args.variant)
    pname, part = tp.pick_part(printables(mod, dims(mod, key)), args.only)
    near = [float(x) for x in args.near.split(",")] if args.near else None
    if near is not None and len(near) != 3:
        sys.exit("edges: --near x,y,z in mm")
    face = int(args.face) if args.face and args.face.strip().isdigit() else args.face
    if isinstance(face, str) and "," in face:
        face = [float(x) for x in face.split(",")]
    res = ed.list_edges(part, face, args.kind, args.convexity, near, args.radius, args.limit)
    sel = ed.selector(part, args.highlight) if args.highlight else None
    if args.json:
        json.dump({**res, **({"selector": sel} if sel else {})}, sys.stdout, indent=1)
        print()
    else:
        counts = ", ".join(f"{n} {k}" for k, n in res["counts"].items())
        print(f"{script.stem}{'[' + key + ']' if key else ''} {pname}: {res['matched']} of {res['total']} edges ({counts})")
        for line in ed.text(res):
            print(line)
        if res.get("note"):
            print(f"  ({res['note']})")
    if sel:
        chosen, ids = ed.find_edges(part, args.highlight)
        img = ed.highlight(part, chosen, outdir.path(script.parent / "out", f"{script.stem}{'_' + key if key else ''}_edges{'-'.join(map(str, ids[:6]))}.png"),
                           f"{script.stem}: edges {ed.id_text(ids)} (red)")
        if not args.json:
            print(f"selector: {sel['expr']}" + (f"\n  {sel['import']}" if sel.get("import") else "")
                  + f"\n  ({sel['note']})")
        print(f"-> {img}")
    return 0


def cmd_view(args) -> int:
    """A self-contained HTML 3D view of a part (viewer and model inline: opens from file://, offline)."""
    from . import viewer
    from .project import Pieces, dims, load, resolve_part

    root, parts_dir = workspace(args.root)
    script = resolve_part(args.part, root, parts_dir)
    mod = load(script)
    key = _one_variant(mod, args.variant)
    layout = "assembly" if args.assembly else "print"
    try:
        glb = viewer.write_view(Pieces(mod, dims(mod, key)), "_".join(x for x in (script.stem, key) if x),
                                script.parent / "out", layout, args.only)
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
    from . import checks as ck, templates as tp
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


def cmd_diagnose(args) -> int:
    """diagnose_failure on the command line: each piece built on its own, with its diagnosis."""
    import warnings

    from . import diagnose
    from .project import resolve_part, variant_key

    root, parts_dir = workspace(args.root)
    script = resolve_part(args.part, root, parts_dir)
    with warnings.catch_warnings(record=True) as warned:
        warnings.simplefilter("always")
        try:
            res = diagnose.deep(script, variant_key(args.variant), args.only, None, warned)
        except KeyError as e:
            sys.exit(f"diagnose: {e.args[0]}")
    if args.json:
        json.dump(res, sys.stdout, indent=1, default=str)
        print()
    else:
        print(diagnose.deep_text(res, script.stem))
    bad = res.get("error") or res.get("assembly_error") or any(
        not p["ok"] or p.get("problems") for p in res.get("pieces", {}).values())
    return 1 if bad else 0


def cmd_bom(args) -> int:
    """The shopping list of the declared hardware (hardware(d)), merged across the parts given."""
    from . import hardware
    from .project import dims, load, variant_key, variants

    entries = []
    for script in _targets(args):
        try:
            mod = load(script)
            keys = list(variants(mod))
            key = variant_key(args.variant) if args.variant else keys[0]
            if key not in keys:
                raise KeyError(f"no variant {args.variant!r}; variants: {[k or 'standard' for k in keys]}")
            items = hardware.declared(mod, dims(mod, key))
        except Exception as e:  # noqa: BLE001 - one unreadable part is reported in the list, not a crash
            if args.parts:
                sys.exit(f"bom: {script.stem}: {e}")
            entries.append({"part": script.stem, "error": str(e).strip('"')})
            continue
        entries.append({"part": script.stem, "variant": key or "standard", "variants": [k or "standard" for k in keys],
                        "declared": items is not None, "items": [item.record() for item in items or []]})
    sys.stdout.write(hardware.shopping_list(entries, args.count, "csv" if args.csv else "table"))
    return 0


def cmd_params(args) -> int:
    """The Dims fields of a part (read from the script, not run)."""
    from .params import read
    from .partfiles import resolve_part

    root, parts_dir = workspace(args.root)
    script = resolve_part(args.part, root, parts_dir)
    info = read(script.read_text(encoding="utf-8"))
    if args.json:
        json.dump(info, sys.stdout, indent=1, ensure_ascii=False)
        print()
        return 0
    print(f"{script.stem}: Dims (line {info['class_line']})")
    for f in info["fields"]:
        val = f["default"] if f["literal"] else f"{f['default']}  (expression)"
        print(f"  {f['name']:16} {f['type']:10} = {val}" + (f"  # {f['comment']}" if f.get("comment") else ""))
    for d in info["derived"]:
        print(f"  {d['name']:16} derived from {', '.join(d['uses']) or '?'}" + (f"  ({d['doc']})" if d.get("doc") else ""))
    for k, ov in info.get("variants", {}).items():
        if ov:
            print(f"  variant {k}: " + ", ".join(f"{n}={v}" for n, v in ov.items()))
    return 0


def _value(text: str):
    """A FIELD=VALUE value: a Python literal (40, 2.5, True, (1, 2), "x"), else the text itself."""
    import ast

    try:
        return ast.literal_eval(text)
    except (ValueError, SyntaxError):
        return text


def cmd_set(args) -> int:
    """set_params on the command line: change Dims defaults (or a variant's overrides) in place."""
    from .params import set_values
    from .project import dims, load, printables, resolve_part, variant_key, variants
    from .render import report

    root, parts_dir = workspace(args.root)
    script = resolve_part(args.part, root, parts_dir)
    values = {}
    for pair in args.values:
        name, eq, val = pair.partition("=")
        if not eq or not name.strip():
            sys.exit(f"set: {pair!r}: give FIELD=VALUE")
        values[name.strip()] = _value(val.strip())

    def sizes() -> dict | None:
        if args.no_build:
            return None
        mod = load(script)
        keys = list(variants(mod))
        k = variant_key(args.variant) if args.variant else keys[0]
        try:
            return {n or "part": report(p) for n, p in printables(mod, dims(mod, k)).items()}
        except Exception as e:  # noqa: BLE001 - say it, the edit still happens
            return {"error": f"{type(e).__name__}: {e}"}

    src = script.read_bytes().decode("utf-8")
    new, changes, notes = set_values(src, values, args.variant)
    before = sizes()
    script.write_text(new, encoding="utf-8", newline="")
    for c in changes:
        where = f"VARIANTS[{c['variant']!r}]" if c.get("variant") else "Dims"
        print(f"{c['field']} ({where}, line {c['line']}): {c['old'] if c['old'] is not None else '(not set)'} -> {c['new']}")
    for n in notes:
        print(f"note: {n}")
    after = sizes()
    if after is None:
        return 0
    if "error" in after:
        print(f"build FAILED: {after['error']} (the change is saved; run `b123d-print diagnose {script.stem}`)")
        return 1
    for pname, r in after.items():
        o = (before or {}).get(pname) if before and "error" not in before else None
        was = f"{o['x']:.2f} x {o['y']:.2f} x {o['z']:.2f} -> " if o else ""
        vol = f"{o['volume']:.1f} -> {r['volume']:.1f}" if o else f"{r['volume']:.1f}"
        print(f"  {pname}: {was}{r['x']:.2f} x {r['y']:.2f} x {r['z']:.2f} mm, volume {vol} mm^3, valid={r['valid']}")
        for pr in diagnose_problems(pname, r):
            print(f"  PROBLEM: {pr}")
    return 0


def diagnose_problems(name: str, rep: dict) -> list[str]:
    """Problems readable from a report alone (the CLI has the report, not the shape)."""
    out = []
    if not rep["valid"]:
        out.append(f"{name} is not a valid solid: b123d-print diagnose shows which faces are bad")
    if rep["volume"] <= 0:
        out.append(f"{name} has zero volume")
    elif abs(rep["min"][2]) > 1e-3:
        out.append(f"{name}'s bottom is at Z={rep['min'][2]:g}, not on the bed (Z=0)")
    return out


def cmd_measure(args) -> int:
    """measure on the command line: a gap, a wall, two faces or a hole, in mm with the points."""
    from . import measure as ms
    from .project import Pieces, dims, load, resolve_part

    root, parts_dir = workspace(args.root)
    script = resolve_part(args.part, root, parts_dir)
    q: dict = {"frame": args.frame, "a": args.of, "image": args.image}
    if args.distance:
        a, _, b = args.distance.partition(",")
        q.update(kind="distance", a=a.strip(), b=b.strip())
    elif args.wall:
        q.update(kind="wall", at=_triple(args.wall, "--wall"))
    elif args.faces:
        f1, _, f2 = args.faces.partition(",")
        q.update(kind="faces", face=int(f1) if f1.strip().isdigit() else f1.strip(),
                 face2=int(f2) if f2.strip().isdigit() else f2.strip())
    else:
        h = args.hole
        q.update(kind="hole", face=None if h in (None, "") else (int(h) if h.isdigit() else h))
    if args.at:
        q["at"] = _triple(args.at, "--at")
    if args.dir:
        q["direction"] = _triple(args.dir, "--dir")
    mod = load(script)
    key = _one_variant(mod, args.variant)
    out = script.parent / "out"
    if args.image:
        out.mkdir(exist_ok=True)
    tag = "_".join(x for x in (script.stem, key) if x)
    try:
        res = ms.run(Pieces(mod, dims(mod, key)), {k: v for k, v in q.items() if v is not None}, load_settings(script),
                     out, tag)
    except (ms.MeasureError, KeyError) as e:
        sys.exit(f"measure: {e.args[0] if isinstance(e, KeyError) else e}")
    except Exception as e:  # noqa: BLE001 - the part does not build: say why, as build_part would
        from . import diagnose

        print(f"measure: the part failed to build: {type(e).__name__}: {e}")
        print(diagnose.text(diagnose.from_exception(e, script), script.stem))
        return 1
    if args.json:
        json.dump(res, sys.stdout, indent=1)
        print()
    else:
        print(res["summary"])
        if res.get("image"):
            print(f"-> {res['image']}")
    return 0


def cmd_printer(args) -> int:
    from . import profiles as pf
    from .config import printer_nicknames, set_user_setting
    from .setup import hole_note

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
        if not args.name and s.nickname:
            print(f"{s.nickname} (nickname; calibration is kept under it)")
        print(pf.load_printer(printer_nicknames().get(name, name) if args.name else s.printer).summary())
        if not args.name and s.material:
            print(pf.load_material(s.material).summary())
        return 0
    if args.pcmd == "use":
        if args.name in ("generic", "none", ""):
            set_user_setting("printer", None)
            path = set_user_setting("material", None)
            print(f"generic mode ({path})")
            return 0
        name = args.name
        if args.nickname:
            pf.save_nickname(args.nickname, name)
            name = args.nickname
        pr = pf.load_printer(printer_nicknames().get(name, name))  # raises with suggestions if unknown
        path = set_user_setting("printer", name)
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
        ws = None
        if getattr(args, "workspace", False):
            if s.root is None:
                sys.exit("--workspace: no b123d-print.toml here or above (b123d-print init makes one)")
            ws = s.root / WORKSPACE_FILE
        where = pf.save_calibration(s.calibration_key, s.material, key, args.value, ws)
        print(f"{key} {args.value:g} for {s.calibration_key}/{s.material or 'any'} -> {where}")
        if key.startswith("hole_comp"):
            s = load_settings()
            print(hole_note(s))
        return 0
    return 1


def _ask(question: str, default: str = "") -> str:
    try:
        a = input(f"{question}{f' [{default}]' if default else ''}: ").strip()
    except EOFError:
        a = ""
    return a or default


def _pick_printer(words: str) -> str:
    """A printer name from search words: the exact name, the only match, or one picked from a list."""
    from . import profiles as pf

    if words in pf.available("printers"):
        return words
    hits = pf.search("printers", words)
    if len(hits) == 1:
        return hits[0]
    if not hits:
        print(f"  no printer matches {words!r}")
        return _pick_printer(_ask("Printer (words to search, blank for generic)")) if sys.stdin.isatty() else ""
    for i, h in enumerate(hits[:20], 1):
        print(f"  {i:2}. {h}")
    if len(hits) > 20:
        print(f"  ... {len(hits) - 20} more; add words to narrow it")
    a = _ask("Number or more words (blank for generic)")
    if a.isdigit() and 1 <= int(a) <= min(20, len(hits)):
        return hits[int(a) - 1]
    return _pick_printer(f"{words} {a}") if a else ""


def cmd_setup(args) -> int:
    from . import setup as st

    root, _ = workspace(args.root)
    if args.workspace:
        init_workspace(root)
        path = root / WORKSPACE_FILE
    else:
        path = user_config_path()
    s = load_settings(root)
    given = {"printer": args.printer, "material": args.material, "formats": args.formats, "style": args.style,
             "hole_comp": args.hole_comp, "hole_comp_h": args.hole_comp_h}
    ask = not args.no_input and sys.stdin.isatty()
    if ask:
        print(f"b123d-print setup: answers go to {path}. Press Enter to keep the value in brackets.")
        if args.printer is None:
            words = _ask("Printer (words to search, e.g. 'bambu a1'; blank for generic)", s.printer)
            given["printer"] = _pick_printer(words) if words else ""
        elif args.printer:
            given["printer"] = _pick_printer(args.printer)
        if args.material is None:
            given["material"] = _ask("Material (pla, petg, asa, abs, tpu or your own)", s.material or "pla")
        if args.formats is None:
            given["formats"] = _ask("Export formats (3mf for Bambu/Orca/Prusa, step to edit in other CAD, png, stl, glb, print, hardware)",
                                    ",".join(s.formats))
        if args.style is None:
            given["style"] = _ask("Default style (functional, modern, least_cost, rugged, soft, structural, organic)", s.style or "functional")
        if args.hole_comp is None:
            given["hole_comp"] = _ask("Measured hole compensation in mm (blank if not measured yet)")
    elif args.printer and args.printer not in ("generic", "none"):
        from .profiles import available, search

        hits = search("printers", args.printer)
        if args.printer not in available("printers") and len(hits) == 1:  # search words with one match
            given["printer"] = hits[0]
    try:
        changes = st.plan(given, path, args.overwrite)
    except (KeyError, ValueError) as e:
        sys.exit(f"setup: {str(e).strip(chr(34))}")
    conflicts = [c for c in changes if c.conflict]
    overwrite = args.overwrite
    if conflicts and not overwrite and ask:
        for c in conflicts:
            print(f"  {c.key} is {c.old} in {c.where}; the new answer is {c.new}")
        overwrite = _ask("Replace these? (y/N)", "n").lower().startswith("y")
        if overwrite:
            changes = st.plan(given, path, True)
    written = st.apply(changes, overwrite)
    print(st.report(changes, written) or "  nothing to write")
    if any(c.conflict for c in changes) and not overwrite:
        print("Existing values were kept; run again with --overwrite to replace them.")
    s = load_settings(root)
    print(st.hole_note(s))
    print(st.next_steps(hole_comp_source(root) is not None))
    if ask and (root / WORKSPACE_FILE).is_file():
        _offer_git(root, False, False)
    return 0


def _offer_git(root: Path, yes: bool, no: bool) -> int:
    """init and setup: ask whether to keep a version history (git) of the project; nothing without a yes."""
    from . import versions

    if no or versions.is_repo(root):
        return 0
    if not versions.git_path():
        if yes:
            sys.exit(f"init: {versions.NO_GIT}")
        return 0
    if not yes:
        if not sys.stdin.isatty():
            print("Version history: `b123d-print init --git` makes this folder a git repository, so `b123d-print save` "
                  "can keep versions of your parts.")
            return 0
        print("Version history: keep versions of your parts (script, ref/, settings) so you can go back to one later. "
              "It makes this folder a git repository on this machine; out/, downloaded zips and tokens are left out, "
              "and nothing is sent anywhere.")
        if not _ask("Start a version history here? (y/N)", "n").lower().startswith("y"):
            print("  not started; `b123d-print init --git` starts it later")
            return 0
    try:
        print(versions.start(root))
    except versions.VersionError as e:
        sys.exit(f"init: {e}")
    return 0


def cmd_versions(args) -> int:
    from . import versions

    root, _ = workspace(args.root)
    try:
        if args.cmd == "save":
            print(versions.save(root, args.message, args.part))
        elif args.cmd == "versions":
            print(versions.history(root, args.part, args.limit))
        else:
            print(versions.restore(root, args.part, args.version))
    except versions.VersionError as e:
        sys.exit(f"{args.cmd}: {e}")
    return 0


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
    g = p.add_mutually_exclusive_group()
    g.add_argument("--git", action="store_true", help="also keep a version history: make the folder a git repo "
                                                     "with a .gitignore (asked when run in a terminal)")
    g.add_argument("--no-git", action="store_true", help="never ask about version history")
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
            p.add_argument("--only", metavar="PIECES", help="comma-separated piece names from build(): build and export only "
                                                             "those (lazy pieces: the others are never built)")
        if name == "check":
            p.add_argument("--json", action="store_true")
            p.add_argument("-v", "--verbose", action="store_true", help="also list passing checks")
    p = sub.add_parser("metrics", help="design metrics and the style's suggestions (filament, time, edges, ...)")
    p.add_argument("parts", nargs="*", help="part names or script paths (default: all)")
    p.add_argument("--variant")
    p.add_argument("--style", help="override the part's STYLE: functional, modern, least_cost, rugged, soft, structural, organic")
    p.add_argument("--up", help="the side that points up in use, for water traps: +X, -Y, ... (default: UP, else +Z)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("orient", help="rank the ways to put each part on the bed (supports, contact, time, tip-over, load)")
    p.add_argument("parts", nargs="*", help="part names or script paths (default: all)")
    p.add_argument("--variant")
    p.add_argument("--piece", help="only this printable part of a script that builds several")
    p.add_argument("--load", help="the bending or tension direction as build(d) returns the part: X, 'along Y', XZ, 1,0,1")
    p.add_argument("--image", action="store_true", help="also render the top choice to out/images/<part>_orient.png")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("fit", help="fit between the pieces of assembly(d): overlaps, gaps under the clearance, hole alignment")
    p.add_argument("parts", nargs="*", help="part names or script paths (default: all with an assembly)")
    p.add_argument("--variant")
    p.add_argument("--hole-tol", type=float, help="largest axis offset of partner holes, mm (default 0.2)")
    p.add_argument("--json", action="store_true")
    p.add_argument("-v", "--verbose", action="store_true", help="also list the pairs that fit")
    p = sub.add_parser("trace", help="trace a flat object in a scan or photo into an outline in mm (JSON, py snippet, overlay PNG)")
    p.add_argument("image", help="a PNG, JPEG, TIFF or BMP")
    p.add_argument("--dpi", type=float, help="scan resolution (default: read from the file)")
    p.add_argument("--grid", type=float, metavar="MM", help="grid cell size in mm (a cutting mat, graph paper)")
    p.add_argument("--reference", metavar="card|L,S", help="a reference object beside it: card (85.60 x 53.98) or its sides in mm")
    p.add_argument("--points", metavar="X1,Y1,X2,Y2", help="two pixels (origin top left) a known --distance apart")
    p.add_argument("--distance", type=float, metavar="MM", help="mm between --points")
    p.add_argument("--tolerance", type=float, default=0.2, help="mm the simplified outline may deviate (default 0.2)")
    p.add_argument("--smooth", action="store_true", help="spline through-points instead of a polyline")
    p.add_argument("--pick", metavar="X,Y", help="a pixel inside the object to trace (default: the largest object)")
    p.add_argument("--threshold", type=float, help="gray level 0..1 (default: automatic)")
    p.add_argument("--invert", action="store_true", help="the object is lighter than the background")
    p.add_argument("-o", "--out", help="folder for the outputs (default: next to the image)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("recipes", help="list the recipe library, or show one recipe's code, notes and sources")
    p.add_argument("name", nargs="?")
    p = sub.add_parser("faces", help="list a part's flat faces with their ids (for a face template)")
    p.add_argument("part", help="part name or script path")
    p.add_argument("--variant")
    p.add_argument("--part", dest="only", metavar="NAME", help="which printable part (default: the only one)")
    p.add_argument("--highlight", metavar="ID", help="also draw the part with this face (id or side) in red")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("edges", help="list a part's edges with their ids, convexity and faces (for a fillet or chamfer)")
    p.add_argument("part", help="part name or script path")
    p.add_argument("--variant")
    p.add_argument("--part", dest="only", metavar="NAME", help="which printable part (default: the only one)")
    p.add_argument("--face", metavar="ID", help="only the edges of this face: an id or side from `faces`, or x,y,z on it")
    p.add_argument("--kind", help="only this type: line, circle, arc, ellipse, spline")
    p.add_argument("--convexity", help="only convex (outside), concave (inside corners), tangent or seam edges")
    p.add_argument("--near", metavar="X,Y,Z", help="only edges within --radius mm of this point, nearest first")
    p.add_argument("--radius", type=float, default=1.0, help="mm for --near (default 1)")
    p.add_argument("--limit", type=int, default=200, help="list at most this many (default 200)")
    p.add_argument("--highlight", metavar="IDS", help="draw these edges (3,4,7 or 3-6) in red and print a selector for them")
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
    p = sub.add_parser("diagnose", help="a failed or broken build: each piece built on its own, with the likely cause "
                                        "and fixes; exit 1 if a piece fails or has a problem")
    p.add_argument("part", help="part name or script path")
    p.add_argument("--variant", help="default: the first variant")
    p.add_argument("--only", metavar="PIECES", help="comma-separated piece names: only those")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("bom", help="what to buy: the hardware the parts declare (hardware(d)) as one merged table, or CSV")
    p.add_argument("parts", nargs="*", help="part names or script paths (default: all, merged into one list)")
    p.add_argument("--variant")
    p.add_argument("--count", type=int, default=1, help="how many assemblies: multiplies every quantity (default 1)")
    p.add_argument("--csv", action="store_true", help="CSV instead of the Markdown table (for a spreadsheet or cart)")
    p = sub.add_parser("params", help="list a part's Dims fields (type, value, source comment) and variant overrides")
    p.add_argument("part", help="part name or script path")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("set", help="change Dims values in the script in place (FIELD=VALUE ...), then build and show "
                                   "what changed")
    p.add_argument("part", help="part name or script path")
    p.add_argument("values", nargs="+", metavar="FIELD=VALUE", help="e.g. WIDTH=42 R=1.9 (Python literals)")
    p.add_argument("--variant", help="change this variant's override in VARIANTS instead of the default")
    p.add_argument("--no-build", action="store_true", help="only edit the script")
    p = sub.add_parser("measure", help="measure a built part in mm: a gap or interference, a wall, two faces, a hole")
    p.add_argument("part", help="part name or script path")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--distance", metavar="A,B", help="gap (or interference) between two pieces or assembly labels")
    g.add_argument("--wall", metavar="X,Y,Z", help="wall thickness at a point (into the part, or along --dir)")
    g.add_argument("--faces", metavar="ID,ID", help="distance or angle between two flat faces (ids or sides from `faces`)")
    g.add_argument("--hole", nargs="?", const="", metavar="FACE", help="holes in a flat face (id or side), or the hole "
                                                                        "nearest --at")
    p.add_argument("--of", metavar="NAME", help="the piece (or assembly label) for --wall, --faces, --hole")
    p.add_argument("--at", metavar="X,Y,Z", help="a point at the hole (--hole)")
    p.add_argument("--dir", metavar="DX,DY,DZ", help="the direction for --wall")
    p.add_argument("--frame", default="auto", choices=("auto", "print", "assembly"),
                   help="print (as build() returns it) or assembly (as assembly(d) places it); default auto")
    p.add_argument("--variant", help="default: the first variant")
    p.add_argument("--image", action="store_true", help="also draw the part with what was measured in red (out/images/)")
    p.add_argument("--json", action="store_true")
    p = sub.add_parser("styles", help="list the design styles (yours and the built-in ones), or show one")
    p.add_argument("name", nargs="?", help="a style to show, with based_on applied")
    p = sub.add_parser("printer", help="optional printer/material profile (default: generic)")
    psub = p.add_subparsers(dest="pcmd", required=True)
    q = psub.add_parser("list", help="search the printer profiles (from OrcaSlicer's library + yours)")
    q.add_argument("query", nargs="*")
    q = psub.add_parser("show", help="show a printer (default: the active one)")
    q.add_argument("name", nargs="?")
    q = psub.add_parser("use", help="set the active printer in your user config; 'generic' clears it")
    q.add_argument("name", help="a printer profile, or a nickname given before")
    q.add_argument("--material", help="pla, petg, asa, abs, tpu or your own")
    q.add_argument("--nickname", help="name this printer (e.g. p2s-garage): two of the same model each keep their own calibration")
    q = psub.add_parser("hole-comp", help="store a measured hole compensation for the active printer + material")
    q.add_argument("value", type=float)
    q = psub.add_parser("calibrate", help="store a value measured with a calibration coupon for the active printer + material")
    q.add_argument("key", choices=CALIBRATED)
    q.add_argument("value", type=float)
    q.add_argument("--workspace", action="store_true",
                   help="store it in this workspace's b123d-print.toml instead of calibration.toml")
    p = sub.add_parser("setup", help="first-run setup: printer, material, export formats, default style, hole compensation "
                                     "(asks, or takes flags); never replaces a value without --overwrite or a yes")
    p.add_argument("--printer", help="a printer profile name or search words ('generic' for none)")
    p.add_argument("--material", help="pla, petg, asa, abs, tpu or your own")
    p.add_argument("--formats", help=f"comma-separated, from {','.join(FORMATS)} or all")
    p.add_argument("--style", help="functional, modern, least_cost, rugged, soft, structural, organic or your own")
    p.add_argument("--hole-comp", help="measured hole compensation, mm (with a printer: stored for it and the material)")
    p.add_argument("--hole-comp-h", help="the same for horizontal holes")
    p.add_argument("--workspace", action="store_true", help="write to this workspace's b123d-print.toml (default: your user config)")
    p.add_argument("--overwrite", action="store_true", help="replace values already set there")
    p.add_argument("--no-input", action="store_true", help="never ask: write only the flags given (default when stdin is not a terminal)")
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
    p.add_argument("--timeout", type=float, help="seconds per build (default 240)")
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
    p = sub.add_parser("save", help="save a version of the parts (script, ref/, MEASURE.md) and b123d-print.toml "
                                    "in the project's version history (git)")
    p.add_argument("message", nargs="?", default="", help="what changed, in a few words (default: the changed values)")
    p.add_argument("--part", help="only this part (default: every part)")
    p = sub.add_parser("versions", help="list the saved versions, newest first, with what changed")
    p.add_argument("part", nargs="?", help="number this part's versions, for restore (default: every part)")
    p.add_argument("--limit", type=int, default=20, help="show at most this many (default 20)")
    p = sub.add_parser("restore", help="bring a part back to a saved version, as a new version (nothing is lost)")
    p.add_argument("part")
    p.add_argument("version", help="a number from `b123d-print versions <part>`, or a commit id")
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
        return _offer_git(Path(args.dir).resolve(), args.git, args.no_git)
    if args.cmd in ("save", "versions", "restore"):
        return cmd_versions(args)
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
    if args.cmd == "setup":
        return cmd_setup(args)
    if args.cmd in ("setup-ssh", "ssh-serve", "pull", "push"):
        return cmd_ssh(args)
    if args.cmd == "examples":
        print("\n".join(examples()))
        return 0
    if args.cmd == "list":
        from .partfiles import find_parts

        root, parts_dir = workspace(args.root)
        for p in find_parts(root, parts_dir):
            print(p.relative_to(root))
        return 0
    if args.cmd in ("metrics", "orient", "styles"):
        try:
            return {"metrics": cmd_metrics, "orient": cmd_orient, "styles": cmd_styles}[args.cmd](args)
        except ValueError as e:
            sys.exit(str(e))
    if args.cmd == "bom":
        try:
            return cmd_bom(args)
        except ValueError as e:
            sys.exit(f"bom: {e}")
    if args.cmd in ("diagnose", "params", "set", "measure"):
        from .params import ParamError
        from .templates import TemplateError

        try:
            return {"diagnose": cmd_diagnose, "params": cmd_params, "set": cmd_set, "measure": cmd_measure}[args.cmd](args)
        except (ParamError, TemplateError, FileNotFoundError) as e:
            sys.exit(f"{args.cmd}: {e}")
    if args.cmd in ("faces", "edges", "template"):
        from .templates import TemplateError

        try:
            return {"faces": cmd_faces, "edges": cmd_edges, "template": cmd_template}[args.cmd](args)
        except (TemplateError, FileNotFoundError) as e:
            sys.exit(f"{args.cmd}: {e}")
    return {"build": cmd_build, "check": cmd_check, "compare": cmd_compare, "to-step": cmd_to_step, "fit": cmd_fit,
            "trace": cmd_trace, "recipes": cmd_recipes, "view": cmd_view}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
