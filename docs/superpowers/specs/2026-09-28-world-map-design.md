# The map: El Niño's effects, street by street — design

Date: 2026-09-28. Branch: `round-14-world-map`, on top of `round-13-storm-desk`.

## What was asked, and what it is taken to mean

The request, in the user's words: "where's the google maps data, i should be
able to go into the map and explore the world with el nino's effects on it."

What exists: the atlas (`atlas.html`) has El Niño's measured effects - the
GPCP/GHCN-CAMS composites, a click dossier - on a plate carrée map of vector
Natural Earth and NASA imagery no finer than 250 m, with links out to Google.
The storm desk (`storms.html`, round 13, not yet run into `output/`) has a
Web Mercator map that zooms to 30 m imagery, a place search and a tap-anywhere
panel, but no El Niño on it. No page has street-level map data, and the one
map that zooms has none of El Niño's effects.

| Said | Taken as |
|---|---|
| google maps data | street maps, sub-metre satellite imagery and place names in the page, zoomable to single streets and buildings; Google's own map, satellite view and Street View of any point, in the page, on request; Google Maps opened at the same point |
| go into the map | one Web Mercator map from the whole planet to a street (zoom 1 to 19), dragged, pinched, searched by town or by street address |
| explore the world with El Niño's effects on it | the measured effects (what past El Niños did to rainfall and temperature, season by season, with the significance test), the event itself today (sea-surface temperature anomaly), what is happening now (floods mapped in the last three days), and where the documented teleconnections land - which of them this event puts in play - all drawn on that map, and read out for any point tapped or searched |

Assumed, not said: this is the same person who asked for the storm desk, on
the same devices, so the map keeps every storm on it and keeps working on a
tablet.

## Verified on 28 September 2026

Every feed below was requested from this machine on that day; each claim is
what came back.

| Feed | Answer |
|---|---|
| Esri World Street Map, World Imagery, World Topo, Reference/World_Boundaries_and_Places, Reference/World_Transportation (`server.arcgisonline.com/.../MapServer/tile/{z}/{y}/{x}`) | 200 with no key, `Access-Control-Allow-Origin: *`; 24 levels listed; imagery real at zoom 17 in Washington (buildings). Credits as the services publish them. Licensed under the Esri Master License Agreement; "not intended to be used to export tiles for offline". |
| Esri past its coverage | **200 with a grey "Map data not yet available" JPEG** - open Pacific from zoom 16, Amazon imagery from 18, Lima from 20. 240 of 256 sampled pixels are exactly RGB 204,204,204. |
| CARTO basemaps | **200 with an "API KEY REQUIRED" image**. Not usable. |
| OpenStreetMap tiles | **200 with an "Access blocked" image when no Referer is sent**, which is what a page opened from a file sends; a real tile with a Referer, which a served page sends. |
| Google `maps.google.com/maps?...&output=embed` / `output=svembed` | 301 to Google's current embed, `https://www.google.com/maps/embed?origin=mfe&pb=...`, which is 200, frameable (no X-Frame-Options), and loads Google's own Maps script with Google's own key. `t=m` maps to a road map, `t=k`/`t=h` to satellite, `svembed` to Street View at `cbll`. |
| Google Maps URLs (`https://www.google.com/maps/@?api=1&map_action=map|pano...`) | documented by Google, no key. |
| Esri World Geocoder `findAddressCandidates` | 200 with no key and no `forStorage`; CORS answered for `Origin: null` (a file) and for `http://127.0.0.1:8765`. "Miraflores, Lima" gave three candidates with extents. |
| GIBS Web Mercator | `GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies`, `GoogleMapsCompatible_Level7`, PNG, daily to 27 Sep 2026; `MODIS_Combined_Flood_3-Day`, `GoogleMapsCompatible_Level9`, PNG, daily to 28 Sep 2026. Colour maps: `GHRSST_Sea_Surface_Temperature_Anomalies.xml` (0.1 °C bins from -3.0 to +3.0 with open ends, one RGB each), `MODIS_Flood.xml` (no water, surface water, recurring flood, flood, insufficient data). |
| GIBS, not used | fire detections are Mapbox vector tiles in Web Mercator; `JPL_MEaSUREs_L4_Sea_Surface_Height_Anomalies` ends in January 2019. |

