import contextlib
import io
import math
import re
import sys
from pathlib import Path

import pytest

from g2g.core import graphtec, toolpath
from g2g.core.gerber import GerberError, eval_expr, load_gerber, parse_gerber
from g2g.core.toolpath import CutParams, CutPass, build_job

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
sys.path.insert(0, str(Path(__file__).parent / "legacy"))

HEADER = "%FSLAX34Y34*%\n%MOMM*%\n"


def polys(src):
    return parse_gerber(HEADER + src).polygons


# ---------------------------------------------------------------- gerber


def test_flash_rectangle():
    (p,) = polys("%ADD10R,2X1*%\nD10*\nX100000Y50000D03*\nM02*\n")
    assert p.bounds == pytest.approx((9, 4.5, 11, 5.5))


def test_inch_units_and_corners_example():
    res = load_gerber(EXAMPLES / "corners.gbr")
    assert res.units == "inch"
    assert len(res.polygons) == 4
    minx, miny, maxx, maxy = res.geometry.bounds
    assert maxx - minx == pytest.approx(5.0 * 25.4, abs=0.01)
    assert maxy - miny == pytest.approx(5.0 * 25.4, abs=0.01)


def test_circle_area_within_tolerance():
    (p,) = polys("%ADD10C,2*%\nD10*\nX0Y0D03*\n")
    assert p.area == pytest.approx(math.pi, rel=0.01)


def test_obround_and_polygon():
    a, b = polys("%ADD10O,3X1*%\n%ADD11P,2X6*%\nD10*\nX0Y0D03*\nD11*\nX100000Y0D03*\n")
    assert a.bounds == pytest.approx((-1.5, -0.5, 1.5, 0.5), abs=1e-3)
    assert len(b.exterior.coords) - 1 == 6


def test_draw_with_square_aperture_is_swept():
    # gEDA pcb style pad: a line drawn with a square aperture
    (p,) = polys("%ADD10R,1X1*%\nD10*\nX0Y0D02*\nX30000Y0D01*\n")
    assert p.bounds == pytest.approx((-0.5, -0.5, 3.5, 0.5))
    assert p.area == pytest.approx(4.0)


def test_draw_with_round_aperture():
    (p,) = polys("%ADD10C,1*%\nD10*\nX0Y0D02*\nX30000Y0D01*\n")
    assert p.bounds == pytest.approx((-0.5, -0.5, 3.5, 0.5), abs=1e-3)


def test_region():
    (p,) = polys("G36*\nX0Y0D02*\nX20000Y0D01*\nX20000Y10000D01*\nX0Y10000D01*\nX0Y0D01*\nG37*\n")
    assert p.area == pytest.approx(2.0)


def test_region_with_arc_multi_quadrant():
    # half disc of radius 1
    src = "G75*\nG36*\nX-10000Y0D02*\nG01X10000Y0D01*\nG03X-10000Y0I-10000J0D01*\nG37*\n"
    (p,) = polys(src)
    assert p.area == pytest.approx(math.pi / 2, rel=0.01)
    assert p.bounds[3] == pytest.approx(1.0, abs=0.01)


def test_clear_polarity_cuts_hole():
    src = "%ADD10R,4X4*%\n%ADD11R,6X1*%\nD10*\nX0Y0D03*\n%LPC*%\nD11*\nX0Y0D03*\n%LPD*%\n"
    ps = polys(src)
    assert len(ps) == 2
    assert sum(p.area for p in ps) == pytest.approx(12.0)


def test_kicad_roundrect_macro():
    src = (
        "%AMRoundRect*\n0 Rectangle with rounded corners*\n0 $1 Rounding radius*\n"
        "4,1,4,$2,$3,$4,$5,$6,$7,$8,$9,$2,$3,0*\n"
        "1,1,$1+$1,$2,$3*\n1,1,$1+$1,$4,$5*\n1,1,$1+$1,$6,$7*\n1,1,$1+$1,$8,$9*\n"
        "20,1,$1+$1,$2,$3,$4,$5,0*\n20,1,$1+$1,$4,$5,$6,$7,0*\n"
        "20,1,$1+$1,$6,$7,$8,$9,0*\n20,1,$1+$1,$8,$9,$2,$3,0*%\n"
        "%ADD10RoundRect,0.25X-0.5X0.25X0.5X0.25X0.5X-0.25X-0.5X-0.25X0*%\n"
        "D10*\nX0Y0D03*\n"
    )
    (p,) = polys(src)
    assert p.bounds == pytest.approx((-0.75, -0.5, 0.75, 0.5), abs=1e-3)
    expected = 1.5 * 1.0 - (4 - math.pi) * 0.25**2
    assert p.area == pytest.approx(expected, rel=0.01)


