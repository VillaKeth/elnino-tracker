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
                f'class="tick">{esc(fmt.format(tick))}</text>'
            )

    def svg(self, title: str, desc: str) -> str:
        body = "\n".join(self.parts)
        return (
            f'<svg viewBox="0 0 {self.w} {self.h}" role="img" '
            f'aria-label="{esc(title)}" preserveAspectRatio="xMidYMid meet">'
            f"<title>{esc(title)}</title><desc>{esc(desc)}</desc>\n{body}\n</svg>"
        )


def nice_ticks(low: float, high: float, count: int = 6) -> list[float]:
    """Round tick values covering [low, high]."""
    span = high - low
    if span <= 0:
        return [low]
    raw = span / max(1, count)
    magnitude = 10 ** (len(f"{int(abs(raw))}") - 1) if abs(raw) >= 1 else 0.1
    for step in (0.1, 0.2, 0.25, 0.5, 1.0, 2.0, 2.5, 5.0, 10.0):
        if step * magnitude >= raw:
            step = step * magnitude
            break
    else:
        step = magnitude
    start = step * (int(low / step) - 1)
    ticks: list[float] = []
    value = start
    while value <= high + step:
        # Stay strictly inside the domain: a tick drawn past the plot floor
        # collides with the x-axis label row underneath it.
        if low <= value <= high:
            ticks.append(round(value, 6))
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
def table(caption: str, headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(cell)}</td>" for cell in row) + "</tr>" for row in rows
    )
    return (
        f'<details class="tableview"><summary>Table view &mdash; {esc(caption)}</summary>'
        f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead>'
        f"<tbody>{body}</tbody></table></div></details>"
    )


def _legend(items: list[tuple[str, str]]) -> str:
    keys = "".join(
        f'<span class="key"><span class="swatch" style="background:{colour}"></span>{esc(name)}</span>'
        for name, colour in items
    )
    return f'<div class="legend">{keys}</div>'


