"""Build the vendored monthly base of the 10 m zonal wind.

Run once. Writes ``elnino/windclim.py``, which the westerly wind events are
measured against; after that a run asks nothing more than the feed itself.

What the base is
----------------
A westerly wind event is a westerly *anomaly*, and Harrison and Vecchi (1997)
measured theirs against a monthly climatology of their own analysis,
linearly interpolated in time between the months' middles. The feed is
Remote Sensing Systems' CCMP version 2.1 near real time, over NCEP's GFS
background, and runs from January 2015 only: too short to be its own
normal. So the base is the version before it, CCMP version 2.0
over ERA-Interim, which ran from July 1987 to April 2019: its monthly means
on the very cells the feed asks, averaged by calendar month over 1991-2018,
the 28 whole years of it inside the WMO's 1991-2020 normal.

Over the 72 analysis times both versions carry in 2016-2019, the near-real-
time product's regional means ran within 0.22 m/s of version 2.0's in every
one of Harrison and Vecchi's regions, an order below their 2 m/s threshold:
the two are close enough for one to be the other's base.

The cells are every ninth of CCMP's quarter degree, 2.25 degrees apart, 14
latitudes from 14.625S to 14.625N, symmetric about the equator, by 72
longitudes from 120.125E to 279.875E. Every cell has a value, land as well as
sea: CCMP's analysis is everywhere, as Harrison and Vecchi's ECMWF analysis
was.

Storage is one line per latitude row, south to north, of integers in
hundredths of a metre a second, ``_`` for a cell some year lacks, a block per
calendar month, as ``composite.py`` keeps its grids.
"""

from __future__ import annotations

import csv
import io
import ssl
import sys
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "elnino" / "windclim.py"

ERDDAP = "https://oceanwatch.pifsc.noaa.gov/erddap/griddap/ccmp-monthly-v2-0.csv"
CELLS = "[(-14.625):9:(14.625)][(120.125):9:(279.875)]"
FIRST, LAST = 1991, 2018
SCALE = 100
AGENT = {"User-Agent": "elnino-tracker/2.0 (+personal ENSO monitoring)"}
MONTHS = ("JAN", "FEB", "MAR", "APR", "MAY", "JUN",
          "JUL", "AUG", "SEP", "OCT", "NOV", "DEC")


def get(url: str, tries: int = 4) -> str:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            request = urllib.request.Request(url, headers=AGENT)
            with urllib.request.urlopen(request, timeout=180,
                                        context=ssl.create_default_context()) as response:
                return response.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            last = exc
            print(f"  retry {attempt + 1}: {type(exc).__name__}", file=sys.stderr)
    raise RuntimeError(f"{url}: {last}")


def year(when: int) -> list[tuple[int, float, float, float | None]]:
    """A year's monthly means on the cells: (month, lat, lon, u)."""
    query = f"uwnd[({when}-01-01):1:({when}-12-31)]{CELLS}"
    text = get(f"{ERDDAP}?{urllib.parse.quote(query, safe=',:')}")
    rows = list(csv.reader(io.StringIO(text)))
    if rows[0] != ["time", "latitude", "longitude", "uwnd"]:
        raise ValueError(f"{when}: not ERDDAP's CSV: {rows[0]}")
    out = []
    for stamp, lat, lon, u in rows[2:]:
        out.append((int(stamp[5:7]), float(lat), float(lon),
                    None if u == "NaN" else float(u)))
    if len({row[0] for row in out}) != 12:
        raise ValueError(f"{when}: {len({row[0] for row in out})} months")
    return out


def main() -> None:
    sums: dict[tuple[int, float, float], list[float]] = {}
    lats: set[float] = set()
    lons: set[float] = set()
    for when in range(FIRST, LAST + 1):
        print(f"{when}", file=sys.stderr)
        for month, lat, lon, u in year(when):
            lats.add(lat)
            lons.add(lon)
            values = sums.setdefault((month, lat, lon), [])
            if u is not None:
                values.append(u)
    years = LAST - FIRST + 1
    lat_axis, lon_axis = sorted(lats), sorted(lons)
    blocks = []
    for month in range(1, 13):
        lines = []
        for lat in lat_axis:
            cells = []
            for lon in lon_axis:
                values = sums.get((month, lat, lon), [])
                cells.append(str(round(sum(values) / years * SCALE))
                             if len(values) == years else "_")
            lines.append(",".join(cells))
        blocks.append(f'U_{MONTHS[month - 1]} = """\\\n' + "\n".join(lines) + '\n"""\n')
    OUT.write_text(TEMPLATE.format(
        lats=",".join(f"{lat:g}" for lat in lat_axis),
        lons=",".join(f"{lon:g}" for lon in lon_axis),
        scale=SCALE, first=FIRST, last=LAST, years=years,
        blocks="\n".join(blocks),
        months=", ".join(f"U_{name}" for name in MONTHS),
    ), encoding="utf-8", newline="\r\n")
    print(f"wrote {OUT} ({len(lat_axis)} x {len(lon_axis)} cells)", file=sys.stderr)


TEMPLATE = '''"""Vendored monthly base of the 10 m zonal wind, for the westerly wind events.

Generated by ``tools/vendor_winds.py``; do not edit by hand. The base does
not move: regenerate it only if the feed's cells change.

Each value is CCMP version 2.0's monthly mean 10 m zonal wind (Remote Sensing
Systems' Cross-Calibrated Multi-Platform analysis, over ERA-Interim), in
m/s, positive from the west, averaged by calendar month over {first}-{last},
the {years} whole years of version 2.0 inside the WMO's 1991-2020 normal.
The cells are the feed's: every ninth of CCMP's quarter degree, latitudes
south to north, longitudes 0..360 east. Storage is one line per latitude, of
integers in hundredths, ``_`` for a cell some year lacked; parsed at import.
"""

from __future__ import annotations

PRODUCT = "CCMP version 2.0 monthly means (Remote Sensing Systems, over ERA-Interim)"
BASE = "{first}-{last}"
SCALE = {scale}.0

_LATS = "{lats}"
_LONS = "{lons}"

{blocks}

def _axis(text: str) -> tuple[float, ...]:
    return tuple(float(value) for value in text.split(","))


def _parse(block: str, cols: int) -> tuple[tuple[float | None, ...], ...]:
    """A month's block: a row of ``cols`` cells per latitude, None for a gap."""
    rows = []
    for line in block.strip().splitlines():
        cells = line.split(",")
        if len(cells) != cols:
            raise ValueError(f"a row of {{len(cells)}} cells, not {{cols}}")
        rows.append(tuple(None if cell == "_" else int(cell) / SCALE for cell in cells))
    return tuple(rows)


LATS = _axis(_LATS)
LONS = _axis(_LONS)
# MONTHLY[month][lat][lon], January first, in LATS' and LONS' order.
MONTHLY = tuple(_parse(block, len(LONS)) for block in ({months}))
'''


if __name__ == "__main__":
    main()
