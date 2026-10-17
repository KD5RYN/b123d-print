"""Docs drift tests: fail when the code has something the docs don't mention, or the other way round.

They check names, not prose. Which page documents what is listed in CONTRIBUTING.md ("The docs
rule"); the generated Reference page (tools/docs_hooks.py) needs no test.
"""

import argparse
import dataclasses
import re
from pathlib import Path

import anyio
import pytest

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
SITE = "https://kd5ryn.github.io/b123d-print/"


def page(rel: str) -> str:
    return (DOCS / rel).read_text(encoding="utf-8")


def code_names(text: str) -> set[str]:
    """Every `code span` and fenced code block in a Markdown text, plus the words and flags inside each."""
    fences = re.findall(r"^```[^\n]*\n(.*?)^```", text, re.S | re.M)
    spans = fences + re.findall(r"`([^`\n]+)`", re.sub(r"^```.*?^```", "", text, flags=re.S | re.M))
    out = set(spans)
    for s in spans:
        out |= set(re.findall(r"--?[\w-]+|[\w-]+", s))
    return out


def table_rows(text: str) -> dict[str, str]:
    """First-column code name -> whole row, for every Markdown table row that starts with `name...`."""
    rows = {}
    for line in text.splitlines():
        m = re.match(r"\|\s*`([\w-]+)", line)
        if m:
            rows.setdefault(m.group(1), line)
    return rows


def table_keys(text: str, header: str) -> set[str]:
    """First-column code names of the table right under `## header`."""
    section = text.split(f"## {header}\n", 1)[1].split("\n## ", 1)[0]
    return set(table_rows(section))


# --- MCP server --------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def server():
    from b123d_print.mcp_server import mcp

    async def collect():
        return await mcp.list_tools(), await mcp.list_prompts(), (await mcp.list_resources(), await mcp.list_resource_templates())

    return anyio.run(collect)


def test_mcp_tools_documented(server):
    """Every tool has a row in the tools table naming each of its parameters, and nothing extra."""
    tools, _, _ = server
    text = page("using/tools.md")
    assert table_keys(text, "Tools") == {t.name for t in tools}, "docs/using/tools.md tools table vs registered tools"
    rows = table_rows(text)
    for t in tools:
        cell = rows[t.name].split("|")[1]
        missing = {p for p in t.input_schema.get("properties", {}) if not re.search(rf"\b{p}\b", cell)}
        assert not missing, f"{t.name}: parameters {missing} not in its row of docs/using/tools.md"


def test_mcp_prompts_and_resources_documented(server):
    _, prompts, (resources, templates) = server
    text = page("using/tools.md")
    assert table_keys(text, "Prompts") == {p.name for p in prompts}, "prompts table vs registered prompts"
    for p in prompts:
        cell = table_rows(text)[p.name].split("|")[1]
        for a in p.arguments or []:
            assert re.search(rf"\b{a.name}\b", cell), f"prompt {p.name}: argument {a.name} not documented"
    documented = set(re.findall(r"`(b123d-print://[\w/{}+-]+)`", text.split("## Resources\n", 1)[1]))
    registered = {str(r.uri) for r in resources} | {t.uri_template for t in templates}
    assert documented == registered, "resources table vs registered resources and resource templates"


def test_skill_lists_every_tool_and_prompt(server):
    """The Claude Code skill names the tools and prompts too; keep it complete."""
    tools, prompts, _ = server
    skill = code_names((ROOT / "skills/cad-parts/SKILL.md").read_text(encoding="utf-8"))
    missing = {t.name for t in tools} | {p.name for p in prompts}
    assert not (missing - skill), f"skills/cad-parts/SKILL.md does not mention {missing - skill}"


def _flags(parser: argparse.ArgumentParser) -> set[str]:
    return {o for a in parser._actions for o in a.option_strings if o not in ("-h", "--help")}


def test_mcp_server_flags_documented():
    from b123d_print.mcp_server import build_parser

    documented = code_names(page("getting-started/mcp-clients.md"))
    assert not (_flags(build_parser()) - documented), "b123d-print-mcp flags missing from mcp-clients.md"


# --- CLI ---------------------------------------------------------------------------------------


def _commands(parser: argparse.ArgumentParser, prefix: tuple = ()):
    yield prefix, parser
    for a in parser._actions:
        if isinstance(a, argparse._SubParsersAction):
            for name, sub in a.choices.items():
                yield from _commands(sub, prefix + (name,))


def _command_rows() -> list[list[str]]:
    """The words of each command in the Commands table of cli.md: `printer use <name>` -> [printer, use, <name>]."""
    section = page("getting-started/cli.md").split("## Commands\n", 1)[1].split("\n## ", 1)[0]
    return [r.split() for r in re.findall(r"^\|\s*`([^`]+)`", section, re.M)]


