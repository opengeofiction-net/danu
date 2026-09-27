"""Constraints, isofill, the incremental engine, ramps and hillshade."""

# The sentinel for "no constraint here", in the raster and in the arrays taken
# from it. Here rather than in build.py, which three modules were importing it
# from: it is a number, and reaching build.py for it drags in GDAL. That broke
# the UI job, which has Qt and no GDAL on purpose - the preview's clamp is pure
# numpy and needs the constant, not the module that writes the raster.
#
# It was also written out separately in build.py and land_clamp.py, which is
# the arrangement build.py's own comment warns about two lines below its copy:
# "a convention they each spell out separately is one that can quietly stop
# holding".
NODATA = -9999


# Rows per strip, chosen so one strip of one band is tens of megabytes whatever
# the width of the zone.
STRIP_BYTES = 64 << 20


def strips(rows, cols, itemsize=2, bands=4):
    """Row ranges covering the raster, sized to a bounded amount of memory.

    Here rather than in land_clamp, which is where it was written and which
    imports GDAL at module scope. It is arithmetic, and the editor wants it for
    walking two display rasters against each other - a caller that needs a
    bounded row range does not need the module that clamps a DEM.
    """
    per_row = cols * itemsize * bands
    step = max(1, min(rows, STRIP_BYTES // max(per_row, 1)))
    for y in range(0, rows, step):
        yield y, min(step, rows - y)
