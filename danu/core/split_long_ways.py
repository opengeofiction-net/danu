#!/usr/bin/env python3
#
# Split over-long ways in the elevation squares - see Admin:Elevation process
#
#   split_long_ways.py [--limit N] [--backup DIR] [--dry-run] <path> [path ...]
#
# GDAL's OSM driver silently drops any way with more than 10,000 nodes. It
# reports one error per node beyond the limit, so a single 45,000 node contour
# buries the message under 35,000 identical lines and GDAL's own 1,000 error cap
# hides the rest. The contour never reaches the DEM and the ground it described
# comes out as a void - which is what put ten contours between 101 m and 171 m
# out of S37E147_Madison_City, in terrain whose median is 126 m.
#
# The OSM API rejects an uploaded way over 2,000 nodes, so that is the bound
# used here: it is the rule these files would have to satisfy anyway, and it
# leaves a five times margin under the limit that actually bites.
#
# Splitting is exact. Consecutive pieces share their boundary node - the same
# node id, referenced by both - so every segment of the original survives and
# the geometry is unchanged. Tags are copied to each piece.
#
# Safe for coastlines: sea_mask.py works from the sides of each segment, not
# from closed rings ("Sides rather than rings", sea_mask.py), so a split
# coastline seeds exactly as it did before. Direction is preserved.
#
# Safe for relations: a member naming a way that is split is replaced by one
# member per piece, in order and with the same role. Without that a lake's
# outer ring loses everything past its first two thousand nodes and the shape
# has a hole in it, written back and nothing said. This works because a square
# writes its relations after its ways, so the pieces are known by the time a
# member is read; a file that puts them first is refused rather than half
# mended. danu.core.edits._ReplaceWays is the same rule on the model, and
# tests/test_edits.py holds the two together.
#
import argparse
import lzma
import os
import re
import shutil
import sys
import tempfile

WAY_RE = re.compile(r"<way\s+id='(-?\d+)'")
MEMBER_RE = re.compile(r"<member\s+type='way'\s+ref='(-?\d+)'")
ID_RE  = re.compile(r"<way\s+id='(-?\d+)'")

def scan(path):
    """Minimum way id, and {way id: node count} for the ways over the limit."""
    min_id = 0
    counts = {}
    way = None
    n = 0
    with lzma.open(path, 'rt', encoding='utf-8', errors='replace') as f:
        for line in f:
            m = WAY_RE.search(line)
            if m:
                way = int(m.group(1)); n = 0
                min_id = min(min_id, way)
            elif '<nd ' in line:
                n += 1
            elif '</way>' in line and way is not None:
                counts[way] = n
                way = None
    return min_id, counts

