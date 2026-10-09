"""The HTML dashboard: inline SVG, its script beside it (elnino/assets.py), no CDN,
no build step.

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

from . import (alerts, assets, atlas, atlasview, cyclones, fields, geo, globe, impacts, live,
               panels, sitenav, space3d, stormdesk, stormfury, storms, worldmap)
from .svg import (  # noqa: F401 - re-exported for the panel modules
    BAND_STATUS,
    DARK,
    LIGHT,
    Plot,
    _hit,
    _legend,
    esc,
    nice_ticks,
    prose,
    table,
    tick_text,
)


# --- chart 1: the official index and the legacy one -------------------------
def chart_oni(official: list[SeasonValue], legacy: list[SeasonValue],
              name: str = "RONI", legacy_name: str = "ONI", seasons: int = 66) -> str:
    """The official index (RONI since February 2026) with the legacy ONI beside it.

    The official index takes the first series colour here as it does on the
    forecast chart, so it is the same line wherever it appears.
    """
    recent = official[-seasons:]
    lookup = {(s.season, s.year): s.value for s in legacy}
    plot = Plot(760, 330, (24, 92, 44, 52))

    values = [s.value for s in recent] + [
        lookup[(s.season, s.year)] for s in recent if (s.season, s.year) in lookup
    ]
    low, high = min(values + [-0.6]), max(values + [0.6])
    pad = (high - low) * 0.14
    plot.domain(0, len(recent) - 1, low - pad, high + pad)
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
    for index, item in enumerate(recent):
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

    official_points = [(plot.sx(i), plot.sy(s.value)) for i, s in enumerate(recent)]
    legacy_points = [
        (plot.sx(i), plot.sy(lookup[(s.season, s.year)]))
        for i, s in enumerate(recent)
        if (s.season, s.year) in lookup
    ]

    if legacy_points:
        plot.add(
            f'<path d="{path_for(legacy_points)}" fill="none" stroke="var(--s2)" '
            f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />'
        )
    plot.add(
        f'<path d="{path_for(official_points)}" fill="none" stroke="var(--s1)" '
        f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" />'
    )

    # end markers with 2px surface ring, and selective direct labels
    for points, colour, label, value in (
        (legacy_points, "var(--s2)", legacy_name,
         lookup.get((recent[-1].season, recent[-1].year))),
        (official_points, "var(--s1)", name, recent[-1].value),
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

    for index, item in enumerate(recent):
        extra = ""
        key = (item.season, item.year)
        if key in lookup:
            extra = f"{legacy_name} {lookup[key]:+.2f} °C (legacy)"
        plot.add(_hit(plot.sx(index), plot.sy(item.value), item.label,
                      f"{name} {item.value:+.2f} °C · {intensity_tier(item.value)}",
                      extra))

    return plot.svg(
        f"{name} and {legacy_name} seasonal trace" if legacy else f"{name} seasonal trace",
        f"Three-month Nino-3.4 index: {name}, the official one, "
        + (f"with the legacy {legacy_name} beside it." if legacy else "on its own."),
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
            f'class="tick">{tick_text(tick)}</text>'
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
                     f"{assessment.index_name} {value:+.2f} °C",
                     f"season {index} after onset")
            )

    # Events that finish at a similar value put their end-labels on top of each other.
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
  amplitude ({esc(assessment.index_name)} against +2.5 °C, a level RONI has not reached
  since 1950), ocean&ndash;atmosphere coupling, basin-wide spatial scale, and rate of
  change.</p>
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
/* A map label over tracks: text ink, and a halo of the map's own ground so
   a line or a marker under it does not cut through the letters. */
.placename {{ fill: var(--ink); font-weight: 600; }}
.halo {{ paint-order: stroke; stroke: var(--plane); stroke-width: 3px;
  stroke-linejoin: round; }}
.band-note, .axistitle {{ fill: var(--muted); font-size: 11px; font-family: var(--font); }}
/* The field is one path per colour class rather than a rectangle per cell,
   so the crisp-edge hint lives on the group instead of on every element. */
.cellfill path {{ shape-rendering: crispEdges; }}
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
th.lbl, td.lbl {{ text-align: left; }}
th.txt, td.txt {{ white-space: normal; text-align: left; min-width: 16em; }}
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
/* --- a page following the site: the notice of a newer run (live.py) ------- */
.livenote {{ position: fixed; z-index: 1000; left: 16px; right: 16px;
  bottom: calc(16px + env(safe-area-inset-bottom, 0px));
  display: flex; justify-content: center; pointer-events: none; }}
.livenote p {{ pointer-events: auto; display: flex; flex-wrap: wrap; align-items: center;
  gap: 6px 12px; margin: 0; padding: 9px 14px; border-radius: 10px;
  background: var(--ink); color: var(--surface); font-family: var(--font);
  font-size: 0.82rem; line-height: 1.4; box-shadow: 0 6px 20px rgba(0,0,0,.18); }}
.livenote button {{ font: inherit; font-weight: 600; color: inherit; background: none;
  border: 1px solid currentColor; border-radius: 7px; padding: 3px 10px; cursor: pointer; }}
.livenote button + button {{ border-color: transparent; font-weight: 400; }}
.livenote button:focus-visible {{ outline: 2px solid currentColor; outline-offset: 2px; }}
@media print {{ .livenote {{ display: none; }} }}
/* --- the site's menu, the first thing on every page (sitenav.py) ---------- */
.sitebar {{ flex: none; display: flex; align-items: center; column-gap: 18px;
  padding: 0 16px; background: var(--surface); border-bottom: 1px solid var(--border);
  font-family: var(--font); overflow-x: auto; scrollbar-width: none; }}
.sitebar .brand {{ flex: none; display: flex; align-items: center; gap: 8px;
  min-height: 44px; color: var(--ink); font-size: 0.92rem; font-weight: 650;
  letter-spacing: -0.01em; text-decoration: none; white-space: nowrap; }}
/* Sized for itself: the shell sizes every svg to its box. A logo keeps its
   colours where colours are forced. */
.sitebar .sitemark {{ flex: none; width: 22px; height: 22px; forced-color-adjust: none; }}
.sitebar ul {{ display: flex; margin: 0; padding: 0; list-style: none; }}
.sitebar .tab {{ display: flex; align-items: center; min-height: 44px; padding: 0 12px;
  color: var(--ink2); font-size: 0.86rem; font-weight: 500; white-space: nowrap;
  text-decoration: none; box-shadow: inset 0 -2px 0 transparent;
  transition: color .15s, box-shadow .15s; }}
.sitebar .tab:hover {{ color: var(--ink); box-shadow: inset 0 -2px 0 var(--border); }}
.sitebar .tab[aria-current="page"] {{ color: var(--ink); font-weight: 600;
  box-shadow: inset 0 -2px 0 var(--s2); }}
.sitebar a:focus-visible {{ outline: 2px solid var(--ink); outline-offset: -2px;
  border-radius: 6px; }}
/* The dashboard is read a long way down: there the menu stays in reach,
   pinned over the page's column, its name where the column's words start.
   What a reader tabs to or opens is scrolled clear of it, 60 px down (its
   45 and room), and the follower reads the view from there (live.py). */
.dashpage .sitebar {{ position: sticky; top: 0; z-index: 30;
  padding-inline: max(16px, (100% - 1080px) / 2 + 16px); }}
:root:has(> body.dashpage) {{ scroll-padding-top: 60px; }}
/* A phone shows the mark for the site's name, and the pages close up; the
   smallest leave the way to the front page to the Dashboard. */
@media (max-width: 640px) {{
  .sitebar {{ column-gap: 6px; }}
  .sitebar .tab {{ padding: 0 6px; }}
  .sitebar .brand span {{ position: absolute; width: 1px; height: 1px; overflow: hidden;
    clip-path: inset(50%); white-space: nowrap; }}
}}
@media (max-width: 359px) {{
  .sitebar .brand {{ display: none; }}
  .sitebar .tab {{ padding: 0 4px; }}
}}
/* Forced colours drop the shadow that marks the reader's page: there it is
   underlined. */
@media (forced-colors: active) {{
  .sitebar .tab[aria-current="page"] {{ text-decoration: underline 2px;
    text-underline-offset: 6px; }}
}}
@media print {{ .sitebar {{ display: none; }} }}
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
/* A bar whose labels are placed at their values rather than spread out. */
.rampscale {{ display: block; position: relative; height: 1.2em; }}
.rampscale .ramptick {{ position: absolute; top: 0; white-space: nowrap; }}

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

  // The run's time ages while the page stays open, as the storm desk's do.
  function span(min) {
    if (min < 60) return min + ' min';
    var h = Math.floor(min / 60), m = min % 60;
    if (h < 48) return h + ' h' + (m ? ' ' + m + ' min' : '');
    return Math.round(h / 24) + ' days';
  }
  function ago(ms) {
    var m = Math.round((Date.now() - ms) / 60000);
    return m < 0 ? 'in ' + span(-m) : span(m) + ' ago';
  }
  function ages() {
    var list = document.querySelectorAll('time[data-age]');
    for (var i = 0; i < list.length; i++) {
      var ms = Date.parse(list[i].getAttribute('datetime'));
      if (!isNaN(ms)) list[i].textContent = list[i].getAttribute('data-age') + ' (' + ago(ms) + ')';
    }
  }
  ages();
  setInterval(ages, 60000);

  // A new run is loaded while the page is open, the reader's place kept
  // (elnino/live.py): held by the part of the page they were reading, found
  // again by its id, as what the run says above it takes more lines or fewer.
  elninoLive.follow({ boxes: ['page'] });
})();
""".replace("__SCENES__", space3d.SCENE_JS).replace("__GLOBE__", globe.js())


