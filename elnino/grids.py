"""Gridded and sectioned ocean data: where the event actually is.

Every other module in this package reduces the Pacific to a number. A number
cannot tell you that the warm anomaly has detached from the coast, that the
thermocline has flattened from 165E to 110W, or that a downwelling Kelvin wave
crossed the dateline five weeks ago. This module keeps the geometry.

Four shapes of data, one container each:

    Field     a regular lattice with labelled axes. A map (lat by lon), a
              Hovmoller (time by lon) and a depth section (depth by lon) are
              all the same object with different axis names, so one renderer
              draws all three.
    Mesh      scattered nodes on a lat/lon lattice with a height, for the 3-D
              thermocline surface.
    Profile   one vertical column of temperature against depth.

The sources are irregular in different ways and are regularised here rather
than in the renderer: OISST and altimetry arrive as a dense grid with holes
over land, TAO arrives as eight moorings on their own depth schedules. The
renderer should never have to know the difference.

Anomalies are computed against a per-calendar-month climatology built from the
feed's own record, for the same reason the atmosphere module standardises per
calendar month: the equatorial thermocline has a large annual cycle, and an
anomaly measured against an all-month mean is mostly that cycle.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass, field as dc_field
from datetime import date, datetime

# The TAO/TRITON Pacific moorings, west to east. RAMA (Indian) and PIRATA
# (Atlantic) share the same feed and are filtered out by longitude.
PACIFIC_LON = (165.0, 180.0, 190.0, 205.0, 220.0, 235.0, 250.0, 265.0)

# Target lattice for the interpolated depth section.
SECTION_DEPTHS = tuple(float(d) for d in range(0, 301, 10))
SECTION_LONS = tuple(float(x) for x in range(165, 266, 5))

# A climatology needs enough years per calendar month to mean anything.
MIN_CLIM_YEARS = 8


def _num(text: str) -> float | None:
    """ERDDAP writes NaN for missing; everything else should parse."""
    try:
        value = float(text)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(value) or math.isinf(value) else value


def read_csv(text: str) -> tuple[list[str], list[list]]:
    """Read an ERDDAP CSV response into column names and typed rows.

    ERDDAP emits a name row, then a units row, then data. Numeric columns come
    back as floats with NaN for missing, time columns stay strings. Anything
    that will not parse as a number is kept verbatim, which is what makes the
    same reader work for both griddap and tabledap.
    """
    reader = csv.reader(io.StringIO(text))
    try:
        names = next(reader)
        next(reader)  # units row
    except StopIteration:
        return [], []
    rows: list[list] = []
    for raw in reader:
        if len(raw) != len(names):
            continue
        out: list = []
        for cell in raw:
            cell = cell.strip()
            if cell[:4].isdigit() and "-" in cell and ":" in cell:
                out.append(cell)  # an ISO timestamp
            else:
                out.append(_num(cell))
        rows.append(out)
    return [n.strip() for n in names], rows


def column(names: list[str], wanted: str) -> int:
    try:
        return names.index(wanted)
    except ValueError as exc:
        raise ValueError(f"column {wanted!r} not in {names}") from exc


def _day(stamp: str) -> str:
    return stamp[:10]


def _ym(stamp: str) -> tuple[int, int]:
    return int(stamp[0:4]), int(stamp[5:7])


@dataclass(frozen=True)
class Field:
    """A regular lattice of values with labelled axes.

    ``values[row][col]`` indexes by y then x, with None for missing. ``y`` runs
    in whatever direction the data does; the renderer decides which way is up,
    because latitude increases upward on a map while depth increases downward
    on a section.
    """

    x: tuple[float, ...]
    y: tuple[float, ...]
    values: tuple[tuple[float | None, ...], ...]
    label: str
    units: str
    x_name: str = "longitude"
    y_name: str = "latitude"
    as_of: str = ""
    y_labels: tuple[str, ...] = ()
    note: str = ""

    @property
    def rows(self) -> int:
        return len(self.y)

    @property
    def cols(self) -> int:
        return len(self.x)

    def finite(self) -> list[float]:
        return [v for row in self.values for v in row if v is not None]

    def span(self) -> tuple[float, float]:
        """Symmetric limits for a diverging field, plain limits otherwise."""
        values = self.finite()
        if not values:
            return (-1.0, 1.0)
        return (min(values), max(values))

    def robust_span(self, low: float = 0.02, high: float = 0.98) -> tuple[float, float]:
        """Percentile limits, so one bad pixel does not flatten the colour ramp."""
        values = sorted(self.finite())
        if not values:
            return (-1.0, 1.0)
        lo = values[min(len(values) - 1, int(low * len(values)))]
        hi = values[min(len(values) - 1, int(high * len(values)))]
        return (lo, hi) if hi > lo else (lo - 1.0, lo + 1.0)

    def at(self, row: int, col: int) -> float | None:
        if 0 <= row < self.rows and 0 <= col < self.cols:
            return self.values[row][col]
        return None

    def row_mean(self, row: int) -> float | None:
        values = [v for v in self.values[row] if v is not None]
        return sum(values) / len(values) if values else None

    def coverage(self) -> float:
        total = self.rows * self.cols
        return len(self.finite()) / total if total else 0.0


@dataclass(frozen=True)
class MeshNode:
    lat: float
    lon: float
    height: float
    anomaly: float | None = None


@dataclass(frozen=True)
class Mesh:
    """Scattered nodes on a lat/lon lattice, for the 3-D surface."""

    nodes: tuple[MeshNode, ...]
    label: str
    units: str
    as_of: str = ""
    note: str = ""

    @property
    def lats(self) -> tuple[float, ...]:
        return tuple(sorted({n.lat for n in self.nodes}))

    @property
    def lons(self) -> tuple[float, ...]:
        return tuple(sorted({n.lon for n in self.nodes}))

    def lookup(self) -> dict[tuple[float, float], MeshNode]:
        return {(n.lat, n.lon): n for n in self.nodes}


@dataclass(frozen=True)
class Profile:
    """One mooring's temperature against depth."""

    lon: float
    depths: tuple[float, ...]
    values: tuple[float, ...]
    anomalies: tuple[float | None, ...] = ()
    as_of: str = ""

    def isotherm(self, target: float = 20.0) -> float | None:
        """Depth of an isotherm, linearly interpolated between samples."""
        for i in range(len(self.depths) - 1):
            top, bottom = self.values[i], self.values[i + 1]
            if (top - target) * (bottom - target) <= 0 and top != bottom:
                span = (top - target) / (top - bottom)
                return self.depths[i] + span * (self.depths[i + 1] - self.depths[i])
        return None


