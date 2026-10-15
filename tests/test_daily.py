"""The dipole and the SOI day by day: the Indian Ocean Dipole's poles from
OISST's daily analyses, as the Nino boxes are, and the SOI, on the Bureau of
Meteorology's definition, from LongPaddock's daily file."""

from __future__ import annotations

import math
import re
import sys
import unittest
import urllib.parse
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elnino import dashboard, daily, grids, parsers, pipeline, report, sources  # noqa: E402


def _query(url: str) -> str:
    return urllib.parse.unquote(url.partition("?")[2])


def _fetched(key, text, url=None):
    source = sources.SOURCES_BY_KEY[key]
    return sources.Fetched(source, text, "2026-10-14T10:12:00+00:00", False, "",
                           url=url or source.url)


# --- the dipole ----------------------------------------------------------------
HEAD = "time,zlev,latitude,longitude,anom\nUTC,m,degrees_north,degrees_east,degree_C\n"
# The poles' rectangle as asked: half a degree from 9.875S and from 50.125E.
LATS = tuple(-9.875 + 0.5 * k for k in range(40))
LONS = tuple(50.125 + 0.5 * k for k in range(120))


def _poles(days, value) -> str:
    """ERDDAP's CSV of OISST's anomaly over the poles' rectangle, day by day,
    each cell's value ``value(lat, lon)``."""
    rows = [f"{day}T12:00:00Z,0.0,{lat},{lon},{value(lat, lon)}"
            for day in days for lat in LATS for lon in LONS]
    return HEAD + "\n".join(rows) + "\n"


def _split(west: float, east: float, elsewhere: float = 9.0):
    """A cell's value: ``west`` in the west pole, ``east`` in the east pole,
    and ``elsewhere`` in the rest of the rectangle, which no pole holds."""
    def value(lat: float, lon: float) -> float:
        if 50.0 <= lon <= 70.0:
            return west
        if 90.0 <= lon <= 110.0 and lat <= 0.0:
            return east
        return elsewhere
    return value


