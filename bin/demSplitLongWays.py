#!/usr/bin/env python3
#
# Split over-long ways in the elevation squares - see Admin:Elevation process
#
#   demSplitLongWays.py [--limit N] [--backup DIR] [--dry-run] <path> [path ...]
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
# Safe for coastlines: demSeaMask.py works from the sides of each segment, not
# from closed rings ("Sides rather than rings", demSeaMask.py), so a split
# coastline seeds exactly as it did before. Direction is preserved.
#
import argparse, lzma, os, re, shutil, sys, tempfile

WAY_RE = re.compile(r"<way\s+id='(-?\d+)'")
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
    fd, tmp = tempfile.mkstemp(suffix='.osm.xz', dir=os.path.dirname(path))
    os.close(fd)
    added = 0
    with lzma.open(path, 'rt', encoding='utf-8', errors='replace') as src, \
         lzma.open(tmp, 'wt', encoding='utf-8', preset=6) as out:
        way = None; header = None; nds = []; tags = []
        for line in src:
            m = WAY_RE.search(line)
            if m:
                way = int(m.group(1)); header = line; nds = []; tags = []
                continue
            if way is None:
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
                    while start < len(nds) - 1:
                        chunk = nds[start:start + limit]
                        if first:
                            out.write(header); first = False
                        else:
                            next_id -= 1; added += 1
                            out.write(header.replace("id='%d'" % way,
                                                     "id='%d'" % next_id, 1))
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
