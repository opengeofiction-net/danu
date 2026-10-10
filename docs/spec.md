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

Not part of the server DEM process. `danu-build-zone` stays as it is, building
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
- **R4** New nodes, ways and relations take negative ids, as JOSM gives them,
  unique within the square's file and no further: a square is edited, sent and
  built as one file, and nothing in the process merges two squares' ids. The
  editor allocates below the lowest id the file holds. `id-blocks.conf` is
  not involved - it allocates the *published* contour PBF's positive ids, one
  block per zone, because the zones are merged into one render database; that
  is the build's business. (Gobras' squares happen to hold disjoint id ranges,
  which is the JOSM counter of whoever drew them and not a rule; the manual
  process never enforced more than the file, and neither does this.)
- **R41** A square carries relations as well as nodes and ways, and they are
  read, edited and saved like the rest of it. A lake with an island in it is a
  multipolygon with an inner ring and there is no other way to say so.
- **R5** Blank square templates can be created for squares nobody has drawn.
- **R42** A square holds something worth building when it carries an elevation,
  a coastline or water. A square of nothing but water is a square somebody has
  drawn, not one of the blanks handed out.
- **R6** The contour ladder is inferred per square, with a per-square override
  and a zone default.
- **R7** The territory and owner under the working set are shown, from the
  wiki's territory administration JSON joined to the daily published
  `territory.json` polygons on the relation id. Advisory: opening a square
  somebody else owns warns and proceeds.

### Map and layers

- **R7a** The map is dragged with the right button, as JOSM does it. The left
  button belongs to the tools: on ground as thick with contours as Gobras
  almost every press lands on one, so left-drag panning is not something a
  mapper can rely on. Zoom and the current tool are on the map as well as on
  the keys.
- **R8** Any OGF tile layer as a backdrop - `ogf-carto`, `ttopo`, `cyclogf`,
  and any other the config names - each with independent opacity.
- **R9** The interpolated surface overlays the map as hillshade or colour ramp,
  with its own opacity.
- **R10** Two ramps: traditional elevation (green - brown - white) and spectral
  (blue - green - yellow - orange - red).
- **R11** Ramp scaling: autoscale to the working set, manual min/max, and *pinch*
  - narrow the ramp to a window around a chosen elevation so local relief reads
  clearly on ground that is otherwise all one colour. The colour scale on the
  map is the legend and the control: drag its marker to set the centre, wheel
  over it for the width, right click or a key to centre it on the active
  elevation. (Called *pitch* until the phase 3 review, which had no idea why.)
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
- **R19** While drawing, the surface updates locally and immediately. It is
  rebuilt exactly on demand, and of its own accord when the preview cannot
  stand in for it. The two states are distinguishable at a glance.
- **R20** Where the first pass found no answer - `OUT_OF_REACH`, `NO_ELEV`,
  `ONE_LEVEL` - the editor says so, as an overlay. This is the single most
  useful thing it can tell a mapper: *here is ground your contours do not
  describe*.
- **R21** The envelope the contours describe, as `danu.surface.drawn_mask` computes it,
  is drawn as an outline. Beyond it the fill does not reach, and a spot height
  constrains the ground inside it but never extends it.
- **R22** Ground outside the working set is shown from the **published** DEM and
  hillshade, fetched as tiles from `data.opengeofiction.net`. Live surface for
  the 3x3, last night's build for everything else, with a visible seam between
  them so nobody mistakes one for the other.

### Water

- **R23** Rivers, streams and water bodies are imported from Overpass into the
  square, not held beside it. A square stays self-contained: opened, edited and
  built from its own file, with or without a network.
- **R24** Set an elevation on a water body or a waterway, by hand or from the
  contours it touches.
- **R25** Burn a river into the terrain: where the contours climb along it,
  bend them so that it descends, at a chosen strength and as often as wanted,
  each time as a proposal the user accepts or rolls back.
- **R26** Flatten a water body at a level: the level goes on its outline, the
  contours inside it are removed and those crossing its shore are pulled back,
  as a proposal likewise.
- **R27** Flowing water is never flattened. A river area descends along its
  course.
- **R40** A second import reconciles rather than duplicates. A feature the
  square already holds is matched by its OSM identity, takes its geometry from
  upstream and keeps the elevation set on it here; a feature gone from upstream
  is reported rather than deleted. An import is one undoable step.
- **R28** Water anchors inside the squares are first-class and editable. The
  separate `water/<zone>.osm` overlay is a legacy artefact to read, never a
  store to write: only `roantra` has one, 54 MB of it, against 32 zones, and
  every other zone's water lives in its squares where Danu already edits it. Reading roantra's overlay for context is cheap and
  worth doing; editing it is a separate job with no second user.

### Spot heights

Numbered from R36 because the earlier numbers are cited from the code.

- **R36** Nodes with `ele` inside the squares are first-class and editable.
  A node carrying `ele` is a constraint, the same as a contour way.
- **R37** A spot height is the only thing which shapes a hilltop. Contours
  cannot say how high a hill goes.
- **R41** The main map's peaks, volcanoes and saddles with a height are
  imported from Overpass into the squares as spot heights, where the contours
  are; a second import reconciles as R40 says, the height set in the square
  kept, and lists each the main map gives otherwise for the mapper to take.

### Checks

- **R29** Rivers which climb, per `demRiverCheck.py`, listed and clickable.
- **R30** Ways over 2,000 nodes, which the OSM API would reject, and over
  10,000, which GDAL silently truncates. Split on save.
