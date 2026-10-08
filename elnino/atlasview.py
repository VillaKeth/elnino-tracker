"""The atlas page: a world you can drag, zoom and click.

``atlas`` computes; this draws. It emits two things:

``page(state)``   a standalone HTML file, ``output/atlas.html``. Full viewport,
                  because a map you are meant to zoom into should not be in a
                  600 pixel card halfway down a dashboard.
``card(state)``   a summary on the dashboard that links to it, with the anchor
                  points as a table so the dashboard still says something
                  without the reader going anywhere.

Everything is drawn in the browser from data embedded in the file. No tiles, no
CDN, no key, no request: the page works from a USB stick on a plane, which is
the same standard the rest of this system is held to.

On the absence of satellite imagery
-----------------------------------
Photographic basemap tiles are not here, by choice. Google's and Mapbox's are
served per tile against a key and a bill; Esri's answer with no key but are
licensed, and their licence rules out exporting tiles for use offline. Any of
them breaks the offline guarantee this page keeps. The street maps are the
map's (``worldmap.py``), which draws them while it has the network.
What is here instead is vector cartography from Natural Earth - coastline,
borders, rivers, lakes and 7,342 populated places - which for this purpose is
the better trade anyway: the question being asked is whether a rainfall
composite lands on a catchment or a city, and a border and a river answer that
where a photograph of cloud does not.

Colour
------
The composite is a difference, so it gets the diverging ramp the spatial tier
already uses, with a neutral midpoint that lets zero recede.

Rainfall inverts it. The ramp runs blue at the low end to red at the high one,
which is right for temperature and backwards for rain, where the dry end is
the one that should read warm. So precipitation maps the *negated* value, and
the colour bar is labelled accordingly rather than the reader being expected
to notice.

Cells that fail the significance test keep their hue and lose their weight:
they are drawn at a sixth of the opacity, and the legend says why. Giving them
a confident colour would claim a difference the record cannot distinguish from
an ordinary year, which is the failure mode this whole tier exists to avoid;
dropping them entirely would instead claim the cell was never measured. The
toggle that turns the fade off is there because a reader comparing the shape of
a pattern to a published composite wants the pattern, not the mask.

The composite is drawn as a field, not a square per cell (``FIELD_JS``, which
the map shares): at each point the cell centres around it, blended by how near
each is, and coloured in the ramp's eleven steps, so the steps meet along soft
lines as a filled contour map's do. A 2.5 degree grid painted a square per
cell read as a mosaic of big pixels. The fade blends too, from a cell that
passes to one that does not, and a click still reads the whole cell.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from . import atlas, atlasdata, coastline, composite, fields, geo, live, relief, sitenav
from .impacts import CATALOGUE
from .svg import esc, table

# Degrees of longitude per pixel at the two ends of the zoom range. The wide
# end puts the whole world in about a thousand pixels; the tight end is about
# 200 m to a pixel, which is past the resolution of every layer here and is
# there so the reader can see that it is, rather than being stopped early.
WIDE = 0.36
TIGHT = 0.002

# Population a place must have to be drawn, by detail level. A world map
# labelled with every town is a grey smear; a street map with only capitals is
# useless. These are the thresholds where each stops being true.
PLACE_FLOOR = (2_000_000, 400_000, 80_000, 0)

VARIABLES = (
    ("PRECIP", "Rainfall", "mm/day", True),
    ("AIR", "Temperature", "°C", False),
)


# NASA's Global Imagery Browse Services, which serves its imagery in
# EPSG:4326 - plate carree, the projection this map already draws in. That is
# why it is here and Google, Mapbox or Esri are not: those are Web Mercator, so
# using one would mean reprojecting every cell of the composite onto it, and
# Google's and Mapbox's also want a key in this repository and a billing
# account behind it (Esri's need no key, but are licensed and not for use
# offline). GIBS needs none of that, is public domain, and lines up. The street
# maps are the map's (worldmap.py), which is Web Mercator throughout.
GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg4326/best"

# ``lag`` is how far behind today to ask for. A daily global mosaic is not
# complete the moment the day ends, and a tile that does not exist yet is a
# 400, so the page asks for a day that has certainly finished processing
# rather than for today and a blank map.
BASEMAPS = (
    {"id": "relief", "label": "Relief", "kind": "relief",
     "credit": "ETOPO1 global relief, NOAA NCEI - vendored, works offline",
     "note": "Land height and sea-floor depth, shaded from the north-west."},
    {"id": "marble", "label": "Blue Marble", "kind": "gibs", "max": 7,
     "layer": "BlueMarble_ShadedRelief_Bathymetry", "tms": "500m",
     "ext": "jpeg", "lag": None,
     "credit": "NASA Blue Marble, shaded relief and bathymetry (GIBS)",
     "note": "A cloud-free composite, so it is the land itself, not a day."},
    {"id": "photo", "label": "Satellite", "kind": "gibs", "max": 8,
     "layer": "VIIRS_SNPP_CorrectedReflectance_TrueColor", "tms": "250m",
     "ext": "jpg", "lag": 2,
     "credit": "VIIRS on Suomi NPP, corrected-reflectance true colour (GIBS)",
     "note": "An actual photograph of the Earth, cloud and all, at 250 m. "
             "Black at the winter pole is night, not missing data."},
    {"id": "sst", "label": "SST anomaly", "kind": "gibs", "max": 6,
     "layer": "GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies", "tms": "1km",
     "ext": "png", "lag": 3, "scale": "NASA's own scale, −3 to +3 °C",
     "credit": "GHRSST Level 4 MUR sea-surface temperature anomaly (GIBS)",
     "note": "Today's ocean against its own climatology - the event itself, "
             "at 1 km, not the forty-year composite."},
)


def _bases_payload() -> list:
    """The basemap catalogue with each dated layer's day already resolved."""
    today = datetime.now(timezone.utc).date()
    out = []
    for base in BASEMAPS:
        item = dict(base)
        lag = item.pop("lag", None)
        if lag is not None:
            item["date"] = (today - timedelta(days=lag)).isoformat()
        out.append(item)
    return out


def _places_payload() -> list:
    return [[p.name, p.country, p.region, p.population,
             round(p.lon, 3), round(p.lat, 3), 1 if p.capital else 0]
            for p in atlasdata.PLACES]


def _grid_payload() -> dict:
    """The composite grids, as stored, for the browser to parse once.

    The encoded text is shipped rather than a JSON array of floats: it is the
    form already in the repository, it is about a third of the size, and the
    parse on the other side is a split and a division.
    """
    out: dict = {}
    for name, label, unit, invert in VARIABLES:
        seasons = {}
        for season in atlas.SEASONS:
            seasons[season] = {
                "diff": getattr(composite, f"{name}_{season}_DIFF"),
                "base": getattr(composite, f"{name}_{season}_BASE"),
                "t": getattr(composite, f"{name}_{season}_T"),
            }
        out[name] = {
            "label": label,
            "unit": unit,
            "invert": invert,
            "scale": getattr(composite, f"{name}_SCALE"),
            "lats": getattr(composite, f"{name}_LATS"),
            "lons": getattr(composite, f"{name}_LONS"),
            "meta": getattr(composite, f"{name}_META"),
            "seasons": seasons,
        }
    return out


def _links_payload() -> list:
    """The teleconnection catalogue with its footprints, for a click."""
    out = []
    for link in CATALOGUE:
        footprint = geo.BY_REGION.get(link.region)
        if footprint is None:
            continue
        out.append({
            "region": link.region,
            "effect": link.effect,
            "window": link.window,
            "confidence": link.confidence,
            "polarity": link.polarity,
            "scope": footprint.scope,
            "detail": link.detail,
            "exposure": link.exposure,
            "boxes": [[b.lon0, b.lon1, b.lat0, b.lat1]
                      for b in footprint.boxes],
        })
    return out


def _storms_payload(state) -> list:
    storms = getattr(getattr(state, "cyclones", None), "storms", ()) or ()
    out = []
    for storm in storms:
        if not getattr(storm, "active", False):
            continue
        fix = storm.latest
        # A storm with an open advisory but no analysis fix has nowhere to be
        # drawn. It is in the storm tier's tables either way; it is only the
        # map that needs a position.
        if fix is None:
            continue

        # Each longitude within 180 degrees of where the storm is now: ATCF's
        # run 180 W to 180 E, and a track across the date line drawn through
        # them as given runs the whole way round the world.
        def beside(lon, now=fix.lon):
            return round(now + (lon - now + 180.0) % 360.0 - 180.0, 2)

        out.append({
            "name": storm.title,
            "basin": storm.basin,
            "lon": round(fix.lon, 2),
            "lat": round(fix.lat, 2),
            "wind": fix.wind,
            "track": [[beside(f.lon), round(f.lat, 2)]
                      for f in storm.track if f.tau == 0],
            "forecast": [[beside(f.lon), round(f.lat, 2)]
                         for f in storm.forecast],
        })
    return out


def payload(state) -> dict:
    return {
        "grids": _grid_payload(),
        "places": _places_payload(),
        "links": _links_payload(),
        "storms": _storms_payload(state),
        "coast": [list(pair) for pair in coastline.packed()],
        "borders": [list(pair) for pair in atlasdata.packed("borders")],
        "rivers": [list(pair) for pair in atlasdata.packed("rivers")],
        "lakes": [list(pair) for pair in atlasdata.packed("lakes")],
        "tolerances": list(atlasdata.TOLERANCES),
        "wide": WIDE,
        "tight": TIGHT,
        "floors": list(PLACE_FLOOR),
        # The |t| each season must reach, per variable: the 95% point of
        # Student's t for that season's own sample. null where a season has
        # too few events to test at all.
        "significant": {
            name: {season: getattr(composite, f"{name}_META")[season]["t_crit"]
                   for season in atlas.SEASONS}
            for name, _, _, _ in VARIABLES
        },
        "seasons": list(atlas.SEASONS),
        "season_label": atlas.SEASON_LABEL,
        "dry_floor": atlas.DRY_FLOOR,
        "bases": _bases_payload(),
        "gibs": GIBS,
        "relief": {
            "ny": relief.NY, "nx": relief.NX, "lat0": relief.LAT0,
            "lon0": relief.LON0, "step": relief.STEP,
            "offset": relief.OFFSET, "source": relief.SOURCE,
            "vendored": relief.VENDORED,
        },
    }


# --- the dashboard card ------------------------------------------------------

def _anchor_rows(state) -> list[list[str]]:
    rows = []
    for local in state.atlas.anchors:
        # Every column in the row's own season: the temperature used to be
        # the December-to-February composite whatever season the row was.
        strongest = local.strongest
        if strongest is None:
            continue
        percent = strongest.precip.percent
        rows.append([
            local.title.split(",")[0],
            atlas.SEASON_LABEL[strongest.season].replace(" to ", "–"),
            "—" if percent is None else f"{percent:+.0f}%",
            f"{strongest.precip.value:+.2f}",
            f"{strongest.precip.t:+.2f}" if strongest.precip.t is not None
            else "—",
            f"{strongest.precip.crit:.2f}",
            strongest.precip.direction,
            atlas.temperature_text(strongest.air) or "—",
        ])
    return rows


def card(state) -> str:
    """The dashboard's summary of the atlas, and the way in."""
    if not getattr(state, "atlas", None) or not state.atlas.available:
        return ""
    tier = state.atlas
    rows = _anchor_rows(state)
    reasons = "".join(f"<li>{esc(reason)}</li>" for reason in tier.reasons)
    lessons = "".join(f'<p class="prose caveat">{esc(lesson)}</p>'
                      for lesson in atlas.lessons(tier))
    return f"""
<section class="card" id="atlas">
  <h2>Where it lands</h2>
  <p class="prose">Every other tier here is about the Pacific. This one is
    about a point on the ground. The atlas holds what the El Nino events since
    1979 actually did at each cell of the world - rainfall against an ordinary
    year, and surface temperature - and resolves a click to the nearest of
    {len(atlasdata.PLACES):,} named places.</p>
  <p class="prose"><a class="bigalink" href="atlas.html">Open the interactive
    atlas &rarr;</a> Drag to pan, scroll or use the buttons to zoom, click
    anywhere for the local record.</p>
  <ul class="reasons">{reasons}</ul>
  {table("The season each anchor feels most, and how far from normal",
         ["Place", "Season", "% of normal", "mm/day", "Welch t", "Needs |t|",
          "Verdict", "Temp °C"], rows, expanded=True)}
  <p class="prose caveat">{esc(atlas.NO_SIGNAL)}
    {esc(atlas.PARENTHESES)}</p>
  {lessons}
</section>"""


