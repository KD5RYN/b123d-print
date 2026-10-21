"""Declared bought parts, independent of printable-piece selection and geometry inference."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class Hardware:
    """One bought item for the entire variant's assembly; quantity is never per printed piece.

    Leave specification empty when it needs confirmation. model is an optional shape or lazy
    zero-argument shape factory for assembly(d), never serialized or added to build(d).
    source and units describe the source model (import_model's scale must match those units).
    """

    id: str
    description: str
    quantity: int
    specification: str = ""
    location: str = ""
    note: str = ""
    source_url: str = ""
    source: str = ""
    units: str = ""
    needs_confirmation: bool = False
    model: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        for name in ("id", "description", "specification", "location", "note", "source_url", "source", "units"):
            value = getattr(self, name)
            if not isinstance(value, str):
                raise ValueError(f"hardware {name} must be a string")
            object.__setattr__(self, name, value.strip())
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", self.id):
            raise ValueError("hardware id must be stable text: letters, numbers, _, . or -")
        if not self.description:
            raise ValueError(f"hardware {self.id!r}: description must not be empty")
        if type(self.quantity) is not int or self.quantity <= 0:
            raise ValueError(f"hardware {self.id!r}: quantity must be a positive integer")
        if type(self.needs_confirmation) is not bool:
            raise ValueError(f"hardware {self.id!r}: needs_confirmation must be a boolean")
        if not self.specification:
            object.__setattr__(self, "needs_confirmation", True)
        if self.model is not None and not (self.source and self.units):
            raise ValueError(f"hardware {self.id!r}: a model requires explicit source and units")

    @classmethod
    def from_bd_warehouse(cls, id: str, fastener, quantity: int, **kwargs):
        """Reuse a bd_warehouse Screw, Nut (including HeatSetNut) or Washer's own metadata.

        The library's identifying info contains class, standard/type and size, plus screw
        length and handedness. It is a declared library specification, not mesh recognition.
        Material/finish or a maker's part number can be added with specification/note.
        """
        from bd_warehouse.fastener import Nut, Screw, Washer

        if not isinstance(fastener, (Nut, Screw, Washer)):
            raise ValueError("from_bd_warehouse requires a bd_warehouse Screw, Nut or Washer")
        specification = fastener.info
        # Nut.info omits the insert length selector and nut handedness in bd_warehouse 0.4.
        # Preserve its declared fields rather than silently dropping purchasing information.
        size = getattr(fastener, "nut_size", fastener.thread_size)
        if size != fastener.thread_size:
            specification += f"; size {size}"
        if getattr(fastener, "hand", "right") == "left" and "left hand" not in specification:
            specification += "; left hand thread"
        defaults = dict(description=type(fastener).__name__, specification=specification,
                        source=f"bd_warehouse.fastener.{type(fastener).__name__}", units="mm", model=fastener)
        defaults.update(kwargs)
        return cls(id=id, quantity=quantity, **defaults)

    def standin(self, shape=None, *, color="silver", label: str | None = None) -> tuple:
        """An assembly(d) tuple, associated by item ID and marked for existing fit checks.

        Call once per placed instance; quantity remains the declared total. Pass shape after
        placing the model with place_on/align_axis/Pos. Neither this nor hardware(d) prints it.
        """
        from build123d import Shape

        if not (self.source and self.units):
            raise ValueError(f"hardware {self.id!r}: a standin requires explicit source and units")
        if shape is None:
            shape = self.model() if callable(self.model) and not isinstance(self.model, Shape) else self.model
        if not isinstance(shape, Shape):
            raise ValueError(f"hardware {self.id!r}: standin requires a model shape")
        return shape, color, f"{self.id}{': ' + label if label else ''} (stand-in)"

    def record(self) -> dict:
        """JSON-safe declared metadata only; model factories are never called for a BOM."""
        names = ("id", "description", "quantity", "specification", "location", "note", "source_url", "source", "units")
        return {**{name: getattr(self, name) for name in names}, "needs_confirmation": self.needs_confirmation}


def declared(mod, d) -> list[Hardware] | None:
    """Validate hardware(d) and sort by stable ID. None preserves legacy sheets verbatim."""
    hook = getattr(mod, "hardware", None)
    if hook is None:
        return None
    if not callable(hook):
        raise ValueError("hardware must be a callable hardware(d) hook")
    entries = hook(d)
    if isinstance(entries, (str, bytes, Mapping)) or entries is None:
        raise ValueError("hardware(d) must return an iterable of Hardware entries or mappings")
    try:
        entries = list(entries)
    except TypeError:
        raise ValueError("hardware(d) must return an iterable of Hardware entries or mappings") from None
    items = {}
    for entry in entries:
        if isinstance(entry, Mapping):
            try:
                entry = Hardware(**entry)
            except TypeError as e:
                raise ValueError(f"invalid hardware entry: {e}") from None
        if not isinstance(entry, Hardware):
            raise ValueError("hardware(d) entries must be Hardware objects or mappings")
        if entry.id in items:
            raise ValueError(f"duplicate hardware id {entry.id!r}; use one entry with the total quantity")
        items[entry.id] = entry
    return [items[key] for key in sorted(items)]


def document(items: list[Hardware] | None, variant: str) -> dict:
    return {"schema_version": SCHEMA_VERSION, "variant": variant or "standard", "scope": "whole_assembly",
            "declared": items is not None, "items": [item.record() for item in items or []]}


def json_text(items: list[Hardware] | None, variant: str) -> str:
    return json.dumps(document(items, variant), ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _cell(value: str) -> str:
    # Escape data, including URLs, so it cannot become Markdown links, HTML or extra rows.
    value = html.escape(value, quote=True)
    for char in "\\`*_{}[]()!|":
        value = value.replace(char, f"&#{ord(char)};")
    return value.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "<br>")


def markdown(items: list[Hardware] | None, variant: str) -> list[str]:
    if items is None:
        return []
    lines = ["", "## Declared hardware", "",
             f"Scope: **whole assembly of variant {_cell(variant or 'standard')}**, including when only selected "
             "printable pieces are exported. Quantities are not scaled by piece selection. These are declared "
             "bought parts; hole-based screw-size advice is inferred and is not a shopping list.", ""]
    if not items:
        return lines + ["The script declares no bought hardware for this variant."]
    lines += ["| ID | Description | Specification | Quantity | Location | Note | Source URL | Model source / units |",
              "| --- | --- | --- | --- | --- | --- | --- | --- |"]
    for item in items:
        specification = item.specification or "Needs confirmation"
        if item.specification and item.needs_confirmation:
            specification += " (needs confirmation)"
        values = [item.id, item.description, specification, str(item.quantity),
                  item.location, item.note, item.source_url, " / ".join(x for x in (item.source, item.units) if x)]
        lines.append("| " + " | ".join(_cell(v) for v in values) + " |")
    return lines + ["", "Full list to order from: the `bom` (or `bom_csv`) export format, or the hardware_list tool "
                        "(CLI `b123d-print bom`)."]


# The shopping list: bom.md, bom.csv and hardware_list. One table, identical items merged.

BOM_COLUMNS = ("Qty", "Item", "Specification", "Used for", "Source/link", "Status")
CONFIRMED, CHECK = "confirmed", "check before ordering"
FORMULA_START = ("=", "+", "-", "@", "＠", "\t", "\r")  # spreadsheet formula triggers (CSV injection)


def _norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def bom_rows(groups, count: int = 1) -> list[dict]:
    """Merge the declared items of one or more parts into shopping-list rows.

    groups: [(part label, [Hardware or record dict, ...]), ...]; the label is "" for a single
    part. Items with the same description and specification (case and spacing aside) are one
    row with the quantities summed, times `count`. An item without a specification is never
    merged with another: nothing says the two are the same thing. Rows are sorted by item.
    """
    if type(count) is not int or count < 1:
        raise ValueError("count must be a positive whole number")
    rows: dict[tuple, dict] = {}
    for label, items in groups:
        for item in items or []:
            r = item.record() if isinstance(item, Hardware) else dict(item)
            spec = r.get("specification", "")
            key = (_norm(r["description"]), _norm(spec)) if spec else ("", label, r["id"])
            row = rows.setdefault(key, {"qty": 0, "item": r["description"], "specification": spec,
                                        "used_for": [], "links": [], "notes": [], "check": False})
            row["qty"] += r["quantity"] * count
            row["check"] |= bool(r.get("needs_confirmation")) or not spec
            use = ": ".join(x for x in (label, r.get("location", "")) if x)
            link = r.get("source_url") or r.get("source") or ""
            for field, value in (("used_for", use), ("links", link), ("notes", r.get("note", ""))):
                if value and value not in row[field]:
                    row[field].append(value)
    out = []
    for row in sorted(rows.values(), key=lambda r: (_norm(r["item"]), _norm(r["specification"]))):
        spec = row["specification"] or "not specified"
        out.append({"qty": row["qty"], "item": row["item"],
                    "specification": "; ".join([spec, *row["notes"]]),
                    "used_for": "; ".join(row["used_for"]), "link": " ".join(row["links"]),
                    "status": CHECK if row["check"] else CONFIRMED})
    return out


def bom_total(rows: list[dict]) -> str:
    n = sum(r["qty"] for r in rows)
    check = sum(r["status"] == CHECK for r in rows)
    text = f"Total: {n} item{'s' * (n != 1)} on {len(rows)} line{'s' * (len(rows) != 1)}"
    return text + (f", {check} to check before ordering." if check else ", all confirmed.")


def _md(value: str) -> str:
    """One table cell, readable as plain text: Markdown and HTML characters backslash-escaped
    (data from the script cannot make links, HTML or extra cells), line breaks as spaces."""
    value = re.sub(r"([\\`*\[\]<>|&~$])", r"\\\1", " ".join(value.split()))
    return re.sub(r"(?<!\w)_|_(?!\w)", r"\\_", value)  # snake_case stays readable: _ inside a word is no emphasis


def _md_link(value: str) -> str:
    # A plain web address becomes an autolink (<https://...> reads fine as text); anything else is text.
    return " ".join(f"<{v}>" if re.fullmatch(r"https?://[^\s<>|\\`]+", v) else _md(v) for v in value.split())


def bom_markdown(rows: list[dict], title: str, intro: list[str] = (),
                 empty: str = "No bought hardware is declared.") -> str:
    """The shopping list as Markdown: a title, a line or two of context, one table padded into
    columns (it reads as plain text too) and a total line."""
    lines = [f"# {_md(title)}", ""]
    for paragraph in intro:
        lines += [paragraph, ""]
    if not rows:
        return "\n".join(lines + [empty]) + "\n"
    cells = [list(BOM_COLUMNS)]
    for r in rows:
        status = CONFIRMED if r["status"] == CONFIRMED else f"**{CHECK}**"
        cells.append([str(r["qty"]), _md(r["item"]), _md(r["specification"]), _md(r["used_for"]),
                      _md_link(r["link"]), status])
    width = [max(3, *(len(c[i]) for c in cells)) for i in range(len(BOM_COLUMNS))]

    def line(c):
        return "| " + " | ".join(v.rjust(w) if i == 0 else v.ljust(w) for i, (v, w) in enumerate(zip(c, width))) + " |"

    rule = "| " + " | ".join(("-" * (w - 1) + ":") if i == 0 else "-" * w for i, w in enumerate(width)) + " |"
    lines += [line(cells[0]), rule, *(line(c) for c in cells[1:]), "", bom_total(rows)]
    return "\n".join(lines) + "\n"


def _csv_cell(value) -> str | int:
    if isinstance(value, int):
        return value
    value = " ".join(str(value).split())
    return "'" + value if value.startswith(FORMULA_START) else value


def bom_csv(rows: list[dict]) -> str:
    """The same columns as CSV (RFC 4180: CRLF, quoted where needed). A cell starting with =, +,
    -, @ is prefixed with ' so a spreadsheet shows it as text instead of running it."""
    import csv
    import io

    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\r\n")
    w.writerow(BOM_COLUMNS)
    for r in rows:
        w.writerow([_csv_cell(r[k]) for k in ("qty", "item", "specification", "used_for", "link", "status")])
    return buf.getvalue()


def bom_file_markdown(items: list[Hardware] | None, part: str, variant: str, date: str) -> str:
    """<name>[_<variant>]_bom.md: the shopping list for one variant's whole assembly."""
    title = f"Hardware for {part}" + (f" ({variant})" if variant else "")
    intro = [f"Variant: {_md(variant or 'standard')} · exported {date} by b123d-print. Quantities are for one "
             "whole assembly. Items marked **check before ordering** have no confirmed specification yet."]
    if items is None:
        return bom_markdown([], title, intro, "The script declares no hardware: it has no `hardware(d)`.")
    return bom_markdown(bom_rows([("", items)]), title, intro)


def bom_file_csv(items: list[Hardware] | None) -> str:
    """<name>[_<variant>]_bom.csv, UTF-8 with a byte-order mark so Excel reads it as UTF-8."""
    return "﻿" + bom_csv(bom_rows([("", items or [])]))


def shopping_list(entries: list[dict], count: int = 1, fmt: str = "table") -> str:
    """hardware_list and `b123d-print bom`: the merged list of one or more parts as Markdown
    (fmt="table") or CSV (fmt="csv").

    entries: one per part, {"part", "variant", "variants", "declared", "items": [record, ...]}
    (the worker's hardware op plus the part name), or {"part", "error"} for a part that could
    not be read. Several parts are merged, with the part named in Used for.
    """
    if fmt not in ("table", "csv"):
        raise ValueError(f"format {fmt!r}: use 'table' or 'csv'")
    ok = [e for e in entries if "error" not in e]
    many = len(entries) > 1

    def label(e):
        return e["part"] + (f" ({e['variant']})" if e["variant"] != "standard" else "") if many else ""

    rows = bom_rows([(label(e), e["items"]) for e in ok], count)
    if fmt == "csv":
        return bom_csv(rows)
    names = [e["part"] + (f" ({e['variant']})" if e.get("variant", "standard") != "standard" else "") for e in ok]
    title = "Hardware for " + (", ".join(names) if names else "no parts")
    intro = []
    if count > 1:
        intro.append(f"Quantities for **{count}** of each assembly.")
    elif ok:
        intro.append("Quantities for one whole assembly" + (" of each part." if many else "."))
    for e in ok:
        others = [v for v in e["variants"] if v != e["variant"]]
        if others:
            intro.append(f"{_md(e['part'])} also has variant(s) {', '.join(_md(v) for v in others)}: this list is for "
                         f"{_md(e['variant'])} (pass variant= or part:variant for another).")
    none = [e["part"] for e in ok if not e["declared"]]
    if none:
        intro.append(f"No `hardware(d)` declared in: {', '.join(_md(n) for n in none)}.")
    for e in entries:
        if "error" in e:
            intro.append(f"Could not read {_md(e['part'])}: {_md(e['error'])}")
    return bom_markdown(rows, title, intro)
