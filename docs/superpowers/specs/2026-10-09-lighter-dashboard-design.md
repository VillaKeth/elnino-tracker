# A lighter dashboard

Written 9 October 2026, continuing the user's request: "make sure that this
model loads as optimally and works as well as possible." The street-and-speed
round made the El Niño Map, the Storm Desk and the atlas load in about a
second after a publish; the dashboard is still the slow page. Self-approved
under the user's standing rule to work without check-ins.

## What the dashboard weighs today

Built offline from the run of 9 October 2026, 19:08Z: 882 KB gzip (4.66 MB
as written), about 20,000 SVG elements. On a throttled phone (1.6 Mbps,
150 ms, CPU 4x) it loads in 7.4 s on a first visit and 5.8 s after an hourly
publish, and its last byte arrives at 6.4 s of a 7.5 s load: the cost is the
bytes.

| part | gzip |
|---|---|
| coastlines on five maps, every vertex written out in full | 275 KB |
| the global map's two pictures, one in each theme's colours | 149 KB |
| the globe's first view, 7,870 polygons | 107 KB |
| the globe's copy of the field for its redraws, a character a cell | 80 KB |
| hover blocks on eight field charts, 8,292 rectangles | 87 KB |
| everything else | 184 KB |

The global map's pictures, the globe's polygons and the globe's characters
are three copies of one field, the day's quarter-degree SST anomaly.

## 1. Coastlines as relative paths

A coastline is written as each vertex's step from the one before
(`M x y l dx dy dx dy ...`), at the same tenth of a plot unit as now, a step
that rounds to nothing left out. The drawing is the same; the flat maps lose
about 101 KB.

Not chosen: a coarser level of the vendored coastline for the world-wide
maps. Level 0 is continents only: on the global map it drops 448 islands a
unit or more across, the Galápagos among them.

## 2. The globe drawn as paths

The globe's cells are one path a colour class, each run of cells a closed
quad within it, and its coastline and graticule one path each, by the server
for the first view and by the script for every redraw alike. About 32 KB
less, 8,400 fewer elements, and a drag redraws a dozen elements where it
made thousands.

## 3. One picture for both themes

A field drawn as a picture is drawn once, in grey levels that are its class
indices (index i of n at grey `round((i + 0.5) * 255 / n)`), and each theme
colours it through an SVG filter: a `feComponentTransfer` whose discrete
tables are that theme's palette, chosen by the theme the way the ramp's
custom properties are. The filters are defined once in the page. Checked in
Chrome 154, in Firefox and in WebKit (Playwright's builds) at one and two
device pixels a unit, and three in WebKit, square and smoothed: every class
comes out its palette colour to within a level, but for about one pixel in a
thousand in Chrome and WebKit, where Chrome's GPU raster meets a class edge or
an overlay, or WebKit places an edge a device pixel off (see Measured after).
The global map loses 75 KB.

Not chosen: pictures as files beside the page. Gzip takes base64 back to
within one per cent of the PNG's own bytes, so a file saves nothing on a
first visit; it would only help a visit after a publish on the same day of
data, which is a later round.

## 4. The globe reads the global map's picture

The globe and the global map are one field with one ramp, the same eleven
classes from the same robust span. The globe's script reads the classes from
the global map's picture instead of carrying its own characters: it inflates
the picture's lines with the browser's `DecompressionStream` and takes each
pixel's palette index as its class (exact in Chrome, Firefox and WebKit). No
canvas is asked for the pixels, as the first build did, so a browser guarding
against fingerprinting cannot change them. The globe loses 80 KB.

- A field too small to be drawn as a picture still ships its characters.
- Until the picture is read, a gesture waits for it; it is read before the
  reader can reach the globe in practice. A click made before then lands where
  the globe was drawn.
- If the picture cannot be read (missing, not one the server writes, or a
  browser without `DecompressionStream`), the globe stays as the server drew
  it and says so: its turning controls are set aside, it does not spin, and a
  click still names the regions.

## 5. One hover grid a field chart

A field chart's hover blocks become one element whose data are the blocks'
edges, the labels of their rows and columns and the range each covers. The
page's tooltip finds the block under the pointer. Same blocks, same words;
about 53 KB and 8,284 elements less.

## Expected

About 540 KB gzip and 2.4 MB as written, 16,700 fewer elements. On the phone
that is about 1.7 s off each visit. Measured the way round one was, with the
numbers put in the README and here.

## Measured after

Built offline from one run of 9 October 2026, before (297583b) and after, and
measured in one session the way round one was: the phone's line (1.6 Mbps,
150 ms, CPU 4x), the median of five visits each made after a publish, the page
served at gzip level 6 as the figures above were. GitHub Pages sends level 5.

