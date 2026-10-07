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
0 deliverable - not at release, where the plan said this kind of thing gets
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

**Not done, by choice.** R22, the published DEM as tiles around the working set
with a visible seam, needs `data.opengeofiction.net` to serve the DEM tiled and
belongs with the server's phase 3 changes. Windows packaging of the editor with
GDAL and `libisofill` is the release phase's polish; the MSYS2 job proves both
build there, which is what phase 0 wanted proven early.

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

## What phase 4 actually did

Ended on 2026-09-30, in thirty-five pull requests here and five in `isofill`,
over the eight days from the 23rd, with the exit criterion restated rather than
met as written - see *Phase 4* in `spec.md`, and *The exit criterion, measured*
below for the numbers that forced it. 191 tests that need neither Qt nor GDAL,
250 on the canvas, 52 that need GDAL.

The phase went to plan as far as F4 and then stopped being about what it said
it was about. F1 to F4 are the incremental path and the job queue, in the order
the plan gave them. F5 was to be the preview and then the margin; the margin
turned out not to be the binding constraint, nor the second, nor the third, and
what the afternoon of using the editor found instead is F5c - four things
ahead of it, none of which anyone had planned for, and the one that mattered
most was the drawing rather than the solve.

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
   that need it - **half done, and the other half moves to phase 7**: fresh
   ground triggers a rebuild, the detector for the other half turned out not
   to discriminate, and using the editor since has put a different question
   under it - whether a long session wants automatic rebuilds at all;
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

**The exit criterion, measured.** Phase 4 ends when drawing a contour moves
the hillshade under the cursor inside 50 ms, and the zoom that matters is z15
to z19 because that is where contours are drawn. Driven through the real
window - `editor.do`, then the preview driver's `patched`, then the next paint
of the surface layer - on the gobras 3x3, one node moved:

| ms, 3 arcseconds | z13 | z15 | z17 | z19 |
|---|---|---|---|---|
| `editor.do` | 30.2 | 30.1 | 28.6 | 30.0 |
| - of which `layer.refresh` | 27.3 | 28.2 | 26.8 | 27.6 |
| to the patch | 123.6 | 111.0 | 109.3 | 111.7 |
| to the frame | 124.3 | 111.8 | 109.9 | 112.8 |

At 1 arcsecond: `editor.do` 22 to 30 ms, the patch at 1,388 to 1,546 ms with
the solve 1,318 to 1,479 of it, the frame at 1,388 to 2,761.

**Zoom no longer matters**, which is the first thing the measurement says and
not what it was taken to find out. Flat from z13 to z19 at both resolutions:
F5c item 1 took the zoom dependence out of the repaint, and there is nothing
left that scales with what is on screen. The question the criterion was waiting
on had already been answered by something else.

**The criterion is missed**, by about twice at 3 arcseconds and thirty times at
1. But the UI thread is free in about 30 ms either way, so the editor is
responsive throughout and what is slow is the hillshade catching up. Those are
two clocks and one number cannot describe both. The budget at 3 arcseconds is
30 ms of `editor.do`, 30 of `GESTURE_MS` - the coalescing window that turns a
fast hand's run of edits into one preview, and deliberate - and 52 of the
solve. At 1 arcsecond the solve is everything.

**The one thing left on the UI thread was the contour layer, again.** Moving
one node re-projected 723 ways and 28,618 points, because `refresh` rebuilt
every way at the elevations the edited ways were and are at: a piece was
reachable only through the level that held it, so there was no way to replace
one. F5c item 1 had fixed `paint` and left `refresh` alone.

A piece now carries its own elevation and label, so dropping one is a list
removal by identity and adding one is a single path:

| ms, 3 arcseconds | z13 | z15 | z17 | z19 |
|---|---|---|---|---|
| `layer.refresh` | 3.9 | 4.2 | 5.4 | 4.8 |
| `editor.do` | 8.2 | 8.1 | 9.4 | 8.7 |
| to the frame | 96.4 | 89.0 | 91.2 | 97.1 |

`index_levels` is worked out again only when a level appeared or emptied,
which is the only thing that can move an index contour. Sorting every drawn
level is small against re-projecting 723 ways, but it still grows with the
working set, and that shape is what the change is for.

By identity and not by equality, in both the code and the test that holds it:
the pieces are rebuilt to the same coordinates, so an equality test would pass
on exactly the behaviour being removed. The first version of that test compared
`id()` values and passed for a worse reason still - a dropped `Label` is freed,
and the replacement landed on its address.

What the change does not do is end the phase. It takes 21 ms off a 110 ms edit
at 3 arcseconds and 22 off 1,400 at 1. What is left, at 3 arcseconds, is:

| | |
|---|---|
| `layer.refresh` | 4 ms |
| the signals `do` emits, run on the spot | 4 ms |
| `GESTURE_MS`, the coalescing window | 30 ms |
| the solve, on a worker | 52 ms |
| the frame | ~1 ms |

The eight milliseconds of `editor.do` are per-edit work on the UI thread and
belong to the responsiveness clock, not to the coalescing one; the thirty is a
deliberate wait for the rest of a gesture, and the fifty-two is the answer
being worked out. Three different things, which is why one number over the sum
of them does not say anything useful about any of them.

**So the criterion is two, and both are met.** `spec.md` carries the wording;
what it comes to is that the editor takes the next input in eight milliseconds
at either resolution, and that nothing a frame waits on grows with the raster,
because the solve, the compose and the build are all on workers. The original
number was a statement about the frame and not about the fill, and the fill is
now somewhere else. What that leaves is not a latency to shave but a policy
question - whether a long session should be waiting on those builds at all -
which is phase 7's and not a reason to hold this one open.

The fifty is the same fifty. What narrowed is what it is measured over - the
UI thread rather than the whole frame - and that is the right narrowing rather
than a convenient one, because the fill it used to include has moved off the
thread the frame is on.

Said plainly, because a restated criterion is the easiest thing in a document
like this to mistake for a lowered one: at 1 arcsecond it is still about 1.4
seconds from the edit to the hillshade moving, nearly all of it the solve.
Nobody is claiming otherwise. The claim is that the editor is drawing
throughout, which is what the fifty milliseconds was for.

**What is not F5c.** Persisting the display settings, and the contour tools a
mapper wants next - split, merge, join - are phase 5 and 6 work that using the
editor surfaced early.

## What phase 5 has done so far

**G1, spot heights are constraints.** R36 says a node carrying `ele` is a
constraint the same as a contour way. Nothing had ever read one, and the reason
turned out to be one line of configuration rather than a missing feature:
`osmconf.ini`'s `[points]` lists `ele` among its `unsignificant` keys, which is
GDAL's own default, and a node tagged with nothing else is then not reported in
the points layer at all. So `ele` moves into `[points] attributes` and out of
`unsignificant`, `collect` gathers the points into a `spot` layer beside
`contour`, and `rasterise` burns both.

**What it is worth, on four rings and nothing else.** Contours can only bracket
a summit - the ground inside the top ring is above it and below a ring nobody
drew - so the fill has nothing to aim at and leaves a plateau:

| | peak | cells at the peak | centre |
|---|---|---|---|
| rings alone | 175.0 m | 6,400 | 175.0 m |
| with a spot height at 240 | 240.0 m | 1 | 240.0 m |

That is R37 in two rows. The test asserts the pointedness as well as the
summit, because a test that only read the centre cell would pass on a spot
height burned into an otherwise flat plateau.

**The spot heights burn after the contours**, so one standing on a contour wins
the cell. A contour says the ground reaches this height somewhere along here; a
spot height says it is exactly this high at this point, and the point is the
more specific statement. It is also the case R37 exists for: a contour burned
over a summit flattens the thing the spot height is there to raise.

**The barrier measurement the phase asked for first.** `barrier_cells` widens a
constraint for the sight test, so a one-cell spot height becomes a five by five
occluder where a contour is a line and hardly notices. Measured on the same
hill, three placements - a spot on the summit, one standing between two rings
where rays have to pass it, and one outside every contour - **no cell loses its
reach in any of them**, and the summit one gains reach for the 1,257 cells of
the disc that can now see something. The fear was reasonable and the answer is
no.

Counting that required naming the classes rather than comparing them: 1 is
nothing in reach, 3 is a single level in sight, 0 is answered, and a first pass
at this read the numbers as a severity ranking and reported 1,256 cells getting
"worse" when what had happened was 1,257 cells getting better.

**A spot height beyond the contours stretches the envelope**, and that is now a
decision rather than an accident. `drawn_area` takes the convex hull of the
constraints raster per degree square and a spot height is in that raster, so
one placed outside grows the drawn area - 519,841 cells to 649,621 on this hill
- and the ground between gets filled. It follows from R36 reading a spot height
as a constraint *the same as a contour way*, since a contour way out there
would stretch the hull too. The alternative is coherent as well - the envelope
being the lines' alone, with spot heights constraining inside it and never
extending it, which isofill supports either way because a constraint outside
the mask still counts as evidence - and a test now says which one is in force
so that changing it is a decision someone makes.

**The preview had to follow, which was not the plan.** G1 was to be the
pipeline alone. But `preview.Contours` burns its box from a layer of contours
after clearing the box to nodata, so a preview over a hilltop would have rubbed
the spot height out and handed the solve a raster the build would never have
produced - the hill flattening under the cursor until the exact rebuild. The
preview now carries the `spot` layer too, read-only, burned after the contours
in the same order the build uses. Editing a spot height is G2, and that layer
is where it will go.

**The burn order is ours and not GDAL's.** `rasterise` first passed both
layers in one `Rasterize` call with `layers=['contour', 'spot']`, which leaves
the order to whether GDAL iterates the list or the datasource - the
GeoPackage's internal layer order, possibly differently between versions. The
preview burns layer by layer in a Python loop, so it has no such doubt, and the
two paths disagreeing about which constraint wins a cell is the failure the
preview architecture exists to avoid. It is one call per layer now, in order.
Not the same mechanism at both ends - the build's first call creates the raster
and initialises it to nodata, the second adds to it, and the preview fills its
window by hand before burning either layer - but the same *order*, decided by
us in both, which is the part a cell's value turns on. That the second call
adds rather than starts again is the other half of it, and has a test of its
own: the contours still read what they read, and a spot height adds exactly one
constraint cell.

**The silent-loss guard extends to them, and warns rather than stops.** The
scanner behind `check_long_ways` already told an `ele` inside a way from one
outside it - it had to, or a spot height before a way made that way look tagged
- and threw the second count away. It now returns it, and `collect` says so
when a square holds `ele` outside its `way` elements and contributes no spot
height, which is the failure that cost liberian 81% of its constraint lines
silently. A
warning and not a refusal, because the count is of `ele` outside a *way* rather
than on a *node*: telling those apart means matching `<node` as well, and there
are two and a half million of those in the largest square, which is the whole
reason this scans rather than parses. A relation tagged `ele` would be counted
and is not a thing these squares hold - not yet: G3 grows the model to carry
them, and R26 flattens a water body by putting `ele` on one, so the false
alarm this tolerates becomes a case that actually arises. The cost of being
wrong is a line in a log rather than a zone build stopped, which was the right
call for one reason and stays the right call for the other.

**What it costs on deployment.** The golden square holds no such node, so the
committed reference surface is unmoved and `test_golden_surface` is
unaffected - though the golden *suite* is not untouched, since the scanner's
count is now a five-tuple and the test holding it to a parse of that same
square counts its node-level `ele` tags too, of which it has none. Both tests
read `S24E125_Los_Pizarrales.osm.xz`, and the scanner's one now asserts the
absence rather than assuming it - so a fixture that grew a spot height says so
there, loudly and by name, rather than in a reference surface moving under
somebody. Of the
squares checked out on this machine on 2026-10-01 exactly one carried one -
`gobras/N20E086`, a node at 225 m - so what a rebuild changed there was one
hilltop. That is a reading of a working tree on a day and not a property of
anything; what a zone costs is whatever its squares hold. Elsewhere it is whatever the
zones hold, and the change is a DEM rebuild rather than a packaging one: same
input files, no new dependency, no new data file.

**G2a, a spot height is an edit the preview can show.** G2 is the editor
editing them, and it splits where F5a and F5b split: what an edit *is* and how
the preview follows it, then the canvas. This is the first half. Nothing in the
editor places a spot height yet; everything underneath one is here.

