"""Benchmark tasks (benchmarks.toml): the agent gets a written task (no images), designs and
exports the part through the MCP server, and its script is scored with pass/fail checks
(scoring.py) instead of a surface comparison. Dialog tasks (kind = "dialog") leave dimensions
out: the agent's first turn is scored instead (dialog.py), it must ask before it models.

    uv run python eval/run.py list --suite bench
    uv run python eval/run.py selftest                                     # references + known bad scripts, no model
    uv run python eval/run.py run --suite bench --agent fake               # the reference through the server
    uv run --group eval python eval/run.py run --suite bench --agent claude --only <id>

Results: <out>/results.json, report.md, report.html, and per task the prompt, transcript, the
agent's script and every check's result (checks.json).
"""

from __future__ import annotations

import json
import shutil
import time
import tomllib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from html import escape
from pathlib import Path

from . import dialog, scoring

BENCH_PROMPT = """{prompt}

These dimensions are confirmed: don't wait for my confirmation, and where something is not given,
choose and say so in your report.

Use the b123d-print tools: create it with new_part(name="{part}") as one part script with no extra
variants, model it, verify it (build_part, render_preview, section, check{fit}), then export it
with export(name="{part}", formats="step,stl"). Finish with a short report."""

# a dialog task: the request as a user would type it, nothing about confirming or asking
DIALOG_PROMPT = """{prompt}

Use the b123d-print tools; call the part "{part}"."""


def default_manifest() -> Path:
    return Path(__file__).resolve().parents[1] / "benchmarks.toml"


@dataclass
class BenchTask:
    id: str
    title: str
    prompt: str
    reference: str
    checks: list[dict]
    mistake: str = ""
    bad: dict = field(default_factory=dict)  # file next to the reference -> checks it must fail
    kind: str = "script"  # script: score the part script; dialog: score the first turn (reference and bad are run records)
    base: Path = Path(".")

    @property
    def reference_path(self) -> Path:
        return self.base / self.reference

    def bad_paths(self) -> dict[Path, list[str]]:
        return {self.reference_path.parent / f: want for f, want in self.bad.items()}

    @property
    def needs_fit(self) -> bool:
        return self.kind == "script" and any(c["check"] in scoring.NEEDS_FIT for c in self.checks)

    @property
    def dialog(self) -> bool:
        return self.kind == "dialog"

    # what the corpus list prints
    @property
    def difficulty(self) -> str:
        return "bench"

    @property
    def license(self) -> str:
        return "MIT (repo)"


def load_tasks(path: str | Path | None = None) -> list[BenchTask]:
    path = Path(path) if path else default_manifest()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    known = set(BenchTask.__dataclass_fields__) - {"base"}
    tasks = []
    for d in data.get("task", []):
        extra = set(d) - known
        if extra:
            raise ValueError(f"{path}: task {d.get('id')!r} has unknown keys {sorted(extra)}")
        kind = d.get("kind", "script")
        if kind not in ("script", "dialog"):
            raise ValueError(f"{path}: task {d.get('id')!r}: unknown kind {kind!r}; have dialog, script")
        known_checks = dialog.CHECKS if kind == "dialog" else scoring.CHECKS
        for c in d.get("checks", []):
            if c.get("check") not in known_checks:
                raise ValueError(f"{path}: task {d.get('id')!r}: unknown check {c.get('check')!r}; have {sorted(known_checks)}")
        tasks.append(BenchTask(**d, base=path.parent))
    ids = [t.id for t in tasks]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate ids")
    return tasks


def select(tasks: list[BenchTask], only: str | None) -> list[BenchTask]:
    if not only:
        return tasks
    want = [s.strip() for s in only.split(",") if s.strip()]
    missing = set(want) - {t.id for t in tasks}
    if missing:
        raise ValueError(f"not in the benchmarks: {sorted(missing)}")
    return [t for t in tasks if t.id in want]


def prompt_for(task: BenchTask, part: str) -> str:
    if task.dialog:
        return DIALOG_PROMPT.format(prompt=task.prompt.strip(), part=part)
    return BENCH_PROMPT.format(prompt=task.prompt.strip(), part=part, fit=", check_fit" if task.needs_fit else "")


# ---------------------------------------------------------------------------------------------
# scoring a script


def reference(task: BenchTask, out: Path) -> scoring.Candidate:
    """The task's reference script, built in this process (it is the repository's own code)."""
    return scoring.build(task.reference_path, out, scoring.in_process, fit=task.needs_fit)


def score_script(task: BenchTask, script: Path, out: Path, run: scoring.JobRunner = scoring.in_process,
                 workspace: Path | None = None, ref: scoring.Candidate | None = None) -> dict:
    """Build `script` (with `run`: sandboxed for agent output) and run the task's checks."""
    out.mkdir(parents=True, exist_ok=True)
    needs_ref = any(c["check"] == "compare" for c in task.checks)
    if ref is None and needs_ref:
        ref = reference(task, out / "reference")
    cand = scoring.build(script, out / "candidate", run, workspace, fit=task.needs_fit)
    results = scoring.run_checks(cand, ref, task.checks)
    return {**scoring.summary(results), "checks": [r.as_dict() for r in results]}


