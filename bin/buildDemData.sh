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
INACTIVE_REASONS="withdrawn unowned quality wip duplicate"
STARTED=$(date -u '+%Y-%m-%d %H:%M:%S UTC')
RUN_TAG=$(date -u '+%Y%m%dT%H%M%SZ')
# A zone list for the next run, so the unit can be used for a forced or partial
# rebuild without editing it or passing arguments: one zone per line, "all" for
# every zone, # for a comment. Removed once the run finishes with nothing
# failed, so it is a single instruction rather than a standing setting - a run
# which fails a zone leaves it in place and the next run retries the same list
LIMIT=${BASE}/limit-build.txt
# How many days of per-run logs to keep beside the stable name
LOG_KEEP_DAYS=${LOG_KEEP_DAYS:-7}
# Written at the top of the publish directory rather than inside a zone,
# because sync-to-ogf@dem.path watches that directory and PathChanged does not
# recurse: a write into dem/<zone>/ triggers nothing, so without this a long
# rebuild publishes only when something syncs it by hand
PROGRESS=${PUB}/dem-build-progress.txt
# Appends a line and closes it, which is what raises IN_CLOSE_WRITE and fires
# the path unit - so each zone syncs itself as it finishes. fsync for the
# durability, the close for the event
progress() {
	mkdir -p ${PUB} 2>/dev/null || return 0
	printf '%s\n' "$*" >> ${PROGRESS}
	sync -d ${PROGRESS} 2>/dev/null || true
}

# The run's own output, published so a mapper can see why their zone did or did
# not rebuild without an account on the server. It comes from the journal rather
# than a tee: buildDemZone.sh writes to the same stdout, so the unit's journal
# already holds every zone's output interleaved with this script's, which is
# exactly what wants publishing. Run by hand rather than by the timer there is
# no journal to read, and the file says so rather than silently being the last
# timer run's.
publish_log() {
	local rc=$?
	mkdir -p ${PUB} 2>/dev/null || return 0
	{
		echo "# buildDemData.sh, run at ${STARTED}, exit ${rc}"
		echo "#"
		if [ -n "${INVOCATION_ID}" ]; then
			journalctl -u dem-build --since "${STARTED}" --no-pager 2>/dev/null ||
				echo "# the journal could not be read"
		else
			echo "# Run by hand, not by dem-build.timer, so there is no journal for"
			echo "# it. What follows is the last run of the unit itself."
			echo "#"
			journalctl -u dem-build -n 2000 --no-pager 2>/dev/null || true
		fi
	} > ${PUB}/dem-build-log-${RUN_TAG}.txt 2>/dev/null || true
	# the stable name every link and bookmark uses, pointing at this run. A hard
	# link rather than a symlink because the sync is rsync -a with no -H, and a
	# symlink would arrive as a symlink into a file the next housekeeping
	# removes. It costs a second copy on the far side, which is the trade
	ln -f ${PUB}/dem-build-log-${RUN_TAG}.txt ${PUB}/dem-build-log.txt 2>/dev/null || true
	# and the older runs go, or every run's log accumulates for ever
	find ${PUB} -maxdepth 1 -name 'dem-build-log-*.txt' -mtime +${LOG_KEEP_DAYS} \
		-delete 2>/dev/null || true
	return ${rc}
}

[ -d "${SQUARES}" ] || { echo "no ${SQUARES}" >&2; exit 1; }
mkdir -p ${STAMPS}

# One run at a time, so a long build and the next timer firing cannot overlap
exec 9>${BASE}/.build.lock
if ! flock -n 9; then
	echo "another run is in progress, giving up" >&2
	exit 1
fi
# Only once the lock is held, so a run which gave up does not overwrite the log
# of the run it gave up to
trap publish_log EXIT

# Size and mtime of every square, which is enough to notice an edit without
# reading a few hundred megabytes per zone
stamp_of() {
	# -L so a zone directory which is a symlink is followed; without it find
	# does not descend and every zone hashes to the same empty digest
	find -L ${SQUARES}/$1 -name '*.osm.xz' -printf '%f %s %T@\n' 2>/dev/null |
		sort | sha256sum | cut -d' ' -f1
}

all_zones() { (cd ${SQUARES} && for d in */; do echo "${d%/}"; done); }

limited=0
if [ $# -gt 0 ]; then
	zones="$*"
	forced=1
elif [ -f "${LIMIT}" ]; then
	zones=$(sed 's/#.*//' "${LIMIT}" | tr ',' ' ' | awk 'NF {for (i = 1; i <= NF; ++i) print $i}')
	forced=1
	limited=1
	case " ${zones} " in
		*" all "*) zones=$(all_zones); echo "$(basename ${LIMIT}): all zones, forced" ;;
		*) if [ -z "${zones}" ]; then
			echo "$(basename ${LIMIT}) names no zones, ignoring it" >&2
			zones=$(all_zones); forced=0; limited=0
		   else
			echo "$(basename ${LIMIT}): $(echo ${zones} | wc -w) zones, forced - $(echo ${zones} | tr '\n' ' ')"
		   fi ;;
	esac
else
	zones=$(all_zones)
	forced=0
fi