**`Command.spots()`, beside `ways()`.** A command says which ways a view has to
redraw; it now also says which nodes may have stopped or started being
constraints. *May*, and the word is doing work: `MoveNode` does not know
whether the node it moves is a spot height, a vertex of a contour or neither,
and it answers from its own fields because it is asked before apply and after
undo alike. So it names the node and the driver asks the square - which is
exactly what `ways()` already makes the driver do with a way that may or may
not carry an elevation. The default is empty, because most commands are about
ways and the two that are not say so.

`AddNode` is new and is not `InsertNode`: one puts a vertex into a way, the
other is a node that belongs to nothing, which is the only kind of node that
means anything on its own. `SetNodeTags` is `SetTags` for a node, and is how a
node becomes a spot height or stops being one. `MoveNode`, `DeleteNode` and
`Compound` name their nodes; `InsertNode` and `SetTags` do not, and a test says
so rather than leaving it to the reader of a default.

**The preview's spot layer stops being read-only.** G1 put it there to keep the
preview and the build burning the same raster. It now takes `apply_spot` and
`remove_spot`, mirroring `apply` and `remove` down to keeping each feature's
FID - for the same reason, which is that within a layer the last feature to
touch a cell wins it, and a spot height moved or re-valued should land on the
side of a tie the build would have put it.

**And the driver follows a node the way it follows a way.** Three cases,
settled against the square rather than against the command: it carries an
elevation now, so put it in the layer and box it - and the cell it came from as
well, since a spot height moved leaves ground behind it; it carried one and
does not now, so take it out, box where it was, and ask for the wider cover
that a constraint taken away needs; or it never did, so do nothing and box
nothing, because a node with no elevation constrains nothing and boxing it
would solve ground the edit cannot have touched. An `ele` that is not a number
is the third case, not a constraint at zero - `ele=TBD` on a lake outlet and
`ele=tbd` on a peak are both real, and the build drops them.

**Held against a rebuild, which is the only claim worth making.** Placing,
moving and removing a spot height in the preview's layer, then burning a box
from it, gives cell for cell what a build of the square that edit describes
puts there. The placing case starts from a working set with no spot height in
it, which is the one a mapper is in the first time.

**One thing G1 got wrong and this corrects.** G1's `collect` comment said the
`spot` layer does not exist until some square contributes a spot height, and
its test was written to cover the append that creates it. Both translates make
their layer on the first square whatever that square holds, so an empty `spot`
layer is there from the start, exactly as an empty `contour` layer would be.
The test is kept - a later square appending to an existing empty layer is still
the path a zone build takes - and it says what it actually covers. The
preview's make-the-layer-on-demand branch is kept too, and now says what it is
for: a GeoPackage written before G1, which an editor started on an old working
directory can still be handed.

**G2b, the canvas.** The other half: a mapper can now see a spot height, put
one down, pick it up, move it and take it away.

**Drawn from z12 up**, which is not where they started. The first version drew
them at every zoom this layer draws at, index levels or not, on the argument
that a spot height is not a level - there is one of it - so hiding it with the
intermediate contours would hide the only thing that says how high a hill goes.
That is still true about *levels* and was the wrong conclusion about *zooms*: a
working set holds a spot height per hilltop, and at z8 to z11 they are a
scatter of dots over index contours too coarse to place them against. `ZOOM_SPOTS`
is 12, where a hill is a hill rather than a smudge.

**And picking follows painting**, with the rule in the layer rather than at the
call site so the two cannot drift. A click that selects something invisible is
worse than one that selects nothing, because the next keystroke goes somewhere
the mapper cannot see.

The marker is a ring in the elevation's own colour, sized in pixels rather than
scene units: it marks a point, and a marker that scales with the zoom is a dot
at z12 and a blot at z19. The value sits beside it from `ZOOM_LABELS`, where
the contour labels start.

**Picked before the contours.** It is a few pixels across and sits on ground a
contour runs through, so a click that could mean either means the small thing.
Shift still reaches the line, as it already did for a contour's nodes, and for
the same reason.

**`Selection.way` becomes optional**, which is the whole of what R36 costs the
selection: a node that is its own constraint rather than a vertex of something.
Every reader of it has to ask, and `Selection.spot` is the question. The one
place it changes behaviour rather than just guarding is undo: a contour's node
undone away leaves the contour selected with no node picked, where a spot
height undone away leaves nothing selected, because there is nothing left.

**The tool is `Z`**, under `Q` for select and `A` for draw. The tools are a
column under the left hand for the same reason the elevation keys are, and
there was a third row free beneath them.

**What it does not do: change the elevation of one that is already placed.**
The way to is to delete it and put another down. That is parity rather than a
gap - there is no action that re-tags a *contour* either, and the editor has
shipped three phases without one - but it is felt more here, because a spot
height's value is the whole of its content where a contour's line is most of
its. An action that re-tags whatever is selected would serve both and belongs
with the rest of phase 6's polish.

**And a button on the map**, under select and draw, because a hand on a map
looks for the tools on the map - which is what the phase 3 review said about
zoom and the mode beside it. The icon is a triangle with a dot in it, the
surveyor's mark for a measured height. Four were drawn and looked at: a dot
beside two short rules, meaning *a point with a value written next to it*,
reads as a dot beside an equals sign; a dot under an up arrow reads as *move
up*; a ringed crosshair reads as *aim*. The triangle says height without a
digit, and a digit at eighteen pixels says nothing. Looked at, because the
first one drawn passed every test and read as a musical note.

**The `ele` tag has to read back, and now says so.** The elevation goes into
the tag through `format_ele` and comes out through `float()` - in another
module, inside a `try` that reads a failure as *this is not a constraint*,
which is right for the `ele=TBD` a square really carries on a lake outlet. That
leniency is what would turn a change to `format_ele` into a spot height
silently not drawn and not pickable rather than into an error. `format_ele`
says what it owes its readers, and the round trip is held twice: over a few
hundred values in `tests/test_ladder.py`, and through the editor at 0, 12.5,
-3, 1234 and `0.1 + 0.2`.

**An elevation that is not a number, in the other sense.** The round trip
above is about a tag our own readers would *decline*; review found the hole on
the other side, a tag they **accept**. `float` reads `inf` and `nan` back
happily, so `parse_ele` returned them, and an infinite elevation reaches a
colour ramp, a ladder, a label and a rasteriser, each of which does something
different and silent with it. That is not new with spot heights - a contour
tagged `ele=inf` has always got through - but a spot height's whole content is
its number, and placing one is how the editor would write such a tag itself.

Refused at both ends now. `parse_ele` declines a non-finite value exactly as it
declines `tbd`, which is the one place a tag becomes a number for contours and
spot heights alike; and `format_ele` raises rather than write one, because the
elevation reaching it comes from a spin box, from arithmetic along the ladder,
and from a value picked up off whatever a square holds.

The two new readers stopped having their own copy of the rule as part of it:
`_project_spot` and the preview driver both call `parse_ele` now, where each
had its own `float()` in a `try`. Three spellings of *is this tag an
elevation* was two too many.

**One thing worth recording about the tests.** The first version of the
drawing test set the zoom inside its loop and the centre outside it, so each
step zoomed away from the spot height and found nothing drawn. It read as a
layer that stops drawing above z9. The test was wrong and the code was right,
which is worth saying because the opposite conclusion was one line away and
would have had me 'fixing' a paint that works.

**G3, the square carries relations.** R41. `read_square` skipped a relation
and `write_square` wrote none, so a square was nodes and ways; it is now nodes,
ways and relations, read in file order, written back in it, and minted from the
allocator that already took one counter across two namespaces and now takes it
across three.

`Member` is its own frozen record of type, ref and role, because all three are
data: a multipolygon's rings are told apart by the role, and an absent role is
written absent rather than as an empty string, which is what the file means.
Relations go last, as JOSM writes them - a member names a way by id, and
putting the ways first means a reader meets the reference after the thing it
refers to.

**The thing that was actually going to break is the split.** `split_long_ways`
cuts a way over two thousand nodes into pieces, the first keeping the id and
the rest taking fresh ones. A relation naming that way would have kept the
first piece and lost the rest - a lake's outer ring down to its first two
thousand nodes, a hole in the shape, written on save, and nothing said. Both
implementations of that rule mend it now: `_ReplaceWays` on the model replaces
the member with one per piece, in order and with the same role, keeping the
whole member list for the undo; and `danu/core/split_long_ways.py`, which
rewrites the XML textually on the server every night, does the same during its
single pass. It can, because a square writes its relations after its ways, so
the pieces are known by the time a member is read - and a file that does not
is refused rather than half mended. Checked as *no way after a relation*: the
first version asked whether a relation came before the first way, which a file
that interleaves them walks straight past, and interleaved is exactly what a
hand-edited or third-party file does.

The test that holds the two implementations together already compared them way
for way. It compares them relation for relation now, by shape rather than by
id: the two mint their fresh ids from different counters, which is why every
comparison in that test was of sequence and not of identity in the first place.
Writing it the obvious way - member refs equal on both sides - failed, and
failed for the right reason.

**And the build does not notice.** Nothing reads a relation yet; `collect`
gathers lines and points. A square that grows one has to build exactly as it
did before, which is not a given: GDAL's OSM driver assembles multipolygons
into a layer of their own, and a driver that dropped member ways from `lines`
while doing it would take a contour out of the constraints for no reason the
file shows. It does not, and there is a golden test saying so rather than an
assumption.

**What G3 does not do** is let anything *edit* a relation - no tool, no
command, no selection. A square round-trips one faithfully and the split keeps
it whole; creating and changing them is G4's business, where the import is what
produces them.

**G4a, what an import is.** The mechanics, without the editor: the query, the
fetch, the filter and which square each feature belongs to. Nothing writes a
square yet - that is G4b, where an import becomes one undoable step.

**It asks for the working set's bounds.** Not the centre square: a river is
graded along its course and a lake flattened across its surface, and both are
cut short by asking a degree at a time. Not the view, which moves.

**It keeps `natural`, `water`, `waterway`, `name` and `ele`, and nothing
else.** A square is somebody's file, and an import that drags in `source`,
`wikidata` and a decade of someone's tagging is harder to reconcile and harder
to read. The tags come out in the order `KEEP` names them, so that two imports
of one feature write the same line and a diff of two versions of a square is
worth reading.

`waterway` is in that list and was not in the sentence that set it, which said
`natural=water`, `water=*`, `name=*` and `ele`. It is here because R27 -
*flowing water is never flattened* - cannot be honoured by a square that
cannot tell a river from a lake, and R25 grades a river along its course.
Dropping it would import rivers as untagged lines and leave G6 and G7 unable
to do the thing they are for. Written down rather than slipped in, because it
is a widening of what was asked.

**A feature goes whole into one square**, the one holding its anchor - a way's
first node, a relation's first member that resolves to one - and its nodes go
with it even where they fall in a neighbour. Whole rather than clipped at the
boundary, for two reasons that are the same reason: a clipped river is two
ways with two ids and the next import has nothing to match the original
against, which is R40 and the whole of G5; and a clipped ring is not a ring,
so cutting a lake at a degree line turns an island into a peninsula.

**Relations are placed before ways**, and a way that is a member goes where
its relation goes rather than where its own first node falls. Otherwise a
lake's outer ring is placed twice - once on its own account and once as a
member - and a square two degrees away holds half its shape.

That rule had a test which passed without it. For a relation of one way
member the two anchors cannot differ, because the relation's anchor *is* that
way's first node: the fixture had to grow a node member in another square
before the test could tell the rule from its absence. Found by taking the rule
out and watching the test go on passing, which happened twice in this file -
the nested-relation test had the same shape and the same fault.

**Relations nest, which review caught and the first version dropped.** A
multipolygon's outer may itself be a relation, a shape OSM really holds; with
only way and node members handled it imported as a shape with nothing in it.
Three things make that work: `_put` follows a relation member, `_outermost_first`
places a relation that nothing names before one that is named - or a child is
placed on its own account first and then again by its parent, in two squares -
and a `seen` set stops a relation that names itself, directly or round a ring
of others, from walking for ever. Bad data rather than a shape, but bad data
is what a public API returns.

**Only a relation that was placed claims anything.** One anchored outside the
set is dropped, and a member way of it that *is* inside has to be left for the
standalone pass; claiming on behalf of a relation that never landed would have
the way belong to nothing and vanish.

