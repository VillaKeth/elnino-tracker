"""Westerly wind events day by day: CCMP's near-real-time 10 m winds over the
tropical Pacific, against a monthly base vendored from CCMP version 2.0, in
Harrison and Vecchi's eight regions."""

from __future__ import annotations

import json
import math
import re
import sys
import tempfile
import unittest
import urllib.parse
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elnino import (  # noqa: E402
    alerts, classify, daily, dashboard, fields, grids, parsers, pipeline, report, sources,
    windclim, winds,
)


# --- the base -----------------------------------------------------------------
class TestBase(unittest.TestCase):
    """CCMP version 2.0's monthly means for 1991-2018, on the feed's cells."""

    def test_the_cells_are_every_ninth_symmetric_about_the_equator(self):
        self.assertEqual(len(windclim.LATS), 14)
        self.assertEqual((windclim.LATS[0], windclim.LATS[-1]), (-14.625, 14.625))
        self.assertEqual(windclim.LATS, tuple(-lat for lat in reversed(windclim.LATS)))
        self.assertEqual(len(windclim.LONS), 72)
        self.assertEqual((windclim.LONS[0], windclim.LONS[-1]), (120.125, 279.875))
        for axis in (windclim.LATS, windclim.LONS):
            self.assertTrue(all(abs(b - a - 2.25) < 1e-9 for a, b in zip(axis, axis[1:])))

    def test_each_month_holds_a_row_of_cells_per_latitude(self):
        self.assertEqual(len(windclim.MONTHLY), 12)
        for month in windclim.MONTHLY:
            self.assertEqual(len(month), len(windclim.LATS))
            self.assertTrue(all(len(row) == len(windclim.LONS) for row in month))

    def test_the_base_is_version_2_0_s_whole_years_inside_the_normal(self):
        self.assertEqual(windclim.BASE, "1991-2018")
        self.assertIn("version 2.0", windclim.PRODUCT)

    def test_the_trades_blow_from_the_east_over_the_cold_tongue_in_september(self):
        # 1.125S 109.4W, where the south-east trades are at their strongest
        # in the southern spring.
        i, j = windclim.LATS.index(-1.125), windclim.LONS.index(250.625)
        self.assertLess(windclim.MONTHLY[8][i][j], -3.0)

    def test_every_cell_has_a_mean_land_as_well_as_sea(self):
        # CCMP's analysis has a value over land, New Guinea's 3.4S 140.4E
        # among them, as Harrison and Vecchi's ECMWF analysis did.
        for month in windclim.MONTHLY:
            self.assertTrue(all(value is not None for row in month for value in row))

    def test_a_block_is_hundredths_of_a_metre_a_second_and_a_gap_is_none(self):
        self.assertEqual(windclim._parse("123,-45,_\n6,-7,800", 3),
                         ((1.23, -0.45, None), (0.06, -0.07, 8.0)))
        with self.assertRaises(ValueError):
            windclim._parse("1,2\n3,4,5", 3)


# --- the events -----------------------------------------------------------------
T0 = datetime(2026, 9, 1, 6, tzinfo=timezone.utc)
HALF = timedelta(hours=12)
HEAD = "time,latitude,longitude,uwnd\nUTC,degrees_north,degrees_east,m s-1\n"


def _times(count: int, start: datetime = T0) -> list[datetime]:
    """``count`` analyses 12 hours apart from ``start``."""
    return [start + k * HALF for k in range(count)]


def _feed(times, anomaly) -> str:
    """ERDDAP's CSV of the feed over the base's cells: at each of ``times``
    each cell's base plus ``anomaly(when, lat, lon)``."""
    rows = []
    for when in times:
        base = winds.climate(when)
        stamp = f"{when:%Y-%m-%dT%H:%M:%SZ}"
        for i, lat in enumerate(windclim.LATS):
            for j, lon in enumerate(windclim.LONS):
                rows.append(f"{stamp},{lat},{lon},{base[i][j] + anomaly(when, lat, lon)}")
    return HEAD + "\n".join(rows) + "\n"


def _block(key: str, times, first: int, count: int, value: float = 3.0):
    """An anomaly of ``value`` over region ``key`` at analyses ``first`` to
    ``first + count - 1``, and none anywhere else or at any other time. A
    block of 3 m/s is above the threshold, smoothed, on exactly its own
    analyses: 2.25 at either end, 0.75 either side of it."""
    hot = set(times[first:first + count])
    region = winds.REGIONS_BY_KEY[key]
    return lambda when, lat, lon: value if when in hot and region.holds(lat, lon) else 0.0


def _sum(*parts):
    return lambda when, lat, lon: sum(part(when, lat, lon) for part in parts)


def _event(region: str, centre: datetime, peak: float) -> winds.Event:
    """An event as the overlap rule sees it: its region, centre and peak."""
    return winds.Event(region=region, first=centre - HALF * 3, last=centre + HALF * 2,
                       samples=6, centre=centre, peak=peak, point_peak=peak + 1.0,
                       point=(1.125, 160.625), measure=peak * 6 * 43200.0,
                       ongoing=False, from_start=False)


class TestRegions(unittest.TestCase):
    """Harrison and Vecchi's eight regions, and which of them border."""

    def test_the_eight_regions_are_harrison_and_vecchi_s(self):
        self.assertEqual(
            [(r.key, r.south, r.north, r.west, r.east) for r in winds.REGIONS],
            [("NW", 5, 15, 120, 150), ("N", 5, 15, 150, 180), ("NE", 5, 15, 180, 210),
             ("W", -5, 5, 130, 155), ("C", -5, 5, 155, 180), ("E", -5, 5, 180, 210),
             ("S", -15, -5, 150, 180), ("SE", -15, -5, 180, 210)])
        self.assertEqual(winds.EQUATORIAL, ("W", "C", "E"))

    def test_regions_border_when_they_share_over_half_the_shorter_edge(self):
        pairs = {frozenset((a.key, b.key)) for a in winds.REGIONS for b in winds.REGIONS
                 if winds.neighbours(a, b)}
        self.assertEqual(pairs, {frozenset(pair) for pair in (
            ("NW", "N"), ("N", "NE"), ("NW", "W"), ("N", "C"), ("NE", "E"),
            ("W", "C"), ("C", "E"), ("C", "S"), ("E", "SE"), ("S", "SE"))})
        # N and W share 150-155E, five degrees of W's twenty-five; W and S the same.
        region = winds.REGIONS_BY_KEY
        self.assertFalse(winds.neighbours(region["N"], region["W"]))
        self.assertFalse(winds.neighbours(region["W"], region["S"]))

    def test_a_region_holds_its_cells_and_says_where_it_is(self):
        west = winds.REGIONS_BY_KEY["W"]
        self.assertTrue(west.holds(-1.125, 131.375))
        self.assertFalse(west.holds(-1.125, 129.125))
        self.assertEqual(west.span, "130E-155E, 5S-5N")
        self.assertEqual(winds.REGIONS_BY_KEY["SE"].span, "180-150W, 15S-5S")

    def test_every_region_holds_the_base_s_cells_its_size_gives(self):
        counts = {r.key: sum(r.holds(lat, lon) for lat in windclim.LATS for lon in windclim.LONS)
                  for r in winds.REGIONS}
        self.assertEqual(counts, {"NW": 70, "N": 65, "NE": 65, "W": 44, "C": 44, "E": 52,
                                  "S": 65, "SE": 65})

    def test_no_cell_is_in_two_regions(self):
        # Harrison and Vecchi's edges held their points, five 2.5-degree
        # points in ten degrees of latitude; no cell of this grid is on one.
        cells = [(lat, lon) for r in winds.REGIONS for lat in windclim.LATS
                 for lon in windclim.LONS if r.holds(lat, lon)]
        self.assertEqual(len(cells), 470)
        self.assertEqual(len(set(cells)), 470)


