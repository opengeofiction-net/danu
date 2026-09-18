"""The contour square, in memory.

A square is one degree of the world as a mapper draws it: an ``.osm.xz`` file
under ``osm-squares/<zone>/`` holding contours as ways tagged ``ele``, and
whatever else was drawn against them - water edges, survey notes, the frame.
This module is how the editor reads one, and how anything else which wants to
look inside a square should read it, rather than adding a fifth ad hoc
``lzma.open`` to the four already in ``core``.

Nothing here knows about GDAL, Qt or the network. The file is plain OSM XML and
the standard library reads it; pyosmium stays on the server side where it is a
Debian package, because a native wheel is one more thing the Windows build has
to get right and this needs none of it.

The degree a square covers comes from its name, never from its nodes. A square
drawn in JOSM has frame nodes a metre or so inside the degree line, and the
build has always taken the extent from the filename; so does this.
"""

from __future__ import annotations

import lzma
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator
from xml.etree import ElementTree

# N42E017, the SRTM convention: the south-west corner, latitude two digits,
# longitude three, always signed by letter. A file may carry a label after the
# name - N18E088_Katyapura - which is for people; only the name is data
_NAME = re.compile(r'([NS])(\d{2})([EW])(\d{3})')
_FILE = re.compile(r'([NS]\d{2}[EW]\d{3})(?:_[^.]*)?\.osm(?:\.xz)?$')


@dataclass(frozen=True, order=True)
class SquareName:
    """A degree square, by its south-west corner in whole degrees."""

    lon: int
    lat: int

    def __post_init__(self):
        if not -180 <= self.lon < 180 or not -90 <= self.lat < 90:
            raise ValueError(f'no degree square at lon {self.lon}, lat {self.lat}')

    @classmethod
    def parse(cls, text: str) -> 'SquareName':
        """``N42E017`` -> the square. Case-insensitive, whole string only."""
        m = _NAME.fullmatch(text.strip().upper())
        if not m:
            raise ValueError(f'{text!r}: not a degree square name, want N42E017')
        ns, lat, ew, lon = m.groups()
        return cls(int(lon) * (1 if ew == 'E' else -1),
                   int(lat) * (1 if ns == 'N' else -1))

    @classmethod
    def from_filename(cls, filename: str | os.PathLike) -> 'SquareName':
        """``N18E088_Katyapura.osm.xz`` -> N18E088. Raises on anything that is
        not a square file, ``EMPTY.osm.xz`` included."""
        base = os.path.basename(os.fspath(filename))
        m = _FILE.match(base)
        if not m:
            raise ValueError(f'{base!r}: not a square file, want N42E017[_Label].osm.xz')
        return cls.parse(m.group(1))

    @property
    def name(self) -> str:
        ns = 'N' if self.lat >= 0 else 'S'
        ew = 'E' if self.lon >= 0 else 'W'
        return f'{ns}{abs(self.lat):02d}{ew}{abs(self.lon):03d}'

    def __str__(self) -> str:
        return self.name

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """(west, south, east, north), in degrees."""
        return (float(self.lon), float(self.lat),
                float(self.lon + 1), float(self.lat + 1))

    def neighbour(self, dx: int, dy: int) -> 'SquareName | None':
        """The square dx east and dy north, wrapping in longitude. None past a
        pole, where there is no square to be had."""
        lat = self.lat + dy
        if not -90 <= lat < 90:
            return None
        lon = (self.lon + dx + 180) % 360 - 180
        return SquareName(lon, lat)

    def contains(self, lon: float, lat: float) -> bool:
        w, s, e, n = self.bounds
        return w <= lon < e and s <= lat < n


# slots, because a square can hold two and a half million of these. Measured on
# the largest square there is, liberian N03E058 at 271 MB uncompressed: a plain
# dataclass per node took 1.2 GB resident, slots 1.08 GB. Kept because it is
# free, not because it solved anything - see read_square on what would
@dataclass(slots=True)
class Node:
    id: int
    lat: float
    lon: float
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(slots=True)
class Way:
    id: int
    refs: list[int]
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def ele(self) -> float | None:
        """The elevation, or None if the way has no ``ele`` or one that is not
        a number. A bad value is kept on the way for the checks to report; it
        is not a contour until it parses, and it is not silently dropped."""
        return parse_ele(self.tags.get('ele'))

    @property
    def closed(self) -> bool:
        return len(self.refs) > 1 and self.refs[0] == self.refs[-1]


def parse_ele(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value.strip())
    except ValueError:
        return None


@dataclass
class Square:
    """One square's contents. ``present`` is False for a square that has no
    file: it is still a Square, with the right name and bounds and nothing in
    it, so a working set is always a full grid and a viewer draws the empty
    ones as empty rather than skipping them."""

    name: SquareName
    path: Path | None = None
    present: bool = False
    nodes: dict[int, Node] = field(default_factory=dict)
    ways: dict[int, Way] = field(default_factory=dict)
    # the <osm> element's attributes - upload='never' above all, which a save
    # must carry forward unchanged, since it is what stops JOSM putting these
    # negative ids onto the live map
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.name.bounds

    def contours(self) -> Iterator[Way]:
        """Ways with a usable elevation, in file order."""
        for way in self.ways.values():
            if way.ele is not None:
                yield way

    def coords(self, way: Way) -> list[tuple[float, float]]:
        """(lon, lat) along a way. A ref with no node is skipped rather than
        raised: JOSM will save a way whose node was deleted under it, and a
        viewer should show the rest of the square, not refuse it."""
        out = []
        for ref in way.refs:
            node = self.nodes.get(ref)
            if node is not None:
                out.append((node.lon, node.lat))
        return out

    def elevations(self) -> list[float]:
        """Distinct contour elevations, ascending."""
        return sorted({w.ele for w in self.contours()})

    @property
    def empty(self) -> bool:
        return not self.ways and not self.nodes


