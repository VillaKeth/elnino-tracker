"""Terminal report: the whole assessment as plain text, safe for any console.

Two audiences, one document. The top third is written to be read in thirty
seconds by someone deciding whether to act - alerts, state, power, the peak
projection and its probabilities. Everything below it is the working that the
top third rests on, in the order a forecaster would want to interrogate it:
ocean first, then atmosphere, then the forecast, then how much that forecast
has historically been worth, then what past events like this one did, then the
hazard outlook, and finally the health of the data underneath it all.

Output is deliberately 7-bit ASCII at a fixed 78 columns, so it survives a
Windows console, an SSH session, a pasted email and a printer without a single
mojibake character. Degrees are written 'degC'.
"""

from __future__ import annotations

import textwrap
import unicodedata
from datetime import datetime, timezone

from . import grids, history
from .grids import lon_name as _lon_name
from .alerts import CRITICAL, INFO, WARNING, WATCH

WIDTH = 78
BAR_WIDTH = 32

LEVEL_MARK = {CRITICAL: "[!!!]", WARNING: "[!! ]", WATCH: "[!  ]", INFO: "[   ]"}

# Sections a caller can ask for by name. Order here is the order they print.
SECTIONS = (
    "alerts", "state", "cpc", "intensity", "spatial", "subsurface",
    "atmosphere", "forecast", "skill", "analogs", "impacts", "data",
)


def _ascii(text: str) -> str:
    """Strip anything a legacy console would render as garbage."""
    text = (
        text.replace("°C", "degC").replace("°", " deg")
        .replace("–", "-").replace("—", "-")
        .replace("‘", "'").replace("’", "'")
        .replace("“", '"').replace("”", '"')
        .replace("≥", ">=").replace("≤", "<=").replace("×", "x")
    )
    text = unicodedata.normalize("NFKD", text)
    return text.encode("ascii", "ignore").decode("ascii")


def _rule(char: str = "=") -> str:
    return char * WIDTH


def _heading(title: str) -> list[str]:
    return ["", title.upper(), _rule("-")]


def _wrap(text: str, indent: str = "  ", width: int = WIDTH) -> list[str]:
    return textwrap.wrap(
        _ascii(text), width=width, initial_indent=indent, subsequent_indent=indent
    ) or [indent.rstrip()]


def _bar(value: float, maximum: float = 100.0, width: int = BAR_WIDTH) -> str:
    filled = int(round(width * max(0.0, min(1.0, value / maximum))))
    return "#" * filled + "." * (width - filled)


def _signed_bar(value: float, limit: float = 3.0, width: int = 21) -> str:
    """A zero-centred bar. Used for standard scores that can go either way."""
    half = width // 2
    steps = int(round(half * max(-1.0, min(1.0, value / limit))))
    cells = ["."] * width
    cells[half] = "|"
    for offset in range(1, abs(steps) + 1):
        position = half + offset if steps > 0 else half - offset
        if 0 <= position < width:
            cells[position] = "#"
    return "".join(cells)


def _ordinal(n: int) -> str:
    if 10 <= n % 100 <= 20:
        return f"{n}th"
    return f"{n}{ {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th') }"


def _rank_phrase(rank: int, total: int, noun: str) -> str:
    if rank == 1:
        return f"the warmest of {total} {noun} on record"
    return f"{_ordinal(rank)} warmest of {total} {noun} on record"


def _ranking(r) -> str:
    """A Ranking rendered as the sentence a forecaster would actually say."""
    return (
        f"{_rank_phrase(r.rank_all, r.total_all, 'seasons')}; "
        f"{_ordinal(r.rank_season)} of {r.total_season} for {r.season} "
        f"({r.percentile_all:.0f}th percentile)"
    )


def _table(rows: list[tuple[str, ...]], widths: tuple[int, ...], indent: str = "  ") -> list[str]:
    out = []
    for row in rows:
        cells = []
        for cell, width in zip(row, widths):
            text = _ascii(str(cell))
            cells.append(text.rjust(-width) if width < 0 else text.ljust(width))
        out.append((indent + " ".join(cells)).rstrip())
    return out


# --------------------------------------------------------------------------
# sections
# --------------------------------------------------------------------------

