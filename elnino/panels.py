"""The panels added for the advanced system: subsurface, forecast, skill, hazard.

Each function returns a self-contained fragment of HTML. The chart type in
every case was chosen from the job the data does, not from what looks
impressive:

  * phase space - a *connected scatter*, because the recharge oscillator's
    whole content is the shape of a loop in two variables. A pair of time
    series would hide the one thing worth seeing.
  * forecast - a *fan*, because the spread is the message. A single line
    through the middle would be a more confident claim than the verification
    supports.
  * Walker indicators - *diverging bars* on a shared zero, because the
    question is polarity and agreement across a dozen indices at once.
  * skill - *bars*, because these are independent measurements at each lead,
    not a continuous quantity that can be interpolated between leads.
  * WWV against Nino-3.4 - *small multiples sharing an x axis*, never a
    second y axis. The two have different units, and a dual-axis chart lets
    the author choose the apparent lead by choosing the scales.

Every chart here carries a legend when it has two or more series, direct
labels on the values that matter, a hover layer, and a table view twin.
"""

from __future__ import annotations

from .alerts import CRITICAL, INFO, WARNING, WATCH
from .svg import Plot, _hit, _legend, esc, nice_ticks, table

PHASE_MONTHS = 48
SPARK_MONTHS = 180


def _series_path(points: list[tuple[float, float]]) -> str:
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points)


# --- subsurface: the recharge oscillator in phase space ----------------------
def chart_phase(state) -> str:
    """The (SST, heat content) loop, which is the physical model made visible."""
    sub = state.subsurface
    if not sub or len(sub.trajectory) < 12:
        return ""

    def sigma(values: list[float]) -> tuple[float, float]:
        mean = sum(values) / len(values)
        spread = (sum((v - mean) ** 2 for v in values) / max(len(values) - 1, 1)) ** 0.5
        return mean, spread or 1.0

    sst_mean, sst_sd = sigma([p.sst for p in sub.trajectory])
    heat_mean, heat_sd = sigma([p.heat for p in sub.trajectory])
    track = sub.trajectory[-PHASE_MONTHS:]
    xs = [(p.sst - sst_mean) / sst_sd for p in track]
    ys = [(p.heat - heat_mean) / heat_sd for p in track]
    limit = max(2.5, max(abs(v) for v in xs + ys) * 1.12)

    plot = Plot(560, 470, (26, 108, 46, 54))
    plot.domain(-limit, limit, -limit, limit)

    # Quadrant furniture. The loop runs clockwise; naming the quadrants is what
    # turns a squiggle into a diagnosis.
    plot.add(
        f'<line x1="{plot.sx(-limit):.1f}" y1="{plot.sy(0):.1f}" '
        f'x2="{plot.sx(limit):.1f}" y2="{plot.sy(0):.1f}" stroke="var(--axis)" stroke-width="1"/>'
        f'<line x1="{plot.sx(0):.1f}" y1="{plot.sy(-limit):.1f}" '
        f'x2="{plot.sx(0):.1f}" y2="{plot.sy(limit):.1f}" stroke="var(--axis)" stroke-width="1"/>'
    )
    quadrants = [
        (limit * 0.52, limit * 0.52, "warm + recharged", "start"),
        (limit * 0.52, -limit * 0.62, "warm, discharging", "start"),
        (-limit * 0.95, -limit * 0.62, "cool + discharged", "start"),
        (-limit * 0.95, limit * 0.52, "cool, recharging", "start"),
    ]
    for qx, qy, label, anchor in quadrants:
        plot.add(
            f'<text x="{plot.sx(qx):.1f}" y="{plot.sy(qy):.1f}" text-anchor="{anchor}" '
            f'class="quad">{esc(label)}</text>'
        )

    # The trail fades with age: a single hue, light to dark, is the correct
    # encoding for "how long ago", and it keeps the categorical slots free.
    points = [(plot.sx(x), plot.sy(y)) for x, y in zip(xs, ys)]
    for index in range(1, len(points)):
        age = index / (len(points) - 1)
        plot.add(
            f'<line x1="{points[index - 1][0]:.1f}" y1="{points[index - 1][1]:.1f}" '
            f'x2="{points[index][0]:.1f}" y2="{points[index][1]:.1f}" '
            f'stroke="var(--s1)" stroke-width="2" stroke-linecap="round" '
            f'opacity="{0.14 + 0.86 * age:.2f}"/>'
        )

    # Year ticks along the trail, so the loop can be read as a clock. The
    # January dot is always drawn; its label is dropped where it would land on
    # the "now" marker or on another year, since a collided label reads as
    # neither year rather than as both.
    current_x, current_y = points[-1]
    placed: list[tuple[float, float]] = [(current_x, current_y - 15)]
    seen: set[int] = set()
    for point, (x, y) in zip(track, points):
        if point.when.year in seen or point.when.month != 1:
            continue
        seen.add(point.when.year)
        plot.add(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="var(--surface)" '
            f'stroke="var(--s1)" stroke-width="2"/>'
        )
        label_x, label_y = x + 7, y - 6
        if any(abs(label_x - px) < 30 and abs(label_y - py) < 13 for px, py in placed):
            continue
        placed.append((label_x, label_y))
        plot.add(
            f'<text x="{label_x:.1f}" y="{label_y:.1f}" class="tiny">{point.when.year}</text>'
        )


    plot.add(
        f'<circle cx="{current_x:.1f}" cy="{current_y:.1f}" r="8" fill="var(--s2)" '
        f'stroke="var(--surface)" stroke-width="2"/>'
    )
    plot.add(
        f'<text x="{current_x:.1f}" y="{current_y - 15:.1f}" text-anchor="middle" '
        f'class="pointlabel">now</text>'
    )

    for point, (x, y), sx_, hy_ in zip(track, points, xs, ys):
        plot.add(_hit(
            x, y, point.when.strftime("%b %Y"),
            f"Nino-3.4 {point.sst:+.2f} °C ({sx_:+.2f}σ)  ·  "
            f"WWV {point.heat:+.2f} ({hy_:+.2f}σ)",
        ))

    plot.add(
        f'<text x="{plot.sx(0):.1f}" y="{plot.h - 12}" text-anchor="middle" '
        f'class="axislabel">Nino-3.4 anomaly (standard deviations) →</text>'
    )
    plot.add(
        f'<text transform="translate(16 {plot.sy(0):.1f}) rotate(-90)" text-anchor="middle" '
        f'class="axislabel">warm water volume (σ) →</text>'
    )
    for tick in nice_ticks(-limit, limit, 5):
        if abs(tick) < 1e-9:
            continue
        plot.add(
            f'<text x="{plot.sx(tick):.1f}" y="{plot.sy(0) + 15:.1f}" text-anchor="middle" '
            f'class="tick">{tick:+.0f}</text>'
            f'<text x="{plot.sx(0) - 8:.1f}" y="{plot.sy(tick) + 4:.1f}" text-anchor="end" '
            f'class="tick">{tick:+.0f}</text>'
        )

    rows = [
        [t.when.strftime("%b %Y"), f"{t.sst:+.2f}", f"{x:+.2f}",
         f"{t.heat:+.2f}", f"{y:+.2f}"]
        for t, x, y in reversed(list(zip(track, xs, ys)))
    ]
    confidence = "" if sub.phase_confident else " (close to a boundary, so read it as indicative)"
    return f"""
<section class="card">
  <h2>Recharge oscillator &mdash; where the event sits on its own cycle</h2>
  <p class="caption">Last {len(track)} months of Nino-3.4 against equatorial warm water volume,
    both as standard deviations. The system circles this plane <strong>clockwise</strong>:
    heat accumulates, converts to surface warmth, discharges, and the ocean cools.
    Position on the loop predicts what happens next far better than amplitude does.</p>
  <div class="chart">{plot.svg(
      'Recharge oscillator phase space',
      'Connected scatter of Nino-3.4 anomaly against warm water volume anomaly, both in '
      'standard deviations, tracing the last four years. The current position is marked.')}</div>
  <div class="phasestate">
    <span class="chip chip-now">{esc(sub.phase_name)}</span>
    <span class="phasenote">{esc(sub.phase_note)}{esc(confidence)}</span>
  </div>
  {table(f'phase-space trajectory ({len(track)} months, newest first)',
         ['month', 'Nino-3.4 (degC)', 'Nino-3.4 (sigma)',
          'WWV (10^14 m3)', 'WWV (sigma)'], rows)}
</section>"""