class TestDipole(unittest.TestCase):
    """The Indian Ocean Dipole's poles day by day, and the Dipole Mode Index."""

    def test_the_poles_are_the_bureau_s(self):
        # Saji et al. (1999), as the Bureau of Meteorology monitors them.
        self.assertEqual([(b.key, b.lon0, b.lon1, b.lat0, b.lat1) for b in grids.IOD_BOXES],
                         [("west", 50.0, 70.0, -10.0, 10.0), ("east", 90.0, 110.0, -10.0, 0.0)])

    def test_the_poles_are_asked_for_on_half_degree_cells_holding_both(self):
        record = sources.SOURCES_BY_KEY["iod_daily"]
        recent = sources.SOURCES_BY_KEY["iod_daily_recent"]
        self.assertTrue(record.url.startswith(sources.OISST_FINAL + "?"), record.url)
        self.assertTrue(recent.url.startswith(sources.OISST_NRT + "?"), recent.url)
        # Half a degree, as the Nino boxes' cells are: one degree put the DMI
        # 0.027 degC off the full grid on 13 October, half a degree 0.009.
        cells = "[(-9.875):2:(9.625)][(50.125):2:(109.625)]"
        self.assertEqual(_query(record.url), f"anom[last-89:1:last][(0.0)]{cells}")
        self.assertEqual(_query(recent.url), f"anom[last-27:1:last][(0.0)]{cells}")
        self.assertEqual((record.final, recent.final), ("", ""))
        for box in grids.IOD_BOXES:
            held = [(lat, lon) for lat in LATS for lon in LONS if box.contains(lat, lon)]
            self.assertEqual(len(held), {"west": 40 * 40, "east": 20 * 40}[box.key], box.key)

    def test_each_pole_is_its_cells_mean_and_the_dmi_the_west_less_the_east(self):
        days = grids.dipole(grids.daily_box_means(_poles(["2026-10-12"], _split(1.0, 0.25)),
                                                  grids.IOD_BOXES))
        (day,) = days
        self.assertEqual(day.means["west"], 1.0)
        self.assertAlmostEqual(day.means["east"], 0.25)
        # The cells between the poles, and north of the equator over the
        # east pole's longitudes, weigh nothing.
        self.assertAlmostEqual(day.means["dmi"], 0.75)
        self.assertEqual(set(day.means), {"west", "east", "dmi"})

    def test_a_pole_s_cells_are_weighted_by_the_cosine_of_their_latitude(self):
        def value(lat, lon):
            return lat if 50.0 <= lon <= 70.0 else 0.0
        (day,) = grids.daily_box_means(_poles(["2026-10-12"], value), grids.IOD_BOXES)
        weights = [math.cos(math.radians(lat)) for lat in LATS]
        expected = sum(lat * w for lat, w in zip(LATS, weights)) / sum(weights)
        self.assertAlmostEqual(day.means["west"], expected)
        self.assertNotAlmostEqual(day.means["west"], sum(LATS) / len(LATS), places=4)

    def test_a_day_with_one_pole_has_no_dmi(self):
        east_land = _split(1.0, "NaN")
        days = grids.dipole(grids.daily_box_means(
            _poles(["2026-10-11"], east_land) + _poles(["2026-10-12"], _split(1.0, 0.5))[len(HEAD):],
            grids.IOD_BOXES))
        self.assertEqual([set(d.means) for d in days], [{"west"}, {"west", "east", "dmi"}])

    def test_the_run_splices_the_poles_and_measures_what_the_final_changed(self):
        record = _poles(["2026-09-27", "2026-09-28"], _split(1.0, 0.25))
        recent = _poles(["2026-09-28", "2026-09-29"], _split(1.1, 0.25))
        state = pipeline.build_spatial({"iod_daily": _fetched("iod_daily", record),
                                        "iod_daily_recent": _fetched("iod_daily_recent", recent)})
        self.assertEqual([(d.day, d.preliminary) for d in state.iod_daily], [
            ("2026-09-27", False), ("2026-09-28", False), ("2026-09-29", True)])
        self.assertAlmostEqual(state.iod_daily[-1].means["dmi"], 0.85)
        self.assertEqual(set(state.iod_revision), {"west", "east", "dmi"})
        moved = state.iod_revision["dmi"]
        self.assertEqual(moved.days, 1)
        self.assertAlmostEqual(moved.mean, -0.1)
        self.assertAlmostEqual(moved.most, 0.1)
        self.assertEqual(state.notes, [])

    def test_the_dipole_stands_on_the_preliminary_alone(self):
        recent = _poles(["2026-10-11", "2026-10-12"], _split(0.6, 0.1))
        state = pipeline.build_spatial({"iod_daily_recent": _fetched("iod_daily_recent", recent)})
        self.assertEqual([(d.day, d.preliminary) for d in state.iod_daily],
                         [("2026-10-11", True), ("2026-10-12", True)])
        self.assertEqual(state.iod_revision, {})
        self.assertTrue(state.available)

    def test_a_broken_dipole_answer_is_noted_and_costs_only_itself(self):
        boxes = (HEAD + "2026-10-12T12:00:00Z,0.0,0.125,200.125,2.0\n")
        state = pipeline.build_spatial({"iod_daily": _fetched("iod_daily", HEAD),
                                        "nino_daily": _fetched("nino_daily", boxes)})
        self.assertEqual(state.iod_daily, ())
        self.assertTrue(any(note.startswith("daily dipole:") for note in state.notes), state.notes)
        self.assertEqual([d.day for d in state.nino_daily], ["2026-10-12"])


# --- the SOI ---------------------------------------------------------------------
SOI_HEAD = "Year Day  Tahiti  Darwin     SOI\n"


def _soi_file(rows) -> str:
    """LongPaddock's daily file: its header, then a row a day of the year, the
    day of the year, Tahiti's and Darwin's pressures and the SOI, as it
    writes them."""
    return SOI_HEAD + "".join(f"{year} {day:3d} {tahiti:7.2f} {darwin:7.2f} {soi:7.2f}\n"
                              for year, day, tahiti, darwin, soi in rows)


def _soi_run(first: date, values, skip=()) -> str:
    """A file of consecutive days from ``first``, the nth day's SOI
    ``values[n]``, leaving out the days numbered in ``skip``."""
    rows = []
    for n, soi in enumerate(values):
        if n in skip:
            continue
        day = first + timedelta(days=n)
        rows.append((day.year, day.timetuple().tm_yday, 1013.0, 1009.0, soi))
    return _soi_file(rows)


