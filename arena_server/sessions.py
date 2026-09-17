"""Persistent game sessions, player timing, intel, and command-level undo."""

from __future__ import annotations

import copy
import json
import secrets
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from arena_core import ActionError, GameMode, GameSession


class ManagedSession:
    SCHEMA_VERSION = 1

    def __init__(
        self,
        game: GameSession,
        *,
        path: Path,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.game = game
        self.path = path
        self.clock = clock
        self.player_elapsed_s = 0.0
        self.running_since: float | None = self.clock()
        self.paused = False
        self.command_history: list[dict[str, Any]] = []
        self.last_command_id: str | None = None
        self.audit: list[dict[str, Any]] = []
        self.intelligence: list[dict[str, Any]] = []
        self.actor = "human"
        self.strategy_name: str | None = None

    @property
    def player_time_s(self) -> float:
        elapsed = self.player_elapsed_s
        if not self.paused and self.running_since is not None:
            elapsed += self.clock() - self.running_since
        return max(0.0, elapsed)

    def _freeze_player_clock(self) -> None:
        if not self.paused and self.running_since is not None:
            self.player_elapsed_s += self.clock() - self.running_since
            self.running_since = None
        self.paused = True

    def pause(self) -> dict[str, Any]:
        if not self.paused:
            self._freeze_player_clock()
            self.audit.append({"type": "pause", "at_player_s": self.player_time_s})
            self.save()
        return self.public_state()

    def resume(self) -> dict[str, Any]:
        if self.game.completed:
            raise ActionError("completed session cannot resume")
        if self.paused:
            self.paused = False
            self.running_since = self.clock()
            self.audit.append({"type": "resume", "at_player_s": self.player_time_s})
            self.save()
        return self.public_state()

    def _snapshot(self) -> dict[str, Any]:
        return {
            "game": copy.deepcopy(self.game.to_dict()),
            "intelligence": copy.deepcopy(self.intelligence),
        }

    def apply_action(
        self, action: dict[str, Any], *, command_id: str | None = None
    ) -> dict[str, Any]:
        if self.paused:
            raise ActionError("session is paused")
        if self.game.completed:
            raise ActionError("session is completed")
        identifier = command_id or uuid.uuid4().hex
        previous_command_id = self.last_command_id
        added_history = identifier != self.last_command_id
        if added_history:
            self.command_history.append(
                {"command_id": identifier, "snapshot": self._snapshot()}
            )
            self.last_command_id = identifier
        try:
            result = self.game.apply(action)
        except Exception:
            if added_history:
                self.command_history.pop()
                self.last_command_id = previous_command_id
            raise
        self.audit.append(
            {
                "type": "action",
                "command_id": identifier,
                "action": copy.deepcopy(action),
                "result": copy.deepcopy(result),
            }
        )
        if self.game.completed:
            self._freeze_player_clock()
        self.save()
        return self.public_state()

    def undo(self) -> dict[str, Any]:
        if self.paused:
            raise ActionError("session is paused")
        if not self.command_history:
            raise ActionError("nothing to undo")
        entry = self.command_history.pop()
        snapshot = entry["snapshot"]
        self.game = GameSession.from_json(json.dumps(snapshot["game"], allow_nan=False))
        self.game.assisted = True
        self.intelligence = copy.deepcopy(snapshot["intelligence"])
        self.last_command_id = None
        self.audit.append(
            {
                "type": "undo",
                "command_id": entry["command_id"],
                "at_player_s": self.player_time_s,
            }
        )
        self.save()
        return self.public_state()

    def get_intel(self, kind: str, channel: int | None = None) -> dict[str, Any]:
        if self.paused:
            raise ActionError("session is paused")
        if kind == "total":
            result = {"kind": "total", "source_count": self.game.reveal_total()}
        elif kind in ("channel_exists", "channel_position"):
            checked = self.game._validate_channel(channel)
            source = self.game.sources.get(checked)
            result = {"kind": kind, "channel": checked, "exists": source is not None}
            if kind == "channel_position" and source is not None:
                result["position"] = [source.x, source.y]
            self.game.assisted = True
        else:
            raise ActionError("unknown intel kind")
        self.intelligence.append(result)
        self.audit.append({"type": "intel", "result": copy.deepcopy(result)})
        self.save()
        return result

    def public_state(self) -> dict[str, Any]:
        state = self.game.public_state()
        state.update(
            {
                "player_time_s": self.player_time_s,
                "paused": self.paused,
                "can_undo": bool(self.command_history),
                "intelligence": copy.deepcopy(self.intelligence),
                "actor": self.actor,
                "strategy_name": self.strategy_name,
            }
        )
        if self.game.mode is GameMode.SHOWCASE:
            state["truth"] = self.game.showcase_truth()
            state["source_count"] = self.game.source_count
            state["directional_count"] = self.game.directional_count
            state["omnidirectional_count"] = self.game.omnidirectional_count
        return state

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "game": self.game.to_dict(),
            "player_elapsed_s": self.player_elapsed_s,
            "running_since": self.running_since,
            "paused": self.paused,
            "command_history": self.command_history,
            "last_command_id": self.last_command_id,
            "audit": self.audit,
            "intelligence": self.intelligence,
            "actor": self.actor,
            "strategy_name": self.strategy_name,
        }

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                self.to_dict(), ensure_ascii=False, allow_nan=False, separators=(",", ":")
            ),
            encoding="utf-8",
        )
        temporary.replace(self.path)

    @classmethod
    def load(
        cls, path: Path, *, clock: Callable[[], float] = time.time
    ) -> "ManagedSession":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("unsupported managed session schema")
        managed = cls(
            GameSession.from_json(json.dumps(payload["game"], allow_nan=False)),
            path=path,
            clock=clock,
        )
        managed.player_elapsed_s = float(payload["player_elapsed_s"])
        managed.running_since = (
            None if payload["running_since"] is None else float(payload["running_since"])
        )
        managed.paused = bool(payload["paused"])
        managed.command_history = list(payload["command_history"])
        managed.last_command_id = payload["last_command_id"]
        managed.audit = list(payload["audit"])
        managed.intelligence = list(payload["intelligence"])
        managed.actor = str(payload.get("actor", "human"))
        managed.strategy_name = payload.get("strategy_name")
        return managed


class SessionStore:
    def __init__(
        self, root: Path, *, clock: Callable[[], float] = time.time
    ) -> None:
        self.root = Path(root)
        self.clock = clock
        self.sessions: dict[str, ManagedSession] = {}

    def create(
        self,
        *,
        mode: GameMode,
        seed: int | None = None,
        source_count: int | None = None,
    ) -> ManagedSession:
        actual_seed = secrets.randbits(63) if seed is None else int(seed)
        game = GameSession.new(seed=actual_seed, mode=mode, source_count=source_count)
        managed = ManagedSession(
            game,
            path=self.root / f"{game.session_id}.json",
            clock=self.clock,
        )
        self.sessions[game.session_id] = managed
        managed.save()
        return managed

    def get(self, session_id: str) -> ManagedSession:
        if session_id in self.sessions:
            return self.sessions[session_id]
        if not session_id or any(character not in "0123456789abcdef-" for character in session_id):
            raise KeyError(session_id)
        path = self.root / f"{session_id}.json"
        if not path.exists():
            raise KeyError(session_id)
        managed = ManagedSession.load(path, clock=self.clock)
        self.sessions[session_id] = managed
        return managed