class TestClimate(unittest.TestCase):
    """The base between months, linearly in time from each month's middle."""

    def test_at_a_month_s_middle_the_base_is_the_month_s_mean(self):
        # July's middle: fifteen and a half days after its first instant.
        self.assertEqual(winds.climate(datetime(2026, 7, 16, 12, tzinfo=timezone.utc)),
                         [list(row) for row in windclim.MONTHLY[6]])
        # A leap year's February's: fourteen and a half days in.
        self.assertEqual(winds.climate(datetime(2028, 2, 15, 12, tzinfo=timezone.utc)),
                         [list(row) for row in windclim.MONTHLY[1]])

    def test_halfway_between_two_middles_it_is_their_mean(self):
        got = winds.climate(datetime(2026, 8, 1, tzinfo=timezone.utc))
        july, august = windclim.MONTHLY[6], windclim.MONTHLY[7]
        self.assertAlmostEqual(got[6][20], (july[6][20] + august[6][20]) / 2, places=9)

    def test_across_the_year_s_end_december_meets_january(self):
        got = winds.climate(datetime(2027, 1, 1, tzinfo=timezone.utc))
        december, january = windclim.MONTHLY[11], windclim.MONTHLY[0]
        self.assertAlmostEqual(got[3][40], (december[3][40] + january[3][40]) / 2, places=9)
        # A quarter of the way from December's middle on.
        quarter = datetime(2026, 12, 16, 12, tzinfo=timezone.utc) + timedelta(days=7.75)
        self.assertAlmostEqual(winds.climate(quarter)[3][40],
                               december[3][40] + (january[3][40] - december[3][40]) / 4,
                               places=9)


class TestRegionalMean(unittest.TestCase):
    """A region's anomaly at an analysis: its cells' mean, weighted by latitude."""

    def test_a_region_s_mean_is_weighted_by_the_cosine_of_latitude(self):
        grid = [[lat for _lon in windclim.LONS] for lat in windclim.LATS]
        north = winds.REGIONS_BY_KEY["N"]
        rows = [lat for lat in windclim.LATS if north.south <= lat <= north.north]
        weights = [math.cos(math.radians(lat)) for lat in rows]
        expected = sum(w * lat for w, lat in zip(weights, rows)) / sum(weights)
        self.assertAlmostEqual(winds.regional(grid, north), expected, places=9)
        self.assertLess(winds.regional(grid, north), sum(rows) / len(rows))

    def test_a_region_short_of_three_quarters_of_its_cells_has_no_mean(self):
        west = winds.REGIONS_BY_KEY["W"]
        cells = [(i, j) for i, lat in enumerate(windclim.LATS)
                 for j, lon in enumerate(windclim.LONS) if west.holds(lat, lon)]
        for missing, valued in ((11, True), (12, False)):
            grid = [[1.0 for _lon in windclim.LONS] for _lat in windclim.LATS]
            for i, j in cells[:missing]:
                grid[i][j] = None
            with self.subTest(missing=missing):
                self.assertEqual(winds.regional(grid, west) is not None, valued)


class TestFilter(unittest.TestCase):
    """Harrison and Vecchi's three-point triangle filter on 12-hourly analyses."""

    def test_the_filter_is_a_quarter_a_half_and_a_quarter(self):
        times = _times(5)
        self.assertEqual(winds.smooth(times, [0.0, 4.0, 0.0, 8.0, 4.0]),
                         [None, 2.0, 3.0, 5.0, None])

    def test_its_half_power_is_at_two_and_three_quarter_days(self):
        # The response of 1/4 1/2 1/4 at a period of 2.75 days, sampled
        # every half day: 1/2 + 1/2 cos(2 pi * 0.5 / 2.75).
        quarter, half, _ = winds.FILTER
        response = half + 2 * quarter * math.cos(2 * math.pi * 0.5 / 2.75)
        self.assertAlmostEqual(response ** 2, 0.5, delta=0.005)
        self.assertEqual(winds.STEP, timedelta(hours=12))

    def test_a_neighbour_missing_or_not_12_hours_away_leaves_no_value(self):
        times = _times(3) + [T0 + HALF * 4, T0 + HALF * 5, T0 + HALF * 6]
        self.assertEqual(winds.smooth(times, [1.0, 1.0, 1.0, 1.0, None, 1.0]),
                         [None, 1.0, None, None, None, None])


class TestRuns(unittest.TestCase):
    """Runs of analyses above the threshold, 12 hours apart."""

    def test_a_run_is_every_analysis_strictly_above_two(self):
        times = _times(8)
        self.assertEqual(winds.runs(times, [None, 2.0, 2.5, 2.01, 2.0, 3.0, 3.0, None]),
                         [(2, 3), (5, 6)])

    def test_a_missing_analysis_or_a_gap_in_time_breaks_a_run(self):
        times = _times(4) + [T0 + HALF * 5, T0 + HALF * 6]
        self.assertEqual(winds.runs(times, [3.0, 3.0, None, 3.0, 3.0, 3.0]),
                         [(0, 1), (3, 3), (4, 5)])


