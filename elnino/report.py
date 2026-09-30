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

from . import (alerts, atlas, cyclones, forecast, grids, history, impacts, outlook,
               stormdesk, stormfury, tcproducts)
from .grids import lon_name as _lon_name
from .alerts import CRITICAL, INFO, WARNING, WATCH

WIDTH = 78
BAR_WIDTH = 32
PLACE_WIDTH = 26
# "Well East-Southeast of the Hawaiian Islands" is 43 characters.
AREA_WIDTH = 44
# A product's name column under each storm: "Tropical Storm Warning" is 22.
PRODUCT_WIDTH = 24
# Wind speed probability rows printed per storm, highest chances first.
WIND_ROWS = 8

LEVEL_MARK = {CRITICAL: "[!!!]", WARNING: "[!! ]", WATCH: "[!  ]", INFO: "[   ]"}

# Sections a caller can ask for by name. Order here is the order they print.
SECTIONS = (
    "alerts", "state", "cpc", "intensity", "spatial", "subsurface",
    "atmosphere", "forecast", "skill", "analogs", "impacts", "cyclones",
    "outlook", "stormfury", "atlas", "data",
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
    # A bullet is printed once and the text hangs under it; repeated on every
    # line, one wrapped note read as several. A "!" callout keeps its bar.
    bulleted = indent.rstrip().endswith(("*", "-"))
    return textwrap.wrap(
        _ascii(text), width=width, initial_indent=indent,
        subsequent_indent=" " * len(indent) if bulleted else indent,
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
        flag = ("  NEW" if alert.is_new
                else f"  ESCALATED from {alert.escalated_from.upper()}"
                if alert.escalated_from else "")
        # A title can outrun the page (a formation area's name is NHC's own
        # and can be forty characters); it wraps under itself, not past 78.
        lines.extend(textwrap.wrap(f"{_ascii(alert.title)}{flag}", width=WIDTH,
                                   initial_indent=f"  {mark} ",
                                   subsequent_indent="        "))
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
    lines.append(
        f"  STATE        {_ascii(a.index_tier)}  ({a.index_name} "
        f"{a.index_latest.value:+.2f} degC, {a.index_latest.label})"
    )
    if a.index_name == "RONI" and a.oni_latest:
        lines.append(
            f"  LEGACY ONI   {a.oni_latest.value:+.2f} degC ({a.oni_latest.label}) "
            f"-> {_ascii(a.oni_tier)}"
        )
    elif a.index_name == "RONI":
        lines.append("  LEGACY ONI   did not arrive this run")
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
            f"  PEAK (proj)  {a.index_name} {peak.mean:+.2f} degC in {peak.label} "
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
        count = len(state.warnings)
        lines.append(f"  DATA         DEGRADED - {count} "
                     f"problem{'s' if count != 1 else ''}, see end")
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


def _index_line(name: str, value, tier: str, role: str) -> str:
    return (f"  {name:<5} {value.value:+.2f} degC  {value.label}   "
            f"-> {_ascii(tier)}  [{role}]")


def _section_intensity(state) -> list[str]:
    a = state.assessment
    lines = _heading("intensity")
    if a.index_name == "RONI" and a.roni_latest:
        lines.append(_index_line("RONI", a.roni_latest, a.roni_tier, "official"))
        if a.roni_ranking:
            lines.extend(_wrap(_ranking(a.roni_ranking), indent="        "))
        if a.oni_latest:
            lines.append(_index_line("ONI", a.oni_latest, a.oni_tier, "legacy"))
        else:
            lines.append("  ONI   did not arrive this run  [legacy]")
        if a.ranking:
            lines.extend(_wrap(_ranking(a.ranking), indent="        "))
        gap = ""
        if a.oni_latest and a.oni_latest.label == a.roni_latest.label:
            gap = (
                f" This season the legacy ONI runs {a.oni_latest.value - a.roni_latest.value:+.2f} "
                "degC above it: warmth the whole tropical ocean shares, not the "
                "Pacific's own."
            )
        lines.extend(_wrap(
            "CPC has classified on RONI since 1 February 2026 (NWS PIS 26-05): "
            "Nino-3.4 with the tropical-mean anomaly taken out and rescaled. "
            "Tiers, episodes and every alert here follow it, on the one-decimal "
            "value CPC prints." + gap,
            indent="        ",
        ))
    else:
        lines.append(_index_line("ONI", a.oni_latest, a.oni_tier, "stand-in"))
        if a.ranking:
            lines.extend(_wrap(_ranking(a.ranking), indent="        "))
        lines.extend(_wrap(
            "RONI, CPC's official index since February 2026, did not arrive; "
            "the legacy ONI stands in for it until it does.",
            indent="        ",
        ))

    lines.append("")
    lines.extend(_wrap("Episode: " + a.episode_status, indent="  "))
    if a.episode:
        run = "  ".join(f"{v.season} {v.value:+.2f}" for v in a.episode.seasons[-6:])
        lines.append(f"  Run so far: {run}")

    if a.scale:
        lines.append("")
        if a.scale.basis == "relative":
            lines.extend(_wrap(
                "Region anomalies, latest week, relative to the tropical mean as "
                "CPC now quotes them ('trad' is the traditional anomaly beside it):",
                indent="  ",
            ))
            rows = [("region", "rel", "trad", "SST", "")]
            for region in a.scale.regions:
                rows.append((
                    region.label,
                    f"{region.anomaly:+.1f}",
                    "-" if region.traditional is None else f"{region.traditional:+.1f}",
                    f"{region.sst:.1f}",
                    _signed_bar(region.anomaly, limit=4.0, width=15),
                ))
            lines.extend(_table(rows, (37, -5, -5, -5, 15)))
        else:
            lines.append("  Region anomalies (latest weekly observation, traditional):")
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
        lines.append(
            f"  Flavour: {_ascii(a.scale.flavour)}  (index {a.scale.flavour_index:+.2f}, "
            f"{a.scale.basis} anomalies)"
        )
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
        latest = at.bursts[0]  # newest first
        lines.extend(_wrap(
            f"Westerly forcing: {at.burst_count_12mo} "
            f"month{'s' if at.burst_count_12mo != 1 else ''} of sustained "
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
        lines.append(
            f"  Projected peak: {f.index_name} {peak.mean:+.2f} degC in {peak.label}"
        )
        for threshold, probability in sorted(f.peak_probability.items()):
            lines.append(
                f"    P(peak {f.index_name} >= {threshold:.1f}) = {probability * 100:5.1f}%   "
                f"[{_bar(probability * 100, 100.0, 24)}]"
            )
        lines.extend(_wrap(
            "Each probability is that of the season likeliest to clear the bar, "
            "from the ensemble mean and its verified spread, judged on the "
            "one-decimal value CPC prints (+1.95 prints as +2.0). The best single "
            "season is a floor on the chance that some season clears it. The "
            "normal error distribution behind it is weakest in the far tail, so "
            "read the 2.5 degC line as an order of magnitude, not a precise number.",
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
    if f.weights:
        lines.append(f"  Method weights: {forecast.weights_text(f.weights)}")
    for note in f.method_notes:
        lines.extend(_wrap(note, indent="  * "))
    for note in f.notes:
        lines.extend(_wrap(note, indent="  ! "))
    return lines


def _horizon_words(skill) -> str:
    months = f"{skill.horizon} month{'' if skill.horizon == 1 else 's'}"
    lost = skill.lost_at()
    if lost is None:
        last = skill.leads[-1]
        return (f"Useful horizon: at least {months} - correlation is still "
                f"{last.acc:.2f} at +{last.lead}, the longest lead scored.")
    if not skill.horizon:
        return (f"No useful horizon: correlation is {lost.acc:.2f} at "
                f"+{lost.lead}, below 0.5.")
    return f"Useful horizon: {months} - correlation falls below 0.5 at +{lost.lead}."


def _section_skill(state) -> list[str]:
    skill = state.skill
    if not skill:
        return []
    lines = _heading("how much is that forecast worth?")
    lines.extend(_wrap(
        f"Hindcast over {skill.sample_years} years, with the start year and the "
        "year after it - the year a long-lead forecast verifies in - held out of "
        "every fit, so none of these numbers are in-sample."
    ))
    lines.append("")
    # Every method the forecast weights, in the forecast table's order; a
    # method with too few forecasts at a lead to score prints no score.
    rows = [("lead", "RMSE", "corr", "bias", "n", "analog", "rechg", "persist", "useful")]
    for s in skill.leads:
        rows.append((
            f"+{s.lead}mo",
            f"{s.rmse:.2f}",
            f"{s.acc:.2f}",
            f"{s.bias:+.2f}",
            str(s.count),
            *(f"{s.by_method[m]:.2f}" if m in s.by_method else "-"
              for m in ("analog", "recharge", "persistence")),
            "yes" if s.useful else "NO",
        ))
    lines.extend(_table(rows, (6, -5, -5, -6, -5, -7, -6, -8, -7)))
    lines.append("")
    lines.extend(_wrap(_horizon_words(skill)))

    if skill.by_target_season:
        lines.append("")
        lines.append(f"  Correlation at {6}-month lead, by the season being forecast:")
        ordered = sorted(
            skill.by_target_season.items(),
            key=lambda kv: -kv[1],
        )
        for season, acc in ordered:
            marker = "  <- weakest" if season in skill.barrier_seasons else ""
            lines.append(f"    {season}  {acc:.2f}  [{_bar(acc * 100, 100.0, 24)}]{marker}")
        if skill.barrier_seasons:
            lines.extend(_wrap(
                "That collapse is where the spring predictability barrier "
                "shows, measured here rather than asserted: a drop of "
                f"{skill.barrier_drop:.2f} in correlation separates the best "
                "target season from the worst, and the weakest are "
                + ", ".join(skill.barrier_seasons) + ".",
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
        f"Matched on the shape of the {a.index_name} run so far, not on peak "
        "value - the peak is what we are trying to anticipate, so using it "
        "would be circular."
    ))
    lines.append("")
    rows = [("event", "fit", "its peak", "peaked in", "to peak", "tier", "flavour")]
    for analog in a.analogs:
        record = history.for_episode(analog.episode)
        rows.append((
            analog.episode.name,
            f"{analog.rmse:.2f}",
            f"{analog.peak_value:+.2f}",
            analog.peak_label,
            f"{analog.seasons_to_peak:+d}",
            _ascii(analog.tier).replace(" El Nino", ""),
            _ascii(record.flavour if record else "-"),
        ))
    lines.extend(_table(rows, (9, -5, -9, 9, -8, 11, 15)))
    lines.extend(_wrap(
        "fit = RMSE against the current run, lower is closer. 'to peak' is how "
        "many seasons that event went on rising from the stage this one has "
        "reached - zero or less means it had already peaked by now. It is the "
        "most directly useful column here, because it dates the risk.",
        indent="  ",
    ))

    for analog in a.analogs[:3]:
        record = history.for_episode(analog.episode)
        if not record:
            continue
        name = analog.episode.name
        documented = (f" (documented as the {record.label} event)"
                      if record.label != name else "")
        lines.append("")
        lines.append(f"  {name} - {_ascii(record.flavour)}{documented}")
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
        f"  Based on a projected {assessment.index_name} peak of "
        f"{assessment.peak_index:+.2f} degC, "
        f"{_ascii(impacts.flavour_words(assessment.flavour))} flavour."
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
        lines.append("  ON WATCH (below the outlook's bar at this peak)")
        for impact in assessment.watch:
            lines.extend(_wrap(
                f"{impact.link.region} - {impact.link.effect}", indent="    "
            ))
            lines.extend(_wrap(_watch_condition(impact, assessment), indent="      "))
    return lines


def _watch_condition(impact, assessment) -> str:
    """What it would take to promote a watch item, said honestly."""
    if impact.needs is None:
        return ("A contested relationship: rated \"possible\" at most, however "
                "strong the event.")
    text = (f"Joins the outlook at a {assessment.index_name} peak of about "
            f"{impact.needs:+.1f} degC")
    penalty = impacts.flavour_penalty(impact.link, assessment.flavour)
    if penalty:
        text += f", {penalty:.2f} higher than usual for an event of this flavour"
    return text + "."


def _section_stormfury(state) -> list[str]:
    """Project STORMFURY, run as a procedure rather than argued about.

    This section exists because "why not just weaken it" is the first thing
    anyone asks about a hurricane, and the answer deserves better than an
    assertion. The experiment was real, its hypothesis was coherent, and it
    failed for three separate measurable reasons. All three are printed with
    this run's numbers on them.
    """
    fury = getattr(state, "stormfury", None)
    if fury is None or not fury.available:
        return []
    lines = _heading("project stormfury, recreated")

    lines.extend(_wrap(
        "The 1962-83 hurricane modification experiment, rebuilt as a decision "
        "procedure and run against the storms that are live right now. Seed "
        "the region outside the eyewall, freeze the supercooled water there, "
        "build a new eyewall further out, and let conservation of angular "
        "momentum slow the winds down."
    ))
    lines.append("")
    lines.extend(_wrap(f"Verdict: {fury.verdict}"))

    lines.append("")
    lines.append("  Three independent failures:")
    for index, reason in enumerate(fury.reasons, start=1):
        lines.append("")
        head, body = reason.split(":", 1)
        lines.append(f"    {index}. {head.strip()}")
        lines.extend(_wrap(body.strip(), indent="       "))

    strongest = max((a for a in fury.assessments if a.momentum),
                    key=lambda a: a.wind_kt or 0, default=None)
    if strongest is not None:
        lines.append("")
        lines.append(f"  The mechanism, computed for {strongest.title} "
                     f"({strongest.wind_kt} kt, eyewall {strongest.rmw_nm} nm):")
        lines.append("")
        lines.append(f"    {'eyewall':>16}  {'wind':>10}  {'drop':>7}")
        for row in strongest.momentum:
            if not row["after_kt"]:
                continue
            move = f'{row["from_nm"]:.0f}->{row["to_nm"]:.0f} nm'
            wind = f'{row["before_kt"]}->{row["after_kt"]} kt'
            lines.append(f"    {move:>16}  {wind:>10}  "
                         f"{-row['drop_pct']:>6.1f}%")
        lines.extend(_wrap(
            "That is what the hypothesis predicts if the eyewall could be "
            "moved. Nothing in this system, or any other, can move it.",
            indent="    ",
        ))

    skill = fury.skill
    if skill.get("count"):
        lines.append("")
        lines.append("  The same calculation, scored against real eyewalls:")
        lines.append("")
        lines.append(f"    natural expansions measured   {skill['count']:>6}"
                     f"  in {skill['storms']} hurricanes")
        lines.append(f"    angular momentum predicted    "
                     f"{-skill['mean_predicted_drop']:>6.1f}%  mean wind change")
        lines.append(f"    the storms actually gave up   "
                     f"{-skill['mean_observed_drop']:>6.1f}%  mean wind change")
        lines.append(f"    held or strengthened anyway   "
                     f"{skill['held_or_strengthened']:>6}  of "
                     f"{skill['count']}")

    swings = fury.swings
    if swings.get("count"):
        lines.append("")
        lines.append("  Unseeded hurricanes this season, 24-hour changes:")
        lines.append("")
        lines.append(f"    intervals measured            "
                     f"{swings['count']:>6}  in {swings['storms']} storms")
        lines.append(f"    weakened by >= {swings['claim']:.0f}%           "
                     f"{swings['weakened_as_much']:>6}  "
                     f"({(swings['share_weakened'] or 0) * 100:.1f}%)")
        lines.append(f"    moved >= {swings['claim']:.0f}% either way    "
                     f"{swings['moved_as_much']:>6}  "
                     f"({(swings['share_moved'] or 0) * 100:.1f}%)")
        lines.append(f"    largest natural weakening     "
                     f"{swings['biggest_drop']:>6.1f}%")

    if fury.assessments:
        lines.append("")
        lines.append("  Would STORMFURY have been allowed to fly these?")
        for a in fury.assessments:
            lines.append("")
            lines.append(f"    {a.title} ({a.basin}, {a.wind_kt} kt)")
            for c in a.criteria:
                mark = {True: "pass", False: "FAIL", None: "----"}[c.passed]
                lines.extend(_wrap(f"[{mark}] {c.name}: {c.detail}",
                                   indent="      "))

    lines.append("")
    lines.append("  The record:")
    for seeded in stormfury.HISTORY:
        lines.append("")
        lines.append(f"    {seeded.name} ({seeded.year}), {seeded.dates}")
        lines.extend(_wrap(f"claimed: {seeded.claimed}", indent="      "))
        lines.extend(_wrap(seeded.outcome, indent="      "))

    lines.append("")
    lines.extend(_wrap(stormfury.PROGRAMME["ended"]))
    lines.append("")
    lines.extend(_wrap("What it did buy: " + stormfury.PROGRAMME["legacy"]))
    lines.append("")
    lines.extend(_wrap(
        "A hurricane cannot be stopped, and this section is the measured "
        "version of why rather than the asserted one. The deliverable is lead "
        "time, and the cyclone section above is what lead time looks like."
    ))
    return lines


def _section_data(state) -> list[str]:
    lines = _heading("data integrity")
    ok = [key for key, item in state.fetched.items() if item.ok and not item.from_cache]
    cached = [key for key, item in state.fetched.items() if item.ok and item.from_cache]
    failed = [(key, item.error) for key, item in state.fetched.items() if not item.ok]

    lines.append(f"  {len(ok)} feed{'s' if len(ok) != 1 else ''} fetched live, "
                 f"{len(cached)} served from cache, "
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


def _section_cyclones(state) -> list[str]:
    """Storms: the thing the boundary condition actually produces.

    Ordered by urgency rather than by basin. A reader opening this section has
    one question - is there something out there aimed at me - and the answer
    to that is the live storms, so they go first, and the seasonal
    verification that explains why there are so many or so few of them goes
    after.
    """
    storms = getattr(state, "cyclones", None)
    if storms is None or not storms.available:
        return []
    lines = _heading("tropical cyclones")

    live = storms.active
    if not live:
        lines.extend(_wrap(
            "No active tropical cyclones in the Atlantic, east or central "
            "Pacific at this run."
        ))
    for storm in live:
        now = storm.latest
        if now is None:
            continue
        lines.append("")
        lines.append(f"  {_ascii(storm.title).upper()}  ({storm.designation}, "
                     f"{storm.basin_name})")
        move = storm.translation
        motion = (f"moving {cyclones.bearing_name(move[1])} at {move[0]:.0f} kt"
                  if move else "motion not resolvable")
        lines.extend(_wrap(
            f"{now.label.capitalize()}, {now.wind or 0} kt sustained"
            + (f", {now.pressure} mb" if now.pressure else "")
            + f", centred {_position(now)}, {motion}.",
            indent="    ",
        ))
        land = storm.nearest_land
        if land:
            lines.extend(_wrap(
                f"Nearest land: {land[1].name}, {land[1].country}, "
                f"{land[0]:.0f} km.",
                indent="    ",
            ))

        change, when = storm.rapid
        if when:
            if abs(change) < 5:
                sentence = "Steady over the last 24 hours."
            else:
                word = "intensified" if change > 0 else "weakened"
                tag = (" - rapid intensification by the NHC definition"
                       if change >= cyclones.RI_THRESHOLD else "")
                sentence = f"Has {word} {abs(change):.0f} kt in the last 24 hours{tag}."
            burst, burst_when = storm.peak_intensification
            if burst >= cyclones.RI_THRESHOLD and burst_when != when:
                sentence += (
                    f" Its fastest 24 hours so far were {burst:+.0f} kt, to "
                    f"{alerts._stamp(burst_when)}."
                )
            lines.extend(_wrap(sentence, indent="    "))

        peak = storm.peak
        if peak and peak.wind and peak.wind > (now.wind or 0):
            lines.extend(_wrap(
                f"Peak so far {peak.wind} kt ({peak.label}) at "
                f"{_stamp(peak.stamp)}. Storm ACE {storm.ace:.1f}.",
                indent="    ",
            ))

        if storm.forecast:
            issued = storm.forecast[0].issued
            if issued and issued != now.stamp:
                lines.append("")
                lines.extend(_wrap(
                    f"Official forecast from the {_stamp(issued)} advisory, with "
                    f"leads counted from the {_stamp(now.stamp)} analysis above.",
                    indent="    ",
                ))
            rows = [("lead", "valid", "position", "wind", "category")]
            for fix in storm.forecast:
                if fix.tau > cyclones.HORIZON:
                    continue
                rows.append((
                    f"+{fix.tau} h", alerts._valid(fix), _position(fix),
                    f"{fix.wind or 0} kt", fix.label,
                ))
            if len(rows) > 1:
                lines.append("")
                # The category is the widest cell: JTWC's "Category
                # 5-equivalent super typhoon" is 35 characters, and the
                # columns before it are as narrow as their contents.
                lines.extend(_table(rows, (-6, 10, 12, -6, 35), indent="    "))
            spread = storm.spread_km
            if spread is not None and storm.spread_tau is not None:
                members = len(storm.scatter)
                kind = "ensemble members" if storm.ensemble else "models"
                lines.append("")
                lines.extend(_wrap(
                    f"The {members} {kind} sit on average {spread:.0f} km from "
                    f"their mean position at +{storm.spread_tau} h. That spread "
                    "is the honest uncertainty of this forecast; the single "
                    "line above is one track inside it, not the whole of it.",
                    indent="    ",
                ))

        threats = [t for t in storm.threats(alerts.BRUSH_KM)
                   if (t[1].wind or 0) >= 34]
        if threats:
            lines.append("")
            lines.extend(_wrap("Closest approach to populated coast:",
                               indent="    "))
            # 6 + 26 + 8 + 16 + 19 and the spaces between them make 78: the
            # widest intensity is "60 kt subtrop storm", the widest time
            # "+120h 00Z 30 Sep".
            rows = [("place", "distance", "when", "intensity")]
            for gap, fix, place in threats[:6]:
                label = f"{place.name}, {place.country}"
                if len(label) > PLACE_WIDTH:
                    label = place.name
                if len(label) > PLACE_WIDTH:
                    # A name too long for the column gets a line of its own
                    # rather than being cut short.
                    rows.append((label,))
                    label = ""
                rows.append((
                    label, f"{gap:.0f} km",
                    f"{'now' if fix.tau == 0 else f'+{fix.tau}h'} "
                    f"{alerts._valid(fix)}", f"{fix.wind or 0} kt {fix.short}",
                ))
            lines.extend(_table(rows, (PLACE_WIDTH, -8, 16, 19), indent="      "))
            lines.extend(_wrap(
                "Distances are to the forecast centre line. Hurricane-force "
                "wind extends tens of kilometres either side of it and "
                "tropical-storm force twice that, so a 200 km pass is not a "
                "miss.",
                indent="      ",
            ))
        lines.extend(_protective(storm))
        for note in storm.notes:
            lines.extend(_wrap(f"Note: {note}", indent="    "))

    # -- the seasonal verification
    lines.append("")
    lines.extend(_wrap(
        f"Season to date, against seasons as they stood on {storms.through}:",
    ))
    rows = [("basin", "ACE", "normal", "vs", "named", "hurr", "major")]
    for basin in ("AL", "EP"):
        season = storms.basins.get(basin)
        if season is None:
            continue
        ratio = season.ace_ratio
        rows.append((
            season.name, f"{season.ace:.0f}",
            f"{season.normal_ace:.0f}" if season.normal_ace else "n/a",
            f"{ratio:.2f}x" if ratio is not None else "n/a",
            str(season.named), str(season.hurricanes), str(season.major),
        ))
    if len(rows) > 1:
        lines.append("")
        lines.extend(_table(rows, (26, -6, -7, -7, -6, -5, -6)))

    index_name = state.assessment.index_name
    index_value = state.assessment.index_latest.value
    flavour = impacts.flavour_of(
        state.assessment.scale.flavour_index if state.assessment.scale else 0.0
    )
    mark = {True: "CONFIRMED", False: "CONTRADICTED", None: "INCONCLUSIVE"}
    for basin in ("AL", "EP"):
        season = storms.basins.get(basin)
        if season is None:
            continue
        scored = cyclones.verdict(season, index_value, flavour)
        if not scored:
            continue
        lines.append("")
        lines.append(f"  {_ascii(season.name).upper()}: {mark[scored['agrees']]}")
        sentence = (
            f"The catalogue calls for {scored['expected']} activity here at "
            f"{index_name} {index_value:+.2f} ({scored['likelihood']}, "
            f"{scored['confidence']} confidence). Observed activity is "
            f"{scored['observed']}."
        )
        if scored["elnino_ratio"] is not None:
            sentence += (
                f" Against past El Nino seasons at the same date it is "
                f"{scored['elnino_ratio']:.2f}x the composite of "
                f"{scored['sample']} of them."
            )
        lines.extend(_wrap(sentence, indent="    "))
        if scored["elapsed"] is not None:
            lines.extend(_wrap(
                f"This verdict rests on the {scored['elapsed'] * 100:.0f} per "
                "cent of a normal season's energy that has usually fallen by "
                "this date. Earlier in a season the same comparison means much "
                "less.",
                indent="    ",
            ))
        if scored["note"]:
            lines.extend(_wrap(scored["note"], indent="    "))

    lines.append("")
    lines.extend(_wrap(
        "On stopping one: it cannot be done, and the attempt has been made. "
        "Project STORMFURY seeded eyewalls with silver iodide from 1962 to "
        "1983 and was abandoned because the observed changes could not be "
        "separated from natural eyewall replacement, and because the cloud "
        "physics the hypothesis rested on proved wrong - mature hurricanes "
        "carry far too little supercooled water to seed. A Category 4 "
        "releases on the order of 10^19 joules a day as latent heat, several "
        "hundred times world electricity generation. The deliverable is lead "
        "time, and the table above is what lead time looks like."
    ))
    for note in [*storms.notes, *storms.upgrades]:
        lines.extend(_wrap(f"Note: {note}", indent="  "))
    return lines


def _protective(storm) -> list[str]:
    """What the storm's warning centre issued to protect people, as issued.

    "None in effect" and "issued but not fetched" are different statements to
    someone deciding whether to leave, so they are never printed alike.
    """
    lines = [""]
    if storm.centre == "JTWC":
        lines.extend(_wrap(
            "JTWC issues no coastal watches or warnings, surge forecast or wind "
            "speed probabilities: each country's national meteorological "
            "service warns for its own coast.",
            indent="    ",
        ))
        return lines
    products = storm.products
    current = cyclones._advisory_number((storm.advisory or {}).get("advisory", ""))
    own = dict(products.advisories) if products is not None else {}
    lines.extend(_wrap(f"Protective products, {stormdesk.centre_name(storm)} advisory "
                       f"{current or 'not given'}:", indent="    "))

    def of(kind: str) -> str:
        # A product from another advisory than the current one says which.
        number = own.get(kind)
        return f" (advisory {number})" if number and current and number != current else ""

    def item(name: str, text: str) -> None:
        lines.extend(textwrap.wrap(
            _ascii(text), width=WIDTH,
            initial_indent="      " + name.ljust(PRODUCT_WIDTH),
            subsequent_indent=" " * (6 + PRODUCT_WIDTH),
        ))

    # The public advisory's own words for where each is in effect; its lines
    # name the coast only where the advisory did not come.
    said = dict(products.in_effect or ()) if products is not None else {}
    status = stormdesk._status(storm, "watches")
    by_kind: dict[str, list] = {}
    if status == "issued":
        for segment in products.watches:
            by_kind.setdefault(segment.kind, []).append(segment)
    kinds = [k for k in tcproducts.WW_ORDER if k in said or k in by_kind]
    kinds += [k for k in dict.fromkeys([*said, *by_kind]) if k not in kinds]
    for kind in kinds:
        if kind in said:
            item(kind, "; ".join(said[kind]) + of("in_effect"))
        else:
            item(kind, "; ".join(alerts._coasts(by_kind[kind])) + of("watches"))
    if status == "unavailable":
        lines.extend(_wrap(
            "The lines of these watches and warnings could not be fetched this run."
            if kinds else
            "Watches and warnings were issued but could not be fetched this "
            "run; read them in the public advisory.",
            indent="      ",
        ))
    elif not kinds:
        lines.extend(_wrap("No coastal watches or warnings are in effect.",
                           indent="      "))

    status = stormdesk._status(storm, "surge")
    if status == "issued":
        # NHC writes the range with its unit: "1-3 ft".
        for area in products.surge:
            item("Peak storm surge", f"{area.label} {area.feet}{of('surge')}")
    elif status == "unavailable":
        lines.extend(_wrap(
            "The peak storm surge forecast was issued but could not be "
            "fetched this run.",
            indent="      ",
        ))

    status = stormdesk._status(storm, "winds")
    winds = products.winds if products is not None else None
    if status == "issued" and winds is not None and winds.rows:
        places: dict[str, dict] = {}
        for row in winds.rows:
            places.setdefault(row.place, {})[row.threshold] = row.total
        order = sorted(places, key=lambda p: (-places[p].get(64, 0), -places[p].get(50, 0),
                                              -places[p].get(34, 0), p))
        hours = winds.hours[-1] if winds.hours else 120

        def cell(value) -> str:
            # 0 is the product's X: below one percent.
            return "-" if value is None else "<1%" if value == 0 else f"{value}%"

        try:
            issued = f"{datetime.strptime(winds.issued, '%H%M UTC %a %b %d %Y'):%Y-%m-%d %H:%M} UTC"
        except ValueError:
            issued = winds.issued
        lines.append("")
        lines.extend(_wrap(
            f"Wind speed probabilities, advisory {winds.advisory}, issued {issued}.",
            indent="      ",
        ))
        lines.extend(_wrap(
            f"The chance of each wind at each place within {hours} h, highest first:",
            indent="      ",
        ))
        rows = [("place", "34 kt", "50 kt", "64 kt")]
        for place in order[:WIND_ROWS]:
            got = places[place]
            rows.append((place, cell(got.get(34)), cell(got.get(50)), cell(got.get(64))))
        lines.extend(_table(rows, (PLACE_WIDTH, -6, -6, -6), indent="        "))
        if any("-" in row[1:] for row in rows[1:]):
            lines.extend(_wrap("A dash: the product has no line for that wind at that place.",
                               indent="        "))
        rest = len(order) - WIND_ROWS
        if rest > 0:
            lines.extend(_wrap(
                f"{rest} more {'place' if rest == 1 else 'places'} in the product, "
                "every one of them on the storm desk.",
                indent="        ",
            ))
    elif status == "unavailable":
        lines.extend(_wrap(
            "The wind speed probabilities were issued but could not be fetched "
            "this run.",
            indent="      ",
        ))
    return lines


# The basins an outlook covers, as the report names them.
_OUTLOOK_BASIN = {"AL": "Atlantic", "EP": "east Pacific", "CP": "central Pacific",
                  "WP": "west Pacific", "IO": "north Indian Ocean",
                  "SH": "southern hemisphere"}
_OUTLOOK_ORDER = {"NHC": 0, "CPHC": 1, "JTWC": 2}


def _issued(area) -> str:
    """An outlook's issue time in UTC, or as the centre wrote it."""
    text = str(area.issued or "").strip()
    try:
        # NHC names each outlook with its issue time in UTC.
        when = datetime.strptime(text, "%a %b %d %H:%M:%S %Y")
        return f"{when:%Y-%m-%d %H:%M} UTC"
    except ValueError:
        pass
    iso = stormdesk._iso_time(text)
    if iso:
        return f"{iso[:10]} {iso[11:16]} UTC"
    return text or "time not given"


def _section_outlook(state) -> list[str]:
    """Where the next storms may come from, as the warning centres rate it."""
    storms = getattr(state, "cyclones", None)
    if storms is None or not storms.available:
        return []
    lines = _heading("formation outlook")
    lines.extend(_wrap(
        "Where the next tropical cyclones may form: every area the warning "
        "centres are watching, with the chance or rating each gives it. An "
        "area is not yet a storm, and nothing here is a track."
    ))
    areas = list(getattr(storms, "outlook", None) or [])
    invests = [s for s in (getattr(storms, "invests", None) or ()) if s.latest is not None]
    if not areas and not invests:
        lines.append("")
        lines.extend(_wrap(
            "No area is being watched for formation in the NHC, CPHC or JTWC "
            "outlooks at this run."
        ))
        return lines

    groups: dict[tuple[str, str], list] = {}
    for area in areas:
        groups.setdefault((area.centre, area.basin), []).append(area)
    for (centre, basin), members in sorted(
            groups.items(), key=lambda kv: (_OUTLOOK_ORDER.get(kv[0][0], 3), kv[0][1])):
        lines.append("")
        lines.append(f"  {centre} {_OUTLOOK_BASIN.get(basin, basin)} outlook, "
                     f"issued {_issued(members[0])}")
        if centre == "JTWC":
            # JTWC gives no percentages: its rating is the potential for a
            # significant tropical cyclone within 24 hours.
            for area in members:
                formation = getattr(area, "formation", None) if area.alert else None
                alert = ""
                if formation and formation.lapsed(getattr(state, "run_at", None)):
                    alert = (f"; JTWC's formation alert ran to {outlook.utc(formation.until)} "
                             "and nothing newer has been read")
                elif area.alert:
                    alert = "; a tropical cyclone formation alert is in effect" + (
                        f" until {outlook.utc(formation.until)}"
                        if formation and formation.until else "")
                lines.extend(_wrap(
                    f"{area.label}, {alerts._latlon(area.lon, area.lat)}: "
                    f"{area.potential or 'unrated'} potential for a significant "
                    f"tropical cyclone within 24 hours{alert}.",
                    indent="    - ",
                ))
                facts = formation.facts() if formation else []
                if facts:
                    lines.extend(_wrap(
                        f"JTWC's alert of {outlook.utc(formation.issued)}: "
                        f"{', '.join(facts)}.", indent="      "))
            continue
        rows = [("area", "2-day", "7-day", "category")]
        for area in members:
            label = area.label
            if len(label) > AREA_WIDTH:
                # A name too long for the column gets a line of its own.
                rows.append((label,))
                label = ""
            rows.append((label,
                         "n/a" if area.chance_2day is None else f"{area.chance_2day}%",
                         "n/a" if area.chance_7day is None else f"{area.chance_7day}%",
                         area.potential or ""))
        lines.extend(_table(rows, (AREA_WIDTH, -6, -6, 9), indent="    "))

    if invests:
        lines.append("")
        lines.extend(_wrap(
            "Invests: disturbances the centres have numbered and track with a "
            "best-track deck. None is a tropical cyclone yet."
        ))
        rows = []
        for storm in invests:
            now = storm.latest
            rows.append((storm.title, _position(now), f"{now.wind or 0} kt", now.label,
                         _stamp(now.stamp)))
        lines.extend(_table(rows, (12, 14, -6, 12, 14), indent="    "))
    return lines


def _position(fix) -> str:
    return (f"{abs(fix.lat):.1f}{'N' if fix.lat >= 0 else 'S'} "
            f"{abs(fix.lon):.1f}{'W' if fix.lon < 0 else 'E'}")


def _stamp(atcf: str) -> str:
    return (f"{atcf[:4]}-{atcf[4:6]}-{atcf[6:8]} {atcf[8:10]}Z"
            if len(atcf) == 10 else atcf)


def _section_atlas(state) -> list[str]:
    """What El Nino has measurably done on the ground, place by place.

    Every other section on this page is about the ocean or about an index. This
    one is about somewhere a person lives, and it is a composite of what
    happened in past events rather than a forecast of this one - which is a
    distinction the section makes twice, because it is the distinction readers
    of a composite most often lose.
    """
    tier = getattr(state, "atlas", None)
    if tier is None or not tier.available:
        return []
    lines = _heading("the ground: what past el ninos actually did")

    lines.extend(_wrap(
        "A composite over the El Nino events since 1979 in which RONI reached "
        "+1.0: per season, the mean of those events minus the mean of the "
        "neutral years (RONI inside +/-0.5), for every cell of a global "
        "rainfall grid and a land surface-temperature grid. Each event counts "
        "once, because the months inside one are not independent, and a cell "
        "is called wetter or drier only where Welch's t passes the 95% "
        "two-sided point of Student's t for its season's sample."
    ))
    lines.append("")
    for season in atlas.SEASONS:
        block = tier.samples[season]
        lines.extend(_wrap(
            atlas.sample_line(season, block) + ": "
            + ", ".join(str(year) for year in block["warm_events"]),
            indent="    ",
        ))
    if tier.in_progress:
        lines.extend(_wrap(
            "Left out as still under way when the grids were built: "
            + ", ".join(str(year) for year in tier.in_progress)
            + ". The composite is what past events did.",
            indent="    ",
        ))

    lines.append("")
    lines.append(f"  {'place':<12}{'season':>7}{'mm/day':>8}{'of normal':>10}"
                 f"{'t':>7}{'needs':>6}  {'verdict':<16}{'degC':>8}")
    rows: list[tuple[str, ...]] = []
    for local in tier.anchors:
        # Every column in the row's own season, temperature included.
        best = local.strongest
        if best is None:
            continue
        percent = best.precip.percent
        rows.append((
            _ascii(local.title.split(",")[0])[:12],
            best.season,
            f"{best.precip.value:+.2f}" if best.precip.value is not None else "-",
            f"{percent:+.0f}%" if percent is not None else "-",
            f"{best.precip.t:+.2f}" if best.precip.t is not None else "-",
            f"{best.precip.crit:.2f}",
            best.precip.direction,
            atlas.temperature_text(best.air) or "-",
        ))
    for row in rows:
        lines.append(f"  {row[0]:<12}{row[1]:>7}{row[2]:>8}{row[3]:>10}"
                     f"{row[4]:>7}{row[5]:>6}  {row[6]:<16}{row[7]:>8}")
    lines.append("")
    lines.extend(_wrap(atlas.NO_SIGNAL + " " + atlas.PARENTHESES))

    for lesson in atlas.lessons(tier):
        lines.append("")
        lines.extend(_wrap(lesson))
    lines.append("")
    lines.extend(_wrap(
        "The interactive atlas resolves any point on Earth to its cell and its "
        "nearest named place, at four levels of coastline, border and river "
        "detail: output/atlas.html."
    ))
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
    "cyclones": _section_cyclones,
    "outlook": _section_outlook,
    "stormfury": _section_stormfury,
    "atlas": _section_atlas,
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
