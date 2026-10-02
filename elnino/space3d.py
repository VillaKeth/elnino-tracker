"""Three-dimensional views: the thermocline as a surface, the oscillator as a spiral.

Two things about this event are genuinely three-dimensional and lose something
when flattened.

The **thermocline** is a sheet. Its depth varies with longitude (the east-west
tilt that El Nino relaxes) and with latitude (the off-equatorial ridges that
hold the recharged heat and decide whether the event keeps going). A section
shows the first, a map shows the second; only a surface shows both at once,
which is the difference between seeing that the tilt has relaxed and seeing
that the warm water is still banked up off the equator waiting to come back.

The **recharge oscillator** is a loop in two variables that does not close: it
spirals, and where it spirals to is the forecast. Plotted in two dimensions the
successive orbits overlap and the last four years become a scribble. Adding
time as the third axis separates the orbits and makes growth or decay a visible
slope rather than something inferred from label order.

How it works
------------
Each panel is rendered twice. The server draws a default oblique view as real
SVG, so the page is complete and correct with JavaScript disabled, in a print,
and in a screenshot. The same geometry is also emitted as JSON, and a small
inline script re-projects and redraws it on drag. There is no library and no
network dependency; the projection is fifteen lines of arithmetic.

The projection is orthographic, not perspective. A perspective view would make
two anomalies of equal size look different depending on where they sat in the
basin, which is exactly the kind of quiet distortion this package avoids
elsewhere by refusing dual axes.
"""

from __future__ import annotations

import json
import math

from . import grids
from .grids import Mesh, lat_name, lon_name
from .svg import esc, table

# Default camera. Yaw is rotation about the vertical, pitch is elevation.
YAW = -38.0
PITCH = 26.0

MESH_LATS = (-8.0, -5.0, -2.0, 0.0, 2.0, 5.0, 8.0)


def project(
    x: float, y: float, z: float, yaw: float, pitch: float
) -> tuple[float, float, float]:
    """Orthographic projection of a unit-cube coordinate.

    Returns screen x, screen y and a camera-depth key for back-to-front
    sorting. Inputs are expected in roughly -1..1 on each axis; scaling to the
    viewport is the caller's business.
    """
    a = math.radians(yaw)
    b = math.radians(pitch)
    xr = x * math.cos(a) - y * math.sin(a)
    yr = x * math.sin(a) + y * math.cos(a)
    screen_x = xr
    screen_y = z * math.cos(b) - yr * math.sin(b)
    depth = yr * math.cos(b) + z * math.sin(b)
    return screen_x, -screen_y, depth


def _cloud(payload: dict) -> list[list[float]]:
    """Every point the scene will draw, in one list.

    Both the fit and the centring have to see the same cloud in both renderers,
    or the server picture and the first client redraw will not line up. The
    axis text anchors are in here deliberately: they sit outside the box, so
    including them is what keeps the labels on screen.
    """
    points: list[list[float]] = []
    for item in payload["axes"]:
        points.extend(item["p"])
        points.extend(item.get("alt", ()))
    if payload.get("kind") == "line":
        for point in payload["line"]:
            points.append(point["p"])
            points.append([point["p"][0], point["p"][1], -1.0])
    else:
        for quad in payload["quads"]:
            points.extend(quad["p"])
    return points


def fit_view(points: list, width: int, height: int, yaw: float, pitch: float,
             pad: float = 18.0) -> tuple[float, float, float]:
    """Scale and centre that make this particular view fill the frame.

    Fitting the current view rather than the whole rotation sphere is a
    deliberate trade. A sphere fit is sized for the worst angle, which here is
    looking straight down, and every other angle then sits in a box two thirds
    empty. Re-fitting per frame means the surface grows and shrinks a little as
    it is dragged; that is the cost, and it buys a picture that is readable at
    every angle instead of only one.
    """
    xs = []
    ys = []
    for point in points:
        sx, sy, _ = project(point[0], point[1], point[2], yaw, pitch)
        xs.append(sx)
        ys.append(sy)
    span_x = max(max(xs) - min(xs), 1e-6)
    span_y = max(max(ys) - min(ys), 1e-6)
    scale = min((width - 2 * pad) / span_x, (height - 2 * pad) / span_y)
    mid_x = (min(xs) + max(xs)) / 2.0
    mid_y = (min(ys) + max(ys)) / 2.0
    return scale, width / 2.0 - mid_x * scale, height / 2.0 - mid_y * scale


