"""Simple version history of a workspace (#125): git underneath, three plain-language actions on top.

    save(root, message, part=None)     commit the part scripts, ref/ and b123d-print.toml
    history(root, part=None)           the saved versions, newest first, with what changed
    restore(root, part, version)       bring a part back to an earlier version, as a NEW commit
    start(root)                        make the workspace a git repo, with a .gitignore

Only the user's machine has the history: the MCP server runs these over stdio only, never on a
shared (HTTP/SSH) server; there it gives the git commands for the client's own shell.

Git runs with a fixed argument list (never a shell), with the repository's hooks and fsmonitor
switched off, signing and signature display off, and inherited GIT_* variables dropped. A
repository whose own config defines a filter (a command git would run on add or checkout) is
refused. A restore writes the old files itself (regular files only, inside the part folder) and
commits them: it never resets, rewrites history or deletes a file.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .config import WORKSPACE_FILE, load_settings

NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")  # the same as cli.NAME_RE (no import cycle)
NUMBER_RE = re.compile(r"^v?(\d{1,6})$")  # a version number from history(): 3 or v3
SHA_RE = re.compile(r"^[0-9a-f]{7,40}$")  # a commit id, at least as long as history() prints it
SHORT = 7
PLAIN = ("100644", "100755")  # git modes of regular files: the only ones saved or restored
TIMEOUT = 60.0

# Config that could run a command, overridden on every call (`-c` beats the repository's config).
SAFE_CONFIG = ("core.hooksPath=/dev/null", "core.fsmonitor=false", "commit.gpgSign=false", "tag.gpgSign=false",
               "log.showSignature=false", "core.pager=cat", "protocol.allow=never")
# Repository config that can run a command and cannot be switched off by name: refused.
UNSAFE_LOCAL = re.compile(r"^filter\.")

GITIGNORE_HEAD = "# b123d-print: made again by an export, or private (tokens and client configs)"
GITIGNORE = ("out/", "*.zip", "__pycache__/", "*.pyc", ".venv/", ".mcp.json", "opencode.json", "*.token",
             "*token*.txt", ".env", ".DS_Store")
EXTRA = ("MEASURE.md",)  # saved with the script when present (the user's measurements: AGENTS.md)


class VersionError(Exception):
    """A refusal or a failure, in words to show the user."""


@dataclass
class Repo:
    root: Path  # the workspace
    top: Path  # the git repository's top folder: the workspace or a folder above it
    prefix: str  # the workspace relative to top ("" or "projects/brackets/")
    parts_dir: str
    identity: tuple[str, ...]  # -c user.name/user.email when git has none


def git_path() -> str | None:
    return shutil.which("git")


def _env() -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env.update(GIT_TERMINAL_PROMPT="0", GIT_PAGER="cat", PAGER="cat", GIT_LITERAL_PATHSPECS="1",
               GIT_OPTIONAL_LOCKS="0", LC_ALL="C")
    return env


def run(cwd: Path, *args: str, ok: tuple[int, ...] = (0,), data: bool = False, extra: tuple[str, ...] = ()):
    """git <args> in `cwd`: a fixed argument list, no shell, the SAFE_CONFIG overrides. Returns
    stdout (str, or bytes with data=True); raises VersionError on another exit code."""
    git = git_path()
    if not git:
        raise VersionError(NO_GIT)
    cmd = [git]
    for c in SAFE_CONFIG + extra:
        cmd += ["-c", c]
    try:
        proc = subprocess.run(cmd + list(args), cwd=cwd, env=_env(), capture_output=True, timeout=TIMEOUT,
                              stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired) as e:
        raise VersionError(f"git did not run: {e}") from None
    if proc.returncode not in ok:
        err = (proc.stderr or proc.stdout).decode(errors="replace").strip()[:2000] or f"exit code {proc.returncode}"
        raise VersionError(f"git {args[0]} failed: {err}")
    return proc.stdout if data else proc.stdout.decode("utf-8", errors="replace")


NO_GIT = ("git is not installed, so there is no version history. Install it (https://git-scm.com/downloads), "
          "then run `b123d-print init --git` in the project folder.")
NOT_A_REPO = ("This project folder has no version history yet. To start one, ask the user, then run "
              "`b123d-print init --git` in the project folder (or save_version(..., start=True)). "
              "It makes the folder a git repository; nothing is sent anywhere.")


def is_repo(root: Path) -> bool:
    """True when git is installed and the workspace is inside a git repository."""
    if not git_path():
        return False
    try:
        run(root, "rev-parse", "--git-dir")
    except VersionError:
        return False
    return True


def open_repo(root: Path) -> Repo:
    """The repository the workspace is in, checked; VersionError with the reason otherwise."""
    root = root.resolve()
    if not git_path():
        raise VersionError(NO_GIT)
    try:
        out = run(root, "rev-parse", "--show-toplevel", "--show-prefix").splitlines()
    except VersionError:
        raise VersionError(NOT_A_REPO) from None
    if len(out) < 1 or not out[0]:
        raise VersionError("this git repository has no working folder (a bare repository): version tools need one")
    top = Path(out[0]).resolve()
    if top != root and top not in root.parents:  # core.worktree pointing elsewhere: never act outside
        raise VersionError(f"the git working folder {top} does not contain the workspace {root}: refused")
    prefix = (out[1] if len(out) > 1 else "").strip()
    items = run(root, "config", "--list", "--show-scope", "-z").split("\0")  # scope \0 key \n value \0 ...
    for scope, item in zip(items[0::2], items[1::2], strict=False):
        key = item.split("\n", 1)[0]
        if scope in ("local", "worktree") and UNSAFE_LOCAL.match(key.lower()):
            raise VersionError(f"this repository's own git config sets {key}, a command git would run on the "
                               "files: b123d-print's version tools refuse to run it. Use git yourself for this "
                               "project, or remove that setting.")
    identity: tuple[str, ...] = ()
    for key, fallback in (("user.name", "b123d-print user"), ("user.email", "b123d-print@localhost")):
        if not run(root, "config", "--get", key, ok=(0, 1)).strip():
            identity += (f"{key}={fallback}",)
    return Repo(root, top, prefix, load_settings(root).parts_dir, identity)


def start(root: Path) -> str:
    """Make the workspace a git repository (if it is not in one) and write the .gitignore."""
    root = root.resolve()
    if not git_path():
        raise VersionError(NO_GIT)
    lines = []
    if is_repo(root):
        lines.append(f"{root} already has version history (git).")
    else:
        run(root, "init", "-q")
        lines.append(f"Started version history in {root} (a git repository, on this machine only).")
    added = write_gitignore(root)
    if added:
        lines.append(f".gitignore: {'wrote' if added == list(GITIGNORE) else 'added'} {', '.join(added)}")
    lines.append("Saved by save_version / `b123d-print save`: each part's script, its ref/ folder, MEASURE.md and "
                 "the .py files beside the script, plus b123d-print.toml. Not saved: out/ (made again by an export), "
                 "downloaded zips, tokens and client configs. Anything else you put in the folder is left alone.")
    return "\n".join(lines)


def write_gitignore(root: Path) -> list[str]:
    """Add the GITIGNORE lines missing from <root>/.gitignore; returns those added."""
    p = root / ".gitignore"
    if p.is_symlink():
        raise VersionError(".gitignore is a symlink: refused")
    old = p.read_text(encoding="utf-8") if p.exists() else ""
    have = {x.strip() for x in old.splitlines()}
    missing = [x for x in GITIGNORE if x not in have]
    if missing:
        sep = "" if not old or old.endswith("\n") else "\n"
        head = "" if GITIGNORE_HEAD in have else ("\n" if old else "") + GITIGNORE_HEAD + "\n"
        p.write_text(old + sep + head + "\n".join(missing) + "\n", encoding="utf-8", newline="")
    return missing


# ---------------------------------------------------------------------------------------------
# What is saved


def _check_part(part: str) -> None:
    if not NAME_RE.match(part or ""):
        raise VersionError(f"bad part name {part!r}: lower_snake_case, starting with a letter")


def _in_scope(rel: str, parts_dir: str, part: str | None) -> bool:
    """Is the workspace-relative path one the version tools save? (for one part, or all)"""
    p = PurePosixPath(rel)
    if any(x in ("", ".", "..") for x in p.parts):
        return False
    if part is None and rel in (WORKSPACE_FILE, ".gitignore"):
        return True
    base = PurePosixPath(parts_dir)
    if p.parts[: len(base.parts)] != base.parts:
        return False
    rest = p.parts[len(base.parts):]
    if len(rest) < 2 or not NAME_RE.match(rest[0]) or (part is not None and rest[0] != part):
        return False
    if len(rest) == 2:  # a file beside the script
        return rest[1].endswith(".py") or rest[1] in EXTRA
    return rest[1] == "ref" and not any(x.startswith(".") or x == "__pycache__" for x in rest[2:])


def _plain_file(p: Path) -> bool:
    return p.is_file() and not p.is_symlink()


def _current(repo: Repo, part: str | None) -> dict[str, Path]:
    """The files on disk that a save of `part` (or of everything) takes: workspace-relative paths."""
    root, pd = repo.root, repo.parts_dir
    found: dict[str, Path] = {}
    if part is None:
        for f in (WORKSPACE_FILE, ".gitignore"):
            if _plain_file(root / f):
                found[f] = root / f
    base = root / pd
    names = [part] if part else sorted(d.name for d in base.iterdir() if d.is_dir() and not d.is_symlink()) if base.is_dir() else []
    for name in names:
        d = base / name
        if not NAME_RE.match(name) or not d.is_dir() or d.is_symlink() or not _plain_file(d / f"{name}.py"):
            continue
        for f in sorted(d.iterdir()):
            rel = f"{pd}/{name}/{f.name}"
            if _plain_file(f) and _in_scope(rel, pd, name):
                found[rel] = f
        ref = d / "ref"
        if ref.is_dir() and not ref.is_symlink():
            for dirpath, dirs, files in os.walk(ref):  # does not follow symlinked folders
                dirs[:] = sorted(x for x in dirs if not x.startswith(".") and x != "__pycache__")
                for fn in sorted(files):
                    f = Path(dirpath) / fn
                    rel = f.relative_to(root).as_posix()
                    if _plain_file(f) and _in_scope(rel, pd, name):
                        found[rel] = f
    return found


def _scope_paths(repo: Repo, part: str | None) -> list[str]:
    """Pathspecs (relative to the workspace) that cover what a save of `part` takes."""
    if part:
        return [f"{repo.parts_dir}/{part}"]
    return [repo.parts_dir, WORKSPACE_FILE, ".gitignore"]


def _tree(repo: Repo, rev: str, part: str | None) -> dict[str, tuple[str, str]]:
    """{workspace-relative path: (mode, blob id)} of the saved files of `part` (or all) in `rev`."""
    out = run(repo.root, "ls-tree", "-r", "-z", "--full-name", rev, "--", *_scope_paths(repo, part), data=True)
    found = {}
    for entry in out.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        mode, _kind, blob = meta.decode().split(" ")
        full = path.decode("utf-8", errors="surrogateescape")
        if not full.startswith(repo.prefix):
            continue
        rel = full[len(repo.prefix):]
        if _in_scope(rel, repo.parts_dir, part):
            found[rel] = (mode, blob)
    return found


def _head(repo: Repo) -> str | None:
    out = run(repo.root, "rev-parse", "--verify", "-q", "HEAD^{commit}", ok=(0, 1)).strip()
    return out or None


def _hashes(repo: Repo, rels: list[str]) -> dict[str, str]:
    """The blob ids the files would get when saved (git hash-object: no repository filter runs)."""
    if not rels:
        return {}
    out = run(repo.root, "hash-object", "--", *rels).split()
    return dict(zip(rels, out, strict=True))


def _changes(repo: Repo, part: str | None) -> tuple[dict[str, Path], dict[str, str]]:
    """(files on disk, {path: 'added' | 'changed' | 'removed'}) against the last saved version."""
    files = _current(repo, part)
    head = _head(repo)
    saved = {rel: e for rel, e in (_tree(repo, head, part) if head else {}).items() if e[0] in PLAIN}  # not symlinks
    now = _hashes(repo, list(files))
    diff = {}
    for rel in files:
        if rel not in saved:
            diff[rel] = "added"
        elif saved[rel][1] != now[rel]:
            diff[rel] = "changed"
    for rel in saved:
        if rel not in files and _part_exists(repo, rel):  # a whole part folder gone: its history stays as it is
            diff[rel] = "removed"
    return files, dict(sorted(diff.items()))


def _part_exists(repo: Repo, rel: str) -> bool:
    name = _part_of(repo, rel)
    return name is None or _plain_file(repo.root / repo.parts_dir / name / f"{name}.py")


def _part_of(repo: Repo, rel: str) -> str | None:
    base = PurePosixPath(repo.parts_dir).parts
    p = PurePosixPath(rel).parts
    return p[len(base)] if p[: len(base)] == base and len(p) > len(base) + 1 else None


# ---------------------------------------------------------------------------------------------
# What changed, in words


def _blob(repo: Repo, blob: str) -> bytes:
    return run(repo.root, "cat-file", "blob", blob, data=True)  # raw: no filter, no textconv


def _dims(src: str | None) -> dict[str, str]:
    from .params import ParamError, read

    if not src:
        return {}
    try:
        info = read(src)
    except (ParamError, SyntaxError, ValueError, TypeError, AttributeError):  # a summary never stops a save
        return {}
    return {f["name"]: _show(f) for f in info.get("fields", [])}


def _show(field: dict) -> str:
    v = field.get("value") if field.get("literal") else None
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v) if v is not None and not isinstance(v, (list, dict)) else str(field.get("default"))


def dims_change(old: str | None, new: str | None) -> list[str]:
    """['ARM_L 115 → 130', 'new HOOK_R 4'] between two versions of a script (read, not run)."""
    a, b = _dims(old), _dims(new)
    out = [f"{k} {a[k]} → {b[k]}" for k in b if k in a and a[k] != b[k]]
    out += [f"new {k} {b[k]}" for k in b if k not in a]
    out += [f"removed {k}" for k in a if k not in b]
    return out


def _summary(repo: Repo, diff: dict[str, str], old_rev: str | None, read_new) -> list[str]:
    """One line per part: '<part>: ARM_L 115 → 130; ref/: added scan.png'."""
    by_part: dict[str, list[str]] = {}
    for rel, how in diff.items():
        name = _part_of(repo, rel)
        if name is None:
            by_part.setdefault(rel, []).append(how)
            continue
        msgs = by_part.setdefault(name, [])
        sub = rel.split(f"/{name}/", 1)[1]
        if sub == f"{name}.py":
            if how == "added":
                msgs.insert(0, "new part")
                continue
            old = _old_text(repo, old_rev, rel)
            ch = dims_change(old, read_new(rel)) if how == "changed" else []
            msgs.insert(0, ", ".join(ch) if ch else f"script {how}")
        else:
            msgs.append(f"{sub} {how}")
    return [f"{k}: {'; '.join(v)}" for k, v in by_part.items()]


def _old_text(repo: Repo, rev: str | None, rel: str) -> str | None:
    if not rev:
        return None
    entry = _tree_file(repo, rev, rel)
    return _blob(repo, entry[1]).decode("utf-8", errors="replace") if entry else None


def _tree_file(repo: Repo, rev: str, rel: str) -> tuple[str, str] | None:
    out = run(repo.root, "ls-tree", "-z", "--full-name", rev, "--", rel, data=True)
    for entry in out.split(b"\0"):
        if entry:
            meta, _, _path = entry.partition(b"\t")
            mode, kind, blob = meta.decode().split(" ")
            if kind == "blob":
                return mode, blob
    return None


# ---------------------------------------------------------------------------------------------
# save, history, restore


def _commit(repo: Repo, files: dict[str, Path], diff: dict[str, str], message: str) -> str:
    adds = [rel for rel, how in diff.items() if how != "removed"]
    gone = [rel for rel, how in diff.items() if how == "removed"]
    if adds:
        run(repo.root, "add", "-f", "--", *adds)  # -f: the user's own ignore rules never drop a saved file
    if gone:
        run(repo.root, "rm", "-q", "--cached", "--ignore-unmatch", "--", *gone)
    # --only with the paths: whatever else the user has staged stays staged, out of this commit
    run(repo.root, "commit", "-q", "--no-verify", "--only", "-m", message, "--", *diff, extra=repo.identity)
    return run(repo.root, "rev-parse", "HEAD").strip()


def _message(message: str, lines: list[str]) -> str:
    subject = " ".join((message or "").split()) or "; ".join(lines)
    return subject[:200] + ("\n\n" + "\n".join(lines) if lines and message else "")


def save(root: Path, message: str = "", part: str | None = None) -> str:
    """Commit what changed in the part (or every part) since the last save; returns what was saved."""
    if part is not None:
        _check_part(part)
    repo = open_repo(root)
    if part and not _plain_file(repo.root / repo.parts_dir / part / f"{part}.py"):
        raise VersionError(f"no part {part!r} in {repo.root / repo.parts_dir}")
    if len(message) > 2000:
        raise VersionError("message too long (over 2000 characters)")
    files, diff = _changes(repo, part)
    what = part or "the project"
    if not diff:
        return f"Nothing to save: {what} is the same as the last saved version."
    head = _head(repo)
    lines = _summary(repo, diff, head, lambda rel: files[rel].read_text(encoding="utf-8", errors="replace"))
    sha = _commit(repo, files, diff, _message(message, lines))
    n = len(_commits(repo, part)) if part else None
    big = [f"{rel} ({files[rel].stat().st_size / 1e6:.0f} MB)" for rel in diff
           if rel in files and files[rel].stat().st_size > 20_000_000]
    out = [f"Saved {what}" + (f" as version {n}" if n else "") + f" ({sha[:SHORT]})" + (f": {message.strip()}" if message.strip() else "")]
    out += [f"  {x}" for x in lines]
    if big:
        out.append(f"  note: large files saved ({', '.join(big)}); GitHub refuses files over 100 MB if you push there.")
    return "\n".join(out)


def _commits(repo: Repo, part: str | None) -> list[tuple[str, str, str]]:
    """[(sha, date, subject)] of the commits that touched what a save of `part` takes, oldest first."""
    if not _head(repo):
        return []
    out = run(repo.root, "log", "--reverse", "--no-show-signature", "--no-ext-diff", "--no-textconv",
              "--date=format:%Y-%m-%d %H:%M", "--format=%H%x1f%ad%x1f%s%x1e", "HEAD", "--", *_scope_paths(repo, part))
    rows = []
    for rec in out.split("\x1e"):
        rec = rec.strip("\n")
        if rec:
            sha, date, subject = rec.split("\x1f", 2)
            rows.append((sha, date, subject))
    return rows


def _touched(repo: Repo, sha: str) -> list[str]:
    out = run(repo.root, "diff-tree", "--no-commit-id", "--name-only", "-r", "-z", "--root", "--no-ext-diff",
              "--no-textconv", sha, data=True)
    names = []
    for full in out.decode("utf-8", errors="replace").split("\0"):
        if full.startswith(repo.prefix):
            name = _part_of(repo, full[len(repo.prefix):])
            if name and name not in names:
                names.append(name)
    return names


def history(root: Path, part: str | None = None, limit: int = 20) -> str:
    """The saved versions, newest first: number (per part), date, id, message, what changed."""
    if part is not None:
        _check_part(part)
    repo = open_repo(root)
    rows = _commits(repo, part)
    if not rows:
        return (f"No saved versions of {part or 'this project'} yet. "
                f"Save one with save_version(<message>{f', part={part!r}' if part else ''}).")
    lines = [f"Versions of {part} (newest first; restore one with restore_version('{part}', <number>)):" if part else
             "Saved versions (newest first; list_versions(<part>) numbers a part's versions for restore_version):"]
    shown = list(enumerate(rows, 1))[::-1][: max(1, limit)]
    script = f"{repo.parts_dir}/{part}/{part}.py" if part else None
    for n, (sha, date, subject) in shown:
        if part:
            new = _old_text(repo, sha, script)
            old = _old_text(repo, rows[n - 2][0], script) if n > 1 else None
            ch = dims_change(old, new) if n > 1 else []
            what = ", ".join(ch) if ch else ("first version" if n == 1 else "")
            lines.append(f"  {n:>3}  {date}  {sha[:SHORT]}  {subject}" + (f"  [{what}]" if what and what != subject else ""))
        else:
            lines.append(f"  {date}  {sha[:SHORT]}  {subject}  [{', '.join(_touched(repo, sha)) or 'settings'}]")
    if len(rows) > len(shown):
        lines.append(f"  ... {len(rows) - len(shown)} older")
    _, diff = _changes(repo, part)
    if diff:
        lines.append("Not saved yet: " + ", ".join(f"{rel} ({how})" for rel, how in diff.items()))
    return "\n".join(lines)


def _resolve(repo: Repo, part: str, version: str) -> tuple[int | None, str, str, str]:
    """(number, sha, date, subject) of a part's version given as a number from history() or a commit id."""
    rows = _commits(repo, part)
    v = (version or "").strip().lower()
    m = NUMBER_RE.match(v)
    if m and not (len(v) >= 7 and SHA_RE.match(v)):
        n = int(m.group(1))
        if not 1 <= n <= len(rows):
            raise VersionError(f"{part} has versions 1 to {len(rows)}" if rows else f"{part} has no saved versions")
        return (n, *rows[n - 1])
    if not SHA_RE.match(v):
        raise VersionError(f"bad version {version!r}: a number from list_versions('{part}') or a commit id "
                           "(7 to 40 hex digits)")
    sha = run(repo.root, "rev-parse", "--verify", "-q", f"{v}^{{commit}}", ok=(0, 1)).strip()
    if not sha:
        raise VersionError(f"no saved version {version!r}")
    for i, row in enumerate(rows, 1):
        if row[0] == sha:
            return (i, *row)
    raise VersionError(f"version {version} did not change {part}: pick one from list_versions('{part}')")


