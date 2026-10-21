"""Named bearer tokens for the HTTP server: one per agent or tool, each limited to workspaces.

The tokens file (B123D_PRINT_TOKENS_FILE) is TOML. It stores only the SHA-256 of each token, so
reading it does not give the tokens away:

    link_secret = "…"                   # signs download links (made on the first `token add`)

    [tokens.grok-chromebook]
    sha256 = "9f2c…"
    workspaces = ["grok-*"]             # fnmatch patterns; "_" is the shared root workspace
    created = "2026-10-17"

    b123d-print-mcp token add grok-chromebook                      # workspace "grok-chromebook"; prints
                                                                   # the token once, with client config
    b123d-print-mcp token add eval-runner --workspace 'eval-*'     # or names/patterns of its own
    b123d-print-mcp token list
    b123d-print-mcp token revoke grok-chromebook

The server re-reads the file when it changes (and on SIGHUP), so adding or revoking a token needs
no restart. B123D_PRINT_TOKEN still works: it is the token "default", allowed every workspace.
"""

from __future__ import annotations

import fnmatch
import hashlib
import hmac
import os
import re
import secrets
import sys
import threading
import time
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")  # also a valid workspace name (the default one)
PATTERN_RE = re.compile(r"^[A-Za-z0-9_*?-]{1,64}$")
ROOT_WS = "_"  # the shared root workspace (as in links.ROOT_WS)


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Token:
    name: str
    sha256: str
    workspaces: list[str] = field(default_factory=lambda: ["*"])
    created: str = ""

    def allows(self, workspace: str | None) -> bool:
        """workspace: the client's workspace name, or None/"" for the shared root workspace."""
        ws = workspace or ROOT_WS
        return any(fnmatch.fnmatchcase(ws, p) for p in self.workspaces)

    def default_workspace(self) -> str | None:
        """The workspace a request without ?workspace= uses: the token's only workspace, if it has
        exactly one and it is not a pattern; else None (the root workspace, if allowed)."""
        if len(self.workspaces) == 1 and not any(c in self.workspaces[0] for c in "*?[") and self.workspaces[0] != ROOT_WS:
            return self.workspaces[0]
        return None