def css() -> str:
    """The atlas page's own rules, on top of the dashboard's tokens."""
    return """
/* One sea colour, because the map has a background that is not the page. */
:root { --sea: #e8eef4; --land: #f6f5f1; --riv: #9ec2dd; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --sea: #10171d; --land: #1d1d1c; --riv: #35566b; } }
:root[data-theme="dark"] { --sea: #10171d; --land: #1d1d1c; --riv: #35566b; }

/* The map is the page here, so it gets the viewport and the panel docks
   beside it; under 900px the panel goes below, because a dossier in a 200px
   column is unreadable and a map in one is pointless. */
body.atlaspage { height: 100vh; display: flex; flex-direction: column;
  overflow: hidden; }
.atlaswrap { flex: 1 1 auto; min-height: 0; display: grid;
  grid-template-columns: 1fr 390px; }
.atlasmap { position: relative; overflow: hidden; background: var(--sea);
  touch-action: none; }
/* Four stacked layers in one box: a canvas carrying the shaded relief, a div
   of imagery tiles, a canvas carrying the composite, and the vector map over
   all three. The first three are painted rasters, which let every click
   through to the vector map on top; it answers with the cell underneath. */
.atlasmap #relief, .atlasmap #tiles, .atlasmap #field { position: absolute; left: 0; top: 0;
  width: 100%; height: 100%; pointer-events: none; }
.atlasmap #tiles { overflow: hidden; }
.atlasmap #tiles img { position: absolute; display: block; }
.atlasmap svg { position: relative; display: block; cursor: grab; }
.atlasmap #credit { position: absolute; right: 14px; bottom: 14px; left: auto;
  max-width: 46%; text-align: right; line-height: 1.35; white-space: normal; }
/* Ways out of the page, for the questions a composite cannot answer: what the
   street looks like, what the cloud did this morning. */
.dossier ul.links { list-style: none; padding: 0; margin: 7px 0 0;
  display: flex; flex-wrap: wrap; gap: 6px; }
.dossier ul.links a, .dossier button#truth { display: inline-block;
  font: inherit; font-size: 11.5px; padding: 4px 9px; background: var(--surface);
  border: 1px solid var(--border); border-radius: 6px; color: var(--ink2);
  text-decoration: none; cursor: pointer; }
.dossier ul.links a:hover, .dossier button#truth:hover { color: var(--ink);
  border-color: var(--ink2); }
.dossier button#truth[disabled] { opacity: .55; cursor: default; }
.dossier #truthout { font-size: 11.5px; color: var(--ink2); }
.atlasmap.dragging svg { cursor: grabbing; }
.atlaspanel { overflow-y: auto; border-left: 1px solid var(--border);
  background: var(--surface); padding: 18px 20px 48px; }
.atlasbar { flex: 0 0 auto; display: flex; flex-wrap: wrap; gap: 10px;
  align-items: center; padding: 9px 16px;
  border-bottom: 1px solid var(--border); background: var(--surface); }
.atlasbar h1 { font-size: 15px; margin: 0 6px 0 0; letter-spacing: -0.01em; }
.atlasbar .grp { display: flex; border: 1px solid var(--border);
  border-radius: 7px; overflow: hidden; }
.atlasbar button { font: inherit; font-size: 12px; padding: 5px 11px;
  background: var(--surface); color: var(--ink); border: 0; cursor: pointer;
  border-right: 1px solid var(--border); }
.atlasbar .grp button:last-child { border-right: 0; }
.atlasbar button[aria-pressed="true"] { background: var(--ink);
  color: var(--surface); }
.atlasbar .lbl { font-size: 10.5px; letter-spacing: .07em;
  text-transform: uppercase; color: var(--muted); }
.atlasbar .spacer { flex: 1 1 auto; }
.atlaszoom { position: absolute; right: 14px; top: 14px; display: grid;
  gap: 6px; }
.atlaszoom button { width: 34px; height: 34px; font-size: 16px; line-height: 1;
  border: 1px solid var(--border); border-radius: 8px;
  background: var(--surface); color: var(--ink); cursor: pointer; }
.atlaspill { position: absolute; font-size: 11px; color: var(--ink2);
  background: var(--surface); padding: 4px 8px; border: 1px solid var(--border);
  border-radius: 6px; opacity: .93; font-variant-numeric: tabular-nums;
  pointer-events: none; }
#read { left: 14px; top: 14px; }
#scale { left: 14px; bottom: 14px; color: var(--ink); }
#scale .bar { display: block; height: 3px; background: var(--ink);
  margin-bottom: 3px; }
.atlaslegend { flex: 0 0 auto; display: flex; flex-wrap: wrap; gap: 6px 18px;
  align-items: center; padding: 7px 16px; border-top: 1px solid var(--border);
  font-size: 11.5px; color: var(--ink2); background: var(--surface); }
.atlaslegend .steps { display: flex; border-radius: 2px; overflow: hidden;
  border: 1px solid var(--border); }
.atlaslegend .steps i { width: 17px; height: 11px; display: block; }
.atlaslegend .key[hidden] { display: none; }
.atlaslegend .key { display: inline-flex; align-items: center; gap: 5px;
  white-space: nowrap; }
.atlaslegend svg { display: block; }

.dossier h2 { margin: 0 0 2px; font-size: 17px; letter-spacing: -0.01em; }
.dossier .where { color: var(--ink2); font-size: 12px; margin: 0 0 16px; }
.dossier .big { font-size: 31px; font-weight: 600; line-height: 1.08;
  font-variant-numeric: tabular-nums; letter-spacing: -0.02em; }
.dossier .bigsub { font-size: 12.5px; color: var(--ink2); margin: 3px 0 2px; }
.dossier table { width: 100%; border-collapse: collapse; font-size: 12.5px;
  margin: 4px 0 2px; }
.dossier th { text-align: left; font-weight: 500; color: var(--muted);
  font-size: 10.5px; letter-spacing: .06em; text-transform: uppercase;
  padding: 0 0 4px; }
.dossier th.num, .dossier td.num { text-align: right;
  font-variant-numeric: tabular-nums; }
.dossier td { padding: 5px 0; border-top: 1px solid var(--border);
  vertical-align: middle; }
.dossier td.bar { width: 96px; padding-left: 8px; padding-right: 8px; }
.dossier .track { display: block; position: relative; height: 12px;
  background: var(--track); border-radius: 3px; }
.dossier .track i { position: absolute; top: 0; bottom: 0; display: block;
  border-radius: 2px; }
.dossier .track u { position: absolute; top: -2px; bottom: -2px; left: 50%;
  width: 1px; background: var(--axis); }
.dossier tr.weak td { opacity: .5; }
.dossier h3 { margin: 22px 0 7px; font-size: 10.5px; letter-spacing: .07em;
  text-transform: uppercase; color: var(--muted); }
.dossier .lk { border-left: 2px solid var(--border); padding: 1px 0 1px 10px;
  margin-bottom: 11px; font-size: 12.5px; line-height: 1.5; }
.dossier .lk b { font-weight: 600; }
.dossier .lk em { font-style: normal; color: var(--ink2); }
.dossier ul.near { margin: 0; padding-left: 16px; font-size: 12.5px;
  color: var(--ink2); }
.dossier p.note { font-size: 12px; color: var(--ink2); line-height: 1.55; }
.dossier .hint { color: var(--ink2); font-size: 13px; line-height: 1.6; }
.dossier .chip { display: inline-block; font-size: 10.5px; padding: 1px 7px;
  border-radius: 999px; border: 1px solid var(--border); color: var(--ink2);
  margin-right: 5px; }
.bigalink { font-weight: 600; }

.atlaslegend .ramp {
  display: inline-block;
  width: 190px;
  height: 11px;
  border-radius: 2px;
  vertical-align: -1px;
  border: 1px solid var(--border);
}

@media (max-width: 900px) {
  body.atlaspage { height: auto; overflow: auto; }
  .atlaswrap { grid-template-columns: 1fr; }
  .atlasmap { height: 64vh; }
  .atlaspanel { border-left: 0; border-top: 1px solid var(--border); }
  /* A legend key holds a swatch and its sentence on one line, which is right
     until the sentence is wider than the phone. Then it wraps: a key that runs
     to two lines is legible, and a page that scrolls sideways is not. */
  .atlaslegend .key { white-space: normal; }
}
"""


# --- the composite as a field -----------------------------------------------
# The page's script and the map's (worldmap.py) take this in at their FIELD
# markers, so the two draw one field by one rule.
FIELD_JS = r"""
  // -- the composite as a field ----------------------------------------------
  // One value per 2.5 degree (rainfall) or 2 degree (temperature) cell,
  // painted a square per cell, reads as a mosaic of big pixels. The atlas and
  // the map draw a field instead: at each point the four cell centres around
  // it, blended by how near each is (bilinear), a cell with no record taking
  // no part. At a centre the field is that cell's value, and a click still
  // reads the whole cell. The share of the blend with a record fades the
  // land-only temperature grid out at the coast; the share of that the t test
  // passed fades a signal out where its cells stop passing.

  // A season's grid made ready to blend: its values in one array, NaN where a
  // cell has no record, and a 1 for each cell whose |t| reaches `crit`.
  function fieldOf(lats, lons, diff, tv, crit) {
    var nr = lats.length, nc = lons.length;
    var val = new Float64Array(nr * nc), sig = new Float64Array(nr * nc), r, c;
    for (r = 0; r < nr; r++) {
      for (c = 0; c < nc; c++) {
        var v = diff[r][c], t = tv[r][c];
        val[r * nc + c] = v === null ? NaN : v;
        sig[r * nc + c] = t !== null && Math.abs(t) >= crit ? 1 : 0;
      }
    }
    return { lat0: lats[0], dlat: nr > 1 ? lats[1] - lats[0] : 1, nr: nr,
             lon0: lons[0], dlon: nc > 1 ? lons[1] - lons[0] : 360, nc: nc,
             val: val, sig: sig };
  }
  // A latitude as the rows of centres either side and the share of the
  // second; past the first or the last row, that row alone.
  function fieldRow(g, lat) {
    var v = (lat - g.lat0) / g.dlat, r0 = Math.floor(v);
    if (r0 < 0) { return [0, 0, 0]; }
    if (r0 >= g.nr - 1) { return [g.nr - 1, g.nr - 1, 0]; }
    return [r0, r0 + 1, v - r0];
  }
  // A longitude as the columns either side and the share of the second, the
  // grid wrapping round the world: no seam at the date line or at Greenwich.
  function fieldCol(g, lon) {
    var u = (lon - g.lon0) / g.dlon, c0 = Math.floor(u), f = u - c0;
    c0 = ((c0 % g.nc) + g.nc) % g.nc;
    return [c0, (c0 + 1) % g.nc, f];
  }
  // The field at one point: its value (null where no cell near has a record),
  // the share of the blend with a record, and the share of that which passed.
  function fieldAt(g, lon, lat) {
    var rw = fieldRow(g, lat), cl = fieldCol(g, lon), cover = 0, sum = 0, pass = 0, i;
    var parts = [[rw[0], cl[0], (1 - rw[2]) * (1 - cl[2])],
                 [rw[0], cl[1], (1 - rw[2]) * cl[2]],
                 [rw[1], cl[0], rw[2] * (1 - cl[2])],
                 [rw[1], cl[1], rw[2] * cl[2]]];
    for (i = 0; i < 4; i++) {
      var k = parts[i][0] * g.nc + parts[i][1], w = parts[i][2], v = g.val[k];
      if (w > 0 && v === v) { cover += w; sum += w * v; pass += w * g.sig[k]; }
    }
    return cover > 0 ? { value: sum / cover, cover: cover, sig: pass / cover }
                     : { value: null, cover: 0, sig: 0 };
  }
  // The field as RGBA, a pixel for each longitude in `lons` across by each
  // latitude in `lats` down (NaN for a row off the world, left clear): each
  // pixel fieldAt its point, in the ramp's colour for the value - tone.rgb
  // the ramp as numbers, tone.invert and tone.lim the atlas's rampIndex -
  // and clear where no cell near has a record. While tone.mask is on, what
  // the t test does not pass is drawn at tone.dim of its strength. `into` is
  // a buffer to fill again. fieldAt's sums, in its order, so a pixel is
  // exactly it.
  function paintField(g, lons, lats, tone, into) {
    var fw = lons.length, fh = lats.length, n = fw * fh * 4;
    var data = into && into.length === n ? into : new Uint8ClampedArray(n);
    if (data === into) { data.fill(0); }
    var nc = g.nc, val = g.val, sig = g.sig, rgb = tone.rgb, lim = tone.lim, dim = tone.dim;
    var c0s = new Int32Array(fw), c1s = new Int32Array(fw), fus = new Float64Array(fw), i, j;
    for (i = 0; i < fw; i++) {
      var cl = fieldCol(g, lons[i]);
      c0s[i] = cl[0]; c1s[i] = cl[1]; fus[i] = cl[2];
    }
    for (j = 0; j < fh; j++) {
      if (lats[j] !== lats[j]) { continue; }
      var rw = fieldRow(g, lats[j]), a0 = rw[0] * nc, a1 = rw[1] * nc, fv = rw[2];
      var row = j * fw * 4;
      for (i = 0; i < fw; i++) {
        var fu = fus[i], c0 = c0s[i], c1 = c1s[i], cover = 0, sum = 0, pass = 0, k, w, v;
        w = (1 - fv) * (1 - fu); k = a0 + c0; v = val[k];
        if (w > 0 && v === v) { cover += w; sum += w * v; pass += w * sig[k]; }
        w = (1 - fv) * fu; k = a0 + c1; v = val[k];
        if (w > 0 && v === v) { cover += w; sum += w * v; pass += w * sig[k]; }
        w = fv * (1 - fu); k = a1 + c0; v = val[k];
        if (w > 0 && v === v) { cover += w; sum += w * v; pass += w * sig[k]; }
        w = fv * fu; k = a1 + c1; v = val[k];
        if (w > 0 && v === v) { cover += w; sum += w * v; pass += w * sig[k]; }
        if (!(cover > 0)) { continue; }
        var value = sum / cover, x = tone.invert ? -value : value;
        var s = Math.floor((x + lim) / (2 * lim) * 11), c = rgb[s < 0 ? 0 : (s > 10 ? 10 : s)];
        var a = cover * (tone.mask ? dim + (1 - dim) * (pass / cover) : 1), at = row + i * 4;
        data[at] = c[0]; data[at + 1] = c[1]; data[at + 2] = c[2];
        data[at + 3] = Math.round(a * 255);
      }
    }
    return { w: fw, h: fh, data: data };
  }
  // The field is worked out every few css pixels and drawn up to the page's
  // size with the browser's smoothing, so the ramp's steps meet along soft
  // lines, as a filled contour map's do. Its points are a lattice fixed to the
  // world, `origin` the page's place of the world's corner: worked out from
  // the page's corner instead, they slid over the ground as the view panned
  // and the steps' edges shimmered. The field starts on the lattice up to a
  // step before the page's edge,
  function fieldStart(origin, step) { return ((origin % step) + step) % step - step; }
  // and this many points from there cover `span` css pixels, however panned.
  function fieldSpan(span, step) { return Math.ceil(span / step) + 1; }
  // Two pixels apart, or wider on a page so big that would be more than a
  // quarter of a million points a frame.
  function fieldStep(w, h) {
    var step = Math.max(2, Math.ceil(Math.sqrt(w * h / 250000)));
    while (fieldSpan(w, step) * fieldSpan(h, step) > 250000) { step++; }
    return step;
  }
  // A ramp token's colour as numbers: "#rrggbb", "#rgb" or "rgb(r, g, b)",
  // else a mid grey.
  function hexRgb(text) {
    var s = String(text || "").trim(), m = /^#([0-9a-f]{6})$/i.exec(s);
    if (m) {
      return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16),
              parseInt(m[1].slice(4, 6), 16)];
    }
    m = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(s);
    if (m) {
      return [parseInt(m[1] + m[1], 16), parseInt(m[2] + m[2], 16),
              parseInt(m[3] + m[3], 16)];
    }
    m = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i.exec(s);
    return m ? [+m[1], +m[2], +m[3]] : [136, 136, 136];
  }
"""


