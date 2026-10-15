"""Series day by day: the Nino boxes, the Indian Ocean Dipole, the SOI and the
westerly wind events, and the plot that draws them.

The classification runs on CPC's weekly and monthly indices, and the Bureau of
Meteorology watches the Indian Ocean's dipole week by week, all out days or
weeks after the time they describe. A series here is the same kind of
quantity a day at a time, a day or two behind. One plot draws them all:
the days on a common axis, a day with no value breaking its line rather than
bridging it, a preliminary analysis's days shaded, a line at each threshold
the series is judged by, each line's latest value at its end, and a column
over every day to hover or focus with all of that day's values. A ``Chart``
says what a series draws; its card says what it means.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from . import windclim
from .fields import EVERY_MONTH, OISST_BASE, _behind, field_table, hovmoller
from .svg import Plot, _legend, esc, nice_ticks, table
from .winds import EQUATORIAL, HV97_EVENTS, HV97_LONGEST, REGIONS_BY_KEY, THRESHOLD, Event, Winds


@dataclass(frozen=True)
class Line:
    """A series' line: the key of its value in a day's values, its name and
    colour, and how heavily it is drawn."""

    key: str
    name: str
    colour: str
    width: float = 2.0
    opacity: float = 1.0


@dataclass(frozen=True)
class Mark:
    """A threshold drawn across the plot and named over the lines."""

    value: float
    label: str
    colour: str


@dataclass(frozen=True)
class Chart:
    """What a plot of days draws: its lines, the first the one its caption
    leads with, drawn last and so on top; the thresholds it marks; the unit
    its leading value is written with, and to how many decimals its values
    are; how far either side of zero its axis reaches at least, which keeps
    the marks in view; what a day without the leading value says; and how its
    axis's ticks are written."""

    lines: tuple[Line, ...]
    marks: tuple[Mark, ...]
    unit: str
    digits: int
    floor: float
    missing: str = "not analysed"
    ticks: str = "{:+.1f}"

    def fmt(self, value: float) -> str:
        return f"{value:+.{self.digits}f}"


# Each box's line, in the legend's order: Nino-3.4 first, the index the
# classification runs on, then the boxes west to east.
NINO = Chart(
    lines=(Line("nino34", "Nino-3.4", "var(--s1)"), Line("nino4", "Nino-4", "var(--s2)"),
           Line("nino3", "Nino-3", "var(--s3)"), Line("nino12", "Nino-1+2", "var(--s4)")),
    marks=(Mark(0.5, "El Nino threshold +0.5", "var(--warm)"),),
    unit=" °C", digits=2, floor=0.6,
)
# The Dipole Mode Index first, the difference the Bureau of Meteorology judges,
# then its poles west to east; the revision sentence calls each by its article.
DIPOLE = Chart(
    lines=(Line("dmi", "DMI", "var(--s1)"), Line("west", "West pole", "var(--s2)"),
           Line("east", "East pole", "var(--s3)")),
    marks=(Mark(0.4, "positive IOD +0.4", "var(--warm)"),
           Mark(-0.4, "negative IOD -0.4", "var(--cool)")),
    unit=" °C", digits=2, floor=0.6,
)
DIPOLE_NAMES = {"dmi": "the DMI", "west": "the west pole", "east": "the east pole"}
# The 30- and 90-day SOI, the means of the days' values, over each day's own
# value drawn faint: a day's pressures are weather as much as climate. The SOI
# is a pure number, and El Nino lowers it.
SOI = Chart(
    lines=(Line("soi30", "30-day SOI", "var(--s1)"), Line("soi90", "90-day SOI", "var(--s2)"),
           Line("soi", "Daily SOI", "var(--s3)", width=1.0, opacity=0.5)),
    marks=(Mark(7.0, "La Nina-like +7", "var(--cool)"),
           Mark(-7.0, "El Nino-like -7", "var(--warm)")),
    unit="", digits=1, floor=10.0, missing="not worked out", ticks="{:+.0f}",
)
# The equatorial regions' smoothed westerly anomalies, west to east, the
# regions whose events force Kelvin waves; each one's events are shaded in its
# colour.
WINDS = Chart(
    lines=(Line("W", "West", "var(--s1)"), Line("C", "Central", "var(--s2)"),
           Line("E", "East", "var(--s3)")),
    marks=(Mark(THRESHOLD, f"event threshold {THRESHOLD:+g} m/s", "var(--warm)"),),
    unit=" m/s", digits=1, floor=3.0, missing="not smoothed", ticks="{:+.0f}",
)
# The SOI card's span, in days back from the file's latest: four months, long
# enough to hold a turn of the 90-day mean.
SOI_DAYS = 120
# Line-end labels nearer each other than this, in plot units, are moved apart.
LABEL_GAP = 13.0
# A band's lane, in plot units: a bar 5 high and a gap of 2, the lanes down
# from the plot's top in the room its axis leaves above the highest value.
LANE = 7.0
# CPC dates a week by its centre, a Wednesday ("week centered on"); a week is
# set against the days within WEEK_HALF of it when WEEK_DAYS of them are drawn.
WEEK_HALF, WEEK_DAYS = 3, 5