def _interpolate_mesh(mesh: Mesh) -> tuple[list[float], list[float], list[list[dict]]]:
    """Fill the mooring lattice into a rectangular grid.

    The array is not complete: 180E carries only three latitudes, 205E only
    three, and a mooring drops out whenever one is off station. Gaps are filled
    by linear interpolation along latitude first (the array is denser that way)
    and then along longitude, and any cell that still has no neighbours on both
    sides is left empty rather than extrapolated.
    """
    lookup = mesh.lookup()
    lons = [lon for lon in mesh.lons if 150.0 <= lon <= 290.0]
    lats = list(MESH_LATS)

    grid: list[list[dict | None]] = []
    for lat in lats:
        row: list[dict | None] = []
        for lon in lons:
            node = lookup.get((lat, lon))
            row.append(
                {"h": node.height, "a": node.anomaly} if node else None
            )
        grid.append(row)

    def fill(line: list[dict | None]) -> None:
        known = [i for i, v in enumerate(line) if v is not None]
        for gap in (i for i, v in enumerate(line) if v is None):
            before = [i for i in known if i < gap]
            after = [i for i in known if i > gap]
            if not before or not after:
                continue
            left, right = before[-1], after[0]
            frac = (gap - left) / (right - left)
            low, high = line[left], line[right]
            merged = {"h": low["h"] + frac * (high["h"] - low["h"]), "a": None}
            if low["a"] is not None and high["a"] is not None:
                merged["a"] = low["a"] + frac * (high["a"] - low["a"])
            line[gap] = merged

    for col in range(len(lons)):
        column = [grid[row][col] for row in range(len(lats))]
        fill(column)
        for row in range(len(lats)):
            grid[row][col] = column[row]
    for row in range(len(lats)):
        fill(grid[row])

    return lons, lats, [[cell for cell in row] for row in grid]


