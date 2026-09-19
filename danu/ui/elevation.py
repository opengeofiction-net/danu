"""The active elevation, on screen - R14 and the spec's *Elevation control*.

Three redundant controls over one ``danu.core.ladder.Elevation``: the keys,
the wheel, and a notched slider. The slider's notches are the ladder of the
square under the cursor - inferred from that square, or its override, or the
zone's default - and the panel names the square it is reading, because
crossing into a neighbour re-notches and doing that silently would be worse
than the inconvenience. The value itself does not move when the ladder does.

``ElevationControl`` is the model side: it owns the Elevation, keeps the
ladder in step with the cursor's square, loads the overrides file, and offers
the moves the menu's actions call. ``ElevationPanel`` is the dock that shows
it. Nothing here draws a contour: the layer is told the active level so it
can draw that one heavier, and asked what lies under the cursor for pick-up.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (QDockWidget, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
                               QSlider, QVBoxLayout, QWidget)

from ..core import ladder as L
from ..core.square import Square, WorkingSet
from .settings import Settings

PICK_PX = 8.0                    # how close the cursor must be to pick a contour up


class ElevationControl(QObject):
    """The active elevation and the ladder under the cursor."""

    changed = Signal(float)          # the value, after every move
    ladderChanged = Signal(object)   # the Ladder the slider should show

    def __init__(self, settings: Settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.overrides = L.Overrides.load(settings.ladders_file)
        self.model = L.Elevation(L.regular_ladder(L.DEFAULT_INTERVAL, 0.0, L.DEFAULT_TOP),
                                 small=settings.small_step, big=settings.big_step)
        self.model.listen(lambda v: self.changed.emit(v))
        self.working_set: WorkingSet | None = None
        self.zone: str = ''
        self.square: Square | None = None        # the one the ladder is read from

    # -------------------------------------------------------------- set
    def set_working_set(self, ws: WorkingSet | None, zone: str = ''):
        self.working_set, self.zone, self.square = ws, zone, None
        if ws is not None:
            self.read_square(ws.squares[ws.centre])
        else:
            self._set_ladder(L.regular_ladder(L.DEFAULT_INTERVAL, 0.0, L.DEFAULT_TOP))

    def cursor_at(self, lon: float, lat: float):
        """The cursor moved; if it is over another square, read that one."""
        if self.working_set is None:
            return
        sq = self.working_set.at(lon, lat)
        if sq is not None and sq is not self.square:
            self.read_square(sq)

    def read_square(self, square: Square):
        self.square = square
        self._set_ladder(L.ladder_for(square, self.zone, self.overrides))

    def _set_ladder(self, ladder: L.Ladder):
        self.model.set_ladder(ladder)
        self.ladderChanged.emit(self.model.ladder)

    def reload_overrides(self):
        """The file was edited by hand; read it again and re-notch."""
        self.overrides = L.Overrides.load(self.settings.ladders_file)
        if self.square is not None:
            self.read_square(self.square)

    # ------------------------------------------------------------ moves
    @property
    def value(self) -> float:
        return self.model.value

    @property
    def ladder(self) -> L.Ladder:
        return self.model.ladder

    def set(self, value: float):
        self.model.set(value)

    def step(self, big: bool, down: bool):
        self.model.step(big=big, down=down)

    def nudge(self, down: bool):
        self.model.nudge(down=down)

    def sea_level(self):
        self.model.sea_level()

    def pick_up(self, value: float | None):
        self.model.pick_up(value)

    def set_steps(self, small: float, big: float):
        self.model.small, self.model.big = small, big
        self.settings.small_step, self.settings.big_step = small, big


class ElevationPanel(QDockWidget):
    """The notched slider, the value, the ladder it reads, and the steps."""

    def __init__(self, control: ElevationControl, parent=None):
        super().__init__('Elevation', parent)
        self.setObjectName('elevation')
        self.control = control
        self._notches: tuple[float, ...] = ()
        self._busy = False
        body = QWidget()
        row = QHBoxLayout(body)
        self.slider = QSlider(Qt.Orientation.Vertical)
        self.slider.setTickPosition(QSlider.TickPosition.TicksBothSides)
        self.slider.setTickInterval(1)
        self.slider.setPageStep(1)
        self.slider.setToolTip('the ladder of the square under the cursor')
        row.addWidget(self.slider)
        column = QVBoxLayout()
        form = QFormLayout()
        self.value = QDoubleSpinBox()
        self.value.setRange(-500.0, 9000.0)
        self.value.setDecimals(1)
        self.value.setSuffix(' m')
        self.value.setKeyboardTracking(False)
        self.small = QDoubleSpinBox(); self.small.setRange(0.1, 1000.0); self.small.setDecimals(1); self.small.setSuffix(' m')
        self.big = QDoubleSpinBox(); self.big.setRange(0.1, 5000.0); self.big.setDecimals(1); self.big.setSuffix(' m')
        self.small.setValue(control.model.small); self.big.setValue(control.model.big)
        form.addRow('Active', self.value)
        form.addRow('Small step', self.small)
        form.addRow('Big step', self.big)
        column.addLayout(form)
        self.reading = QLabel('')
        self.reading.setWordWrap(True)
        column.addWidget(self.reading)
        self.keys = QLabel('')
        self.keys.setWordWrap(True)
        self.keys.setStyleSheet('color: gray')
        column.addWidget(self.keys)
        column.addStretch(1)
        row.addLayout(column, 1)
        self.setWidget(body)

        control.changed.connect(self._value_changed)
        control.ladderChanged.connect(self._ladder_changed)
        self.slider.valueChanged.connect(self._slid)
        self.value.valueChanged.connect(self._typed)
        self.small.valueChanged.connect(self._steps)
        self.big.valueChanged.connect(self._steps)
        self.show_keys(control.settings)
        self._ladder_changed(control.ladder)
        self._value_changed(control.value)

    def show_keys(self, settings: Settings):
        k = settings.key
        self.keys.setText(f"{k('elevation.big_up')} / {k('elevation.big_down')} big step, "
                          f"{k('elevation.small_up')} / {k('elevation.small_down')} small, "
                          f"{k('elevation.nudge_up')} / {k('elevation.nudge_down')} a metre, "
                          f"{k('elevation.pick_up')} picks up the contour under the cursor, "
                          f"{k('elevation.sea_level')} sea level. "
                          "Wheel steps, shift-wheel big, ctrl-wheel zooms.")

    # ------------------------------------------------------- from model
    def _ladder_changed(self, ladder: L.Ladder):
        self._notches = ladder.notches
        self._busy = True
        self.slider.setRange(0, len(self._notches) - 1)
        i = ladder.index(self.control.value)
        if i is not None:
            self.slider.setValue(i)
        self._busy = False
        self.reading.setText(ladder.describe())
        self.slider.setToolTip('\n'.join(L.format_ele(n) for n in reversed(self._notches)))

    def _value_changed(self, value: float):
        self._busy = True
        self.value.setValue(value)
        lad = self.control.ladder
        if lad.notches != self._notches:
            # the value walked off the ladder's end; the slider grows to show it
            self._notches = lad.notches
            self.slider.setRange(0, len(self._notches) - 1)
        i = lad.index(value)
        if i is not None:
            self.slider.setValue(i)
        self._busy = False

    # --------------------------------------------------------- from user
    def _slid(self, i: int):
        if not self._busy and 0 <= i < len(self._notches):
            self.control.set(self._notches[i])

    def _typed(self, v: float):
        if not self._busy:
            self.control.set(v)

    def _steps(self, *_):
        self.control.set_steps(self.small.value(), self.big.value())
