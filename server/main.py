"""Web server + agent harness, based on the gemini-web-tool-calling starter.

Changes from the starter:
- tools come from server/tools.py, which merges all three pipelines,
- run_agent() passes session_id through so tools can read/write the
  session's SideQuest (the model never sees or chooses it),
- malformed tool arguments are reported to the model instead of crashing,
- the system prompt tells the model which features aren't built yet,
- extra JSON endpoints for the UI's SideQuest panel (/api/...),
- /clear also forgets the session's SideQuest.

/chat keeps the starter's response shape: response, session_id, tool_calls.

Run from the repo root:  uv run app.py
"""

import json
import os
import uuid
from pathlib import Path

import litellm
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tools.adaptation import tools as adaptation_tools
from tools.adaptation.schemas import place_from_dict, sidequest_from_dict
from api.events import router as events_router
from server.tools import TOOLS, available_tools, clear_session, features, run_tool

# --- Config ---

MODEL = os.environ.get("SIDEQUEST_MODEL", "vertex_ai/gemini-3.5-flash-lite")
MAX_TOOL_ROUNDS = 8
DEMO_PATH = Path(__file__).resolve().parent.parent / "data" / "demo_sidequest.json"


def build_system_prompt() -> str:
    prompt = (
        "You are Day as Someone, an agent that turns the user's free time in a city into a "
        "SideQuest: a short, themed real-world itinerary told as chapters, experienced 'as "
        "someone' (a persona like a 1950s novelist or a 90s indie filmmaker).\n"
        "For a brand-new SideQuest, first call match_theme to find a diverse, explainable "
        "shortlist of real places in one supported NYC neighborhood. If the user has not "
        "chosen a neighborhood, ask them to choose Morningside Heights, Greenwich Village, "
        "Chinatown, or DUMBO. Do not invent places. Twenty ready-made personas are available: "
        "struggling novelist, urban detective, indie filmmaker, architecture apprentice, "
        "city naturalist, independent magazine editor, jazz age drifter, street photographer, "
        "hidden history archivist, thrift fashion scout, neighborhood food chronicler, "
        "waterfront poet, campus intellectual, avant garde theater actor, urban sketch artist, "
        "community radio producer, romantic city wanderer, industrial design student, museum "
        "time traveler, and midnight mystery writer. For any other persona, infer 3-6 "
        "desired_tags, optional avoid_tags, and a short story_tone from the match_theme schema; "
        "never invent tags outside its enum.\n"
    )
    if "build_sidequest" in available_tools():
        prompt += (
            "Then call build_sidequest with the persona as theme, the shortlisted place names "
            "in visit order, the user's available minutes, and their budget if given. If you "
            "don't know how much time they have, ask before building. When presenting the result, "
            "use each stop's exact minutes, travel_minutes and estimated_cost from the tool. The "
            "duration already includes travel; never invent or round walking times or prices.\n"
        )
    if "find_events" in available_tools():
        prompt += (
            "If the user wants a show, concert or something happening tonight, or the persona "
            "calls for one, call find_events for the neighborhood (hours_ahead = their free "
            "time) and pass one or two real event names to build_sidequest as events. Mention "
            "the event's time and venue. Never invent events; if find_events fails or finds "
            "nothing, build without events and say so.\n"
        )
    prompt += (
        "Once a SideQuest exists, keep it alive across the conversation:\n"
        "- When something changes (a venue is closed, an event is cancelled, it rains, the "
        "budget or time changes, the user doesn't want to walk that far, or wants to skip a "
        "stop), call repair_sidequest. Do not re-plan the whole trip. Keep the same persona "
        "and theme.\n"
        "- If the user mentions the weather or asks whether it'll rain, call get_weather first.\n"
        "- A SideQuest can be loaded outside the chat (e.g. the demo button). Before saying "
        "there is no plan, or to answer questions about it, call get_current_sidequest.\n"
        "- If a tool returns ok=false, follow its `fix` field: retry with corrected arguments "
        "or ask the user the question it suggests.\n"
        "After a repair, tell the user briefly which chapters changed and why, in the "
        "persona's voice. Keep answers short."
    )
    missing = [f for f in features() if not f["available"]]
    if missing:
        prompt += "\n\nNot available yet in this build:\n" + "\n".join(
            f"- {f['label']}: {f['description']}" for f in missing
        )
        prompt += (
            "\nIf the user asks for one of these, say it's coming soon and suggest loading "
            "the demo SideQuest (button in the side panel) to try repairs. Never invent a plan."
        )
    return prompt


# --- The Harness ---