- **R31** `ele` values which are not numbers.
- **R32** Sea level lines which do not lie on a drawn coastline, per
  `demCheckZeroLine.py`.
- **R33** A water body spanning more than one contour.
- **R38** A spot height which contradicts the contours around it: one which
  does not lie between the elevations of the rings enclosing it, or, in no
  ring, within a step of the contours nearest it.
- **R39** A closed contour ring with no spot height inside it. A report rather
  than a warning: plenty of rings are the foot of a slope, not a summit.

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
purposes: the producer's `relief.ramp` colours the relief rasters it
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
    core/          squares (`square.py`: names, reader, working set), ladder, edits, undo, id allocation
    surface/       constraints, isofill driver, incremental engine, ramps
    water/         Overpass client and cache, grading, bodies
    checks/        every validation rule
    cli/           the command line: what the server runs, and what CI runs
    ui/            PySide6, presentation only
  server/
    bin/           the build scripts; shell today, see phase 0
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
machine. `server/bin` was meant to be a thin wrapper over `danu.cli`, so the
logic would live where the editor and the tests can reach it. It is not: the
orchestration is still the shell scripts it arrived as, and `danu.cli` is
empty. See *What phase 0 actually did*, in `implementation.md`.

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

On the desktop, XDG: `~/.config/danu/`, `~/.cache/danu/` for the tiles and for
whatever an Overpass reply is worth keeping between one import and the next,
`~/.local/share/danu/` for sessions and recovery. An imported feature does not
live there - it lives in the square, per *R23*.

There is no service tier. Danu is a desktop application plus a set of batch
entry points. If a long `isofill` run wants its own process so a crash cannot
take the editor down, that is a detail inside `surface/`.

### Threads

Three, and no more.

- **UI** owns Qt and nothing else blocks it.
- **Compute** owns the constraint grid, isofill and the ramp. One worker, a
  queue of jobs, newest wins - a stroke in progress supersedes the job the last
  stroke queued.
- **Network** fetches map tiles, cached on disk, and Overpass, whose answer is
  written into the square.

### Why the preview can be exact locally

A cell's first-pass value depends only on contours within `radius`. Recompute a
box grown by `radius` around an edit and every cell in the original box gets the
value a whole-raster run would give it - bit for bit. This is the same argument
that made the banded first pass exact.

The second pass has no such property. Laplace diffusion is global: a change
anywhere moves everything, by less and less with distance. A local solve holding
the surrounding surface fixed at the box edge is therefore an approximation, and
a good one, because the boundary it holds is the answer the last full solve gave.

F3 measured how good, and the sizes below are its answer rather than a guess.
Two distances matter and they are not the same one. **Cover** is how far past
the edited box the patch reaches, and it decides what is left showing the old
surface; **slack** is the clearance the solve keeps beyond the patch, on top of
the radius, and it decides what the patch gets wrong. Both want two radii; see
*F3, the local solve* in `implementation.md`.

| when | patch covers | solved | pass 1 | pass 2 | cost |
|---|---|---|---|---|---|
| while drawing, coalesced over 30 ms | box + 2 radii | + 3 radii | exact within | local, ~0.27 m | 63-73 ms |
| on idle, 10 s | whole working set | all | exact | exact | 5.6 s at 3", 114 at 1" |

The budgets this table used to carry - 30 ms while dragging, 200 on release,
two seconds to idle - were guesses made before any of it existed, and three of
the four have since been measured or settled. There is no *on release* state:
nothing watches for the pointer coming up, and the coalescing timer covers what
it was for. The costs above are measured; see *F5b* in `implementation.md`,
which is also where the 50 ms this phase ends on is still missed.

They are the cost of *working out* the new surface, and not of seeing it. The
same edit takes 378 ms from the command to the frame, because the contour layer
redraws a third of a million points on every paint; see *F5c* in
`implementation.md`. A reader taking 63 ms from this table as what an edit
feels like would be wrong by a factor of six, which is the sort of thing a
table of measured costs invites.

The drag and the release solve the same ground: at 1 arcsecond a small edit is
about 130,000 cells against the working set's 77.8 million, so there was no
saving worth having in solving less during the drag and being wrong by more.

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

The wheel zooms, which is what a hand on a map expects. Ctrl and the wheel step
the active elevation by the small increment, ctrl and shift by the big one, and
alt is given to the opacity of the active overlay.

It was the other way round - wheel to step, ctrl to zoom - until the phase 3
review, where reaching for the wheel to zoom and changing the drawing elevation
instead was the thing that would not stop happening.

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

- **Burn a river.** Where the selected river climbs against the contours, bend
  them back from it so it descends, at a strength, and again if once was not
  enough. Shown as a proposal: the affected contours highlighted, the surface
  updated, accept or roll back. This is the experiment that prompted Danu, and
  it belongs here rather than in the build precisely because it needs judgement.
- **Flatten a body.** At its outlet level, its rim's lowest contour, or a value
  typed in: the level on its outline, the contours inside it removed, those
  crossing its shore pulled back. Same accept-or-roll-back shape.
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
list of rings of `[lat, lon]` - latitude first, measured against the file on
2026-09-19; a bare ring where a territory has one, a list of rings where it has
several - 1,103 entries and 1.5 MB, with no attributes -
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
  tagging convention first. This is *texture*: inventing plausible roughness
  where nobody has drawn any, which is a different thing from R36's spot
  heights - those only say where the ground already is.
