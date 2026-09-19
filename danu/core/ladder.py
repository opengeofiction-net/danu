"""The elevation ladder: inferred per square, overridable, with a zone default.

Zones do not share a contour interval and within a zone it varies - see *The
elevation ladder* in the spec, whose worked example is ``N20E086_Gobras_City``:
a clean 25 m ladder from 100 to 1075 carrying nearly all the drawn length, and
below 100 m an ad hoc run of 0, 3, 5, 7, 9, 10 ... 95. So the ladder is read
from the data, not configured:

- the modal gap between consecutive distinct elevations is the **interval**;
- the residue most elevations share modulo the interval is the **phase**, and
  the regular ladder is every value on that phase;
- the notches are every elevation that exists, the regular ladder filled
  between its lowest and highest present rung, and the regular ladder
  continued a few rungs above and down to sea level below;
- where the data is irregular the notches follow it rather than spacing it.

Inference is per square. A per-square override replaces it where it goes
wrong; a zone default stands in where there is nothing to infer from, a blank
square being the usual case. Nothing here knows about Qt: the slider and the
keys in ``danu.ui`` drive an ``Elevation`` and read a ``Ladder``.
"""

from __future__ import annotations

import os
import tomllib
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .square import Square

EXTEND_ABOVE = 4                # rungs continued above the highest present
DEFAULT_INTERVAL = 10.0         # with no data and no override: 10 m from sea level
DEFAULT_TOP = 200.0


def format_ele(value: float) -> str:
    """The ``ele`` tag for a value: ``125`` not ``125.0``, ``12.5`` when it is."""
    return str(int(value)) if float(value).is_integer() else repr(float(value))


# --------------------------------------------------------------- ladder

@dataclass(frozen=True)
class Ladder:
    """Notches, ascending, with the regular ladder they were built around.

    ``interval`` and ``phase`` describe the regular ladder - phase being the
    residue its rungs share modulo the interval, 0 for 100/125/150 and 1 for
    101/151/201 - or are None for a ladder given as bare values. ``present``
    is what the square actually holds. ``source`` says where the ladder came
    from and ``square`` which square it reads, because the slider names it:
    crossing into a neighbour re-notches, and doing that silently would be
    worse than the inconvenience."""
    notches: tuple[float, ...]
    interval: float | None = None
    phase: float | None = None
    present: frozenset[float] = frozenset()
    source: str = 'default'                  # inferred | square | zone | default
    square: str | None = None

    def __post_init__(self):
        if not self.notches:
            raise ValueError('a ladder needs at least one notch')
        if list(self.notches) != sorted(set(self.notches)):
            raise ValueError('notches must be ascending and distinct')

    @property
    def low(self) -> float:
        return self.notches[0]

    @property
    def high(self) -> float:
        return self.notches[-1]

    def regular(self, value: float) -> bool:
        """Is the value a rung of the regular ladder?"""
        if self.interval is None:
            return value in self.notches
        return _on_phase(value, self.interval, self.phase or 0.0)

    def above(self, value: float) -> float | None:
        """The first notch strictly above the value, or None at the top."""
        return next((n for n in self.notches if n > value + 1e-9), None)

    def below(self, value: float) -> float | None:
        """The first notch strictly below the value, or None at the bottom."""
        return next((n for n in reversed(self.notches) if n < value - 1e-9), None)

    def nearest(self, value: float) -> float:
        return min(self.notches, key=lambda n: (abs(n - value), n))

    def index(self, value: float) -> int | None:
        """The position of a notch, for a slider, or None if it is not one."""
        for i, n in enumerate(self.notches):
            if abs(n - value) < 1e-9:
                return i
        return None

    def covering(self, value: float) -> 'Ladder':
        """This ladder, extended along the regular spacing (or by the value
        alone) so that the value is a notch. The keys step in metres and can
        walk off the end; the slider must still be able to show where."""
        if self.index(value) is not None:
            return self
        new = set(self.notches)
        if self.interval:
            step = self.interval
            if value > self.high:               # rungs up to, not past, the value
                n = self.high + step
                while n < value - 1e-9:
                    new.add(n)
                    n += step
            else:
                n = self.low - step
                while n > value + 1e-9:
                    new.add(n)
                    n -= step
        new.add(value)
        return Ladder(tuple(sorted(new)), self.interval, self.phase, self.present, self.source, self.square)

    def describe(self) -> str:
        where = {'inferred': f'inferred from {self.square}', 'square': f'override for {self.square}',
                 'zone': 'zone default', 'default': 'default'}[self.source]
        if self.interval is None:
            return f'{len(self.notches)} values, {where}'
        return f'{format_ele(self.interval)} m ladder, {where}'


