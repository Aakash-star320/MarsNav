import math

import pytest

from app.analyzer.discovery.mars_geometry import (
    MARS_MEAN_RADIUS_M,
    bounds_area_m2,
    from_local_xy_m,
    haversine_m,
    to_local_xy_m,
    wrap_longitude_deg,
)
from app.analyzer.discovery.region_planner import (
    RegionPlanningError,
    expand_region,
    plan_analyze_region,
    plan_mission_region,
    plan_route_region,
)
from app.schemas import BoundingBox, LonLat


def ll(lat: float, lon: float) -> LonLat:
    return LonLat(latitude_deg=lat, longitude_deg_east=lon)


def test_longitude_wrapping() -> None:
    assert wrap_longitude_deg(190) == -170
    assert wrap_longitude_deg(-180) == -180
    assert wrap_longitude_deg(180) == -180
    assert wrap_longitude_deg(360) == 0


def test_haversine_uses_mars_radius() -> None:
    quarter = haversine_m(ll(0, 0), ll(0, 90))
    assert quarter == pytest.approx(math.pi / 2 * MARS_MEAN_RADIUS_M)
    assert haversine_m(ll(0, 179), ll(0, -179)) == pytest.approx(math.radians(2) * MARS_MEAN_RADIUS_M)


def test_local_xy_round_trip() -> None:
    origin = ll(18.4, 77.4)
    p = from_local_xy_m(origin, 1234.0, -987.0)
    x, y = to_local_xy_m(origin, p)
    assert (x, y) == (pytest.approx(1234.0), pytest.approx(-987.0))


def test_route_buffer_for_four_km_separation_is_two_km_each_side() -> None:
    a = ll(0.0, 10.0)
    b = from_local_xy_m(a, 4000.0, 0.0)
    plan = plan_route_region([a, b])
    assert plan.buffer_m == pytest.approx(2000.0, rel=1e-3)
    x_min, _ = to_local_xy_m(a, ll(plan.bounds.south_deg, plan.bounds.west_deg_east))
    assert x_min == pytest.approx(-2000.0, rel=1e-3)


def test_route_minimum_buffer_is_one_km() -> None:
    a = ll(0.0, 10.0)
    assert plan_route_region([a, from_local_xy_m(a, 500.0, 0.0)]).buffer_m == 1000.0


def test_impossible_budget_is_rejected_early() -> None:
    a = ll(0.0, 10.0)
    b = from_local_xy_m(a, 4000.0, 0.0)
    with pytest.raises(RegionPlanningError) as exc:
        plan_route_region([a, b], max_travel_distance_m=3000)
    assert exc.value.code == "impossible_budget"


def test_budget_ellipse_tightens_region_and_keeps_endpoints() -> None:
    a = ll(0.0, 10.0)
    b = from_local_xy_m(a, 10_000.0, 0.0)
    loose = plan_route_region([a, b])
    tight = plan_route_region([a, b], max_travel_distance_m=10_500)
    assert bounds_area_m2(tight.bounds) < bounds_area_m2(loose.bounds)
    for p in (a, b):
        assert tight.bounds.west_deg_east <= p.longitude_deg_east <= tight.bounds.east_deg_east
    assert tight.search_mask is not None


def test_mission_radius_matches_documented_example() -> None:
    # 4 h - 0.5 h reserve - 0.5 h science = 3 h; 2 km/h -> 6 km travel -> 3 km radius.
    start = ll(0.0, 10.0)
    plan = plan_mission_region(
        start, duration_min=240, reserve_min=30, min_examination_min=30, upper_speed_m_per_min=2000 / 60,
    )
    east_m, _ = to_local_xy_m(start, ll(0.0, plan.bounds.east_deg_east))
    assert east_m == pytest.approx(3000.0, rel=1e-3)
    assert plan.travel_bounds == plan.bounds


