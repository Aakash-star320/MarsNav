"""The mission planner: which science targets fit the budget, in what order, and the way home."""
from dataclasses import replace
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.analyzer.integration.routing_terrain import TerrainAccessError
from app.api.routes import mission_plans as mission_routes
from app.routing import mission_planner, service as routing_service
from app.routing.mission_api import MissionPlanApi
from app.schemas import BlockedArea, BoundingBox, LonLat, MissionConstraints, ScienceTarget
from app.schemas.mission_plan import MissionPlanRequest

from test_routing_service import scene  # noqa: F401  (the shared synthetic 6 x 6 analysis: 100 m x 120 m cells)

SPEED = 50.0                      # metres per minute, the MissionConstraints default


def tid(n: int) -> UUID:
    return UUID(int=n)


@pytest.fixture
def mission(scene, monkeypatch):  # noqa: F811
    routing, result, provider, _ = scene
    state = {"routing": routing}
    load = lambda svc, analysis_id, version: state["routing"]
    monkeypatch.setattr(mission_planner, "load_routing_terrain", load)        # the planner and the engine read the same terrain
    monkeypatch.setattr(routing_service, "load_routing_terrain", load)
    api = MissionPlanApi(provider)

    def targets(*spec):
        """spec: (id number, (row, col), relevance score); targets are placed at cell centres, and only exist in the analysis."""
        result.science_targets = [ScienceTarget(id=tid(n), location=routing.cell_center_lonlat(*cell), title=f"target {n}", objective_category="hydrated_minerals",
                                                relevance_score=score, confidence="low", evidence=[]) for n, cell, score in spec]

    def request(start=(0, 0), base=(0, 0), target_ids=None, blocked_areas=(), **constraints):
        c = {"max_duration_min": 1000.0, "examination_time_per_target_min": 0.0, **constraints}
        return MissionPlanRequest(mission_id=result.mission_id, analysis_id=result.id, analysis_version="analysis/1",
                                  start=routing.cell_center_lonlat(*start), base=routing.cell_center_lonlat(*base),
                                  constraints=MissionConstraints(**c), blocked_areas=list(blocked_areas), target_ids=target_ids)
    return api, state, routing, result, targets, request


def box_around(routing, cells, pad=1e-9):
    pts = [routing.cell_center_lonlat(*c) for c in cells]
    return BoundingBox(west_deg_east=min(p.longitude_deg_east for p in pts) - pad, south_deg=min(p.latitude_deg for p in pts) - pad,
                       east_deg_east=max(p.longitude_deg_east for p in pts) + pad, north_deg=max(p.latitude_deg for p in pts) + pad)


def cell_of(routing, p):
    return routing.lonlat_to_cell(p)


# -- choosing and ordering -----------------------------------------------------------------------------------
def test_targets_are_chosen_by_value_per_minute_not_by_distance_and_visited_in_that_order(mission) -> None:
    api, _, routing, _, targets, request = mission
    targets((1, (0, 2), 0.5), (2, (0, 4), 0.9), (3, (0, 1), 0.05))           # A: 0.125/min, B: 0.1125/min, C (nearest): 0.025/min
    res = api.plan(request())
    assert res.feasible
    assert [s.target_id for s in res.stops] == [tid(1), tid(2), tid(3)]       # the nearest target (3) is NOT first
    assert [s.order for s in res.stops] == [1, 2, 3]
    assert [cell_of(routing, s.leg.geometry[-1]) for s in res.stops] == [(0, 2), (0, 4), (0, 1)]
    assert cell_of(routing, res.stops[0].leg.geometry[0]) == (0, 0)             # the first leg starts at the start
    assert cell_of(routing, res.return_leg.geometry[0]) == (0, 1) and cell_of(routing, res.return_leg.geometry[-1]) == (0, 0)


