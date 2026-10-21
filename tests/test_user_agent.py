"""Every request Danu makes says it is Danu, and which: ``danu.USER_AGENT``,
the editor's and the server's alike. PRIVACY.md says so."""

import re
from pathlib import Path

import danu
from danu import USER_AGENT
from danu.core import mirror

ROOT = Path(__file__).parents[1]
MADE = re.compile(r'QNetworkRequest\(|urllib\.request\.Request\(')


def test_it_names_danu_and_its_version():
    assert USER_AGENT.startswith(f'Danu/{danu.__version__} ')
    assert 'github.com/opengeofiction-net/danu' in USER_AGENT


def test_it_names_the_platform_and_privacy_says_so():
    assert USER_AGENT == f'Danu/{danu.__version__} ({danu.PLATFORM}; +https://github.com/opengeofiction-net/danu)'
    for python, named in (('win32', 'Windows'), ('darwin', 'macOS'), ('linux', 'Linux'), ('freebsd14', 'freebsd14')):
        assert danu.platform_name(python) == named
    text = (ROOT / 'PRIVACY.md').read_text()
    assert '`Danu/<version> (<platform>; +https://github.com/opengeofiction-net/danu)`' in text
    assert danu.__version__ not in text, 'no version to keep current'


def test_every_request_made_carries_it():
    """Counted in the source: a request built in a file that does not say
    USER_AGENT as often is one sent without it."""
    made = {}
    for path in sorted((ROOT / 'danu').rglob('*.py')):
        text = path.read_text(encoding='utf-8')
        n = len(MADE.findall(text))
        if n:
            made[path.relative_to(ROOT).as_posix()] = n
            said = len(re.findall(r'\bUSER_AGENT\)|\'User-Agent\': USER_AGENT', text))
            assert said >= n, f'{path.name}: {n} requests made, {said} with the user agent'
    assert len(made) >= 9, made                   # the scan finds them; nine files, 2026-10-15


def test_a_request_through_the_opener_has_it():
    seen = []

    class Answer:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

        def read(self):
            return b'<a href="zone-a/">zone-a/</a>'

    def opener(req, timeout):
        seen.append(req.get_header('User-agent'))
        return Answer()
    mirror.list_zones('https://example.invalid/osm-squares', opener=opener)
    assert seen == [USER_AGENT]
