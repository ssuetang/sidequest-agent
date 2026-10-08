"""Story / Experience API with Gemini tool-calling and a local fallback."""

import json
import os
import uuid
from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from tools.story.build_sidequest import (
    BUILD_SIDEQUEST_TOOL,
    SideQuest,
    build_sidequest,
    parse_sidequest,
    run_tool,
    search_events,
)

try:
    import litellm
except ImportError:  # The local fallback should work without cloud dependencies.
    litellm = None


router = APIRouter(prefix="/api/events", tags=["story"])
sessions: dict[str, list[dict[str, Any]]] = {}


class EventRequest(BaseModel):
    message: str = Field(min_length=1)
    theme: str = "curious observer"
    duration_minutes: int = Field(default=120, ge=30, le=720)
    places: list[str] = Field(default_factory=list)
    city: str | None = None
    budget_limit: float = Field(default=0, ge=0)
    include_events: bool = False
    session_id: str | None = None


class EventResponse(BaseModel):
    sidequest: SideQuest
    session_id: str
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    mode: str


def _model_sidequest(request: EventRequest) -> tuple[SideQuest, list[dict[str, Any]]]:
    if litellm is None or os.getenv("SIDEQUEST_USE_MODEL", "1") == "0":
        raise RuntimeError("model disabled")

    messages = [
        {
            "role": "system",
            "content": "You are the Story / Experience agent. Always call build_sidequest before answering.",
        },
        {
            "role": "user",
            "content": json.dumps({
                "request": request.message,
                "theme": request.theme,
                "duration_minutes": request.duration_minutes,
                "places": request.places,
                "budget_limit": request.budget_limit,
            }),
        },
    ]
    calls = []
    for _ in range(3):
        reply = litellm.completion(
            model=os.getenv("SIDEQUEST_MODEL", "vertex_ai/gemini-3.5-flash-lite"),
            vertex_location=os.getenv("VERTEX_LOCATION", "global"),
            messages=messages,
            tools=[BUILD_SIDEQUEST_TOOL],
            num_retries=3,
        ).choices[0].message
        messages.append(reply.model_dump())
        if not reply.tool_calls:
            break
        for call in reply.tool_calls:
            args = json.loads(call.function.arguments)
            result = run_tool(call.function.name, args)
            calls.append({"name": call.function.name, "args": args, "result": result})
            messages.append({"role": "tool", "tool_call_id": call.id, "content": result})
            return parse_sidequest(result), calls
    raise RuntimeError("model did not call build_sidequest")


@router.post("", response_model=EventResponse)
def create_event(request: EventRequest) -> EventResponse:
    session_id = request.session_id or str(uuid.uuid4())
    sessions.setdefault(session_id, []).append(request.model_dump())
    try:
        sidequest, tool_calls = _model_sidequest(request)
        mode = "gemini"
    except Exception:
        events = search_events(request.theme, request.city) if request.include_events else []
        sidequest = parse_sidequest(build_sidequest(request.theme, request.duration_minutes, request.places, request.budget_limit, events))
        tool_calls = [{"name": "build_sidequest", "args": {"theme": request.theme, "duration_minutes": request.duration_minutes, "places": request.places, "budget_limit": request.budget_limit, "events": events}, "result": sidequest.model_dump_json()}]
        mode = "local"
    return EventResponse(sidequest=sidequest, session_id=session_id, tool_calls=tool_calls, mode=mode)