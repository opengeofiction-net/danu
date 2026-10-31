"""The status bar's three parts, a line between each: what was said, its
last three the tooltip; whose ground, with whether it is yours to upload as
a mark; and the cursor's reading."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtWidgets import QFrame


def test_what_was_said_keeps_its_last_three_newest_first(window):
    bar = window.statusBar()
    for text in ('one', 'two', 'two', 'three & more', 'four'):
        bar.showMessage(text)
    bar.clearMessage()
    tip = bar.toolTip()
    assert tip == '<p>four</p><p>three &amp; more</p><p>two</p>', 'repeats once, cleared not kept, escaped'


def test_a_line_between_each_part(window):
    bar = window.statusBar()
    lines = [f for f in bar.findChildren(QFrame) if f.frameShape() == QFrame.Shape.VLine]
    shown = [f for f in lines if f.isVisibleTo(window)]
    assert len(shown) == 2, 'before the territory and before the cursor reading'
    x = lambda wd: wd.mapTo(window, wd.rect().topLeft()).x()  # noqa: E731
    first, second = sorted(shown, key=x)
    assert x(first) < x(window._territory) < x(window._drop) < x(second) < x(window._status)
    window.show_newer('v99.0.0', 'https://example/releases/v99.0.0')
    assert sum(f.isVisibleTo(window) for f in lines) == 3, 'and before a newer release, when there is one'


def test_the_cursor_reading_says_what_it_shows(window):
    assert 'zoom' in window._status.toolTip() and 'latitude' in window._status.toolTip()
