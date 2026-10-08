"""Tropical cyclones: where they are, where they are going, and what this
El Nino is doing to whether they exist at all.

The rest of this package watches a seasonal boundary condition. A cyclone is a
four-day object that lives or dies on that boundary condition and then kills
people in an afternoon. Both timescales belong in the same system, because the
question an operational reader actually has is not "is there an El Nino" but
"given this El Nino, what is over my water this week".

Three ATCF decks, which is the format every warning centre publishes:

    b-deck    the best track. Where the storm has been, every six hours, with
              intensity, central pressure and wind radii. Analysis, revised.
    f-deck    the official forecast. Where the warning centre says it goes,
              out to 120 hours, with the same radii.
    a-deck    the guidance. Every model the centre looked at, including the
              global ensembles, one track per member. This is where forecast
              *spread* comes from, and spread is the only honest statement of
              confidence a track forecast can make.

ATCF is fixed-column CSV with two traps. Positions are tenths of a degree with
a hemisphere letter glued on - ``152N`` is 15.2N and ``1015W`` is 101.5W, so a
naive float() gives a storm a thousand degrees from where it is. And every fix
is repeated once per wind-radius threshold (34, 50 and 64 knots), so a file
with 42 lines may hold 14 positions; counting lines counts the storm's
intensity, not its age.

ACE follows the standard definition - 10^-4 times the sum of the squared
one-minute maximum sustained wind over every six-hourly synoptic fix at or
above 34 knots, while the system is warm-core. It is the accepted way to say
"how much cyclone was there" in one number, because storm *counts* reward a
basin full of two-day tropical storms over one that produced a single Category
5 that lasted a week.

The El Nino connection is the reason this module sits in this package rather
than in one of its own. A warm east Pacific shifts the Walker circulation, and
the upper-level westerlies that result run straight across the tropical
Atlantic as vertical wind shear, which tears developing cyclones apart. The
same shift relaxes shear over the east and central Pacific and deepens the warm
layer there. So one event suppresses one basin and enhances the other, and
``impacts.py`` already carries that claim as a forecast. This module is where
the claim gets checked against what the season actually did.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field as dc_field, replace

from .coastline import COASTLINE

# ATCF basin codes that this system follows. The Atlantic and the east and
# central Pacific are NHC/CPHC responsibility and published openly in ATCF;
# the west Pacific is JTWC and arrives on a different schedule.
BASINS = {
    "AL": "Atlantic",
    "EP": "East Pacific",
    "CP": "Central Pacific",
}
# Every basin a storm can be named for. JTWC warns on the west Pacific, the
# north Indian Ocean and the southern hemisphere; they are kept out of
# ``BASINS`` because that is the list of NHC decks to fetch.
BASIN_NAMES = {
    **BASINS,
    "WP": "West Pacific",
    "IO": "North Indian Ocean",
    "SH": "Southern Hemisphere",
}

# The catalogue entry each basin's seasonal activity is a test of. These are
# the exact region strings in impacts.CATALOGUE, so the verdict below can be
# scored with the same gating the rest of the system uses.
BASIN_LINK = {
    "AL": "Atlantic hurricane season",
    "EP": "Eastern and central Pacific hurricanes",
    "CP": "Eastern and central Pacific hurricanes",
}

# Saffir-Simpson in knots. The boundaries are exact: 64 kt is the hurricane
# threshold by definition, not by rounding from 74 mph.
CATEGORY_FLOOR = ((137, 5), (113, 4), (96, 3), (83, 2), (64, 1))

# Development stage codes. Only warm-core systems at tropical-storm force
# contribute to ACE; a decaying extratropical low with 60 kt of wind is not
# a cyclone for this purpose even though it is still dangerous.
WARM_CORE = {"TD", "TS", "HU", "SS", "SD", "TY", "ST", "TC"}
# TY and ST are JTWC's typhoon and super typhoon; TC is its "tropical
# cyclone" in the Indian Ocean and the southern hemisphere - the same
# hurricane-force stage under the name used there.
ACE_STAGES = {"TS", "HU", "SS", "TY", "ST", "TC"}
# What a count may count. A named storm is a tropical or subtropical storm at
# 34 kt; a gale in an extratropical or post-tropical low is not one, and a
# hurricane-force extratropical low is not a hurricane. HURDAT2 carries both,
# and counting them put 22 false hurricanes and 3 false named storms into the
# Atlantic record - enough to move the 1991-2020 normals off NOAA's own.
NAMED_STAGES = ACE_STAGES
HURRICANE_STAGES = {"HU", "TY", "ST", "TC"}
# What ATCF calls a system that is not a tropical or subtropical cyclone: one
# that was (post-tropical, a remnant low, dissipating) or is yet to be (a
# disturbance, a wave, a low). NHC's track graphic draws its points open.
NOT_A_CYCLONE = frozenset({"EX", "LO", "DB", "WV", "DS"})
SYNOPTIC = (0, 6, 12, 18)

# NHC's operational definition: a 30-knot increase in 24 hours, which is
# roughly the 95th percentile of all observed 24-hour intensity changes.
RI_THRESHOLD = 30.0

# The end of the official forecast. Guidance runs far past it; NHC does not,
# and neither does this system.
HORIZON = 120

# The official forecast, and the guidance worth showing beside it. Everything
# else in an a-deck is either a variant of these or a consensus of them.
OFFICIAL = "OFCL"
GUIDANCE = {
    "AVNO": "GFS",
    "AEMN": "GEFS mean",
    "EMXI": "ECMWF",
    "ECMO": "ECMWF",
    "EGRI": "UKMET",
    "HWFI": "HWRF",
    "HMNI": "HMON",
    "HFAI": "HAFS-A",
    "HFBI": "HAFS-B",
    "CTCI": "COAMPS-TC",
    "TVCN": "track consensus",
    "IVCN": "intensity consensus",
    "OFCI": "NHC, interpolated",
}
# The GEFS and ECMWF ensemble members, which is where spread comes from.
ENSEMBLE = re.compile(r"^(AP|AC|EP|EE|EC)\d\d$")

KT_TO_KMH = 1.852
NM_PER_DEG = 60.0
EARTH_KM = 6371.0


# --------------------------------------------------------------------------
# ATCF
# --------------------------------------------------------------------------
def _tenths(text: str) -> float | None:
    """``152N`` -> 15.2, ``1015W`` -> -101.5, blank -> None.

    The hemisphere letter is the sign and the value is tenths of a degree.
    Read as a plain float this is out by a factor of ten and, in the western
    hemisphere, by the sign as well - which puts an east Pacific hurricane in
    the Indian Ocean without raising anything.
    """
    text = text.strip()
    if not text or text in {"0", "-999", "9999"}:
        return None
    hemisphere = text[-1].upper()
    if hemisphere not in "NSEW":
        return None
    try:
        value = int(text[:-1]) / 10.0
    except ValueError:
        return None
    return -value if hemisphere in "SW" else value


def _int(text: str) -> int | None:
    text = text.strip()
    if not text:
        return None
    try:
        value = int(text)
    except ValueError:
        return None
    # ATCF writes 0 for "not analysed" in the pressure and radius columns, and
    # -999/9999 for missing. Zero knots of wind is never a real observation.
    return None if value in (0, -999, 9999, -9999) else value


@dataclass(frozen=True)
class Fix:
    """One position of one storm, from one source, at one lead time."""

    stamp: str            # YYYYMMDDHH, UTC
    tau: int              # forecast hour; 0 for an analysis
    lat: float
    lon: float            # -180..180
    wind: int | None      # kt, 1-minute sustained
    pressure: int | None  # mb
    stage: str            # TD / TS / HU / ...
    tech: str             # BEST, OFCL, AVNO, ...
    rmw: int | None = None    # radius of maximum wind, nautical miles
    eye: int | None = None    # eye diameter, nautical miles
    issued: str = ""          # the cycle a re-based forecast was issued from
    # The extent of 34, 50 and 64 kt winds, nautical miles by quadrant (NE,
    # SE, SW, NW), as ((threshold, (ne, se, sw, nw)), ...). A threshold the
    # deck did not analyse or forecast is absent, not zero.
    radii: tuple = ()
    # Whether the system had been a tropical or subtropical cyclone by this
    # fix, which decides what a low is called: a low before genesis is a low,
    # after it a remnant. The storm sets it (``Storm``); it is not part of
    # what the fix is, so fixes compare equal either way.
    formed: bool = dc_field(default=True, compare=False)

    def radius(self, threshold: int) -> tuple | None:
        """The four quadrant radii for one wind threshold, or None."""
        for knots, quadrants in self.radii:
            if knots == threshold:
                return quadrants
        return None

    @property
    def hour(self) -> int:
        return int(self.stamp[8:10])

    @property
    def synoptic(self) -> bool:
        return self.hour in SYNOPTIC

    @property
    def category(self) -> int:
        return category(self.wind)

    @property
    def label(self) -> str:
        return intensity_label(self.wind, self.stage, self.formed)

    @property
    def short(self) -> str:
        return short_label(self.wind, self.stage, self.formed)

    @property
    def badge(self) -> str:
        return badge(self.wind, self.stage)

    @property
    def hollow(self) -> bool:
        return hollow(self.stage)


def parse_atcf(text: str, techs=None) -> list[Fix]:
    """Every fix in an ATCF deck, de-duplicated across wind-radii rows.

    A deck repeats each position once per radius threshold it carries. The
    rows are identical in everything this module reads, so the first one wins
    and the rest are dropped; keeping them would triple every track and treble
    the ACE.

    ``techs`` filters by model before anything is built. An a-deck for a
    long-lived storm is seven megabytes and sixty thousand rows covering 92
    models and every cycle since genesis, and all but a few hundred of those
    rows are of no interest to a reader; filtering at the line rather than
    after the fact is the difference between a fast run and a slow one.
    """
    first: dict[tuple[str, int, str], Fix] = {}
    radii: dict[tuple[str, int, str], dict[int, tuple]] = {}
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 11:
            continue
        stamp, tech = parts[2], parts[4]
        if techs is not None and tech not in techs:
            continue
        if not stamp.isdigit() or len(stamp) != 10:
            continue
        try:
            tau = int(parts[5])
        except ValueError:
            continue
        key = (stamp, tau, tech)
        if key not in first:
            lat, lon = _tenths(parts[6]), _tenths(parts[7])
            if lat is None or lon is None:
                continue
            first[key] = Fix(
                stamp=stamp, tau=tau, lat=lat, lon=lon,
                wind=_int(parts[8]), pressure=_int(parts[9]),
                stage=parts[10].upper(), tech=tech,
                rmw=_radius(parts, 19), eye=_radius(parts, 21),
            )
        found = _quadrants(parts)
        if found is not None:
            radii.setdefault(key, {}).setdefault(found[0], found[1])
    out = [replace(fix, radii=tuple(sorted(radii[key].items())))
           if key in radii else fix for key, fix in first.items()]
    out.sort(key=lambda f: (f.stamp, f.tau))
    return out


def _quadrants(parts: list[str]) -> tuple[int, tuple] | None:
    """One row's wind radii: its threshold and (NE, SE, SW, NW) in nm.

    ``NEQ`` gives the four quadrants clockwise from north-east; ``AAA`` is
    one radius all the way round. ATCF writes 0 for "not analysed", so a row
    of four zeros is no information; one zero among real radii is a quadrant
    that genuinely has none, which is how a lopsided storm is described.
    """
    if len(parts) < 17:
        return None
    try:
        threshold = int(parts[11])
    except ValueError:
        return None
    if threshold not in (34, 50, 64):
        return None
    values = []
    for text in parts[13:17]:
        try:
            values.append(max(0, int(text)))
        except ValueError:
            values.append(0)
    code = parts[12].upper()
    if code == "AAA":
        values = [values[0]] * 4
    elif code != "NEQ":
        return None
    if not any(values):
        return None
    return threshold, tuple(values)


def _radius(parts: list[str], index: int) -> int | None:
    """One of the structural radii, in nautical miles, or None.

    ATCF writes an unreported radius as ``0`` rather than leaving the column
    blank, and a zero-radius eyewall is not a thing, so zero means absent. The
    column is also simply missing from short rows in older decks.
    """
    if index >= len(parts):
        return None
    value = _int(parts[index])
    return value if value else None


def wanted_techs() -> set:
    """The models worth carrying out of an a-deck.

    The official forecast, a short list of named deterministic and consensus
    guidance, and the GEFS/ECMWF ensemble members. The rest of the 92 are
    variants, interpolations and decayed versions of these, and showing them
    would make the spread look larger than the independent information in it.
    """
    return {OFFICIAL} | set(GUIDANCE)


def latest_guidance(fixes, within_hours: int = 12) -> dict:
    """One track per model, from the most recent cycle each model ran.

    Guidance arrives staggered - a global model an hour after synoptic time, a
    hurricane model two hours later - so the newest stamp in the file is not
    the newest stamp for every model. Each model contributes its own latest
    run, and a run more than ``within_hours`` behind the newest is dropped
    rather than drawn: a track from two cycles ago looks exactly like a
    disagreeing model on a map, and it is not one.
    """
    by_tech: dict[str, dict[str, list[Fix]]] = {}
    for fix in fixes:
        by_tech.setdefault(fix.tech, {}).setdefault(fix.stamp, []).append(fix)
    if not by_tech:
        return {}
    newest = max(max(cycles) for cycles in by_tech.values())
    out: dict[str, tuple[Fix, ...]] = {}
    for tech, cycles in by_tech.items():
        stamp = max(cycles)
        if _hours_between(stamp, newest) > within_hours:
            continue
        track = sorted(cycles[stamp], key=lambda f: f.tau)
        if len(track) > 1:
            out[tech] = tuple(track)
    return out


def ensemble_techs(text: str) -> set:
    """Ensemble member names actually present in this deck.

    The member count differs by centre and changes between model upgrades, so
    it is read off the file rather than assumed.
    """
    found = set()
    for line in text.splitlines():
        parts = line.split(",")
        if len(parts) > 5:
            tech = parts[4].strip()
            if ENSEMBLE.match(tech):
                found.add(tech)
    return found


def storm_name(text: str) -> str:
    """The name an ATCF deck carries, which appears only once it is assigned.

    A system is numbered before it is named, so the early rows of a b-deck say
    nothing and the later ones say INVEST, then the name. The last non-trivial
    value is the current one.
    """
    found = ""
    for line in text.splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) > 27 and parts[27] and parts[27] not in {"INVEST", "NONAME"}:
            found = parts[27].title()
    return found


# --------------------------------------------------------------------------
# derived quantities
# --------------------------------------------------------------------------
def category(wind: int | None) -> int:
    """Saffir-Simpson category, 0 for anything below hurricane force."""
    if wind is None:
        return 0
    for floor, number in CATEGORY_FLOOR:
        if wind >= floor:
            return number
    return 0


def intensity_label(wind: int | None, stage: str = "", formed: bool = True) -> str:
    """What a forecaster would call it, in words.

    ``formed`` says whether the system had been a tropical or subtropical
    cyclone yet: before that, ATCF's LO is a low and its EX a non-tropical
    low, as NHC's outlooks word them; after, a remnant low and post-tropical.
    """
    if wind is None:
        return "unknown"
    if not formed and stage in {"EX", "LO"}:
        return {"EX": "non-tropical low", "LO": "low"}[stage]
    if stage in NOT_A_CYCLONE:
        return {"EX": "post-tropical", "LO": "remnant low", "DB": "disturbance",
                "WV": "tropical wave", "DS": "dissipating"}[stage]
    if stage in {"SD", "SS"}:
        return "subtropical storm" if wind >= 34 else "subtropical depression"
    number = category(wind)
    if number:
        # JTWC's winds are one-minute means like NHC's, so the category is a
        # like-for-like comparison; the name is the one used in that ocean.
        kind = {"TY": "typhoon", "ST": "super typhoon", "TC": "cyclone"}.get(stage)
        if kind:
            return f"Category {number}-equivalent {kind}"
        return f"Category {number} hurricane"
    return "tropical storm" if wind >= 34 else "tropical depression"


def short_label(wind: int | None, stage: str = "", formed: bool = True) -> str:
    """The same call as ``intensity_label`` in a dozen characters.

    Tables have a width and prose does not, so both spellings exist rather
    than one truncated at render time - a cut-off "Category 4 hurrica" reads
    as a rendering fault and invites the reader to distrust the number beside
    it.
    """
    if wind is None:
        return "unknown"
    if not formed and stage in {"EX", "LO"}:
        return {"EX": "non-trop low", "LO": "low"}[stage]
    if stage in NOT_A_CYCLONE:
        return {"EX": "post-trop", "LO": "rem low", "DB": "disturbance",
                "WV": "wave", "DS": "dissipating"}[stage]
    # Saffir-Simpson is a hurricane's scale: a subtropical storm at hurricane
    # force is still a subtropical storm, as NHC calls it.
    if stage in {"SD", "SS"}:
        return "subtrop storm" if wind >= 34 else "subtrop dep"
    number = category(wind)
    if number:
        return f"Cat {number}"
    return "trop storm" if wind >= 34 else "trop dep"


def badge(wind: int | None, stage: str = "") -> str:
    """The mark a forecast map writes on a point, in one character, as NHC's
    track graphic marks one: the letter of its wind, D under 34 kt, S to 63,
    H to 95 and M above, and for a hurricane, or its equivalent in another
    ocean, the number of its category where NHC writes H or M. A system that
    is no hurricane, subtropical or not a cyclone there at all (``hollow``),
    keeps NHC's letter: Saffir-Simpson is a hurricane's scale. Nothing
    without a wind.
    """
    if wind is None:
        return ""
    if stage not in NOT_A_CYCLONE and stage not in {"SD", "SS"}:
        number = category(wind)
        if number:
            return str(number)
    return "M" if wind >= 96 else "H" if wind >= 64 else "S" if wind >= 34 else "D"


def hollow(stage: str) -> bool:
    """Whether a forecast map draws a point open, as NHC's track graphic draws
    a post-tropical or potential cyclone's: where the system is not a
    tropical or subtropical cyclone."""
    return stage in NOT_A_CYCLONE


def ace(fixes) -> float:
    """Accumulated cyclone energy, in the conventional 10^4 kt^2 units.

    Only six-hourly synoptic analyses count, only at or above 34 knots, and
    only while the system is warm-core. Intermediate fixes issued for a
    landfall would otherwise be counted as if they were another six hours of
    storm.
    """
    total = 0.0
    for fix in fixes:
        if fix.tau != 0 or not fix.synoptic:
            continue
        if fix.stage not in ACE_STAGES or fix.wind is None or fix.wind < 34:
            continue
        total += fix.wind ** 2
    return total * 1e-4


def intensification(fixes, window: int = 24) -> tuple[float, str]:
    """Largest wind change over any ``window`` hours of the storm's life.

    The storm's history, not its present: a burst two days ago is still the
    largest. Positive is intensification. Returns ``(0.0, "")`` if the track
    is too short to span the window, rather than reporting a change it cannot
    see.
    """
    track = [f for f in fixes if f.tau == 0 and f.wind is not None]
    best, when = 0.0, ""
    for i, later in enumerate(track):
        for earlier in track[:i]:
            gap = _hours_between(earlier.stamp, later.stamp)
            if gap != window:
                continue
            change = float(later.wind - earlier.wind)
            if abs(change) > abs(best):
                best, when = change, later.stamp
    return best, when


def recent_change(fixes, window: int = 24) -> tuple[float, str]:
    """Wind change over the ``window`` hours ending at the latest analysis.

    What "in the last 24 hours" means, and what an intensification alert has
    to be about: this used to quote the largest change of the storm's whole
    life, so a hurricane that had jumped 85 kt two days earlier and was now
    weakening read as intensifying rapidly. Returns ``(0.0, "")`` when there is
    no analysis exactly ``window`` hours before the latest one.
    """
    track = [f for f in fixes if f.tau == 0 and f.wind is not None]
    if not track:
        return 0.0, ""
    latest = track[-1]
    for earlier in reversed(track[:-1]):
        gap = _hours_between(earlier.stamp, latest.stamp)
        if gap == window:
            return float(latest.wind - earlier.wind), latest.stamp
        if gap > window:
            break
    return 0.0, ""


def _hours_between(first: str, second: str) -> int:
    """Whole hours between two ATCF stamps, without importing a calendar."""
    from datetime import datetime
    fmt = "%Y%m%d%H"
    delta = datetime.strptime(second, fmt) - datetime.strptime(first, fmt)
    return round(delta.total_seconds() / 3600.0)


def _stamp_plus(stamp: str, hours: int) -> str:
    from datetime import datetime, timedelta
    fmt = "%Y%m%d%H"
    return (datetime.strptime(stamp, fmt) + timedelta(hours=hours)).strftime(fmt)


def lead(fix: Fix) -> str:
    """How far ahead a fix is, as the panels print it: "+18 h", or "now".

    A closest approach at the analysis itself is a storm already moving away,
    and "+0 h" reads as one about to arrive.
    """
    return "now" if fix.tau == 0 else f"+{fix.tau} h"


def valid_stamp(fix: Fix) -> str:
    """When a fix is valid: its cycle plus its lead."""
    return _stamp_plus(fix.stamp, fix.tau) if fix.tau else fix.stamp


def rebase(fixes, reference: str) -> tuple[Fix, ...]:
    """Forecast fixes re-expressed as hours after ``reference``, the latest analysis.

    The official forecast, the guidance and the ensemble come from cycles that
    can be hours older than the newest best-track fix - on 24 September 2026
    Polo's forecast was the 06Z advisory while the best track ran to 12Z - and
    a lead counted from its own cycle is not a time from now: "+3 h" was 09Z,
    already three hours behind the latest analysis. Each fix keeps its valid
    time and becomes ``stamp=reference, tau=hours after it``; its own cycle is
    kept in ``issued``. A fix valid at or before the reference is dropped,
    because the analysis supersedes it. Members from different cycles are then
    compared at the same valid time rather than the same nominal lead.
    """
    out = []
    for fix in fixes:
        lead = fix.tau - _hours_between(fix.stamp, reference)
        if lead <= 0:
            continue
        out.append(replace(fix, stamp=reference, tau=lead,
                           issued=fix.issued or fix.stamp))
    return tuple(out)


def mean_position(fixes) -> tuple[float, float]:
    """The mean of positions on the sphere, as (lon, lat) in degrees.

    Averaged as unit vectors rather than as numbers, so members either side
    of 180 average to 180 and not to the Greenwich meridian.
    """
    x = y = z = 0.0
    for fix in fixes:
        lat, lon = math.radians(fix.lat), math.radians(fix.lon)
        x += math.cos(lat) * math.cos(lon)
        y += math.cos(lat) * math.sin(lon)
        z += math.sin(lat)
    return (math.degrees(math.atan2(y, x)),
            math.degrees(math.atan2(z, math.hypot(x, y))))


def _wrap(degrees: float) -> float:
    """A longitude difference folded into -180..180."""
    return (degrees + 180.0) % 360.0 - 180.0


def _closest_points(line: list, place) -> list:
    """The point of each leg of a track that comes closest to ``place``.

    Found in a flat projection centred on the place, which over one forecast
    interval is good to a kilometre or two in the tropics; the distance itself
    is then taken on the sphere by the caller. A single fix is its own leg.
    """
    if len(line) == 1:
        return list(line)
    scale = math.cos(math.radians(place.lat))
    out = []
    for a, b in zip(line, line[1:]):
        ax, ay = _wrap(a.lon - place.lon) * scale, a.lat - place.lat
        bx, by = _wrap(b.lon - place.lon) * scale, b.lat - place.lat
        dx, dy = bx - ax, by - ay
        length = dx * dx + dy * dy
        fraction = (0.0 if length == 0.0
                    else min(1.0, max(0.0, -(ax * dx + ay * dy) / length)))
        out.append(_between(a, b, fraction))
    return out


def _between(a: Fix, b: Fix, fraction: float) -> Fix:
    """The track ``fraction`` of the way from ``a`` to ``b``.

    Position and time are interpolated, the time to the whole hour; the wind
    to the nearest 5 kt, the precision the official forecast is issued to.
    Anything that cannot be interpolated comes from the nearer end.
    """
    from dataclasses import replace

    if fraction <= 0.0:
        return a
    if fraction >= 1.0:
        return b
    near = a if fraction < 0.5 else b

    def blend(x, y):
        if x is None or y is None:
            return None
        return x + fraction * (y - x)

    wind = blend(a.wind, b.wind)
    pressure = blend(a.pressure, b.pressure)
    return replace(
        near,
        tau=round(a.tau + fraction * (b.tau - a.tau)),
        lat=a.lat + fraction * (b.lat - a.lat),
        lon=_wrap(a.lon + fraction * _wrap(b.lon - a.lon)),
        wind=near.wind if wind is None else 5 * round(wind / 5.0),
        pressure=near.pressure if pressure is None else round(pressure),
    )


def great_circle(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    """Kilometres between two points, on a sphere."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = (math.sin(dp / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)
    return 2 * EARTH_KM * math.asin(min(1.0, math.sqrt(a)))


