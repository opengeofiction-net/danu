# The golden surface

One real contour square, the parameters in `params/elevation.toml`, and the
surface they produce. The test asserts Danu reproduces it cell for cell.

This is the check which stops the editor and the nightly build disagreeing
about what a contour means, which is the failure this architecture is most
exposed to. Everything else here is a unit test; this is the one that matters.

The fixture is not yet committed. It needs:

- `S24E125_Los_Pizarrales.osm.xz` - a real square, small enough to build
  in CI. The name matters: the degree square is read from it.
- `expected.tif` - the surface `danu-build-zone` produces from it, built with
  the parameters in `params/elevation.toml` at a recorded `isofill` tag
- `params.lock` - the parameter values used, so a change to them fails loudly
  rather than silently rebasing the expectation

Rebuilding the reference is deliberate work, not a convenience: if the surface
changes, either something improved and the reference should be regenerated with
a commit explaining what, or something regressed.
