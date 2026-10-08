"""What the set holds that upstream no longer has - R40, G5b.

R40: *a feature gone from upstream is reported rather than deleted.* A square
is somebody's work, an elevation set on a lake is part of it, and an import is
not entitled to throw that away because a river was redrawn somewhere else.
So this reports, and decides nothing; G5c puts the report where a mapper can
work through it.

A held feature is gone when the answer does not name it and the query would
have - ``overpass.asked_for``, the query's own selection said a second time.
Without that test every coastline and contour would be reported missing on
every import. Absence from a whole answer then means one of two things, and
the report does not pretend to know which: deleted upstream, or retagged out
of what the query asks for (a river become a drain). An answer that is not
whole never gets this far - ``overpass.IncompleteAnswer``.

Three limits on what counts, as `docs/implementation.md` lists them:

- **Positive ids only.** A negative id was allocated here, for something the
  mapper drew; it was never upstream, so it cannot have left.
- **A way a held water relation names counts too**, tagged or not. A lake's
  ring carries no tags of its own - the relation holds them - and when
  upstream redraws the ring under a new id, the relation comes back naming
  the new one and the old way is left in the square as an untagged line that
  nothing names. That is exactly what a mapper needs telling about, and the
  tag test alone would never find it. The comparison is made *before* the
  import is applied, while the held relation still names the old ring.
- **The whole answer, not the square's share of it.** Placement is per
  square and identity is not, and a feature placed into a neighbour is not
  gone.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.square import SquareName
from .overpass import asked_for


@dataclass(frozen=True)
class Gone:
    """One held feature the answer did not name."""
    square: SquareName
    kind: str                # 'way' or 'relation', or 'node' - a spot height (G9)
    id: int
    name: str | None         # what a mapper will recognise it by, if anything
    what: str                # the kind of water, or why it counted at all
    # for a ring: the held water relation naming it, lowest id first, so the
    # dock can list the ring under its lake rather than beside it
    of: int | None = None

    def describe(self) -> str:
        label = f'{self.what} "{self.name}"' if self.name else self.what
        return f'{label} - {self.kind} {self.id} in {self.square}'


def _what(kind: str, tags: dict, member: bool) -> str:
    if 'waterway' in tags:
        return tags['waterway']
    if tags.get('natural') == 'water':
        return tags.get('water', 'water')
    return 'lake ring' if member else kind


def gone(working_set, answered_ways, answered_relations) -> list[Gone]:
    """Every held water feature the answer did not name, in a stable order:
    by square, then relations before ways, then id."""
    out: list[Gone] = []
    for name in sorted(working_set.squares, key=str):
        square = working_set.squares[name]
        rings: dict[int, int] = {}            # ring way -> a relation naming it
        for rel in sorted(square.relations.values(), key=lambda r: r.id):
            if not asked_for('relation', rel.tags):
                continue
            for mem in rel.members:
                if mem.type == 'way':
                    rings.setdefault(mem.ref, rel.id)
            if rel.id > 0 and rel.id not in answered_relations:
                out.append(Gone(name, 'relation', rel.id, rel.tags.get('name'),
                                _what('relation', rel.tags, False)))
        for way in square.ways.values():
            if way.id <= 0 or way.id in answered_ways:
                continue
            member = way.id in rings
            if member or asked_for('way', way.tags):
                out.append(Gone(name, 'way', way.id, way.tags.get('name'),
                                _what('way', way.tags, member), rings.get(way.id)))
    out.sort(key=lambda g: (str(g.square), g.kind != 'relation', g.id))
    return out
