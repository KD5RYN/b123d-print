# Contributing

Issues and pull requests are welcome. To work on it:

```bash
git clone https://github.com/KD5RYN/b123d-print && cd b123d-print && uv sync
```

```bash
uv run pytest -n auto && uv run b123d-print check && uv run python tests/mcp_smoke.py
```

The smoke test drives every MCP tool; `--http` runs it over HTTP, `--ssh` through the SSH
forced command (sshd simulated), and `sh tests/ssh_e2e.sh` over a real local sshd.

```bash
uv run mkdocs serve        # the docs site at http://127.0.0.1:8000, rebuilt as you edit
```

New checks and example parts should come from something that was actually printed.

## The docs rule

**A pull request that changes behavior updates the docs in the same pull request.** A new tool,
command, flag, setting, environment variable, check or example is not done until the docs say
what it does. The drift tests (`tests/test_docs.py`, run by `uv run pytest`) enforce the
mechanical part: they fail when the code has something the docs don't mention, or the other way
round. They cannot tell whether the prose is right; the reviewer checks that.

CI builds the site with `uv run mkdocs build --strict` on every pull request: a broken link,
a missing anchor or a page left out of the navigation fails it.

| You changed | Update | Drift test |
| --- | --- | --- |
| an MCP tool, prompt or resource (`mcp_server.py`) | `docs/using/tools.md` (one table row each, every parameter named) and `skills/cad-parts/SKILL.md`'s tool list | `test_mcp_*` |
| a CLI command or flag (`cli.py`) | `docs/getting-started/cli.md` | `test_cli_documented` |
| a server flag (`b123d-print-mcp`) | `docs/getting-started/mcp-clients.md` | `test_mcp_server_flags_documented` |
| a setting (`config.Settings`) | the Keys table in `docs/using/settings.md` | `test_settings_documented` |
| an environment variable (`B123D_PRINT_*`) | the table in `docs/using/settings.md` | `test_env_vars_documented` |
| a check class or its arguments (`checks.py`, `View`) | `docs/scripts/checks-api.md`, and `docs/using/checks.md` for what it does | `test_check_api_documented` |
| a bundled example | `docs/scripts/examples.md` (images in `docs/images/`) | `test_examples_documented` |
| the eval tooling (`eval/`) | `docs/contributing/evals.md` | (none: repo-only; `tests/test_packaging.py` keeps it out of the packages) |
| the workflow rules | `src/b123d_print/data/AGENTS.md`, then copy it to `AGENTS.md` | `test_agents_md_in_sync` |
| a docs page | `nav` in `mkdocs.yml`; links in `README.md` point at the site | `test_readme_site_links`, `mkdocs build --strict` |

The [Reference](https://kd5ryn.github.io/b123d-print/reference/) page (every command's
`--help`, every tool's description, the settings) is generated from the code at build time by
`tools/docs_hooks.py`; it needs no edits.

## Where things live

- `README.md` is the short front page: what it is, pictures, quick start, links into the site.
  Longer text goes in `docs/`.
- The site is [MkDocs](https://www.mkdocs.org) with the
  [Material](https://squidfunk.github.io/mkdocs-material/) theme, versions pinned in the `dev`
  group of `pyproject.toml`. It is published to GitHub Pages from `main` by
  `.github/workflows/docs.yml`.
- The printer table is generated: `python tools/sync_orca_printers.py` refreshes
  `src/b123d_print/data/printers_orca.json` from OrcaSlicer (records the commit it used).
  `.github/workflows/orca-sync.yml` runs it monthly (or by hand from the Actions tab) and opens
  a PR only when the printer data changed; close and reopen that PR to run the full CI.
- Dependency updates: Dependabot (`.github/dependabot.yml`) opens weekly PRs for the pinned
  Python packages, the GitHub Actions and the Docker base image; CI runs on them as on any PR.
- Releasing: `docs/contributing/releasing.md`.
