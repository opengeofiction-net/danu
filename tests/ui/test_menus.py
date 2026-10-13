"""The menus and panels (H6a): six menus with the water work under Edit's
own sub-menu, a View menu that reopens every panel, and panels that dock and
never float - under Wayland a floating panel cannot be moved again.
"""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDockWidget

from danu.ui import session


def menu(w, title):
    return next(a.menu() for a in w.menuBar().actions() if a.text().replace('&', '') == title)


def texts(m):
    return [a.text().replace('&', '') for a in m.actions() if not a.isSeparator()]


def test_the_menus_are_file_edit_view_elevation_surface_help(window):
    assert [a.text().replace('&', '') for a in window.menuBar().actions()] == \
        ['File', 'Edit', 'View', 'Elevation', 'Surface', 'Help']


def test_the_water_work_has_a_menu_of_its_own(window):
    edit = menu(window, 'Edit')
    assert texts(edit) == ['Undo', 'Redo', 'Delete', 'Delete contour', 'Split', 'Unglue', 'Select',
                           'Draw contour', 'Place spot height', 'Measure', 'Water', 'Spot height',
                           'Coastline', 'Cut out the loop chosen']
    water = next(a.menu() for a in edit.actions() if a.text() == '&Water')
    e = window.edit_actions
    assert water.actions() == [e['edit.import_water'], e['edit.set_level'], e['edit.grade'],
                               e['edit.grade_network'], e['edit.flatten'], e['edit.burn'], e['edit.burn_all']]
    heights = next(a.menu() for a in edit.actions() if a.text() == 'Spot &height')
    assert heights.actions() == [e['edit.import_heights']]
    coastline = next(a.menu() for a in edit.actions() if a.text() == '&Coastline')
    assert coastline.actions() == [e['edit.import_coastline'], e['edit.mark_coastline'], e['edit.reverse_coastline']]


def test_the_surface_in_josm_is_under_surface(window):
    assert window.edit_actions['view.josm_surface'] in menu(window, 'Surface').actions()
    assert window.edit_actions['view.josm_surface'].shortcut().toString() == 'Shift+J'


def test_every_panel_is_in_the_view_menu(window):
    view = menu(window, 'View').actions()
    docks = window.findChildren(QDockWidget)
    assert len(docks) == 6 and all(d.toggleViewAction() in view for d in docks)


def test_a_closed_panel_is_opened_again_from_view(window):
    window.elevation_panel.close()
    assert not window.elevation_panel.isVisible()
    window.elevation_panel.toggleViewAction().trigger()
    assert window.elevation_panel.isVisible()


def test_no_panel_floats(window):
    assert all(not d.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable
               for d in window.findChildren(QDockWidget))


def test_a_layout_with_a_floating_panel_comes_back_docked(window):
    """A session written before H6a may hold one."""
    p = window.surface_panel
    p.setFeatures(p.features() | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
    p.setFloating(True)
    state = window.saveState()
    window.restore_layout(state)
    assert not p.isFloating()
    assert not p.features() & QDockWidget.DockWidgetFeature.DockWidgetFloatable


def test_reset_puts_the_panels_back(window):
    window.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, window.surface_panel)
    window.elevation_panel.close()
    window.profile_dock.show()
    window.view_actions['view.reset_panels'].trigger()
    assert window.dockWidgetArea(window.surface_panel) == Qt.DockWidgetArea.RightDockWidgetArea
    assert window.elevation_panel.isVisible() and not window.profile_dock.isVisible()


def test_a_session_layout_is_restored_docked(window, qtbot, tmp_path):
    p = window.checks_dock
    p.setFeatures(p.features() | QDockWidget.DockWidgetFeature.DockWidgetFloatable)
    p.show()
    p.setFloating(True)
    data = session.capture(window)
    p.setFloating(False)
    session.restore_window(window, data)
    assert not p.isFloating()


@pytest.mark.parametrize('name, box', [('view.unknown', 'show_unreached'), ('view.single_level', 'show_one_level'),
                                       ('view.envelope', 'show_envelope')])
def test_the_view_toggles_are_the_surface_panels_boxes(window, name, box):
    a, b = window.view_actions[name], getattr(window.surface_panel, box)
    window.surface_panel.show_unreached.setChecked(True)
    assert a.isChecked() == b.isChecked()
    a.trigger()
    assert a.isChecked() == b.isChecked()
    b.toggle()
    assert a.isChecked() == b.isChecked()


def test_single_level_ground_waits_on_unknown_ground(window):
    unknown, single = window.view_actions['view.unknown'], window.view_actions['view.single_level']
    unknown.setChecked(False)
    assert not single.isEnabled()
    unknown.setChecked(True)
    assert single.isEnabled()


@pytest.mark.parametrize('name', ['edit.set_level', 'edit.import_heights', 'edit.import_coastline',
                                  'edit.mark_coastline', 'edit.reverse_coastline', 'view.josm_surface'])
def test_a_key_still_reaches_an_action_in_a_sub_menu(window, name):
    fired = []
    a = window.edit_actions[name]
    a.triggered.disconnect()                # what it does: Overpass, JOSM - only that it is reached
    a.triggered.connect(lambda: fired.append(name))
    seq = a.shortcut()[0]
    window.map.setFocus()
    QTest.keyClick(window.map, seq.key(), seq.keyboardModifiers())
    assert fired == [name]
