"""The garbage collector on the main thread only (danu.ui.collector): a cycle
made and dropped on a pool worker is freed on the main thread, between
events - never on the worker, where a Qt object freed under the window's
painter is a segfault. Young cycles at each tick past the threshold; old ones
in a full collection, once enough young ones have run and the mapper has
been idle."""

import gc
import threading

import pytest

pytest.importorskip('PySide6')

from danu.ui import collector as C


class Cycle:
    freed_on: list = []

    def __init__(self):
        self.me = self

    def __del__(self):
        Cycle.freed_on.append(threading.current_thread() is threading.main_thread())


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


@pytest.fixture
def made(qapp):
    gc.collect()
    Cycle.freed_on = []
    clock = Clock()
    c = C.MainThreadCollector(qapp, interval_ms=10_000, clock=clock)    # ticked by hand
    yield c, clock
    c.stop()
    qapp.removeEventFilter(c)


def test_it_turns_automatic_collection_off_and_back_on(qapp):
    assert gc.isenabled()
    c = C.MainThreadCollector(None, interval_ms=10_000)
    assert not gc.isenabled()
    c.stop()
    assert gc.isenabled()


def test_a_cycle_dropped_on_a_worker_is_freed_on_the_main_thread(made):
    c, _ = made
    # past the threshold as the collector counts - allocations less frees,
    # so what lives on: with automatic collection on, it would run here, on
    # the worker, and free the cycles there
    n = 2 * c.threshold

    def work():
        for _ in range(n):
            Cycle()

    t = threading.Thread(target=work)
    t.start()
    t.join()
    assert Cycle.freed_on == [], 'collected on the worker'
    assert c.tick() >= n
    assert len(Cycle.freed_on) == n and all(Cycle.freed_on), 'not all freed, or not on the main thread'


def test_a_tick_under_the_threshold_does_nothing(made):
    c, _ = made
    gc.collect()
    assert c.tick() == 0 and c.young == 0


def test_old_cycles_wait_for_a_full_collection_and_the_mapper_idle(made, qapp):
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    c, clock = made
    old = [Cycle() for _ in range(500)]
    gc.collect(0)                       # survived a young collection: old
    del old
    c.young = C.FULL_AFTER              # a full collection due
    clock.t += 1
    move = QMouseEvent(QEvent.Type.MouseMove, QPointF(1, 1), QPointF(1, 1),
                       Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    c.eventFilter(None, move)           # the mapper just moved the mouse
    c.tick()
    assert Cycle.freed_on == [] and c.young == C.FULL_AFTER, 'collected in full mid-stroke'
    clock.t += C.IDLE_S
    c.tick()
    assert len(Cycle.freed_on) == 500 and all(Cycle.freed_on) and c.young == 0