# --- the page ---------------------------------------------------------------

_JS = r"""
(function () {
  "use strict";
  var D = ATLAS;
  var map = document.getElementById("map");
  var svg = document.getElementById("svg");
  var pan = document.getElementById("pan");
  var gVec = document.getElementById("vec");
  var gPt = document.getElementById("pts");
  var gPick = document.getElementById("pick");
  var readout = document.getElementById("read");
  var reliefCanvas = document.getElementById("relief");
  var tileBox = document.getElementById("tiles");
  var fieldCanvas = document.getElementById("field");
  var creditPill = document.getElementById("credit");
  var scalebox = document.getElementById("scale");
  var panel = document.getElementById("panel");

  // -- view ------------------------------------------------------------------
  // Plate carree: one degree of longitude is one degree of latitude on the
  // page. Shapes stretch toward the poles, which is the honest trade for a
  // thematic map whose data is itself on a regular lat/lon grid - a projection
  // that fixed the shapes would misplace the cells.
  var view = { lon: 150, lat: 0, dpp: D.wide };  // replaced on first size
  var W = 100, H = 100;
  // The opening view is the whole world across the width. A plate carree world
  // is twice as wide as it is tall, so on a landscape window this leaves sea
  // above and below; filling the height instead would cut the Atlantic off a
  // page whose whole point is teleconnections, and orientation comes before
  // tidiness on the view a reader arrives at.
  function fitted() { return 366 / W; }
  // How far out the reader may zoom. D.wide is the limit that keeps a desktop
  // window from dollying back into empty space, but on a phone the whole world
  // is wider than that per pixel, and a map that cannot show the world is not
  // an atlas. So the floor is whichever is further out.
  function widest() { return Math.max(D.wide, fitted()); }
  // Label boxes were guessed at 5.9 pixels a character, which is wrong for
  // more than a third of the gazetteer - "Wuhan" is 7.3 - and the halo adds
  // three more. A canvas measures the same string the SVG will draw, once per
  // name for the life of the page, and the collision test stops being a guess.
  var gauge = document.createElement("canvas").getContext("2d");
  gauge.font = "500 11px "
    + getComputedStyle(document.documentElement).getPropertyValue("--font");
  var gauged = {};
  function textWidth(t) {
    if (gauged[t] === undefined) { gauged[t] = gauge.measureText(t).width + 3; }
    return gauged[t];
  }
  var variable = "PRECIP", season = "DJF", fade = true;
  var show = { borders: true, rivers: true, places: true };
  var marked = null;
  // The relief is the opening basemap because it is the only one that is
  // already in the file. Imagery is a click away and says so; a page whose
  // first paint depends on a network round trip is a page that is sometimes
  // blank.
  var base = "relief", composite = true;
  var BASE = {};
  (function () {
    for (var i = 0; i < D.bases.length; i++) { BASE[D.bases[i].id] = D.bases[i]; }
  }());

  function X(lon) { return (lon - view.lon) / view.dpp + W / 2; }
  function Y(lat) { return (view.lat - lat) / view.dpp + H / 2; }
  function lonAt(x) { return (x - W / 2) * view.dpp + view.lon; }
  function latAt(y) { return view.lat - (y - H / 2) * view.dpp; }

  function clampView() {
    // The zoom-out limit depends on the window, so a rotate or a resize can
    // leave the view further out than the new window allows. Clamping here
    // rather than only in the zoom handler means every path that changes the
    // view - drag, key, resize, reset - lands inside the range.
    view.dpp = Math.max(D.tight, Math.min(widest(), view.dpp));
    // Latitude is clamped so the poles cannot be dragged into the middle of
    // the page; longitude is free and wraps, because the Pacific is the
    // subject here and a hard edge down the dateline would cut it in half.
    var half = (H / 2) * view.dpp;
    var lim = Math.max(0, 90 - half);
    if (view.lat > lim) { view.lat = lim; }
    if (view.lat < -lim) { view.lat = -lim; }
    while (view.lon > 180) { view.lon -= 360; }
    while (view.lon < -180) { view.lon += 360; }
  }

  function levelFor(dpp) {
    for (var i = 0; i < D.tolerances.length; i++) {
      if (D.tolerances[i] <= dpp) { return i; }
    }
    return D.tolerances.length - 1;
  }

  // -- packed geometry -------------------------------------------------------
  // Douglas-Peucker is hierarchical, so a level is a filter on one array
  // rather than an array of its own: keep every point whose digit is at most
  // the level asked for. Unpacked once per layer per level and kept.
  var geoCache = {};
  function geom(layer, level) {
    var key = layer + level;
    if (geoCache[key]) { return geoCache[key]; }
    var src = D[layer], out = [], i, j;
    for (i = 0; i < src.length; i++) {
      var parts = src[i][0].split(","), marks = src[i][1];
      var flat = [], x = 0, y = 0;
      var w = 1e9, e = -1e9, s = 1e9, n = -1e9;
      for (j = 0; j < marks.length; j++) {
        x += +parts[j * 2];
        y += +parts[j * 2 + 1];
        if (marks.charAt(j) <= level) {
          var lo = x / 100, la = y / 100;
          flat.push(lo, la);
          if (lo < w) { w = lo; }
          if (lo > e) { e = lo; }
          if (la < s) { s = la; }
          if (la > n) { n = la; }
        }
      }
      if (flat.length > 3) { out.push([flat, w, e, s, n]); }
    }
    geoCache[key] = out;
    return out;
  }

  // -- composite grids -------------------------------------------------------
  var gridCache = {};
  function axis(text) {
    var parts = text.split(","), out = [], i;
    for (i = 0; i < parts.length; i++) { out.push(+parts[i]); }
    return out;
  }
  function plane(name, sea, kind) {
    var key = name + sea + kind;
    if (gridCache[key]) { return gridCache[key]; }
    var v = D.grids[name];
    var rows = v.seasons[sea][kind].split("\n"), out = [], i, j;
    for (i = 0; i < rows.length; i++) {
      if (!rows[i]) { continue; }
      var cells = rows[i].split(","), row = [];
      for (j = 0; j < cells.length; j++) {
        row.push(cells[j] === "_" ? null : +cells[j] / v.scale);
      }
      out.push(row);
    }
    gridCache[key] = out;
    return out;
  }
  function axes(name) {
    var key = name + "@axes";
    if (!gridCache[key]) {
      gridCache[key] = [axis(D.grids[name].lats), axis(D.grids[name].lons)];
    }
    return gridCache[key];
  }

  // The full-scale end of the colour ramp, per variable. Wider than the
  // typical cell so the tails are not all one colour, narrow enough that the
  // middle of the distribution is not all neutral grey.
  var LIMIT = { PRECIP: 3.0, AIR: 1.6 };

  function rampIndex(value, name) {
    // Rainfall is negated before it is mapped. The ramp runs blue to red,
    // which is right for temperature and backwards for rain, where the dry
    // end is the one that should read warm.
    var v = D.grids[name].invert ? -value : value;
    var lim = LIMIT[name];
    var i = Math.floor((v + lim) / (2 * lim) * 11);
    return i < 0 ? 0 : (i > 10 ? 10 : i);
  }

  function nearestIndex(values, target) {
    // The axis is regular but the direction is not guaranteed, and a cell is
    // claimed by the point nearest its centre either way.
    var best = 0, bestd = 1e9, i;
    for (i = 0; i < values.length; i++) {
      var d = Math.abs(values[i] - target);
      if (d < bestd) { bestd = d; best = i; }
    }
    return bestd > 4 ? -1 : best;
  }

  function nearestLon(values, target) {
    // The short way round: 359.87 is 0.38 from 0.25, not 358.62.
    var best = 0, bestd = 1e9, i;
    for (i = 0; i < values.length; i++) {
      var d = Math.abs(((values[i] - target + 540) % 360) - 180);
      if (d < bestd) { bestd = d; best = i; }
    }
    return bestd > 4 ? -1 : best;
  }

  function sample(name, sea, lon, lat) {
    var ax = axes(name), lats = ax[0], lons = ax[1];
    var east = ((lon % 360) + 360) % 360;
    var r = nearestIndex(lats, lat), c = nearestLon(lons, east);
    if (r < 0 || c < 0) { return null; }
    var dy = Math.abs(lats.length > 1 ? lats[1] - lats[0] : 2) / 2;
    var dx = Math.abs(lons.length > 1 ? lons[1] - lons[0] : 2) / 2;
    return {
      value: plane(name, sea, "diff")[r][c],
      base: plane(name, sea, "base")[r][c],
      t: plane(name, sea, "t")[r][c],
      lat0: lats[r] - dy, lat1: lats[r] + dy,
      lon0: lons[c] - dx, lon1: lons[c] + dx
    };
  }

  /*FIELD*/

  // -- drawing ---------------------------------------------------------------
  function offsets() {
    // Longitudes are stored once in -180..180, so anything within reach of a
    // seam is drawn again a turn away - once per turn the view spans, which at
    // the widest zoom on a tall window is more than one. The bounding boxes
    // cull almost all of it, so the extra passes cost nothing.
    var halfspan = (W / 2) * view.dpp;
    var lo = Math.floor((view.lon - halfspan + 180) / 360);
    var hi = Math.floor((view.lon + halfspan + 180) / 360);
    var out = [];
    for (var k = lo; k <= hi; k++) { out.push(k * 360); }
    return out.length ? out : [0];
  }

  // What the t test does not pass is drawn at a sixth of its strength while
  // "Fade below 95%" is on: the map's significance mask, the same 0.16.
  var FAINT = 0.16;
  var ramp = null;            // the ramp as numbers, read from the page tokens
  // The field at its own resolution, drawn up to the page's with smoothing.
  var fieldShot = null, fieldImage = null;

  function readRamp() {
    var cs = getComputedStyle(document.documentElement), out = [], i;
    for (i = 0; i < 11; i++) { out.push(hexRgb(cs.getPropertyValue("--d" + i))); }
    return out;
  }

  function fieldGrid(name, sea) {
    var key = name + sea + "@field";
    if (!gridCache[key]) {
      var ax = axes(name);
      gridCache[key] = fieldOf(ax[0], ax[1], plane(name, sea, "diff"),
                               plane(name, sea, "t"), crit(sea, name));
    }
    return gridCache[key];
  }

  // The field over a page w by h css pixels: a point every `step` of them on
  // the lattice fixed at longitude 0 and the equator, at its own longitude
  // and latitude, and nothing beyond the poles, where a plate carree window
  // taller than the world has only the page. x and y are where it starts.
  function atlasField(name, sea, mask, w, h, step, rgb, into) {
    var x0 = fieldStart(X(0), step), y0 = fieldStart(Y(0), step);
    var fw = fieldSpan(w, step), fh = fieldSpan(h, step);
    var lons = new Float64Array(fw), lats = new Float64Array(fh), i, j;
    for (i = 0; i < fw; i++) { lons[i] = lonAt(x0 + (i + 0.5) * step); }
    for (j = 0; j < fh; j++) {
      var lat = latAt(y0 + (j + 0.5) * step);
      lats[j] = (lat > 90 || lat < -90) ? NaN : lat;
    }
    var f = paintField(fieldGrid(name, sea), lons, lats,
      { invert: D.grids[name].invert, lim: LIMIT[name], rgb: rgb, mask: mask,
        dim: FAINT }, into);
    f.x = x0;
    f.y = y0;
    return f;
  }

  function drawField() {
    if (!composite) { return; }
    var dpr = window.devicePixelRatio || 1;
    var cw = Math.round(W * dpr), ch = Math.round(H * dpr);
    if (fieldCanvas.width !== cw || fieldCanvas.height !== ch) {
      fieldCanvas.width = cw;
      fieldCanvas.height = ch;
    }
    // Held to the page the map was measured at, as the relief is: left to the
    // stylesheet's 100%, it stretched with the map's box when the bar above
    // re-wrapped, and the field slid off the coastlines under it.
    fieldCanvas.style.width = W + "px";
    fieldCanvas.style.height = H + "px";
    var ctx = fieldCanvas.getContext("2d");
    ctx.clearRect(0, 0, cw, ch);
    if (!ramp) { ramp = readRamp(); }
    var step = fieldStep(W, H);
    var f = atlasField(variable, season, fade, W, H, step, ramp,
                       fieldImage ? fieldImage.data : null);
    if (!fieldShot) { fieldShot = document.createElement("canvas"); }
    if (!fieldImage || fieldImage.data !== f.data || fieldImage.width !== f.w) {
      fieldShot.width = f.w;
      fieldShot.height = f.h;
      fieldImage = new ImageData(f.data, f.w, f.h);
    }
    fieldShot.getContext("2d").putImageData(fieldImage, 0, 0);
    // Past the point where one cell is most of the screen, the composite
    // stops being a map and becomes a wall. It is not wrong - the composite
    // really has no more resolution than this - but a reader zoomed in on a
    // city wants to see the city, so the colour yields and the geography
    // comes through it. A click still reads the whole cell, and the scale
    // bar still says how big that is.
    var lons = axes(variable)[1];
    var px = Math.abs(lons.length > 1 ? lons[1] - lons[0] : 2) / view.dpp;
    var weight = px < 90 ? 1 : Math.max(0.42, 1 - (px - 90) / 420);
    ctx.imageSmoothingEnabled = true;
    ctx.imageSmoothingQuality = "high";
    ctx.globalAlpha = weight;
    ctx.drawImage(fieldShot, f.x * dpr, f.y * dpr, f.w * step * dpr, f.h * step * dpr);
    ctx.globalAlpha = 1;
  }

  function pathFor(items, width, stroke, fill, extra) {
    var halfspan = (W / 2) * view.dpp, halfv = (H / 2) * view.dpp;
    var w = view.lon - halfspan, e = view.lon + halfspan;
    var s = view.lat - halfv, n = view.lat + halfv;
    var offs = offsets();
    var buf = [], i, j, k;
    for (i = 0; i < items.length; i++) {
      var it = items[i], flat = it[0];
      if (it[3] > n || it[4] < s) { continue; }
      for (k = 0; k < offs.length; k++) {
        var o = offs[k];
        if (it[1] + o > e || it[2] + o < w) { continue; }
        buf.push("M");
        for (j = 0; j < flat.length; j += 2) {
          buf.push(X(flat[j] + o).toFixed(1), " ", Y(flat[j + 1]).toFixed(1),
                   j + 2 < flat.length ? "L" : "");
        }
      }
    }
    if (!buf.length) { return ""; }
    return '<path d="' + buf.join("") + '" fill="' + fill + '" stroke="'
      + stroke + '" stroke-width="' + width + '" stroke-linejoin="round"'
      + (extra || "") + "/>";
  }

  function drawVectors() {
    var level = String(levelFor(view.dpp));
    var buf = [];
    // Land first so the sea colour is the page behind it, then water bodies,
    // then borders, then the coast again as a thin line on top - a river that
    // runs under a border reads as one interrupted line otherwise.
    buf.push(pathFor(geom("coast", level), 0.9, "var(--ink)", "none",
                     ' opacity=".55"'));
    if (show.rivers) {
      buf.push(pathFor(geom("lakes", level), 0.7, "var(--riv)", "var(--riv)",
                       ' opacity=".55"'));
      buf.push(pathFor(geom("rivers", level), 0.9, "var(--riv)", "none",
                       ' opacity=".75" stroke-linecap="round"'));
    }
    if (show.borders) {
      buf.push(pathFor(geom("borders", level), 0.7, "var(--ink2)", "none",
                       ' opacity=".42" stroke-dasharray="3 2"'));
    }
    gVec.innerHTML = buf.join("");
  }

  function drawPoints() {
    var buf = [], i;
    var halfspan = (W / 2) * view.dpp, halfv = (H / 2) * view.dpp;
    var w = view.lon - halfspan, e = view.lon + halfspan;
    var s = view.lat - halfv, n = view.lat + halfv;
    var offs = offsets();
    // Labels are placed greedily and a candidate that lands on one already
    // placed is dropped. Without this the world view is a grey smear of
    // overlapping type around the Rhine and the Yangtze, and the cities that
    // matter are the ones buried. One registry covers the whole layer, so a
    // city and a cyclone cannot be printed over each other either.
    var taken = [];
    var fits = function (x0, y0, x1, y1) {
      for (var q = 0; q < taken.length; q++) {
        var b = taken[q];
        if (x0 < b[2] && x1 > b[0] && y0 < b[3] && y1 > b[1]) {
          return false;
        }
      }
      taken.push([x0, y0, x1, y1]);
      return true;
    };

    // Storms claim their space before any city does, and keep it whatever the
    // population of what they are over. An active cyclone is the most
    // perishable thing on this map; a city name is not worth hiding it behind.
    var stormAt = [];
    for (i = 0; i < D.storms.length; i++) {
      var s0 = D.storms[i], sx0 = null, o0;
      for (o0 = 0; o0 < offs.length; o0++) {
        var cand = X(s0.lon + offs[o0]);
        if (cand >= -20 && cand <= W + 20) { sx0 = cand; }
      }
      if (sx0 === null) { stormAt.push(null); continue; }
      var sy0 = Y(s0.lat), swide = textWidth(s0.name);
      var sright = sx0 + 10 + swide < W - 3;
      var sbox = sright ? [sx0 - 7, sy0 - 8.5, sx0 + 10 + swide, sy0 + 7.5]
                        : [sx0 - 10 - swide, sy0 - 8.5, sx0 + 7, sy0 + 7.5];
      var snamed = sbox[0] > 3 && sbox[2] < W - 3
        && fits(sbox[0], sbox[1], sbox[2], sbox[3]);
      // A storm that loses its name still keeps the ground under its dot.
      if (!snamed) { fits(sx0 - 7, sy0 - 7, sx0 + 7, sy0 + 7); }
      stormAt.push({ x: sx0, y: sy0, right: sright, named: snamed });
    }

    if (show.places) {
      var floor = D.floors[levelFor(view.dpp)];
      var shown = 0;
      for (i = 0; i < D.places.length && shown < 300; i++) {
        var p = D.places[i];
        if (p[3] < floor) { continue; }
        if (p[5] < s || p[5] > n) { continue; }
        var lon = null, k;
        for (k = 0; k < offs.length; k++) {
          if (p[4] + offs[k] >= w && p[4] + offs[k] <= e) {
            lon = p[4] + offs[k];
          }
        }
        if (lon === null) { continue; }
        shown++;
        // Radius on a log of population, because the range is Tokyo to a town
        // of four thousand and a linear scale draws all but six of them as a
        // point. Area, not radius, carries the number.
        var r = Math.max(2.1, Math.min(7,
          1.7 + 1.5 * Math.log(Math.max(p[3], 1000) / 8000) / Math.LN10));
        var x = X(lon).toFixed(1), y = Y(p[5]).toFixed(1);
        var wide = textWidth(p[0]), ly = Y(p[5]);
        // A name that would run off the right edge goes on the left of its dot
        // instead, and only gives up if that runs off too. The panel crops the
        // map, so the edge is a hard one: a label half-hidden behind it reads as
        // a different city than the one it names.
        var lx = X(lon) + r + 4, anchor = "start";
        if (lx + wide > W - 3) {
          lx = X(lon) - r - 4;
          anchor = "end";
        }
        // The drawn text is 14.7px tall on an 11px stack with the halo, sitting
        // on a baseline 3.6 below the dot, so the box is 8.5 up and 7.5 down.
        var box = anchor === "start"
          ? [lx - r - 5, ly - 8.5, lx + wide, ly + 7.5]
          : [lx - wide, ly - 8.5, lx + r + 5, ly + 7.5];
        var named = box[0] > 3 && box[2] < W - 3 && box[1] > 3 && box[3] < H - 3
          && fits(box[0], box[1], box[2], box[3]);
        // A dot whose name did not fit stays, faintly. It still says a city is
        // there, which is what a reader checking whether a dry cell has anyone
        // in it needs; it just stops competing with the ones that are named.
        buf.push('<circle cx="', x, '" cy="', y, '" r="',
                 (named ? r : Math.min(r, 2.6)).toFixed(1),
                 '" fill="var(--ink)" fill-opacity="', named ? ".62" : ".22",
                 named ? '" stroke="var(--surface)" stroke-width="1.4"/>'
                       : '"/>');
        if (p[6] && named) {
          buf.push('<circle cx="', x, '" cy="', y, '" r="', (r + 2.6).toFixed(1),
                   '" fill="none" stroke="var(--ink)" stroke-opacity=".5"',
                   ' stroke-width="1"/>');
        }
        if (named) {
          buf.push('<text class="plab" x="', lx.toFixed(1),
                   '" y="', (ly + 3.6).toFixed(1),
                   anchor === "end" ? '" text-anchor="end">' : '">',
                   esc(p[0]), "</text>");
        }
      }
    }
    for (i = 0; i < D.storms.length; i++) {
      var st = D.storms[i], j, o;
      for (o = 0; o < offs.length; o++) {
        // A storm gets drawn once per wrap of the world that is on screen, and
        // the track can be long, so the copy whose current position is nowhere
        // near the window is skipped rather than drawn and clipped.
        var sx = X(st.lon + offs[o]);
        if (sx < -W || sx > 2 * W) { continue; }
        var seg = [];
        for (j = 0; j < st.track.length; j++) {
          seg.push(X(st.track[j][0] + offs[o]).toFixed(1), " ",
                   Y(st.track[j][1]).toFixed(1), j + 1 < st.track.length ? "L" : "");
        }
        if (seg.length) {
          buf.push('<path d="M', seg.join(""), '" fill="none" stroke="var(--s2)"',
                   ' stroke-width="2" stroke-linecap="round"/>');
        }
        var fx = [];
        for (j = 0; j < st.forecast.length; j++) {
          fx.push(X(st.forecast[j][0] + offs[o]).toFixed(1), " ",
                  Y(st.forecast[j][1]).toFixed(1), j + 1 < st.forecast.length ? "L" : "");
        }
        if (fx.length) {
          buf.push('<path d="M', fx.join(""), '" fill="none" stroke="var(--s2)"',
                   ' stroke-width="2" stroke-dasharray="5 4" opacity=".8"/>');
        }
      }
      // The track of a wrap copy can cross the window while the storm itself
      // sits outside it, so the lines are drawn per wrap above and the marker
      // once, at the position reserved before the cities were placed.
      var at = stormAt[i];
      if (!at) { continue; }
      buf.push('<circle cx="', at.x.toFixed(1), '" cy="', at.y.toFixed(1),
               '" r="6" fill="var(--s2)"',
               ' stroke="var(--surface)" stroke-width="2"/>');
      if (at.named) {
        buf.push('<text class="plab slab" x="',
                 (at.right ? at.x + 10 : at.x - 10).toFixed(1),
                 '" y="', (at.y + 3.6).toFixed(1),
                 at.right ? '">' : '" text-anchor="end">', esc(st.name),
                 "</text>");
      }
    }
    gPt.innerHTML = buf.join("");
  }

  function drawMark() {
    if (!marked) { gPick.innerHTML = ""; return; }
    // The cell, not a pin. A click is answered with the cell it landed in and
    // that cell's footprint is the honest size of the answer. Its west edge is
    // taken beside the point, so a cell across the date line is outlined where
    // it is rather than the long way round the world; it is outlined while any
    // of it is on the page, whether or not its point is; and a cell wider or
    // taller than the page is not outlined at all, because all that is left of
    // its outline on screen is a lone dashed line or two.
    var b = marked.box, wide = 0, tall = 0, west = 0;
    if (b) {
      wide = ((b[1] - b[0]) % 360 + 360) % 360 / view.dpp;
      tall = Math.abs(Y(b[2]) - Y(b[3]));
      west = b[0] - 360 * Math.round((b[0] - marked.lon) / 360);
    }
    var outline = b && wide <= W && tall <= H;
    // A turn either side of the ones the view spans as well: a point just past
    // the page's edge, or its cell, can lie across the date line from it.
    var offs = offsets(), buf = [], k;
    offs = [offs[0] - 360].concat(offs, [offs[offs.length - 1] + 360]);
    for (k = 0; k < offs.length; k++) {
      var left = X(west + offs[k]);
      if (outline && left < W && left + wide > 0) {
        buf.push('<rect x="', left.toFixed(1), '" y="', Y(b[3]).toFixed(1),
                 '" width="', wide.toFixed(1), '" height="', tall.toFixed(1),
                 '" fill="none" stroke="var(--ink)" stroke-width="1.6"',
                 ' stroke-dasharray="4 3"/>');
      }
      var x = X(marked.lon + offs[k]), y = Y(marked.lat);
      if (x >= -40 && x <= W + 40) {
        buf.push('<circle cx="', x.toFixed(1), '" cy="', y.toFixed(1),
                 '" r="4.5" fill="var(--ink)" stroke="var(--surface)"',
                 ' stroke-width="2"/>');
      }
    }
    gPick.innerHTML = buf.join("");
  }

  function drawScale() {
    // Kilometres, measured at the middle of the view: a plate carree page has
    // no single scale, and the one the reader is looking at is this one.
    var kmPerPx = view.dpp * 111.32 * Math.cos(view.lat * Math.PI / 180);
    var target = kmPerPx * 130;
    var pow = Math.pow(10, Math.floor(Math.log(target) / Math.LN10));
    var nice = pow;
    var steps = [1, 2, 5, 10];
    for (var i = 0; i < steps.length; i++) {
      nice = steps[i] * pow;
      if (nice >= target) { break; }
    }
    var px = nice / kmPerPx;
    var label = nice >= 1 ? Math.round(nice) + " km"
      : Math.round(nice * 1000) + " m";
    // The cell size beside the scale, always. It is the resolution of every
    // number this page reports, and a reader zoomed to a street has a right to
    // know the answer they are about to click on is 280 kilometres wide.
    var ax = axes(variable);
    var step = Math.abs(ax[1].length > 1 ? ax[1][1] - ax[1][0] : 2.5);
    var cell = Math.round(step * 111.32 * Math.cos(view.lat * Math.PI / 180));
    scalebox.innerHTML = '<b class="bar" style="width:' + px.toFixed(0)
      + 'px"></b>' + label + ' · one cell ≈ ' + cell + ' km';
  }

  var pending = 0;
  // -- the solid Earth -------------------------------------------------------
  // A composite drawn over a coastline says where a difference lands. It does
  // not say what it lands on, and a rainfall deficit over the Sunda Shelf and
  // the same deficit over the Barisan range are not the same event. So the
  // ground goes under the data: ETOPO1 at a quarter degree, shaded, from a
  // PNG in the file rather than from a tile server.
  var R = D.relief;
  var elev = null;            // Int16Array, metres, south-north then west-east
  var reliefShot = null;      // the ImageData we paint into, kept across frames
  var tone = null;            // the two base colours, read from the page tokens
  var imageryFailed = false;

  (function loadRelief() {
    var img = new Image();
    img.onload = function () {
      var off = document.createElement("canvas");
      off.width = R.nx;
      off.height = 2 * R.ny;
      var g = off.getContext("2d");
      g.drawImage(img, 0, 0);
      // The two planes are stacked, high byte above low, because eight bits a
      // channel is all getImageData will ever hand back whatever the PNG's
      // declared depth. Split this way the sixteen bits arrive intact.
      var px = g.getImageData(0, 0, R.nx, 2 * R.ny).data;
      var n = R.ny * R.nx, out = new Int16Array(n), i;
      for (i = 0; i < n; i++) {
        out[i] = ((px[i * 4] << 8) | px[(n + i) * 4]) - R.offset;
      }
      elev = out;
      schedule();
    };
    img.onerror = function () { elev = null; };
    img.src = RELIEF;
  }());

  function elevAt(lon, lat) {
    if (!elev) { return null; }
    var l = lon - 360 * Math.floor((lon + 180) / 360);
    var y = Math.round((lat - R.lat0) / R.step);
    var x = Math.round((l - R.lon0) / R.step);
    if (y < 0) { y = 0; }
    if (y > R.ny - 1) { y = R.ny - 1; }
    if (x < 0) { x = 0; }
    if (x > R.nx - 1) { x = R.nx - 1; }
    return elev[y * R.nx + x];
  }

  function rgbOf(name) {
    return hexRgb(getComputedStyle(document.documentElement).getPropertyValue(name));
  }
  function tones() {
    if (tone) { return tone; }
    var sea = rgbOf("--sea"), land = rgbOf("--land");
    // Which way height should push the colour depends on which end of the
    // page we are on. On a dark surface a mountain has to get lighter to be
    // seen at all; on a light one it has to get darker. Reading the sea token
    // rather than the media query means the manual theme button counts too.
    var dark = sea[0] + sea[1] + sea[2] < 330;
    // The far ends: where a colour has gone by four kilometres up or six
    // kilometres down. The near end is the page's own sea and land token, so
    // a shelf and a coastal plain still match the flat map they replaced, and
    // only the parts with relief in them depart from it.
    tone = {
      sea: sea, land: land, off: rgbOf("--surface"),
      seaFar: dark ? [7, 11, 15] : [134, 146, 158],
      landFar: dark ? [74, 70, 62] : [152, 145, 132],
      amp: dark ? 74 : 96
    };
    return tone;
  }

  // Sun from the north-west at 45 degrees, the cartographic convention: lit
  // from anywhere else and every reader reads the valleys as ridges.
  var SUN = [-0.5, 0.5, 0.7071];
  var EXAG = 5;               // vertical exaggeration
  var MLAT = 110574;          // metres in a degree of latitude, near enough

  function drawRelief() {
    var on = base === "relief" && elev !== null;
    reliefCanvas.style.display = on ? "block" : "none";
    if (!on) { return; }
    // A hillshade is four grid reads and a square root per pixel, so it is
    // computed at a capped resolution and stretched. The eye cannot resolve a
    // one-pixel shadow on a 28 km cell anyway, and this keeps a full-screen
    // redraw inside a frame on a laptop.
    var q = Math.min(1, Math.sqrt(900000 / (W * H)));
    var cw = Math.max(1, Math.round(W * q)), ch = Math.max(1, Math.round(H * q));
    if (reliefCanvas.width !== cw || reliefCanvas.height !== ch
        || !reliefShot) {
      reliefCanvas.width = cw;
      reliefCanvas.height = ch;
      reliefShot = null;
    }
    reliefCanvas.style.width = W + "px";
    reliefCanvas.style.height = H + "px";
    var ctx = reliefCanvas.getContext("2d");
    if (!reliefShot) { reliefShot = ctx.createImageData(cw, ch); }
    var out = reliefShot.data;
    var T = tones(), nx = R.nx, ny = R.ny, step = R.step;
    var p = 0, cx, cy;
    for (cy = 0; cy < ch; cy++) {
      var lat = latAt((cy + 0.5) / q);
      var gy = Math.round((lat - R.lat0) / step);
      if (gy < 0) { gy = 0; }
      if (gy > ny - 1) { gy = ny - 1; }
      var north = gy + 1 < ny ? gy + 1 : gy;
      var south = gy > 0 ? gy - 1 : gy;
      var spanY = (north - south) * step * MLAT;
      var cosLat = Math.cos(lat * Math.PI / 180);
      if (cosLat < 0.08) { cosLat = 0.08; }
      var spanX = 2 * step * 111320 * cosLat;
      var rowHere = gy * nx, rowN = north * nx, rowS = south * nx;
      for (cx = 0; cx < cw; cx++) {
        var lon = lonAt((cx + 0.5) / q);
        lon -= 360 * Math.floor((lon + 180) / 360);
        var gx = Math.round((lon - R.lon0) / step);
        if (gx < 0) { gx = 0; }
        if (gx > nx - 1) { gx = nx - 1; }
        var east = gx + 1 < nx ? gx + 1 : 0;
        var west = gx > 0 ? gx - 1 : nx - 1;
        var here = elev[rowHere + gx];
        var zx = (elev[rowHere + east] - elev[rowHere + west]) / spanX * EXAG;
        var zy = (elev[rowN + gx] - elev[rowS + gx]) / spanY * EXAG;
        var shade = (SUN[0] * -zx + SUN[1] * -zy + SUN[2])
          / Math.sqrt(zx * zx + zy * zy + 1);
        if (shade < 0) { shade = 0; }
        var wet = here <= 0;
        var b = wet ? T.sea : T.land;
        var f = wet ? T.seaFar : T.landFar;
        var far = wet ? Math.min(1, -here / 6000) : Math.min(1, here / 4000);
        // Gamma on the depth ramp: half the ocean is between three and five
        // kilometres down, so a linear ramp spends its whole range on water
        // that all looks the same and has nothing left for a shelf edge.
        far = wet ? Math.sqrt(far) : far;
        // The sea floor is shaded more gently than the land. Its relief is
        // real and worth seeing - ridges, trenches, the edge of a shelf - but
        // at land strength an abyssal plain turns into grain, and grain under
        // a blue rainfall cell is the one place this map cannot afford it.
        var k = (shade - 0.58) * T.amp * (wet ? 0.72 : 1);
        var r = b[0] + (f[0] - b[0]) * far + k;
        var g2 = b[1] + (f[1] - b[1]) * far + k;
        var bl = b[2] + (f[2] - b[2]) * far + k;
        out[p] = r < 0 ? 0 : (r > 255 ? 255 : r);
        out[p + 1] = g2 < 0 ? 0 : (g2 > 255 ? 255 : g2);
        out[p + 2] = bl < 0 ? 0 : (bl > 255 ? 255 : bl);
        // Beyond the poles there is no planet, only the page: a plate carree
        // window taller than 180 degrees has real space above and below the
        // world, and filling it with the colour of the last row drawn would
        // invent an Arctic Ocean that runs to the top of the screen.
        if (lat > 90 || lat < -90) {
          out[p] = T.off[0];
          out[p + 1] = T.off[1];
          out[p + 2] = T.off[2];
        }
        out[p + 3] = 255;
        p += 4;
      }
    }
    ctx.putImageData(reliefShot, 0, 0);
  }

  // -- imagery ---------------------------------------------------------------
  // GIBS publishes in EPSG:4326, which is the projection already on the page,
  // so a tile is a rectangle in degrees and goes where the arithmetic says.
  // Level z is 2^(z+1) columns by 2^z rows of 512 pixels, each one 180/2^z
  // degrees square.
  var tileCache = {};
  // Degrees across one 512-pixel tile at the top of the GIBS 4326 pyramid.
  var TOP = 288;

  function drawTiles() {
    var cfg = BASE[base];
    if (!cfg || cfg.kind !== "gibs") {
      if (tileBox.firstChild) { tileBox.textContent = ""; tileCache = {}; }
      tileBox.style.display = "none";
      return;
    }
    tileBox.style.display = "block";
    // GIBS's EPSG:4326 pyramid does not start at the world. Its top level is
    // 288 degrees to a 512-pixel tile, halving from there, so two tiles cover
    // 576 degrees of a 360-degree planet and the far column and bottom row are
    // padded with black. Assuming the obvious 180-degree top level puts every
    // tile above level zero in the wrong place at the wrong size, which is
    // what the first build of this did.
    var z = Math.round(Math.log(TOP / 512 / view.dpp) / Math.LN2);
    if (z < 0) { z = 0; }
    if (z > cfg.max) { z = cfg.max; }
    var span = TOP / Math.pow(2, z);
    var cols = Math.ceil(360 / span), rows = Math.ceil(180 / span);
    var side = span / view.dpp;
    var lonW = lonAt(0), lonE = lonAt(W);
    var ty0 = Math.floor((90 - latAt(0)) / span);
    var ty1 = Math.floor((90 - latAt(H)) / span);
    if (ty0 < 0) { ty0 = 0; }
    if (ty1 > rows - 1) { ty1 = rows - 1; }
    var kFirst = Math.floor((lonW + 180) / 360);
    var kLast = Math.floor((lonE + 180) / 360);
    var stem = D.gibs + "/" + cfg.layer + "/default/"
      + (cfg.date ? cfg.date + "/" : "") + cfg.tms + "/" + z + "/";
    var want = {}, k, tx, ty;
    for (k = kFirst; k <= kLast; k++) {
      // One whole copy of the world per wrap, indexed from its own -180.
      // Tile columns cannot be taken modulo the matrix width the way a
      // power-of-two scheme allows, because the last column is not a whole
      // tile of planet.
      var off = 360 * k;
      var tx0 = Math.floor((lonW - off + 180) / span);
      var tx1 = Math.floor((lonE - off + 180) / span);
      if (tx0 < 0) { tx0 = 0; }
      if (tx1 > cols - 1) { tx1 = cols - 1; }
      for (ty = ty0; ty <= ty1; ty++) {
        for (tx = tx0; tx <= tx1; tx++) {
          var key = cfg.id + ":" + z + ":" + k + ":" + ty + ":" + tx;
          var img = tileCache[key];
          if (!img) {
            img = new Image();
            img.alt = "";
            img.decoding = "async";
            img.onerror = onTileMiss;
            img.src = stem + ty + "/" + tx + "." + cfg.ext;
            tileCache[key] = img;
            tileBox.appendChild(img);
          }
          var lon0 = -180 + tx * span, lat0 = 90 - ty * span;
          // A pixel of bleed on three sides. Neighbouring tiles land on
          // fractional boundaries and the browser antialiases each edge
          // against the page, so an exact fit leaves a hairline that reads as
          // a crack in the Earth. The worst of those is down the antimeridian,
          // where a clipped tile meets the first column of the next copy of
          // the world; the bleed to the west is what closes that one.
          var wpx = side + 2, hpx = side + 1;
          img.style.left = (X(lon0 + off) - 1) + "px";
          img.style.top = Y(lat0) + "px";
          img.style.width = wpx + "px";
          img.style.height = hpx + "px";
          // Crop the padding off the tiles that hang over the edge of the
          // world, or the map ends in a black margin east of 180 and south of
          // the pole that looks like missing data rather than no planet. The
          // cut is at the true edge, so it takes the bleed back off again.
          var fx = Math.min(span, 180 - lon0) / span;
          var fy = Math.min(span, lat0 + 90) / span;
          var right = fx >= 1 ? 0 : Math.max(0, wpx - 1 - fx * side);
          var below = fy >= 1 ? 0 : Math.max(0, hpx - fy * side);
          img.style.clipPath = (right || below)
            ? "inset(0px " + right + "px " + below + "px 0px)" : "";
          want[key] = 1;
        }
      }
    }
    var keys = Object.keys(tileCache), n;
    for (n = 0; n < keys.length; n++) {
      if (!want[keys[n]]) {
        var stale = tileCache[keys[n]];
        if (stale.parentNode) { stale.parentNode.removeChild(stale); }
        delete tileCache[keys[n]];
      }
    }
  }

  function onTileMiss() {
    this.style.display = "none";
    // One missing tile is a gap in a mosaic - polar night, a satellite swath
    // that has not landed yet. A page that cannot reach the server at all is
    // a different thing and the reader should be told which one they have,
    // rather than left looking at an empty rectangle.
    if (!navigator.onLine && !imageryFailed) {
      imageryFailed = true;
      describeBase();
    }
  }

  function applyComposite() {
    var cfg = BASE[base];
    fieldCanvas.style.display = composite ? "" : "none";
    // The composite is the data and everything under it is context, so it
    // gives way as little as it can and no less. Over a photograph it has to
    // give way a lot, or it hides the ground it is there to explain. Over the
    // shaded relief, which is grey and quiet, a touch is enough to let a
    // mountain range read through a significant cell.
    fieldCanvas.style.opacity = !cfg ? "1"
      : (cfg.kind === "gibs" ? "0.58" : "0.82");
  }

  function describeBase() {
    var cfg = BASE[base];
    var slot = document.getElementById("source");
    if (!cfg) {
      creditPill.hidden = true;
      slot.textContent = "";
      return;
    }
    var line = cfg.credit + (cfg.date ? ", " + cfg.date : "");
    if (cfg.scale) { line += " - " + cfg.scale; }
    if (cfg.kind === "gibs" && imageryFailed) {
      line += " - offline: imagery is the one layer that needs a network";
    }
    creditPill.textContent = line;
    creditPill.hidden = false;
    slot.textContent = cfg.note;
  }

  function render() {
    pan.setAttribute("transform", "translate(0,0)");
    reliefCanvas.style.transform = tileBox.style.transform =
      fieldCanvas.style.transform = "";
    drawRelief();
    drawTiles();
    applyComposite();
    drawField();
    drawVectors();
    drawPoints();
    drawMark();
    drawScale();
    pending = 0;
  }
  function schedule() {
    if (pending) { return; }
    pending = requestAnimationFrame(render);
  }

  function resize() {
    var r = map.getBoundingClientRect();
    W = Math.max(200, Math.round(r.width));
    H = Math.max(200, Math.round(r.height));
    svg.setAttribute("width", W);
    svg.setAttribute("height", H);
    svg.setAttribute("viewBox", "0 0 " + W + " " + H);
    if (!sized) { view.dpp = fitted(); sized = true; }
    clampView();
    schedule();
  }

  // -- interaction -----------------------------------------------------------
  // Every pointer on the map is kept: one finger pans, two pinch about the
  // point between them. Kept as one, a second finger restarted the drag from
  // itself and a pinch on a tablet panned the map instead.
  var sized = false;
  var drag = null, pinching = null;
  var pointers = new Map();
  function spot(ev) {
    var r = map.getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  }
  // A gesture moves what is already drawn rather than redrawing it: a million
  // hillshaded pixels, the vector map and forty tiles cannot be rebuilt at
  // sixty frames a second, and nothing about them or the composite changes
  // while the window slides or grows. The view itself moves when the gesture
  // ends.
  function preview(dx, dy, s) {
    var grow = s === 1 ? "" : " scale(" + s + ")";
    pan.setAttribute("transform", "translate(" + dx + "," + dy + ")" + grow);
    reliefCanvas.style.transformOrigin = tileBox.style.transformOrigin =
      fieldCanvas.style.transformOrigin = "0 0";
    reliefCanvas.style.transform = tileBox.style.transform =
      fieldCanvas.style.transform = "translate(" + dx + "px," + dy + "px)" + grow;
  }
  function startDrag(p) {
    drag = { x: p.x, y: p.y, dx: 0, dy: 0, moved: false };
  }
  function commitDrag() {
    if (drag && drag.moved) {
      view.lon -= drag.dx * view.dpp;
      view.lat += drag.dy * view.dpp;
      clampView();
      render();
    }
  }
  // The two fingers now against where they were: the point that was under
  // their midpoint stays under it, scaled by how far apart they have moved.
  function pinch() {
    var two = Array.from(pointers.values()).slice(0, 2);
    var mx = (two[0].x + two[1].x) / 2, my = (two[0].y + two[1].y) / 2;
    var gap = Math.max(1, Math.hypot(two[0].x - two[1].x, two[0].y - two[1].y));
    var next = Math.max(D.tight, Math.min(widest(), view.dpp * pinching.gap / gap));
    pinching.s = view.dpp / next;
    pinching.mx = mx; pinching.my = my;
    preview(mx - pinching.s * pinching.x, my - pinching.s * pinching.y, pinching.s);
  }
  function startPinch() {
    var two = Array.from(pointers.values()).slice(0, 2);
    pinching = { x: (two[0].x + two[1].x) / 2, y: (two[0].y + two[1].y) / 2,
                 gap: Math.max(1, Math.hypot(two[0].x - two[1].x, two[0].y - two[1].y)),
                 s: 1, mx: 0, my: 0 };
    pinching.mx = pinching.x; pinching.my = pinching.y;
  }
  function commitPinch() {
    var lon = lonAt(pinching.x), lat = latAt(pinching.y);
    view.dpp = view.dpp / pinching.s;
    view.lon = lon - (pinching.mx - W / 2) * view.dpp;
    view.lat = lat + (pinching.my - H / 2) * view.dpp;
    pinching = null;
    clampView();
    render();
  }
  // A press on the zoom buttons, which sit on the map, is theirs: taken as the
  // start of a drag, its pointer was captured, its click went to the map, and
  // +, - and Fit did nothing.
  function grab(ev) {
    if (ev.button !== 0 || ev.target.closest(".atlaszoom")) { return; }
    pointers.set(ev.pointerId, spot(ev));
    try { map.setPointerCapture(ev.pointerId); } catch (err) { /* synthetic */ }
    map.classList.add("dragging");
    if (pointers.size === 2) {
      commitDrag();
      drag = null;
      startPinch();
    } else if (pointers.size === 1) {
      startDrag(spot(ev));
    }
  }
  map.addEventListener("pointerdown", grab);
  map.addEventListener("pointermove", function (ev) {
    var p = spot(ev);
    if (pointers.has(ev.pointerId)) { pointers.set(ev.pointerId, p); }
    if (pinching) { pinch(); return; }
    if (drag && pointers.has(ev.pointerId)) {
      drag.dx = p.x - drag.x;
      drag.dy = p.y - drag.y;
      if (Math.abs(drag.dx) + Math.abs(drag.dy) > 3) { drag.moved = true; }
      preview(drag.dx, drag.dy, 1);
      return;
    }
    readAt(p);
  });
  // Where the pointer is; beyond the poles, where a window taller than the
  // world has only the page, nowhere, as before the pointer came.
  function readAt(p) {
    var lat = latAt(p.y);
    readout.textContent = lat > 90 || lat < -90 ? "—"
      : fmtLat(lat) + "  " + fmtLon(lonAt(p.x));
  }
  function lift(ev, cancelled) {
    if (!pointers.has(ev.pointerId)) { return; }
    pointers.delete(ev.pointerId);
    if (pinching) {
      commitPinch();
      // Fingers still down carry on from where they are: two pinch afresh,
      // one pans, and lifting it later ends a gesture rather than clicking.
      if (pointers.size >= 2) {
        startPinch();
      } else if (pointers.size === 1) {
        startDrag(Array.from(pointers.values())[0]);
        drag.moved = true;
      } else {
        map.classList.remove("dragging");
      }
      return;
    }
    if (pointers.size || !drag) { return; }
    map.classList.remove("dragging");
    var moved = drag.moved;
    if (moved) {
      view.lon -= drag.dx * view.dpp;
      view.lat += drag.dy * view.dpp;
      clampView();
      schedule();
    }
    drag = null;
    // A tap beyond the poles, where a window taller than the world has only
    // the page, is a tap on nothing.
    if (!moved && !cancelled) {
      var p = spot(ev), lat = latAt(p.y);
      if (lat >= -90 && lat <= 90) { pick(lonAt(p.x), lat); }
    }
  }
  map.addEventListener("pointerup", function (ev) { lift(ev, false); });
  map.addEventListener("pointercancel", function (ev) { lift(ev, true); });

  map.addEventListener("wheel", function (ev) {
    ev.preventDefault();
    var r = map.getBoundingClientRect();
    var mx = ev.clientX - r.left, my = ev.clientY - r.top;
    zoomAbout(Math.exp((ev.deltaY > 0 ? 1 : -1) * -0.22), mx, my);
  }, { passive: false });

  function zoomAbout(factor, mx, my) {
    var lon = lonAt(mx), lat = latAt(my);
    var next = view.dpp / factor;
    next = Math.max(D.tight, Math.min(widest(), next));
    if (next === view.dpp) { return; }
    view.dpp = next;
    // Hold the point under the cursor still: the reader is zooming into
    // something, and a zoom that recentres on the middle of the page moves it
    // out from under them.
    view.lon = lon - (mx - W / 2) * view.dpp;
    view.lat = lat + (my - H / 2) * view.dpp;
    clampView();
    schedule();
  }

  function zoomBy(factor) { zoomAbout(factor, W / 2, H / 2); }

  // -- the dossier -----------------------------------------------------------
  function haversine(lon1, lat1, lon2, lat2) {
    var R = 6371, rad = Math.PI / 180;
    var dlat = (lat2 - lat1) * rad, dlon = (lon2 - lon1) * rad;
    var a = Math.sin(dlat / 2) * Math.sin(dlat / 2)
      + Math.cos(lat1 * rad) * Math.cos(lat2 * rad)
      * Math.sin(dlon / 2) * Math.sin(dlon / 2);
    return 2 * R * Math.asin(Math.min(1, Math.sqrt(a)));
  }

  function neighbours(lon, lat, limit) {
    var out = [], i;
    for (i = 0; i < D.places.length; i++) {
      var p = D.places[i];
      // A cheap box first: a haversine for seven thousand places on every
      // click is a tenth of a second, and all but a handful are continents
      // away.
      if (Math.abs(p[5] - lat) > 22) { continue; }
      var dlon = Math.abs(((p[4] - lon + 540) % 360) - 180);
      if (dlon * Math.cos(lat * Math.PI / 180) > 25) { continue; }
      out.push([haversine(lon, lat, p[4], p[5]), p]);
    }
    out.sort(function (a, b) { return a[0] - b[0]; });
    return out.slice(0, limit);
  }

  function inBox(lon, lat, b) {
    return lon >= b[0] && lon <= b[1] && lat >= b[2] && lat <= b[3];
  }

  var SCOPE_ORDER = { regional: 0, basin: 1, global: 2 };
  function linksAt(lon, lat) {
    var out = [], i, j;
    var l = ((lon + 540) % 360) - 180;
    for (i = 0; i < D.links.length; i++) {
      var link = D.links[i];
      for (j = 0; j < link.boxes.length; j++) {
        if (inBox(l, lat, link.boxes[j])) { out.push(link); break; }
      }
    }
    // Narrowest first. A global entry is true of every click on the map, so it
    // belongs under the ones that are true of this one.
    out.sort(function (a, b) {
      return (SCOPE_ORDER[a.scope] || 0) - (SCOPE_ORDER[b.scope] || 0);
    });
    return out;
  }

  function fmtLat(v) {
    return Math.abs(v).toFixed(2) + "°" + (v < 0 ? "S" : "N");
  }
  function fmtLon(v) {
    var l = ((v + 540) % 360) - 180;
    return Math.abs(l).toFixed(2) + "°" + (l < 0 ? "W" : "E");
  }
  function esc(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }
  function signed(v, digits) {
    return (v > 0 ? "+" : v < 0 ? "−" : "")
      + Math.abs(v).toFixed(digits);
  }

  // The |t| a season must reach: Student's t at 95% for that season's own
  // sample. June to August has four events and September to November ten, so
  // one number for all four seasons would be too lax for one and too strict
  // for the other. A season with too few events to test has no bar at all.
  // The field's grids name their variable; everything else asks of the one
  // on the map.
  function crit(s, name) {
    var c = D.significant[name || variable][s];
    return (c === null || c === undefined) ? Infinity : c;
  }

  function verdict(cell) {
    if (cell === null || cell.value === null) { return "no record"; }
    if (cell.t === null || Math.abs(cell.t) < crit(season)) {
      return "no clear signal";
    }
    if (variable === "PRECIP") { return cell.value > 0 ? "wetter" : "drier"; }
    return cell.value > 0 ? "warmer" : "cooler";
  }

  // Any longitude into -180..180, as a click past the date line or
  // atlas.html#at=0,200 gives one: the mark is drawn a turn of the world at a
  // time about the view, and a point a turn away from them all was not drawn.
  function lon180(lon) { return ((lon + 180) % 360 + 360) % 360 - 180; }

  function pick(lon, lat) {
    lon = lon180(lon);
    var v = D.grids[variable];
    var cells = {}, i;
    for (i = 0; i < D.seasons.length; i++) {
      cells[D.seasons[i]] = sample(variable, D.seasons[i], lon, lat);
    }
    var here = cells[season];
    marked = { lon: lon, lat: lat,
               box: here ? [here.lon0, here.lon1, here.lat0, here.lat1] : null };
    drawMark();

    var near = neighbours(lon, lat, 6);
    var title, where;
    if (near.length && near[0][0] <= 25) {
      title = label(near[0][1]);
      where = fmtLat(lat) + "  " + fmtLon(lon);
    } else if (near.length && near[0][0] <= 400) {
      title = Math.round(near[0][0]) + " km from " + label(near[0][1]);
      where = fmtLat(lat) + "  " + fmtLon(lon);
    } else {
      title = fmtLat(lat) + ", " + fmtLon(lon);
      where = near.length ? "Nearest named place "
        + Math.round(near[0][0]) + " km away" : "Open ocean";
    }

    var buf = [];
    buf.push("<h2>", esc(title), "</h2>");
    buf.push('<p class="where">', esc(where), "</p>");

    if (!here || here.value === null) {
      buf.push('<p class="hint">No composite here. The rainfall grid covers ',
               "the world; the temperature grid is land only, so a click at ",
               "sea has no temperature to report.</p>");
    } else {
      var pct = (variable === "PRECIP" && here.base !== null
                 && here.base >= D.dry_floor)
        ? here.value / here.base * 100 : null;
      buf.push('<div class="big">', signed(here.value, 2),
               ' <span class="bigsub">', esc(v.unit), "</span></div>");
      // A percentage of a temperature would be arithmetic on an interval
      // scale, so only rainfall gets one; both get the ordinary year they are
      // a difference from, because the difference alone is unreadable.
      var normal = here.base === null ? "an ordinary year"
        : "an ordinary year’s " + here.base.toFixed(2) + " " + v.unit;
      buf.push('<p class="bigsub">', esc(D.season_label[season]), " · ",
               pct === null ? "against " + esc(normal)
                 : signed(pct, 0) + "% of " + esc(normal),
               " · <b>", esc(verdict(here)), "</b></p>");
      buf.push('<p class="bigsub">Welch <i>t</i> = ',
               here.t === null ? "n/a" : signed(here.t, 2),
               here.t !== null && Math.abs(here.t) >= crit(season)
                 ? " · distinguishable from an ordinary year"
                 : " · inside the noise", "</p>");
      buf.push('<h3>Every season here</h3>');
      buf.push("<table><thead><tr><th>Season</th><th></th>",
               '<th class="num">', esc(v.unit), '</th>',
               '<th class="num">t</th></tr></thead><tbody>');
      var lim = LIMIT[variable];
      for (i = 0; i < D.seasons.length; i++) {
        var s = D.seasons[i], cell = cells[s];
        var weak = !cell || cell.value === null || cell.t === null
          || Math.abs(cell.t) < crit(s);
        buf.push('<tr class="', weak ? "weak" : "", '">');
        buf.push("<td>", s, "</td>");
        if (!cell || cell.value === null) {
          buf.push('<td class="bar"></td><td class="num">—</td>',
                   '<td class="num">—</td></tr>');
          continue;
        }
        var frac = Math.max(-1, Math.min(1, cell.value / lim));
        // A quarter of a millimetre a day is a real number in the column
        // beside the bar, and at true scale it is a third of a pixel. Anything
        // that rounds to a printed value keeps a mark wide enough to see, so
        // the bar never contradicts the number it is drawn from.
        var w2 = Math.max(Math.abs(frac) * 50, cell.value === 0 ? 0 : 2.5);
        buf.push('<td class="bar"><span class="track"><u></u><i style="left:',
                 (frac < 0 ? 50 - w2 : 50).toFixed(1), "%;width:",
                 w2.toFixed(1), "%;background:var(--d",
                 rampIndex(cell.value, variable), ')"></i></span></td>');
        buf.push('<td class="num">', signed(cell.value, 2), "</td>");
        buf.push('<td class="num">',
                 cell.t === null ? "—" : signed(cell.t, 1), "</td></tr>");
      }
      buf.push("</tbody></table>");
      var m = v.meta[season];
      buf.push('<p class="note">Measured: ', m.warm_events.length,
               " El Niños (", m.warm_months, " months) against ",
               m.base_years, " neutral years, over the events of ",
               m.warm_events.join(", "),
               isFinite(crit(season))
                 ? "; distinguishable from an ordinary year beyond |t| "
                   + crit(season).toFixed(2)
                 : "; too few events this season to test",
               ". The cell is ", (here.lat1 - here.lat0).toFixed(1),
               "° by ", (here.lon1 - here.lon0).toFixed(1),
               "°; the value is that whole cell's, not this point's.</p>");
    }

    var links = linksAt(lon, lat);
    if (links.length) {
      var local_only = links.filter(function (k) {
        return k.scope !== "global";
      });
      buf.push("<h3>Catalogued for this region</h3>");
      if (!local_only.length) {
        buf.push('<p class="note">Nothing region-specific is catalogued at ',
                 "this point. The composite above is still a measurement here; ",
                 "the catalogue is a shorter list of teleconnections with ",
                 "named mechanisms, and this cell is not inside one of ",
                 "them.</p>");
      }
      for (i = 0; i < links.length; i++) {
        var lk = links[i];
        buf.push('<div class="lk"><b>', esc(lk.region), "</b> · ",
                 esc(lk.effect), "<br><em>", esc(lk.window), " · ",
                 esc(lk.confidence), " confidence · ", esc(lk.scope),
                 "</em>", lk.detail ? "<br>" + esc(lk.detail) : "", "</div>");
      }
    }
    if (near.length) {
      buf.push("<h3>Nearest places</h3><ul class=\"near\">");
      for (i = 0; i < near.length; i++) {
        // Natural Earth writes -99 where it has no population for a place,
        // and a handful of settlements carry it. Printing the sentinel as a
        // number would make two Siberian villages look like a data error in
        // the reader's own head; saying the count is missing is the truth.
        var pop = near[i][1][3];
        buf.push("<li>", esc(label(near[i][1])), " · ",
                 Math.round(near[i][0]), " km · ",
                 pop > 0 ? pop.toLocaleString() + " people"
                         : "population not recorded", "</li>");
      }
      buf.push("</ul>");
    }
    var ground = elevAt(lon, lat);
    if (ground !== null) {
      buf.push("<h3>The ground</h3><p>");
      if (ground > 0) {
        buf.push("Land, <b>", ground.toLocaleString(),
                 " m</b> above sea level.");
      } else if (ground === 0) {
        buf.push("<b>At sea level</b>, on the line.");
      } else {
        buf.push("Sea floor, <b>", (-ground).toLocaleString(),
                 " m</b> down.");
      }
      // A quarter degree is 28 km at the equator, so this is the height of a
      // landscape and not of an address. Saying so is the difference between
      // a figure and a claim.
      buf.push(" ETOPO1 at ", D.relief.step, "°, which is a ",
               Math.round(111 * D.relief.step), " km cell — a landscape, ",
               "not a street.</p>");
      // Only over land: the elevation service models the land surface and
      // answers a flat zero over water, where the vendored bathymetry above
      // is the real number and is already on the screen.
      if (ground > 0) {
        buf.push('<p><button type="button" id="truth" data-lon="',
                 lon.toFixed(5), '" data-lat="', lat.toFixed(5),
                 '" data-coarse="', ground,
                 '">Measure this exact point, 90 m</button>',
                 '<span id="truthout"></span></p>');
      }
    }

    // The composite says what happens here over forty years. It cannot say
    // what the place looks like, and pretending otherwise would be the whole
    // reason to want a photographic basemap. These are the photographs,
    // opened where they are maintained rather than copied in behind a key.
    var gz = Math.round(Math.log(1.40625 / view.dpp) / Math.LN2);
    if (gz < 3) { gz = 3; }
    if (gz > 15) { gz = 15; }
    var la = lat.toFixed(5), lo = lon.toFixed(5);
    // Clamped to the world. The map window is taller than the planet when it
    // is fitted and wider than it when it is wrapped, so the raw viewport is
    // a box reaching past both poles and more than once round, which
    // Worldview either rejects or opens somewhere else entirely.
    // The box is slid back inside the world rather than cut off at it, so a
    // view of the whole planet hands over the whole planet instead of a
    // lopsided box with one edge at the pole.
    var halfLon = Math.min(180, W * view.dpp / 2);
    var halfLat = Math.min(90, H * view.dpp / 2);
    var cLon = Math.min(180 - halfLon, Math.max(halfLon - 180, lon));
    var cLat = Math.min(90 - halfLat, Math.max(halfLat - 90, lat));
    var box = [(cLon - halfLon).toFixed(3), (cLat - halfLat).toFixed(3),
               (cLon + halfLon).toFixed(3), (cLat + halfLat).toFixed(3)]
      .join(",");
    var photo = BASE.photo;
    buf.push("<h3>See the place</h3>",
             '<ul class="links">',
             '<li><a href="map.html#at=', la, ",", lo,
             '">This point on the map: streets, satellite and Google</a></li>',
             '<li><a target="_blank" rel="noopener" href="',
             "https://www.google.com/maps/@?api=1&amp;map_action=map&amp;center=",
             la, ",", lo, "&amp;zoom=", gz,
             '&amp;basemap=satellite">Google Maps, satellite</a></li>',
             '<li><a target="_blank" rel="noopener" href="',
             "https://earth.google.com/web/@", la, ",", lo,
             ',0a,120000d,35y,0h,0t,0r">Google Earth</a></li>',
             '<li><a target="_blank" rel="noopener" href="',
             "https://worldview.earthdata.nasa.gov/?v=", box,
             "&amp;l=", photo ? photo.layer : "VIIRS_SNPP_CorrectedReflectance_TrueColor",
             photo && photo.date ? "&amp;t=" + photo.date : "",
             '">NASA Worldview, this view today</a></li>',
             '<li><a target="_blank" rel="noopener" href="',
             "https://www.openstreetmap.org/#map=", gz, "/", la, "/", lo,
             '">OpenStreetMap</a></li>',
             "</ul>");

    buf.push('<p class="note">Three different kinds of claim are on this ',
             "page and they are not the same thing. The number above is ",
             "<b>measured</b> from the record. The catalogue is a ",
             "<b>documented</b> teleconnection, not a forecast. Neither is a ",
             "prediction of this year.</p>");
    panel.innerHTML = buf.join("");
    panel.scrollTop = 0;
    var truth = document.getElementById("truth");
    if (truth) { truth.addEventListener("click", measure); }
  }
  // The marked point answered again for the field or season now chosen: the
  // outline stayed on the old grid's cell and the dossier on the old numbers.
  function remark() { if (marked) { pick(marked.lon, marked.lat); } }

  function measure() {
    var btn = this, out = document.getElementById("truthout");
    btn.disabled = true;
    out.textContent = " measuring\u2026";
    // Open-Meteo's elevation endpoint: no key, no account, one point a press,
    // and it answers a browser with Access-Control-Allow-Origin, which the
    // obvious alternative does not. It is the only request this page makes to
    // another site that the reader did not ask for by choosing an imagery
    // layer, which is exactly why it is a button and not something a click
    // does by itself.
    fetch("https://api.open-meteo.com/v1/elevation?latitude="
          + btn.dataset.lat + "&longitude=" + btn.dataset.lon)
      .then(function (r) { return r.json(); })
      .then(function (j) {
        var m = j && j.elevation && j.elevation.length ? j.elevation[0] : null;
        if (m === null || m === undefined) {
          out.textContent = " no coverage at that point.";
          btn.disabled = false;
          return;
        }
        var coarse = +btn.dataset.coarse;
        // The point of the number is the difference. A 28 km cell and a 90 m
        // post agreeing says the country is flat; 900 m apart says the cell
        // was an average of a mountainside and the composite for it is an
        // average of two climates.
        out.textContent = " " + Math.round(m) + " m at that exact point"
          + " (Copernicus GLO-90), "
          + (Math.abs(m - coarse) < 25
             ? "within 25 m of the cell."
             : Math.round(Math.abs(m - coarse)) + " m "
               + (m > coarse ? "above" : "below") + " the cell average.");
      })
      .catch(function () {
        out.textContent = " could not reach the elevation service.";
        btn.disabled = false;
      });
  }

  function label(p) {
    var bits = [p[0]];
    if (p[2] && p[2] !== p[0]) { bits.push(p[2]); }
    if (p[1]) { bits.push(p[1]); }
    return bits.join(", ");
  }

  // -- controls --------------------------------------------------------------
  function press(sel, on) {
    var nodes = document.querySelectorAll(sel), i;
    for (i = 0; i < nodes.length; i++) {
      nodes[i].setAttribute("aria-pressed", on(nodes[i]) ? "true" : "false");
    }
  }
  function syncBar() {
    press("[data-var]", function (n) { return n.dataset.var === variable; });
    press("[data-season]", function (n) { return n.dataset.season === season; });
    press("[data-fade]", function () { return fade; });
    press("[data-layer]", function (n) { return show[n.dataset.layer]; });
    press("[data-comp]", function () { return composite; });
    press("[data-base]", function (n) { return n.dataset.base === base; });
    describeBase();
    // A legend is for what is on the map. Left up with the composite switched
    // off it explains a layer that is not there, and next to the satellite
    // anomaly it puts a second diverging scale on the page after the trouble
    // just taken to keep the first one off it.
    document.getElementById("rampkey").hidden = !composite;
    document.getElementById("fadekey").hidden = !composite || !fade;
    document.getElementById("sstkey").hidden = base !== "sst";
    var v = D.grids[variable];
    document.getElementById("unit").textContent = v.unit;
    document.getElementById("what").textContent =
      v.invert ? "drier ← rainfall → wetter"
               : "cooler ← temperature → warmer";
    document.getElementById("limits").textContent =
      "−" + LIMIT[variable] + " to +" + LIMIT[variable];
    document.getElementById("crit").textContent = isFinite(crit(season))
      ? crit(season).toFixed(2) : "any value, too few events to test";
    // The strip is one row of swatches in ramp order, and rainfall reads that
    // ramp backwards, so for rainfall the strip is turned round rather than
    // relabelled. A legend that runs the other way from the map it explains is
    // worse than no legend at all.
    document.getElementById("steps").style.flexDirection =
      v.invert ? "row-reverse" : "row";
  }
  document.addEventListener("click", function (ev) {
    var t = ev.target.closest ? ev.target.closest("button") : null;
    if (!t) { return; }
    if (t.dataset.var) { variable = t.dataset.var; remark(); }
    else if (t.dataset.season) { season = t.dataset.season; remark(); }
    else if (t.dataset.fade !== undefined) { fade = !fade; }
    else if (t.dataset.layer) {
      show[t.dataset.layer] = !show[t.dataset.layer];
    } else if (t.dataset.comp !== undefined) { composite = !composite; }
    else if (t.dataset.base) {
      base = t.dataset.base;
      // Two diverging scales stacked on one map is a picture of nothing, and
      // the satellite anomaly brings its own. Choosing it puts the composite
      // away rather than drawing one over the other; turning the composite
      // back on is one click and is then the reader's choice, not a default.
      if (base === "sst" && composite) { composite = false; }
      imageryFailed = false;
    } else if (t.dataset.zoom) {
      zoomBy(+t.dataset.zoom);
      return;
    } else if (t.dataset.home !== undefined) {
      view = { lon: 150, lat: 0, dpp: fitted() };
      marked = null;
      panel.innerHTML = HINT;
    } else if (t.id === "theme") {
      var dark = document.documentElement.getAttribute("data-theme") === "dark";
      document.documentElement.setAttribute("data-theme", dark ? "light" : "dark");
    } else { return; }
    syncBar();
    schedule();
  });
  // The relief's two colours and the composite's ramp are the page's own
  // tokens, so a change of theme - the button above, or the system's own -
  // is a repaint of both canvases as much as of the page.
  function themed() { tone = null; ramp = null; schedule(); }
  if (window.MutationObserver) {
    new MutationObserver(themed).observe(document.documentElement,
      { attributes: true, attributeFilter: ["data-theme"] });
  }
  if (window.matchMedia) {
    var scheme = window.matchMedia("(prefers-color-scheme: dark)");
    if (scheme.addEventListener) { scheme.addEventListener("change", themed); }
    else if (scheme.addListener) { scheme.addListener(themed); }
  }
  document.addEventListener("keydown", function (ev) {
    if (ev.target.tagName === "INPUT") { return; }
    var step = W * 0.25 * view.dpp;
    if (ev.key === "ArrowLeft") { view.lon -= step; }
    else if (ev.key === "ArrowRight") { view.lon += step; }
    else if (ev.key === "ArrowUp") { view.lat += step; }
    else if (ev.key === "ArrowDown") { view.lat -= step; }
    else if (ev.key === "+" || ev.key === "=") { zoomBy(1.6); return; }
    else if (ev.key === "-") { zoomBy(1 / 1.6); return; }
    else { return; }
    ev.preventDefault();
    clampView();
    schedule();
  });

  var HINT = panel.innerHTML;
  // A link can open the atlas on a point, atlas.html#at=LAT,LON, as the storm
  // desk's "here" does: the view closes in on it and its dossier opens.
  function fromHash() {
    var m = /^#at=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/.exec(location.hash);
    if (!m) { return false; }
    var lat = +m[1], lon = +m[2];
    if (Math.abs(lat) > 90 || Math.abs(lon) > 360) { return false; }
    view = { lon: lon, lat: lat, dpp: Math.max(D.tight, fitted() / 6) };
    clampView();
    pick(lon, lat);
    syncBar();
    schedule();
    return true;
  }
  window.addEventListener("hashchange", fromHash);
  window.addEventListener("resize", resize);
  // The map's box changes without the window when the bar above re-wraps:
  // measured only on a window resize, the vector map kept its old size while
  // the box around it grew, and the field and the coastlines parted.
  if (window.ResizeObserver) { new ResizeObserver(resize).observe(map); }

  // -- following the site (elnino/live.py) -----------------------------------
  // A page loading again for a new run hands over what the reader had: the
  // view, the layers and the point picked, its dossier scrolled where it was.
  // What comes back is read like input: a value that is not one of the
  // atlas's own leaves that part as the page opens.
  function own(table, key) { return Object.prototype.hasOwnProperty.call(table, key); }
  function finite(x) { return typeof x === "number" && isFinite(x); }
  function keep() {
    return { view: { lon: view.lon, lat: view.lat, dpp: view.dpp }, variable: variable,
             season: season, fade: fade, composite: composite, base: base,
             show: { borders: show.borders, rivers: show.rivers, places: show.places },
             marked: marked && { lon: marked.lon, lat: marked.lat }, dossier: panel.scrollTop };
  }
  function restore(kept) {
    if (typeof kept.variable === "string" && own(D.grids, kept.variable)) { variable = kept.variable; }
    if (D.seasons.indexOf(kept.season) >= 0) { season = kept.season; }
    if (typeof kept.fade === "boolean") { fade = kept.fade; }
    if (typeof kept.composite === "boolean") { composite = kept.composite; }
    if (typeof kept.base === "string" && own(BASE, kept.base)) { base = kept.base; }
    if (kept.show && typeof kept.show === "object") {
      Object.keys(show).forEach(function (layer) {
        if (typeof kept.show[layer] === "boolean") { show[layer] = kept.show[layer]; }
      });
    }
    var v = kept.view;
    if (v && finite(v.lon) && finite(v.lat) && finite(v.dpp) && v.dpp > 0) {
      // Onto the world first: clampView() wraps a turn at a time, and a view
      // turned 1e300 degrees would never be done.
      view = { lon: lon180(v.lon), lat: v.lat, dpp: v.dpp };
      clampView();
    }
    // Picked after the variable and the season are back: the dossier is
    // written for them.
    var m = kept.marked;
    if (m && finite(m.lon) && finite(m.lat) && Math.abs(m.lat) <= 90) {
      pick(m.lon, m.lat);
      if (finite(kept.dossier)) { panel.scrollTop = kept.dossier; }
    }
    syncBar();
    schedule();
  }

  syncBar();
  resize();
  fromHash();
  elninoLive.follow({ keep: keep, restore: restore });
})();
""".replace("  /*FIELD*/\n", FIELD_JS)


