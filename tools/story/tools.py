"""Gemini-callable tools owned by the Story / Experience pipeline.

build_sidequest turns match_theme's shortlist into a chaptered SideQuest. The
result is also handed to the Adaptation pipeline (start_session), so the plan
shows up in the side panel and repair_sidequest / get_weather work on it.
Story stops are plain place names; they are resolved against the curated
place data to get coordinates, indoor/outdoor, tags and cost, and the rest of
that neighborhood is kept as spare candidates for repairs.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from tools.adaptation import tools as adaptation_tools
from tools.adaptation.repair import walk_minutes
from tools.adaptation.schemas import PlaceCandidate, QuestStep, SideQuest as RepairableQuest
from tools.story.build_sidequest import BUILD_SIDEQUEST_TOOL, SideQuest, build_sidequest
from integrations.places import PlaceRecord, load_local_places

TOOLS = [BUILD_SIDEQUEST_TOOL]
TOOL_FUNCTIONS = {"build_sidequest": build_sidequest}
_ALLOWED_ARGS = set(BUILD_SIDEQUEST_TOOL["function"]["parameters"]["properties"])


def _error(error: str, fix: str) -> dict[str, Any]:
    return {"ok": False, "error": error, "fix": fix}


def _key(name: str) -> str:
    return " ".join(name.lower().split())


def _to_repairable(story: SideQuest) -> tuple[RepairableQuest, list[PlaceCandidate]]:
    """Convert Story's SideQuest into the shape repair_sidequest works on."""
    records: dict[str, PlaceRecord] = {_key(r.candidate.name): r for r in load_local_places()}
    stops = [(chapter, stop) for chapter in story.chapters for stop in chapter.stops]
    steps: list[QuestStep] = []
    neighborhoods: set[str] = set()
    for i, (chapter, stop) in enumerate(stops, start=1):
        record = records.get(_key(stop.place))
        if record:
            place = record.candidate
            neighborhoods.add(record.neighborhood)
        else:
            # Not in the curated data (e.g. a live Google result): keep the name, no coordinates.
            place = PlaceCandidate(place_id=f"story_{i}", name=stop.place, est_cost=stop.estimated_cost)
        prev = steps[-1].place if steps else None
        steps.append(QuestStep(
            step_id=f"s{i}",
            place=place,
            duration_min=stop.minutes,
            narrative=stop.prompt,
            micro_tasks=list(stop.micro_tasks),
            theme_tags=list(place.tags),
            # Earlier chapters carry the setup, so they are dropped last.
            priority=len(stops) - i + 1,
            travel_min_from_prev=(walk_minutes(prev, place) or 0) if prev else 0,
            chapter=f"Chapter {chapter.order}: {chapter.title}",
        ))
    used = {s.place.place_id for s in steps}
    spares = [r.candidate for r in records.values()
              if r.neighborhood in neighborhoods and r.candidate.place_id not in used]
    quest = RepairableQuest(
        quest_id=f"quest-{uuid.uuid4().hex[:8]}",
        theme=story.theme,
        persona=story.theme,
        steps=steps,
        total_time_min=story.duration_minutes,
        budget=story.budget_limit or None,
    )
    return quest, spares


def run_tool(name: str, args: dict[str, Any] | None, session_id: str) -> dict[str, Any]:
    """Run a Story tool call. Never raises."""
    if name not in TOOL_FUNCTIONS:
        return _error(f"Unknown Story tool {name!r}.", f"Use one of: {', '.join(TOOL_FUNCTIONS)}.")
    args = dict(args or {})
    unknown = sorted(set(args) - _ALLOWED_ARGS)
    if unknown:
        return _error(f"Unknown arguments for {name}: {unknown}.",
                      f"Use only: {', '.join(sorted(_ALLOWED_ARGS))}.")
    if not [p for p in args.get("places") or [] if str(p).strip()]:
        return _error("No places were given, so there is nothing real to build the SideQuest from.",
                      "Call match_theme first and pass the names of its places, in visit order.")
    try:
        story = SideQuest.model_validate_json(build_sidequest(**args))
    except (TypeError, ValueError) as exc:
        return _error(f"Invalid build_sidequest arguments: {exc}",
                      "Check theme (text), duration_minutes (integer), places (list of names) and retry.")
    quest, spares = _to_repairable(story)
    adaptation_tools.start_session(session_id, quest, spares)
    return {"ok": True, "sidequest": json.loads(story.model_dump_json()),
            "step_ids": {s.step_id: s.place.name for s in quest.steps},
            "note": "Saved as the active SideQuest; repair_sidequest and get_weather now work on it."}


def clear_session(session_id: str) -> None:
    del session_id  # the built quest lives in the Adaptation session store
