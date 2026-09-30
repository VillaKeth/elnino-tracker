# Enter a place, before and after El Niño — design

Date: 2026-09-29. Branch: `round-15-then-and-now`, on top of `main` at 5c1720c.

## What was asked, and what it is taken to mean

The request, in the user's words: "how do i dive into the world and explore it
pre and post el nino" and "it should be like the google maps enter into
feature".

What exists: `map.html` and `storms.html` are one page (the storm desk's map
engine in `stormdesk.py`, El Niño's layers in `worldmap.py`). It zooms from
the planet to a street on Esri's maps, draws NASA's imagery, compares two
layers either side of a divider, and answers a tap with the "Here" panel,
which can load Google's own Street View of the point. Every layer shows one
time: today's map, the latest frame, or a day stepped back no more than 40
days. Nothing on the page can show a place as it was before an El Niño, or
say what ENSO was doing on the day an image was taken.

| Said | Taken as |
|---|---|
| the google maps enter into feature | Google Maps' Pegman: drag a figure onto any point of the map, or press it and tap a place, and the view drops into that place at street level; one control leaves again. Google's Street View of the point stays one press away. |
| dive into the world | the drop flies down to the place at the zoom its imagery is made for: buildings on the sub-metre archive, fields on 30 m, a region on 250 m, a basin on the ocean anomaly |
| explore it pre and post el nino | the same ground at two dates side by side, one either side of the divider, with any date the archives hold on either side; every date labelled with what ENSO was doing in the season around it (the tracker's own RONI record); one-step choices for "a year before the peak → the peak" and "the peak → a year after" of every El Niño the archives cover, and "a year ago → now" for this one |

Assumed, not said: the same expert reader as every round (meteorologist), on
the same devices (desktop and tablet); links to a view should be shareable,
as the user asked earlier for something people can "use and reference".

## Verified on 29 September 2026

Every feed below was requested from this machine on that day; each claim is
what came back.

| Feed | Answer |
|---|---|
| GIBS time ranges (`/1.0.0/{layer}/default/{tms}/all/1999-01-01--2026-09-29.xml`) | `MODIS_Terra_CorrectedReflectance_TrueColor` (Level9, JPEG) daily from 2000-02-24, 11 spans; `MODIS_Terra_L3_NDVI_16Day` (Level9, PNG) 16-day composites from 2000-03-05, one span a year starting 1 January; `GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies` (Level6, PNG) daily from 2002-09-01; `HLS_L30_...` daily from 2013-03-22, `HLS_S30_...` from 2015-11-28. |
| GIBS past tiles | 200 for MODIS true colour on 2015-12-15, MUR25 on 2015-12-15, NDVI on 2015-12-19 (a composite start). |
| GIBS colour maps | MUR25 anomalies use `GHRSST_Sea_Surface_Temperature_Anomalies.xml`, the map already keyed and read back on the page; the 16-day NDVI uses `MODIS_L3_NDVI.xml`: 143 entries, NDVI -0.3 to 1.0 in 0.005 steps, brown to dark green, water and fill transparent. |
| GIBS, not used | `MERRA2_Precipitation_Bias_Corrected_Monthly` lists 123 odd single-day times among its months; `Landsat_WELD_..._Global_Monthly` (30 m) holds 1984-03 to 1986-11, 1988-12 to 1991-11 and 1998-12 to 2001-11: neither 1982-83 nor 1997-98 at its peak; `GHRSST_L4_MUR_...` (1 km) starts 2019-07-23. |
| Esri World Imagery Wayback config (`s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json`) | 200, `Access-Control-Allow-Origin: *`, 196 releases from 2014-02-20 to 2026-08-05, each with its item id, tile template (`wayback.maptiles.arcgis.com/.../MapServer/tile/{release}/{level}/{row}/{col}`) and metadata service. |
| Wayback tiles | 301 to the release the tile last changed in, then 200 JPEG, both with `Access-Control-Allow-Origin: *`; **404 past coverage** (open Pacific at zoom 17), not Esri's grey placeholder. |
| Wayback tilemap (`.../World_Imagery/MapServer/tilemap/{release}/{z}/{y}/{x}`) | 200 JSON, CORS `*`: `{"data":[1],"select":[20512],...}` names the release the tile at that address last changed in. Walking back from the newest release, Manaus at zoom 16 changed in 22 releases, 22 requests. |
| Wayback metadata (`metadata.maptiles.arcgis.com/.../World_Imagery_Metadata_{year}_r{nn}/MapServer/{layer}/query`) | 200, CORS `*`; layers 0-13 run from 1.9 cm to 150 m. At Manaus: capture 2025-07-30 (Vantor WV03, 31 cm) in the 2026 releases, 2023-08-27 (Maxar WV03), 2023-06-29 (GE01), 2022-08-15 (WV02), 2021-10-31, 2020-07-22, 2018-08-09, 2017-07-11: the 22 changes are 8 captures. One query timed out at 60 s. |
| Wayback items (`www.arcgis.com/sharing/rest/content/items/{id}?f=json`) | 200; CORS answers `Origin: null` (a page opened from a file). Licence: "This work is licensed under the Esri Master License Agreement ... not intended to be used to export tiles for offline" - the terms the map's World Imagery already runs under. `accessInformation` is the release's credit ("Esri, Vantor, Earthstar Geographics, and the GIS User Community" for 2023-08-31). |

## Success criteria

1. A figure in the toolbar ("Enter") can be dragged onto any point of the map,
   or pressed and then a place tapped, or pressed and then Enter pressed for
   the middle of the view; "Enter here" in the Here panel does the same for
   the point shown. Esc or the bar's Exit leaves, restoring the layers the map
   had.
2. Entering flies to the point at the source's own zoom and shows the same
   source on both sides of the divider, the earlier date on the left, with a
   pin on the point and a chip either side of the divider giving each date.
3. Five sources, each with its archive's first date: the Esri archive (sub-
   metre where Esri has it, 2014 on), Landsat and Sentinel-2 (30 m, 2013 on),
   MODIS Terra true colour (250 m, daily, 2000 on), vegetation (MODIS NDVI,
   16-day, 2000 on) and the ocean temperature anomaly (GHRSST MUR25, daily,
   2002 on). A point on land opens on the Esri archive, at sea on the ocean.
4. Each side's date can be typed, stepped to the previous or next time the
   archive holds (the previous or next capture for Esri, a day with an image
   at the pin for Landsat and Sentinel-2), or set by tapping the RONI strip.
   A date outside an archive is brought to its nearest end, and the bar says so.
5. Every date shown carries the RONI season centred on its month, its value
   as CPC prints it and what it was: the tier and whether it belonged to an
   episode, conditions short of one, conditions still running, or neutral.
   A month after the last season says so and gives the last one.
6. The event menu offers "a year ago → the latest" for now and, for every
   El Niño episode with its peak since March 2000, "a year before the peak →
   the peak" and "the peak → a year after", with the months named. Both sides
   never land on the same capture when an older one exists.
7. On the Esri archive the versions are those whose imagery at the pin
   changed, found as Esri's own Wayback app finds them, each named by the
   date its imagery was taken and by whom; its credit is the release's own.
8. On the ocean and vegetation sources the value at the pin is read on each
   side from NASA's own colour map, with the change between them; the map's
   key shows the source's scale.
9. While comparing dates the map draws only the two dates, Esri's roads and
   names over them (a switch), the pin and town names: not the live storms,
   today's tiles or the composite, which would be read as belonging to the
   dates shown; the bar says they are hidden.
10. The pill, the status line and the credit speak of what is drawn: each
    side's source and time, an archive that did not answer (with Retry), an
    image hunted for and not found, tiles enlarged past their pixels.
11. `#then=lat,lon,zoom,source,left,right` opens the page entered there, and
    the bar's "Copy link" gives that address for the view.
12. Street View stays one press away from the bar: Google's own panorama in
    the Here panel, and a link that opens it in Google Maps, whose own "See
    more dates" holds any older panoramas.
13. The page works on a phone and a tablet: the figure drags by touch, the
    bar wraps, every control is at least 44 px and has a name, and dark mode
    colours come from the page's tokens.

## Out of scope, and why

- Choosing the date of Google's Street View: neither Google's embed nor its
  Maps URLs take a date. Google Maps' own "See more dates" is linked.
- 3-D or tilted views: the map is a flat Web Mercator map; tilting it would
  be a new engine.
- Rainfall by date: MERRA-2's monthly layer lists malformed times, and the
  map already draws the GPCP composites of what El Niños do to rain.
- 1982-83 and 1997-98 at their peaks: no archive GIBS or Esri serves holds
  them (WELD's monthly Landsat stops at 1991-11 and resumes at 1998-12).
- La Niña presets: asked for El Niño; every date is still reachable by hand.
- Offline use: every archive is fetched live; tiles already drawn stay.

## Architecture

A new module, `elnino/thennow.py`, holds everything about comparing dates:
its sources, the Python that turns the RONI record into season words and
event presets, the bar's markup, its CSS, and its script, spliced into the
desk's script at a `/*THENNOW*/` marker as `worldmap._JS` is at
`/*WORLDMAP*/`. `stormdesk.py` gains the Enter button, the map's chips and
hint, the bar's place in the page, and a few hooks in the engine, each one
line that asks `thenOn()`.

### Sources

| id | Name | Tiles | Times | Max zoom | Enters at |
|---|---|---|---|---|---|
| `archive` | Satellite archive (Esri) | Wayback tile template, per release | versions whose imagery at the pin changed | 19 | 16 |
| `hls` | Landsat and Sentinel-2, 30 m | the desk's two HLS layers, stacked | days with an image at the pin | 13 | 12 |
| `modis` | True colour, daily (MODIS Terra) | `MODIS_Terra_CorrectedReflectance_TrueColor`, Level9, JPEG | every day GIBS lists | 13 | 8 |
| `ndvi` | Vegetation (MODIS NDVI, 16-day) | `MODIS_Terra_L3_NDVI_16Day`, Level9, PNG | 16-day composites GIBS lists | 13 | 7 |
| `sst` | Ocean temperature anomaly (MUR25) | `GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies`, Level6, PNG | every day GIBS lists | 13 | 4 |

Each source carries its name, a sentence on what it is and its pixel size,
its first date, its credit, and for `ndvi` and `sst` the key and readout.

### Times

- **GIBS sources.** On first use a source's whole range is asked for once
  (`D.gibs.domains`, start its first date, end tomorrow) and kept as spans:
  start, end and step in days. `snapTime(spans, t)` is the valid time nearest
  `t`, earlier on a tie; `stepTime(spans, key, ±1)` the one before or after.
  Each 16-day span starts on its own 1 January, so steps never cross a year's
  seam wrongly.
- **Landsat and Sentinel-2.** A side's day is the day nearest the date asked
  with an image at the pin, looked for outwards up to 20 days either way with
  the desk's own `imageOn`; ◀ and ▶ look up to 60 days in their direction.
- **Esri archive.** The release list is fetched once. At the pin the tile at
  zoom 16 is walked back from the newest release by its tilemap: each
  `select` is a version, the walk resumes at the release just older than it,
  and stops where the tilemap has no tile. Each version's metadata query
  (layer `clamp(23 - 16, 0, 13)` = 7) names the capture date, the provider,
  the sensor and the resolution; versions sharing a capture date are one,
  kept as the newest release. A date asked for is the version captured
  nearest it (its release date until its capture date answers).
- **Two sides, two captures.** When both sides resolve to the same capture
  and an older one exists, the left steps back one, and the bar says why.

### Enter

Pressing the figure arms it: the map's cursor becomes a crosshair and a hint
says what to do; a tap enters there, Enter enters at the middle of the view,
Esc disarms. Dragging the figure (pointer moved more than 8 px while held)
carries a ghost of it with a ring on the map beneath; letting go over the map
enters there, anywhere else cancels. Entering saves the layer, compare state,
second layer and split; sets the pin; picks the source (land by the
composite's land-only temperature grid or a gazetteer place within 30 km);
applies the default preset; and flies to the point, the flight 600 to
2000 ms by how far the zoom travels. Exit restores what was saved and leaves
the view where it is, as Google leaves the map where Street View was left.
A tap while entered moves the pin, and the archive's versions and the
readouts follow it.

### The bar

Under the map, in the scrubber's place while entered: the source menu, the
event menu, Street View, Copy link, the names switch and Exit; then each
side's date with ◀ and ▶ (a date field, or for the archive a list of its
captures) and the season words beneath; then the RONI strip from January
2000 to the latest season, warm above and cool below zero in the page's
`--warm` and `--cool`, ±0.5 marked, a line for each side's date. Tapping the
strip moves the nearer side's line to that month. Beneath: the readout at the
pin for `ndvi` and `sst`, or each side's capture for the imagery sources.

### ENSO on every date

`thennow.payload(state)` sends, from DJF 2000 on, each season of the tracker's
official index keyed by its centre month (`"2015-12"` for NDJ 2015): its
label, the value as CPC prints it (`classify.displayed`) and its words from
`classify.intensity_tier` and `classify.find_episodes`:

- in an episode of five or more seasons: "very strong El Niño, the 2014-16 episode";
- in the run still going at the latest season: "moderate El Niño conditions, 3 seasons so far";
- in a shorter run: "weak El Niño conditions, short of an episode";
- otherwise "neutral"; La Niña mirrored.

Presets are made in Python from the same episodes, with ISO dates.

### Readouts at the pin

For `sst` and `ndvi` each side's value at the pin is read from its tile at
the source's own zoom, as the map already reads today's SST: the pixel's
colour looked up bin for bin in NASA's colour map (the SST map already on the
page; NDVI's 143 entries sent in the payload). The bar gives both and the
change; a transparent pixel is "no data here" (land for SST, water for NDVI).

### What the map says

The pill's first line names the place and the source; its details give each
side's time and ENSO words, the capture behind an archive version, and the
enlargement past the source's pixels. The status line says when GIBS or
Esri's archive did not answer, with Retry asking again. The credit is read
off the tiles as now: GIBS's words and the source's credit, or "Powered by
Esri." with the shown release's own credit.

## Error handling

| Case | What the page does |
|---|---|
| GIBS or Esri's archive does not answer | the side keeps what it had; the status line says which; Retry asks again |
| A Wayback tile 404s (past coverage) | the nearest coarser tile is drawn, as for Esri's grey tile |
| A metadata query fails or times out | the version is named by its release date, "capture date not given" |
| The tilemap walk stops midway | the versions found so far are offered, and the bar says the archive stopped answering |
| No image within 20 days (Landsat and Sentinel-2) | the side is empty, the bar says so, ◀ and ▶ look further |
| A date before an archive's first | the first date, and the bar says the archive starts then |
| Only one capture at the pin | both sides show it, and the bar says the archive holds one capture here |
| Offline | the bar says the archives need the network; tiles drawn stay |
| `#then=` malformed | ignored, as a malformed `#at=` is |

## Testing

- Python: the season words for runs of every kind, from a made-up series;
  presets for past, current and absent episodes; the payload's sources and
  ranges; the markup's controls, names and roles.
- Script, run under node from the page's own functions: span parsing and
  snapping (daily, 16-day across a year's seam, gaps); the ENSO words for a
  date; presets applied and the same-capture rule; the archive walk against
  a stubbed fetch (select chains, a stop, a failure) and capture dedup; the
  two sides' cells at their own times; enter and exit restoring state;
  arming, tapping, Esc; the drag's drop and cancel; `#then=` parsing; the
  readouts' colour lookups; the pill's and status line's words.
- Each new test watched failing before its code, and each fix checked by
  breaking it (the project's mutation checks).
- A browser pass over the built page: drag, press-and-tap, Here's button;
  each source; the events; the strip; Street View; Copy link; Exit; a phone
  width; dark mode; offline and GIBS blocked. Screenshots under `.playwright-mcp`.
