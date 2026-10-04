"""Grading a waterway from the contours it crosses, by distance - G6b.

``grade_along`` is the batch grader's rule (``profile.grade``) over distance
rather than cell index, for the editor. No Qt, no GDAL.
"""

import random

import pytest

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


def test_it_agrees_with_the_batch_grader_where_index_is_distance():
    """Over points evenly spaced, distance and index are the same measure,
    and the two graders must give the same levels: two hundred random
    profiles, the way densify's merge was checked."""
    rng = random.Random(20261004)
    for _ in range(200):
        n = rng.randint(5, 40)
        vals = [None] * n
        for i in sorted(rng.sample(range(n), rng.randint(2, min(6, n)))):
            vals[i] = rng.choice((10, 20, 30, 40, 50, 60))
        known = [v for v in vals if v is not None]
        if known[0] < known[-1]:
            continue                # the batch grader assumes drawn = downstream
        seg = [10.0] * (n - 1)
        batch, _ = profile.grade(vals, seg)
        mine, _, rev = profile.grade_along(
            [(i * 10.0, v) for i, v in enumerate(vals) if v is not None],
            [i * 10.0 for i in range(n)])
        assert not rev
        for i in range(n):
            assert (batch.get(i) is None) == (mine[i] is None), (vals, i)
            if mine[i] is not None:
                assert mine[i] == pytest.approx(batch[i])


def test_crossing_t_says_where_along_the_segment():
    import numpy as np
    a = np.array([[0.25, -1.0], [0.75, -1.0], [0.0, 5.0]])
    b = np.array([[0.25, 1.0], [0.75, 1.0], [1.0, 5.0]])
    t = geometry.crossing_t((0, 0), (1, 0), a, b)
    assert t[0] == pytest.approx(0.25) and t[1] == pytest.approx(0.75)
    assert np.isnan(t[2]), 'a parallel segment has no crossing'