class TestDailySoi(unittest.TestCase):
    """The SOI day by day, on the Bureau of Meteorology's definition, from
    LongPaddock's file."""

    URL = ("https://data.longpaddock.qld.gov.au/SeasonalClimateOutlook/"
           "SouthernOscillationIndex/SOIDataFiles/DailySOI1933-1992Base.txt")

    def test_the_soi_is_longpaddock_s_daily_file_read_whole_and_not_archived(self):
        source = sources.SOURCES_BY_KEY["soi_daily"]
        self.assertEqual(source.url, self.URL)
        self.assertEqual((source.tier, source.archive, source.critical), ("atmosphere", False, False))
        self.assertEqual((source.final, source.fallback), ("", ()))
        self.assertTrue(source.name and source.note and source.cadence and source.agency)

    def test_each_row_is_a_day_by_its_year_and_its_day_of_the_year(self):
        days = parsers.parse_daily_soi(_soi_file([(2024, 366, 1012.25, 1008.5, 5.0),
                                                  (2025, 1, 1013.0, 1009.75, -6.5)]))
        self.assertEqual([(d.day, d.tahiti, d.darwin, d.soi) for d in days],
                         [("2024-12-31", 1012.25, 1008.5, 5.0), ("2025-01-01", 1013.0, 1009.75, -6.5)])

    def test_a_common_year_s_366th_day_is_left_out(self):
        days = parsers.parse_daily_soi(_soi_file([(2025, 365, 1013.0, 1009.0, 1.0),
                                                  (2025, 366, 1013.0, 1009.0, 2.0),
                                                  (2026, 1, 1013.0, 1009.0, 3.0)]))
        self.assertEqual([(d.day, d.soi) for d in days], [("2025-12-31", 1.0), ("2026-01-01", 3.0)])

    def test_a_pressure_that_is_the_fill_value_leaves_its_day_without_an_soi(self):
        # 20 December 2015 in the file: Darwin -999.90, and an SOI worked out
        # from it.
        text = (SOI_HEAD + "2015 353 1011.20 1006.10    9.12\n"
                "2015 354 1011.74 -999.90 0224.84\n" "2015 355 1011.05 1006.40    7.01\n")
        days = parsers.parse_daily_soi(text)
        self.assertEqual([(d.day, d.soi) for d in days],
                         [("2015-12-19", 9.12), ("2015-12-20", None), ("2015-12-21", 7.01)])
        self.assertEqual((days[1].tahiti, days[1].darwin), (None, None))

    def test_a_day_given_again_is_the_first_s(self):
        # 2012's 328th day in the file, twice, and its 329th not at all.
        text = (SOI_HEAD + "2012 327 1012.76 1008.60    8.25\n" "2012 328 1012.27 1010.60   -8.18\n"
                "2012 328 1012.15 1010.45   -7.98\n" "2012 330 1012.40 1010.10   -5.00\n")
        days = parsers.parse_daily_soi(text)
        self.assertEqual([(d.day, d.soi) for d in days],
                         [("2012-11-22", 8.25), ("2012-11-23", -8.18), ("2012-11-24", None),
                          ("2012-11-25", -5.0)])

    def test_a_page_that_is_not_the_file_is_refused(self):
        for text in ("<!DOCTYPE html><html><body>Maintenance</body></html>\n", "", SOI_HEAD):
            with self.subTest(text=text[:20]), self.assertRaises(ValueError):
                parsers.parse_daily_soi(text)

    def test_the_30_and_90_day_soi_are_the_means_of_the_days_to_each(self):
        days = parsers.parse_daily_soi(_soi_run(date(2026, 6, 16), [float(n) for n in range(120)]))
        last = days[-1]
        self.assertEqual(last.day, "2026-10-13")
        self.assertEqual(last.soi30, sum(range(90, 120)) / 30)
        self.assertEqual(last.soi90, sum(range(30, 120)) / 90)

    def test_a_window_may_lack_five_days_and_three_in_a_row_and_no_more(self):
        # The WMO's 3/5 rule for a month's mean, kept for both windows.
        values = [float(n) for n in range(40)]
        first = date(2026, 9, 4)
        ends = {}
        for name, skip in (("five, three in a row", {20, 21, 22, 30, 35}),
                           ("six", {20, 22, 24, 30, 33, 35}),
                           ("four in a row", {30, 31, 32, 33})):
            ends[name] = parsers.parse_daily_soi(_soi_run(first, values, skip))[-1].soi30
        kept = [n for n in range(10, 40) if n not in {20, 21, 22, 30, 35}]
        self.assertEqual(ends["five, three in a row"], sum(kept) / len(kept))
        self.assertIsNone(ends["six"])
        self.assertIsNone(ends["four in a row"])

    def test_every_calendar_day_is_a_day_and_one_the_file_lacks_keeps_its_means(self):
        # The file has no row for 24 November 2012. A day's means do not need
        # the day's own value, and the 3/5 rule allows for its lack.
        first = date(2026, 9, 1)
        days = parsers.parse_daily_soi(_soi_run(first, [float(n) for n in range(40)], skip={38}))
        self.assertEqual([d.day for d in days],
                         [(first + timedelta(days=n)).isoformat() for n in range(40)])
        lacking = days[38]
        self.assertEqual((lacking.tahiti, lacking.darwin, lacking.soi), (None, None, None))
        self.assertEqual(lacking.soi30, sum(range(9, 38)) / 29)
        self.assertEqual(days[39].soi30, (sum(range(10, 40)) - 38) / 29)

    def test_a_row_whose_soi_is_not_a_number_leaves_its_day_without_one(self):
        # A NaN would reach the means, the page as "+nan" and the JSON, where a
        # bare NaN is no JSON at all.
        text = (SOI_HEAD + "2026 280 1013.00 1009.00    1.00\n" "2026 281 1013.00 1009.00     nan\n"
                "2026 282 1013.00 1009.00     inf\n" "2026 283 1013.00 1009.00    2.00\n")
        self.assertEqual([(d.day, d.soi) for d in parsers.parse_daily_soi(text)],
                         [("2026-10-07", 1.0), ("2026-10-08", None), ("2026-10-09", None),
                          ("2026-10-10", 2.0)])

    def test_a_pressure_past_any_sea_level_pressure_observed_is_left_out(self):
        # From 870 hPa, in Typhoon Tip in 1979, to 1084.8 hPa, at Tosontsengel
        # in Mongolia in 2001.
        text = (SOI_HEAD + "2026 280 1013.00 1084.80    1.00\n" "2026 281 1013.00 1085.50    2.00\n"
                "2026 282  869.50 1009.00    3.00\n" "2026 283  870.00 1009.00    4.00\n")
        self.assertEqual([(d.day, d.soi) for d in parsers.parse_daily_soi(text)],
                         [("2026-10-07", 1.0), ("2026-10-08", None), ("2026-10-09", None),
                          ("2026-10-10", 4.0)])

    def test_the_source_says_whose_soi_it_is(self):
        # The Bureau's own daily SOI data have been unavailable since January
        # 2025; LongPaddock works the SOI out on its definition.
        source = sources.SOURCES_BY_KEY["soi_daily"]
        self.assertIn("on the Bureau of Meteorology's definition", source.name)
        self.assertIn("LongPaddock", source.agency)

    def test_the_run_reads_the_days_and_a_broken_file_is_a_warning(self):
        text = _soi_run(date(2026, 10, 1), [1.0, 2.0, 3.0])
        series, warnings = pipeline.parse_all({"soi_daily": _fetched("soi_daily", text)})
        self.assertEqual([d.day for d in series["soi_daily"]],
                         ["2026-10-01", "2026-10-02", "2026-10-03"])
        self.assertEqual(warnings, [])
        series, warnings = pipeline.parse_all({"soi_daily": _fetched("soi_daily", "<html>\n")})
        self.assertEqual(series["soi_daily"], [])
        self.assertTrue(any(w.startswith("soi_daily: ValueError") for w in warnings), warnings)


