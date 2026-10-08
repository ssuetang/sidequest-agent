"""B — Story / Experience: turn viable places into a playable SideQuest."""

import json
import os
from typing import Any

import requests
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from integrations.places import load_local_places
from tools.adaptation.repair import walk_minutes


load_dotenv()


class SideQuestStop(BaseModel):
    order: int = Field(ge=1)
    place: str = Field(min_length=1)
    minutes: int = Field(ge=1)
    travel_minutes: int = Field(default=0, ge=0)
    estimated_cost: float = Field(ge=0)
    prompt: str = Field(min_length=1)
    micro_tasks: list[str] = Field(min_length=1, max_length=3)
    event: str | None = None


class SideQuestChapter(BaseModel):
    order: int = Field(ge=1)
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    stops: list[SideQuestStop] = Field(min_length=1, max_length=4)


class SideQuest(BaseModel):
    title: str = Field(min_length=1)
    theme: str = Field(min_length=1)
    duration_minutes: int = Field(ge=30, le=720)
    budget_limit: float = Field(ge=0)
    estimated_cost: float = Field(ge=0)
    budget_status: str = Field(pattern="^(within budget|over budget|budget not set)$")
    opening: str = Field(min_length=1)
    chapters: list[SideQuestChapter] = Field(min_length=1, max_length=4)
    closing: str = Field(min_length=1)


BUILD_SIDEQUEST_TOOL = {
    "type": "function",
    "function": {
        "name": "build_sidequest",
        "description": "Turn viable places and optional events into a connected narrative SideQuest with chapters, stops, micro-tasks, timing, and budget.",
        "parameters": {
            "type": "object",
            "properties": {
                "theme": {"type": "string", "description": "The persona, mood, or lens for the experience."},
                "duration_minutes": {"type": "integer", "description": "Total available time in minutes, including travel between stops."},
                "places": {
                    "type": "array",
                    "description": "Viable places in visit order.",
                    "items": {"type": "string"},
                },
                "budget_limit": {"type": "number", "description": "Optional maximum spend in the user's currency."},
                "events": {"type": "array", "items": {"type": "string"}, "description": "Optional event names to weave into the route."},
            },
            "required": ["theme", "duration_minutes", "places"],
        },
    },
}


def build_sidequest(
    theme: str,
    duration_minutes: int,
    places: list[str],
    budget_limit: float = 0,
    events: list[str] | None = None,
) -> str:
    """Build and validate the complete B-owned SideQuest contract."""
    duration = max(30, min(int(duration_minutes), 720))
    clean_theme = theme.strip() or "curious observer"
    selected_places = _rank_places(clean_theme, places)[:4]
    if not selected_places:
        selected_places = ["A familiar street", "A quiet public space", "A place to pause"]

    records = {_place_key(record.candidate.name): record for record in load_local_places()}
    travel_minutes = _route_travel_minutes(selected_places, records)
    # Preserve at least one activity minute per stop. If the route itself cannot
    # fit, remove its last stop rather than silently exceeding the user's time.
    while len(selected_places) > 1 and sum(travel_minutes) > duration - len(selected_places):
        selected_places.pop()
        travel_minutes = _route_travel_minutes(selected_places, records)

    clean_events = [event.strip() for event in (events or []) if event.strip()][: len(selected_places)]
    activity_minutes = duration - sum(travel_minutes)
    base_minutes, remainder = divmod(activity_minutes, len(selected_places))
    chapters = []
    for index, place in enumerate(selected_places, start=1):
        event = clean_events[index - 1] if index <= len(clean_events) else None
        chapters.append({
            "order": index,
            "title": _chapter_title(index),
            "purpose": _chapter_purpose(index, clean_theme),
            "stops": [{
                "order": index,
                "place": place,
                "minutes": base_minutes + (1 if index <= remainder else 0),
                "travel_minutes": travel_minutes[index - 1],
                "estimated_cost": _estimate_cost(place, event, records),
                "prompt": _stop_prompt(index),
                "micro_tasks": _micro_tasks(index),
                "event": event,
            }],
        })
    estimated_cost = round(sum(stop["estimated_cost"] for chapter in chapters for stop in chapter["stops"]), 2)
    status = "budget not set" if budget_limit <= 0 else ("within budget" if estimated_cost <= budget_limit else "over budget")
    quest = {
        "title": f"The {clean_theme.title()} SideQuest",
        "theme": clean_theme,
        "duration_minutes": duration,
        "budget_limit": round(max(0, budget_limit), 2),
        "estimated_cost": estimated_cost,
        "budget_status": status,
        "opening": f"Follow the city as a {clean_theme}, turning ordinary places into evidence for your story.",
        "chapters": chapters,
        "closing": "Choose one detail from the route and turn it into the next sentence of your story.",
    }
    return SideQuest.model_validate(quest).model_dump_json()


