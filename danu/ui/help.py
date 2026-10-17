"""Help (J5b): getting started, the keys, and what each layer is.

Getting started and the layers are Markdown in ``danu/ui/help``, shipped with
the package so they describe the Danu they came with, offline, and read the
same on GitHub. The keys are not written down anywhere: they are made from the
bindings as they are now, so a key changed in Preferences is the key Help
gives. What is not a binding - the mouse, the keys while drawing - is listed
here, beside the code that names the bindings.

The wiki page, Help:Danu, is where Danu is found from outside:
what it is, where to get it, how to send squares in. It changes rarely, and
Help links to it rather than repeating it.
"""

from __future__ import annotations

import re
import sys
from importlib import resources

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices, QKeySequence
from PySide6.QtWidgets import QDialog, QTextBrowser, QVBoxLayout

from .settings import DEFAULT_KEYS, REBUILD_KEY

WIKI = 'https://wiki.opengeofiction.net/index.php/Help:Danu'
PAGES = {'getting-started': 'Getting started', 'keys': 'Keys', 'layers': 'Layers'}

# what no binding names, as the code has it: danu.ui.mapview's wheel and
# drag, danu.ui.tools' keys while drawing or with a proposal shown
MOUSE = (('Wheel', 'zoom in and out, about the cursor'),
         ('Ctrl+Wheel', 'the active elevation, by the small step'),
         ('Ctrl+Shift+Wheel', 'the active elevation, by the big step'),
         ('Alt+Wheel', "the surface's opacity"),
         ('Shift+Wheel', "the magnifier's power, while it is on"),
         ('Right drag', 'move the map, whatever the tool'),
         ('Drag a node', 'move it'),
         ('Ctrl+Drag a node', 'onto another node: join the two'),
         ('Shift+Drag a contour', 'move the whole contour'),
         ('Double click a line', 'insert a node'),
         ('Click again', 'the next of what lies there'))
# and on macOS, a trackpad's own (#194): mapview moves the map for two
# fingers and zooms for a pinch, where a mouse's wheel still zooms
TRACKPAD = (('Two-finger scroll', 'move the map'),
            ('Pinch', 'zoom in and out, about the fingers'))
MAC = sys.platform == 'darwin'
DRAWING = (('Enter', 'finish the contour being drawn; accept a proposal'),
           ('Backspace', 'take back the last node drawn'),
           ('Escape', 'stop drawing - a redraw not brought back is dropped; drop a proposal; '
                      'back to select'))


def page(name: str) -> str:
    """A page of Help as Markdown."""
    return (resources.files('danu.ui') / 'help' / f'{name}.md').read_text(encoding='utf-8')


def _key(seq: str) -> str:
    return QKeySequence(seq).toString(QKeySequence.SequenceFormat.NativeText) or seq


def keys(labels: dict[str, str], key_of) -> str:
    """The keys page: each binding as it is set now, by where the menus put
    it - ``labels`` as MainWindow.action_labels gives them, ``key_of`` a
    binding's key by its name."""
    rows = [(labels.get(n, n), key_of(n)) for n in [*[n for n in labels if n in DEFAULT_KEYS],
                                                    *[n for n in DEFAULT_KEYS if n not in labels]]]
    rows.append(('Surface › Rebuild surface', REBUILD_KEY))
    # the platform's own keys, where it has one: Quit has none on some desktops
    for what, std in (('File › Open square…', QKeySequence.StandardKey.Open),
                      ('File › Preferences…', QKeySequence.StandardKey.Preferences),
                      ('File › Quit', QKeySequence.StandardKey.Quit),
                      ('Help › Getting started', QKeySequence.StandardKey.HelpContents)):
        if k := QKeySequence(std).toString():
            rows.append((what, k))
    out = ['# Keys', '',
           "As they are set now: File › Preferences… changes them, on its Keys tab.", '',
           '| What | Key |', '|---|---|']
    out += [f'| {what} | {_key(k) if k else "-"} |' for what, k in rows]
    out += ['', '## While drawing', '', '| Key | What |', '|---|---|']
    out += [f'| {k} | {what} |' for k, what in DRAWING]
    out += ['', '## The mouse', '', '| Mouse | What |', '|---|---|']
    out += [f'| {k} | {what} |' for k, what in mouse()]
    return '\n'.join(out) + '\n'


def mouse(mac: bool | None = None) -> list[tuple[str, str]]:
    """The mouse table's rows, as the platform writes them: on macOS the
    modifiers as its symbols, in its order, and the trackpad's two."""
    if not (MAC if mac is None else mac):
        return list(MOUSE)
    return [(_mac_modifiers(k), what) for k, what in MOUSE] + list(TRACKPAD)


# the modifiers as macOS writes them and in the order it does: Qt's Ctrl is ⌘
_MAC_ORDER = (('Meta', '⌃'), ('Alt', '⌥'), ('Shift', '⇧'), ('Ctrl', '⌘'))


def _mac_modifiers(text: str) -> str:
    *mods, rest = text.split('+')
    return ''.join(sym for name, sym in _MAC_ORDER if name in mods) + rest


_BOLD_KEY = re.compile(r'\*\*((?:(?:Ctrl|Alt|Shift|Meta)\+)+[A-Za-z0-9]+)\*\*')


def native(markdown: str) -> str:
    """A page's keys, written **Ctrl+S**, as the platform writes them: the
    same on Linux and Windows, **⌘S** on macOS."""
    return _BOLD_KEY.sub(lambda m: f'**{_key(m.group(1))}**', markdown)


class HelpWindow(QDialog):
    """One window for the three pages, each linking to the others; a link
    out of Help goes to the browser."""

    def __init__(self, labels, key_of, parent=None, open_url=None):
        super().__init__(parent)
        self.setWindowTitle('Danu help')
        self.resize(640, 720)
        self.labels, self.key_of = labels, key_of
        self.open_url = open_url or (lambda url: QDesktopServices.openUrl(QUrl(url)))
        self.text = QTextBrowser()
        self.text.setOpenLinks(False)
        self.text.anchorClicked.connect(self._link)
        box = QVBoxLayout(self)
        box.addWidget(self.text)
        self.current = ''

    def show_page(self, name: str) -> None:
        body = keys(self.labels(), self.key_of) if name == 'keys' else native(page(name))
        nav = ' · '.join(f'**{title}**' if n == name else f'[{title}](help:{n})' for n, title in PAGES.items())
        self.text.setMarkdown(f'{nav} · [Danu on the OGF wiki]({WIKI})\n\n{body}')
        self.current = name
        self.show()
        self.raise_()
        self.activateWindow()

    def _link(self, url: QUrl) -> None:
        if url.scheme() == 'help' and url.path() in PAGES:
            self.show_page(url.path())
        else:
            self.open_url(url.toString())
