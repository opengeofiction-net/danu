"""The parameters the build and the editor share, from one file.

``danu/params/elevation.toml`` is the file, in a package that holds data and no
code so the file installs with the wheel; the code that reads it is here.
``params/elevation.toml`` at the repository root is a symlink to it so the
golden test and a reader of the tree find it where the spec says. There are no
defaults here: a key the file lacks is an error, so no caller can quietly assume
a value another did not.

``danu-build-zone`` reads the file through ``--shell`` below rather than
carrying its own copy of the values. Most of them are the surface build's and
never reach the shell at all; the three it still needs are the ones the stages
after the DEM use.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path

# What danu-build-zone still needs, after the stages up to the DEM moved into
# danu.surface.build: the resolution it passes back in and derives its metre
# spacings from, the 3 arcsecond spacing of the derivative and the .hgt archive,
# and the hillshade's box filter. The fill's radius, the barrier and the memory
# budget are not here because the shell no longer has anything to do with them.
SHELL_VARIABLES = {
    ('grid', 'arcsec'): 'ARCSEC',
    ('grid', 'hgt_arcsec'): 'HGT_ARCSEC',
    ('smooth', 'cells'): 'SMOOTH_CELLS',
}


@dataclass(frozen=True)
class Params:
    arcsec: float
    hgt_arcsec: float
    fill_metres: float
    barrier_cells: int
    grad_min: float
    pass2: str
    max_mem_mb: int
    smooth_cells: int
    dem_compress: str
    dem_max_z_error: float
    dem_zstd_level: int

    @property
    def res(self) -> float:
        """Cell size in degrees."""
        return self.arcsec / 3600

    @property
    def fill_cells(self) -> int:
        """The fill's reach in cells, from a distance in metres, so changing
        arcsec does not silently change how far it looks. 1850 m is the old
        process's radius of 20 cells at 3 arcseconds, and holds that distance at
        1 arcsecond as 60 cells. Beyond it a cell has no elevation information of
        its own and takes what the second pass carries in."""
        return max(1, round(self.fill_metres / (self.arcsec * 30.87)))

    def with_arcsec(self, arcsec: float) -> 'Params':
        """The resolution is the one parameter a caller passes rather than
        taking from the file: the golden reference is built at 3 arcseconds so
        it stays committable, and the editor and the shell both override it the
        same way."""
        return replace(self, arcsec=float(arcsec))


def _require(data: dict, *path):
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise KeyError(f'elevation.toml: no [{path[0]}] {".".join(path[1:])}')
        node = node[key]
    return node


def _text(path: Path | None) -> str:
    if path is None:
        return resources.files('danu.params').joinpath('elevation.toml').read_text(encoding='utf-8')
    return Path(path).read_text(encoding='utf-8')


def load(path: Path | None = None) -> Params:
    d = tomllib.loads(_text(path))
    return Params(
        arcsec=float(_require(d, 'grid', 'arcsec')),
        hgt_arcsec=float(_require(d, 'grid', 'hgt_arcsec')),
        fill_metres=float(_require(d, 'fill', 'metres')),
        barrier_cells=int(_require(d, 'fill', 'barrier_cells')),
        grad_min=float(_require(d, 'fill', 'grad_min')),
        pass2=str(_require(d, 'fill', 'pass2')),
        max_mem_mb=int(_require(d, 'memory', 'max_mem_mb')),
        smooth_cells=int(_require(d, 'smooth', 'cells')),
        dem_compress=str(_require(d, 'publish', 'dem_compress')),
        dem_max_z_error=float(_require(d, 'publish', 'dem_max_z_error')),
        dem_zstd_level=int(_require(d, 'publish', 'dem_zstd_level')),
    )


def shell_text(path: Path | None = None) -> str:
    """The file as shell assignments, for a script to source.

    Prefixed ``DANU_``, and the script writes ``ARCSEC=${ARCSEC:-${DANU_ARCSEC}}``
    rather than taking these directly, so an environment override still wins -
    which is how the golden reference is built at 3 arcseconds."""
    d = tomllib.loads(_text(path))
    out = []
    for (section, key), var in SHELL_VARIABLES.items():
        value = _require(d, section, key)
        out.append(f'DANU_{var}={value}')
    return '\n'.join(out) + '\n'


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog='python -m danu.surface.params',
                                 description='the shared parameters, for a shell to source')
    ap.add_argument('--shell', action='store_true', help='emit DANU_NAME=value assignments')
    ap.add_argument('--params', type=Path, help='an elevation.toml other than the packaged one')
    args = ap.parse_args(argv)
    if not args.shell:
        ap.error('nothing to do: pass --shell')
    print(shell_text(args.params), end='')
    return 0


if __name__ == '__main__':
    import sys
    sys.exit(main())
