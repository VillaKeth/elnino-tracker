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

import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from .classify import displayed, find_episodes
from .svg import signed
from .winds import EQUATORIAL, HV97_EVENTS, HV97_LONGEST, REGIONS_BY_KEY, THRESHOLD

INFO = "info"
WATCH = "watch"
WARNING = "warning"
CRITICAL = "critical"

LEVEL_ORDER = {CRITICAL: 0, WARNING: 1, WATCH: 2, INFO: 3}

# Official-index values worth announcing a crossing of, compared with the value
# CPC prints. Only the highest one crossed is raised: three alerts saying the
# same number is one alert and two echoes.
INDEX_STEPS: tuple[tuple[float, str, str], ...] = (
    (0.5, WATCH, "El Nino threshold"),
    (1.0, WATCH, "Moderate El Nino"),
    (1.5, WARNING, "Strong El Nino"),
    (2.0, WARNING, "Very strong El Nino"),
    (2.5, CRITICAL, "Historic territory"),
)

STALE_DAYS = 45  # an index this old means the monthly update was missed

# How long an alert's news stays on it: that it was raised, raised a level, or
# cleared. Marked on its run alone, it was on the site ten minutes at the live
# run's cadence; a day, it stays a day whatever the cadence, as what changed
# does (the change rules' baseline).
NEWS = timedelta(hours=24)

# The alerts the rules raise as rungs of one ladder, lowest first: one rung at
# a time, the highest that holds, each implying those below it. A storm's
# strength (its tc_hurricane_ and tc_major_) and the index's steps (index_ge_)
# are ladders too. Up a ladder, the higher rung is new and the one it leaves
# has not cleared, since its condition still holds; down, the lower rung
# stands since the ladder was first raised, and the one it leaves has cleared.
# As alerts of their own, EP21's hurricane alert was listed as cleared for a
# day while it was a major hurricane (16 October 2026).
LADDERS = (
    ("episode_forming", "episode_qualified"),
    ("top3_season", "record_season"),
    ("wwv_top5", "wwv_record"),
    ("walker_coupled", "walker_extreme"),
    ("forecast_very_strong", "forecast_historic"),
)


@dataclass
class Alert:
    code: str
    level: str
    title: str
    detail: str
    value: float | None = None
    kind: str = "state"
    is_new: bool = False  # raised in the day before this run (NEWS)
    first_seen: str | None = None
    # The level it rose from in the day before this run, while it stays above.
    escalated_from: str | None = None

    @property
    def rank(self) -> int:
        return LEVEL_ORDER.get(self.level, 9)

    @property
    def news(self) -> list[str]:
        """What is news of it, as the report and the console say it: NEW, the
        level it rose from, or both, when it rose in the day it was raised."""
        said = ["NEW"] if self.is_new else []
        if self.escalated_from:
            said.append(f"ESCALATED from {self.escalated_from.upper()}")
        return said


@dataclass
class AlertSet:
    alerts: list[Alert] = field(default_factory=list)
    # The codes of the alerts cleared in the day before this run, the latest
    # first, but those raised again since; and each one's title as it last
    # stood, for the page, which names alerts by title.
    cleared: list[str] = field(default_factory=list)
    cleared_titles: dict[str, str] = field(default_factory=dict)

    @property
    def new(self) -> list[Alert]:
        return [alert for alert in self.alerts if alert.is_new]

    @property
    def cleared_named(self) -> list[str]:
        """The cleared alerts by title, as the page and the report name the
        open ones; a code with no title stands for itself."""
        return [self.cleared_titles.get(code, code) for code in self.cleared]

    @property
    def worst(self) -> str:
        return min((a.level for a in self.alerts), key=lambda l: LEVEL_ORDER[l], default=INFO)

    def by_level(self, level: str) -> list[Alert]:
        return [alert for alert in self.alerts if alert.level == level]


def _add(out: list[Alert], **kwargs) -> None:
    out.append(Alert(**kwargs))


