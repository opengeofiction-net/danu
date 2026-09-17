#!/usr/bin/env python3
#
# A visual index of the elevation zones and their squares, for the wiki's
# MultiMaps - see Admin:Elevation process
#
#   demZonesToMultimap.py <base-dir> [-copyto <publish-dir>]
#
# Writes the three files MultiMaps wants, in the shape dailyActivitySummary.pl
# writes its own:
#
#   elevation-polygons.json   key -> a ring of [lat, lon]
#   elevation.json            key -> what to say about it, plus an InfoBox
#   elevation-template.json   class -> how to draw it and what to put in the popup
#
# Four classes, and the wiki page draws each as its own overlay that a reader can
# turn on and off, filtering on the class name. So the names here are an
# interface: renaming one silently empties an overlay rather than breaking
# anything visibly.
#
# A zone is active or inactive, because "published" and "rendered" are different
# questions here and the index is the only place a mapper can see which a zone
# is. A square is one of three: contours drawn, a coastline and nothing behind
# it, or blank. That middle one is the whole point of splitting them - a shore is
# tagged ele=0, so a square holding only a coastline has constraints and no
# terrain, and calling it drawn tells a mapper the ground is done when all of it
# is still to do.
#
# Whether a square holds contours is decided by reading it for an ele tag, the
# same test demZoneExtent.py uses to pick the squares a zone is built on. Taking
# it from the filename instead would be quicker and would eventually disagree
# with what was built, which is worse than slow: an index nobody can trust is
# not worth drawing.

import json
import lzma
import os
import re
import sys
import time

NAME = re.compile(r'([NS])(\d{2})([EW])(\d{3})')
ELE_TAG = re.compile(rb"""k=["']ele["']\s+v=["']([^"']*)["']""")

CLASS_ZONE_ACTIVE = 'zone'
CLASS_ZONE_INACTIVE = 'zone-inactive'
CLASS_SQUARE = 'square'
CLASS_SQUARE_COASTLINE = 'square-coastline'
CLASS_SQUARE_BLANK = 'square-blank'


def classify_square(path, chunk=1 << 20):
    """'contour', 'coastline' or 'blank'.

    Any ele tag at all is a constraint as far as building goes, which is the
    question demZoneExtent.py asks. It is the wrong question for an index: a
    coastline is drawn at ele=0, so a square holding nothing but a shore has
    constraints and no terrain, and reporting it as drawn tells a mapper the
    ground is done when the whole of it is still to do. zone-penquisset is
    fourteen such squares and zone-tempeira two.

    So the test is whether any elevation is non-zero. Non-numeric ones - ele=TBD
    on an unsurveyed lake, the odd ele=169s typo - are ignored, because the build
    drops them before rasterising and a square holding only those yields nothing.

    Returns at the first non-zero elevation, so a drawn square costs a page or
    two; a coastline-only one has to be read to the end to know that is all it
    is."""
    seen = False
    tail = b''
    try:
        with lzma.open(path, 'rb') as f:
            while True:
                block = f.read(chunk)
                if not block:
                    break
                buf = tail + block
                for m in ELE_TAG.finditer(buf):
                    try:
                        if float(m.group(1)) != 0.0:
                            return 'contour'
                        seen = True
                    except ValueError:
                        pass
                # long enough to hold a tag split across the boundary
                tail = buf[-64:]
    except (lzma.LZMAError, EOFError, OSError):
        return 'blank'
    return 'coastline' if seen else 'blank'


def read_inactive(path):
    """zone -> reason, from the file buildDemData.sh reads. Comments stripped,
    so a zone commented out is active, which is how one is put back."""
    out = {}
    try:
        with open(path) as f:
            for line in f:
                line = line.split('#', 1)[0].strip()
                if not line:
                    continue
                parts = line.split()
                out[parts[0]] = parts[1] if len(parts) > 1 else 'no reason given'
    except OSError:
        pass
    return out


def square_ring(lon, lat):
    return [[lat + 1, lon], [lat + 1, lon + 1], [lat, lon + 1], [lat, lon]]


