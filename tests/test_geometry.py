import math

import pytest

from arena_core import GameMode, GameSession
from arena_core.geometry import enclosing_circle, point_in_convex_polygon


def channel(state, number):
    return next(item for item in state["channels"] if item["channel"] == number)


def test_enclosing_circle_reports_center_and_radius():
    center, radius = enclosing_circle([(-1, -1), (1, -1), (1, 1), (-1, 1)])

    assert center == pytest.approx((0.0, 0.0))
    assert radius == pytest.approx(math.sqrt(2))


def test_enclosing_circle_handles_empty_and_collinear_points():
    assert enclosing_circle([]) == ((0.0, 0.0), 0.0)
    center, radius = enclosing_circle([(-3, 0), (1, 0), (5, 0)])
    assert center == pytest.approx((1.0, 0.0))
    assert radius == pytest.approx(4.0)


def test_direction_measurement_adds_possible_polygon():
    game = GameSession.for_test(
        mode=GameMode.OMNIDIRECTIONAL,
        sources={4: {"x": 500.0, "y": 0.0, "radius": 1000.0}},
    )
    game.apply({"type": "measure", "channel": 4})

    layer = channel(game.public_state(), 4)["layer"]
    assert layer["possible_polygons"]
    assert layer["negative_observations"] == []
    possible_region = channel(game.public_state(), 4)["possible_region"]
    assert set(possible_region) == {"center", "radius_m"}
    assert possible_region["radius_m"] > 0


def test_omnidirectional_no_signal_adds_strict_exclusion_disk():
    game = GameSession.for_test(
        mode=GameMode.OMNIDIRECTIONAL,
        sources={4: {"x": 1200.0, "y": 0.0, "radius": 1100.0}},
    )
    game.apply({"type": "measure", "channel": 4})

    layer = channel(game.public_state(), 4)["layer"]
    assert layer["excluded_disks"] == [{"x": 0.0, "y": 0.0, "radius": 1000.0}]


def test_mixed_mode_no_signal_adds_exclusion_disk_for_channel_layer():
    game = GameSession.for_test(
        mode=GameMode.MIXED_DIRECTIONAL,
        sources={4: {"x": 500.0, "y": 0.0, "radius": 1000.0, "direction_deg": 0.0}},
    )
    game.apply({"type": "measure", "channel": 4})

    layer = channel(game.public_state(), 4)["layer"]
    assert layer["excluded_disks"] == [{"x": 0.0, "y": 0.0, "radius": 1000.0}]
    assert layer["negative_observations"] == [{"x": 0.0, "y": 0.0}]


def test_near_result_replaces_possible_area_with_five_meter_disk():
    game = GameSession.for_test(
        mode=GameMode.OMNIDIRECTIONAL,
        sources={2: {"x": 5.0, "y": 0.0, "radius": 1000.0}},
    )
    game.apply({"type": "measure", "channel": 2})

    layer = channel(game.public_state(), 2)["layer"]
    assert layer["near_disks"] == [{"x": 0.0, "y": 0.0, "radius": 5.0}]
    assert channel(game.public_state(), 2)["possible_region"]["radius_m"] == pytest.approx(
        5.0, abs=0.01
    )


def test_possible_polygon_conservatively_contains_boundary_source():
    angle = math.pi / 96
    source = (1500.0 * math.cos(angle), 1500.0 * math.sin(angle))
    game = GameSession.for_test(
        seed=31,
        mode=GameMode.OMNIDIRECTIONAL,
        sources={6: {"x": source[0], "y": source[1], "radius": 1500.0}},
    )
    game.apply({"type": "measure", "channel": 6})

    polygon = channel(game.public_state(), 6)["layer"]["possible_polygons"][0]
    assert point_in_convex_polygon(source, polygon)
