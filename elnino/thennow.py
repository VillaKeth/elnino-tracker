"""Enter a place and see it before and after El Nino.

"Enter" drops into a point of the map as Google Maps' figure does, and shows
the same ground at two dates either side of the divider, the earlier on the
left, each date named with what ENSO was doing in the season around it: the
tracker's own record of the official index, RONI. Five archives hold the
dates, every one keyless and sent with CORS, as each answered on 29 September
2026:

* Esri's World Imagery Wayback: every release of World Imagery since
  February 2014, sub-metre where Esri has it, under the Esri Master License
  Agreement the map's World Imagery already runs under: drawn as the page is
  viewed, never exported. A release's tilemap names the release a tile last
  changed in, which is how Esri's own Wayback app finds the versions of one
  place, and its metadata service names when and by whom each was taken.
* NASA GIBS: Landsat and Sentinel-2 at 30 m (HLS, 2013 on), MODIS Terra's
  daily true colour (250 m, 2000 on), MODIS Terra's 16-day vegetation index
  (2000 on) and GHRSST MUR25's daily sea surface temperature anomaly (2002
  on).

Google's Street View cannot be had for a date: neither its embed nor its Maps
URLs take one. It stays one press away, and Google Maps' own "See more dates"
holds its older panoramas.
"""

from __future__ import annotations

from datetime import date

from . import classify, worldmap
from .svg import esc

# Esri's World Imagery Wayback as it answered on 29 September 2026: 196
# releases from 2014-02-20 to 2026-08-05, each with its item, its tiles and
# its metadata service, all sent with Access-Control-Allow-Origin: *.
WAYBACK = {
    "config": ("https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/"
               "waybackconfig.json"),
    "tilemap": ("https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/"
                "MapServer/tilemap/{release}/{z}/{y}/{x}"),
    "item": "https://www.arcgis.com/sharing/rest/content/items/{id}?f=json",
    # The pin's tile is walked at zoom 16. The metadata layer for a zoom is
    # 23 minus the zoom, 0 to 13, as Esri's Wayback app reads it: layer 7,
    # 2.4 m, at zoom 16.
    "level": 16,
    "metadata_layer": 7,
    # World Imagery's own credit, until a release's item page gives its own.
    "credit": "Esri, Vantor, Earthstar Geographics, and the GIS User Community",
}
NAMES_CREDIT = ("Roads and names: Esri, HERE, Garmin, (c) OpenStreetMap contributors, "
                "and the GIS user community.")

# Each source: what it is, its first day, the zoom it is drawn to and the
# zoom a place is entered at, as the spec's table has them.
SOURCES = (
    {"id": "archive", "kind": "wayback", "name": "Satellite archive (Esri)",
     "about": ("Esri World Imagery as each Wayback release since February 2014 showed it: "
               "sub-metre where Esri has it, each version named by the day its imagery "
               "was taken and by whom."),
     "first": "2014-02-20", "zoom": 19, "enter": 16},
    {"id": "hls", "kind": "hls", "name": "Landsat and Sentinel-2, 30 m",
     "about": ("NASA's Harmonized Landsat and Sentinel-2: a day's passes at 30 m, clouds as "
               "seen. Each side shows the nearest day with an image at the pin."),
     "first": "2013-03-22", "zoom": 13, "enter": 12, "pixel_km": 0.03,
     "credit": "HLS: NASA, from USGS Landsat and ESA Copernicus Sentinel-2."},
    {"id": "modis", "kind": "gibs", "name": "True colour, daily (MODIS Terra)",
     "about": "MODIS on Terra, one morning pass a day at 250 m, since February 2000.",
     "layer": "MODIS_Terra_CorrectedReflectance_TrueColor",
     "tms": "GoogleMapsCompatible_Level9", "tile_zoom": 9, "format": "jpeg",
     "first": "2000-02-24", "zoom": 13, "enter": 8, "pixel_km": 0.25,
     "credit": "MODIS Terra: NASA."},
    {"id": "ndvi", "kind": "gibs", "name": "Vegetation (MODIS NDVI, 16-day)",
     "about": ("MODIS Terra's vegetation index, a 16-day composite at 250 m: brown bare "
               "ground to dark green canopy; water and gaps are left clear."),
     "layer": "MODIS_Terra_L3_NDVI_16Day",
     "tms": "GoogleMapsCompatible_Level9", "tile_zoom": 9, "format": "png",
     "first": "2000-03-05", "zoom": 13, "enter": 7, "pixel_km": 0.25,
     "credit": "NDVI: MODIS Terra, NASA."},
    {"id": "sst", "kind": "gibs", "name": "Ocean temperature anomaly (MUR25)",
     "about": ("GHRSST MUR25: the daily sea surface temperature anomaly on a quarter-degree "
               "grid, since September 2002, against MUR's own climatology."),
     "layer": "GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies",
     "tms": "GoogleMapsCompatible_Level6", "tile_zoom": 6, "format": "png",
     "first": "2002-09-01", "zoom": 13, "enter": 4, "pixel_km": 25.0,
     "credit": "SST: GHRSST MUR25, NASA JPL."},
)

# The first season the page carries, DJF 2000, centred on January 2000: no
# archive here starts earlier. Events are offered for peaks from March 2000,
# MODIS's first full month.
FIRST_MONTH = date(2000, 1, 1)
PRESETS_FROM = date(2000, 3, 1)

# NASA's colour map for the 16-day NDVI, bin for bin, so a pixel reads back
# to its value: https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_L3_NDVI.xml,
# 29 Sep 2026. (low, high, rgb), [low, high); its fill and the bins below
# zero are drawn clear, and are not listed.
NDVI_COLOURS = (
    (0.0, 0.005, (241, 236, 236)), (0.005, 0.01, (241, 236, 237)),
    (0.01, 0.015, (239, 231, 231)), (0.015, 0.02, (239, 231, 232)),
    (0.02, 0.025, (236, 226, 226)), (0.025, 0.03, (236, 226, 227)),
    (0.03, 0.035, (226, 216, 216)), (0.035, 0.04, (226, 216, 217)),
    (0.04, 0.045, (225, 217, 212)), (0.045, 0.05, (225, 217, 213)),
    (0.05, 0.055, (224, 218, 210)), (0.055, 0.06, (224, 218, 211)),
    (0.06, 0.065, (221, 213, 203)), (0.065, 0.07, (221, 213, 204)),
    (0.07, 0.075, (229, 219, 205)), (0.075, 0.08, (229, 219, 206)),
    (0.08, 0.085, (225, 210, 197)), (0.085, 0.09, (225, 210, 198)),
    (0.09, 0.095, (223, 206, 193)), (0.095, 0.1, (223, 206, 194)),
    (0.1, 0.105, (221, 201, 188)), (0.105, 0.11, (221, 201, 189)),
    (0.11, 0.115, (215, 196, 179)), (0.115, 0.12, (215, 196, 180)),
    (0.12, 0.125, (209, 192, 171)), (0.125, 0.13, (209, 192, 172)),
    (0.13, 0.135, (205, 186, 158)), (0.135, 0.14, (205, 186, 159)),
    (0.14, 0.145, (200, 181, 165)), (0.145, 0.15, (200, 181, 166)),
    (0.15, 0.155, (192, 176, 150)), (0.155, 0.16, (192, 176, 151)),
    (0.16, 0.165, (185, 171, 155)), (0.165, 0.17, (185, 171, 156)),
    (0.17, 0.175, (180, 165, 149)), (0.175, 0.18, (180, 165, 150)),
    (0.18, 0.185, (176, 159, 142)), (0.185, 0.19, (176, 159, 143)),
    (0.19, 0.195, (176, 155, 137)), (0.195, 0.2, (176, 155, 138)),
    (0.2, 0.205, (177, 152, 131)), (0.205, 0.21, (177, 152, 132)),
    (0.21, 0.215, (176, 149, 125)), (0.215, 0.22, (176, 149, 126)),
    (0.22, 0.225, (176, 146, 120)), (0.225, 0.23, (176, 146, 121)),
    (0.23, 0.235, (172, 141, 115)), (0.235, 0.24, (172, 141, 116)),
    (0.24, 0.245, (169, 137, 110)), (0.245, 0.25, (169, 137, 111)),
    (0.25, 0.255, (165, 132, 104)), (0.255, 0.26, (165, 132, 105)),
    (0.26, 0.265, (161, 128, 99)), (0.265, 0.27, (161, 128, 100)),
    (0.27, 0.275, (157, 124, 94)), (0.275, 0.28, (157, 124, 95)), (0.28, 0.285, (154, 110, 89)),
    (0.285, 0.29, (154, 110, 90)), (0.29, 0.295, (150, 90, 70)), (0.295, 0.3, (150, 90, 71)),
    (0.3, 0.308, (191, 222, 119)), (0.308, 0.315, (191, 222, 120)),
    (0.315, 0.323, (176, 207, 104)), (0.323, 0.33, (176, 207, 105)),
    (0.33, 0.338, (167, 204, 75)), (0.338, 0.345, (167, 204, 76)),
    (0.345, 0.353, (164, 198, 61)), (0.353, 0.36, (164, 198, 62)),
    (0.36, 0.368, (160, 192, 48)), (0.368, 0.375, (160, 192, 49)),
    (0.375, 0.383, (150, 186, 32)), (0.383, 0.39, (150, 186, 33)),
    (0.39, 0.398, (143, 183, 21)), (0.398, 0.405, (143, 183, 22)),
    (0.405, 0.413, (135, 179, 10)), (0.413, 0.42, (135, 179, 11)), (0.42, 0.428, (128, 176, 5)),
    (0.428, 0.435, (128, 176, 6)), (0.435, 0.443, (120, 173, 0)), (0.443, 0.45, (120, 173, 1)),
    (0.45, 0.458, (110, 170, 0)), (0.458, 0.465, (110, 170, 1)), (0.465, 0.473, (100, 166, 0)),
    (0.473, 0.48, (100, 166, 1)), (0.48, 0.488, (93, 163, 0)), (0.488, 0.495, (93, 163, 1)),
    (0.495, 0.503, (86, 161, 0)), (0.503, 0.51, (86, 161, 1)), (0.51, 0.518, (82, 152, 0)),
    (0.518, 0.525, (82, 152, 1)), (0.525, 0.533, (83, 151, 0)), (0.533, 0.54, (83, 151, 1)),
    (0.54, 0.548, (78, 148, 0)), (0.548, 0.555, (78, 148, 1)), (0.555, 0.563, (72, 144, 0)),
    (0.563, 0.57, (72, 144, 1)), (0.57, 0.578, (67, 141, 0)), (0.578, 0.585, (67, 141, 1)),
    (0.585, 0.593, (62, 138, 0)), (0.593, 0.6, (62, 138, 1)), (0.6, 0.61, (57, 135, 0)),
    (0.61, 0.62, (57, 135, 1)), (0.62, 0.63, (51, 131, 0)), (0.63, 0.64, (51, 131, 1)),
    (0.64, 0.65, (46, 128, 0)), (0.65, 0.66, (46, 128, 1)), (0.66, 0.67, (41, 125, 0)),
    (0.67, 0.68, (41, 125, 1)), (0.68, 0.69, (33, 120, 0)), (0.69, 0.7, (33, 120, 1)),
    (0.7, 0.71, (29, 117, 0)), (0.71, 0.72, (29, 117, 1)), (0.72, 0.73, (25, 115, 0)),
    (0.73, 0.74, (25, 115, 1)), (0.74, 0.75, (18, 110, 0)), (0.75, 0.76, (18, 110, 1)),
    (0.76, 0.77, (10, 105, 0)), (0.77, 0.78, (10, 105, 1)), (0.78, 0.79, (8, 103, 0)),
    (0.79, 0.8, (8, 103, 1)), (0.8, 0.81, (5, 100, 0)), (0.81, 0.82, (5, 100, 1)),
    (0.82, 0.83, (0, 100, 0)), (0.83, 0.84, (0, 100, 1)), (0.84, 0.85, (0, 96, 0)),
    (0.85, 0.86, (0, 96, 1)), (0.86, 0.87, (0, 90, 0)), (0.87, 0.88, (0, 90, 1)),
    (0.88, 0.89, (0, 84, 0)), (0.89, 0.9, (0, 84, 1)), (0.9, 0.91, (0, 72, 0)),
    (0.91, 0.92, (0, 72, 1)), (0.92, 0.93, (0, 60, 0)), (0.93, 0.94, (0, 60, 1)),
    (0.94, 0.95, (0, 54, 0)), (0.95, 0.96, (0, 54, 1)), (0.96, 0.97, (0, 36, 0)),
    (0.97, 0.98, (0, 36, 1)), (0.98, 0.99, (0, 24, 0)), (0.99, 1.0, (0, 24, 1)),
)


