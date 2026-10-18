"""MCP over SSH: the server end of an `authorized_keys` forced command, its setup, `pull` and `push`.

On the server, one line in ~/.ssh/authorized_keys per client machine (written by `setup-ssh`):

    restrict,command="/home/me/.local/bin/b123d-print ssh-serve --workspace /home/me/parts/laptop --dest me@cad" ssh-ed25519 AAAA... laptop

sshd runs that command whatever the client asks for, and puts what it asked for in
SSH_ORIGINAL_COMMAND. `ssh-serve` answers only:

    (nothing), mcp, b123d-print-mcp   the MCP server over stdio, in the key's workspace
    pull <part> [--formats f]         a tar stream of that part's out/ files (read-only)
    push <part> <file> [--overwrite]  store stdin as the reference file <parts_dir>/<part>/ref/<file>
                                      (STL/3MF/STEP only, size-capped; see refs.py)
    version                           version, workspace and sandbox, to check the setup

Anything else (a shell, scp, sftp, port forwarding...) is refused. The workspace comes from the key
line, never from the client. `restrict` turns off ptys and every kind of forwarding.
"""

from __future__ import annotations

import argparse
import getpass
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import tarfile
from pathlib import Path

from .config import FORMATS, load_settings, parse_formats

KEY_RE = re.compile(r"^(?P<type>(?:ssh|ecdsa|sk)-[\w@.-]+)\s+(?P<blob>[A-Za-z0-9+/]+={0,3})(?:\s+(?P<comment>.*))?$")
WORKSPACE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
PART_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")  # = cli.NAME_RE
SUFFIX = {"step": ".step", "stl": ".stl", "3mf": ".3mf", "png": ".png"}
MARK = "ssh-serve"  # how setup-ssh recognizes its own lines


class Refused(Exception):
    pass


# ---------------------------------------------------------------------------------------------
# server end: the forced command


def _serve_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pull", add_help=False, exit_on_error=False)
    ap.add_argument("part")
    ap.add_argument("--formats")
    return ap


def _push_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="push", add_help=False, exit_on_error=False)
    ap.add_argument("part")
    ap.add_argument("file")
    ap.add_argument("--overwrite", action="store_true")
    return ap


def parse_request(original: str | None) -> tuple[str, dict]:
    """What the client asked for (SSH_ORIGINAL_COMMAND) -> ("mcp" | "version" | "pull" | "push", args).
    Raises Refused for everything else."""
    try:
        words = shlex.split(original or "")
    except ValueError:
        raise Refused("unparsable command") from None
    if not words or (words[0] in ("mcp", "b123d-print-mcp") and len(words) == 1):
        return "mcp", {}
    if words[0] in ("mcp", "b123d-print-mcp"):
        raise Refused("the workspace and server options are set on the server, in this key's authorized_keys line; "
                      "connect with plain `ssh user@host` and no command")
    if words == ["version"]:
        return "version", {}
    if words[0] == "pull":
        try:
            a, extra = _serve_parser().parse_known_args(words[1:])
        except (argparse.ArgumentError, SystemExit):
            raise Refused("usage: pull <part> [--formats step,stl,3mf,png]") from None
        if extra:
            raise Refused(f"pull: unexpected {' '.join(extra)!r}")
        if not PART_RE.match(a.part):
            raise Refused(f"pull: bad part name {a.part!r}")
        try:
            fmts = parse_formats(a.formats) if a.formats else FORMATS
        except ValueError as e:
            raise Refused(f"pull: {e}") from None
        return "pull", {"part": a.part, "formats": fmts}
    if words[0] == "push":
        from .refs import RefError, check_name

        try:
            a, extra = _push_parser().parse_known_args(words[1:])
        except (argparse.ArgumentError, SystemExit):
            raise Refused("usage: push <part> <file> [--overwrite]") from None
        if extra:
            raise Refused(f"push: unexpected {' '.join(extra)!r}")
        if not PART_RE.match(a.part):
            raise Refused(f"push: bad part name {a.part!r}")
        try:
            check_name(a.file)
        except RefError as e:
            raise Refused(f"push: {e}") from None
        return "push", {"part": a.part, "file": a.file, "overwrite": a.overwrite}
    raise Refused(f"{words[0]!r} is not allowed on this key: it only runs the b123d-print MCP server, "
                  "`pull <part>`, `push <part> <file>` and `version`")


