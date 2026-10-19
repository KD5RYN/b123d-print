"""View a part in 3D in the browser: a GLB of its pieces and a small three.js page that shows it.

    out/<name>[_<variant>]_view.glb           print layout: the printable parts on the bed, side by side
    out/<name>[_<variant>]_assembly_view.glb  assembly layout: assembly(d), stand-ins included

One node per piece, named after it, each in its own color (render.PALETTE). glTF is in meters
and Y-up; the page shows mm and the CAD axes (Z up, the bed at Z = 0).

Over HTTP the page is served at a signed link (links.sign_view), the same HMAC, workspace binding
and expiry as the downloads:  /view/<workspace>/<expires>.<sig>/<part>/<stem>  serves the page,
.../<stem>.glb  the model, and /view-assets/<file> the page's static files (fixed names from the
package, no token: they hold nothing of anyone's). The page is the same static file for every
part: nothing from the request or the model is written into it, so nothing can be injected.

Locally (`b123d-print view`, or export over stdio) the page is one self-contained HTML file next
to the GLB (offline_html): viewer and model inline, a CSP that allows exactly those inline
scripts (by hash) and no network at all, so it works from file:// without a server.

The viewer library is three.js (MIT), vendored as data/viewer/three.bundle.min.js by
tools/vendor_viewer.py; its license notice is at the top of that file and so in every copy,
the offline HTML included.
"""

from __future__ import annotations

import base64
import hashlib
import html
import json
from functools import lru_cache
from importlib.metadata import version as _dist_version
from importlib.resources import files
from pathlib import Path

ASSETS = {  # /view-assets/<name>: the only files served there
    "viewer.js": "text/javascript; charset=utf-8",
    "viewer.css": "text/css; charset=utf-8",
    "three.bundle.min.js": "text/javascript; charset=utf-8",
    "three-LICENSE.txt": "text/plain; charset=utf-8",
}
ASSET_PREFIX = "../../../../view-assets/"  # from /view/<ws>/<token>/<part>/<stem>, also under a --public-url prefix
GLB_MIME = "model/gltf-binary"

# the served page: scripts and styles from this server only, the model fetched from it, nothing else
CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
PAGE_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cache-Control": "private, no-store",
}
MODEL_HEADERS = {"X-Content-Type-Options": "nosniff", "Cross-Origin-Resource-Policy": "same-origin",
                 "Cache-Control": "private, no-store", "Content-Security-Policy": "default-src 'none'; sandbox"}
ASSET_HEADERS = {"X-Content-Type-Options": "nosniff", "Cross-Origin-Resource-Policy": "same-origin",
                 "Cache-Control": "public, max-age=3600"}
LAYOUTS = ("print", "assembly")


def stem(tag: str, layout: str = "print") -> str:
    """The file stem of a view: <tag>_view (print) or <tag>_assembly_view."""
    return f"{tag}_view" if layout == "print" else f"{tag}_assembly_view"


def parse_layout(value) -> str | None:
    """export's `view`: 'print' (default) or 'assembly'; 'none' / '' / False: no view."""
    v = str(value).strip().lower() if value not in (None, True) else "print"
    if v in ("", "none", "no", "false", "off", "0"):
        return None
    if v in ("true", "yes", "on", "1"):
        return "print"
    if v not in LAYOUTS:
        raise ValueError(f"view: 'print' (the parts on the bed), 'assembly' or 'none', got {value!r}")
    return v


# ---------------------------------------------------------------------------------------------
# the model (runs in the worker, next to the part script)


def write_glb(items, path: Path) -> Path:
    """[(part, color or None, label)] -> one GLB with a named, colored node per piece."""
    import matplotlib.colors
    from build123d import Color, Compound, export_gltf

    from .render import PALETTE

    children, diag = [], 1.0
    for i, (part, color, label) in enumerate(items):
        piece = Compound(part.solids())  # a new shape (placed solids): labels and colors stay off the script's own
        r, g, b, a = matplotlib.colors.to_rgba(color if color is not None else PALETTE[i % len(PALETTE)])
        piece.color = Color(r, g, b, a)
        piece.label = str(label or f"piece {i + 1}")
        children.append(piece)
        bb = part.bounding_box()
        diag = max(diag, bb.diagonal)
    path.parent.mkdir(parents=True, exist_ok=True)
    tol = min(0.2, max(0.01, diag * 5e-4))  # fine enough to read fillets and holes, small enough to send
    export_gltf(Compound(children=children), str(path), binary=True, linear_deflection=tol, angular_deflection=0.2)
    return path


