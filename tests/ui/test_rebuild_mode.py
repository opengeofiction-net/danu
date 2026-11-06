"""Surface › Rebuild (#239, then three ways). Auto: each edit goes to the
preview and the set is rebuilt once the drawing stops. Local: each edit goes
to the preview and the rebuild waits for Ctrl+R. Manual: the surface is left
as it is until Ctrl+R. Back to auto, what was edited meanwhile is rebuilt."""

import pytest

pytest.importorskip('PySide6')

from danu.ui.settings import Settings

from .conftest import menu


def held(job) -> None:
    """A build started and never run."""


def modes_menu(window):
    # by the conftest helper, not QAction.menu(): PySide6 6.8 loses the menu
    # with the action's wrapper
    return menu(menu(window.menuBar(), 'Surface'), 'Rebuild')


def test_it_is_auto_until_changed_and_the_choice_is_kept(window):
    acts = window.rebuild_mode_actions
    assert list(acts) == ['auto', 'local', 'manual']
    assert set(modes_menu(window).actions()) == set(acts.values())
    assert acts['auto'].isChecked() and window.settings.rebuild_mode == 'auto'
    radios = window.surface_panel.rebuild_modes
    assert [b.text() for b in radios.values()] == ['auto', 'local', 'manual']
    assert radios['auto'].isChecked()
    acts['local'].trigger()
    assert window.settings.rebuild_mode == 'local' and radios['local'].isChecked(), 'the panel follows the menu'
    assert not acts['auto'].isChecked(), 'one at a time'
    radios['manual'].setChecked(True)
    assert acts['manual'].isChecked() and window.settings.rebuild_mode == 'manual', 'and the menu the panel'
    assert window.settings.q.value('surface/rebuild_mode') == 'manual'


@pytest.mark.parametrize('old, mode', [(True, 'auto'), (False, 'manual'), (None, 'auto')])
def test_the_old_on_or_off_is_read_as_auto_or_manual(tmp_path, old, mode):
    s = Settings(tmp_path / 'danu.ini')
    if old is not None:
        s.q.setValue('surface/auto_rebuild', old)
    assert s.rebuild_mode == mode
    s.rebuild_mode = 'local'
    assert Settings(tmp_path / 'danu.ini').rebuild_mode == 'local', 'the new setting wins once written'
    with pytest.raises(ValueError):
        s.rebuild_mode = 'sometimes'


def test_manual_an_edit_reaches_no_preview_and_the_status_line_says_so(window, monkeypatch):
    window.builder._runner = held
    assert window.rebuild_surface()
    seen = []
    monkeypatch.setattr(window.preview, 'edited', lambda *a: seen.append(a))
    sq = next(iter(window.working_set.squares.values()))
    window._edited_ways(sq, {1}, ())
    assert len(seen) == 1, 'auto, the preview is told'
    window.set_rebuild_mode('manual')
    assert not window.preview._idle.isActive(), 'the wait for the drawing to stop is dropped'
    window._edited_ways(sq, {1}, ())
    window._edited_ways(sq, {2}, ())
    assert len(seen) == 1, 'manual, the preview is not'
    assert window._surface_out_of_date
    assert 'out of date' in window.statusBar().currentMessage()
    window.statusBar().showMessage('something else')
    window._edited_ways(sq, {3}, ())
    assert window.statusBar().currentMessage() == 'something else', 'said once, not at every edit'


def test_local_previews_each_edit_and_leaves_the_rebuild_to_ctrl_r(window, monkeypatch):
    window.builder._runner = held
    assert window.rebuild_surface()
    window.set_rebuild_mode('local')
    seen = []
    monkeypatch.setattr(window.preview, 'edited', lambda *a: seen.append(a))
    sq = next(iter(window.working_set.squares.values()))
    window.statusBar().showMessage('quiet')
    window._edited_ways(sq, {1}, ())
    assert len(seen) == 1, 'local, the preview is told'
    assert window.statusBar().currentMessage() == 'quiet', 'the preview says it, not an out-of-date line'
    assert window._surface_out_of_date, 'a preview is not the exact surface'
    asked = []
    window.rebuild_surface = lambda arcsec=None, why='': asked.append(why)
    window.editor.history.dirty_squares = lambda: {'S': object()}
    window._rebuild_after_idle()
    assert asked == [], 'local, the drawing stopping is no rebuild'
    assert 'for exact' in window._settles()
    window.set_rebuild_mode('auto')
    assert asked == ['auto on'], 'back to auto, what the previews approximated is rebuilt'
    asked.clear()
    window._rebuild_after_idle()
    assert asked == ['idle']
    assert window._settles() == 'exact on idle'


def test_ctrl_r_brings_it_up_to_date_and_auto_again_rebuilds_what_was_edited(window):
    window.builder._runner = held
    assert window.rebuild_surface()
    window.set_rebuild_mode('manual')
    sq = next(iter(window.working_set.squares.values()))
    window._edited_ways(sq, {1}, ())
    assert window._surface_out_of_date
    window.rebuild_action.trigger()
    assert not window._surface_out_of_date
    window._edited_ways(sq, {1}, ())
    asked = []
    window.rebuild_surface = lambda arcsec=None, why='': asked.append(arcsec)
    window.set_rebuild_mode('auto')
    assert asked == [window._arcsec], 'auto again, out of date: rebuilt'
    asked.clear()
    window.set_rebuild_mode('local')
    window.set_rebuild_mode('auto')
    assert asked == [window._arcsec], 'still out of date, so again'
    asked.clear()
    window.set_rebuild_mode('auto')
    assert asked == [], 'choosing the mode it is in does nothing'


def test_a_failed_build_leaves_it_out_of_date(window, monkeypatch):
    window.builder._runner = held
    assert window.rebuild_surface()
    window.set_rebuild_mode('manual')
    monkeypatch.setattr('danu.ui.app.QMessageBox.warning', lambda *a: None)
    window.editor.history.dirty_squares = lambda: {'S': object()}
    assert window.rebuild_surface() and not window._surface_out_of_date
    window._surface_failed('no GDAL')
    assert window._surface_out_of_date


@pytest.mark.parametrize('mode', ['local', 'manual'])
def test_with_nothing_built_says_nothing(window, mode):
    window.set_rebuild_mode(mode)
    sq = next(iter(window.working_set.squares.values()))
    window.statusBar().showMessage('quiet')
    window._edited_ways(sq, {1}, ())
    assert not window._surface_out_of_date and window.statusBar().currentMessage() == 'quiet'
