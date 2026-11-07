"""The drawn area's envelopes meet across a degree line their squares'
contours stop just short of: castellan's new squares end every contour a
fraction inside the square, and the cell centred on the shared line - in
neither square's contours - was outside both envelopes, 0 m on the DEM."""

import numpy as np
import pytest

pytest.importorskip('osgeo.gdal', reason='GDAL not available')

from danu.surface import drawn_mask

ND = -9999.0


def test_a_side_near_the_square_edge_is_taken_to_it():
    a = np.full((20, 20), ND)
    a[2:17, 3:19] = 100.0                  # 2, 3, 3 and 1 cells short of the edges
    assert drawn_mask.envelope(a, ND) == (0, 20, 0, 20)


def test_a_side_well_inside_stays_where_the_contours_stop():
    a = np.full((20, 20), ND)
    a[8:12, 4:16] = 100.0                  # 8 and 4 cells in
    assert drawn_mask.envelope(a, ND) == (8, 12, 4, 16)


def test_two_squares_short_of_their_shared_line_leave_no_gap_on_it():
    # a 1" grid over two squares side by side, its cells centred on whole
    # degrees as the build's are: cell N is centred on the shared line
    n = 3600
    gt = (64.0 - 0.5 / n, 1.0 / n, 0.0, 37.0 + 0.5 / n, 0.0, -1.0 / n)
    w, h = 2 * n + 1, n + 1
    a = np.full((h, w), ND)
    a[100:3500, 50:n - 1] = 500.0          # west square's contours end a cell short
    a[100:3500, n + 1:2 * n - 50] = 500.0  # the east's begin a cell past it
    covered = np.zeros(w, int)
    for _, _, x0, x1, y0, y1 in drawn_mask.squares(gt, w, h):
        env = drawn_mask.envelope(a[y0:y1, x0:x1], ND)
        if env is not None:
            covered[x0 + env[2]:x0 + env[3]] += 1
    assert (covered[n - 5:n + 6] >= 1).all(), 'a gap on the shared line'
    # each cell is one square's: taken to its edge, an envelope meets its
    # neighbour's and does not overlap it
    assert covered.max() == 1
