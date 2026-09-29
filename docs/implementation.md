# Danu - what each phase actually did

The specification, the requirements and the plan are in `spec.md`. This is
the record of what building it turned out to involve: written after each
phase, because the plan and the work differ and a plan which quietly
rewrites itself to match is worth nothing. `spec.md` cross-references the
sections here by name.

## What phase 0 actually did

Written after the fact, because the plan and the work differ in three places
and a plan which quietly rewrites itself to match is worth nothing.

**The tile servers were not deployed to, and do not need to be.** That line was
written before the consuming scripts were left in `ogf-server-scripts`.
`fetchDemData.sh` and its two companions read published files; nothing on a tile
server imports Danu.

**`danu.cli` is empty, and `server/bin` is the implementation rather than a
wrapper over it.** Porting a thousand lines of working shell was not worth doing
during a migration whose whole purpose was to change nothing observable, and the
golden surface proves the published output is unchanged for the square it
pins. But the consequence needs stating,
because it lands on phase 2 and not here.

The golden test runs `danu-build-zone` as a subprocess. That is the whole build,
which is the right thing to pin. The editor will not run the whole build: its
incremental path calls the rasteriser and `isofill` on a box directly. So as
soon as that path exists there are two ways to produce a surface, and only one
of them is under test - which is precisely the drift this architecture is
designed to prevent.

Two ways out, and the choice belongs to phase 2 rather than to a plan written
before either existed. Either the per-step logic moves into `danu.cli` and both
the shell and the editor call it, which is what this plan assumed; or the golden
test grows a second case which drives the editor's path over the same fixture
and asserts the same surface. The first is tidier. The second is cheaper and
tests the thing that actually matters, which is that the two agree.

**The Windows build of `isofill` never built, and CI said it did.** The job
was there from the first push with `continue-on-error` set for Windows, and
`make` failed in under a second every time on `gdal-config not found`: conda's
`libgdal` does not put a `gdal-config` script on a PowerShell path, and the
Makefile stops without one. The override turned that red into green, and it was
read as green for the whole of phase 0, including in this document. Found on
2026-09-18 while sizing phase 1. The override went the same day, and the job
was honestly red for a few hours. Then it built: MSYS2's UCRT64 environment
gives the runner `gcc`, `make` and a GDAL whose `gdal-config` works, so the
Makefile builds there exactly as on Linux and `isofill` itself needed no
change. The job also runs the binary and asks for its usage text, because a
build that links and cannot load its DLLs is the Windows failure a build step
never sees. Green from 2026-09-18, on the log rather than the badge: the run
that landed this shows the compile line against `/ucrt64` and the usage text
the binary printed. It was found in phase 1 because
packaging for other people's machines was the reason it was meant to be a phase
0 deliverable - not in phase 7, where the plan said this kind of thing gets
found.

**The week of nightly builds is a clock, not a task.** Phase 0's code, packaging
and cutover were finished on 2026-09-18; what remained was six nights of forced
rebuilds and the decision phase 2 inherits. They are forced because the quiet
nights the pipeline would otherwise have are not evidence - see `danu-soak`
above.

**All six nights are in, and they are clean.** Two zones a night in name
order, queued at 02:45 and built at 03:00: alved and antumnia on the 19th,
axian and deodeca, ellarca and gobras, gwynian and hesperis, iscu and january
on the 23rd, and kofuku and liberian the same evening - the sixth night was run
by hand rather than waited for, so that phase 0 closed before phase 4 opened.
That is twelve of the thirty-two zones, each rebuilt from its squares and
published rather than found unchanged. The sizes are what makes them builds
rather than no-ops: 63M and 153M, 479M and 7.1M, 176M and 73M, 972M and 7.8M,
6.6M and 7.9M, 368M and 67M. Neither unit failed once in the week. The soak
then stopped queueing of its own accord - the count reached zero, the cursor
stands at twelve, and the script removed its own `limit-build.txt` - so there
was nothing to turn off. **Phase 0 is closed.**

What the week did turn up was in its own logs, and nobody read them: every
build printed `Failed to fetch spatial reference on layer encl`, which is ours
- `land_clamp` gave the polygon layers it makes from the sea rasters no
reference, so GDAL had nothing to build a transformer from. It was found from
the other end, in phase 3's review, because the editor runs the same build and
prints the same line where a mapper can see it. That is the argument for the
editor and the server being one codebase, made by accident: a warning that had
been on the server nightly for a week was found the day a person watched it
happen. The fix is in the editor's tree; the sixth night still printed it twice,
because `util` had not taken it yet.

## What phase 1 actually did

Ended on 2026-09-19, in six pull requests over two days, with a mapper able to
open a square from their mirror of `osm-squares/` and look at it over the
tiles. Where it differed from the plan:

**The Windows `isofill` build came first, and had never built.** Found while
sizing the phase: `continue-on-error` had reported a one-second `gdal-config
not found` as green since the first push. Made honest in one pull request,
made to build in the next, by way of MSYS2 rather than the Makefile change the
plan assumed - and the binary is run, not only linked, because a build that
links and cannot load its DLLs is the Windows failure a build step never sees.
All four Windows and UI jobs are required checks now.

**The tiles' colour ramp moved into the package.** The editor's traditional
ramp is `relief.ramp`, the gdaldem table the build applies to every published
relief raster, read from `danu/surface/` by the editor and installed from there
to `/etc/danu` for the build; `server/etc/relief.ramp` is a symlink. One file.
The editor's *default* contour colouring is the spectral ramp over the working
set's range, deliberately not the server's, for telling levels apart.

**Index contours are every fifth distinct level, not every 100 m.** The first
version drew nothing on the golden square, whose levels are 101, 145, 149, 151
- the odd ladders described under *The elevation ladder* - and has no round
hundred in it. Until the ladder is inferred (phase 3), the data decides.

**Two `QGraphicsView` facts that will matter again.** `option.exposedRect` is
clipped only in a real `paintEvent`; under `render()` it is the whole item, and
a tile layer that trusted it asked for the entire world. Paints bound
themselves by the painter's device rect. And a bare change of scale leaves the
scroll position in view pixels, so the view slides; every zoom anchors on a
point now, and `centerOn` snapping to whole pixels is corrected in the
transform, with the scene given a world of margin so the correction survives
the world's edges.

**The read is on a worker, and honestly not silky.** The spec asks that the UI
thread never block; a Python parse on a pool thread yields little under the
GIL. The window is alive - events are processed - and the interface does not
change when the reader gets faster.

**Not done, by choice.** R7, territory and owner, is advisory on editing and
moves to the start of phase 3. R5, blank squares from the editor, goes with
editing. Ladder inference, and the increments and keys under *Elevation
control*, were always phase 3.

**A second reviewer, before the first.** The pull request review runs locally
on the branch before the pull request exists, from the same prompt the
workflow uses (`packaging/ci/cr`). Over phases 0 and 1 the substantive
findings came from the local pass more often than not; the public rounds
dropped from five to one or two.

## What phase 2 actually did

Ended on 2026-09-19, in six pull requests here and two in `isofill`, all in one
day, with the exit criterion met the way the phase asked: the golden fixture
runs three ways - the shell build, the editor through the `isofill` binary, the
editor through the `isofill` library - and every way produces the one
reference, cell for cell. Where it departed from the plan:

**The second way, and it held.** The editor's surface path is
`danu.surface.build`: the shell's stages as functions over the GDAL bindings,
each carrying a `shell:` line naming the command it stands for, checked by a
test that names every stage (`tests/golden/test_editor_surface.py`, and its twin
for the shading stages). The three stages that were already Python became
callable with their command lines unchanged, so both paths run the same code
for them. On the gobras 3x3 at 3 arcseconds, 3.7 seconds to a DEM.

**`isofill` is a library, and the binary calls it.** `isofill_run()` is the
in-core fill, arrays in and an array out, and the binary's own in-core path is
a call to it - one code path, not two that agree. `isofill_params_default()`
hands out the command line's defaults so a caller sets only what it means to
set; `isofill_whole_mb()` is the banding reckoning, so the editor decides
library-or-binary with the binary's arithmetic. Through `ctypes`, not the CFFI
named above: plain C arrays, standard library, one less package per platform.
Versions 0.6.0 and 0.7.0, surface unchanged, and the golden reference built
with 0.5.0 still matched at each step. The proof that the library is the
binary is not the golden square alone: a synthetic raster with a mask *and*
water, which the fixture has neither of, filled both ways, agrees on every
cell.