def thermocline(mesh: Mesh, width: int = 620, height: int = 430) -> str:
    """The 20 °C isotherm as a rotatable surface over the equatorial Pacific."""
    lons, lats, grid = _interpolate_mesh(mesh)
    if len(lons) < 3:
        return ""

    heights = [c["h"] for row in grid for c in row if c]
    anomalies = [c["a"] for row in grid for c in row if c and c["a"] is not None]
    if not heights:
        return ""
    deep, shallow = max(heights), min(heights)
    span = max(deep - shallow, 1.0)
    use_anomaly = len(anomalies) >= len(heights) // 2
    limit = max((abs(a) for a in anomalies), default=1.0) or 1.0

    def norm(lon: float) -> float:
        return (lon - lons[0]) / max(lons[-1] - lons[0], 1.0) * 2.0 - 1.0

    def norm_lat(lat: float) -> float:
        return lat / 10.0

    def norm_depth(value: float) -> float:
        # Deeper is lower on the page: the surface should look like a bowl,
        # not a hill, or the west Pacific warm pool reads as a mountain.
        return -((value - shallow) / span * 1.25 - 0.62)

    def klass(cell: dict) -> str:
        if use_anomaly and cell["a"] is not None:
            index = max(0, min(10, int((cell["a"] / limit + 1.0) / 2.0 * 11)))
            return f"d{index}"
        index = max(0, min(8, int((cell["h"] - shallow) / span * 9)))
        return f"p{index}"

    quads = []
    for row in range(len(lats) - 1):
        for col in range(len(lons) - 1):
            corners = [
                grid[row][col], grid[row][col + 1],
                grid[row + 1][col + 1], grid[row + 1][col],
            ]
            if any(c is None for c in corners):
                continue
            coords = [
                (norm(lons[col]), norm_lat(lats[row]), norm_depth(corners[0]["h"])),
                (norm(lons[col + 1]), norm_lat(lats[row]), norm_depth(corners[1]["h"])),
                (norm(lons[col + 1]), norm_lat(lats[row + 1]), norm_depth(corners[2]["h"])),
                (norm(lons[col]), norm_lat(lats[row + 1]), norm_depth(corners[3]["h"])),
            ]
            mean = {
                "h": sum(c["h"] for c in corners) / 4.0,
                "a": (sum(c["a"] for c in corners) / 4.0
                      if all(c["a"] is not None for c in corners) else None),
            }
            quads.append({
                "p": [[round(v, 4) for v in point] for point in coords],
                "c": klass(mean),
                "t": (
                    f"{lat_name(lats[row])} {lon_name(lons[col])} - "
                    f"{mean['h']:.0f} m"
                    + (f", {mean['a']:+.0f} m vs normal" if mean["a"] is not None else "")
                ),
            })

    axes = _axis_box(lons, lats, norm, norm_lat, shallow, deep, span)
    payload = {"quads": quads, "axes": axes, "yaw": YAW, "pitch": PITCH,
               "w": width, "h": height, "kind": "quads"}
    body = _render_scene(payload, YAW, PITCH, width, height)

    rows = []
    for row in range(len(lats)):
        line = [lat_name(lats[row])]
        for col in range(len(lons)):
            cell = grid[row][col]
            line.append(f"{cell['h']:.0f}" if cell else "-")
        rows.append(line)

    tilt = ""
    equator = grid[lats.index(0.0)]
    measured = grids.tilt([c["h"] if c else None for c in equator])
    if measured is not None:
        drop = measured[0]
        tilt = (
            f" The east-west tilt along the equator is currently "
            f"<strong>{drop:.0f} m</strong> on this daily array; a neutral Pacific "
            f"runs near 100 m, and a strong event flattens it. The cross-section "
            f"below quotes the same tilt from the monthly moorings, over a wider "
            f"span, so the two numbers are two measurements rather than one."
        )

    scale_note = (
        "Colour is the anomaly against this mooring's own climatology for the calendar "
        "month." if use_anomaly else
        "Colour is absolute depth; the anomaly climatology was unavailable this run."
    )
    return f"""<section class="card" id="thermocline-3d">
  <h2>The thermocline, in three dimensions</h2>
  <p class="caption">Depth of the 20 °C isotherm across the TAO/TRITON array, as of
    {esc(mesh.as_of)}. Longitude runs west to east, latitude across, and the surface
    height is depth, so the sheet you are looking at is the top of the cold water.
    {esc(scale_note)}{tilt}
    <span class="hint">Drag to rotate. Use the buttons for fixed views.</span></p>
  {_ramp_note(use_anomaly, limit, shallow, deep)}
  <div class="scene" data-scene='{esc(json.dumps(payload, separators=(",", ":")))}'>
    <div class="viewbtns">
      <button type="button" data-view="-38,26">Oblique</button>
      <button type="button" data-view="0,-88">Top down</button>
      <button type="button" data-view="0,2">Along the equator</button>
      <button type="button" data-view="-90,8">Across the basin</button>
    </div>
    <div class="chart">{body}</div>
  </div>
  {table('20 °C isotherm depth in metres, by mooring',
         ['latitude'] + [lon_name(l) for l in lons], rows)}
</section>"""


def _ramp_note(use_anomaly: bool, limit: float, shallow: float, deep: float) -> str:
    if use_anomaly:
        cells = "".join(
            f'<span class="rampcell" style="background:var(--d{i})"></span>'
            for i in range(11)
        )
        ticks = (
            f'<span class="ramptick">{-limit:+.0f}</span>'
            f'<span class="ramptick">0</span>'
            f'<span class="ramptick">{limit:+.0f}</span>'
        )
        caption = "thermocline anomaly <span class=\"rampunits\">m</span>"
    else:
        cells = "".join(
            f'<span class="rampcell" style="background:var(--p{i})"></span>'
            for i in range(9)
        )
        ticks = (
            f'<span class="ramptick">{shallow:.0f}</span>'
            f'<span class="ramptick">{deep:.0f}</span>'
        )
        caption = "isotherm depth <span class=\"rampunits\">m</span>"
    return (
        f'<div class="ramp"><div class="ramplabel">{caption}</div>'
        f'<div class="rampstrip">{cells}</div>'
        f'<div class="rampticks">{ticks}</div></div>'
    )


