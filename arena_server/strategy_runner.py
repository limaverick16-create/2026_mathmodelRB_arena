"""Subprocess strategy execution and conversion into normal game actions."""

from __future__ import annotations

import copy
import json
import queue
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from arena_core import ActionError


class StrategyError(RuntimeError):
    """A load, execution, protocol, or timeout error from a strategy."""


def discover_strategies(root: Path) -> list[dict[str, str]]:
    root = Path(root)
    if not root.exists():
        return []
    return [
        {"name": path.stem, "file": path.name}
        for path in sorted(root.glob("*.py"))
        if not path.name.startswith("_")
    ]


class StrategyRunner:
    def __init__(self, path: Path, *, timeout_s: float = 2.0) -> None:
        self.path = Path(path).resolve()
        self.timeout_s = float(timeout_s)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "arena_server.strategy_worker", str(self.path)],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._responses: queue.Queue[str] = queue.Queue()
        self._reader = threading.Thread(target=self._read_stdout, daemon=True)
        self._reader.start()

    def _read_stdout(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self._responses.put(line)

    def _request(self, operation: str, payload: dict[str, Any]) -> Any:
        if self.process.poll() is not None:
            raise StrategyError("strategy worker stopped")
        assert self.process.stdin is not None
        try:
            self.process.stdin.write(
                json.dumps(
                    {"operation": operation, "payload": payload},
                    ensure_ascii=False,
                    allow_nan=False,
                )
                + "\n"
            )
            self.process.stdin.flush()
            raw = self._responses.get(timeout=self.timeout_s)
        except queue.Empty as error:
            self.close()
            raise StrategyError(f"strategy timed out after {self.timeout_s:g}s") from error
        except (BrokenPipeError, OSError, TypeError, ValueError) as error:
            self.close()
            raise StrategyError(f"strategy protocol failed: {error}") from error
        try:
            response = json.loads(raw)
        except json.JSONDecodeError as error:
            self.close()
            raise StrategyError("strategy returned invalid JSON") from error
        if not response.get("ok"):
            raise StrategyError(response.get("error", "strategy failed"))
        return response.get("result")

    def reset(self, game_info: dict[str, Any]) -> None:
        self._request("reset", game_info)

    def next_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        result = self._request("next_action", observation)
        if not isinstance(result, dict):
            raise StrategyError("next_action must return an object")
        return result

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=0.5)


class StrategyController:
    def __init__(self, root: Path, *, timeout_s: float = 2.0) -> None:
        self.root = Path(root).resolve()
        self.timeout_s = timeout_s
        self.runners: dict[str, StrategyRunner] = {}
        self.names: dict[str, str] = {}

    def _path(self, name: str) -> Path:
        if not isinstance(name, str) or not name or Path(name).name != name:
            raise StrategyError("invalid strategy name")
        path = self.root / f"{name}.py"
        if not path.is_file() or path.name.startswith("_"):
            raise StrategyError("strategy not found")
        return path

    @staticmethod
    def _safe_state(managed: Any) -> dict[str, Any]:
        state = copy.deepcopy(managed.public_state())
        state.pop("truth", None)
        state.pop("sources", None)
        return state

    def start(self, managed: Any, name: str) -> dict[str, Any]:
        self.stop(managed.game.session_id)
        runner = StrategyRunner(self._path(name), timeout_s=self.timeout_s)
        game_info = {
            "mode": managed.game.mode.value,
            "start": list(managed.game.position),
            "channel_count": 20,
            "rules": {
                "target_radius_m": managed.game.TARGET_RADIUS_M,
                "move_speed_mps": managed.game.MOVE_SPEED_MPS,
                "clear_radius_m": managed.game.CLEAR_RADIUS_M,
            },
        }
        try:
            runner.reset(game_info)
        except Exception:
            runner.close()
            raise
        session_id = managed.game.session_id
        self.runners[session_id] = runner
        self.names[session_id] = name
        managed.actor = "strategy"
        managed.strategy_name = name
        managed.save()
        return {"name": name, "running": True}

    def step(self, managed: Any) -> dict[str, Any]:
        session_id = managed.game.session_id
        runner = self.runners.get(session_id)
        if runner is None:
            raise StrategyError("no strategy is running")
        action = runner.next_action(self._safe_state(managed))
        try:
            return managed.apply_action(action, command_id=f"strategy-{uuid.uuid4().hex}")
        except ActionError as error:
            raise StrategyError(f"invalid strategy action: {error}") from error

    def stop(self, session_id: str) -> None:
        runner = self.runners.pop(session_id, None)
        self.names.pop(session_id, None)
        if runner is not None:
            runner.close()

    def close_all(self) -> None:
        for session_id in list(self.runners):
            self.stop(session_id)
