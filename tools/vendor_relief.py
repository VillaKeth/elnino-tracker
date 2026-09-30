"""Vendor the solid Earth: ETOPO1 topography and bathymetry, once, into source.

The atlas draws a composite over a shape, and until now the shape was a
coastline - a line with nothing inside it. That is enough to say *where* a
rainfall difference lands and useless for saying *what it lands on*. A
teleconnection that dries the Maritime Continent is a different event over the
Sunda Shelf than over the Barisan range, and the map should be able to show the
difference without asking the reader to already know it.

So: ETOPO1, NOAA's one-arc-minute global relief, sampled to a quarter degree
and written into ``elnino/relief.py`` as a PNG.

A PNG rather than a text grid because the numbers are the wrong shape for text.
A quarter-degree world is 721 x 1441 = 1,038,961 elevations; as decimal digits
that is four megabytes of source that Python must parse at import. As a PNG it
is a fifth of that, the browser decodes it in hardware on the way into a
canvas, and Python gets it back with ``zlib.decompress`` and a subtraction,
because we chose the filter.

The encoding is two stacked greyscale planes, high byte over low byte, rather
than one 16-bit image. Canvas ``getImageData`` hands back eight bits a channel
whatever the source depth, so a 16-bit PNG would arrive in the browser already
rounded; split into two 8-bit planes it arrives exact. Stacking them also puts
each plane's bytes next to each other for DEFLATE, and the high plane - which
is the elevation to within 256 metres - is nearly flat over an ocean basin.

Run::

    python tools/vendor_relief.py

It writes ``elnino/relief.py``. Regenerate it when ETOPO does, which is roughly
never, not on a schedule.
"""

from __future__ import annotations

import base64
import datetime as dt
import ssl
import struct
import sys
import urllib.request
import zlib

AGENT = {"User-Agent": "elnino-tracker/2.0 (+personal ENSO monitoring)"}
CTX = ssl.create_default_context()

# NOAA CoastWatch's ERDDAP, which serves ETOPO1 over OPeNDAP with server-side
# striding. Striding on the server is the whole point: the full grid is 233
# million values and we want one in 225 of them.
ERDDAP = "https://coastwatch.pfeg.noaa.gov/erddap/griddap/etopo180"

SOURCE_NY = 10801       # ETOPO1 rows, -90 to +90 at one arc-minute
SOURCE_NX = 21601       # ETOPO1 columns, -180 to +180
STRIDE = 15             # -> 0.25 degrees
ROWS_PER_REQUEST = 60   # about 350 kB a request, 13 requests for the world

OFFSET = 11000          # added before packing, so the deepest trench is positive
DEEPEST = -11000        # anything below this is not on this planet
HIGHEST = 9000


def get(url: str, tries: int = 4) -> bytes:
    last: Exception | None = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=AGENT)
            with urllib.request.urlopen(req, timeout=300, context=CTX) as r:
                return r.read()
        except Exception as exc:                      # noqa: BLE001
            last = exc
            print(f"  retry {attempt + 1}: {type(exc).__name__}", file=sys.stderr)
    raise RuntimeError(f"{url}: {last}")


def dods_ints(body: bytes, expected: int) -> list[int]:
    """The array out of a DAP2 binary response.

    The payload is a readable DDS, then ``Data:`` on its own line, then the
    array: its length as a big-endian uint32 written twice, then one 32-bit
    word per element. Int16 travels in 32 bits because DAP2 has no narrower
    wire type, which is wasteful and is still a twentieth of the same numbers
    as CSV. The coordinate maps follow and are not read - the axes of a
    strided subset are arithmetic, and the first chunk checks that claim
    against the maps rather than trusting it.
    """
    mark = body.find(b"Data:\n")
    if mark < 0:
        raise RuntimeError("no data section in DAP2 response")
    data = body[mark + 6:]
    count, again = struct.unpack_from(">II", data, 0)
    if count != again or count != expected:
        raise RuntimeError(f"length {count}/{again}, expected {expected}")
    words = struct.unpack_from(f">{count}i", data, 8)
    return list(words)


