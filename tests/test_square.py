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
from hypothesis import given, strategies as st

from danu.core.square import (SquareName, Square, WorkingSet, list_squares,
                              parse_ele, read_square)

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
                                'notes_N18E088.osm.xz', 'N18E088Katyapura.osm.xz'])
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
    assert ws.bounds[3] == 90.0


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