def split_file(path, limit, backup_dir, dry_run):
    min_id, counts = scan(path)
    over = {w: n for w, n in counts.items() if n > limit}
    if not over:
        return 0, 0
    pieces_total = 0
    for n in over.values():
        # each piece has at most `limit` nodes and shares one with the next
        pieces_total += -(-(n - 1) // (limit - 1))
    if dry_run:
        return len(over), pieces_total - len(over)

    if backup_dir:
        dest = os.path.join(backup_dir, os.path.basename(os.path.dirname(path)))
        os.makedirs(dest, exist_ok=True)
        shutil.copy2(path, os.path.join(dest, os.path.basename(path)))

    next_id = min_id - 1
    pieces = {}                  # split way -> the ids its pieces took, in order
    seen_relation = False
    # mkstemp creates at 0600. Carry the original's mode across, or the square
    # becomes unreadable to anyone but ogf - and danu-build publishes with
    # cp -p, so Apache then serves 403 for it
    mode = os.stat(path).st_mode & 0o7777
    fd, tmp = tempfile.mkstemp(suffix='.osm.xz', dir=os.path.dirname(path))
    os.close(fd)
    os.chmod(tmp, mode)
    added = 0
    with lzma.open(path, 'rt', encoding='utf-8', errors='replace') as src, \
         lzma.open(tmp, 'wt', encoding='utf-8', preset=6) as out:
        way = None; header = None; nds = []; tags = []
        for line in src:
            m = WAY_RE.search(line)
            if m:
                if seen_relation:
                    # the pieces a member names have to be known by the time
                    # the member is read, so every way has to be written
                    # before every relation. Checked as *no way after a
                    # relation* rather than as *no relation before the first
                    # way*, which a file that interleaves them would walk
                    # straight past
                    raise SystemExit(
                        '%s: a way after a relation, which this cannot mend - a '
                        'member naming a way split later in the file would keep '
                        'the first piece and lose the rest' % path)
                way = int(m.group(1)); header = line; nds = []; tags = []
                continue
            if '<relation ' in line:
                seen_relation = True
            if way is None:
                mem = MEMBER_RE.search(line)
                if mem and int(mem.group(1)) in pieces:
                    # one member per piece, in order, each keeping the role
                    # the original member had - which is the whole of why
                    # this is done here and not left to a later pass
                    was = int(mem.group(1))
                    for nid in pieces[was]:
                        out.write(line.replace("ref='%d'" % was, "ref='%d'" % nid, 1))
                    continue
                out.write(line); continue
            if '<nd ' in line:
                nds.append(line)
            elif '<tag ' in line:
                tags.append(line)
            elif '</way>' in line:
                if way in over:
                    step = limit - 1
                    start = 0
                    first = True
                    pieces[way] = []
                    while start < len(nds) - 1:
                        chunk = nds[start:start + limit]
                        if first:
                            out.write(header); first = False
                            pieces[way].append(way)
                        else:
                            next_id -= 1; added += 1
                            out.write(header.replace("id='%d'" % way,
                                                     "id='%d'" % next_id, 1))
                            pieces[way].append(next_id)
                        out.writelines(chunk)
                        out.writelines(tags)
                        out.write(line)
                        start += step
                else:
                    out.write(header); out.writelines(nds); out.writelines(tags)
                    out.write(line)
                way = None
            else:
                out.write(line)
        # a second pass would be needed to mend members, except that the ways
        # are all written by now and the relations come after them - which is
        # checked above rather than assumed
    os.replace(tmp, path)
    return len(over), added

def main():
    ap = argparse.ArgumentParser(description='Split over-long ways in elevation squares')
    ap.add_argument('paths', nargs='+', help='square files, or directories to walk')
    ap.add_argument('--limit', type=int, default=2000, help='max nodes per way (default 2000)')
    ap.add_argument('--backup', metavar='DIR', help='copy each modified square here first')
    ap.add_argument('--dry-run', action='store_true', help='report, change nothing')
    a = ap.parse_args()
    if a.limit < 2:
        sys.exit('--limit must be at least 2')
    if not a.dry_run and not a.backup:
        sys.exit('refusing to rewrite without --backup (or pass --dry-run)')

    files = []
    for p in a.paths:
        if os.path.isdir(p):
            for root, _, names in os.walk(p):
                files += [os.path.join(root, n) for n in sorted(names) if n.endswith('.osm.xz')]
        else:
            files.append(p)
    files.sort()

    tot_f = tot_w = tot_a = 0
    for path in files:
        w, added = split_file(path, a.limit, a.backup, a.dry_run)
        if w:
            tot_f += 1; tot_w += w; tot_a += added
            verb = 'would split' if a.dry_run else 'split'
            print('  %-14s %-34s %s %d ways into %d pieces' %
                  (os.path.basename(os.path.dirname(path)), os.path.basename(path),
                   verb, w, w + added), flush=True)
    print('%s: %d squares, %d ways, %d new ways' %
          ('would change' if a.dry_run else 'changed', tot_f, tot_w, tot_a))

if __name__ == '__main__':
    main()