def regular_ladder(interval: float, base: float = 0.0, top: float | None = None,
                   source: str = 'default', square: str | None = None) -> Ladder:
    """Rungs of ``interval`` on ``base``'s phase, from the rung at or below sea
    level up to ``top``."""
    if interval <= 0:
        raise ValueError('interval must be positive')
    top = base + 20 * interval if top is None else top
    phase = base % interval
    n = phase - interval if phase > 0 else 0.0
    notches = []
    while n <= top + 1e-9:
        notches.append(n)
        n += interval
    return Ladder(tuple(notches), interval, phase, frozenset(), source, square)


def _on_phase(value: float, interval: float, phase: float) -> bool:
    r = (value - phase) % interval
    return min(r, interval - r) < 1e-6


def infer(square: Square, extend_above: int = EXTEND_ABOVE) -> Ladder | None:
    """The ladder a square's own contours describe, or None when it holds
    fewer than two distinct elevations and there is no gap to read."""
    counts = Counter(w.ele for w in square.contours())
    values = sorted(counts)
    if len(values) < 2:
        return None
    gaps = Counter(round(b - a, 6) for a, b in zip(values, values[1:]))
    # the modal gap; a tie goes to the gap whose ends carry more contours,
    # then to the wider, since the finer one is more often detail
    def weight(g):
        return sum(counts[a] + counts[b] for a, b in zip(values, values[1:]) if round(b - a, 6) == g)
    interval = max(gaps, key=lambda g: (gaps[g], weight(g), g))
    residues = Counter()
    for v in values:
        residues[round(v % interval, 6)] += counts[v]
    phase = max(residues, key=lambda r: (residues[r], -r))
    regular = [v for v in values if _on_phase(v, interval, phase)]
    notches = set(values)
    if regular:
        n = regular[0]
        while n < regular[-1] - 1e-9:          # fill the holes in the regular run
            n += interval
            notches.add(round(n, 6))
        n = regular[-1]
        for _ in range(extend_above):           # continue it above
            n += interval
            notches.add(round(n, 6))
        n = regular[0]
        while n - interval >= -1e-9:            # and down to sea level
            n -= interval
            notches.add(round(n, 6))
    notches.add(0.0)
    return Ladder(tuple(sorted(notches)), float(interval), float(phase), frozenset(values),
                  'inferred', square.name.name)


# ------------------------------------------------------------ overrides

@dataclass(frozen=True)
class LadderSpec:
    """One override as a mapper writes it: a regular ladder (``interval``,
    optionally ``base`` and ``top``) or the bare ``values``."""
    interval: float | None = None
    base: float = 0.0
    top: float | None = None
    values: tuple[float, ...] = ()

    def __post_init__(self):
        if (self.interval is None) == (not self.values):
            raise ValueError('a ladder override is an interval or a list of values, not both or neither')

    def ladder(self, source: str, square: str | None) -> Ladder:
        if self.values:
            return Ladder(tuple(sorted(set(self.values))), None, None, frozenset(), source, square)
        return regular_ladder(self.interval, self.base, self.top, source, square)

    @classmethod
    def from_toml(cls, d: dict) -> 'LadderSpec':
        if 'values' in d:
            return cls(values=tuple(float(v) for v in d['values']))
        return cls(interval=float(d['interval']), base=float(d.get('base', 0)),
                   top=None if d.get('top') is None else float(d['top']))

    def to_toml(self) -> str:
        if self.values:
            return 'values = [' + ', '.join(format_ele(v) for v in self.values) + ']\n'
        out = f'interval = {format_ele(self.interval)}\n'
        if self.base:
            out += f'base = {format_ele(self.base)}\n'
        if self.top is not None:
            out += f'top = {format_ele(self.top)}\n'
        return out


