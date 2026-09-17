"""Danu's surface against a reference built by the pipeline.

Skips until the fixture exists; see README.md in this directory.
"""

import pathlib

import pytest

HERE = pathlib.Path(__file__).parent
SQUARE = HERE / "square.osm.xz"
EXPECTED = HERE / "expected.tif"

pytestmark = pytest.mark.skipif(
    not (SQUARE.exists() and EXPECTED.exists()),
    reason="golden fixture not present; see tests/golden/README.md",
)


def test_surface_matches_the_reference():
    raise NotImplementedError("built with the fixture, in phase 0")
