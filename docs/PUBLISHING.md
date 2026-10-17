# Publishing b123d-print — options and open decisions

Nothing is published yet. This is how the pieces would ship and what needs deciding first.

## What gets distributed

| Artifact | What it is | Who uses it | How it is built |
| --- | --- | --- | --- |
| Source repo | everything | contributors, the Claude plugin | `git push` |
| Python package `b123d-print` (wheel + sdist) | library, `b123d-print` CLI, `b123d-print-mcp` server, examples, AGENTS.md | every MCP client via `uvx` | `uv build` (uv_build backend) |
| Docker image (optional) | server + all dependencies | people who want container isolation | `docker build` |
| Claude Code plugin | `.claude-plugin/`, `.mcp.json`, `skills/` in the repo | Claude Code users | the repo itself is the marketplace |
| MCP Registry entry (optional) | a `server.json` pointing at the PyPI package | clients that browse the registry | `mcp-publisher` CLI |

## Recommended path: GitHub + PyPI

1. **Public GitHub repo** — issues and PRs; GitHub Actions is free for public repos and has
   macOS and Linux runners (Linux sandbox path is still untested; CI is the place to test it).
2. **PyPI via Trusted Publishing** — a GitHub Actions workflow builds on a version tag and
   uploads with OIDC (no API token stored anywhere). Then every client config becomes
   `uvx --from b123d-print b123d-print-mcp`; publishing reserves the name.
3. **Before PyPI, or instead of it**: `uvx --from git+https://github.com/OWNER/cad-kit b123d-print-mcp`
   works straight from the repo — fine for a soft launch.
4. **Claude plugin**: `/plugin marketplace add OWNER/cad-kit` then `/plugin install b123d-print@b123d-print`.
5. **Docker image** on GHCR from the same workflow, if wanted. It redistributes OpenCascade
   (LGPL-2.1) binaries: keep the license files in the image and link the OCCT source (see
   THIRD_PARTY.md). The wheel does not redistribute anything, so it has no such duty.
6. **MCP Registry**: after PyPI, add `<!-- mcp-name: io.github.OWNER/b123d-print -->` to the README
   (it proves ownership of the PyPI package) and publish a `server.json`.

Versioning: semver; bump `version` in `pyproject.toml` and `.claude-plugin/plugin.json` together,
tag `vX.Y.Z`, the workflow does the rest. While 0.x, the part-script convention may still change.

## Decisions (2026-10-17)

- **Name:** `b123d-print` everywhere: GitHub repo, PyPI package, CLI (`b123d-print`,
  `b123d-print-mcp`), Docker image, Claude plugin. Checked that day: no GitHub user/org or repo
  of that name, free on PyPI. (`cadkit` was dropped: a GitHub org and 14 repos already use it.)
- **Authors:** KD5RYN and contributors (LICENSE, `pyproject.toml`, plugin manifests).
- **License:** MIT.
- **Distribution:** PyPI package usable on its own (`uvx --from b123d-print b123d-print-mcp`)
  **and** a Docker image (GHCR), both from tagged releases.

## Still open

- GitHub owner: `KD5RYN/b123d-print` (personal) unless you want an org.
- Linux sandbox (bubblewrap) and the Dockerfile are untested; the first CI run on GitHub
  Actions (macOS + Ubuntu) should cover them before the first release.
