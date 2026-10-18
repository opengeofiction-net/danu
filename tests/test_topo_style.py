"""danu.core.topo_style: the wiki's colours for zones and squares, and its
test of a square, shared with the editor (#190)."""

from danu.core import topo_style as TS
from danu.core.square import Node, Square, SquareName, Way


def square(*eles, node_ele=None):
    sq = Square(name=SquareName(86, 20), present=True)
    sq.nodes = {-1: Node(-1, 20.5, 86.5), -2: Node(-2, 20.6, 86.6)}
    if node_ele is not None:
        sq.nodes[-3] = Node(-3, 20.7, 86.7, {'ele': node_ele})
    sq.ways = {-10 - i: Way(-10 - i, [-1, -2], {'ele': e}) for i, e in enumerate(eles)}
    return sq


def test_a_square_is_drawn_coastline_only_or_blank_as_the_report_says():
    assert TS.square_class(square('0', '125')) == TS.SQUARE
    assert TS.square_class(square('0', '0')) == TS.SQUARE_COASTLINE
    assert TS.square_class(square('TBD', '169s')) == TS.SQUARE_BLANK, 'not numbers: nothing'
    assert TS.square_class(square()) == TS.SQUARE_BLANK
    assert TS.square_class(square('0', node_ele='312')) == TS.SQUARE, 'a spot height is an elevation'


def test_the_wikis_template_is_drawn_from_these():
    from danu.report import zones_to_multimap as Z
    assert Z.STYLES is TS.STYLES and Z.CLASS_ZONE_INACTIVE == 'zone-inactive' == TS.ZONE_INACTIVE
    assert set(TS.STYLES) == {'zone', 'zone-inactive', 'square', 'square-coastline', 'square-blank'}
