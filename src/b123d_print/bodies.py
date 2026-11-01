"""Multi-body parts: several bodies that print together as one object, for multi-colour prints
(a text or logo inlay on an AMS / MMU printer; issue #167).

A part script declares them with `bodies(...)`, as a single part, a dict value or a lazy piece:

    return bodies(base=plate - letters, inlay=(letters, "white"))

Each keyword is a body, in order; its value is a shape, or (shape, colour) with any build123d
Color argument (a name, "#rrggbb", an RGB(A) tuple). The result is a plain build123d Compound
whose children carry the names (`label`) and colours, so it survives Rot/Pos, the build cache and
STEP. A piece is multi-body when it is a Compound with two or more labelled children (`split`).

The bodies print as one: the printability checks run on their union (`printable`), the `Bodies`
check (checks.py) fails on bodies that overlap and warns on one touching no other. Exports: the
3MF holds one object with a named, coloured part per body; STEP a labelled Compound; STL the
union plus one file per body; renders draw each body in its colour.
"""

from __future__ import annotations

import re

NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")  # a body name is also a file name suffix (STL)


def bodies(**named):
    """A multi-body part: {name: shape | (shape, colour)} -> a Compound with labelled, coloured
    children in keyword order. A body without a colour gets the next render palette colour."""
    from build123d import Color, Compound, Shape

    from .render import PALETTE

    if len(named) < 2:
        raise ValueError(f"bodies() takes two or more bodies (name=shape or name=(shape, colour)), got {len(named)}")
    children = []
    for i, (name, v) in enumerate(named.items()):
        if not NAME.match(name):
            raise ValueError(f"body name {name!r}: letters, digits, _ and - only (it names the body's STL file)")
        shape, color = (v[0], v[1]) if isinstance(v, (list, tuple)) and len(v) == 2 and isinstance(v[0], Shape) else (v, None)
        if not isinstance(shape, Shape) or shape.volume <= 0:
            raise ValueError(f"body {name!r} must be a solid shape with volume, got {type(shape).__name__}")
        if color is None:
            color = PALETTE[i % len(PALETTE)]
        try:
            color = color if isinstance(color, Color) else Color(*color) if isinstance(color, (list, tuple)) else Color(color)
        except Exception as e:  # noqa: BLE001 - say which body and what Color takes
            raise ValueError(f"body {name!r}: colour {color!r} is not a build123d Color ({e})") from None
        body = _copy(shape)
        body.label, body.color = name, color
        children.append(body)
    return Compound(children=children)


def _copy(shape):
    """A new shape on the same geometry, so the label and colour stay off the caller's own shape."""
    import copy

    return copy.copy(shape)


def split(shape) -> list[tuple] | None:
    """[(body, Color, name)] of a multi-body part, in order; None for any other shape."""
    from build123d import Compound

    if not isinstance(shape, Compound):
        return None
    kids = list(getattr(shape, "children", ()) or ())
    if len(kids) < 2 or not all(getattr(k, "label", "") for k in kids):
        return None
    return [(k, k.color, k.label) for k in kids]


_UNION: dict = {}  # id(shape) -> (shape, union): the last few multi-body parts fused


def printable(shape):
    """What prints: the union of a multi-body part's bodies (one Part), any other shape as it is."""
    parts = split(shape)
    if parts is None:
        return shape
    hit = _UNION.get(id(shape))
    if hit is not None and hit[0] is shape:
        return hit[1]
    from build123d import Compound, Part

    first, *rest = (b for b, _, _ in parts)
    union = Part(Compound(first.fuse(*rest).clean().solids()).wrapped)
    if len(_UNION) >= 16:
        _UNION.pop(next(iter(_UNION)))
    _UNION[id(shape)] = (shape, union)
    return union


def expand(items) -> list[tuple]:
    """[(part, color, label)] with each multi-body part replaced by its bodies, in their own
    colours (an RGBA tuple) and labelled by body name ("<label> <body>" when the part has a label)."""
    out = []
    for part, color, label in items:
        got = split(part)
        if got is None:
            out.append((part, color, label))
            continue
        for body, c, name in got:
            out.append((body, tuple(c) if c is not None else color, f"{label} {name}" if label else name))
    return out


def stl_files(shape, name: str) -> list[tuple[str, object]]:
    """[(file name, shape)] the STL format writes: <name>.stl (the union of a multi-body part, for
    a one-colour print) and <name>_<body>.stl per body (to load together as parts)."""
    files = [(f"{name}.stl", printable(shape))]
    files += [(f"{name}_{n}.stl", b) for b, _, n in split(shape) or ()]
    return files


def color_name(c) -> str:
    """'#rrggbb' of a build123d Color (with alpha when not opaque)."""
    r, g, b, a = (max(0, min(255, round(x * 255))) for x in tuple(c))
    return f"#{r:02x}{g:02x}{b:02x}" + (f"{a:02x}" if a < 255 else "")
