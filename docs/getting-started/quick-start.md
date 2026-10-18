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

    (Windows and other ways: the [uv install page](https://docs.astral.sh/uv/getting-started/installation/).)

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

        If it then says "uvx not found", put the full path from `which uvx` as `command`.

    Cursor, VS Code, Gemini CLI, Codex and others: [Connect your MCP client](mcp-clients.md).

3. **Restart the assistant.**

## Then ask

> *"Design a 40 mm round spacer, 10 mm tall, with an M3 hole."*

The assistant asks you to confirm the dimensions, designs the part, checks it and saves the
files in your parts folder, under `parts/<name>/out/` (for example
`~/parts/parts/spacer/out/spacer.3mf`), ready for your slicer.

The very first start downloads a few hundred MB (mostly the geometry engine) and can take a few
minutes; later starts are fast. If your assistant gives up waiting, see
[Troubleshooting](../troubleshooting.md).

!!! note "Pictures"
    The assistant checks its own work by looking at the renders and cross-sections it makes.
    Claude Desktop and Claude Code pass those pictures to the model; check your assistant's docs
    for others. Without it the print checks still run, but look at the PNGs in `out/` yourself.

## Next

- [How a session goes](../using/workflow.md): what to expect, and how to describe a part.
- Calibrate [hole compensation](../using/hole-compensation.md) before you print anything with
  holes that matter.
- Parts on a home server, many agents, or Docker: [Advanced: run it on another machine](../advanced/index.md).
- Other ways in: the [Claude Code plugin](mcp-clients.md#claude-code) (adds a skill that points
  at the workflow), or the [CLI and Python](cli.md) for agents that run shell commands, or by
  hand (no sandbox: it runs your own scripts).