def tilt(depths, ends: int = 2):
    """West-minus-east thermocline tilt, and the two endpoint means behind it.

    Returns ``(drop, west, east)`` in metres, or ``None`` if either end is too
    thin to average. Three panels and the terminal report all quote this
    quantity, and they have to quote the same one: a reader comparing the
    section against the report is checking the instrument, not the ocean.

    Each end is averaged over ``ends`` moorings rather than read off the single
    outermost one. That costs a little of the basin span and buys immunity to
    one mooring that has drifted, gone missing or come back warm, which on this
    array is common enough that the single-pair version swings by ten metres
    between runs for no oceanographic reason at all.
    """
    known = [d for d in depths if d is not None]
    if ends < 1 or len(known) < 2 * ends:
        return None
    west = sum(known[:ends]) / ends
    east = sum(known[-ends:]) / ends
    return west - east, west, east


# --- griddap: OISST and altimetry -------------------------------------------
def grid_map(
    text: str, value_key: str, label: str, units: str, note: str = ""
) -> Field:
    """A single-time lat/lon field from a griddap CSV response.

    ERDDAP returns one row per cell in row-major order, but the response is not
    guaranteed to be sorted and land cells come back as NaN, so the lattice is
    rebuilt from the distinct axis values rather than assumed.
    """
    names, rows = read_csv(text)
    if not rows:
        raise ValueError(f"{label}: empty response")
    lat_i = column(names, "latitude")
    lon_i = column(names, "longitude")
    val_i = column(names, value_key)
    time_i = names.index("time") if "time" in names else None

    lats = sorted({r[lat_i] for r in rows if r[lat_i] is not None})
    lons = sorted({r[lon_i] for r in rows if r[lon_i] is not None})
    lat_at = {v: i for i, v in enumerate(lats)}
    lon_at = {v: i for i, v in enumerate(lons)}
    grid: list[list[float | None]] = [[None] * len(lons) for _ in lats]
    stamp = ""
    for row in rows:
        if row[lat_i] is None or row[lon_i] is None:
            continue
        grid[lat_at[row[lat_i]]][lon_at[row[lon_i]]] = row[val_i]
        if time_i is not None and not stamp and isinstance(row[time_i], str):
            stamp = _day(row[time_i])

    return Field(
        x=tuple(lons), y=tuple(lats),
        values=tuple(tuple(r) for r in grid),
        label=label, units=units, x_name="longitude", y_name="latitude",
        as_of=stamp, note=note,
    )


