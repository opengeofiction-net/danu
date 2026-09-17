# Danu

A desktop editor for OGF elevation contours. Draw contours on the map and watch
the surface they produce appear underneath, at the resolution and by the
algorithm the server will use.

Named for the river goddess, which is as good a reason as any.

## Why

Contours are drawn blind. A mapper puts lines on a map, the nightly build turns
them into a DEM, and the hillshade appears on the tiles some hours later. What
the lines *mean* as a surface is invisible at the moment of drawing, and the
consequences are only visible as a rendered hillshade nobody can attribute back
to a particular line.

The measurements are unambiguous. Across the test zones the published elevation
disagrees with the drawn water by 705 m of irreducible ascent on `tapira`,
12,438 m on `gobras` and 7,979 m on `ellarca` - 5 m, 21 m and 80 m per river.
Lake Kinser's surface, 37.5 km of it, sloped through 60 m in 51 distinct
elevations. None of that is visible while drawing, and none of it is the
mapper's fault: the information was never in front of them.

Danu puts it there.

## What it is not

Not part of the server DEM process. `buildDemZone.sh` stays as it is, building
whole zones from whatever squares it is given. The experiments that led here -
burning rivers into the terrain, pinning lakes from their outlets - belong in an
editor where a person accepts or rejects each one, not in an unattended nightly
run where a bad river silently becomes a trench.

Not a general OSM editor. It edits elevation constraints: contours, water
levels, and the anchor features that go in the same squares. JOSM and iD remain
the tools for everything else.

## Requirements

### Data

- **R1** The unit of work is the `.osm.xz` contour square, one per degree
  square, as `osm-squares/<zone>/` holds them. Open, edit, save in place.
- **R2** A 3x3 grid of squares is the default working set, centred on the square
  being edited, so edits near an edge can see their neighbours. The grid is
  configurable; 1x1 and 5x5 have uses.
- **R3** Squares carry contours (`ele` on a way) and may carry water and other
  anchors. All of it is editable.
- **R4** New nodes and ways take ids from the zone's allocation in
  `id-blocks.conf`. Two mappers editing neighbouring squares must not collide.
- **R5** Blank square templates can be created for squares nobody has drawn.
- **R6** The contour ladder is inferred per square, with a per-square override
  and a zone default.
- **R7** The territory and owner under the working set are shown, from the
  wiki's territory administration JSON joined to the daily published
  `territory.json` polygons on the relation id. Advisory: opening a square
  somebody else owns warns and proceeds.

### Map and layers

- **R8** Any OGF tile layer as a backdrop - `ogf-carto`, `ttopo`, `cyclogf`,
  and any other the config names - each with independent opacity.
- **R9** The interpolated surface overlays the map as hillshade or colour ramp,
  with its own opacity.
- **R10** Two ramps: traditional elevation (green - brown - white) and spectral
  (blue - green - yellow - orange - red).
- **R11** Ramp scaling: autoscale to the working set, manual min/max, and *pitch
  highlighting* - narrow the ramp to a window around a chosen elevation so local
  relief reads clearly on ground that is otherwise all one colour.
- **R12** Contours drawn over everything, coloured by elevation, labelled.

### Drawing

- **R13** Draw a contour as a polyline at the active elevation. Continue an
  existing way, insert and move nodes, delete.
- **R14** Active elevation set by a notched slider, by keys, and by the mouse
  wheel. See *Elevation control*.
- **R15** Snap to existing contour nodes and to the coastline.
- **R16** Contours at the same elevation may not cross each other, and a contour
  may not cross one of a different elevation at all. Enforced on commit, warned
  live.
- **R17** Undo and redo across every operation, including the compound ones.

### The surface

- **R18** The surface is produced by the same code as the server: `isofill` with
  the same parameters, the same two passes, the same water mask. What is on
  screen is what the build will produce.
- **R19** While drawing, the surface updates locally and immediately. On idle it
  is rebuilt exactly. The two states are distinguishable at a glance.
