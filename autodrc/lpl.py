from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


Point = tuple[int, int]


def _is_manhattan(a: Point, b: Point) -> bool:
    return a[0] == b[0] or a[1] == b[1]


@dataclass(frozen=True)
class Polygon:
    layer: str
    points: tuple[Point, ...]

    def validate(self, allow_non_manhattan: bool = False) -> list[str]:
        errors: list[str] = []
        if len(self.points) < 4:
            errors.append("polygon has fewer than 4 points")
            return errors
        if self.points[0] != self.points[-1]:
            errors.append("polygon is not closed")
        if not allow_non_manhattan:
            for idx in range(len(self.points) - 1):
                if not _is_manhattan(self.points[idx], self.points[idx + 1]):
                    errors.append(f"non-manhattan edge at segment {idx}")
        return errors

    def to_dict(self) -> dict[str, object]:
        return {"layer": self.layer, "points": [list(p) for p in self.points]}


def rectangle(layer: str, x: int, y: int, width: int, height: int) -> Polygon:
    if width <= 0 or height <= 0:
        raise ValueError("width and height must be > 0")
    points: tuple[Point, ...] = (
        (x, y),
        (x + width, y),
        (x + width, y + height),
        (x, y + height),
        (x, y),
    )
    return Polygon(layer=layer, points=points)


def validate_all(polygons: Iterable[Polygon], allow_non_manhattan: bool = False) -> list[str]:
    errors: list[str] = []
    for idx, poly in enumerate(polygons):
        for err in poly.validate(allow_non_manhattan=allow_non_manhattan):
            errors.append(f"polygon[{idx}]: {err}")
    return errors