# --- subsurface: WWV and SST as small multiples ------------------------------
def chart_heat(state) -> str:
    """Two panels, one x axis, never two y axes."""
    sub = state.subsurface
    if not sub or len(sub.trajectory) < 24:
        return ""
    track = sub.trajectory[-SPARK_MONTHS:]

    plot = Plot(900, 340, (18, 92, 34, 58))
    top_h, gap = 132.0, 30.0
    x_lo, x_hi = 0, len(track) - 1
    plot.domain(x_lo, x_hi, 0, 1)

    def panel(values: list[float], y_top: float, height: float, colour: str,
              fmt: str, title: str) -> list[tuple[float, float]]:
        lo, hi = min(values), max(values)
        span = (hi - lo) or 1.0
        lo, hi = lo - span * 0.12, hi + span * 0.12

        def sy(value: float) -> float:
            return y_top + (hi - value) / (hi - lo) * height

        for tick in nice_ticks(lo, hi, 4):
            y = sy(tick)
            stroke = "var(--axis)" if abs(tick) < 1e-9 else "var(--grid)"
            plot.add(
                f'<line x1="{plot.left:.1f}" y1="{y:.1f}" x2="{plot.left + plot.plot_w:.1f}" '
                f'y2="{y:.1f}" stroke="{stroke}" stroke-width="1"/>'
                f'<text x="{plot.left - 8:.1f}" y="{y + 4:.1f}" text-anchor="end" '
                f'class="tick">{esc(fmt.format(tick))}</text>'
            )
        pts = [(plot.sx(i), sy(v)) for i, v in enumerate(values)]
        plot.add(
            f'<path d="{_series_path(pts)}" fill="none" stroke="{colour}" stroke-width="2" '
            f'stroke-linejoin="round" stroke-linecap="round"/>'
        )
        plot.add(
            f'<text x="{plot.left:.1f}" y="{y_top - 6:.1f}" class="panellabel">{esc(title)}</text>'
        )
        end = pts[-1]
        plot.add(
            f'<circle cx="{end[0]:.1f}" cy="{end[1]:.1f}" r="4.5" fill="{colour}" '
            f'stroke="var(--surface)" stroke-width="2"/>'
            f'<text x="{end[0] + 8:.1f}" y="{end[1] + 4:.1f}" class="pointlabel" '
            f'fill="var(--ink)">{esc(fmt.format(values[-1]))}</text>'
        )
        return pts

    heat_pts = panel([p.heat for p in track], plot.top, top_h, "var(--s1)",
                     "{:+.1f}", "Warm water volume anomaly (10¹⁴ m³)")
    sst_pts = panel([p.sst for p in track], plot.top + top_h + gap, top_h, "var(--s2)",
                    "{:+.1f}", "Nino-3.4 anomaly (°C)")

    step = max(1, len(track) // 10)
    for index in range(0, len(track), step):
        point = track[index]
        plot.add(
            f'<text x="{plot.sx(index):.1f}" y="{plot.h - 12}" text-anchor="middle" '
            f'class="tick">{point.when.strftime("%b %y")}</text>'
        )
    for index, point in enumerate(track):
        plot.add(_hit(heat_pts[index][0], heat_pts[index][1],
                      point.when.strftime("%b %Y"),
                      f"WWV {point.heat:+.2f} × 10¹⁴ m³"))
        plot.add(_hit(sst_pts[index][0], sst_pts[index][1],
                      point.when.strftime("%b %Y"),
                      f"Nino-3.4 {point.sst:+.2f} °C"))

    lead = (
        f"Measured lead {sub.lead_months} months (r = {sub.lead_correlation:.2f})"
        if sub.lead_months else "Lead not resolvable from this record"
    )
    rows = [
        [p.when.strftime("%b %Y"), f"{p.heat:+.2f}", f"{p.sst:+.2f}"]
        for p in reversed(track[-36:])
    ]
    return f"""
<section class="card">
  <h2>Heat content leads the surface</h2>
  <p class="caption">Two panels on one shared time axis &mdash; deliberately not two y axes on
    one panel, which would let the choice of scales manufacture any apparent lead you like.
    {esc(lead)}, computed from this record at run time.</p>
  {_legend([('Warm water volume', 'var(--s1)'), ('Nino-3.4 SST', 'var(--s2)')])}
  <div class="chart">{plot.svg(
      'Warm water volume and Nino-3.4 anomaly',
      'Two stacked line charts sharing a time axis: equatorial warm water volume anomaly '
      'above, Nino-3.4 sea surface temperature anomaly below.')}</div>
  {table('warm water volume and Nino-3.4 (most recent 36 months)',
         ['month', 'WWV anomaly (10^14 m3)', 'Nino-3.4 (degC)'], rows)}
</section>"""


# --- forecast fan ------------------------------------------------------------
def _declutter(
    labels: list[tuple[float, float, str]], spacing: float = 14.0
) -> list[tuple[float, float, str, float]]:
    """Shift overlapping end-labels apart, keeping their original order.

    One pass down the list pushing each label below the one before it, then one
    pass back up to absorb the shift, so a crowded group spreads around its own
    centre instead of drifting downward off the plot.
    """
    if not labels:
        return []
    ordered = sorted(labels, key=lambda item: item[1])
    shifted = [item[1] for item in ordered]
    for index in range(1, len(shifted)):
        shifted[index] = max(shifted[index], shifted[index - 1] + spacing)
    drift = (shifted[-1] - ordered[-1][1]) / 2.0
    if drift > 0:
        shifted = [value - drift for value in shifted]
    return [
        (item[0], item[1], item[2], value + 3.0)
        for item, value in zip(ordered, shifted)
    ]


def chart_forecast(state) -> str:
    forecast = state.forecast
    oni = state.series.get("oni") or []
    if not forecast or not forecast.projections or len(oni) < 12:
        return ""

    history = oni[-18:]
    projections = forecast.projections
    n_hist = len(history)
    total = n_hist + len(projections)

    lows = [p.low for p in projections]
    highs = [p.high for p in projections]
    members = forecast.analog_members or {}
    member_values = [v for track in members.values() for v in track]
    y_lo = min([v.value for v in history] + lows + member_values + [0.0]) - 0.35
    y_hi = max([v.value for v in history] + highs + member_values) + 0.45

    plot = Plot(900, 420, (22, 118, 46, 54))
    plot.domain(0, total - 1, y_lo, y_hi)
    plot.gridlines(nice_ticks(y_lo, y_hi, 6), "{:+.1f}")

    # Threshold bands: the classification tiers are the reason anyone reads this
    # chart, so they are drawn, not left to the reader's memory.
    for level, name in ((0.5, "weak"), (1.0, "moderate"), (1.5, "strong"), (2.0, "very strong")):
        if y_lo < level < y_hi:
            y = plot.sy(level)
            plot.add(
                f'<line x1="{plot.left:.1f}" y1="{y:.1f}" x2="{plot.left + plot.plot_w:.1f}" '
                f'y2="{y:.1f}" stroke="var(--axis)" stroke-width="1" stroke-dasharray="2 4"/>'
                f'<text x="{plot.left + 5:.1f}" y="{y - 5:.1f}" '
                f'class="tiny">{esc(name)}</text>'
            )

    # Observed.
    hist_pts = [(plot.sx(i), plot.sy(v.value)) for i, v in enumerate(history)]
    plot.add(
        f'<path d="{_series_path(hist_pts)}" fill="none" stroke="var(--s1)" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>'
    )

    # The band. Anchored to the last observation so it opens from the present
    # rather than floating free of it.
    anchor = (n_hist - 1, history[-1].value)
    upper = [(plot.sx(anchor[0]), plot.sy(anchor[1]))]
    lower = [(plot.sx(anchor[0]), plot.sy(anchor[1]))]
    for offset, projection in enumerate(projections):
        x = plot.sx(n_hist + offset)
        upper.append((x, plot.sy(projection.high)))
        lower.append((x, plot.sy(projection.low)))
    band = _series_path(upper) + " L" + " L".join(
        f"{x:.1f} {y:.1f}" for x, y in reversed(lower)
    ) + " Z"
    plot.add(f'<path d="{band}" fill="var(--s2)" opacity="0.16" stroke="none"/>')

    # Analog members, recessive: they are context for the band, not headline
    # series, so they take a muted ink rather than a categorical slot.
    end_labels: list[tuple[float, float, str]] = []
    for name, track in members.items():
        pts = [(plot.sx(anchor[0]), plot.sy(anchor[1]))]
        for offset, projection in enumerate(projections):
            if offset < len(track):
                pts.append((plot.sx(n_hist + offset), plot.sy(track[offset])))
        if len(pts) > 2:
            plot.add(
                f'<path d="{_series_path(pts)}" fill="none" stroke="var(--muted)" '
                f'stroke-width="1.5" opacity="0.55" stroke-linejoin="round"/>'
            )
            end_labels.append((pts[-1][0], pts[-1][1], name))

    # Converging analogs would otherwise stack their labels on one another. Push
    # them apart, then draw a leader line back to the track each one names.
    for x, y, name, shifted in _declutter(end_labels, spacing=14.0):
        if abs(shifted - y) > 1.5:
            plot.add(
                f'<path d="M{x:.1f} {y:.1f} L{x + 6:.1f} {y:.1f} '
                f'L{x + 10:.1f} {shifted - 3.5:.1f}" fill="none" stroke="var(--axis)" '
                f'stroke-width="1"/>'
            )
        plot.add(
            f'<text x="{x + 12:.1f}" y="{shifted:.1f}" class="tiny">{esc(name)}</text>'
        )

    # Ensemble mean.
    mean_pts = [(plot.sx(anchor[0]), plot.sy(anchor[1]))]
    for offset, projection in enumerate(projections):
        mean_pts.append((plot.sx(n_hist + offset), plot.sy(projection.mean)))
    plot.add(
        f'<path d="{_series_path(mean_pts)}" fill="none" stroke="var(--s2)" stroke-width="2" '
        f'stroke-dasharray="6 3" stroke-linejoin="round" stroke-linecap="round"/>'
    )

    for index, (x, y) in enumerate(mean_pts[1:]):
        plot.add(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="var(--s2)" '
            f'stroke="var(--surface)" stroke-width="2"/>'
        )
        projection = projections[index]
        plot.add(_hit(
            x, y, projection.label,
            f"{projection.mean:+.2f} °C  (80% band {projection.low:+.2f} to {projection.high:+.2f})",
            "  ·  ".join(f"{k} {v:+.2f}" for k, v in sorted(projection.methods.items())),
        ))
    for index, value in enumerate(history):
        plot.add(_hit(hist_pts[index][0], hist_pts[index][1], value.label,
                      f"{value.value:+.2f} °C observed"))

    peak = forecast.peak
    if peak:
        offset = projections.index(peak)
        px, py = mean_pts[offset + 1]
        plot.add(
            f'<text x="{px:.1f}" y="{py - 14:.1f}" text-anchor="middle" '
            f'class="pointlabel">{peak.mean:+.2f} peak</text>'
        )

    # x labels: observed seasons then projected ones.
    labels = [v.label for v in history] + [p.label for p in projections]
    step = max(1, total // 9)
    for index in range(0, total, step):
        plot.add(
            f'<text x="{plot.sx(index):.1f}" y="{plot.h - 12}" text-anchor="middle" '
            f'class="tick">{esc(labels[index])}</text>'
        )
    divide = plot.sx(n_hist - 1)
    plot.add(
        f'<line x1="{divide:.1f}" y1="{plot.top:.1f}" x2="{divide:.1f}" '
        f'y2="{plot.top + plot.plot_h:.1f}" stroke="var(--ink2)" stroke-width="1"/>'
        f'<text x="{divide + 6:.1f}" y="{plot.top + 12:.1f}" class="tiny">forecast →</text>'
    )

    probability_rows = "".join(
        f'<div class="prob"><span class="prob-label">P(peak ≥ {threshold:+.1f} °C)</span>'
        f'<span class="prob-track"><span class="prob-fill" style="width:{value * 100:.1f}%">'
        f'</span></span><span class="prob-val">{value * 100:.0f}%</span></div>'
        for threshold, value in sorted(forecast.peak_probability.items())
    )
    rows = [
        [f"+{p.lead}", p.label, f"{p.mean:+.2f}", f"{p.low:+.2f}", f"{p.high:+.2f}",
         f"{p.spread:.2f}"]
        + [f"{p.methods[m]:+.2f}" if m in p.methods else "—"
           for m in ("analog", "recharge", "persistence")]
        for p in projections
    ]
    notes = "".join(f"<li>{esc(note)}</li>" for note in forecast.notes)
    return f"""
<section class="card">
  <h2>Forecast</h2>
  <p class="caption">Three methods &mdash; analog ensemble, a nonlinear recharge oscillator and
    damped persistence &mdash; combined with weights taken from {esc(forecast.skill_source)}.
    The shaded fan is the 10th to 90th percentile; it is wide because the verification says
    it should be.</p>
  {_legend([('Observed ONI', 'var(--s1)'), ('Ensemble mean', 'var(--s2)'),
            ('80% range', 'var(--s2)'), ('Analog members', 'var(--muted)')])}
  <div class="chart">{plot.svg(
      'ENSO forecast fan chart',
      'Observed Oceanic Nino Index followed by a projected ensemble mean with a shaded '
      '10th-to-90th-percentile band and individual historical analog tracks.')}</div>
  <div class="probs">{probability_rows}</div>
  {'<ul class="warnlist">' + notes + '</ul>' if notes else ''}
  {table('forecast by lead',
         ['lead', 'season', 'mean', '10th', '90th', 'method spread',
          'analog', 'recharge', 'persistence'], rows)}
</section>"""


# --- atmosphere: Walker indicator panel --------------------------------------
def chart_walker(state) -> str:
    atmosphere = state.atmosphere
    if not atmosphere or not atmosphere.indicators:
        return ""
    indicators = atmosphere.indicators
    limit = max(3.0, max(abs(i.score) for i in indicators) * 1.1)

    row_h, gap = 26, 6
    height = 46 + len(indicators) * (row_h + gap)
    plot = Plot(900, height, (30, 150, 16, 250))
    plot.domain(-limit, limit, 0, 1)

    zero = plot.sx(0.0)
    for tick in nice_ticks(-limit, limit, 5):
        x = plot.sx(tick)
        stroke = "var(--axis)" if abs(tick) < 1e-9 else "var(--grid)"
        plot.add(
            f'<line x1="{x:.1f}" y1="{plot.top - 6:.1f}" x2="{x:.1f}" '
            f'y2="{height - plot.bottom:.1f}" stroke="{stroke}" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="{plot.top - 12:.1f}" text-anchor="middle" '
            f'class="tick">{tick:+.0f}σ</text>'
        )
    plot.add(
        f'<text x="{plot.sx(-limit * 0.5):.1f}" y="{height - 2:.1f}" text-anchor="middle" '
        f'class="tiny">← La Nina-like</text>'
        f'<text x="{plot.sx(limit * 0.5):.1f}" y="{height - 2:.1f}" text-anchor="middle" '
        f'class="tiny">El Nino-like →</text>'
    )

    for index, indicator in enumerate(indicators):
        y = plot.top + index * (row_h + gap)
        x = plot.sx(indicator.score)
        # Diverging pair by polarity, never by rank, so a re-sort cannot
        # repaint a bar.
        colour = "var(--warm)" if indicator.score >= 0 else "var(--cool)"
        left, width = (zero, x - zero) if x >= zero else (x, zero - x)
        width = max(width, 1.5)
        opacity = "0.4" if indicator.stale else "1"
        # 4px rounded data-end, square against the baseline.
        plot.add(
            f'<rect x="{left:.1f}" y="{y:.1f}" width="{width:.1f}" height="{row_h}" '
            f'rx="4" fill="{colour}" opacity="{opacity}"/>'
        )
        if indicator.stale:
            plot.add(
                f'<rect x="{left:.1f}" y="{y:.1f}" width="{width:.1f}" height="{row_h}" '
                f'rx="4" fill="url(#hatch)" opacity="0.9"/>'
            )
        plot.add(
            f'<text x="{plot.left - 10:.1f}" y="{y + row_h / 2 + 4:.1f}" text-anchor="end" '
            f'class="rowlabel">{esc(indicator.name)}</text>'
        )
        suffix = " · stale" if indicator.stale else ""
        anchor = x + 8 if indicator.score >= 0 else x - 8
        align = "start" if indicator.score >= 0 else "end"
        plot.add(
            f'<text x="{anchor:.1f}" y="{y + row_h / 2 + 4:.1f}" text-anchor="{align}" '
            f'class="barvalue">{indicator.score:+.2f}σ{esc(suffix)}</text>'
        )
        plot.add(
            f'<rect class="hit" x="{plot.left:.1f}" y="{y:.1f}" '
            f'width="{plot.plot_w:.1f}" height="{row_h}" fill="transparent" tabindex="0" '
            f'data-label="{esc(indicator.name)} ({esc(indicator.label)})" '
            f'data-value="{indicator.score:+.2f} sigma  ·  raw {indicator.raw:+.2f}" '
            f'data-extra="{esc(indicator.meaning)}"></rect>'
        )

    rows = [
        [i.name, i.label, f"{i.raw:+.2f}", f"{i.score:+.2f}",
         "yes" if i.supports_el_nino else "no", "stale" if i.stale else "current"]
        for i in indicators
    ]
    dissent = (
        ", ".join(f"{d.name} ({d.score:+.2f}σ)" for d in atmosphere.dissenters)
        or "none"
    )
    coupled = "Coupled" if atmosphere.coupled else "Not yet coupled"
    return f"""
<section class="card">
  <h2>Is the atmosphere coupled to the ocean?</h2>
  <p class="caption">Every index is re-signed so that <strong>positive means El Ni&ntilde;o-like</strong>,
    whatever its native convention, and standardised against its own calendar month.
    A warm ocean with a silent atmosphere is the 2014 failure mode, which is why these are
    reported separately from SST rather than blended into it.</p>
  {_legend([('El Niño-like (positive)', 'var(--warm)'),
            ('La Niña-like (negative)', 'var(--cool)')])}
  <div class="chart">{plot.svg(
      'Atmospheric indicators, standardised',
      'Diverging horizontal bars, one per atmospheric index, showing standard-score '
      'anomalies signed so positive is El Nino-like.')}</div>
  <div class="walkerfoot">
    <span class="chip">{esc(coupled)} &middot; composite {atmosphere.walker_index:+.2f}&sigma;</span>
    <span class="chip chip-quiet">{atmosphere.agreement * 100:.0f}% agreement</span>
    <span class="phasenote">Dissenting: {esc(dissent)}</span>
  </div>
  {table('atmospheric indicators',
         ['indicator', 'as of', 'raw value', 'standard score',
          'supports El Nino', 'currency'], rows)}
</section>"""


# --- verification ------------------------------------------------------------
def chart_skill(state) -> str:
    skill = state.skill
    if not skill or not skill.leads:
        return ""

    leads = skill.leads
    plot = Plot(430, 306, (32, 20, 44, 46))
    top = max(s.rmse for s in leads) * 1.25
    plot.domain(-0.6, len(leads) - 0.4, 0, top)
    plot.gridlines(nice_ticks(0, top, 5), "{:.1f}")
    plot.add(
        '<text x="0" y="13" class="panellabel">Error by lead &mdash; RMSE, degrees C '
        '(lower is better)</text>'
    )

    slot = plot.plot_w / len(leads)
    bar_w = slot - 4  # a 2px surface gap each side, per the mark spec
    for index, lead in enumerate(leads):
        x = plot.sx(index) - bar_w / 2
        y = plot.sy(lead.rmse)
        height = plot.sy(0) - y
        colour = "var(--s1)" if lead.useful else "var(--muted)"
        plot.add(
            f'<path d="M{x:.1f} {plot.sy(0):.1f} V{y + 4:.1f} q0 -4 4 -4 '
            f'H{x + bar_w - 4:.1f} q4 0 4 4 V{plot.sy(0):.1f} Z" fill="{colour}"/>'
        )
        plot.add(
            f'<text x="{x + bar_w / 2:.1f}" y="{plot.h - 26:.1f}" text-anchor="middle" '
            f'class="tick">+{lead.lead}</text>'
        )
        plot.add(
            f'<rect class="hit" x="{x:.1f}" y="{plot.top:.1f}" width="{bar_w:.1f}" '
            f'height="{plot.plot_h:.1f}" fill="transparent" tabindex="0" '
            f'data-label="Lead +{lead.lead} months" '
            f'data-value="RMSE {lead.rmse:.2f} °C · correlation {lead.acc:.2f}" '
            f'data-extra="{lead.count} verified forecasts"></rect>'
        )
    plot.add(
        f'<text x="{plot.sx((len(leads) - 1) / 2):.1f}" y="{plot.h - 8}" text-anchor="middle" '
        f'class="axislabel">forecast lead (months)</text>'
    )

    # Skill by target season: the spring barrier, measured.
    seasons = sorted(skill.by_target_season.items(), key=lambda kv: -kv[1])
    season_plot = Plot(430, 306, (32, 20, 44, 46))
    season_plot.domain(-0.6, len(seasons) - 0.4, 0, 1.0)
    season_plot.gridlines(nice_ticks(0, 1.0, 5), "{:.1f}")
    season_plot.add(
        '<text x="0" y="13" class="panellabel">Correlation at 6 months lead, by target '
        'season (higher is better)</text>'
    )
    slot = season_plot.plot_w / max(len(seasons), 1)
    bar_w = slot - 4
    for index, (season, acc) in enumerate(seasons):
        x = season_plot.sx(index) - bar_w / 2
        y = season_plot.sy(acc)
        barrier = season in skill.barrier_seasons
        colour = "var(--s2)" if barrier else "var(--s1)"
        season_plot.add(
            f'<path d="M{x:.1f} {season_plot.sy(0):.1f} V{y + 4:.1f} q0 -4 4 -4 '
            f'H{x + bar_w - 4:.1f} q4 0 4 4 V{season_plot.sy(0):.1f} Z" fill="{colour}"/>'
        )
        season_plot.add(
            f'<text x="{x + bar_w / 2:.1f}" y="{season_plot.h - 26:.1f}" text-anchor="middle" '
            f'class="tick" transform="rotate(-42 {x + bar_w / 2:.1f} '
            f'{season_plot.h - 26:.1f})">{esc(season)}</text>'
        )
        season_plot.add(
            f'<rect class="hit" x="{x:.1f}" y="{season_plot.top:.1f}" width="{bar_w:.1f}" '
            f'height="{season_plot.plot_h:.1f}" fill="transparent" tabindex="0" '
            f'data-label="Forecasting {esc(season)}" '
            f'data-value="correlation {acc:.2f} at 6 months lead" '
            f'data-extra="{"inside the spring predictability barrier" if barrier else ""}">'
            f'</rect>'
        )
    threshold_y = season_plot.sy(0.5)
    season_plot.add(
        f'<line x1="{season_plot.left:.1f}" y1="{threshold_y:.1f}" '
        f'x2="{season_plot.left + season_plot.plot_w:.1f}" y2="{threshold_y:.1f}" '
        f'stroke="var(--ink2)" stroke-width="1" stroke-dasharray="4 3"/>'
        f'<text x="{season_plot.left + season_plot.plot_w - 2:.1f}" '
        f'y="{threshold_y - 6:.1f}" text-anchor="end" '
        f'class="tiny">useful-skill threshold</text>'
    )

    lead_rows = [
        [f"+{s.lead}", f"{s.rmse:.2f}", f"{s.acc:.2f}", f"{s.bias:+.2f}", str(s.count),
         f"{s.by_method.get('persistence', float('nan')):.2f}",
         f"{s.by_method.get('recharge', float('nan')):.2f}",
         "yes" if s.useful else "no"]
        for s in leads
    ]
    season_rows = [[season, f"{acc:.2f}",
                    "barrier" if season in skill.barrier_seasons else ""]
                   for season, acc in seasons]
    return f"""
<section class="card">
  <h2>How much is that forecast worth?</h2>
  <p class="caption">Hindcast across {skill.sample_years} years with the verification year held
    out of every fit, so none of this is in-sample. Useful horizon
    <strong>{skill.horizon} months</strong>. The right-hand panel is the spring predictability
    barrier as measured here, not as asserted from the literature: forecasts that must cross
    boreal spring lose {skill.barrier_drop:.2f} of correlation.</p>
  <div class="twoup">
    <div>
      {_legend([('Inside the useful horizon', 'var(--s1)'),
                ('Beyond it', 'var(--muted)')])}
      <div class="chart">{plot.svg(
          'Forecast error by lead time',
          'Bar chart of root-mean-square error in degrees Celsius against forecast lead in '
          'months; error grows with lead.')}</div>
    </div>
    <div>
      {_legend([('Clear of boreal spring', 'var(--s1)'),
                ('Inside the spring barrier', 'var(--s2)')])}
      <div class="chart">{season_plot.svg(
          'Forecast correlation by target season',
          'Bar chart of anomaly correlation at six months lead for each target season, '
          'showing the collapse for seasons reached across boreal spring.')}</div>
    </div>
  </div>
  {table('verification by lead',
         ['lead', 'RMSE (degC)', 'correlation', 'bias', 'forecasts scored',
          'persistence RMSE', 'recharge RMSE', 'useful'], lead_rows)}
  {table('correlation at 6-month lead by target season',
         ['target season', 'correlation', 'note'], season_rows)}
</section>"""


# --- alerts ------------------------------------------------------------------
# Keys are the level constants from ``alerts``, which are lowercase. A
# mismatch here shows up as a green dot on a critical alert, so it is worth
# keeping the two in the same shape.
_ALERT_STATUS = {CRITICAL: "critical", WARNING: "serious",
                 WATCH: "warning", INFO: "good"}

_ICON_ALARM = (
    '<svg class="statusicon" viewBox="0 0 16 16" aria-hidden="true">'
    '<path d="M8 1.6 15 14H1z" fill="currentColor"/>'
    '<rect x="7.1" y="5.6" width="1.8" height="4.6" rx="0.9" fill="var(--surface)"/>'
    '<circle cx="8" cy="11.9" r="1" fill="var(--surface)"/></svg>'
)
_ICON_DOT = (
    '<svg class="statusicon" viewBox="0 0 16 16" aria-hidden="true">'
    '<circle cx="8" cy="8" r="6.4" fill="currentColor"/></svg>'
)


def alert_feed(state) -> str:
    alert_set = state.alert_set
    if not alert_set.alerts and not alert_set.cleared:
        return ""
    items = []
    for alert in alert_set.alerts:
        status = _ALERT_STATUS.get(alert.level, "good")
        icon = _ICON_ALARM if status in ("critical", "serious") else _ICON_DOT
        new = '<span class="chip chip-new">new</span>' if alert.is_new else ""
        since = (
            f'<span class="alert-since">standing since {esc(alert.first_seen[:10])}</span>'
            if alert.first_seen and not alert.is_new else ""
        )
        items.append(
            f'<li class="alert" data-status="{status}">'
            f'<span class="alert-level">{icon}<span>{esc(alert.level)}</span></span>'
            f'<div class="alert-body"><div class="alert-title">{esc(alert.title)}{new}</div>'
            f'<p>{esc(alert.detail)}</p>{since}</div></li>'
        )
    cleared = (
        f'<p class="note">Cleared this run: {esc(", ".join(alert_set.cleared))}</p>'
        if alert_set.cleared else ""
    )
    rows = [[a.level, a.title, a.kind, "new" if a.is_new else "standing",
             (a.first_seen or "")[:19]] for a in alert_set.alerts]
    return f"""
<section class="card">
  <h2>Alerts</h2>
  <p class="caption">Raised against thresholds and against the previous run held in the local
    database, so an alert fires once when the condition appears and clears itself when it
    lifts. Severity colour never travels alone: each carries an icon and a written level.</p>
  <ul class="alerts">{''.join(items)}</ul>
  {cleared}
  {table('open alerts', ['level', 'alert', 'kind', 'state', 'first seen'], rows)}
</section>"""


# --- hazard outlook ----------------------------------------------------------
_LIKELIHOOD_STATUS = {
    "likely": "serious", "probable": "serious",
    "possible": "warning", "uncertain": "good", "unlikely": "good",
}


def impact_panel(state) -> str:
    assessment = state.impacts
    if not assessment or not assessment.active:
        return ""
    groups = []
    for area, items in assessment.by_area.items():
        cards = []
        for impact in items:
            link = impact.link
            status = _LIKELIHOOD_STATUS.get(impact.likelihood.strip(), "warning")
            flavour = (
                f'<p class="impact-flavour">{esc(impact.flavour_note)}</p>'
                if impact.flavour_note else ""
            )
            cards.append(
                f'<li class="impact" data-status="{status}">'
                f'<div class="impact-head"><span class="chip chip-{status}">'
                f'{esc(impact.likelihood.strip())}</span>'
                f'<strong>{esc(link.region)}</strong>'
                f'<span class="impact-window">{esc(link.window)}</span></div>'
                f'<div class="impact-effect">{esc(link.effect)}</div>'
                f'<p>{esc(link.detail)}</p>'
                f'<p class="impact-exposure"><span>Exposure</span> {esc(link.exposure)}</p>'
                f'{flavour}</li>'
            )
        groups.append(
            f'<div class="impact-group"><h3>{esc(area)}</h3>'
            f'<ul class="impacts">{"".join(cards)}</ul></div>'
        )

    watch = ""
    if assessment.watch:
        entries = "".join(
            f'<li>{esc(i.link.region)} &mdash; {esc(i.link.effect)} '
            f'<span class="tiny">(needs ONI about {i.link.min_intensity:+.1f} &deg;C)</span></li>'
            for i in assessment.watch
        )
        watch = f'<div class="impact-watch"><h3>On watch</h3><ul>{entries}</ul></div>'

    rows = [
        [i.link.area, i.link.region, i.link.effect, i.link.window,
         i.likelihood.strip(), i.link.confidence, f"{i.link.min_intensity:+.1f}",
         i.link.flavour]
        for i in assessment.active
    ]
    notes = "".join(f"<p>{esc(note)}</p>" for note in assessment.notes)
    return f"""
<section class="card">
  <h2>Hazard outlook</h2>
  <div class="disclaimer">{notes}</div>
  <p class="caption">Shifted odds from historical composites for a projected peak of
    <strong>{assessment.peak_oni:+.2f} &deg;C</strong> with a {esc(assessment.flavour)} structure.
    Not a forecast of any individual season, and not a substitute for your national
    meteorological service.</p>
  {''.join(groups)}
  {watch}
  {table('hazard outlook',
         ['area', 'region', 'effect', 'window', 'likelihood', 'confidence',
          'ONI threshold', 'flavour'], rows)}
</section>"""