class TestEvents(unittest.TestCase):
    """Westerly wind events found in a feed of the base plus an anomaly."""

    def test_six_analyses_above_two_are_an_event_and_five_are_not(self):
        times = _times(20)
        six = winds.analyse(_feed(times, _block("C", times, 6, 6)))
        self.assertEqual([(e.region, e.first, e.last, e.samples, e.days) for e in six.events],
                         [("C", times[6], times[11], 6, 3.0)])
        five = winds.analyse(_feed(times, _block("C", times, 6, 5)))
        self.assertEqual(five.events, ())
        self.assertEqual(five.building, ())

    def test_an_event_s_centre_peak_point_and_wind_measure(self):
        times = _times(20)
        ramp = {times[k]: v for k, v in zip(range(6, 13), (3.0, 3.0, 4.0, 6.0, 4.0, 3.0, 3.0))}
        central = winds.REGIONS_BY_KEY["C"]

        def anomaly(when, lat, lon):
            if when not in ramp or not central.holds(lat, lon):
                return 0.0
            # One cell blows 2 m/s harder than the rest of the region.
            return ramp[when] + (2.0 if (lat, lon) == (1.125, 167.375) else 0.0)

        got = winds.analyse(_feed(times, anomaly))
        (event,) = got.events
        smoothed = got.smoothed["C"]
        self.assertEqual(event.centre, times[9])
        self.assertAlmostEqual(event.peak, smoothed[9], places=9)
        self.assertAlmostEqual(event.point_peak, 8.0, places=6)
        self.assertEqual(event.point, (1.125, 167.375))
        run = smoothed[times.index(event.first):times.index(event.last) + 1]
        self.assertAlmostEqual(event.measure, sum(run) * 43200.0, places=3)
        self.assertFalse(event.ongoing)
        self.assertFalse(event.from_start)

    def test_an_event_reaching_the_latest_smoothed_analysis_is_under_way(self):
        times = _times(16)
        got = winds.analyse(_feed(times, _block("E", times, 9, 7)))
        (event,) = got.events
        # The latest analysis waits for the next to be smoothed.
        self.assertIsNone(got.smoothed["E"][-1])
        self.assertTrue(event.ongoing)
        self.assertEqual((event.first, event.last, event.samples), (times[9], times[14], 6))
        self.assertEqual(got.under_way, (event,))

    def test_a_gap_before_the_latest_analysis_leaves_the_run_under_way(self):
        # The last analysis comes a day after the one before it, so neither
        # of the two is smoothed: the run reaching the latest smoothed
        # analysis has not been seen to end.
        times = _times(15) + [T0 + HALF * 16]
        got = winds.analyse(_feed(times, _block("E", times, 7, 9)))
        (event,) = got.events
        self.assertEqual((event.first, event.last, event.samples), (times[7], times[13], 7))
        self.assertTrue(event.ongoing)

    def test_an_event_at_the_window_s_start_began_before_it(self):
        times = _times(16)
        got = winds.analyse(_feed(times, _block("W", times, 0, 8)))
        (event,) = got.events
        self.assertTrue(event.from_start)
        self.assertEqual(event.first, times[1])

    def test_a_run_under_way_short_of_three_days_is_building_and_not_counted(self):
        times = _times(16)
        got = winds.analyse(_feed(times, _block("C", times, 12, 4)))
        self.assertEqual(got.events, ())
        (building,) = got.building
        self.assertEqual((building.region, building.since, building.samples, building.days),
                         ("C", times[12], 3, 1.5))
        self.assertAlmostEqual(building.latest, 3.0, places=6)

    def test_events_in_two_regions_are_each_their_own(self):
        times = _times(30)
        got = winds.analyse(_feed(times, _sum(_block("N", times, 2, 6),
                                              _block("SE", times, 10, 8, 5.0))))
        self.assertEqual([(e.region, e.samples) for e in got.events], [("N", 6), ("SE", 8)])


class TestOverlaps(unittest.TestCase):
    """Events in bordering regions centred within three days count as one."""

    def test_bordering_events_within_three_days_count_as_the_stronger(self):
        west = _event("W", T0, 3.0)
        central = _event("C", T0 + timedelta(days=3), 4.5)
        got = {e.region: e for e in winds.overlaps([west, central])}
        self.assertEqual((got["W"].counted_as, got["W"].overlaps), ("C", ("C",)))
        self.assertEqual((got["C"].counted_as, got["C"].overlaps), ("C", ("W",)))

    def test_four_days_apart_or_not_bordering_they_are_their_own(self):
        apart = winds.overlaps([_event("W", T0, 3.0), _event("C", T0 + timedelta(days=4), 4.5)])
        self.assertEqual([(e.counted_as, e.overlaps) for e in apart], [("W", ()), ("C", ())])
        far = winds.overlaps([_event("N", T0, 3.0), _event("W", T0, 4.5)])
        self.assertEqual([(e.counted_as, e.overlaps) for e in far], [("N", ()), ("W", ())])

    def test_in_a_chain_each_counts_as_the_strongest_it_overlaps(self):
        chain = winds.overlaps([_event("W", T0, 5.0), _event("C", T0 + timedelta(days=2), 4.0),
                                _event("E", T0 + timedelta(days=4), 6.0)])
        self.assertEqual([e.counted_as for e in chain], ["W", "E", "E"])

    def test_an_event_overlapping_two_in_one_region_names_it_once(self):
        got = winds.overlaps([_event("E", T0, 3.0), _event("NE", T0 + timedelta(days=2), 4.0),
                              _event("E", T0 + timedelta(days=4), 5.0)])
        self.assertEqual([(e.region, e.overlaps, e.counted_as) for e in got],
                         [("E", ("NE",), "NE"), ("NE", ("E",), "E"), ("E", ("NE",), "E")])

    def test_the_run_finds_overlaps_between_its_events(self):
        times = _times(24)
        got = winds.analyse(_feed(times, _sum(_block("W", times, 4, 6),
                                              _block("C", times, 6, 6, 5.0))))
        self.assertEqual([(e.region, e.counted_as) for e in got.events], [("W", "C"), ("C", "C")])


class TestHovmoller(unittest.TestCase):
    """The day by day 5S-5N anomaly by longitude."""

    def test_a_row_a_day_the_band_s_cosine_weighted_mean_of_the_day(self):
        times = _times(6)

        def anomaly(when, lat, lon):
            return lat + (1.0 if when.hour == 18 else 0.0)

        got = winds.analyse(_feed(times, anomaly)).hovmoller
        self.assertEqual(got.x, windclim.LONS)
        self.assertEqual(got.y_labels, ("2026-09-01", "2026-09-02", "2026-09-03"))
        self.assertEqual(got.as_of, "2026-09-03")
        self.assertEqual(got.units, "m/s")
        # A symmetric band of latitudes cancels; the day's two analyses average.
        self.assertTrue(all(abs(value - 0.5) < 1e-6 for value in got.values[0]))

    def test_analyses_at_00z_and_12z_make_the_days_as_well(self):
        times = _times(4, datetime(2026, 9, 1, 0, tzinfo=timezone.utc))
        got = winds.analyse(_feed(times, lambda when, lat, lon: 2.0 * (when.hour == 12))).hovmoller
        self.assertEqual(got.y_labels, ("2026-09-01", "2026-09-02"))
        self.assertTrue(all(abs(value - 1.0) < 1e-6 for row in got.values for value in row))

    def test_a_window_not_ending_at_18z_has_its_end_days_from_their_one_analysis(self):
        # From 12Z: the first day has its 12Z analysis alone, the last its 00Z.
        times = _times(4, datetime(2026, 9, 1, 12, tzinfo=timezone.utc))
        got = winds.analyse(_feed(times, lambda when, lat, lon: 2.0 * (when.hour == 12))).hovmoller
        self.assertEqual(got.y_labels, ("2026-09-01", "2026-09-02", "2026-09-03"))
        for row, expected in zip(got.values, (2.0, 1.0, 0.0)):
            self.assertTrue(all(value is not None and abs(value - expected) < 1e-6
                                for value in row), row[:3])

    def test_a_day_without_an_analysis_is_a_row_of_nothing(self):
        times = _times(3) + _times(3, T0 + timedelta(days=3))
        got = winds.analyse(_feed(times, lambda *_: 1.0)).hovmoller
        self.assertEqual(got.y_labels, ("2026-09-01", "2026-09-02", "2026-09-03",
                                        "2026-09-04", "2026-09-05"))
        self.assertTrue(all(value is None for value in got.values[2]))


