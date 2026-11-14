from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Literal
from types import MappingProxyType

from .terrain import Cell, TerrainModel

UnknownPolicy = Literal["block", "penalize"]
HazardPolicy = Literal["block", "penalize"]


@dataclass(frozen=True)
class CostPreferences:
    slope_weight: float = 0.40
    roughness_weight: float = 0.30
    hazard_weight: float = 0.20
    unknown_weight: float = 0.10
    slope_scale_deg: float = 30.0
    roughness_scale_m: float = 5.0
    risk_multiplier: float = 5.0
    unknown_policy: UnknownPolicy = "block"
    hazard_policy: HazardPolicy = "block"

    def normalized_weights(self) -> dict[str, float]:
        values = {
            "slope": self.slope_weight,
            "roughness": self.roughness_weight,
            "hazard": self.hazard_weight,
            "unknown": self.unknown_weight,
        }
        if any(not isfinite(v) or v < 0 for v in values.values()):
            raise ValueError("Preference weights must be finite and non-negative")
        total = sum(values.values())
        if total <= 0:
            raise ValueError("At least one preference weight must be positive")
        if self.slope_scale_deg <= 0 or self.roughness_scale_m <= 0 or self.risk_multiplier < 0:
            raise ValueError("Cost scales must be positive and risk_multiplier non-negative")
        return {key: value / total for key, value in values.items()}


# Named, reproducible starting profiles. These are prototype assumptions, not
# scientifically validated rover safety thresholds. Restore the UI/API to the
# exact DEFAULT_PREFERENCES object when the user selects "restore defaults".
DEFAULT_PREFERENCES = CostPreferences()
PREFERENCE_PRESETS = MappingProxyType({
    "balanced": DEFAULT_PREFERENCES,
    "slope_cautious": CostPreferences(
        slope_weight=0.70, roughness_weight=0.15, hazard_weight=0.10, unknown_weight=0.05
    ),
    "roughness_cautious": CostPreferences(
        slope_weight=0.15, roughness_weight=0.70, hazard_weight=0.10, unknown_weight=0.05
    ),
    "hazard_cautious": CostPreferences(
        slope_weight=0.20, roughness_weight=0.15, hazard_weight=0.60, unknown_weight=0.05
    ),
})


def get_preference_preset(name: str = "balanced") -> CostPreferences:
    """Return a named immutable profile; balanced is the default restore target."""
    try:
        return PREFERENCE_PRESETS[name]
    except KeyError as exc:
        raise ValueError(
            f"Unknown preference preset {name!r}; choose one of {', '.join(PREFERENCE_PRESETS)}"
        ) from exc


@dataclass(frozen=True)
class TraversalLimits:
    max_slope_deg: float | None = None
    max_roughness_m: float | None = None
    block_hazards: bool = True
    block_unknown: bool = True
    max_cost_per_m: float | None = None
    max_route_distance_m: float | None = None

    def __post_init__(self) -> None:
        for name in ("max_slope_deg", "max_roughness_m", "max_cost_per_m", "max_route_distance_m"):
            value = getattr(self, name)
            if value is not None and (not isfinite(value) or value < 0):
                raise ValueError(f"{name} must be a finite non-negative number")


@dataclass(frozen=True)
class CellCost:
    traversable: bool
    cost_per_m: float
    blocked_reasons: tuple[str, ...]
    risk_components: tuple[tuple[str, float], ...]


@dataclass(frozen=True)
class CostModel:
    terrain: TerrainModel
    cells: tuple[tuple[CellCost, ...], ...]
    normalized_weights: tuple[tuple[str, float], ...]
    formula_version: str = "normalized-risk-cost-v1"

    def at(self, cell: Cell) -> CellCost:
        row, col = cell
        if not self.terrain.grid.spec.contains(cell):
            raise IndexError(f"Cell outside grid: {cell}")
        return self.cells[row][col]

    @property
    def minimum_traversable_cost_per_m(self) -> float:
        values = [item.cost_per_m for row in self.cells for item in row if item.traversable]
        return min(values) if values else 1.0


def build_cost_model(
    terrain: TerrainModel,
    preferences: CostPreferences | None = None,
    limits: TraversalLimits | None = None,
) -> CostModel:
    preferences = preferences or CostPreferences()
    limits = limits or TraversalLimits()
    weights = preferences.normalized_weights()
    result: list[tuple[CellCost, ...]] = []

    for row in terrain.cells:
        cost_row: list[CellCost] = []
        for cell in row:
            reasons = [reason for reason in cell.unknown_reasons if reason == "outside_valid_mask"]
            if cell.unknown and (limits.block_unknown or preferences.unknown_policy == "block"):
                reasons.extend(cell.unknown_reasons)
                reasons.append("unknown_terrain")
            if cell.is_hazard and (limits.block_hazards or preferences.hazard_policy == "block"):
                reasons.append("hazard_present")
            if limits.max_slope_deg is not None:
                if cell.slope_deg is None:
                    reasons.append("slope_limit_cannot_be_verified")
                elif cell.slope_deg > limits.max_slope_deg:
                    reasons.append("max_slope_exceeded")
            if limits.max_roughness_m is not None:
                if cell.roughness_m is None:
                    reasons.append("roughness_limit_cannot_be_verified")
                elif cell.roughness_m > limits.max_roughness_m:
                    reasons.append("max_roughness_exceeded")

            slope_risk = 0.0 if cell.slope_deg is None else min(1.0, max(0.0, cell.slope_deg / preferences.slope_scale_deg))
            roughness_risk = 0.0 if cell.roughness_m is None else min(1.0, max(0.0, cell.roughness_m / preferences.roughness_scale_m))
            hazard_risk = cell.hazard_severity if cell.is_hazard else 0.0
            unknown_risk = 1.0 if cell.unknown else 0.0
            weighted_risk = (
                weights["slope"] * slope_risk
                + weights["roughness"] * roughness_risk
                + weights["hazard"] * hazard_risk
                + weights["unknown"] * unknown_risk
            )
            cost_per_m = 1.0 + preferences.risk_multiplier * weighted_risk
            if limits.max_cost_per_m is not None and cost_per_m > limits.max_cost_per_m:
                reasons.append("max_cell_cost_exceeded")

            cost_row.append(
                CellCost(
                    traversable=not reasons,
                    cost_per_m=max(1.0, cost_per_m),
                    blocked_reasons=tuple(sorted(set(reasons))),
                    risk_components=(
                        ("slope", slope_risk),
                        ("roughness", roughness_risk),
                        ("hazard", hazard_risk),
                        ("unknown", unknown_risk),
                    ),
                )
            )
        result.append(tuple(cost_row))

    return CostModel(
        terrain=terrain,
        cells=tuple(result),
        normalized_weights=tuple(sorted(weights.items())),
    )
