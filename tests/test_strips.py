"""``strips`` has to partition the raster exactly.

It is a budgeting helper and looks like one, but two callers now depend on it
for their answer rather than for their memory. ``shade.compose`` writes each
strip into its own rows of the output, so a gap leaves those rows at zero -
transparent black, in the middle of the map - and an overlap composes them
twice, which is the same answer and merely slower.
``Scaling.range_for`` takes a min and a max per strip and combines them, so a
gap silently drops that ground out of the colour scale.

Neither fails loudly. Both produce a wrong surface, which is the thing the
editor and the build agreeing exists to prevent - so the property is asserted
rather than assumed from the two call sites agreeing about it.
"""

from itertools import pairwise

import pytest
from hypothesis import given
from hypothesis import strategies as st

from danu.surface import STRIP_BYTES, strips


@given(rows=st.integers(1, 40_000), cols=st.integers(1, 40_000),
       itemsize=st.integers(1, 200), bands=st.integers(1, 8))
def test_the_strips_cover_every_row_exactly_once(rows, cols, itemsize, bands):
    got = list(strips(rows, cols, itemsize=itemsize, bands=bands))
    assert got, 'no strips at all'
    covered = []
    for y, h in got:
        assert h > 0, f'a strip of {h} rows'
        covered.append((y, y + h))
    # contiguous, in order, from 0 to rows
    assert covered[0][0] == 0
    assert covered[-1][1] == rows
    for (_, end), (start, _) in pairwise(covered):
        assert start == end, f'a gap or an overlap at row {end}'
    assert sum(h for _, h in got) == rows


@given(rows=st.integers(1, 40_000), cols=st.integers(1, 40_000),
       itemsize=st.integers(1, 200), bands=st.integers(1, 8))
def test_a_strip_stays_inside_the_budget_unless_one_row_cannot(rows, cols, itemsize, bands):
    per_row = cols * itemsize * bands
    for _, h in strips(rows, cols, itemsize=itemsize, bands=bands):
        if per_row <= STRIP_BYTES:
            assert h * per_row <= STRIP_BYTES, 'a strip over the budget'
        else:
            # a single row is already over it; one row at a time is the least
            # it can do, and refusing would be worse than going over
            assert h == 1


def test_the_two_spellings_of_a_per_cell_budget_agree():
    """compose passes its cost as the itemsize with one band, range_for passes
    a real band count. The product is what is budgeted, so 104 x 1 and 1 x 104
    are the same strips - which is why the first spelling had to be a comment
    and not a coincidence."""
    assert (list(strips(14367, 15291, itemsize=104, bands=1))
            == list(strips(14367, 15291, itemsize=1, bands=104)))


@pytest.mark.parametrize('rows, cols', [(1, 1), (1, 10_000_000), (7, 3)])
def test_the_awkward_shapes(rows, cols):
    got = list(strips(rows, cols))
    assert sum(h for _, h in got) == rows and got[0][0] == 0
