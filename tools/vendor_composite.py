"""Build the vendored ENSO composite grids.

Run once. Writes ``elnino/composite.py``, which the tracker imports; after that
nothing in the render path touches the network, exactly as with the coastline.

What a composite is
-------------------
A teleconnection is not a forecast, it is a shift in a seasonal distribution.
The honest way to state it is to take every month in the satellite record that
belonged to a real El Nino, average the field over those months, average the
same field over the months that belonged to neither phase, and subtract. What
comes out is "when El Nino has been running, this is how this place has
differed from an ordinary year" - which is the only claim the historical record
actually supports, and it is a claim about a place rather than about a region.

Two fields:

    precip   GPCP v2.3 monthly, 2.5 degrees, 1979-present. Global, ocean and
             land, and the dataset the teleconnection literature is written on.
    air      GHCN-CAMS monthly surface air temperature, native 0.5 degrees,
             taken at a stride of 4 (2 degrees). Land only by construction.

Both are composited by season rather than by month, because a teleconnection
is a seasonal signal and a single month of a 2.5 degree precipitation field is
mostly weather.

Thresholds
----------
Phase is read from RONI, the official index since February 2026 (NWS PIS
26-05), so an "El Nino month" here is one the tracker itself would call one.
El Nino months are RONI >= +1.0 rather than >= +0.5. The weak-event tail is
where the teleconnection is least reliable, and a composite is a statement
about the events people are worried about. Neutral is |RONI| < 0.5, which is
NOAA's own definition of neither phase. La Nina months are excluded from both
sides rather than folded into the baseline: they are not an ordinary year.

An El Nino still under way when the index ends is excluded too. The composite
is what past events did; the event in progress is the one it is being read to
anticipate, and composited it would be partly describing itself.

Significance
------------
The unit of each sample is a season, not a month. An event contributes the
mean of its El Nino months in the season and a neutral year the mean of its
neutral months, because the months inside one event share one ocean and are
not independent draws: counted as if they were, the degrees of freedom were
overstated about threefold and cells the record cannot separate from an
ordinary year were coloured as if it could.

Welch's t is computed per cell from those two samples, and each season carries
``t_crit``, the two-sided 95% point of Student's t at the smaller sample's
degrees of freedom - the conservative end of Welch's range. A renderer uses it
to withhold cells where the difference is inside the noise, instead of drawing
a confident colour over a number that is one wet season away from changing
sign.
"""

from __future__ import annotations

import io
import math
import ssl
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "elnino" / "composite.py"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# The index is read the way CPC prints it, one decimal with ties away from
# zero, because that is how the tracker classifies: RONI AMJ 2026 was +0.49,
# printed +0.5, and the tracker's event began there.
from elnino.classify import displayed  # noqa: E402

PSL = "https://psl.noaa.gov/thredds/dodsC/Datasets"
INDEX_URL = "https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt"
AGENT = {"User-Agent": "elnino-tracker/2.0 (+personal ENSO monitoring)"}
CTX = ssl.create_default_context()

WARM = 1.0     # RONI at or above this is a composited El Nino month
NEUTRAL = 0.5  # RONI strictly inside +/- this is a baseline month
MISSING = -1e30
MIN_EVENTS = 3   # fewer El Ninos than this in a season is an anecdote
MIN_YEARS = 6    # and fewer neutral years than this is not a baseline

# Two-sided 95% points of Student's t by degrees of freedom, from the table.
T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447,
        7: 2.365, 8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179,
        13: 2.160, 14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101,
        19: 2.093, 20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064,
        25: 2.060, 26: 2.056, 27: 2.052, 28: 2.048, 29: 2.045, 30: 2.042}

SEASONS = {
    "DJF": (12, 1, 2),
    "MAM": (3, 4, 5),
    "JJA": (6, 7, 8),
    "SON": (9, 10, 11),
}


def get(url: str, tries: int = 4) -> str:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=AGENT)
            with urllib.request.urlopen(req, timeout=180, context=CTX) as r:
                return r.read().decode("utf-8", "replace")
        except Exception as exc:                      # noqa: BLE001
            last = exc
            print(f"  retry {attempt + 1}: {type(exc).__name__}", file=sys.stderr)
    raise RuntimeError(f"{url}: {last}")


# --- the phase record --------------------------------------------------------

def index_months() -> dict[tuple[int, int], float]:
    """RONI keyed by (year, month), from CPC's seasonal file.

    The file is seasonal: a row labelled ``DJF 2016`` is centred on January
    2016. The centre month is what the value is assigned to, which is how NOAA
    defines the index and how every event table is built from it. The anomaly
    is the last column, which is where both the RONI and the ONI files keep it.
    """
    text = get(INDEX_URL)
    centre = {"DJF": 1, "JFM": 2, "FMA": 3, "MAM": 4, "AMJ": 5, "MJJ": 6,
              "JJA": 7, "JAS": 8, "ASO": 9, "SON": 10, "OND": 11, "NDJ": 12}
    out: dict[tuple[int, int], float] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) < 3 or parts[0] not in centre:
            continue
        try:
            year, anom = int(parts[1]), float(parts[-1])
        except ValueError:
            continue
        out[(year, centre[parts[0]])] = anom
    return out


