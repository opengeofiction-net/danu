"""An opt-in trace of how a surface gets to the screen.

Set ``DANU_SURFACE_TRACE`` to a path and every step is appended to it with a
timestamp and a thread. It exists because the reports that matter here are
about a *sequence* - "the new surface disappears when the repaint starts, back
to the original extent" - and neither a screenshot nor a stack trace shows one.

Off unless the variable is set, and a trace that cannot be written does not
stop the editor: a debug hook that can break a session is worse than none.
"""

from __future__ import annotations

import os
import threading
import time

TRACE = os.environ.get('DANU_SURFACE_TRACE')


def trace(what: str, **fields) -> None:
    if not TRACE:
        return
    bits = ' '.join(f'{k}={v}' for k, v in fields.items())
    try:
        with open(TRACE, 'a') as fh:
            fh.write(f'{time.monotonic():12.3f} {threading.current_thread().name:<16} '
                     f'{what:<22} {bits}\n')
    except OSError:
        pass


def grid(shaded) -> str:
    """A surface as one field: its grid and where it sits, which is what tells
    two builds apart at a glance.

    Returns early when the trace is off, because every call site evaluates this
    whether or not anything is listening - and asks for nothing it cannot do
    without. A test's stand-in surface has the arrays and not the geometry, and
    a debug hook that raises on one is worse than no debug hook: written
    without the guards, this broke twenty-eight driver tests.
    """
    if not TRACE:
        return ''
    if shaded is None:
        return 'none'
    shape = getattr(getattr(shaded, 'dem', None), 'shape', None)
    where = getattr(shaded, 'scene_rect', None)
    size = f'{shape[0]}x{shape[1]}' if shape else '?'
    if where is None:
        return size
    left, top, right, bottom = where
    return f'{size}@({left:.0f},{top:.0f},{right - left:.0f},{bottom - top:.0f})'
