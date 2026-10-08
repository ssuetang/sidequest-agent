"""Gemini-callable tools owned by the Reality / Places pipeline."""

from __future__ import annotations
from typing import Any
from tools.reality.match_theme import match_theme
from integrations.places import search_places


def search_places_tool(neighborhood: str, categories: list[str] | None = None,
                       max_results: int = 12) -> dict[str, Any]:
    result = search_places(neighborhood, categories, max_results)
    if not result.ok:
        return {"ok": False, "error": result.error, "fix": result.fix}
    out = {"ok": True, "source": result.source, "places": [p.to_dict() for p in result.places]}
    if result.fix:
        out["warning"] = result.fix
    return out


TOOL_FUNCTIONS = {"search_places": search_places_tool, "match_theme": match_theme}
_DECLARATIONS = [
    {"name": "search_places", "description": "Search for real place candidates inside one supported New York City neighborhood. Use this external-data tool when fresh Google Places results are useful before theme matching. It supports Morningside Heights, Greenwich Village, Chinatown, and DUMBO and safely falls back to curated local data.",
     "parameters": {"type": "object", "properties": {
        "neighborhood": {"type": "string", "description": "One supported NYC neighborhood."},
        "categories": {"type": "array", "items": {"type": "string"}, "description": "Optional categories or tags such as bookstore, park, gallery, or cafe."},
        "max_results": {"type": "integer", "description": "Maximum number of candidates, from 1 to 20."}}, "required": ["neighborhood"]}},
    {"name": "match_theme", "description": "Original Reality tool that finds and ranks viable places for the persona the user wants to experience. Use it for a brand-new SideQuest before build_sidequest. Twenty preset personas receive curated weights. For any custom persona, first interpret it into desired_tags, avoid_tags, and story_tone using only the allowed vocabulary below. The tool then applies explainable deterministic scoring, excludes reported-closed places, and returns a category-diverse shortlist.",
     "parameters": {"type": "object", "properties": {
        "persona": {"type": "string", "description": "Persona or lens. Twenty presets are available: struggling novelist, urban detective, indie filmmaker, architecture apprentice, city naturalist, independent magazine editor, jazz age drifter, street photographer, hidden history archivist, thrift fashion scout, neighborhood food chronicler, waterfront poet, campus intellectual, avant garde theater actor, urban sketch artist, community radio producer, romantic city wanderer, industrial design student, museum time traveler, and midnight mystery writer. Other creative personas are allowed when desired_tags are supplied."},
        "neighborhood": {"type": "string", "description": "One supported NYC neighborhood."},
        "preferences": {"type": "array", "items": {"type": "string"}, "description": "Optional qualities explicitly requested by the user, such as quiet, free, historic, art, or nature."},
        "desired_tags": {"type": "array", "items": {"type": "string", "enum": ["academic", "architecture", "archive", "art", "bookstore", "cafe", "cinematic", "community", "creative", "design", "dramatic", "food", "free", "gallery", "historic", "history", "independent", "industrial", "inspiration", "landmark", "library", "literary", "low cost", "museum", "music", "mysterious", "nature", "nostalgic", "observation", "park", "people watching", "photography", "playful", "quiet", "reflection", "storytelling", "street", "theater", "touristy", "waterfront", "writing"]}, "description": "For a custom persona, infer 3-6 desired qualities using only these controlled tags. May also refine a preset."},
        "avoid_tags": {"type": "array", "items": {"type": "string", "enum": ["chain", "crowded", "luxury", "touristy"]}, "description": "Infer qualities the persona or user wants to avoid using only these controlled negative tags."},
        "story_tone": {"type": "string", "description": "Short narrative tone inferred from a custom persona, such as noir and reflective. Returned for the Story pipeline; it never overrides place facts."},
        "max_results": {"type": "integer", "description": "Maximum diverse matches to return, usually 4 to 6."}},
      "required": ["persona", "neighborhood"]}},
]
TOOLS = [{"type": "function", "function": d} for d in _DECLARATIONS]


def run_tool(name: str, args: dict[str, Any], session_id: str) -> dict[str, Any]:
    del session_id
    function = TOOL_FUNCTIONS.get(name)
    if function is None:
        return {"ok": False, "error": f"Unknown Reality tool {name!r}.",
                "fix": f"Use one of: {', '.join(TOOL_FUNCTIONS)}."}
    unknown = set(args) - set(function.__annotations__) - {"use_live_places"}
    if unknown:
        return {"ok": False, "error": f"Unknown arguments for {name}: {sorted(unknown)}.",
                "fix": "Use only the arguments in the tool declaration."}
    try:
        return function(**args)
    except (TypeError, ValueError) as exc:
        return {"ok": False, "error": f"Invalid {name} arguments: {exc}",
                "fix": "Correct the arguments using the tool declaration and try again."}


def clear_session(session_id: str) -> None:
    del session_id
