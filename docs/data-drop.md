# Data drop

## Context

Mappers send finished squares in by email and an administrator puts them in `osm-squares/<zone>/` on util.ogf by hand. This issue (#190) replaces that with an authenticated data drop: a mapper signed in to OGF uploads a square from Danu, and it lands where the nightly build reads it.

Note: Not the API database. Contours are never uploaded to the OGF API database, as ways or as changesets. The squares stay files, and this is a place to put the files.

Goes with locking. Once uploads are authenticated, the server knows who may edit which square, and "who may edit this square" stops being a social question. Two people with a claim on one square are kept from overwriting each other by a based-on check, not by a lock.

## What exists already

- Danu signs in to OGF with OAuth 2 and PKCE (`danu/ui/oauth.py`), with the `read_prefs` scope. `user/details` gives the display name and the roles.
- The squares are published read-only at `data.opengeofiction.net/dem/osm-squares/<zone>/`, and Danu's File › Import reads them from there (`danu/core/mirror.py`, with a manifest of each file's SHA-256). JOSM users and the multimap's Download links use the same copy.
- There are two copies on util. The nightly build (`danu-build.timer`, 03:00 UTC) reads the working copy, `elevation/osm-squares/`. Once the build is done, its source-squares step copies every file that is newer into `sync-to-ogf/dem/osm-squares/`, keeping timestamps and replacing each file in one step, and removes files and zones that have gone. `sync-to-ogf@.path` then pushes that copy to `data.opengeofiction.net`, so the published copy can be up to a day behind.
- The nightly build rebuilds a zone when its squares change. A square that arrives is picked up the next night.
- The elevation process - danu-server - runs on `util.ogf`, which is not publicly accessible.
- A zone today is only a directory: 32 of them, 1 to 103 squares each, no square in two.
- Territories: attributes from the wiki's `OpenGeofiction:Territory_administration` (`action=raw`), geometry from `data.opengeofiction.net/utility/territory_1.json` - the least simplified - joined on the relation id (`danu/core/territory.py`).

## The API

The Danu editor needs to be able to:

1. Manage zones, for admins
   1. Create a zone
   1. Change a zone's extent
   1. Inactivate a zone
1. List a zone's squares, and read a square
1. Determine whether the user may edit a square, and in which zone it is
1. Upload a square, where permission exists
1. Delete a square, where permission exists

Reading needs no sign-in. Every other call carries the user's OGF token. The server asks OGF's `user/details` who it is, and caches the answer for a short time. `read_prefs` is enough: Danu doesn't need to sign in again.

### Zones

- A zone has a lowercase name as its ID, which may name a territory within it, a continental reference or some other classification.
- A zone's extent is one or more rectangles of whole degree squares. Zones never overlap, so a square is in at most one zone. That zone is where an upload of the square goes, including one of a square that doesn't exist yet.
- The zones are a text config on `util.ogf`, which the API's admin calls also write. The 32 zones of today are seeded from the squares they hold.
- Inactivating a zone is the existing `inactive` file in danu-server's base directory: the zone is still built, published, edited and uploaded to, and it stays off the tile servers. The admin call adds or removes the zone's entry, with one of that file's reasons and a note, and leaves the other entries and their comments as they are.

### Squares and their names

- A square is its degree cell, e.g. `N20E086`, and a zone holds at most one file for a cell. Most squares also have a name, which grounds them quicker than the grid does: `N20E086_Gobras_City.osm.xz`. On 2026-10-18, 557 of the 807 squares had one.
- A name is letters, digits, `_` and `-`, up to 64 characters. Danu shows `_` as a space. No `.`: a square's file name ends at its first one, so trent's `S01W145_lon-145.00_-144.00lat-1.00_0.00_local-source.osm.xz` isn't read as a square today, and is renamed before the drop goes live.
- A square can be renamed, and its name removed, by anyone who may upload it. A rename can come with an upload or on its own. Either way the file is replaced under its new name in one step, behind the same `If-Match`, and the rename is logged.
- Each zone's `EMPTY.osm.xz` isn't a square. The API ignores it.

### Reading, and the two copies

- The working copy is the one truth, and a square's version is the SHA-256 of its bytes.
- The API lists a zone's squares (cell, name, size, hash) and serves the files, from the working copy, with no sign-in, as Import works today. Danu's Import reads them from the API, so an import after a refusal always fetches what the server holds now.
- Each upload, rename and deletion also updates the published copy at once, and `sync-to-ogf@.path` pushes it out. Downloads from `data.opengeofiction.net` are then current within minutes, not a day.
- The nightly copy step stays as it is. It carries an admin's hand edits on util to the published copy. Such an edit changes the hash, so the next upload of that square is refused and imported again, as it should be.
- Every write - to either copy - is a temporary file renamed into place, so a build running during an upload reads each square whole. A square that changes after the build has listed its zone is built the next night.