## Success criteria

1. `output/map.html` opens on the whole planet with a street map under the
   El Niño rainfall composite for the season containing today, and zooms,
   drags and pinches from zoom 1 to zoom 19. Street, satellite (with roads and
   names) and terrain maps are one tap each; so is every NASA layer the storm
   desk already had.
2. Where Esri has no tile at a zoom, the map shows the nearest coarser tile
   it does have, never the grey placeholder.
3. Rainfall and temperature composites are drawn exactly as the atlas draws
   them - the same grids, colour ramp, full-scale limits, significance mask
   and fade - for any of the four seasons, with the legend and a readout of
   the cell under the centre of the view.
4. Tapping or finding any point gives, for that point: the composite for all
   four seasons for rainfall and temperature, each with its difference, the
   ordinary season it differs from (percentage for rainfall only), |t| against
   what the season needs, and the verdict - identical to Python's
   `atlas.sample` and verdict rule; the documented teleconnections whose
   footprints cover it, marked where this event puts them in play; and, on
   request, Google's own map, satellite view and Street View of the point,
   plus links that open Google Maps, Street View and Google Earth there.
5. The ocean today (MUR SST anomaly) and floods in the last three days are
   drawable over any base, and a tap on them reads back the value or class
   from NASA's own colour map.
6. The Niño regions are drawn with this week's anomalies; the documented
   impact regions are drawn, the ones in play this event solid; the panel
   says what state the event is in.
7. The search finds addresses and streets through Esri's geocoder, but only
   when the reader chooses to send the words there.
8. `output/storms.html` is the same page opened on the storms; both carry
   everything. Dashboard, atlas and storm desk link to the map.
9. Offline, the page still draws the coastline, every storm, the composites,
   the impact regions and the Niño boxes, and says which layers need the
   network. Nothing is presented as finer than it is: a 2.5° composite cell is
   labelled as 278 km across at street zoom, not implied to be a street's.

## Out of scope, and why

- Google's tiles under the page's own layers: Google's terms forbid it, and
  the embed and Maps URLs give the same data legitimately.
- Preventing or steering storms: not possible (README section 10).
- La Niña composites and per-event consistency counts: new computation
  against PSL, not what was asked.
- Fire detections (vector tiles need a protobuf renderer) and sea-surface
  height (ends 2019).
- A forecast of this season's rainfall at a point: the composite is what past
  events did; the CPC and national services' outlooks are the forecast.

## Architecture

