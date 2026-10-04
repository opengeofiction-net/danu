"""What an import does to a feature the square already holds - R40, G5a.

The identity is free. An import lands under the upstream OSM ids, so a second
import names exactly the ids the first one wrote, and "is this the same lake"
is a dictionary lookup rather than a geometric guess. Measured on the gobras
set: a first import overlaps nothing the squares hold - no way, no node, no
node a contour also uses - and a second overlaps everything.

What it does then is a split of ownership, and the split is the whole of R40.
**Upstream owns where the water is**: a matched feature takes its refs, its
node positions, its members and the tags upstream is the authority for
(`natural`, `water`, `waterway`, `name`) from the answer. **The mapper owns how
high it is**: `ele` set here survives, and so does any tag outside the
upstream-owned set, since nothing else would have put it on an imported
feature. Upstream's own `ele` fills in only where the mapper has set none.

This replaces G4b's floor, which overwrote a matched feature whole - so a
second import silently threw away every elevation set since the first. It took
itself back exactly; it just did the wrong thing first.

A re-route leaves vertices behind: nodes the old way named and the new one
does not. Untagged, and named by nothing else in the square, they are removed -
a vertex is part of the way and goes where the way goes. Tagged, they stay:
a node with an `ele` on it is a spot height somebody placed, and an import is
not entitled to throw that away (the same rule G5b applies to whole features).

A node a local way shares with an imported one - a contour snapped to a river
- moves with the river, because upstream owns where the river is and the
contour was put on it deliberately. The local ways that hold such a node are
reported as `moved`, so the caller redraws them; nothing in the gobras data
does this today, but G7's burn will.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .square import Node, Relation, Square, Way


@dataclass
class Reconciled:
    """What to write, and what that writing does beyond the features named."""
    nodes: dict[int, Node] = field(default_factory=dict)
    ways: dict[int, Way] = field(default_factory=dict)
    relations: dict[int, Relation] = field(default_factory=dict)
    # vertices a re-route left behind: untagged, and named by nothing else
    removed: set[int] = field(default_factory=set)
    # local ways - not in the import - holding a node the import moved
    moved: set[int] = field(default_factory=set)


def merge_tags(local: dict[str, str], upstream: dict[str, str],
               owns: tuple[str, ...]) -> dict[str, str]:
    """Upstream's tags for the keys it owns, the mapper's for everything else.

    A key upstream owns follows upstream even when upstream has dropped it - a
    river renamed upstream loses its old name here too, and a local `name`
    does not outlive the one it was copied from. `ele` is the mapper's, and
    upstream's fills in only where the mapper set none. The order is
    upstream's, then `ele`, then the mapper's own, so a feature with nothing
    of the mapper's writes the line it would have written on a first import.
    """
    out = {k: v for k, v in upstream.items() if k in owns}
    if 'ele' in local:
        out['ele'] = local['ele']
    elif 'ele' in upstream:
        out['ele'] = upstream['ele']
    for k, v in local.items():
        if k not in owns and k != 'ele':
            out[k] = v
    return out


def _settled(local_tags: dict, upstream_tags: dict, owns: tuple[str, ...]) -> bool:
    """Whether the merged tags are simply upstream's, so its object can be
    written as it is. Asked of a hundred and fifty thousand vertices on a
    second import of the gobras set, nearly all with no tags on either side -
    and a vertex allocated afresh to say the same thing would be most of the
    cost of the step."""
    if any(k not in owns for k in local_tags):
        return False            # the mapper has something of their own on it
    return all(k in owns or k == 'ele' for k in upstream_tags)


def reconcile(square: Square, nodes: dict[int, Node], ways: dict[int, Way],
              relations: dict[int, Relation], owns: tuple[str, ...]) -> Reconciled:
    """The import as it should land on this square.

    A feature the square does not hold is written as upstream has it. One it
    does is merged - geometry from upstream, tags by `merge_tags` - into a new
    object, never the square's own altered in place: the caller's undo holds
    the square's objects, and an object changed under it would come back
    changed.
    """
    out = Reconciled()
    held_nodes, held_ways, held_rels = square.nodes, square.ways, square.relations

    changed: set[int] = set()       # held nodes whose position upstream moved
    for i, up in nodes.items():
        here = held_nodes.get(i)
        if here is None:
            out.nodes[i] = up
            continue
        if here.lat != up.lat or here.lon != up.lon:
            changed.add(i)
        if _settled(here.tags, up.tags, owns):
            out.nodes[i] = up
        else:
            out.nodes[i] = Node(id=i, lat=up.lat, lon=up.lon,
                                tags=merge_tags(here.tags, up.tags, owns))

    left_behind: set[int] = set()   # vertices the held version named, upstream's does not
    for i, up in ways.items():
        here = held_ways.get(i)
        if here is None:
            out.ways[i] = up
            continue
        left_behind.update(here.refs)
        if _settled(here.tags, up.tags, owns):
            out.ways[i] = up
        else:
            out.ways[i] = Way(id=i, refs=list(up.refs),
                              tags=merge_tags(here.tags, up.tags, owns))

    for i, up in relations.items():
        here = held_rels.get(i)
        if here is None or _settled(here.tags, up.tags, owns):
            out.relations[i] = up
        else:
            out.relations[i] = Relation(id=i, members=list(up.members),
                                        tags=merge_tags(here.tags, up.tags, owns))

    # the vertices left behind, less any still in use. Narrowed before the
    # walk of the square's other ways, which is the one costly step here and
    # is skipped entirely when a re-import moved nothing - the common case
    if left_behind:
        left_behind -= nodes.keys()
        for w in out.ways.values():
            left_behind.difference_update(w.refs)
    if left_behind:
        for w in held_ways.values():
            if w.id not in ways:
                left_behind.difference_update(w.refs)
        for rel in held_rels.values():
            left_behind.difference_update(m.ref for m in rel.members if m.type == 'node')
        for rel in out.relations.values():
            left_behind.difference_update(m.ref for m in rel.members if m.type == 'node')
        out.removed = {i for i in left_behind
                       if i in held_nodes and not held_nodes[i].tags}

    if changed:
        out.moved = {w.id for w in held_ways.values()
                     if w.id not in ways and any(r in changed for r in w.refs)}
    return out
