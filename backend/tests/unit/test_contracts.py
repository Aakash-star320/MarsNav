from app.schemas import (
    AssistantCitation,
    AssistantResponse,
    BoundingBox,
    LonLat,
    RouteRequest,
)
import pytest

def test_canonical_coordinate_limits() -> None:
    assert LonLat(latitude_deg=0, longitude_deg_east=-179.9).longitude_deg_east == -179.9
    with pytest.raises(ValueError):
        LonLat(latitude_deg=91, longitude_deg_east=0)

def test_aoi_has_ordered_latitudes() -> None:
    with pytest.raises(ValueError):
        BoundingBox(west_deg_east=0, south_deg=4, east_deg_east=1, north_deg=4)


def test_aoi_rejects_antimeridian_crossing() -> None:
    with pytest.raises(ValueError, match="split antimeridian"):
        BoundingBox(west_deg_east=170, south_deg=-4, east_deg_east=-170, north_deg=4)


def test_route_request_requires_analysis_version() -> None:
    with pytest.raises(ValueError):
        RouteRequest.model_validate({
            "mission_id": "00000000-0000-0000-0000-000000000001",
            "analysis_id": "00000000-0000-0000-0000-000000000002",
            "start": {"latitude_deg": 0, "longitude_deg_east": 0},
            "destination": {"latitude_deg": 1, "longitude_deg_east": 1},
        })


def test_assistant_response_uses_structured_citations() -> None:
    response = AssistantResponse(
        message="Coverage is partial.",
        citations=[AssistantCitation(id="source-1", source_uri="https://example.test/product")],
    )
    assert response.citations[0].source_uri == "https://example.test/product"