def test_macro_rotation_and_exposure_off():
    src = "%AMDONUT*21,1,2,1,0,0,90*1,0,0.5,0,0*%\n%ADD10DONUT*%\nD10*\nX0Y0D03*\n"
    (p,) = polys(src)
    assert p.bounds == pytest.approx((-0.5, -1, 0.5, 1), abs=1e-6)
    assert len(p.interiors) == 1


def test_macro_expression():
    assert eval_expr("$1x2+($2/4)-1", {1: 3.0, 2: 8.0}) == pytest.approx(7.0)
    with pytest.raises(GerberError):
        eval_expr("__import__('os')", {})


def test_trailing_zero_omission():
    src = "%FSTAX34Y34*%\n%MOMM*%\n%ADD10R,1X1*%\nD10*\nX001Y002D03*\n"
    (p,) = parse_gerber(src).polygons
    assert p.centroid.coords[0] == pytest.approx((1.0, 2.0))


def test_not_a_gerber():
    with pytest.raises(GerberError):
        parse_gerber("hello world")


@pytest.mark.parametrize(
    "name,count",
    [("test_tiny.gbr", None), ("test_0.5mm_0402.gbr", None), ("example1.gbr", None), ("fine_pitch_sampler.gbr", None)],
)
def test_examples_parse(name, count):
    res = load_gerber(EXAMPLES / name)
    assert len(res.polygons) > 0
    for p in res.polygons:
        assert p.is_valid


# ---------------------------------------------------------------- toolpath


def test_job_is_justified_and_bordered():
    res = load_gerber(EXAMPLES / "corners.gbr")
    job = build_job(res.geometry, CutParams())
    assert job.width == pytest.approx(127.0, abs=0.01)
    assert job.height == pytest.approx(127.0, abs=0.01)
    assert min(x for s in job.strokes for x, _ in s) == pytest.approx(0)
    assert job.border_path[0] == (-25.4, -25.4)
    # 4 squares * 4 edges * 2 directions + 4 training lines (4 angle bins)
    assert len(job.lines) == 36
    assert sum(job.training) == 4


def test_inset_shrinks_pads():
    res = load_gerber(EXAMPLES / "corners.gbr")
    a = build_job(res.geometry, CutParams())
    b = build_job(res.geometry, CutParams(inset=0.05))
    assert b.polygons[0].area < a.polygons[0].area
    assert b.width == pytest.approx(a.width - 0.1, abs=1e-6)


def test_rotation_swaps_extent():
    res = load_gerber(EXAMPLES / "test_tiny.gbr")
    a = build_job(res.geometry, CutParams())
    b = build_job(res.geometry, CutParams(rotate=90))
    assert (b.width, b.height) == pytest.approx((a.height, a.width), abs=1e-3)


def test_media_fit():
    res = load_gerber(EXAMPLES / "corners.gbr")
    assert build_job(res.geometry, CutParams()).fits_media()
    assert build_job(res.geometry, CutParams(offset_x=200)).fits_media() is False
    assert build_job(res.geometry, CutParams(offset_x=0, offset_y=0, border_x=5, border_y=5)).fits_media()


def test_params_roundtrip():
    p = CutParams(passes=[CutPass(1, 5), CutPass(3, 20)], mode="fast", mirror=True, matrix=(1.01, 0, 0, 0.99))
    assert CutParams.from_dict(p.to_dict()) == p


# ---------------------------------------------------------------- regression against the original implementation

_CMD = re.compile(r"([MD])(-?[0-9.]+),(-?[0-9.]+)\x03")


