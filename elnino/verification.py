"""Hindcast verification: how much is the forecast actually worth?

A forecast without a measured error bar is an opinion. This module re-runs the
forecast methods over the historical record and scores them, so that every
projection the tracker prints can carry an uncertainty that was measured rather
than assumed.

Two things make this honest rather than decorative:

  * Cross-validation by year. The recharge model's coefficients and the
    persistence regressions are re-estimated with the start year AND the year
    after it held out - a nine-month forecast from mid-year verifies in the
    next calendar year, and a fit that kept those months would be scored on
    data it was trained on. In-sample skill for a model with a dozen free
    parameters would be meaningless.

  * The same forecast that is issued. Persistence uses the production
    regression, the recharge model the production season-averaging, and the
    analog ensemble the production matching, all started from the moment the
    start season's value exists: the end of its last month. The ensemble is
    scored as it is printed - each method weighted by the inverse of its own
    cross-validated mean squared error.

  * Scoring by target season as well as by lead. ENSO forecasts are not
    uniformly skilful: skill collapses for forecasts that must cross boreal
    spring. Reporting only a lead-averaged number would hide the one thing a
    forecaster most needs to know about a given forecast.

All three methods are scored. The analog ensemble used to be left out, as
too awkward to re-derive at every start date, while carrying 45% of the
forecast unverified; matched on the calendar it needs nothing re-derived, and
its weight is now earned the same way as the others'.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .forecast import (
    DEFAULT_WEIGHTS, _mean, _season_step, analog_projection, calendar_analogs,
    filter_analogs, fit_recharge, persist, persistence_fit, recharge_seasons,
    rom_rows, season_months,
)
from .parsers import ONI_SEASONS, MonthValue, SeasonValue

MIN_FIT_SAMPLE = 20
MIN_SCORED = 15  # forecasts needed before a lead's score is worth quoting
BARRIER_LEAD = 6  # the lead at which the spring barrier is clearest

METHODS = ("persistence", "recharge", "analog")


@dataclass
class LeadSkill:
    lead: int
    rmse: float
    acc: float  # anomaly correlation
    bias: float
    count: int
    by_method: dict[str, float] = field(default_factory=dict)  # method -> RMSE

    @property
    def useful(self) -> bool:
        """Correlation above 0.5 is the usual bar for a useful ENSO forecast."""
        return self.acc >= 0.5


@dataclass
class SkillProfile:
    leads: list[LeadSkill]
    by_target_season: dict[str, float]  # season -> ACC at BARRIER_LEAD
    barrier_seasons: list[str]
    barrier_drop: float
    weights: dict[str, float]
    horizon: int  # last lead with ACC >= 0.5
    sample_years: int
    notes: list[str] = field(default_factory=list)

    def rmse_by_lead(self) -> dict[int, float]:
        return {skill.lead: skill.rmse for skill in self.leads}

    def at(self, lead: int) -> LeadSkill | None:
        for skill in self.leads:
            if skill.lead == lead:
                return skill
        return None

    def lost_at(self) -> LeadSkill | None:
        """The first lead scored whose correlation falls below the bar."""
        return next((skill for skill in self.leads if not skill.useful), None)

    @property
    def horizon_is_lower_bound(self) -> bool:
        """No lead scored fell below the bar, so skill lasts at least this long:
        the horizon is where the scoring stopped, not where the skill did."""
        return bool(self.leads) and self.lost_at() is None


def _rmse(errors: list[float]) -> float:
    return math.sqrt(sum(e * e for e in errors) / len(errors)) if errors else 0.0


def _acc(forecasts: list[float], truths: list[float]) -> float:
    if len(forecasts) < 3:
        return 0.0
    f_mean, t_mean = _mean(forecasts), _mean(truths)
    numerator = sum((f - f_mean) * (t - t_mean) for f, t in zip(forecasts, truths))
    denominator = math.sqrt(
        sum((f - f_mean) ** 2 for f in forecasts) * sum((t - t_mean) ** 2 for t in truths)
    )
    return numerator / denominator if denominator else 0.0


def _held_out(year: int) -> tuple[int, int]:
    """The years a hindcast from ``year`` must not be trained on."""
    return (year, year + 1)


def _rom_hindcast(model, sst: dict, heat: dict, start: SeasonValue,
                  leads: int) -> dict[int, float]:
    """The recharge forecast as it would have been issued at the end of ``start``.

    Initialised at the season's last month - the moment the season's value
    exists - and averaged into seasons by the routine the live forecast uses,
    so the score belongs to the forecast actually printed.
    """
    last = season_months(start.season, start.year)[-1]
    return recharge_seasons(model, sst, heat, last, (start.season, start.year), leads)


def _analog_hindcast(series: list[SeasonValue], at: int,
                     leads: int) -> dict[int, float]:
    """The analog forecast as it would have been issued at ``series[at]``."""
    members = filter_analogs(calendar_analogs(series, at=at))
    by_lead, _, _ = analog_projection(series, members, 0, leads,
                                      current_value=series[at].value)
    return {lead: sum(v * w for v, w in pairs) / sum(w for _, w in pairs)
            for lead, pairs in by_lead.items() if pairs}


def _combine(methods: dict[str, float], weights: dict[str, float]) -> float:
    """The ensemble mean exactly as ``forecast.build`` forms it."""
    active = sum(weights.get(name, 0.0) for name in methods)
    if active <= 0.0:
        return _mean(list(methods.values()))
    return sum(weights.get(name, 0.0) * v for name, v in methods.items()) / active


def run(
    series: list[SeasonValue],
    nino34_monthly: list[MonthValue],
    wwv: list[MonthValue],
    leads: int = 9,
    index_name: str = "RONI",
) -> SkillProfile | None:
    """Score all three methods and their weighted ensemble, cross-validated.

    ``series`` is the official index and ``nino34_monthly`` the monthly series
    it averages - the same pair the live forecast runs on.
    """
    if len(series) < 120:
        return None

    notes: list[str] = []
    truth_index = {(v.season, v.year): v.value for v in series}
    years = sorted({v.year for v in series})
    rows = rom_rows(nino34_monthly, wwv) if nino34_monthly and wwv else []
    rom_available = len(rows) >= MIN_FIT_SAMPLE * 2
    if not rom_available and nino34_monthly and wwv:
        notes.append("Too little overlapping SST/WWV data to verify the recharge model.")

    sst_index = {(v.year, v.month): v.value for v in nino34_monthly}
    heat_index = {(v.year, v.month): v.value for v in wwv}

    # Cache the held-out fits: one per year, reused across every start month.
    fit_cache: dict[tuple[int, int], dict[str, tuple[float, float, float]]] = {}
    rom_cache: dict[int, object] = {}

    # One record per start and lead: the target season, the truth, and what
    # each method said. Weights come from the methods' scores, so the
    # ensemble is formed only once every method has been scored.
    records: dict[int, list[tuple[str, float, dict[str, float]]]] = {
        lead: [] for lead in range(1, leads + 1)
    }

    for at, start in enumerate(series):
        # Only verify from a point that has enough record behind it.
        if start.year <= years[0] + 5:
            continue

        track: dict[int, float] = {}
        if rom_available:
            if start.year not in rom_cache:
                rom_cache[start.year] = fit_recharge(
                    nino34_monthly, wwv, exclude_year=_held_out(start.year), rows=rows
                )
            model = rom_cache[start.year]
            if model:
                track = _rom_hindcast(model, sst_index, heat_index, start, leads)
        analog = _analog_hindcast(series, at, leads)

        for lead in range(1, leads + 1):
            target_season, target_year = _season_step(start.season, start.year, lead)
            truth = truth_index.get((target_season, target_year))
            if truth is None:
                continue

            key = (lead, start.year)
            if key not in fit_cache:
                fit_cache[key] = persistence_fit(
                    series, lead, exclude_year=_held_out(start.year)
                )
            fit = fit_cache[key].get(target_season)
            if fit is None:
                continue

            methods = {"persistence": persist(fit, start.value)}
            if lead in track:
                methods["recharge"] = track[lead]
            if lead in analog:
                methods["analog"] = analog[lead]
            records[lead].append((target_season, truth, methods))

    method_mse: dict[str, list[float]] = {name: [] for name in METHODS}
    method_rmse: dict[int, dict[str, float]] = {}
    for lead in range(1, leads + 1):
        if len(records[lead]) < MIN_SCORED:
            continue
        method_rmse[lead] = {}
        for name in METHODS:
            method_pairs = [(m[name], truth) for _, truth, m in records[lead] if name in m]
            if len(method_pairs) >= MIN_SCORED:
                value = _rmse([f - t for f, t in method_pairs])
                method_rmse[lead][name] = value
                method_mse[name].append(value * value)

    # Inverse-MSE weights, every method on the same footing.
    verified = {name: _mean(values) for name, values in method_mse.items() if values}
    inverse = {name: 1.0 / value for name, value in verified.items() if value > 0}
    if inverse:
        total = sum(inverse.values())
        weights = {name: value / total for name, value in inverse.items()}
    else:
        weights = dict(DEFAULT_WEIGHTS)

    results: list[LeadSkill] = []
    per_season: dict[str, list[tuple[float, float]]] = {}
    for lead in range(1, leads + 1):
        if lead not in method_rmse:
            continue
        pairs = [(_combine(m, weights), truth) for _, truth, m in records[lead]]
        if lead == BARRIER_LEAD:
            for (season, _, _), pair in zip(records[lead], pairs):
                per_season.setdefault(season, []).append(pair)
        forecasts = [p[0] for p in pairs]
        truths = [p[1] for p in pairs]
        errors = [f - t for f, t in pairs]
        by_method = method_rmse[lead]
        results.append(
            LeadSkill(
                lead=lead,
                rmse=_rmse(errors),
                acc=_acc(forecasts, truths),
                bias=_mean(errors),
                count=len(pairs),
                by_method=by_method,
            )
        )

    if not results:
        return None

    by_target = {
        season: _acc([p[0] for p in pairs], [p[1] for p in pairs])
        for season, pairs in per_season.items()
        if len(pairs) >= MIN_SCORED
    }
    barrier_seasons: list[str] = []
    barrier_drop = 0.0
    if by_target:
        worst = min(by_target.values())
        best = max(by_target.values())
        barrier_drop = best - worst
        barrier_seasons = sorted(
            (s for s, v in by_target.items() if v <= worst + 0.05),
            key=lambda s: ONI_SEASONS.index(s),
        )

    horizon = 0
    for skill in results:
        if skill.useful:
            horizon = skill.lead
        else:
            break

    notes.append(
        f"Scored over {len(years)} years of {index_name} with the start year and "
        "the year after it held out of every fit."
    )

    return SkillProfile(
        leads=results,
        by_target_season=by_target,
        barrier_seasons=barrier_seasons,
        barrier_drop=barrier_drop,
        weights=weights,
        horizon=horizon,
        sample_years=len(years),
        notes=notes,
    )
