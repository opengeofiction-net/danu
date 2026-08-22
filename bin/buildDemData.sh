#!/bin/bash
#
# Build every elevation zone whose contour squares have changed - see
# Admin:Elevation process
#
#   buildDemData.sh [zone ...]
#
# With no arguments every zone under elevation/osm-squares is considered, and
# only those whose squares have changed since the last build are rebuilt. Naming
# zones builds just those, changed or not.
#
# Zones are discovered from the filesystem, so adding one is a matter of putting
# its squares in place - there is no list to edit here or anywhere else. That was
# the main cost of the process this replaces: a per-zone conversion script, a
# per-zone post-processing script, and a hand-maintained id table.
#
# Run as the ogf user, by dem-build.timer, or by hand.

set -u

OGF=${OGF:-/opt/opengeofiction}
TOOLS=${TOOLS:-${OGF}/OGF-terrain-tools}
BASE=${BASE:-${OGF}/elevation}
SQUARES=${BASE}/osm-squares
STAMPS=${BASE}/stamps
PUB=${PUB:-${OGF}/sync-to-ogf/dem}
# Zones which are built and published but which the renderers should not load.
# "<zone> <reason>", one per line - see etc/dem_inactive.template. The reason is
# required and checked, because "inactive" with no reason recorded is how a zone
# stays inactive long after anyone remembers what the reason was
INACTIVE=${BASE}/inactive
INACTIVE_REASONS="withdrawn quality wip"

[ -d "${SQUARES}" ] || { echo "no ${SQUARES}" >&2; exit 1; }
mkdir -p ${STAMPS}

# One run at a time, so a long build and the next timer firing cannot overlap
exec 9>${BASE}/.build.lock
if ! flock -n 9; then
	echo "another run is in progress, giving up" >&2
	exit 1
fi

# Size and mtime of every square, which is enough to notice an edit without
# reading a few hundred megabytes per zone
stamp_of() {
	# -L so a zone directory which is a symlink is followed; without it find
	# does not descend and every zone hashes to the same empty digest
	find -L ${SQUARES}/$1 -name '*.osm' -printf '%f %s %T@\n' 2>/dev/null |
		sort | sha256sum | cut -d' ' -f1
}

if [ $# -gt 0 ]; then
	zones="$*"
	forced=1
else
	zones=$(cd ${SQUARES} && for d in */; do echo "${d%/}"; done)
	forced=0
fi

built=() skipped=() failed=()

for zone in ${zones}; do
	if [ ! -d "${SQUARES}/${zone}" ]; then
		echo "${zone}: no such zone" >&2
		failed+=("${zone}")
		continue
	fi

	now=$(stamp_of ${zone})
	was=$(cat ${STAMPS}/${zone} 2>/dev/null || true)
	if [ ${forced} -eq 0 ] && [ "${now}" = "${was}" ]; then
		skipped+=("${zone}")
		continue
	fi

	echo
	echo "############ ${zone} ############"
	if ${TOOLS}/bin/buildDemZone.sh ${zone}; then
		# stamped only on success, so a failed build is retried next time rather
		# than being recorded as done
		echo "${now}" > ${STAMPS}/${zone}
		built+=("${zone}")
	else
		echo "${zone}: BUILD FAILED" >&2
		failed+=("${zone}")
	fi
done

# The manifest of what to render. Everything built is published either way, so
# an inactive zone stays downloadable and only stops being drawn - the tile
# servers take a zone that leaves this list out of their rasters and out of
# their contour database.
inactive_list=$(sed 's/#.*//' ${INACTIVE} 2>/dev/null | awk 'NF {print $1}' | sort)
# The reason is part of the record, so an entry without one, or with one that is
# not a reason we recognise, is called out rather than quietly accepted
while read -r zone reason rest; do
	[ -z "${zone}" ] && continue
	case " ${INACTIVE_REASONS} " in
		*" ${reason} "*) ;;
		*) echo "${INACTIVE}: ${zone} has reason '${reason:-none}', expected one of ${INACTIVE_REASONS}" >&2 ;;
	esac
done < <(sed 's/#.*//' ${INACTIVE} 2>/dev/null | awk 'NF')
mkdir -p ${PUB}
{
	echo "# Elevation zones the renderers should load, one per line."
	echo "#"
	echo "# Written by buildDemData.sh - do not edit here. A zone is published"
	echo "# whether or not it appears below; this list is only about rendering,"
	echo "# so a zone left out stays downloadable and stops being drawn."
	echo "#"
	echo "# $(date -u '+%Y-%m-%d %H:%M:%S UTC')"
	(cd ${PUB} && for d in */; do
		d=${d%/}
		[ -f "${d}/dem-${d}.tif" ] || continue
		echo "${d}"
	done) | grep -vxF "${inactive_list:-@@none@@}" || true
} > ${PUB}/active-zones.txt

echo
echo "=== built ${#built[@]}: ${built[*]:-none}"
echo "=== unchanged ${#skipped[@]}: ${skipped[*]:-none}"
if [ -n "${inactive_list}" ]; then
	echo "=== published but not rendered:"
	sed 's/#.*//' ${INACTIVE} 2>/dev/null | awk 'NF {printf "      %-16s %s\n", $1, ($2 == "" ? "NO REASON GIVEN" : $2)}'
fi
echo "=== renderers load $(grep -vc '^#' ${PUB}/active-zones.txt) zones"
if [ ${#failed[@]} -gt 0 ]; then
	echo "=== FAILED ${#failed[@]}: ${failed[*]}" >&2
	exit 1
fi
