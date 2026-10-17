# Releasing

Nothing is published to PyPI or GHCR yet: there are no release tags. Until then everything
installs straight from the repository (`uvx --from git+https://github.com/KD5RYN/b123d-print ...`).
This page is how the pieces ship and what is still open.

## What gets distributed

| Artifact | What it is | Who uses it | How it is built |
| --- | --- | --- | --- |
| Source repo | everything | contributors, the Claude Code plugin | `git push` |
| Python package `b123d-print` (wheel + sdist) | library, `b123d-print` CLI, `b123d-print-mcp` server, examples, AGENTS.md | every MCP client via `uvx` | `uv build` (uv_build backend) |
| Docker image | server + all dependencies | people who want container isolation | `docker build` |
| Claude Code plugin | `.claude-plugin/`, `.mcp.json`, `skills/` in the repo | Claude Code users | the repo itself is the marketplace |
| Docs site | `docs/` + `mkdocs.yml` | everyone | `.github/workflows/docs.yml` on every push to `main` |
| MCP Registry entry (optional) | a `server.json` pointing at the PyPI package | clients that browse the registry | `mcp-publisher` CLI |

## Decisions

- **Name:** `b123d-print` everywhere: GitHub repo (`KD5RYN/b123d-print`), PyPI package, CLI
  (`b123d-print`, `b123d-print-mcp`), Docker image, Claude Code plugin.
- **Authors:** KD5RYN and contributors (LICENSE, `pyproject.toml`, plugin manifests).
- **License:** MIT.
- **Distribution:** a PyPI package usable on its own (`uvx --from b123d-print b123d-print-mcp`)
  **and** a Docker image on GHCR, both from tagged releases.
- **CI** uses GitHub-hosted runners only. Self-hosted runners on a public repo would run code
  from anyone's pull request on your machines.

## Path

1. **PyPI via Trusted Publishing** — `.github/workflows/release.yml` builds on a version tag and
   uploads with OIDC (no API token stored anywhere). Then every client config becomes
   `uvx --from b123d-print b123d-print-mcp`.
2. **Docker image** on GHCR from the same workflow. It redistributes OpenCascade (LGPL-2.1)
   binaries: keep the license files in the image and link the OCCT source (see
   [Credits and licenses](../credits.md)). The wheel does not redistribute anything, so it has no
   such duty.
3. **MCP Registry**: after PyPI, add `<!-- mcp-name: io.github.KD5RYN/b123d-print -->` to the
   README (it proves ownership of the PyPI package) and publish a `server.json`.

Versioning: semver; bump `version` in `pyproject.toml` and `.claude-plugin/plugin.json` together,
tag `vX.Y.Z`, the workflow does the rest (it checks that the tag matches `pyproject.toml`).
While 0.x, the part-script convention may still change; say so in the release notes when it does.

## First release, step by step

1. Wait for CI to be green on `main`.
2. On pypi.org: Account → Publishing → add a *pending trusted publisher*: project
   `b123d-print`, owner/repo `KD5RYN/b123d-print`, workflow `release.yml`, environment `pypi`.
3. In the GitHub repo: Settings → Environments → create `pypi` (optionally require approval).
4. `git tag v0.1.0 && git push --tags` → `release.yml` uploads to PyPI and pushes
   `ghcr.io/kd5ryn/b123d-print-mcp:0.1.0` + `latest`. Make the GHCR package public once.
5. Update the docs that say "once releases exist" (client setup, Docker, Updating).
