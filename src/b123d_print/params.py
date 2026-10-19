"""The Dims of a part script, read and changed without running the script.

`read(src)` lists the fields of the script's `Dims` dataclass (name, type, default as written,
its value when the default is a literal, the comment on its line), its derived values
(@property) and the overrides in `VARIANTS`. `set_values(src, {"WIDTH": 42.0})` returns the
script with those defaults replaced and every other character unchanged: the ast gives the exact
line and column of each default, and only that span is rewritten. With `variant=`, the override
in VARIANTS is changed (or added) instead.

Refused, with the reason: a field Dims does not have (with the closest names), a derived value,
a default that is an expression (`hole_comp(__file__)`, `2 * WALL`: it is computed when the
script runs), and a value of the wrong type (`int` field given 2.5, `float` given "x").

Only the ast is used, never the script itself: the MCP server runs this outside the sandbox.
"""

from __future__ import annotations

import ast
import difflib
import io
import math
import tokenize


class ParamError(ValueError):
    pass


_SCALAR = {"float": (int, float), "int": (int,), "bool": (bool,), "str": (str,)}


def _line_starts(src: str) -> list[int]:
    starts, pos = [0], 0
    for line in src.splitlines(keepends=True):
        pos += len(line)
        starts.append(pos)
    return starts


class _Src:
    """Source text with ast positions (1-based lines, UTF-8 byte columns) turned into string offsets."""

    def __init__(self, src: str):
        self.src = src
        self.lines = src.splitlines(keepends=True)
        self.starts = _line_starts(src)

    def offset(self, line: int, col: int) -> int:
        text = self.lines[line - 1] if line - 1 < len(self.lines) else ""
        return self.starts[line - 1] + len(text.encode("utf-8")[:col].decode("utf-8", errors="replace"))

    def span(self, node) -> tuple[int, int]:
        return self.offset(node.lineno, node.col_offset), self.offset(node.end_lineno, node.end_col_offset)

    def text(self, node) -> str:
        a, b = self.span(node)
        return self.src[a:b]


def _comments(src: str) -> dict[int, str]:
    """{line: comment text} for every `# comment` in the source."""
    out = {}
    try:
        for tok in tokenize.generate_tokens(io.StringIO(src).readline):
            if tok.type == tokenize.COMMENT:
                out[tok.start[0]] = tok.string.lstrip("#").strip()
    except (tokenize.TokenError, IndentationError, SyntaxError):
        pass
    return out


def _parse(src: str) -> ast.Module:
    try:
        return ast.parse(src)
    except SyntaxError as e:
        raise ParamError(f"the script does not parse (line {e.lineno}: {e.msg})") from None


def _dims_class(tree: ast.Module) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "Dims":
            return node
    raise ParamError("the script has no top-level `class Dims` (named dimensions live in a Dims dataclass)")


def _is_property(fn) -> bool:
    return any((isinstance(d, ast.Name) and d.id in ("property", "cached_property"))
               or (isinstance(d, ast.Attribute) and d.attr in ("property", "cached_property")) for d in fn.decorator_list)


def _default_node(value):
    """The node holding a field's default: the value itself, or default= in field(default=...);
    None for field(default_factory=...) or a bare field()."""
    if isinstance(value, ast.Call) and getattr(value.func, "id", getattr(value.func, "attr", None)) == "field":
        for kw in value.keywords:
            if kw.arg == "default":
                return kw.value
        return None
    return value


def _literal(node):
    """(True, value) when `node` is a literal (numbers, strings, bools, None, tuples and lists of
    them, a leading minus included), else (False, None)."""
    if node is None:
        return False, None
    try:
        return True, ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError, RecursionError):
        return False, None


def _self_fields(fn) -> list[str]:
    return sorted({n.attr for n in ast.walk(fn) if isinstance(n, ast.Attribute)
                   and isinstance(n.value, ast.Name) and n.value.id == "self"})


