#!/bin/bash
#
# Build one elevation zone from its contour squares - see Admin:Elevation process
#
#   buildDemZone.sh <zone>
#
# Reads /opt/opengeofiction/elevation/osm-squares/<zone>/*.osm and publishes to
# /opt/opengeofiction/sync-to-ogf/dem/<zone>, which reaches
# data.opengeofiction.net/dem/<zone> through sync-to-ogf@dem.
#
# Run as the ogf user, by dem-build.service or by hand. One zone at a time; the
# whole set is buildDemData.sh.
#
# The parameters below are not arbitrary - each was measured by rebuilding
# zone-roantra and differencing against the DEM the old process published:
#
#   ARCSEC=1        3" loses 80% of the contour geometry to rasterisation, and
#                   halves again to 2.44 m RMS at 1". Compressed, every zone's
#                   DEM at 1" is half a gigabyte for the whole planet
#   FILL_METRES     an unbounded fill extrapolates into squares with no data at
#                   all: 39 m RMS zone wide and ten minutes, against 3.5 m and
#                   six seconds bounded. Tighter than this leaves holes where
#                   contours are genuinely sparse
#   SMOOTH_CELLS    hillshade is a derivative, so it renders the slope
#                   discontinuity at every contour as a visible band. No
#                   interpolator avoids it - the best of them, r.fillnulls
#                   bicubic, has the lowest error of any tested and still bands.
#                   Only a low pass removes it, so the hillshade gets a smoothed
#                   copy and the DEM does not
#
set -e

ZONE=${1:?usage: buildDemZone.sh <zone>}

# Overridable so the pipeline can be run against a copy off the server, which
# is how it gets tested against zone-roantra's known good output
OGF=${OGF:-/opt/opengeofiction}
TOOLS=${TOOLS:-${OGF}/OGF-terrain-tools}
BASE=${BASE:-${OGF}/elevation}
SRC=${BASE}/osm-squares/${ZONE}
WORK=${BASE}/build/${ZONE}
PUB=${PUB:-${OGF}/sync-to-ogf/dem}/${ZONE}

ARCSEC=${ARCSEC:-1}                     # master DEM resolution
HGT_ARCSEC=${HGT_ARCSEC:-3}             # .hgt archive and legacy zip stay at 1201
FILL_METRES=${FILL_METRES:-1850}
SMOOTH_CELLS=${SMOOTH_CELLS:-5}
RAMP=${TOOLS}/etc/dem_relief.ramp
# Water areas for the zone, if there are any: coastline plus whatever is mapped
# as natural=water instead, which for an inland sea is usual. Used only to tell
# land at sea level from the sea itself - the squares remain the elevation
# source of truth. Without it enclosed water reads 1 m instead of 0
WATER=$(ls ${BASE}/water/${ZONE}.osm ${BASE}/water/${ZONE}.osm.pbf 2>/dev/null | head -1)
OSMCONF=${TOOLS}/etc/dem_osmconf.ini

# GDAL's default osmconf.ini ignores ele on every layer, so reading a contour
# square with it yields an empty DEM and no error. The squares also carry
# negative ids, which the custom node index cannot handle
export OSM_CONFIG_FILE=${OSMCONF}
export OSM_USE_CUSTOM_INDEXING=NO
# No .aux.xml sidecars: they double the file count in the hgt archive and would
# be published alongside every raster
export GDAL_PAM_ENABLED=NO

[ -d "${SRC}" ] || { echo "no such zone: ${SRC}" >&2; exit 1; }
[ -f "${RAMP}" ] || { echo "no relief ramp at ${RAMP}" >&2; exit 1; }

mkdir -p ${WORK} ${PUB}

# One build of a zone at a time. The timer and a manual run must not both be
# writing the same working directory
exec 9>${WORK}/.lock
if ! flock -n 9; then
	echo "${ZONE}: another build is in progress, giving up" >&2
	exit 1
fi

