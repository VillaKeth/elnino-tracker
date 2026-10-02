"""The storm desk: storms.json and the page drawn from it.

Everything the page needs to put every live storm on live satellite imagery
and say what to do about it: where each storm is and where it is forecast to
go, what its warning centre has issued, which places the official forecast
brings inside each wind threshold and when, which geostationary imager sees
it best and how far that imager's view of the cloud tops leans, and who is
responsible for warnings there.

Official values are passed through as the centres issued them. Anything
worked out here says so under ``methods``, and every time is ISO 8601 UTC.
Longitudes of one storm - its track, forecast, cone, warnings and the places
in its path - are written in one frame, within 180 degrees of its centre, so
a storm on the date line runs from 179.4W to 180.8W rather than to 179.2E and
nothing the page draws goes the long way round the world.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

from . import alerts, coastline, cyclones, exposure, fields, live, outlook, thennow, worldmap
from .storms import NEUTRAL, STORM_HUES
from .svg import esc, table

SCHEMA = 1

# ----------------------------------------------------------------------------
# imagery: NASA GIBS, Web Mercator. Layer names, tile matrix sets, formats and
# cadences as GIBS's capabilities listed them on 25 September 2026.
# ----------------------------------------------------------------------------
GIBS = "https://gibs.earthdata.nasa.gov/wmts/epsg3857/best"

LAYERS = (
    {"id": "geocolor", "kind": "imagery", "name": "GeoColor",
     "about": "True colour by day, multispectral infrared with city lights by night.",
     "satellites": {"GOES-East": "GOES-East_ABI_GeoColor",
                    "GOES-West": "GOES-West_ABI_GeoColor",
                    "Himawari": None},
     "tms": "GoogleMapsCompatible_Level7", "zoom": 7, "format": "png",
     "step": "PT10M", "pixel_km": 1.0},
    {"id": "visible", "kind": "imagery", "name": "Visible",
     "about": "Red visible band, 0.64 micrometres: cloud texture by day, dark at night.",
     "satellites": {"GOES-East": "GOES-East_ABI_Band2_Red_Visible_1km",
                    "GOES-West": "GOES-West_ABI_Band2_Red_Visible_1km",
                    "Himawari": "Himawari_AHI_Band3_Red_Visible_1km"},
     "tms": "GoogleMapsCompatible_Level7", "zoom": 7, "format": "png",
     "step": "PT10M", "pixel_km": 1.0},
    {"id": "infrared", "kind": "imagery", "name": "Infrared",
     "about": ("Clean longwave window, 10.3 micrometres: cloud-top temperature "
               "day and night."),
     "satellites": {"GOES-East": "GOES-East_ABI_Band13_Clean_Infrared",
                    "GOES-West": "GOES-West_ABI_Band13_Clean_Infrared",
                    "Himawari": "Himawari_AHI_Band13_Clean_Infrared"},
     "tms": "GoogleMapsCompatible_Level6", "zoom": 6, "format": "png",
     "step": "PT10M", "pixel_km": 2.0},
    {"id": "airmass", "kind": "imagery", "name": "Air mass",
     "about": "Water vapour and ozone channels: dry air and jet-stream intrusions.",
     "satellites": {"GOES-East": "GOES-East_ABI_Air_Mass",
                    "GOES-West": "GOES-West_ABI_Air_Mass",
                    "Himawari": "Himawari_AHI_Air_Mass"},
     "tms": "GoogleMapsCompatible_Level6", "zoom": 6, "format": "png",
     "step": "PT10M", "pixel_km": 2.0},
    {"id": "rain", "kind": "imagery", "name": "Rain rate",
     "about": "NASA GPM IMERG, half-hourly, several hours behind real time.",
     "global": "IMERG_Precipitation_Rate_30min",
     "tms": "GoogleMapsCompatible_Level6", "zoom": 6, "format": "png",
     "step": "PT30M", "pixel_km": 11.0, "credit": "IMERG: NASA GPM."},
    {"id": "truecolor", "kind": "imagery", "name": "True colour (daily)",
     "about": "NOAA-20 VIIRS, one daytime pass a day, with gaps between swaths.",
     "global": "VIIRS_NOAA20_CorrectedReflectance_TrueColor",
     "tms": "GoogleMapsCompatible_Level9", "zoom": 9, "format": "jpeg",
     "step": "P1D", "pixel_km": None, "credit": "VIIRS: NASA and NOAA."},
    {"id": "bluemarble", "kind": "imagery", "name": "Blue Marble",
     "about": "Cloud-free relief and sea floor, for orientation: not today's weather.",
     "global": "BlueMarble_ShadedRelief_Bathymetry",
     "tms": "GoogleMapsCompatible_Level8", "zoom": 8, "format": "jpeg",
     "step": None, "pixel_km": None, "credit": "Blue Marble: NASA Earth Observatory."},
    # Harmonized Landsat and Sentinel-2: a day's passes, swath by swath, drawn
    # one over the other for the day with an image at the centre of the view.
    {"id": "detail", "kind": "imagery", "name": "Detail (30 m)",
     "about": ("Landsat 8/9 and Sentinel-2, 30 m pixels: fields, runways, reservoirs "
               "and the outline of a town, not streets. One day's passes, clouds as seen."),
     "stack": ("HLS_L30_Nadir_BRDF_Adjusted_Reflectance",
               "HLS_S30_Nadir_BRDF_Adjusted_Reflectance"),
     "tms": "GoogleMapsCompatible_Level12", "zoom": 12, "format": "png",
     "step": "P1D", "pixel_km": 0.03,
     "credit": "HLS: NASA, from USGS Landsat and ESA Copernicus Sentinel-2."},
    {"id": "lights", "kind": "imagery", "name": "Night lights",
     "about": ("VIIRS Black Marble 2016: a year of cloud-free nights, 500 m pixels. "
               "Where people live, not today's power."),
     "global": "VIIRS_Black_Marble", "time": "2016-01-01",
     "tms": "GoogleMapsCompatible_Level8", "zoom": 8, "format": "png",
     "step": None, "pixel_km": 0.5, "credit": "Black Marble: NASA Earth Observatory."},
    {"id": "roads", "kind": "overlay", "name": "Roads and borders",
     "about": "GIBS reference features, from OpenStreetMap.",
     "global": "Reference_Features_15m",
     "tms": "GoogleMapsCompatible_Level13", "zoom": 13, "format": "png",
     "step": None, "pixel_km": None, "credit": "Reference layers: OpenStreetMap contributors."},
    {"id": "coastlines", "kind": "overlay", "name": "Coastlines",
     "about": "GIBS coastlines.",
     "global": "Coastlines_15m",
     "tms": "GoogleMapsCompatible_Level13", "zoom": 13, "format": "png",
     "step": None, "pixel_km": None, "credit": "Reference layers: OpenStreetMap contributors."},
    {"id": "builtup", "kind": "overlay", "name": "Built-up areas",
     "about": "Landsat human built-up and settlement extent (HBASE), 2010, 30 m.",
     "global": "Landsat_Human_Built-up_And_Settlement_Extent",
     "tms": "GoogleMapsCompatible_Level12", "zoom": 12, "format": "png",
     "step": None, "pixel_km": 0.03, "credit": "HBASE: NASA SEDAC."},
)

# A geostationary layer is credited with the operators of its imagers, the
# page's credit line with those in view.
GIBS_ACKNOWLEDGE = "Imagery: NASA GIBS."
SATELLITE_CREDITS = {"GOES-East": "GOES: NOAA.", "GOES-West": "GOES: NOAA.",
                     "Himawari": "Himawari: JMA."}


def _gibs_credits(layer: dict) -> list:
    """What a GIBS layer is credited with: its imagers' operators, or its own words."""
    imagers = layer.get("satellites")
    if imagers:
        return [SATELLITE_CREDITS[name] for name, gibs_name in imagers.items() if gibs_name]
    return [layer["credit"]]


GIBS_ENDPOINTS = {
    "tiles": GIBS + "/{layer}/default/{time}/{tms}/{z}/{y}/{x}.{ext}",
    "static": GIBS + "/{layer}/default/{tms}/{z}/{y}/{x}.{ext}",
    # The frame times on offer, asked for when the page opens (CORS is open).
    "domains": GIBS + "/1.0.0/{layer}/default/{tms}/all/{start}--{end}.xml",
    "latency": ("Geostationary frames every 10 minutes, typically 40 to 60 "
                "minutes behind real time."),
    # Every source the imagery comes from, once, for the About section.
    "credit": " ".join(dict.fromkeys(
        [GIBS_ACKNOWLEDGE] + [words for layer in LAYERS for words in _gibs_credits(layer)])),
    "acknowledge": GIBS_ACKNOWLEDGE,
    "satellites": dict(SATELLITE_CREDITS),
}

OPERATORS = {"GOES-East": ("NOAA", "ABI"), "GOES-West": ("NOAA", "ABI"),
             "Himawari": ("JMA", "AHI")}

# The vendored coastline the page draws when the imagery cannot be reached.
COAST_LEVEL = 1

# ----------------------------------------------------------------------------
# who warns where
# ----------------------------------------------------------------------------
CENTRES = {
    "NHC": "https://www.nhc.noaa.gov/",
    "CPHC": "https://www.nhc.noaa.gov/?cpac",
    "JTWC": "https://www.metoc.navy.mil/jtwc/jtwc.html",
}
RSMC = {
    "NHC": ("NHC (RSMC Miami)", CENTRES["NHC"]),
    "CPHC": ("CPHC (RSMC Honolulu)", CENTRES["CPHC"]),
    "JMA": ("JMA (RSMC Tokyo)",
            "https://www.jma.go.jp/jma/jma-eng/jma-center/rsmc-hp-pub-eg/RSMC_HP.htm"),
    "IMD": ("IMD (RSMC New Delhi)", "https://rsmcnewdelhi.imd.gov.in/"),
    "REUNION": ("Meteo-France (RSMC La Reunion)", "https://meteofrance.re/fr/cyclone"),
    "BOM": ("Bureau of Meteorology (Australian TCWCs)",
            "https://www.bom.gov.au/weather-and-climate/specialised-forecasts-and-"
            "observations/tropical-cyclone"),
    "NADI": ("Fiji Meteorological Service (RSMC Nadi)", "https://www.met.gov.fj/"),
    "WELLINGTON": ("MetService (TCWC Wellington)", "https://www.metservice.com/"),
}
RESPONSIBILITY = (
    "The regional specialized centre named for each storm issues the official "
    "advisories for its ocean under the World Meteorological Organization; each "
    "country's national meteorological service issues the warnings for its own "
    "coast. JTWC warns for United States forces."
)

# ----------------------------------------------------------------------------
# what to do: the United States government's guidance, quoted closely
# ----------------------------------------------------------------------------
ACTIONS = {
    "people": (
        ("If you live in an evacuation zone and local officials tell you to "
         "evacuate, do so immediately, by routes you have learned beforehand. "
         "Storm surge has historically been the leading cause of hurricane "
         "deaths in the United States.", "https://www.ready.gov/hurricanes"),
        ("For high wind, take refuge in a designated storm shelter or an "
         "interior room.", "https://www.ready.gov/hurricanes"),
        ("If flooding traps you, go to the highest level of the building, but "
         "not into a closed attic, where rising water can trap you.",
         "https://www.ready.gov/hurricanes"),
        ("Do not walk, swim or drive through flood water. Six inches of "
         "fast-moving water can knock you down, and one foot of moving water "
         "can sweep a vehicle away.", "https://www.ready.gov/hurricanes"),
        ("Keep supplies, including medication, in a go bag or car trunk: after "
         "a hurricane you may not be able to get them for days or even weeks.",
         "https://www.ready.gov/hurricanes"),
        ("Run a generator only outdoors, 20 feet from windows, doors and "
         "attached garages. Carbon monoxide has no colour or smell and kills "
         "people and pets.", "https://www.ready.gov/power-outages"),
    ),
    "animals": (
        ("If local officials ask you to evacuate, your pets evacuate too. Pets "
         "left behind may end up lost, injured or worse.",
         "https://www.ready.gov/pets"),
        ("Many public shelters and hotels do not allow pets inside. Know a safe "
         "place to take them before the storm, and arrange with neighbours, "
         "friends or relatives to evacuate them if you cannot.",
         "https://www.ready.gov/pets"),
        ("Microchip your pets and keep the contact details current. A collar "
         "with an ID tag, a leash, a carrier for each pet and a photo of you "
         "together help prove ownership if you are separated.",
         "https://www.ready.gov/pets"),
        ("Pack food, water and your pets' medicines, with copies of their "
         "records in a waterproof container.", "https://www.ready.gov/pets"),
        ("Horses, livestock and other large animals: give every animal "
         "identification, evacuate them early whenever possible, and arrange "
         "vehicles, trailers, handlers and routes in advance.",
         "https://www.ready.gov/animals"),
        ("If large animals cannot be evacuated, decide beforehand whether to "
         "move them into a barn or turn them loose outside.",
         "https://www.ready.gov/animals"),
    ),
}
ACTIONS_NOTE = (
    "This guidance is the United States government's (Ready.gov). Elsewhere, "
    "follow the national meteorological service and local authorities; each "
    "storm lists the centres responsible for it."
)

# ----------------------------------------------------------------------------
# how the derived numbers were made
# ----------------------------------------------------------------------------
METHODS = {
    "path": ("Derived here: the analysed track, then the official forecast hour by "
             "hour, centre and wind radii interpolated linearly between forecast "
             "times. Never extended past the last forecast point."),
    "exposure": ("Derived here: when each wind threshold first reaches a place if "
                 "the storm follows the official forecast track exactly. A "
                 "threshold is evaluated only where the forecast carries radii for "
                 "it; where it does not, the place lists it as not forecast. The "
                 "official wind speed probabilities carry the uncertainty."),
    "parallax": ("Derived here: cloud tops 15 km up appear displaced by 15 km times "
                 "the tangent of the viewing zenith angle, away from the "
                 "sub-satellite point."),
    "satellite": ("The geostationary imager with the smallest viewing zenith angle "
                  "at the centre; none beyond 70 degrees."),
    "motion": ("The advisory's where it gives one; otherwise the great-circle track "
               "between the last two analysed fixes."),
    "category": ("Saffir-Simpson category from the one-minute sustained wind; for "
                 "JTWC's storms the equivalent category."),
    "here": ("Derived here from each storm's official forecast, hour by hour, centre "
             "and wind radii interpolated linearly between forecast times: the "
             "timeline the exposure table is computed from, under the same rules, so "
             "a radius the forecast does not give is not forecast, never zero. "
             "Distances are great-circle. The cone, the surge areas and the formation "
             "areas are the centres' own polygons; a warned coast is measured to the "
             "nearest point of its segment. This is not an official product: the "
             "official chances are each storm's wind speed probabilities, and the "
             "warnings for a coast are its national meteorological service's."),
    "detail": ("The Detail layer shows Harmonized Landsat and Sentinel-2 imagery, "
               "30 m pixels, for the newest day with an image at the centre of the "
               "view: GIBS lists the same days everywhere, so the page looks at the "
               "tile there, day by day back from the newest, 40 days at most. Earlier "
               "and later step to the next day with an image there. Each day is that "
               "day's passes, clouds as seen, Sentinel-2 over Landsat: where the two "
               "meet, the clouds differ by the hours between their passes. 30 m shows "
               "fields, runways and the outline of a town, not streets."),
    "frames": ("The newest frame NASA GIBS lists for each imager that is at least "
               "45 minutes old. GIBS lists a frame before its tiles are all made: on "
               "25 September 2026 Himawari's newest frames were missing tiles 30 "
               "minutes on, and GOES frames were served part white at 46. A tile "
               "missing, or more than a fifth pure white, from one of an imager's "
               "three newest frames sets that frame aside for a quarter of an hour, "
               "and the imager shows the frame before it, so one imager never mixes "
               "two times."),
}

PRODUCT_KINDS = ("watches", "cone", "surge", "winds")


# ----------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------
def _wrap(lon: float) -> float:
    return (lon + 180.0) % 360.0 - 180.0


def _near(lon: float, ref: float, digits: int | None = 2) -> float:
    """``lon`` written within 180 degrees of ``ref``: 179.2 near -179.4 is -180.8."""
    lon = ref + _wrap(lon - ref)
    return lon if digits is None else round(lon, digits)


def _iso(stamp: str) -> str | None:
    """An ATCF ``YYYYMMDDHH`` as ISO 8601 UTC."""
    stamp = str(stamp or "")
    if len(stamp) != 10 or not stamp.isdigit():
        return None
    return f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]}T{stamp[8:10]}:00:00Z"


def _iso_time(text) -> str | None:
    """Any ISO 8601 time, ``Z`` or offset, as ``YYYY-MM-DDTHH:MM:SSZ``."""
    text = str(text or "").strip()
    if not text:
        return None
    try:
        when = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hours(stamp: str, reference: str) -> int:
    """Whole hours from ``reference`` to ``stamp``, both ``YYYYMMDDHH``."""
    def parse(value: str) -> datetime:
        return datetime.strptime(value, "%Y%m%d%H")
    return round((parse(stamp) - parse(reference)) / timedelta(hours=1))


def _radii(fix) -> dict:
    """NE, SE, SW, NW radius of each threshold, nautical miles; null if not given."""
    out = {}
    for threshold in exposure.THRESHOLDS:
        quadrants = fix.radius(threshold)
        out[str(threshold)] = None if quadrants is None else [int(q) for q in quadrants]
    return out


def _ring(points, ref: float) -> list:
    return [[_near(lon, ref), round(lat, 3)] for lon, lat in points]


# ----------------------------------------------------------------------------
# one storm
# ----------------------------------------------------------------------------
def centre_name(storm) -> str:
    """The centre that issues this storm's advisories: CPHC's past 140W."""
    return cyclones.issuing_centre(storm)


def responsible(centre: str, basin: str, lon: float, lat: float) -> list[dict]:
    """The centres responsible for warnings where a storm is, most official first."""
    def entry(key: str, role: str) -> dict:
        name, url = RSMC[key]
        return {"name": name, "role": role, "url": url}

    rsmc = "WMO regional specialized centre: the official advisories for this ocean"
    if centre in ("NHC", "CPHC"):
        return [entry(centre, rsmc)]
    out = []
    east = lon % 360.0
    if basin == "WP":
        out.append(entry("JMA", rsmc))
    elif basin == "IO":
        out.append(entry("IMD", rsmc))
    elif basin == "SH":
        if 30.0 <= east < 90.0:
            out.append(entry("REUNION", rsmc))
        elif 90.0 <= east < 160.0:
            out.append(entry("BOM", "Tropical cyclone warning centres for the "
                                    "Australian region"))
        elif 160.0 <= east < 240.0:
            out.append(entry("NADI", rsmc) if lat >= -25.0
                       else entry("WELLINGTON", "Tropical cyclone warning centre "
                                                "south of 25S"))
    out.append({"name": "JTWC", "role": "Warnings for United States forces",
                "url": CENTRES["JTWC"]})
    return out


def _status(storm, kind: str) -> str:
    """What was issued of one protective product.

    ``issued``; ``none`` - the index links no such product, so none is in
    effect; ``unavailable`` - linked but not fetched or not readable; ``not
    published`` - JTWC issues no cone, surge, probabilities or coastal
    watches, which are the national services' there.
    """
    if storm.centre == "JTWC":
        return "not published"
    links = (storm.advisory or {}).get("products")
    value = None if storm.products is None else getattr(storm.products, kind)
    if links is not None and not links.get(kind):
        return "none"
    if value is None:
        return "unavailable"
    return "issued" if value else "none"


def _forecast(storm) -> list:
    """The official forecast, one fix per lead, to the horizon."""
    ahead: dict[int, object] = {}
    for fix in sorted(storm.forecast, key=lambda f: f.tech not in ("OFCL", "JTWC")):
        if 0 < fix.tau <= cyclones.HORIZON:
            ahead.setdefault(fix.tau, fix)
    return [ahead[tau] for tau in sorted(ahead)]


def _point(fix, ref: float, hour: int | None) -> dict:
    return {
        "t": _iso(cyclones.valid_stamp(fix)), "hour": hour,
        # Unrounded: the page times the wind's arrival at any point from
        # these, and agrees with the exposure table to the hour only so.
        "lon": _near(fix.lon, ref, None), "lat": fix.lat,
        "wind": fix.wind, "pressure": fix.pressure, "stage": fix.stage,
        "category": fix.category, "label": fix.label, "radii": _radii(fix),
    }


def _path(storm, now, ref: float) -> list:
    """The analysed track, then the official forecast hour by hour."""
    hourly = exposure.timeline(now, _forecast(storm))
    start = cyclones.valid_stamp(hourly[0]) if hourly else None
    past = [f for f in storm.track
            if f.tau == 0 and (start is None or f.stamp < start)]
    out = [_point(f, ref, _hours(f.stamp, now.stamp)) for f in past]
    for fix in hourly:
        out.append(_point(fix, ref, _hours(cyclones.valid_stamp(fix), now.stamp)))
    return out


def _motion(storm) -> dict | None:
    advisory = storm.advisory or {}
    toward, speed = advisory.get("movement_dir"), advisory.get("movement_kt")
    if isinstance(toward, (int, float)) and isinstance(speed, (int, float)):
        return {"toward": toward, "kt": speed, "source": "advisory"}
    move = storm.translation
    if move is None:
        return None
    return {"toward": round(move[1]), "kt": round(move[0]), "source": "track"}


def _view(now) -> dict:
    best = exposure.best_satellite(now.lon, now.lat)
    view = {"satellite": None, "zenith": None, "parallax": None, "height_km": 15.0,
            "offset_km": None, "toward": None}
    if best is None:
        return view
    name, zenith = best
    lon, lat = exposure.parallax(now.lon, now.lat, exposure.SATELLITES[name])
    view.update(
        satellite=name, zenith=round(zenith, 1),
        parallax=[_near(lon, now.lon), round(lat, 3)],
        offset_km=round(cyclones.great_circle(now.lon, now.lat, lon, lat), 1),
        toward=round(exposure.bearing(now.lon, now.lat, lon, lat)),
    )
    return view


def _products(storm, ref: float) -> dict:
    status = {kind: _status(storm, kind) for kind in PRODUCT_KINDS}
    products = storm.products
    out = {"products": status, "cone": None, "watches": None, "surge": None,
           "winds": None}
    if status["cone"] == "issued":
        out["cone"] = _ring(products.cone, ref)
    if status["watches"] in ("issued", "none"):
        out["watches"] = [{"kind": w.kind, "coords": _ring(w.coords, ref)}
                          for w in (products.watches or ())] if products else []
    if status["surge"] in ("issued", "none"):
        out["surge"] = [{"label": a.label, "feet": a.feet, "ring": _ring(a.ring, ref)}
                        for a in (products.surge or ())] if products else []
    if status["winds"] == "issued":
        winds = products.winds
        out["winds"] = {
            "issued": winds.issued, "advisory": winds.advisory,
            "hours": list(winds.hours),
            # 0 is the product's X: below one percent.
            "rows": [{"place": row.place, "threshold": row.threshold,
                      "cumulative": list(row.cumulative), "total": row.total}
                     for row in winds.rows],
        }
    # What the public advisory says is in effect, in its own words, by kind.
    out["in_effect"] = ({kind: list(areas) for kind, areas in products.in_effect or ()}
                        if products is not None else {})
    # The advisory each product was issued with, which can lag the storm's
    # current one by a cycle.
    out["product_advisories"] = dict(products.advisories) if products is not None else {}
    return out


def _exposure(storm, ref: float) -> list:
    # Without an official forecast there is no track to be exposed to: the
    # analysed position alone is not one.
    if not _forecast(storm):
        return []
    rows = []
    for found in exposure.exposures(storm):
        rows.append({
            "place": found.place, "country": found.country,
            "population": found.population,
            "lon": _near(found.lon, ref), "lat": round(found.lat, 3),
            "arrival": {str(t): _iso(stamp) if stamp else None
                        for t, stamp in found.arrival.items()},
            "unknown": list(found.unknown),
            "closest_km": round(found.closest_km),
            "closest": _iso(found.closest_stamp),
        })
    return rows


def _advisory_fix(storm, centre: str, ref: float) -> dict | None:
    """Where the advisory put the storm, and when.

    NHC's advisory is written three hours after the synoptic analysis the
    best track ends on, and can differ from it: on 25 September 2026 Polo
    was 908 mb in the 12Z deck and 900 mb in the 15Z advisory. JTWC's
    warning position is its analysis, at the warning's own time.
    """
    advisory = storm.advisory or {}
    lat, lon = advisory.get("lat"), advisory.get("lon")
    if not all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lon)):
        return None
    now = storm.latest
    when = (_iso(now.stamp) if centre == "JTWC" and now is not None
            else _iso_time(advisory.get("last_update")))
    if when is None:
        return None
    return {"t": when, "lat": round(lat, 2), "lon": _near(lon, ref),
            "wind": advisory.get("wind"), "pressure": advisory.get("pressure")}


def storm_entry(storm) -> dict | None:
    """One live storm as the page draws it; None without a position."""
    now = storm.latest
    if now is None:
        return None
    ref = round(_wrap(now.lon), 2)
    advisory = storm.advisory or {}
    centre = centre_name(storm)
    entry = {
        "id": storm.key, "name": storm.name, "title": storm.title,
        "designation": storm.designation, "centre": centre,
        "basin": storm.basin, "basin_name": storm.basin_name,
        "label": now.label, "short": now.short, "category": now.category,
        "stage": now.stage, "formed": now.formed, "wind": now.wind, "pressure": now.pressure,
        "lat": round(now.lat, 2), "lon": ref, "t": _iso(now.stamp),
        "motion": _motion(storm),
        "advisory": cyclones._advisory_number(advisory.get("advisory", "")) or None,
        "issued": _iso_time(advisory.get("last_update")),
        "advisory_fix": _advisory_fix(storm, centre, ref),
        "rmw": now.rmw, "eye": now.eye, "radii": _radii(now),
        "track": [_point(f, ref, _hours(f.stamp, now.stamp))
                  for f in storm.track if f.tau == 0],
        "forecast": [_point(f, ref, f.tau) for f in _forecast(storm)],
        "path": _path(storm, now, ref),
        "exposure": _exposure(storm, ref),
        "view": _view(now),
        "links": {
            "advisory": advisory.get("public") or None,
            "discussion": advisory.get("discussion") or None,
            "graphics": advisory.get("graphics") or None,
            "centre": {"name": centre, "url": CENTRES.get(centre)},
            "responsible": responsible(centre, storm.basin, now.lon, now.lat),
        },
        "notes": list(storm.notes)
                 + list(getattr(storm.products, "notes", None) or ()),
    }
    entry.update(_products(storm, ref))
    return entry


def _invest(storm) -> dict | None:
    now = storm.latest
    if now is None:
        return None
    ref = round(_wrap(now.lon), 2)
    return {
        "id": storm.key, "name": storm.title, "basin": storm.basin,
        "t": _iso(now.stamp), "lat": round(now.lat, 2), "lon": ref,
        "wind": now.wind, "pressure": now.pressure, "stage": now.stage,
        "track": [_point(f, ref, _hours(f.stamp, now.stamp))
                  for f in storm.track if f.tau == 0],
    }


def _area(area) -> dict:
    return {
        "key": area.key, "centre": area.centre, "basin": area.basin,
        "label": area.label, "lon": round(_wrap(area.lon), 2), "lat": round(area.lat, 2),
        "chance_2day": area.chance_2day, "chance_7day": area.chance_7day,
        "potential": area.potential, "text": area.text, "alert": area.alert,
        "issued": area.issued,
        "area": _ring(area.area, _wrap(area.lon)),
        "arrow": _ring(area.arrow, _wrap(area.lon)),
        "formation": _formation(getattr(area, "formation", None)),
    }


def _formation(alert) -> dict | None:
    """What JTWC's formation alert for an area says, beyond its box."""
    if alert is None or alert.cancelled:
        return None
    return {"issued": alert.issued, "until": alert.until, "motion": alert.motion,
            "wind": list(alert.wind), "pressure": alert.pressure}