def read(src: str) -> dict:
    """The script's Dims fields, derived values and variant overrides (see the module docstring)."""
    tree = _parse(src)
    cls = _dims_class(tree)
    s, notes = _Src(src), _comments(src)
    fields, derived = [], []
    for node in cls.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            dn = _default_node(node.value) if node.value is not None else None
            ok, val = _literal(dn)
            f = {"name": node.target.id, "type": s.text(node.annotation), "line": node.lineno,
                 "default": s.text(node.value) if node.value is not None else None,
                 "literal": ok}
            if ok:
                f["value"] = list(val) if isinstance(val, tuple) else val
            comment = notes.get(node.end_lineno) or notes.get(node.lineno)
            if comment:
                f["comment"] = comment
            fields.append(f)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_property(node):
            doc = ast.get_docstring(node)
            derived.append({"name": node.name, "line": node.lineno, "uses": _self_fields(node),
                            **({"doc": doc.splitlines()[0]} if doc else {})})
    out = {"class_line": cls.lineno, "fields": fields, "derived": derived}
    var = _variants(tree, s)
    if var is not None:
        out["variants"] = {k or "standard": {f: s.text(v) for f, (_, v) in ov.items()} for k, (_, ov) in var.items()}
    return out


def _variants(tree: ast.Module, s: _Src) -> dict | None:
    """{key: (container node, {field: (key node or None, value node)})} for a literal VARIANTS
    dict whose values are dicts or dict(...) calls; None without one."""
    node = None
    for st in tree.body:
        if isinstance(st, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "VARIANTS" for t in st.targets):
            node = st.value
        elif isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name) and st.target.id == "VARIANTS":
            node = st.value
    if not isinstance(node, ast.Dict):
        return None
    out = {}
    for k, v in zip(node.keys, node.values):
        ok, key = _literal(k)
        if not ok or not isinstance(key, str):
            continue
        if isinstance(v, ast.Dict):
            ov = {}
            for kk, vv in zip(v.keys, v.values):
                okk, name = _literal(kk)
                if okk and isinstance(name, str):
                    ov[name] = (kk, vv)
            out[key] = (v, ov)
        elif isinstance(v, ast.Call) and getattr(v.func, "id", None) == "dict":
            out[key] = (v, {kw.arg: (None, kw.value) for kw in v.keywords if kw.arg})
    return out


def _fmt(value, kind: str | None, current) -> str:
    """The source text for `value`, for a field of annotation `kind` (float fields keep a decimal point)."""
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return repr(value)
    if isinstance(value, (list, tuple)):
        inner = [_fmt(v, _elem(kind, i), (current or [None] * len(value))[i] if isinstance(current, (list, tuple))
                      and i < len(current) else None) for i, v in enumerate(value)]
        if isinstance(current, list) or (kind or "").startswith("list"):
            return "[" + ", ".join(inner) + "]"
        return "(" + ", ".join(inner) + ("," if len(inner) == 1 else "") + ")"
    if isinstance(value, float) or kind == "float" or (kind is None and isinstance(current, float)):
        v = float(value)
        if not math.isfinite(v):
            raise ParamError(f"{value!r} is not a finite number")
        return repr(v)
    return repr(int(value))


def _elem(kind: str | None, i: int) -> str | None:
    """The element type of tuple[float, int] / tuple[float, ...] / list[float] at index i."""
    if not kind or "[" not in kind:
        return None
    args = [a.strip() for a in kind[kind.index("[") + 1: kind.rindex("]")].split(",")]
    if len(args) == 2 and args[1] == "...":
        return args[0]
    return args[i] if i < len(args) else None


