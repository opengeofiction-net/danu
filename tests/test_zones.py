"""danu.core.zones: the data drop's zones (#190), and danu-build's inactive."""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from danu.core import zones as Z
from danu.core.square import SquareName as S

ZONES = """\
# a comment, kept
gobras         N18E086-N21E089
kofuku         S59E064-S48E079 S47E070   # a note, kept

wrap           N10E179-N11E179 N10W180-N11W179
"""

INACTIVE = """\
# Zones which are built and published but which the renderers should not load.
#
teirolask   wip        # published as zone-mergany, the territory old name.
                       # Recovered 2026-08-22 from its .hgt.
                       #
                       # Not rendered.
deodeca     wip        # 2026-08-24, nothing drawn yet.
urksivo     wip
"""


def test_a_square_is_in_the_one_zone_whose_rectangles_hold_it():
    z = Z.Zones(ZONES)
    assert set(z.zones) == {'gobras', 'kofuku', 'wrap'}
    assert z.zone_of(S.parse('N18E086')) == 'gobras' and z.zone_of(S.parse('N21E089')) == 'gobras'
    assert z.zone_of(S.parse('N22E089')) is None
    assert z.zone_of(S.parse('S47E070')) == 'kofuku', 'a square alone'
    assert z.zone_of(S.parse('S47E071')) is None


def test_across_the_antimeridian_is_a_rectangle_each_side():
    z = Z.Zones(ZONES)
    assert {c.name for c in z.zones['wrap'].cells()} == {
        'N10E179', 'N10W180', 'N10W179', 'N11E179', 'N11W180', 'N11W179'}
    assert z.zone_of(S.parse('N10E178')) is None


def test_zones_never_overlap():
    with pytest.raises(Z.ZoneError, match='overlap at N21E089'):
        Z.Zones('a  N18E086-N21E089\nb  N21E089-N22E090\n')
    z = Z.Zones(ZONES)
    with pytest.raises(Z.ZoneError, match='overlap'):
        z.put('new', ['N20E088-N25E090'])
    assert z.put('gobras', ['N18E086-N22E089']).zone_of(S.parse('N22E089')) == 'gobras', 'a zone may grow over its own'


@pytest.mark.parametrize('text, why', [
    ('Gobras  N18E086\n', 'lowercase'),
    ('gobras\n', 'no squares'),
    ('gobras  N18E086\ngobras  N30E086\n', 'again'),
    ('gobras  N21E086-N18E089\n', 'south of'),
    ('gobras  N18E086-X\n', 'not a rectangle'),
    ('gobras  N18E089-N21E086\n', 'west of'),
    ('gobras  N18E086-\n', 'no square after'),
])
def test_a_bad_line_is_refused_saying_why(text, why):
    with pytest.raises(Z.ZoneError, match=why):
        Z.Zones(text)


def test_put_changes_one_line_and_keeps_the_rest_and_its_note():
    z = Z.Zones(ZONES)
    k = z.put('kofuku', ['S59E064-S47E079'])
    assert k.text == ZONES.replace('S59E064-S48E079 S47E070   # a note, kept', 'S59E064-S47E079   # a note, kept'), \
        'the line keeps its spacing'
    n = z.put('newzone', ['n40e010'])
    assert n.text == ZONES + 'newzone         N40E010\n' and n.zone_of(S.parse('N40E010')) == 'newzone'
    with pytest.raises(Z.ZoneError):
        z.put('Bad', ['N40E010'])
    with pytest.raises(Z.ZoneError):
        z.put('empty', [])


def test_seed_draws_a_rectangle_round_each_zones_squares(tmp_path):
    for zone, files in {'gobras': ['N18E088_Katyapura.osm.xz', 'N21E086_Havreg.osm.xz', 'EMPTY.osm.xz'],
                        'trent': ['S01W145_lon-145.00_-144.00lat-1.00_0.00_local-source.osm.xz'],
                        'sangria': ['N20E066.osm.xz']}.items():
        (tmp_path / zone).mkdir()
        for f in files:
            (tmp_path / zone / f).write_bytes(b'')
    told = []
    z = Z.seed(tmp_path, report=told.append)
    assert told == ['trent: no square file, so no zone - a label with a dot is not read']
    assert {n: [str(r) for r in v.rects] for n, v in z.zones.items()} == {
        'gobras': ['N18E086-N21E088'], 'sangria': ['N20E066']}, 'trent: no square a name the drop takes'
    (tmp_path / 'other').mkdir()
    (tmp_path / 'other' / 'N20E087.osm.xz').write_bytes(b'')
    with pytest.raises(Z.ZoneError, match='overlap'):
        Z.seed(tmp_path)