def _precedent(assessment, threshold: float) -> str:
    """What the record says about a level, read off the record.

    Stated from the official index's own history rather than from memory: on
    RONI no season has reached +2.5 since 1950, and a sentence naming the
    events that "reached" it would be quoting a different index.
    """
    series = assessment.index_series
    name = assessment.index_name
    if not series:
        return f"a level with no {name} record to compare it with."
    reached = [episode.name for episode in find_episodes(series, warm=True)
               if episode.qualifies and displayed(episode.peak.value) >= threshold]
    if reached:
        return (f"a level {name} has reached only in " + ", ".join(reached)
                + f" since {series[0].year}.")
    record = max(series, key=lambda season: season.value)
    return (f"a level {name} has not reached since {series[0].year}: its highest "
            f"season is {signed(displayed(record.value), 1)} degC, {record.label}.")


def evaluate(
    assessment,
    subsurface_state=None,
    atmosphere_state=None,
    forecast_result=None,
    fetched: dict | None = None,
    baseline=None,
    storms=None,
    now: str | None = None,
    winds=None,
) -> list[Alert]:
    """Run every rule against the current state, as of ``now`` (the run's
    time, ISO 8601), with the westerly wind events, ``winds``, when their feed
    came, and the state a day before it, ``baseline`` (``storage.baseline``),
    for what changed. Ordering happens later."""
    out: list[Alert] = []
    latest = assessment.index_latest
    name_of_index = assessment.index_name
    printed = displayed(latest.value)

    # -- state: how big is it, right now ------------------------------------
    crossed = [step for step in INDEX_STEPS if printed >= step[0]]
    if crossed:
        threshold, level, name = crossed[-1]
        _add(
            out,
            code=f"index_ge_{threshold:.1f}",
            level=level,
            title=f"{name_of_index} at or above +{threshold:.1f} degC - {name}",
            detail=(
                f"{latest.label} {name_of_index} is {signed(latest.value, 2)} degC, "
                f"which CPC prints as {signed(printed, 1)}: {assessment.index_tier} "
                "conditions this season. An event's category is set by its "
                "peak, which is still ahead of it while it is building."
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
                f"{assessment.episode.length} consecutive overlapping seasons of "
                f"{name_of_index} at or above +0.5 degC, from "
                f"{assessment.episode.onset.label}. NOAA's five-season rule is "
                "satisfied."
            ),
            value=float(assessment.episode.length),
        )
    elif assessment.seasons_at_threshold >= 3:
        _add(
            out,
            code="episode_forming",
            level=WATCH,
            title="El Nino conditions present, episode not yet formal",
            detail=assessment.episode_status,
            value=float(assessment.seasons_at_threshold),
        )

    ranking = assessment.index_ranking
    if ranking.rank_season == 1 and ranking.total_season >= 20:
        _add(
            out,
            code="record_season",
            level=CRITICAL,
            title=f"Warmest {latest.season} on record",
            detail=(
                f"{signed(latest.value, 2)} degC is the highest {latest.season} "
                f"{name_of_index} in {ranking.total_season} years of record."
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
                f"calendar season on {name_of_index}."
            ),
            value=latest.value,
        )

    # ONI and RONI disagreeing matters: it says how much of the anomaly is the
    # Pacific doing something and how much is a warmer ocean everywhere.
    oni, roni = assessment.oni_latest, assessment.roni_latest
    if roni is not None and oni is not None and oni.label == roni.label:
        divergence = oni.value - roni.value
        if abs(divergence) >= 0.4:
            _add(
                out,
                code="roni_divergence",
                level=INFO,
                title="Legacy ONI and official RONI diverging",
                detail=(
                    f"ONI {signed(oni.value, 2)} against RONI {signed(roni.value, 2)}, a gap "
                    f"of {signed(divergence, 2)} degC. That much of the raw anomaly is "
                    "the whole tropical ocean running warm rather than the "
                    "Pacific, which is why CPC has classified on RONI since "
                    "February 2026."
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
                f"{name_of_index} rose {signed(momentum.season_delta, 2)} degC from the "
                f"previous season ({momentum.direction})."
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
                f"Weekly Nino-3.4 has risen {signed(momentum.weekly_delta, 2)} degC over "
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
                    f"{state.latest.label} WWV anomaly is {signed(state.anomaly, 2)} "
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
                    f"{signed(state.anomaly, 2)} x10^14 m3."
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
                    f"WWV is {signed(state.tendency, 3)} x10^14 m3 per month and still "
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
                    f"Composite atmospheric index {signed(walker, 2)} sigma across "
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
                    f"Composite atmospheric index {signed(walker, 2)} sigma, with "
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
                    f"only {signed(walker, 2)} sigma. Teleconnections need the atmospheric "
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

    # -- westerly wind events, day by day ------------------------------------
    if winds is not None:
        out.extend(wind_rules(winds))

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
                    f"Ensemble peak {signed(peak.mean, 2)} degC at {peak.label}, with "
                    f"{probability[2.5]:.0%} probability of reaching +2.5 degC - "
                    + _precedent(assessment, 2.5)
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
                    f"Ensemble peak {signed(peak.mean, 2)} degC at {peak.label}, "
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
                        f"{name} {signed(value, 2)}" for name, value in sorted(peak.methods.items())
                    )
                    + ". Treat the central value with more caution than usual."
                ),
                value=peak.spread,
            )

    # -- integrity -----------------------------------------------------------
    try:
        centre = latest.centre
        today = (datetime.fromisoformat(now) if now else datetime.now(timezone.utc)).date()
        age_days = (today - centre).days
        if age_days > STALE_DAYS + 60:
            _add(
                out,
                code="index_stale",
                level=WARNING,
                title=f"{name_of_index} has not updated",
                detail=(
                    f"The newest {name_of_index} season is {latest.label}, centred "
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
                title=f"{len(failed)} feed{'s' if len(failed) != 1 else ''} unavailable",
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
                title=(f"{len(cached)} feed{'s' if len(cached) != 1 else ''} "
                       "served from cache"),
                detail="Live fetch failed for: " + ", ".join(sorted(cached)) + ".",
                value=float(len(cached)),
                kind="integrity",
            )

    # -- change against the state a day before -------------------------------
    # Not the run before: a change would be on the site only until the next
    # run. Each says the time of the state it is against, which is a day before
    # unless the record is younger, or has a gap.
    if baseline is not None:
        then = utc_time(baseline.run_at)
        before = baseline.get("status")
        if before and assessment.status and before != assessment.status:
            _add(
                out,
                code="cpc_status_change",
                level=WARNING,
                title="CPC advisory status changed",
                detail=f"Was '{before}' at {then}, now '{assessment.status}'.",
                kind="change",
            )
        prior = baseline.get(name_of_index.lower())
        if prior is not None and abs(latest.value - prior) >= 0.15:
            _add(
                out,
                code="index_moved",
                level=INFO,
                title=f"{name_of_index} changed since {then}",
                detail=(
                    f"{signed(prior, 2)} then, {signed(latest.value, 2)} degC now. A change this "
                    "size usually means a new month posted, but it can also be a "
                    "revision to an existing season."
                ),
                value=latest.value - prior,
                kind="change",
            )

    if storms is not None and storms.available:
        out.extend(cyclone_rules(storms))
        out.extend(product_rules(storms, now))

    return out


def wind_rules(winds) -> list[Alert]:
    """An INFO alert for each equatorial region's westerly wind event under
    way, as Harrison and Vecchi (1997) define one, from CCMP's near-real-time
    winds, raised on every run until the event ends. Events off the equator,
    finished ones and runs still building raise nothing."""
    out: list[Alert] = []
    for event in winds.under_way:
        if event.region not in EQUATORIAL:
            continue
        region = REGIONS_BY_KEY[event.region]
        before = event.from_start
        sustained = (f"; longer than any of the {HV97_EVENTS} events in Harrison and Vecchi's "
                     f"1986-1995 list (at most {HV97_LONGEST:g} days): a sustained westerly "
                     "anomaly more than a burst") if event.sustained else ""
        counts = ("" if event.counted_as == event.region
                  else f"; it counts as the stronger {event.counted_as} event it overlaps")
        _add(
            out,
            code=f"wwe_{event.region.lower()}",
            level=INFO,
            title=f"Westerly wind event under way: {region.name} region, {region.span}",
            detail=(
                f"{'at least ' if before else ''}{event.days:g} days above "
                f"{signed(THRESHOLD, 0)} m/s since {'before ' if before else ''}"
                f"{event.first:%Y-%m-%d %HZ} in CCMP's near-real-time winds to "
                f"{winds.last}, peaking at {signed(event.peak, 1)} m/s on "
                f"{event.centre:%Y-%m-%d}{sustained}{counts}. Equatorial westerly anomalies "
                "force downwelling Kelvin waves east."
            ),
            value=round(event.peak, 2),
        )
    return out


# Distances at which a forecast track stops being weather and starts being a
# decision. The centre line is not the storm - hurricane-force winds reach
# 100 km either side of a large one and tropical-storm force twice that - so
# these are deliberately wider than the radii they are named for.
STRIKE_KM = 150.0
BRUSH_KM = 350.0
# Weeks of lead time are the whole point of the tier, so a threat is worth
# raising out to the end of the official forecast even when it is five days off.
THREAT_HOURS = 120


def cyclone_rules(storms) -> list[Alert]:
    """Storm rules: what is out there, what it is doing, and who it is near.

    These are the only rules in this module that can fire on something that
    did not exist yesterday. An ONI alert describes a boundary condition that
    moves over months; a cyclone alert describes an object that can go from
    nothing to Category 4 in the thirty-six hours between two runs, which is
    precisely what the storm that prompted this tier did.
    """
    from . import cyclones

    out: list[Alert] = []
    for storm in storms.active:
        now = storm.latest
        if now is None:
            continue
        where = storm.nearest_land
        near = (f" Nearest land is {where[1].name}, {where[1].country}, "
                f"{where[0]:.0f} km away." if where else " It is over open ocean.")

        if now.category >= 3:
            level = CRITICAL if now.category >= 4 else WARNING
            # JTWC's storms are typhoons and cyclones, not hurricanes.
            noun = {"TY": "typhoon", "ST": "typhoon", "TC": "cyclone"}.get(now.stage,
                                                                         "hurricane")
            _add(
                out,
                code=f"tc_major_{storm.key}",
                level=level,
                title=f"{storm.title}: major {noun}, {now.label}",
                detail=(
                    f"{now.wind} kt sustained, {now.pressure or 0} mb, at "
                    f"{_pos(now)} in the {storm.basin_name}.{near}"
                ),
                value=float(now.wind or 0),
            )
        elif now.category >= 1:
            _add(
                out,
                code=f"tc_hurricane_{storm.key}",
                level=WATCH,
                title=f"{storm.title}: {now.label}",
                detail=f"{now.wind} kt at {_pos(now)}.{near}",
                value=float(now.wind or 0),
            )

        change, when = storm.rapid
        if change >= cyclones.RI_THRESHOLD:
            _add(
                out,
                code=f"tc_ri_{storm.key}",
                level=WARNING if change < 50 else CRITICAL,
                title=f"{storm.title}: rapid intensification, {signed(change, 0)} kt in 24 h",
                detail=(
                    f"NHC calls 30 kt in 24 hours rapid intensification; this is "
                    f"{change:.0f}, through {_stamp(when)}. Forecast intensity error "
                    "is at its largest exactly here, so treat the official "
                    "intensity forecast as a floor rather than a centre."
                ),
                value=change,
                kind="change",
            )

        for gap, fix, place in storm.threats(BRUSH_KM):
            if fix.tau > THREAT_HOURS or (fix.wind or 0) < 34:
                continue
            strike = gap <= STRIKE_KM
            spread = storm.spread_near(fix.tau)
            level = (CRITICAL if strike and fix.category >= 1
                     else WARNING if strike or fix.category >= 3
                     else WATCH)
            code = f"tc_threat_{storm.key}_{place.name.lower().replace(' ', '_')}"
            if fix.tau == 0:
                # Closest now: the analysis is an observation, so there is no
                # forecast spread to quote, and "passes in 0 h" is not a pass.
                _add(
                    out, code=code, level=level,
                    title=(f"{storm.title} is {gap:.0f} km from {place.name} "
                           f"now, moving away"),
                    detail=(
                        f"The {_stamp(fix.stamp)} analysis has it as a "
                        f"{fix.label} at {fix.wind} kt, {gap:.0f} km from "
                        f"{place.name}, {place.country}, and the official "
                        "forecast takes it further away from here on. This is "
                        "a centre-line distance; the wind field is wider than "
                        "the line."
                    ),
                    value=gap,
                )
                continue
            _add(
                out,
                code=code,
                level=level,
                title=(
                    f"{storm.title} passes {gap:.0f} km from {place.name} "
                    f"in {fix.tau} h ({_valid(fix)})"
                ),
                detail=(
                    f"Official forecast has it as a {fix.label} at {fix.wind} kt "
                    f"on approach to {place.name}, {place.country}, "
                    f"{fix.tau} h after the {_stamp(fix.stamp)} analysis. This is "
                    f"a centre-line distance; the wind field is wider than the "
                    f"line. Track spread across the "
                    f"{'ensemble' if storm.ensemble else 'guidance'} at "
                    + (f"+{spread[0]} h is {spread[1]:.0f} km, the "
                       f"{'members' if storm.ensemble else 'models'}' mean "
                       "distance from their mean position."
                       if spread else "that range is not available.")
                ),
                value=gap,
            )

    for basin, season in storms.basins.items():
        ratio = season.ace_ratio
        if ratio is None:
            continue
        if ratio >= 1.5:
            _add(
                out,
                code=f"tc_season_hot_{basin}",
                level=WATCH,
                title=f"{season.name}: {ratio:.1f}x normal activity for the date",
                detail=(
                    f"{season.ace:.0f} units of accumulated cyclone energy against "
                    f"{season.normal_ace:.0f} for a normal season by {season.through}. "
                    f"{season.named} named storms, {season.hurricanes} hurricanes, "
                    f"{season.major} major."
                ),
                value=ratio,
            )
        elif ratio <= 0.5:
            _add(
                out,
                code=f"tc_season_quiet_{basin}",
                level=INFO,
                title=f"{season.name}: {ratio:.2f}x normal activity for the date",
                detail=(
                    f"{season.ace:.0f} units against {season.normal_ace:.0f} normal "
                    f"by {season.through}. A suppressed basin is the expected "
                    "signature of El Nino in the Atlantic, and it is not a reason "
                    "to relax: 1992 was a quiet season and it produced Andrew."
                ),
                value=ratio,
            )
    return out


# How loudly each official product speaks. A warning means the conditions
# are expected in the area, a watch that they are possible; both are issued
# ahead of the tropical-storm-force wind (36 and 48 hours), because getting
# ready becomes difficult once it arrives.
PRODUCT_LEVEL = {
    "Hurricane Warning": CRITICAL,
    "Hurricane Watch": WARNING,
    "Tropical Storm Warning": WARNING,
    "Tropical Storm Watch": WATCH,
}
PRODUCT_MEANING = {
    "Hurricane Warning": ("Hurricane conditions (64 kt or more) are expected in the "
                          "area; warnings go out 36 hours before tropical-storm-force "
                          "wind is expected to arrive."),
    "Hurricane Watch": ("Hurricane conditions are possible in the area; watches go "
                        "out 48 hours before tropical-storm-force wind is expected."),
    "Tropical Storm Warning": ("Tropical storm conditions (34 to 63 kt) are expected "
                               "in the area within 36 hours."),
    "Tropical Storm Watch": ("Tropical storm conditions are possible in the area "
                             "within 48 hours."),
}
# NHC calls a seven-day formation chance above 60 percent high.
FORMATION_HIGH = 60
# A breakpoint is named after the nearest town within this distance.
NAMING_KM = 150.0
# Round an island a watch is a loop, drawn back to where it began or to within
# a few kilometres of it: CPHC's round the Big Island on 25 September 2026
# ended 6 km from its start.
LOOP_KM = 25.0
# A stretch is named from one town to another only where each end is this
# close to its town; farther, the town can be on another coast. Molokai's
# line ended 48 km from Honolulu, which was under nothing.
ENDS_KM = 40.0


def product_rules(storms, now: str | None = None) -> list[Alert]:
    """Alerts from what the warning centres issued, one per storm and product.

    The centres' own calls outrank anything this system derives: a watch or
    warning is raised at the level its definition implies, and names the
    stretch of coast it covers and the advisory it came from. A formation
    area is raised when NHC puts its seven-day chance above 60 percent or
    JTWC rates its potential high; a formation alert whose time has come by
    ``now`` with nothing newer read is said to have run out.
    """
    from . import cyclones
    from .outlook import utc

    out: list[Alert] = []
    for storm in storms.active:
        products = getattr(storm, "products", None)
        if products is None:
            continue
        # Where the public advisory came, its own words say where each is in
        # effect, and what it lists is in effect though the lines did not
        # come; elsewhere the lines name the coast.
        said = dict(getattr(products, "in_effect", None) or ())
        by_kind: dict[str, list] = {}
        for segment in products.watches or ():
            by_kind.setdefault(segment.kind, []).append(segment)
        # The centre that wrote them: CPHC's past 140W.
        centre = cyclones.issuing_centre(storm) if by_kind or said else ""
        for kind in dict.fromkeys([*by_kind, *said]):
            level = PRODUCT_LEVEL.get(kind)
            if level is None:
                continue
            if kind in said:
                number = products.own("in_effect") or products.advisory
                where = "for " + "; ".join(_in_a_sentence(area) for area in said[kind])
                count = len(said[kind])
            else:
                segments = by_kind[kind]
                number = products.own("watches") or products.advisory
                where = "; ".join(_coasts(segments)) + (
                    f", in {len(segments)} stretches" if len(segments) > 1 else "")
                count = len(segments)
            _add(
                out,
                code=f"tc_ww_{storm.key}_{kind.lower().replace(' ', '_')}",
                level=level,
                title=f"{storm.title}: {kind} in effect",
                detail=(f"{centre} advisory {number}: a {kind} is in effect {where}. "
                        f"{PRODUCT_MEANING[kind]}"),
                value=float(count),
            )

    for area in getattr(storms, "outlook", None) or []:
        if area.centre == "JTWC":
            if area.potential != "high":
                continue
            title = f"{area.label}: high potential for a tropical cyclone within 24 h"
            detail = (f"JTWC's advisory of {_issued(area.issued) or 'this run'} places it near "
                      f"{_latlon(area.lon, area.lat)} and rates the potential for a "
                      "significant tropical cyclone within 24 hours high.")
            if area.alert:
                formation = getattr(area, "formation", None)
                facts = formation.facts() if formation else []
                if formation and formation.lapsed(now):
                    detail += (f" JTWC's formation alert ran to {utc(formation.until)}, the "
                               "time it was to be reissued, upgraded to a warning or "
                               "cancelled by, and nothing newer from JTWC has been read."
                               + (" It said: " + ", ".join(facts) + "." if facts else ""))
                else:
                    detail += (" A tropical cyclone formation alert is in effect"
                               + (f" until {utc(formation.until)}"
                                  if formation and formation.until else "")
                               + (": " + ", ".join(facts) if facts else "") + ".")
        else:
            if area.chance_7day is None or area.chance_7day <= FORMATION_HIGH:
                continue
            title = (f"{area.label}: {area.chance_7day}% chance of a tropical "
                     "cyclone within 7 days")
            words = re.sub(r"^\d+\.\s*[^:]*:\s*", "", area.text)
            detail = (f"{area.centre}'s outlook of {_issued(area.issued) or 'this run'}: "
                      f"{area.chance_2day}% within 48 hours, {area.chance_7day}% "
                      f"within 7 days. {words}")
        _add(out, code=f"tc_formation_{area.key}", level=WATCH, title=title,
             detail=detail, value=float(area.chance_7day or 0))
    return out


def _in_a_sentence(area: str) -> str:
    """An area as the advisory lists it, inside a sentence: "the Cabo Verde Islands"."""
    return "the " + area[4:] if area.startswith("The ") else area


def _coast(segments) -> str:
    """The stretch of coast a set of segments covers, in towns."""
    return _named(segments)[0]


def _coasts(segments) -> list[str]:
    """Each segment's stretch of coast, leaving out one that names no new town.

    Round a group of islands several short stretches of one warning can fall
    nearest the same town, and named one by one they repeat it.
    """
    out: list[str] = []
    seen: set[str] = set()
    for segment in segments:
        phrase, towns = _named([segment])
        if not set(towns) <= seen:
            out.append(phrase)
            seen.update(towns)
    return out


def _named(segments) -> tuple[str, tuple[str, ...]]:
    """The stretch of coast a set of segments covers, and the towns that name it.

    A mainland segment runs breakpoint to breakpoint and is named by its two
    ends, where each is close to a town; otherwise by the town nearest its
    middle. Round an island it is a loop back to where it began, so it is
    named by the towns along it instead.
    """
    if all(_loop(seg) for seg in segments):
        towns: list[str] = []
        for seg in segments:
            step = max(1, len(seg.coords) // 12)
            for lon, lat in seg.coords[::step]:
                name = _town(lon, lat)
                if name not in towns:
                    towns.append(name)
        named = [t for t in towns if not t[:1].isdigit()] or towns[:1]
        if len(named) == 1:
            return f"on the coast near {named[0]}", (named[0],)
        shown = named[:-1][:3] + named[-1:]
        return ("on the coasts near " + ", ".join(shown[:-1]) + f" and {shown[-1]}",
                tuple(shown))
    ends = (_nearest(*segments[0].coords[0]), _nearest(*segments[-1].coords[-1]))
    if all(end is not None and end[0] <= ENDS_KM for end in ends):
        start, end = ends[0][1].name, ends[1][1].name
        if start != end:
            return f"from {start} to {end}", (start, end)
    town = _town(*_middle(segments))
    return f"near {town}", (town,)


def _loop(segment) -> bool:
    """Whether a line goes round an island, back to where it began."""
    from .cyclones import great_circle

    points = segment.coords
    if points[0] == points[-1]:
        return True
    gap = great_circle(*points[0], *points[-1])
    length = sum(great_circle(*a, *b) for a, b in zip(points, points[1:]))
    # A short line's ends are close too; a loop goes somewhere and comes back.
    return gap <= LOOP_KM and length >= 4 * gap


def _middle(segments) -> tuple[float, float]:
    """The point halfway along a stretch of coast."""
    from .cyclones import great_circle

    points = [point for seg in segments for point in seg.coords]
    legs = list(zip(points, points[1:]))
    half = sum(great_circle(*a, *b) for a, b in legs) / 2.0
    for a, b in legs:
        km = great_circle(*a, *b)
        if km > 0 and half <= km:
            share = half / km
            return (a[0] + (b[0] - a[0]) * share, a[1] + (b[1] - a[1]) * share)
        half -= km
    return points[len(points) // 2]


def _latlon(lon: float, lat: float) -> str:
    lon = (lon + 180.0) % 360.0 - 180.0
    return (f"{abs(lat):.1f}{'N' if lat >= 0 else 'S'} "
            f"{abs(lon):.1f}{'W' if lon < 0 else 'E'}")


def _nearest(lon: float, lat: float):
    """The nearest gazetteer town to a point and its distance, (km, place), or None."""
    from . import atlasdata
    from .cyclones import great_circle

    best = None
    for place in atlasdata.PLACES:
        if abs(place.lat - lat) > 2.0 or abs((place.lon - lon + 180.0) % 360.0 - 180.0) > 2.5:
            continue
        km = great_circle(lon, lat, place.lon, place.lat)
        if best is None or km < best[0]:
            best = (km, place)
    return best


def _town(lon: float, lat: float) -> str:
    """The nearest gazetteer town to a breakpoint, or its position if none is near."""
    best = _nearest(lon, lat)
    if best is None or best[0] > NAMING_KM:
        return _latlon(lon, lat)
    return best[1].name


def _pos(fix) -> str:
    return (f"{abs(fix.lat):.1f}{'N' if fix.lat >= 0 else 'S'} "
            f"{abs(fix.lon):.1f}{'W' if fix.lon < 0 else 'E'}")


def utc_time(stamp: str) -> str:
    """A run's time as the alerts say it: 15 Oct 2026 13:30 UTC. One without
    a zone is UTC, as the record's are, and so is one in "Z", as JTWC's are,
    which Python reads only from 3.11."""
    try:
        moment = datetime.fromisoformat(stamp[:-1] + "+00:00" if stamp.endswith("Z") else stamp)
    except (AttributeError, TypeError, ValueError):
        return str(stamp)
    if moment.tzinfo is not None:
        moment = moment.astimezone(timezone.utc)
    return f"{moment.day} {moment:%b %Y %H:%M} UTC"


def _issued(text: str) -> str:
    """An outlook's issue time as the alerts give every time, 20 Oct 2026
    11:52 UTC: from the time NHC names its outlook document with,
    "Tue Oct 20 11:52:05 2026", in UTC, or an ISO time; else as written."""
    try:
        return utc_time(datetime.strptime(text.strip(), "%a %b %d %H:%M:%S %Y").isoformat())
    except (AttributeError, ValueError):
        return utc_time(text) if text else ""


def _stamp(atcf: str) -> str:
    return (f"{atcf[:4]}-{atcf[4:6]}-{atcf[6:8]} {atcf[8:10]}Z"
            if len(atcf) == 10 else atcf)


def _valid(fix) -> str:
    """A forecast fix's valid time, the way an advisory writes it: 18Z 24 Sep."""
    from datetime import datetime

    from .cyclones import valid_stamp

    when = datetime.strptime(valid_stamp(fix), "%Y%m%d%H")
    return f"{when:%H}Z {when.day} {when:%b}"


def reconcile(conn, alerts: list[Alert], seen_at: str) -> AlertSet:
    """Persist the alerts, close the rest, and mark the news of the day before
    ``seen_at`` (NEWS): which were raised, which raised a level, which
    cleared."""
    from . import storage

    ordered = sorted(alerts, key=lambda alert: (alert.rank, alert.code))
    before = {row["code"]: row for row in storage.open_alerts(conn)}
    for alert in ordered:
        storage.upsert_alert(conn, alert.code, alert.level, alert.title, alert.detail,
                             alert.value, seen_at)
        # A standing alert that got worse is news even though its condition
        # is not: a threat that was a watch yesterday and a strike today.
        was = before.get(alert.code)
        if was is not None and alert.rank < LEVEL_ORDER.get(was["level"], 9):
            storage.raise_alert(conn, alert.code, was["level"], seen_at)
    raised = {alert.code for alert in ordered}
    storage.clear_missing_alerts(conn, raised, seen_at)
    left = [row for code, row in before.items() if code not in raised]
    for alert in ordered:
        if alert.code not in before:
            _step(conn, alert, left, seen_at)

    open_rows = {row["code"]: row for row in storage.open_alerts(conn)}
    for alert in ordered:
        row = open_rows[alert.code]
        alert.first_seen = row["first_seen"]
        alert.is_new = _news(row["first_seen"], seen_at)
        rose = row["raised_from"]
        alert.escalated_from = (rose if rose and _news(row["raised_at"], seen_at)
                                and alert.rank < LEVEL_ORDER.get(rose, 9) else None)
    cleared, titles = [], {}
    for row in storage.cleared_since(conn, seen_at, NEWS):
        code = row["code"]
        if (code not in open_rows and code not in cleared and _news(row["cleared_at"], seen_at)
                and not _held(code, open_rows)):
            cleared.append(code)
            titles[code] = row["title"]
    return AlertSet(alerts=ordered, cleared=cleared, cleared_titles=titles)


def rung(code: str) -> tuple[str, float] | None:
    """The ladder an alert's code is a rung of (LADDERS) and how high on it,
    or None for an alert on none."""
    for prefix, height in (("tc_hurricane_", 1.0), ("tc_major_", 2.0)):
        if code.startswith(prefix):
            return "tc_strength_" + code[len(prefix):], height
    if code.startswith("index_ge_"):
        try:
            return "index_ge", float(code[len("index_ge_"):])
        except ValueError:
            return None
    for rungs in LADDERS:
        if code in rungs:
            return rungs[0], float(rungs.index(code))
    return None


def _step(conn, alert: Alert, left, seen_at: str) -> None:
    """An alert raised in place of a rung of its ladder that stood before this
    run, one of those ``left``: up, it is new, notes since when the ladder has
    stood, and a level it rose is said; down, it stands since then."""
    from . import storage

    step = rung(alert.code)
    if step is None:
        return
    for row in left:
        other = rung(row["code"])
        if other is None or other[0] != step[0]:
            continue
        since = row["ladder_since"] or row["first_seen"]
        if step[1] > other[1]:
            storage.step_alert(conn, alert.code, ladder_since=since)
            if alert.rank < LEVEL_ORDER.get(row["level"], 9):
                storage.raise_alert(conn, alert.code, row["level"], seen_at)
        else:
            storage.step_alert(conn, alert.code, first_seen=since)
        return


def _held(code: str, standing) -> bool:
    """Whether a higher rung of the ladder ``code`` is on is among the codes
    ``standing``: its condition then still holds, and it has not cleared."""
    step = rung(code)
    return step is not None and any(
        other is not None and other[0] == step[0] and other[1] > step[1]
        for other in map(rung, standing))


def _news(stamp, now: str) -> bool:
    """Whether the time ``stamp`` is no later than ``now`` and within NEWS
    before it. One without a zone is UTC, as the record's are."""
    try:
        then, at = datetime.fromisoformat(stamp), datetime.fromisoformat(now)
    except (TypeError, ValueError):
        return False
    then, at = (moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc) for moment in (then, at))
    return timedelta(0) <= at - then < NEWS


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