def _coast() -> dict:
    """The vendored coastline, delta-encoded in hundredths of a degree."""
    lines = []
    for line in coastline.lines(COAST_LEVEL):
        x0 = y0 = 0
        parts = []
        for lon, lat in line:
            x, y = round(lon * 100), round(lat * 100)
            parts.append(f"{x - x0},{y - y0}")
            x0, y0 = x, y
        lines.append(",".join(parts))
    return {"level": COAST_LEVEL, "tolerance_deg": coastline.TOLERANCES[COAST_LEVEL],
            "encoding": ("lon,lat pairs in hundredths of a degree, each after the "
                         "first as the change from the one before"),
            "source": "Natural Earth 10m coastline, public domain",
            "lines": lines}


# ----------------------------------------------------------------------------
# the payload
# ----------------------------------------------------------------------------
def _plain_layer(layer: dict) -> dict:
    """A layer as JSON types: its imagers a dict, its stack and overlays lists."""
    out = dict(layer)
    if "satellites" in out:
        out["satellites"] = dict(out["satellites"])
    if "stack" in out:
        out["stack"] = list(out["stack"])
    if "over" in out:
        out["over"] = list(out["over"])
    return out


def payload(state) -> dict:
    """Everything the storm desk shows, as plain JSON types."""
    storms = getattr(state, "cyclones", None)
    live = storms.active if storms is not None else ()
    entries = [e for e in (storm_entry(s) for s in live) if e is not None]
    invests = [e for e in (_invest(s) for s in getattr(storms, "invests", ()) or ())
               if e is not None]
    return {
        "schema": SCHEMA,
        "built": _iso_time(getattr(state, "run_at", "")) or getattr(state, "run_at", None),
        "as_of": getattr(storms, "as_of", None) or None,
        "storms": entries,
        "invests": invests,
        "outlook": [_area(a) for a in (getattr(storms, "outlook", None) or [])],
        "outlook_issued": dict(getattr(storms, "outlook_issued", None) or {}),
        "layers": [_plain_layer(layer) for layer in LAYERS],
        "satellites": [{"name": name, "lon": lon, "operator": OPERATORS[name][0],
                        "imager": OPERATORS[name][1]}
                       for name, lon in exposure.SATELLITES.items()],
        "gibs": dict(GIBS_ENDPOINTS),
        "coast": _coast(),
        "actions": {
            "people": [{"text": t, "source": u} for t, u in ACTIONS["people"]],
            "animals": [{"text": t, "source": u} for t, u in ACTIONS["animals"]],
            "note": ACTIONS_NOTE,
        },
        "responsibility": RESPONSIBILITY,
        "methods": dict(METHODS),
        "notes": [*(getattr(storms, "notes", None) or []),
                  *(getattr(storms, "upgrades", None) or [])],
    }


def write_json(state, path: Path) -> Path:
    """``storms.json``: the payload, for the page to re-read while it is open."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload(state), separators=(",", ":")), encoding="utf-8")
    return path


# ----------------------------------------------------------------------------
# the page
# ----------------------------------------------------------------------------
# Official product colours, from NHC's KML styles (aabbggrr, decoded). Each is
# drawn beside its label, never alone.
PRODUCT_COLOURS = {
    "Hurricane Warning": "#ff0000",
    "Hurricane Watch": "#ffaaff",
    "Tropical Storm Warning": "#5500ff",
    "Tropical Storm Watch": "#f7e222",
}
# Weakest first, the order they are drawn in, so a warning lies over a watch.
PRODUCT_ORDER = ("Tropical Storm Watch", "Tropical Storm Warning", "Hurricane Watch",
                 "Hurricane Warning")
# NHC's formation-chance colours and the ranges they stand for.
OUTLOOK_COLOURS = {"low": "#ffff00", "medium": "#ff9200", "high": "#e80000"}
OUTLOOK_WORDS = (("low", "Low", "under 40%"), ("medium", "Medium", "40 to 60%"),
                 ("high", "High", "over 60%"))
SURGE_COLOUR = "#0070ff"
CONE_COLOURS = {"fill": "#2ee1ea", "edge": "#007bff"}

DRAWN = (("cone", "Forecast cone"), ("radii", "Wind radii"),
         ("watches", "Watches and warnings"), ("surge", "Peak storm surge"),
         ("outlook", "Formation outlook"), ("places", "Places in the path"),
         ("towns", "Town names"))

LEAD_TIME = (
    "Tropical cyclones cannot be prevented or steered. Seeding hurricanes in "
    "Project STORMFURY (1962 to 1983) produced no change that could be told "
    "apart from what the storms did on their own. What a desk like this gives "
    "is lead time: where each storm is, where it is forecast to go and what "
    "its warning centre has issued, early enough to move people and animals "
    "out of its way."
)

_COMPASS = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
            "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")


def _when(iso) -> str:
    """``2026-09-25T15:00:00Z`` as ``25 Sep 15:00 UTC``."""
    try:
        when = datetime.strptime(str(iso), "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return str(iso or "")
    return f"{when.day} {when:%b %H:%M} UTC"


def _alert_words(until, now) -> str:
    """A formation alert in words as of ``now``: until when it holds, or that
    it ran out with nothing newer read. The page's alertWords says the same."""
    if not until:
        return "formation alert in effect"
    if outlook.lapsed(until, now):
        return f"formation alert ran to {_when(until)}; nothing newer read"
    return f"formation alert until {_when(until)}"


def _alert_html(until, now) -> str:
    """The same, in a span the page rewords when ``until`` passes while it is open."""
    words = esc(_alert_words(until, now))
    return f'<span data-until="{esc(until)}">{words}</span>' if until else words


def _time(iso, text: str | None = None) -> str:
    """A time the page ages while it stays open."""
    if not iso:
        return esc(text or "")
    shown = esc(text or _when(iso))
    return f'<time datetime="{esc(iso)}" data-age="{shown}">{shown}</time>'


def _stamped(text: str, pattern: str) -> str:
    """An issue time as a centre writes it, aged when it can be read."""
    try:
        when = datetime.strptime(str(text).strip(), pattern)
    except ValueError:
        return esc(text or "not given")
    return _time(when.strftime("%Y-%m-%dT%H:%M:%SZ"))


def _pos(lon: float, lat: float) -> str:
    lon = _wrap(lon)
    return (f"{abs(lat):.1f}°{'N' if lat >= 0 else 'S'} "
            f"{abs(lon):.1f}°{'W' if lon < 0 else 'E'}")


def _compass(degrees: float) -> str:
    return _COMPASS[round((degrees % 360.0) / 22.5) % 16]


def _cap(text) -> str:
    text = str(text or "")
    return text[:1].upper() + text[1:]


def _https(url) -> str:
    """Every centre linked serves HTTPS; an index that says http is upgraded."""
    url = str(url or "")
    return "https://" + url[7:] if url.startswith("http://") else url


def _link(url, words: str) -> str:
    return f'<a href="{esc(_https(url))}" target="_blank" rel="noopener">{esc(words)}</a>'


def _pct(value) -> str:
    return "not given" if value is None else f"{value}%"


def _hues(entries) -> dict:
    """Each storm's colour, NHC's storms first as the dashboard's track map has
    them, then JTWC's; past the fifth, neutral ink and the name beside it."""
    order = ([e for e in entries if e["centre"] != "JTWC"]
             + [e for e in entries if e["centre"] == "JTWC"])
    return {e["id"]: STORM_HUES[i] if i < len(STORM_HUES) else NEUTRAL
            for i, e in enumerate(order)}


def _level(area) -> str:
    """An outlook area's category in NHC's words: low, medium or high."""
    potential = str(area.get("potential") or "").strip().lower()
    if potential in OUTLOOK_COLOURS:
        return potential
    chance = area.get("chance_7day")
    if chance is None:
        return ""
    return "high" if chance > 60 else "medium" if chance >= 40 else "low"


def _latest(entry) -> tuple:
    """Wind, pressure and intensity as last issued: the advisory's, where it has them."""
    fix = entry.get("advisory_fix") or {}
    wind = fix.get("wind") if isinstance(fix.get("wind"), int) else entry["wind"]
    pressure = (fix.get("pressure") if isinstance(fix.get("pressure"), int)
                else entry["pressure"])
    label = (entry["label"] if wind == entry["wind"]
             else cyclones.intensity_label(wind, entry["stage"], entry.get("formed", True)))
    return wind, pressure, label


def _motion_words(motion, short: bool = False) -> str:
    if not motion:
        return "" if short else "not given"
    if not motion.get("kt"):
        return "stationary"
    if short:
        return f"{_compass(motion['toward'])} {motion['kt']} kt"
    source = ("the advisory" if motion["source"] == "advisory"
              else "the last two best-track fixes (derived)")
    return (f"toward the {_compass(motion['toward'])} ({motion['toward']:.0f}°) at "
            f"{motion['kt']} kt, from {source}")


def _facts(rows) -> str:
    """A definition list from (term, safe HTML) pairs."""
    return ('<dl class="facts">'
            + "".join(f"<dt>{esc(term)}</dt><dd>{value}</dd>" for term, value in rows)
            + "</dl>")


def _storm_row(entry, hue: str) -> str:
    key, title = esc(entry["id"]), esc(entry["title"])
    wind, pressure, label = _latest(entry)
    facts = [_cap(label)]
    if wind is not None:
        facts.append(f"{wind} kt")
    if pressure:
        facts.append(f"{pressure} mb")
    motion = _motion_words(entry["motion"], short=True)
    if motion:
        facts.append(motion)
    issued = (f'{esc(entry["centre"])} advisory {esc(entry["advisory"])}'
              if entry["advisory"] else esc(entry["centre"]))
    if entry["issued"]:
        issued += f' &middot; {_time(entry["issued"])}'
    return (
        f'<li class="stormrow" id="row-{key}" data-row="{key}">'
        f'<span class="swatch" style="background:{hue}"></span>'
        f'<div class="stormtext"><button type="button" class="stormname" '
        f'data-select="{key}">{title}</button>'
        f'<div class="stormfacts">{" &middot; ".join(esc(f) for f in facts)}</div>'
        f'<div class="stormage">{issued}</div></div>'
        f'<button type="button" class="eyebtn" data-fly="{key}" '
        f'aria-label="Fly to the eye of {title}">Eye</button></li>'
    )


def _now_pane(entry) -> str:
    rows = [("Best track", f'{esc(_pos(entry["lon"], entry["lat"]))}, '
                           f'{entry["wind"]} kt'
                           + (f', {entry["pressure"]} mb' if entry["pressure"] else "")
                           + f', {_time(entry["t"])}')]
    fix = entry["advisory_fix"]
    if fix:
        rows.append((f'Advisory {entry["advisory"] or ""}'.strip(),
                     f'{esc(_pos(fix["lon"], fix["lat"]))}'
                     + (f', {fix["wind"]} kt' if fix["wind"] is not None else "")
                     + (f', {fix["pressure"]} mb' if fix["pressure"] else "")
                     + f', {_time(fix["t"])}'))
    rows.append(("Intensity", esc(_cap(_latest(entry)[2]))
                 + (" (JTWC's one-minute wind, as its Saffir-Simpson equivalent)"
                    if entry["centre"] == "JTWC" else "")))
    rows.append(("Motion", esc(_motion_words(entry["motion"]))))
    eye = []
    if entry["eye"]:
        eye.append(f'diameter {entry["eye"]} nm')
    if entry["rmw"]:
        eye.append(f'radius of maximum wind {entry["rmw"]} nm')
    rows.append(("Eye", esc(", ".join(eye) + " (best track)" if eye
                            else "not given in the best track")))
    view = entry["view"]
    if view["satellite"]:
        operator, imager = OPERATORS[view["satellite"]]
        rows.append(("Satellite", esc(
            f'{view["satellite"]} ({operator} {imager}), viewing zenith '
            f'{view["zenith"]}°. Cloud tops {view["height_km"]:.0f} km up appear '
            f'{view["offset_km"]} km to the {_compass(view["toward"])} of the surface '
            "centre (derived); the dashed ring on the map is where the eye appears.")))
    else:
        rows.append(("Satellite", "No geostationary imager in NASA GIBS sees this "
                                  "storm within 70° of zenith."))
    radii = [[f"{t} kt"] + ([f"{q} nm" for q in entry["radii"][str(t)]]
                            if entry["radii"][str(t)] else ["not given"] * 4)
             for t in exposure.THRESHOLDS]
    links = entry["links"]
    anchors = [_link(links[k], words) for k, words in
               (("advisory", "Public advisory"), ("discussion", "Forecast discussion"),
                ("graphics", "Graphics")) if links.get(k)]
    if links["centre"].get("url"):
        anchors.append(_link(links["centre"]["url"], links["centre"]["name"]))
    notes = "".join(f"<li>{esc(n)}</li>" for n in entry["notes"])
    return (_facts(rows)
            + table("Wind radii now, nautical miles by quadrant (best track)",
                    ["Wind", "NE", "SE", "SW", "NW"], radii, expanded=True)
            + (f'<p class="links">{" ".join(anchors)}</p>' if anchors else "")
            + (f'<ul class="notes">{notes}</ul>' if notes else ""))


def _forecast_pane(entry) -> str:
    centre, number = esc(entry["centre"]), entry["advisory"]
    intro = (f"<p>{centre}'s official forecast"
             + (f", advisory {esc(number)}" if number else "")
             + (f", issued {_time(entry['issued'])}" if entry["issued"] else "") + ". "
             "Between forecast times the map interpolates the centre and wind radii "
             "linearly (derived), and draws nothing past the last forecast point.</p>")
    cone = {"issued": "The forecast cone is on the map.",
            "none": "No forecast cone is issued for this advisory.",
            "unavailable": "The forecast cone was issued but could not be fetched this run.",
            "not published": "JTWC publishes no forecast cone."}[entry["products"]["cone"]]
    ahead = [[f'+{p["hour"]} h', _when(p["t"]), _pos(p["lon"], p["lat"]),
              "" if p["wind"] is None else f'{p["wind"]} kt', _cap(p["label"])]
             for p in entry["forecast"]]
    past = [[_when(p["t"]), _pos(p["lon"], p["lat"]),
             "" if p["wind"] is None else f'{p["wind"]} kt',
             f'{p["pressure"]} mb' if p["pressure"] else "", _cap(p["label"])]
            for p in entry["track"]]
    return (intro + f"<p>{esc(cone)}</p>"
            + (table("Official forecast", ["Lead", "Valid", "Position", "Wind", "Intensity"],
                     ahead, expanded=True) if ahead
               else "<p>No official forecast in this run.</p>")
            + table("Best track", ["Time", "Position", "Wind", "Pressure", "Intensity"],
                    past))


def _watches(entry) -> str:
    status, name = entry["products"]["watches"], esc(entry["title"])
    if status == "not published":
        return ("<p>JTWC does not issue coastal watches or warnings. Each country's "
                "national meteorological service issues them for its own coast; see "
                "who warns here, below.</p>")
    # The public advisory's own words for where each is in effect; its lines
    # name the coast only where the advisory did not come.
    said, drawn = entry.get("in_effect") or {}, entry["watches"] or []
    kinds = [kind for kind in reversed(PRODUCT_ORDER)
             if kind in said or any(w["kind"] == kind for w in drawn)]
    kinds += [kind for kind in dict.fromkeys([*said, *(w["kind"] for w in drawn)])
              if kind not in kinds]
    if not kinds:
        if status == "unavailable":
            return (f"<p>Watches and warnings for {name} were issued but could not be "
                    "fetched this run. Read them in the public advisory.</p>")
        return f"<p>No coastal watches or warnings are in effect for {name}.</p>"
    items, rows = [], []
    for kind in kinds:
        coasts = said.get(kind) or alerts._coasts(
            [SimpleNamespace(coords=tuple(map(tuple, w["coords"])))
             for w in drawn if w["kind"] == kind])
        rows.extend([kind, coast] for coast in coasts)
        key = (f'<span class="linekey" style="background:{PRODUCT_COLOURS[kind]}"></span>'
               if kind in PRODUCT_COLOURS else "")
        meaning = alerts.PRODUCT_MEANING.get(kind)
        items.append(f'<li>{key}<b>{esc(kind)}</b> {esc("; ".join(coasts))}.'
                     + (f" {esc(meaning)}" if meaning else "") + "</li>")
    lost = ("<p>Their lines could not be fetched this run, so the map does not draw "
            "them; the list is the public advisory's.</p>" if status == "unavailable" else "")
    return (f'<ul class="wwlist">{"".join(items)}</ul>' + lost
            + table("Watches and warnings", ["Product", "Coast"], rows))


def _winds(entry) -> str:
    status, winds = entry["products"]["winds"], entry["winds"]
    if status == "not published":
        return "<p>JTWC publishes no wind speed probabilities.</p>"
    if status == "unavailable":
        return ("<p>The wind speed probabilities were issued but could not be fetched "
                "this run.</p>")
    if not winds or not winds["rows"]:
        return "<p>No wind speed probabilities are issued for this advisory.</p>"
    places: dict[str, dict] = {}
    for row in winds["rows"]:
        places.setdefault(row["place"], {})[row["threshold"]] = row["total"]
    order = sorted(places, key=lambda p: (-places[p].get(64, 0), -places[p].get(50, 0),
                                          -places[p].get(34, 0), p))

    def cell(value) -> str:
        return "" if value is None else "<1%" if value == 0 else f"{value}%"

    rows = [[p, cell(places[p].get(34)), cell(places[p].get(50)), cell(places[p].get(64))]
            for p in order]
    hours = winds["hours"][-1] if winds["hours"] else 120
    return (f"<p>The chance that each wind occurs at each place within {hours} hours, "
            f"as {esc(entry['centre'])} issued it "
            f"({_stamped(winds['issued'], '%H%M UTC %a %b %d %Y')}). These carry the "
            "forecast's uncertainty.</p>"
            + table(f"Wind speed probabilities, advisory {winds['advisory']}, issued "
                    f"{winds['issued']}", ["Place", "34 kt", "50 kt", "64 kt"], rows,
                    expanded=True))


def _surge(entry) -> str:
    status = entry["products"]["surge"]
    if status == "not published":
        return "<p>JTWC publishes no storm surge forecast.</p>"
    if status == "unavailable":
        return ("<p>The peak storm surge forecast was issued but could not be fetched "
                "this run.</p>")
    if not entry["surge"]:
        return "<p>No peak storm surge forecast is issued for this storm.</p>"
    # NHC writes the range with its unit: "1-3 ft".
    rows = [[area["label"], area["feet"]] for area in entry["surge"]]
    return (f'<p><span class="swatch" style="background:{SURGE_COLOUR}"></span> '
            f"Peak storm surge, feet above ground, as {esc(entry['centre'])} issued "
            "it.</p>"
            + table("Peak storm surge", ["Area", "Surge"], rows, expanded=True))


def _exposure_table(entry) -> str:
    if not entry["forecast"]:
        return ("<p>No official forecast this run, so which places its wind would "
                "reach, and when, cannot be worked out here; read the advisory.</p>")
    intro = ("<p>If the storm follows the official forecast track exactly (derived "
             "here, hour by hour): when each wind first reaches each place. The "
             "official probabilities above carry the uncertainty; &ldquo;not "
             "forecast&rdquo; means the forecast gives no radius for that wind when "
             "it would arrive.</p>")
    if not entry["exposure"]:
        return intro + ("<p>No place in the desk's gazetteer comes inside the "
                        "forecast wind radii.</p>")
    rows = []
    for row in entry["exposure"]:
        unknown = {str(u) for u in row["unknown"]}
        cells = []
        for threshold in ("34", "50", "64"):
            at = row["arrival"].get(threshold)
            cells.append(_when(at) if at else
                         "not forecast" if threshold in unknown else "not reached")
        rows.append([f'{row["place"]}, {row["country"]}',
                     f'{row["closest_km"]} km, {_when(row["closest"])}'] + cells)
    return intro + table("Exposure if the storm follows the official track",
                         ["Place", "Closest approach", "34 kt from", "50 kt from",
                          "64 kt from"], rows, expanded=True)


# The products, as a note on the older ones names them.
LAG_NAMES = (("in_effect", "the summary of what is in effect"),
             ("watches", "the watches and warnings"), ("cone", "the forecast cone"),
             ("surge", "the peak storm surge"), ("winds", "the wind speed probabilities"))


def _lagging(entry) -> list[str]:
    """One sentence for each older advisory some of the storm's products are from.

    Only a product a later advisory would have reissued is older: under the
    intermediate advisory 20A the wind probabilities of 20 are the latest.
    """
    current, own = entry["advisory"], entry.get("product_advisories") or {}
    behind: dict[str, list[str]] = {}
    for kind, name in LAG_NAMES:
        number = own.get(kind)
        if current and number and cyclones._older(kind, number, current):
            behind.setdefault(number, []).append(name)
    out = []
    for number, names in behind.items():
        said = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
        verb = "are" if len(names) > 1 or said.endswith("s") else "is"
        out.append(f"{said[0].upper()}{said[1:]} {verb} from advisory {number}; "
                   f"the current advisory is {current}.")
    return out


def _protect_pane(entry) -> str:
    lag = "".join(f'<p class="lagnote">{esc(said)}</p>' for said in _lagging(entry))
    centres = "".join(f'<li>{_link(c["url"], c["name"])}: {esc(c["role"])}</li>'
                      for c in entry["links"]["responsible"])
    return (lag
            + "<h4>Watches and warnings</h4>" + _watches(entry)
            + "<h4>Wind speed probabilities</h4>" + _winds(entry)
            + "<h4>Peak storm surge</h4>" + _surge(entry)
            + "<h4>Places in the forecast path</h4>" + _exposure_table(entry)
            + f'<h4>Who warns here</h4><ul class="centres">{centres}</ul>'
            + '<p><a href="#actions">What to do: people, pets and livestock</a></p>')


def _storm_section(entry, hue: str) -> str:
    key, title = esc(entry["id"]), esc(entry["title"])
    tabs = "".join(
        f'<button type="button" role="tab" data-tab="{tab}" '
        f'aria-selected="{"true" if tab == "now" else "false"}">{words}</button>'
        for tab, words in (("now", "Now"), ("forecast", "Forecast"), ("protect", "Protect")))
    return (
        f'<section class="storm" id="storm-{key}" data-storm="{key}">'
        f'<h3 class="stormhead"><span class="swatch" style="background:{hue}"></span>'
        f'{title} <span class="pill">{esc(entry["centre"])}</span>'
        f'<button type="button" class="eyebtn" data-fly="{key}" '
        f'aria-label="Fly to the eye of {title}">Eye</button></h3>'
        f'<div class="tabs" role="tablist" aria-label="{title}">{tabs}</div>'
        f'<div class="pane" data-pane="now" role="tabpanel">{_now_pane(entry)}</div>'
        f'<div class="pane" data-pane="forecast" role="tabpanel">{_forecast_pane(entry)}</div>'
        f'<div class="pane" data-pane="protect" role="tabpanel">{_protect_pane(entry)}</div>'
        f"</section><!--{key}-->"
    )


def _area_issued(area) -> str:
    if area["centre"] == "JTWC":
        iso = _iso_time(area["issued"])
        return _time(iso) if iso else esc(area["issued"] or "not given")
    # NHC names each outlook with its issue time in UTC: "Fri Sep 25 11:40:21 2026".
    return _stamped(area["issued"], "%a %b %d %H:%M:%S %Y")


def _outlook_section(data) -> str:
    areas, invests = data["outlook"], data["invests"]
    items, rows = [], []
    for area in areas:
        level = area.get("level") or _level(area)
        colour = OUTLOOK_COLOURS.get(level, "var(--ink2)")
        formation = area.get("formation") or {}
        facts = []
        if area["centre"] == "JTWC":
            chance = [esc(f"{level or 'unrated'} potential within 24 h")]
            if area.get("alert"):
                chance.append(_alert_html(formation.get("until"), data.get("built")))
            # The alert's own estimate of the system, in a storm row's order.
            wind = formation.get("wind") or ()
            if len(wind) == 2:
                facts.append(f"{wind[0]} to {wind[1]} kt")
            if formation.get("pressure"):
                facts.append(f'{formation["pressure"]} mb')
            if formation.get("motion"):
                facts.append(outlook.moving(formation["motion"]))
        else:
            chance = [esc(f"{_pct(area['chance_2day'])} within 2 days, "
                          f"{_pct(area['chance_7day'])} within 7 days")]
        more = (f'<div class="stormfacts">{" &middot; ".join(esc(f) for f in facts)}</div>'
                if facts else "")
        items.append(
            f'<li class="arearow"><span class="swatch" style="background:{colour}"></span>'
            f'<div class="stormtext"><b>{esc(area["label"])}</b> '
            f'<span class="pill">{esc(area["centre"])}</span>'
            f'<div class="stormfacts">{" &middot; ".join(chance)}</div>'
            f'{more}<div class="stormage">Issued {_area_issued(area)}</div></div>'
            f'<button type="button" class="eyebtn" data-fly="area:{esc(area["key"])}" '
            f'aria-label="Show {esc(area["label"])} on the map">Show</button></li>')
        rows.append([area["label"], area["centre"], _pct(area["chance_2day"]),
                     _pct(area["chance_7day"]), level or "not given"])
    body = (f'<ul class="arearows">{"".join(items)}</ul>'
            + table("Formation outlook", ["Area", "Centre", "2 days", "7 days", "Category"],
                    rows)) if items else "<p>No area is being watched for formation.</p>"
    if invests:
        body += table("Invests", ["Name", "Position", "Wind", "Pressure", "Time"],
                      [[v["name"], _pos(v["lon"], v["lat"]),
                        "" if v["wind"] is None else f'{v["wind"]} kt',
                        f'{v["pressure"]} mb' if v["pressure"] else "", _when(v["t"])]
                       for v in invests], expanded=True)
    return ('<section id="outlook-list" class="panelsec">'
            '<h2 class="panelhead">Formation outlook</h2>'
            "<p>The chance of a tropical cyclone forming, as each centre issued it: NHC "
            "and CPHC within 2 and 7 days, JTWC the potential for a significant "
            "tropical cyclone within 24 hours.</p>" + body + "</section>")


def _actions_section(data) -> str:
    def items(group: str) -> str:
        return "".join(
            f'<li>{esc(a["text"])} '
            f'{_link(a["source"], a["source"].split("//", 1)[-1].replace("www.", ""))}</li>'
            for a in data["actions"][group])

    return ('<section id="actions" class="panelsec"><h2 class="panelhead">What to do</h2>'
            f'<h3 class="subhead">People</h3><ul class="actions">{items("people")}</ul>'
            '<h3 class="subhead">Pets, livestock and other animals</h3>'
            f'<ul class="actions">{items("animals")}</ul>'
            f'<p class="note">{esc(data["actions"]["note"])}</p></section>')


def _about(data) -> str:
    methods = [(k.capitalize(), esc(v)) for k, v in data["methods"].items()]
    notes = "".join(f"<li>{esc(n)}</li>" for n in data["notes"])
    as_of = _iso_time(data["as_of"])
    return ('<section id="about" class="panelsec"><h2 class="panelhead">About this desk</h2>'
            f'<p>{esc(LEAD_TIME)} <a href="dashboard.html#stormfury">What Project '
            "STORMFURY found</a>.</p>"
            f'<p>{esc(RESPONSIBILITY)}</p>' + _facts(methods)
            + f'<p class="note">{esc(GIBS_ENDPOINTS["latency"])} '
              f'{esc(GIBS_ENDPOINTS["credit"])}</p>'
            + f'<p class="note">Built {_time(data["built"])}; storm advisories as of '
              f'{_time(as_of) if as_of else "unknown"}.</p>'
            + (f'<ul class="notes">{notes}</ul>' if notes else "") + "</section>")


def _panel(data, hues: dict, focus: str = "storms", now: str = "") -> str:
    """The side panel. ``now`` is the map's "El Nino now" section: after Here
    on the map, after the storms' outlook on the storm desk."""
    entries = data["storms"]
    if entries:
        live = (f'<h2 class="panelhead">Live storms <span class="pill">{len(entries)}'
                '</span></h2><ul class="stormrows">'
                + "".join(_storm_row(e, hues[e["id"]]) for e in entries) + "</ul>"
                + "".join(_storm_section(e, hues[e["id"]]) for e in entries))
    else:
        live = ('<h2 class="panelhead">Live storms</h2><p>No live tropical cyclones: '
                "no warning centre this desk reads has an advisory open.</p>")
    # Empty until a place is found or the map is tapped; the page fills it,
    # and the line after the panel (#here-said) says which place it is on.
    here = ('<section class="here" id="here" aria-labelledby="here-title" '
            'hidden></section>')
    storms = f'<div id="storm-list">{live}</div>' + _outlook_section(data)
    if focus == "world":
        return here + now + storms + _actions_section(data) + _about(data)
    return here + storms + now + _actions_section(data) + _about(data)


