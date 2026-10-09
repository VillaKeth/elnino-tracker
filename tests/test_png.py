"""Large regular fields drawn as pictures, a pixel a cell: the indexed PNGs
elnino/png.py writes, and the fields elnino/fields.py draws with them."""

from __future__ import annotations

import base64
import math
import re
import struct
import sys
import unittest
import zlib
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elnino import fields, grids, png  # noqa: E402

SIGNATURE = b"\x89PNG\r\n\x1a\n"


def decode(data: bytes) -> dict:
    """A PNG read back as far as an indexed, unfiltered, uninterlaced picture
    needs: its chunks (each checked against its CRC), its size and depth, its
    palette as "#rrggbb", its transparency and its rows of palette indices."""
    assert data[:8] == SIGNATURE, data[:8]
    at, chunks = 8, []
    while at < len(data):
        size, kind = struct.unpack(">I4s", data[at:at + 8])
        body = data[at + 8:at + 8 + size]
        crc, = struct.unpack(">I", data[at + 8 + size:at + 12 + size])
        assert zlib.crc32(kind + body) == crc, kind
        chunks.append((kind, body))
        at += 12 + size
    found = dict(chunks)
    width, height, depth, colour, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", found[b"IHDR"])
    assert (colour, compression, filtering, interlace) == (3, 0, 0, 0)
    plte = found[b"PLTE"]
    raw = zlib.decompress(b"".join(body for kind, body in chunks if kind == b"IDAT"))
    stride = (width * depth + 7) // 8
    assert len(raw) == height * (stride + 1)
    rows = []
    for r in range(height):
        line = raw[r * (stride + 1):(r + 1) * (stride + 1)]
        assert line[0] == 0, "a line is filtered"
        bits = "".join(f"{byte:08b}" for byte in line[1:])
        rows.append([int(bits[i * depth:(i + 1) * depth], 2) for i in range(width)])
    return {"kinds": [kind for kind, _ in chunks], "size": (width, height), "depth": depth,
            "palette": ["#%02x%02x%02x" % tuple(plte[i:i + 3]) for i in range(0, len(plte), 3)],
            "alpha": list(found.get(b"tRNS", b"")), "rows": rows}


class TestIndexedPng(unittest.TestCase):
    """png.indexed: a palette, and a palette index a pixel."""

    def test_a_picture_reads_back_as_the_indices_it_was_given(self):
        rows = [[0, 1, 2], [2, 1, 0]]
        got = decode(png.indexed(3, 2, rows, ("#0045af", "#e8e8e8", "#a30000")))
        self.assertEqual(got["kinds"], [b"IHDR", b"PLTE", b"IDAT", b"IEND"])
        self.assertEqual((got["size"], got["rows"]), ((3, 2), rows))
        self.assertEqual(got["palette"], ["#0045af", "#e8e8e8", "#a30000"])

    def test_a_pixel_takes_the_fewest_bits_that_hold_the_palette(self):
        # Rows of odd widths end part way through a byte.
        for colours, depth in ((2, 1), (3, 2), (4, 2), (5, 4), (12, 4), (16, 4), (17, 8), (256, 8)):
            with self.subTest(colours=colours):
                palette = ["#%06x" % (i * 65793) for i in range(colours)]
                rows = [[(r * 7 + c) % colours for c in range(5)] for r in range(3)]
                got = decode(png.indexed(5, 3, rows, palette))
                self.assertEqual((got["depth"], got["rows"], got["palette"]), (depth, rows, palette))

    def test_only_the_transparent_index_is_seen_through(self):
        got = decode(png.indexed(2, 1, [[2, 0]], ("#000000", "#ffffff", "#000000"), transparent=2))
        self.assertEqual(got["kinds"], [b"IHDR", b"PLTE", b"tRNS", b"IDAT", b"IEND"])
        self.assertEqual(got["alpha"], [255, 255, 0])

    def test_what_is_not_a_picture_is_refused(self):
        for rows, palette, transparent in (([[0, 3]], ("#000000",) * 3, None),
                                           ([[0, 1, 0]], ("#000000",) * 3, None),
                                           ([[0, 1], [0, 1]], ("#000000",) * 3, None),
                                           ([[0, 1]], (), None),
                                           ([[0, 1]], ("#000000",) * 257, None),
                                           ([[0, 1]], ("#000000", "white"), None),
                                           ([[0, 1]], ("#000000",) * 3, 3)):
            with self.subTest(rows=rows, colours=len(palette), transparent=transparent):
                with self.assertRaises(ValueError):
                    png.indexed(2, 1, rows, palette, transparent)