**The same hillshade is a test, not an afternoon.** The golden job runs the
shell build once, and the editor shades the DEM it published by the same
stages - box filter through a VRT kernel, warp to spherical Mercator, `gdaldem`
- and matches the shell's published hillshade cell for cell, at both
z-factors. The relief is the canvas's own: either ramp from phase 1, scaled
three ways as R11 asks, composed with the hillshade; the hypsometric ramp
means metres, ignores scaling, and keeps the sea see-through.

**R20 and R21 on the screen.** Pass 1 alone, read into three classes and
warped onto the surface's grid, with the envelope as a dashed outline. Three
thousand square kilometres of the gobras set is ground its contours do not
describe, 5.6% of the drawn area, most of it the bay north of the capital
with no coastline at zero to hold it - which is R20's sentence, read off the
screen. The "one level in sight" class is drawn only on request: it is mostly
the barrier cells beside every contour, and drawn by default it buried the
other two.

**What the pre-flight caught that the golden square could not.** Three
things, each a way the two paths could have diverged with nothing going red.
The editor's library call passed `grad_min` from the file while the binary
passed nothing - closed in `isofill` 0.7.0 by giving the library the binary's
defaults, rather than by copying a number. The overlay's area was measured on
the Mercator grid - the equator's scale, twelve percent high at gobras'
latitude - and the log and the panel each counted their own; measured once
now, by the cosine of latitude, and both read it. And 255 told to be nodata on
one side of a warp made GDAL rewrite every valid 255 to 254, so the outside of
the drawn area counted as inside. None of those is a surface difference the
reference would have shown. That is what a second reviewer is for.

**Two facts corrected, both mine.** `elevation.toml` was described as "the
file the shell reads"; the shell reads no file and carries the values as
`${VAR:-default}` constants. Until it reads the file, a test holds the
constants equal to it, key by key (`tests/test_params.py`). And the shell does not read `relief.ramp`
or `osmconf.ini` from `server/etc/` any more: all three files live in the
package, with symlinks at the old paths, so an installed editor has them.

**Two `QGraphicsView` facts from phase 1 recurred as GDAL facts here.** A
chained `gdal.Open(p).GetRasterBand(1).ReadAsArray()` frees the dataset under
the band; every dataset is held in a name now, and the comment beside the
first one is quoted by the third. `gdaldem hillshade` writes 1 for complete
shadow and 0 only for nodata - measured on a 3 km wall face, 199 cells, every
one a 1 - so transparent-at-zero is its own meaning.

**Not done, by choice.** R22, the published DEM as tiles around the working
set with a visible seam, needs `data.opengeofiction.net` to serve the DEM
tiled and belongs with the server's phase 3 changes. Windows packaging of the
editor with GDAL and `libisofill` is phase 7's polish; the MSYS2 job proves
both build there, which is what phase 0 wanted proven early.

**The `danu.cli` question, re-evaluated as promised.** The second way was
taken because rewriting the build would have pulled the rug from under phase
0's soak, and because it tested the property that matters. Having taken it,
the picture is this: `danu.surface.build` now *is* the per-step implementation
`danu.cli` was meant to wrap, held to the reference by nine golden cases. The
port the first way asked for is no longer writing code that does not exist; it
is making `danu-build-zone` call `python -m danu.surface.build` step by step -
wrapping code that already passes - and retiring the shell's own copies of
those steps. It is worth doing, it is small, and it should wait for the soak
to finish and for the shell to start reading `elevation.toml`, which is the
same change. Recommended for the start of phase 4, before the incremental path
adds a third caller. Not decided here; decided by the reader.

## What phase 3 actually did

Ended on 2026-09-23, in seventeen pull requests here and one in `isofill`, over
the four days from the 19th, with the exit criterion met the way the phase
asked: a square nobody has drawn gets a hill through the edit commands, is
saved as the editor saves, and `danu-build-zone` builds the zone it lands in -
the editor's own path building the same cells, and the summit reading the top
contour's value (`tests/golden/test_editor_surface.py`). 157 tests that need
neither Qt nor GDAL, 155 on the canvas, 29 that need GDAL. Where it departed
from the plan:

**Undo is one history over the working set, not one per square.** R17 asks for
one undo key and an edit near an edge touches the neighbour, so `SetUndoStack`
records `(square, command)` and `dirty` is answered per square, because each is
its own file to save. Every command says which ways it changes (`ways()`), and
that is what the canvas redraws - one projected geometry per way, so an edit
re-projects what the command names and rebuilds only the levels it was and is
at. On the gobras 3x3, 6,401 contours and 335,293 segments, an edit costs
0.19 s and a pick 65 ms.

**The ladder is read from the data, and the data is odd.** The modal gap
between distinct elevations is the interval, the residue most contours share
is the phase, and the notches are every value that exists with the regular run
filled and continued. `N20E086` reads as 25 m on phase 0, and the ad hoc run
below 100 m - 0, 3, 5, 7, 9, 10, 12, 13, 15 and on - is kept as the mapper
left it. The spec's own worked example is a test, from a checked-in census of
ways per elevation (2,807 ways, 78 lines) rather than the 20 MB square, because
inference needs no geometry. `off_ladder` names 113 and 135 in that square, and
the 43, 55, 87 and 91 the spec lists.

**R16 moved to where the spec always said it was.** *Enforced on commit,
warned live*, which the tools did not do at first: every click was refused
outright, and the first attempt to redraw a stretch of a real contour was
refused for crossing the very wiggle it was replacing. So a crossing with the
contour a line began on no longer blocks, and what is asked instead is whether
the contour that results crosses anything - checked over the new run once the
swap is in, and taken back with its reason if it does. Everything else is still
refused at the click.

**Redrawing a stretch was asked for in the review and is the phase's largest
addition.** Start on a contour, draw a new section, end on the contour, and the
stretch between the two points is replaced: same way, same id, same tags, one
step of undo, `redrew 11 nodes of the 100 m contour as 2`. Two stretches run
between any two nodes of a ring, so the one the line was drawn along is the one
replaced, and where that straddles the ring's join the ring is turned first -
the same ring cut open elsewhere, which the build cannot see: the golden square
with all 25 of its rings turned a third of the way round differs from itself in
0 of 1,442,401 cells. A way's direction means nothing for a contour, which is
what makes that safe; `natural=coastline` carries the land on its left and the
sea on its right, and `build.water_mask` reads the sea from exactly that, so a
coastline can never be a redraw's target - the elevation is what keeps it out,
and now a test says so.

**What the review found that the tests could not.** Four faults reached the
mapper's hands through green suites, and each was found by driving the real app
rather than by reasoning:

- *Every click snapped to the contour being redrawn.* Its nodes are 87 m apart
  in gobras - under the ten-pixel snap radius at every zoom that shows a whole
  contour - so click after click landed on one, and each ended the redraw over
  a sliver and left the rest of the gesture as a new line. Clicks on that
  contour are ordinary points now and the redraw ends when the line does.
- *Deleting a contour was there and out of reach*, for the same arithmetic: a
  way could only be selected at zoom 16 and above, where it does not fit on
  the screen. Shift and a click take the line; shift and Delete take it away.
- *Opening a square named a neighbour.* A ladder change refreshed the status
  line through the last cursor position, and that position read the ladder
  again from wherever the cursor had been. The fixture's own working set does
  not contain the view's home, which is why no test saw it.
- *The colour scale tore across the map on every pan.* A scroll blits the
  pixels the viewport has and repaints only what the move exposed, so anything
  drawn in viewport coordinates is dragged along. Giving up the blit costs a
  full repaint per pan step - 104 ms at zoom 11 on the gobras set, 28 ms at
  zoom 15 - so the scale is a widget instead, and a child of the view: a child
  of the *viewport* is carried off by the scroll with everything else in it,
  measured at -33866, -30325 after one pan.

**The wheel was wrong, out of the spec's own reading of the keys.** "The wheel
follows the keys" made it step the elevation, with ctrl to zoom, and in use
reaching for the wheel to zoom and changing the drawing elevation instead was
the thing that would not stop happening. It zooms; ctrl steps. The map is
dragged with the right button as JOSM does it, because the left belongs to the
tools and on this ground almost every press lands on a contour. Zoom and the
current tool are on the map as well as on the keys.

