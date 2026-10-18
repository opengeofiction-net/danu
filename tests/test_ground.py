"""danu.core.ground: a shared square's ground, as the editor shades it (#190)."""

import json

import pytest

pytest.importorskip('osgeo.ogr', reason='GDAL not available')

from danu.core import ground as G
from danu.core import territory as T

# [lat, lon] as published: lon 0..0.5 is One's, 0.5..1 Two's; Three an
# enclave - a hole in Four - and Four round it, both in the square at 10
GEOMETRY = {
    '1': [[0, 0], [1, 0], [1, 0.5], [0, 0.5]],
    '2': [[0, 0.5], [1, 0.5], [1, 1], [0, 1]],
    '3': [[10.4, 10.4], [10.6, 10.4], [10.6, 10.6], [10.4, 10.6]],
    '4': [[[10, 10], [11, 10], [11, 11], [10, 11]], [[10.4, 10.4], [10.6, 10.4], [10.6, 10.6], [10.4, 10.6]]],
    # at 60 N, One's west 0.6 and Two's east 0.6, overlapping by 0.2
    '5': [[60, 0], [61, 0], [61, 0.6], [60, 0.6]],
    '6': [[60, 0.4], [61, 0.4], [61, 1], [60, 1]],
}
ATTRIBUTES = [{'rel': 1, 'ogfId': 'A1', 'name': 'One', 'owner': 'wangi'},
              {'rel': 2, 'ogfId': 'A2', 'name': 'Two', 'owner': 'Luciano'},
              {'rel': 3, 'ogfId': 'A3', 'name': 'Three', 'owner': 'wangi'},
              {'rel': 4, 'ogfId': 'A4', 'name': 'Four', 'owner': 'Luciano'},
              {'rel': 5, 'ogfId': 'A5', 'name': 'Five', 'owner': 'wangi'},
              {'rel': 6, 'ogfId': 'A6', 'name': 'Six', 'owner': 'Luciano'}]
KX = 111320.0                     # metres a degree of longitude at the equator


def index():
    return T.TerritoryIndex(T.parse_geometry(json.dumps(GEOMETRY)), T.parse_attributes(json.dumps(ATTRIBUTES)))


def area(polys):
    out = 0.0
    for rings in polys:
        for i, r in enumerate(rings):
            a = abs(sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(r, r[1:] + r[:1], strict=True))) / 2
            out += a if i == 0 else -a
    return out


def east(polys):
    return max(x for rings in polys for r in rings for x, _ in r)


def test_a_shared_square_shades_the_neighbour_near_and_far():
    g = G.ground(index(), (0, 0, 1, 1), 'wangi')
    assert area(g.mine) == pytest.approx(0.5, abs=1e-6)
    assert east(g.near) == pytest.approx(0.5 + 2000 / KX, abs=1e-4), 'the band reaches 2 km into Two'
    assert area(g.near) == pytest.approx(2000 / KX, rel=0.01)
    assert area(g.near) + area(g.far) == pytest.approx(0.5, abs=1e-6)
    assert min(x for rings in g.far for r in rings for x, _ in r) == pytest.approx(0.5 + 2000 / KX, abs=1e-4)


def test_where_they_overlap_it_is_yours_and_a_degree_east_is_shorter_north():
    g = G.ground(index(), (0, 60, 1, 61), 'wangi')
    assert area(g.mine) == pytest.approx(0.6, abs=1e-6)
    assert area(g.near) + area(g.far) == pytest.approx(0.4, abs=1e-6), 'the overlap is not shaded'
    import math
    reach = 2000 / (KX * math.cos(math.radians(60.5)))
    assert east(g.near) == pytest.approx(0.6 + reach, abs=1e-4)


def test_a_collection_from_an_overlay_is_unpacked_to_its_polygons():
    from osgeo import ogr
    local = G._Local(0, 0)
    gc = ogr.CreateGeometryFromWkt('GEOMETRYCOLLECTION(LINESTRING(0 0,1 1),'
                                   'MULTIPOLYGON(((0 0,100 0,100 100,0 0)),((200 0,300 0,300 100,200 0))))')
    assert len(local.back(gc)) == 2


def test_a_square_all_yours_or_nobody_elses_is_not_shaded():
    g = G.ground(index(), (0.05, 0.05, 0.45, 0.95), 'wangi')
    assert g.near == [] and g.far == [] and area(g.mine) == pytest.approx(0.36)


def test_a_square_none_of_yours_is_all_far():
    g = G.ground(index(), (0, 0, 1, 1), 'nobody')
    assert g.mine == [] and g.near == [] and area(g.far) == pytest.approx(1.0, abs=1e-6)


def test_an_enclave_is_the_hole_in_its_neighbour():
    g = G.ground(index(), (10, 10, 11, 11), 'wangi')
    assert area(g.mine) == pytest.approx(0.04, abs=1e-6), 'Three, not Four'
    assert area(g.near) + area(g.far) == pytest.approx(0.96, abs=1e-6)
    # a band round all four sides, its corners rounded: in degrees at 10.5 N
    import math
    dx, dy = 2000 / (KX * math.cos(math.radians(10.5))), 2000 / 110574
    assert area(g.near) == pytest.approx(0.4 * dx + 0.4 * dy + math.pi * dx * dy, rel=0.01)
    g = G.ground(index(), (10, 10, 11, 11), 'Luciano')
    assert area(g.mine) == pytest.approx(0.96, abs=1e-6), 'Four, its hole out'
    assert area(g.near) + area(g.far) == pytest.approx(0.04, abs=1e-6) and area(g.far) > 0
