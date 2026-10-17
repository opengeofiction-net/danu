"""The libraries an app's programs need, and the rest of its lib removed.

    python3 closure.py RES [LIB...]

RES is the app's Contents/Resources: a conda environment already cut to
what is shipped everywhere but its top-level lib. Every Mach-O file outside
that lib - the interpreter, the extension modules, the Qt plugins, isofill -
and Contents/MacOS/Danu beside it are roots; the libraries they load, named
@rpath/NAME and found as RES/lib/NAME, are followed until nothing new turns
up, as packaging/linux/closure.py follows DT_NEEDED. What is left in RES/lib
after that is removed; directories under it are left alone. Each LIB named
is a library in RES/lib that is a root itself: one loaded by name at run
time, as libisofill is through ctypes, which nothing links.

conda-forge's libraries name each other @rpath/NAME and find each other by
an rpath of @loader_path, so a library kept is found wherever the app is.
The load commands are read here rather than by otool so that this runs, and
is tested, anywhere.
"""

import struct
import sys
from pathlib import Path

MAGIC_64 = 0xfeedfacf
FAT, FAT_64 = 0xcafebabe, 0xcafebabf          # universal, read big-endian
ARM64 = 0x0100000c
LOADS = {0xc, 0x80000018, 0x8000001f, 0x20, 0x80000023}   # LOAD, WEAK, REEXPORT, LAZY, UPWARD


class NotThin(Exception):
    """A Mach-O file this cannot read: cut short, or universal with no arm64
    in it. Its libraries would be dropped unseen, so it stops the build."""


def is_macho(p: Path) -> bool:
    try:
        with open(p, 'rb') as f:
            head = f.read(4)
    except OSError:
        return False
    return len(head) == 4 and (struct.unpack('<I', head)[0] == MAGIC_64
                               or struct.unpack('>I', head)[0] in (FAT, FAT_64))


def arm64(p: Path, data: bytes) -> bytes:
    """The arm64 slice of a universal file - conda-forge ships a few, its
    libgcc_s among them - or the file itself if it is thin."""
    try:
        magic, n = struct.unpack_from('>2I', data, 0)
    except struct.error:
        raise NotThin(f'{p}: cut short') from None
    if magic not in (FAT, FAT_64):
        return data
    wide = magic == FAT_64
    for i in range(n):
        if wide:
            cpu, _sub, off, size, _align, _res = struct.unpack_from('>2I2Q2I', data, 8 + i * 32)
        else:
            cpu, _sub, off, size, _align = struct.unpack_from('>5I', data, 8 + i * 20)
        if cpu == ARM64:
            return data[off:off + size]
    raise NotThin(f'{p}: universal, with no arm64 in it')


def loads(p: Path) -> list[str]:
    """The libraries a 64-bit Mach-O file loads, by the names it gives - its
    arm64 slice's, if it is universal."""
    data = arm64(p, p.read_bytes())
    try:
        magic, _cpu, _sub, _ftype, ncmds, _size, _flags, _res = struct.unpack_from('<8I', data, 0)
    except struct.error:
        raise NotThin(f'{p}: cut short') from None
    if magic != MAGIC_64:
        raise NotThin(f'{p}: loaded, and not a thin 64-bit Mach-O file')
    off, out = 32, []
    for _ in range(ncmds):
        if off + 8 > len(data):
            raise NotThin(f'{p}: cut short')
        cmd, size = struct.unpack_from('<2I', data, off)
        if size < 8 or off + size > len(data):
            raise NotThin(f'{p}: a load command of {size} bytes at {off}')
        if cmd in LOADS:
            name_off = struct.unpack_from('<I', data, off + 8)[0]
            raw = data[off + name_off:off + size]
            out.append(raw.split(b'\0', 1)[0].decode())
        off += size
    return out


def closure(res: Path, extra: list[str]) -> tuple[set[str], list[str]]:
    """The names in RES/lib that something kept loads, and those it loads that
    are not there - which, being neither the system's nor the app's, would
    stop it starting."""
    lib = res / 'lib'
    roots = [p for p in res.rglob('*') if p.is_file() and not p.is_symlink() and p.parent != lib and is_macho(p)]
    roots += [p for p in (res.parent / 'MacOS').glob('*') if is_macho(p)]
    keep, missing = set(), []
    for n in extra:
        if (lib / n).exists():
            keep.update(chain(lib, n))
            roots.append((lib / n).resolve())
        else:
            missing.append(n)
    todo = list(roots)
    while todo:
        for name in loads(todo.pop()):
            if not name.startswith('@rpath/'):
                if not name.startswith(('/usr/lib/', '/System/')):
                    missing.append(name)
                continue
            leaf = name[len('@rpath/'):]
            if leaf in keep:
                continue
            target = lib / leaf
            if not target.exists():
                missing.append(name)
                continue
            keep.update(chain(lib, leaf))
            todo.append(target.resolve())
    return keep, sorted(set(missing))


def chain(lib: Path, name: str) -> list[str]:
    """``name`` and every link it goes through in lib to the file itself -
    libfoo.dylib, libfoo.1.dylib, libfoo.1.2.3.dylib - so none of the chain
    is removed from under the others."""
    out, p = [], lib / name
    while True:
        out.append(p.name)
        if not p.is_symlink():
            return out
        p = p.parent / p.readlink()            # one step, not resolve(): that is the whole chain
        if p.parent != lib:
            return out


def main() -> int:
    res, extra = Path(sys.argv[1]), sys.argv[2:]
    try:
        keep, missing = closure(res, extra)
    except NotThin as e:
        print(f'closure: {e}', file=sys.stderr)
        return 1
    if missing:
        print('closure: loaded and not in the app:', *missing, sep='\n  ', file=sys.stderr)
        return 1
    lib = res / 'lib'
    gone = 0
    for p in lib.iterdir():
        if p.is_dir() and not p.is_symlink():
            continue
        if p.name not in keep:
            p.unlink()
            gone += 1
    print(f'closure: kept {len(keep)} libraries, removed {gone}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