def _axis_box(lons, lats, norm, norm_lat, shallow, deep, span) -> list[dict]:
    """A wireframe floor and labelled edges, so the surface has somewhere to sit."""
    # Below the deepest point of the surface, so the grid always reads as a
    # floor rather than a plane the sheet dives through.
    floor = -1.05
    items: list[dict] = []
    for lon in lons:
        items.append({"kind": "line",
                      "p": [[norm(lon), norm_lat(lats[0]), floor],
                            [norm(lon), norm_lat(lats[-1]), floor]]})
    for lat in lats:
        items.append({"kind": "line",
                      "p": [[norm(lons[0]), norm_lat(lat), floor],
                            [norm(lons[-1]), norm_lat(lat), floor]]})
    # Standing well off the box: at an oblique yaw one of the two floor edges
    # runs up the screen and straight under the surface, and a tick sitting
    # tight against that edge ends up printed on top of the data.
    for lon in lons[::2]:
        items.append({
            "kind": "text",
            "p": [[norm(lon), norm_lat(lats[0]) - 0.50, floor]],
            "alt": [[norm(lon), norm_lat(lats[-1]) + 0.50, floor]],
            "t": lon_name(lon),
        })
    for lat in (lats[0], 0.0, lats[-1]):
        items.append({
            "kind": "text",
            "p": [[norm(lons[0]) - 0.40, norm_lat(lat), floor]],
            "alt": [[norm(lons[-1]) + 0.40, norm_lat(lat), floor]],
            "t": lat_name(lat),
        })
    return items


def _nearer(item: dict, default: tuple, yaw: float, pitch: float) -> tuple:
    """Whichever of a tick's two candidate edges currently faces the camera.

    A floor tick has to live on one of two opposite edges of the box, and at
    any oblique yaw one of those edges is behind the data. Picking per view is
    what keeps the longitude ticks in front of the surface all the way round
    instead of only at the angle the page happened to ship at.
    """
    alt = item.get("alt")
    if not alt:
        return default
    other = project(alt[0][0], alt[0][1], alt[0][2], yaw, pitch)
    return other if other[2] > default[2] else default


def _render_scene(payload: dict, yaw: float, pitch: float, width: int, height: int) -> str:
    """Server-side render of one view, identical in geometry to the client's."""
    scale, cx, cy = fit_view(_cloud(payload), width, height, yaw, pitch)

    parts = []
    labels = []
    for item in payload["axes"]:
        points = [project(*p, yaw, pitch) for p in item["p"]]
        if item["kind"] == "line":
            (x0, y0, _), (x1, y1, _) = points
            parts.append(
                f'<line x1="{cx + x0 * scale:.1f}" y1="{cy + y0 * scale:.1f}" '
                f'x2="{cx + x1 * scale:.1f}" y2="{cy + y1 * scale:.1f}" '
                f'stroke="var(--grid)" stroke-width="1"/>'
            )
        else:
            # Held back until after the surface. An axis label behind an opaque
            # quad is an axis label that is not there.
            x, y, _ = _nearer(item, points[0], yaw, pitch)
            labels.append(
                f'<text x="{cx + x * scale:.1f}" y="{cy + y * scale:.1f}" '
                f'text-anchor="middle" class="tick scenetick">{esc(item["t"])}</text>'
            )

    ordered = sorted(
        payload["quads"],
        key=lambda q: sum(project(*p, yaw, pitch)[2] for p in q["p"]) / 4.0,
    )
    for quad in ordered:
        points = [project(*p, yaw, pitch) for p in quad["p"]]
        path = " ".join(
            f"{cx + x * scale:.1f},{cy + y * scale:.1f}" for x, y, _ in points
        )
        parts.append(
            f'<polygon points="{path}" fill="var(--{quad["c"]})" '
            f'stroke="var(--surface)" stroke-width="0.5" class="hit" '
            f'data-label="20 °C isotherm" data-value="{esc(quad["t"])}"/>'
        )
    parts.extend(labels)

    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" class="scene-svg" '
        f'aria-label="Three dimensional surface of the 20 °C isotherm depth">'
        f"<title>Thermocline depth surface</title>"
        f"<desc>Rotatable surface showing the depth of the 20 degree Celsius isotherm "
        f"across longitude and latitude in the equatorial Pacific.</desc>"
        f'{"".join(parts)}</svg>'
    )