def _day_label(day: date) -> str:
    """"12 Oct 2026", as the page writes a day."""
    return f"{day.day} {day:%b %Y}"


def _stretch_d(points: list[tuple[float, float]]) -> str:
    """One unbroken stretch of a line, as path data; a stretch of one day is
    a dot (a zero-length segment, drawn by the round cap)."""
    head = f"M{points[0][0]:.1f} {points[0][1]:.1f}"
    return head + ("".join(f" L{x:.1f} {y:.1f}" for x, y in points[1:]) or " h0")


def _apart(wanted: list[float], gap: float, top: float, bottom: float) -> list[float]:
    """Heights for labels wanted at ``wanted``, in order down the page: each
    at least ``gap`` below the one before, the stack moved up if it runs past
    ``bottom`` and back down if that takes it over ``top``."""
    placed: list[float] = []
    for y in wanted:
        placed.append(y if not placed else max(y, placed[-1] + gap))
    if placed and placed[-1] > bottom:
        placed = [y - (placed[-1] - bottom) for y in placed]
    if placed and placed[0] < top:
        placed = [y + (top - placed[0]) for y in placed]
    return placed


def _month_ticks(plot: Plot, first: date, last: date, x_of) -> None:
    """Each month's name under its first day, January's with its year."""
    month = date(first.year, first.month, 1)
    while month <= last:
        if month >= first:
            name = f"{month:%b}" if month.month != 1 else f"{month:%b %Y}"
            plot.add(
                f'<text x="{x_of(month):.1f}" y="{plot.h - plot.bottom + 20:.1f}" '
                f'text-anchor="middle" class="tick">{name}</text>'
            )
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)


def _end_labels(plot: Plot, ends, chart: Chart) -> None:
    """A dot on each line's last day, and the line's name and latest value
    past the plot's right edge, moved apart where they would overlap."""
    ends = sorted(ends, key=lambda end: end[0][1])
    heights = _apart([end[0][1] for end in ends], LABEL_GAP, plot.top + 4.0,
                     plot.top + plot.plot_h)
    for ((ex, ey), name, colour, value), y in zip(ends, heights):
        plot.add(
            f'<circle cx="{ex:.1f}" cy="{ey:.1f}" r="4" fill="{colour}" '
            f'stroke="var(--surface)" stroke-width="2" />'
        )
        plot.add(
            f'<text x="{plot.left + plot.plot_w + 8:.1f}" y="{y + 4:.1f}" class="endlabel">'
            f'{esc(name)} {chart.fmt(value)}</text>'
        )


def _day_columns(plot: Plot, values: dict, chart: Chart, preliminary, notes: dict,
                 x_of, column: float) -> None:
    """A column over each day to hover or focus, with the day's value of each
    line, the leading one with its unit, and then the day's notes."""
    lead, rest = chart.lines[0], chart.lines[1:]
    for day, day_values in values.items():
        main = day_values.get(lead.key)
        value = (f"{lead.name} {chart.fmt(main)}{chart.unit}" if main is not None
                 else f"{lead.name} {chart.missing}")
        extra = [f"{line.name} {chart.fmt(day_values[line.key])}" for line in rest
                 if line.key in day_values]
        extra += notes.get(day, [])
        label = _day_label(day) + (", preliminary" if day in preliminary else "")
        plot.add(
            f'<rect class="hit" x="{x_of(day) - column / 2:.1f}" y="{plot.top:.1f}" '
            f'width="{column:.1f}" height="{plot.plot_h:.1f}" fill="transparent" tabindex="0" '
            f'data-label="{esc(label)}" data-value="{esc(value)}" '
            f'data-extra="{esc(" · ".join(extra))}"></rect>'
        )


