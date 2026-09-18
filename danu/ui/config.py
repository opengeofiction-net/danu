"""What the editor is configured with: the tile layers, to begin with.

TOML, read with the standard library's tomllib. A default set ships inside the
package and a user file beside it in the XDG config directory overrides by
layer name and adds what it likes - requirement R8 in docs/spec.md wants any
tile layer the config names,
and cyclogf already lives on a per-server host rather than the shared one.

No Qt here. The caller says where the user file is; this decides what it means.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

USER_FILE = 'layers.toml'


@dataclass(frozen=True)
class Layer:
    name: str
    url: str
    title: str = ''
    attribution: str = ''
    min_zoom: int = 0
    max_zoom: int = 19
    opacity: float = 1.0
    # shown on start, or waiting in the panel
    visible: bool = True

    def __post_init__(self):
        for token in ('{z}', '{x}', '{y}'):
            if token not in self.url:
                raise ValueError(f'layer {self.name!r}: url has no {token}')
        if not 0.0 <= self.opacity <= 1.0:
            raise ValueError(f'layer {self.name!r}: opacity {self.opacity} not in 0..1')
        if not 0 <= self.min_zoom <= self.max_zoom:
            raise ValueError(f'layer {self.name!r}: zoom range {self.min_zoom}..{self.max_zoom}')

    def tile_url(self, z: int, x: int, y: int) -> str:
        return self.url.replace('{z}', str(z)).replace('{x}', str(x)).replace('{y}', str(y))


def _layers_from(text: str, source: str) -> list[Layer]:
    data = tomllib.loads(text)
    out = []
    for i, entry in enumerate(data.get('layer', [])):
        if 'name' not in entry:
            raise ValueError(f'{source}: layer {i} has no name')
        try:
            out.append(Layer(**entry))
        except (TypeError, ValueError) as e:
            # TypeError is an unknown key, ValueError a value the Layer refused;
            # both name the file, because that is where the user has to go
            raise ValueError(f'{source}: {e}') from None
    return out


def default_layers() -> list[Layer]:
    text = resources.files('danu.ui').joinpath('default-layers.toml').read_text(encoding='utf-8')
    return _layers_from(text, 'default-layers.toml')


def load_layers(user_file: Path | None = None) -> list[Layer]:
    """The defaults, with the user's file laid over them: a user layer with a
    default's name replaces it in place, keeping the order; a new name goes on
    the end. A missing user file is the ordinary case."""
    layers = default_layers()
    if user_file is None or not Path(user_file).exists():
        return layers
    user = _layers_from(Path(user_file).read_text(encoding='utf-8'), str(user_file))
    by_name = {l.name: i for i, l in enumerate(layers)}
    for layer in user:
        if layer.name in by_name:
            layers[by_name[layer.name]] = layer
        else:
            by_name[layer.name] = len(layers)
            layers.append(layer)
    return layers
