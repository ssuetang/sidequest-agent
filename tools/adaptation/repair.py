"""`repair_sidequest` — the Adaptation pipeline's original tool.

Given an active SideQuest and what changed (rain, a closed venue, a smaller
budget, ...), repair only the affected stops and keep everything else —
theme, persona, chapter structure, narrative — intact. The whole trip is
never regenerated.

Strategy, in order:
  1. Merge all incoming RepairContexts into one set of constraints.
  2. Mark steps that are broken under those constraints (completed steps are
     frozen). USER_SKIP steps are dropped; every other broken step is
     replaced with the best on-theme candidate, or dropped if none fits.
  3. Enforce the budget: swap the priciest stops for cheaper on-theme ones,
     then drop optional stops.
  4. Enforce the remaining time: drop lowest-priority stops, optional first.

Required (non-optional) stops that end up dropped are reported in
`RepairResult.unresolved` so the orchestrator can tell the user.

The function is pure: the input quest is never mutated.
"""

from __future__ import annotations

import copy
import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace

from tools.adaptation.schemas import (
    ChangeType,
    PlaceCandidate,
    QuestStep,
    RepairAction,
    RepairActionType,
    RepairContext,
    RepairResult,
    SideQuest,
)

# Average walking speed and a street-grid detour factor over straight-line
# distance, used to estimate walk time between stops.
WALK_KM_PER_MIN = 5.0 / 60
DETOUR_FACTOR = 1.25

# Optional hook to fetch more candidates for a specific broken step, e.g. a
# fresh `match_theme` call from the Reality pipeline. Failures are swallowed.
CandidateProvider = Callable[[QuestStep, "Constraints"], Iterable[PlaceCandidate]]


@dataclass
class Constraints:
    """All RepairContexts collapsed into one view."""

    outdoor_ok: bool = True
    unavailable_place_ids: set[str] = field(default_factory=set)
    cancelled_step_ids: set[str] = field(default_factory=set)
    skip_step_ids: set[str] = field(default_factory=set)
    completed_step_ids: set[str] = field(default_factory=set)
    remaining_time_min: int | None = None
    budget: float | None = None
    max_walk_min: int | None = None
    notes: list[str] = field(default_factory=list)


def merge_contexts(quest: SideQuest, changes: Sequence[RepairContext]) -> Constraints:
    c = Constraints(budget=quest.budget, max_walk_min=quest.max_walk_min)
    for ctx in changes:
        c.outdoor_ok = c.outdoor_ok and ctx.outdoor_ok
        c.unavailable_place_ids.update(ctx.unavailable_place_ids)
        c.cancelled_step_ids.update(ctx.cancelled_step_ids)
        c.skip_step_ids.update(ctx.skip_step_ids)
        c.completed_step_ids.update(ctx.completed_step_ids)
        # For scalar limits the latest message wins.
        if ctx.remaining_time_min is not None:
            c.remaining_time_min = ctx.remaining_time_min
        if ctx.new_budget is not None:
            c.budget = ctx.new_budget
        if ctx.max_walk_min is not None:
            c.max_walk_min = ctx.max_walk_min
        if ctx.note:
            c.notes.append(ctx.note)
    return c


def walk_minutes(a: PlaceCandidate, b: PlaceCandidate) -> int | None:
    """Estimated walking minutes between two places; None if coords missing."""
    if None in (a.lat, a.lng, b.lat, b.lng):
        return None
    lat1, lng1, lat2, lng2 = map(math.radians, (a.lat, a.lng, b.lat, b.lng))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    )
    km = 2 * 6371.0 * math.asin(math.sqrt(h))
    return round(km * DETOUR_FACTOR / WALK_KM_PER_MIN)


def _leg_minutes(prev: QuestStep | None, place: PlaceCandidate, fallback: int) -> int:
    if prev is None:
        return 0
    est = walk_minutes(prev.place, place)
    return fallback if est is None else est


def _break_reason(
    quest: SideQuest, idx: int, c: Constraints
) -> str | None:
    """Why step `idx` can no longer happen, or None if it is fine."""
    step = quest.steps[idx]
    if step.step_id in c.completed_step_ids:
        return None
    if step.step_id in c.cancelled_step_ids:
        return "event cancelled"
    if step.place.place_id in c.unavailable_place_ids:
        return "venue unavailable"
    if not step.place.open_now:
        return "venue closed"
    if not c.outdoor_ok and not step.place.indoor:
        return "outdoor stop in bad weather"
    if c.max_walk_min is not None and idx > 0:
        leg = _leg_minutes(quest.steps[idx - 1], step.place, step.travel_min_from_prev)
        if leg > c.max_walk_min:
            return f"{leg} min walk exceeds the {c.max_walk_min} min limit"
    return None


