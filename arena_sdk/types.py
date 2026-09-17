"""Stable public type aliases used by strategy authors."""

from __future__ import annotations

from typing import Any, TypedDict


class GameInfo(TypedDict):
    mode: str
    start: list[float]
    channel_count: int
    rules: dict[str, float]


class Action(TypedDict, total=False):
    type: str
    x: float
    y: float
    channel: int


Observation = dict[str, Any]
