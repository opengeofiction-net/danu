"""Which square of a zone holds each of the main map's ways and relations.

An import holds a feature in one square of the zone - its home, the square
with most of its nodes - whichever squares are open. To know whether a
feature is held already, and where, it asks every square file of the zone,
not only the open set's: the sea, r470432, reaches most of roantra from a
home two squares from N46E030, and an import from there has to find it.

Read from the files themselves, so it is whatever the zone's squares say -
saved here, imported from the drop, uploaded by another mapper - and kept by
each file's size and modification time, so a file is read again when either
changes - a rewrite that kept both, on a filesystem with coarse times, is not
seen until the file changes again.
Only the main map's ids: a way or relation with a positive id. The ids are
found in the text, not by parsing the square: a roantra file is read in a
tenth of a second this way, against a second and more to parse it.
"""

from __future__ import annotations

import lzma
import math
import os
import re
import threading
from pathlib import Path

from .square import SquareName, list_squares

_ID = re.compile(rb"""<(way|relation)\s[^>]*?\bid=['"](\d+)['"]""")
_CACHE: dict[str, tuple[int, int, frozenset]] = {}      # path: (size, mtime_ns, its (kind, id)s)
_LOCK = threading.Lock()


def _held_in(path: Path) -> frozenset:
    st = path.stat()
    key = os.fspath(path)
    with _LOCK:
        hit = _CACHE.get(key)
    if hit is not None and hit[:2] == (st.st_size, st.st_mtime_ns):
        return hit[2]
    opener = lzma.open if path.suffix == '.xz' else open
    with opener(path, 'rb') as f:
        text = f.read()
    found = frozenset((kind.decode(), int(i)) for kind, i in _ID.findall(text))
    # kept only if the file is as it was when stat'd: one rewritten while it
    # was read is read again next time
    after = path.stat()
    if (after.st_size, after.st_mtime_ns) == (st.st_size, st.st_mtime_ns):
        with _LOCK:
            _CACHE[key] = (st.st_size, st.st_mtime_ns, found)
    return found


def squares(zone_dir) -> dict[SquareName, Path]:
    """The zone's squares, each with its file - every square the zone has,
    the blank templates the drop hands out included."""
    return list_squares(zone_dir)


def held(zone_dir, skip=()) -> dict[tuple[str, int], SquareName]:
    """``(kind, id)`` to the square whose file holds it, over the zone's
    files - all but ``skip``'s, the squares the caller holds in memory and
    knows better than their files do."""
    out: dict = {}
    for name, path in sorted(squares(zone_dir).items(), key=lambda kv: str(kv[0])):
        if name in skip:
            continue
        try:
            found = _held_in(path)
        except (OSError, lzma.LZMAError):
            continue                       # a file being written, or not a square: asked again next time
        for key in found:
            out.setdefault(key, name)      # held twice: the first, by name, until the next import settles it
    return out


# ------------------------------------------------- where the water reaches

_EXTENTS: dict[str, tuple[int, int, list]] = {}       # path: (size, mtime_ns, [(kind, id, [(lon, lat), ...])])


def _water(way) -> bool:
    t = way.tags
    return bool(t.get('natural') in ('water', 'coastline') or 'waterway' in t)


def water_extents(path: Path) -> list:
    """Each water feature a square's file holds, with the degree squares
    its nodes fall in: a water relation by its rings, a lake, a river or a
    coastline by itself - as ``(kind, id, [(lon, lat), ...])``, each the
    south-west corner of a degree. The degrees and not a box: a river's or a
    coastline's box takes in squares it never reaches, and a set opened
    beside roantra's coast read nine squares where it needed one or two.
    Parsed, so kept by the file's size and time like the ids."""
    from .square import read_square, water_tags
    st = path.stat()
    key = os.fspath(path)
    with _LOCK:
        hit = _EXTENTS.get(key)
    if hit is not None and hit[:2] == (st.st_size, st.st_mtime_ns):
        return hit[2]
    sq = read_square(path)
    out = []

    def box(refs):
        cells = sorted({(math.floor(sq.nodes[r].lon), math.floor(sq.nodes[r].lat)) for r in refs if r in sq.nodes})
        return cells or None
    members = set()
    for rel in sq.relations.values():
        if not water_tags(rel.tags):
            continue
        refs = [r for m in rel.members if m.type == 'way' and m.ref in sq.ways for r in sq.ways[m.ref].refs]
        members.update(m.ref for m in rel.members if m.type == 'way')
        b = box(refs)
        if b is not None:
            out.append(('relation', rel.id, b))
    for way in sq.ways.values():
        if way.id not in members and _water(way):
            b = box(way.refs)
            if b is not None:
                out.append(('way', way.id, b))
    after = path.stat()
    if (after.st_size, after.st_mtime_ns) == (st.st_size, st.st_mtime_ns):
        with _LOCK:
            _EXTENTS[key] = (st.st_size, st.st_mtime_ns, out)
    return out


def load_extents(cache: Path) -> None:
    """What an earlier session worked out, from ``cache``: a file is read
    again only if it has changed since."""
    import json
    try:
        got = json.loads(Path(cache).read_text())
    except (OSError, ValueError):
        return
    with _LOCK:
        for key, (size, mtime, found) in got.items():
            _EXTENTS.setdefault(key, (size, mtime, [(k, i, [tuple(c) for c in b]) for k, i, b in found]))


def save_extents(cache: Path) -> None:
    import json
    with _LOCK:
        got = {k: [s, m, [[kind, i, [list(c) for c in b]] for kind, i, b in f]] for k, (s, m, f) in _EXTENTS.items()}
    try:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        tmp = Path(cache).with_name(Path(cache).name + '.tmp')
        tmp.write_text(json.dumps(got))
        os.replace(tmp, cache)
    except OSError:
        pass                               # a cache: next time it is worked out again


def reaching(zone_dir, bounds, skip=()) -> list:
    """The zone's squares outside ``skip`` holding water with a node in a
    degree of ``bounds`` (west, south, east, north) - the sea's home, two
    squares from a set it reaches into - by name, nearest first."""
    w, s, e, n = bounds
    out = []
    for name, path in squares(zone_dir).items():
        if name in skip:
            continue
        try:
            found = water_extents(path)
        except (OSError, lzma.LZMAError, ValueError):
            continue
        if any(w <= lon < e and s <= lat < n for _, _, cells in found for lon, lat in cells):
            out.append(name)
    cx, cy = (w + e) / 2, (s + n) / 2
    return sorted(out, key=lambda q: ((q.lon + 0.5 - cx) ** 2 + (q.lat + 0.5 - cy) ** 2, str(q)))
