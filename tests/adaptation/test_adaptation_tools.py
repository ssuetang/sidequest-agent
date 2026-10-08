import json

import pytest

from tools.adaptation import tools
from tools.adaptation.memory import InMemorySessionStore, JsonFileSessionStore
from integrations.weather import WeatherReport


@pytest.fixture(autouse=True)
def fresh_store():
    tools.configure(store=InMemorySessionStore())


@pytest.fixture
def session(novelist_quest, spare_candidates):
    tools.start_session("u1", novelist_quest, spare_candidates)
    return "u1"


def fake_weather(report):
    def _get(lat, lng, **kw):
        return report
    return _get


def test_results_are_json_serializable(session, monkeypatch):
    monkeypatch.setattr(tools.weather_api, "get_weather",
                        fake_weather(WeatherReport(ok=True, condition="rain", bad_for_outdoor=True)))
    for name, args in [("repair_sidequest", {"unavailable_stops": ["gallery"]}),
                       ("get_weather", {}),
                       ("get_current_sidequest", {})]:
        json.dumps(tools.run_tool(name, args, session))


def test_declarations_match_functions():
    assert {d["name"] for d in tools.TOOL_DECLARATIONS} == set(tools.TOOL_FUNCTIONS)
    for d in tools.TOOL_DECLARATIONS:
        assert len(d["description"]) > 80
        for prop in d.get("parameters", {}).get("properties", {}).values():
            assert prop["description"]


def test_second_turn_gallery_closed_and_raining(session):
    # What Gemini would send for "The gallery is closed and it's raining.
    # Keep the novelist theme."
    out = tools.run_tool("repair_sidequest", {"unavailable_stops": ["gallery"], "bad_weather": True}, session)
    assert out["ok"] and out["changed"]
    q = out["sidequest"]
    assert q["theme"] == "novelist" and q["persona"] == "struggling 1950s novelist"
    assert [s["chapter"] for s in q["stops"]] == [
        "Chapter 1: The Blank Page", "Chapter 2: The Muse", "Chapter 3: Overheard", "Chapter 4: The Last Round"]
    assert q["stops"][0]["place"] == "Caffe Reggio"
    assert q["stops"][3]["place"] == "White Horse Tavern"
    assert all(s["indoor"] for s in q["stops"])
    assert {a["step_id"] for a in out["actions"]} == {"s2", "s3"}

    # Memory: the next turn sees the repaired quest.
    current = tools.run_tool("get_current_sidequest", {}, session)
    assert current["sidequest"]["version"] == 2 and current["earlier_versions"] == 1
    assert current["recent_changes"]


def test_unknown_stop_lists_valid_stops(session):
    out = tools.run_tool("repair_sidequest", {"unavailable_stops": ["the opera house"]}, session)
    assert not out["ok"]
    assert "Caffe Reggio" in out["fix"] and "s1" in out["fix"]


def test_ambiguous_stop_asks_to_clarify(session):
    # "literary" is a tag on the cafe, gallery and tavern.
    out = tools.run_tool("repair_sidequest", {"skip_stops": ["literary"]}, session)
    assert not out["ok"] and "several stops" in out["error"]


def test_nothing_to_repair(session):
    out = tools.run_tool("repair_sidequest", {}, session)
    assert not out["ok"] and "get_current_sidequest" in out["fix"]


def test_bad_numbers(session):
    assert not tools.run_tool("repair_sidequest", {"new_budget": -5}, session)["ok"]
    assert not tools.run_tool("repair_sidequest", {"new_budget": "lots"}, session)["ok"]
    assert tools.run_tool("repair_sidequest", {"new_budget": "$10"}, session)["ok"]


def test_no_session():
    for name in ("repair_sidequest", "get_current_sidequest"):
        out = tools.run_tool(name, {"bad_weather": True} if name == "repair_sidequest" else {}, "nobody")
        assert not out["ok"] and "build_sidequest" in out["fix"]


def test_unknown_tool_and_unknown_args(session):
    assert "Use one of" in tools.run_tool("teleport", {}, session)["fix"]
    out = tools.run_tool("repair_sidequest", {"rain": True}, session)
    assert not out["ok"] and "bad_weather" in out["fix"]


