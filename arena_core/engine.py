"""Deterministic, serializable implementation of the Arena rules."""

from __future__ import annotations

import hashlib
import json
import math
import random
import time
import uuid
from typing import Any

from .geometry import (
    circle_polygon,
    enclosing_circle,
    intersect_bearing_wedge,
    intersect_convex,
    json_polygon,
)
from .models import ChannelKnowledge, GameMode, MeasureKind, Source


class ActionError(ValueError):
    """Raised when an action is malformed and therefore has no cost."""


class GameSession:
    TARGET_RADIUS_M = 1800.0
    MIN_RECEPTION_RADIUS_M = 1000.0
    MAX_RECEPTION_RADIUS_M = 1500.0
    NEAR_RADIUS_M = 5.0
    CLEAR_RADIUS_M = 20.0
    MOVE_SPEED_MPS = 5.0
    MEASURE_COST_S = 5.0
    SWITCH_COST_S = 1.0
    CLEAR_SUCCESS_COST_S = 5.0
    CLEAR_FAILURE_COST_S = 3.0
    DIRECTION_ERROR_DEG = 1.0
    DIRECTIONAL_PROBABILITY = 6 / 16

    def __init__(
        self,
        *,
        session_id: str,
        seed: int,
        mode: GameMode,
        sources: dict[int, Source],
        position: tuple[float, float] = (0.0, 0.0),
        current_channel: int = 1,
    ) -> None:
        self.session_id = session_id
        self.seed = int(seed)
        self.mode = GameMode(mode)
        self.sources = dict(sorted(sources.items()))
        self.position = (float(position[0]), float(position[1]))
        self.current_channel = int(current_channel)
        self.virtual_time_s = 0.0
        self.distance_m = 0.0
        self.events: list[dict[str, Any]] = []
        self.cleared_channels: set[int] = set()
        self.knowledge = {channel: ChannelKnowledge(channel) for channel in range(1, 21)}
        self.assisted = False
        self.source_total_revealed = False
        self.created_wall_time = time.time()

    @property
    def source_count(self) -> int:
        return len(self.sources)

    @property
    def directional_probability(self) -> float:
        return self.DIRECTIONAL_PROBABILITY

    @property
    def directional_count(self) -> int:
        return sum(source.direction_deg is not None for source in self.sources.values())

    @property
    def omnidirectional_count(self) -> int:
        return self.source_count - self.directional_count

    @property
    def completed(self) -> bool:
        return len(self.cleared_channels) == self.source_count

    @classmethod
    def new(
        cls,
        *,
        seed: int,
        mode: GameMode,
        source_count: int | None = None,
    ) -> "GameSession":
        rng = random.Random(int(seed))
        count = rng.randint(10, 16) if source_count is None else int(source_count)
        if not 1 <= count <= 20:
            raise ValueError("source_count must be between 1 and 20")
        channels = rng.sample(range(1, 21), count)

        directional_flags = [False] * count
        if GameMode(mode) in (GameMode.MIXED_DIRECTIONAL, GameMode.SHOWCASE):
            while not any(directional_flags):
                directional_flags = [
                    rng.random() < cls.DIRECTIONAL_PROBABILITY for _ in range(count)
                ]

        sources: dict[int, Source] = {}
        for channel, directional in zip(channels, directional_flags):
            angle = rng.uniform(0.0, 2.0 * math.pi)
            radius_from_origin = cls.TARGET_RADIUS_M * math.sqrt(rng.random())
            direction = rng.uniform(0.0, 360.0) if directional else None
            sources[channel] = Source(
                channel=channel,
                x=radius_from_origin * math.cos(angle),
                y=radius_from_origin * math.sin(angle),
                reception_radius=rng.uniform(
                    cls.MIN_RECEPTION_RADIUS_M, cls.MAX_RECEPTION_RADIUS_M
                ),
                direction_deg=direction,
            )
        return cls(
            session_id=uuid.uuid4().hex,
            seed=int(seed),
            mode=GameMode(mode),
            sources=sources,
        )

    @classmethod
    def for_test(
        cls,
        *,
        mode: GameMode,
        sources: dict[int, dict[str, Any]],
        seed: int = 1,
        position: tuple[float, float] = (0.0, 0.0),
    ) -> "GameSession":
        parsed = {
            int(channel): Source(
                channel=int(channel),
                x=float(values["x"]),
                y=float(values["y"]),
                reception_radius=float(values["radius"]),
                direction_deg=(
                    None
                    if values.get("direction_deg") is None
                    else float(values["direction_deg"])
                ),
            )
            for channel, values in sources.items()
        }
        return cls(
            session_id=f"test-{seed}",
            seed=seed,
            mode=mode,
            sources=parsed,
            position=position,
        )

    @staticmethod
    def _finite_number(value: Any) -> bool:
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )

    @classmethod
    def _validate_channel(cls, value: Any) -> int:
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 20:
            raise ActionError("channel must be an integer from 1 to 20")
        return value

    @classmethod
    def _validate_coordinate(cls, value: Any) -> float:
        if not cls._finite_number(value) or abs(float(value)) > 2_000_000:
            raise ActionError("coordinate must be a finite number within bounds")
        return float(value)

    def _bearing_error(self, channel: int, position: tuple[float, float]) -> float:
        material = (
            f"{self.seed}:{channel}:{position[0].hex()}:{position[1].hex()}".encode()
        )
        fraction = int.from_bytes(hashlib.sha256(material).digest()[:8], "big") / (
            2**64 - 1
        )
        return 2.0 * fraction - 1.0

    def _measure_truth(self, channel: int) -> tuple[MeasureKind, float | None]:
        source = self.sources.get(channel)
        if source is None or channel in self.cleared_channels:
            return MeasureKind.NO_SIGNAL, None

        dx = self.position[0] - source.x
        dy = self.position[1] - source.y
        distance = math.hypot(dx, dy)
        visible = source.direction_deg is None
        if source.direction_deg is not None:
            phi = math.radians(source.direction_deg)
            visible = dx * math.cos(phi) + dy * math.sin(phi) >= -1e-9
        if distance > source.reception_radius + 1e-9 or not visible:
            return MeasureKind.NO_SIGNAL, None
        if distance <= self.NEAR_RADIUS_M + 1e-9:
            return MeasureKind.NEAR, None

        true_bearing = math.degrees(math.atan2(source.y - self.position[1], source.x - self.position[0]))
        observed = (true_bearing + self._bearing_error(channel, self.position)) % 360.0
        return MeasureKind.DIRECTION, round(observed, 2)

    def _base_possible_polygon(self, knowledge: ChannelKnowledge) -> list[tuple[float, float]]:
        if knowledge.possible_polygons:
            return [tuple(point) for point in knowledge.possible_polygons[0]]
        return circle_polygon(0.0, 0.0, self.TARGET_RADIUS_M)

    def _update_knowledge(
        self, channel: int, result: MeasureKind, bearing_deg: float | None
    ) -> None:
        knowledge = self.knowledge[channel]
        measurement: dict[str, Any] = {
            "x": self.position[0],
            "y": self.position[1],
            "result": result.value,
        }
        if bearing_deg is not None:
            measurement["bearing_deg"] = bearing_deg
        knowledge.measurements.append(measurement)

        if result is MeasureKind.NO_SIGNAL:
            knowledge.negative_observations.append(
                {"x": self.position[0], "y": self.position[1]}
            )
            knowledge.excluded_disks.append(
                {
                    "x": self.position[0],
                    "y": self.position[1],
                    "radius": self.MIN_RECEPTION_RADIUS_M,
                }
            )
            if knowledge.status == "untested":
                knowledge.status = "no_signal"
            return

        knowledge.status = "detected"
        possible = self._base_possible_polygon(knowledge)
        if result is MeasureKind.NEAR:
            near_disk = {
                "x": self.position[0],
                "y": self.position[1],
                "radius": self.NEAR_RADIUS_M,
            }
            knowledge.near_disks = [near_disk]
            possible = intersect_convex(
                possible,
                circle_polygon(self.position[0], self.position[1], self.NEAR_RADIUS_M),
            )
        else:
            possible = intersect_bearing_wedge(
                possible,
                self.position,
                float(bearing_deg),
                self.DIRECTION_ERROR_DEG,
            )
            possible = intersect_convex(
                possible,
                circle_polygon(
                    self.position[0], self.position[1], self.MAX_RECEPTION_RADIUS_M
                ),
            )
        knowledge.possible_polygons = [json_polygon(possible)] if possible else []
        if possible:
            center, radius = enclosing_circle(possible)
            knowledge.possible_center = [round(center[0], 6), round(center[1], 6)]
            knowledge.possible_radius_m = round(radius, 6)
        else:
            knowledge.possible_center = None
            knowledge.possible_radius_m = None

    def apply(self, action: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(action, dict):
            raise ActionError("action must be an object")
        action_type = action.get("type")
        if action_type == "move":
            x = self._validate_coordinate(action.get("x"))
            y = self._validate_coordinate(action.get("y"))
            distance = math.hypot(x - self.position[0], y - self.position[1])
            cost = distance / self.MOVE_SPEED_MPS
            self.position = (x, y)
            self.distance_m += distance
            self.virtual_time_s += cost
            result = {
                "type": "move",
                "x": x,
                "y": y,
                "distance_m": distance,
                "cost_s": cost,
            }
        elif action_type == "measure":
            channel = self._validate_channel(action.get("channel"))
            switched = channel != self.current_channel
            result_kind, bearing_deg = self._measure_truth(channel)
            cost = self.MEASURE_COST_S + (self.SWITCH_COST_S if switched else 0.0)
            self.current_channel = channel
            self.virtual_time_s += cost
            self._update_knowledge(channel, result_kind, bearing_deg)
            result = {
                "type": "measure",
                "channel": channel,
                "result": result_kind.value,
                "switched": switched,
                "cost_s": cost,
            }
            if bearing_deg is not None:
                result["bearing_deg"] = bearing_deg
        elif action_type == "clear":
            channel = self._validate_channel(action.get("channel"))
            source = self.sources.get(channel)
            success = bool(
                source is not None
                and channel not in self.cleared_channels
                and math.hypot(self.position[0] - source.x, self.position[1] - source.y)
                <= self.CLEAR_RADIUS_M + 1e-9
            )
            cost = self.CLEAR_SUCCESS_COST_S if success else self.CLEAR_FAILURE_COST_S
            self.virtual_time_s += cost
            if success:
                self.cleared_channels.add(channel)
                self.knowledge[channel].status = "cleared"
                self.knowledge[channel].cleared_position = [
                    self.position[0],
                    self.position[1],
                ]
            result = {
                "type": "clear",
                "channel": channel,
                "success": success,
                "cost_s": cost,
            }
        else:
            raise ActionError("unknown action type")

        event = {
            "index": len(self.events) + 1,
            **result,
            "position": [self.position[0], self.position[1]],
            "virtual_time_s": self.virtual_time_s,
        }
        self.events.append(event)
        return dict(result)

    def reveal_total(self) -> int:
        self.assisted = True
        self.source_total_revealed = True
        return self.source_count

    def public_state(self) -> dict[str, Any]:
        reveal_counts = self.source_total_revealed or self.completed
        state: dict[str, Any] = {
            "session_id": self.session_id,
            "mode": self.mode.value,
            "position": [self.position[0], self.position[1]],
            "current_channel": self.current_channel,
            "virtual_time_s": self.virtual_time_s,
            "distance_m": self.distance_m,
            "cleared_count": len(self.cleared_channels),
            "source_count": self.source_count if reveal_counts else None,
            "completed": self.completed,
            "assisted": self.assisted,
            "channels": [
                self.knowledge[channel].public_dict() for channel in range(1, 21)
            ],
            "events": self.events,
        }
        if reveal_counts:
            state["directional_count"] = self.directional_count
            state["omnidirectional_count"] = self.omnidirectional_count
        return state

    def showcase_truth(self) -> list[dict[str, Any]]:
        if self.mode is not GameMode.SHOWCASE:
            raise ActionError("truth is available only in showcase mode")
        return [source.to_dict() for source in self.sources.values()]

    def truth_digest(self) -> str:
        payload = [source.to_dict() for source in self.sources.values()]
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(raw.encode()).hexdigest()

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "session_id": self.session_id,
            "seed": self.seed,
            "mode": self.mode.value,
            "sources": [source.to_dict() for source in self.sources.values()],
            "position": list(self.position),
            "current_channel": self.current_channel,
            "virtual_time_s": self.virtual_time_s,
            "distance_m": self.distance_m,
            "events": self.events,
            "cleared_channels": sorted(self.cleared_channels),
            "knowledge": [self.knowledge[channel].to_dict() for channel in range(1, 21)],
            "assisted": self.assisted,
            "source_total_revealed": self.source_total_revealed,
            "created_wall_time": self.created_wall_time,
        }

    @classmethod
    def from_json(cls, raw: str) -> "GameSession":
        payload = json.loads(raw)
        if payload.get("schema_version") != 1:
            raise ValueError("unsupported session schema")
        sources = {
            int(item["channel"]): Source.from_dict(item) for item in payload["sources"]
        }
        game = cls(
            session_id=str(payload["session_id"]),
            seed=int(payload["seed"]),
            mode=GameMode(payload["mode"]),
            sources=sources,
            position=(float(payload["position"][0]), float(payload["position"][1])),
            current_channel=int(payload["current_channel"]),
        )
        game.virtual_time_s = float(payload["virtual_time_s"])
        game.distance_m = float(payload["distance_m"])
        game.events = list(payload["events"])
        game.cleared_channels = {int(value) for value in payload["cleared_channels"]}
        game.knowledge = {
            int(item["channel"]): ChannelKnowledge.from_dict(item)
            for item in payload["knowledge"]
        }
        game.assisted = bool(payload["assisted"])
        game.source_total_revealed = bool(payload["source_total_revealed"])
        game.created_wall_time = float(payload["created_wall_time"])
        return game
