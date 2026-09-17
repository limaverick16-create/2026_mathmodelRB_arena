"""Strict JSON helpers for Arena session persistence."""

from __future__ import annotations

import json

from .engine import GameSession


def dumps_session(session: GameSession) -> str:
    return json.dumps(
        session.to_dict(), ensure_ascii=False, allow_nan=False, separators=(",", ":")
    )


def loads_session(raw: str) -> GameSession:
    return GameSession.from_json(raw)
