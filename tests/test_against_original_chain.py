"""End-to-end check of the native Gerber reader against the original tool chain.

tests/legacy/pic/*.pic were produced from examples/*.gbr with the original
pipeline (gerbv 2.6.1 --export=pdf --border=20, then pstoedit -f pic) and are
read with the original pic.py.  The pads must be the same shapes in the same
places.

Known, intended differences of the original chain (see README):
  * pstoedit flattens round pads to coarse 8-point diamonds; the native reader
    keeps them round within the configured tolerance.
  * gerbv drops the middle row of the smallest round pads in
    fine_pitch_sampler.gbr (3 of 27 flashes are missing from its PDF).
"""

import sys
from pathlib import Path

import pytest
from shapely import affinity
from shapely.geometry import Polygon
from shapely.ops import unary_union

from g2g.core.gerber import load_gerber
from g2g.core.toolpath import CutParams, build_job

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "legacy"))


def original_pads(name: str) -> list[Polygon]:
    import pic

    polys = []
    for stroke in pic.read_pic(str(ROOT / "legacy" / "pic" / f"{name}.pic")):
        if len(stroke) >= 3:
            p = Polygon([(x * 25.4, y * 25.4) for x, y in stroke])
            polys.append(p if p.is_valid else p.buffer(0))
    min_x = min(p.bounds[0] for p in polys)
    min_y = min(p.bounds[1] for p in polys)
    return [affinity.translate(p, -min_x, -min_y) for p in polys]


def native_pads(name: str) -> list[Polygon]:
    return build_job(load_gerber(ROOT.parent / "examples" / f"{name}.gbr").geometry, CutParams()).polygons


@pytest.mark.parametrize("name", ["corners", "test_tiny", "test_0.5mm_0402", "example1"])
def test_same_pads_as_original_chain(name):
    old, new = original_pads(name), native_pads(name)
    assert len(new) == len(old)
    old_u, new_u = unary_union(old), unary_union(new)
    # every outline within 3 micron (the PDF / pic round trip costs 1-2.5 micron)
    assert old_u.boundary.hausdorff_distance(new_u.boundary) < 0.003
    assert old_u.symmetric_difference(new_u).area < 0.005 * old_u.area


def test_fine_pitch_sampler_differs_only_in_round_pads():
    old, new = original_pads("fine_pitch_sampler"), native_pads("fine_pitch_sampler")
    old_u, new_u = unary_union(old), unary_union(new)

    # practically nothing the original cut lies outside the new pads (only the
    # corners of its diamonds stick out of the true circles by a few micron)
    assert old_u.difference(new_u.buffer(0.003)).area < 0.001 * old_u.area

    def is_round(p: Polygon) -> bool:
        return len(p.exterior.coords) - 1 >= 12

    straight = [p for p in new if not is_round(p)]
    round_pads = [p for p in new if is_round(p)]
    assert len(round_pads) == 27 and len(old) == len(new) - 3

    # straight-edged pads agree to within 3 micron
    for p in straight:
        assert p.difference(old_u.buffer(0.003)).area < 1e-6

    # round pads: the original has a smaller diamond inside 24 of them and lost 3
    missing = [p for p in round_pads if not p.intersects(old_u)]
    assert len(missing) == 3
    for p in round_pads:
        if p not in missing:
            covered = p.intersection(old_u).area / p.area
            assert 0.75 < covered < 0.85
