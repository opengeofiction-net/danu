"""Which square of a zone holds each of the main map's ways and relations.

An import holds a feature in one square of the zone - its home, the square
with most of its nodes - whichever squares are open. To know whether a
feature is held already, and where, it asks every square file of the zone,
not only the open set's: the sea, r470432, reaches most of roantra from a
home two squares from N46E030, and an import from there has to find it.

Read from the files themselves, so it is whatever the zone's squares say -
saved here, imported from the drop, uploaded by another mapper - and kept by
each file's size and time, so a file is read again only when it has changed.
Only the main map's ids: a way or relation with a positive id. The ids are
found in the text, not by parsing the square: a roantra file is read in a
tenth of a second this way, against a second and more to parse it.
"""

from __future__ import annotations

import lzma
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
