"""Self-contained HTML dashboard: inline SVG, no CDN, no build step.

Colour roles follow a validated palette (see README "Design notes"):
categorical slots for identity, a blue/red diverging pair for SST anomaly
polarity, and the reserved status palette for the power meter only. Every
chart ships a legend, selective direct labels, a hover tooltip and a table
view, so no value is reachable by colour alone.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .classify import Assessment, intensity_tier
from .parsers import MonthValue, SeasonValue, WeekObservation
from .sources import Fetched

from . import alerts, fields, geo, globe, panels, space3d
from .svg import (  # noqa: F401 - re-exported for the panel modules
    BAND_STATUS,
    DARK,
    LIGHT,
    Plot,
    _hit,
    _legend,
    esc,
    nice_ticks,
    table,
)


# --- chart 1: ONI / RONI seasonal trace -------------------------------------
def chart_oni(oni: list[SeasonValue], roni: list[SeasonValue], seasons: int = 66) -> str:
    recent_oni = oni[-seasons:]
    lookup = {(s.season, s.year): s.value for s in roni}
    plot = Plot(760, 330, (24, 92, 44, 52))

    values = [s.value for s in recent_oni] + [
        lookup[(s.season, s.year)] for s in recent_oni if (s.season, s.year) in lookup
    ]
    low, high = min(values + [-0.6]), max(values + [0.6])
    pad = (high - low) * 0.14
    plot.domain(0, len(recent_oni) - 1, low - pad, high + pad)
    plot.gridlines(nice_ticks(low - pad, high + pad, 6))

    # El Nino / La Nina threshold bands, drawn as recessive washes.
    for level, colour in ((0.5, "var(--warm)"), (-0.5, "var(--cool)")):
        y = plot.sy(level)
        plot.add(
            f'<line x1="{plot.left}" y1="{y:.1f}" x2="{plot.left + plot.plot_w:.1f}" '
            f'y2="{y:.1f}" stroke="{colour}" stroke-width="1" opacity="0.45" />'
        )
    plot.add(
        f'<text x="{plot.left + 6}" y="{plot.sy(0.5) - 6:.1f}" class="band-note">'
        f'El Nino threshold +0.5</text>'
    )

    # x-axis: one tick per calendar year
    seen: set[int] = set()
    for index, item in enumerate(recent_oni):
        if item.year not in seen:
            seen.add(item.year)
            x = plot.sx(index)
            plot.add(
                f'<text x="{x:.1f}" y="{plot.h - plot.bottom + 20:.1f}" text-anchor="middle" '
                f'class="tick">{item.year}</text>'
            )

    def path_for(points: list[tuple[float, float]]) -> str:
        return " ".join(
            ("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(points)
        )

    oni_points = [(plot.sx(i), plot.sy(s.value)) for i, s in enumerate(recent_oni)]
    roni_points = [
        (plot.sx(i), plot.sy(lookup[(s.season, s.year)]))
        for i, s in enumerate(recent_oni)
        if (s.season, s.year) in lookup
    ]

    plot.add(
        f'<path d="{path_for(roni_points)}" fill="none" stroke="var(--s2)" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" />'
    )
    plot.add(
        f'<path d="{path_for(oni_points)}" fill="none" stroke="var(--s1)" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" />'
    )

    # end markers with 2px surface ring, and selective direct labels
    for points, colour, label, value in (
        (roni_points, "var(--s2)", "RONI", lookup.get((recent_oni[-1].season, recent_oni[-1].year))),
        (oni_points, "var(--s1)", "ONI", recent_oni[-1].value),
    ):
        if not points or value is None:
            continue
        ex, ey = points[-1]
        plot.add(
            f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4.5" fill="{colour}" '
            f'stroke="var(--surface)" stroke-width="2" />'
        )
        plot.add(
            f'<text x="{ex + 10:.1f}" y="{ey + 4:.1f}" class="endlabel">'
            f'{esc(label)} {value:+.2f}</text>'
        )

    for index, item in enumerate(recent_oni):
        extra = ""
        key = (item.season, item.year)
        if key in lookup:
            extra = f"RONI {lookup[key]:+.2f} °C"
        plot.add(_hit(plot.sx(index), plot.sy(item.value), item.label, f"ONI {item.value:+.2f} °C", extra))

    return plot.svg(
        "ONI and RONI seasonal trace",
        "Three-month running Nino-3.4 anomaly (ONI) and the tropical-mean-adjusted RONI.",
    )


# --- chart 2: weekly Nino-region anomalies (diverging bars) -----------------
def chart_regions(assessment: Assessment) -> str:
    scale = assessment.scale
    if not scale or not scale.regions:
        return ""
    plot = Plot(760, 250, (18, 108, 40, 150))
    values = [r.anomaly for r in scale.regions]
    # Zero stays anchored (it is the meaningful midpoint of a diverging scale),
    # but the domain is not forced symmetric -- when every region is on one side
    # a mirrored axis would waste half the plot.
    low = min(values + [0.0]) - 0.35
    high = max(values + [0.0]) + 0.35
    plot.domain(low, high, 0, len(scale.regions))

    zero_x = plot.sx(0.0)
    band = plot.plot_h / len(scale.regions)
    bar_h = min(24.0, band - 14)  # cap thickness, leave the rest as air

    for index, region in enumerate(scale.regions):
        centre = plot.top + band * (index + 0.5)
        y = centre - bar_h / 2
        x = min(zero_x, plot.sx(region.anomaly))
        width = abs(plot.sx(region.anomaly) - zero_x)
        warm = region.anomaly >= 0
        colour = "var(--warm)" if warm else "var(--cool)"
        # 4px rounded data-end, square at the baseline
        radius = 4
        if warm:
            d = (
                f"M{x:.1f} {y:.1f} H{x + max(width - radius, 0):.1f} "
                f"a{radius} {radius} 0 0 1 {radius} {radius} V{y + bar_h - radius:.1f} "
                f"a{radius} {radius} 0 0 1 -{radius} {radius} H{x:.1f} Z"
            )
        else:
            d = (
                f"M{x + width:.1f} {y:.1f} H{x + radius:.1f} "
                f"a{radius} {radius} 0 0 0 -{radius} {radius} V{y + bar_h - radius:.1f} "
                f"a{radius} {radius} 0 0 0 {radius} {radius} H{x + width:.1f} Z"
            )
        plot.add(f'<path d="{d}" fill="{colour}" />')
        plot.add(
            f'<text x="{plot.left - 10:.1f}" y="{centre + 4:.1f}" text-anchor="end" '
            f'class="rowlabel">{esc(region.label)}</text>'
        )
        tip_x = plot.sx(region.anomaly) + (8 if warm else -8)
        anchor = "start" if warm else "end"
        plot.add(
            f'<text x="{tip_x:.1f}" y="{centre + 4:.1f}" text-anchor="{anchor}" '
            f'class="barvalue">{region.anomaly:+.2f} °C</text>'
        )
        plot.add(
            f'<rect class="hit" x="{plot.left:.1f}" y="{centre - band / 2:.1f}" '
            f'width="{plot.plot_w:.1f}" height="{band:.1f}" fill="transparent" tabindex="0" '
            f'data-label="{esc(region.label)}" '
            f'data-value="anomaly {region.anomaly:+.2f} °C" '
            f'data-extra="SST {region.sst:.1f} °C"></rect>'
        )

    plot.add(
        f'<line x1="{zero_x:.1f}" y1="{plot.top:.1f}" x2="{zero_x:.1f}" '
        f'y2="{plot.top + plot.plot_h:.1f}" stroke="var(--axis)" stroke-width="1" />'
    )
    for tick in nice_ticks(low, high, 5):
        x = plot.sx(tick)
        plot.add(
            f'<text x="{x:.1f}" y="{plot.h - plot.bottom + 20:.1f}" text-anchor="middle" '
            f'class="tick">{tick:+.1f}</text>'
        )
    return plot.svg(
        "Weekly Nino-region SST anomalies",
        "Anomaly by Nino region for the most recent CPC week; red warm, blue cool.",
    )


# --- chart 3: weekly Nino-3.4 trace -----------------------------------------
def chart_weekly(weeks: list[WeekObservation], count: int = 104) -> str:
    recent = weeks[-count:]
    if len(recent) < 2:
        return ""
    plot = Plot(760, 300, (22, 92, 44, 52))
    values = [w.nino34_anom for w in recent]
    low, high = min(values + [-0.6]), max(values + [0.6])
    pad = (high - low) * 0.14
    plot.domain(0, len(recent) - 1, low - pad, high + pad)
    plot.gridlines(nice_ticks(low - pad, high + pad, 6))

    y_half = plot.sy(0.5)
    plot.add(
        f'<line x1="{plot.left}" y1="{y_half:.1f}" x2="{plot.left + plot.plot_w:.1f}" '
        f'y2="{y_half:.1f}" stroke="var(--warm)" stroke-width="1" opacity="0.45" />'
    )

    points = [(plot.sx(i), plot.sy(w.nino34_anom)) for i, w in enumerate(recent)]
    line = " ".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(points))
    base = plot.sy(max(plot.y0, 0.0))
    plot.add(
        f'<path d="{line} L{points[-1][0]:.1f} {base:.1f} L{points[0][0]:.1f} {base:.1f} Z" '
        f'fill="var(--warm)" opacity="0.10" />'
    )
    plot.add(
        f'<path d="{line}" fill="none" stroke="var(--warm)" stroke-width="2" '
        f'stroke-linejoin="round" stroke-linecap="round" />'
    )

    seen: set[str] = set()
    for index, week in enumerate(recent):
        stamp = f"{week.week_ending:%b %y}"
        if week.week_ending.month % 3 == 0 and stamp not in seen:
            seen.add(stamp)
            plot.add(
                f'<text x="{plot.sx(index):.1f}" y="{plot.h - plot.bottom + 20:.1f}" '
                f'text-anchor="middle" class="tick">{esc(stamp)}</text>'
            )
        plot.add(
            _hit(
                plot.sx(index), plot.sy(week.nino34_anom), f"Week ending {week.label}",
                f"Nino-3.4 {week.nino34_anom:+.2f} °C", f"SST {week.nino34_sst:.1f} °C",
            )
        )

    ex, ey = points[-1]
    plot.add(
        f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4.5" fill="var(--warm)" '
        f'stroke="var(--surface)" stroke-width="2" />'
    )
    plot.add(
        f'<text x="{ex + 10:.1f}" y="{ey + 4:.1f}" class="endlabel">'
        f'{recent[-1].nino34_anom:+.2f} °C</text>'
    )
    return plot.svg(
        "Weekly Nino-3.4 anomaly",
        "Weekly Nino-3.4 SST anomaly over the last two years.",
    )


# --- chart 4: analog trajectories -------------------------------------------
def chart_analogs(assessment: Assessment) -> str:
    if not assessment.analogs or not assessment.episode:
        return ""
    plot = Plot(760, 320, (22, 118, 44, 52))
    series: list[tuple[str, list[float], str, bool]] = [
        (assessment.episode.name + " (now)", assessment.episode.values, "var(--s1)", True)
    ]
    for slot, analog in zip(("var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)"), assessment.analogs):
        series.append((analog.episode.name, analog.episode.values, slot, False))

    longest = max(len(values) for _, values, _, _ in series)
    every = [v for _, values, _, _ in series for v in values]
    low, high = min(every + [0.0]), max(every)
    pad = (high - low) * 0.14
    plot.domain(0, longest - 1, low - pad, high + pad)
    plot.gridlines(nice_ticks(low - pad, high + pad, 6))

    for step in range(longest):
        if step % 2 == 0:
            plot.add(
                f'<text x="{plot.sx(step):.1f}" y="{plot.h - plot.bottom + 20:.1f}" '
                f'text-anchor="middle" class="tick">{step}</text>'
            )
    plot.add(
        f'<text x="{plot.left + plot.plot_w / 2:.1f}" y="{plot.h - 6:.1f}" '
        f'text-anchor="middle" class="axistitle">seasons since the event crossed +0.5 °C</text>'
    )

    ends: list[tuple[float, float, str, str]] = []
    for name, values, colour, is_current in series:
        points = [(plot.sx(i), plot.sy(v)) for i, v in enumerate(values)]
        d = " ".join(("M" if i == 0 else "L") + f"{x:.1f} {y:.1f}" for i, (x, y) in enumerate(points))
        width = 2.6 if is_current else 2
        opacity = "1" if is_current else "0.85"
        plot.add(
            f'<path d="{d}" fill="none" stroke="{colour}" stroke-width="{width}" '
            f'opacity="{opacity}" stroke-linejoin="round" stroke-linecap="round" />'
        )
        ex, ey = points[-1]
        plot.add(
            f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4.5" fill="{colour}" '
            f'stroke="var(--surface)" stroke-width="2" />'
        )
        ends.append((ex, ey, name, colour))
        for index, value in enumerate(values):
            plot.add(
                _hit(plot.sx(index), plot.sy(value), name,
                     f"ONI {value:+.2f} °C", f"season {index} after onset")
            )

    # Events that finish at a similar ONI put their end-labels on top of each other.
    # Push them apart to a minimum gap and connect each back to its own line with a
    # leader, so a nudged label never looks like it belongs to its neighbour.
    ends.sort(key=lambda e: e[1])
    gap = 15.0
    placed: list[float] = []
    for _, ey, _, _ in ends:
        y = ey if not placed else max(ey, placed[-1] + gap)
        placed.append(y)
    overflow = placed[-1] - (plot.top + plot.plot_h) if placed else 0
    if overflow > 0:  # keep the stack inside the plot box
        placed = [y - overflow for y in placed]

    for (ex, ey, name, colour), label_y in zip(ends, placed):
        if abs(label_y - ey) > 1.5:
            plot.add(
                f'<path d="M{ex + 5.5:.1f} {ey:.1f} L{ex + 11:.1f} {ey:.1f} '
                f'L{ex + 15:.1f} {label_y:.1f} L{ex + 20:.1f} {label_y:.1f}" fill="none" '
                f'stroke="{colour}" stroke-width="1" opacity="0.7" />'
            )
            text_x = ex + 24
        else:
            text_x = ex + 9
        plot.add(
            f'<text x="{text_x:.1f}" y="{label_y + 4:.1f}" class="endlabel">{esc(name)}</text>'
        )

    return plot.svg(
        "Analog event trajectories",
        "The current event against its closest historical analogs, aligned on onset.",
    )


# --- power meter -------------------------------------------------------------
def power_meter(assessment: Assessment) -> str:
    power = assessment.power
    status = BAND_STATUS.get(power.band, "warning")
    rows = []
    for name, value in power.components.items():
        weight = power.weights[name]
        rows.append(
            f'<div class="comp"><span class="comp-name">{esc(name.replace("_", " "))}'
            f'<em>x{weight:.2f}</em></span>'
            f'<span class="comp-track"><span class="comp-fill" style="width:{value:.1f}%"></span></span>'
            f'<span class="comp-val">{value:.0f}</span></div>'
        )
    # Status colour never travels alone: icon + label accompany it.
    icon = (
        '<svg class="statusicon" viewBox="0 0 16 16" aria-hidden="true">'
        '<path d="M8 1.6 15 14H1z" fill="currentColor"/>'
        '<rect x="7.1" y="5.6" width="1.8" height="4.6" rx="0.9" fill="var(--surface)"/>'
        '<circle cx="8" cy="11.9" r="1" fill="var(--surface)"/></svg>'
        if status in ("critical", "serious")
        else '<svg class="statusicon" viewBox="0 0 16 16" aria-hidden="true">'
             '<circle cx="8" cy="8" r="6.4" fill="currentColor"/></svg>'
    )
    return f"""
