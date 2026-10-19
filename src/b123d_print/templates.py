"""Fit-test templates: a quick thin print taken from the real part, to check its size, hole pattern
and mating fits before printing the whole part.

Three kinds, each cut from the part as built (so hole compensation and clearances are exactly the
part's):

    slice_template(part, "XY", 3.0)            # the part between two planes, `thickness` apart
    face_template(part, 7)                     # one flat face (with its holes), as a thin plate
    crop_template(part, (x, y, z), (sx, sy, sz))  # the part inside a box, with a flat base if needed

Each is laid flat on the bed (template face down, Z=0, centered on X/Y), gets an engraved label
where there is room for one, and is validated: a valid, non-empty solid; a plane or box that misses
the part is a TemplateError that says where the part is.

list_faces(part) lists the flat faces with stable ids (the same geometry always gets the same ids),
their normal, area, center, box and round holes, for picking a face; highlight() draws the part
with a face or a template's source region in color, to confirm the choice with the user.

A part script can list standard templates in `templates(d)` (like views(d)); export writes them
with every variant as <name>[_<variant>]_template_<id>.*:

    def templates(d):
        return [Template.face_of("bottom"), Template.slice("XY", d.FLOOR_T + 1)]
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from build123d import Align, Box, Compound, Face, FontStyle, Location, Part, Pos, Text, Vector, Wire, extrude

THICKNESS = 1.2  # mm: default template thickness (six 0.2 mm layers; stiff enough to handle, quick to print)
BASE_T = 1.0  # mm: the flat base plate that joins the pieces of a slice or crop (at least min_wall)
LABEL_SIZE = 5.0  # mm: character height (BP-X1: at least ~5 mm, bold sans-serif)
LABEL_DEPTH = 0.5  # mm: engraving depth (BP-X1: at least 0.5 mm)
LABEL_FLOOR = 0.4  # mm: at least this much material left under the engraving (two layers)
LABEL_MARGIN = 1.0  # mm: clear material around the label (never next to a hole or an edge)
CONTACT_MIN = 0.2  # bed contact below this share of the footprint gets a base plate (crop)
EPS = 1e-6
AXES = {"XY": 2, "XZ": 1, "YZ": 0}
SIDES = {"bottom": (0, 0, -1), "top": (0, 0, 1), "front": (0, -1, 0), "back": (0, 1, 0),
         "left": (-1, 0, 0), "right": (1, 0, 0)}
DIRS = {"-Z": "bottom", "+Z": "top", "-Y": "front", "+Y": "back", "-X": "left", "+X": "right"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")


class TemplateError(ValueError):
    pass


@dataclass
class Template:
    """A fit-test template a part script lists in templates(d); export writes it with every
    variant. kind: "slice" (plane + at), "face" (face) or "crop" (center + size). part: which
    printable part (default: the only one). label: engrave "<part> <id>" (True), a text of your
    own, or nothing (False). name: the template id in file names (default: from the arguments).
    Use the constructors: Template.slice("XY", 3), Template.face_of("bottom"), Template.crop(...)."""

    kind: str
    plane: str = "XY"  # slice: XY (at = Z), XZ (at = Y), YZ (at = X)
    at: float = 0.0
    face: int | str | tuple | None = None  # face: an id from list_faces, a side ("bottom", "-Z", ...) or a point on it
    center: tuple = (0.0, 0.0, 0.0)  # crop: the box's center ...
    size: tuple = (20.0, 20.0, 10.0)  # ... and size (mm)
    thickness: float = THICKNESS
    label: bool | str = True
    base: bool = True  # slice/crop: join separate pieces (and a crop with little bed contact) with a thin base plate
    part: str | None = None
    name: str = ""

    @classmethod
    def slice(cls, plane: str, at: float, **kw) -> Template:
        return cls("slice", plane=plane, at=at, **kw)

    @classmethod
    def face_of(cls, face, **kw) -> Template:
        return cls("face", face=face, **kw)

    @classmethod
    def crop(cls, center, size, **kw) -> Template:
        return cls("crop", center=tuple(center), size=tuple(size), **kw)

    def ident(self) -> str:
        """The id in file names: xy3, face7, face_bottom, crop_10_0_5 (or `name`)."""
        if self.name:
            if not ID_RE.match(self.name):
                raise TemplateError(f"template name {self.name!r}: lower case letters, digits, '_', '-', '.'")
            return self.name
        if self.kind == "slice":
            return f"{self.plane.lower()}{_num(self.at)}"
        if self.kind == "face":
            f = self.face
            if isinstance(f, (int, np.integer)) and not isinstance(f, bool):
                return f"face{int(f)}"
            if isinstance(f, str):
                return f"face_{_side_name(f)}"
            return "face_" + "_".join(_num(v) for v in f)
        if self.kind == "crop":
            return "crop_" + "_".join(_num(v) for v in self.center)
        raise TemplateError(f"template kind {self.kind!r}: slice, face or crop")


@dataclass
class Made:
    """A template as made: `part` laid flat for printing, `where` the same piece in the part's
    own coordinates (before the base plate and label), `info` what was done, `ignore` the regions
    the thin-feature check skips (the label's engraving)."""

    part: Part
    where: Part
    info: dict
    ignore: list = field(default_factory=list)


def _num(v: float) -> str:
    s = f"{round(float(v), 3):g}"
    return "0" if s == "-0" else s


def _side_name(s: str) -> str:
    k = s.strip()
    if k.upper() in DIRS:
        return DIRS[k.upper()]
    if k.lower() in SIDES:
        return k.lower()
    raise TemplateError(f"face side {s!r}: one of {', '.join(SIDES)} or {', '.join(DIRS)}")


# ---------------------------------------------------------------------------------------------
# faces


def _vec(v) -> np.ndarray:
    return np.array([v.X, v.Y, v.Z], dtype=float)


def _round_holes(face: Face) -> tuple[list[dict], int]:
    """Round holes in a flat face (inner wires made only of circle arcs with one center and
    radius): [{"d", "center"}], and the number of other openings."""
    holes, other = [], 0
    for w in face.inner_wires():
        edges = w.edges()
        if edges and all(e.geom_type.name == "CIRCLE" for e in edges):
            rs = {round(e.radius, 4) for e in edges}
            cs = {tuple(np.round(_vec(e.arc_center), 3)) for e in edges}
            if len(rs) == 1 and len(cs) == 1:
                holes.append({"d": round(2 * rs.pop(), 3), "center": [round(float(x), 3) + 0.0 for x in cs.pop()]})
                continue
        other += 1
    holes.sort(key=lambda h: (h["center"][2], h["center"][1], h["center"][0], h["d"]))
    return holes, other


def _planar(part: Part) -> list[Face]:
    """The flat faces in id order: largest first, then by normal and center (rounded, so the same
    geometry rebuilt gets the same order)."""
    def key(f):
        n = np.round(_vec(f.normal_at(f.center())), 3) + 0.0
        c = np.round(_vec(f.center()), 2) + 0.0
        return (-round(f.area, 1), *n[[2, 1, 0]], *c[[2, 1, 0]])  # equal areas: bottom first, then front, left

    return sorted((f for f in part.faces() if f.geom_type.name == "PLANE"), key=key)


def list_faces(part: Part) -> dict:
    """The part's flat faces with stable ids (1 = the largest), each with its outward normal,
    area (mm^2), center, bounding box, round holes (diameter and center) and other openings;
    curved faces are only counted by type. Ids stay the same when the same geometry is rebuilt;
    they change when the geometry changes."""
    out = []
    for i, f in enumerate(_planar(part), 1):
        bb = f.bounding_box()
        n = _vec(f.normal_at(f.center()))
        holes, other = _round_holes(f)
        side = next((name for name, d in SIDES.items() if np.dot(n, d) > 0.9999), None)
        out.append({"id": i, "normal": [round(float(x), 3) + 0.0 for x in n], **({"side": side} if side else {}),
                    "area": round(f.area, 2), "center": [round(float(x), 3) + 0.0 for x in _vec(f.center())],
                    "bbox": {"min": [round(v, 3) for v in (bb.min.X, bb.min.Y, bb.min.Z)],
                             "max": [round(v, 3) for v in (bb.max.X, bb.max.Y, bb.max.Z)]},
                    "holes": holes, **({"other_openings": other} if other else {})})
    curved: dict[str, int] = {}
    for f in part.faces():
        if f.geom_type.name != "PLANE":
            curved[f.geom_type.name.lower()] = curved.get(f.geom_type.name.lower(), 0) + 1
    return {"planar": out, "curved": curved, "faces": len(part.faces())}


def find_face(part: Part, face) -> tuple[Face, int]:
    """A flat face of `part` and its id, from an id (list_faces), a side ("bottom", "-Z", ...: the
    largest flat face facing that way; of equal ones the outermost), or a point (x, y, z) on it."""
    faces = _planar(part)
    if not faces:
        raise TemplateError("the part has no flat faces")
    if isinstance(face, Face):
        c = _vec(face.center())
        for i, f in enumerate(faces, 1):
            if np.allclose(_vec(f.center()), c, atol=1e-6) and abs(f.area - face.area) < 1e-6:
                return f, i
        if face.geom_type.name != "PLANE":
            raise TemplateError("the face is not flat")
        return face, 0
    if isinstance(face, str) and face.strip().lstrip("-+").isdigit():
        face = int(face)
    if isinstance(face, (int, np.integer)) and not isinstance(face, bool):
        if not 1 <= face <= len(faces):
            raise TemplateError(f"no flat face {face}: ids are 1 to {len(faces)} (list_faces)")
        return faces[face - 1], int(face)
    if isinstance(face, str):
        d = np.array(SIDES[_side_name(face)], float)
        hits = [(i, f) for i, f in enumerate(faces, 1) if np.dot(_vec(f.normal_at(f.center())), d) > 0.9999]
        if not hits:
            raise TemplateError(f"no flat face facing {_side_name(face)} ({face}); use list_faces")
        i, f = min(hits, key=lambda h: (-round(h[1].area, 1), -float(np.dot(_vec(h[1].center()), d)), h[0]))
        return f, i
    p = np.array(face, float).reshape(3)
    best = min(((f.distance_to(Vector(*p)), i, f) for i, f in enumerate(faces, 1)), key=lambda x: (x[0], x[1]))
    if best[0] > 0.05:
        raise TemplateError(f"no flat face through {tuple(p)} (the nearest, face {best[1]}, is {best[0]:.2f} mm away)")
    return best[2], best[1]


# ---------------------------------------------------------------------------------------------
# laying flat


def _rotation(a: np.ndarray, b: np.ndarray):
    """The rotation (gp_Trsf) that turns direction a into b; a half turn about X (or Y) when they
    are opposite, so the result is the same on every run."""
    from OCP.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Quaternion, gp_Trsf, gp_Vec

    tr = gp_Trsf()
    if np.dot(a, b) < -0.999999:
        axis = (1, 0, 0) if abs(a[0]) < 0.9 else (0, 1, 0)
        tr.SetRotation(gp_Ax1(gp_Pnt(0, 0, 0), gp_Dir(*axis)), math.pi)
    elif np.dot(a, b) < 0.999999:
        tr.SetRotation(gp_Quaternion(gp_Vec(*a), gp_Vec(*b)))
    return tr


def lay_flat(shape: Part, down) -> tuple[Part, Location]:
    """`shape` turned so direction `down` points to -Z, on the bed (Z=0) and centered on X/Y.
    Returns the moved shape and the Location applied."""
    from OCP.TopLoc import TopLoc_Location

    rot = Location(TopLoc_Location(_rotation(np.asarray(down, float), np.array([0.0, 0.0, -1.0]))))
    turned = shape.moved(rot)
    bb = turned.bounding_box()
    shift = Location((-(bb.min.X + bb.max.X) / 2, -(bb.min.Y + bb.max.Y) / 2, -bb.min.Z))
    return _as_part(turned.moved(shift)), shift * rot


def _as_part(shape) -> Part:
    if isinstance(shape, Part):
        return shape
    solids = shape.solids()
    if not solids:
        return Part(Compound([]).wrapped)
    return Part(Compound(solids).wrapped)  # (Part(<a TopoDS_Solid>) reports volume 0)


def _contact(shape: Part, d: np.ndarray, tol: float = 0.01) -> tuple[float, int]:
    """Flat area facing direction d at the shape's extreme in d (what touches the bed when d points
    down), and how many of its solids reach that extreme."""
    ext = max(float(np.dot(_vec(v), d)) for v in shape.vertices())
    area = sum(f.area for f in shape.faces() if f.geom_type.name == "PLANE"
               and np.dot(_vec(f.normal_at(f.center())), d) > 0.9999 and abs(float(np.dot(_vec(f.center()), d)) - ext) < tol)
    touching = sum(1 for s in shape.solids() if max(float(np.dot(_vec(v), d)) for v in s.vertices()) > ext - tol)
    return area, touching


def _validate(shape, what: str) -> Part:
    p = _as_part(shape)
    if not p.solids() or p.volume <= EPS:
        raise TemplateError(f"{what} is empty")
    if not p.is_valid:
        raise TemplateError(f"{what} is not a valid solid (the part's geometry may be broken there; try another place)")
    return p


def _footprint_box(shape: Part) -> float:
    bb = shape.bounding_box()
    return max(bb.size.X * bb.size.Y, EPS)


def _add_base(flat: Part, base_t: float) -> tuple[Part, int]:
    """A thin plate under the whole footprint joining the pieces (the outline of its sections when
    one piece surrounds the others, else their convex hull), with
    the holes that reach the bed cut through it: an opening in the bottom outline with no other
    material inside it (a screw hole, not the inside of a box wall). The template is raised by base_t."""
    from .render import section_faces

    bb = flat.bounding_box()
    faces = section_faces(flat, "XY", min(0.05, bb.size.Z / 2))
    holes = []
    for f in faces:
        for w in f.inner_wires():
            h = Face(w)
            hb = h.bounding_box()
            inside = [g for g in faces if g is not f and _bbox_in(g.bounding_box(), hb)]
            if any(_common_area(h, g) > 1e-4 for g in inside):
                continue  # material inside: not a hole
            holes.append(h)
    levels = [min(0.05, bb.size.Z / 2)] + [bb.min.Z + bb.size.Z * k for k in (0.25, 0.5, 0.75)] + [bb.max.Z - 0.05]
    plate = extrude(_outline([g for z in levels for g in section_faces(flat, "XY", z)] or faces, bb), amount=base_t,
                    dir=(0, 0, 1))  # (a face made from a wire may face down)
    for h in holes:
        plate = plate - extrude(h.moved(Location((0, 0, -h.center().Z - 1))), amount=base_t + 2, dir=(0, 0, 1))
    up = flat.moved(Location((0, 0, base_t)))
    return _as_part(plate.fuse(up).clean()), len(holes)


def _outline(faces: list, bb) -> Face:
    """The footprint for a base plate, at Z=0, from the template's sections: the outer outline of
    the biggest piece when it holds all the others (a box wall around standoffs), else the convex
    hull of every piece (pieces side by side, a crop that widens upward), else the bounding
    rectangle."""
    from build123d import Rectangle

    filled = [Face(f.outer_wire()) for f in faces]
    if filled:
        big = max(filled, key=lambda f: f.area)
        if all(g is big or _common_area(big, g) > g.area - 1e-4 for g in filled):
            return _to_bed(big)
        try:
            hull = Face(Wire.make_convex_hull([e for f in filled for e in f.edges()]))
            if hull.is_valid and hull.area > 0:
                return _to_bed(hull)
        except Exception:  # noqa: BLE001 - fall back to the rectangle
            pass
    return Pos((bb.min.X + bb.max.X) / 2, (bb.min.Y + bb.max.Y) / 2, 0) * Rectangle(bb.size.X, bb.size.Y)


def _to_bed(f: Face) -> Face:
    return f.moved(Location((0, 0, -f.center().Z)))


def _common_area(a, b) -> float:
    c = a.intersect(b)
    return sum(f.area for f in c.faces()) if c is not None else 0.0


def _bbox_in(a, b, tol: float = 1e-6) -> bool:
    """Does box a overlap box b (in X and Y)?"""
    return a.min.X < b.max.X - tol and a.max.X > b.min.X + tol and a.min.Y < b.max.Y - tol and a.max.Y > b.min.Y + tol


# ---------------------------------------------------------------------------------------------
# the three kinds


def slice_template(part: Part, plane: str = "XY", at: float = 0.0, thickness: float = THICKNESS,
                   base: bool = True, label: str | None = None) -> Made:
    """The part between two planes `thickness` apart, centered on `at` (moved inward when `at` is
    within half a thickness of the part's end, so a slice at Z=0 is the bottom `thickness`).
    plane: XY (at = Z), XZ (at = Y), YZ (at = X). Laid flat on the side with more flat area
    (an XY slice keeps its print orientation unless the top has clearly more)."""
    plane = plane.upper()
    if plane not in AXES:
        raise TemplateError(f"plane {plane!r}: XY (at = Z), XZ (at = Y) or YZ (at = X)")
    if thickness <= 0:
        raise TemplateError("thickness must be more than 0")
    ax = AXES[plane]
    name = "XYZ"[ax]
    bb = part.bounding_box()
    lo_b, hi_b = _vec(bb.min)[ax], _vec(bb.max)[ax]
    if at < lo_b - 1e-6 or at > hi_b + 1e-6:
        raise TemplateError(f"the {plane} plane at {name}={at:g} misses the part: it spans {name} {lo_b:.2f} to {hi_b:.2f}")
    lo = at - thickness / 2
    lo = min(max(lo, lo_b), hi_b - thickness)
    lo = max(lo, lo_b)
    hi = min(lo + thickness, hi_b)
    size = _vec(bb.size) + 2.0
    size[ax] = hi - lo
    ctr = (_vec(bb.min) + _vec(bb.max)) / 2
    ctr[ax] = (lo + hi) / 2
    slab = Pos(*ctr) * Box(*size)
    cut = part & slab
    if not cut.solids() or cut.volume <= EPS:
        raise TemplateError(f"the {plane} slice {name}={lo:.2f}..{hi:.2f} holds no material (the part has a gap there)")
    piece = _validate(cut, f"the {plane} slice at {name}={at:g}")
    n = np.zeros(3)
    n[ax] = 1.0
    a_lo, _ = _contact(piece, -n)
    a_hi, _ = _contact(piece, n)
    down = -n if a_lo >= (0.8 if plane == "XY" else 1.0) * a_hi else n
    info = {"kind": "slice", "plane": plane, "at": at, "range": [round(lo, 3), round(hi, 3)], "axis": name,
            "thickness": round(hi - lo, 3)}
    return _finish(piece, down, info, base, label, base_ok=True)


def face_template(part: Part, face, thickness: float = THICKNESS, label: str | None = None) -> Made:
    """One flat face of the part, with its holes, as a plate `thickness` thick (grown into the
    part, along the face's inward normal), laid face down. face: an id from list_faces, a side
    ("bottom", "-Z", ...), a point on the face, or a build123d Face."""
    if thickness <= 0:
        raise TemplateError("thickness must be more than 0")
    f, fid = find_face(part, face)
    n = _vec(f.normal_at(f.center()))
    plate = extrude(f, amount=thickness, dir=Vector(*(-n)))
    piece = _validate(plate, f"face {fid or face}")
    holes, other = _round_holes(f)
    info = {"kind": "face", "face": fid, "normal": [round(float(x), 3) + 0.0 for x in n], "area": round(f.area, 2),
            "center": [round(float(x), 3) + 0.0 for x in _vec(f.center())], "holes": holes,
            **({"other_openings": other} if other else {}), "thickness": thickness}
    return _finish(piece, n, info, False, label)


def crop_template(part: Part, center, size, base: bool = True, label: str | None = None) -> Made:
    """The part inside a box (center, size in mm). Laid on the side with the most flat contact,
    keeping the print orientation when it has at least half as much; with `base`, a thin plate
    joins separate pieces and gives a crop with little bed contact something to stand on."""
    c = np.array(center, float).reshape(3)
    s = np.array(size, float).reshape(3)
    if (s <= 0).any():
        raise TemplateError("crop size: three lengths over 0")
    cut = part & (Pos(*c) * Box(*s))
    if not cut.solids() or cut.volume <= EPS:
        bb = part.bounding_box()
        raise TemplateError(f"the crop box at {tuple(c)} size {tuple(s)} holds no material; the part spans "
                            f"{tuple(round(v, 2) for v in _vec(bb.min))} to {tuple(round(v, 2) for v in _vec(bb.max))}")
    piece = _validate(cut, "the crop")
    pieces = len(piece.solids())
    best = None
    for k, d in enumerate(np.array([(0, 0, -1), (0, 0, 1), (0, -1, 0), (0, 1, 0), (-1, 0, 0), (1, 0, 0)], float)):
        area, touching = _contact(piece, d)
        cand = (touching == pieces, area, -k, d)
        best = cand if best is None or cand[:3] > best[:3] else best
    down = best[3]
    a_print, t_print = _contact(piece, np.array([0.0, 0.0, -1.0]))
    if (t_print == pieces) >= best[0] and a_print >= 0.5 * best[1]:
        down = np.array([0.0, 0.0, -1.0])
    info = {"kind": "crop", "center": [round(float(x), 3) for x in c], "size": [round(float(x), 3) for x in s]}
    return _finish(piece, down, info, base, label, base_ok=True)


def _finish(piece: Part, down, info: dict, base: bool, label: str | None, base_ok: bool = False) -> Made:
    down = np.asarray(down, float)
    flat, _ = lay_flat(piece, down)
    pieces = len(flat.solids())
    info["pieces"] = pieces
    info["down"] = _dir_name(down)
    info["print_orientation"] = bool(np.dot(down, (0, 0, -1)) > 0.9999)
    contact, touching = _contact(flat, np.array([0.0, 0.0, -1.0]))
    info["bed_contact_mm2"] = round(contact, 1)
    notes = []
    if base_ok and base and (pieces > 1 or contact < CONTACT_MIN * _footprint_box(flat)):
        why = f"{pieces} separate pieces" if pieces > 1 else f"only {contact:.0f} mm^2 on the bed"
        flat, _ = _add_base(flat, BASE_T)
        flat = _validate(flat, "the template with its base plate")
        info["base"] = {"thickness": BASE_T, "why": why}
        notes.append(f"a {BASE_T:g} mm base plate under it ({why}); heights measure from its top")
    elif pieces > 1:
        notes.append(f"{pieces} separate pieces: their positions relative to each other are not kept "
                     "(base=True joins them with a thin plate)")
    if touching < len(flat.solids()) and "base" not in info:
        notes.append("a piece does not reach the bed: it floats; make the crop box bigger so it connects")
    if info["down"] == "top":
        notes.append("printed turned over (the part's top side down): vertical holes stay vertical, overhangs differ")
    elif not info["print_orientation"]:
        notes.append(f"printed with the part's {info['down']} side down, not in the part's print orientation: a hole "
                     "lying on its side in the part stands up here, so check positions and spacing with it, "
                     "and hole sizes on a template printed the way the part is")
    made = Made(flat, piece, info)
    if label:
        _label(made, label)
    else:
        info["label"] = None
    bb = made.part.bounding_box()
    info["size_mm"] = [round(bb.size.X, 2), round(bb.size.Y, 2), round(bb.size.Z, 2)]
    info["volume_mm3"] = round(made.part.volume, 1)
    info["notes"] = notes + info.pop("label_notes", [])
    return made


def _dir_name(d: np.ndarray) -> str:
    for k, v in SIDES.items():
        if np.dot(d, v) > 0.9999:
            return k
    return "(" + ", ".join(f"{x:.3f}" for x in d) + ")"


# ---------------------------------------------------------------------------------------------
# the label


def _label(made: Made, text: str) -> None:
    """Engrave `text` (then a shorter form: the part after the first space) into an upward flat
    face of the template, the top first, where a box around it, LABEL_MARGIN wider, is solid from
    that face down to the floor under the engraving and clear above it: never through a feature,
    never next to a hole or an edge. No room anywhere: no label, and info says so."""
    from .render import section_faces

    t = made.part
    bb = t.bounding_box()
    depth = LABEL_DEPTH
    levels = sorted({round(f.center().Z, 4) for f in t.faces() if f.geom_type.name == "PLANE"
                     and f.normal_at(f.center()).Z > 0.9999}, reverse=True)[:4]
    texts = [text] + ([text.split(" ", 1)[1]] if " " in text else [])
    thin = False
    for txt in texts:
        sk = Text(txt, LABEL_SIZE, font_style=FontStyle.BOLD, align=(Align.CENTER, Align.CENTER))
        tb = sk.bounding_box()
        for top in levels:
            floor = top - depth - LABEL_FLOOR
            if floor <= bb.min.Z + 1e-6:
                thin = True
                continue
            upper = section_faces(t, "XY", top - 0.02)
            lower = section_faces(t, "XY", floor + 0.02)
            above = [f for z in [top + 0.02] + [lv - 0.02 for lv in levels if lv > top + 0.05] if top < bb.max.Z - 0.05
                     for f in section_faces(t, "XY", z)]
            if not upper or not lower:
                continue
            for rot in (0, 90):
                w, h = (tb.size.X, tb.size.Y) if rot == 0 else (tb.size.Y, tb.size.X)
                spot = _find_room(upper, lower, above, top, floor, w + 2 * LABEL_MARGIN, h + 2 * LABEL_MARGIN)
                if spot is None:
                    continue
                x, y = spot
                placed = Pos(x, y, top) * (sk.rotate(_z_axis(), rot) if rot else sk)
                cut = extrude(placed, amount=depth, dir=(0, 0, -1))
                made.part = _validate(t - cut, "the template with its label")
                made.info["label"] = {"text": txt, "at": [round(x, 2), round(y, 2), round(top, 3)], "rotated": rot,
                                      "depth": depth, "height": LABEL_SIZE}
                # the floor under the engraving is thinner than min_wall on purpose: the thin check skips it
                made.ignore.append(((x, y, (bb.min.Z + top) / 2), (w + 1, h + 1, top - bb.min.Z + 0.2)))
                return
    made.info["label"] = None
    made.info["label_notes"] = [f"no label: the template is too thin for a {depth:g} mm engraving" if thin and len(levels) == 1
                                else f"no label: no flat area of {LABEL_SIZE:g} mm text plus a {LABEL_MARGIN:g} mm margin "
                                "on an upward face, clear of holes and edges"]


def _z_axis():
    from build123d import Axis

    return Axis.Z


def _find_room(upper: list, lower: list, above: list, top: float, floor: float, w: float, h: float) -> tuple[float, float] | None:
    """The point nearest the middle of the face at `top` where a w x h rectangle lies inside it,
    inside the section at the engraving's floor and clear of everything above; None if there is none."""
    from build123d import Rectangle

    ub = Compound(upper).bounding_box()
    if ub.size.X < w or ub.size.Y < h:
        return None
    cx, cy = (ub.min.X + ub.max.X) / 2, (ub.min.Y + ub.max.Y) / 2
    xs = np.linspace(ub.min.X + w / 2, ub.max.X - w / 2, max(1, min(40, int((ub.size.X - w) / 0.5) + 1)))
    ys = np.linspace(ub.min.Y + h / 2, ub.max.Y - h / 2, max(1, min(40, int((ub.size.Y - h) / 0.5) + 1)))
    if ub.size.X - w > 0 and ub.size.Y - h > 0:
        xs, ys = np.append(xs, cx), np.append(ys, cy)
    pts = sorted(((float(x), float(y)) for x in xs for y in ys), key=lambda p: (round(math.hypot(p[0] - cx, p[1] - cy), 6), p))
    rect = Rectangle(w, h)
    probes = [(u * w / 2, v * h / 2) for u in (-1, 0, 1) for v in (-1, 0, 1)]

    def solid_at(faces, z, x, y) -> bool:  # quick: nine points of the rectangle on material
        return all(any(f.is_inside(Vector(x + dx, y + dy, z)) for f in faces) for dx, dy in probes)

    def inside(faces, z, x, y) -> bool:  # exact: nothing of the rectangle off the material
        rest = Pos(x, y, z) * rect
        for f in faces:
            rest = rest.cut(f)
            if not rest.faces():
                return True
        return sum(f.area for f in rest.faces()) < 1e-3

    def clear(faces, z, x, y) -> bool:  # nothing above the rectangle
        r = Pos(x, y, z) * rect
        return all(_common_area(r, f) < 1e-3 for f in faces)

    for x, y in pts:
        if (solid_at(upper, top - 0.02, x, y) and solid_at(lower, floor + 0.02, x, y)
                and inside(upper, top - 0.02, x, y) and inside(lower, floor + 0.02, x, y)
                and clear(above, top + 0.02, x, y)):
            return x, y
    return None


# ---------------------------------------------------------------------------------------------
# specs (templates(d), the MCP tool and the CLI)


def make(spec: Template, part: Part, label_prefix: str = "") -> tuple[str, Made]:
    """Make the template a Template spec describes, from `part`. label_prefix: the part's name,
    for the default label "<name> <id>". Returns (id, made)."""
    tid = spec.ident()
    if spec.label is True:
        text = f"{label_prefix} {tid}".strip()
    elif isinstance(spec.label, str) and spec.label:
        text = spec.label
    else:
        text = None
    if spec.kind == "slice":
        m = slice_template(part, spec.plane, spec.at, spec.thickness, spec.base, text)
    elif spec.kind == "face":
        m = face_template(part, spec.face, spec.thickness, text)
    elif spec.kind == "crop":
        m = crop_template(part, spec.center, spec.size, spec.base, text)
    else:
        raise TemplateError(f"template kind {spec.kind!r}: slice, face or crop")
    m.info["id"] = tid
    return tid, m


def pick_part(parts: dict, name: str | None) -> tuple[str, Part]:
    """The printable part a template is cut from: `name`, or the only one ("part")."""
    named = {(k or "part"): v for k, v in parts.items()}
    if name:
        if name not in named:
            raise TemplateError(f"no part {name!r}; parts: {sorted(named)}")
        return name, named[name]
    if len(named) > 1:
        raise TemplateError(f"the script builds several parts: say which one (part=...): {sorted(named)}")
    return next(iter(named.items()))


def checks(made: Made, settings) -> list:
    """The print checks on a template (validity, overhang, thin features without the label's
    engraving, holes, bed edges, separate pieces, build volume), as on any part."""
    from . import checks as ck
    from .render import report

    p = made.part
    valid = bool(p.is_valid) and p.volume > 0
    out = [ck.Finding(ck.OK if valid else ck.FAIL, "valid", "template",
                      "valid solid" if valid else f"is_valid={p.is_valid}, volume={p.volume:.3f}", report(p))]
    lookup = {"template": p}
    for spec in (ck.Overhang("template"), ck.ThinFeature("template", ignore=tuple(made.ignore)), ck.Holes("template"),
                 ck.BedEdge("template"), ck.Gap("template"), ck.Fit("template")):
        try:
            out += spec.run(lookup, None, settings)
        except Exception as e:  # noqa: BLE001 - a check that breaks is a finding, as in run_checks
            out.append(ck.Finding(ck.FAIL, "error", "template", repr(e)))
    return out


def highlight(part: Part, shapes: list, path, title: str, size: str = "normal") -> Path:
    """The part, see-through grey, with `shapes` (faces or solids in the part's coordinates) in
    red: which face a face template takes, or where a slice or crop comes from."""
    from .render import render

    items = [(part, "#9aa0a640", "part")]
    for s in shapes:
        if isinstance(s, Face):  # lift it off the surface a little, so it is drawn on top
            n = s.normal_at(s.center())
            bb = part.bounding_box()
            s = s.moved(Location(tuple(n * max(0.02, 0.003 * max(bb.size.X, bb.size.Y, bb.size.Z)))))
        items.append((s, "#e0303080" if not isinstance(s, Face) else "#e03030", "template" if not isinstance(s, Face) else "face"))
    return render(items, path, title, size=size)