def _safe_target(repo: Repo, part: str, rel: str) -> Path:
    """The file to write for a saved path: inside the part folder, no symlink on the way."""
    if not _in_scope(rel, repo.parts_dir, part):
        raise VersionError(f"refused to write {rel!r}: not a saved file of {part}")
    target = repo.root / rel
    part_dir = repo.root / repo.parts_dir / part
    for p in [target, *target.parents]:
        if p == repo.root:
            break
        if p.is_symlink():
            raise VersionError(f"refused to write {rel}: {p.relative_to(repo.root)} is a symlink")
    if part_dir.resolve() not in target.resolve().parents:
        raise VersionError(f"refused to write {rel}: outside {part_dir}")
    return target


def restore(root: Path, part: str, version: str) -> str:
    """Bring a part's saved files back to an earlier version and save that as a new version."""
    _check_part(part)
    repo = open_repo(root)
    n, sha, date, subject = _resolve(repo, part, version)
    _, unsaved = _changes(repo, part)
    if unsaved:
        raise VersionError(f"{part} has changes that are not saved: {', '.join(unsaved)}. Restoring would lose them. "
                           f"Save them first (save_version(<message>, part='{part}')), then restore.")
    old = _tree(repo, sha, part)
    if not old:
        raise VersionError(f"version {version} has no files of {part}")
    skipped = [rel for rel, (mode, _) in old.items() if mode not in PLAIN]
    plan = {rel: blob for rel, (mode, blob) in old.items() if rel not in skipped}
    targets = {rel: _safe_target(repo, part, rel) for rel in plan}  # check every path before writing any
    for rel, blob in plan.items():
        t = targets[rel]
        if t.exists() and not _plain_file(t):
            raise VersionError(f"refused to write {rel}: something other than a file is there")
    for rel, blob in plan.items():
        t = targets[rel]
        t.parent.mkdir(parents=True, exist_ok=True)
        t.write_bytes(_blob(repo, blob))
    files, diff = _changes(repo, part)
    extra = sorted(rel for rel in files if rel not in old)
    label = f"version {n} ({sha[:SHORT]}, {date}: {subject})"
    if not diff:
        return f"{part} is already the same as {label}. Nothing to restore."
    head = _head(repo)
    lines = _summary(repo, diff, head, lambda rel: files[rel].read_text(encoding="utf-8", errors="replace"))
    new = _commit(repo, files, diff, _message(f"Restore {part} to version {n} ({sha[:SHORT]}): {subject}", lines))
    out = [f"Restored {part} to {label}, saved as a new version {len(_commits(repo, part))} ({new[:SHORT]}); "
           "the versions in between are kept."]
    out += [f"  {x}" for x in lines]
    if extra:
        out.append(f"  kept (not in that version, left as they are): {', '.join(extra)}")
    if skipped:
        out.append(f"  not restored (not a plain file): {', '.join(skipped)}")
    out.append(f"Next: build_part('{part}') and check('{part}') (or `b123d-print build {part}`).")
    return "\n".join(out)


