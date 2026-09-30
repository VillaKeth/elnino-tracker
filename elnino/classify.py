"""ENSO state classification, event detection, scale/power diagnostics, analogs.

Conventions follow NOAA CPC:

* The official index is the Relative Oceanic Nino Index. CPC switched ENSO
  monitoring, prediction and its historical event table from ONI to RONI on
  1 February 2026 (NWS Public Information Statement 26-05). ONI - now on
  ERSSTv6 - is still published for continuity and is reported here as the
  legacy index. It stands in for RONI only when RONI is unavailable.
* An El Nino *episode* requires the index to sit at or above +0.5 degC for five
  consecutive overlapping three-month seasons. Fewer than five consecutive
  seasons means El Nino *conditions* are present but the episode is not yet
  established in the historical record.
* Thresholds are applied to the value CPC prints, which has one decimal: a
  file value of 0.46 is printed, coloured and counted as 0.5. Rounding half
  away from zero reproduces 911 of the 912 RONI cells CPC colours and all 239
  warm ONI cells; comparing the two-decimal file against 0.5 finds only 215 of
  those 239. The one RONI miss is an exact tie (-0.45) that CPC rounded from
  more digits than it publishes, which no rule can recover.
* Intensity tiers use the same printed value:
  weak 0.5-0.9, moderate 1.0-1.4, strong 1.5-1.9, very strong >= 2.0.

The composite "power index" at the bottom of this module is a derived
diagnostic of this tracker, not a NOAA product. Its inputs and weights are
spelled out so the number can be audited or rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .parsers import MonthValue, SeasonValue, WeekObservation

EVENT_THRESHOLD = 0.5
MIN_SEASONS_FOR_EPISODE = 5
# A level RONI has not reached since 1950: its record season is +2.4, in
# 1982-83. The power index reads this as 100.
HISTORIC_RONI = 2.5

# (lower bound, label) evaluated top-down on the peak ONI of an episode.
INTENSITY_TIERS: tuple[tuple[float, str], ...] = (
    (2.0, "Very Strong"),
    (1.5, "Strong"),
    (1.0, "Moderate"),
    (0.5, "Weak"),
)

# Weights for the composite power index; documented in README.md.
POWER_WEIGHTS = {"amplitude": 0.40, "coupling": 0.25, "basin_scale": 0.20, "momentum": 0.15}


def clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


# Where the Nino-1+2 minus Nino-4 difference calls an event east- or
# central-Pacific. The cut is not symmetric because the two regions do not
# swing alike: Nino-1+2 runs to +3.7 in an east-Pacific peak while Nino-4
# rarely passes +1.1, so the difference goes far positive in 1982-83 and
# 1997-98 (+2.4, +3.5 on the relative indices, OND) and only a little
# negative in the central-Pacific events - 2009-10, the textbook Modoki
# case, averaged -0.91 over OND 2009. At -1.0 no El Nino since 1982
# would be central-Pacific. The scale card and the hazard outlook both read
# these, so the page cannot call one event two things.
EP_FLAVOUR = 1.0
CP_FLAVOUR = -0.5


def displayed(value: float) -> float:
    """The value as CPC prints it: one decimal, ties away from zero.

    Through ``repr`` rather than straight from the float, because 0.15 and
    0.25 are not exactly representable and ``round`` would take the binary
    value's side of the tie - 0.1 and 0.2 - where CPC prints 0.2 and 0.3.
    """
    printed = Decimal(repr(value)).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return float(printed) + 0.0  # never "-0.0"


def intensity_tier(value: float) -> str:
    """NOAA intensity label for an index value; La Nina mirrored for completeness."""
    value = displayed(value)
    if value <= -0.5:
        for bound, label in INTENSITY_TIERS:
            if -value >= bound:
                return f"{label} La Nina"
        return "Weak La Nina"
    for bound, label in INTENSITY_TIERS:
        if value >= bound:
            return f"{label} El Nino"
    return "Neutral"


@dataclass
class Episode:
    """A run of consecutive seasons on one side of the +/-0.5 threshold."""

    seasons: list[SeasonValue]
    warm: bool = True

    def __post_init__(self) -> None:
        # Every property below indexes the list, so an empty one is not an
        # episode with no seasons, it is three different IndexErrors waiting
        # for whichever panel reads it first.
        if not self.seasons:
            raise ValueError("an episode needs at least one season")

    @property
    def onset(self) -> SeasonValue:
        return self.seasons[0]

    @property
    def latest(self) -> SeasonValue:
        return self.seasons[-1]

    @property
    def peak(self) -> SeasonValue:
        key = max if self.warm else min
        return key(self.seasons, key=lambda s: s.value)

    @property
    def length(self) -> int:
        return len(self.seasons)

    @property
    def qualifies(self) -> bool:
        return self.length >= MIN_SEASONS_FOR_EPISODE

    @property
    def tier(self) -> str:
        return intensity_tier(self.peak.value)

    @property
    def name(self) -> str:
        start = self.onset.year
        end = self.latest.year
        return f"{start}-{str(end)[-2:]}" if end != start else str(start)

    @property
    def values(self) -> list[float]:
        return [s.value for s in self.seasons]


def find_episodes(series: list[SeasonValue], warm: bool = True) -> list[Episode]:
    """Split a seasonal series into runs that breach the +/-0.5 threshold."""
    episodes: list[Episode] = []
    run: list[SeasonValue] = []
    for item in series:
        value = displayed(item.value)
        breaches = value >= EVENT_THRESHOLD if warm else value <= -EVENT_THRESHOLD
        if breaches:
            run.append(item)
        else:
            if run:
                episodes.append(Episode(run, warm))
            run = []
    if run:
        episodes.append(Episode(run, warm))
    return episodes


def current_episode(series: list[SeasonValue], warm: bool = True) -> Episode | None:
    """The episode still in progress as of the last reported season, if any."""
    episodes = find_episodes(series, warm)
    if not episodes:
        return None
    last = episodes[-1]
    return last if last.latest.centre == series[-1].centre else None


@dataclass
class Ranking:
    value: float
    rank_all: int
    total_all: int
    rank_season: int
    total_season: int
    season: str

    @property
    def percentile_all(self) -> float:
        return 100.0 * (self.total_all - self.rank_all) / self.total_all


def rank_value(series: list[SeasonValue], target: SeasonValue) -> Ranking:
    """Rank a season against the whole record and against the same calendar season.

    The same-season comparison matters because ENSO amplitude has a strong
    annual cycle -- a +1.8 in JJA is not the same animal as a +1.8 in DJF.
    """
    all_values = sorted((s.value for s in series), reverse=True)
    rank_all = all_values.index(target.value) + 1

    same = sorted((s.value for s in series if s.season == target.season), reverse=True)
    rank_season = same.index(target.value) + 1
    return Ranking(target.value, rank_all, len(all_values), rank_season, len(same), target.season)


@dataclass
class Analog:
    episode: Episode
    rmse: float
    peak_value: float
    peak_label: str
    seasons_to_peak: int  # from the stage the current event has reached
    tier: str


def find_analogs(
    history: list[SeasonValue], current: Episode, limit: int = 4
) -> list[Analog]:
    """Match the current episode's trajectory against past episodes at the same phase.

    Only the first N seasons of each past episode are compared, where N is the
    length of the current run, so the comparison is like-for-like in development
    stage rather than in calendar position.
    """
    phase = current.length
    out: list[Analog] = []
    for episode in find_episodes(history, warm=True):
        if episode.onset.centre == current.onset.centre or episode.length < phase:
            continue
        # A run that never reached five seasons is not an El Nino in CPC's
        # table, and an analog that "peaked" at the end of a false start
        # says nothing about where a real event goes next.
        if not episode.qualifies:
            continue
        head = episode.values[:phase]
        errors = [(a - b) ** 2 for a, b in zip(head, current.values)]
        if not errors:
            # Nothing overlaps, so there is no distance to report. An event one
            # season old against a record that starts mid-season can reach
            # this, and a zero rmse here would rank as a perfect analog.
            continue
        rmse = (sum(errors) / len(errors)) ** 0.5
        peak = episode.peak
        out.append(
            Analog(
                episode=episode,
                rmse=rmse,
                peak_value=peak.value,
                peak_label=peak.label,
                # Counted from the analog's equivalent of today - its season
                # number ``phase`` - because "how long until it peaked" is the
                # question, and counting from onset overstated it by the
                # seasons the current event has already used up.
                seasons_to_peak=episode.values.index(peak.value) - (phase - 1),
                tier=episode.tier,
            )
        )
    out.sort(key=lambda a: a.rmse)
    return out[:limit]


@dataclass
class RegionState:
    key: str
    label: str
    anomaly: float  # relative to the tropical mean where CPC publishes that
    sst: float
    traditional: float | None = None  # against the fixed 30-year base alone

    @property
    def active(self) -> bool:
        return displayed(self.anomaly) >= EVENT_THRESHOLD


@dataclass
class ScaleDiagnostic:
    regions: list[RegionState]
    flavour_index: float
    flavour: str
    active_regions: int
    basin_score: float
    basis: str = "traditional"  # or "relative"


REGIONS: tuple[tuple[str, str], ...] = (
    ("nino12", "Nino-1+2 (coastal Peru/Ecuador)"),
    ("nino3", "Nino-3 (eastern Pacific)"),
    ("nino34", "Nino-3.4 (east-central, index region)"),
    ("nino4", "Nino-4 (central/western Pacific)"),
)


def diagnose_scale(
    week: WeekObservation, relative: dict[str, float] | None = None
) -> ScaleDiagnostic:
    """Spatial extent and flavour of the event from the four Nino regions.

    ``relative`` is the same week from CPC's relative weekly file - each
    region's anomaly with the tropical-mean anomaly removed and rescaled, the
    regional counterpart of RONI and the numbers CPC's own discussion now
    quotes. Where it covers all four regions it is what the diagnostic runs
    on; the traditional anomaly is kept beside it, because the gap between the
    two is how much of a region's warmth is the whole tropical ocean.

    flavour_index = Nino-1+2 anomaly minus Nino-4 anomaly. Strongly positive
    means the warmth is concentrated in the eastern Pacific (canonical / EP
    event, as in 1982-83 and 1997-98); negative means a central-Pacific
    "Modoki" event. This is a simple proxy, not the formal E/C EOF indices.
    """
    traditional = {
        "nino12": week.nino12_anom, "nino3": week.nino3_anom,
        "nino34": week.nino34_anom, "nino4": week.nino4_anom,
    }
    sst = {
        "nino12": week.nino12_sst, "nino3": week.nino3_sst,
        "nino34": week.nino34_sst, "nino4": week.nino4_sst,
    }
    basis = "traditional"
    used = traditional
    if relative and all(key in relative for key in traditional):
        basis, used = "relative", relative
    regions = [
        RegionState(key, label, used[key], sst[key], traditional[key])
        for key, label in REGIONS
    ]
    flavour_index = used["nino12"] - used["nino4"]
    if flavour_index >= EP_FLAVOUR:
        flavour = "East Pacific (canonical) El Nino"
    elif flavour_index <= CP_FLAVOUR:
        flavour = "Central Pacific (Modoki) El Nino"
    else:
        flavour = "Mixed / basin-wide pattern"

    active = sum(1 for r in regions if r.active)
    # Mean anomaly across regions, scaled so +2.0 basin-wide reads as 100.
    mean_anomaly = sum(r.anomaly for r in regions) / len(regions)
    basin_score = clamp(50.0 * mean_anomaly)
    return ScaleDiagnostic(regions, flavour_index, flavour, active, basin_score, basis)


@dataclass
class CouplingDiagnostic:
    soi: float | None
    soi_label: str
    mei: float | None
    mei_label: str
    score: float
    coupled: bool


def diagnose_coupling(
    soi: list[MonthValue], mei: list[SeasonValue]
) -> CouplingDiagnostic:
    """Is the atmosphere responding to the ocean? Without it, an SST anomaly is
    just warm water -- the teleconnections need the Walker circulation to shift.

    A 3-month mean SOI is used because single months are noisy.
    """
    soi_value = None
    if soi:
        window = [m.value for m in soi[-3:]]
        soi_value = sum(window) / len(window)
    mei_value = mei[-1].value if mei else None

    # Negative SOI and positive MEI both indicate El Nino-like coupling.
    soi_component = clamp(-(soi_value or 0.0) / 2.0 * 100.0)
    mei_component = clamp((mei_value or 0.0) / 2.0 * 100.0)
    parts = [c for c, v in ((soi_component, soi_value), (mei_component, mei_value)) if v is not None]
    score = sum(parts) / len(parts) if parts else 0.0

    def band(value: float | None, negative_is_warm: bool) -> str:
        if value is None:
            return "unavailable"
        magnitude = -value if negative_is_warm else value
        if magnitude >= 2.0:
            return "strongly El Nino-like"
        if magnitude >= 1.0:
            return "clearly El Nino-like"
        if magnitude >= 0.5:
            return "weakly El Nino-like"
        if magnitude <= -0.5:
            return "La Nina-like"
        return "neutral"

    return CouplingDiagnostic(
        soi=soi_value,
        soi_label=band(soi_value, negative_is_warm=True),
        mei=mei_value,
        mei_label=band(mei_value, negative_is_warm=False),
        score=score,
        coupled=score >= 50.0,
    )


@dataclass
class MomentumDiagnostic:
    season_delta: float | None
    weekly_delta: float | None
    weeks_span: int
    direction: str
    score: float


def diagnose_momentum(
    series: list[SeasonValue],
    weeks: list[WeekObservation],
    relative_weeks: list | None = None,
) -> MomentumDiagnostic:
    """Rate of change: is the event still building, plateauing, or decaying?

    ``series`` is the official seasonal index. The weekly change is read off
    CPC's relative Nino-3.4 where there are enough weeks of it, for the same
    reason the seasonal one is read off RONI.
    """
    season_delta = series[-1].value - series[-2].value if len(series) >= 2 else None

    nino34 = [regions["nino34"] for _, regions in (relative_weeks or [])
              if "nino34" in regions]
    if len(nino34) < 5:
        nino34 = [week.nino34_anom for week in weeks]
    weekly_delta = None
    span = 0
    if len(nino34) >= 5:
        recent = nino34[-5:]
        weekly_delta = recent[-1] - recent[0]
        span = len(recent) - 1

    reference = season_delta if season_delta is not None else (weekly_delta or 0.0)
    if reference >= 0.25:
        direction = "intensifying rapidly"
    elif reference >= 0.10:
        direction = "intensifying"
    elif reference > -0.10:
        direction = "steady / plateauing"
    elif reference > -0.25:
        direction = "weakening"
    else:
        direction = "weakening rapidly"

    # +0.5 degC per season is about as fast as ENSO develops; treat that as full scale.
    score = clamp(50.0 + (reference / 0.5) * 50.0)
    return MomentumDiagnostic(season_delta, weekly_delta, span, direction, score)


@dataclass
class PowerIndex:
    value: float
    components: dict[str, float]
    weights: dict[str, float] = field(default_factory=lambda: dict(POWER_WEIGHTS))

    @property
    def band(self) -> str:
        if self.value >= 85:
            return "Extreme"
        if self.value >= 70:
            return "Very High"
        if self.value >= 55:
            return "High"
        if self.value >= 40:
            return "Moderate"
        if self.value >= 25:
            return "Low"
        return "Minimal"


def compute_power_index(
    index_value: float,
    scale: ScaleDiagnostic,
    coupling: CouplingDiagnostic,
    momentum: MomentumDiagnostic,
) -> PowerIndex:
    """Blend amplitude, coupling, spatial scale and momentum into one 0-100 number.

    Amplitude is the official index - RONI, or ONI where RONI is missing -
    scaled so that +2.5 degC, a level RONI has not reached since 1950, reads
    as 100. Averaging in the legacy ONI would put back the tropical-mean
    warming the official index exists to take out.
    """
    amplitude_value = index_value
    components = {
        "amplitude": clamp(amplitude_value / HISTORIC_RONI * 100.0),
        "coupling": coupling.score,
        "basin_scale": scale.basin_score,
        "momentum": momentum.score,
    }
    total = sum(components[k] * POWER_WEIGHTS[k] for k in POWER_WEIGHTS)
    return PowerIndex(round(total, 1), {k: round(v, 1) for k, v in components.items()})


@dataclass
class Assessment:
    """Everything the report and dashboard need, in one auditable object.

    The ``index_*`` fields are the official index - RONI, or ONI where RONI is
    missing - and are what every tier, episode, ranking and alert runs on.
    ``oni_*`` and ``roni_*`` are the two indices on their own terms, kept so
    the legacy ONI can still be quoted beside the official number.
    """

    index_name: str
    index_latest: SeasonValue
    index_tier: str
    index_ranking: Ranking
    index_series: list[SeasonValue]
    oni_latest: SeasonValue | None     # None when the legacy file did not arrive
    oni_tier: str | None
    roni_latest: SeasonValue | None
    roni_tier: str | None
    episode: Episode | None
    episode_status: str
    seasons_at_threshold: int
    ranking: Ranking  # ONI's, on its own record
    roni_ranking: Ranking | None
    latest_week: WeekObservation | None
    scale: ScaleDiagnostic | None
    coupling: CouplingDiagnostic
    momentum: MomentumDiagnostic
    power: PowerIndex
    analogs: list[Analog]
    historic_watch: bool
    headline: str
    status: str = ""  # CPC advisory status, when the discussion parsed


def _relative_week(week: WeekObservation | None, relative_weeks) -> dict | None:
    """The relative anomalies for the same week as the traditional reading.

    Matched on the date rather than taken from the end of the file, because
    the two files update separately and a relative week paired with a
    different traditional one would put two weeks into one table.
    """
    if week is None:
        return None
    for when, regions in reversed(relative_weeks or []):
        if when == week.week_ending:
            return regions
    return None


def assess(
    oni: list[SeasonValue],
    roni: list[SeasonValue],
    weeks: list[WeekObservation],
    soi: list[MonthValue],
    mei: list[SeasonValue],
    status: str = "",
    relative_weeks: list | None = None,
) -> Assessment:
    """Run the full diagnostic chain over the parsed observations.

    Everything is classified on RONI, CPC's official index since February
    2026. ONI takes its place only when RONI did not arrive, and the headline
    says which one it is either way.
    """
    index_name, series = ("RONI", roni) if roni else ("ONI", oni)
    latest = series[-1]
    tier = intensity_tier(latest.value)
    oni_latest = oni[-1] if oni else None
    roni_latest = roni[-1] if roni else None

    episode = current_episode(series, warm=True)
    seasons_at_threshold = episode.length if episode else 0
    if episode is None:
        episode_status = f"No El Nino conditions in the latest {index_name} season."
    elif episode.qualifies:
        episode_status = (
            f"Established El Nino episode: {episode.length} consecutive seasons "
            f"of {index_name} at or above +0.5 degC (NOAA requires "
            f"{MIN_SEASONS_FOR_EPISODE})."
        )
    else:
        episode_status = (
            f"El Nino conditions present for {episode.length} consecutive "
            f"season{'s' if episode.length != 1 else ''} of {index_name} "
            f"at or above +0.5 degC; "
            f"{MIN_SEASONS_FOR_EPISODE - episode.length} more needed before NOAA "
            "logs this as a formal episode."
        )

    ranking = rank_value(oni, oni_latest) if oni_latest else None
    roni_ranking = rank_value(roni, roni_latest) if roni_latest else None
    index_ranking = roni_ranking if index_name == "RONI" else ranking

    latest_week = weeks[-1] if weeks else None
    relative = _relative_week(latest_week, relative_weeks)
    scale = diagnose_scale(latest_week, relative) if latest_week else None
    coupling = diagnose_coupling(soi, mei)
    momentum = diagnose_momentum(series, weeks, relative_weeks)

    if scale is None:
        scale = ScaleDiagnostic([], 0.0, "unavailable", 0, clamp(50.0 * latest.value))

    power = compute_power_index(latest.value, scale, coupling, momentum)

    analogs = find_analogs(series, episode) if episode else []
    historic_watch = bool(displayed(latest.value) >= 1.0 and momentum.score >= 50)

    legacy = ""
    if index_name == "RONI" and oni_latest and oni_latest.label == latest.label:
        legacy = f"; legacy ONI {oni_latest.value:+.2f}"
    headline = (
        f"{tier} -- {index_name} {latest.value:+.2f} degC ({latest.label}{legacy}), "
        f"power index {power.value:.0f}/100 ({power.band}), {momentum.direction}."
    )

    return Assessment(
        index_name=index_name,
        index_latest=latest,
        index_tier=tier,
        index_ranking=index_ranking,
        index_series=list(series),
        oni_latest=oni_latest,
        oni_tier=intensity_tier(oni_latest.value) if oni_latest else None,
        roni_latest=roni_latest,
        roni_tier=intensity_tier(roni_latest.value) if roni_latest else None,
        episode=episode,
        episode_status=episode_status,
        seasons_at_threshold=seasons_at_threshold,
        ranking=ranking,
        roni_ranking=roni_ranking,
        latest_week=latest_week,
        scale=scale,
        coupling=coupling,
        momentum=momentum,
        power=power,
        analogs=analogs,
        historic_watch=historic_watch,
        headline=headline,
        status=status,
    )
