"""Build the vendored atlas: borders, rivers, lakes and a gazetteer.

Run once. Writes ``elnino/atlasdata.py``. Same contract as the coastline: the
data is downloaded here, checked in, and never fetched again at render time.

Natural Earth, public domain, 10m where it is affordable. What is taken and
what is left:

    admin-0 boundary lines   taken. A map with coastlines and no borders is
                             unreadable the moment it is zoomed past a basin.
    rivers, lake centrelines taken, down to the scalerank where a river is
                             still a landmark rather than a tributary.
    lakes                    taken, same rule.
    populated places         taken whole. This is the layer that makes a click
                             resolve to a place instead of a coordinate, and at
                             7,300 rows it is the cheapest thing here.
    admin-1 (states)         left out. Twenty-one megabytes of source, and at
                             the zooms this atlas reaches a province outline
                             mostly competes with the composite it is drawn
                             over.
    urban area polygons      left out, at twenty-eight megabytes, in favour of
                             city dots graduated by population - which read
                             better at these scales and come free with the
                             gazetteer.

Geometry is stored exactly as the coastline stores it: delta-encoded
hundredths of a degree with a per-point level digit, so the levels are one
array rather than several copies. Douglas-Peucker is hierarchical, which is
what makes that work: the points surviving tolerance T are exactly those whose
split distance is at least T.
"""

from __future__ import annotations

import json
import ssl
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "elnino" / "atlasdata.py"

RAW = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
       "master/geojson")
AGENT = {"User-Agent": "elnino-tracker/2.0 (+personal ENSO monitoring)"}
CTX = ssl.create_default_context()

# Coarsest first, and deliberately the same ladder the coastline uses so a
# border and the shore it meets are simplified by the same amount at the same
# zoom. A border that survives a step its coastline did not separates from it.
TOLERANCES = (0.30, 0.08, 0.035, 0.015)


def fetch(name: str) -> dict:
    url = f"{RAW}/{name}.geojson"
    print(f"  {name} ...", end="", flush=True)
    req = urllib.request.Request(url, headers=AGENT)
    with urllib.request.urlopen(req, timeout=300, context=CTX) as r:
        data = json.loads(r.read().decode("utf-8"))
    print(f" {len(data['features'])} features")
    return data


# --- simplification ----------------------------------------------------------

def _split_distance(points: list[tuple[float, float]]) -> list[float]:
    """Douglas-Peucker split distance for every point in a polyline.

    The value for a point is the perpendicular distance at which it would first
    be kept. Endpoints get infinity because they are never dropped. Computing
    it for every point once gives the whole tolerance ladder from one pass,
    which is the property that lets four levels share one array.
    """
    n = len(points)
    keep = [0.0] * n
    if n < 3:
        return [float("inf")] * n
    keep[0] = keep[n - 1] = float("inf")
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        if hi <= lo + 1:
            continue
        x0, y0 = points[lo]
        x1, y1 = points[hi]
        dx, dy = x1 - x0, y1 - y0
        norm = dx * dx + dy * dy
        best, at = -1.0, lo
        for i in range(lo + 1, hi):
            px, py = points[i]
            if norm <= 0.0:
                far = (px - x0) ** 2 + (py - y0) ** 2
            else:
                t = ((px - x0) * dx + (py - y0) * dy) / norm
                t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
                far = (px - x0 - t * dx) ** 2 + (py - y0 - t * dy) ** 2
            if far > best:
                best, at = far, i
        # A child's distance can exceed its parent's, which would make a point
        # survive a level its parent did not and leave the line with a hole.
        # Clamping to the parent is what keeps the ladder nested.
        keep[at] = min(best ** 0.5, keep[lo], keep[hi])
        stack.append((lo, at))
        stack.append((at, hi))
    return keep


def level_digits(points: list[tuple[float, float]]) -> str:
    """One digit per point: the coarsest level that still keeps it."""
    distances = _split_distance(points)
    digits = []
    for value in distances:
        for level, tol in enumerate(TOLERANCES):
            if value >= tol:
                digits.append(str(level))
                break
        else:
            digits.append(str(len(TOLERANCES) - 1))
    return "".join(digits)