def dods_floats(body: bytes, after: int) -> list[float]:
    """The first Float64 map that follows ``after`` elements of the array."""
    mark = body.find(b"Data:\n") + 6
    start = mark + 8 + 4 * after
    count, again = struct.unpack_from(">II", body, start)
    if count != again:
        raise RuntimeError("map length mismatch")
    return list(struct.unpack_from(f">{count}d", body, start + 8))


def fetch() -> list[list[int]]:
    """The strided grid, south to north, west to east."""
    rows: list[list[int]] = []
    width = len(range(0, SOURCE_NX, STRIDE))
    starts = list(range(0, SOURCE_NY, STRIDE * ROWS_PER_REQUEST))
    for number, first in enumerate(starts, 1):
        last = min(first + STRIDE * (ROWS_PER_REQUEST - 1), SOURCE_NY - 1)
        last -= (last - first) % STRIDE
        query = f"altitude[{first}:{STRIDE}:{last}][0:{STRIDE}:{SOURCE_NX - 1}]"
        print(f"  block {number}/{len(starts)}: rows {first}-{last}")
        body = get(f"{ERDDAP}.dods?{query}")
        height = len(range(first, last + 1, STRIDE))
        flat = dods_ints(body, height * width)
        if number == 1:
            check_axes(body, height * width, height, width)
        rows.extend(flat[r * width:(r + 1) * width] for r in range(height))
    return rows


def check_axes(body: bytes, after: int, height: int, width: int) -> None:
    """Confirm the strided axis is the arithmetic one we are going to assume."""
    lats = dods_floats(body, after)
    if len(lats) != height:
        raise RuntimeError(f"latitude map is {len(lats)}, expected {height}")
    for index, value in enumerate(lats):
        if abs(value - (-90.0 + 0.25 * index)) > 1e-6:
            raise RuntimeError(f"latitude {index} is {value}, not arithmetic")
    print(f"  axes check: {height} latitudes from {lats[0]} step 0.25, "
          f"{width} longitudes assumed to match")


def png_planes(rows: list[list[int]]) -> bytes:
    """Two stacked greyscale planes, PNG, filtered with Up throughout.

    Up (filter 2) on every row rather than the usual per-row adaptive choice,
    because the decoder on the Python side is ours and a single filter makes it
    four lines instead of forty. Adaptive filtering wins a few percent on a
    relief field and costs that clarity, which is a bad trade for a file that
    is written once.
    """
    height, width = len(rows), len(rows[0])
    packed = [[max(0, min(65535, value + OFFSET)) for value in row]
              for row in rows]
    planes = ([bytes(value >> 8 for value in row) for row in packed]
              + [bytes(value & 255 for value in row) for row in packed])

    raw = bytearray()
    previous = bytes(width)
    for line in planes:
        raw.append(2)
        raw.extend((line[i] - previous[i]) & 255 for i in range(width))
        previous = line

    def chunk(kind: bytes, payload: bytes) -> bytes:
        return (struct.pack(">I", len(payload)) + kind + payload
                + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, 2 * height, 8, 0, 0, 0, 0)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", header)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
            + chunk(b"IEND", b""))


def stats(rows: list[list[int]]) -> dict:
    flat = [value for row in rows for value in row]
    land = [value for value in flat if value > 0]
    sea = [value for value in flat if value <= 0]
    return {
        "cells": len(flat),
        "min": min(flat),
        "max": max(flat),
        "land_fraction": round(len(land) / len(flat), 4),
        "mean_land_m": round(sum(land) / len(land)),
        "mean_sea_m": round(sum(sea) / len(sea)),
    }


