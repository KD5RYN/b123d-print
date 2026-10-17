# Publishing cadkit — options and open decisions

Nothing is published yet. This is how the pieces would ship and what needs deciding first.

## What gets distributed

| Artifact | What it is | Who uses it | How it is built |
| --- | --- | --- | --- |
| Source repo | everything | contributors, the Claude plugin | `git push` |
| Python package `cadkit` (wheel + sdist) | library, `cadkit` CLI, `cadkit-mcp` server, examples, AGENTS.md | every MCP client via `uvx` | `uv build` (uv_build backend) |
| Docker image (optional) | server + all dependencies | people who want container isolation | `docker build` |
| Claude Code plugin | `.claude-plugin/`, `.mcp.json`, `skills/` in the repo | Claude Code users | the repo itself is the marketplace |
| MCP Registry entry (optional) | a `server.json` pointing at the PyPI package | clients that browse the registry | `mcp-publisher` CLI |

## Recommended path: GitHub + PyPI

1. **Public GitHub repo** — issues and PRs; GitHub Actions is free for public repos and has
   macOS and Linux runners (Linux sandbox path is still untested; CI is the place to test it).
2. **PyPI via Trusted Publishing** — a GitHub Actions workflow builds on a version tag and
   uploads with OIDC (no API token stored anywhere). Then every client config becomes
   `uvx --from cadkit cadkit-mcp`. The name `cadkit` was free on PyPI on 2026-10-17; publishing
   reserves it. (Optional: a second tiny package `cadkit-mcp` so plain `uvx cadkit-mcp` works.)
3. **Before PyPI, or instead of it**: `uvx --from git+https://github.com/OWNER/cad-kit cadkit-mcp`
   works straight from the repo — fine for a soft launch.
4. **Claude plugin**: `/plugin marketplace add OWNER/cad-kit` then `/plugin install cadkit@cadkit`.
5. **Docker image** on GHCR from the same workflow, if wanted. It redistributes OpenCascade
   (LGPL-2.1) binaries: keep the license files in the image and link the OCCT source (see
   THIRD_PARTY.md). The wheel does not redistribute anything, so it has no such duty.
6. **MCP Registry**: after PyPI, add `<!-- mcp-name: io.github.OWNER/cadkit -->` to the README
   (it proves ownership of the PyPI package) and publish a `server.json`.

Versioning: semver; bump `version` in `pyproject.toml` and `.claude-plugin/plugin.json` together,
tag `vX.Y.Z`, the workflow does the rest. While 0.x, the part-script convention may still change.

## Open decisions

- **Owner and repo name** on GitHub (personal account or an org), and whether a private
  copy elsewhere stays as a mirror.
- **Copyright line and author**: `LICENSE` says "cadkit contributors"; put a name or handle there
  and in `pyproject.toml` `authors` / `plugin.json` `author` if you want credit by name.
- **License**: MIT (current). Apache-2.0 is the other natural choice (matches build123d, adds an
  explicit patent grant). Both are compatible with every dependency.
- **Package name**: `cadkit` is short but generic; `build123d-cadkit` or similar is more
  searchable. Renaming later is painful, so decide before the first upload.
- **Docker image**: ship one, or only the Dockerfile.