**Nothing reaches the network.** The fetch takes its opener as an argument,
as the tile and territory fetchers take theirs, and every test here hands it
one.

**Two things review asked for, one of which I could not reproduce.** The
anchor's cycle guard is now the recursion path rather than the whole walk -
added on the way in, discarded on the way out - which was asked for on the
argument that an accumulating set would mark an inner relation seen on a
branch that found nothing and then refuse a later branch that needed it. I
could not build that case, and it cannot exist: whether a relation resolves
depends on what it can reach and not on how it was reached, so a second visit
returns what the first did. The path-scoped shape is kept because it is the
right one and costs nothing, and the docstring says it is not a fix for a bug
anyone has seen. The test written for it was dropped, because it did not
distinguish the two.

The other was the claim that an imported positive id cannot collide with one a
mapper draws. It is true - `IdAllocator.include` takes `min([0, *ids])`, so a
positive id never moves the counter - and it was asserted rather than shown,
which for the thing the whole identity story rests on is not good enough. It
has a test now.

**And one for G4b.** `place` deliberately files a feature's nodes under the
square the *feature* is in, which for a river crossing a degree line is not
the square some of those nodes are in. That is the point - a feature stays
whole and keeps its id - and it means G4b has to write a bucket into the
square it is filed under rather than sorting the nodes by where they fall.
`write_square` writes a node where it is, so the file is right either way;
what would be wrong is a river split across two files by a writer being
clever.

**The query, tuned.** Three changes, all from reading it rather than running
it. The box moves into the settings as `[bbox:...]`, where every statement
inherits it, instead of being written out on each - the same query, written
once. The waterways become two exact matches rather than one regex, because a
tag value is an index lookup where a pattern is a test run over what the index
returned. And the timeout comes down from the batch grading's 900 seconds to
60: a quarter hour at 3am is nothing and an editor is somebody sitting there.
The read waits 75, a little longer than the server's own limit, so a timeout
comes back as Overpass saying so with its reason rather than as us cutting the
connection and guessing.

`>>` stays, and that is the one place this costs anything. `recurse.cc` has
`DOWN` collecting a relation's member nodes, its member ways and those ways'
nodes, and `DOWN_REL` doing the same after a `relations_loop` over member
*relations*. Under `>` a multipolygon whose outer is itself a relation arrives
as a member id with nothing behind it - a feature without its geometry, which
is not something a square can hold, and which `place` has code to follow.
Settled from the Overpass checkout rather than from memory.

**Measured, against the real server.** Three variants over the gobras 3x3
(86..89 E, 19..22 N), then the whole import end to end.

| | fetch | payload | ways | nodes |
|---|---|---|---|---|
| river + stream + bodies | 0.7 s | 12.94 MB | 4,446 | 147,439 |
| the same with `way["waterway"]` | 0.6 s | 14.50 MB | 5,415 | 164,701 |
| river + stream + riverbank + bodies | 0.7 s | 13.89 MB | 4,561 | 158,633 |

**`way["waterway"]` was tried and is not kept.** It brings 969 more ways: 467
drains, 280 ditches, 44 canals, 32 docks, 24 dams, 5 weirs, two lock gates, a
boatyard and a fish pass. None of them is graded by anything - the batch
grader reads rivers and streams as lines and has done since it was written -
so each would sit in somebody's square and be reconciled on every re-import. A
dam and a weir are lines *across* water; a ditch graded as a valley floor is a
dug channel read as terrain. R23 names the scope and it is rivers, streams and
water bodies.

**`waterway=riverbank` is kept, and finding it is why the experiment was worth
running.** Deprecated in favour of `natural=water` + `water=river`, and the
data has not caught up: 115 of them over this box, 114 closed, and **not one
also carrying `natural=water`**. Without it the river *surfaces* are missed
entirely - 11,835 nodes of them - which is a gap and not a tidiness question.
It turned up in the batch grader's own `FLOWING` list and nowhere in the
query.

**`>` and `>>` returned byte-identical answers.** There is no water relation
inside another water relation anywhere in this box, so the nested-relation
handling in `place` currently exercises nothing in this data. `>>` stays
because it costs nothing here and the shape it covers is real elsewhere, but
the honest state of it is untested-in-anger.

**Does a global `[bbox:]` bound the recurse?** Review said it might, and
called it the one thing to settle before merge - rightly, because a bounded
recurse would hand a square a river with its far bank missing, and the whole
argument for `>>` is that a feature's geometry has to come with it. Run both
ways over the same box:

| | nodes | ways | relations | nodes outside the box |
|---|---|---|---|---|
| box on each statement | 158,633 | 4,561 | 112 | 1,535 |
| `[bbox:]` in the settings | 158,633 | 4,561 | 112 | 1,535 |

Identical id for id, and the second column is the one that answers it: 1,535
nodes beyond the bounding box came back either way, across the 39 ways that
cross it. The two files differ by one line, which is the `<bounds>` element
the global form echoes. The setting reaches the selection statements and not
the recurse.

**And the thing G4b needs.** End to end, on a warm server:

| | |
|---|---|
| fetch | 0.72 s, 13.89 MB |
| parse | 0.52 s, 158,633 nodes into 4,673 features |
| place | 0.04 s |

About one and a third seconds, which is twenty-six times the frame budget and
a fortieth of what the batch grading's timeout was written for. It wants a
worker, as the build and the preview solve do; it does not want a progress
dialogue. One measurement on a quiet server with a warm cache, which is why
the 60 second timeout is there.

Two things the numbers said that the plan had not. **Seventy per cent of the
import lands in one square** - N20E086 takes 3,277 of the 4,673 features - so
"an import is one undoable step" is mostly one square's step. And **features
land in squares that have no file**: N19E086 and N19E087 are not present in
this set and are given 261 and 94 features between them. Whether an import may
bring a square into being, when R5 has blank templates created deliberately,
is a question for G4b and not one the import gets to answer by writing a file.

**G4b, an import is one undoable step.** `ImportWater` writes one import's
features into one square and takes them all back. R40 asks for that in as many
words, and the reason is not tidiness: an import writes hundreds of features at
once over somebody's file, so the answer to a bad one has to be Ctrl+Z and not
an afternoon.

What it writes is what it is given. Deciding what to write when the square
already holds a feature of that id is reconciliation, which is G5; this records
whatever was there and puts it back on the undo, so a second import replaces
and takes itself back exactly - the floor G5 builds on rather than the rule it
will apply.

Its fields are `new_nodes`, `new_ways`, `new_relations` and not the obvious
names, because a dataclass field called `ways` **shadows the `ways()` every
command owes its caller**: the instance attribute wins the lookup and
`cmd.ways(square)` becomes an attempt to call a dict. Written the obvious way
first, and ruff said nothing - the clue was a `noqa: F811` I had added to quiet
the redefinition without asking what it was telling me.

**Bringing a square into being needs nothing.** #87 settled that an import may,
and `save_square` already frames a square that is not present, writes it and
marks it so - the same path a mapper's first contour in a blank square takes.
The import puts features into the in-memory `Square`; the save does the rest.

**R42, measured first.** `has_constraints` now takes an elevation, a coastline
or water, where before it took an `ele` tag and nothing else. Three things the
measurement said that the decision could not:

The widening changes less than it looks. A square whose water carries an
elevation was already caught by the `ele` scan - which is why coastline-only
squares have always counted, a coastline being tagged `ele=0` - and one whose
water carries none contributes no ground anyway, because `collect` gathers
lines with an `ele` and nothing else. What it stops is such a square being read
as a blank template, which is what it is not.

The cost I predicted did not appear. A water-only square outside the zone's
current bounding box would enlarge the raster, and the two squares an import of
the gobras set would create are at lat 19, which looked like a third more
raster - except the real zone already spans 86..90 by 18..22 because of
`N18E089`, so they fall inside it and the grid does not move at all. Measured
rather than asserted, and the assertion was wrong.

And the pair is matched either way round, with anything between, as long as
both halves are inside the one tag element. The first version wanted them
adjacent and `k` first, which is what JOSM writes and what `write_square`
writes - and this file is read from wherever a mapper got it, so a reversed or
separated pair would have gone unseen and a water-only square been read as a
blank template. `[^>]` is what keeps the two halves in one tag: allowed to run
past it, `natural=wood` followed by `landuse=water` answers yes.

The pair match needed a wider window than the scan had. `k='natural'
v='water'` is twenty-one bytes where the longest token before was ten, and the
tail kept was the last sixteen bytes *of the block just read* - so a chunk
smaller than the token leaves the window shorter than the thing being looked
for, and a pair spanning three reads is never whole in any one of them. It is a
rolling tail now. Written the old way the test fails at chunk sizes 8 to 11 and
15 and passes everywhere else, which is the kind of bug that waits for a file
of an awkward size.

**And three the review was right about, after one it was not.** `apply`
re-snapshotting `before` on every call reads as losing the original on a redo.
It does not - the undo puts the square back before the redo snapshots it, so
the second snapshot equals the first - and the test walks that cycle three
times rather than arguing about it. But the invariant was the caller's and not
the command's: applied twice with no undo between, a second snapshot records
the import and the original is gone. `before` is captured once now, and a test
applies it twice.

`spots()` named every node it imported, and the driver walks that list on the
UI thread. A river network is 158,633 vertices on the gobras set; each one
would have been looked up, read for an `ele` it does not have, and dropped -
a hundred and fifty thousand no-ops between two keystrokes. It names the nodes
that carry an elevation, which it can do because unlike `MoveNode` it holds
the nodes rather than their ids. That is the rare node an import brings that
is a constraint and not geometry: a named spring on a river line.

And the coastline claim was stated as if it were about OSM. It is about *these
files*: a coastline in the gobras squares carries `ele=0` as well as
`natural=coastline`, checked rather than assumed, which is why coastline-only
squares have always counted under the `ele` scan alone. A coastline from
anywhere else carries no elevation, so the coastline branch of the pair match
is not the redundancy it looked - it is what catches one drawn elsewhere, or
by a mapper who did not add the zero.

**G4c, the editor does it.** Ctrl+I, a worker, one step on the history, and
water on the canvas.

**A step can span squares now, which is what R40 needed.** `SetUndoStack` kept
one `(square, command)` per entry, and an import of a working set lands in up
to nine files at once; one Ctrl+Z had to take all of them. An entry is a
*list* of pairs - `do_across` puts them on together, `undo_across` takes them
off in reverse, and `do`/`undo`/`redo` are the one-pair case of each. `dirty`
counts a step once for each square it names, which is what offers every
touched file to the save.

**The importer is the builder's queue with a different job.** Newest wins: a
mapper who presses import twice gets one import. The one already out cannot be
stopped - `urlopen` is a blocking read with no cancellation hook - so it
finishes and its answer is dropped by serial, which costs a few seconds of
somebody else's bandwidth and no correctness.

**Water is drawn under the contours**, in one colour rather than the ramp's,
because none of it has an elevation to take a colour from until G6 - a river
is where the valley floor is and not how high it is. Under, because it is the
context a contour is drawn against and not the work.

**And a lake nearly drew as nothing.** A multipolygon's rings carry no tagging
of their own; the relation holds it. A layer that asked the way alone would
keep 1,434 tagged `natural=water` ways and silently drop every ring of the 112
relations - which on this data is most of the lakes. `_project` takes the
square's water-relation members as an argument, gathered once per square
rather than searched per way: 112 relations against four thousand ways is the
difference between a lookup and a scan.

The test for that failed first for a better reason than the one it was written
for. `_project` returns None for a way that is neither contour, coastline nor
tagged water, so an untagged ring never became a geometry at all and the later
"is it a member" check had nothing to ask about. The decision belongs in the
projection, where both the open path and the edit path go through it, and not
in the two callers afterwards.

**Caught during the work, not in it.** Three `str.replace` calls were written
without asserting their anchor, against a file whose anchors were on the parked
`viewport-first` branch rather than on main - so they did nothing, and
`ruff --fix` then tidied away the imports for code that had never landed. The
menu entry appeared and the method behind it did not. It was redone with
`assert old in s` and the branch carries the mended version; the note is here
because asserting the anchor is the difference between a failed edit and a
silent one, and this file has said so since the splice that deleted two tests.

**What the two reviews changed.** Four of their findings were real and three
were worth the change anyway.

