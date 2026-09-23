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
    usable = stray is not None
    if usable:
        try:
            usable = bool(stray.ExportToWkt())
        except RuntimeError:
            usable = False
    assert not usable                                     # whichever way this GDAL fails it


def test_the_published_dem_takes_its_compression_from_the_shared_file(tmp_path):
    """elevation.toml's [publish] keys were loaded and never read: the clamp
    hard-coded LERC_ZSTD, 0.05 and level 9, which happened to be what the file
    said. F1 made that file the one place a parameter lives, so a value there
    that nothing consumes is worse than no value at all - it reads as settable
    and is not."""
    import dataclasses

    import numpy as np
    from osgeo import gdal

    from danu.surface import params
    from danu.surface.land_clamp import clamp

    gdal.UseExceptions()
    rows, cols = 8, 8

    def write(name, arr, dtype, nodata=None):
        path = str(tmp_path / name)
        ds = gdal.GetDriverByName('GTiff').Create(path, cols, rows, 1, dtype)
        ds.SetGeoTransform((10.0, 1 / 1200, 0, 20.0, 0, -1 / 1200))
        band = ds.GetRasterBand(1)
        if nodata is not None:
            band.SetNoDataValue(nodata)
        band.WriteArray(arr)
        ds = None
        return path

    surface = write('rounded.tif', np.full((rows, cols), 50, np.float32), gdal.GDT_Float32)
    cons = write('cont.tif', np.full((rows, cols), -9999, np.int16), gdal.GDT_Int16, -9999)

    def compression_of(path):
        ds = gdal.Open(path)                  # held: the metadata dies with it
        return ds.GetMetadata('IMAGE_STRUCTURE').get('COMPRESSION')

    out = str(tmp_path / 'dem.tif')
    clamp(surface, cons, out)
    assert compression_of(out) == params.load().dem_compress == 'LERC_ZSTD'

    # and the file is what decides it, not the code
    other = dataclasses.replace(params.load(), dem_compress='DEFLATE')
    out2 = str(tmp_path / 'dem-deflate.tif')
    clamp(surface, cons, out2, params=other)
    assert compression_of(out2) == 'DEFLATE'
