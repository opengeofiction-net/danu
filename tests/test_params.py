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
    osm_pkg = ROOT / 'danu' / 'surface' / 'osmconf.ini'
    osm_link = ROOT / 'server' / 'etc' / 'osmconf.ini'
    assert osm_link.is_symlink() and osm_link.resolve() == osm_pkg.resolve()
    install = (ROOT / 'debian' / 'danu-server.install').read_text()
    assert 'danu/surface/osmconf.ini' in install and 'server/etc/osmconf.ini' not in install


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


def test_the_shell_holds_the_same_values_as_the_file():
    """danu-build-zone does not read the file yet; its ${VAR:-default}
    constants must equal it, or the two paths start from different numbers.
    When the shell reads the file this test becomes unnecessary and goes."""
    p = params.load()
    shell = params.shell_defaults(ROOT / 'server' / 'bin' / 'danu-build-zone')
    import tomllib
    d = tomllib.loads((ROOT / 'danu' / 'params' / 'elevation.toml').read_text())
    for (section, key), var in params.SHELL_VARIABLES.items():
        assert var in shell, f'{var} is not a ${{{var}:-default}} in danu-build-zone'
        assert float(shell[var]) == float(d[section][key]), \
            f'{var}={shell[var]} in the shell, [{section}] {key} = {d[section][key]} in the file'
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
