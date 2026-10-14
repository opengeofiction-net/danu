"""The AppImage in the applications menu (J5c): the entry and the icons,
written, taken out, and following an AppImage that moved."""

import configparser
import re
from pathlib import Path

import pytest

pytest.importorskip('PySide6')

from danu.ui import desktop
from danu.ui import preferences as preferences_module

PACKAGED = Path(__file__).parents[2] / 'packaging' / 'linux' / 'danu.desktop'


def entry() -> dict[str, str]:
    cp = configparser.RawConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(desktop.entry_path(), encoding='utf-8')
    return dict(cp['Desktop Entry'])


def exec_argv(value: str) -> list[str]:
    """An Exec value read as the spec reads it: the string's escapes, then the
    quoting, then a doubled % - one quoted argument here."""
    s = re.sub(r'\\(.)', lambda m: {'s': ' ', 'n': '\n', 't': '\t', 'r': '\r'}.get(m[1], m[1]), value)
    assert s.startswith('"') and s.endswith('"'), value
    return [re.sub(r'\\([\\"`$])', r'\1', s[1:-1]).replace('%%', '%')]


@pytest.fixture
def image(tmp_path, monkeypatch):
    path = tmp_path / 'apps' / 'Danu-0.2.0-x86_64.AppImage'
    path.parent.mkdir()
    path.write_bytes(b'')
    monkeypatch.setenv('APPIMAGE', str(path))
    return path


def test_only_an_appimage_is_offered_it(image, monkeypatch):
    assert desktop.appimage() == image
    monkeypatch.delenv('APPIMAGE')
    assert desktop.appimage() is None


def test_the_entry_is_the_packaged_one_running_the_appimage(image):
    desktop.install(image)
    assert desktop.entry_path() == Path(desktop.data_home()) / 'applications' / 'danu.desktop'
    got = entry()
    cp = configparser.RawConfigParser(interpolation=None)
    cp.optionxform = str
    cp.read(PACKAGED, encoding='utf-8')
    packaged = dict(cp['Desktop Entry'])
    assert packaged.pop('Exec') == 'danu'
    assert {k: got[k] for k in packaged} == packaged
    assert exec_argv(got['Exec']) == [str(image)]
    assert got['TryExec'] == str(image) and got[desktop.MARK] == str(image)
    assert desktop.installed() == image


def test_the_icon_at_every_size_danu_ships(image):
    desktop.install(image)
    sizes = sorted(int(p.stem.split('-')[1]) for p in desktop.ICONS.glob('danu-*.png'))
    assert sizes == [16, 24, 32, 48, 64, 128, 256]
    for n in sizes:
        got = desktop.data_home() / 'icons' / 'hicolor' / f'{n}x{n}' / 'apps' / 'danu.png'
        assert got.read_bytes() == (desktop.ICONS / f'danu-{n}.png').read_bytes()


@pytest.mark.parametrize('name', ['with space.AppImage', 'a$HOME`x`.AppImage', 'quote"d.AppImage',
                                  'back\\slash.AppImage', 'per%cent.AppImage'])
def test_a_path_the_shell_or_the_file_would_misread_is_quoted(tmp_path, name):
    path = tmp_path / name
    desktop.install(path)
    got = entry()
    assert exec_argv(got['Exec']) == [str(path)]
    assert desktop.installed() == path


def test_removed_with_its_icons(image):
    desktop.install(image)
    desktop.remove()
    assert not desktop.entry_path().exists()
    assert not list((desktop.data_home() / 'icons').rglob('danu.png'))
    assert desktop.installed() is None


def test_an_entry_danu_did_not_write_is_left_alone(image):
    mine = '[Desktop Entry]\nType=Application\nName=Danu\nExec=/opt/danu/run\n'
    desktop.entry_path().parent.mkdir(parents=True)
    desktop.entry_path().write_text(mine)
    assert desktop.installed() is None
    desktop.remove()
    assert not desktop.follow(image)
    assert desktop.entry_path().read_text() == mine


def test_an_appimage_moved_takes_the_entry_over(image, tmp_path):
    desktop.install(image)
    moved = tmp_path / 'Danu-0.3.0-x86_64.AppImage'
    assert not desktop.follow(moved), 'taken from an AppImage still there'
    assert desktop.installed() == image
    image.unlink()
    assert desktop.follow(moved)
    assert desktop.installed() == moved
    assert not desktop.follow(None)


def test_no_entry_is_not_made_by_following(image):
    assert not desktop.follow(image)
    assert not desktop.entry_path().exists()


# ---------------------------------------------------------------- the window
def preferences_with(monkeypatch, check: bool | None):
    """Preferences, OK'd with the menu's box as ``check`` has it."""
    def run(dlg):
        if check is not None:
            dlg.menu.setChecked(check)
        dlg.accept()
        return dlg.result()
    monkeypatch.setattr(preferences_module.PreferencesDialog, 'exec', run)


def test_the_preferences_have_no_menu_box_but_in_an_appimage(window, monkeypatch, tmp_path):
    seen = []
    monkeypatch.setattr(preferences_module.PreferencesDialog, 'exec',
                        lambda dlg: seen.append(dlg.menu) or 0)
    window.preferences()
    assert seen == [None]


def test_the_preferences_add_it_and_take_it_out(window, image, monkeypatch):
    preferences_with(monkeypatch, True)
    assert window.preferences()
    assert desktop.installed() == image
    assert window.settings.menu_offered, 'the start page would ask again'
    preferences_with(monkeypatch, False)
    assert window.preferences()
    assert desktop.installed() is None


def test_a_menu_that_cannot_be_written_is_said(window, image, monkeypatch):
    said = []
    monkeypatch.setattr('danu.ui.app.QMessageBox.warning', lambda *a: said.append(a[2]))
    desktop.data_home().mkdir(parents=True)
    (desktop.data_home() / 'applications').write_text('a file where the directory goes')
    assert not window.set_menu_entry(True)
    assert said and 'could not be changed' in said[0]
