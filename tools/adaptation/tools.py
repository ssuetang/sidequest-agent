"""Gemini-callable tools for the Adaptation / Memory pipeline.

Tools exposed to the model:
    repair_sidequest      (original) fix only the stops affected by a change
    get_weather           (external API) Open-Meteo conditions near a stop
    get_current_sidequest (memory) the active SideQuest for this session

Wiring (see server/tools.py, which merges every pipeline's tools):

    from tools.adaptation.tools import TOOLS, TOOL_FUNCTIONS, run_tool, start_session

    # after build_sidequest produced a quest:
    start_session(session_id, quest, spare_candidates)

    # TOOLS is in the OpenAI/LiteLLM format the starter passes to
    # litellm.completion(tools=...); run_tool returns a dict the harness
    # json.dumps into the tool message.

`session_id` is injected by the server, never chosen by the model. Every
tool returns a JSON-serializable dict and never raises: failures come back
as {"ok": False, "error": ..., "fix": ...} so the model knows what to do.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from dataclasses import asdict
from typing import Any

from tools.adaptation.memory import InMemorySessionStore, SessionStore, SessionState
from tools.adaptation.repair import CandidateProvider, repair_sidequest as _repair
from tools.adaptation.schemas import (
    ChangeType,
    PlaceCandidate,
    QuestStep,
    RepairActionType,
    RepairContext,
    SideQuest,
)
from integrations import weather as weather_api

_store: SessionStore = InMemorySessionStore()
_candidate_provider: CandidateProvider | None = None


def configure(
    store: SessionStore | None = None,
    candidate_provider: CandidateProvider | None = None,
) -> None:
    """Swap the session store (e.g. JsonFileSessionStore) or plug in a live
    candidate lookup from the Reality pipeline (e.g. a match_theme call)."""
    global _store, _candidate_provider
    if store is not None:
        _store = store
    _candidate_provider = candidate_provider


def start_session(
    session_id: str, quest: SideQuest, candidates: Iterable[PlaceCandidate] = ()
) -> None:
    """Remember a freshly built SideQuest (called by the orchestrator, not the model)."""
    _store.save(SessionState(session_id=session_id, quest=quest, candidates=list(candidates)))


def mark_stop_completed(session_id: str, step_id: str) -> None:
    """Freeze a stop the user already visited so repairs never touch it."""
    state = _store.get(session_id)
    if state:
        state.mark_completed(step_id)
        _store.save(state)


def get_session(session_id: str) -> SessionState | None:
    return _store.get(session_id)


def clear_session(session_id: str) -> None:
    """Forget the session's SideQuest (the /clear endpoint calls this)."""
    _store.delete(session_id)


def undo_last_repair(session_id: str) -> dict[str, Any]:
    """Go back to the previous version of the SideQuest (the UI's undo button)."""
    state = _store.get(session_id)
    if state is None:
        return _error(*_NO_QUEST)
    if not state.revert():
        return _error("There is no earlier version to go back to.", "Nothing to undo.")
    _store.save(state)
    return get_current_sidequest(session_id)


# --- helpers ----------------------------------------------------------------


def _error(error: str, fix: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "error": error, "fix": fix, **extra}


_NO_QUEST = (
    "There is no active SideQuest in this session yet.",
    "Plan one first (build_sidequest), then call this tool again.",
)


def _stop_view(step: QuestStep, completed: set[str] = frozenset()) -> dict[str, Any]:
    p = step.place
    return {
        "step_id": step.step_id,
        "chapter": step.chapter,
        "place": p.name,
        "indoor": p.indoor,
        "duration_min": step.duration_min,
        "walk_min_from_prev": step.travel_min_from_prev,
        "est_cost": p.est_cost,
        "optional": step.optional,
        "completed": step.step_id in completed,
        "narrative": step.narrative,
        "micro_tasks": step.micro_tasks,
    }


def _quest_view(quest: SideQuest, completed: Iterable[str] = ()) -> dict[str, Any]:
    done = set(completed)
    return {
        "theme": quest.theme,
        "persona": quest.persona,
        "version": quest.version,
        "budget": quest.budget,
        "total_cost": quest.total_cost,
        "max_walk_min": quest.max_walk_min,
        "total_time_min": quest.total_time_min,
        "stops": [_stop_view(s, done) for s in quest.steps],
    }


def _stops_hint(quest: SideQuest) -> str:
    return "; ".join(f"{s.step_id} = {s.place.name}" + (f" ({s.chapter})" if s.chapter else "")
                     for s in quest.steps)