class TestAnalyse(unittest.TestCase):
    """The feed read whole: days, the days' values, and what it refuses."""

    def test_each_day_s_value_is_its_smoothed_analyses_mean(self):
        times = _times(8)
        got = winds.analyse(_feed(times, _block("C", times, 3, 1, 4.0)))
        # Smoothed C: 0, 1, 2, 1, 0 about the analysis of 4 m/s.
        self.assertEqual((got.first, got.last), (date(2026, 9, 1), date(2026, 9, 4)))
        self.assertAlmostEqual(got.daily[date(2026, 9, 2)]["C"], 1.5, places=6)
        self.assertAlmostEqual(got.daily[date(2026, 9, 3)]["C"], 0.5, places=6)
        self.assertEqual(got.daily[date(2026, 9, 1)]["C"], 0.0)

    def test_a_feed_not_on_the_base_s_cells_or_too_short_is_refused(self):
        with self.assertRaises(ValueError):
            winds.analyse(HEAD + "2026-09-01T06:00:00Z,0.125,160.125,1.0\n")
        times = _times(2)
        with self.assertRaises(ValueError):
            winds.analyse(_feed(times, lambda *_: 0.0))

    def test_an_analysis_listed_before_its_values_are_in_is_not_read(self):
        times = _times(8)
        late = f"{times[-1] + HALF:%Y-%m-%dT%H:%M:%SZ}"
        empty = "".join(f"{late},{lat},{lon},NaN\n" for lat in windclim.LATS
                        for lon in windclim.LONS)
        got = winds.analyse(_feed(times, lambda *_: 0.0) + empty)
        self.assertEqual(got.times[-1], times[-1])
        self.assertEqual(got.last, date(2026, 9, 4))

    def test_a_feed_with_no_smoothed_value_in_any_region_is_refused(self):
        names, units, *rows = _feed(_times(8), lambda *_: 0.0).splitlines()

        def kept_east_of(lon: float) -> str:
            """The feed with every value at or west of ``lon`` east NaN."""
            return "\n".join([names, units, *(
                row if float(row.split(",")[2]) > lon else row.rpartition(",")[0] + ",NaN"
                for row in rows)]) + "\n"

        six_hourly = [datetime(2026, 9, 1, hour, tzinfo=timezone.utc) for hour in (0, 6, 12)]
        for case, feed in (("every value NaN", kept_east_of(360.0)),
                           ("values only east of 150W, outside every region",
                            kept_east_of(210.0)),
                           ("analyses six hours apart, none smoothed",
                            _feed(six_hourly, lambda *_: 0.0))):
            with self.subTest(case), self.assertRaises(ValueError):
                winds.analyse(feed)


# --- the feed and the run -------------------------------------------------------
def _query(url: str) -> str:
    return urllib.parse.unquote(url.partition("?")[2])


def _fetched(key: str, text: str, error: str | None = None) -> sources.Fetched:
    source = sources.SOURCES_BY_KEY[key]
    return sources.Fetched(source, text, "2026-10-15T09:00:00+00:00", False, "",
                           error=error, url=source.url)


def _axis(start: float, stride: int, stop: float) -> tuple[float, ...]:
    """The values a griddap range asks of CCMP's quarter degree."""
    step = 0.25 * stride
    return tuple(start + step * k for k in range(round((stop - start) / step) + 1))


class TestFeed(unittest.TestCase):
    """CCMP's near-real-time analyses, asked on the base's cells."""

    def test_it_asks_180_days_twice_a_day_on_the_base_s_cells(self):
        source = sources.SOURCES_BY_KEY["wind_daily"]
        self.assertTrue(source.url.startswith(sources.CCMP_NRT + "?"), source.url)
        self.assertEqual(_query(source.url),
                         "uwnd[last-718:2:last][(-14.625):9:(14.625)][(120.125):9:(279.875)]")
        # Every other one of the last 719 six-hourly analyses: 360, 12 hours apart.
        self.assertEqual(len(range(0, 719, 2)), 360)
        self.assertEqual(_axis(-14.625, 9, 14.625), windclim.LATS)
        self.assertEqual(_axis(120.125, 9, 279.875), windclim.LONS)

    def test_it_is_spatial_on_one_server_and_kept_out_of_the_archive(self):
        source = sources.SOURCES_BY_KEY["wind_daily"]
        self.assertEqual((source.tier, source.archive, source.final, source.fallback),
                         ("spatial", False, "", ()))
        self.assertIn("Remote Sensing Systems", source.agency)
        self.assertIn("PIFSC", source.agency)
        self.assertEqual(sources.probe_url(source.url), sources.CCMP_NRT + "?time%5Blast%5D")


class TestRun(unittest.TestCase):
    """The run finds the events, and a feed that fails costs only them."""

    def test_the_run_finds_the_events(self):
        times = _times(20)
        feed = _feed(times, _block("C", times, 6, 6))
        state = pipeline.build_spatial({"wind_daily": _fetched("wind_daily", feed)})
        self.assertEqual([(e.region, e.samples) for e in state.winds.events], [("C", 6)])
        self.assertEqual(state.notes, [])

    def test_a_feed_that_failed_leaves_no_events_and_no_note(self):
        state = pipeline.build_spatial(
            {"wind_daily": _fetched("wind_daily", "", error="RuntimeError: HTTP Error 503")})
        self.assertIsNone(state.winds)
        self.assertEqual(state.notes, [])

    def test_a_broken_answer_is_noted_and_costs_only_itself(self):
        boxes = ("time,zlev,latitude,longitude,anom\nUTC,m,degrees_north,degrees_east,degree_C\n"
                 "2026-10-12T12:00:00Z,0.0,0.125,200.125,2.0\n")
        state = pipeline.build_spatial({"wind_daily": _fetched("wind_daily", HEAD),
                                        "nino_daily": _fetched("nino_daily", boxes)})
        self.assertIsNone(state.winds)
        self.assertTrue(any(note.startswith("westerly wind events:") for note in state.notes),
                        state.notes)
        self.assertEqual([d.day for d in state.nino_daily], ["2026-10-12"])


# --- the card -------------------------------------------------------------------
def _frame(html: str) -> tuple[float, ...]:
    """A plot's area, left, top, width and height, from the frame round it."""
    found = re.findall(r'<rect x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" '
                       r'height="([\d.]+)" fill="none" stroke="var\(--axis\)"', html)
    return tuple(float(value) for value in found[-1])


def _days_field(first: date, count: int) -> grids.Field:
    """A Hovmoller of ``count`` days from ``first`` on the base's longitudes."""
    days = [(first + timedelta(days=k)).isoformat() for k in range(count)]
    return grids.Field(x=windclim.LONS, y=tuple(float(k) for k in range(count)),
                       values=tuple(tuple(float(k % 5 - 2) for _ in windclim.LONS)
                                    for k in range(count)),
                       label="Equatorial 10 m zonal wind anomaly", units="m/s",
                       x_name="longitude", y_name="time", as_of=days[-1], y_labels=tuple(days))


