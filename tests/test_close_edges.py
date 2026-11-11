"""close_edges: a working set's fill takes its edge as the end of the drawn
ground only where the square across it is not the zone's (isofill 0.13's
edge_void 0, 2026-11-11)."""

import numpy as np

from danu.core.square import SquareName
from danu.surface.build import close_edges

RES = 0.25                                   # four cells a degree, edge cells on the lines
GT = (24.875, RES, 0.0, 46.125, 0.0, -RES)   # 25..28 E by 43..46 N, pixel centres on degrees


def test_an_edge_is_closed_only_across_from_squares_outside_the_zone():
    mask = np.ones((13, 13), np.uint8)
    zone = {SquareName(lon, lat) for lon in range(24, 29) for lat in range(42, 47)}
    zone.discard(SquareName(24, 44))          # west of the set, the middle row: nothing drawn
    zone -= {SquareName(lon, 46) for lon in range(24, 29)}   # nothing north of the set
    out = close_edges(mask, GT, (25, 43, 28, 46), zone)
    assert out is not mask and mask.all(), 'a copy; the mask itself untouched'
    assert out[0].sum() == 0, 'the north edge, all across from nothing'
    west = out[:, 0]
    # rows by their own degree square: 46.0 and 45.x are N45, 44.x N44, 43.x N43
    assert west[5:9].tolist() == [0, 0, 0, 0], "across from N44E024's absence"
    assert west[9:12].all() and west[1:5].all(), 'across from squares of the zone'
    assert out[1:, -1].all() and out[-1, 1:].all(), 'east and south go on'
    assert out[1:-1, 1:-1].all(), 'nothing inside touched'


def test_a_set_whose_zone_is_only_itself_is_closed_all_round():
    mask = np.ones((13, 13), np.uint8)
    out = close_edges(mask, GT, (25, 43, 28, 46), {SquareName(lon, lat) for lon in range(25, 28) for lat in range(43, 46)})
    assert not out[0].any() and not out[-1].any() and not out[:, 0].any() and not out[:, -1].any()
    assert out[1:-1, 1:-1].all()


def test_an_open_edge_is_drawn_as_the_cell_inside_it():
    """The drawn area gives a cell on a shared degree line to the square
    south or east of it, so a set's north row and east column belong to
    squares the set build does not draw. Where the zone goes on, they are
    drawn as the cell inside them is - or the void floods from them."""
    mask = np.ones((13, 13), np.uint8)
    mask[0, :] = 0
    mask[:, -1] = 0
    mask[1, 3] = 0                              # undrawn just inside: stays undrawn on the edge
    zone = {SquareName(lon, lat) for lon in range(24, 29) for lat in range(42, 47)}
    out = close_edges(mask, GT, (25, 43, 28, 46), zone)
    assert out[0, 1:-1].tolist() == [1, 1, 0] + [1] * 8
    assert out[1:, -1].all()


def test_a_corner_closed_by_either_side_stays_closed():
    mask = np.ones((13, 13), np.uint8)
    zone = {SquareName(lon, lat) for lon in range(24, 29) for lat in range(42, 47)}
    zone.discard(SquareName(24, 45))           # west of the north-west square only
    out = close_edges(mask, GT, (25, 43, 28, 46), zone)
    assert out[0, 0] == 0, 'closed from the west; the north, open, does not reopen it'
    assert out[0, 1:].all()