# NASA's published colour map for the sea-surface anomaly layer, read from
# their own colormaps service and taken every half a degree. The legend under
# an imagery layer has to be that layer's scale: a spectral ramp described in
# words as "blue to red" is a wrong legend, which is worse than none. It runs
# -3 to +3 degrees and is drawn as a bar rather than as the stepped strip the
# composite uses, because the composite really is binned and this is not.
SST_STOPS = (
    (-3.0, (116, 0, 214)), (-2.5, (127, 26, 209)), (-2.0, (0, 148, 255)),
    (-1.5, (24, 252, 229)), (-1.0, (136, 255, 132)), (-0.5, (191, 244, 163)),
    (0.0, (202, 202, 183)), (0.5, (255, 246, 121)), (1.0, (255, 182, 1)),
    (1.5, (255, 113, 0)), (2.0, (249, 1, 19)), (2.5, (211, 0, 133)),
    (3.0, (128, 0, 0)),
)
SST_LIMIT = 3.0


def _sst_gradient() -> str:
    """NASA's ramp as one CSS gradient, keyed to its own degrees."""
    return "linear-gradient(to right," + ",".join(
        "rgb(%d,%d,%d) %g%%" % (
            rgb[0], rgb[1], rgb[2],
            round((value + SST_LIMIT) / (2 * SST_LIMIT) * 100, 2))
        for value, rgb in SST_STOPS) + ")"


