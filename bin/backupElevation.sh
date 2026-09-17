#!/bin/bash
#
# Back up the elevation source data to AWS S3 - see Admin:Elevation process
#
#   backupElevation.sh [base] [queue]
#
# Run as the ogf user, weekly by backup-elevation.timer, or by hand.
#
# What is backed up is what cannot be rebuilt: the contour squares, which are
# the source of truth and exist nowhere else once a mapper has sent one in, and
# the hand-made water files. Everything else under elevation/ is derived -
# build/ is working files, stamps/ and stats/ fall out of a build, and the
# published DEMs, hillshades and contours are all reproducible from the squares
# by running the process again.
#
# The configuration goes with them. `inactive` is a hand-written record of which
# zones are not rendered and why, and id-blocks.conf is the contour id block
# assigned to each zone on its first build - losing that would renumber every
# zone's contours on the next run.
#
# Thursday, tagged monthly on the last Thursday of the month and yearly on the
# last Thursday of December, which is what backupPlanet.sh and backupWiki.sh do.
# Matching them matters: the retention policy on the bucket is written against
# those tags, so a differently named archive is one nothing ever expires.

set -u

OGF=${OGF:-/opt/opengeofiction}
BASE=${1:-${OGF}/elevation}
BACKUP_QUEUE=${2:-${OGF}/backup-to-s3-queue}
DEST=${DEST:-${OGF}/backup-database}
LOCKFILE=${DEST}/backup-elevation.lock
KEEP_DAYS=30

DATESTR=$(date '+%Y%m%d_%H%M%S%Z')

echo "Started: $(date '+%Y-%m-%d %H:%M:%S %Z')"
renice -n 10 $$ >/dev/null

[ -d "${BASE}" ]         || { echo "ERROR: no ${BASE}" >&2; exit 2; }
[ -d "${BACKUP_QUEUE}" ] || { echo "ERROR: no ${BACKUP_QUEUE}" >&2; exit 3; }
mkdir -p "${DEST}"       || { echo "ERROR: cannot create ${DEST}" >&2; exit 3; }

# one at a time, and released however we leave
if ! mkdir "${LOCKFILE}" 2>/dev/null; then
	echo "a backup is already running" >&2
	exit 1
fi
trap 'rm -rf "${LOCKFILE}"' INT TERM EXIT

# weekly / monthly / yearly, tagged as backupPlanet.sh and backupWiki.sh tag
# theirs. Those two ask ncal for the last Thursday of the month; ncal is in
# bsdextrautils and is not installed here, and a missing ncal fails quietly - the
# test just never matches, every archive is tagged weekly, and nothing is ever
# kept beyond a month. So this asks date instead: if a week from today is a
# different month then today is the last of its weekday in this one.
#
# Run by hand on another day it is still a weekly, which is the harmless answer:
# it expires on the shortest schedule rather than never
timeframe=weekly
if [[ $(date -d '+7 days' +%m) != $(date +%m) ]]; then
	timeframe=monthly
	if [[ $(date +%-m) -eq 12 ]]; then
		timeframe=yearly
	fi
fi
archive=${DATESTR}_ogf-elevation-${timeframe}.tar.gz
echo "Timeframe: ${timeframe}"

# The squares are .osm.xz already, so gzip buys nothing on them and is not being
# asked to; it is here for the water files, which are plain XML
echo "Archiving squares, water and configuration"
tar -C "${BASE}" -czf "${DEST}/${archive}" \
	--exclude='*.tmp' \
	osm-squares water inactive id-blocks.conf 2>/dev/null
status=$?
if [ ${status} -ne 0 ] || [ ! -s "${DEST}/${archive}" ]; then
	echo "ERROR: tar failed (${status})" >&2
	rm -f "${DEST}/${archive}"
	exit 4
fi

# A truncated archive is worse than no archive, because it looks like one until
# the day it is needed
if ! tar -tzf "${DEST}/${archive}" >/dev/null 2>&1; then
	echo "ERROR: ${archive} does not read back" >&2
	rm -f "${DEST}/${archive}"
	exit 5
fi
echo "  $(du -h "${DEST}/${archive}" | cut -f1)  ${archive}"
echo "  $(tar -tzf "${DEST}/${archive}" | wc -l) members"

# Hard link, not copy: backupToS3.sh unlinks its own name when the upload is
# done and the local copy stays for KEEP_DAYS
ln "${DEST}/${archive}" "${BACKUP_QUEUE}/${timeframe}:elevation:${archive}"
echo "Queued for S3 as ${timeframe}:elevation:${archive}"

echo "Deleting local archives older than ${KEEP_DAYS} days"
find "${DEST}" -maxdepth 1 -name '*_ogf-elevation-*.tar.gz' \
	-mtime +${KEEP_DAYS} -print -delete

echo "Finished: $(date '+%Y-%m-%d %H:%M:%S %Z')"
