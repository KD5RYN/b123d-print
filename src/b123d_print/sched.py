"""Fair build slots: which waiting job runs next when a slot frees up (#71, #73).

One scheduler per server process, in front of every sandboxed job (mcp_server._run). It replaces a
single first-come queue, where one client with several long builds made every other client wait.

- **Slots:** at most `slots` jobs run at once (--max-builds), all clients together, as before.
- **Quick lane:** `reserved` of those slots only take quick jobs (measure, section, faces, ...), so
  a quick call never waits behind other clients' long builds. Quick jobs may use any free slot;
  long jobs never use a reserved one. At least one slot always stays open to long jobs.
- **Round-robin:** when a slot frees up, it goes to the waiting client with the fewest running
  jobs; ties go to the client served longest ago. Within one client, jobs start in the order they
  came (FIFO).
- **Per-client cap:** a client with `per_client` jobs running and waiting is refused at once
  (`Busy`), with a plain message, instead of queueing without end (re-submit storms).
- **Wait limit:** a job that waited `wait_limit` seconds for a slot is refused (`Waited`): its
  client has most likely given up by then, and starting it would only delay the others.

All state lives on the server's event loop (no locks): `slot()` is awaited there, and the job
itself runs in a thread inside the `async with`. A job's slot is released only when that thread
returns, so a cancelled call never frees a slot that a build still uses.
"""

from __future__ import annotations

import itertools
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

import anyio


class Busy(Exception):
    """The client already has its share of jobs running and waiting: refused, not queued."""


class Waited(Exception):
    """No slot came free within the wait limit."""


@dataclass(eq=False)
class _Waiter:
    client: str
    quick: bool
    seq: int
    event: anyio.Event = field(default_factory=anyio.Event)
    pool: str | None = None  # "reserved" or "general" once it has a slot


class FairScheduler:
    def __init__(self, slots: int, reserved: int = 0, per_client: int = 0):
        self.slots = max(1, int(slots))
        # never every slot: long jobs (builds, exports, checks) always keep at least one
        self.reserved = min(max(0, int(reserved)), self.slots - 1)
        self.per_client = max(0, int(per_client))  # running + waiting per client; 0 = no cap
        self.running: dict[str, int] = {}
        self.in_general = 0  # general slots in use (long jobs, and quick jobs that took one)
        self.in_reserved = 0  # reserved slots in use (quick jobs only)
        self.waiting: list[_Waiter] = []  # in arrival order
        self._served: dict[str, int] = {}  # client -> when it last got a slot (round-robin order)
        self._seq = itertools.count()
        self._tick = itertools.count(1)

    # --- what the server asks ------------------------------------------------------------------

    @property
    def general(self) -> int:
        return self.slots - self.reserved

    def load(self, client: str) -> int:
        """The client's jobs running and waiting."""
        return self.running.get(client, 0) + sum(w.client == client for w in self.waiting)

    def others_waiting(self, client: str) -> bool:
        return any(w.client != client for w in self.waiting)

    def idle(self) -> int:
        """General slots free right now (what a long job could start on at once)."""
        return self.general - self.in_general

    def room(self, client: str) -> int | None:
        """How many more jobs the client may have, or None without a cap."""
        return None if not self.per_client else max(0, self.per_client - self.load(client))

    def shares(self, client: str, want: int) -> int:
        """How many workers a check may split into now: `want` at most, the general slots free,
        the client's room under its cap, and 1 while another client waits (at least 1)."""
        n = min(want, self.general, max(1, self.idle()))
        room = self.room(client)
        if room is not None:
            n = min(n, room)
        if self.others_waiting(client):
            n = 1
        return max(1, n)

    def busy_message(self, client: str) -> str:
        n = self.load(client)
        return (f"server busy: you have {n} job{'s' if n != 1 else ''} running or queued on this shared server "
                f"(at most {self.per_client} per client); wait for one to finish, then try again")

    # --- taking a slot ----------------------------------------------------------------------------

    @asynccontextmanager
    async def slot(self, client: str, quick: bool = False, wait_limit: float | None = None):
        """Hold one slot for the body of the `async with`. Raises Busy (over the client's cap, at
        once) or Waited (no slot within `wait_limit` seconds)."""
        if self.per_client and self.load(client) >= self.per_client:
            raise Busy(self.busy_message(client))
        w = _Waiter(client, quick, next(self._seq))
        self.waiting.append(w)
        self._dispatch()
        started = time.monotonic()
        try:
            with anyio.move_on_after(wait_limit if wait_limit is not None else float("inf")):
                await w.event.wait()
        except BaseException:  # cancelled while waiting (or just after getting the slot)
            self._drop(w)
            raise
        if w.pool is None:
            self._drop(w)
            raise Waited(f"server busy: no build slot came free within {time.monotonic() - started:.0f} s "
                         "(other clients' builds are running); try again in a minute")
        try:
            yield w.pool
        finally:
            self._drop(w)

    def _drop(self, w: _Waiter) -> None:
        """Forget a waiter: still waiting -> out of the queue; holding a slot -> free it."""
        if w.pool == "done":
            return
        if w.pool is None:
            if w in self.waiting:
                self.waiting.remove(w)
            self._dispatch()  # it may have been the head of its client's line
            return
        if w.pool == "reserved":
            self.in_reserved -= 1
        else:
            self.in_general -= 1
        left = self.running.get(w.client, 0) - 1
        if left > 0:
            self.running[w.client] = left
        else:
            self.running.pop(w.client, None)
        w.pool = "done"  # a second _drop (body raised after release) must not free it twice
        self._dispatch()

    def _dispatch(self) -> None:
        """Hand free slots to waiters until none fits: reserved slots to quick jobs first (so the
        general slots stay for long ones), then general slots to anyone, fairly."""
        while self.waiting:
            if self.in_reserved < self.reserved and (w := self._pick(quick_only=True)):
                self._grant(w, "reserved")
            elif self.in_general < self.general and (w := self._pick(quick_only=False)):
                self._grant(w, "general")
            else:
                return

    def _pick(self, quick_only: bool) -> _Waiter | None:
        """The next waiter: per client its first (FIFO), across clients the one with the fewest
        running jobs, then the one served longest ago (round-robin), then arrival order."""
        heads: dict[str, _Waiter] = {}
        for w in self.waiting:  # arrival order, so the first seen is each client's head
            if (w.quick or not quick_only) and w.client not in heads:
                heads[w.client] = w
        if not heads:
            return None
        return min(heads.values(), key=lambda w: (self.running.get(w.client, 0), self._served.get(w.client, 0), w.seq))

    def _grant(self, w: _Waiter, pool: str) -> None:
        self.waiting.remove(w)
        w.pool = pool
        if pool == "reserved":
            self.in_reserved += 1
        else:
            self.in_general += 1
        self.running[w.client] = self.running.get(w.client, 0) + 1
        self._served[w.client] = next(self._tick)
        w.event.set()