# --- the storm desk ------------------------------------------------------------
# storms.html and storms.json are written beside this page, so the paths are
# relative to it.
STORM_DESK = {"page": "storms.html", "data": "storms.json", "schema": stormdesk.SCHEMA}


def _counted(n: int, one: str, many: str) -> str:
    return f"{n} {one if n == 1 else many}"


def outlook_json(state) -> list:
    """NHC's and JTWC's formation areas, as storms.json carries them."""
    tier = getattr(state, "cyclones", None)
    return [stormdesk._area(area) for area in (getattr(tier, "outlook", None) or [])]


def storm_desk_card(state) -> str:
    """The way into storms.html, and what is on it at this run."""
    tier = getattr(state, "cyclones", None)
    live = tier.active if tier is not None and tier.available else ()
    areas = list(getattr(tier, "outlook", None) or [])
    invests = tuple(getattr(tier, "invests", None) or ())

    counts = [_counted(len(live), "live storm", "live storms") if live
              else "No live tropical cyclones at this run"]
    if areas:
        counts.append(_counted(len(areas), "formation area", "formation areas"))
    if invests:
        counts.append(_counted(len(invests), "invest", "invests"))

    named = []
    for storm in live:
        now = storm.latest
        label = now.label[:1].upper() + now.label[1:] if now else ""
        named.append(f"<li><strong>{esc(storm.title)}</strong> &middot; "
                     f"{esc(label) + ' &middot; ' if label else ''}"
                     f"advisories from {esc(stormdesk.centre_name(storm))}</li>")
    for area in areas:
        if area.chance_7day is not None:
            odds = ("" if area.chance_2day is None else f"{area.chance_2day}% in 2 days, "
                    ) + f"{area.chance_7day}% in 7 days"
        else:
            formation = getattr(area, "formation", None)
            odds = f"{area.potential or 'unrated'} potential" + (
                ", " + stormdesk._alert_words(formation.until if formation else "",
                                              getattr(state, "run_at", None))
                if area.alert else "")
        named.append(f"<li>Formation, {esc(area.centre)}: {esc(area.label)} "
                     f"&middot; {esc(odds)}</li>")
    for storm in invests:
        named.append(f"<li>{esc(storm.title)} &middot; an invest: "
                     "tracked, not yet a tropical cyclone</li>")
    listed = f'<ul class="reasons">{"".join(named)}</ul>' if named else ""

    return f"""<section class="card" id="storm-desk">
  <h2>Storm Desk</h2>
  <p class="caption">{" &middot; ".join(counts)}</p>
  <p class="prose"><a class="bigalink" href="{STORM_DESK['page']}">Open the Storm Desk &rarr;</a>
    Every live storm on the newest satellite frame, drawn at
    the time that frame was taken, with its forecast track, cone and wind
    field. Zoom to the eye, swipe between imagery layers, loop the last two
    hours, and move the forecast forward to see the places each wind
    threshold reaches. Each storm's Protect tab has its watches and warnings,
    wind speed probabilities, peak surge, and what to do for people and for
    animals.</p>
  <p class="prose">Every storm is also on the <a href="map.html">El Ni&ntilde;o
    map</a>, over street maps and satellite.</p>
  {listed}
</section>"""


