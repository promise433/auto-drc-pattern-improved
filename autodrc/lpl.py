from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable


Point = tuple[int, int]


@dataclass(frozen=True)
class TextLabel:
    layer: str
    text: str
    position: Point

    def validate(self) -> list[str]:
        errors=[]
        if not isinstance(self.layer,str) or not self.layer:
            errors.append('label layer must be nonempty')
        if not isinstance(self.text,str) or not self.text or '\0' in self.text:
            errors.append('label text must be nonempty and contain no NUL')
        if len(self.position)!=2 or any(type(v) is not int for v in self.position):
            errors.append('label position must contain two integer nanometre coordinates')
        return errors

    def to_dict(self) -> dict[str,object]:
        return dict(layer=self.layer,text=self.text,position=list(self.position))


def _is_manhattan(a: Point, b: Point) -> bool:
    return a[0] == b[0] or a[1] == b[1]


@dataclass(frozen=True)
class Polygon:
    layer: str
    points: tuple[Point, ...]

    def validate(self, allow_non_manhattan: bool = False, *, rigorous: bool = False) -> list[str]:
        errors: list[str] = []
        if len(self.points) < 4:
            errors.append("polygon has fewer than 4 points")
            return errors
        if self.points[0] != self.points[-1]:
            errors.append("polygon is not closed")
        if rigorous:
            vertices = self.points[:-1] if self.points[0] == self.points[-1] else self.points
            if len(set(vertices)) < 3:
                errors.append("polygon has fewer than 3 distinct vertices")
            edges = list(zip(vertices, vertices[1:] + vertices[:1]))
            if sum(a[0]*b[1]-b[0]*a[1] for a,b in edges) == 0:
                errors.append("polygon has zero signed area")
            def orientation(a, b, c):
                return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
            def on_segment(a, b, c):
                return (orientation(a,b,c) == 0 and
                        min(a[0],b[0]) <= c[0] <= max(a[0],b[0]) and
                        min(a[1],b[1]) <= c[1] <= max(a[1],b[1]))
            def intersects(a,b,c,d):
                x,y,z,w = orientation(a,b,c),orientation(a,b,d),orientation(c,d,a),orientation(c,d,b)
                return ((x*y < 0 and z*w < 0) or on_segment(a,b,c) or
                        on_segment(a,b,d) or on_segment(c,d,a) or on_segment(c,d,b))
            for i,(a,b) in enumerate(edges):
                if a == b:
                    errors.append(f"zero-length edge at segment {i}")
                c = edges[(i+1) % len(edges)][1]
                if orientation(a,b,c) == 0 and (b[0]-a[0])*(c[0]-b[0])+(b[1]-a[1])*(c[1]-b[1]) < 0:
                    errors.append(f"overlapping adjacent edges at segment {i}")
                for j in range(i+2,len(edges)):
                    if i == 0 and j == len(edges)-1:
                        continue
                    if intersects(a,b,*edges[j]):
                        errors.append(f"self-intersection between segments {i} and {j}")
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


def validate_all(polygons: Iterable[Polygon], allow_non_manhattan: bool = False, *, rigorous: bool = False) -> list[str]:
    errors: list[str] = []
    for idx, poly in enumerate(polygons):
        for err in poly.validate(allow_non_manhattan=allow_non_manhattan, rigorous=rigorous):
            errors.append(f"polygon[{idx}]: {err}")
    return errors