def _theme_overlap(step: QuestStep, cand: PlaceCandidate) -> int:
    wanted = {t.lower() for t in step.theme_tags}
    return len(wanted & {t.lower() for t in cand.tags})


def _find_replacement(
    quest: SideQuest,
    idx: int,
    pool: Sequence[PlaceCandidate],
    c: Constraints,
    *,
    max_cost: float | None = None,
) -> PlaceCandidate | None:
    """Best on-theme candidate that can stand in for step `idx`."""
    step = quest.steps[idx]
    prev = quest.steps[idx - 1] if idx > 0 else None
    nxt = quest.steps[idx + 1] if idx + 1 < len(quest.steps) else None
    in_use = {s.place.place_id for s in quest.steps}

    best: tuple[float, PlaceCandidate] | None = None
    for cand in pool:
        if cand.place_id in in_use or cand.place_id in c.unavailable_place_ids:
            continue
        if not cand.open_now or (not c.outdoor_ok and not cand.indoor):
            continue
        if max_cost is not None and cand.est_cost > max_cost:
            continue
        # Keep the persona: a replacement must share at least one theme tag.
        overlap = _theme_overlap(step, cand)
        if step.theme_tags and overlap == 0:
            continue

        legs = [m for m in (
            walk_minutes(prev.place, cand) if prev else None,
            walk_minutes(cand, nxt.place) if nxt else None,
        ) if m is not None]
        if c.max_walk_min is not None and any(m > c.max_walk_min for m in legs):
            continue

        score = (
            3.0 * overlap
            + 0.5 * (cand.rating or 0.0)
            - 0.05 * sum(legs)
            - 0.01 * cand.est_cost
        )
        if best is None or score > best[0]:
            best = (score, cand)
    return best[1] if best else None


def _swap_place(step: QuestStep, new: PlaceCandidate, travel: int) -> QuestStep:
    """Same chapter, same story beat — new venue."""
    old_name = step.place.name

    def rename(text: str) -> str:
        return text.replace(old_name, new.name) if old_name else text

    return replace(
        step,
        place=new,
        narrative=rename(step.narrative),
        micro_tasks=[rename(t) for t in step.micro_tasks],
        travel_min_from_prev=travel,
    )


def _total_time(steps: Sequence[QuestStep]) -> int:
    return sum(s.duration_min + s.travel_min_from_prev for s in steps)


def _drop_order(steps: Sequence[QuestStep], c: Constraints) -> list[QuestStep]:
    """Candidates for dropping: optional first, then lowest priority, then latest."""
    droppable = [s for s in steps if s.step_id not in c.completed_step_ids]
    return sorted(
        droppable,
        key=lambda s: (not s.optional, s.priority, -steps.index(s)),
    )


def _recompute_legs(steps: list[QuestStep]) -> None:
    for i, step in enumerate(steps):
        prev = steps[i - 1] if i > 0 else None
        step.travel_min_from_prev = _leg_minutes(prev, step.place, step.travel_min_from_prev)