def _field(cols: int, rows: int, north_first: bool = False, gap=None, lons=None) -> grids.Field:
    """A half-degree field over the tropical Pacific, its rows listed from the
    south (as ERDDAP lists them) or from the north, a cell missing at gap."""
    lats = [-15.0 + 0.5 * r for r in range(rows)]
    lons = lons or [150.0 + 0.5 * c for c in range(cols)]
    values = [[math.sin(lon / 7.0) * 2.0 + lat / 10.0 for lon in lons] for lat in lats]
    if gap:
        values[gap[0]][gap[1]] = None
    if north_first:
        lats.reverse()
        values.reverse()
    return grids.Field(x=tuple(lons), y=tuple(lats), values=tuple(tuple(row) for row in values),
                       label="test", units="degrees C", as_of="2026-10-09")


def _map(grid: grids.Field, ramp: fields.Ramp):
    """The field drawn north up, as the maps draw it, and the markup."""
    plot = fields.map_plot(880, (14, 16, 26, 44), grid.x[-1] - grid.x[0], abs(grid.y[-1] - grid.y[0]))
    plot.domain(min(grid.x), max(grid.x), min(grid.y), max(grid.y))
    drawn = fields.draw_cells(plot, grid, ramp, row_label=lambda v, _i: grids.lat_name(v),
                              col_label=grids.lon_name)
    return plot, drawn, "".join(plot.parts)


def _pictures(markup: str) -> dict:
    """Each theme's picture in the markup: its place and its PNG, read back."""
    out = {}
    for m in re.finditer(r'<image class="cellimg (light|dark)(?: smooth)?" x="([\d.]+)" y="([\d.]+)" '
                         r'width="([\d.]+)" height="([\d.]+)" preserveAspectRatio="none" '
                         r'href="data:image/png;base64,([A-Za-z0-9+/=]+)"/>', markup):
        out[m.group(1)] = {"box": tuple(float(m.group(i)) for i in range(2, 6)),
                           **decode(base64.b64decode(m.group(6)))}
    return out


