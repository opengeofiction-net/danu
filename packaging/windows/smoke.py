"""The installed Danu, run as a mapper's machine would run it: from its own
tree, with nothing of MSYS2 or of the build on PATH.

    <installed>\\bin\\python.exe smoke.py SQUARE EXPECTED WORK

Imports what the editor imports, from the tree; builds the golden square's
surface with the bundled GDAL and the bundled isofill library, and holds it to
the reference the server's pipeline made, cell for cell - the check the golden
suite makes, made of the installed copy. Exits non-zero on any difference.
"""

import shutil
import sys
from pathlib import Path


def check(ok: bool, what: str) -> None:
    """An assert that python -O cannot take out: this exists to fail."""
    if not ok:
        raise SystemExit(f'smoke: {what}')


def main() -> int:
    check(len(sys.argv) == 4, 'usage: smoke.py SQUARE EXPECTED WORK')
    square, expected, work = (Path(a) for a in sys.argv[1:4])
    check(not work.exists(), f'{work} exists; give a WORK that does not, so nothing in it is stale')
    import danu
    from danu.ui import about
    here = Path(sys.executable).resolve().parents[1]
    check(Path(danu.__file__).resolve().is_relative_to(here), f'danu from {danu.__file__}, not the tree at {here}')
    v = about.versions()
    print(about.text(v))
    check(v['gdal'][0].isdigit(), f"gdal: {v['gdal']}")
    check(v['isofill'].startswith('0.'), f"isofill: {v['isofill']}")

    import numpy as np
    from osgeo import gdal

    from danu.surface import build, params
    zone = work / 'golden'
    zone.mkdir(parents=True)
    shutil.copy(square, zone / square.name)
    lines: list[str] = []
    result = build.build_dem(zone, work / 'build', params.load().with_arcsec(3.0), log=lines.append, library=True)
    print('\n'.join(lines))
    check(result.dem is not None, 'no DEM')
    check(any('as a library' in line for line in lines), 'isofill was not called as the library')
    ref_ds, new_ds = gdal.Open(str(expected)), gdal.Open(str(result.dem))
    a = ref_ds.GetRasterBand(1).ReadAsArray()
    b = new_ds.GetRasterBand(1).ReadAsArray()
    check(a.shape == b.shape, f'reference {a.shape}, built {b.shape}')
    differing = int((a != b).sum())
    check(differing == 0, f'{differing} of {a.size} cells differ; worst {np.abs(a - b).max():.3f} m')
    print(f'the installed Danu built the golden square: all {a.size} cells the reference\'s')
    return 0


if __name__ == '__main__':
    sys.exit(main())