**The suite was making 809 requests to OGF's servers per run.** A window builds
a real tile fetcher from the shipped layer config and painting it asks for every
visible tile; since R7 landed it also fetched the territory files, a megabyte
and a half, on every open. None of it was looked at by any test. Stopped at
conftest import rather than in a fixture, because a window built in one test
goes on painting during later ones and a fixture's patch is undone between
tests. 809 to nil, counted.

**And it was crashing.** Two of six runs on this machine, roughly one in seven
on CI, landing on whatever test was running - which is why it read as the change
under review each time. A Qt object is destroyed wherever Python collects it,
and the loader parsing a square on a pool thread triggers plenty of collections:
the crash was that thread deleting a `QGraphicsItem` while the main thread
painted it. Each test now waits for its workers and collects on the main thread.
A second shape of it, which does not reproduce here at all, was a runnable built
inline as `start()`'s argument: the pool deletes its C++ side when `run()`
returns and nothing held the Python wrapper. Both workers own their jobs now.

**Two facts corrected in the spec, both mine.** R4 said ids must be unique
across a zone; they need only be unique within a square, because a square is
edited, sent and built as one file. And `territory.json` is `[lat, lon]`, not
the `[lon, lat]` the spec claimed - gobras found no territory at all until the
axes were swapped.

**Six claims I got wrong and had to withdraw.** Worth listing, because each was
stated before it was measured: that repeating an arc rule would fix the redraw
taking the inside (the arc rule was not what was wrong); that a screenshot
showed the colour scale smearing (it was the synthetic surface's own edge, and
the artefact does not reproduce offscreen at all); that a widget over the
viewport did not paint (it had been scrolled off the window); that turning
HTTP/2 off silenced the socket message (five runs each way say otherwise, and
it costs 1.4 to 2.5 times the tile latency); and twice, an assertion that could
not fail - a tautology in the tool tests, and a version-tolerant check that
asserted nothing on the version it was written against. The pattern is the
same each time: a plausible mechanism, reported before it was tested.

**Not done, by choice.** The validation panel is phase 6 (R29-R33), so the
crossing and duplicate checks that would *find* rogue contours are not here -
the review hit that limit, and the crossing test from E4 would make an interim
finder cheap if it is wanted before then. The surface does not update while
drawing: that is R19 and the whole of phase 4. Starting a redraw on a
contour's end node continues it rather than redrawing, because a redraw wants
contour on both sides. A log of clicks, positions and actions, which would have
shortened three of the review's findings to one reading, belongs with phase 6's
session files. And `QIODevice::read (QSslSocket)` is still Qt's own, still
emitted, and now filtered rather than fixed.

**The optimisation the review asked for is phase 4's, deliberately.** The
per-edit cost above, `.osm.xz` re-compressed on every build of a dirty square
(0.7 s for gobras' 20 MB), `WorkingSet.open` at 1.4 s and the canvas at 0.8 s
for a 3x3: all of it is the same question the incremental path asks, which is
what to recompute per edit. Sized there, with the `danu.cli` port, rather than
piecemeal here.

## What phase 4 has done so far

**F1, the one surface.** Phase 3 shipped two implementations of the stages from
the squares to the DEM - `danu-build-zone` had its own, the editor had
`danu.surface.build`, and the golden test held the two to one reference cell for
cell. That test can only catch a disagreement after it has been written, so the
shell's copy goes: it calls `python -m danu.surface.build`, gets back the degree
extent and the DEM, and carries on with the stages only a publisher needs - the
smoothed copy for the hillshade, the Mercator rasters, the contour extract, the
`.hgt` archive. The script drops from 634 lines to 304.

Two things had to move with the code rather than be deleted with it. The first
is the reasoning: two hundred lines of the shell's comments are measurements
that cost a rebuild each - why the coastline is read as a line and not an area,
why the barrier is 2, why the second pass is masked, what the memory budget
actually buys - and they are in the module's docstrings and in
`elevation.toml`'s comments now, with a test naming four of them so a tidy-up
cannot quietly drop them. The second is the guards: the check that a square
which converted to nothing stops the build, which is the one that caught
liberian losing 81% of its constraint lines, and the refusal of a way over
10,000 nodes.

The shell reads `elevation.toml` for the three parameters it still needs rather
than carrying `${VAR:-default}` copies of them, so the test that held the two
equal is gone - there is nothing left to hold. Verified by building tempeira and
deodeca on `util` both ways, from the real squares: every published artefact is
byte for byte identical except the GeoPackage, whose SQLite carries a
`last_change` timestamp, and whose features hash the same. A misattribution came
out in the wash - the old script's `say` for the interpolate stage fired before
the drawn area and water steps, so every build has been recording isofill's time
under "water from the coastline direction".

**F2, the optimisation pass.** Phase 3 shipped correct-but-slow deliberately,
and this is where the bill came due. Everything below was measured on the local
gobras 3x3 - 6,317 contours, 335,751 segments, 342,068 points - before and after.

The per-edit costs first. `_rebuild_arrays` built one small numpy array per way
and walked all 342,000 points in Python to build the node index, and an edit to
one way rebuilds all of them: one vectorised operation per array took it from
122 ms to 12 ms, and an edit from 136 ms to 15 ms. `_rebuild_levels` stepped a
numpy `(n, 2)` array row by row, which builds an array scalar per coordinate;
`tolist()` first is 66 ms against 400. The whole set is projected through one
numpy call per way rather than a Python call per point. That is held to the
scalar projection to a hundred-thousandth of a pixel - not to the last bit,
which is what the test first asserted and what CI disproved: numpy's log, tan
and cos are not always the libm `math` reaches, and the two part company in the
last place on the runner. What has to be exact is a contour and the node a
mapper snaps to agreeing with each other, and they do by construction, being
the same array. Staging writes the edited square as a bare
`.osm` - it lives for one build, read by a build that expands it anyway, so xz
was work done to be undone - which took a staging from 692 ms to 177.

Then the one that mattered. The editor was running isofill's first pass **twice**
for every surface: once inside `build_dem`, and again in `first_pass_classes` to
classify the cells it could not answer for the overlay. The first pass is nearly
all of a fill - 0.56 s of a 0.67 s run - so the second was 95 s of the 208 s an
edit took at 1". isofill 0.8.0 adds `isofill_run_ex`, which hands back the first
pass from the same fill; the classes it gives are identical to the second
fill's, cell for cell. An edit at 1" is 114 s rather than 208 - measured back
to back in one process after a warming run, since the absolute pair moves a few
per cent between runs on this machine and the ratio does not.

Two things this pass is worth recording beyond the numbers. A correctness bug
fell out of the first change: the node index paired `way.refs` with the
projected points, but a ref whose node the square has lost has no point - JOSM
will save a way whose node was deleted under it - so every ref after such a gap
sat on the next node's position and the last was dropped. A click snapped to one
node and dragged another. And `_label` was left alone: it looked like the
obvious next target at 45 ms, and vectorised it is 38.6, because numpy's
per-call overhead eats the gain on arrays averaging 54 points. Measuring first
is the difference between those two outcomes.

What F2 does not do is reach 50 ms. After it, the whole-raster solve is 85% of
an edit at 1"; the micro-costs are noise. That is the incremental path's job,
and F2's was to stop the waste around it.

**F3, the local solve.** The preview's whole premise, and the open question
below: a cell's first-pass value depends only on contours within `radius`, so a
box grown by that much is exact inside, but the second pass is Laplace and
Laplace is global. A box solved against a rim held at the last whole-raster
answer is an approximation, and if its seam shows the preview is worth little.

It does not show. `danu.surface.local.resolve` solves a box and hands back a
patch; against a whole-raster solve of the same edit, over eighteen edits the
editor would accept on the gobras 3x3, the patch is wrong by at most **0.268 m**
and leaves nothing behind it out of date. At 1 arcsecond the worst of six edits
is 0.035 m. On the hardest case found - a whole contour level deleted from the
golden square, which opens new ground the first pass cannot answer rather than
merely disturbing old - the patch is exact. Rendered as hillshade, local and
global do not differ by a single grey level.

Those are the two-radii figures, and the radii moved when the margin was
measured for time as well - see *And last, the margin*. On that same hardest
case the patch is 0.000061 m out now rather than exact: a float32 last bit,
about two parts in a million of the contour interval it is drawn against, and
below anything a hillshade can show. Everything else
here stands.

Two numbers control it and they answer different questions, which is worth
saying because treating them as one number hid both for a while. **Cover** is
how far past the edited box the patch reaches, and it decides what goes *stale*:
an edit moves ground beyond the box it was drawn in, and whatever the patch does
not cover keeps showing the surface from before. **Slack** is how much clearance
the solve keeps beyond the patch, on top of the radius, and it decides what the
patch gets *wrong*, because that is the distance between the ground being
answered and the rim the answer is held against. Both want two radii. Deleting a whole contour level from the golden square,
which is the case the tests build:

| | stale outside | wrong inside |
|---|---|---|
| the minimal box | 115.794 m | 0.557 m |
| one radius | 42.392 m | 0.002 m |
| two radii | none | exact |

Over the eighteen gobras edits, which are ordinary rather than worst, the same
two radii take the worst patch from 3.278 m to the 0.268 m above. Nothing there
comes out exact, and the golden square's row does, because one square with one
level taken out of it is a smaller problem than a three by three working set.

What is left at two radii is not the rim at all. It is entirely cells the first
pass declined, where the second invents a value by diffusing across a region of
unanswered ground that runs past any box worth solving - so the patch solves a
truncated version of it and lands a little differently. That is the irreducible
part of being local, and it is what the exact rebuild on idle exists to remove.

`isofill_diffuse` is what makes a box solvable: the second pass on its own, over
a surface the first pass has already written. There is no "hold this cell" in
it, because a cell carrying anything but a sentinel is already fixed - a caller
writes the rim from the last whole-raster answer and the solve runs up to it. I
built a held mask first and measured it doing nothing, over 1024 cells, before
taking it out again.

Two things the measuring caught that reading would not have. The rim must not be
written where the box runs into the raster's own edge: there is nothing outside
to hold it at, the whole-raster solve treats that edge as an edge, and pinning
it at the pre-edit surface left a cell 82.656 m out that no margin could reach.
And the patch must be cropped before it is handed back - the ring where the
first pass is truncated by the crop is not a worse answer, it is no answer, and
splicing it in put 115.794 m into the surface.

**F4, the job queue.** Phase 3's builder ran one build and refused the next:
a second Ctrl+R, or a change of resolution while a build was running, was
answered with *a surface is still building* and dropped. Phase 4 has the editor
asking after every edit, so dropping is not an option - and queueing each
request is worse, since twenty edits would cost twenty builds to show the
twentieth.

So requests coalesce. A request made while a build runs replaces whatever was
waiting rather than joining it, and only the newest is ever started: a run of
edits costs one more build, not one each. Staging moved with it, from the
request to the start of a build, because it is 177 ms on the gobras 3x3 and the
requests that never start should not each pay it.

A build already running cannot be stopped. `isofill` is a C call with no
cancellation hook, so a superseded build is spent whether or not its answer is
used - and it is used: what comes back is the surface as things stood a moment
ago, which beats a blank canvas while the newer one runs. `finished` carries a
stale flag and R19 is what makes it visible.

How long a build took travels with its result. A single attribute on the window
cannot hold it once builds overlap - the superseded build is delivered while
its successor is queued, and one slot is one build's worth of a quantity there
are now two of. It was in fact safe, because the queue emits before it starts
the next, and that was measured rather than argued; but it was safe by an
ordering nothing at the window end can see, so the number goes in the signal.

The build function and the executor are both injectable, which is what lets the
queue be tested without GDAL and without threads - coalescing, staleness,
recovery after a failure, and staging once per build rather than once per
request, each checked by breaking the implementation and watching the test
fail.

One thing found on the way, unrelated to the queue but in the way of seeing it:
the UI suite is written for Qt's offscreen platform and CI sets it in the job's
environment, but nothing set it for a developer running `pytest`. The tests
opened real windows, and the window manager took focus back from whichever one
was mid-keystroke - six failures in `test_elevation`, `test_legend`,
`test_mapview` and `test_tools` which passed on CI and failed on a desk. The
conftest sets it now.

**F5a, the constraints under an edit.** F3 solves a box around an edit and gets
the whole raster's answer, but it takes constraints that already carry the
edit, and producing those by rebuilding is the thing the preview exists to
avoid. Timed per stage on the gobras 3x3 at 3 arcseconds, a whole build is
5.57 s and no one stage dominates it - collect 1.63, water 1.26, interpolate
1.41, clamp 0.86 - so there is nothing to skip. All of it has to go.

The contours are held in memory instead, as a layer loaded once from the
build's GeoPackage (220 ms for gobras' 7,240) and mutated per edit, and a box
is burned from that. 2.3 ms for a five-cell edit and 5.2 ms for a
two-hundred-cell one, against 10 to 18 ms for the solve: twelve to
twenty-three milliseconds together, against the 50 ms the phase ends on, with
the clamp and the shading still to come. Deleting a contour level from the
golden square and previewing it gives the rebuild's answer exactly - 0.000 m,
and nothing left out of date around it.

