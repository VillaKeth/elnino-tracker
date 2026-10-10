"""SVG and HTML primitives shared by every panel.

Pulled out of ``dashboard`` so that the panel modules can use the same plotting
surface, the same validated palette and the same accessibility furniture
without importing the dashboard itself. Nothing here knows anything about
ENSO; it is a small plotting library and no more.

The palette is not a matter of taste. Every categorical and diverging set below
was checked with the dataviz validator for lightness band, chroma floor,
colour-vision-deficiency separation, normal-vision separation and contrast
against its own surface, in both light and dark mode. Light mode returns a
contrast warning on three of the five categorical slots, which is why every
chart in this package carries direct labels and a table view: identity is never
reachable by colour alone.
"""

from __future__ import annotations

import html
import math
import re

# --- palette ---------------------------------------------------------------
LIGHT = {
    "surface": "#fcfcfb", "plane": "#f9f9f7",
    "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
    "grid": "#e1e0d9", "axis": "#c3c2b7", "border": "rgba(11,11,11,0.10)",
    "s1": "#2a78d6", "s2": "#eb6834", "s3": "#1baf7a", "s4": "#eda100", "s5": "#e87ba4",
    "warm": "#e34948", "cool": "#2a78d6",
    "good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b",
    "track": "#e6e5e0",
}
DARK = {
    "surface": "#1a1a19", "plane": "#0d0d0d",
    "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781",
    "grid": "#2c2c2a", "axis": "#383835", "border": "rgba(255,255,255,0.10)",
    "s1": "#3987e5", "s2": "#d95926", "s3": "#199e70", "s4": "#c98500", "s5": "#d55181",
    "warm": "#e66767", "cool": "#3987e5",
    "good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b",
    "track": "#2c2c2a",
}

BAND_STATUS = {
    "Extreme": "critical", "Very High": "serious", "High": "serious",
    "Moderate": "warning", "Low": "good", "Minimal": "good",
}


def esc(text: object) -> str:
    return html.escape(str(text), quote=True)


# The model's sentences are written once, in ASCII, for the report and the
# console as well as the page; these are its unit spellings and the signs the
# page's own charts and tiles use for them.
_PAGE_UNITS = (
    (re.compile(r"degC"), "&deg;C"),
    (re.compile(r" x10\^14 m3\b"), " \u00d7 10\u00b9\u2074 m\u00b3"),
    (re.compile(r"(\d) sigma\b"), "\\1\u03c3"),
)


def tick_text(value: float, fmt: str = "{:+.1f}") -> str:
    """An axis label. Zero is unsigned whatever the format: a "+0.0" at the
    zero line reads as a direction it does not have."""
    if abs(value) < 1e-9:
        return fmt.format(0.0).lstrip("+-")
    return fmt.format(value)


def prose(text: object) -> str:
    """Escape one of the model's sentences for the page, with its units signed.

    Kept apart from ``esc``, which also carries JSON into data attributes,
    where rewriting a substring would rewrite the data.
    """
    out = esc(text)
    for spelling, sign in _PAGE_UNITS:
        out = spelling.sub(sign, out)
    return out


# --- label geometry ----------------------------------------------------------
# An average glyph is about six tenths of the font size wide in the UI stack;
# the boxes below are estimates for keeping labels apart, not a text layout.
EM = 0.6


def label_box(x: float, y: float, text: str, size: float,
              anchor: str = "start") -> tuple[float, float, float, float]:
    """The box a label covers: left, top, right, bottom, in plot units."""
    width = EM * size * len(text)
    left = (x - width / 2 if anchor == "middle"
            else x - width if anchor == "end" else x)
    return (left, y - 0.8 * size, left + width, y + 0.25 * size)


def boxes_clear(box, taken) -> bool:
    """Whether a box overlaps none of the boxes already taken."""
    return not any(box[0] < t[2] and t[0] < box[2]
                   and box[1] < t[3] and t[1] < box[3] for t in taken)


def crosses(box, segment, pad: float = 0.0) -> bool:
    """Whether a straight segment passes through a box grown by ``pad``.

    Liang-Barsky clipping: the segment is cut against each edge in turn, and
    it crosses the box if anything of it survives all four cuts.
    """
    left, top = box[0] - pad, box[1] - pad
    right, bottom = box[2] + pad, box[3] + pad
    x1, y1, x2, y2 = segment
    dx, dy = x2 - x1, y2 - y1
    enter, leave = 0.0, 1.0
    for p, q in ((-dx, x1 - left), (dx, right - x1),
                 (-dy, y1 - top), (dy, bottom - y1)):
        if p == 0:
            if q < 0:
                return False
            continue
        t = q / p
        if p < 0:
            if t > leave:
                return False
            enter = max(enter, t)
        else:
            if t < enter:
                return False
            leave = min(leave, t)
    return enter <= leave


