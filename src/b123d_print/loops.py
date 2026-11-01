"""Booleans inside for loops in a part script: the build report's hint (light: ast only, no CAD).

A part script that does `part -= Pos(x, y, 0) * hole` on every pass of a loop pays one boolean per
copy. Collecting the copies (GridLocations / PolarLocations / HexLocations / Locations(...) *
feature, or a list) and cutting them once is far faster: 400 holes 0.22 s vs 10.2 s (patterns.py).
"""

from __future__ import annotations

import ast

_NUMERIC = {"len", "abs", "min", "max", "sum", "int", "float", "round", "range", "sqrt", "radians", "degrees",
            "sin", "cos", "tan", "atan", "atan2", "hypot", "pow", "floor", "ceil"}


def _call_name(n: ast.AST) -> str | None:
    """The called name of a call that is not plain arithmetic (Box, Pos, screw_hole, moved), else None."""
    if not isinstance(n, ast.Call):
        return None
    f = n.func
    name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
    return None if name in _NUMERIC else name or "?"


def _shape_like(value: ast.AST) -> bool:
    """True when the right-hand side of `x += ...` looks like a shape, not a number: it calls
    something that is not arithmetic (Box(...), screw_hole(...), hole.moved(loc), Pos(...) * hole).
    `x += i * pitch` and `n += 1` are numbers."""
    return any(_call_name(n) for n in ast.walk(value))


def _pair(it: ast.AST) -> bool:
    """A loop over a literal of at most two items (`for sx in (-1, 1)`): two booleans, left alone."""
    if isinstance(it, ast.IfExp):  # `for sy in (-1, 1) if d.LIPS else ()`
        return _pair(it.body) and _pair(it.orelse)
    return isinstance(it, (ast.Tuple, ast.List, ast.Set)) and len(it.elts) <= 2


def loop_booleans(source: str) -> list[int]:
    """Line numbers of `x -= <shape>` / `x += <shape>` / `x &= <shape>` inside a for loop of a part
    script: one boolean per pass, where collecting the copies and cutting or adding them once is
    much faster (patterns guide). Loops over a literal pair are skipped, and so is collecting
    shapes in a list (`cuts += [Pos(x, 0, 0) * hole]`), which is the fix."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    lines: set[int] = set()

    def visit(node: ast.AST, in_loop: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef)):
                visit(child, False)
            elif isinstance(child, ast.For):
                visit(child, in_loop or not _pair(child.iter))
            elif (in_loop and isinstance(child, ast.AugAssign) and isinstance(child.op, (ast.Add, ast.Sub, ast.BitAnd))
                  and not isinstance(child.value, (ast.List, ast.ListComp, ast.Tuple)) and _shape_like(child.value)):
                lines.add(child.lineno)
            else:
                visit(child, in_loop)

    visit(tree, False)
    return sorted(lines)


def loop_hint(source: str) -> str | None:
    """The build report's hint for a script with booleans inside loops, or None."""
    found = loop_booleans(source)
    if not found:
        return None
    where = ", ".join(str(n) for n in found[:6]) + (", ..." if len(found) > 6 else "")
    return (f"line{'s' if len(found) > 1 else ''} {where}: a boolean on every pass of a for loop; collect the copies "
            "and cut or add them once: part -= GridLocations(...) * hole (also PolarLocations, HexLocations, "
            "Locations(*points), or a list of cutters), much faster on a big pattern (recipe bolt_circle, hole_grid; "
            "docs: Patterns)")