def _resolve_stop(ref: str, quest: SideQuest) -> list[QuestStep]:
    """Match a model-supplied stop reference to steps, most specific rule first."""
    r = ref.strip().lower()
    if not r:
        return []
    rules: list[Callable[[QuestStep], bool]] = [
        lambda s: r == s.step_id.lower(),
        lambda s: r == s.place.name.lower() or r == s.place.place_id.lower(),
        lambda s: bool(s.chapter) and r == s.chapter.lower(),
        lambda s: r in s.place.name.lower() or s.place.name.lower() in r,
        lambda s: bool(s.chapter) and r in s.chapter.lower(),
        # "the gallery" -> a stop tagged "gallery"
        lambda s: bool(set(re.findall(r"[a-z]+", r)) & {t.lower() for t in s.place.tags}),
    ]
    for rule in rules:
        hits = [s for s in quest.steps if rule(s)]
        if hits:
            return hits
    return []


def _resolve_all(refs: Any, quest: SideQuest, arg: str) -> tuple[list[QuestStep], dict | None]:
    if refs is None:
        return [], None
    if isinstance(refs, str):
        refs = [refs]
    if not isinstance(refs, (list, tuple)):
        return [], _error(f"`{arg}` must be a list of stop names.",
                          f'Pass e.g. {arg}=["{quest.steps[0].place.name}"].')
    out: list[QuestStep] = []
    for ref in refs:
        hits = _resolve_stop(str(ref), quest)
        if not hits:
            return [], _error(
                f"`{arg}`: no stop in the current SideQuest matches '{ref}'.",
                f"Use one of these names or step ids: {_stops_hint(quest)}. "
                "If the user means a place that isn't in the plan, no repair is needed.",
            )
        if len(hits) > 1:
            return [], _error(
                f"`{arg}`: '{ref}' matches several stops: {', '.join(s.place.name for s in hits)}.",
                "Ask the user which one they mean, then retry with its exact name or step id.",
            )
        out.append(hits[0])
    return out, None


def _number(value: Any, arg: str, *, minimum: float) -> tuple[float | None, dict | None]:
    if value is None:
        return None, None
    try:
        num = float(str(value).replace("$", "").strip())
    except ValueError:
        return None, _error(f"`{arg}` must be a number, got {value!r}.",
                            f"Retry with a plain number, e.g. {arg}=30.")
    if num < minimum:
        return None, _error(f"`{arg}` must be at least {minimum:g}, got {num:g}.",
                            "Confirm the value with the user and retry.")
    return num, None


# --- tool: repair_sidequest -------------------------------------------------


def repair_sidequest(
    session_id: str,
    unavailable_stops: list[str] | None = None,
    cancelled_stops: list[str] | None = None,
    skip_stops: list[str] | None = None,
    bad_weather: bool = False,
    new_budget: float | None = None,
    max_walk_minutes: int | None = None,
    minutes_left: int | None = None,
) -> dict[str, Any]:
    state = _store.get(session_id)
    if state is None:
        return _error(*_NO_QUEST)
    quest = state.quest

    changes: list[RepairContext] = []
    resolved: dict[str, list[QuestStep]] = {}
    for arg, refs in (("unavailable_stops", unavailable_stops),
                      ("cancelled_stops", cancelled_stops),
                      ("skip_stops", skip_stops)):
        steps, err = _resolve_all(refs, quest, arg)
        if err:
            return err
        resolved[arg] = steps

    if resolved["unavailable_stops"]:
        changes.append(RepairContext(ChangeType.PLACE_UNAVAILABLE,
                                     unavailable_place_ids=[s.place.place_id for s in resolved["unavailable_stops"]]))
    if resolved["cancelled_stops"]:
        changes.append(RepairContext(ChangeType.EVENT_CANCELLED,
                                     cancelled_step_ids=[s.step_id for s in resolved["cancelled_stops"]]))
    if resolved["skip_stops"]:
        changes.append(RepairContext(ChangeType.USER_SKIP,
                                     skip_step_ids=[s.step_id for s in resolved["skip_stops"]]))
    if bad_weather is True or str(bad_weather).lower() == "true":
        changes.append(RepairContext(ChangeType.WEATHER, outdoor_ok=False))

    budget, err = _number(new_budget, "new_budget", minimum=0)
    if err:
        return err
    if budget is not None:
        changes.append(RepairContext(ChangeType.BUDGET_CHANGE, new_budget=budget))

    walk, err = _number(max_walk_minutes, "max_walk_minutes", minimum=1)
    if err:
        return err
    if walk is not None:
        changes.append(RepairContext(ChangeType.WALK_LIMIT, max_walk_min=round(walk)))

    left, err = _number(minutes_left, "minutes_left", minimum=1)
    if err:
        return err
    if left is not None:
        changes.append(RepairContext(ChangeType.TIME_CHANGE, remaining_time_min=round(left)))

    if not changes:
        return _error(
            "Nothing to repair: no change was given.",
            "Pass at least one of unavailable_stops, cancelled_stops, skip_stops, "
            "bad_weather, new_budget, max_walk_minutes or minutes_left. If the user "
            "only asked about the plan, call get_current_sidequest instead.",
        )
    changes[0].completed_step_ids.extend(state.completed_step_ids)

    try:
        result = _repair(quest, changes, state.candidates, candidate_provider=_candidate_provider)
    except Exception as exc:  # keep the old plan rather than crash the chat
        return _error(f"Repair failed unexpectedly: {exc}",
                      "The current SideQuest is unchanged. Tell the user and offer to try again.")

    if result.changed:
        state.commit(result.quest, result.actions)
        _store.save(state)

    old_names = {s.step_id: s for s in quest.steps}
    new_names = {s.step_id: s for s in result.quest.steps}
    actions = []
    for a in result.actions:
        old = old_names.get(a.step_id)
        new = new_names.get(a.step_id) if a.action is RepairActionType.REPLACED else None
        actions.append({
            "action": a.action.value,
            "step_id": a.step_id,
            "chapter": old.chapter if old else "",
            "old_place": old.place.name if old else a.old_place_id,
            "new_place": new.place.name if new else None,
            "reason": a.reason,
        })

    out: dict[str, Any] = {
        "ok": True,
        "changed": result.changed,
        "summary": result.summary,
        "actions": actions,
        "sidequest": _quest_view(result.quest, state.completed_step_ids),
    }
    if result.unresolved:
        lost = [old_names[sid] for sid in result.unresolved if sid in old_names]
        out["unresolved"] = [{"step_id": s.step_id, "chapter": s.chapter, "place": s.place.name}
                             for s in lost]
        out["fix"] = (
            "These required chapters were dropped because no on-theme substitute fits the "
            "new constraints. Tell the user, and offer to search for more places "
            "(match_theme) or relax a constraint (budget, walking, time)."
        )
    if budget is not None and result.quest.total_cost > budget:
        out["warning"] = (f"Still over budget ({result.quest.total_cost:g} > {budget:g}) "
                          "because only completed stops remain to cut. Tell the user.")
    return out