def _caption(html: str) -> str:
    """A card's caption, all its paragraphs."""
    return " ".join(re.findall(r'<p class="caption">(.*?)</p>', html, re.S))


def _table(html: str, caption: str) -> str:
    start = html.index(f"Table view &mdash; {caption}")
    return html[start:html.index("</table>", start)]


class TestHovmollerPanel(unittest.TestCase):
    """The Hovmoller's outlined boxes and its month ticks."""

    def test_an_outline_spans_its_longitudes_and_days_with_its_letter(self):
        grid = _days_field(date(2026, 8, 1), 20)
        html = fields.hovmoller(grid, "t", "c", outlines=((155.0, 180.0, 4, 9, "C"),))
        left, top, width, height = _frame(html)
        ((x, y, w, h),) = [tuple(map(float, found)) for found in re.findall(
            r'<rect class="outline" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" '
            r'height="([\d.]+)"', html)]

        def sx(lon):
            return left + (lon - grid.x[0]) / (grid.x[-1] - grid.x[0]) * width

        def sy(row):
            return top + (row + 0.5) / grid.rows * height

        self.assertAlmostEqual(x, sx(155.0), delta=0.11)
        self.assertAlmostEqual(x + w, sx(180.0), delta=0.21)
        self.assertAlmostEqual(y, sy(3.5), delta=0.11)
        self.assertAlmostEqual(y + h, sy(9.5), delta=0.21)
        self.assertEqual(re.findall(r'class="boxlabel"[^>]*>([^<]+)</text>', html), ["C"])

    def test_months_are_ticked_when_asked_and_quarters_otherwise(self):
        grid = _days_field(date(2026, 4, 17), 180)

        def ticks(html):
            return re.findall(r'text-anchor="end" class="tick">([\d-]+)</text>', html)

        self.assertEqual(ticks(fields.hovmoller(grid, "t", "c")), ["2026-04", "07", "10"])
        self.assertEqual(ticks(fields.hovmoller(grid, "t", "c", months=fields.EVERY_MONTH)),
                         ["2026-04", "05", "06", "07", "08", "09", "10"])
        self.assertEqual(fields.QUARTERS, ("01", "04", "07", "10"))


class TestBands(unittest.TestCase):
    """Spans of days shaded on a plot of days."""

    def test_a_band_is_a_lane_of_its_line_s_colour_over_its_days(self):
        first = date(2026, 9, 1)
        values = {first + timedelta(days=k): {"W": 1.0, "C": 2.5, "E": 0.5} for k in range(10)}
        bands = ((first + timedelta(days=2), first + timedelta(days=4), "C"),
                 (first + timedelta(days=6), first + timedelta(days=7), "W"))
        html = daily._plot(values, daily.WINDS, bands=bands).svg("t", "d")
        hits = [(float(x), float(y), float(w)) for x, y, w in re.findall(
            r'<rect class="hit" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)"', html)]
        central, west = [(float(x), float(y), float(w), float(h), fill)
                         for x, y, w, h, fill in re.findall(
                             r'<rect class="band" x="([\d.]+)" y="([\d.]+)" width="([\d.]+)" '
                             r'height="([\d.]+)" fill="([^"]+)"', html)]
        self.assertEqual((central[4], west[4]), ("var(--s2)", "var(--s1)"))
        self.assertAlmostEqual(central[0], hits[2][0], delta=0.11)
        self.assertAlmostEqual(central[0] + central[2], hits[4][0] + hits[4][2], delta=0.21)
        # A lane a line, in the legend's order down from the plot's top, in
        # the room above the highest value that its axis leaves.
        top = hits[0][1]
        self.assertLess(west[1], central[1])
        self.assertLessEqual(top, west[1])
        self.assertLessEqual(central[1] + central[3], top + 25)
        self.assertLess(html.index('class="band"'), html.index('class="dayline"'))