- **R20** Where the first pass found no answer - `OUT_OF_REACH`, `NO_ELEV`,
  `ONE_LEVEL` - the editor says so, as an overlay. This is the single most
  useful thing it can tell a mapper: *here is ground your contours do not
  describe*.
- **R21** The envelope the contours describe, as `demDrawnMask.py` computes it,
  is drawn as an outline. Beyond it the fill does not reach.
- **R22** Ground outside the working set is shown from the **published** DEM and
  hillshade, fetched as tiles from `data.opengeofiction.net`. Live surface for
  the 3x3, last night's build for everything else, with a visible seam between
  them so nobody mistakes one for the other.

### Water

- **R23** Import rivers, streams and water bodies for the working set from
  Overpass, cached locally.
- **R24** Set an elevation on a water body or a waterway, by hand or from the
  contours it touches.
- **R25** Burn a river into the terrain: grade it between the contours it
  crosses and rewrite the contours to match, as a proposal the user accepts or
  rolls back.
- **R26** Flatten a water body at a chosen level, likewise.
- **R27** Flowing water is never flattened. A river area descends along its
  course.
- **R28** Water anchors inside the squares are first-class and editable. The
  separate `water/<zone>.osm` overlay is not: only `roantra` has one, 54 MB of
  it, against 32 zones, and every other zone's water lives in its squares where
  Danu already edits it. Reading roantra's overlay for context is cheap and
  worth doing; editing it is a separate job with no second user.

### Checks

- **R29** Rivers which climb, per `demRiverCheck.py`, listed and clickable.
- **R30** Ways over 2,000 nodes, which the OSM API would reject, and over
  10,000, which GDAL silently truncates. Split on save.
- **R31** `ele` values which are not numbers.
- **R32** Sea level lines which do not lie on a drawn coastline, per
  `demCheckZeroLine.py`.
- **R33** A water body spanning more than one contour.

### Platform

- **R34** Linux and Windows are both primary. macOS if it is free.
- **R35** Shared logic lives in one place and is used by both Danu and the
  server tooling. Neither reimplements the other.

## Architecture

Danu owns elevation, end to end. The server scripts which build the DEM move out
of `ogf-server-scripts` and into this repository alongside the editor, so there
is one place where the elevation pipeline lives and one definition of how a
contour becomes a surface.

That removes the problem rather than working around it. There is no shared
library to extract, no dependency in either direction, and no duplicated glue
policed by a test. `ogf-server-scripts` keeps the tile servers, the coastline,
the admin polygons and the reports; it loses the `dem*` scripts and gains
nothing. It can be renamed to `ogf-server-scripts` whenever that suits, and
Danu will not notice.

The editor and the build then share code because they *are* the same code. The
incremental preview path is the only thing unique to the editor, and it calls
the same rasteriser, the same `isofill`, the same parameters as the nightly run.

`isofill` stays its own repository, pinned here as a submodule, because it is C
with its own release cycle and its own Debian packaging.

### What moves

Sixteen scripts and three configuration files:

| | |
|---|---|
| build | `buildDemData.sh`, `buildDemZone.sh` |
| squares | `demMakeSquare.py`, `demRecoverSquares.py`, `demSplitLongWays.py`, `demZoneExtent.py` |
| surface | `demSeaMask.py`, `demLandClamp.py`, `demDrawnMask.py` |
| output | `demContoursToOsm.py`, `demZoneStats.py`, `demZonesToMultimap.py` |
| checks | `demCheckZeroLine.py`, `demRiverCheck.py` |
| water | `demWaterConstraints.py` |
| backup | `backupElevation.sh` |
| config | `etc/dem_osmconf.ini`, `etc/dem_relief.ramp`, `etc/dem_inactive.template`, the `dem-build` unit and timer |

### What stays

`fetchDemData.sh`, `renderDemZones.sh`, `demExpireTiles.py` and the
`tile-refresh-dem` units stay where they are. They are consumers: they take
published TIFFs and a contour extract and turn them into rendered tiles, and
they belong with the rest of the tile-server tooling.

