"""The local solve against the whole-raster one - phase 4's open question.

The spec asks it plainly: *is the local second pass good enough?* A cell's
first-pass value depends only on contours within ``radius``, so a box grown by
that much is exact inside; the second pass has no such property, and a box
solved against a rim held at the last whole-raster answer is an approximation.
If the seam shows, the preview loses most of its value.

So this does both and compares. Both surfaces come from the same constraints,
the same masks and the same isofill; the only difference is that one solved the
whole raster and the other solved a box around the edit.

Measured on the gobras 3x3 over eighteen edits the editor would accept, with
the patch covering the edit by two radii and solved with two radii of
clearance: it is wrong by at most 0.268 m and leaves nothing behind it out of
date. At 1 arcsecond the worst of six edits is 0.035 m. On the case this file
builds - a whole contour level deleted from the golden square - it is exact.

What makes it that good is that the second pass only moves cells the first pass
declined, and every answered cell is fixed: diffusion cannot cross a ring of
answered ground, so a change is confined to the region of unanswered cells it
lands in, and 99% of those regions are under 105 cells.
"""

import shutil
import tomllib
from pathlib import Path

import pytest

HERE = Path(__file__).parent
ROOT = HERE.parents[1]
SQUARE = HERE / 'S24E125_Los_Pizarrales.osm.xz'

gdal = pytest.importorskip('osgeo.gdal', reason='GDAL not available')
pytestmark = pytest.mark.skipif(shutil.which('isofill') is None, reason='isofill not on PATH')


def lock_params():
    from danu.surface import params
    with (HERE / 'params.lock').open('rb') as fh:
        lock = tomllib.load(fh)
    return params.load().with_arcsec(lock['arcsec'])


def solved(zone, work, params):
    """A whole-raster build, with the rasters the local solve needs."""
    import numpy as np
    from danu.surface import build

    result = build.build_dem(zone, work, params)
    assert result.dem is not None, 'the fixture built nothing'
    held = {}

    def read(path, dtype=None):
        ds = gdal.Open(str(path))            # held: the band dies with it
        held[str(path)] = ds
        a = ds.GetRasterBand(1).ReadAsArray()
        return a.astype(dtype) if dtype else a

    surface = read(work / 'rounded.tif', np.float32)
    constraints = read(result.constraints, np.float32)
    return {
        'surface': surface,
        'constraints': constraints,
        'mask': read(result.drawn_mask),
        'water': read(result.water_mask) if result.water_mask else None,
        'nodata': held[str(result.constraints)].GetRasterBand(1).GetNoDataValue(),
        'gt': gdal.Open(str(result.dem)).GetGeoTransform(),
        'result': result,
        'work': work,
    }


def a_level_worth_deleting(square):
    """Every contour at the lowest elevation the square draws more than once -
    a mapper deciding a level is wrong and taking it out.

    A single contour is not enough of an edit on this fixture. 39 of its 94
    contours are an exact copy of another, so deleting one changes no
    constraint cell at all - its twin burns them. Even a contour that is
    genuinely its own comes back: the one this first used sits between two
    others at its own elevation, so removing its five cells only had the fill
    put 401 m back where they were, and the surface did not move by so much as
    a millimetre. A test that asserts a local solve matches a global one after
    an edit that changed nothing asserts nothing."""
    contours = [w for w in square.ways.values() if w.ele is not None]
    at = {}
    for w in contours:
        at.setdefault(w.ele, []).append(w)
    levels = sorted(ele for ele, ws in at.items() if len(ws) > 1)
    assert levels, 'no elevation in the fixture is drawn more than once'
    return at[levels[0]]