- **Typed elevation features** - `natural=peak`, `saddle`, `sinkhole` read as
  what they are, and areas carrying `ele` held flat the way R26 holds a water
  body, which is what a plateau wants and what karst is mostly made of.
  Deferred until spot heights are carrying their weight.
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
fixture through `danu-build-zone` and assert it produces the same thing. That is
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

What each phase set out to do is here. What each one turned out to involve is
in `implementation.md` alongside, section by section.

### Phase 0

**Phase 0 - move the pipeline.** Create the repository. Move the nineteen
scripts and their configuration in, with history where git makes that easy.
Restructure the logic into `danu.core`, `danu.surface`, `danu.water` and
`danu.checks`, leaving `server/bin` as wrappers so the operational commands are
unchanged. Pin `isofill`. Stand up pytest, CI on Linux and Windows, and a
`.deb`. Then the fixture: one real square, the shared parameters, a reference
surface, and a regression test asserting the surface is reproduced cell for
cell.

Deploy it to `util`, remove the `dem*` scripts from `ogf-server-scripts`, and
let a nightly build run from the new package. No UI.

Ends when the nightly build has run green from Danu for a week, and the only
`dem` left in `ogf-server-scripts` is the three consumer scripts and their
units. Green has to mean built, not skipped: a zone is only rebuilt when its
squares change, so an unattended week would mostly hash the squares and stop,
and prove nothing about whether a zone still builds. `danu-soak` forces two
zones a night, in sorted order from a cursor.

The soak's budget is what "a week" means here. It counts nights on which a
rebuild was queued, not calendar nights: the nights before it was seeded were
no-ops and are not evidence, and a night whose build fails holds its list and
retries free until it passes, so the budget buys six builds however long they
take. Six were seeded on 2026-09-18. That is twelve zone-builds out of
thirty-two, so it samples the zones rather than covering them - the claim being
tested is that the moved pipeline still builds, not that every zone is good.

The notes on what this phase actually did are in `implementation.md`,
under *What phase 0 actually did*.

### Phase 1

**Phase 1 - viewer.** Map, tile layers with opacity, open a 3x3 working set,
draw contours as vectors over it, no editing. Ends when a mapper can look at
their square. It also carried the debt above - `isofill` building on the Windows
runner for real - which landed first, by way of MSYS2 rather than a Makefile
change, before the editor grew anything that would make the answer harder to
hear.

The notes on what this phase actually did are in `implementation.md`,
under *What phase 1 actually did*.

### Phase 2

**Phase 2 - the surface.** The question phase 0 left is settled, for now, the
second way: the golden test grows a second case driving the editor's own
surface path over the same fixture, and the shell build is left as it is.
Decided on 2026-09-19, and not because the architecture with `danu.cli` at
the centre is wrong - it is still the preferred shape - but because rewriting
the build during the phase that puts a surface on screen would pull the rug
from under phase 0's validation, which is still running, and because the
second way tests the property the architecture exists for: that the two paths
agree. It also leaves the first way open. The editor's functions *are* the
per-step implementation `danu.cli` would wrap, so if phase 4's incremental
path wants the shell calling Python step by step, the port becomes wrapping
code that already passes the golden reference rather than writing code that
does not yet exist. Re-evaluated at phase 4, and again at the end, with the
outcome written under that phase's *What it actually did*, as phases 0 and 1
have theirs.

Two requirements on the editor's path, so that the second way is honest. It
must read every parameter from `params/elevation.toml` with no defaults of its
own: a key the file lacks is an error, not a value, so the two paths cannot
quietly disagree about something one of them assumed. The `params.lock` test
holds the reference to the values in that file for the keys it names; the
editor's path is held to the same file, and the cell-for-cell comparison is
what catches anything the lock does not name. And each shell step it
reproduces must carry a one-line mapping to the GDAL call it stands for,
beside the code - a `shell:` line a test looks for on every stage function, so
the convention cannot be the first thing dropped under time pressure.

A correction, found while building this: an earlier draft here called
`elevation.toml` "the file the shell reads", and it is not. `danu-build-zone`
carries the same values as `${VAR:-default}` constants and reads no file. Until
it does - a change to the build, deferred while phase 0's soak runs against it
- a test holds the shell's constants equal to the file, key by key, so the two
paths at least start from the same numbers and a change to one without the
other goes red. The file itself moved into the package (`danu/params/`) so the
editor can read it once installed, with `params/elevation.toml` a symlink to
it, as `relief.ramp` and `osmconf.ini` are.

`isofill` as a library - through `ctypes` rather than the CFFI named here,
since the API is plain C arrays and the standard library does it with one less
package to ship on every platform - whole-set rebuild, hillshade and both ramps
with all three scaling modes, unreachable-ground overlay, envelope outline.
Slow and exact.

Ends when a test asserts the two paths agree: the golden fixture driven through
the shell build - the first case, which exists and runs `danu-build-zone` - and
through the editor's own path - the second case, run both ways the editor can
call `isofill`, as a binary and as a library - all compared cell for cell to
the one reference. That assertion is what closes the risk. Showing the same hillshade on screen demonstrates it
once, for one square, on one afternoon.

The notes on what this phase actually did are in `implementation.md`,
under *What phase 2 actually did*.

### Phase 3

**Phase 3 - editing.** Draw, continue, move, delete. Elevation control in full.
Snapping. Undo. Save to `.osm.xz` with id allocation and long-way splitting.
Ends when a square can be drawn from blank and built by the server unchanged.

