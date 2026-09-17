import textwrap

import pytest

from arena_core import GameMode
from arena_server.sessions import SessionStore
from arena_server.strategy_runner import (
    StrategyController,
    StrategyError,
    StrategyRunner,
    discover_strategies,
)


def write_strategy(tmp_path, name, body):
    path = tmp_path / f"{name}.py"
    path.write_text(textwrap.dedent(body), encoding="utf-8")
    return path


def test_discovery_ignores_private_and_non_python_files(tmp_path):
    write_strategy(tmp_path, "alpha", "class Strategy: pass")
    write_strategy(tmp_path, "_private", "class Strategy: pass")
    (tmp_path / "notes.txt").write_text("no")

    assert discover_strategies(tmp_path) == [{"name": "alpha", "file": "alpha.py"}]


def test_runner_resets_and_returns_one_action(tmp_path):
    path = write_strategy(
        tmp_path,
        "valid",
        """
        class Strategy:
            def reset(self, game_info):
                self.x = game_info["start"][0] + 25
            def next_action(self, observation):
                return {"type": "move", "x": self.x, "y": observation["position"][1]}
        """,
    )
    runner = StrategyRunner(path, timeout_s=1)
    try:
        runner.reset({"start": [0, 0]})
        assert runner.next_action({"position": [0, 10]}) == {
            "type": "move",
            "x": 25,
            "y": 10,
        }
    finally:
        runner.close()


def test_runner_reports_strategy_exception_without_crashing_parent(tmp_path):
    path = write_strategy(
        tmp_path,
        "broken",
        """
        class Strategy:
            def reset(self, game_info): pass
            def next_action(self, observation): raise RuntimeError("boom")
        """,
    )
    runner = StrategyRunner(path, timeout_s=1)
    try:
        runner.reset({})
        with pytest.raises(StrategyError, match="boom"):
            runner.next_action({})
    finally:
        runner.close()


def test_runner_timeout_terminates_worker(tmp_path):
    path = write_strategy(
        tmp_path,
        "slow",
        """
        import time
        class Strategy:
            def reset(self, game_info): pass
            def next_action(self, observation):
                time.sleep(5)
                return {"type": "move", "x": 0, "y": 0}
        """,
    )
    runner = StrategyRunner(path, timeout_s=0.05)
    runner.reset({})
    with pytest.raises(StrategyError, match="timed out"):
        runner.next_action({})
    assert runner.process.poll() is not None


def test_controller_never_sends_showcase_truth_to_strategy(tmp_path):
    write_strategy(
        tmp_path,
        "privacy",
        """
        class Strategy:
            def reset(self, game_info): pass
            def next_action(self, observation):
                if "truth" in observation or "sources" in observation:
                    return {"type": "move", "x": "LEAK", "y": 0}
                return {"type": "move", "x": 10, "y": 0}
        """,
    )
    store = SessionStore(tmp_path / "sessions")
    managed = store.create(mode=GameMode.SHOWCASE, seed=1, source_count=10)
    controller = StrategyController(tmp_path, timeout_s=1)
    try:
        controller.start(managed, "privacy")
        state = controller.step(managed)
        assert state["position"] == [10.0, 0.0]
        assert managed.actor == "strategy"
        assert managed.strategy_name == "privacy"
    finally:
        controller.close_all()


def test_controller_can_switch_strategy_without_reloading_session_store(tmp_path):
    for name, x in (("first", 10), ("second", 20)):
        write_strategy(
            tmp_path,
            name,
            f"""
            class Strategy:
                def reset(self, game_info): pass
                def next_action(self, observation):
                    return {{"type": "move", "x": {x}, "y": 0}}
            """,
        )
    managed = SessionStore(tmp_path / "sessions").create(
        mode=GameMode.OMNIDIRECTIONAL, seed=3, source_count=10
    )
    controller = StrategyController(tmp_path, timeout_s=1)
    try:
        controller.start(managed, "first")
        assert controller.step(managed)["position"] == [10.0, 0.0]
        controller.start(managed, "second")
        assert controller.step(managed)["position"] == [20.0, 0.0]
    finally:
        controller.close_all()
