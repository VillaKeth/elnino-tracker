# Storm desk: design

Date: 2026-09-25. Branch: `round-13-storm-desk`, on top of `round-12-accuracy`.

## What was asked, and what it is taken to mean

The request, in the user's words: accurate map data to zoom directly into the
eye of the storm; predict new hurricanes; track current storms; protect
people, places, pets and animals; something people can use and reference; on
a tablet, zoom in, "swap" and "play"; prevent storms.

Read as:

| Said | Taken as |
|---|---|
| zoom into the eye | live geostationary imagery, zoomable to the eye, with the official centre marked where it is *at the image's own time* |
| predict new hurricanes | every official formation outlook: NHC's three basins with their 2-day and 7-day chances, JTWC's Pacific and Indian Ocean advisories, and the invests NHC is running guidance on |
| track current storms | every live storm on Earth: NHC and CPHC (already tracked) plus JTWC's west Pacific, north Indian and southern hemisphere warnings (not tracked today) |
| protect people, places, pets | the official protective products per storm (watches and warnings, wind speed probabilities, peak surge), which places the official forecast puts inside tropical-storm, 50-kt and hurricane-force winds and when, what to do for people and animals, and who is responsible for warnings there |
| people can reference this | nothing unofficial presented as official; every product with its issue time and age; stale data says so |
| tablet, zoom, swap, play | touch first: pinch, pan, double-tap; a swipe comparing two imagery layers; an imagery loop; a forecast scrubber; served to a tablet on the same network |
| prevent storms | not possible, and not built. README section 10 (STORMFURY) is the argument. The page says, once, that the deliverable is lead time and links to it |

Assumed, not said: "NSA tablet" means any tablet browser; nothing here is
specific to one device or agency.

## Success criteria

1. One tap on any live storm flies to its eye on imagery no older than the
   latest GIBS frame (typically 40-60 minutes behind real time). The frame's
   own UTC time and age are on screen, the official centre is drawn at that
   time, and the satellite-parallax offset of the cloud tops is drawn and
   stated.
2. Every official formation area in the NHC outlooks is on the map with its
   2-day and 7-day chance; every JTWC disturbance with its 24-hour potential.
3. Every live warned storm worldwide is on the map with its track, official
   forecast, cone (NHC; JTWC publishes none) and wind radii.
4. Each storm has a Protect view: watches and warnings in effect, the official
   per-location wind probabilities, peak surge where issued, exposed places
   with the earliest arrival of each wind threshold along the official
   forecast, actions for people and for animals, and the responsible centres.
5. Works by touch on a tablet at 1024x768 and 768x1024 and on a phone at
   390x844: pinch, pan, double-tap, swipe divider, loop, scrubber, 44 px
   targets, no horizontal page scroll. `python track.py --serve --lan`
   serves it to a tablet on the same network and keeps it current with
   `--watch`.
6. Nothing fabricated. Each number is either an official product value or is
   labelled as derived, with the method stated beside it.

## Out of scope

- Modifying or preventing storms.
- An in-house genesis model. NHC's formation probabilities are verified and
  well calibrated; an unverified model beside them would be less accurate and
  would be read as if it were not.
- Local evacuation zones and shelter databases: local, changing, and owned by
  emergency managers. The page links to who owns them.
- Push notifications.

## Architecture

New modules, one job each:

| Module | Job |
|---|---|
| `elnino/kml.py` | KML reading: placemarks, names, ExtendedData, coordinates; polygon simplification |
| `elnino/tcproducts.py` | NHC per-storm products: watches/warnings (KMZ), cone (KMZ), peak surge (KML), wind speed probabilities (text) |
| `elnino/jtwc.py` | JTWC: RSS index, `.tcw` warning files to `Storm` objects, ABPW/ABIO disturbances |
| `elnino/outlook.py` | NHC graphical outlooks (KMZ) to disturbances; merge with JTWC; dedupe the systems CPHC and NHC both list |
| `elnino/exposure.py` | geometry: quadrant wind radii, place exposure along the forecast, centre at a given time, geostationary view angle and parallax |
| `elnino/stormdesk.py` | the page (`storms.html`) and its data (`storms.json`) |