def test_the_numbers_add_up_and_come_from_the_engines_distances(mission) -> None:
    api, _, _, _, targets, request = mission
    targets((1, (0, 2), 0.5), (2, (0, 4), 0.9))
    res = api.plan(request(examination_time_per_target_min=5.0))
    legs = [s.leg for s in res.stops] + [res.return_leg]
    assert res.totals.distance_m == pytest.approx(sum(l.metrics.distance_m for l in legs)) and res.totals.distance_m == pytest.approx(800)
    assert res.totals.duration_min == pytest.approx(800 / SPEED + 2 * 5.0)
    assert res.totals.reserve_min == pytest.approx(200) and res.totals.budget_min == 1000
    assert res.totals.remaining_min == pytest.approx(1000 - 200 - res.totals.duration_min)
    assert res.totals.science_value == pytest.approx(1.4)
    # with a 5 minute examination the far, valuable target wins (0.9 / 13 min > 0.5 / 9 min), then the near one
    assert [s.target_id for s in res.stops] == [tid(2), tid(1)]
    assert [s.arrival_min for s in res.stops] == pytest.approx([400 / SPEED, 400 / SPEED + 5 + 200 / SPEED])
    for leg in legs:
        prof = leg.elevation_profile
        assert len(prof) == len(leg.geometry) and prof[0].distance_m == 0 and prof[-1].distance_m == pytest.approx(leg.metrics.distance_m)
        assert leg.metrics.estimated_duration_min == pytest.approx(leg.metrics.distance_m / SPEED) and leg.metrics.confidence == "low"
    assert res.stops[0].leg.metrics.science_value == 0.9 and res.return_leg.metrics.science_value is None
    assert res.provenance.formula_version.startswith("mission-greedy/1+") and res.provenance.heuristic_disclosure
    assert any("463 m" in w for w in res.warnings) and res.request_version.startswith("mission-request/")


def test_equal_scores_are_broken_by_target_id_so_the_plan_is_reproducible(mission) -> None:
    api, _, _, _, targets, request = mission
    targets((7, (0, 2), 0.5), (3, (0, 2), 0.5))                               # identical score and distance
    first = api.plan(request())
    assert [s.target_id for s in first.stops][0] == tid(3)
    again = api.plan(request())
    assert [s.target_id for s in again.stops] == [s.target_id for s in first.stops]
    assert [s.leg.geometry for s in again.stops] == [s.leg.geometry for s in first.stops] and again.return_leg.geometry == first.return_leg.geometry
    assert again.request_version == first.request_version and again.id != first.id


# -- budget, reserve and stop limit ----------------------------------------------------------------------------------
def test_the_budget_includes_the_return_the_examination_and_the_reserve(mission) -> None:
    api, _, _, _, targets, request = mission
    targets((1, (0, 5), 0.8))                                                  # 500 m each way = 10 + 10 minutes
    fits = api.plan(request(max_duration_min=25.0, reserve_fraction=0.0, examination_time_per_target_min=5.0))
    assert fits.feasible and fits.totals.remaining_min == pytest.approx(0, abs=1e-9)              # 20 + 5 = 25: exactly the budget
    short = api.plan(request(max_duration_min=24.0, reserve_fraction=0.0, examination_time_per_target_min=5.0))
    assert not short.feasible and "no_target_fits_budget" in short.constraint_conflicts and short.excluded[0].code == "does_not_fit_time_budget"
    reserve = api.plan(request(max_duration_min=25.0, reserve_fraction=0.2, examination_time_per_target_min=5.0))     # 20 min usable, 25 needed
    assert not reserve.feasible and reserve.excluded[0].code == "does_not_fit_time_budget" and reserve.totals.reserve_min == pytest.approx(5)
    assert any("time budget" in d.message or "reached, examined" in d.message for d in short.conflict_details)


def test_a_second_target_that_no_longer_fits_is_left_out_with_a_reason(mission) -> None:
    api, _, _, _, targets, request = mission
    targets((1, (0, 2), 0.9), (2, (0, 5), 0.2))
    res = api.plan(request(max_duration_min=18.0, reserve_fraction=0.0))        # target 1 costs 8 min; target 2 would then need 6 out + 10 back (24 min in all)
    assert [s.target_id for s in res.stops] == [tid(1)]
    assert [(e.target_id, e.code) for e in res.excluded] == [(tid(2), "does_not_fit_time_budget")]
    assert res.excluded[0].message and "_" not in res.excluded[0].message