The notes on what this phase actually did are in `implementation.md`,
under *What phase 3 actually did*.

### Phase 4

**Phase 4 - live.** The incremental path, the job queue, preview and exact
states.

It was to end when drawing a contour moved the hillshade under the cursor
inside 50 ms. That was written when an edit was one thing happening on one
thread. It is now three: the editor's own work, a coalescing window that waits
for the rest of a gesture, and a solve on a worker. One number over the sum of
those says nothing about any of them, and at 1 arcsecond nothing makes the sum
50 ms - the solve alone is a second and a half.

So it ends on two clocks, measured through the real window on the gobras 3x3,
at the z15 to z19 where contours are drawn:

- **the editor takes the next input inside 50 ms.** Eight, at 3 arcseconds and
  at 1: `layer.refresh` and the signals `do` emits, and nothing else is on the
  UI thread. **Met.**
- **no frame waits on the surface.** The solve, the compose and the build are
  all on workers, and what an edit costs the UI thread does not grow with the
  resolution - eight milliseconds at both, against a solve that goes from 52 ms
  to about 1.4 s. **Met.**

The fifty is the same fifty, applied to a narrower thing. The old one covered
the whole frame, fill included; this one covers the UI thread alone. That is
the right narrowing rather than a convenient one, because the number was always
a statement about the frame and not about the fill - F5c is where that
distinction stopped being academic - and the fill has since moved off the
thread the frame is on. What it leaves open is not latency but policy: whether
a long editing session should be waiting on those builds at all. That is phase
7's.

The notes on what this phase actually did are in `implementation.md`,
under *What phase 4 actually did*.

### Phase 5

**Phase 5 - the anchors that are not contours.** Water and spot heights - the
two things that say where the ground is and are not contours.

**G1, spot heights are constraints.** R36 says a node with `ele` is a
constraint the same as a contour way, and nothing has ever read one: `collect`
gathers only the lines layer and `rasterise` burns that alone. So this is a
change to the pipeline the server runs, not an editor feature, and it goes
first and by itself. It moves the published DEM for any square holding such a
node, which is a deployment to plan rather than a surprise to discover.

What it is, concretely: `osmconf.ini`'s `[points]` lists `ele` under
`unsignificant`, so GDAL's OSM driver does not report a node carrying only an
elevation at all, and `attributes` there does not name it either. So `ele`
moves into `[points] attributes`, `collect` emits a points layer beside the
lines, and `rasterise` burns both. Same input files, no new dependency and no
new data file - what it costs on deployment is a rebuild of any zone whose
squares hold such a node, which is a DEM change and not a packaging one.

Measure before building on it. `barrier_cells` widens a constraint for the
sight test, so a one-cell spot height becomes a five-by-five occluder. A
contour is a line and hardly notices; a point is not.

**G2, the editor edits them.** Place, move, delete, set `ele`; the elevation
keys and the ladder working on a spot height as they do on a contour; and the
preview burning them, which means `preview.Contours` gains the points layer it
does not have. `Node.tags` already survives a read and a save, so the data
round-trips today and only the two ends are missing.

**G3, the square carries relations.** `read_square` skips a relation and
`write_square` writes none, so a square is nodes and ways. A water body is as
likely to be a multipolygon as a closed way - gobras has 120 water relations,
Lake Kinser among them - and a lake with an island in it *is* a multipolygon
with an inner ring. There is no way to hold one as closed ways, and nothing to
do with the island if it is lost: R26 flattens a body at a level, and a
flattened body with no hole in it puts the island under water.

So the model grows: a `Relation` of members and tags beside `Node` and `Way`,
read in file order, written back in it, and minted negative ids from the same
allocator - which already takes one counter across two namespaces and now takes
it across three. The property to hold is the one `write_square` already holds
for ways: a square opened and saved differs from the square that was opened
only where it was edited. It goes before the import because the import has
nowhere to put a lake until it does.

It also makes one thing true that the pipeline currently assumes is not. The
spot-height guard counts `ele` tags outside a way element and its comment says
a relation carrying one is not a thing these squares hold; once they do, and
once R26 flattens a body by putting `ele` on it, that is exactly what they
hold. The guard warns rather than refuses, which was the right call for a
different reason and remains the right call for this one.

**G4, water is imported into the square.** R23, and the reason it is an import
and not a cache: a square is opened, edited and built from its own file, and a
working set that needs the network to describe its own rivers is not
self-contained. Features arrive carrying the OSM id they had, positive, which
is what a later import matches on; `IdAllocator` mints below the lowest id in
use and takes 0 as its ceiling, so positive ids never move it and nothing
collides.

**An import may bring a square into being.** Measured over the gobras 3x3,
features land in two squares the working set has no file for - 355 of 4,673
between them - and the alternatives are both worse than creating the file:
dropping them silently, or holding them in memory until a mapper notices. A
square of nothing but water is already a shape this data has, in that squares
carrying only a coastline are present in the zones today.

That widens what counts as a drawn square, which R42 now says: an elevation,
a coastline, or water. `has_constraints` asks for an `ele` tag and nothing
else, which catches a coastline because one is tagged `ele=0`, and misses a
square of imported rivers entirely - it would be read as one of the blank
templates and left out of the build. Widening it changes which squares the
nightly build reads, so it is a deployment to measure the way G1's was rather
than a line to change quietly.

