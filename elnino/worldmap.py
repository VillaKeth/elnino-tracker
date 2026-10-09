"""The map: El Nino's effects anywhere on Earth, down to a single street.

The storm desk's map engine, given street, satellite and terrain maps to lay
under everything it draws. The maps are Esri's: their tiles need no key and
are sent with ``Access-Control-Allow-Origin: *``, so the page can look at a
tile it has drawn (Esri answers a zoom past its coverage with a grey "Map
data not yet available" tile, which the page sets aside for the coarser tile
it does have). They are used under the Esri Master License Agreement with
the credit each service publishes shown on the map, and they are drawn as
the page is viewed, never exported for use offline.

Google's tiles are not drawn under the page's own layers: Google's terms
forbid it. Google's own embed and its documented Maps URLs open the same
place in Google's map, satellite view and Street View instead.

OpenStreetMap's tiles are offered only when the page is served
(``python track.py --serve``): its servers answer a page opened from a file,
which sends no Referer, with an "Access blocked" image.

Over the map go the atlas's El Nino composites: the mean of the El Nino
seasons since 1979 minus the mean of the ordinary ones, per grid cell, drawn
as the atlas draws them - the same grids, colour ramp, full scale,
significance mask and fade, and the same field blended between the cell
centres (``atlasview.FIELD_JS``) - for whichever season is chosen, the one
containing the build date first.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from . import atlas, atlasview, composite, geo, grids
from .svg import esc

ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/"
_TILE = "/MapServer/tile/{z}/{y}/{x}"

# Credits as each service's own description gave them on 28 September 2026.
MAP_LAYERS = (
    {"id": "streets", "kind": "map", "name": "Streets",
     "about": "Esri World Street Map: roads, buildings and names down to single streets.",
     "source": "Esri World Street Map", "tiles": ESRI + "World_Street_Map" + _TILE,
     "zoom": 19, "grey": True,
     "credit": ("Powered by Esri. Sources: Esri, HERE, Garmin, USGS, Intermap, "
                "INCREMENT P, NRCan, Esri Japan, METI, Esri China (Hong Kong), Esri Korea, "
                "Esri (Thailand), NGCC, (c) OpenStreetMap contributors, and the GIS User "
                "Community")},
    {"id": "satellite", "kind": "map", "name": "Satellite",
     "about": ("Esri World Imagery: one metre or better satellite and aerial imagery in "
               "many parts of the world and lower resolution satellite imagery worldwide, "
               "with Esri's roads and place names over it."),
     "source": "Esri World Imagery", "tiles": ESRI + "World_Imagery" + _TILE,
     "over": [ESRI + "Reference/World_Transportation" + _TILE,
              ESRI + "Reference/World_Boundaries_and_Places" + _TILE],
     "zoom": 19, "grey": True,
     "credit": ("Powered by Esri. Source: Esri, Vantor, Earthstar Geographics, and the GIS "
                "User Community. Roads and names: Esri, HERE, Garmin, (c) OpenStreetMap "
                "contributors, and the GIS user community")},
    {"id": "terrain", "kind": "map", "name": "Terrain",
     "about": "Esri World Topographic Map: relief, land cover, roads and names.",
     "source": "Esri World Topographic Map", "tiles": ESRI + "World_Topo_Map" + _TILE,
     "zoom": 19, "grey": True,
     "credit": ("Powered by Esri. Sources: Esri, HERE, Garmin, Intermap, increment P Corp., "
                "GEBCO, USGS, FAO, NPS, NRCAN, GeoBase, IGN, Kadaster NL, Ordnance Survey, "
                "Esri Japan, METI, Esri China (Hong Kong), (c) OpenStreetMap contributors, "
                "and the GIS User Community")},
    {"id": "osm", "kind": "map", "name": "OpenStreetMap",
     "about": ("OpenStreetMap's standard map. Offered when the page is served "
               "(python track.py --serve): its servers refuse a page opened from a file."),
     "source": "OpenStreetMap", "tiles": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
     "zoom": 19, "grey": False, "served_only": True,
     "credit": "© OpenStreetMap contributors"},
)

# ----------------------------------------------------------------------------
# today's ocean and the last three days' floods: NASA GIBS, Web Mercator, as
# the capabilities listed them on 28 September 2026
# ----------------------------------------------------------------------------
ENSO_TILES = (
    {"id": "sst", "kind": "enso", "name": "Ocean today",
     "about": ("Sea surface temperature anomaly, GHRSST MUR L4, daily at about 1 km: "
               "the event itself, against MUR's own climatology."),
     "global": "GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies",
     "tms": "GoogleMapsCompatible_Level7", "zoom": 7, "format": "png",
     "step": "P1D", "pixel_km": 1.0, "credit": "SST: GHRSST MUR, NASA JPL."},
    {"id": "floods", "kind": "enso", "name": "Floods, last 3 days",
     "about": ("MODIS Terra and Aqua combined flood product, a three-day window at "
               "250 m: water seen where it is not ordinarily."),
     "global": "MODIS_Combined_Flood_3-Day",
     "tms": "GoogleMapsCompatible_Level9", "zoom": 9, "format": "png",
     "step": "P1D", "pixel_km": 0.25, "credit": "Floods: MODIS, NASA LANCE.",
     "faint": [[50, 210, 245], [175, 175, 175]]},
)
# Past this zoom the tiles are hidden: a pixel of theirs would fill the view.
HIDE_ABOVE = 12
# MODIS's "surface water" (the sea itself, near coasts) and its cloud-bound
# "insufficient data" come as whole granules, over the ocean too; they are
# drawn at this strength so they do not hide the sea. Floods stay full strength.
FAINT = 0.2
ENSO_CREDITS = {l["id"]: l["credit"] for l in ENSO_TILES}

# NASA's own colour maps, bin for bin, so a tapped pixel reads back to its
# value. From https://gibs.earthdata.nasa.gov/colormaps/v1.3/
# GHRSST_Sea_Surface_Temperature_Anomalies.xml and MODIS_Flood.xml, 28 Sep 2026:
# (low, high, rgb) per 0.1 degC bin, [low, high), the two ends open.
SST_COLOURS = (
    (None, -3.0, (107, 0, 219)), (-3.0, -2.9, (116, 0, 214)), (-2.9, -2.8, (127, 0, 211)),
    (-2.8, -2.7, (137, 0, 207)), (-2.7, -2.6, (150, 0, 202)), (-2.6, -2.5, (145, 9, 204)),
    (-2.5, -2.4, (127, 26, 209)), (-2.4, -2.3, (96, 49, 220)), (-2.3, -2.2, (65, 75, 230)),
    (-2.2, -2.1, (34, 100, 241)), (-2.1, -2.0, (8, 124, 251)), (-2.0, -1.9, (0, 148, 255)),
    (-1.9, -1.8, (0, 174, 255)), (-1.8, -1.7, (0, 202, 255)), (-1.7, -1.6, (0, 227, 255)),
    (-1.6, -1.5, (3, 248, 250)), (-1.5, -1.4, (24, 252, 229)),
    (-1.4, -1.3, (47, 255, 206)), (-1.3, -1.2, (71, 255, 182)),
    (-1.2, -1.1, (96, 255, 158)), (-1.1, -1.0, (118, 255, 140)),
    (-1.0, -0.9, (136, 255, 132)), (-0.9, -0.8, (151, 255, 139)),
    (-0.8, -0.7, (164, 255, 145)), (-0.7, -0.6, (177, 255, 152)),
    (-0.6, -0.5, (189, 254, 158)), (-0.5, -0.4, (191, 244, 163)),
    (-0.4, -0.3, (191, 232, 169)), (-0.3, -0.2, (191, 219, 176)),
    (-0.2, -0.1, (191, 208, 182)), (-0.1, 0.0, (194, 202, 184)),
    (0.0, 0.1, (202, 202, 183)), (0.1, 0.2, (213, 213, 172)), (0.2, 0.3, (226, 226, 162)),
    (0.3, 0.4, (237, 237, 152)), (0.4, 0.5, (249, 248, 141)), (0.5, 0.6, (255, 246, 121)),
    (0.6, 0.7, (255, 234, 94)), (0.7, 0.8, (255, 222, 67)), (0.8, 0.9, (255, 208, 37)),
    (0.9, 1.0, (255, 194, 9)), (1.0, 1.1, (255, 182, 1)), (1.1, 1.2, (255, 170, 0)),
    (1.2, 1.3, (255, 157, 0)), (1.3, 1.4, (255, 145, 0)), (1.4, 1.5, (255, 130, 0)),
    (1.5, 1.6, (255, 113, 0)), (1.6, 1.7, (255, 89, 0)), (1.7, 1.8, (255, 61, 0)),
    (1.8, 1.9, (255, 33, 0)), (1.9, 2.0, (254, 9, 0)), (2.0, 2.1, (249, 1, 19)),
    (2.1, 2.2, (243, 0, 45)), (2.2, 2.3, (236, 0, 74)), (2.3, 2.4, (230, 0, 103)),
    (2.4, 2.5, (222, 0, 125)), (2.5, 2.6, (211, 0, 133)), (2.6, 2.7, (191, 0, 104)),
    (2.7, 2.8, (171, 0, 72)), (2.8, 2.9, (154, 0, 44)), (2.9, 3.0, (136, 0, 15)),
    (3.0, None, (128, 0, 0)),
)
FLOOD_CLASSES = (
    ((50, 210, 245), "Surface water"), ((255, 255, 0), "Recurring flood"),
    ((250, 30, 36), "Flood"), ((175, 175, 175), "Insufficient data"),
)

# Every tile layer the map adds to the desk's.
LAYERS = MAP_LAYERS + ENSO_TILES

# ----------------------------------------------------------------------------
# the composites, as the atlas draws them
# ----------------------------------------------------------------------------
LIMITS = {"PRECIP": 3.0, "AIR": 1.6}   # the atlas's full scale (atlasview JS LIMIT)
OPACITY = 0.58                          # over imagery
TILE_OPACITY = 0.8                      # NASA's ocean and flood tiles, until moved
MASK = 0.16                             # a cell the t test does not pass
FADE = (90, 420, 0.42)                  # past 90 px a cell, down to 0.42
_SEASON_OF_MONTH = {12: "DJF", 1: "DJF", 2: "DJF", 3: "MAM", 4: "MAM", 5: "MAM",
                    6: "JJA", 7: "JJA", 8: "JJA", 9: "SON", 10: "SON", 11: "SON"}
_EFFECTS = (("PRECIP", "Rainfall"), ("AIR", "Temperature"), ("", "Off"))
_GEO_WORDS = (("regions", "Impact regions, in play solid"), ("boxes", "Ni\u00f1o regions"))
_TILE_WORDS = (("sst", "Ocean today: SST anomaly, NASA MUR"),
               ("floods", "Floods, last 3 days: NASA MODIS"))


def season_of(day: date) -> str:
    """The three-month season a day falls in, named by its months."""
    return _SEASON_OF_MONTH[day.month]


def next_season(season: str) -> str:
    return atlas.SEASONS[(atlas.SEASONS.index(season) + 1) % len(atlas.SEASONS)]


def _signed(value: float) -> str:
    """One decimal with its sign, the minus a true minus, zero unsigned."""
    sign = "+" if value > 0 else "−" if value < 0 else ""
    return f"{sign}{abs(value):.1f}"


def _sst_label(lo, hi) -> str:
    if lo is None:
        return f"below {_signed(hi)} °C"
    if hi is None:
        return f"{_signed(lo)} °C or more"
    return f"{_signed(lo)} to {_signed(hi)} °C"


def _built_day(state) -> date:
    try:
        return datetime.fromisoformat(str(getattr(state, "run_at", ""))).date()
    except ValueError:
        return datetime.now(timezone.utc).date()


def _links(state) -> list:
    """The documented teleconnections with their footprints, each marked with
    whether this event puts it in play ("in play"), keeps it on the watch list
    ("watch"), or neither ("")."""
    impacts = getattr(state, "impacts", None)
    status: dict = {}
    for kind, word in (("watch", "watch"), ("active", "in play")):
        for impact in getattr(impacts, kind, None) or ():
            status[impact.link.region] = (word, impact.likelihood, impact.timing)
    out = []
    for row in atlasview._links_payload():
        word, likelihood, timing = status.get(row["region"], ("", "", ""))
        out.append({**row, "status": word, "likelihood": likelihood, "timing": timing})
    return out


def payload(state) -> dict:
    """What the page needs to draw and read the composites."""
    now = season_of(_built_day(state))
    return {"grids": atlasview._grid_payload(), "seasons": list(atlas.SEASONS),
            "season_label": dict(atlas.SEASON_LABEL), "now": now, "next": next_season(now),
            "limits": dict(LIMITS), "opacity": OPACITY, "tile_opacity": TILE_OPACITY,
            "mask": MASK, "fade": list(FADE),
            "significant": {name: {s: getattr(composite, f"{name}_META")[s]["t_crit"]
                                   for s in atlas.SEASONS} for name in LIMITS},
            "dry_floor": atlas.DRY_FLOOR, "links": _links(state),
            "colours": {"sst": [{"label": _sst_label(lo, hi), "rgb": list(rgb)}
                                for lo, hi, rgb in SST_COLOURS],
                        "floods": [{"label": label, "rgb": list(rgb)}
                                   for rgb, label in FLOOD_CLASSES]},
            "hide_above": HIDE_ABOVE, "faint": FAINT,
            "boxes": _boxes(state)}


def _nino(text: str) -> str:
    """The tracker's ASCII "El Nino" and "La Nina", spelled for the page."""
    return text.replace("El Nino", "El Ni\u00f1o").replace("La Nina", "La Ni\u00f1a")


