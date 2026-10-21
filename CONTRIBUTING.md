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

## How we work

**Issues.** Every piece of work starts from an issue.

- Before you start, **comment on the issue** to say you are taking it. A maintainer adds the
  `in progress` label, and you, or your draft pull request, are the link on the issue.
- An issue labeled `in progress` is taken; ask on it before doing the same work.
- An issue labeled `blocked` waits on other work; its comment says what. Please hold off on a
  pull request for it until the label is gone.
- Both labels come off on their own when the issue closes (`.github/workflows/issue-labels.yml`).
- Want somewhere to start? Look for `good first issue` and `help wanted`.

**Pull requests.**

- One pull request per change (one issue, or a few small related ones). Say `Closes #N` in the
  description so the issue closes when it merges.
- Run `tools/preflight.sh` first (below) and push once when it passes; batch any fixes for CI
  into as few pushes as you can.
- A maintainer reviews every pull request. Changes to the sandbox and worker (`sandbox.py`,
  `worker.py`, `jobqueue.py`, `deploy/`), tokens and links (`tokens.py`, `links.py`,
  `handoff.py`, `viewer.py`) and the release workflows get a careful security review, so expect
  questions there.
- A single pull request is squash-merged. When several are ready at once, a maintainer may
  merge them together through one combining pull request with a merge commit, so CI runs once
  and each contributor's commits are kept.
- Merging does not release. Releases are cut from `main` when a set of changes is ready
  ([Releasing](https://kd5ryn.github.io/b123d-print/contributing/releasing/)).

**Security problems: do not open a public issue.** Report them privately: see
[SECURITY.md](https://github.com/KD5RYN/b123d-print/blob/main/SECURITY.md).

## Before you push

```bash
tools/preflight.sh
```

It runs what CI runs that can run on your machine: the unit tests in the plain-ASCII locale
(`LANG=C LC_ALL=C uv run pytest -q -n auto`), the checks on every bundled example, the stdio MCP
end-to-end test, the real-sshd test (on Linux with bubblewrap and sshd, or anywhere in a Docker
container), the strict docs build and, when the `claude` CLI is on your PATH,
`claude plugin validate --strict` on `plugin/` and on the marketplace at the root. It ends with
one line, `preflight PASS (...)` or `preflight FAIL (...)`, naming each step that passed, failed
or was skipped, and where its log is. Push only after it passes; a CI run takes about ten
minutes on three operating systems, and each push to a pull request starts one (a newer push
cancels the run still going).

CI skips the long jobs for a pull request that touches only `docs/`, Markdown files at the root,
`mkdocs.yml`, `server.json`, `plugin/`, or a housekeeping workflow that cannot affect a build or a
release (`issue-labels.yml`, `orca-sync.yml`, `dependabot.yml`): a quick job runs
`tests/test_docs.py`, `tests/test_config_and_cli.py`, the docs build and a parse of every
workflow file, and the other jobs report with their steps skipped. `ci.yml`, `release.yml` and
`docs.yml` always get the full run. `tools/ci_scope.sh` decides (`git diff --name-only main | sh tools/ci_scope.sh` shows
what CI will do). Pushes to `main` always run everything.

Tests do not assert wall-clock times: CI runners are shared and slow down without warning. Assert
the outcome (it timed out, the child is gone, the result came before the other) and keep any
timeout a hang guard well above the expected time. A test that runs builds through
`sandbox.run_job` gets its own build slots (`monkeypatch.setattr(sandbox, "SLOT_DIR", tmp_path / "slots")`),
so it does not wait for the builds of tests running beside it.

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
| an MCP tool, prompt or resource (`mcp_server.py`) | `docs/using/tools.md` (one table row each, every parameter named); the plugin's skill need not list it (it points to the guide, and `plugin/` changes wait for the Claude directory's review) | `test_mcp_*` |
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
