"""MkDocs hook: fills the generated reference sections from the code, so they cannot drift.

A page asks for a block with a marker line, e.g. `<!-- generated: cli -->`. Blocks:
cli (every `b123d-print` command's --help), mcp-cli (`b123d-print-mcp --help`), mcp (tools,
prompts, resources and resource templates the server registers) and settings (the config.Settings fields).
"""

from __future__ import annotations

import argparse
import inspect
import json
import os
import re
import textwrap

MARKER = re.compile(r"^<!-- generated: ([a-z-]+) -->$", re.M)


def _help(parser: argparse.ArgumentParser) -> str:
    os.environ["COLUMNS"] = "100"  # argparse wraps to the terminal; keep the output stable
    return parser.format_help().rstrip()


def _subparsers(parser: argparse.ArgumentParser, prefix: str):
    yield prefix, parser
    for action in parser._actions:
        if isinstance(action, argparse._SubParsersAction):
            for name, sub in action.choices.items():
                yield from _subparsers(sub, f"{prefix} {name}")


def cli() -> str:
    from b123d_print.cli import build_parser

    out = []
    for name, parser in _subparsers(build_parser(), "b123d-print"):
        heading = [f"### `{name}`", ""] if " " in name else []  # the page's own heading covers the root
        out += heading + ["```text", _help(parser), "```", ""]
    return "\n".join(out)


def mcp_cli() -> str:
    from b123d_print.mcp_server import build_parser

    return "\n".join(["```text", _help(build_parser()), "```"])


TYPES = {"string": "str", "number": "float", "integer": "int", "boolean": "bool"}


def _text(s: str) -> str:
    """Docstring as Markdown: keep `code` spans, escape < outside them (parts/<name>/...)."""
    s = inspect.cleandoc(s or "")
    return "".join(p if p.startswith("`") else p.replace("<", "&lt;") for p in re.split(r"(`[^`]*`)", s))


def _cell(s: str) -> str:
    """Docstring text for a table cell: one line."""
    return " ".join(_text(s).split())


def _signature(schema: dict) -> str:
    req = set(schema.get("required", []))
    args = []
    for name, prop in schema.get("properties", {}).items():
        types = [p.get("type") for p in prop.get("anyOf", [prop]) if p.get("type") != "null"]
        t = " | ".join(TYPES.get(t, t) for t in types if t) or "any"
        default = prop.get("default")
        args.append(name if name in req else f"{name}: {t} = {'None' if default is None else json.dumps(default)}")
    return ", ".join(args)


def mcp() -> str:
    import anyio

    from b123d_print.mcp_server import mcp as server

    async def collect():
        return (await server.list_tools(), await server.list_prompts(), await server.list_resources(),
                await server.list_resource_templates())

    tools, prompts, resources, templates = anyio.run(collect)
    out = ["### Tools", ""]
    for t in tools:
        out += [f"#### `{t.name}`", "", "```python", f"{t.name}({_signature(t.input_schema)})", "```", "",
                _text(t.description), ""]
    out += ["### Prompts", ""]
    for p in prompts:
        args = ", ".join(f"`{a.name}`" + ("" if a.required else " (optional)") for a in p.arguments or [])
        out += [f"#### `{p.name}`", "", f"Arguments: {args or 'none'}.", "", _text(p.description), ""]
    out += ["### Resources", "", "| URI | Type | What |", "| --- | --- | --- |"]
    for r in resources:
        out.append(f"| `{r.uri}` | `{r.mime_type}` | {_cell(r.description)} |")
    for t in templates:  # parameterized resources, e.g. b123d-print://files/{workspace}/{+path}
        out.append(f"| `{t.uri_template}` | `{t.mime_type or '(per file)'}` | {_cell(t.description)} |")
    return "\n".join(out)


def settings() -> str:
    from dataclasses import fields

    from b123d_print import config

    comments = dict(re.findall(r"^    (\w+): [^=]+=.*?#\s*(.*)$", inspect.getsource(config.Settings), re.M))
    out = ["| Key | Default | Meaning |", "| --- | --- | --- |"]
    for f in fields(config.Settings):
        if f.name == "root":
            continue
        default = list(f.default) if isinstance(f.default, tuple) else f.default
        out.append(f"| `{f.name}` | `{json.dumps(default)}` | {_cell(comments.get(f.name, ''))} |")
    return "\n".join(out)


BLOCKS = {"cli": cli, "mcp-cli": mcp_cli, "mcp": mcp, "settings": settings}


def render(markdown: str) -> str:
    return MARKER.sub(lambda m: BLOCKS[m.group(1)](), markdown)


def on_page_markdown(markdown, page, config, files):
    return render(markdown) if MARKER.search(markdown) else markdown