The real one was the working set. `_water_imported` read `self.working_set`,
which is the set open when the fetch *returns* and not the one whose names
chose the squares. The names of two grids can match and the `Square` objects
behind them cannot, so moving in that second and a half put the features into
squares nobody asked about, silently. The answer carries its set out with it
now and the window refuses one that is no longer open. `started` carries it
too, for the same reason one step down: a queued request begins when the one
before it answers, so the status line could name bounds nobody was fetching.

`self.water` was initialised in `set_working_set` and not in `__init__`, which
`_paint_water` reads to decide there is none - a layer painted before it had a
set raised `AttributeError`. The `spots` dict had always been in `__init__`;
this was the odd member out, and the test that catches it builds a bare layer
and renders it.

`do_across([])` went on the history. The Ctrl+Z that reached it popped the
empty step, undid nothing, and answered `None` - which every caller reads as
"the history is empty" - so the keypress was swallowed and the edit before it
stayed done. Nothing is not a step.

The predicates disagreed. `_is_water` took any `waterway` on a way;
`_water_members` took only `natural=water` on a relation. The import cannot
produce the difference, because the query asks for `relation["natural"="water"]`
and nothing else, but a `type=waterway` relation can be drawn or already be in
a square, and its members carry no tagging of their own exactly as a lake's
rings do. Both now call one `_water_tags`, so they cannot answer differently.

The tooltips named keys rather than bindings - `(Q)`, `(A)`, `(Z)`, `(Ctrl+I)`
written out, while every one of those four is in `DEFAULT_KEYS` and reboundable
from the settings. `MapControls` takes the settings and builds the tooltip from
`key(action)`.

The rest of the second review was the diff read without the files around it:
`ImportWater`, `dirty_squares` and `Water.__len__` were all reported as
possibly missing and all three are on the branch.

## Water drawn as water

Two things, taken together because the first is what the second needs before
G5 lands.

**One forward path.** `_water_imported` wrote out `history.do_across`, the two
refreshes and the two signals - the same lines as `_history_move` minus
`_after_history_move`. Two review rounds pointed at the duplication and I
filed it as deliberate twice. It was harmless only because an import adds:
nothing under the selection could vanish, so there was nothing to clear. G5's
reconciliation replaces superseded features, which is a delete, and then the
forward path would leave a selection pointing at a way no longer in the square
while undoing the same step cleared it. `EditController.do_across` is the one
entry point now, and the test deletes the selected way forward to prove the
ask is made.

**Filled bodies.** A lake drawn as an outline reads as a very round contour,
which is the one thing the water layer exists to stop. So the bodies are
filled, and every water way is still outlined over the top - two passes,
because they say different things: the fill says *inside*, the edge says
*shore*, and where the wash is faint the edge is what a mapper draws against.

The fill is per *relation*, not per ring. An island in a lake is an inner ring
and filling each ring on its own paints the island solid - the one case
relations were grown for in the first place. All of a relation's rings go in
one `QPainterPath` with an odd-even fill, and the hole falls out of the
geometry rather than out of a role we would have to trust.

Which means the rings have to be stitched back together first, and that is
`danu/core/rings.py`: a lake's boundary is a dozen ways in whatever order the
relation lists them and whatever direction each was drawn, so the chaining is
greedy and takes a piece off the pile when either of its ends meets either end
of the chain. It is core rather than ui because it is topology and the `tests`
job can run it without Qt.

Two things keep the stitch from depending on the order the members arrive in,
and the local review found both. A piece that is already a ring is lifted out
first and kept whole: spliced into an open chain it grafts a loop onto a line
and makes a shape that is in neither, and on the real gobras import that was
one lake drawn wrong - the relation fills went from 92 to 93 when it was
fixed. And the rest are sorted by their own node ids, so where a node is
shared by more than two members and the greedy choice is genuinely ambiguous,
it still falls the same way every time. The editor and the server read the
same relation and have to fill the same shape; "whichever order the members
happened to be listed in" does not give that.

What does not close is not filled. A square holds its own degree, so a lake
crossing the edge arrives cut, and those pieces chain into an open line. It
keeps its outline and gets no fill. Closing it would draw a shore along the
square edge that nobody mapped.

The gobras 3x3 does not exercise that, and an earlier draft of this paragraph
said it did. Of the 112 relations in the Overpass answer, 19 are placed into
N19E086, which the set does not hold, so they are never drawn; the other 93
land in present squares and all 93 stitch. Nothing in this box fails to close.
The count here was 92 before the closed-member lift, and the one it recovered
is the only evidence this data gives: the straddling case is covered by tests
rather than by the import.

**The cost, measured.** Painting: +2.2 ms at z10, +0.5 ms at z13 and z15, on
773 fills drawn of 2,072 - the per-piece rectangle cull was already there and
the fills use it. Opening: 65 ms of the 579 ms `set_working_set`, which is on
a worker.

Editing was the one that needed fixing. Rebuilding the square's fills on every
water edit cost **50.7 ms** on N20E086, which holds seventy per cent of the
box's water - a whole frame, on the UI thread, which is exactly the cost phase
4 was spent taking out of `refresh`. A way can only change its own fill and
the fills of the relations that name it, so only those are rebuilt: **0.5 ms**,
and finding which relations name it is a walk of 112 relations rather than of
four thousand ways.

**What the PR review changed.** Three, and all three are about a fill that
stops being true rather than one that never was.

A ring missing a node was filled across the gap. `_project` allows a way in a
square whose nodes are not all in it, and draws the part it knows, which is
right for a line - but a line may stop short where a shape may not, and
joining the two sides of a missing node draws a shore nobody mapped. It is the
straddling case by another road, and gets the same answer: outline, no fill.
`_ring_path` now wants every ref placed, not merely four of them. On the real
import it costs nothing - 2,073 fills before and after - which is the
reassuring result, because it means the invariant usually holds and the guard
is for when it does not.

A relation that stopped *naming* a ring kept the ring. The rebuild was keyed on
"a changed way is a member of this relation", and a relation that loses its
outer ring names no changed way at all. That is exactly what G5 does -
reconciliation rewrites member lists - so the fill a relation was built from is
remembered and compared, and a relation whose members moved is redone whatever
the changed ids say. The first attempt at a test for this passed without the
fix, because the edit it made happened to name the new member; the one that
bites reports a river nearby and nothing else.

And `_add_water_fills(square, members=frozenset())` had a default that was a
lie: called without `members`, every ring of every relation gets a second fill
of its own, the one thing the docstring warns against. It is required now.

The review also asked for the ordering test to compare rings rather than node
sets - two stitchings can group the same nodes in a different order, and the
order is the shape - so it compares them up to rotation and reversal.

**The second review: one real, one that dissolved.**

The real one was a guard that made its own check unreachable. `refresh` only
called `_refresh_water_fills` when one of the changed ways already had a fill
or a line - and the one thing in there that an *ordinary* edit can have broken
is a relation's member list, which names no changed way at all. So the
staleness check added in the round before could never fire on the only path
where it was the only thing that could. The guard is gone. It costs 0.25 ms on
N20E086, six thousand ways and seventy-eight relations, which against the 8 ms
an edit has is worth paying to make a check true rather than decorative. The
test that pins it edits a contour and nothing else.

The second dissolved when the test for it was written, which is the useful
thing about writing the test first. The claim was that a closed way which is a
member of a relation the square cannot stitch loses its fill: skipped by
`_way_fill` for being a member, and not drawn by the relation because the
relation drew nothing. But a closed member *is* a ring - `closed_rings` lifts
it out whatever happens to the cut pieces around it - so the relation always
has a path and the member's ring is in it. The test written to show the gap
showed the lake filled, and is kept saying so, with the cut piece beside it
getting an outline and no fill.

**The water was the ramp's blue.** Reported from the running editor, on
N20E086, as "contours are getting drawn as water" - and the fills were
innocent: the ten largest on that square are the Bosco River, Lake Kinser and
seven `waterway=riverbank`, all correctly tagged. What was wrong was the
colour. Contour lines take theirs from the hypsometric ramp, and spectral
starts at (43, 131, 186) and walks through teal into green, so a 40 m contour
sat 18 units in RGB from the water's (70, 130, 190) and everything under 80 m
within 33. Eighteen units is the same line. On a coastal square almost every
contour is under 80 m, so the whole sheet read as drainage.

Water is (20, 70, 140) now, 80 units clear of the nearest colour the ramp can
make at any elevation in the square. It had to come out of the darkness and
not the hue: the ramp spends its first two hundred metres walking from blue to
green, so there is no free hue down there, only a free value. The test asserts
the distance against the ramp rather than against a literal, so changing the
ramp breaks the test rather than the map.

Two lessons, and the second is the one worth keeping. The first is that a
colour chosen against a white page is not chosen until it has been put next to
everything else that is drawn. The second is that I had seen this myself, in
the z15 render made while settling the fill alphas, and set it aside as a
follow-up to raise rather than a fault to fix. It was in front of me and it
was this change's business.

**The water pass filled the contours.** Reported from the editor on N20E086,
a square that had never seen an import, with the surface at zero opacity: the
whole terrain drawn in water.

```python
painter.setPen(Qt.PenStyle.NoPen)
painter.setBrush(WATER_FILL)      # set before anything is known about there being any
for piece in self.water_fills.values(): ...
if not self.water:
    return                        # and left on the painter
```

The contour pass below sets a pen per level and no brush. It always relied on
`_paint_water` leaving `NoBrush` behind, which the version before this change
did - it returned before touching either when there was no water, and ended
with `setBrush(NoBrush)` when there was. The fill pass broke that silently: on
a square with no water it sets the brush, draws nothing, returns early, and
every closed contour is then filled with it.

Fixed at both ends, because the fault was the implicit dependency and not the
one line. `_paint_water` wraps itself in `save`/`restore`, so it cannot leak
whatever it does; and `paint` sets `NoBrush` before the contour loop, so that
pass says what it needs instead of inheriting it.

The lesson is not about brushes. The counter said `fills drawn 0`, which was
true - no fill was drawn, the brush did the filling - and I offered that
number to the mapper as evidence that nothing was filled, twice, without
opening the image it came from. A rendering fault is settled by looking at the
rendering. This file has said so since the pass-2 streaks, and the rule has
now caught me from the other side: there, a statistic hid a fault that was
obvious on sight; here, a counter did. The test that pins this reads a pixel
inside a contour ring, and the second one hands the pass a magenta brush and
requires it back.

## G5a, the merge rule

R40's split of ownership, in `danu/core/reconcile.py`: upstream owns where the
water is - refs, node positions, members, and the tags it is the authority for
(`natural`, `water`, `waterway`, `name`, now `overpass.UPSTREAM_OWNS`). The
mapper owns how high it is - `ele`, and any tag outside that set, since nothing
else would have put one on an imported feature. Upstream's `ele` fills in only
where the mapper has set none.

Identity is free. An import lands under the upstream OSM ids, so a second
import names exactly the ids the first wrote. On the gobras squares a first
import overlaps nothing they hold - no way, no node, no node a contour uses -
and a second overlaps everything.

Before this, a second import overwrote a held feature whole. It took itself
back exactly, which is what G4b set out to prove, and it threw away every
elevation set since the first import, which is the fault G5 exists for.

`ImportWater.upstream_owns` has no default. It is the line between the two
owners, and an import that did not say where it fell would be choosing
silently. The merge is worked out when the step is applied, against the square
as it stands; a redo after an undo works it out again against the square the
undo put back, which is the same square, so the same answer.

What the merge does beyond the features it names:

- **Vertices a re-route left behind** - named by the held way, not by
  upstream's - are removed when untagged and named by nothing else in the
  square. Tagged, they stay: a node with an `ele` is a spot height somebody
  placed.
- **A node a contour shares with a river moves with the river**, and the
  contour is reported in `moved` so it is redrawn. `ways()` and `spots()` keep
  answering after an undo, because the driver asks them then to know what moved
  back. None of the gobras data does this yet; G7's burn will.
- **Merged objects are new.** The undo holds the square's own, and one altered
  in place would come back altered.