def _plot(values: dict[date, dict[str, float]], chart: Chart,
          preliminary: frozenset[date] = frozenset(),
          dots: tuple[tuple[date, float], ...] = (),
          notes: dict[date, list[str]] | None = None,
          bands: tuple[tuple[date, date, str], ...] = ()) -> Plot:
    """The days drawn: each of ``chart``'s lines from ``values``, each day's
    value of each line by its key, in the order of the days; the
    ``preliminary`` days shaded; ``bands``, spans of days from one to another,
    each a bar in the lane of a line, by its key, in its colour; the marks;
    ``dots``, days and values drawn as hollow dots in the leading line's
    colour; each line's latest value; and a column over each day with its
    values and its ``notes``."""
    dates = list(values)
    first, last = dates[0], dates[-1]
    span = (last - first).days
    drawn = [day[line.key] for day in values.values() for line in chart.lines
             if line.key in day]
    drawn += [value for _day, value in dots]
    low, high = min(drawn + [-chart.floor]), max(drawn + [chart.floor])
    pad = (high - low) * 0.14
    plot = Plot(760, 320, (26, 120, 44, 52))
    plot.domain(-0.5, span + 0.5, low - pad, high + pad)
    plot.gridlines(nice_ticks(low - pad, high + pad, 6), chart.ticks)
    column = plot.plot_w / (span + 1)

    def x_of(day: date) -> float:
        return plot.sx((day - first).days)

    shaded = [day for day in dates if day in preliminary]
    if shaded:
        x0 = x_of(shaded[0]) - column / 2
        plot.add(
            f'<rect class="prelim" x="{x0:.1f}" y="{plot.top:.1f}" '
            f'width="{plot.left + plot.plot_w - x0:.1f}" height="{plot.plot_h:.1f}" '
            f'fill="var(--track)" opacity="0.6"/>'
        )
        plot.add(f'<text x="{x0 + 4:.1f}" y="{plot.top - 8:.1f}" class="band-note">preliminary</text>')
    lanes = {line.key: (lane, line.colour) for lane, line in enumerate(chart.lines)}
    for start, end, key in bands:
        lane, colour = lanes[key]
        x0, x1 = x_of(max(start, first)) - column / 2, x_of(min(end, last)) + column / 2
        plot.add(
            f'<rect class="band" x="{x0:.1f}" y="{plot.top + 3 + lane * LANE:.1f}" '
            f'width="{x1 - x0:.1f}" height="{LANE - 2:.1f}" fill="{colour}" rx="1.5"/>'
        )

    for mark in chart.marks:
        y = plot.sy(mark.value)
        plot.add(
            f'<line x1="{plot.left}" y1="{y:.1f}" x2="{plot.left + plot.plot_w:.1f}" '
            f'y2="{y:.1f}" stroke="{mark.colour}" stroke-width="1" opacity="0.45" />'
        )
    _month_ticks(plot, first, last, x_of)

    # A day with no value breaks the line rather than bridging it; the
    # leading line is drawn last, on top.
    ends = []
    for line in reversed(chart.lines):
        stretches, stretch, latest = [], [], None
        for offset in range(span + 1):
            day = first + timedelta(days=offset)
            value = values[day].get(line.key) if day in values else None
            if value is None:
                if stretch:
                    stretches.append(stretch)
                stretch = []
                continue
            stretch.append((x_of(day), plot.sy(value)))
            latest = value
        if stretch:
            stretches.append(stretch)
        if not stretches:
            continue
        path = " ".join(_stretch_d(points) for points in stretches)
        faint = f' opacity="{line.opacity:g}"' if line.opacity < 1 else ""
        plot.add(
            f'<path d="{path}" class="dayline" stroke="{line.colour}" fill="none" '
            f'stroke-width="{line.width:g}"{faint} stroke-linejoin="round" '
            f'stroke-linecap="round" />'
        )
        ends.append((stretches[-1][-1], line.name, line.colour, latest))

    for day, value in dots:
        plot.add(
            f'<circle class="weekdot" cx="{x_of(day):.1f}" '
            f'cy="{plot.sy(value):.1f}" r="4.5" fill="var(--surface)" '
            f'stroke="{chart.lines[0].colour}" stroke-width="2" />'
        )
    # The marks' names over the lines, which would hide them at the left edge.
    for mark in chart.marks:
        plot.add(f'<text x="{plot.left + 6}" y="{plot.sy(mark.value) - 6:.1f}" '
                 f'class="band-note">{esc(mark.label)}</text>')
    _end_labels(plot, ends, chart)
    _day_columns(plot, values, chart, preliminary, notes or {}, x_of, column)
    return plot


def _analyses(days) -> str:
    """Which of NOAA's two analyses the days are, in words: the final's span,
    then the preliminary's."""
    finals = [item for item in days if not item.preliminary]
    prelims = [item for item in days if item.preliminary]
    spans = []
    if finals:
        spans.append(f"NOAA&rsquo;s final analysis from {finals[0].day} to {finals[-1].day}")
    if prelims:
        spans.append(f"NOAA&rsquo;s preliminary analysis from {prelims[0].day} to {prelims[-1].day}")
    return ", then ".join(spans)


def _analysis_rows(days, chart: Chart) -> list[list[str]]:
    """A table's rows, latest first: each day, which analysis it is, and its
    value of each of ``chart``'s lines, a dash where it has none."""
    return [[item.day, "preliminary" if item.preliminary else "final"]
            + [chart.fmt(item.means[line.key]) if line.key in item.means else "—"
               for line in chart.lines]
            for item in reversed(days)]


