"""The synthetic example files against values calculated by hand from their definition."""

import math
from pathlib import Path

import pytest

from g2g.core import graphtec
from g2g.core.gerber import load_gerber
from g2g.core.toolpath import CutParams, build_job

EXAMPLES = Path(__file__).resolve().parent.parent / "examples"


def pads_at(result, x, y):
    from shapely.geometry import Point

    return [p for p in result.polygons if p.buffer(1e-6).contains(Point(x, y))]


def size(p):
    b = p.bounds
    return (b[2] - b[0], b[3] - b[1])


def roundrect_area(w, h, r):
    return w * h - (4 - math.pi) * r * r


def test_examples_are_up_to_date(tmp_path, monkeypatch):
    """examples/*.gbr are exactly what scripts/make_examples.py writes."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_examples", EXAMPLES.parent / "scripts" / "make_examples.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "OUT", tmp_path)
    mod.main()
    for path in tmp_path.iterdir():
        assert path.read_bytes() == (EXAMPLES / path.name).read_bytes().replace(b"\r\n", b"\n"), path.name


def test_kicad_style_roundrect_macros():
    res = load_gerber(EXAMPLES / "kicad_style_qfn32.gbr")
    assert res.units == "mm" and res.warnings == []
    assert len(res.polygons) == 67 and res.flashes == 67
    expected = (
        32 * roundrect_area(0.75, 0.25, 0.0625)
        + 4 * roundrect_area(1.3, 1.3, 0.2)
        + 12 * roundrect_area(0.5, 0.6, 0.125)
        + 8 * roundrect_area(0.8, 0.95, 0.2)
        + 8 * roundrect_area(1.55, 0.6, 0.15)
        + 3 * roundrect_area(0.9, 0.8, 0.2)
    )
    assert res.geometry.area == pytest.approx(expected, rel=0.006)
    # one macro instance is one pad, not five loose primitives
    (qfn_pad,) = pads_at(res, 20 - 2.45, 20 - 1.75)
    assert size(qfn_pad) == pytest.approx((0.75, 0.25), abs=1e-6)
    (pane,) = pads_at(res, 20.8, 19.2)
    assert size(pane) == pytest.approx((1.3, 1.3), abs=1e-6)
    assert res.geometry.bounds == pytest.approx((10 - 2.475 - 0.775, 14.5 - 0.3, 27.8 + 0.4, 26.5 + 1.905 + 0.3), abs=1e-6)


def test_bga_round_pads():
    res = load_gerber(EXAMPLES / "bga100_0.8mm.gbr")
    assert len(res.polygons) == 103
    true_area = 100 * math.pi * 0.2**2 + 3 * math.pi * 0.5**2
    assert 0.97 * true_area < res.geometry.area <= true_area  # polygons lie inside the true circles
    (ball,) = pads_at(res, 5 + 9 * 0.8, 5 + 9 * 0.8)
    assert size(ball) == pytest.approx((0.4, 0.4), abs=1e-6)
    # a finer tolerance gives rounder pads
    fine = load_gerber(EXAMPLES / "bga100_0.8mm.gbr", tolerance=0.001)
    assert fine.geometry.area > res.geometry.area


def test_arcs_regions_and_polarity():
    res = load_gerber(EXAMPLES / "arcs_regions_polarity.gbr")
    assert len(res.polygons) == 18
    assert len(res.warnings) == 1 and "holes" in res.warnings[0]  # the ring and the pad with a hole

    (d_shape,) = pads_at(res, 2.5, 3.5)  # straight edge at x=2, half circle r=1.5 to the right
    assert d_shape.bounds == pytest.approx((2.0, 2.0, 3.5, 5.0), abs=0.002)
    assert d_shape.area == pytest.approx(math.pi * 1.5**2 / 2, rel=0.01)

    (rounded,) = pads_at(res, 8, 3.5)  # 4 x 3 with 0.5 corner radius
    assert rounded.bounds == pytest.approx((6, 2, 10, 5), abs=1e-6)
    assert rounded.area == pytest.approx(roundrect_area(4, 3, 0.5), rel=0.005)

    (slot,) = pads_at(res, 12 + 3 * math.cos(math.radians(-45)), 5 + 3 * math.sin(math.radians(-45)))
    assert slot.bounds == pytest.approx((11.75, 1.75, 15.25, 5.25), abs=0.002)  # quarter arc r=3, 0.5 wide
    assert slot.area == pytest.approx(0.5 * (math.pi * 3 / 2) + math.pi * 0.25**2, rel=0.02)

    (ring,) = pads_at(res, 19.5, 3.5)  # full circle r=1.5 drawn 0.5 wide
    assert len(ring.interiors) == 1
    assert ring.area == pytest.approx(math.pi * (1.75**2 - 1.25**2), rel=0.01)

    assert size(pads_at(res, 3, 8)[0]) == pytest.approx((2.0, 0.8), abs=1e-6)  # obround
    assert size(pads_at(res, 6, 8)[0]) == pytest.approx((0.8, 2.0), abs=1e-6)
    assert len(pads_at(res, 9, 8)[0].exterior.coords) - 1 == 6  # hexagon
    assert len(pads_at(res, 12, 8)[0].exterior.coords) - 1 == 3  # triangle
    tilted = pads_at(res, 15, 8)[0]  # 1.6 x 0.5 rotated by 30 degrees about its centre
    assert size(tilted) == pytest.approx((1.6 * 0.8660254 + 0.25, 0.8 + 0.5 * 0.8660254), abs=1e-6)
    assert tilted.centroid.coords[0] == pytest.approx((15, 8), abs=1e-6)
    assert len(pads_at(res, 21.6, 8)[0].interiors) == 1  # round pad with a hole

    # clear polarity: the 4 x 4 pad is cut into four 1.8 x 1.8 panes, nothing in the cross
    assert pads_at(res, 4, 13) == [] and pads_at(res, 4, 14.5) == []
    for x, y in ((2.9, 11.9), (5.1, 11.9), (2.9, 14.1), (5.1, 14.1)):
        (pane,) = pads_at(res, x, y)
        assert size(pane) == pytest.approx((1.8, 1.8), abs=1e-6)

    # aperture transformations: rotated 90 degrees, scaled to half, mirrored
    assert size(pads_at(res, 9, 13)[0]) == pytest.approx((0.8, 2.0), abs=1e-6)
    assert size(pads_at(res, 12, 13)[0]) == pytest.approx((0.8, 0.8 * 0.8660254), abs=1e-6)
    mirrored = pads_at(res, 15, 13)[0]
    assert pads_at(res, 15 + 0.6, 13 - 0.35)  # +30 degrees mirrored in X leans the other way
    assert not mirrored.buffer(1e-6).contains(tilted.centroid)


def test_legacy_inch_trailing_zero_omission():
    res = load_gerber(EXAMPLES / "legacy_inch_soic.gbr")
    assert res.units == "inch" and res.warnings == []
    assert len(res.polygons) == 29
    inch = 25.4
    assert res.geometry.bounds == pytest.approx((0.475 * inch, 0.37 * inch, 1.12 * inch, 1.195 * inch), abs=1e-6)
    (pin,) = pads_at(res, 0.85 * inch, 0.64 * inch)  # last pin of the second row, modal D03
    assert size(pin) == pytest.approx((0.024 * inch, 0.060 * inch), abs=1e-6)
    (stroke,) = pads_at(res, 0.51 * inch, 0.9 * inch)  # 20 mil stroke with a 50 x 30 mil aperture
    assert size(stroke) == pytest.approx((0.07 * inch, 0.03 * inch), abs=1e-6)


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.gbr")), ids=lambda p: p.name)
def test_every_example_makes_a_valid_job(path):
    res = load_gerber(path)
    for mode in ("accurate", "fast"):
        job = build_job(res.geometry, CutParams(mode=mode, inset=0.02, rotate=15, mirror=True))
        st = job.stats()
        assert st.pads > 0 and st.cut_total > 0 and st.seconds > 0
        data = graphtec.encode(job)
        assert data.count(b"M") - 1 == st.lifts_total
        assert all(p.is_valid for p in job.polygons)