def test_a_box_solved_against_a_held_rim_is_the_whole_rasters_answer(tmp_path):
    """The question itself. Delete a contour, solve the box around it holding
    the rim at the surface from before the edit, and compare with solving the
    whole raster after it.

    The comparison is over the edited ground - the box the contour occupied.
    The radius ring outside it is scaffolding: pass 1 there is truncated by the
    crop on purpose, which is why the box is grown before solving and shrunk
    before judging.
    """
    import numpy as np
    from danu.core import edits
    from danu.core.square import read_square, write_square
    from danu.surface import local

    p = lock_params()
    zone = tmp_path / 'before'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    before = solved(zone, tmp_path / 'wbefore', p)

    square = read_square(zone / SQUARE.name)
    victims = a_level_worth_deleting(square)
    coords = [(square.nodes[r].lon, square.nodes[r].lat)
              for w in victims for r in w.refs if r in square.nodes]
    history = edits.SetUndoStack()
    for way in victims:
        history.do(square, edits.DeleteWay(way.id))

    after_zone = tmp_path / 'after'
    after_zone.mkdir()
    write_square(square, after_zone / 'S24E125.osm.xz')
    after = solved(after_zone, tmp_path / 'wafter', p)

    gt = before['gt']
    ys = [int((lat - gt[3]) / gt[5]) for _, lat in coords]
    xs = [int((lon - gt[0]) / gt[1]) for lon, _ in coords]
    box = local.Box.around(ys, xs)

    whole = after['surface'].astype(np.float64)

    # the edit has to have done something, or this compares two copies of one
    # surface and would pass however wrong the local solve was
    moved = int((whole != before['surface'].astype(np.float64)).sum())
    assert moved > 50, f'deleting the level moved only {moved} cells'

    def solve(cover=None, slack=None):
        patch, good = local.resolve(after['constraints'], after['mask'], after['water'],
                                    before['surface'], box, p, cover=cover, slack=slack,
                                    nodata=after['nodata'])
        assert patch.shape == good.shape, 'the patch is not the box it says it is good for'
        # the scaffolding is cropped off: more is solved than is handed back,
        # and the ring between the two is where the first pass is truncated by
        # the crop and answers nothing
        c = 2 * p.fill_cells if cover is None else cover
        sl = 2 * p.fill_cells if slack is None else slack
        solved = box.grown(c, after['constraints'].shape).grown(
            local.reach(p, sl), after['constraints'].shape)
        assert good.cells < solved.cells, 'the patch is the whole solve, scaffolding and all'
        got = before['surface'].copy()
        got[good.slice] = patch
        err = np.abs(got.astype(np.float64) - whole)
        stale = err.copy()
        stale[good.slice] = 0
        # what the patch gets wrong, and what it leaves out of date around it
        return float(err[good.slice].max()), float(stale.max())

    # The smallest thing that could work: the edited box and a radius to see
    # the contours, nothing more. Both errors are real there, and they are
    # what cover and slack exist to remove.
    bare_wrong, bare_stale = solve(cover=0, slack=0)
    assert bare_wrong > 0.01, 'the minimal box is already exact - this edit is not testing the rim'
    assert bare_stale > 1.0, 'the minimal box leaves nothing stale - this edit does not travel'

    # and the defaults, two radii of each, measured rather than chosen. On this
    # edit they make the patch exact
    wrong, stale = solve()
    assert wrong == 0.0, f'the patch is {wrong:.6f} m out'
    assert stale == 0.0, f'the ground outside the patch is {stale:.3f} m out of date'

    # slack is what took it there. It is a small distance on this fixture -
    # sixty-one micrometres - because cover already holds the rim well away.
    # The number that chose two radii came from the gobras 3x3, where the worst
    # of eighteen edits goes from 2.231 m at no slack to 0.424 m at two and no
    # further; and what is left there is not the rim at all, but the second
    # pass inventing across a region of unanswered ground that runs past any
    # box worth solving.
    assert solve(slack=0)[0] > wrong, 'slack made no difference, so it is not being tested here'



def test_the_rim_is_what_bounds_it(tmp_path):
    """The boundary condition is the rim written from the previous answer, and
    nothing else. Hand the same box a rim of nonsense and the inside has to
    come out different - otherwise the rim is not being read and the agreement
    above would be luck.

    The box is put over ground the first pass could not answer, because that is
    the only ground the second pass moves: a box of answered cells is fixed
    from end to end and no rim would change it."""
    import numpy as np
    from danu.surface import build, local

    p = lock_params()
    zone = tmp_path / 'zone'
    zone.mkdir()
    shutil.copy(SQUARE, zone / SQUARE.name)
    built = solved(zone, tmp_path / 'work', p)

    classes_path = build.first_pass_classes(built['result'].constraints,
                                            built['result'].drawn_mask, p, built['work'])
    cds = gdal.Open(str(classes_path))            # held
    classes = cds.GetRasterBand(1).ReadAsArray()
    unanswered = np.argwhere((classes == build.UNREACHED) | (classes == build.ONE_ONLY))
    assert len(unanswered) > 100, 'the fixture has no ground the first pass declined'
    y, x = unanswered[len(unanswered) // 2]
    box = local.Box(int(x) - 5, int(y) - 5, int(x) + 5, int(y) + 5)

    # with no margin, so the rim is against the ground being solved. At the
    # default of two radii it is far enough away that lying about it changes
    # nothing measurable - which is the result, and would make this test pass
    # whether or not the rim was read at all
    honest, good = local.resolve(built['constraints'], built['mask'], built['water'],
                                 built['surface'], box, p, cover=0, slack=0, nodata=built['nodata'])
    nonsense = built['surface'] + np.float32(500.0)
    lied_to, _ = local.resolve(built['constraints'], built['mask'], built['water'],
                               nonsense, box, p, cover=0, slack=0, nodata=built['nodata'])
    differ = int((honest != lied_to).sum())
    assert differ > 0, 'the rim changed nothing, so the solve is not reading it'
