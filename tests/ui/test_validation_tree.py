"""The Validation panel as one tree (H6d): a node a check, in a fixed order,
its count in its label and its explanation in its tooltip; a check with
nothing to say greyed, with nothing under it. Over the fixture's working
set, whose golden square holds touches and file findings of its own."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette

from danu.ui.checks_dock import CHECKS


@pytest.fixture
def d(window, qtbot):
    window.checks_dock.toggleViewAction().trigger()
    qtbot.waitUntil(lambda: window.inside_index is not None, timeout=5000)
    return window.checks_dock


def grey(d):
    return d.palette().brush(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text).color()


def test_a_node_a_check_in_order_each_counted(d):
    assert [d.tree.topLevelItem(i) for i in range(d.tree.topLevelItemCount())] == [d.node(k) for k in CHECKS]
    for k, (label, _tip) in CHECKS.items():
        text = d.node(k).text(0)
        assert text.startswith(f'{label} (') and d.node(k).toolTip(0)
        if k not in ('climb', 'backwards', 'sea', 'unreached'):
            assert text == f'{label} ({d.node(k).childCount():,})'


def test_a_check_with_nothing_to_say_is_greyed_and_one_with_rows_is_not(d):
    empty = [k for k in CHECKS if d.node(k).childCount() == 0]
    full = [k for k in CHECKS if d.node(k).childCount()]
    assert empty and full, 'the fixture has some of each'
    assert all(d.node(k).foreground(0).color() == grey(d) for k in empty)
    assert all(d.node(k).foreground(0).color() != grey(d) for k in full)


def test_a_node_is_not_a_row_to_choose(d):
    k = next(k for k in CHECKS if d.node(k).childCount())
    assert not d.node(k).flags() & Qt.ItemFlag.ItemIsSelectable


def test_the_row_chosen_stays_chosen_as_the_checks_follow_an_edit(window, d):
    k = next(k for k in CHECKS if d.node(k).childCount())
    row = d.rows(k)[-1]
    want = row.data(0, Qt.ItemDataRole.UserRole)
    d.tree.setCurrentItem(row)
    window._refresh_checks()
    assert d.tree.currentItem() is not row, 'the rows were not made again'
    assert d.tree.currentItem().data(0, Qt.ItemDataRole.UserRole) == want


def test_a_node_unfolded_stays_unfolded(window, d):
    k = next(k for k in CHECKS if d.node(k).childCount())
    assert not d.node(k).isExpanded()
    d.node(k).setExpanded(True)
    window._refresh_checks()
    assert d.node(k).isExpanded()


def test_cut_out_loop_waits_for_a_loop(d):
    k = next(k for k in CHECKS if d.node(k).childCount() and k != 'loops')
    d.tree.setCurrentItem(d.rows(k)[0])
    assert not d.cut_btn.isEnabled() and d.current_loop() is None
