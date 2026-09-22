"""Alerting: what changed, what crossed a line, and what stopped working.

A monitoring tool that prints the same page every morning trains you to stop
reading it. The rules here exist to answer one question on each run - is there
anything here you did not already know yesterday - and to keep saying so until
the condition clears.

Three kinds of rule:

  * state      a threshold the system has crossed and is still past
  * change     something that moved since the previous run
  * integrity  a feed that is stale, failed, or disagreeing with its siblings

Integrity rules are not filler. The most dangerous failure mode for a tracker
like this is not being wrong; it is being confidently unchanged because a file
stopped updating, which is exactly what CPC's old weekly SST file did for years
while still returning HTTP 200.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

INFO = "info"
WATCH = "watch"
WARNING = "warning"
CRITICAL = "critical"

LEVEL_ORDER = {CRITICAL: 0, WARNING: 1, WATCH: 2, INFO: 3}

# ONI values worth announcing a crossing of.
ONI_STEPS: tuple[tuple[float, str, str], ...] = (
    (0.5, WATCH, "El Nino threshold"),
    (1.0, WATCH, "Moderate El Nino"),
    (1.5, WARNING, "Strong El Nino"),
    (2.0, WARNING, "Very strong El Nino"),
    (2.5, CRITICAL, "Historic territory"),
)

STALE_DAYS = 45  # an ONI this old means the monthly update was missed


@dataclass
class Alert:
    code: str
    level: str
    title: str
    detail: str
    value: float | None = None
    kind: str = "state"
    is_new: bool = False
    first_seen: str | None = None

    @property
    def rank(self) -> int:
        return LEVEL_ORDER.get(self.level, 9)


@dataclass
class AlertSet:
    alerts: list[Alert] = field(default_factory=list)
    cleared: list[str] = field(default_factory=list)

    @property
    def new(self) -> list[Alert]:
        return [alert for alert in self.alerts if alert.is_new]

    @property
    def worst(self) -> str:
        return min((a.level for a in self.alerts), key=lambda l: LEVEL_ORDER[l], default=INFO)

    def by_level(self, level: str) -> list[Alert]:
        return [alert for alert in self.alerts if alert.level == level]


def _add(out: list[Alert], **kwargs) -> None:
    out.append(Alert(**kwargs))


def evaluate(
    assessment,
    subsurface_state=None,
    atmosphere_state=None,
    forecast_result=None,
    fetched: dict | None = None,
    previous=None,
) -> list[Alert]:
    """Run every rule against the current state. Ordering happens later."""
    out: list[Alert] = []
    latest = assessment.oni_latest

    # -- state: how big is it, right now ------------------------------------
    for threshold, level, name in ONI_STEPS:
        if latest.value >= threshold:
            _add(
                out,
                code=f"oni_ge_{threshold:.1f}",
                level=level,
                title=f"ONI at or above +{threshold:.1f} degC - {name}",
                detail=(
                    f"{latest.label} ONI is {latest.value:+.2f} degC. "
                    f"{assessment.oni_tier} by the peak-ONI convention."
                ),
                value=latest.value,
            )

    if assessment.episode and assessment.episode.qualifies:
        _add(
            out,
            code="episode_qualified",
            level=WARNING,
            title="Formal El Nino episode criteria met",
            detail=(
                f"{assessment.episode.length} consecutive overlapping seasons at or "
                f"above +0.5 degC, from {assessment.episode.onset.label}. NOAA's "
                "five-season rule is satisfied."
            ),
            value=float(assessment.episode.length),
        )
    elif assessment.seasons_at_threshold >= 3:
        _add(
            out,
            code="episode_forming",
            level=WATCH,
            title="El Nino conditions present, episode not yet formal",
            detail=(
                f"{assessment.seasons_at_threshold} consecutive seasons at or above "
                f"+0.5 degC. {assessment.episode_status}"
            ),
            value=float(assessment.seasons_at_threshold),
        )

    ranking = assessment.ranking
    if ranking.rank_season == 1 and ranking.total_season >= 20:
        _add(
            out,
            code="record_season",
            level=CRITICAL,
            title=f"Warmest {latest.season} on record",
            detail=(
                f"{latest.value:+.2f} degC is the highest {latest.season} ONI in "
                f"{ranking.total_season} years of record."
            ),
            value=latest.value,
            kind="state",
        )
    elif ranking.rank_season <= 3 and ranking.total_season >= 20:
        _add(
            out,
            code="top3_season",
            level=WARNING,
            title=f"Third-warmest {latest.season} or better",
            detail=(
                f"Rank {ranking.rank_season} of {ranking.total_season} for this "
                "calendar season."
            ),
            value=latest.value,
        )

    # ONI and RONI disagreeing matters: it says how much of the anomaly is the
    # Pacific doing something and how much is a warmer ocean everywhere.
    if assessment.roni_latest is not None:
        divergence = latest.value - assessment.roni_latest.value
        if abs(divergence) >= 0.4:
            _add(
                out,
                code="roni_divergence",
                level=INFO,
                title="ONI and RONI diverging",
                detail=(
                    f"ONI {latest.value:+.2f} against RONI "
                    f"{assessment.roni_latest.value:+.2f}, a gap of {divergence:+.2f} "
                    "degC. The tropical-mean background accounts for that much of "
                    "the raw anomaly, so RONI is the fairer comparison with events "
                    "before the 2000s."
                ),
                value=divergence,
            )

    # -- change: is it still building ---------------------------------------
    momentum = assessment.momentum
    if momentum.season_delta is not None and momentum.season_delta >= 0.25:
        _add(
            out,
            code="momentum_building",
            level=WATCH,
            title="Still intensifying",
            detail=(
                f"ONI rose {momentum.season_delta:+.2f} degC from the previous "
                f"season ({momentum.direction})."
            ),
            value=momentum.season_delta,
            kind="change",
        )
    if momentum.weekly_delta is not None and momentum.weekly_delta >= 0.4:
        _add(
            out,
            code="weekly_surge",
            level=WATCH,
            title="Sharp four-week warming in Nino-3.4",
            detail=(
                f"Weekly Nino-3.4 has risen {momentum.weekly_delta:+.2f} degC over "
                "four weeks."
            ),
            value=momentum.weekly_delta,
            kind="change",
        )

    # -- subsurface ----------------------------------------------------------
    if subsurface_state is not None:
        state = subsurface_state
        if state.rank_alltime == 1:
            _add(
                out,
                code="wwv_record",
                level=CRITICAL,
                title="Record equatorial warm water volume",
                detail=(
                    f"{state.latest.label} WWV anomaly is {state.anomaly:+.2f} "
                    f"x10^14 m3 - the highest of {state.total_alltime} months on "
                    "record. Stored heat is the fuel available to the surface "
                    "anomaly over the following two to three seasons."
                ),
                value=state.anomaly,
            )
        elif state.rank_alltime <= 5:
            _add(
                out,
                code="wwv_top5",
                level=WARNING,
                title="Warm water volume in the top five on record",
                detail=(
                    f"Rank {state.rank_alltime} of {state.total_alltime} months at "
                    f"{state.anomaly:+.2f} x10^14 m3."
                ),
                value=state.anomaly,
            )

        if state.anomaly > 1.0 and state.tendency > 0.05 and latest.value >= 1.0:
            _add(
                out,
                code="recharge_during_event",
                level=WARNING,
                title="Heat content still rising during an active event",
                detail=(
                    f"WWV is {state.tendency:+.3f} x10^14 m3 per month and still "
                    "climbing while the surface anomaly is already large. Events "
                    "normally begin discharging by this stage; continued recharge "
                    "means the event has not yet spent its fuel."
                ),
                value=state.tendency,
                kind="change",
            )
        if state.discharging and latest.value >= 1.0 and state.anomaly < 1.0:
            _add(
                out,
                code="discharge_underway",
                level=INFO,
                title="Discharge phase under way",
                detail=(
                    "Warm water volume is falling while the surface anomaly is still "
                    "high - historically the signature of an event at or just past "
                    "its peak."
                ),
                value=state.tendency,
                kind="change",
            )

    # -- atmosphere ----------------------------------------------------------
    if atmosphere_state is not None:
        walker = atmosphere_state.walker_index
        if walker >= 2.0:
            _add(
                out,
                code="walker_extreme",
                level=CRITICAL,
                title="Walker circulation response is extreme",
                detail=(
                    f"Composite atmospheric index {walker:+.2f} sigma across "
                    f"{len(atmosphere_state.indicators)} independent feeds. Full "
                    "coupling means the teleconnections are live, not merely possible."
                ),
                value=walker,
            )
        elif walker >= 1.0:
            _add(
                out,
                code="walker_coupled",
                level=WARNING,
                title="Ocean and atmosphere are coupled",
                detail=(
                    f"Composite atmospheric index {walker:+.2f} sigma, with "
                    f"{atmosphere_state.agreement:.0%} of indicators in agreement."
                ),
                value=walker,
            )
        elif latest.value >= 1.0:
            _add(
                out,
                code="warm_but_uncoupled",
                level=WATCH,
                title="Ocean warm but atmosphere lagging",
                detail=(
                    f"Nino-3.4 is well above threshold while the Walker index is "
                    f"only {walker:+.2f} sigma. Teleconnections need the atmospheric "
                    "response, so impacts may underperform the SST anomaly."
                ),
                value=walker,
            )

        if atmosphere_state.burst_count_12mo >= 3:
            _add(
                out,
                code="westerly_forcing",
                level=WATCH,
                title="Repeated westerly wind forcing over the warm pool",
                detail=(
                    f"{atmosphere_state.burst_count_12mo} months in the last year "
                    "averaged strongly westerly at 850 hPa in the western Pacific, "
                    "which is how downwelling Kelvin waves get launched."
                ),
                value=float(atmosphere_state.burst_count_12mo),
            )

    # -- forecast ------------------------------------------------------------
    if forecast_result is not None and forecast_result.peak is not None:
        peak = forecast_result.peak
        probability = forecast_result.peak_probability
        if probability.get(2.5, 0.0) >= 0.5:
            _add(
                out,
                code="forecast_historic",
                level=CRITICAL,
                title="More likely than not to reach historic intensity",
                detail=(
                    f"Ensemble peak {peak.mean:+.2f} degC at {peak.label}, with "
                    f"{probability[2.5]:.0%} probability of exceeding +2.5 degC - "
                    "a level reached only in 1982-83, 1997-98 and 2015-16."
                ),
                value=peak.mean,
            )
        elif probability.get(2.0, 0.0) >= 0.5:
            _add(
                out,
                code="forecast_very_strong",
                level=WARNING,
                title="Projected to peak in very strong territory",
                detail=(
                    f"Ensemble peak {peak.mean:+.2f} degC at {peak.label}, "
                    f"{probability[2.0]:.0%} probability of exceeding +2.0 degC."
                ),
                value=peak.mean,
            )
        if peak.spread >= 0.75:
            _add(
                out,
                code="method_disagreement",
                level=INFO,
                title="Forecast methods disagree at the projected peak",
                detail=(
                    f"Method spread is {peak.spread:.2f} degC at {peak.label}: "
                    + ", ".join(
                        f"{name} {value:+.2f}" for name, value in sorted(peak.methods.items())
                    )
                    + ". Treat the central value with more caution than usual."
                ),
                value=peak.spread,
            )

    # -- integrity -----------------------------------------------------------
    try:
        centre = latest.centre
        age_days = (date.today() - centre).days
        if age_days > STALE_DAYS + 60:
            _add(
                out,
                code="oni_stale",
                level=WARNING,
                title="ONI has not updated",
                detail=(
                    f"The newest ONI season is {latest.label}, centred "
                    f"{age_days} days ago. CPC normally posts early each month - "
                    "check whether the feed has moved or stalled."
                ),
                value=float(age_days),
                kind="integrity",
            )
    except (ValueError, TypeError):
        pass

    if fetched:
        failed = [key for key, item in fetched.items() if not item.ok]
        cached = [
            key for key, item in fetched.items() if item.ok and item.from_cache
        ]
        if failed:
            critical_failed = [
                key for key in failed if getattr(fetched[key].source, "critical", False)
            ]
            _add(
                out,
                code="feeds_failed",
                level=CRITICAL if critical_failed else WATCH,
                title=f"{len(failed)} feed(s) unavailable",
                detail=(
                    "No data and no cache for: " + ", ".join(sorted(failed)) + "."
                    + (
                        " These include feeds the analysis depends on."
                        if critical_failed
                        else " The analysis continues without them."
                    )
                ),
                value=float(len(failed)),
                kind="integrity",
            )
        if cached:
            _add(
                out,
                code="feeds_cached",
                level=INFO,
                title=f"{len(cached)} feed(s) served from cache",
                detail="Live fetch failed for: " + ", ".join(sorted(cached)) + ".",
                value=float(len(cached)),
                kind="integrity",
            )

    # -- change against the previous run -------------------------------------
    if previous is not None:
        before = previous.get("status")
        if before and assessment.status and before != assessment.status:
            _add(
                out,
                code="cpc_status_change",
                level=WARNING,
                title="CPC advisory status changed",
                detail=f"Was '{before}', now '{assessment.status}'.",
                kind="change",
            )
        prior_oni = previous.get("oni")
        if prior_oni is not None and abs(latest.value - prior_oni) >= 0.15:
            _add(
                out,
                code="oni_moved",
                level=INFO,
                title="ONI changed since the last run",
                detail=(
                    f"{prior_oni:+.2f} to {latest.value:+.2f} degC. A change this "
                    "size between runs usually means a new month posted, but it can "
                    "also be a revision to an existing season."
                ),
                value=latest.value - prior_oni,
                kind="change",
            )

    return out


def reconcile(conn, alerts: list[Alert], seen_at: str) -> AlertSet:
    """Persist the alerts, marking which are new and closing the rest."""
    from . import storage

    ordered = sorted(alerts, key=lambda alert: (alert.rank, alert.code))
    for alert in ordered:
        alert.is_new = storage.upsert_alert(
            conn, alert.code, alert.level, alert.title, alert.detail, alert.value, seen_at
        )
        alert.first_seen = seen_at if alert.is_new else None

    open_rows = {row["code"]: row for row in storage.open_alerts(conn)}
    for alert in ordered:
        row = open_rows.get(alert.code)
        if row is not None:
            alert.first_seen = row["first_seen"]

    cleared = storage.clear_missing_alerts(conn, {a.code for a in ordered}, seen_at)
    return AlertSet(alerts=ordered, cleared=cleared)


def since(first_seen: str | None) -> str:
    """Human phrasing for how long an alert has been open."""
    if not first_seen:
        return ""
    try:
        started = datetime.fromisoformat(first_seen)
    except ValueError:
        return ""
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - started
    if delta < timedelta(hours=23):
        return "raised today"
    days = delta.days
    return f"open {days} day{'s' if days != 1 else ''}"