Changes to existing modules:

- `cyclones.py`: `Fix.radii` from the ATCF radius rows (34/50/64 kt by quadrant,
  `NEQ` or full-circle `AAA`), merged across the rows `parse_atcf` currently
  collapses. `Storm` gains `centre` (the issuing centre), `products` and an
  `invest` flag. `CycloneState` gains `outlook` and a `JTWC` group that is
  excluded from season statistics, which stay Atlantic and east Pacific.
- `sources.py`: payload decoding split out and made binary-safe: gzip as now,
  a zip containing KML is unpacked to its KML text, so the cache stays text.
  Registry gains the three NHC outlook KMZs, the JTWC RSS, ABPW and ABIO.
  Dynamic sources gain the NHC product URLs read from `CurrentStorms.json` and
  the JTWC `.tcw` per storm.
- `pipeline.py`, `track.py`: wire it in; write `storms.html` and `storms.json`;
  `--serve [PORT]`, `--lan`.
- `dashboard.py`: a Storm desk card linking the page; `latest.json` schema 9.
- `report.py`: an outlook section; protective products under each storm.
- `alerts.py`: official products raise alerts with stable codes, one per
  storm and product type: hurricane warning CRITICAL; hurricane watch or
  tropical storm warning WARNING; tropical storm watch WATCH; a formation
  area at NHC's "high" (7-day chance above 60%) or JTWC's HIGH, WATCH.
- `atlasview.py`, `globe.py`: real two-finger pinch. The atlas hint promises
  pinch, but the handler tracks one pointer, so on a tablet it pans instead.

## Data flow per run

1. First wave (registry, parallel): existing feeds plus the three outlook
   KMZs, JTWC RSS, ABPW, ABIO.
2. Cyclone build: `CurrentStorms.json` as now; per live NHC storm the three
   decks as now, plus watches/warnings, cone, wind probabilities and peak
   surge where the index links them. JTWC: each west Pacific, Indian Ocean
   or southern hemisphere `.tcw` the RSS lists. Invests: b-decks for numbers
   90-99 that the ATCF listing shows modified within 24 hours, with their
   a-deck guidance.
3. Imagery needs nothing at run time. The page asks GIBS for each layer's
   time domain when it opens (CORS is open) and labels every frame with its
   own time, so a page opened hours after it was written still shows the
   newest frame, correctly dated.

## Accuracy rules

- Centre at image time: linear interpolation in time along the analysed fixes,
  the advisory position and the official forecast; never extrapolated past
  the last forecast point.
- Satellite: the one of GOES-East (75.2 W), GOES-West (137.0 W) and Himawari
  (140.7 E) with the smallest viewing zenith angle at the view centre; beyond
  70 degrees none is used and the page says so (the Indian Ocean west of
  about 70 E has no geostationary layer in GIBS).
- Parallax: cloud tops at 15 km appear displaced by 15 km x tan(zenith) away
  from the sub-satellite point. The apparent eye is drawn as a ring at that
  offset beside the surface centre, with the height stated.
- Resolution: native pixel size is shown (1 km visible and GeoColor, 2 km
  infrared); past it, the page says the imagery is enlarged.
- Exposure: hourly along the official forecast, centre and radii interpolated
  between forecast times; a threshold is only evaluated where the forecast
  carries radii for it. Labelled as "if the storm follows the official track
  exactly", next to the official probabilities, which carry the uncertainty.
- Every product shows issue time and age. Warnings and probabilities come
  from the advisory named in the index; a product whose advisory number
  differs from the storm's current one is labelled with its own number.

## Page

Map first. Wide screens: map with a right-hand panel. Narrow: map with a
bottom sheet.