<div class="meter" data-status="{esc(status)}">
  <div class="meter-head">
    <span class="meter-label">Composite power index</span>
    <span class="meter-band">{icon}<span>{esc(power.band)}</span></span>
  </div>
  <div class="meter-track"><div class="meter-fill" style="width:{power.value:.1f}%"></div></div>
  <div class="meter-scale"><span>0</span><span>50</span><span>100</span></div>
  <div class="comps">{''.join(rows)}</div>
  <p class="note">Derived diagnostic of this tracker, not a NOAA product. Weighted blend of
  amplitude (ONI/RONI vs the +2.5 °C historic bar), ocean&ndash;atmosphere coupling,
  basin-wide spatial scale, and rate of change.</p>
</div>"""


def _css() -> str:
    def block(theme: dict[str, str]) -> str:
        return "\n".join(f"    --{k}: {v};" for k, v in theme.items())

    return f"""
:root {{
  color-scheme: light;
{block(LIGHT)}
  --font: system-ui, -apple-system, "Segoe UI", sans-serif;
}}
@media (prefers-color-scheme: dark) {{
  :root:not([data-theme="light"]) {{
    color-scheme: dark;
{block(DARK)}
  }}
}}
:root[data-theme="dark"] {{
  color-scheme: dark;
{block(DARK)}
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; background: var(--plane); color: var(--ink);
  font-family: var(--font); line-height: 1.55;
  -webkit-font-smoothing: antialiased;
}}
.wrap {{ max-width: 1080px; margin: 0 auto; padding: 32px 16px 72px; }}
header.top {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: baseline;
  justify-content: space-between; margin-bottom: 8px; }}
