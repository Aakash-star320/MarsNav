"""The routing API layer: contract-shaped routes, alternatives, blocked areas, replanning and navigation guidance."""
from dataclasses import replace
from uuid import uuid4

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import routing as routing_routes
from app.routing import api_service, service as routing_service
from app.routing.api_service import RouteConflict, RouteNotFound, RoutingApi, blocked_cells_from_areas, request_version
from app.schemas import (BlockedArea, BoundingBox, LonLat, MissionConstraints, NavigationGuideRequest, NavigationState,
                         ReplanRequest, RoutePreset, RouteRequest)

from test_routing_service import scene  # noqa: F401  (the shared synthetic 6 x 6 analysis)


@pytest.fixture
def api(scene, monkeypatch):  # noqa: F811
    routing, result, provider, request = scene
    state = {"routing": routing}
    load = lambda svc, analysis_id, version: state["routing"]
    monkeypatch.setattr(api_service, "load_routing_terrain", load)          # the API layer and the engine read the same terrain
    monkeypatch.setattr(routing_service, "load_routing_terrain", load)
    return RoutingApi(provider), state, routing, request


def box_around(routing, cells, pad=0.0):
    pts = [routing.cell_center_lonlat(*c) for c in cells]
    return BoundingBox(west_deg_east=min(p.longitude_deg_east for p in pts) - pad, south_deg=min(p.latitude_deg for p in pts) - pad,
                       east_deg_east=max(p.longitude_deg_east for p in pts) + pad, north_deg=max(p.latitude_deg for p in pts) + pad)


def cell_of(routing, p):
    return routing.lonlat_to_cell(p)


# -- the contract shape -----------------------------------------------------------------------------
def test_a_route_comes_back_in_contract_form_with_consistent_numbers(api) -> None:
    svc, _, routing, request = api
    res = svc.plan(request(return_to_base=False))
    assert res.feasible and not res.constraint_conflicts
    assert cell_of(routing, res.geometry[0]) == (1, 1) and cell_of(routing, res.geometry[-1]) == (4, 4)
    assert res.metrics.distance_m == pytest.approx(3 * np.hypot(100, 120))
    prof = res.elevation_profile
    assert len(prof) == len(res.geometry) and prof[0].distance_m == 0 and prof[-1].distance_m == pytest.approx(res.metrics.distance_m)
    assert all(b.distance_m >= a.distance_m for a, b in zip(prof, prof[1:])) and all(p.valid for p in prof)
    assert sum(s.distance_m for s in res.segments) == pytest.approx(res.metrics.distance_m)
    assert res.metrics.estimated_duration_min == pytest.approx(res.metrics.distance_m / 50)
    assert res.provenance.analysis_version == "analysis/1" and "+" in res.provenance.formula_version and res.provenance.heuristic_disclosure
    assert res.request_version.startswith("route-request/") and any("463 m" in w for w in res.warnings)
    assert res.metrics.confidence == "low"


def test_the_same_request_gives_the_same_route(api) -> None:
    svc, _, _, request = api
    a, b = svc.plan(request(return_to_base=False)), svc.plan(request(return_to_base=False))
    assert a.geometry == b.geometry and a.metrics == b.metrics and a.request_version == b.request_version and a.id != b.id


def test_return_to_base_is_part_of_the_planned_route(api) -> None:
    svc, _, routing, request = api
    res = svc.plan(request(return_to_base=True))
    assert res.feasible and cell_of(routing, res.geometry[-1]) == (1, 1)
    assert res.metrics.distance_m == pytest.approx(6 * np.hypot(100, 120))
    assert res.segments[-1].to_location == res.geometry[-1]


def test_impossible_requests_explain_themselves_in_plain_words(api) -> None:
    svc, state, routing, request = api
    slope = routing.slope_deg.copy(); slope[:, 3] = 40                       # a wall of steep ground between start and destination
    state["routing"] = replace(routing, slope_deg=slope)
    res = svc.plan(request(return_to_base=False, max_slope_deg=15))
    assert not res.feasible and res.geometry == [] and res.metrics is None and res.constraint_conflicts
    assert all(d.message and "_" not in d.message for d in res.conflict_details)


