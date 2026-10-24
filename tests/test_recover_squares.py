"""recover_squares: the interval by height band, and contours that a coarse
simplification would make cross put back as the DEM drew them."""

import numpy as np
import pytest

gdal = pytest.importorskip('osgeo.gdal')

from danu.checks import crossings, loops  # noqa: E402
from danu.core import recover_squares as R  # noqa: E402
from danu.core.square import Node, Square, SquareName, Way, WorkingSet  # noqa: E402


def test_the_levels_by_band():
    bands = R.parse_levels('10:50,25:200,50')
    assert bands == [(10, 50), (25, 200), (50, None)]
    assert R.levels_for(bands, 430) == [0, 10, 20, 30, 40, 50, 75, 100, 125, 150, 175, 200, 250, 300, 350, 400]
    assert R.levels_for(bands, 37) == [0, 10, 20, 30]
    assert R.levels_for(R.parse_levels('25'), 60) == [0, 25, 50]
    assert R.parse_levels('10:50,25') == [(10, 50), (25, None)]
    for bad in ('0', '10:50,5:40,50', '10:50,25:200,50:400', '10,25'):
        with pytest.raises(ValueError):
            R.parse_levels(bad)


def dem(tmp_path):
    """A degree square of steep, wrinkled hills, 3 arcseconds - ground where a
    coarse tolerance folds small rings and pulls neighbours across."""
    n = 1201
    y, x = np.mgrid[0:n, 0:n] / (n - 1)
    z = (900 * np.exp(-((x - 0.5) ** 2 + (y - 0.5) ** 2) * 9)
         + 60 * np.sin(x * 70) * np.cos(y * 55) + 40 * np.sin((x + y) * 140))
    path = tmp_path / 'dem.tif'
    ds = gdal.GetDriverByName('GTiff').Create(str(path), n, n, 1, gdal.GDT_Int16)
    ds.SetGeoTransform((30 - 1 / 2400, 1 / 1200, 0, 46 + 1 / 2400, 0, -1 / 1200))
    ds.GetRasterBand(1).WriteArray(np.clip(z, 1, None).astype(np.int16))
    ds = None
    return path


def square_of(rings, name):
    """The contours as a square holds them: to 7 places, as OsmFile writes."""
    sq = Square(name=name, present=True, attrs={})
    nid = wid = 0
    for ele, ls in rings.items():
        if ele <= 0:
            continue
        for pts in ls:
            refs = []
            for lon, lat in pts:
                nid -= 1
                sq.nodes[nid] = Node(id=nid, lon=round(lon, 7), lat=round(lat, 7))
                refs.append(nid)
            wid -= 1
            sq.ways[wid] = Way(id=wid, refs=refs, tags={'contour': 'elevation', 'ele': str(ele)})
    return WorkingSet(centre=name, size=1, squares={name: sq})


def test_simplified_contours_never_cross_once_written(tmp_path, monkeypatch):
    path, name = dem(tmp_path), SquareName(30, 45)
    coarse = 4 / 1200                                    # four cells: far past the default quarter
    bands = R.parse_levels('10:50,25:200,50')
    rings, _, _ = R.contours_for_square(str(path), 30, 45, 10, coarse, 4, bands)
    ws = square_of(rings, name)
    assert crossings.find(ws) == [] and loops.find(ws) == []
    # and without the putting back, the same tolerance does cross: the test is of something
    monkeypatch.setattr(R, 'uncross', lambda drawn, made: None)
    bare, _, _ = R.contours_for_square(str(path), 30, 45, 10, coarse, 4, bands)
    raw = square_of(bare, name)
    assert crossings.find(raw) or loops.find(raw)
    nodes = lambda r: sum(len(p) for ls in r.values() for p in ls)  # noqa: E731
    full, _, _ = R.contours_for_square(str(path), 30, 45, 10, 0, 4, bands)
    assert nodes(rings) < nodes(full) * 0.6, 'most lines kept their simplification'
    # two runs of ContourGenerate over one raster give the same lines, so the
    # counts are comparable
    count = lambda r: len([p for ls in r.values() for p in ls])  # noqa: E731
    assert count(rings) == count(bare), 'putting lines back lost or gained some'


def test_rings_are_written_closed_onto_their_first_node(tmp_path, monkeypatch):
    """A ring's last point is its first node, not a second node at its
    place: Danu reads the second as an open line, and roantra's 39,971 rings
    were."""
    import sys

    from danu.core.square import read_square
    out = tmp_path / 'out'
    out.mkdir()
    monkeypatch.setattr(sys, 'argv', ['recover_squares', str(dem(tmp_path)), str(out), '--levels', '10:50,25:200,50'])
    R.main()
    (f,) = out.glob('*.osm.xz')
    sq = read_square(f)
    pos = lambda r: (sq.nodes[r].lon, sq.nodes[r].lat)  # noqa: E731
    contours = [w for w in sq.ways.values() if w.ele is not None and w.ele > 0]
    assert any(w.refs[0] == w.refs[-1] for w in contours), 'the hills make rings'
    assert not [w for w in contours if w.refs[0] != w.refs[-1] and pos(w.refs[0]) == pos(w.refs[-1])]
