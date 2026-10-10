"""A square's unsaved edits as a change file, and the store that keeps them
(H4): the change put onto the file gives back the square as it was in
memory, order and all, and a change against a file that has moved on is
refused."""

import os
from xml.etree import ElementTree

import pytest

from danu.core import autosave, edits, save
from danu.core.change import ApplyChange, change_of, change_text, read_change
from danu.core.square import Member, Relation, Square, SquareName, read_square

NAME = SquareName(126, -24)


def frozen(sq):
    return (tuple((i, n.lat, n.lon, tuple(n.tags.items())) for i, n in sq.nodes.items()),
            tuple((i, tuple(w.refs), tuple(w.tags.items())) for i, w in sq.ways.items()),
            tuple((i, tuple(r.members), tuple(r.tags.items())) for i, r in sq.relations.items()))


@pytest.fixture
def saved(tmp_path):
    """Five contours east-west and a lake relation over the first, saved."""
    sq = Square(name=NAME)
    hist = edits.SetUndoStack()
    alloc = hist.alloc(sq)
    for k in range(5):
        lat = -23.9 + 0.1 * k
        hist.do(sq, edits.AddWay(alloc.take(), [alloc.take() for _ in range(4)],
                                 [(126.1 + 0.2 * j, lat) for j in range(4)], {'ele': str(10 * (k + 1))}))
    first = next(iter(sq.ways))
    rid = alloc.take()
    hist.do(sq, edits.ImportWater(('natural',), new_relations={
        rid: Relation(rid, [Member('way', first, 'outer')], {'type': 'multipolygon', 'natural': 'water'})}))
    path = tmp_path / 'zone' / 'S24E126.osm.xz'
    path.parent.mkdir()
    save.save_square(sq, hist, path)
    return sq, hist, path


def put_back(sq, hist, path):
    """The file read again and the change put on it, through its text."""
    c = change_of(sq, hist.journal(sq))
    again = read_square(path)
    ApplyChange(read_change(change_text(c), c.tail)).apply(again)
    return c, again


def test_nothing_done_is_no_change(saved):
    sq, hist, _ = saved
    c = change_of(sq, hist.journal(sq))
    assert c.empty and c.describe() == 'nothing'


def test_edits_put_back_onto_the_file_are_the_square_in_its_order(saved):
    sq, hist, path = saved
    alloc = hist.alloc(sq)
    ways = list(sq.ways)
    w0, w2 = sq.ways[ways[1]], sq.ways[ways[3]]
    hist.do(sq, edits.MoveNode(w0.refs[1], (126.3, -23.8), (126.31, -23.79)))
    hist.do(sq, edits.ExtendWay(w2.id, True, alloc.take(), (126.9, -23.6)))
    # a way replaced goes to the end of the square: the order the build burns in
    hist.do(sq, edits.ReplaceWay(ways[2], [(ways[2], list(sq.ways[ways[2]].refs[:3]))], {}))
    hist.do(sq, edits.DeleteWay(ways[4]))
    hist.do(sq, edits.AddNode(alloc.take(), (126.5, -23.55), {'ele': '44', 'natural': 'peak'}))
    rel = next(iter(sq.relations))
    hist.do(sq, edits.SetRelationTags(rel, dict(sq.relations[rel].tags), {**sq.relations[rel].tags, 'ele': '9'}))
    assert list(sq.ways)[-1] == ways[2], 'the premise: a replaced way ends the square'
    c, again = put_back(sq, hist, path)
    assert frozen(again) == frozen(sq)
    # made: the node the way was extended by, the spot height; changed: the node
    # moved, the way extended, the way reshaped, the lake's tags; gone: the way
    # deleted and its four nodes, and the node the reshaped way let go
    assert c.counts() == {'create': 2, 'modify': 4, 'delete': 6}, c.counts()
    assert ways[4] in c.delete['way'] and c.tail['way'] == [ways[2]]


def test_made_and_unmade_since_the_save_is_nothing(saved):
    sq, hist, _ = saved
    alloc = hist.alloc(sq)
    hist.do(sq, edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(126.2, -23.2), (126.3, -23.2)],
                             {'ele': '70'}))
    hist.do(sq, edits.DeleteWay(min(sq.ways)))
    assert change_of(sq, hist.journal(sq)).empty


def test_undone_past_the_save_is_put_back_too(saved):
    """Saved, then edits made before the save undone: the file has them,
    the square does not."""
    sq, hist, path = saved
    hist.undo()                                       # the frame the save put on
    hist.undo()                                       # the lake relation
    assert not sq.relations and not save.has_frame(sq)
    c, again = put_back(sq, hist, path)
    assert frozen(again) == frozen(sq) and len(c.delete['relation']) == 1 and len(c.delete['node']) == 4


def test_a_reshape_undone_past_the_save_gives_back_the_nodes_it_let_go(saved, tmp_path):
    """The nodes an undo puts back are named by the command only before the
    undo empties its record of them."""
    sq, hist, path = saved
    ways = list(sq.ways)
    hist.do(sq, edits.ReplaceWay(ways[1], [(ways[1], list(sq.ways[ways[1]].refs[:2]))], {}))
    save.save_square(sq, hist, path)
    hist.undo()
    c, again = put_back(sq, hist, path)
    assert len(c.create['node']) == 2 and frozen(again) == frozen(sq)