def _legend_steps() -> str:
    return "".join(f'<i style="background:var(--d{i})"></i>'
                   for i in range(len(fields.DIVERGING_LIGHT)))


def _controls() -> str:
    seasons = "".join(
        f'<button type="button" data-season="{s}" '
        f'title="{esc(atlas.SEASON_LABEL[s])}">{s}</button>'
        for s in atlas.SEASONS)
    variables = "".join(
        f'<button type="button" data-var="{name}">{esc(label)}</button>'
        for name, label, _unit, _inv in VARIABLES)
    bases = '<button type="button" data-base="none">None</button>' + "".join(
        f'<button type="button" data-base="{b["id"]}" '
        f'title="{esc(b["note"])}">{esc(b["label"])}</button>'
        for b in BASEMAPS)
    return f"""
<header class="atlasbar">
  <h1>El Nino, where it lands</h1>
  <span class="lbl">Field</span><span class="grp">{variables}</span>
  <span class="lbl">Season</span><span class="grp">{seasons}</span>
  <span class="lbl">Base</span><span class="grp">{bases}</span>
  <span class="grp">
    <button type="button" data-comp="1">Composite</button>
    <button type="button" data-fade="1">Fade below 95%</button>
    <button type="button" data-layer="borders">Borders</button>
    <button type="button" data-layer="rivers">Water</button>
    <button type="button" data-layer="places">Places</button>
  </span>
  <span class="spacer"></span>
  <span class="grp"><button type="button" id="theme">Theme</button></span>
</header>"""