def score_dialog(task: BenchTask, run: dict) -> dict:
    """Run a dialog task's checks on a run record (dialog.record(state), or a saved fixture)."""
    results = dialog.run_checks(run, task.checks)
    return {**scoring.summary(results), "checks": [r.as_dict() for r in results]}


def selftest(tasks: list[BenchTask], out: Path) -> list[dict]:
    """Every reference must pass every check; every known bad script must fail exactly the checks
    the manifest lists for it (as a multiset of check names). [{task, script, ok, why, ...}]"""
    rows = []
    for t in tasks:
        if t.dialog:  # reference and bad files are run records: no build
            scored = [(t.reference_path, [])] + list(t.bad_paths().items())
            for path, want in scored:
                res = score_dialog(t, dialog.load(path))
                got = sorted(r["check"] for r in res["checks"] if not r["ok"])
                ok = got == sorted(want)
                why = "" if ok else (f"reference fails {res['failures']}" if not want else f"failed {got}, expected {sorted(want)}")
                rows.append({"task": t.id, "script": path.name, "expect": sorted(want), "ok": ok, "why": why, "result": res})
            continue
        d = out / t.id
        ref = reference(t, d / "reference")
        res = score_script(t, t.reference_path, d / "good", ref=ref)
        rows.append({"task": t.id, "script": t.reference_path.name, "expect": [], "ok": res["passed"],
                     "why": "" if res["passed"] else f"reference fails {res['failures']}", "result": res})
        for path, want in t.bad_paths().items():
            res = score_script(t, path, d / path.stem, ref=ref)
            got = sorted(r["check"] for r in res["checks"] if not r["ok"])
            ok = got == sorted(want)
            rows.append({"task": t.id, "script": path.name, "expect": sorted(want), "ok": ok,
                         "why": "" if ok else f"failed {got}, expected {sorted(want)}", "result": res})
    return rows


def selftest_text(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        tag = "good" if not r["expect"] else "bad "
        lines.append(f"[{'ok' if r['ok'] else 'FAIL':4}] {r['task']:24} {tag} {r['script']:28} "
                     f"{r['why'] or ('passes every check' if not r['expect'] else 'fails ' + ', '.join(r['expect']))}")
        if not r["ok"]:
            lines += ["       " + c_line(c) for c in r["result"]["checks"]]
    n = sum(r["ok"] for r in rows)
    lines.append(f"\n{n}/{len(rows)} scripts scored as expected")
    return "\n".join(lines)


def c_line(c: dict) -> str:
    return scoring.Result(c["check"], c["ok"], c["detail"], c["piece"]).line()


# ---------------------------------------------------------------------------------------------
# running an agent on the tasks


async def run_task(task: BenchTask, agent_name: str, endpoint, out: Path, limits, tag: str = "") -> dict:
    from .agents import Task
    from .runner import run_agent

    d = out / task.id
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    rec: dict = {"id": task.id, "title": task.title, "mistake": task.mistake, "agent": agent_name}
    t0 = time.time()
    part = task.id if not tag else f"{task.id}_{tag}"
    ws = endpoint.remote_workspace if endpoint.url else d / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    if task.dialog:  # the fake agent replies with the reference's last message
        hints = {"reply": dialog.load(task.reference_path)["final_text"]}
    else:
        hints = {"code": task.reference_path.read_text(encoding="utf-8"), "formats": "step,stl"}
    t = Task(task.id, part, prompt_for(task, part), [], hints=hints, interactive=task.dialog)
    (d / "prompt.txt").write_text(t.prompt, encoding="utf-8")
    script = ws / "parts" / part / f"{part}.py"
    state = await run_agent(t, agent_name, endpoint, ws, limits, d, rec)
    rec["seconds"] = round(time.time() - t0, 1)
    if task.dialog and state.stop == "error":  # no answer to score: not a partial pass
        rec.update(score=0.0, passed=False, result="agent error", checks=[], failures=["agent"])
        return rec
    if task.dialog:
        res = score_dialog(task, dialog.record(state))
        rec.update(result="scored", **res)
        (d / "checks.json").write_text(json.dumps(res["checks"], indent=1, default=str), encoding="utf-8")
        if state.final_text:
            (d / "reply.md").write_text(state.final_text, encoding="utf-8")
        return rec
    if not script.is_file():
        rec.update(score=0.0, passed=False, result="no script", checks=[], failures=["script"])
        return rec
    shutil.copy(script, d / "candidate.py")
    res = score_script(task, script, d / "score", scoring.sandboxed(endpoint.build_timeout), ws)
    rec.update(result="scored", **res)
    (d / "checks.json").write_text(json.dumps(res["checks"], indent=1, default=str), encoding="utf-8")
    return rec


async def run_bench(tasks: list[BenchTask], agent_name: str, endpoint, out: Path, limits, max_total_cost: float = 10.0) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)
    tag = started.strftime("%Y%m%d%H%M%S") if endpoint.url else ""
    results, spent = [], 0.0
    for t in tasks:
        if spent >= max_total_cost:
            results.append({"id": t.id, "title": t.title, "mistake": t.mistake, "result": "skipped: total cost cap",
                            "score": 0.0, "passed": False, "checks": [], "failures": []})
            continue
        print(f"[{t.id}] running {agent_name} ...", flush=True)
        rec = await run_task(t, agent_name, endpoint, out, limits, tag)
        spent += rec.get("agent_run", {}).get("cost_usd", 0.0)
        a = rec.get("agent_run", {})
        print(f"[{t.id}] {rec['result']}: {rec['score']:.0f}% {'PASS' if rec['passed'] else 'FAIL'}"
              + (f" (failed {', '.join(rec['failures'])})" if rec.get("failures") else "")
              + f" (agent: {a.get('stop')}, ${a.get('cost_usd', 0):.2f}, {rec.get('seconds')} s)", flush=True)
        results.append(rec)
        write_reports(out, _summary(results, agent_name, endpoint, limits, started, spent))
    s = _summary(results, agent_name, endpoint, limits, started, spent)
    write_reports(out, s)
    return s


