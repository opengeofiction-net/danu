"""danu.surface.params: one file, no defaults, and the shell held to it."""

from pathlib import Path

import pytest

from danu.surface import params

ROOT = Path(__file__).parents[1]


def test_the_shared_file_is_one_file_in_the_package_with_a_symlink_at_the_root():
    pkg = ROOT / 'danu' / 'params' / 'elevation.toml'
    link = ROOT / 'params' / 'elevation.toml'
    assert link.is_symlink() and link.resolve() == pkg.resolve()
    assert link.read_bytes() == pkg.read_bytes()
    # osmconf.ini is read by danu.surface.build out of the package and by
    # nothing else, so it is not installed into /etc/danu any more. A copy
    # there that the build does not read is a trap: it invites an edit that
    # changes nothing
    assert (ROOT / 'danu' / 'surface' / 'osmconf.ini').exists()
    assert not (ROOT / 'server' / 'etc' / 'osmconf.ini').exists()
    install = (ROOT / 'debian' / 'danu-server.install').read_text()
    assert 'osmconf.ini' not in install
    assert 'danu/surface/relief.ramp       etc/danu' in install   # this one is read from there


def test_the_file_loads_and_derives_what_the_shell_derives():
    p = params.load()
    assert p.arcsec == 1 and p.res == 1 / 3600
    assert p.fill_metres == 1850 and p.fill_cells == round(1850 / 30.87) == 60
    assert p.with_arcsec(3).fill_cells == round(1850 / (3 * 30.87)) == 20
    assert p.pass2 == 'diffuse' and p.dem_max_z_error == 0.05


def test_a_missing_key_is_an_error_not_a_default(tmp_path):
    f = tmp_path / 'e.toml'
    f.write_text('[grid]\narcsec = 1\n')
    with pytest.raises(KeyError, match='hgt_arcsec'):
        params.load(f)


def test_the_shell_text_is_the_file_and_the_shell_can_source_it():
    """danu-build-zone reads the parameters from here rather than carrying
    copies of them. Every line has to be a plain assignment a POSIX shell can
    source, and the values have to be the file's."""
    import subprocess
    import tomllib
    d = tomllib.loads((ROOT / 'danu' / 'params' / 'elevation.toml').read_text())
    text = params.shell_text()
    lines = text.splitlines()
    assert len(lines) == len(params.SHELL_VARIABLES)
    for (section, key), var in params.SHELL_VARIABLES.items():
        assert f'DANU_{var}={d[section][key]}' in lines, f'DANU_{var} is not the file\'s value'
    # sourced for real, not merely pattern-matched: a value needing quoting
    # would pass the check above and break the build
    out = subprocess.run(['sh', '-c', f'{text}\nprintf "%s" "$DANU_ARCSEC"'],
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout == str(d['grid']['arcsec'])


def test_the_parameters_the_surface_owns_are_not_offered_to_the_shell():
    """The fill radius, the barrier and the memory budget are the surface
    build's alone since it stopped being written twice. Emitting them here is
    how a copy gets back into danu-build-zone."""
    text = params.shell_text()
    for gone in ('FILL_METRES', 'BARRIER_CELLS', 'MAX_MEM', 'GRAD_MIN'):
        assert gone not in text
    # grad_min is held to the isofill binary's default in tests/golden, where the binary is


def test_the_library_version_this_module_wants_is_the_submodules():
    """danu.surface.isofill_lib speaks to one isofill; extern/isofill is that
    one, and its header says which. Bumping the submodule without updating
    the module - or the other way round - goes red here."""
    import re
    from danu.surface import isofill_lib
    header = (ROOT / 'extern' / 'isofill' / 'src' / 'isofill.h').read_text()
    m = re.search(r'#define ISOFILL_VERSION "([^"]+)"', header)
    assert m, 'extern/isofill/src/isofill.h no longer defines ISOFILL_VERSION'
    assert isofill_lib.EXPECTED_VERSION == m.group(1)
    m = re.search(r'#define ISOFILL_NO_ELEV \((-?\d+)\)', header)
    assert m and int(m.group(1)) == isofill_lib.NO_ELEV
