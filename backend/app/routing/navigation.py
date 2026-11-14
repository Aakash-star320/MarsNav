from __future__ import annotations

from dataclasses import dataclass
from math import atan2, degrees

from .terrain import Cell, GridSpec


@dataclass(frozen=True)
class NavigationInstruction:
    cell: Cell
    bearing_deg: float
    relative_turn_deg: float | None
    turn: str
    text: str

    def to_dict(self) -> dict[str, object]:
        return {
            "row": self.cell[0],
            "col": self.cell[1],
            "bearing_deg": round(self.bearing_deg, 1),
            "relative_turn_deg": None if self.relative_turn_deg is None else round(self.relative_turn_deg, 1),
            "turn": self.turn,
            "text": self.text,
        }


def _bearing(spec: GridSpec, first: Cell, second: Cell) -> float:
    x1, y1 = spec.center_xy_m(first)
    x2, y2 = spec.center_xy_m(second)
    return (degrees(atan2(x2 - x1, y2 - y1)) + 360.0) % 360.0


def _signed_turn(previous: float, following: float) -> float:
    return (following - previous + 540.0) % 360.0 - 180.0


def _turn_name(delta: float) -> str:
    magnitude = abs(delta)
    if magnitude <= 15:
        return "straight"
    if magnitude >= 165:
        return "u_turn"
    side = "right" if delta > 0 else "left"
    if magnitude <= 45:
        return f"slight_{side}"
    if magnitude <= 135:
        return f"turn_{side}"
    return f"sharp_{side}"


def _compass(bearing: float) -> str:
    directions = ("north", "northeast", "east", "southeast", "south", "southwest", "west", "northwest")
    return directions[int((bearing + 22.5) // 45) % 8]


def build_navigation_instructions(spec: GridSpec, path: tuple[Cell, ...] | list[Cell]) -> tuple[NavigationInstruction, ...]:
    """Compress a cell path into start, turn and destination guidance."""
    cells = tuple(path)
    if not cells:
        return ()
    if len(cells) == 1:
        return (NavigationInstruction(cells[0], 0.0, None, "arrived", "You are already at the destination"),)
    if any(not spec.contains(cell) for cell in cells):
        raise ValueError("Navigation path contains a cell outside the grid")

    bearings = [_bearing(spec, cells[index], cells[index + 1]) for index in range(len(cells) - 1)]
    instructions: list[NavigationInstruction] = [
        NavigationInstruction(cells[0], bearings[0], None, "start", f"Start heading {_compass(bearings[0])}")
    ]
    previous = bearings[0]
    for index in range(1, len(bearings)):
        delta = _signed_turn(previous, bearings[index])
        if abs(delta) > 15:
            name = _turn_name(delta)
            degrees_text = f"{abs(delta):.0f} degrees"
            instructions.append(
                NavigationInstruction(
                    cell=cells[index],
                    bearing_deg=bearings[index],
                    relative_turn_deg=delta,
                    turn=name,
                    text=f"{name.replace('_', ' ')} ({degrees_text}); continue {_compass(bearings[index])}",
                )
            )
        previous = bearings[index]

    instructions.append(
        NavigationInstruction(cells[-1], bearings[-1], None, "arrived", "Destination reached")
    )
    return tuple(instructions)
