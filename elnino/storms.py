"""The cyclone panels: live tracks, forecast spread, and seasonal verification.

``cyclones`` computes; this draws. The split is the same one every other
visual tier in this package uses, and it exists because the numbers have to be
testable without rendering anything and the rendering has to be replaceable
without touching the numbers.

Two panels, because a reader has two different questions:

  tracks    where is it, where is it going, how sure is anyone. A map, with
            the best track behind each storm, the official forecast ahead of
            it, and every ensemble member drawn underneath so the width of the
            forecast is visible rather than asserted.
  season    is this basin behaving the way an El Nino says it should. Three
            bars per basin - what happened, what normally happens by this
            date, and what happens in El Nino years by this date - which is
            the whole teleconnection argument in one picture.

On colour. A storm's hue identifies the storm and nothing else: it does not
encode intensity, and it does not change when another storm forms or
dissipates. Intensity is carried by marker size and by a direct label, which
survives both colour-vision deficiency and a monochrome print. The ensemble
members are deliberately not categorical - they are one undifferentiated grey
cloud, because the identity of member seventeen is not information.
"""

from __future__ import annotations

import math
from dataclasses import replace as dc_replace

from . import alerts, cyclones, stormfury
from .coastline import segments
from .svg import Plot, _hit, _legend, esc, nice_ticks, table
from .svg import boxes_clear as _clear, label_box as _label_box

# Fixed hue order, assigned to storms in ATCF order and never cycled. A fourth
# simultaneous storm in one basin is rare; a ninth is not a thing that happens,
# so there is no "Other" bucket to fall into here - the list simply runs out
# and any further storm draws in the neutral ink, still labelled.
STORM_HUES = ("var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)", "var(--s5)")
NEUTRAL = "var(--ink2)"

# Marker radius by Saffir-Simpson category. Eight pixels is the floor for a
# hit target you can actually hit; the top of the ramp is large enough that a
# Category 5 is unmistakable at a glance without a legend lookup.
RADIUS = {0: 4.5, 1: 6.0, 2: 7.0, 3: 8.0, 4: 9.5, 5: 11.0}

MAP_W = 940
PAD = (18, 116, 34, 44)


def _beside(lon: float, middle: float) -> float:
    """A longitude taken within 180 degrees of ``middle``."""
    return middle + (lon - middle + 180.0) % 360.0 - 180.0


def _framed(storms) -> list:
    """The storms with every longitude brought beside the map's middle.

    ATCF gives longitudes from 180 W to 180 E, so a track or a member that
    crosses the date line jumps by 360 degrees. On 29 September 2026 Nolo's
    ensemble ran from 179.9 W to 179.3 E, and the map, drawn from the
    smallest longitude to the largest, came out 430 degrees wide: every storm
    a dot and no town's name finding room. The middle is the circular mean
    of where the storms are now; the coastline is re-wrapped onto the same
    window.
    """
    now = [s.latest for s in storms if s.latest is not None]
    if not now:
        return list(storms)
    middle = math.degrees(math.atan2(sum(math.sin(math.radians(f.lon)) for f in now),
                                     sum(math.cos(math.radians(f.lon)) for f in now)))

    def moved(fixes):
        return tuple(dc_replace(f, lon=_beside(f.lon, middle)) for f in fixes)

    return [dc_replace(s, track=moved(s.track), forecast=moved(s.forecast),
                       ensemble={k: moved(v) for k, v in s.ensemble.items()},
                       guidance={k: moved(v) for k, v in s.guidance.items()})
            for s in storms]


def _bounds(storms) -> tuple[float, float, float, float]:
    """A window that holds every track, with room for the labels beside them."""
    lons: list[float] = []
    lats: list[float] = []
    for storm in storms:
        for fix in list(storm.track) + list(storm.forecast):
            lons.append(fix.lon)
            lats.append(fix.lat)
        for track in storm.scatter.values():
            for fix in track:
                if fix.tau <= cyclones.HORIZON:
                    lons.append(fix.lon)
                    lats.append(fix.lat)
    if not lons:
        return -180.0, -80.0, 0.0, 45.0
    lon_min, lon_max = min(lons), max(lons)
    lat_min, lat_max = min(lats), max(lats)
    # A minimum span, so a storm that has barely moved does not get drawn at a
    # zoom where the coastline is three vertices and the map means nothing.
    pad_x = max(6.0, (lon_max - lon_min) * 0.10)
    pad_y = max(5.0, (lat_max - lat_min) * 0.16)
    return (lon_min - pad_x, lon_max + pad_x,
            max(-60.0, lat_min - pad_y), min(70.0, lat_max + pad_y))


# The track map's height in plot units, between these: a window much wider
# than it is tall gets more latitude rather than a strip of a map, and one
# much taller more longitude rather than a column.
MAP_PLOT_H = (300.0, 560.0)


def _fit(lon_min: float, lon_max: float, lat_min: float, lat_max: float,
         plot_w: float) -> tuple[float, float, float, float, float]:
    """The window grown to a plate carree frame ``plot_w`` wide, and its height.

    A degree of latitude is drawn as long as a degree of longitude. The
    window used to be stretched to a fixed frame: on 24 September 2026 the
    storms from Hawaii to the mid-Atlantic came out 2.17 times too tall, and
    Polo's west-north-west track read as north-west.
    """
    low, high = MAP_PLOT_H
    lon_span, lat_span = lon_max - lon_min, lat_max - lat_min
    plot_h = plot_w * lat_span / lon_span
    if plot_h < low:
        grow = (low * lon_span / plot_w - lat_span) / 2
        lat_min, lat_max = lat_min - grow, lat_max + grow
        # Keep inside the latitudes the map is ever drawn to.
        shift = max(0.0, -60.0 - lat_min) - max(0.0, lat_max - 70.0)
        lat_min, lat_max = lat_min + shift, lat_max + shift
        plot_h = low
    elif plot_h > high:
        grow = (plot_w * lat_span / high - lon_span) / 2
        lon_min, lon_max = lon_min - grow, lon_max + grow
        plot_h = high
    return lon_min, lon_max, lat_min, lat_max, plot_h


def _path(plot: Plot, fixes) -> str:
    return "M" + " L".join(f"{plot.sx(f.lon):.1f} {plot.sy(f.lat):.1f}"
                           for f in fixes)


