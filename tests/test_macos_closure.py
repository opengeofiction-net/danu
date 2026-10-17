"""packaging/macos/closure.py (#194): the libraries Danu.app's programs load,
followed from its roots, and the rest of its lib removed - read from the
Mach-O load commands, so it is tested here on Mach-O files made for it."""

import importlib.util
import struct
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    'closure', Path(__file__).parents[1] / 'packaging' / 'macos' / 'closure.py')
closure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(closure)


def macho(path: Path, *loads: str) -> Path:
    """A thin 64-bit Mach-O file loading each of ``loads``, as LC_LOAD_DYLIB."""
    cmds = b''
    for name in loads:
        raw = name.encode() + b'\0'
        raw += b'\0' * (-(24 + len(raw)) % 8)
        cmds += struct.pack('<6I', 0xc, 24 + len(raw), 24, 0, 0, 0) + raw
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(struct.pack('<8I', 0xfeedfacf, 0x0100000c, 0, 2, len(loads), len(cmds), 0, 0) + cmds)
    return path


@pytest.fixture
def app(tmp_path):
    res = tmp_path / 'Danu.app' / 'Contents' / 'Resources'
    lib = res / 'lib'
    macho(tmp_path / 'Danu.app' / 'Contents' / 'MacOS' / 'Danu', '@rpath/libpython3.14.dylib',
          '/usr/lib/libSystem.B.dylib')
    macho(res / 'bin' / 'python3.14')
    macho(lib / 'python3.14' / 'lib-dynload' / '_ssl.so', '@rpath/libssl.3.dylib')
    macho(lib / 'qt6' / 'plugins' / 'platforms' / 'libqcocoa.dylib', '@rpath/libQt6Core.6.dylib')
    macho(lib / 'libpython3.14.dylib')
    macho(lib / 'libssl.3.dylib', '@rpath/libcrypto.3.dylib')
    macho(lib / 'libcrypto.3.dylib')
    macho(lib / 'libQt6Core.6.11.2.dylib', '@rpath/libicuuc.78.dylib')
    (lib / 'libQt6Core.6.dylib').symlink_to('libQt6Core.6.11.2.dylib')
    macho(lib / 'libicuuc.78.dylib')
    macho(lib / 'libisofill.so', '@rpath/libgdal.39.dylib')
    macho(lib / 'libgdal.39.dylib')
    macho(lib / 'libtk8.6.dylib')                     # nothing loads it
    (lib / 'notes.txt').write_text('not a library')
    return res


def test_what_is_loaded_is_kept_and_the_rest_removed(app, monkeypatch):
    monkeypatch.setattr('sys.argv', ['closure.py', str(app), 'libisofill.so'])
    assert closure.main() == 0
    left = sorted(p.name for p in (app / 'lib').iterdir() if not p.is_dir())
    assert left == ['libQt6Core.6.11.2.dylib', 'libQt6Core.6.dylib', 'libcrypto.3.dylib', 'libgdal.39.dylib',
                    'libicuuc.78.dylib', 'libisofill.so', 'libpython3.14.dylib', 'libssl.3.dylib']
    assert (app / 'lib' / 'qt6' / 'plugins' / 'platforms' / 'libqcocoa.dylib').exists(), 'a directory was touched'


def test_a_library_named_by_a_path_that_will_not_be_there_fails_the_build(app, monkeypatch, capsys):
    """conda's ncurses names its libraries by the path it was built at: kept,
    the app would not start on a mapper's Mac."""
    macho(app / 'lib' / 'libssl.3.dylib', '/Users/runner/work/_temp/env/lib/libcrypto.3.dylib')
    monkeypatch.setattr('sys.argv', ['closure.py', str(app), 'libisofill.so'])
    assert closure.main() == 1
    assert '/Users/runner/work/_temp/env/lib/libcrypto.3.dylib' in capsys.readouterr().err
    assert (app / 'lib' / 'libtk8.6.dylib').exists(), 'removed anything after failing'


def test_what_a_file_loads_is_read_from_its_load_commands(tmp_path):
    p = macho(tmp_path / 'x', '@rpath/a.dylib', '/usr/lib/libz.1.dylib', '@rpath/b.dylib')
    assert closure.is_macho(p) and not closure.is_macho(tmp_path)
    assert closure.loads(p) == ['@rpath/a.dylib', '/usr/lib/libz.1.dylib', '@rpath/b.dylib']