def out_files(workspace: Path, part: str, formats=FORMATS) -> list[Path]:
    """The regular files in <workspace>/<parts_dir>/<part>/out/ with a suffix of `formats` (no
    symlinks, no hidden files, nothing below out/)."""
    from .links import LinkError, servable

    parts_dir = load_settings(workspace).parts_dir
    out = workspace / parts_dir / part / "out"
    if not out.is_dir() or out.is_symlink():
        return []
    want = {SUFFIX[f] for f in formats}
    found = []
    for p in sorted(out.iterdir()):
        if p.suffix.lower() not in want:
            continue
        try:
            found.append(servable(workspace, parts_dir, f"{parts_dir}/{part}/out/{p.name}"))
        except LinkError:
            continue
    return found


def write_tar(files: list[Path], stream) -> None:
    with tarfile.open(fileobj=stream, mode="w|") as tf:
        for f in files:
            info = tf.gettarinfo(str(f), arcname=f.name)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mode = 0o644
            with open(f, "rb") as fh:
                tf.addfile(info, fh)


def serve(workspace: str, dest: str | None, timeout: float | None, original: str | None,
          stdout=None, stderr=None, stdin=None) -> int:
    """The forced command's whole job. Returns the exit code (the MCP server never returns)."""
    stdout = stdout or sys.stdout.buffer
    stderr = stderr or sys.stderr
    ws = Path(workspace).expanduser().resolve()
    try:
        what, args = parse_request(original)
    except Refused as e:
        print(f"b123d-print: refused: {e}", file=stderr)
        return 1
    if what == "mcp":
        from . import mcp_server

        mcp_server.STATE["ssh_dest"] = dest or f"{getpass.getuser()}@{socket.getfqdn()}"
        argv = ["--workspace", str(ws), "--transport", "stdio"]
        if timeout:
            argv += ["--timeout", str(timeout)]
        mcp_server.main(argv)
        return 0
    if what == "version":
        from . import sandbox
        from importlib.metadata import version

        stdout.write(f"b123d-print {version('b123d-print')}\nworkspace: {ws}\nsandbox: {sandbox.describe()}\n".encode())
        stdout.flush()
        return 0
    if what == "push":
        from .refs import MAX_BYTES, RefError, store

        data = (stdin or sys.stdin.buffer).read(MAX_BYTES + 1)
        try:
            if len(data) > MAX_BYTES:
                raise RefError(f"over the {MAX_BYTES // 1_000_000} MB limit for reference files")
            p = store(ws, load_settings(ws).parts_dir, args["part"], args["file"], data, args["overwrite"])
        except (RefError, OSError) as e:
            print(f"b123d-print: refused: push: {e}", file=stderr)
            return 1
        stdout.write(f"stored {p.relative_to(ws.resolve()).as_posix()} ({len(data)} bytes)\n".encode())
        stdout.flush()
        return 0
    files = out_files(ws, args["part"], args["formats"])
    if not files:
        print(f"b123d-print: no {'/'.join(args['formats'])} files for part {args['part']!r} on the server: "
              "export it first", file=stderr)
        return 1
    write_tar(files, stdout)
    stdout.flush()
    return 0


# ---------------------------------------------------------------------------------------------
# client end: pull