- Layers: GeoColor, visible, infrared, air mass (auto-picked satellite), rain
  rate (IMERG 30 min), true colour (daily VIIRS), Blue Marble. Overlays:
  labels and roads (GIBS reference, OSM-derived, to street level), coastlines,
  cone, wind radii, watches and warnings, surge, outlook areas, places.
- Compare: a vertical divider shows a second layer under the first; drag it.
- Loop: the last two hours of frames, play and pause, each frame's time shown.
- Forecast scrubber: now to +120 h; the storm, its radii and the places inside
  each threshold move with it.
- Panel: storm list (name, category, wind, pressure, motion, advisory age,
  Eye button); per storm Now / Forecast / Protect; the outlook list.
- Offline: vendored coastline drawn if tiles fail, and the page says imagery is
  unreachable.
- Encoding: storm identity by categorical hue in fixed order, category by
  marker size and a text label, as the dashboard already does. Watches and
  warnings, surge and outlook chances keep the official product colours and
  always carry their label. Legends present; every map layer has a table.
- Light and dark from tokens; overlays carry halos so they read on cloud and
  on ocean alike.

## Testing

- Parsers against trimmed copies of today's live products: outlook KML,
  watches/warnings KML, cone KML, peak surge KML, wind probability text, TCW,
  RSS, ABPW (live plus a disturbance written to JTWC's format).
- Geometry: quadrant lookup, exposure on a synthetic storm with a known answer,
  interpolation, zenith and parallax against hand-computed values, satellite
  choice.
- Decoding: gzip, zip-with-KML, plain text.
- Page and JSON: payload present, controls, legends, tables, schema 9; the
  end-to-end offline run writes `storms.html`.
- Browser (Playwright): light and dark; tap to eye; pinch by synthetic
  pointers; swipe; loop advances; scrubber moves radii; zero console errors;
  tablet and phone viewports; no page overflow.

## Addendum, 25 September 2026: exploring places

Asked mid-round: "i should be able to exploore the city and geographic
locations". Read as: find any town, region, country or coordinate on the
storm desk, close in until the town can be recognised, and see what every
live storm and formation area means for that exact spot.

1. Find. A search box on the desk takes a town, a first-level region, a
   country or a coordinate ("18.0N 76.8W", "18.0, -76.8"). Suggestions come
   from the vendored Natural Earth gazetteer (7,342 places), case- and
   accent-insensitive. Choosing one flies there and pins it. No geocoding
   service: the gazetteer ships in the page.
2. Here. Tapping the map anywhere, or choosing a search result, pins that
   point and opens a Here panel: the place (nearest named place, region,
   country, population, coordinates); for each live storm the distance and
   bearing now, the closest approach along the official forecast (distance,
   time, intensity), the earliest arrival of 34, 50 and 64 kt winds at that
   point from the official forecast radii (the exposure table's hourly
   timeline and rules: a radius not forecast is not zero), whether the point
   is inside the cone, the distance to the nearest coast under each kind of
   watch or warning, and any peak-surge area containing it; formation areas
   containing it; who warns for it (the country's national meteorological
   service; the storm's advisory centre); a link to the El Nino atlas at that
   point.
3. Close in. The desk zooms to level 13. A Detail layer shows 30 m Harmonized
   Landsat Sentinel-2 imagery (GIBS HLS_L30 and HLS_S30) for the newest day
   with an image at the centre of the view, with earlier and later day steps,
   clouds as seen. The gazetteer's town names are drawn, more as the view
   closes in. A built-up areas overlay (Landsat human built-up and settlement
   extent) and a night-lights layer (VIIRS Black Marble 2016).
4. Honesty. Everything derived is labelled derived, with its method. These
   feeds have no street-level imagery and the page states the resolution of
   what it shows. Nothing here changes what a storm does.

Out of scope: street maps, routing, any geocoding or map service beyond NASA
GIBS, per-country warning-service addresses.
