"""Renderers for spatial fields: maps, Hovmoller diagrams and depth sections.

A ``grids.Field`` is a lattice of numbers with labelled axes, and all three of
these pictures are that same object drawn with different axes. So there is one
cell renderer here and three thin wrappers around it, rather than three
near-identical chart functions.

Colour
------
Anomalies get a **diverging** ramp: two hues with a neutral grey midpoint, so
the sign of the anomaly is the first thing the eye resolves and zero disappears.
Absolute temperature and isotherm depth get **sequential** ramps: one hue,
monotone in lightness. There is no rainbow anywhere in this module, which is a
deliberate break with the convention of operational SST charts. A rainbow ramp
puts its sharpest perceptual edges at arbitrary values (the green-to-yellow
step reads as a boundary whether or not anything happens there), and it is
close to unreadable for a red-green colour-blind reader. Both ramps below were
generated in Oklab and checked with the dataviz validator: lightness is
monotone along each limb, and the poles separate by dE 12.5 to 16.6 under
deuteranopia, protanopia and tritanopia against a target of 8.

The neutral midpoint deliberately sits close to the page surface, which the
validator flags as low contrast. That is the intent - a zero anomaly should
recede - and the relief it requires is shipped: every field carries a labelled
discrete colour bar and a table view.

Dark mode gets its own steps rather than an inversion: the ramps keep their
hues but swap which end is light, so extremes stay luminous against a dark
surface and the neutral midpoint recedes into it. The steps are emitted as CSS
custom properties, so a cell is filled with ``var(--d7)`` and the whole page
re-themes without re-rendering a single rectangle.
"""

from __future__ import annotations

from . import grids
from itertools import count

from .coastline import segments
from .grids import Field, lat_name, lon_name
from .svg import Plot, esc, table

# --- ramps ------------------------------------------------------------------
# Diverging, 11 classes, index 5 is neutral. Generated in Oklab.
DIVERGING_LIGHT = (
    "#0045af", "#2269bd", "#5889ca", "#87a9d5", "#b7c8df", "#e8e8e8",
    "#e7bcb8", "#e19089", "#d6615c", "#c8222c", "#b50000",
)
DIVERGING_DARK = (
    "#61a6ff", "#568cd1", "#4c72a4", "#415979", "#364150", "#2a2a2a",
    "#553937", "#814743", "#af5550", "#df615c", "#ff6d68",
)
# Sequential warm, 9 classes, for absolute temperature.
SEQ_LIGHT = (
    "#f9f2ea", "#e6d6ce", "#d2bbb2", "#bfa096", "#ab867c", "#986c62",
    "#845449", "#713b31", "#5d231a",
)
SEQ_DARK = (
    "#30211e", "#47342e", "#604740", "#7a5c51", "#967264", "#b28877",
    "#cf9f8b", "#ecb69f", "#ffcfb4",
)
# Sequential cool, 9 classes, for depth. Dark reads as deep.
DEPTH_LIGHT = (
    "#f2f3fa", "#d1dbec", "#b0c4de", "#90adcf", "#7096c1", "#5080b2",
    "#2e69a3", "#005393", "#003c84",
)
DEPTH_DARK = (
    "#182431", "#28384a", "#394e64", "#4a6580", "#5d7d9c", "#7096ba",
    "#84afd9", "#98c9f8", "#ade4ff",
)


_CLIP = count()


def ramp_css() -> str:
    """The ramp steps as custom properties, light values with a dark override."""

    def block(prefix: str, colours: tuple[str, ...]) -> str:
        return " ".join(f"--{prefix}{i}: {c};" for i, c in enumerate(colours))

    light = " ".join((
        block("d", DIVERGING_LIGHT), block("q", SEQ_LIGHT), block("p", DEPTH_LIGHT),
    ))
    dark = " ".join((
        block("d", DIVERGING_DARK), block("q", SEQ_DARK), block("p", DEPTH_DARK),
    ))
    return (
        f":root {{ {light} }}\n"
        f'@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) '
        f"{{ {dark} }} }}\n"
        f':root[data-theme="dark"] {{ {dark} }}\n'
    )