def search_events(keyword: str, city: str | None = None) -> list[str]:
    """Return optional Ticketmaster event names when a key is configured."""
    api_key = os.getenv("TICKETMASTER_API_KEY")
    if not api_key or not keyword.strip():
        return []
    params = {"apikey": api_key, "keyword": keyword, "size": 5, "sort": "relevance,desc"}
    if city:
        params["city"] = city
    try:
        response = requests.get("https://app.ticketmaster.com/discovery/v2/events.json", params=params, timeout=8)
        response.raise_for_status()
        events = response.json().get("_embedded", {}).get("events", [])
    except (requests.RequestException, ValueError):
        return []
    return [event.get("name", "") for event in events if event.get("name")]


def parse_sidequest(value: str | dict[str, Any]) -> SideQuest:
    """Validate a tool result before it crosses the API boundary."""
    payload = json.loads(value) if isinstance(value, str) else value
    return SideQuest.model_validate(payload)


def _rank_places(theme: str, places: list[str]) -> list[str]:
    clean = [place.strip() for place in places if place.strip()]
    keywords = set(theme.lower().split())
    return sorted(clean, key=lambda place: (-sum(word in place.lower() for word in keywords), clean.index(place)))


def _chapter_title(index: int) -> str:
    return ["Research", "Inspiration", "The First Draft", "The Reveal"][(index - 1) % 4]


def _chapter_purpose(index: int, theme: str) -> str:
    return [
        f"Gather material like a {theme}.",
        "Find a detail that changes the direction of the story.",
        "Make something small from what you have noticed.",
        "Leave with a conclusion that belongs to you.",
    ][(index - 1) % 4]


def _stop_prompt(index: int) -> str:
    prompts = [
        "Spend one quiet minute noticing what announces itself before you enter.",
        "Find a detail that connects this place to the one before it.",
        "Look again from the position you would usually ignore.",
        "Write one sentence about what this route changed in you.",
    ]
    return prompts[(index - 1) % len(prompts)]


def _micro_tasks(index: int) -> list[str]:
    return [
        ["Pick one detail you would normally miss.", "Give the detail a working title."],
        ["Find something that does not fit the scene.", "Describe it without naming it."],
        ["Make a six-word observation.", "Borrow a texture or color for your story."],
        ["Choose the day's strongest image.", "Write its final line."],
    ][(index - 1) % 4]


def _place_key(name: str) -> str:
    return " ".join(name.lower().split())


def _route_travel_minutes(places, records) -> list[int]:
    travel = [0]
    for previous_name, current_name in zip(places, places[1:]):
        previous = records.get(_place_key(previous_name))
        current = records.get(_place_key(current_name))
        minutes = (walk_minutes(previous.candidate, current.candidate)
                   if previous and current else None)
        travel.append(minutes or 0)
    return travel


def _estimate_cost(place: str, event: str | None, records=None) -> float:
    """Prefer provider/local place pricing, then use transparent fallbacks."""
    text = f"{place} {event or ''}".lower()
    if event:
        return 20.0
    record = (records or {}).get(_place_key(place))
    if record is not None:
        return float(record.candidate.est_cost)
    if any(word in text for word in ("cafe", "coffee", "restaurant")):
        return 8.0
    if any(word in text for word in ("gallery", "museum", "cinema")):
        return 15.0
    if any(word in text for word in ("bookstore", "bookshop", "shop")):
        return 10.0
    return 0.0


def run_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a model-requested Story tool without allowing bad calls to crash the API."""
    if name != "build_sidequest":
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        return build_sidequest(**args)
    except (KeyError, TypeError, ValueError) as error:
        return json.dumps({"error": f"Invalid build_sidequest arguments: {error}"})
