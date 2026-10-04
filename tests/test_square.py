"""danu.core.square: names, one real square, and a working set around it.

The fixture is the golden square, S24E125 Los Pizarrales, because it is the one
real square in the repository and the one whose contents are pinned - so the
counts asserted here are facts about a file under version control, not about a
generator.
"""

import lzma
import shutil
from pathlib import Path

import pytest
from hypothesis import given
from hypothesis import strategies as st

from danu.core.square import Square, SquareName, WorkingSet, list_squares, parse_ele, read_square

GOLDEN = Path(__file__).parent / 'golden' / 'S24E125_Los_Pizarrales.osm.xz'


# ------------------------------------------------------------------ names

@given(st.integers(-180, 179), st.integers(-90, 89))
def test_name_round_trips(lon, lat):
    name = SquareName(lon, lat)
    assert SquareName.parse(name.name) == name
    assert SquareName.parse(name.name.lower()) == name


def test_name_formats_in_the_srtm_convention():
    assert SquareName(17, 42).name == 'N42E017'
    assert SquareName(-121, -3).name == 'S03W121'
    assert SquareName(0, 0).name == 'N00E000'
    assert SquareName(-1, -1).name == 'S01W001'


@pytest.mark.parametrize('bad', ['N42E17', 'X42E017', 'N42E017N', '', 'EMPTY',
                                 'N90E000', 'N00E180'])
def test_name_rejects_what_is_not_a_square(bad):
    with pytest.raises(ValueError):
        SquareName.parse(bad)


@pytest.mark.parametrize('fn', ['N18E088.osm.xz', 'N18E088_Katyapura.osm.xz',
                                'N18E088.osm', 'N18E088_Katya_pura.osm.xz',
                                '/some/zone/N18E088_Katyapura.osm.xz'])
def test_filename_carries_the_name_and_may_carry_a_label(fn):
    assert SquareName.from_filename(fn) == SquareName(88, 18)


@pytest.mark.parametrize('fn', ['EMPTY.osm.xz', 'N18E088.txt', 'N18E088.osm.xz.bak',
                                'notes_N18E088.osm.xz', 'N18E088Katyapura.osm.xz',
                                'N18E088_.osm.xz'])         # a label is for people; empty is not one
def test_filename_rejects_the_template_and_lookalikes(fn):
    with pytest.raises(ValueError):
        SquareName.from_filename(fn)


def test_bounds_are_the_degree_from_the_south_west_corner():
    assert SquareName(125, -24).bounds == (125.0, -24.0, 126.0, -23.0)
    assert SquareName(125, -24).contains(125.5, -23.5)
    assert not SquareName(125, -24).contains(126.0, -23.5)   # east edge exclusive
    assert SquareName(125, -24).contains(125.0, -24.0)       # west/south inclusive


def test_neighbours_wrap_in_longitude_and_stop_at_the_poles():
    assert SquareName(179, 0).neighbour(1, 0) == SquareName(-180, 0)
    assert SquareName(-180, 0).neighbour(-1, 0) == SquareName(179, 0)
    assert SquareName(0, 89).neighbour(0, 1) is None
    assert SquareName(0, -90).neighbour(0, -1) is None
    assert SquareName(10, 10).neighbour(-1, 1) == SquareName(9, 11)


# -------------------------------------------------------------- one square

@pytest.fixture(scope='module')
def golden():
    return read_square(GOLDEN)


def test_the_golden_square_reads_whole(golden):
    assert golden.name == SquareName(125, -24)
    assert golden.present and not golden.empty
    assert len(golden.nodes) == 1694
    assert len(golden.ways) == 95
    assert golden.attrs['upload'] == 'never'


def test_contours_are_the_ways_with_an_elevation(golden):
    contours = list(golden.contours())
    assert len(contours) == 94                  # one way is the frame, no ele
    assert all(w.ele is not None for w in contours)
    eles = golden.elevations()
    assert len(eles) == 22
    assert eles == sorted(eles)
    assert 101.0 in eles


