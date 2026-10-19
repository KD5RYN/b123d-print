"""Reference files: the original model a remix starts from (an STL, 3MF or STEP someone downloaded),
or a scan or photo of a flat object to trace (PNG, JPEG, TIFF, BMP).

They live in the part's own folder, `<parts_dir>/<part>/ref/<file>`, so a part script reads them
with `import_model("ref/bracket.stl")` and the sandbox (which can read the workspace) lets it.
A workspace-wide `refs/` folder also works for files several parts share. This module is the one
place that writes them, for every transport:

    stdio   the client copies the file into the workspace itself (it is a local folder)
    SSH     `b123d-print push <file> --part <name> --to user@host` (ssh-serve's `push`)
    HTTP    the `upload_reference` tool: the file as base64, or a signed PUT link for curl

Writes are refused outside <parts_dir>/<part>/ref/, through symlinks, for names that are not plain
file names, for other suffixes, over MAX_BYTES, and for content that is not what its suffix says.
"""

from __future__ import annotations

import os
import re
import secrets
import stat
from pathlib import Path

MODEL_SUFFIXES = (".stl", ".3mf", ".step", ".stp")
IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp")  # scans and photos to trace (= trace.IMAGE_SUFFIXES)
SUFFIXES = MODEL_SUFFIXES + IMAGE_SUFFIXES
MAX_BYTES = 50_000_000  # per file; a 100k-triangle binary STL is 5 MB
REF_DIR = "ref"
SHARED_DIR = "refs"  # workspace-wide reference folder (read only by import_model; nothing writes it)
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ ()+-]{0,119}$")
PART_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")  # = cli.NAME_RE


class RefError(ValueError):
    pass


def check_name(filename: str) -> str:
    """A plain file name with an allowed suffix; else RefError."""
    if not isinstance(filename, str) or not FILE_RE.match(filename) or ".." in filename or filename.endswith((".", " ")):
        raise RefError(f"bad file name {filename!r}: letters, digits, space and ._()+- only, no folders, "
                       "not starting with a dot, up to 120 characters")
    if Path(filename).suffix.lower() not in SUFFIXES:
        raise RefError(f"{filename!r}: reference files must be {', '.join(SUFFIXES)}")
    return filename


def sniff(data: bytes, filename: str) -> None:
    """Refuse content that is not what the suffix says (a renamed script, an HTML error page)."""
    suffix = Path(filename).suffix.lower()
    head = data[:512]
    if suffix == ".stl":
        binary = len(data) >= 84 and len(data) == 84 + 50 * int.from_bytes(data[80:84], "little")
        if not binary and not head.lstrip().lower().startswith(b"solid"):
            raise RefError(f"{filename}: not an STL (neither a binary STL of the right size nor ASCII 'solid ...')")
    elif suffix == ".3mf":
        if not data.startswith(b"PK\x03\x04"):
            raise RefError(f"{filename}: not a 3MF (a 3MF is a zip file)")
    elif suffix in IMAGE_SUFFIXES:
        magic = {".png": (b"\x89PNG\r\n\x1a\n",), ".jpg": (b"\xff\xd8\xff",), ".jpeg": (b"\xff\xd8\xff",),
                 ".tif": (b"II*\x00", b"MM\x00*"), ".tiff": (b"II*\x00", b"MM\x00*"), ".bmp": (b"BM",)}[suffix]
        if not data.startswith(magic):
            raise RefError(f"{filename}: not a {suffix[1:].upper()} image")
    elif not head.lstrip().startswith(b"ISO-10303-21"):
        raise RefError(f"{filename}: not a STEP file (no ISO-10303-21 header)")


def ref_dir(ws_root: Path, parts_dir: str, part: str) -> Path:
    if not PART_RE.match(part or ""):
        raise RefError(f"bad part name {part!r}: lower_snake_case, starting with a letter")
    return ws_root / parts_dir / part / REF_DIR


def _no_symlinks(ws_root: Path, target: Path) -> None:
    """Every existing segment from ws_root down to target must be a real folder (or the file), not a link."""
    cur = ws_root
    for seg in target.relative_to(ws_root).parts:
        cur = cur / seg
        try:
            st = os.lstat(cur)
        except FileNotFoundError:
            return
        if stat.S_ISLNK(st.st_mode):
            raise RefError(f"refused: {cur.relative_to(ws_root)} is a symlink")


def store(ws_root: Path, parts_dir: str, part: str, filename: str, data: bytes, overwrite: bool = False) -> Path:
    """Write a reference file to <parts_dir>/<part>/ref/<filename> (atomically). Returns its path."""
    check_name(filename)
    if len(data) > MAX_BYTES:
        raise RefError(f"{filename}: {len(data) / 1e6:.1f} MB is over the {MAX_BYTES // 1_000_000} MB limit for reference files")
    if not data:
        raise RefError(f"{filename}: empty file")
    sniff(data, filename)
    ws_root = Path(os.path.realpath(ws_root))
    d = ref_dir(ws_root, parts_dir, part)
    target = d / filename
    _no_symlinks(ws_root, target)
    d.mkdir(parents=True, exist_ok=True)
    _no_symlinks(ws_root, target)  # again: nothing may have swapped a folder for a link meanwhile
    if os.path.lexists(target):
        if not overwrite:
            raise RefError(f"{target.relative_to(ws_root)} already exists (pass overwrite to replace it)")
        if not stat.S_ISREG(os.lstat(target).st_mode):
            raise RefError(f"refused: {target.relative_to(ws_root)} is not a regular file")
    tmp = d / f".{filename}.{secrets.token_hex(4)}.part"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.replace(tmp, target)
    except BaseException:
        if os.path.lexists(tmp):
            os.unlink(tmp)
        raise
    return target


def listing(ws_root: Path, parts_dir: str, part: str) -> list[str]:
    """The reference files of a part (names only)."""
    d = ref_dir(ws_root, parts_dir, part)
    if not d.is_dir() or d.is_symlink():
        return []
    return sorted(p.name for p in d.iterdir() if p.is_file() and not p.is_symlink() and p.suffix.lower() in SUFFIXES
                  and not p.name.startswith("."))
