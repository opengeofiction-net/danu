# Danu

A desktop editor for OpenGeofiction elevation contours, and the pipeline that
builds the DEM from them.

Draw contours on the map and watch the surface they produce appear underneath -
at the resolution the server will use, and by the same algorithm, because the
editor and the nightly build are the same code.

Named for the river goddess, which is as good a reason as any.

## Why

Contours are drawn blind. A mapper puts lines on a map, the nightly build turns
them into a DEM, and the hillshade appears on the tiles some hours later. What
the lines *mean* as a surface is invisible at the moment of drawing.

The cost is measurable. Across the OGF test zones the published elevation
disagrees with the drawn water by 705 m of irreducible ascent on `tapira`,
12,438 m on `gobras` and 7,979 m on `ellarca`. Lake Kinser's surface, 37.5 km²
of it, sloped through 60 m in 51 distinct elevations. None of that is the
mapper's fault: the information was never in front of them.

Danu puts it there.

## What is here

| | |
|---|---|
| `danu/core` | squares, the elevation ladder, edits, undo, id allocation |
| `danu/surface` | constraints, `isofill`, the incremental engine, ramps |
| `danu/water` | Overpass client and cache, grading, water bodies |
| `danu/checks` | validation |
| `danu/cli` | the command line: what the server runs, and what CI runs |
| `danu/ui` | the editor, PySide6 |
| `server/` | the build scripts, configuration and systemd units |
| `params/` | parameters shared by the editor and the build |
| `extern/isofill` | the interpolator, as a submodule |
| `packaging/ci` | what CI runs that is not a test: the `isofill` run check, and the pre-flight review |

`core` through `cli` know nothing of Qt and run on a headless machine. The
server side and the editor are packaged separately - a `.deb` and desktop
installers - from one codebase, so the preview cannot disagree with the build
about what a contour means.

## Reviewing before the pull request

Every pull request is reviewed by DeepSeek through the workflow in
`.github/workflows/deepseek-review.yml`. The same review can be run first,
locally, on the diff against `main`:

```
packaging/ci/cr            # or put it on your PATH as cr
```

It needs [Nushell](https://www.nushell.sh), a checkout of
`hustcer/deepseek-review` at the commit the workflow pins, and `CHAT_TOKEN` in
the environment. The prompt, model and exclusions are read from the workflow
file on every run, so there is one reviewer, not two that drift.

## Status

Early. The specification is complete and the code is not: see
[`docs/spec.md`](docs/spec.md) for the requirements, the architecture and the
plan, and `docs/spec.md#plan` for what order it happens in.

## Relationship to the other repositories

- **`ogf-server-scripts`** keeps the tile servers, the coastline, the admin
  polygons and the reports. The DEM-producing scripts moved here; the three
  which consume published rasters - `fetchDemData.sh`, `renderDemZones.sh`,
  `demExpireTiles.py` - stayed there. Neither repository imports the other.
  Danu publishes a hillshade and a contour extract that the tile servers fetch,
  and reads the daily `utility/territory.json` that they publish.
- **`isofill`** is the interpolator, kept separate because it is C with its own
  release cycle and its own Debian packaging.

## Licence

GPL-3.0-or-later. See [`LICENSE`](LICENSE), which explains why that and not
something more permissive - the short version is that `libisofill` and PySide6
between them leave exactly one option.