def grid_hovmoller(
    text: str, value_key: str, label: str, units: str, note: str = ""
) -> Field:
    """Time by longitude, averaged across the latitudes in the request.

    The equatorial strip is requested a few rows wide and meaned here rather
    than sampled on a single row, because a one-row sample of a 0.25 degree
    product is noisy enough to invent structure that is not there.
    """
    names, rows = read_csv(text)
    if not rows:
        raise ValueError(f"{label}: empty response")
    time_i = column(names, "time")
    lon_i = column(names, "longitude")
    val_i = column(names, value_key)

    bucket: dict[tuple[str, float], list[float]] = {}
    for row in rows:
        if row[val_i] is None or row[lon_i] is None:
            continue
        bucket.setdefault((_day(row[time_i]), row[lon_i]), []).append(row[val_i])

    times = sorted({k[0] for k in bucket})
    lons = sorted({k[1] for k in bucket})
    lon_at = {v: i for i, v in enumerate(lons)}
    grid: list[list[float | None]] = [[None] * len(lons) for _ in times]
    for index, stamp in enumerate(times):
        for lon in lons:
            values = bucket.get((stamp, lon))
            if values:
                grid[index][lon_at[lon]] = sum(values) / len(values)

    return Field(
        x=tuple(lons), y=tuple(float(i) for i in range(len(times))),
        values=tuple(tuple(r) for r in grid),
        label=label, units=units, x_name="longitude", y_name="time",
        as_of=times[-1] if times else "", y_labels=tuple(times), note=note,
    )


# --- tabledap: TAO/TRITON moorings ------------------------------------------
def _tao_rows(text: str, value_key: str) -> list[tuple[str, float, float, float]]:
    """(time, lon, depth-or-zero, value) for Pacific moorings only."""
    names, rows = read_csv(text)
    time_i = column(names, "time")
    lon_i = column(names, "longitude")
    val_i = column(names, value_key)
    depth_i = names.index("depth") if "depth" in names else None
    out = []
    for row in rows:
        lon, value = row[lon_i], row[val_i]
        if lon is None or value is None or not isinstance(row[time_i], str):
            continue
        if not 140.0 <= lon <= 290.0:  # RAMA and PIRATA share the feed
            continue
        depth = row[depth_i] if depth_i is not None else 0.0
        if depth is None:
            continue
        out.append((row[time_i], lon, depth, value))
    return out


def _interp(points: list[tuple[float, float]], target: float) -> float | None:
    """Linear interpolation over sorted (coordinate, value) pairs, no extrapolation."""
    if not points:
        return None
    if len(points) == 1:
        return points[0][1] if abs(points[0][0] - target) < 1e-9 else None
    if target < points[0][0] or target > points[-1][0]:
        return None
    for i in range(len(points) - 1):
        left, right = points[i], points[i + 1]
        if left[0] <= target <= right[0]:
            if right[0] == left[0]:
                return left[1]
            frac = (target - left[0]) / (right[0] - left[0])
            return left[1] + frac * (right[1] - left[1])
    return None


def profiles(text: str, when: str | None = None) -> tuple[list[Profile], str]:
    """Vertical temperature profiles for the most recent month with data."""
    rows = _tao_rows(text, "T_20")
    if not rows:
        raise ValueError("TAO temperature: no Pacific rows")
    stamp = when or max(r[0] for r in rows)
    month = _ym(stamp)
    columns: dict[float, list[tuple[float, float]]] = {}
    for time_stamp, lon, depth, value in rows:
        if _ym(time_stamp) == month:
            columns.setdefault(lon, []).append((depth, value))
    out = []
    for lon in sorted(columns):
        pairs = sorted(columns[lon])
        out.append(Profile(lon, tuple(p[0] for p in pairs),
                           tuple(p[1] for p in pairs), as_of=stamp[:7]))
    return out, stamp