def _summary(results, agent_name, endpoint, limits, started, spent) -> dict:
    from .agents import instructions_mode, model_name

    scores = [r["score"] for r in results]
    return {
        "suite": "bench",
        "started": started.isoformat(timespec="seconds"),
        "agent": agent_name,
        "model": model_name(agent_name),
        "instructions": instructions_mode(),
        "endpoint": endpoint.url or " ".join(endpoint.command or []),
        "limits": asdict(limits),
        "items": len(results),
        "passed": sum(bool(r["passed"]) for r in results),
        "mean_score": round(sum(scores) / len(scores), 2) if scores else 0.0,
        "cost_usd": round(spent, 4),
        "results": results,
    }


def write_reports(out: Path, s: dict) -> None:
    (out / "results.json").write_text(json.dumps(s, indent=1, default=str), encoding="utf-8")
    head = (f"agent **{s['agent']}**{' (' + s['model'] + ')' if s['model'] else ''}, {s['items']} tasks, "
            f"**{s['passed']} passed**, mean **{s['mean_score']:.0f}%** of checks, cost ${s['cost_usd']:.2f}, started {s['started']}")
    cols = ("task", "tests", "checks passed", "pass", "result", "agent stop", "turns", "tool calls", "cost", "failed checks")
    md = [f"# b123d-print benchmarks\n\n{head}\n", "| " + " | ".join(cols) + " |", "|---|---|---:|:-:|---|---|---:|---:|---:|---|"]
    rows = []
    for r in s["results"]:
        a = r.get("agent_run", {})
        cells = [r["id"], r.get("mistake", ""), f"{r['score']:.0f}%", "yes" if r["passed"] else "no", r["result"], a.get("stop", ""),
                 a.get("turns", ""), a.get("tool_calls", ""), f"${a.get('cost_usd', 0):.2f}", ", ".join(r.get("failures", []))]
        md.append("| " + " | ".join(str(c) for c in cells) + " |")
        rows.append((r, cells))
    for r, _ in rows:
        md.append(f"\n## {r['id']}: {r['title']}\n")
        if r.get("agent_run", {}).get("error"):
            md.append(f"Agent error: `{r['agent_run']['error']}`\n")
        md += [f"- {c_line(c)}" for c in r.get("checks", [])]
    (out / "report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    th = "".join(f"<th>{escape(h)}</th>" for h in cols)
    trs = "".join("<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in cells) + "</tr>" for _, cells in rows)
    cards = []
    for r, _ in rows:
        lis = "".join(f"<li class={'ok' if c['ok'] else 'bad'}>{escape(c_line(c))}</li>" for c in r.get("checks", []))
        err = f"<p class=bad>{escape(r['agent_run']['error'])}</p>" if r.get("agent_run", {}).get("error") else ""
        cards.append(f"<section><h2>{escape(r['id'])}: {escape(r['title'])} &mdash; {r['score']:.0f}% "
                     f"{'PASS' if r['passed'] else 'FAIL'}</h2>{err}<ul>{lis}</ul></section>")
    html = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>b123d-print benchmarks</title><style>
:root{{--bg:#fff;--fg:#1d1d1f;--line:#ddd;--ok:#2a7a2a;--bad:#c33}}
@media (prefers-color-scheme: dark){{:root{{--bg:#16171a;--fg:#e8e8ea;--line:#333;--ok:#6c6;--bad:#f77}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0 auto;padding:16px;max-width:1500px}}
table{{border-collapse:collapse;width:100%;display:block;overflow-x:auto}}td,th{{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;white-space:nowrap}}
li{{font-family:ui-monospace,monospace;font-size:12px;overflow-wrap:anywhere}}.ok{{color:var(--ok)}}.bad{{color:var(--bad)}}h2{{font-size:16px;margin-top:28px}}
</style></head><body><h1>b123d-print benchmarks</h1><p>{escape(head.replace('**', ''))}</p>
<table><tr>{th}</tr>{trs}</table>{''.join(cards)}</body></html>"""
    (out / "report.html").write_text(html, encoding="utf-8")
