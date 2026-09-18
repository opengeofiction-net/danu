"""danu.surface.ramp: the tiles' colours, and the spectral one."""

import subprocess
from pathlib import Path

import numpy as np
import pytest

from danu.surface import ramp

ROOT = Path(__file__).parents[1]


def test_the_traditional_ramp_is_the_servers_file_and_there_is_one_of_them():
    pkg = ROOT / 'danu' / 'surface' / 'relief.ramp'
    srv = ROOT / 'server' / 'etc' / 'relief.ramp'
    assert srv.is_symlink() and srv.resolve() == pkg.resolve()
    assert srv.read_bytes() == pkg.read_bytes()
    # and the package installs the one file to where the build reads it
    install = (ROOT / 'debian' / 'danu-server.install').read_text()
    assert 'danu/surface/relief.ramp' in install and 'server/etc/relief.ramp' not in install


def test_the_traditional_ramp_parses_to_the_tiles_stops():
    t = ramp.traditional()
    assert t.values == (0.0, 1.0, 100.0, 300.0, 1500.0, 3000.0, 4000.0, 5000.0, 6000.0)
    assert t.colour(0) == (0, 0, 0, 0)               # sea level is transparent
    assert t.colour(1) == (17, 120, 3, 255)
    assert t.colour(300) == (231, 218, 158, 255)
    assert t.colour(6000) == (255, 255, 255, 255)


def test_colours_are_linear_between_stops_and_clamped_beyond():
    t = ramp.traditional()
    assert t.colour(200) == (152, 190, 114, 255)     # halfway 100..300
    assert t.colour(-50) == t.colour(0)
    assert t.colour(9000) == t.colour(6000)


def test_the_array_form_is_the_scalar_form():
    t = ramp.traditional()
    xs = np.array([-5.0, 0.0, 0.5, 1.0, 57.0, 200.0, 2999.0, 7000.0])
    arr = t.rgba(xs)
    assert arr.shape == (8, 4) and arr.dtype == np.uint8
    for x, row in zip(xs, arr):
        assert tuple(int(v) for v in row) == t.colour(float(x))


def test_spectral_runs_blue_to_red_over_the_range_it_is_given():
    s = ramp.spectral(100, 1100)
    assert s.colour(100) == (43, 131, 186, 255)
    assert s.colour(600) == (255, 255, 191, 255)
    assert s.colour(1100) == (215, 25, 28, 255)
    assert s.colour(50) == s.colour(100) and s.colour(2000) == s.colour(1100)


def test_a_degenerate_range_does_not_divide_by_zero():
    s = ramp.spectral(250, 250)
    assert s.colour(250) == (43, 131, 186, 255)


def test_an_inverted_range_is_refused():
    with pytest.raises(ValueError, match='runs backwards'):
        ramp.spectral(1000, 100)


def test_colour_is_rgba_of_one_value_and_nothing_wraps():
    # a ramp whose channel would round to 256 if it could: it cannot, because
    # stops are 0..255, but the cast must still be a clip and not a wrap
    r = ramp.Ramp('t', (0.0, 1.0), ((254, 0, 0, 255), (255, 0, 0, 255)))
    assert r.colour(0.5) == (254, 0, 0, 255) or r.colour(0.5) == (255, 0, 0, 255)
    assert r.rgba(np.array([0.5]))[0].tolist() == list(r.colour(0.5))
    assert r.rgba(np.array([5.0]))[0, 0] == 255


@pytest.mark.parametrize('text,msg', [
    ('100 1 2\n', 'want "value R G B'),
    ('100 1 2 300\n', 'outside 0..255'),
    ('100 1 2 3\n', 'at least two stops'),
    ('100 1 2 3\n50 4 5 6\n', 'must ascend'),
])
def test_a_bad_ramp_file_is_refused_with_a_reason(text, msg):
    with pytest.raises(ValueError, match=msg):
        ramp.Ramp.from_gdaldem(text, 'bad')


def test_the_gdaldem_format_is_what_the_build_gives_gdaldem():
    """The build passes this file straight to gdaldem color-relief; if it
    parses here it is the format that tool reads, comments included."""
    text = '# comment\n0 0 0 0 0   # trailing comment\n\n10 1 2 3\n'
    r = ramp.Ramp.from_gdaldem(text, 't')
    assert r.values == (0.0, 10.0) and r.colours == ((0, 0, 0, 0), (1, 2, 3, 255))
