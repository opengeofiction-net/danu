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
import math
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator
from xml.etree import ElementTree

# N42E017, the SRTM convention: the south-west corner, latitude two digits,
# longitude three, always signed by letter. A file may carry a label after the
# name - N18E088_Katyapura - which is for people; only the name is data
_NAME = re.compile(r'^([NS])(\d{2})([EW])(\d{3})$')
_FILE = re.compile(r'([NS]\d{2}[EW]\d{3})(?:_[^.]+)?\.osm(?:\.xz)?$')


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
# dataclass per node took 1.2 GB resident, slots 1.08 GB, and clearing the
# parser's root as it goes 0.86 GB. Kept because it is free; see read_square
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
    Node per node, and the largest square takes about 19 s and 860 MB to
    hold. That is the outlier: of 834 squares on the server, 815 are under
    5 MB compressed, 758 under 1 MB, and four are over 10 MB. It is the
    viewer's job to read in a worker and to draw at a level of detail, not this
    module's to be clever about storage before a real square needs it.
    """
    path = Path(path)
    if name is None:
        name = SquareName.from_filename(path)
    square = Square(name=name, path=path, present=True)

    root = None
    with open_square_file(path) as f:
        for event, elem in ElementTree.iterparse(f, events=('start', 'end')):
            if event == 'start':
                if elem.tag == 'osm':
                    root = elem
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
            #
            # clearing a child empties it but leaves it in the root's list, so
            # without this the root ends the parse holding one hollow Element
            # per node - two and a half million of them on the largest square.
            # Clearing the root drops the finished children; the one being
            # parsed has not been appended yet. Its attributes went above
            if root is not None and elem is not root:
                root.clear()
    return square


def _tags(elem) -> dict[str, str]:
    return {t.get('k'): t.get('v', '') for t in elem.iter('tag')}


def list_squares(zone_dir: str | os.PathLike, compressed_only: bool = False) -> dict[SquareName, Path]:
    """Every square file in a zone directory, by name. Files which are not
    squares - ``EMPTY.osm.xz``, the template - are ignored. Two files for one
    square is an error, not a choice: which one the build would read is the
    order the filesystem lists them in, and this should not be luckier.

    ``compressed_only`` takes ``.osm.xz`` and nothing else, which is what the
    build wants: the squares are held compressed, and a bare ``.osm`` beside
    them is somebody's drop that never got packed rather than a second version
    of the square. ``loose_squares`` finds those, to be reported rather than
    read - building the zone without that mapper's work in it, silently, is the
    outcome worth avoiding."""
    found: dict[SquareName, Path] = {}
    for entry in sorted(Path(zone_dir).iterdir()):
        if not entry.is_file():
            continue
        if compressed_only and entry.suffix != '.xz':
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


def loose_squares(zone_dir: str | os.PathLike) -> list[Path]:
    """Square files left uncompressed, which the build does not read."""
    out = []
    for entry in sorted(Path(zone_dir).iterdir()):
        if not entry.is_file() or entry.suffix == '.xz':
            continue
        try:
            SquareName.from_filename(entry)
        except ValueError:
            continue
        out.append(entry)
    return out


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
        """Read the grid. Synchronous, and reads every present square in full,
        so around a large square this is the 18 s case: a viewer calls it from
        a worker, never from the thread that paints."""
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
        """The grid's extent, (west, south, east, north), as one continuous
        box in longitude *unwrapped about the centre*. A set centred on 179
        reports 178..181, not 178..-179: the square at -180 is in it, at 180
        on this axis. That is the box a Mercator canvas zooms to, and a plain
        min/max of the members would span the world instead. Use ``contains``
        rather than comparing a longitude against these edges yourself."""
        half = self.size // 2
        names = list(self.squares)
        # latitude from the members, because a row can be missing at a pole;
        # longitude from the centre, because a column never is, and the
        # members' longitudes cannot be min/maxed across the seam anyway
        south = min(n.lat for n in names)
        north = max(n.lat for n in names) + 1
        return (float(self.centre.lon - half), float(south),
                float(self.centre.lon + half + 1), float(north))

    def unwrap(self, lon: float) -> float:
        """A longitude moved by a whole turn, if needed, onto the continuous
        axis ``bounds`` is in."""
        while lon < self.centre.lon - 180:
            lon += 360
        while lon >= self.centre.lon + 180:
            lon -= 360
        return lon

    def contains(self, lon: float, lat: float) -> bool:
        w, s, e, n = self.bounds
        lon = self.unwrap(lon)
        return w <= lon < e and s <= lat < n

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
        """The square under a point, if it is in the set. Decided by the same
        box and the same unwrap as ``contains``, so the two cannot disagree: a
        caller who asks contains() and then at() gets a square, not None."""
        if not self.contains(lon, lat):
            return None
        lon = self.unwrap(lon)
        # the member's name, from the point: floor to the degree, then the
        # canonical spelling of that longitude, which is what the keys use
        deg = (math.floor(lon) + 180) % 360 - 180
        return self.squares.get(SquareName(deg, math.floor(lat)))


# ----------------------------------------------------------------- write

def write_square(square: Square, path: str | os.PathLike, generator: str = 'danu', preset: int = 6) -> Path:
    """Write a square as JOSM writes one: ``upload='never'`` and the other
    root attributes it was read with, every node and way ``action='modify'``,
    ids as they are, coordinates as the shortest text that reads back to the
    same float. ``.osm.xz`` compressed, ``.osm`` plain, by the suffix.

    Not byte for byte what JOSM would write - attribute order and precision
    are JOSM's own - but the same square: reading it back gives the same
    nodes, ways and tags, and the build makes the same surface from it, which
    is what the golden test asserts.

    Written to a temporary beside the target and moved into place, so a
    failure mid-write leaves the old file whole."""
    import html
    import tempfile
    from decimal import Decimal
    path = Path(path)

    def q(v) -> str:            # single quotes, as JOSM writes them; & < > ' escaped
        return "'" + html.escape(str(v), quote=True).replace('&quot;', '"') + "'"

    def deg(v: float) -> str:
        # the shortest digits that read back to the same float, written as a
        # plain decimal: repr(1e-05) is '1e-05', and a node within eleven
        # metres of the equator or the meridian would carry an exponent into
        # a file every other tool writes as decimals.
        #
        # Only such a node pays for the conversion. repr already gives a plain
        # decimal for every coordinate that is not tiny, and Decimal(repr(v))
        # formatted 'f' is then that same string - held here over every
        # coordinate in the gobras set and 400,000 random ones. A square is
        # 320,000 coordinates and this is 94 ms of a write rather than 191
        s = repr(float(v))
        if 'e' in s or 'E' in s:
            return format(Decimal(s), 'f')
        return s

    attrs = dict(square.attrs)
    attrs.setdefault('version', '0.6')
    attrs['upload'] = 'never'                     # whatever it was read with, this is not for the live map
    attrs['generator'] = generator
    lines = ["<?xml version='1.0' encoding='UTF-8'?>",
             '<osm ' + ' '.join(f'{k}={q(v)}' for k, v in attrs.items()) + '>']
    for nid in sorted(square.nodes, reverse=True):           # highest (least negative) first, as JOSM lists them
        n = square.nodes[nid]
        if n.tags:
            lines.append(f"  <node id='{nid}' action='modify' lat='{deg(n.lat)}' lon='{deg(n.lon)}'>")
            lines += [f"    <tag k={q(k)} v={q(v)} />" for k, v in n.tags.items()]
            lines.append('  </node>')
        else:
            lines.append(f"  <node id='{nid}' action='modify' lat='{deg(n.lat)}' lon='{deg(n.lon)}' />")
    for wid in sorted(square.ways, reverse=True):
        w = square.ways[wid]
        lines.append(f"  <way id='{wid}' action='modify'>")
        lines += [f"    <nd ref='{r}' />" for r in w.refs]
        lines += [f"    <tag k={q(k)} v={q(v)} />" for k, v in w.tags.items()]
        lines.append('  </way>')
    lines.append('</osm>')
    text = '\n'.join(lines) + '\n'
    fd, tmp = tempfile.mkstemp(suffix=path.suffix, dir=str(path.parent))
    os.close(fd)
    try:
        if path.suffix == '.xz':
            with lzma.open(tmp, 'wt', encoding='utf-8', preset=preset) as f:
                f.write(text)
        else:
            Path(tmp).write_text(text, encoding='utf-8')
        if path.exists():
            os.chmod(tmp, os.stat(path).st_mode & 0o7777)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise
    return path


# any way carrying an elevation is a constraint, contour or water edge alike
_HAS_ELE = re.compile(rb"""k=["']ele["']""")


# xz's magic bytes. A square is read by what it is rather than by what it is
# called: a compressed file under a bare .osm name would otherwise be scanned
# as text, find no ele in the compressed bytes, and be taken for a blank
# template - so the square would be dropped from the build with nothing said.
# That is the failure this codebase keeps meeting, and a six byte read closes it
_XZ_MAGIC = b'\xfd7zXZ\x00'


def open_square_file(path: str | os.PathLike):
    """The square's bytes, decompressed if they are compressed."""
    with open(path, 'rb') as probe:
        compressed = probe.read(len(_XZ_MAGIC)) == _XZ_MAGIC
    return lzma.open(path, 'rb') if compressed else open(path, 'rb')


def has_constraints(path: str | os.PathLike, chunk: int = 1 << 20) -> bool:
    """True if the square has any ``ele`` tag - which is what separates a
    square somebody has drawn from one of the blank templates handed out to
    mappers, and so which squares a zone is built over.

    Reads in chunks and stops at the first, since a filled square can be 87 MB
    and most are answered by the first page. Decompressing as it goes, where
    the file is compressed, so a blank template costs a few kilobytes rather
    than the whole file - and compressed is decided by the file's first bytes,
    not by its name."""
    tail = b''
    with open_square_file(path) as f:
        while True:
            block = f.read(chunk)
            if not block:
                return False
            if _HAS_ELE.search(tail + block):
                return True
            tail = block[-16:]
