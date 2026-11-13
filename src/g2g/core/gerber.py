"""Native RS-274X (Gerber) reader.

Turns a Gerber layer (typically the solder paste layer) into shapely polygons
in millimetres.  This replaces the gerbv -> PDF -> pstoedit -> pic tool chain
of the original gerber2graphtec.

Supported: format/unit statements, standard apertures (C, R, O, P) with holes,
aperture macros (primitives 1, 2/20, 21, 22, 4, 5, 7 incl. arithmetic and
variables), flashes, linear and circular draws (single and multi quadrant),
regions (G36/G37), polarity (LPD/LPC), aperture transforms (LM/LR/LS) and the
common deprecated constructs (G54, G70/G71, G90/G91, modal operation codes).
Unsupported constructs (step & repeat, block apertures) produce warnings.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass, field
from pathlib import Path

from shapely import affinity
from shapely.geometry import LineString, MultiPolygon, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

MM_PER_INCH = 25.4
# Draws with a narrower aperture than this are outlines, not copper (mm).
MIN_STROKE_WIDTH = 0.01


class GerberError(ValueError):
    """The file could not be interpreted as a Gerber layer."""


@dataclass
class GerberResult:
    geometry: BaseGeometry  # union of all dark features, mm
    warnings: list[str] = field(default_factory=list)
    units: str = "mm"
    flashes: int = 0
    draws: int = 0
    regions: int = 0

    @property
    def polygons(self) -> list[Polygon]:
        return explode(self.geometry)


def explode(geom: BaseGeometry) -> list[Polygon]:
    """Flatten any geometry into its non-degenerate polygons."""
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom] if geom.area > 1e-9 else []
    out: list[Polygon] = []
    for g in getattr(geom, "geoms", []):
        out.extend(explode(g))
    return out


def quad_segs(radius: float, tol: float) -> int:
    """Segments per quarter circle so the chord error stays below ``tol``."""
    if radius <= 0 or tol >= radius:
        return 2
    step = 2 * math.acos(1 - tol / radius)
    return max(2, min(64, math.ceil((math.pi / 2) / step)))


def circle(radius: float, tol: float, cx: float = 0.0, cy: float = 0.0) -> Polygon:
    return Point(cx, cy).buffer(radius, quad_segs=quad_segs(radius, tol))


# --------------------------------------------------------------------------
# aperture macro arithmetic
# --------------------------------------------------------------------------

_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _eval_node(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    raise GerberError("unsupported macro expression")


def eval_expr(expr: str, variables: dict[int, float]) -> float:
    """Evaluate a macro expression such as ``$1x0.5+($2/2)``."""
    expr = expr.strip()
    if not expr:
        return 0.0
    expr = re.sub(r"\$(\d+)", lambda m: repr(variables.get(int(m.group(1)), 0.0)), expr)
    expr = expr.replace("x", "*").replace("X", "*")
    if not re.fullmatch(r"[0-9eE.+\-*/() ]+", expr):
        raise GerberError(f"bad macro expression: {expr!r}")
    try:
        return _eval_node(ast.parse(expr, mode="eval"))
    except (SyntaxError, ZeroDivisionError) as exc:
        raise GerberError(f"bad macro expression: {expr!r}") from exc


def _rect(w: float, h: float, cx: float = 0.0, cy: float = 0.0) -> Polygon:
    return Polygon([(cx - w / 2, cy - h / 2), (cx + w / 2, cy - h / 2), (cx + w / 2, cy + h / 2), (cx - w / 2, cy + h / 2)])


def _regular(diameter: float, n: int, rot: float, cx: float = 0.0, cy: float = 0.0) -> Polygon:
    n = max(3, int(n))
    r = diameter / 2
    a0 = math.radians(rot)
    return Polygon([(cx + r * math.cos(a0 + 2 * math.pi * i / n), cy + r * math.sin(a0 + 2 * math.pi * i / n)) for i in range(n)])


def build_macro(body: list[str], params: list[float], tol: float) -> BaseGeometry:
    """Instantiate an aperture macro (file units, origin at 0,0)."""
    variables = {i + 1: v for i, v in enumerate(params)}
    shape: BaseGeometry = Polygon()

    def rot(g: BaseGeometry, angle: float) -> BaseGeometry:
        return affinity.rotate(g, angle, origin=(0, 0)) if angle else g

    for raw_stmt in body:
        stmt = raw_stmt.strip()
        if not stmt or re.match(r"0(?![0-9.])", stmt):
            continue  # empty or comment primitive
        if stmt.startswith("$"):
            name, _, expr = stmt.partition("=")
            variables[int(name[1:])] = eval_expr(expr, variables)
            continue
        vals = [eval_expr(p, variables) for p in stmt.split(",")]
        code = int(vals[0])
        p = vals[1:]
        exposure = True
        g: BaseGeometry | None = None

        def arg(i: int, default: float = 0.0, p: list[float] = p) -> float:
            return p[i] if i < len(p) else default

        if code == 1:  # circle: exposure, diameter, cx, cy[, rotation]
            exposure = arg(0) != 0
            g = rot(circle(arg(1) / 2, tol, arg(2), arg(3)), arg(4))
        elif code in (2, 20):  # vector line: exposure, width, x1, y1, x2, y2, rotation
            exposure = arg(0) != 0
            w, x1, y1, x2, y2 = arg(1), arg(2), arg(3), arg(4), arg(5)
            length = math.hypot(x2 - x1, y2 - y1)
            if length > 0 and w > 0:
                nx, ny = -(y2 - y1) / length * w / 2, (x2 - x1) / length * w / 2
                g = Polygon([(x1 + nx, y1 + ny), (x2 + nx, y2 + ny), (x2 - nx, y2 - ny), (x1 - nx, y1 - ny)])
                g = rot(g, arg(6))
        elif code == 21:  # center line: exposure, width, height, cx, cy, rotation
            exposure = arg(0) != 0
            g = rot(_rect(arg(1), arg(2), arg(3), arg(4)), arg(5))
        elif code == 22:  # lower left line: exposure, width, height, x, y, rotation
            exposure = arg(0) != 0
            g = rot(_rect(arg(1), arg(2), arg(3) + arg(1) / 2, arg(4) + arg(2) / 2), arg(5))
        elif code == 4:  # outline: exposure, n, x0, y0, ... xn, yn, rotation
            exposure = arg(0) != 0
            n = int(arg(1))
            pts = [(arg(2 + 2 * i), arg(3 + 2 * i)) for i in range(n + 1)]
            if len(pts) >= 3:
                g = rot(Polygon(pts).buffer(0), arg(4 + 2 * n))
        elif code == 5:  # polygon: exposure, vertices, cx, cy, diameter, rotation
            exposure = arg(0) != 0
            g = rot(_regular(arg(4), int(arg(1)), 0.0, arg(2), arg(3)), arg(5))
        elif code == 7:  # thermal: cx, cy, outer, inner, gap, rotation
            cx, cy, outer, inner, gap = arg(0), arg(1), arg(2), arg(3), arg(4)
            ring = circle(outer / 2, tol, cx, cy).difference(circle(inner / 2, tol, cx, cy))
            cross = _rect(outer * 1.1, gap, cx, cy).union(_rect(gap, outer * 1.1, cx, cy))
            g = rot(ring.difference(cross), arg(5))
        else:
            raise GerberError(f"unsupported macro primitive {code}")

        if g is None or g.is_empty:
            continue
        shape = shape.union(g) if exposure else shape.difference(g)
    return shape


# --------------------------------------------------------------------------
# parser
# --------------------------------------------------------------------------

_WORD = re.compile(r"([GDMXYIJ])([+-]?[0-9.]+)")


@dataclass
class _Aperture:
    geom: BaseGeometry  # mm, centred on the origin
    diameter: float | None = None  # set for plain circles (mm)


class _Parser:
    def __init__(self, tol: float):
        self.tol = tol
        self.warnings: list[str] = []
        self.unit = MM_PER_INCH  # factor file units -> mm; inch is the historic default
        self.unit_set = False
        self.int_digits, self.dec_digits = 2, 4
        self.trailing_zeros_omitted = False
        self.incremental = False
        self.apertures: dict[int, _Aperture] = {}
        self.macros: dict[str, list[str]] = {}
        self.current: _Aperture | None = None
        self.x = self.y = 0.0
        self.interp = 1
        self.multi_quadrant = True
        self.op = 2
        self.in_region = False
        self.contour: list[tuple[float, float]] = []
        self.path: list[tuple[float, float]] = []
        self.dark = True
        self.mirror = "N"
        self.rotation = 0.0
        self.scale = 1.0
        self.groups: list[tuple[bool, list[BaseGeometry]]] = []
        self.flashes = self.draws = self.regions = 0
        self.done = False
        self._warned: set[str] = set()

    # -- helpers -----------------------------------------------------------

    def warn(self, msg: str) -> None:
        if msg not in self._warned:
            self._warned.add(msg)
            self.warnings.append(msg)

    def add(self, geom: BaseGeometry) -> None:
        if geom is None or geom.is_empty:
            return
        if not self.groups or self.groups[-1][0] != self.dark:
            self.groups.append((self.dark, []))
        self.groups[-1][1].append(geom)

    def coord(self, text: str) -> float:
        if "." in text:
            return float(text) * self.unit
        sign = -1.0 if text.startswith("-") else 1.0
        digits = text.lstrip("+-")
        if self.trailing_zeros_omitted:
            digits = digits.ljust(self.int_digits + self.dec_digits, "0")
        return sign * int(digits or "0") / 10**self.dec_digits * self.unit

    def transformed(self, ap: _Aperture) -> BaseGeometry:
        g = ap.geom
        if self.mirror != "N":
            g = affinity.scale(g, -1 if "X" in self.mirror else 1, -1 if "Y" in self.mirror else 1, origin=(0, 0))
        if self.rotation:
            g = affinity.rotate(g, self.rotation, origin=(0, 0))
        if self.scale != 1.0:
            g = affinity.scale(g, self.scale, self.scale, origin=(0, 0))
        return g

    # -- extended (%...%) commands ----------------------------------------

    def extended(self, cmds: list[str]) -> None:
        if not cmds:
            return
        if cmds[0].startswith("AM"):
            self.macros[cmds[0][2:].strip()] = cmds[1:]
            return
        for cmd in cmds:
            self.extended_one(cmd)

    def extended_one(self, cmd: str) -> None:
        code = cmd[:2]
        if code == "FS":
            m = re.match(r"FS([LT]?)([AI]?)X(\d)(\d)Y(\d)(\d)", cmd)
            if not m:
                raise GerberError(f"bad format statement: {cmd}")
            self.trailing_zeros_omitted = m.group(1) == "T"
            self.incremental = m.group(2) == "I"
            self.int_digits, self.dec_digits = int(m.group(3)), int(m.group(4))
        elif code == "MO":
            self.unit = MM_PER_INCH if cmd[2:4] == "IN" else 1.0
            self.unit_set = True
        elif code == "AD":
            self.define_aperture(cmd)
        elif code == "LP":
            self.flush_path()
            self.dark = cmd[2:3] != "C"
        elif code == "LM":
            self.flush_path()
            self.mirror = cmd[2:] or "N"
        elif code == "LR":
            self.flush_path()
            self.rotation = float(cmd[2:] or 0)
        elif code == "LS":
            self.flush_path()
            self.scale = float(cmd[2:] or 1)
        elif code == "IP":
            if cmd[2:5] == "NEG":
                self.warn("Negative image polarity (IPNEG) is not supported; the image is read as positive.")
        elif code == "SR":
            if not re.fullmatch(r"SR(X1Y1(I[0-9.]+J[0-9.]+)?)?", cmd):
                self.warn("Step & repeat (SR) is not supported; only the first copy is read.")
        elif code == "AB":
            self.warn("Block apertures (AB) are not supported and were skipped.")
        # TF/TA/TO/TD attributes, LN, OF, MI, SF, IR, AS, IN: nothing to do

    def define_aperture(self, cmd: str) -> None:
        m = re.match(r"ADD(\d+)([A-Za-z_.$][A-Za-z0-9_.$]*)(?:,(.*))?$", cmd)
        if not m:
            raise GerberError(f"bad aperture definition: {cmd}")
        num, name, rest = int(m.group(1)), m.group(2), m.group(3) or ""
        raw = [float(v) for v in rest.split("X") if v.strip()] if rest else []
        u, tol = self.unit, self.tol
        diameter = None

        def with_hole(g: BaseGeometry, idx: int) -> BaseGeometry:
            if len(raw) > idx and raw[idx] > 0:
                return g.difference(circle(raw[idx] * u / 2, tol))
            return g

        if name == "C" and raw:
            g = with_hole(circle(raw[0] * u / 2, tol), 1)
            if len(raw) < 2 or raw[1] <= 0:
                diameter = raw[0] * u
        elif name == "R" and len(raw) >= 2:
            g = with_hole(_rect(raw[0] * u, raw[1] * u), 2)
        elif name == "O" and len(raw) >= 2:
            w, h = raw[0] * u, raw[1] * u
            r = min(w, h) / 2
            if w >= h:
                spine = LineString([(-(w / 2 - r), 0), (w / 2 - r, 0)])
            else:
                spine = LineString([(0, -(h / 2 - r)), (0, h / 2 - r)])
            g = circle(r, tol) if abs(w - h) < 1e-9 else spine.buffer(r, quad_segs=quad_segs(r, tol))
            g = with_hole(g, 2)
        elif name == "P" and len(raw) >= 2:
            g = with_hole(_regular(raw[0] * u, int(raw[1]), raw[2] if len(raw) > 2 else 0.0), 3)
        elif name in self.macros:
            g = build_macro(self.macros[name], raw, tol / u)
            g = affinity.scale(g, u, u, origin=(0, 0))
        else:
            raise GerberError(f"unknown aperture template {name!r} in {cmd}")
        self.apertures[num] = _Aperture(g, diameter)

    # -- drawing -----------------------------------------------------------

    def flush_path(self) -> None:
        pts, self.path = self.path, []
        ap = self.current
        if len(pts) < 2 or ap is None:
            return
        self.draws += len(pts) - 1
        if ap.diameter is not None:
            d = ap.diameter * self.scale
            if d < MIN_STROKE_WIDTH:
                self.warn("Draws with a (near) zero width aperture were ignored.")
                return
            if all(p == pts[0] for p in pts):
                self.add(circle(d / 2, self.tol, *pts[0]))
            else:
                self.add(LineString(pts).buffer(d / 2, quad_segs=quad_segs(d / 2, self.tol)))
            return
        g = self.transformed(ap)
        for a, b in zip(pts, pts[1:]):
            ends = [affinity.translate(g, *a), affinity.translate(g, *b)]
            self.add(unary_union(ends).convex_hull if a != b else ends[0])

    def close_contour(self) -> None:
        pts, self.contour = self.contour, []
        if len(pts) >= 3:
            poly = Polygon(pts)
            if not poly.is_valid:
                poly = poly.buffer(0)
            self.add(poly)
            self.regions += 1

    def arc_points(self, x0: float, y0: float, x1: float, y1: float, i: float, j: float) -> list[tuple[float, float]]:
        cw = self.interp == 2
        if self.multi_quadrant:
            cx, cy = x0 + i, y0 + j
        else:
            best = None
            for si in (1, -1):
                for sj in (1, -1):
                    c = (x0 + si * abs(i), y0 + sj * abs(j))
                    err = abs(math.hypot(x0 - c[0], y0 - c[1]) - math.hypot(x1 - c[0], y1 - c[1]))
                    sweep = self._sweep(x0, y0, x1, y1, c[0], c[1], cw)
                    if sweep <= math.pi / 2 + 1e-6 and (best is None or err < best[0]):
                        best = (err, c)
            if best is None:
                return [(x1, y1)]
            cx, cy = best[1]
        r = math.hypot(x0 - cx, y0 - cy)
        if r < 1e-9:
            return [(x1, y1)]
        sweep = self._sweep(x0, y0, x1, y1, cx, cy, cw)
        if sweep < 1e-12:
            if not self.multi_quadrant:
                return [(x1, y1)]
            sweep = 2 * math.pi
        step = 2 * math.acos(max(-1.0, 1 - min(self.tol, r) / r)) or math.pi / 8
        n = max(2, math.ceil(sweep / step))
        a0 = math.atan2(y0 - cy, x0 - cx)
        sign = -1 if cw else 1
        pts = [(cx + r * math.cos(a0 + sign * sweep * k / n), cy + r * math.sin(a0 + sign * sweep * k / n)) for k in range(1, n)]
        pts.append((x1, y1))
        return pts

    @staticmethod
    def _sweep(x0: float, y0: float, x1: float, y1: float, cx: float, cy: float, cw: bool) -> float:
        a0 = math.atan2(y0 - cy, x0 - cx)
        a1 = math.atan2(y1 - cy, x1 - cx)
        sweep = (a0 - a1) if cw else (a1 - a0)
        sweep %= 2 * math.pi
        return 0.0 if sweep < 1e-12 or 2 * math.pi - sweep < 1e-12 else sweep

    # -- word commands -----------------------------------------------------

    def word(self, cmd: str) -> None:
        if re.match(r"G0*4(?!\d)", cmd):
            return  # comment
        words = _WORD.findall(cmd)
        if not words:
            return
        coords: dict[str, str] = {}
        dcode: int | None = None
        for letter, value in words:
            if letter == "G":
                self.gcode(int(float(value)))
            elif letter == "D":
                dcode = int(float(value))
            elif letter == "M":
                if int(float(value)) in (0, 2):
                    self.done = True
            else:
                coords[letter] = value
        if dcode is not None and dcode >= 10:
            self.flush_path()
            self.current = self.apertures.get(dcode)
            if self.current is None:
                self.warn(f"Aperture D{dcode} is used but not defined.")
            dcode = None
            if not coords:
                return
        if dcode is None and not coords:
            return
        if dcode is not None:
            self.op = dcode
        self.operate(coords)

    def gcode(self, g: int) -> None:
        if g in (1, 2, 3):
            self.interp = g
        elif g == 36:
            self.flush_path()
            self.in_region = True
            self.contour = []
        elif g == 37:
            self.close_contour()
            self.in_region = False
        elif g == 70:
            self.unit_set = True
            self.unit = MM_PER_INCH
        elif g == 71:
            self.unit_set = True
            self.unit = 1.0
        elif g == 74:
            self.multi_quadrant = False
        elif g == 75:
            self.multi_quadrant = True
        elif g == 90:
            self.incremental = False
        elif g == 91:
            self.incremental = True

    def operate(self, coords: dict[str, str]) -> None:
        x, y = self.x, self.y
        if "X" in coords:
            x = self.coord(coords["X"]) + (self.x if self.incremental else 0.0)
        if "Y" in coords:
            y = self.coord(coords["Y"]) + (self.y if self.incremental else 0.0)
        i = self.coord(coords["I"]) if "I" in coords else 0.0
        j = self.coord(coords["J"]) if "J" in coords else 0.0

        if self.op == 1:
            pts = [(x, y)] if self.interp == 1 else self.arc_points(self.x, self.y, x, y, i, j)
            target = self.contour if self.in_region else self.path
            if not target:
                target.append((self.x, self.y))
            target.extend(pts)
            if not self.in_region and self.current is None:
                self.warn("Draw without a selected aperture was ignored.")
                self.path = []
        elif self.op == 2:
            if self.in_region:
                self.close_contour()
            else:
                self.flush_path()
        elif self.op == 3:
            self.flush_path()
            if self.in_region:
                self.warn("Flash inside a region was ignored.")
            elif self.current is None:
                self.warn("Flash without a selected aperture was ignored.")
            else:
                self.add(affinity.translate(self.transformed(self.current), x, y))
                self.flashes += 1
        self.x, self.y = x, y

    # -- driver ------------------------------------------------------------

    def run(self, text: str) -> GerberResult:
        blocks = text.split("%")
        for idx, block in enumerate(blocks):
            if self.done:
                break
            cmds = [c.strip() for c in block.replace("\r", "").replace("\n", "").split("*")]
            cmds = [c for c in cmds if c]
            if idx % 2 == 1:
                self.extended(cmds)
            else:
                for cmd in cmds:
                    self.word(cmd)
                    if self.done:
                        break
        self.flush_path()
        self.close_contour()

        if not self.unit_set:
            self.warn("No unit statement (%MO) found; inches assumed.")
        acc: BaseGeometry = Polygon()
        for dark, geoms in self.groups:
            merged = unary_union(geoms)
            acc = acc.union(merged) if dark else acc.difference(merged)
        polys = explode(acc)
        if any(p.interiors for p in polys):
            self.warn("Some pads have holes. Only their outline is cut; the island inside would fall out.")
        geometry = MultiPolygon(polys) if polys else Polygon()
        return GerberResult(
            geometry=geometry,
            warnings=self.warnings,
            units="inch" if self.unit == MM_PER_INCH else "mm",
            flashes=self.flashes,
            draws=self.draws,
            regions=self.regions,
        )


def parse_gerber(text: str, tolerance: float = 0.005) -> GerberResult:
    """Parse Gerber source text.  ``tolerance`` is the arc chord error in mm."""
    if "%FS" not in text and "D01" not in text and "D03" not in text and "D1*" not in text and "D3*" not in text:
        raise GerberError("This does not look like a Gerber (RS-274X) file.")
    try:
        return _Parser(max(tolerance, 1e-4)).run(text)
    except GerberError:
        raise
    except (ValueError, IndexError, KeyError) as exc:
        raise GerberError(f"Malformed Gerber data: {exc}") from exc


def load_gerber(path: str | Path, tolerance: float = 0.005) -> GerberResult:
    data = Path(path).read_bytes()
    if b"\x00" in data[:4096]:
        raise GerberError("This is a binary file, not a Gerber file.")
    return parse_gerber(data.decode("latin-1"), tolerance)
