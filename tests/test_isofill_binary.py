"""The isofill binary is asked its version before it is given flags, so an old
one fails with that rather than with its usage text."""

import sys

import pytest

from danu.surface import isofill_lib

pytestmark = pytest.mark.skipif(sys.platform == 'win32', reason='fake binaries are shell scripts')


def _fake(tmp_path, name, version, body='exit 0'):
    exe = tmp_path / name
    exe.write_text('#!/bin/sh\n'
                   f'if [ "$1" = "--version" ]; then echo "isofill {version}"; exit 0; fi\n'
                   f'{body}\n')
    exe.chmod(0o755)
    return str(exe)


def test_an_older_binary_is_refused_with_its_version(tmp_path):
    exe = _fake(tmp_path, 'old', '0.12.0')
    with pytest.raises(isofill_lib.IsofillError, match=r'is isofill 0\.12\.0; this build of danu wants'):
        isofill_lib.check_binary(exe)


def test_the_expected_binary_and_a_newer_one_pass(tmp_path):
    assert isofill_lib.check_binary(_fake(tmp_path, 'same', isofill_lib.EXPECTED_VERSION)) \
        == isofill_lib.EXPECTED_VERSION
    assert isofill_lib.check_binary(_fake(tmp_path, 'newer', '99.0.0')) == '99.0.0'


def test_a_binary_that_does_not_say_is_refused(tmp_path):
    exe = tmp_path / 'mute'
    exe.write_text('#!/bin/sh\nexit 2\n')
    exe.chmod(0o755)
    with pytest.raises(isofill_lib.IsofillError, match='did not say'):
        isofill_lib.check_binary(str(exe))


def test_a_failure_leaves_the_usage_out(tmp_path):
    pytest.importorskip('osgeo')
    from danu.surface import build, params
    exe = _fake(tmp_path, 'usage', isofill_lib.EXPECTED_VERSION,
                'echo "usage: isofill [options] <constraints.tif> <out.tif>" >&2\n'
                'echo "  --radius N     search radius" >&2\nexit 2')
    with pytest.raises(RuntimeError) as e:
        build._interpolate_binary(tmp_path / 'c.tif', tmp_path / 'm.tif', None, params.load(),
                                  tmp_path / 'o.tif', exe, budget=100)
    assert 'usage' in str(e.value) and '--radius N' not in str(e.value)