The trap is ordering, and the obvious way to get it is wrong. Rasterising with
`ATTRIBUTE=ele` is last-writer-wins where two contours touch one cell, so a box
burned in a different order from the whole raster disagrees with it. An OGR
spatial filter hands features back in *spatial index* order, and burning that
way put 1,359 of 48,841 cells at the wrong elevation - not at the box edge
where it would have shown, but scattered through it, median 31 cells in, every
one holding a value in both and a different value in each. Keeping the build's
FIDs and burning in FID order matches exactly at every box size tried;
reversing the order puts 80 cells wrong, which
`test_burning_in_the_wrong_order_is_a_different_raster` renumbers the FIDs to
show - without it, every other assertion here would pass just as well if the
order made no difference at all.

**F5b, the clamp and the shading for a patch.** The rest of what stands between
a solved box and a pixel, measured the same way.

The clamp has two halves and only one is local. Deciding *which* cells are sea
polygonizes the whole raster and keeps the regions reaching open water - a box
cannot do it, because whether a zero-cell is sea depends on what it joins up
with a thousand cells away. The arithmetic that follows is four lines of numpy.
So the decision is read off the last exact build, where a cell reading exactly
zero is one the clamp called sea, and only the arithmetic is redone. Measured
before it was relied on: deleting a contour level from the golden square moves
507 cells of the fill and changes the sea/land decision for 11 of 1,442,401 -
0.0008%. Those eleven are wrong until the rebuild, which is the held rim's
bargain again.

The shading is the box filter, the Mercator warp and the hillshade, on an
in-memory window: 14.4 ms for 215 by 215 and 19.8 for 411 by 411, against 2804
ms for the whole of the gobras 3x3. Each stage reads its neighbours, so the
window carries a halo and only the inside is the whole raster's answer.

One thing the measuring caught. A warp told a resolution and left to choose its
own bounds snaps to the window's extent, which lands up to half a cell off the
display's grid - three grey levels out against the whole raster's shading,
invisible on screen and fatal to splicing, since a patch between cells cannot
be written into an array at all. ``shade_window`` takes the target
geotransform and is put on exactly that grid.

**The budget, measured on the real path rather than assembled from parts.**
The first figures here were 2.3 to 5.2 ms to burn, 10 to 18 to solve and 14.4
to 19.8 to shade - twenty-seven to forty-three against fifty. The solve's share
of that was measured at one place on the raster and quoted as the cost, and it
is not: it is the cheapest of forty. A three-cell edit at forty points on the
gobras 3x3, solved over the same 201 by 201 each time, runs 23.2 ms at best,
41.4 median, 64.7 at worst, and exceeds fifty on its own ten times in forty.
The cost is about the ground, not the box - it tracks how much of the solved
area the first pass could not answer, though only at +0.38, so that is not the
whole of it either.

End to end, one node of a real contour moved on the gobras 3x3 at 3 arcseconds
costs 63 to 73 ms: roughly 1 to mark the box, 2.7 to burn, 45 to solve, 0.5 to
clamp, 14 to shade and half a millisecond to recolour.

That last figure was 1,472 ms until a review asked what the other numbers left
out. The surface is recoloured to be shown, and the whole of it was being
recomposed for every patch: 24.4 M cells, twenty-four times the solve it
followed, so an edit measured at 62 ms took a second and a half to appear. The
comment in the way said `compose` was "the UI thread's cheap end" and that
composing a rectangle instead "would buy a few milliseconds of the fifty" -
both asserted without measuring either. `SurfaceLayer.recolour_box` composes
the rectangle that moved and paints it into the pixmap, which is what the half
millisecond is, and it keeps the surface's own colour scale rather than
restretching to the patch's contents.