# --- the oscillator through time --------------------------------------------
def phase_spiral(state, width: int = 620, height: int = 430) -> str:
    """(SST, heat content, time): the recharge loop pulled apart along time."""
    sub = state.subsurface
    if not sub or len(sub.trajectory) < 24:
        return ""
    track = sub.trajectory[-72:]

    def stats(values):
        mean = sum(values) / len(values)
        spread = (sum((v - mean) ** 2 for v in values) / max(len(values) - 1, 1)) ** 0.5
        return mean, spread or 1.0

    sst_mean, sst_sd = stats([p.sst for p in track])
    heat_mean, heat_sd = stats([p.heat for p in track])
    limit = 2.6

    points = []
    for index, point in enumerate(track):
        label = point.when.strftime("%Y-%m")
        x = max(-limit, min(limit, (point.sst - sst_mean) / sst_sd)) / limit
        y = max(-limit, min(limit, (point.heat - heat_mean) / heat_sd)) / limit
        z = index / max(len(track) - 1, 1) * 2.0 - 1.0
        points.append({
            "p": [round(x, 4), round(y, 4), round(z, 4)],
            "t": f"{label}: Nino-3.4 {point.sst:+.2f} °C, WWV {point.heat:+.2f} × 10¹⁴ m³",
            "label": label,
        })

    axes: list[dict] = []
    for level in (-1.0, 0.0, 1.0):
        axes.append({"kind": "line", "p": [[-1, -1, level], [1, -1, level]]})
        axes.append({"kind": "line", "p": [[-1, -1, level], [-1, 1, level]]})
        axes.append({"kind": "line", "p": [[1, -1, level], [1, 1, level]]})
        axes.append({"kind": "line", "p": [[-1, 1, level], [1, 1, level]]})
    for corner in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
        axes.append({"kind": "line",
                     "p": [[corner[0], corner[1], -1], [corner[0], corner[1], 1]]})
    years = sorted({p["label"][:4] for p in points})
    for year in years:
        first = next(p for p in points if p["label"][:4] == year)
        axes.append({"kind": "text",
                     "p": [[-1.22, -1.0, first["p"][2]]], "t": year})
    axes.append({"kind": "text", "p": [[0, -1.3, -1.12]], "t": "warm ->"})
    axes.append({"kind": "text", "p": [[-1.34, 0, -1.12]], "t": "recharged ->"})

    payload = {"line": points, "axes": axes, "yaw": -50.0, "pitch": 20.0,
               "w": width, "h": height, "kind": "line"}
    body = _render_line_scene(payload, -50.0, 20.0, width, height)

    rows = [
        [p["label"], f"{track[i].sst:+.2f}", f"{track[i].heat:+.2f}"]
        for i, p in enumerate(points)
    ][::-1][:36]

    return f"""<section class="card" id="phase-spiral">
  <h2>Six years of the oscillator, unrolled</h2>
  <p class="caption">The same recharge loop as the phase panel, with time as the third
    axis so successive orbits stop overlapping. A healthy oscillation is a regular
    corkscrew; an event that is still growing shows orbits widening as they climb.
    Both horizontal axes are standardised over the window shown.
    <span class="hint">Drag to rotate. Use the buttons for fixed views.</span></p>
  <div class="scene" data-scene='{esc(json.dumps(payload, separators=(",", ":")))}'>
    <div class="viewbtns">
      <button type="button" data-view="-50,20">Oblique</button>
      <button type="button" data-view="0,90">Phase plane only</button>
      <button type="button" data-view="0,0">SST against time</button>
      <button type="button" data-view="-90,0">Heat against time</button>
    </div>
    <div class="chart">{body}</div>
  </div>
  {table('phase trajectory, newest first',
         ['month', 'Nino-3.4 anomaly (°C)', 'warm water volume anomaly'], rows)}
</section>"""