class TestWindCard(unittest.TestCase):
    """Westerly wind events day by day, after the SOI's days."""

    def test_the_equatorial_regions_the_threshold_and_a_hover_a_day(self):
        times = _times(40)
        html = daily.wind_card(winds.analyse(_feed(times, _block("C", times, 10, 8))))
        self.assertIn('<section class="card" id="wind-events">', html)
        self.assertIn("<h2>Westerly wind events day by day</h2>", html)
        for colour in ("var(--s1)", "var(--s2)", "var(--s3)"):
            self.assertEqual(html.count(f'class="dayline" stroke="{colour}"'), 1, colour)
        for name in ("West", "Central", "East"):
            self.assertIn(f"</span>{name}</span>", html)
        self.assertIn("event threshold +2 m/s", html)
        self.assertEqual(html.count('class="hit"'), 20)
        self.assertIn('data-label="10 Sep 2026"', html)
        self.assertIn("each row the mean of the day&rsquo;s analyses;", html)

    def test_each_equatorial_event_is_shaded_and_outlined_and_no_other(self):
        times = _times(40)
        got = winds.analyse(_feed(times, _sum(_block("C", times, 10, 8),
                                              _block("N", times, 20, 8))))
        html = daily.wind_card(got)
        self.assertEqual(re.findall(r'class="band"[^>]*fill="([^"]+)"', html), ["var(--s2)"])
        self.assertEqual(re.findall(r'class="boxlabel"[^>]*>([^<]+)</text>', html), ["C"])
        self.assertIn("Central event", html)

    def test_an_event_under_way_leads_the_caption_with_its_days_and_peak(self):
        times = _times(40)
        got = winds.analyse(_feed(times, _block("E", times, 25, 15, 4.0)))
        (event,) = got.under_way
        caption = _caption(daily.wind_card(got))
        self.assertIn("under way in the east region (180&ndash;150W, 5S&ndash;5N)", caption)
        self.assertIn(f"<strong>{event.days:g} days</strong>", caption)
        self.assertIn(f"peaking at {event.peak:+.1f} m/s on", caption)
        self.assertNotIn(f"at most {event.peak:+.1f}", caption)
        self.assertNotIn("longer than any", caption)

    def test_an_event_under_way_since_before_the_window_is_at_least_its_days(self):
        times = _times(40)
        caption = _caption(daily.wind_card(winds.analyse(_feed(times, _block("C", times, 0, 40)))))
        self.assertIn("<strong>at least 19 days</strong> above +2 m/s since before 1 Sep 2026",
                      caption)

    def test_with_none_under_way_the_caption_names_the_latest(self):
        times = _times(40)
        got = winds.analyse(_feed(times, _sum(_block("W", times, 4, 6),
                                              _block("SE", times, 16, 8, 5.0))))
        caption = _caption(daily.wind_card(got))
        self.assertIn("No event is under way.", caption)
        self.assertIn("The latest, in the south-east region (180&ndash;150W, 15S&ndash;5S), "
                      "ran 4 days from 9 Sep 2026 to 12 Sep 2026, peaking at +5.0 m/s.", caption)

    def test_an_event_longer_than_any_harrison_and_vecchi_found_is_called_sustained(self):
        times = _times(80)
        got = winds.analyse(_feed(times, _sum(_block("C", times, 10, 70),
                                              _block("N", times, 8, 72))))
        self.assertEqual([event.days for event in got.under_way], [35.5, 34.5])
        caption = _caption(daily.wind_card(got))
        self.assertEqual(caption.count(" (longer than any in Harrison and Vecchi&rsquo;s list)"), 2)
        self.assertEqual(caption.count("Harrison and Vecchi&rsquo;s 351 events of 1986&ndash;1995 "
                                       "lasted 32.5 days at most: a run longer is a sustained "
                                       "westerly anomaly more than a burst."), 1)

    def test_with_no_event_the_caption_says_so(self):
        times = _times(40)
        caption = _caption(daily.wind_card(winds.analyse(_feed(times, lambda *_: 0.0))))
        self.assertIn("No westerly wind event in these 20 days.", caption)

    def test_a_building_run_is_named_and_never_counted(self):
        times = _times(40)
        got = winds.analyse(_feed(times, _block("W", times, 35, 5)))
        caption = _caption(daily.wind_card(got))
        self.assertIn("Building, not yet three days: the west region "
                      "(130E&ndash;155E, 5S&ndash;5N), 2 days above +2 m/s, latest +3.0 m/s.",
                      caption)
        self.assertIn("No westerly wind event in these 20 days.", caption)

    def test_the_caption_gives_the_definition_the_base_the_checks_and_the_months(self):
        times = _times(40)
        caption = _caption(daily.wind_card(winds.analyse(_feed(times, lambda *_: 0.0))))
        for words in ("Remote Sensing Systems", "PIFSC", "Harrison and Vecchi (1997)",
                      "above +2 m/s", "half power at 2.75 days", "count as the stronger",
                      "CCMP version 2.0", "1991&ndash;2018", "0.20 m/s at most on average",
                      "0.19&ndash;0.51 m/s rms", "0.88&ndash;0.95 mooring by mooring",
                      "0.7 m/s less westerly", "TAO measures at 4 m and CCMP is for 10 m",
                      "coupling card", "850 hPa", "last weeks"):
            self.assertIn(words, caption)

    def test_the_table_lists_every_event_latest_first_in_all_eight_regions(self):
        times = _times(40)
        got = winds.analyse(_feed(times, _sum(_block("N", times, 2, 6),
                                              _block("SE", times, 16, 8, 5.0))))
        table = _table(daily.wind_card(got), "westerly wind events")
        self.assertEqual(re.findall(r"<tr><td[^>]*>([A-Z]+)</td>", table), ["SE", "N"])
        for head in ("Type", "Region", "First", "Last", "Days", "Centre", "Peak (smoothed), m/s",
                     "Point peak, m/s", "Where", "Wind measure, 10⁶ m", "Counts as"):
            self.assertIn(f">{head}</th>", table)
        self.assertIn("south-east, 180–150W, 15S–5S", table)
        self.assertIn("2026-09-09 06Z", table)

    def test_an_event_under_way_heads_the_table_however_early_it_began(self):
        times = _times(40)
        got = winds.analyse(_feed(times, _sum(_block("C", times, 4, 36),
                                              _block("N", times, 10, 8))))
        table = _table(daily.wind_card(got), "westerly wind events")
        self.assertEqual(re.findall(r"<tr><td[^>]*>([A-Z]+)</td>", table), ["C", "N"])

    def test_an_overlapping_event_counts_as_the_stronger_in_the_table(self):
        times = _times(24)
        got = winds.analyse(_feed(times, _sum(_block("W", times, 4, 6),
                                              _block("C", times, 6, 6, 5.0))))
        table = _table(daily.wind_card(got), "westerly wind events")
        rows = {cells[0]: cells for cells in
                (re.findall(r"<td[^>]*>([^<]*)</td>", row)
                 for row in re.findall(r"<tr>(.*?)</tr>", table)) if cells}
        self.assertEqual(rows["W"][10], "C")
        self.assertEqual(rows["C"][10], "itself (overlaps W)")

    def test_an_event_under_way_and_one_from_the_start_say_so_in_the_table(self):
        times = _times(40)
        got = winds.analyse(_feed(times, _sum(_block("W", times, 0, 8),
                                              _block("E", times, 30, 10))))
        table = _table(daily.wind_card(got), "westerly wind events")
        self.assertIn("under way", table)
        self.assertIn("began before 1 Sep 2026", table)

    def test_an_event_under_way_since_before_the_window_says_both_in_the_table(self):
        times = _times(40)
        table = _table(daily.wind_card(winds.analyse(_feed(times, _block("C", times, 0, 40)))),
                       "westerly wind events")
        self.assertIn(">under way; began before 1 Sep 2026</td>", table)

    def test_a_latest_day_more_than_four_days_old_says_how_far_behind(self):
        times = _times(40)
        self.assertIn("days behind", daily.wind_card(winds.analyse(_feed(times, lambda *_: 0.0))))
        now = datetime.now(timezone.utc).replace(hour=6, minute=0, second=0, microsecond=0)
        recent = _times(8, now - 7 * HALF)
        self.assertNotIn("days behind",
                         daily.wind_card(winds.analyse(_feed(recent, lambda *_: 0.0))))

    def test_under_two_days_or_without_the_feed_there_is_no_card(self):
        self.assertEqual(daily.wind_card(None), "")
        got = winds.analyse(_feed(_times(4), lambda *_: 0.0))
        self.assertEqual(daily.wind_card(replace(got, daily={got.first: got.daily[got.first]})),
                         "")


# --- the JSON, the report and the alert -------------------------------------------
def _under_way_and_past() -> winds.Winds:
    """Twenty days: an event in the north region from the 2nd to the 5th, one
    under way in the central region since the 14th, and a run building in the
    west region."""
    times = _times(40)
    return winds.analyse(_feed(times, _sum(_block("N", times, 2, 8),
                                           _block("C", times, 26, 14, 4.0),
                                           _block("W", times, 36, 4))))


