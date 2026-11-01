"""The replication spec: a physical part copied for printing (#165, the `replicate_part` prompt).

MEASURE.md next to the part script is the user's measurement sheet (docs/using/measuring.md).
Three more columns make it the replication spec of a part copied from a physical original:

    | Feature | Value | Method | Accuracy | Status | Class | Source | Field | Why changed |

- Value: the reading in mm, or several readings separated by "," or ";" (they are averaged and
  their spread checked). "in" or '"' in the cell means inches. Text in parentheses is a note.
- Class: critical (must match: mating interfaces, hole sizes and spacings, fits, sealing or
  bearing faces, snap and latch geometry, threads, the envelope where it mates) or free.
- Source: measured, standard, derived, changed (for print) or estimate.
- Field: the Dims field that models it, or a simple expression of fields ("PLATE_W - 2 * RIM_WALL").
- Why changed: the reason the model differs from the original (draft removed, wall thickened).

spec() joins the rows with the part's Dims values (variant overrides, derived @property values
and hole_comp() included: the worker passes a real Dims instance) and flags what needs attention:
a critical value that is an estimate or not measured yet, readings that disagree by more than
their accuracy (draft, an oval hole, warp), a critical value the model changes with no reason,
a Field the script does not have. Nothing here changes the part or fails a check: the flags go
to the replication_spec tool, `b123d-print spec` and the `spec` export format.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

MEASURE_FILE = "MEASURE.md"
DEFAULT_TOL = 0.1  # mm, when a row gives no accuracy: what the measuring guide calls plenty for FDM
CLASSES = ("critical", "free")
SOURCES = ("measured", "standard", "derived", "changed", "estimate")
INCH = 25.4

_COLUMNS = {  # column -> header names that mean it (lowercase, without punctuation)
    "feature": ("feature", "dimension", "what"),
    "value": ("value", "measured", "readings", "reading"),
    "method": ("method", "tool", "how"),
    "accuracy": ("accuracy", "tol", "tolerance"),
    "status": ("status",),
    "klass": ("class",),
    "source": ("source",),
    "field": ("field", "dims", "dims field"),
    "why": ("why changed", "why", "reason", "change"),
}
_NUM = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)"
_FRACTION = re.compile(rf"(?:(\d+)[- ])?(\d+)/(\d+)")
_NUMBER = re.compile(_NUM)
_EMPTY = {"", "-", "—", "?", "tbd", "todo", "n/a"}


@dataclass
class Row:
    feature: str
    line: int
    value: str = ""
    method: str = ""
    accuracy: str = ""
    status: str = ""
    klass: str = ""
    source: str = ""
    field: str = ""
    why: str = ""
    readings: list[float] = dc_field(default_factory=list)
    tol: float | None = None
    inch: bool = False

    @property
    def measured(self) -> float | None:
        return sum(self.readings) / len(self.readings) if self.readings else None

    @property
    def spread(self) -> float:
        return max(self.readings) - min(self.readings) if len(self.readings) > 1 else 0.0

    @property
    def estimated(self) -> bool:
        v = self.value.strip().lower()
        return ("estim" in self.status.lower() or self.source == "estimate"
                or v.startswith(("~", "≈", "about", "approx", "ca.")))


def _norm_header(cell: str) -> str:
    return re.sub(r"[^a-z ]", "", cell.lower()).strip()


def _cells(line: str) -> list[str]:
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _number(text: str, inch: bool) -> float | None:
    """One value in mm from a cell piece: a decimal, or (in inches) a fraction like 3-9/32."""
    m = _FRACTION.search(text) if inch else None
    if m:
        whole, num, den = m.groups()
        v = (int(whole) if whole else 0) + int(num) / int(den)
    else:
        m = _NUMBER.search(text)
        if not m:
            return None
        v = float(m.group())
    return v * (INCH if inch else 1.0)


def _is_inch(text: str) -> bool:
    return bool(re.search(r'(\d|\s)(in|inch|inches)\b|"', text))


def readings(cell: str) -> tuple[list[float], bool]:
    """The readings in a Value cell, in mm, and whether they were given in inches."""
    text = re.sub(r"\([^)]*\)", " ", cell)  # notes: "83.3 (3-9/32 in, NEMA WD-6)" is 83.3
    if text.strip().lower() in _EMPTY:
        return [], False
    inch = _is_inch(text)
    vals = [_number(p, inch) for p in re.split(r"[;,]", text)]
    return [v for v in vals if v is not None], inch


def _tol(cell: str, inch: bool) -> float | None:
    text = re.sub(r"\([^)]*\)", " ", cell)
    if text.strip().lower() in _EMPTY:
        return None
    v = _number(text.replace("±", " "), _is_inch(text) or (inch and not re.search(r"\bmm\b", text)))
    return abs(v) if v is not None else None


def _klass(cell: str) -> str:
    c = cell.strip().lower().strip("*_` ")
    if c.startswith("crit"):
        return "critical"
    if c.startswith("free"):
        return "free"
    return c


def _source(cell: str) -> str:
    c = cell.strip().lower().strip("*_` ")
    for s in SOURCES:
        if c.startswith(s[:5]):  # "changed-for-print", "estimated", "standard (NEMA)"
            return s
    if c.startswith(("typed", "caliper")):
        return "measured"
    return c


def parse(text: str) -> tuple[list[Row], set[str]]:
    """Every row of the Markdown tables in `text` that have a Feature column, and the columns
    the tables had (so a sheet without Class columns reads as a plain measurement sheet)."""
    rows: list[Row] = []
    seen: set[str] = set()
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        if not (lines[i].lstrip().startswith("|") and i + 1 < len(lines)
                and re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", lines[i + 1]) and "-" in lines[i + 1]):
            i += 1
            continue
        header = [_norm_header(c) for c in _cells(lines[i])]
        cols: dict[str, int] = {}
        for key, names in _COLUMNS.items():
            for j, h in enumerate(header):
                if h in names and j not in cols.values():
                    cols[key] = j
                    break
        i += 2
        if "feature" not in cols:
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                i += 1
            continue
        seen |= set(cols)
        while i < len(lines) and lines[i].lstrip().startswith("|"):
            cells = _cells(lines[i])
            get = {k: (cells[j] if j < len(cells) else "") for k, j in cols.items()}
            if get["feature"]:
                r = Row(feature=get["feature"], line=i + 1, **{k: get.get(k, "") for k in _COLUMNS if k != "feature"})
                r.klass, r.source, r.field = _klass(r.klass), _source(r.source), r.field.strip("` ")
                r.readings, r.inch = readings(r.value)
                r.tol = _tol(r.accuracy, r.inch)
                if not r.source:
                    r.source = "estimate" if r.estimated else ("measured" if r.readings else "")
                rows.append(r)
            i += 1
    return rows, seen


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}


def modeled(expr: str, d) -> float | str:
    """The value of a Field cell on the Dims instance d: a field or derived name, or a simple
    expression of them with + - * / and numbers. Raises NameError for an unknown name."""
    def ev(n):
        if isinstance(n, ast.Expression):
            return ev(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return n.value
        if isinstance(n, ast.Name):
            if n.id.startswith("_") or not hasattr(d, n.id):
                raise NameError(n.id)
            return getattr(d, n.id)
        if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
            return _OPS[type(n.op)](ev(n.left), ev(n.right))
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -ev(n.operand)
        raise ValueError(f"{expr!r}: use a Dims name or + - * / of names and numbers")

    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        raise ValueError(f"{expr!r} is not a Dims name or expression") from None
    v = ev(tree)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return repr(v)
    return float(v)


def spec(rows: list[Row], columns: set[str], d, base=None, variant: str = "") -> dict:
    """The replication spec: each row with its modeled value and difference, and the flags.
    d: the Dims instance (None: no modeled values). base: the standard variant's Dims when d is
    the variant `variant`: where the two differ, the difference is the variant's own (a bigger
    plate, and everything derived from it), not a flag."""
    out, flags = [], []

    def flag(level: str, r: Row, msg: str) -> None:
        flags.append({"level": level, "feature": r.feature, "line": r.line, "message": msg})

    for r in rows:
        tol = r.tol if r.tol is not None else DEFAULT_TOL
        crit = r.klass == "critical"
        e = {"feature": r.feature, "field": r.field, "class": r.klass, "source": r.source, "readings": r.readings,
             "measured": r.measured, "tol": r.tol, "inch": r.inch, "why": r.why, "method": r.method}
        if r.klass and r.klass not in CLASSES:
            flag("NOTE", r, f"class {r.klass!r}: use critical or free")
        if crit and not r.readings:
            flag("WARN", r, "critical and not measured yet" + (f" ({r.method})" if r.method else ""))
        elif crit and r.estimated:
            flag("WARN", r, "critical but an estimate: measure it" + (f" ({r.method})" if r.method else "")
                 + " and mark it CONFIRMED")
        if len(r.readings) > 1 and r.spread > tol + 1e-9:
            flag("WARN" if crit else "NOTE", r,
                 f"readings spread {r.spread:.2f} mm, more than ±{tol:g}: tapered (draft), oval or warped? "
                 "Say where it was measured (at the mating location, or mid-height) and which value to model")
        if r.field and d is not None:
            try:
                m = modeled(r.field, d)
            except (NameError, ValueError, ArithmeticError, TypeError) as err:
                m = None
                why = (f"no Dims field {err}" if isinstance(err, NameError)
                       else "division by zero" if isinstance(err, ZeroDivisionError)
                       else f"cannot compute it ({err})" if isinstance(err, (ArithmeticError, TypeError)) else str(err))
                flag("WARN", r, f"Field {r.field!r}: {why}")
            e["modeled"] = m
            if isinstance(m, float) and r.measured is not None:
                delta = m - r.measured
                e["delta"] = delta
                if abs(delta) > tol + 1e-9:
                    if r.why:
                        e["changed"] = True
                    elif base is not None and _differs(r.field, base, m):
                        e["changed"] = True
                        e["why"] = f"(variant {variant})"
                    else:
                        flag("WARN" if crit else "NOTE", r,
                             f"modeled {m:g} differs from measured {r.measured:g} by {delta:+.2f} mm "
                             f"(more than ±{tol:g}) and Why changed is empty"
                             + (": a critical size should match, or say why (clearance, rounded to a standard)"
                                if crit else ": say why"))
        elif crit and not r.field and "field" in columns:
            flag("WARN", r, "critical with no Field: name the Dims field that models it so the spec can check it")
        out.append(e)
    if rows and "klass" not in columns:
        flags.append({"level": "NOTE", "feature": "", "line": 0,
                      "message": "a plain measurement sheet: add the Class, Source, Field and Why changed columns to "
                                 "make it a replication spec (docs/using/replicate.md)"})
    elif rows:
        unclassed = [r.feature for r in rows if not r.klass]
        if unclassed:
            flags.append({"level": "NOTE", "feature": "", "line": 0,
                          "message": f"{len(unclassed)} row(s) without a Class: " + ", ".join(unclassed[:6])
                                     + (" ..." if len(unclassed) > 6 else "")})
    counts = {k: sum(1 for r in rows if r.klass == k) for k in CLASSES}
    return {"rows": out, "flags": flags, "counts": counts, "replication": "klass" in columns}


def _differs(expr: str, base, value: float) -> bool:
    try:
        b = modeled(expr, base)
    except (NameError, ValueError, ArithmeticError, TypeError):
        return False
    return isinstance(b, float) and abs(b - value) > 1e-9


def from_part(script: str | Path, d, base=None, variant: str = "") -> dict | None:
    """The spec of the part whose script is `script`, from its MEASURE.md; None without one."""
    f = Path(script).parent / MEASURE_FILE
    if not f.is_file():
        return None
    rows, columns = parse(f.read_text(encoding="utf-8", errors="replace"))
    return spec(rows, columns, d, base, variant)


def standard(mod, key: str):
    """The standard variant's Dims of a loaded part script, when `key` is another variant; else None."""
    from .project import dims, variants

    keys = list(variants(mod))
    std = "" if "" in keys else keys[0]
    return None if key == std else dims(mod, std)


