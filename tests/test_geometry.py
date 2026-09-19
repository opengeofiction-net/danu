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
