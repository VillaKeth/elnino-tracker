"""Westerly wind events, day by day, from CCMP's near-real-time 10 m winds.

The tracker's other westerly forcing is monthly: ``atmosphere`` counts months
whose 850 hPa western-Pacific trade index is strongly westerly, and says
itself that a true westerly wind burst lasts days and needs daily winds to
resolve. This module resolves them, as Harrison and Vecchi (1997) defined
them, from Remote Sensing Systems' CCMP version 2.1 near-real-time analysis
(``sources.wind_daily``): 180 days of analyses 12 hours apart, on every ninth
of CCMP's quarter-degree cells.

The definition
--------------
A westerly wind event of type X is "any period of 3 or more days for which
the 10-m zonal wind anomaly, averaged over region X and smoothed by a
three-point triangle filter in time (half-power point at 2.75 days), exceeded
2 m s-1" (Harrison and Vecchi 1997, NOAA Tech. Memo. ERL PMEL-109), on
12-hourly analyses against a monthly climatology linearly interpolated in
time. Their eight regions, as McGregor et al. (2016) list them, are
``REGIONS``. Here:

- a cell's anomaly is its analysis less the vendored base (``windclim``),
  interpolated linearly between the middles of the months either side;
- a region's anomaly is the cosine-weighted mean of its cells, and it has
  none when fewer than three quarters of them have a value;
- the filter is 1/4, 1/2, 1/4 over an analysis and the ones 12 hours either
  side, with no value where either is missing or not 12 hours away, so a gap
  breaks a run and never bridges one. Its response is 1/2 + 1/2 cos(2 pi f
  dt), half power at 5.49 dt: 2.75 days at 12 hours, the memo's own filter;
- an event is a run of at least 6 smoothed analyses 12 hours apart, every one
  strictly above 2 m/s: three days. Its centre is its largest smoothed value
  (the first of equals) and its peak that value, the memo's "maximum averaged
  anomaly"; its point peak is the largest unsmoothed cell anomaly in the
  region at the centre; its wind measure is the sum of its smoothed values
  times 12 hours, in metres (the memo's composites: 1.1-1.6 x 10^6 m);
- events in bordering regions centred within 3 days of each other overlap,
  and each counts as the region of the largest peak among it and those it
  overlaps, never as a weaker one.

Against a monthly climatology an El Nino's own westerly anomaly counts too,
so in a strong event a run lasts weeks. Harrison and Vecchi's 351 events of
1986-1995 (the memo's Table 1) last 5 days at the median and 32.5 at the
longest; a run longer than any of theirs is ``sustained``, a westerly anomaly
more than a burst.

The window's ends
-----------------
The latest analysis is smoothed only when the next one comes. A run reaching
a region's latest smoothed analysis has not been seen to end: it is under
way, and under way short of three days it is building, reported but never
counted. A run from a region's first smoothed analysis began before the
window and says so; one of those short of three days is dropped, since
whether it reached three days is out of view.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

from . import windclim
from .grids import Field, column, lat_name, lon_name, read_csv

THRESHOLD = 2.0                 # m/s; a smoothed regional anomaly strictly above it counts
STEP = timedelta(hours=12)      # between the analyses the filter and a run take
MIN_SAMPLES = 6                 # analyses in a run: three days
FILTER = (0.25, 0.5, 0.25)      # the three-point triangle
OVERLAP = timedelta(days=3)     # between the centres of overlapping events
COVER = 0.75                    # of a region's cells, for it to have a mean
BAND = (-5.0, 5.0)              # the Hovmoller's latitudes
# Harrison and Vecchi's complete list (PMEL-109, Table 1): 351 events in
# 1986-1995, the longest 32.5 days.
HV97_EVENTS, HV97_LONGEST = 351, 32.5


@dataclass(frozen=True)
class Region:
    """One of Harrison and Vecchi's regions; longitudes in degrees east."""

    key: str
    name: str
    south: float
    north: float
    west: float
    east: float

    def holds(self, lat: float, lon: float) -> bool:
        """Whether a cell is in the region, its edges included as Harrison and
        Vecchi's were (five 2.5-degree points in ten degrees of latitude); no
        cell of the feed's grid lies on an edge."""
        return self.south <= lat <= self.north and self.west <= lon <= self.east

    @property
    def span(self) -> str:
        return (f"{lon_name(self.west)}-{lon_name(self.east)}, "
                f"{lat_name(self.south)}-{lat_name(self.north)}")


