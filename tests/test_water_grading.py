"""Grading a waterway between the contours it crosses."""

import numpy as np
from hypothesis import given, strategies as st

from danu.water.constraints import densify, grade, seg_lengths


def test_two_crossings_grade_linearly_between_them():
    vals = [100, None, None, None, 50]
    graded, rejected = grade(vals, np.zeros(4))
    assert rejected == 0
    assert [graded[i] for i in range(5)] == [100, 87.5, 75, 62.5, 50]


def test_a_climbing_segment_is_rejected_not_forced():
    # the line and the ground describe different terrain; pinning the ground to
    # the line would cut a trench where the contours say there is a hill
    graded, rejected = grade([50, None, 100], np.zeros(2))
    assert graded == {}
    assert rejected == 1


def test_too_few_crossings_grades_nothing():
    assert grade([None, 100, None], np.zeros(2)) == ({}, 0)


def test_a_segment_longer_than_the_limit_is_rejected():
    # too much unseen ground to grade across
    graded, rejected = grade([100, None, 50], np.array([9000.0, 9000.0]))
    assert graded == {}
    assert rejected == 1


def _runs(graded):
    """The graded indices split into maximal consecutive runs. A rejected
    segment leaves a gap, and the runs either side are separate constraints."""
    out, run = [], []
    for i in sorted(graded):
        if run and i != run[-1] + 1:
            out.append(run); run = []
        run.append(i)
    if run:
        out.append(run)
    return out


@given(st.lists(st.integers(0, 2000), min_size=2, max_size=12))
def test_a_graded_run_never_ascends(levels):
    vals = []
    for lv in levels:
        vals += [lv, None, None]
    graded, _ = grade(vals, np.zeros(len(vals)))
    for run in _runs(graded):
        seq = [graded[i] for i in run]
        assert all(b <= a + 1e-9 for a, b in zip(seq, seq[1:]))


def test_a_rejected_segment_leaves_a_step_between_runs():
    """Contours at 0, 0, 1, 0 along a river contradict themselves. The climb is
    rejected, and the descent after it is still graded from the contour value it
    crosses - so the written constraints step up across the gap.

    That is correct rather than a lapse: those values are what the contours say,
    and a river never overrides a contour. The disagreement is real and is what
    danu.checks.rivers reports. Pinned here so the behaviour is deliberate."""
    vals = [0, None, None, 0, None, None, 1, None, None, 0, None, None]
    graded, rejected = grade(vals, np.zeros(len(vals)))
    assert rejected == 1
    runs = _runs(graded)
    assert len(runs) == 2
    assert graded[runs[0][-1]] == 0 and graded[runs[1][0]] == 1


def test_densify_keeps_the_endpoints_and_the_order():
    pts = [(0.0, 0.0), (1.0, 0.0)]
    out = densify(pts, 0.25)
    assert out[0] == pts[0] and out[-1] == pts[-1]
    assert all(b[0] >= a[0] for a, b in zip(out, out[1:]))


def test_segment_lengths_are_metres_and_shrink_with_latitude():
    a = seg_lengths([(0.0, 0.0), (1.0, 0.0)])
    b = seg_lengths([(0.0, 60.0), (1.0, 60.0)])
    assert 110_000 < a[0] < 112_000
    assert b[0] < a[0] * 0.55
