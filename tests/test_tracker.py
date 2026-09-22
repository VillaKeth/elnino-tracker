"""Regression tests for the parsers and the classification chain.

The fixtures reproduce the awkward parts of each NOAA format, so if a feed
changes shape these fail before a bad number reaches the dashboard.
"""

from __future__ import annotations

import json
import math
import re
import sys
import tempfile
import unittest
from datetime import date
from html import escape, unescape
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIXTURES = Path(__file__).resolve().parent / "fixtures"

from elnino import (  # noqa: E402
    alerts, atmosphere, coastline, dashboard, fields, forecast, geo, globe,
    grids, impacts, panels, parsers, pipeline, report, space3d, storage,
    subsurface, verification,
)
from elnino.classify import (  # noqa: E402
    Episode, assess, current_episode, diagnose_scale, find_analogs,
    find_episodes, intensity_tier,
)
from elnino.parsers import MonthValue, SeasonValue  # noqa: E402


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

    def test_rom_forecast_delegates_to_the_production_integrator(self):
        sst, heat = _synthetic_oscillator()
        model = forecast.fit_recharge(sst, heat)
        direct = forecast.recharge_projection(model, 0.4, 0.9, 5, 9)
        through_verification = verification._rom_forecast(model, 5, 0.4, 0.9, 9)
        self.assertEqual(direct, through_verification)

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
                oni_latest=SimpleNamespace(value=over.get("oni", 1.8)),
                scale=SimpleNamespace(flavour_index=over.get("flavour", 3.24)),
            ),
            forecast=SimpleNamespace(
                peak=SimpleNamespace(label=over.get("peak_label", "SON 2026"))),
            impacts=SimpleNamespace(peak_oni=over.get("peak_oni", 2.27)),
        )

    def payload(self, html: str) -> dict:
        """Pull the embedded payload back out the way the browser does."""
        raw = html.split("data-globe='", 1)[1].split("'>", 1)[0]
        return json.loads(unescape(raw))

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
        links = globe.dossier(peak_oni=2.27, current_oni=0.3,
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

    def test_every_report_section_renders(self):
        for section in report.SECTIONS:
            text = report.render(self.state, sections=(section,))
            self.assertTrue(text.strip(), f"{section} rendered empty")

    def test_report_is_ascii_and_fits_eighty_columns(self):
        text = report.render(self.state)
        for number, line in enumerate(text.splitlines(), 1):
            self.assertLessEqual(len(line), report.WIDTH, f"line {number} too wide")
            self.assertTrue(line.isascii(), f"line {number} is not ASCII: {line!r}")

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
        self.assertEqual(restored["schema"], 4)
        for key in ("oni", "power_index", "subsurface", "atmosphere", "forecast",
                    "skill", "alerts", "impacts", "feeds"):
            self.assertIn(key, restored)

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

    def test_skill_degrades_with_lead(self):
        leads = self.state.skill.leads
        self.assertLess(leads[0].rmse, leads[-1].rmse)


if __name__ == "__main__":
    unittest.main(verbosity=2)
