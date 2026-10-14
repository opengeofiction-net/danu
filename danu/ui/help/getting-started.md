# Getting started

Danu draws the contours of an OpenGeofiction territory and shows the ground
they make, as the server will build it. Contours live in **squares**: one file
per degree of latitude and longitude, kept in a folder per zone.

## 1. Sign in to OGF

**File › Sign in to OGF…** opens your browser at opengeofiction.net. Signed
in, Danu can say whether the territory under your squares is yours. Importing
and opening squares work without it.

## 2. Import your zone

**File › Import…** lists the zones on the server and copies the chosen one's
squares to this machine - into the folder Preferences names under *where an
import goes*. Import again later to bring in what others have sent since: a
square that differs from the server's is overwritten only if you say so, and
the squares open with unsaved edits are kept.

## 3. Open a square

**File › Open square…**: choose the zone's folder and a square, such as
`N20E087`. Danu opens it with its neighbours - three by three by default - so
the ground can be seen across the square's edges. **File › Open recent** has
the last few.

## 4. Draw

- **A** draws a contour at the *active* elevation, shown in the Elevation
  panel. Click to place each node; **Enter** finishes the line, **Backspace**
  takes back the last node, **Escape** stops.
- **W** and **S** step the active elevation by the small step, **2** and
  **X** by the big one; **Space** picks up the elevation of the contour under
  the cursor.
- **Q** selects: click a contour or a node to move, delete or split it.
- **Z** places a spot height; **M** measures a line and the ground along it.

Every key can be changed in **File › Preferences…**; **Help › Keys** lists
them as they are set now.

## 5. See the ground

**Ctrl+R** (Surface › Rebuild surface) builds the surface the contours make,
by the same code as the nightly build. After that, each edit is rebuilt around
itself as you draw. The Surface panel
chooses how it is shown; **Help › Layers** says what each part of the map is.

Look for *unknown ground*, which the contours do not describe, and for the
checks panel's findings - crossings, loops, contours touching.

## 6. Save, and send your squares in

**Ctrl+S** saves every square you have changed back to its file. Edits are
also autosaved as you work, and offered back if Danu is closed before they
are saved.

How to send finished squares to OpenGeofiction is on the wiki page,
**Help › Danu on the OGF wiki**.
