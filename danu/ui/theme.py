"""The theme (J5c): the desktop's, or light or dark whatever the desktop is.

Qt 6.8 can be asked for a colour scheme, and where the platform theme
honours the request that is all it takes: the palette, and the style's own
drawing, follow. Not every theme does. Measured on Qt 6.11 under Wayland,
GNOME's honoured light and dark; the portal theme the AppImage runs with
honoured neither, and nor does the offscreen platform the tests run on. There
the palette is set here instead, and Fusion draws with it - Qt's own light
palette, or the dark one below, with Qt's blue rather than the desktop's
accent, which belongs to a desktop that is not being followed.

Following the desktop again puts back the palette the platform gives.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

THEMES = {'auto': 'Follow the desktop', 'light': 'Light', 'dark': 'Dark'}
SCHEMES = {'auto': Qt.ColorScheme.Unknown, 'light': Qt.ColorScheme.Light, 'dark': Qt.ColorScheme.Dark}

# the dark palette, as (active and inactive, disabled). Not GNOME's, which
# Qt gives under Wayland: that has the fields the window's colour and Fusion's
# outlines darker still, and drawn by Fusion on its own an unticked box, the
# ladder's marks and a placeholder all but vanished. The fields darker than
# the window, the lines lighter, the highlight Qt's blue
_DARK = {
    'Window': ('#353535', '#353535'), 'WindowText': ('#f0f0f0', '#808080'),
    'Base': ('#232323', '#2c2c2c'), 'AlternateBase': ('#2c2c2c', '#2c2c2c'),
    'Text': ('#f0f0f0', '#808080'), 'PlaceholderText': ('#8c8c8c', '#6a6a6a'),
    'Button': ('#3c3c3c', '#353535'), 'ButtonText': ('#f0f0f0', '#808080'),
    'BrightText': ('#ff6060', '#ff6060'),
    'Light': ('#5a5a5a', '#4a4a4a'), 'Midlight': ('#484848', '#404040'),
    'Mid': ('#6e6e6e', '#5a5a5a'), 'Dark': ('#232323', '#232323'), 'Shadow': ('#141414', '#141414'),
    'Highlight': ('#308cc6', '#505050'), 'HighlightedText': ('#ffffff', '#909090'),
    'Link': ('#5fa8e0', '#5fa8e0'), 'LinkVisited': ('#b48ce0', '#b48ce0'),
    'ToolTipBase': ('#2c2c2c', '#2c2c2c'), 'ToolTipText': ('#f0f0f0', '#f0f0f0'),
    'Accent': ('#308cc6', '#808080'),
}


def palette(theme: str) -> QPalette:
    """The palette for a theme the platform would not give."""
    if theme == 'light':
        return QStyleFactory.create('Fusion').standardPalette()
    p = QPalette()
    for role, (on, off) in _DARK.items():
        r = getattr(QPalette.ColorRole, role)
        for group in (QPalette.ColorGroup.Active, QPalette.ColorGroup.Inactive):
            p.setColor(group, r, QColor(on))
        p.setColor(QPalette.ColorGroup.Disabled, r, QColor(off))
    return p


def apply(app: QApplication, theme: str) -> bool:
    """``theme`` put to use: one of THEMES, anything else taken as 'auto'.
    True if Qt gave it, False if the palette was set here."""
    want = SCHEMES.get(theme, Qt.ColorScheme.Unknown)
    app.styleHints().setColorScheme(want)
    if want == Qt.ColorScheme.Unknown or app.styleHints().colorScheme() == want:
        app.setPalette(QPalette())                   # the platform's, a palette set here undone
        return True
    app.setPalette(palette(theme))
    return False
