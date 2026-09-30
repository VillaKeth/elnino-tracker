"""Who the wind reaches, when; and where the eye is on the satellite picture.

Exposure. The official forecast gives, at each forecast point, how far
34, 50 and 64 kt winds extend in each quadrant. Stepped hour by hour along
the track - position, wind and every quadrant radius interpolated between
the points - that says when each threshold first reaches each place, which
is the time a person has to act by. Three rules keep it honest:

* A radius the forecast does not give is not zero. NHC stops forecasting
  the 64-kt radius after 72 h; a hurricane at 96 h with no 64-kt radius is
  "not forecast" at a place, never "no hurricane-force wind".
* Stronger winds lie inside weaker ones. A place outside the forecast
  34-kt radius is outside the 64-kt field whether or not that was
  forecast, and inside a forecast 64-kt radius is inside the 50-kt field.
* The analysis starts the line only if the forecast is counted from it;
  a forecast from another cycle would put the two on different clocks.

The quadrant radius is the extent of that wind anywhere in the quadrant,
so a place is in the wind if it is within that distance in its quadrant:
the conservative reading, and the one NHC's own graphics draw.

Viewing geometry. A geostationary imager sees a hurricane's cloud tops,
15 km up, displaced away from the sub-satellite point by h tan z, where z
is the local zenith angle of the satellite: 12 km for a storm off Mexico
seen from GOES-West, 28 km for one off Cabo Verde seen from GOES-East. An
eye is 20 to 60 km across, so the displacement is drawn rather than
ignored, and the satellite with the smallest zenith angle is the one to
look through.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace

from . import atlasdata
from .cyclones import Fix, great_circle, valid_stamp

NM_KM = 1.852
THRESHOLDS = (34, 50, 64)

EARTH_RADIUS_KM = 6378.137          # equatorial, as the geometry is at the equator
GEOSTATIONARY_KM = 42164.0          # orbit radius from the Earth's centre
# The geostationary imagers NASA GIBS serves, by sub-satellite longitude.
SATELLITES = {"GOES-East": -75.2, "GOES-West": -137.0, "Himawari": 140.7}


def _wrap(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


def bearing(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Initial great-circle bearing from the first point to the second, degrees."""
    east = math.radians(lon2 - lon1)
    p1, p2 = math.radians(lat1), math.radians(lat2)
    y = math.sin(east) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(east)
    return math.degrees(math.atan2(y, x)) % 360.0