class Plot:
    """Minimal linear-scale SVG plotting surface."""

    def __init__(self, width: int, height: int, pad: tuple[int, int, int, int]):
        self.w, self.h = width, height
        self.top, self.right, self.bottom, self.left = pad
        self.parts: list[str] = []
        self.x0, self.x1 = 0.0, 1.0
        self.y0, self.y1 = 0.0, 1.0

    @property
    def plot_w(self) -> float:
        return self.w - self.left - self.right

    @property
    def plot_h(self) -> float:
        return self.h - self.top - self.bottom

    def domain(self, x0: float, x1: float, y0: float, y1: float) -> None:
        self.x0, self.x1 = x0, (x1 if x1 != x0 else x0 + 1)
        self.y0, self.y1 = y0, (y1 if y1 != y0 else y0 + 1)

    def sx(self, value: float) -> float:
        return self.left + (value - self.x0) / (self.x1 - self.x0) * self.plot_w

    def sy(self, value: float) -> float:
        return self.top + (self.y1 - value) / (self.y1 - self.y0) * self.plot_h

    def add(self, markup: str) -> None:
        self.parts.append(markup)

    def gridlines(self, ticks: list[float], fmt: str = "{:+.1f}") -> None:
        """Hairline, solid, recessive; zero line one shade stronger."""
        for tick in ticks:
            y = self.sy(tick)
            stroke = "var(--axis)" if abs(tick) < 1e-9 else "var(--grid)"
            self.add(
                f'<line x1="{self.left:.1f}" y1="{y:.1f}" x2="{self.left + self.plot_w:.1f}" '
                f'y2="{y:.1f}" stroke="{stroke}" stroke-width="1" />'
            )
            self.add(
                f'<text x="{self.left - 8:.1f}" y="{y + 4:.1f}" text-anchor="end" '
                f'class="tick">{esc(tick_text(tick, fmt))}</text>'
            )

    def svg(self, title: str, desc: str) -> str:
        body = "\n".join(self.parts)
        return (
            f'<svg viewBox="0 0 {self.w} {self.h}" role="img" '
            f'aria-label="{esc(title)}" preserveAspectRatio="xMidYMid meet">'
            f"<title>{esc(title)}</title><desc>{esc(desc)}</desc>\n{body}\n</svg>"
        )


def map_plot(width: int, pad: tuple[int, int, int, int],
             lon_span: float, lat_span: float) -> Plot:
    """A plot for a latitude-longitude map, at the map's true shape.

    The frame's height follows from its width and the map's extent, so a
    degree of latitude is drawn as long as a degree of longitude - the plate
    carree every gridded product is published on. A fixed frame stretches
    the map to fit instead, and a stretched map turns a storm heading
    west-north-west into one heading north-west.
    """
    top, right, bottom, left = pad
    plot_w = width - left - right
    return Plot(width, round(plot_w * lat_span / lon_span) + top + bottom, pad)


# --- paths -------------------------------------------------------------------
def _tenths(value: float) -> int:
    """A coordinate in tenths of a unit, rounded as ``f"{value:.1f}"`` rounds it."""
    return round(float(f"{value:.1f}") * 10)


def _short(tenths: int) -> str:
    """A number of tenths as briefly as a browser reads it: .5, -1.2, 0, 12."""
    whole, tenth = divmod(abs(tenths), 10)
    text = str(whole) if not tenth else f".{tenth}" if not whole else f"{whole}.{tenth}"
    return "-" + text if tenths < 0 else text


def _numbers(texts) -> str:
    """Numbers run together as a path reads them: a space between two, none
    before a minus, which starts a number of its own, nor before a point
    after a number that has one, as a number holds one point at most:
    "11.5.5" is 11.5 and then .5."""
    out, pointed = "", False
    for text in texts:
        joined = not out or text.startswith("-") or (pointed and text.startswith("."))
        out += text if joined else " " + text
        pointed = "." in text
    return out


def relative_d(lines) -> str:
    """One path's ``d`` for these polylines, each vertex the step from the last.

    A coastline written vertex by vertex in full repeats the hundreds of every
    coordinate: "L176.7 346.6 L176.4 347.1". Written as steps, "-.3.5", it is
    about half the bytes. Every vertex is first rounded to the tenth of a unit
    it would have been written at, and the steps are taken between those, so
    the browser's running sum lands on exactly the points the absolute path
    named. A step that rounds to nothing is left out, and a line left with no
    step at all is not drawn: neither ever showed.
    """
    out = []
    for line in lines:
        points = [(_tenths(x), _tenths(y)) for x, y in line]
        steps = []
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            if (ax, ay) != (bx, by):
                steps.extend((_short(bx - ax), _short(by - ay)))
        if steps:
            out.append(f"M{_numbers(map(_short, points[0]))}l{_numbers(steps)}")
    return "".join(out)


