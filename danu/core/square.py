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
from typing import Iterator
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


@dataclass(slots=True, frozen=True)
class Member:
    """One member of a relation: what it is, which one, and what part it
    plays. ``role`` is ``outer`` or ``inner`` on a multipolygon and the empty
    string on plenty of others, which OSM writes as an absent attribute."""
    type: str          # 'node', 'way' or 'relation'
    ref: int
    role: str = ''


@dataclass(slots=True)
class Relation:
    """A relation the square carries - R41.

    Which is here for one shape above all: a lake with an island in it is a
    multipolygon with an inner ring, and there is no way to hold one as closed
    ways. Losing the island does not merely lose a shape, it puts it under
    water, because a water body flattened at a level flattens everything it
    encloses.

    Members are kept in file order and with their roles, because both are
    data: a multipolygon's rings are its outers and inners, and nothing here
    may decide it knows better than the file what order they came in."""
    id: int
    members: list[Member] = field(default_factory=list)
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def ele(self) -> float | None:
        """The elevation, by the same rule a way's is read by. A water body
        flattened at a level carries one."""
        return parse_ele(self.tags.get('ele'))


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


def water_tags(tags: dict) -> bool:
    """``natural=water``, or any ``waterway``. Asked of a way and of a
    relation with the one function, so the two cannot drift apart."""
    return tags.get('natural') == 'water' or 'waterway' in tags