def test_the_distance_limit_counts_the_way_back_and_the_reserve(mission) -> None:
    api, _, _, _, targets, request = mission
    targets((1, (0, 5), 0.8))
    assert api.plan(request(max_distance_m=1300.0, reserve_fraction=0.2)).feasible                   # 1000 <= 1300 * 0.8 = 1040
    short = api.plan(request(max_distance_m=1200.0, reserve_fraction=0.2))                           # 1000 > 960
    assert not short.feasible and short.excluded[0].code == "exceeds_maximum_distance"


def test_max_target_count_limits_the_stops(mission) -> None:
    api, _, _, _, targets, request = mission
    targets((1, (0, 2), 0.5), (2, (0, 3), 0.4), (3, (0, 4), 0.3))
    res = api.plan(request(max_target_count=1))
    assert len(res.stops) == 1 and res.stops[0].target_id == tid(1)
    assert {e.target_id: e.code for e in res.excluded} == {tid(2): "max_target_count_reached", tid(3): "max_target_count_reached"}
    assert len(api.plan(request(max_target_count=2)).stops) == 2


# -- excluded targets ------------------------------------------------------------------------------------------------
def test_targets_that_cannot_be_visited_are_reported_with_plain_reasons(mission) -> None:
    api, state, routing, result, targets, request = mission
    slope = routing.slope_deg.copy(); slope[3, 3] = 40.0                       # a target on a steep cell
    state["routing"] = replace(routing, slope_deg=slope)
    targets((1, (0, 2), 0.5), (2, (3, 3), 0.9), (3, (2, 5), 0.6), (4, (1, 2), 0.7))
    far = ScienceTarget(id=tid(5), location=LonLat(latitude_deg=80, longitude_deg_east=80), title="far", objective_category="x", relevance_score=0.9, confidence="low", evidence=[])
    result.science_targets = [*result.science_targets, far]
    block = BlockedArea(bounds=box_around(routing, [(2, 5)]), reason="rock field")
    res = api.plan(request(blocked_areas=[block], target_ids=[tid(1), tid(2), tid(3), tid(4), tid(5), tid(99)]))
    codes = {e.target_id: e.code for e in res.excluded}
    assert codes == {tid(2): "leg_slope_exceeds_limit", tid(3): "blocked", tid(5): "outside_grid", tid(99): "unknown_target"}
    assert {s.target_id for s in res.stops} == {tid(1), tid(4)}
    assert all(e.message and "_" not in e.message for e in res.excluded)


def test_a_blocked_area_keeps_the_route_out_of_it(mission) -> None:
    api, _, routing, _, targets, request = mission
    targets((1, (0, 5), 0.8))
    open_plan = api.plan(request())
    block = BlockedArea(bounds=box_around(routing, [(0, 2)]), reason="obstacle")
    plan = api.plan(request(blocked_areas=[block]))
    assert plan.feasible
    b = block.bounds
    inside = lambda p: b.west_deg_east <= p.longitude_deg_east <= b.east_deg_east and b.south_deg <= p.latitude_deg <= b.north_deg
    assert any(inside(p) for p in open_plan.stops[0].leg.geometry)
    assert not any(inside(p) for leg in [plan.stops[0].leg, plan.return_leg] for p in leg.geometry)
    assert plan.totals.distance_m >= open_plan.totals.distance_m


def test_a_wall_of_blocked_cells_makes_the_target_unreachable(mission) -> None:
    api, _, routing, _, targets, request = mission
    targets((1, (0, 5), 0.8))
    wall = BlockedArea(bounds=box_around(routing, [(r, 3) for r in range(6)]), reason="canyon")
    res = api.plan(request(blocked_areas=[wall]))
    assert not res.feasible and res.excluded[0].code == "no_route" and "no_target_fits_budget" in res.constraint_conflicts


def test_a_blocked_start_or_base_is_reported(mission) -> None:
    api, _, routing, _, targets, request = mission
    targets((1, (0, 2), 0.8))
    assert "start_in_blocked_region" in api.plan(request(blocked_areas=[BlockedArea(bounds=box_around(routing, [(0, 0)]), reason="x")])).constraint_conflicts
    assert "base_in_blocked_region" in api.plan(request(start=(1, 1), base=(0, 0), blocked_areas=[BlockedArea(bounds=box_around(routing, [(0, 0)]), reason="x")])).constraint_conflicts