def test_model_cannot_override_session(session):
    out = tools.run_tool("get_current_sidequest", {"session_id": "someone-else"}, session)
    assert out["ok"]


def test_unresolved_gets_actionable_fix(novelist_quest):
    tools.start_session("bare", novelist_quest, candidates=[])  # nothing to swap in
    out = tools.run_tool("repair_sidequest", {"unavailable_stops": ["gallery"]}, "bare")
    assert out["ok"] and out["unresolved"][0]["step_id"] == "s2"
    assert "match_theme" in out["fix"]


def test_walk_and_time_and_skip(session):
    out = tools.run_tool("repair_sidequest", {"max_walk_minutes": 8}, session)
    assert out["ok"] and all(s["walk_min_from_prev"] <= 8 for s in out["sidequest"]["stops"])
    out = tools.run_tool("repair_sidequest", {"skip_stops": ["park"]}, session)
    assert "Overheard" not in [s["chapter"] for s in out["sidequest"]["stops"]]
    out = tools.run_tool("repair_sidequest", {"minutes_left": 60}, session)
    assert out["ok"] and out["sidequest"]["total_time_min"] <= 60


def test_weather_tool_uses_next_stop_and_suggests_repair(session, monkeypatch):
    seen = {}

    def fake(lat, lng, **kw):
        seen["coords"] = (lat, lng)
        return WeatherReport(ok=True, condition="rain", bad_for_outdoor=True)

    monkeypatch.setattr(tools.weather_api, "get_weather", fake)
    out = tools.run_tool("get_weather", {}, session)
    assert out["ok"] and out["location"]["label"] == "Caffe Reggio"
    assert out["outdoor_stops"] == ["Washington Square Park"]
    assert "bad_weather=true" in out["suggestion"]

    tools.run_tool("get_weather", {"stop": "tavern"}, session)
    assert seen["coords"] == (40.7359, -74.0060)


def test_weather_tool_failure_is_actionable(session, monkeypatch):
    monkeypatch.setattr(tools.weather_api, "get_weather",
                        fake_weather(WeatherReport(ok=False, error="HTTP 503")))
    out = tools.run_tool("get_weather", {}, session)
    assert not out["ok"] and "Ask the user" in out["fix"]


def test_weather_without_session_needs_location():
    out = tools.run_tool("get_weather", {}, "nobody")
    assert not out["ok"] and "city name" in out["fix"]


def test_weather_by_city_name(monkeypatch):
    from integrations.weather import GeocodeResult
    monkeypatch.setattr(tools.weather_api, "geocode",
                        lambda name: GeocodeResult(ok=True, name="New York, United States", lat=40.71, lng=-74.0))
    monkeypatch.setattr(tools.weather_api, "get_weather",
                        fake_weather(WeatherReport(ok=True, condition="clear")))
    out = tools.run_tool("get_weather", {"location": "New York"}, "nobody")
    assert out["ok"] and out["location"]["label"] == "New York, United States"
    assert "suggestion" not in out  # no SideQuest to compare against


def test_weather_unknown_city(monkeypatch):
    from integrations.weather import GeocodeResult
    monkeypatch.setattr(tools.weather_api, "geocode",
                        lambda name: GeocodeResult(ok=False, error="no place called 'Atlantis' was found"))
    out = tools.run_tool("get_weather", {"location": "Atlantis"}, "nobody")
    assert not out["ok"] and "Retry" in out["fix"]


def test_completed_stop_is_frozen(session):
    tools.mark_stop_completed(session, "s2")
    out = tools.run_tool("repair_sidequest", {"unavailable_stops": ["gallery"]}, session)
    assert out["ok"] and not out["changed"]


def test_json_store_persists(tmp_path, novelist_quest, spare_candidates):
    tools.configure(store=JsonFileSessionStore(tmp_path))
    tools.start_session("user/1", novelist_quest, spare_candidates)
    tools.run_tool("repair_sidequest", {"unavailable_stops": ["gallery"]}, "user/1")

    tools.configure(store=JsonFileSessionStore(tmp_path))  # simulate restart
    out = tools.run_tool("get_current_sidequest", {}, "user/1")
    assert out["sidequest"]["version"] == 2
