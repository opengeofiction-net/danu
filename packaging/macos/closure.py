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
LOADS = {0xc, 0x80000018, 0x8000001f, 0x20, 0x80000023}   # LOAD, WEAK, REEXPORT, LAZY, UPWARD


def is_macho(p: Path) -> bool:
    try:
        with open(p, 'rb') as f:
            return struct.unpack('<I', f.read(4))[0] == MAGIC_64
    except (OSError, struct.error):
        return False


def loads(p: Path) -> list[str]:
    """The libraries a thin 64-bit Mach-O file loads, by the names it gives."""
    data = p.read_bytes()
    _magic, _cpu, _sub, _ftype, ncmds, _size, _flags, _res = struct.unpack_from('<8I', data, 0)
    off, out = 32, []
    for _ in range(ncmds):
        cmd, size = struct.unpack_from('<2I', data, off)
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
    roots += [lib / n for n in extra]
    keep, missing, todo = set(extra), [], list(roots)
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
            keep.add(leaf)
            real = target.resolve()
            keep.add(real.name)
            todo.append(real)
    return keep, sorted(set(missing))


def main() -> int:
    res, extra = Path(sys.argv[1]), sys.argv[2:]
    keep, missing = closure(res, extra)
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