class TestJson(unittest.TestCase):
    """latest.json's spatial.wind_events, at schema 12."""

    def test_without_the_feed_the_block_is_null(self):
        self.assertIsNone(dashboard._winds_json(None))

    def test_the_block_gives_the_window_the_regions_and_their_days(self):
        got = _under_way_and_past()
        block = json.loads(json.dumps(dashboard._winds_json(got)))
        self.assertIn("Harrison and Vecchi (1997)", block["method"])
        self.assertIn("CCMP v2.1", block["product"])
        self.assertIn(windclim.BASE, block["base"])
        self.assertEqual(block["threshold_m_s"], 2.0)
        self.assertEqual((block["first_day"], block["last_day"], block["latest_analysis_utc"]),
                         ("2026-09-01", "2026-09-20", "2026-09-20T18:00:00Z"))
        self.assertEqual([region["key"] for region in block["regions"]],
                         ["NW", "N", "NE", "W", "C", "E", "S", "SE"])
        self.assertEqual(block["regions"][5], {"key": "E", "name": "east", "lat": [-5, 5],
                                               "lon_east": [180, 210]})
        self.assertEqual(len(block["daily"]), 20)
        self.assertEqual(block["daily"][-1], {"day": "2026-09-20", "anomaly_m_s": {
            "NW": 0.0, "N": 0.0, "NE": 0.0, "W": 3.0, "C": 4.0, "E": 0.0, "S": 0.0, "SE": 0.0}})
        # A day a region has no smoothed analysis is null for it.
        holed = replace(got, daily={**got.daily, got.last: {"C": 4.0}})
        self.assertEqual(dashboard._winds_json(holed)["daily"][-1]["anomaly_m_s"]["W"], None)

    def test_the_block_gives_each_event_and_the_runs_building(self):
        got = _under_way_and_past()
        _north, central = got.events
        block = json.loads(json.dumps(dashboard._winds_json(got)))
        self.assertEqual([event["region"] for event in block["events"]], ["N", "C"])
        self.assertEqual(block["events"][1], {
            "region": "C", "first_utc": "2026-09-14T06:00:00Z",
            "last_utc": "2026-09-20T06:00:00Z", "days": 6.5,
            "centre_utc": f"{central.centre:%Y-%m-%dT%H:%M:%SZ}",
            "peak_m_s": 4.0, "point_peak_m_s": 4.0,
            "point": {"lat": central.point[0], "lon_east": central.point[1]},
            "wind_measure_m": round(central.measure), "under_way": True,
            "began_before_window": False, "overlaps": [], "counted_as": "C"})
        self.assertFalse(block["events"][0]["under_way"])
        self.assertEqual(block["building"], [{"region": "W", "since_utc": "2026-09-19T06:00:00Z",
                                              "days": 1.5, "latest_m_s": 3.0}])

    def test_an_overlapping_event_counts_as_the_stronger_in_the_block(self):
        times = _times(24)
        block = dashboard._winds_json(winds.analyse(_feed(
            times, _sum(_block("W", times, 4, 6), _block("C", times, 6, 6, 5.0)))))
        self.assertEqual([(event["region"], event["overlaps"], event["counted_as"])
                          for event in block["events"]], [("W", ["C"], "C"), ("C", ["W"], "C")])


def _flat(text: str) -> str:
    """Wrapped report text as one line: a line broken after a hyphen joins
    the next without a space."""
    return " ".join(re.sub(r"-\n +", "-", text).split())


class TestReport(unittest.TestCase):
    """The report's westerly wind events, after its monthly westerly forcing."""

    def test_without_the_feed_there_are_no_lines(self):
        self.assertEqual(report._wind_lines(None), [])

    def test_what_is_under_way_and_building_then_the_events_latest_first(self):
        lines = report._wind_lines(_under_way_and_past())
        text = "\n".join(lines)
        flat = _flat(text)
        self.assertTrue(all(len(line) <= report.WIDTH and line.isascii() for line in lines))
        self.assertIn("near-real-time 10 m winds, 2026-09-01 to 2026-09-20: 2 events in the "
                      "eight regions.", flat)
        self.assertIn("Under way in the central region (C, 155E-180, 5S-5N): 6.5 days above "
                      "+2 m/s since 2026-09-14 06Z, peaking at +4.0 m/s on", flat)
        self.assertRegex(flat, r"peaking at \+4\.0 m/s on 2026-09-\d\d\. Building")
        self.assertIn("Building in the west region (W, 130E-155E, 5S-5N): 1.5 days above "
                      "+2 m/s, latest +3.0 m/s; counted from three days.", flat)
        self.assertRegex(text, r"\n  C +2026-09-14 06Z +under way +6\.5 +\+4\.0 +itself\n")
        self.assertRegex(text, r"\n  N +2026-09-02 06Z +2026-09-05 18Z +4 +\+3\.0 +itself\n")
        self.assertLess(text.index("\n  C "), text.index("\n  N "))

    def test_an_event_under_way_heads_the_events_however_early_it_began(self):
        times = _times(40)
        got = winds.analyse(_feed(times, _sum(_block("C", times, 4, 36),
                                              _block("N", times, 10, 8))))
        text = "\n".join(report._wind_lines(got))
        self.assertEqual(re.findall(r"^  (C|N) +2026-", text, re.M), ["C", "N"])

    def test_the_equatorial_regions_latest_days_and_the_note(self):
        text = "\n".join(report._wind_lines(_under_way_and_past()))
        self.assertRegex(text, r"\n +West +Central +East\n  2026-09-20 +\+3\.00 +\+4\.00 +\+0\.00\n")
        self.assertEqual(len(re.findall(r"^  2026-09-\d\d ", text, re.M)), report.DAILY_ROWS)
        flat = _flat(text)
        for words in ("half power at 2.75 days", "count as the stronger",
                      "NW 120E-150E, 5N-15N", "SE 180-150W, 15S-5S", "CCMP version 2.0",
                      "1991-2018", "0.20 m/s at most on average", "0.19-0.51 m/s rms",
                      "0.88-0.95 mooring by mooring", "0.7 m/s less westerly",
                      "TAO measures at 4 m and CCMP is for 10 m", "last weeks"):
            self.assertIn(words, flat)

    def test_an_event_since_before_the_window_is_at_least_its_days(self):
        times = _times(40)
        text = "\n".join(report._wind_lines(winds.analyse(_feed(times, _block("C", times, 0, 40)))))
        self.assertIn("Under way in the central region (C, 155E-180, 5S-5N): at least 19 days "
                      "above +2 m/s since before 2026-09-01 18Z", _flat(text))
        self.assertRegex(text, r"\n  C +2026-09-01 18Z\* +under way +19 ")
        self.assertIn("* Began before the window", text)
        quiet = "\n".join(report._wind_lines(_under_way_and_past()))
        self.assertNotIn("*", quiet)

    def test_an_event_longer_than_any_harrison_and_vecchi_found_is_called_sustained(self):
        times = _times(80)
        got = winds.analyse(_feed(times, _block("C", times, 10, 70)))
        self.assertIn("; longer than any of the 351 events in Harrison and Vecchi's 1986-1995 "
                      "list (at most 32.5 days): a sustained westerly anomaly more than a burst.",
                      _flat("\n".join(report._wind_lines(got))))

    def test_with_none_under_way_it_says_so(self):
        times = _times(40)
        text = "\n".join(report._wind_lines(winds.analyse(_feed(times, _block("N", times, 2, 8)))))
        self.assertIn("No event under way.", text)
        self.assertNotIn("Building", text)
        quiet = "\n".join(report._wind_lines(winds.analyse(_feed(times, lambda *_: 0.0))))
        self.assertIn("2026-09-01 to 2026-09-20: no event in the eight regions.", _flat(quiet))
        self.assertNotRegex(quiet, r"\n  type +first +last")


FIXTURES = ROOT / "tests" / "fixtures"