def parse_ele(value: str | None) -> float | None:
    """A tag's elevation, or None where there is not one.

    None for ``ele=TBD`` on a lake outlet nobody has surveyed and ``ele=tbd``
    on a peak, which squares really carry - and None for ``inf`` and ``nan``,
    which ``float`` accepts and nothing downstream survives. An infinite
    elevation reaches a colour ramp, a ladder, a label and a rasteriser, and
    each of them does something different and silent with it. Not a number is
    not a number however Python spells it."""
    if value is None:
        return None
    try:
        v = float(value.strip())
    except ValueError:
        return None
    return v if math.isfinite(v) else None


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
    relations: dict[int, Relation] = field(default_factory=dict)
    # the <osm> element's attributes - upload='never' above all, which a save
    # must carry forward unchanged, since it is what stops JOSM putting these
    # negative ids onto the live map
    attrs: dict[str, str] = field(default_factory=dict)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        return self.name.bounds

    def contours(self) -> Iterator[Way]:
        """Ways with a usable elevation, in file order - and not water. A lake
        flattened at a level carries it on its outline (G7a), which the build
        reads as a contour and should; in the editor it is the water's level,
        and a contour only in what the surface is built from.

        A waterway *line* with an ``ele`` is still a contour here, as it always
        was: squares carry them on purpose - Los Pizarrales has eight
        ``ldata:survey=thalweg`` river pieces, each at one level, pinning a
        valley floor - and they are a mapper's constraint like any other."""
        bodies = self.water_bodies()
        for way in self.ways.values():
            # and not a lake's fill line (G7a): the lake's level drawn across
            # it for the build's sake, no contour of anybody's
            if way.ele is not None and way.id not in bodies and 'danu:fill' not in way.tags:
                yield way

    def water_bodies(self) -> set[int]:
        """The outlines of still water: a closed ``natural=water`` way, and
        every ring of a water relation, whose tagging is the relation's."""
        out = {w.id for w in self.ways.values()
               if w.tags.get('natural') == 'water' and w.closed}
        for rel in self.relations.values():
            if water_tags(rel.tags):
                out.update(m.ref for m in rel.members if m.type == 'way')
        return out

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
            elif elem.tag == 'relation':
                square.relations[int(elem.get('id'))] = Relation(
                    id=int(elem.get('id')),
                    members=[Member(type=mem.get('type'), ref=int(mem.get('ref')),
                                    role=mem.get('role') or '')
                             for mem in elem.iter('member')],
                    tags=_tags(elem))
                elem.clear()
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
    nodes, ways and tags, in the same order, and the build makes the same
    surface from it.

    "In the same order" is load-bearing and was not always true. The golden
    test asserts the surface claim, but on a fixture whose ways are already
    sorted, so it went on passing while a square with JOSM's real ordering
    came out different - see the loop over the ways in square_text.

    Written to a temporary beside the target and moved into place, so a
    failure mid-write leaves the old file whole. The two halves are
    ``square_text`` and ``write_text``, which the editor runs apart."""
    return write_text(square_text(square, generator), path, preset)


def square_text(square: Square, generator: str = 'danu') -> str:
    """The square as ``write_square`` writes it, as text: what a save reads
    of the square, all of it, so the compression can be done elsewhere while
    the square goes on being edited."""
    import html
    from decimal import Decimal

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
    # Nodes in the order they were read. Nothing in the build depends on it -
    # a way names its nodes by ref and the rasteriser never sees the node
    # layer - so this is fidelity rather than correctness: a square opened and
    # saved should differ from the one that was opened only where it was
    # edited, which is what makes a diff of two versions worth reading.
    for nid in square.nodes:
        n = square.nodes[nid]
        if n.tags:
            lines.append(f"  <node id='{nid}' action='modify' lat='{deg(n.lat)}' lon='{deg(n.lon)}'>")
            lines += [f"    <tag k={q(k)} v={q(v)} />" for k, v in n.tags.items()]
            lines.append('  </node>')
        else:
            lines.append(f"  <node id='{nid}' action='modify' lat='{deg(n.lat)}' lon='{deg(n.lon)}' />")
    # Ways in the order they were read, and here it is correctness. Not sorted,
    # which is what this did on the belief that JOSM writes them sorted: JOSM
    # mostly does, and where it does not - one block of ids sitting among an
    # older run, which is what an edit in a later session leaves - sorting
    # reorders them.
    #
    # gdal_rasterize burns the contours in layer order and the last one to
    # touch a cell wins it, so where two contours of different elevations meet
    # the same cell, the order decides the constraint and the first pass fills
    # from it. Reading N20E087_Artana and writing it back unchanged moved 4,155
    # cells of the gobras 3x3 by up to 650 m: a square merely opened and saved
    # would have published a different surface, and 99 of the 806 drawn squares
    # on the server are ordered so that it would have.
    for wid in square.ways:
        w = square.ways[wid]
        lines.append(f"  <way id='{wid}' action='modify'>")
        lines += [f"    <nd ref='{r}' />" for r in w.refs]
        lines += [f"    <tag k={q(k)} v={q(v)} />" for k, v in w.tags.items()]
        lines.append('  </way>')
    # Relations last, as JOSM writes them and as the file has to be read: a
    # member names a way by id, and a reader that meets the relation first has
    # to hold the reference until the way arrives. Nothing here does - the
    # parse keeps dictionaries and resolves nothing - but the file is read by
    # other things, and the order a square is written in is the order it was
    # read in for everything else in this function.
    #
    # Members in file order, with their roles, both of which are data: a
    # multipolygon's outer and inner rings are told apart by the role, and an
    # empty one is written as an absent attribute because that is what it is.
    for rid in square.relations:
        r = square.relations[rid]
        lines.append(f"  <relation id='{rid}' action='modify'>")
        for mem in r.members:
            role = f" role={q(mem.role)}" if mem.role else ''
            lines.append(f"    <member type={q(mem.type)} ref='{mem.ref}'{role} />")
        lines += [f"    <tag k={q(k)} v={q(v)} />" for k, v in r.tags.items()]
        lines.append('  </relation>')
    lines.append('</osm>')
    return '\n'.join(lines) + '\n'


def write_text(text: str, path: str | os.PathLike, preset: int = 6) -> Path:
    """A square's text to its file: ``.osm.xz`` compressed, ``.osm`` plain,
    by a temporary beside it moved into place. No square is read here - it
    is the half of a save that may run off the UI thread. Compression is
    most of a save: 10 s of N20E086's 10.5 at the default preset."""
    import tempfile
    path = Path(path)
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
# R42: what makes a square one somebody has drawn rather than one of the
# blanks. An elevation, a coastline, or water.
#
# A coastline in *these* squares is tagged ele=0 as well as natural=coastline
# - checked against the gobras set, where every one carries both - which is
# why coastline-only squares have always counted under the ele scan alone.
# That is a fact about this pipeline's files and not about OSM, where a
# coastline carries no elevation at all, so the coastline branch below is not
# the redundancy it looks: it is what catches one drawn somewhere else, or by
# a mapper who did not add the zero.
#
# The pair matched together for natural, because `v='water'` on its own would
# answer for anything - a landuse, a name, a note. Either order and with
# anything between, as long as both are inside the one tag element, which
# `[^>]` is what keeps: JOSM and write_square put them adjacent and k first,
# and this file is read from wherever a mapper got it.
_NATURAL = rb"""k=["']natural["']"""
_WATERY = rb"""v=["'](?:water|coastline)["']"""
_HAS_ELE = re.compile(rb"""k=["']ele["']""")
_HAS_CONSTRAINT = re.compile(
    rb"""k=["']ele["']"""
    rb"""|k=["']waterway["']"""
    + rb"""|""" + _NATURAL + rb"""[^>]{0,60}""" + _WATERY
    + rb"""|""" + _WATERY + rb"""[^>]{0,60}""" + _NATURAL)
