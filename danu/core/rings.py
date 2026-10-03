"""Closed rings, from the ways that make them.

A lake is a `type=multipolygon` relation and its boundary is in pieces: a
dozen ways, in whatever order the relation lists them and in whatever
direction each was drawn. Nothing can be filled until those are stitched back
into rings.

Why it has to be done at all: a filled lake is the only way a water body reads
as water rather than as a contour, and a ring filled one way at a time is
wrong in the one case that matters - an island in a lake is an `inner` ring,
and filling each ring on its own paints the island solid. One path per
relation, with every ring in it and an odd-even fill, makes the island a hole
without the painter being told which ring is which.

What cannot be stitched is left alone. A square holds its own degree and no
more, so a lake that crosses the edge arrives with its boundary cut: those
ways chain into something open, and an open chain is not a ring. It is drawn
as the line it is. Closing it would draw a shoreline along the square edge
that no one mapped.
"""

from __future__ import annotations

from .square import Square


def _chains(ways: list[list[int]]) -> list[list[int]]:
    """Node-id sequences joined end to end, as far as each will go.

    Greedy and order-independent: a piece is taken off the pile whenever
    either of its ends meets either end of the chain being built, reversed if
    that is the end that matched. A relation lists its members in no
    particular order and a way is drawn in no particular direction, so both
    have to be allowed for.
    """
    pile = [list(w) for w in ways if len(w) >= 2]
    out: list[list[int]] = []
    while pile:
        chain = pile.pop(0)
        joined = True
        while joined and chain[0] != chain[-1]:
            joined = False
            for i, piece in enumerate(pile):
                if piece[0] == chain[-1]:
                    chain += piece[1:]
                elif piece[-1] == chain[-1]:
                    chain += piece[-2::-1]
                elif piece[-1] == chain[0]:
                    chain = piece[:-1] + chain
                elif piece[0] == chain[0]:
                    chain = piece[:0:-1] + chain
                else:
                    continue
                pile.pop(i)
                joined = True
                break
        out.append(chain)
    return out


def closed_rings(ways: list[list[int]]) -> list[list[int]]:
    """Only the chains that came back to where they started. The first node is
    the last, so a caller drawing one does not have to close it itself."""
    return [c for c in _chains(ways) if len(c) > 3 and c[0] == c[-1]]


def relation_rings(square: Square, relation) -> list[list[int]]:
    """A relation's rings, from the member ways the square actually holds.

    A member the square does not have is simply not there to stitch with, and
    the chain it would have joined stays open - which is the straddling case,
    and is meant to come out unfilled rather than closed across the edge.
    """
    ways = [square.ways[mem.ref].refs for mem in relation.members
            if mem.type == 'way' and mem.ref in square.ways]
    return closed_rings(ways)


def is_closed(way) -> bool:
    """A way that is its own ring: at least a triangle, and ending where it
    began."""
    return len(way.refs) > 3 and way.refs[0] == way.refs[-1]
