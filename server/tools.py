"""Every tool the harness can run: one registry over all three pipelines.

Each pipeline exposes a tools module with:
    TOOLS           OpenAI/LiteLLM-format declarations (what the model sees)
    TOOL_FUNCTIONS  tool name -> Python function
    run_tool(name, args, session_id) -> dict   never raises
    clear_session(session_id)                  optional

To add your pipeline, import its tools module and append it to PIPELINES.
FEATURES then flips the matching UI section to "live" on its own.
"""

import json

from tools.adaptation import tools as adaptation_tools
from tools.reality import tools as reality_tools
from tools.story import tools as story_tools

PIPELINES = [reality_tools, story_tools, adaptation_tools]

TOOLS = [decl for module in PIPELINES for decl in module.TOOLS]

_OWNER = {name: module for module in PIPELINES for name in module.TOOL_FUNCTIONS}
assert len(_OWNER) == sum(len(m.TOOL_FUNCTIONS) for m in PIPELINES), "duplicate tool name"

# What the UI shows. A feature is live once every tool it needs is registered.
FEATURES = [
    {
        "id": "places",
        "label": "Find places for a persona",
        "owner": "Reality",
        "tools": ["match_theme"],
        "description": "Ranks real places in a NYC neighborhood that fit the persona you want to live.",
    },
    {
        "id": "plan",
        "label": "Build the full SideQuest",
        "owner": "Story",
        "tools": ["build_sidequest"],
        "description": "Turns those places into a chaptered itinerary with narrative and micro-tasks.",
    },
    {
        "id": "events",
        "label": "Live events",
        "owner": "Story",
        "tools": ["find_events"],
        "description": "Finds concerts, shows and exhibitions near you on Ticketmaster to weave into the route.",
    },
    {
        "id": "repair",
        "label": "Repair on the fly",
        "owner": "Adaptation",
        "tools": ["repair_sidequest"],
        "description": "Closed venue, rain, smaller budget, tired feet: swap only the affected chapters.",
    },
    {
        "id": "weather",
        "label": "Live weather",
        "owner": "Adaptation",
        "tools": ["get_weather"],
        "description": "Checks Open-Meteo near your next stop before moving things indoors.",
    },
    {
        "id": "memory",
        "label": "Quest memory",
        "owner": "Adaptation",
        "tools": ["get_current_sidequest"],
        "description": "Remembers your plan and every change across the conversation.",
    },
]


def available_tools() -> list[str]:
    return list(_OWNER)


def features() -> list[dict]:
    return [{**f, "available": all(t in _OWNER for t in f["tools"]),
             "missing_tools": [t for t in f["tools"] if t not in _OWNER]}
            for f in FEATURES]


def run_tool(name: str, args: dict, session_id: str) -> str:
    """Run one tool call and return its result as a JSON string for the model.

    Models invent tool names and arguments; never let that crash the loop.
    """
    module = _OWNER.get(name)
    if module is None:
        result = {"ok": False, "error": f"Unknown tool '{name}'.",
                  "fix": f"Use one of: {', '.join(_OWNER)}."}
    else:
        try:
            result = module.run_tool(name, args, session_id)
        except Exception as e:
            result = {"ok": False, "error": f"{name} crashed: {type(e).__name__}: {e}",
                      "fix": "Tell the user this step failed and offer to try again."}
    return json.dumps(result, ensure_ascii=False, default=str)


def clear_session(session_id: str) -> None:
    for module in PIPELINES:
        clear = getattr(module, "clear_session", None)
        if clear:
            clear(session_id)
