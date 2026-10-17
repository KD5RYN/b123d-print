# CLI and Python (no MCP)

For agents that run shell commands, and for you:

```bash
uv tool install b123d-print
```

(`pip install b123d-print` works too, in a Python 3.12 environment. For unreleased code:
`uv tool install git+https://github.com/KD5RYN/b123d-print`.)

```bash
b123d-print init ~/parts && cd ~/parts
```

```bash
b123d-print new bracket
```

Edit `parts/bracket/bracket.py` (or let your agent do it), then:

```bash
b123d-print build bracket --formats 3mf,png
```

```bash
b123d-print check
```

!!! warning
    The CLI does **not** sandbox: it runs part scripts like any Python. Use it for scripts you
    wrote or read. Model-written scripts are safer through the [MCP server](mcp-clients.md).

## Commands

| Command | Does |
| --- | --- |
| `init [dir] [--update-agents]` | create a workspace: `b123d-print.toml`, `AGENTS.md`, `parts/`; `--update-agents` replaces `AGENTS.md` with this version's text |
| `new <name> [-d/--description text] [--from <example>]` | scaffold `parts/<name>/<name>.py` from the template, or from a bundled example |
| `build [parts] [--variant v] [--formats f]` | export + section views, report sizes; `--formats` overrides the `formats` setting |
| `check [parts] [--variant v] [-v/--verbose] [--json]` | run the checks; exit code 1 on any failure; `-v` also lists passing checks |
| `printer list [words]` | search the printer profiles |
| `printer show [name]` | show a printer (default: the active one) |
| `printer use <name> [--material m]` | set the active printer (and material); `generic` clears it |
| `printer hole-comp <value>` | store a measured hole compensation for the active printer + material |
| `printer calibrate <key> <value>` | store a value measured with a calibration coupon (`hole_comp`, `hole_comp_h`, `clearance`, `press_fit`, `free_fit`, `pip_clearance`, `max_overhang`, `max_bridge`) for the active printer + material |
| `config` | the settings in effect, and which config files were found |
| `list` | parts in the workspace |
| `examples` | the bundled example parts |

Global options, before the command: `--root <folder>` (the workspace; default the nearest
folder with a `b123d-print.toml`, else the current folder) and `--version`.

`parts` is a list of part names or script paths; without it, `build` and `check` take every part
in the workspace. Each command's full `--help` output is in the [Reference](../reference.md#b123d-print).

## Agents and `AGENTS.md`

`AGENTS.md` (written by `init`) carries the workflow for agents that read it, such as Codex and
Cursor; for Claude Code put `@AGENTS.md` in `CLAUDE.md`. Its text is in
[Workflow rules](../scripts/rules.md).

## Running a part script directly

A part script ends with `run(__file__)`, so it runs on its own:

```bash
uv run parts/bracket/bracket.py
```

| Option | Does |
| --- | --- |
| `--variant <key>` | build one variant (`standard` for the default); default: all |
| `--formats <list>` | comma-separated from `step,stl,3mf,png` or `all`; default: the `formats` setting |
| `--no-check` | export only, skip the checks |

## From Python

Everything the CLI and the server use is importable from `b123d_print`: `export`, `render`,
`section`, the check classes (see [Checks API](../scripts/checks-api.md)), `load_settings`,
`hole_comp`, `clearance` and `printer`.
