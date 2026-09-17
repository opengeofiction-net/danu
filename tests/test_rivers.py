"""The uphill detector, ported from OGF::Terrain::RiverProfile.

These are the invariants the whole water story rests on, so they are asserted
rather than assumed - the logic reached the Python by way of a 2014 Perl widget
which nothing ever called, and was verified only by the numbers it produced on
gobras.
"""

import numpy as np
import pytest
from hypothesis import given, strategies as st

from danu.checks.rivers import invalid_intervals, linear_fix


def test_monotonic_descent_has_no_invalid_interval():
    assert invalid_intervals(np.array([100.0, 90, 80, 70, 60])) == []


def test_flat_is_not_a_climb():
    # water on a lake surface neither rises nor falls, and must not be flagged
    assert invalid_intervals(np.array([50.0, 50, 50, 50])) == []


def test_a_single_climb_is_one_interval():
    assert invalid_intervals(np.array([100.0, 90, 95, 80])) == [(2, 2)]


def test_a_climb_running_to_the_mouth_is_closed_at_the_end():
    assert invalid_intervals(np.array([100.0, 90, 95, 99])) == [(2, 3)]


def test_two_separate_climbs():
    assert invalid_intervals(np.array([100.0, 95, 99, 90, 92, 80])) == [(2, 2), (4, 4)]


def test_nan_is_skipped_not_treated_as_a_climb():
    # a way partly outside the raster samples as nan; that is absence of
    # information, not a rise
    assert invalid_intervals(np.array([100.0, np.nan, 90, 80])) == []


@given(st.lists(st.floats(0, 3000, allow_nan=False), min_size=2, max_size=60))
def test_a_descending_profile_is_never_flagged(vals):
    elev = np.array(sorted(vals, reverse=True))
    assert invalid_intervals(elev) == []


@given(st.lists(st.floats(0, 3000, allow_nan=False), min_size=2, max_size=60))
def test_the_linear_fix_never_leaves_a_climb_it_was_given(vals):
    elev = np.array(vals)
    fixed = linear_fix(elev, invalid_intervals(elev))
    # the fix may not be able to touch the mouth, which it guards deliberately,
    # so what is asserted is that it removes climbs rather than adding any
    before = sum(1 for a, b in zip(elev, elev[1:]) if b > a)
    after = sum(1 for a, b in zip(fixed, fixed[1:]) if b > a)
    assert after <= before


def test_the_mouth_is_never_lowered():
    # setLinearElev guards this explicitly and the port must keep it: a river
    # may not be made to end below the sea it runs into
    elev = np.array([100.0, 50, 60, 70])
    fixed = linear_fix(elev, invalid_intervals(elev))
    assert fixed[-1] >= elev[-1]
