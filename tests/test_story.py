import json

from fastapi.testclient import TestClient

from tools.story.build_sidequest import SideQuest, build_sidequest, parse_sidequest, run_tool, search_events
from server.main import app


def test_builder_returns_ordered_sidequest_with_time_budget():
    sidequest = parse_sidequest(build_sidequest("night filmmaker", 90, ["Bookshop", "River path"]))

    assert isinstance(sidequest, SideQuest)
    assert [chapter.title for chapter in sidequest.chapters] == ["Research", "Inspiration"]
    stops = [stop for chapter in sidequest.chapters for stop in chapter.stops]
    assert [stop.order for stop in stops] == [1, 2]
    assert [stop.place for stop in stops] == ["Bookshop", "River path"]
    assert sum(stop.minutes for stop in stops) == sidequest.duration_minutes
    assert all(stop.micro_tasks for stop in stops)


def test_builder_uses_local_defaults_when_places_are_missing():
    sidequest = parse_sidequest(build_sidequest("curious observer", 45, []))

    assert len(sidequest.chapters) == 3
    assert sidequest.duration_minutes == 45


def test_run_tool_reports_unknown_tool():
    result = json.loads(run_tool("unknown", {}))

    assert result["error"] == "Unknown tool: unknown"


def test_events_api_returns_local_sidequest(monkeypatch):
    monkeypatch.setenv("SIDEQUEST_USE_MODEL", "0")
    client = TestClient(app)

    response = client.post(
        "/api/events",
        json={
            "message": "I want a quiet walk",
            "theme": "quiet observer",
            "duration_minutes": 60,
            "places": ["Bookshop", "River path"],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "local"
    assert payload["sidequest"]["chapters"][0]["stops"][0]["place"] == "Bookshop"
    assert payload["session_id"]


def test_builder_weaves_events_and_reports_budget():
    sidequest = parse_sidequest(build_sidequest("struggling novelist", 120, ["Cafe", "Gallery"], 40, ["Author reading"]))

    assert sidequest.budget_status == "within budget"
    assert sidequest.estimated_cost == 35
    assert sidequest.chapters[0].stops[0].event == "Author reading"


def test_search_events_reads_ticketmaster_results(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"_embedded": {"events": [{"name": "Author reading"}, {"name": "Indie film night"}]}}

    monkeypatch.setenv("TICKETMASTER_API_KEY", "test-key")
    monkeypatch.setattr("tools.story.build_sidequest.requests.get", lambda *args, **kwargs: FakeResponse())

    assert search_events("novelist", "New York") == ["Author reading", "Indie film night"]


def test_events_api_rejects_short_duration():
    client = TestClient(app)

    response = client.post(
        "/api/events",
        json={"message": "too short", "duration_minutes": 10},
    )

    assert response.status_code == 422