@dataclass
class Overrides:
    """Per-square overrides and per-zone defaults, keyed by the zone directory
    name and ``zone/SQUARE``. A TOML file holds them::

        [zone."gobras"]
        interval = 25

        [square."gobras/N20E086"]
        values = [0, 3, 5, 7, 10, 25, 50, 75, 100]
    """
    zones: dict[str, LadderSpec] = field(default_factory=dict)
    squares: dict[str, LadderSpec] = field(default_factory=dict)

    @staticmethod
    def key(zone: str, square: str) -> str:
        return f'{zone}/{square}'

    def for_square(self, zone: str, square: str) -> Ladder | None:
        spec = self.squares.get(self.key(zone, square))
        return spec.ladder('square', square) if spec else None

    def for_zone(self, zone: str, square: str | None = None) -> Ladder | None:
        spec = self.zones.get(zone)
        return spec.ladder('zone', square) if spec else None

    @classmethod
    def loads(cls, text: str) -> 'Overrides':
        d = tomllib.loads(text)
        return cls({k: LadderSpec.from_toml(v) for k, v in d.get('zone', {}).items()},
                   {k: LadderSpec.from_toml(v) for k, v in d.get('square', {}).items()})

    @classmethod
    def load(cls, path: str | os.PathLike) -> 'Overrides':
        path = Path(path)
        return cls.loads(path.read_text(encoding='utf-8')) if path.exists() else cls()

    def dumps(self) -> str:
        parts = ['# Danu elevation ladders: a default per zone, an override per square.\n']
        for k in sorted(self.zones):
            parts.append(f'\n[zone."{k}"]\n' + self.zones[k].to_toml())
        for k in sorted(self.squares):
            parts.append(f'\n[square."{k}"]\n' + self.squares[k].to_toml())
        return ''.join(parts)

    def save(self, path: str | os.PathLike) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + '.tmp')
        tmp.write_text(self.dumps(), encoding='utf-8')
        os.replace(tmp, path)
        return path


def ladder_for(square: Square, zone: str, overrides: Overrides | None = None) -> Ladder:
    """The ladder to use for a square: its override, else what its contours
    say, else the zone's default, else 10 m from sea level."""
    overrides = overrides or Overrides()
    name = square.name.name
    return (overrides.for_square(zone, name) or infer(square) or overrides.for_zone(zone, name)
            or regular_ladder(DEFAULT_INTERVAL, 0.0, DEFAULT_TOP, 'default', name))


# --------------------------------------------------------------- advice

@dataclass(frozen=True)
class OffLadder:
    """A value off the regular ladder and used once or twice: 113 between 110
    and 115 in Gobras looks exactly like a mis-typed 125. Advice, not error."""
    value: float
    count: int
    below: float | None          # the nearest present values either side
    above: float | None

    def describe(self) -> str:
        times = 'once' if self.count == 1 else f'{self.count} times'
        span = f' between {format_ele(self.below)} and {format_ele(self.above)}' if self.below is not None and self.above is not None else ''
        return f'{format_ele(self.value)} m used {times}{span}'


def off_ladder(square: Square, ladder: Ladder, at_most: int = 2) -> list[OffLadder]:
    counts = Counter(w.ele for w in square.contours())
    values = sorted(counts)
    out = []
    for i, v in enumerate(values):
        if counts[v] <= at_most and not ladder.regular(v):
            out.append(OffLadder(v, counts[v], values[i - 1] if i else None,
                                 values[i + 1] if i + 1 < len(values) else None))
    return out


# ------------------------------------------------------------ elevation

class Elevation:
    """The active elevation: the editor's most-used state, driven by keys, the
    wheel and the slider. Steps are the configurable small and big increments
    in metres, so a zone at 5/25 and one at 10/50 use the same keys; nudge is
    one metre; pick-up takes a contour's value; the notch moves walk the
    ladder. Listeners are called with the new value after every change."""

    def __init__(self, ladder: Ladder, small: float = 10.0, big: float = 50.0,
                 value: float | None = None):
        self._ladder = ladder
        self.small = small
        self.big = big
        self._value = ladder.nearest(0.0) if value is None else float(value)
        self._listeners: list[Callable[[float], None]] = []

    # -- state
    @property
    def value(self) -> float:
        return self._value

    @property
    def tag(self) -> str:
        return format_ele(self._value)

    @property
    def ladder(self) -> Ladder:
        """The ladder, extended if need be to hold the current value."""
        return self._ladder.covering(self._value)

    def set_ladder(self, ladder: Ladder):
        """A new ladder - the cursor crossed into another square - keeps the
        value; a mapper mid-line does not want it to jump."""
        self._ladder = ladder
        self._notify()

    def listen(self, fn: Callable[[float], None]):
        self._listeners.append(fn)

    def _notify(self):
        for fn in self._listeners:
            fn(self._value)

    # -- moves
    def set(self, value: float):
        self._value = float(value)
        self._notify()

    def step(self, big: bool = False, down: bool = False):
        d = self.big if big else self.small
        self.set(self._value + (-d if down else d))

    def nudge(self, down: bool = False):
        self.set(self._value + (-1.0 if down else 1.0))

    def sea_level(self):
        self.set(0.0)

    def pick_up(self, value: float | None):
        """Take the elevation of the contour under the cursor; nothing there
        changes nothing."""
        if value is not None:
            self.set(value)

    def next_notch(self):
        n = self.ladder.above(self._value)
        if n is not None:
            self.set(n)

    def prev_notch(self):
        n = self.ladder.below(self._value)
        if n is not None:
            self.set(n)
