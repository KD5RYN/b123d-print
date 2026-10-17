# Updating

`b123d-print --version` (or the `version` field of the MCP `list_parts` tool) shows what you run.
Releases: [PyPI](https://pypi.org/project/b123d-print/#history) and
[GitHub releases](https://github.com/KD5RYN/b123d-print/releases) (what changed).

| Installed with | Update |
| --- | --- |
| `uvx --from b123d-print ...` (MCP clients) | uvx caches the package: run `uvx --refresh --from b123d-print b123d-print-mcp --help` once, then restart the client |
| a pinned version `--from b123d-print==0.1.0` | change the version in your client config, restart the client |
| `uvx --from git+https://github.com/KD5RYN/b123d-print ...` (unreleased) | `uvx --refresh --from git+https://github.com/KD5RYN/b123d-print b123d-print-mcp --help`, then restart the client |
| `uv tool install b123d-print` (CLI) | `uv tool upgrade b123d-print` |
| Docker image `ghcr.io/kd5ryn/b123d-print-mcp` | `docker pull ghcr.io/kd5ryn/b123d-print-mcp`, restart the client |
| Docker image built from a clone | `git pull && docker build -t b123d-print-mcp .` in your clone, restart the client |
| Claude Code plugin | `/plugin marketplace update b123d-print`, then restart Claude Code |

After updating:

- **Workspaces** keep your parts and settings. The workflow text in a workspace's `AGENTS.md`
  is a copy; refresh it with `b123d-print init --update-agents` (MCP clients always get the
  current text from the server).
- **Printer profiles** ship with the package and update with it; your own files in
  `~/.config/b123d-print/` are never touched.
- **Part scripts**: while b123d-print is 0.x the script conventions may change; the release
  notes say when, and `b123d-print check` tells you what breaks.