@dataclass(frozen=True)
class Place:
    name: str
    lon: float
    lat: float
    country: str


# Coastal targets in the two basins this system follows. A distance to the
# nearest coastline vertex is a number; a distance to a named place is a
# warning, and only the second one is any use to a reader deciding whether
# this storm is their problem. The list is landfall-prone coast rather than
# population: Cabo Corrientes and Cape Hatteras are here because storms hit
# them, not because anyone lives there.
LANDFALL: tuple[Place, ...] = (
    # -- US Gulf and east coast
    Place("Brownsville", -97.4, 25.9, "United States"),
    Place("Corpus Christi", -97.4, 27.8, "United States"),
    Place("Galveston", -94.8, 29.3, "United States"),
    Place("Cameron", -93.3, 29.8, "United States"),
    Place("New Orleans", -90.1, 29.9, "United States"),
    Place("Mobile", -88.0, 30.7, "United States"),
    Place("Pensacola", -87.2, 30.4, "United States"),
    Place("Panama City", -85.7, 30.2, "United States"),
    Place("Apalachicola", -85.0, 29.7, "United States"),
    Place("Tampa Bay", -82.6, 27.8, "United States"),
    Place("Fort Myers", -82.0, 26.5, "United States"),
    Place("Key West", -81.8, 24.6, "United States"),
    Place("Miami", -80.2, 25.8, "United States"),
    Place("West Palm Beach", -80.1, 26.7, "United States"),
    Place("Cape Canaveral", -80.6, 28.4, "United States"),
    Place("Jacksonville", -81.4, 30.3, "United States"),
    Place("Savannah", -81.1, 32.0, "United States"),
    Place("Charleston", -79.9, 32.8, "United States"),
    Place("Wilmington", -77.9, 34.2, "United States"),
    Place("Cape Hatteras", -75.5, 35.3, "United States"),
    Place("Norfolk", -76.3, 36.9, "United States"),
    Place("Atlantic City", -74.4, 39.4, "United States"),
    Place("New York City", -74.0, 40.6, "United States"),
    Place("Montauk", -71.9, 41.1, "United States"),
    Place("Cape Cod", -70.1, 41.7, "United States"),
    Place("Portland, Maine", -70.2, 43.7, "United States"),
    # -- Atlantic Canada and the open Atlantic
    Place("Halifax", -63.6, 44.6, "Canada"),
    Place("Cape Breton", -60.2, 46.2, "Canada"),
    Place("Newfoundland", -53.0, 47.5, "Canada"),
    Place("Bermuda", -64.8, 32.3, "Bermuda"),
    Place("Azores", -25.7, 37.8, "Portugal"),
    Place("Cabo Verde", -23.6, 15.0, "Cabo Verde"),
    # -- Caribbean
    Place("Nassau", -77.3, 25.1, "Bahamas"),
    Place("Abaco", -77.2, 26.4, "Bahamas"),
    Place("Grand Bahama", -78.6, 26.6, "Bahamas"),
    Place("Havana", -82.4, 23.1, "Cuba"),
    Place("Camaguey coast", -77.3, 21.4, "Cuba"),
    Place("Guantanamo", -75.2, 20.0, "Cuba"),
    Place("Grand Cayman", -81.4, 19.3, "Cayman Islands"),
    Place("Montego Bay", -77.9, 18.5, "Jamaica"),
    Place("Kingston", -76.8, 18.0, "Jamaica"),
    Place("Port-au-Prince", -72.3, 18.5, "Haiti"),
    Place("Cap-Haitien", -72.2, 19.8, "Haiti"),
    Place("Santo Domingo", -69.9, 18.5, "Dominican Republic"),
    Place("Puerto Plata", -70.7, 19.8, "Dominican Republic"),
    Place("San Juan", -66.1, 18.5, "Puerto Rico"),
    Place("St Croix", -64.8, 17.7, "US Virgin Islands"),
    Place("St Maarten", -63.1, 18.0, "Sint Maarten"),
    Place("Antigua", -61.8, 17.1, "Antigua and Barbuda"),
    Place("Guadeloupe", -61.6, 16.2, "France"),
    Place("Dominica", -61.4, 15.4, "Dominica"),
    Place("Martinique", -61.0, 14.6, "France"),
    Place("St Lucia", -61.0, 13.9, "Saint Lucia"),
    Place("Barbados", -59.6, 13.1, "Barbados"),
    Place("Grenada", -61.7, 12.1, "Grenada"),
    Place("Trinidad", -61.4, 10.6, "Trinidad and Tobago"),
    Place("Aruba", -70.0, 12.5, "Aruba"),
    Place("Cartagena", -75.5, 10.4, "Colombia"),
    # -- Central America and the Gulf of Mexico
    Place("Cancun", -86.8, 21.2, "Mexico"),
    Place("Cozumel", -86.9, 20.4, "Mexico"),
    Place("Belize City", -88.2, 17.5, "Belize"),
    Place("La Ceiba", -86.8, 15.8, "Honduras"),
    Place("Bluefields", -83.8, 12.0, "Nicaragua"),
    Place("Limon", -83.0, 10.0, "Costa Rica"),
    Place("Veracruz", -96.1, 19.2, "Mexico"),
    Place("Tampico", -97.9, 22.2, "Mexico"),
    Place("Campeche", -90.5, 19.8, "Mexico"),
    # -- Mexican Pacific coast, which is where an El Nino east Pacific goes
    Place("Puerto Madero", -92.4, 14.7, "Mexico"),  # Tapachula's port
    Place("Salina Cruz", -95.2, 16.2, "Mexico"),
    Place("Puerto Escondido", -97.1, 15.8, "Mexico"),
    Place("Acapulco", -99.9, 16.8, "Mexico"),
    Place("Zihuatanejo", -101.6, 17.6, "Mexico"),
    Place("Lazaro Cardenas", -102.2, 17.9, "Mexico"),
    Place("Manzanillo", -104.3, 19.1, "Mexico"),
    Place("Puerto Vallarta", -105.2, 20.6, "Mexico"),
    Place("Cabo Corrientes", -105.7, 20.4, "Mexico"),
    Place("Mazatlan", -106.4, 23.2, "Mexico"),
    Place("Los Cabos", -109.9, 22.9, "Mexico"),
    Place("La Paz", -110.3, 24.1, "Mexico"),
    Place("Guaymas", -110.9, 27.9, "Mexico"),
    Place("Bahia Magdalena", -112.1, 24.6, "Mexico"),
    Place("Punta Eugenia", -115.1, 27.8, "Mexico"),
    Place("Ensenada", -116.6, 31.9, "Mexico"),
    Place("San Diego", -117.2, 32.7, "United States"),
    # -- Central American Pacific
    Place("San Jose, Guatemala", -90.8, 13.9, "Guatemala"),
    Place("La Union", -87.8, 13.3, "El Salvador"),
    Place("Corinto", -87.2, 12.5, "Nicaragua"),
    Place("Puntarenas", -84.8, 10.0, "Costa Rica"),
    # -- Hawaii and the central Pacific, the basin an El Nino pushes storms into
    Place("Hilo", -155.1, 19.7, "Hawaii"),
    Place("Kona", -156.0, 19.6, "Hawaii"),
    Place("Maui", -156.3, 20.8, "Hawaii"),
    Place("Honolulu", -157.9, 21.3, "Hawaii"),
    Place("Kauai", -159.5, 22.1, "Hawaii"),
    Place("Johnston Atoll", -169.5, 16.7, "United States"),
    Place("Palmyra Atoll", -162.1, 5.9, "United States"),
    Place("Kiritimati", -157.4, 1.9, "Kiribati"),
    Place("Clipperton", -109.2, 10.3, "France"),
    Place("Socorro Island", -110.9, 18.8, "Mexico"),
)