Nothing is shared between the two sides. `demExpireTiles.py` imports only the
standard library. `fetchDemData.sh` reads `etc/cyclogf_contours.style`, which is
tile-server configuration, and the tile server's own `renderd.conf`, which is not
in either repository. The two sides even use different ramps for different
purposes: the producer's `etc/dem_relief.ramp` colours the relief rasters it
publishes, while the consumer's `map-styles/<style>/dem/shade.ramp` colours the
hillshade for a particular style and lives in the styles repository. There is no
module, no helper and no configuration file in common.

### The contract between them

What is shared is a published directory and a manifest, which after the split is
a documented interface between two repositories rather than an implementation
detail inside one. The tile servers fetch exactly three things:

| path | what it is |
|---|---|
| `active-zones.txt` | the manifest; a zone absent from it is treated as removed |
| `<zone>/hillshade-<zfactor>.tif` | greyscale hillshade, `z2` or `z5` by style |
| `<zone>/contours-<zone>.osm.pbf` | contours for the render database |

Danu publishes more than that - `dem-<zone>.tif`, the reliefs, the GeoPackage,
the `.hgt` archive - for mappers and for recovery, but those three are the whole
of what the renderers need, and changing any of them is a change to another
repository's input.

The traffic goes both ways, and by the same mechanism. Danu *consumes*
`utility/territory.json`, which `simplifiedAdminPolygons.py` publishes daily
from the other repository. Neither side imports the other; both read files the
other writes to a documented place. That is the same boundary as the hillshade,
in the opposite direction, and it is the reason the split works.

### Repository shape

```
danu/
  danu/
    core/          squares, ladder, edits, undo, id allocation
    surface/       constraints, isofill driver, incremental engine, ramps
    water/         Overpass client and cache, grading, bodies
    checks/        every validation rule
    cli/           the command line: what the server runs, and what CI runs
    ui/            PySide6, presentation only
  server/
    bin/           the build scripts, thin wrappers over danu.cli
    etc/           osmconf, ramps, templates
    systemd/       danu-build service and timer
  extern/isofill/  submodule, pinned by tag
  params/          elevation.toml, the parameters the build and editor share
  tests/golden/    fixture squares and reference surfaces
  packaging/
    deb/           the server side, as OGF servers install it today
    windows/ linux/ the desktop application
  docs/
```

`core` through `cli` know nothing of Qt and are importable on a headless
machine. `server/bin` are thin wrappers over `danu.cli`, so the logic lives
where the editor and the tests can reach it.

### Naming

The `dem` prefix goes. It distinguished these scripts from their neighbours in a
repository full of unrelated tooling, and in a repository that is *only* about
elevation it says nothing. So `demSeaMask.py` becomes `danu.surface.sea_mask`,
`demCheckZeroLine.py` becomes `danu.checks.zero_line`, and the command line
becomes `danu-build`, `danu-check`, `danu-square` and the rest. The units follow:
`dem-build.service` and `.timer` become `danu-build.service` and `.timer`. So do
the tests and their fixtures - a test named after a script that no longer exists
is a small trap set for a future reader.

Nothing keeps the old names as aliases. Phase 0 redeploys the servers anyway,
the docs are being swept for the rename in the same window, and a compatibility
shim for an audience of one operator is a liability rather than a kindness.

Two artefacts from one CI: a **`.deb`** for the servers and **desktop
installers** for Linux and Windows. Same core, same `isofill`, same parameters,
so the editor cannot disagree with the build about what a contour means.

`isofill` is consumed **as a library**. It becomes `libisofill` with a small C
API and a thin command-line wrapper over it, which is the same refactor its own
test harness wants: `radius_value` and `diffuse` are already isolated static
functions, so the work is exposing them rather than restructuring around them.
CFFI binds the library, and the editor's incremental path calls it directly
without a process per stroke.

No stable ABI. Danu and the build are the only consumers and are upgraded
together, so the API changes when it needs to and a version check at load
catches a mismatched pair. If a third consumer ever appears, that is the point
to start caring, and not before.

### Paths

The `.deb` uses system paths rather than `/opt/opengeofiction`:

