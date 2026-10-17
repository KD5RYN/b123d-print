# Connect your MCP client

Every client runs the same command:

```bash
uvx --from b123d-print b123d-print-mcp --workspace <folder>
```

The **workspace** is the folder that holds your parts (`parts/<name>/<name>.py`); it is created
if missing. Without `--workspace` the server uses `$B123D_PRINT_WORKSPACE`, else the folder the
client starts it in.

## Which version

`--from b123d-print` runs the latest release from [PyPI](https://pypi.org/project/b123d-print/).
In place of `b123d-print` in any config on this page:

| `--from` | Runs |
| --- | --- |
| `b123d-print` | the latest release (uvx caches it; see [Updating](../updating.md)) |
| `b123d-print==0.1.0` | exactly that release |
| `git+https://github.com/KD5RYN/b123d-print` | the latest unreleased code on `main` |

## Server options

| Option | Default | Does |
| --- | --- | --- |
| `--workspace <folder>` | `$B123D_PRINT_WORKSPACE`, else the current folder | where parts and the workspace config live |
| `--timeout <seconds>` | `$B123D_PRINT_TIMEOUT`, else 120 | time limit for each build, render, section, check or export |

The full `--help` output is in the [Reference](../reference.md#b123d-print-mcp).

## Claude Desktop

Settings → Developer → Edit Config (`claude_desktop_config.json`): the block in
[Quick start](quick-start.md). Always pass `--workspace`. If the server fails with "uvx not
found", use the full path from `which uvx` as `command` (desktop apps don't see your shell's
`PATH`).

## Claude Code

```bash
claude mcp add b123d-print -- uvx --from b123d-print b123d-print-mcp --workspace ~/parts
```

Or the plugin (MCP server + skill; uses the project folder as workspace), inside Claude Code:

```text
/plugin marketplace add KD5RYN/b123d-print
/plugin install b123d-print@b123d-print
```

## Gemini CLI

`~/.gemini/settings.json` (or `.gemini/settings.json` in a project):

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

## Cursor

`~/.cursor/mcp.json`, or `.cursor/mcp.json` in a project: the same `mcpServers` block as for
[Gemini CLI](#gemini-cli).

## VS Code (Copilot agent mode)

`.vscode/mcp.json`:

```json
{
  "servers": {
    "b123d-print": {
      "type": "stdio",
      "command": "uvx",
      "args": ["--from", "b123d-print", "b123d-print-mcp", "--workspace", "${workspaceFolder}"]
    }
  }
}
```

## Codex CLI

`~/.codex/config.toml`:

```toml
[mcp_servers.b123d-print]
command = "uvx"
args = ["--from", "b123d-print", "b123d-print-mcp", "--workspace", "/Users/you/parts"]
```

## Other clients

Any client that can start a stdio MCP server: command `uvx`, arguments as above.

To run the server in a container instead of through `uvx`, see [Docker](docker.md).
