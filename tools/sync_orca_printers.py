"""Regenerate src/b123d_print/data/printers_orca.json from OrcaSlicer's printer profiles.

Only plain facts are kept per printer model (build volume, bed shape, nozzle); no OrcaSlicer
files are copied into this repository. OrcaSlicer is AGPL-3.0; see THIRD_PARTY.md.

    python tools/sync_orca_printers.py              # sparse-clones OrcaSlicer (main) into a temp dir
    python tools/sync_orca_printers.py --ref <sha>  # a specific commit
    python tools/sync_orca_printers.py --checkout /path/to/OrcaSlicer
"""

import argparse
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = "https://github.com/SoftFever/OrcaSlicer.git"
OUT = Path(__file__).resolve().parents[1] / "src/b123d_print/data/printers_orca.json"


def clone(ref: str, dest: Path) -> Path:
    subprocess.run(["git", "clone", "-q", "--filter=blob:none", "--no-checkout", REPO, str(dest)], check=True)
    run = lambda *a: subprocess.run(["git", "-C", str(dest), *a], check=True)  # noqa: E731
    run("sparse-checkout", "set", "--no-cone", "/resources/profiles/*.json", "/resources/profiles/*/machine/**/*.json")
    run("checkout", "-q", ref)
    return dest


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", default="main")
    ap.add_argument("--checkout")
    args = ap.parse_args()
    tmp = None
    if args.checkout:
        root = Path(args.checkout)
    else:
        tmp = tempfile.TemporaryDirectory()
        root = clone(args.ref, Path(tmp.name) / "orca")
    commit = subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    prof = root / "resources/profiles"

    by_name: dict[str, dict] = {}  # profile name -> json (per vendor first, global fallback)
    for f in prof.glob("*/machine/**/*.json"):
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            continue
        name = j.get("name") or f.stem
        vendor = f.relative_to(prof).parts[0]
        by_name.setdefault(f"{vendor}/{name}", j)
        by_name.setdefault(name, j)

    def resolve(j: dict, vendor: str, depth=0) -> dict:
        parent = j.get("inherits")
        if not parent or depth > 20:
            return dict(j)
        pj = by_name.get(f"{vendor}/{parent}") or by_name.get(parent)
        base = resolve(pj, vendor, depth + 1) if pj else {}
        return {**base, **j}

    printers: dict[str, dict] = {}
    for key, j in sorted(by_name.items()):
        if "/" not in key or j.get("instantiation") != "true":
            continue
        vendor = key.split("/")[0]
        r = resolve(j, vendor)
        noz = r.get("nozzle_diameter") or ["0.4"]
        try:
            nozzle = float(noz[0] if isinstance(noz, list) else noz)
        except ValueError:
            continue
        if abs(nozzle - 0.4) > 1e-6:
            continue
        model = r.get("printer_model") or j.get("name", "").replace(" 0.4 nozzle", "")
        area, height = r.get("printable_area"), r.get("printable_height")
        if not model or not area or not height:
            continue
        try:
            pts = [tuple(float(v) for v in p.split("x")) for p in area]
            h = float(height)
        except ValueError:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        bx, by = max(xs) - min(xs), max(ys) - min(ys)
        if bx <= 0 or by <= 0 or h <= 0:
            continue
        name = slug(model)
        if name in printers:
            continue
        printers[name] = {
            "label": model,
            "vendor": vendor,
            "bed_x": round(bx, 1),
            "bed_y": round(by, 1),
            "height": round(h, 1),
            "round_bed": len(pts) > 8,  # deltas: circle given as a polygon
            "nozzle": nozzle,
        }
    data = {
        "source": f"OrcaSlicer resources/profiles at {REPO.removesuffix('.git')}/tree/{commit}",
        "license_note": "Facts (build volume, nozzle) extracted from OrcaSlicer's AGPL-3.0 profiles; no files copied.",
        "commit": commit,
        "printers": dict(sorted(printers.items())),
    }
    OUT.write_text(json.dumps(data, indent=0, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{len(printers)} printer models from {commit[:12]} -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
