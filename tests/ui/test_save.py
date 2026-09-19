"""Save, save as, a new blank square, the close prompt, and the advice line."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QEvent, QPointF, Qt                       # noqa: E402
from PySide6.QtGui import QMouseEvent                                # noqa: E402
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from danu.core import edits, save                                    # noqa: E402
from danu.core.square import SquareName, read_square                 # noqa: E402

from .conftest import cursor_to                                      # noqa: E402

TEN = SquareName(126, -24)
BLANK = SquareName(125, -23)


def draw_into(w, square, ele, lon, lat):
    """An edit through the history, as the tools would make it."""
    alloc = w.editor.history.alloc(square)
    cmd = edits.AddWay(alloc.take(), [alloc.take(), alloc.take()], [(lon, lat), (lon + 0.1, lat)], {'ele': str(ele)})
    w.editor.do(square, cmd)


def test_save_writes_every_dirty_square_and_clears_the_star(window, zone):
    w = window
    ws = w.working_set
    ten, gold = ws.squares[TEN], ws.squares[SquareName(125, -24)]
    draw_into(w, ten, 60, 126.2, -23.45)
    draw_into(w, gold, 999, 125.2, -23.45)
    assert w.windowTitle().endswith('*') and len(w.editor.history.dirty_squares()) == 2
    w.save_action.trigger()
    assert not w.windowTitle().endswith('*') and not w.editor.dirty()
    assert 60 in read_square(zone / 'S24E126_Tenmetre.osm.xz').elevations()
    assert 999 in read_square(zone / 'S24E125_Los_Pizarrales.osm.xz').elevations()
    msg = w.statusBar().currentMessage()
    assert 'saved S24E126_Tenmetre.osm.xz' in msg and 'saved S24E125_Los_Pizarrales.osm.xz' in msg
    w.save_action.trigger()
    assert w.statusBar().currentMessage() == 'nothing to save'


def test_a_square_drawn_from_blank_asks_where_and_gets_a_frame(window, zone, monkeypatch):
    w = window
    blank = w.working_set.squares[BLANK]
    assert not blank.present
    draw_into(w, blank, 20, 125.3, -22.5)
    asked = []
    monkeypatch.setattr(QFileDialog, 'getSaveFileName',
                        staticmethod(lambda *a, **k: (asked.append(a[2]) or str(zone / 'S23E125.osm.xz'), '')))
    assert w.save_all()
    assert asked == [str(zone / 'S23E125.osm.xz')]           # the default offered: <zone>/<NAME>.osm.xz
    assert blank.present and blank.path == zone / 'S23E125.osm.xz' and save.has_frame(blank)
    again = read_square(zone / 'S23E125.osm.xz')
    assert save.has_frame(again) and again.elevations() == [20]
    assert 'with a frame' in w.statusBar().currentMessage()
    # declined: nothing written, still dirty, and a close would be stopped
    draw_into(w, blank, 30, 125.3, -22.4)
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', staticmethod(lambda *a, **k: ('', '')))
    w.save_as_action.setEnabled(True)
    assert w.editor.dirty()
    # save as goes to the square under the cursor
    cursor_to(w, 125.5, -22.5)
    before = (zone / 'S23E125.osm.xz').read_bytes()
    w.save_as()
    assert w.editor.dirty() and (zone / 'S23E125.osm.xz').read_bytes() == before   # declined: nothing written


def test_a_new_blank_square_is_written_with_a_frame_and_the_set_re_read(window, zone, monkeypatch, qtbot):
    w = window
    monkeypatch.setattr(QInputDialog, 'getText', staticmethod(lambda *a, **k: ('S23E126', True)))
    with qtbot.waitSignal(w.loader.finished, timeout=15000):
        w.new_blank_square()
    qtbot.waitUntil(lambda: w.working_set.squares[SquareName(126, -23)].present, timeout=5000)
    sq = read_square(zone / 'S23E126.osm.xz')
    assert save.has_frame(sq) and not list(sq.contours())
    # asking again for one that exists is refused
    warned = []
    monkeypatch.setattr(QMessageBox, 'warning', staticmethod(lambda *a, **k: warned.append(a[2])))
    w.new_blank_square()
    assert warned and 'already exists' in warned[0]
    # and with unsaved edits it will not re-read the set from under them
    draw_into(w, w.working_set.squares[TEN], 60, 126.2, -23.45)
    w.new_blank_square()
    assert 'save first' in w.statusBar().currentMessage()


def test_closing_dirty_asks_and_cancel_keeps_the_window(window, monkeypatch):
    w = window
    w.prompt_on_close = True
    draw_into(w, w.working_set.squares[TEN], 60, 126.2, -23.45)
    answers = [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save]
    monkeypatch.setattr(QMessageBox, 'question', staticmethod(lambda *a, **k: answers.pop(0)))
    assert not w.close() and w.isVisible()                     # cancelled
    assert w.close()                                           # saved, then closed
    assert not w.editor.dirty()


def test_the_advice_line_names_off_ladder_values_after_an_edit(window):
    w = window
    ten = w.working_set.squares[TEN]
    cursor_to(w, 126.5, -23.5)
    assert w.elevation_panel.advice.text() == ''
    draw_into(w, ten, 23, 126.2, -23.45)                       # a 23 among 10, 20, 30, 40, 50
    assert '23 m used once between 20 and 30' in w.elevation_panel.advice.text()
    w.editor.undo()
    assert w.elevation_panel.advice.text() == ''
