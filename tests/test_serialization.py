import json

from arena_core import GameMode, GameSession
from arena_core.serialization import dumps_session, loads_session


def test_round_trip_preserves_truth_events_and_public_state():
    game = GameSession.new(seed=99, mode=GameMode.MIXED_DIRECTIONAL, source_count=10)
    game.apply({"type": "move", "x": 30, "y": 40})
    game.apply({"type": "measure", "channel": 2})

    restored = loads_session(dumps_session(game))

    assert restored.truth_digest() == game.truth_digest()
    assert restored.events == game.events
    assert restored.public_state() == game.public_state()


def test_public_state_serializes_as_strict_json_without_truth():
    game = GameSession.new(seed=22, mode=GameMode.MIXED_DIRECTIONAL, source_count=11)
    payload = json.dumps(game.public_state(), allow_nan=False)

    assert "direction_deg" not in payload
    assert "reception_radius" not in payload
    assert '"sources"' not in payload