REGIONS = (
    Region("NW", "north-west", 5, 15, 120, 150),
    Region("N", "north", 5, 15, 150, 180),
    Region("NE", "north-east", 5, 15, 180, 210),
    Region("W", "west", -5, 5, 130, 155),
    Region("C", "central", -5, 5, 155, 180),
    Region("E", "east", -5, 5, 180, 210),
    Region("S", "south", -15, -5, 150, 180),
    Region("SE", "south-east", -15, -5, 180, 210),
)
REGIONS_BY_KEY = {region.key: region for region in REGIONS}
EQUATORIAL = ("W", "C", "E")
_ORDER = {region.key: index for index, region in enumerate(REGIONS)}


def _facing(a0: float, a1: float, b0: float, b1: float) -> bool:
    """Two edges on one line share more than half the shorter of them."""
    return min(a1, b1) - max(a0, b0) > 0.5 * min(a1 - a0, b1 - b0)


def neighbours(a: Region, b: Region) -> bool:
    """Whether two regions border, as the overlap rule needs: they share
    more than half the shorter of their facing edges (the memo's "more than
    half an edge"). N and W share 150-155E, five degrees, and do not."""
    on_parallel = a.north == b.south or b.north == a.south
    on_meridian = a.east == b.west or b.east == a.west
    return ((on_parallel and _facing(a.west, a.east, b.west, b.east))
            or (on_meridian and _facing(a.south, a.north, b.south, b.north)))


@lru_cache(maxsize=None)
def _cells(region: Region) -> tuple[tuple[int, int, float], ...]:
    """The base's cells in a region: (lat index, lon index, cosine weight)."""
    return tuple((i, j, math.cos(math.radians(lat)))
                 for i, lat in enumerate(windclim.LATS)
                 for j, lon in enumerate(windclim.LONS) if region.holds(lat, lon))


