"""Eval runner: for each corpus item, give an agent the task the way a user would (description,
key dimensions, rendered views of the reference), let it design and export through the MCP
server, then compare the export with the reference and score it.

    uv run python eval/run.py run --agent fake --only <id>                 # no model, proves the pipeline
    uv run --group eval python eval/run.py run --agent claude --only <id>  # B123D_EVAL_MODEL, ANTHROPIC_API_KEY

Every item runs in a fresh workspace with its own stdio server (or, with --mcp-url, against an
HTTP server whose workspace is visible here at --remote-workspace). Results: <out>/results.json,
report.md, report.html, and per item the images, transcript and the agent's script.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from html import escape
from pathlib import Path

import anyio
import numpy as np

from b123d_print.compare import Criteria, compare, load_mesh, merge, render_comparison
from b123d_print.render import render
from .agents import Limits, RunState, Task, ToolBox, make_agent
from .corpus import DEFAULT_CACHE, Item, fetch

PROMPT = """I need this part modeled for 3D printing: {title}.

{description}

Dimensions (mm):
{dims}

The attached image shows six views of the original part (iso, top, front, right, iso from below,
bottom), with its overall size in the title. These dimensions are confirmed: don't wait for my
confirmation. Where a dimension is not given, estimate it from the images and say so in your report.

Use the b123d-print tools: create it with new_part(name="{part}") as ONE printable part with no
extra variants, model it, verify it (build_part, render_preview, section, check), then export it
with export(name="{part}", formats="stl"). Finish with a short report."""


@dataclass
class Endpoint:
    """How to reach the MCP server: a stdio command (a fresh server and workspace per item), or
    an HTTP URL plus the local path where that server's workspace is visible."""

    command: list[str] | None = None
    url: str | None = None
    remote_workspace: Path | None = None
    build_timeout: float = 240.0

    @classmethod
    def from_args(cls, cmd: str | None, url: str | None, remote_ws: str | None, build_timeout: float) -> Endpoint:
        if url:
            if not remote_ws:
                raise ValueError("--mcp-url needs --remote-workspace (where this machine sees the server's workspace) to collect the exports")
            return cls(url=url, remote_workspace=Path(remote_ws), build_timeout=build_timeout)
        return cls(command=shlex.split(cmd) if cmd else [sys.executable, "-m", "b123d_print.mcp_server"], build_timeout=build_timeout)

    def client(self, workspace: Path):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters

        if self.url:
            return Client(self.url)
        env = {**os.environ, "XDG_CONFIG_HOME": str(workspace / ".config")}  # generic printer, no user config
        return Client(StdioServerParameters(command=self.command[0], env=env,
                                            args=self.command[1:] + ["--workspace", str(workspace), "--timeout", str(self.build_timeout)]))


def task_for(item: Item, part: str, images: list[Path], ref_size) -> Task:
    dims = "\n".join(f"- {d}" for d in item.dimensions)
    prompt = PROMPT.format(title=item.title, description=item.description.strip(), dims=dims, part=part)
    return Task(item.id, part, prompt, images, hints={"bbox_mm": [float(v) for v in ref_size]})


def find_export(out_dir: Path, part: str) -> list[Path]:
    """The part's slicer files: in out/print/ (0.3.11 and later) or directly in out/ (before)."""
    for d in (out_dir / "print", out_dir):
        for name in (f"{part}.stl", f"{part}.3mf"):
            if (d / name).is_file():
                return [d / name]
    for d in (out_dir / "print", out_dir):
        found = sorted(d.glob("*.stl")) or sorted(d.glob("*.3mf")) if d.is_dir() else []
        if found:
            return found
    return []