def _legend() -> str:
    _SST_GRADIENT = _sst_gradient()
    return f"""
<div class="atlaslegend">
  <span class="key" id="rampkey"><span id="what">drier &larr; rainfall &rarr;
    wetter</span>
    <span class="steps" id="steps">{_legend_steps()}</span>
    <span id="limits">&minus;3 to +3</span> <span id="unit">mm/day</span>
    against a neutral year</span>
  <span class="key" id="fadekey"><span class="steps"><i
    style="background:var(--d9); opacity:.16"></i></span> faded: |t| under
    <span id="crit">{atlas.critical("PRECIP", "DJF"):.2f}</span>, the 95% point
    for this season's own sample - not distinguishable from an ordinary
    year</span>
  <span class="key" id="sstkey" hidden><span class="ramp"
    style="background:{_SST_GRADIENT}"></span>
    &minus;3 &larr; today's sea surface against its climatology &rarr; +3
    &deg;C</span>
  <span class="key"><svg width="34" height="13" aria-hidden="true">
    <circle cx="5" cy="7" r="2.2" fill="var(--ink)" fill-opacity=".62"/>
    <circle cx="16" cy="7" r="4" fill="var(--ink)" fill-opacity=".62"/>
    <circle cx="29" cy="7" r="6" fill="var(--ink)" fill-opacity=".62"/>
    </svg> population; a ring marks a capital</span>
  <span class="key"><svg width="18" height="13" aria-hidden="true">
    <circle cx="9" cy="7" r="5" fill="var(--s2)"/></svg> active cyclone</span>
  <span class="key" id="source"></span>
</div>"""


