"""A newer release (J7): GitHub asked once a day, the newest release that is
not a draft said in the status line, nothing asked under the Store."""

import json

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QNetworkReply

from danu.ui import preferences as preferences_module
from danu.ui import update
from danu.ui.preferences import PreferencesDialog
from danu.ui.settings import Settings

PAGE = 'https://github.com/opengeofiction-net/danu/releases/tag/'


def release(tag, draft=False, prerelease=False, url=None):
    return {'tag_name': tag, 'draft': draft, 'prerelease': prerelease, 'html_url': url or PAGE + tag}


class Reply(QObject):
    finished = Signal()

    def __init__(self, body: bytes = b'', error=QNetworkReply.NetworkError.NoError):
        super().__init__()
        self.body, self._error = body, error

    def error(self):
        return self._error

    def readAll(self):
        return self.body


class Clock:
    def __init__(self, t=1_800_000_000.0):
        self.t = t

    def __call__(self):
        return self.t


@pytest.fixture
def settings(tmp_path):
    return Settings(tmp_path / 'danu.ini')


def checker(settings, answer, clock=None):
    """An UpdateCheck whose GitHub gives ``answer`` - a list of releases, a
    Reply, or bytes - and the requests it was asked."""
    u = update.UpdateCheck(settings, now=clock or Clock())
    u.asked, u.said = [], []
    u.found.connect(lambda t, url: u.said.append((t, url)))

    def send(req):
        u.asked.append(req.url().toString())
        r = answer if isinstance(answer, Reply) else Reply(
            answer if isinstance(answer, bytes) else json.dumps(answer).encode())
        return r
    u._send = send
    return u


def answered(u):
    u.reply.finished.emit()


def test_versions_compare_as_releases_do():
    order = ['0.2.0', 'v0.2.1', 'v0.3.0a1', 'v0.3.0b2', '0.3.0rc1', 'v0.3.0', 'v0.10.0', 'v1.0.0']
    assert sorted(order, key=update.parse) == order
    assert update.parse('latest') is None and update.parse('v0.3') is None
    assert update.is_newer('v0.2.1', '0.2.0') and not update.is_newer('v0.2.0', '0.2.0')
    assert not update.is_newer('nightly', '0.2.0')


def test_the_newest_not_a_draft_prereleases_and_all():
    got = update.newest([release('v0.2.0', prerelease=True), release('v0.4.0', draft=True),
                         release('v0.3.0', prerelease=True), release('v0.9.0', url='https://example.com/x'),
                         release('banana'), 'not a dict'])
    assert got == ('v0.3.0', PAGE + 'v0.3.0')
    assert update.newest([]) is None


def test_a_newer_release_is_said_and_kept(settings):
    u = checker(settings, [release('v0.2.0'), release('v99.0.0')])
    assert u.start()
    assert u.asked == [update.RELEASES]
    answered(u)
    assert u.said == [('v99.0.0', PAGE + 'v99.0.0')]
    assert settings.update_latest == ('v99.0.0', PAGE + 'v99.0.0')
    assert settings.update_checked == u.now()


def test_asked_once_a_day_and_said_from_what_was_kept(settings):
    clock = Clock()
    first = checker(settings, [release('v99.0.0')], clock)
    first.start()
    answered(first)
    clock.t += update.DAY - 60
    again = checker(settings, [release('v99.0.1')], clock)
    assert not again.start(), 'asked twice in a day'
    assert again.said == [('v99.0.0', PAGE + 'v99.0.0')]
    clock.t += 120
    later = checker(settings, [release('v99.0.0')], clock)
    assert later.start()
    answered(later)
    assert later.said == [('v99.0.0', PAGE + 'v99.0.0')], 'said once, not again when GitHub agrees'


def test_this_release_or_older_says_nothing(settings):
    u = checker(settings, [release('v0.1.0'), release(f'v{update.__version__}')])
    u.start()
    answered(u)
    assert u.said == []
    assert settings.update_latest[0] == f'v{update.__version__}'


def test_a_release_installed_since_says_nothing(settings):
    settings.update_latest = ('v0.0.1', PAGE + 'v0.0.1')
    settings.update_checked = Clock()()
    u = checker(settings, [])
    assert not u.start()
    assert u.said == []


@pytest.mark.parametrize('answer', [Reply(b'', QNetworkReply.NetworkError.HostNotFoundError), b'<html>',
                                    b'\xff\xfe'])
def test_no_answer_asks_again_at_the_next_start(settings, answer):
    u = checker(settings, answer)
    assert u.start()
    answered(u)
    assert u.said == [] and settings.update_checked == 0
    assert checker(settings, []).start()


def test_turned_off_it_neither_asks_nor_says(settings):
    settings.update_latest = ('v99.0.0', PAGE + 'v99.0.0')
    settings.update_check = False
    u = checker(settings, [release('v99.0.0')])
    assert not u.start()
    assert u.asked == [] and u.said == []


def test_installed_from_the_store_it_never_asks(settings, monkeypatch):
    monkeypatch.setattr(update, 'from_store', lambda: True)
    settings.update_latest = ('v99.0.0', PAGE + 'v99.0.0')
    u = checker(settings, [release('v99.0.0')])
    assert not u.start()
    assert u.asked == [] and u.said == []


def test_off_windows_nothing_is_the_store():
    assert update.from_store() is False or update.sys.platform == 'win32'


# ---------------------------------------------------------------- the window
def test_the_status_line_links_to_it(window):
    assert not window.newer.isVisibleTo(window)
    window.show_newer('v99.0.0', PAGE + 'v99.0.0')
    assert window.newer.isVisibleTo(window)
    assert 'Danu 99.0.0 is out' in window.newer.text()
    assert f'href="{PAGE}v99.0.0"' in window.newer.text()
    assert window.newer.openExternalLinks()


def test_the_preferences_turn_it_off(window, monkeypatch):
    window.show_newer('v99.0.0', PAGE + 'v99.0.0')

    def run(dlg):
        assert dlg.update_check.isChecked()
        dlg.update_check.setChecked(False)
        dlg.accept()
        return dlg.result()
    monkeypatch.setattr(PreferencesDialog, 'exec', run)
    assert window.preferences()
    assert window.settings.update_check is False
    assert not window.newer.isVisibleTo(window)
    assert Settings(window.settings.q.fileName()).update_check is False

    def on(dlg):
        dlg.update_check.setChecked(True)
        dlg.accept()
        return dlg.result()
    window.settings.update_latest = ('v99.0.0', PAGE + 'v99.0.0')
    monkeypatch.setattr(PreferencesDialog, 'exec', on)
    assert window.preferences()
    assert window.newer.isVisibleTo(window) and 'Danu 99.0.0 is out' in window.newer.text()


def test_the_store_has_no_box_for_it(window, monkeypatch):
    monkeypatch.setattr(preferences_module.update, 'from_store', lambda: True)
    dlg = PreferencesDialog(window.settings, window.action_labels(), window)
    assert dlg.update_check is None
    dlg.accept()
    assert window.settings.update_check is True
