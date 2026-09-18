"""danu.ui.config: the layers, from the shipped defaults and a user's file."""

import pytest

from danu.ui import config


def test_the_shipped_defaults_are_the_three_ogf_layers_and_carto_is_on():
    layers = config.load_layers()
    assert [l.name for l in layers] == ['ogf-carto', 'ttopo', 'cyclogf']
    assert [l.visible for l in layers] == [True, False, False]
    assert all(l.max_zoom == 19 for l in layers)
    assert layers[0].tile_url(6, 53, 33) == 'https://tile.opengeofiction.net/ogf-carto/6/53/33.png'
    assert layers[2].url.startswith('https://tiles06.')     # its own host


def test_a_missing_user_file_is_the_ordinary_case(tmp_path):
    assert config.load_layers(tmp_path / 'nope.toml') == config.load_layers()


def test_a_user_layer_replaces_by_name_in_place_and_new_ones_append(tmp_path):
    f = tmp_path / 'layers.toml'
    f.write_text('''
[[layer]]
name = "ttopo"
url = "https://example.test/topo/{z}/{x}/{y}.png"
opacity = 0.5

[[layer]]
name = "mine"
url = "http://localhost:8080/{z}/{x}/{y}.png"
''')
    layers = config.load_layers(f)
    assert [l.name for l in layers] == ['ogf-carto', 'ttopo', 'cyclogf', 'mine']
    assert layers[1].url.startswith('https://example.test') and layers[1].opacity == 0.5
    assert layers[3].max_zoom == 19        # defaults fill what the user left out


@pytest.mark.parametrize('body,msg', [
    ('[[layer]]\nurl = "https://x/{z}/{x}/{y}.png"', 'no name'),
    ('[[layer]]\nname = "a"\nurl = "https://x/{z}/{x}.png"', 'no {y}'),
    ('[[layer]]\nname = "a"\nurl = "https://x/{z}/{x}/{y}.png"\nopacity = 1.5', 'opacity'),
    ('[[layer]]\nname = "a"\nurl = "https://x/{z}/{x}/{y}.png"\nmin_zoom = 5\nmax_zoom = 3', 'zoom range'),
    ('[[layer]]\nname = "a"\nurl = "https://x/{z}/{x}/{y}.png"\ncolour = "red"', 'colour'),
])
def test_a_bad_layer_is_refused_with_a_reason(tmp_path, body, msg):
    f = tmp_path / 'layers.toml'
    f.write_text(body)
    with pytest.raises(ValueError, match=msg):
        config.load_layers(f)
