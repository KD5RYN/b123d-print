"""Pluggable agents for the eval runner.

An agent gets a `Task` (the prompt a user would write + reference images) and a `ToolBox` (the
b123d-print MCP tools, already connected) and works until it is done or a limit stops it. It
records what it spends in `RunState`, which the runner reads even after a timeout.

Adapters: `fake` (deterministic, no model: a box of the reference's size; proves the pipeline)
and `claude` (Anthropic API; model from B123D_EVAL_MODEL, key from ANTHROPIC_API_KEY or the
SDK's other credential sources). Add another by subclassing Agent and registering it in AGENTS.
"""

from __future__ import annotations

import base64
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

HIDDEN_TOOLS = {"compare", "use_printer"}  # no peeking at the reference; no changing the user's printer


@dataclass
class Task:
    item_id: str
    part_name: str
    prompt: str
    images: list[Path]
    hints: dict = field(default_factory=dict)  # facts for the fake agent only (e.g. the reference bbox)


@dataclass
class Limits:
    max_turns: int = 40  # model requests per item
    max_tool_calls: int = 80
    timeout_s: float = 900.0
    max_cost_usd: float = 3.0  # per item


@dataclass
class RunState:
    turns: int = 0
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost_usd: float = 0.0
    stop: str = "running"  # done | max_turns | max_tool_calls | cost_cap | timeout | error
    error: str = ""
    final_text: str = ""
    transcript: list = field(default_factory=list)

    def log(self, kind: str, **kw) -> None:
        self.transcript.append({"t": round(time.time(), 2), "type": kind, **kw})


@dataclass
class ToolOutput:
    text: str
    images: list[str]  # base64 PNG
    is_error: bool


class ToolBox:
    """The MCP tools as an agent sees them: listing (minus HIDDEN_TOOLS) and calls, logged and
    counted against the limits."""

    def __init__(self, client, limits: Limits, state: RunState, hidden=HIDDEN_TOOLS):
        self.client, self.limits, self.state, self.hidden = client, limits, state, set(hidden)

    @property
    def instructions(self) -> str:
        return getattr(self.client, "instructions", None) or ""

    async def list_tools(self) -> list[dict]:
        tools = (await self.client.list_tools()).tools
        return [{"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
                for t in tools if t.name not in self.hidden]

    async def call(self, name: str, args: dict) -> ToolOutput:
        st = self.state
        if name in self.hidden:
            out = ToolOutput(f"tool {name!r} is not available in this session", [], True)
        elif st.tool_calls >= self.limits.max_tool_calls:
            st.stop = "max_tool_calls"
            out = ToolOutput("tool call limit reached; stop and report", [], True)
        else:
            st.tool_calls += 1
            try:
                res = await self.client.call_tool(name, args)
                text = "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")
                imgs = [c.data for c in res.content if getattr(c, "type", "") == "image"]
                out = ToolOutput(text, imgs, bool(res.is_error))
            except Exception as e:  # transport errors go back to the agent as tool errors
                out = ToolOutput(f"tool call failed: {e!r}", [], True)
        st.log("tool", name=name, args=args, is_error=out.is_error, result=out.text[:4000], images=len(out.images))
        return out


class Agent:
    name = "base"

    async def run(self, task: Task, tools: ToolBox, limits: Limits, state: RunState) -> None:
        raise NotImplementedError


# ---------------------------------------------------------------------------------------------


FAKE_SCRIPT = '''"""Eval fake agent: a plain block of the reference's overall size."""
from dataclasses import dataclass
from build123d import Align, Box, Part

BED = (Align.CENTER, Align.CENTER, Align.MIN)


@dataclass(frozen=True)
class Dims:
    X: float = {x}  # reference bounding box
    Y: float = {y}
    Z: float = {z}


VARIANTS = {{"": {{}}}}


def build(d: Dims) -> Part:
    return Box(d.X, d.Y, d.Z, align=BED)
'''


class FakeAgent(Agent):
    """No model: models the reference's bounding box as a block, through the real MCP tools."""

    name = "fake"

    async def run(self, task, tools, limits, state):
        x, y, z = (round(float(v), 3) for v in task.hints.get("bbox_mm", (20, 20, 10)))
        names = {t["name"] for t in await tools.list_tools()}
        missing = {"new_part", "write_part", "build_part", "check", "export"} - names
        if missing:
            raise RuntimeError(f"MCP server lacks tools {sorted(missing)}")
        for name, args in (("new_part", {"name": task.part_name, "description": "eval fake agent"}),
                           ("write_part", {"name": task.part_name, "code": FAKE_SCRIPT.format(x=x, y=y, z=z)}),
                           ("build_part", {"name": task.part_name}),
                           ("check", {"name": task.part_name}),
                           ("export", {"name": task.part_name, "formats": "stl"})):
            state.turns += 1
            out = await tools.call(name, args)
            if out.is_error:
                raise RuntimeError(f"{name}: {out.text}")
        state.final_text = f"Modeled {task.part_name} as a {x} x {y} x {z} mm block (fake agent)."
        state.stop = "done"


# ---------------------------------------------------------------------------------------------