h1 {{ font-size: 1.35rem; margin: 0; letter-spacing: -0.01em; }}
.sub {{ color: var(--ink2); font-size: 0.85rem; margin: 0; }}
.hero {{
  background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 24px; margin: 18px 0 20px;
  display: grid; grid-template-columns: minmax(230px, 1fr) 1.25fr; gap: 28px;
}}
.hero-fig {{ font-size: 3.4rem; font-weight: 650; line-height: 1; letter-spacing: -0.02em; }}
.hero-unit {{ font-size: 1.15rem; color: var(--ink2); font-weight: 500; }}
.hero-label {{ color: var(--ink2); font-size: 0.82rem; text-transform: uppercase;
  letter-spacing: 0.07em; margin-bottom: 8px; }}
.hero-tier {{ margin-top: 10px; font-size: 1.05rem; font-weight: 600; }}
.hero-note {{ color: var(--ink2); font-size: 0.85rem; margin-top: 6px; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 14px; margin-bottom: 22px; }}
.tile {{ background: var(--surface); border: 1px solid var(--border);
  border-radius: 12px; padding: 14px 16px; }}
.tile .t-label {{ color: var(--ink2); font-size: 0.76rem; }}
.tile .t-value {{ font-size: 1.5rem; font-weight: 620; letter-spacing: -0.01em; margin-top: 2px; }}
.tile .t-note {{ color: var(--muted); font-size: 0.75rem; margin-top: 2px; }}
.card {{ background: var(--surface); border: 1px solid var(--border); border-radius: 14px;
  padding: 20px 22px 16px; margin-bottom: 20px; }}
.card h2 {{ font-size: 1rem; margin: 0 0 2px; }}
.card .caption {{ color: var(--ink2); font-size: 0.83rem; margin: 0 0 14px; }}
svg {{ width: 100%; height: auto; display: block; overflow: visible; }}
.tick {{ fill: var(--muted); font-size: 11px; font-family: var(--font);
  font-variant-numeric: tabular-nums; }}
.rowlabel {{ fill: var(--ink2); font-size: 12px; font-family: var(--font); }}
.barvalue, .endlabel {{ fill: var(--ink); font-size: 12px; font-weight: 600;
  font-family: var(--font); }}
.band-note, .axistitle {{ fill: var(--muted); font-size: 11px; font-family: var(--font); }}
.hit {{ cursor: crosshair; outline: none; }}
.hit:focus-visible {{ stroke: var(--ink); stroke-width: 2; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 16px; margin: 12px 0 2px;
  font-size: 0.82rem; color: var(--ink2); }}
.key {{ display: inline-flex; align-items: center; gap: 7px; }}
.swatch {{ width: 12px; height: 12px; border-radius: 3px; display: inline-block; }}
.meter {{ margin-top: 4px; }}
.meter-head {{ display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 8px; }}
.meter-label {{ color: var(--ink2); font-size: 0.8rem; text-transform: uppercase;
  letter-spacing: 0.06em; }}
.meter-band {{ display: inline-flex; align-items: center; gap: 6px; font-weight: 650;
  font-size: 0.92rem; }}
.statusicon {{ width: 15px; height: 15px; }}
[data-status="critical"] .meter-band, [data-status="critical"] .statusicon {{ color: var(--critical); }}
[data-status="serious"] .meter-band, [data-status="serious"] .statusicon {{ color: var(--serious); }}
[data-status="warning"] .meter-band, [data-status="warning"] .statusicon {{ color: var(--warning); }}
[data-status="good"] .meter-band, [data-status="good"] .statusicon {{ color: var(--good); }}
.meter-track {{ height: 14px; border-radius: 7px; background: var(--track); overflow: hidden; }}
.meter-fill {{ height: 100%; border-radius: 7px; background: var(--warning); }}
[data-status="critical"] .meter-fill {{ background: var(--critical); }}
[data-status="serious"] .meter-fill {{ background: var(--serious); }}
[data-status="good"] .meter-fill {{ background: var(--good); }}
.meter-scale {{ display: flex; justify-content: space-between; color: var(--muted);
  font-size: 0.72rem; margin-top: 4px; font-variant-numeric: tabular-nums; }}
.comps {{ margin-top: 16px; display: grid; gap: 9px; }}
.comp {{ display: grid; grid-template-columns: 150px 1fr 34px; align-items: center; gap: 12px;
  font-size: 0.82rem; }}
