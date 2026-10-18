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
| `b123d-print==0.2.0` | exactly that release |
| `git+https://github.com/KD5RYN/b123d-print` | the latest unreleased code on `main` |

## Server options

| Option | Default | Does |
| --- | --- | --- |
| `--workspace <folder>` | `$B123D_PRINT_WORKSPACE`, else the current folder | where parts and the workspace config live |
| `--timeout <seconds>` | `$B123D_PRINT_TIMEOUT`, else 120 | time limit for each build, render, section or export |
| `--check-timeout <seconds>` | `$B123D_PRINT_CHECK_TIMEOUT`, else 300 (or `--timeout` if longer) | time limit for each `check`, which builds the part and runs every check (a remix's original too); shortly before it, the checks stop and return what they found, with a timeout FAIL naming the check that was running ([time limit](../using/checks.md#time-limit)) |
| `--max-builds <n>` | `$B123D_PRINT_MAX_BUILDS`, else half the CPU cores | build processes at once, across all clients and all of this user's server processes (one per [SSH](ssh.md) connection); more calls wait. A `check` splits over up to this many ([parallel checks](../using/checks.md#time-limit)) |
| `--transport <mode>` | `$B123D_PRINT_TRANSPORT`, else `stdio` | `stdio` or `http`; `http` serves Streamable HTTP at `/mcp`: see [Over the network](http.md) |
| `--host <address>` | `$B123D_PRINT_HOST`, else `127.0.0.1` | HTTP: address to bind |
| `--port <port>` | `$B123D_PRINT_PORT`, else 8000 | HTTP: port |
| `--allowed-hosts <names>` | `$B123D_PRINT_ALLOWED_HOSTS` | HTTP: comma-separated `Host` header values to accept (DNS-rebinding check, behind a proxy) |
| `--shutdown-grace <seconds>` | `$B123D_PRINT_SHUTDOWN_GRACE`, else 30 | HTTP: on SIGTERM or Ctrl-C, how long running calls may finish before their builds are killed |
| `--public-url <url>` | `$B123D_PRINT_PUBLIC_URL` | HTTP: the base URL clients reach the server at, used in download links (e.g. `https://cad.example.com`); default: the request's `Host`, and proxy headers for hosts in `--allowed-hosts` |
| `--link-ttl <seconds>` | `$B123D_PRINT_LINK_TTL`, else 3600 | HTTP: how long a download link stays valid |
| `--retention-days <days>` | `$B123D_PRINT_RETENTION_DAYS`, else 30 | HTTP: [remove a named workspace](http.md#workspace-retention) nobody has used for this many days (checked at startup and hourly, never while in use); `0` = never |
| `--tokens-file <path>` | `$B123D_PRINT_TOKENS_FILE` | HTTP: [named tokens](http.md#tokens), each limited to workspaces; re-read when it changes |
| `--job-queue <folder>` | `$B123D_PRINT_JOB_QUEUE` | HTTP: hand builds to a separate `worker` process through this folder (the Compose setup's network-less worker) |
| `--insecure-no-auth` | off | HTTP: run without a token (otherwise `$B123D_PRINT_TOKEN` or `$B123D_PRINT_TOKEN_FILE` is required) |
| `--healthcheck` | | check a running HTTP server's `/health` and exit (the Docker image's health check) |

Subcommands: `b123d-print-mcp token add|list|revoke` manages the [tokens file](http.md#tokens), and
`b123d-print-mcp worker --queue <folder>` runs the builds a server with `--job-queue` hands over
(`--check` exits 0 while a worker's heartbeat is fresh; the Compose health check).

The full `--help` output is in the [Reference](../reference.md#b123d-print-mcp).

## Claude Desktop

Settings → Developer → Edit Config (`claude_desktop_config.json`): the block in
[Quick start](quick-start.md). Always pass `--workspace`. If the server fails with "uvx not
found", use the full path from `which uvx` (Windows: `where.exe uvx`) as `command` (desktop apps don't see your shell's
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

Any client that can start a stdio MCP server: command `uvx`, arguments as above. To keep the
parts on another machine, such as a home server, see [Remote over SSH](ssh.md); for many agents
sharing one server, [Over the network (HTTP)](http.md).

To run the server in a container instead of through `uvx`, see [Docker](docker.md).