def test_the_nodes_fill_the_square_the_file_names_and_little_more(golden):
    """Not 'every node is inside': 52 of the 1694 here are up to 300 m west of
    the degree line, because a mapper drawing a contour to the edge overshoots
    into the neighbour and JOSM keeps what was drawn. That is data, and a
    viewer shows it. What the filename does guarantee is that the square is
    where the nodes are - so the extent is the degree, give or take that
    overshoot, and nothing is a degree away."""
    w, s, e, n = golden.bounds
    lons = [nd.lon for nd in golden.nodes.values()]
    lats = [nd.lat for nd in golden.nodes.values()]
    slack = 0.01                                   # about a kilometre
    assert w - slack <= min(lons) and max(lons) <= e + slack
    assert s - slack <= min(lats) and max(lats) <= n + slack
    # and it really does fill the degree rather than sitting in a corner of it
    assert max(lons) - min(lons) > 0.9 and max(lats) - min(lats) > 0.9
    outside = [nd for nd in golden.nodes.values()
               if not (w <= nd.lon <= e and s <= nd.lat <= n)]
    assert 0 < len(outside) < 100                  # some, and not many


def test_every_ref_resolves_and_coords_follow_the_refs(golden):
    for way in golden.ways.values():
        assert all(r in golden.nodes for r in way.refs)
        assert len(golden.coords(way)) == len(way.refs)


def test_ids_are_negative_because_nothing_here_is_on_the_live_map(golden):
    assert all(i < 0 for i in golden.nodes)
    assert all(i < 0 for i in golden.ways)


def test_an_uncompressed_drop_reads_the_same(golden, tmp_path):
    loose = tmp_path / 'S24E125_Los_Pizarrales.osm'
    loose.write_bytes(lzma.open(GOLDEN, 'rb').read())
    again = read_square(loose)
    assert len(again.nodes) == len(golden.nodes)
    assert again.elevations() == golden.elevations()


def test_a_missing_ref_is_skipped_not_raised(tmp_path):
    p = tmp_path / 'N00E000.osm'
    p.write_text("<osm version='0.6' upload='never'>"
                 "<node id='-1' lat='0.5' lon='0.5'/>"
                 "<way id='-9'><nd ref='-1'/><nd ref='-2'/><tag k='ele' v='10'/></way>"
                 "</osm>")
    sq = read_square(p)
    assert sq.coords(sq.ways[-9]) == [(0.5, 0.5)]


@pytest.mark.parametrize('v,want', [('101', 101.0), (' 12.5 ', 12.5), ('-3', -3.0),
                                    ('', None), ('ten', None), (None, None)])
def test_parse_ele(v, want):
    assert parse_ele(v) == want


def test_a_way_with_a_bad_ele_is_kept_but_is_not_a_contour():
    from danu.core.square import Way
    w = Way(id=-1, refs=[], tags={'ele': 'approx 100'})
    assert w.ele is None
    sq = Square(name=SquareName(0, 0), present=True, ways={-1: w})
    assert list(sq.contours()) == []
    assert -1 in sq.ways


# ------------------------------------------------------------ working set

@pytest.fixture
def zone(tmp_path):
    """A zone with the golden square, a blank neighbour, the EMPTY template,
    and nothing else - so a 3x3 around the golden square has one drawn, one
    blank, and seven absent."""
    from danu.core.make_square import write_square
    shutil.copy(GOLDEN, tmp_path / GOLDEN.name)
    write_square(tmp_path / 'S24E126.osm.xz', 126, -24, 'frame')
    with lzma.open(tmp_path / 'EMPTY.osm.xz', 'wt') as f:
        f.write("<osm version='0.6' upload='never'></osm>")
    return tmp_path


def test_list_squares_ignores_the_template(zone):
    found = list_squares(zone)
    assert set(found) == {SquareName(125, -24), SquareName(126, -24)}


def test_two_files_for_one_square_is_an_error(zone):
    shutil.copy(GOLDEN, zone / 'S24E125_Other_Label.osm.xz')
    with pytest.raises(FileExistsError):
        list_squares(zone)


def test_a_working_set_is_a_full_grid_absent_squares_included(zone):
    ws = WorkingSet.open(zone, SquareName(125, -24))
    assert ws.size == 3 and len(ws.squares) == 9
    present = {s.name for s in ws.present()}
    assert present == {SquareName(125, -24), SquareName(126, -24)}
    absent = [s for s in ws.squares.values() if not s.present]
    assert len(absent) == 7 and all(s.empty for s in absent)
    assert ws.bounds == (124.0, -25.0, 127.0, -22.0)


def test_a_blank_square_is_present_but_has_no_contours(zone):
    ws = WorkingSet.open(zone, SquareName(125, -24))
    blank = ws.squares[SquareName(126, -24)]
    assert blank.present and not blank.empty
    assert list(blank.contours()) == []