.comp-name {{ color: var(--ink2); }}
.comp-name em {{ color: var(--muted); font-style: normal; margin-left: 5px; font-size: 0.72rem; }}
.comp-track {{ height: 7px; border-radius: 4px; background: var(--track); overflow: hidden; }}
.comp-fill {{ display: block; height: 100%; background: var(--s1); border-radius: 4px; }}
.comp-val {{ text-align: right; font-variant-numeric: tabular-nums; color: var(--ink2); }}
.note {{ color: var(--muted); font-size: 0.78rem; margin: 14px 0 0; }}
.tableview {{ margin-top: 14px; border-top: 1px solid var(--border); padding-top: 10px; }}
.tableview summary {{ cursor: pointer; color: var(--ink2); font-size: 0.8rem; }}
.tablewrap {{ overflow-x: auto; margin-top: 10px; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.82rem;
  font-variant-numeric: tabular-nums; }}
th, td {{ text-align: right; padding: 6px 10px; border-bottom: 1px solid var(--border);
  white-space: nowrap; }}
th:first-child, td:first-child {{ text-align: left; }}
th {{ color: var(--ink2); font-weight: 600; }}
.prose p {{ font-size: 0.88rem; color: var(--ink2); margin: 0 0 10px; }}
.sources {{ list-style: none; padding: 0; margin: 0; font-size: 0.8rem; }}
.sources li {{ display: flex; gap: 10px; padding: 7px 0; border-bottom: 1px solid var(--border);
  color: var(--ink2); flex-wrap: wrap; }}
.sources a {{ color: var(--s1); text-decoration: none; word-break: break-all; }}
.sources a:hover {{ text-decoration: underline; }}
.pill {{ font-size: 0.68rem; padding: 1px 8px; border-radius: 999px; border: 1px solid var(--border);
  color: var(--ink2); white-space: nowrap; }}
.pill.live {{ color: var(--good); border-color: color-mix(in srgb, var(--good) 45%, transparent); }}
.pill.cache {{ color: var(--warning); border-color: color-mix(in srgb, var(--warning) 45%, transparent); }}
.pill.fail {{ color: var(--critical); border-color: color-mix(in srgb, var(--critical) 45%, transparent); }}
#tip {{ position: fixed; pointer-events: none; opacity: 0; transition: opacity .1s;
  background: var(--surface); border: 1px solid var(--border); border-radius: 8px;
  padding: 7px 11px; font-size: 0.78rem; box-shadow: 0 6px 20px rgba(0,0,0,.18);
  z-index: 40; max-width: 260px; }}
#tip b {{ display: block; font-size: 0.8rem; margin-bottom: 1px; }}
#tip span {{ color: var(--ink2); }}
.themebtn {{ background: var(--surface); color: var(--ink2); border: 1px solid var(--border);
  border-radius: 8px; padding: 5px 11px; font-size: 0.78rem; cursor: pointer;
  font-family: var(--font); }}
footer {{ color: var(--muted); font-size: 0.76rem; margin-top: 26px; }}
/* --- panels added by the advanced system ---------------------------------- */
.tiny {{ fill: var(--muted); font-size: 10px; font-family: var(--font); }}
.pointlabel {{ fill: var(--ink); font-size: 11.5px; font-weight: 600;
  font-family: var(--font); }}
.axislabel {{ fill: var(--ink2); font-size: 11.5px; font-family: var(--font); }}
.quad {{ fill: var(--muted); font-size: 11px; font-family: var(--font);
  letter-spacing: 0.02em; }}
.panellabel {{ fill: var(--ink2); font-size: 11.5px; font-weight: 600;
  font-family: var(--font); }}

.twoup {{ display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }}

/* Chips carry a word, never a bare colour. */
.chip {{ display: inline-flex; align-items: center; gap: 5px; font-size: 0.72rem;
  font-weight: 600; padding: 3px 10px; border-radius: 999px;
  border: 1px solid var(--border); color: var(--ink2); white-space: nowrap; }}
.chip-now {{ color: var(--s2);
  border-color: color-mix(in srgb, var(--s2) 45%, transparent); }}
.chip-new {{ color: var(--critical); margin-left: 8px;
  border-color: color-mix(in srgb, var(--critical) 50%, transparent); }}
.chip-quiet {{ color: var(--muted); }}
.chip-critical {{ color: var(--critical);
  border-color: color-mix(in srgb, var(--critical) 45%, transparent); }}
.chip-serious {{ color: var(--serious);
  border-color: color-mix(in srgb, var(--serious) 45%, transparent); }}
.chip-warning {{ color: var(--warning);
  border-color: color-mix(in srgb, var(--warning) 50%, transparent); }}
.chip-good {{ color: var(--good);
  border-color: color-mix(in srgb, var(--good) 45%, transparent); }}

.phasestate, .walkerfoot {{ display: flex; flex-wrap: wrap; align-items: center;
  gap: 10px; margin-top: 12px; }}
.phasenote {{ color: var(--ink2); font-size: 0.8rem; flex: 1 1 260px; }}

/* Banner: the one thing visible without scrolling. */
.banner {{ display: flex; align-items: center; gap: 12px; padding: 11px 16px;
  border-radius: 12px; margin-bottom: 16px; font-size: 0.88rem;
  border: 1px solid var(--border); background: var(--surface); }}
.banner-level {{ font-size: 0.68rem; font-weight: 700; letter-spacing: 0.08em;
  padding: 3px 9px; border-radius: 999px; color: var(--surface); }}
.banner[data-status="critical"] {{
  border-color: color-mix(in srgb, var(--critical) 50%, transparent); }}
.banner[data-status="critical"] .banner-level {{ background: var(--critical); }}
.banner[data-status="serious"] {{
  border-color: color-mix(in srgb, var(--serious) 50%, transparent); }}
.banner[data-status="serious"] .banner-level {{ background: var(--serious); }}
.banner[data-status="warning"] {{
  border-color: color-mix(in srgb, var(--warning) 55%, transparent); }}