class TestFieldsAsPictures(unittest.TestCase):
    """A regular field of more than 2,000 cells is drawn as an indexed PNG, a
    pixel a cell, one for each theme; its hover blocks stay vector."""

    RAMP = fields.Ramp("d", 11, -2.5, 2.5, diverging=True)

    def classes(self, grid: grids.Field, north_up=True) -> list:
        """What each cell should be, the picture's top row first: its ramp
        class, or 11, seen through, where it is missing."""
        order = sorted(range(grid.rows), key=lambda r: -grid.y[r] if north_up else r)
        return [[11 if v is None else self.RAMP.index(v) for v in grid.values[r]] for r in order]

    def test_a_large_regular_field_is_two_pictures_a_pixel_a_cell(self):
        grid = _field(60, 40)
        _plot, drawn, markup = _map(grid, self.RAMP)
        pictures = _pictures(markup)
        self.assertEqual(sorted(pictures), ["dark", "light"])
        for theme, colours in (("light", fields.DIVERGING_LIGHT), ("dark", fields.DIVERGING_DARK)):
            with self.subTest(theme):
                got = pictures[theme]
                self.assertEqual(got["size"], (60, 40))
                self.assertEqual(got["rows"], self.classes(grid))
                self.assertEqual(got["palette"][:11], list(colours))
        # No cell is a shape any more; the hover blocks still are.
        cells = markup[markup.index('<g class="cellfill"'):]
        self.assertNotIn("<path", cells)
        self.assertIn('class="hit"', cells)
        self.assertEqual(drawn, 0)

    def test_a_field_listed_from_the_north_lands_the_same_way_up(self):
        south, north = _field(60, 40), _field(60, 40, north_first=True)
        self.assertEqual(_pictures(_map(north, self.RAMP)[2])["light"]["rows"],
                         _pictures(_map(south, self.RAMP)[2])["light"]["rows"])
        self.assertEqual(_pictures(_map(north, self.RAMP)[2])["light"]["rows"], self.classes(north))

    def test_time_down_the_first_row_is_the_top_one(self):
        # A Hovmoller's rows are weeks, the first at the top.
        grid = grids.Field(x=tuple(120.0 + c for c in range(100)), y=tuple(float(r) for r in range(30)),
                           values=tuple(tuple(math.cos(c / 9.0 + r / 4.0) * 2.0 for c in range(100))
                                        for r in range(30)),
                           label="test", units="degrees C", as_of="2026-10-09")
        plot = fields.Plot(560, 470, (14, 18, 28, 58))
        plot.domain(grid.x[0], grid.x[-1], float(grid.rows - 1) + 0.5, -0.5)
        fields.draw_cells(plot, grid, self.RAMP)
        got = _pictures("".join(plot.parts))["light"]
        self.assertEqual(got["rows"], self.classes(grid, north_up=False))

    def test_a_missing_cell_is_seen_through(self):
        grid = _field(60, 40, gap=(3, 7))
        got = _pictures(_map(grid, self.RAMP)[2])
        for theme in ("light", "dark"):
            with self.subTest(theme):
                # Row 3 from the south is row 36 from the top.
                self.assertEqual(got[theme]["rows"][36][7], 11)
                self.assertEqual(got[theme]["alpha"], [255] * 11 + [0])
                self.assertEqual(got[theme]["rows"], self.classes(grid))

    def test_the_picture_covers_the_cells_edge_to_edge(self):
        grid = _field(60, 40)
        plot, _drawn, markup = _map(grid, self.RAMP)
        left, right = plot.sx(grid.x[0] - 0.25), plot.sx(grid.x[-1] + 0.25)
        top, bottom = plot.sy(grid.y[-1] + 0.25), plot.sy(grid.y[0] - 0.25)
        for theme, got in _pictures(markup).items():
            with self.subTest(theme):
                for have, want in zip(got["box"], (left, top, right - left, bottom - top)):
                    self.assertAlmostEqual(have, want, delta=0.06)

    def test_each_theme_shows_its_own_picture_its_cells_square(self):
        css = fields.ramp_css()
        self.assertIn(".cellimg { image-rendering: crisp-edges; image-rendering: pixelated; }", css)
        self.assertIn(".cellimg.dark { display: none; }", css)
        hide, show = ".cellimg.light { display: none; }", ".cellimg.dark { display: inline; }"
        dark_os = " ".join(re.findall(r'@media \(prefers-color-scheme: dark\) \{ (.*) \}\n', css))
        self.assertIn(f':root:not([data-theme="light"]) {hide}', dark_os)
        self.assertIn(f':root:not([data-theme="light"]) {show}', dark_os)
        self.assertIn(f':root[data-theme="dark"] {hide}', css)
        self.assertIn(f':root[data-theme="dark"] {show}', css)

    def test_cells_finer_than_a_unit_of_the_plot_are_left_to_the_browser_s_smoothing(self):
        # The global map's quarter-degree cells, 1,440 across 827 units: shown
        # at a pixel a unit, nearest-neighbour drops whole columns of them.
        def classes(markup):
            return sorted(re.findall(r'<image class="([^"]*)"', markup))

        weeks = grids.Field(x=tuple(120.0 + c for c in range(100)), y=tuple(float(r) for r in range(600)),
                            values=tuple(tuple(math.cos(c / 9.0 + r / 40.0) * 2.0 for c in range(100))
                                         for r in range(600)),
                            label="test", units="degrees C", as_of="2026-10-09")
        tall = fields.Plot(560, 470, (14, 18, 28, 58))
        tall.domain(weeks.x[0], weeks.x[-1], float(weeks.rows - 1) + 0.5, -0.5)
        fields.draw_cells(tall, weeks, self.RAMP)
        for name, markup, smooth in (("a unit a cell or more", _map(_field(60, 40), self.RAMP)[2], ""),
                                     ("finer across", _map(_field(1500, 40), self.RAMP)[2], " smooth"),
                                     ("finer down", "".join(tall.parts), " smooth")):
            with self.subTest(name):
                self.assertEqual(classes(markup), [f"cellimg dark{smooth}", f"cellimg light{smooth}"])
        css = fields.ramp_css()
        self.assertIn(".cellimg.smooth { image-rendering: auto; }", css)
        self.assertGreater(css.index(".cellimg.smooth"), css.index("image-rendering: pixelated"))

    def test_a_small_or_irregular_field_stays_shapes(self):
        uneven = [150.0 + 0.5 * c for c in range(59)] + [190.0]
        for name, grid in (("2,000 cells", _field(50, 40)),
                           ("uneven longitudes", _field(60, 40, lons=uneven))):
            with self.subTest(name):
                _plot, drawn, markup = _map(grid, self.RAMP)
                self.assertNotIn("<image", markup)
                self.assertGreater(drawn, 0)
        # Depth levels closer near the surface than below.
        depths = [5.0 + 10.0 * r for r in range(25)] + [270.0, 300.0, 350.0, 400.0, 500.0]
        section = grids.Field(x=tuple(120.0 + c for c in range(100)), y=tuple(depths),
                              values=tuple(tuple(1.0 for _ in range(100)) for _ in depths),
                              label="test", units="degrees C", as_of="2026-10-09")
        plot = fields.Plot(560, 300, (14, 18, 28, 58))
        plot.domain(120.0, 219.0, 500.0, 0.0)
        self.assertGreater(fields.draw_cells(plot, section, self.RAMP), 0)
        self.assertNotIn("<image", "".join(plot.parts))

    def test_the_global_map_s_cells_cost_a_fraction_as_pictures_and_nothing_else_changes(self):
        # A one-degree world with the fine structure a day's analysis has, and
        # the Arctic's ice, where there is no sea surface to measure.
        def sst(lon, lat):
            ripple = math.sin(lon * 12.9898 + lat * 78.233) * 43758.5453 % 1.0 - 0.5
            return None if lat > 80 else math.sin(lon / 25.0) * math.cos(lat / 30.0) * 2.0 + ripple

        lons, lats = [0.5 + c for c in range(360)], [-89.5 + r for r in range(180)]
        grid = grids.Field(x=tuple(lons), y=tuple(lats),
                           values=tuple(tuple(sst(lon, lat) for lon in lons) for lat in lats),
                           label="t", units="degrees C", as_of="2026-10-09")
        html = fields.global_map(grid)
        with mock.patch.object(fields, "PICTURE_CELLS", grid.rows * grid.cols):
            shapes = fields.global_map(grid)
        self.assertEqual(len(_pictures(html)), 2)
        self.assertNotIn("<image", shapes)
        pictures, runs = r'<image class="cellimg[^>]*/>', r'<path d="[^"]*" fill="var\(--d\d+\)"/>'
        self.assertLess(sum(map(len, re.findall(pictures, html))), sum(map(len, re.findall(runs, shapes))) / 10)
        # The hover blocks, the coast, the frame and the table are as they were.
        self.assertEqual(re.sub(r"clip\d+", "clip", re.sub(pictures + "\n", "", html)),
                         re.sub(r"clip\d+", "clip", re.sub(runs + "\n", "", shapes)))