def _latest_words(values: dict[date, dict[str, float]], last: date, chart: Chart,
                  subject: str) -> str:
    """The leading value on the latest day, named ``subject``, and how far it
    moved on the week."""
    key = chart.lines[0].key
    now = values[last].get(key)
    if now is None:
        return ""
    then = values.get(last - timedelta(days=7), {}).get(key)
    words = f" {subject} is <strong>{chart.fmt(now)}{chart.unit}</strong> on {_day_label(last)}"
    return words + (f", {chart.fmt(now - then)}{chart.unit} on the week."
                    if then is not None else ".")


def _revision_words(revision, chart: Chart, higher: str, lower: str,
                    names: dict[str, str] | None = None) -> str:
    """How far the final moved the preliminary's leading value on the days
    both analyses carry, ``higher`` or ``lower`` saying which way the final
    runs; and the line it moved most on a day, when that is another. Each
    line is called by its name, or as ``names`` calls it ("the DMI")."""
    moved = (revision or {}).get(chart.lines[0].key)
    if not moved:
        return ""
    names = {line.key: line.name for line in chart.lines} | (names or {})
    where = f"in {names[chart.lines[0].key]}"
    if round(abs(moved.mean), 2) == 0:
        runs = f"the final and the preliminary agree {where} on average, and differ"
    else:
        runs = (f"the final runs {abs(moved.mean):.2f}{chart.unit} "
                f"{higher if moved.mean > 0 else lower} than the preliminary {where} on "
                f"average, and differs")
    widest, most = max(((key, item.most) for key, item in revision.items()),
                       key=lambda pair: pair[1])
    also = f" ({most:.2f}{chart.unit} in {names[widest]})" if most > moved.most else ""
    return (f" On the {moved.days} days both analyses carry, {runs} by up to "
            f"{moved.most:.2f}{chart.unit} on a day{also}: about how far the shaded days may "
            f"yet move.")


# --- the Nino boxes ---------------------------------------------------------------
def _cpc_offset(by_day: dict, weeks) -> tuple[int, float] | None:
    """How far the days' Nino-3.4 runs from CPC's weekly index: the mean, over
    the weeks with WEEK_DAYS of their seven days drawn, of those days' mean
    less CPC's value, with how many weeks that is. None when no week has."""
    gaps = []
    for week in weeks:
        around = (week.week_ending + timedelta(days=k) for k in range(-WEEK_HALF, WEEK_HALF + 1))
        values = [by_day[day].means["nino34"] for day in around
                  if day in by_day and "nino34" in by_day[day].means]
        if len(values) >= WEEK_DAYS:
            gaps.append(sum(values) / len(values) - week.nino34_anom)
    return (len(gaps), sum(gaps) / len(gaps)) if gaps else None


def _cpc_words(by_day: dict, shown) -> str:
    """CPC's weekly index named, and how far the days run from it."""
    if not shown:
        return ""
    words = (" CPC&rsquo;s traditional weekly Nino-3.4, the hollow dots, is against "
             "1991&ndash;2020.")
    measured = _cpc_offset(by_day, shown)
    if not measured:
        return words
    count, offset = measured
    weeks_words = "the one week" if count == 1 else f"the {count} weeks"
    # CPC publishes its weekly index to the tenth, so an offset within half of
    # one is no offset at all.
    how = ("agrees with CPC&rsquo;s within its rounding to tenths"
           if round(abs(offset), 2) < 0.05 else
           f"averages {abs(offset):.2f} °C {'warmer' if offset > 0 else 'cooler'} "
           f"than CPC&rsquo;s")
    return words + f" On {weeks_words} both carry, the days&rsquo; Nino-3.4 {how}."


