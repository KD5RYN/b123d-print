# Quick start

1. Install [uv](https://docs.astral.sh/uv/getting-started/installation/). It fetches Python 3.12
   and every pinned dependency for you.
2. Add the server to your MCP client — Claude Desktop shown,
   [others here](mcp-clients.md):

    ```json
    {
      "mcpServers": {
        "b123d-print": {
          "command": "uvx",
          "args": ["--from", "git+https://github.com/KD5RYN/b123d-print", "b123d-print-mcp",
                   "--workspace", "/Users/you/parts"]
        }
      }
    }
    ```

3. Restart the client and ask: *"Design a 40 mm round spacer, 10 mm tall, with an M3 hole."*
   Files land in `/Users/you/parts/parts/<name>/out/`.

The first start downloads a few hundred MB (mostly OpenCascade, the geometry kernel) and can
take a few minutes; later starts are fast. See [Troubleshooting](../troubleshooting.md) if your
client gives up waiting.

!!! note "Images"
    `render_preview` and `section` return PNG images. The model can only check its own work if
    your client passes tool-result images to the model. Claude Desktop and Claude Code do; check
    your client's docs for others. Without it the checks still run, but the model designs blind
    — look at the PNGs in `out/` yourself.

Next: [how a session goes](../using/workflow.md), and calibrate
[hole compensation](../using/hole-compensation.md) before you print anything with holes that
matter.

## Ways to use it

| Method | When | Sandbox |
| --- | --- | --- |
| **[MCP server via `uvx`](mcp-clients.md)** | any MCP client; the normal way | yes (macOS; Linux with bubblewrap) |
| **[MCP server in Docker](docker.md)** | strongest isolation, or Windows | the container |
| **[Claude Code plugin](mcp-clients.md#claude-code)** | Claude Code; adds a skill that points at the workflow | yes |
| **[CLI / Python](cli.md)** | agents that run shell commands, or by hand | no — runs your own scripts |
