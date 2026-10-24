# Layers

What is on the map, from the bottom up.

## The map underneath

The tiles of the main OpenGeofiction map, chosen with the layers button at
the top left of the map:

- **OGF Carto** - the standard map.
- **Topo** - the topographic style.
- **CyclOGF** - the cycling map.

## The squares

An outline round each square of the working set, the centre one heavier,
in the colours of the wiki's map of the topo layer: **green** for a square
with contours, **orange** for one holding only a coastline, **grey** for a
blank one. A square that has no file yet is hatched: the grid is always the
whole grid, so a gap shows as a gap. Names are written in the squares while
there is room.

## Zones

**View › Zones** opens the Zones panel, and while it is open the map draws
the zones squares are uploaded to, with their names, as the wiki's map does:
**blue**, and an inactive zone - built, but not on the tile servers -
**grey**. The panel lists them, and the map is a way in: outside the open
squares - or anywhere, with nothing open - **click** a zone to choose it,
and **double-click** a square to open it, its zone imported first if it is
not on this machine yet. **Import** imports the zone chosen.

**Ctrl and a double-click** on a square opens it: one of the open set's, and
the set moves onto it; one in a zone, imported first if need be. **Alt and
an arrow** moves the set a square west, east, north or south. Unsaved edits
go with the set. With the draw tool, Ctrl and a double-click stay the line's:
Ctrl snaps it, a double-click ends it. Each zone's
squares are drawn as the wiki's map draws them: **green** with contours,
**orange** a coastline only, **grey** blank. An
administrator edits them there: **New zone…**, and **Edit squares**, which
makes a click or a drag add squares to the zone and ctrl and a drag take
them away, until **Save** - squares another zone holds show red, and are
not taken; **Inactive…** and **Active** set whether it is
drawn on the tile servers. **Split…** makes some of a zone's squares a new
zone: name it, paint the squares that go, and Save - their files go with
them. A change that would leave a square with contours in no zone is
refused, the squares named; blank and coastline-only squares it leaves out
are taken out of the build, kept on the server for an administrator.

## The surface

The ground the contours make, once it has been built (**Ctrl+R**). The Surface
panel's **Show** chooses how:

- **shaded relief** - colour by height, shaded by the slope.
- **hillshade** - the shading alone.
- **relief** - colour by height alone.
- **slope** - steepness.
- **difference** - against the surface the server last published: red where
  yours is higher, blue where it is lower, clear where it has not moved. What
  has your editing actually changed?

**Ramp** is the colours by height, and **Scaling** what range they are spread
over: the whole set's land, the land on screen, a range you give, or pinched
about one height to tell close levels apart. The legend at the edge of the map
shows the ramp; drag it to pinch. **Opacity** lets the map show through, as
does **Alt** with the mouse wheel.

## Over the surface

- **Contours** - **Dark** lines read at any zoom; **Height colour** draws each
  line in its level's colour from the ramp.
- **Unknown ground** - where the contours say nothing and the build found no
  answer: ground a contour is missing from.
- **Single-level ground** - within the unknown, the cells that see one level
  only, mostly beside contours. It shows only while unknown ground does.
- **Envelope** - the outline of the ground the contours describe; the surface
  is not filled beyond it.

View has the same switches, and a toggle for each panel.

## Whose ground

Signed in, a square you share with a neighbour shows their ground: **amber**
within 10 km of yours, **red** beyond it. You may upload the whole square, and
are asked to keep to your own ground, reaching 10 km into theirs at most.
Your own ground and the sea are left clear. An administrator sees it as
anyone does. **Whose ground** in the Surface panel, or in View, turns it off.

The status bar says which zone the open square is in and whether it is yours
to upload. A square in no zone can't be uploaded: its line has a link to
message **admin** on OpenGeofiction to set one up.
