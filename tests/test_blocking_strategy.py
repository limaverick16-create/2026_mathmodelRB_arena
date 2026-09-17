import math

import pytest

from arena_sdk.blocking import BlockingPolicyAdapter


class ScriptedPolicy:
    def __init__(self, measure, clear, game_info):
        self.measure = measure
        self.clear = clear
        self.game_info = game_info

    def run(self):
        result, angle = self.measure((30, 40), 7)
        assert result == "direction"
        assert angle == pytest.approx(math.pi / 2)
        assert self.clear((30, 40), 7) is True


def test_blocking_policy_is_exposed_as_one_arena_action_per_step():
    strategy = BlockingPolicyAdapter(ScriptedPolicy)
    strategy.reset({"start": [0, 0], "mode": "omnidirectional"})

    assert strategy.next_action({"events": [], "position": [0, 0]}) == {
        "type": "move",
        "x": 30.0,
        "y": 40.0,
    }
    assert strategy.next_action(
        {
            "position": [30, 40],
            "events": [{"type": "move", "position": [30, 40]}],
        }
    ) == {"type": "measure", "channel": 7}
    assert strategy.next_action(
        {
            "position": [30, 40],
            "events": [
                {
                    "type": "measure",
                    "channel": 7,
                    "result": "direction",
                    "bearing_deg": 90,
                    "position": [30, 40],
                }
            ],
        }
    ) == {"type": "clear", "channel": 7}


def test_blocking_policy_propagates_background_failures():
    class BrokenPolicy:
        def __init__(self, measure, clear, game_info):
            pass

        def run(self):
            raise ValueError("broken policy")

    strategy = BlockingPolicyAdapter(BrokenPolicy)
    strategy.reset({"start": [0, 0]})
    with pytest.raises(RuntimeError, match="broken policy"):
        strategy.next_action({"events": [], "position": [0, 0]})
