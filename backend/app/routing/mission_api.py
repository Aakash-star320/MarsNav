"""Mission plans held in memory (bounded, newest wins): after a restart a plan id is unknown and the client plans again."""
from __future__ import annotations

import hashlib
import json
import threading
from collections import OrderedDict
from uuid import UUID

from app.schemas.mission_plan import MissionPlanRequest, MissionPlanResult

from .api_service import RouteNotFound
from .mission_planner import plan_mission_trip
from .service import AnalysisProvider

MAX_STORED = 100


def mission_request_version(request: MissionPlanRequest) -> str:
    blob = json.dumps(request.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return "mission-request/" + hashlib.sha256(blob.encode()).hexdigest()[:16]


class MissionPlanApi:
    def __init__(self, analyses: AnalysisProvider) -> None:
        self._analyses = analyses
        self._lock = threading.Lock()
        self._plans: OrderedDict[UUID, MissionPlanResult] = OrderedDict()

    def plan(self, request: MissionPlanRequest) -> MissionPlanResult:
        result = plan_mission_trip(request, self._analyses, mission_request_version(request))
        with self._lock:
            self._plans[result.id] = result
            while len(self._plans) > MAX_STORED:
                self._plans.popitem(last=False)
        return result

    def get(self, plan_id: UUID) -> MissionPlanResult:
        with self._lock:
            if plan_id not in self._plans:
                raise RouteNotFound(f"mission plan {plan_id} is unknown (plans are kept in memory; plan again)")
            self._plans.move_to_end(plan_id)
            return self._plans[plan_id]