class Ramp:
    """A discrete colour scale: value in, CSS variable out."""

    def __init__(self, prefix: str, steps: int, low: float, high: float,
                 diverging: bool = False):
        self.prefix = prefix
        self.steps = steps
        self.diverging = diverging
        if diverging:
            limit = max(abs(low), abs(high)) or 1.0
            self.low, self.high = -limit, limit
        else:
            self.low, self.high = (low, high) if high > low else (low, low + 1.0)

    def index(self, value: float) -> int:
        frac = (value - self.low) / (self.high - self.low)
        return max(0, min(self.steps - 1, int(frac * self.steps)))

    def colour(self, value: float) -> str:
        return f"var(--{self.prefix}{self.index(value)})"

    def edges(self) -> list[float]:
        width = (self.high - self.low) / self.steps
        return [self.low + i * width for i in range(self.steps + 1)]

    def auto_fmt(self) -> str:
        """Enough decimals that two adjacent tick labels cannot read the same.

        Sea surface height spans about a fifth of a metre end to end, and at one
        decimal its colour bar prints "-0.1, -0.1, +0.0, +0.0" and says nothing.
        """
        span = self.high - self.low
        if span >= 20:
            return "{:+.0f}"
        if span >= 2:
            return "{:+.1f}"
        if span >= 0.2:
            return "{:+.2f}"
        return "{:+.3f}"

    def bar(self, units: str, caption: str, fmt: str | None = None) -> str:
        """A labelled discrete colour bar. Every chart using a ramp gets one."""
        fmt = fmt or self.auto_fmt()
        edges = self.edges()
        cells = "".join(
            f'<span class="rampcell" style="background:var(--{self.prefix}{i})" '
            f'title="{esc(fmt.format(edges[i]))} to {esc(fmt.format(edges[i + 1])) }"></span>'
            for i in range(self.steps)
        )
        marks = "".join(
            f'<span class="ramptick">{esc(fmt.format(edges[i]))}</span>'
            for i in range(0, self.steps + 1, max(1, self.steps // 4))
        )
        return (
            f'<div class="ramp"><div class="ramplabel">{esc(caption)} '
            f'<span class="rampunits">{esc(units)}</span></div>'
            f'<div class="rampstrip">{cells}</div>'
            f'<div class="rampticks">{marks}</div></div>'
        )


# --- cell rendering ---------------------------------------------------------
def _edges(values: tuple[float, ...]) -> list[tuple[float, float]]:
    """Cell boundaries from centres: midpoints inside, half-steps at the ends."""
    if not values:
        return []
    if len(values) == 1:
        return [(values[0] - 0.5, values[0] + 0.5)]
    out = []
    for i, value in enumerate(values):
        left = values[i - 1] if i else value - (values[1] - values[0])
        right = values[i + 1] if i + 1 < len(values) else value + (values[-1] - values[-2])
        out.append(((value + left) / 2.0, (value + right) / 2.0))
    return out


def draw_cells(
    plot: Plot,
    grid: Field,
    ramp: Ramp,
    fmt: str = "{:+.2f}",
    row_label=None,
    col_label=None,
    hover: bool = True,
) -> int:
    """Fill the plot with the field, merging equal-coloured neighbours.

    A one-degree Pacific map is twelve thousand cells. Emitting one rectangle
    each would add about a megabyte of markup to a page that is meant to be a
    single self-contained file, so horizontally adjacent cells that land in the
    same colour class are merged into one run. On a smooth field this is a
    ten- to twenty-fold reduction and it changes nothing about what is drawn,
    because the cells were already the same colour.

    Returns the number of rectangles emitted, which the tests assert against
    the cell count to prove the run-length encoding is actually doing work.
    """
    x_edges = _edges(grid.x)
    y_edges = _edges(grid.y)
    # Edge cells are half a cell wider than the outermost centre, so the run
    # rectangles overhang the frame by design; the clip trims them to it.
    plot.add(f'<g clip-path="url(#{clip_area(plot)})">')
    drawn = 0
    for row in range(grid.rows):
        y0, y1 = plot.sy(y_edges[row][0]), plot.sy(y_edges[row][1])
        top, height = min(y0, y1), abs(y1 - y0)
        col = 0
        while col < grid.cols:
            value = grid.values[row][col]
            if value is None:
                col += 1
                continue
            klass = ramp.index(value)
            end = col
            low = high = value
            while end + 1 < grid.cols:
                nxt = grid.values[row][end + 1]
                if nxt is None or ramp.index(nxt) != klass:
                    break
                end += 1
                low, high = min(low, nxt), max(high, nxt)
            x0 = plot.sx(x_edges[col][0])
            x1 = plot.sx(x_edges[end][1])
            attrs = ""
            if hover:
                span = (
                    fmt.format(low) if end == col
                    else f"{fmt.format(low)} to {fmt.format(high)}"
                )
                where = []
                if row_label:
                    where.append(row_label(grid.y[row], row))
                if col_label:
                    where.append(
                        col_label(grid.x[col]) if end == col
                        else f"{col_label(grid.x[col])}-{col_label(grid.x[end])}"
                    )
                attrs = (
                    f' class="hit" data-label="{esc(", ".join(where))}" '
                    f'data-value="{esc(span)} {esc(grid.units)}"'
                )
            plot.add(
                f'<rect x="{min(x0, x1):.1f}" y="{top:.1f}" '
                f'width="{max(abs(x1 - x0), 0.6):.1f}" height="{max(height, 0.6):.1f}" '
                f'fill="var(--{ramp.prefix}{klass})"{attrs} shape-rendering="crispEdges"/>'
            )
            drawn += 1
            col = end + 1
    plot.add("</g>")
    return drawn


def draw_contour(plot: Plot, grid: Field, level: float, width: float = 2.0,
                 dash: str = "") -> None:
    """One isoline over an already-filled field."""
    style = f' stroke-dasharray="{dash}"' if dash else ""
    path = []
    for (x0, y0), (x1, y1) in grids.contour(grid, level):
        path.append(
            f"M{plot.sx(x0):.1f} {plot.sy(y0):.1f} L{plot.sx(x1):.1f} {plot.sy(y1):.1f}"
        )
    if path:
        plot.add(
            f'<path d="{" ".join(path)}" fill="none" stroke="var(--ink)" '
            f'stroke-width="{width}" stroke-linecap="round" opacity="0.85"{style}/>'
        )


def clip_area(plot: Plot) -> str:
    """Id of a clip path covering this plot's data area, defined once.

    Dropping vertices that fall outside the window is not clipping: a coastline
    that leaves the frame and comes back gets cut at whole-vertex granularity,
    which is why an unclipped Pacific map draws Australia across its own axis
    labels. The renderer does the cutting; we only say where.
    """
    existing = getattr(plot, "_clip", None)
    if existing:
        return existing
    name = f"clip{next(_CLIP)}"
    plot.add(
        f'<clipPath id="{name}"><rect x="{plot.left:.1f}" y="{plot.top:.1f}" '
        f'width="{plot.plot_w:.1f}" height="{plot.plot_h:.1f}"/></clipPath>'
    )
    plot._clip = name
    return name


def draw_coast(plot: Plot, lon_min: float, lon_max: float,
               lat_min: float, lat_max: float) -> None:
    """Coastlines clipped to the window, so the field sits on a real map."""
    clip = clip_area(plot)
    paths = []
    for line in segments(lon_min, lon_max):
        # A wide vertex margin, because the clip below does the real cutting and
        # a tight margin here would drop the vertex that carries a line back in.
        points = [
            (plot.sx(lon), plot.sy(lat))
            for lon, lat in line
            if lon_min - 60 <= lon <= lon_max + 60 and lat_min - 40 <= lat <= lat_max + 40
        ]
        if len(points) > 1:
            paths.append("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points))
    if paths:
        plot.add(
            f'<path d="{" ".join(paths)}" fill="none" stroke="var(--ink)" '
            f'stroke-width="0.9" opacity="0.55" stroke-linejoin="round" '
            f'clip-path="url(#{clip})"/>'
        )


def lon_axis(plot: Plot, lon_min: float, lon_max: float, step: float = 20.0) -> None:
    value = lon_min - (lon_min % step)
    while value <= lon_max:
        if lon_min <= value <= lon_max:
            x = plot.sx(value)
            plot.add(
                f'<line x1="{x:.1f}" y1="{plot.top + plot.plot_h:.1f}" x2="{x:.1f}" '
                f'y2="{plot.top + plot.plot_h + 4:.1f}" stroke="var(--axis)" stroke-width="1"/>'
            )
            plot.add(
                f'<text x="{x:.1f}" y="{plot.top + plot.plot_h + 16:.1f}" '
                f'text-anchor="middle" class="tick">{esc(lon_name(value))}</text>'
            )
        value += step


def lat_axis(plot: Plot, lat_min: float, lat_max: float, step: float = 10.0) -> None:
    value = lat_min - (lat_min % step)
    while value <= lat_max:
        if lat_min <= value <= lat_max:
            y = plot.sy(value)
            plot.add(
                f'<text x="{plot.left - 7:.1f}" y="{y + 4:.1f}" text-anchor="end" '
                f'class="tick">{esc(lat_name(value))}</text>'
            )
        value += step


def frame(plot: Plot) -> None:
    plot.add(
        f'<rect x="{plot.left:.1f}" y="{plot.top:.1f}" width="{plot.plot_w:.1f}" '
        f'height="{plot.plot_h:.1f}" fill="none" stroke="var(--axis)" stroke-width="1"/>'
    )


# --- table twins ------------------------------------------------------------
def field_table(grid: Field, caption: str, fmt: str = "{:+.2f}",
                max_rows: int = 26, max_cols: int = 14) -> str:
    """A readable numeric twin of a field, decimated to something legible.

    A 12,000-cell map cannot become a 12,000-cell table and still be a table.
    Rows and columns are sampled evenly, and the caption says so, because a
    silently decimated table would be worse than none.
    """
    row_step = max(1, grid.rows // max_rows)
    col_step = max(1, grid.cols // max_cols)
    rows_used = list(range(0, grid.rows, row_step))
    cols_used = list(range(0, grid.cols, col_step))

    if grid.y_name == "time":
        head = [grid.y_labels[i] if i < len(grid.y_labels) else str(i) for i in rows_used]
        corner = "longitude"
        headers = [corner] + head
        body = []
        for col in cols_used:
            line = [lon_name(grid.x[col])]
            for row in rows_used:
                value = grid.values[row][col]
                line.append(fmt.format(value) if value is not None else "-")
            body.append(line)
    else:
        namer = (lambda v: f"{v:.0f} m") if grid.y_name == "depth" else lat_name
        headers = [grid.y_name] + [lon_name(grid.x[c]) for c in cols_used]
        body = []
        for row in rows_used:
            line = [namer(grid.y[row])]
            for col in cols_used:
                value = grid.values[row][col]
                line.append(fmt.format(value) if value is not None else "-")
            body.append(line)

    note = ""
    if row_step > 1 or col_step > 1:
        note = f" (every {row_step} by {col_step} cell)"
    return table(f"{caption}{note}", headers, body)


# --- panels -----------------------------------------------------------------
def _hov_time_axis(plot: Plot, grid: Field) -> None:
    """Quarter ticks down the side of a Hovmoller, thinned to fit.

    Two separate things have to be guarded here. A weekly product has four or
    five rows inside the same month, so labelling "the month is January" labels
    all of them; and a tall enough window has more quarters than there is room
    for, so the survivors still have to be spaced by pixels rather than by
    calendar.
    """
    labels = grid.y_labels
    if not labels:
        return
    seen: set[tuple[str, str]] = set()
    last_y: float | None = None
    first = True
    for row, stamp in enumerate(labels):
        year, month = stamp[:4], stamp[5:7]
        if month not in ("01", "04", "07", "10") or (year, month) in seen:
            continue
        seen.add((year, month))
        y = plot.sy(float(row))
        if last_y is not None and abs(y - last_y) < 16.0:
            continue
        last_y = y
        text = f"{year}-{month}" if month == "01" or first else month
        first = False
        plot.add(
            f'<text x="{plot.left - 7:.1f}" y="{y + 4:.1f}" text-anchor="end" '
            f'class="tick">{esc(text)}</text>'
        )
        plot.add(
            f'<line x1="{plot.left - 4:.1f}" y1="{y:.1f}" x2="{plot.left:.1f}" '
            f'y2="{y:.1f}" stroke="var(--axis)" stroke-width="1"/>'
        )


def sst_map(grid: Field, box_means: dict[str, float],
            warm_pool: float | None) -> str:
    """Tropical Pacific SST anomaly, with the Nino boxes drawn where they are.

    The boxes are on the map because the whole index system is an average over
    these rectangles, and a reader should be able to see how much of each box
    the anomaly actually fills. A basin-wide plus two degrees and a tight
    coastal tongue can give the same Nino-3 number and mean very different
    things.
    """
    lon_min, lon_max = grid.x[0], grid.x[-1]
    lat_min, lat_max = grid.y[0], grid.y[-1]
    plot = Plot(880, 372, (14, 16, 26, 44))
    plot.domain(lon_min, lon_max, lat_min, lat_max)

    low, high = grid.robust_span()
    ramp = Ramp("d", 11, low, high, diverging=True)
    draw_cells(plot, grid, ramp, row_label=lambda v, _i: lat_name(v), col_label=lon_name)
    draw_coast(plot, lon_min, lon_max, lat_min, lat_max)

    # Equator, then the boxes on top of it.
    plot.add(
        f'<line x1="{plot.left:.1f}" y1="{plot.sy(0):.1f}" '
        f'x2="{plot.left + plot.plot_w:.1f}" y2="{plot.sy(0):.1f}" '
        f'stroke="var(--ink)" stroke-width="0.8" stroke-dasharray="2 4" opacity="0.5"/>'
    )
    for box in grids.NINO_BOXES:
        if box.lon1 < lon_min or box.lon0 > lon_max:
            continue
        x0, x1 = plot.sx(max(box.lon0, lon_min)), plot.sx(min(box.lon1, lon_max))
        y0, y1 = plot.sy(box.lat1), plot.sy(box.lat0)
        plot.add(
            f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{x1 - x0:.1f}" '
            f'height="{y1 - y0:.1f}" fill="none" stroke="var(--ink)" '
            f'stroke-width="1.6" opacity="0.8"/>'
        )
        mean = box_means.get(box.key)
        caption = box.label + (f" {mean:+.2f}" if mean is not None else "")
        # Nino-1+2 is the only box that does not straddle the equator, so its top
        # edge runs straight through Nino-3 and a label above it lands inside its
        # neighbour. That one goes underneath instead.
        y_label = y1 + 13.0 if box.lat1 <= 0.0 else y0 - 4.0
        plot.add(
            f'<text x="{(x0 + x1) / 2:.1f}" y="{y_label:.1f}" text-anchor="middle" '
            f'class="boxlabel">{esc(caption)}</text>'
        )

    if warm_pool is not None and lon_min <= warm_pool <= lon_max:
        x = plot.sx(warm_pool)
        plot.add(
            f'<line x1="{x:.1f}" y1="{plot.top:.1f}" x2="{x:.1f}" '
            f'y2="{plot.top + plot.plot_h:.1f}" stroke="var(--s3)" stroke-width="2.4"/>'
        )
        plot.add(
            f'<text x="{x - 6:.1f}" y="{plot.top + 14:.1f}" text-anchor="end" '
            f'class="pointlabel" fill="var(--s3)">28 C edge {esc(lon_name(warm_pool))}</text>'
        )

    lon_axis(plot, lon_min, lon_max, 20.0)
    lat_axis(plot, lat_min, lat_max, 10.0)
    frame(plot)

    edge_line = ""
    if warm_pool is not None:
        edge_line = (
            f" The eastern edge of the 28 C warm pool on the equator sits at "
            f"<strong>{esc(lon_name(warm_pool))}</strong>; in a neutral year it is "
            f"near 180."
        )
    return f"""<section class="card">
  <h2>Where the anomaly actually is</h2>
  <p class="caption">Daily OISST v2.1 sea-surface temperature anomaly for
    {esc(grid.as_of)}, on a one-degree sample of the quarter-degree analysis. The four
    Nino boxes are drawn in their real positions with their area-weighted means, so the
    shape of the anomaly can be compared against the index it produces.{edge_line}</p>
  {ramp.bar('degrees C', 'SST anomaly')}
  <div class="chart wide">{plot.svg(
      'Tropical Pacific sea surface temperature anomaly map',
      'Map of the tropical Pacific shaded by sea surface temperature anomaly, with '
      'coastlines and the four Nino index boxes marked.')}</div>
  {field_table(grid, 'SST anomaly by latitude and longitude, degrees C')}
</section>"""


def global_map(grid: Field) -> str:
    """The rest of the world, because ENSO is not only a Pacific event."""
    lon_min, lon_max = grid.x[0], grid.x[-1]
    lat_min, lat_max = grid.y[0], grid.y[-1]
    plot = Plot(880, 420, (10, 14, 26, 40))
    plot.domain(lon_min, lon_max, lat_min, lat_max)

    low, high = grid.robust_span()
    ramp = Ramp("d", 11, low, high, diverging=True)
    draw_cells(plot, grid, ramp, row_label=lambda v, _i: lat_name(v), col_label=lon_name)
    draw_coast(plot, lon_min, lon_max, lat_min, lat_max)
    lon_axis(plot, lon_min, lon_max, 40.0)
    lat_axis(plot, lat_min, lat_max, 20.0)
    frame(plot)

    return f"""<section class="card">
  <h2>The same day, worldwide</h2>
  <p class="caption">Global SST anomaly for {esc(grid.as_of)} at two and a half degrees.
    Context for the Pacific map above: the Indian Ocean and tropical Atlantic states
    modify the atmospheric response, and a basin-wide warm background is the reason the
    relative ONI exists at all.</p>
  {ramp.bar('degrees C', 'SST anomaly')}
  <div class="chart wide">{plot.svg(
      'Global sea surface temperature anomaly map',
      'World map shaded by sea surface temperature anomaly for the latest available day.')}</div>
  {field_table(grid, 'global SST anomaly, degrees C', max_rows=18, max_cols=16)}
</section>"""


def hovmoller(grid: Field, title: str, caption: str, diverging: bool = True,
              fmt: str = "{:+.2f}", units: str = "degrees C",
              ramp_caption: str = "anomaly", extra: str = "") -> str:
    """Time down, longitude across: how the anomaly moved.

    Time runs downward so that a feature propagating east appears as a stripe
    leaning to the right as you read down the page, which is the orientation
    every operational centre uses and the one an experienced reader will
    already have calibrated against.
    """
    plot = Plot(560, 470, (14, 18, 28, 58))
    plot.domain(grid.x[0], grid.x[-1], float(grid.rows - 1) + 0.5, -0.5)

    low, high = grid.robust_span()
    ramp = Ramp("d" if diverging else "p", 11 if diverging else 9, low, high,
                diverging=diverging)
    draw_cells(
        plot, grid, ramp, fmt=fmt,
        row_label=lambda _v, i: grid.y_labels[i] if i < len(grid.y_labels) else "",
        col_label=lon_name,
    )
    lon_axis(plot, grid.x[0], grid.x[-1], 20.0)
    _hov_time_axis(plot, grid)
    # Dateline: the single most useful reference on this diagram.
    if grid.x[0] <= 180.0 <= grid.x[-1]:
        x = plot.sx(180.0)
        plot.add(
            f'<line x1="{x:.1f}" y1="{plot.top:.1f}" x2="{x:.1f}" '
            f'y2="{plot.top + plot.plot_h:.1f}" stroke="var(--ink)" stroke-width="0.9" '
            f'stroke-dasharray="3 3" opacity="0.5"/>'
        )
    frame(plot)

    return f"""<div>
  {ramp.bar(units, ramp_caption, fmt=None if diverging else '{:.0f}')}
  <div class="chart">{plot.svg(title, caption)}</div>
  {extra}
</div>"""


def section(grid: Field, absolute: Field | None, title: str) -> str:
    """Depth against longitude on the equator: the thermocline itself.

    This is the one picture that shows the mechanism rather than its symptom.
    In a neutral Pacific the 20 C isotherm sits near 150 m in the west and 50 m
    in the east; the flattening of that slope *is* El Nino, and the surface
    warming follows from it.
    """
    plot = Plot(560, 400, (16, 20, 30, 50))
    plot.domain(grid.x[0], grid.x[-1], grid.y[-1], grid.y[0])

    diverging = "anomaly" in grid.label.lower()
    low, high = grid.robust_span(0.01, 0.99)
    ramp = (Ramp("d", 11, low, high, diverging=True) if diverging
            else Ramp("q", 9, low, high))
    draw_cells(
        plot, grid, ramp,
        row_label=lambda v, _i: f"{v:.0f} m", col_label=lon_name,
    )
    if absolute is not None:
        draw_contour(plot, absolute, 20.0, width=2.2)

    for depth in (0, 50, 100, 150, 200, 250, 300):
        y = plot.sy(float(depth))
        plot.add(
            f'<text x="{plot.left - 7:.1f}" y="{y + 4:.1f}" text-anchor="end" '
            f'class="tick">{depth}</text>'
        )
    lon_axis(plot, grid.x[0], grid.x[-1], 20.0)
    plot.add(
        f'<text x="6" y="{plot.top + plot.plot_h / 2:.1f}" class="axislabel" '
        f'transform="rotate(-90 6 {plot.top + plot.plot_h / 2:.1f})" '
        f'text-anchor="middle">depth (m)</text>'
    )
    frame(plot)

    ramp_bar = ramp.bar(
        "degrees C",
        "temperature anomaly" if diverging else "temperature",
        fmt="{:+.1f}" if diverging else "{:.0f}",
    )
    legend = ""
    if absolute is not None:
        legend = (
            '<div class="legend"><span class="key">'
            '<span class="swatch swatch-line"></span>20 C isotherm</span></div>'
        )
    return f"""<div>
  {ramp_bar}{legend}
  <div class="chart">{plot.svg(title, grid.label + ' by depth and longitude on the equator')}</div>
</div>"""


def _stale_chip(state, name: str, threshold: int) -> str:
    """Say so on the panel when a feed is behind, rather than implying currency."""
    age = state.stale.get(name)
    if age is None or age <= threshold:
        return ""
    return (
        f'<span class="chip chip-warning">{age} days behind</span>'
    )


def hov_card(state) -> str:
    """The three propagation diagrams, side by side on one time axis.

    Surface temperature, thermocline depth and sea surface height are three
    independent measurements of the same wave. Putting them in one card lets a
    reader check that a feature seen in one appears in the others, which is the
    difference between a Kelvin wave and an artefact of a single instrument.
    """
    panels = []
    if state.sst_hov is not None:
        panels.append(hovmoller(
            state.sst_hov,
            "Equatorial SST anomaly, time by longitude",
            "Hovmoller diagram of sea surface temperature anomaly on the equator, with "
            "time running downward and longitude across.",
            extra='<p class="subcaption">OISST v2.1, 2S-2N mean, weekly samples.</p>',
        ))
    if state.iso_hov_anomaly is not None:
        panels.append(hovmoller(
            state.iso_hov_anomaly,
            "20 C isotherm depth anomaly, time by longitude",
            "Hovmoller diagram of the depth anomaly of the 20 degree isotherm on the "
            "equator. A downwelling Kelvin wave appears as a band sloping to the right.",
            fmt="{:+.0f}", units="m", ramp_caption="thermocline anomaly",
            extra='<p class="subcaption">TAO/TRITON moorings. Positive is deeper.</p>',
        ))
    if state.ssh_hov is not None:
        chip = _stale_chip(state, "ssh_hov", 21)
        panels.append(hovmoller(
            state.ssh_hov,
            "Sea surface height anomaly, time by longitude",
            "Hovmoller diagram of sea surface height anomaly from altimetry on the "
            "equator.",
            fmt="{:+.2f}", units="m", ramp_caption="height anomaly",
            extra=f'<p class="subcaption">Altimetry, experimental product. {chip}</p>',
        ))
    if not panels:
        return ""

    tables = []
    for grid, caption in (
        (state.sst_hov, "equatorial SST anomaly, degrees C"),
        (state.iso_hov_anomaly, "20 C isotherm depth anomaly, m"),
        (state.ssh_hov, "sea surface height anomaly, m"),
    ):
        if grid is not None:
            fmt = "{:+.0f}" if grid.units == "m" and "isotherm" in grid.label else "{:+.2f}"
            tables.append(field_table(grid, caption, fmt=fmt, max_rows=17, max_cols=10))

    return f"""<section class="card">
  <h2>How the anomaly moved</h2>
  <p class="caption">Time runs downward, longitude across, so anything travelling east
    leans to the right as you read down. These are three independent instruments
    watching the same ocean: a feature that appears in all three is a wave, a feature
    that appears in one is an instrument. The dashed line is the dateline.</p>
  <div class="threeup">{''.join(panels)}</div>
  {''.join(tables)}
</section>"""


def section_card(state) -> str:
    """Absolute temperature and its anomaly, on the same depth-longitude frame."""
    if state.section is None:
        return ""
    panels = [section(
        state.section, state.section,
        "Equatorial Pacific temperature by depth and longitude",
    )]
    if state.section_anomaly is not None:
        panels.append(section(
            state.section_anomaly, state.section,
            "Equatorial Pacific temperature anomaly by depth and longitude",
        ))

    depths = {
        lon_name(p.lon): p.isotherm() for p in state.profiles
    }
    known = {k: v for k, v in depths.items() if v is not None}
    tilt = ""
    measured = grids.tilt(list(known.values()))
    if measured is not None:
        drop, west, east = measured
        tilt = (
            f" The 20 C isotherm averages {west:.0f} m across the two westernmost "
            f"moorings and {east:.0f} m across the two easternmost, a tilt of "
            f"<strong>{drop:.0f} m</strong> across the basin. A neutral Pacific runs "
            f"near 100 m of tilt and a mature El Nino flattens it."
        )

    rows = [[k, f"{v:.0f}"] for k, v in known.items()]
    return f"""<section class="card">
  <h2>The thermocline in cross-section</h2>
  <p class="caption">Equatorial Pacific temperature against depth, {esc(state.section.as_of)},
    from the TAO/TRITON moorings. This is the mechanism rather than the symptom: the
    surface warming that the indices measure is what happens after this slope
    relaxes.{tilt} The heavy line is the 20 C isotherm, the conventional marker for the
    centre of the thermocline.</p>
  <div class="twoup">{''.join(panels)}</div>
  {field_table(state.section, 'equatorial temperature by depth and longitude, degrees C',
               fmt='{:.1f}', max_rows=16, max_cols=12)}
  {table('20 C isotherm depth by mooring', ['longitude', 'depth (m)'], rows)}
</section>"""


def ssh_card(state) -> str:
    """Altimetric sea surface height: heat content seen from orbit."""
    if state.ssh_map is None:
        return ""
    grid = state.ssh_map
    lon_min, lon_max = grid.x[0], grid.x[-1]
    lat_min, lat_max = grid.y[0], grid.y[-1]
    plot = Plot(880, 330, (14, 16, 26, 44))
    plot.domain(lon_min, lon_max, lat_min, lat_max)
    low, high = grid.robust_span()
    ramp = Ramp("d", 11, low, high, diverging=True)
    draw_cells(plot, grid, ramp, fmt="{:+.2f}",
               row_label=lambda v, _i: lat_name(v), col_label=lon_name)
    draw_coast(plot, lon_min, lon_max, lat_min, lat_max)
    lon_axis(plot, lon_min, lon_max, 20.0)
    lat_axis(plot, lat_min, lat_max, 10.0)
    frame(plot)

    chip = _stale_chip(state, "ssh_map", 21)
    return f"""<section class="card">
  <h2>Sea level, which is heat content you can see from orbit</h2>
  <p class="caption">Sea surface height anomaly for {esc(grid.as_of)}. {chip}
    Warm water expands, so height is a direct proxy for the heat stored in the upper
    ocean and an independent check on the mooring array. This is an experimental
    product and it runs behind the rest of the system; the date above is the date of
    the field, not of this run.</p>
  {ramp.bar('m', 'height anomaly')}
  <div class="chart wide">{plot.svg(
      'Sea surface height anomaly map',
      'Map of the tropical Pacific shaded by sea surface height anomaly from '
      'satellite altimetry.')}</div>
  {field_table(grid, 'sea surface height anomaly, m')}
</section>"""