_HINT = """
<p class="hint"><b>Click anywhere</b> for what forty years of El Nino events
have actually done at that cell &mdash; rainfall and surface temperature
against a neutral year, every season, with the statistic that says whether the
difference is real.</p>
<p class="hint">Drag to pan. Scroll, pinch, or use + and &minus; to zoom; the
coastline, borders, rivers and place names sharpen as you go in. Arrow keys pan,
+ and &minus; zoom.</p>
<p class="hint">The composite is <b>what happened</b>, not what will. It is the
mean of the El Nino months in the record minus the mean of the neutral ones, so
a cell with a strong value and a weak <i>t</i> is telling you the events
disagreed with each other.</p>
"""


def page(state) -> str:
    """The whole standalone atlas, one file."""
    # Imported here rather than at the top: dashboard imports this module for
    # the card, and a top-level import back would close the circle.
    from .dashboard import _css as shell_css
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    data = json.dumps(payload(state), separators=(",", ":"))
    # A closing tag inside a JSON string ends the script element wherever it
    # appears, including inside a quoted place name.
    data = data.replace("</", "<\\/")
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{live.head(getattr(state, "run_at", None))}
{sitenav.ICON}
<title>El Nino Atlas &mdash; where it lands</title>
<style>{shell_css()}{fields.ramp_css()}{css()}
.plab {{ font: 500 11px var(--font); fill: var(--ink); paint-order: stroke;
  stroke: var(--surface); stroke-width: 3px; stroke-linejoin: round;
  pointer-events: none; }}
