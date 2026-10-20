"""Hurricanes on the street: HURDAT2's tracks, the tracks asset, and the
stage's storm panel (elnino/streetstorms.py, and its hooks in the desk's page
and the street's)."""

from __future__ import annotations

import json
import math
import re
import shutil
import sys
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from fractions import Fraction
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from elnino import (assets, atlasdata, classify, cyclones, exposure, parsers, sources, stormdesk,  # noqa: E402
                    street, streetstorms, tcproducts, thennow, worldmap)
import test_thennow  # noqa: E402
from test_street import PANEL_SETUP, RAIN_CTX, top_names  # noqa: E402
from test_thennow import _run  # noqa: E402
from test_tracker import _DeskFixtures, _asset_value, _js_function  # noqa: E402

# Two Atlantic storms as HURDAT2 writes them: one from before the record the
# street counts, and one from 2012 with radii, a landfall record at 16:30, a
# line with no radius known and a header whose count is one short.
ATLANTIC = """\
AL041949,            UNNAMED,      2,
19490901, 0000,  , TS, 25.0N,  80.0W,  50, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999
19490901, 0600,  , TS, 25.5N,  80.5W,  55, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999
AL182012,              SANDY,      3,
20121029, 1200,  , HU, 38.8N,  71.0W,  80,  945,  420,  450,  300,  420,  210,  240,  210,  210,  100,  140,   70,   90, -999
20121029, 1630, L, EX, 39.4N,  74.4W,  70,  946, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999
20121030, 0000,  , EX, 39.8N,  75.4W,  65,  952,  400,  460,  330,  300,  180,  210,  170,  140,    0,    0,    0,    0,   15
20121030, 0600,  , EX, 40.1N,  76.1W,  55,  960,    0,  430,  330,    0,    0,  180,  140,    0,    0,    0,    0,    0, -999
"""

# The Atlantic file's own line for the 29 September 1969 storm off Norway,
# with no comma between its latitude and longitude, and one with a wind HURDAT2
# does not know (-99).
NORWAY = """\
AL191969,            UNNAMED,      3,
19690929, 0000,  , EX, 62.0N,   2.0E,  70, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999
19690929, 0600,  , EX, 63.3N    7.5E,  70, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999
19690929, 1200,  , EX, 64.0N,  12.0E, -99, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999, -999
"""

# A Pacific storm across the date line, a line that cannot be read, and a
# depression that never reached 34 kt.
PACIFIC = """\
CP022015,             KILO,      4,
20150901, 0000,  , HU, 20.0N, 179.5W,  90,  960,   60,   60,   40,   50,   30,   30,   20,   25,   15,   15,   10,   10, -999
20150901, 0600,  , HU, 20.4N, 179.5E,  85,  965,   60,   60,   40,   50,   30,   30,   20,   25,   15,   15,   10,   10, -999
this line is not a fix
20150901, 1200,  , TS, 20.8N, 178.6E,  60,  985,   50,   50,   30,   40,   20,   20,    0,    0,    0,    0,    0,    0, -999
EP151990,            FIFTEEN,      1,
19900801, 0000,  , TD, 15.0N, 110.0W,  30, 1006,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0,    0, -999
"""


class TestHurdatTracks(unittest.TestCase):
    """HURDAT2's tracks read fix by fix, from the year the street counts."""

    def test_a_storm_s_fixes_are_read_with_time_position_wind_status_and_radii(self):
        (sandy,) = cyclones.hurdat_tracks(ATLANTIC, first=1950)
        self.assertEqual((sandy.id, sandy.name, sandy.year, sandy.peak), ("AL182012", "SANDY", 2012, 80))
        first = sandy.fixes[0]
        self.assertEqual((first.when, first.lat, first.lon, first.wind, first.status),
                         (datetime(2012, 10, 29, 12), 38.8, -71.0, 80, "HU"))
        self.assertEqual(first.radii, (420, 450, 300, 420, 210, 240, 210, 210, 100, 140, 70, 90))
        # The landfall record keeps its minutes; it gives no radius at all.
        landfall = sandy.fixes[1]
        self.assertEqual((landfall.when, landfall.status, landfall.radii), (datetime(2012, 10, 29, 16, 30), "EX", None))
        # A quadrant without the wind is 0, which is known; -999 is not.
        self.assertEqual(sandy.fixes[3].radii, (0, 430, 330, 0, 0, 180, 140, 0, 0, 0, 0, 0))
        self.assertEqual(len(sandy.fixes), 4)

    def test_a_storm_before_the_first_year_is_left_out(self):
        self.assertEqual([t.id for t in cyclones.hurdat_tracks(ATLANTIC, first=1949)], ["AL041949", "AL182012"])
        self.assertEqual([t.id for t in cyclones.hurdat_tracks(ATLANTIC, first=2013)], [])

    def test_a_position_written_without_its_comma_is_read_and_an_unknown_wind_is_none(self):
        (storm,) = cyclones.hurdat_tracks(NORWAY, first=1950 - 100)
        self.assertEqual([(f.lat, f.lon, f.wind) for f in storm.fixes], [(62.0, 2.0, 70), (63.3, 7.5, 70), (64.0, 12.0, None)])
        self.assertEqual(storm.peak, 70)
        self.assertIsNone(storm.fixes[0].radii)

    def test_east_longitudes_are_positive_and_a_line_that_is_not_a_fix_is_skipped(self):
        kilo, fifteen = cyclones.hurdat_tracks(PACIFIC, first=1950)
        self.assertEqual([(f.lat, f.lon) for f in kilo.fixes], [(20.0, -179.5), (20.4, 179.5), (20.8, 178.6)])
        self.assertEqual((fifteen.id, fifteen.peak, len(fifteen.fixes)), ("EP151990", 30, 1))

    def test_a_header_s_count_is_not_trusted(self):
        # Sandy's header says three lines and four follow: all four are read.
        (sandy,) = cyclones.hurdat_tracks(ATLANTIC, first=2000)
        self.assertEqual(len(sandy.fixes), 4)
        # A storm with no fixes at all is not a track.
        self.assertEqual(cyclones.hurdat_tracks("AL011990,   EMPTY,   2,\n", first=1950), [])


class TestTracksInTheRun(unittest.TestCase):
    """The cyclone tier keeps each basin's tracks and the file they came from."""

    INDEX = ('<a href="hurdat2-1851-2025-091226.txt">Atlantic</a> '
             '<a href="hurdat2-nepac-1949-2025-091426.txt">Pacific</a>')

    def fetched(self, **texts):
        out = {}
        for key, text in texts.items():
            source = sources.Source(key=key, name=key, url="https://example.invalid/" + key, agency="test",
                                    cadence="annual", tier="cyclone")
            out[key] = sources.Fetched(source, text, "2026-10-14T00:00:00+00:00", from_cache=False, sha256="")
        return out

    def test_build_keeps_each_basin_s_tracks_and_their_file(self):
        state = cyclones.build(self.fetched(hurdat_index=self.INDEX, hurdat_al=ATLANTIC, hurdat_ep=PACIFIC),
                               today=datetime(2026, 10, 14).date())
        self.assertEqual({basin: [t.id for t in tracks] for basin, tracks in state.tracks.items()},
                         {"AL": ["AL182012"], "EP": ["CP022015", "EP151990"]})
        self.assertEqual(state.track_files, {"AL": "hurdat2-1851-2025-091226.txt",
                                             "EP": "hurdat2-nepac-1949-2025-091426.txt"})

    def test_each_basin_s_el_nino_composite_starts_at_its_satellite_era(self):
        # A hurricane a season in El Nino seasons either side of each basin's
        # first, 1966 in the Atlantic and 1971 in the east Pacific: the run's
        # Atlantic composite holds 1966 and 1972, its east Pacific one 1972.
        years = (1957, 1965, 1966, 1972)

        def season(basin, year, lon):
            return _hurdat(f"{basin}01{year},            UNNAMED,      4,",
                           *((f"{year}0901{hour:02d}", "HU", 15.0, lon, 100) for hour in (0, 6, 12, 18)))
        texts = {key: "".join(season(basin, year, lon) for year in years)
                 for key, basin, lon in (("hurdat_al", "AL", -50.0), ("hurdat_ep", "EP", -110.0))}
        state = cyclones.build(self.fetched(hurdat_index=self.INDEX, **texts),
                               index=[parsers.SeasonValue("ASO", year, 1.2) for year in years],
                               today=datetime(2026, 10, 14).date())
        self.assertEqual({basin: (season.elnino["years"], season.elnino["ace"])
                          for basin, season in state.basins.items()},
                         {"AL": (2, 4.0), "EP": (1, 4.0)})

    def test_a_basin_whose_file_cannot_be_read_has_no_tracks_and_the_run_goes_on(self):
        state = cyclones.build(self.fetched(hurdat_index=self.INDEX, hurdat_al=ATLANTIC),
                               today=datetime(2026, 10, 14).date())
        self.assertEqual(list(state.tracks), ["AL"])
        self.assertEqual(state.track_files, {"AL": "hurdat2-1851-2025-091226.txt"})


FILES = {"AL": "hurdat2-1851-2025-091226.txt", "EP": "hurdat2-nepac-1949-2025-091426.txt"}


def _tracked():
    """A run whose cyclone tier holds the samples' tracks."""
    tracks = {"AL": tuple(cyclones.hurdat_tracks(ATLANTIC)), "EP": tuple(cyclones.hurdat_tracks(PACIFIC))}
    return SimpleNamespace(cyclones=cyclones.CycloneState(tracks=tracks, track_files=dict(FILES)))


def _decode(storm, statuses):
    """A payload storm's rows summed back into fixes, as the page reads them."""
    _id, _name, start, rows = storm
    when, lat, lon, fixes = datetime.strptime(start, "%Y%m%d%H%M"), 0, 0, []
    for minutes, dlat, dlon, wind, status, *radii in rows:
        when, lat, lon = when + timedelta(minutes=minutes), lat + dlat, lon + dlon
        fixes.append((when, lat / 10, ((lon + 1800) % 3600 - 1800) / 10, wind, statuses[status],
                      tuple(radii) or None))
    return fixes


class TestTracksPayload(unittest.TestCase):
    """The tracks as the page reads them: the storms that reached 34 kt, each
    fix written relative to the one before."""

    def test_storms_that_never_reached_34_kt_are_left_out(self):
        got = streetstorms.tracks_payload(_tracked())
        self.assertEqual([storm[:3] for storm in got["storms"]],
                         [["AL182012", "SANDY", "201210291200"], ["CP022015", "KILO", "201509010000"]])
        self.assertEqual((got["first"], got["last"], got["statuses"], got["files"]),
                         (1950, 2015, ["EX", "HU", "TS"], FILES))

    def test_the_rows_sum_back_to_every_fix(self):
        state = _tracked()
        got = streetstorms.tracks_payload(state)
        tracks = {track.id: track for basin in state.cyclones.tracks.values() for track in basin}
        for storm in got["storms"]:
            with self.subTest(storm[0]):
                self.assertEqual(_decode(storm, got["statuses"]),
                                 [(f.when, f.lat, f.lon, f.wind, f.status, f.radii) for f in tracks[storm[0]].fixes])

    def test_a_track_across_the_date_line_runs_on_rather_than_jumping_back(self):
        kilo = streetstorms.tracks_payload(_tracked())["storms"][1]
        # 179.5W, then 179.5E: ten tenths further west, not 359 degrees east.
        self.assertEqual([row[2] for row in kilo[3]], [-1795, -10, -9])
        self.assertEqual([row[0] for row in kilo[3]], [0, 360, 360])

    def test_radii_ride_only_on_rows_that_know_one(self):
        sandy = streetstorms.tracks_payload(_tracked())["storms"][0]
        self.assertEqual([len(row) for row in sandy[3]], [17, 5, 17, 17])
        # The landfall at 16:30: 270 minutes on, 0.6 north, 3.4 west, 70 kt, EX.
        self.assertEqual(sandy[3][1], [270, 6, -34, 70, 0])

    def test_without_tracks_there_is_no_payload_and_no_asset(self):
        fifteen = cyclones.hurdat_tracks(PACIFIC)[1]
        for state in (SimpleNamespace(), SimpleNamespace(cyclones=cyclones.CycloneState()),
                      SimpleNamespace(cyclones=cyclones.CycloneState(tracks={"EP": (fifteen,)}))):
            with self.subTest(state):
                self.assertIsNone(streetstorms.tracks_payload(state))
                self.assertIsNone(streetstorms.asset(state))

    def test_the_asset_sets_elnino_tracks_once_for_a_run_s_tracks(self):
        state = _tracked()
        made = streetstorms.asset(state)
        self.assertEqual(made.name, "tracks")
        self.assertIs(streetstorms.asset(state), made)
        self.assertEqual(_asset_value(made), json.loads(json.dumps(streetstorms.tracks_payload(state))))


class TestTheStageData(unittest.TestCase):
    """What the desk's data carry for the storm panel (D.tc)."""

    def test_the_index_s_aso_values_from_1950_as_cpc_prints_them_null_for_a_year_without_one(self):
        series = [parsers.SeasonValue("ASO", 1950, -0.84), parsers.SeasonValue("JAS", 1951, 0.3),
                  parsers.SeasonValue("ASO", 1952, 0.15), parsers.SeasonValue("ASO", 1949, 1.0)]
        got = streetstorms.payload(SimpleNamespace(
            assessment=SimpleNamespace(index_series=series, index_name="RONI")))
        self.assertEqual(got["aso"], {"from": 1950, "values": [-0.8, None, 0.2]})
        self.assertEqual({key: value for key, value in got.items() if key != "aso"}, {
            "index": "RONI", "warm": 0.5, "cool": -0.5, "radii_nm": [50, 100, 200], "radius_nm": 100,
            "speeds": [3, 6, 12], "speed": 6, "near_km": 1000, "inflow": 20, "first": 1950,
            "replay_from": 2004, "centre_km": 10})

    def test_the_methods_say_what_is_interpolated_what_a_radius_is_and_the_inflow_over_land(self):
        panel = streetstorms.panel()
        for words in ("centre, wind and wind radii interpolated linearly between forecast times",
                      "the centre and its wind interpolated linearly between fixes",
                      "A wind radius is the furthest that wind reaches anywhere in its quadrant, so the band here is "
                      "the most the forecast or the analysis allows; the wind at the point may be lower.",
                      "a typical inflow angle near the surface over the sea; over land the angle is larger, so the "
                      "wind there blows more nearly towards the centre than shown; within 10 km of the centre it "
                      "is not given."):
            with self.subTest(words=words[:40]):
                self.assertIn(words, panel)
        # Here's own words for the path it reads, and its method.
        for name in ("path", "here"):
            with self.subTest(name):
                self.assertIn("centre, wind and wind radii interpolated linearly between forecast",
                              stormdesk.METHODS[name])

    def test_a_run_with_no_index_has_no_seasons(self):
        got = streetstorms.payload(SimpleNamespace())
        self.assertEqual((got["aso"], got["index"]), ({"from": 1950, "values": []}, "RONI"))


class TestTheDeskNamesTheTracks(_DeskFixtures, unittest.TestCase):
    """The desk and the map name the tracks to load when the panel asks, and
    carry the panel's data."""

    def test_the_tracks_are_named_to_load_when_asked_and_never_run(self):
        state = self.state(self.polo())
        state.cyclones.tracks.update(_tracked().cyclones.tracks)
        tracks = streetstorms.asset(state)
        scripts = (assets.places(), assets.grids(), assets.coast(), assets.follower(), assets.desk())
        for focus in ("storms", "world"):
            with self.subTest(focus):
                html = stormdesk.page(state, focus=focus)
                self.assertEqual(assets.page_assets(html), [a.file for a in scripts] + [tracks.file])
                self.assertIn(assets.tags(scripts) + "\n" + tracks.lazy_tag() + "\n</head>", html)
                self.assertNotIn(f'<script defer src="assets/{tracks.file}"', html)
                data = json.loads(re.search(r'<script id="desk-data" type="application/json">(.*?)</script>',
                                            html, re.S).group(1))
                self.assertEqual(data["tc"], streetstorms.payload(state))

    def test_a_run_with_no_tracks_names_none(self):
        html = stormdesk.page(self.state(self.polo()))
        self.assertNotIn("elnino-lazy", html)


# ---- the stage's storm line, button and panel ---------------------------------------

def trudy():
    """Trudy as NHC might have had her at 15Z on 25 September 2026, the desk
    fixtures' hour: a tropical storm south of Acapulco, forecast to pass 133 km
    off Manzanillo as a major hurricane, her gale radius over the town on the
    way."""
    fix, radii = _DeskFixtures.fix, _DeskFixtures.RADII
    track = (fix("2026092500", 0, 14.0, -99.5, 40, "TS"), fix("2026092506", 0, 14.4, -100.3, 45, "TS"),
             fix("2026092512", 0, 14.8, -101.1, 50, "TS", radii=radii))
    forecast = tuple(fix("2026092512", tau, lat, lon, wind, stage, tech="OFCL", radii=radii)
                     for tau, lat, lon, wind, stage in (
                         (12, 15.6, -102.2, 65, "HU"), (24, 16.6, -103.4, 85, "HU"),
                         (36, 17.9, -104.8, 100, "HU"), (48, 19.0, -106.4, 110, "HU"),
                         (72, 20.6, -109.2, 95, "HU"), (96, 22.0, -111.5, 70, "HU"),
                         (120, 23.2, -113.0, 50, "TS")))
    advisory = {"advisory": "012", "public": "https://www.nhc.noaa.gov/text/MIATCPEP5.shtml",
                "last_update": "2026-09-25T15:00:00.000Z", "movement_dir": 300, "movement_kt": 8,
                "wind": 50, "lat": 14.9, "lon": -101.4,
                "products": {"watches": "", "cone": "", "surge": "", "winds": ""}}
    return cyclones.Storm(basin="EP", number=20, year=2026, name="Trudy", track=track, forecast=forecast,
                          advisory=advisory, products=tcproducts.Products(advisory="12"))


