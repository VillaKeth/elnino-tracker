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
    atmosphere,
    classify,
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
            "Tropical Pacific SST anomaly", "degrees C",
        )
        absolute = attempt(
            "Pacific SST", grids.grid_map, text["sst_pacific"], "sst",
            "Tropical Pacific SST", "degrees C",
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
            "Global SST anomaly", "degrees C",
        )
    if "sst_hovmoller" in text:
        state.sst_hov = attempt(
            "SST Hovmoller", grids.grid_hovmoller, text["sst_hovmoller"], "anom",
            "Equatorial SST anomaly", "degrees C",
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


def nino34_monthly(series: dict) -> list[parsers.MonthValue]:
    """Best available monthly Nino-3.4 anomaly series."""
    monthly = series.get("monthly") or {}
    if monthly.get("nino34"):
        return monthly["nino34"]
    return series.get("nino34_relative") or []


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

    oni = series.get("oni") or []
    if not oni:
        raise RuntimeError(
            "No ONI data and no cache. The tracker cannot classify the state of "
            "the system without it."
        )

    discussion = series.get("discussion") or {}
    assessment = classify.assess(
        oni,
        series.get("roni") or [],
        series.get("weeks") or [],
        series.get("soi") or [],
        series.get("mei") or [],
        status=discussion.get("status", ""),
    )

    monthly_sst = nino34_monthly(series)
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

    skill = verification.run(oni, monthly_sst, wwv_monthly, leads=leads)

    # Analogs for the forecast: a wider set than the display table uses, so the
    # ensemble spread is not dominated by two or three members.
    analog_members: list[forecast.AnalogMember] = []
    stage = 0
    if assessment.episode:
        stage = max(assessment.episode.length - 1, 0)
        wide = classify.find_analogs(oni, assessment.episode, limit=FORECAST_ANALOGS)
        analog_members = [
            forecast.AnalogMember(
                analog.episode.onset.season,
                analog.episode.onset.year,
                analog.episode.name,
                analog.rmse,
            )
            for analog in wide
        ]

    forecast_result = forecast.build(
        oni,
        monthly_sst,
        wwv_monthly,
        analog_members,
        stage,
        leads=leads,
        skill=skill.rmse_by_lead() if skill else None,
        weights=skill.weights if skill else None,
        skill_source=(
            f"cross-validated hindcast over {skill.sample_years} years"
            if skill
            else "default weights (verification unavailable)"
        ),
    )

    peak_projection = forecast_result.peak
    projected_peak = max(
        assessment.oni_latest.value,
        peak_projection.mean if peak_projection else assessment.oni_latest.value,
    )
    months_to_peak = peak_projection.lead if peak_projection else None
    impact_assessment = impacts.assess(
        projected_peak,
        assessment.scale.flavour_index if assessment.scale else 0.0,
        current_oni=assessment.oni_latest.value,
        months_to_peak=months_to_peak,
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
        )
        alert_set = alerts.reconcile(conn, raised, run_at)

        storage.record_fetches(conn, run_at, fetched)
        storage.record_snapshot(conn, run_at, snapshot_values(
            assessment, subsurface_state, atmosphere_state, forecast_result
        ))
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
        "observed_at": assessment.oni_latest.label,
        "status": assessment.status,
        "oni_label": assessment.oni_latest.label,
        "oni": assessment.oni_latest.value,
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