def nino_card(days, weeks, revision=None) -> str:
    """The four Nino boxes day by day, with CPC's weekly Nino-3.4 beside them.

    The classification runs on CPC's weekly index, out some days after the
    week it means, and the official index on three months of it. These are
    the same four boxes from OISST's daily analysis, on the Pacific map's own
    cells: the final analysis's last ninety days, then the preliminary
    analysis's days since, a day or two behind. A turn shows here before the
    weekly index can show it, and the preliminary days are shaded because the
    final revises them; ``revision``, what the final changed on the days both
    carry, says by about how much.
    """
    if len(days) < 2:
        return ""
    dates = [date.fromisoformat(item.day) for item in days]
    by_day = dict(zip(dates, days))
    values = {day: item.means for day, item in by_day.items()}
    shown = [week for week in weeks if dates[0] <= week.week_ending <= dates[-1]]
    plot = _plot(values, NINO, frozenset(day for day, item in by_day.items() if item.preliminary),
                 dots=tuple((week.week_ending, week.nino34_anom) for week in shown),
                 notes={week.week_ending: [f"CPC week {week.nino34_anom:+.2f}"]
                        for week in shown})

    prelims = any(item.preliminary for item in days)
    latest = _latest_words(values, dates[-1], NINO, "Nino-3.4")
    against = _cpc_words(by_day, shown)
    revised = _revision_words(revision, NINO, "warmer", "cooler") if prelims else ""

    described = ("The area-weighted SST anomaly of each Nino box every day from OISST"
                 + (", the preliminary analysis shaded" if prelims else "")
                 + (", with CPC's traditional weekly Nino-3.4 as hollow dots" if shown else "")
                 + ".")
    keys = [(line.name, line.colour) for line in NINO.lines]
    week_key = ('<span class="key"><span class="swatch swatch-week"></span>'
                'CPC traditional weekly Nino-3.4</span>') if shown else ""
    return f"""<section class="card" id="nino-daily">
  <h2>The Nino boxes day by day</h2>
  <p class="caption">The four Nino boxes each day, on the Pacific map&rsquo;s own
    half-degree cells: {_analyses(days)}.{_behind(days[-1].day)}{latest} The
    anomalies are OISST&rsquo;s own, against its {OISST_BASE} climatology.{against}{revised}</p>
  {_legend(keys, week_key)}
  {plot.svg('Daily Nino box SST anomalies', described)}
  {table("Nino box SST anomalies by day, °C",
         ["Day", "Analysis", "Nino-3.4", "Nino-4", "Nino-3", "Nino-1+2"],
         _analysis_rows(days, NINO))}
</section>"""


# --- the Indian Ocean Dipole ------------------------------------------------------
def dipole_card(days, revision=None) -> str:
    """The Indian Ocean Dipole day by day: the Dipole Mode Index and its poles.

    The Bureau of Meteorology judges the dipole on a weekly index, the
    difference between the SST anomalies of a western pole and an eastern
    one. These are the same two poles from OISST's daily analyses, on
    half-degree cells as the Nino boxes are: the final analysis's last ninety
    days, then the preliminary analysis's days since, a day or two behind and
    shaded because the final revises them; ``revision``, what the final
    changed on the days both carry, says by about how much.
    """
    if len(days) < 2:
        return ""
    dates = [date.fromisoformat(item.day) for item in days]
    values = {day: item.means for day, item in zip(dates, days)}
    preliminary = frozenset(day for day, item in zip(dates, days) if item.preliminary)
    plot = _plot(values, DIPOLE, preliminary)
    latest = _latest_words(values, dates[-1], DIPOLE, "The DMI")
    revised = (_revision_words(revision, DIPOLE, "higher", "lower", DIPOLE_NAMES)
               if preliminary else "")
    described = ("The Dipole Mode Index and the SST anomaly of each of its poles every day "
                 "from OISST" + (", the preliminary analysis shaded" if preliminary else "") + ".")
    keys = [(line.name, line.colour) for line in DIPOLE.lines]
    return f"""<section class="card" id="iod-daily">
  <h2>The Indian Ocean Dipole day by day</h2>
  <p class="caption">The Dipole Mode Index each day, the SST anomaly of the
    west pole (50&ndash;70E, 10S&ndash;10N) less that of the east pole
    (90&ndash;110E, 10S&ndash;0), each area-weighted on half-degree cells:
    {_analyses(days)}.{_behind(days[-1].day)}{latest} The Bureau of
    Meteorology counts a DMI above +0.4 °C as a positive IOD value and one
    below -0.4 °C as a negative one, and eight weeks of either as an event.
    The anomalies are OISST&rsquo;s own, against its {OISST_BASE} climatology:
    a warming common to both poles cancels in their difference, but
    a difference in their warming does not, so the DMI here can
    run apart from the Bureau&rsquo;s own, whose thresholds these are. IOD
    events typically develop from about May, peak from August to October and
    break down when the Australian monsoon arrives at the end of the southern
    spring, so a value past a threshold from December to April seldom marks
    one.{revised}</p>
  {_legend(keys)}
  {plot.svg('Daily Indian Ocean Dipole', described)}
  {table("The Dipole Mode Index and its poles by day, °C",
         ["Day", "Analysis", "DMI", "West pole", "East pole"], _analysis_rows(days, DIPOLE))}
</section>"""


# --- the SOI ----------------------------------------------------------------------
def soi_days(days) -> list:
    """The days of LongPaddock's file the SOI card draws: those within
    SOI_DAYS of its latest, in order."""
    if not days:
        return []
    since = (date.fromisoformat(days[-1].day) - timedelta(days=SOI_DAYS - 1)).isoformat()
    return [item for item in days if item.day >= since]


def _soi_values(item) -> dict[str, float]:
    """A day's SOI values by their lines' keys: the day's own, and each mean
    whose window held days enough for it."""
    return {line.key: getattr(item, line.key) for line in SOI.lines
            if getattr(item, line.key) is not None}


