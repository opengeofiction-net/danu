# Getting started

Danu draws the contours of an OpenGeofiction territory and shows the ground
they make, as the server will build it. Contours live in **squares**: one file
per degree of latitude and longitude, kept in a folder per zone.

## 1. Sign in to OGF

**File › Sign in to OGF…** opens your browser at opengeofiction.net. Signed
in, Danu can say whether the territory under your squares is yours. Importing
and opening squares work without it.

## 2. Import your zone

**View › Zones** shows the zones on the map: double-click a square of yours
to import its zone and open it. Or:

**File › Import…** lists the zones on the server and copies the chosen one's
squares to this machine - into the folder Preferences names under *where an
import goes*. Import again later to bring in what others have sent since: a
square that differs from the server's is overwritten only if you say so, and
the squares open with unsaved edits are kept. A square renamed on the server
comes in under its new name.

## 3. Open a square

**File › Open square…**: choose the zone's folder and a square, such as
`N20E087`. Danu opens it with its neighbours - three by three by default - so
the ground can be seen across the square's edges. **File › Open recent** has
the last few.

Ground nobody has drawn yet starts with **File › New blank square…**, or
**New…** on the start page: the square offered is the one in the middle of
the map, and it goes into its zone's folder, where Import puts the zone - or,
if the server has the square already, the zone is imported and the square
opened. A square in no zone asks for a folder. **Help › Start page** brings the start
page back over whatever is open.

## 4. Draw

- **A** draws a contour at the *active* elevation, shown in the Elevation
  panel. Click to place each node; **Enter** finishes the line, **Backspace**
  takes back the last node, **Escape** stops.
- **W** and **S** step the active elevation by the small step, **2** and
  **X** by the big one; **Space** picks up the elevation of the contour under
  the cursor.
- **Q** selects: click a contour or a node to move, delete or split it.
- **Z** places a spot height; **M** measures a line and the ground along it.

### Changing a contour

- **Redraw a stretch:** at the contour's elevation, start a line on one of
  its nodes, draw the new course, and finish it with **Enter** or a right
  click near another of its nodes. The stretch between the two is replaced.
  A redraw has to come back to the contour it began on; **Escape** drops it.
- **Continue a contour** by starting a line on its end. A line ended on the
  end of a contour at its level joins it - one way, as long as that stays
  within the 2,000 nodes the main map takes in a way.
- **Move a node** by dragging it; drag it onto another node with **Ctrl**
  held to join the two. A node of a contour that crossed nothing is not put
  down crossing another; one of a contour that already crosses moves, so a
  crossing can be mended a node at a time.
- **Move a whole contour** by dragging it with **Shift** held.
- **Insert a node** with a double click on a line.
- Where lines and nodes lie together, **click again** in the same place for
  the next of them.
- **Pick many nodes** by dragging round them on empty ground with **Q**:
  a lasso, or with **Alt** a rectangle. **Shift** adds to what is picked,
  **Ctrl** takes away, and **Delete** deletes them - on contours, water and
  spot heights alike, though a river's points stay: they come from the main
  map. The right button moves the map.
- **Pick by level** with **Pick** in the Selected panel: *At the active
  elevation* picks only the nodes of contours at the level shown in the
  Elevation panel - lasso a hillside for its 150 m, press **W** for the next
  level and **Shift**-lasso to add it - and *From - to* those in a range,
  spot heights by their own level and a flattened lake at its level. Rivers
  have no one level and are left out.
  The status bar says when a filter is on.
- **Move what is picked** by dragging one of its nodes; with **Shift** and
  **Ctrl** held the drag turns it about its middle, and with **Ctrl** and
  **Alt** it scales it there. The keys can be pressed or let go during the
  drag, which carries on as what they now say - a move, then a turn, then a
  scale, in one drag, as in JOSM - and the pointer shows which. Contours that
  crossed nothing are not put down crossing another; ones that already
  crossed move, and the status bar says how the crossings changed.

Every key can be changed in **File › Preferences…**; **Help › Keys** lists
them as they are set now.

## 5. See the ground

**Ctrl+R** (Surface › Rebuild surface) builds the surface the contours make,
by the same code as the nightly build. After that, each edit is rebuilt around
itself as you draw. On a large square that can make drawing stutter: turn
**Surface › Rebuild automatically** off - or **auto** beside the Surface
panel's Rebuild surface - and the surface waits for **Ctrl+R**.
The Surface panel
chooses how it is shown; **Help › Layers** says what each part of the map is.

Look for *unknown ground*, which the contours do not describe, and for the
checks panel's findings - crossings, loops, contours touching.

## 6. Save, and send your squares in

**Ctrl+S** saves every square you have changed back to its file. Edits are
also autosaved as you work, and offered back if Danu is closed before they
are saved.

**File › Upload square…** sends the open square to OpenGeofiction, where
it is built into the elevation the night after. The status bar says first
whether it is yours to upload: a square of your territory, or one you share
with a neighbour - keep to your ground there, and within 10 km of it in
theirs. A square in no zone can't be uploaded yet; its status line links to
message admin to set one up, and an account blocked on OGF uploads nothing
while the block lasts. **File › Rename square…** changes its name on
the server and here, and **File › Delete square from server…** takes it off
the server, leaving your copy. **File › Revert square to the server's…**
throws your changes to the open square away - unsaved, and saved but not
uploaded - and takes the server's copy.

An upload is made from the version you last imported. If somebody else's
upload has gone in since, yours is refused: your version is kept beside the
square as `.mine.osm.xz` and drawn dashed over it, and theirs is imported in
its place. Redo your changes on theirs, upload again, and then
**File › Discard refused version…**. Mappers sharing a square sort this out
between themselves.

## If something goes wrong

If Danu meets an error it did not expect, it writes a report, saves your
edits to the autosave, and offers to open a GitHub issue filled in from the
report. Read the issue before you submit it, and take out anything you would
rather not share: nothing is sent until you submit it. If Danu stops without
warning, the report is offered the next time it starts.
