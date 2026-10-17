#!/bin/bash
# Danu.app, for Apple Silicon (#194): Danu with its own Python, PySide6, GDAL
# and numpy from conda-forge - the versions in packaging/stack.txt, the
# AppImage's and Windows' - and isofill built against that GDAL, packed in a
# .dmg:
#
#   bash packaging/macos/build-app.sh OUT [VERSION]
#
# OUT/Danu.app is the environment as conda-forge lays it out, under
# Contents/Resources, cut as the AppImage's is: the standard library less
# what nothing imports, of site-packages the four packages, of PySide6 the
# four modules the editor imports, the Qt plugins a window on macOS loads,
# GDAL's and PROJ's data, and of the environment's libraries those that
# something kept loads, found by closure.py. Contents/MacOS/Danu is
# launcher.c, which runs the editor with that Python in its own process -
# see there why. The app is signed ad hoc: Apple Silicon runs no code that
# is not signed, and an unsigned app is what was agreed (#194). With
# VERSION, it is then packed as OUT/danu-VERSION-macos-arm64.dmg.
#
# MICROMAMBA is the micromamba to use (default: the one on PATH).
set -euo pipefail

OUT=${1:?usage: build-app.sh OUT [VERSION]}
VERSION=${2:-}
case $VERSION in *[!0-9A-Za-z.+~-]*) echo "version $VERSION: letters, digits and .+~- only" >&2; exit 1 ;; esac
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HERE=$ROOT/packaging/macos
MM=${MICROMAMBA:-micromamba}
APP=$OUT/Danu.app
C=$APP/Contents
R=$C/Resources

[ ! -e "$APP" ] || { echo "$APP exists; give an empty OUT" >&2; exit 1; }
mkdir -p "$C/MacOS"
export MAMBA_ROOT_PREFIX=$OUT/mamba