def test_cli_documented():
    """Every command has a row in cli.md's Commands table, and every flag is on the page."""
    from b123d_print.cli import build_parser

    rows = _command_rows()
    names = code_names(page("getting-started/cli.md"))
    for path, parser in _commands(build_parser()):
        if path and not any(isinstance(a, argparse._SubParsersAction) for a in parser._actions):
            assert any(r[: len(path)] == list(path) for r in rows), f"command {' '.join(path)!r} has no row in cli.md"
        missing = _flags(parser) - names
        assert not missing, f"b123d-print {' '.join(path)}: flags {missing} not in docs/getting-started/cli.md"


def test_cli_page_has_no_stale_commands():
    from b123d_print.cli import build_parser

    real = [list(p) for p, _ in _commands(build_parser()) if p]
    for r in _command_rows():
        assert r[:1] in real and (r[0] != "printer" or r[:2] in real), f"cli.md documents {' '.join(r)!r}, which does not exist"


def test_part_script_flags_documented():
    """`uv run parts/x/x.py --flag`: the runner's flags are on the CLI page too."""
    import inspect

    from b123d_print import project

    flags = set(re.findall(r'add_argument\("(--[\w-]+)"', inspect.getsource(project.run)))
    assert flags and not (flags - code_names(page("getting-started/cli.md")))


# --- settings and environment ------------------------------------------------------------------


def test_settings_documented():
    """The Keys table in settings.md is exactly the config.Settings fields a config file may set."""
    from b123d_print.config import Settings

    keys = {f.name for f in dataclasses.fields(Settings)} - {"root"}
    assert table_keys(page("using/settings.md"), "Keys") == keys


def test_workspace_template_mentions_every_setting():
    from b123d_print.config import Settings

    template = (ROOT / "src/b123d_print/data/b123d-print.toml").read_text(encoding="utf-8")
    keys = {f.name for f in dataclasses.fields(Settings)} - {"root", "printer", "material"}
    assert {k for k in keys if not re.search(rf"^#?\s*{k}\s*=", template, re.M)} == set()


def test_env_vars_documented():
    """Every B123D_PRINT_* variable the package or the Docker image reads is in settings.md, and vice versa."""
    used = set()
    for f in [*(ROOT / "src").rglob("*.py"), ROOT / "Dockerfile"]:
        used |= set(re.findall(r"B123D_PRINT_[A-Z_]+", f.read_text(encoding="utf-8")))
    documented = table_keys(page("using/settings.md"), "Environment variables")
    assert used == documented


# --- part scripts ------------------------------------------------------------------------------


def test_check_api_documented():
    """Each check class (and View) has a section in checks-api.md listing exactly its arguments."""
    import b123d_print as bp

    text = page("scripts/checks-api.md")
    for cls in (bp.Wall, bp.Overhang, bp.ThinFeature, bp.Holes, bp.BedEdge, bp.Gap, bp.Probe, bp.Overlap, bp.Fit, bp.View):
        assert f"## `{cls.__name__}`" in text, f"no section for {cls.__name__} in docs/scripts/checks-api.md"
        documented = table_keys(text, f"`{cls.__name__}`")
        assert documented == {f.name for f in dataclasses.fields(cls)}, f"{cls.__name__} arguments"


def test_check_classes_are_all_covered():
    """A new dataclass check exported from b123d_print needs a section (and a line in the test above)."""
    import b123d_print as bp

    checks = {n for n in bp.__all__ if dataclasses.is_dataclass(getattr(bp, n)) and hasattr(getattr(bp, n), "run")}
    assert checks == {"Wall", "Overhang", "ThinFeature", "Holes", "BedEdge", "Gap", "Probe", "Overlap", "Fit"}


def test_examples_documented():
    from b123d_print.cli import examples

    sections = set(re.findall(r"^## `(\w+)`", page("scripts/examples.md"), re.M))
    assert sections == set(examples())


# --- site structure ----------------------------------------------------------------------------


def test_every_page_in_nav():
    """mkdocs --strict also catches this; here it fails fast without building the site."""
    nav = (ROOT / "mkdocs.yml").read_text(encoding="utf-8").split("\nnav:", 1)[1]
    in_nav = set(re.findall(r":\s*([\w/-]+\.md)\s*$", nav, re.M))
    on_disk = {str(p.relative_to(DOCS)) for p in DOCS.rglob("*.md")}
    assert in_nav == on_disk


def test_readme_site_links():
    """Links from README.md into the site point at pages that exist."""
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    links = re.findall(re.escape(SITE) + r"([\w/-]*)", readme)
    assert links, "README.md should link into the docs site"
    for link in links:
        path = link.split("#")[0].strip("/")
        assert not path or (DOCS / f"{path}.md").is_file() or (DOCS / path / "index.md").is_file(), link


def test_readme_images_exist():
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    for img in re.findall(r"\]\((docs/images/[^)]+)\)", readme):
        assert (ROOT / img).is_file(), img
