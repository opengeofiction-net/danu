"""Danu's surface against a reference the pipeline produced.

This is the check which stops the editor and the nightly build disagreeing
about what a contour means. Everything else in tests/ is a unit test; this one
runs the real thing - the real square, the real isofill, the real GDAL - and
asserts the answer has not moved.

The reference was built on 2026-09-17 by running this fixture through both
ogf-server-scripts master and Danu. Every published artefact matched byte for
byte except the GeoPackage, whose SQLite gpkg_contents carries a last_change
timestamp; its 240 features hashed identically. So the move from one repository
to the other changed nothing, and this test is what keeps that true.
"""

import os
import pathlib
import shutil
import subprocess
import sys
import tomllib

import pytest

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parents[1]
# the name carries the degree square: the build reads it from the
# filename, and a fixture called square.osm.xz builds nothing at all
SQUARE = HERE / "S24E125_Los_Pizarrales.osm.xz"
EXPECTED = HERE / "expected.tif"
LOCK = HERE / "params.lock"

gdal = pytest.importorskip("osgeo.gdal", reason="GDAL not available")
pytestmark = pytest.mark.skipif(
    shutil.which("isofill") is None, reason="isofill not on PATH"
)


@pytest.fixture(scope="module")
def lock():
    with LOCK.open("rb") as fh:
        return tomllib.load(fh)


def test_the_lock_agrees_with_the_shared_parameters(lock):
    """The reference is only meaningful if it was built with the parameters the
    build still uses. Where the two overlap they must agree."""
    with (ROOT / "params" / "elevation.toml").open("rb") as fh:
        params = tomllib.load(fh)
    assert lock["fill_metres"] == params["fill"]["metres"]
    assert lock["barrier_cells"] == params["fill"]["barrier_cells"]
    assert lock["pass2"] == params["fill"]["pass2"]
    assert lock["hgt_arcsec"] == params["grid"]["hgt_arcsec"]


def test_surface_matches_the_reference(tmp_path, lock):
    base = tmp_path / "base"
    (base / "osm-squares" / "golden").mkdir(parents=True)
    shutil.copy(SQUARE, base / "osm-squares" / "golden" / SQUARE.name)

    env = dict(os.environ)
    env.update(
        PYTHONPATH=str(ROOT),
        CONF=str(ROOT / "server" / "etc"),
        BASE=str(base),
        WORKBASE=str(tmp_path / "work"),
        PUBROOT=str(tmp_path / "pub"),
        ARCSEC=str(lock["arcsec"]),
        WATER_CONSTRAINTS="0" if not lock["water_constraints"] else "1",
    )
    run = subprocess.run(
        ["bash", str(ROOT / "server" / "bin" / "danu-build-zone"), "golden"],
        capture_output=True, text=True, env=env, timeout=900,
    )
    assert run.returncode == 0, run.stdout[-3000:] + run.stderr[-3000:]

    produced = tmp_path / "pub" / "golden" / "dem-golden.tif"
    assert produced.exists(), "the build published no DEM"

    import numpy as np

    # the datasets are held in locals on purpose: gdal.Open(...).GetRasterBand(1)
    # frees the dataset before the band is read and fails with a TypeError out
    # of gdal_array, which reads like anything but the lifetime problem it is
    ref_ds = gdal.Open(str(EXPECTED))
    new_ds = gdal.Open(str(produced))
    a = ref_ds.GetRasterBand(1).ReadAsArray()
    b = new_ds.GetRasterBand(1).ReadAsArray()
    assert a.shape == b.shape, f"reference is {a.shape}, produced {b.shape}"
    differing = int((a != b).sum())
    assert differing == 0, (
        f"{differing} of {a.size} cells differ; "
        f"reference {a.min():.2f}..{a.max():.2f}, produced {b.min():.2f}..{b.max():.2f}"
    )