| | |
|---|---|
| `/usr/bin/` | `danu-build`, `danu-check`, and the other entry points |
| `/usr/lib/python3/dist-packages/danu/` | the package |
| `/etc/danu/danu.conf` | configuration, including where the data lives |
| `/usr/lib/systemd/system/` | `danu-build.service` and `.timer` |
| `/var/lib/danu/` | `osm-squares`, `water`, `stamps`, `hgt` |
| `/var/cache/danu/` | `build`, which is transient and rebuildable |

Moving the data is cheap, which was not obvious until measured: the elevation
tree is 2.0 GB, and 1.3 GB of that is `build/`. What cannot be regenerated is
`osm-squares` at 328 MB and `water` at 52 MB. The data root stays configurable
so an existing `/opt/opengeofiction/elevation` can be left alone by setting one
line, but there is no size argument for doing so.

On the desktop, XDG: `~/.config/danu/`, `~/.cache/danu/` for the tile and
Overpass caches, `~/.local/share/danu/` for sessions and recovery.

There is no service tier. Danu is a desktop application plus a set of batch
entry points. If a long `isofill` run wants its own process so a crash cannot
take the editor down, that is a detail inside `surface/`.

### Threads

Three, and no more.

- **UI** owns Qt and nothing else blocks it.
- **Compute** owns the constraint grid, isofill and the ramp. One worker, a
  queue of jobs, newest wins - a stroke in progress supersedes the job the last
  stroke queued.
- **Network** fetches map tiles and Overpass, both cached on disk.

### Why the preview can be exact locally

A cell's first-pass value depends only on contours within `radius`. Recompute a
box grown by `radius` around an edit and every cell in the original box gets the
value a whole-raster run would give it - bit for bit. This is the same argument
that made the banded first pass exact.

The second pass has no such property. Laplace diffusion is global: a change
anywhere moves everything, by less and less with distance. A local solve holding
the surrounding surface fixed at the box edge is therefore an approximation, and
a good one, because the boundary it holds is the answer the last full solve gave.

So:

| when | extent | pass 1 | pass 2 | budget |
|---|---|---|---|---|
| during a drag | edited box, no margin | exact within | local, approximate | 30 ms |
| on release | box + radius margin | exact | local, approximate | 200 ms |
| on idle, 2 s | whole working set | exact | exact | seconds |

The status bar reads `preview` until the idle rebuild lands, then `exact`. Any
measurement the editor reports - a profile, a check, a difference - is taken from
an exact surface or refuses to answer.

## Elevation control

The active elevation is the editor's most-used state, so it gets three
redundant controls.

### Increments

Two configurable steps, **small** and **big**, defaulting to 10 m and 50 m.
Everything below is expressed in those terms rather than in metres, so a zone
working at 5 m and 25 m behaves identically without relearning the keys.

### Keys

The defaults form a column on a QWERTY keyboard, which is the point:

```
 2     big increment      +50 m
 w     small increment    +10 m
 s     small decrement    -10 m
 x     big decrement      -50 m
```

The left hand rests on `w` and `s` and reaches `2` up and `x` down, so
elevation is driven without looking and without leaving the drawing hand. All
four are rebindable, as is everything else.

| key | does |
|---|---|
| `2` / `x` | big increment / decrement |
| `w` / `s` | small increment / decrement |
| space | pick up the elevation of the contour under the cursor |
| `[` / `]` | nudge by one metre, for the awkward cases |
| `0` | 0 m, sea level |

`space` matters more than it looks: most drawing continues an existing line, and
typing its elevation is the slow way to get there.

### Wheel

Follows the keys. Wheel alone steps by the small increment, shift by the big
one, ctrl zooms the map. Alt is free and is given to the opacity of the active
overlay.

## The elevation ladder

Zones do not share a contour interval, and within a zone the interval varies -
finer on shallow ground where 25 m would say nothing, coarser on steep ground
where it would say too much. Nor do they sit on round numbers.

