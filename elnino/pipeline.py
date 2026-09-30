"""The orchestrator: fetch, parse, diagnose, forecast, verify, alert, persist.

Everything else in the package is a component with no knowledge of the others.
This module is the only place that knows the order they run in, and it is
deliberately tolerant: one malformed feed degrades the output, it does not stop
the run. Every degradation is recorded in ``warnings`` and surfaced in the
report and the dashboard, because a silently reduced analysis is worse than no
analysis at all.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from . import (
    alerts,
    atlas,
    atmosphere,
    classify,
    cyclones,
    stormfury,
    forecast,
    grids,
    impacts,
    parsers,
    sources,
    storage,
    subsurface,
    verification,
)

# Feeds that are stacked CPC monthly grids and can share one parser.
GRID_FEEDS = (
    "eqsoi", "darwin", "tahiti", "olr", "olr_central",
    "trade_central", "trade_west", "trade_east", "zwnd200", "qbo30", "qbo50",
)

FORECAST_ANALOGS = 10  # more members than the display table shows


@dataclass
class SystemState:
    """One complete run of the system."""

    run_at: str
    assessment: classify.Assessment
    subsurface: subsurface.SubsurfaceState | None
    atmosphere: atmosphere.AtmosphereState
    forecast: forecast.Forecast
    skill: verification.SkillProfile | None
    impacts: impacts.ImpactAssessment
    alert_set: alerts.AlertSet
    spatial: grids.SpatialState
    cyclones: cyclones.CycloneState
    stormfury: stormfury.FuryState
    atlas: atlas.AtlasState
    discussion: dict
    fetched: dict
    series: dict = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    previous: storage.Snapshot | None = None

    @property
    def degraded(self) -> bool:
        return bool(self.warnings)


def _safe(warnings: list[str], label: str, function, *args, default=None, **kwargs):
    """Run a parser, turning a failure into a warning instead of a crash."""
    try:
        return function(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 - reported, not swallowed
        warnings.append(f"{label}: {type(exc).__name__}: {exc}")
        return default


def parse_all(fetched: dict) -> tuple[dict, list[str]]:
    """Parse every feed that came back, collecting failures as warnings."""
    warnings: list[str] = []
    text = {key: item.text for key, item in fetched.items() if item.ok}
    series: dict = {}

    if "oni" in text:
        series["oni"] = _safe(warnings, "oni", parsers.parse_oni, text["oni"], default=[])
    if "roni" in text:
        series["roni"] = _safe(warnings, "roni", parsers.parse_roni, text["roni"], default=[])
    if "weekly_sst" in text:
        series["weeks"] = _safe(
            warnings, "weekly_sst", parsers.parse_weekly_sst, text["weekly_sst"], default=[]
        )
    if "monthly_sst" in text:
        series["monthly"] = _safe(
            warnings, "monthly_sst", parsers.parse_monthly_sst, text["monthly_sst"], default={}
        )
    if "rel_weekly_sst" in text:
        series["rel_weeks"] = _safe(
            warnings, "rel_weekly_sst", parsers.parse_rel_weekly,
            text["rel_weekly_sst"], default=[],
        )
    if "rel_monthly_sst" in text:
        series["rel_monthly"] = _safe(
            warnings, "rel_monthly_sst", parsers.parse_rel_monthly,
            text["rel_monthly_sst"], default={},
        )
    if "nino34_detrended" in text:
        series["nino34_detrended"] = _safe(
            warnings, "nino34_detrended", parsers.parse_yr_mon_anom,
            text["nino34_detrended"], default=[], column=4, width=5,
        )
    if "nino34_relative" in text:
        series["nino34_relative"] = _safe(
            warnings, "nino34_relative", parsers.parse_yr_mon_anom,
            text["nino34_relative"], default=[],
        )
    if "soi" in text:
        soi = _safe(warnings, "soi", parsers.parse_soi, text["soi"], default={})
        series["soi_tables"] = soi
        series["soi"] = soi.get("standardized", []) if soi else []
    if "mei" in text:
        series["mei"] = _safe(warnings, "mei", parsers.parse_mei, text["mei"], default=[])
    if "atlantic" in text:
        series["atlantic"] = _safe(
            warnings, "atlantic", parsers.parse_atlantic_indices, text["atlantic"], default={}
        )
    if "mjo" in text:
        series["mjo"] = _safe(warnings, "mjo", parsers.parse_mjo, text["mjo"], default={})
    if "discussion" in text:
        series["discussion"] = _safe(
            warnings, "discussion", parsers.parse_discussion, text["discussion"], default={}
        )

    for key in ("wwv", "wwv_west"):
        if key in text:
            series[key] = _safe(warnings, key, parsers.parse_wwv, text[key], default=[])

    # Named for what they are rather than "grids": this module now imports a
    # module of that name, and a local that shadows it is a trap.
    cpc_grids: dict[str, dict] = {}
    for key in GRID_FEEDS:
        if key in text:
            parsed = _safe(warnings, key, parsers.parse_cpc_grid, text[key], default={})
            if parsed:
                cpc_grids[key] = parsed
    if series.get("soi_tables"):
        cpc_grids["soi"] = series["soi_tables"]
    series["grids"] = cpc_grids

    return series, warnings


def build_spatial(fetched: dict) -> grids.SpatialState:
    """Shape every spatial feed that came back, tolerating any of them missing.

    The spatial tier is strictly additive: it makes the event visible, it does
    not feed the classification or the forecast. So a failure anywhere in here
    costs a picture and nothing else, and each field is built inside its own
    try block rather than letting one bad feed take the rest of the geometry
    down with it.
    """
    state = grids.SpatialState()
    text = {key: item.text for key, item in fetched.items() if item.ok}

    def attempt(label: str, function, *args, **kwargs):
        try:
            return function(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - recorded, never fatal
            state.notes.append(f"{label}: {type(exc).__name__}: {exc}")
            return None

    if "sst_pacific" in text:
        state.sst_map = attempt(
            "Pacific SST anomaly", grids.grid_map, text["sst_pacific"], "anom",
            "Tropical Pacific SST anomaly", "°C",
        )
        absolute = attempt(
            "Pacific SST", grids.grid_map, text["sst_pacific"], "sst",
            "Tropical Pacific SST", "°C",
        )
        if absolute is not None:
            state.warm_pool = grids.warm_pool_edge(absolute)
        if state.sst_map is not None:
            for box in grids.NINO_BOXES:
                mean = grids.box_mean(state.sst_map, box)
                if mean is not None:
                    state.box_means[box.key] = mean

    if "sst_global" in text:
        state.sst_global = attempt(
            "global SST anomaly", grids.grid_map, text["sst_global"], "anom",
            "Global SST anomaly", "°C",
        )
    if "sst_hovmoller" in text:
        state.sst_hov = attempt(
            "SST Hovmoller", grids.grid_hovmoller, text["sst_hovmoller"], "anom",
            "Equatorial SST anomaly", "°C",
        )
    if "ssh_pacific" in text:
        state.ssh_map = attempt(
            "sea surface height", grids.grid_map, text["ssh_pacific"], "sla",
            "Sea surface height anomaly", "m",
        )
    if "ssh_hovmoller" in text:
        state.ssh_hov = attempt(
            "sea surface height Hovmoller", grids.grid_hovmoller,
            text["ssh_hovmoller"], "sla", "Equatorial sea surface height anomaly", "m",
        )
    if "tao_temperature" in text:
        state.section = attempt("depth section", grids.section, text["tao_temperature"])
        state.section_anomaly = attempt(
            "depth section anomaly", grids.section, text["tao_temperature"], anomaly=True
        )
        built = attempt("temperature profiles", grids.profiles, text["tao_temperature"])
        if built:
            state.profiles = tuple(built[0])
    if "tao_isotherm" in text:
        state.iso_hov = attempt(
            "isotherm Hovmoller", grids.iso_hovmoller, text["tao_isotherm"],
            months=sources.HOVMOLLER_MONTHS,
        )
        state.iso_hov_anomaly = attempt(
            "isotherm anomaly Hovmoller", grids.iso_hovmoller, text["tao_isotherm"],
            months=sources.HOVMOLLER_MONTHS, anomaly=True,
        )
    if "tao_mesh" in text:
        state.mesh = attempt(
            "thermocline surface", grids.thermocline_mesh, text["tao_mesh"],
            text.get("tao_isotherm"),
        )

    # Age each field against its own stamp. An experimental altimetry product
    # that is three months behind is still worth showing, but only if the
    # panel says so rather than implying it is current.
    for name in ("sst_map", "sst_global", "sst_hov", "ssh_map", "ssh_hov",
                 "section", "section_anomaly", "iso_hov", "iso_hov_anomaly",
                 "mesh"):
        item = getattr(state, name)
        if item is None:
            continue
        age = grids.age_days(item.as_of)
        if age is not None:
            state.stale[name] = age
    return state


# The monthly Nino-3.4 each index is the three-month mean of.
MONTHLY_INPUT = {"RONI": "nino34_relative", "ONI": "nino34_detrended"}


def nino34_monthly(series: dict, index_name: str = "RONI") -> list[parsers.MonthValue]:
    """The monthly Nino-3.4 the official index is the three-month mean of.

    RONI averages Rnino34 and ONI the detrended ERSST series, so those are what
    the recharge model, the hindcast and the phase-space view run on: a
    forecast of the index has to start from the index's own numbers. The OISST
    files are another analysis on another base - for August 2026 they put
    Nino-3.4 at +2.52 degC against +2.17 in the ONI's input and +1.67 in
    RONI's - and stand in only when the index's own input is missing, the
    relative OISST series for RONI because it removes the same tropical mean.
    """
    own = series.get(MONTHLY_INPUT.get(index_name, "nino34_detrended"))
    if own:
        return own
    if index_name == "RONI":
        relative = (series.get("rel_monthly") or {}).get("nino34")
        if relative:
            return relative
    return (series.get("monthly") or {}).get("nino34") or []


def run(
    raw_dir: Path,
    db_path: Path,
    offline: bool = False,
    progress=None,
    leads: int = forecast.DEFAULT_LEADS,
) -> SystemState:
    """Execute one full cycle and return everything it produced."""
    fetched = sources.fetch_all(raw_dir, offline=offline, progress=progress)
    series, warnings = parse_all(fetched)

    # RONI is the official index and ONI the legacy one beside it. Either can
    # carry the classification, so only losing both stops the run; losing
    # either is a degraded run, and says which.
    oni = series.get("oni") or []
    if not oni and not series.get("roni"):
        raise RuntimeError(
            "Neither RONI nor ONI arrived, and neither is cached. The tracker "
            "cannot classify the state of the system without one of them."
        )
    if not series.get("roni"):
        warnings.append(
            "RONI, CPC's official index since February 2026, did not arrive: "
            "the classification is running on the legacy ONI, which reads warm "
            "of RONI in a warming ocean."
        )
    if not oni:
        warnings.append(
            "The legacy ONI did not arrive: RONI, the official index, carries "
            "the analysis, and the comparison with ONI is absent this run."
        )

    discussion = series.get("discussion") or {}
    assessment = classify.assess(
        oni,
        series.get("roni") or [],
        series.get("weeks") or [],
        series.get("soi") or [],
        series.get("mei") or [],
        status=discussion.get("status", ""),
        relative_weeks=series.get("rel_weeks") or [],
    )
    # Everything downstream - forecast, hindcast, analogs, the hazard outlook,
    # the hurricane composite - runs on the index the classification used.
    index_series = assessment.index_series
    index_name = assessment.index_name

    monthly_sst = nino34_monthly(series, index_name)
    if not series.get(MONTHLY_INPUT[index_name]):
        warnings.append(
            f"The monthly Nino-3.4 that {index_name} averages did not arrive; the "
            "recharge model, the hindcast and the phase space are running on the "
            "OISST analysis instead, which is a different product on a different base."
        )
    wwv_obs = series.get("wwv") or []
    wwv_monthly = [obs.month_value for obs in wwv_obs]

    subsurface_state = None
    if wwv_obs:
        # A long trajectory: the phase-space panel shows the last four years of
        # it, the heat-content panel the last fifteen.
        subsurface_state = subsurface.analyse(
            wwv_obs, series.get("wwv_west") or [], monthly_sst,
            trajectory_months=240,
        )
    else:
        warnings.append("No warm water volume data: the subsurface view is unavailable.")

    atmosphere_state = atmosphere.analyse(
        series.get("grids") or {},
        series.get("mjo") or {},
        (series.get("grids") or {}).get("qbo30"),
    )
    if not atmosphere_state.indicators:
        warnings.append("No atmospheric feeds parsed: coupling cannot be assessed.")

    spatial = build_spatial(fetched)
    warnings.extend(spatial.notes)
    if not spatial.available:
        warnings.append("No spatial feeds parsed: the map and section views are absent.")

    # The cyclone tier fetches on its own, because the files it needs are
    # named after storms that only today's advisory index knows exist and
    # after archive files that get renamed every spring. It is given the same
    # cache and the same offline switch as everything else, so an offline run
    # reproduces the last online one instead of going quiet.
    storms = cyclones.build(
        fetched, index_series, lambda source: sources.fetch(source, raw_dir, offline)
    )
    warnings.extend(storms.notes)
    # A protective product the index links but that did not arrive is a failed
    # feed like any other, and the storm it was for is named.
    for storm in storms.active:
        for label in getattr(storm.products, "unavailable", ()):
            warnings.append(f"{storm.title}: {label} could not be fetched or read.")
    if not storms.available:
        warnings.append("No cyclone feeds parsed: the storm tier is absent.")

    # The STORMFURY recreation is pure arithmetic over decks already in hand,
    # so it runs here rather than in the renderers: the report and the
    # dashboard then quote one set of numbers instead of computing two.
    fury = stormfury.evaluate(storms)

    # The atlas reads vendored composites and a vendored gazetteer, so it has
    # nothing to fetch and cannot fail on a feed. It takes the storms only so a
    # click near an active one says so.
    ground = atlas.evaluate(storms.storms if storms.available else ())
    warnings.extend(ground.reasons if not ground.available else [])

    skill = verification.run(
        index_series, monthly_sst, wwv_monthly, leads=leads, index_name=index_name
    )

    # Analogs for the forecast: the years that ran most like this one over the
    # same calendar seasons, continued from the same season - the rule the
    # hindcast above scored. The display card's analogs are a different thing:
    # past El Ninos aligned on onset, to show how comparable events evolved.
    analog_members = forecast.calendar_analogs(index_series, keep=FORECAST_ANALOGS)

    forecast_result = forecast.build(
        index_series,
        monthly_sst,
        wwv_monthly,
        analog_members,
        leads=leads,
        skill=skill.rmse_by_lead() if skill else None,
        weights=skill.weights if skill else None,
        skill_source=(
            f"cross-validated hindcast over {skill.sample_years} years"
            if skill
            else "default weights (verification unavailable)"
        ),
        index_name=index_name,
    )

    peak_projection = forecast_result.peak
    current = assessment.index_latest.value
    projected_peak = max(current, peak_projection.mean if peak_projection else current)
    months_to_peak = peak_projection.lead if peak_projection else None
    impact_assessment = impacts.assess(
        projected_peak,
        assessment.scale.flavour_index if assessment.scale else 0.0,
        current_index=current,
        months_to_peak=months_to_peak,
        index_name=index_name,
    )

    # Persist, then evaluate alerts against what the previous run recorded.
    run_at = storage.now()
    conn = storage.connect(db_path)
    try:
        previous = storage.previous_snapshot(conn, run_at)
        raised = alerts.evaluate(
            assessment,
            subsurface_state,
            atmosphere_state,
            forecast_result,
            fetched,
            previous,
            storms,
            now=run_at,
        )
        alert_set = alerts.reconcile(conn, raised, run_at)

        storage.record_fetches(conn, run_at, fetched)
        storage.record_snapshot(conn, run_at, snapshot_values(
            assessment, subsurface_state, atmosphere_state, forecast_result
        ))
        if oni:
            storage.record_series(
                conn, run_at, "oni", [(v.label, v.value) for v in oni[-24:]]
            )
        if series.get("roni"):
            storage.record_series(
                conn, run_at, "roni", [(v.label, v.value) for v in series["roni"][-24:]]
            )
    finally:
        conn.close()

    return SystemState(
        run_at=run_at,
        assessment=assessment,
        subsurface=subsurface_state,
        atmosphere=atmosphere_state,
        forecast=forecast_result,
        skill=skill,
        impacts=impact_assessment,
        alert_set=alert_set,
        spatial=spatial,
        cyclones=storms,
        stormfury=fury,
        atlas=ground,
        discussion=discussion,
        fetched=fetched,
        series=series,
        warnings=warnings,
        previous=previous,
    )


def snapshot_values(
    assessment, subsurface_state, atmosphere_state, forecast_result
) -> dict:
    """The headline numbers worth keeping run over run."""
    week = assessment.latest_week
    peak = forecast_result.peak if forecast_result else None
    return {
        "observed_at": assessment.index_latest.label,
        "status": assessment.status,
        "index_name": assessment.index_name,
        "index": assessment.index_latest.value,
        "index_label": assessment.index_latest.label,
        "oni_label": assessment.oni_latest.label if assessment.oni_latest else None,
        "oni": assessment.oni_latest.value if assessment.oni_latest else None,
        "roni": assessment.roni_latest.value if assessment.roni_latest else None,
        "nino34_weekly": week.nino34_anom if week else None,
        "nino12_weekly": week.nino12_anom if week else None,
        "flavour_index": assessment.scale.flavour_index if assessment.scale else None,
        "walker_index": atmosphere_state.walker_index if atmosphere_state else None,
        "wwv_anomaly": subsurface_state.anomaly if subsurface_state else None,
        "wwv_rank": subsurface_state.rank_alltime if subsurface_state else None,
        "power_index": assessment.power.value,
        "forecast_peak": peak.mean if peak else None,
        "forecast_label": peak.label if peak else None,
        "episode_length": assessment.episode.length if assessment.episode else 0,
    }