def read_square(path: str | os.PathLike, name: SquareName | None = None) -> Square:
    """Read a square file. ``.osm.xz`` as the squares are held, or ``.osm`` as
    somebody's uncompressed drop; the name comes from the filename unless
    given.

    Streams the XML and discards each element once taken, because a filled
    square can be 271 MB uncompressed and a working set holds nine of them.
    Streaming bounds the parser's memory, not the model's: what is kept is a
    Node per node, and the largest square takes about 18 s and over a gigabyte
    to hold. That is the outlier: of 834 squares on the server, 815 are under
    5 MB compressed, 758 under 1 MB, and four are over 10 MB. It is the
    viewer's job to read in a worker and to draw at a level of detail, not this
    module's to be clever about storage before a real square needs it.
    """
    path = Path(path)
    if name is None:
        name = SquareName.from_filename(path)
    square = Square(name=name, path=path, present=True)

    opener = lzma.open if path.suffix == '.xz' else open
    with opener(path, 'rb') as f:
        for event, elem in ElementTree.iterparse(f, events=('start', 'end')):
            if event == 'start':
                if elem.tag == 'osm':
                    square.attrs = dict(elem.attrib)
                continue
            if elem.tag == 'node':
                square.nodes[int(elem.get('id'))] = Node(
                    id=int(elem.get('id')),
                    lat=float(elem.get('lat')),
                    lon=float(elem.get('lon')),
                    tags=_tags(elem))
                elem.clear()
            elif elem.tag == 'way':
                square.ways[int(elem.get('id'))] = Way(
                    id=int(elem.get('id')),
                    refs=[int(nd.get('ref')) for nd in elem.iter('nd')],
                    tags=_tags(elem))
                elem.clear()
            # relations are not something a square carries; if one turns up it
            # is left where it is and the checks can say so
    return square


def _tags(elem) -> dict[str, str]:
    return {t.get('k'): t.get('v', '') for t in elem.iter('tag')}


def list_squares(zone_dir: str | os.PathLike) -> dict[SquareName, Path]:
    """Every square file in a zone directory, by name. Files which are not
    squares - ``EMPTY.osm.xz``, the template - are ignored. Two files for one
    square is an error, not a choice: which one the build would read is the
    order the filesystem lists them in, and this should not be luckier."""
    found: dict[SquareName, Path] = {}
    for entry in sorted(Path(zone_dir).iterdir()):
        if not entry.is_file():
            continue
        try:
            name = SquareName.from_filename(entry)
        except ValueError:
            continue
        if name in found:
            raise FileExistsError(
                f'{name} is both {found[name].name} and {entry.name} in {zone_dir}')
        found[name] = entry
    return found


@dataclass
class WorkingSet:
    """The squares open at once: a grid of odd side centred on the one being
    edited, so an edit near an edge can see the neighbour it runs into.
    ``squares`` is the full grid, absent squares included, keyed by name."""

    centre: SquareName
    size: int
    squares: dict[SquareName, Square]

    @classmethod
    def open(cls, zone_dir: str | os.PathLike, centre: SquareName,
             size: int = 3) -> 'WorkingSet':
        if size < 1 or size % 2 == 0:
            raise ValueError(f'working set size must be odd and positive, not {size}')
        files = list_squares(zone_dir)
        half = size // 2
        squares: dict[SquareName, Square] = {}
        for dy in range(-half, half + 1):
            for dx in range(-half, half + 1):
                name = centre.neighbour(dx, dy)
                if name is None:
                    continue
                if name in files:
                    squares[name] = read_square(files[name], name)
                else:
                    squares[name] = Square(name=name)
        return cls(centre=centre, size=size, squares=squares)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        """The grid's extent, (west, south, east, north). Longitude is taken
        from the centre so a set straddling the antimeridian keeps its width
        rather than spanning the world."""
        half = self.size // 2
        names = list(self.squares)
        south = min(n.lat for n in names)
        north = max(n.lat for n in names) + 1
        return (float(self.centre.lon - half), float(south),
                float(self.centre.lon + half + 1), float(north))

    def present(self) -> Iterator[Square]:
        return (s for s in self.squares.values() if s.present)

    def contours(self) -> Iterator[tuple[Square, Way]]:
        for square in self.present():
            for way in square.contours():
                yield square, way

    def elevations(self) -> list[float]:
        return sorted({w.ele for _, w in self.contours()})

    def elevation_range(self) -> tuple[float, float] | None:
        eles = self.elevations()
        return (eles[0], eles[-1]) if eles else None

    def at(self, lon: float, lat: float) -> Square | None:
        """The square under a point, if it is in the set."""
        for square in self.squares.values():
            if square.name.contains(lon, lat):
                return square
        return None