`N20E086_Gobras_City` is a fair example. Above 100 m it is a clean 25 m ladder,
100 through 1075, and that ladder carries almost all of the drawn length - 642
ways at 100 m, 381 at 125, 276 at 150. Below 100 m it is ad hoc: 0, 3, 5, 7, 9,
10, 12, 13, 15, 20, 25, 30, 35, 40, 43, 50, 55, 60, 70, 75, 85, 87, 90, 91, 93,
95. The gaps between consecutive values across the square run 1, 2, 3, 5, 7, 10,
15 and 25, the last of those 37 times.

So the ladder is **inferred from the working set, not configured**:

- Read every `ele` in the squares. The modal gap is the interval - 25 m here.
- Notch the slider at the values which actually exist, and extend the regular
  ladder above and below them.
- Where the data is irregular, as it is below 100 m here, the notches follow
  the data rather than imposing a spacing on it.
- Inference is **per square, not per zone**. A zone pulls squares from several
  mappers and they do not agree with each other: one may have worked at 25 m
  and a neighbour at 10 m, and averaging them would serve neither.
- An override exists per square, with a zone-level default, for the cases
  inference gets wrong and for drawing a square from blank where there is
  nothing to infer from.
- Crossing into a neighbouring square therefore changes the notches. The slider
  shows which square it is reading, because silently re-notching would be worse
  than the inconvenience.

This is close to what the 2014 Perl editor did with four hand-written elevation
lists the mapper switched between. Inferring them is the same idea with the
lists kept honest.

### Off-ladder values are usually mistakes

In that same square, 113 and 135 each appear exactly once, sitting between 110
and 115 and between 125 and 150. 43, 55, 87 and 91 likewise appear once each.
Some of those are deliberate detail; 135 between two ladder values is far more
likely a mis-typed 125.

Danu flags a value which is off the inferred ladder **and** used once or twice,
as advice rather than an error. It is cheap, it is new, and on this evidence it
would find real typos.

## Operations

The verbs worth having, beyond drawing.

- **Burn a river.** Grade the selected waterway between the contours it crosses,
  force it to descend, and rewrite contours so the surface follows it. Shown as
  a proposal: the affected contours highlighted, the surface updated, accept or
  roll back. This is the experiment that prompted Danu, and it belongs here
  rather than in the build precisely because it needs judgement.
- **Flatten a body.** At its outlet level, its rim's lowest contour, or a value
  typed in. Same accept-or-roll-back shape.
- **Re-contour the surface.** Cut contours from the interpolated DEM at any
  interval and offer them as new ways. The inverse operation, and the fastest way
  to turn a sparse sketch into a described surface - draw the ridge and the
  valley, generate what lies between, then edit what looks wrong.
- **Profile.** Drag a line, get terrain and water elevation along it, with the
  climbing stretches shaded. `OGF::Terrain::RiverProfile` did this in 2014 and
  the thirty lines that mattered are already ported.
- **Measure.** Distance and gradient between two points, which the old Perl
  editor had and nothing since has replaced.
- **Difference.** The working surface against the published DEM for the same
  ground, as a diverging ramp. What have I actually changed?
- **Magnify.** A loupe at the cursor, because contours are drawn at cell
  precision and the map is not.

## Validation

Checks run continuously over the working set and populate one panel. Each entry
is a location, so clicking it goes there.

| check | why it exists |
|---|---|
| ways over 2,000 nodes | the API rejects them on upload |
| ways over 10,000 nodes | GDAL drops them silently; ten contours went missing from `S37E147_Madison_City` this way, 45% of that square |
| non-numeric `ele` | `gdal_rasterize` coerces `TBD` to 0 and plants a sea level line |
| crossing contours | no surface satisfies them |
| duplicate coincident contours | the fill takes the steepest visible pair and these confuse it |
| rivers which climb | the DEM and the drawn water disagree |
| sea level off the coastline | the fill ran out rather than meeting a shore |
| body spanning contours | a lake is flat; the contours say otherwise |
| off-ladder `ele`, used once or twice | 113 and 135 each appear once in `N20E086`, between 110/115 and 125/150; a mis-typed 125 looks exactly like this |
| unreachable ground | `OUT_OF_REACH` after pass 1, as area and as a fraction |