| | before | after |
|---|---|---|
| the page as written | 4.79 MB | 1.81 MB |
| gzip level 6 | 883 KB | 517 KB |
| gzip level 5, as GitHub Pages sends it | 894 KB | 529 KB |
| gzip level 9, as the README's figures are | 870 KB | 511 KB |
| elements in the page | 29,100 | 12,461 |
| hover elements | 9,331 | 1,047 |
| phone, after a publish | 5.05 s | 3.18 s |
| phone, after a publish, no worker | 6.61 s | 4.63 s |
| phone, first visit | 6.6 to 6.8 s | 4.6 to 4.7 s |
| on the line, no worker | 1,184 KB | 823 KB |
| desktop, after a publish | 0.56 to 0.59 s | 0.41 to 0.46 s |

About 1.9 s off each visit after a publish, 2.0 s without the worker, where
1.7 s was expected; 16,639 fewer elements where 16,700 were. The page before
measured 5.8 s after a publish in round one: a session's figures move by most
of a second, so before and after were measured side by side. A revisit before
the next publish blocks the page 17 to 49 ms in all, where it blocked it 146
to 147 ms.

The globe's read of the picture (section 4) was found here to hold a phone's
processor 60 to 100 ms on end as the page loaded, drawn as an image and walked
in one go: the total blocking time after a publish went from 0 to some 90 ms.
Decoded as a bitmap away from the page's own work and walked eight
milliseconds at a time, it blocked nothing, and the total blocking time after
a publish was 0, as it was. Inflated from the picture's own bytes since the
review, the read takes 14 to 50 ms of the phone's processor where the canvas
took 41 to 103, measured side by side.

The review's fixes, the globe's read inflating the picture and a path's
numbers run closer, are in the sizes above; the times were measured on the
build before them, and side by side with it in one session they changed none:
after a publish 3.26 s against 3.22 with the worker and 4.85 against 4.86
without, the page 7 KB lighter at level 6 and the script 1 KB heavier.

Colours: on the built page every pixel of a square picture comes out within a
level of its class's colour in Firefox; in Chrome fewer than one pixel in a
thousand differ by more, up to 11 levels, at class edges and under overlays,
where its GPU raster blends them. In WebKit 26.6 (Playwright's build of
Safari's engine), at one, two and three device pixels a unit, at most 0.11 per
cent of a square picture's pixels differ by more than 6 levels from the build
that drew two coloured pictures, all of them along class and coast edges it
places a device pixel off; the smoothed global map changes 10.5 to 11.3 per
cent of its pixels, as in Chrome. There the globe's read is exact too, the
globe is left still with `DecompressionStream` taken away, and the field
charts' tooltips say what they say in Chrome and Firefox.

## Testing

- Each change red first, then green; the whole suite in its batches.
- The script's paths and hover read back in node against what the server
  drew, the globe's redraw within a tenth of a unit of the server's first
  view.
- In headless Chrome, Playwright's Firefox and its WebKit, on the built page:
  each theme's colours on the pictures, the globe spun and clicked, and left
  still with `DecompressionStream` taken away, the tooltips of the field
  charts.

## Out of scope

- The globe's first view drawn by the script (97 KB more, but the globe would
  be uncoloured until the script ran).
- Pictures and the field as cached files for a revisit on the same day.
- The ensemble members' curves as relative paths (about 10 KB).