def _tier_words(value: float) -> str:
    """classify's tier as words: "very strong El Niño", "weak La Niña", "neutral"."""
    tier = classify.intensity_tier(value)
    for ascii_name, name in (("El Nino", "El Ni\u00f1o"), ("La Nina", "La Ni\u00f1a")):
        if tier.endswith(ascii_name):
            return tier[: -len(ascii_name)].lower() + name
    return "neutral"


def _month_index(key: str) -> int:
    """Months from January 2000 to a "YYYY-MM" key."""
    return (int(key[:4]) - FIRST_MONTH.year) * 12 + int(key[5:7]) - 1


def season_rows(series) -> list:
    """Each season from DJF 2000 on as [centre month, label, value as CPC
    prints it, what it was]: its strength, and the episode it belonged to,
    the run of conditions still going and how long, or conditions short of
    an episode; otherwise neutral."""
    if not series:
        return []
    last = series[-1].centre
    member = {}
    for warm in (True, False):
        for episode in classify.find_episodes(series, warm):
            for season in episode.seasons:
                member[season.centre] = (episode, episode.latest.centre == last)
    rows = []
    for season in series:
        if season.centre < FIRST_MONTH:
            continue
        words = _tier_words(season.value)
        got = member.get(season.centre)
        if got:
            episode, going = got
            if episode.qualifies:
                words += f", the {episode.name} episode" + (", still going" if going else "")
            elif going:
                n = episode.length
                words += f" conditions, {n} season{'s' if n != 1 else ''} so far"
            else:
                words += " conditions, short of an episode"
        rows.append([f"{season.centre:%Y-%m}", season.label, classify.displayed(season.value), words])
    return rows


def _month(day: date) -> str:
    return f"{day:%b %Y}"


