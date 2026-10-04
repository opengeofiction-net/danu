"""The geometry a waterway is graded over: densified, and measured in metres."""

from itertools import pairwise

from danu.core.profile import densify, seg_lengths


def test_densify_keeps_the_endpoints_and_the_order():
    pts = [(0.0, 0.0), (1.0, 0.0)]
    out = densify(pts, 0.25)
    assert out[0] == pts[0] and out[-1] == pts[-1]
    assert all(b[0] >= a[0] for a, b in pairwise(out))


def test_segment_lengths_are_metres_and_shrink_with_latitude():
    a = seg_lengths([(0.0, 0.0), (1.0, 0.0)])
    b = seg_lengths([(0.0, 60.0), (1.0, 60.0)])
    assert 110_000 < a[0] < 112_000
    assert b[0] < a[0] * 0.55