def test_working_set_contours_and_range_come_from_the_drawn_squares(zone):
    ws = WorkingSet.open(zone, SquareName(125, -24))
    assert len(list(ws.contours())) == 94
    lo, hi = ws.elevation_range()
    assert lo == 101.0 and hi == max(ws.elevations())
    assert ws.at(125.5, -23.5).name == SquareName(125, -24)
    assert ws.at(124.5, -23.5).present is False
    assert ws.at(130.0, 0.0) is None


@pytest.mark.parametrize('size', [0, 2, 4, -1])
def test_working_set_size_must_be_odd(zone, size):
    with pytest.raises(ValueError):
        WorkingSet.open(zone, SquareName(125, -24), size)


def test_working_set_of_one_and_five(zone):
    assert len(WorkingSet.open(zone, SquareName(125, -24), 1).squares) == 1
    assert len(WorkingSet.open(zone, SquareName(125, -24), 5).squares) == 25


def test_working_set_at_a_pole_is_short_not_broken(zone):
    ws = WorkingSet.open(zone, SquareName(0, 89))
    assert len(ws.squares) == 6           # the row north of 89 does not exist
    assert ws.bounds[1:4:2] == (88.0, 90.0)
    ws = WorkingSet.open(zone, SquareName(0, -90))
    assert len(ws.squares) == 6           # and nothing south of -90 either
    assert ws.bounds[1:4:2] == (-90.0, -88.0)


def test_working_set_across_the_antimeridian_is_one_box_that_holds_its_members(zone):
    """The first version asserted the width, which was the one property never
    at risk; the box was 178..181 and the -180 square was outside it. Now:
    every member's square, moved onto the box's axis, lies inside, and the box
    is continuous rather than spanning the world."""
    ws = WorkingSet.open(zone, SquareName(179, 0))
    assert SquareName(-180, 0) in ws.squares
    w, s, e, n = ws.bounds
    assert (w, e) == (178.0, 181.0)
    for sq in ws.squares.values():
        sw, ss, se, sn = sq.bounds
        lo = ws.unwrap(sw)
        assert w <= lo and lo + 1 <= e, f'{sq.name} at {lo} outside {w}..{e}'
    # the point test agrees with membership, on either spelling of the longitude
    assert ws.contains(-179.5, 0.5) and ws.contains(180.5, 0.5)
    assert ws.at(-179.5, 0.5).name == SquareName(-180, 0)
    assert ws.at(180.5, 0.5).name == SquareName(-180, 0)     # the other spelling
    assert ws.at(-181.5, 0.5).name == SquareName(178, 0)
    assert not ws.contains(-178.5, 0.5)        # 181.5, one east of the box
    assert not ws.contains(177.5, 0.5)


def test_working_set_contains_matches_membership_away_from_the_seam(zone):
    ws = WorkingSet.open(zone, SquareName(125, -24))
    assert ws.contains(124.0, -25.0) and not ws.contains(127.0, -25.0)
    assert ws.contains(126.9, -22.1) and not ws.contains(126.9, -22.0)
    assert ws.unwrap(125.0) == 125.0


def test_a_square_is_read_by_what_it_is_not_by_what_it_is_called(tmp_path):
    """A compressed square under a bare .osm name used to be scanned as text:
    has_constraints found no ele in the compressed bytes, called it a blank
    template, and the square was dropped from the build with nothing said.
    That is the silent-loss failure this pipeline keeps meeting, and the first
    six bytes of the file close it."""
    from danu.core.square import Node, SquareName, Way, has_constraints, read_square, write_square

    square = Square(name=SquareName(125, -24), present=True)
    square.nodes[-1] = Node(id=-1, lat=-23.5, lon=125.5)
    square.nodes[-2] = Node(id=-2, lat=-23.6, lon=125.6)
    square.ways[-1] = Way(id=-1, refs=[-1, -2], tags={'ele': '100'})

    packed = write_square(square, tmp_path / 'S24E125.osm.xz')
    bare = write_square(square, tmp_path / 'S24E125.osm')
    assert packed.read_bytes()[:6] == b'\xfd7zXZ\x00' and bare.read_bytes()[:1] == b'<'
    assert has_constraints(str(packed)) and has_constraints(str(bare))

    # the same bytes under the other name, which is what the suffix test got wrong
    misnamed = tmp_path / 'S24E125_misnamed.osm'
    misnamed.write_bytes(packed.read_bytes())
    assert has_constraints(str(misnamed)), 'a compressed square read as text again'
    assert read_square(misnamed).elevations() == [100]

    # and an uncompressed square under an .xz name, the other way round
    other = tmp_path / 'S24E125_other.osm.xz'
    other.write_bytes(bare.read_bytes())
    assert has_constraints(str(other))
    assert read_square(other).elevations() == [100]