def _section_alerts(state) -> list[str]:
    alert_set = state.alert_set
    if not alert_set.alerts and not alert_set.cleared:
        return []
    lines = _heading("alerts")
    if not alert_set.alerts:
        lines.append("  No open alerts.")
    for alert in alert_set.alerts:
        mark = LEVEL_MARK.get(alert.level, "[   ]")
        flag = "  NEW" if alert.is_new else ""
        lines.append(f"  {mark} {_ascii(alert.title)}{flag}")
        lines.extend(_wrap(alert.detail, indent="        "))
        if alert.first_seen and not alert.is_new:
            lines.append(f"        standing since {alert.first_seen[:10]}")
    if alert_set.cleared:
        lines.append("")
        lines.append(f"  Cleared this run: {', '.join(alert_set.cleared)}")
    return lines


def _section_state(state) -> list[str]:
    a = state.assessment
    lines = ["", _rule()]
    for line in _wrap(a.headline, indent="  "):
        lines.append(line)
    lines.append(_rule())
    lines.append("")
    if a.status:
        lines.append(f"  CPC STATUS   {_ascii(a.status)}")
    lines.append(f"  STATE        {_ascii(a.oni_tier)}")
    lines.append(
        f"  POWER        {a.power.value:.0f}/100  [{_bar(a.power.value)}]"
    )
    parts = "  ".join(
        f"{name}={value:.0f}" for name, value in sorted(a.power.components.items())
    )
    lines.append(f"               {parts}")
    lines.append(f"  TREND        {_ascii(a.momentum.direction)}")

    peak = state.forecast.peak if state.forecast else None
    if peak:
        probs = state.forecast.peak_probability
        lines.append(
            f"  PEAK (proj)  {peak.mean:+.2f} degC in {peak.label} "
            f"({peak.low:+.2f} to {peak.high:+.2f})"
        )
        ordered = sorted(probs.items())
        lines.append(
            "               "
            + "  ".join(f"P(>={t:.1f})={p * 100:.0f}%" for t, p in ordered)
        )
    if state.subsurface:
        s = state.subsurface
        lines.append(
            f"  SUBSURFACE   WWV {s.anomaly:+.2f} x10^14 m3, "
            f"rank {s.rank_alltime} of {s.total_alltime}, {_ascii(s.tendency_label)}"
        )
    if state.atmosphere and state.atmosphere.indicators:
        at = state.atmosphere
        coupled = "coupled" if at.coupled else "NOT yet coupled"
        lines.append(
            f"  ATMOSPHERE   Walker {at.walker_index:+.2f} sigma, {coupled}, "
            f"{at.agreement * 100:.0f}% of indicators agree"
        )
    if state.warnings:
        lines.append(f"  DATA         DEGRADED - {len(state.warnings)} problem(s), see end")
    return lines


def _section_cpc(state) -> list[str]:
    d = state.discussion or {}
    if not d.get("synopsis"):
        return []
    lines = _heading("noaa cpc official position")
    lines.append(f"  issued {_ascii(d.get('issued') or 'date not parsed')}")
    lines.append("")
    lines.extend(_wrap(d["synopsis"]))
    if d.get("next_update"):
        lines.append("")
        lines.append(f"  Next official discussion: {_ascii(d['next_update'])}")
    return lines


def _section_intensity(state) -> list[str]:
    a = state.assessment
    lines = _heading("intensity")
    lines.append(
        f"  ONI   {a.oni_latest.value:+.2f} degC  {a.oni_latest.label}   -> {_ascii(a.oni_tier)}"
    )
    if a.ranking:
        lines.extend(_wrap(_ranking(a.ranking), indent="        "))
    if a.roni_latest:
        lines.append(
            f"  RONI  {a.roni_latest.value:+.2f} degC  {a.roni_latest.label}   "
            f"-> {_ascii(a.roni_tier)}"
        )
        lines.append(
            "        RONI removes the tropical-mean warming trend. Where it is "
            "much"
        )
        lines.append(
            "        lower than ONI, part of the warmth is background, not Pacific."
        )
        if a.roni_ranking:
            lines.extend(_wrap(_ranking(a.roni_ranking), indent="        "))

    lines.append("")
    lines.extend(_wrap("Episode: " + a.episode_status, indent="  "))
    if a.episode:
        run = "  ".join(f"{v.season} {v.value:+.2f}" for v in a.episode.seasons[-6:])
        lines.append(f"  Run so far: {run}")

    if a.scale:
        lines.append("")
        lines.append("  Region anomalies (latest weekly observation):")
        rows = [("region", "anom", "SST", "")]
        for region in a.scale.regions:
            rows.append((
                region.label,
                f"{region.anomaly:+.1f}",
                f"{region.sst:.1f}",
                _signed_bar(region.anomaly, limit=4.0),
            ))
        lines.extend(_table(rows, (39, -6, -6, 21)))
        lines.append("")
        lines.append(f"  Flavour: {_ascii(a.scale.flavour)}  (index {a.scale.flavour_index:+.2f})")
        lines.extend(_wrap(
            "The flavour index is Nino-1+2 anomaly minus Nino-4 anomaly. Strongly "
            "positive means the warmth is concentrated in the east, which is the "
            "canonical pattern that drives Peruvian flooding and the strongest "
            "global teleconnections. Near zero or negative is a Modoki event, "
            "whose impacts differ in place as well as degree.",
            indent="  ",
        ))
        lines.append(
            f"  Basin coverage: {a.scale.active_regions} of 4 regions above "
            f"threshold ({a.scale.basin_score:.0f}/100)."
        )
    return lines