def _live(*storms) -> str:
    """A run's live storms as the page takes them (prepare), for a test's
    extra: D.storms with their hues, and takeStorms() making STORMS and BYID of
    D.storms, run once."""
    data = stormdesk.payload(_DeskFixtures().state(*storms))
    style = {"hues": stormdesk._hues(data["storms"]), "products": dict(stormdesk.PRODUCT_COLOURS)}
    return ("D.storms = " + json.dumps(data["storms"]) + ";\nD.style = " + json.dumps(style) + ";\n" + r"""
function takeStorms() {
  STORMS = []; BYID = Object.create(null);
  D.storms.forEach(function (s) {
    var st = {d: s, id: s.id, hue: (D.style.hues || {})[s.id] || "var(--ink2)"};
    STORMS.push(st); BYID[s.id] = st;
  });
}
takeStorms();
""")


# Trudy forecast past Manzanillo, Polo and Nolo further off on the same track,
# and Surigae in the west Pacific; the page's clock at 16Z on 25 September 2026.
STAGE = _live(trudy(), _DeskFixtures().polo(), _DeskFixtures().nolo(), _DeskFixtures().surigae())
AT = 'NOW = Date.parse("2026-09-25T16:00:00Z");\n'
NOW_TC = datetime(2026, 9, 25, 16, tzinfo=timezone.utc)
MANZANILLO = 'streetEnter(-104.32, 19.05, "Manzanillo");\n'
LIMA_TC = 'streetEnter(-77.0428, -12.0464, "Lima");\n'
_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _time(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00"))


def _utc(iso: str) -> str:
    """A time as the desk's utc() writes it: "26 Sep 17:00 UTC"."""
    t = _time(iso)
    return f"{t.day} {_MONTHS[t.month - 1]} {t:%H:%M} UTC"


def _soon(iso: str) -> str:
    """How far off a time is, as the desk's soon() says it, at NOW_TC."""
    h = math.floor((_time(iso) - NOW_TC).total_seconds() / 3600 + 0.5)
    return f"in about {h} h" if h > 0 else "about now" if h == 0 else f"{-h} h ago"


def _kms(value: float) -> str:
    return f"{math.floor(value + 0.5):,} km"


def _lead(row: dict) -> str:
    return f'<p><span class="swatch" style="background:{row["hue"]}"></span><b>{row["title"]}</b> ({row["centre"]}): '


# A row of hereFor's, as its storms come, for the line's words.
ROW = r"""
  function row(o) {
    return Object.assign({id: "x", title: "Kirk", centre: "NHC", advisory: "9", hue: "#123456",
      now: "2026-09-25T15:00:00Z", now_km: 812.4, bearing: 100, now_wind: 90, closest_km: 40.2,
      closest: "2026-09-26T20:00:00Z", closest_wind: 100, receding: false, arrival: {}, unknown: [], cone: null,
      watches: [], surge: [], official: null, forecast: true, gale: true, reached: true, lost: [], in_effect: {}}, o);
  }
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheStageStormsRun(unittest.TestCase):
    """The storm line, the button and the panel on the street stage, run under
    node over then-and-now's faked DOM with the desk's own Here, at 16Z on 25
    September 2026: Trudy forecast past Manzanillo, Polo and Nolo further off,
    Surigae in the west Pacific."""

    def run_tc(self, body: str, extra: str = ""):
        return _run(self, AT + body, extra=STAGE + extra)

    def test_the_storms_are_named_as_the_warning_centres_there_name_them(self):
        points = {"Miami": (-80.19, 25.76), "Manila": (120.98, 14.6), "Mumbai": (72.88, 19.08),
                  "Darwin": (130.84, -12.46), "Honolulu": (-157.86, 21.31), "Dublin": (-6.26, 53.35),
                  "on 180": (180.0, 10.0), "on 180 again": (-180.0, 10.0), "on 100E": (100.0, 5.0),
                  "on 30E": (30.0, 5.0), "west of 30E": (29.9, 5.0)}
        got = self.run_tc("console.log(JSON.stringify(%s.map(function (p) { return tcWord(p[0], p[1]); })));"
                          % json.dumps(list(points.values())))
        self.assertEqual(dict(zip(points, got)), {
            "Miami": "Hurricanes", "Manila": "Typhoons", "Mumbai": "Cyclones", "Darwin": "Cyclones",
            "Honolulu": "Hurricanes", "Dublin": "Hurricanes", "on 180": "Typhoons", "on 180 again": "Typhoons",
            "on 100E": "Typhoons", "on 30E": "Cyclones", "west of 30E": "Hurricanes"})

    def test_the_line_says_what_each_forecast_brings_here_in_here_s_numbers(self):
        got = self.run_tc(ROW + r"""
          var said = [
            row({arrival: {"34": "2026-09-26T10:00:00Z", "50": "2026-09-26T15:00:00Z", "64": "2026-09-26T18:00:00Z"},
                 watches: [{kind: "Hurricane Warning", km: 0.4}, {kind: "Tropical Storm Warning", km: 12}],
                 surge: [{label: "Bahia", feet: "3-5 ft"}]}),
            row({arrival: {"34": "2026-09-26T10:00:00Z", "50": "2026-09-26T15:00:00Z"},
                 watches: [{kind: "Hurricane Watch", km: 12.4}], title: "A&B"}),
            row({arrival: {"34": "2026-09-25T12:00:00Z"}, receding: true, now_km: 95.6}),
            row({unknown: [34]}),
            row({closest_km: 640}),
            row({gale: false, reached: false}),
            row({forecast: false, closest_km: null, closest: null})
          ].map(function (r) { return tcThreatHtml([r]); });
          console.log(JSON.stringify({said: said, two: tcThreatHtml([row({}), row({}), row({})]).split("<p>").length - 1,
                                      none: tcThreatHtml([])}));
        """)
        lead = '<p><span class="swatch" style="background:#123456"></span><b>Kirk</b> (NHC): '
        self.assertEqual(got["said"], [
            # The first of the forecast's winds to come, and the strongest
            # after it; the most severe watch or warning on the coast near; the
            # surge.
            lead + "tropical-storm-force wind here from 26 Sep 10:00 UTC (in about 18 h), hurricane-force from "
                   "26 Sep 18:00 UTC (in about 26 h) on the official forecast; closest 40 km at 26 Sep 20:00 UTC; "
                   "a Hurricane Warning on the coast here; inside the peak storm surge area \u201cBahia\u201d: "
                   "3-5 ft.</p>",
            lead.replace("Kirk", "A&amp;B") + "tropical-storm-force wind here from 26 Sep 10:00 UTC (in about 18 h), "
                   "50 kt from 26 Sep 15:00 UTC (in about 23 h) on the official forecast; closest 40 km at "
                   "26 Sep 20:00 UTC; nearest coast under a Hurricane Watch 12 km away.</p>",
            # Over the place already, and going: the forecast takes it no closer.
            lead + "tropical-storm-force wind here from 25 Sep 12:00 UTC (4 h ago) on the official forecast; "
                   "96 km away now, and the official forecast takes it no closer.</p>",
            # A forecast without the radius to say; one whose gale radius does
            # not reach; one with no gale radius at all.
            lead + "closest 40 km at 26 Sep 20:00 UTC (in about 28 h) on the official forecast; "
                   "its wind here is not forecast.</p>",
            lead + "closest 640 km at 26 Sep 20:00 UTC (in about 28 h) on the official forecast; "
                   "its tropical-storm-force wind does not reach here.</p>",
            lead + "closest 40 km at 26 Sep 20:00 UTC (in about 28 h) on the official forecast.</p>",
            # No forecast this run: where it was, and nothing said of where it goes.
            lead + "812 km E of here at 25 Sep 15:00 UTC; no official forecast this run.</p>"])
        self.assertEqual([got["two"], got["none"]], [2, ""])

    def test_the_chip_says_which_storms_threaten_the_point_nearest_first(self):
        got = self.run_tc(MANZANILLO + r"""
          var rows = tcNear(-104.32, 19.05);
          console.log(JSON.stringify({line: $("street-tc-line").innerHTML, hidden: $("street-tc-line").hidden,
            rows: rows.map(function (r) {
              return {id: r.id, title: r.title, centre: r.centre, hue: r.hue, arrival: r.arrival, closest: r.closest,
                      closest_km: r.closest_km, now_km: r.now_km, receding: r.receding, gale: r.gale,
                      unknown: r.unknown, forecast: r.forecast};
            }),
            here: hereFor(-104.32, 19.05).storms.map(function (r) { return r.title; })}));
        """)
        rows = got["rows"]
        # Surigae is in Here's list but nowhere near; Trudy is nearest.
        self.assertEqual(sorted(got["here"]), ["Nolo", "Polo", "Surigae", "Trudy"])
        self.assertEqual([r["title"] for r in rows][0], "Trudy")
        self.assertEqual(sorted(r["title"] for r in rows), ["Nolo", "Polo", "Trudy"])
        first, second = rows[0], rows[1]
        # Here's own hour: Trudy's gale radius reaches the town between her 24-
        # and 36-hour points, on the hour; nothing stronger does.
        arrive = first["arrival"]["34"]
        self.assertRegex(arrive, r"T\d\d:00:00")
        self.assertTrue(datetime(2026, 9, 26, 12, tzinfo=timezone.utc) <= _time(arrive)
                        <= datetime(2026, 9, 27, tzinfo=timezone.utc), arrive)
        self.assertEqual(sorted(first["arrival"]), ["34"])
        self.assertAlmostEqual(first["closest_km"], 133, delta=2)
        self.assertEqual([second["forecast"], second["receding"], second["gale"], second["arrival"],
                          second["unknown"]], [True, True, True, {}, []])
        # At most two, nearest first, each in Here's numbers.
        self.assertEqual(got["line"],
                         _lead(first) + f"tropical-storm-force wind here from {_utc(arrive)} ({_soon(arrive)}) on "
                         f"the official forecast; closest {_kms(first['closest_km'])} at {_utc(first['closest'])}."
                         "</p>" + _lead(second) + f"{_kms(second['now_km'])} away now, and the official forecast "
                         "takes it no closer; its tropical-storm-force wind does not reach here.</p>")
        self.assertFalse(got["hidden"])

    def test_the_line_is_hidden_with_no_storm_near_and_while_a_panel_is_open(self):
        got = self.run_tc(MANZANILLO + r"""
          function line() { return [$("street-tc-line").hidden, $("street-tc-line").innerHTML.length > 0]; }
          var states = [line()];
          tcOpen(); states.push(line());
          tcClose(); states.push(line());
          simOpen(); states.push(line());
          simClose(); states.push(line());
          """ + LIMA_TC + r"""
          states.push(line());
          streetLeave(); states.push(line());
          console.log(JSON.stringify(states));
        """)
        self.assertEqual(got, [[False, True], [True, True], [False, True], [True, True], [False, True],
                               [True, False], [True, False]])

    def test_the_button_names_the_storms_as_the_centres_there_do_and_opens_the_panel_in_the_chip_s_place(self):
        got = self.run_tc(r"""
          El.prototype.focus = function () { document.activeElement = this; };
          streetEnter(120.98, 14.6, "Manila");
          var words = [$("street-tc-open").textContent];
          """ + MANZANILLO + r"""
          words.push($("street-tc-open").textContent);
          function shown() {
            return [$("street-tc").hidden, $("street-chip-head").hidden, $("street-chip-said").hidden,
                    $("street-stage").classList.contains("tcon"), document.activeElement && document.activeElement.id];
          }
          var before = shown();
          $("street-tc-open").fire("click");
          var open = shown().concat([$("street-tc-title").textContent,
            $("street-tc-live").innerHTML === '<ul class="herestorms">' + tcNear(-104.32, 19.05).map(stormHere).join("") +
            "</ul>"]);
          var panel = $("street-tc"), back = $("street-tc-back");
          panel.contains = function (el) { return el === panel || el === back; };
          back.focus();
          back.fire("click");
          console.log(JSON.stringify({words: words, before: before.slice(0, 4), open: open, closed: shown(), tc: S.tc}));
        """)
        self.assertEqual(got["words"], ["Typhoons here", "Hurricanes here"])
        self.assertEqual(got["before"], [True, False, False, False])
        # In the chip's place, its live part Here's own items for the storms
        # near; the focus on it.
        self.assertEqual(got["open"], [False, True, True, True, "street-tc", "Hurricanes here", True])
        # Back puts the chip back and the focus on the button.
        self.assertEqual(got["closed"], [True, False, False, False, "street-tc-open"])
        self.assertIsNone(got["tc"])

    def test_with_no_live_storm_the_panel_says_so(self):
        got = _run(self, AT + LIMA_TC + r"""
          tcOpen();
          console.log(JSON.stringify([$("street-tc-live").innerHTML, $("street-tc-line").hidden]));
        """)
        self.assertEqual(got, ["<p>No live tropical cyclones.</p>", True])

    def test_the_two_panels_never_open_together_and_esc_closes_the_open_one_then_leaves(self):
        got = self.run_tc(MANZANILLO + r"""
          function shown() {
            return [!!S.tc, !!S.sim, $("street-tc").hidden, $("street-sim").hidden,
                    $("street-stage").classList.contains("tcon"), $("street-stage").classList.contains("simon"),
                    $("street-chip-head").hidden];
          }
          tcOpen(); simOpen();
          var sim = shown();
          tcOpen();
          var tc = shown();
          // A key in a field of the panel's is the panel's; in one elsewhere, the field's.
          var panel = $("street-tc"), mine = new El("tc-field", "select"), other = new El("other", "input");
          mine.closest = function (sel) { return sel === "#street-tc" ? panel : null; };
          var typed = [press("Escape", other).defaultPrevented, !!S.tc];
          var field = [press("Escape", mine).defaultPrevented, !!S.tc, !!S.street];
          tcOpen();
          var esc = [press("Escape").defaultPrevented, !!S.tc, !!S.street];
          simOpen();
          var esc2 = [press("Escape").defaultPrevented, !!S.sim, !!S.street];
          var esc3 = [press("Escape").defaultPrevented, !!S.street];
          console.log(JSON.stringify({sim: sim, tc: tc, typed: typed, field: field, esc: esc, esc2: esc2, esc3: esc3}));
        """)
        self.assertEqual(got["sim"], [False, True, True, False, False, True, True])
        self.assertEqual(got["tc"], [True, False, False, True, True, False, True])
        self.assertEqual(got["typed"], [False, True])
        self.assertEqual(got["field"], [True, False, True])
        self.assertEqual(got["esc"], [True, False, True])
        self.assertEqual(got["esc2"], [True, False, True])
        self.assertEqual(got["esc3"], [True, False])

    def test_leaving_closes_the_panel_and_moving_keeps_it_open_for_the_new_point(self):
        got = self.run_tc(MANZANILLO + r"""
          tcOpen();
          var there = $("street-tc-live").innerHTML;
          """ + LIMA_TC + r"""
          var moved = [!!S.tc, $("street-tc").hidden, $("street-tc-live").innerHTML, $("street-tc-title").textContent,
                       $("street-tc-open").textContent, $("street-tc-line").hidden];
          streetLeave();
          console.log(JSON.stringify({there: there.indexOf("Trudy") >= 0, moved: moved,
            left: [S.tc, $("street-tc").hidden, $("street-stage").classList.contains("tcon"),
                   $("street-tc-line").hidden]}));
        """)
        self.assertTrue(got["there"])
        self.assertEqual(got["moved"], [True, False,
                                        "<p>No live storm\u2019s official forecast comes within 1,500 km of here.</p>",
                                        "Cyclones here", "Cyclones here", True])
        self.assertEqual(got["left"], [None, True, False, True])

    def test_a_run_taken_in_place_writes_the_line_and_the_panel_from_its_storms(self):
        js = stormdesk.script()
        extra = "\n".join(_js_function(js, name) for name in ("refresh", "siteCopy", "newer", "takeRun", "withAssets"))
        extra += r"""
function prepare() { takeStorms(); }
function select() {}
function showHere() { note("showHere"); }
function ages() {}
function tab() {}
function ensoControls() {}
function render() {}
var geoDirty = false;
var ensoSaid = "", coastDone = 1, coastD = "M0", coastG = {innerHTML: ""}, NEXT = null;
var ELNINO = {places: [], coast: {lines: []}, grids: {}};
function DOMParser() {}
DOMParser.prototype.parseFromString = function () {
  return {getElementById: function (id) { return id === "desk-data" ? {textContent: JSON.stringify(NEXT)} : null; }};
};
var elninoLive = {shows: function () { note("shows"); }, sameCode: function () { return true; },
                  hold: function () { return function () {}; }};
"""
        got = self.run_tc(MANZANILLO + r"""
          tcOpen();
          var before = [$("street-tc-line").innerHTML, $("street-tc-live").innerHTML];
          D.built = "2026-09-25T15:00:00Z";
          NEXT = JSON.parse(JSON.stringify(D)); NEXT.built = "2026-09-25T16:00:00Z";
          NEXT.storms = NEXT.storms.filter(function (s) { return s.name !== "Trudy"; });
          route("map.html", "<html></html>");
          refresh(); await flush();
          var line = $("street-tc-line").innerHTML, live = $("street-tc-live").innerHTML;
          tcClose();
          function has(html) { return [html.indexOf("Trudy") >= 0, html.indexOf("Polo") >= 0]; }
          console.log(JSON.stringify({before: before.map(has), line: has(line), live: has(live),
                                      shown: $("street-tc-line").hidden, took: CALLS.indexOf("shows") >= 0}));
        """, extra=extra)
        self.assertEqual(got["before"], [[True, True], [True, True]])
        self.assertEqual([got["line"], got["live"]], [[False, True], [False, True]])
        self.assertEqual([got["shown"], got["took"]], [False, True])

    def test_the_page_s_api_says_what_the_panel_shows(self):
        got = self.run_tc(r"""
          var off = tcView();
          """ + MANZANILLO + r"""
          var shut = tcView();
          tcOpen();
          console.log(JSON.stringify([off, shut, tcView()]));
        """)
        near = ["ep202026", "ep172026", "ep152026"]
        self.assertEqual(got[0], None)
        self.assertEqual(got[1], {"open": False, "word": "Hurricanes", "near": got[1]["near"]})
        self.assertEqual([got[1]["near"][0], sorted(got[1]["near"])], [near[0], sorted(near)])
        self.assertEqual(got[2], dict(got[1], open=True))
        self.assertIn("streetStorms: function (open) { if (open === true) tcOpen(); else if (open === false) "
                      "tcClose(); return tcView(); },", stormdesk.script())


class TestTheStagePanelOnThePage(_DeskFixtures, unittest.TestCase):
    """The line, the button and the panel in the stage's chip, their rules and
    their script in the page."""

    def test_the_line_tops_the_chip_the_button_follows_the_replay_s_and_the_panel_the_replay(self):
        for focus in ("world", "storms"):
            with self.subTest(focus):
                html = stormdesk.page(self.state(self.polo()), focus=focus)
                chip = html[html.index('<div class="streetchip" id="street-chip">'):]
                chip = chip[:chip.index("</section>")]
                at = [chip.index(f'id="{name}"') for name in (
                    "street-tc-line", "street-chip-head", "street-replay", "street-tc-open", "street-more",
                    "street-chip-said", "street-sim", "street-tc")]
                self.assertEqual(at, sorted(at))
                for part in (streetstorms.chip_line(), streetstorms.button(), streetstorms.panel()):
                    self.assertIn(part, chip)
        self.assertEqual(streetstorms.chip_line(),
                         '<div class="streettcline" id="street-tc-line" role="status" hidden></div>')
        self.assertEqual(streetstorms.button(),
                         '<button type="button" class="toolbtn streetreplay" id="street-tc-open">Hurricanes here'
                         "</button>")
        panel = streetstorms.panel()
        self.assertTrue(panel.startswith('<div class="streettc" id="street-tc" role="group" '
                                         'aria-labelledby="street-tc-title" tabindex="-1" hidden>'), panel[:200])
        for part in ('<b id="street-tc-title">Hurricanes here</b>',
                     '<button type="button" class="streetmore" id="street-tc-back">Back to the card</button>',
                     "<h4>Live storms</h4>", '<div id="street-tc-live"></div>',
                     "<summary>Method and sources</summary>"):
            self.assertIn(part, panel)
        # The storms since 1950: how near, the count, what went wrong with a
        # Retry, storm by storm; the history's method after the live part's.
        history = ("<h4>Since 1950</h4>",
                   '<div class="streetsimbar"><label>Within <select id="street-tc-radius">'
                   '<option value="50">50 n mi (93 km)</option><option value="100" selected>100 n mi (185 km)</option>'
                   '<option value="200">200 n mi (370 km)</option></select> of here</label></div>',
                   '<div class="streettcpast" id="street-tc-past" aria-live="polite"></div>',
                   '<p class="streetfail" id="street-tc-fail" hidden><span id="street-tc-why"></span> '
                   '<button type="button" class="toolbtn" id="street-tc-retry">Retry</button></p>',
                   '<details class="streetsimmore" id="street-tc-each" hidden><summary>Storm by storm</summary>'
                   '<div class="streetsimtable" id="street-tc-table"></div></details>',
                   "<summary>Method and sources</summary>", '<div id="street-tc-method"></div>')
        at = [panel.index('<div id="street-tc-live"></div>')] + [panel.index(part) for part in history]
        self.assertEqual(at, sorted(at))
        # The replay, between the live storms and the storms since 1950:
        # Play, the storm and the speed, the hour, its readout, the chart and
        # its key, the words, and the hours in a table.
        replay = ("<h4>Replay</h4>",
                  '<div class="streetsimbar"><button type="button" class="toolbtn" id="street-tc-play" disabled>Play'
                  '</button><label>Storm <select id="street-tc-run" disabled></select></label><label>Speed <select '
                  'id="street-tc-speed"><option value="3">3 hours a second</option><option value="6" selected>6 '
                  'hours a second</option><option value="12">12 hours a second</option></select></label></div>',
                  '<input type="range" class="streetsimday" id="street-tc-hour" min="0" max="0" step="1" value="0" '
                  'aria-label="Hour of the replay" disabled>',
                  '<p class="streetsimread" id="street-tc-read"></p><div class="streetsimchart" id="street-tc-chart">'
                  '</div><p class="streetsimkey" id="street-tc-key"></p><div class="streetsimsaid" id="street-tc-said" '
                  'aria-live="polite"></div>',
                  '<details class="streetsimmore" id="street-tc-every" hidden><summary>Hour by hour</summary>'
                  '<div class="streetsimtable" id="street-tc-hours"></div></details>', "<h4>Since 1950</h4>")
        at = [panel.index('<div id="street-tc-live"></div>')] + [panel.index(part) for part in replay]
        self.assertEqual(at, sorted(at))
        # The storm's menu as wide as the panel lets it be: "Trudy, NHC
        # forecast (34 kt here)" is longer than the El Nino replay's menus.
        self.assertIn(".streettc #street-tc-run { max-width: 100%; }", streetstorms.css())
        # How the live part is known: Here's rule, the official forecast hour
        # by hour, not an official product.
        for words in ("1,500 km", "official forecast", "hour by hour", "not an official product", "UTC"):
            self.assertIn(words, panel)
        # How the replay is known: a past storm's best track since 2004, made
        # hourly by the same rules; where the wind comes from worked out here;
        # the streaks no rain forecast, and blind to Google's view.
        for words in ("since 2004, the first season it gives wind radii", "within 1,000 km of here",
                      "worked out here, not forecast", "20 degrees in towards it", "within 10 km of the centre",
                      "not a rain forecast", "do not turn when Google\u2019s view is turned"):
            self.assertIn(words, panel)

    def test_hurdat2_is_credited_beside_the_stage_s_other_sources(self):
        self.assertEqual(streetstorms.credit(),
                         '<p class="streetcredit" id="street-tc-credit" hidden>Storm tracks: <a '
                         'href="https://www.nhc.noaa.gov/data/#hurdat" target="_blank" rel="noopener">HURDAT2</a>, NOAA '
                         "National Hurricane Center.</p>")
        for focus in ("world", "storms"):
            with self.subTest(focus):
                html = stormdesk.page(self.state(self.polo()), focus=focus)
                # After the El Nino replay's, shown while the panel is open as
                # that one is while the replay is.
                self.assertLess(html.index('id="street-sim-credit"'), html.index(streetstorms.credit()))

    def test_the_panel_s_rules_are_the_page_s_and_open_it_stands_as_the_replay_does(self):
        for focus in ("world", "storms"):
            with self.subTest(focus):
                self.assertIn(streetstorms.css(), stormdesk.page(self.state(self.polo()), focus=focus))
        rules = re.findall(r"[^{}]*\.streetstage\.simon[^{]*\{", street.css())
        self.assertEqual(len(rules), 4)
        for rule in rules:
            self.assertIn(rule.replace("simon", "tcon").strip().split(",")[0].strip(), rule)

    def test_the_panel_s_script_is_the_page_s_after_the_street_s(self):
        js = stormdesk.script()
        self.assertNotIn("/*STREETSTORMS*/", js)
        self.assertIn(streetstorms._JS, js)
        self.assertLess(js.index(street._JS), js.index(streetstorms._JS))
        self.assertLess(js.index(streetstorms._JS), js.index("// ---- start ----"))
        self.assertIn("  S.tc = null;", streetstorms._JS)
        # A run taken in place writes the line and the panel again.
        self.assertIn("if (S.sim) simRetake();\n      tcRetake();", _js_function(js, "takeRun"))

    def test_no_name_of_the_panel_s_script_is_one_of_the_page_s(self):
        mine = top_names(streetstorms._JS)
        self.assertIn("tcOpen", mine)
        others = top_names(stormdesk._JS) | top_names(worldmap._JS) | top_names(thennow._JS) | top_names(street._JS)
        self.assertEqual(sorted(mine & others), [])
        self.assertEqual(sorted(name for name in mine if not re.match(r"(tc|TC_)[A-Z]", name)), [])

    def test_the_page_counts_from_the_threshold_the_tracks_are_kept_at(self):
        self.assertIn(f"  var TC_KT = {streetstorms.STORM_KT};\n", streetstorms._JS)

    def test_the_harness_declares_here_s_constants_as_the_page_does(self):
        js = stormdesk.script()
        for line in ('var THRESHOLDS = ["34", "50", "64"];',
                     'var ORDER = ["Tropical Storm Watch", "Tropical Storm Warning", "Hurricane Watch", '
                     '"Hurricane Warning"];',
                     'var COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", '
                     '"WSW", "W", "WNW", "NW", "NNW"];'):
            with self.subTest(line=line[:20]):
                self.assertIn(line, js)
                self.assertIn(line, test_thennow.PRELUDE)


# ---- the storms since 1950 -------------------------------------------------------------

def _hurdat(header: str, *fixes) -> str:
    """A storm as HURDAT2 writes it: its header, then a line a fix from
    (YYYYMMDDHH, status, latitude, longitude, wind), knowing no radius."""
    lines = [header]
    for when, status, lat, lon, wind in fixes:
        lines.append(f"{when[:8]}, {when[8:]}00,  , {status}, {abs(lat):4.1f}{'N' if lat >= 0 else 'S'}, "
                     f"{abs(lon):5.1f}{'W' if lon < 0 else 'E'}, {wind:3d}" + ", -999" * 14)
    return "\n".join(lines) + "\n"


# Five storms past Manzanillo (19.05N 104.32W), one a season from 1950, each
# up a meridian and nearest the town at 19.05N: Able 34 km off at 70 kt, Baker
# 156 km off at 45 kt as an extratropical low, Charlie 271 km off at 100 kt
# (within 200 n mi, not 100), Dog 76 km off at 30 kt there, reaching 40 kt at
# 22.2N, 357 km off (within 200 n mi, not 100), and Easy 23 km off at 50 kt.
PAST = (_hurdat("EP011950,               ABLE,      2,", ("1950090100", "HU", 18.0, -104.0, 70),
                ("1950090106", "HU", 20.1, -104.0, 70))
        + _hurdat("EP021951,              BAKER,      2,", ("1951090100", "EX", 18.0, -105.8, 45),
                  ("1951090106", "EX", 20.1, -105.8, 45))
        + _hurdat("EP031952,            CHARLIE,      2,", ("1952090100", "HU", 18.0, -106.9, 100),
                  ("1952090106", "HU", 20.1, -106.9, 100))
        + _hurdat("EP041953,                DOG,      3,", ("1953090100", "TD", 18.0, -103.6, 30),
                  ("1953090106", "TD", 20.1, -103.6, 30), ("1953090112", "TS", 22.2, -103.6, 40))
        + _hurdat("EP051954,               EASY,      2,", ("1954090100", "TS", 18.0, -104.1, 50),
                  ("1954090106", "TS", 20.1, -104.1, 50)))
# Their seasons: El Nino in 1950 and 1953, La Nina in 1951, neutral in 1952,
# and 1954 without an ASO value.
PAST_ASO = "D.tc.aso = {from: 1950, values: [0.8, -1.1, 0.0, 0.6, null]};\n"


def _past_raw() -> dict:
    """The five storms as the tracks asset carries them."""
    tracks = {"EP": tuple(cyclones.hurdat_tracks(PAST))}
    return streetstorms.tracks_payload(SimpleNamespace(cyclones=cyclones.CycloneState(
        tracks=tracks, track_files=dict(FILES))))


# The page names the tracks to load when asked, at the address the browser
# resolves its link to; the head takes the script the panel adds, and the
# test lets it load (land) or fail (miss).
LAZY = r"""
  var LINK = new El("", "link");
  LINK.setAttribute("rel", "elnino-lazy"); LINK.setAttribute("href", "assets/tracks.0123456789.js");
  LINK.href = "file:///C:/elnino/output/assets/tracks.0123456789.js";
  LISTS['link[rel="elnino-lazy"]'] = [LINK];
  var ADDED = [];
  document.head = new El("head");
  document.head.appendChild = function (s) { ADDED.push(s); return s; };
  function land(i) { window.ELNINO = {tracks: RAW}; ADDED[i].onload(); }
  function miss(i) { ADDED[i].onerror(); }
"""
READING = '<p class="streetwait">Reading the storm tracks\u2026</p>'
# Outside HURDAT2's basins, and inside them beyond any of its storms.
UNHELD = ("<p>HURDAT2 does not cover here. It holds the North Atlantic\u2019s storms and the eastern and central North "
          "Pacific\u2019s, east of 180\u00b0; of the north-west Pacific\u2019s it holds only the few that crossed 180\u00b0 "
          "from the east, and none of the north Indian Ocean\u2019s or the southern hemisphere\u2019s.</p>")
UNREACHED = "<p>HURDAT2 does not reach here: none of its storms passed within 1,000 km.</p>"
# A central Pacific storm that crossed 180 degrees as Ioke did in 2006, past
# Honolulu, Midway, Wake and Guam and on towards Tokyo; and an Atlantic one
# that reached Portugal as Leslie did in 2018.
CROSSERS = (_hurdat("CP012006,               IOKE,      5,", ("2006082000", "HU", 19.0, -157.0, 80),
                    ("2006082200", "HU", 24.0, -175.0, 100), ("2006082400", "HU", 19.3, 167.0, 120),
                    ("2006082600", "HU", 15.0, 147.0, 110), ("2006082800", "HU", 30.0, 140.0, 90))
            + _hurdat("AL132018,             LESLIE,      3,", ("2018101200", "HU", 35.0, -20.0, 80),
                      ("2018101300", "TS", 38.5, -10.5, 60), ("2018101306", "EX", 40.5, -7.0, 45)))


def _crossers_raw() -> dict:
    """The two storms as the tracks asset carries them, each in its basin."""
    tracks = cyclones.hurdat_tracks(CROSSERS)
    return streetstorms.tracks_payload(SimpleNamespace(cyclones=cyclones.CycloneState(
        tracks={"AL": tuple(t for t in tracks if t.id.startswith("AL")),
                "EP": tuple(t for t in tracks if not t.id.startswith("AL"))}, track_files=dict(FILES))))


def _ms(when: datetime) -> int:
    return int(when.replace(tzinfo=timezone.utc).timestamp() * 1000)


def _quads(radii):
    """HURDAT2's twelve radii as Here keeps a point's: by threshold where all
    four quadrants are known, None with none."""
    if radii is None:
        return None
    out = {kt: list(radii[4 * i:4 * i + 4]) for i, kt in enumerate(("34", "50", "64"))
           if None not in radii[4 * i:4 * i + 4]}
    return out or None


def _haversine(lon1, lat1, lon2, lat2) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = (math.sin((p2 - p1) / 2) ** 2
         + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return 2 * 6371 * math.asin(min(1.0, math.sqrt(a)))


def _binomial(e, l, se, sl) -> float:
    """The two-sided exact binomial test's p, in exact arithmetic."""
    n, p = e + l, Fraction(se, se + sl)
    pmf = [math.comb(n, k) * p ** k * (1 - p) ** (n - k) for k in range(n + 1)]
    return float(sum(q for q in pmf if q <= pmf[e]))


def _phase_table(*rows) -> str:
    """The history's phases as the page tabulates them."""
    head = "".join(f'<th scope="col">{h}</th>' for h in ("Phase", "Seasons", "Storms", "A season"))
    body = "".join(f'<tr><th scope="row">{name}</th><td>{seasons}</td><td>{storms}</td><td>{rate}</td></tr>'
                   for name, seasons, storms, rate in rows)
    return f'<table class="streettable"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>'


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheRecordRun(unittest.TestCase):
    """The record's own functions, run under node: the tracks read back, a
    track's closest approach, a season's phase, the binomial test, the count
    since 1950 and how the panel says it."""

    def test_the_tracks_read_back_to_hurdat2_s_fixes(self):
        state = _tracked()
        raw = streetstorms.tracks_payload(state)
        # A row knowing only some of its radii keeps the thresholds whose four
        # quadrants it knows.
        raw["storms"].append(["AL012013", "ANDREA", "201306051200",
                              [[0, 255, -860, 45, raw["statuses"].index("TS"), 100, None, 80, 90, 50, 40, 30, 20,
                                None, None, None, None]]])
        got = _run(self, "console.log(JSON.stringify(tcDecode(%s)));" % json.dumps(raw))
        self.assertEqual([(t["id"], t["name"], t["year"]) for t in got],
                         [("AL182012", "SANDY", 2012), ("CP022015", "KILO", 2015), ("AL012013", "ANDREA", 2013)])
        tracks = {t.id: t for basin in state.cyclones.tracks.values() for t in basin}
        for track in got[:2]:
            with self.subTest(track["id"]):
                self.assertEqual([[f["t"], f["lat"], round((f["lon"] + 180) % 360 - 180, 6), f["wind"], f["status"],
                                   f["radii"]] for f in track["fixes"]],
                                 [[_ms(f.when), f.lat, f.lon, f.wind, f.status, _quads(f.radii)]
                                  for f in tracks[track["id"]].fixes])
        # Across the date line the longitude runs on, as the rows carry it.
        self.assertEqual([f["lon"] for f in got[1]["fixes"]], [-179.5, -180.5, -181.4])
        self.assertEqual(got[2]["fixes"][0]["radii"], {"50": [50, 40, 30, 20]})

    def test_a_track_s_closest_approach_is_between_its_fixes_with_its_wind_there(self):
        got = _run(self, r"""
          var T0 = Date.UTC(2020, 8, 1);
          function fix(h, lat, lon, wind, status) {
            return {t: T0 + h * HOUR, lat: lat, lon: lon, wind: wind, status: status, radii: null};
          }
          var north = {fixes: [fix(0, 20, -80, 40, "TS"), fix(6, 22, -80, 60, "HU")]};
          var gap = {fixes: [fix(0, 20, -80, 40, "TS"), fix(6, 22, -80, null, "HU")]};
          // Across the date line, the longitude run on as the rows carry it.
          var kilo = {fixes: [fix(0, 20, 179, 50, "HU"), fix(6, 20, 180, 60, "HU"), fix(12, 20, 181, 70, "HU")]};
          var one = {fixes: [fix(0, 25, -75, 55, "TS")]};
          console.log(JSON.stringify({T0: T0,
            mid: tcClosest(north, -79, 20.5), short: tcClosest(north, -80, 19), past: tcClosest(north, -80, 23),
            between: tcClosest(gap, -79, 20.5), first: tcClosest(gap, -80, 19), last: tcClosest(gap, -80, 23),
            line: tcClosest(kilo, -179.6, 20.3), far: tcClosest(kilo, 0.4, 20), one: tcClosest(one, -76, 25)}));
        """)
        t0, h = got["T0"], 3600000

        def kept(r):
            return {k: r[k] for k in ("t", "wind", "status")}

        # A quarter of the way up the leg: the time and the wind a quarter of
        # the way on, the status the nearer fix's, the distance great-circle.
        self.assertEqual(kept(got["mid"]), {"t": t0 + 1.5 * h, "wind": 45, "status": "TS"})
        self.assertAlmostEqual(got["mid"]["km"], _haversine(-79, 20.5, -80, 20.5), places=6)
        # Short of the track and past it: its ends.
        self.assertEqual(kept(got["short"]), {"t": t0, "wind": 40, "status": "TS"})
        self.assertAlmostEqual(got["short"]["km"], _haversine(-80, 19, -80, 20), places=6)
        self.assertEqual(kept(got["past"]), {"t": t0 + 6 * h, "wind": 60, "status": "HU"})
        # A wind a fix does not know is not known on the way to it, though the
        # other fix's own is.
        self.assertEqual([got["between"]["wind"], got["first"]["wind"], got["last"]["wind"]], [None, 40, None])
        # Across the date line the leg is whole: 179.6W is 0.4 of the way from
        # 180 to 179W, 0.3 degrees south of it.
        line = got["line"]
        self.assertAlmostEqual(line["t"], t0 + 8.4 * h, delta=1)
        self.assertAlmostEqual(line["wind"], 64, places=6)
        self.assertAlmostEqual(line["km"], _haversine(-179.6, 20.3, -179.6, 20), places=6)
        # From the other side of the world it is the other side of the world,
        # not a leg joined straight across the point.
        self.assertGreater(got["far"]["km"], 15000)
        # A track of one fix is that fix.
        self.assertEqual(kept(got["one"]), {"t": t0, "wind": 55, "status": "TS"})
        self.assertAlmostEqual(got["one"]["km"], _haversine(-76, 25, -75, 25), places=6)

    def test_a_season_s_phase_is_its_aso_value_as_cpc_prints_it(self):
        got = _run(self, r"""
          D.tc.aso = {from: 1950, values: [0.5, -0.5, 0.4, -0.4, null, 1.2]};
          console.log(JSON.stringify([1949, 1950, 1951, 1952, 1953, 1954, 1955, 1956].map(function (y) {
            return tcPhase(y);
          })));
        """)
        self.assertEqual(got, [None, "warm", "cool", "neutral", "neutral", None, "warm", None])

    def test_a_track_s_strongest_wind_within_the_distance_is_at_an_end_of_its_part_inside(self):
        got = _run(self, r"""
          var T0 = Date.UTC(2020, 8, 1);
          function fix(h, lat, lon, wind) {
            return {t: T0 + h * HOUR, lat: lat, lon: lon, wind: wind, status: "TS", radii: null};
          }
          // Up 80W past a point at 20.5N 79W, its wind rising from 40 kt to 70.
          var rising = {fixes: [fix(0, 18, -80, 40), fix(6, 23, -80, 70)]};
          var gap = {fixes: [fix(0, 18, -80, 40), fix(6, 23, -80, null)]};
          var kilo = {fixes: [fix(0, 20, 179, 50), fix(6, 20, 180, 60), fix(12, 20, 181, 70)]};
          var one = {fixes: [fix(0, 25, -75, 55)]};
          console.log(JSON.stringify({
            rising: [tcWithin(rising, -79, 20.5, 150), tcWithin(rising, -79, 20.5, 100), tcWithin(rising, -79, 20.5, 400)],
            gap: [tcWithin(gap, -79, 20.5, 150), tcWithin(gap, -79, 18.2, 150)],
            line: tcWithin(kilo, -179.6, 20.3, 50), one: [tcWithin(one, -76, 25, 150), tcWithin(one, -76, 25, 50)]}));
        """)

        def plane(lat):
            return 111.32 * math.cos(math.radians(lat)), 110.57

        # The leg leaves the circle north of the point: the wind there, the
        # most inside it; nothing inside a circle the leg passes outside; the
        # whole leg inside a wide one.
        kx, ky = plane(20.5)
        out = 20.5 + math.sqrt(150 ** 2 - kx ** 2) / ky
        self.assertAlmostEqual(got["rising"][0], 40 + (out - 18) / 5 * 30, places=9)
        self.assertEqual(got["rising"][1:], [None, 70])
        # A wind a fix does not know is not known on the way to it, though the
        # other fix's own is, inside the circle.
        self.assertEqual(got["gap"], [None, 40])
        # Across the date line the leg is whole: it leaves the circle 0.76 of
        # the way from 180 to 179W.
        kx, ky = plane(20.3)
        leaves = -179.6 + math.sqrt(50 ** 2 - (0.3 * ky) ** 2) / kx
        self.assertAlmostEqual(got["line"], 60 + (leaves + 180) * 10, places=9)
        # A track of one fix is that fix, inside or not.
        self.assertEqual(got["one"], [55, None])

    def test_the_binomial_test_is_exact(self):
        cases = [(3, 8, 21, 21), (0, 5, 10, 30), (12, 2, 20, 25), (3, 8, 22, 21), (0, 0, 21, 21), (2, 3, 0, 21),
                 (2, 3, 21, 0)]
        got = _run(self, "console.log(JSON.stringify(%s.map(function (c) { return tcBinomial(c[0], c[1], c[2], c[3]); })));"
                   % json.dumps(cases))
        self.assertAlmostEqual(got[0], 464 / 2048, places=12)
        for case, p in zip(cases[1:4], got[1:4]):
            with self.subTest(case):
                self.assertAlmostEqual(p, _binomial(*case), places=12)
        # No storm to split, or no season of a phase to split them by: no test.
        self.assertEqual(got[4:], [None, None, None])

    def test_the_storms_since_1950_are_counted_at_34_kt_or_more_there_by_phase(self):
        got = _run(self, PAST_ASO + "var tracks = tcDecode(%s);\n" % json.dumps(_past_raw()) + r"""
          console.log(JSON.stringify([tcPast(tracks, -104.32, 19.05, 100 * NM), tcPast(tracks, -104.32, 19.05, 200 * NM),
                                      tcPast(tracks, 120.98, 14.6, 100 * NM)]));
        """)
        near, wide, manila = got
        # Newest first: Easy, Baker as an extratropical low, Able; not Charlie,
        # further off, nor Dog, under 34 kt while within 100 n mi.
        self.assertEqual([(r["id"], r["name"], r["year"], r["wind"], r["status"], r["phase"]) for r in near["rows"]],
                         [("EP051954", "EASY", 1954, 50, "TS", None), ("EP021951", "BAKER", 1951, 45, "EX", "cool"),
                          ("EP011950", "ABLE", 1950, 70, "HU", "warm")])
        for row, lon in zip(near["rows"], (-104.1, -105.8, -104.0)):
            with self.subTest(row["name"]):
                self.assertAlmostEqual(row["km"], _haversine(-104.32, 19.05, lon, 19.05), places=6)
                self.assertAlmostEqual(row["t"], _ms(datetime(row["year"], 9, 1, 3)), delta=1)
        # Easy's season has no ASO value: in no phase. Seasons from 1950 to the
        # record's last.
        self.assertEqual(near["counts"], {"warm": {"storms": 1, "seasons": 2}, "cool": {"storms": 1, "seasons": 1},
                                          "neutral": {"storms": 0, "seasons": 1}})
        self.assertAlmostEqual(near["p"], _binomial(1, 1, 2, 1), places=12)
        self.assertEqual([near["covered"], near["held"], near["radius_km"], near["last"]], [True, True, 100 * 1.852,
                                                                                            1954])
        # Within 200 n mi Dog counts too: 30 kt at its closest, 40 kt later
        # while still within the distance.
        self.assertEqual([r["name"] for r in wide["rows"]], ["EASY", "DOG", "CHARLIE", "BAKER", "ABLE"])
        dog = wide["rows"][1]
        self.assertEqual([dog["wind"], dog["top"], dog["status"]], [30, 40, "TD"])
        self.assertAlmostEqual(dog["km"], _haversine(-104.32, 19.05, -103.6, 19.05), places=6)
        self.assertEqual([r["top"] for r in near["rows"]], [50, 45, 70])
        self.assertEqual(wide["counts"]["warm"], {"storms": 2, "seasons": 2})
        self.assertEqual(wide["counts"]["neutral"], {"storms": 1, "seasons": 1})
        # Manila is in the north-west Pacific, outside the record's basins.
        self.assertEqual([manila["rows"], manila["covered"], manila["held"], manila["p"]], [[], False, False, None])

    def test_a_point_outside_hurdat2_s_basins_is_not_counted_whatever_crossed_into_it(self):
        points = {"Wake": (166.65, 19.28), "Guam": (144.79, 13.44), "Tokyo": (139.69, 35.68), "Lima": (-77.04, -12.05),
                  "Midway": (-177.38, 28.21), "Honolulu": (-157.86, 21.31), "Lisbon": (-9.14, 38.72),
                  "N'Djamena": (15.04, 12.13)}
        got = _run(self, "var tracks = tcDecode(%s);\n" % json.dumps(_crossers_raw()) + r"""
          console.log(JSON.stringify(%s.map(function (p) {
            var past = tcPast(tracks, p[0], p[1], 200 * NM);
            return [past.covered, past.held, past.rows.map(function (r) { return r.id; }), tcPastHtml(past)];
          })));
        """ % json.dumps(list(points.values())))
        said = dict(zip(points, got))
        # Ioke passed within 40 km of Wake at 120 kt and 300 km of Guam at
        # 110, and came within 1,000 km of Tokyo: the north-west Pacific's
        # own storms are not in the record, so none of it is counted there,
        # nor south of the equator.
        for place in ("Wake", "Guam", "Tokyo", "Lima"):
            with self.subTest(place):
                self.assertEqual(said[place], [False, False, [], UNHELD])
        # East of 180 degrees and in the Atlantic the record counts; a point
        # in its basins that none of its storms came near is beyond them.
        self.assertEqual([said[p][:3] for p in ("Midway", "Honolulu", "Lisbon")],
                         [[True, True, []], [True, True, ["CP012006"]], [True, True, ["AL132018"]]])
        self.assertEqual(said["N'Djamena"], [False, True, [], UNREACHED])

    def test_the_history_says_how_many_passed_in_each_phase_and_how_often_chance_splits_them(self):
        got = _run(self, r"""
          function past(n, w, c, u, se, sc, su, p, more) {
            var rows = [];
            for (var i = 0; i < n; i++) rows.push({});
            return Object.assign({rows: rows, counts: {warm: {storms: w, seasons: se}, cool: {storms: c, seasons: sc},
                                                       neutral: {storms: u, seasons: su}},
                                  p: p, covered: true, held: true, radius_km: 100 * NM, last: 2025}, more || {});
          }
          console.log(JSON.stringify([
            tcPastHtml(past(25, 3, 8, 14, 22, 21, 33, tcBinomial(3, 8, 22, 21))),
            tcPastHtml(past(2, 1, 1, 0, 22, 21, 33, 1, {radius_km: 50 * NM})),
            tcPastHtml(past(31, 30, 0, 1, 22, 21, 33, 0.0001)),
            tcPastHtml(past(4, 0, 0, 3, 22, 21, 33, null)),
            tcPastHtml(past(5, 1, 1, 1, 22, 21, 33, 1)),
            tcPastHtml(past(0, 0, 0, 0, 22, 21, 33, null)),
            tcPastHtml(past(0, 0, 0, 0, 22, 21, 33, null, {covered: false, held: false})),
            tcPastHtml(past(0, 0, 0, 0, 22, 21, 33, null, {covered: false})),
            tcPastHtml(past(3, 0, 0, 0, 0, 0, 0, null)),
            tcPastHtml(past(2, 1, 1, 0, 2, 1, 1, 1)),
            tcPastHtml(past(3, 2, 0, 1, 22, 0, 33, null))]));
        """)
        span = " of here at 34 kt or more in the 76 seasons from 1950 to 2025.</p>"
        hundred = "passed within 100 n mi (185 km)" + span

        def table(w, c, u):
            return _phase_table(("El Ni\u00f1o", 22) + w, ("La Ni\u00f1a", 21) + c, ("Neutral", 33) + u)

        self.assertEqual(got, [
            # The storms, those in each phase's seasons and a season's worth;
            # how often chance alone splits El Nino's from La Nina's so unevenly.
            "<p><b>25 storms</b> " + hundred + table((3, "0.14"), (8, "0.38"), (14, "0.42"))
            + "<p>3 storms in 22 El Ni\u00f1o seasons against 8 in 21 La Ni\u00f1a seasons: chance alone splits them "
            f"this unevenly {round(_binomial(3, 8, 22, 21) * 100)}% of the time.</p>",
            # As even as chance makes them most often; a nearer radius.
            "<p><b>2 storms</b> passed within 50 n mi (93 km)" + span + table((1, "0.05"), (1, "0.05"), (0, "0.00"))
            + "<p>1 storm in 22 El Ni\u00f1o seasons against 1 in 21 La Ni\u00f1a seasons: the split chance alone "
            "makes most often.</p>",
            "<p><b>31 storms</b> " + hundred + table((30, "1.36"), (0, "0.00"), (1, "0.03"))
            + "<p>30 storms in 22 El Ni\u00f1o seasons against 0 in 21 La Ni\u00f1a seasons: chance alone splits them "
            "this unevenly less than 1% of the time.</p>",
            # Storms in seasons without an ASO value; none in either phase's.
            "<p><b>4 storms</b> " + hundred + table((0, "0.00"), (0, "0.00"), (3, "0.09"))
            + "<p>1 of them came in a season with no ASO value, so in no phase.</p>"
            + "<p>None of them came in an El Ni\u00f1o or a La Ni\u00f1a season, so the two are not set against each "
            "other.</p>",
            "<p><b>5 storms</b> " + hundred + table((1, "0.05"), (1, "0.05"), (1, "0.03"))
            + "<p>2 of them came in seasons with no ASO value, so in no phase.</p>"
            + "<p>1 storm in 22 El Ni\u00f1o seasons against 1 in 21 La Ni\u00f1a seasons: the split chance alone "
            "makes most often.</p>",
            # None near; the point outside the record's basins, or in them
            # beyond its storms.
            "<p>No storm " + hundred,
            UNHELD,
            UNREACHED,
            # A run without the index's seasons.
            "<p><b>3 storms</b> " + hundred
            + "<p>This run has no ASO value for any season, so the storms are not counted by phase.</p>",
            # A phase of one season.
            "<p><b>2 storms</b> " + hundred
            + _phase_table(("El Ni\u00f1o", 2, 1, "0.50"), ("La Ni\u00f1a", 1, 1, "1.00"), ("Neutral", 1, 0, "0.00"))
            + "<p>1 storm in 2 El Ni\u00f1o seasons against 1 in 1 La Ni\u00f1a season: the split chance alone "
            "makes most often.</p>",
            # A run with no season of one phase to set the other against.
            "<p><b>3 storms</b> " + hundred
            + _phase_table(("El Ni\u00f1o", 22, 2, "0.09"), ("La Ni\u00f1a", 0, 0, ""), ("Neutral", 33, 1, "0.03"))
            + "<p>With no La Ni\u00f1a season in the run, the two are not set against each other.</p>"])

    def test_every_status_hurdat2_writes_is_said_in_words(self):
        # HURDAT2's own list, and ET, which the eastern Pacific's file writes
        # for two of its fixes.
        statuses = ["TD", "TS", "HU", "EX", "SD", "SS", "LO", "WV", "DB", "ET"]
        got = _run(self, "console.log(JSON.stringify(%s.map(function (s) { return tcStatus({status: s}); })));"
                   % json.dumps(statuses))
        self.assertEqual(got, ["tropical depression", "tropical storm", "hurricane", "extratropical",
                               "subtropical depression", "subtropical storm", "low", "tropical wave", "disturbance",
                               "extratropical"])

    def test_the_storms_are_listed_newest_first_with_where_they_passed(self):
        got = _run(self, r"""
          console.log(JSON.stringify(tcPastTable({radius_km: 100 * NM, rows: [
            {id: "AL182012", name: "SANDY", year: 2012, km: 50.4, t: Date.UTC(2012, 9, 30, 0, 29), wind: 70.5, top: 80,
             status: "EX", phase: "neutral"},
            {id: "AL031991", name: "BOB", year: 1991, km: 120.6, t: Date.UTC(1991, 7, 19, 15, 31), wind: 87.5, top: 87.6,
             status: "HU", phase: "warm"},
            {id: "AL011954", name: "UNNAMED", year: 1954, km: 7, t: Date.UTC(1954, 7, 31, 12), wind: null, top: 45,
             status: "TS", phase: null},
            {id: "EP011950", name: "ONE-E", year: 1950, km: 160, t: Date.UTC(1950, 5, 1, 6), wind: 40, top: 40,
             status: "SS", phase: "cool"}]})));
        """)
        head = "".join(f'<th scope="col">{h}</th>' for h in ("Season", "Storm", "Closest", "Wind", "Status"))
        self.assertEqual(got, f'<table class="streettable"><thead><tr>{head}</tr></thead><tbody>'
                              "<tr><td>2012, neutral</td><td>Sandy</td><td>50 km, 30 Oct 00:00 UTC</td><td>70 kt (80 kt "
                              "within 100 n mi)</td><td>extratropical</td></tr>"
                              "<tr><td>1991, El Ni\u00f1o</td><td>Bob</td><td>121 km, 19 Aug 16:00 UTC</td><td>88 kt</td>"
                              "<td>hurricane</td></tr>"
                              "<tr><td>1954</td><td>Unnamed</td><td>7 km, 31 Aug 12:00 UTC</td><td>not known (45 kt "
                              "within 100 n mi)</td><td>tropical storm</td></tr>"
                              "<tr><td>1950, La Ni\u00f1a</td><td>One-E</td><td>160 km, 1 Jun 06:00 UTC</td><td>40 kt</td>"
                              "<td>subtropical storm</td></tr></tbody></table>")

    def test_an_asset_named_to_load_later_is_found_by_its_name_at_its_whole_address(self):
        got = _run(self, "var RAW = null;\n" + LAZY + r"""
          var other = new El("", "link");
          other.setAttribute("href", "assets/trackside.0123456789.js");
          other.href = "file:///C:/elnino/output/assets/trackside.0123456789.js";
          LISTS['link[rel="elnino-lazy"]'] = [other, LINK];
          console.log(JSON.stringify([tcLater("tracks"), tcLater("grids")]));
        """)
        self.assertEqual(got, ["file:///C:/elnino/output/assets/tracks.0123456789.js", None])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheHistoryOnThePanel(unittest.TestCase):
    """The panel's storms since 1950 at Manzanillo, under node over the faked
    DOM, the five storms past the town as the tracks."""

    def run_past(self, body: str, lazy: bool = True):
        return _run(self, AT + "var RAW = " + json.dumps(_past_raw()) + ";\n" + (LAZY if lazy else "") + PAST_ASO
                    + body, extra=STAGE)

    def test_the_panel_reads_the_tracks_once_and_then_counts_the_storms_since_1950(self):
        got = self.run_past(MANZANILLO + r"""
          tcOpen();
          var reading = [$("street-tc-past").innerHTML, ADDED.length, ADDED[0].src, $("street-tc-fail").hidden,
                         $("street-tc-each").hidden];
          tcClose(); tcOpen();
          var again = ADDED.length;
          land(0); await flush();
          var past = S.tc.past, kept = "tracks" in window.ELNINO;
          var shown = [$("street-tc-past").innerHTML === tcPastHtml(past), $("street-tc-past").innerHTML,
                       $("street-tc-table").innerHTML === tcPastTable(past), $("street-tc-each").hidden,
                       past.rows.map(function (r) { return r.name; })];
          tcClose(); tcOpen();
          console.log(JSON.stringify({reading: reading, again: again, shown: shown, kept: kept,
                                      reopened: [ADDED.length, !!S.tc.past]}));
        """)
        self.assertFalse(got["kept"])
        # Asked for at its whole address: a script added as "assets/..." would
        # be one the follower compares with a new run's before taking it in place.
        self.assertEqual(got["reading"], [READING, 1, "file:///C:/elnino/output/assets/tracks.0123456789.js", True, True])
        self.assertEqual(got["again"], 1)
        said = got["shown"]
        self.assertEqual([said[0], said[2], said[3], said[4]], [True, True, False, ["EASY", "BAKER", "ABLE"]])
        self.assertIn("<b>3 storms</b> passed within 100 n mi (185 km) of here", said[1])
        self.assertEqual(got["reopened"], [1, True])

    def test_tracks_already_on_the_page_are_not_asked_for_again(self):
        got = self.run_past(MANZANILLO + r"""
          window.ELNINO = {tracks: RAW};
          tcOpen(); await flush();
          console.log(JSON.stringify([ADDED.length, S.tc.past.rows.length, "tracks" in window.ELNINO]));
        """)
        # Read, the asset's copy is let go: the page keeps only what it read.
        self.assertEqual(got, [0, 3, False])

    def test_a_failed_read_says_why_and_retry_reads_again_while_the_live_part_stays(self):
        got = self.run_past(MANZANILLO + r"""
          tcOpen();
          miss(0); await flush();
          var failed = [$("street-tc-fail").hidden, $("street-tc-why").textContent, $("street-tc-past").innerHTML,
                        $("street-tc-live").innerHTML.indexOf("Trudy") >= 0, $("street-tc-each").hidden];
          $("street-tc-retry").fire("click");
          var retried = [ADDED.length, $("street-tc-fail").hidden, $("street-tc-past").innerHTML];
          land(1); await flush();
          console.log(JSON.stringify({failed: failed, retried: retried, past: S.tc.past.rows.length,
                                      fail: $("street-tc-fail").hidden}));
        """)
        self.assertEqual(got["failed"], [False, "The storm tracks could not be read (the file did not load).", "", True,
                                         True])
        self.assertEqual(got["retried"], [2, True, READING])
        self.assertEqual([got["past"], got["fail"]], [3, True])

    def test_a_page_naming_no_tracks_or_a_file_setting_none_says_so(self):
        none = self.run_past(r"""
          var ADDED = [];
          document.head = new El("head");
          document.head.appendChild = function (s) { ADDED.push(s); return s; };
          streetEnter(15.04, 12.13, "N'Djamena");
          tcOpen(); await flush();
          var opened = [$("street-tc-past").innerHTML, $("street-tc-said").innerHTML, $("street-tc-fail").hidden,
                        $("street-tc-why").textContent, ADDED.length];
          tcRetry(); await flush();
          console.log(JSON.stringify({opened: opened, retried: [ADDED.length, $("street-tc-fail").hidden]}));
        """, lazy=False)
        # A run that sent no tracks says so, with no Retry, which could not
        # bring them; the replay says it too.
        self.assertEqual(none["opened"], [
            "<p>This run has no storm tracks: HURDAT2 could not be read when it was made.</p>",
            "<p>No live storm\u2019s official forecast comes within 1,500 km of here, and this run has no storm tracks: "
            "HURDAT2 could not be read when it was made.</p>", True, "", 0])
        self.assertEqual(none["retried"], [0, True])
        empty = self.run_past(MANZANILLO + r"""
          tcOpen();
          ADDED[0].onload(); await flush();
          console.log(JSON.stringify($("street-tc-why").textContent));
        """)
        self.assertEqual(empty, "The storm tracks could not be read (the file held no tracks).")

    def test_the_radius_recounts_and_a_new_point_or_run_counts_again(self):
        got = self.run_past(MANZANILLO + r"""
          tcOpen(); land(0); await flush();
          function names() { return S.tc.past.rows.map(function (r) { return r.name; }); }
          var first = [$("street-tc-radius").value, names()];
          $("street-tc-radius").value = "200";
          $("street-tc-radius").fire("change");
          var wide = [S.tc.radius, names(), $("street-tc-past").innerHTML.indexOf("within 200 n mi (370 km)") >= 0];
          // A run taken in place with 1952 now an El Nino season.
          D.tc.aso = {from: 1950, values: [0.8, -1.1, 0.7, 0.6, null]};
          tcRetake();
          var retaken = S.tc.past.counts;
          streetEnter(120.98, 14.6, "Manila");
          console.log(JSON.stringify({first: first, wide: wide, retaken: retaken,
                                      manila: [S.tc.past.covered, $("street-tc-past").innerHTML, $("street-tc-each").hidden]}));
        """)
        self.assertEqual(got["first"], ["100", ["EASY", "BAKER", "ABLE"]])
        self.assertEqual(got["wide"], [200, ["EASY", "DOG", "CHARLIE", "BAKER", "ABLE"], True])
        self.assertEqual(got["retaken"], {"warm": {"storms": 3, "seasons": 3}, "cool": {"storms": 1, "seasons": 1},
                                          "neutral": {"storms": 0, "seasons": 0}})
        # Manila is outside HURDAT2's basins: said so, not "no storms".
        self.assertEqual(got["manila"], [False, UNHELD, True])

    def test_a_run_that_could_not_read_a_basin_s_tracks_says_so(self):
        raw = _past_raw()
        raw["files"] = {"EP": FILES["EP"]}
        got = _run(self, AT + "var RAW = " + json.dumps(raw) + ";\n" + LAZY + PAST_ASO + MANZANILLO + r"""
          tcOpen(); land(0); await flush();
          var town = $("street-tc-past").innerHTML;
          streetEnter(15.04, 12.13, "N'Djamena");
          var far = [$("street-tc-past").innerHTML, $("street-tc-said").innerHTML];
          streetEnter(120.98, 14.6, "Manila");
          console.log(JSON.stringify({town: town, far: far, manila: $("street-tc-past").innerHTML}));
        """, extra=STAGE)
        note = "<p>This run could not read the North Atlantic\u2019s tracks: those storms are not counted.</p>"
        # The count, after the note; beyond the storms the run has, they are
        # not said to be HURDAT2's all; outside its basins it does not matter.
        self.assertTrue(got["town"].startswith(note + "<p><b>3 storms</b> passed within 100 n mi"), got["town"])
        self.assertEqual(got["far"], [
            note + "<p>None of the storms this run has passed within 1,000 km.</p>",
            "<p>No live storm\u2019s official forecast comes within 1,500 km of here, and no storm since 2004 passed "
            "within 100 n mi (185 km) of here or brought its 34-kt wind here. This run could not read the North "
            "Atlantic\u2019s tracks.</p>"])
        self.assertEqual(got["manila"], UNHELD)

    def test_the_method_names_the_run_s_index_and_hurdat2_is_credited_while_the_panel_is_open(self):
        got = self.run_past(MANZANILLO + r"""
          var before = $("street-tc-credit").hidden;
          tcOpen();
          var method = $("street-tc-method").innerHTML, open = $("street-tc-credit").hidden;
          tcClose();
          console.log(JSON.stringify({before: before, method: method, open: open, closed: $("street-tc-credit").hidden}));
        """)
        self.assertEqual([got["before"], got["open"], got["closed"]], [True, False, True])
        for words in (test_thennow.TC["index"] + "\u2019s August\u2013October value", "+0.5", "\u22120.5", "34 kt",
                      "binomial", "1966", "1971", "1,000 km", "Landsea", "not an official product",
                      'href="https://www.nhc.noaa.gov/data/#hurdat"',
                      "storms come in clusters within a season, so chance alone splits them this unevenly more "
                      "often than it says"):
            self.assertIn(words, got["method"])


# ---- the replay --------------------------------------------------------------------------

def _best(header: str, *fixes) -> str:
    """A storm as HURDAT2 writes it from 2004: its header, then a line a fix
    from (YYYYMMDDHHMM, record mark, status, latitude, longitude, wind, radii),
    the radii twelve nautical miles by threshold and quadrant (NE, SE, SW, NW;
    None unknown), or None for none known."""
    lines = [header]
    for when, mark, status, lat, lon, wind, radii in fixes:
        cells = ", ".join(f"{-999 if r is None else r:4d}" for r in (radii or (None,) * 12))
        lines.append(f"{when[:8]}, {when[8:]}, {mark:>1}, {status}, {abs(lat):4.1f}{'N' if lat >= 0 else 'S'}, "
                     f"{abs(lon):5.1f}{'W' if lon < 0 else 'E'}, {wind:3d}, -999, {cells}, -999")
    return "\n".join(lines) + "\n"


R_ALPHA = (80, 80, 60, 70, 40, 40, 30, 35, 25, 25, 20, 20)
R_BRAVO = (160, 160, 80, 80, 60, 60, 40, 40, 0, 0, 0, 0)
R_GALE = (30, 30, 30, 30, 0, 0, 0, 0, 0, 0, 0, 0)
# Past storms by Manzanillo (19.05N 104.32W) as HURDAT2 has them, each up a
# meridian: Alpha in 2005, 23 km east of the town, a hurricane with a landfall
# record at 08:30 and a last fix knowing no radius; Bravo in 2012, 271 km
# west, its tropical-storm-force wind 296 km wide on its east side; Charlie in
# 2020, 118 km east, its gales 56 km wide; Delta in 1999, before HURDAT2 kept
# radii, over the town; Echo in 2016, 600 km off.
REPLAYS = (_best("EP012005,              ALPHA,      5,",
                 ("200509010000", "", "TS", 18.0, -104.1, 60, (60, 60, 40, 50, 30, 30, 20, 25, 0, 0, 0, 0)),
                 ("200509010600", "", "HU", 19.0, -104.1, 80, R_ALPHA),
                 ("200509010830", "L", "HU", 19.4, -104.1, 85, R_ALPHA),
                 ("200509011200", "", "HU", 20.0, -104.1, 80, R_ALPHA),
                 ("200509011800", "", "TS", 21.0, -104.1, 55, None))
           + _best("EP022012,              BRAVO,      3,",
                   ("201208100000", "", "TS", 18.0, -106.9, 60, R_BRAVO),
                   ("201208100600", "", "TS", 19.0, -106.9, 60, R_BRAVO),
                   ("201208101200", "", "TS", 20.0, -106.9, 60, R_BRAVO))
           + _best("EP032020,            CHARLIE,      3,",
                   ("202007050000", "", "TS", 18.0, -103.2, 45, R_GALE),
                   ("202007050600", "", "TS", 19.0, -103.2, 45, R_GALE),
                   ("202007051200", "", "TS", 20.0, -103.2, 45, R_GALE))
           + _best("EP041999,              DELTA,      2,",
                   ("199908010000", "", "HU", 18.5, -104.3, 90, None),
                   ("199908010600", "", "HU", 19.5, -104.3, 90, None))
           + _best("EP052016,               ECHO,      2,",
                   ("201606010000", "", "TS", 18.5, -110.0, 50, R_GALE),
                   ("201606010600", "", "TS", 19.5, -110.0, 50, R_GALE)))


def _replay_raw() -> dict:
    """The past storms by Manzanillo, with the five of the 1950s, as the tracks
    asset carries them."""
    tracks = {"EP": tuple(cyclones.hurdat_tracks(PAST + REPLAYS))}
    return streetstorms.tracks_payload(SimpleNamespace(cyclones=cyclones.CycloneState(
        tracks=tracks, track_files=dict(FILES))))


def _py_fix(fix, start):
    """A HURDAT2 fix as the exposure table's Fix: its lead in minutes from the
    track's first fix, its radii the thresholds it knows all four of."""
    radii = () if fix.radii is None else tuple(
        (kt, tuple(fix.radii[4 * i:4 * i + 4])) for i, kt in enumerate(exposure.THRESHOLDS)
        if None not in fix.radii[4 * i:4 * i + 4])
    return cyclones.Fix(stamp="", tau=round((fix.when - start).total_seconds() / 60), lat=fix.lat, lon=fix.lon,
                        wind=fix.wind, pressure=None, stage=fix.status, tech="BEST", radii=radii)


def _py_hourly(track) -> list:
    """A track made hourly in Python, as (time, Fix): each whole hour from its
    first fix to its last, a fix's own hour the fix itself, else
    exposure._blend between the fixes either side, their leads in minutes."""
    start = track.fixes[0].when
    fixes, out, i = [_py_fix(f, start) for f in track.fixes], [], 0
    for minute in range((60 - start.minute) % 60, fixes[-1].tau + 1, 60):
        while i < len(fixes) - 1 and fixes[i + 1].tau <= minute:
            i += 1
        a = fixes[i]
        out.append((start + timedelta(minutes=minute), replace(a, lon=exposure._wrap(a.lon)) if a.tau == minute
                    else exposure._blend(a, fixes[i + 1], minute - a.tau)))
    return out


def _py_band(fix, lon, lat) -> list:
    """A point's band at a fix by the exposure table's rule: the strongest
    threshold it is inside, and the next up when that is not known there."""
    inside = {t: exposure.inside(fix, lon, lat, t) for t in exposure.THRESHOLDS}
    kt = max([t for t in exposure.THRESHOLDS if inside[t]], default=0)
    above = [t for t in exposure.THRESHOLDS if t > kt]
    return [kt, above[0] if above and inside[above[0]] is None else None]


def _forecast(storm) -> tuple:
    """A live storm's id and its path from the analysis on as the page has it,
    each point with the exposure table's Fix of it."""
    s = stormdesk.payload(_DeskFixtures().state(storm))["storms"][0]
    return s["id"], [(p, cyclones.Fix(stamp="", tau=0, lat=p["lat"], lon=p["lon"], wind=p["wind"], pressure=None,
                                      stage=p["stage"], tech="OFCL",
                                      radii=tuple((int(t), tuple(q)) for t, q in (p["radii"] or {}).items() if q)))
                     for p in s["path"] if p["hour"] is not None and p["hour"] >= 0]


def trudy_beyond_72():
    """Trudy as NHC forecasts a storm: no 64-kt radius past 72 h."""
    storm = trudy()
    return replace(storm, forecast=tuple(replace(f, radii=tuple(r for r in f.radii if r[0] != 64)) if f.tau > 72
                                         else f for f in storm.forecast))


def trudy_next():
    """Trudy's next advisory, six hours on: her analysis at 18Z, and her
    forecast points the same leads from it."""
    storm = trudy()
    return replace(storm, track=storm.track + (_DeskFixtures.fix("2026092518", 0, 15.2, -101.7, 55, "TS",
                                                                  radii=_DeskFixtures.RADII),),
                   forecast=tuple(replace(f, stamp="2026092518") for f in storm.forecast))


def _storms(*storms) -> str:
    """A run's live storms as the page has them (D.storms), for one taken in place."""
    return json.dumps(stormdesk.payload(_DeskFixtures().state(*storms))["storms"])


def _r1(v: float) -> float:
    """A number to a tenth as the page's script rounds it (Math.round)."""
    return math.floor(v * 10 + 0.5) / 10


TRUDY_ID = "ep202026"
# Trudy alone: the replay's live storm, nothing else near the town.
REPLAY_STAGE = _live(trudy())
# The storm replay's frames among those asked for.
TC_TICKS = r"""
  function tcTicking() { return FRAMES.filter(function (t) { return t.f === tcTick; }).length; }
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheReplayRun(unittest.TestCase):
    """The replay's own functions, run under node: a track made hourly by the
    exposure table's rules, the band at a point hour by hour, where the wind
    comes from, what is drawn, the choices, and a run's readout, badge, words,
    table and chart."""

    def test_a_track_is_made_hourly_by_the_exposure_table_s_rules(self):
        # Fixes at whole hours, set so that hours fall on halves: 45 to 50 kt
        # is 47.5 at three hours (48), 30 to 45 n mi 37.5 (38), 25 to 40 n mi
        # 32.5 (32), 55 to 50 kt 52.5 (52). A 64-kt radius of zeros at both
        # ends is left out between them; a fix at 50 kt or more knowing no
        # 50-kt radius leaves it unknown either side.
        fixes = (("2012102806", 0, 18.0, -76.0, 45, ((34, (30, 25, 20, 20)), (50, (0, 0, 0, 0)), (64, (0, 0, 0, 0)))),
                 ("2012102812", 6, 19.0, -75.5, 50, ((34, (45, 40, 30, 25)), (50, (15, 10, 0, 0)), (64, (0, 0, 0, 0)))),
                 ("2012102815", 9, 19.6, -75.1, 55, ((34, (50, 41, 31, 26)), (64, (0, 0, 0, 0)))),
                 ("2012102821", 15, 20.5, -74.8, 50,
                  ((34, (60, 50, 40, 30)), (50, (30, 20, 10, 5)), (64, (0, 0, 0, 0)))))
        made = [cyclones.Fix(stamp="2012102806", tau=tau, lat=lat, lon=lon, wind=wind, pressure=None, stage="TS",
                             tech="OFCL" if tau else "BEST", radii=radii) for _, tau, lat, lon, wind, radii in fixes]
        line = exposure.timeline(made[0], made[1:])
        js = [{"t": _ms(datetime.strptime(stamp, "%Y%m%d%H")), "lat": lat, "lon": lon, "wind": wind, "status": "TS",
               "radii": {str(kt): list(q) for kt, q in radii}} for stamp, _, lat, lon, wind, radii in fixes]
        got = _run(self, "console.log(JSON.stringify(tcHourly(" + json.dumps(js) + ")));")
        self.assertEqual(len(got), len(line))
        for g, f in zip(got, line):
            with self.subTest(tau=f.tau):
                self.assertEqual(g["t"], _ms(datetime(2012, 10, 28, 6)) + f.tau * 3600000)
                self.assertAlmostEqual(g["lat"], f.lat, places=9)
                self.assertAlmostEqual((g["lon"] + 180) % 360 - 180, f.lon, places=9)
                self.assertEqual([g["wind"], g["radii"], g["status"]],
                                 [f.wind, {str(kt): list(q) for kt, q in f.radii} or None, "TS"])
        self.assertEqual([got[3]["wind"], got[3]["radii"]["34"][:2], got[12]["wind"]], [48, [38, 32], 52])
        self.assertNotIn("64", got[1]["radii"])
        self.assertNotIn("50", got[10]["radii"])

    def test_a_fix_off_the_hour_shapes_the_hours_either_side(self):
        [alpha] = [t for t in cyclones.hurdat_tracks(REPLAYS) if t.name == "ALPHA"]
        got = _run(self, "var a = tcDecode(" + json.dumps(_replay_raw()) + ").filter(function (s) { "
                   "return s.id === \"EP012005\"; })[0];\nconsole.log(JSON.stringify(tcHourly(a.fixes)));")
        want = _py_hourly(alpha)
        # Every whole hour from 00:00 to 18:00: 08:00 and 09:00 lie either side
        # of the 08:30 landfall, which is no hour of its own.
        self.assertEqual([g["t"] for g in got], [_ms(datetime(2005, 9, 1, h)) for h in range(19)])
        for g, (when, f) in zip(got, want):
            with self.subTest(when=when):
                self.assertAlmostEqual(g["lat"], f.lat, places=9)
                self.assertAlmostEqual(g["lon"], f.lon, places=9)
                self.assertEqual([g["wind"], g["radii"], g["status"]],
                                 [f.wind, {str(kt): list(q) for kt, q in f.radii} or None, f.stage])
        self.assertEqual([round(got[8]["lat"], 4), round(got[9]["lat"], 4), got[9]["wind"]], [19.32, 19.4857, 84])

    def test_a_track_across_the_date_line_stays_one_line_hour_by_hour(self):
        [kilo] = [t for t in cyclones.hurdat_tracks(PACIFIC) if t.name == "KILO"]
        lon, lat = 179.8, 20.5
        got = _run(self, "var k = tcDecode(" + json.dumps(streetstorms.tracks_payload(_tracked())) + ").filter("
                   "function (s) { return s.name === \"KILO\"; })[0];\n"
                   "console.log(JSON.stringify(tcHourly(k.fixes).map(function (p) {\n"
                   "  var b = tcBand(p, " + repr(lon) + ", " + repr(lat) + ");\n"
                   "  return [p.lon, b.kt, b.unknown];\n})));")
        lons = [g[0] for g in got]
        # Carried on past 180 degrees, never jumping back 359, and the band at
        # a point across the line the exposure table's on the wrapped fixes.
        self.assertEqual(len(got), 13)
        self.assertLess(max(abs(b - a) for a, b in zip(lons, lons[1:])), 0.2)
        self.assertLess(lons[-1], -180)
        self.assertEqual([g[1:] for g in got], [_py_band(f, lon, lat) for _, f in _py_hourly(kilo)])
        self.assertIn(50, [g[1] for g in got])

    def test_the_band_is_the_strongest_wind_the_point_is_inside_the_next_said_when_not_known(self):
        got = _run(self, r"""
          var at = {lon: -80, lat: 25, wind: 90, radii: {"34": [100, 100, 100, 100], "50": [50, 50, 50, 50],
                                                         "64": [20, 20, 20, 20]}};
          function with2(o) { return Object.assign({}, at, o); }
          function b(p, lat) { var x = tcBand(p, -80, lat); return [x.kt, x.unknown]; }
          console.log(JSON.stringify({bands: [
            b(at, 25.15), b(at, 25.5), b(at, 26.2), b(at, 27),
            b(with2({radii: {"34": [100, 100, 100, 100], "50": [50, 50, 50, 50]}}), 25.5),
            b(with2({radii: {"34": [100, 100, 100, 100], "64": [20, 20, 20, 20]}}), 26.2),
            b(with2({radii: null}), 27),
            b(with2({wind: 40, radii: {"34": [100, 100, 100, 100]}}), 25.5)],
            inside: tcBand(at, -80, 25.15).inside}));
        """)
        # 17 km off inside 64 kt (20 n mi); 56 km inside 50 (50 n mi); 133 km
        # inside 34 (100 n mi); 222 km outside all. No 64-kt radius at 90 kt:
        # 50 kt, 64 not known; no 50-kt radius, outside the 64: 34, 50 not
        # known; no radius at all: none known; at 40 kt, 50 is not reached.
        self.assertEqual(got["bands"], [[64, None], [50, None], [34, None], [0, None], [50, 64], [34, 50], [0, 34],
                                        [34, None]])
        self.assertEqual(got["inside"], {"34": True, "50": True, "64": True})

    def test_each_hour_of_trudy_s_forecast_brings_the_wind_when_the_exposure_table_does(self):
        town = atlasdata.Place("Manzanillo", "Mexico", "", 1000, -104.32, 19.05, False)
        [hit] = exposure.exposures(trudy(), places=(town,))
        tid, path = _forecast(trudy())
        got = _run(self, AT + r"""
          var run = tcForecast(TID, -104.32, 19.05), here = hereFor(-104.32, 19.05).storms[0];
          function first(t) {
            for (var k = 0; k < run.hours.length; k++) if (run.at[k].band.inside[t]) return run.hours[k].t;
            return null;
          }
          console.log(JSON.stringify({first: THRESHOLDS.map(first), here: THRESHOLDS.map(function (t) {
            return here.arrival[t] ? Date.parse(here.arrival[t]) : null;
          }), bands: run.at.map(function (a) { return [a.band.kt, a.band.unknown]; })}));
        """.replace("TID", json.dumps(tid)), extra=REPLAY_STAGE)
        want = [None if hit.arrival[t] is None else _ms(datetime.strptime(hit.arrival[t], "%Y%m%d%H"))
                for t in exposure.THRESHOLDS]
        # Tropical-storm-force wind from 17Z on 26 September, as the exposure
        # table and Here have it; nothing stronger.
        self.assertEqual(want, [_ms(datetime(2026, 9, 26, 17)), None, None])
        self.assertEqual(got["first"], want)
        self.assertEqual(got["here"], want)
        self.assertEqual(got["bands"], [_py_band(f, -104.32, 19.05) for _, f in path])

    def test_past_72_hours_a_64_kt_radius_nhc_does_not_forecast_is_not_forecast(self):
        lon, lat = -111.3, 22.2
        tid, path = _forecast(trudy_beyond_72())
        got = _run(self, AT + "var run = tcForecast(" + json.dumps(tid) + ", " + repr(lon) + ", " + repr(lat) + ");\n"
                   "console.log(JSON.stringify(run.at.map(function (a, k) {\n"
                   "  return [run.hours[k].hour, a.band.kt, a.band.unknown];\n})));",
                   extra=_live(trudy_beyond_72()))
        self.assertEqual([g[1:] for g in got], [_py_band(f, lon, lat) for _, f in path])
        # Inside her 50-kt wind from 89 h, her 64-kt not forecast until her
        # wind falls under 64 kt at 104 h.
        self.assertEqual([g[0] for g in got if g[2] == 64], list(range(89, 104)))

    def test_the_wind_comes_from_70_degrees_round_from_the_centre_and_not_within_10_km(self):
        cases = [(-80.0, 25.0, -79.0, 25.0), (-80.0, 25.0, -81.0, 25.0), (150.0, -20.0, 151.0, -20.0),
                 (150.0, -20.0, 149.0, -20.0), (-80.0, 25.0, -80.0, 26.0)]
        got = _run(self, "console.log(JSON.stringify(" + json.dumps(cases) + ".map(function (c) {\n"
                   "  return tcFrom({lon: c[0], lat: c[1]}, c[2], c[3]);\n"
                   "}).concat([tcFrom({lon: -80, lat: 25}, -80, 25.08), tcFrom({lon: -80, lat: 25}, -80, 25.1)])));")
        want = [(exposure.bearing(clon, clat, lon, lat) + (70 if clat >= 0 else -70)) % 360
                for clon, clat, lon, lat in cases]
        for g, w in zip(got, want):
            self.assertAlmostEqual(g, w, places=9)
        # East of a northern storm the wind comes from the SSE and west of it
        # the NNW; east of a southern storm from the NNE, west of it the SSW.
        self.assertEqual([round(g / 22.5) % 16 for g in got[:4]], [7, 15, 1, 9])
        # 8.9 km from the centre, not given; 11.1 km, given.
        self.assertIsNone(got[5])
        self.assertIsNotNone(got[6])

    def test_what_is_drawn_follows_the_band(self):
        got = _run(self, "console.log(JSON.stringify([0, 34, 50, 64].map(function (kt) {\n"
                   "  return tcLevel({kt: kt, unknown: null});\n}).concat([tcLevel({kt: 34, unknown: 50})])));")
        self.assertEqual([g["drops"] for g in got], [0, 160, 260, 380, 160])
        # Each step faster, darker and leaning further, with gusts at
        # hurricane force; a band whose next threshold is not known is drawn
        # as the band known.
        for key in ("speed", "gloom", "slant"):
            values = [g[key] for g in got[1:4]]
            self.assertEqual(values, sorted(set(values)))
        self.assertEqual([g["gusts"] for g in got], [False, False, False, True, False])
        self.assertEqual(got[1], {"kind": "storm", "drops": 160, "gloom": 0.22, "speed": 2, "slant": 0.45,
                                  "gusts": False})
        self.assertEqual(got[4], got[1])
        self.assertEqual([got[0]["drops"], got[0]["gloom"]], [0, 0])

    def test_the_choices_are_the_live_forecasts_then_the_storms_since_2004_newest_first(self):
        ids = {s["name"]: s["id"] for s in stormdesk.payload(_DeskFixtures().state(
            trudy(), _DeskFixtures().polo(), _DeskFixtures().nolo(), _DeskFixtures().surigae()))["storms"]}
        got = _run(self, AT + "var RAW = " + json.dumps(_replay_raw()) + ";\n" + MANZANILLO + r"""
          TC_DECODED = tcDecode(RAW);
          tcOpen();
          function said(list) { return list.map(function (c) { return [c.key, c.label]; }); }
          var live = tcChoices(-104.32, 19.05);
          D.storms = []; takeStorms();
          var past = tcChoices(-104.32, 19.05);
          console.log(JSON.stringify({live: said(live), first: tcDefault(live).key, past: said(past),
                                      strongest: tcDefault(past).key, none: tcDefault([])}));
        """, extra=STAGE)
        since = [["past:EP032020", "Charlie, Jul 2020"], ["past:EP022012", "Bravo, Aug 2012 (34 kt here)"],
                 ["past:EP012005", "Alpha, Sep 2005 (64 kt here)"]]
        # The live storms near with an official forecast, nearest first; then
        # the storms since 2004 whose 34-kt wind reached here (Bravo, 271 km
        # off) or whose centre passed within 100 n mi (Charlie, whose gales did
        # not reach), newest first; not Delta, before HURDAT2 kept radii, nor
        # Echo, nor the 1950s.
        self.assertEqual(got["live"][0], ["live:" + TRUDY_ID, "Trudy, NHC forecast (34 kt here)"])
        self.assertEqual(sorted(got["live"][1:3]), sorted([["live:" + ids["Polo"], "Polo, NHC forecast"],
                                                           ["live:" + ids["Nolo"], "Nolo, NHC forecast"]]))
        self.assertEqual(got["live"][3:], since)
        self.assertEqual(got["past"], since)
        # The first shown: the nearest live forecast, else the past storm that
        # brought the strongest wind here.
        self.assertEqual([got["first"], got["strongest"], got["none"]], ["live:" + TRUDY_ID, "past:EP012005", None])

    def test_a_live_run_s_hours_said(self):
        got = _run(self, AT + MANZANILLO + r"""
          var run = tcForecast("ep202026", -104.32, 19.05);
          console.log(JSON.stringify({n: run.hours.length, label: tcLabel(run), words: tcWords(run),
                                      read: [4, 38].map(function (k) { return tcRead(run, k); }),
                                      badge: [4, 38].map(function (k) { return tcBadge(run, k); })}));
        """, extra=REPLAY_STAGE)
        self.assertEqual([got["n"], got["label"]], [121, "Trudy, NHC forecast (34 kt here)"])
        self.assertEqual(got["read"], [
            "25 Sep 16:00 UTC: the centre 537 km SE, forecast 55 kt; here under 34 kt.",
            "27 Sep 02:00 UTC: the centre 133 km SW, forecast 102 kt; here 34\u201349 kt, from the ESE."])
        self.assertEqual(got["badge"], ["25 Sep 16:00 UTC \u00b7 centre 537 km SE \u00b7 under 34 kt",
                                        "27 Sep 02:00 UTC \u00b7 centre 133 km SW \u00b7 34\u201349 kt, from the ESE"])
        # When the wind comes and goes and how long it stays, as the exposure
        # table times it; how near the centre comes; what the replay is not.
        self.assertEqual(got["words"],
                         "<p><b>Trudy on NHC\u2019s official forecast (advisory 12)</b>. Wind here: 34 kt from 26 Sep "
                         "17:00 UTC until 27 Sep 13:00 UTC, 20 h; 50 and 64 kt do not reach here. Closest 133 km at 27 "
                         "Sep 02:00 UTC, forecast 102 kt there.</p><p>The replay follows the official track and wind "
                         "radii exactly, hour by hour; the cone and the chances carry the forecast\u2019s uncertainty, "
                         "and it shows neither.</p>")

    def test_the_words_say_each_spell_to_its_end_and_what_is_not_known(self):
        got = _run(self, r"""
          var T0 = Date.UTC(2020, 9, 1), Y = true, N = false, U = null;
          function run(live, rows) {
            return {live: live, name: "ZETA", year: 2020, title: "Zeta", centre: "NHC", advisory: "4",
                    hue: "#123456", official: null, near: 1, top: 34, hours: rows.map(function (r, k) {
                      return {t: T0 + k * HOUR, lat: 20, lon: -90, wind: 60, status: "TS", hour: k};
                    }), at: rows.map(function (r) {
                      return {km: 40, toward: 0, from: 90, band: {kt: r[0] ? 34 : 0, unknown: null,
                                                                   inside: {"34": r[0], "50": r[1], "64": r[2]}}};
                    })};
          }
          var rows = [[U, N, N], [Y, N, N], [Y, U, N], [N, U, N], [Y, N, N], [Y, N, N]];
          var past = run(false, rows), live = run(true, rows.map(function (r) { return [r[0], U, U]; }));
          var over = {live: false, hours: [{t: T0, wind: 60, status: "TS"}], at: [{km: 0.3, toward: 0, from: null,
                      band: {kt: 0, unknown: 34, inside: {"34": U, "50": U, "64": N}}}]};
          function said(r) { return /Wind here: (.*?)\. Closest/.exec(tcWords(r))[1]; }
          console.log(JSON.stringify({past: tcWords(past), live: tcWords(live), over: tcBadge(over, 0),
                                      calm: tcChartSaid(Object.assign(past, {top: 0})),
                                      start: said(run(false, [[Y, N, N], [Y, N, U], [N, N, U]])),
                                      analysis: said(run(true, [[Y, U, U], [Y, U, U], [Y, U, U]])),
                                      alike: said(run(false, [[Y, N, N], [Y, U, U], [N, N, N]]))}));
        """)
        # Two spells, the first not known before it, the second to the end,
        # counted to the last hour; a threshold that never comes said where it
        # is known not to and where it is not known; what never comes.
        self.assertTrue(got["past"].startswith(
            "<p><b>Zeta (2020) on HURDAT2\u2019s best track</b>. Wind here: 34 kt from 1 Oct 01:00 UTC (not known "
            "before) until 1 Oct 03:00 UTC, from 1 Oct 04:00 UTC to the track\u2019s end, 3 h in all; 50 kt does not "
            "reach here until 1 Oct 02:00 UTC, then not known until 1 Oct 04:00 UTC, then does not reach here; 64 kt "
            "does not reach here. Closest 40 km at 1 Oct 01:00 UTC, 60 kt there (tropical storm).</p>"),
            got["past"])
        # What no radius gives here at all, grouped.
        self.assertIn("Wind here: 34 kt from 1 Oct 01:00 UTC (not forecast before) until 1 Oct 03:00 UTC, from 1 Oct "
                      "04:00 UTC to the forecast\u2019s end, 3 h in all; 50 and 64 kt not forecast. Closest 40 km at 1 "
                      "Oct 01:00 UTC, forecast 60 kt there.</p>", got["live"])
        # A wind here at the first hour was here already: it did not come
        # then. Thresholds said alike are said together.
        self.assertEqual(got["start"], "34 kt from the track\u2019s start (1 Oct 00:00 UTC) until 1 Oct 02:00 UTC, 2 h; "
                                       "50 kt does not reach here; 64 kt does not reach here until 1 Oct 01:00 UTC, then "
                                       "not known")
        self.assertEqual(got["analysis"], "34 kt from the analysis (1 Oct 00:00 UTC) to the forecast\u2019s end, 2 h; 50 "
                                          "and 64 kt not forecast")
        self.assertEqual(got["alike"], "34 kt from the track\u2019s start (1 Oct 00:00 UTC) until 1 Oct 02:00 UTC, 2 h; "
                                       "50 and 64 kt do not reach here until 1 Oct 01:00 UTC, then not known until 1 Oct "
                                       "02:00 UTC, then do not reach here")
        # The centre within half a kilometre is over the point; a storm whose
        # gales never come is said so, where its wind is known.
        self.assertEqual(got["over"], "1 Oct 00:00 UTC \u00b7 centre over here \u00b7 wind not known")
        self.assertEqual(got["calm"], "Zeta\u2019s centre from here and its wind here, hour by hour from 1 Oct 00:00 "
                                      "UTC to 1 Oct 05:00 UTC: closest 40 km at 1 Oct 01:00 UTC; never 34 kt or more "
                                      "here where its wind is known.")

    def test_a_past_storm_is_named_by_the_month_and_year_it_came_nearest(self):
        got = _run(self, r"""
          var zeta = {live: false, name: "ZETA", year: 2005, top: 34, near: 1,
                      hours: [{t: Date.UTC(2005, 11, 31, 23)}, {t: Date.UTC(2006, 0, 1, 0)}]};
          console.log(JSON.stringify(tcLabel(zeta)));
        """)
        # Zeta of 2005's season came nearest on New Year's Day 2006.
        self.assertEqual(got, "Zeta, Jan 2006 (34 kt here)")

    def test_a_live_run_names_the_centre_s_own_chance_where_its_product_names_the_town(self):
        got = _run(self, AT + MANZANILLO + r"""
          var run = tcForecast("ep202026", -104.32, 19.05);
          run.official = {place: "Manzanillo", chances: {"34": 45, "50": 0, "64": null}, hours: 120};
          console.log(JSON.stringify(tcWords(run)));
        """, extra=REPLAY_STAGE)
        self.assertIn("</p><p>NHC\u2019s own chance at MANZANILLO within 120 h: 34 kt 45%, 50 kt &lt;1%, 64 kt not "
                      "listed.</p><p>The replay follows", got)

    def test_a_past_run_s_hours_said_and_tabled(self):
        [alpha] = [t for t in cyclones.hurdat_tracks(REPLAYS) if t.name == "ALPHA"]
        got = _run(self, "var RAW = " + json.dumps(_replay_raw()) + ";\n" + r"""
          var run = tcBest(tcDecode(RAW).filter(function (s) { return s.id === "EP012005"; })[0], -104.32, 19.05);
          console.log(JSON.stringify({n: run.hours.length, top: run.top, label: tcLabel(run), words: tcWords(run),
            read: [0, 6, 13].map(function (k) { return tcRead(run, k); }),
            badge: [6, 13].map(function (k) { return tcBadge(run, k); }), hours: tcHours(run),
            bands: run.at.map(function (a) { return [a.band.kt, a.band.unknown]; })}));
        """)
        self.assertEqual([got["n"], got["top"], got["label"]], [19, 64, "Alpha, Sep 2005 (64 kt here)"])
        self.assertEqual(got["bands"], [_py_band(f, -104.32, 19.05) for _, f in _py_hourly(alpha)])
        self.assertEqual(got["read"], [
            "1 Sep 00:00 UTC: the centre 119 km SSE, 60 kt, tropical storm; here under 34 kt.",
            "1 Sep 06:00 UTC: the centre 24 km ESE, 80 kt, hurricane; here 64 kt or more, from the N.",
            "1 Sep 13:00 UTC: the centre 126 km N, 76 kt, hurricane; the wind here not known."])
        self.assertEqual(got["badge"], ["1 Sep 06:00 UTC \u00b7 centre 24 km ESE \u00b7 64 kt or more, from the N",
                                        "1 Sep 13:00 UTC \u00b7 centre 126 km N \u00b7 wind not known"])
        self.assertEqual(got["words"],
                         "<p><b>Alpha (2005) on HURDAT2\u2019s best track</b>. Wind here: 34 kt from 1 Sep 02:00 UTC "
                         "until 1 Sep 13:00 UTC (then not known), 11 h; 50 kt from 1 Sep 04:00 UTC until 1 Sep 10:00 "
                         "UTC, 6 h; 64 kt from 1 Sep 06:00 UTC until 1 Sep 08:00 UTC, 2 h. Closest 24 km at 1 Sep "
                         "06:00 UTC, 80 kt there (hurricane).</p><p>The replay follows HURDAT2\u2019s analysed track "
                         "and wind radii, made hourly; each is an analysis with its own uncertainty.</p>")
        # Every three hours: the time, where the centre is and its wind, the
        # wind here and, inside the gales, where it comes from.
        head = "".join(f'<th scope="col">{h}</th>' for h in ("Time", "Centre from here", "Wind at the centre",
                                                              "Wind here", "From"))
        rows = (("1 Sep 00:00 UTC", "119 km SSE", "60 kt", "under 34 kt", ""),
                ("1 Sep 03:00 UTC", "65 km SSE", "70 kt", "34\u201349 kt", "NE"),
                ("1 Sep 06:00 UTC", "24 km ESE", "80 kt", "64 kt or more", "N"),
                ("1 Sep 09:00 UTC", "54 km NNE", "84 kt", "50\u201363 kt", "W"),
                ("1 Sep 12:00 UTC", "108 km NNE", "80 kt", "34\u201349 kt", "W"),
                ("1 Sep 15:00 UTC", "163 km N", "68 kt", "not known", ""),
                ("1 Sep 18:00 UTC", "218 km N", "55 kt", "not known", ""))
        body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in rows)
        self.assertEqual(got["hours"], f'<table class="streettable"><thead><tr>{head}</tr></thead><tbody>{body}'
                                       "</tbody></table>")

    def test_the_chart_draws_the_distance_the_strips_the_unknown_hatched_and_now(self):
        got = _run(self, AT + "var RAW = " + json.dumps(_replay_raw()) + ";\n" + MANZANILLO + r"""
          var alpha = tcBest(tcDecode(RAW).filter(function (s) { return s.id === "EP012005"; })[0], -104.32, 19.05);
          var trudy = tcForecast("ep202026", -104.32, 19.05);
          console.log(JSON.stringify({alpha: tcChart(alpha, 400), trudy: tcChart(trudy, 400), keys: [tcKey(alpha),
                                      tcKey(trudy)]}));
        """, extra=REPLAY_STAGE)
        svg, geo = got["alpha"]["svg"], got["alpha"]["geo"]
        # Room on the left for the scale's widest label, "1,000 km" and
        # more, which 36 px cut to "000 km" in every browser.
        self.assertEqual(geo, {"L": 50, "W": 338, "N": 19, "T": 8, "PH": 72, "top": 250, "width": 400})

        def x(k, n=19):
            return _r1(50 + min(max(k, 0), n - 1) * 338 / (n - 1))

        def strip(cls, k0, k1, y):
            fill = "url(#street-tc-hatch)" if cls == "unk" else "var(--ink2)"
            return (f'<rect class="{cls}" x="{x(k0 - 0.5):g}" y="{y}" width="{_r1(x(k1 + 0.5) - x(k0 - 0.5)):g}" '
                    f'height="10" style="fill:{fill}"/>')
        # A strip a threshold, filled where Alpha's wind was over the town -
        # 34 kt from 02:00 to 12:00, 50 from 04:00 to 09:00, 64 at 06:00 and
        # 07:00 - and hatched from 13:00, where neither 34 nor 50 is known.
        for part in (strip("b34", 2, 12, 90), strip("b50", 4, 9, 103), strip("b64", 6, 7, 116),
                     strip("unk", 13, 18, 90), strip("unk", 13, 18, 103)):
            self.assertIn(part, svg)
        self.assertEqual([svg.count(f'class="{c}"') for c in ("b34", "b50", "b64", "unk", "lane")], [1, 1, 1, 2, 3])
        self.assertIn('<pattern id="street-tc-hatch"', svg)
        # The distance on a scale to 250 km, 0 at the foot; ticks at 00 and 12
        # UTC, the day at 00; the playhead; no "now" on a past storm.
        for part in ('<text x="46" y="83.5" text-anchor="end">0</text>',
                     '<text x="46" y="11.5" text-anchor="end">250 km</text>',
                     '<line class="tick" x1="50" x2="50" y1="126" y2="130"/><text x="52" y="142">1 Sep</text>',
                     f'<line class="tick" x1="{x(12):g}" x2="{x(12):g}" y1="126" y2="130"/>',
                     '<text x="46" y="98.5" text-anchor="end">34 kt</text>',
                     '<line id="street-tc-head" class="head" x1="50" x2="50" y1="8" y2="126"/>',
                     '<circle id="street-tc-dot" class="dot" r="3.5" cx="50" cy="80"/>'):
            self.assertIn(part, svg)
        self.assertRegex(svg, r'<path class="dist" d="M50,[\d.]+(L[\d.]+,[\d.]+){18}"/>')
        self.assertNotIn("tcnow", svg)
        self.assertIn('aria-label="Alpha\u2019s centre from here and its wind here, hour by hour from 1 Sep 00:00 UTC '
                      'to 1 Sep 18:00 UTC: closest 24 km at 1 Sep 06:00 UTC; at its strongest here, 64 kt or more."',
                      svg)
        self.assertTrue(svg.startswith('<svg class="streetsimsvg streettcsvg" viewBox="0 0 400 144" width="400" '
                                       'height="144" role="img"'), svg[:120])
        # Trudy's forecast: "now" at 16Z, four hours in; nothing hatched.
        live = got["trudy"]["svg"]
        now = _r1(50 + 4 * 338 / 120)
        self.assertIn(f'<line class="tcnow" x1="{now:g}" x2="{now:g}" y1="8" y2="126"/><text class="tcnow" '
                      f'x="{_r1(now + 3):g}" y="77">now</text>', live)
        self.assertEqual([live.count('class="b34"'), live.count('class="unk"'), live.count("street-tc-hatch")],
                         [1, 0, 0])
        self.assertEqual(got["trudy"]["geo"]["top"], 1200)
        self.assertIn("style=\"fill:var(--s1)\"", live)
        # The key: the distance, what a filled strip is, the hatching where
        # there is any, and "now" on a forecast.
        self.assertEqual(got["keys"], [
            '<span class="dist">the centre\u2019s distance</span><span class="wind" style="--hue:var(--ink2)">filled: '
            'that wind here</span><span class="unk" style="--hue:var(--ink2)">hatched: not known</span>',
            '<span class="dist">the centre\u2019s distance</span><span class="wind" style="--hue:var(--s1)">filled: '
            'that wind here</span><span class="tcnow">now</span>'])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheReplayOnThePanel(unittest.TestCase):
    """The replay in the open panel at Manzanillo, under node over the faked
    DOM at 16Z on 25 September 2026: Trudy's forecast and the past storms by
    the town as the tracks; Play, the slider and the chart; the wind drawn
    over the panorama; and the run, the point and the other panel changing."""

    def run_replay(self, body: str, extra: str = REPLAY_STAGE):
        return _run(self, AT + "var RAW = " + json.dumps(_replay_raw()) + ";\n" + LAZY + TC_TICKS + RAIN_CTX + body,
                    extra=extra)

    def test_the_replay_opens_on_the_live_forecast_at_the_hour_now_and_takes_the_past_storms_once_read(self):
        got = self.run_replay(MANZANILLO + r"""
          tcOpen();
          function shown() {
            return {options: $("street-tc-run").innerHTML, value: $("street-tc-run").value,
                    off: [$("street-tc-run").disabled, $("street-tc-play").disabled, $("street-tc-hour").disabled],
                    max: $("street-tc-hour").max, hour: $("street-tc-hour").value, speed: $("street-tc-speed").value,
                    read: $("street-tc-read").textContent, text: $("street-tc-hour").getAttribute("aria-valuetext"),
                    badge: [$("street-day").textContent, $("street-day").hidden, $("street-rain").hidden],
                    every: $("street-tc-every").hidden, chart: $("street-tc-chart").innerHTML.indexOf("<svg") === 0,
                    words: $("street-tc-said").innerHTML.indexOf("<p><b>Trudy on NHC") === 0};
          }
          var opened = shown();
          land(0); await flush();
          console.log(JSON.stringify({opened: opened, read: shown()}));
        """)
        live = ('<optgroup label="Official forecasts"><option value="live:ep202026">Trudy, NHC forecast (34 kt here)'
                "</option></optgroup>")
        badge = "25 Sep 16:00 UTC \u00b7 centre 537 km SE \u00b7 under 34 kt"
        self.assertEqual(got["opened"], {
            "options": live, "value": "live:ep202026", "off": [False, False, False], "max": "120", "hour": "4",
            "speed": "6", "read": "25 Sep 16:00 UTC: the centre 537 km SE, forecast 55 kt; here under 34 kt.",
            "text": badge, "badge": [badge, False, True], "every": False, "chart": True, "words": True})
        self.assertEqual(got["read"]["options"], live + '<optgroup label="Since 2004">'
                         '<option value="past:EP032020">Charlie, Jul 2020</option>'
                         '<option value="past:EP022012">Bravo, Aug 2012 (34 kt here)</option>'
                         '<option value="past:EP012005">Alpha, Sep 2005 (64 kt here)</option></optgroup>')
        self.assertEqual([got["read"]["value"], got["read"]["hour"]], ["live:ep202026", "4"])

    def test_play_steps_the_hours_at_the_speed_chosen_and_stops_at_the_end(self):
        got = self.run_replay(MANZANILLO + r"""
          tcOpen();
          $("street-tc-play").fire("click");
          var started = [S.tc.playing, $("street-tc-play").textContent, tcTicking()];
          frames(16);
          frames(250);
          var moved = [S.tc.pos, S.tc.k];
          frames(5000);
          var held = [S.tc.pos, S.tc.k];
          $("street-tc-speed").value = "12";
          $("street-tc-speed").fire("change");
          frames(250);
          var faster = [S.tc.speed, S.tc.k];
          for (var i = 0; i < 60; i++) frames(250);
          var ended = [S.tc.playing, S.tc.k, $("street-tc-play").textContent];
          $("street-tc-play").fire("click");
          console.log(JSON.stringify({started: started, moved: moved, held: held, faster: faster, ended: ended,
                                      again: [S.tc.k, S.tc.playing]}));
        """)
        # Six hours a second from the hour now (4): a quarter second is an hour
        # and a half; a frame held back five seconds counts a quarter second.
        self.assertEqual(got["started"], [True, "Pause", 1])
        self.assertEqual(got["moved"], [5.5, 5])
        self.assertEqual(got["held"], [7, 7])
        self.assertEqual(got["faster"], [12, 10])
        self.assertEqual(got["ended"], [False, 120, "Play"])
        # Play at the last hour starts again from the first.
        self.assertEqual(got["again"], [0, True])

    def test_the_slider_and_the_chart_seek_the_hour(self):
        got = self.run_replay(MANZANILLO + r"""
          $("street-tc-chart").box = {left: 100, top: 0, width: 400, height: 144};
          tcOpen();
          var hour = $("street-tc-hour"), chart = $("street-tc-chart");
          hour.value = "38";
          hour.fire("input");
          var slid = [S.tc.k, S.tc.pos, $("street-tc-read").textContent];
          function at(k) { return 100 + 50 + 338 * k / 120; }
          chart.fire("pointerdown", {clientX: at(60), clientY: 50, pointerId: 1, pointerType: "mouse", button: 0});
          var down = S.tc.k;
          chart.fire("pointermove", {clientX: at(90), clientY: 50, pointerId: 1});
          var moved = S.tc.k;
          chart.fire("pointerup", {clientX: at(90), clientY: 50, pointerId: 1});
          chart.fire("pointermove", {clientX: at(100), clientY: 50, pointerId: 1});
          var after = S.tc.k;
          chart.fire("pointerdown", {clientX: at(10), clientY: 50, pointerId: 2, pointerType: "touch", button: 0});
          chart.fire("pointermove", {clientX: at(10) + 5, clientY: 50, pointerId: 2});
          var small = S.tc.k;
          chart.fire("pointermove", {clientX: at(20), clientY: 52, pointerId: 2});
          console.log(JSON.stringify({slid: slid, mouse: [down, moved, after], touch: [small, S.tc.k]}));
        """)
        self.assertEqual(got["slid"], [38, 38, "27 Sep 02:00 UTC: the centre 133 km SW, forecast 102 kt; here "
                                               "34\u201349 kt, from the ESE."])
        # A mouse seeks where it goes down and on as it moves until let go; a
        # finger only once it has gone across.
        self.assertEqual(got["mouse"], [60, 90, 90])
        self.assertEqual(got["touch"], [90, 20])

    def test_the_band_is_drawn_over_the_panorama_and_the_badge_names_the_hour(self):
        got = self.run_replay(MANZANILLO + r"""
          tcOpen();
          land(0); await flush();
          function drawn() {
            OPS = [];
            frames(16);
            return [$("street-rain").hidden, $("street-day").hidden, count("drop"), tcTicking()];
          }
          var calm = drawn();
          tcSeekHour(38);
          var gale = drawn();
          $("street-tc-run").value = "past:EP032020";
          $("street-tc-run").fire("change");
          var calmest = [S.tc.k, S.tc.run.near];
          $("street-tc-run").value = "past:EP012005";
          $("street-tc-run").fire("change");
          var picked = [S.tc.k, $("street-day").textContent];
          tcSeekHour(4);
          var storm = drawn();
          tcSeekHour(6);
          var hurricane = [drawn(), S.tc.rain.gusts, $("street-day").textContent];
          tcSeekHour(13);
          console.log(JSON.stringify({calm: calm, gale: gale, calmest: calmest, picked: picked, storm: storm,
                                      hurricane: hurricane, unknown: [drawn(), $("street-day").textContent]}));
        """)
        # Nothing under 34 kt, and no frame asked for; then 160, 260 and 380
        # streaks, a frame at a time, with gusts at hurricane force; nothing
        # where the band is not known. The badge names the hour.
        self.assertEqual(got["calm"], [True, False, 0, 0])
        self.assertEqual(got["gale"], [False, False, 160, 1])
        # A past storm opens at its first hour of 34-kt wind here, not on an
        # empty street hours before it; one whose gales never came, at its
        # closest.
        self.assertEqual(got["calmest"], [6, 6])
        self.assertEqual(got["picked"], [2, "1 Sep 02:00 UTC \u00b7 centre 83 km SSE \u00b7 34\u201349 kt, from the NE"])
        self.assertEqual(got["storm"], [False, False, 260, 1])
        self.assertEqual(got["hurricane"], [[False, False, 380, 1], True,
                                            "1 Sep 06:00 UTC \u00b7 centre 24 km ESE \u00b7 64 kt or more, from the N"])
        self.assertEqual(got["unknown"], [[True, False, 0, 0],
                                          "1 Sep 13:00 UTC \u00b7 centre 126 km N \u00b7 wind not known"])

    def test_under_reduced_motion_the_wind_is_drawn_still(self):
        got = self.run_replay(MANZANILLO + r"""
          window.matchMedia = function (q) { return {matches: /reduce/.test(q)}; };
          tcOpen();
          OPS = [];
          tcSeekHour(38);
          var still = [count("clear"), count("drop"), tcTicking()];
          $("street-tc-play").fire("click");
          frames(16);
          frames(250);
          console.log(JSON.stringify([still, [S.tc.k, count("clear"), tcTicking()]]));
        """)
        # Drawn once, still, and no frame asked for; Play still steps the
        # hours, and each it reaches is drawn once.
        self.assertEqual(got, [[1, 160, 0], [39, 2, 1]])

    def test_one_frame_loop_and_one_rain_as_the_two_replays_take_turns(self):
        got = _run(self, AT + PANEL_SETUP + RAIN_CTX + TC_TICKS + MANZANILLO + r"""
          function state() {
            return {sim: ticking(), tc: tcTicking(), frames: FRAMES.length, day: $("street-day").textContent,
                    badge: $("street-day").hidden, rain: $("street-rain").hidden, head: $("street-chip-head").hidden};
          }
          simOpen();
          await flush();
          var sim = state();
          tcOpen();
          tcSeekHour(38);
          var tc = state();
          simOpen();
          await flush();
          var back = state();
          tcOpen();
          var calm = state();
          tcClose();
          console.log(JSON.stringify({sim: sim, tc: tc, back: back, calm: calm, none: state()}));
        """, extra=REPLAY_STAGE)
        # One replay's frames at a time, its rain on the canvas and its badge,
        # the chip's head hidden while either is open.
        sim = {"sim": 1, "tc": 0, "frames": 1, "day": "1 October 1982: 1.0 mm", "badge": False, "rain": False,
               "head": True}
        self.assertEqual(got["sim"], sim)
        self.assertEqual(got["tc"], {"sim": 0, "tc": 1, "frames": 1, "day": "27 Sep 02:00 UTC \u00b7 centre 133 km "
                                     "SW \u00b7 34\u201349 kt, from the ESE", "badge": False, "rain": False,
                                     "head": True})
        self.assertEqual(got["back"], sim)
        # Opened again, at the hour now: under 34 kt, so no streaks and no
        # frame; closed, nothing over the panorama and the chip's head back.
        calm = "25 Sep 16:00 UTC \u00b7 centre 537 km SE \u00b7 under 34 kt"
        self.assertEqual(got["calm"], {"sim": 0, "tc": 0, "frames": 0, "day": calm, "badge": False, "rain": True,
                                       "head": True})
        self.assertEqual(got["none"], {"sim": 0, "tc": 0, "frames": 0, "day": calm, "badge": True, "rain": True,
                                       "head": False})

    def test_a_run_taken_in_place_keeps_the_hour_by_its_time_or_falls_back_when_the_storm_is_gone(self):
        got = self.run_replay(MANZANILLO + r"""
          tcOpen();
          tcSeekHour(38);
          $("street-tc-play").fire("click");
          frames(16);
          D.storms = NEXT; takeStorms(); tcRetake();
          var kept = [S.tc.key, utc(S.tc.run.hours[S.tc.k].t), S.tc.k, S.tc.playing, S.tc.run.hours.length];
          D.storms = []; takeStorms(); tcRetake();
          var gone = [S.tc.key, S.tc.playing, $("street-tc-play").disabled, $("street-tc-run").disabled,
                      $("street-tc-hour").disabled, $("street-tc-said").innerHTML, tcTicking(),
                      $("street-rain").hidden, $("street-day").hidden];
          land(0); await flush();
          console.log(JSON.stringify({kept: kept, gone: gone,
                                      after: [S.tc.key, S.tc.k, $("street-tc-play").disabled]}));
        """.replace("NEXT", _storms(trudy_next())))
        # Her next advisory, six hours on: the same time, 32 hours into it,
        # still playing.
        self.assertEqual(got["kept"], ["live:ep202026", "27 Sep 02:00 UTC", 32, True, 121])
        # Gone from the run: Play stops and, with nothing else yet, the
        # controls are off and say why; once the tracks are read, the past
        # storm that brought the strongest wind here.
        self.assertEqual(got["gone"], ["", False, True, True, True,
                                       "<p>No live tropical cyclones; the storms since 2004 come when the storm tracks "
                                       "are read.</p>", 0, True, True])
        self.assertEqual(got["after"], ["past:EP012005", 2, False])

    def test_with_the_tracks_unread_the_live_forecast_still_plays_and_retry_brings_the_past(self):
        got = self.run_replay(MANZANILLO + r"""
          tcOpen();
          miss(0); await flush();
          var failed = [$("street-tc-run").innerHTML.indexOf("Since 2004") >= 0, $("street-tc-run").value,
                        $("street-tc-play").disabled, $("street-tc-fail").hidden];
          $("street-tc-play").fire("click");
          frames(16);
          frames(250);
          var played = [S.tc.playing, S.tc.k];
          $("street-tc-retry").fire("click");
          land(1); await flush();
          console.log(JSON.stringify({failed: failed, played: played,
                                      retried: [$("street-tc-run").innerHTML.indexOf("Since 2004") >= 0, S.tc.key,
                                                S.tc.playing]}));
        """)
        self.assertEqual(got["failed"], [False, "live:ep202026", False, False])
        self.assertEqual(got["played"], [True, 5])
        self.assertEqual(got["retried"], [True, "live:ep202026", True])

    def test_with_nothing_to_replay_the_controls_are_off_and_say_why(self):
        body = LIMA_TC + r"""
          tcOpen();
          var reading = $("street-tc-said").innerHTML;
          WHEN; await flush();
          console.log(JSON.stringify({reading: reading, read: $("street-tc-said").innerHTML,
            off: [$("street-tc-run").disabled, $("street-tc-play").disabled, $("street-tc-hour").disabled],
            rest: [$("street-tc-run").innerHTML, $("street-tc-key").innerHTML, $("street-tc-chart").innerHTML,
                   $("street-tc-read").textContent, $("street-tc-every").hidden, $("street-day").hidden]}));
        """
        landed = self.run_replay(body.replace("WHEN", "land(0)"), extra=STAGE)
        missed = self.run_replay(body.replace("WHEN", "miss(0)"), extra=STAGE)
        far = "<p>No live storm\u2019s official forecast comes within 1,500 km of here"
        self.assertEqual(landed["reading"], far + "; the storms since 2004 come when the storm tracks are read.</p>")
        # Lima is outside HURDAT2's basins: said so, as the history below
        # says it, not "no storm since 2004".
        self.assertEqual(landed["read"], far + ", and the storms since 2004 come from HURDAT2, which does not cover "
                                               "here.</p>")
        self.assertEqual(missed["read"], far + ", and the storm tracks, for the storms since 2004, could not be "
                                               "read.</p>")
        for got in (landed, missed):
            self.assertEqual([got["off"], got["rest"]], [[True, True, True], ["", "", "", "", True, True]])

    def test_moving_the_street_keeps_a_storm_still_near_and_otherwise_falls_back(self):
        got = self.run_replay(MANZANILLO + r"""
          tcOpen();
          land(0); await flush();
          tcSeekHour(38);
          $("street-tc-play").fire("click");
          streetEnter(-104.0, 19.2, "Colima coast");
          var near = [S.tc.key, S.tc.k, S.tc.playing];
          streetEnter(-77.0428, -12.0464, "Lima");
          console.log(JSON.stringify({near: near, lima: [S.tc.key, $("street-tc-play").disabled, tcTicking()]}));
        """)
        # Moved, the replay stops where it was, as the El Nino replay does; a
        # storm still near is kept at the same time.
        self.assertEqual(got["near"], ["live:ep202026", 38, False])
        self.assertEqual(got["lima"], ["", True, 0])

    def test_closing_the_panel_or_leaving_stops_play_and_lets_the_canvas_go(self):
        got = self.run_replay(MANZANILLO + r"""
          tcOpen();
          tcSeekHour(38);
          $("street-tc-play").fire("click");
          var open = [tcTicking(), $("street-rain").hidden];
          tcClose();
          var closed = [tcTicking(), FRAMES.length, $("street-rain").hidden, $("street-day").hidden];
          tcOpen();
          tcSeekHour(38);
          streetLeave();
          console.log(JSON.stringify({open: open, closed: closed,
                                      left: [FRAMES.length, $("street-rain").hidden, $("street-day").hidden]}));
        """)
        self.assertEqual(got, {"open": [1, False], "closed": [0, 0, True, True], "left": [0, True, True]})


# ---- naming a point ----
# The gazetteer's rows within a few hundred kilometres of New York, as the
# page has them.
NEAR_NEW_YORK = [row for row in _asset_value(assets.places()) if abs(row[5] - 40.7) < 3 and abs(row[4] + 74) < 4]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestNamingAPoint(unittest.TestCase):
    """placeLabel: a point is in the nearest town whose people reach it - as
    far as a disc of them at 2,000 a square kilometre would, 1.5 to 30 km -
    else so far from the nearest place within 400 km, else at its position;
    and Here's line says the same after the position (placeFact)."""

    def test_staten_island_is_in_new_york_and_downtown_newark_in_newark(self):
        got = _run(self, "PLACES = " + json.dumps(NEAR_NEW_YORK) + ";\n" + r"""
          var points = [[-74.15, 40.58], [-74.172, 40.735], [-74.17, 40.7]];
          console.log(JSON.stringify({
            names: points.map(function (p) { return placeLabel(p[0], p[1]); }),
            facts: points.map(function (p) { return placeFact(p[0], p[1], placeLabel(p[0], p[1])); }),
            reach: [placeReach(19040000), placeReach(280123), placeReach(10000), placeReach(0), placeReach(null)]}));
        """)
        # Staten Island is 13.4 km from Newark's point and 20.4 km from New
        # York's: Newark's 280,123 people reach 6.7 km, New York's 19 million
        # the most there is, 30 km. Downtown Newark, 3.9 km from its point
        # and 14.9 km from New York's, is in both, and named by the nearer.
        self.assertEqual(got["names"], ["New York, United States of America",
                                        "Newark, New Jersey, United States of America",
                                        "Newark, New Jersey, United States of America"])
        self.assertEqual(got["facts"], ["19,040,000 people (Natural Earth)", "280,123 people (Natural Earth)",
                                        "280,123 people (Natural Earth)"])
        self.assertEqual(got["reach"][0], 30)
        self.assertAlmostEqual(got["reach"][1], math.sqrt(280123 / (math.pi * 2000)), places=9)
        self.assertEqual(got["reach"][2:], [1.5, 1.5, 1.5])

    def test_a_small_town_reaches_a_short_way_and_the_open_sea_is_a_position(self):
        got = _run(self, r"""
          PLACES = [["Ashby", "Nowhere", "", 10000, 10, 0, 0]];
          var deg = 180 / (Math.PI * 6371), points = [[10 + 1.4 * deg, 0], [10 + 5 * deg, 0], [10 + 401 * deg, 0],
                                                       [-150, -40]];
          console.log(JSON.stringify({
            names: points.map(function (p) { return placeLabel(p[0], p[1]); }),
            facts: points.map(function (p) { return placeFact(p[0], p[1], placeLabel(p[0], p[1])); }),
            far: where(points[2][0], 0)}));
        """)
        # 10,000 people reach 1.5 km: 1.4 km out is in the town, 5 km out is
        # 5 km from it; past 400 km, and out at sea, a point is its position.
        self.assertEqual(got["names"], ["Ashby, Nowhere", "5 km from Ashby, Nowhere", got["far"], "40.00S 150.00W"])
        self.assertEqual(got["far"], "0.00N 13.61E")
        self.assertEqual(got["facts"], ["10,000 people (Natural Earth)", "5 km from Ashby", "", ""])

    def test_here_s_line_says_what_its_name_says(self):
        show = _js_function(stormdesk.script(), "showHere")
        self.assertIn("var facts = [where(h.lon, h.lat)], fact = placeFact(h.lon, h.lat, S.here.label);", show)
        self.assertIn("if (fact) facts.push(fact);", show)
        self.assertNotIn("place.km <= 25", show)


RAW_DIR = ROOT / "data" / "raw"


@unittest.skipUnless(shutil.which("node"), "node is not installed")
@unittest.skipUnless(all((RAW_DIR / f"{name}.cache").exists() for name in ("hurdat_al", "hurdat_ep", "roni")),
                     "the raw HURDAT2 and RONI caches are not here")
class TestTheRealRecord(unittest.TestCase):
    """The count since 1950 on HURDAT2 and RONI as the tracker last downloaded
    them, at Manhattan, Miami and Cabo San Lucas within 100 n mi, against an
    independent computation of the same rule: each leg walked in a hundred
    steps, the nearest step's distance great-circle, and the strongest wind,
    interpolated, among the steps within the distance."""

    POINTS = {"Manhattan": (-74.006, 40.7128), "Miami": (-80.19, 25.76), "Cabo San Lucas": (-109.91, 22.89)}
    RADIUS = 100 * 1.852

    @staticmethod
    def nearest(track, lon, lat, radius):
        """A track's nearest step to a point and its strongest wind among the
        steps within radius of it, each leg walked in a hundred steps, the
        longitude carried on across the date line; a leg with both fixes over
        1,500 km off is passed over."""
        fixes, best, top = track.fixes, math.inf, None
        lons = [fixes[0].lon]
        for a, b in zip(fixes, fixes[1:]):
            step = b.lon - a.lon
            lons.append(lons[-1] + step - 360 * round(step / 360))
        for i, j in list(zip(range(len(fixes) - 1), range(1, len(fixes)))) or [(0, 0)]:
            a, b = fixes[i], fixes[j]
            if min(_haversine(lon, lat, lons[i], a.lat), _haversine(lon, lat, lons[j], b.lat)) > 1500:
                continue
            for k in range(101):
                f = k / 100
                d = _haversine(lon, lat, lons[i] + f * (lons[j] - lons[i]), a.lat + f * (b.lat - a.lat))
                wind = (a.wind if f == 0 else b.wind if f == 1 else
                        None if a.wind is None or b.wind is None else a.wind + f * (b.wind - a.wind))
                best = min(best, d)
                if d <= radius and wind is not None and (top is None or wind > top):
                    top = wind
        return best, top

    def test_the_counts_agree_with_an_independent_computation(self):
        series = parsers.parse_roni((RAW_DIR / "roni.cache").read_text(encoding="utf-8"))
        tracks = {basin: tuple(cyclones.hurdat_tracks((RAW_DIR / f"hurdat_{basin.lower()}.cache")
                                                      .read_text(encoding="utf-8")))
                  for basin in ("AL", "EP")}
        state = SimpleNamespace(cyclones=cyclones.CycloneState(tracks=tracks, track_files={}),
                                assessment=SimpleNamespace(index_series=series, index_name="RONI"))
        got = _run(self, "D.tc = %s;\nvar tracks = tcDecode(%s);\n" % (json.dumps(streetstorms.payload(state)),
                                                                     json.dumps(streetstorms.tracks_payload(state)))
                   + "console.log(JSON.stringify(%s.map(function (p) {\n"
                     "  var past = tcPast(tracks, p[0], p[1], %r);\n"
                     "  return {ids: past.rows.map(function (r) { return r.id; }), counts: past.counts, "
                     "covered: past.covered};\n})));" % (json.dumps(list(self.POINTS.values())), self.RADIUS))
        phase = {}
        for item in series:
            if item.season == cyclones.SEASON_KEY and item.year >= 1950:
                value = classify.displayed(item.value)
                phase[item.year] = "warm" if value >= 0.5 else "cool" if value <= -0.5 else "neutral"
        kept = [t for basin in tracks.values() for t in basin if t.year >= 1950 and (t.peak or 0) >= 34]
        last = max(t.year for t in kept)
        seasons = {name: sum(1 for year in range(1950, last + 1) if phase.get(year) == name)
                   for name in ("warm", "cool", "neutral")}
        for (place, (lon, lat)), js in zip(self.POINTS.items(), got):
            with self.subTest(place):
                near = {t.id: self.nearest(t, lon, lat, self.RADIUS) for t in kept}
                counted = {i for i, (d, w) in near.items() if d <= self.RADIUS and w is not None and w >= 34}
                # A storm within 2 km or 1 kt of the rule's edges is either
                # computation's to call.
                edge = {i for i, (d, w) in near.items()
                        if abs(d - self.RADIUS) < 2 or (w is not None and abs(w - 34) < 1)}
                self.assertGreater(len(counted), 10)
                self.assertEqual(set(js["ids"]) - edge, counted - edge)
                self.assertTrue(js["covered"])
                for name in ("warm", "cool", "neutral"):
                    storms = sum(1 for i in js["ids"] if phase.get(int(i[4:8])) == name)
                    self.assertEqual(js["counts"][name], {"storms": storms, "seasons": seasons[name]})


if __name__ == "__main__":
    unittest.main()
