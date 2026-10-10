"""Read-only analysis across timelines: lineage, cause chains, state hashes, yearly
checkpoints, metric comparison and the divergence point between two branches.

A fork shares its parent's history up to the snapshot it was forked from, so every
analysis walks a branch's *lineage*: the ancestors' events and snapshots up to each fork
point, then the branch's own. Nothing here mutates a world or the store.
"""

import json
from collections import deque
from typing import NamedTuple

from kronos_sim import models as m
from kronos_sim.queries import influence

from kronos_history.store import HistoryStore

# Bounds keep a trace or comparison cheap on long histories.
MAX_TRACE_EVENTS = 200
MAX_SERIES_POINTS = 240


class Segment(NamedTuple):
    """One branch's part of a lineage: its events and snapshots up to `through`
    (a sequence; None = everything so far)."""

    branch_id: str
    through: int | None


def lineage(store: HistoryStore, branch_id: str) -> list[Segment]:
    """Segments from the root timeline down to `branch_id`, oldest ancestor first."""
    segments = [Segment(branch_id, None)]
    seen = {branch_id}
    meta = store.branch(branch_id)
    while meta.parent_branch_id and meta.source_snapshot_id:
        parent = meta.parent_branch_id
        if parent in seen:  # Defensive: a cycle would never terminate.
            break
        seen.add(parent)
        through = store.snapshot(meta.source_snapshot_id).sequence
        segments.append(Segment(parent, through))
        meta = store.branch(parent)
    return list(reversed(segments))


def history(store: HistoryStore, branch_id: str) -> list[m.SimulationEvent]:
    """Every event in a branch's full history, ancestors included, in order."""
    return [e for seg in lineage(store, branch_id) for e in store.events_through(*seg)]


# --- cause chains --------------------------------------------------------------------


def trace(
    store: HistoryStore, event_id: str, direction: str = "back", depth: int = 5
) -> m.EventTrace:
    """Breadth-first walk of the cause chain from one event.

    `back` follows the event's causal_refs (what caused it); `forward` follows events
    that cite it (what it caused). Events from the same action are linked both ways as
    `same_action` siblings at the first step.
    """
    start = store.event(event_id)
    found: dict[str, m.SimulationEvent] = {start.id: start}
    edges: list[m.TraceEdge] = []
    truncated = False
    if start.action_id:
        for sibling in store.events_of_action(start.branch_id, start.action_id):
            if sibling.id != start.id and sibling.id not in found:
                found[sibling.id] = sibling
                edges.append(m.TraceEdge(from_id=start.id, to_id=sibling.id, kind="same_action"))
    frontier = deque([(start, 0)])
    while frontier:
        event, level = frontier.popleft()
        if level >= depth:
            continue
        if direction == "back":
            steps = []
            for ref in event.causal_refs:
                try:
                    steps.append((store.event(ref), event.id))  # event cites ref
                except KeyError:
                    continue  # A ref to an event that was never saved; skip it.
            steps = [
                (nxt, m.TraceEdge(from_id=src, to_id=nxt.id, kind="cites")) for nxt, src in steps
            ]
        else:
            steps = [
                (nxt, m.TraceEdge(from_id=nxt.id, to_id=event.id, kind="cites"))
                for nxt in store.events_citing(event.branch_id, event.id)
            ]
        for nxt, edge in steps:
            edges.append(edge)
            if nxt.id in found:
                continue
            if len(found) >= MAX_TRACE_EVENTS:
                truncated = True
                continue
            found[nxt.id] = nxt
            frontier.append((nxt, level + 1))
    return m.EventTrace(
        event_id=event_id,
        direction=direction,
        events=list(found.values()),
        edges=edges,
        truncated=truncated,
    )


# --- determinism and checkpoints -----------------------------------------------------


def hashes(store: HistoryStore, branch_id: str) -> list[m.TickHash]:
    """The world hash recorded at the end of every day, across the branch's lineage."""
    out = []
    for seg in lineage(store, branch_id):
        for event in store.list_events_of_types(seg.branch_id, ("tick_completed",)):
            if seg.through is not None and event.sequence > seg.through:
                continue
            out.append(
                m.TickHash(
                    tick=event.tick,
                    sequence=event.sequence,
                    branch_id=seg.branch_id,
                    state_hash=event.payload.state_hash,
                )
            )
    return out


