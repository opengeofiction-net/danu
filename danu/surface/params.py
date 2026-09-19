"""The parameters the build and the editor share, from one file.

``danu/params/elevation.toml`` is the file, in a package that holds data and
no code so the file installs with the wheel; the code that reads it is here.
``params/elevation.toml`` at the repository root is a symlink to it so the golden test and a reader of the tree
find it where the spec says. There are no defaults here: a key the file lacks
is an error, so the editor cannot quietly assume a value the shell did not.

The shell does not read this file yet. ``danu-build-zone`` carries the same
values as ``${VAR:-default}`` constants, and ``shell_defaults`` reads them back
out so a test can hold the two to each other until the shell reads the file
itself - a change to the build, deferred while phase 0's soak runs against it.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, replace
from importlib import resources
from pathlib import Path

# toml key -> the shell's variable, for every parameter the shell holds as a
# ${VAR:-default}; the test holds the two equal
SHELL_VARIABLES = {
    ('grid', 'arcsec'): 'ARCSEC',
    ('grid', 'hgt_arcsec'): 'HGT_ARCSEC',
    ('fill', 'metres'): 'FILL_METRES',
    ('fill', 'barrier_cells'): 'BARRIER_CELLS',
    ('memory', 'max_mem_mb'): 'MAX_MEM',
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
        """Cell size in degrees. shell: RES=$(python3 -c "print(${ARCSEC}/3600)")"""
        return self.arcsec / 3600

    @property
    def fill_cells(self) -> int:
        """The fill's reach in cells, from a distance in metres, so changing
        arcsec does not silently change how far it looks.
        shell: FILL_CELLS=$(python3 -c "print(max(1, round(${FILL_METRES} / (${ARCSEC} * 30.87))))")"""
        return max(1, round(self.fill_metres / (self.arcsec * 30.87)))

    def with_arcsec(self, arcsec: float) -> 'Params':
        """The resolution is the one parameter the shell takes from its
        environment rather than its constants - the golden reference is built
        at 3 arcseconds so it stays committable - and the editor takes it the
        same way."""
        return replace(self, arcsec=float(arcsec))


def _require(data: dict, *path):
    node = data
    for key in path:
        if not isinstance(node, dict) or key not in node:
            raise KeyError(f'elevation.toml: no [{path[0]}] {".".join(path[1:])}')
        node = node[key]
    return node


def load(path: Path | None = None) -> Params:
    if path is None:
        text = resources.files('danu.params').joinpath('elevation.toml').read_text(encoding='utf-8')
    else:
        text = Path(path).read_text(encoding='utf-8')
    d = tomllib.loads(text)
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


def shell_defaults(script: Path) -> dict[str, str]:
    """Every ``NAME=${NAME:-value}`` in a shell script, name to value."""
    out = {}
    for m in re.finditer(r'^\s*([A-Z_]+)=\$\{\1:-([^}]*)\}', Path(script).read_text(), re.M):
        out[m.group(1)] = m.group(2)
    return out