# Fresh each run - the timestamped log is the archive, this is what is happening
# now. Writing it here also fires the path unit once at the start, so a run that
# fails on its first zone still publishes the fact that it began
rm -f ${PROGRESS}
progress "# buildDemData.sh started ${STARTED}, $(echo ${zones} | wc -w) zones to consider"

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
	zone_started=${SECONDS}
	if ${TOOLS}/bin/buildDemZone.sh ${zone}; then
		# stamped only on success, so a failed build is retried next time rather
		# than being recorded as done
		echo "${now}" > ${STAMPS}/${zone}
		built+=("${zone}")
		zone_result=built
	else
		echo "${zone}: BUILD FAILED" >&2
		failed+=("${zone}")
		zone_result=FAILED
	fi
	# and the sync fires on this, carrying the zone just published with it
	progress "$(date -u '+%Y-%m-%dT%H:%M:%SZ') ${zone} ${zone_result} $((SECONDS - zone_started))s"
done

# ---------------------------------------------------------------- squares
# The source squares are published too, because they are what a mapper actually
# needs: a blank template for a square nobody has drawn, or the current contours
# for one they want to revise. That is what osm-squares/ on the old server was
# for, and nothing else in the published set replaces it.
#
# xz, not pbf. JOSM opens .osm.xz without a plugin - gz, bz2, zip and xz are all
# native - and more importantly the XML carries upload='never' and
# action='modify', which pbf has nowhere to put. These files hold negative ids,
# so JOSM treats every object in them as new; without that guard, someone who
# hits upload puts several hundred thousand contour nodes onto the live map.
#
# A copy, not a compression: the squares are held compressed, so what is
# published is byte for byte the file the build reads. That closes the round
# trip - a mapper mirrors this directory, edits a square, sends it back, and it
# drops into osm-squares as it stands. Timestamps are preserved with it, so the
# zone stamp reflects when the square was drawn rather than when it was copied.
#
# Published for every zone, including the inactive ones: leaving a zone out of
# the render says nothing about whether its contours should be available.
echo
echo "############ source squares ############"
PUBSQ=${PUB}/osm-squares
mkdir -p ${PUBSQ}
for zone in $(cd ${SQUARES} && for d in */; do echo "${d%/}"; done); do
	mkdir -p ${PUBSQ}/${zone}
	n=0
	for f in ${SQUARES}/${zone}/*.osm.xz; do
		[ -e "${f}" ] || continue
		out=${PUBSQ}/${zone}/$(basename ${f})
		if [ ! -f "${out}" ] || [ "${f}" -nt "${out}" ]; then
			cp -p "${f}" "${out}.tmp" && mv "${out}.tmp" "${out}"
			n=$((n + 1))
		fi
	done
	# squares which have gone from the source go from the published copy too,
	# or a square deleted upstream stays downloadable for ever - along with
	# anything left behind in a compression this no longer uses
	for out in ${PUBSQ}/${zone}/*.osm.*; do
		[ -e "${out}" ] || continue
		if [ "${out%.osm.xz}" = "${out}" ] ||
			[ ! -f "${SQUARES}/${zone}/$(basename ${out})" ]; then
			rm -f "${out}"
		fi
	done
	[ ${n} -gt 0 ] && printf '  %-16s %d squares published\n' "${zone}" "${n}"
done
# and zones which have gone entirely
for d in ${PUBSQ}/*/; do
	z=$(basename ${d})
	[ -d "${SQUARES}/${z}" ] || { rm -rf "${d}"; echo "  dropped zone ${z}"; }
done
du -sh ${PUBSQ} | sed 's/^/  published squares /'

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

# The index the wiki draws, rewritten every run: it reports which squares are
# blank, and a square stops being blank without this script rebuilding anything
echo
echo "############ wiki index ############"
${TOOLS}/bin/demZonesToMultimap.py ${BASE} -copyto ${PUB} || true

echo
echo "=== built ${#built[@]}: ${built[*]:-none}"
echo "=== unchanged ${#skipped[@]}: ${skipped[*]:-none}"
if [ -n "${inactive_list}" ]; then
	echo "=== published but not rendered:"
	sed 's/#.*//' ${INACTIVE} 2>/dev/null | awk 'NF {printf "      %-16s %s\n", $1, ($2 == "" ? "NO REASON GIVEN" : $2)}'
fi
echo "=== renderers load $(grep -vc '^#' ${PUB}/active-zones.txt) zones"
progress "# finished $(date -u '+%Y-%m-%dT%H:%M:%SZ'), built ${#built[@]}, unchanged ${#skipped[@]}, failed ${#failed[@]}"
if [ ${#failed[@]} -gt 0 ]; then
	echo "=== FAILED ${#failed[@]}: ${failed[*]}" >&2
	# the limit file stays, so the next run retries the same list rather than
	# falling back to whatever has changed since
	[ ${limited} -eq 1 ] && echo "$(basename ${LIMIT}) kept, $((${#failed[@]})) zone(s) still to build" >&2
	exit 1
fi
# a single instruction, carried out - so it goes
if [ ${limited} -eq 1 ]; then
	rm -f ${LIMIT} && echo "=== $(basename ${LIMIT}) done, removed"
fi