def test_mission_one_way_uses_full_distance() -> None:
    start = ll(0.0, 10.0)
    plan = plan_mission_region(
        start, duration_min=240, reserve_min=30, min_examination_min=30, upper_speed_m_per_min=2000 / 60,
        return_to_base=False,
    )
    east_m, _ = to_local_xy_m(start, ll(0.0, plan.bounds.east_deg_east))
    assert east_m == pytest.approx(6000.0, rel=1e-3)


def test_mission_max_distance_gives_tighter_bound() -> None:
    start = ll(0.0, 10.0)
    plan = plan_mission_region(
        start, duration_min=240, reserve_min=30, min_examination_min=30, upper_speed_m_per_min=2000 / 60,
        max_distance_m=2000,
    )
    east_m, _ = to_local_xy_m(start, ll(0.0, plan.bounds.east_deg_east))
    assert east_m == pytest.approx(1000.0, rel=1e-3)


def test_mission_without_travel_time_is_rejected() -> None:
    with pytest.raises(RegionPlanningError) as exc:
        plan_mission_region(ll(0, 0), duration_min=60, reserve_min=30, min_examination_min=30, upper_speed_m_per_min=30)
    assert exc.value.code == "insufficient_time"


def test_mission_selection_area_is_intersected_and_disjoint_is_rejected() -> None:
    start = ll(0.0, 10.0)
    args = dict(duration_min=240, reserve_min=30, min_examination_min=30, upper_speed_m_per_min=2000 / 60)
    full = plan_mission_region(start, **args)
    sel = BoundingBox(west_deg_east=10.0, south_deg=-0.001, east_deg_east=10.01, north_deg=0.001)
    clipped = plan_mission_region(start, selection_bounds=sel, **args)
    assert clipped.bounds != clipped.travel_bounds and clipped.travel_bounds == full.bounds
    far = BoundingBox(west_deg_east=100, south_deg=40, east_deg_east=101, north_deg=41)
    with pytest.raises(RegionPlanningError) as exc:
        plan_mission_region(start, selection_bounds=far, **args)
    assert exc.value.code == "no_overlap"


def test_different_return_base_below_direct_distance_is_impossible() -> None:
    start = ll(0.0, 10.0)
    base = from_local_xy_m(start, 10_000.0, 0.0)
    with pytest.raises(RegionPlanningError) as exc:
        plan_mission_region(start, duration_min=240, reserve_min=30, min_examination_min=30,
                            upper_speed_m_per_min=2000 / 60, return_base=base)
    assert exc.value.code == "impossible_budget"


def test_antimeridian_and_polar_regions_are_rejected() -> None:
    with pytest.raises(RegionPlanningError) as exc:
        plan_route_region([ll(0.0, 179.99), ll(0.0, -179.99)])
    assert exc.value.code in {"antimeridian"}
    with pytest.raises(RegionPlanningError) as exc:
        plan_route_region([ll(88.9, 0.0), ll(89.5, 1.0)])
    assert exc.value.code == "polar_region"


def test_expansion_stops_after_three_attempts() -> None:
    plan = plan_analyze_region(BoundingBox(west_deg_east=10, south_deg=0, east_deg_east=10.1, north_deg=0.1))
    p2 = expand_region(plan)
    p3 = expand_region(p2)
    assert (p2.attempt, p3.attempt) == (2, 3)
    assert (p2.bounds.east_deg_east - p2.bounds.west_deg_east) == pytest.approx(0.15)
    with pytest.raises(RegionPlanningError) as exc:
        expand_region(p3)
    assert exc.value.code == "expansion_limit"


def test_expansion_stops_at_hard_boundary() -> None:
    box = BoundingBox(west_deg_east=10, south_deg=0, east_deg_east=10.1, north_deg=0.1)
    plan = plan_analyze_region(box)
    with pytest.raises(RegionPlanningError) as exc:
        expand_region(plan, hard_bounds=box)
    assert exc.value.code == "hard_boundary"


def test_analyze_area_limit() -> None:
    big = BoundingBox(west_deg_east=0, south_deg=0, east_deg_east=1, north_deg=1)
    with pytest.raises(RegionPlanningError) as exc:
        plan_analyze_region(big, max_area_km2=25)
    assert exc.value.code == "area_limit"