**G5, a second import reconciles.** R40, and the hard half of G4. A feature the
square holds already takes its geometry from upstream and keeps the elevation
set on it here - upstream owns where the river is, the mapper owns how high it
is - and a feature gone from upstream is reported rather than deleted, because
a square is somebody's work and an import is not entitled to throw it away. One
undoable step, so the answer to a bad import is Ctrl+Z.

**G6, elevations on water.** R24: a level on a body or a waterway, by hand or
from the contours it touches. The grading is the rule the old per-zone water step used -
a waterway takes each contour's value where it crosses one, graded between and
forced to descend; a body takes its outlet - made per-feature and interactive
rather than per-zone and unattended.

**G7, burn and flatten, as a proposal.** R25 to R27, in the editor and only
there: water shapes the surface through the contours and levels the editor
writes into the squares, and the build reads no water. The squares then
describe themselves - contours that agree with the water, whoever opens them -
the server pipeline stays as it is, and the editor's surface stays the
server's. Accept and roll back go through the undo stack rather than a
mechanism of their own: a burn is an edit to contour ways, and Ctrl+Z is what
a mapper will reach for.

Three parts, in this order:

- **G7a, flatten** (R26). The level goes on the lake's outline as `ele`, where
  the build already reads it: a closed way's own, or a relation's member ways -
  refused where a member is shared with flowing water (R27). An island's ring
  takes the level too and keeps its own contours. Contours inside the water are
  deleted, not kept as bathymetry; contours crossing the shore at another level
  are pulled back from it, as far as the strength says. The shore alone does not
  fill flat - isofill declines ground that sees one level all round, as a
  hilltop does - so for now straight fill lines at the lake's level cross the
  water every 120 m, tagged `danu:fill`, to be deleted in one pass once isofill
  holds a marked one-level enclosure flat, lakes and plateaus alike. When a
  re-import changes a flattened lake's outline, the lake is reported for
  flattening again.
- **G7b, burn** (R25). From a span the grade left ungraded because the contours
  climb, the whole run it is part of: from where the river leaves its level to
  where it is back down to it. Every contour above that level is kept back from
  the whole stretch, one step further for each contour above it, so the river
  runs in a notch whose sides rise one contour per setback; what lies nearer is
  clipped out and closed along the notch's edge on the high side - a closed
  contour the river runs through becomes two, a contour wholly inside is cut
  away. The setback, metres per contour step, is the strength.
- **G7c, what is left.** A river level that contradicts a contour beside it -
  a contour within a cell of the river, more than a contour step above or below
  its level - listed with the rest of what a grade found, for the mapper to move
  the contour or fix the level.

**G9, spot heights from the main map** (R41). As water is imported, the main
map's peaks, volcanoes and saddles with a height that reads as metres or feet,
by their own action; one with none, or an unreadable one, is skipped and
counted, and one the set holds that upstream no longer answers is reported and
kept.

It ends on three measurements, taken on the gobras 3x3 as the mapper left
it - the contours tidied, the main map's spot heights imported - with the main
map's water imported over it, every river burned and every lake a grade could
level flattened, and built by the server's own `danu-build-zone`:

- **a flattened lake has one elevation, in the editor's surface and the
  server's alike.** 228 lakes flattened; on the server's 1 arcsecond DEM
  99.15% of their 74,317 cells lie within half a metre of their level, against
  28% before, and 200 of the 215 with a cell are wholly at it; the editor's 3
  arcsecond surface 99.33%. **Met** - the misses are sea-level lakes the land
  clamp lifts to 1 m, which it does to any enclosed water at 0 without a water
  file, and shore cells of lakes a few cells across.
- **the climbing ascent left on the spans a burn was run on, against before
  it.** Along the 28 rivers burned, 259 km, the server's DEM climbs 3,120 m
  where it climbed 5,046 - 38% less, less on 26 of them; by the grade, 130
  climbs and 3,058 m to 44 and 978 m. On the hillshade a burned crossing
  reads as a valley cut through the spur, its walls straighter than the ground
  round them. **Met**, as a reduction: what is left is the climbs the burn
  refused, and ground no burn reached.
- **a hill with a spot height on it comes out pointed, at the spot height's
  value.** Of the 38 summits that are one spot height above its ring and
  alone in it, the DEM is the spot height's value at every one, and the top is
  one cell for 89% of them and eight at most; the same rings without them top
  out flat, a median of 36 cells. **Met.**

The profile tool was named here and is phase 6's, with measure and difference:
it is how you read a surface, not how you anchor one.

The notes on what this phase actually did are in `implementation.md`, under
*What phase 5 actually did*.

### Phase 6

**Phase 6 - checks and polish.** The validation panel - its first check,
crossing contours, brought forward into phase 5 as G8a, ahead of the burn:
gobras holds contours that cross dozens of others, and a river crossing one
reads as a climb a burn would bend real contours to fit. A contour crossing
itself followed as G8c, with the loop cut out; G8d split and join to mend what
the checks find; and G8e the rest of R16 - a node two levels share, which
unglues, and contours lying on one another, the duplicate coincident contours
of the validation table. And R38, a spot height which contradicts the contours
around it, came forward with G9, which brought the main map's in. What is left,
in six steps:

**H1, the squares' own checks** - what the files say, with no surface: ways
over 2,000 and 10,000 nodes (R30), split on save but listed until then; `ele`
that is not a number (R31), which the build drops and says so only in its log;
the off-ladder values used once or twice, rows rather than the advice line;
water spanning contours (R33); and rings with no spot height (R39), a report
under its own heading rather than a warning. Each an index kept as edited, as
the four there are.