RES=$(python3 -c "print(${ARCSEC}/3600)")
HGT_RES=$(python3 -c "print(${HGT_ARCSEC}/3600)")
say() { echo "=== ${ZONE}: $* ==="; }

# ---------------------------------------------------------------- extent
# Which degree squares actually hold constraints, and the grids to build them
# on - see demZoneExtent.py for why that is decided by reading the files rather
# than by taking the extent of the collected geometry
say extent
eval "$(${TOOLS}/bin/demZoneExtent.py ${SRC} ${ARCSEC})"
if [ "${SQUARES:-0}" -eq 0 ]; then
	# Not a failure: templates are laid out before the drawing starts, so a zone
	# can legitimately have nothing in it yet
	echo "  ${BLANK:-0} squares, none with contours - nothing to build yet" >&2
	exit 0
fi
echo "  ${SQUARES} squares with contours (${BLANK} blank), ${WEST}..${EAST} by ${SOUTH}..${NORTH}, ${SQ_DEGREES} square degrees"

# fill distance in cells, from a distance in metres, so that changing ARCSEC
# does not silently change how far the fill reaches
FILL_CELLS=$(python3 -c "print(max(1, round(${FILL_METRES} / (${ARCSEC} * 30.87))))")
echo "  fill bounded to ${FILL_METRES} m = ${FILL_CELLS} cells at ${ARCSEC}\""

# ---------------------------------------------------------------- collect
# Every way carrying a numeric ele is a constraint: contours, and the water
# edges at ele 0. Ways without one - the frame, stray tagging - are ignored.
#
# Read with closed_ways_are_polygons emptied, which is the difference between a
# coastline being a constraint and not being one. A coastline is drawn closed
# and tagged natural=coastline, and natural is on GDAL's list, so the driver
# calls the way an area and files it under multipolygons - a layer this reads
# nothing from, and which does not carry ele anyway. The contours survive only
# because they are tagged with nothing but ele.
#
# Silently, and the sea then has nothing holding it down: the fill runs 1,850 m
# out from the lowest contour it can see and the zero line lands there instead
# of on the shore. On zone-axian that put 99% of the published ele=0 vertices
# more than 500 m out to sea, a median of 1,693 m.
#
# Derived from the one file rather than kept as a second copy, because the
# water step below wants the opposite - natural=water has to be an area there.
say collect
sed 's/^closed_ways_are_polygons=.*/closed_ways_are_polygons=/' \
	${OSMCONF} > ${WORK}/osmconf-lines.ini
