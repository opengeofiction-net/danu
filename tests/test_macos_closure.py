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


def test_a_chain_of_links_is_kept_whole(app, monkeypatch):
    """Loaded as libfoo.dylib, a link to libfoo.1.dylib, a link to the file:
    the middle link removed, the other two would point at nothing."""
    lib = app / 'lib'
    macho(lib / 'libfoo.1.2.3.dylib')
    (lib / 'libfoo.1.dylib').symlink_to('libfoo.1.2.3.dylib')
    (lib / 'libfoo.dylib').symlink_to('libfoo.1.dylib')
    macho(lib / 'libisofill.so', '@rpath/libgdal.39.dylib', '@rpath/libfoo.dylib')
    monkeypatch.setattr('sys.argv', ['closure.py', str(app), 'libisofill.so'])
    assert closure.main() == 0
    assert (lib / 'libfoo.dylib').resolve() == (lib / 'libfoo.1.2.3.dylib').resolve()
    assert (lib / 'libfoo.1.dylib').is_symlink()


def universal(path: Path, *slices: tuple[int, bytes]) -> Path:
    """A universal file of (cputype, thin Mach-O bytes) slices."""
    head = struct.pack('>2I', 0xcafebabe, len(slices))
    off, body, archs = 4096, b'', b''
    for cpu, thin in slices:
        archs += struct.pack('>5I', cpu, 0, off + len(body), len(thin), 12)
        body += thin
    path.write_bytes((head + archs).ljust(4096, b'\0') + body)
    return path


def test_a_universal_file_is_read_by_its_arm64_slice(app, monkeypatch, tmp_path):
    """conda-forge's libgcc_s is one: read as thin, its loads were nothing."""
    lib = app / 'lib'
    x86 = macho(tmp_path / 'x86', '@rpath/libtk8.6.dylib').read_bytes()
    arm = macho(tmp_path / 'arm', '@rpath/libcrypto.3.dylib', '@rpath/libgcc_s.1.1.dylib').read_bytes()
    universal(lib / 'libssl.3.dylib', (0x01000007, x86), (0x0100000c, arm))
    macho(lib / 'libgcc_s.1.1.dylib')
    assert closure.loads(lib / 'libssl.3.dylib') == ['@rpath/libcrypto.3.dylib', '@rpath/libgcc_s.1.1.dylib']
    monkeypatch.setattr('sys.argv', ['closure.py', str(app), 'libisofill.so'])
    assert closure.main() == 0
    assert (lib / 'libgcc_s.1.1.dylib').exists() and not (lib / 'libtk8.6.dylib').exists()


@pytest.mark.parametrize('spoil', ['no arm64', 'short', 'not there'])
def test_what_it_cannot_follow_stops_the_build(app, monkeypatch, capsys, spoil):
    """Rather than drop, unseen, the libraries a file it could not read loads."""
    lib = app / 'lib'
    if spoil == 'no arm64':
        universal(lib / 'libssl.3.dylib', (0x01000007, (lib / 'libssl.3.dylib').read_bytes()))
        name = 'libisofill.so'
    elif spoil == 'short':
        (lib / 'libssl.3.dylib').write_bytes((lib / 'libssl.3.dylib').read_bytes()[:40])
        name = 'libisofill.so'
    else:
        name = 'libnothere.so'
    monkeypatch.setattr('sys.argv', ['closure.py', str(app), name])
    assert closure.main() == 1
    assert capsys.readouterr().err
    assert (lib / 'libtk8.6.dylib').exists(), 'removed anything after failing'