def _render_line_scene(payload, yaw, pitch, width, height) -> str:
    scale, cx, cy = fit_view(_cloud(payload), width, height, yaw, pitch)
    parts = []
    labels = []
    for item in payload["axes"]:
        points = [project(*p, yaw, pitch) for p in item["p"]]
        if item["kind"] == "line":
            (x0, y0, _), (x1, y1, _) = points
            parts.append(
                f'<line x1="{cx + x0 * scale:.1f}" y1="{cy + y0 * scale:.1f}" '
                f'x2="{cx + x1 * scale:.1f}" y2="{cy + y1 * scale:.1f}" '
                f'stroke="var(--grid)" stroke-width="1"/>'
            )
        else:
            x, y, _ = _nearer(item, points[0], yaw, pitch)
            labels.append(
                f'<text x="{cx + x * scale:.1f}" y="{cy + y * scale:.1f}" '
                f'text-anchor="middle" class="tick scenetick">{esc(item["t"])}</text>'
            )

    projected = [project(*p["p"], yaw, pitch) for p in payload["line"]]
    # A dropped shadow on the floor: the single cheapest cue for reading depth
    # in an orthographic projection.
    shadow = [project(p["p"][0], p["p"][1], -1.0, yaw, pitch) for p in payload["line"]]
    parts.append(
        '<path d="M' + " L".join(
            f"{cx + x * scale:.1f} {cy + y * scale:.1f}" for x, y, _ in shadow
        ) + '" fill="none" stroke="var(--muted)" stroke-width="1" opacity="0.35"/>'
    )
    parts.append(
        '<path d="M' + " L".join(
            f"{cx + x * scale:.1f} {cy + y * scale:.1f}" for x, y, _ in projected
        ) + '" fill="none" stroke="var(--s1)" stroke-width="2.2" '
        'stroke-linejoin="round" stroke-linecap="round"/>'
    )
    for index, (x, y, _) in enumerate(projected):
        if index % 6 and index != len(projected) - 1:
            continue
        last = index == len(projected) - 1
        parts.append(
            f'<circle cx="{cx + x * scale:.1f}" cy="{cy + y * scale:.1f}" '
            f'r="{5.5 if last else 3.2}" fill="{"var(--s2)" if last else "var(--s1)"}" '
            f'stroke="var(--surface)" stroke-width="1.5" class="hit" '
            f'data-label="{esc(payload["line"][index]["label"])}" '
            f'data-value="{esc(payload["line"][index]["t"])}"/>'
        )
    last_x, last_y, _ = projected[-1]
    parts.append(
        f'<text x="{cx + last_x * scale + 9:.1f}" y="{cy + last_y * scale + 4:.1f}" '
        f'class="pointlabel">now</text>'
    )
    parts.extend(labels)
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" class="scene-svg" '
        f'aria-label="Three dimensional phase trajectory">'
        f"<title>Recharge oscillator through time</title>"
        f"<desc>A three dimensional trajectory of sea surface temperature anomaly "
        f"against warm water volume anomaly, with time on the third axis.</desc>"
        f'{"".join(parts)}</svg>'
    )


