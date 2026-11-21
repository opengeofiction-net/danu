"""Graded waterways, held by the second pass rather than read by the first - #372.

Grading (G, Shift+G) writes an ``ele`` onto the vertices of a river. Read as
spot heights, the way every other node with an ``ele`` is (R36), they spoiled
the ground beside the river wherever the contours either side are further apart
than the fill reaches: a river a few metres below the contour beside it is the
steepest pair in sight, so the first pass filled the ground between them nearly
flat, out to the edge of its reach, and the ground then stepped up there to meet
the contour beyond. On castellan at 65.360E, a 13 m cliff 2 km from the river.

So a graded waterway is not a constraint. Its heights are a line, interpolated
between its vertices, which isofill holds in its second pass (0.14.0,
``--held``): the first pass never sees it, and the solve runs the ground down to
it from the contours either side. On castellan that is a valley where there was
a plain and a cliff, and it moves 1.55% of the land by more than a metre.

This is the one place that says which nodes those are and what line they make,
for the build and the editor's preview both (R35).
"""

from __future__ import annotations

from ..core.square import parse_ele

# The waterways that run as a line. ``flows`` also takes waterway=riverbank and
# water=river, which are areas: grading refuses those (R27), and a vertex of
# one with a height is nothing this knows how to hold.
KINDS = ('river', 'stream', 'canal', 'ditch', 'drain')

# And the landforms drawn as a line, by OSM's natural=* (#191): a valley floor,
# a gully, a gorge - the low line of the ground, as a river is - and a ridge
# or an arete, its high line. Heights on their vertices are held the same way:
# the second pass runs the ground down to a valley floor from the contours
# either side, and up to a crest.
FLOORS = ('valley', 'gully', 'gorge')
CRESTS = ('ridge', 'arete')
LANDFORMS = FLOORS + CRESTS

# Nothing to look for in a square that never says it: the byte guard ``collect``
# uses before parsing a square for anything.
WORDS = (b"'waterway'", b'"waterway"') + tuple(
    q + k.encode() + q for k in LANDFORMS for q in (b"'", b'"'))


def landform(way) -> str | None:
    """The way's landform, a ``natural=*`` value of LANDFORMS, or None."""
    kind = way.tags.get('natural')
    return kind if kind in LANDFORMS else None


def is_crest(way) -> bool:
    """Whether a way is a ridge or an arete: graded between the contours it
    crosses, rising and falling as they do, rather than descending as water
    and a valley floor do."""
    return way.tags.get('natural') in CRESTS


def graded_way(way) -> bool:
    """Whether a way's vertices' heights are held: a waterway that runs as a
    line, or a landform drawn as one."""
    return way.tags.get('waterway') in KINDS or landform(way) is not None


def _vertices(square, way):
    """Each vertex of the way as (ref, node, ele), ele None where it carries
    no height - the one reading of a vertex ``runs`` and ``graded`` share, so
    the nodes they call held cannot drift apart."""
    for ref in way.refs:
        node = square.nodes.get(ref)
        yield ref, node, parse_ele(node.tags.get('ele')) if node is not None else None


def runs(square, way) -> list[list[tuple[float, float, float]]]:
    """The way's held runs, as (lon, lat, ele) each: every stretch of its
    vertices that all carry a height, in order. A stretch of one - a vertex
    with a height between two without - is a run of one, held at its cell.
    Empty for a way that is not a graded waterway."""
    if not graded_way(way):
        return []
    out: list[list[tuple[float, float, float]]] = []
    run: list[tuple[float, float, float]] = []
    for _ref, node, ele in _vertices(square, way):
        if ele is None:
            if run:
                out.append(run)
            run = []
        else:
            run.append((node.lon, node.lat, ele))
    if run:
        out.append(run)
    return out


def feature(defn, run, way_id, square=None):
    """A held run as a feature of the ``held`` layer: a line through its
    vertices with each one's height for Z, or a point for a run of one. The
    build's layer and the preview's are made of these alike."""
    from osgeo import ogr
    g = ogr.Geometry(ogr.wkbPoint25D if len(run) == 1 else ogr.wkbLineString25D)
    for lon, lat, ele in run:
        g.AddPoint(float(lon), float(lat), float(ele))
    f = ogr.Feature(defn)
    f.SetGeometry(g)
    f.SetField('osm_id', str(way_id))
    if square is not None and defn.GetFieldIndex('square') >= 0:
        f.SetField('square', square)
    return f


def graded(square) -> tuple[dict[int, list], set[int]]:
    """The square's held runs by way id, and the ids of the nodes in them -
    which are not spot heights, however many other ways they are on."""
    by_way: dict[int, list] = {}
    nodes: set[int] = set()
    for wid, way in square.ways.items():
        got = runs(square, way)
        if not got:
            continue
        by_way[wid] = got
        nodes.update(ref for ref, _node, ele in _vertices(square, way) if ele is not None)
    return by_way, nodes
