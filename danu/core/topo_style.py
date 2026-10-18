"""How the topo layer's zones and squares look, wherever they are drawn
(#190): on the wiki's map of them (OpenGeofiction:Topo layer, from the
template ``danu.report.zones_to_multimap`` publishes) and in the editor's.
One set of colours, so a zone or a square looks the same in both. Leaflet's
terms: ``weight`` is a line's width in pixels, the opacities 0 to 1.

The class names are the wiki page's - it filters its overlays on them. And
``square_class`` is the report's rule for a square - drawn if any elevation
is non-zero, coastline only if the only elevations are 0, blank otherwise,
an elevation that is not a number counting for nothing - asked of a square
the editor holds. The report asks it of the file, scanning the raw XML
(``zones_to_multimap.classify_square``): two implementations of one rule,
kept in step by ``tests/test_topo_style.py``, which puts the same squares to
both.
"""

from __future__ import annotations

from .square import Square, parse_ele

ZONE = 'zone'
ZONE_INACTIVE = 'zone-inactive'
SQUARE = 'square'
SQUARE_COASTLINE = 'square-coastline'
SQUARE_BLANK = 'square-blank'

STYLES = {
    ZONE: {'color': '#1f78b4', 'opacity': 1, 'weight': 5, 'fillColor': '#1f78b4', 'fillOpacity': 0},
    ZONE_INACTIVE: {'color': '#999999', 'opacity': 1, 'weight': 5, 'fillColor': '#999999', 'fillOpacity': 0.5},
    SQUARE: {'color': '#33a02c', 'opacity': 1, 'weight': 3, 'fillColor': '#33a02c', 'fillOpacity': 0.10},
    SQUARE_COASTLINE: {'color': '#ff7f00', 'opacity': 0.5, 'weight': 1, 'fillColor': '#ff7f00', 'fillOpacity': 0.10},
    SQUARE_BLANK: {'color': '#b2b2b2', 'opacity': 0.5, 'weight': 1, 'fillColor': '#ffffff', 'fillOpacity': 0.5},
}


def square_class(sq: Square) -> str:
    """SQUARE, SQUARE_COASTLINE or SQUARE_BLANK, as the report says of the
    file: an elevation that is not a number counts for nothing."""
    coast = False
    for tagged in (*sq.ways.values(), *sq.nodes.values()):
        ele = parse_ele(tagged.tags.get('ele')) if tagged.tags else None
        if ele is None:
            continue
        if ele != 0.0:
            return SQUARE
        coast = True
    return SQUARE_COASTLINE if coast else SQUARE_BLANK
