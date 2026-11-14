from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError

from app.schemas import MissionConstraints, RoutePreset, RouteRequest as ApiRequest, UnknownTerrainPolicy, WeightPreferences
from app.routing.request_adapter import adapt_route_request, apply_duration_limit


def api(*, preset=None, preferences=None, constraints=None):
    return ApiRequest(mission_id=uuid4(), analysis_id=uuid4(), analysis_version="analysis/1",
        start={"latitude_deg": 0, "longitude_deg_east": 0},
        destination={"latitude_deg": 1, "longitude_deg_east": 1}, preset=preset,
        preferences=preferences or WeightPreferences(), constraints=constraints or MissionConstraints())


@pytest.mark.parametrize("preset", list(RoutePreset))
def test_every_preset_maps_to_cost_preferences(preset):
    adapted = adapt_route_request(api(preset=preset), start=(0, 0), goal=(1, 1), base=(0, 0))
    assert sum(adapted.preferences.normalized_weights().values()) == pytest.approx(1)


def test_custom_cost_preferences_override_preset_dimensions():
    adapted = adapt_route_request(api(preset=RoutePreset.safest,
        preferences=WeightPreferences(slope=7, roughness=1, hazard=2)), start=(0, 0), goal=(1, 1))
    assert adapted.preferences.slope_weight == 7
    assert adapted.preferences.roughness_weight == 1
    assert adapted.preferences.hazard_weight == 2


def test_unsupported_preferences_are_reported():
    adapted = adapt_route_request(api(preferences=WeightPreferences(science=5, confidence=4, elevation_gain=3, distance=2)),
                                  start=(0, 0), goal=(1, 1))
    assert any("science" in warning for warning in adapted.capability_warnings)
    assert any("confidence" in warning for warning in adapted.capability_warnings)
    assert any("elevation gain" in warning for warning in adapted.capability_warnings)
    assert any("metric distance" in warning for warning in adapted.capability_warnings)
    assert any("hazard raster" in warning for warning in adapted.capability_warnings)


@pytest.mark.parametrize("policy,blocks", [(UnknownTerrainPolicy.exclude, True), (UnknownTerrainPolicy.penalize, False)])
def test_unknown_terrain_policy(policy, blocks):
    adapted = adapt_route_request(api(constraints=MissionConstraints(unknown_terrain_policy=policy)), start=(0, 0), goal=(1, 1))
    assert adapted.limits.block_unknown is blocks
    assert adapted.preferences.unknown_policy == ("block" if blocks else "penalize")


def test_slope_distance_reserve_and_return_conversion():
    adapted = adapt_route_request(api(constraints=MissionConstraints(max_slope_deg=9, max_distance_m=1000,
        reserve_fraction=.25, return_to_base=True)), start=(2, 3), goal=(5, 6))
    assert adapted.limits.max_slope_deg == 9
    assert adapted.limits.max_route_distance_m == 1000
    assert adapted.request.available_distance_m == 1000
    assert adapted.request.reserve_distance_m == 250
    assert adapted.request.return_to_base and adapted.request.base == (2, 3)


def test_no_return_omits_base_even_if_one_was_provided():
    adapted = adapt_route_request(api(constraints=MissionConstraints(return_to_base=False)), start=(0, 0), goal=(1, 1), base=(9, 9))
    assert not adapted.request.return_to_base and adapted.request.base is None


def test_duration_budget_includes_travel_and_target_examination():
    adapted = adapt_route_request(api(constraints=MissionConstraints(max_duration_min=10,
        traversal_speed_m_per_min=5, examination_time_per_target_min=2, return_to_base=False)),
        start=(0, 0), goal=(1, 1), target_count=2)
    # Minimal outcome shell keeps this pure test independent of terrain search.
    from app.routing.feasibility import RouteOutcome
    outcome = RouteOutcome("ok", ((0, 0), (1, 1)), 40, 40, 40, 0, 0, None, 1, (), (), (), "v1", ())
    infeasible = apply_duration_limit(outcome, adapted)
    assert infeasible.status == "infeasible"
    assert "max_duration_exceeded" in infeasible.conflicts
    assert infeasible.path_cells == () and infeasible.distance_m is None


def test_target_count_validation_and_invalid_conflicting_constraints():
    with pytest.raises(ValueError, match="max_target_count"):
        adapt_route_request(api(constraints=MissionConstraints(max_target_count=1)), start=(0, 0), goal=(1, 1), target_count=2)
    with pytest.raises(ValidationError):
        MissionConstraints(max_slope_deg=0)
    with pytest.raises(ValidationError):
        MissionConstraints(max_distance_m=0, reserve_fraction=1)


def test_required_target_ids_preserved_and_elevation_weight_reported():
    ids = [uuid4(), uuid4()]
    adapted = adapt_route_request(api(preferences=WeightPreferences(elevation_gain=3),
        constraints=MissionConstraints(required_target_ids=ids)), start=(0, 0), goal=(1, 1))
    assert adapted.required_target_ids == tuple(map(str, ids))
    assert any("elevation" in warning for warning in adapted.capability_warnings)