Measured on N20E086, seventy per cent of the box's water: a first import 32 ms
for 3,199 ways, 78 relations and 96,251 nodes. Then forty river levels set, ten
lake levels, twenty-five vertices nudged by hand, and a second import: 89 ms,
40/40 and 10/10 levels kept, 25/25 vertices back where upstream has them, and
an undo of 11 ms that restores the square exactly. Nearly all of a second
import's vertices carry no tags on either side and are written as upstream's
own objects rather than new ones saying the same thing; that fast path is most
of why 96,251 comparisons cost under a tenth of a second.

Ten mutations of the rule were run against the seventeen tests and every one
failed at least one: overwriting whole, merging in place, removing nothing,
removing tagged vertices, ignoring a contour's hold on a vertex, not reporting
moved contours, letting local `name` win, writing the mapper's tags first,
forgetting what to redraw on undo, and letting upstream's `ele` win.

## G5b, gone from upstream

R40's other half: *a feature gone from upstream is reported rather than
deleted.* `danu/water/gone.py` compares what the set holds against the
answer and decides nothing; G5c gives the report a dock.

A held feature is gone when the answer does not name it **and the query would
have**. That second test is `overpass.asked_for`, the query's own selection
said a second time, and a test holds the two together by reading the
selectors out of `query()`. Without it every contour and coastline would be
reported missing on every import. Re-importing the unchanged gobras answer
reports nothing across 11,070 held features.

Absence then means deleted upstream, or retagged out of what the query asks
for (a river become a drain). The report says neither, because it cannot tell
which.

Three limits on what counts:

- **Positive ids only.** A negative id was allocated in the editor for
  something the mapper drew. It was never upstream, so it cannot have left.
- **A way a held lake relation names counts, tagged or not.** A ring carries
  no tags of its own. When upstream redraws it under a new id the relation
  comes back naming the new one, and the old way is left as an untagged line
  that nothing names. So the comparison runs *before* the import is applied,
  while the held relation still names it. Computed after, the case is
  invisible; the test that pins this was written after a first mutation that
  only emptied the report, which proved nothing about the order.
- **The whole answer, not the square's share of it.** Placement is per
  square and identity is not. A feature placed next door is not gone.

**An answer that says it is incomplete is refused.** Overpass sends what it
had, with an HTTP 200 and a `<remark>` saying *runtime error*. `parse`
ignored it, which was harmless to the merge and would not have been harmless
here: absence from a truncated answer reads as deletion. `IncompleteAnswer`
is an `OSError`, so it fails the import exactly as a network error does.

**A held feature goes back where it is held.** `place` took a feature's
square from its anchor, a way's first node. Upstream redrawing a river from
its other end moves the anchor across a degree line without the river moving
at all. The new copy would then land in the neighbour, without the elevation
set on the held one, while the held one stayed put: one id, two files, which
is the duplication R40 forbids. `held_by` snapshots which square holds each
id on the UI thread when the import starts, and the worker places against
that snapshot rather than walking dictionaries a mapper may be editing.

Measured on the gobras set after a real import: `held_by` and `gone` each
take 1.0 ms on the UI thread over 11,070 held features. Five rivers and a lake
deleted from the answer are reported as exactly those six, by name. Deleting
the lake realistically, so that its two untagged rings leave the answer with
it, reports the relation and both rings.

Eleven mutations, each failing at least one test: ignoring the remark,
refusing any remark, placing by anchor, an empty snapshot, counting any tag as
asked for, counting negative ids, losing the ring rule, deleting instead of
reporting, comparing after the import was applied - and, against the selector
test once the local review had it read the whole union, a selector in another
syntax and one `asked_for` does not know.

## G5c, the dock

R40's report where a mapper can work through it. A list, not a status line,
which could only count, and not a dialog, which is dismissed and gone. The
features want looking at one at a time, and the list outlives the moment the
import finished. It is a tab beside the Surface panel, hidden until an import
finds something gone and raised when one does. Its toggle is under Edit,
beside Import water. Opening another set clears it, because the report names
squares of the set it was made against.

**Choosing a row selects the feature as the map would** and fits the view to
it. What follows is the editor's own: Shift+Delete removes it, Ctrl+Z puts it
back, and keeping a feature means doing nothing. A deleted row stays, struck
through, and comes back on an undo. A list that rearranged itself while the
mapper worked down it would lose their place.

**A lake's rings are listed under the lake** when the lake is gone too;
`Gone.of` says which relation names a ring. A ring whose lake is still
upstream - one upstream replaced under a new id - has nothing to sit under,
and stands on its own.

**A relation can be selected now**, and that was the real work. A lake is a
relation, not one of its rings, and deleting it has to mean the lake. Without
this a gone lake could be looked at but never removed, and would be reported
again on every import. `Selection.relation` is set only from the dock: a
click lands on a line, and which of the relations naming that line was meant
is not something a click says. Four readers of a selection needed to know
about it:

- `_after_history_move` clears it when an undo takes the relation, as it
  already did for a way.
- `delete_way` used to answer "that is a spot height".
- `delete_selected` used to reach `sel.way.id` and raise.
- The overlay used to draw nothing. It now haloes every held member way,
  without per-node marks, since nothing here edits a relation's vertices.

**`edits.delete_relation` is what deleting a lake means**: the relation, plus
the member ways that are nothing without it, as one step. An untagged ring
nothing else names goes with it; left behind, it would be exactly the junk
G5b reports on the next import. A tagged ring is a feature in its own right,
and a ring another relation names - a lake sharing a shore with a riverbank -
still has a use. Both stay. `DeleteRelation.ways()` names the members,
because they were drawn as water only because the relation said so, and the
layer has to look at them again.

The pixel test for the relation halo first said the lake was not drawn. The
image showed it plainly drawn: the halo is orange at alpha 140, which over
the map's grey comes out (246, 183, 106), and the test's guess had excluded a
blue of 106. The threshold is now from that measurement, and the test still
fails with the halo removed.

Walked through on the gobras set with the window: a first import, then an
answer with a named lake (and so its two untagged rings) and two named rivers
deleted upstream. The dock opened with the lake, its two rings nested, and
the two rivers. Choosing the lake fitted the view to it, haloed - the Pool of
the Nation, a reflecting pool with an island, still drawn with its hole.
Shift+Delete gave `deleted "Pool of the Nation" and its 2 rings` and struck
all three rows. Ctrl+Z put all three back. The second import took 355 ms on
the UI thread across the set, the merge and the layer's refresh together:
once per import, a pause rather than a stall.

Eleven mutations, each failing at least one test: deleting the relation
without its rings, taking a tagged ring, taking a shared ring, not naming the
members for redraw, Delete reaching `sel.way.id`, a selection outliving its
relation, no strike-through, a flat list, not raising the dock, a report kept
across sets, and choosing a row without bringing it into view.

## G6a, select water and set a level by hand

R24 by hand. Until this the editor could import water but not give it a
level, so G5a's protection of a mapper's levels had nothing to protect.

**What a click on water selects.** Selection takes **the nearer of a contour
and a water way**. A river runs down the valley a contour bends round, so
contour-first would leave it unselectable at every zoom that shows both. A
test puts a contour three pixels from a river and clicks each.

- A **lake's ring** selects the lake: the relation, when exactly one water
  relation names that ring. The level belongs to the relation, and the ring
  is untagged.
- A **vertex of a waterway** selects that point, because a river's level
  lives there (decision 1 of G6): a river descends, and one number on the
  way could not say so.
- **Shift** selects the whole line, as it does for a contour.

Water has its own `pick_water`, kept out of the segment arrays that `pick`
shares with the crossing checks. In those arrays, every contour drawn across
a river would have been a refused crossing. Measured on the gobras set: 0.7 ms
a click over 4,270 water ways.

**Setting a level** is **L**, or *Edit > Set the level of the water*, and
uses the active elevation:

- a lake's goes on its relation (`SetRelationTags`, new);
- a pond drawn as one closed way takes it on the way;
- a river takes it at the selected vertex (`SetNodeTags`).

A river selected whole is asked for a point. A river area (a `riverbank`, or
`natural=water` + `water=river`) is refused: R27 says flowing water is never
held flat, and one level is exactly that. Flattening the Bosco River's area
at one level once put the whole of it at its mouth's height. What flows is
`overpass.FLOWING`, moved there from `water/constraints.py` (which imports
GDAL) so that the editor and the batch grader share one list.

**Upstream owns the shape, the mapper owns the height.**

- A river's vertex is never dragged: G5a puts it back on the next import, so
  a drag would be an edit that does not last.
- For the same reason, **Delete on a river's point removes its level, not the
  point**. The first version read the level for its message after the step
  had replaced the tags, and raised; the test caught it.

**Drawn.**

- A river's level is a **hollow diamond in the water's colour**, with its
  value above and to the right. A spot height is a filled ring in the ramp's
  colour, so a river graded at three hundred vertices reads as a river with
  levels on it, not as three hundred hilltops.
- The value first sat level with the mark, as a spot height's does. At z16
  that showed its white halo eating the diamond's right half, and the text
  sitting on the river line. Now it sits up and right, drawn before the mark.
- A **lake's level is written on the lake**, centred, from `ZOOM_SPOTS` - the zoom spot
  heights appear at.
- `Spot.on_water` keeps a river's levels out of spot-height picking.
- `_water_refs` counts water vertices so the layer can tell the two apart.
  It is built in `__init__`, not only `set_working_set`, after the
  `self.water` lesson of #90.

The pixel tests were written from the rendering, not from the pen colour.
Twice the guessed colour found nothing on an image that plainly showed the
mark. A 1.6 px antialiased diamond never reaches its pen's colour, and comes
out the same blue as the river through it. So the river test reads **shape**:
ink two and three rows off the line's own row, which the line never reaches.
A companion test reads the same rows at a point with no level and finds
nothing.