def checkpoints(store: HistoryStore, branch_id: str, ticks_per_year: int) -> list[m.Checkpoint]:
    """The last snapshot of each simulated year on this branch (year 0 = its start)."""
    last: dict[int, m.SnapshotMetadata] = {}
    for snap in store.list_snapshots(branch_id):
        last[snap.tick // ticks_per_year] = snap  # Sorted by sequence: the latest wins.
    return [
        m.Checkpoint(year=year, tick=snap.tick, snapshot=snap)
        for year, snap in sorted(last.items())
    ]


# --- metric comparison ---------------------------------------------------------------


def _gini_bps(values: list[int]) -> int:
    """Gini coefficient in basis points (0 = equal, 10000 = one holds everything)."""
    values = sorted(max(v, 0) for v in values)
    total = sum(values)
    if len(values) < 2 or total == 0:
        return 0
    weighted = sum((i + 1) * v for i, v in enumerate(values))
    n = len(values)
    return round((2 * weighted / (n * total) - (n + 1) / n) * 10000)


def metrics(state: m.WorldState) -> m.MetricPoint:
    bakeries = [b.prices["bread"] for b in state.buildings.values() if b.kind == "bakery"]
    money = [c.money for c in state.citizens.values()]
    return m.MetricPoint(
        tick=state.tick,
        bread_price=round(sum(bakeries) / len(bakeries)) if bakeries else None,
        gini_bps=_gini_bps(money),
        population=len(state.citizens),
        total_money=sum(money) + sum(b.cash for b in state.buildings.values()),
        top_influence_bps=max(
            (influence(state, cid).influence for cid in state.citizens), default=0
        ),
    )


def series(store: HistoryStore, branch_id: str, stride: int = 1) -> m.BranchSeries:
    """One metric point per day across the lineage (the day's last snapshot), every
    `stride` days, capped at MAX_SERIES_POINTS by widening the stride."""
    by_tick: dict[int, str] = {}
    for seg in lineage(store, branch_id):
        for snap in store.list_snapshots(seg.branch_id):
            if seg.through is None or snap.sequence <= seg.through:
                by_tick[snap.tick] = snap.id  # A later segment overrides shared days.
    ticks = sorted(by_tick)
    stride = max(stride, -(-len(ticks) // MAX_SERIES_POINTS), 1)
    chosen = ticks[::stride]
    if ticks and chosen[-1] != ticks[-1]:
        chosen.append(ticks[-1])  # Always end on the latest day.
    meta = store.branch(branch_id)
    return m.BranchSeries(
        branch_id=branch_id,
        name=meta.name,
        points=[metrics(store.restore(by_tick[t])) for t in chosen],
    )


def compare(store: HistoryStore, branch_ids: list[str], stride: int = 1) -> m.BranchComparison:
    return m.BranchComparison(branches=[series(store, b, stride) for b in branch_ids])


# --- divergence ----------------------------------------------------------------------


def _signature(event: m.SimulationEvent) -> str:
    """What a decision did, without IDs that differ between timelines by construction."""
    payload = event.payload.model_dump(mode="json")
    return json.dumps([event.tick, event.actor_id, event.type, payload], sort_keys=True)


def divergence(store: HistoryStore, a: str, b: str, chain_depth: int = 3) -> m.Divergence:
    """The first decision (an event from a player or citizen action) that differs between
    two timelines after their shared history, and the forward cause chain of each."""
    events_a, events_b = history(store, a), history(store, b)
    shared = 0
    for left, right in zip(events_a, events_b, strict=False):
        if left.id != right.id:
            break
        shared += 1
    common_tick = events_a[shared - 1].tick if shared else 0
    common_sequence = events_a[shared - 1].sequence if shared else 0
    decisions_a = [e for e in events_a[shared:] if e.action_id]
    decisions_b = [e for e in events_b[shared:] if e.action_id]
    first_a = first_b = None
    for index in range(max(len(decisions_a), len(decisions_b))):
        left = decisions_a[index] if index < len(decisions_a) else None
        right = decisions_b[index] if index < len(decisions_b) else None
        if left is None or right is None or _signature(left) != _signature(right):
            first_a, first_b = left, right
            break

    def chain(event):
        if event is None:
            return []
        return trace(store, event.id, "forward", chain_depth).events[1:]

    ticks = [e.tick for e in (first_a, first_b) if e is not None]
    return m.Divergence(
        a=a,
        b=b,
        common_sequence=common_sequence,
        common_tick=common_tick,
        tick=min(ticks) if ticks else None,
        decision_a=first_a,
        decision_b=first_b,
        chain_a=chain(first_a),
        chain_b=chain(first_b),
    )