def _years_on(day: date, years: int) -> date:
    """The same day some years on (back, when negative); 29 February becomes the 28th."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def presets(series, built: date, index: str = "RONI") -> list:
    """The event menu, each entry two ISO dates for the sides.

    First "a year ago -> the latest", for the event now. Then, newest first,
    each El Nino episode whose peak season is centred on March 2000 or later:
    its developing year, a year before the peak to the peak, and its decaying
    year, the peak to a year after, the peak taken as the 15th of its season's
    centre month, each offered once both its dates have come. Each choice
    names its episode: the menu, closed, shows the choice and not its group."""
    year_ago = _years_on(built, -1)
    out = [{"id": "now", "group": "", "left": year_ago.isoformat(), "right": built.isoformat(),
            "label": f"A year ago \u2192 the latest ({_month(year_ago)} \u2192 {_month(built)})"}]
    episodes = [e for e in classify.find_episodes(series, True)
                if e.qualifies and e.peak.centre >= PRESETS_FROM]
    for n, episode in reversed(list(enumerate(episodes))):
        peak = episode.peak.centre.replace(day=15)
        before, after = _years_on(peak, -1), _years_on(peak, 1)
        name = f"{episode.name} El Ni\u00f1o"
        group = (f"{name}, peaking {episode.peak.label} at {index} "
                 f"{classify.displayed(episode.peak.value):+.1f}")
        for key, left, right, words in (
                ("before", before, peak,
                 f"{name}, developing: {_month(before)} \u2192 peak {_month(peak)}"),
                ("after", peak, after,
                 f"{name}, decaying: peak {_month(peak)} \u2192 {_month(after)}")):
            if right <= built:
                out.append({"id": f"ep{n}-{key}", "group": group, "left": left.isoformat(),
                            "right": right.isoformat(), "label": words})
    return out


def _scales() -> dict:
    """NASA's colour maps as the page reads a pixel back: the ocean's (the
    map's own, worldmap.SST_COLOURS) and the vegetation index's."""
    return {"sst": [{"lo": lo, "hi": hi, "rgb": list(rgb), "label": worldmap._sst_label(lo, hi)}
                    for lo, hi, rgb in worldmap.SST_COLOURS],
            "ndvi": [{"lo": lo, "hi": hi, "rgb": list(rgb), "label": f"NDVI {lo:.3f} to {hi:.3f}"}
                     for lo, hi, rgb in NDVI_COLOURS]}


def payload(state) -> dict:
    """What the page needs to compare dates: the sources, Esri's archive, the
    index's seasons with their words, the event menu and NASA's scales."""
    a = getattr(state, "assessment", None)
    series = list(getattr(a, "index_series", None) or [])
    index = getattr(a, "index_name", None) or "RONI"
    built = worldmap._built_day(state)
    return {"sources": [dict(s) for s in SOURCES], "wayback": dict(WAYBACK),
            "names_credit": NAMES_CREDIT, "index": index,
            "seasons": season_rows(series), "presets": presets(series, built, index),
            "built": built.isoformat(),
            "strip": {"from": f"{FIRST_MONTH:%Y-%m}",
                      "months": _month_index(f"{built:%Y-%m}") + 1},
            "scales": _scales()}


# ----------------------------------------------------------------------------
# the page's parts
# ----------------------------------------------------------------------------
# The figure on the Enter button, and under the pointer while it is carried.
_FIGURE = ('<svg class="thenfigsvg" viewBox="0 0 24 24" width="20" height="20" '
           'aria-hidden="true" focusable="false"><circle cx="12" cy="4.6" r="3.1"/>'
           '<path d="M8.6 9.4h6.8l-1 7.2h-1.4l-.6 6.2h-2.8l-.6-6.2H9.6z"/></svg>')


def enter_button() -> str:
    """The toolbar's figure: pressed, it arms the map for a tap; carried, it
    is let go over the place to enter."""
    return ('<button type="button" class="toolbtn thenfig" id="then-enter" aria-pressed="false" '
            f'aria-describedby="then-enter-how">{_FIGURE} Enter</button>'
            '<span class="thenhow" id="then-enter-how">Drag the figure onto the map, or press '
            "it and tap a place, to see that place before and after El Niño.</span>"
            f'<span class="thenghost" id="then-ghost" aria-hidden="true" hidden>{_FIGURE}</span>')


def map_parts() -> str:
    """What Enter puts on the map: the hint while armed, a chip either side of
    the divider naming its date, and the ring under a carried figure."""
    return ('<p class="thenhint ui" id="then-hint" role="status" hidden>Tap a place to enter it, '
            "or press Enter for the middle of the view. Esc cancels.</p>"
            '<div class="thenchip ui" id="then-chip-a" hidden></div>'
            '<div class="thenchip ui" id="then-chip-b" hidden></div>'
            '<span class="thenring" id="then-ring" aria-hidden="true" hidden></span>')


def _events(presets) -> str:
    """The event menu: now first, each El Nino's two choices under its name,
    and the reader's own dates last."""
    out, group = [], None
    for p in presets:
        if p["group"] != group:
            if group:
                out.append("</optgroup>")
            if p["group"]:
                out.append(f'<optgroup label="{esc(p["group"])}">')
            group = p["group"]
        out.append(f'<option value="{esc(p["id"])}">{esc(p["label"])}</option>')
    if group:
        out.append("</optgroup>")
    out.append('<option value="">Dates of your own</option>')
    return "".join(out)


def _side(key: str, head: str, where: str, built: str) -> str:
    """One side's date: a step back, the date (or the archive's captures), a
    step on, and the season around it beneath."""
    return (f'<div class="thenside" role="group" aria-labelledby="then-head-{key}">'
            f'<span class="thenhead" id="then-head-{key}">{head}</span><div class="thenpick">'
            f'<button type="button" class="thenstep" id="then-back-{key}" '
            f'aria-label="Earlier, {where}">&#9664;</button>'
            f'<input type="date" class="thendate" id="then-date-{key}" min="2000-01-01" '
            f'max="{built}" aria-label="Date, {where}">'
            f'<select class="toolsel thencap" id="then-cap-{key}" aria-label="Capture, {where}" '
            "hidden></select>"
            f'<button type="button" class="thenstep" id="then-next-{key}" '
            f'aria-label="Later, {where}">&#9654;</button></div>'
            f'<p class="thenwords" id="then-words-{key}"></p></div>')


def _strip(then: dict) -> str:
    """The index by season from January 2000, one unit a month and ten a
    degree: warm bars up, cool bars down, the ones short of 0.5 flat grey, the
    +/-0.5 lines dashed, and a line at each side's date; the years beneath."""
    n = then["strip"]["months"]
    rects = []
    for key, _label, shown, _words in then["seasons"]:
        x = _month_index(key)
        if not 0 <= x < n or not shown:
            continue
        kind = "warm" if shown >= 0.5 else "cool" if shown <= -0.5 else "flat"
        height = round(min(abs(shown), 3.0) * 10, 1)
        top = -height if shown > 0 else 0
        rects.append(f'<rect class="{kind}" x="{x}" y="{top:g}" width="1" height="{height:g}"/>')
    first = int(then["strip"]["from"][:4])
    years = "".join(f'<span style="left:{_month_index(f"{y}-01") / n * 100:.2f}%">{y}</span>'
                    for y in range(first, first + (n - 1) // 12 + 1, 5))
    return (f'<div class="thenstripbox"><svg class="thenstrip" id="then-strip" '
            f'viewBox="0 -30 {n} 60" preserveAspectRatio="none" role="img" '
            f'aria-label="{esc(then["index"])} by season since January 2000: warm above zero, '
            "cool below, the plus and minus 0.5 lines dashed, a line at each side’s date. "
            'Tap a month to move the nearer side there.">'
            f'<line class="thenhalf" x1="0" x2="{n}" y1="-5" y2="-5"/>'
            f'<line class="thenhalf" x1="0" x2="{n}" y1="5" y2="5"/>'
            + "".join(rects)
            + f'<line class="thenzero" x1="0" x2="{n}" y1="0" y2="0"/>'
            '<line class="thenline" id="then-line-a" x1="-1" x2="-1" y1="-30" y2="30"/>'
            '<line class="thenline" id="then-line-b" x1="-1" x2="-1" y1="-30" y2="30"/>'
            f'</svg><div class="thenyears" id="then-years" aria-hidden="true">{years}</div></div>')


def bar(then: dict) -> str:
    """The bar under the map while a place is entered, in the scrubber's
    place: the source, the event, Street View, the link, the names and Exit;
    each side's date with the season around it; the strip; the readout."""
    sources = "".join(f'<option value="{esc(s["id"])}">{esc(s["name"])}</option>'
                      for s in then["sources"])
    return ('<section class="thenbar" id="then-bar" aria-label="Then and now" hidden>'
            '<div class="thenrow">'
            f'<label class="thenfield">Source <select class="toolsel" id="then-source">{sources}'
            "</select></label>"
            '<label class="thenfield">Event <select class="toolsel" id="then-event">'
            f'{_events(then["presets"])}</select></label>'
            '<button type="button" class="toolbtn" id="then-street">Street View</button>'
            '<button type="button" class="toolbtn" id="then-copy">Copy link</button>'
            '<label class="check"><input type="checkbox" id="then-names" checked> Roads and names'
            "</label>"
            '<button type="button" class="toolbtn" id="then-exit">Exit</button></div>'
            '<div class="thensides">'
            + _side("a", "Left: the earlier date", "left side", then["built"])
            + _side("b", "Right: the later date", "right side", then["built"])
            + "</div>" + _strip(then)
            + '<p class="thenread" id="then-read" role="status"></p>'
            '<p class="thennote" id="then-note"></p>'
            '<p class="thenlinks"><a id="then-gmaps" href="https://www.google.com/maps" '
            'target="_blank" rel="noopener">Street View in Google Maps, where “See more '
            "dates” holds its older panoramas ↗</a></p>"
            "</section>")


def legend() -> str:
    """The key while a place is entered on the ocean or the vegetation index:
    NASA's own scale, the one the readout reads each side's pixel back in.
    The page shows the one for the source shown, and neither for imagery."""
    sst = "".join(f'<i style="background:rgb({r},{g},{b})"></i>' for _, _, (r, g, b) in worldmap.SST_COLOURS)
    ndvi = "".join(f'<i style="background:rgb({r},{g},{b})"></i>' for _, _, (r, g, b) in NDVI_COLOURS)
    return ('<div class="keygroup ensokey" id="then-sst-key" hidden>'
            '<span class="keyhead">Then and now: sea surface temperature anomaly, GHRSST MUR25</span>'
            f'<span class="ensoramp sstramp">{sst}</span>'
            f"<span>{worldmap._sst_label(None, -3.0)} to {worldmap._sst_label(3.0, None)}, in 0.1 °C steps: "
            "NASA's own scale, against MUR's own climatology; land, ice and gaps are left clear</span></div>"
            '<div class="keygroup ensokey" id="then-ndvi-key" hidden>'
            '<span class="keyhead">Then and now: vegetation index, MODIS Terra NDVI, 16-day</span>'
            f'<span class="ensoramp ndviramp">{ndvi}</span>'
            f"<span>NDVI 0.000, bare ground, to 1.000, dense canopy, in NASA's own {len(NDVI_COLOURS)} steps; "
            "water, cloud and gaps are left clear</span></div>")


def css() -> str:
    """The bar's, the chips' and the figure's rules, over the page's tokens."""
    return """
.thenfig { display: inline-flex; align-items: center; gap: 4px; touch-action: none; }
.thenfigsvg { fill: currentColor; }
.thenhow { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%);
  white-space: nowrap; }
.thenghost { position: fixed; left: 0; top: 0; z-index: 60; margin: -34px 0 0 -10px;
  color: var(--ink); pointer-events: none; }
#map.arming { cursor: crosshair; }
/* While the map waits for a tap, the hint takes the pill's place in its corner. */
.thenhint { position: absolute; left: 10px; top: 10px; z-index: 10;
  margin: 0; max-width: min(480px, calc(100% - 76px)); padding: 8px 12px; border-radius: 10px;
  background: var(--ink); color: var(--surface); font-size: 0.8rem; }
#map.arming #frame { visibility: hidden; }
.thenring { position: absolute; left: 0; top: 0; z-index: 8; width: 30px; height: 30px;
  margin: -15px 0 0 -15px; border-radius: 50%; border: 2px solid var(--ink);
  box-shadow: 0 0 0 2px var(--surface); pointer-events: none; }
.thenchip { position: absolute; bottom: 26px; z-index: 9; max-width: calc(50% - 44px);
  padding: 4px 8px; border-radius: 8px; border: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface) 90%, transparent); color: var(--ink);
  font: 600 0.74rem var(--font); line-height: 1.3; }
.thenbar { background: var(--surface); border-top: 1px solid var(--border); padding: 6px 16px 8px;
  font-size: 0.82rem; color: var(--ink); }
.thenrow { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; }
.thenfield { display: inline-flex; align-items: center; gap: 6px; color: var(--ink2); }
.thenfield .toolsel { max-width: min(62vw, 380px); }
.thensides { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 6px 16px; margin: 6px 0 2px; }
.thenside { min-width: 0; }
.thenhead { font-size: 0.76rem; font-weight: 600; color: var(--ink2); }
.thenpick { display: flex; align-items: center; gap: 4px; }
.thenstep { width: 44px; height: 44px; border-radius: 10px; border: 1px solid var(--border);
  background: var(--surface); color: var(--ink); cursor: pointer; flex: 0 0 auto; }
.thenstep:disabled { opacity: 0.45; cursor: default; }
.thendate { min-height: 44px; padding: 0 8px; border-radius: 10px; border: 1px solid var(--border);
  background: var(--surface); color: var(--ink); font: 500 0.85rem var(--font); min-width: 0; }
.thencap { flex: 1 1 auto; min-width: 0; }
.thenwords { margin: 2px 0 0; color: var(--ink); }
.thenstripbox { position: relative; margin: 8px 0 18px; cursor: pointer; }
.thenstrip { display: block; width: 100%; height: 60px; background: var(--plane);
  border-radius: 6px; }
.thenstrip .warm { fill: var(--warm); }
.thenstrip .cool { fill: var(--cool); }
.thenstrip .flat { fill: var(--ink2); opacity: 0.45; }
.thenstrip line { vector-effect: non-scaling-stroke; }
.thenhalf { stroke: var(--ink2); stroke-width: 1px; stroke-dasharray: 3 3; opacity: 0.7; }
.thenzero { stroke: var(--ink2); stroke-width: 1px; }
.thenline { stroke: var(--ink); stroke-width: 2px; }
.thenyears { position: absolute; left: 0; right: 0; top: 62px; height: 14px;
  font-size: 0.66rem; color: var(--ink2); }
.thenyears span { position: absolute; transform: translateX(-50%); }
.thenread, .thennote { margin: 4px 0; color: var(--ink2); }
.thenread:empty, .thennote:empty { display: none; }
.thenlinks { margin: 4px 0 0; }
.thenlinks a { color: var(--s1); min-height: 44px; display: inline-flex; align-items: center; }
.ndviramp i { width: 2px; }
@media (min-width: 900px) {
  #map.thenon { min-height: 45vh; }
  #map.thenon ~ .desklegend { flex-shrink: 0; }
  .thenbar { flex: 0 1 auto; min-height: 0; overflow-y: auto; }
}
"""


# Taken into the desk's script at its /*THENNOW*/ marker, after the map's.
_JS = r"""
  // ---- then and now: a place before and after El Nino (thennow.py) ---------
  // Enter drops into a point of the map, as Google Maps' figure does, and
  // shows the same ground at two dates either side of the divider, the
  // earlier on the left, each named with the season of the index around it.
  // Each side is a layer of the page's own kinds, LAYERS["then-a"] and
  // LAYERS["then-b"], so the compare view draws them; the engine asks
  // S.then wherever it must not draw today's storms, tiles and composite
  // over another day.
  S.then = null;
  function thenSrc(id) {
    var list = (D.then && D.then.sources) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  // ---- each archive's times, and the season around a date --------------------
  // GIBS lists a layer's times as spans of start, end and period, kept here
  // as [start, end, step in days], oldest first: a single time is a span of
  // one day, and a period that is not whole days belongs to no layer here.
  var DAY = 24 * HOUR;
  function dayNo(key) { return Math.round(stamp(key) / DAY); }
  function keyOf(n) { return dayZ(n * DAY); }
  // A date as written, that is a day of the calendar: not "", not 2015-02-30.
  function realDay(text) {
    if (!/^\d{4}-\d\d-\d\d$/.test(text || "")) return false;
    var t = stamp(text);
    return !isNaN(t) && dayZ(t) === text;
  }
  function parseSpans(text) {
    var m = /<Domain>([^<]*)<\/Domain>/.exec(text || ""), out = [];
    if (!m) return out;
    m[1].split(",").forEach(function (part) {
      var bits = part.trim().split("/"), a = (bits[0] || "").slice(0, 10);
      var b = (bits.length === 3 ? bits[1] : bits[0] || "").slice(0, 10);
      var step = bits.length === 3 ? /^P([1-9]\d*)D$/.exec(bits[2]) : null;
      if ((bits.length !== 1 && !step) || !realDay(a) || !realDay(b) || b < a) return;
      out.push([a, b, step ? +step[1] : 1]);
    });
    return out.sort(function (p, q) { return p[0] < q[0] ? -1 : p[0] > q[0] ? 1 : 0; });
  }
  // The time listed nearest a date, the earlier on a tie; null with none.
  function snapTime(spans, key) {
    var t = dayNo(key), best = null, gap = Infinity;
    function consider(n) {
      var d = Math.abs(n - t);
      if (d < gap || (d === gap && n < best)) { gap = d; best = n; }
    }
    spans.forEach(function (s) {
      var a = dayNo(s[0]), b = dayNo(s[1]), step = s[2];
      if (t <= a) consider(a);
      else if (t >= b) consider(b);
      else {
        var lo = a + Math.floor((t - a) / step) * step;
        consider(lo);
        if (lo + step <= b) consider(lo + step);
      }
    });
    return best === null ? null : keyOf(best);
  }
  // The time listed before (by -1) or after (by +1) a date, null past the
  // ends. Each 16-day span starts on its own 1 January, so a step across the
  // turn of a year lands on the next span's first composite.
  function stepTime(spans, key, by) {
    var t = dayNo(key), best = null;
    spans.forEach(function (s) {
      var a = dayNo(s[0]), b = dayNo(s[1]), step = s[2], n = null;
      if (by > 0) {
        if (t < a) n = a;
        else if (t < b) { n = a + (Math.floor((t - a) / step) + 1) * step; if (n > b) n = null; }
      } else if (t > b) n = a + Math.floor((b - a) / step) * step;
      else if (t > a) n = a + (Math.ceil((t - a) / step) - 1) * step;
      if (n !== null && (best === null || (by > 0 ? n < best : n > best))) best = n;
    });
    return best === null ? null : keyOf(best);
  }
  // Months from the strip's first to a date's, and a date's month in words.
  function monthIndex(key) {
    var from = D.then.strip.from;
    return (+key.slice(0, 4) - +from.slice(0, 4)) * 12 + (+key.slice(5, 7) - +from.slice(5, 7));
  }
  function monthText(key) { return MONTHS[+key.slice(5, 7) - 1] + " " + key.slice(0, 4); }
  // The season of the index centred on a date's month, as the tracker's
  // record has it: [centre month, label, value as CPC prints it, words].
  var SEASONS = {}, SEASONS_OF = null;
  function seasonAt(key) {
    if (SEASONS_OF !== D.then) {
      SEASONS = {}; SEASONS_OF = D.then;
      D.then.seasons.forEach(function (row) { SEASONS[row[0]] = row; });
    }
    return SEASONS[key.slice(0, 7)] || null;
  }
  // What ENSO was doing around a date: the season centred on its month; after
  // the record, the latest season; before it, that there is none.
  function ensoWords(key) {
    var row = seasonAt(key), list = D.then.seasons, last = list[list.length - 1], index = D.then.index;
    if (row) return row[1] + ", centred on " + monthText(row[0]) + ": " + index + " " + signedText(row[2], 1) + ", " + row[3];
    if (last && key.slice(0, 7) > last[0]) {
      return "after the latest season on record, " + last[1] + " (" + index + " " + signedText(last[2], 1) + ", " + last[3] + ")";
    }
    return "no " + index + " season on record for " + monthText(key);
  }
  // The same, short, for a chip on the map; after the record, the latest.
  function ensoShort(key) {
    var row = seasonAt(key), list = D.then.seasons, last = list[list.length - 1];
    if (row) return D.then.index + " " + signedText(row[2], 1) + ", " + row[1];
    if (last && key.slice(0, 7) > last[0]) return "latest " + D.then.index + " " + signedText(last[2], 1) + ", " + last[1];
    return "";
  }
  function presetOf(id) {
    var list = D.then.presets;
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  // ---- Esri's archive: the versions of one place ------------------------------
  // Found as Esri's own Wayback app finds them: the tilemap of the newest
  // release names the release the tile at the pin last changed in; asked
  // again just older than that, it names the one before; and so on until the
  // tilemap has no tile there. Each version's metadata names the day its
  // imagery was taken, by whom and how sharp.
  var WAIT = 20000, WB = {all: null, asking: null, byId: {}, walks: {}, caps: {}, credits: {}};
  // An answer read as JSON (or text), or a rejection: a failure, a status
  // that is not OK, or no answer in 20 s (one metadata query took 60 s on
  // 29 Sep 2026), after which the request is given up.
  function fetchWait(url, text) {
    var ctl = typeof AbortController === "function" ? new AbortController() : null;
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { if (ctl) ctl.abort(); reject(new Error("no answer in 20 s")); }, WAIT);
      fetch(url, ctl ? {signal: ctl.signal} : undefined).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return text ? r.text() : r.json();
      }).then(function (v) { clearTimeout(timer); resolve(v); }, function (err) { clearTimeout(timer); reject(err); });
    });
  }
  // The releases, newest first, each with its id, its day, its item, its
  // metadata service and its tile template. Asked once; again after a failure.
  function wbReleases() {
    if (WB.all) return Promise.resolve(WB.all);
    if (WB.asking) return WB.asking;
    WB.asking = fetchWait(D.then.wayback.config).then(function (cfg) {
      var all = [];
      Object.keys(cfg || {}).forEach(function (id) {
        var e = cfg[id], m = /(\d{4}-\d\d-\d\d)/.exec((e && e.itemTitle) || "");
        if (!m || !e.itemURL || !e.metadataLayerUrl) return;
        all.push({id: +id, day: m[1], item: e.itemID, meta: e.metadataLayerUrl,
                  tiles: e.itemURL.replace("{level}", "{z}").replace("{row}", "{y}").replace("{col}", "{x}")});
      });
      if (!all.length) throw new Error("no releases");
      all.sort(function (p, q) { return p.day < q.day ? 1 : p.day > q.day ? -1 : 0; });
      WB.byId = {};
      all.forEach(function (r, i) { r.i = i; WB.byId[r.id] = r; });
      WB.all = all;
      return all;
    });
    WB.asking.catch(function () { WB.asking = null; });
    return WB.asking;
  }
  // The tile under the pin at the zoom it is walked at, its column in the world.
  function wbTile(lon, lat) {
    var z = D.then.wayback.level, n = Math.pow(2, z);
    var x = Math.floor(mx(wrap(lon)) * n), y = Math.floor(clamp(my(lat), 0, 1 - 1e-9) * n);
    return {z: z, x: ((x % n) + n) % n, y: y};
  }
  // The releases whose imagery changed at the tile, newest first, and why the
  // walk stopped short if it did: "failed" (a tilemap did not answer) or
  // "unknown" (it named a release the list does not hold). A whole walk is
  // kept; one cut short is walked again.
  function wbWalk(all, t) {
    var key = t.z + "/" + t.y + "/" + t.x, found = [], i = 0;
    if (WB.walks[key]) return Promise.resolve(WB.walks[key]);
    function next() {
      if (i >= all.length) return Promise.resolve("");
      var rel = all[i], url = D.then.wayback.tilemap.replace("{release}", rel.id)
        .replace("{z}", t.z).replace("{y}", t.y).replace("{x}", t.x);
      return fetchWait(url).then(function (tm) {
        if (!tm || !tm.data || tm.data[0] !== 1) return "";
        var sel = tm.select && tm.select.length ? WB.byId[tm.select[0]] : rel;
        if (!sel) return "unknown";
        if (found.indexOf(sel) < 0) found.push(sel);
        i = Math.max(sel.i, i) + 1;
        return next();
      }, function () { return "failed"; });
    }
    return next().then(function (stopped) {
      var walk = {list: found, stopped: stopped};
      if (!stopped) WB.walks[key] = walk;
      return walk;
    });
  }
  // When, by whom and how sharp a version's imagery at a point is, from its
  // metadata at the walk's zoom; null where it does not say. An answer is
  // kept; a failure is asked again next time.
  function wbCapture(v, lon, lat) {
    var key = v.id + "@" + lon.toFixed(5) + "," + lat.toFixed(5);
    if (key in WB.caps) return Promise.resolve(WB.caps[key]);
    var url = v.meta + "/" + D.then.wayback.metadata_layer + "/query?geometry=" + wrap(lon).toFixed(6) + "," +
      lat.toFixed(6) + "&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects" +
      "&outFields=*&returnGeometry=false&f=json";
    return fetchWait(url).then(function (got) {
      var a = got && got.features && got.features[0] && got.features[0].attributes;
      var m = a && /^(\d{4})(\d\d)(\d\d)$/.exec(String(a.SRC_DATE));
      var cap = m ? {day: m[1] + "-" + m[2] + "-" + m[3], provider: a.NICE_DESC || "", sensor: a.SRC_DESC || "",
                     res: typeof a.SRC_RES === "number" ? a.SRC_RES : null} : null;
      WB.caps[key] = cap;
      return cap;
    }, function () { return null; });
  }
  // The versions at a point: each release walked, with its capture; those
  // sharing a capture day are one, kept as the newest release; newest
  // capture first. A version whose capture is not given goes by its release,
  // and so does one whose capture has not answered 3 s after the walk: the
  // versions as they stand then go to early(), before the last capture.
  var CAPS_WAIT = 3000;
  function wbVersions(lon, lat, early) {
    return wbReleases().then(function (all) {
      return wbWalk(all, wbTile(lon, lat)).then(function (walk) {
        var caps = walk.list.map(function () { return null; }), timer = 0;
        function listed() {
          var list = [], days = {};
          walk.list.forEach(function (r, j) {
            var cap = caps[j];
            if (cap && days[cap.day]) return;
            if (cap) days[cap.day] = true;
            list.push({id: r.id, day: r.day, item: r.item, tiles: r.tiles, capture: cap,
                       when: cap ? cap.day : r.day, credit: WB.credits[r.item] || ""});
          });
          list.sort(function (p, q) { return p.when < q.when ? 1 : p.when > q.when ? -1 : 0; });
          return {list: list, stopped: walk.stopped};
        }
        if (early) timer = setTimeout(function () { early(listed()); }, CAPS_WAIT);
        return Promise.all(walk.list.map(function (r, j) {
          return wbCapture(r, lon, lat).then(function (cap) { caps[j] = cap; });
        })).then(function () { clearTimeout(timer); return listed(); });
      });
    }, function () { return {list: [], stopped: "config"}; });
  }
  // The version captured nearest a date, the earlier on a tie.
  function wbNearest(list, key) {
    var best = null, gap = Infinity, t = dayNo(key);
    (list || []).forEach(function (v) {
      var d = Math.abs(dayNo(v.when) - t);
      if (d < gap || (d === gap && v.when < best.when)) { gap = d; best = v; }
    });
    return best;
  }
  // A release's own credit, from its item; World Imagery's until that answers.
  function wbCredit(item) {
    if (WB.credits[item]) return Promise.resolve(WB.credits[item]);
    return fetchWait(D.then.wayback.item.replace("{id}", item)).then(function (got) {
      var words = got && typeof got.accessInformation === "string" ? got.accessInformation.trim() : "";
      if (words) WB.credits[item] = words;
      return words || D.then.wayback.credit;
    }, function () { return D.then.wayback.credit; });
  }
  // ---- the two sides, as layers of the page's own kinds -----------------------
  // A place entered: where, what shows it, the dates asked for (want) and
  // found (got) on each side, and what the map showed before (back).
  function thenFresh(o) {
    return {lon: o.lon, lat: o.lat, label: o.label, source: o.source, preset: "now",
            want: {a: null, b: null}, got: {a: null, b: null}, note: {a: "", b: ""},
            look: {a: "", b: ""}, ask: {a: 0, b: 0}, read: null, readKey: "", apart: "", order: "",
            versions: null, stopped: "", names: true, fail: {gibs: false, wayback: false},
            link: "", copy: false, back: o.back};
  }
  function thenVersion(T, id) {
    var list = (T && T.versions) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  // One side as a layer: Esri's archive as a map of one release's tiles;
  // Landsat and Sentinel-2 as the desk's two HLS layers at the side's day;
  // NASA's others as one GIBS layer at the side's time. A side with no time
  // draws nothing: never today's.
  function thenLayer(T, k) {
    var src = thenSrc(T.source), got = T.got[k], l;
    if (src.kind === "wayback") {
      // The release's credit is a sentence of its own before the names' credit.
      var v = thenVersion(T, got), words = (v && v.credit) || D.then.wayback.credit;
      l = {kind: "map", name: src.name, source: src.name, zoom: src.zoom, grey: false,
           wayback: v ? v.id : 0, tiles: v ? v.tiles : null, nodata: v ? "wb" + v.id : "wb",
           credit: "Powered by Esri. Source: " + words + (/[.!?]$/.test(words) ? "" : ".")};
    } else if (src.kind === "hls") {
      var d = LAYERS.detail || {};
      l = {kind: "imagery", name: src.name, stack: d.stack, tms: d.tms, zoom: d.zoom, format: d.format,
           step: "P1D", pixel_km: src.pixel_km, credit: src.credit, time: got || null};
    } else {
      l = {kind: "imagery", name: src.name, global: src.layer, tms: src.tms, zoom: src.tile_zoom,
           format: src.format, step: "P1D", pixel_km: src.pixel_km, credit: src.credit, time: got || null};
    }
    l.id = "then-" + k;
    l.then = true;
    // Esri's roads and names over either side while the switch is on,
    // credited with Esri's words where the side is not Esri's own.
    l.over = T.names && LAYERS.satellite ? LAYERS.satellite.over : null;
    l.overCredit = (src.kind === "wayback" ? "" : "Powered by Esri. ") + D.then.names_credit;
    return l;
  }
  // The two sides registered and compared; again after a refresh rebuilds LAYERS.
  function thenApply() {
    var T = S.then;
    if (!T) return;
    LAYERS["then-a"] = thenLayer(T, "a");
    LAYERS["then-b"] = thenLayer(T, "b");
    S.layer = "then-a"; S.second = "then-b"; S.compare = true;
  }
  // A tile of Esri's archive that did not come, past zoom 13: its release's
  // tilemap says whether it has a tile there. None is Esri's answer that it
  // has nothing finer, and the coarser tile is drawn, as for World Imagery's
  // grey tile; anything else, no answer included, fails as any map tile does.
  function wbAsk(img) {
    img._asked = true;
    var m = Math.pow(2, img._z), c = ((img._c % m) + m) % m;
    var url = D.then.wayback.tilemap.replace("{release}", img._wb).replace("{z}", img._z)
      .replace("{y}", img._r).replace("{x}", c);
    fetchWait(url).then(function (tm) { return !(tm && tm.data && tm.data[0] === 1); },
                        function () { return false; }).then(function (gone) {
      if (!gone) { tileFailed.call(img); return; }
      NODATA[img._name + "/" + img._z + "/" + c + "/" + img._r] = true;
      requestRender();
    });
  }
  // ---- each side's date found in its archive ----------------------------------
  // A layer's times from GIBS, from the archive's first day to tomorrow:
  // asked once a visit, and again after a failure.
  var SPANS = {}, SPANS_GOT = {};
  function thenSpans(src) {
    if (SPANS[src.id]) return SPANS[src.id];
    var url = D.gibs.domains.replace("{layer}", src.layer).replace("{tms}", src.tms)
      .replace("{start}", src.first).replace("{end}", dayZ(Date.now() + DAY));
    SPANS[src.id] = fetchWait(url, true).then(function (text) {
      var spans = parseSpans(text);
      if (!spans.length) throw new Error("no times");
      SPANS_GOT[src.id] = spans;
      S.imagery = "ok";
      return spans;
    });
    SPANS[src.id].catch(function () { delete SPANS[src.id]; });
    return SPANS[src.id];
  }
  // A date outside what an archive holds, said as that. A date past the
  // latest by a month or less is the latest, as "the latest" means.
  function clampNote(first, last, key) {
    if (key < first) return "asked for " + dayText(key) + ", before the first it holds, " + dayText(first);
    if (dayNo(key) - dayNo(last) > 31) return "asked for " + dayText(key) + ", after the latest it holds, " + dayText(last);
    return "";
  }
  // An event's two dates that land on the same image or capture: the left
  // side takes the one before it, where there is one, and says so. A pair
  // the reader chose is left as chosen.
  function thenApart(T, older, what) {
    T.apart = "";
    if (!T.preset || T.got.a === null || T.got.a !== T.got.b) return;
    var before = older(T.got.a);
    if (before === null) return;
    T.got.a = before;
    T.apart = "Both dates fell on the same " + what + ", so the left side shows the one before it.";
  }
  // The earlier date on the left, once neither side is still being found;
  // the sides changing places is said, until the reader's next date.
  function thenOrder(T) {
    if (T.look.a || T.look.b) return;
    var a = sideDay(T, "a"), b = sideDay(T, "b");
    if (!a || !b || a <= b) return;
    ["want", "got", "note", "look"].forEach(function (f) { var v = T[f].a; T[f].a = T[f].b; T[f].b = v; });
    T.order = "The earlier date goes on the left, so the two sides changed places.";
  }
  // The event's dates given up for the reader's own: a side the event moved
  // apart keeps the date it shows, so asking both sides again does not put
  // them back on one image.
  function thenOwnDates(T) {
    if (T.apart && !T.look.a && T.got.a !== null) T.want.a = sideDay(T, "a");
    T.preset = ""; T.apart = ""; T.order = "";
  }
  // The day shown on a side: its capture's for Esri's archive, else its
  // time; the date asked for until one is found.
  function sideDay(T, k) {
    if (thenSrc(T.source).kind === "wayback") {
      var v = thenVersion(T, T.got[k]);
      return v ? v.when : T.want[k];
    }
    return T.got[k] || T.want[k];
  }
  // NASA's daily and 16-day layers: each side at the time GIBS lists
  // nearest its date.
  function thenGibs(T, src) {
    var q = {a: ++T.ask.a, b: ++T.ask.b};
    T.look.a = T.look.b = "asking";
    thenChanged();
    thenSpans(src).then(function (spans) {
      if (T !== S.then || T.source !== src.id) return;
      T.fail.gibs = false;
      ["a", "b"].forEach(function (k) {
        if (q[k] !== T.ask[k]) return;
        T.got[k] = snapTime(spans, T.want[k]);
        T.note[k] = clampNote(spans[0][0], spans[spans.length - 1][1], T.want[k]);
        T.look[k] = "";
      });
      thenApart(T, function (key) { return stepTime(spans, key, -1); }, "image");
      thenOrder(T);
      thenChanged();
    }, function () {
      if (T !== S.then || T.source !== src.id) return;
      T.fail.gibs = true;
      ["a", "b"].forEach(function (k) { if (q[k] === T.ask[k]) T.look[k] = NO_ANSWER; });
      thenChanged();
    });
  }
  // Esri's archive: the versions of the place, and on each side the one
  // captured nearest its date. The versions already drawn stay while a
  // moved pin's are found; a capture slow to answer is found again when it does.
  function thenArchive(T) {
    var lon = T.lon, lat = T.lat, q = {a: ++T.ask.a, b: ++T.ask.b};
    if (!T.versions) T.look.a = T.look.b = "asking";
    thenChanged();
    function show(got) {
      if (T !== S.then || T.source !== "archive" || T.lon !== lon || T.lat !== lat) return;
      var list = got.list;
      T.versions = list; T.stopped = got.stopped;
      T.fail.wayback = got.stopped === "config" || (got.stopped === "failed" && !list.length);
      ["a", "b"].forEach(function (k) {
        // A capture picked while the versions were asked for stands, if it is one of them.
        if (q[k] !== T.ask[k] && thenVersion(T, T.got[k])) return;
        var v = wbNearest(list, T.want[k]);
        T.got[k] = v ? v.id : null;
        T.look[k] = T.fail.wayback ? NO_ANSWER : v ? "" : "none";
        T.note[k] = v ? clampNote(list[list.length - 1].when, list[0].when, T.want[k]) : "";
      });
      thenApart(T, function (id) {
        var i = list.indexOf(thenVersion(T, id));
        return i >= 0 && i + 1 < list.length ? list[i + 1].id : null;
      }, "capture");
      thenOrder(T);
      thenCredits(T);
      thenChanged();
    }
    wbVersions(lon, lat, show).then(show);
  }
  // Each version shown credited in its release's own words.
  function thenCredits(T) {
    ["a", "b"].forEach(function (k) {
      var v = thenVersion(T, T.got[k]);
      if (!v || v.credit) return;
      wbCredit(v.item).then(function (words) {
        v.credit = words;
        if (T === S.then) thenChanged();
      });
    });
  }
  // Landsat and Sentinel-2: the pin's tile at the detail layer's zoom, and
  // on each side the nearest day with an image there, looked for as the
  // detail layer looks: the tile the map draws, read at the pin.
  function hlsTile(lon, lat) {
    var z = LAYERS.detail.zoom, n = Math.pow(2, z);
    var x = mx(wrap(lon)) * n, y = clamp(my(lat), 0, 1 - 1e-9) * n;
    return {z: z, c: ((Math.floor(x) % n) + n) % n, r: Math.floor(y), fx: x - Math.floor(x), fy: y - Math.floor(y)};
  }
  // The days to look at: from a date, the day itself, then a day either side
  // at a time to 20 days (by 0); or the 60 days one way (by -1 or +1).
  function hlsDays(from, by, first, last) {
    var out = [], i;
    if (!by) {
      out.push(from);
      for (i = 1; i <= 20; i++) out.push(shiftDay(from, -i), shiftDay(from, i));
    } else for (i = 1; i <= 60; i++) out.push(shiftDay(from, by * i));
    return out.filter(function (d) { return d >= first && d <= last; });
  }
  // The first day of the list with an image at the pin, six days asked at a
  // time; NO_ANSWER where a whole six went unanswered; null for none.
  function hlsHunt(days, t, still) {
    var batch = days.slice(0, 6);
    if (!batch.length || !still()) return Promise.resolve(null);
    return Promise.all(batch.map(function (day) { return imageOn(day, t); })).then(function (all) {
      for (var i = 0; i < all.length; i++) if (all[i] === true) return batch[i];
      if (all.every(function (a) { return a === null; })) return NO_ANSWER;
      return hlsHunt(days.slice(6), t, still);
    });
  }
  function thenHls(T, k, by) {
    var src = thenSrc("hls"), q = ++T.ask[k], lon = T.lon, lat = T.lat, today = dayZ(Date.now());
    var from = by ? T.got[k] : T.want[k];
    if (!from) return;
    if (!by) {
      T.note[k] = clampNote(src.first, today, from);
      from = from < src.first ? src.first : from > today ? today : from;
    }
    function still() { return T === S.then && T.source === "hls" && T.ask[k] === q && T.lon === lon && T.lat === lat; }
    T.look[k] = "looking";
    thenChanged();
    hlsHunt(hlsDays(from, by, src.first, today), hlsTile(lon, lat), still).then(function (day) {
      if (!still()) return;
      T.look[k] = "";
      if (day === NO_ANSWER) { T.look[k] = NO_ANSWER; T.fail.gibs = true; }
      else if (day) {
        T.got[k] = day; T.fail.gibs = false; S.imagery = "ok";
        if (by) { T.want[k] = day; T.note[k] = ""; }
      } else if (by) T.note[k] = "no " + (by < 0 ? "earlier" : "later") + " day with an image here within 60 days";
      else { T.got[k] = null; T.look[k] = "none"; }
      thenOrder(T);
      thenChanged();
    });
  }
  // Each side found again in the source's archive.
  function thenResolve() {
    var T = S.then;
    if (!T) return;
    var src = thenSrc(T.source);
    if (S.imagery === "offline") {
      T.fail[src.kind === "wayback" ? "wayback" : "gibs"] = true;
      thenChanged();
      return;
    }
    if (src.kind === "wayback") thenArchive(T);
    else if (src.kind === "hls") { thenHls(T, "a", 0); thenHls(T, "b", 0); }
    else thenGibs(T, src);
  }
  function thenChanged() {
    thenApply(); thenRead(); dirty();
    // A link asked for while the sides were being found is made now they are.
    if (S.then && S.then.copy && !thenFinding(S.then)) thenCopy();
  }
  // Whether a side is still being found.
  function thenFinding(T) {
    return ["a", "b"].some(function (k) { return T.look[k] === "asking" || T.look[k] === "looking"; });
  }
  // ---- the bar: each side's date and the season around it ---------------------
  // What a side is waiting on, or why it has nothing, in words.
  function lookWords(T, k) {
    var kind = thenSrc(T.source).kind, look = T.look[k];
    if (kind === "wayback") {
      return look === "asking" ? "asking Esri’s archive for the versions here"
           : look === NO_ANSWER ? "Esri’s archive did not answer" : "Esri’s archive has no imagery here";
    }
    if (look === "asking") return "asking NASA GIBS for its days";
    if (look === "looking") return "looking for a day with an image here";
    if (look === NO_ANSWER) return "NASA GIBS did not answer";
    return "no image here within 20 days of " + dayText(T.want[k]);
  }
  // The chip on the map: the side's date, and the season around it.
  function chipText(T, k) {
    var day = sideDay(T, k);
    if (!day) return "";
    var extra = T.look[k] ? lookWords(T, k) : ensoShort(day);
    return dayText(day) + (extra ? " · " + extra : "");
  }
  // Under a side's date in the bar: the season in full.
  function sideWords(T, k) {
    var day = sideDay(T, k), words = T.look[k] ? lookWords(T, k) : day ? ensoWords(day) : "";
    return words ? words.charAt(0).toUpperCase() + words.slice(1) + "." : "";
  }
  // Written only when changed, so a control being used is not disturbed.
  function setText(el, text) { if (el.textContent !== text) el.textContent = text; }
  function setHidden(el, on) { if (el.hidden !== on) el.hidden = on; }
  function setValue(el, v) { if (el.value !== v) el.value = v; }
  // Whether a side can step back (by -1) or on (by +1) from its date.
  function thenCan(T, k, by) {
    var src = thenSrc(T.source), got = T.got[k];
    if (got === null || T.look[k]) return false;
    if (src.kind === "wayback") {
      var list = T.versions || [], i = list.indexOf(thenVersion(T, got));
      return i >= 0 && (by < 0 ? i < list.length - 1 : i > 0);
    }
    if (src.kind === "hls") return by < 0 ? got > src.first : got < dayZ(Date.now());
    var spans = SPANS_GOT[src.id];
    return !!spans && stepTime(spans, got, by) !== null;
  }
  // A version as its menu names it, and in full.
  function resText(m) { return m < 1 ? Math.round(m * 100) + " cm" : Math.round(m * 10) / 10 + " m"; }
  function captureShort(v) { return dayText(v.when) + (v.capture ? "" : " (release)"); }
  function captureText(v) {
    var c = v.capture;
    if (!c) return "capture date not given, first shown in the " + dayText(v.day) + " release";
    var by = [c.provider, c.sensor].filter(Boolean).join(", ");
    return "taken " + dayText(c.day) + (by ? " by " + by : "") + (c.res !== null ? " at " + resText(c.res) : "") +
      ", first shown in the " + dayText(v.day) + " release";
  }
  function thenCaptures(T, cap, k) {
    var list = T.versions || [], key = list.map(function (v) { return v.id + ":" + v.when; }).join(",");
    if (cap._key !== key) {
      cap._key = key;
      cap.innerHTML = list.map(function (v) {
        return '<option value="' + v.id + '">' + esc(captureShort(v)) + "</option>";
      }).join("");
    }
    setValue(cap, T.got[k] === null ? "" : String(T.got[k]));
  }
  // What was read at the pin on the two sides: the archive's captures, the
  // days found, or the value of NASA's scale under the pin and the change.
  function thenReadText(T) {
    var src = thenSrc(T.source), names = {a: "Left", b: "Right"}, out = [];
    if (src.kind === "wayback") {
      ["a", "b"].forEach(function (k) {
        var v = thenVersion(T, T.got[k]);
        if (v) out.push(names[k] + ": " + captureText(v) + ".");
      });
      return out.join(" ");
    }
    if (src.kind === "hls") {
      ["a", "b"].forEach(function (k) {
        var got = T.got[k], want = T.want[k];
        if (!got || T.look[k]) return;
        out.push(names[k] + ": " + (got === want ? "an image here on " + dayText(got)
          : "the nearest day with an image here to " + dayText(want) + " is " + dayText(got)) + ".");
      });
      return out.join(" ");
    }
    var r = T.read;
    if (!r) return "";
    var digits = src.id === "sst" ? 1 : 3, unit = src.id === "sst" ? " °C" : "";
    var text = "At the pin, left: " + (r.a.label || r.a.none) + "; right: " + (r.b.label || r.b.none);
    if (r.a.label && r.b.label) {
      text += r.a.open || r.b.open ? "; the change runs past the end of NASA’s scale"
        : "; a change of about " + signedText(r.b.mid - r.a.mid, digits) + unit;
    }
    return text + ".";
  }
  // The rest the reader should know: dates outside an archive, a side moved
  // apart, how much Esri's archive answered, the link, and what is not drawn.
  var HIDDEN = "While a place is entered, today’s storms, outlook areas, NASA’s reference overlays, " +
    "the ocean and flood tiles and the El Niño composite are not drawn: they belong to today, not to either date.";
  function thenNotes(T) {
    var src = thenSrc(T.source), names = {a: "Left", b: "Right"}, out = [];
    ["a", "b"].forEach(function (k) { if (T.note[k]) out.push(names[k] + ": " + T.note[k] + "."); });
    if (T.order) out.push(T.order);
    if (T.apart) out.push(T.apart);
    if (src.kind === "wayback" && T.versions) {
      if (T.versions.length === 1) out.push("Esri’s archive holds one version of this place, so both sides show it.");
      if (T.stopped === "failed") out.push("Esri’s archive stopped answering partway, so older versions may be missing.");
      if (T.stopped === "unknown") out.push("Esri’s archive named a release its list does not hold, so older versions may be missing.");
      if (T.versions.some(function (v) { return !v.capture; })) {
        out.push("A version whose capture date Esri’s metadata did not give is named by the release that first showed it.");
      }
    }
    if (T.link) out.push(T.link);
    out.push(HIDDEN);
    return out.join(" ");
  }
  // One pixel of a NASA tile at a point: its RGBA; null where the tile
  // cannot be read; false where it did not come.
  function thenPixel(src, day, lon, lat) {
    var z = src.tile_zoom, n = Math.pow(2, z), x = mx(wrap(lon)) * n, y = clamp(my(lat), 0, 1 - 1e-9) * n;
    var c = ((Math.floor(x) % n) + n) % n, r = Math.floor(y);
    var px = Math.floor((x - Math.floor(x)) * 256), py = Math.floor((y - Math.floor(y)) * 256);
    return new Promise(function (done) {
      var img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = function () {
        try {
          var cv = document.createElement("canvas");
          cv.width = cv.height = 256;
          var cx = cv.getContext("2d", {willReadFrequently: true});
          cx.drawImage(img, 0, 0, 256, 256);
          done(cx.getImageData(px, py, 1, 1).data);
        } catch (err) { done(null); }
      };
      img.onerror = function () { done(false); };
      img.src = tileUrl({name: src.layer, tms: src.tms, ext: src.format}, day, z, r, c);
    });
  }
  function binMid(e) { return e.lo === null ? e.hi : e.hi === null ? e.lo : (e.lo + e.hi) / 2; }
  function readOne(src, day, lon, lat) {
    return thenPixel(src, day, lon, lat).then(function (px) {
      if (px === false) return {none: "its tile did not arrive"};
      if (!px) return {none: "its tile could not be read"};
      var e = classify(D.then.scales[src.id], px);
      if (!e) return {none: "a colour off NASA’s scale"};
      if (e.transparent) return {none: src.id === "sst" ? "no data (land, ice or a gap)" : "no data (water, cloud or a gap)"};
      return {label: e.label, mid: binMid(e), open: e.lo === null || e.hi === null};
    });
  }
  // The two sides read at the pin, once for each pair of dates and place.
  function thenRead() {
    var T = S.then;
    if (!T) return;
    var src = thenSrc(T.source);
    if (!D.then.scales[src.id] || !T.got.a || !T.got.b || T.look.a || T.look.b) { T.read = null; T.readKey = ""; return; }
    var key = src.id + "|" + T.got.a + "|" + T.got.b + "|" + T.lon.toFixed(4) + "|" + T.lat.toFixed(4);
    if (key === T.readKey) return;
    T.readKey = key; T.read = null;
    Promise.all([readOne(src, T.got.a, T.lon, T.lat), readOne(src, T.got.b, T.lon, T.lat)]).then(function (two) {
      if (S.then !== T || T.readKey !== key) return;
      T.read = {a: two[0], b: two[1]};
      dirty();
    });
  }
  // The bar and the chips, drawn with the map.
  function thenRender() {
    var T = S.then, src = thenSrc(T.source), archive = src.kind === "wayback", cut = S.split * S.w;
    // The chips stand clear of the credit, however many lines it wraps to.
    var creditBox = $("credit"), lift = Math.round(((creditBox && creditBox.offsetHeight) || 17) + 9) + "px";
    // The picker reaches today, however many days ago the page was built.
    var today = dayZ(Date.now());
    setValue($("then-source"), T.source);
    setValue($("then-event"), T.preset);
    if ($("then-names").checked !== T.names) $("then-names").checked = T.names;
    ["a", "b"].forEach(function (k) {
      var date = $("then-date-" + k), cap = $("then-cap-" + k), day = sideDay(T, k);
      if (date.getAttribute("max") !== today) date.setAttribute("max", today);
      setHidden(date, archive);
      setHidden(cap, !archive);
      if (!archive && document.activeElement !== date) setValue(date, day || "");
      if (archive) thenCaptures(T, cap, k);
      $("then-back-" + k).disabled = !thenCan(T, k, -1);
      $("then-next-" + k).disabled = !thenCan(T, k, 1);
      setText($("then-words-" + k), sideWords(T, k));
      var chip = $("then-chip-" + k), text = chipText(T, k);
      setText(chip, text);
      setHidden(chip, !text);
      if (k === "a") chip.style.right = Math.round(S.w - cut + 26) + "px";
      else chip.style.left = Math.round(cut + 26) + "px";
      chip.style.bottom = lift;
      var line = $("then-line-" + k), x = String(day ? monthIndex(day) + 0.5 : -1);
      if (line.getAttribute("x1") !== x) { line.setAttribute("x1", x); line.setAttribute("x2", x); }
    });
    setText($("then-read"), thenReadText(T));
    setText($("then-note"), thenNotes(T));
    var href = googleLinks(T.lat, T.lon, S.z).street;
    if ($("then-gmaps").getAttribute("href") !== href) $("then-gmaps").setAttribute("href", href);
    thenKey(T.source);
  }
  // ---- the bar's controls --------------------------------------------------------
  // A side a step back or on: the day before or after with an image here;
  // the older or newer version; the time GIBS lists before or after.
  function thenStep(k, by) {
    var T = S.then;
    if (!T || !thenCan(T, k, by)) return;
    var src = thenSrc(T.source);
    thenOwnDates(T);
    if (src.kind === "hls") { thenHls(T, k, by); return; }
    T.ask[k]++;
    if (src.kind === "wayback") {
      var list = T.versions, v = list[list.indexOf(thenVersion(T, T.got[k])) - by];
      T.got[k] = v.id; T.want[k] = v.when;
    } else T.got[k] = T.want[k] = stepTime(SPANS_GOT[src.id], T.got[k], by);
    T.note[k] = "";
    thenOrder(T);
    if (src.kind === "wayback") thenCredits(T);
    thenChanged();
  }
  // A date typed or picked for a side: a day of the calendar from 2000 to
  // today. One before 2000 or still to come is said and not taken; one that
  // is not a day, or a year still being typed (0201 on the way to 2015), is
  // let be. Either way the field shows the side's date again.
  function thenSetWant(k, text) {
    var T = S.then;
    if (!T || !realDay(text) || text === T.want[k]) return;
    if (text < "2000-01-01" || text > dayZ(Date.now())) {
      if (text < "1900") return;
      T.note[k] = "asked for " + dayText(text) + (text < "2000-01-01"
        ? ", before the first day the page offers, " + dayText("2000-01-01") : ", a day still to come");
      dirty();
      return;
    }
    thenOwnDates(T);
    T.want[k] = text;
    if (thenSrc(T.source).kind === "hls") thenHls(T, k, 0); else thenResolve();
  }
  function thenCapture(k, id) {
    var T = S.then, v = T && thenVersion(T, +id);
    if (!v) return;
    thenOwnDates(T);
    T.ask[k]++;
    T.got[k] = v.id; T.want[k] = v.when; T.note[k] = "";
    thenOrder(T);
    thenCredits(T);
    thenChanged();
  }
  // An event's two dates; "" keeps the dates as they are, as the reader's own.
  function thenPreset(id) {
    var T = S.then, p = presetOf(id);
    if (!T) return;
    if (!p) { thenOwnDates(T); thenChanged(); return; }
    T.preset = id; T.apart = ""; T.order = "";
    T.want = {a: p.left, b: p.right};
    thenResolve();
  }
  // Another archive for the same place and dates, flown to its own zoom.
  function thenSource(id) {
    var T = S.then, src = thenSrc(id);
    if (!T || !src || id === T.source) return;
    T.source = id;
    T.got = {a: null, b: null}; T.note = {a: "", b: ""}; T.look = {a: "", b: ""};
    T.read = null; T.readKey = ""; T.apart = ""; T.order = ""; T.fail = {gibs: false, wayback: false};
    T.ask.a++; T.ask.b++;
    thenApply();
    var z = clamp(src.enter, MINZ, src.zoom);
    animate({x: mx(T.lon) + near(mx(T.lon)), y: my(T.lat), z: z}, flightMs(z));
    thenResolve();
  }
  // A tap on the strip moves the nearer side to the 15th of that month.
  function thenStripAt(frac) {
    var T = S.then;
    if (!T) return;
    var n = D.then.strip.months, i = clamp(Math.floor(frac * n), 0, n - 1), from = D.then.strip.from;
    var m0 = +from.slice(5, 7) - 1 + i, key = (+from.slice(0, 4) + Math.floor(m0 / 12)) + "-" + pad2(m0 % 12 + 1) + "-15";
    var today = dayZ(Date.now());
    if (key > today) key = today;
    var a = sideDay(T, "a"), b = sideDay(T, "b");
    var k = !a ? "a" : !b ? "b" : Math.abs(dayNo(key) - dayNo(a)) <= Math.abs(dayNo(key) - dayNo(b)) ? "a" : "b";
    thenSetWant(k, key);
  }
  // A flight's length: longer the more zoom it crosses.
  function flightMs(z) { return clamp(600 + 200 * Math.abs(z - S.z), 600, 2000); }
  // A refresh brings a new build's event menu (its "now" names the new
  // build's months) and strip (its new seasons); the controls themselves,
  // and what listens to them, stay.
  function thenRefreshed(doc) {
    var events = doc.getElementById("then-event"), strip = doc.getElementById("then-strip");
    var years = doc.getElementById("then-years");
    if (events) $("then-event").innerHTML = events.innerHTML;
    if (strip) {
      $("then-strip").innerHTML = strip.innerHTML;
      $("then-strip").setAttribute("viewBox", strip.getAttribute("viewBox"));
    }
    if (years) $("then-years").innerHTML = years.innerHTML;
  }
  $("then-source").addEventListener("change", function (e) { thenSource(e.target.value); });
  $("then-event").addEventListener("change", function (e) { thenPreset(e.target.value); });
  $("then-names").addEventListener("change", function (e) {
    if (!S.then) return;
    S.then.names = e.target.checked;
    thenChanged();
  });
  ["a", "b"].forEach(function (k) {
    $("then-back-" + k).addEventListener("click", function () { thenStep(k, -1); });
    $("then-next-" + k).addEventListener("click", function () { thenStep(k, 1); });
    $("then-date-" + k).addEventListener("change", function (e) { thenSetWant(k, e.target.value); });
    $("then-date-" + k).addEventListener("blur", function () { requestRender(); });
    $("then-cap-" + k).addEventListener("change", function (e) { thenCapture(k, e.target.value); });
  });
  $("then-strip").addEventListener("click", function (e) {
    var r = $("then-strip").getBoundingClientRect();
    if (r.width > 0) thenStripAt((e.clientX - r.left) / r.width);
  });
  // ---- entering a place, and leaving it ----------------------------------------
  // A point is named by the page's placeLabel, as Here names one.
  // The archive first on land and near a town; the ocean's temperature at sea.
  function thenPick(lon, lat) {
    var land = false;
    try { land = cellAt("AIR", D.enso.now, lon, lat).value !== null; } catch (err) { /* no grid: towns decide */ }
    var p = nearestPlace(lon, lat);
    return land || (p && p.km <= 30) ? "archive" : "sst";
  }
  function thenShow(on) {
    setHidden($("then-bar"), !on);
    // Marked, the map keeps its height over the bar on a page that fits the window.
    map.classList.toggle("thenon", !!on);
    var scrubRow = document.querySelector(".deskscrub");
    if (scrubRow) setHidden(scrubRow, on);
    if (!on) { setHidden($("then-chip-a"), true); setHidden($("then-chip-b"), true); thenKey(""); }
    else document.querySelectorAll("[data-layer]").forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
  }
  // A longitude brought into -180 to 180, and left as it is when it is
  // already there, so the place entered is the place asked for.
  function lonIn(lon) { return lon >= -180 && lon < 180 ? lon : wrap(lon); }
  // The divider set by entering or leaving, and said where it is.
  function thenSplit(v) {
    S.split = v;
    divider.setAttribute("aria-valuenow", String(Math.round(v * 100)));
  }
  // Into a place: the pin, the two sides compared at the divider, and a
  // flight to the source's zoom. Entered already, the place moves and the
  // source, the dates and what Exit goes back to are kept.
  function thenEnter(lon, lat, label, opts) {
    opts = opts || {};
    lon = lonIn(lon); lat = clamp(lat, -85, 85);
    var old = S.then, src = thenSrc(opts.source) || (old && thenSrc(old.source)) || thenSrc(thenPick(lon, lat));
    var back = old ? old.back : {layer: S.layer, second: S.second, compare: S.compare, split: S.split, loop: S.loop};
    if (S.loop) setLoop(false);
    // However it is entered (a tap, Here, a link, the page's API), the map
    // stops waiting for a tap.
    if (S.arming) arm(false);
    var T = thenFresh({lon: lon, lat: lat, label: label || placeLabel(lon, lat), source: src.id, back: back});
    if (realDay(opts.a) && realDay(opts.b)) { T.preset = ""; T.want = {a: opts.a, b: opts.b}; }
    else if (old) { T.preset = old.preset; T.want = {a: old.want.a, b: old.want.b}; T.names = old.names; }
    else { var p = presetOf("now"); T.want = {a: p.left, b: p.right}; }
    if (!old) thenSplit(0.5);
    S.then = T;
    thenApply();
    pin(lon, lat, T.label);
    thenShow(true);
    var z = clamp(opts.z || src.enter, MINZ, src.zoom), to = {x: mx(lon) + near(mx(lon)), y: my(lat), z: z};
    if (opts.instant) { cancelAnimationFrame(anim); anim = 0; S.x = to.x; S.y = to.y; S.z = to.z; settle(); }
    else animate(to, flightMs(z));
    thenResolve();
    return true;
  }
  // Out again, to the layers, comparison, divider and loop there were before.
  function thenLeave() {
    var T = S.then;
    if (!T) return false;
    S.then = null;
    delete LAYERS["then-a"]; delete LAYERS["then-b"];
    var b = T.back;
    S.second = b.second; S.compare = b.compare; thenSplit(b.split);
    setLayer(b.layer);
    setCompare(b.compare);
    if (b.loop) {
      // The loop runs over the frames in view, which are the sides' until the
      // map is drawn again: the layer put back is looked at first.
      S.inView = cells(S.layer, S.frame).used;
      setLoop(true);
    }
    if (S.here) pin(S.here.lon, S.here.lat, S.here.label); else S.pin = null;
    if (/^#then=/.test(location.hash)) {
      try { history.replaceState(null, "", location.href.split("#")[0]); } catch (err) { /* the address keeps it */ }
    }
    thenShow(false);
    dirty();
    return true;
  }
  // A tap while entered: the same dates at another place.
  function thenMove(lon, lat) {
    var T = S.then;
    if (!T) return;
    T.lon = lonIn(lon); T.lat = clamp(lat, -85, 85); T.label = placeLabel(T.lon, T.lat);
    T.read = null; T.readKey = ""; T.apart = ""; T.order = "";
    pin(T.lon, T.lat, T.label);
    thenResolve();
  }
  // For the page's API: where and what is entered.
  function thenView() {
    var T = S.then;
    return T ? {lon: T.lon, lat: T.lat, label: T.label, source: T.source, preset: T.preset,
                left: sideDay(T, "a"), right: sideDay(T, "b"), look: {a: T.look.a, b: T.look.b}} : null;
  }
  $("then-exit").addEventListener("click", function () { thenLeave(); });
  // ---- the figure: pressed, then a tap; or carried onto the map ---------------------
  // Pressed, the map waits for a tap (or Enter, for the middle of the view);
  // carried, a ring shows where it would land, and letting go there enters.
  S.arming = false;
  var fig = $("then-enter"), ghost = $("then-ghost"), landing = $("then-ring"), carry = null, carried = false;
  function arm(on) {
    S.arming = !!on;
    map.classList.toggle("arming", S.arming);
    setHidden($("then-hint"), !S.arming);
    fig.setAttribute("aria-pressed", S.arming ? "true" : "false");
  }
  // A pointer's place on the map, or null off it or over one of the map's
  // own controls (a pill, a chip, the zoom buttons): the figure is let go
  // there as over the toolbar, and enters nowhere.
  function overMap(e) {
    var r = map.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (!(x >= 0 && y >= 0 && x < r.width && y < r.height)) return null;
    var under = document.elementFromPoint ? document.elementFromPoint(e.clientX, e.clientY) : null;
    return under && under.closest && under.closest(".ui") ? null : {x: x, y: y};
  }
  function carryEnd(e, drop) {
    if (!carry || e.pointerId !== carry.id) return;
    var moved = carry.moved;
    carry = null;
    setHidden(ghost, true);
    setHidden(landing, true);
    if (!moved) return;
    // The click that follows letting go is not a press.
    carried = true;
    var at = drop ? overMap(e) : null;
    if (!at) return;
    var w = toWorld(at.x, at.y);
    arm(false);
    thenEnter(lonOf(w.x), latOf(w.y));
  }
  fig.addEventListener("pointerdown", function (e) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    carry = {id: e.pointerId, x0: e.clientX, y0: e.clientY, moved: false};
    carried = false;
    try { fig.setPointerCapture(e.pointerId); } catch (err) { /* a synthetic pointer */ }
  });
  fig.addEventListener("pointermove", function (e) {
    if (!carry || e.pointerId !== carry.id) return;
    if (!carry.moved && Math.hypot(e.clientX - carry.x0, e.clientY - carry.y0) < 8) return;
    carry.moved = true;
    setHidden(ghost, false);
    ghost.style.transform = "translate(" + Math.round(e.clientX) + "px," + Math.round(e.clientY) + "px)";
    var at = overMap(e);
    setHidden(landing, !at);
    if (at) landing.style.transform = "translate(" + Math.round(at.x) + "px," + Math.round(at.y) + "px)";
  });
  fig.addEventListener("pointerup", function (e) { carryEnd(e, true); });
  fig.addEventListener("pointercancel", function (e) { carryEnd(e, false); });
  fig.addEventListener("click", function () {
    if (carried) { carried = false; return; }
    arm(!S.arming);
  });
  // Esc stops waiting for a tap, or leaves the place; Enter while waiting
  // enters the middle of the view. Keys typed into a field are its own.
  document.addEventListener("keydown", function (e) {
    var t = e.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (t && t.closest && t.closest("#findform"))) return;
    if (e.key === "Escape") {
      if (S.arming) { arm(false); e.preventDefault(); }
      else if (S.then) { thenLeave(); e.preventDefault(); }
    } else if (e.key === "Enter" && S.arming) {
      e.preventDefault();
      arm(false);
      thenEnter(lonOf(S.x), latOf(S.y));
    }
  });
  // ---- the pill, the status, the address ------------------------------------------
  // The pill while a place is entered: the place and the source, then one
  // line a side, and how far the view is past the source's own detail.
  function thenPill(head, more) {
    var T = S.then, src = thenSrc(T.source), names = {a: "Left", b: "Right"};
    if (S.imagery === "offline") head.push("Offline: " + src.name + " needs the network; the tiles already loaded stay.");
    else head.push(T.label + ": " + src.name + ", then and now");
    ["a", "b"].forEach(function (k) {
      var day = sideDay(T, k), v = src.kind === "wayback" ? thenVersion(T, T.got[k]) : null;
      more.push(names[k] + ": " + (day ? dayText(day) : "no date") +
                (T.look[k] ? ", " + lookWords(T, k) : day ? ", " + ensoWords(day) : "") +
                (v ? "; " + captureText(v) : "") + ".");
    });
    var l = LAYERS["then-a"];
    if (l && l.pixel_km && S.z > l.zoom + 0.2) {
      more.push("Enlarged " + Math.pow(2, S.z - l.zoom).toFixed(1) + " times past its " +
                (l.pixel_km < 1 ? Math.round(l.pixel_km * 1000) + " m" : l.pixel_km + " km") + " pixels.");
    }
    [S.inView["then-a"], S.inViewB && S.inViewB["then-b"]].forEach(function (drawn, i) {
      if (drawn && drawn.coarser !== null && drawn.coarser !== undefined) {
        more.push((i ? "Right" : "Left") + ": Esri’s archive has nothing finer than zoom " + drawn.coarser +
                  " for part of this view; that part is its zoom-" + drawn.coarser + " tile, enlarged.");
      }
    });
  }
  // The status pill's words while entered. A walk of Esri's archive cut
  // short may have missed older versions: the pill says so, with Retry.
  function thenDown() {
    var T = S.then;
    if (T.fail.wayback || mapDown("then-a") || mapDown("then-b")) return "Esri’s archive unreachable.";
    if (T.fail.gibs || nasaDown(S.inView) || (S.inViewB && nasaDown(S.inViewB))) return "Imagery unreachable.";
    if (thenSrc(T.source).kind === "wayback" && T.stopped && T.versions && T.versions.length) {
      return "Esri’s archive answered in part.";
    }
    return "";
  }
  // Retry: each side found again. A walk cut short is walked again, and one
  // that met a release the list does not hold asks for the list again.
  function thenRetry() {
    var T = S.then;
    if (T.stopped === "unknown") { WB.all = null; WB.asking = null; }
    T.fail = {gibs: false, wayback: false};
    thenResolve();
  }
  // The place, zoom, source and both dates, as an address to open again:
  // #then=lat,lon,zoom,source,left,right.
  function thenHash() {
    var T = S.then;
    return "#then=" + T.lat.toFixed(4) + "," + T.lon.toFixed(4) + "," + S.z.toFixed(2) + "," + T.source + "," +
      (sideDay(T, "a") || "") + "," + (sideDay(T, "b") || "");
  }
  function parseThen(text) {
    var m = /^#then=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(\d+(?:\.\d+)?),([a-z]+),(\d{4}-\d\d-\d\d),(\d{4}-\d\d-\d\d)$/.exec(text || "");
    if (!m) return null;
    var lat = +m[1], lon = +m[2], src = thenSrc(m[4]);
    if (!src || Math.abs(lat) > 90 || Math.abs(lon) > 360 || !realDay(m[5]) || !realDay(m[6])) return null;
    // A longitude inside the world is kept as written, as parseHash keeps it.
    lon = lonIn(lon);
    return {lat: lat, lon: lon, z: clamp(+m[3], MINZ, src.zoom), source: src.id, a: m[5], b: m[6]};
  }
  function thenHashApply(text) {
    var h = parseThen(text);
    if (!h) return false;
    return thenEnter(h.lon, h.lat, null, {source: h.source, a: h.a, b: h.b, z: h.z, instant: true});
  }
  // The link to this place and these dates: to the clipboard where the
  // browser allows it, and shown in the bar either way. Asked for while a
  // side is still being found, it is made once both are, so it holds the
  // dates the sides show, not the dates asked for: opened, those are the
  // reader's own, and an event's two sides on one capture stay on it.
  function thenCopy() {
    var T = S.then;
    if (!T) return;
    T.copy = thenFinding(T);
    if (T.copy) { T.link = "The link is copied once both sides are found."; dirty(); return; }
    var url = location.href.split("#")[0] + thenHash();
    T.link = "Copy this link: " + url;
    try {
      navigator.clipboard.writeText(url).then(function () {
        if (S.then === T) { T.link = "Link copied: " + url; dirty(); }
      }, function () { /* the link stays shown, to copy by hand */ });
    } catch (err) { /* no clipboard: the link stays shown */ }
    dirty();
  }
  // Google's Street View of the place, in the Here panel's frame.
  function thenStreet() {
    var T = S.then;
    if (!T) return;
    hereAt(T.lon, T.lat, T.label);
    var g = S.google, box = $("google-frame");
    if (!(g && g.kind === "street" && box && !box.hidden)) googleFrame("street");
    box = $("google-frame");
    if (box && box.scrollIntoView) box.scrollIntoView({block: "nearest"});
  }
  $("then-copy").addEventListener("click", function () { thenCopy(); });
  $("then-street").addEventListener("click", function () { thenStreet(); });
  // ---- the key -------------------------------------------------------------------
  // The key under the map while a place is entered: NASA's own scale for the
  // source the readout reads, the ocean's or the vegetation index's; none
  // for the imagery, which has none. Today's storms and the marks the key to
  // the map explains are not drawn over another day, and their keys stand
  // aside with them (again after a refresh writes the key anew).
  function thenKey(id) {
    ["sst", "ndvi"].forEach(function (k) { setHidden($("then-" + k + "-key"), k !== id); });
    ["storm-key", "key-more"].forEach(function (k) { if ($(k)) setHidden($(k), !!S.then); });
  }
"""