# --- on the page -------------------------------------------------------------------
def _label(stamp: str) -> str:
    """A day as the page writes it, "12 Oct 2026"."""
    day = date.fromisoformat(stamp)
    return f"{day.day} {day:%b %Y}"


def _dipole_days(first="2026-07-07", last="2026-10-12", prelim_from="2026-09-29"):
    """The poles' days, the west pole warming and the east cooling, each day
    with its DMI."""
    out, day, n = [], date.fromisoformat(first), 0
    while day <= date.fromisoformat(last):
        west, east = 0.3 + n / 200.0, 0.1 - n / 400.0
        out.append(grids.BoxDay(day.isoformat(), {"west": west, "east": east, "dmi": west - east},
                                day.isoformat() >= prelim_from))
        day, n = day + timedelta(days=1), n + 1
    return tuple(out)


class TestDipoleCard(unittest.TestCase):
    """The Indian Ocean Dipole day by day, under the Nino boxes."""

    def test_the_dmi_and_each_pole_are_a_line_with_a_legend(self):
        html = daily.dipole_card(_dipole_days())
        self.assertIn('<section class="card" id="iod-daily">', html)
        for colour in ("var(--s1)", "var(--s2)", "var(--s3)"):
            self.assertEqual(html.count(f'class="dayline" stroke="{colour}"'), 1, colour)
        for name in ("DMI", "West pole", "East pole"):
            self.assertIn(f"</span>{name}</span>", html)

    def test_the_bureau_s_thresholds_are_marked_over_the_lines(self):
        html = daily.dipole_card(_dipole_days())
        for label in ("positive IOD +0.4", "negative IOD -0.4"):
            self.assertGreater(html.index(f">{label}</text>"), html.rindex('class="dayline"'))
        self.assertIn('stroke="var(--warm)" stroke-width="1"', html)
        self.assertIn('stroke="var(--cool)" stroke-width="1"', html)

    def test_a_threshold_s_name_is_haloed_in_the_card_s_ground(self):
        # Over the lines, a line crossing the name would cut its letters.
        rule = re.search(r"\.band-note \{([^}]*)\}", dashboard._css()).group(1)
        for part in ("paint-order: stroke", "stroke: var(--surface)", "stroke-linejoin: round"):
            self.assertIn(part, rule)

    def test_the_axis_is_in_tenths_of_a_degree(self):
        ticks = re.findall(r'class="tick">([+-]?[0-9][0-9.]*)</text>',
                           daily.dipole_card(_dipole_days()))
        self.assertTrue(ticks)
        self.assertTrue(all(tick == "0.0" or tick[0] in "+-" and tick[-2] == "." for tick in ticks),
                        ticks)

    def test_the_preliminary_days_are_shaded_and_every_day_has_a_hover(self):
        days = _dipole_days()
        html = daily.dipole_card(days)
        self.assertEqual(html.count('class="prelim"'), 1)
        self.assertEqual(html.count('class="hit"'), len(days))
        last = days[-1].means
        self.assertIn('data-label="12 Oct 2026, preliminary"', html)
        self.assertIn(f'data-value="DMI {last["dmi"]:+.2f} °C"', html)
        self.assertIn(f'data-extra="West pole {last["west"]:+.2f} · East pole {last["east"]:+.2f}"',
                      html)

    def test_the_caption_gives_the_latest_dmi_the_poles_the_thresholds_and_the_base(self):
        days = _dipole_days()
        html = daily.dipole_card(days)
        now, week_ago = days[-1].means["dmi"], days[-8].means["dmi"]
        self.assertIn(f"The DMI is <strong>{now:+.2f} °C</strong> on 12 Oct 2026, "
                      f"{now - week_ago:+.2f} °C on the week.", html)
        for words in ("(50&ndash;70E, 10S&ndash;10N)", "(90&ndash;110E, 10S&ndash;0)",
                      "NOAA&rsquo;s final analysis from 2026-07-07 to 2026-09-28, then NOAA&rsquo;s "
                      "preliminary analysis from 2026-09-29 to 2026-10-12",
                      "above +0.4 °C as a positive IOD value", "below -0.4 °C as a negative one",
                      "eight weeks", "1971&ndash;2000", "cancels in their difference"):
            self.assertIn(words, html)

    def test_the_dmi_may_run_apart_from_the_bureau_s_own_on_another_base(self):
        # A warming common to both poles cancels in their difference, but a
        # difference in their warming does not, and OISST's base is 1971-2000.
        html = daily.dipole_card(_dipole_days())
        for words in ("a difference in their warming does not",
                      "run apart from the Bureau&rsquo;s own"):
            self.assertIn(words, html)
        self.assertNotIn("whatever its base", html)

    def test_the_caption_gives_the_season_events_form_in(self):
        # The thresholds are drawn all year; an event seldom forms in half of it.
        html = daily.dipole_card(_dipole_days())
        for words in ("from about May", "December to April"):
            self.assertIn(words, html)

    def test_the_card_says_how_far_the_final_moved_the_dmi(self):
        moved = {"dmi": grids.Revision(13, -0.03, 0.08), "west": grids.Revision(13, -0.02, 0.05),
                 "east": grids.Revision(13, 0.01, 0.12)}
        html = daily.dipole_card(_dipole_days(), moved)
        self.assertIn("On the 13 days both analyses carry, the final runs 0.03 °C lower than the "
                      "preliminary in the DMI on average, and differs by up to 0.08 °C on a day "
                      "(0.12 °C in the east pole): about how far the shaded days may yet move.", html)
        higher = daily.dipole_card(_dipole_days(), {"dmi": grids.Revision(3, 0.05, 0.06)})
        self.assertIn("the final runs 0.05 °C higher than the preliminary in the DMI", higher)
        self.assertNotIn("both analyses carry",
                         daily.dipole_card(_dipole_days(prelim_from="9999"), moved))

    def test_a_day_without_a_dmi_breaks_its_line_and_says_so(self):
        days = list(_dipole_days())
        days[40] = grids.BoxDay(days[40].day, {"west": 0.5}, False)
        html = daily.dipole_card(tuple(days))
        for colour, breaks in (("s1", 2), ("s2", 1), ("s3", 2)):
            line = re.search(rf'<path d="([^"]+)" class="dayline" stroke="var\(--{colour}\)"',
                             html).group(1)
            self.assertEqual(line.count("M"), breaks, colour)
        self.assertIn('data-value="DMI not analysed"', html)

    def test_the_table_lists_every_day_latest_first(self):
        days = _dipole_days()
        table = daily.dipole_card(days)
        table = table[table.index("<details"):]
        self.assertEqual(table.count("<tr>"), len(days) + 1)
        self.assertLess(table.index("2026-10-12"), table.index("2026-10-11"))
        for head in ("DMI", "West pole", "East pole"):
            self.assertIn(f">{head}</th>", table)

    def test_fewer_than_two_days_draw_no_card(self):
        self.assertEqual(daily.dipole_card(()), "")
        self.assertEqual(daily.dipole_card(_dipole_days(first="2026-10-12")), "")