**So the phase does not end yet.** Fifty milliseconds is where phase 4 ends and
the preview is over it, by a quarter on a typical edit. The lever is the solve,
and the obvious one is the margin: a three-cell edit is solved over 201 by 201
because cover and slack are two radii each, and F3 chose two radii by measuring
accuracy alone. What it costs in time was not part of that decision and now has
to be. That is **F5c**, below, and not some later phase: fifty milliseconds is
this phase's own exit criterion.

**The wiring.** `danu.ui.preview.PreviewDriver` joins them: the editor says
which ways an edit touched, the driver keeps the contour layer in step, and two
timers decide when anything happens. A short one coalesces a gesture - drawing
a contour is one edit per node, and previewing each would spend the budget many
times over on frames nobody sees. A long one asks for the exact rebuild through
F4's queue once the drawing stops, which is where the preview's approximations
are settled rather than compounded: every build re-adopts the exact grids, so a
preview always starts from an answer.

R19's third clause, the two states told apart at a glance: the surface draws a
dashed amber edge while it is provisional, and the panel says *preview, N ms -
exact on idle*. Around the whole surface and not the patch, because what is
provisional is the surface - one preview's rim is the next one's ground, and
outlining only the last box edited would say the rest had been settled.

R20's overlay is the first pass's classes, which a preview does not recompute,
so it is faded over the ground previewed since the last build and left at full
strength everywhere else. Two things about that were wrong before they were
right, and both are the kind that come back. It is the overlay's own pixmap
drawn twice through a clip, never a wash over the top: a translucent rectangle
over this layer does not dim the overlay, it paints over the hillshade beneath
it, and `unreached_rgba` is transparent wherever the first pass had an answer -
which is most of any box - so a wash turned a mostly-answered patch into a pale
grey rectangle with no red in it. And the clip path is set to winding fill,
against `QPainterPath`'s odd-even default: the rectangles overlap as a matter
of course, since a contour drawn node by node is one preview per gesture, and
under odd-even an overlap cancels out of the faded path, falls back into the
crisp one and is drawn at full strength - the middle of a stroke coming out
brighter than its ends. Both are pinned by rendering tests rather than by
attributes.

The fade costs about 2 ms of a viewport repaint with nothing stale and 5 to 6
with fifty rectangles accumulated, which is the most a gesture reaches between
rebuilds. It is outside the 63 to 73 ms below, which is the driver's own span
from edit to spliced arrays.

What bounds it is memory, and the bound is one this design chose rather than
one it was given - see *F5c*. The preview holds the build's grids as whole
arrays: 308 MB for the gobras 3x3 at 3 arcseconds, 1.5 to 2.8 GB at 1. So they
are kept at the drawing resolution and not at the publishing one, where the
menu already says *slow* and an edit waits for the exact build, and the driver
says which side of that line it is on rather than looking broken. The rasters
are tiled GeoTIFFs and a solve reads one grown box of them, so holding them
open and reading windows would have cost neither; that was not seen until the
editor was used at 1 arcsecond. And the grids are read on the worker inside a `try`: a build
that produced a DEM has produced what was asked for, and if its intermediates
cannot be read back the editor loses the live preview and rebuilds on every
edit, which is what it did before phase 4.

This is the point at which F3, F5a and F5b stop being library and start being
what the editor does.

Running it turned up a shutdown crash the idle timer had made ordinary.
`closeEvent` removed the builder's working directory, and a build still writing
into it reached the clamp to find its own `rounded.tif` gone; Qt then tore down
the signal the failure was being reported through, so what reached the console
was *Signal source has been deleted* out of `QRunnable::run`, with the real
cause underneath it. Closing during a build used to mean closing during a
Ctrl+R and was rare. Once something asked for builds by itself it became what
closing after drawing does. Cleanup waits for the running build now - on the
job's own flag, since the pool's answers for whatever else is on it - and
leaves the directory behind rather than pull it from under a live writer if the
wait runs out.

**F5c, what is actually slow.** Items 1, 2 and 3 done, 4 half done. Named for
the margin, and then
the app was used for an afternoon and the margin turned out not to be the
binding constraint - nor the second, nor the third. What follows is measured on
the gobras 3x3, in the real window rather than in a harness.

In the order a mapper would feel them:

1. the contour layer, which owned 150 ms of a 153 ms repaint - **done**;
2. the recolour after a build, which redrew 24 M cells to move 30 of them -
   **done**;
3. `Kept` holding whole rasters, which is why there was no preview at 1
   arcsecond - **done**;
4. the rebuild trigger, which fired on a timer rather than on the two things
   that need it - **half done**: fresh ground triggers a rebuild, and the
   detector for the other half turned out not to discriminate;
5. the margin, which by then may not be worth changing.

Timing one node moved, through the editor, from the command to the frame:

| | |
|---|---|
| `editor.do`, including the contour layer's refresh | 16.6 ms |
| the preview driver's own span | 62.8 ms |
| the patch recoloured and the panel updated | 0.6 ms |
| **Qt repainting the scene** | **~300 ms** |
| end to end | 377.9 ms |

The preview does what F5b says it does. Everything else is the drawing, and
the drawing is one layer:

| repaint of the map | |
|---|---|
| all layers | 150.8 ms |
| without the surface | 151.2 ms |
| without the unreached overlay | 149.5 ms |
| **without the contours** | **2.7 ms** |
| the tiles alone | 0.6 ms |

`ContourLayer.paint` built one `QPainterPath` per elevation and culled by each
path's `controlPointRect`. On a working set that is 72 elevations over 6,401
ways and 341,694 points, every path spans nearly the whole set, so nothing was
ever culled and a third of a million points were redrawn antialiased on every
paint - on every pan, and on every edit.

**Done.** One path per way, each with its own rectangle. The whole map's
repaint, on the gobras 3x3 at a 687 by 954 viewport. 6,305 ways there, not the
6,401 above: ninety-six of those carry an `ele` but fewer than two points the
square still holds, so they are not geometry and the layer never builds one.

| zoom | | before | after | ways drawn |
|---|---|---|---|---|
| 9 | index levels only | 187.6 ms | 47.6 ms | 1,088 of 6,305 |
| 11 | every level | 170.0 ms | 37.0 ms | 1,062 of 6,305 |
| 12 | every level | 51.0 ms | 22.9 ms | 235 of 6,305 |
| 13 | every level | 36.2 ms | 10.7 ms | 32 of 6,305 |
| 16 | every level | 28.4 ms | 5.7 ms | 5 of 6,305 |

`ZOOM_ALL` is 11, so the first row draws a fifth of the levels and the rest
draw all of them; each row compares like with like, since the same filter
applied before. Faster at every one, including zoom 11, where every level is
drawn and a sixth of the ways still are: a rectangle test per way costs
nothing against the points it saves. The floor - the same repaint with the
layer hidden - is 0.2 ms, so from zoom 13 in the contours are no longer what a
repaint is.

**Correcting F5b's own account.** It said "what F5c does not need to account
for is the drawing", on the strength of the overlay fade measuring 2 to 6 ms.
That measurement was right and the conclusion drawn from it was not: the layer
measured was the one just changed, not the one that dominates. The fade is
still 2 to 6 ms. The contour layer was never measured until it was looked for.

**One arcsecond is the second thing, and it is three problems wearing one
coat.** The window stops responding, an edit takes two minutes, and there is no
preview at all. Each has a different cause and only the third is about the
fill.

The freeze is the *recolour*, not the build. The display grid at 1 arcsecond is
15,291 by 14,367 - 219.7 M cells and 0.82 GB of RGBA - and `recolour` measures
a flat 74 ms per million cells from 4 M to 42 M. That is about sixteen seconds
on the UI thread, after every rebuild. And almost all of it is wasted: an exact
rebuild after one node moved changes **30 cells of 24.4 million**, in eleven
rows. A build is not a reason to recolour a raster, it is a reason to find out
what moved.

**And it was not only the time, which is why the popup came back.** Once item 3
made 1 arcsecond usable, the window manager started putting up *python3 is not
responding* again on the first build of a session - the one case `set_shaded`
still recolours whole. Measured rather than assumed: `shade.compose` allocates
**104 bytes of working space per cell**, dead linear from 2.2 M cells to 56 M.
`rgba[..., :3].astype(np.float32)` is twelve of them and the multiply, the
`rint` and the `clip` are twelve each again, against the four bytes per cell it
produces - about twenty-six times the size of its own answer. Three more copies
sat around it: `Scaling.range_for` built a boolean mask and a compacted copy of
every land cell to answer a min and a max, `img.copy()` duplicated the finished
RGBA, and the layer then held that RGBA for the life of the session.