.banner[data-status="warning"] .banner-level {{ background: var(--warning);
  color: #1a1a19; }}

.alerts {{ list-style: none; padding: 0; margin: 0; }}
.alert {{ display: grid; grid-template-columns: 104px 1fr; gap: 14px;
  padding: 13px 0; border-top: 1px solid var(--border); align-items: start; }}
.alert:first-child {{ border-top: none; }}
.alert-level {{ display: inline-flex; align-items: center; gap: 6px;
  font-size: 0.68rem; font-weight: 700; letter-spacing: 0.06em; }}
.alert[data-status="critical"] .alert-level {{ color: var(--critical); }}
.alert[data-status="serious"] .alert-level {{ color: var(--serious); }}
.alert[data-status="warning"] .alert-level {{ color: var(--warning); }}
.alert[data-status="good"] .alert-level {{ color: var(--muted); }}
.alert-title {{ font-weight: 600; font-size: 0.9rem; }}
.alert-body p {{ margin: 4px 0 0; color: var(--ink2); font-size: 0.82rem; }}
.alert-since {{ display: block; margin-top: 5px; color: var(--muted);
  font-size: 0.72rem; }}

.probs {{ margin: 16px 0 4px; display: grid; gap: 7px; }}
.prob {{ display: grid; grid-template-columns: 160px 1fr 48px; gap: 10px;
  align-items: center; font-size: 0.8rem; color: var(--ink2); }}
.prob-track {{ height: 9px; border-radius: 999px; background: var(--track);
  overflow: hidden; }}
.prob-fill {{ display: block; height: 100%; border-radius: 999px;
  background: var(--s2); }}
.prob-val {{ text-align: right; font-weight: 600; color: var(--ink);
  font-variant-numeric: tabular-nums; }}

.warnlist {{ margin: 12px 0 0; padding-left: 20px; color: var(--ink2);
  font-size: 0.82rem; }}
.warnlist li {{ margin-bottom: 5px; }}

.disclaimer {{ border-left: 3px solid var(--warning); padding: 2px 0 2px 13px;
  margin-bottom: 14px; }}
.disclaimer p {{ margin: 0 0 6px; color: var(--ink2); font-size: 0.82rem; }}
.impact-group {{ margin-top: 20px; }}
.impact-group h3, .impact-watch h3 {{ font-size: 0.76rem; font-weight: 700;
  letter-spacing: 0.09em; text-transform: uppercase; color: var(--muted);
  margin: 0 0 10px; }}
.impacts {{ list-style: none; padding: 0; margin: 0; display: grid; gap: 10px; }}
.impact {{ border: 1px solid var(--border); border-radius: 11px; padding: 12px 14px; }}
.impact-head {{ display: flex; flex-wrap: wrap; align-items: center; gap: 9px;
  margin-bottom: 5px; }}
.impact-window {{ color: var(--muted); font-size: 0.74rem; }}
.impact-effect {{ font-size: 0.86rem; color: var(--ink); margin-bottom: 5px; }}
.impact p {{ margin: 0 0 5px; color: var(--ink2); font-size: 0.81rem; }}
.impact-exposure span {{ color: var(--muted); font-weight: 600;
  text-transform: uppercase; font-size: 0.68rem; letter-spacing: 0.06em;
  margin-right: 5px; }}
.impact-flavour {{ font-style: italic; }}
.impact-watch {{ margin-top: 20px; }}
.impact-watch ul {{ margin: 0; padding-left: 20px; color: var(--ink2);
  font-size: 0.81rem; }}

/* --- spatial panels -------------------------------------------------------- */
.chart.wide {{ max-width: none; }}
.boxlabel {{ fill: var(--ink); font-size: 10.5px; font-weight: 700;
  font-family: var(--font); paint-order: stroke; stroke: var(--surface);
  stroke-width: 3px; stroke-linejoin: round; }}
.subcaption {{ margin: 6px 0 0; color: var(--muted); font-size: 0.74rem; }}
.hint {{ color: var(--muted); font-style: italic; }}
.threeup {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 16px; }}
.swatch-line {{ height: 3px; border-radius: 2px; background: var(--ink); }}

/* Colour bars. Every field that uses a ramp carries one of these, which is the
   relief the validator requires for a neutral midpoint that recedes. */
.ramp {{ margin: 2px 0 10px; }}
.ramplabel {{ font-size: 0.72rem; font-weight: 600; color: var(--ink2);
  letter-spacing: 0.02em; margin-bottom: 4px; }}
.rampunits {{ color: var(--muted); font-weight: 400; }}
.rampstrip {{ display: flex; height: 10px; border-radius: 3px; overflow: hidden;
  border: 1px solid var(--border); }}
.rampcell {{ flex: 1 1 0; }}
.rampticks {{ display: flex; justify-content: space-between; margin-top: 3px; }}
.ramptick {{ font-size: 0.66rem; color: var(--muted);
  font-variant-numeric: tabular-nums; }}

/* Rotatable scenes. */
/* Scene labels are drawn after the geometry, and haloed, so an axis tick that
   lands on top of an opaque quad is still readable. */
.scenetick {{ paint-order: stroke; stroke: var(--surface); stroke-width: 3.5px;
  stroke-linejoin: round; }}
.scene {{ cursor: grab; touch-action: pan-y; }}
.scene.grabbing {{ cursor: grabbing; }}
.scene-svg {{ width: 100%; height: auto; display: block; user-select: none; }}
.viewbtns {{ display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }}
.viewbtns button {{ font: inherit; font-size: 0.72rem; font-weight: 600;
  padding: 4px 11px; border-radius: 999px; cursor: pointer;
  border: 1px solid var(--border); background: var(--plane); color: var(--ink2); }}
.viewbtns button:hover {{ color: var(--ink); border-color: var(--axis); }}
.viewbtns button[aria-pressed="true"] {{ color: var(--s1);
  border-color: color-mix(in srgb, var(--s1) 50%, transparent); }}

@media (max-width: 1000px) {{
  .threeup {{ grid-template-columns: 1fr; }}
}}
/* A scene scales as one piece, so on a narrow screen its 11px ticks land at
   about five real pixels. Text in the viewBox has to grow by the same factor
   the box shrinks by. */
@media (max-width: 720px) {{
  .scene-svg .scenetick, .scene-svg .pointlabel {{ font-size: 20px;
    stroke-width: 5px; }}
}}

@media (max-width: 860px) {{
  .twoup {{ grid-template-columns: 1fr; }}
  .alert {{ grid-template-columns: 1fr; gap: 5px; }}
  .prob {{ grid-template-columns: 120px 1fr 42px; }}
}}

@media (max-width: 720px) {{
  .hero {{ grid-template-columns: 1fr; gap: 18px; }}
  .comp {{ grid-template-columns: 110px 1fr 30px; }}
}}
"""


def _js() -> str:
    return """
(function () {
  var tip = document.getElementById('tip');
  function show(el, x, y) {
    var extra = el.getAttribute('data-extra');
    tip.innerHTML = '<b>' + el.getAttribute('data-label') + '</b><span>' +
      el.getAttribute('data-value') + (extra ? '<br>' + extra : '') + '</span>';
    tip.style.opacity = '1';
    var box = tip.getBoundingClientRect();
    var left = Math.min(Math.max(8, x + 14), window.innerWidth - box.width - 8);
    var top = Math.max(8, y - box.height - 12);
    tip.style.left = left + 'px';
    tip.style.top = top + 'px';
  }
  function hide() { tip.style.opacity = '0'; }
  document.addEventListener('mouseover', function (e) {
    var el = e.target.closest('.hit');
    if (el) { show(el, e.clientX, e.clientY); }
  });
  document.addEventListener('mousemove', function (e) {
    var el = e.target.closest('.hit');
    if (el) { show(el, e.clientX, e.clientY); } else { hide(); }
  });
  document.addEventListener('mouseout', function (e) {
    if (e.target.closest('.hit')) { hide(); }
  });
  document.addEventListener('focusin', function (e) {
    var el = e.target.closest('.hit');
    if (el) { var r = el.getBoundingClientRect(); show(el, r.left + r.width / 2, r.top); }
  });
  document.addEventListener('focusout', hide);

__SCENES__

__GLOBE__

  var btn = document.getElementById('theme');
  if (btn) {
    btn.addEventListener('click', function () {
      var root = document.documentElement;
      var dark = root.getAttribute('data-theme') === 'dark' ||
        (!root.getAttribute('data-theme') &&
          window.matchMedia('(prefers-color-scheme: dark)').matches);
      root.setAttribute('data-theme', dark ? 'light' : 'dark');
    });
  }
})();
""".replace("__SCENES__", space3d.SCENE_JS).replace("__GLOBE__", globe.js())


def render(state) -> str:
    """The whole system state as one self-contained HTML file."""
    a = state.assessment
    oni = state.series.get("oni") or []
    roni = state.series.get("roni") or []
    weeks = state.series.get("weeks") or []
    discussion = state.discussion or {}
    fetches = state.fetched
    now = datetime.now(timezone.utc).strftime("%d %b %Y %H:%M UTC")
    roni_map = {(s.season, s.year): s.value for s in roni}

    # --- hero + tiles --------------------------------------------------------
    hero = f"""
<section class="hero">
  <div>
    <div class="hero-label">Oceanic Nino Index &mdash; {esc(a.oni_latest.label)}</div>
    <div class="hero-fig">{a.oni_latest.value:+.2f}<span class="hero-unit"> °C</span></div>
    <div class="hero-tier">{esc(a.oni_tier)}</div>
    <div class="hero-note">#{a.ranking.rank_season} of {a.ranking.total_season} among all
      {esc(a.ranking.season)} seasons since 1950 &middot; #{a.ranking.rank_all} of
      {a.ranking.total_all} overall</div>
  </div>
  {power_meter(a)}
</section>"""

    tiles: list[str] = []
    if a.roni_latest:
        tiles.append(
            f'<div class="tile"><div class="t-label">RONI ({esc(a.roni_latest.label)})</div>'
            f'<div class="t-value">{a.roni_latest.value:+.2f}</div>'
            f'<div class="t-note">trend-adjusted &middot; {esc(a.roni_tier or "")}</div></div>'
        )
    if a.latest_week:
        tiles.append(
            f'<div class="tile"><div class="t-label">Nino-3.4 weekly</div>'
            f'<div class="t-value">{a.latest_week.nino34_anom:+.2f}</div>'
            f'<div class="t-note">week ending {esc(a.latest_week.label)}</div></div>'
        )
        tiles.append(
            f'<div class="tile"><div class="t-label">Nino-1+2 weekly</div>'
            f'<div class="t-value">{a.latest_week.nino12_anom:+.2f}</div>'
            f'<div class="t-note">eastern Pacific / coastal</div></div>'
        )
    if a.coupling.soi is not None:
        tiles.append(
            f'<div class="tile"><div class="t-label">SOI (3-month mean)</div>'
            f'<div class="t-value">{a.coupling.soi:+.2f}</div>'
            f'<div class="t-note">{esc(a.coupling.soi_label)}</div></div>'
        )
    if a.coupling.mei is not None:
        tiles.append(
            f'<div class="tile"><div class="t-label">MEI.v2</div>'
            f'<div class="t-value">{a.coupling.mei:+.2f}</div>'
            f'<div class="t-note">{esc(a.coupling.mei_label)}</div></div>'
        )

    if state.subsurface:
        sub = state.subsurface
        tiles.append(
            f'<div class="tile"><div class="t-label">Warm water volume</div>'
            f'<div class="t-value">{sub.anomaly:+.2f}</div>'
            f'<div class="t-note">10<sup>14</sup> m&sup3; &middot; '
            f'rank {sub.rank_alltime} of {sub.total_alltime}</div></div>'
        )
    if state.atmosphere and state.atmosphere.indicators:
        at = state.atmosphere
        tiles.append(
            f'<div class="tile"><div class="t-label">Walker composite</div>'
            f'<div class="t-value">{at.walker_index:+.2f}</div>'
            f'<div class="t-note">&sigma; &middot; '
            f'{"coupled" if at.coupled else "not yet coupled"}</div></div>'
        )
    peak = state.forecast.peak if state.forecast else None
    if peak:
        tiles.append(
            f'<div class="tile"><div class="t-label">Projected peak</div>'
            f'<div class="t-value">{peak.mean:+.2f}</div>'
            f'<div class="t-note">{esc(peak.label)} &middot; '
            f'{peak.low:+.2f} to {peak.high:+.2f}</div></div>'
        )

    # --- cards ---------------------------------------------------------------
    cards: list[str] = []

    # Alerts lead, because the page has to work for someone who reads only the
    # first screen before deciding whether to act.
    cards.append(panels.alert_feed(state))

    if discussion.get("synopsis"):
        cards.append(
            f"""<section class="card">
  <h2>NOAA CPC official synopsis</h2>
  <p class="caption">Issued {esc(discussion.get('issued') or 'n/a')}
    &middot; next update {esc(discussion.get('next_update') or 'n/a')}</p>
  <div class="prose"><p><strong>{esc(discussion['synopsis'])}</strong></p>
  {''.join(f'<p>{esc(p)}</p>' for p in discussion.get('body', '').split(chr(10) + chr(10)) if p)}</div>
</section>"""
        )

    # Where the event physically is, before any index of it. An index is a number
    # summarising a map; a reader who has seen the map reads the number better.
    sp = state.spatial
    # The globe first. Every other spatial panel is a slice or a projection of
    # the same ocean, and a reader who has turned the planet around once knows
    # what the slices are slices of.
    cards.append(globe.card(state))
    if sp.sst_map is not None:
        cards.append(fields.sst_map(sp.sst_map, sp.box_means, sp.warm_pool))
    if sp.mesh is not None:
        cards.append(space3d.thermocline(sp.mesh))
    cards.append(fields.section_card(sp))
    cards.append(fields.hov_card(sp))
    cards.append(fields.ssh_card(sp))
    if sp.sst_global is not None:
        cards.append(fields.global_map(sp.sst_global))
    cards.append(space3d.phase_spiral(state))

    recent = oni[-66:]
    cards.append(
        f"""<section class="card">
  <h2>Intensity &mdash; ONI and RONI</h2>
  <p class="caption">{esc(a.episode_status)}</p>
  {chart_oni(oni, roni)}
  {_legend([("ONI (Nino-3.4 anomaly)", "var(--s1)"), ("RONI (trend-adjusted)", "var(--s2)")])}
  {table("ONI and RONI by season (most recent 24)",
         ["Season", "ONI °C", "RONI °C", "Classification"],
         [[s.label, f"{s.value:+.2f}",
           f"{roni_map[(s.season, s.year)]:+.2f}" if (s.season, s.year) in roni_map else "n/a",
           intensity_tier(s.value)]
          for s in reversed(recent[-24:])])}
</section>"""
    )

    if a.scale and a.scale.regions and a.latest_week:
        cards.append(
            f"""<section class="card">
  <h2>Scale &mdash; spatial extent across the Nino regions</h2>
  <p class="caption">Week ending {esc(a.latest_week.label)} &middot;
    {a.scale.active_regions} of 4 regions at or above +0.5 °C &middot; {esc(a.scale.flavour)}
    (Nino-1+2 minus Nino-4 = {a.scale.flavour_index:+.2f} °C)</p>
  {chart_regions(a)}
  {_legend([("warm anomaly", "var(--warm)"), ("cool anomaly", "var(--cool)")])}
  {table("Nino-region weekly values",
         ["Region", "Anomaly °C", "SST °C", "At threshold"],
         [[r.label, f"{r.anomaly:+.2f}", f"{r.sst:.1f}", "yes" if r.active else "no"]
          for r in a.scale.regions])}
</section>"""
        )

    if len(weeks) > 2:
        shown = weeks[-104:]
        cards.append(
            f"""<section class="card">
  <h2>Weekly Nino-3.4 trajectory</h2>
  <p class="caption">Last {len(shown)} weeks &middot; the highest-frequency official view of the
    index region</p>
  {chart_weekly(weeks)}
  {table("Weekly Nino-3.4 (most recent 16 weeks)",
         ["Week ending", "Nino-3.4 anomaly °C", "SST °C", "Nino-1+2 anomaly °C"],
         [[w.label, f"{w.nino34_anom:+.2f}", f"{w.nino34_sst:.1f}", f"{w.nino12_anom:+.2f}"]
          for w in reversed(shown[-16:])])}
</section>"""
        )

    if a.analogs:
        analog_rows = [
            [an.episode.name, f"{an.rmse:.3f}", f"{an.peak_value:+.2f}", an.peak_label,
             str(an.seasons_to_peak), an.tier]
            for an in a.analogs
        ]
        legend_items = [(a.episode.name + " (now)", "var(--s1)")] if a.episode else []
        for slot, analog in zip(("var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)"), a.analogs):
            legend_items.append((analog.episode.name, slot))
        cards.append(
            f"""<section class="card">
  <h2>Closest historical analogs</h2>
  <p class="caption">Past events matched on their first {a.seasons_at_threshold} season(s) above
    +0.5 °C, aligned on onset. Analogs describe how comparable events evolved &mdash; they are
    not a forecast.</p>
  {chart_analogs(a)}
  {_legend(legend_items)}
  {table("Analog events",
         ["Event", "Fit (RMSE °C)", "Peak ONI", "Peak season", "Seasons to peak", "Classification"],
         analog_rows)}
</section>"""
        )

    cards.append(panels.chart_phase(state))
    cards.append(panels.chart_heat(state))
    cards.append(panels.chart_walker(state))
    cards.append(panels.chart_forecast(state))
    cards.append(panels.chart_skill(state))
    cards.append(panels.impact_panel(state))

    momentum_rows = []
    if a.momentum.season_delta is not None:
        momentum_rows.append(["ONI change vs previous season", f"{a.momentum.season_delta:+.2f} °C"])
    if a.momentum.weekly_delta is not None:
        momentum_rows.append(
            [f"Nino-3.4 change over {a.momentum.weeks_span} weeks", f"{a.momentum.weekly_delta:+.2f} °C"]
        )
    momentum_rows.append(["Assessment", a.momentum.direction])
    momentum_rows.append(["Coupling verdict", "coupled" if a.coupling.coupled else "not yet clearly coupled"])
    cards.append(
        f"""<section class="card">
  <h2>Momentum and coupling</h2>
  <p class="caption">Coupling is what turns a warm ocean into global teleconnections; without a
    Walker-circulation response the anomaly stays local.</p>
  {table("Momentum and coupling diagnostics", ["Diagnostic", "Value"], momentum_rows)}
</section>"""
    )

    source_items = []
    for fetched in fetches.values():
        if fetched.error:
            pill, status = "fail", "fetch failed"
        elif fetched.from_cache:
            pill, status = "cache", f"cached {fetched.fetched_at}"
        else:
            pill, status = "live", f"live {fetched.fetched_at}"
        source_items.append(
            f'<li><span class="pill {pill}">{esc(status)}</span>'
            f'<span>{esc(fetched.source.agency)} &mdash; {esc(fetched.source.name)}</span>'
            f'<a href="{esc(fetched.source.url)}">{esc(fetched.source.url)}</a></li>'
        )
    cards.append(
        f"""<section class="card">
  <h2>Data provenance</h2>
  <p class="caption">Every number on this page is pulled directly from these feeds at run time.</p>
  <ul class="sources">{''.join(source_items)}</ul>
</section>"""
    )

    # The banner is the one thing a reader sees without scrolling, so it carries
    # the worst open alert and says how many others sit behind it.
    worst = state.alert_set.worst if state.alert_set.alerts else ""
    banner = ""
    if worst in (alerts.CRITICAL, alerts.WARNING):
        same = state.alert_set.by_level(worst)
        others = len(same) - 1
        trailer = f" &middot; {others} more at this level" if others else ""
        banner = (
            f'<div class="banner" '
            f'data-status="{"critical" if worst == alerts.CRITICAL else "serious"}">'
            f'<span class="banner-level">{esc(worst.upper())}</span>'
            f'<span>{esc(same[0].title)}{trailer}</span></div>'
        )
    degraded = ""
    if state.warnings:
        degraded = (
            f'<div class="banner" data-status="warning"><span class="banner-level">DATA</span>'
            f'<span>Analysis degraded: {len(state.warnings)} feed or parse problem(s). '
            f'See data provenance below.</span></div>'
        )
    cpc_status = discussion.get("status") or ""
    status_line = f" &middot; CPC: {esc(cpc_status)}" if cpc_status else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E%3Ccircle cx='16' cy='16' r='15' fill='%23eb6834'/%3E%3Ccircle cx='16' cy='16' r='7' fill='%23fcd8c6'/%3E%3C/svg%3E">
<title>El Nino Tracker &mdash; {esc(a.oni_latest.label)}</title>
<style>{_css()}{fields.ramp_css()}{globe.css()}</style>
</head>
<body>
<svg width="0" height="0" aria-hidden="true" focusable="false" style="position:absolute"><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="transparent"/><line x1="0" y1="0" x2="0" y2="6" stroke="var(--surface)" stroke-width="2.4"/></pattern></defs></svg>
<div class="wrap">
  <header class="top">
    <div>
      <h1>El Nino / Southern Oscillation Tracker</h1>
      <p class="sub">Generated {esc(now)}{status_line}</p>
    </div>
    <button class="themebtn" id="theme" type="button">Toggle theme</button>
  </header>
  {banner}
  {degraded}
  {hero}
  <div class="tiles">{''.join(tiles)}</div>
  {''.join(card for card in cards if card)}
  <footer>
    Sources: NOAA Climate Prediction Center and NOAA Physical Sciences Laboratory.
    The composite power index is a derived diagnostic of this tracker, not an official product.
    For operational forecasts always consult the CPC ENSO Diagnostic Discussion directly.
  </footer>
</div>
<div id="tip" role="status" aria-live="polite"></div>
<script>{_js()}</script>
</body>
</html>"""


def payload(state) -> dict:
    """Machine-readable snapshot, so the tracker can feed other tools.

    Everything a downstream consumer could want without re-deriving it: the
    classification, the diagnostics behind it, the forecast with its verified
    error bars, the open alerts, and the health of every feed. Keys are stable,
    and a value that could not be computed is null rather than absent, so a
    consumer never has to distinguish "missing" from "not applicable".
    """
    a = state.assessment
    sub = state.subsurface
    atmosphere = state.atmosphere
    forecast = state.forecast
    skill = state.skill

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "run_at": state.run_at,
        "schema": 4,
        "headline": a.headline,
        "cpc_status": a.status or None,
        "degraded": state.degraded,
        "warnings": list(state.warnings),
        "oni": {"season": a.oni_latest.label, "value": a.oni_latest.value, "tier": a.oni_tier},
        "roni": (
            {"season": a.roni_latest.label, "value": a.roni_latest.value, "tier": a.roni_tier}
            if a.roni_latest else None
        ),
        "episode_status": a.episode_status,
        "seasons_at_threshold": a.seasons_at_threshold,
        "ranking": {
            "rank_all": a.ranking.rank_all, "total_all": a.ranking.total_all,
            "rank_in_season": a.ranking.rank_season, "total_in_season": a.ranking.total_season,
            "season": a.ranking.season,
        },
        "weekly": (
            {
                "week_ending": a.latest_week.week_ending.isoformat(),
                "nino12": a.latest_week.nino12_anom, "nino3": a.latest_week.nino3_anom,
                "nino34": a.latest_week.nino34_anom, "nino4": a.latest_week.nino4_anom,
            }
            if a.latest_week else None
        ),
        "scale": (
            {
                "flavour": a.scale.flavour, "flavour_index": a.scale.flavour_index,
                "active_regions": a.scale.active_regions, "basin_score": a.scale.basin_score,
                "regions": [
                    {"key": r.key, "label": r.label, "anomaly": r.anomaly, "sst": r.sst}
                    for r in a.scale.regions
                ],
            }
            if a.scale else None
        ),
        "power_index": {
            "value": a.power.value, "band": a.power.band,
            "components": a.power.components, "weights": a.power.weights,
        },
        "momentum": {
            "season_delta": a.momentum.season_delta, "weekly_delta": a.momentum.weekly_delta,
            "direction": a.momentum.direction, "score": a.momentum.score,
        },
        "subsurface": (
            {
                "month": sub.latest.label,
                "wwv_anomaly": sub.anomaly,
                "wwv_west_anomaly": sub.west.anomaly if sub.west else None,
                "wwv_east_anomaly": sub.east_anomaly,
                "rank_alltime": sub.rank_alltime, "total_alltime": sub.total_alltime,
                "rank_in_month": sub.rank_month, "total_in_month": sub.total_month,
                "percentile": sub.percentile,
                "tendency_per_month": sub.tendency, "tendency": sub.tendency_label,
                "phase": sub.phase_name, "phase_angle_deg": sub.phase_angle,
                "phase_confident": sub.phase_confident,
                "lead_months": sub.lead_months, "lead_correlation": sub.lead_correlation,
                "implied_nino34": sub.implied_nino34,
            }
            if sub else None
        ),
        "atmosphere": (
            {
                "walker_index": atmosphere.walker_index,
                "as_of": atmosphere.latest_label,
                "coupled": atmosphere.coupled,
                "agreement": atmosphere.agreement,
                "dissenters": [d.key for d in atmosphere.dissenters],
                "westerly_burst_months_12mo": atmosphere.burst_count_12mo,
                "indicators": [
                    {
                        "key": i.key, "name": i.name, "as_of": i.label,
                        "raw": i.raw, "standard_score": i.score,
                        "supports_el_nino": i.supports_el_nino, "stale": i.stale,
                    }
                    for i in atmosphere.indicators
                ],
                "mjo": (
                    {
                        "date": atmosphere.mjo.when.isoformat(),
                        "enhanced_longitude": atmosphere.mjo.enhanced_longitude,
                        "amplitude": atmosphere.mjo.amplitude,
                        "constructive": atmosphere.mjo.constructive,
                    }
                    if atmosphere.mjo else None
                ),
            }
            if atmosphere and atmosphere.indicators else None
        ),
        "forecast": (
            {
                "skill_source": forecast.skill_source,
                "peak": (
                    {
                        "season": forecast.peak.label, "lead": forecast.peak.lead,
                        "mean": forecast.peak.mean, "low": forecast.peak.low,
                        "high": forecast.peak.high,
                    }
                    if forecast.peak else None
                ),
                "peak_probability": {
                    f"{threshold:.1f}": value
                    for threshold, value in sorted(forecast.peak_probability.items())
                },
                "analog_weights": forecast.analog_weights,
                "projections": [
                    {
                        "lead": p.lead, "season": p.label, "mean": p.mean,
                        "low": p.low, "high": p.high, "sigma": p.sigma,
                        "methods": p.methods, "method_spread": p.spread,
                    }
                    for p in forecast.projections
                ],
                "notes": list(forecast.notes),
            }
            if forecast else None
        ),
        "skill": (
            {
                "sample_years": skill.sample_years,
                "useful_horizon_months": skill.horizon,
                "barrier_seasons": skill.barrier_seasons,
                "barrier_drop": skill.barrier_drop,
                "weights": skill.weights,
                "by_lead": [
                    {"lead": s.lead, "rmse": s.rmse, "correlation": s.acc,
                     "bias": s.bias, "n": s.count, "by_method": s.by_method}
                    for s in skill.leads
                ],
                "correlation_by_target_season": skill.by_target_season,
            }
            if skill else None
        ),
        "analogs": [
            {"event": an.episode.name, "rmse": round(an.rmse, 4), "peak": an.peak_value,
             "peak_season": an.peak_label, "seasons_to_peak": an.seasons_to_peak,
             "tier": an.tier}
            for an in a.analogs
        ],
        "alerts": [
            {"code": al.code, "level": al.level, "title": al.title, "detail": al.detail,
             "kind": al.kind, "value": al.value, "is_new": al.is_new,
             "first_seen": al.first_seen}
            for al in state.alert_set.alerts
        ],
        "alerts_cleared": list(state.alert_set.cleared),
        "impacts": [
            {"area": i.link.area, "region": i.link.region, "effect": i.link.effect,
             "window": i.link.window, "polarity": i.link.polarity,
             "likelihood": i.likelihood.strip(), "confidence": i.link.confidence,
             "oni_threshold": i.link.min_intensity, "flavour": i.link.flavour}
            for i in state.impacts.active
        ],
        # The same catalogue keyed by coordinate, so a consumer of this file can
        # answer "what does this event do at my location" without the globe.
        "footprints": [
            {"region": f.region, "scope": f.scope, "anchor": list(f.anchor),
             "boxes": [[b.lon0, b.lon1, b.lat0, b.lat1] for b in f.boxes]}
            for f in geo.FOOTPRINTS
        ],
        "spatial": {
            "fields": {
                name: {
                    "as_of": getattr(state.spatial, name).as_of,
                    "age_days": state.spatial.stale.get(name),
                    "rows": getattr(state.spatial, name).rows,
                    "cols": getattr(state.spatial, name).cols,
                    "coverage": round(getattr(state.spatial, name).coverage(), 4),
                }
                for name in ("sst_map", "sst_global", "sst_hov", "ssh_map", "ssh_hov",
                             "section", "section_anomaly", "iso_hov", "iso_hov_anomaly")
                if getattr(state.spatial, name) is not None
            },
            # The map-derived box means are computed from the gridded anomaly with
            # cosine weighting, so they will not match the CPC index to the decimal.
            # They are here to show what the map says, not to replace the index.
            "box_means_from_map": {
                key: round(value, 3) for key, value in state.spatial.box_means.items()
            },
            "warm_pool_east_edge": state.spatial.warm_pool,
            "equatorial_isotherm_20c": [
                {"longitude": pr.lon, "depth_m": pr.isotherm(20.0), "as_of": pr.as_of}
                for pr in state.spatial.profiles
            ],
            "thermocline_mesh": (
                {
                    "as_of": state.spatial.mesh.as_of,
                    "age_days": state.spatial.stale.get("mesh"),
                    "nodes": len(state.spatial.mesh.nodes),
                }
                if state.spatial.mesh else None
            ),
            "notes": list(state.spatial.notes),
        },
        "cpc_discussion": state.discussion,
        "feeds": {
            key: {
                "ok": item.ok, "from_cache": item.from_cache,
                "fetched_at": item.fetched_at, "error": item.error or None,
                "url": item.source.url,
            }
            for key, item in state.fetched.items()
        },
    }


def write_json(state, path) -> None:
    path.write_text(json.dumps(payload(state), indent=2), encoding="utf-8")
