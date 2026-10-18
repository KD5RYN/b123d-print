"""Signed download links for files the HTTP server wrote (exports, renders, sections).

A link is  <base>/files/<workspace>/<expires>.<signature>/<path>  where <workspace> is the client's
workspace name ("_" for the shared root workspace), <path> is relative to that workspace and
<signature> is HMAC-SHA256(secret, workspace NUL path NUL expires), base64url. It needs no bearer
token, so curl, a browser or another agent can fetch it, but it opens exactly that one file until
it expires. The server only serves regular files under <workspace>/<parts_dir>/<part>/out/.

Upload links (`upload_reference`) are the same with /upload/ and a signature over a purpose
("put" or "put-overwrite") as well: a PUT to one stores one reference file in
<parts_dir>/<part>/ref/ (refs.store), until it expires.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import mimetypes
import os
import stat
import time
from pathlib import Path, PurePosixPath
from urllib.parse import quote

ROOT_WS = "_"  # stands for the shared root workspace (no valid workspace name starts with "_")

TYPES = {".3mf": "model/3mf", ".stl": "model/stl", ".step": "model/step", ".stp": "model/step",
         ".png": "image/png", ".json": "application/json"}


def derive_secret(token: str | None, explicit: str | None = None) -> bytes:
    """The signing key: B123D_PRINT_LINK_SECRET if set, else derived from the bearer token (so links
    stay valid across restarts but reveal nothing about the token), else random for this process."""
    if explicit:
        return explicit.encode()
    if token:
        return hmac.new(token.encode(), b"b123d-print file links v1", hashlib.sha256).digest()
    return os.urandom(32)


def _sig(secret: bytes, workspace: str, path: str, expires: int, purpose: str = "") -> str:
    msg = f"{workspace}\0{path}\0{expires}".encode()
    if purpose:  # upload links ("put", "put-overwrite") never verify as download links, nor the other way round
        msg = f"{purpose}\0".encode() + msg
    return base64.urlsafe_b64encode(hmac.new(secret, msg, hashlib.sha256).digest()).rstrip(b"=").decode()


def sign(secret: bytes, workspace: str, path: str, ttl: float, now: float | None = None, purpose: str = "") -> tuple[str, int]:
    """URL path ("/files/...", or "/upload/..." for a purpose) for `path` (POSIX, relative to the
    workspace) and its expiry (epoch s)."""
    expires = int((now if now is not None else time.time()) + ttl)
    route = "upload" if purpose else "files"
    url = f"/{route}/{workspace}/{expires}.{_sig(secret, workspace, path, expires, purpose)}/{quote(path)}"
    return url, expires


class LinkError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def verify(secret: bytes, workspace: str, token: str, path: str, now: float | None = None, purpose: str = "") -> None:
    """Raise LinkError(404) for a link this server did not sign, LinkError(410) once it expired."""
    exp_s, _, sig = token.partition(".")
    if not exp_s.isdigit() or not sig:
        raise LinkError(404, "not found")
    if not hmac.compare_digest(sig, _sig(secret, workspace, path, int(exp_s), purpose)):
        raise LinkError(404, "not found")
    if int(exp_s) < (now if now is not None else time.time()):
        raise LinkError(410, "link expired: call the tool again for a fresh link")


def check_path(path: str) -> PurePosixPath:
    """A relative POSIX path with no '..', '.', empty or hidden segments; else LinkError(404)."""
    p = PurePosixPath(path)
    if not path or "\\" in path or "\0" in path or p.is_absolute() or any(s in ("", ".", "..") or s.startswith(".") for s in path.split("/")):
        raise LinkError(404, "not found")
    return p


def servable(ws_root: Path, parts_dir: str, path: str) -> Path:
    """The file `path` (relative to ws_root) if it is a regular file in <parts_dir>/<part>/out/ with no
    symlink anywhere on the way; else LinkError(404)."""
    rel = check_path(path)
    base = PurePosixPath(parts_dir)
    if len(rel.parts) != len(base.parts) + 3 or rel.parts[: len(base.parts)] != base.parts or rel.parts[-2] != "out":
        raise LinkError(404, "not found")
    cur = ws_root
    for seg in rel.parts:
        cur = cur / seg
        try:
            st = os.lstat(cur)
        except OSError:
            raise LinkError(404, "not found") from None
        if stat.S_ISLNK(st.st_mode):
            raise LinkError(404, "not found")
    if not stat.S_ISREG(st.st_mode):
        raise LinkError(404, "not found")
    return cur


def upload_target(parts_dir: str, path: str) -> tuple[str, str]:
    """(part, filename) of an upload path <parts_dir>/<part>/ref/<file>; else LinkError(404)."""
    rel = check_path(path)
    base = PurePosixPath(parts_dir)
    if len(rel.parts) != len(base.parts) + 3 or rel.parts[: len(base.parts)] != base.parts or rel.parts[-2] != "ref":
        raise LinkError(404, "not found")
    return rel.parts[-3], rel.parts[-1]


def content_type(path: str) -> str:
    suffix = PurePosixPath(path).suffix.lower()
    return TYPES.get(suffix) or mimetypes.guess_type(path)[0] or "application/octet-stream"