def _legend(data, hues: dict) -> str:
    def key(mark: str, words: str) -> str:
        return f'<span class="key">{mark}{esc(words)}</span>'

    def fill(colour: str, opacity: float | None = None) -> str:
        extra = "" if opacity is None else f";opacity:{opacity}"
        return f'<span class="swatch" style="background:{colour}{extra}"></span>'

    def line(colour: str, dashed: bool = False) -> str:
        return (f'<span class="linekey{" dash" if dashed else ""}" '
                f'style="background:{colour}"></span>')

    storms = [key(fill(hues[e["id"]]), e["title"]) for e in data["storms"]]
    groups = (
        ("Tracks, in the storm's colour", [
            key(line("var(--ink2)"), "Analysed track"),
            key(line("var(--ink2)", dashed=True), "Official forecast")]),
        ("Wind radii, in the storm's colour", [
            key(fill("var(--ink2)", 0.3), "34 kt"), key(fill("var(--ink2)", 0.55), "50 kt"),
            key(fill("var(--ink2)", 0.85), "64 kt")]),
        ("Watches and warnings", [key(line(PRODUCT_COLOURS[kind]), kind)
                                  for kind in reversed(PRODUCT_ORDER)]),
        ("Products", [
            key(f'<span class="swatch" style="background:{CONE_COLOURS["fill"]};'
                f'box-shadow:inset 0 0 0 2px {CONE_COLOURS["edge"]}"></span>', "Forecast cone"),
            key(fill(SURGE_COLOUR), "Peak storm surge"),
            key('<span class="ringkey"></span>', "Eye as the satellite sees it (parallax)")]),
        ("Formation chance in 7 days", [key(fill(OUTLOOK_COLOURS[level]), f"{word} ({span})")
                                        for level, word, span in OUTLOOK_WORDS]),
        ("Places at the scrubber time", [
            key(f'<span class="dotkey" style="background:var(--{status})"></span>',
                f"inside {threshold} kt")
            for status, threshold in (("warning", 34), ("serious", 50), ("critical", 64))]),
    )
    # The storms' colours stay in view under the map; the key to every other
    # mark opens beneath them. El Nino's composite, when it is drawn, leads.
    return ('<div class="desklegend" id="legend" aria-label="Map key">'
            + worldmap.legend() + thennow.legend() +
            '<div class="keygroup" id="storm-key"><span class="keyhead">Storms</span>'
            + "".join(storms or ['<span class="key">No live storms</span>']) + "</div>"
            '<details class="keymore" id="key-more"><summary>Key to the map</summary>'
            + "".join(f'<div class="keygroup"><span class="keyhead">{esc(head)}</span>'
                      f'{"".join(keys)}</div>' for head, keys in groups)
            + "</details></div><!--legend-->")


def _toolbar(first: str = "geocolor", controls: str = "") -> str:
    imagery = [layer for layer in LAYERS if layer["kind"] == "imagery"]
    references = [layer for layer in LAYERS if layer["kind"] == "overlay"]

    def buttons(layers) -> str:
        return "".join(
            f'<button type="button" class="segbtn" id="layer-{layer["id"]}" '
            f'data-layer="{layer["id"]}" '
            f'aria-pressed="{"true" if layer["id"] == first else "false"}" '
            f'title="{esc(layer["about"])}">{esc(layer["name"])}</button>'
            for layer in layers)
    # Town names say, beside their box, when they are not drawn and why.
    drawn = "".join(
        f'<label class="check"><input type="checkbox" id="show-{name}" '
        f'data-show="{name}" checked> {esc(words)}'
        + (' <span class="why" id="why-towns"></span>' if name == "towns" else "")
        + "</label>" for name, words in DRAWN)
    # GIBS's reference tiles are off until asked for: on 25 Sep 2026 they
    # answered 500 at random, and black squares where they had nothing.
    refs = "".join(
        f'<label class="check"><input type="checkbox" id="layer-{layer["id"]}" '
        f'data-ref="{layer["id"]}"> '
        f'{esc(layer["name"])}</label>' for layer in references)
    def option(layer) -> str:
        return (f'<option value="{layer["id"]}"{" selected" if layer["id"] == "infrared" else ""}>'
                f'{esc(layer["name"])}</option>')
    # Every layer that can be drawn beside the base, maps too: Swap puts the
    # base there.
    options = (f'<optgroup label="Map">{"".join(option(l) for l in worldmap.MAP_LAYERS)}</optgroup>'
               f'<optgroup label="NASA imagery">{"".join(option(l) for l in imagery)}</optgroup>')
    return (
        '<nav class="desktools" aria-label="Map controls">'
        f'<div class="seg" role="group" aria-label="Map">{buttons(worldmap.MAP_LAYERS)}</div>'
        f'<div class="seg" role="group" aria-label="NASA imagery">{buttons(imagery)}</div>'
        '<p class="toolnote" id="layer-note" role="status"></p>'
        '<div class="toolrow">' + controls +
        '<details class="menu"><summary class="toolbtn">Overlays</summary>'
        f'<div class="menubody">{drawn}{refs}</div></details>'
        '<button type="button" class="toolbtn" id="compare" aria-pressed="false">'
        'Compare</button>'
        f'<select id="compare-layer" class="toolsel" aria-label="Layer to compare with">'
        f'{options}</select>'
        '<button type="button" class="toolbtn" id="swap">Swap</button>'
        '<button type="button" class="toolbtn" id="loop" aria-pressed="false">Loop</button>'
        "</div></nav>"
    )


def _find() -> str:
    """The search box: a town, region, country or position, from the page's gazetteer."""
    return (
        '<form class="deskfind" id="findform" role="search" autocomplete="off">'
        '<label for="find" class="findlabel">Find a place</label>'
        '<input type="search" id="find" name="q" role="combobox" '
        'aria-autocomplete="list" aria-expanded="false" aria-controls="find-list" '
        'enterkeyhint="search" spellcheck="false" '
        'placeholder="Find a town, region, country or 18.0N 76.8W">'
        '<ul id="find-list" class="findlist" role="listbox" aria-label="Places found" '
        'hidden></ul>'
        '<p id="find-note" role="status" class="findnote" hidden></p>'
        "</form>"
    )


def _map() -> str:
    return (
        '<div class="deskmap" id="map" tabindex="0" role="application" '
        'aria-label="Live tropical cyclones on satellite imagery. Drag to pan, pinch '
        'or scroll to zoom, double-tap to zoom in, tap a storm to fly to its eye.">'
        '<div class="gibspane" id="tiles-b" aria-hidden="true"></div>'
        '<div class="gibspane" id="tiles" aria-hidden="true"></div>'
        '<div class="gibspane" id="refs" aria-hidden="true"></div>'
        '<div class="gibspane" id="enso-tiles" aria-hidden="true"></div>'
        '<canvas id="enso-cells" aria-hidden="true"></canvas>'
        '<div class="gibspane" id="over" aria-hidden="true"></div>'
        '<div class="gibspane" id="over-b" aria-hidden="true"></div>'
        '<svg id="overlay" aria-hidden="true"><g id="coast"></g><g id="geo"></g>'
        '<g id="marks"></g></svg>'
        '<div id="divider" class="ui" role="slider" tabindex="0" '
        'aria-label="Compare divider" aria-valuemin="5" aria-valuemax="95" '
        'aria-valuenow="50" hidden><span class="grip"></span></div>'
        '<div class="deskpill ui" id="frame">Imagery: asking NASA GIBS for the latest '
        "frames</div>"
        '<div class="deskpill warnpill ui" id="status" role="status" hidden></div>'
        '<div class="deskdays ui" id="days" role="group" '
        'aria-label="Day of the detail imagery" hidden>'
        '<button type="button" id="day-earlier" aria-label="Earlier day with an image here">'
        '&#9664;</button><span id="day-now" role="status"></span>'
        '<button type="button" id="day-later" aria-label="Later day with an image here">'
        '&#9654;</button></div>'
        '<button type="button" class="deskpill herepill ui" id="herego" hidden>'
        '</button>'
        + thennow.map_parts() +
        '<div class="deskzoom ui">'
        '<button type="button" data-zoom="1" aria-label="Zoom in">+</button>'
        '<button type="button" data-zoom="-1" aria-label="Zoom out">&minus;</button>'
        '<button type="button" data-fit="1" aria-label="Show every storm">All</button>'
        "</div>"
        f'<div class="deskcredit ui" id="credit">{esc(GIBS_ENDPOINTS["credit"])}</div>'
        "</div>"
    )


def _scrubber() -> str:
    return ('<div class="deskscrub"><label for="scrub">Forecast</label>'
            f'<input type="range" id="scrub" min="0" max="{cyclones.HORIZON}" step="1" '
            'value="0" aria-describedby="scrub-read">'
            '<output id="scrub-read" for="scrub">Now</output></div>')


def css() -> str:
    """The storm desk's own rules, over the dashboard's tokens and shell."""
    return f"""
[hidden] {{ display: none !important; }}
body.deskpage {{ background: var(--plane); }}
.deskhead {{ display: flex; flex-wrap: wrap; gap: 6px 16px; align-items: center;
  justify-content: space-between; padding: 6px 16px 2px; }}
.headtext {{ flex: 1 1 200px; display: flex; flex-wrap: wrap; align-items: baseline;
  gap: 0 12px; min-width: 0; }}
.deskhead h1 {{ font-size: 1.15rem; }}
.headbtns {{ display: flex; gap: 8px; }}
.headbtns .themebtn {{ min-height: 44px; min-width: 44px; display: inline-flex;
  align-items: center; justify-content: center; text-decoration: none; }}
.desktools {{ display: flex; flex-wrap: wrap; gap: 6px 12px; align-items: center;
  padding: 2px 16px 8px; }}
.deskfind {{ position: relative; flex: 1 1 260px; max-width: 460px; margin: 0; }}
.findlabel, .heresaid {{ position: absolute; width: 1px; height: 1px; overflow: hidden;
  clip: rect(0 0 0 0); white-space: nowrap; }}
.deskfind input {{ box-sizing: border-box; width: 100%; min-height: 44px; padding: 0 12px;
  border-radius: 10px; border: 1px solid var(--border); background: var(--surface);
  color: var(--ink); font: 500 0.9rem var(--font); }}
.deskfind input:focus-visible {{ outline: 2px solid var(--s1); outline-offset: 2px; }}
.findlist, .findnote {{ position: absolute; z-index: 40; left: 0; right: 0; top: 50px;
  margin: 0; background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; box-shadow: 0 10px 30px rgba(0,0,0,.22); }}
.findlist {{ list-style: none; padding: 4px 0; max-height: 60vh; overflow-y: auto; }}
.findlist li {{ min-height: 44px; padding: 5px 12px; cursor: pointer; display: flex;
  flex-direction: column; justify-content: center; }}
.findlist li[aria-selected="true"], .findlist li:hover {{
  background: color-mix(in srgb, var(--ink) 8%, transparent); }}
.findname {{ font-weight: 600; color: var(--ink); font-size: 0.9rem; }}
.findsub {{ color: var(--ink2); font-size: 0.76rem; }}
.findnote {{ padding: 10px 12px; font-size: 0.82rem; color: var(--ink2); }}
.seg, .toolrow {{ display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }}
.segbtn, .toolbtn, .toolsel {{ min-height: 44px; padding: 0 12px; border-radius: 10px;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink);
  font: 500 0.85rem var(--font); cursor: pointer; }}
.segbtn[aria-pressed="true"], .toolbtn[aria-pressed="true"] {{ background: var(--ink);
  color: var(--surface); border-color: var(--ink); }}
.segbtn:disabled, .segbtn[aria-disabled="true"] {{ opacity: 0.45; }}
.segbtn:disabled {{ cursor: not-allowed; }}
.toolnote {{ flex-basis: 100%; margin: 0; font-size: 0.82rem; color: var(--ink2); }}
.toolnote:empty {{ position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); }}
.segbtn:focus-visible, .toolbtn:focus-visible, .eyebtn:focus-visible,
.tabs button:focus-visible, #map:focus-visible, #divider:focus-visible {{
  outline: 2px solid var(--s1); outline-offset: 2px; }}
.menu {{ position: relative; }}
.menu summary {{ list-style: none; display: inline-flex; align-items: center; }}
.menu summary::-webkit-details-marker {{ display: none; }}
.menubody {{ position: absolute; z-index: 30; top: 50px; left: 0; min-width: 250px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 12px;
  padding: 4px 14px; box-shadow: 0 10px 30px rgba(0,0,0,.22); }}
.check {{ display: flex; align-items: center; gap: 10px; min-height: 44px;
  font-size: 0.86rem; cursor: pointer; }}
.check input {{ width: 20px; height: 20px; margin: 0; }}
.check .why {{ color: var(--ink2); font-size: 0.78rem; }}
.deskmapcol {{ display: flex; flex-direction: column; min-width: 0; }}
#map {{ position: relative; overflow: hidden; height: 56vh; min-height: 300px;
  background: var(--plane); touch-action: none; user-select: none;
  -webkit-user-select: none; cursor: grab; outline: none; }}
#map.dragging {{ cursor: grabbing; }}
.gibspane {{ position: absolute; inset: 0; overflow: hidden; pointer-events: none; }}
/* Bottom to top: the compared layer, the base, NASA's reference overlays,
   NASA's ocean and flood tiles, the El Nino composite, each map's own roads
   and names on its side of the divider, the drawn marks, the divider, the
   controls. */
#tiles-b {{ z-index: 1; }}
#tiles {{ z-index: 2; }}
#refs {{ z-index: 3; }}
#enso-tiles {{ z-index: 4; opacity: 0.8; }}
#over, #over-b {{ z-index: 6; }}
.gibsset {{ position: absolute; inset: 0; }}
.gibstile {{ position: absolute; left: 0; top: 0; max-width: none; display: block;
  -webkit-user-drag: none; }}
#overlay {{ position: absolute; inset: 0; width: 100%; height: 100%; overflow: hidden;
  z-index: 7; }}
#overlay path {{ vector-effect: non-scaling-stroke; stroke-linejoin: round;
  stroke-linecap: round; }}
#overlay .coast {{ fill: none; stroke: var(--ink2); stroke-width: 1px; }}
#overlay .area {{ fill-opacity: 0.1; stroke-width: 2px; }}
#overlay .arrow {{ fill: none; stroke-width: 3px; stroke-dasharray: 9 6; }}
#overlay .cone {{ fill: {CONE_COLOURS["fill"]}; fill-opacity: 0.2;
  stroke: {CONE_COLOURS["edge"]}; stroke-width: 1.5px; }}
#overlay .surge {{ fill: {SURGE_COLOUR}; fill-opacity: 0.55; stroke: {SURGE_COLOUR};
  stroke-width: 1px; }}
#overlay .wwcase {{ fill: none; stroke: #000; stroke-opacity: 0.5; stroke-width: 8px; }}
#overlay .ww {{ fill: none; stroke-width: 5px; }}
#overlay .trackcase {{ fill: none; stroke: var(--plane); stroke-opacity: 0.85;
  stroke-width: 5.5px; }}
#overlay .track {{ fill: none; stroke-width: 2.5px; }}
#overlay .forecast {{ fill: none; stroke-width: 2.5px; stroke-dasharray: 7 6; }}
#overlay .investtrack {{ fill: none; stroke: var(--ink2); stroke-width: 1.5px;
  stroke-dasharray: 2 4; }}
#overlay .radii {{ stroke-width: 1.2px; }}
#overlay .r34 {{ fill-opacity: 0.08; }}
#overlay .r50 {{ fill-opacity: 0.12; }}
#overlay .r64 {{ fill-opacity: 0.16; }}
#overlay.close .radii, #overlay.close .cone {{ fill-opacity: 0; }}
#overlay.close .area {{ fill-opacity: 0.04; }}
#overlay .area.lapsed {{ fill-opacity: 0.03; stroke-width: 1.5px; stroke-dasharray: 6 5; }}
#overlay .dl, #overlay .dl2 {{ fill: var(--ink); paint-order: stroke; stroke: var(--plane);
  stroke-width: 3.5px; stroke-linejoin: round; font-family: var(--font); }}
#overlay .dl {{ font-size: 12.5px; font-weight: 650; }}
#overlay .dl2 {{ font-size: 11px; font-weight: 500; }}
#overlay .hit {{ cursor: pointer; }}
#overlay .pad {{ fill: transparent; }}
#overlay .eye {{ stroke: var(--surface); stroke-width: 2px; }}
#overlay .eye.hollow {{ fill: none; stroke-width: 2.5px; }}
#overlay .eyecase {{ fill: none; stroke: var(--plane); stroke-width: 5.5px; }}
#overlay .ring {{ fill: none; stroke: var(--ink); stroke-width: 1.8px;
  stroke-dasharray: 4 3; }}
#overlay .ringcase {{ fill: none; stroke: var(--plane); stroke-width: 4.5px; }}
#overlay .dot {{ fill: var(--surface); stroke-width: 2px; }}
#overlay .place {{ fill: var(--ink2); stroke: var(--surface); stroke-width: 1.5px; }}
#overlay .in34 {{ fill: var(--warning); }}
#overlay .in50 {{ fill: var(--serious); }}
#overlay .in64 {{ fill: var(--critical); }}
#overlay .xcase {{ fill: none; stroke: #000; stroke-opacity: 0.55; stroke-width: 6px; }}
#overlay .x {{ fill: none; stroke-width: 3.5px; }}
#overlay .invest {{ fill: none; stroke: var(--ink); stroke-width: 2px; }}
#overlay .pin {{ fill: var(--ink); stroke: var(--surface); stroke-width: 2.5px; }}
#overlay .pincase {{ fill: none; stroke: var(--ink); stroke-width: 1.5px; }}
.deskpill {{ position: absolute; left: 10px; top: 10px; z-index: 9;
  max-width: min(480px, calc(100% - 76px));
  background: color-mix(in srgb, var(--surface) 90%, transparent);
  color: var(--ink); border: 1px solid var(--border); border-radius: 10px;
  padding: 6px 10px; font-size: 0.76rem; line-height: 1.4; cursor: pointer; }}
.deskpill .muted {{ color: var(--ink2); }}
.pillmore {{ background: none; border: 0; padding: 4px 0 0; min-height: 24px; cursor: pointer;
  color: var(--ink2); font: 600 0.72rem var(--font); text-decoration: underline; }}
.warnpill {{ top: auto; bottom: 30px; cursor: default; display: flex; gap: 10px;
  align-items: center; border-color: var(--warning); }}
.deskzoom {{ position: absolute; right: 10px; top: 10px; z-index: 9; display: flex;
  flex-direction: column; gap: 6px; }}
.deskzoom button {{ width: 44px; height: 44px; border-radius: 10px; cursor: pointer;
  border: 1px solid var(--border); background: var(--surface); color: var(--ink);
  font: 600 1rem var(--font); }}
.deskcredit {{ position: absolute; right: 6px; bottom: 4px; z-index: 9;
  max-width: calc(100% - 12px); font-size: 0.62rem; color: var(--ink2);
  background: color-mix(in srgb, var(--surface) 82%, transparent); padding: 1px 6px;
  border-radius: 6px; }}
#divider {{ position: absolute; top: 0; bottom: 0; left: 50%; width: 44px;
  margin-left: -22px; z-index: 8; cursor: ew-resize; display: flex;
  justify-content: center; }}
#divider::before {{ content: ""; width: 3px; background: var(--surface);
  box-shadow: 0 0 0 1px var(--ink2); }}
#divider .grip {{ position: absolute; top: 50%; width: 28px; height: 44px;
  margin-top: -22px; border-radius: 8px; background: var(--surface);
  border: 1px solid var(--ink2); }}
.deskscrub {{ display: flex; align-items: center; gap: 10px; padding: 4px 16px;
  background: var(--surface); border-top: 1px solid var(--border); font-size: 0.82rem; }}
.deskscrub input {{ flex: 1; min-width: 0; height: 44px; margin: 0; }}
.deskscrub output {{ flex: 0 1 12em; color: var(--ink2); font-variant-numeric: tabular-nums; }}
.desklegend {{ display: flex; flex-wrap: wrap; align-items: center; gap: 0 20px;
  padding: 0 16px; font-size: 0.74rem; color: var(--ink2); background: var(--surface);
  border-top: 1px solid var(--border); }}
.keymore summary {{ min-height: 44px; display: inline-flex; align-items: center;
  cursor: pointer; color: var(--ink); font-weight: 600; }}
.keymore[open] {{ flex-basis: 100%; padding-bottom: 8px; }}
.keymore .keygroup {{ margin: 3px 0; }}
.keygroup {{ display: flex; flex-wrap: wrap; gap: 4px 12px; align-items: center;
  min-height: 32px; }}
.keyhead {{ color: var(--ink); font-weight: 600; }}
.linekey {{ display: inline-block; width: 18px; height: 5px; border-radius: 3px;
  margin-right: 6px; vertical-align: middle; box-shadow: 0 0 0 1px rgba(0,0,0,.3); }}
.linekey.dash {{ -webkit-mask: repeating-linear-gradient(90deg, #000 0 5px, transparent 5px 8px);
  mask: repeating-linear-gradient(90deg, #000 0 5px, transparent 5px 8px); box-shadow: none; }}
.ringkey {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%;
  border: 1.5px dashed var(--ink); }}
.dotkey {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; }}
.desklegend .key {{ gap: 6px; }}
.deskpanel {{ background: var(--surface); padding: 2px 16px 32px;
  border-top: 1px solid var(--border); overflow-wrap: anywhere; min-width: 0; }}
.panelhead {{ font-size: 1rem; margin: 16px 0 6px; display: flex; align-items: center;
  gap: 8px; }}
.subhead {{ font-size: 0.88rem; margin: 12px 0 4px; }}
.deskpanel h4 {{ font-size: 0.86rem; margin: 16px 0 4px; }}
.deskpanel p {{ font-size: 0.84rem; color: var(--ink2); margin: 4px 0 8px; }}
.deskpanel a {{ color: var(--s1); }}
.stormrows, .arearows, .centres, .actions, .wwlist, .notes {{ list-style: none;
  margin: 0; padding: 0; }}
.stormrow, .arearow {{ display: grid; grid-template-columns: 14px minmax(0, 1fr) auto;
  gap: 0 10px; align-items: center; padding: 6px 4px; border-bottom: 1px solid var(--border); }}
.stormrow[aria-current="true"] {{ background: color-mix(in srgb, var(--ink) 6%, transparent);
  border-radius: 8px; }}
.stormtext {{ min-width: 0; }}
.stormname {{ background: none; border: 0; padding: 0; min-height: 44px;
  font: 650 0.95rem var(--font); color: var(--ink); text-align: left; cursor: pointer; }}
.stormfacts {{ font-size: 0.8rem; color: var(--ink); }}
.stormage {{ font-size: 0.74rem; color: var(--ink2); }}
.eyebtn {{ min-width: 52px; min-height: 44px; padding: 0 10px; border-radius: 10px;
  border: 1px solid var(--ink); background: var(--ink); color: var(--surface);
  font: 600 0.84rem var(--font); cursor: pointer; }}
.stormhead {{ display: flex; align-items: center; flex-wrap: wrap; gap: 8px;
  font-size: 1.02rem; margin: 18px 0 4px; }}
.stormhead .eyebtn {{ margin-left: auto; }}
.tabs {{ display: flex; gap: 6px; margin: 8px 0 6px; }}
.tabs button {{ flex: 1; min-height: 44px; border: 1px solid var(--border);
  border-radius: 10px; background: var(--plane); color: var(--ink2);
  font: 600 0.85rem var(--font); cursor: pointer; }}
.tabs button[aria-selected="true"] {{ background: var(--ink); color: var(--surface);
  border-color: var(--ink); }}
dl.facts {{ display: grid; grid-template-columns: minmax(5.5em, max-content) minmax(0, 1fr);
  gap: 6px 12px; font-size: 0.84rem; margin: 8px 0; }}
dl.facts dt {{ color: var(--ink2); }}
dl.facts dd {{ margin: 0; color: var(--ink); }}
.links {{ display: flex; flex-wrap: wrap; gap: 6px 14px; }}
.links a {{ min-height: 32px; display: inline-flex; align-items: center; }}
.wwlist li, .centres li, .actions li, .notes li {{ padding: 7px 0;
  border-bottom: 1px solid var(--border); font-size: 0.84rem; color: var(--ink); }}
.lagnote {{ border-left: 3px solid var(--warning); padding-left: 8px; }}
.here {{ border-bottom: 1px solid var(--border); padding-bottom: 10px; }}
.here .herewhere {{ font-size: 0.8rem; }}
.herebtns {{ display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0 4px; }}
.herestorms {{ list-style: none; margin: 0; padding: 0; }}
.herestorms li {{ padding: 8px 0; border-bottom: 1px solid var(--border);
  font-size: 0.84rem; color: var(--ink); line-height: 1.45; }}
.herestorms li p {{ margin: 2px 0; color: var(--ink); }}
.herestorms .swatch {{ display: inline-block; width: 10px; height: 10px;
  border-radius: 3px; margin-right: 6px; vertical-align: baseline; }}
.here .method {{ font-size: 0.74rem; }}
.herepill {{ top: auto; bottom: 64px; left: 10px; font: 600 0.8rem var(--font);
  min-height: 44px; max-width: calc(100% - 20px); text-align: left; }}
@media (min-width: 900px) {{ .herepill {{ display: none; }} }}
.deskdays {{ position: absolute; left: 10px; bottom: 44px; z-index: 9; display: flex;
  align-items: center; gap: 4px; max-width: calc(100% - 20px); padding: 0 4px;
  background: color-mix(in srgb, var(--surface) 90%, transparent);
  border: 1px solid var(--border); border-radius: 10px; }}
.deskdays button {{ width: 44px; height: 44px; border: 0; background: none; cursor: pointer;
  color: var(--ink); font-size: 0.9rem; border-radius: 8px; }}
.deskdays button:disabled {{ color: var(--ink2); opacity: 0.45; cursor: default; }}
.deskdays span {{ font: 600 0.8rem var(--font); color: var(--ink); padding: 0 4px; }}
#days:not([hidden]) ~ #herego {{ bottom: 96px; }}
#overlay .town {{ fill: var(--ink); stroke: var(--plane); stroke-width: 1.2px; }}
.deskpanel .tablewrap {{ max-width: 100%; }}
/* The search shares the header's line, so the page's one-line description
   gives way to it rather than pushing the map down. */
@media (max-width: 1399px) {{
  .deskhead .long {{ display: none; }}
}}
/* A phone keeps the map near the top: each row of controls scrolls sideways
   rather than wrapping. */
@media (max-width: 640px) {{
  .deskfind {{ order: 3; flex-basis: 100%; max-width: none; }}
  .desktools {{ flex-wrap: nowrap; flex-direction: column; align-items: stretch; }}
  .seg, .toolrow {{ flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none;
    padding-bottom: 2px; }}
  .seg > *, .toolrow > * {{ flex: 0 0 auto; }}
  .menubody {{ position: fixed; top: auto; left: 16px; right: 16px; min-width: 0; }}
}}
@media (min-width: 900px) {{
  body.deskpage {{ height: 100vh; height: 100dvh; display: flex; flex-direction: column;
    overflow: hidden; }}
  .desk {{ flex: 1; min-height: 0; display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(320px, 380px); }}
  .deskmapcol {{ min-height: 0; }}
  #map {{ flex: 1; height: auto; min-height: 0; }}
  .desklegend {{ max-height: 30vh; overflow-y: auto; }}
  .deskpanel {{ overflow-y: auto; border-top: 0; border-left: 1px solid var(--border); }}
}}
"""