# --- tool: get_weather ------------------------------------------------------


def get_weather(
    session_id: str,
    location: str | None = None,
    stop: str | None = None,
    latitude: float | None = None,
    longitude: float | None = None,
) -> dict[str, Any]:
    state = _store.get(session_id)
    place = None
    if latitude is not None and longitude is not None:
        place = {"latitude": latitude, "longitude": longitude, "label": "given coordinates"}
    elif location:
        geo = weather_api.geocode(location)
        if not geo.ok:
            return _error(
                f"Couldn't find '{location}': {geo.error}",
                "Retry with a well-known city name (e.g. 'New York'), or pass latitude and longitude.",
            )
        place = {"latitude": geo.lat, "longitude": geo.lng, "label": geo.name}
    elif state is not None:
        quest = state.quest
        if stop:
            steps, err = _resolve_all([stop], quest, "stop")
            if err:
                return err
            candidates = steps
        else:
            done = set(state.completed_step_ids)
            candidates = [s for s in quest.steps if s.step_id not in done]
        anchor = next((s for s in candidates if s.place.lat is not None and s.place.lng is not None), None)
        if anchor:
            place = {"latitude": anchor.place.lat, "longitude": anchor.place.lng,
                     "label": anchor.place.name}
    if place is None:
        return _error(
            "No location to check the weather for.",
            "Pass `location` as a city name (e.g. 'New York'), or plan a SideQuest "
            "first so its stops can be used.",
        )

    report = weather_api.get_weather(place["latitude"], place["longitude"])
    if not report.ok:
        return _error(
            f"Weather service failed: {report.error}",
            "Ask the user what the weather is like. If they say it's raining, "
            "call repair_sidequest with bad_weather=true anyway.",
            location=place,
        )

    out = {"ok": True, "location": place, **{k: v for k, v in asdict(report).items()
                                                  if k not in ("ok", "error")}}
    if state is not None:
        done = set(state.completed_step_ids)
        outdoor = [s.place.name for s in state.quest.steps
                   if not s.place.indoor and s.step_id not in done]
        out["outdoor_stops"] = outdoor
        if report.bad_for_outdoor and outdoor:
            out["suggestion"] = ("Conditions are bad for being outside. Call repair_sidequest "
                                 "with bad_weather=true to move the outdoor stops indoors.")
        elif report.bad_for_outdoor:
            out["suggestion"] = "Bad weather, but every remaining stop is indoors — no repair needed."
        else:
            out["suggestion"] = "Weather is fine for the current plan."
    return out


# --- tool: get_current_sidequest --------------------------------------------