async def run_item(item: Item, agent_name: str, endpoint: Endpoint, out: Path, limits: Limits,
                   criteria: Criteria, cache: Path = DEFAULT_CACHE, tag: str = "") -> dict:
    d = out / item.id
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    rec: dict = {"id": item.id, "title": item.title, "agent": agent_name, "difficulty": item.difficulty}
    t0 = time.time()
    ref_path = fetch(item, cache)
    ref = load_mesh(ref_path)
    render(ref, d / "reference.png", f"{item.id} (reference)")
    rec["reference"] = {"file": str(ref_path), **ref.summary()}

    part = item.id if not tag else f"{item.id}_{tag}"
    if endpoint.url:
        ws = endpoint.remote_workspace
    else:
        ws = d / "workspace"
        ws.mkdir()
    task = task_for(item, part, [d / "reference.png"], ref.size)
    (d / "prompt.txt").write_text(task.prompt, encoding="utf-8")
    await run_agent(task, agent_name, endpoint, ws, limits, d, rec)
    rec["seconds"] = round(time.time() - t0, 1)
    script = ws / "parts" / part / f"{part}.py"
    if script.is_file():
        shutil.copy(script, d / "candidate.py")

    found = find_export(ws / "parts" / part / "out", part)
    if not found:
        rec.update(score=0.0, passed=False, result="no export")
        return rec
    try:
        cand = merge([load_mesh(p) for p in found]) if len(found) > 1 else load_mesh(found[0])
        cand.source = ", ".join(str(p) for p in found)
        for p in found:
            shutil.copy(p, d / f"candidate{p.suffix}")
        cmp = compare(ref, cand, criteria=criteria)
        rec.update(score=cmp.score, passed=cmp.passed, result="compared", failures=cmp.failures(), comparison=cmp.as_dict())
        render(cand.transformed(np.array(cmp.transform)), d / "candidate.png", f"{item.id}: candidate (aligned to the reference)")
        render_comparison(ref, cand, cmp, d / "deviation.png", f"{item.id}: deviation, score {cmp.score:.1f}")
    except Exception as e:
        rec.update(score=0.0, passed=False, result=f"compare failed: {type(e).__name__}: {e}")
    return rec


async def run_agent(task: Task, agent_name: str, endpoint: Endpoint, ws: Path, limits: Limits, d: Path, rec: dict) -> RunState:
    """Let the agent work on `task` in workspace `ws` until it stops or a limit does; what it spent
    goes in rec["agent_run"], its tool calls in d/transcript.json."""
    state = RunState()
    try:
        agent = make_agent(agent_name)
        with anyio.move_on_after(limits.timeout_s) as scope:
            async with endpoint.client(ws) as client:
                await agent.run(task, ToolBox(client, limits, state), limits, state)
        if scope.cancelled_caught:
            state.stop = "timeout"
    except Exception as e:
        state.stop, state.error = "error", f"{type(e).__name__}: {e}"
    rec["agent_run"] = {k: v for k, v in asdict(state).items() if k != "transcript"}
    rec["agent_run"]["cost_usd"] = round(state.cost_usd, 4)
    (d / "transcript.json").write_text(json.dumps(state.transcript, indent=1, default=str), encoding="utf-8")
    return state


async def run_eval(items: list[Item], agent_name: str, endpoint: Endpoint, out: Path, limits: Limits,
                   criteria: Criteria, cache: Path = DEFAULT_CACHE, max_total_cost: float = 10.0) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    tag = started.strftime("%Y%m%d%H%M%S") if endpoint.url else ""  # a shared server keeps every run's parts
    results, spent = [], 0.0
    for item in items:
        if spent >= max_total_cost:
            results.append({"id": item.id, "title": item.title, "result": "skipped: total cost cap", "score": 0.0, "passed": False})
            continue
        print(f"[{item.id}] running {agent_name} ...", flush=True)
        rec = await run_item(item, agent_name, endpoint, out, limits, criteria, cache, tag)
        spent += rec.get("agent_run", {}).get("cost_usd", 0.0)
        print(f"[{item.id}] {rec['result']}: score {rec['score']:.1f} {'PASS' if rec['passed'] else 'FAIL'}"
              f" (agent: {rec.get('agent_run', {}).get('stop')}, ${rec.get('agent_run', {}).get('cost_usd', 0):.2f}, {rec.get('seconds')} s)", flush=True)
        results.append(rec)
        write_reports(out, _summary(results, agent_name, endpoint, limits, criteria, started, spent))
    summary = _summary(results, agent_name, endpoint, limits, criteria, started, spent)
    write_reports(out, summary)
    return summary


