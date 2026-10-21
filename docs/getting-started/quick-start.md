# Quick start

b123d-print's MCP server is a plug-in that gives your AI assistant CAD tools: it can then design
a part, look at it, check it for printing problems and save files for your slicer. It runs on
your own computer, and setup takes a couple of minutes.

## The easy way: ask your assistant

Paste this into your AI assistant (Claude Code, Claude Desktop, Cursor, Gemini CLI, Codex, …):

```text
Install the b123d-print MCP server for me. It runs with
`uvx --from b123d-print b123d-print-mcp --workspace <folder>`
where <folder> is a folder for my parts, such as ~/parts.
Install uv first if it is missing (https://docs.astral.sh/uv/).
Add the server to your MCP settings, tell me when to restart you,
and after the restart check that its tools (list_parts, new_part,
build_part, ...) are available.
```

The assistant will probably ask to run a few commands (to install uv and to add the server).
That is expected: say yes. Assistants that can't run commands, such as a chat-only app, will
tell you the steps instead.

## By hand

1. **Install [uv](https://docs.astral.sh/uv/getting-started/installation/)**, a small tool that
   fetches Python and everything else b123d-print needs. On macOS or Linux:

    ```bash
    curl -LsSf https://astral.sh/uv/install.sh | sh
    ```

    On Windows, in PowerShell (installs for your account only, no admin):

    ```powershell
    powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
    ```

    (Other ways: the [uv install page](https://docs.astral.sh/uv/getting-started/installation/).)

2. **Add the server to your assistant.**

    === "Claude Code"

        ```bash
        claude mcp add b123d-print -- uvx --from b123d-print b123d-print-mcp --workspace ~/parts
        ```

    === "Claude Desktop"

        Settings → Developer → Edit Config, and add (change the folder to yours):

        ```json
        {
          "mcpServers": {
            "b123d-print": {
              "command": "uvx",
              "args": ["--from", "b123d-print", "b123d-print-mcp", "--workspace", "/Users/you/parts"]
            }
          }
        }
        ```

        On Windows the folder is written with doubled backslashes:
        `"C:\\Users\\you\\parts"`.

        If it then says "uvx not found", put the full path from `which uvx` (Windows:
        `where.exe uvx`) as `command`.

    Cursor, VS Code, Gemini CLI, Codex and others: [Connect your MCP client](mcp-clients.md).

3. **Restart the assistant.**

## Tell it your printer

Before the first part, ask:

> *"Set up b123d-print for my printer."*

(or pick the `setup_workspace` prompt from your client's prompt menu or slash commands). The
assistant asks for your printer, material, export formats and default style, saves them, and
offers the calibration coupons in order. Without a printer, b123d-print runs in generic mode:
no build-volume check and generic limits. From a terminal, `b123d-print setup` asks the same
questions ([CLI](cli.md)).

## Then ask

> *"Design a 40 mm round spacer, 10 mm tall, with an M3 hole."*

The assistant asks you to confirm the dimensions, designs the part, checks it and saves the
files in your parts folder, under `parts/<name>/out/`. The file for your slicer is in
`out/print/` (for example `~/parts/parts/spacer/out/print/spacer.3mf`); `out/README.md` says
what is where. Only the script and a few settings need a backup: see
[What to save](../using/what-to-save.md). To go back to an earlier version of a part later,
start a [version history](../using/what-to-save.md#versions) (`b123d-print init --git`).

The very first start downloads a few hundred MB (mostly the geometry engine) and can take a few
minutes; later starts are fast. If your assistant gives up waiting, see
[Troubleshooting](../troubleshooting.md).

!!! note "Pictures"
    The assistant checks its own work by looking at the renders and cross-sections it makes.
    Claude Desktop and Claude Code pass those pictures to the model; check your assistant's docs
    for others. Without it the print checks still run, but look at the PNGs in `out/images/` yourself.

## Next

- Follow a whole session from start to finish: [your first bracket](../tutorials/first-bracket.md)
  or [remix a downloaded STL](../tutorials/remix-stl.md).
- [How a session goes](../using/workflow.md): what to expect, and how to describe a part.
- Set your slicer's [hole compensation](../using/hole-compensation.md) from the hole coupon
  before you print anything with holes that matter.

!!! warning "Hole compensation"
    Holes are drawn true to size; hole shrinkage is set in your slicer (X-Y hole
    compensation, from the [hole coupon](../using/hole-compensation.md)). Turning on `hole_comp` bakes
    the correction into the files for one printer, with the slicer's hole compensation then at 0.

- Parts on a home server, many agents, or Docker: [Advanced: run it on another machine](../advanced/index.md).
- Other ways in: the [Claude Code plugin](mcp-clients.md#claude-code) (adds a skill that points
  at the workflow), or the [CLI and Python](cli.md) for agents that run shell commands, or by
  hand (no sandbox: it runs your own scripts).
