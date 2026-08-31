#!/bin/bash
#
# Build one elevation zone from its contour squares - see Admin:Elevation process
#
#   buildDemZone.sh <zone>
#
# Reads /opt/opengeofiction/elevation/osm-squares/<zone>/*.osm.xz and publishes to
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
#   FILL_METRES     how far a cell may look for a contour. 1852 m is the old
#                   process's radius of 20 cells at 3", and holds that distance
#                   at 1" as 60 cells. Beyond it a cell has no elevation
#                   information of its own and takes what the second pass
#                   carries in
#   ISOFILL_EXTRA   further isofill flags, for trying a change on one zone
#                   before it becomes the default. Empty normally
#   BARRIER_CELLS   how wide a contour is for the sight test only, not for its
#                   value. At 3" a one cell line is a 93 m wall; at 1" the same
#                   cell is 31 m, so rays thread gaps which could not exist on
#                   the coarser grid. 0.345% of open water carries elevation at
#                   0, 0.303% at 2, near-line cells moving a median of 1 m
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
HGT_ARCSEC=${HGT_ARCSEC:-3}             # the .hgt archive stays at 1201
FILL_METRES=${FILL_METRES:-1850}
BARRIER_CELLS=${BARRIER_CELLS:-2}
ISOFILL_EXTRA=${ISOFILL_EXTRA:-}
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
# All but two cores, the same budget isofill takes, so the box stays usable.
# GDAL spends it on two things this build does constantly: DEFLATE compression
# on every raster it writes, and gdalwarp's warping. It does nothing for
# gdal_contour, for gdal_rasterize's burn, or for gdaldem's hillshade
# arithmetic - only for what those write
export GDAL_NUM_THREADS=${GDAL_NUM_THREADS:-$(($(nproc) > 2 ? $(nproc) - 2 : 1))}

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
# Every stage's start second, so where a build's time goes is recorded rather
# than guessed at. The per-zone elapsed in dem-build-progress.txt says a zone
# took an hour; this says which part of it did, which is what any work on
# parallelising the build has to be decided from
mkdir -p ${BASE}/stats
TIMINGS=${BASE}/stats/${ZONE}-timings.tsv
: > ${TIMINGS}
say() {
	printf '%s\t%s\n' "${SECONDS}" "$*" >> ${TIMINGS}
	echo "=== ${ZONE}: $* ==="
}

# A stage costs the gap between it starting and the next one starting, so the
# report needs a terminator after the last
timings_report() {
	[ -s ${TIMINGS} ] || return 0
	printf '%s\t%s\n' "${SECONDS}" "(end)" >> ${TIMINGS}
	echo "  where the time went, longest first:"
	awk -F'\t' 'NR > 1 { printf "%d\t%s\n", $1 - p, st } { p = $1; st = $2 }' ${TIMINGS} |
		sort -rn -k1,1 |
		awk -F'\t' -v t="${SECONDS}" '$1 > 0 {
			printf "    %5ds  %5.1f%%  %s\n", $1, (t ? 100 * $1 / t : 0), $2 }' |
		head -10
	printf '    %5ds  total\n' "${SECONDS}"
}

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
#
# The squares are held compressed and GDAL has no VSI handler for xz - there is
# one for zip, gzip and 7z, but not this - so each is expanded into the working
# directory, read, and dropped again. One at a time, so the cost is the largest
# square rather than the whole zone.
say collect
sed 's/^closed_ways_are_polygons=.*/closed_ways_are_polygons=/' \
	${OSMCONF} > ${WORK}/osmconf-lines.ini
