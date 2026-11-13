"""Turn pad polygons into an ordered cutting job.

All lengths are millimetres.  The cutting strategy is the proven one from the
original gerber2graphtec by Peter Monta: every polygon edge is cut as an
individual line, in both directions, grouped by knife angle (16 bins), and each
angle group is preceded by a short "training" cut outside the stencil that
swivels the drag knife into the right orientation.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field

from shapely import affinity
from shapely.geometry import Polygon
from shapely.geometry.base import BaseGeometry

from .gerber import explode

MM_PER_INCH = 25.4
# Space reserved outside the border for the knife training cuts (0.5 inch).
TRAINING_MARGIN = 0.5 * MM_PER_INCH

Point = tuple[float, float]
Line = tuple[float, float, float, float]


@dataclass
class CutPass:
    speed: int = 2  # device units, 1..10
    force: int = 8  # device units, 1..33


@dataclass
class CutParams:
    offset_x: float = 4.0 * MM_PER_INCH
    offset_y: float = 0.5 * MM_PER_INCH
    border_x: float = 1.0 * MM_PER_INCH
    border_y: float = 1.0 * MM_PER_INCH
    matrix: tuple[float, float, float, float] = (1.0, 0.0, 0.0, 1.0)
    passes: list[CutPass] = field(default_factory=lambda: [CutPass(2, 8), CutPass(2, 30)])
    mode: str = "accurate"  # "accurate" (line by line) or "fast" (closed paths)
    media_w: float = 12.0 * MM_PER_INCH
    media_h: float = 11.0 * MM_PER_INCH
    rotate: float = 0.0  # degrees, counter clockwise
    mirror: bool = False
    inset: float = 0.0  # shrink every pad by this much (mm) to compensate knife spread

    def to_dict(self) -> dict:
        d = asdict(self)
        d["matrix"] = list(self.matrix)
        return d

    @classmethod
    def from_dict(cls, d: dict) -> CutParams:
        base = cls()
        for key in ("offset_x", "offset_y", "border_x", "border_y", "media_w", "media_h", "rotate", "inset"):
            if key in d:
                setattr(base, key, float(d[key]))
        if d.get("mode") in ("accurate", "fast"):
            base.mode = d["mode"]
        base.mirror = bool(d.get("mirror", False))
        m = d.get("matrix")
        if isinstance(m, (list, tuple)) and len(m) == 4:
            base.matrix = tuple(float(v) for v in m)  # type: ignore[assignment]
        passes = d.get("passes")
        if isinstance(passes, list) and passes:
            base.passes = [CutPass(int(p.get("speed", 2)), int(p.get("force", 8))) for p in passes]
        return base

    @property
    def has_border(self) -> bool:
        return self.border_x != 0 or self.border_y != 0


@dataclass
class Job:
    params: CutParams
    polygons: list[Polygon]  # justified to (0,0), design space
    strokes: list[list[Point]]  # polygon outlines, open (first point not repeated)
    lines: list[Line]  # accurate mode: ordered single cuts incl. training lines
    training: list[bool]  # parallel to ``lines``
    border_path: list[Point] | None
    width: float
    height: float

    @property
    def origin(self) -> Point:
        p = self.params
        return (p.offset_x + p.border_x + TRAINING_MARGIN, p.offset_y + p.border_y + TRAINING_MARGIN)

    def to_device(self, x: float, y: float) -> Point:
        """Design coordinates -> position on the media in mm."""
        a, b, c, d = self.params.matrix
        ox, oy = self.origin
        return (a * x + b * y + ox, c * x + d * y + oy)

    @property
    def is_empty(self) -> bool:
        return not self.strokes

    def cut_points(self) -> list[Point]:
        pts: list[Point] = [p for s in self.strokes for p in s]
        if self.border_path:
            pts.extend(self.border_path)
        if self.params.mode == "accurate":
            for (x1, y1, x2, y2), t in zip(self.lines, self.training):
                if t:
                    pts.extend([(x1, y1), (x2, y2)])
        return pts

    def device_bounds(self) -> tuple[float, float, float, float] | None:
        pts = [self.to_device(*p) for p in self.cut_points()]
        if not pts:
            return None
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return (min(xs), min(ys), max(xs), max(ys))

    def fits_media(self) -> bool:
        b = self.device_bounds()
        if b is None:
            return True
        eps = 1e-6
        return b[0] >= -eps and b[1] >= -eps and b[2] <= self.params.media_w + eps and b[3] <= self.params.media_h + eps

    def cut_length(self) -> float:
        """Knife-down distance of one pass in mm."""
        if self.params.mode == "accurate":
            total = sum(math.hypot(x2 - x1, y2 - y1) for x1, y1, x2, y2 in self.lines)
        else:
            total = sum(_perimeter(s) for s in self.strokes)
        if self.border_path:
            total += _perimeter(self.border_path)
        return total

    def stats(self) -> JobStats:
        """Figures for one pass and for the whole job."""
        p = self.params
        # every knife-down run as (start, end, length)
        runs: list[tuple[Point, Point, float]] = []
        if p.mode == "accurate":
            for x1, y1, x2, y2 in self.lines:
                runs.append(((x1, y1), (x2, y2), math.hypot(x2 - x1, y2 - y1)))
        else:
            for s in self.strokes:
                runs.append((s[0], s[0], _perimeter(s)))
        if self.border_path:
            runs.append((self.border_path[0], self.border_path[0], _perimeter(self.border_path)))
        cut = sum(r[2] for r in runs)
        travel = sum(math.hypot(b[0][0] - a[1][0], b[0][1] - a[1][1]) for a, b in zip(runs, runs[1:]))
        segments = sum(len(s) for s in self.strokes) + (4 if self.border_path else 0)
        if p.mode == "accurate":
            segments = len(self.lines) + (4 if self.border_path else 0)
        smallest = min((min(q.bounds[2] - q.bounds[0], q.bounds[3] - q.bounds[1]) for q in self.polygons), default=0.0)
        n = len(p.passes)
        return JobStats(
            pads=len(self.strokes),
            width=self.width,
            height=self.height,
            passes=n,
            lifts_per_pass=len(runs),
            lifts_total=len(runs) * n,
            segments_per_pass=segments,
            cut_per_pass=cut,
            cut_total=cut * n,
            travel_per_pass=travel,
            travel_total=travel * n,
            angle_groups=sum(self.training),
            pad_area=sum(q.area for q in self.polygons),
            smallest_opening=smallest,
            seconds=sum(
                cut / (CUT_SPEED_PER_UNIT * max(1, cp.speed)) + travel / TRAVEL_SPEED + len(runs) * LIFT_TIME for cp in p.passes
            )
            + (HANDLING_TIME if runs else 0.0),
        )


# Rough machine model for the duration estimate (not measured on every cutter):
CUT_SPEED_PER_UNIT = 10.0  # mm/s per speed unit (GP-GL speed is given in cm/s)
TRAVEL_SPEED = 100.0  # mm/s with the knife lifted
LIFT_TIME = 0.15  # s for lowering + raising the knife and settling
HANDLING_TIME = 10.0  # s for homing, loading and feeding out


@dataclass
class JobStats:
    pads: int
    width: float
    height: float
    passes: int
    lifts_per_pass: int  # knife down/up strokes ("Hubbewegungen")
    lifts_total: int
    segments_per_pass: int  # straight cuts
    cut_per_pass: float  # mm, knife down
    cut_total: float
    travel_per_pass: float  # mm, knife up between cuts
    travel_total: float
    angle_groups: int  # knife orientations incl. one training cut each
    pad_area: float  # mm^2
    smallest_opening: float  # mm, narrowest pad dimension
    seconds: float  # estimated duration of the whole job


def _perimeter(pts: list[Point]) -> float:
    return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:] + pts[:1]))


def angle_bin(x1: float, y1: float, x2: float, y2: float) -> int:
    theta = math.atan2(y2 - y1, x2 - x1) + math.pi
    ang = round(theta / (math.pi / 8))
    return 0 if ang == 16 else ang


def dice(strokes: list[list[Point]]) -> list[Line]:
    """Every polygon edge as two single lines, one per direction."""
    lines: list[Line] = []
    for s in strokes:
        for p, q in zip(s, s[1:] + s[:1]):
            if p == q:
                continue
            lines.append((p[0], p[1], q[0], q[1]))
            lines.append((q[0], q[1], p[0], p[1]))
    return lines


def training_line(ang: int, border: Point) -> Line:
    c = 0.25 * MM_PER_INCH
    theta = ang * math.pi / 8
    x, y = math.cos(theta), math.sin(theta)
    return (
        0.25 * MM_PER_INCH * x - border[0] - c,
        0.25 * MM_PER_INCH * y - border[1] - c,
        0.05 * MM_PER_INCH * x - border[0] - c,
        0.05 * MM_PER_INCH * y - border[1] - c,
    )


def optimize(strokes: list[list[Point]], border: Point) -> tuple[list[Line], list[bool]]:
    lines = dice(strokes)
    bins: list[list[Line]] = [[] for _ in range(16)]
    for ln in lines:
        bins[angle_bin(*ln)].append(ln)
    out: list[Line] = []
    training: list[bool] = []
    for ang, group in enumerate(bins):
        if not group:
            continue
        group.sort(key=lambda s: (round(s[1], 6), round(s[0], 6)))
        out.append(training_line(ang, border))
        training.append(True)
        out.extend(group)
        training.extend([False] * len(group))
    return out, training


def prepare_geometry(geometry: BaseGeometry, params: CutParams) -> list[Polygon]:
    """Mirror, rotate, shrink and justify the pads to the origin."""
    g = geometry
    if g is None or g.is_empty:
        return []
    if params.mirror:
        g = affinity.scale(g, -1, 1, origin=(0, 0))
    if params.rotate:
        g = affinity.rotate(g, params.rotate, origin=(0, 0))
    if params.inset:
        g = g.buffer(-params.inset, join_style="mitre", mitre_limit=5.0)
    polys = explode(g)
    if not polys:
        return []
    min_x = min(p.bounds[0] for p in polys)
    min_y = min(p.bounds[1] for p in polys)
    polys = [affinity.translate(p, -min_x, -min_y) for p in polys]
    # stable, readable order: bottom to top, left to right
    polys.sort(key=lambda p: (round(p.bounds[1], 3), round(p.bounds[0], 3)))
    return polys


def build_job(geometry: BaseGeometry, params: CutParams) -> Job:
    polys = prepare_geometry(geometry, params)
    strokes: list[list[Point]] = []
    for p in polys:
        ring = p.exterior.simplify(1e-4)
        pts = [(float(x), float(y)) for x, y in ring.coords[:-1]]
        if len(pts) >= 3:
            strokes.append(pts)
    width = max((x for s in strokes for x, _ in s), default=0.0)
    height = max((y for s in strokes for _, y in s), default=0.0)

    border_path = None
    if strokes and params.has_border:
        bx, by = params.border_x, params.border_y
        border_path = [(-bx, -by), (width + bx, -by), (width + bx, height + by), (-bx, height + by)]

    lines: list[Line] = []
    training: list[bool] = []
    if strokes and params.mode == "accurate":
        lines, training = optimize(strokes, (params.border_x, params.border_y))

    return Job(params, polys, strokes, lines, training, border_path, width, height)
