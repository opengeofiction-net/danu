"""The libraries an AppDir's programs need, and the rest of its lib removed.

    python3 closure.py USR [LIB...]

USR is the AppDir's usr, a conda environment already cut to what is shipped
everywhere but its top-level lib. Every ELF file outside that lib - the
interpreter, the extension modules, the Qt plugins, isofill - is a root; the
libraries they link, by DT_NEEDED and found in USR/lib, are followed until
nothing new turns up, as build-tree.sh follows ntldd on Windows. What is left
in USR/lib after that is removed; directories under it are left alone.
Each LIB named is a library in USR/lib that is a root itself: one loaded by
name at run time, as libisofill is through ctypes, which nothing links.

The display driver's own libraries are left to the machine even when linked:
they belong with the driver the machine has. OpenGL's are not: what Qt links
is libglvnd, which only dispatches to the driver the machine names, and a
machine without it - a container, a server - would otherwise not start the
editor at all, where the editor draws without OpenGL.

Then every ELF file kept is asked which glibc it needs, and one that needs a
newer glibc than conda-forge builds against fails the build: the image runs
on no older machine than its most demanding file does.
"""

import re
import subprocess
import sys
from pathlib import Path

GLIBC_FLOOR = (2, 17)
HOST = re.compile(r'^lib(gbm|drm(_\w+)?)\.so')


def is_elf(p: Path) -> bool:
    try:
        with open(p, 'rb') as f:
            return f.read(4) == b'\x7fELF'
    except OSError:
        return False


def needed(p: Path) -> list[str]:
    out = subprocess.run(['readelf', '-d', str(p)], capture_output=True, text=True, check=True).stdout
    return re.findall(r'\(NEEDED\)\s+Shared library: \[([^\]]+)\]', out)


def main() -> int:
    usr = Path(sys.argv[1]).resolve()
    lib = usr / 'lib'
    roots = [p for p in usr.rglob('*')
             if p.is_file() and not p.is_symlink() and p.parent != lib and is_elf(p)]
    for n in sys.argv[2:]:
        if not (lib / n).is_file():
            raise SystemExit(f'closure: {lib / n} is not there')
    roots += [lib / n for n in sys.argv[2:]]
    keep: set[str] = set(sys.argv[2:])
    todo = list(roots)
    while todo:
        for name in needed(todo.pop()):
            if name in keep or HOST.match(name) or not (lib / name).exists():
                continue
            keep.add(name)
            todo.append((lib / name).resolve())
    # a kept name is often a symlink to the versioned file; both stay
    files = keep | {(lib / n).resolve().name for n in keep}
    removed = 0
    for p in lib.iterdir():
        if p.is_dir() and not p.is_symlink():
            continue
        if p.name not in files:
            p.unlink()
            removed += 1
    print(f'  {len(roots)} programs and modules link {len(keep)} libraries; {removed} files of lib removed')
    newer = []
    for p in roots + [lib / n for n in files if not (lib / n).is_symlink()]:
        out = subprocess.run(['readelf', '-V', str(p)], capture_output=True, text=True, check=True).stdout
        want = max((tuple(map(int, v.split('.'))) for v in re.findall(r'Name: GLIBC_([0-9.]+)', out)), default=(0,))
        if want > GLIBC_FLOOR:
            newer.append(f'{p.relative_to(usr)} needs glibc {".".join(map(str, want))}')
    if newer:
        raise SystemExit('closure: newer than glibc %d.%d:\n  ' % GLIBC_FLOOR + '\n  '.join(newer))
    return 0


if __name__ == '__main__':
    sys.exit(main())