# The two pages the one page is written as: storms.html on the storms and
# today's imagery, map.html on the street map under El Nino's rainfall. Each
# names the other in its header, and carries the view across.
FOCUS = {
    "world": {"title": "El Niño map",
              "sub": ("El Niño's measured effects on street maps, satellite and Google, "
                      "anywhere on Earth."),
              "other": ("storms.html", "Storm desk"), "first": "streets"},
    "storms": {"title": "Storm desk",
               "sub": ("Live tropical cyclones on live satellite imagery, with what their "
                       "warning centres have issued."),
               "other": ("map.html", "El Niño map"), "first": "geocolor"},
}


def page(state, focus: str = "storms") -> str:
    """``storms.html``: the storm desk, one file. ``focus`` "world" writes the
    same page as ``map.html``, opened on the map's El Nino view."""
    words = FOCUS[focus]
    # Imported here rather than at the top: the dashboard links to this page,
    # and a top-level import of its shell would close a circle.
    from .dashboard import _css as shell_css
    data = payload(state)
    hues = _hues(data["storms"])
    for area in data["outlook"]:
        area["level"] = _level(area)
    data["style"] = {"hues": hues, "products": dict(PRODUCT_COLOURS),
                     "outlook": dict(OUTLOOK_COLOURS), "surge": SURGE_COLOUR,
                     "cone": dict(CONE_COLOURS)}
    # The gazetteer the search reads, in the atlas's own rows. It is the page's,
    # not storms.json's: it is the same on every run.
    from .atlasview import _places_payload
    data["places"] = _places_payload()
    # The street, satellite and terrain maps are the page's, as the gazetteer
    # is: storms.json keeps the layers it has always had.
    data["layers"] += [_plain_layer(layer) for layer in worldmap.LAYERS]
    data["enso"] = worldmap.payload(state)
    data["then"] = thennow.payload(state)
    data["focus"] = focus
    enso = thennow.enter_button() + worldmap.controls(focus, data["enso"]["now"],
                                                        data["enso"]["next"])
    now = worldmap.section(state)
    other, other_name = words["other"]
    # Every "<" escaped, so nothing in a name or a centre's text can close the
    # script element or open a comment inside it.
    raw = json.dumps(data, separators=(",", ":")).replace("<", "\\u003c")
    built = _time(data["built"]) if data["built"] else "unknown"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{live.head(getattr(state, "run_at", None))}
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='14' fill='%232a78d6'/%3E%3Ccircle cx='16' cy='16' r='4.5' fill='%23fcfcfb'/%3E%3C/svg%3E">
<title>{esc(words["title"])}</title>
<style>{shell_css()}{fields.ramp_css()}{css()}{worldmap.css()}{thennow.css()}</style>
</head>
<body class="deskpage">
<header class="deskhead">
<div class="headtext"><h1>{esc(words["title"])}</h1>
<p class="sub"><span class="long">{esc(words["sub"])} </span>Built <span id="built">{built}</span>.</p></div>
{_find()}
<div class="headbtns"><a class="themebtn" data-carry="{other}" href="{other}">{esc(other_name)}</a>
<a class="themebtn" href="dashboard.html">Dashboard</a>
<button type="button" class="themebtn" id="theme">Dark</button></div>
</header>
{_toolbar(first=words["first"], controls=enso)}
<main class="desk">
<div class="deskmapcol">
{_map()}
{_scrubber()}
{thennow.bar(data["then"])}
{_legend(data, hues)}
</div>
<aside class="deskpanel" id="panel" aria-label="Storms, outlook and what to do">{_panel(data, hues, focus, now)}</aside>
<p class="heresaid" id="here-said" role="status"></p>
</main>
<script id="desk-data" type="application/json">{raw}</script>
<script>{live.SCRIPT}</script>
<script>{script()}</script>
</body>
</html>"""


def script() -> str:
    """The page's script: the desk's, with the map's and the then-and-now
    view's taken in at their markers."""
    return (_JS.replace("  /*WORLDMAP*/\n", worldmap._JS)
            .replace("  /*THENNOW*/\n", thennow._JS))