def section(text: str, anomaly: bool = False) -> Field:
    """Equatorial temperature on a regular depth-by-longitude lattice.

    The moorings sit at eight longitudes on their own depth schedules, so the
    field is built in two interpolation passes: down each mooring onto a common
    depth axis, then across longitude between moorings. Cells outside the array
    stay empty rather than being extrapolated, because the shape of the
    thermocline east of 110W is exactly the kind of thing that should not be
    invented.
    """
    rows = _tao_rows(text, "T_20")
    if not rows:
        raise ValueError("TAO temperature: no Pacific rows")
    stamp = max(r[0] for r in rows)
    month = _ym(stamp)

    climatology: dict[tuple[float, float, int], list[float]] = {}
    latest: dict[float, list[tuple[float, float]]] = {}
    for time_stamp, lon, depth, value in rows:
        year, mon = _ym(time_stamp)
        climatology.setdefault((lon, depth, mon), []).append(value)
        if (year, mon) == month:
            latest.setdefault(lon, []).append((depth, value))

    def cell(lon: float, depth: float) -> float | None:
        pairs = sorted(latest.get(lon, []))
        value = _interp(pairs, depth)
        if value is None or not anomaly:
            return value
        base = climatology.get((lon, depth, month[1]))
        if base is None or len(base) < MIN_CLIM_YEARS:
            # Interpolate the climatology down the same column rather than drop
            # the cell: mooring depth schedules changed over the record.
            column_clim = sorted(
                (d, sum(v) / len(v))
                for (l, d, m), v in climatology.items()
                if l == lon and m == month[1] and len(v) >= MIN_CLIM_YEARS
            )
            reference = _interp(column_clim, depth)
        else:
            reference = sum(base) / len(base)
        return None if reference is None else value - reference

    moorings = sorted(latest)
    grid: list[list[float | None]] = []
    for depth in SECTION_DEPTHS:
        row: list[float | None] = []
        at_depth = [(lon, cell(lon, depth)) for lon in moorings]
        known = [(lon, v) for lon, v in at_depth if v is not None]
        for lon in SECTION_LONS:
            row.append(_interp(known, lon))
        grid.append(row)

    what = "temperature anomaly" if anomaly else "temperature"
    return Field(
        x=SECTION_LONS, y=SECTION_DEPTHS,
        values=tuple(tuple(r) for r in grid),
        label=f"Equatorial Pacific {what}",
        units="°C", x_name="longitude", y_name="depth",
        as_of=stamp[:7],
        note=f"TAO/TRITON moorings at {', '.join(_lon_name(l) for l in moorings)}",
    )


def iso_hovmoller(text: str, months: int = 24, anomaly: bool = False) -> Field:
    """20 °C isotherm depth, time by longitude.

    This is the cleanest available picture of Kelvin wave propagation: a
    downwelling wave appears as a band of deepened thermocline sloping from
    upper left to lower right as it crosses the basin in about two months.
    """
    rows = _tao_rows(text, "ISO_6")
    if not rows:
        raise ValueError("TAO isotherm: no Pacific rows")

    monthly: dict[tuple[str, float], list[float]] = {}
    climatology: dict[tuple[float, int], list[float]] = {}
    for time_stamp, lon, _depth, value in rows:
        key = time_stamp[:7]
        monthly.setdefault((key, lon), []).append(value)
        climatology.setdefault((lon, int(key[5:7])), []).append(value)

    stamps = sorted({k[0] for k in monthly})[-months:]
    # The array has moved over its lifetime: moorings at 143E, 156E, 152W and
    # others reported for years and are long gone. Their columns are not gaps
    # in the data, they are longitudes that no longer exist, and leaving them
    # in prints a diagram that is two thirds empty for no reason.
    window = set(stamps)
    present: dict[float, int] = {}
    for stamp, lon in monthly:
        if stamp in window:
            present[lon] = present.get(lon, 0) + 1
    lons = sorted(lon for lon, count in present.items() if count >= len(stamps) * 0.5)
    lon_at = {v: i for i, v in enumerate(lons)}
    grid: list[list[float | None]] = [[None] * len(lons) for _ in stamps]
    for index, stamp in enumerate(stamps):
        for lon in lons:
            values = monthly.get((stamp, lon))
            if not values:
                continue
            value = sum(values) / len(values)
            if anomaly:
                base = climatology.get((lon, int(stamp[5:7])), [])
                if len(base) < MIN_CLIM_YEARS:
                    continue
                value -= sum(base) / len(base)
            grid[index][lon_at[lon]] = value

    what = "20 °C isotherm depth anomaly" if anomaly else "20 °C isotherm depth"
    return Field(
        x=tuple(lons), y=tuple(float(i) for i in range(len(stamps))),
        values=tuple(tuple(r) for r in grid),
        label=f"Equatorial {what}", units="m",
        x_name="longitude", y_name="time",
        as_of=stamps[-1] if stamps else "", y_labels=tuple(stamps),
        note="Positive anomaly is a deeper thermocline." if anomaly else "",
    )