Splitting long ways is automatic on save, since the file is unusable otherwise.
Everything else is advisory: the mapper is drawing fiction and is allowed to
mean it.

## Ownership and handoff

A square is drawn by whoever owns the ground under it, and OGF already records
that, in two pieces which join on a relation id.

**Attributes** come from the wiki: `OpenGeofiction:Territory_administration`
with `action=raw` is 217 KB of JSON, 1,089 territories, each with an `ogfId`, a
`name`, a `status`, an `owner` and a `rel` - the id of the relation holding its
boundary. 304 are owned, 404 reserved, 276 available, 59 collaborative.

**Geometry** comes from `data.opengeofiction.net/utility/territory.json`, which
`simplifiedAdminPolygons.py` rebuilds daily. It is a map of relation id to a
list of rings of `[lon, lat]`, 1,103 entries and 1.5 MB, with no attributes -
which is exactly the other half. Overpass is not involved: the polygons are
already built, already simplified and already published, and asking Overpass to
resolve a thousand relations on startup would be worse in every respect.

Four simplifications are published beside each other - `territory_1.json` at
5.1 MB, `territory_10.json` at 2.5 MB, `territory.json` at 50 and 1.0 MB of
`territory_200.json` - the thresholds being Visvalingam-Whyatt areas in square
pixels at a computation zoom rather than distances. The 50 is primary and is
plenty: a degree square is 111 km across and this is used to name the territory
under a cursor, not to adjudicate a boundary. `territory_1.json` is there if a
border case ever needs it.

Danu caches both files, joins them on the relation id, and shows the territory
and owner under the working set. That answers the question a mapper actually
has - *is this mine to draw?* - and the question an admin has, which is who to
ask. The two counts do not quite agree, 1,103 geometries against 1,089
attribute records, so the join is not total and the editor says "unknown" rather
than guessing.

The two halves cache differently, and for a reason rather than as a compromise.
The polygons are **stable**: a territory's boundary rarely moves, and changing
ownership is an edit to the attribute record against the same unchanged polygon.
So the geometry is cached for as long as it likes - the daily rebuild is its
natural refresh - while the 217 KB attribute file is re-read cheaply and often.
Ownership is therefore current the moment an admin saves the wiki page, without
the polygons being fetched again.

Ownership **warns and never blocks**. Opening somebody else's square says so;
refusing to open it would be an editor deciding a project question.

For most squares this is one territory to one owner and the answer is simple.
The 59 collaborative territories are not simple, and neither is a square
straddling a border. Danu reports what it finds rather than adjudicating:
ownership is a project matter, not an editor's.

**Handoff is email, for now.** The square is a file and files travel fine, which
is how contour work already reaches the servers.

## Later

Deliberately out of scope, recorded so the shape is not designed against:

- **A data drop point.** Mappers authenticate against the API server over OAuth
  and upload a square directly, instead of sending it to somebody. This is the
  right answer to handoff and it is too many moving parts to take on alongside
  everything above. It also carries the locking problem with it: once uploads
  are authenticated, the server knows who holds what, and *who may edit this
  square* stops being a social question. The two belong in one piece of work.
- **Direct API upload** of contour ways as a changeset, rather than square
  files.
- **Procedural terrain areas** - `ogf:terrain_area` karst, plateau, mountains,
  coastal plain - which the 2014 Perl could generate and nothing has since. No
  way in OGF carries those tags today, so reviving them means re-establishing a
  tagging convention first.
- **Editing roantra's `water/` overlay**, which is the only one of its kind.

## Testing

There is no test suite anywhere in this stack today. `isofill` has none,
`ogf-server-scripts` has none, and the only test file in either repository is
`original/test.pl` from the 2014 Perl. Every correctness argument made about the
elevation pipeline so far has been made by measuring output and reading code.
That has worked, but it has also let three bugs of mine through in one night -
a GDAL driver named differently across versions, a lookup sized by the wrong
set, and a river area flattened as though it were a lake - each caught by a
build guard rather than by a test.