At 3 arcseconds that is 2.5 GB and merely wasteful. At 1 arcsecond it is about
**25 GB on a 15 GB laptop**, so the freeze was never sixteen seconds of
arithmetic - it was that plus swapping.

**Done, for the memory.** `compose` and `range_for` work a strip at a time,
through the same `strips()` the surface comparison uses, and the two spare
copies are gone: `QPixmap.fromImage` copies into the platform format itself, so
`img.copy()` was a second full copy nothing read and keeping the array was a
third. The composed output is byte for byte what it was, over every mode and
both ramps.

| a whole recolour at 1 arcsecond | before | after |
|---|---|---|
| working space | ~25 GB | **0.95 GB** |
| `compose` alone | 104 bytes/cell | 4.3 bytes/cell |

**And done for the block - though not for the popup, which turned out to be
something else.** Bounding the memory stopped it swapping and did not stop it
blocking: the arithmetic is unchanged
and so is its cost, and a window manager gives up long before twenty-one
seconds. So a whole recolour composes on a worker. The layer keeps a runner -
`QThreadPool.start`, installed by the window - and `recolour` hands the job
over and returns, leaving the surface already on screen until the new one is
ready. The UI thread's share is the `QImage` and the `QPixmap`.

Measured at the 1 arcsecond display grid, through the layer configured as the
window configures it - the layer's own default is to compose inline, so the
second and third rows are the window's arrangement and not the class's:

| | UI thread blocked |
|---|---|
| composing on the UI thread | **20.89 s** |
| handing it to a worker | 0.2 ms |
| applying the result when it lands | 65.8 ms |

The nineteen seconds of arithmetic are still nineteen seconds; they are just
not in front of anybody. There is one implementation of the arithmetic,
`_composed_now`, called on a worker or on the calling thread, because two
would be two things to keep in step and the point of the worker is that it
produces what the inline path would have.

Three things the worker needs that composing in place did not. A job cannot be
stopped mid-array, so a superseded one finishes and is dropped by serial when
it lands - the alternative is a surface arriving in a ramp nobody chose. The
style goes to the job as a copy, since `Style` is a mutable dataclass and a
job composing under one ramp while the user picks another must finish saying
what it was asked. And `_moved` refuses to compare while a compose is in
flight: the pixmap is then older than the surface that asked for it, so boxes
would be right about the two surfaces and wrong about the screen, leaving
everything outside them showing a surface two builds old.

Only one compose runs at a time, newest wins - the queue `SurfaceBuilder`
keeps, for the same reason and a sharper one. Asking for another while one ran
used to start it alongside: the serial made the *result* right and nothing
bounded the number in flight, and the default `QThreadPool` offers sixteen
threads against a compose that is 0.88 GB of output on top of its working
space. A mapper editing through a twenty-second compose could stack enough of
them to put a 15 GB machine into swap, which is the failure the banding was
for. The one running is left to land, and what follows it is whatever the
surface and the style are by then.

What the pixmap is of is now recorded rather than assumed. `self.shaded` and
`self._pixmap` are different surfaces for the twenty seconds a compose takes,
so `_drawn` names the one on screen and the two guards that used to ask about
`self.shaded` ask about that instead - which is also what keeps them right
when a compose *fails*, where `_pending` would stay set with nothing coming.
A box is refused while a compose is in flight as well, on a second ground: a
landing compose replaces the whole pixmap with colours worked out before the
patch existed, so patching is work thrown away after being shown, which is a
surface going backwards on screen. That costs the live preview for as long as
a compose takes, and applying one a strip at a time is what would fix it
properly.

**What this was not.** It was taken on as the fix for *python3 is not
responding* at 1 arcsecond, and it is not. A trace of a real session has a
whole recolour happening twice, both at startup, and the status bar reading
"preview, 5643 ms": what a mapper meets on every edit is the preview's own
solve, which is on the UI thread and which this change does not touch. The
work here still earns its place - a whole recolour is twenty-one seconds and
a style or ramp change asks for one - but the popup is the preview's, and the
measurement that said otherwise is corrected below.

A fourth thing, which using it found rather than reasoning about it did. The
rectangle `paint` stretches the pixmap into belongs to the *pixmap*, not to
`self.shaded`, and with the compose on a worker there are twenty seconds
between the two. `set_shaded` had been setting it eagerly, so a rebuild whose
extent had grown - which is what drawing on fresh ground produces - grew the
rectangle at once and left the old pixmap stretched across the new ground:
draw in a fresh area, let the rebuild land, edit there again, and the surface
went *back to the original extent*. Composing on the UI thread had kept the
two in step by accident, there being no moment between them. The compose
carries its surface back with its colours now, and the rectangle and the
pixmap are set together from it.

The layer's own default is still to compose on the calling thread, which is
what every test and every raster small enough wants; the window opts in, and a
test asserts that it does so this cannot quietly stop happening.

**Done.** `set_shaded` compares the new surface with the one on screen and
recolours the boxes that differ. On the gobras 3x3 at 3 arcseconds, showing a
rebuild after one node moved goes from about **1,500 ms to 25 ms**:

| | |
|---|---|
| walking the two rasters in strips | 14.3 ms |
| the colour-scale guard, `range_for` over the new surface | 10.2 ms |
| recolouring the boxes | 0.3 ms |
| recolouring the whole raster, which is what it did before | ~1,500 ms |

The first surface of a session still costs a whole recolour, because there is
nothing to compare it against. So does any build that changes the grid or moves
the colour scale.

Two things about those figures. A whole recolour of that set varies by about
five per cent between runs - 1,475 to 1,547 across the ones taken here - so
they are quoted to the nearest sensible figure rather than to the tenth. And
the colour-scale guard is not free: it is nearly half of what showing a rebuild
now costs, and a build that goes on to recolour the whole raster pays it twice,
since `recolour` works it out again. Worth removing when the sum it sits in
matters; against 1,500 ms it did not.

The comparison walks the two rasters in strips - `strips()`, which was written
for `land_clamp` and now lives where it does not need GDAL to reach - so its
working set is bounded whatever the resolution, and it yields one box per strip
rather than one for the raster, so a change in two places does not drag the
ground between them into the redraw.

Three things send it back to a whole recolour, and the third is the one that
is easy to miss: nothing on screen yet; a grid that has changed, since a build
whose extent grew is a different raster and a box in one is not a box in the
other; and a colour scale that has moved, because in `auto` the ramp is
stretched over the land in the whole array, so a build that raised the highest
ground recolours every cell - including ones whose own elevation did not
change. Recolouring only what moved there would leave the rest at the old scale
and the patch would show as a rectangle.

**Also done, and smaller than it looked.** Re-measuring after the two items
above moved an edit from 378 ms to about 165, and changed what was left: two
contour repaints at 36 ms each, a 58 ms solve, and 17.8 ms inside `editor.do`.
That last one was `_rebuild_arrays`, which rebuilds the flat segment and node
arrays for every way whenever one way changes - and nothing in `paint` reads
them. They are for picking a contour, picking a node, and the crossing check.
Built when something asks instead, an edit costs 5.6 ms there rather than 17.8,
and drawing a contour node by node stops paying for an answer it never uses.

The labels were the other half and gave less. A contour label is text turned
into glyph outlines, and there are only as many distinct strings as elevations
- 72 against 86 labels in one window - so the outline is built once per string
now. That took labels from 9.2 ms of a zoom-13 repaint to 7.3, not to nothing:
building the outline is the smaller half of drawing a label, and stroking a
halo round it and filling it is the larger, which is per label however the path
was made.

An edit measures about 146 ms after both, taken afresh rather than worked out.
Working it out would have given about 149, and the three milliseconds between
them are where run-to-run variation sits on a figure like this - which is the
reason to take the measurement rather than do the arithmetic, and the reason
both numbers are here instead of only the tidier one.

**And the labels stop until z14.** Using it at 146 ms an edit found z12 and z13
still lagging, and the guess was that the labels were in it. They were, and
they cost most where they say least: a contour carries one label however far in
you are, so zooming out puts more of them on screen and makes each one smaller.

One run, so the columns subtract:

| | labels from z12 | from z14 | saved |
|---|---|---|---|
| a repaint at z12 | 33.6 ms, 86 labels | 23.2 ms | 10.4 ms |
| a repaint at z13 | 21.7 ms, 55 labels | 14.6 ms | 7.2 ms |
| a repaint at z14 | 13.2 ms, 11 labels | 13.2 ms | - |

About a third of a *repaint* at both. Not a third of an edit: an edit is two
repaints on top of a solve, so 7.2 ms at z13 is about 14 of some 145 - worth
having, and a different claim from the one the repaint figures make on their
own. An edit measures about 136 ms against 146 before, which is that saving
inside the run-to-run spread rather than distinguishable from it.

Two zooms above `ZOOM_ALL` rather than one, which is the part worth writing
down: the contours are what a mapper is reading at z12 and z13, and the labels
were a third of the cost of showing them.

Index contours below z12 was measured as well, and rendered rather than
guessed at - 12 ms cheaper at z11 and, unexpectedly, easier to read, since z11
draws 1,957 ways and is the smudge this layer's own level-of-detail note warns
about. At z12 the same change takes 44 levels to 8 and the low ground loses its
shape entirely. Not taken, either way, until someone wants z11 specifically.

**Done, and it retires `PREVIEW_ARCSEC`.** The preview was off above 3
arcseconds
because `Kept` holds the build's grids as whole arrays and they would be
gigabytes - but a solve reads *one grown box*, and the rasters are tiled
GeoTIFFs written 256 by 256:

| | cells | time | bytes |
|---|---|---|---|
| the whole constraints raster | 23.0 M | 44.2 ms | 44 MB |
| a 201 by 201 window | 0.040 M | 0.01 ms | 0.08 MB |
| an 801 by 801 window | 0.642 M | 0.08 ms | 1.22 MB |

A window costs the window. So `Kept` holds five `Band`s - an open dataset
each - and reads a box when a preview asks for one. `patch` reads the grown
window of the mask, the water and the surface, and does not read the
constraints at all: it re-burns them from `contours`, so the burn *is* that
window's constraints after the edit. That retired the old put-in-take-out
dance, where the burn went into the whole kept array for the call and came
back out afterwards, which existed only because `local.resolve` took whole
rasters. `resolve` now splits at the seam it always had - it sliced its four
arguments once and worked on the windows from there - so `resolve_window` is
what a caller with a window calls, and the array signature is unchanged for
the golden tests that use it.

Measured cold, in a process that did not do the build, on the gobras squares
around N20E087:

| | 3 arcseconds | 1 arcsecond |
|---|---|---|
| the grid | 2,401 x 2,401, 5.8 M cells | 7,201 x 10,801, 77.8 M cells |
| the five grids as arrays | 81 MB | **1,089 MB** |
| `Kept` open, over a bare interpreter | **+66 MB** | **+66 MB** |
| five successive previews | 18 to 36 ms | 23 to 37 ms |
| peak RSS | 100 MB | 117 MB |

**The preview row is wrong and is left here corrected rather than quietly
fixed, because it was quoted to justify the change.** Those boxes were at the
raster's centre, which on this working set is 0.0% drawn ground: the mask is
empty there, the fill has nothing to answer, and what was being timed was the
window being read and isofill returning. On drawn ground - 65.7% of the solve
window, where a mapper actually draws - the same call at 1 arcsecond is **1.8
to 2.0 s**, and a trace of real use has it between 1.3 and 7.0 s. The memory
rows are unaffected: they do not depend on what the fill finds.

A grid thirteen times the size costs the same to keep. The +66 MB is identical in both columns because it is the contour
layer, which is the same contours either way; the rasters cost nothing until a
box is read, and RSS is flat across five previews, so the windows are not
accumulating. The preview at 1 arcsecond is slower only because `good` is 243
cells square against 83 - the fill radius is 60 cells there and 20 here - which
is 8.6 times the cells for about 1.3 times the time.

`PREVIEW_ARCSEC` is gone. There is no resolution at which the editor declines
to preview.

Writing back is the one thing that is not a read. The surface carries each
patch forward so the next preview holds its rim at what is on screen, and the
clamped patch goes into the DEM for the same reason; both are writes into a
file now, at 0.12 ms for a patch.

Not into the build's own files. One working directory serves a whole session -
`SurfaceBuilder` takes a single `mkdtemp` - so every build writes the same
`dem.tif` and `rounded.tif` into it, and a preview runs *while* the next
rebuild is in flight, because that is what a preview is for. Opening the
build's two files for update would have the preview and the running build
writing the same two files, for the seventy-four seconds a 1 arcsecond build
takes; as arrays there was no such thing. They are compressed GeoTIFFs, 15.5 MB
and 5.2 MB at 1 arcsecond, and copying them is 0.01 s against that build, so
`_read_rasters` copies both into a directory of its own per build and opens the
copies. The build's own rasters are never written at all, and a test says so.
The three nothing writes are opened in place.

There are two implementations of the band interface, which is a thing to keep
honest rather than to be pleased about: `Band` over a dataset, and `ArrayBand`
over an array, because the ui tests run on a job with Qt and no GDAL and cannot
open a raster at all. `tests/golden/test_preview.py` asserts the two present
the same methods with the same arguments and give the same answers over the
same data, and the golden preview test itself now opens the build's real files
rather than handing `Kept` arrays it already had - if nothing there reads a
raster then nothing tests the path a mapper is on.

What cannot be banded is isofill's second pass, which is a global multigrid
solve over the whole raster. It is not, though, where the time goes: measured
over a 77.8 M cell fill, both passes cost 92.9 s and the first pass alone 88.0
- the second is about five per cent of the fill, and the fill is 92.5% of a 1
arcsecond build (65.8 s of 71.2). The two minutes is the first pass, which
bands. What the second pass cannot do is go away, and it runs on a worker, so
it is wall-clock and not a frozen window; it is the rebuild trigger below that
rations the whole build.

**The rebuild, and when it is really needed.** R19 says the surface is rebuilt
exactly on idle, and the editor does it after every pause. Measured against a
rebuild at each of twenty-one successive edits, seventeen of the twenty-one
previews were already right to 0.013 m - so most of those rebuilds recompute an
answer that had not changed, at 4.6 seconds a time and two minutes at 1
arcsecond.

Two things do need it, and a timer is the wrong detector for both.

The first is fresh ground. `drawn area` and the extent belong to the build;
`preview.patch` passes the build's mask straight through. A contour drawn
outside the drawn envelope moved **0 of 25 cells** in the preview - extending
coverage into ground nobody has drawn shows nothing at all until a rebuild, and
no local solve can change that, because the fill is told not to reach outside
the mask. An edit whose box meets the mask's edge, or a square gaining its
first contour, is a rebuild whatever the timer says.

**Fresh ground, done** - and the test is the contour, not the patch. The drawn
mask is the fill's reach from the contours rather than a solid blob, so it is
full of holes and edges an ordinary patch straddles: over twelve edits on the
gobras 3x3, between 1.9% and 28.3% of each patch lay outside it. As a trigger
that fires on almost every edit and is worse than the timer it replaces. The
moved contour's *own* cells lay outside the mask 0.0% of the time across all
twelve, because a contour moved within drawn ground is on drawn ground by
definition. That is the signal.

**The second detector does not work, and the premise behind it was wrong.**

It was to be this: a preview whose solved box has unanswered ground touching
its own boundary is one to distrust, since that is F3's residual - pass 2
diffusing across a region that runs past the box - and the classes are already
computed for R20. Measured over twenty-one edits it discriminates nothing. Any
unanswered cell on the boundary flags 43% to 53% of the boundary on *every*
edit, good and bad alike. Narrowed to the connected region the edit actually
lands in, it flags 8 of 11 wrong previews and the 1 right one as well.

And the figure it was built on - seventeen of twenty-one previews already right
to 0.013 m - is the golden square's, which is one sparse square. Repeated on
the gobras 3x3, with the exact build re-adopted after each edit as the editor
does, eleven of twelve previews are between 0.085 m and 0.877 m out and one is
0.003. Not accumulation: each is measured on its own. Previews on a real
working set are simply less exact than on that fixture, which is worth knowing
wherever the 0.013 m figure is quoted - including in the case for the ten
second backstop above, which it weakens without overturning, since 0.877 m
against a 25 m contour interval is still nothing a hillshade shows.

What would detect the bad ones is not known. It is not the classes.

With those two, the idle timer becomes a long backstop rather than the
mechanism, and the provisional rim says what it already says.