def pull(part: str, dest: str, out_dir: Path, formats: str | None = None, ssh: str = "ssh") -> list[Path]:
    """Run `ssh <dest> pull <part>` and unpack the files into out_dir. Raises RuntimeError on failure."""
    if not PART_RE.match(part):
        raise RuntimeError(f"bad part name {part!r}")
    if formats:
        parse_formats(formats)  # fail here, not on the server
    remote = ["pull", part] + (["--formats", formats] if formats else [])
    # ssh joins the remote words with spaces and the server splits them again: quote each
    cmd = shlex.split(ssh) + ["-T", dest, " ".join(shlex.quote(w) for w in remote)]
    out_dir.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    got = []
    try:
        with tarfile.open(fileobj=proc.stdout, mode="r|") as tf:
            for m in tf:
                if not m.isfile() or "/" in m.name or "\\" in m.name or m.name.startswith(".") or not m.name:
                    raise RuntimeError(f"unexpected entry {m.name!r} from the server; nothing more written")
                target = out_dir / m.name
                with tf.extractfile(m) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                got.append(target)
    except tarfile.ReadError:
        pass  # no tar at all: the server refused; its message is on stderr
    finally:
        rest = proc.stdout.read()
        err = proc.stderr.read().decode(errors="replace").strip()
        proc.wait()
    if proc.returncode != 0 or not got:
        raise RuntimeError(err or f"ssh exited with code {proc.returncode}" + (f" ({rest[:200]!r})" if rest else ""))
    return got


def push(file: Path, part: str, dest: str, name: str | None = None, overwrite: bool = False, ssh: str = "ssh") -> str:
    """Run `ssh <dest> push <part> <name>` with the file on stdin. Returns the server's answer;
    raises RuntimeError (with the server's refusal) on failure."""
    from .refs import MAX_BYTES, RefError, check_name

    if not PART_RE.match(part):
        raise RuntimeError(f"bad part name {part!r}")
    name = name or file.name
    try:
        check_name(name)
    except RefError as e:
        raise RuntimeError(str(e)) from None
    if not file.is_file():
        raise RuntimeError(f"no file {file}")
    if file.stat().st_size > MAX_BYTES:
        raise RuntimeError(f"{file.name}: over the {MAX_BYTES // 1_000_000} MB limit for reference files")
    remote = ["push", part, name] + (["--overwrite"] if overwrite else [])
    cmd = shlex.split(ssh) + ["-T", dest, " ".join(shlex.quote(w) for w in remote)]
    with open(file, "rb") as f:
        proc = subprocess.run(cmd, stdin=f, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.decode(errors="replace").strip() or f"ssh exited with code {proc.returncode}")
    return proc.stdout.decode(errors="replace").strip()


# ---------------------------------------------------------------------------------------------
# setup-ssh


