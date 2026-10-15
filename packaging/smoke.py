"""The installed Danu, run as a mapper's machine would run it: from its own
tree, with nothing of MSYS2, conda or the build on PATH.

    <installed>\\bin\\python.exe smoke.py SQUARE EXPECTED WORK      (Windows)
    danu-<version>-x86_64.AppImage --python smoke.py SQUARE EXPECTED WORK

Imports what the editor imports, from the tree; builds the golden square's
surface with the bundled GDAL, twice - through the bundled isofill library,
and through the bundled binary, which the editor runs for a raster too big to
hold - and holds each to the reference the server's pipeline made, cell for
cell: the check the golden suite makes, made of the installed copy. And a
fault in C, made in a child of the installed Python, written down and found
by the next start as the editor would find it (J6). Exits non-zero on any
difference.
"""

import shutil
import subprocess
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
    # each dataset held by a name while its band is read: chained, the
    # dataset is freed under the band
    ref_ds = gdal.Open(str(expected))
    a = ref_ds.GetRasterBand(1).ReadAsArray()
    exe = here / 'bin' / ('isofill.exe' if sys.platform == 'win32' else 'isofill')
    for library, said in ((True, 'as a library'), (False, 'as the binary')):
        lines: list[str] = []
        result = build.build_dem(zone, work / ('build-library' if library else 'build-binary'), params.load().with_arcsec(3.0),
                                 isofill=str(exe), log=lines.append, library=library)
        print('\n'.join(lines))
        check(result.dem is not None, 'no DEM')
        check(any(said in line for line in lines), f'isofill was not called {said}')
        new_ds = gdal.Open(str(result.dem))
        b = new_ds.GetRasterBand(1).ReadAsArray()
        check(a.shape == b.shape, f'reference {a.shape}, built {b.shape}')
        differing = int((a != b).sum())
        check(differing == 0, f'{differing} of {a.size} cells differ; worst {np.abs(a - b).max():.3f} m')
        print(f'the installed Danu built the golden square with isofill {said}: all {a.size} cells the reference\'s')
    crashed(work / 'crashes')
    return 0


FAULT = '''
import faulthandler, sys
from pathlib import Path
from danu.ui import crash
crash.Reporter(Path(sys.argv[1])).install()
faulthandler._sigsegv()
'''


def crashed(directory: Path) -> None:
    """A segfault leaves a report the next start offers."""
    from danu.ui import crash
    done = subprocess.run([sys.executable, '-c', FAULT, str(directory)], capture_output=True, timeout=120)
    check(done.returncode != 0, 'the fault did not end the child')
    reports = crash.Reporter(directory).earlier()
    check(len(reports) == 1, f'{len(reports)} reports of the fault; {done.stderr.decode(errors="replace")[-500:]}')
    check('Segmentation fault' in reports[0].trace and 'in <module>' in reports[0].trace,
          f'the report: {reports[0].trace[:500]}')
    print(f'a fault in C was written down and offered at the next start: {reports[0].path}')


if __name__ == '__main__':
    sys.exit(main())
