"""danu.surface.land_clamp's dealings with GDAL, at the unit level.

GDAL only, so it skips where there is none - and the golden job names it, as
it names tests/test_mercator_proj.py, because the pure job has no GDAL to run
it with.
"""

import pytest

osr = pytest.importorskip('osgeo.osr', reason='GDAL not available')
ogr = pytest.importorskip('osgeo.ogr', reason='GDAL not available')

from danu.surface.land_clamp import ogr_memory_driver, srs_for        # noqa: E402


def test_a_layer_takes_the_rasters_reference_or_none_but_never_an_empty_one():
    """An empty SpatialReference is not the same as no reference: a layer made
    with one answers GetSpatialRef with an object that raises when read, where
    None is simply nothing there. Measured all three ways before fixing it."""
    wgs84 = osr.SpatialReference()
    wgs84.ImportFromEPSG(4326)
    assert srs_for(None) is None and srs_for('') is None
    got = srs_for(wgs84.ExportToWkt())
    assert got is not None and 'WGS 84' in got.ExportToWkt()

    drv = ogr_memory_driver()      # 'MEM' on GDAL 3.11, 'Memory' before it
    for proj, has_reference in ((wgs84.ExportToWkt(), True), (None, False)):
        ds = drv.CreateDataSource('m')
        layer = ds.CreateLayer('l', geom_type=ogr.wkbPolygon, srs=srs_for(proj))
        ref = layer.GetSpatialRef()
        assert (ref is not None) is has_reference
        if has_reference:
            assert ref.ExportToWkt()                      # reads, rather than raising

    # and what the empty one this replaces would have left behind. Held, because
    # a layer whose data source has been collected is a dangling pointer, which
    # GDAL answers with a TypeError rather than a crash.
    #
    # How it goes wrong is this GDAL's business - here GetSpatialRef gives an
    # object that raises OGR Error on being read - so what is asked is only
    # that it is not a reference anyone can use, which is the reason srs_for
    # returns None instead.
    held = drv.CreateDataSource('e')
    empty = held.CreateLayer('l', geom_type=ogr.wkbPolygon, srs=osr.SpatialReference())
    stray = empty.GetSpatialRef()
    if stray is not None:
        try:
            assert not stray.ExportToWkt()
        except RuntimeError:
            pass