### Upload

- The unit is the `.osm.xz` file as a whole.
- An upload names the version it was edited from: the hash of the square as it was read, sent as `If-Match`. If the square has changed since, the upload is refused (`412`), and Danu offers to import the square again. The first upload of a new square says there is none (`If-None-Match: *`).
- The server refuses a file that isn't a readable `.osm.xz`, whose name isn't a degree square, or that is over 64 MB - the largest square on 2026-10-18 was 24 MB, liberian's N03E058. The contour checks - crossings and the rest - stay in the editor.
- Each upload and deletion is logged: who, when, which square, its hash. The file it replaced is kept on util for an admin to recover by hand, outside `osm-squares/`: the build looks for squares in a zone's subdirectories too. None of that is exposed through the API.

### Excluded

The API will not support:

* Versioning, rollbacks - the unit is the `.osm.xz` file as a complete whole

### Network architecture

The API runs alongside danu-server on `util.ogf`: a small WSGI service from `python3-danu`, run by a systemd unit. It's reached from outside at `data.opengeofiction.net`, where nginx fronts it as an HTTPS endpoint and proxies to util over the OGF WireGuard VPN.

## Permissions model

- Admins - users with the OGF `administrator` role - may edit every square, and manage the zones.
- A user's territories are those which list them as the owner, or one of the `;` separated owners, or in a `dem:` entry of the territory's `constraints`, `;` separated too - e.g. `"dem:Alice;Bob"`. Names are trimmed of spaces either side. A territory's status is not considered: the territory administration process removes owners when a territory is withdrawn.
- Owners and delegates are matched on the OGF display name. Renames on OGF are made only by an admin, who changes the wiki with them.
- For a square, the user has:
  - `yes`: all the territory in the square is the user's. Ground outside every territory (i.e. sea) doesn't count against it.
  - `partial`: some of the territory in the square is the user's, and some is another's.
  - `no`: none of it is the user's.
- `yes` and `partial` may upload. Only `yes` and admins may delete.
- Where permission is "partial" the user can edit anywhere within the square but has a social contract to focus within their own territory, with latitude to map up to 10 km within the neighbouring one. The server doesn't look at where the changes are.

## Danu editor

The editor needs to:

- Allow users to edit outside of the zones, but make it plain that such a square can't be uploaded. They should contact an admin, via OGF message, to set up a zone
- Query the API for the square's zone and permission
- Show where in the square the user may edit, from the territory polygons: their own territory (may edit), a 10 km buffer around it (permissive) and outwith (should not edit)
- Show a square's name beside its cell, and let it be set, changed or removed
- Import from the API, by cell, so a square renamed on the server replaces the local copy under its old name
- Upload via the API. On a refusal because the square changed, keep the mapper's version beside it as `<square>.mine.osm.xz`, import the server's, and open it with the `.mine` copy as a reference layer, so they can redo their changes where the other mapper didn't draw. The `.mine` copy is never listed as a square, opened as one, or uploaded. Mappers sharing a square coordinate between themselves; admins don't settle it for them
- After an upload, record the uploaded hash in the mirror's manifest as the server's. Safe because Import reads the working copy, which can never be older than what was uploaded
- Delete a square, after a confirmation
- For admins, a map to view and edit the zones: draw and change their rectangles of squares, refused where they would overlap, create and inactivate zones

## Implementation

Six PRs. N1 and N2 first; N4 and N5 can be built against N2 run locally while N3 waits for the servers; N6 last, the text config on util serving until then:

- **N1, permissions:** pure, in `danu.core`. The zones config: read, write, the overlap check, and the seed from `osm-squares`. The owner and `dem:` parsing, and `yes`/`partial`/`no` for a square from the territory geometry. Tests.
- **N2, the service:** the WSGI app - token check, permission, the zone listing and reads from the working copy, upload with `If-Match`, rename, delete, each written to the published copy too, the zone admin calls, the log and the kept files. The systemd unit in the `.deb`. Tests against a fake OGF.
- **N3, deployment:** util and the `data.opengeofiction.net` nginx, the zones seeded, the runbook in docs-internal. Done with the user, on the servers.
- **N4, the editor sees:** the square's zone and permission, the territory shading with the 10 km buffer, and the not-in-a-zone notice with its link to message an admin.
- **N5, the editor sends:** Import from the API, upload, rename and delete, the manifest after an upload, the refusal with its `.mine` copy and reference layer, and Help and Help:Danu changed from email to upload.
- **N6, the zone map:** for admins, the zones drawn on the map and edited there.

Then a release.