def check_type(name: str, kind: str | None, value, current, have_current: bool):
    """`value` converted for a field of annotation `kind` whose current literal is `current`, or
    ParamError when it does not fit. A float field takes ints (written as floats); an int field
    takes a whole float (3.0 -> 3)."""
    kind = (kind or "").replace("typing.", "")
    if kind.startswith("Optional[") or "None" in kind.split("|"):
        if value is None:
            return None
        kind = kind.removeprefix("Optional[").removesuffix("]") if kind.startswith("Optional[") else \
            "|".join(k for k in kind.split("|") if k.strip() != "None").strip()
    base = kind.split("[")[0].strip().lower()
    if base not in _SCALAR and base not in ("tuple", "list") and have_current:  # no usable annotation: like the current value
        base = ("bool" if isinstance(current, bool) else "int" if isinstance(current, int)
                else "float" if isinstance(current, float) else "str" if isinstance(current, str)
                else "tuple" if isinstance(current, (tuple, list)) else base)
    if base in ("float", "int"):
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ParamError(f"{name} is {kind or base}: give a number, not {value!r}")
        if not math.isfinite(float(value)):
            raise ParamError(f"{name}: {value!r} is not a finite number")
        if base == "int":
            if float(value) != int(value):
                raise ParamError(f"{name} is int: {value!r} is not a whole number")
            return int(value)
        return float(value)
    if base == "bool":
        if not isinstance(value, bool):
            raise ParamError(f"{name} is bool: give true or false, not {value!r}")
        return value
    if base == "str":
        if not isinstance(value, str):
            raise ParamError(f"{name} is str: give a string, not {value!r}")
        return value
    if base in ("tuple", "list"):
        if not isinstance(value, (list, tuple)):
            raise ParamError(f"{name} is {kind or base}: give a list of values, not {value!r}")
        if have_current and isinstance(current, (list, tuple)) and len(current) != len(value) and "..." not in (kind or ""):
            raise ParamError(f"{name} has {len(current)} values; got {len(value)}")
        out = []
        for i, v in enumerate(value):
            c = current[i] if have_current and isinstance(current, (list, tuple)) and i < len(current) else None
            out.append(check_type(f"{name}[{i}]", _elem(kind, i), v, c, c is not None))
        return out
    if base in ("", "any"):
        if not isinstance(value, (bool, int, float, str, list, tuple)) and value is not None:
            raise ParamError(f"{name}: {value!r} is not a number, string, bool or list")
        return value
    raise ParamError(f"{name} is {kind}: set_params changes numbers, strings, bools and tuples of them only; "
                     "edit this one with write_part")


def _pick(fields: dict, name: str, derived: dict) -> ast.AnnAssign:
    if name in fields:
        return fields[name]
    if name in derived:
        uses = derived[name]
        raise ParamError(f"{name} is derived (a @property of Dims), not a field: change "
                         + (f"the fields it uses ({', '.join(uses)})" if uses else "the fields it is computed from"))
    close = difflib.get_close_matches(name, list(fields), n=3, cutoff=0.6)
    raise ParamError(f"Dims has no field {name!r}" + (f"; did you mean {', '.join(close)}?" if close else "")
                     + f" Fields: {', '.join(fields) or 'none'}")


