"""ENSO state classification, event detection, scale/power diagnostics, analogs.

Conventions follow NOAA CPC:

* An El Nino *episode* requires the ONI to sit at or above +0.5 degC for five
  consecutive overlapping three-month seasons. Fewer than five consecutive
  seasons means El Nino *conditions* are present but the episode is not yet
  established in the historical record.
* Intensity tiers are taken from the peak ONI of the episode:
  weak 0.5-0.9, moderate 1.0-1.4, strong 1.5-1.9, very strong >= 2.0.

The composite "power index" at the bottom of this module is a derived
diagnostic of this tracker, not a NOAA product. Its inputs and weights are
spelled out so the number can be audited or rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .parsers import MonthValue, SeasonValue, WeekObservation

EVENT_THRESHOLD = 0.5
MIN_SEASONS_FOR_EPISODE = 5
HISTORIC_RONI = 2.5  # CPC's own bar for an event beyond anything since 1950

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


def intensity_tier(oni: float) -> str:
    """NOAA intensity label for an ONI value; La Nina mirrored for completeness."""
    if oni <= -0.5:
        for bound, label in INTENSITY_TIERS:
            if -oni >= bound:
                return f"{label} La Nina"
        return "Weak La Nina"
    for bound, label in INTENSITY_TIERS:
        if oni >= bound:
            return f"{label} El Nino"
    return "Neutral"


@dataclass
class Episode:
    """A run of consecutive seasons on one side of the +/-0.5 threshold."""

    seasons: list[SeasonValue]
    warm: bool = True

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
        breaches = item.value >= EVENT_THRESHOLD if warm else item.value <= -EVENT_THRESHOLD
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
    seasons_to_peak: int
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
        head = episode.values[:phase]
        errors = [(a - b) ** 2 for a, b in zip(head, current.values)]
        rmse = (sum(errors) / len(errors)) ** 0.5
        peak = episode.peak
        out.append(
            Analog(
                episode=episode,
                rmse=rmse,
                peak_value=peak.value,
                peak_label=peak.label,
                seasons_to_peak=episode.values.index(peak.value),
                tier=episode.tier,
            )
        )
    out.sort(key=lambda a: a.rmse)
    return out[:limit]


@dataclass
class RegionState:
    key: str
    label: str
    anomaly: float
    sst: float

    @property
    def active(self) -> bool:
        return self.anomaly >= EVENT_THRESHOLD


@dataclass
class ScaleDiagnostic:
    regions: list[RegionState]
    flavour_index: float
    flavour: str
    active_regions: int
    basin_score: float


def diagnose_scale(week: WeekObservation) -> ScaleDiagnostic:
    """Spatial extent and flavour of the event from the four Nino regions.

    flavour_index = Nino-1+2 anomaly minus Nino-4 anomaly. Strongly positive
    means the warmth is concentrated in the eastern Pacific (canonical / EP
    event, as in 1982-83 and 1997-98); negative means a central-Pacific
    "Modoki" event. This is a simple proxy, not the formal E/C EOF indices.
    """
    regions = [
        RegionState("nino12", "Nino-1+2 (coastal Peru/Ecuador)", week.nino12_anom, week.nino12_sst),
        RegionState("nino3", "Nino-3 (eastern Pacific)", week.nino3_anom, week.nino3_sst),
        RegionState("nino34", "Nino-3.4 (east-central, index region)", week.nino34_anom, week.nino34_sst),
        RegionState("nino4", "Nino-4 (central/western Pacific)", week.nino4_anom, week.nino4_sst),
    ]
    flavour_index = week.nino12_anom - week.nino4_anom
    if flavour_index >= 1.0:
        flavour = "East Pacific (canonical) El Nino"
    elif flavour_index <= -1.0:
        flavour = "Central Pacific (Modoki) El Nino"
    else:
        flavour = "Mixed / basin-wide pattern"

    active = sum(1 for r in regions if r.active)
    # Mean anomaly across regions, scaled so +2.0 basin-wide reads as 100.
    mean_anomaly = sum(r.anomaly for r in regions) / len(regions)
    basin_score = clamp(50.0 * mean_anomaly)
    return ScaleDiagnostic(regions, flavour_index, flavour, active, basin_score)


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
    oni: list[SeasonValue], weeks: list[WeekObservation]
) -> MomentumDiagnostic:
    """Rate of change: is the event still building, plateauing, or decaying?"""
    season_delta = oni[-1].value - oni[-2].value if len(oni) >= 2 else None

    weekly_delta = None
    span = 0
    if len(weeks) >= 5:
        recent = weeks[-5:]
        weekly_delta = recent[-1].nino34_anom - recent[0].nino34_anom
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
    oni_value: float,
    roni_value: float | None,
    scale: ScaleDiagnostic,
    coupling: CouplingDiagnostic,
    momentum: MomentumDiagnostic,
) -> PowerIndex:
    """Blend amplitude, coupling, spatial scale and momentum into one 0-100 number.

    Amplitude uses the mean of ONI and RONI where RONI is available, scaled so
    that +2.5 degC -- CPC's threshold for an event beyond anything since 1950 --
    reads as 100.
    """
    amplitude_value = oni_value if roni_value is None else (oni_value + roni_value) / 2.0
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
    """Everything the report and dashboard need, in one auditable object."""

    oni_latest: SeasonValue
    oni_tier: str
    roni_latest: SeasonValue | None
    roni_tier: str | None
    episode: Episode | None
    episode_status: str
    seasons_at_threshold: int
    ranking: Ranking
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


def assess(
    oni: list[SeasonValue],
    roni: list[SeasonValue],
    weeks: list[WeekObservation],
    soi: list[MonthValue],
    mei: list[SeasonValue],
    status: str = "",
) -> Assessment:
    """Run the full diagnostic chain over the parsed observations."""
    latest = oni[-1]
    tier = intensity_tier(latest.value)
    roni_latest = roni[-1] if roni else None

    episode = current_episode(oni, warm=True)
    seasons_at_threshold = episode.length if episode else 0
    if episode is None:
        episode_status = "No El Nino conditions in the latest season."
    elif episode.qualifies:
        episode_status = (
            f"Established El Nino episode: {episode.length} consecutive seasons "
            f"at or above +0.5 degC (NOAA requires {MIN_SEASONS_FOR_EPISODE})."
        )
    else:
        episode_status = (
            f"El Nino conditions present for {episode.length} consecutive season(s); "
            f"{MIN_SEASONS_FOR_EPISODE - episode.length} more needed before NOAA logs "
            "this as a formal episode."
        )

    ranking = rank_value(oni, latest)
    roni_ranking = rank_value(roni, roni_latest) if roni_latest else None

    latest_week = weeks[-1] if weeks else None
    scale = diagnose_scale(latest_week) if latest_week else None
    coupling = diagnose_coupling(soi, mei)
    momentum = diagnose_momentum(oni, weeks)

    if scale is None:
        scale = ScaleDiagnostic([], 0.0, "unavailable", 0, clamp(50.0 * latest.value))

    power = compute_power_index(
        latest.value, roni_latest.value if roni_latest else None, scale, coupling, momentum
    )

    analogs = find_analogs(oni, episode) if episode else []
    historic_watch = bool(roni_latest and roni_latest.value >= 1.0 and momentum.score >= 50)

    headline = (
        f"{tier} -- ONI {latest.value:+.2f} degC ({latest.label}), "
        f"power index {power.value:.0f}/100 ({power.band}), {momentum.direction}."
    )

    return Assessment(
        oni_latest=latest,
        oni_tier=tier,
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