def ongoing(index: dict[tuple[int, int], float]) -> set[tuple[int, int]]:
    """The months of an El Nino still under way when the index ends.

    Walked back from the last month while the index stays at or above the
    neutral bound. In September 2026 these were May to July 2026, and the JJA
    composite of "what past El Ninos did" had been holding June and July of
    the event it was being read to anticipate.
    """
    out: set[tuple[int, int]] = set()
    for key in sorted(index, reverse=True):
        if displayed(index[key]) < NEUTRAL:
            break
        out.add(key)
    return out


def t_critical(df: int) -> float:
    """Two-sided 95% Student's t. Past thirty degrees of freedom the table's
    last row, which errs on the strict side of the 1.96 it tends to."""
    return T975[min(max(df, 1), 30)]


def phase(index: dict[tuple[int, int], float], year: int, month: int) -> str:
    """``warm``, ``base`` or ``skip`` for one calendar month."""
    value = index.get((year, month))
    if value is None:
        return "skip"
    value = displayed(value)
    if value >= WARM:
        return "warm"
    if abs(value) < NEUTRAL:
        return "base"
    return "skip"


# --- OPeNDAP -----------------------------------------------------------------

def parse_ascii(body: str, want: str) -> tuple[list[list[list[float]]], int, int]:
    """Parse an OPeNDAP ASCII Grid into ``[time][lat][lon]``.

    The payload is a header, a dashed rule, then one line per (time, lat) row
    of the form ``[t][y], v, v, v, ...`` followed by the coordinate MAPS. Rows
    are keyed by their own bracketed index rather than by position, because a
    server is free to reorder them and a silent transpose here would be a map
    of the wrong planet.
    """
    _, _, tail = body.partition("-" * 20)
    rows: dict[tuple[int, int], list[float]] = {}
    for line in tail.splitlines():
        line = line.strip()
        if not line.startswith("["):
            continue
        index, _, values = line.partition(",")
        if not values:
            continue
        try:
            first, _, second = index.strip().strip("[]").partition("][")
            key = (int(first), int(second))
        except ValueError:
            continue
        rows[key] = [float(v) for v in values.split(",")]
    if not rows:
        raise RuntimeError(f"{want}: no data rows in {len(body)} bytes")
    times = max(k[0] for k in rows) + 1
    lats = max(k[1] for k in rows) + 1
    grid = [[rows[(t, y)] for y in range(lats)] for t in range(times)]
    return grid, times, lats


def fetch_block(dataset: str, var: str, start: int, stop: int,
                stride_y: int, ny: int, stride_x: int, nx: int):
    """One contiguous run of months, subset and strided on the server."""
    query = (f"{var}[{start}:1:{stop}][0:{stride_y}:{ny - 1}]"
             f"[0:{stride_x}:{nx - 1}]")
    url = f"{PSL}/{dataset}.ascii?{query}"
    grid, _, _ = parse_ascii(get(url), f"{var}[{start}:{stop}]")
    return start, grid


def axis(dataset: str, name: str) -> list[float]:
    """One coordinate variable, as a flat list.

    The payload declares the array, rules off, repeats ``name[N]`` and then
    prints the numbers. That repeated declaration is the anchor rather than the
    rule, because the rule is a run of dashes whose length is promised nowhere.
    """
    lines = get(f"{PSL}/{dataset}.ascii?{name}").splitlines()
    for index, line in enumerate(lines):
        if line.strip().startswith(f"{name}["):
            tail = lines[index + 1:]
            break
    else:
        raise RuntimeError(f"{name}: no data section")
    return [float(piece) for line in tail for piece in line.split(",")
            if piece.strip()]