**Lengthened in the meantime.** A second and a half is shorter than an ordinary
pause in drawing - reading the ground, moving the mouse, deciding where the next
node goes - so the rebuild fired mid-gesture and was superseded, repeatedly,
which is what using it feels like rather than what any measurement said. Ten
seconds now. The two costs are asymmetric and the old value was set as though
they were not: waiting is nearly free, since seventeen previews of twenty-one
were already right to 0.013 m, and firing is 5.6 seconds of a core at 3
arcseconds and two minutes at 1. It is still a timer standing in for a
condition, and the conditions above are what replace it.

**And the preview itself goes to a worker, which is what the popup was.**
Composing was taken on as the fix and was not it: a trace of a real session has
a whole recolour twice, both at startup, and the status bar reading "preview,
5643 ms". What a mapper meets on every edit is the preview's own solve.

Measured on the gobras set at 1 arcsecond, over the 604 by 604 window a
three-cell edit grows to:

| | |
|---|---|
| the first pass, the sight test | 1.7 to 2.2 s |
| the second pass | 17 ms |
| burning the constraints and reading the windows | 6 ms |

The first pass is the whole of it, and none of it was ever on a worker. The
seam is `preview.prepared`: it touches the contour layer and the datasets, so
it belongs to whichever thread owns them - the editor mutates the OGR layer on
every keystroke - and what it returns is arrays and can be solved anywhere.
`patch` is the two in a row for a caller that does not care, so there is one
implementation and the worker solves what `patch` would have.

| the UI thread's share of one preview | |
|---|---|
| `patch()`, all on one thread | **1736 ms** |
| `prepared()`, which stays | **6 ms** |
| `resolve_window()`, to the worker | 1726 ms |

One at a time, and edits during a solve stay pending for the next preview
rather than starting a second: two solves at 1 arcsecond compete for the same
cores and neither arrives sooner. A solve that cannot run comes back as a
value rather than an exception, because re-raising it from the slot that
receives it would leave a queued slot with no caller, and PySide6 aborts the
process rather than printing it - which is the failure that handling was
written for in the first place.

**What grows, and what does not.** The trace has four previews of nearly one
size at 1301, 2852, 3535 and 6989 ms, which looks like something accumulating
and is not. The contour layer does not grow - `apply` reuses a way's FID.
Drawing barely moves the burned cells: 78,792 to 79,185 over five edits, and a
run that reapplies one way id climbs the same. Writing patches into the
compressed rasters does not slow the reads: 1 to 2 ms, flat over six rounds.
What it is: the same solve run twelve times on identical input goes from 1,783
to 3,466 ms while the average clock sags from about 1,500 MHz to 1,000, and
then levels off. It is the laptop throttling - sixteen cores at 100%, 75 C -
and in a real session a rebuild competing for them as well. There is nothing
to fix there, which is worth knowing before treating a worker as having hidden
it.

**And every build is adopted, not only the ones that are not stale.** This is
the surface being lost, and it took the trace to see. `follow` points the
driver at the array the layer draws and runs for every build; `adopt` gives it
the grids a preview works *from*, and ran only when a build was not stale, on
the reasoning that the approximations should restart from an exact answer
rather than compound.

At 1 arcsecond it does the opposite. A build is a hundred seconds and an edit
lands inside every one of them, so every build finishes stale and none is ever
adopted: a traced session has five `follow`s and one `adopt`, every preview
reading `kept_gen=1` while the display is on its third. The preview worked from
the first build's surface throughout, and spliced patches derived from it over
the exact ground each later build had just put on screen - which is a mapper
drawing a contour, watching the rebuild land correctly, and watching the next
preview take it away again.

A stale build's grids are not the newest edits. They are the newest exact
answer there is, and strictly closer than one five builds back; and what a
preview owes each edit it re-burns from `contours`, which has every edit in it
either way.

**And last, the margin - done, and it was not last after all.** `cover` and
`slack` were two radii each because F3 measured what they were worth in
accuracy: two radii take the worst of eighteen edits from 3.278 m to 0.268 m,
and no further. What they cost in time was not part of that decision. At 3
arcseconds it is 63 to 73 ms and nobody would look again; at 1 arcsecond the
first pass sweeps the grown window and the radii are most of a two-second
preview.

Measured again at 1 arcsecond, eight node drags and five contours deleted, each
against a whole-raster rebuild of the same edit. Two numbers per setting,
because the radii answer different questions: how wrong the patch is where it
claims to be right, and how much ground the rebuild moved that the patch does
not cover at all and so leaves showing the surface from before.

| cover | slack | best ms | worst, drags | worst, deletes |
|---|---|---|---|---|
| 2r | 2r | 2,950 | 1.312 m | 0.819 m |
| 2r | 1r | 1,930 | 1.312 m | 1.007 m |
| 1r | 1r | 1,244 | 1.250 m | **0.564 m stale** |
| ½r | ½r | 663 | 1.122 m | **1.616 m stale** |

`slack` is one radius now. It is the clearance the solve keeps, so it cannot
leave anything stale, and halving it costs at most 0.19 m across both sets.

`cover` is one radius, and two when the edit *removed* a contour. Over eight
drags nothing was left stale at *half* a radius - 0.000 m, every one - so one
radius is twice what they were measured to need. Deleting is not like that: of
five, four also left nothing stale at half a radius, and the fifth moved 47,614
cells where the others moved 197 to 1,575, and left 1.616 m at half a radius,
0.564 at one and 0.001 at two. That is F3's own finding reproduced, and it is
why the two radii stay where the risk was found rather than everywhere. The
driver already knows which kind of edit it has - a way it can no longer find in
the square is a deletion - and it asks for the wider cover for the whole
preview when any edit in it removed something, because boxes are merged and a
piece cannot say which edits it came from.

A drag is the common edit. On the gobras set at 1 arcsecond, over the same box:

| | window | |
|---|---|---|
| before | 604 x 604 | 1,854 ms |
| a removal | 484 x 484 | 1,138 ms |
| a drag | 364 x 364 | **720 ms** |

**How it was measured, because four different ways of doing it gave confident
wrong answers first.** Moving a node by degrees rather than cells moved it less
than one cell, and the constraint raster came out byte for byte identical -
there was nothing to measure and the harness said so by reporting no change at
all. Dragging eight cells took contours across each other, which the editor
refuses, and moved ground 305 m at distances no cover reaches, so every setting
looked equally bad. Boxing the one node that moved rather than the contour made
every setting exact, because the cover reached far past anything that changed.
And judging each setting over its own `good` box flatters the small ones: a
bigger cover is judged over more ground and can only look worse, so what is
reported here is the worst error anywhere on the displayed surface - the patch
where the patch reaches, what was there before everywhere else.

The settings are interleaved and taken best-of three, not run one to
completion after another, because this laptop drops from about 1,500 MHz to
1,000 under sustained all-core load and whichever ran last would otherwise
look slowest.

**One thing that does not reproduce.** F3's figures for the two-radii setting
are 0.268 m over eighteen edits at 3 arcseconds and 0.035 m at 1; this harness
gives 0.777 m and 1.312 m for the same setting. The comparison between settings
is sound - every setting sees the same edits through the same harness - but the
absolute disagreement is real and unexplained, and most likely the edits: F3's
eighteen are not these thirteen.

**And the small things.** `local.resolve` loads `libisofill.so` and has no
fallback to the binary, which `interpolate` has had all along, so a machine
with one and not the other builds but cannot preview. The squares saved before
ids were unique across a working set still hold two contours claiming to be the
same way, which the preview detects and refuses rather than repairs. And the
overlay's second checkbox, *and cells seeing one level*, stays live when the
first one is off, where it does nothing.

**Decided, and done.** Changing the resolution used to do nothing until
*Rebuild* was pressed: the panel named one resolution while the surface stayed
at another, and an edit redrew at the old one. That was deliberate - it is what
stops an automatic rebuild spending 77 seconds at a resolution nobody asked for
- and it reads as the control not working, because that is what it looks like.
Choosing now builds. The Rebuild button stays, for rebuilding at the resolution
already chosen.

The idle rebuild still settles the surface on screen rather than the resolution
named in the panel, which is now a distinction only visible while a build is
running - but it is the right one either way, since what a preview needs
settling at is the ground it was drawn over.

**What is not F5c.** Persisting the display settings, and the contour tools a
mapper wants next - split, merge, join - are phase 5 and 6 work that using the
editor surfaced early.