def test_an_edit_made_while_the_file_was_written_stays_in_the_change(saved):
    sq, hist, path = saved
    alloc = hist.alloc(sq)
    pending = save.prepare(sq, hist, path)
    nid = alloc.take()
    hist.do(sq, edits.AddNode(nid, (126.4, -23.4), {'ele': '50'}))     # during the write
    save.write(pending)
    save.finish(pending, hist)
    assert hist.dirty(sq)
    c, again = put_back(sq, hist, path)
    assert nid in c.create['node'] and frozen(again) == frozen(sq)


def test_the_change_is_an_osm_change_file(saved):
    sq, hist, _ = saved
    hist.do(sq, edits.MoveNode(next(iter(sq.nodes)), (0, 0), (126.0001, -23.00001)))
    hist.do(sq, edits.DeleteWay(min(sq.ways)))                  # the frame, and its corners
    root = ElementTree.fromstring(change_text(change_of(sq, hist.journal(sq))))
    assert root.tag == 'osmChange' and root.get('version') == '0.6'
    assert [b.tag for b in root] == ['modify', 'delete']
    assert root.find('modify/node').get('lat') == '-23.00001', 'a plain decimal, as the squares are written'
    deleted = [e.tag for e in root.find('delete')]
    assert deleted.index('way') < deleted.index('node'), 'a way goes before the nodes it names'


def test_a_recovery_is_one_step_taken_back_in_the_files_order(saved):
    sq, hist, path = saved
    ways = list(sq.ways)
    hist.do(sq, edits.ReplaceWay(ways[0], [(ways[0], list(sq.ways[ways[0]].refs[:2]))], {}))
    c = change_of(sq, hist.journal(sq))
    again = read_square(path)
    before = frozen(again)
    h2 = edits.SetUndoStack()
    h2.do(again, ApplyChange(c))
    assert frozen(again) == frozen(sq) and h2.dirty(again)
    h2.undo()
    assert frozen(again)[1:] == before[1:], 'the ways and relations back in the order the file has them'
    assert dict.fromkeys(frozen(again)[0]) == dict.fromkeys(before[0])


# ---------------------------------------------------------------- store

def test_held_until_saved_and_refused_once_the_file_moves_on(saved, tmp_path):
    sq, hist, path = saved
    store = autosave.Store(tmp_path / 'data')
    hist.do(sq, edits.MoveNode(next(iter(sq.nodes)), (0, 0), (126.2, -23.2)))
    store.write(path.parent, sq, change_of(sq, hist.journal(sq)))
    (e,) = store.entries()
    assert e.square == NAME and e.file == path.resolve() and e.refused() is None
    assert e.data['counts']['modify'] == 1
    again = read_square(path)
    ApplyChange(e.change()).apply(again)
    assert frozen(again) == frozen(sq)
    os.utime(path, ns=(1, 1))                         # somebody else saved over it
    assert 'has changed since' in e.refused()
    store.remove(path.parent, NAME)
    assert store.entries() == [] and not list((tmp_path / 'data').rglob('*.osc'))


def test_a_kill_between_the_two_writes_leaves_the_last_whole(saved, tmp_path, monkeypatch):
    sq, hist, path = saved
    store = autosave.Store(tmp_path / 'data')
    hist.do(sq, edits.MoveNode(next(iter(sq.nodes)), (0, 0), (126.2, -23.2)))
    store.write(path.parent, sq, change_of(sq, hist.journal(sq)))
    hist.do(sq, edits.DeleteWay(max(sq.ways)))
    real = autosave._replace

    def killed(p, text):
        if p.suffix == '.json':
            raise KeyboardInterrupt                     # the manifest never lands
        real(p, text)
    monkeypatch.setattr(autosave, '_replace', killed)
    with pytest.raises(KeyboardInterrupt):
        store.write(path.parent, sq, change_of(sq, hist.journal(sq)))
    (e,) = store.entries()
    assert e.data['seq'] == 1 and e.change().counts()['delete'] == 0, 'the first, whole'


def test_a_square_with_no_file_is_refused_once_one_is_made(tmp_path):
    zone = tmp_path / 'zone'
    zone.mkdir()
    sq = Square(name=NAME)
    hist = edits.SetUndoStack()
    alloc = hist.alloc(sq)
    hist.do(sq, edits.AddNode(alloc.take(), (126.5, -23.5), {'ele': '5'}))
    store = autosave.Store(tmp_path / 'data')
    store.write(zone, sq, change_of(sq, hist.journal(sq)))
    (e,) = store.entries(zone)
    assert e.file is None and e.refused() is None
    fresh = Square(name=NAME)
    ApplyChange(e.change()).apply(fresh)
    assert frozen(fresh) == frozen(sq)
    from danu.core import make_square
    make_square.write_square(zone / 'S24E126.osm.xz', 126, -24, save.FRAME_NOTE)
    assert 'made since' in e.refused()


def test_set_aside_rather_than_deleted(saved, tmp_path):
    sq, hist, path = saved
    store = autosave.Store(tmp_path / 'data')
    hist.do(sq, edits.MoveNode(next(iter(sq.nodes)), (0, 0), (126.2, -23.2)))
    (e,) = [store.write(path.parent, sq, change_of(sq, hist.journal(sq)))]
    to = store.set_aside(e)
    assert to.exists() and to.suffix == '.osc' and store.entries() == []


def test_two_zones_of_one_name_are_kept_apart(tmp_path):
    a, b = tmp_path / 'a' / 'gobras', tmp_path / 'b' / 'gobras'
    assert autosave.zone_key(a) != autosave.zone_key(b) and autosave.zone_key(a).startswith('gobras-')
