#!/bin/bash
#
# Prove a freshly built isofill runs, not merely links. Run from the directory
# holding the binary, on Linux and under MSYS2 alike - one script so the two
# platforms cannot drift apart in what they assert.
#
# A binary that compiles and cannot load its GDAL DLLs is the Windows failure a
# build step never sees. So the binary is executed, and two things are required
# of it: the exit status isofill gives after printing usage, which is 2, and the
# first line of that usage text exactly. Either alone is weak - a loader error
# can exit 2 as well, and a chatty diagnostic can contain the word "usage" - and
# together they only hold if isofill's own main() ran to its usage() call.

set -u
cd "$(dirname "$0")/../../extern/isofill" || exit 1

bin=./isofill
[ -x "$bin" ] || [ -x "$bin.exe" ] || { echo "no isofill binary here"; exit 1; }

out=$("$bin" 2>&1)
status=$?
printf '%s\n' "$out" | head -3

if [ "$status" -ne 2 ]; then
	echo "expected exit 2 after usage, got $status"
	exit 1
fi
if ! printf '%s\n' "$out" | grep -qx 'usage: isofill \[options\] <constraints.tif> <out.tif>'; then
	echo "usage text not found in the output"
	exit 1
fi
echo "isofill runs: exit 2 and its usage text"