# -- alternatives -----------------------------------------------------------------------------------
def test_every_preset_is_offered_even_when_they_take_the_same_cells(api) -> None:
    svc, _, _, request = api
    res = svc.plan(request(return_to_base=False))                           # flat terrain: every preset takes the same cells
    assert len(res.alternatives) == 2 and all(a.geometry == res.geometry for a in res.alternatives)


def test_rough_ground_changes_the_route_and_alternatives_are_distinct(api) -> None:
    svc, state, routing, request = api
    straight = svc.plan(request(return_to_base=False, max_slope_deg=20)).metrics.distance_m
    slope = routing.slope_deg.copy(); rough = routing.roughness_m.copy()
    slope[2:4, 2:4] = 13.0; rough[2:4, 2:4] = 4.0                           # a rough, steep (but passable) patch on the straight line
    state["routing"] = replace(routing, slope_deg=slope, roughness_m=rough)
    res = svc.plan(request(return_to_base=False, max_slope_deg=20))
    cells = [cell_of(routing, p) for p in res.geometry]
    assert res.feasible and not {(2, 2), (2, 3), (3, 2), (3, 3)} & set(cells)          # it goes around the patch
    assert res.metrics.distance_m > straight                                           # at the price of a longer route
    assert res.alternatives, "the other presets choose different cells on this terrain"
    labels = [a.label for a in res.alternatives]
    assert len(set(labels)) == len(labels) and all(a.metrics.distance_m > 0 for a in res.alternatives)
    assert any(a.geometry != res.geometry for a in res.alternatives)
    alt = res.alternatives[0]                                                           # an alternative is a full route: readable, with its own profile, and followable
    assert svc.get(alt.id).geometry == alt.geometry and len(alt.elevation_profile) == len(alt.geometry)
    assert guide(svc, svc.get(alt.id), alt.geometry[0], 0.0).remaining_distance_m == pytest.approx(alt.metrics.distance_m)


# -- waypoints and the base point -----------------------------------------------------------------------
def test_waypoints_are_visited_in_order_and_become_segments(api) -> None:
    svc, _, routing, request = api
    direct = svc.plan(request(return_to_base=False))
    first, second = routing.cell_center_lonlat(1, 4), routing.cell_center_lonlat(4, 1)
    res = svc.plan(request(return_to_base=False).model_copy(update={"waypoints": [first, second]}))
    assert res.feasible
    cells = [cell_of(routing, p) for p in res.geometry]
    assert cells.index((1, 4)) < cells.index((4, 1)) and cells[-1] == (4, 4)                 # in the order given, then the destination
    assert res.metrics.distance_m > direct.metrics.distance_m
    assert len(res.segments) == 3 and res.segments[0].to_location == res.waypoints[0] and len(res.waypoints) == 2
    assert all(s.target_id is None for s in res.segments)                                    # waypoints are not science targets


def test_a_waypoint_outside_the_analysed_area_is_reported(api) -> None:
    svc, _, _, request = api
    res = svc.plan(request(return_to_base=False).model_copy(update={"waypoints": [LonLat(latitude_deg=80, longitude_deg_east=80)]}))
    assert not res.feasible and "waypoint_outside_grid" in res.constraint_conflicts
    assert any("waypoint is outside" in d.message for d in res.conflict_details)


def test_the_return_trip_ends_at_the_base_not_the_start(api) -> None:
    svc, _, routing, request = api
    base = routing.cell_center_lonlat(4, 1)
    res = svc.plan(request(return_to_base=True).model_copy(update={"base": base}))
    assert res.feasible and cell_of(routing, res.geometry[0]) == (1, 1) and cell_of(routing, res.geometry[-1]) == (4, 1)
    assert res.segments[-1].to_location == res.geometry[-1]
    back_to_start = svc.plan(request(return_to_base=True))                                   # no base given: the old behaviour, back to the start
    assert cell_of(routing, back_to_start.geometry[-1]) == (1, 1)


def test_a_base_outside_the_analysed_area_is_reported(api) -> None:
    svc, _, _, request = api
    res = svc.plan(request(return_to_base=True).model_copy(update={"base": LonLat(latitude_deg=80, longitude_deg_east=80)}))
    assert not res.feasible and "base_outside_grid" in res.constraint_conflicts


