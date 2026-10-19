# Releasing

Released: **0.3.2** on [PyPI](https://pypi.org/project/b123d-print/) and as
`ghcr.io/kd5ryn/b123d-print-mcp:0.3.2` (+ `latest`, public); changes in
[CHANGELOG.md](https://github.com/KD5RYN/b123d-print/blob/main/CHANGELOG.md). This page is how the pieces ship
and how to cut the next release.

## What gets distributed

| Artifact | What it is | Who uses it | How it is built |
| --- | --- | --- | --- |
| Source repo | everything | contributors, the Claude Code plugin | `git push` |
| Python package `b123d-print` (wheel + sdist) | library, `b123d-print` CLI, `b123d-print-mcp` server, examples, AGENTS.md | every MCP client via `uvx` | `uv build` (uv_build backend) |
| Docker image | server + all dependencies | people who want container isolation | `docker build` |
| Claude Code plugin | `plugin/` (manifest, `.mcp.json`, a `pyproject.toml` + `uv.lock` that lock the server to a released PyPI version, skill, README, LICENSE, icon); the marketplace is `.claude-plugin/marketplace.json` at the repo root | Claude Code users, the Claude plugin directory | the repo itself is the marketplace |
| Docs site | `docs/` + `mkdocs.yml` | everyone | `.github/workflows/docs.yml` on every push to `main` |
| MCP Registry entry | `server.json`, pointing at the PyPI package | clients that browse the registry | `release.yml` (`mcp-publisher`, GitHub OIDC) |

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
3. **MCP Registry** from the same workflow, after the PyPI upload (see [below](#mcp-registry)).
4. **Claude plugin pin**: after the PyPI upload the workflow opens a pull request that moves the
   plugin to the new version.

Versioning: semver; bump `version` in `pyproject.toml`, `plugin/.claude-plugin/plugin.json` and `server.json` together (the plugin's pin and lock follow after the upload, in their own pull request),
tag `vX.Y.Z`, the workflow does the rest (it checks that the tag matches `pyproject.toml`).
While 0.x, the part-script convention may still change; say so in the release notes when it does.

## Cutting a release

There is no separate release commit: the version bump and the dated changelog go into the last
feature pull request of the release.

1. In that pull request, bump `version` in `pyproject.toml`, `plugin/.claude-plugin/plugin.json`
   and `server.json` (both `version` fields; a test keeps them all equal), run `uv lock`, and
   date the version's `CHANGELOG.md` section (`## X.Y.Z — YYYY-MM-DD`). The release refuses to
   start if that section is missing or still says "unreleased"; preview the notes with
   `python tools/release_notes.py X.Y.Z`. Leave `plugin/pyproject.toml`, `plugin/.mcp.json` and
   `plugin/uv.lock` alone: their pin can only move once the version is on PyPI.
2. Merge it, then tag the merge commit: `git tag vX.Y.Z <merge commit> && git push origin vX.Y.Z`.
3. `release.yml` starts and waits for approval of the `pypi` environment. Approve the deployment
   once CI on `main` is green for that commit. Then, without anything more from you:
    - `pypi` uploads the package;
    - `ghcr` pushes `ghcr.io/kd5ryn/b123d-print-mcp:X.Y.Z` + `latest`;
    - `github-release` turns the version's `CHANGELOG.md` section into the GitHub Release page
      (and creates missing pages for older tags);
    - `mcp-registry` publishes `server.json` to the MCP Registry;
    - `plugin-pin` opens a pull request on `release/plugin-pin-X.Y.Z` that sets `version` and the
      `b123d-print==X.Y.Z` pin in `plugin/pyproject.toml`, the pin in `plugin/.mcp.json`, and
      runs `uv lock --directory plugin` (a test checks the lock matches the pin and is no newer
      than the package).
4. Merge the plugin-pin pull request. A pull request opened by the workflow's `GITHUB_TOKEN` does
   not start CI on its own: close and reopen it to run CI. It touches only `plugin/`, so only
   the quick job runs.
5. Update the pinned-version examples in the docs (`b123d-print==X.Y.Z`) if they should follow.

## MCP Registry

The server is listed in the [MCP Registry](https://registry.modelcontextprotocol.io) as
`io.github.KD5RYN/b123d-print`, described by `server.json` (clients start it with
`uvx b123d-print mcp`). The registry checks ownership through the `mcp-name:` line at the top of
the README, which PyPI shows as the package description, so the entry is published only
**after** the PyPI release of that version: the `mcp-registry` job in `release.yml` runs after
`pypi`, installs a pinned `mcp-publisher` from the
[registry's GitHub releases](https://github.com/modelcontextprotocol/registry/releases) (checked
against the release's sha256), logs in with `mcp-publisher login github-oidc` (GitHub's OIDC
token for this repository: nothing stored) and runs `mcp-publisher publish`. To move to a newer
`mcp-publisher`, change `PUBLISHER_VERSION` and `PUBLISHER_SHA256` in that job (the sha256 is the
`mcp-publisher_linux_amd64.tar.gz` line of that release's `registry_X.Y.Z_checksums.txt`).

By hand, if the job fails:

```bash
brew install mcp-publisher
mcp-publisher login github     # device login in the browser, as KD5RYN
mcp-publisher publish          # reads server.json
curl "https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.KD5RYN/b123d-print"
```