def _soi_latest(item) -> str:
    """The latest day's means, or the day's own SOI when its 30-day window
    held too few days for one."""
    when = _day_label(date.fromisoformat(item.day))
    if item.soi30 is None:
        return f" The day&rsquo;s SOI is <strong>{SOI.fmt(item.soi)}</strong> on {when}."
    ninety = f", the 90-day {SOI.fmt(item.soi90)}" if item.soi90 is not None else ""
    return f" The 30-day SOI is <strong>{SOI.fmt(item.soi30)}</strong> on {when}{ninety}."


def soi_card(days) -> str:
    """The SOI day by day, on the Bureau of Meteorology's definition: its 30-
    and 90-day means over each day's own value, faint, for the last SOI_DAYS
    days of LongPaddock's file.

    CPC's monthly SOI, on the coupling card, comes out after the month it
    means. LongPaddock works the SOI out every day from the day's pressures
    at Tahiti and Darwin, and its means move a day at a time, so the
    atmosphere's half of a coupled event shows in them weeks before the
    month's index can show it. A day the file lacks breaks the day's own
    line, and not the means', whose windows allow for it.
    """
    days = soi_days(days)
    if len(days) < 2:
        return ""
    dates = [date.fromisoformat(item.day) for item in days]
    values = {day: _soi_values(item) for day, item in zip(dates, days)}
    notes = {day: [f"Tahiti {item.tahiti:.1f} hPa", f"Darwin {item.darwin:.1f} hPa"]
             for day, item in zip(dates, days) if item.tahiti is not None}
    plot = _plot(values, SOI, notes=notes)
    first, last = days[0].day, days[-1].day
    behind, latest = _behind(last), _soi_latest(days[-1])
    described = "The 30- and 90-day SOI every day, over each day's own SOI drawn faint."
    keys = [(line.name, line.colour) for line in SOI.lines]
    rows = [[item.day]
            + [SOI.fmt(values[day][line.key]) if line.key in values[day] else "—"
               for line in SOI.lines]
            + [f"{pressure:.1f}" if pressure is not None else "—"
               for pressure in (item.tahiti, item.darwin)]
            for day, item in zip(reversed(dates), reversed(days))]
    return f"""<section class="card" id="soi-daily">
  <h2>The Southern Oscillation Index day by day</h2>
  <p class="caption">The Southern Oscillation Index day by day
    on the Bureau of Meteorology&rsquo;s definition, Troup&rsquo;s, as the
    Queensland Government&rsquo;s LongPaddock works it out from each
    day&rsquo;s Tahiti and Darwin pressures, {first} to {last}. The
    Bureau&rsquo;s own daily SOI data have been unavailable since January 2025,
    when Météo-France changed its Tahiti data service.{behind}{latest}
    The 30- and 90-day SOI are the means of the days&rsquo; values, as
    LongPaddock&rsquo;s own are, none where a window lacks more than five days
    or more than three in a row; sustained values below -7 are El Nino-like
    and above +7 La Nina-like. Each day&rsquo;s SOI is
    ten times the standardised Tahiti less Darwin pressure difference, against
    1933&ndash;1992, so CPC&rsquo;s monthly SOI, a standard score, runs at
    about a tenth of the 30-day SOI; and the SOI keeps its own sign here,
    El Nino negative, where the coupling card signs every index El Nino-positive.</p>
  {_legend(keys)}
  {plot.svg('Daily Southern Oscillation Index', described)}
  {table("LongPaddock's SOI and the day's pressures, by day",
         ["Day", "30-day SOI", "90-day SOI", "Daily SOI", "Tahiti, hPa", "Darwin, hPa"], rows)}
</section>"""


# --- westerly wind events -----------------------------------------------------------
def _region_words(key: str) -> str:
    """A region as a caption calls it: "the central region (155E-180, 5S-5N)"."""
    region = REGIONS_BY_KEY[key]
    return f"the {region.name} region ({region.span.replace('-', '&ndash;')})"


def _days_words(days: float) -> str:
    return f"{days:g} day{'' if days == 1 else 's'}"


def _under_way_words(event: Event) -> str:
    """An event under way as the caption says it: its region, its days above
    the threshold since it began, and its smoothed peak; at least those days,
    since before its first analysis, when it began before the window; and
    when it has run longer than any of Harrison and Vecchi's, a mark saying
    so, which ``_wind_now`` explains once."""
    before = event.from_start
    sustained = " (longer than any in Harrison and Vecchi&rsquo;s list)" if event.sustained else ""
    return (f"{_region_words(event.region)}: <strong>{'at least ' if before else ''}"
            f"{_days_words(event.days)}</strong> above {THRESHOLD:+g} m/s since "
            f"{'before ' if before else ''}{_day_label(event.first.date())}, peaking at "
            f"{event.peak:+.1f} m/s on {_day_label(event.centre.date())}{sustained}")


