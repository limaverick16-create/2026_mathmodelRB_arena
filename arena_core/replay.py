"""Portable, hash-protected action replays for local verification."""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from .engine import GameSession
from .models import GameMode


class ReplayError(ValueError):
    """Raised when a replay is malformed or cannot be verified."""


def _canonical(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def _digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _event_action(event: dict[str, Any]) -> dict[str, Any]:
    action_type = event.get("type")
    if action_type == "move":
        return {"type": "move", "x": event["x"], "y": event["y"]}
    if action_type in {"measure", "clear"}:
        return {"type": action_type, "channel": event["channel"]}
    raise ReplayError(f"unsupported replay event: {action_type}")


def build_replay(managed: Any) -> dict[str, Any]:
    """Build a replay without embedding source coordinates or directions."""

    game = managed.game
    payload: dict[str, Any] = {
        "schema_version": 1,
        "mode": game.mode.value,
        "seed": game.seed,
        "source_count": game.source_count,
        "actions": [_event_action(event) for event in game.events],
        "result": {
            "virtual_time_s": game.virtual_time_s,
            "distance_m": game.distance_m,
            "cleared_count": len(game.cleared_channels),
            "completed": game.completed,
            "assisted": game.assisted,
            "event_count": len(game.events),
        },
    }
    payload["payload_sha256"] = _digest(payload)
    return payload


def verify_replay(replay: dict[str, Any]) -> dict[str, Any]:
    """Verify the hash, deterministically re-run actions, and compare results."""

    if not isinstance(replay, dict):
        raise ReplayError("replay must be an object")
    payload = copy.deepcopy(replay)
    claimed_hash = payload.pop("payload_sha256", None)
    if not isinstance(claimed_hash, str) or claimed_hash != _digest(payload):
        raise ReplayError("replay hash mismatch")
    if payload.get("schema_version") != 1:
        raise ReplayError("unsupported replay schema")
    try:
        game = GameSession.new(
            seed=int(payload["seed"]),
            mode=GameMode(payload["mode"]),
        )
        if game.source_count != int(payload["source_count"]):
            raise ReplayError("replay source count mismatch")
        for action in payload["actions"]:
            game.apply(action)
    except ReplayError:
        raise
    except (KeyError, TypeError, ValueError) as error:
        raise ReplayError(f"invalid replay: {error}") from error

    actual = {
        "virtual_time_s": game.virtual_time_s,
        "distance_m": game.distance_m,
        "cleared_count": len(game.cleared_channels),
        "completed": game.completed,
        "assisted": bool(payload["result"].get("assisted")),
        "event_count": len(game.events),
    }
    if actual != payload.get("result"):
        raise ReplayError("replay result mismatch")
    return actual
