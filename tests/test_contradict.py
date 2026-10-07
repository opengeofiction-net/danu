"""A river level a contour beside it contradicts - G7c. No Qt, no GDAL.

A river running east along LAT, graded by hand, and contours put beside it
at known distances and levels.
"""

import pytest

from danu.core.square import Node, Square, SquareName, Way, WorkingSet
from danu.water import contradict

A = SquareName(125, -23)
LAT = -22.70
M_LAT = 1 / 110540
_ids = iter(range(1000, 10**6))
RIVER = [(125.30 + 0.0025 * k, LAT) for k in range(9)]           # ~2 km, every ~257 m


def ws():
    sq = Square(name=A, present=True, attrs={})
    return WorkingSet(centre=A, size=1, squares={A: sq}), sq


def way(sq, pts, ele):
    refs = []
    for lon, lat in pts:
        i = next(_ids)
        sq.nodes[i] = Node(id=i, lon=lon, lat=lat)
        refs.append(i)
    i = next(_ids)
    sq.ways[i] = Way(id=i, refs=refs, tags={'ele': str(ele)})
    return sq.ways[i]


def dist():
    import math
    k = 111320 * math.cos(math.radians(LAT))
    return [k * 0.0025 * j for j in range(len(RIVER))]


FLAT = [100.0] * len(RIVER)


def test_a_contour_beside_the_river_far_above_its_level_is_found():
    """The Merta's shape: a contour running along the river 10 m off it, 40 m
    above the river's level - from the river's 3rd vertex to its 5th."""
    w, sq = ws()
    c = way(sq, [(125.305, LAT + 10 * M_LAT), (125.31, LAT + 10 * M_LAT)], 140)
    (found,) = contradict.find(w, RIVER, dist(), FLAT)
    assert found.contour == (A, c.id) and found.diff == pytest.approx(40)
    assert found.apart_m == pytest.approx(10, abs=0.5)
    # and a cell either side of its ends: 30 m from them, 10 m off, is 28 m along
    assert found.d0 == pytest.approx(dist()[2] - 28.3, abs=6) and found.d1 == pytest.approx(dist()[4] + 28.3, abs=6)


def test_one_below_it_is_found_too():
    w, sq = ws()
    way(sq, [(125.305, LAT - 5 * M_LAT), (125.31, LAT - 5 * M_LAT)], 60)
    (found,) = contradict.find(w, RIVER, dist(), FLAT)
    assert found.diff == pytest.approx(-40)


def test_a_step_away_a_cell_off_is_a_steep_bank_not_a_fault():
    w, sq = ws()
    way(sq, [(125.305, LAT + 10 * M_LAT), (125.31, LAT + 10 * M_LAT)], 125)     # 25 m: a step
    way(sq, [(125.305, LAT + 40 * M_LAT), (125.31, LAT + 40 * M_LAT)], 175)     # 75 m, but 40 m off
    assert contradict.find(w, RIVER, dist(), FLAT) == []


def test_a_contour_crossing_where_the_river_is_at_its_level_is_not_one():
    """The river crosses the 100 m: graded there to 100 m, and its own
    crossing contour is at the river's level."""
    w, sq = ws()
    way(sq, [(125.31, LAT - 0.01), (125.31, LAT + 0.01)], 100)
    assert contradict.find(w, RIVER, dist(), FLAT) == []


def test_an_ungraded_stretch_says_nothing():
    w, sq = ws()
    way(sq, [(125.305, LAT + 10 * M_LAT), (125.31, LAT + 10 * M_LAT)], 140)
    levels = [100.0, 100.0, None, None, None, None, 100.0, 100.0, 100.0]
    assert contradict.find(w, RIVER, dist(), levels) == []


def test_the_level_said_is_the_river_graded_between_its_vertices():
    """Half way between the vertices at 160 m and 150 m: 155 m, not either."""
    w, sq = ws()
    x = 125.30625
    way(sq, [(x, LAT + 5 * M_LAT), (x + 0.00002, LAT + 5 * M_LAT)], 200)
    levels = [180.0 - 10 * j for j in range(len(RIVER))]
    (found,) = contradict.find(w, RIVER, dist(), levels)
    # the river falls a metre over the cell either side; at either vertex it is 5 m off
    assert found.level == pytest.approx(155, abs=1.5) and found.diff == pytest.approx(200 - found.level)


def test_within_a_cell_is_measured_not_boxed():
    """Off the river's end, 20 m on and 28 m north: 34 m from it, inside the
    box a cell round the contour, and not within a cell."""
    w, sq = ws()
    end = RIVER[-1][0]
    import math
    m_lon = 1 / (111320 * math.cos(math.radians(LAT)))
    way(sq, [(end + 20 * m_lon, LAT + 28 * M_LAT), (end + 0.01, LAT + 0.01)], 200)
    assert contradict.find(w, RIVER, dist(), FLAT) == []


def test_the_near_segment_of_a_long_contour_is_found():
    """The contour comes down from the north and runs along the river only on
    its last segment."""
    w, sq = ws()
    way(sq, [(125.30, LAT + 0.01), (125.305, LAT + 0.005), (125.305, LAT + 10 * M_LAT),
             (125.31, LAT + 10 * M_LAT)], 140)
    (found,) = contradict.find(w, RIVER, dist(), FLAT)
    assert found.apart_m == pytest.approx(10, abs=0.5)
    # the whole of the last segment, 125.305 to 125.31 and a cell either end
    assert found.d1 - found.d0 == pytest.approx(0.005 * 111320 * 0.9227 + 2 * 28.3, abs=12)
