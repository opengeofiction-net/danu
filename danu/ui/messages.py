"""What Qt says on the terminal, and what is worth saying.

Qt's network stack reports conditions a mapper cannot act on and we do not
cause. Two arrive in quantity while tiles are fetched::

    QIODevice::read (QSslSocket): device not open
    qt.network.http2: stream 21 error: "Received GOAWAY"
    qt.network.http2: stream 21 finished with error: "Remote host signaled shutdown"

GOAWAY is how a server says a connection has had its fill of requests; Qt
logs one per stream, and a session of panning brings dozens. Neither is ours
to answer - the socket is read inside Qt, and the shutdown is the server's -
and together they bury the messages that are ours, and GDAL's.

Turning HTTP/2 off would end the GOAWAY reports by ending HTTP/2. Measured
against tile.opengeofiction.net, 48 tiles at zoom 13: 0.92 s and 2.44 s over
HTTP/2, 2.28 s and 3.51 s over HTTP/1.1. A canvas asks for thirty tiles at
once, so the multiplexing is worth having and the reports are filtered
instead. It does not quieten the socket message, which is emitted either way
- measured over five runs each.

Nothing is filtered silently: whatever is filtered is counted and the count
reported as the application exits, and ``DANU_QT_MESSAGES=all`` leaves Qt's
own handler in place, which reports nothing because it filters nothing.

What is not filtered is printed as Qt prints it - measured: Qt's handler gives
a plain message for the default category and ``category: message`` for a named
one, so a line pasted into a bug report reads the same either way.
"""

from __future__ import annotations

import atexit
import os
import sys

from PySide6.QtCore import QtMsgType, qInstallMessageHandler

# matched anywhere in the text, whatever the category
NOISE = (
    'QIODevice::read (QSslSocket): device not open',
)
# and these categories, but only for what they say about a connection ending.
# The wording is Qt's own, as it appeared in the review's terminal; a future
# Qt saying it differently means one line through, not a line lost
NOISY = {
    'qt.network.http2': ('GOAWAY', 'signaled shutdown'),
}

suppressed = 0


def is_noise(category: str, text: str) -> bool:
    if any(n in text for n in NOISE):
        return True
    return any(m in text for m in NOISY.get(category, ()))


def _report():
    if suppressed:
        print(f'danu: {suppressed} Qt network message(s) not shown'
              ' - DANU_QT_MESSAGES=all to see them', file=sys.stderr)


def install() -> bool:
    """Filter the known chatter unless asked not to. True if installed."""
    if os.environ.get('DANU_QT_MESSAGES') == 'all':
        return False

    def handler(mode: QtMsgType, context, message: str):
        global suppressed
        category = getattr(context, 'category', '') or ''
        if is_noise(category, message):
            suppressed += 1
            return
        # as Qt formats it: bare for the default category, prefixed for a named one
        where = f'{category}: ' if category and category != 'default' else ''
        print(f'{where}{message}', file=sys.stderr)

    qInstallMessageHandler(handler)
    atexit.register(_report)
    return True