SCENE_JS = r"""
(function () {
  function project(p, yaw, pitch) {
    var a = yaw * Math.PI / 180, b = pitch * Math.PI / 180;
    var xr = p[0] * Math.cos(a) - p[1] * Math.sin(a);
    var yr = p[0] * Math.sin(a) + p[1] * Math.cos(a);
    return [xr, -(p[2] * Math.cos(b) - yr * Math.sin(b)),
            yr * Math.cos(b) + p[2] * Math.sin(b)];
  }
  function esc(s) {
    return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }
  // Same cloud, same fitted scale, same centring rule as the server render:
  // the first client redraw has to land exactly on top of the picture that
  // shipped in the HTML, or the scene jumps the moment you touch it.
  function cloud(data) {
    var pts = [], i, j;
    for (i = 0; i < data.axes.length; i++) {
      for (j = 0; j < data.axes[i].p.length; j++) { pts.push(data.axes[i].p[j]); }
      if (data.axes[i].alt) {
        for (j = 0; j < data.axes[i].alt.length; j++) { pts.push(data.axes[i].alt[j]); }
      }
    }
    if (data.kind === 'line') {
      for (i = 0; i < data.line.length; i++) {
        var q = data.line[i].p;
        pts.push(q); pts.push([q[0], q[1], -1]);
      }
    } else {
      for (i = 0; i < data.quads.length; i++) {
        for (j = 0; j < data.quads[i].p.length; j++) { pts.push(data.quads[i].p[j]); }
      }
    }
    return pts;
  }
  function fitView(pts, w, h, yaw, pitch) {
    var pad = 18;
    var minx = Infinity, maxx = -Infinity, miny = Infinity, maxy = -Infinity;
    for (var i = 0; i < pts.length; i++) {
      var s = project(pts[i], yaw, pitch);
      if (s[0] < minx) { minx = s[0]; } if (s[0] > maxx) { maxx = s[0]; }
      if (s[1] < miny) { miny = s[1]; } if (s[1] > maxy) { maxy = s[1]; }
    }
    var spanx = Math.max(maxx - minx, 1e-6), spany = Math.max(maxy - miny, 1e-6);
    var scale = Math.min((w - 2 * pad) / spanx, (h - 2 * pad) / spany);
    return [scale, w / 2 - (minx + maxx) / 2 * scale,
            h / 2 - (miny + maxy) / 2 * scale];
  }
  function draw(scene, data, yaw, pitch) {
    var w = data.w, h = data.h;
    var fit = fitView(cloud(data), w, h, yaw, pitch);
    var scale = fit[0], cx = fit[1], cy = fit[2];
    var out = [], labels = [];
    for (var i = 0; i < data.axes.length; i++) {
      var item = data.axes[i];
      if (item.kind === 'line') {
        var p0 = project(item.p[0], yaw, pitch), p1 = project(item.p[1], yaw, pitch);
        out.push('<line x1="' + (cx + p0[0] * scale).toFixed(1) + '" y1="' +
          (cy + p0[1] * scale).toFixed(1) + '" x2="' + (cx + p1[0] * scale).toFixed(1) +
          '" y2="' + (cy + p1[1] * scale).toFixed(1) +
          '" stroke="var(--grid)" stroke-width="1"/>');
      } else {
        var t = project(item.p[0], yaw, pitch);
        if (item.alt) {
          var other = project(item.alt[0], yaw, pitch);
          if (other[2] > t[2]) { t = other; }
        }
        labels.push('<text x="' + (cx + t[0] * scale).toFixed(1) + '" y="' +
          (cy + t[1] * scale).toFixed(1) +
          '" text-anchor="middle" class="tick scenetick">' + esc(item.t) + '</text>');
      }
    }
    if (data.kind === 'line') {
      var pts = [], shadow = [];
      for (var k = 0; k < data.line.length; k++) {
        var q = data.line[k].p;
        var pp = project(q, yaw, pitch), sp = project([q[0], q[1], -1], yaw, pitch);
        pts.push(pp); shadow.push(sp);
      }
      out.push('<path d="M' + shadow.map(function (p) {
        return (cx + p[0] * scale).toFixed(1) + ' ' + (cy + p[1] * scale).toFixed(1);
      }).join(' L') + '" fill="none" stroke="var(--muted)" stroke-width="1" opacity="0.35"/>');
      out.push('<path d="M' + pts.map(function (p) {
        return (cx + p[0] * scale).toFixed(1) + ' ' + (cy + p[1] * scale).toFixed(1);
      }).join(' L') + '" fill="none" stroke="var(--s1)" stroke-width="2.2" ' +
        'stroke-linejoin="round" stroke-linecap="round"/>');
      for (var m = 0; m < pts.length; m++) {
        var last = m === pts.length - 1;
        if (m % 6 && !last) { continue; }
        out.push('<circle cx="' + (cx + pts[m][0] * scale).toFixed(1) + '" cy="' +
          (cy + pts[m][1] * scale).toFixed(1) + '" r="' + (last ? 5.5 : 3.2) +
          '" fill="' + (last ? 'var(--s2)' : 'var(--s1)') +
          '" stroke="var(--surface)" stroke-width="1.5" class="hit" data-label="' +
          esc(data.line[m].label) + '" data-value="' + esc(data.line[m].t) + '"/>');
      }
      var lastp = pts[pts.length - 1];
      out.push('<text x="' + (cx + lastp[0] * scale + 9).toFixed(1) + '" y="' +
        (cy + lastp[1] * scale + 4).toFixed(1) + '" class="pointlabel">now</text>');
    } else {
      var quads = data.quads.map(function (q) {
        var pp = q.p.map(function (p) { return project(p, yaw, pitch); });
        var d = (pp[0][2] + pp[1][2] + pp[2][2] + pp[3][2]) / 4;
        return { pp: pp, d: d, c: q.c, t: q.t };
      });
      quads.sort(function (a, b) { return a.d - b.d; });
      for (var n = 0; n < quads.length; n++) {
        var pts2 = quads[n].pp.map(function (p) {
          return (cx + p[0] * scale).toFixed(1) + ',' + (cy + p[1] * scale).toFixed(1);
        }).join(' ');
        out.push('<polygon points="' + pts2 + '" fill="var(--' + quads[n].c +
          ')" stroke="var(--surface)" stroke-width="0.5" class="hit" ' +
          'data-label="20 °C isotherm" data-value="' + esc(quads[n].t) + '"/>');
      }
    }
    var svg = scene.querySelector('svg');
    if (svg) { svg.innerHTML = svg.querySelector('title').outerHTML +
      svg.querySelector('desc').outerHTML + out.join('') + labels.join(''); }
  }

  var scenes = document.querySelectorAll('.scene');
  for (var i = 0; i < scenes.length; i++) {
    (function (scene) {
      var data;
      try { data = JSON.parse(scene.getAttribute('data-scene')); } catch (e) { return; }
      var yaw = data.yaw, pitch = data.pitch, dragging = false, lx = 0, ly = 0;
      function redraw() { draw(scene, data, yaw, pitch); }
      function start(x, y) { dragging = true; lx = x; ly = y; scene.classList.add('grabbing'); }
      function move(x, y) {
        if (!dragging) { return; }
        yaw -= (x - lx) * 0.55;
        pitch = Math.max(-89, Math.min(89, pitch + (y - ly) * 0.45));
        lx = x; ly = y; redraw();
      }
      function end() { dragging = false; scene.classList.remove('grabbing'); }
      scene.addEventListener('mousedown', function (e) { start(e.clientX, e.clientY); e.preventDefault(); });
      window.addEventListener('mousemove', function (e) { move(e.clientX, e.clientY); });
      window.addEventListener('mouseup', end);
      scene.addEventListener('touchstart', function (e) {
        if (e.touches.length === 1) { start(e.touches[0].clientX, e.touches[0].clientY); }
      }, { passive: true });
      scene.addEventListener('touchmove', function (e) {
        if (e.touches.length === 1 && dragging) {
          move(e.touches[0].clientX, e.touches[0].clientY);
          e.preventDefault();
        }
      }, { passive: false });
      scene.addEventListener('touchend', end);
      var buttons = scene.querySelectorAll('.viewbtns button');
      for (var b = 0; b < buttons.length; b++) {
        buttons[b].addEventListener('click', function () {
          var parts = this.getAttribute('data-view').split(',');
          yaw = parseFloat(parts[0]); pitch = parseFloat(parts[1]);
          for (var c = 0; c < buttons.length; c++) {
            buttons[c].setAttribute('aria-pressed', buttons[c] === this ? 'true' : 'false');
          }
          redraw();
        });
      }
    })(scenes[i]);
  }
})();
"""
