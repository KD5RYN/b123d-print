"""Bringing a part home from a remote server, and cleaning up server workspaces nobody uses.

A remote server (HTTP or SSH) is a workbench, not storage: the client takes the whole part home,
in the same layout a local (stdio) install writes into the project folder:

    parts/<name>/<name>.py        the script (and any other plain file next to it)
    parts/<name>/out/...          exports, renders, sections (all, or filtered by variant / format)
    parts/<name>/ref/...          reference models for a remix

Over HTTP `download_part` returns one signed link to a zip of that (links.sign_zip); over SSH
`b123d-print pull <name>` fetches the same files as a tar (`pull --tree`). Both come from
part_files() here, which never follows a symlink and never lists a hidden file.

Retention (HTTP): a named workspace (<root>/workspaces/<name>) nobody has used for
B123D_PRINT_RETENTION_DAYS (default 30; 0 = never) is removed by a sweep at startup and every
hour. Every request touches its workspace's LAST_USE file; a workspace with a request in flight
(a build queued or running included) is never removed. The shared root workspace is never
removed, and neither is anything in SSH mode or stdio, whose folders the user chose.
"""

from __future__ import annotations

import ast
import os
import re
import secrets
import shutil
import stat
import sys
import threading
import time
import zipfile
from pathlib import Path

LAST_USE = ".b123d-print-last-use"
SUBDIRS = ("out", "ref")
MAX_BYTES = 1_000_000_000  # a zip / tar of one part; refs are capped at 50 MB each, so this is generous
STORED = (".3mf", ".png", ".zip")  # already compressed
SUFFIX = {"step": ".step", "stl": ".stl", "3mf": ".3mf", "png": ".png"}
SWEEP_EVERY = 3600.0  # seconds between retention sweeps
TRASH = ".trash-"
WORKSPACE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")  # an HTTP workspace name (?workspace=)  # a workspace being removed is renamed to workspaces/.trash-<name>-<random> first


class HandoffError(ValueError):
    pass


# ---------------------------------------------------------------------------------------------
# what goes home


def variant_keys(script: Path) -> list[str]:
    """The keys of the script's VARIANTS, read without running it (it is model-written code).
    No VARIANTS: just the standard one (""). Raises HandoffError if they are not plain strings."""
    tree = ast.parse(script.read_text(encoding="utf-8"), str(script))
    for node in tree.body:
        target = node.targets[0] if isinstance(node, ast.Assign) and len(node.targets) == 1 else (
            node.target if isinstance(node, ast.AnnAssign) else None)
        if isinstance(target, ast.Name) and target.id == "VARIANTS":
            v = node.value
            if isinstance(v, ast.Dict) and all(isinstance(k, ast.Constant) and isinstance(k.value, str) for k in v.keys):
                return [k.value for k in v.keys]
            raise HandoffError("VARIANTS is not a plain {'key': {...}} dict, so files cannot be told apart by "
                               "variant: leave variant out to get them all")
    return [""]


def _variant_of(stem: str, name: str, keys: list[str]) -> str:
    """Which variant an out/ file belongs to: <name>_<key> or <name>_<key>_...; the longest key wins."""
    best = ""
    for k in keys:
        if k and (stem == f"{name}_{k}" or stem.startswith(f"{name}_{k}_")) and len(k) > len(best):
            best = k
    return best


def _plain_files(folder: Path) -> list[Path]:
    """Regular, non-hidden files directly in `folder` (no symlinks, nothing below)."""
    try:
        st = os.lstat(folder)
    except OSError:
        return []
    if not stat.S_ISDIR(st.st_mode):
        return []
    found = []
    for p in sorted(folder.iterdir()):
        if p.name.startswith(".") or p.suffix == ".pyc":
            continue
        if stat.S_ISREG(os.lstat(p).st_mode):
            found.append(p)
    return found


def part_files(ws: Path, parts_dir: str, name: str, variant: str | None = None,
               formats: list[str] | tuple[str, ...] | None = None) -> list[tuple[str, Path]]:
    """(path relative to the part folder, file) for everything that goes home: the part folder's
    own files (the script), out/ (filtered by variant and formats) and ref/. Raises HandoffError."""
    from .links import LinkError, check_path

    try:
        check_path(f"{parts_dir}/{name}")
    except LinkError:
        raise HandoffError(f"no part {name!r}") from None
    folder = ws / parts_dir / name
    cur = ws
    for seg in Path(parts_dir).parts + (name,):  # no symlink on the way to the part folder
        cur = cur / seg
        try:
            if stat.S_ISLNK(os.lstat(cur).st_mode):
                raise HandoffError(f"no part {name!r}")
        except OSError:
            raise HandoffError(f"no part {name!r}") from None
    script = folder / f"{name}.py"
    if not script.is_file() or script.is_symlink():
        raise HandoffError(f"no part {name!r}")
    want_suffix = {SUFFIX[f] for f in formats} if formats else None
    keys = None
    if variant is not None:
        key = "" if variant in ("", "standard") else variant
        keys = variant_keys(script)
        if key not in keys:
            raise HandoffError(f"no variant {variant!r}; the variants are {[k or 'standard' for k in keys]}")
    out = [(p.name, p) for p in _plain_files(folder)]
    for p in _plain_files(folder / "out"):
        if want_suffix is not None and p.suffix.lower() not in want_suffix:
            continue
        if keys is not None and _variant_of(p.stem, name, keys) != key:
            continue
        out.append((f"out/{p.name}", p))
    out += [(f"ref/{p.name}", p) for p in _plain_files(folder / "ref")]
    if sum(p.stat().st_size for _, p in out) > MAX_BYTES:
        raise HandoffError(f"part {name!r} is over {MAX_BYTES // 1_000_000} MB: narrow it with variant= or formats=")
    return out