# USD per million tokens: input, output, cache read, cache write (5 min). Override with
# B123D_EVAL_PRICES="in,out,cache_read,cache_write" for a model not listed here.
PRICES = {
    "claude-fable-5-1": (10.0, 50.0, 1.0, 12.5),
    "claude-opus-5-5": (4.0, 20.0, 0.2, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.5, 6.25),
    "claude-sonnet-5-5": (2.0, 10.0, 0.2, 2.5),
    "claude-sonnet-5": (2.0, 10.0, 0.2, 2.5),
    "claude-haiku-5-5": (0.1, 0.5, 0.01, 0.125),
}
DEFAULT_MODEL = "claude-opus-5-5"


def prices(model: str) -> tuple[float, float, float, float]:
    env = os.environ.get("B123D_EVAL_PRICES")
    if env:
        a, b, c, d = (float(v) for v in env.split(","))
        return a, b, c, d
    if model not in PRICES:
        raise ValueError(f"no price for {model!r}: set B123D_EVAL_PRICES=in,out,cache_read,cache_write (USD per MTok) so the cost cap works")
    return PRICES[model]


class ClaudeAgent(Agent):
    """Anthropic Messages API, manual tool loop over the MCP tools.

    Env: B123D_EVAL_MODEL (default claude-opus-5-5), B123D_EVAL_EFFORT (default high),
    ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / an `ant auth login` profile (read by the SDK).
    The history is append-only (thinking blocks stay valid); tools and system are cached."""

    name = "claude"

    def __init__(self):
        try:
            import anthropic
        except ImportError:
            raise RuntimeError("the claude agent needs the 'eval' extra: uv sync --extra eval (or pip install 'b123d-print[eval]')") from None
        self.anthropic = anthropic
        self.model = os.environ.get("B123D_EVAL_MODEL", DEFAULT_MODEL)
        self.effort = os.environ.get("B123D_EVAL_EFFORT", "high")
        self.price = prices(self.model)
        self.client = anthropic.AsyncAnthropic()

    def _charge(self, usage, state: RunState) -> None:
        pin, pout, pread, pwrite = self.price
        i, o = usage.input_tokens or 0, usage.output_tokens or 0
        r, w = getattr(usage, "cache_read_input_tokens", 0) or 0, getattr(usage, "cache_creation_input_tokens", 0) or 0
        state.input_tokens += i
        state.output_tokens += o
        state.cache_read_tokens += r
        state.cache_write_tokens += w
        state.cost_usd += (i * pin + o * pout + r * pread + w * pwrite) / 1e6

    async def run(self, task, tools, limits, state):
        system = (
            "You are a CAD designer working for a user through the b123d-print MCP tools. "
            "Work on your own until the part is exported; the user is not available for questions.\n\n"
            + tools.instructions
        )
        tool_defs = await tools.list_tools()
        tool_defs[-1] = {**tool_defs[-1], "cache_control": {"type": "ephemeral"}}
        content = [{"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                                "data": base64.standard_b64encode(p.read_bytes()).decode()}}
                   for p in task.images]
        messages = [{"role": "user", "content": content + [{"type": "text", "text": task.prompt}]}]
        while True:
            if state.turns >= limits.max_turns:
                state.stop = "max_turns"
                return
            if state.cost_usd >= limits.max_cost_usd:
                state.stop = "cost_cap"
                return
            state.turns += 1
            resp = await self.client.messages.create(
                model=self.model, max_tokens=16000, system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=tool_defs, messages=messages, output_config={"effort": self.effort},
                cache_control={"type": "ephemeral"},
            )
            self._charge(resp.usage, state)
            text = "".join(b.text for b in resp.content if b.type == "text")
            state.log("model", turn=state.turns, stop_reason=resp.stop_reason, text=text[:4000],
                      usage=resp.usage.to_dict(), cost_usd=round(state.cost_usd, 4))
            if text:
                state.final_text = text
            messages.append({"role": "assistant", "content": resp.content})
            if resp.stop_reason == "refusal":
                state.stop, state.error = "error", f"refusal: {getattr(resp, 'stop_details', None)}"
                return
            if resp.stop_reason == "pause_turn":
                continue
            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                state.stop = "done" if resp.stop_reason == "end_turn" else resp.stop_reason
                return
            results = []
            for b in calls:
                out = await tools.call(b.name, dict(b.input or {}))
                blocks = [{"type": "text", "text": out.text or "(no output)"}]
                blocks += [{"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": d}} for d in out.images]
                results.append({"type": "tool_result", "tool_use_id": b.id, "content": blocks, "is_error": out.is_error})
            messages.append({"role": "user", "content": results})
            if state.stop == "max_tool_calls":
                return


AGENTS: dict[str, type[Agent]] = {"fake": FakeAgent, "claude": ClaudeAgent}


def make_agent(name: str) -> Agent:
    if name not in AGENTS:
        raise ValueError(f"unknown agent {name!r}; have {sorted(AGENTS)}")
    return AGENTS[name]()


def dump(obj) -> str:
    return json.dumps(obj, indent=1, default=str)
