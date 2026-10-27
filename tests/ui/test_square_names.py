"""A square's name - the one its file gives it, which Send › Rename sets -
shown: in the title bar, under its grid name on the map, and on the zones
map under each held square's."""

import os

import pytest

pytest.importorskip('PySide6')

from PySide6.QtGui import QImage, QPainter

from danu import __version__
from danu.core.square import SquareName
from danu.ui import about
from danu.ui.zones import ZonesItem

SHOT = os.environ.get('DANU_SHOT')        # a path prefix: the renders saved there, to look at


def render(view, name):
    img = QImage(view.viewport().size(), QImage.Format.Format_ARGB32)
    img.fill(0xFFFFFFFF)
    p = QPainter(img)
    view.render(p)
    p.end()
    if SHOT:
        img.save(f'{SHOT}-{name}.png')
    return img


def dark(img) -> int:
    return sum(1 for x in range(0, img.width(), 2) for y in range(0, img.height(), 2)
               if img.pixelColor(x, y).lightness() < 140)


def test_the_title_carries_the_centre_squares_name(window):
    assert window.working_set.squares[SquareName(125, -24)].label == 'Los Pizarrales'
    assert window.windowTitle() == f'Danu {__version__} - S24E125 Los Pizarrales'
    assert about.title('N20E086', True, 'Katyapura') == f'Danu {__version__} - N20E086 Katyapura *'
    assert window.working_set.squares[SquareName(125, -23)].label == '', 'a blank square has no name'


def test_the_map_writes_the_name_under_the_grid_name(window):
    w = window
    w.map.fit_bounds(*SquareName(125, -24).bounds)
    named = render(w.map, 'set')
    assert w.squares.drawn_names >= 1
    # the same, the name taken away: less written
    w.working_set.squares[SquareName(125, -24)].path = None
    plain = render(w.map, 'set-unnamed')
    assert dark(named) > dark(plain)


def test_the_zones_map_names_each_held_square(window):
    w = window
    item = ZonesItem()
    w.map.scene().addItem(item)
    item.set_zones([{'name': 'gobras', 'squares': ['N20E086-N21E087'], 'inactive': None,
                     'held': [{'square': 'N20E086', 'file': 'N20E086_Katyapura_East.osm.xz', 'class': 'contour'},
                              {'square': 'N21E086', 'file': 'N21E086.osm.xz', 'class': 'coastline'}]}])
    assert item.labels[SquareName(86, 20)] == 'Katyapura East' and item.labels[SquareName(86, 21)] == ''
    w.map.fit_bounds(86, 20, 88, 22)
    named = render(w.map, 'zones')
    item.labels.clear()
    assert dark(named) > dark(render(w.map, 'zones-unnamed'))


def test_the_zones_map_draws_what_is_in_view_as_it_draws_it_all(window, monkeypatch):
    """Zones and their squares over a few degrees, the view on a corner of
    one: only the squares in view are drawn, and the picture is the one
    drawn with nothing culled - a zone's name, off its squares, too."""
    from PySide6.QtCore import QRectF

    from danu.ui import mercator as m
    from danu.ui import zones
    w = window
    item = ZonesItem()
    w.map.scene().addItem(item)
    item.set_zones([{'name': name, 'squares': [f'N20E0{lon}-N21E0{lon + 1}'], 'inactive': None,
                     'held': [{'square': f'N2{k}E0{lon + j}', 'file': f'N2{k}E0{lon + j}_{name}.osm.xz', 'class': 'contour'}
                              for j in (0, 1) for k in (0, 1)]}
                    for name, lon in (('west', 80), ('middle', 83), ('east', 86))])
    names = []
    monkeypatch.setattr(zones, 'draw_name', lambda p, r, text, *a: names.append(text))
    w.map.fit_bounds(83.9, 20.9, 84.4, 21.4)
    culled = render(w.map, 'zones-culled')
    assert set(names) == {'N20E083', 'N20E084', 'N21E083', 'N21E084'}, 'the four in view, the others not'
    monkeypatch.setattr(zones, 'visible_rect', lambda *a: QRectF(0, 0, m.WORLD, m.WORLD))
    names.clear()
    assert render(w.map, 'zones-whole') == culled
    assert len(set(names)) == 12