So the harness is phase 0 work, not phase 6 work.

**pytest** for `core`. Unit tests for the square reader and writer, id
allocation, the ladder inference, grading, the checks. These are pure functions
over small fixtures and should be fast enough to run on every save.

**pytest-qt** for the UI. Tool state machines, key and wheel handling, the
elevation model. Not pixel comparison of the map.

**Golden-surface regression** is the test that matters most, and the one that
justifies the whole `core` extraction. A fixture square, a fixed `isofill`
revision and parameters, and a stored reference DEM. The test asserts the
editor's surface is identical to the reference, cell for cell. Run the same
fixture through `buildDemZone.sh` and assert it produces the same thing. That is
the only mechanism which will notice the editor and the server drifting apart,
which is the failure this design is most exposed to.

**Property tests**, with `hypothesis`, for the invariants that are easy to state
and easy to break:

- a graded waterway never ascends
- a flattened body has exactly one elevation
- splitting a way preserves its geometry and node order
- ladder inference on a synthetic ladder returns that ladder
- an edit followed by its undo restores the working set exactly

**Comparison tests** for the incremental path. Solve a box locally, solve the
whole set, and assert the first pass agrees exactly and the second agrees within
a stated tolerance. If that tolerance cannot be met the preview is not worth
having, and it is better to learn that in phase 4 than after building on it.

**`isofill` gets C tests too**, however modest. It is 1,392 lines with
`radius_value` and `diffuse` already isolated as static functions, so exposing
them for a test harness is the same refactor as exposing them for CFFI. Two jobs,
one change.

## Plan

**Phase 0 - move the pipeline.** Create the repository. Move the nineteen
scripts and their configuration in, with history where git makes that easy.
Restructure the logic into `danu.core`, `danu.surface`, `danu.water` and
`danu.checks`, leaving `server/bin` as wrappers so the operational commands are
unchanged. Pin `isofill`. Stand up pytest, CI on Linux and Windows, and a
`.deb`. Then the fixture: one real square, the shared parameters, a reference
surface, and a regression test asserting the surface is reproduced cell for
cell.

Deploy it to `util` and the tile servers, remove the `dem*` scripts from
`ogf-server-scripts`, and let a nightly build run from the new package. No UI.

Ends when the nightly build has run green from Danu for a week, and the only
`dem` left in `ogf-server-scripts` is the three consumer scripts and their
units.

**Phase 1 - viewer.** Map, tile layers with opacity, open a 3x3 working set,
draw contours as vectors over it, no editing. Ends when a mapper can look at
their square.

**Phase 2 - the surface.** `isofill` via CFFI, whole-set rebuild, hillshade and
both ramps with all three scaling modes, unreachable-ground overlay, envelope
outline. Slow and exact. Ends when the editor shows the same hillshade the
server does for the same square.

**Phase 3 - editing.** Draw, continue, move, delete. Elevation control in full.
Snapping. Undo. Save to `.osm.xz` with id allocation and long-way splitting.
Ends when a square can be drawn from blank and built by the server unchanged.

**Phase 4 - live.** The incremental path, the job queue, preview and exact
states. Ends when drawing a contour moves the hillshade under the cursor inside
50 ms.

**Phase 5 - water.** Overpass import and cache, elevations on water, burn and
flatten with accept and roll back, profile tool. Ends when the gobras experiment
is reproducible by hand in the editor.

**Phase 6 - checks and polish.** The validation panel, measure, difference,
magnify, autosave and crash recovery, session files.

**Phase 7 - release.** Installers for Linux and Windows, GDAL and Qt bundled,
`isofill` built for both, a settings UI, first-run help, and somewhere for a
crash to go. Ends when someone who has never opened a terminal can install it
and draw a contour.

Phases 1 to 4 are the spine; 5 onward are separable and could ship in any order.