# --- the base between months ------------------------------------------------
def _middle(year: int, month: int) -> datetime:
    """A month's middle: half its length after its first instant."""
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    after = datetime(year + month // 12, month % 12 + 1, 1, tzinfo=timezone.utc)
    return start + (after - start) / 2


def climate(when: datetime) -> list[list[float | None]]:
    """The base at ``when``, on ``windclim``'s cells: each cell's calendar-month
    mean, interpolated linearly in time between the middles either side."""
    year, month = when.year, when.month
    if when < _middle(year, month):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
    after = (year + 1, 1) if month == 12 else (year, month + 1)
    start = _middle(year, month)
    weight = (when - start) / (_middle(*after) - start)
    return [[None if a is None or b is None else a + (b - a) * weight
             for a, b in zip(row_a, row_b)]
            for row_a, row_b in zip(windclim.MONTHLY[month - 1], windclim.MONTHLY[after[1] - 1])]


# --- the feed -----------------------------------------------------------------
def read(text: str) -> list[tuple[datetime, list[list[float | None]]]]:
    """The feed's analyses in time order, each a grid on ``windclim``'s cells
    (``grid[lat][lon]``, None where the analysis has no value). One with no
    value at all, listed before its values are in, is not read."""
    names, rows = read_csv(text)
    time_i, lat_i, lon_i, u_i = (column(names, name)
                                 for name in ("time", "latitude", "longitude", "uwnd"))
    lat_at = {round(lat, 3): i for i, lat in enumerate(windclim.LATS)}
    lon_at = {round(lon, 3): j for j, lon in enumerate(windclim.LONS)}
    grids: dict[str, list[list[float | None]]] = {}
    for row in rows:
        stamp, lat, lon = row[time_i], row[lat_i], row[lon_i]
        if not isinstance(stamp, str) or lat is None or lon is None:
            continue
        i, j = lat_at.get(round(lat, 3)), lon_at.get(round(lon % 360.0, 3))
        if i is None or j is None:
            continue
        grid = grids.get(stamp)
        if grid is None:
            grid = grids[stamp] = [[None] * len(windclim.LONS) for _ in windclim.LATS]
        grid[i][j] = row[u_i]
    analyses = [(datetime.fromisoformat(stamp.replace("Z", "+00:00")), grid)
                for stamp, grid in grids.items()
                if any(value is not None for cells in grid for value in cells)]
    if not analyses:
        raise ValueError("wind feed: no value on the base's cells")
    return sorted(analyses, key=lambda analysis: analysis[0])


def regional(grid: list[list[float | None]], region: Region) -> float | None:
    """A region's anomaly at an analysis: its cells' mean weighted by the
    cosine of latitude, or None short of three quarters of its cells."""
    cells = _cells(region)
    total = weights = 0.0
    count = 0
    for i, j, weight in cells:
        value = grid[i][j]
        if value is not None:
            total += weight * value
            weights += weight
            count += 1
    return total / weights if count and count >= COVER * len(cells) else None


def smooth(times: list[datetime], values: list[float | None]) -> list[float | None]:
    """The triangle filter: none at either end, at a missing value, or where
    either neighbour is missing or not 12 hours away."""
    out: list[float | None] = [None] * len(values)
    before, here, after = FILTER
    for k in range(1, len(values) - 1):
        trio = values[k - 1:k + 2]
        if any(value is None for value in trio):
            continue
        if times[k] - times[k - 1] != STEP or times[k + 1] - times[k] != STEP:
            continue
        out[k] = before * trio[0] + here * trio[1] + after * trio[2]
    return out


def runs(times: list[datetime], smoothed: list[float | None]) -> list[tuple[int, int]]:
    """Each run of analyses strictly above the threshold and 12 hours apart,
    as (first index, last index). A series from ``smooth`` has no value beside
    a gap, so the time check matters only for any other series."""
    found: list[tuple[int, int]] = []
    start: int | None = None
    for k, value in enumerate(smoothed):
        above = value is not None and value > THRESHOLD
        if start is not None and not (above and times[k] - times[k - 1] == STEP):
            found.append((start, k - 1))
            start = None
        if above and start is None:
            start = k
    if start is not None:
        found.append((start, len(smoothed) - 1))
    return found


# --- what the feed holds ------------------------------------------------------
@dataclass(frozen=True)
class Event:
    """A westerly wind event: a region's run of three days or more above 2 m/s."""

    region: str
    first: datetime             # the first smoothed analysis above the threshold
    last: datetime              # and the last
    samples: int                # analyses in the run, 12 hours each
    centre: datetime            # the analysis of its largest smoothed value
    peak: float                 # that value, the maximum averaged anomaly (m/s)
    point_peak: float           # the largest cell anomaly in the region at the centre
    point: tuple[float, float]  # and its cell, (lat, lon east)
    measure: float              # the smoothed values' sum times 12 hours (m)
    ongoing: bool               # reaches the region's latest smoothed analysis
    from_start: bool            # from the region's first: began before the window
    overlaps: tuple[str, ...] = ()  # regions of the events it overlaps
    counted_as: str = ""        # region of the largest peak among it and them

    @property
    def days(self) -> float:
        return self.samples * STEP / timedelta(days=1)

    @property
    def sustained(self) -> bool:
        """Longer than any of Harrison and Vecchi's events: more a sustained
        westerly anomaly than a burst."""
        return self.days > HV97_LONGEST


@dataclass(frozen=True)
class Building:
    """A run under way above the threshold, short of three days: never counted."""

    region: str
    since: datetime             # its first analysis above the threshold
    samples: int
    latest: float               # its latest smoothed value (m/s)

    @property
    def days(self) -> float:
        return self.samples * STEP / timedelta(days=1)


@dataclass(frozen=True)
class Winds:
    """The feed read whole, for the card, the JSON, the report and the alert."""

    times: tuple[datetime, ...]
    smoothed: dict[str, tuple[float | None, ...]]  # region -> a value per analysis
    daily: dict[date, dict[str, float]]            # day -> region -> its smoothed mean
    events: tuple[Event, ...]                      # by first analysis
    building: tuple[Building, ...]
    hovmoller: Field

    @property
    def first(self) -> date:
        return self.times[0].date()

    @property
    def last(self) -> date:
        return self.times[-1].date()

    @property
    def under_way(self) -> tuple[Event, ...]:
        return tuple(event for event in self.events if event.ongoing)

    @property
    def latest_first(self) -> tuple[Event, ...]:
        """The events, the latest to end first: those under way, then the rest."""
        return tuple(sorted(self.events, key=lambda event: (event.last, event.first),
                            reverse=True))


def _find(region: Region, times: list[datetime], anomalies: list[list[list[float | None]]],
          smoothed: list[float | None]) -> tuple[list[Event], list[Building]]:
    """A region's events and its building run, from its smoothed series."""
    valued = [k for k, value in enumerate(smoothed) if value is not None]
    events: list[Event] = []
    building: list[Building] = []
    for a, b in runs(times, smoothed):
        samples = b - a + 1
        ongoing = b == valued[-1]
        if samples < MIN_SAMPLES:
            if ongoing:
                building.append(Building(region.key, times[a], samples, smoothed[b]))
            continue
        centre = max(range(a, b + 1), key=lambda k: smoothed[k])
        grid = anomalies[centre]
        point_peak, point = max(
            ((grid[i][j], (windclim.LATS[i], windclim.LONS[j]))
             for i, j, _weight in _cells(region) if grid[i][j] is not None),
            key=lambda cell: cell[0])
        events.append(Event(
            region=region.key, first=times[a], last=times[b], samples=samples,
            centre=times[centre], peak=smoothed[centre], point_peak=point_peak, point=point,
            measure=sum(smoothed[a:b + 1]) * STEP.total_seconds(),
            ongoing=ongoing, from_start=a == valued[0]))
    return events, building


def overlaps(events: list[Event] | tuple[Event, ...]) -> tuple[Event, ...]:
    """Each event with the regions of the bordering regions' events centred
    within 3 days of it, each region once, counted as the region of the
    largest peak among it and them; it keeps its own against an equal peak."""
    out = []
    for event in events:
        region = REGIONS_BY_KEY[event.region]
        partners = [other for other in events
                    if neighbours(region, REGIONS_BY_KEY[other.region])
                    and abs(other.centre - event.centre) <= OVERLAP]
        strongest = max([event, *partners], key=lambda candidate: candidate.peak)
        named = tuple(dict.fromkeys(other.region for other in partners))
        out.append(replace(event, overlaps=named, counted_as=strongest.region))
    return tuple(out)


def _days(times: list[datetime]) -> list[date]:
    first, last = times[0].date(), times[-1].date()
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


def _daily(times: list[datetime], smoothed: dict[str, tuple[float | None, ...]]
           ) -> dict[date, dict[str, float]]:
    """Each day's mean of each region's smoothed analyses that day."""
    daily: dict[date, dict[str, float]] = {day: {} for day in _days(times)}
    for key, series in smoothed.items():
        values: dict[date, list[float]] = {}
        for when, value in zip(times, series):
            if value is not None:
                values.setdefault(when.date(), []).append(value)
        for day, day_values in values.items():
            daily[day][key] = sum(day_values) / len(day_values)
    return daily


def _mean(values: list[float | None]) -> float | None:
    """The mean of the values there are, or None without one."""
    present = [value for value in values if value is not None]
    return sum(present) / len(present) if present else None


def _band(grid: list[list[float | None]]) -> list[float | None]:
    """An analysis's 5S-5N cosine-weighted mean at each longitude, None short
    of three quarters of the band's cells."""
    rows = [(i, math.cos(math.radians(lat))) for i, lat in enumerate(windclim.LATS)
            if BAND[0] <= lat <= BAND[1]]
    out: list[float | None] = []
    for j in range(len(windclim.LONS)):
        valued = [(weight, grid[i][j]) for i, weight in rows if grid[i][j] is not None]
        enough = valued and len(valued) >= COVER * len(rows)
        out.append(sum(w * v for w, v in valued) / sum(w for w, _ in valued) if enough else None)
    return out


def _hovmoller(times: list[datetime], anomalies: list[list[list[float | None]]]) -> Field:
    """A row a day of the 5S-5N anomaly by longitude: the mean of the day's
    analyses with a value there, two 12 hours apart but one on the window's
    first and last days when it ends at 00Z or 06Z; nothing on a day without."""
    by_day: dict[date, list[list[float | None]]] = {}
    for when, grid in zip(times, anomalies):
        by_day.setdefault(when.date(), []).append(_band(grid))
    days = _days(times)
    rows = []
    for day in days:
        bands = by_day.get(day, [])
        rows.append(tuple(_mean([band[j] for band in bands]) for j in range(len(windclim.LONS))))
    labels = tuple(day.isoformat() for day in days)
    return Field(
        x=windclim.LONS, y=tuple(float(k) for k in range(len(days))), values=tuple(rows),
        label="Equatorial 10 m zonal wind anomaly", units="m/s",
        x_name="longitude", y_name="time", as_of=labels[-1], y_labels=labels,
        note="Positive is westerly.",
    )


def analyse(text: str) -> Winds:
    """The feed's westerly wind events, its regions' smoothed anomalies day
    by day, and its Hovmoller. A feed with no smoothed value in any region is
    refused, not read as having no event."""
    analyses = read(text)
    if len(analyses) < 3:
        raise ValueError(f"wind feed: {len(analyses)} analyses, and the filter needs 3")
    times = [when for when, _grid in analyses]
    anomalies = []
    for when, grid in analyses:
        base = climate(when)
        anomalies.append([[None if u is None or b is None else u - b
                           for u, b in zip(row, base_row)]
                          for row, base_row in zip(grid, base)])
    smoothed: dict[str, tuple[float | None, ...]] = {}
    events: list[Event] = []
    building: list[Building] = []
    for region in REGIONS:
        series = smooth(times, [regional(grid, region) for grid in anomalies])
        smoothed[region.key] = tuple(series)
        if any(value is not None for value in series):
            found, growing = _find(region, times, anomalies, series)
            events += found
            building += growing
    if not any(value is not None for series in smoothed.values() for value in series):
        raise ValueError("wind feed: no smoothed value in any region")
    events.sort(key=lambda event: (event.first, _ORDER[event.region]))
    building.sort(key=lambda run: (run.since, _ORDER[run.region]))
    return Winds(
        times=tuple(times), smoothed=smoothed, daily=_daily(times, smoothed),
        events=overlaps(events), building=tuple(building),
        hovmoller=_hovmoller(times, anomalies),
    )