def radius_toward(radii4, toward: float) -> int | None:
    """The quadrant radius (NE, SE, SW, NW) that covers a bearing."""
    if radii4 is None:
        return None
    return radii4[int((toward % 360.0) // 90.0) % 4]


def _within(fix: Fix, lon: float, lat: float, quadrants) -> bool:
    km = great_circle(fix.lon, fix.lat, lon, lat)
    if km < 1e-6:       # at the centre, give or take a rounding error
        return True
    reach = radius_toward(quadrants, bearing(fix.lon, fix.lat, lon, lat))
    return km <= reach * NM_KM


def inside(fix: Fix, lon: float, lat: float, threshold: int) -> bool | None:
    """Whether a place is inside one wind threshold at a fix; None if not forecast."""
    quadrants = fix.radius(threshold)
    if quadrants is not None:
        return _within(fix, lon, lat, quadrants)
    if fix.wind is not None and fix.wind < threshold:
        return False
    for other in THRESHOLDS:
        known = fix.radius(other)
        if known is None:
            continue
        if other < threshold and not _within(fix, lon, lat, known):
            return False
        if other > threshold and _within(fix, lon, lat, known):
            return True
    return None


def _known(fix: Fix, threshold: int):
    """A fix's radii at a threshold: as forecast, zero below it, else unknown."""
    quadrants = fix.radius(threshold)
    if quadrants is not None:
        return quadrants
    if fix.wind is not None and fix.wind < threshold:
        return (0, 0, 0, 0)
    return None


def _blend(a: Fix, b: Fix, hour: int) -> Fix:
    """The fix ``hour`` hours after ``a`` on the way to ``b``."""
    span = b.tau - a.tau
    if hour <= 0:
        return replace(a, lon=_wrap(a.lon))
    f = hour / span
    radii = []
    for threshold in THRESHOLDS:
        qa, qb = _known(a, threshold), _known(b, threshold)
        if qa is None or qb is None:
            continue
        quadrants = tuple(round(x + (y - x) * f) for x, y in zip(qa, qb))
        if any(quadrants):
            radii.append((threshold, quadrants))
    wind = None if a.wind is None or b.wind is None else round(a.wind + (b.wind - a.wind) * f)
    return replace(a, tau=a.tau + hour, lat=a.lat + (b.lat - a.lat) * f,
                   lon=_wrap(a.lon + _wrap(b.lon - a.lon) * f), wind=wind,
                   pressure=None, rmw=None, eye=None, radii=tuple(radii))


def timeline(analysis: Fix | None, forecast, step: int = 1) -> list[Fix]:
    """The official track every ``step`` hours, radii interpolated.

    One fix per lead, the official forecast's own when a deck carries
    several techs at the same lead; the analysis goes first only when the
    forecast is counted from it.
    """
    ahead: dict[int, Fix] = {}
    for fix in sorted(forecast, key=lambda f: f.tech != "OFCL"):
        if fix.tau > 0:
            ahead.setdefault(fix.tau, fix)
    line = [ahead[tau] for tau in sorted(ahead)]
    if analysis is not None and (not line or analysis.stamp == line[0].stamp):
        line.insert(0, analysis)
    out = []
    for a, b in zip(line, line[1:]):
        out.extend(_blend(a, b, hour) for hour in range(0, b.tau - a.tau, step))
    if line:
        out.append(replace(line[-1], lon=_wrap(line[-1].lon)))
    return out


@dataclass(frozen=True)
class Exposure:
    """When each wind threshold first reaches one place, and how near the centre comes.

    ``arrival`` maps 34, 50 and 64 kt to the valid time (``YYYYMMDDHH``)
    the wind first reaches the place, or None if it does not. ``unknown``
    lists the thresholds that do not arrive but were not forecast while the
    place was in the storm's reach, so "does not arrive" cannot be said.
    """

    place: str
    country: str
    population: int
    lon: float
    lat: float
    arrival: dict
    unknown: tuple
    closest_km: float
    closest_stamp: str


def exposures(storm, places=None, horizon: int = 120) -> list[Exposure]:
    """Every place a threshold reaches, or might, earliest gale first."""
    line = [f for f in timeline(storm.latest, storm.forecast) if f.tau <= horizon]
    if not line:
        return []
    places = atlasdata.PLACES if places is None else places
    gale_nm = max((q for fix in line for t, quads in fix.radii if t == 34 for q in quads),
                  default=0)
    reach_km = gale_nm * NM_KM + 111.2       # the widest gale, plus a degree
    pad = reach_km / 111.2
    south, north = min(f.lat for f in line) - pad, max(f.lat for f in line) + pad
    out = []
    for place in places:
        if not south <= place.lat <= north:
            continue
        if not any(great_circle(f.lon, f.lat, place.lon, place.lat) <= reach_km for f in line):
            continue
        arrival: dict[int, str | None] = {t: None for t in THRESHOLDS}
        unknown = set()
        closest = (math.inf, "")
        for fix in line:
            km = great_circle(fix.lon, fix.lat, place.lon, place.lat)
            if km < closest[0]:
                closest = (km, valid_stamp(fix))
            for threshold in THRESHOLDS:
                if arrival[threshold] is not None:
                    continue
                state = inside(fix, place.lon, place.lat, threshold)
                if state:
                    arrival[threshold] = valid_stamp(fix)
                elif state is None:
                    unknown.add(threshold)
        unknown_after = tuple(sorted(t for t in unknown if arrival[t] is None))
        if arrival[34] is None and not unknown_after:
            continue
        out.append(Exposure(place.name, place.country, place.population, place.lon,
                            place.lat, arrival, unknown_after, closest[0], closest[1]))
    out.sort(key=lambda e: (e.arrival[34] is None, e.arrival[34] or "", e.closest_km))
    return out


# --------------------------------------------------------------------------
# viewing geometry
# --------------------------------------------------------------------------
def view_zenith(lon: float, lat: float, sub_lon: float) -> float | None:
    """The satellite's zenith angle at a point, degrees; None below the horizon."""
    cos_g = math.cos(math.radians(lat)) * math.cos(math.radians(_wrap(lon - sub_lon)))
    g = math.acos(max(-1.0, min(1.0, cos_g)))
    below = math.cos(g) - EARTH_RADIUS_KM / GEOSTATIONARY_KM
    if below <= 0.0:
        return None
    return math.degrees(math.atan2(math.sin(g), below))


def best_satellite(lon: float, lat: float, limit: float = 70.0) -> tuple[str, float] | None:
    """The imager that sees a point most nearly overhead, within ``limit`` degrees."""
    views = [(zenith, name) for name, sub in SATELLITES.items()
             if (zenith := view_zenith(lon, lat, sub)) is not None and zenith <= limit]
    if not views:
        return None
    zenith, name = min(views)
    return name, zenith


def _destination(lon: float, lat: float, heading: float, km: float) -> tuple[float, float]:
    d = km / 6371.0
    p1, l1, t = math.radians(lat), math.radians(lon), math.radians(heading)
    p2 = math.asin(math.sin(p1) * math.cos(d) + math.cos(p1) * math.sin(d) * math.cos(t))
    l2 = l1 + math.atan2(math.sin(t) * math.sin(d) * math.cos(p1),
                         math.cos(d) - math.sin(p1) * math.sin(p2))
    return _wrap(math.degrees(l2)), math.degrees(p2)


def parallax(lon: float, lat: float, sub_lon: float,
             height_km: float = 15.0) -> tuple[float, float]:
    """Where a cloud top ``height_km`` above a point appears on the image.

    Displaced h tan z away from the sub-satellite point, along the great
    circle from it through the point. At the sub-satellite point itself
    there is no displacement.
    """
    zenith = view_zenith(lon, lat, sub_lon)
    if zenith is None or (lat == 0.0 and _wrap(lon - sub_lon) == 0.0):
        return lon, lat
    away = (bearing(lon, lat, sub_lon, 0.0) + 180.0) % 360.0
    return _destination(lon, lat, away, height_km * math.tan(math.radians(zenith)))


def centre_at(path, when: float) -> tuple[float, float] | None:
    """The centre at an epoch time, from ``(seconds, lon, lat)`` in time order.

    Linear between the two points either side, longitude the short way
    round; None outside the path, because the centre is not extrapolated.
    """
    for (t1, lon1, lat1), (t2, lon2, lat2) in zip(path, path[1:]):
        if t1 <= when <= t2:
            f = 0.0 if t2 == t1 else (when - t1) / (t2 - t1)
            return _wrap(lon1 + _wrap(lon2 - lon1) * f), lat1 + (lat2 - lat1) * f
    if len(path) == 1 and path[0][0] == when:
        return path[0][1], path[0][2]
    return None