def _fmt(v) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        if math.isnan(v):
            return ""
        return f"{v:.3f}".rstrip("0").rstrip(".")
    return str(v)


def _cell(s: str) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ")


def text(res: dict, title: str) -> str:
    """The spec as Markdown: the table, then the flags, most serious first."""
    c = res["counts"]
    lines = [f"# {title}: replication spec", "",
             f"{len(res['rows'])} dimension(s): {c['critical']} critical, {c['free']} free. "
             "Measured values come from MEASURE.md, modeled values from the script's Dims.", "",
             "| Feature | Field | Class | Source | Measured | Tol | Modeled | Δ | Why changed |",
             "| --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for e in res["rows"]:
        meas = _fmt(e["measured"])
        if len(e["readings"]) > 1:
            meas += f" (×{len(e['readings'])}, spread {_fmt(max(e['readings']) - min(e['readings']))})"
        if e["inch"]:
            meas += " (from in)"
        tol = f"±{_fmt(e['tol'])}" if e["tol"] is not None else ""
        delta = f"{e['delta']:+.2f}" if "delta" in e else ""
        lines.append("| " + " | ".join(_cell(x) for x in (
            e["feature"], f"`{e['field']}`" if e["field"] else "", e["class"], e["source"], meas, tol,
            _fmt(e.get("modeled")), delta, e["why"])) + " |")
    flags = sorted(res["flags"], key=lambda f: f["level"] != "WARN")
    lines.append("")
    if not flags:
        lines.append("No flags: every critical value is measured, traced to a Dims field and modeled as measured "
                     "or with a reason.")
    for f in flags:
        where = f"{f['feature']} (MEASURE.md line {f['line']}): " if f["feature"] else ""
        lines.append(f"- **{f['level']}** {where}{f['message']}")
    return "\n".join(lines) + "\n"


def summary(res: dict) -> str:
    """One line for results that only mention the spec (export, the review checklist)."""
    w = sum(1 for f in res["flags"] if f["level"] == "WARN")
    c = res["counts"]
    return (f"replication spec: {c['critical']} critical, {c['free']} free"
            + (f"; {w} warning(s): replication_spec shows them" if w else "; no warnings"))
