"""Agent eval: reference corpus + runner (repo-only dev tooling; not part of the package).

    uv run python eval/run.py list
    uv run python eval/run.py fetch [--only id,id]
    uv run python eval/run.py run --agent fake [--only id]                  # no model
    uv run --group eval python eval/run.py run --agent claude --only id     # ANTHROPIC_API_KEY, B123D_EVAL_MODEL

See eval/README.md.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from b123d_eval import corpus  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="eval/run.py", description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, hlp in (("list", "list the corpus"), ("fetch", "download the corpus into the cache and verify hashes"),
                      ("run", "run an agent on corpus items, compare and report")):
        q = sub.add_parser(name, help=hlp)
        q.add_argument("--manifest", help="corpus TOML (default: eval/corpus.toml)")
        q.add_argument("--only", help="comma-separated item ids")
        q.add_argument("--cache", default=str(corpus.DEFAULT_CACHE), help=f"download cache (default {corpus.DEFAULT_CACHE})")
        if name == "run":
            q.add_argument("--agent", required=True, help="fake (no model) or claude (B123D_EVAL_MODEL, ANTHROPIC_API_KEY)")
            q.add_argument("--out", help="results folder (default .b123d-eval/runs/<time>-<agent>)")
            q.add_argument("--mcp-cmd", help="stdio server command (default: this Python's b123d_print.mcp_server); --workspace is appended")
            q.add_argument("--mcp-url", help="Streamable HTTP endpoint instead of stdio")
            q.add_argument("--remote-workspace", help="with --mcp-url: local path of that server's workspace")
            q.add_argument("--build-timeout", type=float, default=240.0, help="seconds per sandboxed build (stdio)")
            q.add_argument("--max-turns", type=int, default=40)
            q.add_argument("--max-tool-calls", type=int, default=80)
            q.add_argument("--timeout", type=float, default=900.0, help="seconds per item")
            q.add_argument("--max-cost", type=float, default=3.0, help="USD per item")
            q.add_argument("--max-total-cost", type=float, default=10.0, help="USD for the run; later items are skipped")
            q.add_argument("--threshold", action="append", metavar="NAME=VALUE", help="compare pass/fail threshold override")
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        items = corpus.select(corpus.load_manifest(args.manifest), args.only)
    except ValueError as e:
        sys.exit(f"eval: {e}")
    cache = Path(args.cache)
    if args.cmd == "list":
        for it in items:
            print(f"{it.id:28} {it.difficulty:7} {it.license:13} {it.title}")
        return 0
    if args.cmd == "fetch":
        res = corpus.fetch_all(items, cache)
        for k, v in res.items():
            print(f"{k:28} {v}")
        return 1 if any(v.startswith("FAILED") for v in res.values()) else 0

    import anyio

    from b123d_eval.agents import Limits
    from b123d_eval.runner import Endpoint, run_eval
    from b123d_print.compare import Criteria

    try:
        endpoint = Endpoint.from_args(args.mcp_cmd, args.mcp_url, args.remote_workspace, args.build_timeout)
        crit = Criteria.from_pairs(args.threshold)
    except ValueError as e:
        sys.exit(f"eval: {e}")
    limits = Limits(max_turns=args.max_turns, max_tool_calls=args.max_tool_calls, timeout_s=args.timeout, max_cost_usd=args.max_cost)
    out = Path(args.out or Path(".b123d-eval") / "runs" / f"{datetime.now():%Y%m%d-%H%M%S}-{args.agent}").resolve()
    s = anyio.run(lambda: run_eval(items, args.agent, endpoint, out, limits, crit, cache, args.max_total_cost))
    print(f"\n{s['passed']}/{s['items']} passed, mean score {s['mean_score']:.1f}, cost ${s['cost_usd']:.2f}\nreport: {out / 'report.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
