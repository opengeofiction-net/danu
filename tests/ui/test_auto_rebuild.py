"""Surface › Rebuild automatically (#239): on, each edit goes to the preview
and the set is rebuilt once the drawing stops; off, the surface is left as it
is until Ctrl+R, and turning it on again rebuilds what was edited meanwhile."""

import pytest

pytest.importorskip('PySide6')


def held(job) -> None:
    """A build started and never run."""


def test_it_is_on_until_turned_off_and_the_choice_is_kept(window):
    a = window.auto_rebuild_action
    assert a.isCheckable() and a.isChecked() and window.settings.auto_rebuild
    assert a in window.menuBar().actions()[[m.text() for m in window.menuBar().actions()].index('&Surface')].menu().actions()
    box = window.surface_panel.auto
    assert box.text() == 'auto' and box.isChecked()
    a.setChecked(False)
    assert window.settings.auto_rebuild is False and not box.isChecked(), 'the panel follows the menu'
    box.setChecked(True)
    assert a.isChecked() and window.settings.auto_rebuild, 'and the menu the panel'
    box.setChecked(False)
    assert window.settings.q.value('surface/auto_rebuild') in (False, 'false')


def test_off_an_edit_reaches_no_preview_and_the_status_line_says_so(window, monkeypatch):
    window.builder._runner = held
    assert window.rebuild_surface()
    seen = []
    monkeypatch.setattr(window.preview, 'edited', lambda *a: seen.append(a))
    sq = next(iter(window.working_set.squares.values()))
    window._edited_ways(sq, {1}, ())
    assert len(seen) == 1, 'on, the preview is told'
    window.auto_rebuild_action.setChecked(False)
    assert not window.preview._idle.isActive(), 'the wait for the drawing to stop is dropped'
    window._edited_ways(sq, {1}, ())
    window._edited_ways(sq, {2}, ())
    assert len(seen) == 1, 'off, the preview is not'
    assert window._surface_out_of_date
    assert 'out of date' in window.statusBar().currentMessage()
    window.statusBar().showMessage('something else')
    window._edited_ways(sq, {3}, ())
    assert window.statusBar().currentMessage() == 'something else', 'said once, not at every edit'


def test_ctrl_r_brings_it_up_to_date_and_turning_it_on_rebuilds_what_was_edited(window):
    window.builder._runner = held
    assert window.rebuild_surface()
    window.auto_rebuild_action.setChecked(False)
    sq = next(iter(window.working_set.squares.values()))
    window._edited_ways(sq, {1}, ())
    assert window._surface_out_of_date
    window.rebuild_action.trigger()
    assert not window._surface_out_of_date
    window._edited_ways(sq, {1}, ())
    asked = []
    window.rebuild_surface = lambda arcsec=None: asked.append(arcsec)
    window.auto_rebuild_action.setChecked(True)
    assert asked == [window._arcsec], 'on again, out of date: rebuilt'
    asked.clear()
    window.auto_rebuild_action.setChecked(False)
    window.auto_rebuild_action.setChecked(True)
    assert asked == [window._arcsec], 'still out of date, so again'


def test_a_failed_build_leaves_it_out_of_date(window, monkeypatch):
    window.builder._runner = held
    assert window.rebuild_surface()
    window.auto_rebuild_action.setChecked(False)
    monkeypatch.setattr('danu.ui.app.QMessageBox.warning', lambda *a: None)
    window.editor.history.dirty_squares = lambda: {'S': object()}
    assert window.rebuild_surface() and not window._surface_out_of_date
    window._surface_failed('no GDAL')
    assert window._surface_out_of_date


def test_off_with_nothing_built_says_nothing(window):
    window.auto_rebuild_action.setChecked(False)
    sq = next(iter(window.working_set.squares.values()))
    window.statusBar().showMessage('quiet')
    window._edited_ways(sq, {1}, ())
    assert not window._surface_out_of_date and window.statusBar().currentMessage() == 'quiet'