# Beyond this a storm is over open ocean and naming the nearest land is
# misleading rather than informative.
NEAR_KM = 1500.0


def nearest_place(lon: float, lat: float) -> tuple[float, Place] | None:
    """The closest named coastal target, and how far away it is."""
    scored = [(great_circle(lon, lat, p.lon, p.lat), p) for p in LANDFALL]
    best = min(scored, key=lambda pair: pair[0])
    return best if best[0] <= NEAR_KM else None


def distance_to_coast(lon: float, lat: float) -> float:
    """Kilometres from a point to the nearest vendored coastline vertex.

    The coastline is simplified to 0.08 degrees, so this is accurate to about
    ten kilometres and is used for ordering and for a plain-language "how far
    offshore", never for a landfall time. A forecast cone is the thing that
    answers landfall, and it is drawn from the official track.
    """
    best = float("inf")
    # Cheap rejection before the trigonometry. The coastline is 24,147
    # vertices and this runs for every fix of every storm, so a great circle
    # is only worth computing for a vertex that could plausibly win.
    #
    # The longitude test has to be conservative or it will reject the answer.
    # A degree of longitude is shortest at the highest latitude in play, so
    # the cosine used is the one for the far edge of the latitude band - any
    # vertex that survives the first test sits at a latitude whose degrees of
    # longitude are at least this long, and the bound therefore never throws
    # away a vertex that could be nearer than BOX degrees of arc.
    BOX = 25.0
    scale = math.cos(math.radians(min(abs(lat) + BOX, 89.0)))
    reach = BOX / scale if scale > 1e-6 else 360.0
    for line in COASTLINE:
        for clon, clat in line:
            if abs(clat - lat) > BOX:
                continue
            gap_lon = abs(clon - lon)
            if gap_lon > 180.0:      # the antimeridian is not a wall
                gap_lon = 360.0 - gap_lon
            if gap_lon > reach:
                continue
            gap = great_circle(lon, lat, clon, clat)
            if gap < best:
                best = gap
    return best


