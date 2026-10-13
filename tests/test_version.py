"""J1: one version. danu/__init__.py holds it, pyproject.toml reads it from
there, and the .deb's changelog says the same - so a tag names one thing,
which the release workflow checks it against."""

import re
import tomllib
from pathlib import Path

from danu import __version__

ROOT = Path(__file__).parents[1]


def test_the_version_is_a_release_number():
    assert re.fullmatch(r'\d+\.\d+\.\d+', __version__)


def test_pyproject_reads_the_version_from_the_package():
    p = tomllib.loads((ROOT / 'pyproject.toml').read_text())
    assert 'version' not in p['project'] and 'version' in p['project']['dynamic']
    assert p['tool']['setuptools']['dynamic']['version'] == {'attr': 'danu.__version__'}


def test_the_debian_changelog_is_at_the_same_version():
    top = (ROOT / 'debian' / 'changelog').read_text().splitlines()[0]
    m = re.match(r'danu \(([^)-]+)-\d+\) ', top)
    assert m and m.group(1) == __version__, top