def _boxes(state) -> list:
    """CPC's four Nino regions, each with this week's anomaly where it arrived:
    relative to the tropical mean when CPC's relative file had the week (the
    regional counterpart of RONI, which CPC now quotes), else the traditional
    anomaly, else none."""
    a = getattr(state, "assessment", None)
    week = getattr(a, "latest_week", None)
    scale = getattr(a, "scale", None)
    relative = ({r.key: r.anomaly for r in scale.regions}
                if scale is not None and getattr(scale, "basis", "") == "relative" else {})
    out = []
    for box in grids.NINO_BOXES:
        if relative:
            anomaly, basis = relative.get(box.key), "relative"
        elif week is not None:
            anomaly, basis = getattr(week, f"{box.key}_anom", None), "traditional"
        else:
            anomaly, basis = None, ""
        out.append({"key": box.key, "label": box.label.replace("Nino-", "Ni\u00f1o "),
                    "lon0": box.lon0, "lon1": box.lon1, "lat0": box.lat0, "lat1": box.lat1,
                    "anomaly": anomaly, "basis": basis if anomaly is not None else "",
                    "week": week.week_ending.isoformat() if week is not None else None})
    return out


def _impact_item(impact) -> str:
    """One effect, with Show where it has a place to fly to: a global effect
    has no box to show. Pressed again, Show puts its region away."""
    link = impact.link
    footprint = geo.BY_REGION.get(link.region)
    show = (f' <button type="button" class="toolbtn" data-show-region="{esc(link.region)}" '
            'aria-pressed="false">Show</button>'
            if footprint is not None and footprint.scope != geo.GLOBAL else "")
    return (f'<li><b>{esc(link.region)}</b>: {esc(link.effect)} '
            f'<span class="muted">({esc(impact.likelihood)}, {esc(impact.timing)})</span>'
            f'{show}</li>')


_LAYER_FACTS = (
    ("Rainfall and temperature",
     "What past events did, not a forecast: the mean of the El Ni\u00f1o seasons since 1979 "
     "(RONI +1.0 or more) minus the mean of the neutral ones (RONI within 0.5), per season "
     "and cell, from GPCP v2.3 rainfall (2.5\u00b0) and GHCN-CAMS land temperature (2\u00b0), "
     "computed by this tracker (composite.py), with Welch's t for each cell. Drawn blended "
     "between the cell centres; a tap reads the whole cell."),
    ("Ocean today", "GHRSST MUR L4 sea surface temperature anomaly, daily, via NASA GIBS."),
    ("Floods", "The MODIS (Terra and Aqua) combined flood product, three-day window, via NASA GIBS."),
    ("Impact regions",
     "This tracker's catalogue of documented teleconnections: coarse boxes by design, solid "
     "where this event puts the effect in play. Drawn when ticked, or one at a time from "
     "Show."),
    ("Ni\u00f1o regions", "CPC's four boxes, with this week's anomalies."),
    ("Street maps", "Esri's street, satellite and terrain maps; OpenStreetMap's when the page is served."),
    ("Google", "Google's own map, satellite view and Street View of a point, loaded only when asked for."),
)