def test_writing_a_square_keeps_the_order_its_ways_were_in(tmp_path):
    """gdal_rasterize burns the contours in layer order and the last one to
    touch a cell wins it, so where two contours of different elevations meet
    the same cell the order in the file decides the constraint - and the first
    pass fills from it.

    write_square used to sort by id, on the belief that JOSM writes them
    sorted. JOSM mostly does; where it does not - a block of ids from a later
    session sitting among an older run - sorting reordered the ways. Reading
    gobras' N20E087_Artana and writing it back unchanged moved 4,155 cells by
    up to 650 m, and 99 of the 806 drawn squares on the server are ordered so
    that a save would have done it.

    This asserts the ordering only. That the surface follows from it is
    asserted in tests/golden/test_editor_surface.py, which needs GDAL and
    isofill to build one."""
    from danu.core.square import Node, SquareName, Way, read_square, write_square

    square = Square(name=SquareName(125, -24), present=True)
    # the shape JOSM leaves: a descending run with a later block dropped into
    # the middle of it, which is what an edit in a second session produces
    order = [-100, -101, -102, -500, -501, -103, -104]
    for i, wid in enumerate(order):
        a, b = wid * 10, wid * 10 - 1
        square.nodes[a] = Node(id=a, lat=-23.5 + i * 0.01, lon=125.5)
        square.nodes[b] = Node(id=b, lat=-23.5 + i * 0.01, lon=125.6)
        square.ways[wid] = Way(id=wid, refs=[a, b], tags={'ele': str(100 + i)})
    assert list(square.ways) != sorted(square.ways, reverse=True), 'the fixture must be unsorted'

    back = read_square(write_square(square, tmp_path / 'S24E125.osm.xz'))
    assert list(back.ways) == order, 'the ways came back in a different order'
    assert list(back.nodes) == list(square.nodes), 'the nodes came back in a different order'


def test_the_golden_square_round_trips_in_its_own_order(tmp_path):
    """The same property on a real JOSM file rather than a made-up one.

    This fixture happens to be sorted already, so a round trip is a no-op on it
    and it cannot tell the sorted write from the faithful one. That is why the
    golden test which builds a surface from an editor-written copy of it passed
    throughout. The surface claim is pinned instead by
    tests/golden/test_editor_surface.py, on a square that is not sorted and
    where a cliff puts two elevations in one cell."""
    from danu.core.square import read_square, write_square

    golden = Path(__file__).parent / 'golden' / 'S24E125_Los_Pizarrales.osm.xz'
    original = read_square(golden)
    back = read_square(write_square(original, tmp_path / 'S24E125.osm.xz'))
    assert list(back.ways) == list(original.ways)
    assert list(back.nodes) == list(original.nodes)


def test_an_elevation_that_is_not_finite_is_not_an_elevation():
    """``float`` reads 'inf' and 'nan' back happily, so a square carrying one
    would have an elevation every reader accepts and nothing downstream
    survives: a colour ramp, a ladder, a label and a rasteriser each do
    something different and silent with it."""
    from danu.core.square import parse_ele
    assert parse_ele('inf') is None
    assert parse_ele('-inf') is None
    assert parse_ele('nan') is None
    assert parse_ele('NaN') is None
    assert parse_ele('Infinity') is None
    # and the ordinary cases are untouched
    assert parse_ele('125') == 125.0 and parse_ele(' 12.5 ') == 12.5
    assert parse_ele('tbd') is None and parse_ele(None) is None


# ---------------------------------------------------------- relations

LAKE = """<?xml version='1.0' encoding='UTF-8'?>
<osm version='0.6' upload='never' generator='JOSM'>
  <node id='-1' action='modify' lat='-23.9' lon='125.1' />
  <node id='-2' action='modify' lat='-23.9' lon='125.9' />
  <node id='-3' action='modify' lat='-23.1' lon='125.9' />
  <node id='-4' action='modify' lat='-23.1' lon='125.1' />
  <node id='-5' action='modify' lat='-23.6' lon='125.4' />
  <node id='-6' action='modify' lat='-23.6' lon='125.6' />
  <node id='-7' action='modify' lat='-23.4' lon='125.6' />
  <node id='-8' action='modify' lat='-23.4' lon='125.4' />
  <way id='-20' action='modify'>
    <nd ref='-1' /><nd ref='-2' /><nd ref='-3' /><nd ref='-4' /><nd ref='-1' />
    <tag k='natural' v='water' />
  </way>
  <way id='-21' action='modify'>
    <nd ref='-5' /><nd ref='-6' /><nd ref='-7' /><nd ref='-8' /><nd ref='-5' />
  </way>
  <relation id='-30' action='modify'>
    <member type='way' ref='-20' role='outer' />
    <member type='way' ref='-21' role='inner' />
    <member type='node' ref='-5' />
    <tag k='type' v='multipolygon' />
    <tag k='natural' v='water' />
    <tag k='ele' v='120' />
  </relation>
</osm>
"""


