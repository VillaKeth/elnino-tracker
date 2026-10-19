"""The ocean as of a day or two ago: OISST's preliminary analysis for the maps,
the day-by-day Nino boxes and the Hovmoller's latest rows, a gridded feed
downloaded again only when its dataset has a new day, and a file only when its
server says it changed."""

from __future__ import annotations

import email.message
import gzip
import hashlib
import http.client
import http.server
import json
import math
import re
import socketserver
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.parse
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from elnino import (dashboard, daily, fields, grids, parsers, pipeline, report,  # noqa: E402
                    sources, worldmap)


def _query(url: str) -> str:
    return urllib.parse.unquote(url.partition("?")[2])


class TestOisstProducts(unittest.TestCase):
    """Which of OISST's two products each spatial feed asks for."""

    def test_the_maps_ask_the_preliminary_analysis_and_the_final_alike(self):
        for key in ("sst_pacific", "sst_global"):
            with self.subTest(key=key):
                source = sources.SOURCES_BY_KEY[key]
                self.assertTrue(source.url.startswith(sources.OISST_NRT + "?"), source.url)
                self.assertTrue(source.final.startswith(sources.OISST_FINAL + "?"),
                                source.final)
                # The same subset of either product: only the dataset differs.
                self.assertEqual(_query(source.url), _query(source.final))
                self.assertIn("[last]", _query(source.url))

    def test_the_two_products_are_two_datasets_on_one_server(self):
        self.assertEqual(sources.OISST_FINAL,
                         f"{sources.COASTWATCH}/griddap/ncdcOisst21Agg.csv")
        self.assertEqual(sources.OISST_NRT,
                         f"{sources.COASTWATCH}/griddap/ncdcOisst21NrtAgg.csv")

    def test_the_hovmoller_keeps_the_final_record_and_takes_its_latest_days_apart(self):
        record = sources.SOURCES_BY_KEY["sst_hovmoller"]
        recent = sources.SOURCES_BY_KEY["sst_hovmoller_recent"]
        self.assertTrue(record.url.startswith(sources.OISST_FINAL + "?"))
        # A week apart back from the final's latest day, so its last row is
        # that day and every preliminary day after the record is one the
        # final does not have; sixty-nine weeks, sixteen months.
        self.assertEqual(_query(record.url), f"anom[last-483:7:last][(0.0)]{sources._EQ_STRIP}")
        self.assertTrue(recent.url.startswith(sources.OISST_NRT + "?"))
        # Every day of the last four weeks, on the record's own strip: the
        # preliminary product has gaps, so its days are picked by date, never
        # by a stride that a missing day would knock off the week.
        self.assertIn("anom[last-27:1:last][(0.0)]", _query(recent.url))
        self.assertTrue(_query(recent.url).endswith(sources._EQ_STRIP))
        self.assertEqual(recent.final, "")

    def test_the_daily_boxes_ask_for_the_map_s_own_cells(self):
        record = sources.SOURCES_BY_KEY["nino_daily"]
        recent = sources.SOURCES_BY_KEY["nino_daily_recent"]
        self.assertTrue(record.url.startswith(sources.OISST_FINAL + "?"))
        self.assertTrue(recent.url.startswith(sources.OISST_NRT + "?"))
        # Half a degree, on the points the Pacific map samples (29.875S and
        # 100.125E onward), so a day both carry has the same box means in both.
        cells = "[(-9.875):2:(4.625)][(160.125):2:(279.625)]"
        self.assertEqual(_query(record.url), f"anom[last-89:1:last][(0.0)]{cells}")
        self.assertEqual(_query(recent.url), f"anom[last-27:1:last][(0.0)]{cells}")
        self.assertIn("[(-30):2:(30)][(100):2:(300)]", _query(sources.SOURCES_BY_KEY["sst_pacific"].url))

    def test_every_new_feed_is_spatial_and_says_what_it_is(self):
        for key in ("sst_hovmoller_recent", "nino_daily", "nino_daily_recent",
                    "iod_daily", "iod_daily_recent"):
            with self.subTest(key=key):
                source = sources.SOURCES_BY_KEY[key]
                self.assertEqual(source.tier, "spatial")
                self.assertFalse(source.critical)
                self.assertTrue(source.name and source.note and source.cadence)

    def test_the_rolling_windows_of_days_are_not_archived(self):
        # Each day's download of a window repeats all but a day of the day
        # before's, and NOAA keeps every day of both products itself; so does
        # each day's of LongPaddock's daily SOI, the whole record since 1999,
        # which it keeps itself, and each day's of CCMP's last 180 days of
        # winds, every analysis of which Remote Sensing Systems keeps.
        windows = {"sst_hovmoller_recent", "nino_daily", "nino_daily_recent",
                   "iod_daily", "iod_daily_recent", "soi_daily", "wind_daily"}
        self.assertEqual({s.key for s in sources.SOURCES if not s.archive}, windows)

    def test_ncei_s_own_erddap_serves_the_two_products_as_well(self):
        self.assertEqual(sources.NCEI, "https://www.ncei.noaa.gov/erddap")
        self.assertEqual(sources.NCEI_FINAL,
                         f"{sources.NCEI}/griddap/ncdc_oisst_v2_avhrr_by_time_zlev_lat_lon.csv")
        self.assertEqual(sources.NCEI_NRT,
                         f"{sources.NCEI}/griddap/ncdc_oisst_v2_avhrr_prelim_by_time_zlev_lat_lon.csv")

    def test_each_oisst_product_falls_back_on_the_same_subset_of_it_at_ncei(self):
        ncei = {sources.OISST_NRT: sources.NCEI_NRT, sources.OISST_FINAL: sources.NCEI_FINAL}
        for source in sources.SOURCES:
            for url, fallback in ((source.url, source.fallback),
                                  (source.final, source.final_fallback)):
                with self.subTest(key=source.key, final=url == source.final):
                    base = url.partition("?")[0]
                    if base not in ncei:
                        # Only OISST has a final analysis behind a feed, so
                        # no other feed has a second server for one.
                        if url == source.final:
                            self.assertEqual(fallback, ())
                        continue
                    windows = (("[0:1:last]", "[1:1:last]") if "[last-27:1:last]" in _query(url)
                               else ("[last-27:1:last]",))
                    self.assertEqual(
                        [(address.partition("?")[0], _query(address)) for address in fallback],
                        [(ncei[base], _query(url).replace("[last-27:1:last]", days))
                         for days in windows])

    def test_ncei_s_preliminary_is_asked_for_all_its_days_then_all_but_the_oldest(self):
        # It holds only the days its final has not replaced, about two weeks,
        # and refuses a window that reaches back past its first: CoastWatch's
        # last 28 days are an error there. Its oldest day's file is taken away
        # when the final replaces it, hours before its ERDDAP stops listing
        # the day, and asking for it meanwhile is an error too (on 14 October,
        # 29 September's), so then it is asked for the rest.
        for key in ("sst_hovmoller_recent", "nino_daily_recent", "iod_daily_recent"):
            with self.subTest(key=key):
                fallback = sources.SOURCES_BY_KEY[key].fallback
                self.assertEqual([address.partition("?")[0] for address in fallback],
                                 [sources.NCEI_NRT, sources.NCEI_NRT])
                self.assertEqual([_query(address).partition("[(0.0)]")[0] for address in fallback],
                                 ["anom[0:1:last]", "anom[1:1:last]"])

    def test_oisst_and_sea_level_have_a_second_server(self):
        # TAO's moorings have none that serves their data: PMEL's ERDDAP sends
        # a request for the moorings back to CoastWatch.
        seconded = {s.key for s in sources.SOURCES if s.fallback or s.final_fallback}
        self.assertEqual(seconded, {"sst_pacific", "sst_global", "sst_hovmoller",
                                    "sst_hovmoller_recent", "nino_daily", "nino_daily_recent",
                                    "iod_daily", "iod_daily_recent",
                                    "ssh_pacific", "ssh_hovmoller"})

    def test_a_feed_with_two_servers_names_both_above_the_address_that_served(self):
        agency = {"sst": "NOAA NCEI, via CoastWatch's ERDDAP or its own",
                  "nin": "NOAA NCEI, via CoastWatch's ERDDAP or its own",
                  "iod": "NOAA NCEI, via CoastWatch's ERDDAP or its own",
                  "ssh": "NOAA CoastWatch, at its own ERDDAP or its West Coast node's"}
        for source in sources.SOURCES:
            if source.fallback:
                with self.subTest(key=source.key):
                    self.assertEqual(source.agency, agency[source.key[:3]])


class TestProbe(unittest.TestCase):
    """The question asked before a gridded download: has the dataset a new day?"""

    def test_a_griddap_subset_is_probed_at_its_dataset_s_latest_time(self):
        url = sources.SOURCES_BY_KEY["sst_global"].url
        self.assertEqual(sources.probe_url(url), sources.OISST_NRT + "?time%5Blast%5D")
        final = sources.SOURCES_BY_KEY["sst_global"].final
        self.assertEqual(sources.probe_url(final), sources.OISST_FINAL + "?time%5Blast%5D")

    def test_any_other_feed_has_no_probe(self):
        for key in ("oni", "tao_mesh", "nhc_current", "weekly_sst"):
            with self.subTest(key=key):
                self.assertEqual(sources.probe_url(sources.SOURCES_BY_KEY[key].url), "")
        self.assertEqual(sources.probe_url("https://example.invalid/griddap/x.csv"), "")


LAST = "time\nUTC\n2026-10-12T12:00:00Z\n"
LATER = "time\nUTC\n2026-10-13T12:00:00Z\n"
NEXT = "time\nUTC\n2026-10-14T12:00:00Z\n"
FINAL_LAST = "time\nUTC\n2026-09-28T12:00:00Z\n"
FINAL_BEFORE = "time\nUTC\n2026-09-27T12:00:00Z\n"
STALLED = "time\nUTC\n2026-09-01T12:00:00Z\n"
FIELD = "time,zlev,latitude,longitude,anom\nUTC,m,degrees_north,degrees_east,degree_C\n"


def csv(tag: str) -> str:
    """ERDDAP's CSV of a subset of one row, told apart from others by ``tag``."""
    return FIELD + f"2026-10-13T12:00:00Z,0.0,0.125,180.125,{tag}\n"


# What a server answers when asked whether a file changed and it has not.
NOT_MODIFIED = object()


def answering(answers, asked=None, asking=None, missing=None):
    """An address's answers from a table, as ``sources._http_get`` gives them:
    text, or an ``Answer`` with its server's tag and date, an Exception raised,
    or NOT_MODIFIED, which a server sends only to a request that asked. An
    address not in the table fails, with ``missing`` if given. Each URL is
    noted in ``asked``, and the headers that asked in ``asking``."""
    def get(url, headers=None, wait=None):
        if asked is not None:
            asked.append(url)
        if asking is not None:
            asking.append(dict(headers or {}))
        answer = answers.get(url, RuntimeError(missing or f"no route to {url}"))
        if isinstance(answer, Exception):
            raise answer
        if answer is NOT_MODIFIED:
            if not headers:
                raise RuntimeError("HTTPError: HTTP Error 304: Not Modified")
            return None
        return answer if isinstance(answer, sources.Answer) else sources.Answer(answer)
    return get


class _Fetching:
    """A feed fetched with each address answered from a table, its copies kept
    in a directory of their own. The test case sets ``source``."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name)
        self.asked: list[str] = []
        self.asking: list[dict] = []

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, answers, offline=False):
        """Fetch with each URL answered from ``answers`` (see ``answering``)."""
        get = answering(answers, self.asked, self.asking)
        with mock.patch.object(sources, "_http_get", side_effect=get):
            return sources.fetch(self.source, self.raw, offline=offline)

    def probe(self, url):
        return sources.probe_url(url)

    def meta(self, name="grid"):
        return json.loads((self.raw / f"{name}.meta.json").read_text(encoding="utf-8"))

    def kept(self, name="grid"):
        return (self.raw / f"{name}.cache").read_text(encoding="utf-8")


class TestAnUnfilledDay(_Fetching, unittest.TestCase):
    """A day a dataset lists before its values are in it, every row of it NaN,
    as NCEI's preliminary OISST listed 12 October on the evening of the 14th."""

    URL = "https://example.invalid/erddap/griddap/nrt.csv?anom%5Blast%5D"

    def setUp(self):
        super().setUp()
        self.source = sources.Source(key="grid", name="grid", url=self.URL,
                                     agency="test", cadence="daily")

    @staticmethod
    def rows(*days):
        """ERDDAP's CSV of two cells a day, each day's value, NaN for None."""
        return FIELD + "".join(
            f"{day}T12:00:00Z,0.0,0.125,{lon},{'NaN' if value is None else value}\n"
            for day, value in days for lon in (180.125, 180.375))

    def test_a_map_of_a_day_without_values_is_no_answer_and_its_copy_serves(self):
        kept = self.rows(("2026-10-13", 1.5))
        self.fetch({self.probe(self.URL): LATER, self.URL: kept})
        got = self.fetch({self.probe(self.URL): NEXT, self.URL: self.rows(("2026-10-14", None))})
        self.assertEqual((got.text, got.from_cache), (kept, True))
        self.assertIn(f"its answer has no values ({self.URL})", got.warnings[0])
        self.assertEqual((self.kept(), self.meta()["probe"]), (kept, "2026-10-13T12:00:00Z"))

    def test_a_window_ending_on_a_day_without_values_is_asked_again_until_they_come(self):
        unfilled = self.rows(("2026-10-13", 1.5), ("2026-10-14", None))
        got = self.fetch({self.probe(self.URL): NEXT, self.URL: unfilled})
        self.assertEqual((got.text, got.from_cache, got.warnings), (unfilled, False, []))
        # Kept at the last day it has values for, not the day its dataset said.
        self.assertEqual(self.meta()["probe"], "2026-10-13T12:00:00Z")
        filled = self.rows(("2026-10-13", 1.5), ("2026-10-14", 1.7))
        got = self.fetch({self.probe(self.URL): NEXT, self.URL: filled})
        self.assertEqual((got.text, got.unchanged), (filled, False))
        self.assertEqual(self.meta()["probe"], "2026-10-14T12:00:00Z")
        self.asked.clear()
        self.assertTrue(self.fetch({self.probe(self.URL): NEXT}).unchanged)
        self.assertEqual(self.asked, [self.probe(self.URL)])

    def test_a_value_counts_in_any_of_an_answer_s_variables_whatever_its_axes(self):
        # Sea level's answers have no depth; the maps' carry SST beside the
        # anomaly; NCEI names its depth "depth" where CoastWatch says "zlev".
        both = ("time,latitude,longitude,anom,sst\nUTC,degrees_north,degrees_east,C,C\n"
                "2026-10-13T12:00:00Z,0.125,180.125,NaN,28.5\n"
                "2026-10-14T12:00:00Z,0.125,180.125,NaN,NaN\n")
        self.assertEqual(sources._last_times(both), ("2026-10-14T12:00:00Z", "2026-10-13T12:00:00Z"))
        ncei = ("time,depth,latitude,longitude,anom\nUTC,m,degrees_north,degrees_east,Celsius\n"
                "2026-10-12T12:00:00Z,0.0,0.125,180.125,{}\n"
                "2026-10-12T12:00:00Z,0.0,0.375,180.125,NaN\n")
        self.assertEqual(sources._last_times(ncei.format("NaN")), ("2026-10-12T12:00:00Z", ""))
        # A day whose last cell is land is a day with values all the same.
        self.assertEqual(sources._last_times(ncei.format("0.0")),
                         ("2026-10-12T12:00:00Z", "2026-10-12T12:00:00Z"))


