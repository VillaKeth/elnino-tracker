"""Regression tests for the parsers and the classification chain.

The fixtures reproduce the awkward parts of each NOAA format, so if a feed
changes shape these fail before a bad number reaches the dashboard.
"""

from __future__ import annotations

import dataclasses
import http.client
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import threading
import unittest
from datetime import date, datetime, timezone
from unittest import mock
from html import escape, unescape
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).resolve().parent / "fixtures"

from elnino import (  # noqa: E402
    alerts, atlas, atlasdata, atlasview, atmosphere, coastline, composite,
    cyclones, dashboard, exposure, fields, forecast, geo, globe, grids, history, impacts,
    jtwc, kml, live,
    outlook, panels, parsers, pipeline, relief, report, sources, space3d, storage, stormdesk, storms,
    tcproducts,
    stormfury, subsurface, svg,
    verification, worldmap,
)
from elnino.classify import (  # noqa: E402
    Episode, assess, current_episode, diagnose_scale, find_analogs,
    find_episodes, intensity_tier,
)
from elnino.parsers import MonthValue, SeasonValue  # noqa: E402


def anchor_table(text: list[str]) -> tuple[str, list[str]]:
    """The report's atlas anchor table: its header, and its rows."""
    (at,) = [i for i, line in enumerate(text) if line.strip().startswith("place ")]
    rows = []
    for line in text[at + 1:]:
        if not line.strip():
            break
        rows.append(line)
    return text[at], rows


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class TestParsers(unittest.TestCase):
    def test_oni_skips_header_and_keeps_order(self):
        result = parsers.parse_oni(fixture("oni.txt"))
        self.assertEqual(len(result), 5)
        self.assertEqual(result[-1].label, "JJA 2026")
        self.assertAlmostEqual(result[-1].value, 1.80)
        self.assertAlmostEqual(result[0].value, -1.32)

    def test_oni_season_centre_month(self):
        self.assertEqual(SeasonValue("DJF", 2026, 0.0).centre, date(2026, 1, 1))
        self.assertEqual(SeasonValue("JJA", 2026, 0.0).centre, date(2026, 7, 1))
        self.assertEqual(SeasonValue("NDJ", 2026, 0.0).centre, date(2026, 12, 1))

    def test_roni_three_column_format(self):
        result = parsers.parse_roni(fixture("roni.txt"))
        self.assertEqual(len(result), 4)
        self.assertAlmostEqual(result[-1].value, 1.36)

    def test_weekly_splits_glued_negative_anomalies(self):
        """' 30DEC2020     22.2-1.3 ...' must yield 22.2 and -1.3, not 22.2-1.3."""
        result = parsers.parse_weekly_sst(fixture("weekly.for"))
        self.assertEqual(len(result), 3)
        first = result[0]
        self.assertEqual(first.week_ending, date(2020, 12, 30))
        self.assertAlmostEqual(first.nino12_sst, 22.2)
        self.assertAlmostEqual(first.nino12_anom, -1.3)
        self.assertAlmostEqual(first.nino4_anom, -1.1)
        latest = result[-1]
        self.assertEqual(latest.week_ending, date(2026, 9, 9))
        self.assertAlmostEqual(latest.nino34_anom, 2.9)

    def test_soi_returns_both_tables_and_drops_fill_values(self):
        tables = parsers.parse_soi(fixture("soi.txt"))
        self.assertIn("anomaly", tables)
        self.assertIn("standardized", tables)
        standardized = tables["standardized"]
        # Aug 2026 is the last real value; Sep-Dec are -999.9 and must be gone.
        self.assertEqual(standardized[-1].year, 2026)
        self.assertEqual(standardized[-1].month, 8)
        self.assertAlmostEqual(standardized[-1].value, -1.1)
        self.assertAlmostEqual(tables["anomaly"][-1].value, -1.8)
        self.assertTrue(all(m.value > -99 for m in standardized))

    def test_soi_tables_are_distinct(self):
        tables = parsers.parse_soi(fixture("soi.txt"))
        self.assertNotEqual(
            [m.value for m in tables["anomaly"]],
            [m.value for m in tables["standardized"]],
        )

    def test_mei_bimonthly_seasons_and_trailing_prose(self):
        result = parsers.parse_mei(fixture("mei.txt"))
        self.assertEqual(result[-1].season, "JA")
        self.assertEqual(result[-1].year, 2026)
        self.assertAlmostEqual(result[-1].value, 2.54)
        self.assertTrue(all(s.value > -99 for s in result))

    def test_monthly_sst_picks_the_anomaly_columns(self):
        regions = parsers.parse_monthly_sst(fixture("sstoi.indices"))
        self.assertAlmostEqual(regions["nino34"][-1].value, 2.52)
        self.assertAlmostEqual(regions["nino12"][-1].value, 4.08)
        self.assertAlmostEqual(regions["nino4"][-1].value, 0.93)

    def test_discussion_extracts_status_and_drops_boilerplate(self):
        html = (
            "<html><body><p>Climate Prediction Center: ENSO Diagnostic Discussion</p>"
            "<p>10 September 2026</p><p>El Ni&ntilde;o Advisory</p>"
            "<p>El Ni&ntilde;o is strengthening, with a greater than 90&#37; chance of a "
            "very strong event during the Northern Hemisphere fall and winter 2026-27.</p>"
            "<p>" + ("Real analysis of the subsurface and the thermocline. " * 6) + "</p>"
            "<p>" + ("This discussion is a consolidated effort of NOAA and partners. " * 5) + "</p>"
            "<p>The next ENSO Diagnostics Discussion is scheduled for 8 October 2026.</p>"
            "</body></html>"
        )
        parsed = parsers.parse_discussion(html)
        self.assertEqual(parsed["issued"], "10 September 2026")
        self.assertEqual(parsed["status"], "El Nino Advisory")
        self.assertTrue(parsed["synopsis"].startswith("El Nino is strengthening"))
        self.assertIn("thermocline", parsed["body"])
        self.assertNotIn("consolidated effort", parsed["body"])
        self.assertEqual(parsed["next_update"], "8 October 2026")


class TestClassification(unittest.TestCase):
    def test_intensity_tiers(self):
        self.assertEqual(intensity_tier(0.3), "Neutral")
        self.assertEqual(intensity_tier(0.5), "Weak El Nino")
        self.assertEqual(intensity_tier(1.2), "Moderate El Nino")
        self.assertEqual(intensity_tier(1.8), "Strong El Nino")
        self.assertEqual(intensity_tier(2.4), "Very Strong El Nino")
        self.assertEqual(intensity_tier(-1.7), "Strong La Nina")

    def _series(self, values: list[float]) -> list[SeasonValue]:
        seasons = parsers.ONI_SEASONS
        out = []
        for index, value in enumerate(values):
            out.append(SeasonValue(seasons[index % 12], 2020 + index // 12, value))
        return out

    def test_episode_requires_five_consecutive_seasons(self):
        short = self._series([0.0, 0.6, 0.9, 1.2, 0.0])
        episodes = find_episodes(short, warm=True)
        self.assertEqual(len(episodes), 1)
        self.assertEqual(episodes[0].length, 3)
        self.assertFalse(episodes[0].qualifies)

        long = self._series([0.0, 0.6, 0.9, 1.2, 1.4, 1.1, 0.0])
        self.assertTrue(find_episodes(long, warm=True)[0].qualifies)

    def test_current_episode_only_when_still_running(self):
        running = self._series([0.0, 0.6, 0.9, 1.2])
        self.assertIsNotNone(current_episode(running, warm=True))
        ended = self._series([0.0, 0.6, 0.9, 1.2, 0.1])
        self.assertIsNone(current_episode(ended, warm=True))

    def test_episode_peak_and_tier(self):
        episode = Episode(self._series([0.6, 1.9, 1.2]), warm=True)
        self.assertAlmostEqual(episode.peak.value, 1.9)
        self.assertEqual(episode.tier, "Strong El Nino")

    def test_analogs_compare_at_equal_phase_and_exclude_self(self):
        history = self._series(
            # a past event that runs long and peaks high, then a gap, then the current run
            [0.6, 1.0, 1.5, 2.0, 1.6, 0.9, 0.0, 0.0, 0.6, 1.0, 1.4]
        )
        current = current_episode(history, warm=True)
        self.assertIsNotNone(current)
        self.assertEqual(current.length, 3)
        analogs = find_analogs(history, current)
        self.assertEqual(len(analogs), 1)
        self.assertAlmostEqual(analogs[0].peak_value, 2.0)
        # the analog must not be the current run itself
        self.assertNotEqual(analogs[0].episode.onset.centre, current.onset.centre)

    def test_analogs_skip_events_shorter_than_current_phase(self):
        history = self._series([0.6, 0.7, 0.0, 0.6, 1.0, 1.4])
        current = current_episode(history, warm=True)
        self.assertEqual(find_analogs(history, current), [])

    def test_scale_flavour_detects_east_pacific_event(self):
        weeks = parsers.parse_weekly_sst(fixture("weekly.for"))
        scale = diagnose_scale(weeks[-1])
        self.assertEqual(scale.active_regions, 4)
        self.assertAlmostEqual(scale.flavour_index, 3.6)
        self.assertEqual(scale.flavour, "East Pacific (canonical) El Nino")

    def test_scale_flavour_detects_central_pacific_event(self):
        week = parsers.WeekObservation(
            date(2026, 9, 9), 25.0, 0.2, 28.0, 0.6, 29.0, 1.1, 29.6, 1.6
        )
        self.assertEqual(diagnose_scale(week).flavour, "Central Pacific (Modoki) El Nino")

    def test_the_scale_card_and_the_hazard_outlook_share_one_flavour(self):
        # The scale card called a central-Pacific event at -1.0 and the hazard
        # outlook at -0.5, from the same Nino-1+2 minus Nino-4 number, so
        # between the two the page said "Mixed / basin-wide" above a hazard
        # outlook written for a Modoki event. 2009-10, the textbook Modoki
        # case, reached -0.91 on the relative indices; at -1.0 no El Nino
        # since 1982 is central-Pacific.
        words = {"East Pacific (canonical) El Nino": impacts.EP,
                 "Central Pacific (Modoki) El Nino": impacts.CP,
                 "Mixed / basin-wide pattern": "mixed"}
        for difference in (-1.4, -0.91, -0.7, -0.5, -0.3, 0.0, 0.99, 1.0, 2.4):
            week = parsers.WeekObservation(
                date(2026, 9, 9), 25.0, 1.0 + difference, 28.0, 1.0,
                29.0, 1.0, 29.6, 1.0)
            scale = diagnose_scale(week)
            with self.subTest(difference=difference):
                self.assertEqual(words[scale.flavour],
                                 impacts.flavour_of(scale.flavour_index))
        week = parsers.WeekObservation(
            date(2026, 9, 9), 25.0, 0.04, 28.0, 0.5, 29.0, 0.95, 29.6, 0.95)
        self.assertEqual(diagnose_scale(week).flavour,
                         "Central Pacific (Modoki) El Nino")

    def test_ranking_uses_same_season_comparison(self):
        oni = parsers.parse_oni(fixture("oni.txt"))
        roni = parsers.parse_roni(fixture("roni.txt"))
        weeks = parsers.parse_weekly_sst(fixture("weekly.for"))
        soi = parsers.parse_soi(fixture("soi.txt"))["standardized"]
        mei = parsers.parse_mei(fixture("mei.txt"))
        result = assess(oni, roni, weeks, soi, mei)

        self.assertEqual(result.oni_latest.label, "JJA 2026")
        self.assertEqual(result.oni_tier, "Strong El Nino")
        # only one JJA season in the fixture, so it must rank first of one
        self.assertEqual(result.ranking.rank_season, 1)
        self.assertEqual(result.ranking.total_season, 1)
        self.assertEqual(result.seasons_at_threshold, 3)
        self.assertIn("2 more needed", result.episode_status)
        self.assertEqual(result.momentum.direction, "intensifying rapidly")
        self.assertTrue(result.coupling.coupled)
        self.assertTrue(0 <= result.power.value <= 100)

    def test_power_index_weights_sum_to_one(self):
        oni = parsers.parse_oni(fixture("oni.txt"))
        roni = parsers.parse_roni(fixture("roni.txt"))
        weeks = parsers.parse_weekly_sst(fixture("weekly.for"))
        soi = parsers.parse_soi(fixture("soi.txt"))["standardized"]
        mei = parsers.parse_mei(fixture("mei.txt"))
        power = assess(oni, roni, weeks, soi, mei).power
        self.assertAlmostEqual(sum(power.weights.values()), 1.0)
        expected = sum(power.components[k] * power.weights[k] for k in power.weights)
        self.assertAlmostEqual(power.value, round(expected, 1), places=1)


class TestPlotting(unittest.TestCase):
    def test_nice_ticks_stay_inside_the_domain(self):
        from elnino.svg import nice_ticks

        for low, high in ((-2.0, 2.0), (-0.34, 3.1), (0.0, 1.0), (-1.7, -0.2)):
            ticks = nice_ticks(low, high, 6)
            self.assertTrue(ticks)
            self.assertTrue(all(low <= t <= high for t in ticks), (low, high, ticks))

    def test_escaping_closes_the_markup_hole(self):
        from elnino.svg import esc

        self.assertEqual(esc('<a href="x">'), "&lt;a href=&quot;x&quot;&gt;")

    def test_declutter_separates_colliding_labels(self):
        spread = panels._declutter([(0.0, 100.0, "a"), (0.0, 101.0, "b"),
                                    (0.0, 102.0, "c")], spacing=14.0)
        ys = sorted(item[3] for item in spread)
        for lower, upper in zip(ys, ys[1:]):
            self.assertGreaterEqual(upper - lower, 13.9)

    def test_declutter_leaves_separated_labels_alone(self):
        spread = panels._declutter([(0.0, 10.0, "a"), (0.0, 90.0, "b")], spacing=14.0)
        self.assertEqual([round(item[3] - item[1]) for item in spread], [3, 3])


# ---------------------------------------------------------------------------
# Feeds added for the advanced system
# ---------------------------------------------------------------------------


class TestTables(unittest.TestCase):

    def test_a_column_of_sentences_wraps_and_a_column_of_numbers_does_not(self):
        # Every cell was nowrap and right-aligned, which suits a column of
        # numbers: the STORMFURY criteria table, five columns and the whole of
        # its card, ran 2262 px wide on a 1265 px page and was read by
        # scrolling sideways through each sentence.
        html = svg.table("t", ["storm", "detail", "value"], [
            ["Ana", "Sea-surface temperature under the core is above 26 degrees", "+1.2"],
            ["Bob", "short", "+0.3"],
        ])
        self.assertEqual(re.findall(r"<th(?: class=\"(\w+)\")?>", html), ["lbl", "txt", ""])
        self.assertEqual(re.findall(r"<td(?: class=\"(\w+)\")?>", html),
                         ["lbl", "txt", "", "lbl", "txt", ""])
        css = " ".join(dashboard._css().split())
        self.assertIn("th.txt, td.txt { white-space: normal; text-align: left;", css)

    def test_words_align_left_and_numbers_right(self):
        # Right-aligned text in every column but the first: "Within aircraft
        # range" and "Pass" hung off the right edge of their columns like
        # numbers, in the criteria table and some thirty others.
        html = svg.table("t", ["storm", "criterion", "verdict", "wind", "seen", "gap"], [
            ["Polo", "Within aircraft range", "Fail", "135 kt", "2026-09-24T16:51", "—"],
            ["Nolo", "Coherent eyewall", "Pass", "50 kt", "2026-09-23T10:02", "-0.4"],
        ])
        self.assertEqual(re.findall(r"<th(?: class=\"(\w+)\")?>", html),
                         ["lbl", "lbl", "lbl", "", "", ""])
        css = " ".join(dashboard._css().split())
        self.assertIn("th.lbl, td.lbl { text-align: left; }", css)


class TestLabelGeometry(unittest.TestCase):
    """The segment-against-box test that keeps labels off the lines."""

    BOX = (10.0, 10.0, 30.0, 20.0)          # left, top, right, bottom

    def test_a_segment_through_the_box_crosses_it(self):
        self.assertTrue(svg.crosses(self.BOX, (0.0, 15.0, 40.0, 15.0)))
        self.assertTrue(svg.crosses(self.BOX, (0.0, 0.0, 40.0, 30.0)))

    def test_a_segment_wholly_inside_crosses_it(self):
        self.assertTrue(svg.crosses(self.BOX, (12.0, 12.0, 14.0, 13.0)))

    def test_a_segment_that_stops_short_does_not(self):
        self.assertFalse(svg.crosses(self.BOX, (0.0, 15.0, 9.0, 15.0)))
        self.assertFalse(svg.crosses(self.BOX, (40.0, 15.0, 31.0, 15.0)))

    def test_a_segment_past_a_corner_does_not(self):
        # The line through (0, 9) and (11, 0) misses the top-left corner at
        # (10, 10): at x = 10 it is at y = 0.82, above the box.
        self.assertFalse(svg.crosses(self.BOX, (0.0, 9.0, 11.0, 0.0)))

    def test_a_parallel_segment_outside_does_not(self):
        self.assertFalse(svg.crosses(self.BOX, (0.0, 25.0, 40.0, 25.0)))
        self.assertFalse(svg.crosses(self.BOX, (5.0, 0.0, 5.0, 30.0)))

    def test_padding_grows_the_box(self):
        near = (0.0, 21.0, 40.0, 21.0)       # 1 below the bottom edge
        self.assertFalse(svg.crosses(self.BOX, near))
        self.assertTrue(svg.crosses(self.BOX, near, pad=1.5))


class TestGridParsers(unittest.TestCase):
    """The CPC monthly grid: stacked sections, glued fill values, no headers."""

    def test_splits_three_stacked_sections(self):
        sections = parsers.parse_cpc_grid(fixture("cpc_grid.for"))
        self.assertEqual(list(sections), ["original", "anomaly", "standardized"])

    def test_fill_values_never_reach_a_series(self):
        sections = parsers.parse_cpc_grid(fixture("cpc_grid.for"))
        for name, values in sections.items():
            for value in values:
                self.assertLess(abs(value.value), 900.0, f"{name} kept a fill value")

    def test_glued_fill_columns_split_on_the_minus_sign(self):
        """'1974-999.9-999.9... 61.0' must yield June, not a single huge token."""
        original = parsers.parse_cpc_grid(fixture("cpc_grid.for"))["original"]
        first = [v for v in original if v.year == 1974]
        self.assertEqual(first[0].month, 6)
        self.assertAlmostEqual(first[0].value, 61.0)
        self.assertEqual(len(first), 7)  # Jun through Dec; Jan-May are fill

    def test_trailing_fill_truncates_the_current_year(self):
        standardized = parsers.parse_cpc_grid(fixture("cpc_grid.for"))["standardized"]
        latest = standardized[-1]
        self.assertEqual((latest.year, latest.month), (2026, 8))
        self.assertAlmostEqual(latest.value, -3.2)

    def test_headerless_file_becomes_one_data_section(self):
        sections = parsers.parse_cpc_grid(fixture("headerless.for"))
        self.assertEqual(list(sections), ["data"])
        self.assertEqual(sections["data"][-1].month, 7)

    def test_grid_section_prefers_then_falls_back(self):
        sections = parsers.parse_cpc_grid(fixture("cpc_grid.for"))
        chosen = parsers.grid_section(sections, "standardized")
        self.assertIs(chosen, sections["standardized"])
        # An absent preference falls through to the last populated section.
        self.assertIs(parsers.grid_section(sections, "nope"), sections["standardized"])
        self.assertEqual(parsers.grid_section({}, "standardized"), [])


class TestWarmWaterVolume(unittest.TestCase):
    def test_reads_fortran_floats_without_a_leading_zero(self):
        """PMEL writes '-.4883405E+14'; float() takes it, a fixed slice would not."""
        rows = parsers.parse_wwv(fixture("wwv.dat"))
        self.assertEqual(len(rows), 4)
        self.assertAlmostEqual(rows[0].anomaly, -0.4883405, places=6)

    def test_scales_to_ten_to_the_fourteenth_cubic_metres(self):
        rows = parsers.parse_wwv(fixture("wwv.dat"))
        latest = rows[-1]
        self.assertEqual((latest.year, latest.month), (2026, 7))
        self.assertAlmostEqual(latest.anomaly, 3.244526, places=5)
        self.assertAlmostEqual(latest.volume, 27.05609, places=4)

    def test_header_lines_are_ignored_and_order_is_chronological(self):
        rows = parsers.parse_wwv(fixture("wwv.dat"))
        self.assertEqual([(r.year, r.month) for r in rows],
                         [(1980, 1), (1980, 2), (2026, 6), (2026, 7)])
        self.assertEqual(rows[-1].label, "Jul 2026")
        self.assertEqual(rows[-1].month_value.value, rows[-1].anomaly)


class TestRelativeSst(unittest.TestCase):
    """The weekly and monthly relative files disagree on column order."""

    def test_weekly_puts_nino34_third(self):
        rows = parsers.parse_rel_weekly(fixture("rel_weekly.txt"))
        week, regions = rows[-1]
        self.assertEqual(week, date(2026, 9, 9))
        self.assertAlmostEqual(regions["nino12"], 3.7)
        self.assertAlmostEqual(regions["nino3"], 2.8)
        self.assertAlmostEqual(regions["nino34"], 2.0)
        self.assertAlmostEqual(regions["nino4"], -0.1)

    def test_monthly_puts_nino34_fourth(self):
        regions = parsers.parse_rel_monthly(fixture("rel_monthly.txt"))
        self.assertAlmostEqual(regions["nino4"][-1].value, 0.12)
        self.assertAlmostEqual(regions["nino34"][-1].value, 1.78)

    def test_the_two_orders_are_not_accidentally_the_same(self):
        self.assertNotEqual(parsers.REL_WEEKLY_ORDER, parsers.REL_MONTHLY_ORDER)


class TestColumnarParsers(unittest.TestCase):
    def test_yr_mon_anom_default_columns(self):
        rows = parsers.parse_yr_mon_anom(fixture("yr_mon_anom.txt"))
        self.assertEqual(len(rows), 3)
        self.assertAlmostEqual(rows[-1].value, 1.92)

    def test_same_routine_reads_the_five_column_detrended_file(self):
        rows = parsers.parse_yr_mon_anom(fixture("detrended.txt"), column=4, width=5)
        self.assertEqual(len(rows), 3)
        self.assertEqual((rows[0].year, rows[0].month), (1949, 12))
        self.assertAlmostEqual(rows[-1].value, 1.92)

    def test_atlantic_keeps_anomalies_not_absolute_temperatures(self):
        regions = parsers.parse_atlantic_indices(fixture("atlantic.indices"))
        self.assertEqual(set(regions), {"natl", "satl", "trop"})
        self.assertAlmostEqual(regions["trop"][-1].value, 0.98)
        self.assertAlmostEqual(regions["natl"][-1].value, 0.48)

    def test_mjo_skips_star_fill_and_keeps_longitude_keys(self):
        series = parsers.parse_mjo(fixture("mjo.ascii"))
        self.assertIn("120W", series)
        self.assertEqual(len(series["120W"]), 2)  # the '*****' pentad is dropped
        stamp, value = series["120W"][-1]
        self.assertEqual(stamp, date(2026, 9, 6))
        self.assertAlmostEqual(value, -2.05)

    def test_monthly_sst_four_regions(self):
        regions = parsers.parse_monthly_sst(fixture("sstoi.indices"))
        self.assertAlmostEqual(regions["nino34"][-1].value, 2.52)
        self.assertAlmostEqual(regions["nino12"][-1].value, 4.08)


# ---------------------------------------------------------------------------
# The recharge oscillator and its verification
# ---------------------------------------------------------------------------


def _months(values: list[float], start_year: int = 1990) -> list[MonthValue]:
    """Monthly series from a flat list, starting in January of start_year."""
    out = []
    for index, value in enumerate(values):
        out.append(MonthValue(start_year + index // 12, index % 12 + 1, value))
    return out


PERIOD = 43.0  # months; deliberately not a multiple of 12


def _synthetic_oscillator(months: int = 900) -> tuple[list[MonthValue], list[MonthValue]]:
    """A clean recharge loop: h leads T by a quarter cycle.

    The period is not a multiple of twelve and the amplitude drifts, because a
    period that divides the year leaves each calendar month with a handful of
    repeated values, on which T and T-cubed are collinear and the cubic fit is
    singular. That is a property of the test data, not of the model.
    """
    sst, heat = [], []
    for index in range(months):
        phase = 2 * math.pi * index / PERIOD
        amplitude = 0.65 + 0.45 * math.sin(2 * math.pi * index / 137.0)
        sst.append(amplitude * math.sin(phase))
        heat.append(amplitude * math.cos(phase))
    return _months(sst), _months(heat)


class TestRechargeOscillator(unittest.TestCase):
    def test_rom_rows_pairs_each_month_with_its_successor(self):
        sst, heat = _synthetic_oscillator(36)
        rows = forecast.rom_rows(sst, heat)
        self.assertEqual(len(rows), 35)  # the final month has no successor
        year, month, t, h, dt, dh = rows[0]
        self.assertEqual((year, month), (1990, 1))
        self.assertAlmostEqual(dt, sst[1].value - sst[0].value)
        self.assertAlmostEqual(dh, heat[1].value - heat[0].value)

    def test_rom_rows_skips_a_gap_rather_than_bridging_it(self):
        sst = _months([0.1, 0.2, 0.3])
        heat = _months([1.0, 1.1, 1.2])
        del sst[1]
        rows = forecast.rom_rows(sst, heat)
        self.assertEqual([(r[0], r[1]) for r in rows], [])

    def test_fit_refuses_a_sample_that_is_too_small(self):
        sst, heat = _synthetic_oscillator(12)
        self.assertIsNone(forecast.fit_recharge(sst, heat))

    def test_fit_recovers_the_planted_oscillation(self):
        sst, heat = _synthetic_oscillator()
        model = forecast.fit_recharge(sst, heat)
        self.assertIsNotNone(model)
        # Start at the top of the loop (T=0, h=+1); a quarter period later the
        # surface should be warm. That is the whole physical claim.
        quarter = round(PERIOD / 4)
        projection = forecast.recharge_projection(model, 0.0, 1.0, 1, quarter)
        self.assertGreater(projection[quarter], 0.5)

    def test_projection_stops_rather_than_returning_a_diverged_integration(self):
        sst, heat = _synthetic_oscillator()
        model = forecast.fit_recharge(sst, heat)
        projection = forecast.recharge_projection(model, 50.0, 50.0, 1, 24)
        self.assertTrue(all(abs(v) <= forecast.ROM_DIVERGENCE for v in projection.values()))

    def test_excluding_a_year_changes_the_fit(self):
        sst, heat = _synthetic_oscillator()
        full = forecast.fit_recharge(sst, heat)
        held = forecast.fit_recharge(sst, heat, exclude_year=1995)
        self.assertEqual(full.samples - held.samples, 12)

    def test_season_step_wraps_the_year(self):
        self.assertEqual(forecast._season_step("NDJ", 2026, 1), ("DJF", 2027))
        self.assertEqual(forecast._season_step("JJA", 2026, 3), ("SON", 2026))
        self.assertEqual(forecast._season_step("DJF", 2026, 0), ("DJF", 2026))


class TestVerificationScoresProduction(unittest.TestCase):
    """Verification must score the model production uses, not a copy of it."""

    def test_rom_hindcast_delegates_to_the_production_forecast(self):
        self.assertIs(verification.recharge_seasons, forecast.recharge_seasons)

    def test_verification_imports_the_production_fit(self):
        self.assertIs(verification.fit_recharge, forecast.fit_recharge)
        self.assertIs(verification.rom_rows, forecast.rom_rows)


# ---------------------------------------------------------------------------
# Subsurface, atmosphere, impacts, alerts
# ---------------------------------------------------------------------------


class TestSubsurface(unittest.TestCase):
    def test_lead_lag_recovers_a_planted_lead(self):
        sst, heat = _synthetic_oscillator()
        # heat = cos, sst = sin: heat leads sst by a quarter of the period.
        lead, correlation, profile = subsurface.lead_lag(heat, sst)
        self.assertEqual(lead, round(PERIOD / 4))
        self.assertGreater(correlation, 0.95)
        self.assertEqual(len(profile), 13)

    def test_phase_quadrants_run_clockwise(self):
        """Warm and recharged must not be read as the same phase as cool and discharged."""
        _, warm_recharged, _, _ = subsurface.classify_phase(1.0, 1.0)
        _, cool_discharged, _, _ = subsurface.classify_phase(-1.0, -1.0)
        self.assertNotEqual(warm_recharged, cool_discharged)

    def test_a_point_near_the_origin_is_not_confident(self):
        *_, confident = subsurface.classify_phase(0.05, 0.05)
        self.assertFalse(confident)

    def test_analyse_ranks_the_latest_month(self):
        rows = parsers.parse_wwv(fixture("wwv.dat"))
        sst = [MonthValue(r.year, r.month, 1.0) for r in rows]
        state = subsurface.analyse(rows, [], sst, trajectory_months=12)
        self.assertIsNotNone(state)
        self.assertEqual(state.rank_alltime, 1)  # the last row is the largest
        self.assertEqual(state.total_alltime, len(rows))

    def test_analyse_without_wwv_returns_none(self):
        self.assertIsNone(subsurface.analyse([], [], []))

    def test_east_loaded_heat_is_named_as_the_tilt_not_a_late_stage(self):
        # Heat piled in the east with the west drawn down is the thermocline
        # tilt, which moves with the surface warming. Calling it "late-stage"
        # while the basin total is still climbing contradicts the tendency
        # printed beside it.
        rows = parsers.parse_wwv(fixture("wwv.dat"))
        last = rows[-1]
        west = [parsers.WwvObservation(last.year, last.month, 0.0, -0.4)]
        sst = [MonthValue(r.year, r.month, 1.0) for r in rows]
        state = subsurface.analyse(rows, west, sst, trajectory_months=12)
        self.assertGreater(last.anomaly - (-0.4), 0.5)
        text = " ".join(state.notes)
        self.assertIn("tilt", text)
        self.assertNotIn("late-stage", text)


class TestAtmosphere(unittest.TestCase):
    def test_standardize_removes_the_annual_cycle(self):
        """A big annual cycle must not masquerade as an anomaly."""
        raw = [12.0 * math.sin(2 * math.pi * i / 12.0) + 0.01 * i for i in range(360)]
        raw[350] += 9.0  # one genuinely anomalous month
        standardized = atmosphere.standardize(_months(raw))
        peak = max(standardized, key=lambda v: abs(v.value))
        self.assertEqual((peak.year, peak.month), (standardized[350].year,
                                                   standardized[350].month))
        # Every other month sits well inside the anomalous one.
        others = [abs(v.value) for i, v in enumerate(standardized) if i != 350]
        self.assertLess(max(others), abs(peak.value))

    def test_indicator_sign_convention_makes_positive_mean_el_nino(self):
        sections = parsers.parse_cpc_grid(fixture("cpc_grid.for"))
        indicator = atmosphere.build_indicator("olr_central", sections)
        self.assertIsNotNone(indicator)
        # Suppressed OLR (negative anomaly) is enhanced convection, which is
        # El-Nino-like, so the score must come out positive.
        self.assertLess(indicator.raw, 0.0)
        self.assertGreater(indicator.score, 0.0)
        self.assertTrue(indicator.supports_el_nino)

    def test_unknown_indicator_key_is_declined_not_guessed(self):
        sections = parsers.parse_cpc_grid(fixture("cpc_grid.for"))
        self.assertIsNone(atmosphere.build_indicator("not_a_feed", sections))

    def test_westerly_bursts_are_found_in_the_recent_window_only(self):
        quiet = [0.0] * 200
        series = _months(quiet + [-4.0, 0.0, -4.0])
        bursts = atmosphere.detect_bursts(series, within_months=2)
        self.assertEqual(len(bursts), 1)
        self.assertEqual(bursts[0].when.month, series[-1].month)


class TestImpacts(unittest.TestCase):
    def test_flavour_selects_different_teleconnections(self):
        east = impacts.assess(2.0, flavour_index=3.0)
        central = impacts.assess(2.0, flavour_index=-1.5)
        self.assertEqual(east.flavour, impacts.EP)
        self.assertEqual(central.flavour, impacts.CP)
        # The regions overlap; the specific links do not.
        self.assertNotEqual(
            {(i.link.region, i.link.effect) for i in east.active},
            {(i.link.region, i.link.effect) for i in central.active},
        )

    def test_a_weak_event_puts_fewer_links_in_play(self):
        weak = impacts.assess(0.6, flavour_index=0.0)
        strong = impacts.assess(2.3, flavour_index=0.0)
        self.assertLess(len(weak.active), len(strong.active))

    def test_every_active_link_clears_its_own_intensity_threshold(self):
        result = impacts.assess(1.2, flavour_index=0.0)
        for item in result.active:
            self.assertLessEqual(item.link.min_intensity, 1.2)


    def test_the_projected_peak_is_quoted_once_not_two_ways(self):
        # The note said "PROJECTED RONI peak of +1.8" over a caption, a report
        # line and a globe reading of "+1.85": the same number at two
        # precisions, which a reader takes for two numbers - or for 1.85
        # rounded down.
        result = impacts.assess(1.847, flavour_index=1.5, current_index=1.36)
        keyed = next(n for n in result.notes if "PROJECTED" in n)
        self.assertIn("+1.85 degC", keyed)
        self.assertIn("today's +1.36 degC", keyed)
        self.assertNotIn("+1.8 degC", keyed)

    def test_the_hazard_card_names_the_flavour_in_english(self):
        # "with a east-pacific structure": the catalogue key, printed raw.
        for flavour_index, words in ((3.0, "an east-Pacific structure"),
                                     (-1.5, "a central-Pacific structure"),
                                     (0.0, "a mixed structure")):
            state = SimpleNamespace(impacts=impacts.assess(
                2.3, flavour_index=flavour_index, current_index=1.4))
            html = panels.impact_panel(state)
            with self.subTest(words=words):
                self.assertIn(words, " ".join(html.split()))
                self.assertNotIn("east-pacific structure", html)
                self.assertNotIn("central-pacific structure", html)

    def test_the_coral_entry_knows_the_fourth_global_bleaching(self):
        # The fourth global bleaching event, from 2023, put more of the world's
        # reef under bleaching-level heat stress than any before it; the entry
        # still named 1997-98 and 2014-17 as the largest on record.
        coral = next(link for link in impacts.CATALOGUE if "coral" in link.region)
        self.assertIn("2023-25", coral.detail)
        self.assertNotIn("drove the largest bleaching episodes", coral.detail)

    def test_the_report_names_the_flavour_in_english(self):
        state = SimpleNamespace(impacts=impacts.assess(
            2.3, flavour_index=3.0, current_index=1.4))
        text = " ".join(" ".join(report._section_impacts(state)).split())
        self.assertIn("east-Pacific flavour", text)
        self.assertNotIn("east-pacific", text)

    def test_the_hazard_card_writes_degrees_as_a_symbol(self):
        # The notes are shared with the ASCII report, which needs "degC"; on
        # the page they printed "+1.8 degC" beside "+1.85 &deg;C".
        state = SimpleNamespace(impacts=impacts.assess(
            1.847, flavour_index=1.5, current_index=1.36))
        html = panels.impact_panel(state)
        self.assertNotIn("degC", html)
        self.assertIn("+1.85 &deg;C, not today", html)


class TestAlertLevels(unittest.TestCase):
    """The level constants are lowercase; every table keyed on them must agree.

    A mismatch here does not raise - it falls through to a default - so a
    critical alert quietly renders in the colour of an informational one.
    """

    LEVELS = (alerts.CRITICAL, alerts.WARNING, alerts.WATCH, alerts.INFO)

    def test_levels_are_lowercase(self):
        for level in self.LEVELS:
            self.assertEqual(level, level.lower())

    def test_dashboard_status_map_covers_every_level(self):
        from elnino import panels

        for level in self.LEVELS:
            self.assertIn(level, panels._ALERT_STATUS)

    def test_report_marks_cover_every_level(self):
        for level in self.LEVELS:
            self.assertIn(level, report.LEVEL_MARK)

    def test_worst_is_the_most_severe_not_the_first(self):
        found = [
            alerts.Alert(code="a", level=alerts.INFO, title="a", detail="", kind="x"),
            alerts.Alert(code="b", level=alerts.CRITICAL, title="b", detail="", kind="x"),
            alerts.Alert(code="c", level=alerts.WATCH, title="c", detail="", kind="x"),
        ]
        self.assertEqual(alerts.AlertSet(found, []).worst, alerts.CRITICAL)


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "test.db"

    def tearDown(self):
        self.tmp.cleanup()

    def test_snapshot_roundtrip(self):
        conn = storage.connect(self.path)
        try:
            storage.record_snapshot(conn, "2026-09-01T00:00:00", {"oni": 1.4, "power_index": 70})
            storage.record_snapshot(conn, "2026-09-17T00:00:00", {"oni": 1.8, "power_index": 82})
            history = storage.snapshot_history(conn, limit=10)
            self.assertEqual(len(history), 2)
            # Oldest first: the CLI prints this as a chronological log.
            self.assertAlmostEqual(history[0].get("oni"), 1.4)
            self.assertAlmostEqual(history[-1].get("oni"), 1.8)
            earlier = storage.previous_snapshot(conn, "2026-09-17T00:00:00")
            self.assertAlmostEqual(earlier.get("oni"), 1.4)
        finally:
            conn.close()

    def test_an_alert_keeps_its_first_seen_time_across_runs(self):
        conn = storage.connect(self.path)
        try:
            alert = alerts.Alert(code="oni_ge_1.5", level=alerts.WARNING,
                                 title="t", detail="d", kind="state")
            first = alerts.reconcile(conn, [alert], "2026-09-01T00:00:00")
            self.assertTrue(first.alerts[0].is_new)
            again = alerts.reconcile(conn, [alert], "2026-09-17T00:00:00")
            self.assertFalse(again.alerts[0].is_new)
            self.assertEqual(again.alerts[0].first_seen, "2026-09-01T00:00:00")
        finally:
            conn.close()

    def test_an_alert_that_stops_firing_is_cleared(self):
        conn = storage.connect(self.path)
        try:
            alert = alerts.Alert(code="wwv_record", level=alerts.CRITICAL,
                                 title="t", detail="d", kind="subsurface")
            alerts.reconcile(conn, [alert], "2026-09-01T00:00:00")
            after = alerts.reconcile(conn, [], "2026-09-17T00:00:00")
            self.assertEqual(after.alerts, [])
            self.assertIn("wwv_record", after.cleared)
        finally:
            conn.close()


class TestFetchCache(unittest.TestCase):
    """What is cached reads back as what was downloaded."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name)
        self.source = sources.Source(key="probe", name="probe", url="https://example.invalid/x",
                                     agency="test", cadence="daily")

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, payload):
        with mock.patch.object(sources, "_http_get", return_value=payload):
            return sources.fetch(self.source, self.raw)

    def test_the_cache_reads_back_as_what_was_downloaded(self):
        # A feed served with CRLF line ends, as some NOAA text products are.
        # Written in text mode on Windows each "\r\n" became "\r\r\n", and
        # read back it split in two - a blank line after every record.
        payload = "  DJF 2026   1.02\r\n  JFM 2026   0.88\r\n"
        live = self.fetch(payload)
        cached = sources.fetch(self.source, self.raw, offline=True)
        self.assertEqual(cached.text, live.text)
        self.assertEqual(cached.text.splitlines(), ["  DJF 2026   1.02", "  JFM 2026   0.88"])
        self.assertEqual((self.raw / "probe.cache").read_bytes(), live.text.encode("utf-8"))

    def test_an_unchanged_payload_is_not_archived_twice(self):
        import hashlib
        import os

        payload = "SEAS  YR  TOTAL ANOM\n DJF 2026 26.10 1.02\n"
        self.fetch(payload)
        (archived,) = (self.raw / "archive").glob("probe_*.txt")
        self.assertEqual(hashlib.sha256(archived.read_bytes()).hexdigest(),
                         hashlib.sha256(payload.encode("utf-8")).hexdigest())
        os.utime(archived, (1_000_000_000, 1_000_000_000))
        self.fetch(payload)
        self.assertEqual(archived.stat().st_mtime, 1_000_000_000)



class TestPayloadDecoding(unittest.TestCase):
    """What arrives on the wire, turned into the text the cache keeps."""

    def test_plain_text_passes_through(self):
        self.assertEqual(sources.decode_payload(b"abc\n"), "abc\n")

    def test_a_stored_gzip_is_unpacked(self):
        import gzip
        self.assertEqual(sources.decode_payload(gzip.compress(b"deck")), "deck")

    def test_a_kmz_arrives_as_its_kml_text(self):
        # NHC publishes its outlooks, cones and warnings as KMZ: a zip holding
        # one KML and its icons. Decoded as text it is binary garbage.
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl54.png", b"\x89PNG")
            z.writestr("gtwo_atl.kml", "<kml>outlook</kml>")
        self.assertEqual(sources.decode_payload(buf.getvalue()), "<kml>outlook</kml>")

    def test_a_zip_without_kml_is_an_error_not_garbage(self):
        import io
        import zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.shp", b"\x00\x00")
        with self.assertRaises(ValueError):
            sources.decode_payload(buf.getvalue())


class TestKml(unittest.TestCase):
    """KML as NHC writes it: namespaced, with the numbers in ExtendedData."""

    def test_placemarks_keep_document_order_and_extended_data(self):
        marks = kml.placemarks(fixture("gtwo_pac.kml"))
        first = marks[0]
        self.assertEqual(first.style, "#3")
        self.assertEqual(first.data["2day_percentage"], "40%")
        self.assertEqual(first.data["7day_category"], "High")
        self.assertEqual(len(first.polygons), 1)
        point = marks[1]
        self.assertAlmostEqual(point.points[0][0], -92.689, places=3)
        self.assertAlmostEqual(point.points[0][1], 10.868, places=3)
        self.assertEqual(len(marks[2].lines), 1)

    def test_a_namespace_does_not_hide_anything(self):
        marks = kml.placemarks(fixture("ww_ep152026.kml"))
        self.assertIn("Hurricane Watch", {m.name for m in marks})
        self.assertTrue(all(m.data.get("atcfid") == "EP152026" for m in marks))

    def test_a_placemark_knows_its_folder(self):
        marks = kml.placemarks(fixture("surge_ep152026.kml"))
        self.assertEqual({m.folder for m in marks if m.polygons}, {"Polygons"})
        self.assertIn("Breakpoints", {m.folder for m in marks if m.points})

    def test_the_document_is_named(self):
        self.assertIn("Hurricane Nolo (Advisory #20)",
                      kml.document_name(fixture("ww_ep152026.kml")))

    def test_a_broken_description_does_not_lose_the_file(self):
        # Descriptions are raw HTML pasted into the XML; one unclosed tag
        # must cost the description, not every placemark in the file.
        text = ("<kml><Document><description><TABLE><TR><TD>Issued<br></TD>"
                "</TR></TABLE></description><Placemark><name>Hurricane Warning"
                "</name><LineString><coordinates>-80.1,25.0,0 -80.3,26.1,0"
                "</coordinates></LineString></Placemark></Document></kml>")
        (mark,) = kml.placemarks(text)
        self.assertEqual(mark.name, "Hurricane Warning")
        self.assertEqual(mark.lines, (((-80.1, 25.0), (-80.3, 26.1)),))

    def test_simplify_keeps_the_ends_and_drops_the_straight_middle(self):
        ring = ((0.0, 0.0), (1.0, 0.001), (2.0, 0.0), (2.0, 2.0), (0.0, 0.0))
        out = kml.simplify(ring, 0.01)
        self.assertEqual(out[0], ring[0])
        self.assertEqual(out[-1], ring[-1])
        self.assertNotIn((1.0, 0.001), out)
        self.assertIn((2.0, 2.0), out)


class TestProtectiveProducts(unittest.TestCase):
    """The per-storm products NHC issues to protect people, read from KML/text."""

    def test_watches_and_warnings_by_kind(self):
        segments = tcproducts.watches_warnings(fixture("ww_ep152026.kml"))
        kinds = {s.kind for s in segments}
        self.assertEqual(kinds, {"Hurricane Watch", "Tropical Storm Warning",
                                 "Tropical Storm Watch"})
        self.assertTrue(all(len(s.coords) >= 2 for s in segments))
        self.assertEqual(tcproducts.advisory_of(fixture("ww_ep152026.kml")), "20")

    def test_the_cone_is_one_closed_ring_over_the_storm(self):
        ring = tcproducts.cone(fixture("cone_ep152026.kml"))
        self.assertEqual(ring[0], ring[-1])
        lons = [p[0] for p in ring]
        lats = [p[1] for p in ring]
        self.assertTrue(min(lons) < -155.5 < max(lons))
        self.assertTrue(min(lats) < 16.0 < max(lats))

    def test_peak_surge_areas_carry_their_range(self):
        areas = tcproducts.peak_surge(fixture("surge_ep152026.kml"))
        self.assertEqual(len(areas), 4)
        self.assertEqual({a.feet for a in areas}, {"1-3 ft"})
        self.assertIn("Southeast coast of Hawaii", {a.label for a in areas})

    def test_wind_probabilities_read_as_cumulative_by_hour(self):
        table = tcproducts.wind_probabilities(fixture("pws_ep152026.shtml"))
        self.assertEqual(table.hours, (12, 24, 36, 48, 72, 96, 120))
        self.assertEqual(table.advisory, "20")
        self.assertIn("1500 UTC FRI SEP 25 2026", table.issued)
        rows = {(r.place, r.threshold): r for r in table.rows}
        self.assertEqual(rows[("SOUTH POINT", 34)].cumulative, (1, 29, 49, 50, 50, 50, 50))
        self.assertEqual(rows[("HILO", 34)].cumulative, (0, 3, 6, 6, 7, 7, 7))
        self.assertEqual(rows[("FR FRIG SHOALS", 64)].total, 7)
        self.assertEqual(rows[("BUOY 51002", 64)].total, 57)

    def test_the_prose_above_the_table_is_not_a_row(self):
        # "PROBABILITIES FOR 34 KT AND 50 KT ARE SHOWN..." names thresholds
        # too; only the lines under FORECAST HOUR are locations.
        table = tcproducts.wind_probabilities(fixture("pws_ep152026.shtml"))
        places = {r.place for r in table.rows}
        self.assertEqual(len(table.rows), 43)
        self.assertFalse(any("PROBABILIT" in place for place in places))

    def test_a_page_without_a_table_is_none(self):
        self.assertIsNone(tcproducts.wind_probabilities("<html><pre>000</pre></html>"))

    def test_a_cone_across_180_goes_the_short_way_round(self):
        # A central Pacific cone crossing the date line is written with the
        # longitude jumping from 179 to -179; drawn as written it would span
        # the world. Each vertex is kept within 180 degrees of the last.
        text = ("<kml><Document><Placemark><Polygon><outerBoundaryIs><LinearRing>"
                "<coordinates>179.0,10.0,0 -179.0,10.0,0 -179.0,12.0,0 "
                "179.0,12.0,0 179.0,10.0,0</coordinates>"
                "</LinearRing></outerBoundaryIs></Polygon></Placemark>"
                "</Document></kml>")
        ring = tcproducts.cone(text)
        self.assertEqual([p[0] for p in ring], [179.0, 181.0, 181.0, 179.0, 179.0])

    ERROR_PAGE = ("<!DOCTYPE html><html><head><title>502 Bad Gateway</title></head>"
                  "<body><h1>502 Bad Gateway</h1></body></html>")

    def test_an_error_page_is_not_a_file_with_nothing_in_it(self):
        # Read as empty, it said "no coastal watches or warnings are in
        # effect" for a storm under a Hurricane Watch.
        for read in (tcproducts.watches_warnings, tcproducts.peak_surge, tcproducts.cone):
            with self.assertRaises(ValueError, msg=read.__name__):
                read(self.ERROR_PAGE)

    def test_a_file_cut_short_is_not_a_file_with_nothing_in_it(self):
        text = fixture("ww_ep152026.kml")
        with self.assertRaises(SyntaxError):  # ElementTree's ParseError
            tcproducts.watches_warnings(text[: len(text) // 2])

    def test_a_watch_of_a_kind_this_reader_does_not_know_is_not_dropped(self):
        text = ("<kml xmlns='http://www.opengis.net/kml/2.2'><Document>"
                "<name>Hurricane Nolo (Advisory #21) - Watch/Warnings</name>"
                "<Placemark><name>Storm Surge Warning</name><styleUrl>#SSW</styleUrl>"
                "<LineString><coordinates>-155.0,19.5 -155.1,19.6</coordinates>"
                "</LineString></Placemark></Document></kml>")
        with self.assertRaises(ValueError):
            tcproducts.watches_warnings(text)

    def test_the_advisory_of_an_error_page_is_not_known(self):
        self.assertEqual(tcproducts.advisory_of(self.ERROR_PAGE), "")

    def test_the_public_advisory_says_what_is_in_effect_in_its_own_words(self):
        self.assertEqual(tcproducts.in_effect(fixture("tcp_hfotcpcp2.shtml")), (
            ("Hurricane Watch", ("Hawaii County",)),
            ("Tropical Storm Warning", ("Hawaii County",)),
            ("Tropical Storm Watch", ("Maui County",))))
        self.assertEqual(tcproducts.in_effect(fixture("tcp_miatcpat2.shtml")),
                         (("Tropical Storm Warning", ("The Cabo Verde Islands",)),))

    def test_a_public_advisory_with_nothing_in_effect_says_so(self):
        self.assertEqual(tcproducts.in_effect(fixture("tcp_miatcpep2.shtml")), ())

    def test_an_area_that_wraps_is_one_area(self):
        text = ("<pre>BULLETIN\nHurricane Helene Advisory Number  15\n \n"
                "WATCHES AND WARNINGS\n--------------------\n"
                "CHANGES WITH THIS ADVISORY:\n \nNone.\n \n"
                "SUMMARY OF WATCHES AND WARNINGS IN EFFECT:\n \n"
                "A Storm Surge Warning is in effect for...\n"
                "* Anclote River to Ochlockonee River\n"
                "* Tampa Bay\n \n"
                "A Hurricane Warning is in effect for...\n"
                "* Englewood to Indian Pass, including Tampa Bay and the coast of the\n"
                "Florida Big Bend\n \n"
                "A Storm Surge Warning means there is a danger of life-threatening\n"
                "inundation.\n</pre>")
        self.assertEqual(tcproducts.in_effect(text), (
            ("Storm Surge Warning", ("Anclote River to Ochlockonee River", "Tampa Bay")),
            ("Hurricane Warning", ("Englewood to Indian Pass, including Tampa Bay and the "
                                   "coast of the Florida Big Bend",))))

    def test_an_error_page_is_not_an_advisory_with_nothing_in_effect(self):
        with self.assertRaises(ValueError):
            tcproducts.in_effect(self.ERROR_PAGE)
        # Nor is an advisory whose watches and warnings cannot be found.
        with self.assertRaises(ValueError):
            tcproducts.in_effect("<pre>BULLETIN\nHurricane Nolo Advisory Number  21\n"
                                 "WATCHES AND WARNINGS\n--------------------\n</pre>")

    def test_the_public_advisory_carries_its_own_number(self):
        self.assertEqual(tcproducts.advisory_of(fixture("tcp_hfotcpcp2.shtml")), "21")
        self.assertEqual(tcproducts.advisory_of(
            "Hurricane Nolo Intermediate Advisory Number  20A"), "20A")

    def test_a_file_with_no_watches_is_an_empty_list(self):
        text = ("<kml xmlns='http://www.opengis.net/kml/2.2'><Document>"
                "<name>Hurricane Nolo (Advisory #21) - Watch/Warnings</name>"
                "</Document></kml>")
        self.assertEqual(tcproducts.watches_warnings(text), [])
        self.assertEqual(tcproducts.advisory_of(text), "21")


class TestJtwc(unittest.TestCase):
    """JTWC's warnings: the west Pacific, Indian Ocean and southern hemisphere."""

    def test_the_rss_lists_only_jtwc_basins(self):
        self.assertEqual(jtwc.warning_files(fixture("jtwc.rss")), ["wp2526.tcw"])

    def test_a_warning_becomes_a_storm_with_history_and_forecast(self):
        storm = jtwc.parse_tcw(fixture("jtwc_wp2526.tcw"))
        self.assertEqual((storm.basin, storm.number, storm.year), ("WP", 25, 2026))
        self.assertEqual(storm.name, "Surigae")
        self.assertEqual(storm.centre, "JTWC")
        now = storm.latest
        self.assertEqual((now.stamp, now.lat, now.lon, now.wind), ("2026092512", 21.4, 128.2, 50))
        self.assertEqual(now.radius(34), (60, 35, 45, 70))
        self.assertEqual(len([f for f in storm.track if f.tau == 0]), 22)
        self.assertEqual(storm.track[0].stamp, "2026092006")
        day1 = [f for f in storm.forecast if f.tau == 24][0]
        self.assertEqual((day1.lat, day1.lon, day1.wind), (23.6, 127.0, 70))
        self.assertEqual(day1.radius(64), (0, 0, 0, 10))
        self.assertEqual([f.stage for f in storm.forecast if f.tau == 120], ["EX"])
        self.assertEqual(storm.advisory["advisory"], "10")

    def test_the_warning_says_how_it_moves_and_how_sure_the_fix_is(self):
        storm = jtwc.parse_tcw(fixture("jtwc_wp2526.tcw"),
                               url="https://www.metoc.navy.mil/jtwc/products/wp2526.tcw")
        self.assertEqual(storm.latest.pressure, 998)
        self.assertEqual((storm.advisory["movement_dir"], storm.advisory["movement_kt"]), (305, 12))
        self.assertEqual(storm.advisory["accuracy_nm"], 60)
        self.assertEqual(storm.advisory["public"],
                         "https://www.metoc.navy.mil/jtwc/products/wp2526web.txt")
        self.assertEqual(storm.advisory["last_update"], "2026-09-25T15:00:00Z")
        self.assertTrue(storm.active)

    def test_southern_hemisphere_positions_are_signed(self):
        storm = jtwc.parse_tcw(fixture("jtwc_sh0326.tcw"))
        self.assertEqual(storm.basin, "SH")
        self.assertEqual((storm.latest.lat, storm.latest.lon), (-15.8, 71.2))
        self.assertEqual(storm.track[0].stamp, "2026011318")

    def test_a_southern_season_is_named_by_the_year_it_ends(self):
        # JTWC's southern season runs July to June and its ids carry the
        # year the season ends, so a cyclone in October 2026 is sh..27.
        storm = jtwc.parse_tcw(fixture("jtwc_sh0326.tcw"),
                               url="https://www.metoc.navy.mil/jtwc/products/sh0327.tcw")
        self.assertEqual(storm.year, 2027)

    def test_a_cyclone_counts_toward_ace_at_cyclone_strength(self):
        # 35, 45, 50, 55 kt as a tropical storm and 65 kt as a cyclone.
        storm = jtwc.parse_tcw(fixture("jtwc_sh0326.tcw"))
        self.assertEqual(storm.latest.stage, "TC")
        self.assertAlmostEqual(storm.ace, 1.3)

    def test_dissipation_in_the_remarks_ends_the_storm_as_dissipating(self):
        text = fixture("jtwc_wp2526.tcw").replace(
            "120HR BECOMING EXTRATROPICAL",
            "120HR DISSIPATED AS A SIGNIFICANT TROPICAL CYCLONE OVER WATER")
        storm = jtwc.parse_tcw(text)
        self.assertEqual([f.stage for f in storm.forecast if f.tau == 120], ["DS"])

    def test_something_that_is_not_a_warning_is_none(self):
        self.assertIsNone(jtwc.parse_tcw("<html>404 Not Found</html>"))

    def test_a_typhoon_is_named_as_one(self):
        self.assertEqual(cyclones.intensity_label(100, "TY"), "Category 3-equivalent typhoon")
        self.assertEqual(cyclones.intensity_label(140, "ST"), "Category 5-equivalent super typhoon")
        self.assertEqual(cyclones.intensity_label(65, "TC"), "Category 1-equivalent cyclone")
        self.assertEqual(cyclones.intensity_label(50, "TS"), "tropical storm")

    def test_a_past_position_west_of_100e_is_read(self):
        # JTWC pads a three-digit longitude with a space: 92W's positions
        # over the Andaman Sea on 26 September 2026 read "145N 997E". Read
        # as one token, every position west of 100 E was dropped.
        text = fixture("jtwc_sh0326.tcw").replace("S0", "S ")
        storm = jtwc.parse_tcw(text)
        self.assertEqual(len(storm.track), 7)
        self.assertEqual((storm.track[0].stamp, storm.track[0].lat, storm.track[0].lon),
                         ("2026011318", -12.1, 76.2))


class TestLowBeforeGenesis(unittest.TestCase):
    """A low that has never been a tropical cyclone is a low. The report called
    Invest 99E, stage LO in its deck, a "remnant low": the remnant of nothing."""

    @staticmethod
    def fix(stamp, stage, wind=25, tau=0):
        return cyclones.Fix(stamp=stamp, tau=tau, lat=12.0, lon=-100.0, wind=wind,
                            pressure=1008, stage=stage, tech="BEST" if not tau else "OFCL")

    def storm(self, track=(), forecast=(), **extra):
        return cyclones.Storm(basin="EP", number=99, year=2026, track=track,
                              forecast=forecast, **extra)

    def test_an_invest_s_low_is_a_low(self):
        invest = self.storm((self.fix("2026092506", "DB"), self.fix("2026092512", "LO")),
                            name="Invest 99E", invest=True)
        self.assertEqual((invest.latest.label, invest.latest.short), ("low", "low"))

    def test_a_non_tropical_low_before_genesis_is_not_post_tropical(self):
        invest = self.storm((self.fix("2026092512", "EX"),), invest=True)
        self.assertEqual((invest.latest.label, invest.latest.short),
                         ("non-tropical low", "non-trop low"))

    def test_a_storm_s_low_after_genesis_is_its_remnant(self):
        storm = self.storm((self.fix("2026091800", "LO"), self.fix("2026091806", "TD", 30),
                            self.fix("2026091812", "TS", 40), self.fix("2026092000", "LO"),
                            self.fix("2026092006", "EX")))
        self.assertEqual([f.label for f in storm.track],
                         ["low", "tropical depression", "tropical storm", "remnant low",
                          "post-tropical"])
        self.assertEqual([f.short for f in storm.track],
                         ["low", "trop dep", "trop storm", "rem low", "post-trop"])

    def test_a_forecast_low_after_forecast_genesis_is_a_remnant(self):
        # A potential tropical cyclone: a low now, a storm in a day, a remnant in five.
        ptc = self.storm((self.fix("2026092512", "LO", 30),),
                         (self.fix("2026092512", "LO", 30, tau=12),
                          self.fix("2026092512", "TS", 40, tau=24),
                          self.fix("2026092512", "LO", 25, tau=120)))
        self.assertEqual([f.label for f in ptc.forecast],
                         ["low", "tropical storm", "remnant low"])

    def test_a_track_given_after_the_storm_is_made_is_worded_by_it(self):
        # The builders fill in a storm's track and forecast after making it.
        storm = self.storm()
        storm.track = (self.fix("2026091800", "LO"), self.fix("2026091806", "TD", 30))
        self.assertEqual(storm.track[0].label, "low")
        storm.forecast = (self.fix("2026091806", "LO", tau=72),)
        self.assertEqual(storm.forecast[0].label, "remnant low")

    def test_a_fix_is_still_equal_to_itself(self):
        # Before or after genesis is the storm's to say, not part of the fix.
        low = self.fix("2026091800", "LO")
        self.assertEqual(self.storm((low,)).track, (low,))
        self.assertEqual(low.label, "remnant low")     # alone, no storm to ask

    def test_the_desk_and_the_report_call_an_invest_s_low_a_low(self):
        invest = self.storm((self.fix("2026092512", "LO"),), name="Invest 99E", invest=True)
        [point] = stormdesk._invest(invest)["track"]
        self.assertEqual(point["label"], "low")
        state = SimpleNamespace(cyclones=cyclones.CycloneState(
            basins={"EP": cyclones.BasinSeason(basin="EP", storms=())}, invests=(invest,)))
        text = "\n".join(report._section_outlook(state))
        self.assertRegex(text, r"Invest 99E\s+12\.0N 100\.0W\s+25 kt\s+low\s")
        self.assertNotIn("remnant", text)

    def test_the_desk_words_an_advisory_s_wind_for_a_low_as_a_low(self):
        # The advisory's wind differs from the deck's, so the desk words the
        # advisory's: a potential tropical cyclone read "Remnant low".
        ptc = self.storm((self.fix("2026092512", "LO", 30),),
                         name="Potential Tropical Cyclone Nine",
                         advisory={"lat": 12.1, "lon": -100.2, "wind": 35, "pressure": 1006,
                                   "last_update": "2026-09-25T15:00:00Z"})
        entry = stormdesk.storm_entry(ptc)
        self.assertEqual(stormdesk._latest(entry), (35, 1006, "low"))
        self.assertIn("<dt>Intensity</dt><dd>Low</dd>", stormdesk._now_pane(entry))
        self.assertIn("Low &middot; 35 kt &middot; 1006 mb", stormdesk._storm_row(entry, "#888"))
        # After genesis a low is still the storm's remnant.
        storm = self.storm((self.fix("2026092500", "TS", 40), self.fix("2026092512", "LO", 30)),
                           advisory=dict(ptc.advisory))
        self.assertEqual(stormdesk._latest(stormdesk.storm_entry(storm))[2], "remnant low")


class TestFormationAlert(unittest.TestCase):
    """JTWC's tropical cyclone formation alerts: the ATCF "ALERT" files the RSS
    links beside the warnings. On 29 September 2026 wp9326.tcw was the alert
    for Invest 93W, and the reader took it for a warning it did not know."""

    URL = "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw"
    CANCEL = "https://www.metoc.navy.mil/jtwc/products/wp9226.tcw"

    def alert(self, text=None, url=URL):
        return jtwc.formation_alert(fixture("jtwc_wp9326.tcw") if text is None else text, url)

    def advisory(self):
        """JTWC's ABPW10 reissued with the alert: 93W upgraded to high."""
        return jtwc.disturbances(fixture("jtwc_abpw_93w.txt"))

    @staticmethod
    def first_warning(ref="(WTPN21 PGTW 291700)"):
        """Surigae's warning as a first warning, ending the alert ``ref`` names."""
        return fixture("jtwc_wp2526.tcw").replace(
            "AMP", "THIS WARNING SUPERSEDES AND CANCELS REF A, JOINT TYPHOON WRNCEN PEARL\n"
                   f"HARBOR HI 291700Z SEP 26 TROPICAL CYCLONE FORMATION ALERT {ref}.\nAMP", 1)

    def test_an_alert_is_keyed_placed_and_timed(self):
        alert = self.alert()
        self.assertEqual((alert.key, alert.label), ("93w", "Invest 93W"))
        self.assertEqual((alert.lat, alert.lon), (15.9, 152.8))
        self.assertEqual(alert.issued, "2026-09-29T17:00:00Z")
        # "REISSUED, UPGRADED TO WARNING OR CANCELLED BY 301700Z"
        self.assertEqual(alert.until, "2026-09-30T17:00:00Z")
        self.assertEqual(alert.potential, "high")
        self.assertFalse(alert.cancelled)

    def test_an_alert_says_how_the_system_moves_and_how_strong_it_is(self):
        alert = self.alert()
        self.assertEqual(alert.motion, "west-northwest at 14 kt")
        self.assertEqual(alert.wind, (18, 23))
        self.assertEqual(alert.pressure, 1005)

    def test_the_area_is_the_line_widened_120_nm_either_side(self):
        box = self.alert().box
        self.assertEqual(len(box), 5)
        self.assertEqual(box[0], box[-1])
        start, end = (153.1, 15.9), (147.9, 16.0)
        for corner in box[:4]:
            self.assertAlmostEqual(min(cyclones.great_circle(*corner, *start),
                                       cyclones.great_circle(*corner, *end)),
                                   120 * 1.852, delta=1.0)
        # The line's two ends are the middles of the box's short sides.
        for (a, b), end_point in (((box[0], box[3]), start), ((box[1], box[2]), end)):
            middle = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            self.assertLess(cyclones.great_circle(*middle, *end_point), 3.0)

    def test_an_alert_round_a_point_is_a_circle(self):
        text = fixture("jtwc_wp9326.tcw").replace(
            "120 NM EITHER SIDE OF A LINE FROM 15.9N 153.1E TO 16.0N 147.9E",
            "150 NM RADIUS OF 15.9N 152.8E")
        box = self.alert(text).box
        self.assertEqual(box[0], box[-1])
        self.assertGreaterEqual(len(box), 25)
        for point in box:
            self.assertAlmostEqual(cyclones.great_circle(*point, 152.8, 15.9),
                                   150 * 1.852, delta=1.0)

    def test_the_invest_s_letter_is_its_ocean_s(self):
        for name, lat, lon, key in (("io9326", "12.0N", 88.0, "93b"),
                                    ("io9326", "12.0N", 65.0, "93a"),
                                    ("sh9327", "12.0S", 120.0, "93s"),
                                    ("sh9327", "12.0S", 160.0, "93p"),
                                    ("wp9326", "15.9N", 152.8, "93w")):
            text = fixture("jtwc_wp9326.tcw").replace("15.9N 152.8E", f"{lat} {lon:.1f}E")
            alert = self.alert(text, f"https://www.metoc.navy.mil/jtwc/products/{name}.tcw")
            self.assertEqual(alert.key, key, name)
        self.assertEqual(alert.label, "Invest 93W")

    def test_the_invest_the_alert_names_is_its_key(self):
        # 92W crossed into the Andaman Sea keeping its name, under an Indian
        # Ocean heading (WTIO21): the letter is the invest's, not the ocean's.
        self.assertEqual(jtwc.formation_alert(fixture("jtwc_wp9226_cancel.tcw")).key, "92w")

    def test_a_cancellation_is_read_as_one(self):
        alert = jtwc.formation_alert(fixture("jtwc_wp9226_cancel.tcw"), self.CANCEL)
        self.assertTrue(alert.cancelled)
        self.assertEqual((alert.lat, alert.lon), (17.4, 97.4))
        self.assertEqual(alert.issued, "2026-09-28T17:30:00Z")
        self.assertEqual(alert.box, ())

    def test_what_is_not_an_alert_is_none(self):
        self.assertIsNone(jtwc.formation_alert(fixture("jtwc_wp2526.tcw")))
        self.assertIsNone(jtwc.formation_alert("<html>404 Not Found</html>"))
        # A storm's first warning cancels the alert it grew from, and is a warning.
        first = fixture("jtwc_wp2526.tcw").replace(
            "AMP", "THIS WARNING SUPERSEDES AND CANCELS REF A, JOINT TYPHOON WRNCEN PEARL "
                   "HARBOR HI 291700Z SEP 26 TROPICAL CYCLONE FORMATION ALERT (WTPN21 PGTW "
                   "291700).\nAMP", 1)
        self.assertIn("FORMATION ALERT", first)
        self.assertIsNone(jtwc.formation_alert(first))
        self.assertIsNotNone(jtwc.parse_tcw(first))

    def test_a_first_warning_is_a_warning_however_its_remarks_wrap(self):
        # JTWC wraps a warning's remarks near 66 columns. Wherever the wrap put
        # "ALERT" at the start of a line, a storm's first warning was read as
        # a formation alert and the storm left the desk for the run.
        remark = ("THIS WARNING SUPERSEDES AND CANCELS REF A, JOINT TYPHOON WRNCEN "
                  "PEARL HARBOR HI 291700Z SEP 26 TROPICAL CYCLONE FORMATION ALERT "
                  "(WTPN21 PGTW 291700).")
        starts = 0
        for width in range(40, 81):
            lines = textwrap.wrap(remark, width)
            starts += any(line.startswith("ALERT") for line in lines)
            first = fixture("jtwc_wp2526.tcw").replace("AMP", "\n".join(lines) + "\nAMP", 1)
            self.assertIsNone(jtwc.formation_alert(first), width)
            self.assertIsNotNone(jtwc.parse_tcw(first), width)
        self.assertTrue(starts)     # some width puts ALERT at a line's start

    def test_a_first_warning_ends_the_alert_its_remarks_name(self):
        # "THIS WARNING SUPERSEDES AND CANCELS REF A, ... FORMATION ALERT
        # (WTPN21 PGTW 291700)": while the feed still linked the alert, the
        # desk drew the storm and a live alert box for the one system.
        text = self.first_warning()
        end = jtwc.superseding(text, jtwc.parse_tcw(text))
        self.assertTrue(end.cancelled)
        self.assertEqual((end.ref, end.issued, end.lat, end.lon, end.box),
                         ("WTPN21 PGTW 291700", "2026-09-25T15:00:00Z", 21.4, 128.2, ()))
        self.assertEqual(self.alert().ref, "WTPN21 PGTW 291700")
        self.assertEqual(jtwc.superseded([self.alert()], [end]), [end])
        other = dataclasses.replace(self.alert(), ref="WTPN22 PGTW 291800", key="94w")
        self.assertEqual(jtwc.superseded([other], [end]), [other, end])
        plain = fixture("jtwc_wp2526.tcw")
        self.assertIsNone(jtwc.superseding(plain, jtwc.parse_tcw(plain)))

    def test_a_first_warning_naming_no_heading_ends_the_older_alert_beside_it(self):
        text = self.first_warning(ref="")
        end = jtwc.superseding(text, jtwc.parse_tcw(text))
        self.assertEqual(end.ref, "")
        beside = dataclasses.replace(self.alert(), lon=128.9, lat=20.8,
                                     issued="2026-09-25T06:00:00Z")
        far = dataclasses.replace(beside, lon=140.0)
        later = dataclasses.replace(beside, issued="2026-09-25T18:00:00Z")
        self.assertEqual(jtwc.superseded([beside, far, later], [end]), [far, later, end])

    def test_an_alert_whose_time_was_not_given_is_kept(self):
        # With no WMO heading its issue time is unknown, and any advisory read
        # that run hid it: "" is older than every time.
        unknown = dataclasses.replace(self.alert(), issued="")
        [[own]] = jtwc.alerted([], [unknown], {"ABPW": "2026-09-30T06:00:00Z"})
        self.assertTrue(own.alert)
        self.assertEqual((own.area, own.issued), (unknown.box, ""))
        plain = [dataclasses.replace(a, alert=False) for a in self.advisory()]
        [[laid]] = jtwc.alerted([plain], [unknown], {})
        self.assertTrue(laid.alert)
        self.assertEqual(laid.area, unknown.box)
        # Not known to be the newer, it leaves the advisory's place and time.
        self.assertEqual((laid.lat, laid.lon, laid.issued),
                         (plain[0].lat, plain[0].lon, plain[0].issued))

    def test_two_alerts_that_name_no_invest_are_two_areas(self):
        # Keyed "", both were raised as tc_formation_ and one hid the other.
        one = dataclasses.replace(self.alert(), key="", label="Formation alert area")
        two = dataclasses.replace(one, lon=160.0, lat=12.0)
        [areas] = jtwc.alerted([], [one, two], {})
        self.assertEqual([a.key for a in areas], ["tcfa-16n153e", "tcfa-12n160e"])
        raised = alerts.product_rules(SimpleNamespace(active=(), outlook=areas))
        self.assertEqual(sorted(a.code for a in raised),
                         ["tc_formation_tcfa-12n160e", "tc_formation_tcfa-16n153e"])

    def test_an_alert_s_motion_in_other_words(self):
        said = "THE SYSTEM IS MOVING WEST-NORTHWESTWARD AT 14\nKNOTS."
        for words, motion, fact in (
                ("THE SYSTEM IS DRIFTING SLOWLY WESTWARD.", "slowly west", "moving slowly west"),
                ("THE SYSTEM IS DRIFTING NORTHWARD.", "slowly north", "moving slowly north"),
                ("THE SYSTEM IS TRACKING NORTHWARD AT 05 KNOTS.", "north at 5 kt",
                 "moving north at 5 kt"),
                ("THE SYSTEM IS QUASI-STATIONARY.", "quasi-stationary", "quasi-stationary"),
                ("THE SYSTEM IS TRACKING POLEWARD AT 08 KNOTS.", "poleward at 8 kt",
                 "moving poleward at 8 kt"),
                # The system's motion is stated before any forecast of it.
                ("THE SYSTEM IS QUASI-STATIONARY. MODELS AGREE IT WILL BEGIN TRACKING "
                 "NORTHWESTWARD.", "quasi-stationary", "quasi-stationary")):
            alert = self.alert(fixture("jtwc_wp9326.tcw").replace(said, words))
            self.assertEqual(alert.motion, motion, words)
            self.assertEqual(alert.facts()[0], fact, words)

    def test_an_alert_past_its_time_has_lapsed(self):
        # "THIS ALERT WILL BE REISSUED, UPGRADED TO WARNING OR CANCELLED BY
        # 301700Z": past that, with nothing newer read, it is not in effect.
        alert = self.alert()
        self.assertEqual(alert.until, "2026-09-30T17:00:00Z")
        self.assertFalse(alert.lapsed("2026-09-30T16:59:00+00:00"))
        self.assertTrue(alert.lapsed("2026-09-30T17:00:00+00:00"))
        self.assertTrue(alert.lapsed("2026-09-30T18:05:00Z"))
        self.assertFalse(alert.lapsed(None))
        self.assertFalse(alert.lapsed("not a time"))
        self.assertFalse(dataclasses.replace(alert, until="").lapsed("2026-10-01T00:00:00Z"))

    def test_an_alert_lays_its_area_and_facts_on_the_advisory_s_invest(self):
        [area] = outlook.merge(*jtwc.alerted([self.advisory()], [self.alert()], {}))
        self.assertEqual((area.key, area.label, area.centre), ("93w", "Invest 93W", "JTWC"))
        self.assertTrue(area.alert)
        self.assertEqual(area.area, self.alert().box)
        self.assertEqual(area.formation, self.alert())
        self.assertEqual(area.formation.until, "2026-09-30T17:00:00Z")
        self.assertIn("ECENS", area.text)     # the advisory's words stay

    def test_an_alert_no_advisory_lists_yet_is_an_area_of_its_own(self):
        [area] = outlook.merge(*jtwc.alerted([], [self.alert()], {}))
        self.assertEqual((area.key, area.label, area.basin, area.potential),
                         ("93w", "Invest 93W", "WP", "high"))
        self.assertTrue(area.alert)
        self.assertEqual((area.lat, area.lon, area.issued),
                         (15.9, 152.8, "2026-09-29T17:00:00Z"))
        self.assertEqual(area.area, self.alert().box)
        self.assertEqual(area.formation, self.alert())

    def test_the_newer_of_alert_and_advisory_places_the_system(self):
        older = [dataclasses.replace(a, issued="2026-09-29T06:00:00Z", lat=15.4, lon=155.0)
                 for a in self.advisory()]
        [[area]] = jtwc.alerted([older], [self.alert()], {})
        self.assertEqual((area.lat, area.lon, area.issued),
                         (15.9, 152.8, "2026-09-29T17:00:00Z"))
        newer = [dataclasses.replace(a, issued="2026-09-30T06:00:00Z", lat=16.5, lon=150.0)
                 for a in self.advisory()]
        [[area]] = jtwc.alerted([newer], [self.alert()], {})
        self.assertEqual((area.lat, area.lon, area.issued),
                         (16.5, 150.0, "2026-09-30T06:00:00Z"))
        self.assertEqual(area.area, self.alert().box)    # still in effect, still drawn

    def test_an_alert_a_later_advisory_no_longer_cites_is_over(self):
        # Reissued after the alert, the advisory says no alert is in effect:
        # it was cancelled or became a warning, and the box is not drawn.
        later = [dataclasses.replace(a, issued="2026-09-30T06:00:00Z", alert=False)
                 for a in self.advisory()]
        [[area]] = jtwc.alerted([later], [self.alert()], {})
        self.assertEqual((area.area, area.formation, area.alert), ((), None, False))
        # And a later advisory that lists the system no longer has no area for it.
        self.assertEqual(jtwc.alerted([], [self.alert()], {"ABPW": "2026-09-30T06:00:00Z"}),
                         [])
        self.assertEqual(len(jtwc.alerted([], [self.alert()], {"ABIO": "2026-09-30T06:00:00Z"})),
                         1)

    def test_a_cancellation_clears_an_older_advisory_s_alert_and_draws_nothing(self):
        cancel = jtwc.formation_alert(fixture("jtwc_wp9226_cancel.tcw"), self.CANCEL)
        cited = outlook.Disturbance(
            centre="JTWC", basin="IO", label="Invest 92W", lon=97.8, lat=16.0,
            chance_2day=None, chance_7day=None, potential="high", text="", area=(),
            arrow=(), alert=True, issued="2026-09-28T06:00:00Z", key="92w")
        [[area]] = jtwc.alerted([[cited]], [cancel], {})
        self.assertFalse(area.alert)
        self.assertEqual(area.area, ())
        self.assertEqual(jtwc.alerted([], [cancel], {}), [])

    def test_an_alert_finds_an_area_the_advisory_did_not_number(self):
        unnumbered = outlook.Disturbance(
            centre="JTWC", basin="WP", label="Area of convection", lon=153.4, lat=15.2,
            chance_2day=None, chance_7day=None, potential="medium", text="", area=(),
            arrow=(), alert=False, issued="2026-09-29T06:00:00Z", key="jtwc1-1")
        [[area]] = jtwc.alerted([[unnumbered]], [self.alert()], {})
        self.assertEqual((area.key, area.label, area.potential), ("93w", "Invest 93W", "high"))
        self.assertTrue(area.alert)


class TestOutlook(unittest.TestCase):
    """Where new storms may form: NHC's outlooks, JTWC's advisories, invests."""

    def test_the_east_pacific_outlook(self):
        issued, areas = outlook.nhc(fixture("gtwo_pac.kml"), "EP")
        self.assertIn("Fri Sep 25", issued)
        self.assertEqual([(a.chance_2day, a.chance_7day) for a in areas], [(40, 90), (20, 50)])
        self.assertEqual(areas[0].potential, "high")
        self.assertIn("Gulf of Tehuantepec", areas[0].text)
        self.assertTrue(areas[0].area and areas[0].arrow)

    def test_an_area_is_named_and_keyed_as_nhc_numbers_it(self):
        issued, areas = outlook.nhc(fixture("gtwo_pac.kml"), "EP")
        self.assertEqual(areas[0].label, "South of the Gulf of Tehuantepec")
        self.assertEqual([a.key for a in areas], ["ep1", "ep2"])
        self.assertEqual((areas[0].centre, areas[0].issued), ("NHC", issued))
        self.assertAlmostEqual(areas[0].lon, -92.689, places=3)
        self.assertAlmostEqual(areas[0].lat, 10.868, places=3)
        self.assertFalse(areas[0].alert)

    def test_an_error_page_is_not_an_outlook_with_nothing_expected(self):
        with self.assertRaises(ValueError):
            outlook.nhc(TestProtectiveProducts.ERROR_PAGE, "EP")
        with self.assertRaises(ValueError):
            jtwc.disturbances("<html><body>The server is busy</body></html>")

    def test_nothing_expected_is_an_empty_list(self):
        issued, areas = outlook.nhc(fixture("gtwo_atl.kml"), "AL")
        self.assertEqual(areas, [])
        self.assertIn("Fri Sep 25", issued)

    def test_a_system_both_centres_list_is_kept_once_by_its_owner(self):
        _, ep = outlook.nhc(fixture("gtwo_pac.kml"), "EP")
        _, cp = outlook.nhc(fixture("gtwo_cpac.kml"), "CP")
        merged = outlook.merge(ep, cp)
        self.assertEqual(len(merged), 2)
        hawaii = [d for d in merged if d.lon < -140][0]
        self.assertEqual((hawaii.centre, hawaii.basin), ("CPHC", "CP"))

    def test_two_areas_of_one_outlook_are_never_merged(self):
        def area(key, lon):
            return outlook.Disturbance(
                centre="NHC", basin="EP", label=key, lon=lon, lat=12.0,
                chance_2day=10, chance_7day=20, potential="low", text="",
                area=(), arrow=(), alert=False, issued="", key=key)
        self.assertEqual(len(outlook.merge([area("ep1", -110.0), area("ep2", -110.5)])), 2)

    def test_the_likeliest_first_then_jtwc_by_potential(self):
        _, ep = outlook.nhc(fixture("gtwo_pac.kml"), "EP")
        _, cp = outlook.nhc(fixture("gtwo_cpac.kml"), "CP")
        found = jtwc.disturbances(fixture("jtwc_abpw_invests.txt"))
        merged = outlook.merge(ep, cp, found)
        self.assertEqual([d.key for d in merged], ["ep1", "cp1", "98w", "91p", "97w"])

    def test_areas_of_responsibility(self):
        self.assertEqual(outlook.aor(-45.0, 20.0), "AL")
        self.assertEqual(outlook.aor(-120.0, 15.0), "EP")
        self.assertEqual(outlook.aor(-150.0, 15.0), "CP")
        self.assertEqual(outlook.aor(-90.0, 10.0), "EP")   # Pacific side of Central America
        self.assertEqual(outlook.aor(-80.0, 20.0), "AL")   # Caribbean

    def test_areas_of_responsibility_beyond_nhc(self):
        self.assertEqual(outlook.aor(147.4, 14.6), "WP")
        self.assertEqual(outlook.aor(179.0, 10.0), "WP")
        self.assertEqual(outlook.aor(-179.5, 10.0), "CP")
        self.assertEqual(outlook.aor(190.0, 10.0), "CP")   # 170 W, however written
        self.assertEqual(outlook.aor(88.0, 15.0), "IO")
        self.assertEqual(outlook.aor(-172.9, -13.4), "SH")

    def test_invests_come_from_the_listing(self):
        self.assertEqual(outlook.invest_candidates(fixture("atcf_btk_listing.html")),
                         ["al902026", "ep992026"])

    def test_jtwc_advisory_disturbances(self):
        self.assertEqual(jtwc.disturbances(fixture("jtwc_abpw.txt")), [])
        found = jtwc.disturbances(fixture("jtwc_abpw_invests.txt"))
        self.assertEqual([d.label for d in found], ["Invest 97W", "Invest 98W", "Invest 91P"])
        self.assertEqual([d.potential for d in found], ["low", "high", "medium"])
        self.assertEqual((found[0].lat, found[0].lon), (14.6, 147.4))
        self.assertEqual((found[2].lat, found[2].lon), (-13.4, -172.9))
        self.assertTrue(found[1].alert)       # it cites a formation alert
        self.assertEqual(found[0].centre, "JTWC")

    def test_jtwc_disturbances_are_keyed_placed_and_timed(self):
        found = jtwc.disturbances(fixture("jtwc_abpw_invests.txt"))
        self.assertEqual([d.key for d in found], ["97w", "98w", "91p"])
        self.assertEqual([d.basin for d in found], ["WP", "WP", "SH"])
        self.assertFalse(found[0].alert)
        self.assertEqual(found[0].issued, "2026-09-21T06:00:00Z")
        self.assertEqual((found[1].lat, found[1].lon), (10.1, 131.2))
        self.assertIsNone(found[0].chance_7day)

    def test_an_area_jtwc_has_stopped_watching_is_not_listed(self):
        # 97W dissipated, 98W became Tropical Depression 26W, and 03P's
        # remnants are no longer suspect: none is rated, and each was listed
        # as a live "unrated" area at the position it had left.
        found = jtwc.disturbances(fixture("jtwc_abpw_gone.txt"))
        self.assertEqual([d.key for d in found], ["99w", "91p"])
        self.assertEqual([d.potential for d in found], ["low", "medium"])


def _radii_fix(stamp, tau, lat, lon, wind, r34=None, r64=None):
    radii = tuple(pair for pair in ((34, r34), (64, r64)) if pair[1])
    return cyclones.Fix(stamp=stamp, tau=tau, lat=lat, lon=lon, wind=wind,
                        pressure=None, stage="HU", tech="OFCL", radii=radii)


class TestExposure(unittest.TestCase):
    """When each wind threshold reaches each place, along the official track."""

    def storm(self, *extra):
        now = _radii_fix("2026092512", 0, 15.0, -150.0, 90, (60,) * 4, (20,) * 4)
        ahead = (_radii_fix("2026092512", 12, 16.0, -150.0, 90, (60,) * 4, (20,) * 4),
                 _radii_fix("2026092512", 24, 17.0, -150.0, 90, (60,) * 4, (20,) * 4)) + extra
        return cyclones.Storm(basin="CP", number=1, year=2026, name="Test",
                              track=(now,), forecast=ahead, advisory={"x": 1})

    def test_quadrants(self):
        radii = (10, 20, 30, 40)
        self.assertEqual([exposure.radius_toward(radii, b) for b in (45, 135, 225, 315)],
                         [10, 20, 30, 40])

    def test_bearings(self):
        self.assertAlmostEqual(exposure.bearing(0.0, 0.0, 0.0, 1.0), 0.0, places=6)
        self.assertAlmostEqual(exposure.bearing(0.0, 0.0, 1.0, 0.0), 90.0, places=6)
        self.assertAlmostEqual(exposure.bearing(179.5, 0.0, -179.5, 0.0), 90.0, places=6)

    def test_arrival_of_each_threshold_along_the_official_track(self):
        place = atlasdata.Place("Here", "Nowhere", "", 1000, -150.0, 16.55, False)
        [hit] = exposure.exposures(self.storm(), places=(place,))
        self.assertEqual(hit.arrival[34], "2026092519")
        self.assertEqual(hit.arrival[64], "2026092603")

    def test_the_closest_approach_is_when_and_how_near(self):
        place = atlasdata.Place("Here", "Nowhere", "", 1000, -150.0, 16.55, False)
        [hit] = exposure.exposures(self.storm(), places=(place,))
        self.assertEqual(hit.closest_stamp, "2026092607")
        self.assertLess(hit.closest_km, 10.0)
        self.assertEqual((hit.place, hit.country, hit.population), ("Here", "Nowhere", 1000))

    def test_a_place_the_wind_never_reaches_is_not_listed(self):
        far = atlasdata.Place("Far", "Nowhere", "", 1000, -140.0, 16.0, False)
        self.assertEqual(exposure.exposures(self.storm(), places=(far,)), [])

    def test_a_hair_from_the_centre_is_at_the_centre(self):
        # A point a rounding error from the centre has a bearing that is only
        # noise; toward a quadrant the wind does not reach it was outside.
        fix = _radii_fix("2026092512", 12, 16.0, -150.0, 90, (60, 0, 0, 0), None)
        self.assertTrue(exposure.inside(fix, -150.0, 16.0, 34))
        self.assertTrue(exposure.inside(fix, -150.0 - 1e-12, 16.0 - 1e-12, 34))

    def test_unforecast_radii_are_unknown_not_calm(self):
        fix = _radii_fix("2026092512", 96, 16.0, -150.0, 100, (60,) * 4, None)
        self.assertIsNone(exposure.inside(fix, -150.0, 16.1, 64))
        weak = _radii_fix("2026092512", 96, 16.0, -150.0, 50, (60,) * 4, None)
        self.assertFalse(exposure.inside(weak, -150.0, 16.1, 64))

    def test_outside_the_gale_field_is_outside_the_hurricane_field(self):
        # 64-kt winds lie inside the 34-kt field, so a place outside the
        # forecast 34-kt radius is outside hurricane-force wind even when
        # the 64-kt radius was not forecast.
        fix = _radii_fix("2026092512", 96, 16.0, -150.0, 100, (60,) * 4, None)
        self.assertFalse(exposure.inside(fix, -150.0, 18.0, 64))
        blind = _radii_fix("2026092512", 96, 16.0, -150.0, 100, None, None)
        self.assertIsNone(exposure.inside(blind, -150.0, 18.0, 64))

    def test_an_exposure_says_what_was_not_forecast(self):
        # NHC forecasts the 64-kt radius to 72 h and no further: past 24 h
        # this hurricane has its 34- and 50-kt radii and no 64-kt one.
        def fix(tau, lat, wind, r64):
            radii = ((34, (60,) * 4), (50, (40,) * 4)) + (((64, r64),) if r64 else ())
            return cyclones.Fix(stamp="2026092512", tau=tau, lat=lat, lon=-150.0,
                                wind=wind, pressure=None, stage="HU", tech="OFCL",
                                radii=radii)
        storm = cyclones.Storm(
            basin="CP", number=1, year=2026, name="Test",
            track=(fix(0, 15.0, 90, (20,) * 4),),
            forecast=(fix(12, 16.0, 90, (20,) * 4), fix(24, 17.0, 90, (20,) * 4),
                      fix(96, 17.5, 100, None)),
            advisory={"x": 1})
        close = atlasdata.Place("Close", "Nowhere", "", 1000, -150.0, 17.6, False)
        [hit] = exposure.exposures(storm, places=(close,))
        self.assertEqual(hit.arrival[34], "2026092608")
        self.assertIsNone(hit.arrival[64])
        self.assertEqual(hit.unknown, (64,))
        # Outside the forecast 50-kt radius is outside hurricane force too.
        beyond = atlasdata.Place("Beyond", "Nowhere", "", 1000, -150.0, 18.3, False)
        [hit] = exposure.exposures(storm, places=(beyond,))
        self.assertEqual(hit.arrival[34], "2026092808")
        self.assertEqual(hit.unknown, ())
        # Beside the track early on and far from it by then: no hurricane
        # wind, and nothing unknown about that.
        beside = atlasdata.Place("Beside", "Nowhere", "", 1000, -149.2, 16.0, False)
        [hit] = exposure.exposures(storm, places=(beside,))
        self.assertIsNotNone(hit.arrival[34])
        self.assertIsNone(hit.arrival[64])
        self.assertEqual(hit.unknown, ())

    def test_the_timeline_is_hourly_from_the_analysis(self):
        storm = self.storm()
        line = exposure.timeline(storm.latest, storm.forecast)
        self.assertEqual([f.tau for f in line], list(range(25)))
        self.assertAlmostEqual(line[6].lat, 15.5)
        self.assertEqual(line[6].radius(34), (60, 60, 60, 60))

    def test_an_analysis_from_another_cycle_does_not_start_the_line(self):
        storm = self.storm()
        old = _radii_fix("2026092506", 0, 14.0, -150.0, 80, (50,) * 4, (10,) * 4)
        line = exposure.timeline(old, storm.forecast)
        self.assertEqual(line[0].tau, 12)

    def test_the_antimeridian_is_crossed_the_short_way(self):
        path = [(0.0, 179.5, 10.0), (43200.0, -179.5, 10.0)]
        lon, lat = exposure.centre_at(path, 21600.0)
        self.assertAlmostEqual(abs(lon), 180.0, places=6)
        self.assertIsNone(exposure.centre_at(path, 50000.0))

    def test_a_timeline_across_180_goes_the_short_way(self):
        a = _radii_fix("2026092512", 12, 10.0, 179.5, 90, (60,) * 4, (20,) * 4)
        b = _radii_fix("2026092512", 24, 10.0, -179.5, 90, (60,) * 4, (20,) * 4)
        line = exposure.timeline(None, (a, b))
        self.assertTrue(all(abs(f.lon) >= 179.5 for f in line))


class TestViewGeometry(unittest.TestCase):
    """Which geostationary satellite sees the eye best, and where it appears."""

    def test_zenith_angles(self):
        self.assertAlmostEqual(exposure.view_zenith(-108.5, 17.1, -137.0), 38.24, places=1)
        self.assertIsNone(exposure.view_zenith(10.0, 0.0, -137.0))  # below the horizon

    def test_the_best_view(self):
        self.assertEqual(exposure.best_satellite(-108.5, 17.1)[0], "GOES-West")
        self.assertEqual(exposure.best_satellite(-22.7, 15.1)[0], "GOES-East")
        self.assertEqual(exposure.best_satellite(128.2, 21.4)[0], "Himawari")
        self.assertIsNone(exposure.best_satellite(71.2, -15.8))

    def test_parallax_moves_cloud_tops_away_from_the_satellite(self):
        lon, lat = exposure.parallax(-108.5, 17.1, -137.0)
        km = cyclones.great_circle(-108.5, 17.1, lon, lat)
        self.assertAlmostEqual(km, 11.8, delta=0.3)
        self.assertGreater(lon, -108.5)
        self.assertGreater(lat, 17.1)


class TestStormProductsWiring(unittest.TestCase):
    """The cyclone tier fetches what each centre issued, and says what it could not."""

    API = "https://www.nhc.noaa.gov/storm_graphics/api/"
    TEXT = "https://www.nhc.noaa.gov/text/"

    def current(self) -> str:
        def storm(key, name, advisory, ww=None, cone=None, pws=None, surge=None,
                  public="PUB.shtml"):
            def link(field, url):
                return {"advNum": advisory, field: url} if url else None
            return {
                "id": key, "name": name, "classification": "HU", "intensity": "75",
                "pressure": "980", "latitudeNumeric": 16.0, "longitudeNumeric": -155.5,
                "movementDir": 300, "movementSpeed": 9,
                "lastUpdate": "2026-09-25T15:00:00.000Z",
                "publicAdvisory": {"advNum": advisory, "url": self.TEXT + public},
                "windWatchesWarnings": link("kmzFile", ww),
                "trackCone": link("kmzFile", cone),
                "windSpeedProbabilities": link("url", pws),
                "peakSurgeKML": link("peakSurgeKMLFile", surge),
            }
        return json.dumps({"activeStorms": [
            storm("ep152026", "Nolo", "020", ww=self.API + "EP152026_020adv_WW.kmz",
                  cone=self.API + "EP152026_020adv_CONE.kmz",
                  pws=self.TEXT + "HFOPWSCP2.shtml",
                  surge=self.API + "EP152026_PeakStormSurge_020adv.kml",
                  public="HFOTCPCP2.shtml"),
            storm("ep162026", "Odalys", "023", ww=self.API + "EP162026_023adv_WW.kmz"),
            storm("ep172026", "Polo", "021", pws=self.TEXT + "MIAPWSEP2.shtml",
                  public="MIATCPEP2.shtml"),
        ]})

    def test_the_index_gives_motion_in_mph_and_it_is_kept_so(self):
        # CurrentStorms.json gives the forward speed in mph, as the public
        # advisory does: on 25 September 2026 at 15Z Polo's entry was 270 at
        # 12, the advisory "toward the west near 12 mph" and the discussion
        # 270/10 kt. Read as knots, every speed was 15 percent fast.
        meta = cyclones.parse_current(self.current())["ep152026"]
        self.assertEqual((meta["movement_dir"], meta["movement_mph"]), (300, 9))
        self.assertEqual(meta["movement_kt"], 8)

    def fetcher(self):
        best = [("2026092506", 0, "155N", "1546W", 70, 985, "HU", "BEST", 34),
                ("2026092512", 0, "160N", "1553W", 75, 980, "HU", "BEST", 34)]
        pages = {
            self.API + "EP152026_020adv_WW.kmz": fixture("ww_ep152026.kml"),
            self.API + "EP152026_020adv_CONE.kmz": fixture("cone_ep152026.kml"),
            self.TEXT + "HFOPWSCP2.shtml": fixture("pws_ep152026.shtml"),
            self.API + "EP152026_PeakStormSurge_020adv.kml": fixture("surge_ep152026.kml"),
            # Polo's page carries advisory 20 while the index is at 21.
            self.TEXT + "MIAPWSEP2.shtml": fixture("pws_ep152026.shtml"),
            # Nolo's public advisory as it stood at 20: 21 changed nothing in
            # effect. Polo's, at 21, has nothing in effect.
            self.TEXT + "HFOTCPCP2.shtml": fixture("tcp_hfotcpcp2.shtml").replace(
                "Advisory Number  21", "Advisory Number  20"),
            self.TEXT + "MIATCPEP2.shtml": fixture("tcp_miatcpep2.shtml"),
            sources.deck_source("b", "ep152026").url: _deck(best),
            sources.deck_source("f", "ep152026").url: FST_NOLO,
            sources.deck_source("b", "ep162026").url: _deck(best),
            sources.deck_source("b", "ep172026").url: _deck(best),
            sources.deck_source("b", "ep992026").url: _deck(
                [("2026092512", 0, "102N", "1005W", 25, 1008, "DB", "BEST", 34)]),
            sources.deck_source("b", "al902026").url: _deck(
                [("2026090112", 0, "120N", "0400W", 25, 1009, "DB", "BEST", 34)]),
            "https://www.metoc.navy.mil/jtwc/products/wp2526.tcw": fixture("jtwc_wp2526.tcw"),
        }

        def fetch(source):
            text = pages.get(source.url, "")
            return sources.Fetched(source, text, "", False, "",
                                   error=None if text else "HTTP Error 404: Not Found")
        return fetch

    def state(self, fetcher=None, current=None, **feeds):
        texts = {
            "nhc_current": current or self.current(),
            "atcf_index": fixture("atcf_btk_listing.html"),
            "nhc_outlook_at": fixture("gtwo_atl.kml"),
            "nhc_outlook_ep": fixture("gtwo_pac.kml"),
            "nhc_outlook_cp": fixture("gtwo_cpac.kml"),
            "jtwc_rss": fixture("jtwc.rss"),
            "jtwc_abpw": fixture("jtwc_abpw_invests.txt"),
            **feeds,
        }
        fetched = {key: sources.Fetched(sources.SOURCES_BY_KEY[key], text, "", False, "")
                   for key, text in texts.items()}
        return cyclones.build(fetched, fetcher=fetcher or self.fetcher(),
                              today=date(2026, 9, 25))

    def storm(self, state, key):
        return [s for s in state.storms if s.key == key][0]

    def test_every_product_issued_for_a_storm_is_read(self):
        nolo = self.storm(self.state(), "ep152026")
        self.assertTrue(nolo.products.watches)
        self.assertEqual(nolo.products.cone[0], nolo.products.cone[-1])
        self.assertEqual(nolo.products.winds.advisory, "20")
        self.assertEqual(len(nolo.products.surge), 4)
        self.assertEqual(nolo.products.advisory, "20")
        self.assertEqual(nolo.products.notes, ())

    def test_none_issued_is_not_unavailable(self):
        state = self.state()
        polo = self.storm(state, "ep172026")
        self.assertEqual(polo.products.watches, ())
        self.assertEqual(polo.products.cone, ())
        self.assertFalse(any("atch" in note for note in polo.products.notes))
        odalys = self.storm(state, "ep162026")
        self.assertIsNone(odalys.products.watches)
        self.assertTrue(any("unavailable" in note for note in odalys.products.notes))

    def test_a_product_from_an_older_advisory_says_so(self):
        polo = self.storm(self.state(), "ep172026")
        self.assertIsNotNone(polo.products.winds)
        self.assertTrue(any("advisory 20" in note and "21" in note
                            for note in polo.products.notes))

    def test_jtwc_storms_are_live_but_not_in_the_season(self):
        state = self.state()
        [surigae] = state.others
        self.assertEqual((surigae.centre, surigae.name), ("JTWC", "Surigae"))
        self.assertIn(surigae, state.active)
        self.assertIn(surigae, state.storms)
        for season in state.basins.values():
            self.assertNotIn(surigae, season.storms)
        self.assertIsNone(surigae.products)

    def test_a_formation_alert_the_feed_links_is_read_not_noted(self):
        # On 29 September 2026 the feed linked wp9326.tcw, JTWC's formation
        # alert for Invest 93W, and the run was marked degraded for it.
        tcfa = "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw"
        fetch = self.fetcher()

        def patched(source):
            if source.url == tcfa:
                return sources.Fetched(source, fixture("jtwc_wp9326.tcw"), "", False, "")
            return fetch(source)
        rss = fixture("jtwc.rss").replace(
            "<li><a href='https://www.metoc.navy.mil/jtwc/products/wp2526.tcw'",
            f"<li><a href='{tcfa}' target='newwin'>JMV 3.0 Data</a></li>\n"
            "<li><a href='https://www.metoc.navy.mil/jtwc/products/wp2526.tcw'")
        state = self.state(patched, jtwc_rss=rss, jtwc_abpw=fixture("jtwc_abpw_93w.txt"))
        self.assertEqual([n for n in state.notes if "wp9326" in n], [])
        [alert] = state.alerts
        self.assertEqual(alert.key, "93w")
        [area] = [d for d in state.outlook if d.key == "93w"]
        self.assertEqual((area.area, area.formation), (alert.box, alert))
        self.assertEqual([s.name for s in state.others], ["Surigae"])

    def test_a_first_warning_ends_its_alert_though_the_feed_still_links_it(self):
        tcfa = "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw"
        warning = fixture("jtwc_wp2526.tcw").replace(
            "AMP", "THIS WARNING SUPERSEDES AND CANCELS REF A, JOINT TYPHOON WRNCEN PEARL\n"
                   "HARBOR HI 291700Z SEP 26 TROPICAL CYCLONE FORMATION ALERT (WTPN21 PGTW\n"
                   "291700).\nAMP", 1)
        fetch = self.fetcher()

        def patched(source):
            if source.url == tcfa:
                return sources.Fetched(source, fixture("jtwc_wp9326.tcw"), "", False, "")
            if source.url.endswith("/wp2526.tcw"):
                return sources.Fetched(source, warning, "", False, "")
            return fetch(source)
        rss = fixture("jtwc.rss").replace(
            "<li><a href='https://www.metoc.navy.mil/jtwc/products/wp2526.tcw'",
            f"<li><a href='{tcfa}' target='newwin'>JMV 3.0 Data</a></li>\n"
            "<li><a href='https://www.metoc.navy.mil/jtwc/products/wp2526.tcw'")
        state = self.state(patched, jtwc_rss=rss, jtwc_abpw=fixture("jtwc_abpw_93w.txt"))
        self.assertEqual([s.name for s in state.others], ["Surigae"])
        self.assertEqual([a for a in state.alerts if not a.cancelled], [])
        [area] = [d for d in state.outlook if d.key == "93w"]
        self.assertEqual((area.area, area.formation), ((), None))

    def test_an_alert_that_gives_no_time_is_kept_and_said(self):
        # No WMO heading, so no issue time: the advisory read that run hid it.
        tcfa = "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw"
        fetch = self.fetcher()

        def patched(source):
            if source.url == tcfa:
                return sources.Fetched(source, fixture("jtwc_wp9326.tcw").replace(
                    "WTPN21 PGTW 291700\n", ""), "", False, "")
            return fetch(source)
        rss = fixture("jtwc.rss").replace(
            "<li><a href='https://www.metoc.navy.mil/jtwc/products/wp2526.tcw'",
            f"<li><a href='{tcfa}' target='newwin'>JMV 3.0 Data</a></li>\n"
            "<li><a href='https://www.metoc.navy.mil/jtwc/products/wp2526.tcw'")
        state = self.state(patched, jtwc_rss=rss)
        [area] = [d for d in state.outlook if d.key == "93w"]
        self.assertTrue(area.alert)
        self.assertEqual(len(area.area), 5)
        self.assertEqual([n for n in state.notes if "wp9326" in n],
                         ["JTWC wp9326.tcw: the formation alert gives no issue time; "
                          "it is kept as in effect."])

    def test_a_run_after_an_alert_s_time_raises_it_as_run_out(self):
        # The run's own time decides it: "CANCELLED BY 301700Z", read at 18:05Z.
        if not (CACHE / "oni.cache").exists():
            self.skipTest("no cached feeds; run `python track.py` once first")
        tcfa = "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw"
        fetch = self.fetcher()

        def patched(source):
            if source.url == tcfa:
                return sources.Fetched(source, fixture("jtwc_wp9326.tcw"), "", False, "")
            return fetch(source)
        rss = fixture("jtwc.rss").replace(
            "<li><a href='https://www.metoc.navy.mil/jtwc/products/wp2526.tcw'",
            f"<li><a href='{tcfa}' target='newwin'>JMV 3.0 Data</a></li>\n"
            "<li><a href='https://www.metoc.navy.mil/jtwc/products/wp2526.tcw'")
        storms = self.state(patched, jtwc_rss=rss, jtwc_abpw=fixture("jtwc_abpw_93w.txt"))
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cyclones, "build", return_value=storms), \
                mock.patch.object(storage, "now", return_value="2026-09-30T18:05:00+00:00"):
            state = pipeline.run(CACHE, Path(tmp) / "one.db", offline=True, leads=9)
        [raised] = [a for a in state.alert_set.alerts if a.code == "tc_formation_93w"]
        self.assertIn("formation alert ran to 2026-09-30 17:00 UTC", raised.detail)

    def test_a_first_warning_wrapped_at_its_alert_s_name_is_the_storm(self):
        # Its remarks wrapped so a line began "ALERT (WTPN21 ...)": the warning
        # was taken for a formation alert, and Surigae left the desk, the
        # dashboard and the report for the run.
        warning = fixture("jtwc_wp2526.tcw").replace(
            "AMP", "THIS WARNING SUPERSEDES AND CANCELS REF A, TROPICAL CYCLONE FORMATION\n"
                   "ALERT (WTPN21 PGTW 291700).\nAMP", 1)
        fetch = self.fetcher()

        def patched(source):
            if source.url.endswith("/wp2526.tcw"):
                return sources.Fetched(source, warning, "", False, "")
            return fetch(source)
        state = self.state(patched)
        self.assertEqual([s.name for s in state.others], ["Surigae"])
        self.assertEqual([a for a in state.alerts if not a.cancelled], [])

    def test_the_outlooks_are_merged(self):
        state = self.state()
        self.assertEqual([d.key for d in state.outlook], ["ep1", "cp1", "98w", "91p", "97w"])
        self.assertIn("Fri Sep 25", state.outlook_issued["AL"])
        self.assertEqual(state.outlook_issued["ABPW"], "2026-09-21T06:00:00Z")
        self.assertTrue(any("Indian Ocean" in note for note in state.notes))

    def test_only_invests_still_being_tracked_are_listed(self):
        state = self.state()
        self.assertEqual([s.key for s in state.invests], ["ep992026"])
        self.assertTrue(state.invests[0].invest)
        self.assertEqual(state.invests[0].name, "Invest 99E")
        self.assertNotIn(state.invests[0], state.active)

    def upgraded(self):
        """The fixtures' state with Invest 99E's deck ending on a numbered storm."""
        fetch = self.fetcher()
        deck = _deck([("2026092506", 0, "150N", "1540W", 30, 1004, "DB", "BEST", 34),
                      ("2026092512", 0, "160N", "1553W", 40, 1000, "TS", "BEST", 34)])

        def patched(source):
            if source.url == sources.deck_source("b", "ep992026").url:
                return sources.Fetched(source, deck, "", False, "")
            return fetch(source)
        return self.state(patched)

    def test_an_invest_that_became_a_storm_is_not_listed_as_an_invest(self):
        # On 25 September 2026 Invest 90L's deck stopped at 00Z on a 40 kt
        # tropical storm at 12.9N 22.0W, the same fix as Gonzalo's (AL07), whose
        # deck carried it on. Listed as an invest, it was "not yet a tropical
        # cyclone" beside the storm it already was.
        state = self.upgraded()
        self.assertEqual(state.invests, ())
        self.assertTrue(any(note.startswith("Invest 99E is now ") for note in state.upgrades),
                        state.upgrades)

    def test_an_upgrade_is_news_not_a_problem(self):
        # The notes are what went wrong: the run folds them into its warnings,
        # and any warning makes it a degraded run.
        state = self.upgraded()
        self.assertEqual([note for note in state.notes if " is now " in note], [])

    def test_an_upgrade_leaves_the_run_healthy_and_still_says_so(self):
        # On 25 September 2026 "Invest 90L is now Gonzalo (AL07)." made every
        # run degraded: latest.json said so, the report listed it under PARSE
        # WARNINGS, and a run with no serious alert exited 3.
        if not (CACHE / "oni.cache").exists():
            self.skipTest("no cached feeds; run `python track.py` once first")
        upgraded = self.upgraded()
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cyclones, "build", return_value=upgraded):
            state = pipeline.run(CACHE, Path(tmp) / "one.db", offline=True, leads=9)
        self.assertEqual([w for w in state.warnings if " is now " in w], [])
        text = "\n".join(report._section_cyclones(state))
        self.assertEqual(text.count("Invest 99E is now "), 1, text)
        [said] = dashboard.payload(state)["cyclones"]["upgrades"]
        self.assertTrue(said.startswith("Invest 99E is now "), said)
        self.assertIn(said, stormdesk.payload(state)["notes"])

    def test_a_protective_product_that_failed_degrades_the_run(self):
        # The index linked Nolo's watches and warnings and they did not come:
        # a failed feed like any other, so the run says it is degraded rather
        # than exiting as if everything had arrived.
        if not (CACHE / "oni.cache").exists():
            self.skipTest("no cached feeds; run `python track.py` once first")
        fetch = self.fetcher()

        def patched(source):
            if source.url == self.API + "EP152026_020adv_WW.kmz":
                return sources.Fetched(source, "", "", False, "",
                                       error="HTTP Error 503: Service Unavailable")
            return fetch(source)
        failed = self.state(patched)
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(cyclones, "build", return_value=failed):
            state = pipeline.run(CACHE, Path(tmp) / "one.db", offline=True, leads=9)
        said = [w for w in state.warnings if "Nolo" in w and "Watches and warnings" in w]
        self.assertEqual(len(said), 1, state.warnings)

    def test_an_unreadable_watches_file_is_unavailable_not_none(self):
        fetch = self.fetcher()

        def patched(source):
            if source.url == self.API + "EP152026_020adv_WW.kmz":
                return sources.Fetched(source, TestProtectiveProducts.ERROR_PAGE, "",
                                       False, "")
            return fetch(source)
        [nolo] = [s for s in self.state(patched).active if s.key == "ep152026"]
        self.assertIsNone(nolo.products.watches)
        self.assertIn("Watches and warnings could not be read", nolo.products.notes)
        self.assertEqual(stormdesk._status(nolo, "watches"), "unavailable")

    def test_an_unreadable_outlook_is_said_and_the_others_are_kept(self):
        state = cyclones.CycloneState()
        cyclones._outlooks({"nhc_outlook_at": fixture("gtwo_atl.kml"),
                            "nhc_outlook_ep": TestProtectiveProducts.ERROR_PAGE,
                            "nhc_outlook_cp": fixture("gtwo_cpac.kml"),
                            "jtwc_abpw": "<html><body>The server is busy</body></html>",
                            "jtwc_abio": fixture("jtwc_abpw.txt")}, state)
        self.assertIn("The formation outlook for the eastern North Pacific could not be read.",
                      state.notes)
        self.assertIn("The formation outlook for the west and south Pacific (JTWC) could not "
                      "be read.", state.notes)
        self.assertNotIn("EP", state.outlook_issued)
        self.assertIn("AL", state.outlook_issued)

    def live(self) -> str:
        """The index as it stood on 25 September 2026 at 21Z.

        Each product carries its own advisory number. CPHC's intermediate
        advisory 20A reissued Nolo's public advisory, watches and cone; its
        wind probabilities and surge were still 20's, which come with full
        advisories only. Polo's index was at 21 with its cone still at 20.
        """
        def link(field, url, number):
            return {"advNum": number, field: url}

        def storm(key, name, advisory, public, **products):
            return dict({
                "id": key, "name": name, "classification": "HU", "intensity": "75",
                "pressure": "980", "latitudeNumeric": 16.0, "longitudeNumeric": -155.5,
                "movementDir": 300, "movementSpeed": 9,
                "lastUpdate": "2026-09-25T21:00:00.000Z",
                "publicAdvisory": {"advNum": advisory, "url": self.TEXT + public},
            }, **products)
        return json.dumps({"activeStorms": [
            storm("ep152026", "Nolo", "020a", "HFOTCPCP2.shtml",
                  windWatchesWarnings=link("kmzFile", self.API + "EP152026_020Aadv_WW.kmz",
                                           "020a"),
                  trackCone=link("kmzFile", self.API + "EP152026_020Aadv_CONE.kmz", "020a"),
                  windSpeedProbabilities=link("url", self.TEXT + "HFOPWSCP2.shtml", "020"),
                  peakSurgeKML=link("peakSurgeKMLFile",
                                    self.API + "EP152026_PeakStormSurge_020adv.kml", "020")),
            storm("ep172026", "Polo", "021", "MIATCPEP2.shtml",
                  trackCone=link("kmzFile", self.API + "EP172026_020adv_CONE.kmz", "020")),
        ]})

    def live_state(self):
        fetch = self.fetcher()

        def reissued(text):
            # The same file as CPHC reissued it with advisory 20A.
            text = re.sub(r'(<Data name="advisoryNum">\s*<value>)20(</value>)',
                          r"\g<1>20A\2", text)
            return text.replace("(Advisory #20)", "(Advisory #20A)")
        pages = {
            self.API + "EP152026_020Aadv_WW.kmz": reissued(fixture("ww_ep152026.kml")),
            self.API + "EP152026_020Aadv_CONE.kmz": reissued(fixture("cone_ep152026.kml")),
            self.API + "EP172026_020adv_CONE.kmz": fixture("cone_ep152026.kml"),
            self.TEXT + "HFOTCPCP2.shtml": fixture("tcp_hfotcpcp2.shtml").replace(
                "Advisory Number  21", "Intermediate Advisory Number  20A"),
        }

        def patched(source):
            if source.url in pages:
                return sources.Fetched(source, pages[source.url], "", False, "")
            return fetch(source)
        return self.state(patched, current=self.live())

    def test_an_intermediate_advisory_is_numbered_as_the_products_number_it(self):
        # The index writes CPHC's intermediate advisory "020a"; the products,
        # and the public advisory, write it 20A.
        self.assertEqual(cyclones._advisory_number("020a"), "20A")
        self.assertEqual(cyclones._advisory_number("020"), "20")
        self.assertEqual(cyclones._advisory_number(""), "")

    def test_a_product_is_older_only_once_a_later_advisory_would_have_reissued_it(self):
        older = cyclones._older
        self.assertFalse(older("winds", "20", "20A"))
        self.assertFalse(older("surge", "20", "20A"))
        self.assertTrue(older("watches", "20", "20A"))
        self.assertTrue(older("cone", "20A", "21"))
        self.assertTrue(older("winds", "20", "21"))
        self.assertFalse(older("watches", "21", "20A"))
        self.assertFalse(older("watches", "", "20"))

    def test_each_product_carries_its_own_advisory(self):
        nolo = self.storm(self.live_state(), "ep152026")
        self.assertEqual(nolo.products.advisory, "20A")
        self.assertEqual({kind: nolo.products.own(kind)
                          for kind in ("watches", "cone", "surge", "winds")},
                         {"watches": "20A", "cone": "20A", "surge": "20", "winds": "20"})

    def test_an_intermediate_advisory_leaves_the_last_full_ones_products_current(self):
        # At 20A the wind probabilities and surge were still 20's, the latest
        # issued. Every one of Nolo's four products was said to be "from an
        # older advisory": 20A against 20a, and 20 against 20a.
        nolo = self.storm(self.live_state(), "ep152026")
        self.assertEqual([note for note in nolo.products.notes if "advisory" in note], [])
        self.assertNotIn("lagnote", stormdesk._protect_pane(stormdesk.storm_entry(nolo)))

    def test_a_product_a_full_advisory_behind_says_so(self):
        polo = self.storm(self.live_state(), "ep172026")
        self.assertIn("Forecast cone is from advisory 20; the current advisory is 21",
                      polo.products.notes)
        entry = stormdesk.storm_entry(polo)
        self.assertEqual((entry.get("product_advisories") or {}).get("cone"), "20")
        self.assertIn("The forecast cone is from advisory 20; the current advisory is 21.",
                      stormdesk._protect_pane(entry))

    def test_cphc_is_credited_with_what_cphc_issued(self):
        # Nolo crossed 140W as EP15 and CPHC writes its advisories now: its
        # public advisory is HFOTCPCP2. The alerts credited them to NHC.
        state = self.live_state()
        nolo = self.storm(state, "ep152026")
        self.assertEqual(nolo.centre, "CPHC")
        details = [a.detail for a in alerts.product_rules(state) if "ep152026" in a.code]
        self.assertTrue(details)
        for detail in details:
            self.assertTrue(detail.startswith("CPHC advisory 20A: "), detail)
        self.assertIn("Protective products, CPHC advisory 20A:",
                      "\n".join(report._protective(nolo)))

    def test_the_public_advisory_is_read_with_the_other_products(self):
        state = self.state()
        nolo = self.storm(state, "ep152026")
        self.assertEqual(nolo.products.in_effect, (
            ("Hurricane Watch", ("Hawaii County",)),
            ("Tropical Storm Warning", ("Hawaii County",)),
            ("Tropical Storm Watch", ("Maui County",))))
        self.assertEqual(nolo.products.own("in_effect"), "20")
        self.assertEqual(self.storm(state, "ep172026").products.in_effect, ())

    def test_a_warned_coast_is_named_in_the_centres_own_words(self):
        # On 25 September 2026 CPHC had a Hurricane Watch up for Hawaii County
        # and a Tropical Storm Watch for Maui County. Named from the lines, the
        # first was "near Kailua-Kona", without Hilo, and the second ran "from
        # Wailuku to Honolulu", which was under nothing.
        state = self.live_state()
        nolo = self.storm(state, "ep152026")
        said = {a.code: a.detail for a in alerts.product_rules(state) if "ep152026" in a.code}
        self.assertIn("is in effect for Hawaii County.", said["tc_ww_ep152026_hurricane_watch"])
        self.assertIn("is in effect for Maui County.",
                      said["tc_ww_ep152026_tropical_storm_watch"])
        text = "\n".join(report._protective(nolo))
        self.assertRegex(text, r"Hurricane Watch\s+Hawaii County")
        self.assertRegex(text, r"Tropical Storm Watch\s+Maui County")
        pane = stormdesk._watches(stormdesk.storm_entry(nolo))
        self.assertIn("<b>Tropical Storm Watch</b> Maui County.", pane)
        for words in [*said.values(), text, pane]:
            self.assertNotIn("Honolulu", words)

    def test_without_the_public_advisory_the_lines_name_the_coast(self):
        # The public advisory did not come: the watch round the Big Island is
        # named by the towns along it, Hilo among them, and the one round
        # Maui County by the town near it, not by Honolulu.
        fetch = self.fetcher()

        def patched(source):
            if source.url == self.TEXT + "HFOTCPCP2.shtml":
                return sources.Fetched(source, "", "", False, "",
                                       error="HTTP Error 503: Service Unavailable")
            return fetch(source)
        state = self.state(patched)
        nolo = self.storm(state, "ep152026")
        self.assertIsNone(nolo.products.in_effect)
        self.assertIn("Public advisory", nolo.products.unavailable)
        said = {a.code: a.detail for a in alerts.product_rules(state) if "ep152026" in a.code}
        self.assertIn("Hilo", said["tc_ww_ep152026_hurricane_watch"])
        self.assertIn("Wailuku", said["tc_ww_ep152026_tropical_storm_watch"])
        self.assertNotIn("Honolulu", said["tc_ww_ep152026_tropical_storm_watch"])

    def test_the_public_advisory_names_what_the_lines_could_not_show(self):
        # The watches file failed and the public advisory came: what it says
        # is in effect is listed and alerted on, and the lost lines are said.
        fetch = self.fetcher()

        def patched(source):
            if source.url == self.API + "EP152026_020adv_WW.kmz":
                return sources.Fetched(source, "", "", False, "",
                                       error="HTTP Error 503: Service Unavailable")
            return fetch(source)
        state = self.state(patched)
        nolo = self.storm(state, "ep152026")
        self.assertIsNone(nolo.products.watches)
        self.assertIn("tc_ww_ep152026_hurricane_watch",
                      {a.code for a in alerts.product_rules(state)})
        text = "\n".join(report._protective(nolo))
        self.assertRegex(text, r"Hurricane Watch\s+Hawaii County")
        self.assertIn("could not be fetched", text)
        pane = stormdesk._watches(stormdesk.storm_entry(nolo))
        self.assertIn("<b>Hurricane Watch</b> Hawaii County.", pane)
        self.assertIn("could not be fetched", pane)

    def test_the_eastern_track_map_leaves_jtwc_storms_to_the_storm_desk(self):
        state = self.state()
        card = storms.tracks_card(SimpleNamespace(cyclones=state))
        drawn = card.split("<svg", 1)[1].split("</svg>", 1)[0]
        self.assertNotIn("Surigae", drawn)
        self.assertIn("Surigae", card)
        self.assertIn("JTWC", card)


class TestProductAlerts(unittest.TestCase):
    """Official watches, warnings and formation chances raise alerts of their own."""

    # From Hilo round to Kailua-Kona, the Big Island's east and south coasts.
    COAST = ((-155.08, 19.70), (-155.60, 18.95), (-155.99, 19.64))

    def state(self, kinds=(), outlook=(), stage="HU", wind=75, centre="NHC"):
        segments = tuple(tcproducts.WarningSegment(kind, self.COAST) for kind in kinds)
        fix = cyclones.Fix(stamp="2026092512", tau=0, lat=16.0, lon=-155.5, wind=wind,
                           pressure=980, stage=stage, tech="BEST")
        storm = cyclones.Storm(
            basin="EP", number=15, year=2026, name="Nolo", track=(fix,),
            advisory={"advisory": "020"}, centre=centre,
            products=tcproducts.Products(watches=segments, advisory="20"))
        season = cyclones.BasinSeason(basin="EP", storms=(storm,))
        return cyclones.CycloneState(basins={"EP": season}, outlook=list(outlook))

    def levels(self, state) -> dict:
        return {a.code: a.level for a in alerts.product_rules(state)}

    def test_each_watch_and_warning_raises_its_own_level(self):
        found = self.levels(self.state(kinds=tcproducts.WW_ORDER))
        self.assertEqual(found["tc_ww_ep152026_hurricane_warning"], alerts.CRITICAL)
        self.assertEqual(found["tc_ww_ep152026_hurricane_watch"], alerts.WARNING)
        self.assertEqual(found["tc_ww_ep152026_tropical_storm_warning"], alerts.WARNING)
        self.assertEqual(found["tc_ww_ep152026_tropical_storm_watch"], alerts.WATCH)

    def test_the_detail_names_the_coast_and_the_advisory(self):
        [alert] = alerts.product_rules(self.state(kinds=("Hurricane Watch",)))
        self.assertIn("Hilo", alert.detail)
        self.assertIn("Kailua-Kona", alert.detail)
        self.assertIn("advisory 20", alert.detail)
        self.assertIn("Hurricane Watch", alert.title)

    def test_the_detail_gives_the_centre_and_advisory_the_watches_came_with(self):
        state = self.state(kinds=("Hurricane Watch",))
        storm = state.basins["EP"].storms[0]
        storm.advisory = {"advisory": "021",
                          "public": "https://www.nhc.noaa.gov/text/HFOTCPCP2.shtml"}
        storm.products = dataclasses.replace(storm.products, advisory="21",
                                             advisories=(("watches", "20"),))
        [alert] = alerts.product_rules(state)
        self.assertTrue(alert.detail.startswith("CPHC advisory 20: "), alert.detail)

    def test_a_line_round_an_island_that_does_not_quite_close_is_named_round_it(self):
        # CPHC's line round the Big Island ends 6 km from where it starts.
        # Named as a stretch from one end to the other it was "near
        # Kailua-Kona": both ends are on the Kona coast.
        [watch] = [s for s in tcproducts.watches_warnings(fixture("ww_ep152026.kml"))
                   if s.kind == "Hurricane Watch"]
        self.assertIn("Hilo", alerts._coast([watch]))

    def test_a_stretch_is_not_named_after_a_town_across_the_water(self):
        # Molokai's line ends 48 km from Honolulu, on another island, which
        # was under nothing.
        segments = [s for s in tcproducts.watches_warnings(fixture("ww_ep152026.kml"))
                    if s.kind == "Tropical Storm Watch"]
        self.assertNotIn("Honolulu", "; ".join(alerts._coasts(segments)))
        self.assertNotIn("Honolulu", alerts._coast(segments))

    def test_a_short_stretch_is_not_taken_for_an_island(self):
        short = tcproducts.WarningSegment("Hurricane Watch",
                                          ((-155.08, 19.70), (-155.05, 19.55)))
        self.assertEqual(alerts._coast([short]), "near Hilo")

    def test_an_island_watch_names_the_towns_round_its_coast(self):
        # Round an island the segment is a closed loop: its two ends are the
        # same point, and "from Kailua-Kona to Kailua-Kona" names one town.
        loop = ((-155.08, 19.70), (-155.60, 18.95), (-155.99, 19.64),
                (-155.85, 20.20), (-155.08, 19.70))
        state = self.state()
        storm = state.basins["EP"].storms[0]
        storm.products = tcproducts.Products(
            watches=(tcproducts.WarningSegment("Hurricane Watch", loop),), advisory="20")
        [alert] = alerts.product_rules(state)
        self.assertIn("Hilo", alert.detail)
        self.assertIn("Kailua-Kona", alert.detail)
        self.assertNotIn(" from ", alert.detail)

    def test_the_formation_detail_does_not_repeat_the_heading(self):
        area = outlook.Disturbance(
            centre="NHC", basin="EP", label="South of Mexico", lon=-100.0, lat=12.0,
            chance_2day=40, chance_7day=90, potential="high",
            text="1. South of Mexico: A low is expected to form.", area=(), arrow=(),
            alert=False, issued="Fri Sep 25 11:40:21 2026", key="ep1")
        [alert] = alerts.product_rules(self.state(outlook=[area]))
        self.assertIn("A low is expected to form.", alert.detail)
        self.assertNotIn("1. South of Mexico:", alert.detail)

    def test_a_long_alert_title_wraps_inside_the_report(self):
        long = alerts.Alert(
            code="tc_formation_cp1", level=alerts.WATCH,
            title=("Well East-Southeast of the Hawaiian Islands: 90% chance of a "
                   "tropical cyclone within 7 days"),
            detail="x", is_new=True)
        lines = report._section_alerts(SimpleNamespace(
            alert_set=alerts.AlertSet(alerts=[long])))
        self.assertTrue(all(len(line) <= report.WIDTH for line in lines), lines)
        self.assertIn("NEW", "".join(lines))

    def test_the_eastern_track_map_never_draws_a_jtwc_storm(self):
        nhc = self.state().basins["EP"].storms[0]
        typhoon = jtwc.parse_tcw(fixture("jtwc_wp2526.tcw"))
        drawn = storms.track_map([nhc, typhoon])
        self.assertIn("Nolo", drawn)
        self.assertNotIn("Surigae", drawn)

    def test_no_watches_no_alerts(self):
        self.assertEqual(alerts.product_rules(self.state()), [])

    def test_formation_chances_raise_a_watch_when_high(self):
        def area(key, centre, chance, potential):
            return outlook.Disturbance(
                centre=centre, basin="EP", label=f"Area {key}", lon=-100.0, lat=12.0,
                chance_2day=None if chance is None else chance // 2, chance_7day=chance,
                potential=potential, text="", area=(), arrow=(), alert=False,
                issued="Fri Sep 25 11:40:21 2026", key=key)
        state = self.state(outlook=[area("ep1", "NHC", 90, "high"),
                                    area("ep2", "NHC", 50, "medium"),
                                    area("98w", "JTWC", None, "high"),
                                    area("91p", "JTWC", None, "medium")])
        found = self.levels(state)
        self.assertEqual(found.get("tc_formation_ep1"), alerts.WATCH)
        self.assertNotIn("tc_formation_ep2", found)
        self.assertEqual(found.get("tc_formation_98w"), alerts.WATCH)
        self.assertNotIn("tc_formation_91p", found)

    def test_a_formation_alert_s_detail_says_until_when(self):
        alert = jtwc.formation_alert(fixture("jtwc_wp9326.tcw"),
                                     "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw")
        [[area]] = jtwc.alerted([jtwc.disturbances(fixture("jtwc_abpw_93w.txt"))], [alert], {})
        [raised] = alerts.product_rules(self.state(outlook=[area]))
        self.assertEqual(raised.code, "tc_formation_93w")
        self.assertIn("A tropical cyclone formation alert is in effect until "
                      "2026-09-30 17:00 UTC: moving west-northwest at 14 kt, winds 18 to "
                      "23 kt, pressure near 1005 mb.", raised.detail)

    def test_a_formation_alert_past_its_time_is_said_to_have_run_out(self):
        # Past "CANCELLED BY 301700Z", with nothing newer read, the detail
        # still said the alert was in effect.
        alert = jtwc.formation_alert(fixture("jtwc_wp9326.tcw"),
                                     "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw")
        [[area]] = jtwc.alerted([jtwc.disturbances(fixture("jtwc_abpw_93w.txt"))], [alert], {})
        state = self.state(outlook=[area])
        [before] = alerts.product_rules(state, now="2026-09-30T16:59:00+00:00")
        self.assertIn("is in effect until 2026-09-30 17:00 UTC", before.detail)
        [after] = alerts.product_rules(state, now="2026-09-30T18:05:00+00:00")
        self.assertNotIn("in effect", after.detail)
        self.assertIn("JTWC's formation alert ran to 2026-09-30 17:00 UTC, the time it was "
                      "to be reissued, upgraded to a warning or cancelled by, and nothing "
                      "newer from JTWC has been read. It said: moving west-northwest at "
                      "14 kt, winds 18 to 23 kt, pressure near 1005 mb.", after.detail)
        self.assertEqual((after.code, after.level), ("tc_formation_93w", alerts.WATCH))
        raised = {a.code: a for a in alerts.evaluate(assess(*_fixture_inputs()), storms=state,
                                                      now="2026-09-30T18:05:00+00:00")}
        self.assertIn("ran to", raised["tc_formation_93w"].detail)

    def test_the_evaluation_includes_the_product_rules(self):
        state = self.state(kinds=("Hurricane Warning",))
        raised = {a.code for a in alerts.evaluate(assess(*_fixture_inputs()), storms=state)}
        self.assertIn("tc_ww_ep152026_hurricane_warning", raised)

    def test_a_typhoon_is_not_called_a_hurricane(self):
        state = self.state(stage="TY", wind=100, centre="JTWC")
        [major] = [a for a in alerts.cyclone_rules(state) if a.code.startswith("tc_major")]
        self.assertIn("major typhoon", major.title)
        self.assertNotIn("hurricane", major.title)


class _DeskFixtures:
    """Storms for the storm desk's tests: Polo, Surigae (JTWC) and Iona (on 180)."""

    PUBLIC = "https://www.nhc.noaa.gov/text/MIATCPEP2.shtml"
    RADII = ((34, (130, 110, 90, 120)), (50, (60, 50, 40, 50)), (64, (35, 30, 25, 30)))

    @staticmethod
    def fix(stamp, tau, lat, lon, wind, stage="HU", tech="BEST", radii=(),
            pressure=None, rmw=None, eye=None):
        return cyclones.Fix(stamp=stamp, tau=tau, lat=lat, lon=lon, wind=wind,
                            pressure=pressure, stage=stage, tech=tech, rmw=rmw,
                            eye=eye, radii=radii)

    def polo(self, products=None, links=None):
        track = (self.fix("2026092500", 0, 17.0, -107.0, 150, pressure=905),
                 self.fix("2026092506", 0, 17.1, -107.6, 155, pressure=900),
                 self.fix("2026092512", 0, 17.1, -108.2, 155, pressure=900,
                          radii=self.RADII, rmw=8, eye=10))
        forecast = tuple(
            self.fix("2026092512", tau, lat, lon, wind, tech="OFCL", radii=self.RADII)
            for tau, lat, lon, wind in ((3, 17.1, -108.5, 155), (12, 17.2, -109.8, 155),
                                        (24, 17.8, -111.5, 140), (120, 22.0, -118.0, 60)))
        cone = ((-108.5, 17.1), (-111.0, 19.5), (-118.5, 24.5), (-119.0, 20.0),
                (-108.5, 17.1))
        advisory = {
            "advisory": "020", "public": self.PUBLIC,
            "discussion": "https://www.nhc.noaa.gov/text/MIATCDEP2.shtml",
            "graphics": "https://www.nhc.noaa.gov/graphics_ep2.shtml",
            "last_update": "2026-09-25T15:00:00.000Z",
            "movement_dir": 270, "movement_kt": 10, "movement_mph": 12,
            "wind": 155, "pressure": 900, "lat": 17.1, "lon": -108.5,
            "products": links if links is not None else {
                "watches": "", "cone": "https://example.invalid/cone.kmz",
                "surge": "", "winds": ""},
        }
        if products is None:
            products = tcproducts.Products(watches=(), cone=cone, surge=(), winds=None,
                                           advisory="20")
        return cyclones.Storm(basin="EP", number=17, year=2026, name="Polo",
                              track=track, forecast=forecast, advisory=advisory,
                              products=products)

    def surigae(self):
        return cyclones.Storm(
            basin="WP", number=25, year=2026, name="Surigae", centre="JTWC",
            track=(self.fix("2026092506", 0, 20.8, 128.9, 45, "TS", "JTWC"),
                   self.fix("2026092512", 0, 21.4, 128.2, 50, "TS", "JTWC",
                            pressure=998)),
            forecast=(self.fix("2026092512", 12, 22.5, 127.2, 60, "TS", "JTWC"),
                      self.fix("2026092512", 24, 23.6, 127.0, 70, "TY", "JTWC")),
            advisory={
                "advisory": "12",
                "public": "https://www.metoc.navy.mil/jtwc/products/wp2526web.txt",
                "discussion": "https://www.metoc.navy.mil/jtwc/products/wp2526prog.txt",
                "last_update": "2026-09-25T15:00:00Z",
                "movement_dir": 315, "movement_kt": 12})

    def iona(self):
        # West-bound across the date line: 179.4W now, 179.2E at +12 h.
        return cyclones.Storm(
            basin="CP", number=3, year=2026, name="Iona",
            track=(self.fix("2026092506", 0, 15.0, -178.0, 90),
                   self.fix("2026092512", 0, 15.5, -179.4, 95)),
            forecast=tuple(
                self.fix("2026092512", tau, lat, lon, 95, tech="OFCL")
                for tau, lat, lon in ((12, 16.2, 179.2), (24, 17.0, 177.5),
                                      (48, 19.0, 174.0))),
            advisory={"advisory": "015",
                      "public": "https://www.nhc.noaa.gov/text/HFOTCPCP3.shtml",
                      "last_update": "2026-09-25T15:00:00.000Z"})

    WW = "https://www.nhc.noaa.gov/storm_graphics/api/EP152026_020adv_WW.kmz"

    def nolo(self):
        """Polo's track under Nolo's name, with every protective product issued."""
        products = tcproducts.Products(
            watches=(tcproducts.WarningSegment("Hurricane Watch",
                                               ((-110.2, 19.0), (-109.6, 18.6))),
                     tcproducts.WarningSegment("Tropical Storm Warning",
                                               ((-109.6, 18.6), (-109.3, 18.9)))),
            cone=((-108.5, 17.1), (-111.0, 19.5), (-118.5, 24.5), (-108.5, 17.1)),
            surge=(tcproducts.SurgeArea("Isla Socorro", "1-3 ft",
                                        ((-110.9, 18.7), (-110.8, 18.8),
                                         (-110.9, 18.9), (-110.9, 18.7))),),
            winds=tcproducts.WindTable(
                issued="1500 UTC FRI SEP 25 2026", advisory="20",
                hours=(12, 24, 36, 48, 72, 96, 120),
                rows=(tcproducts.WindProbability("ISLA SOCORRO", 34, (2, 9, 30, 44, 51, 52, 52)),
                      tcproducts.WindProbability("ISLA SOCORRO", 50, (0, 3, 11, 19, 22, 22, 22)),
                      tcproducts.WindProbability("ISLA SOCORRO", 64, (0, 0, 4, 8, 9, 9, 9)))),
            advisory="20")
        storm = self.polo(products=products, links={
            "watches": self.WW, "cone": "https://example.invalid/cone.kmz",
            "surge": "https://example.invalid/surge.kml",
            "winds": "https://www.nhc.noaa.gov/text/MIAPWSEP2.shtml"})
        storm.number, storm.name = 15, "Nolo"
        return storm

    @staticmethod
    def warned(storm, kind, *lines):
        """The storm with only these stretches of one watch or warning in effect."""
        storm.products = dataclasses.replace(storm.products, watches=tuple(
            tcproducts.WarningSegment(kind, line) for line in lines))
        return storm

    def state(self, *storms, outlook=(), invests=()):
        nhc = tuple(s for s in storms if s.centre != "JTWC")
        return SimpleNamespace(
            run_at="2026-09-25T16:04:00+00:00",
            cyclones=cyclones.CycloneState(
                basins={"EP": cyclones.BasinSeason(basin="EP", storms=nhc)},
                others=tuple(s for s in storms if s.centre == "JTWC"),
                as_of="2026-09-25T15:00", outlook=list(outlook),
                outlook_issued={"EP": "Fri Sep 25 11:40:21 2026"},
                invests=tuple(invests)))

    def storms(self, *storms) -> dict:
        return {s["id"]: s for s in stormdesk.payload(self.state(*storms))["storms"]}


class TestStormDeskPayload(_DeskFixtures, unittest.TestCase):
    """storms.json: what the storm desk is drawn from."""

    def test_the_payload_survives_a_json_round_trip(self):
        data = stormdesk.payload(self.state(self.polo(), self.surigae(), self.iona()))
        self.assertEqual(data["schema"], 1)
        self.assertEqual(json.loads(json.dumps(data)), data)
        self.assertEqual(len(data["storms"]), 3)

    def test_the_methods_say_which_frame_is_shown(self):
        # GIBS lists a frame before its tiles exist; the page shows the frame
        # before it, and says so.
        methods = stormdesk.payload(self.state(self.polo()))["methods"]
        self.assertIn("frames", methods)
        self.assertIn("before its tiles", methods["frames"])

    def test_a_path_runs_forward_in_time_to_the_last_forecast_point(self):
        polo = self.storms(self.polo())["ep172026"]
        times = [point["t"] for point in polo["path"]]
        self.assertEqual(times, sorted(set(times)))
        self.assertEqual(times[0], "2026-09-25T00:00:00Z")
        last, end = polo["forecast"][-1], polo["path"][-1]
        self.assertEqual((end["t"], end["lon"], end["lat"]),
                         (last["t"], last["lon"], last["lat"]))
        self.assertEqual(last["t"], "2026-09-30T12:00:00Z")

    def test_a_storm_crossing_the_date_line_stays_continuous(self):
        iona = self.storms(self.iona())["cp032026"]
        for key in ("track", "forecast", "path"):
            lons = [point["lon"] for point in iona[key]]
            for a, b in zip(lons, lons[1:]):
                self.assertLess(abs(b - a), 180.0, key)
        # One frame for the whole storm: the forecast carries on from the
        # track rather than jumping to the other side of the map.
        self.assertLess(abs(iona["forecast"][0]["lon"] - iona["track"][-1]["lon"]), 5.0)
        self.assertAlmostEqual(iona["forecast"][0]["lon"], -180.8, places=2)

    def test_polo_is_seen_best_from_goes_west(self):
        view = self.storms(self.polo())["ep172026"]["view"]
        self.assertEqual(view["satellite"], "GOES-West")
        self.assertAlmostEqual(view["zenith"], 38.0, delta=1.0)
        # Cloud tops lean away from the sub-satellite point, south-west of Polo.
        lon, lat = view["parallax"]
        self.assertGreater(lon, -108.2)
        self.assertGreater(lat, 17.1)
        self.assertAlmostEqual(view["offset_km"], 15 * math.tan(math.radians(view["zenith"])),
                               delta=0.2)

    def test_links_carry_the_advisory_and_the_responsible_centre(self):
        found = self.storms(self.polo(), self.surigae(), self.iona())
        polo, surigae, iona = found["ep172026"], found["wp252026"], found["cp032026"]
        self.assertEqual(polo["links"]["advisory"], self.PUBLIC)
        self.assertEqual(polo["links"]["centre"]["name"], "NHC")
        self.assertTrue(polo["links"]["centre"]["url"].startswith("https://www.nhc.noaa.gov"))
        self.assertEqual(iona["centre"], "CPHC")
        # JTWC warns for United States forces; the public warnings in the west
        # Pacific are the Japan Meteorological Agency's, as RSMC Tokyo.
        self.assertEqual(surigae["links"]["centre"]["name"], "JTWC")
        self.assertIn("RSMC Tokyo", " ".join(c["name"] for c in surigae["links"]["responsible"]))

    def test_a_storm_west_of_140w_is_cphcs(self):
        # Nolo kept its east Pacific number after crossing 140W, and from
        # there its advisories came from Honolulu (HFOTCPCP2), not Miami.
        nolo = self.polo()
        nolo.number, nolo.name = 15, "Nolo"
        nolo.advisory = dict(nolo.advisory,
                             public="https://www.nhc.noaa.gov/text/HFOTCPCP2.shtml")
        nolo.track = tuple(cyclones.Fix(**dict(vars(f), lon=f.lon - 47.0))
                           for f in nolo.track)
        shown = self.storms(nolo)["ep152026"]
        self.assertEqual(shown["centre"], "CPHC")
        self.assertEqual(shown["links"]["centre"]["name"], "CPHC")
        self.assertEqual(shown["links"]["responsible"][0]["name"], "CPHC (RSMC Honolulu)")

    def test_the_advisory_carries_its_own_fix(self):
        # The 15Z advisory is newer than the 12Z best track and can differ
        # from it: Polo was 908 mb in the deck and 900 mb in the advisory.
        found = self.storms(self.polo(), self.surigae())
        self.assertEqual(found["ep172026"]["advisory_fix"],
                         {"t": "2026-09-25T15:00:00Z", "lat": 17.1, "lon": -108.5,
                          "wind": 155, "pressure": 900})
        self.assertIsNone(found["wp252026"]["advisory_fix"])

    def test_every_time_is_iso_utc(self):
        found = self.storms(self.polo(), self.surigae(), self.iona())
        for storm in found.values():
            self.assertRegex(storm["issued"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$")
            for point in storm["track"] + storm["forecast"] + storm["path"]:
                datetime.strptime(point["t"], "%Y-%m-%dT%H:%M:%SZ")
        self.assertEqual(found["ep172026"]["forecast"][1]["t"], "2026-09-26T00:00:00Z")
        self.assertEqual(found["ep172026"]["issued"], "2026-09-25T15:00:00Z")

    def test_a_jtwc_storm_has_no_cone_and_says_why(self):
        surigae = self.storms(self.surigae())["wp252026"]
        self.assertEqual(surigae["centre"], "JTWC")
        self.assertIsNone(surigae["cone"])
        self.assertEqual(surigae["products"]["cone"], "not published")
        self.assertEqual(surigae["label"], "tropical storm")

    def test_none_in_effect_is_not_the_same_as_unavailable(self):
        # The index links no watches for Polo: none are in effect. For the
        # second copy it links them and the fetch failed.
        calm = self.storms(self.polo())["ep172026"]
        self.assertEqual(calm["watches"], [])
        self.assertEqual(calm["products"]["watches"], "none")
        self.assertEqual(calm["products"]["cone"], "issued")
        failed = self.polo(
            products=tcproducts.Products(watches=None, cone=(), surge=(), winds=None,
                                         advisory="20",
                                         notes=("Watches and warnings unavailable (timeout)",)),
            links={"watches": "https://example.invalid/ww.kmz", "cone": "", "surge": "",
                   "winds": ""})
        broken = self.storms(failed)["ep172026"]
        self.assertIsNone(broken["watches"])
        self.assertEqual(broken["products"]["watches"], "unavailable")
        self.assertIn("Watches and warnings unavailable (timeout)", broken["notes"])

    def test_actions_for_people_and_animals_carry_their_sources(self):
        actions = stormdesk.payload(self.state())["actions"]
        for group in ("people", "animals"):
            self.assertGreaterEqual(len(actions[group]), 3, group)
            for action in actions[group]:
                self.assertTrue(action["text"].strip())
                self.assertRegex(action["source"], r"^https://www\.ready\.gov/")

    def test_exposure_is_listed_with_iso_arrival_times(self):
        town = atlasdata.Place("Isla Socorro", "Mexico", "Colima", 250,
                                -110.0, 17.5, False)
        with mock.patch.object(atlasdata, "PLACES", (town,)):
            [row] = self.storms(self.polo())["ep172026"]["exposure"]
        self.assertEqual(row["place"], "Isla Socorro")
        self.assertRegex(row["arrival"]["34"], r"^2026-09-2\dT\d\d:00:00Z$")
        self.assertIsInstance(row["unknown"], list)

    def test_outlook_areas_and_invests_are_carried(self):
        area = outlook.Disturbance(
            centre="NHC", basin="EP", label="Southwest of Mexico", lon=-102.0, lat=12.0,
            chance_2day=40, chance_7day=90, potential="high", text="Showers...",
            area=((-104.0, 10.0), (-100.0, 10.0), (-100.0, 14.0), (-104.0, 10.0)),
            arrow=(), alert=False, issued="Fri Sep 25 11:40:21 2026", key="ep1")
        invest = cyclones.Storm(basin="AL", number=90, year=2026, name="Invest 90L",
                                track=(self.fix("2026092512", 0, 12.0, -40.0, 25, "DB"),),
                                invest=True)
        data = stormdesk.payload(self.state(outlook=[area], invests=[invest]))
        [shown] = data["outlook"]
        self.assertEqual((shown["key"], shown["chance_2day"], shown["chance_7day"]),
                         ("ep1", 40, 90))
        self.assertEqual(shown["area"][0], [-104.0, 10.0])
        self.assertEqual(data["outlook_issued"]["EP"], "Fri Sep 25 11:40:21 2026")
        [inv] = data["invests"]
        self.assertEqual((inv["name"], inv["lat"], inv["lon"]), ("Invest 90L", 12.0, -40.0))

    def alerted_area(self):
        """JTWC's ABPW10 of 29 September 2026 17Z with its formation alert laid on."""
        alert = jtwc.formation_alert(fixture("jtwc_wp9326.tcw"),
                                     "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw")
        [[area]] = jtwc.alerted([jtwc.disturbances(fixture("jtwc_abpw_93w.txt"))], [alert], {})
        return area

    def test_a_formation_alert_is_carried_with_its_box_and_facts(self):
        [shown] = stormdesk.payload(self.state(outlook=[self.alerted_area()]))["outlook"]
        self.assertTrue(shown["alert"])
        self.assertEqual(len(shown["area"]), 5)
        self.assertEqual(shown["formation"], {
            "issued": "2026-09-29T17:00:00Z", "until": "2026-09-30T17:00:00Z",
            "motion": "west-northwest at 14 kt", "wind": [18, 23], "pressure": 1005})
        json.dumps(shown)
        plain = dataclasses.replace(self.alerted_area(), formation=None)
        self.assertIsNone(stormdesk._area(plain)["formation"])

    def test_the_outlook_row_says_until_when_and_what_the_system_is_doing(self):
        html = stormdesk._outlook_section(
            stormdesk.payload(self.state(outlook=[self.alerted_area()])))
        text = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
        self.assertIn("high potential within 24 h · formation alert until "
                      "30 Sep 17:00 UTC", text)
        self.assertIn("18 to 23 kt · 1005 mb · moving west-northwest at 14 kt", text)
        still = dataclasses.replace(self.alerted_area(), formation=dataclasses.replace(
            self.alerted_area().formation, motion="quasi-stationary"))
        html = stormdesk._outlook_section(stormdesk.payload(self.state(outlook=[still])))
        text = " ".join(unescape(re.sub(r"<[^>]+>", " ", html)).split())
        self.assertIn("1005 mb · quasi-stationary", text)

    def test_the_outlook_row_says_when_an_alert_ran_out(self):
        # Past its time, with nothing newer read, the row still said "until";
        # the page rewords it when the time passes while it is open.
        state = self.state(outlook=[self.alerted_area()])
        self.assertIn('<span data-until="2026-09-30T17:00:00Z">formation alert until '
                      '30 Sep 17:00 UTC</span>',
                      stormdesk._outlook_section(stormdesk.payload(state)))
        state.run_at = "2026-09-30T18:05:00+00:00"
        self.assertIn('<span data-until="2026-09-30T17:00:00Z">formation alert ran to '
                      '30 Sep 17:00 UTC; nothing newer read</span>',
                      stormdesk._outlook_section(stormdesk.payload(state)))

    def test_the_map_and_here_name_the_formation_alert(self):
        # Each words it as alertWords does, which knows when it ran out, and
        # the map draws a box that ran out faded and dashed.
        js = stormdesk._JS
        self.assertIn("alertWords(a.formation && a.formation.until, true)",
                      _js_function(js, "drawMarks"))
        self.assertIn('", " + alertHtml(a.until)', _js_function(js, "showHere"))
        self.assertIn('"formation alert area "', _js_function(js, "showHere"))
        self.assertIn("lapsed(a.formation.until)", _js_function(js, "buildGeo"))
        self.assertRegex(stormdesk.page(self.state()),
                         r"#overlay \.area\.lapsed \{[^}]*stroke-dasharray")

    def test_imagery_layers_name_real_gibs_layers(self):
        data = stormdesk.payload(self.state())
        pattern = r"^(GOES-East_ABI|GOES-West_ABI|Himawari_AHI)_\w+$"
        ids = [layer["id"] for layer in data["layers"]]
        self.assertEqual(ids[:4], ["geocolor", "visible", "infrared", "airmass"])
        for layer in data["layers"]:
            self.assertEqual(layer["tms"], f"GoogleMapsCompatible_Level{layer['zoom']}")
            for name in (layer.get("satellites") or {}).values():
                if name is not None:
                    self.assertRegex(name, pattern)
        self.assertEqual([s["name"] for s in data["satellites"]],
                         ["GOES-East", "GOES-West", "Himawari"])
        self.assertIn("{layer}", data["gibs"]["tiles"])
        self.assertTrue(data["coast"]["lines"])

    def test_write_json_writes_the_payload(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = stormdesk.write_json(self.state(self.polo()), Path(tmp) / "storms.json")
            data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data["storms"][0]["id"], "ep172026")


class TestStormDeskPage(_DeskFixtures, unittest.TestCase):
    """storms.html: the map, its controls, and the panel beside it."""

    def page(self, *storms, **extra) -> str:
        town = atlasdata.Place("Isla Socorro", "Mexico", "Colima", 250,
                                -110.0, 17.5, False)
        with mock.patch.object(atlasdata, "PLACES", (town,)):
            return stormdesk.page(self.state(*storms, **extra))

    def section(self, html: str, key: str) -> str:
        match = re.search(rf'<section class="storm" id="storm-{key}".*?</section><!--{key}-->',
                          html, re.S)
        self.assertIsNotNone(match, key)
        return match.group(0)

    def test_the_page_embeds_the_payload(self):
        html = self.page(self.polo(), self.surigae())
        raw = re.search(r'<script id="desk-data" type="application/json">(.*?)</script>',
                        html, re.S).group(1)
        data = json.loads(raw)
        self.assertEqual(data["schema"], 1)
        self.assertEqual([s["id"] for s in data["storms"]], ["ep172026", "wp252026"])

    def test_the_page_has_its_controls(self):
        html = self.page(self.polo())
        for name in ("map", "tiles", "tiles-b", "overlay", "divider", "compare", "loop",
                     "scrub", "panel", "storm-list", "outlook-list", "legend"):
            self.assertIn(f'id="{name}"', html)
        for layer in stormdesk.LAYERS:
            self.assertIn(f'id="layer-{layer["id"]}"', html)
        for drawn in ("cone", "radii", "watches", "surge", "outlook", "places"):
            self.assertIn(f'id="show-{drawn}"', html)

    def test_the_legend_keys_every_kind_of_mark(self):
        html = self.page(self.polo(), self.surigae())
        legend = re.search(r'<div class="desklegend" id="legend".*?</div><!--legend-->',
                           html, re.S).group(0)
        for words in ("Polo", "Surigae", "34 kt", "50 kt", "64 kt", "Hurricane Warning",
                      "Hurricane Watch", "Tropical Storm Warning", "Tropical Storm Watch",
                      "Forecast cone", "Peak storm surge", "Low", "Medium", "High"):
            self.assertIn(words, legend)

    def test_each_storm_has_forecast_probability_and_exposure_tables(self):
        section = self.section(self.page(self.nolo()), "ep152026")
        for caption in ("Official forecast", "Wind speed probabilities", "Exposure"):
            self.assertIn(f"Table view &mdash; {caption}", section)
        self.assertIn("ISLA SOCORRO", section)
        self.assertIn("52%", section)
        self.assertIn("Hurricane Watch", section)
        self.assertIn("1-3 ft", section)

    def test_a_coast_is_named_once_however_many_stretches_fall_near_it(self):
        # Round Maui on 25 September 2026 four stretches of one warning fell
        # nearest Wailuku, and the desk read "on the coast near Wailuku; from
        # Wailuku to Honolulu; near Wailuku; near Wailuku".
        storm = self.warned(self.nolo(), "Hurricane Warning",
                            ((-110.3, 17.3), (-110.2, 17.4), (-110.3, 17.5), (-110.3, 17.3)),
                            ((-110.2, 18.0), (-109.8, 17.8)),
                            ((-109.9, 17.3), (-109.8, 17.2)))
        section = self.section(self.page(storm), "ep152026")
        self.assertIn("</b> on the coast near Isla Socorro. ", section)
        self.assertNotIn("; near Isla Socorro", section)
        self.assertNotIn(">near Isla Socorro<", section)

    def test_a_storm_with_no_official_forecast_is_not_said_to_reach_nowhere(self):
        # "No place in the desk's gazetteer comes inside the forecast wind
        # radii", of a storm whose forecast did not come.
        storm = self.polo()
        storm.forecast = ()
        entry = stormdesk.storm_entry(storm)
        self.assertEqual(entry["exposure"], [])
        pane = stormdesk._exposure_table(entry)
        self.assertIn("No official forecast this run", pane)
        self.assertNotIn("comes inside", pane)

    def test_surge_is_given_as_the_centre_wrote_it(self):
        # NHC's peak surge range carries its unit ("1-3 ft"); the page adds none.
        section = self.section(self.page(self.nolo()), "ep152026")
        self.assertIn(">1-3 ft<", section)
        self.assertNotIn("ft ft", section)
        self.assertNotIn('" ft surge"', stormdesk._JS)

    def test_a_product_from_an_older_advisory_carries_its_own_number(self):
        nolo = self.nolo()
        nolo.advisory = dict(nolo.advisory, advisory="021")
        nolo.products = dataclasses.replace(nolo.products, advisories=(
            ("watches", "20"), ("cone", "20"), ("surge", "20"), ("winds", "20")))
        section = self.section(self.page(nolo), "ep152026")
        self.assertIn("advisory 21", section)
        self.assertIn("from advisory 20", section)

    def test_only_the_products_a_later_advisory_superseded_are_called_old(self):
        # At the intermediate advisory 21A the watches and cone were reissued,
        # and the surge and wind probabilities, which come with full
        # advisories only, were still 21's: none of them is out of date.
        nolo = self.nolo()
        nolo.advisory = dict(nolo.advisory, advisory="021a")
        nolo.products = dataclasses.replace(nolo.products, advisory="21A", advisories=(
            ("watches", "21A"), ("cone", "21A"), ("surge", "21"), ("winds", "21")))
        self.assertNotIn("lagnote", self.section(self.page(nolo), "ep152026"))
        # Watches still at 21 under 21A are.
        nolo.products = dataclasses.replace(nolo.products, advisories=(
            ("watches", "21"), ("cone", "21A"), ("surge", "21"), ("winds", "21")))
        self.assertIn("The watches and warnings are from advisory 21; the current advisory "
                      "is 21A.", self.section(self.page(nolo), "ep152026"))

    def test_storm_colours_follow_the_dashboards_order(self):
        # The dashboard's track map draws NHC's storms only, strongest first,
        # in s1, s2...; JTWC's storms take the hues after them here, so Polo
        # is the same colour on both pages even when Surigae is stronger.
        surigae = self.surigae()
        surigae.track = tuple(cyclones.Fix(**dict(vars(f), wind=160)) for f in surigae.track)
        html = self.page(self.polo(), surigae)
        legend = re.search(r'<div class="desklegend" id="legend".*?</div><!--legend-->',
                           html, re.S).group(0)
        self.assertRegex(legend, r'var\(--s1\)"></span>[^<]*Polo')
        self.assertRegex(legend, r'var\(--s2\)"></span>[^<]*Surigae')

    def test_protect_says_whether_a_product_is_none_unavailable_or_not_published(self):
        failed = self.polo(
            products=tcproducts.Products(watches=None, cone=(), surge=(), winds=None,
                                         advisory="20"),
            links={"watches": self.WW, "cone": "", "surge": "", "winds": ""})
        failed.number, failed.name = 18, "Rosa"
        html = self.page(self.polo(), failed, self.surigae())
        self.assertIn("No coastal watches or warnings are in effect",
                      self.section(html, "ep172026"))
        self.assertIn("could not be fetched", self.section(html, "ep182026"))
        self.assertIn("JTWC does not issue coastal watches or warnings",
                      self.section(html, "wp252026"))

    def test_actions_for_people_and_animals_are_on_the_page_with_sources(self):
        html = self.page(self.polo())
        actions = re.search(r'<section id="actions".*?</section>', html, re.S).group(0)
        self.assertIn("pets evacuate too", actions)
        self.assertIn('href="https://www.ready.gov/pets"', actions)
        self.assertIn('href="https://www.ready.gov/hurricanes"', actions)

    def test_the_outlook_lists_chances_and_potentials(self):
        area = outlook.Disturbance(
            centre="NHC", basin="EP", label="Southwest of Mexico", lon=-102.0, lat=12.0,
            chance_2day=40, chance_7day=90, potential="high", text="", area=(),
            arrow=(), alert=False, issued="Fri Sep 25 11:40:21 2026", key="ep1")
        suspect = outlook.Disturbance(
            centre="JTWC", basin="WP", label="Invest 97W", lon=140.0, lat=10.0,
            chance_2day=None, chance_7day=None, potential="medium", text="",
            area=(), arrow=(), alert=False, issued="2026-09-25T06:00:00Z", key="97w")
        html = self.page(outlook=[area, suspect])
        listed = re.search(r'<section id="outlook-list".*?</section>', html, re.S).group(0)
        for words in ("Southwest of Mexico", "40%", "90%", "Invest 97W", "medium"):
            self.assertIn(words, listed)

    def test_a_quiet_page_says_so(self):
        html = self.page()
        self.assertIn("No live tropical cyclones", html)
        self.assertIn('id="outlook-list"', html)

    def test_no_external_scripts_and_no_insecure_urls(self):
        html = self.page(self.polo(), self.surigae())
        self.assertNotIn("<script src", html)
        self.assertNotIn("http://", html.replace("http://www.w3.org/2000/svg", ""))

    def test_only_the_map_takes_over_touch(self):
        css = stormdesk.css()
        owners = [rule.split("{")[0].strip()
                  for rule in re.findall(r"[^{}]+\{[^}]*touch-action:\s*none[^}]*\}", css)]
        self.assertEqual(owners, ["#map"])

    def test_the_page_says_once_that_storms_cannot_be_prevented(self):
        html = self.page(self.polo())
        self.assertEqual(html.count("cannot be prevented"), 1)
        self.assertIn('href="dashboard.html#stormfury"', html)

    def test_names_are_escaped(self):
        storm = self.polo()
        storm.name = "<b>Polo</b>"
        html = self.page(storm)
        panel = html.split('<script id="desk-data"')[0]
        self.assertNotIn("<b>Polo</b>", panel)
        self.assertIn("&lt;b&gt;Polo&lt;/b&gt;", panel)

    def test_the_script_exposes_its_hooks_and_pinches_with_two_pointers(self):
        script = stormdesk._JS
        self.assertIn("window.stormDesk", script)
        for hook in ("flyTo", "setLayer", "view"):
            self.assertRegex(script, rf"\b{hook}\s*:")
        self.assertIn("pointers.size", script)
        self.assertIn("D.gibs.domains", script)

    def test_the_legend_names_the_storms_and_keeps_the_rest_a_tap_away(self):
        # Below the map there is room for one row: the storms' colours stay in
        # view, and the key to every other mark opens under them.
        html = self.page(self.polo(), self.surigae())
        legend = re.search(r'<div class="desklegend" id="legend".*?</div><!--legend-->',
                           html, re.S).group(0)
        shown, _, folded = legend.partition("<details")
        self.assertIn("Polo", shown)
        self.assertIn("Surigae", shown)
        self.assertIn("<summary>Key to the map</summary>", folded)
        for words in ("Official forecast", "34 kt", "Hurricane Warning", "Peak storm surge",
                      "High"):
            self.assertNotIn(words, shown)
            self.assertIn(words, folded)

    def test_no_overlay_is_one_gibs_serves_black(self):
        # In Web Mercator GIBS answers every Reference_Labels_15m tile with the
        # same opaque black 921-byte PNG (z3 to z8, 25 Sep 2026): switched on,
        # it blacked out the map.
        names = [layer.get("global") for layer in stormdesk.LAYERS]
        self.assertNotIn("Reference_Labels_15m", names)
        self.assertNotIn('"labels"', stormdesk._JS)

    def test_the_reference_overlays_wait_to_be_asked_for(self):
        # GIBS's coastline tiles answered 500 at random on 25 Sep 2026, and a
        # page that asks for them unbidden logs errors it cannot prevent.
        toolbar = stormdesk._toolbar()
        boxes = re.findall(r'<input type="checkbox" id="layer-[^"]+" data-ref="[^"]+"[^>]*>', toolbar)
        self.assertEqual(len(boxes), len([l for l in stormdesk.LAYERS if l["kind"] == "overlay"]))
        for box in boxes:
            self.assertNotIn("checked", box)

    def test_the_dashboards_card_rules_never_reach_a_map_tile(self):
        # The shell draws .tile as a white card with a border and padding; a
        # map tile wearing that class was framed in white, and a transparent
        # coastline tile over the imagery turned the whole map white.
        from elnino.dashboard import _css as shell_css
        styled = set(re.findall(r"\.([A-Za-z][\w-]*)", shell_css()))
        names = set(re.findall(r'className = "([\w-]+)"', stormdesk._JS))
        names |= set(re.findall(r'class="([\w-]+)" id="(?:tiles|tiles-b|refs)"',
                                stormdesk._map()))
        self.assertGreaterEqual(len(names), 3)
        self.assertEqual(names & styled, set())


class TestStormDeskFind(_DeskFixtures, unittest.TestCase):
    """Finding a town, region, country or coordinate on the storm desk."""

    def data(self, html: str) -> dict:
        raw = re.search(r'<script id="desk-data" type="application/json">(.*?)</script>',
                        html, re.S).group(1)
        return json.loads(raw)

    def test_the_page_carries_the_gazetteer_as_the_atlas_does(self):
        data = self.data(stormdesk.page(self.state(self.polo())))
        self.assertEqual(data["places"], atlasview._places_payload())
        kingston = [row for row in data["places"]
                    if row[0] == "Kingston" and row[1] == "Jamaica"]
        self.assertEqual(len(kingston), 1)

    def test_the_data_file_leaves_the_gazetteer_out(self):
        # storms.json is re-read by whatever consumes it; 7,342 places a run
        # that never change are the page's business.
        self.assertNotIn("places", stormdesk.payload(self.state(self.polo())))

    def test_the_search_box_is_labelled_and_lists_what_it_finds(self):
        html = stormdesk.page(self.state(self.polo()))
        form = re.search(r'<form class="deskfind"[^>]*role="search"[^>]*>.*?</form>',
                         html, re.S)
        self.assertIsNotNone(form)
        form = form.group(0)
        self.assertRegex(form, r'<label for="find"[^>]*>Find a place</label>')
        self.assertRegex(form, r'<input type="search" id="find"[^>]*role="combobox"'
                               r'[^>]*aria-controls="find-list"')
        self.assertRegex(form, r'<ul id="find-list"[^>]*role="listbox"')
        self.assertIn('id="find-note" role="status"', form)


class TestStormDeskHere(_DeskFixtures, unittest.TestCase):
    """What every live storm means for one point someone picks."""

    def test_the_panel_opens_with_an_empty_here_section(self):
        html = stormdesk.page(self.state(self.polo()))
        panel = re.search(r'<aside class="deskpanel" id="panel"[^>]*>(.*?)</aside>',
                          html, re.S).group(1)
        self.assertRegex(panel, r'^<section class="here" id="here"[^>]*hidden[^>]*></section>')

    def test_the_method_behind_here_is_stated(self):
        words = stormdesk.METHODS["here"]
        for phrase in ("official forecast", "hour by hour", "not forecast",
                       "not an official product"):
            self.assertIn(phrase, words)

    def test_the_map_can_point_down_to_here_on_a_narrow_screen(self):
        html = stormdesk.page(self.state(self.polo()))
        self.assertRegex(html, r'<button type="button" class="deskpill herepill ui" '
                               r'id="herego" hidden>')

    def test_the_atlas_opens_at_a_point_named_in_its_address(self):
        self.assertIn("#at=", atlasview._JS)
        self.assertIn("hashchange", atlasview._JS)

    def test_the_path_carries_each_centre_as_the_exposure_table_has_it(self):
        # The page works out when the wind reaches a point from this path, as
        # the exposure table does from the forecast itself. A centre rounded
        # half a kilometre off moved a town at the edge of a radius an hour;
        # rounded to ten metres, one point in six hundred still moved.
        storm = self.polo()
        path = [p for p in stormdesk.storm_entry(storm)["path"] if p["hour"] >= 0]
        line = [f for f in exposure.timeline(storm.latest, storm.forecast) if f.tau <= 120]
        self.assertEqual(len(path), len(line))
        for point, fix in zip(path, line):
            self.assertAlmostEqual(point["lat"], fix.lat, places=9)
            self.assertAlmostEqual(stormdesk._wrap(point["lon"] - fix.lon), 0, places=9)


def _js_function(js: str, name: str) -> str:
    """One named function of a page script, as written; "" if it has none."""
    found = re.search(r"\bfunction %s\(" % re.escape(name), js)
    if not found:
        return ""
    depth, i = 0, js.index("{", found.start())
    while True:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if not depth:
                return js[found.start():i + 1]
        i += 1


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestHereRuns(_DeskFixtures, unittest.TestCase):
    """What Here says of a point, run under node: the page's own functions, fed
    the storms' payload as the page is, at 15Z on 25 September 2026."""

    NAMES = ("rad", "deg", "wrap", "km", "bearing", "pad2", "utc", "esc", "clamp",
             "frameLon", "within", "insideAt", "inRing", "toLine", "nearestPlace", "fold",
             "kms", "soon", "pct", "hereFor", "nearHere", "stormHere")
    HARNESS = r"""
var HOUR = 3600000, NM = 1.852, THRESHOLDS = ["34", "50", "64"];
var ORDER = ["Tropical Storm Watch", "Tropical Storm Warning", "Hurricane Watch", "Hurricane Warning"];
var COMPASS8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
var PLACES = [], D = {outlook: [], style: {products: {}}}, STORMS = [];
Date.now = function () { return Date.parse("2026-09-25T15:00:00Z"); };
/*FUNCTIONS*/
var input = JSON.parse(require("fs").readFileSync(0, "utf8"));
STORMS = input.storms.map(function (d) { return {d: d, hue: "#000"}; });
D.outlook = input.outlook;
var h = hereFor(input.point[0], input.point[1]);
console.log(JSON.stringify({
  storms: h.storms.map(function (r) {
    return {id: r.id, html: stormHere(r),
            near: typeof nearHere === "function" ? nearHere(r) : null};
  }),
  soon: input.soon.map(soon),
  areas: h.areas
}));
"""

    def here(self, *storms, point=(-111.0, 18.0), soon=(), outlook=()):
        js = stormdesk._JS
        functions = "\n".join(_js_function(js, name) for name in self.NAMES)
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "here.js"
            script.write_text(self.HARNESS.replace("/*FUNCTIONS*/", functions),
                              encoding="utf-8")
            done = subprocess.run(
                ["node", str(script)], capture_output=True, text=True, timeout=120,
                input=json.dumps({"storms": [stormdesk.storm_entry(s) for s in storms],
                                  "point": list(point), "soon": list(soon),
                                  "outlook": [stormdesk._area(a) for a in outlook]}))
        if done.returncode:
            raise AssertionError(done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_a_storm_with_no_official_forecast_is_said_to_have_none(self):
        # Its forecast deck did not come. Here said "Its official forecast
        # takes it no closer than that", of a forecast there was not.
        storm = self.polo()
        storm.forecast = ()
        [said] = self.here(storm)["storms"]
        self.assertIn("No official forecast this run", said["html"])
        self.assertNotIn("official forecast takes it", said["html"])
        self.assertIs(said["near"], True)

    def test_a_product_that_could_not_be_fetched_is_said_to_be_missing(self):
        # Nothing said read as nothing in effect here.
        storm = self.nolo()
        storm.products = dataclasses.replace(
            storm.products, watches=None, cone=None, surge=None,
            in_effect=(("Hurricane Watch", ("Isla Socorro",)),))
        html = self.here(storm)["storms"][0]["html"]
        self.assertIn("the public advisory has in effect: Hurricane Watch for Isla Socorro",
                      html)
        self.assertIn("The forecast cone could not be fetched this run", html)
        self.assertIn("The peak storm surge forecast could not be fetched this run", html)

    def test_a_storm_with_everything_issued_is_not_said_to_be_missing_anything(self):
        [said] = self.here(self.nolo())["storms"]
        self.assertNotIn("could not be fetched", said["html"])
        self.assertNotIn("No official forecast", said["html"])
        self.assertIn("official forecast", said["html"])

    def test_inside_a_formation_alert_s_box_here_says_until_when(self):
        alert = jtwc.formation_alert(fixture("jtwc_wp9326.tcw"),
                                     "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw")
        [[area]] = jtwc.alerted([jtwc.disturbances(fixture("jtwc_abpw_93w.txt"))], [alert], {})
        [inside] = self.here(point=(150.5, 16.5), outlook=[area])["areas"]
        self.assertEqual((inside["key"], inside["inside"], inside["until"]),
                         ("93w", True, "2026-09-30T17:00:00Z"))
        self.assertIn("alertHtml(a.until)", _js_function(stormdesk._JS, "showHere"))

    def test_a_time_past_is_so_many_hours_ago(self):
        # A wind already over the place, 3 hours before: "(-3 h ago)".
        self.assertEqual(self.here(self.nolo(), soon=("2026-09-25T12:00:00Z",
                                                      "2026-09-25T18:00:00Z",
                                                      "2026-09-25T15:10:00Z"))["soon"],
                         ["3 h ago", "in about 3 h", "about now"])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestAlertTimeRuns(unittest.TestCase):
    """A formation alert on the open page, run under node at 15Z on 25
    September 2026: worded until its time, and as run out after it."""

    def run_js(self, body: str):
        functions = "\n".join(_js_function(stormdesk._JS, name) for name in (
            "pad2", "utc", "esc", "span", "ago", "lapsed", "alertWords", "alertHtml", "ages"))
        return _node_json(self, r"""
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
Date.now = function () { return Date.parse("2026-09-25T15:00:00Z"); };
var dirtied = 0, lapsedNow = "";
function dirty() { dirtied++; }
""" + functions + body)

    def test_an_alert_is_worded_until_its_time_and_as_run_out_after(self):
        got = self.run_js(r"""
console.log(JSON.stringify([
  alertWords("2026-09-25T16:00:00Z"), alertWords("2026-09-25T14:00:00Z"), alertWords(""),
  lapsed("2026-09-25T15:00:00Z"), lapsed("2026-09-25T15:01:00Z"), lapsed(undefined),
  alertHtml("2026-09-25T16:00:00Z"), alertHtml(""),
  alertWords("2026-09-25T16:00:00Z", true), alertWords("2026-09-25T14:00:00Z", true)]));
""")
        self.assertEqual(got, [
            "formation alert until 25 Sep 16:00 UTC",
            "formation alert ran to 25 Sep 14:00 UTC; nothing newer read",
            "formation alert in effect", True, False, False,
            '<span data-until="2026-09-25T16:00:00Z">formation alert until 25 Sep 16:00 UTC</span>',
            "formation alert in effect",
            # A map label, as short as the line it replaced.
            "formation alert until 25 Sep 16:00 UTC", "formation alert ran to 25 Sep 14:00 UTC"])

    def test_an_alert_that_runs_out_while_the_page_is_open_is_reworded_and_redrawn(self):
        got = self.run_js(r"""
var row = {textContent: "formation alert until 25 Sep 16:00 UTC",
           getAttribute: function (name) { return name === "data-until" ? "2026-09-25T16:00:00Z" : null; }};
var document = {querySelectorAll: function (sel) { return sel === "[data-until]" ? [row] : []; }};
var D = {outlook: [{key: "93w", alert: true, formation: {until: "2026-09-25T16:00:00Z"}},
                   {key: "94w", alert: false, formation: null}]};
ages();
var before = [row.textContent, dirtied];
Date.now = function () { return Date.parse("2026-09-25T16:01:00Z"); };
ages();
var after = [row.textContent, dirtied];
ages();
console.log(JSON.stringify([before, after, dirtied]));
""")
        self.assertEqual(got, [
            ["formation alert until 25 Sep 16:00 UTC", 0],
            ["formation alert ran to 25 Sep 16:00 UTC; nothing newer read", 1], 1])


class TestStormDeskCloseIn(_DeskFixtures, unittest.TestCase):
    """Closing in on a town: 30 m imagery, night lights, built-up areas, names."""

    def layer(self, key: str) -> dict:
        [found] = [layer for layer in stormdesk.LAYERS if layer["id"] == key]
        return found

    def test_the_close_layers_are_named_as_gibs_capabilities_list_them(self):
        # GIBS WMTS capabilities (EPSG:3857), 25 Sep 2026.
        detail = self.layer("detail")
        self.assertEqual(detail["stack"], ("HLS_L30_Nadir_BRDF_Adjusted_Reflectance",
                                           "HLS_S30_Nadir_BRDF_Adjusted_Reflectance"))
        self.assertEqual((detail["kind"], detail["tms"], detail["format"], detail["step"]),
                         ("imagery", "GoogleMapsCompatible_Level12", "png", "P1D"))
        self.assertEqual(detail["pixel_km"], 0.03)
        lights = self.layer("lights")
        self.assertEqual((lights["global"], lights["time"], lights["tms"], lights["format"]),
                         ("VIIRS_Black_Marble", "2016-01-01", "GoogleMapsCompatible_Level8",
                          "png"))
        builtup = self.layer("builtup")
        self.assertEqual((builtup["kind"], builtup["global"], builtup["tms"],
                          builtup["format"], builtup["step"]),
                         ("overlay", "Landsat_Human_Built-up_And_Settlement_Extent",
                          "GoogleMapsCompatible_Level12", "png", None))

    def test_the_desk_closes_in_to_level_13(self):
        self.assertRegex(stormdesk._JS, r"MAXZ = 13\b")

    def test_town_names_are_an_overlay_that_can_be_switched_off(self):
        html = stormdesk.page(self.state(self.polo()))
        self.assertRegex(html, r'<input type="checkbox" id="show-towns" data-show="towns" '
                               r'checked> Town names <span class="why" id="why-towns"></span></label>')

    def test_the_detail_layer_steps_between_days_with_an_image(self):
        html = stormdesk.page(self.state(self.polo()))
        days = re.search(r'<div class="deskdays ui" id="days"[^>]*hidden>.*?</div>', html, re.S)
        self.assertIsNotNone(days)
        self.assertRegex(days.group(0), r'<button type="button" id="day-earlier" '
                                        r'aria-label="Earlier day with an image here"')
        self.assertRegex(days.group(0), r'<button type="button" id="day-later" '
                                        r'aria-label="Later day with an image here"')
        self.assertIn('id="day-now" role="status"', days.group(0))

    def test_how_the_day_is_chosen_is_stated(self):
        words = stormdesk.METHODS["detail"]
        for phrase in ("newest day", "centre of the view", "30 m", "clouds as seen"):
            self.assertIn(phrase, words)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestDaySearchRuns(unittest.TestCase):
    """The desk's day search for the detail layer, run under node.

    Everything else in the page script is checked by reading it. What the day
    search concludes depends on which tiles answer and how, so it is run: its
    own code, sliced from the page, with the tiles stubbed.
    """

    HARNESS = r"""
function make(env) {
  var S = env.S, LAYERS = env.LAYERS, DOM = env.DOM, Image = env.Image, document = env.document;
  var HOUR = 3600000, MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var setTimeout = env.later, clearTimeout = function () {};
  function clamp(v, a, b) { return Math.max(a, Math.min(b, v)); }
  function dayZ(t) { return new Date(t).toISOString().slice(0, 10); }
  function stamp(text) { return Date.parse(/^\d{4}-\d\d-\d\d$/.test(text) ? text + "T00:00:00Z" : text); }
  function source(layer, name) { return name; }
  function tileUrl(name, day) { return name + "/" + day; }
  function requestRender() {} function dirty() {} function ask() {}
/*DAYS*/
  return {dayCheck: dayCheck, dayWords: dayWords};
}
function run(scenario, answer) {
  return new Promise(function (finish) {
    var S = {layer: "detail", compare: false, second: "infrared", imagery: "ok", z: 11,
             x: 0.2, y: 0.45, day: null, dayState: null, dayStepped: false};
    var requests = 0, later = [];
    function Image() {}
    Object.defineProperty(Image.prototype, "src", {set: function (url) {
      var img = this, got = answer(url);
      requests++;
      img.alpha = got === "error" ? 0 : got;
      setTimeout(function () { got === "error" ? img.onerror() : img.onload(); }, 0);
    }});
    var document = {createElement: function () {
      var alpha = 0;
      return {getContext: function () {
        return {drawImage: function (img) { alpha = img.alpha; },
                getImageData: function () {
                  var data = new Uint8ClampedArray(32 * 32 * 4);
                  for (var i = 3; i < data.length; i += 4) data[i] = alpha;
                  return {data: data};
                }};
      }};
    }};
    var desk = make({S: S, Image: Image, document: document,
                     LAYERS: {detail: {zoom: 12, stack: ["HLS_L30", "HLS_S30"]}},
                     DOM: {HLS_L30: {frames: [{key: "2026-09-23"}]}, HLS_S30: {frames: [{key: "2026-09-23"}]}},
                     later: function (fn, ms) { later.push(ms); return later.length; }});
    desk.dayCheck();
    var began = Date.now();
    (function settled() {
      if (S.dayState === "looking" && Date.now() - began < 10000) return setTimeout(settled, 10);
      finish({scenario: scenario, day: S.day, dayState: S.dayState, words: desk.dayWords(),
              requests: requests, later: later});
    })();
  });
}
(async function () {
  console.log(JSON.stringify([
    await run("network down", function () { return "error"; }),
    await run("Landsat 500s, Sentinel-2 blank", function (url) {
      return url.indexOf("HLS_L30/") === 0 ? "error" : 0; }),
    await run("an image on 20 Sep", function (url) {
      return url.indexOf("HLS_S30/2026-09-20") === 0 ? 255 : 0; })
  ]));
})();
"""

    @classmethod
    def setUpClass(cls):
        js = stormdesk._JS
        days = js[js.index("  // ---- the detail layer's day"):js.index("  function dayControls()")]
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "days.js"
            script.write_text(cls.HARNESS.replace("/*DAYS*/", days), encoding="utf-8")
            done = subprocess.run(["node", str(script)], capture_output=True, text=True,
                                  timeout=120)
        if done.returncode:
            raise AssertionError(done.stderr)
        cls.runs = {run["scenario"]: run for run in json.loads(done.stdout)}

    def test_no_answer_from_gibs_is_not_no_image(self):
        # A network that drops while the desk is open: every tile fails. The
        # search stops at the first day, says GIBS did not answer rather than
        # that there is no image, and looks again in a minute.
        run = self.runs["network down"]
        self.assertEqual((run["day"], run["dayState"]), (None, "no answer"))
        self.assertIn("NASA GIBS did not answer", run["words"])
        self.assertNotIn("no image here", run["words"])
        self.assertEqual(run["requests"], 2)
        self.assertIn(60000, run["later"])

    def test_one_imager_failing_while_the_other_answers_blank_is_no_image(self):
        # GIBS's 500 for a Landsat day, with Sentinel-2 answering: as ruled in
        # Task 17, that day has no image here, and the search goes on.
        run = self.runs["Landsat 500s, Sentinel-2 blank"]
        self.assertEqual((run["day"], run["dayState"]), (None, "none"))
        self.assertEqual(run["words"], "no image here in the 40 days to 23 Sep 2026")
        self.assertEqual(run["requests"], 82)

    def test_the_newest_day_with_an_image_is_found(self):
        run = self.runs["an image on 20 Sep"]
        self.assertEqual((run["day"], run["dayState"]), ("2026-09-20", "ok"))
        self.assertEqual(run["requests"], 8)


class TestImageryNoAnswer(unittest.TestCase):
    """No answer from GIBS is said as that, never as GIBS having nothing."""

    def test_a_layer_gibs_did_not_answer_for_is_not_said_to_have_no_frames(self):
        # Frame times asked for while the network is down: the layer's pill
        # says GIBS did not answer, not that GIBS has no frames.
        js = stormdesk._JS
        failed = re.search(r"\.catch\(function \(\) \{\s*(//[^\n]*\s*)?"
                           r"DOM\[s\.name\]\.unanswered = !DOM\[s\.name\]\.frames\.length;", js)
        self.assertIsNotNone(failed, "a failed frame-times request is not marked unanswered")
        self.assertTrue('d && d.unanswered ? ": GIBS did not answer"' in js,
                        "the layer's pill does not say GIBS did not answer")


class TestStormDeskLink(_DeskFixtures, unittest.TestCase):
    """The dashboard's way into storms.html, beside its own storm cards."""

    AREA = dict(centre="NHC", basin="EP", label="Southwest of Mexico", lon=-102.0,
                lat=12.0, chance_2day=40, chance_7day=90, potential="high", text="",
                area=(), arrow=(), alert=False, issued="Fri Sep 25 11:40:21 2026",
                key="ep1")

    def test_the_card_opens_the_storm_desk_and_says_what_is_on_it(self):
        card = dashboard.storm_desk_card(
            self.state(self.polo(), self.surigae(), outlook=[outlook.Disturbance(**self.AREA)]))
        self.assertIn('id="storm-desk"', card)
        self.assertIn('href="storms.html"', card)
        for words in ("Polo", "NHC", "Surigae", "JTWC", "Southwest of Mexico", "90%"):
            self.assertIn(words, card)

    def test_the_card_says_a_formation_alert_is_in_effect(self):
        area = outlook.Disturbance(**dict(self.AREA, centre="JTWC", basin="WP",
                                          label="Invest 93W", chance_2day=None,
                                          chance_7day=None, alert=True, key="93w"))
        self.assertIn("Invest 93W &middot; high potential, formation alert",
                      dashboard.storm_desk_card(self.state(outlook=[area])))

    def test_the_card_says_until_when_a_formation_alert_holds(self):
        # It said ", formation alert" and no more.
        alert = jtwc.formation_alert(fixture("jtwc_wp9326.tcw"),
                                     "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw")
        [[area]] = jtwc.alerted([jtwc.disturbances(fixture("jtwc_abpw_93w.txt"))], [alert], {})
        state = self.state(outlook=[area])
        self.assertIn(f"{area.label} &middot; high potential, formation alert until "
                      "30 Sep 17:00 UTC</li>", dashboard.storm_desk_card(state))
        state.run_at = "2026-09-30T18:05:00+00:00"
        self.assertIn("high potential, formation alert ran to 30 Sep 17:00 UTC; nothing "
                      "newer read</li>", dashboard.storm_desk_card(state))

    def test_a_quiet_run_still_opens_the_desk(self):
        # No storm is live, but the imagery and the formation outlook are the
        # reason to open the desk on a quiet day.
        card = dashboard.storm_desk_card(self.state())
        self.assertIn('href="storms.html"', card)
        self.assertIn("No live tropical cyclones", card)

    def test_the_payload_carries_the_outlook_the_desk_draws(self):
        state = self.state(outlook=[outlook.Disturbance(**self.AREA)])
        self.assertEqual(dashboard.outlook_json(state), stormdesk.payload(state)["outlook"])

    def test_the_payload_says_where_the_storm_desk_is(self):
        self.assertEqual(dashboard.STORM_DESK,
                         {"page": "storms.html", "data": "storms.json",
                          "schema": stormdesk.SCHEMA})


class TestStreetMaps(_DeskFixtures, unittest.TestCase):
    """Street, satellite and terrain maps under the desk's marks, to zoom 19."""

    ESRI = "https://server.arcgisonline.com/ArcGIS/rest/services/"

    def layer(self, key):
        [found] = [l for l in worldmap.MAP_LAYERS if l["id"] == key]
        return found

    def data(self, html):
        raw = re.search(r'<script id="desk-data" type="application/json">(.*?)</script>',
                        html, re.S).group(1)
        return json.loads(raw)

    def test_the_maps_are_esris_and_openstreetmaps_keyless_tiles(self):
        tile = "/MapServer/tile/{z}/{y}/{x}"
        self.assertEqual(self.layer("streets")["tiles"], self.ESRI + "World_Street_Map" + tile)
        self.assertEqual(self.layer("satellite")["tiles"], self.ESRI + "World_Imagery" + tile)
        self.assertEqual(self.layer("satellite")["over"], [
            self.ESRI + "Reference/World_Transportation" + tile,
            self.ESRI + "Reference/World_Boundaries_and_Places" + tile])
        self.assertEqual(self.layer("terrain")["tiles"], self.ESRI + "World_Topo_Map" + tile)
        self.assertEqual(self.layer("osm")["tiles"],
                         "https://tile.openstreetmap.org/{z}/{x}/{y}.png")
        for layer in worldmap.MAP_LAYERS:
            self.assertEqual((layer["kind"], layer["zoom"]), ("map", 19))
            self.assertTrue(layer["credit"])

    def test_openstreetmap_is_for_a_served_page_only(self):
        # Its servers answer a page opened from a file, which sends no
        # Referer, with an "Access blocked" image (28 Sep 2026).
        self.assertTrue(self.layer("osm")["served_only"])
        self.assertFalse(self.layer("osm")["grey"])
        self.assertIn("servedOnly(location.protocol)", stormdesk._JS)

    def test_the_compare_menu_offers_every_layer_it_can_show(self):
        # Swap puts the base on the compared side; a street map there left
        # the menu blank, as it listed NASA's imagery only.
        html = stormdesk.page(self.state(self.polo()), focus="world")
        menu = re.search(r'<select id="compare-layer"[^>]*>(.*?)</select>', html, re.S).group(1)
        self.assertEqual(re.findall(r'<optgroup label="([^"]+)">', menu), ["Map", "NASA imagery"])
        offered = re.findall(r'<option value="(\w+)"', menu)
        shown = [l["id"] for l in self.data(html)["layers"] if l["kind"] in ("map", "imagery")]
        self.assertEqual(sorted(offered), sorted(shown))
        self.assertEqual(re.findall(r'<option value="(\w+)" selected>', menu), ["infrared"])

    def test_a_layer_that_needs_the_page_served_says_so_where_it_is_pressed(self):
        html = stormdesk.page(self.state(self.polo()), focus="world")
        # A live region is announced when its words change, if it was
        # rendered before they did: so the line is always there, and takes
        # no room while it has nothing to say.
        self.assertIn('<p class="toolnote" id="layer-note" role="status"></p>', html)
        self.assertRegex(html, r"\.toolnote:empty \{ position: absolute;[^}]*clip-path: inset\(50%\)")
        self.assertNotIn("b.disabled = true", stormdesk._JS)

    def test_every_nasa_layer_is_credited_in_its_own_words(self):
        for layer in stormdesk.LAYERS:
            parts = stormdesk._gibs_credits(layer)
            self.assertTrue(parts and all(parts), layer["id"])
        self.assertEqual(stormdesk._gibs_credits(stormdesk.LAYERS[0]), ["GOES: NOAA.", "GOES: NOAA."])
        full = stormdesk.GIBS_ENDPOINTS["credit"]
        self.assertTrue(full.startswith("Imagery: NASA GIBS. GOES: NOAA. Himawari: JMA."))
        # Every source on the page is named once, the four the old line missed too.
        for words in ("Blue Marble", "Black Marble", "HLS", "HBASE", "IMERG", "VIIRS",
                      "OpenStreetMap"):
            self.assertEqual(full.count(words), 1, words)
        self.assertEqual(full.count("GOES"), 1)

    def test_town_names_say_when_they_are_not_drawn(self):
        html = stormdesk.page(self.state(self.polo()), focus="world")
        self.assertRegex(html, r'data-show="towns" checked> Town names '
                               r'<span class="why" id="why-towns"></span></label>')

    def test_the_page_offers_the_maps_beside_nasas_imagery(self):
        html = stormdesk.page(self.state(self.polo()))
        group = re.search(r'<div class="seg" role="group" aria-label="Map">(.*?)</div>',
                          html, re.S).group(1)
        self.assertEqual(re.findall(r'data-layer="(\w+)"', group),
                         ["streets", "satellite", "terrain", "osm"])
        self.assertIn('aria-label="NASA imagery"', html)
        kinds = [l["kind"] for l in self.data(html)["layers"]]
        self.assertEqual(kinds.count("map"), 4)
        self.assertIn('id="over"', html)
        self.assertIn('id="over-b"', html)

    def test_the_data_file_keeps_its_layers_as_they_were(self):
        data = stormdesk.payload(self.state())
        self.assertEqual({l["kind"] for l in data["layers"]}, {"imagery", "overlay"})

    def test_the_map_script_is_taken_in_once(self):
        self.assertEqual(stormdesk._JS.count("/*WORLDMAP*/"), 1)
        self.assertNotIn("/*WORLDMAP*/", stormdesk.script())
        self.assertIn(worldmap._JS.strip()[:40], stormdesk.script())

    def test_offline_the_page_says_the_maps_need_the_network(self):
        self.assertIn("street and satellite maps need the network", stormdesk._JS)


    def test_a_tile_that_failed_is_not_taken_for_a_placeholder(self):
        # A network failure is not Esri saying it has nothing finer; marking
        # it would walk every tile up the pyramid while the network is down.
        self.assertNotIn("NODATA", _js_function(stormdesk._JS, "tileFailed"))
        self.assertIn("NODATA", _js_function(stormdesk._JS, "tileLoaded"))

    def test_the_page_says_when_part_of_the_view_is_enlarged(self):
        self.assertIn("has nothing finer than zoom", stormdesk._JS)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestStreetMapRuns(unittest.TestCase):
    """The engine's street-map functions, under node."""

    NAMES = ("clamp", "world", "origin", "xyzUrl", "present", "xyzCells", "maxZoom",
             "servedOnly", "placeholder", "source")
    HARNESS = r"""
var TILE = 256, MAXZ = 13, NODATA = {};
var LAYERS = {streets: {id: "streets", kind: "map", zoom: 19, grey: true},
              infrared: {id: "infrared", kind: "imagery", zoom: 6}};
var S = {layer: "streets", x: 0.5, y: 0.5, z: 2, w: 512, h: 512};
/*FUNCTIONS*/
var out = {};
out.url = xyzUrl("https://x/tile/{z}/{y}/{x}", 17, 38000, 49000);
out.deep = maxZoom(); S.layer = "infrared"; out.nasa = maxZoom(); S.layer = "streets";
out.served = ["http:", "https:", "file:", "about:"].map(servedOnly);
out.cells = xyzCells(LAYERS.streets, "t/{z}/{y}/{x}", "streets").map(function (c) {
  return [c.z, c.c, c.r, c.url, c.grey]; });
S.x = 0.01; S.z = 1;
out.wrapped = xyzCells(LAYERS.streets, "t/{z}/{y}/{x}", "streets").map(function (c) { return c.url; });
S.z = 22;
out.capped = xyzCells(LAYERS.streets, "t/{z}/{y}/{x}", "streets")[0].z;
function px(list) {            // list of [count, r, g, b, a]
  var a = [];
  list.forEach(function (run) { for (var i = 0; i < run[0]; i++) a.push(run[1], run[2], run[3], run[4]); });
  return a;
}
out.grey = [
  placeholder(px([[256, 204, 204, 204, 255]])),
  placeholder(px([[200, 204, 204, 204, 255], [56, 255, 255, 255, 255]])),
  placeholder(px([[199, 204, 204, 204, 255], [57, 255, 255, 255, 255]])),
  placeholder(px([[256, 207, 201, 205, 255]])),
  placeholder(px([[256, 208, 204, 204, 255]])),
  placeholder(px([[256, 242, 239, 210, 255]])),
  placeholder(px([[256, 170, 211, 223, 255]])),
  placeholder(px([[256, 204, 204, 204, 0]]))
];
NODATA = {"streets/16/100/200": true, "streets/15/50/100": true};
out.fallback = [present("streets", 16, 100, 200), present("streets", 16, 101, 200),
                present("streets", 16, 100 - 65536, 200)];
out.source = source("streets", "GOES-West");
console.log(JSON.stringify(out));
"""

    def run_page(self):
        functions = "\n".join(_js_function(stormdesk._JS, n) for n in self.NAMES)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "map.js"
            path.write_text(self.HARNESS.replace("/*FUNCTIONS*/", functions), encoding="utf-8")
            done = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                  timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_each_side_of_the_divider_draws_only_its_own_layer(self):
        # Compared on the right, Esri's imagery came without the roads and
        # names it carries as the base, while the gazetteer's town names stood
        # aside for them there. And the compared layer, under the base, showed
        # through on the base's side wherever the base drew nothing: past an
        # imager's disc, or a tile not yet come.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "clamp", "world", "origin", "xyzUrl", "present", "xyzCells", "cells", "overSpecs", "tiles",
            "loopWhenKnown"))
        got = _node_json(self, r"""
var TILE = 256, NODATA = {}, D = {layers: []};
var LAYERS = {streets: {id: "streets", kind: "map", zoom: 19, tiles: "st/{z}/{y}/{x}"},
              satellite: {id: "satellite", kind: "map", zoom: 19, tiles: "im/{z}/{y}/{x}",
                          over: ["rd/{z}/{y}/{x}", "pl/{z}/{y}/{x}"]}};
function pane() { return {el: {style: {clipPath: ""}}, drawn: null}; }
var panes = {a: pane(), b: pane(), o: pane(), ob: pane(), r: pane(), e: pane()};
function drawPane(p, specs) {
  p.drawn = specs.map(function (sp) {
    var from = [];
    sp.cells.forEach(function (c) { var w = c.url.split("/")[0]; if (from.indexOf(w) < 0) from.push(w); });
    return [sp.key, from];
  });
}
function ensoTileSpecs() { return []; }
var S = {layer: "streets", second: "satellite", compare: true, split: 0.25, w: 800, h: 400,
         x: 0.5, y: 0.5, z: 3, frame: 0, loop: false, imagery: "ok", refs: {}};
""" + functions + r"""
function look() {
  tiles(false);
  return ["a", "b", "o", "ob"].map(function (k) { return [panes[k].drawn, panes[k].el.style.clipPath]; })
    .concat([S.inViewB ? Object.keys(S.inViewB) : null]);
}
var out = [look()];
S.layer = "satellite"; S.second = "streets"; out.push(look());
S.compare = false; out.push(look());
S.layer = "streets"; S.second = "satellite"; out.push(look());
console.log(JSON.stringify(out));
""")
        left, right = "inset(0 600.0px 0 0)", "inset(0 0 0 200.0px)"
        roads = [["o0", ["rd"]], ["o1", ["pl"]]]
        # A street map as the base, Esri's imagery compared: the imagery and
        # its roads and names right of the divider, nothing of it left.
        self.assertEqual(got[0], [[[["f0", ["st"]]], left], [[["b", ["im"]]], right],
                                  [[], left], [roads, right], ["satellite"]])
        self.assertEqual(got[1], [[[["f0", ["im"]]], left], [[["b", ["st"]]], right],
                                  [roads, left], [[], right], ["streets"]])
        # Not compared, the second layer draws nothing, its roads and names included.
        self.assertEqual(got[2], [[[["f0", ["im"]]], ""], [[], ""], [roads, ""], [[], ""], None])
        self.assertEqual(got[3], [[[["f0", ["st"]]], ""], [[], ""], [[], ""], [[], ""], None])

    def test_a_tile_address_is_z_y_x_as_the_template_orders_it(self):
        self.assertEqual(self.run_page()["url"], "https://x/tile/17/49000/38000")

    def test_a_map_closes_in_to_19_and_nasa_imagery_to_13(self):
        out = self.run_page()
        self.assertEqual((out["deep"], out["nasa"]), (19, 13))

    def test_openstreetmap_waits_for_a_served_page(self):
        self.assertEqual(self.run_page()["served"], [True, True, False, False])

    def test_the_tiles_in_view_are_listed_once_each(self):
        cells = self.run_page()["cells"]
        self.assertEqual(sorted(c[:3] for c in cells),
                         [[2, 1, 1], [2, 1, 2], [2, 2, 1], [2, 2, 2]])
        self.assertIn([2, 1, 2, "t/2/2/1", True], cells)

    def test_a_view_across_the_seam_asks_for_real_columns(self):
        for url in self.run_page()["wrapped"]:
            col = int(url.split("/")[-1])
            self.assertIn(col, (0, 1))

    def test_past_the_maps_deepest_zoom_its_deepest_tiles_are_enlarged(self):
        self.assertEqual(self.run_page()["capped"], 19)

    def test_only_esris_grey_placeholder_is_a_placeholder(self):
        # All grey; 200 of 256 grey; 199; within 3; 4 off; the cream of an
        # empty street tile; open sea; transparent.
        self.assertEqual(self.run_page()["grey"],
                         [True, True, False, True, False, False, False, False])

    def test_a_map_layer_has_no_imager_frame_to_draw_a_storm_at(self):
        # Under a street map a storm is drawn at the clock's time. Asking the
        # map for an imager's frame threw, and took every storm mark with it.
        self.assertIsNone(self.run_page()["source"])

    def test_a_placeholder_is_drawn_from_the_nearest_tile_esri_has(self):
        out = self.run_page()["fallback"]
        self.assertEqual(out[0], {"z": 14, "c": 25, "r": 50})
        # The neighbour's parent at 15 is a placeholder, so it has nothing either.
        self.assertEqual(out[1], {"z": 14, "c": 25, "r": 50})
        self.assertEqual(out[2], {"z": 14, "c": 25 - 16384, "r": 50})


class TestCompositeOnTheMap(_DeskFixtures, unittest.TestCase):
    """The atlas's composites, on the map, drawn as the atlas draws them."""

    def data(self, html):
        raw = re.search(r'<script id="desk-data" type="application/json">(.*?)</script>',
                        html, re.S).group(1)
        return json.loads(raw)

    def test_the_season_shown_first_is_the_one_containing_the_build_date(self):
        self.assertEqual(worldmap.season_of(date(2026, 9, 28)), "SON")
        for month, season in ((12, "DJF"), (1, "DJF"), (2, "DJF"), (3, "MAM"),
                              (6, "JJA"), (8, "JJA"), (11, "SON")):
            self.assertEqual(worldmap.season_of(date(2026, month, 5)), season)
        self.assertEqual([worldmap.next_season(s) for s in atlas.SEASONS],
                         ["MAM", "JJA", "SON", "DJF"])

    def test_the_page_carries_the_atlas_grids_and_its_rules(self):
        enso = self.data(stormdesk.page(self.state()))["enso"]
        self.assertEqual(enso["grids"], json.loads(json.dumps(atlasview._grid_payload())))
        self.assertEqual((enso["now"], enso["next"]), ("SON", "DJF"))
        self.assertEqual(enso["limits"], {"PRECIP": 3.0, "AIR": 1.6})
        self.assertEqual((enso["opacity"], enso["mask"], enso["fade"]),
                         (0.58, 0.16, [90, 420, 0.42]))
        self.assertEqual(enso["dry_floor"], atlas.DRY_FLOOR)
        self.assertEqual(enso["significant"]["AIR"]["JJA"], 3.182)

    def test_the_full_scale_is_the_atlas_own(self):
        self.assertIn("var LIMIT = { PRECIP: %s, AIR: %s };"
                      % (worldmap.LIMITS["PRECIP"], worldmap.LIMITS["AIR"]), atlasview._JS)
        self.assertIn("var FAINT = %s;" % worldmap.MASK, atlasview._JS)
        self.assertIn("Math.max(0.42, 1 - (px - 90) / 420)", atlasview._JS)

    def test_the_ramp_is_the_pages_own_tokens(self):
        html = stormdesk.page(self.state())
        self.assertIn("--d0:", html)
        self.assertIn('<canvas id="enso-cells"', html)
        self.assertRegex(worldmap.legend(), r'id="enso-key"')

    def test_the_controls_mark_the_season_now_and_next(self):
        controls = worldmap.controls("world", "SON", "DJF")
        self.assertEqual(re.findall(r'data-enso-season="(\w+)"', controls),
                         ["DJF", "MAM", "JJA", "SON"])
        self.assertRegex(controls, r'data-enso-season="SON"[^>]*>SON <span[^>]*>now</span>')
        self.assertRegex(controls, r'data-enso-season="DJF"[^>]*>DJF <span[^>]*>next</span>')
        self.assertEqual(re.findall(r'data-enso-var="(\w*)"', controls), ["PRECIP", "AIR", ""])

    def test_the_map_draws_a_smoothed_field_not_a_cell_per_square(self):
        # Painted cell by cell, the 2.5 degree grid read as a mosaic of pixels.
        script = stormdesk.script()
        body = _js_function(script, "drawComposite")
        self.assertIn("compositeField(", body)
        self.assertIn("imageSmoothingEnabled = true", body)
        self.assertNotIn(".rect(", body)
        self.assertEqual(_js_function(script, "compositeRects"), "")
        # One colour rule, paintField's: no second copy of the atlas's step.
        self.assertEqual(_js_function(script, "rampStep"), "")
        self.assertIn("var GRIDS = {}, RAMP_RGB = [];", script)

    def test_either_theme_switch_reads_the_ramp_again(self):
        # The ramp was read once: switched to dark, the composite stayed in
        # the light theme's colours under the dark theme's legend.
        body = _js_function(worldmap._JS, "rethemed")
        self.assertIn("RAMP_RGB = [];", body)
        self.assertIn("requestRender();", body)
        self.assertIn('attributeFilter: ["data-theme"]', worldmap._JS)
        self.assertIn('matchMedia("(prefers-color-scheme: dark)")', worldmap._JS)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestCompositeOnTheMapRuns(_DeskFixtures, unittest.TestCase):
    """The map's composite functions under node, against the atlas's: the
    cells drawn as a field, blended between their centres, not as squares."""

    MAP = ("clamp", "mx", "my", "rad", "deg", "lonOf", "latOf", "wrap180", "gridAxis",
           "gridPlane", "gridAxes", "nearestAt", "nearestLon", "critOf",
           "cellWeight", "cellPx", "hexRgb", "fieldOf", "fieldGrid", "fieldRow", "fieldCol",
           "fieldAt", "paintField", "compositeField", "fieldStart", "fieldSpan", "fieldStep",
           "cellFits", "cellAt")
    HARNESS = r"""
var TILE = 256, GRIDS = {};
var D = {enso: JSON.parse(require("fs").readFileSync(0, "utf8"))};
var ATLAS = {grids: D.enso.grids};
/*MAP*/
function atlasRamp(value, name) { var D = ATLAS, LIMIT = {PRECIP: 3.0, AIR: 1.6}; /*RAMP*/ return rampIndex(value, name); }
var out = {steps: [], weights: [10, 90, 300, 1000].map(cellWeight),
           px: [cellPx("PRECIP", 1024), cellPx("AIR", 1024)]};
// One cell painted at each value in the map's tone, its red the ramp step.
var STEP = [];
for (var k = 0; k < 11; k++) STEP.push([k, 0, 0]);
["PRECIP", "AIR"].forEach(function (name) {
  for (var v = -5; v <= 5; v += 0.01) {
    var one = paintField(fieldOf([0], [0], [[v]], [[null]], Infinity), [0], [0],
                         {invert: D.enso.grids[name].invert, lim: D.enso.limits[name], rgb: STEP,
                          mask: false, dim: 0});
    out.steps.push([one.data[0], atlasRamp(v, name)]);
  }
});
out.hex = [hexRgb("#0045af"), hexRgb(" #ABC "), hexRgb("rgb(1, 2, 3)"), hexRgb("")];
// A 2.5 degree cell on a 1157 pixel map: 8 pixels at zoom 2.2, 1820 at 10.
// At 60 N, Mercator draws the same cell twice as tall as it is wide.
var EQ = {lat0: -1.25, lat1: 1.25}, N60 = {lat0: 58.75, lat1: 61.25};
out.fits = [cellFits("PRECIP", 1153, 1157, 2000, EQ), cellFits("PRECIP", 262144, 1157, 2000, EQ),
            cellFits("PRECIP", 1157 * 144, 1157, 2000, EQ),
            cellFits("AIR", 1157 * 180 + 1, 1157, 2000, EQ),
            cellFits("PRECIP", 41652, 1157, 500, EQ), cellFits("PRECIP", 41652, 1157, 500, N60)];
out.fieldSteps = [[375, 460], [1157, 561], [1000, 1000], [1920, 900], [3840, 1800]].map(function (s) {
  var step = fieldStep(s[0], s[1]);
  return [step, fieldSpan(s[0], step) * fieldSpan(s[1], step)];
});
// Rainfall's centres are at -88.75 + 2.5 r N and 1.25 + 2.5 c E: row 36 is
// 1.25 N, row 37 3.75 N; columns 71 and 72 are 178.75 E and 181.25 E, either
// side of the date line; 143 and 0 are 358.75 E and 1.25 E, either side of
// Greenwich; row 71 is 88.75 N, the last.
var P = fieldGrid("PRECIP", "DJF"), pd = gridPlane("PRECIP", "DJF", "diff");
var pt = gridPlane("PRECIP", "DJF", "t"), pc = critOf("PRECIP", "DJF");
out.cells = {a: pd[36][71], b: pd[36][72], c: pd[37][71], d: pd[37][72], w: pd[36][143], e: pd[36][0],
             top: [pd[71][4], pd[71][5]]};
out.at = {centre: fieldAt(P, 181.25, 1.25), sig: Math.abs(pt[36][72]) >= pc ? 1 : 0,
          dateline: [fieldAt(P, 180, 1.25), fieldAt(P, -180, 1.25), fieldAt(P, 540, 1.25)],
          greenwich: [fieldAt(P, 0, 1.25), fieldAt(P, 360, 1.25), fieldAt(P, -360, 1.25)],
          north: fieldAt(P, 181.25, 2.5), corner: fieldAt(P, 180, 2.5),
          pole: fieldAt(P, 12.5, 89.9)};
out.seam = [-80, -40, 0, 40, 80].map(function (lat) {
  return [fieldAt(P, 179.9999, lat).value, fieldAt(P, -179.9999, lat).value];
});
// A cell the t test passes beside one it does not: half and half between.
out.halfsig = null;
for (var r = 20; r < 52 && !out.halfsig; r++) for (var c = 0; c + 1 < 144; c++) {
  var yes = pt[r][c] !== null && Math.abs(pt[r][c]) >= pc;
  var no = !(pt[r][c + 1] !== null && Math.abs(pt[r][c + 1]) >= pc);
  if (yes && no) { out.halfsig = fieldAt(P, 2.5 + 2.5 * c, -88.75 + 2.5 * r); break; }
}
// Temperature is land only: a coast is a cell with a record beside one without.
var A = fieldGrid("AIR", "DJF"), ad = gridPlane("AIR", "DJF", "diff"), aax = gridAxes("AIR");
out.coast = null;
for (var r = 10; r < 80 && !out.coast; r++) for (var c = 0; c + 1 < aax[1].length; c++) {
  if (ad[r][c] !== null && ad[r][c + 1] === null) {
    out.coast = {cell: ad[r][c], at: fieldAt(A, aax[1][c] + 1, aax[0][r])};
    break;
  }
}
out.sea = fieldAt(A, -150, 0);
// Whole views, pixel by pixel, against fieldAt at each pixel's centre.
var RGB = [];
for (var k = 0; k < 11; k++) RGB.push([k * 20, 255 - k * 20, 7 * k]);
function check(name, mask, o, w, h, step) {
  var f = compositeField(name, "DJF", mask, o, w, h, step, RGB, D.enso.mask), g = fieldGrid(name, "DJF");
  var n = {w: f.w, h: f.h, drawn: 0, clear: 0, faint: 0, bad: 0, first: null};
  for (var j = 0; j < f.h; j++) for (var i = 0; i < f.w; i++) {
    var X = (f.x + (i + 0.5) * step - o.left) / o.W, Y = (f.y + (j + 0.5) * step - o.top) / o.W;
    var k = (j * f.w + i) * 4, want = [0, 0, 0, 0];
    if (Y >= 0 && Y <= 1) {
      var at = fieldAt(g, lonOf(X), latOf(Y));
      if (at.cover > 0) {
        var rgb = RGB[atlasRamp(at.value, name)];
        var a = at.cover * (mask ? D.enso.mask + (1 - D.enso.mask) * at.sig : 1);
        want = [rgb[0], rgb[1], rgb[2], Math.round(a * 255)];
      }
    }
    var got = [f.data[k], f.data[k + 1], f.data[k + 2], f.data[k + 3]];
    if (want[3] === 0 ? got[3] !== 0 : got.join() !== want.join()) {
      n.bad++;
      if (!n.first) n.first = [i, j, got, want];
    }
    if (want[3] === 0) n.clear++; else n.drawn++;
    if (want[3] > 0 && want[3] < 255) n.faint++;
  }
  return n;
}
// 1024 by 512 at zoom 2: centred on 180, so the date line is at screen
// x = 512; centred on 0 for Greenwich; and a world of 256 pixels, four times
// across, with room above and below it.
out.views = {
  dateline: check("PRECIP", true, {W: 1024, left: -512, top: -256}, 1024, 512, 2),
  greenwich: check("AIR", true, {W: 1024, left: 0, top: -256}, 1024, 512, 2),
  unmasked: check("PRECIP", false, {W: 1024, left: -512, top: -256}, 1024, 512, 3),
  small: check("PRECIP", true, {W: 256, left: 0, top: 128}, 1024, 512, 2)
};
// The world a pixel to the right and a pixel down: the same field on the
// same ground, drawn a pixel over, not a lattice slid across the world.
var before = compositeField("PRECIP", "DJF", true, {W: 1024, left: -512, top: -256}, 1024, 512, 2,
                            RGB, D.enso.mask);
var after = compositeField("PRECIP", "DJF", true, {W: 1024, left: -511, top: -255}, 1024, 512, 2,
                           RGB, D.enso.mask);
out.pan = {same: before.data.join() === after.data.join(), size: [after.w, after.h],
           moved: [after.x - before.x, after.y - before.y]};
var reused = new Uint8ClampedArray(513 * 257 * 4).fill(9);
out.reused = compositeField("PRECIP", "DJF", true, {W: 256, left: 0, top: 128}, 1024, 512, 2,
                            RGB, D.enso.mask, reused).data === reused;
out.cleared = reused[0] === 0 && reused[3] === 0;
out.london = cellAt("AIR", "DJF", -0.13, 51.5);
out.dateline = [cellAt("AIR", "DJF", 180.9, 65.8), cellAt("AIR", "DJF", -179.5, 65.8),
                cellAt("AIR", "DJF", 179.1, 65.8)];
console.log(JSON.stringify(out));
"""
    _out = None

    def run_page(self):
        if TestCompositeOnTheMapRuns._out is None:
            script = stormdesk.script()
            harness = (self.HARNESS
                       .replace("/*MAP*/", "\n".join(_js_function(script, n) for n in self.MAP))
                       .replace("/*RAMP*/", _js_function(atlasview._JS, "rampIndex")))
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "composite.js"
                path.write_text(harness, encoding="utf-8")
                done = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                      timeout=120,
                                      input=json.dumps(worldmap.payload(self.state())))
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            TestCompositeOnTheMapRuns._out = json.loads(done.stdout)
        return TestCompositeOnTheMapRuns._out

    def test_every_value_takes_the_atlas_colour_step(self):
        steps = self.run_page()["steps"]
        self.assertGreaterEqual(len(steps), 2000)
        self.assertEqual([mine for mine, _ in steps], [theirs for _, theirs in steps])

    def test_a_cell_fades_as_the_atlas_fades_it(self):
        self.assertEqual(self.run_page()["weights"], [1, 1, 0.5, 0.42])

    def test_a_cell_is_measured_across_as_the_map_draws_it(self):
        px = self.run_page()["px"]
        self.assertAlmostEqual(px[0], 1024 * 2.5 / 360, places=9)
        self.assertAlmostEqual(px[1], 1024 * 2.0 / 360, places=9)

    def test_a_ramp_token_is_read_as_numbers(self):
        self.assertEqual(self.run_page()["hex"],
                         [[0, 69, 175], [170, 187, 204], [1, 2, 3], [136, 136, 136]])

    def test_the_cell_under_the_pin_is_outlined_only_while_it_fits_the_view(self):
        # Close in, the outline of a cell wider than the map was one straight
        # line across the streets, with no edge of colour beside it any more.
        # Nor is it while taller than the map: far north, Mercator stretches
        # the cell up, and its outline was two lone lines down the streets.
        self.assertEqual(self.run_page()["fits"], [True, False, True, False, True, False])
        body = _js_function(stormdesk.script(), "drawComposite")
        self.assertIn("var pin = S.pin ? cellAt(name, S.enso.season, S.pin.lon, S.pin.lat) : null;",
                      body)
        self.assertIn('svgEl.classList.toggle("bigcell", !!pin && !cellFits(name, o.W, S.w, S.h, pin));',
                      body)
        self.assertRegex(worldmap.css(),
                         r"#overlay\.bigcell \.pinned, #overlay\.bigcell \.pinnedcase \{ display: none; \}")

    def test_the_field_is_worked_out_on_no_more_than_a_quarter_million_points(self):
        # Every point costs a blend, every frame the map moves: at 2 css
        # pixels a 1920 by 900 map took 8 ms under node. Two pixels apart is
        # the finest; a bigger map is worked out coarser.
        steps = self.run_page()["fieldSteps"]
        self.assertEqual([step for step, _ in steps], [2, 2, 3, 3, 6])
        for _, points in steps:
            self.assertLessEqual(points, 250000)

    def test_at_a_cell_centre_the_field_is_the_cell(self):
        out = self.run_page()
        centre = out["at"]["centre"]
        self.assertAlmostEqual(centre["value"], out["cells"]["b"], places=9)
        self.assertEqual(centre["cover"], 1)
        self.assertEqual(centre["sig"], out["at"]["sig"])

    def test_between_centres_the_field_blends_the_cells(self):
        out = self.run_page()
        cells, at = out["cells"], out["at"]
        self.assertAlmostEqual(at["north"]["value"], (cells["b"] + cells["d"]) / 2, places=9)
        self.assertAlmostEqual(at["corner"]["value"],
                               (cells["a"] + cells["b"] + cells["c"] + cells["d"]) / 4, places=9)

    def test_the_field_runs_across_the_date_line_and_greenwich_unbroken(self):
        out = self.run_page()
        cells, at = out["cells"], out["at"]
        for got in at["dateline"]:
            self.assertAlmostEqual(got["value"], (cells["a"] + cells["b"]) / 2, places=9)
        for got in at["greenwich"]:
            self.assertAlmostEqual(got["value"], (cells["w"] + cells["e"]) / 2, places=9)
        for east, west in out["seam"]:
            self.assertAlmostEqual(east, west, places=3)

    def test_past_the_last_centres_the_field_keeps_the_last_row(self):
        out = self.run_page()
        self.assertAlmostEqual(out["at"]["pole"]["value"], sum(out["cells"]["top"]) / 2, places=9)

    def test_a_cell_with_no_record_takes_no_part_and_the_coast_fades(self):
        out = self.run_page()
        coast = out["coast"]
        self.assertIsNotNone(coast)
        self.assertAlmostEqual(coast["at"]["value"], coast["cell"], places=9)
        self.assertAlmostEqual(coast["at"]["cover"], 0.5, places=9)
        self.assertEqual(out["sea"]["cover"], 0)
        self.assertIsNone(out["sea"]["value"])

    def test_the_mask_fades_out_where_the_cells_stop_passing(self):
        half = self.run_page()["halfsig"]
        self.assertIsNotNone(half)
        self.assertAlmostEqual(half["sig"], 0.5, places=9)
        self.assertEqual(half["cover"], 1)

    def test_every_pixel_is_the_field_at_its_centre(self):
        views = self.run_page()["views"]
        for name, view in views.items():
            self.assertEqual(view["bad"], 0, (name, view["first"]))
            self.assertGreater(view["drawn"], 1000, name)
        # A point more each way than the page needs: the lattice is fixed to
        # the world, so its first point is up to a step before the page's edge.
        self.assertEqual((views["dateline"]["w"], views["dateline"]["h"]), (513, 257))
        self.assertEqual((views["unmasked"]["w"], views["unmasked"]["h"]), (343, 172))
        # The mask draws faint what the t test does not pass; without it, nothing is.
        self.assertGreater(views["dateline"]["faint"], 1000)
        self.assertEqual(views["unmasked"]["faint"], 0)
        # Temperature is land only: the sea is left clear.
        self.assertGreater(views["greenwich"]["clear"], 10000)

    def test_off_the_top_and_bottom_of_the_world_nothing_is_drawn(self):
        small = self.run_page()["views"]["small"]
        self.assertEqual(small["bad"], 0, small["first"])
        # The world is rows 65 to 192 of the field's 257: the other 129 are clear.
        self.assertEqual(small["clear"], 513 * 129)

    def test_the_field_holds_still_on_the_ground_as_the_view_pans(self):
        # Worked out from the page's corner, the lattice slid over the world
        # as the map panned, and the steps' edges shimmered under the reader.
        pan = self.run_page()["pan"]
        self.assertTrue(pan["same"])
        self.assertEqual(pan["size"], [513, 257])
        self.assertEqual(pan["moved"], [1, 1])

    def test_a_buffer_passed_in_is_filled_afresh(self):
        out = self.run_page()
        self.assertTrue(out["reused"])
        self.assertTrue(out["cleared"])

    def test_the_date_line_cell_reads_as_one_cell_from_either_side(self):
        # 65.8 N is Chukotka, land either side of the date line.
        east, west, near = self.run_page()["dateline"]
        for cell in (east, west):
            self.assertAlmostEqual(cell["lon0"], 179.25, places=9)
            self.assertAlmostEqual(cell["lon1"], -178.75, places=9)
        self.assertIsNotNone(east["value"])
        self.assertEqual(east["value"], west["value"])
        self.assertEqual(east["value"], atlas.sample("AIR", "DJF", -179.5, 65.8).value)
        self.assertAlmostEqual(near["lon0"], 177.25, places=9)
        self.assertAlmostEqual(near["lon1"], 179.25, places=9)

    def test_london_reads_its_own_cell_not_the_one_across_greenwich(self):
        london = self.run_page()["london"]
        self.assertAlmostEqual(london["lon0"], -0.75, places=9)
        self.assertAlmostEqual(london["lon1"], 1.25, places=9)
        self.assertEqual(london["value"], atlas.sample("AIR", "DJF", -0.13, 51.5).value)

class TestEnsoHere(unittest.TestCase):
    """One point, as the map says it: the verdict worded once for every surface."""

    def test_the_verdict_is_worded_once_for_every_surface(self):
        cell = atlas.Cell(value=0.5, base=2.0, t=3.0, crit=2.262)
        self.assertEqual(atlas.verdict("PRECIP", cell), "wetter")
        self.assertEqual(atlas.verdict("AIR", cell), "warmer")
        self.assertEqual(atlas.verdict("AIR", dataclasses.replace(cell, value=-0.5, t=-3.0)),
                         "cooler")
        self.assertEqual(atlas.verdict("PRECIP", dataclasses.replace(cell, t=1.0)),
                         "no clear signal")
        self.assertEqual(atlas.verdict("AIR", atlas.Cell(None, None, None)), "no record")

    def test_the_table_wraps_inside_the_panel(self):
        # The dashboard's shell keeps every table cell on one line; this
        # table's sentences ran to 800 px in a 364 px panel on 28 Sep 2026.
        rule = re.search(r"\.ensohere th, \.ensohere td \{([^}]*)\}", worldmap.css())
        self.assertIsNotNone(rule)
        self.assertIn("white-space: normal", rule.group(1))

    def test_here_says_what_el_nino_does_after_the_storms(self):
        body = _js_function(stormdesk._JS, "showHere")
        self.assertLess(body.index("Who warns here"), body.index("ensoHereHtml("))
        self.assertLess(body.index("ensoHereHtml("), body.index("atlas.html#at="))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestEnsoHereRuns(_DeskFixtures, unittest.TestCase):
    """What the map says of a point, against atlas.sample, cell for cell."""

    NAMES = ("clamp", "wrap180", "gridAxis", "gridPlane", "gridAxes", "nearestAt",
             "nearestLon", "critOf", "cellAt", "verdictOf", "percentOf")
    LONS = [x / 10 for x in range(-1799, 1800, 121)] + [-0.13, -0.5, 0.0, 179.9, -179.9,
                                                        180.0, -180.0, 359.5]
    LATS = [y / 10 for y in range(-890, 891, 113)] + [0.0, 51.5, -12.05, 88.9, -88.9]

    def test_every_point_reads_what_python_reads(self):
        points = [(lon, lat) for lon in self.LONS for lat in self.LATS]
        harness = (
            "var GRIDS = {};\nvar D = {enso: %s};\n%s\nvar out = [];\n"
            "var P = %s;\n['PRECIP', 'AIR'].forEach(function (n) {\n"
            " D.enso.seasons.forEach(function (s) {\n"
            "  P.forEach(function (p) { var c = cellAt(n, s, p[0], p[1]);\n"
            "   out.push([c.value, c.base, c.t, c.lon0, c.lon1, c.lat0, c.lat1,\n"
            "             verdictOf(n, c), percentOf(n, c)]); }); }); });\n"
            "console.log(JSON.stringify(out));"
            % (json.dumps(worldmap.payload(self.state())),
               "\n".join(_js_function(worldmap._JS, n) for n in self.NAMES),
               json.dumps(points)))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "here.js"
            path.write_text(harness, encoding="utf-8")
            done = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                  timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        got = iter(json.loads(done.stdout))
        for name in ("PRECIP", "AIR"):
            for season in atlas.SEASONS:
                for lon, lat in points:
                    cell = atlas.sample(name, season, lon, lat)
                    js = next(got)
                    where = (name, season, lon, lat)
                    self.assertEqual(js[:3], [cell.value, cell.base, cell.t], where)
                    for mine, theirs in zip(js[3:7], (cell.lon0, cell.lon1, cell.lat0,
                                                      cell.lat1)):
                        self.assertAlmostEqual(mine, theirs, places=9, msg=where)
                    self.assertEqual(js[7], atlas.verdict(name, cell), where)
                    pct = cell.percent if name == "PRECIP" else None
                    if pct is None:
                        self.assertIsNone(js[8], where)
                    else:
                        self.assertAlmostEqual(js[8], pct, places=9, msg=where)

    def test_the_impact_regions_carry_whether_this_event_puts_them_in_play(self):
        links = worldmap.payload(self.state())["links"]
        self.assertEqual({l["status"] for l in links}, {""})    # no impacts in the fixture
        self.assertEqual([l["region"] for l in links],
                         [l["region"] for l in atlasview._links_payload()])

    HERE = ("esc", "rad", "clamp", "wrap180", "gridAxis", "gridPlane", "gridAxes",
            "nearestAt", "nearestLon", "critOf", "cellAt", "verdictOf", "percentOf",
            "regionsAt", "ensoHere", "signedText", "ensoCellText", "ensoHereHtml")

    def _here(self, body: str):
        script = stormdesk.script()
        harness = "var GRIDS = {};\nvar D = {enso: %s};\n%s\n%s" % (
            json.dumps(worldmap.payload(self.state())),
            "\n".join(_js_function(script, n) for n in self.HERE), body)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "here.js"
            path.write_text(harness, encoding="utf-8")
            done = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=300)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_the_regions_at_a_point_are_the_footprints_that_cover_it(self):
        points = [(lon, lat) for lon in range(-180, 181, 9) for lat in range(-60, 61, 8)]
        points += [(-77.03, -12.05), (190.0, -10.0), (-190.0, 10.0)]
        got = self._here("console.log(JSON.stringify(%s.map(function (p) {\n"
                         " return regionsAt(p[0], p[1]).map(function (l) { return l.region; });\n"
                         "})));" % json.dumps(points))
        rank = {"regional": 0, "basin": 1, "global": 2}
        for (lon, lat), regions in zip(points, got):
            w, found = geo.wrap180(lon), []
            for row in atlasview._links_payload():
                areas = [(b[1] - b[0]) * (b[3] - b[2]) for b in row["boxes"]
                         if b[0] <= w <= b[1] and b[2] <= lat <= b[3]]
                if areas:
                    found.append((rank[row["scope"]], min(areas), row["region"]))
            want = [region for _, _, region in sorted(found, key=lambda f: f[:2])]
            self.assertEqual(regions, want, (lon, lat))
        self.assertTrue(any(len(regions) > 1 for regions in got))

    def test_here_reads_every_season_and_the_record_behind_it(self):
        lima, sea = (-77.03, -12.05), (-140.0, -40.0)
        land_html, sea_html, sizes = self._here(
            "var h = ensoHere(%r, %r);\nconsole.log(JSON.stringify([ensoHereHtml(h),\n"
            " ensoHereHtml(ensoHere(%r, %r)), h.sizes]));" % (*lima, *sea))
        payload = worldmap.payload(self.state())
        self.assertIn("<h4>El Niño here</h4>", land_html)
        self.assertIn("not this season’s forecast", land_html)
        self.assertEqual(land_html.count('<tr><th scope="row">'), len(atlas.SEASONS))
        self.assertIn(payload["now"] + " (now)", land_html)
        self.assertIn(payload["next"] + " (next)", land_html)
        for season in atlas.SEASONS:
            cell = atlas.sample("PRECIP", season, *lima)
            sign = "+" if cell.value > 0 else "−" if cell.value < 0 else ""
            said = "%s%.2f mm/day against an ordinary %.2f" % (sign, abs(cell.value), cell.base)
            self.assertIn(said, land_html, season)
            self.assertIn(": <b>%s</b>" % atlas.verdict("PRECIP", cell), land_html, season)
        self.assertIn("<details><summary>Events sampled</summary>", land_html)
        self.assertIn("Documented effects here", land_html)
        self.assertIn("Everywhere:", land_html)
        self.assertTrue(all(atlas.sample("AIR", s, *sea).value is None for s in atlas.SEASONS))
        self.assertEqual(sea_html.count("no record: the temperature grid is land only"),
                         len(atlas.SEASONS))
        self.assertAlmostEqual(sizes["PRECIP"]["dx"], 2.5)
        self.assertAlmostEqual(sizes["PRECIP"]["kmx"],
                               2.5 * 111.32 * math.cos(math.radians(lima[1])), places=6)
        self.assertAlmostEqual(sizes["AIR"]["kmy"], sizes["AIR"]["dy"] * 110.57, places=6)


class TestEnsoTiles(_DeskFixtures, unittest.TestCase):
    """Today's ocean and the last three days' floods: NASA's own tiles and colours."""

    def test_the_tiles_are_gibs_web_mercator_layers_as_listed(self):
        sst, floods = worldmap.ENSO_TILES
        self.assertEqual((sst["id"], sst["global"], sst["tms"], sst["format"], sst["step"]),
                         ("sst", "GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies",
                          "GoogleMapsCompatible_Level7", "png", "P1D"))
        self.assertEqual((floods["id"], floods["global"], floods["tms"], floods["format"]),
                         ("floods", "MODIS_Combined_Flood_3-Day",
                          "GoogleMapsCompatible_Level9", "png"))
        self.assertEqual(worldmap.HIDE_ABOVE, 12)

    def test_nasas_sst_colour_map_is_carried_bin_for_bin(self):
        bins = worldmap.SST_COLOURS
        self.assertEqual(len(bins), 62)
        self.assertEqual(bins[0], (None, -3.0, (107, 0, 219)))
        self.assertEqual(bins[1], (-3.0, -2.9, (116, 0, 214)))
        self.assertIsNone(bins[-1][1])
        for (lo, hi, _), (lo2, _, _) in zip(bins, bins[1:]):
            self.assertAlmostEqual(hi, lo2)
        labels = [e["label"] for e in worldmap.payload(self.state())["colours"]["sst"]]
        self.assertEqual(labels[0], "below −3.0 °C")
        self.assertIn("+1.2 to +1.3 °C", labels)
        self.assertIn("−0.1 to 0.0 °C", labels)
        self.assertEqual(labels[-1], "+3.0 °C or more")

    def test_the_flood_classes_are_modis_own(self):
        self.assertEqual(worldmap.FLOOD_CLASSES, (
            ((50, 210, 245), "Surface water"), ((255, 255, 0), "Recurring flood"),
            ((250, 30, 36), "Flood"), ((175, 175, 175), "Insufficient data")))

    def test_the_tiles_can_be_switched_on_and_are_off_until_then(self):
        controls = worldmap.controls("world", "SON", "DJF")
        for key in ("sst", "floods"):
            box = re.search(r'<input type="checkbox"[^>]*data-enso-tile="%s"[^>]*>' % key,
                            controls).group(0)
            self.assertNotIn("checked", box)
        self.assertIn('id="enso-tiles"', stormdesk.page(self.state()))

    def test_nasas_tiles_have_their_own_strength(self):
        # The slider was the composite's alone; the tiles stood at 0.8.
        controls = worldmap.controls("world", "SON", "DJF")
        today = controls[controls.index("Today, from NASA"):controls.index("Regions")]
        self.assertIn('<input type="range" id="enso-tile-opacity" min="0.2" max="1" '
                      'step="0.05" value="0.8">', today)
        self.assertEqual(worldmap.payload(self.state())["tile_opacity"], 0.8)

    def test_the_tiles_are_drawn_read_back_and_credited(self):
        self.assertIn("drawPane(panes.e, ensoTileSpecs(), moving)", _js_function(stormdesk._JS, "tiles"))
        here = _js_function(stormdesk._JS, "showHere")
        self.assertLess(here.index("ensoHereHtml("), here.index("ensoTodayHtml(S.here.lon, S.here.lat)"))
        # Today's value is read into Here once Here is written.
        self.assertLess(here.index('hereWrite(box, html.join(""))'), here.index("ensoTodayRead(S.here.lon, S.here.lat)"))
        self.assertIn("ensoTileMore()", _js_function(stormdesk._JS, "pills"))
        self.assertIn("from(panes.e", _js_function(stormdesk._JS, "credit"))
        self.assertIn("crossOrigin", _js_function(worldmap._JS, "readEnso"))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestEnsoTilesRuns(_DeskFixtures, unittest.TestCase):
    """A pixel of NASA's tile read back to the bin or class it was painted from."""

    def run_js(self, script):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "tiles.js"
            path.write_text(script, encoding="utf-8")
            done = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_every_colour_reads_back_to_its_own_bin(self):
        colours = worldmap.payload(self.state())["colours"]
        for key in ("sst", "floods"):
            entries = colours[key]
            pixels = ([e["rgb"] + [255] for e in entries]
                      + [[c + 1 for c in e["rgb"]] + [255] for e in entries]
                      + [[0, 0, 0, 0], [0, 255, 0, 255]])
            got = self.run_js("%s\nvar E = %s;\nconsole.log(JSON.stringify(%s.map(function (p) {"
                              " return classify(E, p); })));"
                              % (_js_function(worldmap._JS, "classify"), json.dumps(entries),
                                 json.dumps(pixels)))
            n = len(entries)
            self.assertEqual(got[:n], entries, key)
            self.assertEqual(got[n:2 * n], entries, key)
            self.assertEqual(got[-2], {"transparent": True}, key)
            self.assertIsNone(got[-1], key)

    def test_the_tiles_hide_past_zoom_12_and_say_how_coarse_they_would_be(self):
        layers = [worldmap.ENSO_TILES[0], dict(worldmap.ENSO_TILES[1])]
        got = self.run_js(
            "var S = {z: 0, enso: {tiles: {sst: true, floods: false}}};\n"
            "var D = {enso: {hide_above: 12}, layers: %s};\n"
            "function cells(id, frame) { return {cells: [id + '@' + frame]}; }\n%s\n%s\n"
            "var out = [];\n[3, 12].forEach(function (z) { S.z = z; out.push(ensoTileSpecs()); });\n"
            "S.enso.tiles.floods = true; S.z = 12; out.push(ensoTileSpecs());\n"
            "S.z = 12.2; out.push(ensoTileSpecs());\n"
            "S.z = 13; out.push(ensoHiddenText(D.layers[0]), ensoHiddenText(D.layers[1]));\n"
            "console.log(JSON.stringify(out));"
            % (json.dumps(layers), _js_function(worldmap._JS, "ensoTileSpecs"),
               _js_function(worldmap._JS, "ensoHiddenText")))
        sst = {"key": "sst", "cells": ["sst@0"], "visible": True, "z": 0}
        floods = {"key": "floods", "cells": ["floods@0"], "visible": True, "z": 1}
        self.assertEqual(got[:4], [[sst], [sst], [sst, floods], []])
        self.assertEqual(got[4], "Ocean today hidden past zoom 12: its 1 km pixels would be "
                                 "64 screen pixels across.")
        self.assertEqual(got[5], "Floods, last 3 days hidden past zoom 12: its 250 m pixels "
                                 "would be 16 screen pixels across.")

    def test_modis_context_classes_are_drawn_faint(self):
        # MODIS granules come back as whole squares of "surface water" (the sea
        # itself, near coasts) and of cloud-bound "insufficient data", over the
        # ocean too; drawn at full strength they hide the sea beneath. Floods
        # and recurring floods stay at full strength.
        floods = worldmap.ENSO_TILES[1]
        self.assertEqual(floods["faint"], [[50, 210, 245], [175, 175, 175]])
        self.assertNotIn("faint", worldmap.ENSO_TILES[0])
        got = self.run_js(
            "%s\nvar px = new Uint8ClampedArray([175, 175, 175, 255, 250, 30, 36, 255,"
            " 176, 174, 175, 255, 175, 175, 175, 0, 50, 210, 245, 255, 255, 255, 0, 255]);\n"
            "var n = fadePixels(px, %s, %r);\n"
            "console.log(JSON.stringify([n, Array.from(px)]));"
            % (_js_function(worldmap._JS, "fadePixels"), json.dumps(floods["faint"]),
               worldmap.FAINT))
        self.assertEqual(got, [3, [175, 175, 175, 51, 250, 30, 36, 255, 176, 174, 175, 51,
                                   175, 175, 175, 0, 50, 210, 245, 51, 255, 255, 0, 255]])
        loaded = _js_function(stormdesk._JS, "tileLoaded")
        self.assertIn("this._faint && !this._faded && fadeTile(this)", loaded)
        self.assertIn("img._faint = cell.faint", stormdesk._JS)


class TestEnsoNow(_DeskFixtures, unittest.TestCase):
    """Where the event stands this run, and the regions drawn with it."""

    def test_a_run_missing_its_index_still_builds_and_says_so(self):
        section = worldmap.section(self.state())
        self.assertIn('id="enso-now"', section)
        self.assertIn("did not arrive this run", section)
        boxes = worldmap.payload(self.state())["boxes"]
        self.assertEqual([b["key"] for b in boxes], ["nino4", "nino34", "nino3", "nino12"])
        self.assertEqual({b["anomaly"] for b in boxes}, {None})
        self.assertIn("El Ni", stormdesk.page(self.state(), focus="world"))

    def test_the_boxes_are_cpcs(self):
        box = {b["key"]: b for b in worldmap.payload(self.state())["boxes"]}["nino34"]
        self.assertEqual((box["lon0"], box["lon1"], box["lat0"], box["lat1"]),
                         (190.0, 240.0, -5.0, 5.0))
        self.assertEqual(box["label"], "Niño 3.4")

    def test_every_missing_piece_is_one_sentence(self):
        section = worldmap.section(self.state())
        for said in ("The index did not arrive this run.", "No weekly SSTs arrived this run.",
                     "No forecast this run.", "The impact outlook did not run."):
            self.assertEqual(section.count(said), 1, said)
        self.assertIn('<dl class="facts">', section)

    def test_the_nino_boxes_are_on_for_the_map_and_the_impact_regions_wait_to_be_asked(self):
        # Twenty-odd grey boxes over the composite read as more big pixels:
        # the regions are drawn when ticked, or one at a time from Show.
        for focus, boxes in (("world", True), ("storms", False)):
            controls = worldmap.controls(focus, "SON", "DJF")
            for key, checked in (("boxes", boxes), ("regions", False)):
                box = re.search(r'<input type="checkbox"[^>]*data-enso-geo="%s"[^>]*>' % key,
                                controls).group(0)
                self.assertEqual("checked" in box, checked, (focus, key))

    def test_show_is_offered_for_a_place_and_is_a_toggle(self):
        # The global effects have no box: their Show flew out to the whole
        # world and drew nothing there.
        def item(region):
            return worldmap._impact_item(SimpleNamespace(
                link=SimpleNamespace(region=region, effect="An effect"),
                likelihood="likely", timing="this winter"))
        for region in ("Canada and the northern United States", "Atlantic hurricane season"):
            self.assertIn('data-show-region="%s" aria-pressed="false">Show</button>' % region,
                          item(region))
        for region in ("Global mean surface temperature", "Atlantis"):
            self.assertNotIn("data-show-region", item(region))
            self.assertIn("An effect", item(region))

    def test_ticking_the_regions_on_or_off_ends_a_region_shown_alone(self):
        self.assertIn('if (key === "regions") patch.shown = null;', worldmap._JS)
        self.assertIn("shown: null", worldmap._JS)

    def test_the_section_sits_after_here_on_the_map_and_after_the_outlook_on_the_desk(self):
        world = stormdesk.page(self.state(), focus="world")
        self.assertLess(world.index('id="here"'), world.index('id="enso-now"'))
        self.assertLess(world.index('id="enso-now"'), world.index('id="storm-list"'))
        storms = stormdesk.page(self.state())
        self.assertLess(storms.index('id="outlook-list"'), storms.index('id="enso-now"'))
        self.assertLess(storms.index('id="enso-now"'), storms.index('id="actions"'))

    def test_the_shapes_are_drawn_labelled_and_flown_to(self):
        self.assertIn("ensoGeo()", _js_function(stormdesk._JS, "buildGeo").split("\n")[2])
        self.assertIn("ensoLabels(sx, sy, off, label)", _js_function(stormdesk._JS, "drawMarks"))
        self.assertIn("dirty()", _js_function(stormdesk._JS, "pin"))
        self.assertIn('showRegion(el.getAttribute("data-show-region"))', stormdesk._JS)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestEnsoShapesRuns(_DeskFixtures, unittest.TestCase):
    """The boxes drawn as the desk draws everything: in world units, eastward."""

    def run_js(self, body):
        script = "var UNIT = 1048576, geoLo = 0, geoHi = 0;\n%s\n%s" % (
            "\n".join(_js_function(stormdesk.script(), n)
                      for n in ("mx", "my", "rad", "clamp", "X", "Y", "boxPath", "regionBox")),
            body)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shapes.js"
            path.write_text(script, encoding="utf-8")
            done = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_nino_4_runs_east_across_the_date_line(self):
        unit = 1048576
        d = self.run_js("console.log(JSON.stringify(boxPath(160, 210, -5, 5, 0)));")
        xs = [int(v) for v in re.findall(r"[MH](-?\d+)", d)]
        self.assertEqual(len(xs), 3)
        self.assertAlmostEqual(xs[1] - xs[0], round(50 / 360 * unit), delta=1)
        self.assertEqual(xs[0], xs[2])
        self.assertTrue(all(0 < x < 2 * unit for x in xs))

    def test_the_geometry_draws_what_is_switched_on(self):
        links = worldmap.payload(self.state())["links"]
        links[0] = dict(links[0], status="in play")
        glob = [l for l in links if l["scope"] == "global"]
        self.assertTrue(glob)
        body = ("var S = {enso: {regions: true, boxes: true, variable: null, season: 'SON'}, pin: null};\n"
                "var D = {enso: {links: %s, boxes: %s}};\n"
                "function near(x) { return 0; }\n"
                "function cellAt() { return {lon0: 178.75, lon1: -178.75, lat0: -1.25, lat1: 1.25}; }\n"
                "%s\nvar out = [ensoGeo()];\n"
                "S.enso.variable = 'PRECIP'; out.push(ensoGeo());\n"
                "S.pin = {lon: 180, lat: 0}; out.push(ensoGeo());\n"
                "S.enso.regions = false; S.enso.boxes = false; out.push(ensoGeo());\n"
                "console.log(JSON.stringify(out));"
                % (json.dumps(links), json.dumps(worldmap.payload(self.state())["boxes"]),
                   _js_function(worldmap._JS, "ensoGeo")))
        got = self.run_js(body)
        boxes = sum(len(l["boxes"]) for l in links if l["scope"] != "global")
        self.assertEqual(got[0].count('class="region'), boxes)
        self.assertEqual(got[0].count('class="region play"'), len(links[0]["boxes"]))
        self.assertEqual(got[0].count('class="ninobox"'), 4)
        self.assertEqual(got[0].count('class="ninocase"'), 4)
        self.assertLess(got[0].index('class="ninocase"'), got[0].index('class="ninobox"'))
        self.assertEqual(got[0], got[1])                     # no pin, no cell outline
        self.assertEqual(got[2].count('class="pinned"'), 1)  # the cell across 180, drawn east
        pinned = re.search(r'class="pinned" d="M(\d+) \d+H(\d+)', got[2])
        self.assertAlmostEqual(int(pinned.group(2)) - int(pinned.group(1)), round(2.5 / 360 * 1048576),
                               delta=1)
        self.assertEqual(got[3].count("<path"), 2)           # the outline alone, cased

    def test_a_region_shown_is_drawn_alone_and_every_region_when_ticked(self):
        links = worldmap.payload(self.state())["links"]
        regional = [l for l in links if l["scope"] != "global"]
        shown = regional[3]
        body = ("var S = {enso: {regions: false, boxes: false, shown: %s, variable: null}, pin: null};\n"
                "var D = {enso: {links: %s, boxes: []}};\n"
                "function near(x) { return 0; }\n"
                "%s\nvar out = [ensoGeo()];\n"
                "S.enso.regions = true; out.push(ensoGeo());\n"
                "S.enso.regions = false; S.enso.shown = null; out.push(ensoGeo());\n"
                "console.log(JSON.stringify(out));"
                % (json.dumps(shown["region"]), json.dumps(links),
                   _js_function(worldmap._JS, "ensoGeo")))
        got = self.run_js(body)
        self.assertEqual(got[0].count('class="region'), len(shown["boxes"]))
        self.assertEqual(got[1].count('class="region'), sum(len(l["boxes"]) for l in regional))
        self.assertEqual(got[2], "")

    def test_show_draws_its_region_alone_and_flies_there_and_again_puts_it_away(self):
        # Shown, a region stayed until every region was ticked on and off.
        got = _node_json(self, r"""
var S = {then: null, enso: {regions: false, shown: null}}, calls = [];
var D = {enso: {links: [{region: "Peru", scope: "regional", boxes: [[-82, -75, -15, -3]]}]}};
function thenLeave() { calls.push("leave"); }
function setEnso(p) { calls.push(JSON.stringify(p)); for (var k in p) S.enso[k] = p[k]; }
function viewFor(v) { return v; }
function regionBox(l) { return {x0: 0.27, x1: 0.29, y0: 0.5, y1: 0.54}; }
function animate(v) { calls.push("fly"); }
var map = {getBoundingClientRect: function () { return {top: 10, bottom: 500}; }, scrollIntoView: function () {}};
var window = {innerHeight: 900};
""" + _js_function(worldmap._JS, "showRegion") + r"""
var out = [showRegion("Peru"), S.enso.regions, S.enso.shown, calls.slice()];
out.push(showRegion("Peru"), S.enso.shown, calls.slice(), showRegion("Atlantis"));
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, [True, False, "Peru", ['{"shown":"Peru"}', "fly"],
                               True, None, ['{"shown":"Peru"}', "fly", '{"shown":null}'], False])

    def test_a_show_button_says_whether_its_region_is_shown(self):
        got = _node_json(self, r"""
function button(region) {
  var a = {"data-show-region": region, "aria-pressed": "false"};
  return {a: a, getAttribute: function (k) { return k in a ? a[k] : null; },
          setAttribute: function (k, v) { a[k] = String(v); }};
}
var shows = [button("Peru"), button("Southern Africa")];
var document = {querySelectorAll: function (sel) { return sel === "[data-show-region]" ? shows : []; }};
var S = {then: null, here: null, enso: {variable: null, season: "SON", tiles: {}, shown: null}};
function $() { return null; }
function dirty() {}
function thenLeave() {}
function showHere() {}
""" + _js_function(worldmap._JS, "ensoControls") + _js_function(worldmap._JS, "setEnso") + r"""
function pressed() { return shows.map(function (b) { return b.a["aria-pressed"]; }); }
var out = [];
setEnso({shown: "Peru"}); out.push(pressed());
setEnso({shown: "Southern Africa"}); out.push(pressed());
setEnso({shown: null}); out.push(pressed());
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, [["true", "false"], ["false", "true"], ["false", "false"]])

    def test_a_region_across_the_date_line_is_flown_to_as_one_place(self):
        # The Pacific island states (155E to 155W) and the coral reefs (40E to
        # 150W): each box east of the date line is taken on the far side of it.
        rows = [r for r in atlasview._links_payload() if r["scope"] != "global"
                and any(b[1] == 180.0 for b in r["boxes"])
                and any(b[0] == -180.0 for b in r["boxes"])]
        self.assertEqual(len(rows), 2)
        got = self.run_js("console.log(JSON.stringify(%s.map(regionBox)));" % json.dumps(rows))
        for row, box in zip(rows, got):
            west = min(b[0] for b in row["boxes"] if b[0] > 0)
            east = max(b[1] if b[1] > 0 else b[1] + 360 for b in row["boxes"])
            self.assertAlmostEqual(box["x0"], (west + 180) / 360, places=9, msg=row["region"])
            self.assertAlmostEqual(box["x1"], (east + 180) / 360, places=9, msg=row["region"])
            self.assertLess(box["y0"], box["y1"])


class TestGoogleHere(unittest.TestCase):
    """Google's own map of the point: after El Nino here, on a button, and kept."""

    def test_here_offers_google_after_el_nino_and_before_the_atlas(self):
        body = _js_function(stormdesk._JS, "showHere")
        self.assertLess(body.index("ensoHereHtml("), body.index("googleHtml(h.lat, h.lon, S.z)"))
        self.assertLess(body.index("googleHtml("), body.index("atlas.html#at="))

    def test_a_google_button_opens_its_frame(self):
        selectors = re.findall(r'closest\("([^"]*data-here[^"]*)"\)', stormdesk._JS)
        self.assertEqual(len(selectors), 1)
        self.assertIn("[data-google]", selectors[0])
        self.assertIn('googleFrame(el.getAttribute("data-google"))', stormdesk._JS)

    def test_here_is_written_around_an_open_frame(self):
        # The frame itself is kept, never loaded again: TestTheDeskKeepsThePlace.
        body = _js_function(stormdesk._JS, "showHere")
        self.assertEqual(body.count('hereWrite(box, html.join(""));'), 1)
        self.assertNotIn("innerHTML = html", body)
        self.assertIn("S.google.lon === S.here.lon && S.google.lat === S.here.lat",
                      _js_function(stormdesk._JS, "hereWrite"))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestGoogleHereRuns(unittest.TestCase):
    NAMES = ("wrap180", "googleZoom", "googleEmbed", "googleLinks", "googleHtml")

    def run_page(self, body):
        functions = "\n".join(_js_function(worldmap._JS, n) for n in self.NAMES)
        script = "function esc(v) { return String(v).replace(/&/g, '&amp;').replace(/\"/g, '&quot;'); }\n" \
                 + functions + "\nconsole.log(JSON.stringify(" + body + "));"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "g.js"
            path.write_text(script, encoding="utf-8")
            done = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_google_is_asked_for_its_own_map_satellite_and_street_view(self):
        got = self.run_page("['map', 'satellite', 'street'].map(function (k) {"
                            " return googleEmbed(k, -12.0464, -77.0428, 15.4); })")
        self.assertEqual(got, [
            "https://maps.google.com/maps?q=-12.046400,-77.042800&t=m&z=15&output=embed",
            "https://maps.google.com/maps?q=-12.046400,-77.042800&t=k&z=15&output=embed",
            "https://maps.google.com/maps?layer=c&cbll=-12.046400,-77.042800"
            "&cbp=12,0,0,0,0&output=svembed"])

    def test_the_links_open_google_maps_street_view_and_earth_there(self):
        got = self.run_page("googleLinks(-12.0464, -77.0428, 15.4)")
        self.assertEqual(got, {
            "map": "https://www.google.com/maps/@?api=1&map_action=map"
                   "&center=-12.046400,-77.042800&zoom=15&basemap=roadmap",
            "satellite": "https://www.google.com/maps/@?api=1&map_action=map"
                         "&center=-12.046400,-77.042800&zoom=15&basemap=satellite",
            "street": "https://www.google.com/maps/@?api=1&map_action=pano"
                      "&viewpoint=-12.046400,-77.042800",
            "earth": "https://earth.google.com/web/@-12.046400,-77.042800,0a,18056d,35y,0h,0t,0r"})

    def test_the_zoom_google_is_given_is_one_it_has(self):
        got = self.run_page("[googleZoom(0.4), googleZoom(25), googleLinks(10, 190, 5).map]")
        self.assertEqual(got[:2], [3, 21])
        self.assertIn("center=10.000000,-170.000000", got[2])

    def test_nothing_is_asked_of_google_until_a_button_is_pressed(self):
        html = self.run_page("googleHtml(-12.0464, -77.0428, 15)")
        self.assertNotIn("<iframe", html)
        self.assertIn('data-google="street"', html)
        self.assertIn("&amp;basemap=satellite", html)
        self.assertIn("iframe", _js_function(worldmap._JS, "googleFrame"))


class TestTwoPages(_DeskFixtures, unittest.TestCase):
    """map.html and storms.html: one page, opened on the map or on the storms."""

    def test_the_map_opens_on_streets_under_the_rainfall_composite(self):
        html = stormdesk.page(self.state(self.polo()), focus="world")
        self.assertIn("<title>El Niño map</title>", html)
        self.assertIn("<h1>El Niño map</h1>", html)
        self.assertRegex(html, r'data-layer="streets" aria-pressed="true"')
        self.assertRegex(html, r'data-enso-var="PRECIP"[^>]*aria-pressed="true"')
        self.assertIn('data-carry="storms.html"', html)
        data = json.loads(re.search(r'id="desk-data" type="application/json">(.*?)</script>',
                                    html, re.S).group(1))
        self.assertEqual(data["focus"], "world")

    def test_the_storm_desk_opens_as_it_did(self):
        html = stormdesk.page(self.state(self.polo()))
        self.assertIn("<title>Storm desk</title>", html)
        self.assertRegex(html, r'data-layer="geocolor" aria-pressed="true"')
        self.assertRegex(html, r'data-enso-var=""[^>]*aria-pressed="true"')
        self.assertIn('data-carry="map.html"', html)
        data = json.loads(re.search(r'id="desk-data" type="application/json">(.*?)</script>',
                                    html, re.S).group(1))
        self.assertEqual(data["focus"], "storms")

    def test_the_atlas_dossier_opens_the_map_at_the_point(self):
        self.assertIn('href="map.html#at=', atlasview._JS)
        self.assertIn("This point on the map", atlasview._JS)

    def test_the_output_map_page_is_not_source(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        self.assertIn("output/map.html", ignored)

    def test_a_refreshed_page_writes_the_el_nino_key_again(self):
        # A refresh puts back the legend's markup, empty; the key's text is
        # only written when it changes, so what it last said is forgotten.
        self.assertIn('ensoSaid = ""', _js_function(stormdesk.script(), "takeRun"))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestHashRuns(unittest.TestCase):
    """#at= and #view=, as the page reads them, run under node."""

    NAMES = ("clamp", "wrap", "rad", "deg", "mx", "my", "lonOf", "latOf", "parseHash",
             "viewHash")

    def run_page(self, body, before=""):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in self.NAMES)
        script = functions + "\n" + before + "\nconsole.log(JSON.stringify(" + body + "));"
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "h.js"
            path.write_text(script, encoding="utf-8")
            done = subprocess.run(["node", str(path)], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_a_place_and_a_view_are_read(self):
        got = self.run_page('["#at=-12.05,-77.04", "#view=10.5,-150,3.5", "#view=10,-150,30",'
                            ' "#at=10,200"].map(parseHash)')
        self.assertEqual(got, [{"at": [-12.05, -77.04]}, {"view": [10.5, -150, 3.5]},
                               {"view": [10, -150, 19]}, {"at": [10, -160]}])

    def test_anything_else_is_not_a_place(self):
        got = self.run_page('["#at=abc", "#view=91,0,3", "#at=1,2,3", "#view=1,2", "",'
                            ' "#at=<script>", null, "#at=1,2&x=3"].map(parseHash)')
        self.assertEqual(got, [None] * 8)

    def test_the_view_carried_to_the_other_page_reads_back_as_the_same_view(self):
        got = self.run_page("[viewHash(), parseHash(viewHash())]",
                            "var S = {x: mx(-77.0428) + 1, y: my(-12.0464), z: 15.4};")
        self.assertEqual(got, ["#view=-12.0464,-77.0428,15.40",
                               {"view": [-12.0464, -77.0428, 15.4]}])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestAddressSearchRuns(unittest.TestCase):
    """Esri's geocoder as the page asks it and reads its answer, under node."""

    NAMES = ("clamp", "rad", "mx", "my", "fold", "coordinate", "where", "wrap",
             "geocodeUrl", "geocoded", "searchRow", "esc", "people", "peopleFact")
    ANSWER = {"candidates": [
        {"address": "Miraflores, Lima", "location": {"x": -77.0311217, "y": -12.1169693},
         "score": 100, "attributes": {"Match_addr": "Miraflores, Lima", "Type": "City"},
         "extent": {"xmin": -77.0541217, "ymin": -12.1399693, "xmax": -77.0081217,
                    "ymax": -12.0939693}},
        {"address": "<b>x</b>", "location": {"x": 10, "y": 20}, "score": 90,
         "attributes": {}}]}

    def run_page(self, body):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in self.NAMES)
        geocoder = re.search(r"var GEOCODER = [^\n]+", js)
        script = ((geocoder.group(0) if geocoder else "") + "\n" + functions
                  + "\nconsole.log(JSON.stringify(" + body + "));")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "a.js"
            path.write_text(script, encoding="utf-8")
            done = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                  encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    def test_the_words_are_sent_as_written_and_nothing_else(self):
        url = self.run_page('geocodeUrl("Rua 25 de Março & São Paulo #1")')
        self.assertEqual(
            url, "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/"
                 "findAddressCandidates?SingleLine=Rua%2025%20de%20Mar%C3%A7o%20%26%20S%C3%A3o"
                 "%20Paulo%20%231&maxLocations=6&outFields=Match_addr,Type&f=json")

    def test_the_candidates_come_back_as_places_to_fly_to(self):
        got = self.run_page("geocoded(" + json.dumps(self.ANSWER) + ")")
        first, second = got
        self.assertEqual({k: first[k] for k in ("kind", "label", "lon", "lat", "deep")},
                         {"kind": "address", "label": "Miraflores, Lima", "lon": -77.0311217,
                          "lat": -12.1169693, "deep": True})
        self.assertLess(first["box"]["x0"], first["box"]["x1"])
        self.assertLess(first["box"]["y0"], first["box"]["y1"])
        self.assertIn("City", first["sub"])
        self.assertIn("Esri World Geocoder", first["sub"])
        self.assertEqual(second["label"], "<b>x</b>")
        self.assertIsNone(second["box"])

    def test_an_extent_across_the_date_line_is_the_short_way_round(self):
        answer = {"candidates": [
            {"address": "Fiji", "location": {"x": 178.0, "y": -17.8},
             "attributes": {"Match_addr": "Fiji", "Type": "Country"},
             "extent": {"xmin": 177.0, "ymin": -21.0, "xmax": -178.0, "ymax": -12.0}}]}
        box = self.run_page("geocoded(" + json.dumps(answer) + ")")[0]["box"]
        self.assertAlmostEqual((box["x1"] - box["x0"]) * 360, 5.0, places=6)
        self.assertAlmostEqual(box["x0"] * 360 - 180, 177.0, places=6)

    def test_a_failed_answer_is_no_places(self):
        got = self.run_page("[geocoded(null), geocoded({error: {code: 498}}),"
                            " geocoded({candidates: [{location: {x: null, y: 3}}]})]")
        self.assertEqual(got, [[], [], []])

    def test_the_search_row_is_offered_only_for_words(self):
        got = self.run_page('[searchRow("ab"), searchRow("18.0N 76.8W"),'
                            ' searchRow("  Jr. de la Unión 300, Lima ")]')
        self.assertIsNone(got[0])
        self.assertIsNone(got[1])
        self.assertEqual(got[2]["kind"], "search")
        self.assertEqual(got[2]["q"], "Jr. de la Unión 300, Lima")
        self.assertIn("“Jr. de la Unión 300, Lima”", got[2]["label"])

    def test_a_town_s_people_are_not_said_to_live_at_an_address(self):
        lima = {"name": "Lima", "population": 8012000, "km": 1.2}
        got = self.run_page("[peopleFact('Lima, Peru', " + json.dumps(lima) + "),"
                            " peopleFact('Jirón Unión 300, Lima, 15001', "
                            + json.dumps(lima) + ")]")
        self.assertEqual(got, ["8,012,000 people (Natural Earth)",
                               "Lima: 8,012,000 people (Natural Earth)"])


class TestAddressSearch(unittest.TestCase):
    def test_nothing_is_sent_to_the_geocoder_until_its_row_is_chosen(self):
        self.assertIn("geocode(", _js_function(stormdesk._JS, "go"))
        self.assertNotIn("geocode(", _js_function(stormdesk._JS, "listFound"))
        self.assertIn("searchRow(", _js_function(stormdesk._JS, "listFound"))
        self.assertNotIn("forStorage", worldmap._JS)

    def test_an_address_flies_as_close_as_the_street_map_goes(self):
        view = _js_function(stormdesk._JS, "viewFor")
        self.assertIn("r.deep ? maxZoom() : 9", view)
        self.assertIn('setLayer("streets")', _js_function(stormdesk._JS, "go"))


class TestMapDocumented(unittest.TestCase):
    def setUp(self):
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_the_readme_has_the_map(self):
        self.assertIn("## 13. The map", self.readme)
        for words in ("map.html", "server.arcgisonline.com", "Map data not yet available",
                      "findAddressCandidates", "output=embed", "tile.openstreetmap.org"):
            self.assertIn(words, self.readme)

    def test_esri_is_not_said_to_need_a_key(self):
        # Esri's tiles answered with no key on 28 Sep 2026; they are
        # licensed, not keyed.
        self.assertNotIn("licensed, keyed and billed per tile", self.readme)
        self.assertNotRegex(atlasview.__doc__, r"Esri[\s\S]{0,60}keyed")

    def test_the_storm_desk_is_not_said_to_have_no_streets_or_geocoder(self):
        # Both were true of round 13's desk; the map's layers and its
        # geocoder are the same page's now.
        self.assertNotIn("no geocoding service asked", self.readme)
        self.assertNotIn("nothing on these keyless public feeds is", self.readme)


def _js_assignment(js: str, head: str) -> str:
    """One ``head = function (...) {...}`` of a page script, as written; "" if absent."""
    at = js.find(head + " = function")
    if at < 0:
        return ""
    depth, i = 0, js.index("{", at)
    while True:
        if js[i] == "{":
            depth += 1
        elif js[i] == "}":
            depth -= 1
            if not depth:
                return js[at:i + 1] + ";"
        i += 1


def _node_json(case: unittest.TestCase, script: str):
    """What a script run under node prints, read as JSON."""
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "w.js"
        path.write_text(script, encoding="utf-8")
        done = subprocess.run(["node", str(path)], capture_output=True, text=True,
                              encoding="utf-8", timeout=60)
    case.assertEqual(done.returncode, 0, done.stderr[-2000:])
    return json.loads(done.stdout)


def _named_run(page: str) -> str | None:
    """The run a page names in its head (elnino/live.py); None if it names none."""
    found = re.search(r'<meta name="elnino-run" content="([^"]*)">', page.split("</head>", 1)[0])
    return found.group(1) if found else None


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestNoWayBackRuns(unittest.TestCase):
    """A state the page could get into and not out of, run under node."""

    def run_script(self, script):
        return _node_json(self, script)

    def test_a_map_tile_that_failed_is_asked_for_again(self):
        # One lost answer from Esri's CDN left a hole in the street map for the
        # rest of the visit: a failed tile was never asked for again.
        js = stormdesk.script()
        self.assertIn("AGAIN = {}", _js_function(js, "forgetMaps"))
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "origin", "place", "inside_view", "TileSet", "tally", "againIn",
            "askAgain", "tileFailed"))
        got = self.run_script(r"""
var TILE = 256, S = {x: 0.5, y: 0.5, z: 3, w: 800, h: 600}, MAPS = {}, AGAIN = {}, now = 0, timers = [];
Date.now = function () { return now; };
function setTimeout(f, ms) { timers.push(ms); }
function requestRender() {}
function setAside() {}
function tileLoaded() {}
function node() { return {style: {}, appendChild: function () {}, remove: function () { this.gone = true; }}; }
var document = {createElement: node};
""" + functions + "\n" + _js_assignment(js, "TileSet.prototype.draw") + r"""
var set = new TileSet(node()), cell = {id: "streets/3/1/2", z: 3, c: 1, r: 2, name: "streets",
  key: "k", url: "https://x/3/2/1", map: "streets", grey: true};
set.draw([cell]);
var first = set.imgs[cell.id];
tileFailed.call(first);
set.draw([cell]);
var kept = set.imgs[cell.id] === first;
now = 29999; set.draw([cell]);
var early = set.imgs[cell.id] === first;
now = 30000; set.draw([cell]);
var second = set.imgs[cell.id];
var asked = second !== first && second.src === cell.url && !!first.gone;
tileFailed.call(second);
now = 89999; set.draw([cell]);
var waits = set.imgs[cell.id] === second;
now = 90000; set.draw([cell]);
console.log(JSON.stringify([kept, early, asked, waits, set.imgs[cell.id] !== second, timers,
                            MAPS.streets]));
""")
        self.assertEqual(got, [True, True, True, True, True, [30100, 60100],
                               {"ok": 0, "failed": 2}])

    def test_the_google_links_follow_the_view_to_the_point(self):
        # Here is written as a flight to a found place begins; its links to
        # Google carried the zoom the flight started from.
        self.assertIn("googleRelink()", _js_function(stormdesk.script(), "settle"))
        functions = "\n".join(_js_function(worldmap._JS, n) for n in (
            "wrap180", "googleZoom", "googleEmbed", "googleLinks", "googleHtml", "googleRelink"))
        got = self.run_script(r"""
function esc(v) { return String(v).replace(/&/g, '&amp;').replace(/"/g, '&quot;'); }
""" + functions + r"""
var S = {here: {lat: -12.1219, lon: -77.0297}, z: 2.1}, anchors = [];
googleHtml(S.here.lat, S.here.lon, S.z).replace(/<a href="([^"]*)"([^>]*)>/g, function (all, href, rest) {
  var attrs = {href: href.replace(/&amp;/g, "&")};
  rest.replace(/([\w-]+)="([^"]*)"/g, function (a, k, v) { attrs[k] = v; });
  anchors.push({getAttribute: function (k) { return attrs[k] === undefined ? null : attrs[k]; },
                setAttribute: function (k, v) { attrs[k] = v; }});
});
var document = {querySelectorAll: function () { return anchors; }};
S.z = 17.2;
googleRelink();
console.log(JSON.stringify(anchors.map(function (a) { return a.getAttribute("href"); })));
""")
        self.assertEqual(len(got), 4)
        self.assertIn("&zoom=17&basemap=roadmap", got[0])
        self.assertIn("&zoom=17&basemap=satellite", got[1])
        self.assertIn("map_action=pano&viewpoint=-12.121900,-77.029700", got[2])
        self.assertIn(",0a,%dd," % round(591657550.5 / 2 ** 17), got[3])

    def test_retry_is_offered_whenever_something_drawn_needs_nasa(self):
        # Over a street map, GIBS not answering left the ocean and flood
        # layers dead: Retry was offered only when NASA was the base.
        js = stormdesk.script()
        self.assertIn("downWord()", _js_function(js, "pills"))
        functions = "\n".join(_js_function(js, n) for n in (
            "labelled", "labelledBase", "mapDown", "nasaWanted", "gotKey", "tilesDown", "nasaDown",
            "downWord"))
        got = self.run_script(r"""
var LAYERS = {streets: {id: "streets", kind: "map"}, geocolor: {id: "geocolor", kind: "imagery"},
              infrared: {id: "infrared", kind: "imagery"}};
var MAPS = {}, S;
function state(over) {
  S = {layer: "streets", second: "infrared", compare: false, imagery: "unreachable", refs: {},
       enso: {tiles: {}}};
  for (var k in over) S[k] = over[k];
  return downWord();
}
""" + functions + r"""
var out = [state({enso: {tiles: {sst: true}}}), state({}), state({layer: "geocolor"}),
           state({refs: {roads: true}}), state({compare: true}), state({imagery: "ok"})];
MAPS.streets = {ok: 0, failed: 3};
out.push(state({imagery: "ok"}), state({imagery: "offline"}));
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, ["Imagery unreachable.", "", "Imagery unreachable.",
                               "Imagery unreachable.", "Imagery unreachable.", "",
                               "Map unreachable.", ""])

    def test_retry_asks_gibs_again_whatever_the_base(self):
        # Under a street map with only NASA's overlays on, nothing asked GIBS
        # after Retry or the network's return: the page waited on no question.
        js = stormdesk.script()
        online = js[js.index('addEventListener("online"'):]
        self.assertIn("askGibsAgain()", online[:online.index("});")])
        self.assertIn('if (el.id === "retry") { retry(); return; }', js)
        functions = "\n".join(_js_function(js, n) for n in ("askGibsAgain", "retry"))
        got = self.run_script(r"""
var S = {imagery: "unreachable", layer: "streets", refs: {coastlines: true}}, DOM = {"GOES-East": {}};
var probing = false, asked = [], forgot = 0, drawn = 0;
var statusPill = {innerHTML: "<span>Imagery unreachable.</span>"};
function source(id, sat) { return {name: id + "/" + sat, step: "PT10M"}; }
function ask(s) { asked.push([s.name, S.imagery, Object.keys(DOM).length, probing]); }
function forgetMaps() { forgot++; }
function dirty() { drawn++; }
""" + functions + r"""
retry();
console.log(JSON.stringify([asked, S.imagery, statusPill.innerHTML, forgot, drawn]));
""")
        self.assertEqual(got, [[["geocolor/GOES-East", "pending", 0, False]], "pending", "", 1, 1])


    def test_a_tile_failure_counts_once_no_frame_is_left_to_fall_back_to(self):
        # GIBS can list a frame and not send its tiles. A failure that sets its
        # frame aside is the frame not finished, and the one before is drawn;
        # once no frame is left to set aside, the failure is counted against
        # the frame on show, as an arrival is.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "tally", "tallyNasa", "gotKey", "setAside", "tileFailed", "tileLoaded"))
        got = self.run_script(r"""
var DOM = {G: {frames: [{key: "k4"}, {key: "k3"}, {key: "k2"}, {key: "k1"}, {key: "k0"}], aside: {}}};
var ASIDE = 900000, now = 1e6, MAPS = {}, AGAIN = {}, GOT = {};
Date.now = function () { return now; };
function dirty() {}
function requestRender() {}
function tile(name, key) { return {_name: name, _key: key, style: {}}; }
""" + functions + r"""
var out = [];
["k4", "k3", "k2", "k1"].forEach(function (k) { var t = tile("G", k); tileFailed.call(t); out.push(t._failed); });
out.push(DOM.G.frames.map(function (f) { return f.key; }), JSON.parse(JSON.stringify(GOT)));
tileLoaded.call(tile("G", "k1"));
tileFailed.call(tile("VIIRS", null));
out.push(GOT);
console.log(JSON.stringify(out));
""")
        self.assertEqual(got[:4], [True, True, True, True])
        self.assertEqual(got[4], ["k1", "k0"])
        self.assertEqual(got[5], {"G/k1": {"ok": 0, "failed": 1}})
        self.assertEqual(got[6], {"G/k1": {"ok": 1, "failed": 1}, "VIIRS/-": {"ok": 0, "failed": 1}})

    def test_imagery_whose_tiles_never_come_is_down_and_retried(self):
        # GIBS answered the frame listing, then every tile failed: the pill named
        # a frame time over an empty map, with no coastline and no Retry.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "labelled", "labelledBase", "mapDown", "nasaWanted", "gotKey", "tilesDown", "nasaDown",
            "downWord", "baseDown"))
        got = self.run_script(r"""
var LAYERS = {geocolor: {id: "geocolor", kind: "imagery"}, streets: {id: "streets", kind: "map"},
              satellite: {id: "satellite", kind: "map"}};
var MAPS = {}, GOT = {};
function frameOf(s, i) { return s.frames ? s.frames[i] : null; }
var G = {name: "G", step: "PT10M", frames: [{key: "k1"}], layer: {name: "GeoColor"}};
var H = {name: "H", step: "PT10M", frames: [{key: "k9"}], layer: {name: "GeoColor"}};
var street = {name: "streets", map: true, layer: LAYERS.streets}, sat = {name: "satellite", map: true, layer: LAYERS.satellite};
var S = {layer: "geocolor", second: "streets", compare: false, imagery: "ok", frame: 0, refs: {},
         enso: {tiles: {}}, inView: {G: G, H: H, none: true}, inViewB: null};
""" + functions + r"""
function look() { return [downWord(), baseDown()]; }
var out = [look()];
GOT["G/k1"] = {ok: 0, failed: 2}; out.push(look());
GOT["H/k9"] = {ok: 0, failed: 1}; out.push(look());
S.imagery = "offline"; out.push(look()); S.imagery = "ok";
GOT["H/k9"].ok = 1; out.push(look());
S.layer = "streets"; S.inView = {streets: street}; S.compare = true; S.second = "geocolor"; S.inViewB = {G: G};
out.push(look());
S.layer = "geocolor"; S.inView = {H: H}; S.second = "satellite"; S.inViewB = {satellite: sat};
MAPS.satellite = {ok: 0, failed: 2}; out.push(look());
// A year's layer and the day's 30 m stack are counted at the key their tiles are asked at.
var V = {name: "V", layer: {time: "2016-01-01"}}, L = {name: "L", step: "P1D", layer: {stack: ["L"]}}, C = {name: "C", layer: {}};
S.day = "2026-09-20";
GOT = {"V/2016-01-01": {ok: 0, failed: 1}, "L/2026-09-20": {ok: 0, failed: 1}, "C/-": {ok: 0, failed: 1}};
out.push([tilesDown(V), tilesDown(L), tilesDown(C)]);
GOT = {"V/-": {ok: 0, failed: 1}, "L/-": {ok: 0, failed: 1}, "C/x": {ok: 0, failed: 1}};
out.push([tilesDown(V), tilesDown(L), tilesDown(C)]);
console.log(JSON.stringify(out));
""")
        down = "Imagery unreachable."
        self.assertEqual(got[:7], [["", False], ["", False], [down, True], ["", True], ["", False],
                                   # A compared layer's tiles failing is said, and retried;
                                   # the coastline is for the base.
                                   [down, False], ["Map unreachable.", False]])
        self.assertEqual(got[7:], [[True, True, True], [False, False, False]])

    def test_the_pill_says_whose_tiles_never_came_and_what_the_compared_side_shows(self):
        # Compared, the pill spoke of the base alone: the compared layer's own
        # frame, which can be another time, was said nowhere, nor a compared
        # map's server not answering.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "labelled", "labelledBase", "mapDown", "nasaWanted", "gotKey", "tilesDown", "nasaDown",
            "downWord", "sourceWords", "pills"))
        got = self.run_script(r"""
var LAYERS = {geocolor: {id: "geocolor", kind: "imagery", name: "GeoColor", zoom: 13},
              streets: {id: "streets", kind: "map", source: "Esri World Street Map"},
              satellite: {id: "satellite", kind: "map", source: "Esri World Imagery", over: ["x"]}};
var MAPS = {}, GOT = {}, DOM = {}, BYID = {}, pillOpen = true, pillHtml = "";
var framePill = {innerHTML: ""}, statusPill = {innerHTML: "", hidden: true, firstChild: null};
function $() { return null; }
function esc(v) { return String(v); }
function frameOf(s, i) { return s.frames ? s.frames[i] : null; }
function timed() { return true; }
function utc(t) { return "T" + t; }
function ago(t) { return "A" + t; }
function ensoTileMore() { return []; }
function src(name, sat, layer, key, t) { return {name: name, sat: sat, step: "PT10M", frames: [{key: key, t: t}], layer: {name: layer}}; }
var G = src("G", "GOES-East", "GeoColor", "k1", 1), H = src("H", "GOES-West", "GeoColor", "k9", 2);
var I = src("I", "GOES-East", "Clean infrared", "k7", 7);
var street = {name: "streets", map: true, layer: LAYERS.streets}, sat = {name: "satellite", map: true, layer: LAYERS.satellite};
var S = {layer: "geocolor", second: "streets", compare: false, imagery: "ok", frame: 0, z: 3, refs: {},
         enso: {tiles: {}}, inView: {G: G, H: H}, inViewB: null, selected: null};
""" + functions + r"""
function look() {
  pills();
  return [framePill.innerHTML.replace(/<button[^>]*>[^<]*<\/button>/g, "").split(/<[^>]+>/).filter(Boolean),
          statusPill.hidden ? "" : statusPill.innerHTML.split(/<[^>]+>/).filter(Boolean)[0]];
}
var out = [look()];
GOT["G/k1"] = {ok: 0, failed: 1}; out.push(look());
GOT["H/k9"] = {ok: 0, failed: 3}; out.push(look());
GOT = {}; S.compare = true; S.second = "infrared"; S.inViewB = {I: I}; out.push(look());
S.imagery = "pending"; out.push(look()); S.imagery = "ok";
S.layer = "streets"; S.inView = {streets: street}; S.second = "geocolor"; S.inViewB = {G: G}; out.push(look());
S.layer = "geocolor"; S.inView = {G: G}; S.second = "satellite"; S.inViewB = {satellite: sat}; out.push(look());
MAPS.satellite = {ok: 0, failed: 1}; out.push(look());
console.log(JSON.stringify(out));
""")
        self.assertEqual(got[0], [["GOES-East GeoColor: T1, A1", "GOES-West GeoColor: T2, A2"], ""])
        # One imager's tiles not arriving is said on its line.
        self.assertEqual(got[1], [["GOES-East GeoColor: its tiles did not arrive", "GOES-West GeoColor: T2, A2"], ""])
        # None arriving: the map is said to be down, as when GIBS does not answer.
        self.assertEqual(got[2], [["Imagery unreachable: NASA GIBS sent none of the tiles in view. "
                                   "The coastline is the page's own copy."], "Imagery unreachable."])
        compared = "Compared, right of the divider: "
        self.assertEqual(got[3], [["GOES-East GeoColor: T1, A1", "GOES-West GeoColor: T2, A2",
                                   compared + "GOES-East Clean infrared: T7, A7."], ""])
        self.assertEqual(got[4], [["Imagery: asking NASA GIBS for the latest frames"], ""])
        self.assertEqual(got[5], [["Map: Esri World Street Map", compared + "GOES-East GeoColor: T1, A1."], ""])
        self.assertEqual(got[6], [["GOES-East GeoColor: T1, A1", compared + "Esri World Imagery."], ""])
        self.assertEqual(got[7], [["GOES-East GeoColor: T1, A1", compared + "Esri World Imagery did not answer."],
                                  "Map unreachable."])

    def test_retry_asks_again_for_every_tile_that_failed(self):
        # Retry and the network's return asked again for the map tiles alone:
        # NASA's that had failed stayed holes, the frames listed again or not.
        js = stormdesk.script()
        got = self.run_script(r"""
var MAPS = {streets: {ok: 0, failed: 1}}, AGAIN = {"u": 2}, GOT = {"G/k1": {ok: 0, failed: 1}};
function img(failed, map) { return {_failed: failed, _map: map, remove: function () { this.gone = true; }}; }
function pane(list) { var imgs = {}; list.forEach(function (t, i) { imgs["t" + i] = t; }); return {sets: {s: {imgs: imgs}}}; }
var a = [img(true, "streets"), img(true, null), img(false, null)], e = [img(true, null)], r = [img(true, null)];
var panes = {a: pane(a), b: pane([]), o: pane([]), ob: pane([]), r: pane(r), e: pane(e)};
""" + _js_function(js, "forgetMaps") + r"""
forgetMaps();
console.log(JSON.stringify([a.concat(e, r).map(function (t) { return !!t.gone; }),
                            Object.keys(panes.a.sets.s.imgs), MAPS, AGAIN, GOT]));
""")
        self.assertEqual(got, [[True, True, False, True, True], ["t2"], {}, {}, {}])

@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestLayerChoiceRuns(unittest.TestCase):
    """Choosing a map layer, run under node."""

    def test_a_layer_that_needs_the_page_served_says_why_when_pressed(self):
        # Its reason was a tooltip on a disabled button: nothing on a tablet.
        # Then the reason stayed under the buttons after the layer changed by
        # Swap, a found address or a storm's button.
        js = stormdesk.script()
        self.assertIn("pressLayer(b.getAttribute(\"data-layer\"))", js)
        functions = "\n".join(_js_function(js, n) for n in (
            "servedOnly", "servedWhy", "unserved", "setLayer", "pressLayer"))
        got = _node_json(self, r"""
var location = {protocol: "file:"}, S = {layer: "streets", second: "infrared", compare: false};
var D = {layers: [{id: "streets", kind: "map", name: "Streets"}, {id: "satellite", kind: "map", name: "Satellite"},
                  {id: "osm", kind: "map", name: "OpenStreetMap", served_only: true}]};
var LAYERS = {streets: D.layers[0], satellite: D.layers[1], osm: D.layers[2]};
function el() { return {hidden: false, textContent: "", title: "", disabled: false, value: "",
                        attrs: {}, setAttribute: function (k, v) { this.attrs[k] = v; }}; }
var els = {"layer-streets": el(), "layer-osm": el(), "layer-note": el(), "opt-osm": el(), "compare-layer": el()};
els["opt-osm"].textContent = "OpenStreetMap";
function $(id) { return els[id] || null; }
var document = {querySelector: function (q) { return q.indexOf('value="osm"') >= 0 ? els["opt-osm"] : null; },
                querySelectorAll: function () { return []; }};
function dirty() {}
""" + functions + r"""
unserved();
var button = els["layer-osm"], note = els["layer-note"], option = els["opt-osm"];
var out = [button.disabled, button.attrs["aria-disabled"], option.disabled, option.textContent];
out.push(pressLayer("osm"), note.hidden, note.textContent, S.layer);
out.push(pressLayer("streets"), note.textContent, S.layer);
pressLayer("osm");
out.push(setLayer("satellite"), note.textContent, S.layer);
location.protocol = "http:";
out.push(pressLayer("osm"), note.textContent, S.layer);
console.log(JSON.stringify(out));
""")
        self.assertEqual(got[:4], [False, "true", True, "OpenStreetMap (needs the page served)"])
        self.assertEqual(got[4:6], [False, False])
        self.assertIn("python track.py --serve", got[6])
        self.assertIn("--lan for a tablet", got[6])
        self.assertEqual(got[7:], ["streets", True, "", "streets", True, "", "satellite", True, "", "osm"])

    def test_town_names_say_why_they_are_not_drawn(self):
        # The box did nothing over a street map, or below zoom 4, and said nothing.
        js = stormdesk.script()
        self.assertIn("townsNote();", _js_function(js, "render"))
        functions = "\n".join(_js_function(js, n) for n in ("labelled", "labelledBase", "townsWhy", "townsNote"))
        got = _node_json(self, r"""
var LAYERS = {streets: {kind: "map"}, geocolor: {kind: "imagery"}}, S = {}, townsSaid = null;
var why = {textContent: "", writes: 0};
function $(id) { return id === "why-towns" ? why : null; }
""" + functions + r"""
var out = [];
[["streets", 9], ["geocolor", 3], ["geocolor", 4], ["geocolor", 4]].forEach(function (v) {
  S.layer = v[0]; S.z = v[1]; townsNote(); out.push([why.textContent, townsWhy()]);
});
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, [["(the map names its own)", "(the map names its own)"],
                               ["(from zoom 4)", "(from zoom 4)"], ["", ""], ["", ""]])

    def test_the_credit_names_what_is_drawn_and_nothing_else(self):
        # With only NASA's SST tile over a street map, the line named GOES,
        # Himawari, IMERG, VIIRS and OpenStreetMap's reference layers too; then
        # a compared Air mass named Himawari with only GOES-East on the screen,
        # and a layer GIBS never answered for was credited all the same. The
        # line is read off the tiles on the screen, each on its side of the
        # divider, loaded and not hidden.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in ("world", "origin", "shows", "credit"))
        got = _node_json(self, r"""
var TILE = 256, D = {gibs: """ + json.dumps(stormdesk.GIBS_ENDPOINTS) + r"""};
var creditEl = {textContent: ""}, creditSaid = "", S, panes;
function img(words, nasa, over) {
  var t = {complete: true, naturalWidth: 256, style: {visibility: ""}, _z: 2, _c: 1, _r: 1, _credit: words, _nasa: nasa};
  for (var k in over) t[k] = over[k];
  return t;
}
function pane(sets) {
  var out = {sets: {}};
  sets.forEach(function (imgs, i) {
    var set = {el: {style: {visibility: ""}}, imgs: {}};
    imgs.forEach(function (t, j) { set.imgs[i + "/" + j] = t; });
    out.sets["s" + i] = set;
  });
  return out;
}
function view(p, over) {
  S = {x: 0.5, y: 0.5, z: 2, w: 1024, h: 1024, compare: false, split: 0.5};
  for (var k in over) S[k] = over[k];
  panes = {a: pane(p.a || []), o: pane(p.o || []), b: pane(p.b || []), ob: pane(p.ob || []),
           r: pane(p.r || []), e: pane(p.e || [])};
  if (p.hide) p.hide(panes);
  credit();
  return creditEl.textContent;
}
""" + functions + r"""
var goes = "GOES: NOAA.", hima = "Himawari: JMA.", esri = "Esri.", sst = "SST: GHRSST MUR, NASA JPL.";
console.log(JSON.stringify([
  view({a: [[img(esri, false)]], e: [[img(sst, true)]]}),
  view({a: [[img(goes, true), img(goes, true)]], b: [[img(goes, true, {_c: 2})]]}, {compare: true}),
  view({a: [[img(goes, true, {naturalWidth: 0}), img(hima, true, {style: {visibility: "hidden"}})]]}),
  view({a: [[img(esri, false, {complete: false})]]}),
  view({a: [[img(goes, true, {_c: 3})], [img(hima, true)]]}, {compare: true}),
  view({a: [[img(hima, true)]], hide: function (p) { p.a.sets.s0.el.style.visibility = "hidden"; }}),
  view({a: [[img(goes, true, {_c: 9})]]}),
  view({a: [[img(hima, true), img(goes, true)]], r: [[img("Reference layers: OpenStreetMap contributors.", true)]]}),
  view({a: [[img(goes, true)]], ob: [[img(esri, false, {_c: 2})]]}, {compare: true}),
  view({a: [[img(goes, true)]], ob: [[img(esri, false, {_c: 0})]]}, {compare: true})
]));
""")
        ack = "Imagery: NASA GIBS."
        self.assertEqual(got[0], "Esri. " + ack + " SST: GHRSST MUR, NASA JPL.")
        # Compared, each side says only what it shows.
        self.assertEqual(got[1], ack + " GOES: NOAA.")
        # A tile that failed, or that was hidden, is not drawn.
        self.assertEqual(got[2], "")
        self.assertEqual(got[3], "")
        # The base's tile right of the divider is under the compared layer.
        self.assertEqual(got[4], ack + " Himawari: JMA.")
        # A frame not on show (the loop's others) is not drawn either.
        self.assertEqual(got[5], "")
        # Nor is a tile off the screen.
        self.assertEqual(got[6], "")
        # Within a pane the words keep one order, whichever tile came first.
        self.assertEqual(got[7], ack + " GOES: NOAA. Himawari: JMA. Reference layers: OpenStreetMap contributors.")
        # A compared map's own roads and names, on its side of the divider only.
        self.assertEqual(got[8], ack + " GOES: NOAA. Esri.")
        self.assertEqual(got[9], ack + " GOES: NOAA.")

    def test_each_tile_carries_the_words_of_what_drew_it(self):
        # The credit line reads these off the tiles on the screen: an imager's
        # tile its operator's, a global layer's its mission's, a map's its own.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "clamp", "deg", "world", "origin", "lonOf", "latOf", "xyzUrl", "present", "xyzCells", "source",
            "cells"))
        layers = [stormdesk._plain_layer(l) for l in stormdesk.LAYERS + worldmap.LAYERS]
        got = _node_json(self, r"""
var TILE = 256, NODATA = {}, D = {gibs: """ + json.dumps(stormdesk.GIBS_ENDPOINTS) + r"""};
var LAYERS = {}; """ + json.dumps(layers) + r""".forEach(function (l) { LAYERS[l.id] = l; });
var S = {x: 0.5, y: 0.5, z: 2, w: 512, h: 512, imagery: "ok"}, sat = "GOES-East";
function owners(lo, hi) { return [{name: sat, w: -180, e: lo + (hi - lo) / 4, seen: true}]; }
function ask() {}
function frameOf() { return {key: "k"}; }
function timed() { return false; }
function tileUrl() { return "u"; }
""" + functions + r"""
function words(id) {
  var seen = [];
  cells(id, 0).cells.forEach(function (c) { var w = [c.credit, c.nasa]; if (JSON.stringify(seen).indexOf(JSON.stringify(w)) < 0) seen.push(w); });
  return seen;
}
var out = [words("infrared"), words("rain"), words("streets")];
sat = "Himawari"; out.push(words("geocolor"));
var cut = cells("infrared", 0).cells[0].cut;
out.push([cut[0], Math.round(cut[1] * 1000) / 1000]);
console.log(JSON.stringify(out));
""")
        self.assertEqual(got[0], [["GOES: NOAA.", True]])
        self.assertEqual(got[1], [["IMERG: NASA GPM.", True]])
        self.assertEqual(got[2], [[worldmap.MAP_LAYERS[0]["credit"], False]])
        # GIBS has no Himawari GeoColor: its infrared stands in, and JMA is credited.
        self.assertEqual(got[3], [["Himawari: JMA.", True]])
        # The imager draws the west quarter of its tile, less a hair for the seam.
        self.assertEqual(got[4], [0, 0.749])

    def test_the_reading_under_the_map_holds_its_height(self):
        # The composite's reading shared a line with its scale when short and
        # took one of its own when long, so the map above jumped 9 px, and
        # every piece of geometry was rebuilt, each time the centre of the
        # view crossed into a cell with more or fewer words.
        js = stormdesk.script()
        self.assertIn('holdHeight($("enso-read"))', _js_function(js, "ensoLegend"))
        self.assertRegex(worldmap.css(), r"#enso-read \{[^}]*flex-basis: 100%")
        self.assertIn('window.addEventListener("resize", function () { ensoSaid = ""; });', js)
        got = _node_json(self, r"""
var readTall = 0, readWide = 0;
""" + _js_function(js, "holdHeight") + r"""
var el = {parentNode: {clientWidth: 900}, style: {minHeight: ""}, textContent: ""};
Object.defineProperty(el, "offsetHeight", {get: function () {
  var natural = Math.ceil(this.textContent.length * 6 / this.parentNode.clientWidth) * 16;
  return Math.max(natural, parseFloat(this.style.minHeight) || 0); }});
var out = [];
function read(n) { el.textContent = new Array(n + 1).join("x"); holdHeight(el); out.push(el.style.minHeight); }
read(100); read(200); read(30);
el.parentNode.clientWidth = 1500; read(30);
console.log(JSON.stringify(out));
""")
        # It grows to the most it has needed at this width, and starts again
        # when the width changes.
        self.assertEqual(got, ["16px", "32px", "32px", "16px"])

    def test_a_reading_written_anew_by_a_take_keeps_the_height_held(self):
        # A run taken in place writes the key anew: its reading, shorter for
        # now, keeps the height the old one held, so the map does not jump.
        got = _node_json(self, r"""
var readTall = 0, readWide = 0;
""" + _js_function(stormdesk.script(), "holdHeight") + r"""
function reading(text) {
  var el = {parentNode: {clientWidth: 900}, style: {minHeight: ""}, textContent: text};
  Object.defineProperty(el, "offsetHeight", {get: function () {
    var natural = Math.ceil(this.textContent.length * 6 / this.parentNode.clientWidth) * 16;
    return Math.max(natural, parseFloat(this.style.minHeight) || 0); }});
  return el;
}
var old = reading(new Array(201).join("x")); holdHeight(old);
var fresh = reading("Centre of the view: +0.4"); holdHeight(fresh);
console.log(JSON.stringify([old.style.minHeight, fresh.style.minHeight, fresh.offsetHeight]));
""")
        self.assertEqual(got, ["32px", "32px", 32])

    def test_the_el_nino_controls_show_what_is_set_wherever_they_are(self):
        # setEnso and a run taken in place (whose panel brings the regions'
        # Show anew) both set the controls from S.enso.
        js = stormdesk.script()
        self.assertIn("ensoControls();", _js_function(js, "setEnso"))
        self.assertIn("ensoControls();", _js_function(js, "takeRun"))
        got = _node_json(self, _js_function(js, "ensoControls") + r"""
var S = {enso: {variable: "PRECIP", season: "SON", mask: true, opacity: 0.7, tileOpacity: 0.8,
                tiles: {sst: true}, regions: false, boxes: true, shown: "Coastal Peru and Ecuador"}};
function button(attr, value) {
  return {attrs: {}, checked: false, getAttribute: function (k) { return k === attr ? value : this.attrs[k]; },
          setAttribute: function (k, v) { this.attrs[k] = v; }};
}
var LISTS = {
  "[data-enso-var]": [button("data-enso-var", "PRECIP"), button("data-enso-var", "")],
  "[data-enso-season]": [button("data-enso-season", "DJF"), button("data-enso-season", "SON")],
  "[data-enso-tile]": [button("data-enso-tile", "sst"), button("data-enso-tile", "floods")],
  "[data-enso-geo]": [button("data-enso-geo", "regions"), button("data-enso-geo", "boxes")],
  "[data-show-region]": [button("data-show-region", "Coastal Peru and Ecuador"), button("data-show-region", "Caribbean")]
};
var document = {querySelectorAll: function (sel) { return LISTS[sel] || []; }};
var els = {"enso-mask": {checked: false}, "enso-opacity": {value: 0}, "enso-tile-opacity": {value: 0},
           "enso-tiles": {style: {opacity: ""}}};
function $(id) { return els[id] || null; }
ensoControls();
function pressed(sel) { return LISTS[sel].map(function (b) { return b.attrs["aria-pressed"]; }); }
function ticked(sel) { return LISTS[sel].map(function (b) { return b.checked; }); }
console.log(JSON.stringify([pressed("[data-enso-var]"), pressed("[data-enso-season]"), ticked("[data-enso-tile]"),
                            ticked("[data-enso-geo]"), pressed("[data-show-region]"), els["enso-mask"].checked,
                            els["enso-opacity"].value, els["enso-tiles"].style.opacity]));
""")
        self.assertEqual(got, [["true", "false"], ["false", "true"], [True, False], [False, True],
                               ["true", "false"], True, 0.7, 0.8])

    def test_nasas_tiles_follow_their_own_slider(self):
        js = stormdesk.script()
        self.assertIn('setEnso({tileOpacity: +e.target.value})', js)
        functions = "\n".join(_js_function(js, name) for name in ("ensoControls", "setEnso"))
        got = _node_json(self, r"""
var S = {enso: {tiles: {}, tileOpacity: 0.8}, here: null}, dirtied = 0;
var els = {"enso-tile-opacity": {value: 0.8}, "enso-tiles": {style: {opacity: ""}}};
function $(id) { return els[id] || null; }
var document = {querySelectorAll: function () { return []; }};
function dirty() { dirtied++; }
function showHere() {}
""" + functions + r"""
setEnso({tileOpacity: 0.45});
console.log(JSON.stringify([els["enso-tiles"].style.opacity, els["enso-tile-opacity"].value, dirtied]));
""")
        self.assertEqual(got, [0.45, 0.45, 1])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestWorldCopiesRuns(unittest.TestCase):
    """Zoomed out on a wide screen the world repeats; everything drawn repeats with it."""

    def test_the_geometry_is_drawn_on_every_copy_of_the_world_in_view(self):
        # The composite and the tiles repeated at zoom 1 and 2; the Nino boxes,
        # regions and storm tracks were drawn on one copy only.
        js = stormdesk.script()
        self.assertIn("geoReach() !== geoCopies", _js_function(js, "render"))
        functions = "\n".join(_js_function(js, n) for n in ("world", "near", "mx", "X", "geoReach", "repeated", "buildGeo"))
        got = _node_json(self, r"""
var TILE = 256, UNIT = 1048576, geoDirty = true, geoRef = null, geoCopies = 0, geoLo = 0, geoHi = 0, geoExt = null;
var STORMS = [], S = {x: 0.5, z: 1, w: 1920, h: 600, show: {}};
var D = {style: {}, outlook: [], invests: []}, geoG = {innerHTML: ""}, box = null;
function ensoGeo() { return box === null ? "" : '<path class="ninobox" d="M' + X(box[0], box[1]) + ' 0"/>'; }
""" + functions + r"""
var out = [];
function build(z, w, lon, k) {
  S.z = z; S.w = w; box = lon === null ? null : [lon, k];
  buildGeo(); out.push(geoG.innerHTML, geoCopies);
}
build(1, 1920, -170, 0);
build(2, 390, -170, 0);
build(6, 1920, -170, 0);
// A track reaching 0.651 of a world west of the view's centre, at zoom 4.65
// on a 1540 px map: panned a quarter of a world on before the next rebuild,
// its copy a world east reaches the screen.
build(4.65, 1540, 125.64, -1);
build(1, 1920, null, 0);
console.log(JSON.stringify(out));
""")

        def one(x):
            return '<path class="ninobox" d="M%d 0"/>' % x

        def at(x, inner):
            return '<g transform="translate(%d 0)">%s</g>' % (x, inner)
        w = one(29127)
        self.assertEqual(got[0], w + at(1048576, w) + at(-1048576, w) + at(2097152, w) + at(-2097152, w))
        self.assertEqual(got[1], 2)
        # A box half a world off the centre, on a narrow screen at zoom 2, has
        # no copy a quarter of a world's pan could bring into view.
        self.assertEqual(got[2:6], [w, 0, w, 0])
        far = one(-158335)
        self.assertEqual(got[6:8], [far + at(1048576, far) + at(-1048576, far), 1])
        # Nothing drawn, nothing copied.
        self.assertEqual(got[8:], ["", 0])

    def test_the_coastline_is_drawn_again_a_world_to_either_side(self):
        # The page's own coastline, drawn when the map cannot be had, is
        # copied as the markup itself, as many worlds either side as half the
        # view is wide: at zoom 1 on a wide map, one each side left the
        # screen's ends blank sea under the storms and regions.
        functions = "\n".join(_js_function(stormdesk.script(), n) for n in (
            "clamp", "rad", "mx", "my", "world", "repeated", "coastReach", "buildCoast"))
        got = _node_json(self, r"""
var TILE = 256, UNIT = 1048576, coastDone = 0, coastD = "", coastG = {sets: 0, h: ""};
Object.defineProperty(coastG, "innerHTML", {get: function () { return this.h; }, set: function (v) { this.h = v; this.sets++; }});
var S = {w: 400, z: 3}, D = {coast: {lines: ["0,0,100,0"]}}, down = true;
function baseDown() { return down; }
""" + functions + r"""
var out = [];
buildCoast(); out.push(coastG.innerHTML);
S.z = 1; S.w = 1920; buildCoast(); out.push((coastG.innerHTML.match(/class="coast"/g) || []).length);
var sets = coastG.sets; buildCoast(); out.push(coastG.sets === sets);
down = false; buildCoast(); out.push(coastG.innerHTML);
console.log(JSON.stringify(out));
""")
        one = '<path class="coast" d="M524288 524288L527201 524288"/>'
        self.assertEqual(got[0], one + '<g transform="translate(1048576 0)">%s</g>' % one +
                         '<g transform="translate(-1048576 0)">%s</g>' % one)
        self.assertEqual(got[1:], [5, True, ""])

    def test_the_coastline_moves_whole_worlds_with_the_view(self):
        # Dragged a world or more before the view settles, the coastline's
        # copies stay under it.
        functions = "\n".join(_js_function(stormdesk.script(), n) for n in ("world", "origin", "placeWorld"))
        got = _node_json(self, r"""
var TILE = 256, UNIT = 1048576, S = {x: 2.3, y: 0.5, z: 1, w: 1920, h: 600};
function el() { return {attrs: {}, setAttribute: function (k, v) { this.attrs[k] = v; }}; }
var geoG = el(), coastG = el();
""" + functions + r"""
placeWorld();
console.log(JSON.stringify([geoG.attrs.transform, coastG.attrs.transform]));
""")
        self.assertEqual(got, ["matrix(0.00048828125 0 0 0.00048828125 -217.60 44.00)",
                               "matrix(0.00048828125 0 0 0.00048828125 806.40 44.00)"])

    def test_no_copy_of_the_world_is_a_use_element(self):
        # The page's stylesheet does not reach into what a <use> element
        # draws: each copy of a region or a coast drawn that way was a black
        # fill, in Chrome, across a whole copy of the world.
        self.assertNotIn("<use", stormdesk.script())

    def test_marks_are_drawn_on_every_copy_of_the_world_in_view(self):
        # A storm, an outlook area and the pin, at zoom 1 on a 1920 px screen:
        # the world is 512 px wide, so each shows four times, not once.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "origin", "near", "copies", "clamp", "mx", "my", "rad", "esc", "pct",
            "drawMarks", "ensoLabels"))
        got = _node_json(self, r"""
var TILE = 256, HOUR = 3600000, NM = 1.852, CIRCUMFERENCE = 40075.017;
var S = {x: 0.5, y: 0.5, z: 1, w: 1920, h: 600, scrub: 0, selected: null,
         show: {outlook: true, places: false, towns: false},
         pin: {lon: -77.03, lat: -12.05, label: "Lima"}, enso: {boxes: false, regions: false}};
var D = {outlook: [{lon: -150, lat: 10, key: "a", label: "Area", level: "low", centre: "NHC",
                    chance_2day: 10, chance_7day: 20}],
         invests: [], style: {outlook: {}}};
var storm = {id: "s1", hue: "#f00", d: {title: "Polo", forecast: [], view: null, advisory_fix: null,
                                        wind: 50}};
var STORMS = [storm], BYID = {s1: storm}, marksG = {innerHTML: ""};
function base() { return {t: 0, image: false}; }
function centreAt() { return {lon: -60, lat: 15, category: 1, wind: 50}; }
""" + functions + r"""
storm.x0 = mx(-60);
drawMarks();
var h = marksG.innerHTML;
function count(cls) { return h.split('class="' + cls + '"').length - 1; }
var eyes = (h.match(/class="eye" cx="[-0-9.]+"/g) || []).map(function (m) { return +m.split('cx="')[1].slice(0, -1); });
console.log(JSON.stringify([eyes.filter(function (x) { return x >= 0 && x <= 1920; }).length, count("x"), count("pin"),
                            eyes.every(function (x) { return x > -200 && x < 2120; })]));
""")
        # A storm just off the screen is still drawn, as before: its winds can
        # reach into view. Nothing further off is.
        self.assertEqual(got, [4, 4, 4, True])

    def test_a_tap_on_any_copy_flies_the_short_way(self):
        # Zoomed out, a storm or an outlook area shows on every copy of the
        # world in view; a tap on any of them flies to the one nearest the view,
        # across the date line if that is shorter, never back across worlds.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in ("clamp", "rad", "mx", "my", "near", "tap", "flyTo", "flyToArea"))
        got = _node_json(self, r"""
var TILE = 256, S = {z: 1, layer: "geocolor", y: 0.5}, lastTap = null, tapTimer = 0, flown = [];
var LAYERS = {geocolor: {}}, window = {innerHeight: 900};
var map = {getBoundingClientRect: function () { return {top: 0, bottom: 600}; }, scrollIntoView: function () {}};
var storm = {id: "s1", d: {lon: -170, lat: 15, view: {satellite: "GOES-West"}}};
var BYID = {s1: storm}, D = {outlook: [{key: "a1", lon: 179, lat: 12}]};
function select() {}
function when() { return 0; }
function centreAt(st) { return {lon: st.d.lon, lat: st.d.lat}; }
function animate(to) { flown.push(Math.round(to.x * 1e4) / 1e4); }
function on(attr, value) {
  return {closest: function () { return {getAttribute: function (a) { return a === attr ? value : null; }}; }};
}
""" + functions + r"""
var t = 0;
function tapAt(x, attr, value) { S.x = x; t += 1000; tap({x: 100, y: 100, target: on(attr, value)}, t); }
storm.d.lon = -60; tapAt(3.5, "data-storm", "s1");       // dragged three worlds east
storm.d.lon = -170; tapAt(0.95, "data-storm", "s1");     // just west of the date line
tapAt(0.02, "data-area", "a1");                          // just east of it
console.log(JSON.stringify(flown));
""")
        self.assertEqual(got, [3.3333, 1.0278, -0.0028])

    def test_town_names_give_way_to_a_map_on_its_own_side_of_the_divider(self):
        # Compared with a map, the gazetteer's names were drawn over the map's
        # own on its side, or not at all over NASA's imagery when the map was
        # the base. Each side now says for itself, and the Towns reason agrees.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "origin", "near", "copies", "clamp", "mx", "my", "rad", "esc", "pct",
            "labelled", "labelledBase", "namedAt", "townsWhy", "drawMarks", "ensoLabels"))
        got = _node_json(self, r"""
var TILE = 256, HOUR = 3600000, NM = 1.852, CIRCUMFERENCE = 40075.017;
var LAYERS = {streets: {kind: "map"}, satellite: {kind: "map"}, geocolor: {kind: "imagery"}};
var PLACES = [["West", "", "", 500000, -10, 0, false], ["East", "", "", 500000, 10, 0, false],
              ["Hamlet", "", "", 900, 0, 5, false]], BYPOP = null;
var D = {outlook: [], invests: [], style: {outlook: {}}};
var STORMS = [], BYID = {}, marksG = {innerHTML: ""}, calls = 0;
function base() { return {t: 0, image: false}; }
function centreAt() { return null; }
""" + functions + r"""
var counted = copies;
copies = function (x0, px) { calls++; return counted(x0, px); };
function view(layer, second) {
  S = {x: 0.5, y: 0.5, z: 6, w: 1920, h: 600, scrub: 0, selected: null, show: {towns: true, outlook: false, places: false},
       pin: null, enso: {boxes: false, regions: false}, layer: layer, second: second || "geocolor", compare: !!second, split: 0.5};
  calls = 0; drawMarks();
  var names = (marksG.innerHTML.match(/>(West|East|Hamlet)</g) || []).map(function (m) { return m.slice(1, -1); });
  return [names, townsWhy(), calls];
}
var S;
console.log(JSON.stringify([view("geocolor", "streets"), view("streets", "geocolor"), view("streets"),
                            view("geocolor"), view("streets", "satellite")]));
""")
        self.assertEqual([g[:2] for g in got], [
            [["West"], ""], [["East"], ""], [[], "(the map names its own)"],
            [["West", "East"], ""], [[], "(the map names its own)"]])
        # Only the towns big enough for the zoom are placed on the world's copies.
        self.assertEqual(got[3][2], 2)

    def test_a_town_name_keeps_off_a_map_across_the_divider(self):
        # A town just on the imagery side of the divider had its name drawn to
        # the right of its dot, across the divider and over the map's own names.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "origin", "near", "copies", "clamp", "mx", "my", "rad", "esc", "pct",
            "labelled", "labelledBase", "namedAt", "townsWhy", "drawMarks", "ensoLabels"))
        got = _node_json(self, r"""
var TILE = 256, HOUR = 3600000, NM = 1.852, CIRCUMFERENCE = 40075.017;
var LAYERS = {streets: {kind: "map"}, geocolor: {kind: "imagery"}};
var PLACES = [["Norman", "", "", 600000, 0.4, 0, false], ["Oklahoma City", "", "", 500000, -0.5, 0, false],
              ["Edmond", "", "", 400000, 0.3, 0, false], ["Tulsa", "", "", 300000, 3, 0, false]], BYPOP = null;
var D = {outlook: [], invests: [], style: {outlook: {}}};
var STORMS = [], BYID = {}, marksG = {innerHTML: ""}, S;
function base() { return {t: 0, image: false}; }
function centreAt() { return null; }
""" + functions + r"""
function view(layer, second) {
  S = {x: 0.5, y: 0.5, z: 6, w: 1920, h: 600, scrub: 0, selected: null, show: {towns: true, outlook: false, places: false},
       pin: null, enso: {boxes: false, regions: false}, layer: layer, second: second || "streets", compare: !!second, split: 0.5};
  drawMarks();
  return (marksG.innerHTML.match(/<text [^>]*>[^<]*/g) || []).map(function (t) {
    return [t.split(">")[1], t.match(/text-anchor="(\w+)"/)[1], Math.round(+t.match(/ x="([-0-9.]+)"/)[1])];
  });
}
console.log(JSON.stringify([view("geocolor", "streets"), view("streets", "geocolor"), view("geocolor")]));
""")
        # Its name goes to the left of the dot instead, on the imagery.
        self.assertEqual(got[0], [["Oklahoma City", "end", 929]])
        # Right of the divider, a name with no room on its right is left out
        # rather than drawn leftward across it (Edmond, under Norman's name).
        self.assertEqual(got[1], [["Norman", "start", 986], ["Tulsa", "start", 1105]])
        # Not compared, nothing changes.
        self.assertEqual(got[2], [["Norman", "start", 986], ["Oklahoma City", "end", 929],
                                  ["Tulsa", "start", 1105]])

    def test_the_nino_boxes_are_named_on_every_copy_in_view(self):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "near", "copies", "mx", "ensoLabels", "signedText"))
        got = _node_json(self, r"""
var TILE = 256, S = {x: 0.5, z: 1, w: 1920, enso: {boxes: true, regions: false}};
var D = {enso: {boxes: [{lon0: 190, lon1: 240, lat0: -5, lat1: 5, label: "Nino 3.4", anomaly: 1.8}]}};
function sx(lon, k) { return (mx(lon) + k) * 512 + 704; }
function sy() { return 300; }
function off(x) { return x < 0 || x > 1920; }
function label(x) { return "L" + Math.round(x); }
""" + functions + r"""
console.log(JSON.stringify(ensoLabels(sx, sy, off, label)));
""")
        self.assertEqual(len(got), 4)


    def test_a_region_shown_alone_is_named_whatever_its_status(self):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "near", "copies", "mx", "ensoLabels", "signedText"))
        got = _node_json(self, r"""
var TILE = 256, S = {x: 0.5, z: 3, w: 1920, enso: {boxes: false, regions: false, shown: "Peru"}};
var D = {enso: {boxes: [], links: [
  {region: "Peru", scope: "regional", status: "", boxes: [[-82, -75, -15, -3]]},
  {region: "Chile", scope: "regional", status: "in play", boxes: [[-75, -70, -40, -30]]}]}};
function sx(lon, k) { return (mx(lon) + k) * 2048; }
function sy() { return 300; }
function off(x) { return x < 0 || x > 1920; }
function label(x, y, a, lines) { return lines[0][0]; }
""" + functions + r"""
var out = [ensoLabels(sx, sy, off, label)];
S.enso.regions = true; out.push(ensoLabels(sx, sy, off, label));
S.enso.regions = false; S.enso.shown = null; out.push(ensoLabels(sx, sy, off, label));
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, [["Peru"], ["Peru", "Chile"], []])

    def test_a_nino_name_with_no_room_above_its_box_goes_below_it(self):
        # At zoom 3 the four boxes' names, each above its box's northwest
        # corner, left Nino 3's out: the name of Nino 3.4 fills the 20 degrees
        # between their western edges. Where there is no room above, a name
        # now goes under its box before it is left out.
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "origin", "near", "copies", "clamp", "mx", "my", "rad", "esc", "pct",
            "labelled", "labelledBase", "namedAt", "townsWhy", "drawMarks", "ensoLabels", "signedText"))
        boxes = [dict(b, anomaly=a) for b, a in zip(worldmap._boxes(None), (0.1, 2.2, 2.9, 3.9))]
        got = _node_json(self, r"""
var TILE = 256, HOUR = 3600000, NM = 1.852, CIRCUMFERENCE = 40075.017;
var LAYERS = {}, PLACES = [], BYPOP = null, STORMS = [], BYID = {}, marksG = {innerHTML: ""};
var D = {outlook: [], invests: [], style: {outlook: {}}, enso: {boxes: """ + json.dumps(boxes) + r"""}};
function base() { return {t: 0, image: false}; }
function centreAt() { return null; }
""" + functions + r"""
var S = {x: mx(-150), y: my(0), z: 3, w: 1540, h: 600, scrub: 0, selected: null, pin: null,
         show: {towns: false, outlook: false, places: false}, enso: {boxes: true, regions: false},
         layer: "geocolor", compare: false};
var o = origin(), out = [];
drawMarks();
D.enso.boxes.forEach(function (b) {
  var at = marksG.innerHTML.match(new RegExp('y="([-0-9.]+)"[^>]*>' + b.label.split("+").join("[+]") + " "));
  out.push(at ? [b.label, +at[1] < my(b.lat1) * o.W + o.top ? "above" : +at[1] > my(b.lat0) * o.W + o.top ? "below" : "inside"] : [b.label, null]);
});
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, [["Niño 4", "above"], ["Niño 3.4", "above"],
                               ["Niño 3", "below"], ["Niño 1+2", "above"]])

@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestEsriCoverageRuns(unittest.TestCase):
    """Where Esri's imagery stops, learned once and used, run under node."""

    def test_a_level_without_imagery_rules_out_every_level_under_it(self):
        # Esri's placeholder at one level means none under it has imagery
        # either; zooming further in asked for each deeper level again.
        functions = _js_function(stormdesk.script(), "present")
        got = _node_json(self, r"""
var NODATA = {"satellite/16/100/200": true, "satellite/15/50/100": true};
""" + functions + r"""
console.log(JSON.stringify([present("satellite", 19, 803, 1601), present("satellite", 16, 100, 200),
                            present("satellite", 17, 202, 402), present("satellite", 19, 5, 5),
                            present("streets", 19, 803, 1601), present("satellite", 16, -65436, 200)]));
""")
        # The last is the same tile one world to the west: its column stays
        # where it was asked for, and the key wraps.
        self.assertEqual(got, [{"z": 14, "c": 25, "r": 50}, {"z": 14, "c": 25, "r": 50},
                               {"z": 14, "c": 25, "r": 50}, {"z": 19, "c": 5, "r": 5},
                               {"z": 19, "c": 803, "r": 1601}, {"z": 14, "c": -16359, "r": 50}])

    def test_an_esri_placeholder_redraws_the_tiles_not_the_marks(self):
        # A placeholder changes only which tile is asked for; each one used to
        # rebuild every storm track, region and box as it arrived.
        functions = "\n".join(_js_function(stormdesk.script(), n)
                              for n in ("tally", "placeholder", "tileLoaded"))
        got = _node_json(self, r"""
var MAPS = {}, NODATA = {}, geoDirty = false, renders = 0;
function dirty() { geoDirty = true; renders++; }
function requestRender() { renders++; }
function fadeTile() { return false; }
function setAside() {}
function sample() { return null; }
var grey = []; for (var i = 0; i < 256; i++) grey.push(204, 204, 204, 255);
function pixels() { return grey; }
""" + functions + r"""
var tile = {_grey: true, _map: "streets", _name: "streets", _z: 3, _c: 9, _r: 2, style: {}};
tileLoaded.call(tile);
console.log(JSON.stringify([NODATA, tile.style.visibility, geoDirty, renders, MAPS.streets]));
""")
        self.assertEqual(got, [{"streets/3/1/2": True}, "hidden", False, 1, {"ok": 1, "failed": 0}])


class TestTouchZoom(unittest.TestCase):
    """Two fingers pinch. A handler that kept one pointer turned a pinch into
    a pan, which is what the atlas did on a tablet while its hint promised a
    pinch."""

    def assert_pinches(self, js: str):
        self.assertRegex(js, r"pointers\s*=\s*new Map\(\)")
        self.assertRegex(js, r"pointers\.size\s*===\s*2")
        self.assertRegex(js, r"function pinch\(")

    def test_the_atlas_follows_both_fingers(self):
        self.assert_pinches(atlasview._JS)

    def test_the_globe_follows_both_fingers(self):
        self.assert_pinches(globe.GLOBE_JS)


class TestReportOutlook(_DeskFixtures, unittest.TestCase):
    """The report's formation outlook, and what each storm's centre issued."""

    def areas(self):
        return [
            outlook.Disturbance(
                centre="NHC", basin="EP", label="South of the Gulf of Tehuantepec",
                lon=-95.0, lat=12.0, chance_2day=40, chance_7day=90, potential="high",
                text="", area=(), arrow=(), alert=False,
                issued="Fri Sep 25 11:40:21 2026", key="ep1"),
            outlook.Disturbance(
                centre="CPHC", basin="CP",
                label="Well East-Southeast of the Hawaiian Islands", lon=-145.0,
                lat=12.0, chance_2day=20, chance_7day=50, potential="medium", text="",
                area=(), arrow=(), alert=False, issued="Fri Sep 25 12:00:00 2026",
                key="cp1"),
            outlook.Disturbance(
                centre="JTWC", basin="WP", label="Invest 97W", lon=140.0, lat=10.0,
                chance_2day=None, chance_7day=None, potential="medium", text="",
                area=(), arrow=(), alert=True, issued="2026-09-25T06:00:00Z", key="97w"),
        ]

    def invest(self):
        return cyclones.Storm(basin="AL", number=90, year=2026, name="Invest 90L",
                              track=(self.fix("2026092512", 0, 12.0, -40.0, 25, "DB"),),
                              invest=True)

    def outlook_text(self, **extra) -> str:
        return "\n".join(report._section_outlook(self.state(**extra)))

    def protective_text(self, storm) -> str:
        # Within NAMING_KM of every breakpoint of Nolo's watches.
        town = atlasdata.Place("Isla Socorro", "Mexico", "Colima", 250,
                                -110.0, 18.8, False)
        with mock.patch.object(atlasdata, "PLACES", (town,)):
            return "\n".join(report._protective(storm))

    def test_the_outlook_prints_straight_after_the_storms(self):
        self.assertEqual(report.SECTIONS.index("outlook"),
                         report.SECTIONS.index("cyclones") + 1)

    def test_each_area_has_its_two_and_seven_day_chances(self):
        text = self.outlook_text(outlook=self.areas())
        self.assertRegex(text, r"South of the Gulf of Tehuantepec\s+40%\s+90%\s+high")
        self.assertRegex(text, r"Well East-Southeast of the Hawaiian Islands\s+20%\s+50%\s+medium")
        self.assertIn("NHC east Pacific outlook, issued 2026-09-25 11:40 UTC", text)
        self.assertIn("CPHC central Pacific outlook, issued 2026-09-25 12:00 UTC", text)

    def test_a_jtwc_disturbance_has_its_potential_and_any_alert(self):
        text = self.outlook_text(outlook=self.areas())
        self.assertRegex(text, r"Invest 97W[^\n]*10\.0N 140\.0E")
        self.assertIn("medium", text.split("Invest 97W", 1)[1])
        self.assertIn("formation alert", text)

    def test_a_formation_alert_says_until_when_and_what_the_system_is_doing(self):
        alert = jtwc.formation_alert(fixture("jtwc_wp9326.tcw"),
                                     "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw")
        [[area]] = jtwc.alerted([jtwc.disturbances(fixture("jtwc_abpw_93w.txt"))], [alert], {})
        text = " ".join(self.outlook_text(outlook=[area]).split())
        self.assertIn("a tropical cyclone formation alert is in effect until "
                      "2026-09-30 17:00 UTC", text)
        self.assertIn("JTWC's alert of 2026-09-29 17:00 UTC: moving west-northwest at "
                      "14 kt, winds 18 to 23 kt, pressure near 1005 mb.", text)

    def test_a_formation_alert_past_its_time_is_said_to_have_run_out(self):
        alert = jtwc.formation_alert(fixture("jtwc_wp9326.tcw"),
                                     "https://www.metoc.navy.mil/jtwc/products/wp9326.tcw")
        [[area]] = jtwc.alerted([jtwc.disturbances(fixture("jtwc_abpw_93w.txt"))], [alert], {})
        state = self.state(outlook=[area])
        state.run_at = "2026-09-30T18:05:00+00:00"
        text = " ".join("\n".join(report._section_outlook(state)).split())
        self.assertIn("high potential for a significant tropical cyclone within 24 hours; "
                      "JTWC's formation alert ran to 2026-09-30 17:00 UTC and nothing newer "
                      "has been read.", text)
        self.assertNotIn("in effect", text)
        self.assertIn("JTWC's alert of 2026-09-29 17:00 UTC: moving west-northwest", text)

    def test_invests_are_listed_as_not_yet_storms(self):
        text = self.outlook_text(invests=[self.invest()])
        self.assertRegex(text, r"Invest 90L\s+12\.0N 40\.0W\s+25 kt")

    def test_a_quiet_outlook_says_so(self):
        self.assertIn("No area is being watched for formation", self.outlook_text())

    def test_a_storm_under_watches_prints_each_kind_and_its_coast(self):
        text = self.protective_text(self.nolo())
        self.assertIn("NHC advisory 20", text)
        self.assertRegex(text, r"Hurricane Watch\s+near Isla Socorro")
        self.assertRegex(text, r"Tropical Storm Warning\s+near Isla Socorro")
        self.assertRegex(text, r"Peak storm surge\s+Isla Socorro 1-3 ft")

    def test_a_coast_is_named_once_however_many_stretches_fall_near_it(self):
        storm = self.warned(self.nolo(), "Hurricane Warning",
                            ((-110.9, 18.7), (-110.8, 18.8), (-110.9, 18.9), (-110.9, 18.7)),
                            ((-110.2, 19.0), (-109.6, 18.6)),
                            ((-109.9, 18.5), (-109.8, 18.4)))
        text = self.protective_text(storm)
        self.assertRegex(text, r"(?m)Hurricane Warning\s+on the coast near Isla Socorro$")
        self.assertNotIn("; near Isla Socorro", text)

    def test_a_product_from_another_advisory_says_which(self):
        nolo = self.nolo()
        nolo.advisory = dict(nolo.advisory, advisory="021")
        nolo.products = dataclasses.replace(nolo.products, advisories=(
            ("watches", "20"), ("cone", "20"), ("surge", "20"), ("winds", "20")))
        text = self.protective_text(nolo)
        self.assertIn("Protective products, NHC advisory 21:", text)
        self.assertRegex(text, r"Hurricane Watch\s+near Isla Socorro \(advisory 20\)")
        self.assertRegex(text, r"Peak storm surge\s+Isla Socorro 1-3 ft \(advisory 20\)")

    def test_the_official_wind_probabilities_are_printed_highest_first(self):
        text = self.protective_text(self.nolo())
        self.assertRegex(text, r"ISLA SOCORRO\s+52%\s+22%\s+9%")
        self.assertIn("advisory 20, issued 2026-09-25 15:00 UTC", text)

    def test_a_dash_in_the_wind_table_is_explained_where_one_is_printed(self):
        self.assertNotIn("A dash:", self.protective_text(self.nolo()))
        storm = self.nolo()
        winds = storm.products.winds
        storm.products = dataclasses.replace(storm.products, winds=dataclasses.replace(
            winds, rows=winds.rows + (
                tcproducts.WindProbability("CLARION", 34, (0, 1, 2, 4, 5, 5, 5)),)))
        text = self.protective_text(storm)
        self.assertRegex(text, r"CLARION\s+5%\s+-\s+-")
        self.assertIn("A dash: the product has no line for that wind at that place.", text)

    def test_none_in_effect_and_not_fetched_are_told_apart(self):
        quiet = self.protective_text(self.polo())
        self.assertIn("No coastal watches or warnings are in effect", quiet)
        lost = self.polo(products=tcproducts.Products(watches=None, cone=(), surge=(),
                                                      winds=None, advisory="20"),
                         links={"watches": self.WW, "cone": "", "surge": "", "winds": ""})
        self.assertIn("could not be fetched", self.protective_text(lost))

    def test_a_jtwc_storm_points_to_the_national_services(self):
        self.assertIn("national meteorological service",
                      self.protective_text(self.surigae()))

    def test_every_line_is_ascii_and_fits_the_report(self):
        lines = (report._section_outlook(self.state(outlook=self.areas(),
                                                    invests=[self.invest()]))
                 + self.protective_text(self.nolo()).splitlines())
        for line in lines:
            self.assertLessEqual(len(line), report.WIDTH, line)
            self.assertTrue(line.isascii(), line)


class TestAlertEscalation(unittest.TestCase):
    """A standing alert that gets worse is announced, and the log keeps up."""

    CODE = "tc_threat_ep052026_acapulco"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.conn = storage.connect(Path(self.tmp.name) / "test.db")

    def tearDown(self):
        self.conn.close()
        self.tmp.cleanup()

    def raise_(self, level, title, when):
        alert = alerts.Alert(code=self.CODE, level=level, title=title,
                             detail="d", kind="cyclone")
        return alerts.reconcile(self.conn, [alert], when).alerts[0]

    def test_an_escalation_is_announced(self):
        self.raise_(alerts.WATCH, "passes 240 km from Acapulco in 72 h",
                    "2026-09-20T00:00:00")
        alert = self.raise_(alerts.CRITICAL, "passes 40 km from Acapulco in 24 h",
                            "2026-09-22T00:00:00")
        self.assertFalse(alert.is_new)
        self.assertEqual(getattr(alert, "escalated_from", None), alerts.WATCH)
        # The condition began on the 20th; it did not restart on the 22nd.
        self.assertEqual(alert.first_seen, "2026-09-20T00:00:00")

    def test_the_log_holds_the_current_level_and_title(self):
        self.raise_(alerts.WATCH, "passes 240 km from Acapulco in 72 h",
                    "2026-09-20T00:00:00")
        self.raise_(alerts.CRITICAL, "passes 40 km from Acapulco in 24 h",
                    "2026-09-22T00:00:00")
        (row,) = storage.open_alerts(self.conn)
        self.assertEqual(row["level"], alerts.CRITICAL)
        self.assertEqual(row["title"], "passes 40 km from Acapulco in 24 h")

    def test_an_easing_is_logged_but_not_announced(self):
        self.raise_(alerts.CRITICAL, "passes 40 km from Acapulco in 24 h",
                    "2026-09-20T00:00:00")
        alert = self.raise_(alerts.WATCH, "passes 240 km from Acapulco in 12 h",
                            "2026-09-21T00:00:00")
        self.assertFalse(alert.is_new)
        self.assertIsNone(getattr(alert, "escalated_from", None))
        (row,) = storage.open_alerts(self.conn)
        self.assertEqual(row["level"], alerts.WATCH)

    def test_the_report_and_the_feed_say_it_escalated(self):
        alert = alerts.Alert(code=self.CODE, level=alerts.CRITICAL,
                             title="Polo passes 40 km from Acapulco", detail="d",
                             kind="cyclone", first_seen="2026-09-20T00:00:00")
        alert.escalated_from = alerts.WATCH
        state = SimpleNamespace(alert_set=alerts.AlertSet(alerts=[alert]))
        text = "\n".join(report._section_alerts(state))
        self.assertIn("Polo passes 40 km from Acapulco  ESCALATED from WATCH", text)
        feed = panels.alert_feed(state)
        self.assertIn("up from watch", feed)


# ---------------------------------------------------------------------------
# End to end, against the cached feeds this repo ships
# ---------------------------------------------------------------------------


CACHE = ROOT / "data" / "raw"


# ---------------------------------------------------------------------------
# The spatial tier: gridded fields, sections, meshes and the renderers over them
# ---------------------------------------------------------------------------

# A three-by-three ERDDAP griddap response. The units row under the names, the
# unsorted rows and the NaN over land are all things the live feed really does.
MAP_CSV = """time,latitude,longitude,anom
UTC,degrees_north,degrees_east,degree_C
2026-09-02T12:00:00Z,0.0,210.0,3.0
2026-09-02T12:00:00Z,-1.0,200.0,1.5
2026-09-02T12:00:00Z,-1.0,210.0,2.0
2026-09-02T12:00:00Z,-1.0,220.0,NaN
2026-09-02T12:00:00Z,0.0,200.0,2.5
2026-09-02T12:00:00Z,0.0,220.0,3.5
2026-09-02T12:00:00Z,1.0,200.0,0.5
2026-09-02T12:00:00Z,1.0,210.0,1.0
2026-09-02T12:00:00Z,1.0,220.0,1.5
"""

# Two moorings on the equator, four depths each, over two months. 143E is the
# decommissioned case and reports in the first month only.
TAO_CSV = """time,latitude,longitude,depth,T_20
UTC,degrees_north,degrees_east,m,degree_C
2026-07-15T00:00:00Z,0.0,143.0,50.0,29.0
2026-07-15T00:00:00Z,0.0,165.0,50.0,29.0
2026-07-15T00:00:00Z,0.0,165.0,100.0,25.0
2026-07-15T00:00:00Z,0.0,165.0,150.0,19.0
2026-07-15T00:00:00Z,0.0,165.0,200.0,15.0
2026-07-15T00:00:00Z,0.0,265.0,50.0,24.0
2026-07-15T00:00:00Z,0.0,265.0,100.0,21.0
2026-07-15T00:00:00Z,0.0,265.0,150.0,17.0
2026-07-15T00:00:00Z,0.0,265.0,200.0,13.0
2026-08-15T00:00:00Z,0.0,165.0,50.0,29.4
2026-08-15T00:00:00Z,0.0,165.0,100.0,25.4
2026-08-15T00:00:00Z,0.0,165.0,150.0,19.4
2026-08-15T00:00:00Z,0.0,165.0,200.0,15.4
2026-08-15T00:00:00Z,0.0,265.0,50.0,24.4
2026-08-15T00:00:00Z,0.0,265.0,100.0,21.4
2026-08-15T00:00:00Z,0.0,265.0,150.0,17.4
2026-08-15T00:00:00Z,0.0,265.0,200.0,13.4
"""

# The isotherm feed is a different column of the same array. 143E appears in
# one month of four: a mooring that no longer exists, not a gap.
ISO_CSV = """time,latitude,longitude,ISO_6
UTC,degrees_north,degrees_east,m
2026-05-15T00:00:00Z,0.0,143.0,150.0
2026-05-15T00:00:00Z,0.0,165.0,150.0
2026-05-15T00:00:00Z,0.0,265.0,60.0
2026-06-15T00:00:00Z,0.0,165.0,155.0
2026-06-15T00:00:00Z,0.0,265.0,70.0
2026-07-15T00:00:00Z,0.0,165.0,160.0
2026-07-15T00:00:00Z,0.0,265.0,85.0
2026-08-15T00:00:00Z,0.0,165.0,161.0
2026-08-15T00:00:00Z,0.0,265.0,109.0
"""


def flat_field(rows, cols, value=1.0, units="degrees C"):
    """A constant field with list rows, so a test can poke a value into it."""
    return grids.Field(
        x=tuple(float(c) for c in range(cols)),
        y=tuple(float(r) for r in range(rows)),
        values=[[value for _ in range(cols)] for _ in range(rows)],
        label="test", units=units, as_of="2026-09-02",
    )


class TestGridReading(unittest.TestCase):
    def test_erddap_csv_drops_the_units_row(self):
        names, rows = grids.read_csv(MAP_CSV)
        self.assertEqual(names[-1], "anom")
        self.assertEqual(len(rows), 9)
        self.assertNotIn("degree_C", [str(cell) for cell in rows[0]])

    def test_nan_becomes_none_not_a_float(self):
        grid = grids.grid_map(MAP_CSV, "anom", "t", "degrees C")
        self.assertIsNone(grid.values[grid.y.index(-1.0)][grid.x.index(220.0)])
        self.assertAlmostEqual(grid.coverage(), 8 / 9)

    def test_axes_are_sorted_even_though_the_feed_need_not_be(self):
        grid = grids.grid_map(MAP_CSV, "anom", "t", "degrees C")
        self.assertEqual(grid.y, (-1.0, 0.0, 1.0))
        self.assertEqual(grid.x, (200.0, 210.0, 220.0))
        self.assertEqual(grid.as_of, "2026-09-02")

    def test_box_mean_weights_by_the_cosine_of_latitude(self):
        grid = grids.Field(
            x=(200.0, 210.0), y=(-60.0, 0.0),
            values=((0.0, 0.0), (4.0, 4.0)),
            label="t", units="degrees C", as_of="2026-09-02",
        )
        box = grids.Box("b", "B", 195.0, 215.0, -70.0, 10.0)
        # cos(60) = 0.5, so the equatorial row carries two thirds of the weight
        # and an unweighted mean would wrongly report 2.0.
        self.assertAlmostEqual(grids.box_mean(grid, box), 4.0 / 1.5, places=6)

    def test_warm_pool_edge_is_the_easternmost_crossing(self):
        grid = grids.Field(
            x=(180.0, 190.0, 200.0, 210.0), y=(0.0,),
            values=((30.0, 29.0, 27.0, 26.0),),
            label="t", units="degrees C", as_of="2026-09-02",
        )
        self.assertEqual(grids.warm_pool_edge(grid, 28.0), 190.0)

    def test_warm_pool_edge_reads_only_the_equatorial_rows(self):
        grid = grids.Field(
            x=(180.0, 260.0), y=(0.0, 20.0),
            values=((29.0, 26.0), (29.0, 29.0)),
            label="t", units="degrees C", as_of="2026-09-02",
        )
        self.assertEqual(grids.warm_pool_edge(grid, 28.0), 180.0)

    def test_warm_pool_edge_ends_where_the_pool_does(self):
        # Warm from 150E to 200E, cold from 210E, then one warm coastal cell at
        # 280E. On 8 September 2026 that coastal water put the "edge" at 78.9W
        # while the pool itself ended near 109W.
        grid = grids.Field(
            x=(150.0, 160.0, 170.0, 180.0, 190.0, 200.0, 210.0, 240.0, 270.0, 280.0),
            y=(0.0,),
            values=((29.5, 29.8, 29.6, 29.2, 28.8, 28.3, 27.6, 26.9, 26.4, 28.6),),
            label="t", units="degrees C", as_of="2026-09-08",
        )
        self.assertEqual(grids.warm_pool_edge(grid, 28.0), 200.0)

    def test_the_walk_starts_in_the_pacific_not_the_maritime_continent(self):
        # The live grid starts at 100E. A coastal Borneo cell at 111E reads
        # 30.6 C - warmer than anything in the Pacific - and the Maluku Sea
        # upwells to 27.3 C at 126E, so a walk from the warmest cell anywhere
        # west of 160W stopped at 124E.
        grid = grids.Field(
            x=(110.0, 126.0, 140.0, 170.0, 200.0, 210.0), y=(0.0,),
            values=((30.6, 27.3, 30.2, 29.3, 28.4, 27.5),),
            label="t", units="degrees C", as_of="2026-09-08",
        )
        self.assertEqual(grids.warm_pool_edge(grid, 28.0), 200.0)

    def test_land_inside_the_pool_does_not_end_it(self):
        grid = grids.Field(
            x=(150.0, 160.0, 170.0, 180.0), y=(0.0,),
            values=((29.5, None, 29.0, 27.0),),
            label="t", units="degrees C", as_of="2026-09-08",
        )
        self.assertEqual(grids.warm_pool_edge(grid, 28.0), 170.0)

    def test_no_pool_has_no_edge(self):
        grid = grids.Field(
            x=(150.0, 180.0, 210.0, 280.0), y=(0.0,),
            values=((27.5, 27.0, 26.0, 28.5),),
            label="t", units="degrees C", as_of="2026-09-08",
        )
        self.assertIsNone(grids.warm_pool_edge(grid, 28.0))

    def test_the_sst_map_caption_states_the_sampling_it_has(self):
        # The Pacific map is every second point of the quarter-degree OISST
        # grid: half a degree, not the "one-degree sample" it claimed.
        xs = tuple(180.0 + 0.5 * i for i in range(5))
        grid = grids.Field(
            x=xs, y=(-0.5, 0.0, 0.5),
            values=tuple(tuple(1.0 for _ in xs) for _ in range(3)),
            label="t", units="degrees C", as_of="2026-09-08",
        )
        html = fields.sst_map(grid, {}, None)
        self.assertIn("half-degree sample of the quarter-degree analysis", html)
        self.assertNotIn("one-degree sample", html)

    def test_a_sampled_field_table_says_how_in_english(self):
        # The global map's twin was captioned "(every 35 by 90 cell)".
        def field(rows, cols, y_name="latitude"):
            return grids.Field(
                x=tuple(float(i) for i in range(cols)),
                y=tuple(float(j) for j in range(rows)),
                values=tuple(tuple(0.0 for _ in range(cols)) for _ in range(rows)),
                label="t", units="degrees C", as_of="2026-09-08", y_name=y_name)

        html = fields.field_table(field(70, 180), "sst", max_rows=2, max_cols=2)
        self.assertIn("(every 35th latitude and every 90th longitude of the grid)",
                      html)
        self.assertNotIn(" cell)", html)
        html = fields.field_table(field(22, 42, "time"), "hov", max_rows=11,
                                  max_cols=2)
        self.assertIn("(every 2nd time step and every 21st longitude of the grid)",
                      html)
        html = fields.field_table(field(10, 36, "depth"), "section",
                                  max_rows=10, max_cols=3)
        self.assertIn("(every depth and every 12th longitude of the grid)", html)
        html = fields.field_table(field(10, 13), "small", max_rows=10, max_cols=1)
        self.assertIn("(every latitude and every 13th longitude of the grid)", html)

    def test_the_global_map_caption_states_the_sampling_it_has(self):
        # The global request is every point of the quarter-degree grid, and
        # the caption said "at two and a half degrees".
        for step, words in ((0.25, "the full quarter-degree analysis"),
                            (2.5, "a 2.5-degree sample of the quarter-degree "
                                  "analysis")):
            xs = tuple(0.125 + step * i for i in range(5))
            grid = grids.Field(
                x=xs, y=(-0.125, 0.125, 0.375),
                values=tuple(tuple(1.0 for _ in xs) for _ in range(3)),
                label="t", units="degrees C", as_of="2026-09-08",
            )
            html = fields.global_map(grid)
            with self.subTest(step=step):
                self.assertIn(words, html)
                self.assertNotIn("two and a half degrees", html)

    def test_contour_returns_segments_on_the_level(self):
        grid = grids.Field(
            x=(0.0, 1.0), y=(0.0, 1.0),
            values=((0.0, 0.0), (2.0, 2.0)),
            label="t", units="x", as_of="2026-09-02",
        )
        segments = grids.contour(grid, 1.0)
        self.assertTrue(segments)
        for segment in segments:
            for _, y in segment:
                self.assertAlmostEqual(y, 0.5)

    def test_robust_span_ignores_the_tails(self):
        grid = flat_field(1, 100)
        grid.values[0][0] = -500.0
        grid.values[0][-1] = 500.0
        low, high = grid.robust_span()
        self.assertGreater(low, -500.0)
        self.assertLess(high, 500.0)

    def test_coverage_of_an_empty_field_is_zero_not_an_error(self):
        grid = grids.Field(x=(), y=(), values=(), label="t", units="x")
        self.assertEqual(grid.coverage(), 0.0)
        self.assertEqual(grid.span(), (-1.0, 1.0))

    def test_age_days_reads_both_stamp_shapes(self):
        self.assertEqual(grids.age_days("2026-09-01", date(2026, 9, 17)), 16)
        self.assertEqual(grids.age_days("2026-08", date(2026, 9, 17)), 47)
        self.assertIsNone(grids.age_days("not a date"))
        self.assertIsNone(grids.age_days(""))

    def test_longitude_and_latitude_names(self):
        self.assertEqual(grids.lon_name(165.0), "165E")
        self.assertEqual(grids.lon_name(180.0), "180")
        self.assertEqual(grids.lon_name(250.0), "110W")
        self.assertEqual(grids.lat_name(0.0), "EQ")
        self.assertEqual(grids.lat_name(5.0), "5N")
        self.assertEqual(grids.lat_name(-5.0), "5S")


class TestMooringSection(unittest.TestCase):
    def test_section_interpolates_onto_a_common_depth_axis(self):
        grid = grids.section(TAO_CSV)
        self.assertEqual(grid.y, grids.SECTION_DEPTHS)
        self.assertEqual(grid.as_of, "2026-08")
        row = grid.y.index(100.0)
        self.assertAlmostEqual(grid.values[row][grid.x.index(165.0)], 25.4)
        self.assertAlmostEqual(grid.values[row][grid.x.index(265.0)], 21.4)

    def test_section_does_not_extrapolate_past_the_deepest_sensor(self):
        grid = grids.section(TAO_CSV)
        deepest = grid.y.index(300.0)
        self.assertTrue(all(v is None for v in grid.values[deepest]))

    def test_section_interpolates_across_longitude_between_moorings(self):
        grid = grids.section(TAO_CSV)
        row = grid.y.index(100.0)
        middle = grid.values[row][grid.x.index(215.0)]
        self.assertIsNotNone(middle)
        self.assertTrue(21.4 < middle < 25.4)

    def test_isotherm_interpolates_the_crossing(self):
        built, stamp = grids.profiles(TAO_CSV)
        self.assertTrue(stamp.startswith("2026-08"))
        west = next(pr for pr in built if pr.lon == 165.0)
        # 25.4 degC at 100 m and 19.4 at 150 m: the 20 degC line sits at 145 m.
        self.assertAlmostEqual(west.isotherm(20.0), 145.0, places=6)

    def test_isotherm_is_none_when_the_column_never_crosses(self):
        warm = grids.Profile(165.0, (50.0, 100.0), (29.0, 28.0))
        self.assertIsNone(warm.isotherm(20.0))

    def test_profiles_use_the_latest_month_only(self):
        built, _ = grids.profiles(TAO_CSV)
        self.assertEqual([pr.lon for pr in built], [165.0, 265.0])

    def test_isotherm_hovmoller_drops_decommissioned_longitudes(self):
        grid = grids.iso_hovmoller(ISO_CSV, months=4)
        # 143E reported in one month of four. Keeping it would print a column
        # that is three quarters empty next to two that are full.
        self.assertNotIn(143.0, grid.x)
        self.assertEqual(grid.x, (165.0, 265.0))
        self.assertEqual(grid.y_labels[-1], "2026-08")
        self.assertEqual(grid.coverage(), 1.0)

    def test_tilt_averages_both_ends_and_shows_its_working(self):
        """Three panels and the report quote this, so it lives in one place."""
        drop, west, east = grids.tilt([160.0, 164.0, 140.0, 130.0, 110.0])
        self.assertAlmostEqual(west, 162.0)
        self.assertAlmostEqual(east, 120.0)
        self.assertAlmostEqual(drop, 42.0)
        # The quoted endpoints have to subtract to the quoted tilt, or the
        # sentence built from them contradicts itself in front of the reader.
        self.assertAlmostEqual(west - east, drop)

    def test_tilt_skips_moorings_that_never_crossed(self):
        self.assertEqual(
            grids.tilt([160.0, None, 164.0, 140.0, None, 130.0, 110.0]),
            grids.tilt([160.0, 164.0, 140.0, 130.0, 110.0]),
        )

    def test_tilt_declines_rather_than_averaging_one_end_with_itself(self):
        self.assertIsNone(grids.tilt([160.0, 120.0]))
        self.assertIsNone(grids.tilt([160.0, None, None, 120.0]))
        self.assertIsNotNone(grids.tilt([160.0, 164.0, 130.0, 110.0]))

    def test_interp_refuses_to_extrapolate(self):
        points = [(10.0, 1.0), (20.0, 2.0)]
        self.assertAlmostEqual(grids._interp(points, 15.0), 1.5)
        self.assertIsNone(grids._interp(points, 5.0))
        self.assertIsNone(grids._interp(points, 25.0))
        self.assertIsNone(grids._interp([], 15.0))


class TestCoastline(unittest.TestCase):
    def test_the_vendored_coastline_has_real_geometry(self):
        self.assertGreater(len(coastline.COASTLINE), 20)
        points = sum(len(line) for line in coastline.COASTLINE)
        self.assertGreater(points, 500)

    def test_segments_never_span_the_wrap(self):
        """A Pacific-centred frame must not join Asia to the Americas."""
        for line in coastline.segments(100.0, 300.0):
            for (lon0, _), (lon1, _) in zip(line, line[1:]):
                self.assertLess(abs(lon1 - lon0), 180.0)

    def test_segments_are_rewrapped_into_the_requested_frame(self):
        drawn = coastline.segments(100.0, 300.0)
        self.assertTrue(drawn)
        for line in drawn:
            self.assertGreaterEqual(len(line), 2)
            for lon, lat in line:
                self.assertTrue(-90.0 <= lat <= 90.0)
                self.assertTrue(-80.0 <= lon <= 480.0, lon)


class TestFieldRendering(unittest.TestCase):
    def plot(self, cols=2, rows=2):
        plot = fields.Plot(400, 200, (10, 10, 10, 10))
        plot.domain(0, cols - 1, 0, rows - 1)
        return plot

    def test_run_length_encoding_beats_one_rect_per_cell(self):
        grid = flat_field(20, 60)
        ramp = fields.Ramp("d", 11, -1.0, 1.0, diverging=True)
        # A constant field is one run per row, against 1200 separate cells.
        self.assertEqual(fields.draw_cells(self.plot(60, 20), grid, ramp), 20)

    def test_runs_break_on_a_colour_change_and_on_a_gap(self):
        grid = flat_field(1, 6)
        grid.values[0][2] = -1.0
        grid.values[0][4] = None
        ramp = fields.Ramp("d", 11, -1.0, 1.0, diverging=True)
        self.assertEqual(fields.draw_cells(self.plot(6, 1), grid, ramp), 4)

    def test_cells_carry_the_hover_contract_the_page_delegates_on(self):
        plot = self.plot()
        fields.draw_cells(plot, flat_field(2, 2),
                          fields.Ramp("d", 11, -1.0, 1.0, True),
                          row_label=lambda v, i: grids.lat_name(v),
                          col_label=grids.lon_name)
        markup = "".join(plot.parts)
        self.assertIn('class="hit"', markup)
        self.assertIn("data-label=", markup)
        self.assertIn("data-value=", markup)

    def test_cells_are_clipped_to_the_frame(self):
        plot = self.plot()
        fields.draw_cells(plot, flat_field(2, 2),
                          fields.Ramp("d", 11, -1.0, 1.0, True))
        self.assertIn("clip-path=", "".join(plot.parts))

    def test_a_clip_path_is_defined_once_per_plot(self):
        plot = self.plot()
        first = fields.clip_area(plot)
        self.assertEqual(first, fields.clip_area(plot))
        self.assertEqual("".join(plot.parts).count("<clipPath"), 1)

    def test_two_plots_get_two_clip_ids(self):
        """Two maps on one page share a DOM, so the ids cannot collide."""
        self.assertNotEqual(fields.clip_area(self.plot()),
                            fields.clip_area(self.plot()))

    def test_diverging_ramp_is_symmetric_about_zero(self):
        ramp = fields.Ramp("d", 11, -1.0, 4.0, diverging=True)
        self.assertEqual((ramp.low, ramp.high), (-4.0, 4.0))
        self.assertEqual(ramp.index(0.0), 5)
        self.assertEqual(ramp.index(-99.0), 0)
        self.assertEqual(ramp.index(99.0), 10)

    def test_sequential_ramp_survives_a_degenerate_span(self):
        ramp = fields.Ramp("q", 9, 5.0, 5.0)
        self.assertEqual((ramp.low, ramp.high), (5.0, 6.0))

    def test_colour_bar_precision_follows_the_span(self):
        # SSH spans about a fifth of a metre; at one decimal its bar would
        # print "-0.1, -0.1, +0.0, +0.0" and say nothing.
        self.assertEqual(fields.Ramp("d", 11, -0.1, 0.1, True).auto_fmt(), "{:+.2f}")
        self.assertEqual(fields.Ramp("d", 11, -4.0, 4.0, True).auto_fmt(), "{:+.1f}")
        self.assertEqual(fields.Ramp("p", 9, 0.0, 250.0).auto_fmt(), "{:+.0f}")

    def test_every_ramp_bar_is_labelled_with_its_units(self):
        bar = fields.Ramp("d", 11, -4.0, 4.0, True).bar("degrees C", "anomaly")
        self.assertIn("degrees C", bar)
        self.assertIn("anomaly", bar)
        self.assertIn("rampstrip", bar)
        self.assertEqual(bar.count("rampcell"), 11)

    def test_a_colour_bar_label_sits_where_its_value_is(self):
        # The labels were every second edge of the bar, spread evenly across
        # it: on an 11-step bar that is six labels for twelve edges, so the
        # last one, printed at the right-hand end where the bar reaches +4.0,
        # said +3.3, and nothing marked zero. A diverging bar is labelled at
        # its ends, its middle and halfway out, each at its own place.
        bar = fields.Ramp("d", 11, -3.0, 4.0, True).bar("degrees C", "anomaly")
        ticks = re.findall(r'<span class="ramptick" style="left:([\d.]+)%'
                           r'[^"]*">([^<]*)</span>', bar)
        self.assertEqual([label for _, label in ticks],
                         ["-4.0", "-2.0", "0", "+2.0", "+4.0"])
        self.assertEqual([float(left) for left, _ in ticks],
                         [0.0, 25.0, 50.0, 75.0, 100.0])
        # A sequential bar keeps its edge labels, at their own places, and
        # its top end: 0 to 9 in nine steps, labelled 0, 2, 4, 6, 8 and 9.
        bar = fields.Ramp("q", 9, 0.0, 9.0).bar("mm", "rain")
        ticks = re.findall(r'<span class="ramptick" style="left:([\d.]+)%'
                           r'[^"]*">([^<]*)</span>', bar)
        self.assertEqual([label for _, label in ticks],
                         ["+0.0", "+2.0", "+4.0", "+6.0", "+8.0", "+9.0"])
        for (left, label) in ticks:
            self.assertAlmostEqual(float(left), float(label) / 9.0 * 100.0,
                                   places=1)

    def test_ramp_css_defines_both_themes(self):
        css = fields.ramp_css()
        for prefix in ("--d0:", "--q0:", "--p0:"):
            self.assertIn(prefix, css)
        self.assertIn("prefers-color-scheme: dark", css)
        self.assertIn('[data-theme="dark"]', css)

    def test_field_table_says_when_it_decimated(self):
        table = fields.field_table(flat_field(40, 40), "caption",
                                   max_rows=10, max_cols=10)
        self.assertIn("caption", table)
        self.assertIn("every", table)


class TestThreeDimensions(unittest.TestCase):
    def test_projection_is_orthographic_and_turns_with_yaw(self):
        x, y, _ = space3d.project(1.0, 0.0, 0.0, 0.0, 0.0)
        self.assertAlmostEqual(x, 1.0)
        self.assertAlmostEqual(y, 0.0)
        self.assertAlmostEqual(space3d.project(1.0, 0.0, 0.0, 180.0, 0.0)[0], -1.0)

    def test_projection_has_no_perspective_divide(self):
        """Two equal anomalies must measure the same wherever they sit."""
        near = (space3d.project(0.5, -1.0, 0.0, 30.0, 25.0)[0]
                - space3d.project(-0.5, -1.0, 0.0, 30.0, 25.0)[0])
        far = (space3d.project(0.5, 1.0, 0.0, 30.0, 25.0)[0]
               - space3d.project(-0.5, 1.0, 0.0, 30.0, 25.0)[0])
        self.assertAlmostEqual(near, far)

    def test_depth_key_orders_the_painter_pass(self):
        # Quads are drawn in ascending depth, so the larger key is nearer.
        front = space3d.project(0.0, 1.0, 0.0, 0.0, 20.0)[2]
        back = space3d.project(0.0, -1.0, 0.0, 0.0, 20.0)[2]
        self.assertGreater(front, back)
        self.assertAlmostEqual(front, -back)

    def test_fit_puts_the_cloud_inside_the_frame_at_any_angle(self):
        cloud = [[x, y, z] for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
        for yaw, pitch in ((0, 0), (-38, 26), (0, -88), (-90, 8), (137, -61)):
            scale, cx, cy = space3d.fit_view(cloud, 620, 430, yaw, pitch)
            for point in cloud:
                sx, sy, _ = space3d.project(point[0], point[1], point[2], yaw, pitch)
                self.assertTrue(0 <= cx + sx * scale <= 620)
                self.assertTrue(0 <= cy + sy * scale <= 430)

    def test_fit_actually_fills_the_frame(self):
        """A rotation-invariant fit would leave the flat views two thirds empty."""
        cloud = [[x, y, 0.0] for x in (-1, 1) for y in (-1, 1)]
        scale, _, _ = space3d.fit_view(cloud, 620, 430, 0.0, -90.0)
        self.assertGreater(2 * scale, 430 * 0.8)

    def test_the_cloud_includes_the_axis_text_anchors(self):
        """Labels sit outside the box; excluding them would crop them away."""
        payload = {"kind": "line", "line": [{"p": [0.0, 0.0, 0.0]}],
                   "axes": [{"p": [[0.0, 0.0, 0.0]], "alt": [[9.0, 0.0, 0.0]]}]}
        self.assertIn([9.0, 0.0, 0.0], space3d._cloud(payload))

    def test_the_server_picture_and_the_client_share_one_transform(self):
        """The inline script must reproduce the fit, or the scene jumps on drag."""
        for needle in ("function fitView", "function cloud", "var pad = 18",
                       "return a.d - b.d"):
            self.assertIn(needle, space3d.SCENE_JS)

    def test_mesh_interpolation_fills_gaps_but_does_not_extrapolate(self):
        mesh = grids.Mesh(
            nodes=(grids.MeshNode(-2.0, 165.0, 150.0, 10.0),
                   grids.MeshNode(2.0, 165.0, 170.0, 20.0),
                   grids.MeshNode(-2.0, 265.0, 110.0, 30.0),
                   grids.MeshNode(2.0, 265.0, 130.0, 40.0)),
            label="iso", units="m", as_of="2026-09-01",
        )
        lons, lats, grid = space3d._interpolate_mesh(mesh)
        self.assertEqual(lons, [165.0, 265.0])
        at = {(lat, lon): grid[r][c]
              for r, lat in enumerate(lats) for c, lon in enumerate(lons)}
        # The equator sits between two known latitudes and is filled...
        self.assertAlmostEqual(at[(0.0, 165.0)]["h"], 160.0)
        self.assertAlmostEqual(at[(0.0, 165.0)]["a"], 15.0)
        # ...while 8S is outside the array and stays empty.
        self.assertIsNone(at[(-8.0, 165.0)])

    def test_mesh_interpolation_drops_longitudes_off_the_pacific(self):
        mesh = grids.Mesh(
            nodes=(grids.MeshNode(0.0, 65.0, 100.0),
                   grids.MeshNode(0.0, 165.0, 150.0)),
            label="iso", units="m",
        )
        self.assertEqual(space3d._interpolate_mesh(mesh)[0], [165.0])


class TestSpatialIntoTheReport(unittest.TestCase):
    def test_character_ramp_spans_the_range_monotonically(self):
        chars = report.SEQUENTIAL_CHARS
        picked = [report._char_for(v / 10.0, 0.0, 1.0, chars) for v in range(11)]
        self.assertEqual(picked[0], chars[0])
        self.assertEqual(picked[-1], chars[-1])
        self.assertEqual(picked, sorted(picked, key=chars.index))

    def test_missing_data_prints_a_space_not_a_zero(self):
        self.assertEqual(report._char_for(None, -1.0, 1.0, report.DIVERGING_CHARS), " ")

    def test_a_flat_field_does_not_divide_by_zero(self):
        chars = report.DIVERGING_CHARS
        self.assertEqual(report._char_for(1.0, 1.0, 1.0, chars), chars[len(chars) // 2])

    def test_decimation_keeps_both_ends(self):
        indices = report._decimate(tuple(range(100)), 10)
        self.assertLessEqual(len(indices), 10)
        self.assertEqual(indices[0], 0)
        self.assertEqual(indices[-1], 99)
        self.assertEqual(indices, sorted(set(indices)))

    def test_decimation_is_a_no_op_when_it_already_fits(self):
        self.assertEqual(report._decimate((1, 2, 3), 10), [0, 1, 2])

    def test_the_longitude_ruler_labels_both_ends(self):
        """A bare east edge reads as the end of the grid, and it is not."""
        lons = tuple(120.0 + (160.0 / 52.0) * i for i in range(53))
        marks, labels = report._lon_ruler(lons, indent=13)
        self.assertEqual(marks.strip()[0], "|")
        self.assertTrue(labels.strip().startswith("120E"))
        self.assertTrue(labels.rstrip().endswith("80W"))
        self.assertEqual(marks.index("|"), labels.index("1"))

    def test_the_longitude_ruler_survives_a_single_column(self):
        marks, labels = report._lon_ruler((165.0,), indent=3)
        self.assertEqual(marks.strip(), "|")
        self.assertEqual(labels.strip(), "165E")

    def test_the_character_key_labels_every_character(self):
        key = report._char_key(report.DIVERGING_CHARS, -4.0, 4.0, "degrees C")
        text = " ".join(key)
        for char in report.DIVERGING_CHARS:
            self.assertIn(f"{char}=", text)
        self.assertIn("blank = no data", text)

    def test_the_ascii_field_fits_the_report_width(self):
        grid = grids.section(TAO_CSV)
        lines = report._ascii_field(
            grid, report.SEQUENTIAL_CHARS, lambda r: f"{grid.y[r]:.0f}m",
            max_rows=16, max_cols=56, label_width=5, diverging=False, fmt="{:.1f}",
        )
        self.assertTrue(lines)
        for line in lines:
            self.assertLessEqual(len(line), report.WIDTH)

    def test_the_ascii_field_skips_rows_the_instrument_never_sampled(self):
        """A labelled blank line reads as a rendering fault, not as an absence."""
        grid = grids.section(TAO_CSV)
        lines = report._ascii_field(
            grid, report.SEQUENTIAL_CHARS, lambda r: f"{grid.y[r]:.0f}m",
            max_rows=31, max_cols=21, label_width=5, diverging=False, fmt="{:.1f}",
        )
        self.assertFalse([ln for ln in lines if ln.strip() == "0m"])


class TestGeography(unittest.TestCase):
    """The catalogue keyed by coordinate, which is what makes the globe work."""

    def test_every_teleconnection_has_a_footprint_and_every_footprint_a_link(self):
        # Either list non-empty means the globe silently drops a region, so the
        # assertion prints the names rather than just a count.
        self.assertEqual(geo.missing(), [])
        self.assertEqual(geo.orphaned(), [])

    def test_longitudes_come_back_in_the_half_open_range(self):
        self.assertEqual(geo.wrap180(0.0), 0.0)
        self.assertEqual(geo.wrap180(180.0), 180.0)
        self.assertEqual(geo.wrap180(-180.0), 180.0)
        self.assertEqual(geo.wrap180(200.0), -160.0)
        self.assertEqual(geo.wrap180(360.0), 0.0)
        self.assertAlmostEqual(geo.wrap180(280.5), -79.5)

    def test_a_region_across_the_antimeridian_is_found_from_both_sides(self):
        """Two boxes, not one wrapped box, so no consumer has to know the wrap."""
        west = [f.region for f in geo.at(170.0, -14.0)]
        east = [f.region for f in geo.at(-170.0, -14.0)]
        self.assertIn("Pacific island states", west)
        self.assertIn("Pacific island states", east)
        self.assertEqual(len(geo.BY_REGION["Pacific island states"].boxes), 2)

    def test_the_most_specific_claim_is_listed_first(self):
        # The Dry Corridor sits inside the Caribbean box. A reader clicking
        # Honduras wants the corridor, not the basin.
        found = [f.region for f in geo.at(-84.0, 14.0)]
        self.assertEqual(found[0], "Central American Dry Corridor")
        self.assertIn("Caribbean", found)

    def test_a_global_signal_does_not_crowd_out_the_local_answer(self):
        names = [f.region for f in geo.at(-77.0, -12.0)]
        self.assertNotIn("Global mean surface temperature", names)
        widened = [f.region for f in geo.at(
            -77.0, -12.0, scopes=(geo.REGIONAL, geo.BASIN, geo.GLOBAL))]
        self.assertIn("Global mean surface temperature", widened)

    def test_lima_resolves_to_the_coast_the_fishery_and_the_highlands(self):
        names = [f.region for f in geo.at(-77.0, -12.0)]
        self.assertEqual(names[0], "Coastal Peru and Ecuador")
        self.assertIn("Peruvian anchoveta fishery", names)
        self.assertIn("Highland malaria, East Africa and Andes", names)

    def test_a_place_with_no_catalogued_relationship_returns_nothing(self):
        """Silence has to stay distinguishable from coverage, not be faked."""
        self.assertEqual(geo.at(0.0, 51.5), [])      # London
        self.assertEqual(geo.at(139.7, 35.7), [])    # Tokyo
        self.assertEqual(geo.at(133.0, -24.0), [])   # central Australia


class TestGlobeProjection(unittest.TestCase):
    def test_a_point_survives_the_trip_through_the_inverse(self):
        """Click picking is this, backwards; if it drifts, every click is wrong."""
        for lon0, lat0 in ((-150.0, 12.0), (22.0, 4.0), (-100.0, 78.0)):
            for lon in range(-180, 180, 17):
                for lat in range(-85, 86, 13):
                    point = globe.project(float(lon), float(lat), lon0, lat0)
                    if point is None:
                        continue
                    back = globe.unproject(point[0], point[1], lon0, lat0)
                    self.assertIsNotNone(back)
                    self.assertAlmostEqual(back[1], float(lat), places=6)
                    delta = abs((back[0] - lon + 180.0) % 360.0 - 180.0)
                    self.assertLess(delta, 1e-5)

    def test_the_far_side_is_culled(self):
        self.assertIsNone(globe.project(30.0, -12.0, -150.0, 12.0))
        self.assertEqual(globe.project(-150.0, 12.0, -150.0, 12.0), (0.0, 0.0))

    def test_a_click_that_misses_the_globe_is_not_a_location(self):
        self.assertIsNone(globe.unproject(1.4, 0.0, 0.0, 0.0))
        self.assertIsNone(globe.unproject(0.8, 0.8, 0.0, 0.0))

    def test_the_quantised_field_is_one_character_per_cell(self):
        grid = flat_field(4, 5, value=1.0)
        grid.values[1][1] = None
        text = globe.encode(grid, 2.0)
        self.assertEqual(len(text), 20)
        self.assertEqual(text[6], globe.EMPTY_CHAR)
        self.assertEqual(set(text) - {globe.EMPTY_CHAR}, {"8"})

    def test_the_ramp_clamps_instead_of_running_off_the_end(self):
        self.assertEqual(globe.ramp_index(0.0, 4.0), 5)
        self.assertEqual(globe.ramp_index(99.0, 4.0), globe.STEPS - 1)
        self.assertEqual(globe.ramp_index(-99.0, 4.0), 0)

    def test_a_step_reads_back_within_half_a_step(self):
        """The panel quotes a number off the colour, so the error needs a bound."""
        half = 2.0 * 4.0 / globe.STEPS / 2.0
        for value in (-3.9, -1.0, 0.0, 0.4, 2.2, 3.8):
            index = globe.ramp_index(value, 4.0)
            self.assertLessEqual(abs(globe.step_value(index, 4.0) - value), half)


class TestGlobePanel(unittest.TestCase):
    def state(self, **over):
        grid = grids.Field(
            x=tuple(-180.0 + 45.0 * c for c in range(8)),
            y=tuple(-75.0 + 30.0 * r for r in range(6)),
            values=[[1.0 for _ in range(8)] for _ in range(6)],
            label="global sst", units="degrees C", as_of="2026-09-02",
        )
        return SimpleNamespace(
            spatial=SimpleNamespace(sst_global=over.get("grid", grid)),
            assessment=SimpleNamespace(
                index_name="RONI",
                index_latest=SimpleNamespace(value=over.get("index", 1.36)),
                scale=SimpleNamespace(flavour_index=over.get("flavour", 3.24)),
            ),
            forecast=SimpleNamespace(
                peak=SimpleNamespace(label=over.get("peak_label", "SON 2026"))),
            impacts=SimpleNamespace(peak_index=over.get("peak_index", 2.27)),
        )

    def payload(self, html: str) -> dict:
        """Pull the embedded payload back out the way the browser does."""
        raw = html.split("data-globe='", 1)[1].split("'>", 1)[0]
        return json.loads(unescape(raw))

    def test_the_caption_says_the_globe_can_be_pinched(self):
        html = globe.card(self.state())
        self.assertIn("pinch", html.split('<div class="ramp">')[0])
        self.assertIn("pinch", re.search(r'<p class="ghint">.*?</p>', html).group(0))

    def test_the_payload_survives_being_an_html_attribute(self):
        """One catalogue entry names the world's largest fishery, with an
        apostrophe in it. Unescaped, that single character closes the attribute
        early and the whole panel goes inert with no error anywhere."""
        html = globe.card(self.state())
        raw = html.split("data-globe='", 1)[1].split("'>", 1)[0]
        self.assertNotIn("'", raw)
        self.assertEqual(len(self.payload(html)["links"]), len(impacts.CATALOGUE))

    def test_the_picture_and_the_data_to_redraw_it_both_ship(self):
        html = globe.card(self.state())
        self.assertIn("<polygon", html)          # server-rendered cells
        self.assertIn('class="zone"', html)      # server-rendered footprints
        payload = self.payload(html)
        self.assertEqual(len(payload["grid"]["data"]),
                         payload["grid"]["rows"] * payload["grid"]["cols"])
        self.assertEqual(payload["view"]["lon"], globe.HOME[0])
        self.assertEqual(payload["view"]["lat"], globe.HOME[1])

    def test_a_run_with_no_global_field_drops_the_panel_rather_than_half_drawing(self):
        self.assertEqual(globe.card(self.state(grid=None)), "")

    def test_every_region_appears_in_the_table_twin(self):
        html = globe.card(self.state())
        table = html.split('<table class="dtable">', 1)[1]
        for link in impacts.CATALOGUE:
            self.assertIn(escape(link.region), table)

    def test_the_catalogue_is_scored_now_as_well_as_at_the_peak(self):
        """The whole point of the panel: what is already true against what comes."""
        links = globe.dossier(peak_index=2.27, current_index=0.3,
                              flavour_index=3.24, peak_label="SON 2026")
        moved = [link for link in links
                 if link["now"]["likelihood"] != link["peak"]["likelihood"]]
        self.assertTrue(moved, "no relationship changed between now and peak")
        for link in links:
            self.assertGreaterEqual(link["peak"]["margin"], link["now"]["margin"])

    def test_scoring_reuses_the_gating_rules_rather_than_restating_them(self):
        """Same inputs through the globe and through the report have to agree."""
        flavour = impacts.flavour_of(3.24)
        links = globe.dossier(2.27, 1.8, 3.24, "SON 2026")
        by_region = {link["region"]: link for link in links}
        for entry in impacts.CATALOGUE:
            margin, likelihood, _ = impacts.evaluate(entry, 2.27, flavour)
            self.assertEqual(by_region[entry.region]["peak"]["likelihood"],
                             likelihood)
            self.assertAlmostEqual(by_region[entry.region]["peak"]["margin"],
                                   round(margin, 2))

    def test_a_footprint_over_the_limb_is_dropped_whole(self):
        """Half a box drawn across the rim would read as a different region."""
        box = [170.0, 180.0, -20.0, 0.0]           # behind an Atlantic view
        ring = globe._box_ring(box, 0.0, 0.0)
        self.assertTrue(any(point is None for point in ring))
        self.assertEqual(globe._zones(
            [{"scope": geo.REGIONAL, "boxes": [box], "polarity": "dry"}],
            0.0, 0.0, 100.0, 120.0, 120.0), [])

    def test_the_likelihood_chip_carries_dots_as_well_as_the_word(self):
        """Colour alone would fail a greyscale print and a colourblind reader."""
        self.assertIn("●●●", globe._chip("likely"))
        self.assertIn("○○○", globe._chip("unlikely"))
        self.assertIn("likely", globe._chip("likely"))

    def test_the_script_carries_its_own_coastline_and_defs(self):
        script = globe.js()
        self.assertIn("var GLOBE_COAST=", script)
        self.assertIn("var GLOBE_DEFS=", script)
        self.assertIn("function unproject", script)
        # The redraw must repaint the no-data hatch, or a spin loses the land.
        self.assertIn("svg.innerHTML = DEFS +", script)


def _fix(stamp="2026092312", tau=0, lat=15.2, lon=-101.5, wind=130,
         pressure=925, stage="HU", tech="BEST", rmw=None, eye=None):
    return cyclones.Fix(stamp=stamp, tau=tau, lat=lat, lon=lon, wind=wind,
                        pressure=pressure, stage=stage, tech=tech,
                        rmw=rmw, eye=eye)



def _label_boxes(drawn: str) -> list:
    """Every label on a drawn map with the box a browser gives it.

    Half an em a character is what the system sans measures at these sizes;
    0.55 leaves a margin. The graticule's degrees sit outside the plot and
    are left out.
    """
    boxes = []
    for attrs, words in re.findall(r"<text([^>]*)>([^<]*)</text>", drawn):
        words = unescape(words)
        if re.fullmatch(r"\d+(\.\d+)?°[NSEW]?", words):
            continue
        x = float(re.search(r'\bx="([-\d.]+)"', attrs).group(1))
        y = float(re.search(r'\by="([-\d.]+)"', attrs).group(1))
        size = 12.0 if "endlabel" in attrs else 11.0
        width = 0.55 * size * len(words)
        anchor = re.search(r'text-anchor="(\w+)"', attrs)
        anchor = anchor.group(1) if anchor else "start"
        left = (x - width / 2 if anchor == "middle"
                else x - width if anchor == "end" else x)
        boxes.append((words, left, y - 0.75 * size, left + width,
                      y + 0.2 * size))
    return boxes


def _first_overlap(boxes):
    """The words of the first two boxes that overlap, or None."""
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            if a[1] < b[3] and b[1] < a[3] and a[2] < b[4] and b[2] < a[4]:
                return a[0], b[0]
    return None

def _loaded(basin: str, wind: int):
    """A storm made of four synoptic fixes at one intensity, so its ACE is a
    round number a test can assert against: 100 kt gives exactly 4.0."""
    return cyclones.Storm(basin=basin, number=1, year=2026, track=tuple(
        _fix(stamp=f"20260910{hour:02d}", wind=wind, stage="TS")
        for hour in cyclones.SYNOPTIC))


def _deck(rows) -> str:
    """An ATCF b-deck line, in the column order the real files use."""
    out = []
    for row in rows:
        stamp, tau, lat, lon, wind, pressure, stage, tech, radii = row[:9]
        # Columns 19 and 21 are the radius of maximum wind and the eye
        # diameter. A row may set them; the default is the shape a real file
        # usually has, an RMW with no eye reported.
        rmw, eye = (list(row[9:]) + [15, 0])[:2]
        out.append(
            f"EP, 17, {stamp},   , {tech}, {tau:>3}, {lat}, {lon}, {wind:>3}, "
            f"{pressure:>4}, {stage}, {radii}, NEQ,    0,    0,    0,    0, "
            f"1009,  180, {rmw:>3},  150, {eye:>3},   L,   0,    ,   0,   0, "
            "   POLO,  D,"
        )
    return "\n".join(out)


def _polo(ensemble_spread_by_tau=None):
    """Polo as the decks had it on 24 September: best track through 12Z, the
    official forecast issued from the 06Z advisory."""
    winds = (("2026092112", 55), ("2026092212", 140), ("2026092218", 155),
             ("2026092312", 130), ("2026092318", 125), ("2026092400", 140),
             ("2026092406", 140), ("2026092412", 135))
    track = tuple(_fix(stamp=s, wind=w, lat=16.7, lon=-103.9) for s, w in winds)
    forecast = tuple(
        _fix(stamp="2026092406", tau=tau, lat=16.4 + 0.02 * tau, lon=-103.0 - 0.08 * tau,
             wind=wind, tech="OFCL")
        for tau, wind in ((0, 140), (3, 140), (12, 145), (24, 145), (48, 135), (120, 80)))
    ensemble = {}
    for member in range(4):
        ensemble[f"AP{member + 1:02d}"] = tuple(
            _fix(stamp="2026092406", tau=tau,
                 lat=16.4 + member * spread / (math.pi * cyclones.EARTH_KM / 180.0),
                 lon=-103.0 - 0.08 * tau,
                 wind=100, tech=f"AP{member + 1:02d}")
            for tau, spread in (ensemble_spread_by_tau or {}).items())
    return cyclones.Storm(basin="EP", number=17, year=2026, name="Polo",
                          advisory={"advisory": "20"}, track=track,
                          forecast=cyclones.rebase(forecast, track[-1].stamp),
                          ensemble={k: cyclones.rebase(v, track[-1].stamp)
                                    for k, v in ensemble.items()})


class TestExitCodes(unittest.TestCase):
    """1 means "ran, and serious alerts are open". A crash must not say that."""

    def test_an_unexpected_error_exits_as_could_not_run(self):
        import track

        with mock.patch.object(track.pipeline, "run", side_effect=ValueError("boom")), \
                mock.patch("sys.stderr"):
            self.assertEqual(track.main(["--offline", "--no-files", "--quiet"]), 2)

    def test_the_windows_updater_does_not_call_open_alerts_a_failure(self):
        script = (ROOT / "update.bat").read_text(encoding="utf-8")
        self.assertNotRegex(script, r"(?im)^\s*if\s+errorlevel\s+1\b")

    def test_the_windows_publisher_publishes_a_run_with_open_alerts(self):
        script = (ROOT / "publish.bat").read_text(encoding="utf-8")
        self.assertNotRegex(script, r"(?im)^\s*if\s+errorlevel\s+1\b")
        self.assertIn("python publish.py", script)

    def test_the_windows_publisher_never_waits_on_a_schedule(self):
        script = (ROOT / "publish.bat").read_text(encoding="utf-8")
        pauses = re.findall(r"(?im)^.*\bpause\b.*$", script)
        self.assertTrue(pauses)
        for line in pauses:
            self.assertRegex(line, r'(?i)^\s*if /i not "%~1"=="/scheduled" pause\s*$')

    @unittest.skipUnless(sys.platform == "win32", "publish.bat is for Windows")
    def test_the_windows_publisher_publishes_exactly_the_runs_that_happened(self):
        # publish.bat itself, run by cmd.exe, against a track.py and a
        # publish.py that only exit with the codes they are handed.
        with tempfile.TemporaryDirectory() as tmp:
            here = Path(tmp)
            shutil.copyfile(ROOT / "publish.bat", here / "publish.bat")
            (here / "track.py").write_text(
                "import os, sys\nsys.exit(int(os.environ['TRACK']))\n", encoding="utf-8")
            (here / "publish.py").write_text(
                "import os, pathlib, sys\npathlib.Path('published').write_text('yes')\n"
                "sys.exit(int(os.environ['PUBLISH']))\n", encoding="utf-8")
            path = os.pathsep.join([str(Path(sys.executable).parent), os.environ.get("PATH", "")])
            for track, publish, code, published in ((0, 0, 0, True), (1, 0, 1, True), (3, 0, 3, True),
                                                    (2, 0, 2, False), (5, 0, 2, False), (1, 2, 4, True)):
                with self.subTest(track=track, publish=publish):
                    (here / "published").unlink(missing_ok=True)
                    env = dict(os.environ, PATH=path, TRACK=str(track), PUBLISH=str(publish))
                    done = subprocess.run(["cmd", "/d", "/c", str(here / "publish.bat"), "/scheduled"],
                                          env=env, stdin=subprocess.DEVNULL, capture_output=True,
                                          timeout=120)
                    self.assertEqual(done.returncode, code)
                    self.assertEqual((here / "published").exists(), published)

    def test_the_posix_publisher_runs_the_tracker_then_publishes(self):
        script = (ROOT / "publish.sh").read_text(encoding="utf-8")
        self.assertIn("python3 track.py --brief\n", script)
        self.assertIn("  0 | 1 | 3) ;;\n", script)
        self.assertIn('if ! python3 publish.py "$@"; then\n', script)

    def test_the_posix_publisher_keeps_lf_endings_in_every_checkout(self):
        # The hourly run is Linux: "sh\r" is no shell, and a checkout under
        # core.autocrlf would otherwise give it one.
        script = (ROOT / "publish.sh").read_bytes()
        self.assertTrue(script.startswith(b"#!/bin/sh\n"))
        self.assertNotIn(b"\r", script)
        self.assertIn("*.sh text eol=lf", (ROOT / ".gitattributes").read_text(encoding="utf-8").splitlines())

    @unittest.skipUnless(shutil.which("git") and (ROOT / ".git").exists(), "needs the git checkout")
    def test_the_posix_publisher_is_committed_executable(self):
        listed = subprocess.run(["git", "ls-files", "-s", "publish.sh"], cwd=ROOT, capture_output=True,
                                text=True, check=True).stdout
        self.assertTrue(listed.startswith("100755 "), listed)

    @unittest.skipIf(sys.platform == "win32", "publish.sh is for Linux and macOS")
    def test_the_posix_publisher_publishes_exactly_the_runs_that_happened(self):
        # publish.sh itself, run by sh from another folder, against a track.py
        # and a publish.py that only exit with the codes they are handed;
        # publish.py writes down the options it was given.
        with tempfile.TemporaryDirectory() as tmp:
            here = Path(tmp)
            shutil.copyfile(ROOT / "publish.sh", here / "publish.sh")
            (here / "track.py").write_text(
                "import os, sys\nsys.exit(int(os.environ['TRACK']))\n", encoding="utf-8")
            (here / "publish.py").write_text(
                "import json, os, pathlib, sys\n"
                "pathlib.Path('published').write_text(json.dumps(sys.argv[1:]))\n"
                "sys.exit(int(os.environ['PUBLISH']))\n", encoding="utf-8")
            bin_dir = here / "bin"
            bin_dir.mkdir()
            python3 = bin_dir / "python3"
            python3.write_text(f'#!/bin/sh\nexec "{sys.executable}" "$@"\n', encoding="utf-8")
            python3.chmod(0o755)
            path = os.pathsep.join([str(bin_dir), os.environ.get("PATH", "")])
            remote = ["--remote", "https://example.invalid/site.git"]
            for track, publish, code, published in ((0, 0, 0, True), (1, 0, 1, True), (3, 0, 3, True),
                                                    (2, 0, 2, False), (5, 0, 2, False), (1, 2, 4, True)):
                with self.subTest(track=track, publish=publish):
                    (here / "published").unlink(missing_ok=True)
                    env = dict(os.environ, PATH=path, TRACK=str(track), PUBLISH=str(publish))
                    done = subprocess.run(["sh", str(here / "publish.sh"), *remote], cwd=bin_dir, env=env,
                                          stdin=subprocess.DEVNULL, capture_output=True, timeout=120)
                    self.assertEqual(done.returncode, code, done.stderr)
                    self.assertEqual((here / "published").exists(), published)
                    if published:
                        self.assertEqual(json.loads((here / "published").read_text(encoding="utf-8")), remote)


@unittest.skipUnless(shutil.which("git"), "publishing needs git")
class TestPublish(unittest.TestCase):
    """publish.py: the pages of the last run, put up as the site on GitHub Pages."""

    RUN_AT = "2026-09-30T19:59:20+00:00"
    SITE = [".nojekyll", "atlas.html", "dashboard.html", "index.html",
            "latest.json", "map.html", "run.json", "storms.html", "storms.json"]

    def setUp(self):
        import publish

        self.publish = publish
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.nobody = self.tmp / "home" / "nobody"
        self.out = self.tmp / "output"
        self.out.mkdir()
        self._run(self.RUN_AT)
        self.remote = self.tmp / "site.git"
        self._git("init", "-q", "--bare", str(self.remote))

    def _page(self, name, text):
        (self.out / name).write_bytes(text.encode("utf-8"))

    def _html(self, body, run_at=None):
        """A page of the run at run_at (the fixture's own by default), naming
        it in its head as the tracker's pages do."""
        return f"<html><head>{live.head(run_at or self.RUN_AT)}</head><body>{body}</body></html>"

    def _run(self, run_at):
        """Every page of a run, each naming it where the tracker's own do."""
        for name in ("dashboard.html", "storms.html", "map.html", "atlas.html"):
            self._page(name, self._html(f"<!-- {name} -->", run_at))
        built = datetime.fromisoformat(run_at).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        self._page("storms.json", json.dumps({"built": built}))
        self._page("run.json", json.dumps({"run_at": run_at}))
        self._page("latest.json", json.dumps({"run_at": run_at}))

    def _git(self, *args):
        done = subprocess.run(["git", *args], check=True, capture_output=True, text=True)
        return done.stdout.strip()

    def _published(self, *args):
        return self._git("--git-dir", str(self.remote), *args)

    def _published_bytes(self, spec):
        return subprocess.run(["git", "--git-dir", str(self.remote), "cat-file", "blob", spec],
                              check=True, capture_output=True).stdout

    def _publish(self, **kwargs):
        kwargs.setdefault("home", self.nobody)
        return self.publish.publish(self.out, remote=str(self.remote), **kwargs)

    def _refused(self, pattern, **kwargs):
        with self.assertRaisesRegex(self.publish.PublishError, pattern):
            self._publish(**kwargs)
        self.assertEqual(self._published("for-each-ref"), "")

    def _config(self, name, *settings):
        path = self.tmp / name
        for key, value in settings:
            self._git("config", "--file", str(path), key, value)
        return {"GIT_CONFIG_GLOBAL": str(path)}

    def test_the_site_opens_on_the_dashboard(self):
        site = self.tmp / "site"
        site.mkdir()
        self.assertEqual(self.publish.lay_out(self.out, site, home=self.nobody), self.RUN_AT)
        self.assertEqual(sorted(path.name for path in site.iterdir()), self.SITE)
        self.assertEqual((site / "index.html").read_bytes(), (self.out / "dashboard.html").read_bytes())

    def test_a_run_missing_a_page_is_not_published(self):
        (self.out / "map.html").unlink()
        self._refused("map.html")

    def test_an_empty_or_cut_off_page_is_not_published(self):
        for name, text, said in (("storms.html", " \r\n", "storms.html is empty"),
                                 ("atlas.html", "<html><body>half a pa", "atlas.html is cut off"),
                                 ("storms.json", '{"storms": [', "storms.json is cut off"),
                                 ("latest.json", '{"schema": 9}', "latest.json gives no run time"),
                                 ("latest.json", '{"run_at": "yesterday"}', "latest.json gives no run time")):
            with self.subTest(page=name, text=text):
                kept = (self.out / name).read_bytes()
                self._page(name, text)
                self._refused(said)
                (self.out / name).write_bytes(kept)

    def test_an_unreadable_page_exits_as_could_not_publish(self):
        read = Path.read_bytes

        def locked(path):
            if path.name == "storms.html":
                raise PermissionError(13, "The process cannot access the file", str(path))
            return read(path)

        with mock.patch.object(Path, "read_bytes", locked), mock.patch("sys.stderr") as err:
            code = self.publish.main(["--out", str(self.out), "--remote", str(self.remote)])
        self.assertEqual(code, 2)
        self.assertIn("storms.html could not be read",
                      "".join(str(call.args[0]) for call in err.write.call_args_list))

    def test_a_page_naming_this_machine_s_home_is_not_published(self):
        home = self.tmp / "home" / "someone"
        built = json.loads((self.out / "storms.json").read_text(encoding="utf-8"))["built"]
        self._page("storms.json", json.dumps({"built": built, "cache": str(home / "data")}))
        self._page("atlas.html", self._html(f'<a href="file:///{home.as_posix()}/x"></a>'))
        self._refused("atlas.html, storms.json name this machine's home folder", home=home)

    def test_the_home_folder_is_found_in_any_spelling(self):
        from urllib.parse import quote

        home = self.tmp / "home" / "some one"
        text, posix = str(home), home.as_posix()
        drive = home.drive.rstrip(":").lower()
        tail = posix[len(home.drive):]
        spellings = {
            "as written": text,
            "upper case": text.upper(),
            "forward slashes": posix,
            "escaped once": json.dumps(text),
            "escaped twice": json.dumps(json.dumps(text)),
            "a file address": "file:///" + quote(posix),
            "Git Bash": f"/{drive}{tail}" if drive else posix,
            "a network path": "\\\\host\\" + (f"{drive}$" if drive else "share") + tail.replace("/", "\\"),
        }
        for how, spelled in spellings.items():
            with self.subTest(how):
                self._page("map.html", self._html(f"<p>{spelled}</p>"))
                self._refused("map.html names this machine's home folder", home=home)

    def test_a_folder_named_only_like_home_does_not_stop_the_publish(self):
        self._page("map.html", self._html(f"<p>{self.tmp / 'home' / 'someone'}</p>"))
        self._publish(home=self.tmp / "home" / "some")
        self.assertEqual(self._published("rev-list", "--count", "gh-pages"), "1")

    def test_the_site_goes_up_under_its_own_name_not_this_machine_s(self):
        work = {"GIT_AUTHOR_NAME": "Someone", "GIT_AUTHOR_EMAIL": "someone@work.example",
                "GIT_COMMITTER_NAME": "Someone", "GIT_COMMITTER_EMAIL": "someone@work.example"}
        with mock.patch.dict(os.environ, work):
            self._publish()
        name, email = self.publish.IDENTITY
        self.assertEqual(self._published("log", "-1", "--format=%an <%ae>|%cn <%ce>", "gh-pages"),
                         f"{name} <{email}>|{name} <{email}>")

    def test_nothing_of_this_machine_s_git_setup_goes_up_with_the_site(self):
        hooks = self.tmp / "hooks"
        hooks.mkdir()
        hook = hooks / "commit-msg"
        hook.write_bytes(b'#!/bin/sh\necho "Signed-off-by: Someone <someone@work.example>" >> "$1"\n')
        hook.chmod(0o755)
        refuse = hooks / "pre-push"
        refuse.write_bytes(b"#!/bin/sh\nexit 1\n")
        refuse.chmod(0o755)
        work = self._config("work.gitconfig", ("core.hooksPath", hooks.as_posix()),
                            ("commit.gpgsign", "true"), ("gpg.format", "ssh"),
                            ("user.signingkey", (self.tmp / "no-such-key").as_posix()),
                            ("i18n.commitEncoding", "ISO-8859-1"))
        with mock.patch.dict(os.environ, work):
            self._publish()
        commit = self._published("cat-file", "-p", "gh-pages")
        self.assertNotIn("gpgsig", commit)
        self.assertNotIn("someone@work.example", commit)
        self.assertNotRegex(commit, r"(?m)^encoding ")

    def test_the_site_goes_up_byte_for_byte(self):
        page = f"<html>\r\n<head>{live.head(self.RUN_AT)}</head>\r\n<body>crlf</body>\r\n</html>\r\n".encode()
        (self.out / "storms.html").write_bytes(page)
        with mock.patch.dict(os.environ, self._config("crlf.gitconfig", ("core.autocrlf", "true"))):
            self._publish()
        self.assertEqual(self._published_bytes("gh-pages:storms.html"), page)

    def test_an_address_turned_away_from_https_is_refused(self):
        rewrite = self._config("rewrite.gitconfig",
                               ("url.ssh://git@example.invalid/site.git.insteadOf", str(self.remote)))
        with mock.patch.dict(os.environ, rewrite):
            self._refused("not allowed")

    def test_git_s_own_environment_does_not_steer_the_publish(self):
        elsewhere = self.tmp / "elsewhere.git"
        self._git("init", "-q", "--bare", str(elsewhere))
        steer = {"GIT_DIR": str(elsewhere), "GIT_INDEX_FILE": str(self.tmp / "index"),
                 "GIT_CONFIG_COUNT": "2", "GIT_CONFIG_KEY_0": "commit.gpgsign", "GIT_CONFIG_VALUE_0": "true",
                 "GIT_CONFIG_KEY_1": "user.signingkey", "GIT_CONFIG_VALUE_1": str(self.tmp / "no-such-key")}
        with mock.patch.dict(os.environ, steer):
            self._publish()
            self.assertEqual(self.publish._environment()["GIT_TERMINAL_PROMPT"], "0")
        self.assertEqual(self._git("--git-dir", str(elsewhere), "for-each-ref"), "")
        self.assertEqual(self._published("ls-tree", "--name-only", "gh-pages").split(), self.SITE)

    def test_a_page_a_global_ignore_rule_would_drop_is_still_published(self):
        xdg = self.tmp / "xdg"
        (xdg / "git").mkdir(parents=True)
        (xdg / "git" / "ignore").write_text("*.json\n.nojekyll\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": str(xdg)}):
            self._publish()
        self.assertEqual(self._published("ls-tree", "--name-only", "gh-pages").split(), self.SITE)

    def test_each_publish_replaces_the_branch_with_one_commit(self):
        self._publish()
        later = "2026-09-30T20:59:20+00:00"
        self._run(later)
        self._publish()
        self.assertEqual(self._published("rev-list", "--count", "gh-pages"), "1")
        self.assertEqual(self._published("show", "gh-pages:index.html"),
                         self._html("<!-- dashboard.html -->", later))
        self.assertEqual(self._published("ls-tree", "--name-only", "gh-pages").split(), self.SITE)

    def test_a_page_of_another_run_is_not_published(self):
        for name, text in (("map.html", self._html("<!-- map -->", "2026-09-30T18:59:20+00:00")),
                           ("storms.json", json.dumps({"built": "2026-09-30T18:59:20Z"})),
                           ("run.json", json.dumps({"run_at": "2026-09-30T18:59:20+00:00"}))):
            with self.subTest(page=name):
                kept = (self.out / name).read_bytes()
                self._page(name, text)
                self._refused(f"{name} names the run of 2026-09-30T18:59:20.*, where latest.json "
                              f"names the run of {re.escape(self.RUN_AT)}: run track.py again")
                (self.out / name).write_bytes(kept)

    def test_a_page_naming_no_run_is_not_published(self):
        # A page that names a run run.json never will would load again for
        # ever, looking for it.
        for name, text in (("dashboard.html", "<html><head></head><body></body></html>"),
                           ("atlas.html", self._html("<!-- atlas -->").replace(self.RUN_AT, "soon")),
                           ("storms.json", json.dumps({"storms": []})),
                           ("run.json", json.dumps(["run_at"]))):
            with self.subTest(page=name):
                kept = (self.out / name).read_bytes()
                self._page(name, text)
                self._refused(f"{name} names no run")
                (self.out / name).write_bytes(kept)

    def test_a_run_named_outside_the_head_does_not_count(self):
        self._page("storms.html", f"<html><head></head><body>{live.head(self.RUN_AT)}</body></html>")
        self._refused("storms.html names no run")

    def test_one_moment_written_two_ways_is_one_run(self):
        # storms.json writes its run in UTC with a Z, the pages as the run
        # gives it; an offset is the same moment too.
        self._page("atlas.html", self._html("<!-- atlas -->", "2026-09-30T21:59:20+02:00"))
        self.assertEqual(self._publish(), self.RUN_AT)

    def test_the_beacon_goes_up_with_the_pages(self):
        self._publish()
        self.assertEqual(json.loads(self._published("show", "gh-pages:run.json")), {"run_at": self.RUN_AT})

    def test_a_run_older_than_the_site_s_is_not_published_unless_asked(self):
        self._publish()
        older = "2026-09-29T21:55:00+00:00"
        self._run(older)
        with self.assertRaisesRegex(self.publish.PublishError, "older"):
            self._publish()
        with mock.patch("sys.stderr"):
            self.assertEqual(self.publish.main(["--out", str(self.out), "--remote", str(self.remote),
                                                "--dry-run"]), 2)
        self.assertIn(self.RUN_AT, self._published("show", "gh-pages:latest.json"))
        self._publish(allow_older=True)
        self.assertIn(older, self._published("show", "gh-pages:latest.json"))

    def test_the_commit_names_the_run_it_publishes(self):
        self.assertEqual(self._publish(), self.RUN_AT)
        self.assertIn(self.RUN_AT, self._published("log", "-1", "--format=%s", "gh-pages"))

    def test_a_code_branch_is_never_published_over(self):
        for branch in ("main", "master"):
            with self.assertRaises(self.publish.PublishError):
                self._publish(branch=branch)
        self.assertEqual(self._published("for-each-ref"), "")

    def test_a_dry_run_says_which_run_and_pushes_nothing(self):
        with mock.patch("sys.stdout") as said:
            code = self.publish.main(["--out", str(self.out), "--remote", str(self.remote), "--dry-run"])
        self.assertEqual(code, 0)
        self.assertRegex("".join(str(call.args[0]) for call in said.write.call_args_list),
                         r"30 Sep 2026 19:59 UTC \(.* old\)")
        self.assertEqual(self._published("for-each-ref"), "")

    def test_a_refused_publish_exits_as_could_not_publish(self):
        (self.out / "atlas.html").unlink()
        with mock.patch("sys.stderr"):
            self.assertEqual(self.publish.main(["--out", str(self.out), "--remote", str(self.remote)]), 2)


class TestServe(unittest.TestCase):
    """`--serve`: the output directory over HTTP, read-only, for a tablet."""

    def setUp(self):
        import track

        self.track = track
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        self.out = root / "output"
        (self.out / "archive").mkdir(parents=True)
        (self.out / "storms.html").write_text("<p>the desk</p>", encoding="utf-8")
        (root / "secret.txt").write_text("not for the tablet", encoding="utf-8")
        quiet = mock.patch.object(track.DeskHandler, "log_message")
        quiet.start()
        self.addCleanup(quiet.stop)

    def get(self, path: str):
        server = self.track.serve(self.out, 0, lan=False)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=10)
        try:
            conn.request("GET", path)
            reply = conn.getresponse()
            return reply.status, dict(reply.getheaders()), reply.read().decode("utf-8")
        finally:
            conn.close()
            server.shutdown()
            server.server_close()

    def test_the_storm_desk_is_served_from_the_output_directory(self):
        status, _, body = self.get("/storms.html")
        self.assertEqual((status, body), (200, "<p>the desk</p>"))

    def test_the_root_opens_the_storm_desk(self):
        status, headers, _ = self.get("/")
        self.assertEqual((status, headers.get("Location")), (302, "/storms.html"))

    def test_the_address_given_names_the_map_and_the_desk(self):
        server = mock.MagicMock()
        server.server_address = ("127.0.0.1", 8765)
        said = self.track._where(server, lan=False)
        self.assertIn("http://127.0.0.1:8765/map.html", said)
        self.assertIn("http://127.0.0.1:8765/ ", said)
        with mock.patch.object(self.track, "_lan_address", return_value="192.168.1.5"):
            said_lan = self.track._where(server, lan=True)
        self.assertIn("http://192.168.1.5:8765/map.html", said_lan)
        self.assertIn("http://192.168.1.5:8765/ ", said_lan)
        self.assertTrue(said.isascii() and said_lan.isascii())

    def test_nothing_outside_the_output_directory_is_served(self):
        for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/..%5csecret.txt",
                     "/archive/../../secret.txt"):
            status, _, body = self.get(path)
            self.assertEqual(status, 404, path)
            self.assertNotIn("not for the tablet", body, path)

    def test_a_directory_is_not_listed(self):
        self.assertEqual(self.get("/archive/")[0], 404)

    def test_a_rewritten_page_is_not_kept_from_an_earlier_run(self):
        # --watch rewrites the files in place; a cached copy would be a stale desk.
        self.assertEqual(self.get("/storms.html")[1].get("Cache-Control"), "no-cache")

    def test_it_answers_this_machine_only_unless_asked_for_the_network(self):
        server = self.track.serve(self.out, 0, lan=False)
        server.server_close()
        self.assertEqual(server.server_address[0], "127.0.0.1")
        # Not bound for real: listening on every interface can raise a
        # firewall prompt on the machine running the tests.
        with mock.patch("http.server.HTTPServer.server_bind"),                 mock.patch("socketserver.TCPServer.server_activate"):
            server = self.track.serve(self.out, 0, lan=True)
        server.server_close()
        self.assertEqual(server.server_address[0], "0.0.0.0")

    def main(self, *argv):
        server = mock.MagicMock()
        server.server_address = ("127.0.0.1", 8765)
        server.serve_forever.side_effect = KeyboardInterrupt
        with mock.patch.object(self.track, "serve", return_value=server) as serve,                 mock.patch.object(self.track, "_guarded", return_value=0) as run,                 mock.patch.object(self.track.time, "sleep", side_effect=KeyboardInterrupt),                 mock.patch("sys.stderr"):
            code = self.track.main(["--out", str(self.out), *argv])
        return code, serve, run, server

    def test_serving_runs_once_then_serves_until_stopped(self):
        code, serve, run, server = self.main("--serve")
        self.assertEqual(code, 0)
        serve.assert_called_once_with(self.out, 8765, False)
        run.assert_called_once()
        server.serve_forever.assert_called_once()

    def test_a_port_and_the_network_are_passed_through(self):
        _, serve, _, _ = self.main("--serve", "9000", "--lan")
        serve.assert_called_once_with(self.out, 9000, True)

    def test_watching_keeps_serving_between_runs(self):
        code, _, run, server = self.main("--serve", "--watch", "30")
        self.assertEqual(code, 0)
        run.assert_called_once()
        server.shutdown.assert_called_once()

    def test_the_network_without_serving_is_refused(self):
        with mock.patch("sys.stderr"), self.assertRaises(SystemExit):
            self.track.main(["--lan"])

    def test_the_files_a_run_writes_are_not_source(self):
        ignored = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
        for name in ("dashboard.html", "atlas.html", "latest.json", "storms.html",
                     "storms.json", "map.html", "run.json"):
            self.assertIn(f"output/{name}", ignored)


class TestCycloneTiming(unittest.TestCase):
    """What "now", "in N hours" and "the last 24 hours" mean for a storm."""

    def test_the_last_24_hours_are_the_24_hours_to_the_latest_analysis(self):
        storm = _polo()
        self.assertEqual(storm.rapid, (5.0, "2026092412"))       # 130 -> 135
        self.assertFalse(storm.intensifying_rapidly)
        self.assertEqual(storm.peak_intensification, (85.0, "2026092212"))

    def test_forecast_leads_count_from_the_latest_analysis(self):
        storm = _polo()
        # Issued at 06Z; the 06Z and 09Z points are behind the 12Z analysis.
        self.assertEqual([f.tau for f in storm.forecast], [6, 18, 42, 114])
        self.assertTrue(all(f.stamp == "2026092412" for f in storm.forecast))
        self.assertEqual(storm.forecast[0].issued, "2026092406")
        self.assertEqual(cyclones.valid_stamp(storm.forecast[0]), "2026092418")

    def test_members_are_compared_at_one_valid_time(self):
        storm = _polo({12: 50.0, 24: 100.0, 126: 900.0})
        # Member n sits n * s km north of member 0, four members on one
        # meridian. Their mean position is halfway along, 1.5 s from each
        # end: the members sit 1.5 s, 0.5 s, 0.5 s and 1.5 s from it, and the
        # spread - their mean distance from it - is s. Re-based, 12 -> 6 and
        # 24 -> 18.
        self.assertAlmostEqual(storm.spread_at(6), 50.0, places=6)
        self.assertAlmostEqual(storm.spread_at(18), 100.0, places=6)

    def test_one_lost_member_does_not_set_the_spread(self):
        # Thirty members on one point and a thirty-first 600 km north, the
        # way a GEFS member that has lost the vortex tracks the next one. The
        # furthest pair is 600 km apart and would be quoted as the forecast's
        # width. The mean position is 1/31 of the way up: 30 members sit
        # 600/31 km from it and one sits 600 * 30/31, a mean of
        # 2 * 600 * 30 / 31 / 31 = 37.5 km.
        per_degree = math.pi * cyclones.EARTH_KM / 180.0
        members = {
            f"AP{n:02d}": (_fix(stamp="2026092412", tau=6, tech=f"AP{n:02d}",
                                lat=16.0 + (600.0 / per_degree if n == 31 else 0.0),
                                lon=-105.0),
                           _fix(stamp="2026092412", tau=12, tech=f"AP{n:02d}",
                                lat=16.5, lon=-105.5))
            for n in range(1, 32)
        }
        storm = cyclones.Storm(basin="EP", number=17, year=2026, name="Polo",
                               ensemble=members)
        self.assertAlmostEqual(storm.spread_at(6), 2 * 600.0 * 30 / 31 / 31,
                               delta=0.5)
        self.assertAlmostEqual(storm.spread_at(12), 0.0, places=6)

    def test_spread_is_measured_across_the_date_line(self):
        # Four members 0.1 degree either side of 180 on the equator: each is
        # 0.1 degree, 11.1 km, from their mean position. Averaging longitudes
        # as numbers puts that position at 0 degrees, half a world away.
        per_degree = math.pi * cyclones.EARTH_KM / 180.0
        members = {
            f"AP{n:02d}": (_fix(stamp="2026092412", tau=6, tech=f"AP{n:02d}",
                                lat=0.0, lon=lon),
                           _fix(stamp="2026092412", tau=12, tech=f"AP{n:02d}",
                                lat=0.0, lon=lon))
            for n, lon in enumerate((179.9, 179.9, -179.9, -179.9), start=1)
        }
        storm = cyclones.Storm(basin="CP", number=3, year=2026, name="Test",
                               ensemble=members)
        self.assertAlmostEqual(storm.spread_at(6), 0.1 * per_degree, places=6)

    def test_a_threat_quotes_the_spread_at_its_own_lead(self):
        storm = _polo({12: 50.0, 24: 100.0, 126: 900.0})
        # A place on the forecast point issued as +24 h from 06Z: +18 h from
        # the 12Z analysis, valid 06Z on the 25th, where the members sit
        # 100 km from their mean. (Lazaro Cardenas used to be the example,
        # at "+6 h"; measured from the analysis, Polo is already closest to
        # it and moving away.)
        ahead = cyclones.Place("Ahead", -103.0 - 0.08 * 24, 16.4 + 0.02 * 24,
                               "Nowhere")
        with mock.patch.object(cyclones, "LANDFALL", (ahead,)):
            state = SimpleNamespace(active=(storm,), basins={})
            raised = alerts.cyclone_rules(state)
        threat = next(a for a in raised if a.code.startswith("tc_threat_"))
        self.assertIn("passes 0 km from Ahead in 18 h", threat.title)
        self.assertIn("06Z 25 Sep", threat.title)
        self.assertIn("+18 h is 100 km", threat.detail)
        # Named, because the other reading - the gap between the two furthest
        # members - is three or four times larger.
        self.assertIn("from their mean position", threat.detail)

    def test_no_ri_alert_for_a_burst_two_days_old(self):
        state = SimpleNamespace(active=(_polo(),), basins={})
        codes = [a.code for a in alerts.cyclone_rules(state)]
        self.assertFalse([c for c in codes if c.startswith("tc_ri_")])


class TestCycloneCounts(unittest.TestCase):
    """A named storm is a tropical or subtropical storm, not any gale."""

    HURDAT = "\n".join([
        "AL012001,            ONE,      3,",
        "20010801, 0000,  , TD, 20.0N,  60.0W,  30, 1010,",
        "20010801, 0600,  , TS, 20.5N,  61.0W,  40, 1005,",
        "20010801, 1200,  , TS, 21.0N,  62.0W,  45, 1003,",
        "AL022001,            TWO,      2,",
        "20010901, 0000,  , TD, 30.0N,  60.0W,  30, 1010,",
        "20010901, 0600,  , EX, 35.0N,  55.0W,  55,  990,",
        "AL032001,            THREE,      3,",
        "20011001, 0000,  , TS, 25.0N,  70.0W,  60,  990,",
        "20011001, 0600,  , EX, 35.0N,  60.0W,  75,  975,",
        "20011001, 1200,  , EX, 40.0N,  50.0W,  70,  980,",
        "AL042001,            FOUR,      2,",
        "20011101, 0000,  , HU, 25.0N,  70.0W, 100,  950,",
        "20011101, 0600,  , HU, 26.0N,  71.0W,  90,  960,",
    ])

    def test_hurdat_counts_need_a_tropical_stage(self):
        season = cyclones.hurdat_seasons(self.HURDAT)[2001]
        # ONE and THREE were tropical storms and FOUR a major hurricane; TWO's
        # gale was extratropical, and so was THREE's hurricane-force wind.
        self.assertEqual(season["named"], 3)
        self.assertEqual(season["hurricanes"], 1)
        self.assertEqual(season["major"], 1)

    def test_live_counts_need_a_tropical_stage(self):
        gale = cyclones.Storm(basin="AL", number=2, year=2026, track=(
            _fix(stamp="2026090100", wind=30, stage="TD"),
            _fix(stamp="2026090106", wind=55, stage="EX")))
        post = cyclones.Storm(basin="AL", number=3, year=2026, track=(
            _fix(stamp="2026090100", wind=60, stage="TS"),
            _fix(stamp="2026090106", wind=75, stage="EX")))
        season = cyclones.BasinSeason(basin="AL", storms=(gale, post))
        self.assertEqual(post.peak.wind, 60)  # its 75 kt was extratropical
        self.assertEqual((season.named, season.hurricanes, season.major), (1, 0, 0))

    def test_no_two_landfall_places_are_the_same_place(self):
        places = cyclones.LANDFALL
        for i, a in enumerate(places):
            for b in places[i + 1:]:
                self.assertGreater(
                    cyclones.great_circle(a.lon, a.lat, b.lon, b.lat), 5.0,
                    f"{a.name} and {b.name}")


class TestAtcfParsing(unittest.TestCase):
    def test_tenths_and_hemisphere(self):
        """Read as a plain float a west-Pacific hurricane lands in Africa."""
        self.assertEqual(cyclones._tenths("152N"), 15.2)
        self.assertEqual(cyclones._tenths("1015W"), -101.5)
        self.assertEqual(cyclones._tenths("1200E"), 120.0)
        self.assertEqual(cyclones._tenths("85S"), -8.5)
        self.assertIsNone(cyclones._tenths(""))
        self.assertIsNone(cyclones._tenths("1015"))

    def test_zero_is_not_an_observation(self):
        """ATCF writes 0 for "not analysed" in wind and pressure."""
        self.assertIsNone(cyclones._int("0"))
        self.assertIsNone(cyclones._int("-999"))
        self.assertEqual(cyclones._int("925"), 925)

    def test_wind_radii_rows_are_one_fix_not_three(self):
        """Every position repeats once per radius threshold. Counted as
        separate fixes the track triples and the ACE with it."""
        text = _deck([
            ("2026092312", 0, "152N", "1015W", 130, 925, "HU", "BEST", " 34"),
            ("2026092312", 0, "152N", "1015W", 130, 925, "HU", "BEST", " 50"),
            ("2026092312", 0, "152N", "1015W", 130, 925, "HU", "BEST", " 64"),
            ("2026092318", 0, "154N", "1020W", 135, 920, "HU", "BEST", " 34"),
        ])
        fixes = cyclones.parse_atcf(text)
        self.assertEqual(len(fixes), 2)
        self.assertEqual(fixes[0].lat, 15.2)
        self.assertEqual(fixes[0].lon, -101.5)
        self.assertEqual(fixes[0].wind, 130)

    def test_a_tech_filter_drops_rows_at_the_line(self):
        text = _deck([
            ("2026092312", 0, "152N", "1015W", 130, 925, "HU", "BEST", " 34"),
            ("2026092312", 12, "156N", "1025W", 125, 930, "HU", "AVNO", " 34"),
            ("2026092312", 12, "150N", "1030W", 115, 940, "HU", "AEMN", " 34"),
        ])
        self.assertEqual({f.tech for f in cyclones.parse_atcf(text, {"AVNO"})},
                         {"AVNO"})

    def test_the_name_arrives_late_and_the_last_one_wins(self):
        text = ("EP, 17, 2026091206,   , BEST,   0, 120N, 1100W,  25, 1008, DB,"
                "  34, NEQ, 0,0,0,0, 1009, 180, 15, 0, 0, L, 0, , 0, 0, INVEST, D,\n"
                "EP, 17, 2026091218,   , BEST,   0, 122N, 1105W,  35, 1004, TS,"
                "  34, NEQ, 0,0,0,0, 1009, 180, 15, 0, 0, L, 0, , 0, 0, POLO, D,")
        self.assertEqual(cyclones.storm_name(text), "Polo")



# Five rows of the official forecast deck for Nolo, 25 September 2026: each
# forecast point repeated once per wind threshold it carries, and no 64-kt
# row at 96 h because NHC stops forecasting that radius at 72 h.
FST_NOLO = """\
EP, 15, 2026092512, 03, OFCL,  12, 167N, 1553W,  90,    0, HU,  34, NEQ,  100,   90,   80,  110,    0,    0,   0, 110,   0,    ,   0, ESB,  15,   5,
EP, 15, 2026092512, 03, OFCL,  12, 167N, 1553W,  90,    0, HU,  50, NEQ,   60,   50,   40,   50,    0,    0,   0, 110,   0,    ,   0, ESB,  15,   5,
EP, 15, 2026092512, 03, OFCL,  12, 167N, 1553W,  90,    0, HU,  64, NEQ,   40,   35,   25,   30,    0,    0,   0, 110,   0,    ,   0, ESB,  15,   5,
EP, 15, 2026092512, 03, OFCL,  96, 202N, 1643W, 100,    0, HU,  34, NEQ,  120,   90,   70,   90,    0,    0,   0, 120,   0,    ,   0, ESB, 320,   9,
EP, 15, 2026092512, 03, OFCL,  96, 202N, 1643W, 100,    0, HU,  50, NEQ,   50,   40,   30,   40,    0,    0,   0, 120,   0,    ,   0, ESB, 320,   9,
"""


class TestWindRadii(unittest.TestCase):
    """The radii rows are where the size of the storm is, so they are kept."""

    def test_radii_rows_merge_onto_one_fix(self):
        fixes = cyclones.parse_atcf(FST_NOLO)
        self.assertEqual(len(fixes), 2)
        self.assertEqual(fixes[0].radius(34), (100, 90, 80, 110))
        self.assertEqual(fixes[0].radius(50), (60, 50, 40, 50))
        self.assertEqual(fixes[0].radius(64), (40, 35, 25, 30))

    def test_a_threshold_the_forecast_does_not_carry_is_absent(self):
        day4 = cyclones.parse_atcf(FST_NOLO)[1]
        self.assertEqual(day4.radius(50), (50, 40, 30, 40))
        self.assertIsNone(day4.radius(64))

    def test_a_full_circle_radius_fills_all_four_quadrants(self):
        row = ("AL, 06, 2026092512,   , BEST,   0, 301N,  425W,  50, 1002, TS,"
               "  34, AAA,   60,    0,    0,    0, 1012,  150,  30,")
        self.assertEqual(cyclones.parse_atcf(row)[0].radius(34), (60, 60, 60, 60))

    def test_a_row_of_zeros_is_not_analysed_rather_than_calm(self):
        # ATCF writes 0 for "not analysed". A 50-kt storm with no 34-kt wind
        # anywhere is not a thing, so all four zero means unknown; one zero
        # among real radii is a quadrant that really has none.
        row = ("AL, 06, 2026092512,   , BEST,   0, 301N,  425W,  50, 1002, TS,"
               "  34, NEQ,    0,    0,    0,    0, 1012,  150,  30,")
        self.assertIsNone(cyclones.parse_atcf(row)[0].radius(34))
        lopsided = ("WP, 25, 2026092612,   , BEST,   0, 236N, 1270E,  70,  985, TY,"
                    "  64, NEQ,    0,    0,    0,   10, 1004,  150,  15,")
        self.assertEqual(cyclones.parse_atcf(lopsided)[0].radius(64), (0, 0, 0, 10))

    def test_rebasing_keeps_the_radii(self):
        fix = cyclones.parse_atcf(FST_NOLO)[0]
        moved = cyclones.rebase((fix,), "2026092518")[0]
        self.assertEqual(moved.tau, 6)
        self.assertEqual(moved.radius(50), (60, 50, 40, 50))

class TestCycloneQuantities(unittest.TestCase):
    def test_category_sits_on_the_published_thresholds(self):
        for wind, expected in ((63, 0), (64, 1), (82, 1), (83, 2), (95, 2),
                               (96, 3), (112, 3), (113, 4), (136, 4), (137, 5)):
            self.assertEqual(cyclones.category(wind), expected, f"{wind} kt")

    def test_ace_counts_only_synoptic_warm_core_gales(self):
        """ACE is 1e-4 times the sum of the squares, so four six-hourly fixes
        at 50 kt is 4 * 2500 * 1e-4 = 1.0. An intermediate landfall fix, a
        post-tropical one, a sub-gale one and a forecast one are not counted."""
        fixes = [
            _fix(stamp="2026092300", wind=50, stage="TS"),
            _fix(stamp="2026092306", wind=50, stage="TS"),
            _fix(stamp="2026092312", wind=50, stage="TS"),
            _fix(stamp="2026092318", wind=50, stage="TS"),
            _fix(stamp="2026092303", wind=50, stage="TS"),   # intermediate
            _fix(stamp="2026092400", wind=50, stage="EX"),   # not warm core
            _fix(stamp="2026092406", wind=30, stage="TD"),   # below gale
            _fix(stamp="2026092412", tau=12, wind=90, stage="HU"),  # forecast
        ]
        self.assertAlmostEqual(cyclones.ace(fixes), 1.0, places=6)

    def test_rapid_intensification_is_the_nhc_definition(self):
        """30 kt in 24 hours, not 29 and not over 30 hours."""
        rapid = [_fix(stamp="2026092200", wind=60, stage="TS"),
                 _fix(stamp="2026092300", wind=90, stage="HU")]
        change, when = cyclones.intensification(rapid)
        self.assertEqual(change, 30.0)
        self.assertEqual(when, "2026092300")
        self.assertGreaterEqual(change, cyclones.RI_THRESHOLD)

        short = [_fix(stamp="2026092200", wind=60, stage="TS"),
                 _fix(stamp="2026092300", wind=89, stage="HU")]
        self.assertLess(cyclones.intensification(short)[0],
                        cyclones.RI_THRESHOLD)

        # A track that does not span the window reports nothing rather than
        # extrapolating a rate it cannot see.
        self.assertEqual(cyclones.intensification([_fix(wind=60)]), (0.0, ""))

    def test_weakening_is_reported_as_a_negative_change(self):
        fixes = [_fix(stamp="2026092200", wind=130, stage="HU"),
                 _fix(stamp="2026092300", wind=75, stage="HU")]
        self.assertEqual(cyclones.intensification(fixes)[0], -55.0)

    def test_great_circle_against_a_known_leg(self):
        """Los Angeles to New York is 3,940 km, give or take the ellipsoid."""
        km = cyclones.great_circle(-118.24, 34.05, -73.94, 40.67)
        self.assertAlmostEqual(km, 3940.0, delta=25.0)

    def test_bearing_names_box_the_compass(self):
        for degrees, name in ((0, "N"), (45, "NE"), (90, "E"), (180, "S"),
                              (338, "NNW"), (360, "N")):
            self.assertEqual(cyclones.bearing_name(degrees), name)
        self.assertEqual(cyclones.bearing_name(None), "stationary")

    def test_the_gazetteer_finds_the_coast_a_storm_is_off(self):
        gap, place = cyclones.nearest_place(-101.5, 15.2)
        self.assertEqual(place.country, "Mexico")
        self.assertLess(gap, 400.0)

    def test_a_mid_ocean_position_has_no_near_place(self):
        self.assertIsNone(cyclones.nearest_place(-40.0, 5.0))


class TestStormAssembly(unittest.TestCase):
    def storm(self, **over):
        track = over.get("track", tuple(
            _fix(stamp=stamp, lat=lat, lon=lon, wind=wind, stage="HU")
            for stamp, lat, lon, wind in (
                ("2026092200", 13.8, -99.0, 45),
                ("2026092212", 14.4, -100.2, 90),
                ("2026092300", 14.8, -100.9, 130),
                ("2026092312", 15.2, -101.5, 130),
            )))
        forecast = over.get("forecast", tuple(
            _fix(stamp="2026092312", tau=tau, lat=lat, lon=lon, wind=wind,
                 stage="HU", tech="OFCL")
            for tau, lat, lon, wind in (
                (12, 15.4, -102.0, 135), (24, 16.2, -103.4, 135),
                (120, 22.4, -113.1, 90), (144, 25.0, -118.0, 45))))
        return cyclones.Storm(
            basin="EP", number=17, year=2026, name=over.get("name", "Polo"),
            track=track, forecast=forecast,
            ensemble=over.get("ensemble", {}),
            advisory=over.get("advisory", {"advisory": "011a"}),
        )

    def test_identity_is_built_from_the_atcf_id(self):
        storm = self.storm()
        self.assertEqual(storm.key, "ep172026")
        self.assertEqual(storm.designation, "EP17")
        self.assertEqual(cyclones.split_id(storm.key), ("EP", 17, 2026))

    def test_a_storm_is_live_only_while_an_advisory_is_open(self):
        self.assertTrue(self.storm().active)
        self.assertFalse(self.storm(advisory={}).active)

    def test_peak_and_current_are_different_questions(self):
        storm = self.storm(track=tuple(
            _fix(stamp=stamp, wind=wind, stage="HU")
            for stamp, wind in (("2026092200", 155), ("2026092312", 90))))
        self.assertEqual(storm.peak.wind, 155)
        self.assertEqual(storm.latest.wind, 90)
        self.assertEqual(storm.peak_category, 5)

    def test_motion_comes_from_the_last_two_fixes(self):
        speed, bearing = self.storm().translation
        self.assertGreater(speed, 0.0)
        self.assertIn(cyclones.bearing_name(bearing), {"NW", "WNW", "NNW"})

    def test_the_forecast_horizon_is_the_official_one(self):
        """Ensemble members run to +384 h. Quoting spread out there implies a
        forecast the NHC does not issue."""
        members = {
            name: tuple(_fix(stamp="2026092312", tau=tau, lat=20.0 + tau / 24,
                             lon=lon, wind=80, tech=name)
                        for tau in (0, 24, 120, 192))
            for name, lon in (("AP01", -110.0), ("AP02", -113.0),
                              ("AP03", -116.0), ("AP04", -119.0))
        }
        storm = self.storm(ensemble=members)
        self.assertLessEqual(storm.spread_tau, cyclones.HORIZON)
        self.assertGreater(storm.spread_km, 0.0)

    def test_threats_are_ordered_by_distance_and_carry_their_lead(self):
        threats = self.storm().threats(600.0)
        self.assertTrue(threats)
        self.assertEqual(threats, sorted(threats, key=lambda t: t[0]))
        for gap, fix, place in threats:
            self.assertLessEqual(fix.tau, cyclones.HORIZON)
            self.assertLessEqual(gap, 600.0)

    def test_a_coast_between_two_forecast_points_is_measured_where_the_line_passes(self):
        # The forecast points are 24 hours and 627 km apart along 20N, and
        # the place sits on that line halfway between them. Measured only at
        # the points it is 3 degrees of longitude away, 313 km; the line
        # passes over it at +24 h, when the wind is halfway from 100 to 80.
        spot = cyclones.Place("Midway Point", -107.0, 20.0, "Nowhere")
        storm = self.storm(
            track=(_fix(stamp="2026092312", lat=20.0, lon=-111.0, wind=100,
                        stage="HU"),),
            forecast=tuple(
                _fix(stamp="2026092312", tau=tau, lat=20.0, lon=lon, wind=wind,
                     stage="HU", tech="OFCL")
                for tau, lon, wind in ((12, -110.0, 100), (36, -104.0, 80))))
        with mock.patch.object(cyclones, "LANDFALL", (spot,)):
            ((gap, fix, place),) = storm.threats(400.0)
        self.assertIs(place, spot)
        self.assertLess(gap, 5.0)
        self.assertEqual(fix.tau, 24)
        self.assertEqual(fix.wind, 90)
        self.assertAlmostEqual(fix.lon, -107.0, places=6)

    def test_a_storm_moving_away_is_closest_now(self):
        # The storm is north-east of nothing and heading west-north-west,
        # away from a place 1 degree north and 1 degree east of it. Its
        # closest approach is the analysis itself; the first forecast point
        # is 4 degrees of longitude, 423 km, from the place.
        spot = cyclones.Place("Behind It", -102.0, 18.0, "Nowhere")
        now = _fix(stamp="2026092312", lat=17.0, lon=-103.0, wind=135, stage="HU")
        storm = self.storm(
            track=(now,),
            forecast=tuple(
                _fix(stamp="2026092312", tau=tau, lat=lat, lon=lon, wind=130,
                     stage="HU", tech="OFCL")
                for tau, lat, lon in ((12, 18.0, -106.0), (24, 19.0, -109.0))))
        with mock.patch.object(cyclones, "LANDFALL", (spot,)):
            ((gap, fix, place),) = storm.threats(400.0)
            raised = alerts.cyclone_rules(
                SimpleNamespace(active=(storm,), basins={}))
        self.assertEqual(fix.tau, 0)
        self.assertEqual(fix, now)
        self.assertAlmostEqual(
            gap, cyclones.great_circle(-103.0, 17.0, -102.0, 18.0), places=6)
        (threat,) = [a for a in raised if a.code.startswith("tc_threat_")]
        self.assertIn(f"is {gap:.0f} km from Behind It now", threat.title)
        self.assertIn("moving away", threat.title)
        self.assertNotIn("in 0 h", threat.title + threat.detail)

    def test_a_storm_closest_now_reads_as_now_everywhere(self):
        # "+0 h" and "in 0 h" are what a lead of zero prints by default, and
        # neither says the thing that matters: it is closest now and leaving.
        spot = cyclones.Place("Behind It", -102.0, 18.0, "Nowhere")
        storm = self.storm(
            track=(_fix(stamp="2026092312", lat=17.0, lon=-103.0, wind=135,
                        stage="HU"),),
            forecast=tuple(
                _fix(stamp="2026092312", tau=tau, lat=lat, lon=lon, wind=130,
                     stage="HU", tech="OFCL")
                for tau, lat, lon in ((12, 18.0, -106.0), (24, 19.0, -109.0))))
        state = SimpleNamespace(cyclones=SimpleNamespace(
            available=True, active=(storm,), as_of="2026-09-23T15:00",
            basins={}, notes=[], upgrades=[], through="23 September", year=2026,
            elnino_years=()),
            assessment=SimpleNamespace(index_name="RONI", scale=None,
                                       index_latest=SimpleNamespace(value=1.36)))
        with mock.patch.object(cyclones, "LANDFALL", (spot,)):
            card = storms.tracks_card(state)
            text = "\n".join(report._section_cyclones(state))
            layer = globe.storm_layer(state)
        for shown in (card, text):
            self.assertIn("Behind It", shown)
            self.assertNotRegex(shown, r"[+]0 ?h|in 0 h")
        self.assertIn("now", card)
        self.assertRegex(text, r"now 12Z 23 Sep")
        (threat,) = layer[0]["threats"]
        self.assertEqual(threat[-1], "now")

    def report_state(self, storm):
        return SimpleNamespace(cyclones=SimpleNamespace(
            available=True, active=(storm,), as_of="2026-09-23T15:00",
            basins={}, notes=[], upgrades=[], through="23 September", year=2026,
            elnino_years=()),
            assessment=SimpleNamespace(index_name="RONI", scale=None,
                                       index_latest=SimpleNamespace(value=1.36)))

    def test_the_longest_category_fits_the_report_forecast_table(self):
        # JTWC's names run longer than NHC's: "Category 5-equivalent super
        # typhoon" is 35 characters, and the table has to hold it whole.
        storm = cyclones.Storm(
            basin="WP", number=25, year=2026, name="Surigae", centre="JTWC",
            track=(_fix(stamp="2026092512", lat=21.4, lon=128.2, wind=155,
                        stage="ST"),),
            forecast=tuple(
                _fix(stamp="2026092512", tau=tau, lat=lat, lon=128.0, wind=155,
                     stage="ST", tech="JTWC")
                for tau, lat in ((12, 22.5), (120, 30.4))),
            advisory={"advisory": "12"})
        text = report._section_cyclones(self.report_state(storm))
        self.assertIn("Category 5-equivalent super typhoon", "\n".join(text))
        for line in text:
            self.assertLessEqual(len(line), report.WIDTH, line)

    def test_the_longest_place_and_intensity_fit_the_report(self):
        # "60 kt subtrop storm" is the longest intensity the table prints, and
        # the gazetteer has names of 33 characters. Neither may be cut short.
        spot = cyclones.Place("General Eugenio Alejandrino Garay", -102.0, 16.0,
                              "Paraguay")
        storm = self.storm(
            track=(_fix(stamp="2026092312", lat=15.0, lon=-101.0, wind=60,
                        stage="SS"),),
            forecast=tuple(
                _fix(stamp="2026092312", tau=tau, lat=lat, lon=lon, wind=60,
                     stage="SS", tech="OFCL")
                for tau, lat, lon in ((12, 15.8, -102.0), (24, 16.5, -103.0))))
        with mock.patch.object(cyclones, "LANDFALL", (spot,)):
            text = report._section_cyclones(self.report_state(storm))
        joined = "\n".join(text)
        self.assertIn("General Eugenio Alejandrino Garay", joined)
        self.assertIn("60 kt subtrop storm", joined)
        for line in text:
            self.assertLessEqual(len(line), report.WIDTH, line)

    def test_two_storms_side_by_side_keep_their_labels_apart(self):
        # On 25 September 2026 Odalys's "115 kt · Cat 4" was written over
        # Polo's "155 kt · Cat 5": every storm's labels went to the right of
        # its eye, whatever another storm had already put there.
        # A storm in the Atlantic widens the map to the scale it had then,
        # where 8 degrees of longitude is shorter than one of the labels.
        def storm(basin, number, name, lon, lat):
            return cyclones.Storm(
                basin=basin, number=number, year=2026, name=name,
                track=(_fix(stamp="2026092512", lat=lat, lon=lon, wind=115),),
                forecast=(_fix(stamp="2026092512", tau=24, lat=lat + 2.0,
                               lon=lon - 3.0, wind=115, tech="OFCL"),),
                advisory={"advisory": "20"})
        drawn = storms.track_map([storm("EP", 16, "Odalys", -124.0, 17.7),
                                  storm("EP", 17, "Polo", -116.0, 17.1),
                                  storm("AL", 6, "Fay", -45.0, 25.0)])
        names = [box[0] for box in _label_boxes(drawn)]
        self.assertIn("Polo", names)
        self.assertIn("115 kt · Cat 4", names)
        self.assertIsNone(_first_overlap(_label_boxes(drawn)))

    def test_a_member_across_the_date_line_keeps_the_map_to_the_storm(self):
        # On 29 September 2026 Nolo's ensemble ran from 179.9 W to 179.3 E:
        # drawn from its smallest longitude to its largest, the map came out
        # 430 degrees wide, every storm a dot and no town's name finding room.
        nolo = cyclones.Storm(
            basin="EP", number=15, year=2026, name="Nolo",
            track=(_fix(stamp="2026092912", lat=20.1, lon=-164.2, wind=100),),
            forecast=(_fix(stamp="2026092912", tau=24, lat=22.3, lon=-164.5, wind=70,
                           tech="OFCL"),),
            ensemble={"AP01": tuple(
                _fix(stamp="2026092912", tau=tau, lat=lat, lon=lon, wind=60, tech="AP01")
                for tau, lat, lon in ((24, 22.0, -174.0), (48, 22.5, -179.9),
                                      (72, 23.0, 179.3)))},
            advisory={"advisory": "20"})
        drawn = storms.track_map([nolo])
        degrees = re.findall(r'class="tick">(\d+&#176;[EW]?)</text>', drawn)
        self.assertEqual(len(degrees), len(set(degrees)), degrees)
        self.assertLessEqual(len(degrees), 6, degrees)
        # The member runs west across the date line, and so does its line.
        [member] = re.findall(r'<path d="([^"]+)"[^>]*opacity="0.30"', drawn)
        xs = [float(x) for x in re.findall(r"[ML]([-\d.]+) ", member)]
        self.assertEqual(xs, sorted(xs, reverse=True))

    def test_a_fix_past_the_date_line_is_hovered_at_its_own_longitude(self):
        # Framed about the storm, a forecast point at 178 E lies at -182, and
        # its hover read "182.0°W".
        def fix(lon, tau=0):
            return _fix(stamp="2026092912", tau=tau, lat=20.0, lon=lon, wind=90,
                        tech="OFCL" if tau else "BEST")
        nolo = cyclones.Storm(basin="CP", number=5, year=2026, name="Nolo",
                              track=(fix(-176.0), fix(-178.0), fix(-179.0)),
                              forecast=(fix(178.0, 12), fix(176.5, 24)),
                              advisory={"advisory": "20"})
        drawn = storms.track_map([nolo])
        where = [unescape(unescape(extra)).split(",")[0]
                 for extra in re.findall(r'data-extra="([^"]*)"', drawn)]
        for point in ("20.0°N 179.0°W", "20.0°N 178.0°E", "20.0°N 176.5°E"):
            self.assertIn(point, where)
        self.assertEqual([w for w in where if re.search(r"1[89]\d\.\d°", w)], [], where)
        # The date line and the meridian have no hemisphere, however near.
        for lon, words in ((-180.0, "180.0°"), (179.96, "180.0°"), (-0.02, "0.0°")):
            self.assertEqual(unescape(storms._degrees(SimpleNamespace(lat=20.0, lon=lon))),
                             f"20.0°N {words}")

    def test_a_town_under_a_forecast_eye_still_gets_a_clear_name(self):
        # The 12-hour point sits on the town itself, a category 4 eye 9.5
        # units across plus a unit of margin, 10.5 each way. Every spot next
        # to the dot - 15 below, 7 above, 7 either side - lands on it; the
        # name has to go one step further out to be read.
        town = cyclones.Place("Target", -106.0, 18.0, "Nowhere")
        storm = self.storm(
            track=(_fix(stamp="2026092312", lat=16.0, lon=-104.0, wind=135,
                        stage="HU"),),
            forecast=tuple(
                _fix(stamp="2026092312", tau=tau, lat=lat, lon=lon, wind=wind,
                     stage="HU", tech="OFCL")
                for tau, lat, lon, wind in ((12, 18.0, -106.0, 135),
                                            (24, 20.0, -108.0, 130))))
        with mock.patch.object(cyclones, "LANDFALL", (town,)):
            drawn = storms.track_map([storm])
        dot = re.search(r'<circle cx="([-\d.]+)" cy="([-\d.]+)" r="3.2"', drawn)
        cx, cy = float(dot.group(1)), float(dot.group(2))
        eye = re.search(rf'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="([-\d.]+)"'
                        r'[^>]*stroke-width="2"', drawn)
        self.assertIsNotNone(eye)
        reach = float(eye.group(1)) + 1.0
        (label,) = re.findall(r'<text x="([-\d.]+)" y="([-\d.]+)" '
                              r'text-anchor="(\w+)"[^>]*placename[^>]*>Target<',
                              drawn)
        x, y, anchor = float(label[0]), float(label[1]), label[2]
        width = 0.55 * 11.0 * len("Target")
        left = (x - width / 2 if anchor == "middle"
                else x - width if anchor == "end" else x)
        box = (left, y - 0.75 * 11.0, left + width, y + 0.2 * 11.0)
        self.assertFalse(box[0] < cx + reach and cx - reach < box[2]
                         and box[1] < cy + reach and cy - reach < box[3], box)
        # Pushed that far out, the name is tied back to its dot: a hairline
        # from the dot's edge to the label, or a cluster of towns reads as
        # whichever names happen to sit nearest.
        leaders = [tuple(map(float, found)) for found in re.findall(
            r'<line class="leader" x1="([-\d.]+)" y1="([-\d.]+)" '
            r'x2="([-\d.]+)" y2="([-\d.]+)"', drawn)]
        self.assertEqual(len(leaders), 1)
        x1, y1, x2, y2 = leaders[0]
        self.assertLessEqual(math.hypot(x1 - cx, y1 - cy), 4.0)
        self.assertGreaterEqual(x2, box[0] - 4.0)
        self.assertLessEqual(x2, box[2] + 4.0)
        self.assertGreaterEqual(y2, box[1] - 4.0)
        self.assertLessEqual(y2, box[3] + 4.0)

    def test_a_tall_window_is_widened_not_stretched(self):
        # 15 degrees of longitude by 30 of latitude in a 780-unit frame is
        # 1560 units tall at true shape. Capped at 560, the longitude has to
        # grow to 780 * 30 / 560 = 41.79 degrees, 13.39 either side.
        lon0, lon1, lat0, lat1, height = storms._fit(-75.0, -60.0, 15.0, 45.0, 780.0)
        self.assertEqual(height, 560.0)
        self.assertAlmostEqual(lon0, -75.0 - 13.392857, places=5)
        self.assertAlmostEqual(lon1, -60.0 + 13.392857, places=5)
        self.assertEqual((lat0, lat1), (15.0, 45.0))

    def test_a_wide_window_grows_in_latitude_inside_the_map(self):
        # 160 by 28 degrees is 136.5 units tall; the floor of 300 needs
        # 300 * 160 / 780 = 61.54 degrees. Grown 16.77 each way, 40-68N
        # would reach 84.77N; it is moved down to end at 70N instead.
        lon0, lon1, lat0, lat1, height = storms._fit(-180.0, -20.0, 40.0, 68.0, 780.0)
        self.assertEqual(height, 300.0)
        self.assertEqual((lon0, lon1), (-180.0, -20.0))
        self.assertAlmostEqual(lat1, 70.0, places=6)
        self.assertAlmostEqual(lat1 - lat0, 300.0 * 160.0 / 780.0, places=6)

    def test_the_graticule_names_the_equator_and_the_date_line(self):
        # A central Pacific storm's window runs past -180. Its labels were
        # "190°W", a longitude that does not exist, "180°W", which is neither,
        # and "0°N" for the equator.
        from elnino.svg import Plot
        plot = Plot(940, 470, storms.PAD)
        plot.domain(-200.0, -150.0, -10.0, 10.0)
        storms._graticule(plot, -200.0, -150.0, -10.0, 10.0)
        labels = [unescape(text) for text in re.findall(
            r'class="tick">([^<]*)</text>', "".join(plot.parts))]
        self.assertEqual(labels, ["160°E", "170°E", "180°", "170°W", "160°W",
                                  "150°W", "10°S", "EQ", "10°N"])


class TestSeasonClimatology(unittest.TestCase):
    # Two storms in one season: one that peaked in August, one in October.
    # Anything comparing a September season against the full-year total has to
    # get these two wrong in opposite directions.
    HURDAT = """\
AL012020,             EARLY,     4,
20200810, 0000,  , TS, 15.0N,  50.0W,  50, 1000,
20200810, 0600,  , TS, 15.5N,  51.0W,  50, 1000,
20200810, 1200,  , HU, 16.0N,  52.0W,  70,  985,
20200810, 1800,  , HU, 16.5N,  53.0W, 100,  960,
AL022020,              LATE,     4,
20201015, 0000,  , TS, 20.0N,  60.0W,  50, 1000,
20201015, 0600,  , TS, 20.5N,  61.0W,  50, 1000,
20201015, 1200,  , HU, 21.0N,  62.0W,  70,  985,
20201015, 1800,  , HU, 21.5N,  63.0W, 100,  960,
AL012019,          NEITHER,     2,
20190901, 0300,  , TS, 25.0N,  70.0W,  60, 1000,
20190901, 0000,  , EX, 25.5N,  71.0W,  80,  990,
"""

    def table(self, through=(9, 23)):
        return cyclones.hurdat_seasons(self.HURDAT, through=through)

    def test_a_season_is_counted_whole_and_to_the_date(self):
        seasons = self.table()
        year = seasons[2020]
        one_storm = (50 ** 2 + 50 ** 2 + 70 ** 2 + 100 ** 2) * 1e-4
        self.assertAlmostEqual(year["ace"], one_storm * 2, places=6)
        self.assertAlmostEqual(year["ace_todate"], one_storm, places=6)
        self.assertEqual(year["named"], 2)
        self.assertEqual(year["named_todate"], 1)
        self.assertEqual(year["hurricanes"], 2)
        self.assertEqual(year["hurricanes_todate"], 1)
        self.assertEqual(year["major"], 2)
        self.assertEqual(year["major_todate"], 1)

    def test_ace_ignores_intermediate_and_extratropical_fixes(self):
        """Both of 2019's fixes are disqualified - one off the synoptic hours,
        one post-tropical - so the season has a named storm and no energy."""
        year = self.table()[2019]
        self.assertEqual(year["ace"], 0.0)
        self.assertEqual(year["named"], 1)

    def test_the_two_pacific_centres_are_one_ledger(self):
        self.assertEqual(cyclones.season_of("CP"), "EP")
        self.assertEqual(cyclones.season_of("EP"), "EP")
        self.assertEqual(cyclones.season_of("AL"), "AL")
        merged = cyclones.merge_seasons({2020: {"ace": 10.0, "named": 2}},
                                        {2020: {"ace": 5.0, "named": 1}})
        self.assertEqual(merged[2020]["ace"], 15.0)
        self.assertEqual(merged[2020]["named"], 3)

    def test_a_running_season_is_scored_against_the_same_date(self):
        """The bug this exists to catch: 4 units of ACE by 23 September
        against an 8-unit full season reads as half normal, and against the 4
        units a normal season had by that date reads as exactly normal."""
        normal = {"ace": 8.0, "ace_todate": 4.0, "named": 14.0,
                  "hurricanes": 7.0, "major": 3.0, "years": 30}
        season = cyclones.BasinSeason(basin="AL", storms=(_loaded("AL", 100),),
                                      normal=normal, through="23 September")
        self.assertAlmostEqual(season.ace, 4.0)
        self.assertEqual(season.normal_ace, 4.0)
        self.assertEqual(season.full_normal_ace, 8.0)
        self.assertAlmostEqual(season.ace_ratio, 1.0)
        self.assertAlmostEqual(season.elapsed, 0.5)

    def test_the_index_page_is_scraped_rather_than_the_name_assumed(self):
        """The file is renamed every spring; hard-coding it freezes the
        climatology at whatever year the code was written."""
        page = """<a href="hurdat2-1851-2023-051124.txt">Atlantic 2023</a>
        <a href="hurdat2-1851-2024-040425.txt">Atlantic 2024</a>
        <a href="hurdat2-nepac-1949-2024-042625.txt">Pacific</a>"""
        self.assertEqual(cyclones.hurdat_latest(page, "AL"),
                         "hurdat2-1851-2024-040425.txt")
        self.assertEqual(cyclones.hurdat_latest(page, "EP"),
                         "hurdat2-nepac-1949-2024-042625.txt")
        self.assertIsNone(cyclones.hurdat_latest("<p>nothing here</p>", "AL"))

    def test_the_season_roster_skips_invests_and_other_years(self):
        listing = ("bal052026.dat bep152026.dat bep162026.dat bep172026.dat "
                   "bep902026.dat bep942026.dat bep172025.dat bwp172026.dat")
        self.assertEqual(cyclones.season_ids(listing, 2026),
                         ["al052026", "ep152026", "ep162026", "ep172026"])


class TestElNinoVerdict(unittest.TestCase):
    def season(self, basin, ratio):
        """A season at a chosen ratio, made by moving the normal rather than
        by inventing a storm no ocean could produce."""
        normal = {"ace": 8.0 / ratio, "ace_todate": 4.0 / ratio, "named": 14.0,
                  "hurricanes": 7.0, "major": 3.0, "years": 30}
        return cyclones.BasinSeason(
            basin=basin, storms=(_loaded(basin, 100),), normal=normal,
            through="23 September")

    def test_expectation_is_read_off_the_effect_not_the_polarity(self):
        """Every basin entry in the catalogue is polarity "storm". The
        direction lives in the sentence, and reading the polarity instead
        makes a suppressed Atlantic and an enhanced Pacific the same claim."""
        self.assertEqual(
            cyclones.expectation(cyclones.link_for("AL")), "below normal")
        self.assertEqual(
            cyclones.expectation(cyclones.link_for("EP")), "above normal")

    def test_a_quiet_atlantic_in_an_el_nino_confirms_the_catalogue(self):
        flavour = impacts.flavour_of(3.2)
        scored = cyclones.verdict(self.season("AL", 0.10), 1.8, flavour)
        self.assertEqual(scored["expected"], "below normal")
        self.assertEqual(scored["observed"], "below normal")
        self.assertIs(scored["agrees"], True)

    def test_a_busy_atlantic_in_an_el_nino_contradicts_it(self):
        flavour = impacts.flavour_of(3.2)
        scored = cyclones.verdict(self.season("AL", 1.9), 1.8, flavour)
        self.assertEqual(scored["observed"], "above normal")
        self.assertIs(scored["agrees"], False)

    def test_a_season_near_its_normal_settles_nothing(self):
        """ENSO shifts the odds over a basin; it does not decide one season,
        and a 0.95x Atlantic is what suppressed and ordinary both look like."""
        flavour = impacts.flavour_of(3.2)
        scored = cyclones.verdict(self.season("AL", 0.95), 1.8, flavour)
        self.assertEqual(scored["observed"], "near normal")
        self.assertIsNone(scored["agrees"])

    def test_the_verdict_uses_the_same_gating_as_the_hazard_outlook(self):
        flavour = impacts.flavour_of(3.2)
        link = cyclones.link_for("EP")
        margin, likelihood, _ = impacts.evaluate(link, 1.8, flavour)
        scored = cyclones.verdict(self.season("EP", 1.8), 1.8, flavour)
        self.assertEqual(scored["likelihood"], likelihood)
        self.assertAlmostEqual(scored["margin"], round(margin, 2))

    def test_el_nino_seasons_come_from_the_systems_own_oni(self):
        seasons = [SeasonValue(year=2014, season="ASO", value=0.2),
                   SeasonValue(year=2015, season="ASO", value=2.0),
                   SeasonValue(year=2015, season="DJF", value=2.5),
                   SeasonValue(year=2023, season="ASO", value=1.3)]
        self.assertEqual(cyclones.elnino_years(seasons), (2015, 2023))


class TestCyclonesOnTheGlobe(unittest.TestCase):
    """The storm overlay has to be the same storm as the flat track map."""

    def state(self):
        grid = grids.Field(
            x=tuple(-180.0 + 45.0 * c for c in range(8)),
            y=tuple(-75.0 + 30.0 * r for r in range(6)),
            values=[[1.0 for _ in range(8)] for _ in range(6)],
            label="global sst", units="degrees C", as_of="2026-09-23",
        )
        storm = cyclones.Storm(
            basin="EP", number=17, year=2026, name="Polo",
            advisory={"advisory": "011a"},
            track=tuple(_fix(stamp=stamp, lat=lat, lon=lon, wind=wind)
                        for stamp, lat, lon, wind in (
                            ("2026092300", 14.8, -100.9, 45),
                            ("2026092312", 15.2, -101.5, 130))),
            forecast=tuple(_fix(stamp="2026092312", tau=tau, lat=lat, lon=lon,
                                wind=wind, tech="OFCL")
                           for tau, lat, lon, wind in (
                               (24, 16.2, -103.4, 135),
                               (120, 22.4, -113.1, 90))),
        )
        season = cyclones.BasinSeason(basin="EP", storms=(storm,))
        return SimpleNamespace(
            spatial=SimpleNamespace(sst_global=grid),
            assessment=SimpleNamespace(
                index_name="RONI",
                index_latest=SimpleNamespace(value=1.36),
                scale=SimpleNamespace(flavour_index=3.24)),
            forecast=SimpleNamespace(peak=SimpleNamespace(label="SON 2026")),
            impacts=SimpleNamespace(peak_index=2.27),
            cyclones=cyclones.CycloneState(basins={"EP": season},
                                           as_of="2026-09-23T12:00:00Z"),
        )

    def payload(self, html):
        raw = html.split("data-globe='", 1)[1].split("'>", 1)[0]
        return json.loads(unescape(raw))

    def test_a_storm_reaches_the_sphere_and_the_redraw_payload(self):
        html = globe.card(self.state())
        self.assertIn('<g class="storms">', html)
        self.assertIn('class="tcdot"', html)
        self.assertIn('class="tcahead"', html)
        storms = self.payload(html)["storms"]
        self.assertEqual(len(storms), 1)
        self.assertEqual(storms[0]["name"], "Polo")
        self.assertEqual(storms[0]["cat"], 4)

    def test_tracks_travel_as_flat_pairs(self):
        """Half a coordinate pair is a storm in the wrong ocean."""
        storm = self.payload(globe.card(self.state()))["storms"][0]
        for key in ("track", "ahead"):
            self.assertEqual(len(storm[key]) % 2, 0)
            self.assertTrue(storm[key])
        # The forecast leg starts at the current position, so the dashed line
        # joins the solid one instead of starting twelve hours away from it.
        self.assertEqual(storm["ahead"][:2], [storm["lon"], storm["lat"]])

    def test_the_forecast_shipped_to_the_browser_stops_at_the_horizon(self):
        storm = self.payload(globe.card(self.state()))["storms"][0]
        self.assertTrue(storm["steps"])
        for tau, *_ in storm["steps"]:
            self.assertLessEqual(tau, cyclones.HORIZON)

    def test_colour_identifies_the_storm_and_matches_the_track_map(self):
        """A reader moving between the globe and the map must not have to
        relearn which line is which."""
        self.assertEqual(globe.hue_for(0), storms.STORM_HUES[0])
        self.assertEqual(globe.hue_for(len(storms.STORM_HUES)), storms.NEUTRAL)
        self.assertEqual(globe.hue_for(-1), storms.NEUTRAL)

    def test_a_storm_name_wears_text_ink_not_its_line_colour(self):
        # Colour carries identity on the eye and the track beside the name;
        # the name itself stays in text ink, legible on either theme.
        state = self.state()
        track_map = storms.track_map(state.cyclones.active)
        names = re.findall(r'<text[^>]*class="endlabel[ "][^>]*>', track_map)
        self.assertTrue(names)
        for tag in names:
            self.assertNotIn("fill", tag)
        layer = self.payload(globe.card(state))["storms"]
        drawn = "".join(globe._storms(layer, -100.0, 15.0, 200.0, 320.0, 320.0))
        labels = re.findall(r'<text class="tcname"[^>]*>', drawn)
        self.assertTrue(labels)
        for tag in labels:
            self.assertNotIn("fill", tag)
        self.assertIsNone(re.search(r'class="tcname".{0,160}?style="fill:',
                                    globe.js(), re.S))

    def test_a_run_with_no_storms_still_draws_the_globe(self):
        state = self.state()
        state.cyclones = cyclones.CycloneState()
        html = globe.card(state)
        self.assertIn('class="globe"', html)
        self.assertEqual(self.payload(html)["storms"], [])
        self.assertNotIn("data-globe-storm", html)

    def test_the_script_can_redraw_and_pick_a_storm(self):
        script = globe.js()
        for symbol in ("function stormArt", "function pickStorm",
                       "function reportStorm", "stormArt(r)"):
            self.assertIn(symbol, script)




# ---------------------------------------------------------------------------
#  Project STORMFURY, recreated
# ---------------------------------------------------------------------------


def _fury_storm(basin="EP", number=17, name="Polo", lat=15.2, lon=-101.5,
                fixes=(), forecast=()):
    """A storm built to exercise one STORMFURY rule at a time."""
    track = tuple(_fix(stamp=stamp, lat=lat, lon=lon, wind=wind, rmw=rmw,
                       stage="HU" if wind >= 64 else "TS")
                  for stamp, wind, rmw in fixes)
    ahead = tuple(_fix(stamp=track[-1].stamp if track else "2026092312",
                       tau=tau, lat=flat, lon=flon, wind=wind, tech="OFCL")
                  for tau, flat, flon, wind in forecast)
    return cyclones.Storm(basin=basin, number=number, year=2026, name=name,
                          advisory={"advisory": "011a"},
                          track=track, forecast=ahead)


class TestAngularMomentum(unittest.TestCase):
    """The hypothesis itself, which was never the part that was wrong."""

    def test_at_the_equator_relocation_is_pure_one_over_r(self):
        """With no Coriolis term, M = rv, so doubling the eyewall halves the
        wind exactly. Any other answer means the algebra is wrong."""
        self.assertAlmostEqual(
            stormfury.relocated_wind(100.0, 10.0, 20.0, 0.0), 50.0, places=6)
        self.assertAlmostEqual(
            stormfury.relocated_wind(120.0, 12.0, 18.0, 0.0), 80.0, places=6)

    def test_the_planetary_term_takes_a_bite_out_of_the_budget(self):
        """Away from the equator, half f r squared grows with r, so the same
        absolute momentum buys less relative wind further out. A relocation
        that looked gentler at latitude would mean the sign is flipped."""
        flat = stormfury.relocated_wind(100.0, 10.0, 20.0, 0.0)
        north = stormfury.relocated_wind(100.0, 10.0, 20.0, 25.0)
        south = stormfury.relocated_wind(100.0, 10.0, 20.0, -25.0)
        self.assertLess(north, flat)
        # And it bites equally hard on both sides of the equator. A cyclone
        # at 25S turns the other way, which is a sign convention, not a
        # discount on the planetary term.
        self.assertAlmostEqual(north, south, places=6)
        self.assertLess(stormfury.coriolis(-25.0), 0.0)

    def test_absolute_momentum_is_the_textbook_expression(self):
        radius = 20.0 * stormfury.NM_TO_M
        wind = 90.0 * stormfury.KT_TO_MS
        expected = radius * wind + 0.5 * stormfury.coriolis(15.0) * radius ** 2
        self.assertAlmostEqual(
            stormfury.absolute_momentum(20.0, 90.0, 15.0), expected, places=3)

    def test_a_radius_beyond_the_budget_has_no_answer_not_a_wrong_one(self):
        """Far enough out the planetary term alone exceeds the momentum and
        the relative wind turns negative, which is an anticyclone, not a
        weaker hurricane. It reports nothing instead."""
        self.assertIsNone(stormfury.relocated_wind(60.0, 10.0, 4000.0, 30.0))
        self.assertIsNone(stormfury.relocated_wind(100.0, 0.0, 20.0, 15.0))
        self.assertIsNone(stormfury.relocated_wind(100.0, 10.0, 0.0, 15.0))

    def test_the_table_weakens_monotonically_and_never_gains_a_category(self):
        table = stormfury.momentum_table(130.0, 10.0, 15.2)
        self.assertEqual(len(table), len(stormfury.EXPANSION))
        drops = [row["drop_pct"] for row in table]
        self.assertEqual(drops, sorted(drops))
        for row in table:
            self.assertLessEqual(row["category_after"], row["category_before"])
            self.assertLess(row["after_kt"], row["before_kt"])

    def test_the_seedable_layer_sits_above_the_freezing_level(self):
        layer = stormfury.seedable_layer()
        self.assertLess(layer["freezing_km"], layer["base_km"])
        self.assertLess(layer["base_km"], layer["top_km"])
        self.assertAlmostEqual(layer["depth_km"],
                               layer["top_km"] - layer["base_km"], places=1)


class TestSeedingCriteria(unittest.TestCase):
    """Would the programme have been allowed to fly this storm?"""

    def criteria(self, storm):
        found = stormfury.assess(storm)
        self.assertIsNotNone(found)
        return {c.name: c for c in found.criteria}, found

    def test_the_programme_never_flew_from_guam(self):
        # A move to the western Pacific was planned in the mid-1970s and
        # abandoned; no STORMFURY aircraft seeded or staged from Guam. A
        # typhoon off Guam is over 12,000 km from Lakeland and Roosevelt Roads.
        self.assertNotIn("Guam", " ".join(name for name, _, _ in stormfury.BASES))
        self.assertFalse(stormfury._range_criterion(145.0, 15.0).passed)

    def test_a_storm_in_reach_of_a_base_passes_the_range_rule(self):
        near = stormfury._range_criterion(-80.0, 26.0)     # off Florida
        far = stormfury._range_criterion(-130.0, 15.0)     # deep east Pacific
        self.assertTrue(near.passed)
        self.assertFalse(far.passed)
        self.assertIn("km", near.detail)

    def test_an_eyewall_needs_hurricane_force_and_a_tight_radius(self):
        self.assertFalse(stormfury._eyewall_criterion(30, 10).passed)
        self.assertTrue(stormfury._eyewall_criterion(130, 10).passed)
        # Hurricane force but no radius reported: unknown, not a pass.
        self.assertIsNone(stormfury._eyewall_criterion(130, None).passed)
        self.assertFalse(
            stormfury._eyewall_criterion(130,
                                         stormfury.MAX_EYEWALL_NM + 5).passed)

    def test_the_seedability_rule_fails_for_every_storm_that_ever_was(self):
        """The one criterion that is not about this storm. It is why the
        programme ended, so it cannot be made to pass by better weather."""
        self.assertFalse(stormfury._seedability_criterion().passed)
        self.assertIn("glaciated",
                      stormfury._seedability_criterion().detail.lower())

    def test_a_storm_heading_for_land_is_not_eligible(self):
        """Seeding something about to make landfall makes the experiment
        unreadable and the liability unbounded."""
        offshore = _fury_storm(fixes=(("2026092312", 130, 10),),
                               forecast=((24, 16.2, -103.4, 135),))
        inbound = _fury_storm(lat=25.0, lon=-96.0,
                              fixes=(("2026092312", 130, 10),),
                              forecast=((24, 25.6, -97.3, 130),))
        self.assertTrue(stormfury._landfall_criterion(offshore).passed)
        self.assertFalse(stormfury._landfall_criterion(inbound).passed)

    def test_a_perfect_hurricane_is_still_blocked_by_the_trigger(self):
        """Put a storm right where the programme wanted one - hurricane
        strength, tight eyewall, in range, days from land - and it still
        fails, on the criterion no hurricane has ever passed."""
        storm = _fury_storm(basin="AL", lat=28.0, lon=-72.0,
                            fixes=(("2026092312", 130, 10),),
                            forecast=((24, 29.0, -71.0, 130),))
        rules, found = self.criteria(storm)
        self.assertTrue(rules["Within aircraft range"].passed)
        self.assertTrue(rules["Coherent eyewall"].passed)
        self.assertFalse(rules["Supercooled water to seed"].passed)
        self.assertFalse(found.eligible)
        self.assertEqual(found.blocked_by, ["Supercooled water to seed"])
        self.assertTrue(found.momentum)

    def test_a_storm_with_no_eyewall_carries_no_momentum_table(self):
        """Quoting a relocation for a 30 kt depression would be arithmetic
        about a structure that does not exist."""
        weak = _fury_storm(name="Fifteen-E",
                           fixes=(("2026092312", 30, None),))
        found = stormfury.assess(weak)
        self.assertEqual(found.momentum, [])
        self.assertFalse(found.eligible)


class TestNaturalConfound(unittest.TestCase):
    """The measurement problem: hurricanes do this on their own."""

    def moves(self, fixes):
        return stormfury.eyewall_moves([_fury_storm(fixes=fixes)])

    def test_a_real_eyewall_expansion_is_scored(self):
        found = self.moves((("2026092312", 130, 10), ("2026092318", 120, 16)))
        self.assertEqual(len(found), 1)
        self.assertEqual(found[0]["from_nm"], 10)
        self.assertEqual(found[0]["to_nm"], 16)
        self.assertEqual(found[0]["wind_before"], 130)
        self.assertAlmostEqual(found[0]["observed_pct"], -7.7, places=1)
        self.assertLess(found[0]["predicted_kt"], found[0]["wind_before"])

    def test_a_tropical_storm_radius_is_not_an_eyewall(self):
        """Below hurricane force the radius of maximum wind is a wind field.
        Applying eyewall physics to it produces confident nonsense."""
        self.assertEqual(
            self.moves((("2026092312", 45, 30), ("2026092318", 40, 55))), [])

    def test_a_radius_too_wide_to_be_an_eyewall_is_left_alone(self):
        self.assertEqual(
            self.moves((("2026092312", 90, 80), ("2026092318", 85, 120))), [])

    def test_a_jump_too_large_to_be_structural_is_a_reanalysis(self):
        """An RMW that quintuples between two six-hourly analyses is a
        forecaster changing their mind, not an eyewall moving."""
        self.assertEqual(
            self.moves((("2026092312", 100, 10), ("2026092318", 95, 50))), [])

    def test_a_contracting_eyewall_is_not_a_relocation(self):
        self.assertEqual(
            self.moves((("2026092312", 100, 20), ("2026092318", 115, 10))), [])

    def test_swings_are_counted_only_among_storms_debbie_belonged_to(self):
        """A depression becoming a tropical storm is a 200 per cent swing and
        tells you nothing about what seeding a hurricane would do."""
        genesis = _fury_storm(fixes=(("2026092012", 25, None),
                                     ("2026092112", 75, None)))
        weakening = _fury_storm(fixes=(("2026092012", 130, 10),
                                       ("2026092112", 85, 20)))
        swings = stormfury.natural_swings([genesis, weakening])
        self.assertEqual(swings["count"], 1)
        self.assertEqual(swings["weakened_as_much"], 1)
        self.assertEqual(swings["moved_as_much"], 1)
        self.assertAlmostEqual(swings["biggest_drop"], -34.6, places=1)

    def test_the_window_is_exactly_debbies_and_other_gaps_are_ignored(self):
        storm = _fury_storm(fixes=(("2026092012", 130, 10),
                                   ("2026092018", 90, 12)))
        self.assertEqual(stormfury.natural_swings([storm])["count"], 0)

    def test_the_prediction_is_scored_against_what_the_storm_actually_did(self):
        """The finding this section exists for: a closed-system momentum
        argument is an upper bound, because the inflow keeps feeding the
        vortex while the eyewall moves."""
        scored = stormfury.relocation_skill([
            {"key": "ep17", "wind_before": 100, "predicted_kt": 50,
             "observed_pct": -10.0},
            {"key": "ep17", "wind_before": 100, "predicted_kt": 70,
             "observed_pct": 0.0},
            {"key": "al09", "wind_before": 80, "predicted_kt": None,
             "observed_pct": -5.0},
        ])
        self.assertEqual(scored["count"], 2)
        self.assertEqual(scored["storms"], 1)
        self.assertAlmostEqual(scored["mean_predicted_drop"], 40.0, places=1)
        self.assertAlmostEqual(scored["mean_observed_drop"], 5.0, places=1)
        self.assertAlmostEqual(scored["overstatement"], 8.0, places=1)
        self.assertEqual(scored["held_or_strengthened"], 1)

    def test_nothing_to_score_is_reported_as_nothing(self):
        self.assertEqual(stormfury.relocation_skill([]), {"count": 0})
        self.assertEqual(
            stormfury.relocation_skill([{"key": "x", "wind_before": 100,
                                         "predicted_kt": None,
                                         "observed_pct": -3.0}]),
            {"count": 0})


class TestFuryAssembly(unittest.TestCase):
    """The state object and the three reasons it prints."""

    def state(self, rich=False):
        """One live storm. ``rich`` gives it a track long enough to supply
        the two measurements - an eyewall that moved and a 24-hour swing -
        so the evidence blocks have something under them."""
        fixes = ((("2026092212", 130, 10), ("2026092218", 120, 16),
                  ("2026092300", 105, 20), ("2026092312", 130, 12))
                 if rich else (("2026092312", 130, 10),))
        storm = _fury_storm(fixes=fixes, forecast=((24, 16.2, -103.4, 135),))
        season = cyclones.BasinSeason(basin="EP", storms=(storm,))
        return cyclones.CycloneState(basins={"EP": season},
                                     as_of="2026-09-23T12:00:00Z")

    def test_no_storms_still_describes_the_layer_and_stays_quiet(self):
        empty = stormfury.evaluate(cyclones.CycloneState())
        self.assertFalse(empty.available)
        self.assertTrue(empty.layer)
        self.assertFalse(stormfury.evaluate(None).available)

    def test_a_live_storm_produces_a_verdict_and_the_trigger_reason(self):
        fury = stormfury.evaluate(self.state())
        self.assertTrue(fury.available)
        self.assertEqual(len(fury.assessments), 1)
        self.assertEqual(fury.eligible, [])
        self.assertIn("supercooled water", fury.verdict)
        # The trigger reason stands with no data behind it at all; the other
        # two only appear when this season supplied the numbers.
        self.assertTrue(fury.reasons[0].startswith("TRIGGER:"))
        self.assertIn("Willoughby", fury.reasons[0])

    def test_the_record_is_the_four_storms_that_were_actually_seeded(self):
        self.assertEqual([h.name for h in stormfury.HISTORY],
                         ["Esther", "Beulah", "Debbie", "Ginger"])
        self.assertEqual(stormfury.PROGRAMME["seeded"], len(stormfury.HISTORY))
        self.assertIn("31 per cent", stormfury.HISTORY[2].claimed)

    def test_the_card_carries_its_charts_a_legend_and_a_table_twin(self):
        state = SimpleNamespace(stormfury=stormfury.evaluate(self.state(True)))
        html = storms.fury_card(state)
        self.assertIn("PROJECT STORMFURY", html.upper())
        self.assertIn('class="legend"', html)
        self.assertIn("<svg", html)
        self.assertIn("Supercooled water to seed", html)
        # Every chart on the card has a table beside it: the momentum table,
        # the relocation scores, the swing distribution, and the record.
        self.assertGreaterEqual(html.count("Table view"), 4)

    def test_a_claim_with_no_numbers_under_it_is_left_off_the_page(self):
        """Both measurement blocks argue from this season's decks. With no
        decks behind them they would be a conclusion above an empty table."""
        thin = storms.fury_card(
            SimpleNamespace(stormfury=stormfury.evaluate(self.state())))
        rich = storms.fury_card(
            SimpleNamespace(stormfury=stormfury.evaluate(self.state(True))))
        for heading in ("What real eyewalls actually do",
                        "Why nobody could have told"):
            self.assertNotIn(heading, thin)
            self.assertIn(heading, rich)
        # The parts that stand on their own are still there.
        self.assertIn("The mechanism, computed", thin)
        self.assertIn("The record", thin)

    def test_a_run_with_no_storms_draws_no_card_rather_than_an_empty_one(self):
        state = SimpleNamespace(
            stormfury=stormfury.evaluate(cyclones.CycloneState()))
        self.assertEqual(storms.fury_card(state), "")


@unittest.skipUnless((CACHE / "oni.cache").exists(),
                     "no cached feeds; run `python track.py` once first")
class TestEndToEnd(unittest.TestCase):
    """One offline run through the whole chain, then every renderer over it."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.state = pipeline.run(
            CACHE, Path(cls.tmp.name) / "e2e.db", offline=True, leads=9
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_run_produced_a_complete_state(self):
        self.assertTrue(self.state.assessment.headline)
        self.assertTrue(self.state.forecast.projections)
        self.assertIsNotNone(self.state.subsurface)
        self.assertTrue(self.state.atmosphere.indicators)

    def test_every_page_names_the_run_and_follows_the_site(self):
        for name, html in (("dashboard", dashboard.render(self.state)),
                           ("atlas", atlasview.page(self.state)),
                           ("storms", stormdesk.page(self.state)),
                           ("map", stormdesk.page(self.state, focus="world"))):
            with self.subTest(name):
                self.assertEqual(_named_run(html), self.state.run_at)
                self.assertEqual(html.count(f"<script>{live.SCRIPT}</script>"), 1)
                self.assertEqual(html.count("elninoLive.follow("), 1)
                # The theme a page loading again hands over is set before it is styled.
                theme, style = html.find(live.head(self.state.run_at)), html.find("<style>")
                self.assertTrue(0 <= theme < style, (theme, style))

    def test_a_run_s_pages_publish_as_one_run_naming_no_path_of_this_machine(self):
        import publish
        import track

        with (tempfile.TemporaryDirectory() as tmp,
              mock.patch.object(track.pipeline, "run", return_value=self.state),
              mock.patch("sys.stdout"), mock.patch("sys.stderr")):
            out = Path(tmp)
            self.assertIn(track.main(["--offline", "--quiet", "--out", str(out)]), (0, 1, 3))
            # On GitHub the checkout and the run's folder both lie under the
            # runner's home: a page naming either would stop every publish.
            for n, home in enumerate((ROOT, out)):
                site = out / f"site{n}"
                site.mkdir()
                self.assertEqual(publish.lay_out(out, site, home=home), self.state.run_at)
            beacon = json.loads((site / "run.json").read_text(encoding="utf-8"))
        self.assertEqual(beacon, {"run_at": self.state.run_at})

    def test_the_dashboard_names_its_run_and_is_dated_by_it(self):
        html = dashboard.render(self.state)
        self.assertEqual(_named_run(html), self.state.run_at)
        shown = (datetime.fromisoformat(self.state.run_at).astimezone(timezone.utc)
                 .strftime("%d %b %Y %H:%M UTC"))
        stamp = re.search(r"Generated (<time [^>]*>[^<]*</time>)", html)
        self.assertEqual(stamp and stamp.group(1),
                         f'<time datetime="{self.state.run_at}" data-age="{shown}">{shown}</time>')

    def test_the_dashboard_holds_a_reader_by_the_part_they_are_reading(self):
        # The run's own words above the part being read, its "Generated ...
        # (x ago)" among them, wrap to a line more or less from one run to the
        # next: on a phone the scroll alone put a reader back 21 px off after a
        # load. The follower holds them by what stands at the top of the view,
        # found again by id (elnino/live.py), so the page names its body as
        # the box to hold, and every part of it wears an id of its own.
        html = dashboard.render(self.state)
        box = re.findall(r"elninoLive\.follow\(\{ boxes: \['([\w-]+)'\] \}\)", html)
        self.assertEqual(len(box), 1, "the dashboard names no box for the follower")
        start = html.find(f'<div class="wrap" id="{box[0]}">')
        self.assertGreater(start, 0, "the box named is not the page's body")
        body = html[start:html.index("</footer>", start)]
        parts = re.findall(r'<(?:section|div) class="(?:card|hero|tiles)(?: [^"]*)?"[^>]*>', body)
        self.assertIn('<section class="hero" id="hero">', parts)
        self.assertEqual([part for part in parts if ' id="' not in part], [])
        ids = re.findall(r'(?<![\w-])id="([^"]+)"', html)
        self.assertEqual(sorted({i for i in ids if ids.count(i) > 1}), [])

    def test_no_chart_text_is_painted_in_a_series_colour(self):
        # Text wears text tokens; a series or ramp colour belongs on the mark
        # beside it. A fill attribute on a label is also dead weight under a
        # class rule, and a lie about what the page draws.
        html = dashboard.render(self.state) + atlasview.page(self.state)
        painted = re.findall(
            r'<text[^>]*(?:fill="var\(--[sd]\d+\)"|style="fill:[^"]*--[sd]\d)[^>]*>',
            html)
        self.assertEqual(painted, [])

    def test_el_nino_now_quotes_the_index_the_week_and_the_impacts(self):
        a = self.state.assessment
        section = worldmap.section(self.state)
        self.assertIn(a.index_name, section)
        self.assertIn(f"{a.index_latest.value:+.2f}", section)
        if a.latest_week:
            self.assertIn(a.latest_week.label, section)
        shows = re.findall(r'data-show-region="([^"]+)"', section)
        self.assertEqual([unescape(s) for s in shows],
                         [i.link.region for i in
                          [*self.state.impacts.active, *self.state.impacts.watch]
                          if geo.BY_REGION.get(i.link.region) is not None
                          and geo.BY_REGION[i.link.region].scope != geo.GLOBAL])
        boxes = worldmap.payload(self.state)["boxes"]
        self.assertTrue(all(b["anomaly"] is not None for b in boxes))

    def test_the_map_marks_the_impacts_this_event_puts_in_play(self):
        links = {l["region"]: l for l in worldmap.payload(self.state)["links"]}
        for impact in self.state.impacts.active:
            self.assertEqual(links[impact.link.region]["status"], "in play")
            self.assertEqual(links[impact.link.region]["likelihood"], impact.likelihood)
        for impact in self.state.impacts.watch:
            self.assertEqual(links[impact.link.region]["status"], "watch")

    def test_every_report_section_renders(self):
        for section in report.SECTIONS:
            text = report.render(self.state, sections=(section,))
            self.assertTrue(text.strip(), f"{section} rendered empty")

    def test_report_is_ascii_and_fits_eighty_columns(self):
        text = report.render(self.state)
        for number, line in enumerate(text.splitlines(), 1):
            self.assertLessEqual(len(line), report.WIDTH, f"line {number} too wide")
            self.assertTrue(line.isascii(), f"line {number} is not ASCII: {line!r}")

    def test_a_run_writes_the_storm_desk_beside_the_dashboard(self):
        import track

        with tempfile.TemporaryDirectory() as tmp,                 mock.patch.object(track.pipeline, "run", return_value=self.state),                 mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            track.main(["--offline", "--quiet", "--out", tmp])
            page = (Path(tmp) / "storms.html").read_text(encoding="utf-8")
            data = json.loads((Path(tmp) / "storms.json").read_text(encoding="utf-8"))
        self.assertIn('id="desk-data"', page)
        self.assertEqual(data["schema"], stormdesk.SCHEMA)

    def test_a_run_writes_the_map_beside_the_storm_desk(self):
        import track

        with tempfile.TemporaryDirectory() as tmp,                 mock.patch.object(track.pipeline, "run", return_value=self.state),                 mock.patch("sys.stdout"), mock.patch("sys.stderr"):
            track.main(["--offline", "--quiet", "--out", tmp])
            page = (Path(tmp) / "map.html").read_text(encoding="utf-8")
        self.assertIn('id="desk-data"', page)
        self.assertIn('"focus":"world"', page)

    def test_the_dashboard_opens_the_map(self):
        html = dashboard.render(self.state)
        card = html.find('id="world-map"')
        self.assertGreater(card, 0)
        self.assertLess(card, html.find('id="atlas"'))
        desk = html[html.find('id="storm-desk"'):]
        self.assertIn('href="map.html"', desk[:desk.find("</section>")])

    def test_brief_is_a_subset_of_the_full_report(self):
        brief = report.brief(self.state)
        full = report.render(self.state)
        self.assertLess(len(brief.splitlines()), len(full.splitlines()) / 3)
        self.assertIn("ALERTS", brief)
        self.assertNotIn("HAZARD OUTLOOK", brief)

    def test_the_report_and_the_dashboard_quote_the_same_thermocline_tilt(self):
        """Two panels and the report say "tilt"; a reader comparing them is
        checking the instrument, not the ocean, so they have to agree."""
        text = report.render(self.state, sections=("spatial",))
        html = dashboard.render(self.state)
        spoken = re.search(r"West-minus-east tilt is (-?\d+) m", text)
        written = re.search(r"a tilt of <strong>(-?\d+) m</strong>", html)
        self.assertIsNotNone(spoken, "the report stopped quoting the tilt")
        self.assertIsNotNone(written, "the section card stopped quoting the tilt")
        self.assertEqual(spoken.group(1), written.group(1))

    def test_dashboard_is_self_contained(self):
        html = dashboard.render(self.state)
        self.assertIn("<!DOCTYPE html>", html)
        self.assertNotIn("<script src", html)
        self.assertNotIn("<link rel=\"stylesheet\"", html)
        body = html.split("<footer>")[0].replace("http://www.w3.org", "")
        self.assertNotIn("http://", body)

    def test_every_chart_ships_a_table_view(self):
        html = dashboard.render(self.state)
        self.assertGreaterEqual(html.count("Table view"), 8)
        # A legend for every multi-series chart, so identity is never colour alone.
        self.assertGreaterEqual(html.count('class="legend"'), 5)

    def test_alert_severity_reaches_the_markup(self):
        html = dashboard.render(self.state)
        for alert in self.state.alert_set.alerts:
            status = panels._ALERT_STATUS[alert.level]
            self.assertIn(f'data-status="{status}"', html)

    def test_payload_is_json_serialisable_and_keyed_as_documented(self):
        payload = dashboard.payload(self.state)
        restored = json.loads(json.dumps(payload))
        self.assertEqual(restored["schema"], 9)
        for key in ("index", "oni", "power_index", "subsurface", "atmosphere", "forecast",
                    "skill", "alerts", "impacts", "feeds", "footprints",
                    "cyclones", "stormfury", "atlas", "outlook", "storm_desk"):
            self.assertIn(key, restored)
        self.assertEqual(restored["storm_desk"]["page"], "storms.html")
        self.assertIsInstance(restored["outlook"], list)

    def test_the_storm_desk_card_sits_with_the_storm_cards(self):
        html = dashboard.render(self.state)
        desk = html.find('id="storm-desk"')
        self.assertGreater(desk, 0)
        self.assertGreater(desk, html.find('id="globe"'))
        season = html.find('id="cyclone-season"')
        if season >= 0:
            self.assertLess(desk, season)

    def test_forecast_band_brackets_its_own_mean(self):
        for projection in self.state.forecast.projections:
            self.assertLessEqual(projection.low, projection.mean)
            self.assertLessEqual(projection.mean, projection.high)

    def test_the_spatial_tier_survived_the_run(self):
        spatial = self.state.spatial
        self.assertTrue(spatial.available)
        self.assertIsNotNone(spatial.sst_map)
        self.assertEqual(set(spatial.box_means),
                         {"nino4", "nino34", "nino3", "nino12"})
        self.assertIsNotNone(spatial.warm_pool)
        self.assertTrue(spatial.profiles)

    def test_map_derived_box_means_agree_with_the_published_index(self):
        """Different method, same ocean: a wide divergence means a broken grid."""
        published = self.state.assessment.latest_week
        if published is None:
            self.skipTest("no weekly index in the cache")
        self.assertAlmostEqual(self.state.spatial.box_means["nino34"],
                               published.nino34_anom, delta=1.0)

    def test_every_spatial_panel_reaches_the_page(self):
        html = dashboard.render(self.state)
        for heading in ("The planet, and what this event does to it",
                        "Where the anomaly actually is",
                        "The thermocline, in three dimensions",
                        "The thermocline in cross-section",
                        "How the anomaly moved",
                        "Sea level, which is heat content you can see from orbit",
                        "The same day, worldwide",
                        "Six years of the oscillator, unrolled"):
            self.assertIn(heading, html, f"{heading} is missing from the dashboard")

    def test_scenes_ship_both_a_picture_and_the_data_to_redraw_it(self):
        html = dashboard.render(self.state)
        self.assertEqual(html.count('class="scene"'), 2)
        self.assertEqual(html.count("data-scene="), 2)
        self.assertIn("function fitView", html)

    def test_the_globe_ships_with_its_geography_and_its_script(self):
        """A live run has to produce a globe that is actually operable."""
        html = dashboard.render(self.state)
        self.assertEqual(html.count('class="globe"'), 1)
        raw = html.split("data-globe='", 1)[1].split("'>", 1)[0]
        payload = json.loads(unescape(raw))
        self.assertEqual(len(payload["links"]), len(impacts.CATALOGUE))
        self.assertEqual(len(payload["grid"]["data"]),
                         payload["grid"]["rows"] * payload["grid"]["cols"])
        self.assertIn("var GLOBE_COAST=", html)
        self.assertIn("function unproject", html)

    def test_the_globe_scores_the_catalogue_at_today_as_well_as_at_the_peak(self):
        """The report only ever quotes the peak; the globe has to do both."""
        html = dashboard.render(self.state)
        raw = html.split("data-globe='", 1)[1].split("'>", 1)[0]
        links = json.loads(unescape(raw))["links"]
        self.assertTrue(all(link["now"]["likelihood"] for link in links))
        self.assertTrue(all(link["peak"]["likelihood"] for link in links))
        self.assertEqual(links[0]["peak_label"], self.state.forecast.peak.label)

    def test_the_footprints_reach_the_json_payload(self):
        data = dashboard.payload(self.state)
        self.assertEqual(len(data["footprints"]), len(geo.FOOTPRINTS))
        regions = {f["region"] for f in data["footprints"]}
        self.assertEqual(regions, {link.region for link in impacts.CATALOGUE})

    def test_every_field_ships_a_labelled_colour_bar(self):
        html = dashboard.render(self.state)
        self.assertGreaterEqual(html.count('class="rampstrip"'), 7)
        self.assertGreaterEqual(html.count('class="ramptick"'), 14)

    def test_the_spatial_payload_is_documented_and_serialisable(self):
        block = json.loads(json.dumps(dashboard.payload(self.state)))["spatial"]
        for key in ("fields", "box_means_from_map", "warm_pool_east_edge",
                    "equatorial_isotherm_20c", "thermocline_mesh", "notes"):
            self.assertIn(key, block)
        self.assertIn("sst_map", block["fields"])
        for item in block["fields"].values():
            self.assertIn("as_of", item)
            self.assertIn("coverage", item)
            self.assertLessEqual(item["coverage"], 1.0)

    def test_the_ascii_spatial_section_draws_a_map(self):
        text = report.render(self.state, sections=("spatial",))
        self.assertIn("WHERE THE EVENT IS", text)
        self.assertIn("28 degC warm pool", text)
        self.assertIn("20 degC isotherm", text)
        self.assertIn("key  ", text)

    def test_the_cyclone_tier_survived_the_run(self):
        state = self.state.cyclones
        self.assertTrue(state.available)
        self.assertEqual(set(state.basins), {"AL", "EP"})
        for season in state.basins.values():
            self.assertGreaterEqual(season.ace, 0.0)
            self.assertIsNotNone(season.normal_ace)
            # Date-matched, so it has to be the smaller of the two.
            self.assertLessEqual(season.normal_ace, season.full_normal_ace)

    def test_the_hurdat_parse_reproduces_the_published_normals(self):
        """NHC publishes the 1991-2020 Atlantic normal: 122.9 ACE, 14.4 named
        storms, 7.2 hurricanes, 3.2 major. A parser that disagrees with that
        is wrong about every ratio in the section."""
        normal = self.state.cyclones.basins["AL"].normal
        if not normal:
            self.skipTest("no HURDAT2 in the cache")
        self.assertAlmostEqual(normal["ace"], 122.9, delta=3.0)
        self.assertAlmostEqual(normal["named"], 14.4, delta=0.5)
        self.assertAlmostEqual(normal["hurricanes"], 7.2, delta=0.5)
        self.assertAlmostEqual(normal["major"], 3.2, delta=0.5)

    def test_the_report_and_the_dashboard_quote_the_same_season(self):
        """Two panels saying different things about the same basin is a
        reader checking the instrument instead of the ocean."""
        text = report.render(self.state, sections=("cyclones",))
        html = dashboard.render(self.state)
        data = json.loads(json.dumps(dashboard.payload(self.state)))
        for basin, season in self.state.cyclones.basins.items():
            quoted = data["cyclones"]["seasons"][basin]
            self.assertAlmostEqual(quoted["ace"], season.ace, places=1)
            self.assertIn(f"{season.ace:.0f}", text)
            self.assertIn(escape(season.name), html)

    def test_the_report_says_what_its_track_spread_measures(self):
        spread = [storm for storm in self.state.cyclones.active
                  if storm.spread_km is not None]
        if not spread:
            self.skipTest("no storm with guidance in the cache")
        text = " ".join(report.render(self.state, sections=("cyclones",)).split())
        for storm in spread:
            with self.subTest(storm=storm.title):
                self.assertIn(
                    f"sit on average {storm.spread_km:.0f} km from their mean "
                    f"position at +{storm.spread_tau} h", text)

    def test_no_two_labels_on_the_track_map_overlap(self):
        # On 24 September Manzanillo, Lazaro Cardenas, Zihuatanejo and Socorro
        # Island were all threatened and all written over one another beside
        # Polo's name, and Hilo, Kona and Maui made a second pile by Nolo.
        live = self.state.cyclones.active
        if not live:
            self.skipTest("no active storms in the cache")
        drawn = storms.track_map(live)
        boxes = _label_boxes(drawn)
        self.assertGreater(len(boxes), len(live))
        self.assertIsNone(_first_overlap(boxes))

    def test_place_names_sit_on_top_of_the_tracks(self):
        # With the names clear of one another, Guaymas, La Paz, Los Cabos and
        # Kona still went under Polo's and Nolo's forecast markers: the names
        # were drawn first and the storms painted over them.
        live = self.state.cyclones.active
        if not live:
            self.skipTest("no active storms in the cache")
        drawn = storms.track_map(live)
        names = list(re.finditer(r'<text[^>]*class="([^"]*placename[^"]*)"',
                                 drawn))
        self.assertTrue(names)
        last_mark = max(m.start() for m in re.finditer(
            r'<(?:path|circle)(?![^>]*class="hit")', drawn))
        self.assertGreater(min(m.start() for m in names), last_mark)
        for m in names:
            self.assertIn("halo", m.group(1).split())
        css = dashboard.render(self.state)
        self.assertRegex(css, r"\.halo \{[^}]*paint-order: stroke")

    def test_every_map_is_drawn_at_its_true_shape(self):
        # A degree of latitude and a degree of longitude get the same length
        # on the page. Each map fitted its extent to a fixed frame instead:
        # the cyclone map came out 2.17 times too tall for its width, the
        # tropical Pacific 1.35 and sea level 1.20, which turns a storm going
        # west-north-west into one going north-west and a Kelvin wave's
        # equatorial ridge into a bulge. Measured off the axis labels the
        # page prints, so it holds whatever the maps are made of.
        html = dashboard.render(self.state)
        label = re.compile(r'<text[^>]*\bx="([-\d.]+)" y="([-\d.]+)"[^>]*>'
                           r'(\d+)(?:&#176;|°)?([NSEW]?)</text>|'
                           r'<text[^>]*\bx="([-\d.]+)" y="([-\d.]+)"[^>]*>EQ</text>')
        measured = 0
        for svg in re.findall(r"<svg[^>]*role=\"img\".*?</svg>", html, re.S):
            lons, lats = [], []
            for m in label.finditer(svg):
                if m.group(5) is not None:
                    lats.append((0.0, float(m.group(6))))
                    continue
                x, y, value, hemi = (float(m.group(1)), float(m.group(2)),
                                     float(m.group(3)), m.group(4))
                if hemi in ("N", "S"):
                    lats.append((value if hemi == "N" else -value, y))
                elif hemi in ("E", "W") or value in (0.0, 180.0):
                    lons.append((value if hemi != "W" else 360.0 - value, x))
            if len(lons) < 2 or len(lats) < 2:
                continue
            lons.sort(key=lambda pair: pair[1])
            unwrapped = [lons[0][0]]
            for value, _ in lons[1:]:
                while value <= unwrapped[-1]:
                    value += 360.0
                unwrapped.append(value)
            per_lon = (lons[-1][1] - lons[0][1]) / (unwrapped[-1] - unwrapped[0])
            lats.sort(key=lambda pair: pair[1])
            per_lat = (lats[-1][1] - lats[0][1]) / (lats[0][0] - lats[-1][0])
            title = re.search(r'aria-label="([^"]*)"', svg).group(1)
            if "three dimensional" in title.lower():
                continue                        # an oblique view, not a plan
            with self.subTest(map=title):
                self.assertAlmostEqual(per_lat / per_lon, 1.0, delta=0.03)
            measured += 1
        self.assertGreaterEqual(measured, 3)

    def test_the_field_cells_tile_without_seams(self):
        # Each cell's top and height were rounded to a tenth separately, so a
        # row could end a tenth of a unit above the next one's top, and the
        # page showed through: dark streaks right across the SST map at
        # 8N, 12N, 17N and 23N.
        html = dashboard.render(self.state)
        for title in ("Tropical Pacific sea surface temperature anomaly map",
                      "Sea surface height anomaly map",
                      "Global sea surface temperature anomaly map"):
            found = re.search(r'<svg[^>]*aria-label="' + re.escape(title)
                              + r'".*?</svg>', html, re.S)
            if found is None:
                continue
            runs = [tuple(map(float, run)) for run in re.findall(
                r"M([-\d.]+) ([-\d.]+)h([-\d.]+)v([-\d.]+)h-[-\d.]+z",
                found.group(0))]
            self.assertTrue(runs)
            rows = sorted({(top, top + height) for _, top, _, height in runs})
            with self.subTest(map=title, axis="rows"):
                for (_, bottom), (top, _) in zip(rows, rows[1:]):
                    self.assertLessEqual(top, bottom + 1e-9)
            by_row: dict = {}
            for left, top, width, _ in runs:
                by_row.setdefault(top, []).append((left, left + width))
            with self.subTest(map=title, axis="runs"):
                for spans in by_row.values():
                    spans.sort()
                    for (_, right), (left, _) in zip(spans, spans[1:]):
                        # A rounding seam is a tenth wide; a real gap - a
                        # land cell, 0.57 wide on the quarter-degree global
                        # grid, less the overlap - is three tenths or more.
                        if left - right < 0.15:
                            self.assertLessEqual(left, right + 1e-9)

    def test_no_card_is_only_a_caption_and_a_folded_table(self):
        # A table behind a disclosure is the twin of a chart. "Momentum and
        # coupling" had no chart, so the card showed its heading, a sentence,
        # and a closed "Table view" - its numbers one click away and the card
        # apparently empty.
        html = dashboard.render(self.state)
        for card in re.findall(r'<section class="card".*?</section>', html, re.S):
            title = re.search(r"<h2>(.*?)</h2>", card, re.S).group(1)
            shown = re.sub(r'<details class="tableview">.*?</details>', "",
                           card, flags=re.S)
            shown = re.sub(r"<h2>.*?</h2>|<p[ >].*?</p>", "", shown, flags=re.S)
            shown = re.sub(r"</?section[^>]*>", "", shown)
            with self.subTest(card=title):
                self.assertTrue(shown.strip(), "nothing shown but a folded table")

    def test_no_year_on_the_recharge_loop_is_written_across_its_trail(self):
        # Each January label went up and to the right of its dot whatever the
        # loop was doing there, and on 24 September 2026 all four - 2023 to
        # 2026 - had the trail running through their digits.
        html = panels.chart_phase(self.state)
        if not html:
            self.skipTest("no subsurface trajectory in this run")
        trail = [tuple(float(v) for v in m) for m in re.findall(
            r'<line x1="([-\d.]+)" y1="([-\d.]+)" x2="([-\d.]+)" '
            r'y2="([-\d.]+)" stroke="var\(--s1\)"', html)]
        years = re.findall(
            r'<text x="([-\d.]+)" y="([-\d.]+)"(?: text-anchor="(\w+)")? '
            r'class="tiny[^"]*">(\d{4})</text>', html)
        self.assertTrue(trail)
        self.assertTrue(years)

        def crosses(box, segment):
            x1, y1, x2, y2 = segment
            steps = 50
            return any(box[0] <= x1 + (x2 - x1) * i / steps <= box[2]
                       and box[1] <= y1 + (y2 - y1) * i / steps <= box[3]
                       for i in range(steps + 1))

        for x, y, anchor, year in years:
            x, y = float(x), float(y)
            width = 0.6 * 10 * len(year)       # .tiny is 10px
            left = {"middle": x - width / 2, "end": x - width}.get(anchor, x)
            box = (left, y - 8, left + width, y + 2.5)
            with self.subTest(year=year):
                self.assertFalse(any(crosses(box, seg) for seg in trail),
                                 f"{year} at {box} sits on the trail")

    def test_stormfury_shows_the_tables_that_are_its_only_evidence(self):
        # "Would it even have been allowed to fly?" was a heading, a sentence
        # and a closed disclosure - the answer one click away, as were the
        # angular-momentum arithmetic and the record of the seeded storms. A
        # folded table is the twin of a chart; with no chart it is the
        # evidence, and it shows.
        html = dashboard.render(self.state)
        card = re.search(r'<section class="card" id="stormfury">.*?</section>',
                         html, re.S)
        if not card:
            self.skipTest("no STORMFURY card in this run")
        for part in re.split(r"(?=<h[23][ >])", card.group(0)):
            heading = re.match(r"<h[23][^>]*>(.*?)</h[23]>", part, re.S)
            for folded in re.findall(r'<details class="tableview"><summary>'
                                     r'Table view &mdash; (.*?)</summary>', part):
                with self.subTest(heading=heading.group(1) if heading else "-",
                                  table=folded):
                    self.assertIn("<svg", part, "folded with no chart to twin")

    def test_the_provenance_card_says_what_came_from_the_cache(self):
        # "Every number on this page is pulled directly from these feeds at
        # run time" - above a list in which every feed said "cached".
        html = dashboard.render(self.state)
        card = re.search(r"<h2>Data provenance</h2>.*?</section>", html,
                         re.S).group(0)
        self.assertNotIn("at run time", card)
        cached = card.count('class="pill cache"')
        live = card.count('class="pill live"')
        if cached:
            self.assertIn(f"{cached} read from the local cache", card)
        if live:
            self.assertIn(f"{live} fetched live this run", card)

    def test_the_feed_registry_knows_which_index_is_official(self):
        # The ONI entry still called itself "the official index NOAA uses to
        # declare El Nino / La Nina episodes" seven months after RONI took over.
        by_key = {source.key: source for source in sources.SOURCES}
        self.assertIn("official", by_key["roni"].name.lower())
        self.assertIn("legacy", by_key["oni"].name.lower())
        self.assertNotIn("Official index", by_key["oni"].note)
        self.assertIn("roni", sources.CRITICAL_KEYS)
        self.assertNotIn("oni", sources.CRITICAL_KEYS)

    def test_the_forecast_analogs_are_read_from_the_same_season(self):
        # Each member continues the same calendar season of its own year,
        # shifted by today's lead over it then - not the stage after onset.
        series = self.state.assessment.index_series
        latest = series[-1]
        index = {(v.season, v.year): v.value for v in series}
        members = self.state.forecast.analog_members
        self.assertTrue(members)
        for name, track in members.items():
            first = int(name[:4])
            year = first + 1 if latest.season in ("DJF", "JFM", "FMA", "MAM") else first
            after = forecast._season_step(latest.season, year, 1)
            expected = index[after] + latest.value - index[(latest.season, year)]
            with self.subTest(member=name):
                self.assertAlmostEqual(track[0], expected)

    def test_the_page_writes_degrees_with_the_sign(self):
        # The alert and episode text is written once in ASCII for the report;
        # thirteen places on the page printed its "degC" - an alert title
        # reading "+1.0 degC" above a tile reading "+1.36 °C". Scripts count:
        # the atlas's writes its imagery scale into the credit line.
        for html in (dashboard.render(self.state), atlasview.page(self.state)):
            self.assertNotIn("degC", html)

    def test_the_page_writes_celsius_with_the_sign(self):
        # "The 20 C isotherm", "28 C edge 109W", "+1.39 degrees C" - beside
        # tiles and axes in °C, and a bare "C" after a number is a coulomb.
        # Path data is left out: C is also the curve command there.
        for html in (dashboard.render(self.state), atlasview.page(self.state)):
            visible = re.sub(r"<script.*?</script>|<style.*?</style>"
                             r'|\s(?:d|points|transform|viewBox)="[^"]*"', "", html, flags=re.S)
            for spelling in (r"\d C\b", r"degrees C\b"):
                with self.subTest(spelling=spelling):
                    found = re.search(spelling, visible)
                    self.assertIsNone(found, found and visible[found.start() - 60:found.end()])

    def test_a_zero_tick_has_no_sign(self):
        # "+0.0" at the zero line of the forecast axis, "+0σ" under the
        # Walker bars: a signed zero reads as a direction it does not have.
        html = dashboard.render(self.state)
        found = re.search('class="tick[^"]*"[^>]*>[+\\-−]0(?:\\.0+)?σ?<', html)
        self.assertIsNone(found, found and html[found.start():found.end()])

    def test_the_page_writes_units_as_its_charts_do(self):
        # The recharge charts label their axes in σ and 10¹⁴ m³; the tables
        # behind them said "sigma" and "10^14 m3", as did the alerts written
        # once for the report, and a bar's tooltip read "+0.52 sigma" beside
        # the bar's own "+0.52σ". The entity &sigma; is the sign, not the word.
        html = dashboard.render(self.state)
        visible = re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)
        for ascii_unit in (r"(?<!&)sigma", r"10\^14", r" m3\b"):
            with self.subTest(unit=ascii_unit):
                found = re.search(ascii_unit, visible)
                self.assertIsNone(found, found and visible[found.start() - 80:found.end()])

    def test_the_forecast_shows_the_weights_it_combined_with(self):
        # "Combined with weights set by how well each verified historically",
        # and the weights were in neither the report nor the page.
        weights = self.state.forecast.weights
        self.assertEqual(weights, self.state.skill.weights)
        shown = ", ".join(f"{name} {weights[name]:.0%}"
                          for name in ("analog", "recharge", "persistence"))
        text = " ".join(report.render(self.state, sections=("forecast",)).split())
        self.assertIn(shown, text)
        self.assertIn(shown, " ".join(dashboard.render(self.state).split()))
        payload = dashboard.payload(self.state)
        self.assertEqual(payload["forecast"]["weights"], weights)
        self.assertEqual(payload["skill"]["useful_horizon_is_lower_bound"],
                         self.state.skill.horizon_is_lower_bound)

    def test_the_peak_tile_says_what_its_range_is(self):
        # "OND 2026 - +0.71 to +2.65": a range with no coverage is a range the
        # reader has to guess the meaning of.
        html = dashboard.render(self.state)
        tile = re.search(r"Projected \w+ peak</div>.*?</div></div>", html, re.S)
        if not tile:
            self.skipTest("no forecast peak in this run")
        self.assertIn("80% range", tile.group(0))

    def test_the_forecast_legend_tells_the_band_from_the_mean(self):
        # Both keys were a solid orange square: the band is the same hue at a
        # sixth of the strength, and its key has to look like it.
        html = panels.chart_forecast(self.state)
        if not html:
            self.skipTest("no forecast in this run")
        keys = {name: colour for colour, name in re.findall(
            r'<span class="swatch" style="background:([^"]+)"></span>([^<]+)</span>',
            html)}
        self.assertNotEqual(keys["80% range"], keys["Ensemble mean"])
        band = re.search(r'fill="var\(--s2\)" opacity="([\d.]+)"', html)
        share = f"{float(band.group(1)) * 100:.0f}%"
        self.assertIn(share, keys["80% range"])

    def test_the_skill_panel_names_its_seasons_by_what_was_measured(self):
        # The orange bars are the target seasons within 0.05 of the weakest;
        # every other bar was labelled "clear of boreal spring", which put AMJ
        # - six months out from November, verifying in spring itself - clear
        # of the spring it sits in, on the strength of a correlation 0.004
        # above the cut.
        html = panels.chart_skill(self.state)
        if not html:
            self.skipTest("no verification in this run")
        self.assertNotIn("Clear of boreal spring", html)
        self.assertIn("Other target seasons", html)
        self.assertIn("within 0.05 of the weakest", html)
        text = " ".join(report.render(self.state, sections=("skill",)).split())
        weakest = self.state.skill.barrier_seasons
        self.assertNotIn("must cross", text)
        self.assertIn("the weakest are " + ", ".join(weakest), text)

    def test_every_live_storm_reaches_the_report_the_page_and_the_globe(self):
        live = self.state.cyclones.active
        if not live:
            self.skipTest("no active storms in the cache")
        text = report.render(self.state, sections=("cyclones",))
        html = dashboard.render(self.state)
        payload = json.loads(json.dumps(dashboard.payload(self.state)))
        raw = html.split("data-globe=\'", 1)[1].split("\'>", 1)[0]
        on_globe = {s["id"] for s in json.loads(unescape(raw))["storms"]}
        quoted = {s["id"] for s in payload["cyclones"]["active"]}
        for storm in live:
            self.assertIn(storm.title.upper(), text.upper())
            self.assertIn(escape(storm.title), html)
            self.assertIn(storm.key, quoted)
            self.assertIn(storm.key, on_globe)

    def test_the_globe_and_the_track_map_give_a_storm_the_same_colour(self):
        live = self.state.cyclones.active
        if not live:
            self.skipTest("no active storms in the cache")
        html = dashboard.render(self.state)
        raw = html.split("data-globe=\'", 1)[1].split("\'>", 1)[0]
        on_globe = json.loads(unescape(raw))["storms"]
        self.assertEqual([s["id"] for s in on_globe],
                         [s.key for s in live])
        for index, entry in enumerate(on_globe):
            self.assertEqual(globe.hue_for(entry["hue"]),
                             storms.STORM_HUES[index]
                             if index < len(storms.STORM_HUES)
                             else storms.NEUTRAL)

    def test_a_storm_alert_names_a_storm_the_section_describes(self):
        """The two are built from the same storms, or the page warns about
        one hurricane while the section discusses another."""
        named = {s.title for s in self.state.cyclones.active}
        fired = [a for a in self.state.alert_set.alerts
                 if a.code.startswith("tc_")]
        for alert in fired:
            # Season totals and formation areas are not about a storm.
            if alert.code.startswith(("tc_season_", "tc_formation_")):
                continue
            self.assertTrue(
                any(title in alert.title or title in alert.detail
                    for title in named),
                f"alert names no live storm: {alert.title}")

    def test_the_stormfury_tier_survived_the_run(self):
        fury = self.state.stormfury
        self.assertTrue(fury.available)
        self.assertTrue(fury.verdict)
        self.assertTrue(fury.reasons[0].startswith("TRIGGER:"))
        # Not one storm, in any season, has ever passed the trigger rule.
        self.assertEqual(fury.eligible, [])
        for found in fury.assessments:
            self.assertIn("Supercooled water to seed", found.blocked_by)

    def test_the_report_the_page_and_the_payload_quote_one_verdict(self):
        """Three renderers over one calculation. If they disagree the reader
        is reading the instrument instead of the hurricane."""
        text = report.render(self.state, sections=("stormfury",))
        html = dashboard.render(self.state)
        data = json.loads(json.dumps(dashboard.payload(self.state)))["stormfury"]
        self.assertIn("PROJECT STORMFURY", text)
        self.assertIn("PROJECT STORMFURY", html.upper())
        self.assertEqual(data["verdict"], self.state.stormfury.verdict)
        self.assertIn(escape(self.state.stormfury.verdict), html)
        self.assertEqual(len(data["assessments"]),
                         len(self.state.stormfury.assessments))
        self.assertEqual(data["programme"]["storms_seeded"],
                         len(data["seeded_storms"]))

    def test_the_momentum_prediction_is_scored_not_just_asserted(self):
        """The claim that the hypothesis overstates the weakening has to come
        from this season's decks, not from the module's prose."""
        skill = self.state.stormfury.skill
        if not skill.get("count"):
            self.skipTest("no natural eyewall expansions in the cache")
        self.assertGreater(skill["mean_predicted_drop"],
                           skill["mean_observed_drop"])
        self.assertEqual(skill["count"], len(self.state.stormfury.moves))
        self.assertLessEqual(skill["held_or_strengthened"], skill["count"])

    def test_skill_degrades_with_lead(self):
        leads = self.state.skill.leads
        self.assertLess(leads[0].rmse, leads[-1].rmse)

    # -- the official index, all the way to the page -----------------------
    def test_the_report_states_the_official_index(self):
        a = self.state.assessment
        text = report.render(self.state, sections=("state", "intensity"))
        state_line = next(line for line in text.splitlines()
                          if line.strip().startswith("STATE"))
        self.assertIn(a.index_tier, state_line)
        self.assertIn(a.index_name, state_line)
        if a.oni_tier != a.index_tier:
            self.assertNotIn(a.oni_tier, state_line)
        self.assertIn("legacy", text.lower())

    def test_the_dashboard_hero_is_the_official_index(self):
        a = self.state.assessment
        html = dashboard.render(self.state)
        hero = html.split('class="hero-label"', 1)[1].split("</div>", 3)
        hero = "".join(hero[:3])
        self.assertIn("Relative Oceanic Nino Index", hero)
        self.assertIn(f"{a.index_latest.value:+.2f}", hero)

    def test_the_report_names_the_most_recent_westerly_month(self):
        bursts = self.state.atmosphere.bursts
        if not bursts:
            self.skipTest("no westerly months in the cached record")
        newest = max(bursts, key=lambda burst: burst.when)
        text = " ".join(report.render(self.state, sections=("atmosphere",)).split())
        self.assertIn(f"Most recent {newest.label},", text)

    def test_no_caption_prints_an_entity_as_text(self):
        html = dashboard.render(self.state)
        captions = re.findall(r'<p class="caption">(.*?)</p>', html, re.S)
        self.assertTrue(captions)
        for caption in captions:
            self.assertNotIn("&amp;middot;", caption)

    def test_the_storm_forecast_is_stamped_with_valid_times(self):
        html = dashboard.render(self.state)
        live = [s for s in self.state.cyclones.active if s.forecast]
        if not live:
            self.skipTest("no live storm with a forecast in the cache")
        fix = live[0].forecast[0]
        self.assertIn(f"+{fix.tau} h ({alerts._valid(fix)})", html)

    def test_the_atlantic_normals_are_noaas(self):
        # NOAA's 1991-2020 Atlantic averages: 14.4 named storms, 7.2
        # hurricanes, 3.2 major hurricanes.
        normal = self.state.cyclones.basins["AL"].normal
        self.assertAlmostEqual(normal["named"], 14.4, places=1)
        self.assertAlmostEqual(normal["hurricanes"], 7.2, places=1)
        self.assertAlmostEqual(normal["major"], 3.2, places=1)

    def test_the_hurricane_composite_is_keyed_on_the_official_index(self):
        # ASO 1994 is RONI +0.79 but ONI +0.47; ASO 2018 is ONI +0.52 but
        # RONI +0.35. Keyed on RONI, 1994 is an El Nino season and 2018 is not.
        years = self.state.cyclones.elnino_years
        self.assertIn(1994, years)
        self.assertNotIn(2018, years)

    def test_the_hazard_outlook_is_keyed_to_the_official_index(self):
        a = self.state.assessment
        expected = max(a.index_latest.value, self.state.forecast.peak.mean)
        self.assertAlmostEqual(self.state.impacts.peak_index, expected)
        self.assertEqual(self.state.impacts.index_name, a.index_name)

    def test_the_forecast_chart_plots_the_official_index(self):
        html = dashboard.render(self.state)
        self.assertIn(f"Observed {self.state.assessment.index_name}", html)

    def test_the_globe_scores_today_on_the_official_index(self):
        a = self.state.assessment
        html = dashboard.render(self.state)
        raw = html.split("data-globe='", 1)[1].split("'>", 1)[0]
        payload = json.loads(unescape(raw))
        self.assertEqual(payload["index_name"], a.index_name)
        self.assertAlmostEqual(payload["index"], round(a.index_latest.value, 2))

    def test_the_forecast_is_of_the_official_index(self):
        self.assertEqual(self.state.forecast.index_name, self.state.assessment.index_name)

    def test_the_forecast_report_names_the_index_it_forecasts(self):
        name = self.state.assessment.index_name
        text = report.render(self.state, sections=("forecast", "skill"))
        self.assertIn(f"P(peak {name} >= 2.0)", text)
        if name != "ONI":
            self.assertNotIn("peak ONI", text)
        self.assertIn("the year after", text)
        self.assertNotIn("the verification year held", text)

    def test_the_regions_are_read_on_the_relative_anomalies(self):
        scale = self.state.assessment.scale
        self.assertEqual(scale.basis, "relative")
        text = report.render(self.state, sections=("intensity",))
        nino34 = next(r for r in scale.regions if r.key == "nino34")
        line = next(l for l in text.splitlines() if l.strip().startswith("Nino-3.4 ("))
        self.assertIn(f"{nino34.anomaly:+.1f}", line)
        self.assertIn(f"{nino34.traditional:+.1f}", line)

    def test_the_payload_names_the_official_index(self):
        a = self.state.assessment
        data = json.loads(json.dumps(dashboard.payload(self.state)))
        self.assertEqual(data["index"]["name"], a.index_name)
        self.assertAlmostEqual(data["index"]["value"], a.index_latest.value)
        self.assertEqual(data["index"]["tier"], a.index_tier)


def _run_without(key: str):
    """One offline run in which one feed failed and left no cache behind."""
    real = sources.fetch_all

    def fetch_all(*args, **kwargs):
        fetched = real(*args, **kwargs)
        lost = fetched[key]
        fetched[key] = sources.Fetched(lost.source, "", "", from_cache=False,
                                       sha256="", error="HTTP Error 404")
        return fetched

    tmp = tempfile.TemporaryDirectory()
    with mock.patch.object(sources, "fetch_all", fetch_all):
        state = pipeline.run(CACHE, Path(tmp.name) / "one.db", offline=True,
                             leads=9)
    return tmp, state


@unittest.skipUnless((CACHE / "oni.cache").exists(),
                     "no cached feeds; run `python track.py` once first")
class TestRunsOnOneIndex(unittest.TestCase):
    """RONI is the official index; ONI is the legacy one beside it.

    The run refused to start without ONI - "the tracker cannot classify the
    state of the system without it" - although it classifies on RONI, so a
    404 on the legacy file stopped the official reading from being made. And
    a run with no RONI fell back to ONI and exited clean, as if nothing were
    missing.
    """

    @classmethod
    def setUpClass(cls):
        cls.tmp_oni, cls.no_oni = _run_without("oni")
        cls.tmp_roni, cls.no_roni = _run_without("roni")

    @classmethod
    def tearDownClass(cls):
        cls.tmp_oni.cleanup()
        cls.tmp_roni.cleanup()

    def test_a_missing_legacy_index_does_not_stop_the_official_one(self):
        a = self.no_oni.assessment
        self.assertEqual(a.index_name, "RONI")
        self.assertIsNone(a.oni_latest)
        self.assertNotIn("legacy ONI", a.headline)
        self.assertTrue(self.no_oni.degraded)
        self.assertTrue(any("ONI" in w and "legacy" in w
                            for w in self.no_oni.warnings))

    def test_every_renderer_copes_without_the_legacy_index(self):
        html = dashboard.render(self.no_oni)
        text = report.render(self.no_oni)
        self.assertIn("RONI", html)
        self.assertIn("Legacy ONI", html)
        self.assertIn("did not arrive", " ".join(text.split()))
        json.dumps(dashboard.payload(self.no_oni))

    def test_running_on_the_legacy_index_is_a_degraded_run(self):
        a = self.no_roni.assessment
        self.assertEqual(a.index_name, "ONI")
        self.assertTrue(self.no_roni.degraded)
        self.assertTrue(any("RONI" in w for w in self.no_roni.warnings))


class TestCompositeGrids(unittest.TestCase):
    """The vendored composites are data in a source file, which means nothing
    upstream will ever tell us they went wrong. These are the tripwires."""

    SHAPES = {"PRECIP": (72, 144), "AIR": (90, 180)}

    def test_axes_are_regular_monotone_and_the_size_the_grids_claim(self):
        for variable, (rows, cols) in self.SHAPES.items():
            lats = atlas._axis(f"{variable}_LATS")
            lons = atlas._axis(f"{variable}_LONS")
            self.assertEqual(len(lats), rows, variable)
            self.assertEqual(len(lons), cols, variable)
            for axis, name in ((lats, "lats"), (lons, "lons")):
                steps = {round(b - a, 6)
                         for a, b in zip(axis, axis[1:])}
                self.assertEqual(len(steps), 1,
                                 f"{variable} {name} is not a regular grid")
                self.assertNotEqual(steps.pop(), 0.0)

    def test_every_plane_decodes_to_the_shape_of_its_axes(self):
        for variable, (rows, cols) in self.SHAPES.items():
            for season in atlas.SEASONS:
                for kind in ("DIFF", "T", "BASE"):
                    plane = atlas._grid(variable, season, kind)
                    self.assertEqual(len(plane), rows,
                                     f"{variable} {season} {kind}")
                    for row in plane:
                        self.assertEqual(len(row), cols,
                                         f"{variable} {season} {kind}")

    def test_the_difference_and_its_statistic_are_missing_in_the_same_places(self):
        """A cell with a difference but no t would be drawn as certain."""
        for variable in self.SHAPES:
            for season in atlas.SEASONS:
                diff = atlas._grid(variable, season, "DIFF")
                stat = atlas._grid(variable, season, "T")
                for r, (drow, trow) in enumerate(zip(diff, stat)):
                    for c, (d, t) in enumerate(zip(drow, trow)):
                        self.assertEqual(d is None, t is None,
                                         f"{variable} {season} at {r},{c}")

    def test_the_air_baseline_is_celsius_and_not_kelvin(self):
        """GHCN-CAMS publishes Kelvin. A difference of Kelvin is a difference
        of Celsius, so this survived every check on DIFF and t; it showed up
        as an ordinary Jakarta December at 300 degrees."""
        for season in atlas.SEASONS:
            values = [v for row in atlas._grid("AIR", season, "BASE")
                      for v in row if v is not None]
            self.assertTrue(values)
            self.assertGreater(min(values), -80.0, season)
            self.assertLess(max(values), 60.0, season)
        jakarta = atlas.sample("AIR", "DJF", 106.85, -6.2)
        self.assertIsNotNone(jakarta.base)
        self.assertGreater(jakarta.base, 20.0)
        self.assertLess(jakarta.base, 35.0)

    def test_the_rainfall_baseline_is_a_rate_and_never_negative(self):
        for season in atlas.SEASONS:
            values = [v for row in atlas._grid("PRECIP", season, "BASE")
                      for v in row if v is not None]
            self.assertGreaterEqual(min(values), 0.0, season)
            self.assertLess(max(values), 40.0, season)

    def test_the_sample_metadata_describes_a_composite_that_could_exist(self):
        for meta in (composite.PRECIP_META, composite.AIR_META):
            for season in atlas.SEASONS:
                block = meta[season]
                self.assertGreater(block["warm_months"], 0, season)
                self.assertGreater(block["base_months"], block["warm_months"])
                events = block["warm_events"]
                self.assertEqual(events, sorted(set(events)), season)
                self.assertGreaterEqual(min(events), 1979)


class TestCompositeSample(unittest.TestCase):
    """The composite is past events on the official index, judged honestly."""

    # Two-sided 95% points of Student's t, copied from the printed table.
    T975 = {2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365,
            8: 2.306, 9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160,
            14: 2.145, 15: 2.131, 16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093,
            20: 2.086, 21: 2.080, 22: 2.074, 23: 2.069, 24: 2.064, 25: 2.060}

    def test_the_event_in_progress_is_not_composited(self):
        # "What past El Ninos did" cannot include this one: in September 2026
        # the JJA composite held June and July 2026, the event being tracked.
        if not (CACHE / "roni.cache").exists():
            self.skipTest("no cached feeds; run `python track.py` once first")
        roni = parsers.parse_roni((CACHE / "roni.cache").read_text(encoding="utf-8"))
        current = current_episode(roni, warm=True)
        if current is None:
            self.skipTest("no El Nino in progress in the cached index")
        running = set(range(current.onset.year, current.latest.year + 2))
        for meta in (composite.PRECIP_META, composite.AIR_META):
            for season in atlas.SEASONS:
                with self.subTest(season=season):
                    self.assertFalse(running & set(meta[season]["warm_events"]))

    def test_each_season_is_judged_at_its_own_critical_value(self):
        # Months inside one event are not independent draws - a wet January
        # and a wet February in 1998 are one El Nino - so the unit is the
        # event, and the critical value is Student's t at the smaller of the
        # two samples' degrees of freedom, which is conservative for Welch.
        for meta in (composite.PRECIP_META, composite.AIR_META):
            for season in atlas.SEASONS:
                with self.subTest(season=season):
                    block = meta[season]
                    df = min(len(block["warm_events"]) - 1, block["base_years"] - 1)
                    self.assertAlmostEqual(block["t_crit"], self.T975[df], places=3)

    def test_a_cell_is_significant_only_past_its_seasons_critical_value(self):
        self.assertFalse(atlas.Cell(value=1.0, base=3.0, t=2.1, crit=2.262).significant)
        self.assertTrue(atlas.Cell(value=1.0, base=3.0, t=-2.3, crit=2.262).significant)
        for season in atlas.SEASONS:
            with self.subTest(season=season):
                cell = atlas.sample("PRECIP", season, 106.85, -6.2)
                self.assertEqual(cell.crit, composite.PRECIP_META[season]["t_crit"])
                air = atlas.sample("AIR", season, 106.85, -6.2)
                self.assertEqual(air.crit, composite.AIR_META[season]["t_crit"])

    def test_the_surest_season_is_judged_against_its_own_bar(self):
        # Fortaleza in the rebuilt composite: t -1.86 against DJF's 2.31 is
        # 0.81 of the way to significance; -2.48 against JJA's 3.18 is 0.78.
        # Raw |t| picked June to August; the record is surer about DJF.
        def seasonal(season, t, crit):
            cell = atlas.Cell(value=-1.0, base=3.0, t=t, crit=crit)
            return atlas.Seasonal(season=season, precip=cell, air=cell)

        local = atlas.Local(
            lon=-38.5, lat=-3.7,
            seasons=(seasonal("DJF", -1.86, 2.306), seasonal("MAM", -1.04, 2.571),
                     seasonal("JJA", -2.48, 3.182), seasonal("SON", -1.63, 2.262)),
            places=(), footprints=(), links=(), coast_km=None,
        )
        self.assertEqual(local.strongest.season, "DJF")

    def test_the_cautionary_examples_are_this_composites_numbers(self):
        state = atlas.evaluate()
        report_text = " ".join(" ".join(
            report._section_atlas(SimpleNamespace(atlas=state))).split())
        card = " ".join(unescape(atlasview.card(SimpleNamespace(atlas=state))).split())
        for text in (report_text, card):
            self.assertNotIn("+111%", text)
            self.assertNotIn("ten events", text)
        named = dict(zip((name for name, _, _ in atlas.ANCHORS), state.anchors))
        best = named["Fortaleza"].strongest
        if best.precip.significant or best.precip.value >= 0:
            self.skipTest("Fortaleza is no longer the cautionary case")
        quoted = f"{best.precip.percent:+.0f}% of normal in {atlas.SEASON_LABEL[best.season]}"
        self.assertIn(quoted, report_text)
        self.assertIn(quoted, card)
        self.assertIn(f"{best.precip.crit:.2f}", report_text)

    def test_an_anchor_row_reads_every_column_in_its_own_season(self):
        # Jakarta's row is June to August. Its temperature column was the
        # December-to-February composite, printed beside JJA rainfall.
        state = atlas.evaluate()
        named = dict(zip((name for name, _, _ in atlas.ANCHORS), state.anchors))
        jakarta = named["Jakarta"]
        best = jakarta.strongest
        self.assertNotEqual(best.season, atlas.PEAK_SEASON)
        air = jakarta.at(best.season).air.value
        (row,) = [r for r in atlasview._anchor_rows(SimpleNamespace(atlas=state))
                  if r[0] == "Jakarta"]
        # The value, whatever its marking for significance.
        self.assertEqual(row[-1].strip("()"), f"{air:+.2f}")
        text = report._section_atlas(SimpleNamespace(atlas=state))
        (line,) = [l for l in anchor_table(text)[1]
                   if l.strip().startswith("Jakarta ")]
        self.assertTrue(line.rstrip().rstrip(")").endswith(f"{air:+.2f}"), line)
        self.assertIn(f"{best.precip.crit:.2f}", line)

    def test_the_anchor_table_keeps_its_columns_apart(self):
        # 'no clear signal' fills the verdict column to one space short, and
        # a bracketed temperature fills its own: the two ran together.
        text = report._section_atlas(SimpleNamespace(atlas=atlas.evaluate()))
        header, rows = anchor_table(text)
        self.assertTrue(rows)
        for line in rows:
            with self.subTest(line=line):
                self.assertEqual(len(line), len(header))
                verdict = line[:len(line) - 8].rstrip()
                self.assertTrue(verdict.endswith(("wetter", "drier", "signal")))
                self.assertGreaterEqual(len(line) - len(verdict)
                                        - len(line.split()[-1]), 2)

    def test_what_no_clear_signal_means_is_said_once_and_always(self):
        # The card said it as a caveat and again as the opening of the
        # Fortaleza lesson; the report said it only inside that lesson, so it
        # would vanish the day Fortaleza stopped being the example.
        state = atlas.evaluate()
        card = atlasview.card(SimpleNamespace(atlas=state))
        text = " ".join(report._section_atlas(SimpleNamespace(atlas=state)))
        self.assertEqual(card.count("not a gap"), 1)
        self.assertEqual(" ".join(text.split()).count("not a gap"), 1)
        for lesson in atlas.lessons(state):
            self.assertNotIn("not a gap", lesson)

    def test_the_atlas_card_shows_its_table_rather_than_folding_it(self):
        # Elsewhere a table is the twin of a chart and waits behind a
        # disclosure. This card has no chart: the table is what it shows, and
        # every caveat under it refers to its columns.
        from elnino.svg import table
        card = atlasview.card(SimpleNamespace(atlas=atlas.evaluate()))
        self.assertIn('<details class="tableview" open>', card)
        self.assertEqual(table("c", ["h"], [["v"]]).count(" open>"), 0)

    def test_a_temperature_inside_the_noise_is_marked_as_such(self):
        # The rainfall columns carry a verdict; the temperature column printed
        # a bare number, so Los Angeles in SON read -1.14 degC on a t of -1.84
        # against the 2.26 its season needs. Inside the noise, it is shown in
        # parentheses and the table says what they mean.
        state = atlas.evaluate()
        rows = atlasview._anchor_rows(SimpleNamespace(atlas=state))
        text = report._section_atlas(SimpleNamespace(atlas=state))
        for local, (name, _, _) in zip(state.anchors, atlas.ANCHORS):
            best = local.strongest
            if best is None or best.air.value is None:
                continue
            shown = (f"{best.air.value:+.2f}" if best.air.significant
                     else f"({best.air.value:+.2f})")
            with self.subTest(place=name):
                (row,) = [r for r in rows if r[0] == local.title.split(",")[0]]
                self.assertEqual(row[-1], shown)
                (line,) = [l for l in anchor_table(text)[1]
                           if l.strip().startswith(local.title.split(",")[0] + " ")]
                self.assertTrue(line.rstrip().endswith(shown), line)
        self.assertIn("in parentheses", " ".join(text))
        self.assertIn("in parentheses", atlasview.card(SimpleNamespace(atlas=state)))

    def test_the_tier_states_each_seasons_own_sample(self):
        state = atlas.evaluate()
        text = " ".join(state.reasons)
        lines = "\n".join(report._section_atlas(SimpleNamespace(atlas=state)))
        for season in atlas.SEASONS:
            with self.subTest(season=season):
                block = composite.PRECIP_META[season]
                phrase = (f"{season} {len(block['warm_events'])} events "
                          f"({block['warm_months']} months)")
                self.assertIn(phrase, text)
                self.assertIn(phrase, " ".join(lines.split()))
        self.assertNotIn("ONI +1.0", text)
        self.assertIn("RONI", text)


class TestCompositeBuilder(unittest.TestCase):
    """The vendoring tool's statistic, on a grid of one cell worked by hand."""

    @staticmethod
    def tool():
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "vendor_composite", ROOT / "tools" / "vendor_composite.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_events_not_months_are_the_sample(self):
        tool = self.tool()
        index, stack = {}, {}
        # Three El Ninos, each warm through June-August, with event means of
        # 5, 7 and 9; six neutral years with means 1, 2, 3, 1, 2, 3; two La
        # Nina years that belong to neither; and 2011, warm and still running
        # when the index ends, holding a value that would swamp the composite.
        warm = {2000: (4, 5, 6), 2003: (6, 7, 8), 2006: (8, 9, 10)}
        neutral = {2001: 1, 2002: 2, 2004: 3, 2005: 1, 2007: 2, 2008: 3}
        for year in range(2000, 2012):
            for month in (6, 7, 8):
                if year in warm:
                    index[(year, month)] = 1.5
                    value = warm[year][month - 6]
                elif year in neutral:
                    index[(year, month)] = 0.0
                    value = neutral[year]
                elif year == 2011:
                    index[(year, month)] = 1.2
                    value = 100.0
                else:
                    index[(year, month)] = -1.0
                    value = 50.0
                stack[(year, month)] = [[float(value)]]
        jja = tool.composite(stack, index, 1, 1)["JJA"]
        # Warm means 5, 7, 9: mean 7, variance 4. Neutral means: mean 2,
        # variance 4/5. Welch t = 5 / sqrt(4/3 + 0.8/6) = 4.1286, on at least
        # min(3, 6) - 1 = 2 degrees of freedom, where the 95% point is 4.303.
        self.assertAlmostEqual(jja["diff"][0][0], 5.0)
        self.assertAlmostEqual(jja["base"][0][0], 2.0)
        self.assertAlmostEqual(jja["t"][0][0], 5.0 / math.sqrt(4 / 3 + 0.8 / 6), places=4)
        self.assertEqual(jja["warm_events"], [2000, 2003, 2006])
        self.assertEqual((jja["warm_months"], jja["base_years"], jja["base_months"]),
                         (9, 6, 18))
        self.assertAlmostEqual(jja["t_crit"], 4.303)
        self.assertEqual(jja["in_progress"], [2011])

    def test_phase_reads_the_index_as_cpc_prints_it(self):
        # The tracker classifies on the displayed value, so the composite
        # does too: +0.95 prints as +1.0 and is an El Nino month at the +1.0
        # bar; +0.45 prints as +0.5, which is El Nino territory, not neutral.
        tool = self.tool()
        cases = {0.95: "warm", 0.94: "skip", 0.45: "skip", 0.44: "base",
                 -0.44: "base", -0.45: "skip", -1.2: "skip"}
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(tool.phase({(2000, 1): value}, 2000, 1), expected)

    def test_the_event_under_way_starts_where_the_index_prints_plus_half(self):
        # RONI AMJ 2026 was +0.49, printed +0.5: the run began in May.
        tool = self.tool()
        index = {(2026, 3): 0.10, (2026, 4): 0.30, (2026, 5): 0.49,
                 (2026, 6): 0.97, (2026, 7): 1.36}
        self.assertEqual(tool.ongoing(index), {(2026, 5), (2026, 6), (2026, 7)})

    def test_a_season_too_thin_to_test_says_so(self):
        tool = self.tool()
        index = {(2000, 7): 1.5, (2001, 7): 0.0}
        stack = {(2000, 7): [[1.0]], (2001, 7): [[0.0]]}
        jja = tool.composite(stack, index, 1, 1)["JJA"]
        self.assertIsNone(jja["t_crit"])
        self.assertIsNone(jja["t"][0][0])


class TestAtlasSampling(unittest.TestCase):

    def test_a_sample_reports_the_cell_that_contains_the_point(self):
        cell = atlas.sample("PRECIP", "DJF", 106.85, -6.2)
        self.assertLessEqual(cell.lon0, 106.85)
        self.assertGreaterEqual(cell.lon1, 106.85)
        self.assertLessEqual(cell.lat0, -6.2)
        self.assertGreaterEqual(cell.lat1, -6.2)

    def test_longitude_wraps_rather_than_falling_off_the_grid(self):
        """The grids are stored 0..360 and the page hands over -180..180."""
        west = atlas.sample("PRECIP", "DJF", -160.0, 0.0)
        same = atlas.sample("PRECIP", "DJF", 200.0, 0.0)
        self.assertEqual(west.value, same.value)
        self.assertEqual(west.t, same.t)

    def test_the_composite_reproduces_the_maritime_continent_drought(self):
        """If this fails the grids are not what they claim to be."""
        cell = atlas.sample("PRECIP", "JJA", 106.85, -6.2)
        self.assertLess(cell.value, -1.0)
        self.assertLess(cell.t, -cell.crit)
        self.assertEqual(cell.direction, "drier")

    def test_the_composite_reproduces_coastal_ecuador_flooding(self):
        cell = atlas.sample("PRECIP", "MAM", -79.9, -2.2)
        self.assertGreater(cell.value, 1.0)
        self.assertGreater(cell.t, cell.crit)
        self.assertEqual(cell.direction, "wetter")

    def test_a_weak_statistic_is_reported_as_no_clear_signal(self):
        cell = atlas.Cell(value=0.9, base=3.0, t=1.2)
        self.assertFalse(cell.significant)
        self.assertEqual(cell.direction, "no clear signal")

    def test_a_percentage_is_refused_where_the_ordinary_year_is_dry(self):
        """Half a millimetre on a tenth of one is not '+400% of normal', it is
        a desert with a shower in it."""
        self.assertIsNone(atlas.Cell(value=0.5, base=0.05, t=3.0).percent)
        self.assertAlmostEqual(
            atlas.Cell(value=0.5, base=2.0, t=3.0).percent, 25.0)

    def test_an_unknown_cell_says_so_rather_than_guessing(self):
        cell = atlas.Cell(value=None, base=None, t=None)
        self.assertFalse(cell.known)
        self.assertFalse(cell.significant)
        self.assertIsNone(cell.percent)
        self.assertEqual(cell.direction, "unknown")

    def test_a_point_just_west_of_greenwich_reads_the_cell_it_is_in(self):
        # London, 0.13 W. The temperature cells are centred on 0.25, 2.25 ...
        # 358.25 E; the nearest centre to 359.87 is 0.25, a turn away, and the
        # cell read was the one ending at 0.75 W, which London is not in.
        cell = atlas.sample("AIR", "DJF", -0.13, 51.5)
        self.assertEqual((cell.lon0, cell.lon1), (-0.75, 1.25))

    def test_every_point_reads_a_cell_that_contains_it(self):
        for variable in ("PRECIP", "AIR"):
            for tenth in range(-1800, 1800, 7):
                lon = tenth / 10
                cell = atlas.sample(variable, "SON", lon, 12.3)
                width = (cell.lon1 - cell.lon0) % 360
                self.assertLessEqual((lon - cell.lon0) % 360, width + 1e-9,
                                     (variable, lon))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestAtlasSampleRuns(unittest.TestCase):
    """The atlas's own sample(), under node, on the real grids."""

    NAMES = ("axis", "plane", "axes", "nearestIndex", "nearestLon", "sample")

    def test_london_reads_the_cell_it_is_in(self):
        functions = "\n".join(_js_function(atlasview._JS, n) for n in self.NAMES)
        script = ("var D = {grids: %s}, gridCache = {};\n%s\n"
                  "console.log(JSON.stringify(sample('AIR', 'DJF', -0.13, 51.5)));"
                  % (json.dumps(atlasview._grid_payload()), functions))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "atlas.js"
            path.write_text(script, encoding="utf-8")
            done = subprocess.run(["node", str(path)], capture_output=True,
                                  text=True, timeout=120)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        cell = json.loads(done.stdout)
        self.assertEqual((cell["lon0"], cell["lon1"]), (-0.75, 1.25))


class TestAtlasField(unittest.TestCase):
    """The atlas's composite, drawn as the map draws it: one field, shared."""

    def test_the_atlas_paints_a_field_not_a_rect_per_cell(self):
        # A rect per cell read as a mosaic of big pixels, as the map's did.
        js = atlasview._JS
        self.assertEqual(_js_function(js, "drawCells"), "")
        body = _js_function(js, "drawField")
        self.assertIn("atlasField(", body)
        self.assertIn("imageSmoothingEnabled = true", body)
        self.assertIn("drawField();", _js_function(js, "render"))

    def test_the_map_and_the_atlas_paint_one_field_by_one_rule(self):
        for script in (atlasview._JS, stormdesk.script()):
            self.assertIn(atlasview.FIELD_JS, script)
            for name in ("fieldOf", "fieldRow", "fieldCol", "fieldAt", "paintField",
                         "fieldStart", "fieldSpan", "fieldStep", "hexRgb"):
                self.assertEqual(len(re.findall(r"\bfunction %s\(" % name, script)), 1, name)

    def test_either_theme_switch_reads_the_ramp_again(self):
        # The cells were var(--dN) and re-themed themselves; a canvas does not.
        body = _js_function(atlasview._JS, "themed")
        self.assertIn("ramp = null", body)
        self.assertIn("tone = null", body)
        self.assertIn('attributeFilter: ["data-theme"]', atlasview._JS)
        self.assertIn('matchMedia("(prefers-color-scheme: dark)")', atlasview._JS)

    def test_the_page_is_measured_again_whenever_the_map_box_changes(self):
        # A window resize was the only cue: when the bar above re-wrapped, the
        # map's box grew while the vector map kept the size it was measured
        # at, and the field and the coastlines parted.
        self.assertIn("new ResizeObserver(resize).observe(map);", atlasview._JS)
        self.assertIn('window.addEventListener("resize", resize);', atlasview._JS)

    def test_a_new_field_or_season_answers_the_marked_point_again(self):
        # The outline stayed on the old grid's cell and the dossier on the
        # old season's numbers.
        js = atlasview._JS
        self.assertIn("if (t.dataset.var) { variable = t.dataset.var; remark(); }", js)
        self.assertIn("else if (t.dataset.season) { season = t.dataset.season; remark(); }", js)

    def test_a_point_is_answered_within_one_turn_of_the_world(self):
        # atlas.html#at=0,200 put the dot a turn away from the view on it.
        body = _js_function(atlasview._JS, "pick")
        self.assertIn("lon = lon180(lon);", body)
        self.assertLess(body.index("lon = lon180(lon);"), body.index("marked = "))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestAtlasFieldRuns(unittest.TestCase):
    """The atlas's composite under node, on the real grids: every pixel the
    field at its point, in the atlas's own colour step, and the cell under a
    click outlined where it is."""

    NAMES = ("hexRgb", "axis", "plane", "axes", "crit", "rampIndex", "X", "Y", "lonAt",
             "latAt", "offsets", "fieldOf", "fieldRow", "fieldCol", "fieldAt", "paintField",
             "fieldStart", "fieldSpan", "fieldStep", "fieldGrid", "atlasField", "drawField",
             "drawMark", "preview", "applyComposite", "lon180", "spot", "lift", "remark",
             "startDrag", "grab", "fmtLat", "fmtLon", "readAt")
    HARNESS = r"""
var D = JSON.parse(require("fs").readFileSync(0, "utf8")), gridCache = {};
var variable = "PRECIP", season = "DJF", marked = null, composite = true, base = "relief";
var view = {lon: 180, lat: 0, dpp: 360 / 1024}, W = 1024, H = 512;
var LIMIT = { PRECIP: 3.0, AIR: 1.6 }, FAINT = 0.16;
var BASE = {relief: {kind: "relief"}, photo: {kind: "gibs"}};
var gPick = {innerHTML: ""}, pan = {setAttribute: function (k, v) { this[k] = v; }};
var reliefCanvas = {style: {}}, tileBox = {style: {}}, fieldCanvas = {style: {}};
var window = {devicePixelRatio: 2}, fade = true, ramp = null, fieldShot = null, fieldImage = null;
var pointers = new Map(), drag = null, pinching = null, picked = [];
var map = {getBoundingClientRect: function () { return {left: 0, top: 0}; },
           classList: {remove: function () {}}};
function pick(lon, lat) { picked.push([lon, lat]); }
function ImageData(data, w, h) { this.data = data; this.width = w; this.height = h; }
/*ATLAS*/
var RGB = [];
for (var k = 0; k < 11; k++) RGB.push([k * 20, 255 - k * 20, 7 * k]);
function check(name, mask, v, w, h, step) {
  view = v; W = w; H = h;
  var f = atlasField(name, "DJF", mask, w, h, step, RGB), g = fieldGrid(name, "DJF");
  var n = {w: f.w, h: f.h, drawn: 0, clear: 0, faint: 0, bad: 0, first: null};
  for (var j = 0; j < f.h; j++) for (var i = 0; i < f.w; i++) {
    var lon = lonAt(f.x + (i + 0.5) * step), lat = latAt(f.y + (j + 0.5) * step);
    var at = (j * f.w + i) * 4, want = [0, 0, 0, 0];
    if (lat >= -90 && lat <= 90) {
      var here = fieldAt(g, lon, lat);
      if (here.cover > 0) {
        var rgb = RGB[rampIndex(here.value, name)];
        var a = here.cover * (mask ? FAINT + (1 - FAINT) * here.sig : 1);
        want = [rgb[0], rgb[1], rgb[2], Math.round(a * 255)];
      }
    }
    var got = [f.data[at], f.data[at + 1], f.data[at + 2], f.data[at + 3]];
    if (want[3] === 0 ? got[3] !== 0 : got.join() !== want.join()) {
      n.bad++;
      if (!n.first) n.first = [i, j, got, want];
    }
    if (want[3] === 0) n.clear++; else n.drawn++;
    if (want[3] > 0 && want[3] < 255) n.faint++;
  }
  return n;
}
var out = {};
// A world 1024 pixels across on a 1024 by 512 page, centred on the date line
// and then on Greenwich; then a world 512 across, with room above and below.
out.views = {
  dateline: check("PRECIP", true, {lon: 180, lat: 0, dpp: 360 / 1024}, 1024, 512, 2),
  greenwich: check("AIR", true, {lon: 0, lat: 0, dpp: 360 / 1024}, 1024, 512, 2),
  unmasked: check("PRECIP", false, {lon: 180, lat: 0, dpp: 360 / 1024}, 1024, 512, 3),
  tall: check("PRECIP", true, {lon: 0, lat: 0, dpp: 360 / 512}, 1024, 512, 2)
};
// The world a pixel to the right and a pixel down: the same field on the
// same ground, drawn a pixel over.
W = 1024; H = 512;
view = {lon: 180, lat: 0, dpp: 360 / 1024};
var before = atlasField("PRECIP", "DJF", true, 1024, 512, 2, RGB);
view = {lon: 180 - 360 / 1024, lat: 360 / 1024, dpp: 360 / 1024};
var after = atlasField("PRECIP", "DJF", true, 1024, 512, 2, RGB);
out.pan = {same: before.data.join() === after.data.join(), size: [after.w, after.h],
           moved: [after.x - before.x, after.y - before.y]};
// The rainfall cell under a click at 179.5 W runs from 180 to 177.5 W, and
// Chukotka's temperature cell from 179.25 E to 178.75 W, as sample() gives
// them: 0 to 360.
W = 1000; H = 600;
view = {lon: 180, lat: 0, dpp: 0.05};
marked = {lon: -179.5, lat: -10, box: [180, 182.5, -11.25, -8.75]};
drawMark(); out.dateline = gPick.innerHTML;
view = {lon: -179.9, lat: 65.8, dpp: 0.05};
marked = {lon: -179.9, lat: 65.8, box: [179.25, 181.25, 64.75, 66.75]};
drawMark(); out.chukotka = gPick.innerHTML;
// Lima at the closest zoom, where a rainfall cell is 1250 pixels across.
view = {lon: -77.03, lat: -12.05, dpp: 0.002};
marked = {lon: -77.03, lat: -12.05, box: [282.5, 285, -12.5, -10]};
drawMark(); out.tight = gPick.innerHTML;
// A page too short for the cell: 250 pixels tall on a page of 200.
W = 1000; H = 200;
view = {lon: 0, lat: 0, dpp: 0.01};
marked = {lon: 1, lat: 0, box: [0, 2.5, -1.25, 1.25]};
drawMark(); out.short = gPick.innerHTML;
// The point panned 60 pixels off the page, its cell still 150 pixels on it.
W = 1000; H = 600;
marked = {lon: -5.6, lat: 0, box: [354, 356.5, -1.25, 1.25]};
drawMark(); out.offpage = gPick.innerHTML;
// A view from 175.5 E to 179.5 E, short of the date line, and a point at
// 179.5 W in Chukotka's cell, 179.25 E to 178.75 W: its point is a turn of
// the world away from any the view spans, and its cell on the page.
view = {lon: 177.5, lat: 65.8, dpp: 0.004};
marked = {lon: -179.5, lat: 65.8, box: [179.25, 181.25, 64.75, 66.75]};
drawMark(); out.across = gPick.innerHTML;
preview(10, -4, 1.5);
out.preview = [fieldCanvas.style.transform, fieldCanvas.style.transformOrigin,
               reliefCanvas.style.transform];
base = "photo"; applyComposite(); out.over = [fieldCanvas.style.display, fieldCanvas.style.opacity];
composite = false; applyComposite(); out.off = fieldCanvas.style.display;
// Taps on a world 256 pixels tall on a page of 512: one above the north
// pole, one on the equator, one on the pole itself.
W = 1024; H = 512;
view = {lon: 0, lat: 0, dpp: 360 / 512};
function tap(x, y) {
  pointers.set(1, {x: x, y: y});
  drag = {x: x, y: y, dx: 0, dy: 0, moved: false};
  lift({pointerId: 1, clientX: x, clientY: y}, false);
}
tap(300, 50); tap(300, 256); tap(300, 128);
out.taps = picked.slice();
// The readout of where the pointer is, above the north pole and on the equator.
var readout = {textContent: ""};
readAt({x: 300, y: 50}); out.readout = [readout.textContent];
readAt({x: 300, y: 256}); out.readout.push(readout.textContent);
picked = [];
marked = {lon: 10, lat: 5, box: null}; remark();
marked = null; remark();
out.remark = picked;
out.lon180 = [200, -190, 540, -540, 0, 179.5, -180, 180].map(lon180);
// A press on the zoom buttons, which sit on the map, and one on the map.
var captured = 0;
map.setPointerCapture = function () { captured++; };
map.classList.add = function () {};
pointers = new Map(); drag = null; pinching = null;
function on(zoom) {
  return {closest: function (sel) { return zoom && sel === ".atlaszoom" ? {} : null; }};
}
grab({button: 0, pointerId: 7, clientX: 1000, clientY: 20, target: on(true)});
out.zoomPress = [pointers.size, captured, drag];
grab({button: 0, pointerId: 8, clientX: 500, clientY: 300, target: on(false)});
out.mapPress = [pointers.size, captured, !!drag];
// The field drawn: the canvas held to the page the map was measured at.
var drawn = [];
var ctx2d = {clearRect: function () {}, putImageData: function () {},
             drawImage: function (img, x, y, w, h) { drawn.push([x, y, w, h]); }};
fieldCanvas = {style: {}, width: 0, height: 0, getContext: function () { return ctx2d; }};
var document = {createElement: function () {
  return {width: 0, height: 0, getContext: function () { return ctx2d; }};
}};
composite = true; ramp = RGB;
W = 1024; H = 512; view = {lon: 180, lat: 0, dpp: 360 / 1024};
drawField();
out.field = {style: [fieldCanvas.style.width, fieldCanvas.style.height],
             store: [fieldCanvas.width, fieldCanvas.height],
             image: [fieldImage.width, fieldImage.height], drawn: drawn};
console.log(JSON.stringify(out));
"""
    _out = None

    def run_atlas(self):
        if TestAtlasFieldRuns._out is None:
            data = atlasview.payload(SimpleNamespace())
            harness = self.HARNESS.replace(
                "/*ATLAS*/", "\n".join(_js_function(atlasview._JS, n) for n in self.NAMES))
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "field.js"
                path.write_text(harness, encoding="utf-8")
                done = subprocess.run(["node", str(path)], capture_output=True, text=True,
                                      encoding="utf-8", timeout=120, input=json.dumps(
                                          {"grids": data["grids"],
                                           "significant": data["significant"]}))
            self.assertEqual(done.returncode, 0, done.stderr[-2000:])
            TestAtlasFieldRuns._out = json.loads(done.stdout)
        return TestAtlasFieldRuns._out

    @staticmethod
    def rects(svg):
        return [(float(x), float(w)) for x, w in re.findall(
            r'<rect x="([-\d.]+)" y="[-\d.]+" width="([-\d.]+)"', svg)]

    def test_every_pixel_is_the_field_at_its_point(self):
        views = self.run_atlas()["views"]
        for name, view in views.items():
            self.assertEqual(view["bad"], 0, (name, view["first"]))
            self.assertGreater(view["drawn"], 1000, name)
        self.assertEqual((views["dateline"]["w"], views["dateline"]["h"]), (513, 257))
        self.assertEqual((views["unmasked"]["w"], views["unmasked"]["h"]), (343, 172))
        # Fade below 95% draws faint what the t test does not pass; off, nothing is.
        self.assertGreater(views["dateline"]["faint"], 1000)
        self.assertEqual(views["unmasked"]["faint"], 0)
        # Temperature is land only: the sea is left clear.
        self.assertGreater(views["greenwich"]["clear"], 10000)

    def test_beyond_the_poles_nothing_is_drawn(self):
        tall = self.run_atlas()["views"]["tall"]
        self.assertEqual(tall["bad"], 0, tall["first"])
        # The world is rows 65 to 192 of the field's 257: the other 129 are clear.
        self.assertEqual(tall["clear"], 513 * 129)

    def test_the_field_holds_still_on_the_ground_as_the_view_pans(self):
        pan = self.run_atlas()["pan"]
        self.assertTrue(pan["same"])
        self.assertEqual(pan["size"], [513, 257])
        self.assertEqual(pan["moved"], [1, 1])

    def test_the_field_canvas_is_held_to_the_page_the_map_was_measured_at(self):
        # Left to the stylesheet's 100%, it stretched with the map's box while
        # the vector map kept its measured size.
        field = self.run_atlas()["field"]
        self.assertEqual(field["style"], ["1024px", "512px"])
        self.assertEqual(field["store"], [2048, 1024])
        self.assertEqual(field["image"], [513, 257])
        # Drawn from its first point, a step before the page's corner.
        self.assertEqual(field["drawn"], [[-4, -4, 2052, 1028]])

    def test_a_cell_across_the_date_line_is_outlined_where_it_is(self):
        # Its east edge wrapped to the far side of the world, the dashed box
        # was drawn from 177.5 W the long way round to 180: 7150 pixels wide.
        out = self.run_atlas()
        self.assertEqual(self.rects(out["dateline"]), [(500.0, 50.0)])
        self.assertEqual(self.rects(out["chukotka"]), [(483.0, 40.0)])

    def test_a_cell_wider_than_the_view_is_not_outlined(self):
        # All that is left of it on screen is a lone dashed line.
        tight = self.run_atlas()["tight"]
        self.assertEqual(self.rects(tight), [])
        self.assertIn("<circle", tight)
        # Nor one taller than it: its sides were two lone lines down the page.
        short = self.run_atlas()["short"]
        self.assertEqual(self.rects(short), [])
        self.assertIn("<circle", short)

    def test_a_cell_still_on_the_page_is_outlined_when_its_point_is_not(self):
        offpage = self.run_atlas()["offpage"]
        self.assertEqual(self.rects(offpage), [(-100.0, 250.0)])
        self.assertNotIn("<circle", offpage)
        across = self.run_atlas()["across"]
        self.assertEqual(self.rects(across), [(937.5, 500.0)])
        self.assertNotIn("<circle", across)

    def test_a_tap_beyond_the_poles_opens_nothing(self):
        # It opened a dossier for 144.84 N.
        self.assertEqual(self.run_atlas()["taps"], [[-149.0625, 0], [-149.0625, 90]])

    def test_the_readout_beyond_the_poles_is_a_dash(self):
        # It read 233.27°N under a pointer above the world on a phone.
        self.assertEqual(self.run_atlas()["readout"], ["\u2014", "0.00\u00b0N  149.06\u00b0W"])

    def test_the_marked_point_is_answered_again_and_nothing_else(self):
        self.assertEqual(self.run_atlas()["remark"], [[10, 5]])

    def test_a_press_on_the_zoom_buttons_is_theirs_not_the_maps(self):
        # The map took every press and captured the pointer, so the click
        # went to the map: +, - and Fit did nothing, in any browser.
        out = self.run_atlas()
        self.assertEqual(out["zoomPress"], [0, 0, None])
        self.assertEqual(out["mapPress"], [1, 1, True])
        self.assertIn('map.addEventListener("pointerdown", grab);', atlasview._JS)

    def test_a_longitude_is_taken_into_one_turn_of_the_world(self):
        self.assertEqual(self.run_atlas()["lon180"], [-160, 170, -180, -180, 0, 179.5, -180, -180])

    def test_a_gesture_moves_the_field_with_the_ground_under_it(self):
        self.assertEqual(self.run_atlas()["preview"],
                         ["translate(10px,-4px) scale(1.5)", "0 0",
                          "translate(10px,-4px) scale(1.5)"])

    def test_the_field_gives_way_over_imagery_as_the_cells_did(self):
        out = self.run_atlas()
        self.assertEqual(out["over"], ["", "0.58"])
        self.assertEqual(out["off"], "none")


class TestAtlasDossier(unittest.TestCase):

    def test_a_dossier_covers_every_season_in_order(self):
        local = atlas.dossier(106.85, -6.2)
        self.assertEqual(tuple(s.season for s in local.seasons), atlas.SEASONS)

    def test_the_nearest_place_to_jakarta_is_jakarta(self):
        local = atlas.dossier(106.85, -6.2)
        self.assertEqual(local.places[0].place.name, "Jakarta")
        distances = [n.km for n in local.places]
        self.assertEqual(distances, sorted(distances))

    def test_a_point_outside_a_regional_footprint_only_gets_the_global_ones(self):
        """The Great Sandy Desert is not in the eastern Australia box, and a
        page that says it is has stopped being about this point."""
        local = atlas.dossier(127.34, -21.09)
        scopes = {geo.BY_REGION[link.region].scope for link in local.links}
        self.assertNotIn(geo.REGIONAL, scopes)
        self.assertIn(geo.GLOBAL, scopes)

    def test_a_dossier_east_of_the_dateline_is_the_dossier_west_of_it(self):
        east = atlas.dossier(200.0, -5.0)
        west = atlas.dossier(-160.0, -5.0)
        self.assertEqual(east.lon, west.lon)
        self.assertEqual([s.precip.value for s in east.seasons],
                         [s.precip.value for s in west.seasons])

    def test_a_storm_is_reported_only_when_it_is_actually_nearby(self):
        near = SimpleNamespace(
            title="Test", basin="EP", active=True,
            latest=SimpleNamespace(lon=107.0, lat=-6.0, wind=75),
        )
        far = SimpleNamespace(
            title="Elsewhere", basin="AL", active=True,
            latest=SimpleNamespace(lon=-40.0, lat=20.0, wind=75),
        )
        local = atlas.dossier(106.85, -6.2, storms=(near, far))
        names = [s["name"] for s in local.storms]
        self.assertIn("Test", names)
        self.assertNotIn("Elsewhere", names)

    def test_the_tier_builds_offline_and_explains_its_own_sample(self):
        state = atlas.evaluate()
        self.assertTrue(state.available)
        self.assertTrue(state.anchors)
        self.assertEqual(set(state.samples), set(atlas.SEASONS))
        for block in state.samples.values():
            self.assertGreater(block["base_years"], len(block["warm_events"]))
        self.assertTrue(any("Welch" in reason for reason in state.reasons))


class TestGazetteer(unittest.TestCase):

    def test_every_place_is_on_the_planet(self):
        self.assertGreater(len(atlasdata.PLACES), 7000)
        for place in atlasdata.PLACES:
            self.assertGreaterEqual(place.lon, -180.0)
            self.assertLessEqual(place.lon, 180.0)
            self.assertGreaterEqual(place.lat, -90.0)
            self.assertLessEqual(place.lat, 90.0)
            self.assertGreaterEqual(place.population, 0)

    def test_places_are_stored_most_populous_first(self):
        """``visible`` walks the list and stops at its limit, which is only
        the most populous window if the list is in that order."""
        populations = [p.population for p in atlasdata.PLACES]
        self.assertEqual(populations, sorted(populations, reverse=True))

    def test_near_returns_ascending_distances_and_honours_its_limit(self):
        found = atlasdata.near(0.0, 51.5, limit=4)
        self.assertEqual(len(found), 4)
        self.assertEqual([km for km, _ in found],
                         sorted(km for km, _ in found))
        self.assertLess(found[0][0], 60.0)

    def test_a_window_that_wraps_past_the_dateline_still_finds_places(self):
        """A Pacific-centred map runs 100 to 300, which is off the end of
        -180..180 and has to be compared in the window's own frame."""
        found = atlasdata.visible(100.0, 300.0, -40.0, 40.0, limit=50)
        self.assertTrue(found)
        names = {p.name for p in found}
        self.assertTrue(names & {"Jakarta", "Manila", "Lima", "Singapore"})

    def test_capitals_are_flagged(self):
        jakarta = next(p for p in atlasdata.PLACES if p.name == "Jakarta")
        self.assertTrue(jakarta.capital)
        self.assertIn("Indonesia", jakarta.label)


class TestVectorLayers(unittest.TestCase):

    def test_detail_never_drops_as_the_level_rises(self):
        """Douglas-Peucker is run per level with the child tolerance clamped to
        its parent, so a point kept at level 1 must still be there at level 3.
        Without the clamp a coastline can gain detail and lose a headland."""
        for layer in atlasdata.LAYERS:
            counts = [sum(len(line) for line in atlasdata.lines(layer, level))
                      for level in range(len(atlasdata.TOLERANCES))]
            self.assertEqual(counts, sorted(counts), layer)
            self.assertGreater(counts[0], 0, layer)

    def test_every_decoded_vertex_is_a_coordinate(self):
        for layer in atlasdata.LAYERS:
            for line in atlasdata.lines(layer, 1):
                for lon, lat in line:
                    self.assertGreaterEqual(lon, -180.0)
                    self.assertLessEqual(lon, 180.0)
                    self.assertGreaterEqual(lat, -90.0)
                    self.assertLessEqual(lat, 90.0)

    def test_the_packed_form_carries_one_level_digit_per_point(self):
        for layer in atlasdata.LAYERS:
            for coords, marks in atlasdata.packed(layer):
                self.assertEqual(len(coords.split(",")), len(marks) * 2)

    def test_the_level_for_a_zoom_is_the_coarsest_that_still_fits_a_pixel(self):
        self.assertEqual(atlasdata.level_for(1.0), 0)
        self.assertEqual(atlasdata.level_for(atlasview.TIGHT),
                         len(atlasdata.TOLERANCES) - 1)
        self.assertLessEqual(atlasdata.level_for(0.05), 2)


class TestAtlasPage(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.state = SimpleNamespace(
            atlas=atlas.evaluate(),
            cyclones=SimpleNamespace(storms=(), available=False),
            generated=date(2026, 9, 23),
        )

    def test_the_payload_is_json_and_carries_every_layer_the_page_draws(self):
        payload = atlasview.payload(self.state)
        restored = json.loads(json.dumps(payload))
        for key in ("grids", "places", "links", "storms", "coast", "borders",
                    "rivers", "lakes", "tolerances", "seasons", "significant"):
            self.assertIn(key, restored)
        self.assertEqual(set(restored["grids"]), {"PRECIP", "AIR"})
        self.assertTrue(restored["grids"]["PRECIP"]["invert"])
        self.assertFalse(restored["grids"]["AIR"]["invert"])

    def test_a_storm_with_no_analysis_fix_is_skipped_rather_than_crashing(self):
        """``latest`` is None for an advisory with no zero-hour fix, and a
        storm with nowhere to be drawn is not a storm the map can draw."""
        state = SimpleNamespace(cyclones=SimpleNamespace(storms=(
            SimpleNamespace(title="Ghost", basin="AL", active=True,
                            latest=None, track=(), forecast=()),
            SimpleNamespace(title="Real", basin="AL", active=True,
                            latest=SimpleNamespace(lon=-50.0, lat=15.0, wind=80),
                            track=(SimpleNamespace(lon=-48.0, lat=14.0, tau=0),
                                   SimpleNamespace(lon=-49.0, lat=14.5, tau=12)),
                            forecast=(SimpleNamespace(lon=-52.0, lat=16.0),)),
        )))
        drawn = atlasview._storms_payload(state)
        self.assertEqual([s["name"] for s in drawn], ["Real"])
        # Only analysis fixes make the track; a forecast point is not history.
        self.assertEqual(drawn[0]["track"], [[-48.0, 14.0]])

    def test_a_storm_across_the_date_line_is_drawn_the_short_way(self):
        # ATCF's longitudes run 180 W to 180 E, so a track that crosses the
        # date line jumps 360 degrees, and a line drawn through the numbers
        # as given runs the whole way round the world.
        fix = lambda lon, tau=0: SimpleNamespace(lon=lon, lat=20.0, tau=tau)  # noqa: E731
        state = SimpleNamespace(cyclones=SimpleNamespace(storms=(
            SimpleNamespace(title="Nolo", basin="CP", active=True,
                            latest=SimpleNamespace(lon=179.6, lat=20.0, wind=90),
                            track=(fix(-178.8), fix(-179.7), fix(179.6)),
                            forecast=(fix(178.0, 12), fix(-179.0, 24))),)))
        [nolo] = atlasview._storms_payload(state)
        self.assertEqual(nolo["lon"], 179.6)
        self.assertEqual(nolo["track"], [[181.2, 20.0], [180.3, 20.0], [179.6, 20.0]])
        self.assertEqual(nolo["forecast"], [[178.0, 20.0], [181.0, 20.0]])

    def test_the_composite_is_a_canvas_between_the_imagery_and_the_vector_map(self):
        html = atlasview.page(self.state)
        order = [html.index(tag) for tag in ('<canvas id="relief"', '<div id="tiles"',
                                             '<canvas id="field"', '<svg id="svg"')]
        self.assertEqual(order, sorted(order))
        self.assertNotIn('<g id="cells">', html)
        self.assertIn(".atlasmap #relief, .atlasmap #tiles, .atlasmap #field {"
                      " position: absolute;", atlasview.css())

    def test_the_page_draws_itself_without_asking_anyone(self):
        """The offline guarantee, restated for a page that now offers imagery.
        It is not that nothing is ever fetched - it is that nothing is fetched
        to draw the page. Every mark on first paint comes out of the file: the
        cartography, the composite, and the relief. The XML namespace on the
        favicon is a URI and not a request."""
        html = atlasview.page(self.state)
        # Nothing the browser loads on its own: no script, style, image or
        # font with an address. The tiles are Image objects made in JavaScript
        # when a reader picks an imagery base, which is a different thing.
        for attr in ("src=", "href="):
            for quote in ("'", '"'):
                self.assertNotIn(f"{attr}{quote}http", html)
                self.assertNotIn(f"{attr}{quote}//", html)
        for host in ("googleapis", "mapbox", "arcgis", "cdn.", "unpkg"):
            self.assertNotIn(host, html)
        # And the base it opens on is the one that needs no network.
        self.assertIn('var base = "relief"', html)
        self.assertIn("<svg", html)
        self.assertIn("function pick", html)

    def test_nothing_in_the_page_is_a_credential(self):
        """The reason there is no Google basemap here. Every tile source on
        the page is public and keyless; the moment one is not, a key is in the
        repository and the page cannot be handed to anyone."""
        html = atlasview.page(self.state)
        for secret in ("api_key", "apikey", "api-key", "access_token",
                       "&key=", "?key=", "appid", "client_secret",
                       "subscription-key", "Authorization"):
            self.assertNotIn(secret, html)

    def test_every_address_the_page_can_reach_is_a_known_public_one(self):
        """A page that opens links and loads tiles should not be able to
        surprise the reader with where it goes. This is the whole list."""
        import re
        html = atlasview.page(self.state)
        allowed = {
            "gibs.earthdata.nasa.gov",          # the imagery itself
            "worldview.earthdata.nasa.gov",     # the same imagery, their tool
            "www.google.com",                   # maps, satellite view
            "earth.google.com",                 # the oblique view
            "www.openstreetmap.org",            # what is actually there
            "api.open-meteo.com",               # one elevation, on a press
            "www.w3.org",                       # the SVG namespace, not a fetch
        }
        hosts = set(re.findall(r"https?://([A-Za-z0-9.\-]+)", html))
        self.assertTrue(hosts)
        self.assertEqual(hosts - allowed, set())
        # http:// is not in that set at all - every one of them is https.
        self.assertNotIn("http://", html.replace("http://www.w3.org", ""))

    def test_the_legend_turns_round_for_the_variable_that_inverts(self):
        """Rainfall maps the negated value so the dry end reads warm. A strip
        drawn in ramp order under a -3..+3 label would then be backwards."""
        html = atlasview.page(self.state)
        self.assertIn('id="steps"', html)
        self.assertIn("flexDirection", html)
        self.assertIn("row-reverse", html)

    def test_the_card_names_the_column_it_actually_shows(self):
        html = atlasview.card(self.state)
        self.assertIn("% of normal", html)
        self.assertIn("atlas.html", html)


class TestAtlasInTheDashboard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.state = SimpleNamespace(atlas=atlas.evaluate())

    def test_only_rainfall_gets_a_percentage_of_normal(self):
        """A percentage of a temperature is arithmetic on an interval scale.
        It is also how a Kelvin baseline hides: 0.4 degrees on 300 is 0.1%."""
        blob = dashboard._atlas_json(self.state)
        self.assertTrue(blob["anchors"])
        for anchor in blob["anchors"]:
            for season in anchor["seasons"].values():
                self.assertIn("percent_of_normal", season["precip_mm_day"])
                self.assertNotIn("percent_of_normal", season["air_degc"])
                # And the baseline it would be taken against is a temperature
                # a person could stand in, not an absolute one.
                base = season["air_degc"]["neutral_mean"]
                if base is not None:
                    self.assertGreater(base, -90.0)
                    self.assertLess(base, 60.0)


class TestVendoredRelief(unittest.TestCase):
    """The solid Earth, carried in the file rather than fetched."""

    @classmethod
    def setUpClass(cls):
        cls.grid = relief.grid()

    def test_the_png_is_two_stacked_byte_planes_of_the_right_size(self):
        """The browser reads this with its own decoder and splits the planes
        by arithmetic, so the shape has to be exactly what it expects: one
        eight-bit greyscale image, as wide as the grid and twice as tall."""
        import base64
        import struct
        raw = base64.b64decode(relief.png().split(",", 1)[1])
        self.assertEqual(raw[:8], b"\x89PNG\r\n\x1a\n")
        self.assertEqual(raw[12:16], b"IHDR")
        width, height, depth, colour = struct.unpack(">IIBB", raw[16:26])
        self.assertEqual(width, relief.NX)
        self.assertEqual(height, 2 * relief.NY)
        self.assertEqual(depth, 8)
        self.assertEqual(colour, 0)

    def test_the_grid_decodes_to_one_elevation_a_cell(self):
        self.assertEqual(len(self.grid), relief.NY)
        for row in self.grid:
            self.assertEqual(len(row), relief.NX)
        self.assertEqual(relief.STATS["cells"], relief.NY * relief.NX)

    def test_the_extremes_are_the_ones_the_generator_recorded(self):
        flat = [value for row in self.grid for value in row]
        self.assertEqual(min(flat), relief.STATS["min"])
        self.assertEqual(max(flat), relief.STATS["max"])
        land = [v for v in flat if v > 0]
        self.assertAlmostEqual(len(land) / len(flat),
                               relief.STATS["land_fraction"], places=3)

    def test_it_knows_where_the_deep_and_the_high_places_are(self):
        """Spot checks against the world, not against itself. A quarter-degree
        cell is 28 km, so these are ranges a landscape has to fall in and not
        summit elevations."""
        cases = [
            # lon, lat, low, high, what
            (86.9, 27.99, 3000, 6500, "Everest massif"),
            (142.2, 11.35, -11000, -7000, "Mariana Trench"),
            (-150.0, 0.0, -6000, -3000, "central Pacific floor"),
            (2.0, 25.0, 100, 1200, "central Sahara"),
            (-60.0, -3.0, 0, 300, "Amazon lowland"),
            (35.5, 31.5, -450, 200, "Dead Sea rift"),
            (0.0, 85.0, -5000, 0, "Arctic Ocean"),
            (0.0, -85.0, 0, 4000, "East Antarctic ice sheet"),
        ]
        for lon, lat, low, high, what in cases:
            metres = relief.at(lon, lat)
            self.assertGreaterEqual(metres, low, what)
            self.assertLessEqual(metres, high, what)

    def test_a_longitude_the_far_side_of_the_dateline_wraps(self):
        self.assertEqual(relief.at(190.0, 0.0), relief.at(-170.0, 0.0))
        self.assertEqual(relief.at(-181.0, 10.0), relief.at(179.0, 10.0))

    def test_the_sea_is_most_of_the_planet_and_averages_an_abyss(self):
        """A sanity check on the whole grid at once: if the sign convention
        were inverted, or the bias not taken off, this is what would catch it.
        """
        self.assertGreater(relief.STATS["land_fraction"], 0.25)
        self.assertLess(relief.STATS["land_fraction"], 0.35)
        self.assertLess(relief.STATS["mean_sea_m"], -3000)
        self.assertGreater(relief.STATS["mean_land_m"], 500)


class TestImageryGeometry(unittest.TestCase):
    """GIBS's EPSG:4326 pyramid, which is not the obvious one.

    Its top level is 288 degrees to a 512-pixel tile, halving from there, so
    two tiles span 576 degrees of a 360-degree planet and the far column and
    bottom row are padded. Assuming 180 degrees at the top - the power-of-two
    scheme every other tile server uses - puts every tile above level zero in
    the wrong place at the wrong size. This is that assumption, as a test.
    """

    TOP = 288.0

    def matrix(self, z):
        import math
        span = self.TOP / 2 ** z
        return math.ceil(360 / span), math.ceil(180 / span), span

    def test_the_matrix_sizes_are_the_ones_nasa_publishes(self):
        published = [(2, 1), (3, 2), (5, 3), (10, 5), (20, 10),
                     (40, 20), (80, 40), (160, 80), (320, 160)]
        for z, (cols, rows) in enumerate(published):
            got_cols, got_rows, _ = self.matrix(z)
            self.assertEqual((got_cols, got_rows), (cols, rows), f"level {z}")

    def test_the_matrix_covers_the_world_with_less_than_a_tile_to_spare(self):
        for z in range(0, 9):
            cols, rows, span = self.matrix(z)
            self.assertGreaterEqual(cols * span, 360.0, f"level {z}")
            self.assertGreaterEqual(rows * span, 180.0, f"level {z}")
            self.assertLess((cols - 1) * span, 360.0, f"level {z}")
            self.assertLess((rows - 1) * span, 180.0, f"level {z}")

    def test_the_top_levels_end_in_a_partial_tile(self):
        """Which is why the page cannot take a tile column modulo the matrix
        width to wrap the world, and why the edge tiles are clipped. From
        level two down the columns happen to divide exactly - but the map
        opens fitted to the whole world, which is level zero or one, and that
        is exactly where the padding showed as a black band."""
        partial = []
        for z in range(0, 9):
            cols, rows, span = self.matrix(z)
            if cols * span > 360.0 or rows * span > 180.0:
                partial.append(z)
        self.assertIn(0, partial)
        self.assertIn(1, partial)
        self.assertIn(2, partial)          # in latitude: three rows of 72

    def test_the_page_carries_that_number_and_clips_the_padding(self):
        state = SimpleNamespace(
            atlas=atlas.evaluate(),
            cyclones=SimpleNamespace(storms=(), available=False),
            generated=date(2026, 9, 23),
        )
        html = atlasview.page(state)
        self.assertIn("var TOP = 288", html)
        self.assertIn("clipPath", html)
        self.assertIn("Math.ceil(360 / span)", html)

    def test_every_imagery_layer_is_named_with_its_matrix_set_and_type(self):
        for base in atlasview.BASEMAPS:
            if base["kind"] != "gibs":
                continue
            for key in ("layer", "tms", "ext", "max", "credit", "note"):
                self.assertIn(key, base, base["id"])
            self.assertIn(base["ext"], ("jpg", "jpeg", "png"))
            self.assertGreaterEqual(base["max"], 5)

    def test_a_dated_layer_asks_for_a_day_that_has_finished_processing(self):
        """A global daily mosaic is not complete the moment the day ends, and
        a tile that does not exist yet is an error, not an empty map."""
        today = datetime.now(timezone.utc).date()
        for base in atlasview._bases_payload():
            if not base.get("date"):
                continue
            asked = date(*[int(p) for p in base["date"].split("-")])
            self.assertLess(asked, today)
            self.assertGreater((today - asked).days, 0)
            self.assertLessEqual((today - asked).days, 7)


class TestPhysicalReadout(unittest.TestCase):
    """What a click says about the ground, and where it can send you."""

    @classmethod
    def setUpClass(cls):
        cls.state = SimpleNamespace(
            atlas=atlas.evaluate(),
            cyclones=SimpleNamespace(storms=(), available=False),
            generated=date(2026, 9, 23),
        )
        cls.html = atlasview.page(cls.state)

    def test_the_payload_describes_the_relief_grid_the_page_decodes(self):
        payload = atlasview.payload(self.state)
        self.assertIn("relief", payload)
        block = payload["relief"]
        self.assertEqual(block["ny"], relief.NY)
        self.assertEqual(block["nx"], relief.NX)
        self.assertEqual(block["step"], relief.STEP)
        self.assertEqual(block["lat0"], relief.LAT0)
        self.assertEqual(block["lon0"], relief.LON0)
        self.assertEqual(block["offset"], relief.OFFSET)
        self.assertEqual(block["vendored"], relief.VENDORED)

    def test_the_basemap_catalogue_reaches_the_page(self):
        payload = atlasview.payload(self.state)
        ids = [base["id"] for base in payload["bases"]]
        self.assertEqual(ids, ["relief", "marble", "photo", "sst"])
        self.assertTrue(payload["gibs"].startswith("https://"))

    def test_the_reader_is_told_the_cell_is_a_landscape_not_an_address(self):
        """A quarter-degree elevation quoted to the metre beside a place name
        invites the reader to think it is the height of that place."""
        self.assertIn("a landscape, ", self.html)
        self.assertIn("not a street", self.html)

    def test_the_ways_out_of_the_page_are_all_four_of_them(self):
        for where in ("google.com/maps", "earth.google.com",
                      "worldview.earthdata.nasa.gov",
                      "openstreetmap.org"):
            self.assertIn(where, self.html)

    def test_the_elevation_service_is_one_that_answers_a_browser(self):
        """OpenTopoData serves no Access-Control-Allow-Origin, so a page
        calling it gets a CORS error and the reader gets nothing, forever.
        This was shipped once and caught by pressing the button."""
        self.assertIn("api.open-meteo.com/v1/elevation", self.html)
        self.assertNotIn("opentopodata", self.html)

    def test_the_measurement_is_offered_only_where_there_is_land(self):
        """That DEM models the land surface and answers a flat zero over
        water, where the vendored bathymetry is the real number."""
        self.assertIn("if (ground > 0) {", self.html)


class TestDivergingRamp(unittest.TestCase):
    """The composite ramp, checked as a diverging ramp rather than as a
    categorical palette.

    The palette validator's categorical checks are the wrong instrument here
    and say so themselves: adjacent steps of a diverging ramp are meant to be
    close, its midpoint is meant to be neutral, and its ends are meant to be
    dark. What has to hold is that lightness runs monotonically from each end
    to a neutral middle, that chroma falls to zero there, and that the two
    halves are two hues rather than a rainbow.
    """

    LIGHT = ("#0045af", "#2269bd", "#5889ca", "#87a9d5", "#b7c8df",
             "#e8e8e8", "#e7bcb8", "#e19089", "#d6615c", "#c8222c")
    DARK = ("#61a6ff", "#568cd1", "#4c72a4", "#415979", "#364150",
            "#2a2a2a", "#553937", "#814743", "#af5550", "#df615c")

    @staticmethod
    def oklab(value):
        def linear(channel):
            return (channel / 12.92 if channel <= 0.04045
                    else ((channel + 0.055) / 1.055) ** 2.4)
        r, g, b = (linear(int(value[i:i + 2], 16) / 255) for i in (1, 3, 5))
        l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
        m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
        s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
        return (0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s,
                1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s,
                0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s)

    def parts(self, ramp):
        import math
        lab = [self.oklab(step) for step in ramp]
        light = [value[0] for value in lab]
        chroma = [math.hypot(value[1], value[2]) for value in lab]
        hue = [math.degrees(math.atan2(value[2], value[1])) % 360
               for value in lab]
        return light, chroma, hue

    def test_the_midpoint_is_the_only_neutral_step(self):
        for name, ramp in (("light", self.LIGHT), ("dark", self.DARK)):
            _, chroma, _ = self.parts(ramp)
            self.assertEqual(chroma.index(min(chroma)), 5, name)
            self.assertLess(chroma[5], 0.01, name)
            for index in (0, 9):
                self.assertGreater(chroma[index], 0.12, name)

    def test_chroma_falls_to_the_middle_and_rises_out_of_it(self):
        for name, ramp in (("light", self.LIGHT), ("dark", self.DARK)):
            _, chroma, _ = self.parts(ramp)
            for i in range(5):
                self.assertGreaterEqual(chroma[i] + 0.005, chroma[i + 1], name)
            for i in range(5, 9):
                self.assertLessEqual(chroma[i], chroma[i + 1] + 0.005, name)

    def test_lightness_runs_one_way_to_the_middle_and_back(self):
        """Which way depends on the surface: against a white page the middle
        is the lightest step, against a dark one it is the darkest. Both are
        monotone, and that is the property being checked."""
        for name, ramp in (("light", self.LIGHT), ("dark", self.DARK)):
            light, _, _ = self.parts(ramp)
            rising = light[5] > light[0]
            for i in range(5):
                if rising:
                    self.assertLessEqual(light[i], light[i + 1] + 0.004, name)
                else:
                    self.assertGreaterEqual(light[i], light[i + 1] - 0.004,
                                            name)
            for i in range(5, 9):
                if rising:
                    self.assertGreaterEqual(light[i], light[i + 1] - 0.004,
                                            name)
                else:
                    self.assertLessEqual(light[i], light[i + 1] + 0.004, name)

    def test_the_two_halves_are_two_hues_and_not_a_rainbow(self):
        for name, ramp in (("light", self.LIGHT), ("dark", self.DARK)):
            _, _, hue = self.parts(ramp)
            cool, warm = hue[:5], hue[6:]
            self.assertLess(max(cool) - min(cool), 30, name)
            self.assertLess(max(warm) - min(warm), 30, name)
            apart = abs(sum(cool) / len(cool) - sum(warm) / len(warm))
            apart = min(apart, 360 - apart)
            self.assertGreater(apart, 100, name)


class TestRegressions(unittest.TestCase):
    """One test per bug that reached a rendered page in an earlier round."""

    def test_an_episode_needs_at_least_one_season(self):
        with self.assertRaises(ValueError):
            Episode([])

    def test_a_ramp_survives_a_value_that_is_not_a_number(self):
        ramp = fields.Ramp("d", 11, -1.0, 1.0, diverging=True)
        for bad in (float("nan"), float("inf"), float("-inf")):
            index = ramp.index(bad)
            self.assertGreaterEqual(index, 0)
            self.assertLess(index, ramp.steps)

    def test_a_negative_domain_keeps_its_leftmost_tick_and_never_shows_zero(self):
        from elnino.svg import nice_ticks
        ticks = nice_ticks(-2.4, -0.2, 5)
        self.assertLessEqual(ticks[0], -0.2)
        for tick in ticks:
            self.assertNotEqual(repr(tick), "-0.0")


def _seasons(values: list[float], start_year: int = 2020) -> list[SeasonValue]:
    """A contiguous seasonal series from DJF of ``start_year``."""
    seasons = parsers.ONI_SEASONS
    return [SeasonValue(seasons[i % 12], start_year + i // 12, v)
            for i, v in enumerate(values)]


def _fixture_inputs():
    return (
        parsers.parse_oni(fixture("oni.txt")),
        parsers.parse_roni(fixture("roni.txt")),
        parsers.parse_weekly_sst(fixture("weekly.for")),
        parsers.parse_soi(fixture("soi.txt"))["standardized"],
        parsers.parse_mei(fixture("mei.txt")),
    )


class TestCpcDisplayedValue(unittest.TestCase):
    """CPC classifies on the one-decimal value it prints, not the file's two.

    Rounding the two-decimal RONI half away from zero reproduces 911 of the
    912 cells CPC colours on its RONI page, and the ONI page's 239 warm cells
    exactly; comparing the raw file against 0.5 finds 215 of those 239.
    """

    def test_ties_round_away_from_zero_on_both_sides(self):
        from elnino.classify import displayed
        for raw, printed in ((0.45, 0.5), (-0.45, -0.5), (0.25, 0.3),
                             (-0.25, -0.3), (0.15, 0.2), (0.95, 1.0),
                             (0.44, 0.4), (1.36, 1.4), (-0.04, 0.0)):
            self.assertEqual(displayed(raw), printed, raw)

    def test_a_season_printed_as_half_a_degree_is_part_of_the_run(self):
        run = current_episode(_seasons([0.0, 0.46, 0.95, 1.39, 1.80]), warm=True)
        self.assertEqual(run.length, 4)
        self.assertEqual(run.onset.value, 0.46)

    def test_a_cold_season_printed_as_minus_half_counts(self):
        episodes = find_episodes(_seasons([0.0, -0.45, -0.6, -0.8, -0.9, -1.0, 0.0]),
                                 warm=False)
        self.assertEqual(episodes[0].length, 5)
        self.assertTrue(episodes[0].qualifies)

    def test_a_season_printed_as_four_tenths_does_not_count(self):
        self.assertIsNone(current_episode(_seasons([0.0, 0.3, 0.44]), warm=True))

    def test_tiers_are_read_off_the_printed_value(self):
        self.assertEqual(intensity_tier(1.46), "Strong El Nino")
        self.assertEqual(intensity_tier(0.95), "Moderate El Nino")
        self.assertEqual(intensity_tier(1.94), "Strong El Nino")
        self.assertEqual(intensity_tier(1.95), "Very Strong El Nino")
        self.assertEqual(intensity_tier(-0.45), "Weak La Nina")
        self.assertEqual(intensity_tier(0.44), "Neutral")


class TestOfficialIndex(unittest.TestCase):
    """RONI has been CPC's official ENSO index since 1 February 2026 (NWS
    PIS 26-05). ONI is kept for continuity and is reported as legacy."""

    def test_classification_follows_roni(self):
        a = assess(*_fixture_inputs())
        self.assertEqual(a.index_name, "RONI")
        self.assertAlmostEqual(a.index_latest.value, 1.36)
        self.assertEqual(a.index_tier, "Moderate El Nino")
        # The legacy index is still reported, on its own terms.
        self.assertEqual(a.oni_tier, "Strong El Nino")
        self.assertIn("RONI +1.36", a.headline)
        self.assertIn("Moderate El Nino", a.headline)

    def test_oni_stands_in_only_when_roni_is_missing(self):
        oni, _, weeks, soi, mei = _fixture_inputs()
        a = assess(oni, [], weeks, soi, mei)
        self.assertEqual(a.index_name, "ONI")
        self.assertEqual(a.index_tier, "Strong El Nino")

    def test_the_episode_is_counted_on_roni(self):
        # ONI has been above +0.5 since FMA: five seasons, a formal episode.
        # RONI crossed in AMJ: three, and two more are needed.
        oni = _seasons([0.0, 0.2, 0.6, 0.8, 0.95, 1.39, 1.80], 2026)
        roni = _seasons([-0.5, -0.4, 0.1, 0.3, 0.49, 0.97, 1.36], 2026)
        a = assess(oni, roni, [], [], [])
        self.assertEqual(a.seasons_at_threshold, 3)
        self.assertEqual(a.episode.onset.label, "AMJ 2026")
        self.assertIn("2 more needed", a.episode_status)

    def test_power_amplitude_is_the_official_index(self):
        a = assess(*_fixture_inputs())
        self.assertAlmostEqual(a.power.components["amplitude"], 54.4, places=1)

    def test_momentum_is_measured_on_the_official_index(self):
        a = assess(*_fixture_inputs())
        self.assertAlmostEqual(a.momentum.season_delta, 0.39, places=6)

    def test_analogs_are_episodes_not_short_runs(self):
        history = _seasons([0.6, 0.9, 1.0, 0.8, 0.0, 0.0, 0.6, 1.0, 1.4])
        current = current_episode(history, warm=True)
        self.assertEqual(find_analogs(history, current), [])

    def test_regions_are_counted_on_relative_anomalies(self):
        week = parsers.parse_weekly_sst(fixture("weekly.for"))[-1]
        relative = dict(parsers.parse_rel_weekly(fixture("rel_weekly.txt"))[-1][1])
        scale = diagnose_scale(week, relative=relative)
        # Traditional: 4.5 / 3.7 / 2.9 / 0.9, all four above 0.5.
        # Relative: 3.7 / 2.8 / 2.0 / -0.1, Nino-4 no warmer than the tropics.
        self.assertEqual(scale.active_regions, 3)
        self.assertAlmostEqual(scale.flavour_index, 3.8)
        nino4 = next(r for r in scale.regions if r.key == "nino4")
        self.assertAlmostEqual(nino4.anomaly, -0.1)
        self.assertAlmostEqual(nino4.traditional, 0.9)

    def test_assess_uses_the_relative_week_that_matches_the_traditional_one(self):
        oni, roni, weeks, soi, mei = _fixture_inputs()
        relative = parsers.parse_rel_weekly(fixture("rel_weekly.txt"))
        a = assess(oni, roni, weeks, soi, mei, relative_weeks=relative)
        self.assertEqual(a.scale.active_regions, 3)

    def test_intensity_alerts_fire_on_the_official_index(self):
        raised = alerts.evaluate(assess(*_fixture_inputs()))
        titles = [a.title for a in raised if a.code.startswith("index_ge_")]
        # One alert, for the highest tier crossed: ONI's +1.80 would be
        # "Strong", RONI's +1.4 is "Moderate".
        self.assertEqual(len(titles), 1, titles)
        self.assertIn("RONI", titles[0])
        self.assertIn("+1.0", titles[0])

    def test_a_record_season_is_judged_on_the_official_index(self):
        # 25 years in which JJA of the final year is ONI's warmest JJA but
        # only RONI's fourth warmest.
        years = 25
        oni_values, roni_values = [], []
        for year in range(years):
            for month in range(12):
                oni_values.append(0.1)
                roni_values.append(0.1)
        jja = parsers.ONI_SEASONS.index("JJA")
        for year, value in ((3, 2.0), (9, 1.9), (15, 1.8)):
            roni_values[year * 12 + jja] = value
            oni_values[year * 12 + jja] = value - 0.6
        final = (years - 1) * 12 + jja
        oni_values = oni_values[:final + 1]
        roni_values = roni_values[:final + 1]
        oni_values[final] = 1.9
        roni_values[final] = 1.5
        a = assess(_seasons(oni_values, 2000), _seasons(roni_values, 2000), [], [], [])
        codes = {alert.code for alert in alerts.evaluate(a)}
        self.assertNotIn("record_season", codes)
        self.assertEqual(a.index_ranking.rank_season, 4)

    def test_historic_alert_cites_the_record_from_the_data(self):
        values = [0.0] * 12 + [0.6, 1.2, 1.8, 2.2, 2.4, 2.1, 1.0, 0.0] + [0.0] * 4
        values += [0.6, 1.0, 1.5]
        a = assess(_seasons(values, 2000), _seasons(values, 2000), [], [], [])
        peak = SimpleNamespace(mean=2.7, label="NDJ 2002", spread=0.1, methods={})
        forecast_result = SimpleNamespace(peak=peak,
                                          peak_probability={2.0: 0.9, 2.5: 0.6})
        raised = alerts.evaluate(a, forecast_result=forecast_result)
        historic = next(x for x in raised if x.code == "forecast_historic")
        self.assertIn("+2.4", historic.detail)
        self.assertIn("AMJ 2001", historic.detail)
        self.assertNotIn("1997-98", historic.detail)


class TestIndexInputs(unittest.TestCase):
    """A forecast of the index starts from the numbers the index averages."""

    def series(self, **drop):
        series = {
            "nino34_relative": [MonthValue(2026, 8, 1.67)],   # Rnino34: RONI's input
            "nino34_detrended": [MonthValue(2026, 8, 2.17)],  # ONI's input
            "rel_monthly": {"nino34": [MonthValue(2026, 8, 1.70)]},  # OISST relative
            "monthly": {"nino34": [MonthValue(2026, 8, 2.52)]},       # OISST sstoi
        }
        for key in drop:
            series.pop(key)
        return series

    def test_roni_runs_on_rnino34(self):
        self.assertEqual(pipeline.nino34_monthly(self.series(), "RONI")[-1].value, 1.67)

    def test_oni_runs_on_the_detrended_series(self):
        self.assertEqual(pipeline.nino34_monthly(self.series(), "ONI")[-1].value, 2.17)

    def test_roni_falls_back_to_the_relative_analysis_not_the_traditional(self):
        series = self.series(nino34_relative=True)
        self.assertEqual(pipeline.nino34_monthly(series, "RONI")[-1].value, 1.70)

    def test_oni_falls_back_to_oisst(self):
        series = self.series(nino34_detrended=True)
        self.assertEqual(pipeline.nino34_monthly(series, "ONI")[-1].value, 2.52)


def _linear_model(growth: float) -> forecast.RechargeModel:
    """T(m+1) = (1 + growth) * T(m), heat frozen: arithmetic done by hand."""
    return forecast.RechargeModel({}, {}, (growth, 0.0, 0.0), (0.0, 0.0), 0)


RNINO34_2026 = {(2026, 6): 1.07, (2026, 7): 1.33, (2026, 8): 1.67}
WWV_2026 = {(2026, 7): 0.9, (2026, 8): 1.0}


class TestForecastOnTheIndex(unittest.TestCase):
    def test_a_season_is_its_centre_month_and_the_two_beside_it(self):
        self.assertEqual(forecast.season_months("DJF", 2027),
                         [(2026, 12), (2027, 1), (2027, 2)])
        self.assertEqual(forecast.season_months("NDJ", 2026),
                         [(2026, 11), (2026, 12), (2027, 1)])
        self.assertEqual(forecast.season_months("JJA", 2026),
                         [(2026, 6), (2026, 7), (2026, 8)])

    def test_the_recharge_forecast_is_a_three_month_mean_from_the_last_month(self):
        # From August +1.67 at 10 per cent a month: Sep 1.837, Oct 2.0207,
        # Nov 2.22277. JAS keeps the observed Jul and Aug.
        seasons = forecast.recharge_seasons(
            _linear_model(0.1), RNINO34_2026, WWV_2026, (2026, 8), ("JJA", 2026), 3)
        self.assertAlmostEqual(seasons[1], (1.33 + 1.67 + 1.837) / 3)
        self.assertAlmostEqual(seasons[2], (1.67 + 1.837 + 2.0207) / 3)
        self.assertAlmostEqual(seasons[3], (1.837 + 2.0207 + 2.22277) / 3)

    def test_the_initial_state_is_the_last_sst_month(self):
        sst = [MonthValue(2026, m, v) for (_, m), v in sorted(RNINO34_2026.items())]
        heat = [MonthValue(2026, 7, 0.9)]  # the heat content runs a month behind
        start, t, h = forecast.initial_state(sst, heat)
        self.assertEqual((start, t, h), ((2026, 8), 1.67, 0.9))
        heat.append(MonthValue(2026, 9, 1.4))  # never borrowed from the future
        self.assertIsNone(forecast.initial_state(sst, heat[1:]))

    def test_the_hindcast_starts_from_the_season_last_month(self):
        hindcast = verification._rom_hindcast(
            _linear_model(0.1), RNINO34_2026, WWV_2026,
            SeasonValue("JJA", 2026, 1.36), 3)
        self.assertAlmostEqual(hindcast[1], (1.33 + 1.67 + 1.837) / 3)
        self.assertAlmostEqual(hindcast[3], (1.837 + 2.0207 + 2.22277) / 3)

    def test_persistence_is_the_regression_of_target_on_start(self):
        # Every year is one number z carried by a seasonal amplitude: JJA
        # carries half of NDJ's. JJA -> NDJ is then perfectly correlated with
        # a slope of two, and the best forecast of NDJ is twice JJA - not JJA
        # times a correlation of one.
        amplitude = {"JJA": 0.5, "NDJ": 1.0}
        values, z_last = [], None
        for k in range(30):
            z = math.sin(1.3 * k + 0.4)
            for season in parsers.ONI_SEASONS:
                values.append(amplitude.get(season, 0.75) * z)
                if k == 29 and season == "JJA":
                    z_last = z
                    break
        series = _seasons(values, start_year=1990)
        self.assertEqual(series[-1].label, "JJA 2019")
        projection = forecast.damped_persistence(series, 5)
        self.assertAlmostEqual(projection[5], 1.0 * z_last)

    def test_verification_scores_the_production_persistence(self):
        self.assertIs(verification.persistence_fit, forecast.persistence_fit)

    def test_the_hindcast_never_trains_on_the_year_it_forecasts_into(self):
        # A nine-month forecast from JJA verifies in the next calendar year.
        # Holding out only the start year leaves those months in the fit.
        sst, heat = _synthetic_oscillator(600)
        values = [sum(v.value for v in sst[i - 1:i + 2]) / 3 for i in range(1, len(sst) - 1)]
        seasons = [SeasonValue(parsers.ONI_SEASONS[m.month - 1], m.year, value)
                   for m, value in zip(sst[1:-1], values)]
        held: list = []

        def spy(real):
            def wrapper(*args, **kwargs):
                held.append(kwargs.get("exclude_year", args[2] if len(args) > 2 else None))
                return real(*args, **kwargs)
            return wrapper

        with mock.patch.object(verification, "fit_recharge", spy(forecast.fit_recharge)), \
                mock.patch.object(verification, "persistence_fit", spy(forecast.persistence_fit)):
            verification.run(seasons, sst, heat, leads=9)
        self.assertTrue(held)
        for years in held:
            self.assertEqual(len(years), 2, years)
            self.assertEqual(years[1], years[0] + 1)

    def test_a_fit_can_hold_out_two_years(self):
        sst, heat = _synthetic_oscillator()
        full = forecast.fit_recharge(sst, heat)
        held = forecast.fit_recharge(sst, heat, exclude_year=(1995, 1996))
        self.assertEqual(full.samples - held.samples, 24)

    def test_peak_odds_are_the_best_season_on_the_printed_value(self):
        sharp = forecast.Projection(1, "JAS", 2026, 1.9, 1.77, 2.03, 0.1)
        wide = forecast.Projection(2, "ASO", 2026, 1.8, 1.03, 2.57, 0.6)
        odds = forecast.peak_probability([sharp, wide], (2.0, 2.5))
        # P(printed >= 2.0) = P(value >= 1.95): 0.309 for the sharp season,
        # 0.401 for the wide one. P(printed >= 2.5) comes from the wide
        # season alone: z = 0.65 / 0.6 = 1.083 -> 0.139.
        self.assertAlmostEqual(odds[2.0], 0.401, places=3)
        self.assertAlmostEqual(odds[2.5], 0.139, places=3)


class TestAnalogTiming(unittest.TestCase):
    def test_seasons_to_peak_count_from_the_present_stage(self):
        past = [0.6, 0.9, 1.2, 1.5, 1.8, 1.2, 0.6]   # peaks in its fifth season
        now = [0.6, 0.9, 1.2]                       # three seasons in
        history = _seasons(past + [0.0] * 5 + now, start_year=1990)
        current = current_episode(history, warm=True)
        (analog,) = find_analogs(history, current)
        self.assertEqual(analog.seasons_to_peak, 2)


    def test_the_members_drawn_are_the_members_the_band_is_built_from(self):
        # The band is built from each analog shifted by today's lead over it
        # at the same stage; the chart drew the unshifted tracks, each hung
        # from today's value, so on 24 September 2026 the grey lines fell to
        # -1.2 below a band whose members sat about +0.8 higher.
        values = ([0.0] * 4 + [0.2, 0.4, 0.5, 0.7, 0.9, 1.0, 1.1, 1.0]
                  + [0.0] * 23 + [1.4])
        series = _seasons(values, start_year=2000)      # JJA 2000 is index 6
        member = forecast.AnalogMember("JJA", 2000, "2000-01", 0.1)
        result = forecast.build(series, [], [], [member], stage=2, leads=3)
        # At stage 2 (ASO 2000) the analog read +0.9 against today's +1.4, so
        # its SON, OND and NDJ of +1.0, +1.1, +1.0 enter the band at +0.5.
        self.assertEqual([round(v, 6) for v in result.analog_members["2000-01"]],
                         [1.5, 1.6, 1.5])
        for projection, value in zip(result.projections,
                                     result.analog_members["2000-01"]):
            self.assertIn(round(value, 6),
                          [round(v, 6) for v in projection.members])


class TestCalendarAnalogs(unittest.TestCase):
    """Forecast analogs matched and continued on the calendar.

    The forecast matched each past El Nino on its first seasons after onset
    and read it forward from that stage, whatever the month: an event that
    began in autumn was continued from its winter peak into its decay, set
    against a summer event with its growth season still ahead. Cross-
    validated over 1956-2026 that ensemble was the worst method at every lead
    past the first - RMSE 0.90 at six months inside El Nino, against 0.78 for
    damped persistence - while carrying 45% of the weight, unverified. Matched
    on the same calendar seasons and continued from the same season, the
    analogs scored 0.66.
    """

    @staticmethod
    def years(levels: dict[int, float], current: float = 1.0):
        """Each past year flat at its level; the current one flat through JJA."""
        values = []
        for year in sorted(levels):
            values += [levels[year]] * 12
        values += [current] * 7                          # DJF..JJA
        return _seasons(values, start_year=min(levels))

    def test_members_are_the_same_season_of_other_years_by_likeness(self):
        series = self.years({2000: 0.0, 2001: 0.9, 2002: 1.3, 2003: -0.5,
                             2004: 1.05, 2005: 0.2, 2006: 1.0})
        self.assertEqual(series[-1].label, "JJA 2007")
        members = forecast.calendar_analogs(series)
        # 2006 ran closest of all, but its continuation runs into the current
        # year's own record, and the hindcast holds out the same neighbours.
        self.assertEqual([m.year for m in members], [2004, 2001, 2002, 2005, 2000, 2003])
        self.assertEqual({m.season for m in members}, {"JJA"})
        self.assertEqual(members[0].name, "2004-05")
        self.assertAlmostEqual(members[0].rmse, 0.05)
        self.assertAlmostEqual(members[2].rmse, 0.3)

    def test_a_hindcast_start_holds_out_its_neighbours(self):
        series = self.years({2000: 0.0, 2001: 0.9, 2002: 1.3, 2003: -0.5,
                             2004: 1.05, 2005: 0.2, 2006: 1.0})
        at = next(i for i, v in enumerate(series) if v.label == "JJA 2003")
        members = forecast.calendar_analogs(series, at=at)
        self.assertFalse({2002, 2003, 2004, 2005} & {m.year for m in members})
        self.assertEqual([m.year for m in members], [2000, 2001, 2006])

    def test_a_winter_start_is_named_for_the_winter(self):
        values = [0.3] * 12 * 3 + [0.5]                  # DJF 2003 is the last
        series = _seasons(values, start_year=2000)
        self.assertEqual(series[-1].label, "DJF 2003")
        members = forecast.calendar_analogs(series)
        self.assertEqual([m.name for m in members], ["2000-01"])  # DJF 2001

    def test_the_hindcast_scores_the_analogs_and_weights_every_method_by_it(self):
        sst, heat = _synthetic_oscillator(600)
        values = [sum(v.value for v in sst[i - 1:i + 2]) / 3
                  for i in range(1, len(sst) - 1)]
        seasons = [SeasonValue(parsers.ONI_SEASONS[m.month - 1], m.year, value)
                   for m, value in zip(sst[1:-1], values)]
        profile = verification.run(seasons, sst, heat, leads=9)
        self.assertFalse(any("not scored" in note for note in profile.notes))
        scored = [lead for lead in profile.leads if "analog" in lead.by_method]
        self.assertTrue(scored, "the analog ensemble was not scored")
        mse = {}
        for name in ("persistence", "recharge", "analog"):
            values = [lead.by_method[name] ** 2 for lead in profile.leads
                      if name in lead.by_method]
            mse[name] = sum(values) / len(values)
        self.assertAlmostEqual(sum(profile.weights.values()), 1.0)
        for name in ("recharge", "analog"):
            self.assertAlmostEqual(profile.weights[name] / profile.weights["persistence"],
                                   mse["persistence"] / mse[name])


class TestWording(unittest.TestCase):

    def test_no_count_is_printed_with_a_lazy_plural(self):
        # "3 consecutive season(s) of RONI", "4 candidate analog(s) were
        # dropped", "1 feed(s) unavailable": every one of these counts is a
        # number the tracker has in hand, so it can say which. String tokens
        # only, a whole word, and a following word or a stop that ends the
        # clause, so the scripts' esc(s) {, String(s).replace and a
        # season_row(s) for s in ... inside an f-string are not counted.
        import tokenize
        lazy = re.compile(r"(?<!\w)[a-z]+\(s\)(?:[.,:](?=\s|$|['\"])|\s+[a-z])")
        found = []
        for path in sorted((Path(__file__).resolve().parents[1] / "elnino").glob("*.py")):
            with path.open(encoding="utf-8") as handle:
                for token in tokenize.generate_tokens(handle.readline):
                    if token.type == tokenize.STRING and lazy.search(token.string):
                        found.append(f"{path.name}:{token.start[0]}")
        self.assertEqual(found, [])


class TestSkillTables(unittest.TestCase):
    """The verification tables score every method the forecast weights.

    The analog ensemble is verified and weighted like the other two, but the
    tables on the page and in the report still listed persistence and the
    recharge model alone - 35% of the forecast with its score out of sight.
    A method with too few forecasts at a lead printed "nan" on the page and
    "0.00", a perfect score, in the report.
    """

    @staticmethod
    def state():
        leads = [
            verification.LeadSkill(1, 0.20, 0.95, 0.01, 600, {
                "persistence": 0.22, "recharge": 0.25, "analog": 0.21}),
            verification.LeadSkill(2, 0.30, 0.90, 0.02, 598, {
                "persistence": 0.33, "analog": 0.31}),
        ]
        return SimpleNamespace(skill=verification.SkillProfile(
            leads, {"DJF": 0.9, "MAM": 0.4}, ["MAM"], 0.5,
            {"persistence": 0.3, "recharge": 0.3, "analog": 0.4}, 2, 70))

    def test_the_page_table_scores_all_three_methods(self):
        html = panels.chart_skill(self.state())
        block = html.split("Table view &mdash; verification by lead", 1)[1]
        block = block.split("</details>", 1)[0]
        heads = [unescape(h) for h in re.findall(r"<th[^>]*>(.*?)</th>", block)]
        self.assertEqual(heads[-4:], ["analog RMSE", "recharge RMSE",
                                      "persistence RMSE", "useful"])
        rows = [dict(zip(heads, (unescape(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", r))))
                for r in re.findall(r"<tr>(.*?)</tr>", block) if "<td" in r]
        self.assertEqual([r["analog RMSE"] for r in rows], ["0.21", "0.31"])
        self.assertEqual([r["recharge RMSE"] for r in rows], ["0.25", "\u2014"])
        self.assertEqual([r["persistence RMSE"] for r in rows], ["0.22", "0.33"])

    def test_a_horizon_at_the_longest_lead_scored_is_a_lower_bound(self):
        # Every lead scored cleared 0.5, so all the hindcast can say is that
        # skill lasts at least that long; "9 months" read as where it ends.
        state = self.state()
        self.assertTrue(state.skill.horizon_is_lower_bound)
        text = " ".join(" ".join(report._section_skill(state)).split())
        self.assertIn("Useful horizon: at least 2 months - correlation is still 0.90 "
                      "at +2, the longest lead scored.", text)
        html = " ".join(panels.chart_skill(state).split())
        self.assertIn("Useful horizon <strong>at least 2 months</strong>, the longest "
                      "lead scored.", html)

    def test_a_horizon_inside_the_leads_scored_is_where_skill_ends(self):
        state = self.state()
        state.skill.leads[1].acc = 0.40
        state.skill.horizon = 1
        self.assertFalse(state.skill.horizon_is_lower_bound)
        text = " ".join(" ".join(report._section_skill(state)).split())
        self.assertIn("Useful horizon: 1 month - correlation falls below 0.5 at +2.", text)
        html = " ".join(panels.chart_skill(state).split())
        self.assertIn("Useful horizon <strong>1 month</strong>; correlation falls below "
                      "0.5 at +2.", html)

    def test_the_report_table_scores_all_three_methods(self):
        lines = report._section_skill(self.state())
        head = next(line.split() for line in lines if line.split()[:1] == ["lead"])
        self.assertEqual(head[5:], ["analog", "rechg", "persist", "useful"])
        rows = {line.split()[0]: line.split() for line in lines
                if line.split()[:1] in (["+1mo"], ["+2mo"])}
        self.assertEqual(rows["+1mo"][5:8], ["0.21", "0.25", "0.22"])
        self.assertEqual(rows["+2mo"][5:8], ["0.31", "-", "0.33"])


class TestEventRecords(unittest.TestCase):
    """A documented record belongs to the episode it describes, and only to it."""

    @staticmethod
    def run_of(first: str, last: str, peak: str) -> Episode:
        order = parsers.ONI_SEASONS

        def number(label):
            season, year = label.split()
            return order.index(season) + 12 * int(year)

        return Episode([
            SeasonValue(order[n % 12], n // 12,
                        2.2 if f"{order[n % 12]} {n // 12}" == peak else 0.8)
            for n in range(number(first), number(last) + 1)
        ])

    def test_a_run_across_two_winters_gets_the_winter_it_peaked_in(self):
        # SON 2014 to AMJ 2016 spans the winters of 2014-15 and 2015-16. It
        # peaked in NDJ 2015, centred on December 2015, so its record is the
        # event that developed in 2015 - not the weak 2014-15 false start.
        episode = self.run_of("SON 2014", "AMJ 2016", peak="NDJ 2015")
        self.assertEqual(episode.name, "2014-16")
        self.assertEqual(history.for_episode(episode).label, "2015-16")

    def test_a_neighbouring_years_record_is_not_borrowed(self):
        # OND 2019 to FMA 2020 contains only the winter of 2019-20, which has
        # no record. The 2018-19 record describes a run that ended in 2019.
        episode = self.run_of("OND 2019", "FMA 2020", peak="DJF 2020")
        self.assertIsNone(history.for_episode(episode))

    def test_a_run_named_differently_from_its_record_still_finds_it(self):
        # JAS 1986 to DJF 1988 is "1986-88" in the index; the literature's
        # 1986-87 event is its first winter, where it peaked.
        episode = self.run_of("JAS 1986", "DJF 1988", peak="DJF 1987")
        self.assertEqual(episode.name, "1986-88")
        self.assertEqual(history.for_episode(episode).label, "1986-87")

    def test_a_summary_never_states_a_strength_class(self):
        # The class is computed from the live index and the two indices
        # disagree: 1965-66 is Very Strong on RONI (+1.99) and Strong on ONI
        # (+1.82); 2023-24 is Moderate on RONI and Very Strong on ONI. A
        # stored word contradicts the table printed above it.
        tier = re.compile(r"\b(weak|moderate|strong)\b", re.I)
        for year, record in history.EVENTS.items():
            with self.subTest(event=record.label):
                self.assertIsNone(tier.search(record.summary), record.summary)
                self.assertIsNone(
                    re.search(r"\b(weak|moderate|strong) event\b", record.lesson, re.I),
                    record.lesson,
                )

    def test_the_report_prints_the_record_of_the_analog_it_names(self):
        from elnino.classify import Analog

        episode = self.run_of("SON 2014", "AMJ 2016", peak="NDJ 2015")
        analog = Analog(episode, 0.1, 2.2, "NDJ 2015", 6, "Very Strong El Nino")
        state = SimpleNamespace(assessment=SimpleNamespace(
            analogs=[analog], index_name="RONI", historic_watch=False,
        ))
        text = "\n".join(report._section_analogs(state))
        self.assertIn("- Drought in Ethiopia", text)
        self.assertNotIn("Little direct impact", text)
        self.assertIn("2014-16 - east-pacific (documented as the 2015-16 event)", text)


class TestReportWrapping(unittest.TestCase):
    """A wrapped note is one note: its bullet is printed once."""

    def test_a_wrapped_bullet_hangs_under_its_text(self):
        for bullet in ("  * ", "      - ", "    - "):
            with self.subTest(bullet=bullet):
                lines = report._wrap("word " * 40, indent=bullet)
                self.assertGreater(len(lines), 1)
                self.assertEqual(lines[0], (bullet + "word " * 40)[:len(lines[0])])
                hang = " " * len(bullet)
                for line in lines[1:]:
                    self.assertTrue(line.startswith(hang + "word"), repr(line))

    def test_a_callout_bar_runs_down_every_line(self):
        lines = report._wrap("word " * 40, indent="  ! ")
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertTrue(line.startswith("  ! word"), repr(line))

    def test_plain_text_keeps_its_indent(self):
        lines = report._wrap("word " * 40, indent="    ")
        for line in lines:
            self.assertTrue(line.startswith("    word"), repr(line))


class TestHazardWatchList(unittest.TestCase):
    """The watch list says what it would take, and says it once."""

    def assessment(self):
        # A central-Pacific event peaking at +1.8. The east-Pacific-gated links
        # carry the flavour penalty: coastal Peru (threshold +1.0) sits at a
        # margin of 1.8 - 1.0 - 0.75 = +0.05, "possible", so it is on watch and
        # needs 1.0 + 0.75 + 0.4 = +2.15 to reach "probable". India is
        # contested and can never get there.
        return impacts.assess(1.8, -1.5, current_index=1.36, months_to_peak=3)

    def test_the_threshold_quoted_includes_the_flavour_penalty(self):
        a = self.assessment()
        gated = [i for i in a.watch + a.active if i.link.flavour == impacts.EP]
        self.assertTrue(gated, "the catalogue has no east-Pacific link")
        peru = next(i for i in a.watch if i.link.region == "Coastal Peru and Ecuador")
        self.assertAlmostEqual(peru.needs, 2.15)
        for item in gated:
            if item.link.confidence == impacts.EMERGING:
                self.assertIsNone(item.needs)
            else:
                self.assertAlmostEqual(item.needs, item.link.min_intensity + 0.75 + 0.4)

    def test_a_contested_link_is_never_promised_a_threshold(self):
        a = self.assessment()
        contested = [i for i in a.watch if i.link.confidence == impacts.EMERGING]
        self.assertTrue(contested)
        for item in contested:
            self.assertIsNone(item.needs)

    def test_each_watch_item_is_printed_once(self):
        a = self.assessment()
        text = report.render(SimpleNamespace(impacts=a), sections=("impacts",))
        for item in a.watch:
            self.assertEqual(text.count(report._ascii(item.link.region)), 1,
                             item.link.region)

    def test_the_hurricane_seasons_count_on_the_printed_value(self):
        seasons = [SeasonValue("ASO", 1977, 0.45), SeasonValue("ASO", 1978, 0.44),
                   SeasonValue("SON", 1979, 0.9)]
        self.assertEqual(cyclones.elnino_years(seasons), (1977,))


class TestCpcAlertStatus(unittest.TestCase):
    """The status is read from CPC's own status line, whatever it says."""

    PAGE = (
        "<html><body><p>Climate Prediction Center: ENSO Diagnostic Discussion</p>"
        "<p>12 March 2027</p>"
        "<p align=\"center\"><strong>ENSO Alert System Status: </strong>\n"
        "<span style=\"color:red\">{status}</span></p>"
        "<p>El Ni&ntilde;o has ended and ENSO-neutral is expected to continue "
        "through the Northern Hemisphere summer.</p></body></html>"
    )

    def _status(self, status: str) -> str:
        return parsers.parse_discussion(self.PAGE.format(status=status))["status"]

    def test_a_final_advisory_is_not_read_as_an_advisory(self):
        self.assertEqual(self._status("Final El Ni&ntilde;o Advisory"),
                         "Final El Nino Advisory")

    def test_a_dual_status_is_kept_whole(self):
        self.assertEqual(
            self._status("El Ni&ntilde;o Advisory / La Ni&ntilde;a Watch"),
            "El Nino Advisory / La Nina Watch")

    def test_not_active_is_a_status(self):
        self.assertEqual(self._status("Not Active"), "Not Active")


if __name__ == "__main__":
    unittest.main(verbosity=2)
