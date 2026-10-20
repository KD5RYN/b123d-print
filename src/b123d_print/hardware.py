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
    return lines