def render(state) -> str:
    """The whole system state as one self-contained HTML file."""
    a = state.assessment
    oni = state.series.get("oni") or []
    roni = state.series.get("roni") or []
    official = a.index_series
    legacy = oni if a.index_name == "RONI" else []
    weeks = state.series.get("weeks") or []
    discussion = state.discussion or {}
    fetches = state.fetched
    # Dated by its run, as the storm desk is, not by when the page was drawn.
    run_time = (datetime.fromisoformat(state.run_at.replace("Z", "+00:00"))
                .astimezone(timezone.utc).strftime("%d %b %Y %H:%M UTC"))
    legacy_map = {(s.season, s.year): s.value for s in legacy}

    # --- hero + tiles --------------------------------------------------------
    index_title = ("Relative Oceanic Nino Index" if a.index_name == "RONI"
                   else "Oceanic Nino Index")
    index_role = ("CPC&rsquo;s official index since February 2026"
                  if a.index_name == "RONI"
                  else "standing in: RONI, the official index, did not arrive")
    rank = a.index_ranking
    rank_note = (
        f"#{rank.rank_season} of {rank.total_season} among all {esc(rank.season)} "
        f"seasons since 1950 &middot; #{rank.rank_all} of {rank.total_all} overall "
        f"&middot; " if rank else ""
    )
    hero = f"""
<section class="hero" id="hero">
  <div>
    <div class="hero-label">{index_title} &mdash; {esc(a.index_latest.label)}</div>
    <div class="hero-fig">{a.index_latest.value:+.2f}<span class="hero-unit"> °C</span></div>
    <div class="hero-tier">{esc(a.index_tier)}</div>
    <div class="hero-note">{rank_note}{index_role}</div>
  </div>
  {power_meter(a)}
</section>"""

    tiles: list[str] = []
    if a.index_name == "RONI" and a.oni_latest:
        tiles.append(
            f'<div class="tile"><div class="t-label">Legacy ONI ({esc(a.oni_latest.label)})</div>'
            f'<div class="t-value">{a.oni_latest.value:+.2f}</div>'
            f'<div class="t-note">pre-2026 index &middot; {esc(a.oni_tier)}</div></div>'
        )
    elif a.index_name == "RONI":
        tiles.append(
            '<div class="tile"><div class="t-label">Legacy ONI</div>'
            '<div class="t-value">&mdash;</div>'
            '<div class="t-note">did not arrive this run</div></div>'
        )
    if a.latest_week:
        regions = {r.key: r for r in a.scale.regions} if a.scale else {}
        relative = bool(a.scale and a.scale.basis == "relative")
        for key, label, note in (
            ("nino34", "Nino-3.4 weekly", f"week ending {esc(a.latest_week.label)}"),
            ("nino12", "Nino-1+2 weekly", "eastern Pacific / coastal"),
        ):
            region = regions.get(key)
            if region is None:
                continue
            if relative and region.traditional is not None:
                note += f" &middot; relative; traditional {region.traditional:+.2f}"
            tiles.append(
                f'<div class="tile"><div class="t-label">{label}</div>'
                f'<div class="t-value">{region.anomaly:+.2f}</div>'
                f'<div class="t-note">{note}</div></div>'
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
            f'<div class="tile"><div class="t-label">Projected {esc(a.index_name)} peak</div>'
            f'<div class="t-value">{peak.mean:+.2f}</div>'
            f'<div class="t-note">{esc(peak.label)} &middot; 80% range '
            f'{peak.low:+.2f} to {peak.high:+.2f}</div></div>'
        )

    # --- cards ---------------------------------------------------------------
    cards: list[str] = []

    # Alerts lead, because the page has to work for someone who reads only the
    # first screen before deciding whether to act.
    cards.append(panels.alert_feed(state))

    if discussion.get("synopsis"):
        cards.append(
            f"""<section class="card" id="synopsis">
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
    # Storms next, before any of the slower-moving geometry. A reader who
    # opens this page because something has formed should not have to scroll
    # past a thermocline section to find out where it is going.
    cards.append(storms.tracks_card(state))
    # The storm desk straight after the map it goes further than: every
    # basin, live imagery, and what each warning centre has issued.
    cards.append(storm_desk_card(state))
    cards.append(storms.season_card(state))
    # STORMFURY last of the three, because it only makes sense once the reader
    # has seen what tracking actually delivers.
    cards.append(storms.fury_card(state))
    # The map, then the atlas, after the storms and before the ocean geometry:
    # they are the panels that answer "and what about here", which is the
    # question a reader arrives with and the rest of the page never quite
    # addresses. The map goes down to the street; the atlas keeps the record.
    cards.append(worldmap.card(state))
    cards.append(atlasview.card(state))
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

    recent = official[-66:]
    name = a.index_name
    legend = [(f"{name} (official, tropical mean removed)", "var(--s1)")]
    columns = ["Season", f"{name} °C", f"Classification ({name}, as printed)"]
    if legacy:
        legend.append(("ONI (legacy)", "var(--s2)"))
        columns.insert(2, "ONI °C (legacy)")

    def season_row(s: SeasonValue) -> list[str]:
        row = [s.label, f"{s.value:+.2f}", intensity_tier(s.value)]
        if legacy:
            key = (s.season, s.year)
            row.insert(2, f"{legacy_map[key]:+.2f}" if key in legacy_map else "n/a")
        return row

    cards.append(
        f"""<section class="card" id="intensity">
  <h2>Intensity &mdash; {esc(name)}{" and the legacy ONI" if legacy else ""}</h2>
  <p class="caption">{prose(a.episode_status)} Tiers follow the one-decimal value CPC
    prints: +1.46 reads +1.5, Strong.</p>
  {chart_oni(official, legacy, name)}
  {_legend(legend)}
  {table(f"{name} by season (most recent 24)", columns,
         [season_row(s) for s in reversed(recent[-24:])])}
</section>"""
    )

    if a.scale and a.scale.regions and a.latest_week:
        cards.append(
            f"""<section class="card" id="regions">
  <h2>Scale &mdash; spatial extent across the Nino regions</h2>
  <p class="caption">Week ending {esc(a.latest_week.label)} &middot;
    {a.scale.active_regions} of 4 regions at or above +0.5 °C &middot; {esc(a.scale.flavour)}
    (Nino-1+2 minus Nino-4 = {a.scale.flavour_index:+.2f} °C) &middot;
    {"relative anomalies, tropical mean removed, as CPC now quotes them"
     if a.scale.basis == "relative" else "traditional anomalies"}</p>
  {chart_regions(a)}
  {_legend([("warm anomaly", "var(--warm)"), ("cool anomaly", "var(--cool)")])}
  {table("Nino-region weekly values",
         ["Region", f"{a.scale.basis.capitalize()} anomaly °C", "Traditional anomaly °C",
          "SST °C", "At threshold"],
         [[r.label, f"{r.anomaly:+.2f}",
           "n/a" if r.traditional is None else f"{r.traditional:+.2f}",
           f"{r.sst:.1f}", "yes" if r.active else "no"]
          for r in a.scale.regions])}
</section>"""
        )

    if len(weeks) > 2:
        shown = weeks[-104:]
        relative_by_week = {
            when: regions.get("nino34")
            for when, regions in (state.series.get("rel_weeks") or [])
        }

        def relative_cell(week) -> str:
            value = relative_by_week.get(week.week_ending)
            return "n/a" if value is None else f"{value:+.2f}"

        cards.append(
            f"""<section class="card" id="weekly">
  <h2>Weekly Nino-3.4 trajectory</h2>
  <p class="caption">Last {len(shown)} weeks of the traditional weekly anomaly, against a fixed
    1991&ndash;2020 base &middot; the relative value CPC now quotes, with the tropical mean
    taken out, is beside it in the table</p>
  {chart_weekly(weeks)}
  {table("Weekly Nino-3.4 (most recent 16 weeks)",
         ["Week ending", "Relative anomaly °C", "Traditional anomaly °C", "SST °C",
          "Nino-1+2 traditional °C"],
         [[w.label, relative_cell(w), f"{w.nino34_anom:+.2f}", f"{w.nino34_sst:.1f}",
           f"{w.nino12_anom:+.2f}"]
          for w in reversed(shown[-16:])])}
</section>"""
        )

    if a.analogs:
        analog_rows = [
            [an.episode.name, f"{an.rmse:.3f}", f"{an.peak_value:+.2f}", an.peak_label,
             f"{an.seasons_to_peak:+d}", an.tier]
            for an in a.analogs
        ]
        legend_items = [(a.episode.name + " (now)", "var(--s1)")] if a.episode else []
        for slot, analog in zip(("var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)"), a.analogs):
            legend_items.append((analog.episode.name, slot))
        cards.append(
            f"""<section class="card" id="analogs">
  <h2>Closest historical analogs</h2>
  <p class="caption">Past events matched on their first {a.seasons_at_threshold}
    season{'s' if a.seasons_at_threshold != 1 else ''} above
    +0.5 °C, aligned on onset. Analogs describe how comparable events evolved &mdash; they are
    not a forecast.</p>
  {chart_analogs(a)}
  {_legend(legend_items)}
  {table("Analog events",
         ["Event", "Fit (RMSE °C)", f"Peak {a.index_name}", "Peak season",
          "Seasons from this stage to its peak", "Classification"],
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
        momentum_rows.append([f"{a.index_name} change vs previous season",
                              f"{a.momentum.season_delta:+.2f} °C"])
    if a.momentum.weekly_delta is not None:
        momentum_rows.append(
            [f"Nino-3.4 change over {a.momentum.weeks_span} weeks", f"{a.momentum.weekly_delta:+.2f} °C"]
        )
    momentum_rows.append(["Assessment", a.momentum.direction])
    momentum_rows.append(["Coupling verdict", "coupled" if a.coupling.coupled else "not yet clearly coupled"])
    cards.append(
        f"""<section class="card" id="momentum">
  <h2>Momentum and coupling</h2>
  <p class="caption">Coupling is what turns a warm ocean into global teleconnections; without a
    Walker-circulation response the anomaly stays local.</p>
  {table("Momentum and coupling diagnostics", ["Diagnostic", "Value"],
         momentum_rows, expanded=True)}
</section>"""
    )

    source_items, pills = [], []
    for fetched in fetches.values():
        if fetched.error:
            pill, status = "fail", "fetch failed"
        elif fetched.from_cache:
            pill, status = "cache", f"cached {fetched.fetched_at}"
        else:
            pill, status = "live", f"live {fetched.fetched_at}"
        pills.append(pill)
        source_items.append(
            f'<li><span class="pill {pill}">{esc(status)}</span>'
            f'<span>{esc(fetched.source.agency)} &mdash; {esc(fetched.source.name)}</span>'
            f'<a href="{esc(fetched.source.url)}">{esc(fetched.source.url)}</a></li>'
        )
    # Say where the numbers came from this run, not where they would come
    # from on a good day: an offline run is every feed out of the cache.
    came = []
    if pills.count("live"):
        came.append(f"{pills.count('live')} fetched live this run")
    if pills.count("cache"):
        came.append(f"{pills.count('cache')} read from the local cache, each "
                    "stamped with when it was fetched")
    if pills.count("fail"):
        came.append(f"{pills.count('fail')} failed with no cache to fall back on")
    cards.append(
        f"""<section class="card" id="provenance">
  <h2>Data provenance</h2>
  <p class="caption">Every number on this page comes from these feeds:
    {"; ".join(came)}.</p>
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
            f'<span>{prose(same[0].title)}{trailer}</span></div>'
        )
    degraded = ""
    if state.warnings:
        degraded = (
            f'<div class="banner" data-status="warning"><span class="banner-level">DATA</span>'
            f'<span>Analysis degraded: {len(state.warnings)} feed or parse '
            f'problem{"s" if len(state.warnings) != 1 else ""}. '
            f'See data provenance below.</span></div>'
        )
    cpc_status = discussion.get("status") or ""
    status_line = f" &middot; CPC: {esc(cpc_status)}" if cpc_status else ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{live.head(state.run_at)}
{sitenav.ICON}
<title>El Nino Tracker &mdash; {esc(a.index_latest.label)}</title>
<style>{_css()}{fields.ramp_css()}{globe.css()}{storms.css()}{storms.fury_css()}</style>
{assets.tags((assets.follower(), assets.dashboard()))}
</head>
<body class="dashpage">
{sitenav.bar("dashboard.html")}
<svg width="0" height="0" aria-hidden="true" focusable="false" style="position:absolute"><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><rect width="6" height="6" fill="transparent"/><line x1="0" y1="0" x2="0" y2="6" stroke="var(--surface)" stroke-width="2.4"/></pattern></defs></svg>
<main class="wrap" id="page">
  <header class="top">
    <div>
      <h1>El Nino / Southern Oscillation Tracker</h1>
      <p class="sub">Generated {stormdesk._time(state.run_at, run_time)}{status_line}</p>
    </div>
    <button class="themebtn" id="theme" type="button">Toggle theme</button>
  </header>
  {banner}
  {degraded}
  {hero}
  <div class="tiles" id="indices">{''.join(tiles)}</div>
  {''.join(card for card in cards if card)}
  <footer>
    Sources: NOAA Climate Prediction Center and NOAA Physical Sciences Laboratory.
    The composite power index is a derived diagnostic of this tracker, not an official product.
    For operational forecasts always consult the CPC ENSO Diagnostic Discussion directly.
  </footer>
</main>
<div id="tip" role="status" aria-live="polite"></div>
</body>
</html>"""


def _fix_json(fix) -> dict | None:
    """One ATCF fix in the units a consumer expects rather than the ones it
    was stored in: decimal degrees, east and north positive."""
    if fix is None:
        return None
    return {
        "time_utc": (f"{fix.stamp[:4]}-{fix.stamp[4:6]}-{fix.stamp[6:8]}T"
                     f"{fix.stamp[8:10]}:00:00Z" if len(fix.stamp) == 10
                     else fix.stamp),
        "lead_hours": fix.tau,
        "lat": fix.lat,
        "lon": fix.lon,
        "wind_kt": fix.wind,
        "pressure_mb": fix.pressure,
        "stage": fix.stage,
        "category": fix.category,
        "intensity": fix.label,
    }


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
        "schema": 9,
        "headline": a.headline,
        "cpc_status": a.status or None,
        "degraded": state.degraded,
        "warnings": list(state.warnings),
        # The index everything is classified on: RONI, or ONI standing in.
        "index": {
            "name": a.index_name, "season": a.index_latest.label,
            "value": a.index_latest.value, "tier": a.index_tier,
        },
        "oni": ({"season": a.oni_latest.label, "value": a.oni_latest.value,
                 "tier": a.oni_tier} if a.oni_latest else None),
        "roni": (
            {"season": a.roni_latest.label, "value": a.roni_latest.value, "tier": a.roni_tier}
            if a.roni_latest else None
        ),
        "episode_status": a.episode_status,
        "seasons_at_threshold": a.seasons_at_threshold,
        "ranking": (
            {
                "index": a.index_name,
                "rank_all": a.index_ranking.rank_all, "total_all": a.index_ranking.total_all,
                "rank_in_season": a.index_ranking.rank_season,
                "total_in_season": a.index_ranking.total_season,
                "season": a.index_ranking.season,
            }
            if a.index_ranking else None
        ),
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
                "basis": a.scale.basis,
                "regions": [
                    {"key": r.key, "label": r.label, "anomaly": r.anomaly,
                     "traditional": r.traditional, "sst": r.sst}
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
                "weights": forecast.weights,
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
                "useful_horizon_is_lower_bound": skill.horizon_is_lower_bound,
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
             "escalated_from": al.escalated_from,
             "first_seen": al.first_seen}
            for al in state.alert_set.alerts
        ],
        "alerts_cleared": list(state.alert_set.cleared),
        "impacts": [
            {"area": i.link.area, "region": i.link.region, "effect": i.link.effect,
             "window": i.link.window, "polarity": i.link.polarity,
             "likelihood": i.likelihood.strip(), "confidence": i.link.confidence,
             "threshold": i.link.min_intensity, "flavour": i.link.flavour}
            for i in state.impacts.active
        ],
        "impacts_watch": [
            {"area": i.link.area, "region": i.link.region, "effect": i.link.effect,
             "likelihood": i.likelihood.strip(), "confidence": i.link.confidence,
             "threshold": i.link.min_intensity, "needs": i.needs,
             "flavour": i.link.flavour}
            for i in state.impacts.watch
        ],
        # The same catalogue keyed by coordinate, so a consumer of this file can
        # answer "what does this event do at my location" without the globe.
        "footprints": [
            {"region": f.region, "scope": f.scope, "anchor": list(f.anchor),
             "boxes": [[b.lon0, b.lon1, b.lat0, b.lat1] for b in f.boxes]}
            for f in geo.FOOTPRINTS
        ],
        # Storms: the part of this file that changes between two runs an hour
        # apart. Positions are decimal degrees, east and north positive, which
        # is not the convention ATCF stores them in - a consumer should never
        # have to know that 1015W means -101.5.
        "cyclones": {
            "as_of": state.cyclones.as_of or None,
            "season": state.cyclones.year or None,
            "through": state.cyclones.through or None,
            "elnino_seasons": list(state.cyclones.elnino_years),
            "active": [
                {
                    "id": storm.key,
                    "name": storm.title,
                    "designation": storm.designation,
                    "basin": storm.basin,
                    "basin_name": storm.basin_name,
                    "advisory": storm.advisory.get("advisory") or None,
                    "ace": round(storm.ace, 2),
                    "peak_category": storm.peak_category,
                    "rapid_intensification_kt_24h": round(storm.rapid[0], 1),
                    "track_spread_km": (
                        None if storm.spread_km is None else round(storm.spread_km)
                    ),
                    "track_spread_lead_hours": storm.spread_tau,
                    "ensemble_members": len(storm.ensemble),
                    "guidance_models": len(storm.guidance),
                    "current": _fix_json(storm.latest),
                    "forecast": [
                        _fix_json(f) for f in storm.forecast
                        if f.tau <= cyclones.HORIZON
                    ],
                    "track": [_fix_json(f) for f in storm.track if f.tau == 0],
                    "threats": [
                        {"place": place.name, "country": place.country,
                         "km": round(gap), "lead_hours": fix.tau,
                         "wind_kt": fix.wind, "intensity": fix.label}
                        for gap, fix, place in storm.threats(400.0)
                        if (fix.wind or 0) >= 34
                    ],
                    "notes": list(storm.notes),
                }
                for storm in state.cyclones.active
            ],
            "seasons": {
                basin: {
                    "name": season.name,
                    "ace": round(season.ace, 1),
                    "named": season.named,
                    "hurricanes": season.hurricanes,
                    "major": season.major,
                    "normal_ace_to_date": (
                        None if season.normal_ace is None
                        else round(season.normal_ace, 1)
                    ),
                    "normal_ace_full_season": (
                        None if season.full_normal_ace is None
                        else round(season.full_normal_ace, 1)
                    ),
                    "elnino_ace_to_date": (
                        None if season.elnino_ace is None
                        else round(season.elnino_ace, 1)
                    ),
                    "ratio_vs_normal": (
                        None if season.ace_ratio is None
                        else round(season.ace_ratio, 3)
                    ),
                    "season_elapsed_fraction": (
                        None if season.elapsed is None else round(season.elapsed, 3)
                    ),
                    "storms": len(season.storms),
                    "verdict": cyclones.verdict(
                        season, a.index_latest.value,
                        impacts.flavour_of(a.scale.flavour_index if a.scale else 0.0),
                    ),
                }
                for basin, season in state.cyclones.basins.items()
            },
            "notes": list(state.cyclones.notes),
            "upgrades": list(state.cyclones.upgrades),
        },
        # Where the next storms may come from: NHC's and JTWC's formation
        # areas, with their chances or potentials and when each was issued.
        "outlook": outlook_json(state),
        # The page that draws all of the above on live satellite imagery, and
        # the JSON it re-reads, both beside this file.
        "storm_desk": dict(STORM_DESK),
        # STORMFURY, recreated: the criteria as a decision procedure, the
        # angular-momentum hypothesis computed, and the two measurements that
        # falsify it. Every number here is derived from the decks above, so a
        # consumer can re-derive it and should get the same answer.
        "stormfury": (
            {
                "as_of": state.stormfury.as_of or None,
                "verdict": state.stormfury.verdict,
                "reasons": list(state.stormfury.reasons),
                "seedable_layer_km": state.stormfury.layer,
                "programme": {
                    "ran": stormfury.PROGRAMME["ran"],
                    "agencies": stormfury.PROGRAMME["agencies"],
                    "storms_seeded": stormfury.PROGRAMME["seeded"],
                },
                "seeded_storms": [
                    {"name": h.name, "year": h.year, "dates": h.dates,
                     "claimed": h.claimed, "outcome": h.outcome}
                    for h in stormfury.HISTORY
                ],
                "assessments": [
                    {
                        "id": a.storm_key,
                        "name": a.title,
                        "basin": a.basin,
                        "wind_kt": a.wind_kt,
                        "rmw_nm": a.rmw_nm,
                        "lat": a.lat,
                        "lon": a.lon,
                        "eligible": a.eligible,
                        "blocked_by": a.blocked_by,
                        "unknown": a.unknown,
                        "criteria": [
                            {"name": c.name, "passed": c.passed,
                             "detail": c.detail}
                            for c in a.criteria
                        ],
                        # What the hypothesis predicts if the eyewall could be
                        # moved outward by each factor. It cannot be.
                        "momentum": a.momentum,
                    }
                    for a in state.stormfury.assessments
                ],
                # The hypothesis scored against eyewalls that moved on their
                # own. A closed-system momentum argument is an upper bound.
                "relocation_skill": state.stormfury.skill,
                "natural_eyewall_moves": state.stormfury.moves,
                # The confound that ended the programme, measured on this
                # season rather than cited.
                "natural_swings": {
                    key: value
                    for key, value in state.stormfury.swings.items()
                    if key != "changes"
                },
            }
            if state.stormfury.available else None
        ),
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
        "atlas": _atlas_json(state),
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


def _atlas_json(state) -> dict | None:
    """The atlas tier for a consumer: the anchors, with their statistics.

    The grids themselves are not in here. They are a megabyte of vendored
    constants that have not changed since they were generated and will not
    change between runs, so a snapshot that repeated them every hour would be
    mostly the same megabyte over and over. A consumer that wants them imports
    ``elnino.composite``.
    """
    tier = getattr(state, "atlas", None)
    if tier is None or not tier.available:
        return None

    def cell(c, ratio: bool) -> dict:
        out = {
            "value": None if c.value is None else round(c.value, 3),
            "neutral_mean": None if c.base is None else round(c.base, 3),
            "t": None if c.t is None else round(c.t, 2),
            "t_needed": None if c.crit == float("inf") else c.crit,
            "significant": c.significant,
        }
        # A percentage of a temperature is arithmetic on an interval scale and
        # means nothing: half a degree on 27 is not "two percent warmer" in any
        # sense a reader could use. Only rainfall gets one.
        if ratio:
            out["percent_of_normal"] = (None if c.percent is None
                                        else round(c.percent, 1))
        return out

    return {
        "method": (
            "Past El Ninos (RONI >= +1.0) minus neutral years (|RONI| < 0.5), "
            "per season, per grid cell, since 1979, with each event and each "
            "neutral year counted once. Welch's t accompanies every "
            "difference and is judged against each season's own 95% point of "
            "Student's t. An event under way when the grids were built is "
            "left out."
        ),
        "samples": {season: dict(block) for season, block in tier.samples.items()},
        "in_progress": list(tier.in_progress),
        "anchors": [
            {
                "title": local.title,
                "longitude": round(local.lon, 3),
                "latitude": round(local.lat, 3),
                "strongest_season": (local.strongest.season
                                     if local.strongest else None),
                "seasons": {
                    item.season: {"precip_mm_day": cell(item.precip, True),
                                  "air_degc": cell(item.air, False)}
                    for item in local.seasons
                },
                "teleconnections": [link.region for link in local.links],
            }
            for local in tier.anchors
        ],
    }


def write_json(state, path) -> None:
    path.write_text(json.dumps(payload(state), indent=2), encoding="utf-8")