def test_inactive_is_read_and_left_as_it_is():
    i = Z.Inactive(INACTIVE)
    assert i.reasons() == {'teirolask': 'wip', 'deodeca': 'wip', 'urksivo': 'wip'}
    assert i.text == INACTIVE


def test_clearing_takes_the_entry_and_its_comments_and_nothing_else():
    assert Z.Inactive(INACTIVE).clear('teirolask').text == INACTIVE.replace(
        INACTIVE[INACTIVE.index('teirolask'):INACTIVE.index('deodeca')], '')
    assert Z.Inactive(INACTIVE).clear('urksivo').text == INACTIVE.replace('urksivo     wip\n', '')
    assert Z.Inactive(INACTIVE).clear('gobras').text == INACTIVE
    with pytest.raises(Z.ZoneError):
        Z.Inactive(INACTIVE).clear('# a comment')


def test_setting_adds_an_entry_or_changes_its_reason_in_place():
    i = Z.Inactive(INACTIVE)
    assert i.set('gobras', 'quality', 'squares to fix').text == INACTIVE + 'gobras      quality    # squares to fix\n'
    assert i.set('a-longer-zone-name', 'wip').lines[-1] == 'a-longer-zone-name wip'
    t = i.set('teirolask', 'duplicate').text
    assert t == INACTIVE.replace('teirolask   wip        #', 'teirolask   duplicate  #'), 'note and comments kept'
    assert i.set('deodeca', 'withdrawn', 'gone').lines[6] == 'deodeca     withdrawn  # gone'
    assert i.set('deodeca', 'wip').text == INACTIVE, 'the same reason: the file as it was'
    assert i.set('urksivo', 'quality').lines[-1] == 'urksivo     quality'
    assert i.set('urksivo', 'quality', 'see #12').lines[-1] == 'urksivo     quality    # see #12'
    with pytest.raises(Z.ZoneError, match='one of'):
        i.set('gobras', 'bored')
    with pytest.raises(Z.ZoneError, match='one line'):
        i.set('gobras', 'wip', 'two\nlines')


def test_the_reasons_are_danu_builds():
    from pathlib import Path
    build = (Path(__file__).parents[1] / 'server' / 'bin' / 'danu-build').read_text()
    m = re.search(r'^INACTIVE_REASONS="([a-z ]+)"$', build, re.MULTILINE)
    assert m, 'INACTIVE_REASONS="..." in danu-build'
    assert tuple(m.group(1).split()) == Z.REASONS


def test_a_file_not_there_is_empty(tmp_path):
    assert Z.Zones.read(tmp_path / 'zones').zones == {} and Z.Inactive.read(tmp_path / 'inactive').text == ''


# ------------------------------------------------------------------ squares as rectangles (N6)


@given(st.sets(st.tuples(st.integers(-4, 4), st.integers(-3, 3)), min_size=1, max_size=40))
def test_rects_for_covers_exactly_the_squares_without_overlap(pairs):
    cells = {S(lon, lat) for lon, lat in pairs}
    rects = Z.rects_for(cells)
    seen = [c for r in rects for c in r.cells()]
    assert set(seen) == cells and len(seen) == len(cells), 'every square once'


def test_rects_for_a_block_is_one_and_a_shape_is_few():
    block = {S(lon, lat) for lon in range(86, 90) for lat in range(18, 22)}
    assert [str(r) for r in Z.rects_for(block)] == ['N18E086-N21E089']
    ell = block | {S(90, 18), S(91, 18)}
    assert [str(r) for r in Z.rects_for(ell)] == ['N18E086-N18E091', 'N19E086-N21E089']
    across = {S(179, 10), S(-180, 10)}
    assert sorted(str(r) for r in Z.rects_for(across)) == ['N10E179', 'N10W180'], 'a rectangle each side'
