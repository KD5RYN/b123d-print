"""Print intent: what a part script says about how it must be printed (issue #115).

The print sheet's advice (supports, walls, infill, brim) is inferred from the geometry and the
style, and cannot know intent: a calibration coupon that tests unsupported holes would be told to
use supports. A script states its intent with a `PRINT` mapping, at module level or as a `Dims`
field (so a variant can override it, like PRINT_NOTES):

    PRINT = {"supports": "none", "why": "the coupon measures holes printed without supports"}

The vocabulary is fixed (KEYS) and validated; `why` is required whenever anything is set. Intent
overrides the recommendation, never the facts: the sheet still lists the faces that would need
supports, and the overhang check still reports them, as accepted instead of a warning. It never
turns a FAIL into a pass.

Every recommendation names its source (resolve): the part script, then your settings (the
workspace b123d-print.toml, then the user config: `supports`, `walls`, `infill`), then the
suggestion from the geometry and style.
"""

from __future__ import annotations

from collections.abc import Mapping

SUPPORTS = ("none", "auto", "build_plate_only", "tree")
ORIENTATIONS = ("locked",)
REVIEWS = ("exempt",)
KEYS = {  # key -> what it takes (for the error message)
    "supports": " | ".join(f'"{s}"' for s in SUPPORTS),
    "walls": "an int (perimeters)",
    "infill": "a percent, 0-100",
    "infill_pattern": "a string, e.g. \"gyroid\"",
    "brim": "true / false, or a width in mm",
    "orientation": '"locked" (don\'t re-orient)',
    "review": '"exempt" (a calibration coupon or test print: no design review checklist, review.py)',
    "vase": "true / false: print in vase mode (spiral vase / spiralize: one continuous wall, no top, no infill)",
    "why": "free text, required whenever anything else is set",
}
PART, SETTINGS, SUGGESTED = "set by the part", "your settings", "suggested from the geometry/style"


def _keys_help() -> str:
    return "; ".join(f"{k}: {v}" for k, v in KEYS.items())


def validate(value, where: str = "PRINT") -> dict:
    """The PRINT mapping checked and normalized ({} for None or empty). Raises ValueError naming the
    bad key or value and listing the valid keys."""
    if value in (None, {}, ()):
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"{where} must be a dict, got {type(value).__name__}; keys: {_keys_help()}")
    unknown = sorted(set(value) - set(KEYS))
    if unknown:
        raise ValueError(f"{where}: unknown key(s) {unknown}; valid keys: {_keys_help()}")
    out: dict = {}
    for k, v in value.items():
        bad = ValueError(f"{where}[{k!r}] = {v!r}: {k} takes {KEYS[k]}")
        if k == "supports":
            v = str(v).strip().lower().replace("-", "_").replace(" ", "_")
            if v not in SUPPORTS:
                raise bad
        elif k == "walls":
            if isinstance(v, bool) or not isinstance(v, int) or v < 1:
                raise bad
        elif k == "infill":
            if isinstance(v, bool) or not isinstance(v, (int, float)) or not 0 <= v <= 100:
                raise bad
            v = float(v)
        elif k == "brim":
            if not isinstance(v, (bool, int, float)) or (not isinstance(v, bool) and v < 0):
                raise bad
            v = v if isinstance(v, bool) else float(v)
        elif k == "orientation":
            if v not in ORIENTATIONS:
                raise bad
        elif k == "review":
            if v not in REVIEWS:
                raise bad
        elif k == "vase":
            if not isinstance(v, bool):
                raise bad
        elif k in ("infill_pattern", "why"):
            if not isinstance(v, str) or not v.strip():
                raise bad
            v = v.strip()
        out[k] = v
    clash = sorted({"walls", "infill", "infill_pattern"} & set(out)) + (["supports"] if out.get("supports", "none") != "none" else [])
    if out.get("vase") and clash:
        raise ValueError(f"{where}: vase mode prints one wall, no infill and no supports; drop {clash} or 'vase'")
    if set(out) - {"why"} and "why" not in out:
        raise ValueError(f"{where}: say why with a 'why' key (sets {sorted(out)}): the print sheet and the "
                         "checks show it next to every setting the part overrides")
    return out


def declared(mod, d) -> dict:
    """The script's PRINT (Dims field first, so a variant can override it; else module level), validated."""
    from .metrics import script_attr

    return validate(script_attr(mod, d, "PRINT", None))


def resolve(mod, d, settings) -> dict:
    """{key: (value, source)} for supports, walls, infill and brim (and the other declared keys):
    the part's PRINT, else your settings (workspace, then user config), else absent (the sheet
    then suggests from the geometry and style). `why` is the part's reason, or ""."""
    part = declared(mod, d)
    out = {k: (v, PART) for k, v in part.items() if k != "why"}
    for k in ("supports", "walls", "infill"):
        v = getattr(settings, k, None)
        if k not in out and v not in (None, "", 0):
            out[k] = (v, SETTINGS)
    out["why"] = (part.get("why", ""), PART)
    return out


def no_supports_why(mod, d) -> str:
    """The part's why when it declares supports "none" (the overhang check accepts its overhangs), else ""."""
    p = declared(mod, d)
    return p["why"] if p.get("supports") == "none" else ""


def supports_label(v: str) -> str:
    return {"none": "none", "auto": "auto (normal)", "build_plate_only": "on build plate only", "tree": "tree"}[v]