# enough to hold the longest of those across a chunk boundary. The longest the
# alternation can match is a pair the wide way round - `v='coastline'` at 13
# bytes, sixty between, `k='natural'` at 11 - which is 84, and a little more
# with double quotes. 128 leaves room to widen the gap without coming back
# here, which is the only reason it is not 96
_SCAN_OVERLAP = 128


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
    """True if the square carries an elevation, a coastline or water - R42,
    and what separates a square somebody has drawn from one of the blank
    templates handed out to mappers, and so which squares a zone is built
    over.

    Water joined that list when an import could bring a square into being
    holding nothing else. It changes less than it looks: a square whose water
    has an elevation was already caught by the ``ele`` scan, and one whose
    water has none contributes no ground until G6 gives it one - ``collect``
    gathers lines with an ``ele`` and nothing else. What it does is stop such
    a square being read as a blank template, which is what it is not.

    The coastline branch is not redundant either, though a coastline in these
    squares carries ``ele=0`` and would be caught without it. That is a fact
    about this pipeline's files; a coastline from anywhere else carries no
    elevation.

    Reads in chunks and stops at the first, since a filled square can be 87 MB
    and most are answered by the first page. Decompressing as it goes, where
    the file is compressed, so a blank template costs a few kilobytes rather
    than the whole file - and compressed is decided by the file's first bytes,
    not by its name."""
    return _scan(path, _HAS_CONSTRAINT, chunk)


def has_elevation(path: str | os.PathLike, chunk: int = 1 << 20) -> bool:
    """True if the square carries an ``ele`` anywhere - a contour, a spot
    height, a level on its water, a coastline's zero. Whether a build has
    anything to read at all - G6c: a square of water and nothing else is
    drawn (R42) but holds no ground, and an import of the gobras set creates
    five, three of them a degree west of the zone, which stretched its raster
    by a quarter with nothing in it. The grid itself is then taken over those
    of them that brought a way with a numeric ``ele``."""
    return _scan(path, _HAS_ELE, chunk)


def _scan(path, pattern, chunk: int) -> bool:
    tail = b''
    with open_square_file(path) as f:
        while True:
            block = f.read(chunk)
            if not block:
                return False
            if pattern.search(tail + block):
                return True
            # the rolling tail, not this block's: a chunk smaller than the
            # token leaves `block[-n:]` shorter than the token, and a pair
            # spanning three small reads is never whole in any one window
            tail = (tail + block)[-_SCAN_OVERLAP:]