_JS = r"""
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("desk-data").textContent);
  function $(id) { return document.getElementById(id); }
  var map = $("map"), svgEl = $("overlay"), coastG = $("coast"), geoG = $("geo"), marksG = $("marks");
  var divider = $("divider"), framePill = $("frame"), statusPill = $("status");
  var scrub = $("scrub"), scrubRead = $("scrub-read");
  var TILE = 256, MINZ = 1, MAXZ = 13, UNIT = 1048576, HOUR = 3600000, NM = 1.852, ASIDE = 900000, SETTLE = 2700000;
  var EARTH_KM = 6378.137, GEO_KM = 42164.0, CIRCUMFERENCE = 40075.017;
  var THRESHOLDS = ["34", "50", "64"];
  var ORDER = ["Tropical Storm Watch", "Tropical Storm Warning", "Hurricane Watch", "Hurricane Warning"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  var LAYERS = {}, STORMS = [], BYID = {}, DOM = {};
  var S = {
    x: 0.5, y: 0.45, z: 3, w: 1, h: 1,
    layer: "geocolor", second: "infrared", compare: false, split: 0.5,
    loop: false, loopWanted: false, frame: 0, scrub: 0, selected: null, inView: {},
    show: {}, refs: {}, pin: null, day: null, dayState: "idle", dayStepped: false,
    imagery: navigator.onLine === false ? "offline" : "pending"
  };

  // ---- small things -------------------------------------------------------
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function wrap(lon) { return ((lon + 180) % 360 + 360) % 360 - 180; }
  function rad(d) { return d * Math.PI / 180; }
  function deg(r) { return r * 180 / Math.PI; }
  function mx(lon) { return (lon + 180) / 360; }
  function my(lat) {
    var p = rad(clamp(lat, -85.0511, 85.0511));
    return (1 - Math.log(Math.tan(p) + 1 / Math.cos(p)) / Math.PI) / 2;
  }
  function lonOf(x) { return x * 360 - 180; }
  function latOf(y) { return deg(Math.atan(Math.sinh(Math.PI * (1 - 2 * y)))); }
  // A name a table has of its own: words, and not one every object inherits
  // ("constructor").
  function own(table, key) { return typeof key === "string" && Object.prototype.hasOwnProperty.call(table, key); }
  function finite(x) { return typeof x === "number" && isFinite(x); }
  function world() { return TILE * Math.pow(2, S.z); }
  function km(lon1, lat1, lon2, lat2) {
    var p1 = rad(lat1), p2 = rad(lat2), dp = p2 - p1, dl = rad(lon2 - lon1);
    var a = Math.sin(dp / 2) * Math.sin(dp / 2) +
            Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) * Math.sin(dl / 2);
    return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(a)));
  }
  function bearing(lon1, lat1, lon2, lat2) {
    var dl = rad(lon2 - lon1), p1 = rad(lat1), p2 = rad(lat2);
    var y = Math.sin(dl) * Math.cos(p2);
    var x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
    return (deg(Math.atan2(y, x)) + 360) % 360;
  }
  // Where a heading and a distance lead; the longitude is left unwrapped so a
  // storm's rings stay in the storm's own frame across the date line.
  function dest(lon, lat, heading, dist) {
    var d = dist / 6371, p1 = rad(lat), t = rad(heading);
    var p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(t));
    var dl = Math.atan2(Math.sin(t) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
    return [lon + deg(dl), deg(p2)];
  }
  function zenith(lon, lat, sub) {
    var g = Math.acos(clamp(Math.cos(rad(lat)) * Math.cos(rad(wrap(lon - sub))), -1, 1));
    var below = Math.cos(g) - EARTH_KM / GEO_KM;
    return below <= 0 ? null : deg(Math.atan2(Math.sin(g), below));
  }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function utc(ms) {
    var d = new Date(ms);
    return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + " " +
           pad2(d.getUTCHours()) + ":" + pad2(d.getUTCMinutes()) + " UTC";
  }
  function isoZ(ms) { return new Date(ms).toISOString().slice(0, 19) + "Z"; }
  function dayZ(ms) { return new Date(ms).toISOString().slice(0, 10); }
  function span(min) {
    if (min < 60) return min + " min";
    var h = Math.floor(min / 60), m = min % 60;
    if (h < 48) return h + " h" + (m ? " " + m + " min" : "");
    return Math.round(h / 24) + " days";
  }
  function ago(ms) {
    var m = Math.round((Date.now() - ms) / 60000);
    return m < 0 ? "in " + span(-m) : span(m) + " ago";
  }
  function pct(v) { return v == null ? "not given" : v + "%"; }
  // A formation alert holds until the time JTWC said it would reissue,
  // upgrade or cancel it by; past that, with nothing newer read, it ran out,
  // and which of the three JTWC did is not known here. A map label is short.
  function lapsed(until) { var t = Date.parse(until || ""); return !isNaN(t) && t <= Date.now(); }
  function alertWords(until, short) {
    var t = Date.parse(until || "");
    if (isNaN(t)) return "formation alert in effect";
    if (t > Date.now()) return "formation alert until " + utc(t);
    return "formation alert ran to " + utc(t) + (short ? "" : "; nothing newer read");
  }
  function alertHtml(until) {
    return until ? '<span data-until="' + esc(until) + '">' + esc(alertWords(until)) + "</span>" : esc(alertWords(until));
  }
  var lapsedNow = "";
  function ages() {
    var list = document.querySelectorAll("time[data-age]");
    for (var i = 0; i < list.length; i++) {
      var ms = Date.parse(list[i].getAttribute("datetime"));
      if (!isNaN(ms)) list[i].textContent = list[i].getAttribute("data-age") + " (" + ago(ms) + ")";
    }
    // An alert that runs out while the page is open is reworded, and its box redrawn.
    var spans = document.querySelectorAll("[data-until]");
    for (var j = 0; j < spans.length; j++) spans[j].textContent = alertWords(spans[j].getAttribute("data-until"));
    var out = D.outlook.filter(function (a) { return a.alert && a.formation && lapsed(a.formation.until); })
                       .map(function (a) { return a.key; }).join(" ");
    if (out !== lapsedNow) { lapsedNow = out; dirty(); }
  }

  // ---- the storms ---------------------------------------------------------
  function prepare() {
    bands();
    LAYERS = {};
    D.layers.forEach(function (l) { LAYERS[l.id] = l; });
    STORMS = []; BYID = {};
    D.storms.forEach(function (s) {
      var nodes = [];
      s.path.forEach(function (p) {
        var t = Date.parse(p.t);
        if (!isNaN(t)) nodes.push({t: t, lon: p.lon, lat: p.lat, wind: p.wind,
                                   radii: p.radii || {}, label: p.label, category: p.category});
      });
      // The advisory's own position replaces the path's at the advisory time.
      var fix = s.advisory_fix;
      if (fix) {
        var at = Date.parse(fix.t);
        for (var i = 0; i < nodes.length; i++) {
          if (nodes[i].t === at) { nodes[i].lon = fix.lon; nodes[i].lat = fix.lat; break; }
          if (nodes[i].t > at && i > 0) {
            nodes.splice(i, 0, {t: at, lon: fix.lon, lat: fix.lat, wind: fix.wind,
                                radii: nodes[i - 1].radii, label: nodes[i - 1].label,
                                category: nodes[i - 1].category});
            break;
          }
        }
      }
      var st = {d: s, id: s.id, hue: (D.style.hues || {})[s.id] || "var(--ink2)",
                nodes: nodes, x0: mx(s.lon)};
      STORMS.push(st); BYID[s.id] = st;
    });
  }
  // The centre and radii at a time, straight between the nodes either side;
  // nothing before the first node or after the last forecast point.
  function centreAt(st, T) {
    var n = st.nodes;
    if (!n.length || T < n[0].t || T > n[n.length - 1].t) return null;
    var i = 0;
    while (i < n.length - 2 && n[i + 1].t < T) i++;
    var a = n[i], b = n[Math.min(i + 1, n.length - 1)];
    var f = b.t > a.t ? clamp((T - a.t) / (b.t - a.t), 0, 1) : 0;
    var radii = {};
    THRESHOLDS.forEach(function (k) {
      var ra = a.radii[k], rb = b.radii[k];
      radii[k] = ra && rb ? ra.map(function (v, q) { return v + (rb[q] - v) * f; })
               : (f === 0 ? ra || null : (f === 1 ? rb || null : null));
    });
    var near = f < 0.5 ? a : b;
    return {t: T, lon: a.lon + (b.lon - a.lon) * f, lat: a.lat + (b.lat - a.lat) * f,
            wind: a.wind != null && b.wind != null ? a.wind + (b.wind - a.wind) * f : near.wind,
            radii: radii, label: near.label, category: near.category};
  }
  function inside(c, lon, lat) {
    var d = km(c.lon, c.lat, lon, lat), q = Math.floor(bearing(c.lon, c.lat, lon, lat) / 90) % 4;
    var found = 0;
    THRESHOLDS.forEach(function (t) { var r = c.radii[t]; if (r && d <= r[q] * NM) found = +t; });
    return found;
  }

  // ---- imagery: which layer, which frames ---------------------------------
  function source(id, sat) {
    var l = LAYERS[id];
    if (!l) return null;
    if (l.stack) return l.stack.indexOf(sat) >= 0 ?
      {name: sat, tms: l.tms, zoom: l.zoom, ext: l.format, step: l.step, sat: null, layer: l, note: ""} : null;
    if (l.global) return {name: l.global, tms: l.tms, zoom: l.zoom, ext: l.format, step: l.step,
                          sat: null, layer: l, note: ""};
    // A street map has no imager and no frames: a storm over it is drawn at the clock's time.
    if (!sat || !l.satellites) return null;
    var name = l.satellites[sat];
    if (name) return {name: name, tms: l.tms, zoom: l.zoom, ext: l.format, step: l.step,
                      sat: sat, layer: l, note: ""};
    var ir = LAYERS.infrared;   // GIBS carries no GeoColor from Himawari
    return {name: ir.satellites[sat], tms: ir.tms, zoom: ir.zoom, ext: ir.format, step: ir.step,
            sat: sat, layer: ir, note: "GIBS has no " + sat + " " + l.name + ": infrared instead"};
  }
  function timed(s) { return !!(s && s.step && s.step.indexOf("D") < 0); }
  function framesOf(s) { var d = s && DOM[s.name]; return d && d.frames.length ? d.frames : null; }
  function frameOf(s, i) { var f = framesOf(s); return f ? f[Math.min(i, f.length - 1)] : null; }
  // The time a storm is drawn for: the frame on screen from the imager that
  // sees it, or the clock where there is no such frame.
  function base(st) {
    var s = source(S.layer, st.d.view && st.d.view.satellite);
    if (timed(s)) {
      ask(s);
      var f = frameOf(s, S.frame);
      if (f) return {t: f.t, image: true};
    }
    return {t: Date.now(), image: false};
  }
  function when(st) { return base(st).t + S.scrub * HOUR; }
  function duration(text) {
    var m = /^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/.exec(text || "");
    if (!m) return 0;
    return ((((+m[1] || 0) * 24 + (+m[2] || 0)) * 60 + (+m[3] || 0)) * 60 + (+m[4] || 0)) * 1000;
  }
  function stamp(text) { return Date.parse(/^\d{4}-\d\d-\d\d$/.test(text) ? text + "T00:00:00Z" : text); }
  // GIBS answers with start/end/period ranges; the frames are counted back
  // from each range's end, which is always a frame that exists. A frame
  // younger than SETTLE can still be part made (GOES GeoColor half white at
  // 35 minutes, 25 Sep 2026), so the newest frame shown is the newest older
  // than that, where GIBS lists one.
  function parseDomain(text, daily) {
    var m = /<Domain>([^<]*)<\/Domain>/.exec(text), times = [];
    if (!m) return [];
    m[1].split(",").forEach(function (part) {
      var bits = part.trim().split("/");
      if (bits.length === 3) {
        var a = stamp(bits[0]), b = stamp(bits[1]), step = duration(bits[2]);
        if (isNaN(a) || isNaN(b) || !step) return;
        for (var t = b, n = 0; t >= a && n < 400; t -= step, n++) times.push(t);
      } else if (bits[0]) {
        var one = stamp(bits[0]);
        if (!isNaN(one)) times.push(one);
      }
    });
    times.sort(function (p, q) { return q - p; });
    var settled = times.filter(function (t) { return Date.now() - t >= SETTLE; });
    if (!daily && settled.length) times = settled;
    if (!times.length) return [];
    var latest = times[0], keep = [];
    times.forEach(function (t) {
      if (keep.length && keep[keep.length - 1].t === t) return;
      if (daily ? !keep.length : latest - t <= 2 * HOUR) keep.push({t: t, key: daily ? dayZ(t) : isoZ(t)});
    });
    return keep;
  }
  // One question goes out first; the rest wait for its answer, so a page
  // that cannot reach GIBS makes one failed request, not one per imager.
  var probing = false;
  function ask(s) {
    if (!s || !s.step || S.imagery === "offline" || S.imagery === "unreachable") return;
    if (S.imagery === "pending" && probing) return;
    var known = DOM[s.name];
    if (known && !known.stale) return;
    if (known) known.stale = false; else DOM[s.name] = {frames: [], stale: false, failed: false, unanswered: false, aside: {}};
    if (S.imagery === "pending") probing = true;
    var daily = s.step.indexOf("D") >= 0, now = Date.now();
    var back = daily ? 240 : (s.step === "PT10M" ? 6 : 24), fmt = daily ? dayZ : isoZ;
    var url = D.gibs.domains.replace("{layer}", s.name).replace("{tms}", s.tms)
      .replace("{start}", fmt(now - back * HOUR)).replace("{end}", fmt(now + HOUR));
    fetch(url).then(function (r) {
      if (!r.ok) throw new Error("GIBS " + r.status);
      return r.text();
    }).then(function (text) {
      var aside = DOM[s.name].aside, since = Date.now() - ASIDE;
      var frames = parseDomain(text, daily).filter(function (f) { return !(aside[f.key] > since); });
      if (frames.length) DOM[s.name].frames = frames;
      DOM[s.name].failed = !frames.length && !DOM[s.name].frames.length;
      DOM[s.name].unanswered = false;
      S.imagery = "ok";
      probing = false;
      dirty();
    }).catch(function () {
      // No answer is not "no frames": the ten-minute refresh asks again.
      DOM[s.name].unanswered = !DOM[s.name].frames.length;
      if (S.imagery !== "ok") S.imagery = "unreachable";
      probing = false;
      dirty();
    });
  }
  // GIBS asked again from the start, with the page's opening question: under
  // a street map with only NASA's overlays on, no other question would go.
  function askGibsAgain() {
    DOM = {}; S.imagery = "pending"; probing = false;
    ask(source("geocolor", "GOES-East"));
  }
  function retry() { statusPill.innerHTML = ""; askGibsAgain(); forgetMaps(); if (S.then) thenRetry(); dirty(); }

  // ---- tiles ----------------------------------------------------------------
  function tileUrl(s, key, z, row, col) {
    return (key ? D.gibs.tiles : D.gibs.static).replace("{layer}", s.name).replace("{time}", key || "")
      .replace("{tms}", s.tms).replace("{z}", z).replace("{y}", row).replace("{x}", col)
      .replace("{ext}", s.ext);
  }
  // Street maps: XYZ tiles from a template, never deeper than the layer goes.
  var NODATA = {}, MAPS = {};
  function xyzUrl(template, z, x, y) {
    return template.replace("{z}", z).replace("{y}", y).replace("{x}", x);
  }
  // Past its coverage Esri answers 200 with a grey "Map data not yet
  // available" JPEG (open Pacific from zoom 16, Amazon imagery from 18, Lima
  // from 20; 28 Sep 2026): 240 of 256 samples exactly 204,204,204.
  function placeholder(px) {
    var grey = 0;
    for (var i = 0; i + 3 < px.length; i += 4) {
      if (px[i + 3] >= 250 && Math.abs(px[i] - 204) <= 3 && Math.abs(px[i + 1] - 204) <= 3 &&
          Math.abs(px[i + 2] - 204) <= 3) grey++;
    }
    return grey >= 200;
  }
  // The tile to draw for one asked for: itself, or where Esri has answered
  // with its placeholder, the nearest coarser tile it has not. A placeholder
  // at one level means no level under it has imagery either, so the
  // shallowest level known to have none decides, and zooming further in
  // asks for nothing already known to be missing.
  function present(name, z, c, r) {
    var at = {z: z, c: c, r: r};
    for (; z > 0; z--, c = Math.floor(c / 2), r = Math.floor(r / 2)) {
      var m = Math.pow(2, z);
      if (NODATA[name + "/" + z + "/" + (((c % m) + m) % m) + "/" + r]) at = {z: z - 1, c: Math.floor(c / 2), r: Math.floor(r / 2)};
    }
    return at;
  }
  function xyzCells(l, template, name) {
    var out = [], seen = {};
    var gz = clamp(Math.round(S.z), 0, l.zoom), n = Math.pow(2, gz), o = origin(), size = o.W / n;
    var c0 = Math.floor(-o.left / size), c1 = Math.floor((S.w - o.left - 0.01) / size);
    var r0 = Math.max(0, Math.floor(-o.top / size)), r1 = Math.min(n - 1, Math.floor((S.h - o.top - 0.01) / size));
    for (var r = r0; r <= r1; r++) for (var c = c0; c <= c1; c++) {
      var t = present(name, gz, c, r), m = Math.pow(2, t.z), id = name + "/" + t.z + "/" + t.c + "/" + t.r;
      if (seen[id]) continue;
      seen[id] = true;
      out.push({id: id, z: t.z, c: t.c, r: t.r, clip: "", name: name, key: null, map: l.id,
                url: xyzUrl(template, t.z, ((t.c % m) + m) % m, t.r), check: false, grey: !!l.grey,
                credit: l.credit, nasa: false, wb: l.wayback || 0});
    }
    return out;
  }
  function maxZoom() { var l = LAYERS[S.layer]; return l && l.kind === "map" ? l.zoom : MAXZ; }
  function servedOnly(protocol) { return /^https?:$/.test(protocol); }
  // A then-and-now side (thennow.py) names its places while Esri's names are over it.
  function labelled(id) { var l = LAYERS[id]; return !!(l && (l.then ? !!l.over : l.kind === "map")); }
  function labelledBase() { return labelled(S.layer); }
  // Whether the map under a point on the screen names its own places: with
  // two layers compared, the second is the one right of the divider.
  function namedAt(x) { return labelled(S.compare && x >= S.split * S.w ? S.second : S.layer); }
  function mapDown(id) { var m = MAPS[id]; return !!(m && m.failed && !m.ok); }
  // NASA's tiles are counted by layer and frame: GIBS can list a frame and not
  // send its tiles. A failure that set its frame aside is not counted, as the
  // frame before it is drawn instead.
  var GOT = {};
  function gotKey(name, key) { return name + "/" + (key || "-"); }
  function tallyNasa(img, what) {
    var k = gotKey(img._name, img._key), g = GOT[k] || (GOT[k] = {ok: 0, failed: 0});
    g[what]++;
  }
  // Whether none of the tiles of a source's frame on show arrived, and some failed.
  function tilesDown(s) {
    var l = s.layer || {}, f = s.step && !l.stack && !l.time && !l.then ? frameOf(s, S.frame) : null;
    var g = GOT[gotKey(s.name, l.then ? l.time : l.stack ? S.day : l.time || (f && f.key))];
    return !!(g && g.failed && !g.ok);
  }
  // Every NASA source of one side's layer in view has had its tiles fail.
  function nasaDown(view) {
    var any = false;
    for (var k in view || {}) {
      var s = view[k];
      if (!s || !s.name || s.map) continue;
      if (!tilesDown(s)) return false;
      any = true;
    }
    return any;
  }
  function tally(img, what) {
    var m = MAPS[img._map] || (MAPS[img._map] = {ok: 0, failed: 0});
    m[what]++;
  }
  // A map tile that did not arrive is asked for again 30 s after its address
  // first failed, and after twice the wait each time since, up to 16 minutes:
  // one lost answer from a map's server does not leave a hole for the visit.
  var AGAIN = {};
  function againIn(fails) { return Math.min(30000 * Math.pow(2, Math.max(0, fails - 1)), 960000); }
  function askAgain(img, now) { return !!(img._map && img._failed && now - img._failedAt >= againIn(AGAIN[img._url] || 1)); }
  // Once the network is back or Retry is pressed, every tile that failed, a
  // map's or NASA's, is asked for again at once, and the waits start over.
  function forgetMaps() {
    MAPS = {};
    AGAIN = {};
    GOT = {};
    [panes.a, panes.b, panes.o, panes.ob, panes.r, panes.e].forEach(function (pane) {
      for (var k in pane.sets) {
        var imgs = pane.sets[k].imgs;
        for (var id in imgs) if (imgs[id]._failed) { imgs[id].remove(); delete imgs[id]; }
      }
    });
  }
  function TileSet(parent, ref) {
    this.el = document.createElement("div");
    this.el.className = "gibsset";
    parent.appendChild(this.el);
    this.imgs = {};
    this.ref = !!ref;
  }
  function origin() { var W = world(); return {W: W, left: S.w / 2 - S.x * W, top: S.h / 2 - S.y * W}; }
  function place(img, o) {
    var size = o.W / Math.pow(2, img._z);
    img.style.transform = "translate(" + (o.left + img._c * size).toFixed(1) + "px," +
                          (o.top + img._r * size).toFixed(1) + "px)";
    img.style.width = img.style.height = (size + 0.6).toFixed(1) + "px";
  }
  function inside_view(img, o) {
    var size = o.W / Math.pow(2, img._z), x = o.left + img._c * size, y = o.top + img._r * size;
    return x < S.w && y < S.h && x + size > 0 && y + size > 0;
  }
  // GIBS sends its tiles with CORS, so a tile can be looked at: 16 by 16
  // samples, the share that is solid black and, of the opaque ones, the share
  // that is pure white.
  var sampler = null;
  // A tile as 16 by 16 RGBA samples; null where it cannot be read.
  function pixels(img) {
    try {
      sampler = sampler || document.createElement("canvas");
      sampler.width = sampler.height = 16;
      var cx = sampler.getContext("2d", {willReadFrequently: true});
      cx.clearRect(0, 0, 16, 16);
      cx.drawImage(img, 0, 0, 16, 16);
      return cx.getImageData(0, 0, 16, 16).data;
    } catch (err) { return null; }
  }
  function sample(img) {
    var px = pixels(img), black = 0, white = 0, opaque = 0;
    if (!px) return null;
    for (var i = 0; i < px.length; i += 4) {
      if (px[i + 3] < 250) continue;
      opaque++;
      if (Math.max(px[i], px[i + 1], px[i + 2]) <= 8) black++;
      if (Math.min(px[i], px[i + 1], px[i + 2]) >= 252) white++;
    }
    return {black: black / 256, white: opaque ? white / opaque : 0};
  }
  // GIBS lists a frame before all its tiles are made. A tile of an unfinished
  // frame is missing (Himawari, 20 minutes on), or is served with white where
  // the data will go (GOES, 45 minutes on; real cloud tops sample no pure
  // white at all). Either sets the frame aside if it is one of the imager's
  // three newest, and every tile of that imager falls back to the frame
  // before it, so one imager never shows two times at once. No more than
  // three frames an imager are set aside in a quarter of an hour, so a
  // network that fails every tile costs three requests a tile, not thirteen.
  function setAside(img) {
    var d = DOM[img._name], recent = 0, since = Date.now() - ASIDE;
    if (!d || !img._key) return;
    for (var k in d.aside) if (d.aside[k] > since) recent++;
    if (recent >= 3) return;
    for (var i = 0; i < Math.min(3, d.frames.length - 1); i++) {
      if (d.frames[i].key !== img._key) continue;
      d.aside[img._key] = Date.now();
      d.frames.splice(i, 1);
      dirty();
      return true;
    }
    return false;
  }
  function tileLoaded() {
    // A class NASA paints too strongly for an overlay is faded, and the tile drawn again.
    if (this._faint && !this._faded && fadeTile(this)) return;
    if (this._map) tally(this, "ok"); else tallyNasa(this, "ok");
    // Esri's placeholder is an answer that it has nothing finer here: the
    // tile is hidden and the next draw asks for the one above it. Only the
    // tiles change, so nothing else is rebuilt.
    if (this._grey) {
      var px = pixels(this);
      if (px && placeholder(px)) {
        var m = Math.pow(2, this._z);
        this.style.visibility = "hidden";
        NODATA[this._name + "/" + this._z + "/" + (((this._c % m) + m) % m) + "/" + this._r] = true;
        requestRender();
        return;
      }
    }
    var got = this._ref || this._check ? sample(this) : null;
    // Where a reference layer has nothing, GIBS can answer with an opaque
    // black square (the same 921-byte PNG everywhere; coastlines at 7/58/24).
    if (got && this._ref && got.black === 1) this.style.visibility = "hidden";
    if (got && this._check && got.white > 0.2) { this.style.visibility = "hidden"; setAside(this); }
    requestRender();
  }
  function tileFailed() {
    this.style.visibility = "hidden";
    this._failed = true;
    // A tile of Esri's archive past zoom 13 is asked after in its release's
    // tilemap first (thennow.py): if Esri has none there, the coarser is drawn.
    if (this._wb && this._z > 13 && !this._asked) { wbAsk(this); return; }
    if (this._map) {
      this._failedAt = Date.now(); tally(this, "failed");
      AGAIN[this._url] = (AGAIN[this._url] || 0) + 1;
      setTimeout(requestRender, againIn(AGAIN[this._url]) + 100);
      requestRender();
    } else if (!setAside(this)) {
      tallyNasa(this, "failed");
      requestRender();
    }
  }
  TileSet.prototype.draw = function (cells) {
    var o = origin(), want = {}, ready = true;
    for (var i = 0; i < cells.length; i++) {
      var cell = cells[i], img = this.imgs[cell.id];
      if (img && askAgain(img, Date.now())) { img.remove(); delete this.imgs[cell.id]; img = null; }
      if (!img) {
        img = document.createElement("img");
        img.alt = ""; img.draggable = false; img.decoding = "async"; img.className = "gibstile";
        img._z = cell.z; img._c = cell.c; img._r = cell.r; img._name = cell.name; img._key = cell.key;
        if (cell.clip) img.style.clipPath = cell.clip;
        img.crossOrigin = "anonymous"; img._ref = this.ref; img._check = cell.check;
        img._grey = cell.grey; img._map = cell.map; img._faint = cell.faint; img._url = cell.url;
        img._credit = cell.credit; img._nasa = !!cell.nasa; img._cut = cell.cut || [0, 0]; img._wb = cell.wb || 0;
        img.onload = tileLoaded; img.onerror = tileFailed;
        img.src = cell.url;
        this.el.appendChild(img);
        this.imgs[cell.id] = img;
      }
      // Finer tiles over coarser ones standing in beneath them.
      img.style.zIndex = 10 + cell.z;
      want[cell.id] = true;
      if (!img.complete) ready = false;
      place(img, o);
    }
    // Tiles from the last zoom or layer stay under the new ones until those arrive.
    for (var k in this.imgs) {
      if (want[k]) continue;
      var old = this.imgs[k];
      if (!ready && old.complete && old.naturalWidth && inside_view(old, o)) { old.style.zIndex = 1; place(old, o); }
      else { old.remove(); delete this.imgs[k]; }
    }
  };
  TileSet.prototype.move = function () {
    var o = origin();
    for (var k in this.imgs) {
      var img = this.imgs[k];
      if (inside_view(img, o)) place(img, o); else { img.remove(); delete this.imgs[k]; }
    }
  };
  TileSet.prototype.drop = function () { this.el.remove(); this.imgs = {}; };
  var panes = {a: {el: $("tiles"), sets: {}}, b: {el: $("tiles-b"), sets: {}}, r: {el: $("refs"), sets: {}},
               o: {el: $("over"), sets: {}}, ob: {el: $("over-b"), sets: {}}, e: {el: $("enso-tiles"), sets: {}}};
  function drawPane(pane, specs, moving) {
    var keep = {};
    specs.forEach(function (sp) {
      var set = pane.sets[sp.key] || (pane.sets[sp.key] = new TileSet(pane.el, pane === panes.r));
      if (moving) set.move(); else set.draw(sp.cells);
      set.el.style.visibility = sp.visible ? "" : "hidden";
      set.el.style.zIndex = sp.z || 0;
      keep[sp.key] = true;
    });
    for (var k in pane.sets) if (!keep[k]) { pane.sets[k].drop(); delete pane.sets[k]; }
  }
  // Each imager keeps the longitudes nearer its sub-point than any other's,
  // which it sees most nearly overhead. Geostationary sub-points lie on the
  // equator, so the borders are the meridians halfway between them, and a
  // tile across a border is drawn from both imagers, each clipped to its side.
  var BANDS = [];
  function bands() {
    var sats = D.satellites.slice().sort(function (a, b) { return a.lon - b.lon; }), n = sats.length;
    BANDS = sats.map(function (s, i) {
      var west = sats[(i + n - 1) % n], east = sats[(i + 1) % n];
      var toW = n > 1 ? ((s.lon - west.lon) % 360 + 360) % 360 : 360;
      var toE = n > 1 ? ((east.lon - s.lon) % 360 + 360) % 360 : 360;
      return {name: s.name, lon: s.lon, w: s.lon - toW / 2, e: s.lon + toE / 2};
    });
  }
  // The imagers owning parts of longitudes lo..hi, in that frame, and whether
  // each sees any of its part within 70 degrees of zenith between the
  // latitudes south..north.
  function owners(lo, hi, south, north) {
    var out = [], lat = south > 0 ? south : (north < 0 ? north : 0);
    BANDS.forEach(function (b) {
      for (var k = Math.ceil((lo - b.e) / 360); b.w + 360 * k < hi; k++) {
        var w = Math.max(lo, b.w + 360 * k), e = Math.min(hi, b.e + 360 * k);
        if (e - w < 1e-9) continue;
        var z = zenith(clamp(b.lon + 360 * k, w, e), lat, b.lon);
        out.push({name: b.name, w: b.w + 360 * k, e: b.e + 360 * k, seen: z !== null && z <= 70});
      }
    });
    return out;
  }
  // The tiles of one layer in view, each at the frame GIBS lists for its imager.
  function cells(id, frame) {
    var l = LAYERS[id], out = [], used = {}, seen = {};
    if (!l) return {cells: out, used: used};
    if (l.kind === "map") {
      // The coarsest zoom drawn where Esri had nothing finer, for the pill to say.
      var list = l.tiles ? xyzCells(l, l.tiles, l.nodata || l.id) : [], wanted = clamp(Math.round(S.z), 0, l.zoom), coarser = null;
      list.forEach(function (t) { if (t.z < wanted && (coarser === null || t.z < coarser)) coarser = t.z; });
      used[l.id] = {name: l.id, layer: l, map: true, coarser: coarser};
      return {cells: list, used: used};
    }
    var gz = clamp(Math.round(S.z), 0, l.zoom), n = Math.pow(2, gz), o = origin(), size = o.W / n;
    var c0 = Math.floor(-o.left / size), c1 = Math.floor((S.w - o.left - 0.01) / size);
    var r0 = Math.max(0, Math.floor(-o.top / size)), r1 = Math.min(n - 1, Math.floor((S.h - o.top - 0.01) / size));
    for (var r = r0; r <= r1; r++) {
      for (var c = c0; c <= c1; c++) {
        var parts = l.stack ? l.stack.map(function (name) { return {name: name, seen: true, stack: true}; })
                  : l.global ? [{name: null, seen: true}] : owners(lonOf(c / n), lonOf((c + 1) / n), latOf((r + 1) / n), latOf(r / n));
        for (var j = 0; j < parts.length; j++) {
          var p = parts[j];
          if (!p.seen) { used.none = true; continue; }
          var s = source(id, p.name), key = null;
          if (!s) continue;
          if (l.stack) {
            // Every part at the day found for the centre of the view; a
            // then-and-now side's at its own day.
            ask(s);
            used[s.name] = s;
            var day = l.then ? l.time : S.day;
            if (!day || S.imagery !== "ok") continue;
            key = day;
          } else if (l.time || l.then) {
            // A then-and-now side with no day draws nothing, never the latest.
            if (S.imagery !== "ok" || !l.time) continue;
            used[s.name] = s;
            key = l.time;
          } else if (s.step) {
            ask(s);
            var f = frameOf(s, frame);
            used[s.name] = s;
            if (!f) continue;
            key = f.key;
          } else {
            if (S.imagery !== "ok") continue;
            used[s.name] = s;
          }
          var z = Math.min(gz, s.zoom), k = Math.pow(2, gz - z);
          var cc = Math.floor(c / k), rr = Math.floor(r / k), m = Math.pow(2, z), clip = "", left = 0, right = 0;
          if (p.name && !p.stack) {
            // The imager's side of the tile, a hair wide so no seam shows.
            var P0 = lonOf(cc / m), P1 = lonOf((cc + 1) / m);
            left = Math.max(0, (p.w - P0) / (P1 - P0) * 100 - 0.1); right = Math.max(0, (P1 - p.e) / (P1 - P0) * 100 - 0.1);
            if (left > 0 || right > 0) clip = "inset(0 " + right.toFixed(2) + "% 0 " + left.toFixed(2) + "%)";
          }
          var id2 = s.name + "/" + (key || "-") + "/" + z + "/" + cc + "/" + rr + (clip ? "/" + clip : "");
          if (seen[id2]) continue;
          seen[id2] = true;
          out.push({id: id2, z: z, c: cc, r: rr, clip: clip, name: s.name, key: key,
                    url: tileUrl(s, key, z, rr, ((cc % m) + m) % m), faint: l.faint || null,
                    credit: (s.sat && D.gibs.satellites[s.sat]) || l.credit, nasa: true, cut: [left / 100, right / 100],
                    check: timed(s)});
        }
      }
    }
    return {cells: out, used: used};
  }
  function loopLength() {
    var n = 1;
    for (var k in S.inView) {
      var s = S.inView[k];
      if (s && s.name && timed(s)) { var f = framesOf(s); if (f) n = Math.max(n, f.length); }
    }
    return n;
  }
  function overSpecs(id) {
    var l = LAYERS[id];
    // Over a then-and-now side, Esri's roads and names as over World
    // Imagery: to their own zoom, credited in their own words.
    if (l && l.then) l = l.over ? {id: l.id + "-names", over: l.over, zoom: 19, grey: true, credit: l.overCredit} : null;
    return ((l && l.over) || []).map(function (template, j) {
      return {key: "o" + j, cells: xyzCells(l, template, l.id + "+" + j), visible: true, z: j};
    });
  }
  function tiles(moving) {
    // Offline, the tiles already here stay and move with the map; none are asked for.
    moving = moving || S.imagery === "offline";
    var specs = [], inView = {}, count = S.loop ? loopLength() : 1;
    for (var i = 0; i < count; i++) {
      var fi = S.loop ? i : S.frame, got = cells(S.layer, fi);
      for (var k in got.used) inView[k] = got.used[k];
      specs.push({key: "f" + fi, cells: got.cells, visible: fi === S.frame});
    }
    drawPane(panes.a, specs, moving);
    // Each layer on its side of the divider only: the compared one, under the
    // base, does not show through where the base has drawn nothing.
    if (S.compare) {
      var second = cells(S.second, S.frame);
      drawPane(panes.b, [{key: "b", cells: second.cells, visible: true}], moving);
      if (!moving) S.inViewB = second.used;
      panes.a.el.style.clipPath = "inset(0 " + Math.max(0, S.w - S.split * S.w).toFixed(1) + "px 0 0)";
      panes.b.el.style.clipPath = "inset(0 0 0 " + (S.split * S.w).toFixed(1) + "px)";
    } else {
      drawPane(panes.b, [], moving);
      S.inViewB = null;
      panes.a.el.style.clipPath = panes.b.el.style.clipPath = "";
    }
    // A map's own roads and names, over the NASA overlays, on its side of the divider.
    drawPane(panes.o, overSpecs(S.layer), moving);
    panes.o.el.style.clipPath = panes.a.el.style.clipPath;
    drawPane(panes.ob, S.compare ? overSpecs(S.second) : [], moving);
    panes.ob.el.style.clipPath = panes.b.el.style.clipPath;
    var refs = [];
    D.layers.forEach(function (l) {
      if (l.kind === "overlay" && S.refs[l.id] && S.imagery === "ok" && !S.then) refs.push({key: l.id, cells: cells(l.id, 0).cells, visible: true, z: refs.length});
    });
    drawPane(panes.r, refs, moving);
    // NASA's ocean and flood tiles, over the whole map, both sides of the divider.
    drawPane(panes.e, ensoTileSpecs(), moving);
    if (!moving) { S.inView = inView; loopWhenKnown(); }
  }

  // ---- drawing in world units -------------------------------------------------
  var geoDirty = true, geoRef = null, coastDone = 0, coastD = "", geoCopies = 0, geoLo = 0, geoHi = 0, geoExt = null;
  // Every x of the geometry passes here, which keeps the span it reaches.
  function X(lon, k) {
    var x = Math.round((mx(lon) + k) * UNIT);
    if (x < geoLo) geoLo = x;
    if (x > geoHi) geoHi = x;
    return x;
  }
  function Y(lat) { return Math.round(my(lat) * UNIT); }
  function line(points, k, close) {
    var out = "";
    for (var i = 0; i < points.length; i++) out += (i ? "L" : "M") + X(points[i][0], k) + " " + Y(points[i][1]);
    return out && close ? out + "Z" : out;
  }
  function pt(p) { return [p.lon, p.lat]; }
  function ring(c, quads) {
    var pts = [];
    for (var q = 0; q < 4; q++) {
      var r = quads[q] * NM;
      if (!(r > 0)) { pts.push([c.lon, c.lat]); continue; }
      for (var b = q * 90; b <= q * 90 + 90; b += 5) pts.push(dest(c.lon, c.lat, b, r));
    }
    return pts;
  }
  function near(x0) { return Math.round(S.x - x0); }
  // Zoomed out on a wide screen the world repeats, as the tiles and the
  // composite do. A mark shows on every copy in view: the nearest, then a
  // world either side, as many as the view is wide, with px of margin for
  // what runs past the mark.
  function copies(x0, px) {
    var W = world(), reach = Math.max(0, Math.ceil(S.w / (2 * W) + px / W - 0.5)), k = near(x0), out = [k];
    for (var j = 1; j <= reach; j++) out.push(k - j, k + j);
    return out;
  }
  // The geometry is built once, round the copy nearest the view, and drawn
  // again a world to either side as often as the view needs: it is rebuilt
  // only a quarter of a world on, so a copy is drawn wherever what it holds,
  // as far from the centre as the farthest point built, could be brought
  // into view by then.
  function geoReach() { return geoExt === null ? 0 : Math.max(0, Math.floor(S.w / (2 * world()) + 0.25 + geoExt)); }
  // The markup again, a world to either side, reach times over. Each copy
  // is markup of its own and not an SVG use element: the page's stylesheet
  // does not reach into what one of those draws, and Chrome filled every
  // region and coast on such a copy black.
  function repeated(markup, reach) {
    var out = markup;
    for (var j = 1; j <= reach; j++) {
      out += '<g transform="translate(' + j * UNIT + ' 0)">' + markup + "</g>" +
             '<g transform="translate(' + (-j * UNIT) + ' 0)">' + markup + "</g>";
    }
    return out;
  }
  function buildGeo() {
    geoDirty = false; geoRef = S.x; geoLo = Infinity; geoHi = -Infinity;
    var h = [ensoGeo()], style = D.style;
    // Entered (thennow.py), no geometry of today's is drawn over another day's ground.
    if (S.then) { geoExt = null; geoCopies = geoReach(); geoG.innerHTML = ""; return; }
    if (S.show.outlook) D.outlook.forEach(function (a) {
      var k = near(mx(a.lon)), colour = style.outlook[a.level] || "var(--ink2)";
      var ran = a.alert && a.formation && lapsed(a.formation.until);
      if (a.area && a.area.length > 2) h.push('<path class="area' + (ran ? " lapsed" : "") + '" d="' + line(a.area, k, true) + '" style="fill:' + colour + ";stroke:" + colour + '"/>');
      if (a.arrow && a.arrow.length > 1) h.push('<path class="arrow" d="' + line(a.arrow, k) + '" style="stroke:' + colour + '"/>');
    });
    STORMS.forEach(function (st) {
      var s = st.d, k = near(st.x0);
      if (S.show.cone && s.cone && s.cone.length > 2) h.push('<path class="cone" d="' + line(s.cone, k, true) + '"/>');
      if (S.show.surge && s.surge) s.surge.forEach(function (a) { h.push('<path class="surge" d="' + line(a.ring, k, true) + '"/>'); });
      if (S.show.watches && s.watches) ORDER.forEach(function (kind) {
        s.watches.forEach(function (w) {
          if (w.kind !== kind) return;
          var d = line(w.coords, k);
          h.push('<path class="wwcase" d="' + d + '"/><path class="ww" d="' + d + '" style="stroke:' + (style.products[kind] || "var(--ink)") + '"/>');
        });
      });
    });
    (D.invests || []).forEach(function (v) {
      if (v.track.length > 1) h.push('<path class="investtrack" d="' + line(v.track.map(pt), near(mx(v.lon))) + '"/>');
    });
    STORMS.forEach(function (st) {
      var s = st.d, k = near(st.x0), past = s.track.map(pt);
      var ahead = (past.length ? [past[past.length - 1]] : []).concat(s.forecast.map(pt));
      if (past.length > 1) {
        var dp = line(past, k);
        h.push('<path class="trackcase" d="' + dp + '"/><path class="track" d="' + dp + '" style="stroke:' + st.hue + '"/>');
      }
      if (ahead.length > 1) {
        var df = line(ahead, k);
        h.push('<path class="trackcase" d="' + df + '"/><path class="forecast" d="' + df + '" style="stroke:' + st.hue + '"/>');
      }
      if (!S.show.radii) return;
      var c = centreAt(st, when(st));
      if (!c) return;
      THRESHOLDS.forEach(function (t) {
        var q = c.radii[t];
        if (!q || !(q[0] || q[1] || q[2] || q[3])) return;
        h.push('<path class="radii r' + t + '" data-radii="' + esc(st.id) + '" data-kt="' + t + '" d="' +
               line(ring(c, q), k, true) + '" style="fill:' + st.hue + ";stroke:" + st.hue + '"/>');
      });
    });
    geoExt = geoLo > geoHi ? null : Math.max(geoRef - geoLo / UNIT, geoHi / UNIT - geoRef);
    geoCopies = geoReach();
    geoG.innerHTML = repeated(h.join(""), geoCopies);
  }
  // The page's own coastline, drawn only when what lies under the marks cannot
  // be had: offline, the map's service not answering, or, under a NASA layer,
  // GIBS not answering or none of its tiles arriving.
  function baseDown() {
    if (S.imagery === "offline") return true;
    var l = LAYERS[S.layer];
    return l && l.kind === "map" ? mapDown(S.layer) : S.imagery === "unreachable" || nasaDown(S.inView);
  }
  // It runs from 0 to 1 in x and moves whole worlds with the view (placeWorld),
  // so it is drawn again as many worlds either side as half the view is wide.
  function coastReach() { return Math.ceil(S.w / (2 * world())); }
  function buildCoast() {
    var want = baseDown() ? coastReach() : 0;
    if (want === coastDone) return;
    coastDone = want;
    if (!want) { coastG.innerHTML = ""; return; }
    if (!coastD) {
      var parts = [];
      D.coast.lines.forEach(function (text) {
        var v = text.split(","), x = 0, y = 0, s = "";
        for (var i = 0; i + 1 < v.length; i += 2) {
          x += +v[i]; y += +v[i + 1];
          s += (i ? "L" : "M") + Math.round(mx(x / 100) * UNIT) + " " + Math.round(my(y / 100) * UNIT);
        }
        parts.push(s);
      });
      coastD = parts.join("");
    }
    coastG.innerHTML = repeated('<path class="coast" d="' + coastD + '"/>', want);
  }
  function placeWorld() {
    var o = origin(), k = o.W / UNIT, at = function (left) {
      return "matrix(" + k + " 0 0 " + k + " " + left.toFixed(2) + " " + o.top.toFixed(2) + ")";
    };
    geoG.setAttribute("transform", at(o.left));
    // The coastline's own world is the one under the view, however far a drag has run.
    coastG.setAttribute("transform", at(o.left + Math.floor(S.x) * o.W));
  }

  // ---- drawing on the screen -------------------------------------------------
  function drawMarks() {
    var o = origin(), out = [], top = [], boxes = [];
    function sx(lon, k) { return (mx(lon) + k) * o.W + o.left; }
    function sy(lat) { return my(lat) * o.W + o.top; }
    function off(x, y, m) { return x < -m || y < -m || x > S.w + m || y > S.h + m; }
    function free(x, y, w, hgt) {
      for (var i = 0; i < boxes.length; i++) {
        var b = boxes[i];
        if (x < b[2] && b[0] < x + w && y < b[3] && b[1] < y + hgt) return false;
      }
      boxes.push([x, y, x + w, y + hgt]);
      return true;
    }
    // A label to the right of its mark, else to the left, else left out:
    // the mark keeps its place and a tap still names it. A label that must
    // keep to part of the screen says which spans it may take (fits).
    function label(x, y, r, lines, always, fits) {
      var w = 0;
      lines.forEach(function (l, i) { w = Math.max(w, l[0].length * (i ? 6.2 : 7.2)); });
      var hgt = lines.length * 14, top = y - 10;
      var right = x + r + 5, left = x - r - 5 - w;
      var at = (!fits || fits(right, right + w)) && free(right, top, w, hgt) ? [right, "start", right]
             : (!fits || fits(left, left + w)) && free(left, top, w, hgt) ? [left, "end", x - r - 5]
             : always ? [right, "start", right] : null;
      if (!at) return "";
      return lines.map(function (l, i) {
        return '<text x="' + at[2].toFixed(1) + '" y="' + (y + 3 + i * 14).toFixed(1) + '" text-anchor="' + at[1] + '" class="' + l[1] + '">' + esc(l[0]) + "</text>";
      }).join("");
    }
    function cross(x, y, colour) {
      var d = "M" + (x - 6) + " " + (y - 6) + "L" + (x + 6) + " " + (y + 6) + "M" + (x + 6) + " " + (y - 6) + "L" + (x - 6) + " " + (y + 6);
      return '<path class="xcase" d="' + d + '"/><path class="x" d="' + d + '" style="stroke:' + colour + '"/>';
    }
    // Storms are placed first, so their names win any contest for the space,
    // and drawn last, over every other mark.
    // Entered (thennow.py), the ground is another day's: today's storms,
    // outlook areas, invests and regions are not drawn on it.
    var drawn = [], live = !S.then;
    if (live) STORMS.forEach(function (st) {
      var b = base(st), c = centreAt(st, b.t + S.scrub * HOUR);
      if (!c) return;
      copies(st.x0, 200).forEach(function (k) {
        var x = sx(c.lon, k), y = sy(c.lat);
        if (off(x, y, 200)) return;
        // Close in, the centre is a hollow ring, so the eye under it shows.
        var close = S.z >= 6, R = close ? 6 : [5, 6.5, 7.5, 8.5, 9.5, 11][clamp(c.category || 0, 0, 5)];
        free(x - R, y - R, 2 * R, 2 * R);
        drawn.push({st: st, c: c, x: x, y: y, R: R, image: b.image, close: close});
      });
    });
    drawn.forEach(function (m) {
      var s = m.st.d, selected = m.st.id === S.selected, pieces = [];
      if (m.image && !S.scrub && s.view && s.view.parallax) {
        var dx = (mx(s.view.parallax[0]) - mx(s.lon)) * o.W, dy = (my(s.view.parallax[1]) - my(s.lat)) * o.W;
        var nm = s.eye > 0 ? s.eye / 2 : (s.rmw > 0 ? s.rmw : 8);
        var r = nm * NM / (CIRCUMFERENCE * Math.cos(rad(m.c.lat)) / o.W);
        if (r >= 3) {
          var cx = (m.x + dx).toFixed(1), cy = (m.y + dy).toFixed(1);
          pieces.push('<circle class="ringcase" cx="' + cx + '" cy="' + cy + '" r="' + r.toFixed(1) + '"/>' +
                      '<circle class="ring" cx="' + cx + '" cy="' + cy + '" r="' + r.toFixed(1) + '"/>');
        }
      }
      // Now, the centre's own figure; ahead, the forecast's, between its times.
      var fix = s.advisory_fix, kt = S.scrub ? m.c.wind : (fix && fix.wind != null ? fix.wind : s.wind);
      var wind = kt != null ? Math.round(kt / 5) * 5 + " kt" : "";
      top.push(pieces.join("") + '<g class="hit" data-storm="' + esc(m.st.id) + '">' +
        '<circle class="pad" cx="' + m.x.toFixed(1) + '" cy="' + m.y.toFixed(1) + '" r="24"/>' +
        (m.close ? '<circle class="eyecase" cx="' + m.x.toFixed(1) + '" cy="' + m.y.toFixed(1) + '" r="' + m.R + '"/>' +
                   '<circle class="eye hollow" cx="' + m.x.toFixed(1) + '" cy="' + m.y.toFixed(1) + '" r="' + m.R + '" style="stroke:' + m.st.hue + '"/>'
                 : '<circle class="eye" cx="' + m.x.toFixed(1) + '" cy="' + m.y.toFixed(1) + '" r="' + m.R + '" style="fill:' + m.st.hue + '"/>') +
        label(m.x, m.y, m.R, [[s.title, "dl"], [wind + (S.scrub ? " at +" + S.scrub + " h" : ""), "dl2"]], selected) + "</g>");
    });
    // Close in, each watch or warning and each surge area says what it is
    // beside its official colour.
    if (live && S.z >= 6) STORMS.forEach(function (st) {
      var s = st.d;
      copies(st.x0, 200).forEach(function (k) {
        if (S.show.watches && s.watches) s.watches.forEach(function (w) {
          var n = w.coords.length, a = w.coords[Math.floor((n - 1) / 2)], b = w.coords[Math.ceil((n - 1) / 2)];
          if (!a) return;
          var x = sx((a[0] + b[0]) / 2, k), y = sy((a[1] + b[1]) / 2);
          if (!off(x, y, 0)) out.push(label(x, y, 6, [[w.kind, "dl2"]]));
        });
        if (S.show.surge && s.surge) s.surge.forEach(function (area) {
          var lon = 0, lat = 0, n = area.ring.length;
          if (!n) return;
          area.ring.forEach(function (p) { lon += p[0] / n; lat += p[1] / n; });
          var x = sx(lon, k), y = sy(lat);
          if (!off(x, y, 0)) out.push(label(x, y, 4, [[area.feet + " surge", "dl2"]]));
        });
      });
    });
    if (live) STORMS.forEach(function (st) {
      var s = st.d, selected = st.id === S.selected;
      copies(st.x0, 200).forEach(function (k) {
        s.forecast.forEach(function (p) {
          var x = sx(p.lon, k), y = sy(p.lat);
          if (off(x, y, 20)) return;
          out.push('<circle class="dot" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="3.5" style="stroke:' + st.hue + '"/>');
          if (selected && p.hour % 24 === 0) out.push(label(x, y, 4, [["+" + p.hour + " h", "dl2"]]));
        });
      });
    });
    // The place found or tapped: over everything, and always named, in full
    // where that fits beside it on the map, else by its first part.
    var pins = [], named = [];
    if (S.pin) copies(mx(S.pin.lon), 200).forEach(function (k) {
      var px = sx(S.pin.lon, k), py = sy(S.pin.lat);
      if (off(px, py, 30)) return;
      pins.push([px, py]);
      var text = S.pin.label, w = text.length * 7.2;
      if (w > Math.max(S.w - px, px) - 20) { text = text.split(", ")[0]; w = text.length * 7.2; }
      var right = px + 16 + w <= S.w - 4 || px - 16 - w < 4 && S.w - px >= px;
      free(right ? px + 16 : px - 16 - w, py - 10, w, 14);
      top.push('<circle class="pincase" cx="' + px.toFixed(1) + '" cy="' + py.toFixed(1) + '" r="11"/>' +
        '<circle class="pin" cx="' + px.toFixed(1) + '" cy="' + py.toFixed(1) + '" r="6"/>' +
        '<text x="' + (right ? px + 16 : px - 16).toFixed(1) + '" y="' + (py + 3).toFixed(1) +
        '" text-anchor="' + (right ? "start" : "end") + '" class="dl">' + esc(text) + "</text>");
    });
    function underPin(x, y) { return pins.some(function (p) { return Math.abs(x - p[0]) < 3 && Math.abs(y - p[1]) < 3; }); }
    var sel = BYID[S.selected];
    if (live && sel && S.show.places) {
      var c = centreAt(sel, when(sel));
      copies(sel.x0, 200).forEach(function (k) {
        sel.d.exposure.forEach(function (pl) {
          var x = sx(pl.lon, k), y = sy(pl.lat);
          if (off(x, y, 10)) return;
          var level = c ? inside(c, pl.lon, pl.lat) : 0;
          // A town under the pin is named by the pin.
          named.push([x, y]);
          out.push('<circle class="place' + (level ? " in" + level : "") + '" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + (level ? 5.5 : 4) + '"/>' +
                   (underPin(x, y) ? "" : label(x, y, 5, [[pl.place + (level ? ": inside " + level + " kt" : ""), "dl2"]], !!level)));
        });
      });
    }
    if (live && S.show.outlook) D.outlook.forEach(function (a) {
      var colour = D.style.outlook[a.level] || "var(--ink2)";
      var words = a.centre === "JTWC" ? (a.level || "unrated") + " potential in 24 h"
                : pct(a.chance_2day) + " in 2 days, " + pct(a.chance_7day) + " in 7";
      var lines = [[a.label, "dl2"], [words, "dl2"]];
      if (a.centre === "JTWC" && a.alert) lines.push([alertWords(a.formation && a.formation.until, true), "dl2"]);
      copies(mx(a.lon), 200).forEach(function (k) {
        var x = sx(a.lon, k), y = sy(a.lat);
        if (off(x, y, 10)) return;
        out.push('<g class="hit" data-area="' + esc(a.key) + '"><circle class="pad" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="22"/>' +
                 cross(x, y, colour) + label(x, y, 7, lines) + "</g>");
      });
    });
    if (live) (D.invests || []).forEach(function (v) {
      copies(mx(v.lon), 200).forEach(function (k) {
        var x = sx(v.lon, k), y = sy(v.lat);
        if (off(x, y, 10)) return;
        out.push('<circle class="invest" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="6"/>' +
                 label(x, y, 6, [[v.name + (v.wind != null ? ", " + v.wind + " kt" : ""), "dl2"]]));
      });
    });
    // The Nino regions with this week's anomalies, the regions in play while
    // they are ticked, and the one Show asked for.
    if (live) ensoLabels(sx, sy, off, label).forEach(function (words) { out.push(words); });
    // The gazetteer's towns, the most populous first and more as the view
    // closes in, wherever a name fits; capitals from the first level shown.
    // A map carries its own names, so over one the gazetteer's stand aside,
    // on its own side of the divider when two layers are compared.
    if (S.show.towns && !townsWhy()) {
      if (!BYPOP) BYPOP = PLACES.map(function (p, i) { return i; }).sort(function (a, b) { return PLACES[b][3] - PLACES[a][3]; });
      var least = S.z >= 9 ? 0 : S.z >= 8 ? 20000 : S.z >= 7 ? 60000 : S.z >= 6 ? 200000 : S.z >= 5 ? 600000 : 2000000;
      pins.forEach(function (p) { named.push(p); });
      for (var i = 0, shown = 0; i < BYPOP.length && shown < 120; i++) {
        var pl = PLACES[BYPOP[i]];
        if (pl[3] < least && !pl[6]) continue;
        var ks = copies(mx(pl[4]), 200);
        for (var j = 0; j < ks.length && shown < 120; j++) {
          var tx = sx(pl[4], ks[j]), ty = sy(pl[5]);
          if (off(tx, ty, -2) || namedAt(tx) || named.some(function (q) { return Math.abs(q[0] - tx) < 3 && Math.abs(q[1] - ty) < 3; })) continue;
          // Its name lies wholly on imagery, not across the divider on a map.
          var words = label(tx, ty, 3, [[pl[0], "dl2"]], false, function (a, b) { return !namedAt(a) && !namedAt(b); });
          if (!words) continue;
          out.push('<circle class="town" cx="' + tx.toFixed(1) + '" cy="' + ty.toFixed(1) + '" r="' + (pl[6] ? 3.2 : 2.4) + '"/>' + words);
          shown++;
        }
      }
    }
    marksG.innerHTML = out.join("") + top.join("");
  }
  // The gazetteer's town names are drawn over NASA's imagery from zoom 4; a
  // map names its own. Their box says which holds while they are not drawn:
  // compared, while neither side of the divider is imagery.
  function townsWhy() {
    if (labelledBase() && (!S.compare || labelled(S.second))) return "(the map names its own)";
    return S.z < 4 ? "(from zoom 4)" : "";
  }
  var townsSaid = null;
  function townsNote() {
    var el = $("why-towns"), text = townsWhy();
    if (el && text !== townsSaid) { el.textContent = text; townsSaid = text; }
  }

  // ---- the detail layer's day --------------------------------------------------
  // HLS is each day's Landsat and Sentinel-2 passes, swath by swath, and GIBS
  // lists every day for everywhere, so the day with an image at the centre of
  // the view is found by looking at the tile there: the newest day GIBS lists
  // first, then a day at a time back, DAYS_BACK at most. A day stepped to stays
  // while the centre still has an image on it; otherwise the newest there is
  // found again once the view settles. A day GIBS does not answer for at all
  // is no answer, not no image: the search stops there, says so, and looks
  // again in a minute.
  var DAYS_BACK = 40, NO_ANSWER = "no answer", looks = {}, dayAt = "", dayRetry = 0, quest = 0;
  function detailOn() { return S.layer === "detail" || (S.compare && S.second === "detail"); }
  function newestDay() {
    var best = null;
    (LAYERS.detail ? LAYERS.detail.stack : []).forEach(function (name) {
      var d = DOM[name];
      if (d && d.frames.length && (!best || d.frames[0].key > best)) best = d.frames[0].key;
    });
    return best;
  }
  function shiftDay(day, n) { return dayZ(stamp(day) + n * 24 * HOUR); }
  function dayText(day) { var d = new Date(stamp(day)); return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + " " + d.getUTCFullYear(); }
  function centreTile() {
    var z = clamp(Math.round(S.z), 0, LAYERS.detail.zoom), n = Math.pow(2, z);
    var x = (((S.x % 1) + 1) % 1) * n, y = clamp(S.y, 0, 1 - 1e-9) * n;
    return {z: z, c: Math.floor(x), r: Math.floor(y), fx: x - Math.floor(x), fy: y - Math.floor(y)};
  }
  // One imager's tile for a day, as 32 by 32 pixels; it is the tile the map
  // draws, so the browser asks for it once. A tile that does not load is
  // false: no answer, which a blank tile is not.
  function look(name, day, t) {
    var key = name + "/" + day + "/" + t.z + "/" + t.c + "/" + t.r;
    if (!looks[key]) looks[key] = new Promise(function (done) {
      var img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = function () {
        try {
          var cv = document.createElement("canvas");
          cv.width = cv.height = 32;
          var cx = cv.getContext("2d", {willReadFrequently: true});
          cx.drawImage(img, 0, 0, 32, 32);
          done(cx.getImageData(0, 0, 32, 32).data);
        } catch (err) { done(null); }
      };
      img.onerror = function () { delete looks[key]; done(false); };
      img.src = tileUrl(source("detail", name), day, t.z, t.r, t.c);
    });
    return looks[key];
  }
  function covered(px, t) {
    if (!px) return false;
    var cx = Math.floor(t.fx * 32), cy = Math.floor(t.fy * 32);
    for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
      if (px[(clamp(cy + dy, 0, 31) * 32 + clamp(cx + dx, 0, 31)) * 4 + 3] > 0) return true;
    }
    return false;
  }
  // true: an image here that day. false: none, from the imagers that
  // answered; a 500 for Landsat's day while Sentinel-2 answers is still none.
  // null: none, and no imager answered at all.
  function imageOn(day, t) {
    return Promise.all(LAYERS.detail.stack.map(function (name) { return look(name, day, t); }))
      .then(function (all) {
        if (all.some(function (px) { return covered(px, t); })) return true;
        return all.every(function (px) { return px === false; }) ? null : false;
      });
  }
  function hunt(day, by, last, t, q) {
    if (q !== quest || (by < 0 ? day < last : day > last)) return Promise.resolve(null);
    return imageOn(day, t).then(function (yes) {
      if (q !== quest) return null;
      if (yes === null) return NO_ANSWER;
      return yes ? day : hunt(shiftDay(day, by), by, last, t, q);
    });
  }
  // by: 0 the newest day with an image here, -1 the one before the day shown, +1 after.
  function findDay(by) {
    var newest = newestDay(), t = centreTile(), q = ++quest;
    if (!newest) return;
    var from = by ? shiftDay(S.day || newest, by) : newest;
    S.dayState = "looking";
    requestRender();
    hunt(from, by > 0 ? 1 : -1, by > 0 ? newest : shiftDay(newest, -DAYS_BACK), t, q).then(function (day) {
      if (q !== quest) return;
      if (day === NO_ANSWER) noAnswer(!by);
      else if (day) { S.day = day; S.dayState = "ok"; S.dayStepped = !!by; }
      else if (by) S.dayState = by < 0 ? "none earlier" : "none later";
      else { S.day = null; S.dayState = "none"; }
      dirty();
    });
  }
  // GIBS did not answer here: said as that, and the place looked at again in a
  // minute, or at once if the view moves. A day already shown stays shown.
  function noAnswer(forget) {
    if (forget) S.day = null;
    S.dayState = NO_ANSWER;
    clearTimeout(dayRetry);
    dayRetry = setTimeout(function () {
      if (S.dayState === NO_ANSWER) { dayAt = ""; requestRender(); }
    }, 60000);
  }
  function dayCheck() {
    if (!detailOn() || S.imagery !== "ok") return;
    var t = centreTile(), at = [t.z, t.c, t.r, Math.floor(t.fx * 8), Math.floor(t.fy * 8)].join("/");
    if (at === dayAt) return;
    if (!newestDay()) {
      LAYERS.detail.stack.forEach(function (name) { ask(source("detail", name)); });
      return;
    }
    dayAt = at;
    if (!S.day || !S.dayStepped) { findDay(0); return; }
    var q = ++quest, day = S.day;
    imageOn(day, t).then(function (yes) {
      if (q !== quest) return;
      if (yes === null) { noAnswer(false); dirty(); }
      else if (yes) { S.dayState = "ok"; dirty(); }
      else { S.dayStepped = false; findDay(0); }
    });
  }
  function dayWords() {
    if (S.dayState === "looking") return "looking for a day with an image here";
    if (S.dayState === NO_ANSWER) return (S.day ? dayText(S.day) + "; " : "") + "NASA GIBS did not answer, so " +
      (S.day ? "no other day" : "no day") + " could be checked here; looking again in a minute";
    if (!S.day) return S.dayState === "none" && newestDay()
      ? "no image here in the " + DAYS_BACK + " days to " + dayText(newestDay()) : "asking NASA GIBS for the days";
    var age = Math.round((stamp(dayZ(Date.now())) - stamp(S.day)) / (24 * HOUR));
    return dayText(S.day) + (age > 0 ? ", " + age + (age === 1 ? " day" : " days") + " ago" : "") +
      (S.dayState === "none earlier" ? "; no earlier day with an image here" :
       S.dayState === "none later" ? "; no later day with an image here" : "");
  }
  function dayControls() {
    var box = $("days"), on = detailOn() && S.imagery === "ok";
    if (box.hidden !== !on) box.hidden = !on;
    if (!on) return;
    var words = S.dayState === "looking" ? "Looking\u2026" : S.day ? dayText(S.day) : S.dayState === "none" ? "No image here" : S.dayState === NO_ANSWER ? "No answer" : "Asking GIBS\u2026";
    if ($("day-now").textContent !== words) $("day-now").textContent = words;
    var busy = S.dayState === "looking" || !S.day, newest = newestDay();
    $("day-earlier").disabled = busy || S.dayState === "none earlier";
    $("day-later").disabled = busy || S.dayState === "none later" || !newest || S.day >= newest;
  }

  // ---- what the map is showing, in words -------------------------------------
  // Two lines show: the imagery under the selected storm, and when and where
  // that storm is drawn. Every other imager and note is one tap away.
  var pillOpen = false, pillHtml = "";
  // Anything drawn from NASA: imagery under or beside the map, its overlays,
  // and the El Nino tiles over it.
  function nasaWanted() {
    var l = LAYERS[S.layer], two = S.compare ? LAYERS[S.second] : null, k;
    if (!l || l.kind !== "map" || (two && two.kind !== "map")) return true;
    for (k in S.refs) if (S.refs[k]) return true;
    for (k in (S.enso && S.enso.tiles) || {}) if (S.enso.tiles[k]) return true;
    return false;
  }
  // The status pill's words, beside its Retry: a map whose server is not
  // answering, on either side of the divider; GIBS not answering while
  // anything drawn needs it, or none of the tiles of a side's NASA layer arriving.
  function downWord() {
    if (S.imagery === "offline") return "";
    if (S.then) return thenDown();
    if (labelledBase() && mapDown(S.layer) || S.compare && labelled(S.second) && mapDown(S.second)) return "Map unreachable.";
    if (S.imagery === "ok" && (nasaDown(S.inView) || S.compare && nasaDown(S.inViewB))) return "Imagery unreachable.";
    return S.imagery === "unreachable" && nasaWanted() ? "Imagery unreachable." : "";
  }
  // One NASA source drawn, as the pill names it: its imager and layer, and
  // the time of its frame on show, or why there is none.
  function sourceWords(s) {
    var words = (s.sat ? s.sat + " " : "") + s.layer.name + (s.note ? " (" + s.note + ")" : "");
    if (tilesDown(s)) return words + ": its tiles did not arrive";
    if (s.layer.time) return words + ": VIIRS, " + s.layer.time.slice(0, 4) + ", 500 m";
    if (!s.step) return words;
    var f = frameOf(s, S.frame), d = DOM[s.name];
    return words + (f ? ": " + (timed(s) ? utc(f.t) + ", " + ago(f.t) : f.key + ", daily")
                      : d && d.unanswered ? ": GIBS did not answer" : d && d.failed ? ": no frames from GIBS" : ": loading");
  }
  function pills() {
    var head = [], more = [], layer = LAYERS[S.layer], st = BYID[S.selected], then = !!S.then;
    var mine = st && st.d.view ? st.d.view.satellite : null;
    if (then) thenPill(head, more);
    else if (layer && layer.kind === "map") {
      // A map comes from its own service, not from GIBS, and is spoken of as that.
      if (S.imagery === "offline") head.push("Offline: street and satellite maps need the network; the tiles already loaded stay. The coastline is the page's own copy.");
      else if (mapDown(layer.id)) head.push("Map unreachable: " + layer.source + " did not answer. The coastline is the page's own copy.");
      else head.push("Map: " + layer.source + (layer.over ? ", with Esri's roads and place names" : ""));
      var drawn = S.inView[layer.id];
      if (drawn && drawn.coarser !== null && drawn.coarser !== undefined) {
        more.push(layer.source + " has nothing finer than zoom " + drawn.coarser + " for part of this view; that part is its zoom-" +
                  drawn.coarser + " tile, enlarged.");
      }
    }
    else if (S.imagery === "offline") head.push(document.querySelector("#tiles img") ? "Offline: the imagery already loaded stays; no new frames. The coastline is the page's own copy." : "Offline: no imagery. The coastline is the page's own copy.");
    else if (S.imagery === "unreachable") head.push("Imagery unreachable: NASA GIBS did not answer. The coastline is the page's own copy.");
    else if (S.imagery === "pending") head.push("Imagery: asking NASA GIBS for the latest frames");
    else {
      var lines = [];
      var stacked = false;
      Object.keys(S.inView).forEach(function (name) {
        var s = S.inView[name];
        if (!s || !s.name) return;
        if (s.layer.stack) {
          if (!stacked) lines.push("Landsat and Sentinel-2, 30 m: " + dayWords());
          stacked = true;
          return;
        }
        var words = sourceWords(s);
        if (mine && s.sat === mine) lines.unshift(words); else lines.push(words);
      });
      if (!lines.length) lines.push(layer.name + ": nothing in view");
      if (nasaDown(S.inView)) head.push("Imagery unreachable: NASA GIBS sent none of the tiles in view. The coastline is the page's own copy.");
      else { head.push(lines.shift()); more = lines; }
      if (S.inView.none) more.push("No geostationary imagery in GIBS for part of this view: no imager within 70 degrees of zenith.");
      if (layer.pixel_km && S.z > layer.zoom + 0.2) more.push("Enlarged " + Math.pow(2, S.z - layer.zoom).toFixed(1) + " times past its " + (layer.pixel_km < 1 ? Math.round(layer.pixel_km * 1000) + " m" : layer.pixel_km + " km") + " pixels.");
    }
    // The compared layer draws its own frame, which can be another time.
    if (S.compare && S.inViewB && !then) {
      var two = [], stacked2 = false;
      Object.keys(S.inViewB).forEach(function (name) {
        var s = S.inViewB[name];
        if (!s || !s.name) return;
        if (s.map) two.push(s.layer.source + (mapDown(s.name) && S.imagery !== "offline" ? " did not answer" : ""));
        else if (S.imagery !== "ok") return;
        else if (s.layer.stack) { if (!stacked2) two.push("Landsat and Sentinel-2, 30 m: " + dayWords()); stacked2 = true; }
        else two.push(sourceWords(s));
      });
      if (two.length) more.push("Compared, right of the divider: " + two.join("; ") + ".");
    }
    if (st && !then) {
      var b = base(st), v = st.d.view || {}, T = b.t + S.scrub * HOUR, toward = COMPASS[Math.round(v.toward / 22.5) % 16];
      var said = st.d.title + " drawn for " + utc(T);
      if (!centreAt(st, T)) said = st.d.title + ": nothing drawn for " + utc(T) + ", past the last forecast point";
      else if (b.image && !S.scrub) said = st.d.title + " at the image time, " + utc(T);
      if (v.satellite && b.image && !S.scrub && centreAt(st, T)) {
        said += "; eye appears " + v.offset_km + " km " + toward + " (ring)";
        more.push("Parallax: cloud tops 15 km up appear " + v.offset_km + " km " + toward + " of the centre, seen by " + v.satellite + " at zenith " + v.zenith + " degrees.");
      }
      head.push(said);
    }
    if (!then) ensoTileMore().forEach(function (l) { more.push(l); });
    var html = head.map(function (l) { return "<div>" + esc(l) + "</div>"; }).join("") +
      (more.length ? '<div class="more"' + (pillOpen ? "" : " hidden") + ">" +
        more.map(function (l) { return '<div class="muted">' + esc(l) + "</div>"; }).join("") + "</div>" +
        '<button type="button" class="pillmore" aria-expanded="' + pillOpen + '">' + (pillOpen ? "Less" : more.length + " more") + "</button>" : "");
    if (html !== pillHtml) { framePill.innerHTML = html; pillHtml = html; }
    var down = downWord();
    statusPill.hidden = !down;
    if (down && (!$("retry") || statusPill.firstChild.textContent !== down)) statusPill.innerHTML = "<span>" + down + '</span><button type="button" class="toolbtn" id="retry">Retry</button>';
  }
  // Every layer drawn is credited as its source asks, and nothing that is
  // not drawn: the words are read off the tiles on the screen, each on its
  // side of the divider, loaded and not hidden. A map is credited in its own
  // service's words; NASA's imagery, overlays and tiles by GIBS's and their
  // own, an imager's only where a tile of its is in view.
  var creditEl = $("credit"), creditSaid = "";
  // Whether the part of a tile its imager draws lies on the screen between x0 and x1.
  function shows(img, o, x0, x1) {
    var size = o.W / Math.pow(2, img._z), x = o.left + img._c * size, y = o.top + img._r * size, cut = img._cut || [0, 0];
    return x + cut[0] * size < x1 && x + size - cut[1] * size > x0 && y < S.h && y + size > 0;
  }
  function credit() {
    var said = [], o = origin(), cut = S.compare ? S.split * S.w : S.w;
    function from(pane, x0, x1) {
      var maps = [], nasa = [];
      for (var k in pane.sets) {
        var set = pane.sets[k];
        if (set.el.style.visibility === "hidden") continue;
        for (var id in set.imgs) {
          var t = set.imgs[id], list = t._nasa ? nasa : maps;
          if (!t._credit || !t.complete || !t.naturalWidth || t.style.visibility === "hidden" || !shows(t, o, x0, x1)) continue;
          if (list.indexOf(t._credit) < 0) list.push(t._credit);
        }
      }
      maps.sort().forEach(function (w) { if (said.indexOf(w) < 0) said.push(w); });
      if (nasa.length && said.indexOf(D.gibs.acknowledge) < 0) said.push(D.gibs.acknowledge);
      nasa.sort().forEach(function (w) { if (said.indexOf(w) < 0) said.push(w); });
    }
    from(panes.a, 0, cut);
    from(panes.o, 0, cut);
    if (S.compare) { from(panes.b, cut, S.w); from(panes.ob, cut, S.w); }
    from(panes.r, 0, S.w);
    from(panes.e, 0, S.w);
    var text = said.join(" ");
    if (text !== creditSaid) { creditEl.textContent = text; creditSaid = text; }
  }
  function scrubText() {
    var st = BYID[S.selected];
    if (!st) return S.scrub ? "+" + S.scrub + " h" : "Now";
    var T = when(st);
    if (!S.scrub) return "Now: " + utc(T);
    return "+" + S.scrub + " h: " + utc(T) + (centreAt(st, T) ? "" : ", past the forecast");
  }

  // ---- the frame loop ------------------------------------------------------
  var raf = 0, anim = 0, loopTimer = 0;
  function requestRender() { if (!raf) raf = requestAnimationFrame(function () { raf = 0; render(); }); }
  function dirty() { geoDirty = true; requestRender(); }
  function measure() {
    var r = map.getBoundingClientRect();
    S.w = Math.max(1, r.width); S.h = Math.max(1, r.height);
    svgEl.setAttribute("viewBox", "0 0 " + S.w + " " + S.h);
  }
  function render() {
    S.z = clamp(S.z, MINZ, maxZoom());
    var W = world(), half = S.h / 2 / W;
    S.y = W > S.h ? clamp(S.y, half, 1 - half) : 0.5;
    tiles(anim !== 0);
    drawComposite();
    // Close in, the rings and cone are outlines, so the imagery shows through.
    svgEl.classList.toggle("close", S.z >= 6);
    if (geoDirty || geoRef === null || Math.abs(S.x - geoRef) > 0.25 || geoReach() !== geoCopies) buildGeo();
    buildCoast();
    placeWorld();
    drawMarks();
    pills();
    townsNote();
    ensoLegend();
    ensoTileLegend();
    credit();
    if (!anim && !pointers.size) dayCheck();
    dayControls();
    if (S.then) thenRender();
    scrubRead.textContent = scrubText();
    divider.hidden = !S.compare;
    if (S.compare) divider.style.left = (S.split * S.w).toFixed(1) + "px";
    $("loop").setAttribute("aria-pressed", S.loop ? "true" : "false");
  }
  function settle() {
    if (S.x < 0 || S.x >= 1) { S.x -= Math.floor(S.x); geoDirty = true; }
    render();
    carryView();
    googleRelink();
  }
  function animate(to, ms) {
    cancelAnimationFrame(anim);
    var from = {x: S.x, y: S.y, z: S.z}, t0 = 0, dur = ms || 650;
    function step(now) {
      if (!t0) t0 = now;
      var f = clamp((now - t0) / dur, 0, 1), e = f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
      S.x = from.x + (to.x - from.x) * e; S.y = from.y + (to.y - from.y) * e; S.z = from.z + (to.z - from.z) * e;
      render();
      if (f < 1) anim = requestAnimationFrame(step); else { anim = 0; settle(); }
    }
    anim = requestAnimationFrame(step);
  }
  function toWorld(px, py) { var W = world(); return {x: S.x + (px - S.w / 2) / W, y: S.y + (py - S.h / 2) / W}; }
  function zoomBy(dz, px, py) {
    px = px == null ? S.w / 2 : px; py = py == null ? S.h / 2 : py;
    var a = toWorld(px, py), z = clamp(S.z + dz, MINZ, maxZoom()), W = TILE * Math.pow(2, z);
    animate({x: a.x - (px - S.w / 2) / W, y: a.y - (py - S.h / 2) / W, z: z}, 300);
  }
  function setLoop(on) {
    clearTimeout(loopTimer);
    S.loopWanted = false;
    S.loop = !!on && loopLength() > 1;
    S.frame = S.loop ? loopLength() - 1 : 0;
    if (S.loop) loopTimer = setTimeout(tick, 450);
    dirty();
    return S.loop;
  }
  function tick() {
    if (!S.loop) return;
    var n = loopLength();
    S.frame = S.frame > 0 ? Math.min(S.frame - 1, n - 1) : n - 1;
    dirty();
    loopTimer = setTimeout(tick, S.frame === 0 ? 1400 : 450);
  }
  // A loop waiting on GIBS's frames: one handed across a load, or kept while
  // a place was entered. It runs once the map is drawn with the frames in
  // view; the reader's own Loop, pressed meanwhile, comes first.
  function loopWhenKnown() {
    if (S.loopWanted && loopLength() > 1) setLoop(true);
  }

  // ---- choosing what to show ------------------------------------------------------
  function select(id) {
    if (!BYID[id]) return;
    S.selected = id;
    document.querySelectorAll("#panel section.storm").forEach(function (sec) { sec.hidden = sec.getAttribute("data-storm") !== id; });
    document.querySelectorAll("#panel .stormrow").forEach(function (row) { row.setAttribute("aria-current", row.getAttribute("data-row") === id ? "true" : "false"); });
    dirty();
  }
  function tab(section, name) {
    section.querySelectorAll("[data-tab]").forEach(function (b) { b.setAttribute("aria-selected", b.getAttribute("data-tab") === name ? "true" : "false"); });
    section.querySelectorAll("[data-pane]").forEach(function (p) { p.hidden = p.getAttribute("data-pane") !== name; });
  }
  // A layer whose servers refuse a page opened from a file is offered only
  // when the page is served. Its button stays, dimmed, and says why when
  // pressed, where a tablet shows it; the compare menu greys it out.
  function servedWhy(l) {
    return l.name + " needs this page served: its servers refuse a page opened from a file. " +
           "Run python track.py --serve (add --lan for a tablet) and open the address it prints.";
  }
  function unserved() {
    D.layers.forEach(function (l) {
      if (!l.served_only || servedOnly(location.protocol)) return;
      var b = $("layer-" + l.id), o = document.querySelector('#compare-layer option[value="' + l.id + '"]');
      if (b) { b.setAttribute("aria-disabled", "true"); b.title = servedWhy(l); }
      if (o) { o.disabled = true; o.textContent = l.name + " (needs the page served)"; }
    });
  }
  function pressLayer(id) {
    var ok = setLayer(id), l = LAYERS[id], note = $("layer-note");
    if (note && !ok && l && l.served_only) note.textContent = servedWhy(l);
    return ok;
  }
  // The layer shown. Whatever changes it, a button, Swap, a found address or
  // a storm's own imagery, the reason a layer could not be had is done with.
  function setLayer(id) {
    if (S.then) thenLeave();
    var l = LAYERS[id], note = $("layer-note");
    if (!l || (l.kind !== "imagery" && l.kind !== "map")) return false;
    if (l.served_only && !servedOnly(location.protocol)) return false;
    if (note) note.textContent = "";
    if (S.compare && id === S.second) S.second = S.layer;
    S.layer = id;
    if (id === "detail") { S.dayStepped = false; dayAt = ""; }
    document.querySelectorAll("[data-layer]").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-layer") === id ? "true" : "false"); });
    $("compare-layer").value = S.second;
    dirty();
    return true;
  }
  // Compare pressed: the button as it shows. While a place is entered the
  // two dates are compared, but the button shows the comparison there was
  // before, and a press turns that one.
  function pressCompare() { setCompare(!(S.then ? S.then.back.compare : S.compare)); }
  function setCompare(on) {
    if (S.then) thenLeave();
    S.compare = !!on;
    if (S.compare && S.second === S.layer) S.second = S.layer === "infrared" ? "geocolor" : "infrared";
    $("compare").setAttribute("aria-pressed", S.compare ? "true" : "false");
    $("compare-layer").value = S.second;
    dirty();
    return S.compare;
  }
  function flyToArea(key) {
    var a = D.outlook.filter(function (x) { return x.key === key; })[0];
    if (!a) return false;
    animate({x: mx(a.lon) + near(mx(a.lon)), y: my(a.lat), z: Math.max(S.z, 5)});
    return true;
  }
  function flyTo(id) {
    if (S.then) thenLeave();
    if (String(id).indexOf("area:") === 0) return flyToArea(String(id).slice(5));
    var st = BYID[id];
    if (!st) return false;
    select(id);
    if (!(st.d.view && st.d.view.satellite) && LAYERS[S.layer].satellites) setLayer("truecolor");
    var c = centreAt(st, when(st)) || {lon: st.d.lon, lat: st.d.lat};
    animate({x: mx(c.lon) + near(mx(c.lon)), y: my(c.lat), z: 7});
    var box = map.getBoundingClientRect();
    if (box.top < 0 || box.bottom > window.innerHeight) map.scrollIntoView({block: "start", behavior: "smooth"});
    return true;
  }
  function fit(instant) {
    var xs = [], ys = [], ref = null;
    function add(lon, lat) { var x = mx(lon); if (ref === null) ref = x; xs.push(x + Math.round(ref - x)); ys.push(my(lat)); }
    STORMS.forEach(function (st) { var c = centreAt(st, when(st)) || {lon: st.d.lon, lat: st.d.lat}; add(c.lon, c.lat); });
    if (!xs.length) D.outlook.forEach(function (a) { add(a.lon, a.lat); });
    var to = {x: mx(-60), y: my(20), z: 3};
    if (xs.length) {
      var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
      var z = Math.log(Math.min(S.w / Math.max((x1 - x0) * TILE, 1e-9), S.h / Math.max((y1 - y0) * TILE, 1e-9))) / Math.LN2 - 0.7;
      to = {x: (x0 + x1) / 2, y: (y0 + y1) / 2, z: clamp(z, MINZ, 5)};
    }
    if (instant) { S.x = to.x; S.y = to.y; S.z = to.z; settle(); } else animate(to);
  }
  // The map page opens on the whole planet across the width with the Pacific
  // in the middle: the ocean El Nino lives in, and every coast it reaches.
  function planet() {
    S.x = mx(-150); S.y = my(0);
    S.z = clamp(Math.log(S.w / TILE) / Math.LN2, Math.max(MINZ, 1), maxZoom());
    settle();
  }
  // A place or a view in the address: #at=lat,lon opens Here there, and
  // #view=lat,lon,zoom shows that view. Anything else is no place at all.
  function parseHash(text) {
    var m = /^#(at|view)=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?:,(-?\d+(?:\.\d+)?))?$/.exec(text || "");
    if (!m || (m[1] === "at") !== (m[4] === undefined)) return null;
    var lat = +m[2], lon = +m[3];
    if (Math.abs(lat) > 90 || Math.abs(lon) > 360) return null;
    // A longitude inside the world is kept as written: wrap() would make
    // -77.04 into -77.04000000000002.
    if (lon < -180 || lon >= 180) lon = wrap(lon);
    return m[1] === "at" ? {at: [lat, lon]} : {view: [lat, lon, clamp(+m[4], 1, 19)]};
  }
  function viewHash() {
    return "#view=" + latOf(S.y).toFixed(4) + "," + wrap(lonOf(S.x)).toFixed(4) + "," + S.z.toFixed(2);
  }
  // The other page's link opens it on this view.
  function carryView() {
    var hash = viewHash();
    document.querySelectorAll("a[data-carry]").forEach(function (a) {
      a.setAttribute("href", a.getAttribute("data-carry") + hash);
    });
  }
  function applyHash(text) {
    if (/^#then=/.test(text || "") && thenHashApply(text)) return true;
    var h = parseHash(text);
    if (!h) return false;
    if (S.then) thenLeave();
    cancelAnimationFrame(anim); anim = 0;
    var p = h.at || h.view;
    S.x = mx(p[1]); S.y = my(p[0]); S.z = clamp(h.view ? p[2] : 10, MINZ, maxZoom());
    settle();
    if (h.at) hereAt(p[1], p[0]);
    return true;
  }
  function readToggles() {
    document.querySelectorAll("[data-show]").forEach(function (box) { S.show[box.getAttribute("data-show")] = box.checked; });
    document.querySelectorAll("[data-ref]").forEach(function (box) { S.refs[box.getAttribute("data-ref")] = box.checked; });
  }

  // ---- finding a place ------------------------------------------------------------
  // The gazetteer ships in the page as the atlas ships it: [name, country,
  // region, population, lon, lat, capital], most populous first. Matching
  // ignores case and accents, so "sao paulo" finds Sao Paulo with its tilde.
  var PLACES = D.places || [], FOLDED = null, BYPOP = null, found = [], active = -1;
  var findForm = $("findform"), findBox = $("find"), findList = $("find-list"), findNote = $("find-note");
  function fold(text) {
    return String(text || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }
  function folded() {
    return FOLDED || (FOLDED = PLACES.map(function (p) { return [fold(p[0]), fold(p[2]), fold(p[1])]; }));
  }
  function named(p) {
    var bits = [p[0]];
    if (p[2] && p[2] !== p[0]) bits.push(p[2]);
    if (p[1]) bits.push(p[1]);
    return bits.join(", ");
  }
  function where(lon, lat) {
    var w = wrap(lon);
    return Math.abs(lat).toFixed(2) + (lat >= 0 ? "N" : "S") + " " + Math.abs(w).toFixed(2) + (w < 0 ? "W" : "E");
  }
  function people(n) { return n > 0 ? n.toLocaleString("en-US") : ""; }
  // The nearest town's people, named unless Here is that town: an address in
  // Lima is not home to all of Lima.
  function peopleFact(label, place) {
    return (String(label).split(", ")[0] === place.name ? "" : esc(place.name) + ": ") +
      people(place.population) + " people (Natural Earth)";
  }
  // Latitude first, as positions are written: "18.0N 76.8W", "18.0, -76.8".
  function coordinate(text) {
    var m = /^\s*([+-]?\d{1,2}(?:\.\d+)?)\s*\u00b0?\s*([NSns])?\s*(?:[,;]\s*|\s+)([+-]?\d{1,3}(?:\.\d+)?)\s*\u00b0?\s*([EWew])?\s*$/.exec(text);
    if (!m) return null;
    var lat = +m[1], lon = +m[3];
    if (m[2] && /s/i.test(m[2])) lat = -Math.abs(lat);
    if (m[4] && /w/i.test(m[4])) lon = -Math.abs(lon);
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return {kind: "point", label: where(lon, lat), sub: "A position", lon: lon, lat: lat, zoom: 9};
  }
  function gather(groups, key, i, rank) {
    var g = groups[key] || (groups[key] = {rank: rank, first: i, members: []});
    g.rank = Math.min(g.rank, rank);
    g.members.push(i);
  }
  // A region's or a country's places within reach of its largest, so islands
  // half a world away do not set the view.
  function extent(g, reach) {
    var p0 = PLACES[g.first], x0 = mx(p0[4]), xs = [], ys = [];
    g.members.forEach(function (i) {
      var p = PLACES[i];
      if (km(p0[4], p0[5], p[4], p[5]) > reach) return;
      var x = mx(p[4]);
      xs.push(x + Math.round(x0 - x)); ys.push(my(p[5]));
    });
    return {x0: Math.min.apply(null, xs), x1: Math.max.apply(null, xs),
            y0: Math.min.apply(null, ys), y1: Math.max.apply(null, ys)};
  }
  function find(text) {
    var c = coordinate(text);
    if (c) return [c];
    var q = fold(text);
    if (q.length < 2) return [];
    var F = folded(), out = [], regions = {}, countries = {};
    for (var i = 0; i < PLACES.length; i++) {
      var f = F[i], p = PLACES[i];
      var r = f[0] === q ? 0 : f[0].indexOf(q) === 0 ? 1 : (" " + f[0]).indexOf(" " + q) >= 0 ? 2 : -1;
      if (r >= 0) out.push({kind: "town", rank: r, weight: p[3], label: named(p),
                            sub: [p[6] ? "Capital" : "Town", p[3] ? people(p[3]) + " people" : ""].filter(Boolean).join(", "),
                            lon: p[4], lat: p[5], zoom: 10, place: i});
      if (f[1] && f[1] !== f[0] && f[1].indexOf(q) === 0) gather(regions, p[2] + "|" + p[1], i, f[1] === q ? 0 : 1);
      if (f[2] && f[2].indexOf(q) === 0) gather(countries, p[1], i, f[2] === q ? 0 : 1);
    }
    function add(groups, kind, reach) {
      Object.keys(groups).forEach(function (k) {
        var g = groups[k], p = PLACES[g.first], n = g.members.length;
        out.push({kind: kind, rank: g.rank, weight: p[3],
                  label: kind === "country" ? p[1] : p[2] + ", " + p[1],
                  sub: (kind === "country" ? "Country" : "Region") + ", " + n + (n === 1 ? " place" : " places") + " in the gazetteer",
                  lon: p[4], lat: p[5], zoom: 7, box: extent(g, reach), place: g.first});
      });
    }
    add(regions, "region", 1500);
    add(countries, "country", 2500);
    out.sort(function (a, b) { return a.rank - b.rank || b.weight - a.weight; });
    return out.slice(0, 8);
  }
  function viewFor(r) {
    if (!r.box) { var x = mx(r.lon); return {x: x + near(x), y: my(clamp(r.lat, -85, 85)), z: Math.min(r.zoom, maxZoom())}; }
    var b = r.box, cx = (b.x0 + b.x1) / 2;
    var z = Math.log(Math.min(S.w / Math.max((b.x1 - b.x0) * TILE, 1e-9),
                              S.h / Math.max((b.y1 - b.y0) * TILE, 1e-9))) / Math.LN2 - 0.5;
    // A street or an address found by the geocoder goes as close as the map
    // does; a region or a country of the gazetteer's stops at 9.
    return {x: cx + near(cx), y: (b.y0 + b.y1) / 2, z: clamp(z, 3, r.deep ? maxZoom() : 9)};
  }
  function pin(lon, lat, text) {
    S.pin = {lon: wrap(lon), lat: clamp(lat, -85, 85), label: text};
    // The composite cell under the pin is outlined in the geometry.
    dirty();
  }
  function go(r) {
    if (!r) return false;
    // The geocoder's row sends the words, and lists what comes back.
    if (r.kind === "search") { geocode(r.q); return true; }
    if (S.then) thenLeave();
    closeList();
    findBox.value = r.label;
    findBox.blur();
    // NASA's imagery stops short of a street: an address opens on the street map.
    if (r.deep && LAYERS[S.layer] && LAYERS[S.layer].kind === "imagery") setLayer("streets");
    hereAt(r.lon, r.lat, r.kind === "town" || r.kind === "point" || r.kind === "address" ? r.label : named(PLACES[r.place]));
    animate(viewFor(r));
    var box = map.getBoundingClientRect();
    if (box.top < 0 || box.bottom > window.innerHeight) map.scrollIntoView({block: "start", behavior: "smooth"});
    return true;
  }
  function closeList() {
    findList.hidden = true; findNote.hidden = true;
    findBox.setAttribute("aria-expanded", "false");
    findBox.removeAttribute("aria-activedescendant");
  }
  function highlight(i) {
    active = i;
    findList.querySelectorAll("[role=option]").forEach(function (li, j) {
      li.setAttribute("aria-selected", j === i ? "true" : "false");
      if (j === i && li.scrollIntoView) li.scrollIntoView({block: "nearest"});
    });
    if (i >= 0) findBox.setAttribute("aria-activedescendant", "find-opt-" + i);
  }
  function showFound() {
    active = found.length ? 0 : -1;
    findList.innerHTML = found.map(function (r, i) {
      return '<li role="option" id="find-opt-' + i + '" data-find="' + i + '" aria-selected="' + (i === 0) + '">' +
        '<span class="findname">' + esc(r.label) + '</span><span class="findsub">' + esc(r.sub) + "</span></li>";
    }).join("");
    findList.hidden = !found.length;
    findBox.setAttribute("aria-expanded", found.length ? "true" : "false");
    if (found.length) findBox.setAttribute("aria-activedescendant", "find-opt-0");
    else findBox.removeAttribute("aria-activedescendant");
  }
  function listFound(text, asked) {
    // New words set aside an answer still on its way for the old ones.
    geocoding++;
    found = find(text);
    // Last, after the gazetteer's own: the offer to ask Esri's geocoder.
    var offer = searchRow(text);
    if (offer) found.push(offer);
    showFound();
    var say = !found.length && (asked || fold(text).length >= 3);
    findNote.hidden = !say;
    findNote.textContent = say ? "Nothing called \u201c" + text.trim() + "\u201d in the desk\u2019s gazetteer of " +
      PLACES.length.toLocaleString("en-US") + " places. Try a town, a region, a country, or a position such as 18.0N 76.8W." : "";
  }
  findBox.addEventListener("input", function () { listFound(findBox.value, false); });
  findBox.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown" && found.length) { highlight(Math.min(active + 1, found.length - 1)); e.preventDefault(); }
    else if (e.key === "ArrowUp" && found.length) { highlight(Math.max(active - 1, 0)); e.preventDefault(); }
    else if (e.key === "Escape") closeList();
  });
  findForm.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!found.length || findList.hidden) listFound(findBox.value, true);
    if (found.length) go(found[Math.max(0, active)]);
  });
  findList.addEventListener("click", function (e) {
    var li = e.target.closest ? e.target.closest("[data-find]") : null;
    if (li) go(found[+li.getAttribute("data-find")]);
  });
  document.addEventListener("pointerdown", function (e) {
    if (!(e.target.closest && e.target.closest("#findform"))) closeList();
  });

  // ---- here: what the storms mean for one point ----------------------------------
  // Read from each storm's own payload: its advisory position, its official
  // forecast hour by hour with the wind radii (the path the exposure table is
  // computed from), its cone, watches and warnings and surge areas, and the
  // outlook. The wind rules are Python's exposure.inside, rule for rule, so a
  // town in a storm's exposure table gets the same times here.
  var COMPASS8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  function within(p, lon, lat, quads) {
    // At the centre is inside, as in Python; a millimetre allows for the
    // longitude having been written about the storm's own meridian.
    var d = km(p.lon, p.lat, lon, lat);
    if (d < 1e-6) return true;
    return d <= quads[Math.floor(bearing(p.lon, p.lat, lon, lat) / 90) % 4] * NM;
  }
  function insideAt(p, lon, lat, t) {
    var r = p.radii || {}, quads = r[t];
    if (quads) return within(p, lon, lat, quads);
    if (p.wind != null && p.wind < +t) return false;
    for (var i = 0; i < THRESHOLDS.length; i++) {
      var o = THRESHOLDS[i], known = r[o];
      if (!known) continue;
      if (+o < +t && !within(p, lon, lat, known)) return false;
      if (+o > +t && within(p, lon, lat, known)) return true;
    }
    return null;
  }
  function frameLon(lon, ref) { return lon + 360 * Math.round((ref - lon) / 360); }
  function inRing(ring, lon, lat) {
    if (!ring || ring.length < 3) return false;
    var x = frameLon(lon, ring[0][0]), inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > lat) !== (yj > lat) && x < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  // Kilometres to the nearest point of a line, on a plane about the point:
  // close enough within the few hundred kilometres it is asked about.
  function toLine(coords, lon, lat) {
    var kx = 111.32 * Math.cos(rad(lat)), ky = 110.57, best = Infinity, prev = null;
    coords.forEach(function (c) {
      var q = [(frameLon(c[0], lon) - lon) * kx, (c[1] - lat) * ky];
      if (prev) {
        var dx = q[0] - prev[0], dy = q[1] - prev[1], L = dx * dx + dy * dy;
        var f = L ? clamp(-(prev[0] * dx + prev[1] * dy) / L, 0, 1) : 0;
        best = Math.min(best, Math.hypot(prev[0] + f * dx, prev[1] + f * dy));
      } else best = Math.hypot(q[0], q[1]);
      prev = q;
    });
    return best;
  }
  function nearestPlace(lon, lat) {
    var best = null;
    for (var i = 0; i < PLACES.length; i++) {
      var p = PLACES[i];
      if (Math.abs(p[5] - lat) > 8) continue;
      if (Math.abs(((p[4] - lon + 540) % 360) - 180) * Math.cos(rad(lat)) > 10) continue;
      var d = km(lon, lat, p[4], p[5]);
      if (!best || d < best.km) best = {km: d, p: p};
    }
    return best;
  }
  function hereFor(lon, lat) {
    lon = wrap(lon);
    var place = nearestPlace(lon, lat), local = place && place.km <= 25 ? place.p : null;
    var out = {lon: lon, lat: lat, place: place ? {name: place.p[0], region: place.p[2], country: place.p[1],
               population: place.p[3], km: place.km} : null, storms: [], areas: []};
    STORMS.forEach(function (st) {
      var s = st.d, fx = s.advisory_fix || {t: s.t, lon: s.lon, lat: s.lat, wind: s.wind};
      var r = {id: s.id, title: s.title, centre: s.centre, advisory: s.advisory, hue: st.hue,
               now: fx.t, now_km: km(fx.lon, fx.lat, lon, lat), bearing: bearing(lon, lat, fx.lon, fx.lat),
               now_wind: fx.wind, closest_km: null, closest: null, closest_wind: null, receding: false,
               arrival: {}, unknown: [], cone: null, watches: [], surge: [], official: null};
      // As far as the exposure table looks: the widest gale radius anywhere
      // on the forecast, plus a degree.
      var line = s.path.filter(function (p) { return p.hour != null && p.hour >= 0; });
      // Without an official forecast there is nothing to say of where it goes
      // or when its wind arrives: the analysed position alone is not one.
      r.forecast = line.some(function (p) { return p.hour > 0; });
      if (!r.forecast) line = [];
      var gale = 0, south = Infinity, north = -Infinity, best = null, unknown = {};
      line.forEach(function (p) {
        var q = (p.radii || {})["34"];
        if (q) gale = Math.max.apply(null, [gale].concat(q));
        south = Math.min(south, p.lat); north = Math.max(north, p.lat);
        var d = km(p.lon, p.lat, lon, lat);
        if (!best || d < best.km) best = {km: d, p: p};
      });
      var reach = gale * NM + 111.2, pad = reach / 111.2;
      r.gale = gale > 0;
      r.reached = lat >= south - pad && lat <= north + pad &&
                  line.some(function (p) { return km(p.lon, p.lat, lon, lat) <= reach; });
      if (r.reached) line.forEach(function (p) {
        THRESHOLDS.forEach(function (t) {
          if (r.arrival[t]) return;
          var got = insideAt(p, lon, lat, t);
          if (got) r.arrival[t] = p.t;
          else if (got === null) unknown[t] = true;
        });
      });
      if (best) {
        r.closest_km = best.km; r.closest = best.p.t; r.closest_wind = best.p.wind;
        r.receding = best.p === line[0];
      }
      r.unknown = THRESHOLDS.filter(function (t) { return unknown[t] && !r.arrival[t]; }).map(Number);
      if (s.cone && s.cone.length > 2) r.cone = inRing(s.cone, lon, lat);
      // A product that could not be fetched is said to be missing, never left
      // to read as nothing in effect.
      r.lost = ["watches", "cone", "surge"].filter(function (k) { return (s.products || {})[k] === "unavailable"; });
      r.in_effect = s.in_effect || {};
      var byKind = {};
      (s.watches || []).forEach(function (w) {
        var d = toLine(w.coords, lon, lat);
        if (!(w.kind in byKind) || d < byKind[w.kind]) byKind[w.kind] = d;
      });
      ORDER.slice().reverse().concat(Object.keys(byKind).filter(function (k) { return ORDER.indexOf(k) < 0; }))
        .forEach(function (kind) { if (kind in byKind && byKind[kind] <= 300) r.watches.push({kind: kind, km: byKind[kind]}); });
      (s.surge || []).forEach(function (a) { if (inRing(a.ring, lon, lat)) r.surge.push({label: a.label, feet: a.feet}); });
      // The centre's own chances, where its product names the town the point is in.
      if (local && s.winds && s.winds.rows) {
        var name = fold(local[0]), got = {};
        s.winds.rows.forEach(function (row) { if (fold(row.place) === name) got[row.threshold] = row.total; });
        if (Object.keys(got).length) r.official = {place: local[0], chances: got,
          hours: s.winds.hours && s.winds.hours.length ? s.winds.hours[s.winds.hours.length - 1] : null,
          advisory: s.winds.advisory, issued: s.winds.issued};
      }
      out.storms.push(r);
    });
    out.storms.sort(function (a, b) { return (a.closest_km == null ? 1e9 : a.closest_km) - (b.closest_km == null ? 1e9 : b.closest_km); });
    D.outlook.forEach(function (a) {
      var polygon = a.area && a.area.length > 2, inside = polygon && inRing(a.area, lon, lat);
      var d = inside ? 0 : polygon ? toLine(a.area, lon, lat) : km(a.lon, a.lat, lon, lat);
      if (inside || d <= (polygon ? 300 : 600)) out.areas.push({key: a.key, centre: a.centre, label: a.label,
        inside: !!inside, km: d, polygon: !!polygon, chance_2day: a.chance_2day, chance_7day: a.chance_7day,
        potential: a.potential, alert: a.alert, until: a.formation ? a.formation.until : ""});
    });
    return out;
  }
  function soon(t) {
    var h = Math.round((Date.parse(t) - Date.now()) / HOUR);
    return h > 0 ? "in about " + h + " h" : h === 0 ? "about now" : -h + " h ago";
  }
  function kms(v) { return Math.round(v).toLocaleString("en-US") + " km"; }
  // A storm Here speaks of: its forecast comes within 1,500 km of the point,
  // or with no forecast it is that close now, or the point is under a watch
  // or in the surge.
  function nearHere(r) {
    var d = r.forecast ? r.closest_km : r.now_km;
    return d != null && d <= 1500 || r.surge.length > 0 || r.watches.length > 0;
  }
  function stormHere(r) {
    var lines = [], near = r.closest_km != null && r.closest_km <= 1500;
    var LOST = {watches: "The watches and warnings could not be fetched this run; read the advisory.",
                cone: "The forecast cone could not be fetched this run; read the advisory.",
                surge: "The peak storm surge forecast could not be fetched this run; read the advisory."};
    lines.push("At " + utc(Date.parse(r.now)) + " (advisory " + esc(r.advisory) + ") " + esc(r.title) + " was " +
               kms(r.now_km) + " " + COMPASS8[Math.round(r.bearing / 45) % 8] + " of here" +
               (r.now_wind != null ? ", " + r.now_wind + " kt." : "."));
    if (!r.forecast) lines.push("No official forecast this run, so how close it comes and when its wind " +
                                "would reach here are not known; read the advisory.");
    if (r.closest != null) lines.push(r.receding ? "Its official forecast takes it no closer than that."
      : "On the official forecast it comes closest at " + utc(Date.parse(r.closest)) + " (" + soon(r.closest) + "), " +
        kms(r.closest_km) + " away" + (r.closest_wind != null ? ", forecast " + r.closest_wind + " kt." : "."));
    var reach = THRESHOLDS.map(function (t) {
      if (r.arrival[t]) return t + " kt from " + utc(Date.parse(r.arrival[t])) + " (" + soon(r.arrival[t]) + ")";
      if (r.unknown.indexOf(+t) >= 0) return t + " kt not forecast";
      return t + " kt does not reach here";
    });
    if (r.arrival["34"] || r.unknown.length) lines.push("Wind here on that forecast: " + reach.join("; ") + ".");
    else if (near) lines.push(r.gale ? "Its forecast gale radius does not reach here."
      : r.reached ? "Its forecast keeps it below gale force, 34 kt."
      : "Its forecast gives no gale radius; the exposure table looks a degree either side " +
        "of its track, and here is further.");
    if (r.cone !== null && near) lines.push(r.cone ? "Inside the forecast cone." : "Outside the forecast cone.");
    r.watches.forEach(function (w) {
      lines.push('<span class="linekey" style="background:' + (D.style.products[w.kind] || "var(--ink)") + '"></span>' +
                 "Nearest coast under a " + esc(w.kind) + ": " + kms(w.km) + ".");
    });
    r.surge.forEach(function (a) { lines.push("Inside the peak storm surge area \u201c" + esc(a.label) + "\u201d: " + esc(a.feet) + "."); });
    r.lost.forEach(function (k) {
      var said = Object.keys(r.in_effect);
      lines.push(k === "watches" && said.length
        ? "The lines of the watches and warnings could not be fetched this run; the public advisory has in effect: " +
          said.map(function (kind) { return esc(kind) + " for " + esc(r.in_effect[kind].join("; ")); }).join("; ") + "."
        : LOST[k]);
    });
    if (r.official) {
      var c = r.official.chances;
      lines.push(esc(r.centre) + "\u2019s own chance at " + esc(r.official.place.toUpperCase()) +
                 (r.official.hours ? " within " + r.official.hours + " h" : "") + ": " +
                 THRESHOLDS.map(function (t) { return t + " kt " + (c[t] == null ? "not listed" : c[t] === 0 ? "<1%" : c[t] + "%"); }).join(", ") + ".");
    }
    return '<li><b><span class="swatch" style="background:' + r.hue + '"></span>' + esc(r.title) + "</b> " +
           '<span class="muted">' + esc(r.centre) + "</span>" +
           lines.map(function (l) { return "<p>" + l + "</p>"; }).join("") + "</li>";
  }
  function showHere() {
    var box = $("here");
    if (!box) return;
    if (!S.here) {
      box.hidden = true; box.innerHTML = ""; $("herego").hidden = true; S.google = null;
      hereSay("");
      return;
    }
    var h = hereFor(S.here.lon, S.here.lat), html = [], place = h.place;
    html.push('<h2 class="panelhead" id="here-title">Here: ' + esc(S.here.label) + "</h2>");
    var facts = [where(h.lon, h.lat)];
    if (place && place.km <= 25 && place.population) facts.push(peopleFact(S.here.label, place));
    else if (place && place.km <= 400) facts.push(kms(place.km) + " from " + esc(place.name));
    html.push('<p class="herewhere">' + facts.join(" \u00b7 ") + "</p>");
    html.push('<div class="herebtns"><button type="button" class="toolbtn" data-here="show">Show on map</button>' +
              '<button type="button" class="toolbtn" data-here="enter">Enter here</button>' +
              '<button type="button" class="toolbtn" data-here="clear">Clear</button></div>');
    var near = h.storms.filter(nearHere);
    var far = h.storms.filter(function (r) { return near.indexOf(r) < 0; });
    html.push("<h4>Live storms</h4>");
    if (!h.storms.length) html.push("<p>No live tropical cyclones.</p>");
    if (near.length) html.push('<ul class="herestorms">' + near.map(stormHere).join("") + "</ul>");
    else if (h.storms.length) html.push("<p>No live storm\u2019s official forecast comes within 1,500 km of here.</p>");
    if (far.length) html.push("<p>Further away, closest on their forecasts: " + far.map(function (r) {
      return esc(r.title) + " " + (r.closest_km == null ? "no forecast" : kms(r.closest_km));
    }).join(", ") + ".</p>");
    html.push("<h4>Formation outlook</h4>");
    if (!h.areas.length) html.push("<p>No area the warning centres are watching for formation is near here.</p>");
    h.areas.forEach(function (a) {
      var chance = a.centre === "JTWC" ? (a.potential || "unrated") + " potential in 24 h" + (a.alert ? ", " + alertHtml(a.until) : "")
                 : pct(a.chance_2day) + " in 2 days, " + pct(a.chance_7day) + " in 7 days";
      html.push("<p>" + (a.inside ? "Inside " : kms(a.km) + " from ") + esc(a.centre) + "\u2019s " +
                (a.centre !== "JTWC" ? "formation area " : a.polygon ? "formation alert area " : "") + "\u201c" + esc(a.label) + "\u201d: " + chance + ".</p>");
    });
    html.push("<h4>Who warns here</h4>");
    html.push("<p>" + (place && place.km <= 400 && place.country
      ? "Warnings for " + esc(place.country) + "\u2019s coast come from its national meteorological service. "
      : "Out at sea, far from any named place. ") +
      "Each storm\u2019s advisories come from the centre named beside it.</p>");
    html.push(ensoHereHtml(ensoHere(h.lon, h.lat)));
    html.push(ensoTodayHtml(S.here.lon, S.here.lat));
    html.push(googleHtml(h.lat, h.lon, S.z));
    html.push('<p><a href="atlas.html#at=' + h.lat.toFixed(2) + "," + h.lon.toFixed(2) + '">What El Ni\u00f1o usually does here, season by season &rarr;</a></p>');
    html.push('<p class="method">' + esc(D.methods.here || "") + "</p>");
    hereWrite(box, html.join(""));
    box.hidden = false;
    hereSay("Here: " + S.here.label);
    ensoTodayRead(S.here.lon, S.here.lat);
    var go2 = $("herego");
    go2.textContent = S.here.label.split(", ")[0] + (D.focus === "world" ? ": El Ni\u00f1o here \u2193" : ": what the storms mean here \u2193");
    go2.hidden = false;
  }
  // Here written anew, as the reader left it: its tables open or shut, and
  // the focus on its control (retake). Google's frame open on this point is
  // left where it is, never loaded again, so the place the reader has gone to
  // in it (Street View walked on, Google's map moved) stays; a frame of
  // another point closes.
  function hereWrite(box, html) {
    var frame = S.google && S.google.lon === S.here.lon && S.google.lat === S.here.lat ? $("google-frame") : null;
    retake(box, html, frame);
    if (frame) googlePressed(S.google.kind);
    else S.google = null;
  }
  // Which place Here is on, said by the line kept for it outside the panel:
  // written only when that changes, so Here written anew (each take writes
  // it) is not read out again.
  function hereSay(words) {
    var line = $("here-said");
    if (line && line.textContent !== words) line.textContent = words;
  }
  // A point named: the town it is in, the distance from the nearest, or its
  // latitude and longitude. Here's name for it, and an entered place's.
  function placeLabel(lon, lat) {
    var p = nearestPlace(lon, lat);
    return p && p.km <= 25 ? named(p.p) : p && p.km <= 400 ? kms(p.km) + " from " + named(p.p) : where(lon, lat);
  }
  function hereAt(lon, lat, label) {
    lon = wrap(lon); lat = clamp(lat, -85, 85);
    if (!label) label = placeLabel(lon, lat);
    S.here = {lon: lon, lat: lat, label: label};
    pin(lon, lat, label);
    showHere();
    var panel = $("panel");
    if (panel && window.matchMedia && window.matchMedia("(min-width: 900px)").matches) panel.scrollTop = 0;
  }
  function clearHere() { S.here = null; if (!S.then) S.pin = null; showHere(); requestRender(); }

  // ---- touch, mouse and keys ------------------------------------------------------
  var pointers = new Map(), gesture = null, lastTap = null, wheelTimer = 0, dragging = false, tapTimer = 0;
  function local(e) { var r = map.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; }
  function begin() {
    var pts = Array.from(pointers.values());
    if (!pts.length) return null;
    var g = {multi: pts.length > 1 || !!(gesture && gesture.multi)};
    if (pts.length === 1) g.a = toWorld(pts[0].x, pts[0].y);
    else {
      var m = {x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2};
      g.a = toWorld(m.x, m.y); g.z0 = S.z;
      g.d0 = Math.max(1, Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y));
    }
    return g;
  }
  map.addEventListener("pointerdown", function (e) {
    if (e.target.closest && e.target.closest(".ui")) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    // A synthetic pointer has nothing to capture; the gesture works without it.
    try { map.setPointerCapture(e.pointerId); } catch (err) { /* nothing to capture */ }
    var p = local(e);
    pointers.set(e.pointerId, {x: p.x, y: p.y, x0: p.x, y0: p.y, t0: e.timeStamp, target: e.target});
    cancelAnimationFrame(anim); anim = 0;
    gesture = begin();
    map.classList.add("dragging");
  });
  map.addEventListener("pointermove", function (e) {
    var q = pointers.get(e.pointerId);
    if (!q || !gesture) return;
    var p = local(e);
    q.x = p.x; q.y = p.y;
    var pts = Array.from(pointers.values()), W;
    if (pointers.size === 1) {
      W = world();
      S.x = gesture.a.x - (q.x - S.w / 2) / W; S.y = gesture.a.y - (q.y - S.h / 2) / W;
    } else {
      // Two fingers: the zoom follows their spread, about their midpoint.
      var d = Math.max(1, Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y));
      var m = {x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2};
      S.z = clamp(gesture.z0 + Math.log(d / gesture.d0) / Math.LN2, MINZ, maxZoom());
      W = world();
      S.x = gesture.a.x - (m.x - S.w / 2) / W; S.y = gesture.a.y - (m.y - S.h / 2) / W;
    }
    requestRender();
  });
  function tap(q, time) {
    clearTimeout(tapTimer);
    if (S.arming) { var w = toWorld(q.x, q.y); arm(false); thenEnter(lonOf(w.x), latOf(w.y)); return; }
    if (lastTap && time - lastTap.t < 320 && Math.hypot(q.x - lastTap.x, q.y - lastTap.y) < 30) {
      lastTap = null;
      zoomBy(1, q.x, q.y);
      return;
    }
    lastTap = {t: time, x: q.x, y: q.y};
    var hit = q.target && q.target.closest ? q.target.closest("[data-storm],[data-area]") : null;
    if (!hit) {
      // Anywhere else is a place to ask about, once it is clear the tap is
      // not the first of a double tap.
      var a = toWorld(q.x, q.y);
      tapTimer = setTimeout(function () {
        if (S.then) thenMove(lonOf(a.x), latOf(a.y)); else hereAt(lonOf(a.x), latOf(a.y));
      }, 330);
      return;
    }
    if (hit.getAttribute("data-storm")) flyTo(hit.getAttribute("data-storm"));
    else flyToArea(hit.getAttribute("data-area"));
  }
  function release(e) {
    var q = pointers.get(e.pointerId);
    if (!q) return;
    pointers.delete(e.pointerId);
    var multi = gesture && gesture.multi;
    if (e.type === "pointerup" && !pointers.size && !multi &&
        Math.hypot(q.x - q.x0, q.y - q.y0) < 10 && e.timeStamp - q.t0 < 600) tap(q, e.timeStamp);
    gesture = pointers.size ? begin() : null;
    if (gesture && multi) gesture.multi = true;
    if (!pointers.size) { map.classList.remove("dragging"); settle(); }
  }
  map.addEventListener("pointerup", release);
  map.addEventListener("pointercancel", release);
  map.addEventListener("wheel", function (e) {
    e.preventDefault();
    var p = local(e), a = toWorld(p.x, p.y);
    var dz = -e.deltaY * (e.deltaMode === 1 ? 0.05 : e.deltaMode === 2 ? 1 : 0.002);
    S.z = clamp(S.z + clamp(dz, -1, 1), MINZ, maxZoom());
    var W = world();
    S.x = a.x - (p.x - S.w / 2) / W; S.y = a.y - (p.y - S.h / 2) / W;
    requestRender();
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(settle, 200);
  }, {passive: false});
  map.addEventListener("keydown", function (e) {
    if (e.target !== map) return;
    var step = 80 / world(), done = true;
    if (e.key === "ArrowLeft") S.x -= step;
    else if (e.key === "ArrowRight") S.x += step;
    else if (e.key === "ArrowUp") S.y -= step;
    else if (e.key === "ArrowDown") S.y += step;
    else if (e.key === "+" || e.key === "=") { zoomBy(1); return e.preventDefault(); }
    else if (e.key === "-" || e.key === "_") { zoomBy(-1); return e.preventDefault(); }
    else done = false;
    if (done) { e.preventDefault(); settle(); }
  });
  divider.addEventListener("pointerdown", function (e) {
    dragging = true;
    try { divider.setPointerCapture(e.pointerId); } catch (err) { /* synthetic */ }
    e.stopPropagation();
  });
  divider.addEventListener("pointermove", function (e) {
    if (!dragging) return;
    S.split = clamp(local(e).x / S.w, 0.05, 0.95);
    divider.setAttribute("aria-valuenow", String(Math.round(S.split * 100)));
    requestRender();
  });
  function stopDrag() { dragging = false; }
  divider.addEventListener("pointerup", stopDrag);
  divider.addEventListener("pointercancel", stopDrag);
  divider.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    S.split = clamp(S.split + (e.key === "ArrowLeft" ? -0.05 : 0.05), 0.05, 0.95);
    divider.setAttribute("aria-valuenow", String(Math.round(S.split * 100)));
    e.preventDefault();
    requestRender();
  });
  document.querySelectorAll("[data-layer]").forEach(function (b) {
    b.addEventListener("click", function () { pressLayer(b.getAttribute("data-layer")); });
  });
  document.querySelectorAll("[data-show],[data-ref]").forEach(function (box) {
    box.addEventListener("change", function () { readToggles(); dirty(); });
  });
  document.querySelectorAll("[data-zoom]").forEach(function (b) {
    b.addEventListener("click", function () { zoomBy(+b.getAttribute("data-zoom")); });
  });
  document.querySelectorAll("[data-fit]").forEach(function (b) {
    b.addEventListener("click", function () { fit(false); });
  });
  $("compare").addEventListener("click", pressCompare);
  $("day-earlier").addEventListener("click", function () { findDay(-1); });
  $("day-later").addEventListener("click", function () { findDay(1); });
  $("compare-layer").addEventListener("change", function (e) {
    if (S.then) thenLeave();
    S.second = e.target.value;
    if (S.second === "detail") { S.dayStepped = false; dayAt = ""; }
    if (S.second === S.layer) setLayer(S.layer === "infrared" ? "geocolor" : "infrared");
    dirty();
  });
  $("swap").addEventListener("click", function () {
    if (S.then) thenLeave();
    var top = S.layer, under = S.second;
    S.second = top;
    setLayer(under);
    $("compare-layer").value = S.second;
  });
  $("loop").addEventListener("click", function () { setLoop(!S.loop); });
  scrub.addEventListener("input", function () { S.scrub = +scrub.value; dirty(); });
  framePill.addEventListener("click", function () {
    var had = document.activeElement && document.activeElement.classList.contains("pillmore");
    pillOpen = !pillOpen;
    pills();
    if (had && framePill.querySelector(".pillmore")) framePill.querySelector(".pillmore").focus();
  });
  var root = document.documentElement, themeBtn = $("theme");
  function darkNow() {
    var t = root.getAttribute("data-theme");
    return t ? t === "dark" : !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }
  function themeLabel() { themeBtn.textContent = darkNow() ? "Light" : "Dark"; }
  themeBtn.addEventListener("click", function () { root.setAttribute("data-theme", darkNow() ? "light" : "dark"); themeLabel(); });
  document.addEventListener("click", function (e) {
    var el = e.target.closest ? e.target.closest("[data-fly],[data-select],[data-tab],[data-here],[data-google],[data-show-region],#retry,#herego") : null;
    if (!el) return;
    if (el.hasAttribute("data-show-region")) { showRegion(el.getAttribute("data-show-region")); return; }
    if (el.hasAttribute("data-google")) { googleFrame(el.getAttribute("data-google")); return; }
    if (el.id === "herego") { var hb = $("here"); if (hb && !hb.hidden) hb.scrollIntoView({block: "start"}); return; }
    if (el.hasAttribute("data-here")) {
      if (el.getAttribute("data-here") === "clear") clearHere();
      else if (el.getAttribute("data-here") === "enter") { if (S.here) thenEnter(S.here.lon, S.here.lat, S.here.label); }
      else if (S.here) {
        map.scrollIntoView({block: "nearest"});
        animate({x: mx(S.here.lon) + near(mx(S.here.lon)), y: my(S.here.lat), z: Math.max(S.z, 9)});
      }
      return;
    }
    if (el.id === "retry") { retry(); return; }
    if (el.hasAttribute("data-fly")) { flyTo(el.getAttribute("data-fly")); return; }
    if (el.hasAttribute("data-select")) { select(el.getAttribute("data-select")); return; }
    var sec = el.closest("section.storm");
    if (sec) tab(sec, el.getAttribute("data-tab"));
  });

  // ---- a run taken where the reader is ---------------------------------------
  // A box written anew around one node of it, which is left where it is: the
  // new markup's node of the same id marks its place. A frame taken out of
  // the page loads again, so Google's frame, and Here, which holds it, never
  // are. Without that node, or with one that is not the box's, the box is
  // written whole.
  function writeAround(box, html, keep) {
    if (!keep || keep.parentNode !== box) { box.innerHTML = html; return; }
    var fresh = document.createElement("div"), before = true;
    fresh.innerHTML = html;
    Array.prototype.slice.call(box.childNodes).forEach(function (n) { if (n !== keep) box.removeChild(n); });
    Array.prototype.slice.call(fresh.childNodes).forEach(function (n) {
      if (n.id === keep.id) before = false;
      else box.insertBefore(n, before ? keep : null);
    });
  }
  // A new run's markup put in a box as the reader left it: each storm on the
  // tab it showed, each <details> open or shut as it was, and the focus on
  // the control it was on, each found again by knownAs(). The node kept
  // (Here) keeps its own.
  function retake(box, html, keep) {
    var tabs = shownTabs(box), open = {}, on = document.activeElement;
    var focus = on && on !== box && box.contains(on) && !(keep && keep.contains(on)) ? knownAs(on) : "";
    box.querySelectorAll("details").forEach(function (d) { open[knownAs(d)] = d.open; });
    writeAround(box, html, keep);
    box.querySelectorAll("section.storm").forEach(function (sec) { tab(sec, tabs[sec.id] || "now"); });
    box.querySelectorAll("details").forEach(function (d) {
      var k = knownAs(d);
      if (k in open) d.open = open[k];
    });
    if (!focus) return;
    var again = box.querySelectorAll("a[href], button, summary, input, select");
    for (var i = 0; i < again.length; i++) {
      if (knownAs(again[i]) === focus) { again[i].focus({preventScroll: true}); return; }
    }
  }
  // Each storm's tab as the reader left it, by its section's id.
  function shownTabs(root) {
    var tabs = {};
    root.querySelectorAll("section.storm").forEach(function (sec) {
      var on = sec.querySelector('[data-tab][aria-selected="true"]');
      if (on) tabs[sec.id] = on.getAttribute("data-tab");
    });
    return tabs;
  }
  // A control, or a <details> by its summary, known by what it is and not by
  // where it stands: its section, then its id, address and data-* actions,
  // or its words where it has none (a summary's, as live.py finds a section
  // across a load).
  function knownAs(el) {
    var sec = el.closest("section[id]"), named = el.tagName === "DETAILS" ? el.querySelector("summary") : el;
    if (!named) return "";
    var says = Array.prototype.filter.call(named.attributes, function (a) {
      return a.name === "id" || a.name === "href" || a.name.slice(0, 5) === "data-";
    }).map(function (a) { return a.name + "=" + a.value; });
    return (sec ? sec.id : "") + "|" + named.tagName + "|" + (says.length ? says.join(" ") : named.textContent.trim());
  }

  // ---- keeping current -----------------------------------------------------------
  // A new run is read from the page itself, map data and panel together, and
  // the view is left where it is. Served, the page asks the site each minute
  // which run it serves (elninoLive, in live.py) and comes here only for a run
  // it does not show; the promise says when the page has taken it, and the
  // page then names the run in its head. A run another code wrote is not this
  // script's to read: the promise says false, and the follower loads the page
  // again for it, the reader's place handed across (keepPlace, below). A copy
  // no newer than the page's own run (a CDN's edge can still serve an older
  // one) is passed over, and the follower goes for the run again after a pause.
  function refresh() {
    return siteCopy().then(function (copy) {
      if (copy === false) return false;
      if (copy && newer(copy.data.built, D.built)) return takeRun(copy.doc, copy.data);
    });
  }
  // The site's copy of this page and its data, read: false when another code
  // wrote it; null when it could not be had or read.
  function siteCopy() {
    return fetch(location.href.split("#")[0], {cache: "no-store"}).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.text();
    }).then(function (text) {
      var doc = new DOMParser().parseFromString(text, "text/html");
      if (!elninoLive.sameCode(doc)) return false;
      var node = doc.getElementById("desk-data");
      return node ? {doc: doc, data: JSON.parse(node.textContent)} : null;
    }).catch(function () { return null; });
  }
  // Whether one run is later than another, however each is written.
  function newer(a, b) { return Date.parse(a) > Date.parse(b); }
  // The new run taken where the reader is, the place in the panel and the key
  // held by the follower (elninoLive.hold). A take that fails part way leaves
  // the page between two runs: it throws once the place is put back, and the
  // follower loads the page for the run.
  function takeRun(doc, next) {
    var panel = doc.getElementById("panel"), legend = doc.getElementById("legend");
    var stamp = doc.getElementById("built");
    var putPlaceBack = elninoLive.hold();
    try {
      D = next;
      // The panel and the key as the reader left them. Here is the page's own:
      // showHere, below, writes it from the new run around Google's frame.
      if (panel) retake($("panel"), panel.innerHTML, $("here"));
      // The header's stamp is the new run's, as the panel's is.
      if (stamp) $("built").innerHTML = stamp.innerHTML;
      // The legend comes back empty, so the El Nino key is written again.
      if (legend) { retake($("legend"), legend.innerHTML); ensoSaid = ""; }
      // The regions' Show in the new panel, pressed as the reader left them.
      ensoControls();
      prepare();
      thenRefreshed(doc);
      if (S.then) thenApply();
      coastDone = 0; coastD = ""; coastG.innerHTML = "";
      select(BYID[S.selected] ? S.selected : (STORMS[0] ? STORMS[0].id : null));
      showHere();
      ages();
      // Drawn now, keys and all, so the reader's place is put back on the page
      // as it will stand.
      geoDirty = true;
      render();
    } finally {
      putPlaceBack();
    }
    elninoLive.shows(doc);
  }

  // ---- a run loaded where the reader was ------------------------------------------
  // A run the page cannot take in place is loaded, and the reader's place
  // handed across: the view; the layers, the comparison, the divider and the
  // loop as the map's own (Exit's, while a place is entered); the hour scrubbed to,
  // the day stepped to, the overlays and El Nino's map; Here, and Google's
  // frame in it; the place entered, on its event or its dates; the storm
  // chosen and each storm's tab. The follower keeps the panel's scroll, its
  // tables open or shut and the theme.
  function keepPlace() {
    var T = S.then, layers = T ? T.back : S;
    return {view: {lon: wrap(lonOf(S.x)), lat: latOf(S.y), z: S.z},
            layer: layers.layer, second: layers.second, compare: layers.compare, split: layers.split,
            loop: layers.loop, scrub: S.scrub, day: S.dayStepped ? S.day : null,
            show: S.show, refs: S.refs, enso: S.enso,
            here: S.here, google: S.google ? S.google.kind : null,
            then: T ? {lon: T.lon, lat: T.lat, label: T.label, source: T.source, preset: T.preset,
                       a: sideDay(T, "a"), b: sideDay(T, "b"), names: T.names, split: S.split} : null,
            storm: S.selected, tabs: shownTabs($("panel"))};
  }
  // The place handed across, put back over the page as it opened. It is
  // read like input, and only what is this page's own is put back: a layer
  // it draws, a storm it shows, a region it names, a day that is one. A
  // place the reader had left stays left, though the address opened on it.
  function restorePlace(k) {
    function point(p) { return !!p && typeof p === "object" && finite(p.lon) && finite(p.lat) && Math.abs(p.lat) <= 90; }
    // Leaving the place the address opened on strips the address of it: the
    // place entered again, the address is put back as it was.
    var address = /^#then=/.test(location.hash) ? location.href : null;
    if (S.then) thenLeave();
    if (drawable(k.layer)) setLayer(k.layer);
    if (drawable(k.second) && k.second !== S.layer) { S.second = k.second; $("compare-layer").value = S.second; }
    if (typeof k.compare === "boolean") setCompare(k.compare);
    if (finite(k.split)) thenSplit(clamp(k.split, 0.05, 0.95));
    if (finite(k.scrub)) { scrub.value = k.scrub; S.scrub = +scrub.value; }
    if (realDay(k.day)) { S.day = k.day; S.dayStepped = true; }
    ticked(k.show, "data-show");
    ticked(k.refs, "data-ref");
    readToggles();
    var enso = ensoKept(k.enso);
    if (Object.keys(enso).length) setEnso(enso);
    if (own(BYID, k.storm)) select(k.storm);
    var tabs = k.tabs && typeof k.tabs === "object" ? k.tabs : {};
    $("panel").querySelectorAll("section.storm").forEach(function (sec) {
      var name = own(tabs, sec.id) ? tabs[sec.id] : null;
      if (Array.prototype.some.call(sec.querySelectorAll("[data-tab]"), function (b) {
        return b.getAttribute("data-tab") === name;
      })) tab(sec, name);
    });
    // The view before Here, so Google's map opens at the reader's zoom, and
    // again last, over the flight into a place entered.
    var h = k.here, t = k.then, v = k.view;
    var seen = !!v && typeof v === "object" && finite(v.lon) && finite(v.lat) && finite(v.z);
    function look() {
      cancelAnimationFrame(anim); anim = 0;
      S.x = mx(wrap(v.lon)); S.y = my(clamp(v.lat, -85, 85)); S.z = clamp(v.z, MINZ, maxZoom());
    }
    if (seen) look();
    if (point(h)) {
      hereAt(h.lon, h.lat, typeof h.label === "string" ? h.label : "");
      if (k.google === "map" || k.google === "satellite" || k.google === "street") googleFrame(k.google);
    } else if (h === null && S.here) clearHere();
    if (point(t) && thenSrc(t.source)) {
      thenEnter(t.lon, t.lat, typeof t.label === "string" && t.label ? t.label : null,
                {source: t.source, preset: t.preset, a: t.a, b: t.b, names: t.names, instant: true});
      if (finite(t.split)) thenSplit(clamp(t.split, 0.05, 0.95));
    }
    // A loop runs over frames GIBS has yet to give: on Exit, while a place is
    // entered, and else once they are in view (loopWhenKnown).
    if (k.loop === true) {
      if (S.then) S.then.back.loop = true;
      else S.loopWanted = true;
    }
    if (seen) { look(); settle(); }
    if (address && S.then) {
      try { history.replaceState(null, "", address); } catch (err) { /* the address stays without it */ }
    }
  }
  // A layer the map can show, as its base or beside it: one of its maps, or
  // NASA's imagery; not a side of then and now.
  function drawable(id) {
    var l = own(LAYERS, id) ? LAYERS[id] : null;
    return !!l && (l.kind === "map" || l.kind === "imagery") && !l.then;
  }
  // The Overlays menu's boxes of one kind, ticked as they were kept, each by
  // its name; a name the page no longer has is passed over.
  function ticked(kept, attr) {
    if (!kept || typeof kept !== "object") return;
    document.querySelectorAll("[" + attr + "]").forEach(function (box) {
      var name = box.getAttribute(attr);
      if (own(kept, name) && typeof kept[name] === "boolean") box.checked = kept[name];
    });
  }
  // El Nino's map as it was kept, as a change of what this page has: a
  // variable it draws (or none), a season it has, its switches, strengths
  // from 0 to 1, each of NASA's layers it offers, a region it names.
  function ensoKept(e) {
    var patch = {};
    if (!e || typeof e !== "object") return patch;
    if (e.variable === null || own(D.enso.grids, e.variable)) patch.variable = e.variable;
    if (own(D.enso.season_label, e.season)) patch.season = e.season;
    ["mask", "regions", "boxes"].forEach(function (key) { if (typeof e[key] === "boolean") patch[key] = e[key]; });
    ["opacity", "tileOpacity"].forEach(function (key) { if (finite(e[key])) patch[key] = clamp(e[key], 0, 1); });
    if (e.tiles && typeof e.tiles === "object") {
      patch.tiles = {};
      ensoTileLayers().forEach(function (l) { patch.tiles[l.id] = own(e.tiles, l.id) && e.tiles[l.id] === true; });
    }
    if (e.shown === null || (D.enso.links || []).some(function (l) { return l.region === e.shown; })) patch.shown = e.shown;
    return patch;
  }
  window.addEventListener("offline", function () { S.imagery = "offline"; dirty(); });
  window.addEventListener("online", function () {
    forgetMaps();
    if (S.imagery === "ok") { dirty(); return; }
    askGibsAgain(); dirty();
  });
  if (window.ResizeObserver) new ResizeObserver(function () { measure(); dirty(); }).observe(map);
  else window.addEventListener("resize", function () { measure(); dirty(); });

  /*WORLDMAP*/
  /*THENNOW*/
  // ---- start ------------------------------------------------------------------
  prepare();
  unserved();
  readToggles();
  measure();
  themeLabel();
  document.querySelectorAll("#panel section.storm").forEach(function (sec) { tab(sec, "now"); });
  if (STORMS.length) select(STORMS[0].id);
  // The page's first layer is the one its toolbar shows pressed: the street
  // map on map.html, GeoColor on storms.html. A place or a view in the
  // address comes before the page's own opening view.
  var firstLayer = document.querySelector('.desktools [data-layer][aria-pressed="true"]');
  if (firstLayer) setLayer(firstLayer.getAttribute("data-layer"));
  if (!applyHash(location.hash)) { if (D.focus === "world") planet(); else fit(true); }
  window.addEventListener("hashchange", function () { applyHash(location.hash); });
  if (S.imagery === "pending" && !Object.keys(DOM).length) ask(source("geocolor", "GOES-East"));
  ages();
  setInterval(ages, 60000);
  // GIBS adds a geostationary frame every ten minutes.
  setInterval(function () {
    if (S.imagery !== "ok") return;
    for (var k in DOM) DOM[k].stale = true;
    dirty();
  }, 600000);
  // A new run is taken in place while the page is open (see refresh); one it
  // cannot take is loaded, the reader's place handed across (see keepPlace).
  elninoLive.follow({take: refresh, keep: keepPlace, restore: restorePlace,
                     boxes: ["panel", "legend"]});

  window.stormDesk = {
    flyTo: function (id) { return flyTo(id); },
    setLayer: function (id) { return setLayer(id); },
    enso: function (patch) { return setEnso(patch || {}); },
    compare: function (on) { return setCompare(on); },
    loop: function (on) { return setLoop(on); },
    scrub: function (hours) { scrub.value = hours; S.scrub = +scrub.value; dirty(); return S.scrub; },
    find: function (text) {
      return find(text).map(function (r) { return {kind: r.kind, label: r.label, lon: r.lon, lat: r.lat, zoom: r.zoom}; });
    },
    go: function (text) { var r = find(text); return r.length ? go(r[0]) : false; },
    here: function (lon, lat, open) { if (open) hereAt(lon, lat); return hereFor(lon, lat); },
    enter: function (lon, lat, opts) { return thenEnter(lon, lat, null, opts || {}); },
    leave: function () { return thenLeave(); },
    view: function () {
      var st = BYID[S.selected], b = st ? base(st) : null;
      return {lon: wrap(lonOf(S.x)), lat: latOf(S.y), zoom: S.z, layer: S.layer,
              compare: S.compare, second: S.second, split: S.split, loop: S.loop,
              frame: S.frame, frames: loopLength(), scrub: S.scrub, selected: S.selected,
              imagery: S.imagery, imageTime: b && b.image ? isoZ(b.t) : null,
              sources: Object.keys(S.inView).filter(function (k) { return k !== "none"; }),
              tiles: document.querySelectorAll("#tiles img").length, pin: S.pin,
              day: S.day, dayState: S.dayState, then: thenView()};
    }
  };
})();
"""
