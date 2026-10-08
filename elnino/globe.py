"""The planet, spinnable, with the anomaly on it and the consequences under it.

Every other view in this package answers "how big" or "where in the Pacific".
This one answers "what does this event do where I am", which is the question
anyone outside the tropical Pacific actually has. Spin the globe, zoom in, click
a place: the panel says which catalogued teleconnections cover that point, what
they do, in which season, how likely at today's index value and at the
projected peak,
and who is exposed.

Projection
----------
Orthographic, the same choice and the same reason as ``space3d``: it is what a
planet looks like from far away, area near the centre of view is undistorted,
and there is no perspective divide to make one anomaly look bigger than an equal
one elsewhere. The near hemisphere is drawn and the far side culled, which is
the honest behaviour - a globe that shows the whole world at once is a map
wearing a costume.

The inverse projection is what makes it clickable: screen point in, latitude and
longitude out, and from there the footprint lookup in ``geo``.

Rendering
---------
Server-rendered SVG for the default view, so the panel is complete in a print, a
screenshot and with JavaScript off, plus an inline script that re-projects on
drag. Same dual-render contract as the 3-D scenes.

The anomaly field ships to the script as one character per cell rather than as
numbers. A 53x144 grid is 7,632 values; as JSON that is about forty kilobytes of
text, as a string of ramp indices it is seven and a half. Nothing is lost,
because the cells were already quantised to eleven colour classes before they
were drawn.

Colour
------
The globe's colour is the SST anomaly, diverging, blue-white-red - the one job
colour is doing here. Footprint outlines are deliberately *not* a seven-way
categorical scheme: there are seven polarities and the page has five categorical
hues, and inventing two more would be exactly the mistake that makes a chart
unreadable for a colourblind reader. Instead every footprint is drawn in a
recessive neutral, the polarity filter highlights one class at a time with its
name on the control, and the panel labels each entry in words and with a shape.
Identity is never carried by colour alone here.

No library, no CDN, no tiles. The coastline is vendored, the projection is
twenty lines, and the result is still one self-contained file.
"""

from __future__ import annotations

import json
import math

from . import coastline, cyclones, geo
from .grids import Field
from .impacts import CATALOGUE, evaluate, flavour_of, flavour_penalty
from .storms import NEUTRAL, STORM_HUES
from .svg import esc

# Near hemisphere only. A point within this of the limb is dropped: right at the
# edge a quad projects almost edge-on and becomes a sliver of noise on the rim.
LIMB = 0.02

# One character per colour class, so the field travels as a string. Order is the
# ramp order; "." is no data - land, or a cell the sensor missed.
RAMP_CHARS = "0123456789a"
EMPTY_CHAR = "."
STEPS = len(RAMP_CHARS)

# Default view: the Pacific, tilted so the equatorial waveguide runs across the
# middle of the disc rather than along its edge.
HOME = (-150.0, 12.0)

VIEWS = (
    ("Pacific", -150.0, 12.0),
    ("Americas", -85.0, 10.0),
    ("Africa", 22.0, 4.0),
    ("Asia-Pacific", 118.0, 6.0),
    ("Atlantic", -40.0, 18.0),
    ("North pole", -100.0, 78.0),
    ("South pole", -150.0, -78.0),
)

# Polarity in words and in a shape, for the filter control and the panel. The
# catalogue's polarity strings are terse; these are what a reader should see.
POLARITY_NAME = {
    "dry": "Drier",
    "wet": "Wetter",
    "hot": "Hotter",
    "cold": "Cooler",
    "storm": "Storms",
    "marine": "Marine",
    "health": "Health",
}
POLARITY_MARK = {
    "dry": "▼",      # down: less of it
    "wet": "▲",      # up: more of it
    "hot": "▲",
    "cold": "▼",
    "storm": "◆",
    "marine": "●",
    "health": "■",
}


# --- projection -------------------------------------------------------------
def project(lon: float, lat: float, lon0: float, lat0: float):
    """Orthographic projection onto the unit sphere. None if on the far side."""
    phi, theta = math.radians(lat), math.radians(lon - lon0)
    phi0 = math.radians(lat0)
    cos_c = (math.sin(phi0) * math.sin(phi)
             + math.cos(phi0) * math.cos(phi) * math.cos(theta))
    if cos_c < LIMB:
        return None
    return (math.cos(phi) * math.sin(theta),
            math.cos(phi0) * math.sin(phi)
            - math.sin(phi0) * math.cos(phi) * math.cos(theta))


def unproject(x: float, y: float, lon0: float, lat0: float):
    """A point on the unit disc back to lon/lat. None if it missed the globe."""
    rho = math.hypot(x, y)
    if rho > 1.0:
        return None
    if rho < 1e-9:
        return geo.wrap180(lon0), lat0
    c = math.asin(min(1.0, rho))
    phi0 = math.radians(lat0)
    lat = math.degrees(math.asin(
        math.cos(c) * math.sin(phi0) + y * math.sin(c) * math.cos(phi0) / rho))
    lon = lon0 + math.degrees(math.atan2(
        x * math.sin(c),
        rho * math.cos(c) * math.cos(phi0) - y * math.sin(c) * math.sin(phi0)))
    return geo.wrap180(lon), lat


# --- the field, quantised ---------------------------------------------------
def ramp_index(value: float, limit: float) -> int:
    """Which of the eleven diverging steps a value falls in."""
    return max(0, min(STEPS - 1, int((value / limit + 1.0) / 2.0 * STEPS)))


def step_value(index: int, limit: float) -> float:
    """The middle of a step, for reading a quantised cell back out."""
    return ((index + 0.5) / STEPS * 2.0 - 1.0) * limit


def encode(grid: Field, limit: float) -> str:
    """The whole field as one character per cell, row-major from the south."""
    out = []
    for row in range(grid.rows):
        for col in range(grid.cols):
            value = grid.values[row][col]
            out.append(EMPTY_CHAR if value is None
                       else RAMP_CHARS[ramp_index(value, limit)])
    return "".join(out)


# The sphere under the data. Land and any cell the sensor missed show this
# through, and it is hatched rather than flat because a flat pale grey sits
# right on top of the diverging ramp's neutral step: a continent would read as
# "measured, near zero" instead of "not measured".
DEFS = (
    '<defs><pattern id="gnodata" width="6" height="6" '
    'patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
    '<rect width="6" height="6" fill="var(--plane)"/>'
    '<line x1="0" y1="0" x2="0" y2="6" stroke="var(--axis)" stroke-width="1"/>'
    "</pattern></defs>"
)


# --- drawing helpers --------------------------------------------------------
def _pt(point, radius: float, cx: float, cy: float) -> str:
    return f"{cx + point[0] * radius:.1f},{cy - point[1] * radius:.1f}"


def _runs(points, radius: float, cx: float, cy: float,
          attrs: str = "") -> list[str]:
    """Polylines for a path that goes over the limb and may come back."""
    head = f"<polyline {attrs} " if attrs else "<polyline "
    out: list[str] = []
    run: list[str] = []
    for point in points:
        if point is None:
            if len(run) > 1:
                out.append(f'{head}points="{" ".join(run)}"/>')
            run = []
        else:
            run.append(_pt(point, radius, cx, cy))
    if len(run) > 1:
        out.append(f'{head}points="{" ".join(run)}"/>')
    return out


def _edge(lon_a, lat_a, lon_b, lat_b, lon0, lat0, steps: int = 6):
    """One box edge, subdivided so it bends with the sphere.

    A footprint drawn as four straight screen lines reads as a flat sticker on a
    round object, and away from the centre of view it is visibly wrong: the top
    of a box spanning seventy degrees of longitude is not a straight line.
    """
    return [project(lon_a + (lon_b - lon_a) * i / steps,
                    lat_a + (lat_b - lat_a) * i / steps, lon0, lat0)
            for i in range(steps + 1)]


def _box_ring(box, lon0: float, lat0: float):
    return (_edge(box[0], box[2], box[1], box[2], lon0, lat0)
            + _edge(box[1], box[2], box[1], box[3], lon0, lat0)
            + _edge(box[1], box[3], box[0], box[3], lon0, lat0)
            + _edge(box[0], box[3], box[0], box[2], lon0, lat0))


# How many quads the globe may draw in one pass. The field behind it is half a
# degree - 228,000 cells - and a browser asked to lay out that many polygons
# stops being a map and becomes a progress bar. So the budget is spent where
# the reader is looking: work out the window the viewport can actually show,
# then take the coarsest stride that fills it. Zoomed out that is a decimated
# view of the field; zoomed six times, where the window is a five-hundredth of
# the sphere, it is every cell of it. Cost per frame stays flat and detail
# follows the zoom, which is the opposite of drawing everything and hoping.
#
# The ceiling counts cells looked at, not quads drawn: merging equal-coloured
# runs typically cuts that by ten, so sixty-five thousand buys a one-degree
# view unzoomed and the field's own half degree from the second zoom step on.
CELL_BUDGET = 65000

# A merged run is still four straight screen lines, so it cannot be allowed to
# span enough longitude for the chord to leave the sphere. Six degrees is a
# dozen cells at half-degree spacing and under a pixel of sag at full zoom.
MAX_RUN_DEG = 6.0