def main():
    args = [a for a in sys.argv[1:]]
    publish = None
    if '-copyto' in args:
        i = args.index('-copyto')
        publish = args[i + 1] if i + 1 < len(args) else None
        del args[i:i + 2]
    if len(args) != 1:
        sys.exit('usage: demZonesToMultimap.py <base-dir> [-copyto <publish-dir>]')
    base = args[0]
    squares_dir = os.path.join(base, 'osm-squares')
    if not os.path.isdir(squares_dir):
        sys.exit(f'no {squares_dir}')

    inactive = read_inactive(os.path.join(base, 'inactive'))
    polygons, records = {}, []
    n_zones = n_drawn = n_shore = n_blank = 0

    for zone in sorted(os.listdir(squares_dir)):
        zdir = os.path.join(squares_dir, zone)
        if not os.path.isdir(zdir):
            continue
        drawn, shore, blank = [], [], []
        for name in sorted(os.listdir(zdir)):
            if not name.endswith('.osm.xz'):
                continue
            m = NAME.match(name)
            if not m:
                continue                       # EMPTY.osm.xz and anything else
            ns, la, ew, lo = m.groups()
            lon = int(lo) * (1 if ew == 'E' else -1)
            lat = int(la) * (1 if ns == 'N' else -1)
            # the part after the underscore is the territory the mapper named it
            # for, and is what they will recognise it by
            label = name[:-len('.osm.xz')]
            title = label.split('_', 1)[1].replace('_', ' ') if '_' in label else ''
            kind = classify_square(os.path.join(zdir, name))
            if kind == 'contour':
                drawn.append((lon, lat, label, title))
            elif kind == 'coastline':
                shore.append((lon, lat, label, title))
            else:
                blank.append((lon, lat, label, title))

        if not drawn and not shore and not blank:
            continue
        n_zones += 1
        n_drawn += len(drawn)
        n_shore += len(shore)
        n_blank += len(blank)

        # The zone as built is the box round the squares holding any constraint,
        # a lone coastline included - that is the question demZoneExtent.py asks
        # and this box has to agree with what was actually built
        extent = (drawn + shore) or blank
        west = min(s[0] for s in extent)
        east = max(s[0] for s in extent) + 1
        south = min(s[1] for s in extent)
        north = max(s[1] for s in extent) + 1

        reason = inactive.get(zone)
        polygons[f'zone:{zone}'] = [[north, west], [north, east],
                                    [south, east], [south, west]]
        records.append({
            'key': f'zone:{zone}',
            'class': CLASS_ZONE_INACTIVE if reason else CLASS_ZONE_ACTIVE,
            'zone': zone,
            'drawn': str(len(drawn)),
            'shore': str(len(shore)),
            'blank': str(len(blank)),
            'degrees': str((east - west) * (north - south)),
            'reason': reason or '',
        })

        for cls, group in ((CLASS_SQUARE, drawn),
                           (CLASS_SQUARE_COASTLINE, shore),
                           (CLASS_SQUARE_BLANK, blank)):
            for lon, lat, label, title in group:
                key = f'square:{zone}:{label}'
                polygons[key] = square_ring(lon, lat)
                records.append({
                    'key': key,
                    'class': cls,
                    'zone': zone,
                    'square': label,
                    'title': title,
                    'midpoint': f'{lat + 0.5}/{lon + 0.5}',
                })

    now = time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())
    records.append({
        'control': 'InfoBox',
        'text': (f'Elevation zones and contour squares - {n_zones} zones, '
                 f'{n_drawn} with contours, {n_shore} holding only a coastline, '
                 f'{n_blank} still blank. Written at {now}'),
        'started': now,
    })

    # Styling is the wiki's, not this script's. The MultiMaps page draws each
    # class as its own toggleable overlay and filters on the class name, so the
    # four names here are what its overlaydef refers to and cannot be renamed
    # without editing the page too. Everything else - weights, opacities - was
    # set on the published file by hand and is copied back here, because this
    # rewrites the file every run and would otherwise undo it each Wednesday.
    template = {
        CLASS_ZONE_ACTIVE: {
            'color': '#1f78b4', 'opacity': 1, 'weight': 5,
            'fillColor': '#1f78b4', 'fillOpacity': 0,
            'text': ['Elevation zone: <b>%zone%</b><br/>',
                     '%drawn% squares with contours, %shore% coastline only, %blank% blank<br/>',
                     'Extent: %degrees% square degrees<br/>',
                     'Rendered on the topo layer<br/>',
                     '<a href="https://data.opengeofiction.net/dem/%zone%/">Published data</a>'],
        },
        CLASS_ZONE_INACTIVE: {
            'color': '#999999', 'opacity': 1, 'weight': 5,
            'fillColor': '#999999', 'fillOpacity': 0.5,
            'text': ['Elevation zone: <b>%zone%</b><br/>',
                     '%drawn% squares with contours, %shore% coastline only, %blank% blank<br/>',
                     'Extent: %degrees% square degrees<br/>',
                     '<b>Not rendered</b>: %reason%<br/>',
                     'Published and downloadable either way<br/>',
                     '<a href="https://data.opengeofiction.net/dem/%zone%/">Published data</a>'],
        },
        CLASS_SQUARE: {
            'color': '#33a02c', 'opacity': 1, 'weight': 3,
            'fillColor': '#33a02c', 'fillOpacity': 0.10,
            'text': ['Square: <b>%square%</b><br/>',
                     '%title%<br/>',
                     'Zone: %zone%<br/>',
                     'Contours drawn<br/>',
                     '<a href="https://data.opengeofiction.net/dem/osm-squares/%zone%/%square%.osm.xz">Download</a>'],
        },
        CLASS_SQUARE_COASTLINE: {
            'color': '#ff7f00', 'opacity': 0.5, 'weight': 1,
            'fillColor': '#ff7f00', 'fillOpacity': 0.10,
            'text': ['Square: <b>%square%</b><br/>',
                     '%title%<br/>',
                     'Zone: %zone%<br/>',
                     '<b>Coastline only</b> - the shore is drawn, the ground behind it is not<br/>',
                     '<a href="https://data.opengeofiction.net/dem/osm-squares/%zone%/%square%.osm.xz">Download</a>'],
        },
        CLASS_SQUARE_BLANK: {
            'color': '#b2b2b2', 'opacity': 0.5, 'weight': 1,
            'fillColor': '#ffffff', 'fillOpacity': 0.5,
            'text': ['Square: <b>%square%</b><br/>',
                     'Zone: %zone%<br/>',
                     '<b>Blank</b> - a template, nothing drawn yet<br/>',
                     '<a href="https://data.opengeofiction.net/dem/osm-squares/%zone%/%square%.osm.xz">Download</a>'],
        },
        'x': {},
    }

    out = {
        'elevation-polygons.json': polygons,
        'elevation.json': records,
        'elevation-template.json': template,
    }
    for name, data in out.items():
        path = os.path.join(publish or '.', name)
        with open(path, 'w') as f:
            json.dump(data, f, indent=1)
        print(f'  {os.path.getsize(path):>9} bytes  {path}')
    print(f'  {n_zones} zones, {n_drawn} with contours, {n_shore} coastline '
          f'only, {n_blank} blank, {len(polygons)} polygons')


if __name__ == '__main__':
    main()