def _section_subsurface(state) -> list[str]:
    s = state.subsurface
    if not s:
        return []
    lines = _heading("subsurface: heat available to the event")
    lines.extend(_wrap(
        "Warm water volume is the water above the 20 degC isotherm across the "
        "equatorial Pacific. It is the fuel supply: an event cannot sustain "
        "itself on surface warmth alone, and WWV leads the surface index by "
        "roughly two seasons. This is the single most useful early number in "
        "the whole system."
    ))
    lines.append("")
    lines.append(
        f"  WWV anomaly   {s.anomaly:+.2f} x10^14 m3   ({s.latest.label})"
    )
    lines.append(f"  Rank          {_rank_phrase(s.rank_alltime, s.total_alltime, 'months')}")
    lines.append(
        f"                {_ordinal(s.rank_month)} of {s.total_month} for this calendar month "
        f"({s.percentile:.0f}th percentile)"
    )
    lines.append(f"  Tendency      {s.tendency:+.3f} per month - {_ascii(s.tendency_label)}")
    if s.west is not None:
        lines.append(
            f"  Western half  {s.west.anomaly:+.2f} x10^14 m3   "
            f"eastern half {s.east_anomaly:+.2f}"
        )
        lines.extend(_wrap(
            "Heat piled in the west is fuel not yet spent; heat already in the "
            "east is fuel being burned. A drawn-down west with a loaded east is "
            "a mature event, and the discharge that follows is what ends it.",
            indent="    ",
        ))

    lines.append("")
    lines.append(f"  Recharge oscillator phase: {_ascii(s.phase_name)}")
    lines.append(f"    angle {s.phase_angle:+.0f} deg" + ("" if s.phase_confident else "  (near a boundary - treat as indicative)"))
    lines.extend(_wrap(s.phase_note, indent="    "))
    lines.extend(_wrap(
        "The oscillator traces a clockwise loop: recharge, warming, discharge, "
        "cooling. Where the event sits on that loop says more about what "
        "happens next than its present amplitude does.",
        indent="    ",
    ))

    if s.lead_months:
        lines.append("")
        lines.extend(_wrap(
            f"Measured lead: WWV leads Nino-3.4 by {s.lead_months} months "
            f"(r = {s.lead_correlation:.2f}). That lag is computed from this "
            "record at run time, not taken from the literature, so it tracks "
            "the basin as it actually behaves now.",
            indent="  ",
        ))
    if s.implied_nino34 is not None:
        lines.extend(_wrap(
            f"At that lead the present WWV alone implies Nino-3.4 near "
            f"{s.implied_nino34:+.2f} degC. This is a one-predictor regression "
            "shown only as a sanity check on the full forecast; it is "
            "deliberately naive and will understate a strongly coupled event.",
            indent="  ",
        ))
    for note in s.notes:
        lines.extend(_wrap(note, indent="  * "))
    return lines


