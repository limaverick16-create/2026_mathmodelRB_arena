"""Small dependency-free geometry helpers for public map layers."""

from __future__ import annotations

import math
from collections.abc import Iterable

Point = tuple[float, float]


def _contains(circle: tuple[Point, float], point: Point, tolerance: float = 1e-7) -> bool:
    center, radius = circle
    return math.hypot(point[0] - center[0], point[1] - center[1]) <= radius + tolerance


def _diameter_circle(first: Point, second: Point) -> tuple[Point, float]:
    center = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
    return center, math.hypot(first[0] - second[0], first[1] - second[1]) / 2


def _three_point_circle(first: Point, second: Point, third: Point) -> tuple[Point, float]:
    ax, ay = first
    bx, by = second
    cx, cy = third
    denominator = 2 * (ax * (by - cy) + bx * (cy - ay) + cx * (ay - by))
    if abs(denominator) <= 1e-12:
        pairs = ((first, second), (first, third), (second, third))
        return _diameter_circle(*max(pairs, key=lambda pair: math.dist(*pair)))
    a2, b2, c2 = ax * ax + ay * ay, bx * bx + by * by, cx * cx + cy * cy
    center = (
        (a2 * (by - cy) + b2 * (cy - ay) + c2 * (ay - by)) / denominator,
        (a2 * (cx - bx) + b2 * (ax - cx) + c2 * (bx - ax)) / denominator,
    )
    return center, math.dist(center, first)


def enclosing_circle(points: Iterable[Point]) -> tuple[Point, float]:
    """Return the deterministic smallest circle enclosing the supplied points."""
    values = [(float(x), float(y)) for x, y in points]
    if not values:
        return (0.0, 0.0), 0.0
    circle: tuple[Point, float] = (values[0], 0.0)
    for index, point in enumerate(values):
        if _contains(circle, point):
            continue
        circle = (point, 0.0)
        for second_index, second in enumerate(values[:index]):
            if _contains(circle, second):
                continue
            circle = _diameter_circle(point, second)
            for third in values[:second_index]:
                if not _contains(circle, third):
                    circle = _three_point_circle(point, second, third)
    return circle


def circle_polygon(x: float, y: float, radius: float, sides: int = 96) -> list[Point]:
    # Circumscribe the true circle so a display/constraint approximation never
    # removes a physically possible boundary point.
    vertex_radius = radius / math.cos(math.pi / sides)
    return [
        (
            x + vertex_radius * math.cos(2 * math.pi * index / sides),
            y + vertex_radius * math.sin(2 * math.pi * index / sides),
        )
        for index in range(sides)
    ]


def _evaluate(point: Point, half_plane: tuple[float, float, float]) -> float:
    a, b, c = half_plane
    return a * point[0] + b * point[1] + c


def clip_half_plane(
    polygon: Iterable[Point], half_plane: tuple[float, float, float], tolerance: float = 1e-9
) -> list[Point]:
    points = list(polygon)
    if not points:
        return []
    result: list[Point] = []
    previous = points[-1]
    previous_value = _evaluate(previous, half_plane)
    previous_inside = previous_value >= -tolerance
    for current in points:
        current_value = _evaluate(current, half_plane)
        current_inside = current_value >= -tolerance
        if current_inside != previous_inside:
            denominator = previous_value - current_value
            ratio = 0.0 if abs(denominator) <= tolerance else previous_value / denominator
            result.append(
                (
                    previous[0] + ratio * (current[0] - previous[0]),
                    previous[1] + ratio * (current[1] - previous[1]),
                )
            )
        if current_inside:
            result.append(current)
        previous = current
        previous_value = current_value
        previous_inside = current_inside
    return result


def intersect_convex(subject: Iterable[Point], clipper: Iterable[Point]) -> list[Point]:
    """Intersect two counter-clockwise convex polygons."""
    result = list(subject)
    clip_points = list(clipper)
    for start, end in zip(clip_points, clip_points[1:] + clip_points[:1]):
        dx, dy = end[0] - start[0], end[1] - start[1]
        # cross(edge, point-start) >= 0
        half_plane = (-dy, dx, dy * start[0] - dx * start[1])
        result = clip_half_plane(result, half_plane)
        if not result:
            break
    return result


def intersect_bearing_wedge(
    polygon: Iterable[Point], observer: Point, bearing_deg: float, error_deg: float = 1.0
) -> list[Point]:
    low = math.radians(bearing_deg - error_deg)
    high = math.radians(bearing_deg + error_deg)
    sx, sy = observer
    low_direction = (math.cos(low), math.sin(low))
    high_direction = (math.cos(high), math.sin(high))

    # cross(low_direction, point-observer) >= 0
    low_half_plane = (
        -low_direction[1],
        low_direction[0],
        low_direction[1] * sx - low_direction[0] * sy,
    )
    # cross(high_direction, point-observer) <= 0
    high_half_plane = (
        high_direction[1],
        -high_direction[0],
        -high_direction[1] * sx + high_direction[0] * sy,
    )
    return clip_half_plane(clip_half_plane(polygon, low_half_plane), high_half_plane)


def json_polygon(points: Iterable[Point], precision: int = 6) -> list[list[float]]:
    return [[round(x, precision), round(y, precision)] for x, y in points]


def point_in_convex_polygon(
    point: Point, polygon: Iterable[Point], tolerance: float = 1e-4
) -> bool:
    points = list(polygon)
    if len(points) < 3:
        return False
    signs = []
    for start, end in zip(points, points[1:] + points[:1]):
        cross = (end[0] - start[0]) * (point[1] - start[1]) - (
            end[1] - start[1]
        ) * (point[0] - start[0])
        if abs(cross) > tolerance:
            signs.append(cross > 0)
    return not signs or all(sign == signs[0] for sign in signs)