def thermocline_mesh(text: str, iso_text: str | None = None) -> Mesh:
    """The thermocline as a surface over latitude and longitude.

    Averaged over the last fortnight of daily values, because a single day at a
    single mooring is dominated by tropical instability waves and the surface
    comes out corrugated for reasons that have nothing to do with ENSO.
    """
    rows = _tao_rows(text, "ISO_6")
    if not rows:
        raise ValueError("TAO isotherm: no Pacific rows")
    names, raw = read_csv(text)
    lat_i = column(names, "latitude")
    lon_i = column(names, "longitude")
    time_i = column(names, "time")
    val_i = column(names, "ISO_6")

    bucket: dict[tuple[float, float], list[float]] = {}
    stamps: list[str] = []
    for row in raw:
        lat, lon, value = row[lat_i], row[lon_i], row[val_i]
        if lat is None or lon is None or value is None:
            continue
        if not 140.0 <= lon <= 290.0:
            continue
        bucket.setdefault((lat, lon), []).append(value)
        if isinstance(row[time_i], str):
            stamps.append(_day(row[time_i]))

    climatology: dict[tuple[float, int], list[float]] = {}
    if iso_text:
        for time_stamp, lon, _d, value in _tao_rows(iso_text, "ISO_6"):
            climatology.setdefault((lon, int(time_stamp[5:7])), []).append(value)
    month = int(stamps[-1][5:7]) if stamps else 0

    nodes = []
    for (lat, lon), values in sorted(bucket.items()):
        height = sum(values) / len(values)
        base = climatology.get((lon, month), [])
        anomaly = (height - sum(base) / len(base)) if len(base) >= MIN_CLIM_YEARS else None
        nodes.append(MeshNode(lat=lat, lon=lon, height=height, anomaly=anomaly))

    return Mesh(
        nodes=tuple(nodes), label="20 °C isotherm depth", units="m",
        as_of=max(stamps) if stamps else "",
        note="Mean of the last fortnight of daily values at each mooring.",
    )


# --- labels -----------------------------------------------------------------
def _lon_name(lon: float) -> str:
    """Longitude in the form a meteorologist reads: 165E, 180, 110W."""
    value = lon % 360.0
    if value == 0 or value == 180:
        return f"{value:.0f}"
    if value < 180:
        return f"{value:.0f}E"
    return f"{360.0 - value:.0f}W"


def _lat_name(lat: float) -> str:
    if abs(lat) < 0.5:
        return "EQ"
    return f"{abs(lat):.0f}{'N' if lat > 0 else 'S'}"


lon_name = _lon_name
lat_name = _lat_name


# --- Nino regions, for drawing on a map -------------------------------------
@dataclass(frozen=True)
class Box:
    key: str
    label: str
    lon0: float
    lon1: float
    lat0: float
    lat1: float


NINO_BOXES: tuple[Box, ...] = (
    Box("nino4", "Nino-4", 160.0, 210.0, -5.0, 5.0),
    Box("nino34", "Nino-3.4", 190.0, 240.0, -5.0, 5.0),
    Box("nino3", "Nino-3", 210.0, 270.0, -5.0, 5.0),
    Box("nino12", "Nino-1+2", 270.0, 280.0, -10.0, 0.0),
)


def box_mean(grid: Field, box: Box) -> float | None:
    """Area-weighted mean of a lat/lon field inside a box.

    Weighted by cos(latitude), because a 0.25 degree cell at 25N covers about
    nine tenths of the area of one on the equator and an unweighted mean of a
    wide box quietly over-counts the poleward rows.
    """
    total = 0.0
    weight = 0.0
    for row, lat in enumerate(grid.y):
        if not box.lat0 <= lat <= box.lat1:
            continue
        cos = math.cos(math.radians(lat))
        for col, lon in enumerate(grid.x):
            east = lon % 360.0
            # A box given west-of-east in 0..360 is an ordinary interval; one
            # given the other way round has wrapped past 360, and is the union
            # of the two pieces either side of the seam. Testing it as an
            # ordinary interval makes it the empty set, so a box over the
            # dateline used to return None and the panel above it a dash.
            inside = (box.lon0 <= east <= box.lon1 if box.lon0 <= box.lon1
                      else east >= box.lon0 or east <= box.lon1)
            if not inside:
                continue
            value = grid.values[row][col]
            if value is not None:
                total += value * cos
                weight += cos
    return total / weight if weight else None