def nice_ticks(low: float, high: float, count: int = 6) -> list[float]:
    """Round tick values covering [low, high].

    The step is the smallest of 1, 2, 2.5, 5 or 10 times a power of ten that is
    at least the requested spacing, and the first candidate is the multiple of
    that step at or below ``low``.

    Two things here are less obvious than they look. The decade comes from a
    logarithm rather than the digit count of ``int(raw)``, which collapses to
    zero for every spacing below one and used to pin the decade at 0.1 for all
    of them: a domain of +/-0.003 then asked for a 0.01 step, no multiple of
    which lies inside it, and the axis came back with a single tick. And the
    first candidate is a floor rather than a truncation, which rounds toward
    zero and so lands *inside* a negative domain - which is why an axis from
    -0.35 to -0.05 used to lose its leftmost tick.
    """
    span = high - low
    if span <= 0:
        return [low]
    raw = span / max(1, count)
    magnitude = 10.0 ** math.floor(math.log10(raw))
    step = magnitude
    for multiple in (1.0, 2.0, 2.5, 5.0, 10.0):
        step = multiple * magnitude
        if step >= raw:
            break
    # A tick is kept only if it is inside the domain, because one drawn past
    # the plot floor collides with the axis label row underneath it; the
    # tolerance is there so a boundary tick is not lost to binary rounding.
    ticks: list[float] = []
    value = math.floor(low / step) * step
    edge = step * 1e-9
    while value <= high + step:
        if low - edge <= value <= high + edge:
            # Adding zero because -0.0 survives round() and formats as
            # "-0.00", which is a tick label claiming a sign that zero has not
            # got. It reached the page.
            ticks.append(round(value, 10) + 0.0)
        value += step
    return ticks or [low, high]


def _hit(x: float, y: float, label: str, value: str, extra: str = "") -> str:
    """Invisible, generous hover target carrying its own tooltip payload."""
    return (
        f'<circle class="hit" cx="{x:.1f}" cy="{y:.1f}" r="13" fill="transparent" '
        f'tabindex="0" data-label="{esc(label)}" data-value="{esc(value)}" '
        f'data-extra="{esc(extra)}"></circle>'
    )


# --- tables ------------------------------------------------------------------
# Characters past which a table cell is a sentence rather than a value, and
# the look of a value: a number, signed or not, or the mark for a missing one.
TEXT_CELL = 40
_NUMBER = re.compile(r"[+\-\u2212]?\.?\d")
_MISSING = {"", "-", "\u2014", "n/a"}


def _column_class(values: list[str]) -> str:
    """"txt" for a column of sentences, "lbl" for words, "" for numbers."""
    if any(len(v) > TEXT_CELL for v in values):
        return "txt"
    if all(_NUMBER.match(v) or v in _MISSING for v in values):
        return ""
    return "lbl"


def table(caption: str, headers: list[str], rows: list[list[str]],
          expanded: bool = False) -> str:
    """A table behind a disclosure: folded when it is the twin of a chart,
    expanded when it is the only thing its card shows."""
    # Numbers align right, on one line; words align left, and a column of
    # sentences wraps as well.
    kinds = [_column_class([str(row[i]) for row in rows if i < len(row)])
             for i in range(len(headers))]

    def cell(tag: str, i: int, value: object) -> str:
        kind = kinds[i] if i < len(kinds) else ""
        mark = f' class="{kind}"' if kind else ""
        return f"<{tag}{mark}>{prose(value)}</{tag}>"

    head = "".join(cell("th", i, h) for i, h in enumerate(headers))
    body = "".join(
        "<tr>" + "".join(cell("td", i, value) for i, value in enumerate(row)) + "</tr>"
        for row in rows
    )
    return (
        f'<details class="tableview"{" open" if expanded else ""}>'
        f"<summary>Table view &mdash; {prose(caption)}</summary>"
        f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div></details>"
    )


def _legend(items: list[tuple[str, str]], extra: str = "") -> str:
    """A key for each colour, and after them ``extra``: keys drawn otherwise."""
    keys = "".join(
        f'<span class="key"><span class="swatch" style="background:{colour}"></span>{esc(name)}</span>'
        for name, colour in items
    )
    return f'<div class="legend">{keys}{extra}</div>'


