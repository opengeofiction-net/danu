"""Grading a waterway from the contours it crosses, by distance - G6b.

No Qt, no GDAL.
"""

from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from danu.core import geometry, profile


def test_between_two_crossings_a_vertex_takes_the_value_by_distance():
    levels, rejected, rev = profile.grade_along([(0, 100), (1000, 50)], [0, 250, 1000])
    assert levels == [100, 87.5, 50] and rejected == [] and not rev


def test_before_the_first_crossing_and_after_the_last_nothing_is_graded():
    levels, _, _ = profile.grade_along([(100, 80), (300, 60)], [0, 200, 400])
    assert levels == [None, 70, None]


def test_a_span_that_climbs_is_left_ungraded_and_reported():
    """Not forced down: that would invent ground nobody drew."""
    levels, rejected, _ = profile.grade_along(
        [(0, 100), (100, 80), (200, 90), (300, 60)], [50, 150, 250])
    assert levels[0] == 90 and levels[1] is None and levels[2] == 75
    assert rejected == [(100, 200, 80, 90)]


def test_a_span_longer_than_the_limit_is_rejected():
    far = profile.MAX_SEGMENT_M + 1
    levels, rejected, _ = profile.grade_along([(0, 100), (far, 50)], [far / 2])
    assert levels == [None] and len(rejected) == 1


def test_downstream_is_found_not_assumed():
    """Drawn upstream, the crossings rise along the way. Graded as drawn,
    every span would climb and nothing be levelled; water descends, so the
    higher end is upstream."""
    levels, rejected, rev = profile.grade_along([(0, 50), (1000, 100)], [0, 500, 1000])
    assert rev and rejected == [] and levels == [50, 75, 100]


def test_a_climb_is_judged_walking_downstream_in_a_river_drawn_upstream():
    levels, rejected, rev = profile.grade_along(
        [(0, 50), (100, 70), (200, 60), (300, 100)], [150, 250])
    # downstream runs 300 -> 0: 100, 60, 70 (climbs), 50
    assert rev and levels[1] == 80 and levels[0] is None
    assert rejected == [(100, 200, 70, 60)]      # in drawn order: 70 at 100 m, 60 at 200 m


def test_too_few_crossings_grade_nothing():
    assert profile.grade_along([(10, 40)], [0, 10, 20])[0] == [None, None, None]
    assert profile.grade_along([], [0])[0] == [None]


@given(st.lists(st.integers(0, 2000), min_size=2, max_size=12), st.booleans())
def test_a_graded_run_never_ascends(levels, drawn_upstream):
    """The spec's property: walked downstream, a graded waterway never climbs -
    whichever way round it was drawn."""
    known = [(30.0 * i, float(v)) for i, v in enumerate(levels)]
    d = [10.0 * i for i in range(3 * len(levels) - 2)]
    if drawn_upstream:
        known = [(d[-1] - x, v) for x, v in known]
    got, _, rev = profile.grade_along(known, d)
    # downstream found from the levels: the end at the higher crossing is upstream
    by_d = sorted(known)
    assert rev == (by_d[0][1] < by_d[-1][1])
    walk = list(reversed(got)) if rev else got
    run = []
    for v in [*walk, None]:
        if v is None:
            assert all(b <= a + 1e-9 for a, b in pairwise(run)), run
            run = []
        else:
            run.append(v)


def test_a_rejected_span_leaves_a_step_between_runs():
    """Contours at 0, 0, 1, 0 along a river contradict themselves. The climb is
    left ungraded, and the descent after it is still graded from the contour
    it crosses - so the levels step up across the gap. That is what the
    contours say, and a river never overrides a contour."""
    got, rejected, _ = profile.grade_along(
        [(0.0, 0.0), (30.0, 0.0), (60.0, 1.0), (90.0, 0.0)], [10.0 * i for i in range(10)])
    assert len(rejected) == 1 and rejected[0][:2] == (30.0, 60.0)
    assert got[3] == 0.0 and got[6] == 1.0
    assert got[4] is None and got[5] is None


def test_crossing_t_says_where_along_the_segment():
    import numpy as np
    a = np.array([[0.25, -1.0], [0.75, -1.0], [0.0, 5.0]])
    b = np.array([[0.25, 1.0], [0.75, 1.0], [1.0, 5.0]])
    t = geometry.crossing_t((0, 0), (1, 0), a, b)
    assert t[0] == pytest.approx(0.25) and t[1] == pytest.approx(0.75)
    assert np.isnan(t[2]), 'a parallel segment has no crossing'


def test_crossing_t_is_along_p_q_when_the_two_cross_obliquely():
    """Not a geometry where the two parameters coincide: p-q runs (0,0) to
    (2,2) and a-b (0,1) to (4,1), meeting at (1,1) - halfway along p-q and a
    quarter of the way along a-b."""
    import numpy as np
    t = geometry.crossing_t((0, 0), (2, 2), np.array([[0.0, 1.0]]), np.array([[4.0, 1.0]]))
    assert t[0] == pytest.approx(0.5)