.slab {{ font-weight: 600; }}
</style>
</head>
<body class="atlaspage">
{sitenav.bar("atlas.html")}
{_controls()}
<main class="atlaswrap">
  <div class="atlasmap" id="map">
    <canvas id="relief" aria-hidden="true"></canvas>
    <div id="tiles" aria-hidden="true"></div>
    <canvas id="field" aria-hidden="true"></canvas>
    <svg id="svg" width="100" height="100" viewBox="0 0 100 100"
         role="img" aria-label="Interactive world map of El Nino composite
         rainfall and temperature anomalies">
      <g id="pan">
        <g id="vec"></g>
        <g id="pts"></g>
        <g id="pick"></g>
      </g>
    </svg>
    <div class="atlaspill" id="read">&mdash;</div>
    <div class="atlaspill" id="credit" hidden></div>
    <div class="atlaspill" id="scale"></div>
    <div class="atlaszoom">
      <button type="button" data-zoom="1.6" aria-label="Zoom in">+</button>
      <button type="button" data-zoom="0.625" aria-label="Zoom out">&minus;</button>
      <button type="button" data-home="1" aria-label="Reset the view"
              title="Reset the view" style="font-size:11px">Fit</button>
    </div>
  </div>
  <aside class="atlaspanel dossier" id="panel">{_HINT}</aside>
</main>
{_legend()}
<script>var RELIEF="{relief.png()}";</script>
<script>var ATLAS={data};</script>
<script>{live.SCRIPT}</script>
<script>{_JS}</script>
</body>
</html>"""