def _coast(plot: Plot, lon_min: float, lon_max: float,
           lat_min: float, lat_max: float) -> None:
    paths = []
    for line in segments(lon_min, lon_max):
        points = [(plot.sx(lon), plot.sy(lat)) for lon, lat in line
                  if lon_min - 30 <= lon <= lon_max + 30
                  and lat_min - 20 <= lat <= lat_max + 20]
        if len(points) > 1:
            paths.append("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in points))
    if paths:
        plot.add(
            f'<path d="{" ".join(paths)}" fill="none" stroke="var(--ink)" '
            f'stroke-width="0.9" opacity="0.5" stroke-linejoin="round" '
            f'clip-path="url(#tcclip)"/>'
        )


def _lon_label(value: float) -> str:
    """A graticule longitude: folded into -180..180, so a window that runs
    past the date line reads 170E rather than 190W, and 180 and 0 without a
    hemisphere, because they have none."""
    folded = (value + 180.0) % 360.0 - 180.0
    if abs(folded) in (0.0, 180.0):
        return f"{abs(folded):.0f}&#176;"
    return f"{abs(folded):.0f}&#176;{'W' if folded < 0 else 'E'}"


def _lat_label(value: float) -> str:
    if value == 0.0:
        return "EQ"
    return f"{abs(value):.0f}&#176;{'S' if value < 0 else 'N'}"


def _graticule(plot: Plot, lon_min: float, lon_max: float,
               lat_min: float, lat_max: float) -> None:
    step = 10.0 if lon_max - lon_min < 70 else 20.0
    value = lon_min - (lon_min % step)
    while value <= lon_max:
        if lon_min <= value <= lon_max:
            x = plot.sx(value)
            plot.add(f'<line x1="{x:.1f}" y1="{plot.top}" x2="{x:.1f}" '
                     f'y2="{plot.top + plot.plot_h:.1f}" stroke="var(--grid)" '
                     f'stroke-width="1"/>')
            plot.add(f'<text x="{x:.1f}" y="{plot.top + plot.plot_h + 16:.1f}" '
                     f'text-anchor="middle" class="tick">'
                     f'{_lon_label(value)}</text>')
        value += step
    value = lat_min - (lat_min % step)
    while value <= lat_max:
        if lat_min <= value <= lat_max:
            y = plot.sy(value)
            plot.add(f'<line x1="{plot.left}" y1="{y:.1f}" '
                     f'x2="{plot.left + plot.plot_w:.1f}" y2="{y:.1f}" '
                     f'stroke="var(--grid)" stroke-width="1"/>')
            plot.add(f'<text x="{plot.left - 8:.1f}" y="{y + 4:.1f}" '
                     f'text-anchor="end" class="tick">'
                     f'{_lat_label(value)}</text>')
        value += step


# A label's box is estimated, because the SVG is written before any browser
# has measured it: 0.6 em a character is wider than the system sans at these
# sizes, so a label that clears by this estimate clears on screen.
def _spots(x: float, y: float) -> tuple:
    """Where a place name may go around its dot, in order of preference.

    Next to the dot first - below, above, right, left - then a step further
    out in the same four directions, which is what clears a forecast marker
    sitting on the town itself.
    """
    return ((x, y + 15, "middle"), (x, y - 7, "middle"),
            (x + 7, y + 4, "start"), (x - 7, y + 4, "end"),
            (x, y + 27, "middle"), (x, y - 19, "middle"),
            (x + 19, y + 4, "start"), (x - 19, y + 4, "end"))


def _storm_spots(x: float, y: float) -> tuple:
    """Where a storm's name and intensity may go around its eye, in order.

    To the right first, where they have always gone; then left, below and
    above, for when another storm's labels or markers are there already.
    Below and above clear the largest eye, a Category 5's eleven units.
    """
    return (((x + 14, y - 12), (x + 14, y + 2), "start"),
            ((x - 14, y - 12), (x - 14, y + 2), "end"),
            ((x, y + 26), (x, y + 40), "middle"),
            ((x, y - 30), (x, y - 16), "middle"))


def _place_storm_labels(plot: Plot, live, taken: list, marks: list) -> dict:
    """Each storm's name and intensity, at the first spot that clears.

    Storms are labelled in order, each at the first of ``_storm_spots`` that
    stays on the canvas and clears every label already down, preferring one
    off every marker. On 25 September 2026 Odalys's labels, always to the
    right of its eye, ran over Polo's eye and Polo's own labels 16 degrees
    to the east. With no clear spot a storm keeps the first one, as before.
    Returns the chosen spot by the storm's position in ``live``; the boxes
    go into ``taken``.
    """
    placed = {}
    for index, storm in enumerate(live):
        now = storm.latest
        if now is None:
            continue
        x, y = plot.sx(now.lon), plot.sy(now.lat)
        wind = f"{now.wind or 0} kt · {now.short}"
        spots = []
        for title_at, wind_at, anchor in _storm_spots(x, y):
            boxes = (_label_box(*title_at, storm.title, 12.0, anchor),
                     _label_box(*wind_at, wind, 11.0, anchor))
            if all(0 <= box[0] and box[2] <= plot.w and 0 <= box[1]
                   and box[3] <= plot.h and _clear(box, taken) for box in boxes):
                spots.append((title_at, wind_at, anchor, boxes))
        spots.sort(key=lambda spot: not all(_clear(box, marks) for box in spot[3]))
        if not spots:
            title_at, wind_at, anchor = _storm_spots(x, y)[0]
            spots.append((title_at, wind_at, anchor,
                          (_label_box(*title_at, storm.title, 12.0, anchor),
                           _label_box(*wind_at, wind, 11.0, anchor))))
        placed[index] = spots[0]
        taken.extend(spots[0][3])
    return placed


def _places(plot: Plot, lon_min: float, lon_max: float,
            lat_min: float, lat_max: float, threatened: dict,
            taken: list, marks: list) -> list[str]:
    """Named coastal targets inside the window, the threatened ones marked.

    Without these the map is a line over an outline and a reader has to know
    the coastline of western Mexico by sight to make anything of it.

    The dots are drawn here, under the tracks; the names are returned, to go
    on top of them. Threatened places are named nearest approach first, each
    in the first of four positions around its dot - below, above, right,
    left - that clears every label already down, the storms' own included,
    and every storm marker; failing that, the first that clears the labels,
    where the halo keeps it legible over a marker. One with no clear position
    keeps its marked dot and its hover, and the table under the map lists
    it. On 24 September 2026 Manzanillo, Lazaro Cardenas, Zihuatanejo and
    Socorro Island were written over one another and over Polo's name, and
    Guaymas, La Paz and Los Cabos under Polo's forecast markers.
    """
    hot = []
    for place in cyclones.LANDFALL:
        lon = _beside(place.lon, (lon_min + lon_max) / 2.0)
        if not (lon_min <= lon <= lon_max and lat_min <= place.lat <= lat_max):
            continue
        x, y = plot.sx(lon), plot.sy(place.lat)
        marked = place.name in threatened
        plot.add(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{3.2 if marked else 2.2}" '
            f'fill="{"var(--critical)" if marked else "var(--muted)"}" '
            f'stroke="var(--surface)" stroke-width="1.5"/>'
        )
        if marked:
            hot.append((threatened[place.name], place, x, y))
    right, bottom = plot.left + plot.plot_w, plot.top + plot.plot_h
    names = []
    for gap, place, x, y in sorted(hot, key=lambda item: item[0]):
        plot.add(_hit(x, y, f"{place.name}, {place.country}",
                      f"closest approach {gap:.0f} km"))
        spots = []
        for lx, ly, anchor in _spots(x, y):
            box = _label_box(lx, ly, place.name, 11.0, anchor)
            if (plot.left <= box[0] and box[2] <= right
                    and plot.top <= box[1] and box[3] <= bottom
                    and _clear(box, taken)):
                spots.append((lx, ly, anchor, box))
        spots.sort(key=lambda spot: not _clear(spot[3], marks))
        if spots:
            lx, ly, anchor, box = spots[0]
            taken.append(box)
            # A name pushed away from its dot is tied back to it, or a
            # cluster of towns reads as whichever names sit nearest.
            nx, ny = min(max(x, box[0]), box[2]), min(max(y, box[1]), box[3])
            reach = math.hypot(nx - x, ny - y)
            if reach > 6.0:
                ux, uy = (nx - x) / reach, (ny - y) / reach
                names.append(
                    f'<line class="leader" x1="{x + 3.5 * ux:.1f}" '
                    f'y1="{y + 3.5 * uy:.1f}" x2="{nx - 1.5 * ux:.1f}" '
                    f'y2="{ny - 1.5 * uy:.1f}" stroke="var(--muted)" '
                    f'stroke-width="1"/>'
                )
            names.append(
                f'<text x="{lx:.1f}" y="{ly:.1f}" text-anchor="{anchor}" '
                f'class="tick placename halo">{esc(place.name)}</text>'
            )
    return names


def _marked(storm) -> list:
    """The fixes that get a marker on the track map.

    Every sixth-hourly analysis at hurricane strength, plus every forecast
    point; the weaker history is a line only, because a track of forty
    identical small dots is a dotted line.
    """
    history = [f for f in storm.track if f.tau == 0]
    ahead = [f for f in storm.forecast if f.tau <= cyclones.HORIZON]
    return [f for f in history if f.category >= 1] + ahead


def track_map(storms) -> str:
    """Every live storm on one map: past, forecast, and the spread around it.

    The map is drawn for the Atlantic and the eastern Pacific. JTWC's storms
    are left off it: a plate carree window from Hawaii to a typhoon off
    Luzon runs the long way round, and shrinks every storm on it to a dot.
    """
    live = _framed([s for s in storms if getattr(s, "centre", "NHC") != "JTWC"])
    top, right, bottom, left = PAD
    lon_min, lon_max, lat_min, lat_max, plot_h = _fit(
        *_bounds(live), MAP_W - left - right)
    plot = Plot(MAP_W, round(plot_h) + top + bottom, PAD)
    plot.domain(lon_min, lon_max, lat_min, lat_max)
    plot.add(
        f'<defs><clipPath id="tcclip"><rect x="{plot.left}" y="{plot.top}" '
        f'width="{plot.plot_w:.1f}" height="{plot.plot_h:.1f}"/></clipPath></defs>'
    )
    plot.add(
        f'<rect x="{plot.left}" y="{plot.top}" width="{plot.plot_w:.1f}" '
        f'height="{plot.plot_h:.1f}" fill="var(--plane)"/>'
    )
    _graticule(plot, lon_min, lon_max, lat_min, lat_max)
    _coast(plot, lon_min, lon_max, lat_min, lat_max)

    threatened: dict[str, float] = {}
    for storm in live:
        for gap, fix, place in storm.threats(350.0):
            if (fix.wind or 0) >= 34:
                threatened[place.name] = min(gap, threatened.get(place.name, gap))
    # The storms' names go down first, so a place gives way to them, and
    # a place name keeps off the storms' markers where it can.
    taken, marks = [], []
    for storm in live:
        for fix in _marked(storm):
            x, y = plot.sx(fix.lon), plot.sy(fix.lat)
            radius = RADIUS.get(fix.category, 4.5) + 1.0
            marks.append((x - radius, y - radius, x + radius, y + radius))
    placed = _place_storm_labels(plot, live, taken, marks)
    names = _places(plot, lon_min, lon_max, lat_min, lat_max, threatened,
                    taken, marks)

    # --- the spread, underneath everything, in one undifferentiated grey
    for storm in live:
        for track in storm.scatter.values():
            inside = [f for f in track if f.tau <= cyclones.HORIZON]
            if len(inside) > 1:
                plot.add(
                    f'<path d="{_path(plot, inside)}" fill="none" '
                    f'stroke="var(--muted)" stroke-width="1" opacity="0.30" '
                    f'stroke-linecap="round" clip-path="url(#tcclip)"/>'
                )

    for index, storm in enumerate(live):
        hue = STORM_HUES[index] if index < len(STORM_HUES) else NEUTRAL
        history = [f for f in storm.track if f.tau == 0]
        if len(history) > 1:
            plot.add(
                f'<path d="{_path(plot, history)}" fill="none" stroke="{hue}" '
                f'stroke-width="2" stroke-linejoin="round" stroke-linecap="round" '
                f'clip-path="url(#tcclip)"/>'
            )
        now = storm.latest
        ahead = [f for f in storm.forecast if f.tau <= cyclones.HORIZON]
        if ahead and now is not None:
            plot.add(
                f'<path d="{_path(plot, [now] + ahead)}" fill="none" '
                f'stroke="{hue}" stroke-width="2" stroke-dasharray="7 5" '
                f'stroke-linecap="round" clip-path="url(#tcclip)"/>'
            )

        for fix in _marked(storm):
            x, y = plot.sx(fix.lon), plot.sy(fix.lat)
            if not (plot.left <= x <= plot.left + plot.plot_w
                    and plot.top <= y <= plot.top + plot.plot_h):
                continue
            radius = RADIUS.get(fix.category, 4.5)
            forecast = fix.tau > 0
            plot.add(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{radius:.1f}" '
                f'fill="{"var(--surface)" if forecast else hue}" stroke="{hue}" '
                f'stroke-width="2"/>'
            )
            when = f"+{fix.tau} h" if forecast else _clock(fix.stamp)
            plot.add(_hit(
                x, y, f"{storm.title} {when}",
                f"{fix.wind or 0} kt, {fix.label}",
                f"{_degrees(fix)}"
                + (f", {fix.pressure} mb" if fix.pressure else ""),
            ))

        if index in placed:
            # The name in text ink: the eye and the track beside it carry the
            # storm's colour, and a name painted in that colour loses contrast
            # against the surface in one theme or the other.
            (tx, ty), (wx, wy), anchor, _ = placed[index]
            plot.add(
                f'<text x="{tx:.1f}" y="{ty:.1f}" text-anchor="{anchor}" '
                f'class="endlabel halo">{esc(storm.title)}</text>'
            )
            plot.add(
                f'<text x="{wx:.1f}" y="{wy:.1f}" text-anchor="{anchor}" '
                f'class="tick halo">{now.wind or 0} kt &middot; '
                f'{esc(now.short)}</text>'
            )

    # Place names last, over every track, each with a halo of the map's
    # own ground.
    for name in names:
        plot.add(name)

    return plot.svg(
        "Live tropical cyclone tracks and forecasts",
        "Best track behind each storm, official forecast ahead of it as a "
        "dashed line, and every available ensemble member drawn in grey "
        "underneath to show the width of the forecast.",
    )


def _clock(stamp: str) -> str:
    return (f"{stamp[6:8]} {_MONTH[int(stamp[4:6])]} {stamp[8:10]}Z"
            if len(stamp) == 10 else stamp)


_MONTH = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
          "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _degrees(fix) -> str:
    """A fix's position in words. A framed longitude can lie past 180, so it
    is folded back, and the date line and the meridian, as written to the
    tenth, have no hemisphere."""
    lon = round((fix.lon + 180.0) % 360.0 - 180.0, 1) + 0.0
    east = "" if abs(lon) in (0.0, 180.0) else "W" if lon < 0 else "E"
    return (f"{abs(fix.lat):.1f}&#176;{'N' if fix.lat >= 0 else 'S'} "
            f"{abs(lon):.1f}&#176;{east}")


# --------------------------------------------------------------------------
# the seasonal bars
# --------------------------------------------------------------------------
SERIES = (
    ("This season so far", "var(--s1)"),
    ("Normal by this date", "var(--s2)"),
    ("El Nino years by this date", "var(--s3)"),
)
BAR_W, ROW_H = 940, 74


def season_chart(state) -> str:
    """Observed against two climatologies, on one axis, per basin.

    One axis is not a stylistic choice here: the three bars are the same
    quantity measured three ways, and putting the observation on a second
    scale would let any basin be made to look like any answer.
    """
    rows = []
    for basin in ("AL", "EP"):
        season = state.basins.get(basin)
        if season is None:
            continue
        rows.append((season, [
            season.ace,
            season.normal_ace or 0.0,
            season.elnino_ace or 0.0,
        ]))
    if not rows:
        return ""
    peak = max(max(values) for _, values in rows) or 1.0
    height = 46 + len(rows) * ROW_H
    plot = Plot(BAR_W, height, (26, 150, 20, 186))
    plot.domain(0.0, peak * 1.06, 0.0, 1.0)

    ticks = nice_ticks(0.0, peak * 1.06, 5)
    for tick in ticks:
        x = plot.sx(tick)
        plot.add(f'<line x1="{x:.1f}" y1="{plot.top - 6}" x2="{x:.1f}" '
                 f'y2="{plot.top + plot.plot_h:.1f}" stroke="var(--grid)" '
                 f'stroke-width="1"/>')
        plot.add(f'<text x="{x:.1f}" y="{plot.top - 12}" text-anchor="middle" '
                 f'class="tick">{tick:.0f}</text>')
    plot.add(f'<text x="{plot.left}" y="{plot.top - 12}" text-anchor="end" '
             f'class="axistitle">ACE</text>')

    bar_h = 14
    for index, (season, values) in enumerate(rows):
        base = plot.top + index * ROW_H + 8
        plot.add(
            f'<text x="{plot.left - 12}" y="{base + 20}" text-anchor="end" '
            f'class="rowlabel" style="font-weight:600">{esc(season.name)}</text>'
        )
        ratio = season.ace_ratio
        if ratio is not None:
            plot.add(
                f'<text x="{plot.left - 12}" y="{base + 38}" text-anchor="end" '
                f'class="tick">{ratio:.2f}&#215; normal for the date</text>'
            )
        for slot, (value, (name, hue)) in enumerate(zip(values, SERIES)):
            y = base + slot * (bar_h + 2)
            width = max(0.0, plot.sx(value) - plot.left)
            plot.add(
                f'<rect x="{plot.left}" y="{y:.1f}" width="{width:.1f}" '
                f'height="{bar_h}" rx="4" fill="{hue}"/>'
            )
            plot.add(
                f'<text x="{plot.left + width + 8:.1f}" y="{y + bar_h - 2:.1f}" '
                f'class="barvalue">{value:.0f}</text>'
            )
            plot.add(_hit(plot.left + width, y + bar_h / 2,
                          f"{season.name} - {name}", f"{value:.1f} ACE",
                          f"through {season.through}"))
    return plot.svg(
        "Accumulated cyclone energy by basin against climatology",
        "Season to date compared with a normal season and with past El Nino "
        "seasons, both measured at the same calendar date.",
    )


# --------------------------------------------------------------------------
# cards
# --------------------------------------------------------------------------
ICON = {
    "critical": '<svg class="statusicon" viewBox="0 0 16 16" aria-hidden="true">'
                '<path d="M8 1 15 14H1Z" fill="none" stroke="currentColor" '
                'stroke-width="1.6"/><path d="M8 6v4" stroke="currentColor" '
                'stroke-width="1.6"/><circle cx="8" cy="12" r="0.9" '
                'fill="currentColor"/></svg>',
    "serious": '<svg class="statusicon" viewBox="0 0 16 16" aria-hidden="true">'
               '<circle cx="8" cy="8" r="6.4" fill="none" stroke="currentColor" '
               'stroke-width="1.6"/><path d="M8 4.5v5" stroke="currentColor" '
               'stroke-width="1.6"/></svg>',
    "warning": '<svg class="statusicon" viewBox="0 0 16 16" aria-hidden="true">'
               '<circle cx="8" cy="8" r="6.4" fill="none" stroke="currentColor" '
               'stroke-width="1.6"/><path d="M8 4.5v4.2" stroke="currentColor" '
               'stroke-width="1.6"/><circle cx="8" cy="11.4" r="0.9" '
               'fill="currentColor"/></svg>',
    "good": '<svg class="statusicon" viewBox="0 0 16 16" aria-hidden="true">'
            '<circle cx="8" cy="8" r="6.4" fill="none" stroke="currentColor" '
            'stroke-width="1.6"/><path d="M5 8.2 7.2 10.5 11 5.9" fill="none" '
            'stroke="currentColor" stroke-width="1.6"/></svg>',
}


def _chip(status: str, text: str) -> str:
    """A status always arrives as colour, icon and word together."""
    return (f'<span class="tcchip" data-status="{status}">{ICON[status]}'
            f'<span>{esc(text)}</span></span>')


def _status_for(fix) -> str:
    if fix is None:
        return "good"
    if fix.category >= 4:
        return "critical"
    if fix.category >= 1:
        return "serious"
    return "warning" if (fix.wind or 0) >= 34 else "good"


def tracks_card(state) -> str:
    """The live storms: map, per-storm summary, and the full forecast table."""
    storms = getattr(state, "cyclones", None)
    if storms is None or not storms.available:
        return ""
    # This map is drawn for the Atlantic and the eastern Pacific, the basins
    # the season is measured in. JTWC's storms are on the other side of the
    # date line - one plate carree window holding both would run the long way
    # round the world - so they are named here and drawn on the storm desk.
    live = tuple(s for s in storms.active if s.centre != "JTWC")
    beyond = [s for s in storms.active if s.centre == "JTWC"]
    elsewhere = ""
    if beyond:
        named = "; ".join(
            f"{esc(s.title)} ({esc(s.basin_name)}, "
            f"{esc(s.latest.label if s.latest else 'position unknown')})"
            for s in beyond)
        elsewhere = (f'<p class="caption">Also live, warned on by JTWC: {named}. '
                     "Drawn on the globe and the storm desk rather than on this "
                     "map of the Atlantic and eastern Pacific.</p>")
    if not live:
        return f"""<section class="card" id="cyclones">
  <h2>Tropical cyclones &mdash; live tracks</h2>
  <p class="caption">No active storms in the Atlantic, east or central Pacific
    at this run &middot; best-track and forecast decks checked
    {esc(storms.as_of[:16].replace('T', ' ') or 'this run')}</p>
  {elsewhere}
  <p class="prose">A quiet map is a reading, not an absence of one. In a strong
    El Nino an empty Atlantic in September is the teleconnection working, and
    the season panel below puts a number on how empty it is.</p>
</section>"""

    keyed = [(name, hue) for (name, hue) in
             zip([s.title for s in live], STORM_HUES)]
    legend = _legend(keyed + [("ensemble members", "var(--muted)")])

    blocks = []
    for storm in live:
        now = storm.latest
        if now is None:
            continue
        move = storm.translation
        motion = (f"moving {cyclones.bearing_name(move[1])} at {move[0]:.0f} kt"
                  if move else "motion not resolvable")
        change, _ = storm.rapid
        chips = [_chip(_status_for(now), now.label)]
        if change >= cyclones.RI_THRESHOLD:
            chips.append(_chip("critical" if change >= 50 else "serious",
                               f"rapid intensification {change:+.0f} kt/24 h"))
        threats = [t for t in storm.threats(350.0) if (t[1].wind or 0) >= 34]
        if threats:
            gap, fix, place = threats[0]
            chips.append(_chip(
                "critical" if gap <= 150 and fix.category >= 1 else "serious",
                f"{place.name} {gap:.0f} km now, moving away" if fix.tau == 0
                else f"{place.name} {gap:.0f} km in {fix.tau} h ({alerts._valid(fix)})",
            ))
        spread = storm.spread_km
        land = storm.nearest_land
        facts = [
            f"{now.wind or 0} kt sustained"
            + (f", {now.pressure} mb" if now.pressure else ""),
            _degrees(now).replace("&#176;", "°"),
            motion,
        ]
        if land:
            facts.append(f"{land[0]:.0f} km from {land[1].name}")
        if spread is not None:
            facts.append(
                f"{spread:.0f} km of track spread at +{storm.spread_tau} h")
        blocks.append(
            f'<div class="tcstorm"><h3>{esc(storm.title)} '
            f'<span class="tcid">{esc(storm.designation)}</span></h3>'
            f'<p class="caption">{" &middot; ".join(esc(fact) for fact in facts)}</p>'
            f'<div class="tcchips">{"".join(chips)}</div></div>'
        )

    rows = []
    for storm in live:
        for fix in [storm.latest] + [f for f in storm.forecast
                                     if f.tau <= cyclones.HORIZON]:
            if fix is None:
                continue
            rows.append([
                storm.title,
                "now" if fix.tau == 0 else f"+{fix.tau} h ({alerts._valid(fix)})",
                f"{abs(fix.lat):.1f}°{'N' if fix.lat >= 0 else 'S'}",
                f"{abs(fix.lon):.1f}°{'W' if fix.lon < 0 else 'E'}",
                f"{fix.wind or 0}",
                f"{fix.pressure}" if fix.pressure else "n/a",
                fix.label,
            ])

    threat_rows = []
    for storm in live:
        for gap, fix, place in storm.threats(400.0):
            if (fix.wind or 0) < 34:
                continue
            threat_rows.append([
                storm.title, f"{place.name}, {place.country}",
                f"{gap:.0f}", f"{cyclones.lead(fix)} ({alerts._valid(fix)})",
                f"{fix.wind or 0}",
                fix.label,
            ])
    threat_rows.sort(key=lambda row: float(row[2]))

    threat_table = table(
        "Closest approach to named coast, official forecast centre line",
        ["Storm", "Place", "km", "Lead", "kt", "Intensity"], threat_rows,
    ) if threat_rows else ""

    return f"""<section class="card" id="cyclones">
  <h2>Tropical cyclones &mdash; live tracks and forecast spread</h2>
  <p class="caption">{len(live)} active
    &middot; decks as of {esc(storms.as_of[:16].replace('T', ' ') or 'this run')}
    &middot; solid line is the best track, dashed is the official forecast,
    grey is every ensemble member</p>
  {track_map(live)}
  {legend}
  {elsewhere}
  <div class="tcgrid">{"".join(blocks)}</div>
  {table("Current position and official forecast",
         ["Storm", "Lead", "Lat", "Lon", "kt", "mb", "Intensity"], rows)}
  {threat_table}
  <p class="prose">Distances are to the forecast centre line. The wind field is
    wider than the line &mdash; hurricane-force wind reaches tens of kilometres
    either side of it and tropical-storm force roughly twice that &mdash; so a
    two-hundred-kilometre pass is not a miss. The grey cloud behind each
    forecast is the honest width of it.</p>
</section>"""


def season_card(state) -> str:
    """Did this El Nino do to these basins what the catalogue said it would."""
    from . import impacts

    storms = getattr(state, "cyclones", None)
    if storms is None or not storms.available:
        return ""
    chart = season_chart(storms)
    if not chart:
        return ""
    assessment = state.assessment
    index_name = assessment.index_name
    index_value = assessment.index_latest.value
    flavour = impacts.flavour_of(
        assessment.scale.flavour_index if assessment.scale else 0.0)

    verdicts = []
    rows = []
    for basin in ("AL", "EP"):
        season = storms.basins.get(basin)
        if season is None:
            continue
        scored = cyclones.verdict(season, index_value, flavour)
        if not scored:
            continue
        status = {True: "good", False: "critical", None: "warning"}[scored["agrees"]]
        word = {True: "Confirmed", False: "Contradicted",
                None: "Inconclusive"}[scored["agrees"]]
        verdicts.append(
            f'<div class="tcverdict"><h3>{esc(season.name)}</h3>'
            f'<div class="tcchips">{_chip(status, word)}</div>'
            f'<p class="prose">The catalogue calls for <strong>'
            f'{esc(scored["expected"])}</strong> activity here at {esc(index_name)} '
            f'{index_value:+.2f} ({esc(scored["likelihood"])}, '
            f'{esc(scored["confidence"])} confidence). Observed activity is '
            f'<strong>{esc(scored["observed"])}</strong>: {season.ace:.0f} ACE '
            f'against {scored["normal_ace"]:.0f} normal by {esc(season.through)}'
            + (f', and {scored["elnino_ratio"]:.2f}&#215; the composite of '
               f'{scored["sample"]} past El Nino seasons at the same date'
               if scored["elnino_ratio"] is not None else "")
            + f'. {esc(scored["effect"])}.</p></div>'
        )
        rows.append([
            season.name, f"{season.ace:.1f}",
            f"{season.normal_ace:.1f}" if season.normal_ace else "n/a",
            f"{season.ace_ratio:.2f}" if season.ace_ratio is not None else "n/a",
            f"{season.elnino_ace:.1f}" if season.elnino_ace else "n/a",
            str(season.named), str(season.hurricanes), str(season.major), word,
        ])

    elapsed = next((s.elapsed for s in storms.basins.values()
                    if s.elapsed is not None), None)
    footnote = (
        f"About {elapsed * 100:.0f} per cent of a normal season's energy has "
        "fallen by this date, so the comparison has that much of a season "
        "behind it." if elapsed else ""
    )
    return f"""<section class="card" id="cyclone-season">
  <h2>Season verification &mdash; what this El Nino did to the basins</h2>
  <p class="caption">Accumulated cyclone energy through {esc(storms.through)}
    &middot; climatology 1991&ndash;2020
    &middot; El Nino composite from {len(storms.elnino_years)} seasons with
    ASO {esc(index_name)} printed at or above +0.5&nbsp;&#176;C</p>
  {chart}
  {_legend(list(SERIES))}
  <div class="tcgrid">{"".join(verdicts)}</div>
  {table("Season to date against climatology",
         ["Basin", "ACE", "Normal to date", "Ratio", "El Nino to date",
          "Named", "Hurricanes", "Major", "Verdict"], rows)}
  <p class="prose">This is the one panel in the system where a forecast it
    made is scored against an outcome in the same season. The Atlantic
    suppression and the east Pacific enhancement are the two most reliable
    seasonal signals El Nino has, and they are being tested here in public
    rather than asserted. {esc(footnote)}</p>
  <p class="prose">On stopping a hurricane: it is not possible. Project
    STORMFURY seeded eyewalls with silver iodide from 1962 to 1983 and was
    abandoned because the changes it produced could not be separated from
    natural eyewall replacement, and because mature hurricanes carry far too
    little supercooled water for seeding to work at all. A Category&nbsp;4
    releases on the order of 10<sup>19</sup> joules a day as latent heat,
    several hundred times world electricity generation. What can be delivered
    is lead time, and the tracks above are four days of it.</p>
</section>"""


def css() -> str:
    return """
.tcgrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(270px, 1fr));
  gap: 14px; margin: 16px 0 4px; }
.tcstorm, .tcverdict { background: var(--plane); border: 1px solid var(--border);
  border-radius: 11px; padding: 12px 14px; }
.tcstorm h3, .tcverdict h3 { font-size: 0.95rem; margin: 0 0 3px; }
.tcstorm .caption, .tcverdict .prose { margin: 0 0 9px; font-size: 0.8rem; }
.tcid { color: var(--muted); font-weight: 500; font-size: 0.8rem; margin-left: 6px; }
.tcchips { display: flex; flex-wrap: wrap; gap: 7px; }
.tcchip { display: inline-flex; align-items: center; gap: 5px; font-size: 0.76rem;
  font-weight: 600; padding: 3px 9px 3px 7px; border-radius: 999px;
  border: 1px solid currentColor; }
.tcchip[data-status="critical"] { color: var(--critical); }
.tcchip[data-status="serious"] { color: var(--serious); }
.tcchip[data-status="warning"] { color: var(--warning); }
.tcchip[data-status="good"] { color: var(--good); }
.tcchip span { color: var(--ink); }
@media (max-width: 640px) { .tcgrid { grid-template-columns: 1fr; } }
"""


# --- Project STORMFURY, recreated -------------------------------------------
# Three series, fixed order, never cycled: what the storm had, what conserving
# angular momentum said it would be left with, and what it actually had six
# hours later. The third is the finding, so it sits last and reads last.
# Two categorical series, plus a reference mark. The wind before the eyewall
# moved is the origin each row is read from, not a third thing being compared,
# so it draws in neutral ink at a smaller radius: a hue there would claim an
# identity it does not have, and would put a near-grey in a palette whose other
# two slots have to carry identity by colour.
FURY_SERIES = (
    ("Angular momentum predicted", "var(--s2)"),
    ("What the hurricane actually did", "var(--s1)"),
)
FURY_REFERENCE = ("Wind before the eyewall moved (reference)", NEUTRAL)

FURY_ROWS = 14           # beyond this the row labels stop being legible
BIN_PCT = 10.0


def _fury_dumbbell(moves: list[dict], skill: dict) -> str:
    """Predicted against observed, one row per natural eyewall expansion."""
    shown = [m for m in moves if m.get("predicted_kt")][:FURY_ROWS]
    if not shown:
        return ""
    height = 76 + len(shown) * 26
    plot = Plot(940, height, (26, 168, 54, 210))
    winds = [v for m in shown
             for v in (m["wind_before"], m["wind_after"], m["predicted_kt"])]
    # Not anchored at zero. These are positions on a wind scale, not lengths
    # from an origin, and the quantity being read is the gap between two dots
    # - which a linear axis preserves wherever it starts. Anchoring at zero
    # would spend half the width on winds no hurricane in the sample had.
    lo, hi = min(winds) * 0.88, max(winds) * 1.06
    plot.domain(lo, hi, -0.6, len(shown) - 0.4)

    for tick in nice_ticks(lo, hi, 6):
        x = plot.sx(tick)
        plot.add(f'<line x1="{x:.1f}" y1="{plot.top:.1f}" x2="{x:.1f}" '
                 f'y2="{plot.top + plot.plot_h:.1f}" stroke="var(--grid)" '
                 f'stroke-width="1"/>')
        plot.add(f'<text x="{x:.1f}" y="{plot.top + plot.plot_h + 20:.1f}" '
                 f'text-anchor="middle" class="tick">{esc(int(tick))}</text>')
    plot.add(f'<text x="{plot.left + plot.plot_w / 2:.1f}" '
             f'y="{height - 4:.1f}" text-anchor="middle" class="axistitle">'
             f'maximum sustained wind, knots</text>')

    for index, move in enumerate(shown):
        # The list is sorted biggest relocation first, so it has to be drawn
        # downward: the y domain counts upward, and index 0 at sy(0) would put
        # the largest expansion at the bottom of a table read from the top.
        y = plot.sy(len(shown) - 1 - index)
        before = plot.sx(move["wind_before"])
        after = plot.sx(move["wind_after"])
        guess = plot.sx(move["predicted_kt"])
        # The gap between the prediction and the outcome IS the point, so it
        # is drawn as a bar rather than left for the reader to measure.
        plot.add(f'<line x1="{min(guess, after):.1f}" y1="{y:.1f}" '
                 f'x2="{max(guess, after):.1f}" y2="{y:.1f}" '
                 f'stroke="var(--track)" stroke-width="6" '
                 f'stroke-linecap="round"/>')
        plot.add(f'<circle cx="{before:.1f}" cy="{y:.1f}" r="4.5" '
                 f'fill="{NEUTRAL}" stroke="var(--plane)" stroke-width="2"/>')
        plot.add(f'<circle cx="{guess:.1f}" cy="{y:.1f}" r="6" '
                 f'fill="var(--s2)" stroke="var(--plane)" stroke-width="2"/>')
        plot.add(f'<circle cx="{after:.1f}" cy="{y:.1f}" r="6" '
                 f'fill="var(--s1)" stroke="var(--plane)" stroke-width="2"/>')

        label = f'{move["storm"]} {move["from_nm"]}→{move["to_nm"]} nm'
        plot.add(f'<text x="{plot.left - 12:.1f}" y="{y + 4:.1f}" '
                 f'text-anchor="end" class="rowlabel">{esc(label)}</text>')
        miss = move["wind_after"] - move["predicted_kt"]
        plot.add(f'<text x="{plot.left + plot.plot_w + 12:.1f}" '
                 f'y="{y + 4:.1f}" class="rowlabel">'
                 f'{esc(f"{miss:+d} kt off")}</text>')
        # One direct label, on the first row, so the legend never has to be
        # consulted to know which dot is which.
        if index == 0:
            plot.add(f'<text x="{guess:.1f}" y="{y - 12:.1f}" '
                     f'text-anchor="middle" class="pointlabel">predicted'
                     f'</text>')
            plot.add(f'<text x="{after:.1f}" y="{y - 12:.1f}" '
                     f'text-anchor="middle" class="pointlabel">actual</text>')
        detail = (f'{move["wind_before"]} kt before, {move["predicted_kt"]} kt '
                  f'predicted, {move["wind_after"]} kt observed')
        plot.add(_hit(guess, y, f'{move["storm"]}, {move["stamp"]}', detail,
                      f'eyewall {move["from_nm"]} to {move["to_nm"]} nm '
                      f'in {move["hours"]} h'))
        plot.add(_hit(after, y, f'{move["storm"]}, {move["stamp"]}', detail,
                      f'observed change {move["observed_pct"]:+.0f}%'))

    desc = (f'{len(shown)} natural eyewall expansions. Angular momentum '
            f'predicted a mean {skill.get("mean_predicted_drop", 0):.0f} per '
            f'cent wind drop; the storms gave up '
            f'{skill.get("mean_observed_drop", 0):.0f} per cent.')
    return plot.svg("Angular momentum against observation", desc)


def _fury_histogram(swings: dict) -> str:
    """How often untouched hurricanes move as far as STORMFURY claimed to."""
    changes = swings.get("changes") or []
    if not changes:
        return ""
    values = [c["pct"] for c in changes]
    low = math.floor(min(values) / BIN_PCT) * BIN_PCT
    high = math.ceil(max(values) / BIN_PCT) * BIN_PCT
    edges = []
    edge = low
    while edge < high:
        edges.append(edge)
        edge += BIN_PCT
    counts = []
    for start in edges:
        counts.append(len([v for v in values
                           if start <= v < start + BIN_PCT]))
    if not counts or not max(counts):
        return ""

    plot = Plot(940, 300, (22, 26, 56, 52))
    plot.domain(low, high, 0, max(counts) * 1.12)
    plot.gridlines(nice_ticks(0, max(counts) * 1.12, 5), fmt="{:.0f}")

    width = (plot.plot_w / len(edges)) - 2.0
    for start, count in zip(edges, counts):
        if not count:
            continue
        x = plot.sx(start) + 1.0
        y = plot.sy(count)
        base = plot.sy(0)
        plot.add(f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" '
                 f'height="{base - y:.1f}" rx="3" fill="var(--s3)"/>')
        plot.add(_hit(x + width / 2, y, f"{start:+.0f}% to "
                      f"{start + BIN_PCT:+.0f}%",
                      f"{count} of {len(values)} intervals",
                      "unseeded hurricanes, 24 hours apart"))

    # STORMFURY's claim, both signs, because the detection argument is about
    # magnitude rather than direction.
    claim = swings.get("claim", 31.0)
    for mark in (-claim, claim):
        if not low <= mark <= high:
            continue
        x = plot.sx(mark)
        plot.add(f'<line x1="{x:.1f}" y1="{plot.top:.1f}" x2="{x:.1f}" '
                 f'y2="{plot.sy(0):.1f}" stroke="var(--ink2)" '
                 f'stroke-width="2" stroke-dasharray="5 4"/>')
    # Both marks are labelled. One dashed line with a caption and one without
    # reads as a threshold and an artefact, rather than as a band.
    if low <= -claim <= high:
        plot.add(f'<text x="{plot.sx(-claim) - 8:.1f}" '
                 f'y="{plot.top + 14:.1f}" text-anchor="end" '
                 f'class="pointlabel">{esc(f"Debbie: -{claim:.0f}%")}</text>')
    if low <= claim <= high:
        plot.add(f'<text x="{plot.sx(claim) + 8:.1f}" '
                 f'y="{plot.top + 14:.1f}" class="pointlabel">'
                 f'{esc(f"the same swing upward: +{claim:.0f}%")}</text>')

    for tick in nice_ticks(low, high, 8):
        plot.add(f'<text x="{plot.sx(tick):.1f}" '
                 f'y="{plot.sy(0) + 20:.1f}" text-anchor="middle" '
                 f'class="tick">{esc(f"{tick:+.0f}%")}</text>')
    plot.add(f'<text x="{plot.left + plot.plot_w / 2:.1f}" y="296" '
             f'text-anchor="middle" class="axistitle">change in maximum '
             f'wind over 24 hours, unseeded hurricanes this season</text>')
    return plot.svg(
        "Natural intensity change against STORMFURY's claim",
        f"{swings['weakened_as_much']} of {swings['count']} unseeded "
        f"hurricane intervals weakened by at least {claim:.0f} per cent.")


def _criteria_rows(fury) -> list[list[str]]:
    rows = []
    for a in fury.assessments:
        for c in a.criteria:
            rows.append([
                a.title,
                f"{a.wind_kt} kt" if a.wind_kt else "-",
                c.name,
                {True: "Pass", False: "Fail", None: "Unknown"}[c.passed],
                c.detail,
            ])
    return rows


def fury_card(state) -> str:
    """Project STORMFURY, run as a procedure against the storms that exist."""
    fury = getattr(state, "stormfury", None)
    if fury is None or not fury.available:
        return ""

    reasons = "".join(
        f'<div class="furyreason"><h3>{esc(r.split(":")[0])}</h3>'
        f'<p>{esc(r.split(":", 1)[1].strip())}</p></div>'
        for r in fury.reasons)

    dumbbell = _fury_dumbbell(fury.moves, fury.skill)
    histogram = _fury_histogram(fury.swings)

    move_rows = [[m["storm"], m["stamp"], f'{m["from_nm"]}→{m["to_nm"]} nm',
                  f'{m["hours"]} h', f'{m["wind_before"]} kt',
                  f'{m["predicted_kt"]} kt', f'{m["wind_after"]} kt',
                  f'{m["observed_pct"]:+.0f}%']
                 for m in fury.moves if m.get("predicted_kt")]
    swing_rows = [[c["storm"], c["stamp"], f'{c["from_kt"]} kt',
                   f'{c["to_kt"]} kt', f'{c["pct"]:+.1f}%']
                  for c in sorted(fury.swings.get("changes") or [],
                                  key=lambda c: c["pct"])]

    momentum = ""
    strongest = max((a for a in fury.assessments if a.momentum),
                    key=lambda a: a.wind_kt or 0, default=None)
    if strongest is not None:
        rows = [[f'x{r["factor"]}', f'{r["from_nm"]}→{r["to_nm"]} nm',
                 f'{r["before_kt"]} kt', f'{r["after_kt"]} kt',
                 f'-{r["drop_pct"]}%',
                 f'Cat {r["category_before"]}→{r["category_after"]}']
                for r in strongest.momentum if r["after_kt"]]
        # These three tables have no chart to be the twin of: each is the
        # evidence for the sentence above it, so each is shown, not folded.
        momentum = table(
            f"If {strongest.title}'s eyewall could be moved outward",
            ["Expansion", "Eyewall", "Before", "After", "Drop", "Category"],
            rows, expanded=True)

    # Both of these argue from this season's numbers, so with no numbers
    # they are an assertion with a chart-shaped hole under it. Out they go,
    # rather than shipping an empty table below a paragraph of conclusions.
    relocation = ""
    if move_rows:
        relocation = f"""
  <h3>What real eyewalls actually do</h3>
  <p class="prose">Hurricanes relocate their own eyewalls, unaided, several
    times a season. That gives a live test of the prediction above: take every
    natural expansion in a hurricane this season, ask what conserving angular
    momentum says the wind should become, and compare it with the wind the
    storm actually had six hours later.</p>
  {dumbbell}
  {_legend(list(FURY_SERIES) + [FURY_REFERENCE])}
  <p class="prose">The prediction is consistently far too strong. A hurricane
    is not a spinning-down flywheel - it is fed high-momentum air continuously
    through the inflow, and the vortex restores itself while the eyewall
    moves. A closed-system momentum argument is an upper bound, not a
    forecast, and STORMFURY's expected effect came from exactly that
    calculation.</p>
  {table("Angular momentum against observation",
         ["Storm", "When", "Eyewall", "Over", "Before", "Predicted",
          "Observed", "Change"], move_rows)}
"""

    confound = ""
    if swing_rows:
        confound = f"""
  <h3>Why nobody could have told</h3>
  <p class="prose">The claimed result for Debbie was a
    {stormfury.DEBBIE_CLAIM_PCT:.0f}% wind reduction. This is every 24-hour
    intensity change in every unseeded hurricane this season, on the same
    axis. An effect that has to be picked out of this distribution, from a
    sample of four storms, was never going to be separable from what
    hurricanes do on their own.</p>
  {histogram}
  {table("Unseeded hurricane intensity changes, 24 h",
         ["Storm", "When", "From", "To", "Change"], swing_rows)}
"""

    history_rows = [[h.name, str(h.year), h.dates, h.claimed, h.outcome]
                    for h in stormfury.HISTORY]

    layer = fury.layer
    return f"""
<section class="card" id="stormfury">
  <h2>Project STORMFURY, recreated</h2>
  <p class="caption">The 1962-83 hurricane modification experiment, rebuilt as
    a decision procedure and run against the storms that are live right now.
    Three parts, kept separate because they failed differently:
    the mechanism, the trigger, and the measurement.</p>

  <p class="prose"><strong>{esc(fury.verdict)}</strong></p>
  <div class="furygrid">{reasons}</div>

  <h3>The mechanism, computed</h3>
  <p class="prose">Seeding was supposed to build a new eyewall further out.
    Air arriving at a larger radius with the same absolute angular momentum
    turns more slowly, so the wind falls - and the arithmetic
    (<code>M = rv + fr&sup2;/2</code>) genuinely predicts a drop about the
    size STORMFURY reported. That part was never wrong.{
    " " if momentum else ""}</p>
  {momentum}

{relocation}{confound}

  <h3>Would it even have been allowed to fly?</h3>
  <p class="prose">STORMFURY could not seed whatever it liked. Its own
    operating rules are checked here against each live storm - including the
    one rule no hurricane has ever passed.</p>
  {table("STORMFURY criteria against live storms",
         ["Storm", "Intensity", "Criterion", "Verdict", "Detail"],
         _criteria_rows(fury), expanded=True)}

  <h3>The record</h3>
  {table("Storms STORMFURY seeded",
         ["Storm", "Year", "Dates", "Claimed", "What it means"], history_rows,
         expanded=True)}
  <p class="prose">Four storms in twenty-one years, because the criteria above
    are almost never met at once. The seeding layer the hypothesis needed sits
    between {layer.get("base_km", 0)} and {layer.get("top_km", 0)} km, about
    {layer.get("depth_km", 0)} km deep, above a freezing level near
    {layer.get("freezing_km", 0)} km - and the observation that closed the
    programme is that there is almost no supercooled water up there to freeze.
    <em>{esc(stormfury.SEEDABILITY["source"])}</em></p>

  <p class="prose">{esc(stormfury.PROGRAMME["ended"])}</p>
  <p class="prose"><strong>What it did buy:</strong>
    {esc(stormfury.PROGRAMME["legacy"])} The deliverable from all of this is
    lead time, and the tracks and the forecast panels above are what lead time
    looks like.</p>
</section>"""


def fury_css() -> str:
    return """
.furygrid { display: grid; grid-template-columns: repeat(auto-fit, minmax(255px, 1fr));
  gap: 14px; margin: 14px 0 20px; }
.furyreason { background: var(--plane); border: 1px solid var(--border);
  border-radius: 11px; padding: 12px 14px; }
.furyreason h3 { font-size: 0.78rem; letter-spacing: 0.08em; margin: 0 0 6px;
  color: var(--muted); font-weight: 700; }
.furyreason p { margin: 0; font-size: 0.83rem; line-height: 1.5; }
#stormfury h3 { font-size: 1rem; margin: 26px 0 6px; }
#stormfury code { font-size: 0.85em; background: var(--plane);
  border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; }
@media (max-width: 640px) { .furygrid { grid-template-columns: 1fr; } }
"""
