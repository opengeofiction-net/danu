"""Danu: a contour editor and the elevation pipeline behind it.

`core` through `cli` are importable without Qt and run headless. `ui` is the
editor and is the only part which imports PySide6.
"""

# The one version: pyproject.toml reads it from here, debian/changelog says
# the same (tests/test_version.py), and a release is tagged with it.
__version__ = "1.3.2"

import sys as _sys


def platform_name(python: str) -> str:
    """The platform as the user agent names it, from ``sys.platform``: the
    three Danu is built for, and anything else as Python names it."""
    if python.startswith('linux'):
        return 'Linux'
    return {'win32': 'Windows', 'darwin': 'macOS'}.get(python, python)


PLATFORM = platform_name(_sys.platform)

# what every request Danu makes says it is - the editor's and the server's
# alike, so a server's log can tell Danu's from anything else, and which
# version on which platform
USER_AGENT = f'Danu/{__version__} ({PLATFORM}; +https://github.com/opengeofiction-net/danu)'