def read_pubkey(text: str) -> tuple[str, str, str]:
    """(type, base64 blob, comment) of a one-line OpenSSH public key."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    if len(lines) != 1:
        raise ValueError("expected exactly one public key line (the .pub file, not the private key)")
    m = KEY_RE.match(lines[0])
    if not m:
        raise ValueError("not an OpenSSH public key (expected e.g. 'ssh-ed25519 AAAA... comment'; "
                         "pass the .pub file, without options in front)")
    return m["type"], m["blob"], (m["comment"] or "").strip()


def workspace_path(value: str) -> Path:
    """A bare name ('laptop') is ~/parts/<name>; anything with a slash or ~ is a path."""
    if WORKSPACE_NAME_RE.match(value) and value not in (".", ".."):
        return Path.home() / "parts" / value
    return Path(value).expanduser().resolve()


def program() -> list[str]:
    """How sshd should start b123d-print: the installed script by absolute path (not via PATH,
    which a forced command's shell may not have)."""
    me = Path(sys.argv[0])
    if me.name == "b123d-print" and me.exists():
        return [str(me.absolute())]
    found = shutil.which("b123d-print")
    if found:
        return [str(Path(found).absolute())]
    return [sys.executable, "-m", "b123d_print.cli"]


def forced_command(workspace: Path, dest: str, prog: list[str] | None = None) -> str:
    return " ".join(shlex.quote(w) for w in [*(prog or program()), MARK, "--workspace", str(workspace), "--dest", dest])


def key_line(pubkey: str, workspace: Path, dest: str, prog: list[str] | None = None) -> str:
    ktype, blob, comment = read_pubkey(pubkey)
    cmd = forced_command(workspace, dest, prog).replace("\\", "\\\\").replace('"', '\\"')
    return f'restrict,command="{cmd}" {ktype} {blob} {comment or "b123d-print " + workspace.name}'.rstrip()


def line_command(line: str) -> str | None:
    """The command="..." of an authorized_keys line (unescaped), or None."""
    m = re.search(r'(?:^|,)command="((?:[^"\\]|\\.)*)"', line)
    return re.sub(r"\\(.)", r"\1", m.group(1)) if m else None


def add_line(path: Path, line: str, blob: str) -> str:
    """Put `line` (for the key `blob`) into authorized_keys at `path`: 'added', 'unchanged', or
    'replaced' (the same key's earlier b123d-print line). Refuses if that key already has other
    access there."""
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    old = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    hits = [i for i, ln in enumerate(old) if re.search(rf"(^|\s){re.escape(blob)}(\s|$)", ln)]
    if any(old[i].strip() == line for i in hits):
        return "unchanged"
    if any(MARK not in (line_command(old[i]) or "") for i in hits):
        raise ValueError(f"this key is already in {path} with other access (e.g. a normal login); sshd uses only "
                         "the first line for a key, so use a separate key pair for b123d-print "
                         "(ssh-keygen -t ed25519 -f ~/.ssh/b123d_print)")
    new = [ln for i, ln in enumerate(old) if i not in hits] + [line]
    tmp = path.with_name(path.name + ".b123d-print.tmp")
    tmp.write_text("\n".join(new) + "\n", encoding="utf-8")
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    return "replaced" if hits else "added"


def client_snippets(dest: str) -> str:
    import json

    generic = json.dumps({"mcpServers": {"b123d-print": {"command": "ssh", "args": [dest]}}})
    vscode = json.dumps({"servers": {"b123d-print": {"type": "stdio", "command": "ssh", "args": [dest]}}})
    return f"""On the client machine (it needs the private key; run `ssh {dest} version` once first:
it accepts the host key and should print the version and workspace):

  Claude Code:
    claude mcp add b123d-print -- ssh {dest}

  Claude Desktop, Cursor (~/.cursor/mcp.json), and most other clients:
{_indent(generic, 4)}

  VS Code (.vscode/mcp.json):
{_indent(vscode, 4)}

  Exported files, copied to the client:
    b123d-print pull <part> --from {dest}

  A model to remix (STL/3MF/STEP), copied to the server:
    b123d-print push <file> --part <part> --to {dest}

If the key is not your default one, add `-i ~/.ssh/<key>` before {dest} (or use a Host entry in ~/.ssh/config)."""


def _indent(s: str, n: int) -> str:
    return "\n".join(" " * n + ln for ln in s.splitlines())


def setup(key: str, workspace: str, host: str | None, add: bool, authorized_keys: Path | None, out=None) -> int:
    from .cli import init_workspace
    from . import sandbox

    out = out or sys.stdout
    text = sys.stdin.read() if key == "-" else Path(key).expanduser().read_text(encoding="utf-8")
    ws = workspace_path(workspace)
    dest = f"{getpass.getuser()}@{host or socket.getfqdn()}"
    line = key_line(text, ws, dest)
    init_workspace(ws)
    ak = authorized_keys or Path.home() / ".ssh" / "authorized_keys"
    print(f"workspace: {ws}", file=out)
    if sandbox.kind() == "none":
        print(f"warning: no OS sandbox here ({sandbox.describe()})", file=out)
    if add:
        status = add_line(ak, line, read_pubkey(text)[1])
        print(f"{ak}: {status}", file=out)
    else:
        print(f"\nAdd this line to {ak} (or run again with --add):\n\n{line}\n", file=out)
    print(f"\n{client_snippets(dest)}\n\nTo revoke: delete that line from {ak}.", file=out)
    return 0