def get_current_sidequest(session_id: str) -> dict[str, Any]:
    state = _store.get(session_id)
    if state is None:
        return _error(*_NO_QUEST)
    return {
        "ok": True,
        "sidequest": _quest_view(state.quest, state.completed_step_ids),
        "earlier_versions": len(state.history),
        "recent_changes": state.repair_log[-10:],
    }


# --- registry ---------------------------------------------------------------

_STOP_LIST = {"type": "array", "items": {"type": "string"}}

TOOL_DECLARATIONS: list[dict[str, Any]] = [
    {
        "name": "repair_sidequest",
        "description": (
            "Repair the user's active SideQuest after something changed, replacing ONLY the "
            "affected stops with nearby places that keep the same theme, persona and chapter; "
            "everything else stays as planned. Use it when the user says a venue is closed, an "
            "event was cancelled, it's raining, the budget changed, they don't want to walk "
            "that far, they're short on time, or they want to skip a stop. Do NOT use it to "
            "plan a brand-new trip. Combine several changes in one call. Returns the revised "
            "SideQuest plus a list of what was swapped or dropped."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "unavailable_stops": {**_STOP_LIST, "description":
                    "Stops whose venue is closed, full or gone. Use the place name, a word "
                    "the user used for it (e.g. 'gallery'), or a step id like 's2'."},
                "cancelled_stops": {**_STOP_LIST, "description":
                    "Stops whose event (reading, show, tour) was cancelled."},
                "skip_stops": {**_STOP_LIST, "description":
                    "Stops the user doesn't want any more. These are removed, not replaced."},
                "bad_weather": {"type": "boolean", "description":
                    "true if it's raining/snowing/too hot or cold, so outdoor stops should be "
                    "moved indoors. Trust the user's report over the forecast."},
                "new_budget": {"type": "number", "description":
                    "The user's new total budget for the whole SideQuest, in dollars."},
                "max_walk_minutes": {"type": "integer", "description":
                    "Longest walk the user accepts between two stops, in minutes. If they "
                    "just say 'I don't want to walk that far', use 10."},
                "minutes_left": {"type": "integer", "description":
                    "How many minutes the user has left from now."},
            },
        },
    },
    {
        "name": "get_weather",
        "description": (
            "Get current weather and the rain chance for the next 3 hours (Open-Meteo API) "
            "near a stop of the active SideQuest, or for a named city. Use it when the "
            "user asks about the weather or mentions it might rain, before deciding whether "
            "to move outdoor stops inside. Returns condition, temperature, rain probability, "
            "bad_for_outdoor and which stops are outdoors."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string", "description":
                    "Optional city name, e.g. 'New York'. Use it when there's no SideQuest yet "
                    "or the user asks about somewhere else."},
                "stop": {"type": "string", "description":
                    "Optional stop name or step id to check. Defaults to the next upcoming stop."},
                "latitude": {"type": "number", "description":
                    "Optional latitude, only when there is no SideQuest or for another place."},
                "longitude": {"type": "number", "description":
                    "Optional longitude, paired with latitude."},
            },
        },
    },
    {
        "name": "get_current_sidequest",
        "description": (
            "Read the user's active SideQuest from session memory: theme, persona, budget and "
            "every stop with its chapter, place, walk time and cost, plus recent changes. Use "
            "it to answer questions about the current plan or to look up exact stop names "
            "before calling repair_sidequest."
        ),
        # No "parameters": Gemini rejects an OBJECT schema with empty properties.
    },
]

# The same declarations in the OpenAI/LiteLLM shape the starter harness uses.
TOOLS: list[dict[str, Any]] = [{"type": "function", "function": d} for d in TOOL_DECLARATIONS]

TOOL_FUNCTIONS: dict[str, Callable[..., dict[str, Any]]] = {
    "repair_sidequest": repair_sidequest,
    "get_weather": get_weather,
    "get_current_sidequest": get_current_sidequest,
}


def run_tool(name: str, args: dict[str, Any] | None, session_id: str) -> dict[str, Any]:
    """Dispatch a model function call. Never raises."""
    fn = TOOL_FUNCTIONS.get(name)
    if fn is None:
        return _error(f"Unknown tool '{name}'.", f"Use one of: {', '.join(TOOL_FUNCTIONS)}.")
    args = dict(args or {})
    args.pop("session_id", None)  # always the server's, never the model's
    allowed = {p for d in TOOL_DECLARATIONS if d["name"] == name
               for p in d.get("parameters", {}).get("properties", {})}
    unknown = sorted(set(args) - allowed)
    if unknown:
        return _error(f"Unknown argument(s) for {name}: {', '.join(unknown)}.",
                      f"Valid arguments: {', '.join(sorted(allowed)) or 'none'}.")
    try:
        return fn(session_id, **args)
    except Exception as exc:
        return _error(f"{name} failed: {exc}", "Tell the user something went wrong and try again.")