def _wind_now(winds: Winds) -> str:
    """What is under way, or else the latest event, or that there is none; and
    the runs still building."""
    above = f"above {THRESHOLD:+g} m/s"
    if winds.under_way:
        each = [_under_way_words(event) for event in winds.under_way]
        words = (" A westerly wind event is under way in " if len(each) == 1
                 else " Westerly wind events are under way in ") + "; and in ".join(each) + "."
        if any(event.sustained for event in winds.under_way):
            words += (f" Harrison and Vecchi&rsquo;s {HV97_EVENTS} events of 1986&ndash;1995 "
                      f"lasted {HV97_LONGEST:g} days at most: a run longer is a sustained "
                      "westerly anomaly more than a burst.")
    elif winds.events:
        latest = max(winds.events, key=lambda event: event.last)
        words = (f" No event is under way. The latest, in {_region_words(latest.region)}, ran "
                 f"{_days_words(latest.days)} from {_day_label(latest.first.date())} to "
                 f"{_day_label(latest.last.date())}, peaking at {latest.peak:+.1f} m/s.")
    else:
        words = f" No westerly wind event in these {len(winds.daily)} days."
    if winds.building:
        words += " Building, not yet three days: " + "; ".join(
            f"{_region_words(run.region)}, {_days_words(run.days)} {above}, "
            f"latest {run.latest:+.1f} m/s" for run in winds.building) + "."
    return words


def _lon_words(lon: float) -> str:
    if lon == 180.0:
        return "180"
    return f"{lon:.1f}E" if lon < 180.0 else f"{360.0 - lon:.1f}W"


def counts_as(event: Event) -> str:
    """What an event counts as, for a table: "itself", or "itself (overlaps
    W)"; or the stronger it overlaps, "C", or "C (also overlaps N)"."""
    others = ", ".join(key for key in event.overlaps if key != event.counted_as)
    if event.counted_as == event.region:
        return f"itself (overlaps {others})" if others else "itself"
    return event.counted_as + (f" (also overlaps {others})" if others else "")


def _wind_rows(winds: Winds) -> list[list[str]]:
    """The events, the latest to end first: each one's type, region and run,
    its centre, peak and point peak, its wind measure, what it counts as, and
    whether it is under way or began before the window."""
    rows = []
    for event in winds.latest_first:
        region = REGIONS_BY_KEY[event.region]
        lat, lon = event.point
        note = "; ".join(words for words in (
            "under way" if event.ongoing else "",
            f"began before {_day_label(winds.first)}" if event.from_start else "") if words)
        rows.append([
            # A table's cells are escaped: the dash itself, not its entity.
            event.region, f"{region.name}, {region.span.replace('-', '–')}",
            f"{event.first:%Y-%m-%d %HZ}", f"{event.last:%Y-%m-%d %HZ}", f"{event.days:g}",
            f"{event.centre:%Y-%m-%d %HZ}", f"{event.peak:+.1f}", f"{event.point_peak:+.1f}",
            f"{abs(lat):.1f}{'N' if lat >= 0 else 'S'} {_lon_words(lon)}",
            f"{event.measure / 1e6:.2f}", counts_as(event), note or "—",
        ])
    return rows


