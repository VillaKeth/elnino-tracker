"""What El Nino has meant at one point on Earth.

Every other tier in this system answers a question about the Pacific, or about
a region named in a catalogue. This one answers the question a reader actually
asks, which is "what about *here*" - a click on a map, resolved to a place, a
grid cell, and a number with a denominator.

Three things are combined, and they are different kinds of claim:

**Measured.** The composite grids: the mean over past El Ninos minus the mean
over neutral years, per season, per cell, over the satellite record, with the
neutral mean beside it so the difference can be stated as a fraction of an
ordinary year, and Welch's t so a difference inside the noise can be said to be
inside the noise. This is the only part that is a measurement, and it is a
measurement of what *has happened*, in four to ten events depending on the
season, not of what will.

**Catalogued.** The teleconnection entries from ``impacts``, which are the
documented mechanisms, and the footprints in ``geo`` that say where each one
lands. These are literature, not this season's data.

**Current.** Where the live storms are, how far the coast is, what the running
event is doing. This is the only part that moves between runs.

They are kept apart in the dossier and on the page, because a reader who
cannot tell a forty-year composite from a five-day forecast will act on the
wrong one.

Resolution, and why there is no interpolation
---------------------------------------------
The precipitation composite is on GPCP's own 2.5 degree grid and the
temperature composite on GHCN-CAMS at 2 degrees. A click is answered with the
cell it lands in and the bounds of that cell, not with a bilinear blend of the
four around it. Interpolation would produce a number that varies smoothly as
the reader moves the cursor, which reads as precision the composite does not
have: the underlying quantity is an average over a 280 km box and a handful of
events, and it genuinely is constant across that box. Saying so is more honest than
drawing a gradient through it.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import atlasdata, composite, geo
from .impacts import CATALOGUE, Teleconnection


# Below this ordinary-year rainfall a percentage change is arithmetic rather
# than information: a tenth of a millimetre a day on a desert cell is a 300%
# increase and still nothing anyone would notice.
DRY_FLOOR = 0.2

SEASONS: tuple[str, ...] = ("DJF", "MAM", "JJA", "SON")
SEASON_LABEL = {
    "DJF": "December to February",
    "MAM": "March to May",
    "JJA": "June to August",
    "SON": "September to November",
}
# Northern-hemisphere naming would be wrong for half the places this atlas can
# be clicked on, so seasons are named by their months and the peak is named by
# what it is: El Nino matures in the boreal winter wherever you are standing.
PEAK_SEASON = "DJF"


def critical(variable: str, season: str) -> float:
    """The |t| a cell must reach to be told apart from an ordinary year.

    The two-sided 95% point of Student's t for that season's own sample,
    stored with the grids. It is not one number for all four seasons: the
    unit of the sample is the event, and June to August has four of them
    where September to November has ten. A season too thin to test has
    none, and nothing in it is significant.
    """
    crit = getattr(composite, f"{variable}_META")[season].get("t_crit")
    return math.inf if crit is None else float(crit)


@dataclass(frozen=True)
class Cell:
    """One composite grid cell, as read at a point."""

    value: float | None       # El Nino mean minus neutral mean
    base: float | None        # the neutral mean itself
    t: float | None           # Welch's t for the difference
    lon0: float = 0.0
    lon1: float = 0.0
    lat0: float = 0.0
    lat1: float = 0.0
    crit: float = math.inf    # the |t| this cell's season must reach

    @property
    def known(self) -> bool:
        return self.value is not None

    @property
    def significant(self) -> bool:
        return self.t is not None and abs(self.t) >= self.crit

    @property
    def percent(self) -> float | None:
        """The difference as a percentage of an ordinary year, where that
        means anything. Temperature has no meaningful percentage, so callers
        ask for this only on precipitation."""
        if self.value is None or self.base is None or self.base < DRY_FLOOR:
            return None
        return self.value / self.base * 100.0

    @property
    def direction(self) -> str:
        if not self.known:
            return "unknown"
        if not self.significant:
            return "no clear signal"
        return "wetter" if (self.value or 0) > 0 else "drier"


@dataclass(frozen=True)
class Seasonal:
    """Both composites for one point in one season."""

    season: str
    precip: Cell
    air: Cell


@dataclass(frozen=True)
class Neighbour:
    km: float
    place: atlasdata.Place


@dataclass(frozen=True)
class Local:
    """The whole dossier for one point."""

    lon: float
    lat: float
    seasons: tuple[Seasonal, ...]
    places: tuple[Neighbour, ...]
    footprints: tuple[str, ...]
    links: tuple[Teleconnection, ...]
    coast_km: float | None
    storms: tuple[dict, ...] = ()

    @property
    def place(self) -> atlasdata.Place | None:
        return self.places[0].place if self.places else None

    @property
    def title(self) -> str:
        if not self.places:
            return f"{_lat_name(self.lat)}, {_lon_name(self.lon)}"
        first = self.places[0]
        # Twenty-five kilometres is about the point at which "you are in this
        # city" stops being true and "the nearest city is" starts being the
        # honest phrasing. Out at sea it is neither, and the coordinate is.
        if first.km <= 25.0:
            return first.place.label
        if first.km <= 400.0:
            return f"{first.km:.0f} km from {first.place.label}"
        return f"{_lat_name(self.lat)}, {_lon_name(self.lon)}"

    @property
    def offshore(self) -> bool:
        return self.coast_km is not None and self.coast_km > 60.0

    def at(self, season: str) -> Seasonal | None:
        for item in self.seasons:
            if item.season == season:
                return item
        return None

    @property
    def peak(self) -> Seasonal | None:
        return self.at(PEAK_SEASON)

    @property
    def strongest(self) -> Seasonal | None:
        """The season whose rainfall signal is furthest from an ordinary year.

        Ranked on t rather than on millimetres, because the question a reader
        is asking is which season the record is most sure about, and a large
        difference in a place where every year differs is not an answer. And
        on t against its own season's bar, because the seasons have different
        samples: -2.48 on June to August's four events is less sure than -1.86
        on December to February's nine.
        """
        scored = [s for s in self.seasons
                  if s.precip.t is not None and s.precip.crit < math.inf]
        if not scored:
            return None
        return max(scored, key=lambda s: abs(s.precip.t or 0.0) / s.precip.crit)


@dataclass
class AtlasState:
    """The tier, as the pipeline carries it."""

    available: bool = False
    anchors: tuple[Local, ...] = ()
    # Per season, the precipitation composite's sample as stored with it:
    # warm_events, warm_months, base_years, base_months, t_crit, in_progress.
    samples: dict[str, dict] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    @property
    def in_progress(self) -> tuple[int, ...]:
        """The event under way when the grids were built, left out of them."""
        return tuple(sorted({year for block in self.samples.values()
                             for year in block.get("in_progress", ())}))


# --- grid access -------------------------------------------------------------

_GRIDS: dict[tuple[str, str, str], tuple] = {}


def _axis(name: str) -> tuple[float, ...]:
    key = ("axis", name, "")
    if key not in _GRIDS:
        _GRIDS[key] = composite._axis(getattr(composite, name))
    return _GRIDS[key]


def _grid(variable: str, season: str, kind: str) -> tuple:
    """One decoded plane, cached; decoding 10,000 cells is not free."""
    key = (variable, season, kind)
    if key not in _GRIDS:
        text = getattr(composite, f"{variable}_{season}_{kind}")
        scale = 100.0 if kind == "T" else getattr(composite,
                                                  f"{variable}_SCALE")
        _GRIDS[key] = composite._grid(text, scale)
    return _GRIDS[key]


def _index(values: tuple[float, ...], target: float) -> int:
    """Nearest axis index. The axes are regular but stored, not assumed."""
    best, at = float("inf"), 0
    for i, value in enumerate(values):
        gap = abs(value - target)
        if gap < best:
            best, at = gap, i
    return at


def _nearest_lon(values: tuple[float, ...], target: float) -> int:
    """Nearest centre on a 0..360 axis, measured the short way round: 359.87
    is 0.38 from 0.25, not 358.62."""
    best, at = float("inf"), 0
    for i, value in enumerate(values):
        gap = abs((value - target + 180.0) % 360.0 - 180.0)
        if gap < best:
            best, at = gap, i
    return at


def _bounds(values: tuple[float, ...], index: int) -> tuple[float, float]:
    """The edges of one cell, from the spacing of its own axis."""
    if len(values) < 2:
        return values[index], values[index]
    step = abs(values[1] - values[0])
    return values[index] - step / 2.0, values[index] + step / 2.0


def sample(variable: str, season: str, lon: float, lat: float) -> Cell:
    """Read one composite cell at a point.

    ``lon`` may be in either convention. The grids are published in 0..360 and
    the rest of this system works in -180..180, so the conversion happens here
    rather than in five callers.
    """
    lats = _axis(f"{variable}_LATS")
    lons = _axis(f"{variable}_LONS")
    yi = _index(lats, lat)
    xi = _nearest_lon(lons, lon % 360.0)
    diff = _grid(variable, season, "DIFF")
    base = _grid(variable, season, "BASE")
    tstat = _grid(variable, season, "T")
    lat0, lat1 = _bounds(lats, yi)
    lon0, lon1 = _bounds(lons, xi)
    return Cell(
        value=diff[yi][xi], base=base[yi][xi], t=tstat[yi][xi],
        lon0=geo.wrap180(lon0), lon1=geo.wrap180(lon1),
        lat0=min(lat0, lat1), lat1=max(lat0, lat1),
        crit=critical(variable, season),
    )


def verdict(variable: str, cell: Cell) -> str:
    """A cell in one word, the same on every surface: the atlas, the map."""
    if not cell.known:
        return "no record"
    if not cell.significant:
        return "no clear signal"
    if variable == "PRECIP":
        return "wetter" if cell.value > 0 else "drier"
    return "warmer" if cell.value > 0 else "cooler"


# --- naming ------------------------------------------------------------------

def _lon_name(lon: float) -> str:
    lon = geo.wrap180(lon)
    hemisphere = "E" if lon >= 0 else "W"
    return f"{abs(lon):.2f} {hemisphere}"


def _lat_name(lat: float) -> str:
    hemisphere = "N" if lat >= 0 else "S"
    return f"{abs(lat):.2f} {hemisphere}"


# --- the dossier -------------------------------------------------------------

def dossier(lon: float, lat: float, storms: tuple = (),
            coast: bool = True) -> Local:
    """Everything this system can say about one point.

    ``storms`` is the live cyclone list, which is the only part of this that
    changes between runs. Passing it is optional so the function can be used
    offline and in tests.
    """
    lon = geo.wrap180(lon)
    lat = max(-90.0, min(90.0, lat))

    seasons = tuple(
        Seasonal(season,
                 sample("PRECIP", season, lon, lat),
                 sample("AIR", season, lon, lat))
        for season in SEASONS
    )

    places = tuple(Neighbour(km, place)
                   for km, place in atlasdata.near(lon, lat, limit=5))

    covering = geo.at(lon, lat, scopes=(geo.REGIONAL, geo.BASIN, geo.GLOBAL))
    names = tuple(f.region for f in covering)
    links = tuple(link for link in CATALOGUE if link.region in names)

    coast_km = None
    if coast:
        from .cyclones import distance_to_coast
        coast_km = distance_to_coast(lon, lat)

    nearby = []
    for storm in storms:
        fix = getattr(storm, "latest", None)
        if fix is None:
            continue
        km = _separation(lon, lat, fix.lon, fix.lat)
        if km <= 2500.0:
            nearby.append({
                "name": storm.title if hasattr(storm, "title") else storm.name,
                "km": round(km, 1),
                "wind_kt": fix.wind,
                "basin": storm.basin,
            })
    nearby.sort(key=lambda item: item["km"])

    return Local(
        lon=lon, lat=lat, seasons=seasons, places=places,
        footprints=names, links=links, coast_km=coast_km,
        storms=tuple(nearby),
    )


def _separation(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * 6371.0088 * math.asin(min(1.0, math.sqrt(a)))


# --- the tier ----------------------------------------------------------------

# Points the terminal report and the JSON carry without anyone clicking
# anything. Chosen because each one is a place where this event will be
# decided or felt, not because they are large.
ANCHORS: tuple[tuple[str, float, float], ...] = (
    ("Jakarta", 106.85, -6.21),
    ("Darwin", 130.84, -12.46),
    ("Manila", 120.98, 14.60),
    ("Nairobi", 36.82, -1.29),
    ("Harare", 31.05, -17.83),
    ("Lima", -77.03, -12.05),
    ("Guayaquil", -79.90, -2.19),
    ("Fortaleza", -38.54, -3.72),
    ("Los Angeles", -118.24, 34.05),
    ("Sydney", 151.21, -33.87),
)


def evaluate(storms: tuple = ()) -> AtlasState:
    """Build the tier. Offline: every number here is already in the repo."""
    state = AtlasState()
    try:
        state.samples = {season: dict(composite.PRECIP_META[season])
                         for season in SEASONS}
    except Exception as exc:                          # noqa: BLE001
        state.reasons.append(f"composite grids unavailable: {exc}")
        return state

    state.available = True
    state.anchors = tuple(
        dossier(lon, lat, storms=storms) for _, lon, lat in ANCHORS
    )

    state.reasons = [
        "Composited per season over the El Nino events since 1979 in which "
        "RONI reached +1.0, against the neutral years (RONI inside +/-0.5): "
        + "; ".join(sample_line(season, state.samples[season])
                    for season in SEASONS) + ".",
        "Each event counts once and each neutral year once, because the months "
        "inside one event are not independent. A cell is called wetter or "
        "drier only where Welch's t passes the 95% two-sided point of "
        "Student's t for its season's sample - the |t| quoted with each "
        "season. Everywhere else the record does not separate the event from "
        "an ordinary year, and the page says so rather than colouring it in.",
    ]
    if state.in_progress:
        state.reasons.append(
            "The El Nino under way when the grids were built ("
            + ", ".join(str(year) for year in state.in_progress)
            + ") is not in the sample: the composite is what past events did."
        )
    state.reasons.append(
        "The composite is what has happened in past events, not a forecast "
        "for this one. The forecast tier is the one that forecasts."
    )
    return state


def lessons(state: AtlasState) -> list[str]:
    """The misreadings a composite invites, told with this composite's numbers.

    These were prose once, with the numbers typed in, and the composite moved
    under them: rebuilt on RONI with the event as the unit, Fortaleza is no
    longer "drying by a quarter at ten events" and Los Angeles is not "+111%".
    Each is written only while the example still shows what it is there to
    show.
    """
    named = dict(zip((name for name, _, _ in ANCHORS), state.anchors))
    out: list[str] = []

    jakarta = named.get("Jakarta")
    best = jakarta.strongest if jakarta else None
    if best is not None and best.season == "JJA":
        out.append(
            "The season shown is the one the rainfall record is most sure "
            "about at that place, which is not always the one the event peaks "
            "in: Jakarta's strongest signal is the June-to-August dry season, "
            "not the December monsoon, which is why El Nino fire years there "
            "are counted in the middle of the year."
        )

    fortaleza = named.get("Fortaleza")
    best = fortaleza.strongest if fortaleza else None
    if (best is not None and best.precip.known and not best.precip.significant
            and best.precip.value < 0 and best.precip.percent is not None):
        events = len(state.samples[best.season]["warm_events"])
        out.append(
            "Fortaleza is the one to read twice: the Nordeste drought is a "
            "textbook El Nino teleconnection, and the composite has it at "
            f"{best.precip.percent:+.0f}% of normal in "
            f"{SEASON_LABEL[best.season]} - yet across {events} events its t of "
            f"{best.precip.t:+.2f} does not reach the {best.precip.crit:.2f} "
            "that season's sample needs. The sign is right and the sample is "
            "not big enough to say so. Calling that a drought signal is the "
            "most common way a composite like this gets misused."
        )

    angeles = named.get("Los Angeles")
    best = angeles.strongest if angeles else None
    if (best is not None and best.precip.percent is not None
            and best.precip.percent >= 50.0 and best.precip.base is not None
            and best.precip.base < 1.5):
        out.append(
            "Read the percentages against the millimetres beside them. Los "
            f"Angeles composites at {best.precip.percent:+.0f}% of normal in "
            f"{SEASON_LABEL[best.season]}, which sounds large and is "
            f"{best.precip.value:.1f} mm a day on top of an ordinary "
            f"{best.precip.base:.1f}: the percentage is large because the "
            "season is dry there, not because the anomaly is."
        )
    return out


def temperature_text(cell: Cell) -> str | None:
    """A temperature anomaly as the anchor tables print it.

    Bare where the composite separates it from the neutral years at that
    season's critical t, in parentheses where it does not: the rainfall
    beside it carries a verdict, and a bare number beside a verdict reads as
    one that passed.
    """
    if cell.value is None:
        return None
    text = f"{cell.value:+.2f}"
    return text if cell.significant else f"({text})"


NO_SIGNAL = ("A verdict of 'no clear signal' is a measurement, not a gap: "
             "across that season's El Ninos and neutral years, the record "
             "does not separate the two at that place.")

PARENTHESES = ("A temperature in parentheses does not pass the same test as "
               "the rainfall beside it: the sign is the composite's, the size "
               "is inside the noise.")


def sample_line(season: str, block: dict) -> str:
    """One season's sample, the way every surface states it."""
    crit = block.get("t_crit")
    test = "too few to test" if crit is None else f"|t| {crit:.2f}"
    return (f"{season} {len(block['warm_events'])} events "
            f"({block['warm_months']} months) against "
            f"{block['base_years']} neutral years, {test}")