def section(state) -> str:
    """El Nino now: where the event stands this run, what it puts in play, and
    what each of the map's layers is. Each piece that did not arrive is one
    sentence saying so."""
    a = getattr(state, "assessment", None)
    latest = getattr(a, "index_latest", None)
    out = ['<section id="enso-now" class="panelsec"><h2 class="panelhead">El Ni\u00f1o now</h2>']
    if latest is None:
        out.append("<p>The index did not arrive this run.</p>")
    else:
        said = (f"<b>{esc(a.index_name)} {latest.value:+.2f} \u00b0C</b> for {esc(latest.label)}: "
                f"{esc(_nino(a.index_tier))}.")
        oni = getattr(a, "oni_latest", None)
        if a.index_name == "RONI" and oni is not None:
            said += f" The legacy ONI reads {oni.value:+.2f} \u00b0C for {esc(oni.label)}."
        out.append(f"<p>{said}</p>")
        if getattr(a, "status", ""):
            out.append(f"<p>CPC's status: {esc(_nino(a.status))}.</p>")
    box = {b["key"]: b for b in _boxes(state)}["nino34"]
    if box["anomaly"] is None:
        out.append("<p>No weekly SSTs arrived this run.</p>")
    else:
        basis = ("against the tropical mean, as CPC now quotes it" if box["basis"] == "relative"
                 else "the traditional anomaly")
        out.append(f"<p>Ni\u00f1o 3.4 this week: <b>{box['anomaly']:+.2f} \u00b0C</b>, {basis} "
                   f"(week ending {esc(a.latest_week.label)}).</p>")
    peak = getattr(getattr(state, "forecast", None), "peak", None)
    if peak is None:
        out.append("<p>No forecast this run.</p>")
    else:
        index = getattr(a, "index_name", "the index")
        out.append(f"<p>Forecast peak of {esc(index)}: <b>{peak.mean:+.2f} \u00b0C</b> in "
                   f"{esc(peak.label)} (10 to 90%: {peak.low:+.2f} to {peak.high:+.2f} \u00b0C).</p>")
    impacts = getattr(state, "impacts", None)
    if impacts is None:
        out.append("<p>The impact outlook did not run.</p>")
    else:
        out.append("<h4>In play this event</h4>")
        out.append('<ul class="wwlist">' + "".join(_impact_item(i) for i in impacts.active) + "</ul>"
                   if impacts.active else "<p>No documented effect is in play at this strength.</p>")
        if impacts.watch:
            out.append("<h4>Watch list</h4>")
            out.append('<ul class="wwlist">' + "".join(_impact_item(i) for i in impacts.watch)
                       + "</ul>")
    out.append("<h4>What the map layers are</h4>")
    out.append('<dl class="facts">' + "".join(f"<dt>{esc(term)}</dt><dd>{esc(words)}</dd>"
                                              for term, words in _LAYER_FACTS) + "</dl>")
    out.append("</section>")
    return "".join(out)


def card(state) -> str:
    """The dashboard's way into map.html."""
    season = atlas.SEASON_LABEL[season_of(_built_day(state))]
    return f"""<section class="card" id="world-map">
  <h2>The map</h2>
  <p class="prose"><a class="bigalink" href="map.html">Open the El Ni&ntilde;o Map &rarr;</a>
    From the whole planet down to a single street, on Esri's street,
    satellite and terrain maps, with Google's own map, satellite view and Street
    View of any point on request. Over them go this tracker's El Ni&ntilde;o
    composites for {esc(season)}, the season now: what the El Ni&ntilde;o seasons
    since 1979 did to rainfall and temperature against the ordinary ones. Today's
    sea surface temperature anomaly and the last three days' floods come from
    NASA, and the documented impact regions are a tick away, solid where this
    event puts them in play.</p>
  <ul class="reasons">
    <li>Tap anywhere for what the El Ni&ntilde;o seasons since 1979 did there, season by
      season, and whether the record can tell it from an ordinary year.</li>
    <li>The documented effects whose regions take in the point, marked in play or on
      the watch list for this event.</li>
    <li>Today's ocean temperature anomaly and flood class at that spot, read from
      NASA's own tiles, while those layers are on.</li>
    <li>Google's map, satellite view and Street View of the point, and links that
      open it in Google Maps and Google Earth.</li>
  </ul>
</section>"""


def controls(focus: str, now: str, nxt: str) -> str:
    """The El Nino menu: which effect, which season, the fade and how strong.

    The map opens on rainfall; the storm desk opens with the composites off,
    so the imagery under a storm is not tinted until asked for.
    """
    first = "PRECIP" if focus == "world" else ""
    effects = "".join(
        f'<button type="button" class="segbtn" data-enso-var="{key}" '
        f'aria-pressed="{"true" if key == first else "false"}">{words}</button>'
        for key, words in _EFFECTS)

    def season(code: str) -> str:
        tag = ("now" if code == now else "next" if code == nxt else "")
        return (f'<button type="button" class="segbtn" data-enso-season="{code}" '
                f'aria-pressed="{"true" if code == now else "false"}" '
                f'title="{esc(atlas.SEASON_LABEL[code])}">{code}'
                + (f' <span class="muted">{tag}</span>' if tag else "") + "</button>")

    return (
        '<details class="menu" id="enso-menu"><summary class="toolbtn">El Niño</summary>'
        '<div class="menubody ensomenu">'
        '<div class="ensorow"><span class="ensohead" id="enso-effect">Effect</span>'
        f'<div class="seg" role="group" aria-labelledby="enso-effect">{effects}</div></div>'
        '<div class="ensorow"><span class="ensohead" id="enso-season">Season</span>'
        '<div class="seg" role="group" aria-labelledby="enso-season">'
        + "".join(season(code) for code in atlas.SEASONS) + "</div></div>"
        '<label class="check"><input type="checkbox" id="enso-mask" data-enso-mask checked> '
        "Fade what the record cannot tell from an ordinary year</label>"
        '<label class="ensorange" for="enso-opacity">Strength of the colours'
        f'<input type="range" id="enso-opacity" min="0.2" max="0.9" step="0.05" '
        f'value="{OPACITY}"></label>'
        '<div class="ensorow"><span class="ensohead">Today, from NASA</span>'
        + "".join(f'<label class="check"><input type="checkbox" id="enso-tile-{key}" '
                  f'data-enso-tile="{key}"> {esc(words)}</label>'
                  for key, words in _TILE_WORDS)
        + '<label class="ensorange" for="enso-tile-opacity">Strength of NASA&rsquo;s tiles'
        f'<input type="range" id="enso-tile-opacity" min="0.2" max="1" step="0.05" '
        f'value="{TILE_OPACITY}"></label>'
        + '</div><div class="ensorow"><span class="ensohead">Regions</span>'
        + "".join(f'<label class="check"><input type="checkbox" id="enso-geo-{key}" '
                  f'data-enso-geo="{key}"{" checked" if focus == "world" and key == "boxes" else ""}> '
                  f"{esc(words)}</label>" for key, words in _GEO_WORDS)
        + "</div></div></details>"
    )


def legend() -> str:
    """The composite's key; the page fills it for the effect and season shown."""
    steps = "".join(f'<i style="background:var(--d{i})"></i>' for i in range(11))
    return ('<div class="keygroup ensokey" id="enso-key" hidden>'
            '<span class="keyhead" id="enso-name"></span>'
            f'<span class="ensoramp" id="enso-ramp">{steps}</span>'
            '<span id="enso-ends"></span><output id="enso-read"></output></div>'
            + _tile_legend())


def _tile_legend() -> str:
    """NASA's own scales for the ocean and flood tiles, shown while they are on."""
    sst = "".join(f'<i style="background:rgb({r},{g},{b})"></i>' for _, _, (r, g, b) in SST_COLOURS)
    faint = ENSO_TILES[1]["faint"]
    floods = "".join(f'<span class="key"><span class="swatch" style="background:rgb({r},{g},{b})'
                     + (f';opacity:{FAINT}' if [r, g, b] in faint else "") + '"></span>'
                     + esc(label + (" (drawn faint)" if [r, g, b] in faint else "")) + "</span>"
                     for (r, g, b), label in FLOOD_CLASSES)
    return ('<div class="keygroup ensokey" id="enso-sst-key" hidden>'
            '<span class="keyhead">Ocean today: sea surface temperature anomaly, GHRSST MUR</span>'
            f'<span class="ensoramp sstramp">{sst}</span>'
            f'<span>{_sst_label(None, -3.0)} to {_sst_label(3.0, None)}, in 0.1 °C steps: '
            "NASA's own scale, against MUR's own climatology</span><output></output></div>"
            '<div class="keygroup ensokey" id="enso-floods-key" hidden>'
            '<span class="keyhead">Floods, last 3 days: MODIS, Terra and Aqua</span>'
            f"{floods}<output></output></div>")