def run_agent(messages: list[dict], session_id: str) -> tuple[str, list[dict]]:
    """Complete until the model answers without asking for a tool.

    Returns the final text and a record of every tool call made along the way.
    """
    tool_calls = []

    for _ in range(MAX_TOOL_ROUNDS):
        reply = litellm.completion(
            model=MODEL,
            vertex_location="global",
            messages=messages,
            tools=TOOLS,
            num_retries=3,  # ride out dropped connections (SSL EOF, resets)
        ).choices[0].message

        # Append assistant's reply (text, tool calls, or both) to the context.
        # model_dump() keeps it a plain dict: the raw object carries provider-specific
        # fields that trip Pydantic when LiteLLM re-serializes it next round.
        messages += [reply.model_dump()]

        if not reply.tool_calls:
            return reply.content or "", tool_calls

        # The harness, not the model, runs each tool and appends the result
        for call in reply.tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError as e:
                args = {}
                result = json.dumps({"ok": False, "error": f"Arguments were not valid JSON: {e}",
                                     "fix": "Call the tool again with a valid JSON object."})
            else:
                result = run_tool(call.function.name, args, session_id)
            tool_calls += [{"name": call.function.name, "args": args, "result": result}]

            messages += [{"role": "tool", "tool_call_id": call.id, "content": result}]

    return "Sorry, I hit my tool-call limit before finishing.", tool_calls


def describe_model_error(e: Exception) -> str:
    """One readable line plus how to fix it, instead of a provider traceback."""
    detail = (str(e).strip().splitlines() or [type(e).__name__])[0][:300]
    text = str(e).lower()
    if "connection" in text or "ssl" in text or "timed out" in text:
        hint = "Network problem reaching Google (VPN/proxy?). Check your connection and try again."
    elif "credentials" in text or "default credentials" in text:
        hint = "Run `gcloud auth application-default login`, then restart the server."
    elif "sdk not found" in text or "aiplatform" in text:
        hint = "Install the dependencies with `uv sync` (needs google-cloud-aiplatform)."
    elif "billing" in text or "permission" in text or "403" in text:
        hint = "Check that your GCP project has billing and the Vertex AI API enabled."
    else:
        hint = "Check the server log for details."
    return f"Model call failed: {type(e).__name__}: {detail}\n{hint}"


# --- Session Store ---

# session_id -> list of messages. In-memory, single process.
# Each pipeline keeps its own per-session state (e.g. the current SideQuest),
# keyed by the same session_id.
sessions: dict[str, list] = {}


def get_or_create_session(session_id: str | None) -> str:
    session_id = session_id or str(uuid.uuid4())
    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": build_system_prompt()}]
    return session_id


# --- FastAPI App ---

app = FastAPI(title="Day as Someone")
app.include_router(events_router)


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]


class SessionRequest(BaseModel):
    session_id: str


@app.get("/")
def index():
    return FileResponse(
        Path(__file__).parent / "index.html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


@app.get("/story")
def story_page():
    """Story's standalone /api/events form, kept as a developer page."""
    return FileResponse(Path(__file__).resolve().parent.parent / "frontend" / "sidequest.html")


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    session_id = get_or_create_session(request.session_id)

    # Append user's message to the context
    sessions[session_id] += [{"role": "user", "content": request.message}]

    try:
        response, tool_calls = run_agent(sessions[session_id], session_id)
    except Exception as e:
        # Auth, billing, a model that is not running: show it in the chat, not as a 500.
        response, tool_calls = describe_model_error(e), []

    return ChatResponse(response=response, session_id=session_id, tool_calls=tool_calls)


@app.post("/clear")
def clear(session_id: str | None = None):
    sessions.pop(session_id, None)
    if session_id:
        clear_session(session_id)
    return {"status": "ok"}


# --- UI endpoints (the SideQuest side panel) ---


@app.get("/api/status")
def status():
    """Which features are live, so the UI can disable the rest."""
    return {"model": MODEL, "features": features(), "demo_available": DEMO_PATH.exists()}


@app.get("/api/sidequest")
def current_sidequest(session_id: str):
    return adaptation_tools.get_current_sidequest(session_id)


@app.post("/api/demo")
def load_demo(request: SessionRequest):
    """Load a sample SideQuest so repairs can be tried before planning exists."""
    try:
        data = json.loads(DEMO_PATH.read_text(encoding="utf-8"))
        quest = sidequest_from_dict(data["quest"])
        candidates = [place_from_dict(c) for c in data.get("candidates", [])]
    except (OSError, ValueError, KeyError, TypeError) as e:
        return {"ok": False, "error": f"Couldn't load the demo SideQuest: {e}"}

    session_id = get_or_create_session(request.session_id)
    adaptation_tools.start_session(session_id, quest, candidates)
    stops = ", ".join(f"{s.chapter or s.step_id}: {s.place.name}" for s in quest.steps)
    # Tell the model, so "what's my plan?" works without a tool call.
    sessions[session_id] += [{
        "role": "assistant",
        "content": f"I loaded the demo SideQuest \"{data.get('title', quest.theme)}\" in "
                   f"{data.get('city', 'the city')} as a {quest.persona}. Stops: {stops}.",
    }]
    return {**adaptation_tools.get_current_sidequest(session_id),
            "title": data.get("title"), "city": data.get("city")}


@app.post("/api/undo")
def undo(request: SessionRequest):
    result = adaptation_tools.undo_last_repair(request.session_id)
    if result.get("ok") and request.session_id in sessions:
        version = result["sidequest"]["version"]
        sessions[request.session_id] += [{
            "role": "assistant",
            "content": f"(The user undid the last change; the SideQuest is back to version {version}.)",
        }]
    return result