def _section_atmosphere(state) -> list[str]:
    at = state.atmosphere
    if not at or not at.indicators:
        return []
    lines = _heading("atmosphere: is the ocean coupled to it?")
    lines.extend(_wrap(
        "A warm ocean is not an El Nino. The event exists when the atmosphere "
        "responds - trades slacken, convection shifts east, the Walker "
        "circulation weakens. 2014 is the cautionary case: the ocean warmed, "
        "the atmosphere never answered, and the event stalled. Every index "
        "below is signed so that POSITIVE means El-Nino-like, whatever its "
        "native convention."
    ))
    lines.append("")
    coupled = "COUPLED" if at.coupled else "NOT COUPLED"
    lines.append(
        f"  Walker composite   {at.walker_index:+.2f} sigma  "
        f"[{_signed_bar(at.walker_index)}]  {coupled}"
    )
    lines.append(
        f"  Agreement          {at.agreement * 100:.0f}% of current indicators point the same way"
    )
    if at.dissenters:
        dissent = ", ".join(
            f"{_ascii(d.name)} ({d.score:+.2f})" for d in at.dissenters
        )
        lines.append(f"  Dissenting         {dissent}")
        lines.extend(_wrap(
            "A dissenting index is not noise to be averaged away. It is the "
            "part of the system that has not yet joined in, and it is where a "
            "stalling event would show up first.",
            indent="    ",
        ))
    if len(at.walker_history) >= 4:
        recent = at.walker_history[-1].value - at.walker_history[-4].value
        word = "strengthening" if recent > 0.2 else "weakening" if recent < -0.2 else "steady"
        lines.append(
            f"  Trend              {word}, {recent:+.2f} sigma over 3 months"
        )

    lines.append("")
    rows = [("indicator", "value", "sigma", "", "as of")]
    for ind in at.indicators:
        rows.append((
            ind.name,
            f"{ind.raw:+.2f}",
            f"{ind.score:+.2f}",
            _signed_bar(ind.score, width=13),
            ind.label + (" STALE" if ind.stale else ""),
        ))
    lines.extend(_table(rows, (32, -7, -6, 13, 14)))

    lines.append("")
    if at.bursts:
        latest = at.bursts[-1]
        lines.extend(_wrap(
            f"Westerly forcing: {at.burst_count_12mo} month(s) of sustained "
            f"westerly anomaly in the last 12. Most recent {latest.label}, at "
            f"{abs(latest.score):.2f} sigma of westerly anomaly (the raw trade "
            "index is negative for westerly; it is quoted as a magnitude here "
            "to match the sign convention of the table above).",
            indent="  ",
        ))
        lines.extend(_wrap(
            "Monthly means are a lower bound on true wind burst activity - real "
            "bursts last days. Bursts are what push Kelvin waves east and turn a "
            "recharged ocean into a surface event.",
            indent="    ",
        ))
    else:
        lines.append("  Westerly forcing: none detected in the recent record.")

    if at.mjo:
        m = at.mjo
        lines.append("")
        lines.append(
            f"  MJO ({m.when:%Y-%m-%d}): enhanced convection near "
            f"{_ascii(m.enhanced_longitude)}, amplitude {m.amplitude:.1f}"
        )
        lines.extend(_wrap(m.note, indent="    "))
    if at.qbo:
        lines.append("")
        phase = "easterly" if at.qbo.raw < 0 else "westerly"
        lines.append(
            f"  QBO (30 hPa, {at.qbo.label}): {at.qbo.raw:+.1f} m/s, {phase} phase."
        )
        lines.extend(_wrap(
            "The quasi-biennial oscillation is not an ENSO index. It is here "
            "because its phase modulates the stratospheric polar vortex and so "
            "conditions how an El Nino winter signal reaches the extratropics.",
            indent="    ",
        ))
    for note in at.notes:
        lines.extend(_wrap(note, indent="  * "))
    return lines