def legacy_stream(strokes_mm, params: CutParams) -> str:
    """Run the original (inch based) gerber2graphtec code on the same strokes."""
    import graphtec as legacy_graphtec
    import optimize as legacy_optimize

    inch = 25.4
    strokes = [[(x / inch, y / inch) for x, y in s] for s in strokes_mm]
    offset = (params.offset_x / inch, params.offset_y / inch)
    border = (params.border_x / inch, params.border_y / inch)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        g = legacy_graphtec.graphtec()
        g.fd = buf
        g.set(media_size=(round(params.media_w / inch, 9), round(params.media_h / inch, 9)))
        g.set(offset=(offset[0] + border[0] + 0.5, offset[1] + border[1] + 0.5))
        g.set(matrix=params.matrix)
        g.start()
        max_x, max_y = legacy_optimize.max_extent(strokes)
        border_path = [
            (-border[0], -border[1]),
            (max_x + border[0], -border[1]),
            (max_x + border[0], max_y + border[1]),
            (-border[0], max_y + border[1]),
        ]
        if params.mode == "accurate":
            lines = legacy_optimize.optimize(strokes, border)
            for cp in params.passes:
                g.set(speed=cp.speed, force=cp.force)
                for x in lines:
                    g.line(*x)
                if border[0] != 0 or border[1] != 0:
                    g.closed_path(border_path)
        else:
            for cp in params.passes:
                g.set(speed=cp.speed, force=cp.force)
                for s in strokes:
                    g.closed_path(s)
                if border[0] != 0 or border[1] != 0:
                    g.closed_path(border_path)
        g.end()
    return buf.getvalue()


def split_stream(stream: str):
    moves = [(m.group(1), float(m.group(2)), float(m.group(3))) for m in _CMD.finditer(stream)]
    return _CMD.sub("", stream), moves


@pytest.mark.parametrize("name", ["corners.gbr", "test_tiny.gbr", "test_0.5mm_0402.gbr", "example1.gbr", "fine_pitch_sampler.gbr"])
@pytest.mark.parametrize(
    "params",
    [
        CutParams(),
        CutParams(mode="fast", passes=[CutPass(5, 20)]),
        CutParams(matrix=(1.001, 0.0, -0.0005, 0.9985), offset_x=76.2, offset_y=101.6, border_x=0, border_y=0),
        CutParams(rotate=35.7, passes=[CutPass(2, 5), CutPass(1, 15), CutPass(1, 30)]),
    ],
    ids=["default", "fast", "matrix-noborder", "rotated-3pass"],
)
def test_stream_matches_original(name, params):
    job = build_job(load_gerber(EXAMPLES / name).geometry, params)
    new = graphtec.encode(job).decode("latin-1")
    old = legacy_stream(job.strokes, params)
    new_ctrl, new_moves = split_stream(new)
    old_ctrl, old_moves = split_stream(old)
    assert new_ctrl == old_ctrl
    assert len(new_moves) == len(old_moves) > 0
    # Lines with identical start height may be ordered differently (float noise in
    # the sort key), so compare the cuts as a set: same lines, same count.
    assert [m[0] for m in new_moves] == [m[0] for m in old_moves]
    for (c1, x1, y1), (c2, x2, y2) in zip(sorted(new_moves), sorted(old_moves)):
        assert c1 == c2
        assert abs(x1 - x2) <= 0.0021 and abs(y1 - y2) <= 0.0021  # < 0.11 micron


def test_stream_shape():
    job = build_job(load_gerber(EXAMPLES / "corners.gbr").geometry, CutParams())
    data = graphtec.encode(job)
    assert data.startswith(b"\x1b\x04\x1b\x05TT\x03")
    assert data.endswith(b"FO0\x03H,")
    assert b"Z6096,5588,L0," in data
    assert data.count(b"!2\x03") == 2 and b"FX8,0\x03" in data and b"FX30,0\x03" in data


def test_empty_job():
    job = build_job(parse_gerber(HEADER + "M02*\n").geometry, CutParams())
    assert job.is_empty and job.fits_media() and toolpath._perimeter([]) == 0
