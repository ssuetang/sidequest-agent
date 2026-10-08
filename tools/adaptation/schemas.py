"""Data contracts used by the Adaptation / Memory pipeline.

The team-wide shared schemas (UserRequest, PlaceCandidate, SideQuest, ...)
are still TBD. These are the minimal shapes `repair_sidequest` needs; once
the shared contracts land, swap these for imports from the shared module.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


@dataclass
class PlaceCandidate:
    """A real-world place, as produced by the Reality pipeline."""

    place_id: str
    name: str
    tags: list[str] = field(default_factory=list)
    indoor: bool = True
    lat: float | None = None
    lng: float | None = None
    rating: float | None = None
    open_now: bool = True
    # Rough per-person spend at this stop (entry, coffee, ...), same currency
    # as SideQuest.budget.
    est_cost: float = 0.0


@dataclass
class QuestStep:
    """One stop in a SideQuest, as produced by the Story pipeline."""

    step_id: str
    place: PlaceCandidate
    duration_min: int
    narrative: str = ""
    micro_tasks: list[str] = field(default_factory=list)
    theme_tags: list[str] = field(default_factory=list)
    # Higher = more important to the story. Lowest priority is dropped first.
    priority: int = 1
    optional: bool = False
    travel_min_from_prev: int = 0
    # Story label for this stop, e.g. "Chapter 2: The Manuscript".
    chapter: str = ""


@dataclass
class SideQuest:
    quest_id: str
    theme: str
    steps: list[QuestStep]
    total_time_min: int
    persona: str = ""
    budget: float | None = None
    # Longest walk the user accepts between two consecutive stops.
    max_walk_min: int | None = None
    # Bumped every time the quest is repaired.
    version: int = 1

    @property
    def total_cost(self) -> float:
        return sum(s.place.est_cost for s in self.steps)


class ChangeType(str, Enum):
    WEATHER = "weather"                      # e.g. rain -> outdoor stops invalid
    PLACE_UNAVAILABLE = "place_unavailable"  # closed, full, out of business
    EVENT_CANCELLED = "event_cancelled"      # the event at a stop was cancelled
    TIME_CHANGE = "time_change"              # running late / less time left
    BUDGET_CHANGE = "budget_change"          # budget went down (or up)
    WALK_LIMIT = "walk_limit"                # "I don't want to walk that far"
    USER_SKIP = "user_skip"                  # user doesn't want a stop


@dataclass
class RepairContext:
    """What changed, plus anything the repair needs to react to it."""

    change_type: ChangeType
    # PLACE_UNAVAILABLE: ids of places that can no longer be visited.
    unavailable_place_ids: list[str] = field(default_factory=list)
    # EVENT_CANCELLED: ids of steps whose event was cancelled.
    cancelled_step_ids: list[str] = field(default_factory=list)
    # USER_SKIP: ids of steps the user wants removed.
    skip_step_ids: list[str] = field(default_factory=list)
    # WEATHER: True when outdoor stops should be avoided.
    outdoor_ok: bool = True
    # TIME_CHANGE (or any change): minutes the user has left from now.
    remaining_time_min: int | None = None
    # BUDGET_CHANGE: the new total budget for the quest.
    new_budget: float | None = None
    # WALK_LIMIT: longest acceptable walk between consecutive stops.
    max_walk_min: int | None = None
    # Steps already done; repair never touches them.
    completed_step_ids: list[str] = field(default_factory=list)
    note: str = ""


class RepairActionType(str, Enum):
    REPLACED = "replaced"
    DROPPED = "dropped"


@dataclass
class RepairAction:
    action: RepairActionType
    step_id: str
    reason: str
    old_place_id: str | None = None
    new_place_id: str | None = None


@dataclass
class RepairResult:
    quest: SideQuest
    actions: list[RepairAction]
    # Required (non-optional) steps that had to be dropped with no substitute.
    unresolved: list[str]
    summary: str

    @property
    def changed(self) -> bool:
        return bool(self.actions)


# --- (de)serialization, used by the session store ---------------------------


def sidequest_to_dict(quest: SideQuest) -> dict[str, Any]:
    return asdict(quest)


def sidequest_from_dict(data: dict[str, Any]) -> SideQuest:
    steps = [
        QuestStep(**{**s, "place": PlaceCandidate(**s["place"])})
        for s in data["steps"]
    ]
    return SideQuest(**{**data, "steps": steps})


def place_from_dict(data: dict[str, Any]) -> PlaceCandidate:
    return PlaceCandidate(**data)