def repair_sidequest(
    quest: SideQuest,
    changes: RepairContext | Sequence[RepairContext],
    candidates: Iterable[PlaceCandidate] = (),
    *,
    candidate_provider: CandidateProvider | None = None,
) -> RepairResult:
    """Repair `quest` for `changes`, replacing only the affected stops.

    Args:
        quest: the active SideQuest. Not mutated.
        changes: one or more RepairContexts (e.g. rain + a closed venue).
        candidates: spare PlaceCandidates to draw replacements from, usually
            the leftovers from the original `match_theme` call.
        candidate_provider: optional callback for fetching extra candidates
            for one broken step. Exceptions it raises are ignored.
    """
    if isinstance(changes, RepairContext):
        changes = [changes]
    c = merge_contexts(quest, changes)

    new = copy.deepcopy(quest)
    new.budget = c.budget
    new.max_walk_min = c.max_walk_min
    pool = list(candidates)
    actions: list[RepairAction] = []
    unresolved: list[str] = []

    def drop(step: QuestStep, reason: str) -> None:
        new.steps.remove(step)
        actions.append(RepairAction(
            RepairActionType.DROPPED, step.step_id, reason,
            old_place_id=step.place.place_id,
        ))
        if not step.optional and step.step_id not in c.skip_step_ids:
            unresolved.append(step.step_id)

    # 1. Explicit skips.
    for step in [s for s in new.steps if s.step_id in c.skip_step_ids]:
        if step.step_id not in c.completed_step_ids:
            drop(step, "user asked to skip")

    # 2. Replace (or drop) broken steps, one at a time, left to right, so each
    #    replacement sees the already-repaired previous stop.
    i = 0
    while i < len(new.steps):
        reason = _break_reason(new, i, c)
        if reason is None:
            i += 1
            continue
        step = new.steps[i]
        step_pool = pool
        if candidate_provider is not None:
            try:
                step_pool = pool + list(candidate_provider(step, c))
            except Exception as exc:  # provider is best-effort
                c.notes.append(f"candidate lookup failed for {step.step_id}: {exc}")
        # Fit the budget if possible, but never get pricier than the stop we're
        # replacing — step 3 deals with an already-blown budget.
        remaining = None if c.budget is None else max(
            c.budget - new.total_cost + step.place.est_cost, step.place.est_cost,
        )
        cand = _find_replacement(new, i, step_pool, c, max_cost=remaining)
        if cand is None:
            drop(step, f"{reason}; no on-theme replacement found")
            continue  # same index now points at the next step
        prev = new.steps[i - 1] if i > 0 else None
        new.steps[i] = _swap_place(step, cand, _leg_minutes(prev, cand, step.travel_min_from_prev))
        actions.append(RepairAction(
            RepairActionType.REPLACED, step.step_id, reason,
            old_place_id=step.place.place_id, new_place_id=cand.place_id,
        ))
        i += 1

    # 3. Budget: cheaper swaps first, then drop.
    if c.budget is not None and new.total_cost > c.budget:
        by_cost = sorted(
            (s for s in new.steps if s.step_id not in c.completed_step_ids),
            key=lambda s: -s.place.est_cost,
        )
        for step in by_cost:
            if new.total_cost <= c.budget:
                break
            idx = new.steps.index(step)
            over = new.total_cost - c.budget
            cand = _find_replacement(
                new, idx, pool, c, max_cost=step.place.est_cost - over,
            )
            if cand is not None:
                prev = new.steps[idx - 1] if idx > 0 else None
                new.steps[idx] = _swap_place(step, cand, _leg_minutes(prev, cand, step.travel_min_from_prev))
                actions.append(RepairAction(
                    RepairActionType.REPLACED, step.step_id, "over budget",
                    old_place_id=step.place.place_id, new_place_id=cand.place_id,
                ))
        for step in _drop_order(new.steps, c):
            if new.total_cost <= c.budget:
                break
            if step.place.est_cost > 0:
                drop(step, "over budget")

    # 4. Time left.
    _recompute_legs(new.steps)
    if c.remaining_time_min is not None:
        def time_left_needed() -> int:
            return _total_time([s for s in new.steps if s.step_id not in c.completed_step_ids])

        for step in _drop_order(new.steps, c):
            if time_left_needed() <= c.remaining_time_min or len(new.steps) <= 1:
                break
            drop(step, "not enough time left")
            _recompute_legs(new.steps)

    new.total_time_min = _total_time(new.steps)
    if actions:
        new.version = quest.version + 1
    return RepairResult(
        quest=new,
        actions=actions,
        unresolved=unresolved,
        summary=_summarize(quest, new, actions, unresolved, c),
    )


def _summarize(
    old: SideQuest,
    new: SideQuest,
    actions: Sequence[RepairAction],
    unresolved: Sequence[str],
    c: Constraints,
) -> str:
    if not actions:
        return f"No changes needed — your {new.theme} SideQuest still works as planned."
    names = {s.place.place_id: s.place.name for s in old.steps}
    names.update({p.place_id: p.name for p in (s.place for s in new.steps)})
    lines = []
    for a in actions:
        old_name = names.get(a.old_place_id or "", a.old_place_id)
        if a.action is RepairActionType.REPLACED:
            lines.append(f"- Swapped {old_name} → {names.get(a.new_place_id or '', a.new_place_id)} ({a.reason}).")
        else:
            lines.append(f"- Dropped {old_name} ({a.reason}).")
    if unresolved:
        lines.append(f"- Couldn't find on-theme substitutes for: {', '.join(unresolved)}.")
    lines.extend(f"- Note: {n}" for n in c.notes)
    header = f"Updated your {new.theme} SideQuest (v{new.version}), kept everything else as is:"
    return "\n".join([header, *lines])
