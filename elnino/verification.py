"""Hindcast verification: how much is the forecast actually worth?

A forecast without a measured error bar is an opinion. This module re-runs the
forecast methods over the historical record and scores them, so that every
projection the tracker prints can carry an uncertainty that was measured rather
than assumed.

Two things make this honest rather than decorative:

  * Cross-validation by year. The recharge model's coefficients and the
    persistence autocorrelations are re-estimated with the verification year
    held out, so a method is never scored on data it was fitted to. In-sample
    skill for a model with a dozen free parameters would be meaningless.

  * Scoring by target season as well as by lead. ENSO forecasts are not
    uniformly skilful: skill collapses for forecasts that must cross boreal
    spring. Reporting only a lead-averaged number would hide the one thing a
    forecaster most needs to know about a given forecast.

The analog method is deliberately NOT scored here - see ANALOG_NOTE.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from .forecast import _mean, _season_step, fit_recharge, rom_rows
from .parsers import ONI_SEASONS, MonthValue, SeasonValue

MIN_FIT_SAMPLE = 20
MIN_SCORED = 15  # forecasts needed before a lead's score is worth quoting
BARRIER_LEAD = 6  # the lead at which the spring barrier is clearest

ANALOG_NOTE = (
    "The analog ensemble is not scored here. Scoring it would require "
    "re-deriving the episode catalogue at every historical start date, and a "
    "version that skipped that step would not be the method actually in use. "
    "Its members supply the spread of the forecast band; the band's width "
    "comes from the verified methods."
)


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


def _persistence_rho(
    series: list[SeasonValue], lead: int, exclude_year: int | None
) -> dict[str, float]:
    """Per-target-season lag correlation, optionally holding out one year."""
    index = {(v.season, v.year): v.value for v in series}
    buckets: dict[str, list[tuple[float, float]]] = {}
    for value in series:
        if exclude_year is not None and value.year == exclude_year:
            continue
        target_season, target_year = _season_step(value.season, value.year, lead)
        if exclude_year is not None and target_year == exclude_year:
            continue
        target = index.get((target_season, target_year))
        if target is None:
            continue
        buckets.setdefault(target_season, []).append((value.value, target))

    out: dict[str, float] = {}
    for season, pairs in buckets.items():
        if len(pairs) < MIN_FIT_SAMPLE:
            continue
        starts = [p[0] for p in pairs]
        ends = [p[1] for p in pairs]
        start_mean, end_mean = _mean(starts), _mean(ends)
        numerator = sum((a - start_mean) * (b - end_mean) for a, b in pairs)
        denominator = math.sqrt(
            sum((a - start_mean) ** 2 for a in starts)
            * sum((b - end_mean) ** 2 for b in ends)
        )
        out[season] = numerator / denominator if denominator else 0.0
    return out


def _rom_forecast(model, start_month: int, sst: float, heat: float, leads: int):
    """Integrate a held-out model forward. Same stepper as the live forecast."""
    from .forecast import recharge_projection

    return recharge_projection(model, sst, heat, start_month, leads)


def run(
    oni: list[SeasonValue],
    nino34_monthly: list[MonthValue],
    wwv: list[MonthValue],
    leads: int = 9,
) -> SkillProfile | None:
    """Score damped persistence and the recharge oscillator, cross-validated."""
    if len(oni) < 120:
        return None

    notes: list[str] = [ANALOG_NOTE]
    oni_index = {(v.season, v.year): v.value for v in oni}
    years = sorted({v.year for v in oni})
    rows = rom_rows(nino34_monthly, wwv) if nino34_monthly and wwv else []
    rom_available = len(rows) >= MIN_FIT_SAMPLE * 2
    if not rom_available and nino34_monthly and wwv:
        notes.append("Too little overlapping SST/WWV data to verify the recharge model.")

    sst_index = {(v.year, v.month): v.value for v in nino34_monthly}
    heat_index = {(v.year, v.month): v.value for v in wwv}

    # Cache the held-out fits: one per year, reused across every start month.
    rho_cache: dict[tuple[int, int], dict[str, float]] = {}
    rom_cache: dict[int, object] = {}

    scored: dict[int, dict[str, list[tuple[float, float]]]] = {
        lead: {"persistence": [], "recharge": [], "ensemble": []}
        for lead in range(1, leads + 1)
    }
    per_season: dict[str, list[tuple[float, float]]] = {}

    for start in oni:
        # Only verify from a point that has enough record behind it.
        if start.year <= years[0] + 5:
            continue
        for lead in range(1, leads + 1):
            target_season, target_year = _season_step(start.season, start.year, lead)
            truth = oni_index.get((target_season, target_year))
            if truth is None:
                continue

            key = (lead, start.year)
            if key not in rho_cache:
                rho_cache[key] = _persistence_rho(oni, lead, start.year)
            rho = rho_cache[key].get(target_season)
            if rho is None:
                continue
            persistence = start.value * max(rho, 0.0)

            members: list[tuple[str, float]] = [("persistence", persistence)]

            if rom_available:
                if start.year not in rom_cache:
                    rom_cache[start.year] = fit_recharge(
                        nino34_monthly, wwv, exclude_year=start.year, rows=rows
                    )
                model = rom_cache[start.year]
                centre_month = ONI_SEASONS.index(start.season) + 1
                sst_now = sst_index.get((start.year, centre_month))
                heat_now = heat_index.get((start.year, centre_month))
                if model and sst_now is not None and heat_now is not None:
                    track = _rom_forecast(model, centre_month, sst_now, heat_now, leads)
                    if lead in track:
                        members.append(("recharge", track[lead]))

            for name, value in members:
                scored[lead][name].append((value, truth))
            ensemble = _mean([value for _, value in members])
            scored[lead]["ensemble"].append((ensemble, truth))

            if lead == BARRIER_LEAD:
                per_season.setdefault(target_season, []).append((ensemble, truth))

    results: list[LeadSkill] = []
    method_mse: dict[str, list[float]] = {"persistence": [], "recharge": []}
    for lead in range(1, leads + 1):
        pairs = scored[lead]["ensemble"]
        if len(pairs) < MIN_SCORED:
            continue
        forecasts = [p[0] for p in pairs]
        truths = [p[1] for p in pairs]
        errors = [f - t for f, t in pairs]
        by_method = {}
        for name in ("persistence", "recharge"):
            method_pairs = scored[lead][name]
            if len(method_pairs) >= MIN_SCORED:
                value = _rmse([f - t for f, t in method_pairs])
                by_method[name] = value
                method_mse[name].append(value * value)
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

    # Inverse-MSE weights for the verified methods; the analog ensemble keeps
    # its default share because it is not scored here.
    weights = {"analog": 0.45}
    verified = {
        name: _mean(values) for name, values in method_mse.items() if values
    }
    if verified:
        inverse = {name: 1.0 / value for name, value in verified.items() if value > 0}
        total = sum(inverse.values())
        for name, value in inverse.items():
            weights[name] = 0.55 * value / total
    else:
        weights.update({"persistence": 0.2, "recharge": 0.35})

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
        f"Scored over {len(years)} years of ONI with the verification year held "
        "out of every fit."
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