def bearing_name(degrees: float | None) -> str:
    if degrees is None:
        return "stationary"
    points = ("N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
              "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW")
    return points[int((degrees % 360.0) / 22.5 + 0.5) % 16]


def _genesis(track, forecast) -> tuple[tuple, tuple]:
    """A storm's track and forecast with each fix's ``formed`` set: from its
    first tropical or subtropical stage in the track, or, in a forecast,
    from the track's or from an earlier hour of the same forecast."""
    warm = sorted(f.stamp for f in track if f.stage in WARM_CORE)
    first = warm[0] if warm else None

    def told(fix, formed: bool):
        return fix if fix.formed == formed else replace(fix, formed=formed)

    track = tuple(told(f, first is not None and f.stamp >= first) for f in track)
    forecast = tuple(
        told(f, (first is not None and first <= f.stamp)
             or any(g.stage in WARM_CORE and g.stamp == f.stamp and g.tau < f.tau
                    for g in forecast))
        for f in forecast)
    return track, forecast


# --------------------------------------------------------------------------
# a storm
# --------------------------------------------------------------------------
@dataclass
class Storm:
    """One cyclone: its history, the official forecast, and the guidance."""

    basin: str
    number: int
    year: int
    name: str = ""
    track: tuple[Fix, ...] = ()
    forecast: tuple[Fix, ...] = ()
    guidance: dict = dc_field(default_factory=dict)
    ensemble: dict = dc_field(default_factory=dict)
    advisory: dict = dc_field(default_factory=dict)
    notes: list = dc_field(default_factory=list)
    centre: str = "NHC"     # the warning centre whose forecast this is
    # What the centre issued to protect people (``tcproducts.Products``);
    # None where nothing was fetched - a finished storm, or JTWC's.
    products: object = None
    invest: bool = False    # a disturbance being run through the models, 90-99

    def __setattr__(self, name: str, value) -> None:
        super().__setattr__(name, value)
        # Every track and forecast the storm is given, made with it or filled
        # in later, has each fix told whether the system had formed by then.
        if name in ("track", "forecast") and {"track", "forecast"} <= self.__dict__.keys():
            track, forecast = _genesis(self.track, self.forecast)
            super().__setattr__("track", track)
            super().__setattr__("forecast", forecast)

    @property
    def key(self) -> str:
        return f"{self.basin.lower()}{self.number:02d}{self.year}"

    @property
    def designation(self) -> str:
        return f"{self.basin}{self.number:02d}"

    @property
    def title(self) -> str:
        return self.name or f"{self.basin_name} {self.number:02d}"

    @property
    def basin_name(self) -> str:
        return BASIN_NAMES.get(self.basin, self.basin)

    @property
    def latest(self) -> Fix | None:
        analyses = [f for f in self.track if f.tau == 0]
        return analyses[-1] if analyses else None

    @property
    def active(self) -> bool:
        """Live if the warning centre still has an advisory open on it.

        Not inferred from the last b-deck fix. A deck that ends on ``HU``
        because the storm moved out of the area of responsibility looks
        identical to one that ends on ``HU`` because the storm is still there,
        and the advisory index is the thing that knows the difference.
        """
        return bool(self.advisory)

    @property
    def ace(self) -> float:
        return ace(self.track)

    @property
    def peak(self) -> Fix | None:
        """The strongest analysis while the storm was a tropical cyclone."""
        scored = [f for f in self.track
                  if f.tau == 0 and f.wind is not None and f.stage in WARM_CORE]
        return max(scored, key=lambda f: f.wind) if scored else None

    @property
    def peak_category(self) -> int:
        peak = self.peak
        return peak.category if peak else 0

    @property
    def rapid(self) -> tuple[float, str]:
        """Wind change over the 24 hours to the latest analysis, and its stamp."""
        return recent_change(self.track)

    @property
    def peak_intensification(self) -> tuple[float, str]:
        """The fastest 24-hour change of the storm's life, and when it ended."""
        return intensification(self.track)

    @property
    def intensifying_rapidly(self) -> bool:
        change, _ = self.rapid
        return change >= RI_THRESHOLD

    @property
    def forecast_peak(self) -> Fix | None:
        scored = [f for f in self.forecast if f.wind is not None]
        return max(scored, key=lambda f: f.wind) if scored else None

    @property
    def scatter(self) -> dict:
        """Whichever set of tracks is the better statement of uncertainty.

        The ensemble if the deck carried one, because thirty members perturbed
        from the same analysis measure how much the atmosphere itself has not
        decided. Otherwise the deterministic guidance, which measures
        something related but weaker - how much the modelling centres disagree.
        """
        return self.ensemble or self.guidance

    def spread_near(self, tau: int) -> tuple[int, float] | None:
        """The spread at ``tau``, or at the nearest lead the members share.

        The first shared lead at or after ``tau``, else the last one before
        it, so a threat six hours out is quoted the spread six hours out and
        not the spread at day five.
        """
        taus = sorted({f.tau for track in self.scatter.values() for f in track
                       if 0 < f.tau <= HORIZON})
        known = [(t, self.spread_at(t)) for t in taus]
        known = [(t, km) for t, km in known if km is not None]
        if not known:
            return None
        after = [pair for pair in known if pair[0] >= tau]
        return after[0] if after else known[-1]

    def spread_at(self, tau: int) -> float | None:
        """Mean kilometres of the members from their mean position at one lead.

        The conventional measure of ensemble track spread, and the one the
        spread-skill literature sets against the ensemble-mean track error.
        This used to be the distance between the two furthest-apart members:
        an extreme-value statistic that one member tracking the wrong vortex
        sets on its own, and that grows with the member count, so 31 GEFS
        members and 81 GEFS and ECMWF members gave different widths for the
        same uncertainty. On 24 September 2026 it put Polo's GEFS at 342 km
        six hours out, where the members averaged 71 km from their mean.
        """
        fixes = [f for track in self.scatter.values() for f in track
                 if f.tau == tau]
        if len(fixes) < 4:
            return None
        lon, lat = mean_position(fixes)
        return sum(great_circle(f.lon, f.lat, lon, lat)
                   for f in fixes) / len(fixes)

    @property
    def spread_km(self) -> float | None:  # noqa: D401 - see docstring below
        """How far apart the tracks are at the furthest lead time they share.

        The single most useful number a track forecast has, and the one a cone
        graphic hides: members 80 km from their mean at day five is a
        confident forecast, and 900 km is not, while the cone drawn from the
        official track looks identical in both cases because it is drawn from
        five years of average error rather than from today's.
        """
        return self.spread_at(self.spread_tau) if self.spread_tau else None

    @property
    def spread_tau(self) -> int | None:
        """The lead time spread is quoted at: the longest one NHC forecasts to.

        The ensembles run to eight days and some members are still drawing a
        track at 384 hours. Quoting spread there would be quoting the spread
        of a forecast nobody issues; 120 hours is the end of the official
        forecast and therefore the end of the comparison.
        """
        taus = {f.tau for track in self.scatter.values() for f in track
                if 0 < f.tau <= HORIZON}
        for tau in sorted(taus, reverse=True):
            if self.spread_at(tau) is not None:
                return tau
        return None

    @property
    def translation(self) -> tuple[float, float] | None:
        """Speed in knots and bearing in degrees, from the last two analyses.

        Recomputed here rather than read from the deck's own DIR/SPEED columns
        because those are blank on roughly a third of the fixes in a live
        file, and a stalling storm - which is the dangerous case, because it
        rains on one place for two days - is exactly where they go blank.
        """
        track = [f for f in self.track if f.tau == 0]
        if len(track) < 2:
            return None
        before, now = track[-2], track[-1]
        hours = _hours_between(before.stamp, now.stamp)
        if hours <= 0:
            return None
        km = great_circle(before.lon, before.lat, now.lon, now.lat)
        knots = (km / KT_TO_KMH) / hours
        east = math.radians(now.lon - before.lon)
        lat1, lat2 = math.radians(before.lat), math.radians(now.lat)
        y = math.sin(east) * math.cos(lat2)
        x = (math.cos(lat1) * math.sin(lat2)
             - math.sin(lat1) * math.cos(lat2) * math.cos(east))
        return knots, math.degrees(math.atan2(y, x)) % 360.0

    @property
    def offshore_km(self) -> float | None:
        current = self.latest
        return distance_to_coast(current.lon, current.lat) if current else None

    @property
    def closest_approach(self) -> tuple[float, Fix] | None:
        """The forecast fix that comes nearest a coast, and how near."""
        if not self.forecast:
            return None
        scored = [(distance_to_coast(f.lon, f.lat), f)
                  for f in self.forecast if f.tau <= HORIZON]
        return min(scored, key=lambda pair: pair[0]) if scored else None

    def threats(self, within: float = 400.0) -> list:
        """Named places the official forecast brings this storm near, and when.

        One entry per place, at its closest approach, sorted by distance. The
        forecast track is a line rather than a cone, so this is a centre-line
        distance and understates the risk to anywhere it passes beside - which
        is why the radius is generous and why the panel that prints this also
        prints the spread.

        The approach is measured along the line from the latest analysis
        through the forecast points, not at the points alone. They are 12 to
        24 hours and up to 600 km apart, and a coast the line crosses between
        two of them was reported as far away as the nearer point: on 24
        September 2026, Polo's pass of Bahia Magdalena as 123 km where the
        line comes within 83. Where the analysis itself is the closest point,
        the storm is moving away, and the entry is the analysis at +0 h.
        """
        ahead: dict[int, Fix] = {}
        for fix in self.forecast:
            if 0 < fix.tau <= HORIZON:
                ahead.setdefault(fix.tau, fix)
        if not ahead:
            return []
        line = [ahead[tau] for tau in sorted(ahead)]
        now = self.latest
        # Only an analysis the forecast is counted from starts the line; a
        # forecast from another cycle would put the two on different clocks.
        if now is not None and now.stamp == line[0].stamp:
            line.insert(0, now)
        best: dict[str, tuple[float, Fix, Place]] = {}
        for place in LANDFALL:
            for fix in _closest_points(line, place):
                gap = great_circle(fix.lon, fix.lat, place.lon, place.lat)
                if gap > within:
                    continue
                if place.name not in best or gap < best[place.name][0]:
                    best[place.name] = (gap, fix, place)
        return sorted(best.values(), key=lambda item: item[0])

    @property
    def nearest_land(self) -> tuple[float, Place] | None:
        current = self.latest
        return nearest_place(current.lon, current.lat) if current else None


