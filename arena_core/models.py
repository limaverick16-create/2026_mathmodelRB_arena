"""Data types used by the deterministic Arena rule engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class GameMode(str, Enum):
    OMNIDIRECTIONAL = "omnidirectional"
    MIXED_DIRECTIONAL = "mixed_directional"
    SHOWCASE = "showcase"


class MeasureKind(str, Enum):
    NO_SIGNAL = "no_signal"
    NEAR = "near"
    DIRECTION = "direction"


@dataclass(frozen=True)
class Source:
    channel: int
    x: float
    y: float
    reception_radius: float
    direction_deg: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "Source":
        return cls(
            channel=int(payload["channel"]),
            x=float(payload["x"]),
            y=float(payload["y"]),
            reception_radius=float(payload["reception_radius"]),
            direction_deg=(
                None
                if payload.get("direction_deg") is None
                else float(payload["direction_deg"])
            ),
        )


@dataclass
class ChannelKnowledge:
    channel: int
    status: str = "untested"
    measurements: list[dict[str, Any]] = field(default_factory=list)
    possible_polygons: list[list[list[float]]] = field(default_factory=list)
    excluded_disks: list[dict[str, float]] = field(default_factory=list)
    negative_observations: list[dict[str, float]] = field(default_factory=list)
    near_disks: list[dict[str, float]] = field(default_factory=list)
    possible_center: list[float] | None = None
    possible_radius_m: float | None = None
    cleared_position: list[float] | None = None

    def public_dict(self) -> dict[str, Any]:
        result = {
            "channel": self.channel,
            "status": self.status,
            "measurements": self.measurements,
            "cleared_position": self.cleared_position,
            "layer": {
                "possible_polygons": self.possible_polygons,
                "excluded_disks": self.excluded_disks,
                "negative_observations": self.negative_observations,
                "near_disks": self.near_disks,
            },
        }
        result["possible_region"] = (
            None
            if self.possible_center is None or self.possible_radius_m is None
            else {
                "center": self.possible_center,
                "radius_m": self.possible_radius_m,
            }
        )
        return result

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "ChannelKnowledge":
        return cls(
            channel=int(payload["channel"]),
            status=str(payload.get("status", "untested")),
            measurements=list(payload.get("measurements", [])),
            possible_polygons=list(payload.get("possible_polygons", [])),
            excluded_disks=list(payload.get("excluded_disks", [])),
            negative_observations=list(payload.get("negative_observations", [])),
            near_disks=list(payload.get("near_disks", [])),
            possible_center=payload.get("possible_center"),
            possible_radius_m=payload.get("possible_radius_m"),
            cleared_position=payload.get("cleared_position"),
        )
