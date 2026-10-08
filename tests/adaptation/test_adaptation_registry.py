import json

from tools.adaptation import tools as adaptation_tools
from server import tools as registry


def test_tools_are_litellm_format():
    names = [t["function"]["name"] for t in registry.TOOLS]
    assert {"repair_sidequest", "get_weather", "get_current_sidequest"} <= set(names)
    assert all(t["type"] == "function" and t["function"]["description"] for t in registry.TOOLS)


def test_run_tool_returns_json_string(novelist_quest, spare_candidates):
    adaptation_tools.start_session("s", novelist_quest, spare_candidates)
    out = registry.run_tool("repair_sidequest", {"unavailable_stops": ["gallery"]}, "s")
    assert isinstance(out, str) and json.loads(out)["ok"]


def test_unknown_tool_is_reported_not_raised():
    out = json.loads(registry.run_tool("fly_to_moon", {}, "s"))
    assert not out["ok"] and "repair_sidequest" in out["fix"]


def test_clear_session_forgets_quest(novelist_quest):
    adaptation_tools.start_session("gone", novelist_quest)
    registry.clear_session("gone")
    assert not json.loads(registry.run_tool("get_current_sidequest", {}, "gone"))["ok"]
