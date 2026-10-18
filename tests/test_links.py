"""Signed download links: signing, expiry, tampering, and which files may be served."""

import os

import pytest

from b123d_print import links

SECRET = links.derive_secret("a-bearer-token-0123456789")
PATH = "parts/box/out/box.3mf"


def parse(url: str) -> tuple[str, str, str]:
    _, files, ws, token, rest = url.split("/", 4)
    assert files == "files"
    return ws, token, rest


def test_round_trip():
    url, exp = links.sign(SECRET, "agent-a", PATH, 60, now=1000)
    ws, token, path = parse(url)
    assert (ws, path, exp) == ("agent-a", PATH, 1060)
    links.verify(SECRET, ws, token, path, now=1059)


def test_expired_is_410():
    url, _ = links.sign(SECRET, "agent-a", PATH, 60, now=1000)
    ws, token, path = parse(url)
    with pytest.raises(links.LinkError) as e:
        links.verify(SECRET, ws, token, path, now=1061)
    assert e.value.status == 410


@pytest.mark.parametrize("change", ["workspace", "path", "expiry", "signature", "secret"])
def test_tampered_is_404(change):
    url, _ = links.sign(SECRET, "agent-a", PATH, 60, now=1000)
    ws, token, path = parse(url)
    exp, sig = token.split(".")
    secret = SECRET
    if change == "workspace":
        ws = "agent-b"
    elif change == "path":
        path = "parts/box/out/box.stl"
    elif change == "expiry":
        token = f"{int(exp) + 3600}.{sig}"
    elif change == "signature":
        token = f"{exp}.{sig[:-2]}AA"
    else:
        secret = links.derive_secret("another-token-0123456789")
    with pytest.raises(links.LinkError) as e:
        links.verify(secret, ws, token, path, now=1001)
    assert e.value.status == 404


@pytest.mark.parametrize("token", ["", "x", "1000", "abc.def", ".sig"])
def test_malformed_token_is_404(token):
    with pytest.raises(links.LinkError):
        links.verify(SECRET, "agent-a", token, PATH, now=0)


def test_secret_is_not_the_token_and_is_stable():
    assert links.derive_secret("tok-0123456789abcdef") == links.derive_secret("tok-0123456789abcdef")
    assert b"tok-0123456789abcdef" not in links.derive_secret("tok-0123456789abcdef")
    assert links.derive_secret("t" * 20, "explicit") == b"explicit"
    assert links.derive_secret(None) != links.derive_secret(None)  # no token: random per process


@pytest.mark.parametrize("bad", ["../x", "parts/../../etc/passwd", "/etc/passwd", "parts//out/x", "parts/./out/x",
                                 "parts/box/out/.hidden", "a\\b", ""])
def test_check_path_refuses(bad):
    with pytest.raises(links.LinkError):
        links.check_path(bad)


def test_servable(tmp_path):
    out = tmp_path / "parts/box/out"
    out.mkdir(parents=True)
    (out / "box.3mf").write_bytes(b"3mf")
    (tmp_path / "parts/box/box.py").write_text("x")
    (tmp_path / "secret.txt").write_text("no")
    assert links.servable(tmp_path, "parts", PATH).read_bytes() == b"3mf"
    for p in ("parts/box/box.py", "secret.txt", "parts/box/out", "parts/box/out/missing.stl", "parts/box/out/sub/x.stl"):
        with pytest.raises(links.LinkError):
            links.servable(tmp_path, "parts", p)


@pytest.mark.symlinks
def test_servable_refuses_symlinks(tmp_path):
    out = tmp_path / "parts/box/out"
    out.mkdir(parents=True)
    (tmp_path / "secret.txt").write_text("no")
    os.symlink(tmp_path / "secret.txt", out / "leak.stl")
    os.symlink(out, tmp_path / "parts/link")
    (tmp_path / "parts/link2").mkdir()
    os.symlink(out, tmp_path / "parts/link2/out")
    for p in ("parts/box/out/leak.stl", "parts/link/out/leak.stl", "parts/link2/out/leak.stl"):
        with pytest.raises(links.LinkError):
            links.servable(tmp_path, "parts", p)


def test_content_types():
    assert links.content_type("a/b.3mf") == "model/3mf"
    assert links.content_type("a/b.STL") == "model/stl"
    assert links.content_type("a/b.step") == "model/step"
    assert links.content_type("a/b.png") == "image/png"
