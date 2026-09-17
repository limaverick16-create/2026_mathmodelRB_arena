"""Bridge blocking callback-based policies to Arena's pull-style strategy API."""

from __future__ import annotations

import math
import queue
import threading
from dataclasses import dataclass
from typing import Any, Callable, Protocol


class BlockingPolicy(Protocol):
    def run(self) -> Any: ...


PolicyFactory = Callable[
    [Callable[[Any, int], tuple[str, float | None]], Callable[[Any, int], bool], dict[str, Any]],
    BlockingPolicy,
]


@dataclass(frozen=True)
class _Failure:
    error: BaseException


@dataclass(frozen=True)
class _Finished:
    result: Any


class BlockingPolicyAdapter:
    """Turn synchronous ``measure``/``clear`` callbacks into one action per step.

    The legacy policy runs in a daemon thread. Each callback yields a move when
    needed, then its requested operation, and blocks until Arena returns the
    corresponding public observation.
    """

    def __init__(self, policy_factory: PolicyFactory) -> None:
        self.policy_factory = policy_factory
        self._actions: queue.Queue[dict[str, Any] | _Failure | _Finished]
        self._observations: queue.Queue[dict[str, Any]]
        self._awaiting_result = False
        self._position = (0.0, 0.0)

    def reset(self, game_info: dict[str, Any]) -> None:
        start = game_info.get("start", [0.0, 0.0])
        self._position = (float(start[0]), float(start[1]))
        self._actions = queue.Queue()
        self._observations = queue.Queue()
        self._awaiting_result = False
        thread = threading.Thread(
            target=self._run_policy,
            args=(dict(game_info),),
            daemon=True,
            name="arena-blocking-policy",
        )
        thread.start()

    def _run_policy(self, game_info: dict[str, Any]) -> None:
        try:
            policy = self.policy_factory(self._measure, self._clear, game_info)
            self._actions.put(_Finished(policy.run()))
        except BaseException as error:
            self._actions.put(_Failure(error))

    @staticmethod
    def _point(value: Any) -> tuple[float, float]:
        if len(value) != 2:
            raise ValueError("policy point must contain x and y")
        x, y = float(value[0]), float(value[1])
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("policy point must be finite")
        return x, y

    def _exchange(self, action: dict[str, Any]) -> dict[str, Any]:
        self._actions.put(action)
        observation = self._observations.get()
        position = observation.get("position", self._position)
        self._position = self._point(position)
        return observation

    def _move_to(self, point: Any) -> None:
        x, y = self._point(point)
        if math.hypot(x - self._position[0], y - self._position[1]) > 1e-9:
            self._exchange({"type": "move", "x": x, "y": y})

    @staticmethod
    def _last_event(observation: dict[str, Any], expected: str) -> dict[str, Any]:
        events = observation.get("events") or []
        if not events or events[-1].get("type") != expected:
            raise RuntimeError(f"Arena did not return a {expected} event")
        return events[-1]

    def _measure(self, point: Any, channel: int) -> tuple[str, float | None]:
        self._move_to(point)
        observation = self._exchange({"type": "measure", "channel": int(channel)})
        event = self._last_event(observation, "measure")
        result = str(event["result"])
        angle = event.get("bearing_deg")
        return result, None if angle is None else math.radians(float(angle))

    def _clear(self, point: Any, channel: int) -> bool:
        self._move_to(point)
        observation = self._exchange({"type": "clear", "channel": int(channel)})
        return bool(self._last_event(observation, "clear")["success"])

    def next_action(self, observation: dict[str, Any]) -> dict[str, Any]:
        if self._awaiting_result:
            self._observations.put(observation)
        item = self._actions.get()
        if isinstance(item, _Failure):
            raise RuntimeError(
                f"blocking policy failed: {type(item.error).__name__}: {item.error}"
            ) from item.error
        if isinstance(item, _Finished):
            raise RuntimeError(f"blocking policy finished: {item.result}")
        self._awaiting_result = True
        return item
