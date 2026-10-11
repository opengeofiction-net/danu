"""The Elevation and Surface panels as H6c's review left them: the units
beside the fields, the key help behind an "i", and the surface's overlays
in short words with their explanation in the tooltips."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QLabel


def test_the_elevation_fields_carry_no_unit_and_have_one_beside(window):
    p = window.elevation_panel
    for f in (p.value, p.small, p.big):
        assert f.suffix() == '' and f.parentWidget().unit.text() == 'm'
        assert f.parentWidget().unit.isVisibleTo(p)


def test_the_keys_are_behind_an_i_not_written_out(window):
    p = window.elevation_panel
    tip = p.keys.toolTip()
    assert not p.keys.pixmap().isNull() and not p.keys.text()
    for name in ('elevation.big_up', 'elevation.small_down', 'elevation.pick_up', 'elevation.sea_level'):
        assert window.settings.key(name) in tip
    prose = [lb.text() for lb in p.findChildren(QLabel) if lb.isVisible() and len(lb.text()) > 60]
    assert not prose, prose


def test_the_overlays_are_short_and_explained_on_hover(window):
    p = window.surface_panel
    assert [b.text() for b in (p.show_unreached, p.show_one_level, p.show_envelope)] == \
        ['Unknown ground', 'Single-level ground', 'Envelope']
    assert all(len(b.toolTip()) > 30 for b in (p.show_unreached, p.show_one_level, p.show_envelope))


def test_single_level_ground_is_greyed_without_unknown_ground(window):
    p = window.surface_panel
    p.show_unreached.setChecked(False)
    assert not p.show_one_level.isEnabled()
    p.show_unreached.setChecked(True)
    assert p.show_one_level.isEnabled()


def test_the_surface_panels_josm_button_is_shift_j(window):
    fired = []
    a = window.edit_actions['view.josm_surface']
    a.triggered.disconnect()                    # not JOSM: only that it is reached
    a.triggered.connect(lambda: fired.append(1))
    window.surface_panel.josm_btn.click()
    assert fired == [1]
