# Over the network (HTTP)

By default the MCP server talks over stdio: each client starts its own copy. With
`--transport http` one server runs as a service and several clients (or agents, or eval runs)
connect to it over [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports#streamable-http).
Use it when the parts should live on one machine, such as a home server, while the clients run
elsewhere.

!!! note
    HTTP mode is newer than the 0.1.0 release, so the `latest` image and `b123d-print` from PyPI
    don't have it yet. Until the next release, install from the git URL (see
    [Which version](mcp-clients.md#which-version)) or build the Docker image from a clone.

## Start it

```bash
export B123D_PRINT_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
```

```bash
b123d-print-mcp --transport http --workspace ~/parts
```

That serves `http://127.0.0.1:8000/mcp`. To accept clients from other machines on your network:

```bash
b123d-print-mcp --transport http --workspace ~/parts --host 0.0.0.0 --port 8000
```

- **A token is required.** Set `B123D_PRINT_TOKEN`, or `B123D_PRINT_TOKEN_FILE` with the path of
  a file that holds it; at least 16 characters. Without one the server refuses to start. The
  token is never taken from the command line, where other users could read it in `ps`.
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

### If it does not start

The server checks its setup before it listens and stops with a one-line message and a non-zero
exit code when something is wrong:

| Message | Fix |
| --- | --- |
| `HTTP needs a token: set B123D_PRINT_TOKEN ...` | set `B123D_PRINT_TOKEN` or `B123D_PRINT_TOKEN_FILE` |
| `B123D_PRINT_TOKEN is too short` | use at least 16 characters; the `secrets` command above makes a good one |
| `cannot read B123D_PRINT_TOKEN_FILE` | check the path and that the server's user can read the file |
| `workspace ... is not writable` | fix the folder's owner; in Docker the image runs as uid 1000 |
| `address already in use` (from uvicorn) | another process has the port; pick another `--port` |

### Stopping

On SIGTERM (`docker stop`, `systemctl stop`) or Ctrl-C the server stops accepting requests and
gives calls that are running `--shutdown-grace` seconds (default 30) to finish. Builds still
running after that are killed, and the server exits with code 0. Give the service manager a
longer stop timeout than that: `stop_grace_period` in Compose, `docker stop -t`,
`TimeoutStopSec` in systemd.

## Several clients at once

**Give every client its own workspace.** A client adds `?workspace=<name>` to the URL (or sends
the header `X-B123D-Workspace: <name>`), and its parts live in
`<workspace>/workspaces/<name>/`, created on first use. Names use letters, digits, `_` and `-`,
up to 64 characters. Clients without a name share the server's root workspace and can overwrite
each other's parts.

**Printers are per workspace.** Over HTTP, `use_printer` saves the printer and material in that
workspace's `b123d-print.toml`, so one client never changes another's printer. (Over stdio it
writes your user config, as before.)

**Builds take turns.** `--max-builds N` (default: half the CPU cores) caps how many build,
render, section, check and export processes run at once across all clients; further calls wait.
Each build keeps its own `--timeout` (default 120 s) once it starts. A long queue can outlast a
client's read timeout (300 s by default in the MCP Python SDK), so size N and the number of
clients together. `list_parts` reports the limit.

## Get the files

Over HTTP the files the server writes stay on the server. The tools hand them to you three ways:

- **Download links.** `export` lists every file with an HTTPS link, and `render_preview`,
  `section` and `compare` add one for their image. A link needs no token, so `curl -fO <url>`,
  a browser or another agent can fetch it, but it opens only that one file, and only until it
  expires (`--link-ttl`, default 1 hour; an expired link answers 410, so call the tool again).
  Links are signed with a key derived from the token (or `B123D_PRINT_LINK_SECRET`): they survive
  a restart, and changing the token invalidates them.
- **Resource links.** The same results carry MCP resource links
  (`b123d-print://files/<workspace>/parts/<part>/out/<file>`) that a client can read over the MCP
  connection itself. A session can read only its own workspace's files.
- **Images.** `render_preview`, `section` and `compare` still return their image inline, so the
  model sees the part. `size="small"` makes it ~800 px wide; `inline=false` returns only the
  link, for clients that do not show images.
- **Embedded files.** `export(..., embed=true)` also puts each file up to 2 MB (8 MB in all) into
  the result, for clients that can neither fetch URLs nor read resources. It is off by default:
  embedded models cost a lot of context.

Only the files in `parts/<part>/out/` are served: not the part scripts and nothing outside the
workspace. Agents should never need SSH access to the server.

**Behind a reverse proxy**, set `--public-url https://cad.example.com` (or
`B123D_PRINT_PUBLIC_URL`) so the links point at the proxy. Without it the server uses the
request's `Host` header, and it trusts `X-Forwarded-Host` / `X-Forwarded-Proto` only for hosts
listed in `--allowed-hosts`.

## Connect a client

Claude Code:

```bash
claude mcp add --transport http b123d-print "http://HOST:8000/mcp?workspace=myagent" --header "Authorization: Bearer $B123D_PRINT_TOKEN"
```

Clients that take a JSON config with remote servers (Cursor, VS Code, and others; the exact key
names vary, check your client's docs):

```json
{
  "mcpServers": {
    "b123d-print": {
      "type": "http",
      "url": "http://HOST:8000/mcp?workspace=myagent",
      "headers": {"Authorization": "Bearer <token>"}
    }
  }
}
```

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
[`deploy/compose.yaml`](https://github.com/KD5RYN/b123d-print/blob/main/deploy/compose.yaml): the
image from GHCR, the token in an env file, the port on localhost only, a stop grace period
longer than `--shutdown-grace`, and an optional Caddy service for TLS in front. Next to it:

```bash
mkdir -p parts && sudo chown 1000:1000 parts
```

```bash
python3 -c 'import secrets; print("B123D_PRINT_TOKEN=" + secrets.token_urlsafe(32))' > b123d-print.env && chmod 600 b123d-print.env
```

```bash
docker compose up -d && docker compose ps
```

`docker compose ps` shows the service as `(healthy)` once `/health` answers. The `parts` folder
must be writable by uid 1000, the user the image runs as.

### `docker run`

The same image serves HTTP when the environment selects it (so the image's health check knows
to probe `/health`):

```bash
docker run -d --name b123d-print --restart unless-stopped -p 127.0.0.1:8000:8000 -v "$PWD/parts:/work" -e B123D_PRINT_TRANSPORT=http -e B123D_PRINT_TOKEN="$B123D_PRINT_TOKEN" b123d-print-mcp
```

```bash
docker inspect -f '{{.State.Health.Status}}' b123d-print
```

- The container is still the sandbox, but HTTP needs a network, so `--network none` does not
  apply. Inside the container the server listens on all interfaces; choose who can reach it with
  `-p`: `127.0.0.1:8000:8000` for a reverse proxy on the same machine, `8000:8000` for the whole
  network.
- The stdio setup in [Docker](docker.md) is unchanged.

## Check a server

From a clone, `uv run python tests/mcp_smoke.py --http` starts a server and runs every tool
over HTTP, plus checks that a wrong token is refused, that workspaces stay apart and that
builds run in parallel. Against a server that is already running:

```bash
B123D_PRINT_SMOKE_URL=http://HOST:8000/mcp B123D_PRINT_SMOKE_TOKEN=... uv run python tests/mcp_smoke.py
```