def _tropical_peak(fixes, stages) -> int:
    """Highest analysed wind while the storm was in one of ``stages``."""
    return max((f.wind for f in fixes
                if f.tau == 0 and f.wind is not None and f.stage in stages), default=0)


# --------------------------------------------------------------------------
# a season, and what El Nino said about it
# --------------------------------------------------------------------------
SEASON_BASINS = {"AL": "Atlantic", "EP": "East and central Pacific"}


def season_of(basin: str) -> str:
    """Which seasonal ledger a storm's activity belongs to.

    The central Pacific is a separate warning centre with its own ATCF basin
    code, and it is not a separate basin: storms cross 140W in both directions
    and get renumbered when they do. HURDAT2 keeps them in one file and the
    teleconnection catalogue makes one claim about both, so they are summed.
    """
    return "AL" if basin.upper() == "AL" else "EP"


@dataclass
class BasinSeason:
    """One basin's season to date, against its own climatology."""

    basin: str
    storms: tuple[Storm, ...] = ()
    normal: dict = dc_field(default_factory=dict)
    elnino: dict = dc_field(default_factory=dict)
    through: str = ""

    @property
    def name(self) -> str:
        return SEASON_BASINS.get(self.basin, BASINS.get(self.basin, self.basin))

    @property
    def ace(self) -> float:
        return sum(s.ace for s in self.storms)

    @property
    def named(self) -> int:
        return sum(1 for s in self.storms if _tropical_peak(s.track, NAMED_STAGES) >= 34)

    @property
    def hurricanes(self) -> int:
        return sum(1 for s in self.storms if _tropical_peak(s.track, HURRICANE_STAGES) >= 64)

    @property
    def major(self) -> int:
        return sum(1 for s in self.storms if _tropical_peak(s.track, HURRICANE_STAGES) >= 96)

    @property
    def active(self) -> tuple[Storm, ...]:
        return tuple(s for s in self.storms if s.active)

    @property
    def normal_ace(self) -> float | None:
        """The date-matched normal: ACE a typical season had by today.

        Not the full-season normal. Comparing a season in progress against
        what seasons finish with is the single easiest way to make a busy
        September look quiet, and it is a mistake that gets made in public
        every year.
        """
        return self.normal.get("ace_todate")

    @property
    def full_normal_ace(self) -> float | None:
        return self.normal.get("ace")

    @property
    def elnino_ace(self) -> float | None:
        return self.elnino.get("ace_todate")

    @property
    def sample(self) -> int:
        return int(self.elnino.get("years", 0))

    @property
    def ace_ratio(self) -> float | None:
        """Season-to-date ACE as a fraction of the date-matched normal."""
        normal = self.normal_ace
        if not normal:
            return None
        return self.ace / normal

    @property
    def elnino_ratio(self) -> float | None:
        """The same, against past El Nino seasons at the same date."""
        normal = self.elnino_ace
        if not normal:
            return None
        return self.ace / normal

    @property
    def elapsed(self) -> float | None:
        """Fraction of a normal season's ACE that has fallen by this date.

        Printed beside the ratio so a reader can see how much of the season
        the comparison is actually made of. An Atlantic verdict on 1 July
        rests on four per cent of a season and should be read that way.
        """
        whole, sofar = self.normal.get("ace"), self.normal.get("ace_todate")
        if not whole or sofar is None:
            return None
        return sofar / whole


@dataclass
class CycloneState:
    """Everything the cyclone tier managed to build this run."""

    basins: dict = dc_field(default_factory=dict)
    as_of: str = ""
    year: int = 0
    through: str = ""
    elnino_years: tuple = ()
    # What went wrong this run; the run counts every one as a warning.
    notes: list[str] = dc_field(default_factory=list)
    # News, not a problem: an invest numbered since its deck's last fix.
    upgrades: list[str] = dc_field(default_factory=list)
    # JTWC's storms: live and tracked, but outside the seasons above, which
    # are the Atlantic and east Pacific the El Nino claim is tested on.
    others: tuple = ()
    invests: tuple = ()
    # JTWC's formation alerts and their cancellations, as the feed links them;
    # the outlook carries each one on its system's area.
    alerts: list = dc_field(default_factory=list)
    outlook: list = dc_field(default_factory=list)
    outlook_issued: dict = dc_field(default_factory=dict)

    @property
    def available(self) -> bool:
        return bool(self.basins)

    @property
    def storms(self) -> tuple[Storm, ...]:
        out: list[Storm] = []
        for season in self.basins.values():
            out.extend(season.storms)
        out.extend(self.others)
        return tuple(out)

    @property
    def active(self) -> tuple[Storm, ...]:
        """Live storms, strongest first, because that is the reading order."""
        live = [s for s in self.storms if s.active]
        live.sort(key=lambda s: -((s.latest.wind or 0) if s.latest else 0))
        return tuple(live)

    @property
    def dangerous(self) -> tuple[Storm, ...]:
        return tuple(s for s in self.active
                     if (s.latest and s.latest.category >= 3)
                     or s.intensifying_rapidly)