rm -f ${WORK}/contours.gpkg
first=1
for f in ${SRC}/*.osm; do
	[ -e "${f}" ] || continue
	if [ ${first} -eq 1 ]; then
		OSM_CONFIG_FILE=${WORK}/osmconf-lines.ini \
			ogr2ogr -f GPKG ${WORK}/contours.gpkg "${f}" lines \
			-where "ele IS NOT NULL" -nln contour -nlt LINESTRING >/dev/null
		first=0
	else
		OSM_CONFIG_FILE=${WORK}/osmconf-lines.ini \
			ogr2ogr -f GPKG -append ${WORK}/contours.gpkg "${f}" lines \
			-where "ele IS NOT NULL" -nln contour >/dev/null
	fi
done
# ele is a string, and not every string is a height. Squares carry ele=TBD on
# lake outlines nobody has surveyed yet, ele=tbd on peaks, the odd ele=169s
# typo - and gdal_rasterize -a ele coerces each of them to 0, planting a sea
# level constraint across whatever the way runs over. Worse than no constraint,
# since the fill then drags the ground around it down to meet the line.
#
# Cleaned here rather than filtered on the way in: the -where above goes to the
# OSM driver, whose OGR SQL has no pattern test this needs, and the GeoPackage
# is SQLite and does
NONNUM="NOT ((ele GLOB '[0-9]*' OR ele GLOB '-[0-9]*') AND ele NOT GLOB '*[^-0-9.]*')"
DROPPED=$(ogrinfo -q ${WORK}/contours.gpkg -dialect SQLite \
	-sql "SELECT DISTINCT ele FROM contour WHERE ${NONNUM}" 2>/dev/null |
	sed -n 's/^  ele (String) = //p' | paste -sd' ')
if [ -n "${DROPPED}" ]; then
	echo "  ignoring ways whose ele is not a number: ${DROPPED}"
	ogrinfo -q ${WORK}/contours.gpkg -dialect SQLite \
		-sql "DELETE FROM contour WHERE ${NONNUM}" >/dev/null
fi

FEATURES=$(ogrinfo -so -al ${WORK}/contours.gpkg 2>/dev/null |
	sed -n 's/^Feature Count: //p')
if [ ! -f ${WORK}/contours.gpkg ] || [ "${FEATURES:-0}" -eq 0 ]; then
	# Not a failure. A zone's directory holds the blank templates handed out to
	# mappers - one frame way, no contours - and a zone which is all templates
	# has nothing to build yet rather than something wrong with it
	echo "${ZONE}: no contours in any square, nothing to build yet" >&2
	exit 0
fi
echo "  ${FEATURES} constraint lines"

# Water with nothing holding it at sea level is the largest error this pipeline
# can produce - 46 m RMS over the water in the one roantra square the water file
# did not reach - and it is silent, because the result looks like plausible
# terrain. A zone with no zero constraint anywhere either has no sea, which is
# fine, or has sea nobody has drawn a coastline for, which is not
ZEROS=$(ogrinfo -q -al -where "ele = 0" ${WORK}/contours.gpkg 2>/dev/null |
	grep -c '^OGRFeature' || true)
echo "  ${ZEROS} of them at ele 0, holding sea level"
if [ "${ZEROS}" -eq 0 ]; then
	echo "  WARNING: no ele 0 constraint anywhere in this zone. If it has sea," >&2
	echo "  its squares need coastline, or the water will interpolate upward" >&2
fi

# ---------------------------------------------------------------- rasterise
say "rasterise at ${ARCSEC}\""
rm -f ${WORK}/cont.tif
# Int16, not Int32: elevations fit with room to spare and so does the nodata,
# and at 1 arcsecond the wider type costs 1.7 GB of the clamp's working set
gdal_rasterize -q -a ele -a_nodata -9999 -init -9999 -ot Int16 \
	-tr ${RES} ${RES} -te ${TE} -co TILED=YES -co COMPRESS=DEFLATE \
	${WORK}/contours.gpkg ${WORK}/cont.tif
gdalinfo ${WORK}/cont.tif | sed -n 's/^Size is/  size/p'

# ---------------------------------------------------------------- interpolate
say interpolate
rm -f ${WORK}/filled.tif ${WORK}/rounded.tif ${WORK}/dem.tif
gdal_fillnodata.py -q -md ${FILL_CELLS} -si 0 -co TILED=YES -co COMPRESS=DEFLATE \
	${WORK}/cont.tif ${WORK}/filled.tif
# What the bounded fill could not reach has no elevation information at all, and
# becomes zero - which is what the old process did implicitly by initialising
# its tiles to zero
# rint, not truncation: the fill returns floats, and truncating puts every
# coastal cell below a metre onto zero
gdal_calc.py --quiet --hideNoData -A ${WORK}/filled.tif --outfile=${WORK}/rounded.tif \
	--calc="where(A==-9999,-9999,rint(A))" --type=Int16 --NoDataValue=-9999 --overwrite \
	--co TILED=YES --co COMPRESS=DEFLATE --co PREDICTOR=2

# Water areas as a mask, where the zone has a water file. natural=water states
# that its interior is water; a closed coastline ring does not, being equally
# able to describe an island
WATER_MASK=
if [ -n "${WATER}" ]; then
	say "water areas from $(basename ${WATER})"
	rm -f ${WORK}/water-areas.gpkg ${WORK}/water-mask.tif
	ogr2ogr -f GPKG ${WORK}/water-areas.gpkg "${WATER}" multipolygons \
		-where "natural='water'" -nln water >/dev/null
	ogrinfo -so -al ${WORK}/water-areas.gpkg 2>/dev/null |
		grep -i 'feature count' | sed 's/^/  /'
	gdal_rasterize -q -burn 1 -init 0 -ot Byte -tr ${RES} ${RES} -te ${TE} \
		-co TILED=YES -co COMPRESS=DEFLATE \
		${WORK}/water-areas.gpkg ${WORK}/water-mask.tif
	WATER_MASK=${WORK}/water-mask.tif
else
	echo "  no water file at ${BASE}/water/${ZONE}.osm - enclosed water will" >&2
	echo "  read 1 m rather than 0, which shows in the relief rasters" >&2
fi

# Land at sea level is not the sea. Flat coastal ground whose nearest constraint
# is the coastline interpolates to zero, and zero is transparent in the relief
# ramp, so it would vanish from the map - 64% of the low land in zone-roantra
# did
rm -f ${WORK}/dem.tif
${TOOLS}/bin/demLandClamp.py ${WORK}/rounded.tif ${WORK}/cont.tif ${WORK}/dem.tif \
	${WATER_MASK}

# ---------------------------------------------------------------- smooth
# Box filter through a VRT kernel, which GDAL streams block by block, so this
# costs no memory whatever the size of the zone. For hillshading only.
say "smooth ${SMOOTH_CELLS} cells, for hillshade only"
rm -f ${WORK}/smooth.vrt ${WORK}/smooth.tif
gdal_translate -q -of VRT ${WORK}/dem.tif ${WORK}/smooth.vrt
python3 - ${WORK}/smooth.vrt ${SMOOTH_CELLS} <<'PY'
import sys
path, n = sys.argv[1], int(sys.argv[2])
text = open(path).read()
kernel = (f'<Kernel normalized="1"><Size>{n}</Size>'
          f'<Coefs>{" ".join(["1"] * n * n)}</Coefs></Kernel>')
text = (text.replace('<SimpleSource>', '<KernelFilteredSource>')
            .replace('</SimpleSource>', kernel + '</KernelFilteredSource>'))
open(path, 'w').write(text)
PY
gdal_translate -q -ot Int16 -co TILED=YES -co COMPRESS=DEFLATE \
	${WORK}/smooth.vrt ${WORK}/smooth.tif

# ---------------------------------------------------------------- derivative
# One 3" copy of the master, used by three things: the contour lines, the .hgt
# archive and the legacy zip. Contours come from here rather than the 1" master
# deliberately - at 1" the same lines carry three times the vertices, which
# triples what the render databases hold to draw a line 0.2 to 0.6 px wide
say "3\" derivative, for contours, hgt and the legacy zip"
rm -f ${WORK}/dem-hgtres.tif
gdalwarp -q -overwrite -r average -te ${TE_HGT} -tr ${HGT_RES} ${HGT_RES} \
	-ot Int16 -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2 \
	${WORK}/dem.tif ${WORK}/dem-hgtres.tif
gdalinfo ${WORK}/dem-hgtres.tif | sed -n 's/^Size is/  3 arcsec size/p'

# ---------------------------------------------------------------- rasters
# Mercator, as the styles expect, and hillshaded there rather than in degrees -
# gdaldem on a lat/lon raster treats degrees as metres.
MERC="+proj=merc +ellps=sphere +R=6378137 +a=6378137 +units=m"
warp() {                            # warp <src> <metres> <out>
	gdalwarp -q -overwrite -t_srs "${MERC}" -r bilinear -tr $2 $2 \
		-co TILED=YES -co COMPRESS=DEFLATE -co BIGTIFF=IF_SAFER $1 $3
}
shade() {                           # shade <src> <zfactor> <out>
	gdaldem hillshade -q -z $2 -compute_edges \
		-co TILED=YES -co COMPRESS=DEFLATE $1 $3
}

say rasters
FINE=$(python3 -c "print(round(${ARCSEC} * 30.87))")
warp ${WORK}/smooth.tif ${FINE} ${WORK}/merc-fine.tif
for m in 500 1000 5000; do warp ${WORK}/dem.tif ${m} ${WORK}/merc-${m}.tif; done

# z factor 2 is what cyclogf reads, 5 what the topo layer reads at z9-17. Same
# DEM, two strengths - the old process produced both and named neither clearly
# Named for the z factor, not the resolution: the resolution is a property of
# the zone's DEM and changing it must not rename the files consumers read
shade ${WORK}/merc-fine.tif 2 ${WORK}/hillshade-z2.tif
shade ${WORK}/merc-fine.tif 5 ${WORK}/hillshade-z5.tif
shade ${WORK}/merc-500.tif  4 ${WORK}/hillshade-500.tif
shade ${WORK}/merc-1000.tif 7 ${WORK}/hillshade-1000.tif
shade ${WORK}/merc-5000.tif 7 ${WORK}/hillshade-5000.tif

for m in 500 5000; do
	gdaldem color-relief -q -alpha -co TILED=YES -co COMPRESS=DEFLATE \
		${WORK}/merc-${m}.tif ${RAMP} ${WORK}/relief-${m}.tif
done

# ---------------------------------------------------------------- contours out
say contours
rm -f ${WORK}/contours-out.gpkg ${WORK}/contours-${ZONE}.osm.pbf
gdal_contour -q -a ele -i 10 ${WORK}/dem-hgtres.tif ${WORK}/contours-out.gpkg
${TOOLS}/bin/demContoursToOsm.py ${WORK}/contours-out.gpkg \
	${WORK}/contours-${ZONE}.osm.pbf --zone ${ZONE} \
	--id-blocks ${BASE}/id-blocks.conf

# ---------------------------------------------------------------- hgt archive
# The .hgt set is an archive and a recovery path, not the master any more, so it
# stays at 1201 samples: the convention only really supports 1201 and 3601, and
# 3601 for every zone would be 4.6 GB to publish for no consumer
say "hgt archive at ${HGT_ARCSEC}\""
rm -rf ${WORK}/hgt; mkdir -p ${WORK}/hgt
for lat in $(seq ${SOUTH} $((NORTH - 1))); do
	for lon in $(seq ${WEST} $((EAST - 1))); do
		name=$(python3 -c "
lat, lon = ${lat}, ${lon}
print(f'{\"N\" if lat >= 0 else \"S\"}{abs(lat):02d}{\"E\" if lon >= 0 else \"W\"}{abs(lon):03d}')")
		h=$(python3 -c "print(${HGT_ARCSEC}/7200)")
		gdal_translate -q -of SRTMHGT -projwin \
			$(python3 -c "h=${HGT_ARCSEC}/7200; print(f'{${lon}-h:.9f} {${lat}+1+h:.9f} {${lon}+1+h:.9f} {${lat}-h:.9f}')") \
			${WORK}/dem-hgtres.tif ${WORK}/hgt/${name}.hgt 2>/dev/null || \
			echo "  ${name}: skipped" >&2
	done
done
ls ${WORK}/hgt | wc -l | sed 's/^/  hgt files: /'

# ---------------------------------------------------------------- legacy zip
# tiles04 still reads seven files by their old names, and unzips with -j, so the
# zip is flat. It stays at 3" and DEFLATE: that server is Ubuntu 20.04 with GDAL
# 3.0.4, which predates ZSTD and LERC, and 1" rasters would grow its tree ninefold
say "legacy zip for tiles04"
LEG=${WORK}/legacy
rm -rf ${LEG}; mkdir -p ${LEG}
cp ${WORK}/dem-hgtres.tif ${LEG}/raw.tif
warp ${WORK}/smooth.tif 90 ${WORK}/merc-90.tif
shade ${WORK}/merc-90.tif 5 ${LEG}/hillshade-30m-jpeg.tif
for f in hillshade-500 hillshade-1000 hillshade-5000 relief-500 relief-5000; do
	cp ${WORK}/${f}.tif ${LEG}/${f}.tif
done
rm -f ${WORK}/tiff-${ZONE}.zip
(cd ${LEG} && zip -q -j ../tiff-${ZONE}.zip *.tif)

# ---------------------------------------------------------------- publish
say publish
install -m 644 ${WORK}/dem.tif                      ${PUB}/dem-${ZONE}.tif
install -m 644 ${WORK}/hillshade-z2.tif             ${PUB}/
install -m 644 ${WORK}/hillshade-z5.tif             ${PUB}/
install -m 644 ${WORK}/hillshade-500.tif            ${PUB}/
install -m 644 ${WORK}/hillshade-1000.tif           ${PUB}/
install -m 644 ${WORK}/hillshade-5000.tif           ${PUB}/
install -m 644 ${WORK}/relief-500.tif               ${PUB}/
install -m 644 ${WORK}/relief-5000.tif              ${PUB}/
install -m 644 ${WORK}/contours-${ZONE}.osm.pbf     ${PUB}/
rm -f ${WORK}/contours-${ZONE}.gpkg.zip
cp ${WORK}/contours-out.gpkg ${WORK}/contours-${ZONE}.gpkg
(cd ${WORK} && zip -q -9 -j contours-${ZONE}.gpkg.zip contours-${ZONE}.gpkg)
install -m 644 ${WORK}/contours-${ZONE}.gpkg.zip    ${PUB}/
rm -f ${PUB}/contours-${ZONE}.gpkg
install -m 644 ${WORK}/tiff-${ZONE}.zip             ${PUB}/
mkdir -p ${PUB}/hgt && install -m 644 ${WORK}/hgt/*.hgt ${PUB}/hgt/

du -sh ${PUB} | sed 's/^/  published /'

# Everything here is either published or regenerable, and a big zone leaves two
# gigabytes of it. util has 36 GB for twenty-nine zones and the published set,
# so the working files go unless KEEP_WORK says otherwise
if [ -z "${KEEP_WORK:-}" ]; then
	WAS=$(du -sm ${WORK} | cut -f1)
	rm -rf ${WORK}/legacy ${WORK}/hgt
	rm -f ${WORK}/cont.tif ${WORK}/filled.tif ${WORK}/rounded.tif \
		${WORK}/smooth.tif ${WORK}/smooth.vrt ${WORK}/water-mask.tif \
		${WORK}/water-areas.gpkg ${WORK}/merc-*.tif ${WORK}/dem-hgtres.tif \
		${WORK}/hillshade-*.tif ${WORK}/relief-*.tif ${WORK}/contours-out.gpkg \
		${WORK}/contours-${ZONE}.gpkg ${WORK}/contours-${ZONE}.gpkg.zip \
		${WORK}/contours-${ZONE}.osm.pbf ${WORK}/tiff-${ZONE}.zip
	# dem.tif and contours.gpkg are kept: small next to the rest, and the two
	# things worth having to hand when a build looks wrong
	echo "  working files ${WAS} MB -> $(du -sm ${WORK} | cut -f1) MB (KEEP_WORK to keep them)"
fi

# The distribution, against the previous build of this zone. An aggregate error
# figure hides exactly the faults this pipeline produces - three separate land
# and sea bugs each moved roantra's RMS by under 0.1 m while making the map
# visibly wrong - so the shares are what gets watched
say distribution
mkdir -p ${BASE}/stats
${TOOLS}/bin/demZoneStats.py ${WORK}/dem.tif ${BASE}/stats/${ZONE}.json

say done