def test_waypoints_and_base_are_part_of_the_request_version(api) -> None:
    _, _, routing, request = api
    plain = request(return_to_base=True)
    with_wp = plain.model_copy(update={"waypoints": [routing.cell_center_lonlat(1, 4)]})
    with_base = plain.model_copy(update={"base": routing.cell_center_lonlat(4, 1)})
    assert len({request_version(plain), request_version(with_wp), request_version(with_base)}) == 3


# -- blocked areas and replanning ----------------------------------------------------------------------
def test_blocked_area_boxes_become_blocked_cells(api) -> None:
    _, _, routing, _ = api
    cells = blocked_cells_from_areas(routing, [BlockedArea(bounds=box_around(routing, [(2, 2), (3, 3)], pad=1e-9), reason="rock field")])
    assert {(2, 2), (3, 3)} <= cells and (1, 1) not in cells and (4, 4) not in cells


def test_a_planned_route_goes_around_a_blocked_area(api) -> None:
    svc, _, routing, request = api
    open_route = svc.plan(request(return_to_base=False))
    mid = open_route.geometry[len(open_route.geometry) // 2]
    block = BlockedArea(bounds=box_around(routing, [cell_of(routing, mid)], pad=1e-9), reason="obstacle")
    res = svc.plan(request(return_to_base=False).model_copy(update={"blocked_areas": [block]}))
    assert res.feasible and res.geometry != open_route.geometry
    assert all(not (block.bounds.west_deg_east <= p.longitude_deg_east <= block.bounds.east_deg_east and block.bounds.south_deg <= p.latitude_deg <= block.bounds.north_deg) for p in res.geometry)
    assert res.metrics.distance_m >= open_route.metrics.distance_m


def test_a_blocked_start_is_reported_not_ignored(api) -> None:
    svc, _, routing, request = api
    block = BlockedArea(bounds=box_around(routing, [(1, 1)], pad=1e-9), reason="blocked")
    res = svc.plan(request(return_to_base=False).model_copy(update={"blocked_areas": [block]}))
    assert not res.feasible and "start_in_blocked_region" in res.constraint_conflicts
    assert any("start lies inside a blocked area" in d.message for d in res.conflict_details)


def test_replan_keeps_earlier_blocks_adds_new_ones_and_checks_versions(api) -> None:
    svc, _, routing, request = api
    first = svc.plan(request(return_to_base=False))
    mid = first.geometry[len(first.geometry) // 2]
    block = BlockedArea(bounds=box_around(routing, [cell_of(routing, mid)], pad=1e-9), reason="new obstacle")
    again = svc.replan(ReplanRequest(original_route_id=first.id, analysis_id=first.analysis_id, original_request_version=first.request_version, blocked_areas=[block]))
    assert again.feasible and again.id != first.id and again.geometry != first.geometry
    assert svc.get(again.id).geometry == again.geometry                       # the new route is stored too
    with pytest.raises(RouteConflict):
        svc.replan(ReplanRequest(original_route_id=first.id, analysis_id=first.analysis_id, original_request_version="route-request/stale", blocked_areas=[block]))
    with pytest.raises(RouteConflict):
        svc.replan(ReplanRequest(original_route_id=first.id, analysis_id=uuid4(), original_request_version=first.request_version, blocked_areas=[block]))
    with pytest.raises(RouteNotFound):
        svc.replan(ReplanRequest(original_route_id=uuid4(), analysis_id=first.analysis_id, original_request_version=first.request_version, blocked_areas=[block]))


def test_request_version_changes_with_the_request_and_not_otherwise(api) -> None:
    _, _, _, request = api
    a, b = request(return_to_base=False), request(return_to_base=False)
    assert request_version(a) == request_version(b) and request_version(a) != request_version(request(return_to_base=True))


# -- navigation guidance -------------------------------------------------------------------------------
def guide(svc, route, position, heading):
    return svc.guide(NavigationGuideRequest(route_id=route.id, state=NavigationState(position=position, heading_deg_clockwise_from_north=heading)))


def test_guidance_reports_the_next_move_distance_left_and_progress(api) -> None:
    svc, _, _, request = api
    res = svc.plan(request(start=(0, 0), destination=(5, 5), return_to_base=False))
    start, end = res.geometry[0], res.geometry[-1]
    first = guide(svc, res, start, 0.0)
    assert first.remaining_distance_m == pytest.approx(res.metrics.distance_m) and first.distance_to_waypoint_m > 0 and first.message
    assert -180 <= first.relative_turn_deg < 180
    middle = guide(svc, res, res.geometry[len(res.geometry) // 2], 90.0)
    assert 0 < middle.remaining_distance_m < first.remaining_distance_m
    done = guide(svc, res, end, 0.0)
    assert done.remaining_distance_m == 0 and "reached the destination" in done.message


def test_guidance_turns_toward_the_next_point_relative_to_the_current_heading(api) -> None:
    svc, _, _, request = api
    res = svc.plan(request(start=(0, 0), destination=(0, 5), return_to_base=False))        # due east
    here = res.geometry[0]
    east = guide(svc, res, here, 90.0)
    assert abs(east.relative_turn_deg) < 5 and east.message.startswith("Continue east")
    north_facing = guide(svc, res, here, 0.0)
    assert north_facing.relative_turn_deg == pytest.approx(90.0, abs=5) and "Turn right" in north_facing.message
    south_facing = guide(svc, res, here, 180.0)
    assert south_facing.relative_turn_deg == pytest.approx(-90.0, abs=5) and "Turn left" in south_facing.message


def test_guidance_refuses_unknown_and_infeasible_routes(api) -> None:
    svc, state, routing, request = api
    with pytest.raises(RouteNotFound):
        svc.guide(NavigationGuideRequest(route_id=uuid4(), state=NavigationState(position=LonLat(latitude_deg=20, longitude_deg_east=10), heading_deg_clockwise_from_north=0)))
    bad = svc.plan(request(return_to_base=False).model_copy(update={"blocked_areas": [BlockedArea(bounds=box_around(routing, [(1, 1)], pad=1e-9), reason="x")]}))
    with pytest.raises(RouteConflict):
        guide(svc, bad, LonLat(latitude_deg=20, longitude_deg_east=10), 0.0)


# -- the HTTP layer ------------------------------------------------------------------------------------
def client_for(svc):
    app = FastAPI()
    app.include_router(routing_routes.router, prefix="/api/v1")
    app.dependency_overrides[routing_routes.get_routing] = lambda: svc
    return TestClient(app)


def test_endpoints_plan_replan_read_and_guide(api) -> None:
    svc, _, routing, request = api
    c = client_for(svc)
    body = request(return_to_base=False).model_dump(mode="json")
    r = c.post("/api/v1/routes", json=body)
    assert r.status_code == 200 and r.json()["feasible"] and len(r.json()["geometry"]) >= 2
    rid, ver = r.json()["id"], r.json()["request_version"]
    assert c.get(f"/api/v1/routes/{rid}").json()["id"] == rid
    mid = r.json()["geometry"][len(r.json()["geometry"]) // 2]
    block = {"bounds": box_around(routing, [cell_of(routing, LonLat(**mid))], pad=1e-9).model_dump(), "reason": "obstacle"}
    rp = {"original_route_id": rid, "analysis_id": r.json()["analysis_id"], "original_request_version": ver, "blocked_areas": [block]}
    assert c.post(f"/api/v1/routes/{rid}/replan", json=rp).json()["feasible"]
    assert c.post(f"/api/v1/routes/{uuid4()}/replan", json=rp).status_code == 422                 # path id must match the body
    assert c.post(f"/api/v1/routes/{rid}/replan", json={**rp, "original_request_version": "stale"}).status_code == 409
    g = c.post("/api/v1/navigation/guide", json={"route_id": rid, "state": {"position": r.json()["geometry"][0], "heading_deg_clockwise_from_north": 0}})
    assert g.status_code == 200 and g.json()["message"]
    assert c.get(f"/api/v1/routes/{uuid4()}").status_code == 404
    assert c.post("/api/v1/routes", json={"nonsense": 1}).status_code == 422


def test_the_placeholder_501_routes_are_gone() -> None:
    from app.main import app
    c = TestClient(app)
    r = c.post("/api/v1/navigation/guide", json={"route_id": str(uuid4()), "state": {"position": {"latitude_deg": 1, "longitude_deg_east": 1}, "heading_deg_clockwise_from_north": 0}})
    assert r.status_code == 404                                              # a real "unknown route", not "Contract scaffold" (501)