def pack(points: list[tuple[float, float]]) -> tuple[str, str] | None:
    """Delta-encoded hundredths of a degree, plus the level digits."""
    rounded, last = [], None
    for lon, lat in points:
        cell = (round(lon * 100), round(lat * 100))
        if cell != last:
            rounded.append(cell)
            last = cell
    if len(rounded) < 2:
        return None
    digits = level_digits([(x / 100.0, y / 100.0) for x, y in rounded])
    parts, px, py = [], 0, 0
    for x, y in rounded:
        parts.append(str(x - px))
        parts.append(str(y - py))
        px, py = x, y
    return ",".join(parts), digits


def geometry_lines(feature: dict) -> list[list[tuple[float, float]]]:
    """Every polyline in a feature, whatever its geometry type."""
    geom = feature.get("geometry") or {}
    kind = geom.get("type")
    coords = geom.get("coordinates") or []
    if kind == "LineString":
        return [coords]
    if kind == "MultiLineString":
        return list(coords)
    if kind == "Polygon":
        return list(coords)
    if kind == "MultiPolygon":
        return [ring for polygon in coords for ring in polygon]
    return []


def layer(name: str, keep=lambda props: True) -> list[tuple[str, str]]:
    data = fetch(name)
    packed = []
    for feature in data["features"]:
        if not keep(feature.get("properties") or {}):
            continue
        for line in geometry_lines(feature):
            clean = [(float(p[0]), float(p[1])) for p in line
                     if len(p) >= 2 and abs(float(p[0])) <= 180.0
                     and abs(float(p[1])) <= 90.0]
            result = pack(clean)
            if result:
                packed.append(result)
    points = sum(len(d) for _, d in packed)
    print(f"    -> {len(packed)} lines, {points} points")
    return packed


def rank(props: dict, limit: float) -> bool:
    """Natural Earth's scalerank, which counts up as a feature gets smaller."""
    for key in ("scalerank", "SCALERANK", "strokeweig"):
        if key in props and props[key] is not None:
            try:
                return float(props[key]) <= limit
            except (TypeError, ValueError):
                continue
    return True


# --- the gazetteer -----------------------------------------------------------

def places() -> list[tuple]:
    data = fetch("ne_10m_populated_places_simple")
    rows = []
    for feature in data["features"]:
        props = feature.get("properties") or {}
        geom = feature.get("geometry") or {}
        if geom.get("type") != "Point":
            continue
        lon, lat = geom["coordinates"][0], geom["coordinates"][1]
        name = (props.get("name") or props.get("nameascii") or "").strip()
        if not name:
            continue
        population = props.get("pop_max") or props.get("pop_min") or 0
        rows.append((
            name,
            (props.get("adm0name") or "").strip(),
            (props.get("adm1name") or "").strip(),
            int(population or 0),
            round(float(lon), 3),
            round(float(lat), 3),
            # A capital outranks a larger provincial city when the question is
            # what to label a country with, so the flag is kept rather than
            # inferred back from population.
            1 if (props.get("featurecla") or "").startswith("Admin-0 capital")
            else 0,
        ))
    rows.sort(key=lambda r: (-r[3], r[0]))
    print(f"    -> {len(rows)} places, largest {rows[0][0]} {rows[0][3]:,}")
    return rows


PIPE = "│"  # names contain commas; they do not contain box drawing


def main() -> None:
    borders = layer("ne_10m_admin_0_boundary_lines_land")
    rivers = layer("ne_10m_rivers_lake_centerlines",
                   lambda p: rank(p, 7))
    lakes = layer("ne_10m_lakes", lambda p: rank(p, 4))
    gazetteer = places()

    out = [HEADER]
    for name, packed in (("BORDERS", borders), ("RIVERS", rivers),
                         ("LAKES", lakes)):
        out.append(f"_{name}: tuple[tuple[str, str], ...] = (\n")
        for coords, digits in packed:
            out.append(f'    ("{coords}",\n     "{digits}"),\n')
        out.append(")\n\n")

    out.append("# name | country | admin-1 | population | lon | lat | capital\n")
    out.append('_PLACES = """\\\n')
    for row in gazetteer:
        out.append(PIPE.join(str(v) for v in row) + "\n")
    out.append('"""\n\n')
    out.append(FOOTER)

    OUT.write_text("".join(out), encoding="utf-8", newline="\n")
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.2f} MB)")


