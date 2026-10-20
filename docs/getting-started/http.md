# Over the network (HTTP)

By default the MCP server talks over stdio: each client starts its own copy. For a home server
and a few of your own machines, [SSH](ssh.md) is simpler. With
`--transport http` one server runs as a service and several clients (or agents, or eval runs)
connect to it over [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#streamable-http).
Use it when the parts should live on one machine, such as a home server, while the clients run
elsewhere.

!!! note
    HTTP mode needs b123d-print **0.2.0 or later** (PyPI and `ghcr.io/kd5ryn/b123d-print-mcp`).

!!! tip "Just you, from a laptop?"
    For one person reaching a home server, running the server over SSH (stdio) is simpler and
    needs no tokens at all. HTTP mode is for many agents at once: eval runs, a team, a lab.

## Connect a new AI

Every AI tool that connects (Claude Code on a laptop, an eval runner, a teammate's agent) gets
its own named token. With the server running from [Compose](#compose), one command next to
`compose.yaml` makes the token and the client config:

```bash
docker compose run --rm -T b123d-print token add claude-laptop
```

The token appears once, alone on its own line, and is never shown again: the server keeps
only its SHA-256. Below it comes the config to paste into the tool:

```text
added claude-laptop: workspaces claude-laptop. The token (above) is shown only this once.

Connect an MCP client:
  URL     https://cad.example.com/mcp
  Header  Authorization: Bearer <token>

Claude Code, in the project folder (--scope project keeps the token out of ~/.claude.json,
which other agent tools import):
  claude mcp add --scope project --transport http b123d-print "https://cad.example.com/mcp" --header "Authorization: Bearer <token>"

Other clients (Cursor, VS Code, ...; key names vary):
  {"mcpServers": {"b123d-print": {"type": "http", "url": "https://cad.example.com/mcp",
    "headers": {"Authorization": "Bearer <token>"}}}}

Revoke it with: b123d-print-mcp token revoke claude-laptop
```

Run the `claude mcp add` line in the project folder where you use Claude Code, or paste the JSON
into another client, and the tool is connected.

- **Its workspace is its name.** The tool's parts land in `parts/workspaces/claude-laptop/`, and
  the URL needs no `?workspace=`. For a tool that needs several, such as an eval runner, pass
  patterns: `--workspace 'eval-*'` (repeatable, `'*'` for all); the printed URL then carries an
  example (`?workspace=eval-1`) and the tool picks one per connection.
- **The address** in the printed config is `--url`, else `B123D_PRINT_PUBLIC_URL` (set it once
  in [`.env`](#settings-in-env)), else a `https://<your-server>` placeholder to fill in.
- **Names:** letters, digits, `_` and `-`, up to 64 characters. No dots: the name is also a
  workspace name.
- **Stop a tool** with `docker compose run --rm -T b123d-print token revoke claude-laptop`;
  `token list` shows names, workspaces, dates and a hash prefix, never the tokens. Neither
  needs a restart.
- **Without Docker,** the same commands are `b123d-print-mcp token add|list|revoke`, with
  `--tokens-file` or `B123D_PRINT_TOKENS_FILE` pointing at the file the server reads.

!!! warning "One token per tool, added per project"
    `claude mcp add` at its default (user) scope writes the token in plain text into
    `~/.claude.json`, and other agent tools import MCP servers from that file: one machine's
    grok-cli connected that way without anyone entering a token. So give **each tool its own
    token**, limited to its own workspace; add it **per project** (`--scope project` writes
    `.mcp.json` in that folder; keep that file out of git); and revoke a token when a tool should
    stop. A token used outside its workspaces gets 403, and the server log names the token of
    every request (`docker compose logs b123d-print`).

## Start it

Make a token for each agent or tool that will connect (it is printed once; only its SHA-256 is
stored):

```bash
export B123D_PRINT_TOKENS_FILE=~/.config/b123d-print/tokens.toml
```

```bash
b123d-print-mcp token add claude-laptop --url https://cad.example.com
```

It prints the token once, with the client config to paste (see [Tokens](#tokens)).

```bash
b123d-print-mcp --transport http --workspace ~/parts
```

That serves `http://127.0.0.1:8000/mcp`. To accept clients from other machines on your network:

```bash
b123d-print-mcp --transport http --workspace ~/parts --host 0.0.0.0 --port 8000
```

- **A token is required**: named tokens from `--tokens-file` / `B123D_PRINT_TOKENS_FILE` (see
  [Tokens](#tokens)), or one shared `B123D_PRINT_TOKEN` (or `B123D_PRINT_TOKEN_FILE`, the path of
  a file holding it; at least 16 characters). Without any the server refuses to start. Tokens are
  never taken from the command line, where other users could read them in `ps`.
  `--insecure-no-auth` runs without one: only for a trusted setup on your own machine.
- **Binds to 127.0.0.1** unless `--host` says otherwise.
- **Endpoints:** `/mcp` (stateless, so clients carry on after a server restart) and
  `GET /health`, which answers `{"status": "ok", "version": ...}` without a token.
- **Plain HTTP.** Anything beyond a trusted local network belongs behind a reverse proxy with
  TLS. Behind a proxy that forwards the `Host` header, pass the names clients use, e.g.
  `--allowed-hosts cad.example.com,cad.example.com:*`; this turns on the MCP SDK's Host/Origin
  check against DNS rebinding.

Every option also has an environment variable (`B123D_PRINT_TRANSPORT`, `B123D_PRINT_HOST`,
`B123D_PRINT_PORT`, `B123D_PRINT_MAX_BUILDS`, `B123D_PRINT_ALLOWED_HOSTS`,
`B123D_PRINT_SHUTDOWN_GRACE`); see
[Server options](mcp-clients.md#server-options) and [Settings](../using/settings.md#environment-variables).

## Tokens

Give every agent or tool its **own named token**, limited to the workspaces it should use. Then
the log says who did what, and one token can be revoked without touching the others.

| Command | Does |
| --- | --- |
| `b123d-print-mcp token add <name> [--workspace PATTERN ...] [--url URL]` | make a token, print it once with the client config ([Connect a new AI](#connect-a-new-ai)); `--workspace` names or patterns, repeatable (default: the token's name); `--url` the address in the printed config |
| `b123d-print-mcp token list` | names, workspaces, dates and a hash prefix (never the tokens) |
| `b123d-print-mcp token revoke <name>` | delete it |

All three use `--tokens-file` or `B123D_PRINT_TOKENS_FILE`.

- **No restart needed.** The server re-reads the file when it changes (and on SIGHUP): a revoked
  token is refused on its next request, a new one works at once.
- **Workspaces.** A request for a workspace outside the token's patterns gets **403**. A token
  with exactly one plain workspace (the default: its own name) uses it when the client sends no
  `?workspace=`; a token with patterns must name one. `_` stands for the shared root workspace.
- **The log names the token** of every request:
  `b123d-print-mcp: 10.0.0.7 grok-chromebook POST /mcp ws=grok-1 -> 200`. Download links show
  up as `link`, without their signature.
- **The file holds only hashes** (and the key that signs download links), mode 600. Keep it out
  of the parts folder: the Compose setup mounts it only into the HTTP container.
- **`B123D_PRINT_TOKEN` still works**: it is a token named `default` that may use every
  workspace. You can use both at once while moving to named tokens.

See [Connect a new AI](#connect-a-new-ai) for why each tool gets its own token, added per project.

### If it does not start

The server checks its setup before it listens and stops with a one-line message and a non-zero
exit code when something is wrong:

| Message | Fix |
| --- | --- |
| `HTTP needs a token: ...` | add a token with `token add` and set `B123D_PRINT_TOKENS_FILE`, or set `B123D_PRINT_TOKEN` |
| `no tokens file ...` | the path in `B123D_PRINT_TOKENS_FILE` does not exist yet: run `token add` first |
| `cannot read the tokens file: ...` | the file is not valid TOML or a token entry is malformed; `token list` shows the same error |
| `B123D_PRINT_TOKEN is too short` | use at least 16 characters; the `secrets` command above makes a good one |
| `cannot read B123D_PRINT_TOKEN_FILE` | check the path and that the server's user can read the file |
| `workspace ... is not writable` | fix the folder's owner; in Docker the image runs as uid 1000 |
| `address already in use` (from uvicorn) | another process has the port; pick another `--port` |

### Stopping

On SIGTERM (`docker stop`, `systemctl stop`), Ctrl-C, or on Windows Ctrl-Break, the server stops accepting requests and
gives calls that are running `--shutdown-grace` seconds (default 30) to finish. Builds still
running after that are killed, and the server exits with code 0. Give the service manager a
longer stop timeout than that: `stop_grace_period` in Compose, `docker stop -t`,
`TimeoutStopSec` in systemd.

## Several clients at once

**Every client works in its own workspace**, `<workspace>/workspaces/<name>/`, created on first
use. A named token's default is the workspace with its own name, so most clients never say
which. A client can pick one with `?workspace=<name>` in the URL (or the header
`X-B123D-Workspace: <name>`), if its token allows it. Names use letters, digits, `_` and `-`, up to
64 characters. A client that names none and whose token has no single default (the shared
`B123D_PRINT_TOKEN`, a `'*'` token, or `--insecure-no-auth`) works in the server's root
workspace, `_`, where clients can overwrite each other's parts. Named [tokens](#tokens) limit which workspaces a client may use; the part
scripts themselves all run in the same sandbox, so do not rely on workspaces to keep secrets
apart.

**Printers are per workspace.** Over HTTP, `use_printer` saves the printer and material in that
workspace's `b123d-print.toml`, so one client never changes another's printer. (Over stdio it
writes your user config, as before.)

**Builds take turns.** `--max-builds N` (default: half the CPU cores) caps how many build,
render, section, check, export and compare processes run at once across all clients; further
calls wait; a `check` uses up to N of them at once, split by check, and gives them up as its
shares finish. Each one keeps its own time limit once it starts: `--timeout` (default 240 s), or
`--check-timeout` for a check (default 300 s; a check returns a little before it, with what it
found). A long queue can outlast a client's read timeout (300 s by default in the MCP Python
SDK), so size N and the number of clients together. `list_parts` reports the limit.

## Get the files

Over HTTP the server is a workbench, not storage: the files it writes are a temporary working
copy on the server ([removed after 30 days unused](#workspace-retention)), and the client brings
them home. Agents use only the MCP tools and the links they return; the server gives no shell,
ssh or scp access, and the tool descriptions and results say so.

**The whole part, in one step.** `download_part("bracket")` returns one signed link to a zip of
the part in the same layout a local install writes into the project folder:

```text
parts/bracket/bracket.py      the script
parts/bracket/out/...         exports, renders, section views (all variants and formats)
parts/bracket/ref/...         reference models (remixes)
```

```bash
curl -fLo bracket.zip '<link>'
unzip -o bracket.zip          # in the project folder; on Windows: tar -xf bracket.zip
```

`variant=` and `formats=` narrow the `out/` files (the script and `ref/` always come along);
the zip is made when the link is fetched, so it holds the files as they are then. Like the other
links it needs no token, opens only that part (with that filter) in that workspace, and expires.
The server's instructions, `AGENTS.md` and the prompts make this the required last step of
remote work: `download_part`, unzip, check the files are there, then report. The results of
`export` and `make_template` end with a **NEXT STEP** that says so, with the exact call. Results
show workspace-relative paths (`parts/bracket/out/bracket.3mf`), never the server's own folders.

**No network in the agent's shell?** Some clients run shell commands in a sandbox without
network ([Antigravity's `agy`](mcp-clients.md#antigravity-agy-cli-and-ide), for one), so `curl`
fails. `download_part("bracket", embed=True)` puts the zip itself (up to 8 MB; narrow it with
`formats=` if it is bigger) into the MCP result; the client saves it to a file, and
`unzip -o <saved zip> -d <project folder>` writes the same layout offline.

Single files, too:

- **Download links.** `export` lists every file with an HTTPS link, and `render_preview`,
  `section` and `compare` add one for their image. A link needs no token, so `curl -fO <url>`,
  a browser or another agent can fetch it, but it opens only that one file, and only until it
  expires (`--link-ttl`, default 1 hour; an expired link answers 410, so call the tool again).
  Links are signed with the `link_secret` in the tokens file (made by the first `token add`), or
  `B123D_PRINT_LINK_SECRET`, or with only `B123D_PRINT_TOKEN` a key derived from it: they survive
  a restart, and revoking a token does not cancel links it already got (they expire on their own).
- **Resource links.** The same results carry MCP resource links
  (`b123d-print://files/<workspace>/parts/<part>/out/<file>`) that a client can read over the MCP
  connection itself. A session can read only its own workspace's files.
- **Images.** `render_preview`, `section` and `compare` still return their image inline, so the
  model sees the part. `size="small"` makes it ~800 px wide; `inline=false` returns only the
  link, for clients that do not show images.
- **Embedded files.** `export(..., embed=true)` also puts each file up to 2 MB (8 MB in all) into
  the result, for clients that can neither fetch URLs nor read resources. It is off by default:
  embedded models cost a lot of context.

The per-file links serve only the files in `parts/<part>/out/`; the script and `ref/` come only
in `download_part`'s zip. Nothing outside the workspace is ever served. Agents never need a shell
on the server.

### View in 3D

`export` also returns a **view link** per variant (`view="print"` by default, `"assembly"`, or
`"none"`), and `download_part` lists them again:

```text
https://cad.example.com/view/<workspace>/<expires>.<signature>/bracket/bracket_view
```

Open it in a browser to turn the part around before printing: orbit, zoom and pan, show or hide
each piece, the bed at Z = 0, the size in mm and a section plane
([what the viewer shows](../using/formats.md#3d-view-in-the-browser)). Like a download link it
needs no token, is signed for one model of one part in one workspace, and expires with the others
(`--link-ttl`; an expired one answers 410). The page loads the model,
`parts/<part>/out/<part>_view.glb`, through the same signed link (`.../bracket_view.glb`), and
its scripts from `/view-assets/`, a fixed list of files from the package that needs no token
(they hold nothing of anyone's). The viewer library, three.js, ships inside the package: the
browser loads nothing from the internet, so it works on a lab network without internet access.

How the view is kept safe:

- the same HMAC signature, workspace binding and expiry as the download links, under its own
  purpose, so a view signature never opens a download, a zip or an upload, nor the other way
  round; the model must be a regular file in that part's `out/` (no symlinks, no `..`);
- the page is one static file, the same for every part: nothing from the request or the model
  is written into it. Its headers: `Content-Security-Policy: default-src 'none'; script-src 'self';
  style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; base-uri 'none';
  form-action 'none'; frame-ancestors 'none'` (no inline script at all),
  `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer` (the link is the
  credential), `X-Frame-Options: DENY` and `Cache-Control: no-store`;
- the model is served as `model/gltf-binary`, `nosniff`, as an attachment; the viewer treats it
  as data: piece names are shown as text, and the loader fetches nothing the model names;
- like the other links, the signature never appears in the server's log
  (`GET /view/<workspace>/.../<part>/<stem>`).

**Caddy (or another reverse proxy).** Nothing to change if it forwards everything to the server,
as `caddy reverse-proxy --to b123d-print:8000` and the [Compose](#compose) block do. A
Caddyfile that forwards only some paths needs `/view/*` and `/view-assets/*` next to `/mcp`,
`/files/*`, `/zip/*` and `/upload/*`. Do not let the proxy replace the server's
`Content-Security-Policy` header. `encode gzip` is worth having: the viewer's script is 640 KB,
160 KB compressed.

### Workspace retention

A named workspace (`?workspace=<name>`, kept in `<workspace>/workspaces/<name>`) that nobody has
used for **30 days** is removed, with everything in it (its parts and its `b123d-print.toml`,
so its printer choice too). Every request and every link fetch counts as a use; the server
checks at startup and then hourly, logs each removal by name, and never removes a workspace
while a request for it (a queued or running build included) is in flight. Set the number of
days with `--retention-days` or `B123D_PRINT_RETENTION_DAYS` (`0` = never). The shared root
workspace (clients without `?workspace=`) is never removed. Tool results say how long the copy
is kept ("deleted after 30 days unused").

The other way, a model to [remix](../using/remix.md): `upload_reference` returns a signed
**upload link**, and `curl -fT bracket.stl '<link>'` on your machine stores the file as
`parts/<part>/ref/bracket.stl`. Like a download link it needs no token, works for that one file
only and expires; it takes STL, 3MF and STEP up to 50 MB and does not replace an existing file
unless the tool was asked to (`overwrite=true`).

**Behind a reverse proxy**, set `--public-url https://cad.example.com` (or
`B123D_PRINT_PUBLIC_URL`) so the links point at the proxy. Without it the server uses the
request's `Host` header, and it trusts `X-Forwarded-Host` / `X-Forwarded-Proto` only for hosts
listed in `--allowed-hosts`.

## Connect a client

Claude Code:

```bash
claude mcp add --scope project --transport http b123d-print "https://cad.example.com/mcp" --header "Authorization: Bearer $TOKEN"
```

`token add` prints this line, filled in, for each token ([Connect a new AI](#connect-a-new-ai)).

Clients that take a JSON config with remote servers (Cursor, VS Code, and others; the exact key
names vary, check your client's docs):

```json
{
  "mcpServers": {
    "b123d-print": {
      "type": "http",
      "url": "https://cad.example.com/mcp",
      "headers": {"Authorization": "Bearer <token>"}
    }
  }
}
```

Per-client snippets (Antigravity, Gemini CLI, Zed, Windsurf, LM Studio, Grok, claude.ai, ChatGPT) are in
[Connect your MCP client](mcp-clients.md#which-clients).

### Clients that can't send a header

The server accepts exactly one kind of credential: `Authorization: Bearer <token>` with a
[named token](#tokens). It has no OAuth, no sign-in page and no other way to authenticate
(`--insecure-no-auth` turns authentication off altogether, for a trusted network only). Clients
whose remote connectors offer only OAuth or no auth can't connect:

- **ChatGPT** (custom MCP servers: no auth or OAuth, no custom headers) can't connect at all.
- **claude.ai** custom connectors (web, mobile) can only with the Request headers beta, which a
  limited set of Team and Enterprise organizations has.

What works instead:

1. **Run the server locally over stdio** in a client that starts commands (Claude Desktop, Claude
   Code, Cursor, ...): no network and no token ([Quick start](quick-start.md)). To keep the parts
   on a home server, run it over [SSH](ssh.md): still stdio, still no token.
2. **A small local proxy** that the client starts as a stdio server and that adds the header:
   `mcp-remote` or `mcp-proxy`, see [a local proxy](mcp-clients.md#remote-server-from-a-stdio-only-client).
   This helps clients that start commands but can't set headers; it doesn't help ChatGPT or
   claude.ai, whose connectors run in the vendor's cloud and start nothing on your machine.
3. **OAuth** (the [MCP authorization spec](https://modelcontextprotocol.io/specification/latest/basic/authorization))
   is what connector-style clients expect. b123d-print doesn't implement it yet.

**Why there is no `?token=` in the URL.** A token in the URL ends up wherever URLs are written:
reverse-proxy and load-balancer access logs, the client's own logs and config, shell history,
browser history and `Referer` headers. Unlike a header, it gets copied around without anyone
noticing, and a server token is long-lived and opens a whole workspace. The signed download and
view links are different: each opens one file (or one zip, or one view) for `--link-ttl` seconds,
and the server log never prints their signatures. So b123d-print doesn't accept tokens in
URLs, and a reverse proxy that turns `?token=` into a header has the same problem: don't build one.

Python, with the MCP SDK 2.x:

```python
from mcp import Client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

http = create_mcp_http_client(headers={"Authorization": f"Bearer {token}"})
async with Client(streamable_http_client("http://HOST:8000/mcp?workspace=run1", http_client=http)) as c:
    res = await c.call_tool("render_preview", {"name": "box"})
```

## In Docker

### Compose

The repository has a ready-to-copy Compose file,
[`deploy/compose.yaml`](https://github.com/KD5RYN/b123d-print/blob/main/deploy/compose.yaml). It runs
**two containers** from the same image, sharing the parts folder:

- `b123d-print` answers HTTP. It has a network but runs no part scripts.
- `worker` runs the model-written part scripts with **no network at all** (`network_mode:
  none`). The two talk only through a job folder on the shared volume
  (`--job-queue` / `B123D_PRINT_JOB_QUEUE` on the server, `b123d-print-mcp worker --queue` on the
  worker). Inside the worker each job runs in its own [bubblewrap](https://github.com/containers/bubblewrap)
  mount namespace that sees only that client's workspace, so clients are isolated from each other
  (see [Sandbox](../using/sandbox.md#what-keeps-workspaces-apart)). This needs **unprivileged user
  namespaces** in the container: the compose file sets a custom seccomp profile
  (`deploy/seccomp-bwrap.json`) and `apparmor:unconfined` for the worker. If the host cannot
  provide user namespaces (some hardened kernels, or a nested LXC container), the worker reports
  unhealthy and refuses jobs rather than running them unisolated; set `B123D_PRINT_SANDBOX=none` on
  the worker to accept the audit hook alone, or run a separate deployment per client.

Next to the file:

```bash
mkdir -p parts config && sudo chown 1000:1000 parts config
```

```bash
echo "B123D_PRINT_PUBLIC_URL=https://cad.example.com" >> .env
```

```bash
docker compose up -d && docker compose ps
```

Then [connect each AI](#connect-a-new-ai) with `docker compose run --rm -T b123d-print token add <name>`.

Both services show `(healthy)` once they run; `/health` answers 503 `"degraded"` while the worker
is down, and builds then fail at once with "the build worker is not running". `parts` and `config`
must be writable by uid 1000, the user the image runs as (or set `B123D_PRINT_UID` /
`B123D_PRINT_GID`). The tokens live in `config/`, which only the HTTP container mounts.

#### Settings in `.env`

Compose reads these from a `.env` file next to `compose.yaml`, so the file itself stays as
shipped and `git pull` updates it cleanly (`deploy/.env.example` lists them with their defaults):

| Variable | Default | What |
| --- | --- | --- |
| `B123D_PRINT_PUBLIC_URL` | taken from each request | the address clients use (behind a proxy, its `https://` URL): used in download links and in the config `token add` prints |
| `B123D_PRINT_LISTEN` | `127.0.0.1:8000` | where the port is published: localhost for a reverse proxy on the same machine (the optional Caddy block), `8000` for the whole network |
| `B123D_PRINT_IMAGE` | `ghcr.io/kd5ryn/b123d-print-mcp:latest` | the image; `b123d-print-mcp` for one [built from a clone](#from-a-clone) |
| `B123D_PRINT_MAX_BUILDS` | `2` | builds at once, all clients together |
| `B123D_PRINT_RETENTION_DAYS` | `30` | remove a workspace nobody used for this many days ([retention](#workspace-retention)); `0` = never |
| `B123D_PRINT_TIMEOUT` | `240` | seconds per build, render, section or export (under the 300 s a client waits for a result) |
| `B123D_PRINT_CHECK_TIMEOUT` | `300` | seconds per `check` (a big remix on a slow CPU needs more); it returns a little before, with the findings it has |
| `B123D_PRINT_PARTS`, `B123D_PRINT_CONFIG` | `./parts`, `./config` | the parts folder and the tokens folder |
| `B123D_PRINT_UID`, `B123D_PRINT_GID` | `1000` | the user the containers run as |

#### From a clone

To run unreleased code, or to deploy from a checkout you can update with `git pull`:

```bash
git clone https://github.com/KD5RYN/b123d-print && cd b123d-print
```

```bash
docker build -t b123d-print-mcp .
```

```bash
cd deploy && echo "B123D_PRINT_IMAGE=b123d-print-mcp" >> .env
```

Then continue as above, in `deploy/`. The repository's `.gitignore` already covers
`deploy/.env`, `deploy/parts/`, `deploy/config/` and `deploy/compose.override.yaml`, so your
settings, parts and tokens never show up as changes. To update it, see
[Updating](../updating.md#a-compose-install).

### `docker run`

The same image serves HTTP when the environment selects it (so the image's health check knows
to probe `/health`):

```bash
docker run -d --name b123d-print --restart unless-stopped -p 127.0.0.1:8000:8000 -v "$PWD/parts:/work" -e B123D_PRINT_TRANSPORT=http -e B123D_PRINT_TOKEN="$B123D_PRINT_TOKEN" b123d-print-mcp
```

```bash
docker inspect -f '{{.State.Health.Status}}' b123d-print
```

- This runs the part scripts in the same container as the HTTP server, which has a network.
  Prefer the two-container Compose setup above for anything shared. Inside the container the server listens on all interfaces; choose who can reach it with
  `-p`: `127.0.0.1:8000:8000` for a reverse proxy on the same machine, `8000:8000` for the whole
  network.
- The stdio setup in [Docker](docker.md) is unchanged.

## Check a server

From a clone, `uv run python tests/mcp_smoke.py --http` starts a server and runs every tool
over HTTP, plus checks that a wrong token is refused, that named tokens keep to their
workspaces and can be revoked live, that workspaces stay apart and that builds run in parallel;
`--split` does the same with builds in a separate `worker` process. Against a server that is already running:

```bash
B123D_PRINT_SMOKE_URL=http://HOST:8000/mcp B123D_PRINT_SMOKE_TOKEN=... uv run python tests/mcp_smoke.py
```
