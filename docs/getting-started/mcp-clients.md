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
| `--max-builds <n>` | `$B123D_PRINT_MAX_BUILDS`, else half the CPU cores | build processes at once, across all clients and all of this user's server processes (one per [SSH](ssh.md) connection); more calls wait, [shared fairly between clients](http.md#several-clients-at-once) over HTTP. A `check` splits over up to 2 of them ([parallel checks](../using/checks.md#time-limit)) |
| `--max-memory <size>` | `$B123D_PRINT_MAX_MEMORY`, else `2g` | memory per build process (`2g`, `1536m`); a build over it fails with a plain message; Linux and Windows ([memory](../using/sandbox.md#memory)); `0` = no limit |
| `--quick-slots <n>` | `$B123D_PRINT_QUICK_SLOTS`, else 1 over HTTP with 2+ build slots, 0 otherwise | build slots (out of `--max-builds`) kept for quick calls (`measure`, `section`, `list_faces`, `list_edges`, `hardware_list`), so they never wait behind long builds; at least one slot stays for long ones |
| `--client-jobs <n>` | `$B123D_PRINT_CLIENT_JOBS`, else 4 | HTTP: calls one client (token) may have running and waiting; more are refused with a message until one finishes; `0` = no cap |
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

Each client below has its own section. **Tested** means we have run b123d-print with that
client, the way listed (on your own machine, stdio, or against a shared server over HTTP).
"Untested" means the snippet comes from that client's own docs (linked) and nobody has run
b123d-print with it yet: tell us how it went in an
[issue](https://github.com/KD5RYN/b123d-print/issues).

| Client | Local (stdio) | Remote (HTTP) with a Bearer token | Images reach the model | MCP prompts | Tested |
| --- | --- | --- | --- | --- | --- |
| [Claude Desktop](#claude-desktop) | yes | through a [local proxy](#remote-server-from-a-stdio-only-client) | yes | yes | **yes** |
| [Claude Code](#claude-code) | yes | yes (`--header`) | yes | yes | **yes** (stdio, HTTP) |
| [claude.ai](#claudeai-web-and-mobile-custom-connectors) (web, mobile) | no | only with the Request headers beta | yes | yes | untested |
| [ChatGPT](#chatgpt) | web: no; the desktop app uses the [Codex config](#codex-cli) | web: no (OAuth or no auth only); desktop: as Codex | not documented | not documented | untested |
| [Gemini CLI](#gemini-cli) | yes | yes (`httpUrl`, `headers`) | yes | not documented | untested (Gemini itself: tested through Antigravity) |
| [Antigravity](#antigravity-agy-cli-and-ide) (`agy` CLI, IDE) with Gemini | yes | yes (`serverUrl`, `headers`) | yes | not documented | **yes** (`agy`, HTTP) |
| [Cursor](#cursor) | yes | see its docs | not documented | not documented | untested |
| [VS Code](#vs-code-copilot-agent-mode) | yes | see its docs | not documented | not documented | untested |
| [Codex CLI](#codex-cli) | yes | yes (`bearer_token_env_var`) | not documented | not documented | **yes** (stdio, HTTP) |
| [Grok Build CLI](#grok) (xAI) | yes | yes (`--header`) | not documented | not documented | **yes** (HTTP) |
| [OpenCode](#opencode) | yes (`"type": "local"`) | yes (`"type": "remote"`, `headers`) | not documented | not documented | **yes** (HTTP, with Ollama `gemma4:31b-cloud`) |
| [Qwen Code](#qwen-code) | yes | yes (`httpUrl`, `headers`) | not documented | not documented | **yes** (HTTP, with Ollama `gemma4:31b-cloud`) |
| [pi](#pi) (pi coding agent) | yes | yes (`url`, `headers`) | not documented | not documented | **yes** (HTTP, with Ollama `gemma4:31b-cloud`) |
| [Windsurf](#windsurf) | yes | yes (`headers`) | not documented | yes | untested |
| [Zed](#zed) | yes | yes (`headers`) | not documented | yes | untested |
| [LM Studio](#lm-studio) | yes | yes (`headers`) | not documented | not documented | untested |

**Images matter.** The workflow has the model look at its own renders and sections
(`render_preview`, `section`). If your client doesn't pass tool-result images to the model, the
assistant works blind: ask it to render the part and describe what it sees, and check the PNGs
in `parts/<name>/out/images/` yourself. "Not documented" means the client's MCP docs don't say.
**Prompts** (`design_review`, `new_part_workflow`, ...) are shortcuts; every tool works without them.

**The rules.** The workflow rules (confirm dimensions before modeling, verify before reporting,
bring the files home) are the `b123d-print://guide` resource and the server's instructions, and
many clients pass neither to the model. If your client doesn't read MCP resources, tell it to
call `read_guide`: the tool returns the same text. The first results (`list_parts`, `new_part`)
also carry a short checklist of the rules most often skipped.

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

Remote (HTTP): Gemini CLI takes `httpUrl` for Streamable HTTP (`url` means SSE there) and
`headers` ([Gemini CLI MCP servers](https://github.com/google-gemini/gemini-cli/blob/main/docs/tools/mcp-server.md)):

```json
{"mcpServers": {"b123d-print": {"httpUrl": "https://cad.example.com/mcp?workspace=<name>", "headers": {"Authorization": "Bearer <token>"}}}}
```

`/mcp` lists the servers and their tools. Tool-result images reach the model as images;
`"trust": true` on the server skips the confirmations. Its shell is not sandboxed unless you turn
the sandbox on, so the usual `download_part` link and `curl` work. Google's newer
[Antigravity CLI](#antigravity-agy-cli-and-ide) uses a different config file and keys.

## Antigravity (`agy` CLI and IDE)

Google Antigravity drives Gemini from the Antigravity app, the IDE and the `agy` CLI
([install](https://antigravity.google/docs/getting-started?tab=cli)). All three read the same
MCP config ([Antigravity MCP](https://antigravity.google/docs/mcp)). Tested: `agy` against a
remote HTTP server.

**Global**, `~/.gemini/config/mcp_config.json`. A remote server takes `serverUrl` (Antigravity
refuses `url` and `httpUrl`) and `headers`:

```json
{
  "mcpServers": {
    "b123d-print": {
      "serverUrl": "https://cad.example.com/mcp?workspace=<name>",
      "headers": {"Authorization": "Bearer <token>"}
    }
  }
}
```

Other agent CLIs don't import this file (unlike `~/.claude.json`), but it fixes one
`?workspace=` for every folder you open.

**Per project**, one workspace per folder: the same block in `.agents/mcp_config.json` in the
project folder ([Antigravity MCP](https://antigravity.google/docs/mcp)), or as a plugin,
`.agents/plugins/b123d-print/plugin.json` with `{"name": "b123d-print"}` next to
`.agents/plugins/b123d-print/mcp_config.json` ([plugins](https://antigravity.google/docs/plugins);
the CLI needs the `name`). Give each project [its own token](http.md#connect-a-new-ai), and keep
`.agents/` out of git when it holds one.

**Local** instead of a server: `"command": "uvx", "args": ["--from", "b123d-print",
"b123d-print-mcp", "--workspace", "/Users/you/parts"]` (or `uvx b123d-print mcp`). The files
are then written straight into the project folder, and nothing needs downloading.

**Reload.** After creating or editing the config, type `/mcp` in `agy` and reload the servers
(or restart `agy`); in the IDE, Manage MCP Servers, then Refresh. A turn already running doesn't pick up new
tools.

**Approvals.** An MCP tool you haven't configured asks before it runs
([Antigravity MCP](https://antigravity.google/docs/mcp)), and the agent modes don't change that:
`accept-edits` approves file edits only ([modes](https://antigravity.google/docs/cli/modes)).
Allow a tool when it asks, or add rules to `permissions.allow` in
`~/.gemini/antigravity-cli/settings.json` (`/settings` in `agy`; the agent can't edit that file)
([permissions](https://antigravity.google/docs/permissions)):

```json
{"permissions": {"allow": ["mcp(b123d-print/*)", "command(unzip)"]}}
```

`mcp(b123d-print/build_part)` allows one tool instead of all of them. Rules match a command's
first words, so **ask the agent for one command at a time**: `unzip ... && ls ...` or a pipe
doesn't match `command(unzip)` and asks again.

**Bringing the files home.** With the terminal sandbox on, `agy`'s shell has no network
([sandbox](https://antigravity.google/docs/sandbox); `enableTerminalSandbox`, or `--sandbox`),
so the `curl` that `download_part` suggests fails. Use the zip inside the result instead:

1. `download_part("<name>", embed=True)`: the zip (up to 8 MB) comes back inside the MCP result,
   and `agy` saves it as a file under
   `~/.gemini/antigravity-cli/brain/<conversation>/.system_generated/steps/<N>/media_0.zip`.
2. `unzip -o <that file> -d <project folder>`: it creates `parts/<name>/...` offline.

Images from `render_preview` and `section` reach the model and are saved next to it the same way
(`media_0.png`). A remote `export` ends with a NEXT STEP that says this; still, tell the agent
to bring the part home if it reports without doing so (the save location is what we saw in a
real session, not from Google's docs).

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

Tested on your own machine (stdio) and against a shared server (HTTP). `~/.codex/config.toml`,
or `.codex/config.toml` in a trusted project; the ChatGPT desktop app and the Codex IDE extension
read the same file ([Codex MCP](https://developers.openai.com/codex/mcp)).

On your machine:

```toml
[mcp_servers.b123d-print]
command = "uvx"
args = ["--from", "b123d-print", "b123d-print-mcp", "--workspace", "/Users/you/parts"]
startup_timeout_sec = 120   # the first start downloads the packages (default 10 s)
tool_timeout_sec = 300      # builds and checks can take minutes (default 60 s)
```

A shared server, with the token in an environment variable (never in the file):

```toml
[mcp_servers.b123d-print]
url = "https://cad.example.com/mcp?workspace=you-codex"
bearer_token_env_var = "B123D_TOKEN"
tool_timeout_sec = 300
```

**Raise `tool_timeout_sec`.** With Codex's 60-second default, a longer build or check ends in a
timeout on the Codex side even though the server finishes it. Run `/mcp` in Codex to see the
server connected.

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
  ([MCP servers](https://docs.x.ai/build/features/mcp-servers)). Tested with b123d-print
  against a shared server over HTTP.

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

## OpenCode

[OpenCode](https://opencode.ai) has its own config format: the servers go under **`"mcp"`**
(not `"mcpServers"`), and a remote server is **`"type": "remote"`** (not `"http"`)
([OpenCode MCP](https://opencode.ai/docs/mcp-servers/)). Put it in `opencode.json` in the
project folder, or in `~/.config/opencode/opencode.json`. Tested against a shared server over
HTTP, with the Ollama model `gemma4:31b-cloud`.

A shared server:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "b123d-print": {
      "type": "remote",
      "url": "https://cad.example.com/mcp?workspace=you-opencode",
      "enabled": true,
      "oauth": false,
      "timeout": 30000,
      "headers": {
        "Authorization": "Bearer {env:B123D_TOKEN}"
      }
    }
  }
}
```

- **`{env:B123D_TOKEN}`** reads the environment variable *named* `B123D_TOKEN`: run
  `export B123D_TOKEN='<token>'` in the terminal you start `opencode` from. Or write the token
  itself, `"Bearer <token>"`, with no `{env:}`, and keep the file private. Putting the token
  *inside* `{env:...}` sends an empty header: the server answers 401 and logs `(bad token)`.
- **`"oauth": false`**: b123d-print uses a fixed token; without it OpenCode may start an OAuth
  login when it sees a 401.
- **`"timeout"`** is how long OpenCode waits for the tool list (default 5 s).
- `?workspace=` must be one the token may use, or the server answers 403. A token with a single
  workspace needs none.

`token add` on the server prints this block filled in ([Tokens](http.md#tokens)). Check with
`opencode mcp list`, or `opencode mcp debug b123d-print` when it fails.

On your own machine:

```json
{
  "$schema": "https://opencode.ai/config.json",
  "mcp": {
    "b123d-print": {
      "type": "local",
      "command": ["uvx", "--from", "b123d-print", "b123d-print-mcp", "--workspace", "/Users/you/parts"],
      "enabled": true,
      "timeout": 120000
    }
  }
}
```

The first start downloads the packages, hence the long `timeout`.

## Qwen Code

[Qwen Code](https://github.com/QwenLM/qwen-code) is built on Gemini CLI and uses the same
format: `~/.qwen/settings.json`, or `.qwen/settings.json` in a project. A remote server is
**`httpUrl`** with `headers`. Tested against a shared server over HTTP, with the Ollama model
`gemma4:31b-cloud`.

```json
{
  "mcpServers": {
    "b123d-print": {
      "httpUrl": "https://cad.example.com/mcp",
      "headers": {"Authorization": "Bearer <token>"},
      "timeout": 300000
    }
  }
}
```

- The token goes in as is (this format has no environment-variable syntax): keep the file
  private.
- A token with one workspace needs no `?workspace=`; with several, add one the token may use,
  or the server answers 403 (its log shows the token's name and the workspace asked for).
- `"timeout"` (ms) covers long builds and checks.
- Before using the token, Qwen Code asks the server for OAuth details
  (`/.well-known/oauth-...`); the server log shows those as 401s. They are harmless.

On your own machine, `"command": "uvx"` and `"args": ["--from", "b123d-print",
"b123d-print-mcp", "--workspace", "/Users/you/parts"]` instead of `httpUrl`. Check with `/mcp`.
`token add` prints the remote block filled in.

## pi

[pi](https://github.com/earendil-works/pi) (the pi coding agent) reads `~/.pi/agent/mcp.json`,
or `.pi/mcp.json` in a trusted project, in the common `mcpServers` format. Tested against a
shared server over HTTP, with the Ollama model `gemma4:31b-cloud`. The easiest way is its own
command, with the token in an environment variable:

```bash
pi mcp add b123d-print --url "https://cad.example.com/mcp" --bearer-token-env-var B123D_TOKEN --description "Design 3D-printable parts; call read_guide first"
```

That writes this entry; add `"timeout"`:

```json
{
  "mcpServers": {
    "b123d-print": {
      "url": "https://cad.example.com/mcp",
      "headers": {"Authorization": "Bearer ${B123D_TOKEN}"},
      "description": "Design 3D-printable parts; call read_guide first",
      "timeout": 300
    }
  }
}
```

- **`"timeout": 300`** (seconds): pi's default is 60 per request, shorter than a long build or
  check.
- **`description`** goes into the model's system prompt: the place to tell any model to read
  the guide first.
- `${B123D_TOKEN}` reads the environment variable: `export B123D_TOKEN='<token>'` before `pi`.
  The literal token works too; keep the file private.
- pi's default `exposure` is `codemode` (the model reaches the tools through pi's code mode);
  `/mcp` in a session changes it.
- Check with `pi mcp list`; after editing the file, `/reload` in a running session.

On your own machine: `pi mcp add b123d-print -- uvx --from b123d-print b123d-print-mcp
--workspace ~/parts`, and the same `timeout`.

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
