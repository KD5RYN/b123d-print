# Releasing

Released: **0.2.0** on [PyPI](https://pypi.org/project/b123d-print/) and as
`ghcr.io/kd5ryn/b123d-print-mcp:0.2.0` (+ `latest`, public); changes in
[CHANGELOG.md](https://github.com/KD5RYN/b123d-print/blob/main/CHANGELOG.md). This page is how the pieces ship
and how to cut the next release.

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

## How it ships

1. **PyPI via Trusted Publishing** (done) — `.github/workflows/release.yml` builds on a version
   tag and uploads with OIDC (no API token stored anywhere). The trusted publisher is
   `KD5RYN/b123d-print`, workflow `release.yml`, environment `pypi`; that environment requires
   approval and only accepts `v*` tags.
2. **Docker image** on GHCR from the same workflow (done; the package is public). It redistributes OpenCascade (LGPL-2.1)
   binaries: keep the license files in the image and link the OCCT source (see
   [Credits and licenses](../credits.md)). The wheel does not redistribute anything, so it has no
   such duty.
3. **MCP Registry**: after PyPI, add `<!-- mcp-name: io.github.KD5RYN/b123d-print -->` to the
   README (it proves ownership of the PyPI package) and publish a `server.json`.

Versioning: semver; bump `version` in `pyproject.toml` and `.claude-plugin/plugin.json` together,
tag `vX.Y.Z`, the workflow does the rest (it checks that the tag matches `pyproject.toml`).
While 0.x, the part-script convention may still change; say so in the release notes when it does.

## Cutting a release

1. Wait for CI to be green on `main`.
2. Bump `version` in `pyproject.toml` and `.claude-plugin/plugin.json`, run `uv lock`, merge.
3. `git tag vX.Y.Z && git push origin vX.Y.Z` → `release.yml` waits for approval of the `pypi`
   environment, then uploads to PyPI and pushes `ghcr.io/kd5ryn/b123d-print-mcp:X.Y.Z` + `latest`.
4. The release notes write themselves: the `github-release` job turns the version's
   `CHANGELOG.md` section into the GitHub Release page (and creates missing pages for older
   tags). The release refuses to start if that section is missing or still says "unreleased",
   so date it in step 2. Preview: `python tools/release_notes.py X.Y.Z`.
5. Update the pinned-version examples in the docs (`b123d-print==0.2.0`) if they should follow.