def write_zip(files: list[tuple[str, Path]], prefix: str, fileobj) -> None:
    """A zip of `files`, each at <prefix>/<its relative path> (prefix: 'parts/<name>')."""
    with zipfile.ZipFile(fileobj, "w") as zf:
        for rel, p in files:
            kind = zipfile.ZIP_STORED if p.suffix.lower() in STORED else zipfile.ZIP_DEFLATED
            zf.write(p, f"{prefix}/{rel}", compress_type=kind)


def zip_bytes(files: list[tuple[str, Path]], prefix: str) -> bytes:
    import io

    buf = io.BytesIO()
    write_zip(files, prefix, buf)
    return buf.getvalue()


def safe_rel(rel: str) -> bool:
    """A relative path a client may write inside the part folder: <file>, out/<file> or ref/<file>."""
    parts = rel.split("/")
    if "\\" in rel or "\0" in rel or len(parts) > 2 or (len(parts) == 2 and parts[0] not in SUBDIRS):
        return False
    return all(s and s not in (".", "..") and not s.startswith(".") and ":" not in s for s in parts)


def summary(files: list[tuple[str, Path]]) -> str:
    n_out = sum(1 for r, _ in files if r.startswith("out/"))
    n_ref = sum(1 for r, _ in files if r.startswith("ref/"))
    return f"{len(files)} file(s): the script, {n_out} in out/, {n_ref} in ref/"


# ---------------------------------------------------------------------------------------------
# retention (HTTP workspaces)


def touch(ws: Path) -> None:
    """Mark a workspace as used now (only if it exists: never create one here)."""
    try:
        if ws.is_dir() and not ws.is_symlink():
            (ws / LAST_USE).touch()
    except OSError:
        pass


def last_use(ws: Path) -> float:
    """The newest mtime in the workspace (its LAST_USE file, any file or folder in it), never following symlinks."""
    newest = os.lstat(ws).st_mtime
    for dirpath, dirnames, filenames in os.walk(ws, followlinks=False):
        for n in dirnames + filenames:
            try:
                newest = max(newest, os.lstat(os.path.join(dirpath, n)).st_mtime)
            except OSError:
                pass
    return newest


class Retention:
    """Removes named workspaces under <root>/workspaces nobody used for `days` days (0: never).
    enter()/leave() bracket every request for a workspace: one in use is never removed."""

    def __init__(self, root: Path, days: float, log=None):
        self.root, self.days = root, days
        self.busy: dict[str, int] = {}
        self.lock = threading.Lock()
        self.log = log or (lambda msg: print(f"b123d-print-mcp: {msg}", file=sys.stderr, flush=True))
        self._stop = threading.Event()

    def enter(self, name: str) -> None:
        with self.lock:
            self.busy[name] = self.busy.get(name, 0) + 1

    def leave(self, name: str) -> None:
        with self.lock:
            n = self.busy.get(name, 0) - 1
            if n > 0:
                self.busy[name] = n
            else:
                self.busy.pop(name, None)

    def sweep(self, now: float | None = None) -> list[str]:
        """Remove every workspace unused for `days`; returns their names (each is also logged)."""
        if self.days <= 0:
            return []
        now = time.time() if now is None else now
        base = self.root / "workspaces"
        removed: list[str] = []
        try:
            entries = sorted(base.iterdir())
        except OSError:
            return []
        for d in entries:
            if d.name.startswith(TRASH):  # a removal that was cut short (the server stopped)
                shutil.rmtree(d, ignore_errors=True)
                continue
            if not WORKSPACE_RE.match(d.name) or d.is_symlink() or not d.is_dir():
                continue
            try:
                age = now - last_use(d)
            except OSError:
                continue
            if age < self.days * 86400:
                continue
            trash = base / f"{TRASH}{d.name}-{secrets.token_hex(4)}"
            with self.lock:  # no request may start on it between the check and the rename
                if self.busy.get(d.name):
                    continue
                try:
                    os.rename(d, trash)
                except OSError as e:
                    self.log(f"retention: could not remove workspace {d.name}: {e}")
                    continue
            shutil.rmtree(trash, ignore_errors=True)
            removed.append(d.name)
            self.log(f"retention: removed workspace {d.name} (unused for {age / 86400:.0f} days; "
                     f"the limit is {self.days:g})")
        return removed

    def run(self, every: float = SWEEP_EVERY) -> None:
        """Sweep now and then every `every` seconds until stop()."""
        while True:
            try:
                self.sweep()
            except Exception as e:  # never let a bad moment stop the sweeps
                self.log(f"retention: sweep failed: {type(e).__name__}: {e}")
            if self._stop.wait(every):
                return

    def start(self, every: float = SWEEP_EVERY) -> threading.Thread | None:
        if self.days <= 0:
            return None
        t = threading.Thread(target=self.run, args=(every,), daemon=True, name="b123d-print-retention")
        t.start()
        return t

    def stop(self) -> None:
        self._stop.set()