def css() -> str:
    return """
#enso-cells { position: absolute; inset: 0; width: 100%; height: 100%; z-index: 5;
  pointer-events: none; }
.ensomenu { min-width: 300px; }
.ensorow { display: flex; flex-direction: column; gap: 4px; padding: 6px 0; }
.ensohead { font-size: 0.78rem; font-weight: 600; color: var(--ink2); }
.segbtn .muted { font-weight: 400; opacity: 0.75; }
.ensorange { display: flex; flex-direction: column; gap: 2px; font-size: 0.86rem;
  padding: 6px 0 8px; }
.ensorange input { width: 100%; min-height: 32px; margin: 0; }
.ensokey { gap: 4px 10px; }
.ensoramp { display: inline-flex; border-radius: 3px; overflow: hidden;
  box-shadow: 0 0 0 1px rgba(0,0,0,.25); }
.ensoramp i { display: block; width: 14px; height: 10px; }
#enso-read { color: var(--ink); flex-basis: 100%; }
.ensohere { width: 100%; border-collapse: collapse; font-size: 0.8rem; margin: 4px 0 6px; }
.ensohere th, .ensohere td { text-align: left; vertical-align: top; padding: 5px 6px 5px 0;
  border-bottom: 1px solid var(--border); white-space: normal; }
.ensohere thead th { font-size: 0.74rem; color: var(--ink2); }
.ensohere tbody th { white-space: nowrap; }
.ensohere tbody th .muted { display: block; font-weight: 400; white-space: normal; }
.sstramp i { width: 3px; }
#overlay .region { fill: var(--ink); fill-opacity: 0.03; stroke: var(--ink); stroke-width: 1px;
  stroke-dasharray: 5 4; stroke-opacity: 0.7; }
#overlay .region.play { fill-opacity: 0.08; stroke-width: 2px; stroke-dasharray: none;
  stroke-opacity: 0.9; }
#overlay .ninocase { fill: none; stroke: var(--plane); stroke-width: 4px; stroke-opacity: 0.6; }
#overlay .ninobox { fill: none; stroke: var(--ink); stroke-width: 1.5px; stroke-dasharray: 6 4; }
#overlay .pinnedcase { fill: none; stroke: var(--plane); stroke-width: 5px; stroke-opacity: 0.85; }
#overlay .pinned { fill: none; stroke: var(--ink); stroke-width: 2px; }
#overlay.bigcell .pinned, #overlay.bigcell .pinnedcase { display: none; }
.gframe { margin: 8px 0 4px; }
.gframe iframe { width: 100%; height: 320px; border: 0; border-radius: 10px; }
"""