def visible_radius(radius: float, size: float, zoom: float = 1.0) -> float:
    """Angular radius, in degrees, of the cap the viewport can show.

    In an orthographic projection the whole near hemisphere lands inside one
    unit of the centre, so the fraction of that unit the viewport covers is the
    sine of the angle from the centre of view to its edge.
    """
    half = (size / 2.0) / max(radius * zoom, 1e-6)
    if half >= 1.0:
        return 90.0
    return math.degrees(math.asin(half))


def _reach(lat: float, theta: float) -> float:
    """How far east and west of centre is visible along one parallel.

    Meridians converge, so a cap of fixed angular radius covers more longitude
    the further it sits from the equator, and all of it at the pole.
    """
    if theta >= 89.0:
        return 180.0
    cos = math.cos(math.radians(min(abs(lat), 89.0)))
    if cos <= 0.02:
        return 180.0
    return min(180.0, theta / cos + 2.0)


def cell_stride(grid: Field, lat0: float, theta: float,
                budget: int = CELL_BUDGET) -> int:
    """Coarsest stride whose visible cell count stays inside the budget."""
    dlat = abs(grid.y[1] - grid.y[0]) or 1.0
    dlon = abs(grid.x[1] - grid.x[0]) or 1.0
    rows = max(1.0, 2.0 * theta / dlat)
    cols = max(1.0, 2.0 * _reach(lat0, theta) / dlon)
    return max(1, math.ceil(math.sqrt(rows * cols / max(budget, 1))))


def _near(line_bounds, lon0: float, lat0: float, theta: float) -> bool:
    """Could this polyline's bounding box put anything on screen?

    Latitude is exact. Longitude is only tested for a box narrow enough for the
    test to mean something - a line spanning half the world is drawn and left to
    the per-point culling, which is the honest answer and still cheap.
    """
    lon_min, lon_max, lat_min, lat_max = line_bounds
    if lat_min > lat0 + theta + 5.0 or lat_max < lat0 - theta - 5.0:
        return False
    if lon_max - lon_min > 170.0:
        return True
    nearest_lat = min(max(lat0, lat_min), lat_max)
    reach = _reach(nearest_lat, theta) + 5.0
    if reach >= 180.0:
        return True
    gap = min(abs(geo.wrap180(lon_min - lon0)), abs(geo.wrap180(lon_max - lon0)))
    if geo.wrap180(lon_min - lon0) <= 0 <= geo.wrap180(lon_max - lon0):
        gap = 0.0
    return gap <= reach


_BOUNDS: dict[int, tuple] = {}


def _coast_bounds(level: int):
    """Bounding boxes for one coastline level, worked out once."""
    hit = _BOUNDS.get(level)
    if hit is None:
        hit = tuple(coastline.bounds(line) for line in coastline.lines(level))
        _BOUNDS[level] = hit
    return hit


