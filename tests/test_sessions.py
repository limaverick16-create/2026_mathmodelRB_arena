import json

import pytest

from arena_core import ActionError, GameMode
from arena_server.sessions import SessionStore


class FakeClock:
    def __init__(self, value=1000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


@pytest.fixture
def clock():
    return FakeClock()


@pytest.fixture
def store(tmp_path, clock):
    return SessionStore(tmp_path, clock=clock)


def test_session_autosaves_and_can_be_reloaded(store, tmp_path):
    managed = store.create(mode=GameMode.OMNIDIRECTIONAL, seed=12, source_count=10)
    managed.apply_action({"type": "move", "x": 30, "y": 40}, command_id="move-1")

    saved = tmp_path / f"{managed.game.session_id}.json"
    assert saved.exists()
    restored_store = SessionStore(tmp_path, clock=store.clock)
    restored = restored_store.get(managed.game.session_id)
    assert restored.public_state()["position"] == [30.0, 40.0]
    assert restored.public_state()["virtual_time_s"] == 10.0


def test_player_clock_pauses_and_resumes_without_affecting_virtual_time(store, clock):
    managed = store.create(mode=GameMode.OMNIDIRECTIONAL, seed=12, source_count=10)
    clock.advance(8)
    assert managed.public_state()["player_time_s"] == 8

    managed.pause()
    clock.advance(20)
    assert managed.public_state()["player_time_s"] == 8
    assert managed.public_state()["paused"] is True

    managed.resume()
    clock.advance(3)
    assert managed.public_state()["player_time_s"] == 11
    assert managed.public_state()["virtual_time_s"] == 0


def test_actions_are_rejected_while_paused(store):
    managed = store.create(mode=GameMode.OMNIDIRECTIONAL, seed=1, source_count=10)
    managed.pause()
    with pytest.raises(ActionError, match="paused"):
        managed.apply_action({"type": "move", "x": 1, "y": 1})
    with pytest.raises(ActionError, match="paused"):
        managed.get_intel("total")
    with pytest.raises(ActionError, match="paused"):
        managed.undo()


def test_intel_marks_assisted_and_records_only_requested_truth(store):
    managed = store.create(mode=GameMode.OMNIDIRECTIONAL, seed=4, source_count=10)
    existing_channel = next(iter(managed.game.sources))
    absent_channel = next(channel for channel in range(1, 21) if channel not in managed.game.sources)

    total = managed.get_intel("total")
    assert total == {"kind": "total", "source_count": 10}
    assert managed.public_state()["assisted"] is True

    exists = managed.get_intel("channel_exists", existing_channel)
    missing = managed.get_intel("channel_exists", absent_channel)
    assert exists["exists"] is True
    assert missing["exists"] is False

    position = managed.get_intel("channel_position", existing_channel)
    assert set(position) == {"kind", "channel", "exists", "position"}
    assert position["position"] == [
        managed.game.sources[existing_channel].x,
        managed.game.sources[existing_channel].y,
    ]


def test_undo_restores_one_command_and_marks_assisted(store, clock):
    managed = store.create(mode=GameMode.OMNIDIRECTIONAL, seed=3, source_count=10)
    clock.advance(5)
    managed.apply_action({"type": "move", "x": 30, "y": 40}, command_id="move")
    managed.apply_action({"type": "measure", "channel": 1}, command_id="batch")
    managed.apply_action({"type": "measure", "channel": 2}, command_id="batch")
    before_undo_player_time = managed.public_state()["player_time_s"]

    managed.undo()
    state = managed.public_state()
    assert state["position"] == [30.0, 40.0]
    assert state["current_channel"] == 1
    assert state["virtual_time_s"] == 10.0
    assert state["assisted"] is True
    assert state["player_time_s"] == before_undo_player_time
    assert managed.audit[-1]["type"] == "undo"
    assert managed.audit[-1]["command_id"] == "batch"


def test_public_state_has_showcase_truth_only_in_showcase_mode(store):
    formal = store.create(mode=GameMode.MIXED_DIRECTIONAL, seed=1, source_count=10)
    showcase = store.create(mode=GameMode.SHOWCASE, seed=1, source_count=10)

    assert "truth" not in formal.public_state()
    assert len(showcase.public_state()["truth"]) == 10
    assert showcase.public_state()["source_count"] == 10


def test_saved_json_contains_truth_but_public_json_does_not(store, tmp_path):
    managed = store.create(mode=GameMode.MIXED_DIRECTIONAL, seed=15, source_count=10)
    public = json.dumps(managed.public_state())
    saved = (tmp_path / f"{managed.game.session_id}.json").read_text()

    assert '"sources"' not in public
    assert '"sources"' in saved