def month_of(days_since_1800: float, per_day: float) -> tuple[int, int]:
    """Calendar (year, month) for a CF time value on a 1800-01-01 epoch."""
    days = days_since_1800 / per_day
    year, remaining = 1800, days
    while True:
        length = 366 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)) \
            else 365
        if remaining < length:
            break
        remaining -= length
        year += 1
    lengths = [31, 29 if (year % 4 == 0 and (year % 100 != 0 or year % 400 == 0))
               else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
    month = 1
    for length in lengths:
        if remaining < length:
            break
        remaining -= length
        month += 1
    return year, min(month, 12)


# --- compositing -------------------------------------------------------------

def composite(stack: dict[tuple[int, int], list[list[float]]],
              index: dict[tuple[int, int], float],
              ny: int, nx: int) -> dict[str, dict]:
    """Warm-minus-neutral difference and Welch's t, per season, per cell.

    Both samples are season means: one value per El Nino, one per neutral
    year. See the module docstring for why the month is not the unit.
    """
    running = ongoing(index)
    out: dict[str, dict] = {}
    for season, months in SEASONS.items():
        warm_tags: dict[int, list[tuple[int, int]]] = {}
        base_tags: dict[int, list[tuple[int, int]]] = {}
        in_progress: set[int] = set()
        for (year, month) in stack:
            if month not in months:
                continue
            # December belongs to the following year's DJF, which is what makes
            # "the 1997-98 event" one season rather than two half seasons.
            tag = year + 1 if (season == "DJF" and month == 12) else year
            if (year, month) in running:
                in_progress.add(tag)
                continue
            state = phase(index, year, month)
            if state == "warm":
                warm_tags.setdefault(tag, []).append((year, month))
            elif state == "base":
                base_tags.setdefault(tag, []).append((year, month))

        usable = len(warm_tags) >= MIN_EVENTS and len(base_tags) >= MIN_YEARS
        crit = (t_critical(min(len(warm_tags), len(base_tags)) - 1)
                if usable else None)

        def means(tags, y, x):
            values = []
            for keys in tags.values():
                cells = [stack[k][y][x] for k in keys if stack[k][y][x] > MISSING]
                if cells:
                    values.append(sum(cells) / len(cells))
            return values

        diff = [[None] * nx for _ in range(ny)]
        tstat = [[None] * nx for _ in range(ny)]
        base_mean = [[None] * nx for _ in range(ny)]
        for y in range(ny):
            for x in range(nx):
                if not usable:
                    continue
                warm = means(warm_tags, y, x)
                base = means(base_tags, y, x)
                if len(warm) < MIN_EVENTS or len(base) < MIN_YEARS:
                    continue
                mw = sum(warm) / len(warm)
                mb = sum(base) / len(base)
                vw = sum((v - mw) ** 2 for v in warm) / max(len(warm) - 1, 1)
                vb = sum((v - mb) ** 2 for v in base) / max(len(base) - 1, 1)
                se = math.sqrt(vw / len(warm) + vb / len(base))
                diff[y][x] = mw - mb
                tstat[y][x] = (mw - mb) / se if se > 1e-12 else 0.0
                # The ordinary year the difference is against. Without it a
                # reader has millimetres and no denominator, and -1.5 mm/day
                # is a fifth of Jakarta's wet season or three quarters of
                # Darwin's dry one.
                base_mean[y][x] = mb

        out[season] = {
            "diff": diff,
            "t": tstat,
            "base": base_mean,
            "warm_months": sum(len(keys) for keys in warm_tags.values()),
            "base_months": sum(len(keys) for keys in base_tags.values()),
            "warm_events": sorted(warm_tags),
            "base_years": len(base_tags),
            "t_crit": crit,
            "in_progress": sorted(in_progress),
        }
    return out


def encode(values: list[list[float | None]], scale: float) -> str:
    """One row per line, integers at ``scale``, ``_`` for a cell with no data.

    Plain text rather than a tuple literal for the same reason the coastline is
    text: a few hundred thousand float literals is slow to compile and large in
    the .pyc, and a split plus an int() is neither.
    """
    lines = []
    for row in values:
        lines.append(",".join("_" if v is None else str(int(round(v * scale)))
                              for v in row))
    return "\n".join(lines)


def build(dataset: str, var: str, stride: int, ny: int, nx: int,
          first: int, per_day: float, index, label: str):
    print(f"[{label}] axes")
    lats = axis(dataset, "lat")[::stride]
    lons = axis(dataset, "lon")[::stride]
    times = axis(dataset, "time")
    # Every month the dataset has from ``first`` on, rather than a count fixed
    # on the day this was first written.
    count = len(times) - first
    sy = len(lats)
    sx = len(lons)
    print(f"[{label}] {sy} x {sx} cells, {count} months from index {first}")

    blocks = [(s, min(s + 29, first + count - 1))
              for s in range(first, first + count, 30)]
    stack: dict[tuple[int, int], list[list[float]]] = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(fetch_block, dataset, var, a, b,
                               stride, ny, stride, nx) for a, b in blocks]
        for done, future in enumerate(futures, 1):
            start, grid = future.result()
            for offset, plane in enumerate(grid):
                stack[month_of(times[start + offset], per_day)] = plane
            print(f"[{label}] block {done}/{len(blocks)}")

    print(f"[{label}] {len(stack)} months, compositing")
    return lats, lons, composite(stack, index, sy, sx)


def shift(plane, offset: float):
    """One plane with a constant added, missing cells left missing."""
    if not offset:
        return plane
    return [[None if v is None else v + offset for v in row] for row in plane]


