"""MCP over SSH: the forced-command dispatcher, setup-ssh, pull, and the build limit across processes."""

import io
import os
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

import pytest

from b123d_print import sandbox, ssh

ROOT = Path(__file__).resolve().parents[1]
FAKE_SSH = f"{sys.executable} {ROOT / 'tests' / 'fake_ssh.py'}"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKCbiyMIpQvcOhoPsC6yzJoIhRkkG7wuIPlTJDRKILTV laptop"
KEY2 = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIGmF9n0V5d3cJ2r9pW4xk8yZt1L0qQn5rS3aB6cD7eFg other"


@pytest.fixture
def ws(tmp_path, monkeypatch):
    """A workspace with one exported part, plus things that must never be served."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    w = tmp_path / "ws"
    out = w / "parts" / "box" / "out"
    out.mkdir(parents=True)
    (w / "b123d-print.toml").write_text("", encoding="utf-8")
    (w / "parts" / "box" / "box.py").write_text("SECRET = 1\n", encoding="utf-8", newline="")
    for name, data in (("box.3mf", b"3mf-bytes"), ("box.stl", b"stl-bytes"), ("box.png", b"png"), (".hidden.stl", b"no")):
        (out / name).write_bytes(data)
    (tmp_path / "outside.stl").write_bytes(b"outside")
    try:
        os.symlink(tmp_path / "outside.stl", out / "link.stl")
    except OSError:  # Windows without Developer Mode or admin: no symlinks to refuse, either
        pass
    (out / "sub").mkdir()
    (out / "sub" / "deep.stl").write_bytes(b"deep")
    return w


def run_serve(ws: Path, original: str | None):
    out, err = io.BytesIO(), io.StringIO()
    code = ssh.serve(str(ws), "me@cad", None, original, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue()


def untar(data: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(data)) as tf:
        return {m.name: tf.extractfile(m).read() for m in tf}


# --- what the dispatcher allows ------------------------------------------------------------------


@pytest.mark.parametrize("cmd", [None, "", "mcp", "b123d-print-mcp", "  mcp  "])
def test_mcp_requests(cmd):
    assert ssh.parse_request(cmd) == ("mcp", {})


@pytest.mark.parametrize("cmd", [
    "bash", "sh -c id", "/bin/sh", "ls", "cat /etc/passwd", "internal-sftp", "/usr/lib/openssh/sftp-server",
    "scp -f parts/box/out/box.3mf", "rsync --server --sender . parts", "git-upload-pack 'repo'",
    "b123d-print-mcp --workspace /etc", "mcp --workspace ../other", "b123d-print-mcp --transport http",
    "python -c 'import os'", "version; bash", "pull box; bash", "pull box && id", "pull '", "pull",
    "pull ../../etc", "pull box/../x", "pull Box", "pull box extra", "pull box --formats obj",
    "pull box --workspace /etc", "pull box --root /", "pull /etc/passwd", "PULL box",
])
def test_refused(ws, cmd):
    code, out, err = run_serve(ws, cmd)
    assert code == 1 and out == b"" and "refused" in err


def test_version(ws):
    code, out, _ = run_serve(ws, "version")
    assert code == 0 and b"b123d-print " in out and str(ws.resolve()).encode() in out


def test_pull_serves_only_out_files(ws):
    code, out, err = run_serve(ws, "pull box")
    assert code == 0, err
    assert untar(out) == {"box.3mf": b"3mf-bytes", "box.png": b"png", "box.stl": b"stl-bytes"}
    code, out, _ = run_serve(ws, "pull box --formats 3mf")
    assert untar(out) == {"box.3mf": b"3mf-bytes"}
    code, out, err = run_serve(ws, "pull nosuch")
    assert code == 1 and out == b"" and "export it first" in err


def test_pull_tree_serves_the_whole_part(ws):
    (ws / "parts/box/ref").mkdir()
    (ws / "parts/box/ref/orig.stl").write_bytes(b"solid ref")
    code, out, err = run_serve(ws, "pull box --tree")
    assert code == 0, err
    assert untar(out) == {"box.py": b"SECRET = 1\n", "out/box.3mf": b"3mf-bytes", "out/box.png": b"png",
                          "out/box.stl": b"stl-bytes", "ref/orig.stl": b"solid ref"}
    code, out, err = run_serve(ws, "pull box --tree --formats 3mf --variant standard")
    assert code == 0 and set(untar(out)) == {"box.py", "out/box.3mf", "ref/orig.stl"}, err
    for bad in ("pull box --variant x", "pull box --tree --variant '../x'", "pull nosuch --tree"):
        code, out, err = run_serve(ws, bad)
        assert code == 1 and out == b"" and "refused" in err, bad


def test_workspace_is_pinned_by_the_key(ws, tmp_path):
    """The client's command can never pick another workspace: only the key line's --workspace counts."""
    other = tmp_path / "other"
    (other / "parts" / "box" / "out").mkdir(parents=True)
    (other / "parts" / "box" / "out" / "box.3mf").write_bytes(b"OTHER")
    for cmd in ("pull box --workspace " + str(other), "pull box --root " + str(other)):
        assert run_serve(ws, cmd)[0] == 1
    assert untar(run_serve(ws, "pull box --formats 3mf")[1]) == {"box.3mf": b"3mf-bytes"}


# --- setup-ssh -----------------------------------------------------------------------------------


@pytest.mark.posix(reason="checks how sshd's /bin/sh splits the forced command; SSH mode's server side is POSIX only")
def test_key_line_round_trip(tmp_path):
    ws = tmp_path / "my parts" / 'odd"name'
    line = ssh.key_line(KEY, ws, "me@cad", prog=["/opt/b123d print/bin/b123d-print"])
    assert line.startswith('restrict,command="') and line.endswith(" laptop")
    cmd = ssh.line_command(line)
    # what sshd hands to the shell splits back into exactly the intended words
    words = subprocess.run(["/bin/sh", "-c", f'for w in {cmd}; do printf "%s\\n" "$w"; done'],
                           capture_output=True, text=True).stdout.splitlines()
    assert words == ["/opt/b123d print/bin/b123d-print", "ssh-serve", "--workspace", str(ws), "--dest", "me@cad"]


@pytest.mark.parametrize("bad", ["", "not a key", KEY + "\n" + KEY2, 'command="x" ' + KEY,
                                 "-----BEGIN OPENSSH PRIVATE KEY-----\nabc\n-----END OPENSSH PRIVATE KEY-----"])
def test_bad_public_keys(bad):
    with pytest.raises(ValueError):
        ssh.read_pubkey(bad)


def test_workspace_names(tmp_path):
    assert ssh.workspace_path("laptop") == Path.home() / "parts" / "laptop"
    assert ssh.workspace_path(str(tmp_path / "x")) == (tmp_path / "x").resolve()
    assert ssh.workspace_path("../x") == Path("../x").resolve()


def test_add_line_is_idempotent(tmp_path):
    ak = tmp_path / ".ssh" / "authorized_keys"
    ak.parent.mkdir()
    ak.write_text(KEY2 + "\n", encoding="utf-8")  # someone's normal login key stays as it is
    blob = ssh.read_pubkey(KEY)[1]
    l1 = ssh.key_line(KEY, tmp_path / "a", "me@cad", prog=["b123d-print"])
    l2 = ssh.key_line(KEY, tmp_path / "b", "me@cad", prog=["b123d-print"])
    assert ssh.add_line(ak, l1, blob) == "added"
    assert ssh.add_line(ak, l1, blob) == "unchanged"
    assert ssh.add_line(ak, l2, blob) == "replaced"
    assert ak.read_text(encoding="utf-8").splitlines() == [KEY2, l2]
    if sys.platform != "win32":  # no POSIX modes on Windows (the file inherits the folder's ACL)
        assert (ak.stat().st_mode & 0o777) == 0o600


def test_add_line_refuses_a_key_with_other_access(tmp_path):
    ak = tmp_path / "authorized_keys"
    ak.write_text(KEY + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="separate key"):
        ssh.add_line(ak, ssh.key_line(KEY, tmp_path / "a", "me@cad"), ssh.read_pubkey(KEY)[1])
    assert ak.read_text(encoding="utf-8") == KEY + "\n"


def test_setup_ssh_cli(tmp_path, monkeypatch, capsys):
    from b123d_print.cli import main

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    pub = tmp_path / "laptop.pub"
    pub.write_text(KEY + "\n", encoding="utf-8")
    ak = tmp_path / "ak"
    args = ["setup-ssh", "--key", str(pub), "--workspace", str(tmp_path / "ws"), "--host", "cad.lan", "--authorized-keys", str(ak)]
    assert main(args) == 0
    out = capsys.readouterr().out
    assert "restrict,command=" in out and "claude mcp add b123d-print -- ssh " in out and "@cad.lan" in out
    assert not ak.exists() and (tmp_path / "ws" / "b123d-print.toml").exists()
    assert main(args + ["--add"]) == 0 and main(args + ["--add"]) == 0
    assert len(ak.read_text(encoding="utf-8").splitlines()) == 1


# --- pull, end to end through the forced command ---------------------------------------------------


def forced(ws: Path) -> str:
    return ssh.line_command(ssh.key_line(KEY, ws, "me@cad", prog=[sys.executable, "-m", "b123d_print.cli"]))


def test_pull_cli(ws, tmp_path, monkeypatch):
    monkeypatch.setenv("B123D_PRINT_FAKE_SSH_FORCED", forced(ws))
    dest = tmp_path / "got"
    files = ssh.pull("box", "me@cad", dest, "3mf,stl", ssh=FAKE_SSH)
    assert sorted(p.relative_to(dest).as_posix() for p in files) == [
        "parts/box/box.py", "parts/box/out/box.3mf", "parts/box/out/box.stl"]  # the local layout
    assert (dest / "parts/box/out/box.3mf").read_bytes() == b"3mf-bytes"
    with pytest.raises(RuntimeError, match="no part"):
        ssh.pull("nosuch", "me@cad", dest, ssh=FAKE_SSH)
    with pytest.raises(RuntimeError, match="bad part name"):
        ssh.pull("../x", "me@cad", dest, ssh=FAKE_SSH)
    r = subprocess.run([sys.executable, "-m", "b123d_print.cli", "pull", "box", "--from", "me@cad", "--formats", "png",
                        "-o", str(tmp_path / "cli"), "--ssh", FAKE_SSH], capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert [p.name for p in (tmp_path / "cli/parts/box/out").iterdir()] == ["box.png"]


def test_shell_metacharacters_never_reach_a_shell(ws, tmp_path, monkeypatch):
    monkeypatch.setenv("B123D_PRINT_FAKE_SSH_FORCED", forced(ws))
    marker = tmp_path / "pwned"
    r = subprocess.run(FAKE_SSH.split() + ["me@cad", f"pull box; touch {marker}"], capture_output=True, text=True)
    assert r.returncode == 1 and "refused" in r.stderr and not marker.exists()
    r = subprocess.run(FAKE_SSH.split() + ["me@cad", f"$(touch {marker})"], capture_output=True, text=True)
    assert r.returncode == 1 and not marker.exists()


def test_pull_rejects_a_malicious_tar(tmp_path):
    """A compromised server cannot write outside the chosen folder."""
    evil = io.BytesIO()
    with tarfile.open(fileobj=evil, mode="w") as tf:
        info = tarfile.TarInfo("../escape.txt")
        info.size = 1
        tf.addfile(info, io.BytesIO(b"x"))
    blob = tmp_path / "evil.tar"
    blob.write_bytes(evil.getvalue())
    fake = tmp_path / "evilssh.py"
    fake.write_text(f"import sys\nsys.stdout.buffer.write(open({str(blob)!r}, 'rb').read())\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="unexpected entry"):
        ssh.pull("box", "me@cad", tmp_path / "dest", ssh=f'"{sys.executable}" "{fake}"')
    assert not (tmp_path / "escape.txt").exists()


# --- the build limit across server processes -------------------------------------------------------


def test_build_slot_limits_across_processes(tmp_path, monkeypatch):
    """Two slots: two other processes hold them, so a third caller waits until one lets go."""
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    # Order, not wall-clock: under a loaded CI runner the holders start at different times, so
    # the test checks that our slot came only AFTER the short holder let go of its slot.
    hold = ("import sys, time; from pathlib import Path; from b123d_print import sandbox; "
            "sandbox.SLOT_DIR = Path(sys.argv[1]); s = sandbox.build_slot(2, poll=0.02); s.__enter__(); "
            "print('held', flush=True); time.sleep(float(sys.argv[2])); "
            "Path(sys.argv[3]).write_text(repr(time.time())); s.__exit__(None, None, None)")
    released = tmp_path / "released"
    procs = [subprocess.Popen([sys.executable, "-c", hold, str(tmp_path / "slots"), t, str(released)],
                              stdout=subprocess.PIPE, text=True)
             for t in ("1.0", "30")]
    try:
        for p in procs:
            assert p.stdout.readline().strip() == "held"
        assert not released.exists()  # both slots are taken now
        with sandbox.build_slot(2, poll=0.02) as slot:
            got = time.time()
        assert released.exists(), "got a slot while both were still held"
        assert slot in (0, 1) and got >= float(released.read_text()) - 0.05, "got a slot before it was released"
    finally:
        for p in procs:
            p.kill()
            p.wait()


def test_build_slot_freed_when_a_holder_dies(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    hold = ("import sys, time; from pathlib import Path; from b123d_print import sandbox; "
            "sandbox.SLOT_DIR = Path(sys.argv[1]); s = sandbox.build_slot(1); s.__enter__(); print('held', flush=True); time.sleep(60)")
    p = subprocess.Popen([sys.executable, "-c", hold, str(tmp_path / "slots")], stdout=subprocess.PIPE, text=True)
    assert p.stdout.readline().strip() == "held"
    got = []
    t = threading.Thread(target=lambda: got.append(sandbox.build_slot(1, poll=0.02).__enter__()))
    t.start()
    time.sleep(0.3)
    assert not got  # still waiting
    p.kill()
    p.wait()
    t.join(5)
    assert got == [0]


def test_build_slot_threads_in_one_process(tmp_path, monkeypatch):
    monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")
    running, peak, lock = [0], [0], threading.Lock()

    def job():
        with sandbox.build_slot(2, poll=0.01):
            with lock:
                running[0] += 1
                peak[0] = max(peak[0], running[0])
            time.sleep(0.1)
            with lock:
                running[0] -= 1

    threads = [threading.Thread(target=job) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak[0] == 2
