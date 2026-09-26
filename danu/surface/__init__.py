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
