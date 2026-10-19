# Agent evals

How well does an agent design parts with b123d-print? The eval gives an agent a part the way a
user would (a description, the key dimensions, six rendered views of the original), lets it
design and export through the MCP server, then [compares](../using/compare.md) the export with
the original. The [benchmarks](#benchmarks-orientation-coordinates-mirrors-units-assemblies)
add written tasks with pass/fail checks for mistakes that come back when the model changes.

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

## Benchmarks: orientation, coordinates, mirrors, units, assemblies

The corpus measures how close a part comes to a reference. The benchmarks catch specific
mistakes that come back when the model changes, each with a pass/fail answer. `eval/benchmarks.toml`
lists the tasks, written the way a user would write them (no images):

| Task | Tests | Passes when |
| --- | --- | --- |
| `orient_shelf_bracket` | print orientation | an L bracket described *in use* is built on Z=0 in an orientation `suggest_orientation` ranks at the top or within 0.5 of the top score, with under 200 mm² of supports and no tip-over warning; `compare` matches the reference in any orientation |
| `datum_hole_plate` | coordinates from a datum | holes given from the plate's -X -Y corner are within 0.15 mm of their place (and the right diameter), while the origin is at the plate's centre as asked |
| `mirrored_end_brackets` | mirrored pieces | `left` and `right` each match the reference without mirroring, and `right` is the mirror image of `left`, not a copy or a copy turned round |
| `inch_cover_plate` | units | a plate drawn in inches is 76.2 x 50.8 x 6.35 mm with its holes at the converted positions (25.4 mm to the inch, not 25, not rounded) |
| `box_lid_screws` | assembly placement | `check_fit` on `assembly(d)` finds no failure, the four box/lid hole pairs line up for an M3 screw, and four screw stand-ins are in it |

Each task has a reference script and known bad scripts (the mistake made on purpose) in
`eval/benchmarks/<id>/`. The scorers in `eval/b123d_eval/scoring.py` (`pieces`, `on_bed`, `size`,
`origin`, `holes`, `orientation`, `supports`, `tip_over`, `compare`, `mirror_of`, `fit`) build the
agent's script once in the [sandbox](../using/sandbox.md) (a STEP export of each piece and, for
`fit`, the fit report of its assembly) and then read only geometry.

The self-test scores every reference and every bad script, with no model and no cost. A
reference must pass every check, a bad script must fail exactly the checks listed for it in
`bad`; CI runs it (`tests/test_eval_bench.py`), so a scorer that stops catching its mistake fails
the build:

```bash
uv run python eval/run.py selftest
```

```bash
uv run python eval/run.py list --suite bench
```

Run them with an agent like the corpus, with `--suite bench` (the `fake` agent writes the
reference script, which proves the pipeline):

```bash
ANTHROPIC_API_KEY=... uv run --group eval python eval/run.py run --suite bench --agent claude --only datum_hole_plate
```

The options are the same as above except `--threshold` (thresholds of the benchmarks are in
`benchmarks.toml`). The results: `results.json`, and `report.md` / `report.html` with one row per
task (the share of checks passed, pass or fail, the failed checks, the agent's stop reason,
turns, tool calls, cost) and below it every check's line, which says what it measured, for example

```text
[FAIL] holes [part]: 3/5 holes within 0.15 mm of their place from the bounding-box -X -Y corner (worst 0.012); missing d 3.4 at (82, 8), ...
```

Per task the folder has the prompt, the transcript, the agent's script (`candidate.py`) and
`checks.json`. A task passes only when every check passes. To tell two models apart, read which
checks failed, not only the share.

To add a task: write the prompt as a user would, a reference script and at least one bad script
per mistake the task is about, list the checks (and their parameters) and the checks each bad
script must fail, then run the self-test. A new kind of check goes in `scoring.py` (`CHECKS`).

## Adding an agent

Subclass `Agent` in `eval/b123d_eval/agents.py`, implement `run(task, tools, limits, state)`
(`tools.list_tools()` and `tools.call(name, args)` reach the MCP server; record tokens and cost
in `state` so the limits work), and register it in `AGENTS`.