def read(path: Path) -> tuple[dict[str, Token], str | None]:
    """{name: Token}, link_secret. Raises ValueError for a malformed file."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    out = {}
    for name, t in (raw.get("tokens") or {}).items():
        if not NAME_RE.match(name) or not isinstance(t, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(t.get("sha256", ""))):
            raise ValueError(f"{path}: token {name!r} needs a name and a 64-hex-digit sha256")
        ws = t.get("workspaces", ["*"])
        if not isinstance(ws, list) or not ws or not all(isinstance(p, str) and PATTERN_RE.match(p) for p in ws):
            raise ValueError(f"{path}: token {name!r}: workspaces must be a non-empty list of names or patterns")
        out[name] = Token(name, t["sha256"], list(ws), str(t.get("created", "")))
    secret = raw.get("link_secret")
    return out, (str(secret) if secret else None)


def _q(s: str) -> str:
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def write(path: Path, toks: dict[str, Token], link_secret: str | None) -> None:
    """Write the file atomically (readers never see half a file), mode 600."""
    lines = ["# b123d-print HTTP tokens: only their SHA-256 is stored. Edit with `b123d-print-mcp token ...`.", ""]
    if link_secret:
        lines += [f"link_secret = {_q(link_secret)}", ""]
    for t in toks.values():
        lines += [f"[tokens.{t.name}]", f"sha256 = {_q(t.sha256)}",
                  "workspaces = [" + ", ".join(_q(p) for p in t.workspaces) + "]", f"created = {_q(t.created)}", ""]
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    os.replace(tmp, path)


class Store:
    """The tokens the server accepts: the file (re-read when it changes) plus B123D_PRINT_TOKEN."""

    def __init__(self, path: Path | None, legacy: str | None = None):
        self.path, self.legacy = path, legacy
        self._lock = threading.Lock()
        self._stamp = None
        self._by_hash: dict[str, Token] = {}
        self.link_secret: str | None = None
        self.reload(force=True)

    def _stat(self):
        try:
            st = os.stat(self.path)
            return st.st_mtime_ns, st.st_ino, st.st_size
        except OSError:
            return None

    def reload(self, force: bool = False) -> None:
        if self.path is None:
            if force:
                self._set({}, None)
            return
        stamp = self._stat()
        if not force and stamp == self._stamp:
            return
        with self._lock:
            if not force and stamp == self._stamp:
                return
            try:
                toks, secret = read(self.path) if stamp else ({}, None)
            except (OSError, ValueError, tomllib.TOMLDecodeError) as e:
                if force and stamp:
                    raise
                print(f"b123d-print-mcp: keeping the previous tokens; cannot read {self.path}: {e}", file=sys.stderr)
                self._stamp = stamp
                return
            self._set(toks, secret)
            self._stamp = stamp
            if not force:
                print(f"b123d-print-mcp: tokens reloaded from {self.path}: {', '.join(sorted(toks)) or 'none'}", file=sys.stderr)

    def request_reload(self) -> None:
        """SIGHUP: re-read the file on the next request even if it looks unchanged."""
        self._stamp = ("reload",)

    def _set(self, toks: dict[str, Token], secret: str | None) -> None:
        by_hash = {t.sha256: t for t in toks.values()}
        if self.legacy:
            by_hash[digest(self.legacy)] = Token("default", digest(self.legacy), ["*"])
        self._by_hash, self.link_secret = by_hash, secret

    def check(self, token: str) -> Token | None:
        self.reload()
        h = digest(token)
        for known, t in self._by_hash.items():  # constant time per comparison; the set is small
            if hmac.compare_digest(known, h):
                return t
        return None

    def names(self) -> list[str]:
        return sorted(t.name for t in self._by_hash.values())


def generate() -> str:
    return "b1p_" + secrets.token_urlsafe(32)


# --- CLI: b123d-print-mcp token ... ------------------------------------------------------------


def cli(args) -> int:
    path = Path(args.tokens_file).expanduser() if args.tokens_file else None
    if path is None:
        print("b123d-print-mcp token: set B123D_PRINT_TOKENS_FILE or pass --tokens-file <path>", file=sys.stderr)
        return 2
    try:
        toks, secret = read(path) if path.exists() else ({}, None)
    except (ValueError, tomllib.TOMLDecodeError) as e:
        print(f"b123d-print-mcp token: {e}", file=sys.stderr)
        return 1
    if args.token_command == "list":
        if not toks:
            print(f"no tokens in {path}")
        for t in toks.values():
            print(f"{t.name:24} workspaces {', '.join(t.workspaces):30} created {t.created or '?':10} sha256 {t.sha256[:12]}...")
        return 0
    name = args.name
    if not NAME_RE.match(name):
        print(f"b123d-print-mcp token: bad name {name!r}: letters, digits, '_', '-', up to 64", file=sys.stderr)
        return 2
    if args.token_command == "revoke":
        if name not in toks:
            print(f"b123d-print-mcp token: no token {name!r} in {path}", file=sys.stderr)
            return 1
        del toks[name]
        write(path, toks, secret)
        print(f"revoked {name}; the server stops accepting it on its next request", file=sys.stderr)
        return 0
    # add
    if name in toks:
        print(f"b123d-print-mcp token: {name!r} exists; revoke it first to replace it", file=sys.stderr)
        return 1
    patterns = args.workspace or [name]  # by default a token gets one workspace of its own
    bad = [p for p in patterns if not PATTERN_RE.match(p)]
    if bad:
        print(f"b123d-print-mcp token: bad workspace pattern(s) {bad}: letters, digits, '_', '-', '*', '?'", file=sys.stderr)
        return 2
    tok = generate()
    toks[name] = Token(name, digest(tok), patterns, time.strftime("%Y-%m-%d"))
    write(path, toks, secret or secrets.token_urlsafe(32))
    print(tok)
    print(client_config(name, tok, patterns, args.url or os.environ.get("B123D_PRINT_PUBLIC_URL")), file=sys.stderr)
    return 0


def _example_workspace(patterns: list[str], name: str) -> str | None:
    """The workspace to put in a client's URL: None when the token's one workspace is the default."""
    if len(patterns) == 1 and not any(c in patterns[0] for c in "*?") and patterns[0] != ROOT_WS:
        return None
    p = next((p for p in patterns if p not in ("*", ROOT_WS)), None)
    return (p.replace("*", "1").replace("?", "x") if p else f"{name}-1")


def client_config(name: str, tok: str, patterns: list[str], url: str | None) -> str:
    """What to paste into an MCP client for this token (printed by `token add`, to stderr)."""
    base = (url or "https://<your-server>").rstrip("/")
    ws = _example_workspace(patterns, name)
    mcp = f"{base}/mcp" + (f"?workspace={ws}" if ws else "")
    lines = [
        f"added {name}: workspaces {', '.join(patterns)}. The token (above) is shown only this once.",
        "",
        "Connect an MCP client:",
        f"  URL     {mcp}",
        f"  Header  Authorization: Bearer {tok}",
    ]
    if ws:
        lines.append(f"  (this token may use workspaces {', '.join(patterns)}; ?workspace= picks one)")
    if not url:
        lines.append("  (replace https://<your-server>: pass --url or set B123D_PRINT_PUBLIC_URL)")
    lines += [
        "",
        "Claude Code, in the project folder (--scope project keeps the token out of ~/.claude.json,",
        "which other agent tools import):",
        f'  claude mcp add --scope project --transport http b123d-print "{mcp}" --header "Authorization: Bearer {tok}"',
        "",
        "OpenCode (opencode.json; its own format: \"mcp\" and \"type\": \"remote\"):",
        '  {"$schema": "https://opencode.ai/config.json", "mcp": {"b123d-print": {"type": "remote",',
        '    "url": "' + mcp + '", "enabled": true, "oauth": false, "timeout": 30000,',
        '    "headers": {"Authorization": "Bearer ' + tok + '"}}}}',
        "",
        "Antigravity (agy, IDE; ~/.gemini/config/mcp_config.json or the project's .agents/plugins/):",
        '  {"mcpServers": {"b123d-print": {"serverUrl": "' + mcp + '",',
        '    "headers": {"Authorization": "Bearer ' + tok + '"}}}}',
        "",
        "Codex (~/.codex/config.toml; the token from an environment variable, export B123D_TOKEN=<token>):",
        "  [mcp_servers.b123d-print]",
        f'  url = "{mcp}"',
        '  bearer_token_env_var = "B123D_TOKEN"',
        "  tool_timeout_sec = 300",
        "",
        "Qwen Code (~/.qwen/settings.json or the project's .qwen/settings.json):",
        '  {"mcpServers": {"b123d-print": {"httpUrl": "' + mcp + '",',
        '    "headers": {"Authorization": "Bearer ' + tok + '"}, "timeout": 300000}}}',
        "",
        "Grok Build (xAI grok CLI):",
        f'  grok mcp add --transport http b123d-print "{mcp}" --header "Authorization: Bearer {tok}"',
        "",
        "Other clients (Cursor, VS Code, ...; key names vary):",
        '  {"mcpServers": {"b123d-print": {"type": "http", "url": "' + mcp + '",',
        '    "headers": {"Authorization": "Bearer ' + tok + '"}}}}',
        "",
        "More: https://kd5ryn.github.io/b123d-print/getting-started/mcp-clients/",
        "",
        f"Revoke it with: b123d-print-mcp token revoke {name}",
    ]
    return "\n".join(lines)
