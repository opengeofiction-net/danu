"""The nightly build reads the squares and nothing else - G6c.

It never fetched from Overpass in service - server/etc/danu.conf held the
switch off - but the switch was there, defaulting on in danu-build-zone. The editor imports water
into the squares; a level on it reaches the build as a spot height. Read as text,
so it runs where GDAL does not.
"""

from pathlib import Path

ROOT = Path(__file__).parents[1]
BUILD = [*sorted((ROOT / 'server').rglob('*')), *sorted((ROOT / 'danu' / 'surface').rglob('*.py'))]


def test_nothing_the_build_runs_names_overpass_or_the_network():
    said = {}
    for path in BUILD:
        if not path.is_file():
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        found = [w for w in ('overpass.', 'api/interpreter', 'urllib', 'urlopen', 'requests.',
                             'WATER_CONSTRAINTS', 'water-constraints') if w in text]
        if found:
            said[path.relative_to(ROOT).as_posix()] = found
    assert said == {}, said