One map engine: the storm desk's Web Mercator map. It gains street-map tile
layers, a composite canvas, El Niño tile overlays and hooks for the new panel
sections. A new module, `elnino/worldmap.py`, owns everything El Niño and
everything street-map: the layer catalogue, the colour maps, the "El Niño now"
panel section, the payload the page adds to the desk's, its CSS and its
script, which the desk's script takes in at a marker. `stormdesk.page(state,
focus)` writes both pages; `focus="world"` is `map.html`, `focus="storms"` is
`storms.html` (unchanged defaults).

### Layers

| Group | Id | Source | Native max zoom |
|---|---|---|---|
| Map (kind `map`) | `streets` | Esri World Street Map | 19 |
| | `satellite` | Esri World Imagery, then World Transportation, then World Boundaries and Places, drawn as one stack | 19 |
| | `terrain` | Esri World Topo Map | 19 |
| | `osm` | OpenStreetMap standard; offered only when the page is served over http(s) | 19 |
| NASA (kind `imagery`) | unchanged from round 13 | GIBS | as before |
| El Niño tiles (kind `enso`) | `sst` | GIBS MUR SST anomaly, daily | 7 |
| | `floods` | GIBS MODIS combined flood, 3-day, daily | 9 |
| El Niño drawn | `rain`, `temp` | `composite.py` grids, drawn on a canvas | n/a |

The view's maximum zoom is 19 on a map layer and 13 on a NASA layer, as
before; switching to a NASA layer from deeper zooms out to 13. El Niño tile
overlays hide above zoom 12 (a 1 km pixel is then 128 screen pixels) and the
legend says so.

Placeholder rule: a map-layer tile is sampled 16 x 16 once loaded (CORS is
open); if at least 200 of the 256 samples are within 3 of RGB 204,204,204 it
is Esri's placeholder. It is hidden, its (layer, z, x, y) is remembered, and
that part of the view is drawn from the parent tile, repeatedly, up the
pyramid until a real tile answers.

### The composite on the map

The grids are the atlas's (`atlasview._grid_payload()`), parsed once. Each
cell is a rectangle in Mercator, drawn on a canvas under the map's place
names and marks, culled to the view, batched by colour. Colour: the atlas's
11-step diverging ramp (`fields.DIVERGING_LIGHT/DARK`, the page's `--d0..--d10`),
rainfall negated so dry reads warm, full scale ±3.0 mm/day and ±1.6 °C.
Cells failing the season's t test are drawn at 0.16 of full weight unless the
reader turns the mask off. Past 90 screen pixels a cell, weight falls to
`max(0.42, 1 - (px - 90) / 420)`, as in the atlas. Overall opacity 0.58,
adjustable. When a point is pinned, its cell is outlined.

The season shown by default is the one containing the build date (SON on 28
September), the payload carries `now` and `next`, and the buttons mark them.

### Here

After the storm lines: "El Niño here" - per season, rainfall and temperature
lines (value, ordinary season, percentage for rain where the ordinary season
is at least `atlas.DRY_FLOOR`, |t| and what it needs, verdict), the cell size
in kilometres, the events sampled; the impact regions covering the point with
"in play" where the event's hazard outlook lists them. Then "Google Maps here":
Map, Satellite and Street View buttons that load Google's embed in a frame
beneath (nothing is requested from Google before a press), and links opening
Google Maps, Street View and Google Earth. Then the atlas link.

### Find

Gazetteer first, as now. A last row, "Search streets and addresses for
'...'", sends the words to Esri's World Geocoder only when chosen, and lists
up to six candidates, which fly to their extents.

### The panel's El Niño section (server-rendered)

The index tier, value and season (legacy ONI beside RONI), CPC's status, this
week's Niño 3.4, the forecast peak; the impacts this event puts in play and
the watch list, each with a Show button that flies to its footprint; what each
layer is and where it comes from.

### Pages and links

- `map.html`: title "El Niño map"; base `streets`, overlay `rain`, season
  now; opens on the planet centred at 150°W, or on `#at=LAT,LON` /
  `#view=LAT,LON,Z` when the link carries one.
- `storms.html`: as round 13 (GeoColor, no El Niño overlay, fitted to the
  storms), plus everything above one tap away.
- Header links between the two carry the current view.
- Dashboard: a card for the map beside the atlas's, and the storm-desk card
  mentions it. Atlas dossier: "This point on the map".
- `track.py` writes `map.html` with `storms.html`; `--serve` prints both
  addresses; `/` still redirects to the storm desk.

## Error handling

- Esri unreachable or tiles failing: tiles stay hidden; the status line says
  which service did not answer; the vendored coastline is drawn as for GIBS.
- OSM from a file: the button is disabled and says why.
- GIBS down: El Niño tile overlays say GIBS did not answer; composites,
  impact regions and Niño boxes draw from the page.
- Geocoder fails or offline: the note says so; the gazetteer still works.
- Google embed: Google's own frame shows Google's own errors; the links still
  work.
- State pieces missing (no assessment, no impacts, no forecast): the El Niño
  section says what did not arrive; the map layers still draw.

## Testing

- Python: the layer catalogue, the colour maps as parsed, season-now, the El
  Niño section from a state and from a state missing parts, both page focuses,
  the map payload, track writing `map.html`, the dashboard and atlas links.
- Node (the page's own functions, as in round 13): tile URLs for the map
  layers; the placeholder test on synthetic pixels; parent fallback in
  `cells`; composite sampling and verdicts against Python `atlas.sample` at
  hundreds of points; the SST and flood read-back against the colour maps;
  the Google URL builders; the geocoder answer parsed; the hash parsed.
- The browser: one pass with Playwright if the page can be loaded without a
  server; otherwise said so.