def _section_forecast(state) -> list[str]:
    f = state.forecast
    if not f or not f.projections:
        return []
    lines = _heading("forecast")
    lines.extend(_wrap(
        "Three independent methods, combined with weights set by how well each "
        "verified historically. The band is the 10th to 90th percentile of the "
        "combined distribution, widened by the measured error at that lead - it "
        "is not a confidence interval invented for the occasion."
    ))
    lines.append("")
    rows = [("lead", "season", "mean", "10-90%", "spread", "analog", "rechg", "persist")]
    for p in f.projections:
        methods = p.methods
        rows.append((
            f"+{p.lead}mo",
            p.label,
            f"{p.mean:+.2f}",
            f"{p.low:+.2f} to {p.high:+.2f}",
            f"{p.spread:.2f}",
            f"{methods['analog']:+.2f}" if "analog" in methods else "-",
            f"{methods['recharge']:+.2f}" if "recharge" in methods else "-",
            f"{methods['persistence']:+.2f}" if "persistence" in methods else "-",
        ))
    lines.extend(_table(rows, (6, 9, -6, 16, -6, -7, -6, -7)))

    peak = f.peak
    if peak:
        lines.append("")
        lines.append(f"  Projected peak: {peak.mean:+.2f} degC in {peak.label}")
        for threshold, probability in sorted(f.peak_probability.items()):
            lines.append(
                f"    P(peak ONI >= {threshold:.1f}) = {probability * 100:5.1f}%   "
                f"[{_bar(probability * 100, 100.0, 24)}]"
            )
        lines.extend(_wrap(
            "These probabilities come from the ensemble mean and its verified "
            "spread assuming a normal error distribution. That assumption is "
            "weakest in the far tail, so read the 2.5 degC line as an order of "
            "magnitude, not a precise number.",
            indent="    ",
        ))

    if f.analog_weights:
        lines.append("")
        lines.append("  Analog members and their weights:")
        total = sum(f.analog_weights.values()) or 1.0
        for name, weight in sorted(f.analog_weights.items(), key=lambda kv: -kv[1]):
            lines.append(f"    {name:<10s} {weight / total * 100:4.0f}%")

    lines.append("")
    lines.append(f"  Weighting from: {_ascii(f.skill_source)}")
    for note in f.method_notes:
        lines.extend(_wrap(note, indent="  * "))
    for note in f.notes:
        lines.extend(_wrap(note, indent="  ! "))
    return lines


def _section_skill(state) -> list[str]:
    skill = state.skill
    if not skill:
        return []
    lines = _heading("how much is that forecast worth?")
    lines.extend(_wrap(
        f"Hindcast over {skill.sample_years} years, with the verification year "
        "held out of every fit, so none of these numbers are in-sample."
    ))
    lines.append("")
    rows = [("lead", "RMSE", "corr", "bias", "n", "persist", "recharge", "useful")]
    for s in skill.leads:
        rows.append((
            f"+{s.lead}mo",
            f"{s.rmse:.2f}",
            f"{s.acc:.2f}",
            f"{s.bias:+.2f}",
            str(s.count),
            f"{s.by_method.get('persistence', 0.0):.2f}" if s.by_method else "-",
            f"{s.by_method.get('recharge', 0.0):.2f}" if s.by_method else "-",
            "yes" if s.useful else "NO",
        ))
    lines.extend(_table(rows, (6, -5, -5, -6, -5, -8, -9, -7)))
    lines.append("")
    lines.append(
        f"  Useful horizon: {skill.horizon} months (correlation stays above 0.5)."
    )

    if skill.by_target_season:
        lines.append("")
        lines.append(f"  Correlation at {6}-month lead, by the season being forecast:")
        ordered = sorted(
            skill.by_target_season.items(),
            key=lambda kv: -kv[1],
        )
        for season, acc in ordered:
            marker = "  <- barrier" if season in skill.barrier_seasons else ""
            lines.append(f"    {season}  {acc:.2f}  [{_bar(acc * 100, 100.0, 24)}]{marker}")
        if skill.barrier_seasons:
            lines.extend(_wrap(
                "That collapse is the spring predictability barrier, and it is "
                "measured here rather than asserted: forecasts that must cross "
                "boreal spring lose most of their skill. A drop of "
                f"{skill.barrier_drop:.2f} in correlation separates the best "
                "target season from the worst.",
                indent="    ",
            ))
    for note in skill.notes:
        lines.extend(_wrap(note, indent="  * "))
    return lines


def _section_analogs(state) -> list[str]:
    a = state.assessment
    if not a.analogs:
        return []
    lines = _heading("closest historical analogs")
    lines.extend(_wrap(
        "Matched on the shape of the run so far, not on peak value - the peak "
        "is what we are trying to anticipate, so using it would be circular."
    ))
    lines.append("")
    rows = [("event", "fit", "its peak", "peaked in", "+seasons", "tier", "flavour")]
    for analog in a.analogs:
        record = history.for_label(analog.episode.name)
        rows.append((
            analog.episode.name,
            f"{analog.rmse:.2f}",
            f"{analog.peak_value:+.2f}",
            analog.peak_label,
            f"+{analog.seasons_to_peak}",
            _ascii(analog.tier).replace(" El Nino", ""),
            _ascii(record.flavour if record else "-"),
        ))
    lines.extend(_table(rows, (9, -5, -9, 9, -8, 11, 15)))
    lines.extend(_wrap(
        "fit = RMSE against the current run, lower is closer. '+seasons' is how "
        "many seasons past the present stage that event took to peak - the most "
        "directly useful column here, because it dates the risk.",
        indent="  ",
    ))

    for analog in a.analogs[:3]:
        record = history.for_label(analog.episode.name)
        if not record:
            continue
        lines.append("")
        lines.append(f"  {record.label} - {_ascii(record.flavour)}")
        lines.extend(_wrap(record.summary, indent="    "))
        for consequence in record.consequences:
            lines.extend(_wrap(consequence, indent="      - "))
        if record.lesson:
            lines.extend(_wrap("Lesson: " + record.lesson, indent="    "))

    if a.historic_watch:
        lines.append("")
        lines.extend(_wrap(
            "This event is on track to belong in the same category as the "
            "benchmark events above: RONI above 1.0 with momentum still "
            "building. Read their consequence lists as a plausible scale of "
            "outcome, not as a prediction of the same outcomes.",
            indent="  ! ",
        ))
    return lines