**A latent fault found on the way.** The layer drew `ws.present()` only.
"Present" means *has a file*, and an import can fill a square that has none
(#87), so a rebuild dropped water imported there from the canvas while the
square still held it. Nothing in the app rebuilds before such a square is
saved today, but a test that did is what found it. The layer now walks every
square; an empty absent one costs nothing.

**G5a, in the editor at last.** Set a river level and a lake level by click
and **L**, re-import the same answer, and both survive.

Fourteen mutations, each failing at least one test: contour-first picking, no
water picking, a ring not taken for its lake, no vertex selection, one level
on a river, a river area held flat, Delete removing the point, dragging
water, a river level taken for a spot height, no mark drawn, no lake label,
a relation retag naming no ways to redraw, water in the crossing arrays, and
walking only present squares.

## The selection panel

Out of the first session spent using phase 5: there was nowhere to see what was
selected, and no way to change a contour's elevation once drawn. G2's notes had
already said *"an action that re-tags whatever is selected would serve both and
belongs with the rest of phase 6's polish"*. It came before G6b instead,
because selection had just become complete, with G5c and G6a covering every
kind there is. G6b's grade and G7's burn both want somewhere to show what they
propose.

A dock under the Elevation panel says what the selection is: a contour, a point
on one, a spot height, a point on a river, a river, a river area, a lake, or a
lake ring two lakes share. It shows the name, the elevation, where it is, and
its other tags. **Only `ele` is editable.** Danu is not a general OSM editor,
and on imported water upstream owns `name` and the rest (G5a).

**The selection announces itself now.** It was an attribute set all through
the controller, and nothing heard about a change. It is a property that emits
`selectionChanged` on every assignment, so every one of those places says so
without remembering to. It fires on every assignment rather than on a change,
because telling a change means comparing Selections, and a Selection's
dataclass equality compares its Square, which is every node and way in it.

**`EditController.set_ele(value)`** is the one edit, for every kind, with the
rules L follows:

- A **contour** is re-levelled - the edit there was no way to make before. A
  node of one is the contour.
- A **spot height**'s value changes without deleting it.
- Neither can be **cleared**: a way with no elevation is not a contour, and
  Delete is how a spot height goes.
- A **lake** takes one level, and can be cleared.
- A **river** takes levels at points, and a point's can be cleared.
- A **river area** is refused (R27).

L still sets only water, as its menu says. The panel is what re-levels a
contour.

The field commits on Enter. An unchanged value is not a step on the history,
and anything that isn't a number is refused with the field put back. Escape
also puts it back. Either way the keys go back to the map, because the tools
are keys and a mapper who typed a level should not then find Q typed into the
field. **Why** a field is disabled is written under it in grey, not hidden
in a tooltip, which is found only by someone already hovering over the thing
they were told they could not use.

Seen, not only tested, on the gobras set:

- **A river area got a river line's advice.** It said "select one of its
  points", which a closed area never lets a click do. It says R27 now, in the
  panel and in L's message.
- **"Levels at 0" read oddly.** It says "levels at 0 of 419 points" now.
- **"Drawn here" was wrong.** The squares are JOSM files never uploaded, so a
  contour drawn there years ago carries a negative id as surely as one drawn
  in Danu this morning. The panel says "(local)".

The panel's tests type into the field as a mapper does. The first version of
the helper cleared nothing - selecting text is not deleting it - and two tests
of clearing failed on the helper, not the panel.

Twelve mutations, each failing at least one test: the selection not
announcing itself, the panel not following an undo, a contour clearable, a
spot height clearable, a river area editable, a river whole editable, the
keys not handed back, an unchanged value made a step, Escape keeping the typed
text, bad text accepted, the reason hidden, and a river area given a line's
advice.

## G6b, grade from the contours

R24's other half: a level *from the contours it touches*. **G**, or the panel's
button, works one out for the selected water and **proposes** it. The panel
shows what it found and a profile, the map shows where, and Enter accepts it
as one step or Escape drops it. Any edit or change of selection drops it too,
since it was worked out against the square as it was.

**A river** is graded between the contours it crosses, by distance along it.
`profile.grade_along` is the batch grader's `grade` over distance, not cell
index, and on evenly spaced points the two agree over two hundred random
profiles drawn downstream and two hundred drawn upstream, the batch grader
handed the latter downstream. The crossings are vector ones, `ContourLayer.crossings_of`:

- **against every contour in the working set**, because a river near a
  degree line crosses the contours its neighbour holds;
- **and nodes it shares with a contour**, which `geometry.crossings` counts
  as a touch, though a contour snapped to a river is the clearest crossing
  there is.

Two kinds of span are left ungraded, never forced down, and the summary tells
them apart: one where the contours **climb**, which is the data disagreeing
with itself, and one **running over 5 km without a contour**, which is ground
nobody contoured. On the gobras set, the Bass River climbs from 200 m to 350 m
and back down as drawn. The Prado River's lowland run has descending crossings
too far apart. The first version reported both kinds as "climb".

**Downstream is found, not assumed.** A way's direction means nothing
elsewhere in Danu, and mappers draw rivers either way round. Water descends,
so the end at the higher crossing is upstream. The way is never reversed;
only levels are written. Rocky River and Wine River grade though drawn
upstream, and the summary says so.

Levels go on the vertices (G6 decision 1), **to the decimetre**: the build
rasterises to the metre, so a millimetre is precision nobody measured, and a
whole metre would turn a slow river into a staircase. A grade is one
`SetNodeLevels`, not a `Compound` of `SetNodeTags`, because each of those
scans every way in the square for its one node and a grade names hundreds.

**A lake** takes the lower of two candidates:

- its **outlet**: the lowest graded river level inside it or on its shore;
- its **rim**: the lowest contour its shore crosses, which is where it would
  spill, and so a ceiling.

The batch grader takes the outlet whenever there is one. That is right there,
because it grades every river at once, so the outflow is always graded and
always lowest. The editor grades one river at a time. On the gobras set, with
only Oleander Creek graded, Lake Therran's "outlet" came out at 25.2 m, 10 m
above the 15 m contour crossing its own shore: the creek flows *in*. Taking
the lower of the two keeps the batch's answer wherever it had a true outflow,
and says so when an inflow is higher than the rim. An outflow *starting* at a
shore has no level there, since a river grades only between crossings. The
outlet comes from a river mapped through the lake, the OSM convention, whose
vertices inside sit between the contours upstream and downstream.

**What the map shows.**

- **Ungraded spans in red.** They were drawn under the selection's orange
  halo, on the very river being graded, and could not be seen. They are drawn
  over it now.
- **Proposed levels as dark diamonds on a white halo.** Amber on orange
  vanished.
- **No selection vertex marks while a grade is open.** At z12 those marks,
  the same size as a proposed level, made the Prado River look graded at both
  ends when it was graded at one. It took a close-up of each end to see that
  the data was right and the picture wasn't.

**The profile** in the panel plots distance against elevation: crossings as
dots, proposed levels in amber, current levels in grey, ungraded spans shaded
red. A climb shows as a line going up, which a list of numbers hides.

**The pixel tests took three tries.** "Any reddish pixel" passed with the
proposal drawn under the halo. A threshold from the commonest colours missed
the core rows of the line. Measured down a column, the core is (189, 50, 44)
on top and (207, 87, 34) under, and green tells them apart. The test that the
selection's marks are hidden reads blue at a vertex in the climbing span: the
mark under the red is (212, 54, 24), and nothing else there falls below 49.

Sixteen mutations, each failing at least one test:

- **the grade itself:** interpolating by index, assuming drawn is downstream,
  forcing climbs down, no length limit, writing to the millimetre, one reason
  for every rejection;
- **the crossings:** the river's own square only, no shared-node crossings;
- **the lake:** the outlet over the rim (the batch rule, unmodified);
- **the proposal's life:** not dropped by a selection, not dropped by an
  edit, Escape clearing the selection with it, a grade as many steps;
- **the panel and map:** no grade button, the proposal drawn under the halo,
  the selection's marks shown under a proposal.

The local review counted those as sixteen against a "seventeen" written here,
and was right. And `ui (windows-latest)` failed the span test: it sampled a
fixed window east of the map's middle, and with Windows' wider docks the map
was narrow enough that most of it fell off the image - 42 red pixels where
Linux has 300. The test finds the span from its own vertices now and asks what
share of its columns is red over the halo; it passes at map widths of 387, 87
and 68 px, and still fails with the order reversed.

**A river area mapped as a relation was proposed one level.** The GitHub
review noticed that the grade button showed for any selected relation.
Following that up found the worse case: `grade()` sent every relation down
the lake path without asking whether it flows. So a river area drawn as a
multipolygon (`natural=water` + `water=river`) was proposed one flat level,
which is exactly what R27 forbids and how the Bosco River's area once got its
mouth's height. `set_ele` refused it; `grade` did not. Both refuse now, and
only water relations are offered a grade.

## G6d-1, chains

Mappers split a river wherever they stopped, or a tag changed, or a bridge went
over: on the gobras set 158 of 398 named rivers and streams are more than one
way, the Bosco River thirty-eight. Graded way by way, a piece with one crossing
gets nothing though the next has five. **G now grades the chain the selected
way belongs to** - JOSM's non-branching way sequence - and on the gobras set,
through the editor's own code, the 149 chains of three or more ways level
**7,478 points instead of 4,090**, 83% more. Wandrasoon Creek, nine ways: 428
of 539 points, 100 m to 15 m over 12.3 km, as one step.

`danu/core/chains.py`, with no Qt. A chain runs end to end through nodes where
exactly two waterway lines meet, both ending there, and stops where a third
meets it (a confluence - 241 on the set), where one passes through without
ending (a tributary drawn on to a river's side - 496, G6d-2's ground), where it
comes back on itself (12), and where it ends (1,099). Its pieces are walked in
one order, each against its drawing where it has to be, and never reversed;
the grade finds downstream itself (G6b). A chain runs into the next square by
an imported node's id, which is the same OSM node in every file that holds it
- so **a level on a junction is written into every copy**, the chain's squares
and any other that holds it, as one step across them.
A negative id belongs to one file and chains nothing next door.

**Gaps of up to 5 m between free ends are walked across, for the grade only.**
No node is added or moved; the gap's length is distance along the chain; and
each is reported, with where it is, as a mapping error to join upstream. On
the gobras set that is seven, all in two-way chains: six are two nodes on one
spot never merged - said as that, since "a 0 m gap" names nothing to fix - and
one is 2.5 m at the Petunia River. None crosses into a differently named
waterway, and that is refused anyway, as is a gap with two pieces in reach of
it, which is a branch the data does not say is one. The 5 m was chosen from a
measurement: end to end, 1 m catches six of the set's breaks and 5 m seven,
and nothing within 25 m joins two differently named streams. Most snapping
misses are not end to end at all but a tributary stopping short of a river's
side, which is a network join and G6d-2's.

**Seen on the gobras set:** Wandrasoon Creek's summary said 429 points and
wrote 428. Its way 30384414 passes through one of its own nodes twice, which
gives that node two distances and two levels; the first visit in walking order
is the one written, and points are counted as nodes now, not as places along
the chain.

**And a G6b fix that never landed.** G6b's review commit said the Proposal's
annotations matched their neighbours; on main they did not. A falsification
probe later in G6b restored `tools.py` from a copy saved before that edit,
silently reverting it. Done here - and mutations now take a fresh copy just
before each one and `cmp` it after restoring, rather than reusing one across
edits.

Fourteen mutations, each failing at least one test, every one from a fresh
copy: no gap crossing, any distance, crossing into another named stream,
crossing with two in reach, walking through a pass-through, walking through a
confluence, local ids treated as global, a junction written in one square
only, a gap not counted as distance, a shared node walked twice, one way only,
points counted as places, a gap not reported, and the chain not drawn. Three of
them survived the first tests - the gap's distance, the shared node and the
drawing - and have tests of their own now: the proposal's distances read
straight, and the chain's halo read from pixels on a piece that was not
clicked.

## G6d-2, networks

**Shift+G grades the river network the selected river or stream belongs to**,
as one proposal and one step; G still grades the chain. A network is every
waterway line connected to it - by a shared node, by a gap end to end, or by
an end that stops short of another line's side within 5 m. It is split into
stems, and each stem is graded as a chain is, in an order that lets a
tributary take the level its river has where they meet: a tributary with one
crossing of its own, which neither G nor G6d-1 could grade, is graded from
that crossing down to the river.

**Stems by name first, then by length.** At a confluence a stem carries on
into the one arm with its own name (`Network.stem_of`) - on the gobras set the
name settles 445 of the 632 confluences, and agrees with the longer arm at 340
of them. Where it does not, the stem stops, and stems are claimed named before
unnamed, the longest name first, then the longest way. **A stem is graded
after the stems its ends sit on**, at a shared node or beside a side; among
stems ready together, named first, then longer. The level a stem inherits is
exact at a shared node, and interpolated along the segment where a tributary
stops short. A level set by an earlier stem is not changed by a later one.
The network is named after its first named stem graded, not the line clicked.

**Tributaries that stop short of a river's side are joined for the grade
only** and reported with where they are, like G6d-1's gaps. On the gobras set
four of the 93 networks with contours to grade from walk a gap: four
tributaries short of a side, 0.7 to 5 m, and one gap end to end.

**On the gobras set**: 280 networks, 187 with too few crossings to grade -
said, and nothing proposed. Graded one network at a time, the rest level
22,404 points, against 19,186 graded one chain at a time - 17% more. One
point a chain levels the network does not: a lone 62.8 m on the Palaconsino
River, whose two-way chain mostly climbs; followed through its confluences by
name, the longer stem's grade leaves it out. The largest network - Prado
River, 423 ways, 211 stems - is proposed in 1.0 s.

**Two bugs the gobras set found.** A network asked for from its river did not
include a tributary that stops short of it - the join was only found from the
tributary's end, and one network was proposed three ways depending on the
line clicked. Gaps and sides are now links both ways. And segments were
looked up by the cell of their middle: a segment a kilometre long, beside a
tributary's end near one of its own ends, was not found.

`crossings_of` asked of every contour for each of a network's ways was 7.3 s
for the largest; the contour segments by grid cell and contour vertices by
node, built once per rebuild of the arrays, make it 0.48 s with the same
answers on all 422 ways. Free ends are found by cell too.

Eleven mutations, each failing at least one test, every one from a fresh copy:
no inheritance at a shared node, none at a side, dependency order ignored, no
name continuation, joins found one way only, a segment in one cell only, the
network named after the line clicked, no refusal, a side with two lines in
reach, a side for an end that already meets a line, and sides left out of the
network.

## G6d-3, what a grade found, on the map

A grade's findings were a sentence: "81 spans left ungraded - 69 where the
contours climb, 12 running over 5 km", and on the profile red bands that all
looked the same. **Each is now an item with its place** (`tools.Issue`): a
span left ungraded, told apart as a climb - the contours and the river
disagreeing, a fault in one or the other - or a span over 5 km with no
contour, which is only ground nobody contoured; and a gap walked across,
between two ways or a tributary short of its river's side.

- **The panel lists them** under the summary, gaps first since they are the
  mapping errors to fix, then climbs, then long spans, each with a swatch in
  its map colour. A click takes the map to it and outlines it in yellow. The
  summary keeps the counts; the coordinates moved into the list.
- **The profile shades a climb red and a long span grey.** Hover says which,
  with how far along; a click takes the map there. A span is found within
  3 px of its band - on the Bosco River's 86 km stem a climb of a hundred
  metres is a pixel wide.
- **On the map** the same two colours: red solid, grey dashed.
- **The map goes no nearer than z16** to show one. Fitted to the window, a
  climb of a few hundred metres went to z19 and a gap to z18, where the river
  round it, which is what says where it is, was off the screen. A zoom and
  not a margin, since the zoom a margin comes to depends on the window.

**River level labels are thinned below z16.** A river graded at every vertex
wrote its values over each other at z14 and z15. Now a value is written only
where no other is within 60 px; every diamond is still drawn, and from z16
every value. By cells of scene pixels, so the labels kept do not change as the
map pans. On the gobras set after grading the Prado River network, a view at
z14 draws 149 levels and labels 24, at z15 70 and 14, at z16 14 and 14.

Thirteen mutations, each failing at least one test, every one from a fresh
copy. Two survived the first tests - the z16 limit, and a network's spans in
the list - and have tests of their own now.

## G6c, the build reads the squares and nothing else

**The Overpass switch is gone from the build.** `danu-build-zone` turned
`--water-constraints` on unless `WATER_CONSTRAINTS=0`, and
`server/etc/danu.conf` set it to 0, so the server never fetched - but the
switch was there, a deployment away from every nightly build reaching the
network. The editor imports water into the squares now, and a level on it
reaches the build as a spot height with no build change (G6 decision 1). Gone:
the option, the environment variable, the conf entry, `build.water_constraints`
and `build_dem`'s `water` argument, and the golden lock's `water_constraints`,
which was false. A test reads the server scripts, the surface build and
`constraints.py` for Overpass, the network or the switch, as text, so it runs
without GDAL.

**`danu/water/constraints.py` stays, reading a file.** `fetch` is gone and
`--osm` is required. G7's measure is that the editor's burn writes the same
constraints as this does over the same input, cell for cell, so its burn is
kept to compare against. Run on the gobras graded zone's contour raster with
the raw Overpass answer as input it grades 892 waterways and adds 12,068 cells,
as before.

**A square of water alone no longer widens the grid.** The concern from G4 -
water written after the envelope is taken lands outside it - went with the
step. What a build of the gobras 3x3, every network graded and saved, showed
instead: the import creates five squares of water and nothing else, none of
which a grade levels (every graded point lies in a square with contours), and
three of them a degree west of the zone - so the grid ran 85..88 where the
ground is 86..88, 3601x3601 cells for 2401x2401 worth. Such a square is still
drawn (R42) and read; `has_elevation`, an `ele` anywhere, decides which squares
the grid is taken over. The envelopes are the same four, and the DEM over the
common area differs by at most 0.1 m, the fill near the raster's moved edge. A
working set of water alone has nothing to build, and says so. Once a level is
put on such a square's water it is elevated, and counts.

`LINE_KINDS` is one list, in `core.chains`, which `overpass` and
`constraints.py` and the selection panel take; `core` does not import from
`water`, so it lives on the lower side. `danu/checks/rivers.py` still fetches
from Overpass - a check run by hand, not part of the build, and not touched.

Four mutations, each failing a test, every one from a fresh copy: the grid
over every drawn square, `has_elevation` answering for water, a working set of
water alone built, and the switch put back into `danu-build-zone`.

## `danu/water/constraints.py` goes

G6c kept it, reading a file, for one purpose: G7's measure that the editor's
burn writes the same constraints as it does, cell for cell. The spec now has
G7 burn and flatten through the contours in the editor, with the build reading
no water (#102), so that comparison has nothing to compare and the module
nothing to do. `profile.grade`, the per-cell grader it alone called, goes with
it. Its two properties - a graded run never ascends, and a climb rejected
leaves the levels stepping up across the gap rather than forced down - are now
tested on `grade_along`, the grader the editor uses, drawn either way round.
Both fail when `grade_along` is let grade a climb. The agreement test between
the two graders goes, its reference with it; `densify` and the segment lengths
keep their tests, in `test_profile_geometry.py`.

## G7a, flatten

**F flattens the selected lake at its level**, proposed like a grade and
accepted as one step across every square it touches. Four edits, in
`danu/water/flatten.py`, with no Qt:

- the level on its outline as `ele` - a closed way's own, a relation's member
  ways, an island's ring among them. A member another relation names is
  refused, and one that is flowing water's bank says so (R27);
- contours in the water deleted, the islands' kept;
- contours crossing the shore clipped, and drawn back from it by a distance
  the proposal sets - 100 m by default, tried before it is accepted - unless
  at the lake's own level, which stay touching it;
- fill lines across the water at its level, every 120 m, tagged `danu:fill`.

**The fill lines are an interim measure, and the measurement that made them
one.** The design said a closed contour at the lake's level with nothing
inside fills flat. It does not. Lake Kinser flattened that way came out 125 to
150 m with 8% of it at its level, median 132. The shore was in the
constraints; isofill declines a cell that sees one level in every direction -
which is how a hilltop looks, a closed contour with nothing inside - and its
second pass filled the lake from the 150 to 200 m islands. Holding it flat from
the squares needs something inside it. Spot heights on a grid needed 2,586
nodes at 120 m for 96% at 3 arcseconds. Straight lines, as AlvedC's mapper
had drawn across its big lake a kilometre apart, need far fewer:

| Lines at 125 m, 120 m apart unless said | nodes | at 125 m, 3" | at 125 m, 1" |
|---|---|---|---|
| none | 0 | 8% | - |
| 1,000 m | 38 | 35% | - |
| 250 m | 144 | 95.1% | 97.1% |
| 120 m | 296 | 98.8% | **99.7%** |

At 250 m the hillshade showed smears off the islands' tips; at 120 m none, and
no striping. Through the editor, the flatten of Lake Kinser - 105 contours
removed, 21 drawn back, 148 fill lines - built at 1 arcsecond puts 41,734 cells
of lake at 125 m to 99.7%. An isofill change that holds a marked one-level
enclosure flat, for plateaus as much as lakes, is the real fix; then every way
tagged `danu:fill` is deleted in one pass.

**Water with a level is still water in the editor.** Any way with a usable
`ele` was a contour, which a flattened lake's outline now has. A lake's
outline - a closed `natural=water` way, or a ring of a water relation - stays
water: drawn, filled and picked as the lake, left out of the contour arrays and
the ladder. A waterway *line* with an `ele` is a contour as before: Los
Pizarrales has eight `ldata:survey=thalweg` river pieces pinning a valley floor,
and the first version of this rule took them away from the golden ladder. Fill
lines are drawn dashed over the water and are in nothing a click or a grade
reads. Lake Kinser showed why the rule is needed: one of its rings is also
tagged `natural=wood`, and with a level on it the editor drew and picked it as
a 125 m contour.

**A flattened lake's level stays one level.** Setting it by L, the panel or G
carries the new level to its outline and fill lines in the same step;
clearing it takes the outline's `ele` and the fill lines. Its contours were
clipped against the old level, and the message says F again redoes them.

`ReplaceWay` is the new edit: a way replaced by pieces through its own nodes
and new ones, orphans kept for the undo - G7b's bends will use it too. The
shore tests went to numpy after the first version took 4.9 s on Lake Kinser's
3,000 shore edges; 0.85 s now, the same answers.

Not yet: reporting a flattened lake whose outline a re-import changes, which
the spec asks for - a follow-up.

Fourteen mutations, each failing a test, every one from a fresh copy.

## G7a-bis, a re-import that reshapes a flattened lake

A flattened lake's fill lines and clipped contours are laid against its shore
as it was. Upstream owns the shore (G5a), and a re-import that moves it leaves
them laid against a shore that is no longer there. So, as the spec asks, the
lake is reported for flattening again.

Before the import is applied, every flattened lake's outline is taken as it
stands - a lake with fill lines, or a relation whose rings carry a level, so a
lake too narrow for a fill line still counts. After it, the same lakes are
compared. An outline is its rings' coordinates, each ring from its lowest point
and the shorter way round, so the same shore redrawn from another node or the
other way about is no change - a property test walks random rings from every
start, both ways. A lake whose shore no longer closes in the square is reported
as that; a lake gone altogether is the gone report's. And a relation lake whose
ring upstream redrew under a new way, the same shore, is reported too: the new
way does not carry the level, so the build has lost the lake's shore contour
though nothing moved. Review asked whether a renumbered ring would be a false
report; it is not, the outline is coordinates - but it found this.

The report is a second group in the gone dock, *Flattened, and reshaped
upstream since*: the same kind of thing a mapper looks at after an import, so
the same list. Choosing a row selects the lake and says F flattens it again;
accepting that strikes the row through, as a deleted feature's row is, rather
than taking it away from under the mapper. On gobras, with Lake Kinser
flattened, finding the flattened lakes takes 3 ms and re-importing the same
answer reports nothing.

Seven mutations, each failing a test, every one from a fresh copy.

## G8a, the checks panel: contours that cross

Brought forward from phase 6, ahead of G7b's burn. Looking at the climbs the
grade lists before designing the burn, gobras showed contours that cross
dozens of others - and a river crossing one of those reads as a climb, which a
burn would then bend real contours to fit. R16 was enforced on what is drawn
and never asked of what the squares already hold.

**Gobras holds 6,714 crossings between 279 contours**, none at the same level.
Most come from a few dozen rogue ways in N20E086 and N20E087, of two kinds:
wanderers - a 425 m contour (way -63580402) down the east side of the massif
across 36 others from 300 to 500 m, 337 times - and edge-runners, 625 to 750 m
contours along the square's southern edge across the 25 to 100 m ones that
reach it, and a block in N20E087 crossing 13 to 16 contours each. Deleting the
425 m wanderer alone takes the count to 6,377 among 261 contours: 18 others
crossed nothing else.

The first count was 2,292, and wrong: done in degrees, the orientation test's
`EPS` was near the size of a 20 m segment's cross product, and missed most of
them. In metres the check agrees with a brute-force walk of the worst contour,
337 both ways. A crossing met twice - the same two segments in two cells, or a
crossing on a vertex, where both segments meeting at it cross - is one.

`danu/checks/crossings.py`, with no Qt: segments in 500 m cells, each cell's
pairs tested at once; a long segment goes in the cells along its line rather
than its box, which for a degree drawn diagonally was tens of thousands of
cells and turned a 2 s test into 54 s. A full scan of gobras is 1.3 s; the
`Index` keeps it as edited, an edit re-testing only the ways it touched against
the segments in their cells - 1.4 ms for a typical way, 42 ms for the 425 m
rogue's 613 segments, which tested against everything near it at once was
400 ms. Tested equal to a fresh full scan after every kind of edit.

**The panel**, *Checks*, in the Edit menu: one row per contour, the one crossing
the most others first, with what it crosses under it - a rogue is one row at
the top, not hundreds. A crossing does not say which of its two is wrong; one
that crosses thirty-six others usually does, and the fix is the mapper's.
Choosing a row selects the contour, rings its crossings and brings them into
view; while the panel is open the map marks every crossing.

**The index is built when the panel is first opened**, not with the working
set: 3.6 s on gobras. Built in the loader's thread it added 70 ms to every
window the UI tests open - the build competing for the interpreter with the
thread waiting for it - and the suite went from 85 s to 163 s.

Not in G8a, by decision: contours that touch at a node at different levels,
which R16 also forbids - gobras has 4,266 such nodes - and the rest of the
spec's checks.

Thirteen mutations, each failing a test, every one from a fresh copy. Putting a
long segment in its box of cells instead is slower, not wrong, and no test
fails for it.

## G8b, moving a contour whole

The checks panel found the rogue contours; for many of them the fix is not
deleting one but putting it where it belongs - its shape right, its place not.
The editor could drag one node at a time and redraw a stretch, and nothing
moved a contour as a whole.

**Shift and a drag carries a contour.** Shift already meant the line rather
than a node of it; with a drag it carries the line. A dashed ghost follows the
cursor and nothing in the square changes until the drop, which is one step -
`edits.TranslateWay`, every node moved by the same offset in scene terms.

**R16 asked of the move, not the contour.** A node drag is refused if what
results crosses anything. A misplaced contour crosses its neighbours where it
is, and the first drag towards the right place need not land it. The first
version refused any move that made a crossing the contour did not already
have - and in use the 425 m rogue could go nowhere: threaded through 36
contours, 50 m south crossed four new ones, 50 m north three, 200 m east two.
The refusal named "the 425 m contour" - another 425 m rogue, way -63580714 -
which read as the contour crossing itself. So a contour that already crosses
others is in breach of R16 and moves freely, the mapper repairing it, told
how it went: "crosses 31 contours, was 36", "still crosses 2", "crosses nothing
now". A contour that crosses nothing may not be moved into a crossing - that is
good data - and the refusal names the other contour's level and way and rings
where. On gobras the rogue moved 50 m south now: 38 contours, was 36, and it
came away from the one node it shared. A drop that moves the rogue is about
1 s, most of it the edit redrawing a 614-node way.

**A node it shares is copied, not moved.** Moving a shared node drags the other
way with it - a contour snapped to a neighbour, or to the coastline. A
misplaced contour moved away from what it was snapped to comes away from it:
it takes a new node at the new place and the other way keeps the old one, and
the status says how many it left.

**The selected contour is the one carried.** On gobras the first try carried
a 575 m contour, not the 425 m rogue it was meant for: in a massif a press is
near several, and the nearest wins a plain pick. A contour chosen in the checks
panel is selected, and a shift-press that lands on it carries it, though
another runs nearer. Dropping the rogue's 613 segments - the crossing test
before and after, by the layer's segment grid - is 0.3 s.

Eleven mutations: ten fail a test, each from a fresh copy - among them the
first version's rule, which the test of a crossing contour moving into a new
crossing now fails. The eleventh, moving a ring's closing node twice, is
equivalent - both moves are to the same place.

## G7b, burn

**B burns the climb chosen in the grade's list or on its profile; Shift+B every
climb the grade found.** Proposed like any grade - the old line across the
river struck through, the new lines drawn, pieces dropped greyed, what could
not be burned listed with why - and accepted as one step. The setback is the
strength, tried before it is accepted.

**What a climb is, on cleaned gobras.** Of the 128 one-step climbs, 120 are a
contour crossing the river twice with lower ground between: 85 where it
crosses again just downstream, a bump of a contour a stream runs along or a
hill's flank it runs into and out of; 35 where the pair is a proper crossing
upstream and a wrong one downstream, a ridge's finger the river cuts the tip
from. Eight cross only once (spurs) and are not burned yet; five are climbs of
more than a step.

**The cut.** The contour is cut at its two crossings and each piece closed
along its own bank, set back from the river. The first design took the shorter
part of a closed contour and moved it across; the mapper's question - why not
split the closed way in two - was right: the strip across the river is ground
the mapper drew, and if the river runs through the hill the hill is now two.
So nothing is deleted that the setback leaves room for, and a piece with
nothing left once its vertices within the setback are taken off is dropped and
said.

**The spur.** Built that way, 87 of the 128 were refused: the cut line ran into
another contour. In 73 of them other contours cross the river between the pair
- nearly all higher, +25 to +100 m: the river is not nicking a contour's tip,
it runs over a whole spur, in through the 250 and the 275, 300, 325 and out
again. So every contour crossing the river between the pair is cut, each set
back one step further than the one below - the river's level plus one step at
the setback, plus two at twice it - and the river runs in a V-shaped notch
through the spur, its sides rising one contour every setback. 50 m a step is a
steep side, some 27 degrees; it is the proposal's to change. Contours above the
river's level that come nearer than their own setback without crossing it are
pushed straight back to it, and a spur's inner contour wholly inside the notch
is cut away with it.

**On gobras**, one Shift+B on every river and then a second: 139 climbs, 3,473 m
of climb, to 95 and 2,403 m, then 87 and 2,223 m - 36% less. The first pass
burned 39 and the count fell by 44, a spur's cut taking its neighbours' climbs
with it. A cut at Bass River, where the river ran over the 400 m hill's lower
flank, lowered 171 cells at 1 arcsecond by up to 75 m, the rest of the surface
untouched. What stops the rest is mostly the cut line running into a contour
above and a lower contour crossing inside the stretch - another climb, to be
burned first. Hands-on use is what will say whether it hits the spot.

**Along the way**: a contour that crosses the river at a vertex of either line
- a contour snapped to it shares a node - is a crossing, as the grade has it;
the burn missed every one at first. Which bank is which is judged against the
bank line, which runs from one crossing to the other in the contour's order -
judged against the river's own direction it closed each piece on the wrong
side whenever the contour was drawn the other way. A spur's contours are cut
one after another and their new nodes took each other's ids until the plan
kept one allocator a square. And F on a lake flattened with no pull-back at
all: the action's triggered signal passes checked=False, which `flatten` took
for 0 m - G7a's, found here, tested through the action now.

Thirteen mutations, each failing a test, every one from a fresh copy: which
bank judged against the river's direction, one setback for every contour of a
spur, only the climbing contour cut, a lower contour inside not waited for, no
push, a contour inside the notch a refusal, crossings at a vertex not counted,
an allocator a cut, no clash check, the farthest climb burned instead of the
nearest, the setback not re-proposing, F through its action, and what was not
burned left out of the list.

**After PR 108's review.** Four points held, and two small ones:

- **A second Shift+B found nothing.** Accepting a burn replaces the grade, and
  Shift+B took its climbs from the grade in front of it - the second pass,
  the way a spur's neighbours are reached, said to grade first. It grades
  again now: the same kind of grade as last time, of what is selected.
- **The strike-through on a ring was the wrong part.** It ran the arc between
  the crossings, which on a hill is half of it. It is the old line at each
  crossing, out to the first vertex kept on either side.
- **A push gave up on the whole contour** for one vertex on the river; it
  skips that one.
- **Contacts were counted node by node.** A contour snapped along the river
  for a stretch shares a run of its nodes, each a crossing, and a touch that
  turns back counted as one. A run is one contact now, and a crossing only if
  the contour goes over. The gobras refusals for a contour crossing four, six
  or twelve times inside a climb are not this - those weave across the river
  properly, and are still refused.
- The spec says the setback is per contour step; the mutations are listed.

Five more mutations, each failing a test, every one from a fresh copy: the
second Shift+B not grading again, a touch counted, a run counted node by node,
a push dropped for one vertex, and the strike-through not reaching out.

## G7b, a run burned whole

**At the Bosco River the burn refused all but one of six climbs.** The river
climbs from 75 m over a spur to 225 m and back down to 75 m in two
kilometres; the grade sees a climb per step, and the burn took each with its
own contour's other crossing, so the 100 m's cut line ran into the 125 m
still crossing inside it. The mapper's point: the unit is the run, not the
climb. A run goes from the crossing the river climbs from to the first
downstream back at or below that level; runs nest or keep apart, and each
climb goes with the largest holding it, so B on any of the six burns the
hill.

**Cutting a run pair by pair did not do it.** The 125 m weaves - over the river
and back four times, 20 to 90 m north of it between - and the 100 m's line,
50 m back the whole length of the run, crossed the part of the 125 m between
its pairs. The run is the river burned down to its level from one end to the
other, so every contour above that level is kept its setback from the whole
stretch: what lies nearer is clipped out, and the ends are joined along the
notch's rim on the high side. One rule then does the cut, every pair of a
weave, a contour that only comes near - `_push` went, the rim does it - and
the cut-away of one wholly inside. Which side is high is read from the contour's direction
where it crosses the river, rising across the first crossing; reading it
from the river below each stretch of rim failed on the Bosco's 100 m, which
touches the river at one node without crossing it.

**The rim** is the stretch's offset either side and a half circle round each
end. Inside a bend tighter than the setback the offset folds back on itself;
those points are nearer the river than the setback and are left out. A rim
that would cross the river where it comes back, or a contour it did not cross
before, refuses the run.

**On gobras**, one Shift+B on every river: 133 climbs and 3,390 m of climb, to
46 and 1,285 m - 62% less, against 36% from two passes before, and a second
pass now finds nothing more. Refused: 10 contours crossing only once in a run,
9 rivers never back down to the run's level, and 4 rims that would cross a
contour or the river. At the Bosco the river now runs in a gorge through the
spur, its tip left a hill of its own south of it; the plan takes 1.1 s there,
from 13.7 s, once proper and vertex crossings test only segments whose boxes
meet.

Fifteen mutations, each failing a test, every one from a fresh copy: each climb
its own run, a run ending only below its level, the high side flipped for a
contour crossing and for one only near, a ring losing its piece through its
start, the fold kept, a piece taken whole not said, an odd crossing count not
refused, a run never back down not said, no clash check, a rim over the river
not refused, one setback for every contour, rim joins the wrong way round, a
pair crossing before refused, and sampling too coarse. A change to Shift+B's
filter for contours shared between rivers was made and taken out: mutated, no
test noticed, because it compares each square's commands against what earlier
rivers used, never against its own.

## G8c, a contour crossing itself

**The checks panel's second check.** R16 asked of one contour: two of its
segments properly crossing, or the contour passing through one node twice.
On the gobras originals, 23 crossings in 7 contours and 61 pinches; after the
cleaning, none and 12, in 6 contours. The pinches are three shapes: a loop
through a node; a spike, out along a segment and back over it; and, where the
contour area meets N20E087's edge at lon 87.2617, contours running out along
the edge and back over the same nodes - a pinch at every node of the run.
One row a place under the crossings; choosing one selects the contour and
rings it, and the list follows edits as the crossings do.

**O cuts out the loop**, proposed with what goes struck through: the part of
the contour between the two visits, a node put where the strands cross. A
closed contour has two such parts and loses the shorter - which is why it is
proposed and not done. A run out and back goes whole with its outermost pinch;
cutting an inner one first leaves the outer to cut.

**The scan** is every contour's segments grouped by contour and 500 m cell,
the pairs of every group tested together: 1.1 s over gobras, from 3.6 s a cell
at a time, since nearly every group holds a few segments and a numpy call a
group was most of it. It runs when the panel opens, with the crossings; an
edit asks again of the ways it touched.

**Along the way**: the cut is handed the way and reads it again from the
square, since an edit replaces the object - a second cut on the same contour
was refused as a loop no longer there. And after a cut the selection is the
contour as it now stands, not the way it replaced.

Nine mutations, each failing a test, every one from a fresh copy: a ring's
closing node counted as a pinch, an open line's ends taken for neighbours, the
longer side of a ring cut, no node where the strands cross, a loop already
gone cut anyway, the way handed in used, the panel not following an edit, the
selection left on the old way, and an empty list shown.

## G8d, split and join

**P splits the contour selected at the node selected**, as JOSM's does. An
open contour becomes two, the first keeping the way's id; a closed one opens
there into one line, from the node round to it. The two new ends are unglued
- a node each, the old one going unless another way holds it - and drawn 5 m
back along their own lines, a third of a short segment at most, so they come
apart where a mapper can see and take hold of them: 34 px at z19.

**Ctrl and a drag of an end onto another contour's end joins them**, as
JOSM's merge does: one way, keeping the dragged contour's id, the other turned
to meet it. Onto the contour's own other end, it closes. Refused, the end put
back and the reason said: another level, a node in the middle of a contour, a
closed contour, an end in another square - squares meet at their edges - and
a joining segment that would cross a contour (R16). Dropped where no node is,
or without ctrl, it is a move as before. The node under the drop is found
passing over the one dragged, which is under the cursor itself.

**The surface's pinch moves from P to C.** A key already rebound in the INI
keeps its own.

**After the local review**: the joined way keeps both contours' tags, and a
join whose tags disagree on a key - beyond the level, said first - is refused,
naming it; and a closed contour through the node twice is not split there, as
an open one already was not.

Thirteen mutations, each failing a test, every one from a fresh copy: drawn back
past the next node, the ends not drawn apart, a ring opened at its first node
and not the one chosen, an end split, a join across levels, a join onto a
middle node, the other way not turned to meet, a join without ctrl, a join
across a contour, the dragged node taken for the target, the pinch still on P,
the other way's tags lost, and a ring split through a node it holds twice.