HEADER = '''"""Vendored atlas: borders, rivers, lakes and a world gazetteer.

Generated by ``tools/vendor_atlas.py``; do not edit by hand.

Natural Earth 10m, public domain, downloaded once and checked in so that
nothing in the render path touches a third network service - the same contract
``coastline`` is under, and for the same reason.

Geometry uses that module's encoding exactly: delta-encoded hundredths of a
degree with one Douglas-Peucker level digit per point, against the same
tolerance ladder, so a border and the coast it meets shed detail together as
the view zooms out. Call ``lines(layer, level)``.

The gazetteer is 7,300 populated places with country, first-level division,
population and a capital flag, sorted by population so a caller can take the
top N for a zoom without sorting anything. Call ``near(lon, lat)`` for the
place a click landed on, or ``visible(...)`` for what to draw.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

TOLERANCES: tuple[float, ...] = (0.30, 0.08, 0.035, 0.015)
FINEST = len(TOLERANCES) - 1
DEFAULT_LEVEL = 1

'''

FOOTER = '''

@dataclass(frozen=True)
class Place:
    """One populated place from the gazetteer."""

    name: str
    country: str
    region: str
    population: int
    lon: float
    lat: float
    capital: bool

    @property
    def label(self) -> str:
        """Name, qualified by whatever distinguishes it from its namesakes."""
        if self.region and self.region != self.name:
            return f"{self.name}, {self.region}, {self.country}"
        return f"{self.name}, {self.country}" if self.country else self.name


def _unpack(coords: str, levels: str, digit: str):
    parts = coords.split(",")
    out: list[tuple[float, float]] = []
    x = y = 0
    for index, mark in enumerate(levels):
        x += int(parts[index * 2])
        y += int(parts[index * 2 + 1])
        if mark <= digit:
            out.append((x / 100.0, y / 100.0))
    return out


_LAYERS = {"borders": _BORDERS, "rivers": _RIVERS, "lakes": _LAKES}
_CACHE: dict[tuple[str, int], tuple] = {}


def lines(layer: str, level: int = DEFAULT_LEVEL):
    """Every polyline in one layer at one level of detail, in -180..180."""
    level = max(0, min(FINEST, int(level)))
    key = (layer, level)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    digit = str(level)
    built = tuple(
        tuple(line) for line in
        (_unpack(coords, marks, digit) for coords, marks in _LAYERS[layer])
        if len(line) > 1)
    _CACHE[key] = built
    return built

def packed(layer: str) -> tuple[tuple[str, str], ...]:
    """The stored form of one layer, for a caller shipping it elsewhere.

    The browser side of the atlas unpacks this itself rather than being handed
    four flattened copies of every border, for the same reason the globe does
    it with the coastline.
    """
    return _LAYERS[layer]


LAYERS: tuple[str, ...] = ("borders", "rivers", "lakes")


def level_for(degrees_per_pixel: float) -> int:
    """The coarsest level whose tolerance still falls under one pixel."""
    for level, tol in enumerate(TOLERANCES):
        if tol <= degrees_per_pixel:
            return level
    return FINEST


def _parse_places() -> tuple[Place, ...]:
    out = []
    for row in _PLACES.splitlines():
        if not row:
            continue
        name, country, region, population, lon, lat, capital = row.split("\\u2502")
        out.append(Place(name, country, region, int(population),
                         float(lon), float(lat), capital == "1"))
    return tuple(out)


PLACES: tuple[Place, ...] = _parse_places()


def _separation(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Great-circle kilometres. Local to this module so it imports alone."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(a)))


def near(lon: float, lat: float, limit: int = 6) -> list[tuple[float, Place]]:
    """The nearest places to a point, as (kilometres, place), nearest first.

    Every place is measured, because 7,300 great-circle distances is under ten
    milliseconds and a bounding box would have to be widened for the empty
    quarters of the Pacific until it stopped saving anything.
    """
    lon = (lon + 180.0) % 360.0 - 180.0
    scored = [(_separation(lon, lat, p.lon, p.lat), p) for p in PLACES]
    scored.sort(key=lambda item: (item[0], -item[1].population))
    return scored[:limit]


def visible(lon_min: float, lon_max: float, lat_min: float, lat_max: float,
            limit: int = 40) -> list[Place]:
    """The most populous places inside a window, largest first.

    The window may run past 360 - a Pacific-centred map is 100 to 300 and a
    zoomed one can wrap - so longitudes are compared in the window's own frame
    rather than in -180..180.
    """
    span = lon_max - lon_min
    out = []
    for place in PLACES:                     # already sorted by population
        x = place.lon
        while x < lon_min:
            x += 360.0
        if x - lon_min > span:
            continue
        if lat_min <= place.lat <= lat_max:
            out.append(place)
            if len(out) >= limit:
                break
    return out
'''


if __name__ == "__main__":
    main()
