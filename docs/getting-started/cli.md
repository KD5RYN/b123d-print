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
| `build [parts] [--variant v] [--formats f] [--only pieces]` | export + section views, report sizes and each piece's faces and build time; `--formats` overrides the `formats` setting; `--only a,b` builds and exports only those pieces of `build()` ([lazy pieces](../scripts/convention.md#big-and-multi-piece-projects)) |
| `check [parts] [--variant v] [-v/--verbose] [--json]` | run the checks; exit code 1 on any failure; `-v` also lists passing checks |
| `metrics [parts] [--variant v] [--style s] [--up +Y] [--json]` | the [design review](../using/design-review.md) numbers and the suggestions the part's style triggers (filament roughly ±20 %, time a rough estimate); never fails |
| `orient [parts] [--variant v] [--piece name] [--load X] [--image] [--json]` | rank the ways to put each part on the bed: supports, contact, height, time, bridges, tip-over, the load against the layers; prints the `Rot(...)` to apply in `build(d)` (see [suggest_orientation](../using/tools.md#suggest_orientation)); `--image` renders the top choice to `out/<part>_orient.png`; never fails, changes nothing |
| `faces <part> [--variant v] [--part name] [--highlight ID] [--json]` | the part's flat faces with their ids, holes and sides, for a face template; `--highlight` draws one in red ([fit-test templates](../using/templates.md)) |
| `template <part> --slice XY:3 \| --face ID \| --crop x,y,z:sx,sy,sz [--thickness t] [--no-label] [--no-base] [--name id] [--variant v] [--part name] [--formats f]` | make a [fit-test template](../using/templates.md), write it to `out/` and check it; exit code 1 if a check fails |
| `view <part> [--variant v] [--parts a,b] [--assembly] [--open]` | write `out/<part>_view.html`, a self-contained [3D view](../using/formats.md#3d-view-in-the-browser) of the part (viewer and model inline: opens offline, from `file://`); the printable parts on the bed, or `--assembly`; `--open` also opens the browser |
| `styles [name]` | list the [design styles](../using/design-review.md#custom-styles) and where each comes from (workspace, user, built-in), or show one with `based_on` applied |
| `printer list [words]` | search the printer profiles |
| `printer show [name]` | show a printer (default: the active one) |
| `printer use <name> [--material m]` | set the active printer (and material); `generic` clears it |
| `printer hole-comp <value>` | store a measured hole compensation for the active printer + material |
| `printer calibrate <key> <value>` | store a value measured with a calibration coupon (`hole_comp`, `hole_comp_h`, `clearance`, `press_fit`, `free_fit`, `pip_clearance`, `max_overhang`, `max_bridge`) for the active printer + material |
| `compare <reference> <candidate> [--json] [--image png] [--threshold name=value] [--samples n] [--no-icp] [--seed n]` | measure a part against a reference (STL, 3MF or STEP): differences, a 0-100 score, pass/fail; exit code 1 on fail ([comparing parts](../using/compare.md)) |
| `to-step <in.stl/3mf> [-o/--output out.step] [--scale s] [--max-triangles n] [--no-merge]` | convert a mesh to a STEP solid, the same way [`import_model`](../using/remix.md) does: coplanar triangles merged into faces, small gaps closed; reports faces before and after merging and whether curves stayed faceted |
| `setup-ssh --key <file.pub> --workspace <name> [--host h] [--add] [--authorized-keys file]` | on the server: the `authorized_keys` line that gives one client key the MCP server in one workspace, and the client config to match; `--add` writes it ([Remote over SSH](ssh.md)) |
| `ssh-serve --workspace <folder> [--dest user@host] [--timeout s] [--check-timeout s]` | the forced command in that line: runs the MCP server, `pull`, `push` or `version` as `$SSH_ORIGINAL_COMMAND` asks, refuses anything else; not for running by hand |
| `pull <part> --from user@host [--formats f] [--variant v] [-o/--out folder] [--ssh cmd]` | on the client: copy a part from an SSH server into `parts/<part>/` of the project folder (`-o`, default the current one): the script, `out/` (narrowed by `--formats` / `--variant`) and `ref/`, the same layout as a local install (`--ssh` passes ssh options, e.g. `'ssh -i key -p 2222'`) |
| `push <file> --part <name> --to user@host [--name n] [--overwrite] [--ssh cmd]` | on the client: copy a model to [remix](../using/remix.md) (STL, 3MF or STEP, up to 50 MB) to an SSH server, into `parts/<name>/ref/` |
| `config` | the settings in effect, and which config files were found |
| `list` | parts in the workspace |
| `examples` | the bundled example parts |
| `mcp [options]` | run the MCP server, the same as `b123d-print-mcp` with all its options; lets `uvx b123d-print mcp` start it |

Global options, before the command: `--root <folder>` (the workspace; default the nearest
folder with a `b123d-print.toml`, else the current folder) and `--version`.

`parts` is a list of part names or script paths; without it, `build`, `check`, `metrics` and `orient` take every part
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
| `--only <pieces>` | comma-separated piece names from `build()`: build and export only those, without the checks |
| `--no-check` | export only, skip the checks |

## From Python

Everything the CLI and the server use is importable from `b123d_print`: `export`, `render`,
`section`, the check classes (see [Checks API](../scripts/checks-api.md)), `load_settings`,
`hole_comp`, `clearance` and `printer`.
