#!/bin/bash
# The tree the Windows packages install, built in MSYS2's UCRT64 shell from
# the packages CI's windows-stack job tests:
#
#   bash packaging/windows/build-tree.sh OUT
#
# OUT/Danu is laid out as MSYS2's /ucrt64 is - bin, lib/python3.14,
# share/qt6/plugins, share/gdal, share/proj - because Python and Qt each find
# their own files relative to where their DLLs are, so a tree shaped like the
# prefix needs no configuration to run. What goes in is what Danu imports and
# no more: Python and its standard library less the parts nothing uses,
# PySide6, GDAL's bindings and numpy; the Qt plugins a window on Windows
# loads; and then every DLL any of those links, found by ntldd, rather than a
# copy of /ucrt64/bin. isofill is built against the same GDAL, and Danu.exe is
# the launcher.
set -euo pipefail

OUT=${1:?usage: build-tree.sh OUT}
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
PREFIX=${MINGW_PREFIX:-/ucrt64}
PY=$(python3 -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')
T=$OUT/Danu

[ ! -e "$T" ] || { echo "$T exists; give an empty OUT" >&2; exit 1; }
mkdir -p "$T/bin" "$T/lib" "$T/share/qt6"

# Python: the interpreters, the standard library less what nothing here uses,
# and of site-packages only what Danu imports
cp "$PREFIX"/bin/python.exe "$PREFIX"/bin/pythonw.exe "$PREFIX"/bin/python3.exe "$T/bin/"
cp "$PREFIX"/bin/lib"$PY".dll "$T/bin/"
mkdir -p "$T/lib/$PY/site-packages"
(cd "$PREFIX/lib/$PY" && tar -cf - \
	--exclude=./site-packages --exclude=./test --exclude=./idlelib --exclude=./tkinter \
	--exclude=./turtledemo --exclude=./ensurepip --exclude=./venv --exclude=./pydoc_data \
	--exclude='./config-*' --exclude='*/tests' .) | (cd "$T/lib/$PY" && tar -xf -)
for pkg in PySide6 shiboken6 osgeo numpy; do
	cp -r "$PREFIX/lib/$PY/site-packages/$pkg" "$T/lib/$PY/site-packages/"
done
# PySide6's tools and the translations nothing here reads
rm -rf "$T/lib/$PY/site-packages/PySide6/"{examples,include,glue,typesystems,scripts}
# Danu itself, as the source has it: pure Python and its package data
(cd "$ROOT" && tar -cf - --exclude=__pycache__ danu) | (cd "$T/lib/$PY/site-packages" && tar -xf -)

# Qt's plugins: a window on Windows, the images and icons it draws, TLS for
# the tiles and the sign-in, and the network state Qt asks about
for d in platforms imageformats iconengines styles tls networkinformation; do
	[ -d "$PREFIX/share/qt6/plugins/$d" ] && mkdir -p "$T/share/qt6/plugins" && \
		cp -r "$PREFIX/share/qt6/plugins/$d" "$T/share/qt6/plugins/"
done
# GDAL's and PROJ's data: the CRS database and the driver tables
cp -r "$PREFIX/share/gdal" "$PREFIX/share/proj" "$T/share/"

# isofill, built here against the GDAL being shipped
make -C "$ROOT/extern/isofill" isofill libisofill.dll >/dev/null
cp "$ROOT/extern/isofill/isofill.exe" "$ROOT/extern/isofill/libisofill.dll" "$T/bin/"

# the launcher, with the icon in it
windres --include-dir "$ROOT/packaging/windows" "$ROOT/packaging/windows/launcher.rc" -O coff -o "$OUT/launcher.res"
gcc -O2 -municode -mwindows -o "$T/Danu.exe" "$ROOT/packaging/windows/launcher.c" "$OUT/launcher.res"

# Every DLL anything in the tree links, from the prefix, until nothing new is
# found. ntldd -R walks the whole chain of each; the loop is for the DLLs a
# copied DLL brings in that were not linked by what was there before.
prefix_win=$(cygpath -m "$PREFIX/bin" | tr '[:upper:]' '[:lower:]')
while :; do
	new=0
	while IFS= read -r dll; do
		name=$(basename "$dll")
		if [ ! -e "$T/bin/$name" ]; then
			cp "$dll" "$T/bin/"
			new=$((new + 1))
		fi
	done < <(find "$T" \( -iname '*.dll' -o -iname '*.exe' -o -iname '*.pyd' \) -print0 |
		xargs -0 ntldd -R 2>/dev/null |
		sed -nE 's/^\s*\S+ => (.*\.dll) \(0x[0-9a-f]+\)\s*$/\1/Ip' |
		tr '\\' '/' | while IFS= read -r p; do
			case "$(echo "$p" | tr '[:upper:]' '[:lower:]')" in
				"$prefix_win"/*) cygpath -u "$p" ;;
			esac
		done | sort -u)
	echo "  $new DLLs from $PREFIX/bin"
	[ "$new" -eq 0 ] && break
done

# compiled once, here, rather than on a mapper's first start from a directory
# they may not be able to write
"$T/bin/python.exe" -m compileall -q -j 0 "$T/lib/$PY" >/dev/null || true

echo "tree: $(du -sh "$T" | cut -f1) in $(find "$T" -type f | wc -l) files"