rm -f ${WORK}/contours.gpkg
first=1
SQUARE=${WORK}/square.osm
for f in ${SRC}/*.osm.xz; do
	[ -e "${f}" ] || continue
	xz -dc "${f}" > ${SQUARE}
	# GDAL's OSM driver drops any way over 10,000 nodes. It says so once per
	# node beyond the limit, so one 45,000 node contour buries the message
	# under 35,000 identical lines and GDAL's own 1,000 error cap hides the
	# rest - which is how ten contours between 101 m and 171 m went missing
	# from S37E147_Madison_City, 45% of that square's contour length, and
	# came back as voids nobody could account for.
	#
	# A blank square is better than a quietly wrong one, so this stops. The
	# warning threshold is the OSM API's own limit, which these files would
	# have to satisfy to be uploaded. demSplitLongWays.py fixes both.
	eval "$(awk '
		/<way id=/ { n = 0 }
		/<nd / { ++n }
		/<\/way>/ { if (n > 2000) ++over; if (n > 10000) ++drop; if (n > max) max = n }
		END { printf "sq_over=%d sq_drop=%d sq_max=%d\n", over+0, drop+0, max+0 }' ${SQUARE})"
	if [ "${sq_drop}" -gt 0 ]; then
		echo "  ERROR: $(basename ${f}) has ${sq_drop} way(s) over 10,000 nodes" >&2
		echo "  (longest ${sq_max}). GDAL drops these silently and the ground they" >&2
		echo "  describe comes out as a void. Run:" >&2
		echo "    ${TOOLS}/bin/demSplitLongWays.py --backup <dir> ${SRC}" >&2
		exit 1
	fi
	if [ "${sq_over}" -gt 0 ]; then
		echo "  WARNING: $(basename ${f}) has ${sq_over} way(s) over 2,000 nodes" >&2
		echo "  (longest ${sq_max}), which the OSM API would reject on upload" >&2
	fi
	if [ ${first} -eq 1 ]; then
		OSM_CONFIG_FILE=${WORK}/osmconf-lines.ini \
			ogr2ogr -f GPKG ${WORK}/contours.gpkg ${SQUARE} lines \
			-where "ele IS NOT NULL" -nln contour -nlt LINESTRING >/dev/null
		first=0
	else
		OSM_CONFIG_FILE=${WORK}/osmconf-lines.ini \
			ogr2ogr -f GPKG -append ${WORK}/contours.gpkg ${SQUARE} lines \
			-where "ele IS NOT NULL" -nln contour >/dev/null
	fi
	rm -f ${SQUARE}
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
# -at, all touched: a thin line leaves diagonal gaps, and the fill's sight test
# threads them - a ray reaches the ground behind a coastline without crossing it
gdal_rasterize -q -at -a ele -a_nodata -9999 -init -9999 -ot Int16 \
	-tr ${RES} ${RES} -te ${TE} -co TILED=YES -co COMPRESS=DEFLATE \
	${WORK}/contours.gpkg ${WORK}/cont.tif
gdalinfo ${WORK}/cont.tif | sed -n 's/^Size is/  size/p'

# ---------------------------------------------------------------- interpolate
say "interpolate, radius ${FILL_CELLS} cells, barrier ${BARRIER_CELLS}${ISOFILL_EXTRA:+, extra ${ISOFILL_EXTRA}}"
rm -f ${WORK}/filled.tif ${WORK}/rounded.tif ${WORK}/dem.tif
# isofill, not gdal_fillnodata: the latter will interpolate from a single
# sample, which terraces the surface into plateaus with straight edges where the
# chosen sample switches. A hillshade is a derivative and shows that plainly
# where a slope histogram averages it away. isofill takes the steepest pair of
# contours in line of sight and declines to fill at all from one, which is also
# what keeps water enclosed by a coastline empty.
#
# Needs isofill 0.4.0 or later, which fills the cells the first pass found
# nothing for rather than leaving them at zero - the behaviour 0.3.1 had behind
# --no-reach, and what the original does. Against 0.3.1's default this square
# was one of 114,309 in zone-tapira reading 1 m between ground at 130 m
isofill --radius ${FILL_CELLS} --barrier ${BARRIER_CELLS} ${ISOFILL_EXTRA} \
	${WORK}/cont.tif ${WORK}/rounded.tif
# No rounding step: isofill writes Int16, where gdal_fillnodata returned floats

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
	# No curated file, so the mask comes from the coastline's own direction -
	# land on the left, water on the right - which the squares already carry.
	# Same artefact, same slot, no file to maintain. It exists to stop the fill
	# leaving elevation offshore: on zone-alved it covers 96.8% of the cells
	# which had it, and 99.6% of what it marks is genuinely sea
	say "water from the coastline direction"
	rm -f ${WORK}/water-mask.tif
	if ${TOOLS}/bin/demSeaMask.py ${WORK}/contours.gpkg ${WORK}/cont.tif \
			${WORK}/water-mask.tif; then
		WATER_MASK=${WORK}/water-mask.tif
	else
		echo "  no coastline in this zone either - enclosed water will read" >&2
		echo "  1 m rather than 0, which shows in the relief rasters" >&2
	fi
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
# One 3" copy of the master, used by the contour lines and the .hgt archive.
# Contours come from here rather than the 1" master deliberately - at 1" the
# same lines carry three times the vertices, which triples what the render
# databases hold to draw a line 0.2 to 0.6 px wide
say "3\" derivative, for contours and hgt"
rm -f ${WORK}/dem-hgtres.tif
gdalwarp -q -overwrite -multi -r average -te ${TE_HGT} -tr ${HGT_RES} ${HGT_RES} \
	-ot Int16 -co TILED=YES -co COMPRESS=DEFLATE -co PREDICTOR=2 \
	${WORK}/dem.tif ${WORK}/dem-hgtres.tif
gdalinfo ${WORK}/dem-hgtres.tif | sed -n 's/^Size is/  3 arcsec size/p'

# ---------------------------------------------------------------- rasters
# Mercator, as the styles expect, and hillshaded there rather than in degrees -
# gdaldem on a lat/lon raster treats degrees as metres.
MERC="+proj=merc +ellps=sphere +R=6378137 +a=6378137 +units=m"
# No -multi here, measured. On makaska it took the raster stage from 134 s to
# 152 s: this warps five times, and at 500, 1000 and 5000 m the outputs are
# small enough that coordinating threads costs more than it saves. The one big
# warp in the build, the 3 arcsecond derivative, does take it - 23 s to 2 s
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

# Where the published sea level ended up against the shore somebody drew. A
# report, deliberately, not a warning: a zone whose contours stop in the middle
# of a square - undrawn land around a drawn patch - has the fill running out on
# dry ground, which reads exactly like an island with no coastline and is
# perfectly correct. zone-axian's KojoA squares do it every build. A warning
# that is usually wrong gets ignored, which is how the coastline the OSM driver
# was dropping went unnoticed for as long as it did
${TOOLS}/bin/demCheckZeroLine.py ${SRC} ${WORK}/contours-${ZONE}.osm.pbf ||
	echo "  zero line check did not run" >&2

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
mkdir -p ${PUB}/hgt && install -m 644 ${WORK}/hgt/*.hgt ${PUB}/hgt/

du -sh ${PUB} | sed 's/^/  published /'

# Everything here is either published or regenerable, and a big zone leaves two
# gigabytes of it. util has 36 GB for twenty-nine zones and the published set,
# so the working files go unless KEEP_WORK says otherwise
if [ -z "${KEEP_WORK:-}" ]; then
	WAS=$(du -sm ${WORK} | cut -f1)
	rm -rf ${WORK}/hgt
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
timings_report