**H2, the surface's checks** - what only a build can say, from the last exact
one and said stale while a preview stands: rivers which climb on the DEM (R29),
`checks.rivers` - the surface's view, where the grade's climbs are the
contours'; sea level off the drawn coastline (R32), `checks.zero_line`; and the
unreached ground as area and fraction, R20's overlay counted. Both modules are
batch tools today; they become the panel's.

**H3, reading the surface.** Profile - drag a line, terrain and water along it,
the climbing shaded, the grade's profile plot reused; measure, distance and
gradient between two points; difference, the working surface against the
published DEM as a diverging ramp; and magnify, a loupe at the cursor. And two
ways of showing it: slope, a fourth mode beside shaded relief, hillshade and
relief; and a scaling that stretches the ramp over the ground in view, where
auto stretches it over the whole set.

**H4, not losing work.** Autosave to `~/.local/share/danu/` on a timer and on
idle, never over the mapper's files, as a change file rather than the square:
an `.osc` per dirty square of what the edits since its last save created,
modified and deleted, against the file it was read from - so its cost is the
size of the edit, not of the square, where a whole square is seconds of xz.
Recovery offered at the next start, square by square: the square read from its
file and the change applied, refused and said if that file has changed since
the change was written; a session file - the
working set, the view, the panels - reopened as it was; and a usage log,
written beside it: each click with the tool, the snapped node and the action
it made, so a reported bug can be replayed rather than described.

**H5, Danu and JOSM.** The water and the peaks are fixed in JOSM, against the
main map; the surface they are fixed against is Danu's. J already shows the
place in JOSM and selects what came from the main map, and only the place for
what was drawn here. Danu serves its surface as a WMS on the loopback, and
JOSM's `/imagery` adds it as a layer, so the ground under the water being
edited in JOSM is the ground Danu has built.

**H6, the interface reviewed and reworked**, last so that it covers what the
phase added - the panels, the keys, the menus and what the status line says -
with the maximum zoom among it, below.

Ends when every row of the validation table is a row in the panel, each a
place to go to; when Danu killed mid-edit on the gobras 3x3 loses no more
than the autosave interval, the next start putting the edits back; and when
the working surface shows in JOSM as a layer.

**Revisit z19 as the maximum zoom**, in H6. It is the tiles' limit, and the map
stops there (`mercator.MAX_ZOOM`), but the editor's own layers are vector and
would draw at any zoom. On the gobras set it leaves features that cannot be
picked apart: the Water of Meeonoa, a `waterway=stream` (way 4878968), runs
inside a narrow `natural=water` + `water=river` area (way 4878947), a median
1.4 m from its outline and sharing a node with it. At z19 that is about 5 px,
inside the 8 px pick tolerance, so a click on the stream is in reach of both
and no zoom separates them. To weigh when it is taken up: zooming past the
tiles' limit with them stretched; preferring a line to an area's outline when
both are in reach; and cycling through what is under the cursor on repeated
clicks, as JOSM does.

### Phase 7

**Phase 7 - the surface while editing.** Three things about building a
surface with a mapper waiting on it, held together because they are the same
subject and separately because none of them blocks anything.

**When a rebuild happens.** R19 says the surface is rebuilt exactly on idle,
and phase 4 made that work: fresh ground triggers a rebuild and the timer
covers the rest. What using it has shown is that automatic is the wrong default
for a long editing session. A mapper drawing for an hour does not want a
seventy-second build starting every time they pause to think, and a build that
starts on its own is a build they did not choose the moment for. On demand is
the better shape there - the preview is exact enough to draw against, and the
mapper says when to settle it. What that leaves open is the detection the other
half of phase 4's item 4 was for: something still has to notice when the
preview has stopped being trustworthy and say so, rather than quietly showing
ground that is out of date.

**The first build's head start.** Opening a working set and building at 1
arcsecond draws nothing for a minute and a half, because a first build has no
previous surface to leave on screen. Solving the ground the view covers between
the cheap stages and the fill puts it up in about three and a half seconds - a
window costs the window, and the fill is 92.5% of the build. Written and
measured, and parked here rather than merged: it belongs with the rebuild
question above, since what it is really doing is deciding what to show while a
build a mapper did not ask for is running.

**The out-of-core second pass.** `isofill`'s banded pass 2 is an approximation,
and the error is a streak on every band join: measured on the gobras 3x3 at 1
arcsecond, every one of the 964 cells wrong by more than 100 m sits within
thirty rows of a join, and the worst is a trench a hundred metres below the
contours enclosing it. A mapper would read it as terrain. The cause is that
each band's margin rows are pinned to the coarse answer, so a free interior
meets a boundary carrying 1-in-4 detail; widening the margin moves that
boundary rather than removing it, and has been tried. The candidate is a
reconciliation across each join once the bands are written. See `isofill`'s
README.

Nothing Danu does today depends on that last one: the committed surface is
built whole, and the preview's local second pass is a different path that F3
measured separately. It becomes real when a zone will not fit - a question of
raster size, not of anything the editor chooses.

Ends when a long editing session never waits for a build it did not ask for,
never draws a surface it cannot vouch for without saying so, and a raster
forced out of core matches the same raster solved whole to the interval rather
than to hundreds of metres.

### Phase 8

**Phase 8 - release.** Installers for Linux and Windows, GDAL and Qt bundled,
`isofill` built for both, a settings UI, first-run help, and somewhere for a
crash to go. Ends when someone who has never opened a terminal can install it
and draw a contour.