def _section_impacts(state) -> list[str]:
    assessment = state.impacts
    if not assessment or not assessment.active:
        return []
    lines = _heading("hazard outlook")
    for note in assessment.notes:
        lines.extend(_wrap(note, indent="  "))
        lines.append("")
    lines.append(
        f"  Based on a projected peak of {assessment.peak_oni:+.2f} degC, "
        f"{_ascii(assessment.flavour)} flavour."
    )
    lines.append("")

    for area, items in assessment.by_area.items():
        lines.append(f"  {_ascii(area).upper()}")
        for impact in items:
            link = impact.link
            lines.append(f"    [{impact.likelihood:<8s}] {_ascii(link.region)}")
            lines.extend(_wrap(
                f"{link.effect} ({link.window})", indent="               "
            ))
            lines.extend(_wrap(link.detail, indent="        "))
            if link.exposure:
                lines.extend(_wrap("Exposure: " + link.exposure, indent="        "))
            if impact.flavour_note:
                lines.extend(_wrap(impact.flavour_note, indent="        ~ "))
        lines.append("")

    if assessment.watch:
        lines.append("  ON WATCH (would become likely if the event strengthens further)")
        for impact in assessment.watch:
            lines.append(
                f"    {_ascii(impact.link.region)} - {_ascii(impact.link.effect)} "
                f"(needs ONI about {impact.link.min_intensity:+.1f})"
            )
    return lines


def _section_data(state) -> list[str]:
    lines = _heading("data integrity")
    ok = [key for key, item in state.fetched.items() if item.ok and not item.from_cache]
    cached = [key for key, item in state.fetched.items() if item.ok and item.from_cache]
    failed = [(key, item.error) for key, item in state.fetched.items() if not item.ok]

    lines.append(f"  {len(ok)} feed(s) fetched live, {len(cached)} served from cache, "
                 f"{len(failed)} failed.")
    if cached:
        lines.extend(_wrap("Cached: " + ", ".join(sorted(cached)), indent="  "))
    if failed:
        lines.append("")
        lines.append("  FAILED FEEDS:")
        for key, error in failed:
            lines.append(f"    {key}: {_ascii(str(error))[:60]}")
    if state.warnings:
        lines.append("")
        lines.append("  PARSE WARNINGS:")
        for warning in state.warnings:
            lines.extend(_wrap(warning, indent="    - "))
    if not failed and not state.warnings:
        lines.append("  No feed failures and no parse warnings this run.")
    return lines


# --------------------------------------------------------------------------
# spatial views
# --------------------------------------------------------------------------

# Seven bins either side of zero would be prettier and would not survive a
# monochrome terminal at 78 columns. These are chosen so the sign of a cell is
# readable from the character alone rather than from counting ink: the cold
# half is punctuation, the warm half is symbols with a vertical stroke.
DIVERGING_CHARS = ("#", "=", "-", ".", "+", "*", "@")
SEQUENTIAL_CHARS = (".", ":", "-", "=", "+", "*", "#", "@")


