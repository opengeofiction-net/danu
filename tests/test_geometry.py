"""danu.core.geometry: crossings and touches, over many segments at once."""

import numpy as np
import pytest
from hypothesis import given, settings, strategies as st

from danu.core import geometry as g

A = np.array([[0.0, 0.0], [0.0, 2.0], [5.0, 5.0], [0.0, 10.0]])
B = np.array([[2.0, 0.0], [2.0, 2.0], [7.0, 5.0], [2.0, 10.0]])      # four east-west segments


def test_a_segment_across_is_a_crossing_and_beside_is_not():
    assert list(g.crossings((1, -1), (1, 3), A, B)) == [True, True, False, False]
    assert list(g.crossings((3, -1), (3, 3), A, B)) == [False] * 4
    assert not g.crossings((0, 0), (1, 1), np.zeros((0, 2)), np.zeros((0, 2))).any()


def test_touching_at_an_endpoint_or_along_is_a_touch_not_a_crossing():
    # ends on the first segment
    assert list(g.crossings((1, -1), (1, 0), A, B)) == [False] * 4
    assert list(g.touches((1, -1), (1, 0), A, B)) == [True, False, False, False]
    # starts at the first segment's end node and goes away: shared node
    assert list(g.touches((2, 0), (3, 1), A, B)) == [True, False, False, False]
    assert not g.crossings((2, 0), (3, 1), A, B).any()
    # along it
    assert list(g.touches((0.5, 0), (1.5, 0), A, B)) == [True, False, False, False]
    assert not g.crossings((0.5, 0), (1.5, 0), A, B).any()
    # clear of everything
    assert not g.touches((3, 1), (4, 1), A, B).any()


@settings(max_examples=300, deadline=None)
@given(st.lists(st.floats(-10, 10), min_size=8, max_size=8))
def test_a_proper_crossing_is_symmetric(v):
    p, q, a, b = np.array(v[0:2]), np.array(v[2:4]), np.array(v[4:6]), np.array(v[6:8])
    one = g.crossings(p, q, a[None, :], b[None, :])[0]
    other = g.crossings(a, b, p[None, :], q[None, :])[0]
    assert one == other


def test_nearest_point_on_segments():
    t, d = g.nearest_point_on_segments((1, 1), A, B)
    assert t[0] == pytest.approx(0.5) and d[0] == pytest.approx(1.0)
    assert t[1] == pytest.approx(0.5) and d[1] == pytest.approx(1.0)
    t, d = g.nearest_point_on_segments((-3, 0), A, B)
    assert t[0] == 0 and d[0] == pytest.approx(3.0)


def test_simplify_keeps_the_ends_and_the_corners_and_drops_the_rest():
    line = [(float(i), 0.0) for i in range(11)]                    # straight: only the ends survive
    assert g.simplify(line, 0.5) == [(0.0, 0.0), (10.0, 0.0)]
    corner = [(0.0, 0.0), (1.0, 0.1), (2.0, 0.0), (3.0, 0.1), (4.0, 0.0), (4.0, 1.0), (4.0, 2.0), (4.1, 3.0), (4.0, 4.0)]
    out = g.simplify(corner, 0.3)
    assert out[0] == (0.0, 0.0) and out[-1] == (4.0, 4.0) and (4.0, 0.0) in out and len(out) == 3
    tight = g.simplify(corner, 0.05)                               # too tight to drop anything but the exactly collinear
    assert len(tight) == len(corner) - 1 and (4.0, 1.0) not in tight
    assert g.simplify([(1.0, 1.0)], 1.0) == [(1.0, 1.0)] and g.simplify([], 1.0) == []


@settings(max_examples=200, deadline=None)
@given(st.lists(st.tuples(st.floats(-100, 100), st.floats(-100, 100)), min_size=2, max_size=40),
       st.floats(0.01, 10))
def test_simplified_points_are_a_subsequence_within_tolerance(pts, tol):
    out = g.simplify(pts, tol)
    assert out[0] == tuple(pts[0]) and out[-1] == tuple(pts[-1])
    # a subsequence: each kept point matched in order, duplicates and all
    idx, k = [], 0
    for p in out:
        while tuple(pts[k]) != p:
            k += 1
        idx.append(k)
        k += 1
    a = np.array(pts, dtype=float)
    for (i, s), (j, e) in zip(zip(idx, out), zip(idx[1:], out[1:])):
        d = np.array([g.nearest_point_on_segments(p, np.array([s]), np.array([e]))[1][0] for p in a[i:j + 1]])
        assert (d <= tol + 1e-9).all()
