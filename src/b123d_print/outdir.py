"""The layout of a part's out/ folder (#124): one subfolder per purpose, so the file for the
slicer is easy to find.

    out/
      print/            3MF, STL and <name>_print.md: what you open in the slicer
      print/templates/  the 3MF and STL of fit-test templates (small test prints)
      cad/              STEP and GLB: to open in other CAD or a 3D app
      images/           previews, sections, before/after, compare, traces
      docs/             BOM (.md, .csv), hardware JSON, the 3D view HTML, outlines
      README.md         a short index: what is where, which file to slice
      .cache/           the build cache (never downloaded)

A file's folder follows from its name (folder()); only templates are told by the writer. Before
0.3.11 everything sat directly in out/: tidy() moves such old flat files into their folders, so
a part never has both layouts. files() lists both, so an old flat part still downloads.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

PRINT, CAD, IMAGES, DOCS = "print", "cad", "images", "docs"
TEMPLATES = "print/templates"
FOLDERS = (PRINT, TEMPLATES, CAD, IMAGES, DOCS)  # every folder below out/ that holds files
README = "README.md"

_PRINT = (".3mf", ".stl", "_print.md")
_CAD = (".step", ".stp", ".glb")
_IMAGES = (".png", ".jpg", ".jpeg", ".svg")


def folder(filename: str, template: bool = False) -> str:
    """The folder below out/ for a file of this name ("print", "print/templates", "cad", ...)."""
    n = filename.lower()
    if n.endswith(_PRINT):
        return TEMPLATES if template and not n.endswith("_print.md") else PRINT
    if n.endswith(_CAD):
        return CAD
    if n.endswith(_IMAGES):
        return IMAGES
    return DOCS


def path(out: str | Path, filename: str, template: bool = False) -> Path:
    """out/<folder>/<filename>, its folder made."""
    d = Path(out) / folder(filename, template)
    d.mkdir(parents=True, exist_ok=True)
    return d / filename


def out_of(file: str | Path) -> Path | None:
    """The out/ folder `file` is in (directly, the old flat layout, or in one of FOLDERS), else None."""
    parent = Path(file).parent
    if parent.name == "out":
        return parent
    for f in FOLDERS:
        depth = f.count("/") + 1
        if depth <= len(parent.parents):
            top = parent.parents[depth - 1]
            if top.name == "out" and parent.relative_to(top).as_posix() == f:
                return top
    return None


def _dir(p: Path) -> bool:
    try:
        return stat.S_ISDIR(os.lstat(p).st_mode)  # a symlink is not a folder here
    except OSError:
        return False


def _plain(d: Path) -> list[Path]:
    """Regular, non-hidden files directly in folder `d` (no symlinks, nothing below)."""
    if not _dir(d):
        return []
    found = []
    for p in sorted(d.iterdir()):
        if p.name.startswith(".") or p.suffix == ".pyc":
            continue
        try:
            if stat.S_ISREG(os.lstat(p).st_mode):
                found.append(p)
        except OSError:
            continue
    return found


def files(out: str | Path) -> list[tuple[str, Path]]:
    """(path relative to out/, file) for every file in out/: README.md and old flat files directly
    in it, then each folder of FOLDERS. Never follows a symlink, never lists a hidden file or
    anything in another folder (.cache/ included)."""
    out = Path(out)
    if not _dir(out):
        return []
    found = [(p.name, p) for p in _plain(out)]
    for f in FOLDERS:
        if all(_dir(out.joinpath(*f.split("/")[:i + 1])) for i in range(f.count("/") + 1)):
            found += [(f"{f}/{p.name}", p) for p in _plain(out / f)]
    return found


def tidy(out: str | Path) -> list[str]:
    """Move old flat files (out/<file>, the layout before 0.3.11) into their folders, so a part
    never has both layouts. A file of the same name already in its folder is newer: the flat one
    is removed. Returns the names moved or removed."""
    out = Path(out)
    done = []
    for p in _plain(out):
        if p.name == README:
            continue
        dest = path(out, p.name, template="_template_" in p.name)
        try:
            if os.path.lexists(dest):
                p.unlink()
            else:
                os.replace(p, dest)
        except OSError:
            continue
        done.append(p.name)
    return done


def readme(out: str | Path, part: str) -> Path:
    """Write out/README.md: what each folder holds and which files to slice. Written only when
    its text changed, so an export of nothing new leaves it alone."""
    out = Path(out)
    listed = files(out)
    to_slice = [rel for rel, p in listed if rel.startswith(PRINT + "/") and "/templates/" not in rel
                and p.suffix.lower() == ".3mf"]
    if not to_slice:
        to_slice = [rel for rel, p in listed if rel.startswith(PRINT + "/") and "/templates/" not in rel
                    and p.suffix.lower() == ".stl"]
    tests = [rel for rel, p in listed if rel.startswith(TEMPLATES + "/") and p.suffix.lower() in (".3mf", ".stl")]
    lines = [f"# {part}: exported files", "",
             f"Made by `b123d-print` from `../{part}.py`. One export makes all of this again, so these files",
             "do not need a backup: keep the script, `ref/` and `b123d-print.toml`.", "",
             "| Folder | What is in it |", "|---|---|",
             "| `print/` | 3MF and STL files for the slicer, and the print sheet (`_print.md`) |",
             "| `print/templates/` | fit-test templates: small, quick test prints of one feature |",
             "| `cad/` | STEP (opens in other CAD: Onshape, Fusion, FreeCAD) and GLB (3D apps) |",
             "| `images/` | previews, section cuts, before/after and compare pictures |",
             "| `docs/` | shopping list (`_bom.md`, `_bom.csv`), hardware JSON, the 3D view (`_view.html`) |",
             ""]
    if to_slice:
        lines += ["## Open in the slicer", ""] + [f"- `{rel}`" for rel in to_slice] + [""]
    if tests:
        lines += ["## Test prints", ""] + [f"- `{rel}`" for rel in tests] + [""]
    text = "\n".join(lines)
    f = out / README
    try:
        if not os.path.islink(f) and f.read_text(encoding="utf-8") == text:
            return f
    except OSError:
        pass
    if os.path.islink(f):
        f.unlink()
    f.write_text(text, encoding="utf-8", newline="\n")
    return f