def _summary(results, agent_name, endpoint, limits, criteria, started, spent) -> dict:
    scores = [r["score"] for r in results]
    from .agents import instructions_mode, model_name

    model = model_name(agent_name)
    return {
        "started": started.isoformat(timespec="seconds"),
        "agent": agent_name,
        "model": model,
        "instructions": instructions_mode(),
        "endpoint": endpoint.url or " ".join(endpoint.command or []),
        "limits": asdict(limits),
        "criteria": asdict(criteria),
        "items": len(results),
        "passed": sum(bool(r["passed"]) for r in results),
        "mean_score": round(float(np.mean(scores)), 2) if scores else 0.0,
        "cost_usd": round(spent, 4),
        "results": results,
    }


def write_reports(out: Path, s: dict) -> None:
    (out / "results.json").write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
    head = (f"agent **{s['agent']}**{' (' + s['model'] + ')' if s['model'] else ''}, {s['items']} items, "
            f"**{s['passed']} passed**, mean score **{s['mean_score']:.1f}**, cost ${s['cost_usd']:.2f}, started {s['started']}")
    md = [f"# b123d-print eval\n\n{head}\n",
          "| item | score | pass | result | agent stop | turns | tool calls | cost | mean mm | Hausdorff mm | volume | failed checks |",
          "|---|---:|:-:|---|---|---:|---:|---:|---:|---:|---:|---|"]
    rows = []
    for r in s["results"]:
        a, m = r.get("agent_run", {}), r.get("comparison", {}).get("metrics", {})
        cells = [r["id"], f"{r['score']:.1f}", "yes" if r["passed"] else "no", r["result"], a.get("stop", ""),
                 a.get("turns", ""), a.get("tool_calls", ""), f"${a.get('cost_usd', 0):.2f}",
                 m.get("mean_mm", ""), m.get("hausdorff_mm", ""),
                 f"{m['volume_rel']:+.1%}" if "volume_rel" in m else "", ", ".join(r.get("failures", []))]
        md.append("| " + " | ".join(str(c) for c in cells) + " |")
        rows.append((r, cells))
    md.append("")
    for r, _ in rows:
        md.append(f"## {r['id']}: {r['title']}\n")
        if r.get("agent_run", {}).get("error"):
            md.append(f"Agent error: `{r['agent_run']['error']}`\n")
        imgs = [f"![{n}]({r['id']}/{n}.png)" for n in ("reference", "candidate", "deviation") if (out / r["id"] / f"{n}.png").is_file()]
        md.append(" ".join(imgs) + "\n")
    (out / "report.md").write_text("\n".join(md), encoding="utf-8")

    th = "".join(f"<th>{escape(h)}</th>" for h in ("item", "score", "pass", "result", "agent stop", "turns", "tool calls", "cost",
                                                    "mean mm", "Hausdorff mm", "volume", "failed checks"))
    trs = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in cells) + "</tr>" for _, cells in rows)
    cards = []
    for r, _ in rows:
        imgs = "".join(f'<figure><img src="{escape(r["id"])}/{n}.png" alt="{n}"><figcaption>{n}</figcaption></figure>'
                       for n in ("reference", "candidate", "deviation") if (out / r["id"] / f"{n}.png").is_file())
        err = f"<p class=err>{escape(r['agent_run']['error'])}</p>" if r.get("agent_run", {}).get("error") else ""
        cards.append(f"<section><h2>{escape(r['id'])}: {escape(r['title'])} &mdash; {r['score']:.1f}"
                     f" {'PASS' if r['passed'] else 'FAIL'}</h2>{err}<div class=imgs>{imgs}</div></section>")
    html = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>b123d-print eval</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--line:#ddd;--muted:#666}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16171a;--fg:#e8e8ea;--line:#333;--muted:#999}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;padding:16px;max-width:1500px}}
table{{border-collapse:collapse;width:100%;display:block;overflow-x:auto}}td,th{{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;white-space:nowrap}}
.imgs{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:8px}}img{{width:100%;background:#fff;border:1px solid var(--line)}}
figcaption{{color:var(--muted)}}.err{{color:#c33}}h2{{font-size:16px;margin-top:28px}}
</style></head><body><h1>b123d-print eval</h1><p>{escape(head.replace('**', ''))}</p>
<table><tr>{th}</tr>{trs}</table>{''.join(cards)}</body></html>"""
    (out / "report.html").write_text(html, encoding="utf-8")