@pytest.fixture
def lake(tmp_path):
    """A lake with an island in it - R41's reason for relations existing at
    all. The island is an inner ring, and there is no way to say so without
    one."""
    path = tmp_path / 'S24E125_Lake.osm'
    path.write_text(LAKE)
    return path


def test_a_relation_is_read_with_its_members_in_order(lake):
    from danu.core.square import read_square

    sq = read_square(lake)
    assert list(sq.relations) == [-30]
    rel = sq.relations[-30]
    assert [(m.type, m.ref, m.role) for m in rel.members] == [
        ('way', -20, 'outer'), ('way', -21, 'inner'), ('node', -5, '')]
    assert rel.tags['type'] == 'multipolygon'
    assert rel.ele == 120.0


def test_a_square_with_a_relation_round_trips(lake, tmp_path):
    """The property ``write_square`` already holds for nodes and ways: a square
    opened and saved differs from the one that was opened only where it was
    edited. Members keep their order and their roles, and a role that is empty
    stays absent rather than becoming an empty string in the file."""
    from danu.core.square import read_square, write_square

    original = read_square(lake)
    written = write_square(original, tmp_path / 'S24E125_Out.osm')
    back = read_square(written)

    assert list(back.relations) == list(original.relations)
    assert list(back.ways) == list(original.ways)
    assert list(back.nodes) == list(original.nodes)
    a, b = original.relations[-30], back.relations[-30]
    assert [(m.type, m.ref, m.role) for m in a.members] == [(m.type, m.ref, m.role) for m in b.members]
    assert a.tags == b.tags
    text = written.read_text()
    assert "role='outer'" in text and "role='inner'" in text
    assert "role=''" not in text, 'an absent role was written as an empty one'
    # and relations come last, as JOSM writes them and as a member reference
    # wants: a way is in the file before the relation that names it
    assert text.index('<way id=') < text.index('<relation id=')


def test_the_allocator_counts_relations_too(lake):
    """One counter over three namespaces. A square whose lowest id is a
    relation's would otherwise mint one already in use."""
    from danu.core import edits
    from danu.core.square import read_square

    sq = read_square(lake)
    assert min(sq.relations) < min(sq.ways) < min(sq.nodes)
    assert edits.IdAllocator(sq).take() == min(sq.relations) - 1


def test_a_square_with_no_relations_writes_none(golden, tmp_path):
    from danu.core.square import write_square

    assert golden.relations == {}
    text = write_square(golden, tmp_path / 'S24E125_Out.osm').read_text()
    assert '<relation' not in text


def test_a_square_of_nothing_but_water_is_not_a_blank_template(tmp_path):
    """R42. An import can bring a square into being holding nothing but
    rivers, and that is a square somebody has drawn - not one of the blanks
    handed out to mappers.

    It changes less than it looks. A square whose water carries an elevation
    was already caught by the ``ele`` scan; one whose water carries none
    contributes no ground until something gives it one, because ``collect``
    gathers lines with an ``ele`` and nothing else. What this stops is the
    square being read as a template.
    """
    from danu.core.square import has_constraints

    def square(tags, name='S24E125_W.osm'):
        path = tmp_path / name
        path.write_text(
            "<?xml version='1.0'?>\n<osm version='0.6' upload='never'>\n"
            "  <node id='-1' lat='-23.5' lon='125.5' />\n"
            "  <node id='-2' lat='-23.4' lon='125.6' />\n"
            "  <way id='-9'>\n    <nd ref='-1' />\n    <nd ref='-2' />\n"
            + ''.join(f"    <tag k='{k}' v='{v}' />\n" for k, v in tags.items())
            + '  </way>\n</osm>\n')
        return path

    assert has_constraints(str(square({'waterway': 'river'}, 'S24E125_A.osm')))
    assert has_constraints(str(square({'natural': 'water'}, 'S24E125_B.osm')))
    assert has_constraints(str(square({'natural': 'coastline'}, 'S24E125_C.osm')))
    assert has_constraints(str(square({'ele': '125'}, 'S24E125_D.osm')))
    # and still no, for a square of something else entirely
    assert not has_constraints(str(square({'highway': 'track'}, 'S24E125_E.osm')))
    assert not has_constraints(str(square({'natural': 'wood'}, 'S24E125_F.osm')))
    assert not has_constraints(str(square({}, 'S24E125_G.osm')))
    # `v='water'` on its own answers for anything, and must not
    assert not has_constraints(str(square({'landuse': 'water'}, 'S24E125_H.osm')))
    assert not has_constraints(str(square({'name': 'coastline'}, 'S24E125_I.osm')))