def _char_for(value, low: float, high: float, chars: tuple[str, ...]) -> str:
    if value is None:
        return " "
    if high <= low:
        return chars[len(chars) // 2]
    frac = (value - low) / (high - low)
    return chars[max(0, min(len(chars) - 1, int(frac * len(chars))))]


def _char_key(chars: tuple[str, ...], low: float, high: float,
              units: str, fmt: str = "{:+.1f}") -> list[str]:
    """One legend line: which character stands for which range."""
    width = (high - low) / len(chars)
    pairs = [f"{chars[i]}={fmt.format(low + i * width)}" for i in range(len(chars))]
    return _wrap("key  " + "  ".join(pairs) + f"  ({units}; blank = no data)",
                 indent="    ")


def _lon_ruler(lons: tuple, indent: int, every: int = 8) -> list[str]:
    """A longitude scale under a character grid, with the ticks lined up."""
    # Ticks are spread from the first column to the last rather than stepped
    # from the left, so both ends are always labelled. Stepping leaves the east
    # edge bare, and the last label then reads as the end of the grid: 92W on a
    # strip that runs to 80W, which is where the warm pool edge and the
    # Nino-1+2 box are, so that misread is the expensive kind.
    if len(lons) < 2:
        ticks = list(range(len(lons)))
    else:
        count = max(2, (len(lons) - 1) // every + 1)
        step = (len(lons) - 1) / (count - 1)
        ticks = sorted({int(round(i * step)) for i in range(count)})
    marks = [" "] * len(lons)
    labels = [" "] * (len(lons) + 8)
    for i in ticks:
        marks[i] = "|"
        name = _ascii(_lon_name(lons[i]))
        for j, ch in enumerate(name):
            if i + j < len(labels):
                labels[i + j] = ch
    return [(" " * indent + "".join(marks)).rstrip(),
            (" " * indent + "".join(labels)).rstrip()]


def _decimate(values, limit: int) -> list[int]:
    """Indices of at most *limit* evenly spaced samples, both ends kept."""
    if len(values) <= limit:
        return list(range(len(values)))
    step = (len(values) - 1) / (limit - 1)
    return sorted({int(round(i * step)) for i in range(limit)})


def _ascii_field(grid, chars: tuple[str, ...], row_label, max_rows: int,
                 max_cols: int, label_width: int, diverging: bool,
                 fmt: str = "{:+.1f}") -> list[str]:
    """A gridded field as a character map, decimated to fit 78 columns."""
    rows = _decimate(grid.y, max_rows)
    cols = _decimate(grid.x, max_cols)
    low, high = grid.robust_span()
    if diverging:
        limit = max(abs(low), abs(high)) or 1.0
        low, high = -limit, limit
    lines = []
    for r in rows:
        cells = "".join(_char_for(grid.values[r][c], low, high, chars) for c in cols)
        # A row the instrument never sampled - the surface bin of a mooring
        # section, say - is a blank line with a label on it, which reads as a
        # rendering fault rather than as an absence.
        if not cells.strip():
            continue
        label = _ascii(row_label(r))[:label_width].rjust(label_width)
        lines.append(f"  {label} {cells}".rstrip())
    lines.extend(_lon_ruler(tuple(grid.x[c] for c in cols), 3 + label_width))
    lines.append("")
    lines.extend(_char_key(chars, low, high, grid.units, fmt))
    return lines


def _section_spatial(state) -> list[str]:
    spatial = getattr(state, "spatial", None)
    if spatial is None or not spatial.available:
        return []
    lines = _heading("where the event is: maps, sections and propagation")
    lines.extend(_wrap(
        "An index is a number summarising a map, and two very different maps "
        "can produce the same number. This section is the map. Everything in "
        "it is descriptive: none of it feeds the classification or the "
        "forecast, so a gap here costs a picture and nothing else."
    ))

    if spatial.box_means:
        lines.append("")
        lines.append("  Area-weighted mean SST anomaly over each index box, from the grid:")
        names = (("nino4", "Nino-4"), ("nino34", "Nino-3.4"),
                 ("nino3", "Nino-3"), ("nino12", "Nino-1+2"))
        rows = [
            (label, f"{spatial.box_means[key]:+.2f} degC",
             _signed_bar(spatial.box_means[key], limit=4.0))
            for key, label in names if key in spatial.box_means
        ]
        lines.extend(_table(rows, (10, -12, 23)))
        west = spatial.box_means.get("nino4")
        east = spatial.box_means.get("nino12")
        if west is not None and east is not None:
            gradient = east - west
            if gradient > 0.5:
                flavour = ("east-Pacific (canonical): the warmth is strongest "
                           "against the South American coast")
            elif gradient < -0.5:
                flavour = ("central-Pacific (Modoki): the warmth is strongest "
                           "near the dateline")
            else:
                flavour = "neither flavour is clearly dominant on this gradient"
            lines.extend(_wrap(
                f"Nino-1+2 minus Nino-4 is {gradient:+.2f} degC - {flavour}.",
                indent="    ",
            ))

    if spatial.warm_pool is not None:
        lines.append("")
        lines.append(
            "  28 degC warm pool, eastern edge on the equator: "
            f"{_ascii(_lon_name(spatial.warm_pool))}"
        )
        lines.extend(_wrap(
            "In a neutral Pacific that edge sits near the dateline. Every "
            "degree of longitude it travels east drags the deep convection "
            "with it, and that convection is what every teleconnection in the "
            "hazard outlook is anchored to.",
            indent="    ",
        ))

    if spatial.profiles:
        lines.append("")
        lines.append("  Depth of the 20 degC isotherm along the equator:")
        rows = []
        for profile in spatial.profiles:
            depth = profile.isotherm(20.0)
            rows.append((
                _ascii(_lon_name(profile.lon)),
                f"{depth:.0f} m" if depth is not None else "n/a",
                _bar(depth or 0.0, maximum=250.0, width=28),
            ))
        lines.extend(_table(rows, (7, -7, 28)))
        measured = grids.tilt([p.isotherm(20.0) for p in spatial.profiles])
        if measured is not None:
            drop, west, east = measured
            lines.extend(_wrap(
                f"West-minus-east tilt is {drop:.0f} m, {west:.0f} m at the two "
                f"western moorings against {east:.0f} m at the two eastern. A "
                "neutral Pacific runs near 100 m; a mature El Nino flattens "
                "it, and that flattening is the event rather than a symptom "
                "of it.",
                indent="    ",
            ))

    if spatial.section is not None:
        lines.append("")
        lines.append("  Equatorial temperature against depth, "
                     f"{_ascii(spatial.section.as_of)} (surface at the top):")
        lines.extend(_ascii_field(
            spatial.section, SEQUENTIAL_CHARS,
            lambda r: f"{spatial.section.y[r]:.0f}m",
            max_rows=16, max_cols=56, label_width=5, diverging=False,
            fmt="{:.1f}",
        ))

    if spatial.sst_hov is not None:
        lines.append("")
        lines.append("  Equatorial SST anomaly, longitude across and time downward:")
        labels = spatial.sst_hov.y_labels
        lines.extend(_ascii_field(
            spatial.sst_hov, DIVERGING_CHARS,
            lambda r: labels[r] if r < len(labels) else "",
            max_rows=20, max_cols=53, label_width=10, diverging=True,
        ))
        lines.extend(_wrap(
            "Anything travelling east leans to the right as you read down. "
            "That lean is a Kelvin wave crossing the basin.",
            indent="    ",
        ))

    stale = [
        f"{name} is {age} days behind this run"
        for name, age in sorted(spatial.stale.items())
        if age is not None and age > 45
    ]
    for note in stale:
        lines.append(f"  NOTE  {note}.")
    for note in spatial.notes:
        lines.extend(_wrap(f"NOTE  {_ascii(note)}", indent="  "))
    return lines


_RENDERERS = {
    "alerts": _section_alerts,
    "state": _section_state,
    "cpc": _section_cpc,
    "intensity": _section_intensity,
    "spatial": _section_spatial,
    "subsurface": _section_subsurface,
    "atmosphere": _section_atmosphere,
    "forecast": _section_forecast,
    "skill": _section_skill,
    "analogs": _section_analogs,
    "impacts": _section_impacts,
    "data": _section_data,
}


def render(state, sections: tuple[str, ...] = SECTIONS) -> str:
    """Render a SystemState as a fixed-width ASCII report."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        _rule(),
        "EL NINO / SOUTHERN OSCILLATION TRACKER".center(WIDTH),
        f"generated {now}".center(WIDTH),
        _rule(),
    ]
    for name in sections:
        renderer = _RENDERERS.get(name)
        if renderer:
            lines.extend(renderer(state))

    lines.append("")
    lines.append(_rule())
    lines.extend(_wrap(
        "This tracker is a decision-support tool built on public NOAA data. It "
        "is not an official forecast. For operational warnings use your national "
        "meteorological service and the NOAA CPC ENSO Diagnostic Discussion.",
    ))
    lines.append(_rule())
    return "\n".join(_ascii(line) for line in lines)


def brief(state) -> str:
    """The thirty-second version: alerts and state only."""
    return render(state, sections=("alerts", "state"))
