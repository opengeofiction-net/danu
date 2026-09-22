"""The terminal's contents: Qt's network chatter out, everything else in."""

import pytest

pytest.importorskip('PySide6')
from PySide6.QtCore import QLoggingCategory, qCritical, qInstallMessageHandler, qWarning   # noqa: E402

from danu.ui import messages                                          # noqa: E402


@pytest.mark.parametrize('category,text,noise', [
    ('', 'QIODevice::read (QSslSocket): device not open', True),
    ('default', 'QIODevice::read (QSslSocket): device not open', True),
    ('qt.network.http2', 'stream 21 error: "Received GOAWAY"', True),
    ('qt.network.http2', 'stream 21 finished with error: "Remote host signaled shutdown"', True),
    ('qt.network.http2', 'something nobody has seen before', False),   # the category is not blanket
    ('qt.network.ssl', 'certificate verify failed', False),            # a real network fault stays
    ('', 'QPainter::begin: Paint device returned engine == 0', False),
    ('default', 'the surface could not be built', False),
])
def test_what_counts_as_chatter(category, text, noise):
    assert messages.is_noise(category, text) is noise


def test_the_handler_drops_the_chatter_counts_it_and_passes_the_rest(qapp, capsys, monkeypatch):
    monkeypatch.delenv('DANU_QT_MESSAGES', raising=False)
    monkeypatch.setattr(messages, 'suppressed', 0)
    try:
        assert messages.install()
        qWarning('QIODevice::read (QSslSocket): device not open')
        qWarning('something a mapper can act on')
        qCritical('the surface could not be built')
        err = capsys.readouterr().err
        assert 'QSslSocket' not in err
        assert 'something a mapper can act on' in err and 'the surface could not be built' in err
        assert messages.suppressed == 1
    finally:
        qInstallMessageHandler(None)


def test_asking_for_everything_leaves_qt_alone(monkeypatch):
    monkeypatch.setenv('DANU_QT_MESSAGES', 'all')
    assert messages.install() is False