class TestFetchFallbackAndProbe(_Fetching, unittest.TestCase):
    """A gridded feed's preliminary product, its final one, and the copy kept of each."""

    PRIMARY = "https://example.invalid/erddap/griddap/nrt.csv?anom%5Blast%5D"
    FINAL = "https://example.invalid/erddap/griddap/final.csv?anom%5Blast%5D"

    def setUp(self):
        super().setUp()
        self.source = sources.Source(key="grid", name="grid", url=self.PRIMARY,
                                     agency="test", cadence="daily", final=self.FINAL)

    def hour(self, field="a", day=LATER):
        """An hour like most: the preliminary at 13 October, the final at 28 September."""
        return {self.probe(self.PRIMARY): day, self.probe(self.FINAL): FINAL_LAST,
                self.PRIMARY: csv(field), self.FINAL: csv("final")}

    def test_the_preliminary_serves_when_its_latest_day_is_the_later(self):
        got = self.fetch(self.hour())
        self.assertEqual(self.asked, [self.probe(self.PRIMARY), self.probe(self.FINAL), self.PRIMARY])
        self.assertTrue(got.ok)
        self.assertEqual((got.text, got.url, got.from_cache, got.unchanged),
                         (csv("a"), self.PRIMARY, False, False))
        self.assertEqual(got.warnings, [])
        self.assertEqual((self.meta()["url"], self.meta()["probe"]),
                         (self.PRIMARY, "2026-10-13T12:00:00Z"))
        self.assertFalse((self.raw / "grid.final.cache").exists())

    def test_the_final_serves_when_the_preliminary_fails_and_says_so(self):
        got = self.fetch({self.probe(self.FINAL): FINAL_LAST, self.FINAL: csv("b")})
        self.assertTrue(got.ok)
        self.assertEqual((got.text, got.url, got.from_cache), (csv("b"), self.FINAL, False))
        (warning,) = got.warnings
        self.assertTrue(warning.startswith("no route to"), warning)
        self.assertIn(f"served by {self.FINAL}", warning)
        # A preliminary whose probe fails is not downloaded as well: the
        # dataset that cannot say its latest day is not asked for the day.
        self.assertNotIn(self.PRIMARY, self.asked)
        # The final's copy is its own, archived under its own name, and the
        # preliminary's is not touched.
        self.assertEqual(self.kept("grid.final"), csv("b"))
        self.assertEqual(self.meta("grid.final")["url"], self.FINAL)
        self.assertFalse((self.raw / "grid.cache").exists())
        self.assertEqual([p.name.rpartition("_")[0] for p in (self.raw / "archive").iterdir()],
                         ["grid.final"])

    def test_the_final_serves_when_the_preliminary_has_fallen_behind_it(self):
        # The preliminary stalls at 1 September while the final reaches the 28th.
        got = self.fetch(self.hour(day=STALLED))
        self.assertEqual((got.text, got.url), (csv("final"), self.FINAL))
        self.assertNotIn(self.PRIMARY, self.asked)
        (warning,) = got.warnings
        self.assertIn("2026-09-01", warning)
        self.assertIn(self.PRIMARY, warning)

    def test_a_preliminary_saying_no_day_beside_a_dated_final_is_said_to_have_said_none(self):
        got = self.fetch({self.probe(self.PRIMARY): "", self.probe(self.FINAL): FINAL_LAST,
                          self.PRIMARY: csv("a"), self.FINAL: csv("b")})
        self.assertEqual((got.text, got.url), (csv("b"), self.FINAL))
        self.assertEqual(got.warnings,
                         [f"latest day not said ({self.PRIMARY}); served by {self.FINAL}"])

    def test_on_a_day_both_carry_the_final_s_analysis_serves(self):
        got = self.fetch(self.hour(day=FINAL_LAST))
        self.assertEqual(got.url, self.FINAL)

    def test_with_no_day_said_by_either_the_preliminary_serves(self):
        # Were ERDDAP to answer the probe in some other form, the maps would
        # stay on the preliminary and be downloaded every run.
        answers = {self.probe(self.PRIMARY): "", self.probe(self.FINAL): "",
                   self.PRIMARY: csv("a"), self.FINAL: csv("b")}
        self.assertEqual(self.fetch(answers).url, self.PRIMARY)
        self.assertEqual(self.fetch(answers).url, self.PRIMARY)

    def test_the_preliminary_s_own_copy_stands_in_when_its_download_fails(self):
        self.fetch(self.hour())
        # An hour later its dataset says the 14th but the subset fails. Its
        # copy of the 13th is still two weeks ahead of the final: it serves,
        # and the final is not downloaded over it.
        answers = self.hour(day=NEXT)
        answers[self.PRIMARY] = RuntimeError("HTTP Error 500")
        self.asked.clear()
        got = self.fetch(answers)
        self.assertNotIn(self.FINAL, self.asked)
        self.assertTrue(got.from_cache)
        self.assertEqual((got.text, got.url), (csv("a"), self.PRIMARY))
        self.assertIn("HTTP Error 500", got.warnings[0])
        self.assertEqual(self.kept(), csv("a"))
        self.assertEqual(self.meta()["probe"], "2026-10-13T12:00:00Z")
        # And with everything down the copy of the 13th serves still.
        got = self.fetch({})
        self.assertEqual((got.text, got.url, got.from_cache), (csv("a"), self.PRIMARY, True))

    def test_a_copy_of_an_earlier_day_than_the_final_s_gives_way_to_it(self):
        self.fetch(self.hour(day=STALLED) | {self.probe(self.FINAL): RuntimeError("down")})
        self.assertEqual(self.meta()["probe"], "2026-09-01T12:00:00Z")
        answers = self.hour(day=NEXT)
        answers[self.PRIMARY] = RuntimeError("HTTP Error 500")
        got = self.fetch(answers)
        self.assertEqual((got.text, got.url, got.from_cache), (csv("final"), self.FINAL, False))

    def test_each_product_keeps_its_own_copy_and_the_later_day_serves_from_them(self):
        self.fetch({self.probe(self.FINAL): FINAL_LAST, self.FINAL: csv("b")})
        self.fetch(self.hour())
        self.assertEqual((self.kept(), self.kept("grid.final")), (csv("a"), csv("b")))
        got = self.fetch({})
        self.assertEqual((got.text, got.url, got.from_cache), (csv("a"), self.PRIMARY, True))
        got = self.fetch({}, offline=True)
        self.assertEqual((got.text, got.url, got.from_cache), (csv("a"), self.PRIMARY, True))

    def test_the_cache_serves_when_both_fail(self):
        self.fetch(self.hour())
        got = self.fetch({})
        self.assertTrue(got.ok)
        self.assertTrue(got.from_cache)
        self.assertEqual(got.text, csv("a"))
        self.assertEqual(got.url, self.PRIMARY)
        self.assertIn("live fetch failed", got.warnings[0])

    def test_nothing_at_all_is_an_error_naming_both(self):
        got = self.fetch({})
        self.assertFalse(got.ok)
        self.assertIn("nrt.csv", got.error)
        self.assertIn("final.csv", got.error)
        self.assertTrue(got.error.startswith("no route to"), got.error)

    def test_an_unchanged_dataset_is_not_downloaded_again(self):
        first = self.fetch(self.hour())
        self.asked.clear()
        again = self.fetch(self.hour(field="changed?"))
        self.assertEqual(self.asked, [self.probe(self.PRIMARY), self.probe(self.FINAL)])
        self.assertTrue(again.ok)
        self.assertEqual(again.text, csv("a"))
        self.assertTrue(again.unchanged)
        self.assertFalse(again.from_cache)
        self.assertEqual(again.url, self.PRIMARY)
        self.assertEqual(again.fetched_at, first.fetched_at)
        self.assertEqual(again.sha256, first.sha256)
        self.assertEqual(again.warnings, [])

    def test_a_new_day_is_downloaded(self):
        self.fetch(self.hour())
        again = self.fetch(self.hour(field="b", day=NEXT))
        self.assertEqual(again.text, csv("b"))
        self.assertFalse(again.unchanged)
        self.assertEqual(self.meta()["probe"], "2026-10-14T12:00:00Z")

    def test_a_copy_the_old_single_cache_kept_is_taken_for_the_product_it_came_from(self):
        # Before each product kept its own copy, the one cache could hold the
        # final's. With everything down it serves as the final's...
        old = csv("b").encode("utf-8")
        (self.raw / "grid.cache").write_bytes(old)
        (self.raw / "grid.meta.json").write_text(json.dumps({
            "url": self.FINAL, "fetched_at": "2026-10-12T13:00:00+00:00",
            "sha256": hashlib.sha256(old).hexdigest(), "probe": "2026-10-12T12:00:00Z"}),
            encoding="utf-8")
        got = self.fetch({})
        self.assertEqual((got.text, got.url, got.from_cache), (csv("b"), self.FINAL, True))
        # ...and the preliminary's dataset at that very day (it cannot be, but
        # the stamp alone must not be what decides) is downloaded, not taken.
        again = self.fetch({self.probe(self.PRIMARY): LAST, self.PRIMARY: csv("a")})
        self.assertEqual(again.text, csv("a"))
        self.assertFalse(again.unchanged)

    def test_a_changed_request_is_downloaded_whatever_the_stamp(self):
        self.fetch({self.probe(self.PRIMARY): LAST, self.PRIMARY: csv("a")})
        moved = self.PRIMARY.replace("last", "last-1")
        self.source = sources.Source(key="grid", name="grid", url=moved,
                                     agency="test", cadence="daily")
        again = self.fetch({self.probe(moved): LAST, moved: csv("c")})
        self.assertEqual(again.text, csv("c"))

    def test_a_missing_cache_file_is_downloaded_even_when_the_stamp_matches(self):
        self.fetch(self.hour())
        (self.raw / "grid.cache").unlink()
        again = self.fetch(self.hour(field="a2"))
        self.assertEqual(again.text, csv("a2"))

    def test_a_copy_that_is_not_what_its_record_was_written_for_is_downloaded_again(self):
        self.fetch(self.hour())
        (self.raw / "grid.cache").write_bytes(FIELD.encode("utf-8"))
        again = self.fetch(self.hour(field="a2"))
        self.assertEqual(again.text, csv("a2"))
        self.assertFalse(again.unchanged)

    def test_a_copy_that_is_not_what_its_record_was_written_for_is_not_served(self):
        self.fetch(self.hour())
        (self.raw / "grid.cache").write_bytes(b"time,zlev")
        got = self.fetch({})
        self.assertFalse(got.ok)
        self.assertIn("does not match its record", got.error)

    def test_an_answer_that_is_not_erddap_s_csv_is_not_kept(self):
        for name, answer in (("a page", "<html><body>Service unavailable</body></html>"),
                             ("no rows", FIELD), ("nothing", ""),
                             ("a row cut short", FIELD + "2026-10-14T12:00:00Z,0.0,0.1"),
                             ("an error after the rows", csv("b") + "Error: Internal Server Error\n")):
            with self.subTest(name):
                self.fetch(self.hour())
                answers = self.hour(day=NEXT)
                answers[self.PRIMARY] = answer
                got = self.fetch(answers)
                # The copy of the 13th serves and keeps its record, so the
                # next hour downloads the 14th.
                self.assertEqual((got.text, got.from_cache), (csv("a"), True))
                self.assertIn("not ERDDAP's CSV", got.warnings[0])
                self.assertEqual(self.meta()["probe"], "2026-10-13T12:00:00Z")
                self.assertEqual(self.fetch(self.hour(field="b", day=NEXT)).text, csv("b"))
                for path in self.raw.glob("grid.*"):
                    path.unlink()

    def test_an_empty_answer_from_any_feed_is_a_failure_and_its_copy_stands_in(self):
        plain = "https://example.invalid/data/oni.txt"
        self.source = sources.Source(key="plain", name="plain", url=plain,
                                     agency="test", cadence="monthly")
        self.assertEqual(self.fetch({plain: "x\n"}).text, "x\n")
        got = self.fetch({plain: " \n"})
        self.assertEqual((got.text, got.from_cache), ("x\n", True))
        self.assertIn("its answer is empty", got.warnings[0])
        (self.raw / "plain.cache").unlink()
        got = self.fetch({plain: ""})
        self.assertFalse(got.ok)
        self.assertEqual(got.error, f"its answer is empty ({plain})")

    def test_a_probe_answering_no_day_does_not_count_as_unchanged(self):
        self.fetch({self.probe(self.PRIMARY): "", self.PRIMARY: csv("a")})
        again = self.fetch({self.probe(self.PRIMARY): "", self.PRIMARY: csv("b")})
        self.assertEqual(again.text, csv("b"))
        self.assertFalse(again.unchanged)

    def test_the_text_serves_though_no_copy_of_it_can_be_kept(self):
        with mock.patch.object(sources.os, "replace", side_effect=OSError("disk full")):
            got = self.fetch(self.hour())
        self.assertEqual((got.text, got.url, got.from_cache), (csv("a"), self.PRIMARY, False))
        self.assertTrue(any("disk full" in w for w in got.warnings), got.warnings)
        self.assertEqual(sorted(p.name for p in self.raw.iterdir()), ["archive"])

    def test_an_archive_that_cannot_be_written_costs_only_a_warning(self):
        (self.raw / "archive").write_text("not a directory", encoding="utf-8")
        got = self.fetch(self.hour())
        self.assertEqual((got.text, got.url, got.from_cache), (csv("a"), self.PRIMARY, False))
        self.assertTrue(any("archived no copy" in w for w in got.warnings), got.warnings)
        self.assertNotIn(self.FINAL, self.asked)
        self.assertEqual(self.kept(), csv("a"))

    def test_a_feed_kept_out_of_the_archive_writes_no_dated_copy(self):
        self.source = replace(self.source, archive=False)
        got = self.fetch(self.hour())
        self.assertEqual(got.warnings, [])
        self.assertFalse((self.raw / "archive").exists())

    def test_offline_reads_the_cache_and_asks_nothing(self):
        self.fetch(self.hour())
        self.asked.clear()
        got = self.fetch({}, offline=True)
        self.assertEqual(self.asked, [])
        self.assertTrue(got.from_cache)
        self.assertEqual(got.text, csv("a"))

    def test_a_feed_without_a_probe_or_final_is_fetched_as_before(self):
        plain = "https://example.invalid/data/oni.txt"
        self.source = sources.Source(key="plain", name="plain", url=plain,
                                     agency="test", cadence="monthly")
        got = self.fetch({plain: "x\n"})
        self.assertEqual(self.asked, [plain])
        self.assertEqual((got.text, got.url, got.unchanged), ("x\n", plain, False))
        self.fetch({plain: "x\n"})
        self.assertEqual(self.asked, [plain, plain])