HEAD = '''"""Vendored global relief: ETOPO1 topography and bathymetry at 0.25 degrees.

Generated by ``tools/vendor_relief.py``; do not edit by hand.

One elevation in metres for every quarter-degree cell of the planet, sea floor
included - {cells:,} of them, from {low:,} m to {high:,} m. Land is
{land:.1%} of the cells. It is here so the atlas can draw what a composite
lands on rather than only where it lands, and so a click can answer how high
the ground under it is when there is no network to ask.

Storage is a PNG, described at length in the generator. Briefly: two stacked
greyscale planes, high byte above low byte, elevation biased by {offset} so the
Mariana Trench is a positive number. The browser decodes it with its own PNG
decoder into a canvas and reads the bytes back exactly, because eight-bit
planes survive ``getImageData`` and a 16-bit image would not. Python decodes it
with :func:`grid`, which is ``zlib.decompress`` and one subtraction a byte,
since the file was written with a single filter type on purpose.

    source     ETOPO1 ice-surface global relief, NOAA NCEI, 1 arc-minute
    served by  ERDDAP at NOAA CoastWatch, subset and strided on the server
    sampled    every 15th point, so 0.25 deg; {ny} latitudes, {nx} longitudes
    vendored   {when}

Latitudes run south to north from -90.0, longitudes west to east from -180.0,
both in steps of 0.25. The axes are arithmetic and the generator checks that
against the coordinate maps the server sends rather than assuming it.
"""

from __future__ import annotations

import base64
import zlib

LAT0 = -90.0
LON0 = -180.0
STEP = 0.25
NY = {ny}
NX = {nx}
OFFSET = {offset}
UNIT = "m"
SOURCE = "ETOPO1 ice-surface relief, NOAA NCEI, via ERDDAP at NOAA CoastWatch"
VENDORED = "{when}"
STATS = {stats!r}

_GRID: tuple[tuple[int, ...], ...] | None = None


def png() -> str:
    """The relief as a data URI, for an ``<img>`` in a self-contained page."""
    return "data:image/png;base64," + PNG


def grid() -> tuple[tuple[int, ...], ...]:
    """Elevations in metres, south to north, west to east, memoized.

    The PNG was written with filter type 2 - Up - on every row, so undoing it
    is a running addition down each column and nothing else. That is the whole
    reason the generator declines adaptive filtering.
    """
    global _GRID
    if _GRID is not None:
        return _GRID
    raw = base64.b64decode(PNG)
    at, chunks = 8, []
    while at < len(raw):
        size = int.from_bytes(raw[at:at + 4], "big")
        kind = raw[at + 4:at + 8]
        if kind == b"IDAT":
            chunks.append(raw[at + 8:at + 8 + size])
        at += 12 + size
    data = zlib.decompress(b"".join(chunks))

    stride = NX + 1
    planes: list[list[int]] = []
    previous = bytes(NX)
    for line in range(2 * NY):
        row = bytearray(data[line * stride + 1:(line + 1) * stride])
        for column in range(NX):
            row[column] = (row[column] + previous[column]) & 255
        previous = bytes(row)
        planes.append(list(row))

    _GRID = tuple(
        tuple((planes[y][x] << 8 | planes[NY + y][x]) - OFFSET
              for x in range(NX))
        for y in range(NY)
    )
    return _GRID


def at(lon: float, lat: float) -> int:
    """Elevation in metres at a point, nearest cell, longitude wrapped."""
    while lon < -180.0:
        lon += 360.0
    while lon >= 180.0:
        lon -= 360.0
    y = min(NY - 1, max(0, round((lat - LAT0) / STEP)))
    x = min(NX - 1, max(0, round((lon - LON0) / STEP)))
    return grid()[y][x]


PNG = "\\
'''


def main() -> None:
    print("ETOPO1 -> elnino/relief.py")
    rows = fetch()
    print(f"  grid {len(rows)} x {len(rows[0])}")
    summary = stats(rows)
    print(f"  {summary}")

    blob = png_planes(rows)
    print(f"  png {len(blob):,} bytes "
          f"({len(blob) / summary['cells']:.2f} bytes a cell)")
    text = base64.b64encode(blob).decode("ascii")

    head = HEAD.format(
        cells=summary["cells"], low=summary["min"], high=summary["max"],
        land=summary["land_fraction"], ny=len(rows), nx=len(rows[0]),
        offset=OFFSET, when=dt.date.today().isoformat(), stats=summary,
    )
    body = "\n".join(text[i:i + 96] + "\\" for i in range(0, len(text), 96))
    with open("elnino/relief.py", "w", encoding="utf-8", newline="\n") as fh:
        fh.write(head)
        fh.write(body[:-1])     # the last line carries no continuation
        fh.write('"\n')
    print(f"  wrote elnino/relief.py, {len(head) + len(body):,} bytes")


if __name__ == "__main__":
    main()