def _cells(grid: Field, limit: float, lon0: float, lat0: float,
           radius: float, cx: float, cy: float, theta: float = 90.0,
           stride: int = 1) -> list[str]:
    """The anomaly field as spherical quads over the visible cap.

    Runs of equal colour along a parallel are merged into one quad. The ramp
    has eleven steps and the ocean is smooth at this spacing, so a row of two
    hundred cells is typically a few dozen runs: the merge costs one comparison
    per cell and saves most of the markup.
    """
    dlat = grid.y[1] - grid.y[0]
    dlon = grid.x[1] - grid.x[0]
    half_lat = dlat / 2.0
    half_lon = dlon / 2.0
    run_cap = max(1, int(MAX_RUN_DEG / abs(dlon) / stride))
    out: list[str] = []

    centre_row = int(round((lat0 - grid.y[0]) / dlat))
    span_rows = int(theta / abs(dlat)) + 2
    row_lo = max(0, ((centre_row - span_rows) // stride) * stride)
    row_hi = min(grid.rows, centre_row + span_rows + 1)
    centre_col = int(round(((lon0 - grid.x[0]) % 360.0) / dlon))

    for row in range(row_lo, row_hi, stride):
        south = grid.y[row] - half_lat
        north = south + dlat * stride
        span_cols = int(_reach((south + north) / 2.0, theta) / abs(dlon)) + 2
        start = ((centre_col - span_cols) // stride) * stride
        stop = centre_col + span_cols + 1
        run_lo, run_index, run_len = None, None, 0

        def flush(end: int) -> None:
            if run_lo is None or run_index is None:
                return
            west = grid.x[0] + run_lo * dlon - half_lon
            east = grid.x[0] + (end - stride) * dlon - half_lon + dlon * stride
            corners = (project(west, south, lon0, lat0),
                       project(east, south, lon0, lat0),
                       project(east, north, lon0, lat0),
                       project(west, north, lon0, lat0))
            if any(corner is None for corner in corners):
                return
            path = " ".join(_pt(corner, radius, cx, cy) for corner in corners)
            out.append(f'<polygon points="{path}" '
                       f'fill="var(--d{run_index})"/>')

        for step in range(start, stop + stride, stride):
            index = None
            if step < stop:
                value = grid.values[row][step % grid.cols]
                if value is not None:
                    index = ramp_index(value, limit)
            if index != run_index or run_len >= run_cap:
                flush(step)
                run_lo, run_index, run_len = step, index, 0
            run_len += 1
    return out


def _coast(lon0: float, lat0: float, radius: float, cx: float,
           cy: float, level: int = coastline.DEFAULT_LEVEL,
           theta: float = 90.0) -> list[str]:
    """The coastline at one level of detail, over the visible cap.

    At full zoom this is a hundred and thirty thousand vertices, nine tenths of
    them behind the sphere or off the side of the viewport. Rejecting a line on
    its bounding box before projecting any of it is what keeps a drag smooth.
    """
    out = []
    lines = coastline.lines(level)
    for box, line in zip(_coast_bounds(level), lines):
        if not _near(box, lon0, lat0, theta):
            continue
        out.extend(_runs([project(lon, lat, lon0, lat0) for lon, lat in line],
                         radius, cx, cy))
    return out


def _graticule(lon0: float, lat0: float, radius: float, cx: float,
               cy: float) -> list[str]:
    out = []
    for lat in range(-60, 61, 30):
        out.extend(_runs([project(lon - 180.0, float(lat), lon0, lat0)
                          for lon in range(0, 361, 3)], radius, cx, cy))
    for lon in range(-180, 180, 30):
        out.extend(_runs([project(float(lon), float(lat), lon0, lat0)
                          for lat in range(-90, 91, 3)], radius, cx, cy))
    return out


def _zones(links: list[dict], lon0: float, lat0: float, radius: float,
           cx: float, cy: float) -> list[str]:
    out = []
    for link in links:
        if link["scope"] == geo.GLOBAL:
            continue
        for box in link["boxes"]:
            ring = _box_ring(box, lon0, lat0)
            if any(point is None for point in ring):
                continue
            path = " ".join(_pt(point, radius, cx, cy) for point in ring)
            out.append(f'<polygon points="{path}" class="zone"/>')
    return out


# --- the catalogue, scored and given coordinates ----------------------------
def dossier(peak_index: float, current_index: float, flavour_index: float,
            peak_label: str) -> list[dict]:
    """Every catalogue entry, scored now and at peak, with its geography.

    Scored here rather than in the browser so there is exactly one copy of the
    gating rules - the same ``impacts.evaluate`` the report and the hazard
    outlook use - instead of a second copy in JavaScript free to drift away.
    """
    flavour = flavour_of(flavour_index)
    out = []
    for link in CATALOGUE:
        footprint = geo.BY_REGION.get(link.region)
        if footprint is None:
            continue
        now_margin, now_likelihood, note = evaluate(link, current_index, flavour)
        peak_margin, peak_likelihood, _ = evaluate(link, peak_index, flavour)
        out.append({
            "region": link.region,
            "area": link.area,
            "scope": footprint.scope,
            "window": link.window,
            "effect": link.effect,
            "polarity": link.polarity,
            "polarity_name": POLARITY_NAME.get(link.polarity, link.polarity),
            "mark": POLARITY_MARK.get(link.polarity, "●"),
            "confidence": link.confidence,
            "threshold": link.min_intensity,
            # Where it appears for an event of this flavour: a gated link needs
            # a stronger event of the wrong flavour.
            "threshold_here": round(link.min_intensity + flavour_penalty(link, flavour), 2),
            "detail": link.detail,
            "exposure": link.exposure,
            "note": note,
            "anchor": list(footprint.anchor),
            "now": {"likelihood": now_likelihood, "margin": round(now_margin, 2)},
            "peak": {"likelihood": peak_likelihood, "margin": round(peak_margin, 2)},
            "peak_label": peak_label,
            "boxes": [[b.lon0, b.lon1, b.lat0, b.lat1] for b in footprint.boxes],
        })
    return out


def _lon_name(value: float) -> str:
    value = geo.wrap180(value)
    if abs(value) < 0.05:
        return "0"
    return f"{abs(value):.1f}{'E' if value > 0 else 'W'}"


def _lat_name(value: float) -> str:
    if abs(value) < 0.05:
        return "0 (equator)"
    return f"{abs(value):.1f}{'N' if value > 0 else 'S'}"


LIKELIHOOD_RANK = {"likely": 3, "probable": 2, "possible": 1, "uncertain": 1,
                   "unlikely": 0}


def _chip(word: str) -> str:
    """A likelihood as dots plus the word.

    The dots are there so the strength survives a greyscale print and a
    colourblind reader, and because "probable" against "possible" is one letter
    of difference at a glance.
    """
    rank = LIKELIHOOD_RANK.get(word, 0)
    dots = "●" * rank + "○" * (3 - rank)
    return (f'<span class="lk lk{rank}"><span class="lkdots">{dots}</span>'
            f"{esc(word)}</span>")


def _table(links: list[dict]) -> str:
    """The twin of the picture: the same dossier as rows, sorted by region."""
    head = ("<tr><th>Region</th><th>Centre</th><th>Effect</th><th>Season</th>"
            "<th>Now</th><th>At peak</th><th>Confidence</th></tr>")
    body = []
    for link in sorted(links, key=lambda item: item["region"]):
        lon, lat = link["anchor"]
        body.append(
            "<tr>"
            f'<td>{esc(link["region"])}</td>'
            f"<td>{esc(_lat_name(lat))}, {esc(_lon_name(lon))}</td>"
            f'<td>{esc(link["mark"])} {esc(link["polarity_name"])}'
            f' &mdash; {esc(link["effect"])}</td>'
            f'<td>{esc(link["window"])}</td>'
            f'<td>{_chip(link["now"]["likelihood"])}</td>'
            f'<td>{_chip(link["peak"]["likelihood"])}</td>'
            f'<td>{esc(link["confidence"])}</td>'
            "</tr>")
    return (f'<details class="tableview"><summary>Table view: all '
            f"{len(links)} catalogued regions, with coordinates</summary>"
            f'<table class="dtable"><thead>{head}</thead>'
            f'<tbody>{"".join(body)}</tbody></table></details>')


# --- the card ---------------------------------------------------------------
# --- live storms on the sphere ----------------------------------------------
# Marker radius by Saffir-Simpson category. Smaller than the flat track map's
# markers because here they sit on a busy coloured field rather than on a plain
# panel, and a large disc would hide the anomaly it is standing on.
EYE = {0: 3.0, 1: 4.0, 2: 4.6, 3: 5.2, 4: 6.0, 5: 7.0}


def hue_for(index: int) -> str:
    """A storm's colour. Same index, same storm, same hue as the track map."""
    return STORM_HUES[index] if 0 <= index < len(STORM_HUES) else NEUTRAL


def _flat(fixes) -> list[float]:
    """A track as [lon, lat, lon, lat, ...].

    Flat for the same reason the anomaly field travels as a string: a fifty
    member ensemble at twenty-one leads is two thousand points, and the bracket
    pairs alone would be a kilobyte of punctuation in the page.
    """
    return [round(value, 2) for fix in fixes for value in (fix.lon, fix.lat)]


def _when(stamp: str) -> str:
    return (f"{stamp[:4]}-{stamp[4:6]}-{stamp[6:8]} {stamp[8:10]}Z"
            if len(stamp) == 10 else stamp)


def storm_layer(state) -> list[dict]:
    """Every live storm, with everything its dossier needs already computed.

    Scored and shaped here rather than in the browser, for the same reason the
    teleconnections are: one copy of the rules, in Python, tested - not a
    second copy in JavaScript free to drift away from it.
    """
    storms = getattr(state, "cyclones", None)
    if storms is None or not storms.available:
        return []
    out = []
    for index, storm in enumerate(storms.active):
        now = storm.latest
        if now is None:
            continue
        history = [fix for fix in storm.track if fix.tau == 0]
        ahead = [fix for fix in storm.forecast if fix.tau <= cyclones.HORIZON]
        move = storm.translation
        change, _ = storm.rapid
        peak = storm.peak
        land = storm.nearest_land
        out.append({
            "id": storm.key,
            "name": storm.title,
            "designation": storm.designation,
            "basin": storm.basin_name,
            "hue": index if index < len(STORM_HUES) else -1,
            "track": _flat(history),
            "ahead": _flat([now] + ahead) if ahead else [],
            "spread": [_flat([fix for fix in member
                              if fix.tau <= cyclones.HORIZON])
                       for member in storm.scatter.values()],
            "members": len(storm.scatter),
            "lon": round(now.lon, 2),
            "lat": round(now.lat, 2),
            "wind": now.wind or 0,
            "pressure": now.pressure,
            "cat": now.category,
            "short": now.short,
            "when": _when(now.stamp),
            "advisory": storm.advisory.get("advisory") or "",
            "move": (None if move is None
                     else [round(move[0]), cyclones.bearing_name(move[1])]),
            "change": round(change),
            "rapid": storm.intensifying_rapidly,
            "ace": round(storm.ace, 1),
            # Peak only when it is above the current intensity: a storm that
            # is at its own peak right now would otherwise read as having two
            # separate facts that are the same fact.
            "peak": (None if peak is None or not peak.wind
                     or peak.wind <= (now.wind or 0)
                     else [peak.wind, peak.short, _when(peak.stamp)]),
            "spread_km": (None if storm.spread_km is None
                          else round(storm.spread_km)),
            "spread_tau": storm.spread_tau,
            "land": (None if land is None
                     else [land[1].name, land[1].country, round(land[0])]),
            "steps": [[fix.tau, round(fix.lat, 1), round(fix.lon, 1),
                       fix.wind or 0, fix.short] for fix in ahead],
            "threats": [[place.name, place.country, round(gap), fix.tau,
                         fix.wind or 0, fix.short, cyclones.lead(fix)]
                        for gap, fix, place in storm.threats(400.0)
                        if (fix.wind or 0) >= 34][:6],
        })
    return out


def _arc(flat: list[float], lon0: float, lat0: float):
    return [project(flat[i], flat[i + 1], lon0, lat0)
            for i in range(0, len(flat) - 1, 2)]


def _storms(layer: list[dict], lon0: float, lat0: float, radius: float,
            cx: float, cy: float) -> list[str]:
    """Spread first and faint, then the tracks, then the eyes.

    Drawing order is the confidence order: the faint scatter, in its storm's
    colour, is the width of what is known, the line is the middle of it, and
    the disc is the one position that is measured rather than forecast.
    """
    out: list[str] = []
    for storm in layer:
        paint = hue_for(storm["hue"])
        for member in storm["spread"]:
            out.extend(_runs(_arc(member, lon0, lat0), radius, cx, cy,
                             f'class="tcspread" style="stroke:{paint}"'))
    for storm in layer:
        paint = hue_for(storm["hue"])
        out.extend(_runs(_arc(storm["track"], lon0, lat0), radius, cx, cy,
                         f'class="tctrack" style="stroke:{paint}"'))
        out.extend(_runs(_arc(storm["ahead"], lon0, lat0), radius, cx, cy,
                         f'class="tcahead" style="stroke:{paint}"'))
        point = project(storm["lon"], storm["lat"], lon0, lat0)
        if point is None:
            continue
        x, y = cx + point[0] * radius, cy - point[1] * radius
        out.append(
            f'<circle class="tcdot" cx="{x:.1f}" cy="{y:.1f}" '
            f'r="{EYE.get(storm["cat"], 3.0):.1f}" style="fill:{paint}"/>'
            f'<text class="tcname" x="{x + 12:.1f}" y="{y - 9:.1f}">'
            f'{esc(storm["name"])}</text>'
        )
    return out


def card(state, size: int = 640) -> str:
    """The globe panel: spin it, zoom it, click it, read what happens there."""
    spatial = getattr(state, "spatial", None)
    grid = getattr(spatial, "sst_global", None) if spatial else None
    if grid is None or grid.rows < 2 or grid.cols < 2:
        return ""

    low, high = grid.robust_span()
    limit = max(abs(low), abs(high), 0.5)
    radius = size / 2.0 - 24.0
    cx = cy = size / 2.0
    lon0, lat0 = HOME

    # The server renders the unzoomed view, so it renders it at the detail an
    # unzoomed view can carry. Everything past that is the browser's job, and
    # it asks for the same two numbers with the zoom folded in.
    theta = visible_radius(radius, size)
    stride = cell_stride(grid, lat0, theta)
    level = coastline.level_for(math.degrees(1.0) / radius)

    assessment = state.assessment
    index_name = assessment.index_name
    current_index = assessment.index_latest.value
    peak = state.forecast.peak if state.forecast else None
    peak_index = state.impacts.peak_index if state.impacts else current_index
    peak_label = peak.label if peak else ""
    flavour_index = assessment.scale.flavour_index if assessment.scale else 0.0
    links = dossier(peak_index, current_index, flavour_index, peak_label)
    layer = storm_layer(state)

    payload = {
        "grid": {
            "lat0": grid.y[0], "lon0": geo.wrap180(grid.x[0]),
            "dlat": grid.y[1] - grid.y[0], "dlon": grid.x[1] - grid.x[0],
            "rows": grid.rows, "cols": grid.cols,
            "limit": round(limit, 3), "steps": STEPS,
            "data": encode(grid, limit),
        },
        "view": {"lon": lon0, "lat": lat0, "r": radius, "cx": cx, "cy": cy},
        "links": links,
        "storms": layer,
        "as_of": grid.as_of,
        "index_name": index_name,
        "index": round(current_index, 2),
        "peak_index": round(peak_index, 2),
        "peak_label": peak_label,
    }

    scene = [
        DEFS,
        f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{radius:.1f}" class="ocean"/>',
        '<g class="cells">',
        *_cells(grid, limit, lon0, lat0, radius, cx, cy, theta, stride),
        '</g><g class="grat">', *_graticule(lon0, lat0, radius, cx, cy),
        '</g><g class="coast">',
        *_coast(lon0, lat0, radius, cx, cy, level, theta),
        '</g><g class="zones">', *_zones(links, lon0, lat0, radius, cx, cy),
        '</g><g class="storms">', *_storms(layer, lon0, lat0, radius, cx, cy),
        '</g>',
        f'<circle cx="{cx:.0f}" cy="{cy:.0f}" r="{radius:.1f}" class="limb"/>',
    ]

    ramp = "".join(f'<span class="rampcell" style="background:var(--d{i})"></span>'
                   for i in range(STEPS))
    views = "".join(
        f'<button type="button" class="gbtn" data-globe-view="{lon},{lat}">'
        f"{esc(name)}</button>" for name, lon, lat in VIEWS)
    polarities = "".join(
        f'<button type="button" class="gchip" data-globe-pol="{pol}">'
        f"{esc(POLARITY_MARK[pol])} {esc(name)}</button>"
        for pol, name in POLARITY_NAME.items())

    chips = "".join(
        f'<button type="button" class="gchip tcchip" '
        f'data-globe-storm="{esc(storm["id"])}" '
        f'style="--tc:{hue_for(storm["hue"])}"><span class="tcsw"></span>'
        f'{esc(storm["name"])} {storm["wind"]} kt</button>' for storm in layer)
    storm_row = (
        f'<div class="grow"><span class="glabel">Storms</span>{chips}'
        f'<button type="button" class="gchip on" data-globe-tc="1">'
        f'Tracks on</button></div>') if layer else ""
    storm_legend = (
        '<span class="gl"><span class="glsw gltrack"></span>Best track</span>'
        '<span class="gl"><span class="glsw glahead"></span>'
        'Official forecast, to +120 h</span>'
        '<span class="gl"><span class="glsw glspread"></span>'
        'Ensemble members</span>'
    ) if layer else ""
    storm_phrase = (
        f" {len(layer)} live storm{'s' if len(layer) != 1 else ''} "
        f"sit on the sphere with the best track behind, the official forecast "
        f"ahead and every ensemble member faintly in the colour of its storm - "
        f"click one to open it."
    ) if layer else ""

    peak_phrase = (f" and at the projected peak of {peak_index:+.2f} in "
                   f"{esc(peak_label)}") if peak_label else ""
    return f"""<section class="card wide" id="globe">
  <h2>The planet, and what this event does to it</h2>
  <p class="caption">Sea surface temperature anomaly for {esc(grid.as_of)} painted
  on the sphere, with the {len(links)} catalogued teleconnection regions outlined.
  <strong>Drag to spin, pinch or use &minus;/+ (or ctrl and the wheel) to
  zoom, click anywhere to open that location.</strong> The panel reports every relationship covering the point
  you pick, scored at today&rsquo;s {esc(index_name)} of {current_index:+.2f}{peak_phrase}.{storm_phrase}</p>
  <div class="ramp">
    <div class="ramplabel">SST anomaly <span class="rampunits">°C</span></div>
    <div class="rampstrip">{ramp}</div>
    <div class="rampticks"><span class="ramptick">&minus;{limit:.1f}</span>
      <span class="ramptick">0</span>
      <span class="ramptick">+{limit:.1f}</span></div>
  </div>
  <div class="gcontrols">
    <div class="grow"><span class="glabel">View</span>{views}
      <button type="button" class="gbtn" data-globe-zoom="-1"
        aria-label="Zoom out">&minus;</button>
      <button type="button" class="gbtn" data-globe-zoom="1"
        aria-label="Zoom in">+</button>
      <button type="button" class="gbtn" data-globe-zoom="0">Reset</button></div>
    <div class="grow"><span class="glabel">Highlight</span>
      <button type="button" class="gchip on" data-globe-pol="">All regions</button>
      {polarities}</div>
    {storm_row}
  </div>
  <div class="glegend">
    <span class="gl"><span class="glsw glzone"></span>Teleconnection region</span>
    <span class="gl"><span class="glsw gllive"></span>Highlighted, or under the pin</span>
    <span class="gl"><span class="glsw glnd"></span>Land, or no sea surface reading</span>{storm_legend}
  </div>
  <div class="globewrap">
    <div class="globe" data-globe='{esc(json.dumps(payload, separators=(",", ":")))}'>
      <svg class="globe-svg" viewBox="0 0 {size} {size}" role="img"
           aria-label="Rotatable globe of the sea surface temperature anomaly with
           teleconnection regions outlined. Click a location for its effects.">
        {''.join(scene)}
      </svg>
      <p class="ghint">Drag to spin &middot; click to inspect &middot; pinch, or ctrl and scroll, to zoom</p>
    </div>
    <div class="dossier" aria-live="polite">
      <p class="hint">Click anywhere on the globe. The panel will report the sea
      surface anomaly in that cell and every catalogued relationship that covers
      it, with its likelihood now and at the projected peak.</p>
    </div>
  </div>
  {_table(links)}
  <p class="subcaption">Footprints are deliberately coarse boxes. A
  teleconnection is a shift in a seasonal probability distribution over a broad
  region, and a precise polygon would claim a spatial resolution the underlying
  composites do not have. Nothing here is a forecast for a specific place or
  date: it is a hazard outlook built from historical composites, and the caveats
  in the impacts section apply to every line of it.</p>
</section>"""


# --- style ------------------------------------------------------------------
def css() -> str:
    """The globe's own styles. Plain text, so it escapes no braces on the way."""
    return CSS


CSS = """
/* --- the globe ------------------------------------------------------------- */
.globewrap { display: grid; grid-template-columns: minmax(0, 1.25fr) minmax(0, 1fr);
  gap: 22px; align-items: start; }
.glegend { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 0 0 10px;
  font-size: 0.72rem; color: var(--ink2); }
.gl { display: inline-flex; align-items: center; gap: 7px; }
.glsw { width: 22px; height: 12px; border-radius: 2px; flex: none; }
.glzone { border: 1.4px dashed var(--ink2); opacity: 0.6; }
.gllive { border: 2px solid var(--s1);
  background: color-mix(in srgb, var(--s1) 12%, transparent); }
.glnd { border: 1px solid var(--axis);
  background: repeating-linear-gradient(45deg, var(--plane) 0 3px,
    var(--axis) 3px 4px); }
.globe { cursor: grab; touch-action: pan-y; position: relative; }
.globe.grabbing { cursor: grabbing; }
/* At rest the frame is the limb, so the panel is a sphere rather than a
   picture of one. Zoomed in the sphere is larger than the frame, and a round
   clip would then crop the data to a porthole for no reason. */
.globe-svg { width: 100%; height: auto; display: block; user-select: none;
  overflow: hidden; border-radius: 50%; }
.globe.zoomed .globe-svg { border-radius: 12px;
  background: var(--surface); box-shadow: inset 0 0 0 1px var(--border); }
.globe-svg:focus-visible { outline: 2px solid var(--s1); outline-offset: 4px; }
.ghint { margin: 6px 0 0; text-align: center; font-size: 0.7rem;
  color: var(--muted); }

/* The sphere itself. Ocean is the neutral midpoint of the diverging ramp, so a
   cell the sensor missed reads as "no reading" rather than as zero anomaly. */
.ocean { fill: url(#gnodata); }
.limb { fill: none; stroke: var(--axis); stroke-width: 1.2; }
.cells polygon { shape-rendering: crispEdges; }
.grat polyline { fill: none; stroke: var(--axis); stroke-width: 0.6;
  opacity: 0.5; }
.coast polyline { fill: none; stroke: var(--ink); stroke-width: 0.9;
  opacity: 0.62; stroke-linejoin: round; }

/* Footprints are outlines, not fills: a fill would hide the anomaly under it,
   and the anomaly is the measurement while the footprint is the inference. */
.zone { fill: none; stroke: var(--ink2); stroke-width: 1.1; opacity: 0.45;
  stroke-dasharray: 4 3; }
.zone.dim { opacity: 0.12; }
.zone.live { stroke: var(--s1); stroke-width: 2.4; opacity: 1;
  stroke-dasharray: none; fill: color-mix(in srgb, var(--s1) 12%, transparent); }
.pin circle { fill: none; stroke: var(--ink); stroke-width: 2.5; }
.pin .pindot { fill: var(--ink); stroke: var(--surface); stroke-width: 1.5; }

/* --- controls -------------------------------------------------------------- */
.gcontrols { display: flex; flex-direction: column; gap: 6px; margin-bottom: 12px; }
.grow { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.glabel { font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--muted); margin-right: 2px;
  min-width: 62px; }
.gbtn, .gchip { font: inherit; font-size: 0.72rem; font-weight: 600;
  padding: 4px 11px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--border); background: var(--plane); color: var(--ink2); }
.gbtn:hover, .gchip:hover { color: var(--ink); border-color: var(--axis); }
.gchip.on { color: var(--s1); background: color-mix(in srgb, var(--s1) 10%, transparent);
  border-color: color-mix(in srgb, var(--s1) 50%, transparent); }

/* --- the panel that opens on a click --------------------------------------- */
.dossier { max-height: 640px; overflow-y: auto; padding-right: 4px; }
.dhead { display: flex; align-items: baseline; justify-content: space-between;
  gap: 10px; border-bottom: 1px solid var(--border); padding-bottom: 6px; }
.dossier h3 { margin: 0; font-size: 0.95rem; font-variant-numeric: tabular-nums; }
.localsst { font-size: 0.83rem; color: var(--ink2); margin: 8px 0 2px; }
.dcount { font-size: 0.74rem; color: var(--muted); margin: 0 0 10px; }
.dz { border-top: 1px solid var(--border); padding-top: 10px; margin-top: 10px; }
.dz h4 { margin: 0 0 4px; font-size: 0.86rem; display: flex; gap: 7px;
  align-items: baseline; flex-wrap: wrap; }
.pmark { color: var(--ink2); font-size: 0.7rem; }
.pname { font-weight: 500; color: var(--muted); font-size: 0.72rem;
  text-transform: uppercase; letter-spacing: 0.05em; }
.dzeffect { margin: 0 0 8px; font-size: 0.85rem; }
.dzgrid { display: grid; grid-template-columns: max-content 1fr; gap: 3px 12px;
  margin: 0 0 8px; font-size: 0.78rem; }
.dzgrid dt { color: var(--muted); }
.dzgrid dd { margin: 0; color: var(--ink2); }
.dzdetail { margin: 0 0 6px; font-size: 0.78rem; color: var(--ink2); }
.dzexp { margin: 0; font-size: 0.78rem; color: var(--ink2); }
.dznote { margin: 6px 0 0; font-size: 0.74rem; color: var(--muted);
  font-style: italic; }

/* A likelihood carries its strength in dots as well as in the word, so it
   survives greyscale, colour vision deficiency and a glance. */
.lk { display: inline-flex; align-items: baseline; gap: 5px; white-space: nowrap; }
.lkdots { letter-spacing: 1px; font-size: 0.62rem; color: var(--muted); }
.lk3 { color: var(--ink); font-weight: 650; }
.lk3 .lkdots { color: var(--ink); }
.lk2 { color: var(--ink); font-weight: 600; }
.lk2 .lkdots { color: var(--ink2); }
.lk1 { color: var(--ink2); }
.lk0 { color: var(--muted); }

.dtable td { white-space: normal; text-align: left; vertical-align: top; }
.dtable th { text-align: left; }
.dtable td:nth-child(2) { white-space: nowrap; }

/* --- live storms ----------------------------------------------------------- */
/* Colour here identifies the storm and nothing else - the same hue it wears on
   the flat track map, so a reader moving between the two panels is not asked
   to relearn which line is which. Intensity is the marker's size and the words
   beside it, never the hue. */
.storms polyline { fill: none; stroke-linejoin: round; stroke-linecap: round; }
.tcspread { stroke-width: 1; opacity: 0.35; }
.tctrack { stroke-width: 2.2; }
.tcahead { stroke-width: 2.2; stroke-dasharray: 7 5; }
/* A surface ring, because the disc sits on top of a coloured field and two
   saturated colours meeting with no gap read as one shape. */
.tcdot { stroke: var(--surface); stroke-width: 2; }
/* The name in text ink; the eye beside it carries the storm's colour. */
.tcname { font-size: 0.7rem; font-weight: 700; paint-order: stroke;
  fill: var(--ink); stroke: var(--surface); stroke-width: 3px;
  stroke-linejoin: round; }
.tcchip .tcsw { width: 10px; height: 10px; border-radius: 50%;
  background: var(--tc); display: inline-block; margin-right: 6px;
  vertical-align: -1px; }
.gchip.off { opacity: 0.5; }
/* The keys in the legend's own ink: each storm wears its own colour on the
   sphere, and a key in one storm's would read as that storm's alone. */
.gltrack, .glahead, .glspread { height: 0; border-radius: 0;
  border-top: 3px solid currentColor; }
.glahead { border-top-style: dashed; }
.glspread { border-top-width: 2px; opacity: 0.45; }
.tckey { display: inline-block; width: 12px; height: 12px; border-radius: 50%;
  margin-right: 8px; vertical-align: -1px; }
.dsub { margin: 14px 0 5px; font-size: 0.72rem; font-weight: 700;
  letter-spacing: 0.06em; text-transform: uppercase; color: var(--muted); }
.tctable { width: 100%; border-collapse: collapse; font-size: 0.76rem;
  font-variant-numeric: tabular-nums; }
.tctable th, .tctable td { text-align: left; white-space: nowrap;
  border-bottom: 1px solid var(--border); }
.tctable th { font-weight: 600; color: var(--muted); padding: 2px 8px 4px 0; }
.tctable td { padding: 3px 8px 3px 0; }
.tctable .tcnum { text-align: right; padding-right: 14px; }
.tcwarn { margin: 10px 0 0; font-size: 0.76rem; color: var(--ink2); }

@media (max-width: 1000px) {
  .globewrap { grid-template-columns: 1fr; }
  .dossier { max-height: none; }
}
@media (max-width: 720px) {
  .glabel { min-width: 0; width: 100%; }
}
"""


# --- the script -------------------------------------------------------------
def _coast_js() -> str:
    """The packed coastline, all four levels, for the browser to unpack.

    The packed form is what is shipped rather than four flattened copies: the
    levels are a subset relation, so one array with a digit per point is a
    quarter of the bytes and the browser does the same running sum the Python
    side does.
    """
    return json.dumps([list(pair) for pair in coastline.packed()],
                      separators=(",", ":"))


def js() -> str:
    """Inline script: rotate, zoom, pick, and redraw. No dependencies."""
    return ("var GLOBE_COAST=" + _coast_js() + ";\n"
            + "var GLOBE_TOL=" + json.dumps(list(coastline.TOLERANCES)) + ";\n"
            + "var GLOBE_DEFS=" + json.dumps(DEFS) + ";\n"
            + GLOBE_JS)


GLOBE_JS = r"""
(function () {
  var LIMB = 0.02;
  var CHARS = "0123456789a";
  var DEFS = GLOBE_DEFS;

  function wrap(lon) { return ((lon + 180) % 360 + 360) % 360 - 180; }
  // A modulo that never returns a negative, which JavaScript's does.
  function mod(a, n) { return ((a % n) + n) % n; }
  function project(lon, lat, lon0, lat0) {
    var phi = lat * Math.PI / 180, th = (lon - lon0) * Math.PI / 180;
    var p0 = lat0 * Math.PI / 180;
    var cosc = Math.sin(p0) * Math.sin(phi) +
               Math.cos(p0) * Math.cos(phi) * Math.cos(th);
    if (cosc < LIMB) { return null; }
    return [Math.cos(phi) * Math.sin(th),
            Math.cos(p0) * Math.sin(phi) -
            Math.sin(p0) * Math.cos(phi) * Math.cos(th)];
  }
  function unproject(x, y, lon0, lat0) {
    var rho = Math.sqrt(x * x + y * y);
    if (rho > 1) { return null; }
    if (rho < 1e-9) { return [wrap(lon0), lat0]; }
    var c = Math.asin(Math.min(1, rho)), p0 = lat0 * Math.PI / 180;
    var lat = Math.asin(Math.cos(c) * Math.sin(p0) +
              y * Math.sin(c) * Math.cos(p0) / rho) * 180 / Math.PI;
    var lon = lon0 + Math.atan2(x * Math.sin(c),
      rho * Math.cos(c) * Math.cos(p0) -
      y * Math.sin(c) * Math.sin(p0)) * 180 / Math.PI;
    return [wrap(lon), lat];
  }
  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  }
  function signed(v, places) {
    return (v >= 0 ? "+" : "−") + Math.abs(v).toFixed(places);
  }
  function lonName(v) {
    v = wrap(v);
    return Math.abs(v) < 0.05 ? "0"
      : Math.abs(v).toFixed(1) + (v > 0 ? "E" : "W");
  }
  function latName(v) {
    return Math.abs(v) < 0.05 ? "0 (equator)"
      : Math.abs(v).toFixed(1) + (v > 0 ? "N" : "S");
  }

  document.querySelectorAll(".globe").forEach(function (host) {
    var data;
    try { data = JSON.parse(host.getAttribute("data-globe")); } catch (e) { return; }
    var svg = host.querySelector("svg");
    if (!svg) { return; }
    var card = host.closest(".card") || document;
    var panel = card.querySelector(".dossier");
    var view = data.view, g = data.grid;
    var lon0 = view.lon, lat0 = view.lat, zoom = 1;
    var pin = null, filter = "", coarse = false, frame = null;
    var STORMS = data.storms || [], showStorms = true;

    function sample(row, col) {
      var i = CHARS.indexOf(g.data.charAt(row * g.cols + col));
      return i < 0 ? null : i;
    }
    function pt(p, r) {
      return (view.cx + p[0] * r).toFixed(1) + "," +
             (view.cy - p[1] * r).toFixed(1);
    }
    function runs(points, r, out, attrs) {
      var head = attrs ? "<polyline " + attrs + " " : "<polyline ";
      var run = [];
      for (var i = 0; i < points.length; i++) {
        if (!points[i]) {
          if (run.length > 1) {
            out.push(head + 'points="' + run.join(" ") + '"/>');
          }
          run = [];
        } else { run.push(pt(points[i], r)); }
      }
      if (run.length > 1) { out.push(head + 'points="' + run.join(" ") + '"/>'); }
    }
    function ring(points, r) {
      var out = [];
      for (var i = 0; i < points.length; i++) {
        if (!points[i]) { return null; }
        out.push(pt(points[i], r));
      }
      return out.join(" ");
    }
    function edge(a, b, c, d) {
      var out = [];
      for (var i = 0; i <= 6; i++) {
        out.push(project(a + (c - a) * i / 6, b + (d - b) * i / 6, lon0, lat0));
      }
      return out;
    }
    function boxRing(B) {
      return edge(B[0], B[2], B[1], B[2])
        .concat(edge(B[1], B[2], B[1], B[3]))
        .concat(edge(B[1], B[3], B[0], B[3]))
        .concat(edge(B[0], B[3], B[0], B[2]));
    }
    function inBox(B, lon, lat) {
      return lon >= B[0] && lon <= B[1] && lat >= B[2] && lat <= B[3];
    }
    function pinned(link) {
      if (!pin) { return false; }
      for (var i = 0; i < link.boxes.length; i++) {
        if (inBox(link.boxes[i], pin[0], pin[1])) { return true; }
      }
      return false;
    }

    // --- live storms ------------------------------------------------------
    // Same geometry, same colours and the same drawing order as the server
    // rendered pass above, so a drag changes the viewpoint and nothing else.
    var EYE = { 0: 3, 1: 4, 2: 4.6, 3: 5.2, 4: 6, 5: 7 };
    function hue(i) { return i >= 0 ? "var(--s" + (i + 1) + ")" : "var(--ink2)"; }
    function arc(flat) {
      var out = [];
      for (var i = 0; i + 1 < flat.length; i += 2) {
        out.push(project(flat[i], flat[i + 1], lon0, lat0));
      }
      return out;
    }
    function stormArt(r) {
      if (!showStorms || !STORMS.length) { return ""; }
      var out = [], i, j, S, h, p, x, y;
      // The ensemble is dropped while the globe is in motion for the same
      // reason the cells coarsen: it is a thousand short segments, and nobody
      // reads a spread envelope mid-drag.
      if (!coarse) {
        for (i = 0; i < STORMS.length; i++) {
          for (j = 0; j < STORMS[i].spread.length; j++) {
            runs(arc(STORMS[i].spread[j]), r, out, 'class="tcspread" style="stroke:' + hue(STORMS[i].hue) + '"');
          }
        }
      }
      for (i = 0; i < STORMS.length; i++) {
        S = STORMS[i]; h = hue(S.hue);
        runs(arc(S.track), r, out, 'class="tctrack" style="stroke:' + h + '"');
        runs(arc(S.ahead), r, out, 'class="tcahead" style="stroke:' + h + '"');
        p = project(S.lon, S.lat, lon0, lat0);
        if (!p) { continue; }
        x = view.cx + p[0] * r; y = view.cy - p[1] * r;
        out.push('<circle class="tcdot" cx="' + x.toFixed(1) + '" cy="' +
          y.toFixed(1) + '" r="' + (EYE[S.cat] || 3) + '" style="fill:' + h +
          '"/><text class="tcname" x="' + (x + 12).toFixed(1) + '" y="' +
          (y - 9).toFixed(1) + '">' + esc(S.name) + '</text>');
      }
      return '<g class="storms">' + out.join("") + '</g>';
    }
    function pickStorm(sx, sy, r) {
      if (!showStorms) { return null; }
      for (var i = 0; i < STORMS.length; i++) {
        var p = project(STORMS[i].lon, STORMS[i].lat, lon0, lat0);
        if (!p) { continue; }
        var dx = view.cx + p[0] * r - sx, dy = view.cy - p[1] * r - sy;
        // A generous target: the eye of a hurricane is a few pixels wide here
        // and the reader is aiming with a finger on a phone.
        if (dx * dx + dy * dy <= 400) { return STORMS[i]; }
      }
      return null;
    }
    function deg(lat, lon) {
      return Math.abs(lat).toFixed(1) + (lat >= 0 ? "N" : "S") + " " +
             Math.abs(lon).toFixed(1) + (lon < 0 ? "W" : "E");
    }
    function attachCentre() {
      var centre = panel.querySelector("[data-globe-centre]");
      if (!centre) { return; }
      centre.addEventListener("click", function () {
        if (!pin) { return; }
        lon0 = pin[0]; lat0 = pin[1]; draw();
      });
    }
    function reportStorm(S) {
      var h = hue(S.hue), i, rows;
      var out = ['<div class="dhead"><h3><span class="tckey" style="background:' +
        h + '"></span>' + esc(S.name) + '</h3>' +
        '<button type="button" class="gbtn" data-globe-centre="1">' +
        'Centre here</button></div>'];
      out.push('<p class="localsst"><strong>' + S.wind + ' kt</strong> ' +
        esc(S.short) + (S.pressure ? ' &middot; ' + S.pressure + ' mb' : "") +
        '</p>');
      out.push('<p class="dcount">' + esc(S.designation) + ' &middot; ' +
        esc(S.basin) + ' &middot; fix ' + esc(S.when) +
        (S.advisory ? ' &middot; advisory ' + esc(S.advisory) : "") + '</p>');
      rows = ['<dt>Position</dt><dd>' + deg(S.lat, S.lon) + '</dd>'];
      if (S.move) {
        rows.push('<dt>Moving</dt><dd>' + esc(S.move[1]) + ' at ' +
          S.move[0] + ' kt</dd>');
      }
      rows.push('<dt>Past 24 h</dt><dd>' + signed(S.change, 0) + ' kt' +
        (S.rapid ? ' &mdash; rapid intensification' : "") + '</dd>');
      if (S.peak) {
        rows.push('<dt>Peak so far</dt><dd>' + S.peak[0] + ' kt, ' +
          esc(S.peak[1]) + ', ' + esc(S.peak[2]) + '</dd>');
      }
      rows.push('<dt>Storm ACE</dt><dd>' + S.ace.toFixed(1) + '</dd>');
      if (S.spread_km !== null && S.spread_km !== undefined) {
        rows.push('<dt>Track spread</dt><dd>' + S.spread_km + ' km across ' +
          S.members + ' members at +' + S.spread_tau + ' h</dd>');
      }
      if (S.land) {
        rows.push('<dt>Nearest land</dt><dd>' + esc(S.land[0]) + ', ' +
          esc(S.land[1]) + ', ' + S.land[2] + ' km</dd>');
      }
      out.push('<dl class="dzgrid">' + rows.join("") + '</dl>');
      if (S.steps.length) {
        rows = ['<h4 class="dsub">Official forecast</h4><table class="tctable">' +
          '<thead><tr><th>Lead</th><th>Position</th>' +
          '<th class="tcnum">Wind</th><th>Intensity</th></tr></thead><tbody>'];
        for (i = 0; i < S.steps.length; i++) {
          rows.push('<tr><td>+' + S.steps[i][0] + ' h</td><td>' +
            deg(S.steps[i][1], S.steps[i][2]) + '</td><td class="tcnum">' +
            S.steps[i][3] + ' kt</td><td>' + esc(S.steps[i][4]) + '</td></tr>');
        }
        out.push(rows.join("") + '</tbody></table>');
      }
      if (S.threats.length) {
        rows = ['<h4 class="dsub">Closest approach to named coast</h4>' +
          '<table class="tctable"><thead><tr><th>Place</th>' +
          '<th class="tcnum">km</th><th>Lead</th><th>Intensity</th>' +
          '</tr></thead><tbody>'];
        for (i = 0; i < S.threats.length; i++) {
          rows.push('<tr><td>' + esc(S.threats[i][0]) + ', ' +
            esc(S.threats[i][1]) + '</td><td class="tcnum">' + S.threats[i][2] +
            '</td><td>' + esc(S.threats[i][6]) + '</td><td>' + S.threats[i][4] +
            ' kt ' + esc(S.threats[i][5]) + '</td></tr>');
        }
        out.push(rows.join("") + '</tbody></table>');
      }
      out.push('<p class="tcwarn">Distances are to the forecast centre line. ' +
        'Hurricane-force wind reaches tens of kilometres either side of it and ' +
        'tropical-storm force twice that, so a 200 km pass is not a miss. The ' +
        'grey lines are the honest width of this forecast; the dashed line is ' +
        'the middle of them, not the whole of them.</p>');
      panel.innerHTML = out.join("");
      attachCentre();
    }

    // --- level of detail --------------------------------------------------
    // The same three numbers the server worked out before it rendered the
    // first frame, recomputed here with the zoom folded in. Drawing is bounded
    // by what the viewport can show rather than by the size of the field, so
    // the cost of a frame does not change when the reader zooms - only the
    // detail does.
    var CELL_BUDGET = 65000, MAX_RUN_DEG = 6, DEG = 180 / Math.PI;
    // The field is a quarter degree, so the zoom is allowed to run far
    // enough in to actually reach it: ten times is about 0.02 degrees to
    // a pixel, which is one cell to twelve and the finest coastline.
    var MAX_ZOOM = 10;
    var coastCache = {}, boundsCache = {};

    function visibleRadius(r) {
      var half = (view.cx * 2) / (2 * Math.max(r, 1e-6));
      return half >= 1 ? 90 : Math.asin(half) * DEG;
    }
    function reach(lat, theta) {
      if (theta >= 89) { return 180; }
      var c = Math.cos(Math.min(Math.abs(lat), 89) / DEG);
      return c <= 0.02 ? 180 : Math.min(180, theta / c + 2);
    }
    function cellStride(theta) {
      var rows = Math.max(1, 2 * theta / Math.abs(g.dlat));
      var cols = Math.max(1, 2 * reach(lat0, theta) / Math.abs(g.dlon));
      return Math.max(1, Math.ceil(Math.sqrt(rows * cols / CELL_BUDGET)));
    }
    function levelFor(dpp) {
      for (var i = 0; i < GLOBE_TOL.length; i++) {
        if (GLOBE_TOL[i] <= dpp) { return i; }
      }
      return GLOBE_TOL.length - 1;
    }
    // Douglas-Peucker is hierarchical, so a level is a filter on one array
    // rather than an array of its own: keep every point whose digit is at most
    // the level asked for. Unpacked once per level and kept.
    function coastAt(level) {
      if (coastCache[level]) { return coastCache[level]; }
      var digit = String(level), out = [], boxes = [], i, j;
      for (i = 0; i < GLOBE_COAST.length; i++) {
        var parts = GLOBE_COAST[i][0].split(","), marks = GLOBE_COAST[i][1];
        var flat = [], x = 0, y = 0;
        var w = 1e9, e = -1e9, s2 = 1e9, n = -1e9;
        for (j = 0; j < marks.length; j++) {
          x += +parts[j * 2];
          y += +parts[j * 2 + 1];
          if (marks.charAt(j) <= digit) {
            var lo = x / 100, la = y / 100;
            flat.push(lo, la);
            if (lo < w) { w = lo; }
            if (lo > e) { e = lo; }
            if (la < s2) { s2 = la; }
            if (la > n) { n = la; }
          }
        }
        if (flat.length > 3) { out.push(flat); boxes.push([w, e, s2, n]); }
      }
      coastCache[level] = out;
      boundsCache[level] = boxes;
      return out;
    }
    function nearBox(b, theta) {
      if (b[2] > lat0 + theta + 5 || b[3] < lat0 - theta - 5) { return false; }
      if (b[1] - b[0] > 170) { return true; }
      var near = Math.min(Math.max(lat0, b[2]), b[3]);
      var span = reach(near, theta) + 5;
      if (span >= 180) { return true; }
      var a = wrap(b[0] - lon0), c = wrap(b[1] - lon0);
      if (a <= 0 && c >= 0) { return true; }
      return Math.min(Math.abs(a), Math.abs(c)) <= span;
    }

    function draw() {
      var r = view.r * zoom;
      host.classList.toggle("zoomed", zoom > 1.001);
      var theta = visibleRadius(r);
      // One step coarser while dragging: a 2x2 merge is a quarter of the
      // polygons and the difference is invisible on a globe in motion.
      var step = cellStride(theta) * (coarse ? 2 : 1);
      var hlat = g.dlat / 2, hlon = g.dlon / 2;
      var runCap = Math.max(1, Math.floor(MAX_RUN_DEG / Math.abs(g.dlon) / step));
      var cells = [], row, col, i, pts, s;
      var midRow = Math.round((lat0 - g.lat0) / g.dlat);
      var spanRow = Math.floor(theta / Math.abs(g.dlat)) + 2;
      var rowLo = Math.max(0, Math.floor((midRow - spanRow) / step) * step);
      var rowHi = Math.min(g.rows, midRow + spanRow + 1);
      var midCol = Math.round(mod(lon0 - g.lon0, 360) / g.dlon);
      for (row = rowLo; row < rowHi; row += step) {
        var south = g.lat0 + row * g.dlat - hlat;
        var north = south + g.dlat * step;
        var spanCol = Math.floor(reach((south + north) / 2, theta) /
                                 Math.abs(g.dlon)) + 2;
        var start = Math.floor((midCol - spanCol) / step) * step;
        var stop = midCol + spanCol + 1;
        var runLo = null, runIx = null, runLen = 0;
        for (col = start; col <= stop; col += step) {
          var v = col < stop ? sample(row, mod(col, g.cols)) : null;
          if (v !== runIx || runLen >= runCap) {
            if (runLo !== null && runIx !== null) {
              var west = g.lon0 + runLo * g.dlon - hlon;
              var east = g.lon0 + (col - step) * g.dlon - hlon + g.dlon * step;
              var quad = ring([project(west, south, lon0, lat0),
                               project(east, south, lon0, lat0),
                               project(east, north, lon0, lat0),
                               project(west, north, lon0, lat0)], r);
              if (quad) {
                cells.push('<polygon points="' + quad +
                           '" fill="var(--d' + runIx + ')"/>');
              }
            }
            runLo = col; runIx = v; runLen = 0;
          }
          runLen++;
        }
      }
      var grat = [];
      for (var la = -60; la <= 60; la += 30) {
        pts = [];
        for (s = 0; s <= 360; s += 3) { pts.push(project(s - 180, la, lon0, lat0)); }
        runs(pts, r, grat);
      }
      for (var lo2 = -180; lo2 < 180; lo2 += 30) {
        pts = [];
        for (s = -90; s <= 90; s += 3) { pts.push(project(lo2, s, lon0, lat0)); }
        runs(pts, r, grat);
      }
      // A level finer than the display is invisible and a level coarser is
      // the polygon the reader complains about, so it follows the zoom - and
      // drops one while dragging, where nobody is reading an estuary.
      var level = levelFor(DEG / r);
      if (coarse) { level = Math.max(0, level - 1); }
      var shore = coastAt(level), boxes = boundsCache[level];
      var coast = [];
      for (i = 0; i < shore.length; i++) {
        if (!nearBox(boxes[i], theta)) { continue; }
        var flat = shore[i];
        pts = [];
        for (var j = 0; j < flat.length; j += 2) {
          pts.push(project(flat[j], flat[j + 1], lon0, lat0));
        }
        runs(pts, r, coast);
      }
      var zones = [], hot = [];
      for (var k = 0; k < data.links.length; k++) {
        var L = data.links[k];
        if (L.scope === "global") { continue; }
        var live = pinned(L) || (filter !== "" && L.polarity === filter);
        for (var b = 0; b < L.boxes.length; b++) {
          var path = ring(boxRing(L.boxes[b]), r);
          if (!path) { continue; }
          var cls = live ? "zone live" : (filter !== "" ? "zone dim" : "zone");
          (live ? hot : zones).push(
            '<polygon points="' + path + '" class="' + cls + '"/>');
        }
      }
      var mark = "";
      if (pin) {
        var p = project(pin[0], pin[1], lon0, lat0);
        if (p) {
          var xy = pt(p, r).split(",");
          mark = '<g class="pin"><circle cx="' + xy[0] + '" cy="' + xy[1] +
                 '" r="7"/><circle class="pindot" cx="' + xy[0] + '" cy="' +
                 xy[1] + '" r="2.5"/></g>';
        }
      }
      svg.innerHTML = DEFS +
        '<circle cx="' + view.cx + '" cy="' + view.cy + '" r="' + r.toFixed(1) +
        '" class="ocean"/>' +
        '<g class="cells">' + cells.join("") + '</g>' +
        '<g class="grat">' + grat.join("") + '</g>' +
        '<g class="coast">' + coast.join("") + '</g>' +
        '<g class="zones">' + zones.join("") + hot.join("") + '</g>' +
        stormArt(r) + mark +
        '<circle cx="' + view.cx + '" cy="' + view.cy + '" r="' + r.toFixed(1) +
        '" class="limb"/>';
    }

    // Three dots beside the word, because a likelihood must not be legible by
    // colour alone - and because "probable" against "possible" is one letter
    // of difference at a glance.
    function chip(word) {
      var rank = word === "likely" ? 3 : word === "probable" ? 2
        : (word === "possible" || word === "uncertain") ? 1 : 0;
      var dots = "";
      for (var i = 0; i < 3; i++) { dots += i < rank ? "●" : "○"; }
      return '<span class="lk lk' + rank + '"><span class="lkdots">' + dots +
             '</span>' + esc(word) + '</span>';
    }

    function report(lon, lat) {
      var hits = [], i, b, L;
      for (i = 0; i < data.links.length; i++) {
        L = data.links[i];
        if (L.scope === "global") { continue; }
        for (b = 0; b < L.boxes.length; b++) {
          if (inBox(L.boxes[b], lon, lat)) {
            hits.push([L, (L.boxes[b][1] - L.boxes[b][0]) *
                          (L.boxes[b][3] - L.boxes[b][2])]);
            break;
          }
        }
      }
      // Smallest box first: a specific claim about the Dry Corridor beats a
      // general one about the Caribbean when a click lands in both.
      hits.sort(function (a, c) { return a[1] - c[1]; });

      var row = Math.round((lat - g.lat0) / g.dlat);
      var col = Math.round(wrap(lon - g.lon0) / g.dlon);
      col = ((col % g.cols) + g.cols) % g.cols;
      var local = '<p class="localsst hint">Outside the gridded field.</p>';
      if (row >= 0 && row < g.rows) {
        var v = sample(row, col);
        if (v === null) {
          local = '<p class="localsst hint">Land, or no sea surface reading in ' +
                  'this cell.</p>';
        } else {
          var mid = ((v + 0.5) / g.steps * 2 - 1) * g.limit;
          local = '<p class="localsst">Sea surface anomaly here: <strong>' +
                  signed(mid, 1) + ' °C</strong> <span class="hint">(' +
                  esc(data.as_of) + ', to the nearest colour step)</span></p>';
        }
      }
      var head = '<div class="dhead"><h3>' + latName(lat) + ", " + lonName(lon) +
        '</h3><button type="button" class="gbtn" data-globe-centre="1">' +
        'Centre here</button></div>' + local;

      if (!hits.length) {
        panel.innerHTML = head + '<p class="hint">No catalogued teleconnection ' +
          'covers this point. That is not the same as &ldquo;no effect&rdquo;: it ' +
          'means this package holds no relationship here it is willing to stand ' +
          'behind.</p>';
      } else {
        var out = [head, '<p class="dcount">' + hits.length +
          (hits.length === 1 ? ' relationship covers' : ' relationships cover') +
          ' this point, most specific first.</p>'];
        for (i = 0; i < hits.length; i++) {
          L = hits[i][0];
          out.push('<article class="dz">' +
            '<h4><span class="pmark">' + esc(L.mark) + '</span>' +
            esc(L.region) + ' <span class="pname">' + esc(L.polarity_name) +
            '</span></h4>' +
            '<p class="dzeffect">' + esc(L.effect) + '</p>' +
            '<dl class="dzgrid">' +
            '<dt>Season</dt><dd>' + esc(L.window) + '</dd>' +
            '<dt>Now (' + esc(data.index_name) + ' ' + signed(data.index, 2) + ')</dt><dd>' +
              chip(L.now.likelihood) + '</dd>' +
            '<dt>At peak' + (L.peak_label ? ", " + esc(L.peak_label) : "") +
              ' (' + signed(data.peak_index, 2) + ')</dt><dd>' +
              chip(L.peak.likelihood) + '</dd>' +
            '<dt>Appears above</dt><dd>' + esc(data.index_name) + ' ' +
              signed(L.threshold_here, 1) + ' °C' +
              (L.threshold_here > L.threshold ? ' for this flavour' : '') + '</dd>' +
            '<dt>Confidence</dt><dd>' + esc(L.confidence) + '</dd>' +
            '</dl>' +
            '<p class="dzdetail">' + esc(L.detail) + '</p>' +
            '<p class="dzexp"><strong>Exposure.</strong> ' + esc(L.exposure) +
            '</p>' +
            (L.note ? '<p class="dznote">' + esc(L.note) + '</p>' : "") +
            (L.scope === "basin" ? '<p class="dznote">This is a signal about ' +
              'activity over the basin, not about conditions at this point on ' +
              'the ground.</p>' : "") +
            '</article>');
        }
        panel.innerHTML = out.join("");
      }
      attachCentre();
    }

    function queue() {
      if (frame) { return; }
      frame = requestAnimationFrame(function () { frame = null; draw(); });
    }

    // Every pointer on the globe is kept: one spins it, two pinch its zoom.
    // Kept as one, a second finger jerked the spin between the two of them.
    var pointers = new Map(), travelled = 0, spread = 0;
    function gap() {
      var two = Array.from(pointers.values()).slice(0, 2);
      return Math.max(1, Math.hypot(two[0].x - two[1].x, two[0].y - two[1].y));
    }
    // Zoom by how far apart the fingers have moved since the last event. The
    // globe grows about its own centre: a sphere turned under the fingers as
    // well would be a second gesture hidden in the first.
    function pinch() {
      var now = gap();
      zoom = Math.max(1, Math.min(MAX_ZOOM, zoom * now / spread));
      spread = now;
      queue();
    }
    svg.addEventListener("pointerdown", function (e) {
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size === 1) { travelled = 0; }
      // A pinch is never a click, whichever finger lifts last.
      if (pointers.size === 2) { spread = gap(); travelled = Infinity; }
      coarse = true; host.classList.add("grabbing");
      try { svg.setPointerCapture(e.pointerId); } catch (err) { /* no capture */ }
    });
    svg.addEventListener("pointermove", function (e) {
      var last = pointers.get(e.pointerId);
      if (!last) { return; }
      var dx = e.clientX - last.x, dy = e.clientY - last.y;
      pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pointers.size >= 2) { pinch(); return; }
      travelled += Math.abs(dx) + Math.abs(dy);
      // Slower turn when zoomed in, so a gesture covers the same ground.
      lon0 = wrap(lon0 - dx * 0.35 / zoom);
      lat0 = Math.max(-89, Math.min(89, lat0 + dy * 0.35 / zoom));
      queue();
    });
    function release(e) {
      if (!pointers.has(e.pointerId)) { return; }
      pointers.delete(e.pointerId);
      // Fingers still down carry on: two pinch from where they are now, one
      // spins from where it is.
      if (pointers.size >= 2) { spread = gap(); }
      if (pointers.size) { return; }
      coarse = false; host.classList.remove("grabbing");
      if (travelled < 5) {
        var rect = svg.getBoundingClientRect();
        var sx = (e.clientX - rect.left) / rect.width * view.cx * 2;
        var sy = (e.clientY - rect.top) / rect.height * view.cy * 2;
        var r = view.r * zoom;
        // A storm wins the click over the ocean under it: a reader aiming at a
        // hurricane wants the hurricane, not the cell it happens to sit on.
        var hit = pickStorm(sx, sy, r);
        if (hit) {
          pin = [hit.lon, hit.lat];
          reportStorm(hit);
        } else {
          var ll = unproject((sx - view.cx) / r, (view.cy - sy) / r, lon0, lat0);
          if (ll) { pin = ll; report(ll[0], ll[1]); }
        }
      }
      draw();
    }
    svg.addEventListener("pointerup", release);
    svg.addEventListener("pointercancel", function (e) {
      pointers.delete(e.pointerId);
      if (pointers.size >= 2) { spread = gap(); }
      if (pointers.size) { return; }
      coarse = false; host.classList.remove("grabbing"); draw();
    });
    // Ctrl/Cmd is required to zoom on the wheel. A bare wheel that zoomed would
    // trap the reader: this panel sits in the middle of a very long page, and a
    // scroll past it must stay a scroll past it.
    svg.addEventListener("wheel", function (e) {
      if (!e.ctrlKey && !e.metaKey) { return; }
      e.preventDefault();
      zoom = Math.max(1, Math.min(MAX_ZOOM, zoom * (e.deltaY < 0 ? 1.15 : 1 / 1.15)));
      queue();
    }, { passive: false });

    card.querySelectorAll("[data-globe-view]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var parts = btn.getAttribute("data-globe-view").split(",");
        lon0 = parseFloat(parts[0]); lat0 = parseFloat(parts[1]); draw();
      });
    });
    card.querySelectorAll("[data-globe-zoom]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var dir = parseInt(btn.getAttribute("data-globe-zoom"), 10);
        if (dir === 0) { zoom = 1; lon0 = view.lon; lat0 = view.lat; }
        else { zoom = Math.max(1, Math.min(MAX_ZOOM, zoom * (dir > 0 ? 1.4 : 1 / 1.4))); }
        draw();
      });
    });
    card.querySelectorAll("[data-globe-pol]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        filter = btn.getAttribute("data-globe-pol");
        card.querySelectorAll("[data-globe-pol]").forEach(function (other) {
          other.classList.toggle("on", other === btn);
        });
        draw();
      });
    });

    card.querySelectorAll("[data-globe-storm]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var id = btn.getAttribute("data-globe-storm"), i, toggle;
        for (i = 0; i < STORMS.length; i++) {
          if (STORMS[i].id !== id) { continue; }
          showStorms = true;
          toggle = card.querySelector("[data-globe-tc]");
          if (toggle) {
            toggle.classList.add("on"); toggle.classList.remove("off");
            toggle.textContent = "Tracks on";
          }
          lon0 = STORMS[i].lon; lat0 = STORMS[i].lat;
          pin = [STORMS[i].lon, STORMS[i].lat];
          reportStorm(STORMS[i]);
          draw();
          return;
        }
      });
    });
    card.querySelectorAll("[data-globe-tc]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        showStorms = !showStorms;
        btn.classList.toggle("on", showStorms);
        btn.classList.toggle("off", !showStorms);
        btn.textContent = showStorms ? "Tracks on" : "Tracks off";
        draw();
      });
    });

    // The globe is a control, so it has to work without a pointer.
    svg.setAttribute("tabindex", "0");
    svg.addEventListener("keydown", function (e) {
      var keys = { ArrowLeft: [-8, 0], ArrowRight: [8, 0],
                   ArrowUp: [0, 6], ArrowDown: [0, -6] };
      if (keys[e.key]) {
        e.preventDefault();
        lon0 = wrap(lon0 + keys[e.key][0]);
        lat0 = Math.max(-89, Math.min(89, lat0 + keys[e.key][1]));
        draw();
      } else if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        pin = [wrap(lon0), lat0];
        report(pin[0], pin[1]);
        draw();
      }
    });
  });
})();
"""