class TestConditionalRequests(_Fetching, unittest.TestCase):
    """A file is downloaded again only when its server says it changed: the
    date it gave the copy is sent back (If-Modified-Since), or with none, its
    tag (If-None-Match), and 304 Not Modified serves the copy, as current as a
    download. HURDAT2's two files are 11 MB, and were downloaded every run."""

    URL = "https://example.invalid/data/hurdat2.txt"
    TAG, DATE = '"6be750-65bb41b1a4eb7"', "Thu, 17 Sep 2026 21:02:47 GMT"
    ASKING = {"If-Modified-Since": DATE}

    def setUp(self):
        super().setUp()
        self.source = sources.Source(key="file", name="file", url=self.URL,
                                     agency="test", cadence="annual")

    def test_a_tagged_and_dated_file_is_asked_whether_it_changed(self):
        first = self.fetch({self.URL: sources.Answer("AL011851\n", self.TAG, self.DATE)})
        record = self.meta("file")
        self.assertEqual((record["etag"], record["modified"]), (self.TAG, self.DATE))
        got = self.fetch({self.URL: NOT_MODIFIED})
        self.assertEqual(self.asking, [{}, self.ASKING])
        self.assertEqual((got.text, got.unchanged, got.from_cache, got.warnings, got.error),
                         ("AL011851\n", True, False, [], None))
        # Unchanged since it was downloaded, as a gridded feed with no new day
        # is, and its record as the download left it.
        self.assertEqual((got.fetched_at, got.url, got.sha256), (first.fetched_at, self.URL, first.sha256))
        self.assertEqual(self.meta("file"), record)

    def downloaded(self, change):
        """The file downloaded, tagged and dated, its record then changed by
        ``change``."""
        self.fetch({self.URL: sources.Answer("AL011851\n", self.TAG, self.DATE)})
        record = self.meta("file")
        change(record)
        (self.raw / "file.meta.json").write_text(json.dumps(record), encoding="utf-8")

    @staticmethod
    def ago(span):
        def change(record):
            record["fetched_at"] = (datetime.now(timezone.utc) - span).isoformat(timespec="seconds")
        return change

    def test_a_copy_a_day_after_its_download_is_asked_for_whole(self):
        # A file put back from a backup keeps the backup's older date, so a
        # copy of what it replaced would be told it has not changed until the
        # file next did, a month for ONI. A server's word serves a day.
        for span in (timedelta(days=1), timedelta(days=3)):
            with self.subTest(span=span):
                self.downloaded(self.ago(span))
                got = self.fetch({self.URL: sources.Answer("AL011851 restored\n", self.TAG, self.DATE)})
                self.assertEqual(self.asking[-1], {})
                self.assertEqual((got.text, got.unchanged), ("AL011851 restored\n", False))
                self.assertEqual(self.kept("file"), "AL011851 restored\n")

    def test_a_copy_under_a_day_old_is_asked_whether_it_changed(self):
        for span in (timedelta(0), timedelta(hours=23, minutes=59)):
            with self.subTest(span=span):
                self.downloaded(self.ago(span))
                got = self.fetch({self.URL: NOT_MODIFIED})
                self.assertEqual((self.asking[-1], got.text, got.unchanged), (self.ASKING, "AL011851\n", True))

    def test_a_copy_whose_record_says_no_fair_time_is_asked_for_whole(self):
        # No time, not a time, one without its zone, or one after now, as a
        # clock put back would give.
        hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
        for stamp in (None, "a while ago", hour_ago.replace(tzinfo=None).isoformat(timespec="seconds"),
                      (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(timespec="seconds")):
            with self.subTest(stamp=stamp):
                self.downloaded(lambda record: record.pop("fetched_at") if stamp is None
                                else record.update(fetched_at=stamp))
                got = self.fetch({self.URL: "AL011851\n"})
                self.assertEqual((self.asking[-1], got.unchanged), ({}, False))

    def test_a_file_changed_since_replaces_its_copy_and_its_tag(self):
        self.fetch({self.URL: sources.Answer("AL011851\n", self.TAG, self.DATE)})
        got = self.fetch({self.URL: sources.Answer("AL011851\nAL021851\n", '"7c0"')})
        self.assertEqual(self.asking[-1], self.ASKING)
        self.assertEqual((got.text, got.unchanged), ("AL011851\nAL021851\n", False))
        self.assertEqual(self.kept("file"), "AL011851\nAL021851\n")
        # The new answer's own tag, and no date, as it gave none.
        self.assertEqual(self.meta("file")["etag"], '"7c0"')
        self.assertNotIn("modified", self.meta("file"))

    def test_a_file_its_server_neither_tags_nor_dates_is_asked_for_whole(self):
        self.fetch({self.URL: "x\n"})
        got = self.fetch({self.URL: "x\n"})
        self.assertEqual(self.asking, [{}, {}])
        self.assertEqual((got.unchanged, "etag" in self.meta("file"), "modified" in self.meta("file")),
                         (False, False, False))

    def test_a_file_with_a_date_is_asked_by_its_date_alone(self):
        # A server weighs a tag over a date, and a tag can be one it never
        # matches again: PSL's, which Apache's compression ends in "-gzip",
        # was answered in full when asked by both, and 304 by its date alone
        # (16 October 2026), as every server here that gives a date answers.
        url = "https://psl.invalid/enso/mei/data/meiv2.data"
        self.source = sources.Source(key="mei", name="mei", url=url, agency="test", cadence="monthly")
        self.fetch({url: sources.Answer("1979 -0.05\n", '"15df-65d2d75c728d3-gzip"', self.DATE)})
        got = self.fetch({url: NOT_MODIFIED})
        self.assertEqual(self.asking, [{}, {"If-Modified-Since": self.DATE}])
        self.assertEqual((got.text, got.unchanged), ("1979 -0.05\n", True))

    def test_a_tag_or_a_date_alone_is_sent_back_alone(self):
        self.fetch({self.URL: sources.Answer("x\n", etag=self.TAG)})
        self.fetch({self.URL: NOT_MODIFIED})
        self.fetch({self.URL: sources.Answer("y\n", modified=self.DATE)})
        got = self.fetch({self.URL: NOT_MODIFIED})
        self.assertEqual(self.asking, [{}, {"If-None-Match": self.TAG}, {"If-None-Match": self.TAG},
                                       {"If-Modified-Since": self.DATE}])
        self.assertEqual((got.text, got.unchanged), ("y\n", True))

    def test_a_copy_that_does_not_read_back_is_not_asked_after(self):
        # A copy whose bytes are not its record's, or that is gone, is
        # downloaded whole: a 304 would leave nothing to serve.
        for spoil in ("tampered\n", None):
            with self.subTest(spoil=spoil):
                self.fetch({self.URL: sources.Answer("x\n", self.TAG, self.DATE)})
                if spoil is None:
                    (self.raw / "file.cache").unlink()
                else:
                    (self.raw / "file.cache").write_text(spoil, encoding="utf-8")
                got = self.fetch({self.URL: sources.Answer("x\n", self.TAG, self.DATE)})
                self.assertEqual((self.asking[-1], got.text, got.unchanged), ({}, "x\n", False))
                self.assertEqual(self.kept("file"), "x\n")

    def test_a_copy_from_another_address_is_not_asked_after(self):
        self.fetch({self.URL: sources.Answer("x\n", self.TAG, self.DATE)})
        record = self.meta("file")
        record["url"] = "https://elsewhere.invalid/data/hurdat2.txt"
        (self.raw / "file.meta.json").write_text(json.dumps(record), encoding="utf-8")
        got = self.fetch({self.URL: "x\n"})
        self.assertEqual((self.asking[-1], got.unchanged), ({}, False))

    def test_a_tag_that_is_not_text_is_not_sent(self):
        self.fetch({self.URL: "x\n"})
        record = self.meta("file")
        record.update(etag=7, modified=["Thu"])
        (self.raw / "file.meta.json").write_text(json.dumps(record), encoding="utf-8")
        self.fetch({self.URL: "x\n"})
        self.assertEqual(self.asking[-1], {})

    def test_a_gridded_feed_with_no_new_day_is_not_asked_at_all(self):
        # The probe answers first: a dataset with no new day keeps its copy
        # without a request for the subset, tagged or not.
        url = "https://example.invalid/erddap/griddap/x.csv?anom%5Blast%5D"
        self.source = sources.Source(key="grid", name="grid", url=url, agency="test", cadence="daily")
        self.fetch({self.probe(url): LAST, url: sources.Answer(csv("a"), modified=self.DATE)})
        self.asked.clear()
        got = self.fetch({self.probe(url): LAST})
        self.assertEqual((self.asked, got.unchanged), ([self.probe(url)], True))


class TestResting(_Fetching, unittest.TestCase):
    """ERDDAP's tables rest an hour. ERDDAP makes each table afresh for each
    request, so it cannot say whether one changed: its Last-Modified is the
    moment it answered, and it answers a conditional request in full. A copy
    downloaded from the same address under an hour before serves without the
    table being asked for, and says so; TAO's moorings, the tables read here,
    are averaged by the day and the month. The temperature record is 5.7 MB."""

    URL = "https://example.invalid/erddap/tabledap/pmelTaoMonT.csv?time,longitude,depth,T_20"
    TABLE = "time,longitude,depth,T_20\nUTC,degrees_east,m,degree_C\n2026-10-01T00:00:00Z,165.0,100.0,27.1\n"

    def setUp(self):
        super().setUp()
        self.source = sources.Source(key="table", name="table", url=self.URL,
                                     agency="test", cadence="monthly")

    def downloaded(self, ago: timedelta, url: str | None = None):
        """A copy of the table, recorded as downloaded ``ago`` before now."""
        self.fetch({self.URL: sources.Answer(self.TABLE, modified="Fri, 16 Oct 2026 13:39:43 GMT")})
        record = self.meta("table")
        stamp = (datetime.now(timezone.utc) - ago).isoformat(timespec="seconds")
        record.update(fetched_at=stamp, url=url or self.URL)
        (self.raw / "table.meta.json").write_text(json.dumps(record), encoding="utf-8")
        self.asked.clear()
        self.asking.clear()
        return stamp

    def test_a_table_downloaded_under_an_hour_ago_rests(self):
        for ago in (timedelta(0), timedelta(minutes=10), timedelta(minutes=59, seconds=50)):
            with self.subTest(ago=ago):
                stamp = self.downloaded(ago)
                got = self.fetch({})
                self.assertEqual(self.asked, [])
                self.assertEqual((got.text, got.rested, got.unchanged, got.from_cache, got.warnings),
                                 (self.TABLE, True, False, False, []))
                self.assertEqual((got.fetched_at, got.url, got.ok), (stamp, self.URL, True))

    def test_a_table_an_hour_old_is_asked_for_again(self):
        for ago in (timedelta(hours=1), timedelta(hours=1, minutes=5), timedelta(days=3)):
            with self.subTest(ago=ago):
                self.downloaded(ago)
                newer = self.TABLE + "2026-10-01T00:00:00Z,170.0,100.0,26.9\n"
                got = self.fetch({self.URL: newer})
                self.assertEqual(self.asked, [self.URL])
                self.assertEqual((got.text, got.rested), (newer, False))

    def test_a_copy_that_cannot_rest_is_downloaded(self):
        # From another address, from the future (a clock put back), or not
        # reading back as its record says.
        for spoil in ("address", "future", "bytes", "date"):
            with self.subTest(spoil=spoil):
                if spoil == "address":
                    self.downloaded(timedelta(minutes=5), url="https://elsewhere.invalid/erddap/tabledap/x.csv")
                elif spoil == "future":
                    self.downloaded(-timedelta(minutes=5))
                else:
                    self.downloaded(timedelta(minutes=5))
                    if spoil == "bytes":
                        (self.raw / "table.cache").write_text("tampered\n", encoding="utf-8")
                    else:
                        record = self.meta("table")
                        record["fetched_at"] = "a while ago"
                        (self.raw / "table.meta.json").write_text(json.dumps(record), encoding="utf-8")
                got = self.fetch({self.URL: self.TABLE})
                self.assertEqual((self.asked, got.rested, got.text), ([self.URL], False, self.TABLE))

    def test_a_file_or_a_grid_does_not_rest(self):
        plain = "https://example.invalid/data/oni.txt"
        self.source = sources.Source(key="plain", name="plain", url=plain, agency="test", cadence="monthly")
        self.fetch({plain: "x\n"})
        got = self.fetch({plain: "x\n"})
        self.assertEqual((self.asked, got.rested), ([plain, plain], False))
        self.assertFalse(sources.rests(plain))
        self.assertFalse(sources.rests("https://example.invalid/erddap/griddap/x.csv?anom%5Blast%5D"))
        # A query that only names a table is not one.
        self.assertFalse(sources.rests("https://example.invalid/data/x.csv?from=/tabledap/"))

    def test_the_tables_that_rest_are_tao_s(self):
        self.assertEqual([s.key for s in sources.SOURCES if sources.rests(s.url)],
                         ["tao_temperature", "tao_isotherm", "tao_mesh"])


class _Response:
    """What urlopen hands back: the body, and the headers it came with. The
    body is read as http.client's is, a piece at a time (``read1``), until it
    is all in (``isclosed``)."""

    length = None  # what its server said was still to come, as http.client's has

    def __init__(self, body: bytes, headers: dict):
        self.body = body
        self.at = 0
        self.headers = email.message.Message()
        for name, value in headers.items():
            self.headers[name] = value

    def read1(self, n=-1):
        end = len(self.body) if n < 0 else min(len(self.body), self.at + n)
        piece, self.at = self.body[self.at:end], end
        return piece

    def isclosed(self):
        return self.at == len(self.body)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class TestHttpGet(unittest.TestCase):
    """What an address answers, as read off the wire."""

    URL = "https://example.invalid/data/oni.txt"

    def get(self, *answers, headers=None):
        """``_http_get`` with urlopen answering each try in turn: a _Response or
        an Exception. Returns what it gave, and the headers of each request."""
        sent = []

        def urlopen(request, timeout=None, context=None):
            sent.append({name.lower(): value for name, value in request.header_items()})
            answer = answers[min(len(sent), len(answers)) - 1]
            if isinstance(answer, Exception):
                raise answer
            return answer

        with mock.patch.object(sources.urllib.request, "urlopen", urlopen), \
                mock.patch.object(sources.time, "sleep"):
            try:
                return sources._http_get(self.URL, headers), sent
            except RuntimeError as exc:
                return exc, sent

    def not_modified(self):
        return urllib.error.HTTPError(self.URL, 304, "Not Modified", email.message.Message(), None)

    def test_the_text_comes_with_its_server_s_tag_and_date(self):
        got, sent = self.get(_Response(b"x\n", {"ETag": '"2555-65df"', "Last-Modified": "Fri, 16 Oct 2026 11:36:00 GMT"}))
        self.assertEqual(got, sources.Answer("x\n", '"2555-65df"', "Fri, 16 Oct 2026 11:36:00 GMT"))
        self.assertNotIn("if-none-match", sent[0])
        got, _ = self.get(_Response(b"x\n", {}))
        self.assertEqual(got, sources.Answer("x\n", "", ""))

    def test_asked_whether_it_changed_a_server_saying_no_answers_none(self):
        asking = {"If-None-Match": '"2555-65df"', "If-Modified-Since": "Fri, 16 Oct 2026 11:36:00 GMT"}
        got, sent = self.get(self.not_modified(), headers=asking)
        self.assertIsNone(got)
        self.assertEqual((sent[0]["if-none-match"], sent[0]["if-modified-since"], len(sent)),
                         ('"2555-65df"', "Fri, 16 Oct 2026 11:36:00 GMT", 1))

    def test_a_304_to_a_request_that_asked_nothing_is_no_answer(self):
        got, sent = self.get(self.not_modified())
        self.assertIsInstance(got, RuntimeError)
        self.assertIn("304", str(got))
        self.assertEqual(len(sent), sources.RETRIES)

    def test_asked_whether_it_changed_a_new_version_is_its_text(self):
        got, _ = self.get(_Response(b"y\n", {"ETag": '"7c0"'}), headers={"If-None-Match": '"2555-65df"'})
        self.assertEqual(got, sources.Answer("y\n", '"7c0"', ""))

    def test_an_answer_its_server_cut_short_is_no_answer(self):
        cut = _Response(b"x\n", {})
        cut.length = 5  # what its server said was still to come when it closed
        with mock.patch.object(sources.urllib.request, "urlopen", return_value=cut), \
                self.assertRaises(http.client.IncompleteRead):
            sources._http_get(self.URL)


class TestHttpGetOffTheWire(unittest.TestCase):
    """What an address answers, read off a socket from a server on this
    machine: http.client's own response, read a piece at a time."""

    BODY = b"".join(b"%06d\n" % n for n in range(40000))  # several pieces

    def serve(self, answer, host="127.0.0.1"):
        """The address of a server on this machine, at ``host``, that answers
        each request with ``answer(handler)``."""
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_GET(self):
                answer(self)

            def log_message(self, *args):
                pass

        # A TCP server, not http.server's, which looks its own name up.
        server = socketserver.ThreadingTCPServer((host, 0), Handler)
        server.daemon_threads = True
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://{host}:{server.server_address[1]}/feed.txt"

    @staticmethod
    def head(handler, **headers):
        handler.send_response(200)
        for name, value in headers.items():
            handler.send_header(name.replace("_", "-"), value)
        handler.end_headers()

    def test_a_body_comes_whole_however_its_server_sends_it(self):
        body = self.BODY

        def sized(handler):
            self.head(handler, Content_Length=str(len(body)))
            handler.wfile.write(body)

        def chunked(handler):
            self.head(handler, Transfer_Encoding="chunked")
            for start in range(0, len(body), 50000):
                piece = body[start:start + 50000]
                handler.wfile.write(b"%x\r\n%s\r\n" % (len(piece), piece))
            handler.wfile.write(b"0\r\n\r\n")

        def zipped(handler):
            packed = gzip.compress(body)
            self.head(handler, Content_Encoding="gzip", Content_Length=str(len(packed)))
            handler.wfile.write(packed)

        def until_closed(handler):
            self.head(handler, Connection="close")
            handler.wfile.write(body)

        for answer in (sized, chunked, zipped, until_closed):
            with self.subTest(answer.__name__):
                self.assertEqual(sources._http_get(self.serve(answer)).text, body.decode())

    def test_a_body_its_server_cuts_short_is_no_answer(self):
        def cut(handler):
            self.head(handler, Content_Length="10")
            handler.wfile.write(b"12345")
            handler.close_connection = True

        with self.assertRaises(http.client.IncompleteRead):
            sources._http_get(self.serve(cut))

    def test_each_read_waits_on_its_server_no_longer_than_the_feed_has_left(self):
        # The headers come halfway through the feed's 3 s, and a byte; then
        # nothing. The read after the byte waits the 1.5 s left, not the 3 s
        # its try was given.
        went_on = threading.Event()
        self.addCleanup(went_on.set)

        def stalls(handler):
            went_on.wait(1.5)
            self.head(handler, Content_Length="10")
            handler.wfile.write(b"1")
            went_on.wait(30)

        url = self.serve(stalls)
        began = time.monotonic()
        with mock.patch.object(sources, "FEED_TIME", 3):
            with self.assertRaises(RuntimeError) as cm:
                sources._http_get(url)
        self.assertLess(time.monotonic() - began, 3.75)
        self.assertIn("the feed's 3 s are spent", str(cm.exception))

    def test_a_server_that_takes_the_request_and_never_answers_is_silent(self):
        went_on = threading.Event()
        self.addCleanup(went_on.set)
        url = self.serve(lambda handler: went_on.wait(30))
        patience = sources.Patience()
        began = time.monotonic()
        with mock.patch.object(sources, "TIMEOUT", 1.5):
            with self.assertRaises(RuntimeError) as cm:
                sources._http_get(url, wait=patience.for_feed())
            # One try, and no pause after it: the next is not made.
            self.assertLess(time.monotonic() - began, 2.5)
            self.assertIn("127.0.0.1 left a try unanswered for 1.5 s", str(cm.exception))
            with self.assertRaises(RuntimeError) as cm:
                sources._http_get(url, wait=patience.for_feed())
        self.assertEqual(str(cm.exception), "127.0.0.1 left a try unanswered for 1.5 s, and is not asked again this run")

    def test_a_server_a_try_is_sent_on_to_that_never_answers_is_the_silent_one(self):
        # urllib follows a redirect within the try, and notes on the request
        # each address it sent it on to: the silence is that server's, and
        # the one that sent the try on is still asked.
        went_on = threading.Event()
        self.addCleanup(went_on.set)
        there = self.serve(lambda handler: went_on.wait(30), host="127.0.0.2")

        def sends_on(handler):
            handler.send_response(302)
            handler.send_header("Location", there)
            handler.send_header("Content-Length", "0")
            handler.end_headers()

        patience = sources.Patience()
        with mock.patch.object(sources, "TIMEOUT", 1.5), self.assertRaises(RuntimeError) as cm:
            sources._http_get(self.serve(sends_on), wait=patience.for_feed())
        self.assertIn("127.0.0.2 left a try unanswered for 1.5 s", str(cm.exception))
        self.assertEqual((patience.is_silent("127.0.0.2"), patience.is_silent("127.0.0.1")), (True, False))


class _Clock:
    """The clock a run's patience reads, and the sleep that moves it on."""

    START = 1000.0

    def __init__(self):
        self.now = self.START

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class _Trickle(_Response):
    """A download that comes a byte at a time, each byte ``each`` seconds
    after the last, or as long as the socket waits when that is less; the
    socket notes each wait it is given."""

    def __init__(self, clock, each, size):
        super().__init__(b"x" * size, {})
        self.clock, self.each, self.timeouts = clock, each, []
        self.fp = SimpleNamespace(raw=SimpleNamespace(_sock=SimpleNamespace(settimeout=self.timeouts.append)))

    def read1(self, n=-1):
        self.clock.now += min([self.each, *self.timeouts[-1:]])
        return super().read1(1)


class TestPatience(unittest.TestCase):
    """A run's patience with the servers it asks (``sources.Patience``): a
    server that leaves a try unanswered for the whole of its timeout is not
    asked again in the run, as CoastWatch's West Coast node at times left
    every try on 17 to 19 October 2026, three tries of 45 s an address; and a
    feed has FEED_TIME for all it asks, whatever its servers do."""

    HUNG = "https://coastwatch.example/erddap/griddap/nrt.csv"
    SAME = "https://coastwatch.example/erddap/griddap/final.csv"
    OTHER = "https://ncei.example/erddap/griddap/nrt.csv"
    # What CoastWatch's node answered after each try's 45 s: its IPv4 address
    # hung, and its IPv6 one, tried last, was unreachable from the runner.
    UNREACHABLE = urllib.error.URLError(OSError(101, "Network is unreachable"))

    def setUp(self):
        self.clock = _Clock()
        self.patience = sources.Patience(clock=self.clock)
        self.tries = []  # each try made: its address and the timeout it was given

    def urlopen(self, script):
        """urlopen answering each address's tries in turn from ``script``, the
        last answer over again: a _Response; an Exception, at once; ("hang",
        e), e after the try's whole timeout; ("slow", s, e), e after s
        seconds, or the socket's own timeout first when s is longer; or
        ("redirect", url), the try sent on to url's answer, as urllib follows
        a redirect, noting on the request each address it sent it on to."""
        def next_answer(url):
            answers = script[url]
            return answers.pop(0) if len(answers) > 1 else answers[0]

        def urlopen(request, timeout=None, context=None):
            url = request.full_url
            self.tries.append((url, timeout))
            answer = next_answer(url)
            while isinstance(answer, tuple) and answer[0] == "redirect":
                request.redirect_dict = {**getattr(request, "redirect_dict", {}), answer[1]: 1}
                answer = next_answer(answer[1])
            if isinstance(answer, tuple) and answer[0] == "hang":
                self.clock.now += timeout
                raise answer[1]
            if isinstance(answer, tuple):
                _, seconds, exc = answer
                if seconds > timeout:
                    self.clock.now += timeout
                    raise TimeoutError("timed out")
                self.clock.now += seconds
                raise exc
            if isinstance(answer, Exception):
                raise answer
            return answer
        return urlopen

    def get(self, url, script, wait=None):
        """What _http_get gives, or the error it raises, for one feed's ask."""
        with mock.patch.object(sources.urllib.request, "urlopen", self.urlopen(script)), \
                mock.patch.object(sources.time, "sleep", self.clock.sleep):
            try:
                return sources._http_get(url, wait=wait or self.patience.for_feed())
            except RuntimeError as exc:
                return exc

    def test_a_server_that_leaves_a_try_unanswered_its_whole_timeout_is_not_asked_again_that_run(self):
        script = {self.HUNG: [("hang", self.UNREACHABLE)], self.SAME: [_Response(b"same\n", {})],
                  self.OTHER: [_Response(b"other\n", {})]}
        first = self.get(self.HUNG, script)
        self.assertIsInstance(first, RuntimeError)
        self.assertIn("Network is unreachable", str(first))
        # One try, not three: the next two would only have waited as long.
        self.assertEqual(self.tries, [(self.HUNG, sources.TIMEOUT)])
        self.assertEqual(self.clock.now - _Clock.START, sources.TIMEOUT)
        # Another feed of the run asks another of its addresses, and is told
        # why at once; another server is asked as ever.
        same, other = self.get(self.SAME, script), self.get(self.OTHER, script)
        self.assertIsInstance(same, RuntimeError)
        self.assertIn("coastwatch.example left a try unanswered for 45 s", str(same))
        self.assertIn("not asked again this run", str(same))
        self.assertEqual(other, sources.Answer("other\n"))
        self.assertEqual(self.tries, [(self.HUNG, 45), (self.OTHER, 45)])
        self.assertEqual(self.clock.now - _Clock.START, sources.TIMEOUT)
        # The next run asks it again.
        again = sources.Patience(clock=self.clock)
        self.assertEqual(self.get(self.SAME, script, again.for_feed()), sources.Answer("same\n"))

    def test_a_try_its_server_left_unanswered_is_not_counted_in_the_feed_s_time(self):
        # CoastWatch's silence costs its 45 s, and NCEI behind it still has
        # the feed's 120 s, here for a download that comes slowly.
        trickle = _Trickle(self.clock, 40, 3)
        wait = self.patience.for_feed()
        self.assertIsInstance(self.get(self.HUNG, {self.HUNG: [("hang", self.UNREACHABLE)]}, wait), RuntimeError)
        self.assertEqual(self.get(self.OTHER, {self.OTHER: [trickle]}, wait), sources.Answer("xxx"))
        self.assertEqual(trickle.timeouts, [45, 45, 40])
        self.assertEqual(self.clock.now - _Clock.START, sources.TIMEOUT + sources.FEED_TIME)

    def test_the_server_a_try_was_sent_on_to_is_the_silent_one_when_it_never_answers(self):
        # CoastWatch answered, sending the try on to another server, which
        # never did: that one is silent, and CoastWatch is still asked by the
        # run's other feeds.
        moved = "https://moved.example/erddap/griddap/nrt.csv"
        script = {self.SAME: [("redirect", moved)], moved: [("hang", self.UNREACHABLE)],
                  self.HUNG: [_Response(b"here\n", {})]}
        self.assertIn("moved.example left a try unanswered for 45 s", str(self.get(self.SAME, script)))
        # One try: the next would be sent on to the same silence.
        self.assertEqual(self.tries, [(self.SAME, sources.TIMEOUT)])
        self.assertEqual(self.get(self.HUNG, script), sources.Answer("here\n"))
        self.assertIn("moved.example left a try unanswered", str(self.get(moved, script)))

    def test_a_try_that_hangs_at_its_own_server_is_its_own_server_s_silence(self):
        # Each try is a request of its own: where an earlier try was sent on
        # to says nothing of where a later one hung.
        moved = "https://moved.example/erddap/griddap/nrt.csv"
        busy = urllib.error.HTTPError(moved, 503, "Service Unavailable", email.message.Message(), None)
        script = {self.SAME: [("redirect", moved), ("hang", self.UNREACHABLE)], moved: [busy]}
        self.assertIn("coastwatch.example left a try unanswered for 45 s", str(self.get(self.SAME, script)))
        self.assertEqual(self.tries, [(self.SAME, 45), (self.SAME, 45)])

    def test_a_try_that_fails_at_once_is_made_again_and_its_server_still_asked(self):
        refused = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        script = {self.HUNG: [refused, refused, _Response(b"x\n", {})], self.SAME: [_Response(b"y\n", {})]}
        self.assertEqual(self.get(self.HUNG, script), sources.Answer("x\n"))
        self.assertEqual(len(self.tries), sources.RETRIES)
        self.assertEqual(self.get(self.SAME, script), sources.Answer("y\n"))

    def test_a_server_that_answers_slowly_with_an_error_is_still_asked(self):
        # It answered: the run is not told it went silent. The feed's time
        # cuts the third try short, and a try cut short by the feed's time,
        # not the server's whole timeout, is no silence either.
        busy = urllib.error.HTTPError(self.HUNG, 503, "Service Unavailable", email.message.Message(), None)
        script = {self.HUNG: [("slow", 40, busy)], self.SAME: [_Response(b"y\n", {})]}
        got = self.get(self.HUNG, script)
        self.assertIsInstance(got, RuntimeError)
        self.assertEqual(self.tries, [(self.HUNG, 45), (self.HUNG, 45), (self.HUNG, 32.5)])
        self.assertEqual(self.clock.now - _Clock.START, sources.FEED_TIME)
        self.assertEqual(self.get(self.SAME, script), sources.Answer("y\n"))

    def test_a_feed_s_time_spans_every_address_it_asks_and_no_try_or_pause_outlasts_it(self):
        reset = urllib.error.URLError(ConnectionResetError(104, "Connection reset by peer"))
        script = {self.HUNG: [("slow", 30, reset)], self.OTHER: [("slow", 30, reset)]}
        wait = self.patience.for_feed()
        self.assertIsInstance(self.get(self.HUNG, script, wait), RuntimeError)
        got = self.get(self.OTHER, script, wait)
        self.assertIsInstance(got, RuntimeError)
        self.assertIn("the feed's 120 s are spent", str(got))
        # 30 s a try with 2.5 and 5 s between: 97.5 s on the first address,
        # the rest on one try at the second, and no pause past the end.
        self.assertEqual(self.tries, [(self.HUNG, 45), (self.HUNG, 45), (self.HUNG, 45), (self.OTHER, 22.5)])
        self.assertEqual(self.clock.now - _Clock.START, sources.FEED_TIME)
        self.assertEqual(self.get(self.OTHER, script, wait).args[0], "the feed's 120 s are spent")
        self.assertEqual(len(self.tries), 4)

    def test_a_download_still_coming_when_the_feed_s_time_is_spent_is_cut_off(self):
        trickle = _Trickle(self.clock, 40, 100)
        got = self.get(self.OTHER, {self.OTHER: [trickle]})
        self.assertIsInstance(got, RuntimeError)
        self.assertIn("the feed's 120 s were spent before its download was in", str(got))
        # Each read waited no longer than the feed had left, and the server,
        # which was answering, is not taken for silent.
        self.assertEqual(trickle.timeouts, [45, 45, 40])
        self.assertEqual(self.clock.now - _Clock.START, sources.FEED_TIME)
        self.assertEqual(self.tries, [(self.OTHER, 45)])
        self.assertEqual(self.get(self.OTHER, {self.OTHER: [_Response(b"z\n", {})]}), sources.Answer("z\n"))

    def test_a_download_in_as_the_feed_s_time_runs_out_is_in(self):
        self.assertEqual(self.get(self.OTHER, {self.OTHER: [_Trickle(self.clock, 40, 3)]}), sources.Answer("xxx"))
        self.assertEqual(self.clock.now - _Clock.START, sources.FEED_TIME)

    def test_a_feed_whose_server_is_silent_serves_its_copy_and_asks_the_second_server(self):
        # Two products, each on CoastWatch with NCEI behind it, as OISST's
        # feeds are: CoastWatch's silence costs one timeout for the feed, not
        # one an address, and NCEI's answers decide as they would.
        nrt, final = self.HUNG + "?anom%5Blast%5D", self.SAME + "?anom%5Blast%5D"
        ncei_nrt = self.OTHER + "?anom%5Blast%5D"
        ncei_final = "https://ncei.example/erddap/griddap/final.csv?anom%5Blast%5D"
        source = sources.Source(key="grid", name="grid", url=nrt, agency="test", cadence="daily",
                                final=final, fallback=(ncei_nrt,), final_fallback=(ncei_final,))
        probe = sources.probe_url

        def run(script):
            self.tries.clear()
            with mock.patch.object(sources.urllib.request, "urlopen", self.urlopen(script)), \
                    mock.patch.object(sources.time, "sleep", self.clock.sleep):
                return sources.fetch(source, raw, patience=sources.Patience(clock=self.clock))

        def answer(text):
            return [_Response(text.encode("utf-8"), {})]

        with tempfile.TemporaryDirectory() as tmp:
            raw = Path(tmp)
            first = run({probe(nrt): answer(LATER), probe(final): answer(FINAL_LAST), nrt: answer(csv("a"))})
            self.assertEqual((first.text, first.from_cache), (csv("a"), False))
            start = self.clock.now
            got = run({probe(nrt): [("hang", self.UNREACHABLE)], probe(final): [("hang", self.UNREACHABLE)],
                       probe(ncei_nrt): answer(LATER), probe(ncei_final): answer(FINAL_LAST)})
        self.assertEqual((got.text, got.from_cache), (csv("a"), True))
        self.assertEqual(self.clock.now - start, sources.TIMEOUT)
        self.assertEqual([url for url, _ in self.tries if "coastwatch" in url], [probe(nrt)])
        self.assertIn("coastwatch.example left a try unanswered for 45 s", got.warnings[0])
        self.assertIn(probe(ncei_nrt), "".join(url for url, _ in self.tries))

    def test_the_feeds_of_a_run_share_its_patience(self):
        a = sources.Source(key="a", name="a", url="https://cpc.example/indices/a.txt", agency="t", cadence="monthly")
        b = sources.Source(key="b", name="b", url="https://cpc.example/indices/b.txt", agency="t", cadence="monthly")
        script = {a.url: [("hang", self.UNREACHABLE)], b.url: [("hang", self.UNREACHABLE)]}
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(sources, "SOURCES", (a, b)), mock.patch.object(sources, "MAX_PARALLEL", 1), \
                mock.patch.object(sources.urllib.request, "urlopen", self.urlopen(script)), \
                mock.patch.object(sources.time, "sleep", self.clock.sleep), \
                mock.patch.object(sources.time, "monotonic", self.clock):
            got = sources.fetch_all(Path(tmp))
        self.assertEqual(self.tries, [(a.url, sources.TIMEOUT)])
        self.assertIn("Network is unreachable", got["a"].error)
        self.assertIn("cpc.example left a try unanswered for 45 s", got["b"].error)


class TestAWebPageForAFile(_Fetching, unittest.TestCase):
    """A web page answering for a feed's file, with a 200, as a server down for
    maintenance or a file moved can send one: not kept over the copy."""

    URL = "https://example.invalid/indices/daily.txt"
    FILE = "Year Day  Tahiti  Darwin     SOI\n2026 286 1014.33 1014.55  -19.13\n"
    PAGE = "<!DOCTYPE html>\n<html><body><h1>Down for maintenance</h1></body></html>\n"

    def setUp(self):
        super().setUp()
        self.source = sources.Source(key="grid", name="grid", url=self.URL,
                                     agency="test", cadence="daily")

    def test_a_page_for_a_file_is_no_answer_and_the_copy_serves(self):
        self.fetch({self.URL: self.FILE})
        got = self.fetch({self.URL: self.PAGE})
        self.assertEqual((got.text, got.from_cache), (self.FILE, True))
        self.assertIn(f"its answer is a web page ({self.URL})", got.warnings[0])
        self.assertEqual(self.kept(), self.FILE)

    def test_a_page_is_one_after_white_space_or_a_byte_order_mark(self):
        for page in ("\n\n  " + self.PAGE, "\N{ZERO WIDTH NO-BREAK SPACE}" + self.PAGE, "<html>\n"):
            with self.subTest(page=page[:12]):
                got = self.fetch({self.URL: page})
                self.assertFalse(got.ok)
                self.assertIn("its answer is a web page", got.error)

    def test_a_feed_that_is_a_page_keeps_its_page(self):
        self.source = replace(self.source, markup=True)
        got = self.fetch({self.URL: self.PAGE})
        self.assertEqual((got.text, got.from_cache), (self.PAGE, False))

    def test_the_feeds_that_are_pages_rss_or_kml_are_marked_so(self):
        self.assertEqual({source.key for source in sources.SOURCES if source.markup},
                         {"discussion", "atcf_index", "hurdat_index", "nhc_outlook_at",
                          "nhc_outlook_ep", "nhc_outlook_cp", "jtwc_rss"})
        self.assertTrue(sources.product_source("cone", "ep152026", "https://example.invalid/c.kmz")
                        .markup)
        for built in (sources.deck_source("b", "ep152026"), sources.hurdat_source("AL", "h.txt"),
                      sources.jtwc_source("wp2526.tcw")):
            self.assertFalse(built.markup, built.key)

    def test_each_feed_s_own_sample_is_markup_only_if_it_is_a_page_rss_or_kml(self):
        # The fixtures are feeds' own files as they were downloaded.
        for path in sorted((Path(__file__).resolve().parent / "fixtures").iterdir()):
            if path.is_file():
                with self.subTest(path=path.name):
                    text = path.read_text(encoding="utf-8", errors="replace")
                    self.assertEqual(sources._is_markup(text),
                                     path.suffix in {".html", ".shtml", ".kml", ".rss"})


class TestSecondServer(_Fetching, unittest.TestCase):
    """NCEI's own ERDDAP behind CoastWatch's: a product whose address fails is
    asked for the same subset there, and the product's copy claims beside it."""

    PRIMARY = "https://coastwatch.invalid/erddap/griddap/nrt.csv?anom%5Blast%5D"
    FINAL = "https://coastwatch.invalid/erddap/griddap/final.csv?anom%5Blast%5D"
    SECOND = "https://ncei.invalid/erddap/griddap/prelim.csv?anom%5Blast%5D"
    SECOND_FINAL = "https://ncei.invalid/erddap/griddap/final.csv?anom%5Blast%5D"
    # The same dataset of NCEI's, asked for a window less its oldest day.
    SECOND_LESS = "https://ncei.invalid/erddap/griddap/prelim.csv?anom%5B1%5D"

    def setUp(self):
        super().setUp()
        self.source = sources.Source(key="grid", name="grid", url=self.PRIMARY, agency="test",
                                     cadence="daily", final=self.FINAL, fallback=(self.SECOND,),
                                     final_fallback=(self.SECOND_FINAL,))

    def hour(self, coastwatch=LATER, ncei=LATER):
        """Each server's preliminary at its day, and each one's final at 28 September."""
        return {self.probe(self.PRIMARY): coastwatch, self.probe(self.FINAL): FINAL_LAST,
                self.probe(self.SECOND): ncei, self.probe(self.SECOND_FINAL): FINAL_LAST,
                self.PRIMARY: csv("cw"), self.FINAL: csv("cw final"),
                self.SECOND: csv("ncei"), self.SECOND_FINAL: csv("ncei final")}

    def down(self, answers):
        """The same hour with CoastWatch down."""
        return {url: answer for url, answer in answers.items() if "coastwatch" not in url}

    def failed(self, url):
        """What the report says of an address whose probe found no route."""
        return f"no route to {self.probe(url)} ({url})"

    def test_while_coastwatch_answers_ncei_is_not_asked(self):
        got = self.fetch(self.hour())
        self.assertEqual(self.asked, [self.probe(self.PRIMARY), self.probe(self.FINAL), self.PRIMARY])
        self.assertEqual((got.url, got.warnings), (self.PRIMARY, []))
        # Not even when it has a later day: it stands behind CoastWatch, it
        # does not race it.
        self.asked.clear()
        self.assertEqual(self.fetch(self.hour(coastwatch=LAST, ncei=NEXT)).url, self.PRIMARY)
        self.assertFalse([url for url in self.asked if "ncei" in url], self.asked)

    def test_ncei_serves_a_product_coastwatch_fails_and_says_why(self):
        got = self.fetch(self.down(self.hour()))
        self.assertEqual((got.text, got.url, got.from_cache), (csv("ncei"), self.SECOND, False))
        self.assertEqual(got.warnings, [f"{self.failed(self.PRIMARY)}; {self.failed(self.FINAL)}; "
                                        f"served by {self.SECOND}"])
        # The product keeps one copy, whichever server it came from.
        self.assertEqual((self.kept(), self.meta()["url"]), (csv("ncei"), self.SECOND))
        self.assertEqual(self.meta()["probe"], "2026-10-13T12:00:00Z")
        self.assertEqual([p.name.rpartition("_")[0] for p in (self.raw / "archive").iterdir()],
                         ["grid"])

    def test_the_copy_ncei_served_is_not_downloaded_again_while_its_day_stands(self):
        first = self.fetch(self.down(self.hour()))
        self.asked.clear()
        again = self.fetch(self.down(self.hour()))
        self.assertNotIn(self.SECOND, self.asked)
        self.assertEqual((again.text, again.url, again.unchanged, again.fetched_at),
                         (csv("ncei"), self.SECOND, True, first.fetched_at))

    def test_coastwatch_back_serves_again(self):
        self.fetch(self.down(self.hour()))
        got = self.fetch(self.hour())
        self.assertEqual((got.text, got.url, got.unchanged, got.warnings),
                         (csv("cw"), self.PRIMARY, False, []))
        self.assertEqual(self.meta()["url"], self.PRIMARY)

    def test_ncei_is_asked_when_coastwatch_says_its_day_but_fails_the_subset(self):
        answers = self.hour()
        answers[self.PRIMARY] = RuntimeError("HTTP Error 502: Bad Gateway")
        got = self.fetch(answers)
        self.assertEqual((got.text, got.url), (csv("ncei"), self.SECOND))
        self.assertEqual(got.warnings, [f"HTTP Error 502: Bad Gateway ({self.PRIMARY}); "
                                        f"served by {self.SECOND}"])

    def test_a_copy_of_a_later_day_than_ncei_s_serves_and_says_so(self):
        self.fetch(self.hour(coastwatch=NEXT))
        self.asked.clear()
        got = self.fetch(self.down(self.hour(ncei=LATER)))
        self.assertEqual((got.text, got.url, got.from_cache), (csv("cw"), self.PRIMARY, True))
        self.assertNotIn(self.SECOND, self.asked)
        self.assertEqual(got.warnings, [
            f"live fetch failed ({self.failed(self.PRIMARY)}; {self.failed(self.FINAL)}; "
            f"latest day 2026-10-13, no later than its copy's 2026-10-14 ({self.SECOND}))"])
        self.assertEqual((self.kept(), self.meta()["probe"]), (csv("cw"), "2026-10-14T12:00:00Z"))

    def test_ncei_s_answer_for_the_day_of_coastwatch_s_copy_leaves_the_copy(self):
        # CoastWatch's preliminary window reaches back four weeks and NCEI's
        # two: a day both have is not swapped for NCEI's, and the daily card
        # keeps what the final changed.
        self.fetch(self.hour())
        self.asked.clear()
        got = self.fetch(self.down(self.hour(ncei=LATER)))
        self.assertEqual((got.text, got.url, got.from_cache), (csv("cw"), self.PRIMARY, True))
        self.assertNotIn(self.SECOND, self.asked)
        self.assertEqual(got.warnings, [
            f"live fetch failed ({self.failed(self.PRIMARY)}; {self.failed(self.FINAL)}; "
            f"latest day 2026-10-13, no later than its copy's 2026-10-13 ({self.SECOND}))"])
        self.assertEqual((self.kept(), self.meta()["url"]), (csv("cw"), self.PRIMARY))

    def test_coastwatch_failing_its_new_day_s_subset_leaves_its_copy_before_ncei_s_same_day(self):
        self.fetch(self.hour())
        self.asked.clear()
        answers = self.hour(coastwatch=NEXT, ncei=LATER)
        answers[self.PRIMARY] = RuntimeError("HTTP Error 502: Bad Gateway")
        got = self.fetch(answers)
        self.assertEqual((got.text, got.url, got.from_cache), (csv("cw"), self.PRIMARY, True))
        self.assertNotIn(self.SECOND, self.asked)
        self.assertEqual(got.warnings, [
            f"live fetch failed (HTTP Error 502: Bad Gateway ({self.PRIMARY}); "
            f"latest day 2026-10-13, no later than its copy's 2026-10-13 ({self.SECOND}))"])

    def test_coastwatch_back_behind_the_copy_ncei_made_leaves_it_current_and_says_so(self):
        # NCEI served the 14th through the outage and CoastWatch comes back on
        # the 13th: the maps do not go back a day, and NCEI is not asked.
        self.fetch(self.down(self.hour(ncei=NEXT)))
        self.asked.clear()
        got = self.fetch(self.hour(coastwatch=LATER, ncei=NEXT))
        self.assertEqual((got.text, got.url, got.from_cache, got.unchanged),
                         (csv("ncei"), self.SECOND, False, True))
        self.assertEqual(self.asked, [self.probe(self.PRIMARY), self.probe(self.FINAL)])
        self.assertEqual(got.warnings, [
            f"latest day 2026-10-13, no later than its copy's 2026-10-14 ({self.PRIMARY}); "
            f"served by {self.SECOND}"])
        self.assertEqual((self.kept(), self.meta()["url"]), (csv("ncei"), self.SECOND))
        # CoastWatch at the copy's day serves again.
        got = self.fetch(self.hour(coastwatch=NEXT))
        self.assertEqual((got.text, got.url, got.unchanged), (csv("cw"), self.PRIMARY, False))
        self.assertEqual(self.meta()["url"], self.PRIMARY)

    def test_a_copy_coastwatch_made_gives_way_to_coastwatch_going_back_a_day(self):
        # CoastWatch is the authority on its own days: one it no longer has
        # is not kept on.
        self.fetch(self.hour(coastwatch=NEXT))
        got = self.fetch(self.hour(coastwatch=LATER))
        self.assertEqual((got.url, got.from_cache, got.unchanged), (self.PRIMARY, False, False))
        self.assertEqual(self.meta()["probe"], "2026-10-13T12:00:00Z")

    def test_coastwatch_saying_no_day_is_downloaded_over_the_copy_ncei_made(self):
        # An answer of CoastWatch's that says no day is a full download.
        self.fetch(self.down(self.hour(ncei=NEXT)))
        answers = self.hour(coastwatch="")
        del answers[self.probe(self.FINAL)], answers[self.probe(self.SECOND_FINAL)]
        got = self.fetch(answers)
        self.assertEqual((got.text, got.url, got.from_cache), (csv("cw"), self.PRIMARY, False))

    def test_ncei_saying_no_day_leaves_the_copy_and_is_said_to_have_said_none(self):
        # Its answer is not shown to be the later; the copy's day is known.
        self.fetch(self.hour())
        got = self.fetch(self.down(self.hour(ncei="")))
        self.assertEqual((got.text, got.url, got.from_cache), (csv("cw"), self.PRIMARY, True))
        self.assertEqual(got.warnings, [
            f"live fetch failed ({self.failed(self.PRIMARY)}; {self.failed(self.FINAL)}; "
            f"latest day not said ({self.SECOND}))"])

    def test_the_final_s_own_answer_from_ncei_is_not_named_as_a_stalled_preliminary(self):
        self.fetch({self.probe(self.FINAL): FINAL_LAST, self.FINAL: csv("cw final")})
        got = self.fetch({self.probe(self.SECOND_FINAL): FINAL_BEFORE,
                          self.SECOND_FINAL: csv("ncei final")})
        self.assertEqual((got.text, got.url, got.from_cache), (csv("cw final"), self.FINAL, True))
        self.assertEqual(got.warnings, [
            f"live fetch failed ({self.failed(self.PRIMARY)}; {self.failed(self.SECOND)}; "
            f"{self.failed(self.FINAL)}; "
            f"latest day 2026-09-27, no later than its copy's 2026-09-28 ({self.SECOND_FINAL}))"])

    def test_a_copy_ncei_made_that_is_not_what_its_record_says_is_named_by_ncei_s_address(self):
        self.fetch(self.down(self.hour()))
        (self.raw / "grid.cache").write_bytes(b"tampered\n")
        got = self.fetch({})
        self.assertFalse(got.ok)
        self.assertIn(f"the copy kept of it does not match its record ({self.SECOND})", got.error)

    def test_ncei_s_next_address_is_asked_when_one_fails_its_subset(self):
        self.source = replace(self.source, fallback=(self.SECOND, self.SECOND_LESS))
        answers = self.down(self.hour())
        answers[self.SECOND] = RuntimeError("HTTP Error 500: Internal Server Error")
        answers[self.SECOND_LESS] = csv("ncei less")
        got = self.fetch(answers)
        self.assertEqual((got.text, got.url, got.from_cache), (csv("ncei less"), self.SECOND_LESS, False))
        self.assertEqual(got.warnings, [
            f"{self.failed(self.PRIMARY)}; {self.failed(self.FINAL)}; "
            f"HTTP Error 500: Internal Server Error ({self.SECOND}); served by {self.SECOND_LESS}"])
        self.assertEqual((self.asked.count(self.SECOND), self.asked.count(self.SECOND_LESS)), (1, 1))
        self.assertEqual(self.meta()["url"], self.SECOND_LESS)

    def test_ncei_failing_its_subset_leaves_the_copy_and_is_asked_once(self):
        self.fetch(self.hour())
        self.asked.clear()
        answers = self.down(self.hour(ncei=NEXT))
        answers[self.SECOND] = RuntimeError("HTTP Error 500: Internal Server Error")
        got = self.fetch(answers)
        self.assertEqual((got.text, got.url, got.from_cache), (csv("cw"), self.PRIMARY, True))
        self.assertEqual((self.asked.count(self.probe(self.SECOND)), self.asked.count(self.SECOND)),
                         (1, 1))
        self.assertEqual(got.warnings, [
            f"live fetch failed ({self.failed(self.PRIMARY)}; {self.failed(self.FINAL)}; "
            f"HTTP Error 500: Internal Server Error ({self.SECOND}))"])

    def test_ncei_s_final_serves_when_all_else_fails(self):
        got = self.fetch({self.probe(self.SECOND_FINAL): FINAL_LAST,
                          self.SECOND_FINAL: csv("ncei final")})
        self.assertEqual((got.text, got.url), (csv("ncei final"), self.SECOND_FINAL))
        self.assertEqual(got.warnings, [
            f"{self.failed(self.PRIMARY)}; {self.failed(self.SECOND)}; {self.failed(self.FINAL)}; "
            f"served by {self.SECOND_FINAL}"])
        self.assertEqual(self.meta("grid.final")["url"], self.SECOND_FINAL)

    def test_a_preliminary_stalled_at_ncei_is_named_against_the_final(self):
        got = self.fetch(self.down(self.hour(ncei=STALLED)))
        self.assertEqual(got.url, self.SECOND_FINAL)
        (warning,) = got.warnings
        self.assertIn(f"latest day 2026-09-01, no later than the final's ({self.SECOND})", warning)

    def test_nothing_at_all_is_an_error_naming_all_four_addresses(self):
        got = self.fetch({})
        self.assertFalse(got.ok)
        self.assertEqual(got.error, "; ".join(self.failed(url) for url in (
            self.PRIMARY, self.SECOND, self.FINAL, self.SECOND_FINAL)))

    def test_offline_the_copy_serves_whichever_server_it_came_from(self):
        self.fetch(self.down(self.hour()))
        self.asked.clear()
        got = self.fetch({}, offline=True)
        self.assertEqual(self.asked, [])
        self.assertEqual((got.text, got.url, got.from_cache), (csv("ncei"), self.SECOND, True))


# --- the day by day boxes and the Hovmoller's latest rows ---------------------
HEAD = "time,zlev,latitude,longitude,anom\nUTC,m,degrees_north,degrees_east,degree_C\n"


def _days_csv(days: dict[str, list[tuple[float, float, str]]]) -> str:
    """An ERDDAP CSV of days, each a list of (lat, lon, value) cells."""
    rows = [f"{day}T12:00:00Z,0.0,{lat},{lon},{value}"
            for day, cells in days.items() for lat, lon, value in cells]
    return HEAD + "\n".join(rows) + "\n"


# Cells in each box on 11 and 12 October: Nino-4 and Nino-3.4 share 200.125E.
CELLS = {
    "2026-10-11": [(-4.875, 200.125, "1.0"), (-4.875, 230.125, "NaN"),
                   (-5.125, 275.125, "4.0"),
                   (0.125, 200.125, "2.0"), (0.125, 230.125, "3.0"),
                   (4.625, 230.125, "NaN")],
    "2026-10-12": [(-4.875, 200.125, "1.5"), (-4.875, 230.125, "2.5"),
                   (-5.125, 275.125, "4.5"),
                   (0.125, 200.125, "2.5"), (0.125, 230.125, "3.5"),
                   (4.625, 230.125, "0.5")],
}


class TestDailyBoxes(unittest.TestCase):
    """Each day's mean over each Nino box, and the record spliced to the latest."""

    def test_each_day_has_each_box_s_cosine_weighted_mean(self):
        days = grids.daily_box_means(_days_csv(CELLS))
        self.assertEqual([d.day for d in days], ["2026-10-11", "2026-10-12"])
        c0, c5 = math.cos(math.radians(0.125)), math.cos(math.radians(-4.875))
        first = days[0].means
        # Nino-3.4 holds 200.125E and 230.125E; the NaN cells weigh nothing.
        self.assertAlmostEqual(first["nino34"], (1.0 * c5 + 2.0 * c0 + 3.0 * c0) / (c5 + 2 * c0))
        self.assertAlmostEqual(first["nino4"], (1.0 * c5 + 2.0 * c0) / (c5 + c0))
        self.assertAlmostEqual(first["nino3"], 3.0)
        self.assertAlmostEqual(first["nino12"], 4.0)
        self.assertFalse(days[0].preliminary)

    def test_a_day_on_the_map_has_the_map_s_box_means_to_the_last_bit(self):
        day = "2026-10-12"
        map_csv = ("time,zlev,latitude,longitude,anom\nUTC,m,degrees_north,degrees_east,degree_C\n"
                   + "\n".join(f"{day}T12:00:00Z,0.0,{lat},{lon},{v}" for lat, lon, v in CELLS[day]) + "\n")
        grid = grids.grid_map(map_csv, "anom", "t", "°C")
        (got,) = grids.daily_box_means(_days_csv({day: CELLS[day]}))
        for box in grids.NINO_BOXES:
            with self.subTest(box=box.key):
                self.assertEqual(got.means[box.key], grids.box_mean(grid, box))

    def test_a_box_with_no_value_on_a_day_is_left_out_of_that_day(self):
        csv = _days_csv({"2026-10-12": [(0.125, 200.125, "NaN"), (-5.125, 275.125, "1.0")]})
        (day,) = grids.daily_box_means(csv)
        self.assertEqual(set(day.means), {"nino12"})

    def test_the_preliminary_product_s_days_say_so(self):
        days = grids.daily_box_means(_days_csv(CELLS), preliminary=True)
        self.assertTrue(all(d.preliminary for d in days))

    def test_an_empty_answer_is_an_error_not_an_empty_series(self):
        with self.assertRaises(ValueError):
            grids.daily_box_means(HEAD)

    def test_a_row_whose_time_is_not_a_day_is_left_out(self):
        text = _days_csv(CELLS).replace("2026-10-12T12:00:00Z,0.0,0.125,230.125",
                                        "2026-13-45T12:00:00Z,0.0,0.125,230.125")
        text += "not a time,0.0,0.125,200.125,9.9\n"
        days = grids.daily_box_means(text)
        self.assertEqual([d.day for d in days], ["2026-10-11", "2026-10-12"])
        self.assertIn('id="nino-daily"', daily.nino_card(days, []))

    def test_the_days_are_summed_as_they_come_and_a_day_come_again_is_an_error(self):
        # ERDDAP sends a subset day by day, and a day is summed when its rows
        # end, so that ninety days of cells are never held at once.
        text = _days_csv(CELLS) + "2026-10-11T12:00:00Z,0.0,0.125,200.125,2.0\n"
        with self.assertRaisesRegex(ValueError, "2026-10-11"):
            grids.daily_box_means(text)

    def test_the_record_then_the_preliminary_days_after_it(self):
        def day(stamp, value, preliminary=False):
            return grids.BoxDay(stamp, {"nino34": value}, preliminary)
        record = [day("2026-09-26", 1.0), day("2026-09-27", 1.1), day("2026-09-28", 1.2)]
        recent = [day("2026-09-27", 9.9, True), day("2026-09-28", 9.9, True),
                  day("2026-09-29", 1.3, True), day("2026-10-12", 1.5, True)]
        spliced = grids.splice_days(record, recent)
        self.assertEqual([(d.day, d.means["nino34"], d.preliminary) for d in spliced], [
            ("2026-09-26", 1.0, False), ("2026-09-27", 1.1, False), ("2026-09-28", 1.2, False),
            ("2026-09-29", 1.3, True), ("2026-10-12", 1.5, True)])
        self.assertEqual(grids.splice_days([], recent), recent)
        self.assertEqual(grids.splice_days(record, []), record)

    def test_what_the_final_changed_on_the_days_both_carry_is_measured(self):
        def day(stamp, preliminary=False, **means):
            return grids.BoxDay(stamp, means, preliminary)
        record = [day("2026-09-26", nino34=1.0), day("2026-09-27", nino34=1.1, nino12=2.0),
                  day("2026-09-28", nino34=1.2, nino12=2.1)]
        recent = [day("2026-09-27", True, nino34=1.0, nino12=2.3),
                  day("2026-09-28", True, nino34=1.3),
                  day("2026-09-29", True, nino34=1.4, nino12=2.2)]
        moved = grids.revisions(record, recent)
        self.assertEqual(set(moved), {"nino34", "nino12"})
        self.assertEqual(moved["nino34"].days, 2)
        self.assertAlmostEqual(moved["nino34"].mean, 0.0)    # +0.1 and -0.1
        self.assertAlmostEqual(moved["nino34"].most, 0.1)
        self.assertEqual(moved["nino12"].days, 1)
        self.assertAlmostEqual(moved["nino12"].mean, -0.3)
        self.assertAlmostEqual(moved["nino12"].most, 0.3)
        self.assertEqual(grids.revisions(record, []), {})
        self.assertEqual(grids.revisions([], recent), {})


def _hov(labels, rows, lons=(200.125, 210.125)):
    return grids.Field(
        x=tuple(lons), y=tuple(float(i) for i in range(len(labels))),
        values=tuple(tuple(r) for r in rows), label="Equatorial SST anomaly",
        units="°C", x_name="longitude", y_name="time", as_of=labels[-1],
        y_labels=tuple(labels))


def _strip_csv(days, lons=(200.125, 210.125)):
    """Daily equatorial rows, two latitudes a day, the value the day's day of month."""
    from datetime import date, timedelta
    out = []
    for stamp in days:
        value = date.fromisoformat(stamp).day / 10.0
        for lat in (-0.875, 0.125):
            for k, lon in enumerate(lons):
                out.append((stamp, lat, lon, f"{value + k:.2f}"))
    return HEAD + "\n".join(f"{d}T12:00:00Z,0.0,{lat},{lon},{v}" for d, lat, lon, v in out) + "\n"


def _span(first, last, skip=()):
    from datetime import date, timedelta
    day, end, out = date.fromisoformat(first), date.fromisoformat(last), []
    while day <= end:
        if day.isoformat() not in skip:
            out.append(day.isoformat())
        day += timedelta(days=1)
    return out


class TestHovmollerTail(unittest.TestCase):
    """The weekly record carried on with the preliminary days, to the latest."""

    RECORD = _hov(("2026-09-08", "2026-09-15", "2026-09-22"),
                  ((0.1, 0.2), (0.3, 0.4), (0.5, 0.6)))

    def test_a_row_a_week_on_the_record_s_beat_then_the_latest_day(self):
        tail = grids.hovmoller_tail(self.RECORD, _strip_csv(_span("2026-09-15", "2026-10-12")))
        self.assertEqual(tail.y_labels, ("2026-09-08", "2026-09-15", "2026-09-22",
                                         "2026-09-29", "2026-10-06", "2026-10-12"))
        self.assertEqual(tail.y, tuple(float(i) for i in range(6)))
        self.assertEqual(tail.as_of, "2026-10-12")
        self.assertEqual(tail.preliminary, "2026-09-29")
        # The record's rows as they were; a new row is its day's strip mean.
        self.assertEqual(tail.values[:3], self.RECORD.values)
        self.assertEqual(tail.values[3], (2.9, 3.9))
        self.assertEqual(tail.values[5], (1.2, 2.2))
        self.assertEqual((tail.x, tail.label, tail.units), (self.RECORD.x, self.RECORD.label, "°C"))

    def test_the_latest_day_on_the_beat_is_not_drawn_twice(self):
        tail = grids.hovmoller_tail(self.RECORD, _strip_csv(_span("2026-09-23", "2026-10-06")))
        self.assertEqual(tail.y_labels[3:], ("2026-09-29", "2026-10-06"))

    def test_a_missing_day_takes_the_nearest_within_three_and_the_beat_holds(self):
        days = _span("2026-09-23", "2026-10-12", skip=("2026-09-29", "2026-10-06", "2026-10-05",
                                                        "2026-10-07", "2026-10-03", "2026-10-09"))
        tail = grids.hovmoller_tail(self.RECORD, _strip_csv(days))
        # 29 September is missing: 28 and 30 are as near, and the earlier is
        # taken. 5 to 7 October are missing: 4 and 8 are two away, and the
        # earlier is taken. The beat stays on the record's.
        self.assertEqual(tail.y_labels[3:], ("2026-09-28", "2026-10-04", "2026-10-12"))

    def test_a_week_with_no_day_near_it_is_a_blank_row_and_the_beat_holds(self):
        days = _span("2026-09-23", "2026-10-12", skip=_span("2026-09-26", "2026-10-02"))
        tail = grids.hovmoller_tail(self.RECORD, _strip_csv(days))
        self.assertEqual(tail.y_labels[3:], ("2026-09-29", "2026-10-06", "2026-10-12"))
        self.assertEqual(tail.values[3], (None, None))
        self.assertEqual(tail.values[4], (0.6, 1.6))
        self.assertEqual(tail.preliminary, "2026-09-29")

    def test_no_day_after_the_record_leaves_it_as_it_was(self):
        tail = grids.hovmoller_tail(self.RECORD, _strip_csv(_span("2026-09-15", "2026-09-22")))
        self.assertEqual(tail, self.RECORD)
        self.assertEqual(tail.preliminary, "")

    def test_no_record_is_no_hovmoller(self):
        self.assertIsNone(grids.hovmoller_tail(None, _strip_csv(_span("2026-09-15", "2026-10-12"))))

    def test_a_longitude_the_preliminary_lacks_is_a_gap(self):
        tail = grids.hovmoller_tail(self.RECORD, _strip_csv(_span("2026-09-23", "2026-09-29"),
                                                            lons=(200.125,)))
        self.assertEqual(tail.values[3], (2.9, None))


def _fetched(key, text, url=None):
    source = sources.SOURCES_BY_KEY[key]
    return sources.Fetched(source, text, "2026-10-14T10:12:00+00:00", False, "",
                           url=url or source.url)


PACIFIC = ("time,zlev,latitude,longitude,anom,sst\nUTC,m,degrees_north,degrees_east,degree_C,degree_C\n"
           + "\n".join(f"2026-10-12T12:00:00Z,0.0,{lat},{lon},{a},{s}" for lat, lon, a, s in (
               (-4.875, 200.125, 1.5, 28.6), (0.125, 200.125, 2.5, 29.1),
               (-4.875, 230.125, 2.5, 27.0), (0.125, 230.125, 3.5, 27.5))) + "\n")


class TestSpatialInRealTime(unittest.TestCase):
    """What the run makes of the preliminary and final products together."""

    def test_a_map_the_preliminary_served_says_its_day_is_preliminary(self):
        state = pipeline.build_spatial({"sst_pacific": _fetched("sst_pacific", PACIFIC)})
        self.assertEqual(state.sst_map.as_of, "2026-10-12")
        self.assertEqual(state.sst_map.preliminary, "2026-10-12")

    def test_a_map_the_final_served_is_not_preliminary(self):
        final = sources.SOURCES_BY_KEY["sst_pacific"].final
        state = pipeline.build_spatial({"sst_pacific": _fetched("sst_pacific", PACIFIC, final)})
        self.assertEqual(state.sst_map.preliminary, "")

    def test_a_map_ncei_served_says_which_analysis_it_is_alike(self):
        # NCEI names the depth axis "depth" and its units "Celsius"; the cells
        # and their values are CoastWatch's.
        pacific = sources.SOURCES_BY_KEY["sst_pacific"]
        ncei = PACIFIC.replace(",zlev,", ",depth,").replace("degree_C", "Celsius")
        coastwatch = pipeline.build_spatial({"sst_pacific": _fetched("sst_pacific", PACIFIC)})
        state = pipeline.build_spatial({"sst_pacific": _fetched("sst_pacific", ncei,
                                                                pacific.fallback[0])})
        self.assertEqual(state.sst_map.preliminary, "2026-10-12")
        self.assertEqual(state.sst_map.values, coastwatch.sst_map.values)
        state = pipeline.build_spatial({"sst_pacific": _fetched("sst_pacific", ncei,
                                                                pacific.final_fallback[0])})
        self.assertEqual(state.sst_map.preliminary, "")

    def test_the_global_map_says_which_product_served_it_as_well(self):
        world = PACIFIC.replace(",sst\n", "\n").replace(",degree_C\n", "\n", 1)
        world = "\n".join(line.rsplit(",", 1)[0] if line[:1].isdigit() else line
                          for line in world.splitlines()) + "\n"
        state = pipeline.build_spatial({"sst_global": _fetched("sst_global", world)})
        self.assertEqual(state.sst_global.preliminary, "2026-10-12")

    def test_the_daily_boxes_are_the_record_then_the_preliminary_days(self):
        record = _days_csv({"2026-10-10": CELLS["2026-10-11"], "2026-10-11": CELLS["2026-10-11"]})
        recent = _days_csv(CELLS)
        state = pipeline.build_spatial({"nino_daily": _fetched("nino_daily", record),
                                        "nino_daily_recent": _fetched("nino_daily_recent", recent)})
        self.assertEqual([(d.day, d.preliminary) for d in state.nino_daily], [
            ("2026-10-10", False), ("2026-10-11", False), ("2026-10-12", True)])

    def test_the_daily_boxes_stand_on_either_product_alone(self):
        recent = _days_csv(CELLS)
        state = pipeline.build_spatial({"nino_daily_recent": _fetched("nino_daily_recent", recent)})
        self.assertEqual([d.day for d in state.nino_daily], ["2026-10-11", "2026-10-12"])
        state = pipeline.build_spatial({"nino_daily": _fetched("nino_daily", recent)})
        self.assertFalse(any(d.preliminary for d in state.nino_daily))

    def test_the_days_alone_make_a_spatial_section(self):
        recent = _days_csv(CELLS)
        state = pipeline.build_spatial({"nino_daily_recent": _fetched("nino_daily_recent", recent)})
        self.assertTrue(state.available)
        self.assertFalse(grids.SpatialState().available)

    def test_a_broken_daily_answer_is_noted_and_costs_only_itself(self):
        state = pipeline.build_spatial({"nino_daily": _fetched("nino_daily", HEAD),
                                        "sst_pacific": _fetched("sst_pacific", PACIFIC)})
        self.assertEqual(state.nino_daily, ())
        self.assertTrue(any("daily Nino boxes" in note for note in state.notes))
        self.assertIsNotNone(state.sst_map)

    def test_the_hovmoller_runs_on_to_the_preliminary_s_latest_day(self):
        record = HEAD + "\n".join(
            f"{d}T12:00:00Z,0.0,{lat},{lon},0.5" for d in ("2026-09-08", "2026-09-15", "2026-09-22")
            for lat in (-0.875, 0.125) for lon in (200.125, 210.125)) + "\n"
        state = pipeline.build_spatial({
            "sst_hovmoller": _fetched("sst_hovmoller", record),
            "sst_hovmoller_recent": _fetched("sst_hovmoller_recent",
                                             _strip_csv(_span("2026-09-23", "2026-10-12")))})
        self.assertEqual(state.sst_hov.y_labels[-3:], ("2026-09-29", "2026-10-06", "2026-10-12"))
        self.assertEqual(state.sst_hov.preliminary, "2026-09-29")
        self.assertEqual(state.sst_hov.as_of, "2026-10-12")



# --- on the page ---------------------------------------------------------------
def _grid(as_of="2026-10-12", preliminary="2026-10-12", step=0.5):
    xs = tuple(200.125 + step * i for i in range(3))
    return grids.Field(x=xs, y=(-0.375, 0.125), values=((1.0, 2.0, 3.0), (1.5, 2.5, 3.5)),
                       label="Tropical Pacific SST anomaly", units="°C", as_of=as_of,
                       preliminary=preliminary)


def _days(first="2026-07-07", last="2026-10-12", prelim_from="2026-09-29", skip=()):
    out = []
    for i, stamp in enumerate(_span(first, last, skip)):
        means = {"nino34": 1.0 + i / 100.0, "nino4": 0.5 + i / 200.0,
                 "nino3": 1.5 + i / 100.0, "nino12": 2.0 - i / 100.0}
        out.append(grids.BoxDay(stamp, means, stamp >= prelim_from))
    return tuple(out)


def _week(stamp, nino34):
    from datetime import date
    return parsers.WeekObservation(date.fromisoformat(stamp), 24.0, 2.0, 26.0, 1.5,
                                   28.0, nino34, 29.0, 0.6)


# --- sea level ----------------------------------------------------------------
SLA_HEAD = "time,latitude,longitude,sla\nUTC,degrees_north,degrees_east,m\n"


def _sla(days, lats, lons) -> str:
    """ERDDAP's CSV of sea level, each cell's value telling its latitude and
    longitude apart."""
    rows = [f"{day}T00:00:00Z,{lat},{lon},{lat + lon / 1000:.6f}"
            for day in days for lat in lats for lon in lons]
    return SLA_HEAD + "\n".join(rows) + "\n"


class TestSeaLevel(unittest.TestCase):
    """Sea level from NOAA CoastWatch's own ERDDAP, a day or two behind, with
    the West Coast node's experimental product behind it, both asked for whole
    circles of latitude and kept to the Pacific's longitudes."""

    # Both datasets' longitudes: 179.875W to 179.875E.
    CIRCLE = tuple(-179.875 + 2.5 * k for k in range(144))
    STRIP = tuple(-179.875 + k for k in range(360))

    def test_sea_level_is_coastwatch_s_blended_altimetry_with_its_west_coast_node_behind_it(self):
        self.assertEqual(sources.SSH,
                         "https://coastwatch.noaa.gov/erddap/griddap/noaacwBLENDEDsshDaily.csv")
        self.assertEqual(sources.SSH_EXPERIMENTAL,
                         "https://coastwatch.pfeg.noaa.gov/erddap/griddap/nesdisSSH1day.csv")
        for key in ("ssh_pacific", "ssh_hovmoller"):
            with self.subTest(key=key):
                source = sources.SOURCES_BY_KEY[key]
                self.assertTrue(source.url.startswith(sources.SSH + "?"), source.url)
                self.assertEqual(source.fallback,
                                 (source.url.replace(sources.SSH, sources.SSH_EXPERIMENTAL),))
                self.assertEqual((source.final, source.tier), ("", "spatial"))
                self.assertNotIn("experimental", source.cadence)

    def test_the_pacific_is_asked_for_whole_circles_on_the_points_it_was_sampled_on(self):
        # The longitudes run -180 to 180 and the tropical Pacific crosses the
        # date line: whole circles of latitude from 179.875W, every 2.5 degrees
        # for the map and every degree for the strip, carry the very points
        # the 0-360 requests sampled from 120.125E. The strip's rows are a
        # week apart back from the latest day, as the SST Hovmoller's are.
        self.assertEqual(_query(sources.SOURCES_BY_KEY["ssh_pacific"].url),
                         "sla[last][(-24.875):10:(25.125)][(-179.875):10:(179.875)]")
        self.assertEqual(_query(sources.SOURCES_BY_KEY["ssh_hovmoller"].url),
                         "sla[last-483:7:last][(-1.875):4:(2.125)][(-179.875):4:(179.875)]")
        self.assertLessEqual({120.125 + 2.5 * k for k in range(69)},
                             {lon % 360 for lon in self.CIRCLE})
        self.assertEqual(sources.SSH_MAP_LONS, (120.125, 290.125))
        self.assertEqual(sources.SSH_STRIP_LONS, (120.125, 280.125))

    def test_a_map_of_whole_circles_keeps_the_pacific_s_longitudes_east_of_greenwich(self):
        text = _sla(["2026-10-13"], (-0.875, 0.125),
                    (-179.875, -70.125, -67.375, 0.125, 119.875, 120.125, 179.875))
        grid = grids.grid_map(text, "sla", "Sea surface height anomaly", "m",
                              within=(120.125, 290.125))
        self.assertEqual(grid.x, (120.125, 179.875, 180.125, 289.875))
        self.assertEqual(grid.y, (-0.875, 0.125))
        self.assertEqual(grid.values[1], tuple(round(0.125 + lon / 1000, 6) for lon in
                                               (120.125, 179.875, -179.875, -70.125)))
        self.assertEqual(grid.as_of, "2026-10-13")

    def test_a_copy_east_of_greenwich_already_is_kept_as_it_was(self):
        # A copy the 0-360 requests made, served while both servers fail.
        text = _sla(["2026-09-28"], (0.125,), (120.125, 200.125, 290.125))
        grid = grids.grid_map(text, "sla", "Sea surface height anomaly", "m",
                              within=(120.125, 290.125))
        self.assertEqual(grid, grids.grid_map(text, "sla", "Sea surface height anomaly", "m"))

    def test_a_hovmoller_of_whole_circles_keeps_the_strip_s_longitudes(self):
        text = _sla(["2026-10-06", "2026-10-13"], (-0.875, 0.125, 1.125),
                    (-179.875, -80.125, -78.875, 119.875, 120.125))
        grid = grids.grid_hovmoller(text, "sla", "Equatorial sea surface height anomaly", "m",
                                    within=(120.125, 280.125))
        self.assertEqual(grid.x, (120.125, 180.125, 279.875))
        self.assertEqual(grid.y_labels, ("2026-10-06", "2026-10-13"))
        self.assertAlmostEqual(grid.values[1][1], 0.125 - 0.179875, places=9)

    def test_the_run_s_sea_level_is_the_pacific_s(self):
        map_lats = tuple(-24.875 + 2.5 * k for k in range(21))
        strip_lats = (-1.875, -0.875, 0.125, 1.125, 2.125)
        state = pipeline.build_spatial({
            "ssh_pacific": _fetched("ssh_pacific", _sla(["2026-10-13"], map_lats, self.CIRCLE)),
            "ssh_hovmoller": _fetched("ssh_hovmoller",
                                      _sla(["2026-10-06", "2026-10-13"], strip_lats, self.STRIP)),
        })
        self.assertEqual((len(state.ssh_map.x), state.ssh_map.x[0], state.ssh_map.x[-1]),
                         (69, 120.125, 290.125))
        self.assertEqual(len(state.ssh_map.y), 21)
        self.assertEqual((len(state.ssh_hov.x), state.ssh_hov.x[0], state.ssh_hov.x[-1]),
                         (161, 120.125, 280.125))
        self.assertEqual(state.ssh_hov.as_of, "2026-10-13")
        self.assertEqual(state.notes, [])

    def _state(self, age, served=lambda source: source.url):
        lats = tuple(-24.875 + 2.5 * k for k in range(21))
        pacific, strip = sources.SOURCES_BY_KEY["ssh_pacific"], sources.SOURCES_BY_KEY["ssh_hovmoller"]
        state = pipeline.build_spatial({
            "ssh_pacific": _fetched("ssh_pacific", _sla(["2026-10-13"], lats, self.CIRCLE),
                                    served(pacific)),
            "ssh_hovmoller": _fetched("ssh_hovmoller",
                                      _sla(["2026-10-06", "2026-10-13"], (0.125,), self.STRIP),
                                      served(strip)),
        })
        state.stale.update(ssh_map=age, ssh_hov=age)
        return state

    def test_the_sea_level_card_says_whose_altimetry_it_is_and_how_far_behind_past_four_days(self):
        card = fields.ssh_card(self._state(4))
        self.assertIn("blend of the altimeters", card)
        self.assertIn("near-real-time passes; the", card)
        self.assertNotIn("experimental", card)
        self.assertNotIn("behind", card)
        self.assertIn("5 days behind", fields.ssh_card(self._state(5)))

    def test_the_sea_level_hovmoller_says_whose_altimetry_it_is_and_how_far_behind(self):
        card = fields.hov_card(self._state(4))
        self.assertIn("Altimetry: NOAA CoastWatch", card)
        self.assertIn("near-real-time passes. ", card)
        self.assertNotIn("experimental", card)
        self.assertNotIn("behind", card)
        self.assertIn("5 days behind", fields.hov_card(self._state(5)))

    def test_sea_level_the_west_coast_node_served_is_said_to_be_its_experimental_product(self):
        state = self._state(17, served=lambda source: source.fallback[0])
        for card in (fields.ssh_card(state), fields.hov_card(state)):
            self.assertIn("experimental product of the altimeters", card)
            self.assertIn("serving while CoastWatch", card)
            self.assertNotIn("near-real-time", card)
            self.assertNotIn("same altimetry", card)
            self.assertNotIn("weeks behind", card)
            self.assertIn("17 days behind", card)

    def test_a_field_past_four_days_says_how_far_behind_in_its_chip_alone(self):
        # CoastWatch's own copy serving through an outage of its ERDDAP: the
        # words name the product and the chip says how far behind the field
        # is, rather than words saying "a day or two" beside a chip saying 9.
        state = self._state(9)
        for card in (fields.ssh_card(state), fields.hov_card(state)):
            self.assertIn("9 days behind", card)
            self.assertEqual(card.count("behind"), 1)

    def test_a_sea_level_copy_of_the_old_shape_is_said_to_be_altimetry_and_no_more(self):
        old = ("https://coastwatch.pfeg.noaa.gov/erddap/griddap/nesdisSSH1day_Lon0360.csv"
               "?sla%5Blast%5D")
        state = self._state(17, served=lambda source: old)
        self.assertIn("This is satellite altimetry;", fields.ssh_card(state))
        self.assertIn('<p class="subcaption">Altimetry. ', fields.hov_card(state))


class TestSeaLevelCopies(_Fetching, unittest.TestCase):
    """The copies the runner kept of the West Coast node's 0-360 dataset, gone
    since 14 October, against CoastWatch's own ERDDAP and the West Coast node."""

    OLD = ("https://coastwatch.pfeg.noaa.gov/erddap/griddap/nesdisSSH1day_Lon0360.csv"
           "?sla%5Blast%5D%5B%28-25%29:10:%2825%29%5D%5B%28120%29:10:%28290%29%5D")

    def setUp(self):
        super().setUp()
        self.source = sources.SOURCES_BY_KEY["ssh_pacific"]
        old = _sla(["2026-09-28"], (0.125,), (120.125, 200.125)).encode("utf-8")
        (self.raw / "ssh_pacific.cache").write_bytes(old)
        (self.raw / "ssh_pacific.meta.json").write_text(json.dumps({
            "url": self.OLD, "fetched_at": "2026-10-14T16:25:29+00:00",
            "sha256": hashlib.sha256(old).hexdigest(), "probe": "2026-09-28T00:00:00Z"}),
            encoding="utf-8")

    def test_an_old_copy_gives_way_to_the_west_coast_node_s_same_day_while_coastwatch_is_down(self):
        west = self.source.fallback[0]
        text = _sla(["2026-09-28"], (0.125,), (-179.875, 120.125))
        got = self.fetch({self.probe(west): "time\nUTC\n2026-09-28T00:00:00Z\n", west: text})
        self.assertEqual(self.asked[0], self.probe(self.source.url))
        self.assertEqual((got.text, got.url, got.from_cache), (text, west, False))
        self.assertIn(f"served by {west}", got.warnings[0])

    def test_an_old_copy_serves_while_both_servers_are_down(self):
        got = self.fetch({})
        self.assertEqual((got.url, got.from_cache), (self.OLD, True))
        state = pipeline.build_spatial({"ssh_pacific": got})
        self.assertEqual(state.ssh_map.x, (120.125, 200.125))
        self.assertEqual(state.ssh_map.note, "")


class TestPreliminaryOnThePage(unittest.TestCase):
    """Each picture says which of NOAA's analyses it shows."""

    def test_the_pacific_map_says_its_day_is_the_preliminary_analysis(self):
        html = fields.sst_map(_grid(), {}, None)
        self.assertIn("for 2026-10-12, NOAA&rsquo;s preliminary analysis", html)
        self.assertIn("the final replaces it about two weeks on", html)

    def test_a_map_from_the_final_analysis_says_so_and_how_far_behind_it_is(self):
        from datetime import date, timedelta
        old = (date.today() - timedelta(days=16)).isoformat()
        html = fields.sst_map(_grid(as_of=old, preliminary=""), {}, None)
        self.assertIn(f"for {old}, NOAA&rsquo;s final analysis", html)
        self.assertIn("16 days behind", html)
        recent = (date.today() - timedelta(days=2)).isoformat()
        self.assertNotIn("days behind", fields.sst_map(_grid(as_of=recent, preliminary=""), {}, None))

    def test_the_global_map_says_which_analysis_it_is_as_well(self):
        world = _grid()
        self.assertIn("for 2026-10-12, NOAA&rsquo;s preliminary analysis", fields.global_map(world))

    def test_the_hovmoller_says_where_its_preliminary_rows_begin(self):
        hov = _hov(("2026-09-15", "2026-09-22", "2026-09-29", "2026-10-06", "2026-10-12"),
                   ((0.1, 0.2),) * 5)
        hov = grids.Field(**{**hov.__dict__, "preliminary": "2026-09-29"})
        html = fields.hov_card(grids.SpatialState(sst_hov=hov))
        self.assertIn("from 2026-09-29 NOAA&rsquo;s preliminary analysis, its last row "
                      "the latest day, 2026-10-12", html)
        plain = fields.hov_card(grids.SpatialState(sst_hov=_hov(("2026-09-15", "2026-09-22"),
                                                                ((0.1, 0.2), (0.3, 0.4)))))
        self.assertNotIn("preliminary", plain)


class TestDailyCard(unittest.TestCase):
    """The four boxes day by day, with CPC's weeks beside them."""

    def card(self, days=None, weeks=()):
        return daily.nino_card(_days() if days is None else days, list(weeks))

    def test_one_line_a_box_in_its_own_colour_with_a_legend(self):
        html = self.card()
        self.assertIn('<section class="card" id="nino-daily">', html)
        for colour in ("var(--s1)", "var(--s2)", "var(--s3)", "var(--s4)"):
            self.assertEqual(html.count(f'class="dayline" stroke="{colour}"'), 1, colour)
        for name in ("Nino-3.4", "Nino-4", "Nino-3", "Nino-1+2"):
            self.assertIn(f"</span>{name}</span>", html)

    def test_each_line_ends_on_its_latest_value(self):
        html = self.card()
        days = _days()
        last = days[-1].means
        for key, name in (("nino34", "Nino-3.4"), ("nino12", "Nino-1+2")):
            self.assertIn(f">{name} {last[key]:+.2f}</text>", html)

    def test_the_preliminary_days_are_shaded_and_named(self):
        html = self.card()
        self.assertEqual(html.count('class="prelim"'), 1)
        self.assertIn(">preliminary</text>", html)
        self.assertIn("then NOAA&rsquo;s preliminary analysis from 2026-09-29 to 2026-10-12", html)
        final_only = self.card(days=_days(prelim_from="9999"))
        self.assertNotIn('class="prelim"', final_only)
        self.assertNotIn("preliminary analysis from", final_only)

    def test_a_missing_day_breaks_the_lines(self):
        html = self.card(days=_days(skip=("2026-08-15",)))
        line = re.search(r'<path d="([^"]+)" class="dayline" stroke="var\(--s1\)"', html).group(1)
        self.assertEqual(line.count("M"), 2)
        whole = re.search(r'<path d="([^"]+)" class="dayline" stroke="var\(--s1\)"', self.card()).group(1)
        self.assertEqual(whole.count("M"), 1)

    def test_every_day_has_a_hover_with_all_four_boxes(self):
        days = _days()
        html = self.card()
        self.assertEqual(html.count('class="hit"'), len(days))
        last = days[-1].means
        self.assertIn('data-label="12 Oct 2026, preliminary"', html)
        self.assertIn(f'data-value="Nino-3.4 {last["nino34"]:+.2f} °C"', html)
        self.assertIn(f'Nino-4 {last["nino4"]:+.2f} · Nino-3 {last["nino3"]:+.2f} · '
                      f'Nino-1+2 {last["nino12"]:+.2f}', html)

    def test_cpc_s_weeks_in_the_window_are_hollow_dots_and_the_rest_are_not_drawn(self):
        weeks = [_week("2026-06-03", 0.9), _week("2026-09-02", 1.6), _week("2026-10-07", 1.8)]
        html = self.card(weeks=weeks)
        self.assertEqual(html.count('class="weekdot"'), 2)
        self.assertIn("CPC traditional weekly Nino-3.4", html)
        self.assertNotIn("CPC weekly", self.card())

    def test_the_caption_gives_the_latest_value_and_the_week_s_change(self):
        days = _days()
        html = self.card()
        now, week_ago = days[-1].means["nino34"], days[-8].means["nino34"]
        self.assertIn(f"Nino-3.4 is <strong>{now:+.2f} °C</strong> on 12 Oct 2026", html)
        self.assertIn(f"{now - week_ago:+.2f} °C on the week", html)

    def test_the_table_lists_every_day_latest_first(self):
        days = _days()
        html = self.card()
        table = html[html.index("<details"):]
        self.assertEqual(table.count("<tr>"), len(days) + 1)
        self.assertLess(table.index("2026-10-12"), table.index("2026-10-11"))

    def test_fewer_than_two_days_draw_no_card(self):
        self.assertEqual(self.card(days=()), "")
        self.assertEqual(self.card(days=_days(first="2026-10-12")), "")

    def test_month_ticks_name_each_month_once(self):
        html = self.card()
        for month in ("Aug", "Sep", "Oct"):
            self.assertEqual(html.count(f'class="tick">{month}</text>'), 1, month)

    def test_the_caption_gives_each_analysis_s_base_and_measures_the_days_against_cpc_s_weeks(self):
        # OISST's anomaly is against its own 1971-2000 climatology and CPC's
        # weekly index against 1991-2020, so the two differ by more than the
        # analyses do: the card says so, and measures it on the weeks both
        # carry, a CPC week being the seven days centred on its Wednesday.
        days = _days()
        stamps = [d.day for d in days]
        centre = stamps.index("2026-09-02")
        mean = sum(d.means["nino34"] for d in days[centre - 3:centre + 4]) / 7
        html = self.card(weeks=[_week("2026-09-02", 1.2)])
        self.assertIn("1971&ndash;2000", html)
        self.assertIn("1991&ndash;2020", html)
        self.assertIn(f"On the one week both carry, the days&rsquo; Nino-3.4 averages "
                      f"{mean - 1.2:.2f} °C warmer than CPC&rsquo;s", html)
        both = self.card(weeks=[_week("2026-09-02", 1.2), _week("2026-09-09", 1.85)])
        later = stamps.index("2026-09-09")
        second = sum(d.means["nino34"] for d in days[later - 3:later + 4]) / 7
        offset = ((mean - 1.2) + (second - 1.85)) / 2
        self.assertIn(f"On the 2 weeks both carry, the days&rsquo; Nino-3.4 averages "
                      f"{abs(offset):.2f} °C {'warmer' if offset >= 0 else 'cooler'} than CPC&rsquo;s", both)

    def test_a_cpc_week_short_of_five_drawn_days_is_drawn_but_not_measured(self):
        # Centred on the first day: four of its seven days are drawn.
        html = self.card(weeks=[_week("2026-07-07", 1.0)])
        self.assertEqual(html.count('class="weekdot"'), 1)
        self.assertNotIn("both carry", html)

    def test_days_within_cpc_s_tenths_of_its_week_say_so(self):
        # CPC publishes its weekly index to the tenth.
        days = _days()
        centre = [d.day for d in days].index("2026-09-02")
        mean = sum(d.means["nino34"] for d in days[centre - 3:centre + 4]) / 7
        html = self.card(weeks=[_week("2026-09-02", round(mean, 1))])
        self.assertIn("the days&rsquo; Nino-3.4 agrees with CPC&rsquo;s within its rounding "
                      "to tenths", html)
        self.assertNotIn("hundredth", html)

    def test_the_dots_are_cpc_s_traditional_weekly_index(self):
        html = self.card(weeks=[_week("2026-09-02", 1.2)])
        self.assertIn("CPC&rsquo;s traditional weekly Nino-3.4, the hollow dots, is against "
                      "1991&ndash;2020", html)
        self.assertIn("CPC traditional weekly Nino-3.4</span>", html)

    def test_a_card_whose_latest_day_is_old_says_how_far_behind_it_is(self):
        from datetime import date, timedelta
        start = (date.today() - timedelta(days=60)).isoformat()
        old = (date.today() - timedelta(days=16)).isoformat()
        html = self.card(days=_days(first=start, last=old, prelim_from="9999"))
        self.assertIn('<span class="chip chip-warning">16 days behind</span>', html)
        recent = (date.today() - timedelta(days=2)).isoformat()
        self.assertNotIn("days behind", self.card(days=_days(first=start, last=recent)))

    def test_the_card_says_how_far_the_final_moved_the_preliminary_s_days(self):
        moved = {"nino34": grids.Revision(13, 0.07, 0.2), "nino4": grids.Revision(13, -0.01, 0.05),
                 "nino12": grids.Revision(13, 0.14, 0.34)}
        html = daily.nino_card(_days(), [], moved)
        self.assertIn("On the 13 days both analyses carry, the final runs 0.07 °C warmer than the "
                      "preliminary in Nino-3.4 on average, and differs by up to 0.20 °C on a day "
                      "(0.34 °C in Nino-1+2): about how far the shaded days may yet move.", html)
        cooler = daily.nino_card(_days(), [], {"nino34": grids.Revision(5, -0.04, 0.09)})
        self.assertIn("the final runs 0.04 °C cooler than the preliminary in Nino-3.4 on average, "
                      "and differs by up to 0.09 °C on a day: about", cooler)
        same = daily.nino_card(_days(), [], {"nino34": grids.Revision(4, 0.001, 0.1)})
        self.assertIn("the final and the preliminary agree in Nino-3.4 on average, and differ "
                      "by up to 0.10 °C on a day: about", same)
        # Nothing to say with no shaded days.
        self.assertNotIn("both analyses carry",
                         daily.nino_card(_days(prelim_from="9999"), [], moved))

    def test_the_threshold_s_label_is_drawn_over_the_lines(self):
        html = self.card()
        self.assertGreater(html.index("El Nino threshold +0.5</text>"), html.rindex('class="dayline"'))

    def test_the_line_ends_are_labelled_clear_of_each_other(self):
        days = list(_days(last="2026-08-30"))
        level = {"nino34": 1.0, "nino4": 1.0, "nino3": 1.01, "nino12": 0.99}
        days[-1] = grids.BoxDay(days[-1].day, level, days[-1].preliminary)
        html = self.card(days=tuple(days))
        ys = sorted(float(y) for y in re.findall(r'<text x="[\d.]+" y="([\d.]+)" class="endlabel">', html))
        self.assertEqual(len(ys), 4)
        self.assertTrue(all(b - a >= 13.0 - 1e-6 for a, b in zip(ys, ys[1:])), ys)
        height = float(re.search(r'<svg viewBox="0 0 \d+ (\d+)"', html).group(1))
        self.assertTrue(0 < ys[0] and ys[-1] < height, ys)


class TestFeedWarnings(unittest.TestCase):
    """What went wrong on the way to each feed is said beside it: on the
    provenance card, in the JSON and in the report."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.raw = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def fetch(self, key, answers, offline=False):
        get = answering(answers, missing="HTTP Error 404: Not Found")
        with mock.patch.object(sources, "_http_get", side_effect=get):
            return sources.fetch(sources.SOURCES_BY_KEY[key], self.raw, offline=offline)

    def fetches(self):
        """ONI as on any day; the Pacific map from the final, the preliminary
        failing; NHC's index failing with no copy to stand in."""
        pacific = sources.SOURCES_BY_KEY["sst_pacific"]
        return {
            "oni": self.fetch("oni", {sources.SOURCES_BY_KEY["oni"].url: "SEAS YR TOTAL ANOM\n"}),
            "sst_pacific": self.fetch("sst_pacific", {sources.probe_url(pacific.final): FINAL_LAST,
                                                      pacific.final: csv("row")}),
            "nhc_current": self.fetch("nhc_current", {}),
        }

    def data(self, fetched):
        return " ".join("\n".join(report._section_data(
            SimpleNamespace(fetched=fetched, warnings=[]))).split())

    def test_the_provenance_card_says_beside_each_feed_what_went_wrong(self):
        oni, pacific, nhc = re.findall(r"<li>.*?</li>", dashboard._provenance_card(self.fetches()), re.S)
        self.assertNotIn('class="said"', oni)
        said = re.search(r'<span class="said">(.*?)</span>', pacific).group(1)
        self.assertTrue(said.startswith("HTTP Error 404: Not Found ("), said)
        self.assertIn("served by", said)
        self.assertIn('<span class="said">HTTP Error 404: Not Found (', nhc)

    def test_the_report_gives_each_failure_s_reason_first(self):
        text = self.data(self.fetches())
        self.assertIn("nhc_current: HTTP Error 404: Not Found", text)
        self.assertIn("FEED WARNINGS: - sst_pacific: HTTP Error 404: Not Found (", text)

    def test_the_report_counts_the_feeds_checked_and_found_unchanged(self):
        def live(key, unchanged):
            return sources.Fetched(sources.SOURCES_BY_KEY[key], "x", "2026-10-14T09:00:00+00:00",
                                   False, "", unchanged=unchanged)
        text = self.data({"sst_global": live("sst_global", True), "oni": live("oni", False)})
        self.assertIn("2 feeds fetched live (1 checked and unchanged since downloaded), "
                      "0 served from cache, 0 failed.", text)

    def resting(self):
        source = sources.SOURCES_BY_KEY["tao_temperature"]
        return {
            "tao_temperature": sources.Fetched(source, "x", "2026-10-16T13:25:21+00:00", False, "",
                                               url=source.url, rested=True),
            "sst_global": sources.Fetched(sources.SOURCES_BY_KEY["sst_global"], "x",
                                          "2026-10-14T09:00:00+00:00", False, "", unchanged=True),
            "oni": sources.Fetched(sources.SOURCES_BY_KEY["oni"], "x", "2026-10-16T13:35:20+00:00",
                                   False, ""),
        }

    def test_the_report_counts_the_tables_downloaded_within_the_hour_apart(self):
        text = self.data(self.resting())
        self.assertIn("3 feeds fetched live (1 checked and unchanged since downloaded; 1 downloaded "
                      "within the hour and asked again hourly, as ERDDAP's tables cannot say whether "
                      "they changed), 0 served from cache, 0 failed.", text)

    def test_the_provenance_card_says_a_resting_table_was_downloaded_within_the_hour(self):
        card = dashboard._provenance_card(self.resting())
        tao, grid, oni = re.findall(r"<li>.*?</li>", card, re.S)
        self.assertIn('<span class="pill live">downloaded 2026-10-16T13:25:21+00:00, asked again hourly</span>',
                      tao)
        self.assertIn('<span class="pill live">unchanged since 2026-10-14T09:00:00+00:00</span>', grid)
        self.assertIn('<span class="pill live">live 2026-10-16T13:35:20+00:00</span>', oni)
        caption = " ".join(re.search(r'<p class="caption">(.*?)</p>', card, re.S).group(1).split())
        self.assertEqual(caption, "Every number on this page comes from these feeds: 1 fetched live this run; "
                                  "1 checked live and unchanged since they were downloaded; 1 downloaded "
                                  "within the hour and asked again hourly, as ERDDAP&rsquo;s tables cannot "
                                  "say whether they changed.")

    def test_one_reason_for_many_feeds_is_said_once(self):
        # An offline run reads every feed from its copy, for the one reason.
        fetched = {}
        for key in ("oni", "roni"):
            self.fetch(key, {sources.SOURCES_BY_KEY[key].url: "SEAS YR TOTAL ANOM\n"})
            fetched[key] = self.fetch(key, {}, offline=True)
        self.assertEqual(fetched["oni"].warnings, ["live fetch failed (offline mode requested)"])
        text = self.data(fetched)
        self.assertEqual(text.count("offline mode requested"), 1)
        self.assertIn("- oni, roni: live fetch failed (offline mode requested)", text)


def _realtime_fetch_all(real):
    """The cached run, as if OISST's preliminary had served the maps today and
    the daily boxes and the Hovmoller's latest days had come with it."""
    def fetch_all(*args, **kwargs):
        fetched = real(*args, **kwargs)
        pac = fetched["sst_pacific"]
        fetched["sst_pacific"] = sources.Fetched(pac.source, pac.text, pac.fetched_at, False,
                                                 pac.sha256, url=pac.source.url)
        world = fetched["sst_global"]
        fetched["sst_global"] = sources.Fetched(world.source, world.text, world.fetched_at,
                                                False, world.sha256, url=world.source.url,
                                                unchanged=True)
        record = _days_csv({d: CELLS["2026-10-11"] for d in _span("2026-09-01", "2026-09-28")})
        recent = _days_csv({d: CELLS["2026-10-12"] for d in _span("2026-09-20", "2026-10-12")})
        strip = HEAD + "\n".join(
            f"{d}T12:00:00Z,0.0,{lat},{120.125 + k},0.75"
            for d in _span("2026-09-14", "2026-10-12") for lat in (-0.875, 0.125)
            for k in range(161)) + "\n"
        poles = _days_csv({d: [(0.125, 60.125, "1.0"), (-5.125, 100.125, "0.25")]
                           for d in _span("2026-09-01", "2026-09-28")})
        poles_recent = _days_csv({d: [(0.125, 60.125, "1.1"), (-5.125, 100.125, "0.25")]
                                  for d in _span("2026-09-20", "2026-10-12")})
        soi = "Year Day  Tahiti  Darwin     SOI\n" + "".join(
            f"2026 {n:3d} 1013.00 1009.00 {(150 - n) / 10:7.2f}\n" for n in range(150, 287))
        for key, text in (("nino_daily", record), ("nino_daily_recent", recent),
                          ("sst_hovmoller_recent", strip), ("iod_daily", poles),
                          ("iod_daily_recent", poles_recent), ("soi_daily", soi)):
            source = sources.SOURCES_BY_KEY[key]
            fetched[key] = sources.Fetched(source, text, "2026-10-14T10:12:00+00:00", False, "",
                                           url=source.url)
        fetched["nino_daily"].warnings.append("kept no copy: [Errno 28] No space left on device")
        fetched["tao_temperature"] = replace(fetched["tao_temperature"], from_cache=False, rested=True)
        return fetched
    return fetch_all


CACHE = ROOT / "data" / "raw"


@unittest.skipUnless((CACHE / "oni.cache").exists(), "no cached feeds; run `python track.py` once first")
class TestOneRunOnePatience(unittest.TestCase):
    """A run has one patience with its servers, for every feed and for the
    storms' files fetched after them (pipeline.run)."""

    def test_every_feed_of_a_run_and_its_storms_files_share_the_run_s_patience(self):
        seen = []
        real_fetch, real_all = sources.fetch, sources.fetch_all

        def fetch(source, raw_dir, offline=False, patience=None):
            seen.append(patience)
            return real_fetch(source, raw_dir, offline, patience)

        def fetch_all(*args, **kwargs):
            seen.append(kwargs.get("patience"))
            return real_all(*args, **kwargs)

        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(sources, "fetch", fetch), \
                mock.patch.object(sources, "fetch_all", fetch_all):
            pipeline.run(CACHE, Path(tmp) / "p.db", offline=True, leads=9)
        self.assertIsInstance(seen[0], sources.Patience)
        # Every feed of the registry, and then the storms' files.
        self.assertGreater(len(seen), 1 + len(sources.SOURCES))
        self.assertTrue(all(patience is seen[0] for patience in seen))


@unittest.skipUnless((CACHE / "oni.cache").exists() and (CACHE / "sst_pacific.cache").exists(),
                     "no cached feeds; run `python track.py` once first")
class TestRealTimeRun(unittest.TestCase):
    """A whole run with the preliminary product, on every page it reaches."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with mock.patch.object(sources, "fetch_all", _realtime_fetch_all(sources.fetch_all)):
            cls.state = pipeline.run(CACHE, Path(cls.tmp.name) / "rt.db", offline=True, leads=9)
        cls.html = dashboard.render(cls.state)
        cls.data = dashboard.payload(cls.state)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_daily_card_follows_the_map_it_is_the_boxes_of(self):
        self.assertIn('id="nino-daily"', self.html)
        self.assertLess(self.html.index('id="sst-map"'), self.html.index('id="nino-daily"'))
        self.assertLess(self.html.index('id="nino-daily"'), self.html.index('id="hovmoller"'))

    def test_the_dipole_follows_the_boxes_and_the_soi_the_walker_circulation(self):
        page = self.html
        self.assertLess(page.index('id="nino-daily"'), page.index('id="iod-daily"'))
        self.assertLess(page.index('id="iod-daily"'), page.index('id="hovmoller"'))
        self.assertLess(page.index('id="walker"'), page.index('id="soi-daily"'))
        self.assertLess(page.index('id="soi-daily"'), page.index('id="forecast"'))

    def test_the_maps_and_the_hovmoller_say_preliminary(self):
        self.assertIn("NOAA&rsquo;s preliminary analysis", self.html[self.html.index('id="sst-map"'):])
        self.assertEqual(self.state.spatial.sst_hov.y_labels[-1], "2026-10-12")
        self.assertTrue(self.state.spatial.sst_hov.preliminary)

    def test_each_feed_in_the_json_says_whether_it_rested(self):
        feeds = self.data["feeds"]
        self.assertEqual(self.data["schema"], 13)
        self.assertEqual((feeds["tao_temperature"]["rested"], feeds["tao_temperature"]["unchanged"]),
                         (True, False))
        self.assertEqual((feeds["sst_global"]["rested"], feeds["sst_global"]["unchanged"]), (False, True))
        self.assertTrue(all(set(feed) >= {"rested", "unchanged", "from_cache"} for feed in feeds.values()))

    def test_the_json_carries_the_days_and_which_analysis_each_field_is(self):
        spatial = self.data["spatial"]
        self.assertEqual(self.data["schema"], 13)
        self.assertEqual(spatial["fields"]["sst_map"]["preliminary"],
                         self.state.spatial.sst_map.as_of)
        self.assertEqual(spatial["fields"]["sst_hov"]["preliminary"],
                         self.state.spatial.sst_hov.preliminary)
        days = spatial["nino_daily"]
        self.assertEqual(days[0]["day"], "2026-09-01")
        self.assertEqual(days[-1]["day"], "2026-10-12")
        self.assertEqual([d["preliminary"] for d in days[-15:]], [False] + [True] * 14)
        self.assertFalse(days[0]["preliminary"])
        self.assertEqual(set(days[-1]), {"day", "preliminary", "nino4", "nino34", "nino3", "nino12"})

    def test_the_json_gives_the_dipole_day_by_day_and_what_the_final_changed(self):
        spatial = self.data["spatial"]
        days = spatial["iod_daily"]
        self.assertEqual((days[0]["day"], days[-1]["day"]), ("2026-09-01", "2026-10-12"))
        self.assertEqual([d["preliminary"] for d in days[-15:]], [False] + [True] * 14)
        self.assertEqual(days[-1], {"day": "2026-10-12", "preliminary": True, "west": 1.1,
                                    "east": 0.25, "dmi": 0.85})
        self.assertEqual(set(spatial["iod_revision"]), {"west", "east", "dmi"})
        self.assertEqual(spatial["iod_revision"]["dmi"], {"days": 9, "mean": -0.1, "most": 0.1})

    def test_the_json_gives_the_soi_s_days_the_card_draws(self):
        soi = self.data["atmosphere"]["soi_daily"]
        self.assertEqual(len(soi), daily.SOI_DAYS)
        self.assertEqual((soi[0]["day"], soi[-1]["day"]), ("2026-06-16", "2026-10-13"))
        self.assertEqual(soi[-1], {"day": "2026-10-13", "tahiti": 1013.0, "darwin": 1009.0,
                                   "soi": -13.6, "soi30": -12.15, "soi90": -9.15})

    def test_the_json_names_the_address_each_feed_was_served_from(self):
        feeds = self.data["feeds"]
        self.assertEqual(feeds["sst_pacific"]["url"], sources.SOURCES_BY_KEY["sst_pacific"].url)
        self.assertTrue(feeds["sst_global"]["unchanged"])
        self.assertFalse(feeds["sst_pacific"]["unchanged"])

    def test_the_json_gives_each_feed_s_warnings(self):
        feeds = self.data["feeds"]
        self.assertEqual(feeds["nino_daily"]["warnings"],
                         ["kept no copy: [Errno 28] No space left on device"])
        self.assertEqual(feeds["oni"]["warnings"], ["live fetch failed (offline mode requested)"])
        self.assertEqual(feeds["sst_pacific"]["warnings"], [])

    def test_the_provenance_says_a_feed_with_no_new_day_was_not_downloaded_again(self):
        card = self.html[self.html.index('id="provenance"'):]
        self.assertIn("unchanged since", card)
        self.assertIn("checked live and unchanged since they were downloaded", card)

    def test_cpc_s_weeks_are_named_by_the_day_they_are_centred_on(self):
        # CPC's weekly files date each week by its centre, a Wednesday ("week
        # centered on"), not by its end: in the table, on the gauge and on the map.
        world = worldmap.section(self.state)
        for page in (self.html, world):
            self.assertFalse("week ending" in page.lower(), "a CPC week named by its end")
        self.assertIn("Week centred on", self.html)
        self.assertIn("Nino-3.4 weekly", self.html)
        self.assertIn("week centred on", world)

    def test_the_report_gives_the_boxes_day_by_day(self):
        text = report.render(self.state)
        self.assertIn("Day by day, from OISST", text)
        self.assertIn("Nino-3.4", text)
        self.assertIn("2026-10-12 (preliminary)", text)
        self.assertIn("On the 9 days both analyses carry, the final runs", " ".join(text.split()))

    def test_the_report_gives_the_dipole_after_the_boxes_and_the_soi_with_the_atmosphere(self):
        text = report.render(self.state)
        self.assertLess(text.index("Day by day, from OISST"),
                        text.index("The Indian Ocean Dipole day by day"))
        soi = text.index("The SOI day by day, from LongPaddock's file")
        self.assertLess(text.index("ATMOSPHERE: IS THE OCEAN COUPLED TO IT?"), soi)
        self.assertLess(soi, text.index("\nFORECAST\n"))
        self.assertIn("  2026-10-13", text[soi:])

    def test_the_report_s_box_means_say_which_map_they_are_of(self):
        def said(spatial):
            return " ".join("\n".join(report._section_spatial(SimpleNamespace(spatial=spatial))).split())
        grid = self.state.spatial.sst_map
        self.assertIn(f"Area-weighted mean SST anomaly over each index box, from the Pacific map "
                      f"for {grid.as_of}, NOAA's preliminary analysis:", said(self.state.spatial))
        final = replace(self.state.spatial, sst_map=replace(grid, preliminary=None))
        self.assertIn(f"from the Pacific map for {grid.as_of}, NOAA's final analysis:", said(final))

    def test_the_json_and_the_card_say_what_the_final_changed(self):
        final = grids.daily_box_means(_days_csv({"2026-10-11": CELLS["2026-10-11"]}))[0].means
        prelim = grids.daily_box_means(_days_csv({"2026-10-12": CELLS["2026-10-12"]}))[0].means
        moved = self.data["spatial"]["nino_revision"]
        self.assertEqual(set(moved), set(final) & set(prelim))
        self.assertEqual(moved["nino34"], {"days": 9, "mean": round(final["nino34"] - prelim["nino34"], 3),
                                           "most": round(abs(final["nino34"] - prelim["nino34"]), 3)})
        self.assertIn("On the 9 days both analyses carry", self.html)


if __name__ == "__main__":
    unittest.main()
