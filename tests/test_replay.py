import copy

import pytest

from arena_core import GameMode
from arena_core.replay import ReplayError, build_replay, verify_replay
from arena_server.sessions import SessionStore


def test_replay_round_trip_recomputes_identical_result(tmp_path):
    managed = SessionStore(tmp_path).create(
        mode=GameMode.OMNIDIRECTIONAL, seed=5153753722767590603
    )
    for source in managed.game.sources.values():
        managed.apply_action({"type": "move", "x": source.x, "y": source.y})
        managed.apply_action({"type": "clear", "channel": source.channel})

    replay = build_replay(managed)
    verified = verify_replay(replay)

    assert verified["virtual_time_s"] == managed.game.virtual_time_s
    assert verified["completed"] is True
    assert verified["event_count"] == managed.game.source_count * 2
    assert len(replay["payload_sha256"]) == 64


def test_replay_rejects_changed_action_or_hash(tmp_path):
    managed = SessionStore(tmp_path).create(mode=GameMode.OMNIDIRECTIONAL, seed=44)
    managed.apply_action({"type": "move", "x": 30, "y": 40})
    replay = build_replay(managed)

    tampered = copy.deepcopy(replay)
    tampered["actions"][0]["x"] = 999
    with pytest.raises(ReplayError, match="hash"):
        verify_replay(tampered)


def test_replay_does_not_include_hidden_source_truth(tmp_path):
    managed = SessionStore(tmp_path).create(mode=GameMode.MIXED_DIRECTIONAL, seed=8)
    replay = build_replay(managed)

    assert "sources" not in replay
    assert "truth" not in replay
    assert "direction_deg" not in str(replay)
