#!/bin/bash
# The AppImage: Danu with its own Python, PySide6, GDAL and numpy from
# conda-forge - the versions in stack.txt, Windows' versions - and isofill
# built against that GDAL by conda-forge's compiler, so nothing in it asks for
# a newer glibc than conda-forge's 2.17:
#
#   bash packaging/linux/build-appdir.sh OUT [VERSION]
#
# OUT/AppDir is the environment cut to what Danu uses: the standard library
# less what nothing imports, of site-packages the four packages, of PySide6
# the four modules the editor imports, the Qt plugins a window on Linux
# loads, GDAL's and PROJ's data, and of the environment's libraries those
# that something kept links, found by closure.py. With VERSION, it is then
# packed by appimagetool as OUT/danu-VERSION-x86_64.AppImage.
#
# MICROMAMBA is the micromamba to use (default: the one on PATH);
# APPIMAGETOOL and RUNTIME the packer - appimagetool's own AppImage - and the
# runtime it puts at the head of the image (default: fetched, at the versions
# named below).
set -euo pipefail

OUT=${1:?usage: build-appdir.sh OUT [VERSION]}
VERSION=${2:-}
case $VERSION in *[!0-9A-Za-z.+~-]*) echo "version $VERSION: letters, digits and .+~- only" >&2; exit 1 ;; esac
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
HERE=$ROOT/packaging/linux
MM=${MICROMAMBA:-micromamba}
APPIMAGETOOL_URL=https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage
RUNTIME_URL=https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64
A=$OUT/AppDir
U=$A/usr
B=$OUT/build-env

[ ! -e "$A" ] || { echo "$A exists; give an empty OUT" >&2; exit 1; }
mkdir -p "$OUT"
export MAMBA_ROOT_PREFIX=$OUT/mamba

# the stack, and beside it the compiler isofill is built with, which stays out
spec=$(grep -v '^#' "$HERE/stack.txt")
# shellcheck disable=SC2086
"$MM" create -q -y -p "$U" -c conda-forge --override-channels $spec
# conda-forge's compiler defaults to a newer sysroot than its packages are
# built on; unpinned, isofill asked for glibc 2.38
"$MM" create -q -y -p "$B" -c conda-forge --override-channels c-compiler make 'sysroot_linux-64=2.17'
PY=$("$U/bin/python3" -c 'import sys; print(f"python{sys.version_info.major}.{sys.version_info.minor}")')

# isofill, against the GDAL being shipped, finding its libraries beside it
# wherever the image is mounted; built from a copy, so the checkout's own
# build is left as it was
mkdir "$OUT/isofill"
cp -r "$ROOT/extern/isofill/Makefile" "$ROOT/extern/isofill/src" "$OUT/isofill/"
PATH="$U/bin:$B/bin:$PATH" make -C "$OUT/isofill" isofill libisofill.so \
	CC="$B/bin/x86_64-conda-linux-gnu-cc" LDFLAGS="-L$U/lib -Wl,-rpath-link,$U/lib -Wl,-rpath,'\$\$ORIGIN/../lib'" >/dev/null
cp "$OUT/isofill/isofill" "$U/bin/"
cp "$OUT/isofill/libisofill.so" "$U/lib/"

# of bin, the interpreter and isofill
find "$U/bin" -mindepth 1 \( -name isofill -o -name python3 -o -name python -o -name "$PY" \) -prune -o -print0 |
	xargs -0 rm -rf

# the standard library less what nothing here uses, and of site-packages only
# what Danu imports
P=$U/lib/$PY
rm -rf "$P"/{test,idlelib,tkinter,turtledemo,ensurepip,venv,pydoc_data,lib2to3}
rm -rf "$P"/config-*
find "$P" -depth -type d \( -name tests -o -name __pycache__ \) -exec rm -rf {} +
find "$P/site-packages" -mindepth 1 -maxdepth 1 \
	! -name PySide6 ! -name shiboken6 ! -name osgeo ! -name numpy -print0 | xargs -0 rm -rf