def link_for(basin: str):
    """The teleconnection entry whose claim this basin's season tests."""
    from . import impacts

    wanted = BASIN_LINK.get(basin.upper())
    for link in impacts.CATALOGUE:
        if link.region == wanted:
            return link
    return None


def expectation(link) -> str:
    """Which way the catalogue says this basin should go, in three words.

    Read off the catalogue's own ``effect`` wording rather than kept as a
    second copy here. The polarity field says ``storm`` for every basin - it
    records that the hazard is a storm, not which direction El Nino pushes it
    - so the direction has to come from the sentence that states it, and that
    sentence is the one the hazard outlook prints.
    """
    effect = link.effect.lower()
    if "suppress" in effect or "reduced" in effect or "fewer" in effect:
        return "below normal"
    if "enhanc" in effect or "increas" in effect or "more intense" in effect:
        return "above normal"
    return "unclear"


def verdict(season: BasinSeason, index: float, flavour) -> dict | None:
    """Score a basin against what the teleconnection catalogue predicted.

    The catalogue makes a falsifiable claim about each basin, and this is the
    only place in the system where one of its claims can be checked against an
    outcome in the same season it was made. ``impacts.evaluate`` does the
    gating, so the expectation here is the one the hazard outlook prints
    rather than a second opinion free to drift away from it.

    A season near its normal is reported as neither agreement nor
    disagreement. ENSO shifts the odds over a basin; it does not determine one
    season, and a 0.9x Atlantic is exactly what a suppressed basin and an
    ordinary basin both look like.
    """
    from . import impacts

    link = link_for(season.basin)
    if link is None:
        return None
    margin, likelihood, note = impacts.evaluate(link, index, flavour)
    expected = expectation(link)
    ratio = season.ace_ratio

    observed, agrees = "no reading", None
    if ratio is not None:
        if ratio >= 1.15:
            observed = "above normal"
        elif ratio <= 0.85:
            observed = "below normal"
        else:
            observed = "near normal"
        if observed != "near normal" and expected != "unclear":
            agrees = observed == expected

    elnino_ratio = season.elnino_ratio
    return {
        "basin": season.basin,
        "name": season.name,
        "region": link.region,
        "effect": link.effect,
        "expected": expected,
        "observed": observed,
        "agrees": agrees,
        "likelihood": likelihood,
        "margin": round(margin, 2),
        "note": note,
        "confidence": link.confidence,
        "ace": round(season.ace, 1),
        "named": season.named,
        "hurricanes": season.hurricanes,
        "major": season.major,
        "normal_ace": None if season.normal_ace is None else round(season.normal_ace, 1),
        "full_normal_ace": None if season.full_normal_ace is None else round(season.full_normal_ace, 1),
        "ratio": None if ratio is None else round(ratio, 2),
        "elnino_ace": None if season.elnino_ace is None else round(season.elnino_ace, 1),
        "elnino_ratio": None if elnino_ratio is None else round(elnino_ratio, 2),
        "elapsed": None if season.elapsed is None else round(season.elapsed, 2),
        "sample": season.sample,
        "through": season.through,
    }


# --------------------------------------------------------------------------
# HURDAT2, for the climatology the season is measured against
# --------------------------------------------------------------------------
HURDAT_HEADER = re.compile(r"^(AL|EP|CP)(\d\d)(\d{4}),")


FIELDS = ("ace", "named", "hurricanes", "major")


def hurdat_seasons(text: str, through: tuple | None = None) -> dict:
    """ACE and storm counts per season, from a HURDAT2 best-track file.

    HURDAT2 alternates a header line naming the storm with a block of
    six-hourly observations, and the header carries the count of lines that
    follow. That count is trusted for nothing: a line that starts with a basin
    code is a header and anything else is an observation, which survives the
    occasional off-by-one in the published file.

    Every quantity is returned twice - once for the whole season, and once
    counting only what had happened by ``through``, a ``(month, day)`` pair.
    The second is the one a running season can honestly be compared against.
    Half of an Atlantic season's ACE typically falls after 10 September, so
    scoring 23 September against a full-season mean makes every season in
    progress look suppressed, including the ones that are about to be records.
    """
    seasons: dict[int, dict] = {}
    year = 0
    peak = peak_todate = 0
    named = named_todate = False

    def close():
        if not year:
            return
        entry = _blank(seasons, year)
        if named:
            entry["named"] += 1
        if named_todate:
            entry["named_todate"] += 1
        for value, suffix in ((peak, ""), (peak_todate, "_todate")):
            if value >= 64:
                entry["hurricanes" + suffix] += 1
            if value >= 96:
                entry["major" + suffix] += 1

    for line in text.splitlines():
        header = HURDAT_HEADER.match(line)
        if header:
            close()
            year = int(header.group(3))
            peak = peak_todate = 0
            named = named_todate = False
            _blank(seasons, year)
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 7 or not year:
            continue
        stamp, hour, stage = parts[0], parts[1], parts[3].upper()
        if not stamp.isdigit() or len(stamp) != 8 or len(hour) != 4:
            continue
        try:
            wind = int(parts[6])
        except ValueError:
            continue
        if wind < 0:
            continue
        early = through is None or (int(stamp[4:6]), int(stamp[6:8])) <= through
        if wind >= 34 and stage in NAMED_STAGES:
            named = True
            named_todate = named_todate or early
        if stage in HURRICANE_STAGES:
            peak = max(peak, wind)
            if early:
                peak_todate = max(peak_todate, wind)
        if (int(hour[:2]) in SYNOPTIC and hour[2:] == "00"
                and stage in ACE_STAGES and wind >= 34):
            seasons[year]["ace"] += wind ** 2 * 1e-4
            if early:
                seasons[year]["ace_todate"] += wind ** 2 * 1e-4
    close()
    return seasons


def _blank(seasons: dict, year: int) -> dict:
    keys = [f + suffix for f in FIELDS for suffix in ("", "_todate")]
    return seasons.setdefault(year, {k: 0.0 if k.startswith("ace") else 0
                                     for k in keys})


def merge_seasons(*tables: dict) -> dict:
    """Add two HURDAT2 season tables together, basin by basin.

    The east and central Pacific are two warning centres and one basin as far
    as El Nino is concerned, and the catalogue treats them as one region, so
    their activity is summed rather than compared.
    """
    out: dict[int, dict] = {}
    for table in tables:
        for year, entry in table.items():
            target = _blank(out, year)
            for key, value in entry.items():
                target[key] = target.get(key, 0) + value
    return out


def normals(seasons: dict, first: int = 1991, last: int = 2020) -> dict:
    """The WMO 30-year normal period, which is what "normal" means on a chart."""
    return _mean(
        [v for y, v in seasons.items() if first <= y <= last],
        period=f"{first}-{last}",
    )


def composite(seasons: dict, years) -> dict:
    """Mean activity over a named set of years - here, past El Nino seasons.

    A normal answers "is this season busy". This answers the question a reader
    holding an ENSO forecast actually has: "is this season busy *for an El
    Nino season*", which in the Atlantic is a much lower bar and in the east
    Pacific a higher one.
    """
    return _mean([seasons[y] for y in years if y in seasons], period="El Nino")


def _mean(window: list, period: str) -> dict:
    if not window:
        return {}
    count = len(window)
    out = {key: sum(v.get(key, 0) for v in window) / count
           for key in window[0]}
    out["period"] = period
    out["years"] = count
    return out


# --------------------------------------------------------------------------
# NHC's live advisory index
# --------------------------------------------------------------------------
def parse_current(text: str) -> dict:
    """``CurrentStorms.json`` keyed by ATCF id.

    This carries what the decks do not: the storm's public name before the
    b-deck catches up, the advisory number, and links to the discussion a
    forecaster wrote. It is the only feed here that is not a best track, and
    it is treated as metadata - never as a position, because the deck is the
    authority on that and they can disagree by an advisory cycle.
    """
    try:
        payload = json.loads(text)
    except (ValueError, TypeError):
        return {}
    out = {}
    for storm in payload.get("activeStorms", []):
        key = str(storm.get("id", "")).lower()
        if not key:
            continue
        out[key] = {
            "name": storm.get("name", ""),
            "classification": storm.get("classification", ""),
            "wind": _int(str(storm.get("intensity", ""))),
            "pressure": _int(str(storm.get("pressure", ""))),
            "lat": storm.get("latitudeNumeric"),
            "lon": storm.get("longitudeNumeric"),
            "movement_dir": storm.get("movementDir"),
            # The index gives the forward speed in mph, as the public
            # advisory does; the discussion's knots are that divided back.
            "movement_mph": storm.get("movementSpeed"),
            "movement_kt": _knots(storm.get("movementSpeed")),
            "last_update": storm.get("lastUpdate", ""),
            "advisory": (storm.get("publicAdvisory") or {}).get("advNum", ""),
            "discussion": (storm.get("forecastDiscussion") or {}).get("url", ""),
            "public": (storm.get("publicAdvisory") or {}).get("url", ""),
            "graphics": _link(storm.get("forecastGraphics"), "url"),
            # Null in the index means the product was not issued - no
            # watches in effect - which is not the same as failing to fetch it.
            "products": {
                "watches": _link(storm.get("windWatchesWarnings"), "kmzFile"),
                "cone": _link(storm.get("trackCone"), "kmzFile"),
                "surge": _link(storm.get("peakSurgeKML"), "peakSurgeKMLFile"),
                "winds": _link(storm.get("windSpeedProbabilities"), "url"),
                # The public advisory, for what it says is in effect.
                "in_effect": _link(storm.get("publicAdvisory"), "url"),
            },
            # Each product's own advisory number, which is not always the
            # public advisory's: an intermediate advisory reissues some.
            "product_advisories": {
                "watches": _link(storm.get("windWatchesWarnings"), "advNum"),
                "cone": _link(storm.get("trackCone"), "advNum"),
                "surge": _link(storm.get("peakSurgeKML"), "advNum"),
                "winds": _link(storm.get("windSpeedProbabilities"), "advNum"),
                "in_effect": _link(storm.get("publicAdvisory"), "advNum"),
            },
        }
    return out


MPH_PER_KT = 1.150779