def _soi_record(first=date(2026, 5, 1), count=166):
    """LongPaddock's days from ``first``, the SOI falling from +5 by a tenth a
    day, to 13 October 2026."""
    return parsers.parse_daily_soi(_soi_run(first, [5.0 - n / 10.0 for n in range(count)]))


class TestSoiCard(unittest.TestCase):
    """The SOI day by day, after the Walker circulation's months."""

    def test_the_last_120_days_are_three_lines_with_a_legend(self):
        days = _soi_record()
        html = daily.soi_card(days)
        self.assertIn('<section class="card" id="soi-daily">', html)
        self.assertEqual(daily.SOI_DAYS, 120)
        self.assertEqual(html.count('class="hit"'), 120)
        self.assertIn(f'data-label="{_label(days[-120].day)}"', html)
        self.assertNotIn(f'data-label="{_label(days[-121].day)}"', html)
        for colour in ("var(--s1)", "var(--s2)", "var(--s3)"):
            self.assertEqual(html.count(f'class="dayline" stroke="{colour}"'), 1, colour)
        for name in ("30-day SOI", "90-day SOI", "Daily SOI"):
            self.assertIn(f"</span>{name}</span>", html)

    def test_each_day_s_own_soi_is_drawn_faint_under_the_means(self):
        html = daily.soi_card(_soi_record())
        self.assertIn('class="dayline" stroke="var(--s3)" fill="none" stroke-width="1" '
                      'opacity="0.5"', html)
        self.assertLess(html.index('stroke="var(--s3)" fill="none"'),
                        html.index('stroke="var(--s1)" fill="none"'))

    def test_the_bureau_s_thresholds_are_marked(self):
        html = daily.soi_card(_soi_record())
        self.assertIn(">El Nino-like -7</text>", html)
        self.assertIn(">La Nina-like +7</text>", html)

    def test_the_axis_counts_in_whole_numbers(self):
        # The SOI runs to tens; "-20.0" is a decimal it does not have.
        ticks = re.findall(r'class="tick">([+-]?[0-9][0-9.]*)</text>',
                           daily.soi_card(_soi_record()))
        self.assertTrue(ticks)
        self.assertFalse([tick for tick in ticks if "." in tick], ticks)
        self.assertIn('class="tick">0</text>', daily.soi_card(_soi_record()))

    def test_each_day_has_a_hover_with_its_values_and_its_pressures(self):
        days = _soi_record()
        html = daily.soi_card(days)
        last = days[-1]
        self.assertIn(f'data-value="30-day SOI {last.soi30:+.1f}"', html)
        self.assertIn(f'data-extra="90-day SOI {last.soi90:+.1f} · Daily SOI {last.soi:+.1f} · '
                      f'Tahiti 1013.0 hPa · Darwin 1009.0 hPa"', html)

    def test_a_day_without_a_30_day_soi_says_it_was_not_worked_out(self):
        # The file's first days: their windows reach back past its start.
        html = daily.soi_card(parsers.parse_daily_soi(_soi_run(date(2026, 9, 1), [1.0] * 30)))
        self.assertIn('data-value="30-day SOI not worked out"', html)
        self.assertEqual(html.count('class="dayline"'), 2)

    def test_the_caption_gives_the_latest_means_the_thresholds_and_what_the_soi_is(self):
        days = _soi_record()
        html = daily.soi_card(days)
        last = days[-1]
        self.assertIn(f"The 30-day SOI is <strong>{last.soi30:+.1f}</strong> on 13 Oct 2026, "
                      f"the 90-day {last.soi90:+.1f}.", html)
        for words in ("LongPaddock", "Tahiti and Darwin pressures", "means of the days&rsquo;",
                      "below -7 are El Nino-like", "above +7 La Nina-like",
                      "ten times the standardised", "1933&ndash;1992"):
            self.assertIn(words, html)

    def test_a_day_the_file_lacks_keeps_the_means_whole_and_breaks_its_own_line(self):
        days = parsers.parse_daily_soi(_soi_run(date(2026, 5, 1),
                                                [5.0 - n / 10.0 for n in range(166)], skip={150}))
        html = daily.soi_card(days)
        self.assertEqual(html.count('class="hit"'), 120)
        for colour, pieces in (("s1", 1), ("s2", 1), ("s3", 2)):
            line = re.search(rf'<path d="([^"]+)" class="dayline" stroke="var\(--{colour}\)"',
                             html).group(1)
            self.assertEqual(line.count("M"), pieces, colour)
        hover = re.search(r'<[^>]*data-label="28 Sep 2026"[^>]*>', html).group(0)
        mean = sum(5.0 - n / 10.0 for n in range(121, 150)) / 29
        self.assertIn(f'data-value="30-day SOI {mean:+.1f}"', hover)
        self.assertNotIn("Tahiti", hover)
        row = re.search(r"<tr><td>2026-09-28</td>(.*?)</tr>", html).group(1)
        self.assertEqual(row.count("<td>—</td>"), 3)

    def test_the_caption_says_whose_soi_it_is(self):
        html = daily.soi_card(_soi_record())
        for words in ("on the Bureau of Meteorology&rsquo;s definition", "Troup",
                      "LongPaddock", "unavailable since January 2025"):
            self.assertIn(words, html)
        for words in ("The Bureau of Meteorology&rsquo;s Southern Oscillation Index",
                      "as the Bureau quotes them", "The Bureau of Meteorology's SOI"):
            self.assertNotIn(words, html)

    def test_cpc_s_monthly_soi_is_set_beside_the_30_day_soi(self):
        # A day's SOI swings far wider than a month's: CPC's monthly standard
        # score runs at about a tenth of the 30-day SOI, not of a day's.
        self.assertIn("about a tenth of the 30-day SOI", daily.soi_card(_soi_record()))

    def test_the_table_lists_the_days_drawn_latest_first(self):
        table = daily.soi_card(_soi_record())
        table = table[table.index("<details"):]
        self.assertEqual(table.count("<tr>"), 121)
        self.assertLess(table.index("2026-10-13"), table.index("2026-10-12"))
        for head in ("30-day SOI", "90-day SOI", "Daily SOI", "Tahiti, hPa", "Darwin, hPa"):
            self.assertIn(f">{head}</th>", table)

    def test_a_latest_day_long_past_says_how_far_behind_it_is(self):
        days = parsers.parse_daily_soi(_soi_run(date.today() - timedelta(days=60), [1.0] * 45))
        self.assertIn('<span class="chip chip-warning">16 days behind</span>', daily.soi_card(days))

    def test_fewer_than_two_days_draw_no_card(self):
        self.assertEqual(daily.soi_card([]), "")
        one = parsers.parse_daily_soi(_soi_run(date(2026, 10, 13), [1.0]))
        self.assertEqual(daily.soi_card(one), "")


