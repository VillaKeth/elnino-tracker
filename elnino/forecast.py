"""Forecast: three independent methods and an ensemble of them.

This is where the tracker stops describing and starts projecting. Nothing here
is a dynamical model - there is no GCM in a standard-library Python script -
but three statistical methods with genuinely different failure modes, run
against each other with honest uncertainty, are worth more than one method
quoted with false confidence.

    damped persistence   the benchmark every operational forecast must beat.
                         Regresses each target season on today's anomaly,
                         fitted separately FOR THAT TARGET SEASON, which is
                         what makes the spring predictability barrier appear
                         on its own rather than being asserted.

    recharge oscillator  a seasonal linear inverse model fitted to the joint
                         evolution of Nino-3.4 and warm water volume. It knows
                         that stored heat becomes surface warmth and that the
                         growth rate is strongly seasonal, so it can forecast a
                         turning point instead of only a decay.

    analog ensemble      past years whose index ran most like this one over
                         the same calendar seasons, each continued forward
                         through the real record from the same season. ENSO
                         is phase-locked to the calendar - events grow through
                         boreal summer and autumn, peak near December and decay
                         through spring - so an analog is only an analog at the
                         same time of year. Its spread is a direct estimate of
                         how differently things can go from here.

The ensemble mean is the headline; the disagreement between methods is
reported next to it, because when they diverge that is the honest signal.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .parsers import ONI_SEASONS, MonthValue, SeasonValue

MIN_FIT_SAMPLE = 20
DEFAULT_LEADS = 9

# Fallback weights, used only when verification cannot run. With a record to
# verify against, every method's weight is the inverse of its cross-validated
# mean squared error.
DEFAULT_WEIGHTS = {"analog": 0.45, "recharge": 0.35, "persistence": 0.20}

# The order the methods are listed in wherever they are shown side by side.
METHODS_SHOWN = ("analog", "recharge", "persistence")


def weights_text(weights: dict[str, float]) -> str:
    """"analog 35%, recharge 37%, persistence 28%" - the order never changes."""
    return ", ".join(f"{name} {weights[name]:.0%}"
                     for name in METHODS_SHOWN if name in weights)

# Thresholds worth a probability statement, in degC of the official index
# (RONI, or ONI where RONI is missing), judged on the value CPC prints.
THRESHOLDS = (1.0, 1.5, 2.0, 2.5)
# CPC prints one decimal, so a season "at or above +2.0" is one of +1.95 or more.
PRINTED_HALF_STEP = 0.05

# How far the warm water volume may trail the SST at the forecast's start. It
# changes slowly enough that a month or two of lag costs less than throwing
# away the newest SST; beyond that the start state is too stale to integrate.
MAX_HEAT_LAG = 2

# Analog quality gate. Past events are ranked by RMSE against the current
# event's trajectory so far; a member is kept only if it is close in absolute
# terms AND not much worse than the best match. Without this, widening the
# member count to get a usable spread quietly admits events that look nothing
# like the current one and drags the mean toward climatology.
ANALOG_RMSE_CEILING = 0.45
ANALOG_RMSE_RATIO = 1.6

# Seasons an analog is matched on, ending with the latest, and how many of the
# closest years go forward to the quality gate. Four seasons scored as well as
# six in the cross-validated hindcast and admit one more year of record.
ANALOG_WINDOW = 4
ANALOG_KEEP = 10

# The largest ONI ever observed is about +2.6 degC. A linear model integrated
# forward from a record initial state will sail past that, so the SST equation
# carries a cubic damping term - the standard nonlinear extension of the
# recharge oscillator - and the integration is abandoned if it still diverges.
ROM_DIVERGENCE = 6.0


@dataclass(frozen=True)
class Projection:
    lead: int  # months ahead of the latest observed season
    season: str
    year: int
    mean: float
    low: float  # 10th percentile
    high: float  # 90th percentile
    sigma: float
    methods: dict[str, float] = field(default_factory=dict)
    members: list[float] = field(default_factory=list)

    @property
    def label(self) -> str:
        return f"{self.season} {self.year}"

    @property
    def spread(self) -> float:
        """How far apart the methods are - the honest uncertainty signal."""
        if len(self.methods) < 2:
            return 0.0
        return max(self.methods.values()) - min(self.methods.values())

    def probability_above(self, threshold: float) -> float:
        """P(index >= threshold), from the ensemble mean and spread."""
        if self.sigma <= 0.0:
            return 1.0 if self.mean >= threshold else 0.0
        z = (threshold - self.mean) / self.sigma
        return 1.0 - _normal_cdf(z)


@dataclass
class Forecast:
    projections: list[Projection]
    peak: Projection | None
    peak_probability: dict[float, float]
    method_notes: list[str]
    skill_source: str
    analog_members: dict[str, list[float]] = field(default_factory=dict)
    analog_weights: dict[str, float] = field(default_factory=dict)
    weights: dict[str, float] = field(default_factory=dict)  # method -> share
    rom_fitted: bool = False
    notes: list[str] = field(default_factory=list)
    index_name: str = "RONI"

    def at(self, lead: int) -> Projection | None:
        for projection in self.projections:
            if projection.lead == lead:
                return projection
        return None


def _normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def _mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _stdev(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    average = _mean(values)
    return math.sqrt(sum((v - average) ** 2 for v in values) / (len(values) - 1))


def _percentile(values: list[float], fraction: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = fraction * (len(ordered) - 1)
    lower = int(math.floor(position))
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _season_step(season: str, year: int, steps: int) -> tuple[str, int]:
    """Advance an ONI season by whole months (ONI seasons overlap monthly)."""
    index = ONI_SEASONS.index(season) + steps
    return ONI_SEASONS[index % 12], year + index // 12


def _month_add(year: int, month: int, steps: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + steps
    return index // 12, index % 12 + 1


def season_months(season: str, year: int) -> list[tuple[int, int]]:
    """The (year, month) pairs an overlapping three-month season averages.

    CPC dates a season by its centre month, so DJF 2027 runs from December
    2026 to February 2027 and NDJ 2026 ends in January 2027.
    """
    centre = ONI_SEASONS.index(season) + 1
    return [_month_add(year, centre, offset) for offset in (-1, 0, 1)]


def _held_out(exclude_year) -> set[int]:
    """``exclude_year`` as a set: one year, several, or none."""
    if exclude_year is None:
        return set()
    if isinstance(exclude_year, int):
        return {exclude_year}
    return set(exclude_year)


def _solve3(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting for the 3-predictor fit."""
    size = len(rhs)
    augmented = [row[:] + [rhs[i]] for i, row in enumerate(matrix)]
    for column in range(size):
        pivot = max(range(column, size), key=lambda r: abs(augmented[r][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            return [0.0] * size
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        for row in range(column + 1, size):
            factor = augmented[row][column] / augmented[column][column]
            for k in range(column, size + 1):
                augmented[row][k] -= factor * augmented[column][k]
    out = [0.0] * size
    for row in reversed(range(size)):
        total = augmented[row][size] - sum(
            augmented[row][k] * out[k] for k in range(row + 1, size)
        )
        out[row] = total / augmented[row][row]
    return out


def _solve2(
    a11: float, a12: float, a22: float, b1: float, b2: float
) -> tuple[float, float]:
    """Solve a symmetric 2x2 normal-equation system. Zero if singular."""
    determinant = a11 * a22 - a12 * a12
    if abs(determinant) < 1e-12:
        return 0.0, 0.0
    return (b1 * a22 - b2 * a12) / determinant, (a11 * b2 - a12 * b1) / determinant


# ---------------------------------------------------------------------------
# 1. Damped persistence
# ---------------------------------------------------------------------------


def persistence_fit(
    series: list[SeasonValue], lead: int, exclude_year=None
) -> dict[str, tuple[float, float, float]]:
    """Least-squares persistence at one lead, fitted per target season.

    Returns target season -> (slope, start mean, target mean). The slope is the
    lag correlation times the ratio of the target season's spread to the start
    season's. The correlation alone is the right multiplier only when both
    seasons vary equally, and ENSO's seasons do not: the winter seasons swing
    far wider than the summer ones, so a correlation applied to a summer
    anomaly forecasts the winter too low - from RONI's JJA 2026 +1.36 the
    correlation says NDJ +1.21, the regression +2.08. Fitting per target
    season is still what makes the spring barrier fall out of the data: the
    fit into MAM and AMJ collapses while the fit into NDJ stays strong.

    ``exclude_year`` (a year or a collection of them) drops every pair that
    starts or ends in a held-out year, so a hindcast never scores a fit on the
    seasons it is verified against.
    """
    held = _held_out(exclude_year)
    index = {(v.season, v.year): v.value for v in series}
    buckets: dict[str, list[tuple[float, float]]] = {}
    for value in series:
        if value.year in held:
            continue
        target_season, target_year = _season_step(value.season, value.year, lead)
        if target_year in held:
            continue
        target = index.get((target_season, target_year))
        if target is None:
            continue
        buckets.setdefault(target_season, []).append((value.value, target))

    out: dict[str, tuple[float, float, float]] = {}
    for season, pairs in buckets.items():
        if len(pairs) < MIN_FIT_SAMPLE:
            continue
        start_mean = _mean([a for a, _ in pairs])
        target_mean = _mean([b for _, b in pairs])
        spread = sum((a - start_mean) ** 2 for a, _ in pairs)
        covariance = sum((a - start_mean) * (b - target_mean) for a, b in pairs)
        out[season] = (covariance / spread if spread else 0.0, start_mean, target_mean)
    return out


def persist(fit: tuple[float, float, float], value: float) -> float:
    """Carry one starting anomaly forward through a persistence fit.

    A negative slope is held at zero, which forecasts the target season's mean:
    damped persistence is a benchmark, and a benchmark that predicts a sign
    flip is a model.
    """
    slope, start_mean, target_mean = fit
    return target_mean + max(slope, 0.0) * (value - start_mean)


def damped_persistence(series: list[SeasonValue], leads: int) -> dict[int, float]:
    """Today's anomaly carried forward by the per-target-season regression."""
    if not series:
        return {}
    latest = series[-1]
    out: dict[int, float] = {}
    for lead in range(1, leads + 1):
        target_season, _ = _season_step(latest.season, latest.year, lead)
        fit = persistence_fit(series, lead).get(target_season)
        if fit is None:
            continue
        out[lead] = persist(fit, latest.value)
    return out


# ---------------------------------------------------------------------------
# 2. Seasonal recharge oscillator (linear inverse model)
# ---------------------------------------------------------------------------


@dataclass
class RechargeModel:
    """dT/dt = a*T + b*h - e*T^3 ;  dh/dt = c*T + d*h, all fitted per month.

    The cubic term is what keeps the model honest at large amplitude. ENSO's
    growth is not linear all the way up: the thermocline feedback saturates as
    the east Pacific warms and the thermocline flattens, and without a damping
    term a model initialised from a record warm water volume will forecast an
    SST anomaly that has never been observed.
    """

    growth: dict[int, tuple[float, float, float]]  # month -> (a, b, e)
    heat: dict[int, tuple[float, float]]  # month -> (c, d)
    pooled_growth: tuple[float, float, float]
    pooled_heat: tuple[float, float]
    samples: int
    seasonal_months: int = 0

    def step(self, month: int, sst: float, heat: float) -> tuple[float, float]:
        a, b, e = self.growth.get(month, self.pooled_growth)
        c, d = self.heat.get(month, self.pooled_heat)
        return (
            sst + a * sst + b * heat - e * sst ** 3,
            heat + c * sst + d * heat,
        )


def rom_rows(
    sst: list[MonthValue], heat: list[MonthValue]
) -> list[tuple[int, int, float, float, float, float]]:
    """(year, month, T, h, dT, dh) for every month with a successor.

    Built once and reused: cross-validation refits from this same list with one
    year removed, which is what makes leave-one-year-out cheap enough to run on
    every update.
    """
    sst_index = {(v.year, v.month): v.value for v in sst}
    heat_index = {(v.year, v.month): v.value for v in heat}
    rows = []
    for key in sorted(set(sst_index) & set(heat_index)):
        year, month = key
        nxt = (year, month + 1) if month < 12 else (year + 1, 1)
        if nxt not in sst_index or nxt not in heat_index:
            continue
        rows.append(
            (
                year,
                month,
                sst_index[key],
                heat_index[key],
                sst_index[nxt] - sst_index[key],
                heat_index[nxt] - heat_index[key],
            )
        )
    return rows


def _fit_growth(sample) -> tuple[float, float, float]:
    """Regress dT on (T, h, T^3)."""
    def dot(i: int, j: int) -> float:
        return sum(_term(row, i) * _term(row, j) for row in sample)

    matrix = [[dot(i, j) for j in range(3)] for i in range(3)]
    rhs = [sum(_term(row, i) * row[4] for row in sample) for i in range(3)]
    a, b, e = _solve3(matrix, rhs)
    return a, b, -e  # stored as a damping coefficient, so it subtracts


def _term(row, index: int) -> float:
    return (row[2], row[3], row[2] ** 3)[index]


def _fit_heat(sample) -> tuple[float, float]:
    """Regress dh on (T, h)."""
    a11 = sum(r[2] * r[2] for r in sample)
    a12 = sum(r[2] * r[3] for r in sample)
    a22 = sum(r[3] * r[3] for r in sample)
    b1 = sum(r[2] * r[5] for r in sample)
    b2 = sum(r[3] * r[5] for r in sample)
    return _solve2(a11, a12, a22, b1, b2)


def fit_recharge(
    sst: list[MonthValue],
    heat: list[MonthValue],
    exclude_year: int | None = None,
    rows: list | None = None,
) -> RechargeModel | None:
    """Least-squares fit of the two-variable model, per calendar month.

    Fitting a growth rate per calendar month is what lets the model reproduce
    ENSO's seasonal phase locking - events grow through boreal autumn and decay
    through spring - without that behaviour being hard-coded. ``exclude_year``
    holds one year (or several) out so verification never scores the model on
    its own training data.
    """
    rows = rom_rows(sst, heat) if rows is None else rows
    held = _held_out(exclude_year)
    sample = [r for r in rows if r[0] not in held]
    if len(sample) < MIN_FIT_SAMPLE * 2:
        return None

    pooled_growth = _fit_growth(sample)
    pooled_heat = _fit_heat(sample)

    growth: dict[int, tuple[float, float, float]] = {}
    heat_coeffs: dict[int, tuple[float, float]] = {}
    for month in range(1, 13):
        monthly = [r for r in sample if r[1] == month]
        if len(monthly) >= MIN_FIT_SAMPLE:
            growth[month] = _fit_growth(monthly)
            heat_coeffs[month] = _fit_heat(monthly)

    return RechargeModel(
        growth, heat_coeffs, pooled_growth, pooled_heat, len(sample), len(growth)
    )


def recharge_projection(
    model: RechargeModel,
    sst_now: float,
    heat_now: float,
    start_month: int,
    leads: int,
) -> dict[int, float]:
    """Integrate the fitted model forward one month at a time."""
    out: dict[int, float] = {}
    sst, heat, month = sst_now, heat_now, start_month
    for lead in range(1, leads + 1):
        sst, heat = model.step(month, sst, heat)
        month = month % 12 + 1
        if not math.isfinite(sst) or abs(sst) > ROM_DIVERGENCE:
            break  # a diverged integration is not a forecast
        out[lead] = sst
    return out


def _heat_at(heat: dict[tuple[int, int], float], start: tuple[int, int]) -> float | None:
    """Heat content at the start month, or the latest up to MAX_HEAT_LAG before."""
    for back in range(MAX_HEAT_LAG + 1):
        value = heat.get(_month_add(start[0], start[1], -back))
        if value is not None:
            return value
    return None


def initial_state(
    sst: list[MonthValue], heat: list[MonthValue]
) -> tuple[tuple[int, int], float, float] | None:
    """Where the recharge model starts: the last month of SST that is in.

    The heat content is that month's, or the latest before it when the warm
    water volume runs behind. Never a later one: a start state borrowed from
    the future is not a forecast.
    """
    if not sst:
        return None
    last = max(sst, key=lambda v: (v.year, v.month))
    start = (last.year, last.month)
    heat_now = _heat_at({(v.year, v.month): v.value for v in heat}, start)
    if heat_now is None:
        return None
    return start, last.value, heat_now


def recharge_seasons(
    model: RechargeModel,
    sst: dict[tuple[int, int], float],
    heat: dict[tuple[int, int], float],
    start: tuple[int, int],
    latest: tuple[str, int],
    leads: int,
) -> dict[int, float]:
    """The recharge model's forecast of each season ahead, as the index averages it.

    The model steps a month at a time from ``start``, the last month observed,
    and the index is a three-month mean dated by its centre month. So each
    target season is the mean of its three months: observed where the month is
    already in - a forecast made at the end of August still has July and
    August in hand for JAS - and projected where it is not. ``latest`` is the
    last observed season, from which the leads count.

    Reading one projected month as the season, as this used to, dated every
    lead a month late and threw away the two measured months of the first one.
    """
    sst_now = sst.get(start)
    heat_now = _heat_at(heat, start)
    if sst_now is None or heat_now is None:
        return {}
    season, year = latest
    last = season_months(*_season_step(season, year, leads))[-1]
    steps = (last[0] - start[0]) * 12 + (last[1] - start[1])
    track = recharge_projection(model, sst_now, heat_now, start[1], steps) if steps > 0 else {}
    projected = {_month_add(start[0], start[1], step): value for step, value in track.items()}

    out: dict[int, float] = {}
    for lead in range(1, leads + 1):
        months = season_months(*_season_step(season, year, lead))
        values = [sst.get(key) if key <= start else projected.get(key) for key in months]
        if any(value is None for value in values):
            continue
        out[lead] = sum(values) / 3.0
    return out


# ---------------------------------------------------------------------------
# 3. Analog ensemble
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AnalogMember:
    season: str
    year: int
    name: str
    rmse: float


def _year_name(season: str, year: int) -> str:
    """The ENSO year a season belongs to: JJA 1997 and DJF 1998 are 1997-98."""
    first = year - 1 if season in ("DJF", "JFM", "FMA", "MAM") else year
    return f"{first}-{(first + 1) % 100:02d}"


def calendar_analogs(series: list[SeasonValue], at: int | None = None,
                     window: int = ANALOG_WINDOW,
                     keep: int = ANALOG_KEEP) -> list[AnalogMember]:
    """Past years whose index ran most like this one over the same seasons.

    ``at`` is the position of the forecast's start in ``series`` - the last
    season for the live forecast, an earlier one in the hindcast. Each other
    year is scored by RMSE over the ``window`` seasons ending with the start's
    calendar season, and only a year whose record continues past that season
    can be a member. The start's own year and its neighbours are held out,
    the year before as well as the two after: the year before's continuation
    runs through the start's own record, and in the hindcast the two after
    hold the truth being forecast. The live forecast and its verification
    hold out the same years, so the skill quoted is the skill of this rule.
    """
    at = len(series) - 1 if at is None else at
    if at + 1 < window:
        return []
    start = series[at]
    now = [series[at - k].value for k in range(window - 1, -1, -1)]
    position = {(v.season, v.year): i for i, v in enumerate(series)}
    held = {start.year - 1, start.year, start.year + 1, start.year + 2}
    after = _season_step(start.season, start.year, 1)[0]
    scored = []
    for year in sorted({v.year for v in series} - held):
        where = position.get((start.season, year))
        if where is None or where + 1 < window:
            continue
        if (after, _season_step(start.season, year, 1)[1]) not in position:
            continue
        past = [series[where - k].value for k in range(window - 1, -1, -1)]
        rmse = math.sqrt(sum((a - b) ** 2 for a, b in zip(now, past)) / window)
        scored.append((rmse, year))
    scored.sort()
    return [AnalogMember(start.season, year, _year_name(start.season, year), rmse)
            for rmse, year in scored[:keep]]


def filter_analogs(members: list[AnalogMember]) -> list[AnalogMember]:
    """Drop past events that are not actually similar to this one."""
    if not members:
        return []
    best = min(member.rmse for member in members)
    ceiling = max(ANALOG_RMSE_CEILING, best * ANALOG_RMSE_RATIO)
    return [member for member in members if member.rmse <= ceiling]


def analog_projection(
    series: list[SeasonValue],
    members: list[AnalogMember],
    stage: int,
    leads: int,
    current_value: float | None = None,
) -> tuple[dict[int, list[tuple[float, float]]], dict[str, list[float]], dict[str, float]]:
    """Continue each analog forward from the equivalent point of its own year.

    Each member is read forward from its own season plus ``stage`` months -
    zero for calendar analogs, whose season is already the start's - through
    the real record, so the continuation includes what that year actually did
    rather than a fitted curve.

    Two corrections make the result usable rather than merely interesting:

      * **Similarity weighting.** Members are weighted by 1/(RMSE + 0.1), so the
        closest analog dominates instead of being averaged in with marginal ones.

      * **Offset correction.** If the current event is running warmer than its
        analogs were at the same point - which is the case whenever an event is
        outpacing history - a raw continuation under-forecasts by exactly that
        gap. Each member is therefore shifted by the difference between today's
        value and that member's value at the start. The shift is held constant
        rather than tapered: it is a simple, auditable assumption, and the
        hindcast scores it as it stands.

    The per-member tracks carry the same shift, so what a chart draws from
    today's value is what the band was built from. They used to be the raw
    record, hung from today's value: a member that stood 0.8 below this
    event at the start fell 0.8 further on the page than in the band.

    Returns (per-lead (value, weight) pairs, per-member tracks, weights).
    """
    index = {(v.season, v.year): v.value for v in series}
    by_lead: dict[int, list[tuple[float, float]]] = {lead: [] for lead in range(1, leads + 1)}
    by_name: dict[str, list[float]] = {}
    weights: dict[str, float] = {}

    for member in members:
        weight = 1.0 / (member.rmse + 0.1)
        at_stage = index.get(_season_step(member.season, member.year, stage))
        offset = 0.0
        if current_value is not None and at_stage is not None:
            offset = current_value - at_stage

        track: list[float] = []
        for lead in range(1, leads + 1):
            target = _season_step(member.season, member.year, stage + lead)
            value = index.get(target)
            if value is None:
                break
            by_lead[lead].append((value + offset, weight))
            track.append(value + offset)
        if track:
            by_name[member.name] = track
            weights[member.name] = weight
    return by_lead, by_name, weights


# ---------------------------------------------------------------------------
# Ensemble
# ---------------------------------------------------------------------------


def peak_probability(
    projections: list[Projection], thresholds: tuple[float, ...] = THRESHOLDS
) -> dict[float, float]:
    """P(the event's peak prints at or above each threshold).

    Taken from the season likeliest to clear each bar, not only from the
    season with the highest mean: a later season with a slightly lower mean
    and a wider band can be the likelier route past a high threshold, and
    reading the peak season alone called a +2.5 degC event all but impossible
    whenever the peak season happened to be the sharpest one. The best single
    season is a floor on the chance that some season clears the bar.

    CPC tiers on the printed one-decimal value, so "at or above +2.0" means a
    value of +1.95 or more.
    """
    if not projections:
        return {}
    return {
        threshold: max(p.probability_above(threshold - PRINTED_HALF_STEP)
                       for p in projections)
        for threshold in thresholds
    }


def build(
    series: list[SeasonValue],
    nino34_monthly: list[MonthValue],
    wwv: list[MonthValue],
    analog_members: list[AnalogMember],
    stage: int = 0,
    leads: int = DEFAULT_LEADS,
    skill: dict[int, float] | None = None,
    weights: dict[str, float] | None = None,
    skill_source: str = "default weights (no verification run)",
    index_name: str = "RONI",
) -> Forecast:
    """Run all three methods and combine them.

    ``series`` is the official seasonal index and ``nino34_monthly`` the
    monthly series it is the three-month mean of, so every method forecasts
    the number the classification runs on. ``skill`` maps lead time to
    hindcast RMSE; when present it sets the width of the uncertainty band,
    which is the only honest way to size it.
    """
    if not series:
        return Forecast([], None, {}, [], skill_source,
                        notes=[f"No {index_name} data."], index_name=index_name)

    weights = dict(weights or DEFAULT_WEIGHTS)
    latest = series[-1]
    notes: list[str] = []
    method_notes: list[str] = []

    persistence = damped_persistence(series, leads)
    if persistence:
        method_notes.append(
            "Damped persistence regresses each target season on today's value, "
            "fitted separately for each target season, so the spring barrier and "
            "the autumn growth are both in the numbers rather than asserted."
        )

    recharge: dict[int, float] = {}
    model = fit_recharge(nino34_monthly, wwv) if nino34_monthly and wwv else None
    if model:
        state = initial_state(nino34_monthly, wwv)
        if state is None:
            notes.append(
                f"The warm water volume is more than {MAX_HEAT_LAG} months behind "
                "the SST, so the recharge model has no start state and is left out."
            )
        else:
            recharge = recharge_seasons(
                model,
                {(v.year, v.month): v.value for v in nino34_monthly},
                {(v.year, v.month): v.value for v in wwv},
                state[0],
                (latest.season, latest.year),
                leads,
            )
        method_notes.append(
            f"Recharge oscillator fitted to {model.samples} monthly transitions of "
            f"Nino-3.4 against warm water volume, with a separate growth rate and "
            f"nonlinear damping term for each of {model.seasonal_months} calendar months."
        )
        if state is not None and not recharge:
            notes.append(
                "The recharge model's integration diverged and was discarded; the "
                "ensemble is running on the remaining methods."
            )
        if len(model.growth) < 12:
            notes.append(
                "Some calendar months had too few samples for their own growth "
                "rate and fall back to the pooled fit."
            )
    elif nino34_monthly and wwv:
        notes.append("Not enough overlapping SST and WWV data to fit the recharge model.")

    kept = filter_analogs(analog_members)
    dropped = len(analog_members) - len(kept)
    analog_by_lead, analog_tracks, analog_weights = analog_projection(
        series, kept, stage, leads, current_value=latest.value
    )
    if analog_tracks:
        best = min(kept, key=lambda m: m.rmse)
        method_notes.append(
            f"Analog ensemble: {len(analog_tracks)} past years matched on the "
            f"same {ANALOG_WINDOW} calendar seasons ending {latest.season}, "
            f"weighted by closeness of fit (best is {best.name}, RMSE "
            f"{best.rmse:.2f}) and offset-corrected to today's value."
        )
        if dropped:
            notes.append(
                f"{dropped} candidate analog{'s were' if dropped != 1 else ' was'} "
                "dropped for being too "
                "dissimilar to the current trajectory."
            )
        at_stage_index = {(v.season, v.year): v.value for v in series}
        gaps = [
            latest.value - at_stage_index[_season_step(m.season, m.year, stage)]
            for m in kept
            if _season_step(m.season, m.year, stage) in at_stage_index
        ]
        if gaps and min(gaps) > 0.1:
            notes.append(
                f"This event is running warmer than every analog at the same point of its year, "
                f"by {min(gaps):+.2f} to {max(gaps):+.2f} degC. The analog members "
                "are shifted by that gap; without the shift they would understate "
                "the projection."
            )
    else:
        notes.append("No usable analogs; the ensemble is running without them.")

    projections: list[Projection] = []
    for lead in range(1, leads + 1):
        methods: dict[str, float] = {}
        if lead in persistence:
            methods["persistence"] = persistence[lead]
        if lead in recharge:
            methods["recharge"] = recharge[lead]
        weighted = analog_by_lead.get(lead, [])
        members = [value for value, _ in weighted]
        if weighted:
            total = sum(weight for _, weight in weighted)
            methods["analog"] = sum(v * w for v, w in weighted) / total
        if not methods:
            continue

        active = sum(weights.get(name, 0.0) for name in methods)
        if active <= 0.0:
            mean = _mean(list(methods.values()))
        else:
            mean = sum(weights.get(n, 0.0) * v for n, v in methods.items()) / active

        # Uncertainty: measured hindcast error where available, otherwise the
        # analog spread, otherwise a lead-scaled default. Method disagreement
        # is folded in so that divergence widens the band.
        if skill and lead in skill:
            sigma = skill[lead]
        elif len(members) >= 3:
            sigma = _stdev(members)
        else:
            sigma = 0.25 + 0.06 * lead
        sigma = math.hypot(sigma, 0.5 * (max(methods.values()) - min(methods.values())))

        season, year = _season_step(latest.season, latest.year, lead)
        low = _percentile(members, 0.10) if len(members) >= 5 else mean - 1.2816 * sigma
        high = _percentile(members, 0.90) if len(members) >= 5 else mean + 1.2816 * sigma
        # Never let the analog envelope be narrower than the measured error.
        low = min(low, mean - 1.2816 * sigma)
        high = max(high, mean + 1.2816 * sigma)

        projections.append(
            Projection(
                lead=lead,
                season=season,
                year=year,
                mean=mean,
                low=low,
                high=high,
                sigma=sigma,
                methods=methods,
                members=members,
            )
        )

    peak = max(projections, key=lambda p: p.mean) if projections else None

    return Forecast(
        projections=projections,
        peak=peak,
        peak_probability=peak_probability(projections),
        method_notes=method_notes,
        skill_source=skill_source,
        analog_members=analog_tracks,
        analog_weights=analog_weights,
        weights=weights,
        rom_fitted=model is not None,
        notes=notes,
        index_name=index_name,
    )