### Phase scheduling

Phases 1 to 4 are the spine; 5 onward are separable and could ship in any
order. Phase 7 is the odd one: it is partly work in `isofill`, and it is the
only phase whose contents arrived by using the thing rather than by planning
it.

Because Danu is meant for other OGF mappers rather than for one machine,
packaging is not deferred to the release phase - only the *polish* is. A
Windows build of `core` plus `isofill`, produced by CI and installable, was
meant to be a phase 0 deliverable that stayed green from then on; it was not
delivered, and CI hid that - see *What phase 0 actually did* in
`implementation.md`. It is owed by phase 1. The alternative is discovering at
release that a choice made in phase 2 cannot be shipped, which is the usual way
this goes wrong. Being a tool for other people also means their machines are
not yours: no terminal, no `PYTHONPATH`, no system GDAL, and an error message
that says what to do rather than what failed.

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
- **Overpass** is a dependency the editor cannot control. What it provides is
  imported into the square rather than held beside it, so a square that has
  been imported into once needs it no further and the editor works without it -
  see *R23*. What is exposed to an outage is the import itself, which is a
  thing a mapper chooses to do rather than something every open waits on.

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
| map canvas | `QGraphicsView` in Web Mercator with our own tile layer; not QtWebEngine, not QtLocation |
| reading squares | stdlib `lzma` + `ElementTree.iterparse` in `danu.core.square`; no pyosmium in the editor |
| extent | from the filename, or the name a caller already parsed from it - never the nodes; JOSM frames sit inside the degree |
| ids in squares | negative, unique within the file, allocated below the lowest it holds; `id-blocks.conf` is the PBF's, not the squares' |
| editor config | TOML via `tomllib`, user file under `QStandardPaths` |
| tile cache | `QNetworkDiskCache` |
| phase 2 path | a second golden case over the editor's own surface path; the shell build untouched; `danu.cli` still the preferred shape, re-evaluated at phase 4 and at the end |
| panning | the right button drags the map, as JOSM does; the left belongs to the tools, because on this ground almost every press lands on a contour |
| the wheel | zooms; ctrl and the wheel step the elevation, ctrl and shift by the big step, alt the overlay's opacity |
| redrawing | a line from a contour back to it replaces the stretch it was drawn along, ends when the line ends, and never touches a coastline |
| crossings | warned live, and refused on what results - so a redraw may cross the stretch it is replacing, which goes with it |
| moving a contour whole | shift and a drag carries it, as one step; one that already crosses others moves freely, being repaired, and is told how many it crosses now; one that crosses nothing may not be moved into a crossing; a node it shares with another way is copied, not moved, so it comes away |
| a contour crossing itself | listed in the checks panel, a row a place - a crossing, or a node passed through twice, or twice in a row; O proposes the loop cut out, a node put where the strands cross, the shorter side of a closed contour - or, for a node twice in a row, every such in the contour held once |
| splitting a contour | P at a node, as JOSM's: an open contour becomes two, a closed one opens there; the new ends are unglued and drawn 5 m back along their own lines, a third of a short segment at most |
| joining contours | ctrl and a drag of an end onto another contour's end, as JOSM's: one way, the first's id kept and both's tags; onto its own other end, it closes; another level, tags that disagree, a middle node, a ring, another square or a crossing refuse it and say why; without ctrl the drop is a move |
| contours that touch | listed in the checks panel: a node two levels share, a place a row, and a stretch of one contour within 1 m of another for a segment or more - a duplicate at one level, two levels in one place at two; U unglues a shared node, the contours other than the one selected each given a node of its own drawn 5 m back into its own line, a third of the way to its neighbours at most |
| a spot height the contours contradict | listed in the checks panel, judged against the innermost closed contour round it and the one round that - a hill or a hollow; on a hill it lies between that ring's level and the ladder's next rung up, turned over in a hollow; one in no ring is not judged; choosing it selects it, for its height to be set |
| a spot height beyond the contours | burned, and stretches nothing: the envelope is the contour lines', and the grid the squares that hold a way with a numeric ele - a square of peaks alone, or of a lake whose level is in feet, builds nothing |
| saving | the text taken on the UI thread, compressed and written on a thread of its own, one square at a time in the order asked; a square is clean once its own file has landed, at the history as it stood when its text was taken; a write that fails says so and leaves it dirty; a close or an open waits for the writes |
| dirty | by the last step done on the square, not how many: saved, undone and edited again is dirty |
| the checks' first scan | on a worker, the panel saying it is finding them; an edit made meanwhile is put to the indexes when they land |
| a main-map spot height beyond the contours | not imported, and counted: a new one in a square with no contour line, or past the box of its square's contour vertices - the build's envelope to the cell; one the set holds is reconciled wherever it stands |
| a spot height the main map gives another height | on a second import the square's is kept and the row listed in the import report, "698 m here, 286 m on the main map"; one button takes the main map's for the row chosen, one for every row, either one step; a row is struck through once the square's is the main map's, by the button or by hand, or the spot height is deleted here, and an undo unstrikes it |
| what the files say (H1a) | the checks panel's fifth list, a heading a kind: ways over 2,000 nodes and over 10,000, split on save; an `ele` on a way or node that is not a number; a contour at a value off the square's ladder used once or twice; a row selects the way or node; a square is asked again on any edit to it |
| what lies inside the rings (H1b) | the checks panel's sixth list: a lake with a contour at another level inside it or across it - a vertex in the water, or a segment crossing the shore - selected for F; flowing water is no body, and a contour at the lake's level or sharing a node with its shore is not inside; and, as a report under a folded heading that does not mark the map, a closed contour of 10 ha or more - `checks/bare_min_hectares` in the INI - with no contour and no spot height inside it |
| what the surface says (H2) | the checks panel's seventh list, asked of a build's own grids on its worker while the panel is open, from a snapshot of the squares taken as it started: a waterway climbing 10 m or more it cannot lose whichever way it runs, at its worst climb, worst first, and one climbing most of its way said as drawn backwards; the DEM's zero line over 1 km long and more than 500 m from a drawn shore, in a square with sea level drawn and well inside the drawn area; and a row a square with unreached ground, its area and its share of the drawn area. Said pending while a build runs, with a busy bar, and stale once an edit follows it; a sea level or a square row shows the place |
| slope (H3a) | a fourth mode beside shaded relief, hillshade and relief: the ground's slope against the ground, not the map - a Mercator cell is cos(latitude) of itself on the ground - coloured in degrees, pale on the flat, yellow by 5, orange by 15, red by 30, dark past 45; the ramp and the scaling do not apply, the sea stays clear, and the legend reads 0 to 45 degrees and does not pinch |
| the view scaling (H3a) | the ramp stretched over the land on screen rather than the whole set's, recoloured once the map has been still for 400 ms; with no land in view, the set's; the legend spans what is in view, its ends to the metre |
| measure and profile (H3b) | M, or the ruler on the map: points clicked along a line, ended by a double click, Enter or a right click, or a drag for a straight one; Backspace takes a point back, Esc clears the line. Drawn, the status line reads its length and the ground at the cursor against the start; ended, the profile panel gives its length on the ground, the ground at its ends, the rise and gradient between them, what it climbs and falls along the way, and the steepest it gets, and draws the ground a cell apart with the contours it crosses at their values and the water at its level - a lake's, a river's between the levels on its vertices - or, switched to slope, the ground's slope as the map's slope mode gives it, with what it crosses as ticks; under the line, each stretch filled in the colour the map gives that place, by its slope while the map shows slope and grey in hillshade. Hover for the ground and slope at a place, marked on the map; a click takes the map there. No climbs are shaded: on a line drawn anywhere a climb is only the ground going up, and a river's are the grade's. The ground is the exact surface's: while a preview stands the panel says so, and it is drawn again when the exact build lands. An ended line stays with the other tools, measured again once edits pause for half a second |
| the difference (H3c) | a fifth way of showing the surface: the exact build less the zone's published DEM, `dem-<zone>.tif` from `data.opengeofiction.net/dem/<zone>/`, warped onto the map's grid - red higher than published, blue lower, a diverging ramp either side of nothing changed, clear under half a metre so the map shows through; the legend reads ±the span, the 98th percentile of what changed rounded up, never under 5 m, and does not pinch; the status line reads "changed +12.0 m", "unchanged" or "not published". The published DEM is fetched when the difference is first shown and kept in the cache, asked again with If-Modified-Since, and the copy held is used, and said, when the server cannot be reached. Of an exact build only: worked out as one lands, and a preview leaves it as it was |
| the status line's reading | bottom right, after the active elevation: what the surface on screen reads under the cursor - "ground 182 m", or "slope 11.1°" while slope is shown, "sea" at sea level - from the arrays the layer draws, so a preview reads as it looks; nothing off the surface or with none built |
| a spot height in no ring | judged against the first contour met in each of eight directions within 3 km: more than a ladder step above the highest of them, or below the lowest, is listed with the spot heights R38 finds, "in no ring, the contours nearest it 5 to 7 m"; fewer than six directions meeting a contour is too little to judge by |
| the checks' first scan, seen | the panel brought to the front, a bar a check naming the one it is on, the lists and buttons put away until there is something in them, and the status line saying so - and how long it took when it lands |
| JOSM | J, or the Show in JOSM button in the checks panel and the import report: JOSM's remote control `/zoom` at `http://127.0.0.1:8111` (`josm/url` in the INI) to the box the map shows, selecting what is selected if it came from the main map - a positive id; nothing is downloaded, and a refusal or a JOSM not running is said in the status line |
| the pinch key | C, the surface's pinch, since P became the split |
| tests and the network | none of them reach it: the tile and territory fetchers are pointed at fixtures at conftest import, not in a fixture |

## Open questions

Nothing about the design. What is left is what building it will answer:

1. **Can the move keep its history?** `git filter-repo` can lift a path set with
   its commits, and these files carry the reasoning behind most of the elevation
   decisions of the last two months. Worth an hour; not worth a week.
2. ~~**Is the local second pass good enough?**~~ **Answered: yes.** Measured
   against a whole-raster solve in F3, a patch covering the edit by two radii
   and solved with two radii of clearance is wrong by at most 0.268 m over
   eighteen edits on the gobras 3x3, 0.035 m at 1 arcsecond, and exact on the
   hardest case found. Those radii have since changed, and so has that last
   figure - the hardest case is 0.000061 m out now rather than exact, which
   leaves the answer to the question the same. Local and global hillshades do
   not differ by a grey level. The seam does not show, and the coarser global
   preview the fallback plan called for is not needed. See *F3, the local
   solve* in `implementation.md`.
3. **Does Windows package cleanly?** Qt and GDAL together, plus a C library
   built for it. The phase 0 CI build is there to find out early rather than at
   the end.
