# Updating

`b123d-print --version` (or the `version` field of the MCP `list_parts` tool) shows what you run.
Releases and what changed: [GitHub releases](https://github.com/KD5RYN/b123d-print/releases).

| Installed with | Update |
| --- | --- |
| `uvx --from git+https://github.com/KD5RYN/b123d-print ...` (MCP clients) | uvx caches the build: run `uvx --refresh --from git+https://github.com/KD5RYN/b123d-print b123d-print-mcp --help` once, then restart the client |
| a pinned version `...b123d-print@v0.1.0` | change the tag in your client config, restart the client |
| `uv tool install git+https://github.com/KD5RYN/b123d-print` (CLI) | `uv tool install --force git+https://github.com/KD5RYN/b123d-print` |
| Docker | `git pull && docker build -t b123d-print-mcp .` in your clone, restart the client |
| Claude Code plugin | `/plugin marketplace update b123d-print`, then restart Claude Code |

After updating:

- **Workspaces** keep your parts and settings. The workflow text in a workspace's `AGENTS.md`
  is a copy; refresh it with `b123d-print init --update-agents` (MCP clients always get the
  current text from the server).
- **Printer profiles** ship with the package and update with it; your own files in
  `~/.config/b123d-print/` are never touched.
- **Part scripts**: while b123d-print is 0.x the script conventions may change; the release
  notes say when, and `b123d-print check` tells you what breaks.
