"""The review checklist (issue #146): which design steps ran on this version of a part script.

Models forget the style, the design review and the orientation step and go straight to export;
static instructions get skimmed, but the result of the tool just called gets read. So the MCP
server records, per part and per version of its script (the hash of its bytes), what ran:

    style    the part's style is settled: the script's STYLE, the `style` setting, or an explicit
             design_metrics(style=...)
    check    the last check of this version, passed or failed
    look     render_preview and a section were taken
    metrics  design_metrics ran, and with which style
    orient   suggest_orientation ran (or the script's PRINT locks the orientation)

and build_part, check, design_metrics and export end with one short block (block()): the steps
still missing, each with the exact call to make. Any edit (write_part, set_params, a restore)
changes the hash, so the new version starts with an empty checklist. A part whose PRINT intent
says `"review": "exempt"` (the calibration coupons) gets no block and no export notice.

export follows the `review` setting (workspace b123d-print.toml, else the user config): "warn"
(the default) exports and says what was skipped, in the result and on the print sheet;
"required" refuses until the steps are done, unless called with skip_review="<the user's
reason>", which the print sheet records; "off" is the behaviour before 0.3.15.

The state is out/.cache/review.json next to the build cache: the same locally, over HTTP (each
workspace has its own parts) and over SSH, it survives a server restart, and download_part never
sends out/.cache/. The sandboxed part script can write out/, so the file is read with a size cap
and written only where out/ and out/.cache/ are what they look like (never through a link).
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path

MODES = ("warn", "required", "off")
STATE_FILE = "review.json"
MAX_BYTES = 64_000  # the file is small; a bigger one was not written by the server
KEEP = 5  # versions remembered per part (a restore of a recent version finds its steps again)
STYLES = "functional, modern, least_cost, rugged, soft, structural, organic"


def script_hash(script: Path) -> str:
    return hashlib.sha256(Path(script).read_bytes()).hexdigest()[:16]


def _cache_dir(script: Path, make: bool = False) -> Path | None:
    """<part>/out/.cache, or None when out/ or out/.cache/ is a link (or out/ is missing and not made)."""
    folder = Path(os.path.realpath(Path(script).parent))
    out, cache = folder / "out", folder / "out" / ".cache"
    if make:
        try:
            cache.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
    if not cache.is_dir():
        return None
    if os.path.islink(out) or os.path.islink(cache) or os.path.normcase(os.path.realpath(cache)) != os.path.normcase(str(cache)):
        return None
    return cache


def _read_all(script: Path) -> dict:
    d = _cache_dir(script)
    if d is None:
        return {}
    p = d / STATE_FILE
    try:
        if os.path.islink(p) or p.stat().st_size > MAX_BYTES:
            return {}
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) and isinstance(raw.get("versions"), dict) else {}


def steps(script: Path) -> dict:
    """The steps recorded for the script as it is now ({} for a new or edited version)."""
    got = _read_all(script).get("versions", {}).get(script_hash(script), {})
    return got if isinstance(got, dict) else {}


def record(script: Path, step: str, version: str | None = None, **info) -> None:
    """Record that `step` ran on the script as it is now (info: its outcome). version: the hash
    the step ran on (taken before it ran); nothing is recorded when the script changed since.
    Never fails a tool."""
    try:
        h = script_hash(script)
        if version is not None and version != h:
            return
        d = _cache_dir(script, make=True)
        if d is None:
            return
        raw = _read_all(script)
        versions = {k: v for k, v in raw.get("versions", {}).items() if isinstance(v, dict)}
        cur = versions.pop(h, {})  # re-inserted last: the most recent version
        cur[step] = info
        versions[h] = cur
        versions = dict(list(versions.items())[-KEEP:])
        tmp = d / f".{STATE_FILE}.{os.getpid()}.tmp"
        if os.path.lexists(tmp):
            os.unlink(tmp)
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o644)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"versions": versions}, f)
        os.replace(tmp, d / STATE_FILE)  # replaces a link itself, never its target
    except OSError:
        pass


# --- what the script declares, read without running it (the server is outside the sandbox) ----

@dataclass(frozen=True)
class Declared:
    style: str = ""  # the script's STYLE ("" = not set)
    style_field: bool = False  # Dims has a STYLE field with a literal default (set_params can change it)
    exempt: str = ""  # PRINT["review"] == "exempt": its why
    locked: bool = False  # PRINT["orientation"] == "locked"


def declared(src: str) -> Declared:
    try:
        tree = ast.parse(src)
    except (SyntaxError, ValueError):
        return Declared()
    style, field, intent = "", False, {}
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Dims":
            for n in node.body:
                if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "STYLE":
                    v = _literal(n.value)
                    if isinstance(v, str):
                        field, style = True, style or v.strip()
                elif isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name) and n.target.id == "PRINT":
                    v = _literal(_default(n.value))
                    intent = v if isinstance(v, dict) else intent
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name, v = node.targets[0].id, _literal(node.value)
            if name == "STYLE" and isinstance(v, str) and v.strip():
                style = style or v.strip()
            elif name == "PRINT" and isinstance(v, dict) and not intent:
                intent = v
    exempt = str(intent.get("why") or "exempt") if intent.get("review") == "exempt" else ""
    return Declared(style, field, exempt, intent.get("orientation") == "locked")


def _default(node):
    """field(default_factory=lambda: {...}) -> the dict node; anything else as it is."""
    if isinstance(node, ast.Call):
        for kw in node.keywords:
            if kw.arg == "default_factory" and isinstance(kw.value, ast.Lambda):
                return kw.value.body
            if kw.arg == "default":
                return kw.value
    return node


def _literal(node):
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return None


# --- the checklist ----------------------------------------------------------------------------

@dataclass(frozen=True)
class Item:
    key: str
    done: bool
    text: str  # "check passed (this version)" / "design review not run"
    call: str = ""  # the exact next call, only on a missing step


@dataclass(frozen=True)
class Checklist:
    name: str
    style: str  # the style the review should use ("" = not chosen yet)
    style_source: str
    items: tuple[Item, ...]
    exempt: str = ""

    @property
    def missing(self) -> list[Item]:
        return [i for i in self.items if not i.done]

    def block(self) -> str:
        """The block that ends a result: the missing steps with their calls, or one "Ready" line."""
        if self.exempt:
            return ""
        style = self.style or "not chosen"
        if not self.missing:
            return (f"Ready to print {self.name} (style: {style}): check passed, preview and section looked at, "
                    "design review and orientation done on this version.")
        lines = [f"Before printing {self.name} (style: {style}):"]
        for i in self.items:
            lines.append(f"  ✓ {i.text}" if i.done else f"  ✗ {i.text}: {i.call}")
        return "\n".join(lines)

    def short(self) -> str:
        """The block when it was shown unchanged before: just the next call."""
        if self.exempt:
            return ""
        if not self.missing:
            return f"Ready to print {self.name}."
        n = len(self.missing)
        return f"Before printing {self.name}: {n} step{'s' if n > 1 else ''} left; next: {self.missing[0].call}"

    def skipped(self) -> str:
        """The missing steps as one phrase: "the design review (design_metrics), the orientation check (...)"."""
        return ", ".join(SKIPPED[i.key] for i in self.missing)


SKIPPED = {"style": "a chosen style", "check": "a passing check", "look": "the preview and a section",
           "metrics": "the design review (design_metrics)", "orient": "the orientation check (suggest_orientation)"}


def checklist(name: str, script: Path, settings) -> Checklist:
    """The checklist of the part `name` as its script is now. settings: the workspace's (for the
    default style)."""
    dec = declared(Path(script).read_bytes().decode("utf-8", errors="replace"))
    done = steps(script)
    q = f"'{name}'"
    metrics = done.get("metrics") or {}
    style, source = "", ""
    if dec.style:
        style, source = dec.style, "the script's STYLE"
    elif getattr(settings, "style", ""):
        style, source = settings.style, "the workspace default"
    elif metrics.get("explicit") and metrics.get("style"):
        style, source = metrics["style"], "chosen with design_metrics"
    try:
        from .styles import normalize

        style = normalize(style) if style else ""
    except ValueError:
        pass
    items = []
    if style:
        items.append(Item("style", True, f"style: {style} ({source})"))
    else:
        how = (f"set_params({q}, {{'STYLE': '<style>'}})" if dec.style_field else
               "add STYLE: str = '<style>' to Dims with write_part")
        items.append(Item("style", False, "no style chosen",
                          f"ask the user which style ({STYLES}; list_parts shows the workspace's), then {how}"))
    chk = done.get("check")
    if chk is None:
        items.append(Item("check", False, "check not run on this version", f"check({q})"))
    elif not chk.get("passed"):
        items.append(Item("check", False, "check FAILED on this version", f"fix every FAIL, then check({q})"))
    else:
        items.append(Item("check", True, "check passed (this version)"))
    look = [s for s in ("preview", "section") if s not in done]
    calls = {"preview": f"render_preview({q})", "section": f"section({q}, 'XY', <a height through the holes and pockets>)"}
    if not look:
        items.append(Item("look", True, "preview and section looked at"))
    else:
        what = "not looked at" if len(look) == 2 else ("no preview rendered" if look == ["preview"] else "no section taken")
        items.append(Item("look", False, what, ", then ".join(calls[s] for s in look)))
    want = style or "<the user's style>"
    if not metrics:
        items.append(Item("metrics", False, "design review not run", f"design_metrics({q}, style='{want}')"))
    elif style and metrics.get("style") and metrics["style"] != style:
        items.append(Item("metrics", False, f"design review ran with style '{metrics['style']}', not '{style}'",
                          f"design_metrics({q}, style='{style}')"))
    else:
        items.append(Item("metrics", True, f"design review run (style: {metrics.get('style') or style})"))
    if dec.locked:
        items.append(Item("orient", True, "orientation locked by the script's PRINT"))
    elif "orient" in done:
        items.append(Item("orient", True, "orientation checked"))
    else:
        load = ", load='<bending direction, e.g. X>'" if style == "structural" else ""
        items.append(Item("orient", False, "orientation not checked", f"suggest_orientation({q}{load})"))
    return Checklist(name, style, source, tuple(items), dec.exempt)


def mode(settings) -> str:
    m = (getattr(settings, "review", "") or "warn").strip().lower()
    return m if m in MODES else "warn"


def sheet_lines(c: Checklist, skip_reason: str = "") -> list[str]:
    """The print sheet's "Design review" section (empty for an exempt part)."""
    if c.exempt:
        return []
    L = ["## Design review", ""]
    if not c.missing:
        L.append(f"Done on the exported version: style {c.style}, check passed, preview and section, "
                 "design review and orientation check.")
    else:
        L.append(f"Exported **without** {c.skipped()}." if not skip_reason else
                 f"Exported **without** {c.skipped()}. Skipped on purpose: {skip_reason}")
        L += [""] + [f"- {'done' if i.done else 'MISSING'}: {i.text}" for i in c.items]
    return L