def test_the_natural_pair_is_found_whichever_way_round_it_is_written(tmp_path):
    """JOSM writes ``k`` then ``v``, adjacent, and so does ``write_square``.
    This file is read from wherever a mapper got it, and a pair that is
    reversed or has something between would otherwise go unseen - which for a
    water-only square means being read as a blank template."""
    from danu.core.square import has_constraints

    def tag(text, name):
        path = tmp_path / name
        path.write_text(
            "<?xml version='1.0'?>\n<osm version='0.6' upload='never'>\n"
            f"  <way id='-9'>\n    <tag {text} />\n  </way>\n</osm>\n")
        return str(path)

    assert has_constraints(tag("k='natural' v='water'", 'S24E125_P.osm'))
    assert has_constraints(tag("v='water' k='natural'", 'S24E125_Q.osm'))
    assert has_constraints(tag("k='natural' version='3' v='water'", 'S24E125_R.osm'))
    assert has_constraints(tag('k="natural" v="coastline"', 'S24E125_S.osm'))
    # but not across two different tags, which is two different statements
    path = tmp_path / 'S24E125_T.osm'
    path.write_text(
        "<?xml version='1.0'?>\n<osm version='0.6' upload='never'>\n"
        "  <way id='-9'>\n    <tag k='natural' v='wood' />\n"
        "    <tag k='landuse' v='water' />\n  </way>\n</osm>\n")
    assert not has_constraints(str(path))


def test_the_constraint_scan_sees_a_tag_split_across_a_read(tmp_path):
    """``k='natural' v='water'`` is matched as a pair, twenty-one bytes of it,
    where the longest token before was ten. The overlap carries it - and it
    has to be a *rolling* tail rather than the last block's bytes, or a chunk
    smaller than the token leaves the window shorter than the thing being
    looked for and a pair spanning three reads is never whole in any one of
    them. Written with the old ``block[-n:]`` this fails at chunk sizes 8 to
    11 and 15 and passes everywhere else, which is the kind of bug that waits
    for a file of an awkward size."""
    from danu.core.square import has_constraints

    path = tmp_path / 'S24E125_Split.osm'
    path.write_text(
        "<?xml version='1.0'?>\n<osm version='0.6' upload='never'>\n"
        "  <node id='-1' lat='-23.5' lon='125.5' />\n"
        "  <way id='-9'>\n    <nd ref='-1' />\n"
        "    <tag k='natural' v='water' />\n  </way>\n</osm>\n")
    for chunk in range(1, 80):
        assert has_constraints(str(path), chunk=chunk), f'missed at chunk {chunk}'


def test_has_elevation_is_an_ele_anywhere_and_not_water_alone(tmp_path):
    """The squares a build's grid is taken over - G6c. Water with no level on
    it is drawn but holds no ground."""
    from danu.core.square import has_constraints, has_elevation

    def square(body, name):
        path = tmp_path / name
        path.write_text("<?xml version='1.0'?>\n<osm version='0.6' upload='never'>\n"
                        f"{body}</osm>\n")
        return path

    river = ("  <node id='-1' lat='-23.5' lon='125.5' />\n  <node id='-2' lat='-23.4' lon='125.6' />\n"
             "  <way id='-9'><nd ref='-1' /><nd ref='-2' /><tag k='waterway' v='river' /></way>\n")
    water = square(river, 'S24E125_A.osm')
    assert has_constraints(str(water)) and not has_elevation(str(water))
    levelled = square(river.replace("lon='125.5' />", "lon='125.5'><tag k='ele' v='40' /></node>"),
                      'S24E125_B.osm')
    assert has_elevation(str(levelled)), 'a level on a river is an elevation'
    contour = square("  <way id='-9'><tag k=\"ele\" v=\"100\" /></way>\n", 'S24E125_C.osm')
    assert has_elevation(str(contour))
