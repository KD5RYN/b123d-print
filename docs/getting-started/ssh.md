# Remote over SSH (recommended)

To keep your parts on a home server and design from a laptop, run the MCP server over **SSH**.
Every MCP client can start a stdio server, and `ssh` is one: the client runs
`ssh you@server`, and SSH does the rest. Login and encryption come from SSH keys you probably
already have, so there are no certificates, tokens or open ports to set up.

## Which remote mode?

| Mode | Use it for | Login | Files come back by |
| --- | --- | --- | --- |
| [Local (stdio)](mcp-clients.md) | everything on one machine | none needed | they are already on your disk |
| **SSH** (this page) | a home server and a few of your own machines | your SSH key, one line per machine in `authorized_keys` | `b123d-print pull`, or `export(embed=true)` |
| [HTTP](http.md) | many agents at once, eval runs, a shared service | a bearer token, TLS from a reverse proxy | download links |

## Set it up

**1. On the server**, install b123d-print with [uv](https://docs.astral.sh/uv/getting-started/installation/)
(on Linux also install `bubblewrap`, the [sandbox](../using/sandbox.md)):

```bash
uv tool install b123d-print
```

!!! note
    SSH mode is newer than the 0.1.0 release. Until the next one, install from git:
    `uv tool install git+https://github.com/KD5RYN/b123d-print`.

**2. Copy the laptop's public key** to the server (e.g. `scp ~/.ssh/id_ed25519.pub server:laptop.pub`),
then on the server:

```bash
b123d-print setup-ssh --key laptop.pub --workspace laptop --add
```

That creates the workspace `~/parts/laptop`, adds one line to `~/.ssh/authorized_keys` and prints
the client configuration to match. Without `--add` it only prints the line, for you to add
yourself. Running it again changes nothing; with another `--workspace` it replaces that key's
line. `--host` sets the name clients reach the server by (default: its FQDN).

**3. On the laptop**, check that the key works. This also accepts the server's host key, which
the MCP client cannot do for you:

```bash
ssh you@server version
```

It prints the version, the workspace and the sandbox. Then add the server to your client.
Claude Code:

```bash
claude mcp add b123d-print -- ssh you@server
```

Claude Desktop, Cursor (`~/.cursor/mcp.json`), Gemini CLI and most others:

```json
{"mcpServers": {"b123d-print": {"command": "ssh", "args": ["you@server"]}}}
```

VS Code (`.vscode/mcp.json`):

```json
{"servers": {"b123d-print": {"type": "stdio", "command": "ssh", "args": ["you@server"]}}}
```

If the key is not your default one, add `"-i", "/home/you/.ssh/b123d_print"` before
`you@server`, or give the server a `Host` entry in `~/.ssh/config`. A key with a passphrase needs
`ssh-agent`: the MCP client cannot type it.

Done. Repeat step 2 for each machine, with its own key and workspace name.

## What the line allows

```text
restrict,command="/home/you/.local/bin/b123d-print ssh-serve --workspace /home/you/parts/laptop --dest you@server" ssh-ed25519 AAAA... laptop
```

sshd runs that command whatever the client asks for (a *forced command*), and `restrict` turns off
terminals and every kind of forwarding. `ssh-serve` then answers only three requests:

| The client runs | It gets |
| --- | --- |
| `ssh you@server` (what the MCP client does) | the MCP server, in that workspace |
| `ssh you@server pull <part> [--formats ...]` | that part's exported files (what `b123d-print pull` uses), read-only |
| `ssh you@server version` | the version, workspace and sandbox |

Anything else (a shell, `scp`, `sftp`, `rsync`, other options for the server) is refused. The
workspace comes from the line on the server, never from the client, so a machine's key reaches
only its own workspace. Builds still run in the [sandbox](../using/sandbox.md).

**To revoke a machine, delete its line** from `~/.ssh/authorized_keys`.

!!! warning "Per machine, not per tool"
    SSH decides by key, and any program running as you on the laptop can use your key: a second
    AI tool there gets the same access as the first. That is the same as running the server
    locally, but it means SSH cannot give two tools on one machine different access. For that,
    give each tool its own key (with `-i`) and its own line, or use [HTTP](http.md).

Use a key that is only for b123d-print if the same key also logs you in to that server:
`setup-ssh` refuses to turn a key with normal login access into a restricted one (sshd uses
only the first line for a key). `ssh-keygen -t ed25519 -f ~/.ssh/b123d_print` makes one.

## Get the files

The files the server writes stay on the server. `export` ends with the command that copies them
to the laptop, for example:

```bash
b123d-print pull bracket --formats 3mf --from you@server
```

`pull` runs on the laptop (install b123d-print there too, or use
`uvx --from b123d-print b123d-print pull ...`) and uses the same SSH key. `-o <folder>` picks
where the files go (default: the current folder); `--ssh 'ssh -i ~/.ssh/b123d_print -p 2222'`
passes options to ssh.

`export(..., embed=true)` instead puts each file up to 2 MB (8 MB in all) into the tool result,
over SSH as well as locally; it costs a lot of context, so it is off by default.

## Several machines at once

Each SSH connection runs its own server process. The build limit (`B123D_PRINT_MAX_BUILDS`,
default half the CPU cores) holds across all of them together, through lock files in
`~/.cache/b123d-print/build-slots/`: further builds wait their turn.

Settings come from the server's user config (`~/.config/b123d-print/config.toml`) and each
workspace's `b123d-print.toml`. Over SSH, `use_printer` saves the printer and material in the
workspace's `b123d-print.toml`, so one machine never changes another's printer.

## If it does not work

| Symptom | Fix |
| --- | --- |
| The client says the server closed or never started | run `ssh you@server version` in a terminal and fix what it says |
| `Permission denied (publickey)` | the client uses another key: add `-i`, or check the line is in the right user's `authorized_keys` |
| `Host key verification failed` | run `ssh you@server version` once and accept the key |
| The client hangs, or reports invalid JSON | your shell startup files on the server print something (e.g. `echo` in `.zshenv` or `.bashrc`): sshd runs the command through your shell, and anything printed breaks the MCP stream |
| `refused: ...` | the key allows only the three requests above; for a shell, log in with another key |
| `no ... files for part` from `pull` | export the part first |