def view_items(mod, d, layout: str = "print", parts: list[str] | None = None) -> list:
    """What a view shows: the printable parts on the bed (side by side, as render_preview lays
    them out), only `parts` if given; or the assembly with its stand-ins."""
    from .project import assembly, printables
    from .render import side_by_side

    if layout == "assembly":
        asm = assembly(mod, d)
        if not asm:
            raise ValueError("this script has no assembly(d): use view='print'")
        return asm
    named = {(k or "part"): p for k, p in printables(mod, d).items()}
    if parts:
        missing = [n for n in parts if n not in named]
        if missing:
            raise KeyError(f"no part(s) {missing}; parts: {sorted(named)}")
        named = {n: named[n] for n in parts}
    items = [(p, n) for n, p in named.items()]
    return side_by_side(items) if len(items) > 1 else [(items[0][0], None, items[0][1])]


def write_view(mod, d, tag: str, out: Path, layout: str = "print", parts: list[str] | None = None) -> Path:
    """out/<tag>_view.glb (or <tag>_assembly_view.glb) for one variant's dims `d`."""
    return write_glb(view_items(mod, d, layout, parts), out / f"{stem(tag, layout)}.glb")


# ---------------------------------------------------------------------------------------------
# the page


def _asset(name: str) -> str:
    return files("b123d_print").joinpath("data", "viewer", name).read_text(encoding="utf-8")


def asset_bytes(name: str) -> bytes:
    """A /view-assets/ file by its fixed name (KeyError for any other name)."""
    ASSETS[name]
    return files("b123d_print").joinpath("data", "viewer", name).read_bytes()


@lru_cache(maxsize=1)
def vendor() -> dict:
    return json.loads(_asset("vendor.json"))


def _fill(title: str, csp: str, style: str, model: str, scripts: str, license_link: str) -> str:
    out = _asset("viewer.html")
    for key, val in (("CSP", csp), ("TITLE", html.escape(title)), ("STYLE", style), ("MODEL", model),
                     ("VERSION", html.escape(_dist_version("b123d-print"))),
                     ("THREE_REVISION", html.escape(vendor()["package"].split("@")[1].split(".")[1])),
                     ("LICENSE_LINK", license_link), ("SCRIPTS", scripts)):
        out = out.replace("{{" + key + "}}", val)
    return out


@lru_cache(maxsize=1)
def served_page() -> bytes:
    """The page behind every /view/ link: the same bytes for every part (it reads the model's
    name from its own URL), so no request or model data is ever written into it."""
    p = ASSET_PREFIX
    return _fill("3D view", "", f'<link rel="stylesheet" href="{p}viewer.css">', "",
                 f'<script src="{p}three.bundle.min.js"></script>\n<script src="{p}viewer.js"></script>',
                 f', <a href="{p}three-LICENSE.txt">license</a>').encode()


def _inline_safe(code: str, what: str) -> str:
    low = code.lower()
    if "</script" in low or "<!--" in low or "<script" in low:
        raise ValueError(f"{what} cannot be inlined in a <script> element")
    return code


def _sha(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode()).digest()).decode() + "'"


def offline_html(glb: bytes, title: str) -> str:
    """One self-contained page: the viewer, three.js (with its license notice) and the model
    (base64, in a data block that never runs). Its CSP allows exactly these inline scripts and
    styles by hash and no network, so it works from file:// and fetches nothing."""
    three = _inline_safe(_asset("three.bundle.min.js"), "three.bundle.min.js")
    js = _inline_safe(_asset("viewer.js"), "viewer.js")
    css = _asset("viewer.css")
    if "</style" in css.lower():
        raise ValueError("viewer.css cannot be inlined")
    csp = (f"default-src 'none'; script-src {_sha(three)} {_sha(js)}; style-src {_sha(css)}; img-src blob: data:; "
           "connect-src 'none'; base-uri 'none'; form-action 'none'")
    model = (f'<script type="application/octet-stream" id="b123d-model">'
             f'{base64.b64encode(glb).decode()}</script>')  # base64: nothing in it can close the element
    return _fill(title, f'<meta http-equiv="Content-Security-Policy" content="{html.escape(csp, quote=False)}">',
                 f"<style>{css}</style>", model, f"<script>{three}</script>\n<script>{js}</script>", "")


def write_offline(glb_path: Path, title: str | None = None) -> Path:
    """<stem>.html next to <stem>.glb (the offline page); returns its path."""
    out = glb_path.with_suffix(".html")
    name = title or glb_path.stem.removesuffix("_view")
    out.write_text(offline_html(glb_path.read_bytes(), name), encoding="utf-8", newline="\n")
    return out