# Taken into the desk's script at its /*WORLDMAP*/ marker.
_JS = r"""
  // ---- the map: El Nino's effects, street by street (worldmap.py) ----------
  // The atlas's composites: the El Nino seasons since 1979 minus the ordinary
  // ones, per 2.5 degree (rainfall) or 2 degree (temperature) cell, drawn as
  // the atlas's field, blended between the cell centres, on a canvas under the
  // map's own names, in the atlas's colours to its full scale.
  var GRIDS = {}, RAMP_RGB = [];
  var ensoFirst = document.querySelector('[data-enso-var][aria-pressed="true"]');
  function geoOn(key) { var b = document.querySelector('[data-enso-geo="' + key + '"]'); return !!(b && b.checked); }
  S.enso = {variable: (ensoFirst && ensoFirst.getAttribute("data-enso-var")) || null,
            season: D.enso.now, mask: true, opacity: D.enso.opacity, tileOpacity: D.enso.tile_opacity,
            tiles: {}, regions: geoOn("regions"), boxes: geoOn("boxes"), shown: null};
  if ($("enso-tiles")) $("enso-tiles").style.opacity = S.enso.tileOpacity;
  function gridAxis(text) { return String(text).split(",").map(Number); }
  function gridPlane(name, season, kind) {
    var key = name + season + kind, v = D.enso.grids[name];
    if (GRIDS[key]) return GRIDS[key];
    return (GRIDS[key] = v.seasons[season][kind].split("\n").filter(Boolean).map(function (row) {
      return row.split(",").map(function (c) { return c === "_" ? null : +c / v.scale; });
    }));
  }
  function gridAxes(name) {
    var key = name + "@axes", v = D.enso.grids[name];
    return GRIDS[key] || (GRIDS[key] = [gridAxis(v.lats), gridAxis(v.lons)]);
  }
  // Python's atlas._index and atlas._nearest_lon, step for step.
  function nearestAt(values, target) {
    var best = Infinity, at = 0;
    for (var i = 0; i < values.length; i++) { var g = Math.abs(values[i] - target); if (g < best) { best = g; at = i; } }
    return at;
  }
  function nearestLon(values, target) {
    var best = Infinity, at = 0;
    for (var i = 0; i < values.length; i++) {
      var g = Math.abs(((values[i] - target + 180) % 360 + 360) % 360 - 180);
      if (g < best) { best = g; at = i; }
    }
    return at;
  }
  function wrap180(lon) { var v = ((lon + 180) % 360 + 360) % 360 - 180; return v === -180 ? 180 : v; }
  function critOf(name, season) { var c = D.enso.significant[name][season]; return c == null ? Infinity : c; }
  // One cell at a point, as atlas.sample reads it.
  function cellAt(name, season, lon, lat) {
    var ax = gridAxes(name), lats = ax[0], lons = ax[1];
    var r = nearestAt(lats, lat), c = nearestLon(lons, ((lon % 360) + 360) % 360);
    var dy = lats.length > 1 ? Math.abs(lats[1] - lats[0]) / 2 : 0;
    var dx = lons.length > 1 ? Math.abs(lons[1] - lons[0]) / 2 : 0;
    return {value: gridPlane(name, season, "diff")[r][c], base: gridPlane(name, season, "base")[r][c],
            t: gridPlane(name, season, "t")[r][c], crit: critOf(name, season),
            lon0: wrap180(lons[c] - dx), lon1: wrap180(lons[c] + dx),
            lat0: Math.min(lats[r] - dy, lats[r] + dy), lat1: Math.max(lats[r] - dy, lats[r] + dy)};
  }
  // atlas.verdict and Cell.percent, rule for rule.
  function verdictOf(name, cell) {
    if (cell.value === null) return "no record";
    if (cell.t === null || Math.abs(cell.t) < cell.crit) return "no clear signal";
    if (name === "PRECIP") return cell.value > 0 ? "wetter" : "drier";
    return cell.value > 0 ? "warmer" : "cooler";
  }
  function percentOf(name, cell) {
    if (name !== "PRECIP" || cell.value === null || cell.base === null || cell.base < D.enso.dry_floor) return null;
    return cell.value / cell.base * 100;
  }
  // The documented effects whose footprints cover a point: regional, then
  // basin, then those true of everywhere; within each, the smallest box first,
  // as geo.at orders them (no box crosses the date line).
  function regionsAt(lon, lat) {
    var w = wrap180(lon), found = [], rank = {regional: 0, basin: 1, global: 2};
    (D.enso.links || []).forEach(function (l, i) {
      var area = Infinity;
      l.boxes.forEach(function (b) {
        if (w >= b[0] && w <= b[1] && lat >= b[2] && lat <= b[3]) area = Math.min(area, (b[1] - b[0]) * (b[3] - b[2]));
      });
      if (area < Infinity) found.push({link: l, area: area, i: i});
    });
    return found.sort(function (a, b) {
      return (rank[a.link.scope] || 0) - (rank[b.link.scope] || 0) || a.area - b.area || a.i - b.i;
    }).map(function (f) { return f.link; });
  }
  // Everything the record says of one point: each season's rainfall and
  // temperature cell with its verdict, the cells' size there, and the regions.
  function ensoHere(lon, lat) {
    var out = {lon: wrap180(lon), lat: lat, seasons: [], sizes: {}, regions: regionsAt(lon, lat)};
    D.enso.seasons.forEach(function (s) {
      var row = {season: s, now: s === D.enso.now, next: s === D.enso.next};
      ["PRECIP", "AIR"].forEach(function (n) {
        var c = cellAt(n, s, lon, lat);
        row[n] = {cell: c, verdict: verdictOf(n, c), percent: percentOf(n, c)};
      });
      out.seasons.push(row);
    });
    ["PRECIP", "AIR"].forEach(function (n) {
      var c = cellAt(n, D.enso.now, lon, lat), dx = (c.lon1 - c.lon0 + 360) % 360 || 360, dy = c.lat1 - c.lat0;
      out.sizes[n] = {dx: dx, dy: dy, kmx: dx * 111.32 * Math.cos(rad(lat)), kmy: dy * 110.57};
    });
    return out;
  }
  function ensoCellText(name, got) {
    var c = got.cell, unit = D.enso.grids[name].unit;
    if (c.value === null) return name === "AIR" ? "no record: the temperature grid is land only" : "no record";
    var text = signedText(c.value, 2) + " " + unit;
    if (name === "PRECIP" && c.base !== null) {
      text += " against an ordinary " + c.base.toFixed(2) + (got.percent === null ? "" : " (" + signedText(got.percent, 0) + "%)");
    }
    text += ", |t| " + (c.t === null ? "n/a" : Math.abs(c.t).toFixed(2));
    text += isFinite(c.crit) ? ", needs " + c.crit.toFixed(2) : ", too few events to test";
    return esc(text) + ": <b>" + esc(got.verdict) + "</b>";
  }
  function ensoHereHtml(h) {
    var html = ["<h4>El Niño here</h4>",
      '<p class="method">What the El Niño seasons since 1979 (RONI +1.0 or more) did here against the neutral ones ' +
      "(RONI within 0.5), season by season. " +
      "It is the record of past events, not this season’s forecast.</p>",
      '<table class="ensohere"><thead><tr><th>Season</th><th>Rainfall</th><th>Temperature</th></tr></thead><tbody>'];
    h.seasons.forEach(function (row) {
      var mark = row.now ? " (now)" : row.next ? " (next)" : "";
      html.push("<tr><th scope=\"row\">" + esc(row.season + mark) + '<span class="muted"> ' +
                esc(D.enso.season_label[row.season]) + "</span></th><td>" + ensoCellText("PRECIP", row.PRECIP) +
                "</td><td>" + ensoCellText("AIR", row.AIR) + "</td></tr>");
    });
    html.push("</tbody></table>");
    var p = h.sizes.PRECIP, a = h.sizes.AIR;
    html.push('<p class="method">Rainfall is one ' + p.dx.toFixed(1) + "° by " + p.dy.toFixed(1) + "° cell, about " +
              Math.round(p.kmx) + " by " + Math.round(p.kmy) + " km here; temperature one " + a.dx.toFixed(1) + "° by " +
              a.dy.toFixed(1) + "° cell, about " + Math.round(a.kmx) + " by " + Math.round(a.kmy) +
              " km. Each value is the whole cell’s, not this street’s.</p>");
    html.push("<details><summary>Events sampled</summary>");
    D.enso.seasons.forEach(function (s) {
      var m = D.enso.grids.PRECIP.meta[s];
      html.push('<p class="method">' + esc(s) + ": " + m.warm_events.length + " El Niños (" + m.warm_months +
                " months) against " + m.base_years + " neutral years: " + esc(m.warm_events.join(", ")) + ".</p>");
    });
    html.push("</details>");
    var local = h.regions.filter(function (l) { return l.scope !== "global"; });
    var everywhere = h.regions.filter(function (l) { return l.scope === "global"; });
    function region(l) {
      var said = l.status === "in play" ? "In play this event: " + l.likelihood + (l.timing ? ", " + l.timing : "") + "."
               : l.status === "watch" ? "On the watch list this event." : "";
      return "<li><b>" + esc(l.region) + "</b>: " + esc(l.effect) + " (" + esc(l.window) + ", " + esc(l.confidence) +
             " confidence)." + (said ? " <b>" + esc(said) + "</b>" : "") + "</li>";
    }
    html.push("<h4>Documented effects here</h4>");
    html.push(local.length ? '<ul class="wwlist">' + local.map(region).join("") + "</ul>"
                           : "<p>No regional effect in the catalogue has a footprint here.</p>");
    if (everywhere.length) html.push("<p>Everywhere:</p><ul class=\"wwlist\">" + everywhere.map(region).join("") + "</ul>");
    return html.join("");
  }
  // ---- Google's own map of the point, on request ---------------------------
  // Google's tiles are not drawn on this map (its terms allow them only
  // through its own map); its embed and its Maps URLs are, and nothing is
  // asked of Google until a button is pressed.
  function googleZoom(z) { return Math.max(3, Math.min(21, Math.round(z))); }
  function googleEmbed(kind, lat, lon, z) {
    var at = lat.toFixed(6) + "," + wrap180(lon).toFixed(6);
    if (kind === "street") return "https://maps.google.com/maps?layer=c&cbll=" + at + "&cbp=12,0,0,0,0&output=svembed";
    return "https://maps.google.com/maps?q=" + at + "&t=" + (kind === "satellite" ? "k" : "m") +
           "&z=" + googleZoom(z) + "&output=embed";
  }
  function googleLinks(lat, lon, z) {
    var at = lat.toFixed(6) + "," + wrap180(lon).toFixed(6), zoom = googleZoom(z);
    var maps = "https://www.google.com/maps/@?api=1&map_action=map&center=" + at + "&zoom=" + zoom + "&basemap=";
    return {map: maps + "roadmap", satellite: maps + "satellite",
            street: "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=" + at,
            earth: "https://earth.google.com/web/@" + at + ",0a," +
                   Math.round(591657550.5 / Math.pow(2, zoom)) + "d,35y,0h,0t,0r"};
  }
  function googleHtml(lat, lon, z) {
    var l = googleLinks(lat, lon, z);
    var kinds = [["map", "Map"], ["satellite", "Satellite"], ["street", "Street View"]];
    return "<h4>Google Maps here</h4>" +
      '<div class="herebtns">' + kinds.map(function (k) {
        return '<button type="button" class="toolbtn" data-google="' + k[0] + '" aria-pressed="false">' + k[1] + "</button>";
      }).join("") + "</div>" +
      '<div id="google-frame" class="gframe" hidden></div>' +
      '<p class="method">Nothing goes to Google until a button is pressed; then Google’s own map loads here and ' +
      "Google receives this position. Street View opens on the nearest imagery Google has, which can be some way off.</p>" +
      '<p class="links">' + [["map", "Google Maps"], ["satellite", "Google satellite"], ["street", "Street View"],
                             ["earth", "Google Earth"]].map(function (k) {
        return '<a href="' + esc(l[k[0]]) + '" target="_blank" rel="noopener" data-glink="' + k[0] + '">' + k[1] + " ↗</a>";
      }).join("") + "</p>";
  }
  // Here is written as a flight to a found place begins, so its links to
  // Google take the zoom of each view the map settles on.
  function googleRelink() {
    if (!S.here) return;
    var l = googleLinks(S.here.lat, S.here.lon, S.z);
    document.querySelectorAll("#here a[data-glink]").forEach(function (a) { a.setAttribute("href", l[a.getAttribute("data-glink")]); });
  }
  // The Google buttons, the one whose frame is open pressed ("" for none).
  function googlePressed(kind) {
    document.querySelectorAll("[data-google]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-google") === kind ? "true" : "false");
    });
  }
  // Google's own map of S.here, at the view's zoom; the pressed button again
  // closes it.
  function googleFrame(kind) {
    var box = $("google-frame");
    if (!box || !S.here) return;
    var closing = !!S.google && S.google.kind === kind && !box.hidden;
    googlePressed(closing ? "" : kind);
    box.innerHTML = "";
    if (closing) { S.google = null; box.hidden = true; return; }
    S.google = {kind: kind, lon: S.here.lon, lat: S.here.lat};
    var frame = document.createElement("iframe");
    frame.setAttribute("title", {map: "Google Maps", satellite: "Google Maps satellite view",
                                 street: "Google Street View"}[kind] + " of " + S.here.label);
    frame.setAttribute("loading", "lazy");
    frame.setAttribute("referrerpolicy", "no-referrer-when-downgrade");
    frame.setAttribute("allowfullscreen", "");
    frame.setAttribute("src", googleEmbed(kind, S.here.lat, S.here.lon, S.z));
    box.appendChild(frame);
    box.hidden = false;
  }
  // ---- the Nino regions and the impact regions -------------------------------
  // A box in world units, west edge to east edge: Nino-4's 160E to 210E runs
  // east across the date line, not west across the world.
  function boxPath(lon0, lon1, lat0, lat1, k) {
    return "M" + X(lon0, k) + " " + Y(lat1) + "H" + X(lon1, k) + "V" + Y(lat0) + "H" + X(lon0, k) + "Z";
  }
  // A region's boxes as one place, in world fractions: each box is taken on
  // the side of the date line nearer the first, so the Pacific islands'
  // boxes either side of 180 make one view, not the width of the world.
  function regionBox(l) {
    var ref = (l.boxes[0][0] + l.boxes[0][1]) / 2, x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    l.boxes.forEach(function (b) {
      var shift = Math.round((ref - (b[0] + b[1]) / 2) / 360) * 360;
      x0 = Math.min(x0, mx(b[0] + shift)); x1 = Math.max(x1, mx(b[1] + shift));
      y0 = Math.min(y0, my(clamp(b[3], -85, 85))); y1 = Math.max(y1, my(clamp(b[2], -85, 85)));
    });
    return {x0: x0, x1: x1, y0: y0, y1: y1};
  }
  // The regions under everything else drawn: the impact regions (the ones
  // true of everywhere left out), every one while they are ticked, else the
  // one Show asked for alone, solid where this event puts it in play; CPC's
  // boxes; and the composite cell under the pin while one is shown.
  function ensoGeo() {
    var h = [];
    if (S.enso.regions || S.enso.shown) (D.enso.links || []).forEach(function (l) {
      if (l.scope === "global" || !(S.enso.regions || l.region === S.enso.shown)) return;
      var cls = l.status === "in play" ? "region play" : "region";
      l.boxes.forEach(function (b) {
        h.push('<path class="' + cls + '" d="' + boxPath(b[0], b[1], b[2], b[3], near(mx((b[0] + b[1]) / 2))) + '"/>');
      });
    });
    // Each box on a light case, so the dashes show over dark imagery too.
    if (S.enso.boxes) (D.enso.boxes || []).forEach(function (b) {
      var d = boxPath(b.lon0, b.lon1, b.lat0, b.lat1, near(mx((b.lon0 + b.lon1) / 2)));
      h.push('<path class="ninocase" d="' + d + '"/><path class="ninobox" d="' + d + '"/>');
    });
    if (S.enso.variable && S.pin) {
      var c = cellAt(S.enso.variable, S.enso.season, S.pin.lon, S.pin.lat);
      var lon1 = c.lon1 < c.lon0 ? c.lon1 + 360 : c.lon1, d = boxPath(c.lon0, lon1, c.lat0, c.lat1, near(mx((c.lon0 + lon1) / 2)));
      h.push('<path class="pinnedcase" d="' + d + '"/><path class="pinned" d="' + d + '"/>');
    }
    return h.join("");
  }
  // Each box named with this week's anomaly, above its northwest corner, or
  // under the box where a neighbour's name has the room above; each region
  // in play named at its anchor from zoom 3, where a name fits, and the one
  // Show asked for, whatever its status.
  function ensoLabels(sx, sy, off, label) {
    var out = [];
    if (S.enso.boxes) (D.enso.boxes || []).forEach(function (b) {
      copies(mx((b.lon0 + b.lon1) / 2), 200).forEach(function (k) {
        var x = sx(b.lon0, k), y = sy(b.lat1) - 9, under = sy(b.lat0) + 13;
        var lines = [[b.label + (b.anomaly === null ? "" : " " + signedText(b.anomaly, 2) + " °C"), "dl2"]];
        if (off(x, y, 0)) return;
        out.push(label(x, y, 0, lines) || (off(x, under, 0) ? "" : label(x, under, 0, lines)));
      });
    });
    if ((S.enso.regions || S.enso.shown) && S.z >= 3) (D.enso.links || []).forEach(function (l) {
      if (l.scope === "global") return;
      if (l.region !== S.enso.shown && !(S.enso.regions && l.status === "in play")) return;
      var b = l.boxes[0], lon = (b[0] + b[1]) / 2;
      copies(mx(lon), 200).forEach(function (k) {
        var x = sx(lon, k), y = sy((b[2] + b[3]) / 2);
        if (off(x, y, 0)) return;
        out.push(label(x, y, 0, [[l.region, "dl2"]]));
      });
    });
    return out;
  }
  // The map flown to a region's boxes, drawn alone unless every region is on;
  // asked again, the region put away and the map left where it is.
  function showRegion(name) {
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    var l = (D.enso.links || []).filter(function (x) { return x.region === name; })[0];
    if (!l) return false;
    if (S.enso.shown === name) { setEnso({shown: null}); return true; }
    setEnso({shown: name});
    animate(viewFor({box: regionBox(l)}));
    var box = map.getBoundingClientRect();
    if (box.top < 0 || box.bottom > window.innerHeight) map.scrollIntoView({block: "start", behavior: "smooth"});
    return true;
  }
  // ---- NASA's own tiles: today's ocean, the last three days' floods ----------
  // A pixel back to the entry of NASA's colour map it was painted from: the
  // nearest within a hair (the PNGs are paletted, so a pixel is exact unless
  // a browser's colour handling moves it), transparent where nothing is mapped.
  function classify(entries, px) {
    if (px[3] < 128) return {transparent: true};
    var best = null, bestd = 7;
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i].rgb, d = Math.abs(e[0] - px[0]) + Math.abs(e[1] - px[1]) + Math.abs(e[2] - px[2]);
      if (d < bestd) { bestd = d; best = entries[i]; }
    }
    return best;
  }
  // The classes drawn faint: their pixels' alpha cut to the given strength.
  function fadePixels(data, rgbs, strength) {
    var n = 0, a = Math.round(255 * strength);
    for (var i = 0; i + 3 < data.length; i += 4) {
      if (data[i + 3] < 128) continue;
      for (var j = 0; j < rgbs.length; j++) {
        var c = rgbs[j];
        if (Math.abs(data[i] - c[0]) + Math.abs(data[i + 1] - c[1]) + Math.abs(data[i + 2] - c[2]) < 7) { data[i + 3] = a; n++; break; }
      }
    }
    return n;
  }
  // A tile with a class to draw faint is drawn again from a canvas, once.
  function fadeTile(img) {
    img._faded = true;
    try {
      var cv = document.createElement("canvas");
      cv.width = img.naturalWidth || 256; cv.height = img.naturalHeight || 256;
      var cx = cv.getContext("2d", {willReadFrequently: true});
      cx.drawImage(img, 0, 0);
      var data = cx.getImageData(0, 0, cv.width, cv.height);
      if (!fadePixels(data.data, img._faint, D.enso.faint)) return false;
      cx.putImageData(data, 0, 0);
      img.src = cv.toDataURL();
      return true;
    } catch (err) { return false; }   // drawn as NASA made it
  }
  function ensoTileLayers() { return D.layers.filter(function (l) { return l.kind === "enso"; }); }
  // The switched-on tile layers, each at the latest day GIBS lists; none past
  // zoom 12, where one of their pixels would fill much of the view.
  function ensoTileSpecs() {
    var specs = [];
    if (S.z > D.enso.hide_above || S.then) return specs;
    D.layers.filter(function (l) { return l.kind === "enso"; }).forEach(function (l, i) {
      if (S.enso.tiles[l.id]) specs.push({key: l.id, cells: cells(l.id, 0).cells, visible: true, z: i});
    });
    return specs;
  }
  function ensoHiddenText(l) {
    var size = l.pixel_km >= 1 ? l.pixel_km + " km" : Math.round(l.pixel_km * 1000) + " m";
    return l.name + " hidden past zoom " + D.enso.hide_above + ": its " + size + " pixels would be " +
           Math.round(Math.pow(2, S.z - l.zoom)) + " screen pixels across.";
  }
  // Where a switched-on tile layer stands, for its key.
  function ensoTileState(l) {
    if (S.z > D.enso.hide_above) return ensoHiddenText(l);
    var s = source(l.id), f = frameOf(s, 0), d = s && DOM[s.name];
    if (f) return (l.id === "floods" ? "Three days to " : "Day of ") + dayText(f.key) + ". Tap a point to read it.";
    if (S.imagery === "offline") return "Offline: NASA's tiles need the network.";
    if ((d && d.unanswered) || S.imagery === "unreachable") return "NASA GIBS did not answer.";
    if (d && d.failed) return "NASA GIBS lists no recent day for it.";
    return "Asking NASA GIBS for the latest day.";
  }
  function ensoTileLegend() {
    ensoTileLayers().forEach(function (l) {
      var key = $("enso-" + l.id + "-key"), on = !!S.enso.tiles[l.id] && !S.then;
      if (!key) return;
      if (key.hidden !== !on) key.hidden = !on;
      if (!on) return;
      var out = key.querySelector("output"), text = ensoTileState(l);
      if (out && out.textContent !== text) out.textContent = text;
    });
  }
  // For the pill: the switched-on layers hidden at this zoom.
  function ensoTileMore() {
    if (S.z <= D.enso.hide_above) return [];
    return ensoTileLayers().filter(function (l) { return S.enso.tiles[l.id]; }).map(ensoHiddenText);
  }
  // For the credit line: NASA's words for each layer drawn.
  function ensoWhat(l, f) {
    var day = f ? dayText(f.key) : "the latest day";
    return l.id === "floods" ? "Floods, 3 days to " + day : "Ocean today (MUR SST anomaly, " + day + ")";
  }
  // One pixel of the day's tile under a point, at the layer's own zoom, read
  // back to NASA's own bin or class: a sentence, never a rejection, and the
  // day whose pixel it read ("" when none was).
  function readEnso(id, lon, lat) {
    var l = LAYERS[id], s = source(id), entries = D.enso.colours[id];
    return new Promise(function (resolve) {
      function answer(text, day) { resolve({text: text, day: day || ""}); }
      if (!l || !s || !entries) { answer(""); return; }
      function attempt(tries) {
        var f = frameOf(s, 0);
        if (!f) {
          ask(s);
          if (tries > 0 && S.imagery !== "offline" && S.imagery !== "unreachable") {
            setTimeout(function () { attempt(tries - 1); }, 1000);
            return;
          }
          answer(ensoWhat(l, null) + ": " + (S.imagery === "offline" ? "offline, NASA's tiles need the network" : "NASA GIBS did not answer"));
          return;
        }
        var n = Math.pow(2, l.zoom), x = mx(wrap(lon)) * n, y = clamp(my(lat), 0, 0.9999999) * n;
        var col = Math.floor(x), row = Math.floor(y), img = new Image();
        img.crossOrigin = "anonymous";
        img.onload = function () {
          var px = null;
          try {
            var cv = document.createElement("canvas");
            cv.width = cv.height = 256;
            var cx = cv.getContext("2d", {willReadFrequently: true});
            cx.drawImage(img, 0, 0, 256, 256);
            px = cx.getImageData(Math.min(255, Math.floor((x - col) * 256)), Math.min(255, Math.floor((y - row) * 256)), 1, 1).data;
          } catch (err) { px = null; }
          if (!px) { answer(ensoWhat(l, f) + ": the tile could not be read"); return; }
          var got = classify(entries, px), said;
          if (got === null) said = "a colour not on NASA’s scale";
          else if (got.transparent) said = l.id === "floods" ? "nothing mapped here: no water seen, or no data" : "nothing mapped here: land, ice or no data";
          else said = l.id === "floods" ? got.label : got.label + " at this pixel, on NASA’s own colour scale";
          answer(ensoWhat(l, f) + ": " + said, f.key);
        };
        img.onerror = function () { answer(ensoWhat(l, f) + ": NASA GIBS did not answer"); };
        img.src = tileUrl(s, f.key, l.zoom, row, ((col % n) + n) % n);
      }
      attempt(8);
    });
  }
  // Here's readings of NASA's tiles, by layer, day and point: Here written
  // anew (each take writes it) shows a reading it has had, not asked again.
  var TODAY = {};
  function todayKey(id, day, lon, lat) { return [id, day, lon, lat].join("|"); }
  // Here: a line for each switched-on tile layer, filled once its pixel is
  // read, or at once with the reading of the day's pixel already had.
  function ensoTodayHtml(lon, lat) {
    var on = ensoTileLayers().filter(function (l) { return S.enso.tiles[l.id]; });
    if (!on.length) return "";
    return "<h4>Today here, from NASA</h4>" + on.map(function (l) {
      var f = frameOf(source(l.id), 0), had = f && TODAY[todayKey(l.id, f.key, lon, lat)];
      return '<p id="here-' + l.id + '">' + esc(had || ensoWhat(l, f) + ": reading NASA’s tile…") + "</p>";
    }).join("");
  }
  function ensoTodayRead(lon, lat) {
    ensoTileLayers().forEach(function (l) {
      var f = frameOf(source(l.id), 0);
      if (!S.enso.tiles[l.id] || (f && TODAY[todayKey(l.id, f.key, lon, lat)])) return;
      readEnso(l.id, lon, lat).then(function (got) {
        if (got.day) TODAY[todayKey(l.id, got.day, lon, lat)] = got.text;
        var p = $("here-" + l.id);
        if (p && got.text && S.here && S.here.lon === lon && S.here.lat === lat) p.textContent = got.text;
      });
    });
  }
  // Past 90 pixels a cell the colour yields, down to 0.42, so the streets
  // show through a cell that is now most of the screen.
  function cellWeight(px) { var f = D.enso.fade; return px < f[0] ? 1 : Math.max(f[2], 1 - (px - f[0]) / f[1]); }
  // How wide one of the grid's cells is on a world W pixels across.
  function cellPx(name, W) {
    var lons = gridAxes(name)[1];
    return (lons.length > 1 ? Math.abs(lons[1] - lons[0]) : 2) / 360 * W;
  }
  // Whether a cell fits a view w by h pixels. The cell under the pin is
  // outlined only while it does: wider or taller, its outline is a lone line
  // or two across the streets, with no edge of colour beside them to be the
  // edge of. Mercator draws a cell taller the further it is from the equator:
  // at 60 N, twice as tall as it is wide.
  function cellFits(name, W, w, h, cell) {
    return cellPx(name, W) <= w && (my(cell.lat0) - my(cell.lat1)) * W <= h;
  }
  // ---- the composite as a field -----------------------------------------------
  // The atlas's field, taken in here from atlasview.FIELD_JS: blended between
  // the cell centres, while a tap still reads the whole cell (cellAt).
  /*FIELD*/
  function fieldGrid(name, season) {
    var key = name + season + "@field", ax = gridAxes(name);
    return GRIDS[key] || (GRIDS[key] = fieldOf(ax[0], ax[1], gridPlane(name, season, "diff"),
                                               gridPlane(name, season, "t"), critOf(name, season)));
  }
  // The field over a view w by h css pixels, a pixel every `step` of them on
  // the lattice fixed at the world's corner, at its centre's longitude and
  // latitude, clear off the top and bottom of the world: `rgb` the ramp as
  // numbers, `dim` the strength of what the t test does not pass while `mask`
  // is on, `into` a buffer to fill again. x and y are where it starts.
  function compositeField(name, season, mask, o, w, h, step, rgb, dim, into) {
    var x0 = fieldStart(o.left, step), y0 = fieldStart(o.top, step), fw = fieldSpan(w, step), fh = fieldSpan(h, step);
    var lons = new Float64Array(fw), lats = new Float64Array(fh), i, j;
    for (i = 0; i < fw; i++) lons[i] = lonOf((x0 + (i + 0.5) * step - o.left) / o.W);
    for (j = 0; j < fh; j++) {
      var wy = (y0 + (j + 0.5) * step - o.top) / o.W;
      lats[j] = wy < 0 || wy > 1 ? NaN : latOf(wy);
    }
    var f = paintField(fieldGrid(name, season), lons, lats,
                       {invert: D.enso.grids[name].invert, lim: D.enso.limits[name], rgb: rgb, mask: mask, dim: dim}, into);
    f.x = x0; f.y = y0;
    return f;
  }
  // The ramp is the page's own tokens, read again when the theme changes, by
  // the button or the system's own: read once, the composite stayed in the
  // light theme's colours under the dark theme's legend.
  function readRamp() {
    var cs = getComputedStyle(document.documentElement);
    RAMP_RGB = [];
    for (var i = 0; i < 11; i++) RAMP_RGB.push(hexRgb(cs.getPropertyValue("--d" + i)));
  }
  function rethemed() { RAMP_RGB = []; requestRender(); }
  if (window.MutationObserver) {
    new MutationObserver(rethemed).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
  }
  if (window.matchMedia) {
    var darkScheme = window.matchMedia("(prefers-color-scheme: dark)");
    if (darkScheme.addEventListener) darkScheme.addEventListener("change", rethemed);
    else if (darkScheme.addListener) darkScheme.addListener(rethemed);
  }
  var ensoCanvas = $("enso-cells"), ensoCtx = ensoCanvas && ensoCanvas.getContext ? ensoCanvas.getContext("2d") : null;
  var fieldCanvas = null, fieldCtx = null, fieldImage = null;
  function drawComposite() {
    if (!ensoCtx) return;
    // Entered (thennow.py), the composite of today's season stands aside.
    var name = S.then ? null : S.enso.variable;
    if (ensoCanvas.hidden !== !name) ensoCanvas.hidden = !name;
    if (!name) return;
    var dpr = window.devicePixelRatio || 1, w = Math.round(S.w * dpr), h = Math.round(S.h * dpr);
    if (ensoCanvas.width !== w || ensoCanvas.height !== h) { ensoCanvas.width = w; ensoCanvas.height = h; }
    ensoCtx.clearRect(0, 0, w, h);
    ensoCanvas.style.opacity = S.enso.opacity;
    if (!RAMP_RGB.length) readRamp();
    var o = origin(), step = fieldStep(S.w, S.h);
    var pin = S.pin ? cellAt(name, S.enso.season, S.pin.lon, S.pin.lat) : null;
    svgEl.classList.toggle("bigcell", !!pin && !cellFits(name, o.W, S.w, S.h, pin));
    var f = compositeField(name, S.enso.season, S.enso.mask, o, S.w, S.h, step, RAMP_RGB, D.enso.mask,
                           fieldImage ? fieldImage.data : null);
    if (!fieldCanvas) { fieldCanvas = document.createElement("canvas"); fieldCtx = fieldCanvas.getContext("2d"); }
    if (!fieldImage || fieldImage.data !== f.data || fieldImage.width !== f.w) {
      fieldCanvas.width = f.w; fieldCanvas.height = f.h; fieldImage = new ImageData(f.data, f.w, f.h);
    }
    fieldCtx.putImageData(fieldImage, 0, 0);
    ensoCtx.imageSmoothingEnabled = true;
    ensoCtx.imageSmoothingQuality = "high";
    ensoCtx.globalAlpha = cellWeight(cellPx(name, o.W));
    ensoCtx.drawImage(fieldCanvas, f.x * dpr, f.y * dpr, f.w * step * dpr, f.h * step * dpr);
    ensoCtx.globalAlpha = 1;
  }
  function signedText(v, digits) { return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(digits); }
  var ensoSaid = "";
  // The reading changes as the view moves. On a line of its own, it only grows
  // while the key keeps its width, so the map above does not jump by a line,
  // and redraw all it holds, each time the centre crosses into a cell with
  // more or fewer words. A reading written anew, by a run taken in place,
  // keeps the height held.
  var readTall = 0, readWide = 0;
  function holdHeight(el) {
    var wide = el.parentNode ? el.parentNode.clientWidth : 0;
    if (wide !== readWide) { readWide = wide; readTall = 0; el.style.minHeight = ""; }
    readTall = Math.max(readTall, el.offsetHeight);
    if (el.style.minHeight !== readTall + "px") el.style.minHeight = readTall + "px";
  }
  // A new width is read again, whatever the words.
  window.addEventListener("resize", function () { ensoSaid = ""; });
  // The key: what is drawn, which end is which, and the cell under the centre
  // of the view, read by the same rule as a tap.
  function ensoLegend() {
    var key = $("enso-key"), name = S.then ? null : S.enso.variable;
    if (!key) return;
    if (key.hidden !== !name) key.hidden = !name;
    if (!name) return;
    var g = D.enso.grids[name], lim = D.enso.limits[name], season = S.enso.season, crit = critOf(name, season);
    var lon = wrap180(lonOf(S.x)), lat = latOf(S.y), c = cellAt(name, season, lon, lat);
    var word = verdictOf(name, c), read;
    if (c.value === null) read = "Centre of the view: no record" + (name === "AIR" ? " (the temperature grid is land only)." : ".");
    else {
      var pct = percentOf(name, c);
      read = "Centre of the view: " + signedText(c.value, 2) + " " + g.unit +
        (pct === null ? "" : " (" + signedText(pct, 0) + "% of an ordinary " + c.base.toFixed(2) + ")") + ", " + word +
        (c.t === null ? "" : "; |t| " + Math.abs(c.t).toFixed(2) + (isFinite(crit) ? ", needs " + crit.toFixed(2) : ", too few events to test")) + ".";
    }
    if (S.z >= 7) {
      var deg = (c.lon1 - c.lon0 + 360) % 360 || 360, across = Math.round(deg * 111.32 * Math.cos(rad(lat)));
      read += " One " + deg.toFixed(1) + "° cell is about " + across + " km across here: the colours blend between cell centres, and the value read is the whole cell's.";
    }
    var ends = name === "PRECIP" ? "−" + lim + " " + g.unit + " drier to +" + lim + " wetter"
             : "−" + lim + " " + g.unit + " cooler to +" + lim + " warmer";
    if (S.enso.mask) ends += "; faint where |t| is under " + (isFinite(crit) ? crit.toFixed(2) : "any value") + ", not told apart from an ordinary year";
    var said = [g.label + ", " + D.enso.season_label[season] + ": El Niño minus ordinary years", ends, read].join("|");
    if (said === ensoSaid) return;
    ensoSaid = said;
    $("enso-name").textContent = g.label + ", " + D.enso.season_label[season] + ": El Niño minus ordinary years";
    // Rainfall reads the ramp backwards, so its strip is turned round, as the atlas turns it.
    $("enso-ramp").style.flexDirection = g.invert ? "row-reverse" : "row";
    $("enso-ends").textContent = ends;
    $("enso-read").textContent = read;
    holdHeight($("enso-read"));
  }
  // The El Nino controls as S.enso has them: the menu's, and the regions'
  // Show, which a run taken in place brings anew in the panel.
  function ensoControls() {
    document.querySelectorAll("[data-enso-var]").forEach(function (b) {
      b.setAttribute("aria-pressed", (b.getAttribute("data-enso-var") || null) === S.enso.variable ? "true" : "false");
    });
    document.querySelectorAll("[data-enso-season]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-enso-season") === S.enso.season ? "true" : "false");
    });
    if ($("enso-mask")) $("enso-mask").checked = !!S.enso.mask;
    if ($("enso-opacity")) $("enso-opacity").value = S.enso.opacity;
    if ($("enso-tile-opacity")) $("enso-tile-opacity").value = S.enso.tileOpacity;
    if ($("enso-tiles")) $("enso-tiles").style.opacity = S.enso.tileOpacity;
    document.querySelectorAll("[data-enso-tile]").forEach(function (b) {
      b.checked = !!S.enso.tiles[b.getAttribute("data-enso-tile")];
    });
    document.querySelectorAll("[data-enso-geo]").forEach(function (b) {
      b.checked = !!S.enso[b.getAttribute("data-enso-geo")];
    });
    document.querySelectorAll("[data-show-region]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-show-region") === S.enso.shown ? "true" : "false");
    });
  }
  function setEnso(patch) {
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    for (var k in patch) S.enso[k] = patch[k];
    ensoControls();
    dirty();
    if ("tiles" in patch && S.here) showHere();
    return S.enso;
  }
  document.querySelectorAll("[data-enso-var]").forEach(function (b) {
    b.addEventListener("click", function () { setEnso({variable: b.getAttribute("data-enso-var") || null}); });
  });
  document.querySelectorAll("[data-enso-season]").forEach(function (b) {
    b.addEventListener("click", function () { setEnso({season: b.getAttribute("data-enso-season")}); });
  });
  if ($("enso-mask")) $("enso-mask").addEventListener("change", function (e) { setEnso({mask: e.target.checked}); });
  if ($("enso-opacity")) $("enso-opacity").addEventListener("input", function (e) { setEnso({opacity: +e.target.value}); });
  if ($("enso-tile-opacity")) $("enso-tile-opacity").addEventListener("input", function (e) { setEnso({tileOpacity: +e.target.value}); });
  document.querySelectorAll("[data-enso-geo]").forEach(function (b) {
    b.addEventListener("change", function () {
      var patch = {}, key = b.getAttribute("data-enso-geo");
      patch[key] = b.checked;
      // Every region ticked on or off: one shown alone is shown no longer.
      if (key === "regions") patch.shown = null;
      setEnso(patch);
    });
  });
  document.querySelectorAll("[data-enso-tile]").forEach(function (b) {
    b.addEventListener("change", function () {
      var tiles = {};
      for (var k in S.enso.tiles) tiles[k] = S.enso.tiles[k];
      tiles[b.getAttribute("data-enso-tile")] = b.checked;
      setEnso({tiles: tiles});
    });
  });
  function ramped() { readRamp(); dirty(); }
  if (window.MutationObserver) new MutationObserver(ramped).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
  if (window.matchMedia) {
    var schemeQuery = window.matchMedia("(prefers-color-scheme: dark)");
    if (schemeQuery.addEventListener) schemeQuery.addEventListener("change", ramped);
    else if (schemeQuery.addListener) schemeQuery.addListener(ramped);
  }

  // ---- streets and addresses: Esri's World Geocoder, only when asked ----------
  // The gazetteer answers as the reader types and sends nothing anywhere. The
  // geocoder is its last row: the words go to Esri only when that row is
  // chosen, for a single search whose answer is shown and not kept.
  var GEOCODER = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates";
  function geocodeUrl(q) {
    return GEOCODER + "?SingleLine=" + encodeURIComponent(q) + "&maxLocations=6&outFields=Match_addr,Type&f=json";
  }
  // Esri's candidates as places to fly to. An extent whose east edge is west
  // of its west edge crosses the date line, and is taken the short way round.
  function geocoded(answer) {
    var list = answer && answer.candidates;
    if (!Array.isArray(list)) return [];
    return list.slice(0, 6).filter(function (c) {
      return c && c.location && Number.isFinite(c.location.x) && Number.isFinite(c.location.y);
    }).map(function (c) {
      var a = c.attributes || {}, e = c.extent, box = null;
      if (e && [e.xmin, e.xmax, e.ymin, e.ymax].every(Number.isFinite)) {
        box = {x0: mx(e.xmin), x1: mx(e.xmax), y0: my(e.ymax), y1: my(e.ymin)};
        if (box.x1 < box.x0) box.x1 += 1;
      }
      return {kind: "address", label: a.Match_addr || c.address || "", deep: true, zoom: 16,
              sub: (a.Type || "Address") + " · Esri World Geocoder",
              lon: c.location.x, lat: c.location.y, box: box};
    });
  }
  function searchRow(text) {
    var q = String(text || "").trim();
    if (fold(q).length < 3 || coordinate(q)) return null;
    return {kind: "search", q: q, label: "Search streets and addresses for “" + q + "”",
            sub: "Sends these words to Esri’s World Geocoder"};
  }
  var geocoding = 0;
  function geocode(q) {
    var ticket = ++geocoding;
    closeList();
    findNote.hidden = false;
    findNote.textContent = "Asking Esri’s geocoder…";
    fetch(geocodeUrl(q)).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (answer) {
      if (ticket !== geocoding) return;
      if (!answer || answer.error) throw new Error("refused");
      var got = geocoded(answer);
      if (!got.length) { findNote.textContent = "Esri’s geocoder found nothing for “" + q + "”."; return; }
      findNote.hidden = true;
      found = got;
      showFound();
    }).catch(function () {
      if (ticket !== geocoding) return;
      findNote.hidden = false;
      findNote.textContent = "Esri’s geocoder did not answer (offline, or blocked); the gazetteer still works.";
    });
  }
""".replace("  /*FIELD*/\n", atlasview.FIELD_JS)