Because Danu is meant for other OGF mappers rather than for one machine,
packaging is not deferred to phase 7 - only the *polish* is. A Windows build of
`core` plus `isofill`, produced by CI and installable, is a phase 0 deliverable
and stays green from then on. The alternative is discovering in phase 7 that a
choice made in phase 2 cannot be shipped, which is the usual way this goes
wrong. Being a tool for other people also means their machines are not yours:
no terminal, no `PYTHONPATH`, no system GDAL, and an error message that says
what to do rather than what failed.

## Sequencing

Three changes to the same repository, in order, each landing cleanly before the
next:

1. **Move the sixteen scripts** into Danu. This is phase 0, and it removes 22 of
   `ogf-server-scripts`' self-references to its own name along the way, so it
   shrinks the rename that follows.
2. **Rename `ogf-server-scripts` to `ogf-server-scripts`.** GitHub redirects
   `clone`, `fetch` and `push` from the old URL, and carries issues, wikis,
   stars and followers across. Three things do not follow: any GitHub Action
   hosted in the repository, which fails with `repository not found` until its
   references are updated; GitHub Pages URLs; and the old name, which must never
   be reused or every redirect dies. The real work is not the rename but the
   paths - 61 occurrences across 16 documents here, eight systemd units on
   `util`, and checkouts on four servers.
3. **Go live with the API rebuild**, on the `lugus-ogf-rebuild` branch.

Doing 1 and 2 before 3 is the right order. The move is almost entirely file
deletions on this side, so it merges into a long-running branch about as cleanly
as a change can, and renaming while the rebuild is still in preparation costs a
`git remote set-url` rather than an incident.

## Risks

- **Packaging GDAL and Qt on Windows** is the largest. It is no longer deferred:
  a Windows CI build of `core` and `isofill` lands in phase 0, before any choice
  has been made that a packager might veto.
- **Moving a working pipeline** is the phase 0 risk. It runs nightly and
  `ogf-server-scripts` is checked out on four servers. It happens once,
  deliberately, with the nightly build as the acceptance test, and the old
  scripts stay in place until the new package has run green for a week.
- **isofill via CFFI** assumes it can be called as a library. It is currently a
  program with a `main`. If that proves awkward, a subprocess with a shared
  memory-mapped raster is the fallback and costs milliseconds, not seconds.
- **The local second pass** is an approximation, and if its seam is visible the
  preview loses its value. Measurable early: solve locally, solve globally,
  compare. Do it in phase 4 before building the rest on it.
- **Overpass** is a dependency the editor cannot control. Everything it provides
  is cached and the editor works, degraded, without it.

## Decided

Recorded so the reasoning is not relitigated:

| | |
|---|---|
| language | Python with PySide6; `isofill` stays C |
| `isofill` | consumed as `libisofill`, no stable ABI, version check at load |
| repository | Danu's own; the 16 producing scripts move in, the 3 consumers stay |
| `ogf-server-scripts` | gains nothing, depends on nothing, renameable at will |
| shared code | none needed - the producer moved, so both sides are one codebase |
| naming | the `dem` prefix goes, in scripts, units, modules and tests |
| preview | local and exact for pass 1, local and approximate for pass 2, exact on idle |
| fidelity | the same `isofill` and the same parameter file as the build |
| increments | configurable, 10 m and 50 m, on `2`/`w`/`s`/`x` |
| ladder | inferred per square, overridable, zone default |
| handoff | files by email; a drop point is under *Later* |
| ownership | advisory, never blocking |
| packaging | a `.deb` on system paths, and desktop installers, from one CI |
| testing | pytest, pytest-qt, hypothesis, and a golden-surface regression |
| sequencing | move, then rename, then the API rebuild goes live |

## Open questions

Nothing about the design. What is left is what building it will answer:

1. **Can the move keep its history?** `git filter-repo` can lift a path set with
   its commits, and these files carry the reasoning behind most of the elevation
   decisions of the last two months. Worth an hour; not worth a week.
2. **Is the local second pass good enough?** Phase 4 measures it against a
   global solve. If the seam shows, the preview loses most of its value and the
   answer is a coarser but global preview instead.
3. **Does Windows package cleanly?** Qt and GDAL together, plus a C library
   built for it. The phase 0 CI build is there to find out early rather than at
   the end.
