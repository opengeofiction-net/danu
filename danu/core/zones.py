"""The zones of the data drop (#190): which zone a square goes to, and the
two files on the server that say so - ``zones``, written here, and
``inactive``, which danu-build reads.

A zone is a lowercase name and one or more rectangles of whole degree
squares, ``N18E086-N21E089`` from its south-west square to its north-east
one, or one square alone. Zones never overlap, so a square is in at most
one, and that is where its upload goes - one nobody has drawn yet too. A
rectangle whose west is east of its east crosses the antimeridian.

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
        a, _, b = text.partition('-')
        try:
            sw = SquareName.parse(a)
            ne = SquareName.parse(b) if b else sw
        except ValueError as e:
            raise ZoneError(f'{text!r}: not a rectangle of squares, want N18E086-N21E089') from e
        if ne.lat < sw.lat:
            raise ZoneError(f'{text!r}: its north-east square is south of its south-west one')
        return cls(sw, ne)

    def __str__(self) -> str:
        return self.sw.name if self.sw == self.ne else f'{self.sw.name}-{self.ne.name}'

    def cells(self) -> set[SquareName]:
        width = (self.ne.lon - self.sw.lon) % 360 + 1
        return {SquareName((self.sw.lon + dx + 180) % 360 - 180, lat)
                for dx in range(width) for lat in range(self.sw.lat, self.ne.lat + 1)}


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
        squares changed, its line's note kept. Raises if it would overlap."""
        _check_name(zone)
        if not rects:
            raise ZoneError(f'{zone}: a zone needs squares')
        parsed = [Rect.parse(r) for r in rects]
        body = f'{zone:<15} {" ".join(str(r) for r in parsed)}'
        lines, done = [], False
        for line in self.lines:
            words = line.split('#', 1)[0].split()
            if words and words[0] == zone:
                note = line.partition('#')[2]
                lines.append(f'{body}   #{note}' if note else body)
                done = True
            else:
                lines.append(line)
        if not done:
            lines.append(body)
        return Zones('\n'.join(lines))


def seed(squares_dir: str | Path) -> Zones:
    """``zones`` for the zones that exist: one rectangle each, round the
    squares each holds. Raises where two would overlap - an admin draws
    those."""
    lines = ['# The data drop\'s zones (#190): a zone, then its rectangles of squares,',
             '# from the south-west square to the north-east one. Zones never overlap.',
             '# Written by the API as admins change them; comments are kept.']
    for d in sorted(p for p in Path(squares_dir).iterdir() if p.is_dir()):
        cells = list(list_squares(d, compressed_only=True))
        if not cells:
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
        """A new ``inactive`` with ``zone`` in it for ``reason``."""
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
            # the reason changed in place, and the note with it if one is
            # given; the comments running on after it are kept either way
            old = lines[span[0]]
            kept = old.partition('#')[2].strip()
            note = note or kept
            lines[span[0]] = f'{zone:<11} {reason:<10} # {note}' if note else f'{zone:<11} {reason}'
        return Inactive('\n'.join(lines))

    def clear(self, zone: str) -> 'Inactive':
        """A new ``inactive`` without ``zone``: its line and its comments."""
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
        sys.stdout.write(seed(a.squares).text)
    except ZoneError as e:
        print(f'zones: {e}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
