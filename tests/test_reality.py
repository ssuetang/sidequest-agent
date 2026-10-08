import json
from tools.reality.match_theme import PERSONA_PROFILES, candidate_places, match_theme
from tools.reality import tools
from server import tools as registry
from integrations.places import PLACES_URL, search_places


def test_novelist_prefers_literary_places():
    result = match_theme("struggling novelist", "Greenwich Village", use_live_places=False)
    assert result["ok"]
    assert result["places"][0]["name"] in {"Three Lives & Company", "Caffe Reggio", "Jefferson Market Library"}
    assert result["places"][0]["theme_score"] > 0 and result["places"][0]["match_reasons"]


def test_personas_produce_different_rankings():
    a = match_theme("novelist", "Greenwich Village", use_live_places=False)
    b = match_theme("indie filmmaker", "Greenwich Village", use_live_places=False)
    assert [p["place_id"] for p in a["places"][:3]] != [p["place_id"] for p in b["places"][:3]]


def test_twenty_presets_are_viable_and_explainable():
    assert len(PERSONA_PROFILES) == 20
    for persona in PERSONA_PROFILES:
        result = match_theme(persona, "DUMBO", max_results=4, use_live_places=False)
        assert result["ok"] and result["profile_used"] == persona
        assert len(result["places"]) == 4
        assert all(place["match_reasons"] for place in result["places"])


def test_new_persona_aliases_resolve_to_presets():
    assert match_theme("jazz musician", "Chinatown", use_live_places=False)["profile_used"] == "jazz age drifter"
    assert match_theme("food writer", "Chinatown", use_live_places=False)["profile_used"] == "neighborhood food chronicler"
    assert match_theme("melancholy poet", "DUMBO", use_live_places=False)["profile_used"] == "waterfront poet"
    assert match_theme("radio producer", "DUMBO", use_live_places=False)["profile_used"] == "community radio producer"
    assert match_theme("noir writer", "Chinatown", use_live_places=False)["profile_used"] == "midnight mystery writer"
    assert match_theme("time traveler", "Morningside Heights", use_live_places=False)["profile_used"] == "museum time traveler"


def test_results_stay_in_neighborhood_and_are_diverse():
    result = match_theme("urban detective", "Chinatown", max_results=5, use_live_places=False)
    assert all(p["neighborhood"] == "Chinatown" for p in result["places"])
    assert len({p["category"] for p in result["places"]}) >= 4


def test_preferences_change_reason():
    result = match_theme("urban detective", "DUMBO", ["waterfront"], use_live_places=False)
    place = next(p for p in result["places"] if "waterfront" in p["tags"])
    assert any("user's preference" in reason for reason in place["match_reasons"])


def test_errors_and_custom_persona():
    bad = match_theme("novelist", "Queens", use_live_places=False)
    assert not bad["ok"] and "Greenwich Village" in bad["fix"]
    assert not match_theme(" ", "DUMBO", use_live_places=False)["ok"]
    custom = match_theme("cinematic street observer", "DUMBO", use_live_places=False)
    assert custom["ok"] and custom["profile_used"] == "custom"


def test_custom_persona_uses_controlled_llm_analysis():
    result = match_theme("nocturnal image-maker", "DUMBO",
        desired_tags=["music", "photography", "street", "not-a-real-tag"],
        avoid_tags=["touristy", "made-up"], story_tone="noir and reflective",
        use_live_places=False)
    assert result["ok"] and result["profile_used"] == "custom"
    analysis = result["role_analysis"]
    assert analysis["desired_tags"] == ["music", "photography", "street"]
    assert analysis["avoid_tags"] == ["touristy"]
    assert analysis["story_tone"] == "noir and reflective"
    assert analysis["ignored_tags"] == ["made up", "not a real tag"]
    assert any("photography" in reason or "street" in reason
               for place in result["places"] for reason in place["match_reasons"])


def test_custom_tags_can_refine_a_preset():
    result = match_theme("indie filmmaker", "DUMBO",
                         desired_tags=["quiet", "waterfront"],
                         avoid_tags=["touristy"], use_live_places=False)
    assert result["ok"]
    assert result["profile_used"] == "indie filmmaker"
    assert result["role_analysis"]["desired_tags"] == ["quiet", "waterfront"]


def test_output_converts_to_shared_candidates():
    result = match_theme("architecture apprentice", "Morningside Heights", use_live_places=False)
    places = candidate_places(result)
    assert places and places[0].place_id and places[0].tags
    json.dumps(result)


def test_search_places_category_filter():
    result = search_places("Morningside Heights", ["bookstore"], use_live=False)
    assert result.ok and {p.category for p in result.places} == {"bookstore"}


def test_google_places_request_and_mapping():
    class Response:
        def raise_for_status(self): pass
        def json(self):
            return {"places": [{"id": "google-1", "displayName": {"text": "Live Bookshop"},
                "formattedAddress": "New York, NY", "location": {"latitude": 40.73, "longitude": -74.0},
                "primaryType": "book_store", "types": ["book_store", "store"], "rating": 4.9,
                "priceLevel": "PRICE_LEVEL_INEXPENSIVE", "currentOpeningHours": {"openNow": True}}]}
    seen = {}
    def fake_post(url, **kwargs):
        seen.update(url=url, headers=kwargs["headers"]); return Response()
    result = search_places("Greenwich Village", ["bookstore"], api_key="key", http_post=fake_post)
    assert result.ok and result.source == "google+local" and seen["url"] == PLACES_URL
    assert "places.displayName" in seen["headers"]["X-Goog-FieldMask"]
    assert result.places[0].candidate.name == "Live Bookshop"


def test_google_failure_falls_back_to_local():
    def fail(*args, **kwargs): raise ValueError("bad response")
    result = search_places("DUMBO", api_key="key", http_post=fail)
    assert result.ok and result.source == "local" and "fallback" in result.fix


def test_tool_contract_and_errors():
    names = {d["function"]["name"] for d in tools.TOOLS}
    assert names == set(tools.TOOL_FUNCTIONS) == {"search_places", "match_theme"}
    assert all(len(d["function"]["description"]) > 100 for d in tools.TOOLS)
    out = tools.run_tool("match_theme", {"persona": "novelist", "neighborhood": "Greenwich Village",
        "max_results": 4, "use_live_places": False}, "session")
    assert out["ok"] and not tools.run_tool("teleport", {}, "s")["ok"]
    bad = tools.run_tool("match_theme", {"persona": "novelist", "neighborhood": "DUMBO", "rain": True}, "s")
    assert not bad["ok"] and "Unknown arguments" in bad["error"]


def test_main_registry_exposes_and_runs_reality_tool():
    names = {d["function"]["name"] for d in registry.TOOLS}
    assert {"search_places", "match_theme"} <= names
    payload = json.loads(registry.run_tool("match_theme", {
        "persona": "architecture apprentice",
        "neighborhood": "Morningside Heights",
        "max_results": 4,
        "use_live_places": False,
    }, "reality-session"))
    assert payload["ok"] and len(payload["places"]) == 4
