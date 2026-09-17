import math

import pytest

from arena_core import ActionError, GameMode, GameSession, MeasureKind


def test_fixed_seed_reproduces_world_and_other_seed_changes_it():
    first = GameSession.new(seed=1234, mode=GameMode.MIXED_DIRECTIONAL, source_count=12)
    again = GameSession.new(seed=1234, mode=GameMode.MIXED_DIRECTIONAL, source_count=12)
    other = GameSession.new(seed=1235, mode=GameMode.MIXED_DIRECTIONAL, source_count=12)

    assert first.truth_digest() == again.truth_digest()
    assert first.truth_digest() != other.truth_digest()


@pytest.mark.parametrize("seed", range(25))
def test_random_source_count_and_unique_channels(seed):
    game = GameSession.new(seed=seed, mode=GameMode.OMNIDIRECTIONAL)
    assert 10 <= game.source_count <= 16
    assert len(game.sources) == len(set(game.sources))


def test_source_types_follow_mode_rules():
    omni = GameSession.new(seed=7, mode=GameMode.OMNIDIRECTIONAL, source_count=16)
    mixed = GameSession.new(seed=7, mode=GameMode.MIXED_DIRECTIONAL, source_count=16)

    assert all(source.direction_deg is None for source in omni.sources.values())
    assert any(source.direction_deg is not None for source in mixed.sources.values())
    assert mixed.directional_count + mixed.omnidirectional_count == 16


def test_mixed_mode_uses_six_sixteenths_threshold(monkeypatch):
    game = GameSession.new(seed=9, mode=GameMode.MIXED_DIRECTIONAL, source_count=16)
    assert game.directional_probability == pytest.approx(6 / 16)


def test_move_measure_switch_and_clear_costs():
    game = GameSession.for_test(
        mode=GameMode.OMNIDIRECTIONAL,
        sources={3: {"x": 100.0, "y": 0.0, "radius": 1000.0}},
    )

    game.apply({"type": "move", "x": 30.0, "y": 40.0})
    assert game.virtual_time_s == pytest.approx(10.0)

    measured = game.apply({"type": "measure", "channel": 3})
    assert measured["result"] == MeasureKind.DIRECTION.value
    assert game.virtual_time_s == pytest.approx(16.0)
    assert game.current_channel == 3

    game.apply({"type": "measure", "channel": 3})
    assert game.virtual_time_s == pytest.approx(21.0)

    failed = game.apply({"type": "clear", "channel": 3})
    assert failed["success"] is False
    assert game.virtual_time_s == pytest.approx(24.0)
    assert game.current_channel == 3

    game.apply({"type": "move", "x": 80.0, "y": 0.0})
    cleared = game.apply({"type": "clear", "channel": 3})
    assert cleared["success"] is True
    assert game.virtual_time_s == pytest.approx(24.0 + math.hypot(50.0, -40.0) / 5.0 + 5.0)
    assert game.current_channel == 3


def test_near_and_clear_boundaries_are_inclusive():
    near_game = GameSession.for_test(
        mode=GameMode.OMNIDIRECTIONAL,
        sources={1: {"x": 5.0, "y": 0.0, "radius": 1000.0}},
    )
    assert near_game.apply({"type": "measure", "channel": 1})["result"] == "near"

    clear_game = GameSession.for_test(
        mode=GameMode.OMNIDIRECTIONAL,
        sources={1: {"x": 20.0, "y": 0.0, "radius": 1000.0}},
    )
    assert clear_game.apply({"type": "clear", "channel": 1})["success"] is True
    cleared = clear_game.public_state()["channels"][0]
    assert cleared["status"] == "cleared"
    assert cleared["cleared_position"] == [0.0, 0.0]


def test_directional_visibility_half_plane_boundary_is_inclusive():
    game = GameSession.for_test(
        mode=GameMode.MIXED_DIRECTIONAL,
        sources={1: {"x": 0.0, "y": 0.0, "radius": 1000.0, "direction_deg": 90.0}},
        position=(5.0, 0.0),
    )
    assert game.apply({"type": "measure", "channel": 1})["result"] == "near"


def test_bearing_error_is_deterministic_and_bounded():
    game = GameSession.for_test(
        seed=77,
        mode=GameMode.OMNIDIRECTIONAL,
        sources={1: {"x": 100.0, "y": 0.0, "radius": 1000.0}},
    )
    first = game.apply({"type": "measure", "channel": 1})
    game.apply({"type": "move", "x": 0.0, "y": 10.0})
    second = game.apply({"type": "move", "x": 0.0, "y": 0.0})
    repeated = game.apply({"type": "measure", "channel": 1})

    assert second["type"] == "move"
    assert first["bearing_deg"] == repeated["bearing_deg"]
    error = ((first["bearing_deg"] - 0.0 + 180.0) % 360.0) - 180.0
    assert abs(error) <= 1.0


def test_invalid_actions_do_not_change_time():
    game = GameSession.new(seed=1, mode=GameMode.OMNIDIRECTIONAL, source_count=10)

    with pytest.raises(ActionError):
        game.apply({"type": "measure", "channel": 21})
    with pytest.raises(ActionError):
        game.apply({"type": "move", "x": math.nan, "y": 0})

    assert game.virtual_time_s == 0
    assert game.events == []


def test_source_count_is_hidden_until_intel_or_completion():
    game = GameSession.for_test(
        mode=GameMode.OMNIDIRECTIONAL,
        sources={1: {"x": 0.0, "y": 0.0, "radius": 1000.0}},
    )

    initial = game.public_state()
    assert initial["source_count"] is None
    assert "sources" not in initial

    game.reveal_total()
    revealed = game.public_state()
    assert revealed["source_count"] == 1
    assert revealed["assisted"] is True


def test_completion_reveals_total_without_marking_assisted():
    game = GameSession.for_test(
        mode=GameMode.OMNIDIRECTIONAL,
        sources={1: {"x": 0.0, "y": 0.0, "radius": 1000.0}},
    )
    game.apply({"type": "clear", "channel": 1})

    state = game.public_state()
    assert state["completed"] is True
    assert state["source_count"] == 1
    assert state["assisted"] is False