# --- in the report -----------------------------------------------------------------
class TestReport(unittest.TestCase):
    """The text report: the dipole's latest days after the Nino boxes', and the
    SOI's in the atmosphere's section."""

    @staticmethod
    def _spatial(**fields) -> list[str]:
        return report._section_spatial(SimpleNamespace(spatial=grids.SpatialState(**fields)))

    def test_the_dipole_s_latest_days_follow_the_boxes_days(self):
        days = _dipole_days()
        boxes = tuple(grids.BoxDay(d.day, {"nino34": 1.0}, d.preliminary) for d in days)
        lines = self._spatial(nino_daily=boxes, iod_daily=days)
        start = next(i for i, line in enumerate(lines) if "Indian Ocean Dipole day by day" in line)
        self.assertGreater(start, next(i for i, line in enumerate(lines)
                                       if "Day by day, from OISST" in line))
        block = lines[start:]
        self.assertEqual(block[1].split(), ["DMI", "West", "East"])
        rows = [line.split() for line in block if line.startswith("  2026-")]
        self.assertEqual(len(rows), report.DAILY_ROWS)
        last = days[-1].means
        self.assertEqual(rows[0], ["2026-10-12", "(preliminary)", f"{last['dmi']:+.2f}",
                                   f"{last['west']:+.2f}", f"{last['east']:+.2f}"])
        said = " ".join(" ".join(block).split())
        for words in ("west pole (50-70E, 10S-10N)", "east pole (90-110E, 10S-0)",
                      "above +0.4", "below -0.4", "eight weeks"):
            self.assertIn(words, said)
        self.assertTrue(all(len(line) <= report.WIDTH and line.isascii() for line in lines))

    def test_the_report_says_how_far_the_final_moved_the_dmi(self):
        lines = self._spatial(iod_daily=_dipole_days(),
                              iod_revision={"dmi": grids.Revision(13, -0.03, 0.08)})
        self.assertIn("On the 13 days both analyses carry, the final runs -0.03 degC from the "
                      "preliminary in the DMI on average, and up to 0.08 degC on a day",
                      " ".join(" ".join(lines).split()))

    def test_a_day_without_a_dmi_says_n_a(self):
        days = list(_dipole_days())
        days[-1] = grids.BoxDay(days[-1].day, {"west": 0.5}, True)
        lines = self._spatial(iod_daily=tuple(days))
        row = next(line.split() for line in lines if line.startswith("  2026-10-12"))
        self.assertEqual(row, ["2026-10-12", "(preliminary)", "n/a", "+0.50", "n/a"])

    def test_a_run_without_the_dipole_reports_none(self):
        boxes = tuple(grids.BoxDay(d.day, {"nino34": 1.0}, d.preliminary) for d in _dipole_days())
        self.assertFalse(any("Dipole" in line for line in self._spatial(nino_daily=boxes)))

    def test_the_soi_s_latest_days_come_latest_first_with_their_pressures(self):
        days = _soi_record()
        lines = report._soi_lines(days)
        rows = [line.split() for line in lines if line.startswith("  2026-")]
        self.assertEqual(len(rows), report.DAILY_ROWS)
        last = days[-1]
        self.assertEqual(rows[0], ["2026-10-13", f"{last.soi30:+.1f}", f"{last.soi90:+.1f}",
                                   f"{last.soi:+.1f}", "1013.0", "1009.0"])
        said = " ".join(" ".join(lines).split())
        for words in ("El Nino lowers the SOI", "below -7", "above +7", "1933-1992"):
            self.assertIn(words, said)

    def test_the_soi_report_says_whose_it_is_and_sets_cpc_s_beside_the_30_day(self):
        said = " ".join(" ".join(report._soi_lines(_soi_record())).split())
        for words in ("from LongPaddock's file, on the Bureau's definition", "Troup",
                      "about a tenth of the 30-day SOI", "unavailable since January 2025"):
            self.assertIn(words, said)
        self.assertNotIn("as the Bureau quotes them", said)

    def test_a_day_the_file_lacks_says_n_a_for_its_own_values(self):
        days = parsers.parse_daily_soi(_soi_run(date(2026, 5, 1),
                                                [5.0 - n / 10.0 for n in range(166)], skip={160}))
        rows = {line.split()[0]: line.split() for line in report._soi_lines(days)
                if line.startswith("  2026-")}
        self.assertIn("2026-10-08", rows)
        self.assertEqual(rows["2026-10-08"][3:], ["n/a", "n/a", "n/a"])
        self.assertNotEqual(rows["2026-10-08"][1], "n/a")

    def test_the_dipole_report_says_the_base_and_the_season(self):
        said = " ".join(" ".join(self._spatial(iod_daily=_dipole_days())).split())
        for words in ("a difference in their warming does not", "from about May",
                      "December to April"):
            self.assertIn(words, said)

    def test_a_day_without_a_mean_says_n_a_and_every_line_fits(self):
        lines = report._soi_lines(parsers.parse_daily_soi(_soi_run(date(2026, 9, 1), [1.0] * 30)))
        row = next(line.split() for line in lines if line.startswith("  2026-09-25"))
        self.assertEqual(row, ["2026-09-25", "n/a", "n/a", "+1.0", "1013.0", "1009.0"])
        self.assertTrue(all(len(line) <= report.WIDTH and line.isascii() for line in lines))
        self.assertEqual(report._soi_lines([]), [])


if __name__ == "__main__":
    unittest.main()
