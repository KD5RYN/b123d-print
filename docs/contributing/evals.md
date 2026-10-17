# Agent evals

How well does an agent design parts with b123d-print? The eval gives an agent a part the way a
user would (a description, the key dimensions, six rendered views of the original), lets it
design and export through the MCP server, then [compares](../using/compare.md) the export with
the original.

This is development tooling: it lives in `eval/` in the repository and is not part of the
package, the Docker image or its dependencies (`tests/test_packaging.py` checks that).

## The reference corpus

`eval/corpus.toml` lists simple functional parts from open sources: brackets, spacers, clips,
boxes, knobs. Each entry has the download URL (pinned to a commit), the author, the license and
where it was verified, the file's SHA-256, and the description and dimensions the agent gets.
The model files are not in the repository; `fetch` downloads them into `.b123d-eval/cache/`
(git-ignored) and refuses any file whose hash changed.

```bash
uv run python eval/run.py list
```

```bash
uv run python eval/run.py fetch
```

To add a part: only permissive licenses (CC0, CC-BY, CC-BY-SA, MIT, BSD, Apache-2.0; nothing
NonCommercial or NoDerivatives), a direct download that needs no login, the URL pinned to a
commit, the author credited, and dimensions measured from the file. An entry can point to a
local file with `file = "path"` instead of `url` (for private references).

## Running

Without a model, the `fake` agent models the reference's bounding box as a block. It proves the
pipeline (server, export, compare, report) and is what CI runs:

```bash
uv run python eval/run.py run --agent fake --only <id>
```

With Claude (Anthropic API; the `eval` dependency group has the SDK):

```bash
ANTHROPIC_API_KEY=... uv run --group eval python eval/run.py run --agent claude --only <id>
```

`B123D_EVAL_MODEL` picks the model (default `claude-opus-5-5`), `B123D_EVAL_EFFORT` the effort
(default `high`). For a model without a built-in price, set `B123D_EVAL_PRICES=in,out,cache_read,cache_write`
(USD per million tokens) so the cost cap works.

| Option | Default | |
| --- | --- | --- |
| `--only id,id` | all | items to run |
| `--max-turns` | 40 | model requests per item |
| `--max-tool-calls` | 80 | per item |
| `--timeout` | 900 | seconds per item |
| `--max-cost` | 3 | USD per item |
| `--max-total-cost` | 10 | USD per run; later items are skipped |
| `--threshold name=value` | | compare's pass/fail thresholds |
| `--mcp-cmd "<command>"` | this Python's server | stdio server; `--workspace <dir>` is appended (a fresh workspace per item) |
| `--mcp-url <url>` + `--remote-workspace <dir>` | | an HTTP server, and where its workspace is visible here to collect the exports |
| `--out <dir>` | `.b123d-eval/runs/<time>-<agent>` | results |

The agent cannot see the `compare` tool (no peeking) or `use_printer`. Each item runs in a
fresh workspace in generic printer mode.

## Results

`results.json` (every number, per item and in total), `report.md` and `report.html` (a table and
the reference, the aligned candidate and the deviation view side by side), and per item the
prompt, the transcript of tool calls, the agent's script and its export.

## Adding an agent

Subclass `Agent` in `eval/b123d_eval/agents.py`, implement `run(task, tools, limits, state)`
(`tools.list_tools()` and `tools.call(name, args)` reach the MCP server; record tokens and cost
in `state` so the limits work), and register it in `AGENTS`.