def warm_pool_edge(grid: Field, threshold: float = 28.0) -> float | None:
    """Longitude of the eastern edge of the 28 °C warm pool on the equator.

    Only meaningful on an absolute SST field. The eastward march of this edge
    is one of the clearest single numbers for how far the event has displaced
    the Pacific convection centre.

    The edge is where the pool ends: walking east from the warmest equatorial
    water of the open western Pacific, 130E to 160W, the last column still at
    the threshold before the first one below it. Warm water further east that
    the pool does not reach is not its edge: on 8 September 2026 the coastal
    cells off Colombia were above 28 °C at 79W while the pool itself ended near
    109W, and taking the easternmost warm column anywhere put the edge on the
    coast. The walk does not start west of 130E, where coastal cells in the
    Maritime Continent run warmer than the open ocean and the Maluku Sea
    upwells below 28 °C. A column with no ocean in it - land on the equator -
    does not end the pool.
    """
    rows = [row for row, lat in enumerate(grid.y) if abs(lat) <= 2.5]
    profile = []
    for col, lon in enumerate(grid.x):
        values = [grid.values[r][col] for r in rows if grid.values[r][col] is not None]
        if values:
            profile.append((lon, sum(values) / len(values)))
    west = [pair for pair in profile if 130.0 <= pair[0] < 200.0] or profile
    if not west:
        return None
    core = max(west, key=lambda pair: pair[1])
    if core[1] < threshold:
        return None
    edge = core[0]
    for lon, mean in profile[profile.index(core) + 1:]:
        if mean < threshold:
            break
        edge = lon
    return edge


# --- contouring -------------------------------------------------------------
def contour(grid: Field, level: float) -> list[list[tuple[float, float]]]:
    """Marching-squares contour at one level, in data coordinates.

    Returns unjoined segments. Drawing them as separate two-point paths is
    enough for an isotherm on a section, and avoids the bookkeeping of walking
    contours into closed rings for no visual gain at this size.
    """
    segments: list[list[tuple[float, float]]] = []
    for row in range(grid.rows - 1):
        for col in range(grid.cols - 1):
            corners = [
                (grid.x[col], grid.y[row], grid.values[row][col]),
                (grid.x[col + 1], grid.y[row], grid.values[row][col + 1]),
                (grid.x[col + 1], grid.y[row + 1], grid.values[row + 1][col + 1]),
                (grid.x[col], grid.y[row + 1], grid.values[row + 1][col]),
            ]
            if any(c[2] is None for c in corners):
                continue
            crossings = []
            for i in range(4):
                x0, y0, v0 = corners[i]
                x1, y1, v1 = corners[(i + 1) % 4]
                if (v0 - level) * (v1 - level) < 0:
                    frac = (level - v0) / (v1 - v0)
                    crossings.append((x0 + frac * (x1 - x0), y0 + frac * (y1 - y0)))
            if len(crossings) == 2:
                segments.append([crossings[0], crossings[1]])
            elif len(crossings) == 4:
                # Saddle: join them the short way rather than crossing over.
                segments.append([crossings[0], crossings[1]])
                segments.append([crossings[2], crossings[3]])
    return segments


@dataclass
class SpatialState:
    """Everything spatial that a run managed to build."""

    sst_map: Field | None = None
    sst_global: Field | None = None
    sst_hov: Field | None = None
    ssh_map: Field | None = None
    ssh_hov: Field | None = None
    section: Field | None = None
    section_anomaly: Field | None = None
    iso_hov: Field | None = None
    iso_hov_anomaly: Field | None = None
    mesh: Mesh | None = None
    profiles: tuple[Profile, ...] = ()
    box_means: dict[str, float] = dc_field(default_factory=dict)
    warm_pool: float | None = None
    stale: dict[str, int] = dc_field(default_factory=dict)
    notes: list[str] = dc_field(default_factory=list)

    @property
    def available(self) -> bool:
        return any(
            getattr(self, name) is not None
            for name in ("sst_map", "sst_hov", "section", "iso_hov", "mesh")
        )


def age_days(stamp: str, today: date | None = None) -> int | None:
    """How stale a field is, in days, from its own as_of stamp."""
    if not stamp:
        return None
    for pattern in ("%Y-%m-%d", "%Y-%m"):
        try:
            when = datetime.strptime(stamp, pattern).date()
        except ValueError:
            continue
        return ((today or date.today()) - when).days
    return None
