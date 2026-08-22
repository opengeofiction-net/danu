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
	find ${SQUARES}/$1 -name '*.osm' -printf '%f %s %T@\n' 2>/dev/null | sort | sha256sum | cut -d' ' -f1
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

echo
echo "=== built ${#built[@]}: ${built[*]:-none}"
echo "=== unchanged ${#skipped[@]}: ${skipped[*]:-none}"
if [ ${#failed[@]} -gt 0 ]; then
	echo "=== FAILED ${#failed[@]}: ${failed[*]}" >&2
	exit 1
fi
