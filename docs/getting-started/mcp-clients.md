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
| `--timeout <seconds>` | `$B123D_PRINT_TIMEOUT`, else 240 | time limit for each build, render, section or export (under the 300 s an MCP client waits for a result) |
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

## Which clients

Each client below has its own section. "Untested" means the snippet comes from that client's
own docs (linked) and nobody has run b123d-print with it yet: tell us how it went in an
[issue](https://github.com/KD5RYN/b123d-print/issues).

| Client | Local (stdio) | Remote (HTTP) with a Bearer token | Images reach the model | MCP prompts | Tested |
| --- | --- | --- | --- | --- | --- |
| [Claude Desktop](#claude-desktop) | yes | through a [local proxy](#remote-server-from-a-stdio-only-client) | yes | yes | yes |
| [Claude Code](#claude-code) | yes | yes (`--header`) | yes | yes | yes |
| [claude.ai](#claudeai-web-and-mobile-custom-connectors) (web, mobile) | no | only with the Request headers beta | yes | yes | untested |
| [ChatGPT](#chatgpt) | no | no (OAuth or no auth only) | not documented | not documented | untested |
| [Gemini CLI](#gemini-cli) | yes | see its docs | not documented | not documented | |
| [Cursor](#cursor) | yes | see its docs | not documented | not documented | |
| [VS Code](#vs-code-copilot-agent-mode) | yes | see its docs | not documented | not documented | |
| [Codex CLI](#codex-cli) | yes | see its docs | not documented | not documented | |
| [Grok Build CLI](#grok) (xAI) | yes | yes (`--header`) | not documented | not documented | untested |
| [Windsurf](#windsurf) | yes | yes (`headers`) | not documented | yes | untested |
| [Zed](#zed) | yes | yes (`headers`) | not documented | yes | untested |
| [LM Studio](#lm-studio) | yes | yes (`headers`) | not documented | not documented | untested |

**Images matter.** The workflow has the model look at its own renders and sections
(`render_preview`, `section`). If your client doesn't pass tool-result images to the model, the
assistant works blind: ask it to render the part and describe what it sees, and check the PNGs
in `parts/<name>/out/` yourself. "Not documented" means the client's MCP docs don't say.
**Prompts** (`design_review`, `new_part_workflow`, ...) are shortcuts; every tool works without them.

## Claude Desktop

Settings → Developer → Edit Config (`claude_desktop_config.json`): the block in
[Quick start](quick-start.md). Always pass `--workspace`. If the server fails with "uvx not
found", use the full path from `which uvx` (Windows: `where.exe uvx`) as `command` (desktop apps don't see your shell's
`PATH`).

## Claude Code

```bash
claude mcp add b123d-print -- uvx --from b123d-print b123d-print-mcp --workspace ~/parts
```

Or the plugin (MCP server + skill; uses the project folder as workspace), in one command:

```bash
claude plugin install b123d-print --marketplace KD5RYN/b123d-print
```

Inside a Claude Code session the same works as `/plugin install b123d-print --marketplace KD5RYN/b123d-print`.
On older Claude Code versions use two steps: `/plugin marketplace add KD5RYN/b123d-print`, then
`/plugin install b123d-print@b123d-print`. Update later with `claude plugin update b123d-print@b123d-print`.

The server is also listed in the [MCP Registry](https://registry.modelcontextprotocol.io) as
`io.github.KD5RYN/b123d-print`; clients that read the registry start it with `uvx b123d-print mcp`.

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

## claude.ai (web and mobile): custom connectors

A custom connector (Customize → Connectors → **Add custom connector**: a name and the server's
URL) connects claude.ai to a **remote** server only, and the connection comes from Anthropic's
cloud, not from your device: the server must be reachable over the public internet from
Anthropic's IP ranges, so a server on your home network isn't reachable without a public HTTPS
address
([custom connectors](https://support.claude.com/en/articles/11175166-getting-started-with-custom-connectors-using-remote-mcp),
[building connectors](https://claude.com/docs/connectors/building)).

Connectors sign in with OAuth or not at all. Sending a fixed `Authorization` header ("Request
headers", entered once by an organization Owner) is a beta for a limited set of organizations
([authentication](https://claude.com/docs/connectors/building/authentication)). b123d-print's
HTTP server takes only a Bearer token, so:

- **With the Request headers beta** (Team or Enterprise): the Owner adds the connector with the
  URL `https://<your-server>/mcp` and the header `Authorization: Bearer <token>` from
  [`token add`](http.md#connect-a-new-ai). Images and prompts are supported; a tool call may
  take up to 240 s, the same as b123d-print's default `--timeout`.
- **Otherwise:** use **Claude Desktop** with the local (stdio) server from
  [Quick start](quick-start.md); it uses the same Claude account. For a remote server, see
  [a local proxy](#remote-server-from-a-stdio-only-client). See also
  [clients that can't send a header](http.md#clients-that-cant-send-a-header).

## ChatGPT

ChatGPT adds a custom MCP server in its web settings (chatgpt.com/plugins → **Add custom MCP
server**) by URL, over Streamable HTTP, at a public HTTPS address or through OpenAI's Secure MCP
Tunnel ([connect from ChatGPT](https://developers.openai.com/plugins/deploy/connect-chatgpt),
[secure MCP tunnels](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)). It offers
no authentication, OAuth, or a mix, and says it has no API-key or Bearer-token input and doesn't
send custom headers ([authentication](https://developers.openai.com/plugins/build/auth)). Local
(stdio) servers in the ChatGPT desktop app are limited to approved partners
([desktop-only plugins](https://developers.openai.com/plugins/deploy/desktop-only)).

So **ChatGPT can't connect to b123d-print today**: the HTTP server needs a Bearer token, and
ChatGPT can't send one. Don't run the server with `--insecure-no-auth` on a public address to
get around it: anyone who finds the URL can then run part scripts on your machine (in the
[sandbox](../using/sandbox.md), but still). OpenAI's tunnel can start a local stdio server
(`tunnel-client --mcp-command ...`); it's untested with b123d-print, and whoever can use the
connector in your ChatGPT workspace reaches the server. Use another client from this page
until b123d-print supports OAuth.

## Grok

Two different tools are called "grok CLI":

- **Grok Build** (xAI's own `grok` CLI): `grok mcp add` or `~/.grok/config.toml`
  (project: `.grok/config.toml`); stdio and HTTP, static headers with `--header`
  ([MCP servers](https://docs.x.ai/build/features/mcp-servers)). Untested.

    ```bash
    grok mcp add b123d-print -- uvx --from b123d-print b123d-print-mcp --workspace ~/parts
    grok mcp add --transport http b123d-print https://cad.example.com/mcp --header "Authorization: Bearer ${B123D_TOKEN}"
    ```

    ```toml
    [mcp_servers.b123d-print]
    command = "uvx"
    args = ["--from", "b123d-print", "b123d-print-mcp", "--workspace", "/Users/you/parts"]
    ```

- **superagent-ai/grok-cli** (community, not xAI's): its README says to add servers with
  `/mcps` in the app or under `mcpServers` in `.grok/settings.json`
  ([README](https://github.com/superagent-ai/grok-cli)). Untested.

Both read MCP servers from other tools' configs (Grok Build reads `~/.claude.json`,
`.cursor/mcp.json` and `.mcp.json`), so a token you gave Claude Code at its user scope reaches
Grok too: see [one token per tool](http.md#connect-a-new-ai).

## Windsurf

`~/.codeium/windsurf/mcp_config.json` (Windsurf Next: `~/.codeium/windsurf-next/`), or in the
Devin Desktop app `~/.config/devin/mcp_config.json` (Windows: `%APPDATA%\devin\mcp_config.json`).
stdio, Streamable HTTP and SSE; a remote server takes `serverUrl` and `headers`; tools,
resources and prompts are supported ([Cascade MCP](https://docs.devin.ai/desktop/cascade/mcp),
[Windsurf plugin](https://docs.devin.ai/windsurf/plugins/cascade/mcp)). Untested.

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

Remote: `"b123d-print": {"serverUrl": "https://cad.example.com/mcp", "headers": {"Authorization": "Bearer ${env:B123D_TOKEN}"}}`
(`${env:...}` reads the token from the environment instead of the file).

## Zed

`settings.json` (`zed: open settings file`), under `context_servers`, or Settings → AI → MCP
Servers; tools and prompts are supported. A remote server without an `Authorization` header gets
Zed's OAuth sign-in, which b123d-print doesn't offer, so always set the header
([Zed MCP](https://zed.dev/docs/ai/mcp)). Untested.

```json
{
  "context_servers": {
    "b123d-print": {
      "command": "uvx",
      "args": ["--from", "b123d-print", "b123d-print-mcp", "--workspace", "/Users/you/parts"],
      "env": {}
    }
  }
}
```

Remote: `"b123d-print": {"url": "https://cad.example.com/mcp", "headers": {"Authorization": "Bearer <token>"}}`.

## LM Studio

`mcp.json` (Program tab → Install → Edit mcp.json), in Cursor's `mcpServers` notation, so the
[Cursor](#cursor) block works; a remote server takes `url` and `headers`
([LM Studio MCP](https://lmstudio.ai/docs/app/mcp)). Untested. A local model needs tool calling,
and vision to see the renders, to follow the workflow.

```json
{"mcpServers": {"b123d-print": {"url": "https://cad.example.com/mcp", "headers": {"Authorization": "Bearer <token>"}}}}
```

## Remote server from a stdio-only client

A client that can only start a command (Claude Desktop's config, or any client above without
`headers`) can still reach a [remote HTTP server](http.md): it starts a small local proxy that
speaks stdio to the client and HTTP, with your token, to the server. Two well-known ones:

[mcp-remote](https://github.com/geelen/mcp-remote) (Node.js, `npx`). Put the token in `env`: some
clients (its README names Cursor, Codex CLI and Claude Desktop on Windows) break arguments that
contain spaces, so `Authorization:${AUTH_HEADER}` has none:

```json
{
  "mcpServers": {
    "b123d-print": {
      "command": "npx",
      "args": ["mcp-remote", "https://cad.example.com/mcp", "--header", "Authorization:${AUTH_HEADER}"],
      "env": {"AUTH_HEADER": "Bearer <token>"}
    }
  }
}
```

[mcp-proxy](https://github.com/sparfenyuk/mcp-proxy) (Python, `uvx`). It defaults to SSE, so pass
`--transport streamablehttp`; it reads the token from `API_ACCESS_TOKEN`:

```json
{
  "mcpServers": {
    "b123d-print": {
      "command": "uvx",
      "args": ["mcp-proxy", "--transport", "streamablehttp", "https://cad.example.com/mcp"],
      "env": {"API_ACCESS_TOKEN": "<token>"}
    }
  }
}
```

Either way the token sits in that client's config file in plain text: give the client
[its own token](http.md#connect-a-new-ai). For one person and a home server, [SSH](ssh.md) does the
same job with no token at all.

## Other clients

Any client that can start a stdio MCP server: command `uvx`, arguments as above. To keep the
parts on another machine, such as a home server, see [Remote over SSH](ssh.md); for many agents
sharing one server, [Over the network (HTTP)](http.md).

To run the server in a container instead of through `uvx`, see [Docker](docker.md).