# the stack, with the OpenMP runtime isofill is built against
spec=$(grep -v '^#' "$ROOT/packaging/stack.txt")
# shellcheck disable=SC2086
"$MM" create -q -y -p "$R" -c conda-forge --override-channels $spec llvm-openmp
PY=$("$R/bin/python3" -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')

# isofill, against the GDAL being shipped, by the system's clang, which has
# no OpenMP of its own: the environment's libomp, through the preprocessor.
# Each finds its libraries beside it wherever the app is. No fused
# multiply-add, which isofill's Makefile sees to (isofill #14). Built from a
# copy, so the checkout's own build is left as it was
mkdir "$OUT/isofill"
cp -r "$ROOT/extern/isofill/Makefile" "$ROOT/extern/isofill/src" "$OUT/isofill/"
PATH="$R/bin:$PATH" make -C "$OUT/isofill" isofill libisofill.so CC=cc \
	OPENMP="-Xpreprocessor -fopenmp -I$R/include -L$R/lib -lomp" \
	LDFLAGS="-Wl,-rpath,@loader_path/../lib -Wl,-rpath,@loader_path" >/dev/null
cp "$OUT/isofill/isofill" "$R/bin/"
cp "$OUT/isofill/libisofill.so" "$R/lib/"

# the launcher, against the app's libpython, found from Contents/MacOS
cc -O2 -Wall -Wextra -I"$R/include/$PY" -o "$C/MacOS/Danu" "$HERE/launcher.c" \
	-L"$R/lib" -l"$PY" -Wl,-rpath,@executable_path/../Resources/lib

# of bin, the interpreter and isofill
find "${R:?}/bin" -mindepth 1 \( -name isofill -o -name python3 -o -name python -o -name "$PY" \) -prune -o -print0 |
	xargs -0 rm -rf

# the standard library less what nothing here uses - curses and readline
# among it, for a terminal, whose ncurses names its libraries by the path it
# was built at - and of site-packages only what Danu imports
P=$R/lib/$PY
rm -rf "${P:?}"/{test,idlelib,tkinter,turtledemo,ensurepip,venv,pydoc_data,lib2to3,curses}
rm -rf "${P:?}"/config-* "${P:?}"/lib-dynload/_curses* "${P:?}"/lib-dynload/readline*
find "${P:?}" -depth -type d \( -name tests -o -name __pycache__ \) -exec rm -rf {} +
find "${P:?}/site-packages" -mindepth 1 -maxdepth 1 \
	! -name PySide6 ! -name shiboken6 ! -name osgeo ! -name numpy -print0 | xargs -0 rm -rf
# of PySide6 the modules the editor imports; the rest bring all of Qt with them
find "${P:?}/site-packages/PySide6" -mindepth 1 -maxdepth 1 \
	! -name '__init__.py' ! -name '_config.py' ! -name '_git_pyside_version.py' \
	! -name 'QtCore.*' ! -name 'QtGui.*' ! -name 'QtWidgets.*' ! -name 'QtNetwork.*' \
	! -name support -print0 | xargs -0 rm -rf
# Danu itself, as the source has it
(cd "$ROOT" && tar -cf - --exclude=__pycache__ danu) | (cd "$P/site-packages" && tar -xf -)

# Qt: the Cocoa platform (and offscreen, for a check without a screen), the
# macOS style, the images and icons it draws, TLS for the tiles and the
# sign-in, and the network state it asks about
Q=$R/lib/qt6
find "${Q:?}" -mindepth 1 -maxdepth 1 ! -name plugins -print0 | xargs -0 rm -rf
find "${Q:?}/plugins" -mindepth 1 -maxdepth 1 \
	! -name platforms ! -name styles ! -name imageformats ! -name iconengines ! -name tls \
	! -name networkinformation -print0 | xargs -0 rm -rf

# the rest of the environment that nothing runs: of share, GDAL's and PROJ's
# data and the licences; of lib, the directories of what is kept; of ssl, the
# CA certificates, which the launcher points OpenSSL at
find "${R:?}" -mindepth 1 -maxdepth 1 ! -name bin ! -name lib ! -name share ! -name ssl -print0 | xargs -0 rm -rf
find "${R:?}/share" -mindepth 1 -maxdepth 1 ! -name gdal ! -name proj ! -name licenses -print0 | xargs -0 rm -rf
find "${R:?}/lib" -mindepth 1 -maxdepth 1 -type d ! -name "$PY" ! -name qt6 -print0 | xargs -0 rm -rf
find "${R:?}/ssl" -mindepth 1 -maxdepth 1 ! -name cacert.pem -print0 | xargs -0 rm -rf
find "${R:?}/lib" -maxdepth 1 \( -name '*.a' -o -name '*.la' -o -name '*.prl' \) -delete
"$R/bin/python3" "$HERE/closure.py" "$R" libisofill.so

# compiled once, here: an app run from its .dmg, or from /Applications by
# another user, cannot write beside its sources
"$R/bin/python3" -m compileall -q -j 0 "$P" ||
	echo "  warning: some of the tree did not compile; it will be compiled in memory on each start" >&2

# the bundle: Info.plist, the icon at each size drawn, and an ad hoc signature
v=${VERSION:-$("$R/bin/python3" -c 'import sys; sys.path.insert(0, sys.argv[1]); import danu; print(danu.__version__)' "$ROOT")}
sed "s/@VERSION@/$v/g" "$HERE/Info.plist.in" > "$C/Info.plist"
icons=$OUT/danu.iconset
mkdir "$icons"
I=$ROOT/danu/ui/icons
cp "$I/danu-16.png" "$icons/icon_16x16.png"
cp "$I/danu-32.png" "$icons/icon_16x16@2x.png"
cp "$I/danu-32.png" "$icons/icon_32x32.png"
cp "$I/danu-64.png" "$icons/icon_32x32@2x.png"
cp "$I/danu-128.png" "$icons/icon_128x128.png"
cp "$I/danu-256.png" "$icons/icon_128x128@2x.png"
cp "$I/danu-256.png" "$icons/icon_256x256.png"
iconutil -c icns -o "$R/danu.icns" "$icons"
codesign --force --deep --sign - "$APP"
codesign --verify --deep "$APP"
echo "Danu.app: $(du -sh "$APP" | cut -f1) in $(find "$APP" -type f | wc -l | tr -d ' ') files"

[ -n "$VERSION" ] || exit 0
stage=$OUT/dmg
mkdir "$stage"
cp -R "$APP" "$stage/"
ln -s /Applications "$stage/Applications"
hdiutil create -quiet -volname Danu -srcfolder "$stage" -format UDZO -ov "$OUT/danu-$VERSION-macos-arm64.dmg"
ls -l "$OUT/danu-$VERSION-macos-arm64.dmg"
