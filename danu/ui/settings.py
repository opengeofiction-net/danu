"""What the editor remembers between runs: where the squares are, what was
open last. QSettings in INI form at ~/.config/danu/danu.ini - the directory
the spec names, beside layers.toml. Nothing here is required to exist."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSettings

from ..core.square import SquareName

RECENT_MAX = 8

# Rebuild's key, which is not rebound - the menu and the preferences' clash
# check both read it here
REBUILD_KEY = 'Ctrl+R'

# the keys the spec gives, a column on a QWERTY keyboard: the left hand rests
# on w and s and reaches 2 up and x down. All rebindable, under [keys] in the
# INI, as Qt key sequences - 'Ctrl+Shift+E', 'PgUp', 'Space'
DEFAULT_KEYS = {
    'elevation.big_up': '2',
    'elevation.small_up': 'W',
    'elevation.small_down': 'S',
    'elevation.big_down': 'X',
    'elevation.pick_up': 'Space',
    'elevation.nudge_up': ']',
    'elevation.nudge_down': '[',
    'elevation.sea_level': '0',
    'tool.select': 'Q',
    'tool.draw': 'A',
    # Q, A, Z: the tools are a column under the left hand, as the
    # elevation keys are, and for the same reason
    'tool.spot': 'Z',
    # M for measure: a line, and the ground along it - H3b
    'tool.measure': 'M',
    'edit.undo': 'Ctrl+Z',
    'edit.redo': 'Ctrl+Shift+Z',
    'edit.delete': 'Delete',
    'edit.delete_way': 'Shift+Delete',
    'edit.import_water': 'Ctrl+I',
    # and the main map's peaks and saddles with a height, as spot heights - G9
    'edit.import_heights': 'Ctrl+Shift+I',
    # L for level: a lake's, or a river's at the point selected - G6a
    'edit.set_level': 'L',
    # G for grade: a level from the contours, proposed - G6b
    'edit.grade': 'G',
    # and the river network it belongs to - G6d-2
    'edit.grade_network': 'Shift+G',
    # and flatten a lake at its level, through the contours - G7a
    'edit.flatten': 'F',
    # burn a climb the grade found into the terrain, or every one - G7b
    'edit.burn': 'B',
    'edit.burn_all': 'Shift+B',
    # O for loop: a contour crossing itself, chosen in the checks panel, the
    # loop cut out - G8c
    'edit.cut_loop': 'O',
    # P splits a contour at the node selected, as JOSM's does - G8d; the
    # surface's pinch, which had P, moves to C
    'edit.split': 'P',
    # U unglues a node contours of two levels share - G8e
    'edit.unglue': 'U',
    # R reverses the coastline selected, the sea to its other side; and the
    # main map's coastlines imported, beside water's and the spot heights'
    'edit.reverse_coastline': 'R',
    # K marks the 0 m line selected as the coastline, or unmarks one
    'edit.mark_coastline': 'K',
    'edit.import_coastline': 'Ctrl+Alt+I',
    # J for JOSM: the place shown, and what is selected, shown in JOSM by its
    # remote control - for the water and peaks fixed on the main map
    'view.josm': 'J',
    # and the surface, served as a WMS, added to JOSM as a layer - H5
    'view.josm_surface': 'Shift+J',
    # V for view closer: the loupe at the cursor, on and off - H3d
    'view.magnify': 'V',
    'file.save': 'Ctrl+S',
    'file.save_as': 'Ctrl+Shift+S',
    'surface.pinch': 'C',
}


# the addresses the preferences edit (H6e), as key: label
URLS = {'ogf/server': 'OGF server',
        'overpass/url': 'Overpass',
        'territory/geometry': 'Territories',
        'territory/owners': 'Territory owners',
        'published/dem': 'Published DEM',
        'josm/url': 'JOSM remote control',
        'squares/mirror': 'Squares to import'}


def default_url(key: str) -> str:
    """The address Danu uses when the INI gives none - read from its module
    as it is asked for, so a test pointing a module elsewhere is heeded."""
    from ..core import mirror, published
    from ..water import overpass
    from . import josm, territory
    return {'ogf/server': 'https://opengeofiction.net',
            'overpass/url': overpass.OVERPASS_URL,
            'territory/geometry': territory.GEOMETRY_URL,
            'territory/owners': territory.ATTRIBUTES_URL,
            'published/dem': published.URL,
            'josm/url': josm.DEFAULT_URL,
            'squares/mirror': mirror.URL}[key]


class Settings:
    def __init__(self, path: Path | None = None):
        if path is None:
            self.q = QSettings(QSettings.Format.IniFormat, QSettings.Scope.UserScope, 'danu', 'danu')
        else:
            self.q = QSettings(str(path), QSettings.Format.IniFormat)

    @property
    def file(self) -> Path:
        return Path(self.q.fileName())

    # ----------------------------------------------------------- squares
    @property
    def squares_root(self) -> Path | None:
        v = self.q.value('squares/root', '')
        return Path(v) if v else None

    @squares_root.setter
    def squares_root(self, path: Path | None):
        self.q.setValue('squares/root', str(path) if path else '')

    @property
    def import_root(self) -> Path:
        """Where File › Import mirrors a zone's squares to (H6g), a zone a
        directory: ~/Documents/danu/osm-squares unless the INI says."""
        v = self.q.value('squares/import_root', '')
        if v:
            return Path(v)
        from PySide6.QtCore import QStandardPaths
        docs = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        return Path(docs or Path.home() / 'Documents') / 'danu' / 'osm-squares'

    @import_root.setter
    def import_root(self, path: Path | None):
        self.q.setValue('squares/import_root', str(path) if path else '')

    @property
    def size(self) -> int:
        try:
            n = int(self.q.value('squares/size', 3))
        except (TypeError, ValueError):
            return 3
        return n if n in (1, 3, 5) else 3

    @size.setter
    def size(self, n: int):
        self.q.setValue('squares/size', int(n))

    # --------------------------------------------------------- elevation
    def _metres(self, key: str, default: float) -> float:
        try:
            v = float(self.q.value(key, default))
        except (TypeError, ValueError):
            return default
        return v if v > 0 else default

    @property
    def small_step(self) -> float:
        return self._metres('elevation/small', 10.0)

    @small_step.setter
    def small_step(self, v: float):
        self.q.setValue('elevation/small', float(v))

    @property
    def big_step(self) -> float:
        return self._metres('elevation/big', 50.0)

    @big_step.setter
    def big_step(self, v: float):
        self.q.setValue('elevation/big', float(v))

    @property
    def user(self) -> str:
        """The mapper's OGF username, for 'is this mine to draw?' - the
        server's, from signing in (H6f). Empty means unknown, and then
        ownership is shown but never called wrong."""
        return str(self.q.value('user/name', '') or '')

    @user.setter
    def user(self, name: str):
        self.q.setValue('user/name', name.strip())

    @property
    def roles(self) -> list[str]:
        """The user's roles on the server, as signing in found them."""
        return [r for r in str(self.q.value('user/roles', '') or '').split(',') if r]

    @roles.setter
    def roles(self, roles: list[str]):
        self.q.setValue('user/roles', ','.join(roles))

    @property
    def admin(self) -> bool:
        """An OGF administrator - said beside the territory warning."""
        return 'administrator' in self.roles

    @property
    def token(self) -> str:
        """The OAuth 2 token signing in to OGF gave (H6f), or empty."""
        return str(self.q.value('ogf/token', '') or '')

    @token.setter
    def token(self, value: str):
        self.q.setValue('ogf/token', value)

    @property
    def bare_min_hectares(self) -> float:
        """The smallest closed contour the checks report as holding nothing
        (R39), in hectares - 10 unless the INI says otherwise."""
        try:
            return float(self.q.value('checks/bare_min_hectares', 10))
        except (TypeError, ValueError):
            return 10.0

    @property
    def wms_port(self) -> int:
        """The loopback port the surface is served on (H5), the same from
        one run to the next so a layer JOSM keeps finds it again."""
        from .wms import PORT
        try:
            return int(self.q.value('josm/wms_port', PORT))
        except (TypeError, ValueError):
            return PORT

    @wms_port.setter
    def wms_port(self, port: int):
        self.q.setValue('josm/wms_port', int(port))

    @bare_min_hectares.setter
    def bare_min_hectares(self, ha: float):
        self.q.setValue('checks/bare_min_hectares', float(ha))

    # ------------------------------------------------------------ the look
    @property
    def theme(self) -> str:
        """'auto', 'light' or 'dark' (J5c): the desktop's scheme, or one
        whatever the desktop is."""
        v = str(self.q.value('appearance/theme', 'auto') or 'auto')
        return v if v in ('auto', 'light', 'dark') else 'auto'

    @theme.setter
    def theme(self, v: str):
        self.q.setValue('appearance/theme', v)

    def _flag(self, key: str, default: bool) -> bool:
        # an INI holds 'true' and 'false' as text, which bool() takes as true
        v = self.q.value(key, default)
        return v if isinstance(v, bool) else str(v).lower() in ('true', '1', 'yes')

    @property
    def start_always(self) -> bool:
        """The start page at start even when a square opens (J5c), over it."""
        return self._flag('start/always', False)

    @start_always.setter
    def start_always(self, v: bool):
        self.q.setValue('start/always', bool(v))

    @property
    def menu_offered(self) -> bool:
        """The start page has offered the AppImage a place in the
        applications menu, and been answered (J5c): it asks once."""
        return self._flag('start/menu_offered', False)

    @menu_offered.setter
    def menu_offered(self, v: bool):
        self.q.setValue('start/menu_offered', bool(v))

    # ------------------------------------------------------------ the servers
    # Each read where it is used, so one changed in the preferences (H6e)
    # holds from the next use on. Empty, or absent, is the default.
    def url(self, key: str) -> str:
        """The address under ``key`` - one of URLS - or its default."""
        return str(self.q.value(key, '') or '').strip() or default_url(key)

    def set_url(self, key: str, value: str) -> None:
        value = value.strip()
        self.q.setValue(key, '' if value == default_url(key) else value)

    @property
    def server_url(self) -> str:
        """The OGF server: where an object's page is, by its id (H6c)."""
        return self.url('ogf/server').rstrip('/')

    @property
    def josm_url(self) -> str:
        """JOSM's remote control, which listens on the loopback only."""
        return self.url('josm/url')

    @property
    def overpass_url(self) -> str:
        return self.url('overpass/url')

    @property
    def ladders_file(self) -> Path:
        """The ladder overrides, beside the INI: ~/.config/danu/ladders.toml."""
        return self.file.parent / 'ladders.toml'

    # -------------------------------------------------------------- keys
    def key(self, action: str) -> str:
        """The key sequence bound to an action, the spec's default unless
        the INI says otherwise. An empty binding unbinds."""
        v = self.q.value(f'keys/{action}', None)
        return DEFAULT_KEYS[action] if v is None else str(v)

    def set_key(self, action: str, sequence: str):
        self.q.setValue(f'keys/{action}', sequence)

    # ------------------------------------------------------------ recent
    # One string, entries separated by newlines, rather than a QSettings list.
    # Qt's INI backend has been known to hand a list of one back as a plain
    # string, which a loop would walk character by character. Measured on
    # PySide6 6.11 it does not - a one-item list came back a list - but the
    # encoding here is under our control on every Qt and costs nothing, so it
    # does not lean on that
    def _entries(self) -> list[str]:
        raw = self.q.value('recent/squares', '')
        return [e for e in str(raw or '').split('\n') if e]

    def recent(self) -> list[tuple[Path, SquareName, int]]:
        out = []
        for entry in self._entries():
            try:
                d, name, size = entry.split('|')
                out.append((Path(d), SquareName.parse(name), int(size)))
            except ValueError:
                continue
        return out

    def remember(self, zone_dir: Path, name: SquareName, size: int):
        entry = f'{zone_dir}|{name}|{size}'
        items = [e for e in self._entries() if e != entry]
        self.q.setValue('recent/squares', '\n'.join([entry] + items[:RECENT_MAX - 1]))
        self.q.sync()