# -- no targets, and nothing invented ------------------------------------------------------------------------------------
def test_an_analysis_without_targets_says_so_and_does_not_claim_there_are_none(mission) -> None:
    api, _, _, _, targets, request = mission
    targets()
    res = api.plan(request())
    assert not res.feasible and res.stops == [] and res.return_leg is None and res.constraint_conflicts == ["no_science_targets"]
    assert "not evidence" in res.conflict_details[0].message


def test_only_targets_of_the_analysis_are_ever_planned(mission) -> None:
    api, _, _, result, targets, request = mission
    targets((1, (0, 2), 0.5))
    res = api.plan(request(target_ids=[tid(1), uuid4(), tid(2)]))
    assert [s.target_id for s in res.stops] == [tid(1)]
    assert {e.code for e in res.excluded} == {"unknown_target"} and len(res.excluded) == 2
    assert {s.target_id for s in res.stops} <= {t.id for t in result.science_targets}
    only_listed = api.plan(request(target_ids=[]))                                # an empty list means "none of them", not "all of them"
    assert not only_listed.feasible and only_listed.stops == []


def test_points_outside_the_grid_are_reported(mission) -> None:
    api, _, _, _, targets, request = mission
    targets((1, (0, 2), 0.5))
    bad = request().model_copy(update={"start": LonLat(latitude_deg=80, longitude_deg_east=80)})
    assert api.plan(bad).constraint_conflicts == ["start_outside_grid"]
    bad = request().model_copy(update={"base": LonLat(latitude_deg=80, longitude_deg_east=80)})
    assert api.plan(bad).constraint_conflicts == ["base_outside_grid"]


def test_a_different_mission_id_is_refused(mission) -> None:
    api, _, _, _, targets, request = mission
    targets((1, (0, 2), 0.5))
    assert api.plan(request().model_copy(update={"mission_id": uuid4()})).constraint_conflicts == ["mission_id_mismatch"]


# -- the HTTP layer ----------------------------------------------------------------------------------------------------
def client_for(api):
    app = FastAPI()
    app.include_router(mission_routes.router, prefix="/api/v1")
    app.dependency_overrides[mission_routes.get_mission_planner] = lambda: api
    return TestClient(app)


def test_endpoints_plan_read_and_reject(mission, monkeypatch) -> None:
    api, _, _, _, targets, request = mission
    targets((1, (0, 2), 0.5), (2, (0, 4), 0.9))
    c = client_for(api)
    body = request().model_dump(mode="json")
    r = c.post("/api/v1/mission-plans", json=body)
    assert r.status_code == 200 and r.json()["feasible"] and [s["order"] for s in r.json()["stops"]] == [1, 2]
    assert set(r.json()) >= {"id", "stops", "return_leg", "totals", "excluded", "warnings", "constraint_conflicts", "conflict_details", "provenance", "request_version"}
    got = c.get(f"/api/v1/mission-plans/{r.json()['id']}")
    assert got.status_code == 200 and got.json() == r.json()
    assert c.get(f"/api/v1/mission-plans/{uuid4()}").status_code == 404
    assert c.post("/api/v1/mission-plans", json={"nonsense": 1}).status_code == 422
    assert c.post("/api/v1/mission-plans", json={**body, "target_ids": ["not-a-uuid"]}).status_code == 422
    def missing(*_):
        raise TerrainAccessError("not_found", "analysis does not exist")
    monkeypatch.setattr(mission_planner, "load_routing_terrain", missing)
    assert c.post("/api/v1/mission-plans", json=body).status_code == 404
    def stale(*_):
        raise TerrainAccessError("version_mismatch", "analysis version differs")
    monkeypatch.setattr(mission_planner, "load_routing_terrain", stale)
    assert c.post("/api/v1/mission-plans", json=body).status_code == 409


def test_the_real_app_serves_the_mission_plan_routes() -> None:
    from app.main import app
    r = TestClient(app).get(f"/api/v1/mission-plans/{uuid4()}")
    assert r.status_code == 404 and "unknown" in r.json()["detail"]