def _knots(mph) -> int | None:
    """A speed the index gives in mph, in whole knots."""
    if isinstance(mph, bool) or not isinstance(mph, (int, float)):
        return None
    return round(mph / MPH_PER_KT)


def _link(entry, field: str) -> str:
    """A URL from one of the index's product entries, or "" if not issued."""
    if not isinstance(entry, dict):
        return ""
    return str(entry.get(field) or "")


BTK_FILE = re.compile(r"\bb(al|ep|cp)(\d\d)(\d{4})\.dat\b", re.I)
# 90-99 are invest numbers - a disturbance being watched, which may become a
# storm or may become nothing. They carry a b-deck, and counting them would
# inflate a season with systems that never existed as cyclones.
FIRST_INVEST = 90


def season_ids(listing: str, year: int) -> list[str]:
    """Every real storm of one season, from the best-track directory listing.

    Active storms are the urgent part of this tier but they are not the
    season. Season-to-date activity - the number the El Nino claim is actually
    tested against - needs the ones that have already come and gone, and
    HURDAT2 will not carry them until the season is reanalysed the following
    spring. The live directory has them now.
    """
    found = set()
    for match in BTK_FILE.finditer(listing):
        basin, number, stamp = match.group(1).upper(), int(match.group(2)), int(match.group(3))
        if stamp != year or basin not in BASINS or number >= FIRST_INVEST:
            continue
        found.add(f"{basin.lower()}{number:02d}{stamp}")
    return sorted(found)


def active_ids(current: dict) -> list[str]:
    """ATCF ids of every live storm in a basin this system follows."""
    return sorted(
        key for key in current
        if len(key) == 8 and key[:2].upper() in BASINS and key[2:4].isdigit()
    )


def split_id(key: str) -> tuple[str, int, int]:
    """``ep172026`` -> ``("EP", 17, 2026)``."""
    return key[:2].upper(), int(key[2:4]), int(key[4:8])


def hurdat_latest(index_html: str, basin: str) -> str | None:
    """The newest HURDAT2 file named on NHC's index page.

    The filename carries both the last season and the revision date and is
    renamed every spring, so hard-coding it means the climatology silently
    stops updating. The index is scraped instead and the file with the latest
    end-year wins, with the revision date breaking a tie.
    """
    pattern = (r"hurdat2-nepac-1949-(\d{4})-(\d{6,8})\.txt" if basin == "EP"
               else r"hurdat2-1851-(\d{4})-(\d{6,8})\.txt")
    best = None
    for match in re.finditer(pattern, index_html):
        stamp = match.group(2)
        # Revisions are written both MMDDYY and MMDDYYYY; normalise to a
        # comparable year-first key so a 2026 revision beats a 2025 one.
        year = stamp[-4:] if len(stamp) == 8 else "20" + stamp[-2:]
        rank = (int(match.group(1)), year, stamp[:4])
        if best is None or rank > best[0]:
            best = (rank, match.group(0))
    return best[1] if best else None


# --------------------------------------------------------------------------
# assembly
# --------------------------------------------------------------------------
# The season whose ONI defines a hurricane season's ENSO state. ASO is the
# climatological peak of the Atlantic season and sits inside the east Pacific
# one, so it is the season a basin composite should be keyed on - not DJF,
# which is the peak of the *event* and arrives after both seasons have ended.
SEASON_KEY = "ASO"
EVENT_FLOOR = 0.5


def elnino_years(series, floor: float = EVENT_FLOOR) -> tuple[int, ...]:
    """Hurricane seasons that ran under El Nino, from the official index.

    ``series`` is RONI, CPC's index since February 2026, compared on the value
    CPC prints. That changes the composite: ASO 1977, 1993 and 1994 were El
    Nino seasons by RONI and not by the ONI file, and ASO 2018 was the reverse.

    Derived rather than listed. A hard-coded set of years is a second opinion
    about what counts as an event, and it goes stale the moment CPC reissues
    the index - which it does, because both are recomputed as base periods
    move and past seasons change value.
    """
    from .classify import displayed

    return tuple(sorted(
        s.year for s in series
        if s.season == SEASON_KEY and displayed(s.value) >= floor
    ))