# of PySide6 the modules the editor imports; the rest bring all of Qt with them
find "$P/site-packages/PySide6" -mindepth 1 -maxdepth 1 \
	! -name '__init__.py' ! -name '_config.py' ! -name '_git_pyside_version.py' \
	! -name 'QtCore.*' ! -name 'QtGui.*' ! -name 'QtWidgets.*' ! -name 'QtNetwork.*' \
	! -name support -print0 | xargs -0 rm -rf
# Danu itself, as the source has it
(cd "$ROOT" && tar -cf - --exclude=__pycache__ danu) | (cd "$P/site-packages" && tar -xf -)

# Qt: its plugins for a window under X11 or Wayland, the images and icons it
# draws, TLS for the tiles and the sign-in, the network state it asks about,
# and the desktop's file dialogs
Q=$U/lib/qt6
find "$Q" -mindepth 1 -maxdepth 1 ! -name plugins -print0 | xargs -0 rm -rf
find "$Q/plugins" -mindepth 1 -maxdepth 1 \
	! -name platforms ! -name platformthemes ! -name platforminputcontexts ! -name imageformats \
	! -name iconengines ! -name tls ! -name networkinformation ! -name xcbglintegrations \
	! -name 'wayland-*' -print0 | xargs -0 rm -rf
find "$Q/plugins/platforms" -mindepth 1 \
	! -name libqxcb.so ! -name libqwayland.so ! -name libqoffscreen.so ! -name libqminimal.so -delete
# The environment's qt6.conf names the prefix it was installed at; a qt.conf
# beside the interpreter, for Qt the application, is read first and its paths
# are taken from where it is
rm -f "$U/bin/qt6.conf"
printf '[Paths]\nPrefix = ..\nPlugins = lib/qt6/plugins\n' > "$U/bin/qt.conf"

# the rest of the environment that nothing runs: of share, GDAL's and PROJ's
# data, X11's compose tables and the licences; of lib, the directories of
# what is kept; of ssl, the CA certificates, for a machine without its own.
# PySide6's generator and its tools are at the top, beside bin, and go too
find "$U" -mindepth 1 -maxdepth 1 ! -name bin ! -name lib ! -name share ! -name ssl -print0 | xargs -0 rm -rf
find "$U/share" -mindepth 1 -maxdepth 1 ! -name gdal ! -name proj ! -name X11 ! -name licenses -print0 |
	xargs -0 rm -rf
find "$U/lib" -mindepth 1 -maxdepth 1 -type d ! -name "$PY" ! -name qt6 -print0 | xargs -0 rm -rf
find "$U/ssl" -mindepth 1 -maxdepth 1 ! -name cacert.pem -print0 | xargs -0 rm -rf
find "$U/lib" -maxdepth 1 \( -name '*.a' -o -name '*.la' -o -name '*.prl' \) -delete
"$U/bin/python3" "$HERE/closure.py" "$U" libisofill.so

# compiled once, here, rather than on a mapper's first start inside an image
# nothing can write to
"$U/bin/python3" -m compileall -q -j 0 "$P" ||
	echo "  warning: some of the tree did not compile; it will be compiled in memory on each start" >&2

cp "$HERE/AppRun" "$A/AppRun"
cp "$HERE/danu.desktop" "$A/danu.desktop"
cp "$ROOT/danu/ui/icons/danu-256.png" "$A/danu.png"
ln -s danu.png "$A/.DirIcon"
echo "AppDir: $(du -sh "$A" | cut -f1) in $(find "$A" -type f | wc -l) files"

[ -n "$VERSION" ] || exit 0
tool=${APPIMAGETOOL:-}
runtime=${RUNTIME:-}
if [ -z "$tool" ]; then
	tool=$OUT/appimagetool
	curl -fsSL -o "$tool" "$APPIMAGETOOL_URL"
	chmod +x "$tool"
fi
if [ -z "$runtime" ]; then
	runtime=$OUT/runtime
	curl -fsSL -o "$runtime" "$RUNTIME_URL"
fi
# --appimage-extract-and-run: the packer is an AppImage itself, and a CI
# container has no FUSE to mount it with
ARCH=x86_64 "$tool" --appimage-extract-and-run --no-appstream --runtime-file "$runtime" \
	"$A" "$OUT/danu-$VERSION-x86_64.AppImage" >/dev/null
ls -l "$OUT/danu-$VERSION-x86_64.AppImage"