def _assessment():
    """The classification on the test fixtures, as the alert rules take it."""
    def text(name: str) -> str:
        return (FIXTURES / name).read_text(encoding="utf-8")
    return classify.assess(parsers.parse_oni(text("oni.txt")), parsers.parse_roni(text("roni.txt")),
                           parsers.parse_weekly_sst(text("weekly.for")),
                           parsers.parse_soi(text("soi.txt"))["standardized"],
                           parsers.parse_mei(text("mei.txt")))


class TestAlert(unittest.TestCase):
    """An equatorial event under way raises an INFO alert; nothing else does."""

    def test_an_equatorial_event_under_way_raises_an_info_alert(self):
        got = _under_way_and_past()
        (event,) = got.under_way
        (alert,) = alerts.wind_rules(got)
        self.assertEqual((alert.code, alert.level, alert.kind), ("wwe_c", alerts.INFO, "state"))
        self.assertEqual(alert.title,
                         "Westerly wind event under way: central region, 155E-180, 5S-5N")
        self.assertIn("6.5 days above +2 m/s since 2026-09-14 06Z", alert.detail)
        self.assertIn("winds to 2026-09-20", alert.detail)
        self.assertIn("peaking at +4.0 m/s on", alert.detail)
        self.assertNotIn("longer than any", alert.detail)
        self.assertTrue(alert.detail.endswith(
            ". Equatorial westerly anomalies force downwelling Kelvin waves east."), alert.detail)
        self.assertEqual(alert.value, round(event.peak, 2))

    def test_an_event_since_before_the_window_is_at_least_its_days(self):
        times = _times(40)
        (alert,) = alerts.wind_rules(winds.analyse(_feed(times, _block("C", times, 0, 40))))
        self.assertIn("at least 19 days above +2 m/s since before 2026-09-01 18Z", alert.detail)

    def test_an_event_longer_than_any_harrison_and_vecchi_found_is_called_sustained(self):
        times = _times(80)
        (alert,) = alerts.wind_rules(winds.analyse(_feed(times, _block("C", times, 10, 70))))
        self.assertIn("; longer than any of the 351 events in Harrison and Vecchi's 1986-1995 "
                      "list (at most 32.5 days): a sustained westerly anomaly more than a burst.",
                      alert.detail)

    def test_an_off_equatorial_event_a_finished_one_or_a_building_run_raises_none(self):
        times = _times(40)
        for anomaly in (_block("N", times, 26, 14, 4.0),    # under way, off the equator
                        _block("C", times, 4, 10, 4.0),     # over
                        _block("C", times, 36, 4)):         # building
            self.assertEqual(alerts.wind_rules(winds.analyse(_feed(times, anomaly))), [])

    def test_an_event_counted_as_a_stronger_one_says_so(self):
        times = _times(24)
        # Peaks a step above each run's level fix the centres half a day apart.
        got = winds.analyse(_feed(times, _sum(
            _block("W", times, 12, 12), _block("W", times, 18, 1, 1.0),
            _block("C", times, 14, 10, 5.0), _block("C", times, 19, 1, 1.0))))
        raised = {alert.code: alert for alert in alerts.wind_rules(got)}
        self.assertEqual(set(raised), {"wwe_w", "wwe_c"})
        self.assertIn("counts as the stronger C event it overlaps", raised["wwe_w"].detail)
        self.assertNotIn("counts as", raised["wwe_c"].detail)

    def test_evaluate_raises_it_from_the_winds_it_is_given(self):
        assessment = _assessment()
        got = _under_way_and_past()
        self.assertIn("wwe_c", {alert.code for alert in alerts.evaluate(assessment, winds=got)})
        self.assertNotIn("wwe_c", {alert.code for alert in alerts.evaluate(assessment)})


class TestDocumented(unittest.TestCase):
    """The README says what the events are, where they come from and where
    they go."""

    def test_the_readme_has_the_events(self):
        readme = " ".join((ROOT / "README.md").read_text(encoding="utf-8").split())
        for words in ("**Westerly wind events day by day.**", "Harrison and Vecchi (1997)",
                      "ccmp-daily-v2-1-NRT", "tools/vendor_winds.py",
                      "0.20 m/s at most on average", "correlates at 0.88–0.95",
                      "0.7 m/s less westerly", "4 m above the sea",
                      "a sustained westerly anomaly more than a burst", "Schema 12 adds",
                      "`spatial.wind_events`",
                      "`wwe_c`", "All 50 feeds", "Gridded and mooring feeds (14)"):
            self.assertIn(words, readme)


CACHE = ROOT / "data" / "raw"


@unittest.skipUnless((CACHE / "oni.cache").exists() and (CACHE / "sst_pacific.cache").exists(),
                     "no cached feeds; run `python track.py` once first")
class TestOnThePage(unittest.TestCase):
    """A whole run, offline on the cached feeds, with the wind feed's answer."""

    @classmethod
    def setUpClass(cls):
        times = _times(60, datetime(2026, 9, 14, 6, tzinfo=timezone.utc))
        feed = _feed(times, _block("C", times, 44, 16))
        # LongPaddock's file, which the cache may not hold, for the SOI's card.
        soi = "Year Day  Tahiti  Darwin     SOI\n" + "".join(
            f"2026 {n:3d} 1013.00 1009.00 {(150 - n) / 10:7.2f}\n" for n in range(150, 287))
        real = sources.fetch_all

        def fetch_all(*args, **kwargs):
            fetched = real(*args, **kwargs)
            fetched["wind_daily"] = _fetched("wind_daily", feed)
            fetched["soi_daily"] = _fetched("soi_daily", soi)
            return fetched

        cls.tmp = tempfile.TemporaryDirectory()
        with mock.patch.object(sources, "fetch_all", fetch_all):
            cls.state = pipeline.run(CACHE, Path(cls.tmp.name) / "w.db", offline=True, leads=9)
        cls.html = dashboard.render(cls.state)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_card_follows_the_soi_s_days(self):
        page = self.html
        self.assertLess(page.index('id="soi-daily"'), page.index('id="wind-events"'))
        self.assertLess(page.index('id="wind-events"'), page.index('id="forecast"'))

    def test_the_json_gives_the_events_since_schema_12_and_null_without_the_feed(self):
        data = json.loads(json.dumps(dashboard.payload(self.state)))
        self.assertEqual(data["schema"], 14)
        events = data["spatial"]["wind_events"]["events"]
        self.assertEqual([(event["region"], event["under_way"]) for event in events],
                         [("C", True)])
        bare = replace(self.state, spatial=replace(self.state.spatial, winds=None))
        self.assertIsNone(dashboard.payload(bare)["spatial"]["wind_events"])

    def test_the_run_raises_the_alert_for_the_event_under_way(self):
        self.assertIn("wwe_c", {alert.code for alert in self.state.alert_set.alerts})

    def test_the_report_gives_the_events_after_the_monthly_westerly_forcing(self):
        text = report.render(self.state, ("atmosphere",))
        self.assertLess(text.index("Westerly forcing"), text.index("Westerly wind events"))
        self.assertIn("Under way in the central region (C, 155E-180, 5S-5N)", _flat(text))


if __name__ == "__main__":
    unittest.main()
