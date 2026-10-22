"""The zones of the data drop (#190): which zone a square goes to, and the
two files on the server that say so - ``zones``, written here, and
``inactive``, which danu-build reads.

A zone is a lowercase name and one or more rectangles of whole degree
squares, ``N18E086-N21E089`` from its south-west square to its north-east
one, or one square alone. Zones never overlap, so a square is in at most
one, and that is where its upload goes - one nobody has drawn yet too. A
zone across the antimeridian is two rectangles, one each side: a rectangle
whose east is west of its west is refused, being far likelier a typing slip
than the world less a few degrees.

``zones`` is one zone a line::

    # comments, kept
    gobras      N18E086-N21E089
    kofuku      N48E064-N59E079 N60E070   # a note, kept

``inactive`` is danu-build's: ``<zone> <reason>  # note``, the note running
on over the indented comment lines after it. Both are edited a zone at a
time, by an admin through the API, and the rest of each file - the other
zones, the comments people wrote - is left exactly as it was.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .square import SquareName, list_squares

ZONE = re.compile(r'[a-z][a-z0-9_-]{0,31}')
# danu-build's INACTIVE_REASONS
REASONS = ('withdrawn', 'unowned', 'quality', 'wip', 'duplicate')


class ZoneError(ValueError):
    """A zone or a rectangle refused, saying why."""


@dataclass(frozen=True)
class Rect:
    """Whole degree squares from ``sw`` to ``ne``, both in."""
    sw: SquareName
    ne: SquareName

    @classmethod
    def parse(cls, text: str) -> 'Rect':
        a, dash, b = text.partition('-')
        if dash and not b:
            raise ZoneError(f'{text!r}: a - and no square after it')
        try:
            sw = SquareName.parse(a)
            ne = SquareName.parse(b) if b else sw
        except ValueError as e:
            raise ZoneError(f'{text!r}: not a rectangle of squares, want N18E086-N21E089') from e
        if ne.lat < sw.lat:
            raise ZoneError(f'{text!r}: its north-east square is south of its south-west one')
        if ne.lon < sw.lon:
            raise ZoneError(f'{text!r}: its north-east square is west of its south-west one'
                            ' - across the antimeridian, give a rectangle each side')
        return cls(sw, ne)

    def __str__(self) -> str:
        return self.sw.name if self.sw == self.ne else f'{self.sw.name}-{self.ne.name}'

    def cells(self) -> set[SquareName]:
        return {SquareName(lon, lat) for lon in range(self.sw.lon, self.ne.lon + 1)
                for lat in range(self.sw.lat, self.ne.lat + 1)}


@dataclass(frozen=True)
class Zone:
    name: str
    rects: tuple[Rect, ...]

    def cells(self) -> set[SquareName]:
        return set().union(*(r.cells() for r in self.rects))


def _check_name(zone: str) -> None:
    if not ZONE.fullmatch(zone):
        raise ZoneError(f'{zone!r}: a zone is lowercase letters, digits, _ and -, starting with a letter')


class Zones:
    """The ``zones`` file: read, asked, and changed a zone at a time."""

    def __init__(self, text: str = ''):
        self.lines = text.splitlines()
        self.zones: dict[str, Zone] = {}
        for i, line in enumerate(self.lines):
            words = line.split('#', 1)[0].split()
            if not words:
                continue
            name, rects = words[0], words[1:]
            _check_name(name)
            if name in self.zones:
                raise ZoneError(f'line {i + 1}: {name} again')
            if not rects:
                raise ZoneError(f'line {i + 1}: {name} has no squares')
            self.zones[name] = Zone(name, tuple(Rect.parse(r) for r in rects))
        self.check()
        self._of = {c: z.name for z in self.zones.values() for c in z.cells()}

    @classmethod
    def read(cls, path: str | Path) -> 'Zones':
        p = Path(path)
        return cls(p.read_text(encoding='utf-8') if p.exists() else '')

    @property
    def text(self) -> str:
        return '\n'.join(self.lines) + '\n' if self.lines else ''

    def check(self) -> None:
        """No square in two zones."""
        seen: dict[SquareName, str] = {}
        for z in self.zones.values():
            for c in z.cells():
                if c in seen and seen[c] != z.name:
                    raise ZoneError(f'{z.name} and {seen[c]} overlap at {c}')
                seen[c] = z.name

    def zone_of(self, square: SquareName) -> str | None:
        return self._of.get(square)

    def put(self, zone: str, rects: list[str]) -> 'Zones':
        """A new ``zones`` with ``zone`` set to ``rects`` - created, or its
        squares changed, its line's spacing and note kept. Raises if it would
        overlap."""
        _check_name(zone)
        if not rects:
            raise ZoneError(f'{zone}: a zone needs squares')
        parsed = [Rect.parse(r) for r in rects]
        squares = ' '.join(str(r) for r in parsed)
        body = f'{zone:<15} {squares}'
        lines, done = [], False
        for line in self.lines:
            words = line.split('#', 1)[0].split()
            if words and words[0] == zone:
                # the zone and the gap after it as they were
                lead = re.match(r'\s*\S+\s+', line).group(0)
                note = line.partition('#')[2]
                lines.append(f'{lead}{squares}   #{note}' if note else f'{lead}{squares}')
                done = True
            else:
                lines.append(line)
        if not done:
            lines.append(body)
        return Zones('\n'.join(lines))


def rects_for(cells) -> list[Rect]:
    """Squares as rectangles, few of them: each row's runs of squares side by
    side, then runs alike in the rows above stacked onto them. What the zone
    map draws becomes what the ``zones`` file says. A zone across the
    antimeridian comes out a rectangle each side, as it must be written."""
    rows: dict[int, list[int]] = {}
    for c in cells:
        rows.setdefault(c.lat, []).append(c.lon)
    runs: list[tuple[int, int, int]] = []            # (lat, west, east)
    for lat, lons in sorted(rows.items()):
        lons.sort()
        start = prev = lons[0]
        for lon in lons[1:]:
            if lon != prev + 1:
                runs.append((lat, start, prev))
                start = lon
            prev = lon
        runs.append((lat, start, prev))
    open_: dict[tuple[int, int], list[int]] = {}     # (west, east) -> [south, north] still growing
    done: list[tuple[int, int, int, int]] = []
    for lat, w, e in runs:
        grow = open_.get((w, e))
        if grow is not None and grow[1] == lat - 1:
            grow[1] = lat
        else:
            if grow is not None:
                done.append((w, grow[0], e, grow[1]))
            open_[(w, e)] = [lat, lat]
    done += [(w, s, e, n) for (w, e), (s, n) in open_.items()]
    return [Rect(SquareName(w, s), SquareName(e, n)) for w, s, e, n in sorted(done, key=lambda r: (r[1], r[0]))]


# the way round a ring, turning at a corner: east, north, west, south
_STEPS = ((1, 0), (0, 1), (-1, 0), (0, -1))


def outline(cells) -> list[list[tuple[int, int]]]:
    """The squares' edge as rings of (lon, lat) corners, a ring's first not
    repeated at its end: one for each piece, anticlockwise, and one for each
    hole, clockwise - what the Zones map draws, for a map that fills even-odd
    as Leaflet does. Two squares touching only at a corner are one ring
    through that corner twice, touching itself there and never crossing."""
    cells = {(c.lon, c.lat) for c in cells}
    edges: dict[tuple[int, int], list[tuple[int, int]]] = {}
    # each square's sides that no square shares, the square on their left
    for x, y in cells:
        for (dx, dy), (a, b) in zip(_STEPS, (((x, y), (x + 1, y)), ((x + 1, y), (x + 1, y + 1)),
                                            ((x + 1, y + 1), (x, y + 1)), ((x, y + 1), (x, y))), strict=True):
            if (x + dy, y - dx) not in cells:          # the square to that side's right
                edges.setdefault(a, []).append(b)
    rings = []
    while edges:
        start = min(edges)
        ring, at, heading = [start], start, None
        while True:
            outs = edges[at]
            if len(outs) > 1 and heading is not None:
                # a pinch, two squares meeting at a corner: on round the
                # next one, so the ring touches itself here and never crosses
                right = (heading[1], -heading[0])
                nxt = next((o for o in outs if (o[0] - at[0], o[1] - at[1]) == right), outs[0])
            else:
                nxt = outs[0]
            outs.remove(nxt)
            if not outs:
                del edges[at]
            heading = (nxt[0] - at[0], nxt[1] - at[1])
            at = nxt
            if at == start:
                break
            ring.append(at)
        # corners only: a point on a straight run between two others goes
        n = len(ring)
        rings.append([p for i, p in enumerate(ring)
                      if (ring[i - 1][0] - p[0]) * (ring[(i + 1) % n][1] - p[1])
                      != (ring[i - 1][1] - p[1]) * (ring[(i + 1) % n][0] - p[0])])
    return rings


def seed(squares_dir: str | Path, report=None) -> Zones:
    """``zones`` for the zones that exist: one rectangle each, round the
    squares each holds. Raises where two would overlap - an admin draws
    those. A directory with no square file the pattern reads is left out,
    and told to ``report``."""
    lines = ['# The data drop\'s zones (#190): a zone, then its rectangles of squares,',
             '# from the south-west square to the north-east one. Zones never overlap.',
             '# Written by the API as admins change them; comments are kept.']
    for d in sorted(p for p in Path(squares_dir).iterdir() if p.is_dir()):
        cells = list(list_squares(d, compressed_only=True))
        if not cells:
            if report:
                report(f'{d.name}: no square file, so no zone - a label with a dot is not read')
            continue
        sw = SquareName(min(c.lon for c in cells), min(c.lat for c in cells))
        ne = SquareName(max(c.lon for c in cells), max(c.lat for c in cells))
        lines.append(f'{d.name:<15} {Rect(sw, ne)}')
    return Zones('\n'.join(lines))


class Inactive:
    """danu-build's ``inactive``: a zone's entry set or cleared, the others
    and every comment left as they are."""

    def __init__(self, text: str = ''):
        self.lines = text.splitlines()

    @classmethod
    def read(cls, path: str | Path) -> 'Inactive':
        p = Path(path)
        return cls(p.read_text(encoding='utf-8') if p.exists() else '')

    @property
    def text(self) -> str:
        return '\n'.join(self.lines) + '\n' if self.lines else ''

    def _entry(self, zone: str) -> tuple[int, int] | None:
        """The lines of a zone's entry: its own, and the indented comments
        running on after it."""
        for i, line in enumerate(self.lines):
            words = line.split('#', 1)[0].split()
            if words and words[0] == zone:
                j = i + 1
                while j < len(self.lines) and self.lines[j][:1].isspace() and self.lines[j].lstrip().startswith('#'):
                    j += 1
                return i, j
        return None

    def reasons(self) -> dict[str, str]:
        out = {}
        for line in self.lines:
            words = line.split('#', 1)[0].split()
            if words:
                out[words[0]] = words[1] if len(words) > 1 else ''
        return out

    def set(self, zone: str, reason: str, note: str = '') -> 'Inactive':
        """A new ``inactive`` with ``zone`` in it for ``reason``. An entry
        already there has its reason changed in place, and its note if one is
        given; no note keeps the old one, so a note is cleared by ``clear``
        and ``set`` again."""
        _check_name(zone)
        if reason not in REASONS:
            raise ZoneError(f'{reason!r}: the reason is one of {", ".join(REASONS)}')
        if '\n' in note:
            raise ZoneError('a note is one line')
        lines = list(self.lines)
        span = self._entry(zone)
        if span is None:
            lines.append(f'{zone:<11} {reason:<10} # {note}' if note else f'{zone:<11} {reason}')
        else:
            # the reason replaced where it stands, the spacing kept; the
            # comments running on after it are kept either way
            old = lines[span[0]]
            lead, was, gap, comment = re.match(r'(\s*\S+\s+)(\S*)(\s*)(#.*)?$', old).groups()
            comment = f'# {note}' if note else comment
            if not comment:
                lines[span[0]] = f'{lead}{reason}'
            else:
                # the # where it was, or a space after a longer reason
                at = len(lead) + len(was) + len(gap) if was and gap else len(lead) + 11
                lines[span[0]] = f'{lead}{reason}'.ljust(at - 1) + ' ' + comment
        return Inactive('\n'.join(lines))

    def clear(self, zone: str) -> 'Inactive':
        """A new ``inactive`` without ``zone``: its line and its comments."""
        _check_name(zone)
        span = self._entry(zone)
        if span is None:
            return Inactive('\n'.join(self.lines))
        i, j = span
        return Inactive('\n'.join(self.lines[:i] + self.lines[j:]))


def main(argv: list[str] | None = None) -> int:
    """``python -m danu.core.zones seed <osm-squares>``: the first ``zones``,
    on stdout."""
    import argparse
    import sys
    ap = argparse.ArgumentParser(prog='python -m danu.core.zones')
    sub = ap.add_subparsers(dest='cmd', required=True)
    sub.add_parser('seed', help="write zones for the zones that exist").add_argument('squares')
    a = ap.parse_args(argv)
    try:
        sys.stdout.write(seed(a.squares, report=lambda m: print(f'zones: {m}', file=sys.stderr)).text)
    except ZoneError as e:
        print(f'zones: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
