"""Scorers for dialog tasks (benchmarks.toml, kind = "dialog"): pass/fail checks on what the agent
did and said in its first turn, not on a part script.

A dialog task gives the agent a request with dimensions missing. The right first turn lists the
dimensions it has and the ones it needs, asks, and stops, without writing or building a part.
The checks read a run record, {"stop": ..., "final_text": ..., "transcript": [...]} (the agent's
RunState, or a saved fixture), and nothing else:

    no_tool      none of these tools was called (write_part, build_part, ...)
    asked        the turn ended on its own (not at a limit) and its last text asks: a question, or
                 a request such as "I need ..." or "please send ..."
    mentions     the agent's text names every group of things: each group is a list of regexes
                 (case-insensitive), one match is enough

Each check returns a scoring.Result; a task passes when every one passes.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .scoring import Result


def load(path: Path) -> dict:
    """A saved run record (a fixture): {"stop", "final_text", "transcript"}."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def record(state) -> dict:
    """The run record of an agent's RunState."""
    return {"stop": state.stop, "final_text": state.final_text, "transcript": state.transcript}


def _calls(run: dict) -> list[str]:
    return [e["name"] for e in run.get("transcript", []) if e.get("type") == "tool"]


def _texts(run: dict) -> list[str]:
    texts = [e.get("text", "") for e in run.get("transcript", []) if e.get("type") == "model" and e.get("text")]
    if run.get("final_text") and run["final_text"] not in texts:
        texts.append(run["final_text"])
    return texts


def check_no_tool(run: dict, tools: list[str]) -> Result:
    hit = [n for n in _calls(run) if n in tools]
    if hit:
        return Result("no_tool", False, f"called {', '.join(dict.fromkeys(hit))} before the user answered", value=hit, limit=tools)
    return Result("no_tool", True, f"none of {', '.join(tools)} called ({len(_calls(run))} other tool calls)", value=[], limit=tools)


# a request without a question mark: "I need a few dimensions:", "Please send ...", "Let me know ..."
REQUEST = re.compile(r"\b(I need|I'll need|I will need|please (send|provide|give|tell|measure|confirm|share|let)|let me know|"
                     r"waiting for|once you (send|give|provide|confirm))\b", re.IGNORECASE)


def check_asked(run: dict) -> Result:
    stop, last = run.get("stop", ""), (run.get("final_text") or "").strip()
    if stop != "done":
        return Result("asked", False, f"the turn did not end on its own (stop: {stop})", value=stop)
    sentences = [s.strip() for s in re.split(r"(?<=[.?!:])\s+", last) if s.strip()]
    asks = [s for s in sentences if s.endswith("?") or REQUEST.search(s)]
    if not asks:
        return Result("asked", False, "the last message asks for nothing: " + (last[-160:] or "(empty)"), value=last[-160:])
    return Result("asked", True, "stopped and asked: " + asks[-1][-160:], value=asks[-1][-160:])


def check_mentions(run: dict, groups: list[dict]) -> Result:
    text = "\n".join(_texts(run))
    found, missing = [], []
    for g in groups:
        (found if any(re.search(p, text, re.IGNORECASE) for p in g["any"]) else missing).append(g["label"])
    detail = f"{len(found)}/{len(groups)} named" + (f"; missing: {', '.join(missing)}" if missing else f": {', '.join(found)}")
    return Result("mentions", not missing, detail, value=found, limit=[g["label"] for g in groups])


CHECKS = {"no_tool": check_no_tool, "asked": check_asked, "mentions": check_mentions}


def run_checks(run: dict, specs: list[dict]) -> list[Result]:
    out = []
    for spec in specs:
        params = {k: v for k, v in spec.items() if k != "check"}
        try:
            out.append(CHECKS[spec["check"]](run, **params))
        except Exception as e:  # noqa: BLE001 - a malformed spec or record: the check fails with the reason
            out.append(Result(spec["check"], False, f"could not run: {type(e).__name__}: {e}"))
    return out
