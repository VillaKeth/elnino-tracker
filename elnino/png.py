"""Indexed PNG pictures, written with the standard library alone.

A field drawn as a picture is tens of thousands of cells in a dozen colours.
As an indexed PNG, a palette and a few bits a cell, deflated, it is some
kilobytes; the same cells drawn as SVG paths were megabytes.
"""

from __future__ import annotations

import re
import struct
import zlib

_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_COLOUR = re.compile(r"#[0-9a-fA-F]{6}")


def _chunk(kind: bytes, body: bytes) -> bytes:
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))


def indexed(width: int, height: int, rows, palette, transparent: int | None = None) -> bytes:
    """A PNG of width by height pixels, each the index into palette given in
    rows, the top row first and each row left to right. palette holds one to
    256 "#rrggbb" colours; the one at index transparent, if any, is seen
    through. A pixel takes the fewest bits that hold the palette, and each line
    goes unfiltered, as the PNG specification advises for a palette."""
    if not 0 < len(palette) <= 256:
        raise ValueError(f"a palette holds 1 to 256 colours, not {len(palette)}")
    if not all(isinstance(c, str) and _COLOUR.fullmatch(c) for c in palette):
        raise ValueError("a palette's colours are written #rrggbb")
    if transparent is not None and not 0 <= transparent < len(palette):
        raise ValueError(f"index {transparent} is not in a palette of {len(palette)}")
    rows = [list(row) for row in rows]
    if width < 1 or height < 1 or len(rows) != height or any(len(row) != width for row in rows):
        raise ValueError(f"the rows are not {width} pixels by {height}")
    depth = next(bits for bits in (1, 2, 4, 8) if len(palette) <= 1 << bits)
    per = 8 // depth
    lines = bytearray()
    for row in rows:
        if not all(isinstance(i, int) and 0 <= i < len(palette) for i in row):
            raise ValueError(f"a pixel's index is not in a palette of {len(palette)}")
        lines.append(0)
        for start in range(0, width, per):
            byte = 0
            for k, index in enumerate(row[start:start + per]):
                byte |= index << (8 - depth * (k + 1))
            lines.append(byte)
    out = [_SIGNATURE,
           _chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, depth, 3, 0, 0, 0)),
           _chunk(b"PLTE", b"".join(bytes.fromhex(c[1:]) for c in palette))]
    if transparent is not None:
        out.append(_chunk(b"tRNS", bytes([255] * transparent + [0])))
    out.append(_chunk(b"IDAT", zlib.compress(bytes(lines), 9)))
    out.append(_chunk(b"IEND", b""))
    return b"".join(out)
