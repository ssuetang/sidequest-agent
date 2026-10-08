from tools.adaptation.repair import repair_sidequest
from tools.adaptation.schemas import ChangeType, RepairActionType, RepairContext


def ids(quest):
    return [s.place.place_id for s in quest.steps]


def test_no_change_needed(novelist_quest, spare_candidates):
    result = repair_sidequest(novelist_quest, RepairContext(ChangeType.WEATHER, outdoor_ok=True), spare_candidates)
    assert not result.changed
    assert result.quest.version == 1
    assert "No changes needed" in result.summary


def test_venue_closed_replaces_only_that_stop(novelist_quest, spare_candidates):
    ctx = RepairContext(ChangeType.PLACE_UNAVAILABLE, unavailable_place_ids=["p_gallery"])
    result = repair_sidequest(novelist_quest, ctx, spare_candidates)

    assert ids(result.quest) == ["p_cafe", "c_bookstore", "p_park", "p_bar"]
    new_step = result.quest.steps[1]
    # Same chapter, story beat and step id; narrative points at the new venue.
    assert new_step.step_id == "s2"
    assert new_step.chapter == "Chapter 2: The Muse"
    assert "Three Lives & Company" in new_step.narrative
    assert "Three Lives & Company" in new_step.micro_tasks[0]
    assert result.quest.theme == "novelist"
    assert result.quest.persona == "struggling 1950s novelist"
    assert result.quest.version == 2
    # Input quest untouched.
    assert ids(novelist_quest) == ["p_cafe", "p_gallery", "p_park", "p_bar"]


def test_rain_swaps_outdoor_stop_for_indoor_on_theme(novelist_quest, spare_candidates):
    result = repair_sidequest(novelist_quest, RepairContext(ChangeType.WEATHER, outdoor_ok=False), spare_candidates)
    park_step = result.quest.steps[2]
    assert park_step.place.indoor
    assert park_step.place.place_id != "c_garden"  # outdoor, not allowed
    assert {"people-watching", "inspiration"} & set(park_step.place.tags)
    assert [a.step_id for a in result.actions] == ["s3"]


def test_replacement_must_stay_on_theme(novelist_quest, spare_candidates):
    # Only an off-theme candidate available -> drop instead of breaking persona.
    off_theme = [c for c in spare_candidates if c.place_id == "c_offtheme"]
    ctx = RepairContext(ChangeType.PLACE_UNAVAILABLE, unavailable_place_ids=["p_gallery"])
    result = repair_sidequest(novelist_quest, ctx, off_theme)
    assert ids(result.quest) == ["p_cafe", "p_park", "p_bar"]
    assert result.actions[0].action is RepairActionType.DROPPED
    assert result.unresolved == ["s2"]


def test_event_cancelled(novelist_quest, spare_candidates):
    ctx = RepairContext(ChangeType.EVENT_CANCELLED, cancelled_step_ids=["s4"])
    result = repair_sidequest(novelist_quest, ctx, spare_candidates)
    assert result.actions[0].reason == "event cancelled"
    assert result.quest.steps[-1].step_id == "s4"
    assert result.quest.steps[-1].place.place_id != "p_bar"


def test_user_skip_drops_without_unresolved(novelist_quest, spare_candidates):
    ctx = RepairContext(ChangeType.USER_SKIP, skip_step_ids=["s2"])
    result = repair_sidequest(novelist_quest, ctx, spare_candidates)
    assert "s2" not in [s.step_id for s in result.quest.steps]
    assert result.unresolved == []


def test_budget_cut_swaps_expensive_stop(novelist_quest, spare_candidates):
    # Original spend is 8 + 0 + 0 + 15 = 23.
    ctx = RepairContext(ChangeType.BUDGET_CHANGE, new_budget=10)
    result = repair_sidequest(novelist_quest, ctx, spare_candidates)
    assert result.quest.total_cost <= 10
    assert result.quest.budget == 10
    assert "p_cafe" in ids(result.quest)  # untouched, already cheap


def test_walk_limit_replaces_far_stop(novelist_quest, spare_candidates):
    ctx = RepairContext(ChangeType.WALK_LIMIT, max_walk_min=8)
    result = repair_sidequest(novelist_quest, ctx, spare_candidates)
    assert result.changed
    assert all(s.travel_min_from_prev <= 8 for s in result.quest.steps)
    assert result.quest.max_walk_min == 8


def test_time_cut_drops_optional_first(novelist_quest, spare_candidates):
    # Full plan is 204 min; without the optional park stop it's 169.
    ctx = RepairContext(ChangeType.TIME_CHANGE, remaining_time_min=175)
    result = repair_sidequest(novelist_quest, ctx, spare_candidates)
    assert [s.step_id for s in result.quest.steps] == ["s1", "s2", "s4"]
    assert result.quest.total_time_min <= 175
    assert result.unresolved == []


def test_time_cut_reports_dropped_required_stop(novelist_quest, spare_candidates):
    ctx = RepairContext(ChangeType.TIME_CHANGE, remaining_time_min=120)
    result = repair_sidequest(novelist_quest, ctx, spare_candidates)
    assert result.quest.total_time_min <= 120
    assert result.unresolved  # a required chapter had to go; user gets told


def test_completed_steps_are_frozen(novelist_quest, spare_candidates):
    ctx = RepairContext(ChangeType.PLACE_UNAVAILABLE, unavailable_place_ids=["p_cafe"],
                        completed_step_ids=["s1"])
    result = repair_sidequest(novelist_quest, ctx, spare_candidates)
    assert not result.changed


def test_multiple_changes_at_once(novelist_quest, spare_candidates):
    changes = [
        RepairContext(ChangeType.PLACE_UNAVAILABLE, unavailable_place_ids=["p_gallery"]),
        RepairContext(ChangeType.WEATHER, outdoor_ok=False),
    ]
    result = repair_sidequest(novelist_quest, changes, spare_candidates)
    assert {a.step_id for a in result.actions} == {"s2", "s3"}
    assert all(s.place.indoor for s in result.quest.steps)
    assert len(set(ids(result.quest))) == 4  # no place used twice


def test_failing_candidate_provider_is_ignored(novelist_quest, spare_candidates):
    def boom(step, constraints):
        raise RuntimeError("places API down")

    ctx = RepairContext(ChangeType.PLACE_UNAVAILABLE, unavailable_place_ids=["p_gallery"])
    result = repair_sidequest(novelist_quest, ctx, spare_candidates, candidate_provider=boom)
    assert result.quest.steps[1].place.place_id == "c_bookstore"
    assert "places API down" in result.summary