def wind_card(winds: Winds | None) -> str:
    """Westerly wind events day by day, as Harrison and Vecchi (1997) defined
    them, from CCMP's near-real-time winds: the 5S-5N anomaly's Hovmoller with
    each equatorial event outlined, the equatorial regions' smoothed
    anomalies with each of their events shaded, and every event of the
    window in all eight regions.

    The coupling card's 850 hPa trades are CPC's monthly indices, and the
    report's westerly forcing counts months of them; these are the bursts
    themselves, days long, a day or two behind.
    """
    if winds is None or len(winds.daily) < 2:
        return ""
    names = {line.key: line.name for line in WINDS.lines}
    outlines, bands, notes = [], [], {}
    for event in winds.events:
        if event.region not in EQUATORIAL:
            continue
        region = REGIONS_BY_KEY[event.region]
        first, last = event.first.date(), event.last.date()
        outlines.append((region.west, region.east, (first - winds.first).days,
                         (last - winds.first).days, event.region))
        bands.append((first, last, event.region))
        for offset in range((last - first).days + 1):
            notes.setdefault(first + timedelta(days=offset), []).append(
                f"{names[event.region]} event")
    panel = hovmoller(
        winds.hovmoller, "Equatorial 10 m zonal wind anomaly, time by longitude",
        "Hovmoller diagram of the 10 m zonal wind anomaly from 5S to 5N, a row a day, time "
        "running downward and longitude across, westerly warm, with each equatorial westerly "
        "wind event outlined over its region and its days.",
        fmt="{:+.1f}", units="m/s", ramp_caption="zonal wind anomaly",
        outlines=tuple(outlines), months=EVERY_MONTH,
        extra=('<p class="subcaption">CCMP v2.1 near real time, 5S&ndash;5N cosine-weighted, '
               'each row the mean of the day&rsquo;s analyses; outlined and lettered, the '
               'west, central and east regions&rsquo; events.</p>'))
    values = {day: {key: value for key, value in day_values.items() if key in EQUATORIAL}
              for day, day_values in winds.daily.items()}
    plot = _plot(values, WINDS, notes=notes, bands=tuple(bands))
    described = ("The smoothed 10 m zonal wind anomaly of the west, central and east regions "
                 "each day, with each region's westerly wind events as bars in its colour along "
                 "the top.")
    product = (
        "Remote Sensing Systems&rsquo; Cross-Calibrated Multi-Platform (CCMP) 10 m winds, "
        "version 2.1 near real time, from NOAA PIFSC&rsquo;s OceanWatch: an analysis of "
        "satellite radiometer and scatterometer winds over NCEP&rsquo;s GFS, here twice a day "
        f"on cells 2.25 degrees apart, {winds.first} to {winds.last}.")
    definition = (
        " An event, as Harrison and Vecchi (1997) define one, is three days or more in which "
        "the 10 m zonal wind anomaly over one of their eight regions, cosine-weighted and "
        "smoothed by a three-point triangle filter on analyses 12 hours apart (half power at "
        f"2.75 days), stays above {THRESHOLD:+g} m/s; an analysis is smoothed when the next "
        "one comes. Its centre is its largest smoothed value, its peak that value, its point "
        "peak the strongest cell in the region then, and its wind measure the time integral "
        "of its smoothed anomaly. Events in bordering regions centred within three days "
        "overlap, and count as the stronger. Against a monthly climatology an El Nino&rsquo;s "
        "own westerly anomaly counts as well, so in a strong event the central and eastern "
        "regions&rsquo; runs can last weeks, the bursts within them showing in the chart and "
        "the Hovmoller.")
    # Measured on 15 October 2026: the near-real-time product against version
    # 2.0 at 72 analysis times both carry, and against TAO's daily winds, TAO
    # lifted from 4 m to 10 m by a neutral log profile (z0 2e-5 to 2e-4 m).
    base = (
        " The anomalies are against CCMP version 2.0&rsquo;s monthly means for "
        f"{windclim.BASE.replace('-', '&ndash;')} on the same cells, interpolated between "
        "the months&rsquo; middles. At 72 analysis times in 2016&ndash;2019 that both "
        "versions carry, the near-real-time product&rsquo;s regional means differ from "
        "version 2.0&rsquo;s by 0.20 m/s at most on average (in the north-west; 0.12 m/s at "
        "most in the equatorial regions), and by 0.19&ndash;0.51 m/s rms analysis by "
        "analysis. Against TAO&rsquo;s daily winds at its seven reporting equatorial "
        "moorings, 165E to 95W, June to September 2026, its daily zonal wind correlates at "
        "0.88&ndash;0.95 mooring by mooring. At 165E and 170W, where the wind was westerly "
        "on average, it ran 0.7 m/s less westerly than TAO&rsquo;s; from 155W to 95W, "
        "0.2 m/s more easterly. TAO measures at 4 m and CCMP is for 10 m, where a neutral "
        "log profile has the wind about 8% stronger: that leaves the eastern difference "
        "within 0.15 m/s and widens the western one to 0.9 m/s, so events&rsquo; peaks "
        "there may run low.")
    months = (
        " The coupling card&rsquo;s 850 hPa trades are CPC&rsquo;s monthly indices, and the "
        "report&rsquo;s westerly forcing counts months of the western one strongly westerly; "
        "these are the surface bursts themselves, days long, that force the downwelling "
        "Kelvin waves the Hovmoller card follows east.")
    rows = _wind_rows(winds)
    events = table(
        f"westerly wind events in these {len(winds.daily)} days, latest first",
        ["Type", "Region", "First", "Last", "Days", "Centre", "Peak (smoothed), m/s",
         "Point peak, m/s", "Where", "Wind measure, 10⁶ m", "Counts as", "Note"],
        rows) if rows else ""
    keys = [(line.name, line.colour) for line in WINDS.lines]
    return f"""<section class="card" id="wind-events">
  <h2>Westerly wind events day by day</h2>
  <p class="caption">{product}{_behind(winds.last.isoformat())}{_wind_now(winds)}</p>
  <p class="caption">{definition.lstrip()}{base}{months}</p>
  <div class="hovsolo">{panel}</div>
  {_legend(keys)}
  {plot.svg('Daily equatorial zonal wind anomalies', described)}
  {events}
  {field_table(winds.hovmoller, "equatorial 10 m zonal wind anomaly, m/s", fmt="{:+.1f}",
               max_rows=18, max_cols=12)}
</section>"""