def main() -> None:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else OUT
    index = index_months()
    print(f"RONI: {len(index)} months, "
          f"{sum(1 for v in index.values() if v >= WARM)} at or above +{WARM}, "
          f"{len(ongoing(index))} in an event still under way")

    p_lats, p_lons, p_comp = build(
        "gpcp/precip.mon.mean.nc", "precip", 1, 72, 144, 0, 1.0,
        index, "precip")
    a_lats, a_lons, a_comp = build(
        "ghcncams/air.mon.mean.nc", "air", 4, 360, 720, 372, 24.0,
        index, "air")

    parts = [HEADER]
    for name, lats, lons, comp, scale, unit, base_offset in (
        ("PRECIP", p_lats, p_lons, p_comp, 100.0, "mm/day", 0.0),
        # GHCN-CAMS publishes Kelvin. A difference of Kelvin is a difference of
        # degrees Celsius, so DIFF and T need no conversion at all - which is
        # exactly why this was easy to miss. The neutral mean is an absolute
        # temperature and does need it, or a page reports an ordinary Jakarta
        # December as 300 degrees and every percentage taken against it as a
        # tenth of a percent.
        ("AIR", a_lats, a_lons, a_comp, 100.0, "degC", -273.15),
    ):
        # Not %.4g: four significant digits round 358.75 to 358.8, which is a
        # cell centre displaced by a twentieth of a degree and, worse, an axis
        # whose spacing is no longer constant - 2.4, 2.45, 2.6 in a row.
        parts.append(f'{name}_LATS = '
                     f'"{",".join(repr(round(v, 6)) for v in lats)}"\n')
        parts.append(f'{name}_LONS = '
                     f'"{",".join(repr(round(v, 6)) for v in lons)}"\n')
        parts.append(f'{name}_UNIT = "{unit}"\n')
        parts.append(f"{name}_SCALE = {scale}\n")
        meta = {s: {"warm_months": c["warm_months"],
                    "base_months": c["base_months"],
                    "warm_events": c["warm_events"],
                    "base_years": c["base_years"],
                    "t_crit": c["t_crit"],
                    "in_progress": c["in_progress"]}
                for s, c in comp.items()}
        parts.append(f"{name}_META = {meta!r}\n\n")
        for season, c in comp.items():
            parts.append(f'{name}_{season}_DIFF = """\\\n'
                         f'{encode(c["diff"], scale)}"""\n\n')
            parts.append(f'{name}_{season}_T = """\\\n'
                         f'{encode(c["t"], 100.0)}"""\n\n')
            parts.append(f'{name}_{season}_BASE = """\\\n'
                         f'{encode(shift(c["base"], base_offset), scale)}"""\n\n')
    parts.append(FOOTER)

    out.write_text("".join(parts), encoding="utf-8", newline="\n")
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


HEADER = '''"""Vendored ENSO composite grids: what El Nino has actually done where.

Generated by ``tools/vendor_composite.py``; do not edit by hand. Regenerate it
when another event has matured, not on a schedule - a composite over forty
years does not move in a month.

Each field is **the mean over El Nino seasons minus the mean over neutral
seasons**, per season, per grid cell, over the satellite record. El Nino here
is RONI >= +1.0 - the official index since February 2026 - and neutral is
|RONI| < 0.5; La Nina months are in neither sample, and nor is an El Nino
still under way when the file was built (``in_progress``). Each event
contributes one value, the mean of its El Nino months in the season, and each
neutral year one, because months inside one event are not independent.
Welch's t accompanies every cell, and each season's META carries ``t_crit``,
the two-sided 95% point of Student's t at the smaller sample's degrees of
freedom, so a renderer can decline to colour a difference that is inside the
noise. The neutral-year mean is stored beside the difference, because a
difference in millimetres a day cannot be read without the ordinary year it is
a difference from.

    precip   GPCP v2.3, 2.5 deg, 1979-present, global
    air      GHCN-CAMS surface air temperature, 2 deg, 1979-present, land only

Storage is one line per latitude row, integers at a stated scale, ``_`` for a
cell with too little data. Parsing is a split and an int, which costs a few
milliseconds at import against a second or more to compile the same numbers as
float literals.

Longitudes are 0..360 as the source publishes them. Latitudes run north to
south for precip and south to north for air, which is also as published; both
axes are stored explicitly so no consumer has to assume either.
"""

from __future__ import annotations

'''

FOOTER = '''

def _axis(text: str) -> tuple[float, ...]:
    return tuple(float(v) for v in text.split(","))


def _grid(text: str, scale: float) -> tuple[tuple[float | None, ...], ...]:
    rows = []
    for line in text.splitlines():
        rows.append(tuple(None if v == "_" else int(v) / scale
                          for v in line.split(",")))
    return tuple(rows)
'''


if __name__ == "__main__":
    main()