def set_values(src: str, values: dict, variant: str | None = None) -> tuple[str, list[dict], list[str]]:
    """`src` with the Dims defaults in `values` replaced (or, with `variant`, that variant's
    overrides in VARIANTS changed or added). Returns (new source, changes, notes): each change is
    {"field", "old", "new", "line"} with old and new as source text; notes name variants that
    override a changed default (they do not change) and derived values that follow it."""
    if not values:
        raise ParamError("no values given: {\"FIELD\": value, ...}")
    tree = _parse(src)
    cls = _dims_class(tree)
    s = _Src(src)
    fields = {n.target.id: n for n in cls.body if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)}
    derived = {n.name: _self_fields(n) for n in cls.body
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_property(n)}
    key = None if variant in (None, "", "standard") else variant
    var = _variants(tree, s)
    if key is not None:
        if var is None:
            raise ParamError("variant given, but the script has no literal VARIANTS dict to change")
        if key not in var:
            raise ParamError(f"no variant {variant!r}; variants: {[k or 'standard' for k in var]}")
    edits: list[tuple[int, int, str]] = []
    changes, notes = [], []
    for name, value in values.items():
        node = _pick(fields, name, derived)
        kind = s.text(node.annotation)
        dn = _default_node(node.value) if node.value is not None else None
        have, cur = _literal(dn)
        if key is None:
            if node.value is None:
                raise ParamError(f"{name} has no default in Dims (every variant must set it): give it one with write_part")
            if dn is None:
                raise ParamError(f"{name}'s default is `{s.text(node.value)}` (a default_factory): edit it with write_part")
            if not have:
                raise ParamError(f"{name}'s default is the expression `{s.text(dn)}`, computed when the script runs; "
                                 "set_params only replaces literal values. "
                                 + _expr_hint(s.text(dn)))
            new = _like(_fmt(check_type(name, kind, value, cur, have), _base(kind), cur), s.text(dn))
            a, b = s.span(dn)
            edits.append((a, b, new))
            changes.append({"field": name, "old": s.text(dn), "new": new, "line": dn.lineno})
            over = [k or "standard" for k, (_, ov) in (var or {}).items() if name in ov]
            if over:
                notes.append(f"{name}: variant(s) {', '.join(over)} override it, so they do not change "
                             f"(set_params(..., variant=...) changes an override)")
        else:
            container, ov = var[key]
            if name in ov:
                vnode = ov[name][1]
                okv, curv = _literal(vnode)
                if not okv:
                    raise ParamError(f"variant {variant!r} sets {name} to the expression `{s.text(vnode)}`; "
                                     "edit it with write_part")
                new = _like(_fmt(check_type(name, kind, value, curv, True), _base(kind), curv), s.text(vnode))
                a, b = s.span(vnode)
                edits.append((a, b, new))
                changes.append({"field": name, "variant": key or "standard", "old": s.text(vnode), "new": new,
                                "line": vnode.lineno})
            else:
                new = _fmt(check_type(name, kind, value, cur, have), _base(kind), cur)
                pos, text = _insertion(s, container, name, new)
                edits.append((pos, pos, text))
                changes.append({"field": name, "variant": key or "standard", "old": None, "new": new,
                                "line": container.end_lineno})
        uses = [d for d, u in derived.items() if name in u]
        if uses and key is None:
            notes.append(f"{name} is used by the derived value(s) {', '.join(uses)}")
    out = src
    for a, b, text in sorted(edits, reverse=True):
        out = out[:a] + text + out[b:]
    try:
        compile(out, "<script>", "exec")
    except SyntaxError as e:  # never write a script that does not parse
        raise ParamError(f"the edit would break the script (line {e.lineno}: {e.msg}); nothing changed") from None
    return out, changes, notes


def _like(new: str, old: str | None) -> str:
    """A string literal in the quotes the old one used ("lid" stays double-quoted)."""
    if old and old[:1] == '"' and new[:1] == "'" and '"' not in new[1:-1] and "\\'" not in new:
        return '"' + new[1:-1] + '"'
    return new


def _base(kind: str) -> str | None:
    b = kind.replace("typing.", "").split("[")[0].strip()
    return b if b in _SCALAR or b in ("tuple", "list") else None


def _expr_hint(expr: str) -> str:
    if "hole_comp" in expr:
        return "HOLE_COMP comes from the user's settings: change it there (`b123d-print printer hole-comp <value>`), not in the script."
    if any(f in expr for f in ("clearance(", "press_fit(", "free_fit(", "pip_clearance(")):
        return "Fit values come from the user's settings (b123d-print.toml or the user config); change them there."
    return "Change the fields it is computed from, or edit that line with write_part."


def _insertion(s: _Src, container, name: str, new: str) -> tuple[int, str]:
    """Where and what to insert to add `name` to a variant's overrides (a {...} dict or dict(...))."""
    end = s.offset(container.end_lineno, container.end_col_offset) - 1  # the closing } or )
    items = (container.values if isinstance(container, ast.Dict) else [kw.value for kw in container.keywords]
             + list(container.args))
    entry = f'"{name}": {new}' if isinstance(container, ast.Dict) else f"{name}={new}"
    if not items:
        return end, entry
    last = max(items, key=lambda n: (n.end_lineno, n.end_col_offset))
    after = s.offset(last.end_lineno, last.end_col_offset)
    between = s.src[after:end]
    if "," in between:
        return after + between.index(",") + 1, " " + entry
    return after, ", " + entry
