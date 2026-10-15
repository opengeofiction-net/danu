"""Danu: a contour editor and the elevation pipeline behind it.

`core` through `cli` are importable without Qt and run headless. `ui` is the
editor and is the only part which imports PySide6.
"""

# The one version: pyproject.toml reads it from here, debian/changelog says
# the same (tests/test_version.py), and a release is tagged with it.
__version__ = "0.2.0"

# what every request Danu makes says it is - the editor's and the server's
# alike, so a server's log can tell Danu's from anything else, and which
USER_AGENT = f'Danu/{__version__} (+https://github.com/opengeofiction-net/danu)'