# ---------------------------------------------------------------------------------------------
# Shared servers: the commands for the client's own shell


def _q(s: str) -> str:
    """Quote for a POSIX shell (the commands are shown, never run here)."""
    import shlex

    return shlex.quote(s)


def client_commands(action: str, parts_dir: str, part: str | None = None, message: str = "",
                    version: str = "") -> str:
    """What to run in the project folder on the user's machine, for a remote (HTTP/SSH) server."""
    if part is not None:
        _check_part(part)
    paths = [f"{parts_dir}/{part}"] if part else [parts_dir, WORKSPACE_FILE]
    head = ("This server is shared: the version history lives in the project folder on the user's machine, never "
            "on the server. Bring the part home first (download_part), then run in the project folder")
    tool = ("If b123d-print is installed there, the same in plain words: `b123d-print " +
            {"save": f"save {_q(message or 'my change')}" + (f" --part {part}" if part else ""),
             "list": "versions" + (f" {part}" if part else ""),
             "restore": f"restore {part} {_q(version)}"}[action] + "`.")
    if action == "save":
        cmds = [f"git add -- {' '.join(_q(p) for p in paths)}",
                f"git commit -m {_q(message or 'my change')} -- {' '.join(_q(p) for p in paths)}"]
        note = "out/ stays out if the folder's .gitignore lists it (`b123d-print init --git` writes one)."
    elif action == "list":
        cmds = ["git log --date=short --format='%h  %ad  %s' -- " + " ".join(_q(p) for p in paths)]
        note = "Each line: the version's id, date and message."
    else:
        if not part or not SHA_RE.match((version or "").lower()):
            raise VersionError("restore over a shared server needs the part and a commit id from the list "
                               "(7 to 40 hex digits)")
        cmds = [f"git checkout {version} -- {_q(parts_dir + '/' + part)}",
                f"git commit -m {_q(f'Restore {part} to {version}')} -- {_q(parts_dir + '/' + part)}"]
        note = (f"This makes a new version; nothing is lost. Then put the part back on the server: "
                f"write_part('{part}', <the restored {parts_dir}/{part}/{part}.py>) and upload_reference for "
                "any ref/ file that changed.")
    if action != "list":
        cmds.insert(0, "git status --short")
    return head + ":\n" + "\n".join(f"  {c}" for c in cmds) + f"\n{note}\n{tool}"


def offer(root: Path, part: str) -> str:
    """The line a passing check adds: offer to save (only when the workspace has version history
    and the part changed since its last save)."""
    try:
        repo = open_repo(root)
        _, diff = _changes(repo, part)
    except (VersionError, OSError):
        return ""
    if not diff:
        return ""
    return (f"Offer the user: \"Save this version of {part}?\" with a few words on what changed; on a yes, "
            f"save_version('<what changed>', part='{part}'). Never save without asking.")