def build(fetched: dict, index=None, fetcher=None, today=None) -> CycloneState:
    """Assemble the cyclone tier from what came back, tolerating gaps.

    Additive, like the spatial tier: nothing here feeds the ENSO
    classification or the forecast, so every step runs inside its own guard
    and a failure costs a panel rather than the run. The one ordering
    constraint is real - the live-storm index has to be read before the decks,
    because the decks are named after storms that only that index knows exist.
    """
    from datetime import date

    state = CycloneState()
    text = {key: item.text for key, item in fetched.items() if item.ok}
    today = today or date.today()
    cutoff = (today.month, today.day)
    state.through = today.strftime("%d %B")

    def attempt(label: str, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - recorded, never fatal
            state.notes.append(f"{label}: {type(exc).__name__}: {exc}")
            return None

    current = attempt("active storms", parse_current, text.get("nhc_current", "")) or {}
    if "nhc_current" not in text:
        state.notes.append("No active-storm index: live storms cannot be listed.")
    state.as_of = max((m["last_update"] for m in current.values()), default="")
    state.year = _season_year(current, today)
    warm = elnino_years(index or [])
    state.elnino_years = warm

    # --- climatology, which is what makes this season's number mean anything
    archive: dict[str, dict] = {}
    index = text.get("hurdat_index", "")
    for basin in ("AL", "EP"):
        filename = hurdat_latest(index, basin)
        if not filename:
            state.notes.append(
                f"No HURDAT2 file listed for {basin}: this season has no "
                "climatology to be measured against."
            )
            continue
        raw = text.get(f"hurdat_{basin.lower()}")
        if raw is None and fetcher is not None:
            from . import sources
            got = attempt(f"HURDAT2 {basin}", fetcher,
                          sources.hurdat_source(basin, filename))
            if got is not None and got.ok:
                raw = got.text
            elif got is not None:
                state.notes.append(f"HURDAT2 {basin}: {got.error}")
        if raw:
            parsed = attempt(f"HURDAT2 {basin} parse", hurdat_seasons, raw,
                             through=cutoff)
            if parsed:
                archive[basin] = parsed

    # --- this season's storms, from the decks
    live = set(active_ids(current))
    roster = set(season_ids(text.get("atcf_index", ""), state.year)) | live
    if not text.get("atcf_index"):
        state.notes.append(
            "No best-track directory listing: only live storms are counted, "
            "so season-to-date activity is a floor rather than a total."
        )
    by_season: dict[str, list[Storm]] = {"AL": [], "EP": []}
    for key in sorted(roster):
        basin, number, storm_year = split_id(key)
        storm = attempt(f"{key} decks", _storm, key, basin, number, storm_year,
                        current.get(key, {}), fetcher, state, key in live)
        if storm is not None:
            by_season.setdefault(season_of(basin), []).append(storm)

    for basin, storms in by_season.items():
        table = archive.get(basin, {})
        state.basins[basin] = BasinSeason(
            basin=basin,
            storms=tuple(sorted(storms, key=lambda s: (s.basin, s.number))),
            normal=normals(table) if table else {},
            elnino=composite(table, warm) if table and warm else {},
            through=state.through,
        )

    attempt("JTWC", _jtwc, text, fetcher, state)
    attempt("outlooks", _outlooks, text, state)
    attempt("invests", _invests, text, fetcher, state, today)
    return state


def _jtwc(text: dict, fetcher, state: CycloneState) -> None:
    """JTWC's live storms: the west Pacific, Indian Ocean and south."""
    from . import jtwc, sources

    if "jtwc_rss" not in text:
        state.notes.append("No JTWC index: storms in the west Pacific, Indian "
                           "Ocean and southern hemisphere are not listed.")
        return
    if fetcher is None:
        return
    found, ends, undated = [], [], []
    for filename in jtwc.warning_files(text["jtwc_rss"]):
        source = sources.jtwc_source(filename)
        got = fetcher(source)
        if not got.ok:
            state.notes.append(f"JTWC {filename}: {got.error}")
            continue
        # The feed links a formation alert as it links a warning.
        alert = jtwc.formation_alert(got.text, source.url)
        if alert is not None:
            state.alerts.append(alert)
            if not alert.issued and not alert.cancelled:
                undated.append((filename, alert))
            continue
        storm = jtwc.parse_tcw(got.text, source.url)
        if storm is None:
            state.notes.append(f"JTWC {filename}: not a warning this reader knows")
            continue
        found.append(storm)
        end = jtwc.superseding(got.text, storm)
        if end is not None:
            ends.append(end)
    state.others = tuple(found)
    # A storm's first warning ends the alert it grew from, linked or not.
    state.alerts = jtwc.superseded(state.alerts, ends)
    # An alert that gives no time cannot be put before or after the advisories:
    # it is kept, and said to be kept, since it may be the older.
    for filename, alert in undated:
        if alert in state.alerts:
            state.notes.append(f"JTWC {filename}: the formation alert gives no issue "
                               "time; it is kept as in effect.")


# The outlooks, the basin (or JTWC product) each covers, and its name.
OUTLOOKS = (("nhc_outlook_at", "AL", "Atlantic"),
            ("nhc_outlook_ep", "EP", "eastern North Pacific"),
            ("nhc_outlook_cp", "CP", "central North Pacific"),
            ("jtwc_abpw", "ABPW", "west and south Pacific (JTWC)"),
            ("jtwc_abio", "ABIO", "Indian Ocean (JTWC)"))


def _outlooks(text: dict, state: CycloneState) -> None:
    """Every official formation outlook, merged so each system is listed once,
    with JTWC's formation alerts laid on the areas they are for."""
    from . import jtwc, outlook

    groups = []
    for key, code, name in OUTLOOKS:
        if key not in text:
            state.notes.append(f"No formation outlook for the {name} this run.")
            continue
        try:
            if code.startswith("AB"):
                areas = jtwc.disturbances(text[key])
                issued = jtwc.advisory_time(text[key])
            else:
                issued, areas = outlook.nhc(text[key], code)
        except Exception:  # noqa: BLE001 - an unreadable outlook is a note
            # Not "nothing expected": the others are still read.
            state.notes.append(f"The formation outlook for the {name} could not be read.")
            continue
        groups.append(areas)
        state.outlook_issued[code] = issued
    state.outlook = outlook.merge(*jtwc.alerted(groups, state.alerts, state.outlook_issued))


# NHC's letter for each basin in an invest's name: Invest 90L, 99E, 90C.
INVEST_LETTER = {"AL": "L", "EP": "E", "CP": "C"}
# An invest whose latest fix is older than this has been dropped.
INVEST_STALE_HOURS = 24
# An invest whose latest fix lies this close to a storm's fix at the same hour
# is that storm: a centre that upgrades an invest opens the storm's deck on the
# invest's history, so the two decks share their fixes to the hour.
INVEST_SAME_KM = 150


def _invests(text: dict, fetcher, state: CycloneState, today) -> None:
    """The invests still being tracked, from their best-track decks.

    The directory keeps an invest's deck after the system is dropped, and
    reuses the number for the next one, so a deck counts only while its
    latest fix is within a day of the newest advisory.
    """
    from . import outlook, sources

    candidates = outlook.invest_candidates(text.get("atcf_index", ""))
    if not candidates or fetcher is None:
        return
    reference = (state.as_of[:13].replace("-", "").replace("T", "")
                 if len(state.as_of) >= 13 else today.strftime("%Y%m%d") + "00")
    found = []
    for key in candidates:
        got = fetcher(sources.deck_source("b", key))
        if not got.ok:
            continue
        track = [f for f in parse_atcf(got.text) if f.tau == 0]
        if not track or _hours_between(track[-1].stamp, reference) > INVEST_STALE_HOURS:
            continue
        basin, number, year = split_id(key)
        name = f"Invest {number}{INVEST_LETTER.get(basin, '')}"
        became = _became(track[-1], state.storms)
        if became is not None:
            # Its deck stopped when it was upgraded; listed, it would read as
            # "not yet a tropical cyclone" beside the storm it already is.
            state.upgrades.append(f"{name} is now {became.title} ({became.designation}).")
            continue
        found.append(Storm(basin=basin, number=number, year=year, name=name,
                           track=tuple(track), invest=True))
    state.invests = tuple(found)


def _became(fix: Fix, storms) -> Storm | None:
    """The storm an invest was upgraded to, if its latest fix is that storm's."""
    near = [(great_circle(fix.lon, fix.lat, f.lon, f.lat), n, storm)
            for n, storm in enumerate(storms) for f in storm.track
            if f.tau == 0 and f.stamp == fix.stamp]
    near = [row for row in near if row[0] <= INVEST_SAME_KM]
    return min(near)[2] if near else None


def _season_year(current: dict, today) -> int:
    """The season these storms belong to.

    Read from an advisory stamp when there is one, because a storm that forms
    on 31 December in one hemisphere is still numbered in the year it formed,
    and falling back on the calendar would file it under the next one.
    """
    for meta in current.values():
        stamp = str(meta.get("last_update", ""))
        if len(stamp) >= 4 and stamp[:4].isdigit():
            return int(stamp[:4])
    return today.year


def issuing_centre(storm) -> str:
    """The centre that issues this storm's advisories.

    An east Pacific storm that crosses 140W keeps its EP number, and CPHC
    writes its advisories from there on: the advisory's own file name says
    which office wrote it, MIA for Miami and HFO for Honolulu. Without one,
    the position decides.
    """
    from . import outlook

    if storm.centre != "NHC":
        return storm.centre
    public = str((storm.advisory or {}).get("public") or "")
    office = public.rsplit("/", 1)[-1][:3].upper()
    if office in ("HFO", "MIA"):
        return "CPHC" if office == "HFO" else "NHC"
    now = storm.latest
    if storm.basin == "CP" or (now is not None and outlook.aor(now.lon, now.lat) == "CP"):
        return "CPHC"
    return "NHC"


def _storm(key: str, basin: str, number: int, year: int, meta: dict,
           fetcher, state: CycloneState, live: bool = True) -> Storm | None:
    """Build one storm from its decks. Only the b-deck is required.

    A finished storm gets its best track and nothing else. Its forecast decks
    still exist, and fetching them would add a megabyte apiece to describe
    where a dissipated system was once expected to go.
    """
    from . import sources

    if fetcher is None:
        return None
    storm = Storm(basin=basin, number=number, year=year,
                  name=meta.get("name", ""), advisory=meta)

    best = fetcher(sources.deck_source("b", key, storm.name))
    if not best.ok:
        state.notes.append(f"{key} best track: {best.error}")
        return None
    storm.track = tuple(parse_atcf(best.text))
    if not storm.name:
        storm.name = storm_name(best.text)
    storm.centre = issuing_centre(storm)

    if not live:
        return storm

    storm.products = _products(key, storm.name, meta, fetcher)

    official = fetcher(sources.deck_source("f", key, storm.name))
    if official.ok:
        storm.forecast = tuple(f for f in parse_atcf(official.text)
                               if f.tech in {OFFICIAL, "OFCI", "CARQ"} and f.tau > 0)
    else:
        storm.notes.append(f"no official forecast deck ({official.error})")

    guidance = fetcher(sources.deck_source("a", key, storm.name))
    if guidance.ok:
        members = ensemble_techs(guidance.text)
        keep = wanted_techs() | members
        fixes = parse_atcf(guidance.text, techs=keep)
        tracks = latest_guidance(fixes)
        storm.guidance = {t: f for t, f in tracks.items() if t not in members}
        storm.ensemble = {t: f for t, f in tracks.items() if t in members}
        # The a-deck carries OFCL too, and it is the same forecast. If the
        # f-deck was missing, take it from here rather than showing a storm
        # with no forecast at all.
        if not storm.forecast and OFFICIAL in storm.guidance:
            storm.forecast = storm.guidance[OFFICIAL]
    else:
        storm.notes.append(f"no guidance deck ({guidance.error})")

    # Every lead from here on is hours after the latest analysis.
    now = storm.latest
    if now is not None:
        storm.forecast = rebase(storm.forecast, now.stamp)
        storm.guidance = _rebased(storm.guidance, now.stamp)
        storm.ensemble = _rebased(storm.ensemble, now.stamp)
    return storm


# Each protective product: the index's name for it, what to call it, and
# how to read it. A reader returning None, or an empty cone, is unreadable.
def _read_products():
    from . import tcproducts
    return (
        ("watches", "Watches and warnings", lambda t: tuple(tcproducts.watches_warnings(t))),
        ("cone", "Forecast cone", tcproducts.cone),
        ("surge", "Peak storm surge", lambda t: tuple(tcproducts.peak_surge(t))),
        ("winds", "Wind speed probabilities", tcproducts.wind_probabilities),
        ("in_effect", "Public advisory", tcproducts.in_effect),
    )


def _advisory_number(text: str) -> str:
    """``"020"`` -> ``"20"``, ``"021a"`` -> ``"21A"``, as the products write it."""
    text = str(text or "").strip().upper()
    return text.lstrip("0") or ("0" if text else "")


# The products reissued with an intermediate advisory - 20A, issued between
# full ones while watches or warnings are up. The surge and the wind
# probabilities come with full advisories only: under 20A, 20's are still
# the latest there are.
EVERY_ADVISORY = ("watches", "cone", "in_effect")


def _advisory_order(number: str):
    """``"20A"`` -> ``(20, "A")``; None for anything that is not a number."""
    found = re.fullmatch(r"(\d+)([A-Z]?)", _advisory_number(number))
    return (int(found.group(1)), found.group(2)) if found else None


def _older(kind: str, number: str, current: str) -> bool:
    """Whether a product of advisory ``number`` is superseded at ``current``."""
    mine, now = _advisory_order(number), _advisory_order(current)
    if mine is None or now is None:
        return False
    if kind not in EVERY_ADVISORY:
        return mine[0] < now[0]
    return mine < now


def _products(key: str, name: str, meta: dict, fetcher):
    """What NHC issued for one storm at its current advisory.

    A product the index does not link was not issued: ``()``, or None for
    the wind table, with nothing to say about it. One it links but that
    cannot be fetched or read is None with a note saying so. Each keeps its own
    advisory number - the file's, else the index's - and one that a later
    advisory has superseded is kept with a note saying which: a person reading
    it should know it may be out of date.
    """
    from . import sources, tcproducts

    links = meta.get("products") or {}
    numbers = meta.get("product_advisories") or {}
    expected = _advisory_number(meta.get("advisory", ""))
    values: dict = {}
    notes: list[str] = []
    unavailable: list[str] = []
    advisories: list[tuple[str, str]] = []
    for kind, label, read in _read_products():
        url = links.get(kind, "")
        if not url:
            values[kind] = None if kind == "winds" else ()
            continue
        got = fetcher(sources.product_source(kind, key, url, name))
        if not got.ok:
            values[kind] = None
            notes.append(f"{label} unavailable ({got.error})")
            unavailable.append(label)
            continue
        try:
            value = read(got.text)
        except Exception:  # noqa: BLE001 - an unreadable product is a note
            value = None
        if value is None or (kind == "cone" and not value):
            values[kind] = None
            notes.append(f"{label} could not be read")
            unavailable.append(label)
            continue
        values[kind] = value
        own = (_advisory_number(tcproducts.advisory_of(got.text))
               or _advisory_number(numbers.get(kind, "")))
        if not own:
            continue
        advisories.append((kind, own))
        if expected and _older(kind, own, expected):
            notes.append(f"{label} {'are' if label.endswith('s') else 'is'} from "
                         f"advisory {own}; the current advisory is {expected}")
    return tcproducts.Products(watches=values["watches"], cone=values["cone"],
                               surge=values["surge"], winds=values["winds"],
                               in_effect=values["in_effect"],
                               advisory=expected, notes=tuple(notes),
                               unavailable=tuple(unavailable),
                               advisories=tuple(advisories))


def _rebased(tracks: dict, reference: str) -> dict:
    out = {}
    for tech, fixes in tracks.items():
        ahead = rebase(fixes, reference)
        if len(ahead) > 1:
            out[tech] = ahead
    return out
