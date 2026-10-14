"""The AppImage in the applications menu (J5c).

An AppImage is one file a mapper downloads and runs; nothing installs it, so
the desktop's menu has no Danu in it. This puts one there for the user alone:
``danu.desktop`` under ``$XDG_DATA_HOME/applications``, running the AppImage
by its path, and the icon at each size under ``icons/hicolor``. The .deb and
the Windows installers have their own entries, so this is offered only where
the AppImage runtime says it is running one - ``$APPIMAGE``, its path.

The entry is marked as written here, with the AppImage it runs, so a file
the mapper wrote is never taken for it, removed or rewritten. An AppImage
moved, or replaced by a newer one and deleted, leaves an entry naming a file
that is gone; the AppImage running then takes it over.

The entry is the packaged ``packaging/linux/danu.desktop`` with Exec and
TryExec the AppImage's path; a test holds the two the same.
"""

from __future__ import annotations

import os
from pathlib import Path

ICONS = Path(__file__).parent / 'icons'
MARK = 'X-Danu-AppImage'
ENTRY = {
    'Type': 'Application',
    'Name': 'Danu',
    'Comment': 'Draw the contours of an OpenGeofiction territory',
    'Icon': 'danu',
    'Categories': 'Science;Geography;Maps;',
    'Terminal': 'false',
}


def appimage() -> Path | None:
    """The AppImage Danu runs from, if it runs from one."""
    path = os.environ.get('APPIMAGE', '')
    return Path(path) if path else None


def data_home() -> Path:
    # a relative one is to be ignored, the base directory spec says
    env = os.environ.get('XDG_DATA_HOME', '')
    return Path(env) if os.path.isabs(env) else Path.home() / '.local' / 'share'


def entry_path() -> Path:
    return data_home() / 'applications' / 'danu.desktop'


def _icon_paths() -> list[tuple[Path, Path]]:
    """Each icon Danu ships, and where the menu looks for it."""
    out = []
    for png in sorted(ICONS.glob('danu-*.png')):
        n = png.stem.split('-')[1]
        out.append((png, data_home() / 'icons' / 'hicolor' / f'{n}x{n}' / 'apps' / 'danu.png'))
    return out


# a string value's escapes, as the Desktop Entry spec gives them
_ESCAPES = (('\\', '\\\\'), ('\n', '\\n'), ('\t', '\\t'), ('\r', '\\r'))


def _string(s: str) -> str:
    for c, e in _ESCAPES:
        s = s.replace(c, e)
    return s


def _unstring(s: str) -> str:
    out, i = [], 0
    back = {e[1]: c for c, e in _ESCAPES}
    while i < len(s):
        if s[i] == '\\' and i + 1 < len(s) and s[i + 1] in back:
            out.append(back[s[i + 1]])
            i += 2
        else:
            out.append(s[i])
            i += 1
    return ''.join(out)


def _quote(path: Path) -> str:
    """A path as an Exec argument: a literal % doubled, as the field codes
    want; quoted, the four characters the spec reserves inside quotes
    escaped; and then escaped again as any string in the file is."""
    s = str(path).replace('%', '%%')
    for c in '\\"`$':
        s = s.replace(c, '\\' + c)
    return _string(f'"{s}"')


def installed() -> Path | None:
    """The AppImage the entry written here runs, or None: no entry, or one
    Danu did not write."""
    try:
        text = entry_path().read_text(encoding='utf-8')
    except (OSError, UnicodeDecodeError):
        return None
    for line in text.splitlines():
        if line.startswith(f'{MARK}='):
            return Path(_unstring(line.split('=', 1)[1]))
    return None


def install(image: Path) -> None:
    """The entry and the icons, running ``image``."""
    lines = ['[Desktop Entry]', *(f'{k}={v}' for k, v in ENTRY.items()),
             f'Exec={_quote(image)}', f'TryExec={_string(str(image))}', f'{MARK}={_string(str(image))}']
    path = entry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    tmp.replace(path)                                    # a menu reading it never sees half
    for src, dst in _icon_paths():
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(src.read_bytes())


def remove() -> None:
    """The entry and the icons, if the entry is Danu's."""
    if installed() is None:
        return
    entry_path().unlink(missing_ok=True)
    for _src, dst in _icon_paths():
        dst.unlink(missing_ok=True)


def follow(image: Path | None) -> bool:
    """At start: an entry naming an AppImage that is gone runs this one.
    True if it was rewritten."""
    named = installed()
    if image is None or named is None or named == image or named.exists():
        return False
    install(image)
    return True
