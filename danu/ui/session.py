"""The session - H4b: Danu reopened as it was left.

``~/.local/share/danu/session.json``, beside the autosave: the working set,
the view on it, the window with its panels where they were and which are
open, the layer under the map, the surface panel's choices and whether a
surface was built, the tool, the loupe and the active elevation. Written as
the map comes to rest and as any of those is chosen, as well as on closing,
so a Danu killed reopens where it was too; read when Danu starts with no
square named. A surface that was built is built again at its resolution - a
surface is never kept, only how to make it.

What a square holds is not here: that is the squares' and, unsaved, the
autosave's, which the set reopening offers back.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from PySide6.QtCore import QByteArray

from ..core.square import SquareName

VERSION = 1
FILE = 'session.json'


def capture(win) -> dict:
    """The window as it stands, as the session holds it."""
    out: dict = {'version': VERSION}
    if win.working_set is not None and win.zone_dir is not None:
        ws = win.working_set
        out['set'] = {'zone': str(win.zone_dir), 'centre': str(ws.centre), 'size': ws.size}
        lon, lat = win.map.center_lonlat()
        out['view'] = {'lon': lon, 'lat': lat, 'zoom': win.map.zoom}
        out['elevation'] = win.elevation.value
    out['window'] = {'geometry': bytes(win.saveGeometry().toBase64()).decode(),
                     'state': bytes(win.saveState().toBase64()).decode()}
    active = win.panel.active
    out['layer'] = {'name': active.layer.name if active else None, 'opacity': win.panel.slider.value()}
    p = win.surface_panel
    out['surface'] = {'built': win._arcsec if win.surface.shaded is not None else None,
                      'mode': p.mode.currentText(), 'ramp': p.ramp.currentText(),
                      'scaling': p.scaling.currentText(),
                      'lo': p.lo.value(), 'hi': p.hi.value(), 'centre': p.centre.value(), 'width': p.width.value(),
                      'opacity': p.opacity.value(), 'unreached': p.show_unreached.isChecked(),
                      'one_level': p.show_one_level.isChecked(), 'envelope': p.show_envelope.isChecked()}
    out['tool'] = win.editor.tool
    out['magnify'] = win.loupe.on
    return out


def write(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=1)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def read(path: Path | None) -> dict | None:
    """The session, or None: no data directory, no file, or one of another
    version."""
    if path is None:
        return None
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get('version') == VERSION else None


def restore_window(win, data: dict) -> None:
    """The window and its panels: before it is shown, so it opens there
    rather than jumping."""
    w = data.get('window') or {}
    if w.get('geometry'):
        win.restoreGeometry(QByteArray.fromBase64(w['geometry'].encode()))
    if w.get('state'):
        win.restoreState(QByteArray.fromBase64(w['state'].encode()))


def restore(win, data: dict) -> bool:
    """Everything but the window: the choices made, then the set opened, and
    once it is read the view, the elevation and the surface. False if there
    was no set to open."""
    layer = data.get('layer') or {}
    for i, item in enumerate(win.panel.items):
        if item.layer.name == layer.get('name'):
            win.panel.radios[i].setChecked(True)
    if layer.get('opacity') is not None:
        win.panel.slider.setValue(int(layer['opacity']))
    s = data.get('surface') or {}
    p = win.surface_panel
    for box, key in ((p.mode, 'mode'), (p.ramp, 'ramp'), (p.scaling, 'scaling')):
        if s.get(key) and box.findText(s[key]) >= 0:
            box.setCurrentText(s[key])
    for spin, key in ((p.lo, 'lo'), (p.hi, 'hi'), (p.centre, 'centre'), (p.width, 'width')):
        if s.get(key) is not None:
            spin.setValue(float(s[key]))
    if s.get('opacity') is not None:
        p.opacity.setValue(int(s['opacity']))
    for box, key in ((p.show_unreached, 'unreached'), (p.show_one_level, 'one_level'),
                     (p.show_envelope, 'envelope')):
        if s.get(key) is not None:
            box.setChecked(bool(s[key]))
    if data.get('tool') in ('select', 'draw', 'spot', 'measure'):
        win.editor.set_tool(data['tool'])
    win.edit_actions['view.magnify'].setChecked(bool(data.get('magnify')))
    ws = data.get('set')
    if not ws:
        return False
    try:
        zone, centre, size = Path(ws['zone']), SquareName.parse(ws['centre']), int(ws['size'])
    except (KeyError, ValueError):
        return False
    if not zone.is_dir():
        win.statusBar().showMessage(f'the last session was in {zone}, which is not there')
        return False

    def landed(_ws):
        win.loader.finished.disconnect(landed)
        v = data.get('view') or {}
        if v:
            win.map.set_zoom(int(v['zoom']))
            win.map.center_on_lonlat(float(v['lon']), float(v['lat']))
        if data.get('elevation') is not None:
            win.elevation.set(float(data['elevation']))
        if s.get('built'):
            win.rebuild_surface(float(s['built']))
    # after the window's own handler, which fits the view to the centre square
    win.loader.finished.connect(landed)
    if not win.open_working_set(zone, centre, size):
        win.loader.finished.disconnect(landed)
        return False
    return True
