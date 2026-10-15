# Danu in the Microsoft Store

What Partner Center asks for, to paste from, and how a release gets there.
The app is reserved as **Danu**. Its identity, from Product management ›
Product identity, is the default in `build-msix.ps1`:

| | |
|---|---|
| Package/Identity/Name | `OpenGeofiction.Danu` |
| Package/Identity/Publisher | `CN=8B656AD9-4FD8-43AC-8CE7-DAC62DE06D6C` |
| Package/Properties/PublisherDisplayName | `OpenGeofiction` |

## A release, submitted

1. Tag `vX.Y.Z`. The release workflow builds `danu-X.Y.Z-windows.msix`,
   installs a test-signed copy on a clean runner, builds the golden square
   with it and starts it. Take the unsigned `.msix` from the run's `msix`
   artifact. It isn't on the GitHub release, because unsigned it installs
   nowhere else.
2. In Partner Center, open Danu, then Submissions › Update (or Start your
   submission for the first one), then Packages. Upload the `.msix`. The
   Store signs it after certification.
3. On the first submission, and whenever this file changes, fill in the
   sections below.
4. Submit. Certification takes up to a few days. Every release after the
   first is certified the same way, and the Store then updates the
   installs.

The version must rise with each submission. MSIX versions have four parts,
and the fourth is the Store's, always `.0`.

## Properties

- **Category:** Navigation & maps
- **Privacy policy URL:** https://github.com/opengeofiction-net/danu/blob/main/PRIVACY.md
- **Website:** https://github.com/opengeofiction-net/danu
- **Support contact:** https://github.com/opengeofiction-net/danu/issues
- **System requirements:** Windows 10 version 1809 or later, x64.
- **Product declarations:** none apply. Danu has no in-app purchases, no
  advertising, and no access to the camera, microphone or location.

## Age ratings

Fill in the IARC questionnaire as a utility or productivity app: no violence,
no sexual content, no gambling, no purchases. Users don't interact with each
other in the app, and it shares no location. It reaches the internet: map
tiles, sign-in, and release checks against fixed servers.

## Pricing and availability

Free, in all markets.

## Restricted capability: runFullTrust

Partner Center asks why the package declares it. Paste:

> Danu is a desktop map editor built with Python and Qt, packaged as a
> full-trust desktop application. It needs full trust to read and write the
> map files (.osm) in folders the user chooses, to run its bundled elevation
> builder (isofill.exe) as a child process, and to listen on 127.0.0.1 for
> the OAuth sign-in redirect and for the JOSM map editor on the same machine.
> It does nothing else outside the package.

## Store listing (English)

**Product name:** Danu

**Description:**

> Danu is the contour editor for OpenGeofiction, the collaborative map of
> invented countries. Draw the contour lines of your territory, and Danu
> builds the elevation surface under them as you work: the hillshade, the
> slopes and the height of any point, the same surface OpenGeofiction's own
> servers build from what you send in.
>
> Sign in with your OpenGeofiction account, import your zone's contour
> squares, and draw: a stroke snaps onto the nodes it meets, crossings and
> loops are found as you go, and every edit is autosaved. Water,
> coastlines and peaks come from the live map; the elevation can be shown in
> JOSM as a layer beside your other work.
>
> Danu is free software under the GNU General Public Licence, version 3 or
> later, made by OpenGeofiction's volunteers.

**What's new in this version:** the release's notes from its GitHub release.

**Product features** (one per line):

> Draw and edit contour lines, spot heights and coastlines
> See the elevation surface, hillshade and slopes as you draw
> Checks for crossing, looping and touching contours
> Sign in with your OpenGeofiction account and import your zone
> Autosave, and recovery after a crash
> Show the elevation in JOSM as a WMS layer
> Every key can be changed

**Keywords:** OpenGeofiction, contours, elevation, map editor, cartography,
hillshade, JOSM

**Copyright and trademark info:** © OpenGeofiction contributors. GPL-3.0-or-later.

**Screenshots:** at least one, and up to ten, PNG at 1366×768 or larger, of
Danu on Windows. Suggested: a square drawn with the surface under it; the
checks panel with its findings; the start page.

**Store logos:** none needed. The package's own tiles from `packaging/icon`
are used.
