# Danu privacy policy

Danu is the OpenGeofiction contour editor, a desktop program made and run by
OpenGeofiction's volunteers. This policy says what Danu itself sends, to
whom, and what it keeps on your computer. Your OpenGeofiction account, and
everything kept on OpenGeofiction's servers, is covered by OpenGeofiction's
own [Privacy policy](https://wiki.opengeofiction.net/index.php/OpenGeofiction:Privacy_policy)
and [Terms of Use](https://wiki.opengeofiction.net/index.php/OpenGeofiction:Terms_of_Use).

Danu has no analytics, no advertising and no tracking. Nothing is sold or
given to anyone.

## What Danu sends, and to whom

Danu talks only to OpenGeofiction's own servers, and to GitHub, where Danu is
published. Each request carries your IP address, as any request on the
internet does. Each also tells the server it comes from Danu and which
version, as `Danu/1.3.1 (+https://github.com/opengeofiction-net/danu)` for this one.

- **Signing in** (optional, File › Sign in to OGF). Your browser opens
  opengeofiction.net, where you sign in. OpenGeofiction gives Danu a token
  that can only read who you are. Danu never sees your password. Danu uses
  the token to ask for your user name, so it can tell which territories
  are yours, and sends it to OpenGeofiction's data drop on
  data.opengeofiction.net, which asks opengeofiction.net who it belongs to.
  Signing out forgets the token and asks OpenGeofiction to revoke it.
- **The map.** Danu fetches map tiles from tile.opengeofiction.net and
  tiles06.opengeofiction.net for the area on screen.
- **Territories.** Danu fetches the list of territories and their owners
  from data.opengeofiction.net and wiki.opengeofiction.net.
- **Water and coastlines.** Danu fetches the water, coastlines and peaks
  around the squares you open from overpass.opengeofiction.net.
- **Importing squares, and comparing elevation.** When you ask, Danu
  fetches contour squares and a zone's published elevation model from
  data.opengeofiction.net.
- **The data drop.** For the square you open, Danu asks
  data.opengeofiction.net which zone it is in and, signed in, whether it
  is yours to upload; it can also fetch the list of zones. When you ask -
  File › Upload, Rename or Delete square - Danu sends the square's file, or
  its new name, with your token. The server keeps a record of the change -
  your user name, the time, the square - and a copy of the file the change
  replaced, so an administrator can recover it. An uploaded square is
  published, and built into OpenGeofiction's elevation, as squares always
  have been.
- **Checking for a newer Danu.** At start, at most once a day, Danu asks
  GitHub (api.github.com) for the list of Danu's releases. Nothing about
  you or your work is sent. You can turn this off in File › Preferences ›
  General, and Danu installed from the Microsoft Store never asks.

The servers above can be changed in File › Preferences › Servers. Danu then
sends the same requests to the servers you name.

Danu also listens on your own computer (127.0.0.1) and accepts no
connections from anywhere else. It listens for the browser's return when
you sign in, and to serve the elevation to JOSM as a WMS layer. When you
ask, it talks to JOSM's remote control on your computer.

## What Danu keeps on your computer

All of this stays on your computer. Danu never sends any of it.

- **Settings**, including the sign-in token and your user name, in a file
  only your account can read.
- **The autosave**: edits you have not yet saved, so they can be recovered.
- **A usage log**: what you did in the editor, such as clicks, keys and
  tools, so that a bug can be reproduced. The last 20 runs are kept.
- **Crash reports**: if Danu fails, it writes down the versions it runs on,
  where it failed, and the last lines of the usage log. The last 20 are
  kept.
- **A cache** of map tiles and the data fetched above.

On Linux these are under `~/.config/danu`, `~/.local/share/danu` and
`~/.cache/danu`. On Windows they are under your `AppData` folder. On macOS
they are under `~/.config/danu`, and `danu` in your `Library`'s
`Preferences`, `Application Support` and `Caches`.
Uninstalling Danu from the Microsoft Store removes them. Otherwise you can
delete them yourself at any time.

## Reporting a problem

When Danu fails, it offers to open a GitHub issue filled in from its crash
report. This happens only if you choose it. The issue opens in your
browser, so you can read it and take anything out before you decide
whether to submit it. Once submitted, it is public on GitHub and covered by
[GitHub's privacy statement](https://docs.github.com/site-policy/privacy-policies/github-general-privacy-statement).

## Contact

Questions about this policy: info@opengeofiction.net, or an issue at
https://github.com/opengeofiction-net/danu/issues.

Changes to this policy are made in this file, and its history is the
record of them.
