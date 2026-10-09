"""Street View, and what El Nino does to the street dropped into
(elnino/street.py, and its hooks in the desk's page)."""

from __future__ import annotations

import copy
import html as htmllib
import importlib.util
import json
import math
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from elnino import atlas, stormdesk, street, thennow, worldmap  # noqa: E402
from elnino.svg import esc  # noqa: E402
# The helpers only: importing a TestCase class here would run it twice.
from test_thennow import EVENT, MANAUS, MODIS_DAYS, SCREEN, _run, seasons_from, state_with  # noqa: E402
from test_tracker import _DeskFixtures, _js_function, _node_json  # noqa: E402


def composite_tool():
    """tools/vendor_composite.py, the script that composited the atlas."""
    spec = importlib.util.spec_from_file_location("vendor_composite", ROOT / "tools" / "vendor_composite.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestStreetPayload(unittest.TestCase):
    """What the page carries for the card: the tracker's index month by month,
    the atlas composite's own rules, and where each source is asked."""

    def test_the_index_is_given_by_its_centre_month_as_cpc_prints_it(self):
        # NDJ 1978 is centred on December 1978, before the record the card
        # reads; 0.15 and 0.25 print as CPC prints them, ties away from zero.
        series = seasons_from("NDJ", 1978, (0.9, 0.15, 0.25, -0.46, 1.04))
        months = street.payload(state_with(series))["months"]
        self.assertEqual(months, {"from": "1979-01", "values": [0.2, 0.3, -0.5, 1.0]})

    def test_a_season_the_record_lacks_is_a_gap_not_a_neighbour(self):
        series = seasons_from("DJF", 2000, (0.1, 0.2, 0.3, 0.4))
        del series[1]
        self.assertEqual(street.payload(state_with(series))["months"],
                         {"from": "2000-01", "values": [0.1, None, 0.3, 0.4]})

    def test_the_months_run_from_the_first_season_on_record_to_the_last(self):
        months = street.payload(state_with(EVENT))["months"]
        first = EVENT[0].centre
        self.assertEqual(months["from"], f"{first:%Y-%m}")
        self.assertEqual(len(months["values"]), len(EVENT))
        self.assertEqual(months["values"][-1], -0.6)

    def test_with_no_index_there_are_no_months(self):
        state = SimpleNamespace(run_at=None, assessment=SimpleNamespace(index_name=None, index_series=[]))
        payload = street.payload(state)
        self.assertEqual(payload["months"], {"from": None, "values": []})
        self.assertEqual(payload["index"], "RONI")

    def test_the_rules_are_the_atlas_composite_s_own(self):
        tool, payload = composite_tool(), street.payload(state_with(EVENT))
        self.assertEqual((payload["warm"], payload["neutral"]), (tool.WARM, tool.NEUTRAL))
        self.assertEqual((payload["min_events"], payload["min_years"]), (tool.MIN_EVENTS, tool.MIN_YEARS))
        self.assertEqual(payload["t975"], [tool.T975[df] for df in range(1, 31)])

    def test_rain_is_a_percentage_only_from_the_atlas_s_dry_floor_up(self):
        self.assertEqual(street.payload(state_with(EVENT))["dry_floor"], atlas.DRY_FLOOR)

    def test_each_source_is_asked_for_the_point_and_nothing_else(self):
        sources = street.payload(state_with(EVENT))["sources"]
        self.assertEqual(set(sources), {"monthly", "daily", "now", "ahead"})
        for key, url in sources.items():
            with self.subTest(key):
                self.assertTrue(url.startswith("https://"), url)
                self.assertIn("{lat}", url)
                self.assertIn("{lon}", url)
        self.assertIn("parameters=PRECTOTCORR,T2M", sources["monthly"])
        self.assertIn("start=1981&end={year}", sources["monthly"])
        self.assertIn("start={start}&end={end}", sources["daily"])
        self.assertIn("monthly=temperature_2m_anomaly,precipitation_mean,precipitation_anomaly,"
                      "sea_surface_temperature_anomaly", sources["ahead"])
        self.assertIn("forecast_hours=24", sources["now"])

    def test_a_picked_point_is_taken_to_the_nearest_road_on_osrm_s_car_network(self):
        # FOSSGIS's OSRM over OpenStreetMap, as it answered on 9 October 2026:
        # the nearest point on a road a car may take, its name and how far.
        self.assertEqual(street.payload(state_with(EVENT))["roads"],
                         "https://routing.openstreetmap.de/routed-car/nearest/v1/driving/{lon},{lat}?number=1")


class TestStreetOnThePage(_DeskFixtures, unittest.TestCase):
    """The desk's page, written as the map or the desk, carries the street."""

    def page(self, focus="world") -> str:
        state = self.state(self.polo())
        state.assessment = SimpleNamespace(index_name="RONI", index_series=list(EVENT))
        state.run_at = "2026-09-29T12:00:00+00:00"
        return stormdesk.page(state, focus=focus)

    def data(self, html: str) -> dict:
        raw = re.search(r'<script id="desk-data" type="application/json">(.*?)</script>', html, re.S).group(1)
        return json.loads(raw)

    def test_both_pages_carry_the_street_payload(self):
        state = SimpleNamespace(assessment=SimpleNamespace(index_name="RONI", index_series=list(EVENT)))
        for focus in ("world", "storms"):
            with self.subTest(focus):
                self.assertEqual(self.data(self.page(focus))["street"], street.payload(state))

    def test_both_pages_carry_the_card_s_rules(self):
        for focus in ("world", "storms"):
            with self.subTest(focus):
                self.assertIn(street.css(), self.page(focus))

    def test_here_opens_on_the_card_and_keeps_an_asked_point_current(self):
        show = _js_function(stormdesk.script(), "showHere")
        card = show.index('html.push(\'<div class="streetcard" id="street-card">\' + '
                          'streetCardHtml(streetState(S.here.lon, S.here.lat)) + "</div>");')
        self.assertLess(show.index('data-here="clear">Clear</button>'), card)
        self.assertLess(card, show.index('html.push("<h4>Live storms</h4>");'))
        self.assertIn("if (streetAsked(S.here.lon, S.here.lat)) streetCard(S.here.lon, S.here.lat, true);", show)

    def test_here_offers_street_view_of_the_point_it_shows(self):
        js = stormdesk.script()
        show = _js_function(js, "showHere")
        buttons = ('<div class="herebtns"><button type="button" class="toolbtn" data-here="show">Show on map</button>'
                   '<button type="button" class="toolbtn" data-here="street">Street View here</button>'
                   '<button type="button" class="toolbtn" data-here="then">Then and now here</button>'
                   '<button type="button" class="toolbtn" data-here="clear">Clear</button></div>')
        self.assertIn(buttons, show.replace("' +\n              '", ""))
        self.assertNotIn("Enter here", js)
        self.assertIn('else if (h && what === "street") streetPick(h.lon, h.lat, S.z, h.label);', js)
        # The street's chip says what Here's card says, each time Here is written.
        self.assertIn("if (S.street) streetChip();", show)


def top_names(js: str) -> set:
    """A script's own names at the top of the page's one scope: its
    functions, and what its var lines declare."""
    return set(re.findall(r"^  function ([A-Za-z_$][\w$]*)", js, re.M)) | {
        name for line in re.findall(r"^  var (.*)$", js, re.M)
        for name in re.findall(r"(?:^|, )([A-Za-z_$][\w$]*) =", line)}


class TestStreetStageMarkup(_DeskFixtures, unittest.TestCase):
    """The stage's parts: on the map, hidden until the figure is let go,
    every control named, nothing of the page over Google's panorama."""

    def page(self, focus="world") -> str:
        state = self.state(self.polo())
        state.assessment = SimpleNamespace(index_name="RONI", index_series=list(EVENT))
        state.run_at = "2026-09-29T12:00:00+00:00"
        return stormdesk.page(state, focus=focus)

    @staticmethod
    def stage(html: str) -> str:
        return re.search(r'<section class="streetstage ui" id="street-stage".*?</section>', html, re.S).group(0)

    def test_the_stage_is_on_the_map_of_both_pages_hidden_until_a_drop(self):
        for focus in ("world", "storms"):
            with self.subTest(focus):
                html = self.page(focus)
                mapped = html[html.index('<div class="deskmap" id="map"'):html.index('<div class="deskscrub">')]
                stage = self.stage(html)
                self.assertIn(stage, mapped)
                self.assertTrue(stage.startswith('<section class="streetstage ui" id="street-stage" '
                                                 'aria-label="Street View" tabindex="-1" hidden>'))
                self.assertEqual(stage, street.map_parts())

    def test_the_bar_names_the_place_and_every_way_on(self):
        stage = street.map_parts()
        self.assertIn('<p class="streetplace" id="street-place" aria-live="polite"></p>', stage)
        for words, ident in (("Then and now", "street-then"), ("Copy link", "street-copy"), ("Exit", "street-exit")):
            self.assertIn(f'<button type="button" class="toolbtn" id="{ident}">{words}</button>', stage)
        self.assertIn('<a class="toolbtn" id="street-gmaps" href="https://www.google.com/maps" target="_blank" '
                      'rel="noopener">Google Maps \u2197</a>', stage)
        self.assertIn('<p class="streetlink" id="street-link" role="status"></p>', stage)
        self.assertIn('<div class="streetpano" id="street-pano"></div>', stage)

    def test_what_google_shows_is_said_before_it_is_met(self):
        self.assertIn('<p class="streetnote">A point picked goes first to the nearest street within reach, and '
                      "Street View opens on Google\u2019s panorama there; where Google has none it says \u201cNo "
                      "Street View available\u201d, and the minimap and the card are this point\u2019s either "
                      "way.</p>", street.map_parts())

    def test_the_nearest_street_is_credited_as_its_operator_and_openstreetmap_ask(self):
        self.assertIn('<p class="streetcredit">Nearest street: <a href="https://project-osrm.org/" target="_blank" '
                      'rel="noopener">OSRM</a> by FOSSGIS over <a href="https://www.openstreetmap.org/copyright" '
                      'target="_blank" rel="noopener">\u00a9 OpenStreetMap contributors</a>; <a '
                      'href="https://www.openstreetmap.org/fixthemap" target="_blank" rel="noopener">fix the '
                      "map</a>.</p>", street.map_parts())

    def test_open_the_stage_takes_the_room_of_the_map_s_scrubber_and_key(self):
        # Both are the hidden map's; the panorama gets their height.
        self.assertIn(".deskmapcol:has(#map.streeton) .deskscrub, .deskmapcol:has(#map.streeton) .desklegend "
                      "{ display: none; }", street.css())

    def test_the_minimap_has_its_own_zoom_and_esri_s_credit_beside_it(self):
        stage = street.map_parts()
        credit = next(layer for layer in worldmap.MAP_LAYERS if layer["id"] == "streets")["credit"]
        self.assertIn('<div class="streetmini" id="street-mini" role="group" aria-label="Minimap: tap a street to '
                      'move Street View there">', stage)
        self.assertIn('<div class="streetminitiles" id="street-mini-tiles" aria-hidden="true"></div>', stage)
        self.assertIn('<span class="streetminipin" aria-hidden="true"></span>', stage)
        self.assertIn('<button type="button" id="street-mini-in" aria-label="Zoom the minimap in">+</button>', stage)
        self.assertIn('<button type="button" id="street-mini-out" aria-label="Zoom the minimap out">&minus;</button>',
                      stage)
        self.assertIn(f'<p class="streetcredit">Minimap: {esc(credit)}</p>', stage)

    def test_the_chip_holds_the_card_s_first_lines_and_goes_to_the_rest(self):
        stage = street.map_parts()
        self.assertIn('<div class="streetchip" id="street-chip"><div class="streetchiphead"><b>El Ni\u00f1o on this '
                      'street</b><button type="button" class="streetmore" id="street-more">The whole card \u2193'
                      "</button></div>", stage)
        self.assertIn('<p class="streetchipsaid" id="street-chip-said"></p>', stage)
        # The panorama is between the bar and the strip under it, so nothing
        # of the page sits on Google's own controls and credit.
        order = [stage.index(s) for s in ('class="streetbar"', 'id="street-pano"', 'class="streetfoot"')]
        self.assertEqual(order, sorted(order))

    def test_the_chip_credits_open_meteo_whose_forecast_it_quotes(self):
        # The chip's sentence gives ECMWF's months as Open-Meteo serves them,
        # and Open-Meteo asks for its credit, linked, wherever its data show.
        stage = street.map_parts()
        chip = stage[stage.index('<div class="streetchip" id="street-chip">'):]
        self.assertIn('<p class="streetcredit">ECMWF\u2019s forecast: <a href="https://open-meteo.com/" target="_blank" '
                      'rel="noopener">Weather data by Open-Meteo.com</a></p>', chip)


class TestStreetScript(unittest.TestCase):
    """The street's script, taken into the page's one scope."""

    def test_no_name_of_the_street_s_script_is_one_of_the_page_s(self):
        mine = top_names(street._JS)
        self.assertIn("streetEnter", mine)
        others = top_names(stormdesk._JS) | top_names(worldmap._JS) | top_names(thennow._JS)
        self.assertEqual(sorted(mine & others), [])

    def test_the_figure_lands_in_the_street_wherever_it_is_let_go(self):
        js = stormdesk.script()
        self.assertIn("if (S.arming) { var w = toWorld(q.x, q.y); arm(false); figureLand(lonOf(w.x), latOf(w.y)); return; }",
                      _js_function(js, "tap"))
        self.assertIn("figureLand(lonOf(w.x), latOf(w.y));", _js_function(js, "carryEnd"))
        self.assertNotIn("thenEnter(lonOf", js)

    def test_the_page_s_other_controls_leave_the_street_first(self):
        js = stormdesk.script()
        for name in ("setLayer", "setCompare", "flyTo", "setEnso", "showRegion"):
            self.assertEqual(_js_function(js, name).split("\n")[1:3],
                             ["    if (S.then) thenLeave();", "    if (S.street) streetLeave();"], name)
        self.assertIn("if (S.then) thenLeave();\n    if (S.street) streetLeave();\n    closeList();", _js_function(js, "go"))
        self.assertIn("if (S.then) thenLeave();\n    if (S.street) streetLeave();\n    // An address followed",
                      _js_function(js, "applyHash"))
        for control in ('$("swap").addEventListener("click", function () {',
                        '$("compare-layer").addEventListener("change", function (e) {'):
            self.assertIn(control + "\n    if (S.then) thenLeave();\n    if (S.street) streetLeave();", js)
        self.assertIn("function clearHere() { if (S.street) streetLeave(); S.here = null;", js)

    def test_a_point_the_reader_picks_goes_to_its_street_and_an_address_is_where_it_says(self):
        js = stormdesk.script()
        self.assertIn("function figureLand(lon, lat) { return streetPick(lon, lat, S.z); }", js)
        self.assertIn("streetPick(p.lon, p.lat, S.street.mini);", js)
        self.assertIn("return T ? streetPick(T.lon, T.lat, S.z, T.label) : false;", _js_function(js, "thenStreet"))
        # An address, the page's API and a street kept across a load are exact.
        self.assertIn("return h ? streetEnter(h.lon, h.lat) : false;", _js_function(js, "streetHashApply"))
        self.assertIn("street: function (lon, lat) { return streetEnter(lon, lat); },", js)
        self.assertIn("if (point(s)) streetEnter(s.lon, s.lat,", _js_function(js, "restorePlace"))

    def test_the_page_s_api_drives_the_street(self):
        js = stormdesk.script()
        self.assertIn("street: function (lon, lat) { return streetEnter(lon, lat); },", js)
        self.assertIn("leaveStreet: function () { return streetLeave(); },", js)
        self.assertIn("then: thenView(), street: streetView()};", js)

    def test_the_loop_stopped_behind_the_stage_is_handed_across_as_the_map_s(self):
        # Kept across a load, the loop is the map's: the one the street
        # stopped, and handed back to it if the street is entered again.
        js = stormdesk.script()
        self.assertIn("loop: T ? T.back.loop : S.street ? S.street.back.loop : S.loop,", _js_function(js, "keepPlace"))
        self.assertIn("if (S.then) S.then.back.loop = true;\n      else if (S.street) S.street.back.loop = true;\n"
                      "      else S.loopWanted = true;", _js_function(js, "restorePlace"))


# Lima, entered as an address enters it.
LIMA = 'streetEnter(-77.0428, -12.0464, "Lima");\n'

# OSRM's answer for a point in Lima where Google's embed had no panorama, as
# FOSSGIS's server answered on 9 October 2026 (its hint and nodes left out).
ROAD_LIMA = {"code": "Ok", "waypoints": [{"location": [-77.050231, -12.045687], "name": "Avenida Guillermo Dansey",
                                          "distance": 59.23305783}]}
CARD_ASKED = ["https://api.open-meteo.com/v1/forecast", "https://power.larc.nasa.gov/api/temporal/daily/point",
              "https://power.larc.nasa.gov/api/temporal/monthly/point",
              "https://seasonal-api.open-meteo.com/v1/seasonal"]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestStreetStageRuns(unittest.TestCase):
    """Into the street and out again, under node with the page's DOM faked as
    then-and-now's tests fake it: Here and the stage, the map on the way out,
    then and now beside it, the minimap, the address, the link and Esc."""

    def test_entering_moves_here_to_the_point_shows_the_stage_and_asks_the_card(self):
        got = _run(self, r"""
          $("then-enter").fire("click");
          """ + LIMA + r"""
          console.log(JSON.stringify({street: S.street && [S.street.lon, S.street.lat, S.street.label, S.street.mini],
            here: S.here, hidden: $("street-stage").hidden, on: map.classList.contains("streeton"), arming: S.arming,
            place: $("street-place").textContent, gmaps: $("street-gmaps").getAttribute("href"),
            frame: $("street-pano").innerHTML, asked: ASKED.map(function (u) { return u.split("?")[0]; }).sort(),
            here_calls: CALLS.filter(function (c) { return c.indexOf("hereAt") === 0; })}));
        """)
        self.assertEqual(got["street"], [-77.0428, -12.0464, "Lima", 15])
        self.assertEqual(got["here"], {"lon": -77.0428, "lat": -12.0464, "label": "Lima"})
        self.assertEqual([got["hidden"], got["on"], got["arming"], got["place"]], [False, True, False, "Lima"])
        self.assertEqual(got["gmaps"], "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=-12.046400,-77.042800")
        self.assertEqual(got["frame"], '<iframe class="streetframe" title="Google Street View of Lima" '
                         'src="https://maps.google.com/maps?layer=c&amp;cbll=-12.046400,-77.042800&amp;cbp=12,0,0,0,0'
                         '&amp;output=svembed" allowfullscreen referrerpolicy="no-referrer-when-downgrade"></iframe>')
        # The drop is the reader asking: the card's four sources are asked.
        self.assertEqual(got["asked"], ["https://api.open-meteo.com/v1/forecast",
                                        "https://power.larc.nasa.gov/api/temporal/daily/point",
                                        "https://power.larc.nasa.gov/api/temporal/monthly/point",
                                        "https://seasonal-api.open-meteo.com/v1/seasonal"])
        self.assertEqual(got["here_calls"], ["hereAt Lima"])

    def test_a_picked_point_waits_for_its_street_then_takes_it_and_its_name(self):
        got = _run(self, r"""
          route("routed-car/nearest", """ + json.dumps(ROAD_LIMA) + r""");
          S.z = 15;
          streetPick(-77.050283, -12.045154, S.z);
          var finding = {at: [S.street.lon, S.street.lat, S.street.label], hidden: $("street-stage").hidden,
                         pano: $("street-pano").innerHTML, chip: $("street-chip-said").innerHTML, asked: ASKED.slice(),
                         here: CALLS.filter(function (c) { return c.indexOf("hereAt") === 0; })};
          advance(0);
          await flush();
          console.log(JSON.stringify({finding: finding, found: [S.street.lon, S.street.lat, S.street.label],
            here: S.here, frame: $("street-pano").innerHTML.indexOf("cbll=-12.045687,-77.050231") > 0,
            first: ASKED[0], card: ASKED.slice(1).map(function (u) { return u.split("?")[0]; }).sort()}));
        """)
        finding = got["finding"]
        # At once: the stage on the point, Google's frame and the card held back.
        self.assertEqual(finding["at"], [-77.050283, -12.045154, "12.05S 77.05W"])
        self.assertFalse(finding["hidden"])
        self.assertEqual(finding["pano"], '<p class="streetfinding">Finding the nearest street\u2026</p>')
        self.assertEqual(finding["chip"], "Finding the nearest street\u2026")
        self.assertEqual([finding["asked"], finding["here"]], [[], []])
        # Then the street, named; Here, Google's frame and the card are its.
        label = "Avenida Guillermo Dansey, 12.05S 77.05W"
        self.assertEqual(got["found"], [-77.050231, -12.045687, label])
        self.assertEqual(got["here"], {"lon": -77.050231, "lat": -12.045687, "label": label})
        self.assertTrue(got["frame"])
        self.assertEqual(got["first"],
                         "https://routing.openstreetmap.de/routed-car/nearest/v1/driving/-77.050283,-12.045154?number=1")
        self.assertEqual(got["card"], CARD_ASKED)

    def test_a_street_is_within_reach_of_24_pixels_of_the_view_from_250_m_to_5_km(self):
        got = _run(self, r"""
          console.log(JSON.stringify([[16, 0], [12, -12.05], [3, 0], [15, 60], [13, 0]].map(function (p) {
            return snapReach(p[0], p[1]);
          })));
        """)
        for (z, lat), reach in zip(((16, 0), (12, -12.05), (3, 0), (15, 60), (13, 0)), got):
            with self.subTest(z=z, lat=lat):
                metres = 24 * 40075017 * math.cos(math.radians(lat)) / (256 * 2 ** z)
                self.assertAlmostEqual(reach, max(250, min(5000, metres)), places=6)
        self.assertAlmostEqual(got[1], 897.0, delta=0.5)
        self.assertAlmostEqual(got[4], 458.6, delta=0.5)

    def test_a_road_out_of_reach_or_no_answer_leaves_the_point_where_it_was_picked(self):
        def road(distance, name="Avenida Guillermo Dansey", location=(-77.050231, -12.045687)):
            return {"code": "Ok", "waypoints": [{"location": list(location), "name": name, "distance": distance}]}
        cases = [("out of reach at a street's zoom", 16, road(400)), ("within a city's view", 12, road(400)),
                 ("past 5 km at the world's", 3, road(6000)), ("a failure", 16, "error"), ("an error status", 16, 503),
                 ("no road", 16, {"code": "NoSegment", "message": "Could not find a matching segment"}),
                 ("a strange answer", 16, {"code": "Ok", "waypoints": [{"location": ["a", None], "distance": 5}]}),
                 ("no answer", 16, "hang"), ("an unnamed road", 16, road(5, name=""))]
        got = _run(self, r"""
          var out = [];
          async function pick(z, answer) {
            ROUTES = []; route("routed-car/nearest", answer === "error" ? new TypeError("Failed to fetch") : answer);
            streetPick(-77.050283, -12.045154, z);
            advance(1000); await flush();
            advance(2500); await flush();
            return [S.street.lon, S.street.lat, S.street.label, S.street.finding,
                    $("street-pano").innerHTML.indexOf("cbll=" + S.street.lat.toFixed(6) + "," + S.street.lon.toFixed(6)) > 0];
          }
          var cases = """ + json.dumps([[z, answer] for _, z, answer in cases]) + r""";
          for (var i = 0; i < cases.length; i++) out.push(await pick(cases[i][0], cases[i][1]));
          console.log(JSON.stringify(out));
        """)
        stayed = [-77.050283, -12.045154, "12.05S 77.05W", False, True]
        went = [-77.050231, -12.045687, "Avenida Guillermo Dansey, 12.05S 77.05W", False, True]
        expected = [stayed, went, stayed, stayed, stayed, stayed, stayed, stayed,
                    [-77.050231, -12.045687, "12.05S 77.05W", False, True]]
        for (name, _, _), result, want in zip(cases, got, expected):
            with self.subTest(name):
                self.assertEqual(result, want)

    def test_a_newer_pick_or_leaving_drops_an_older_answer_and_osrm_is_asked_once_a_second(self):
        got = _run(self, r"""
          route("routed-car/nearest", function (url) {
            var p = url.split("driving/")[1].split("?")[0].split(",").map(Number);
            return {code: "Ok", waypoints: [{location: [Math.round((p[0] + 0.001) * 1e6) / 1e6, p[1]],
                                             name: "Road at " + p[0].toFixed(3), distance: 100}]};
          });
          function roads() { return ASKED.filter(function (u) { return u.indexOf("routed-car") >= 0; }).length; }
          function at() { return [S.street.lon, S.street.lat, S.street.label, S.street.finding]; }
          streetPick(-77.0, -12.0, 15);
          advance(0);
          streetPick(-77.1, -12.1, 15);
          await flush();
          var a = [at(), roads()];
          advance(999); await flush();
          var held = roads();
          advance(1); await flush();
          var b = [at(), roads()];
          streetPick(-77.2, -12.2, 15);
          streetLeave();
          advance(5000); await flush();
          var left = [S.street, roads()];
          streetPick(-77.3, -12.3, 15);
          streetEnter(-77.4, -12.4, "Exact");
          advance(5000); await flush();
          console.log(JSON.stringify([a, held, b, left, [at(), roads()]]));
        """)
        a, held, b, left, exact = got
        # The first answer came for a pick replaced since: dropped, and the
        # second pick waits out the second before it is asked.
        self.assertEqual(a, [[-77.1, -12.1, "12.10S 77.10W", True], 1])
        self.assertEqual(held, 1)
        self.assertEqual(b, [[-77.099, -12.1, "Road at -77.100, 12.10S 77.10W", False], 2])
        # Left before its question went, a pick asks nothing...
        self.assertEqual(left, [None, 2])
        # ...and one an address replaced asks nothing and moves nothing.
        self.assertEqual(exact, [[-77.4, -12.4, "Exact", False], 2])

    def test_the_figure_picks_and_an_address_opens_where_it_says(self):
        got = _run(self, r"""
          figureLand(-77.050283, -12.045154);
          var picked = [S.street.finding, $("street-pano").innerHTML.indexOf("streetfinding") > 0];
          streetHashApply("#street=-12.04640,-77.04280");
          var linked = [S.street.finding, $("street-pano").innerHTML.indexOf("<iframe") === 0];
          console.log(JSON.stringify([picked, linked]));
        """)
        self.assertEqual(got, [[True, True], [False, True]])

    def test_a_point_entered_again_keeps_google_s_frame_and_another_loads_it(self):
        got = _run(self, LIMA + r"""
          var frame = $("street-pano"), writes = 0, html = frame.innerHTML;
          Object.defineProperty(frame, "innerHTML", {get: function () { return html; },
                                                     set: function (v) { writes++; html = v; }});
          streetEnter(-77.0428, -12.0464, "Lima");
          var same = writes;
          streetEnter(-77.0300, -12.0464, "Lima, east");
          console.log(JSON.stringify([same, writes, html.indexOf("cbll=-12.046400,-77.030000") > 0]));
        """)
        self.assertEqual(got, [0, 1, True])

    def test_leaving_puts_the_map_on_the_point_and_takes_google_s_frame_away(self):
        got = _run(self, r"""
          S.x = 0.5; S.y = 0.5; S.z = 3;
          """ + LIMA + r"""
          CALLS = [];
          var out = streetLeave(), again = streetLeave();
          console.log(JSON.stringify([out, again, S.street, $("street-stage").hidden, map.classList.contains("streeton"),
                                      $("street-pano").innerHTML,
                                      [lonOf(S.x), latOf(S.y), S.z].map(function (v) { return Math.round(v * 1e6) / 1e6; }),
                                      CALLS.indexOf("settle") >= 0]));
        """)
        self.assertEqual(got, [True, False, None, True, False, "", [-77.0428, -12.0464, 16], True])

    def test_leaving_goes_no_deeper_than_the_map_s_layer(self):
        got = _run(self, r"""
          S.layer = "infrared"; S.z = 3;
          """ + LIMA + r"""
          streetLeave();
          console.log(JSON.stringify(S.z));
        """)
        # NASA's imagery stops at the map's own deepest zoom.
        self.assertEqual(got, 13)

    def test_then_and_now_and_the_street_are_one_place_s_two_views(self):
        got = _run(self, MODIS_DAYS + MANAUS + r"""
          await flush();
          $("then-street").fire("click");
          var street = [S.then, S.street && S.street.label, S.street && [S.street.lon, S.street.lat]];
          $("street-then").fire("click");
          var back = [S.street, S.then && S.then.source, S.then && S.then.want, S.then && S.then.label];
          streetEnter(-60.025, -3.1, "Manaus");
          var left = [S.then, !!S.street];
          thenEnter(-60.025, -3.1, "Manaus");
          console.log(JSON.stringify([street, back, left, S.street]));
        """)
        # Coming back, then and now is on the source and the dates last used.
        self.assertEqual(got, [[None, "Manaus", [-60.025, -3.1]],
                               [None, "modis", {"a": "2014-11-15", "b": "2015-11-15"}, "Manaus"],
                               [None, True], None])

    def test_then_and_now_from_the_street_first_time_is_then_and_now_s_own(self):
        got = _run(self, LIMA + r"""
          $("street-then").fire("click");
          console.log(JSON.stringify([S.street, S.then && S.then.label, S.then && S.then.preset]));
        """)
        self.assertEqual(got, [None, "Lima", "now"])

    def test_the_minimap_s_tiles_cover_its_box_round_the_world(self):
        got = _run(self, r"""
          function covers(tiles, w, h) {
            for (var y = 0; y < h; y += 5) for (var x = 0; x < w; x += 5) {
              if (!tiles.some(function (t) { return x >= t.left && x < t.left + TILE && y >= t.top && y < t.top + TILE; })) return [x, y];
            }
            return true;
          }
          var lima = miniTiles(-77.0428, -12.0464, 15, 220, 165);
          var dateline = miniTiles(179.99, 0, 2, 600, 100);
          var pole = miniTiles(0, 84.9, 1, 300, 600);
          console.log(JSON.stringify([covers(lima, 220, 165), lima, covers(dateline, 600, 100),
                                      dateline.map(function (t) { return [t.x, t.y]; }),
                                      pole.map(function (t) { return [t.y, t.top]; })]));
        """)
        self.assertEqual(got[0], True)
        self.assertEqual(got[1], [
            {"x": 9370, "y": 17488, "z": 15, "left": -247, "top": -86, "url": "https://streets/15/17488/9370"},
            {"x": 9371, "y": 17488, "z": 15, "left": 9, "top": -86, "url": "https://streets/15/17488/9371"}])
        # Across the date line the columns go round the world...
        self.assertEqual(got[2], True)
        self.assertEqual(got[3], [[2, 1], [3, 1], [0, 1], [1, 1], [2, 2], [3, 2], [0, 2], [1, 2]])
        # ...and past the top of the map there is none.
        self.assertEqual(got[4], [[0, 298], [0, 298], [1, 554], [1, 554]])

    def test_a_tap_on_the_minimap_moves_the_street_and_its_zoom_is_its_own(self):
        got = _run(self, r"""
          var mini = $("street-mini");
          mini.box = {left: 30, top: 400, width: 220, height: 165};
          """ + LIMA + r"""
          var middle = miniPoint(110, 82.5);
          // A tile's width east of the middle, at zoom 15, is 360 / 2^15 degrees on.
          mini.fire("click", {clientX: 30 + 110 + 256, clientY: 400 + 82.5});
          advance(0);
          await flush();
          var moved = [S.street.lon, S.street.lat, S.street.label, S.street.mini, S.here.label];
          for (var i = 0; i < 4; i++) $("street-mini-in").fire("click");
          var deep = [S.street.mini, $("street-mini-in").disabled, $("street-mini-out").disabled];
          for (i = 0; i < 20; i++) $("street-mini-out").fire("click");
          var shallow = [S.street.mini, $("street-mini-in").disabled, $("street-mini-out").disabled];
          console.log(JSON.stringify([middle, moved, deep, shallow, $("street-mini-tiles").innerHTML.split("<img").length - 1]));
        """)
        middle, moved, deep, shallow, images = got
        self.assertAlmostEqual(middle["lon"], -77.0428, places=9)
        self.assertAlmostEqual(middle["lat"], -12.0464, places=9)
        self.assertAlmostEqual(moved[0], -77.0428 + 360 / 2 ** 15, places=9)
        self.assertAlmostEqual(moved[1], -12.0464, places=9)
        self.assertEqual(moved[2:], ["12.05S 77.03W", 15, "12.05S 77.03W"])
        self.assertEqual(deep, [18, True, False])
        self.assertEqual(shallow, [3, False, True])
        self.assertGreater(images, 0)

    def test_the_street_s_address_opens_it_and_a_malformed_one_is_refused(self):
        got = _run(self, r"""
          var ok = ["#street=-12.0464,-77.0428", "#street=-12.0464,282.9572", "#street=85.5,0"].map(parseStreet);
          var bad = ["#street=", "#street=91,0", "#street=0,361", "#street=a,b", "#street=1,2,3", "#street=-12.0464",
                     "#street=1e3,2", "#then=-3.1,-60.0,8.00,modis,2014-11-15,2015-11-15", "", null].map(parseStreet);
          var opened = streetHashApply("#street=-12.0464,-77.0428");
          var refused = streetHashApply("#street=nowhere");
          console.log(JSON.stringify([ok, bad, opened, refused, S.street && [S.street.lon, S.street.lat, S.street.label]]));
        """)
        ok, bad, opened, refused, where = got
        self.assertEqual(ok[0], {"lat": -12.0464, "lon": -77.0428})
        self.assertAlmostEqual(ok[1]["lon"], -77.0428, places=9)
        self.assertEqual(ok[2], {"lat": 85.5, "lon": 0})
        self.assertEqual(bad, [None] * 10)
        self.assertEqual([opened, refused, where], [True, False, [-77.0428, -12.0464, "12.05S 77.04W"]])

    def test_the_page_s_address_opens_the_street_and_any_other_leaves_it(self):
        js = stormdesk.script()
        extra = "\n".join(_js_function(js, n) for n in ("parseHash", "applyHash")) + r"""
var BYID = {}, scrub = {max: "120"};
function own(table, key) { return typeof key === "string" && Object.prototype.hasOwnProperty.call(table, key); }
function setPlay() {}
function select() {}
function setScrub() {}
"""
        got = _run(self, r"""
          S.playing = false;
          var opened = applyHash("#street=-12.0464,-77.0428");
          var street = S.street && S.street.label;
          var viewed = applyHash("#view=10.0000,20.0000,5.00");
          console.log(JSON.stringify([opened, street, viewed, S.street, [latOf(S.y), lonOf(S.x), S.z].map(Math.round)]));
        """, extra=extra)
        self.assertEqual(got, [True, "12.05S 77.04W", True, None, [10, 20, 5]])

    def test_copy_link_writes_the_street_s_address(self):
        got = _run(self, LIMA + r"""
          $("street-copy").fire("click");
          var shown = $("street-link").textContent;
          await flush();
          console.log(JSON.stringify([shown, COPIED, $("street-link").textContent]));
        """)
        url = "file:///C:/elnino/output/map.html#street=-12.04640,-77.04280"
        self.assertEqual(got, ["Copy this link: " + url, [url], "Link copied: " + url])

    def test_leaving_lets_go_of_the_address_the_street_was_opened_from(self):
        got = _run(self, r"""
          location.hash = "#street=-12.04640,-77.04280"; location.href = "file:///C:/elnino/output/map.html" + location.hash;
          streetHashApply(location.hash);
          streetLeave();
          console.log(JSON.stringify([location.href, CALLS.filter(function (c) { return /^replaceState/.test(c); })]));
        """)
        self.assertEqual(got, ["file:///C:/elnino/output/map.html",
                               ["replaceState file:///C:/elnino/output/map.html"]])

    def test_esc_leaves_the_street_and_keys_typed_in_a_field_are_their_own(self):
        got = _run(self, LIMA + r"""
          var typed = press("Escape", new El("q", "input"));
          var stayed = [!!S.street, typed.defaultPrevented];
          var out = press("Escape");
          var again = press("Escape");
          console.log(JSON.stringify([stayed, out.defaultPrevented, S.street, again.defaultPrevented]));
        """)
        self.assertEqual(got, [[True, False], True, None, False])

    def test_the_exit_button_leaves_the_street(self):
        got = _run(self, LIMA + r"""
          $("street-exit").fire("click");
          console.log(JSON.stringify([S.street, $("street-stage").hidden]));
        """)
        self.assertEqual(got, [None, True])

    def test_the_figure_picked_up_in_the_street_shows_the_map_to_drop_it_on(self):
        got = _run(self, SCREEN + LIMA + r"""
          $("then-enter").fire("click");
          var pressed = [S.street, S.arming];
          arm(false);
          """ + LIMA + r"""
          var fig = $("then-enter");
          fig.fire("pointerdown", {pointerId: 2, pointerType: "touch", clientX: 20, clientY: 20});
          var down = !!S.street;
          fig.fire("pointermove", {pointerId: 2, clientX: 200, clientY: 200});
          console.log(JSON.stringify([pressed, down, S.street, $("then-ghost").hidden]));
        """)
        # Pressed, the map waits for a tap; carried, the map is under it.
        self.assertEqual(got, [[None, True], True, None, False])

    def test_the_chip_says_what_the_card_says_as_each_source_answers(self):
        got = _run(self, r"""
          route("v1/seasonal", """ + json.dumps(AHEAD_LIMA) + r""");
          route("v1/forecast", """ + json.dumps(NOW_LIMA) + r""");
          route("power.larc.nasa.gov", 500);
          """ + LIMA + r"""
          var asking = $("street-chip-said").innerHTML;
          await flush();
          var said = $("street-chip-said").innerHTML;
          console.log(JSON.stringify([asking, said, said === streetSentence(streetState(-77.0428, -12.0464))]));
        """)
        asking, said, same = got
        self.assertIn("Reading NASA POWER\u2019s record of this place\u2026", asking)
        self.assertIn("Asking Open-Meteo for ECMWF\u2019s forecast\u2026", asking)
        self.assertIn("NASA POWER\u2019s record of this place could not be read (answered 500)", said)
        self.assertIn("ECMWF expects", said)
        self.assertTrue(same)

    def test_the_whole_card_is_here_s_and_here_comes_back_to_the_street_for_it(self):
        got = _run(self, LIMA + r"""
          CALLS = [];
          $("street-more").fire("click");
          var first = CALLS.slice();
          S.here = {lon: 10, lat: 10, label: "elsewhere"}; CALLS = [];
          $("street-more").fire("click");
          console.log(JSON.stringify([first, CALLS]));
        """)
        self.assertEqual(got, [["scroll street-card"], ["hereAt Lima", "scroll street-card"]])

    def test_the_page_s_api_says_where_the_street_is(self):
        got = _run(self, r"""
          var none = streetView();
          """ + LIMA + r"""
          console.log(JSON.stringify([none, streetView()]));
        """)
        self.assertEqual(got, [None, {"lon": -77.0428, "lat": -12.0464, "label": "Lima", "mini": 15}])

    def test_a_control_of_the_map_leaves_the_street_for_the_map(self):
        extra = _js_function(stormdesk.script(), "setLayer")
        got = _run(self, LIMA + r"""
          var ok = setLayer("satellite");
          console.log(JSON.stringify([ok, S.street, S.layer, $("street-stage").hidden]));
        """, extra=extra)
        self.assertEqual(got, [True, None, "satellite", True])

    def test_a_run_taken_in_place_keeps_the_stage_and_google_s_frame(self):
        js = stormdesk.script()
        names = ("refresh", "siteCopy", "newer", "takeRun", "withAssets")
        extra = "\n".join(_js_function(js, name) for name in names) + r"""
function prepare() { note("prepare"); }
function select() {}
function showHere() { note("showHere"); }
function ages() {}
function tab() {}
function ensoControls() {}
function render() {}
var geoDirty = false;
var ensoSaid = "", coastDone = 1, coastD = "M0", coastG = {innerHTML: ""}, STORMS = [], BYID = {}, NEXT = null;
var ELNINO = {places: [], coast: {lines: []}, grids: {}};
function DOMParser() {}
DOMParser.prototype.parseFromString = function () {
  return {getElementById: function (id) { return id === "desk-data" ? {textContent: JSON.stringify(NEXT)} : null; }};
};
var elninoLive = {shows: function () { note("shows"); }, sameCode: function () { return true; },
                  hold: function () { return function () {}; }};
"""
        got = _run(self, LIMA + r"""
          await flush();
          var asked = ASKED.length, frame = $("street-pano").innerHTML;
          D.built = "2026-09-29T11:00:00Z";
          NEXT = JSON.parse(JSON.stringify(D)); NEXT.built = "2026-09-29T12:00:00Z";
          route("map.html", "<html></html>");
          refresh(); await flush();
          console.log(JSON.stringify([S.street && S.street.label, $("street-stage").hidden,
                                      $("street-pano").innerHTML === frame, ASKED.length - asked,
                                      CALLS.indexOf("showHere") >= 0]));
        """, extra=extra)
        self.assertEqual(got, ["Lima", False, True, 1, True])

    def test_asking_again_lets_go_of_the_point_s_answers_and_asks_each_source(self):
        got = _run(self, r"""
          route("v1/seasonal", """ + json.dumps(AHEAD_LIMA) + r""");
          route("v1/forecast", """ + json.dumps(NOW_LIMA) + r""");
          route("power.larc.nasa.gov", 500);
          """ + LIMA + r"""
          await flush();
          var asked = ASKED.length, kept = Object.keys(STREET_KEPT).sort();
          var again = new El("again");
          again.setAttribute("data-street", "again");
          again.closest = function () { return again; };
          DOC.click.forEach(function (f) { f({target: again}); });
          var during = [Object.keys(STREET_KEPT).length, Object.keys(STREET_ASKED).length, Object.keys(STREET_WHY).length];
          await flush();
          console.log(JSON.stringify([kept, during, ASKED.slice(asked).map(function (u) { return u.split("?")[0]; }).sort(),
                                      Object.keys(STREET_KEPT).sort()]));
        """)
        kept = ["ahead|-12.05,-77.04", "now|-12.05,-77.04"]
        self.assertEqual(got, [kept, [0, 4, 0], CARD_ASKED, kept])

    def test_the_loop_and_play_stop_behind_the_stage_and_come_back_on_exit(self):
        # Both run over the map, which the stage hides: entering stops them,
        # moving within the street keeps them stopped, Exit runs again what
        # ran - the loop over the frames in view where the map is put.
        extra = ("\n".join(_js_function(stormdesk.script(), name)
                           for name in ("setLoop", "loopLength", "timed", "framesOf"))
                 + "\nvar loopTimer = 0;\nfunction tick() {}\n"
                 + 'function setPlay(on) { note("setPlay " + on); S.playing = !!on; return S.playing; }\n')
        got = _run(self, r"""
          LAYERS.loopy = {id: "loopy", kind: "imagery", name: "Loopy", global: "LOOPY", tms: "GoogleMapsCompatible_Level6",
                          zoom: 6, format: "png", step: "PT10M"};
          DOM.LOOPY = {frames: [{t: 1, key: "k1"}, {t: 2, key: "k2"}, {t: 3, key: "k3"}]};
          S.layer = "loopy"; S.inView = cells("loopy", 0).used; S.playing = false;
          var before = setLoop(true);
          """ + LIMA + r"""
          var inside = [S.loop, !!S.loopWanted];
          streetEnter(-77.05, -12.05, "Lima again");
          var moved = S.loop;
          streetLeave();
          var out = [S.loop, S.frame];
          setLoop(false); setPlay(true); CALLS = [];
          """ + LIMA + r"""
          var playing = S.playing;
          streetLeave();
          var played = [S.playing, S.loop, CALLS.filter(function (c) { return /^setPlay/.test(c); })];
          setPlay(false); S.loopWanted = true;
          """ + LIMA + r"""
          var waiting = !!S.loopWanted;
          streetLeave();
          console.log(JSON.stringify([before, inside, moved, out, playing, played, waiting, [S.loop, !!S.loopWanted]]));
        """, extra=extra)
        self.assertEqual(got, [True, [False, False], False, [True, 2], False,
                               [True, False, ["setPlay false", "setPlay true"]], False, [True, False]])

    def test_loop_pressed_in_the_street_leaves_it_and_runs_on_the_map(self):
        # The loop runs on the map; pressed while the stage hides the map, it
        # leaves the street for it, as the map's other controls do.
        line = next(text for text in stormdesk.script().splitlines()
                    if text.lstrip().startswith('$("loop").addEventListener("click",'))
        got = _run(self, LIMA + r"""
          CALLS = [];
          $("loop").fire("click");
          console.log(JSON.stringify([S.street, S.loop, CALLS.filter(function (c) { return c.indexOf("setLoop") === 0; })]));
        """, extra=line)
        self.assertEqual(got, [None, True, ["setLoop true"]])

    def test_a_pick_takes_the_focus_to_the_stage_and_leaving_gives_it_to_the_map(self):
        # The stage covers the map: keys pressed after a pick go to the
        # street, not to the map under it. An address, the page's API and a
        # street kept across a load leave the focus where it is.
        self.assertIn('<section class="streetstage ui" id="street-stage" aria-label="Street View" tabindex="-1" hidden>',
                      street.map_parts())
        got = _run(self, r"""
          El.prototype.focus = function () { document.activeElement = this; note("focus " + this.id); };
          var stage = $("street-stage");
          stage.contains = function (el) { return el === stage; };
          streetPick(-77.0428, -12.0464, 15, "Lima");
          var picked = document.activeElement && document.activeElement.id;
          CALLS = [];
          streetPick(-77.05, -12.05, 15);
          var moved = CALLS.filter(function (c) { return /^focus/.test(c); });
          streetLeave();
          var left = document.activeElement && document.activeElement.id;
          CALLS = [];
          """ + LIMA + r"""
          console.log(JSON.stringify([picked, moved, left, CALLS.filter(function (c) { return /^focus/.test(c); })]));
        """)
        self.assertEqual(got, ["street-stage", [], "map", []])


def power(months: dict, fill=-999.0, daily=False) -> dict:
    """POWER's answer for a point: ``months`` maps "YYYYMM" (or "YYYYMMDD")
    to (rainfall, temperature), None standing for POWER's fill value; a
    monthly answer also carries each year's mean as month 13."""
    p, t = {}, {}
    for key, (rain, temp) in sorted(months.items()):
        p[key] = fill if rain is None else rain
        t[key] = fill if temp is None else temp
    if not daily:
        for year in sorted({key[:4] for key in months}):
            p[year + "13"], t[year + "13"] = 99.0, 99.0
    return {"type": "Feature", "header": {"fill_value": fill, "sources": ["MERRA2"]},
            "properties": {"parameter": {"PRECTOTCORR": p, "T2M": t}}}


def monthly_keys(first: tuple, last: tuple):
    """Every month from ``first`` to ``last``, (year, month) each, in order."""
    year, month = first
    while (year, month) <= last:
        yield year, month
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestStreetRecordRuns(unittest.TestCase):
    """The point's record read from POWER and composited by the atlas's own
    rules, run under node: the page's own functions."""

    NAMES = ("pad2", "streetMean", "streetKey", "streetIndexOf", "powerRead", "powerMonths", "powerFill",
             "indexAt", "ongoingFrom", "phaseAt", "seasonMonths", "seasonOf", "streetYear", "streetLatest",
             "eventLabel")
    HARNESS = r"""
var SEASON_NAMES = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"];
var DAYS_FULL = 25;
var INPUT = JSON.parse(require("fs").readFileSync(0, "utf8"));
var D = {street: INPUT.street};
/*FUNCTIONS*/
console.log(JSON.stringify((function () { /*BODY*/ })()));
"""

    def run_js(self, body: str, street_payload: dict, **extra):
        js = stormdesk.script()
        missing = [name for name in self.NAMES if not _js_function(js, name)]
        self.assertFalse(missing, "the page has no " + ", ".join(missing))
        functions = "\n".join(_js_function(js, name) for name in self.NAMES)
        script = self.HARNESS.replace("/*FUNCTIONS*/", functions).replace("/*BODY*/", body)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "street.js"
            path.write_text(script, encoding="utf-8")
            done = subprocess.run(["node", str(path)], input=json.dumps(dict(street=street_payload, **extra)),
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    @staticmethod
    def payload(first: str, values: list) -> dict:
        out = street.payload(state_with([]))
        out["months"] = {"from": first, "values": values}
        return out

    def test_a_fill_value_is_a_gap_and_the_year_s_mean_is_no_month(self):
        months = {f"{y}{m:02d}": (1.0 + m / 10, 20.0 + m) for y, m in monthly_keys((1981, 1), (1982, 1))}
        months["198102"] = (None, None)
        got = self.run_js("return powerMonths(INPUT.monthly);", self.payload(None, []), monthly=power(months))
        self.assertEqual(got["from"], "1981-01")
        self.assertEqual(len(got["p"]), 13)
        self.assertEqual((got["p"][1], got["t"][1]), (None, None))
        self.assertEqual((got["p"][12], got["t"][12]), (1.1, 21.0))
        self.assertNotIn(99.0, got["p"])

    def test_the_daily_record_fills_whole_months_the_monthly_one_has_not(self):
        months = {f"{y}{m:02d}": (2.0, 15.0) for y, m in monthly_keys((2026, 1), (2026, 10))}
        months["202609"] = months["202610"] = (None, None)
        days = {f"202609{d:02d}": (float(d), 10.0 + d) for d in range(1, 31)}
        days["20260903"] = days["20260917"] = (None, None)
        days.update({f"202610{d:02d}": (5.0, 5.0) for d in range(1, 7)})
        got = self.run_js("return powerFill(powerMonths(INPUT.monthly), INPUT.daily);", self.payload(None, []),
                          monthly=power(months), daily=power(days, daily=True))
        rain = [float(d) for d in range(1, 31) if d not in (3, 17)]
        self.assertAlmostEqual(got["p"][8], sum(rain) / len(rain))
        self.assertAlmostEqual(got["t"][8], sum(10.0 + d for d in range(1, 31) if d not in (3, 17)) / 28)
        # Six days of October are not a month.
        self.assertEqual((got["p"][9], got["t"][9]), (None, None))
        self.assertEqual(got["p"][:8], [2.0] * 8)

    def record(self, first=(1981, 1), last=(2010, 12), index=None):
        """A point whose rainfall and temperature follow the index, plus a
        wobble that differs month to month, and the index itself."""
        keys = list(monthly_keys(first, last))
        index = index or (lambda y, m: [0.2, -0.3, 1.4, 0.1, 1.1, -0.2, 0.4, 2.0, -0.6, 0.0, 1.0, -1.2][(y * 7 + m) % 12])
        values = [index(y, m) for y, m in keys]
        months = {f"{y}{m:02d}": (round(3.0 + 1.5 * v + ((y * 13 + m * 5) % 7) / 10, 2),
                                  round(25.0 + 0.6 * v + ((y * 11 + m * 3) % 5) / 10, 2))
                  for (y, m), v in zip(keys, values)}
        return months, self.payload(f"{first[0]}-{first[1]:02d}", values), dict(zip(keys, values))

    def test_each_season_is_composited_as_the_atlas_tool_composites_a_cell(self):
        # The page's composite at a point is the atlas tool's for a grid of
        # one cell, fed the same months and the same index: the same events,
        # difference, neutral mean, t and t_crit, season by season.
        months, payload, index = self.record()
        tool = composite_tool()
        for var, column in (("p", 0), ("t", 1)):
            stack = {(int(k[:4]), int(k[4:])): [[v[column]]] for k, v in months.items()}
            want = tool.composite(stack, index, 1, 1)
            got = self.run_js("var r = powerMonths(INPUT.monthly);"
                              "return [0, 3, 6, 9].map(function (i) { return seasonOf(r, i); });",
                              payload, monthly=power(months))
            for season, mine in zip(("DJF", "MAM", "JJA", "SON"), got):
                with self.subTest(var=var, season=season):
                    theirs, ours = want[season], mine[var]
                    self.assertEqual(mine["name"], season)
                    self.assertEqual([e["tag"] for e in ours["events"]], theirs["warm_events"])
                    self.assertTrue(ours["usable"])
                    self.assertAlmostEqual(ours["diff"], theirs["diff"][0][0], places=9)
                    self.assertAlmostEqual(ours["t"], theirs["t"][0][0], places=9)
                    self.assertAlmostEqual(ours["base"], theirs["base"][0][0], places=9)
                    self.assertEqual(ours["crit"], theirs["t_crit"])

    def test_december_joins_the_next_djf_and_january_the_ndj_before(self):
        def index(y, m):
            return 1.5 if (y, m) in ((1990, 12), (1995, 1)) else 0.0
        months, payload, _ = self.record(index=index)
        got = self.run_js("var r = powerMonths(INPUT.monthly);"
                          "return [seasonOf(r, 0).p.events, seasonOf(r, 11).p.events];",
                          payload, monthly=power(months))
        self.assertEqual([e["tag"] for e in got[0]], [1991, 1995])
        self.assertEqual([e["tag"] for e in got[1]], [1990, 1994])

    def test_the_el_nino_under_way_is_not_one_of_the_past_ones(self):
        # The index ends on a run at +0.5 or more: those months, El Nino ones
        # included, are what the composite is being read to anticipate.
        def index(y, m):
            if (y, m) >= (2010, 6):
                return [0.5, 0.8, 1.2, 1.6, 1.9, 2.1, 2.2][(y - 2010) * 12 + m - 6]
            return 1.3 if m == 1 and y % 4 == 0 else 0.1
        months, payload, _ = self.record(index=index)
        got = self.run_js("var r = powerMonths(INPUT.monthly);"
                          "return {since: ongoingFrom(), djf: seasonOf(r, 0).p.events.map(function (e) { return e.tag; }),"
                          " son: seasonOf(r, 9).p.events.length, phase: phaseAt(2010, 10, ongoingFrom())};",
                          payload, monthly=power(months))
        self.assertEqual(got["since"], "2010-06")
        self.assertEqual(got["son"], 0)
        self.assertEqual(got["phase"], "skip")
        self.assertEqual(got["djf"], [y for y in range(1981, 2011) if y % 4 == 0])

    def test_a_season_short_of_three_events_says_so_and_gives_no_difference(self):
        def index(y, m):
            return 1.2 if (y, m) in ((1985, 7), (1999, 7)) else 0.0
        months, payload, _ = self.record(index=index)
        got = self.run_js("return seasonOf(powerMonths(INPUT.monthly), 6).p;", payload, monthly=power(months))
        self.assertFalse(got["usable"])
        self.assertEqual([e["tag"] for e in got["events"]], [1985, 1999])
        self.assertIsNone(got["diff"])
        self.assertIsNone(got["percent"])
        self.assertIsNotNone(got["base"])

    def test_a_percentage_of_the_ordinary_rain_needs_the_atlas_s_dry_floor(self):
        # As the atlas's percentOf: the difference as a percentage of the
        # neutral mean, only where that mean is DRY_FLOOR mm a day or more.
        # A tenth of a millimetre or so is not, though it is more than nothing.
        months, payload, _ = self.record()
        dry = {k: (round(v[0] / 25, 4), v[1]) for k, v in months.items()}
        got = self.run_js("return [seasonOf(powerMonths(INPUT.monthly), 0).p, seasonOf(powerMonths(INPUT.dry), 0).p];",
                          payload, monthly=power(months), dry=power(dry))
        wet, desert = got
        self.assertAlmostEqual(wet["percent"], wet["diff"] / wet["base"] * 100)
        self.assertTrue(0.1 <= desert["base"] < atlas.DRY_FLOOR, desert["base"])
        self.assertIsNone(desert["percent"])
        self.assertIsNotNone(desert["diff"])

    def test_this_year_so_far_is_the_last_season_with_every_month_on_record(self):
        months, payload, _ = self.record(last=(2010, 10))
        months["201009"] = (None, 24.0)
        months["201010"] = (None, None)
        got = self.run_js("return streetLatest(powerMonths(INPUT.monthly));", payload, monthly=power(months))
        self.assertEqual((got["season"], got["name"], got["tag"]), (6, "JJA", 2010))
        want = [months[f"2010{m:02d}"] for m in (6, 7, 8)]
        self.assertAlmostEqual(got["p"], sum(v[0] for v in want) / 3)
        self.assertAlmostEqual(got["t"], sum(v[1] for v in want) / 3)

    def test_an_event_is_named_by_the_years_its_season_spans(self):
        got = self.run_js("return [eventLabel(0, 1998), eventLabel(11, 1997), eventLabel(6, 2015), eventLabel(0, 2000)];",
                          self.payload(None, []))
        # As the site names an episode: "the 1997-98 episode".
        self.assertEqual(got, ["1997-98", "1997-98", "2015", "1999-00"])


def text(markup: str) -> str:
    """What a reader reads of some markup."""
    return htmllib.unescape(re.sub(r"<[^>]+>", "", markup))


# ECMWF's months ahead as Open-Meteo answered for Lima and for Jakarta on
# 9 October 2026 (Jakarta's sea surface made up, as at a point offshore), and
# Lima's weather that morning, its hours of rain made up.
_MONTHS_AHEAD = ["2026-10-01", "2026-11-01", "2026-12-01", "2027-01-01", "2027-02-01", "2027-03-01"]
AHEAD_LIMA = {"monthly": {"time": _MONTHS_AHEAD,
                          "temperature_2m_anomaly": [3.7, 4.3, 4.1, 3.7, 3.4, 3.4],
                          "precipitation_mean": [4.7, 12.5, 20.4, 30.6, 20.9, 20.2],
                          "precipitation_anomaly": [3.2, 10.4, 16.0, 21.4, 9.6, 7.7],
                          "sea_surface_temperature_anomaly": [None] * 6}}
AHEAD_JAKARTA = {"monthly": {"time": _MONTHS_AHEAD,
                             "temperature_2m_anomaly": [1.5, 1.8, 1.3, 1.5, 1.5, 1.5],
                             "precipitation_mean": [47.1, 149.9, 292.6, 337.0, 292.2, 307.7],
                             "precipitation_anomaly": [-80.1, -76.0, 40.5, 66.8, 41.3, 49.7],
                             "sea_surface_temperature_anomaly": [0.6, 0.5, 0.4, 0.4, 0.3, 0.3]}}
NOW_LIMA = {"latitude": -12.056238, "longitude": -77.06198, "utc_offset_seconds": -18000,
            "timezone": "America/Lima", "timezone_abbreviation": "GMT-5",
            "current": {"time": "2026-10-09T08:45", "interval": 900, "temperature_2m": 23.4, "precipitation": 0.0,
                        "weather_code": 0, "wind_speed_10m": 11.3, "wind_direction_10m": 155,
                        "wind_gusts_10m": 31.7},
            "hourly": {"time": [f"2026-10-09T{h:02d}:00" for h in range(8, 24)] +
                               [f"2026-10-10T{h:02d}:00" for h in range(0, 8)],
                       "precipitation": [0.0] * 20 + [0.2, 0.5, 0.0, 0.1]}}
# The index's last seasons as the page's then-and-now payload words them.
THEN_ROWS = [["2026-07", "JJA 2026", 1.4, "moderate El Ni\u00f1o conditions, 4 seasons so far"],
             ["2026-08", "JAS 2026", 1.7, "strong El Ni\u00f1o conditions, 4 seasons so far"]]


def wet_rain(y, m, v):
    return round(3.0 + 1.5 * v + ((y * 13 + m * 5) % 7) / 10, 2)


def warm_air(y, m, v):
    return round(25.0 + 0.6 * v + ((y * 11 + m * 3) % 5) / 10, 2)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestStreetCardRuns(unittest.TestCase):
    """The card: its sources asked, kept and failed, and what it says of a
    point, run under node: the page's own functions, at 15Z on 9 October
    2026, when the season ahead is November to January."""

    # The page's own functions the card's call, beside every one street.py
    # defines; and the page's lines declaring what they share.
    SHARED = ("pad2", "esc", "signedText", "wrap")
    VARS = ('var SEASON_NAMES = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"];',
            'var MONTH_WORDS = "January February March April May June July August September October November '
            'December".split(" ");',
            "var DAYS_FULL = 25;",
            'var STREET_KINDS = ["monthly", "daily", "now", "ahead"], STREET_WAIT = 20000, NOW_KEPT = 900000, '
            'RECORD_KEPT = 86400000;',
            'var STREET_KEPT = {}, STREET_ASKED = {}, STREET_WHY = {}, STREET_STORE = "elnino-street-1:", '
            'STREET_POINTS = 20;',
            'var STREET_UNREAD = "What the sources sent for this point could not be read.";',
            'var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];',
            'var COMPASS8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];')
    HARNESS = r"""
/*VARS*/
var INPUT = JSON.parse(require("fs").readFileSync(0, "utf8"));
var D = INPUT.D;
Date.now = function () { return Date.parse(INPUT.at); };
/*FUNCTIONS*/
Promise.resolve().then(function () { /*BODY*/ }).then(function (v) { console.log(JSON.stringify(v)); },
  function (e) { console.error(e && e.stack || String(e)); process.exit(1); });
"""

    def run_js(self, body: str, street_payload: dict | None = None, at="2026-10-09T15:00:00Z", **extra):
        js = stormdesk.script()
        names = re.findall(r"^  function (\w+)\(", street._JS, re.M) + list(self.SHARED)
        twice = [name for name in names if len(re.findall(r"\bfunction %s\(" % name, js)) != 1]
        self.assertFalse(twice, "not defined once in the page: " + ", ".join(twice))
        functions = "\n".join(_js_function(js, name) for name in names)
        script = (self.HARNESS.replace("/*VARS*/", "\n".join(self.VARS))
                  .replace("/*FUNCTIONS*/", functions).replace("/*BODY*/", body))
        d = {"street": street_payload or street.payload(state_with([])), "then": {"seasons": THEN_ROWS}}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "card.js"
            path.write_text(script, encoding="utf-8")
            done = subprocess.run(["node", str(path)], input=json.dumps(dict(D=d, at=at, **extra)),
                                  capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr[-2000:])
        return json.loads(done.stdout)

    @staticmethod
    def state(asked=True, why=None, asking=None) -> dict:
        """What the card has for Lima: nothing yet, unless the body adds it."""
        kinds = ("monthly", "daily", "now", "ahead")
        return {"lon": -77.04, "lat": -12.05, "asked": asked, "got": {k: None for k in kinds},
                "why": {k: (why or {}).get(k, "") for k in kinds},
                "asking": {k: (asking or {}).get(k, False) for k in kinds}}

    @staticmethod
    def record(rain, temp, index=None, first=(1981, 1), last=(2010, 12)):
        """A point's months, rain and temperature each a function of the
        year, the month and the index, and the payload with that index."""
        index = index or (lambda y, m: [0.2, -0.3, 1.4, 0.1, 1.1, -0.2, 0.4, 2.0, -0.6, 0.0, 1.0, -1.2][(y * 7 + m) % 12])
        keys = list(monthly_keys(first, last))
        values = [index(y, m) for y, m in keys]
        months = {f"{y}{m:02d}": (rain(y, m, v), temp(y, m, v)) for (y, m), v in zip(keys, values)}
        return months, TestStreetRecordRuns.payload(f"{first[0]}-{first[1]:02d}", values)

    def test_the_harness_declares_what_the_page_does(self):
        js = stormdesk.script()
        for line in self.VARS:
            with self.subTest(line=line[:40]):
                self.assertIn(line, js)

    # ---- the sources -------------------------------------------------------------

    def test_a_point_is_asked_for_and_kept_to_a_hundredth_of_a_degree(self):
        got = self.run_js('return [streetCacheKey("now", -77.0412, -12.0461), streetCacheKey("now", -77.0444, -12.0549),'
                          ' streetCacheKey("now", -77.0349, -12.0461), streetCacheKey("ahead", 0.004, -0.004),'
                          ' streetCacheKey("ahead", 182.5, 10), streetCacheKey("ahead", 179.996, 10)];')
        self.assertEqual(got, ["now|-12.05,-77.04", "now|-12.05,-77.04", "now|-12.05,-77.03",
                               "ahead|0.00,0.00", "ahead|10.00,-177.50", "ahead|10.00,-180.00"])

    def test_each_source_is_asked_for_the_rounded_point_at_the_reader_s_date(self):
        body = 'return ["monthly", "daily", "now", "ahead"].map(function (k) { return streetUrl(k, -77.0412, -12.0461); });'
        at = dict(lat="-12.05", lon="-77.04")
        got = self.run_js(body)
        self.assertEqual(got, [street.SOURCES["monthly"].format(year=2026, **at),
                               street.SOURCES["daily"].format(start="20260701", end="20261009", **at),
                               street.SOURCES["now"].format(**at), street.SOURCES["ahead"].format(**at)])
        january = self.run_js(body, at="2027-01-15T00:00:00Z")
        self.assertIn("&start=1981&end=2027&", january[0])
        self.assertIn("&start=20261001&end=20270115&", january[1])

    def test_a_source_is_asked_once_and_kept_for_the_session(self):
        got = self.run_js(r"""
var calls = [], store = {};
sessionStorage = {getItem: function (k) { return k in store ? store[k] : null; },
                  setItem: function (k, v) { store[k] = String(v); }};
fetch = function (url) {
  calls.push(url);
  return Promise.resolve({ok: true, status: 200, json: function () { return Promise.resolve(INPUT.reply); }});
};
var a = streetGet("ahead", -77.0412, -12.0461), b = streetGet("ahead", -77.0444, -12.0549);
return Promise.all([a, b]).then(function (both) {
  STREET_KEPT = {};  // the page loaded again: its memory gone, the tab's session kept
  return streetGet("ahead", -77.04, -12.05).then(function (again) {
    return {calls: calls.length, same: both[0] === both[1], again: again.monthly.time.length,
            stored: Object.keys(store), asking: Object.keys(STREET_ASKED).length};
  });
});""", reply=AHEAD_LIMA)
        self.assertEqual(got, {"calls": 1, "same": True, "again": 6, "stored": ["elnino-street-1:ahead|-12.05,-77.04"],
                               "asking": 0})

    def test_the_weather_now_is_asked_again_after_a_quarter_of_an_hour(self):
        got = self.run_js(r"""
var calls = 0;
fetch = function () {
  calls++;
  return Promise.resolve({ok: true, status: 200, json: function () { return Promise.resolve(INPUT.reply); }});
};
STREET_KEPT["now|-12.05,-77.04"] = {at: Date.now() - 14 * 60000, data: {current: {temperature_2m: 1}}};
STREET_KEPT["now|10.00,20.00"] = {at: Date.now() - 16 * 60000, data: {current: {temperature_2m: 2}}};
STREET_KEPT["ahead|10.00,20.00"] = {at: Date.now() - 600 * 60000, data: {monthly: {time: []}}};
return Promise.all([streetGet("now", -77.04, -12.05), streetGet("now", 20, 10), streetGet("ahead", 20, 10)])
  .then(function (got) { return [calls, got[0].current.temperature_2m, got[1].current.temperature_2m, got[2].monthly.time.length]; });
""", reply=NOW_LIMA)
        self.assertEqual(got, [1, 1, 23.4, 0])

    def test_a_source_that_fails_says_why_and_is_not_kept(self):
        got = self.run_js(r"""
STREET_WAIT = 50;
fetch = function (url) {
  if (url.indexOf("https://api.open-meteo.com/") === 0) return Promise.resolve({ok: false, status: 429});
  if (url.indexOf("https://seasonal-api.open-meteo.com/") === 0) return new Promise(function () {});
  if (url.indexOf("/daily/") > 0) return Promise.reject(new TypeError("Failed to fetch"));
  return Promise.resolve({ok: true, status: 200, json: function () { return Promise.resolve({messages: ["none"]}); }});
};
function why(kind) { return streetGet(kind, -77.04, -12.05).then(function () { return "kept"; }, function (e) { return e.why; }); }
return Promise.all(["now", "ahead", "daily", "monthly"].map(why)).then(function (said) {
  return {said: said, kept: Object.keys(STREET_KEPT), why: STREET_WHY, asking: Object.keys(STREET_ASKED)};
});""")
        self.assertEqual(got["said"], ["answered 429", "did not answer within 0.05 s", "could not be reached",
                                       "has nothing for this point"])
        self.assertEqual((got["kept"], got["asking"]), ([], []))
        self.assertEqual(got["why"]["now|-12.05,-77.04"], "answered 429")

    def test_what_the_card_has_for_a_point_is_read_from_what_is_kept(self):
        got = self.run_js(r"""
STREET_KEPT["ahead|-12.05,-77.04"] = {at: Date.now(), data: {monthly: {time: ["2026-10-01"]}}};
STREET_WHY["now|-12.05,-77.04"] = "answered 429";
STREET_ASKED["monthly|-12.05,-77.04"] = new Promise(function () {});
var st = streetState(-77.0412, -12.0461), away = streetState(-77.06, -12.05);
return [st.asked, st.got.ahead.monthly.time, st.why.now, st.asking.monthly, st.got.monthly, away.asked];""")
        self.assertEqual(got, [True, ["2026-10-01"], "answered 429", True, None, False])

    # ---- what each source says ------------------------------------------------------

    def test_the_weather_is_said_in_words(self):
        got = self.run_js("return [0, 2, 3, 45, 53, 63, 65, 71, 82, 95, 99, 42].map(function (c) { return weatherWords(c); });")
        self.assertEqual(got, ["clear sky", "partly cloudy", "overcast", "fog", "drizzle", "rain", "heavy rain",
                               "light snow", "violent showers", "thunderstorm", "thunderstorm with heavy hail",
                               "weather code 42"])

    def test_right_now_is_said_in_words_at_its_local_time(self):
        got = text(self.run_js('var st = INPUT.state; st.got.now = streetTrim("now", INPUT.now); return streetNowHtml(st);',
                               state=self.state(), now=NOW_LIMA))
        self.assertIn("23.4 \u00b0C, clear sky, wind 11 km/h from the SE with gusts of 32 km/h. "
                      "0.8 mm of rain forecast in the next 24 hours.", got)
        self.assertIn("08:45 local time (GMT-5)", got)
        self.assertIn("Weather data by Open-Meteo.com", got)

    def test_the_months_ahead_give_rain_a_day_and_a_percentage_only_from_the_dry_floor_up(self):
        gap = copy.deepcopy(AHEAD_LIMA)
        gap["monthly"]["precipitation_mean"][5] = None
        lima, jakarta, holed = self.run_js("return [seasonalRows(INPUT.lima), seasonalRows(INPUT.jakarta), seasonalRows(INPUT.gap)];",
                                           lima=AHEAD_LIMA, jakarta=AHEAD_JAKARTA, gap=gap)
        october, january, february = lima[0], lima[3], lima[4]
        self.assertEqual((october["month"], october["label"], october["days"], october["t"]), ("2026-10", "Oct 2026", 31, 3.7))
        self.assertAlmostEqual(october["rain"], 4.7 / 31)
        self.assertAlmostEqual(october["anom"], 3.2 / 31)
        self.assertAlmostEqual(october["normal"], 1.5 / 31)
        # A normal of 0.05 mm a day: +213% of it would be arithmetic, not news.
        self.assertIsNone(october["percent"])
        self.assertAlmostEqual(january["percent"], 21.4 / 9.2 * 100)
        self.assertEqual(february["days"], 28)
        self.assertAlmostEqual(jakarta[0]["percent"], -80.1 / 127.2 * 100)
        self.assertEqual([r["sst"] for r in lima], [None] * 6)
        self.assertEqual(jakarta[0]["sst"], 0.6)
        self.assertEqual((holed[5]["rain"], holed[5]["normal"], holed[5]["percent"]), (None, None, None))
        self.assertAlmostEqual(holed[5]["anom"], 7.7 / 31)

    def test_the_season_ahead_is_the_three_months_from_next_month(self):
        got = self.run_js('return [streetAhead(Date.parse("2026-10-09T15:00:00Z")), streetAhead(Date.parse("2026-12-31T23:00:00Z"))];')
        self.assertEqual(got[0], {"season": 11, "name": "NDJ", "months": ["2026-11", "2026-12", "2027-01"],
                                  "words": "November to January"})
        self.assertEqual(got[1], {"season": 1, "name": "JFM", "months": ["2027-01", "2027-02", "2027-03"],
                                  "words": "January to March"})

    # ---- the sentence -------------------------------------------------------------

    SENTENCE = r"""
var st = INPUT.state;
if (INPUT.monthly) st.got.monthly = powerMonths(INPUT.monthly);
if (INPUT.ahead) st.got.ahead = INPUT.ahead;
return {said: streetSentence(st), ndj: st.got.monthly ? seasonOf(st.got.monthly, 11) : null};"""
    ECMWF = "ECMWF expects +0.52 mm a day and +4.0 \u00b0C against its normal for November to January."

    def test_the_sentence_where_el_nino_brings_rain(self):
        months, payload = self.record(wet_rain, warm_air)
        got = self.run_js(self.SENTENCE, payload, state=self.state(), monthly=power(months), ahead=AHEAD_LIMA)
        said, p = text(got["said"]), got["ndj"]["p"]
        self.assertTrue(said.startswith("RONI is +1.7 for JAS 2026: strong El Ni\u00f1o conditions, 4 seasons so far. "), said)
        found = re.search(r"In past El Ni\u00f1os, November to January here was wetter by ([\d.]+) mm a day "
                          r"\(\+(\d+)%; (\d+) of (\d+) events\)", said)
        self.assertIsNotNone(found, said)
        self.assertAlmostEqual(float(found.group(1)), p["diff"], delta=0.051)
        self.assertLessEqual(abs(int(found.group(2)) - p["percent"]), 0.5 + 1e-9)
        wetter = sum(1 for e in p["events"] if e["value"] > p["base"])
        self.assertEqual((int(found.group(3)), int(found.group(4))), (wetter, len(p["events"])))
        self.assertIn(" than in neutral years. ", said)
        self.assertTrue(said.endswith(self.ECMWF), said)

    def test_the_sentence_where_el_nino_leaves_the_street_alone(self):
        months, payload = self.record(lambda y, m, v: 3.0, lambda y, m, v: 25.0)
        got = self.run_js(self.SENTENCE, payload, state=self.state(), monthly=power(months), ahead=AHEAD_LIMA)
        said = text(got["said"])
        self.assertIn("Past El Ni\u00f1os left no clear mark on November to January here: rain and temperature were "
                      f"within what chance gives against {got['ndj']['p']['years']} neutral years.", said)
        for word in ("wetter", "drier", "warmer", "cooler"):
            self.assertNotIn(word, said)

    def test_the_sentence_where_too_few_el_ninos_fall_in_the_season(self):
        months, payload = self.record(wet_rain, warm_air,
                                      index=lambda y, m: 1.5 if (y, m) in ((1990, 12), (1995, 1)) else 0.0)
        got = self.run_js(self.SENTENCE, payload, state=self.state(), monthly=power(months), ahead=AHEAD_LIMA)
        said, p = text(got["said"]), got["ndj"]["p"]
        self.assertIn(f"Too few past El Ni\u00f1os fall in November to January to say what they did here "
                      f"(2 El Ni\u00f1os against {p['years']} neutral years; the composite needs 3 and 6).", said)

    def test_the_sentence_where_only_the_forecast_could_be_read(self):
        got = self.run_js(self.SENTENCE, state=self.state(why={"monthly": "did not answer within 20 s"}), ahead=AHEAD_LIMA)
        said = text(got["said"])
        self.assertIn("NASA POWER\u2019s record of this place could not be read (did not answer within 20 s), "
                      "so what past El Ni\u00f1os did here is not shown. ", said)
        self.assertNotIn("In past El Ni\u00f1os", said)
        self.assertTrue(said.endswith(self.ECMWF), said)

    # ---- the card -----------------------------------------------------------------

    def test_nothing_is_asked_for_until_the_reader_asks(self):
        got = self.run_js("return streetCardHtml(INPUT.state);", state=self.state(asked=False))
        self.assertIn('data-street="ask"', got)
        self.assertNotIn("data-street-retry", got)
        self.assertNotIn("Right now", got)
        self.assertIn("RONI is +1.7 for JAS 2026", text(got))

    def test_a_source_being_asked_says_so(self):
        got = text(self.run_js("return streetCardHtml(INPUT.state);",
                               state=self.state(asking={"monthly": True, "daily": True, "now": True, "ahead": True})))
        self.assertIn("Reading NASA POWER\u2019s record of this place\u2026", got)
        self.assertIn("Asking Open-Meteo\u2026", got)
        self.assertNotIn("Retry", got)

    def test_a_failed_source_offers_retry_and_the_others_still_show(self):
        months, payload = self.record(wet_rain, warm_air)
        got = self.run_js(r"""
var st = INPUT.state; st.got.monthly = powerMonths(INPUT.monthly); st.got.now = streetTrim("now", INPUT.now);
return streetCardHtml(st);""", payload, state=self.state(why={"ahead": "answered 429"}), monthly=power(months),
                          now=NOW_LIMA)
        self.assertIn('data-street-retry="ahead"', got)
        self.assertNotIn('data-street-retry="now"', got)
        self.assertNotIn('data-street-retry="monthly"', got)
        words = text(got)
        self.assertIn("Open-Meteo answered 429.", words)
        self.assertIn("23.4 \u00b0C, clear sky", words)
        self.assertIn("El Ni\u00f1o\u2019s year here", words)
        self.assertIn('<svg class="streetbars"', got)
        self.assertIn('<a href="https://open-meteo.com/" target="_blank" rel="noopener">Weather data by Open-Meteo.com</a>',
                      got)

    def test_el_nino_s_year_draws_only_what_the_composite_can_say(self):
        # El Nino in six DJFs and in two Julys: DJF can be composited, JJA
        # cannot, and is said to be short, not drawn; temperature does not
        # follow the index, so where it is drawn it is faint unless the t
        # test passes it.
        def index(y, m):
            djf = m in (12, 1, 2) and y in (1983, 1987, 1992, 1995, 1998, 2003)
            return 1.5 if djf or (m == 7 and y in (1985, 1999)) else 0.0
        months, payload = self.record(wet_rain, lambda y, m, v: round(25.0 + ((y * 11 + m * 3) % 5) / 10, 2), index=index)
        got = self.run_js(r"""
var rec = powerMonths(INPUT.monthly), year = streetYear(rec);
return {html: streetYearHtml(INPUT.state, year, streetAhead(Date.now())), year: year};""", payload,
                          state=self.state(), monthly=power(months))
        markup, year = got["html"], got["year"]
        bars = {(int(col), key): cls for cls, col, key in
                re.findall(r'<path class="bar([^"]*)" data-col="(\d+)" data-series="(\w+)"', markup)}
        self.assertTrue(year[0]["p"]["usable"])
        self.assertGreaterEqual(abs(year[0]["p"]["t"]), year[0]["p"]["crit"])
        self.assertFalse(year[6]["p"]["usable"])
        for s in year:
            for key in ("p", "t"):
                c = s[key]
                with self.subTest(season=s["name"], key=key):
                    if not c["usable"]:
                        self.assertNotIn((s["season"], key), bars)
                    else:
                        self.assertEqual("faint" in bars[(s["season"], key)], abs(c["t"]) < c["crit"])
        row = re.search(r"<tr><th scope=\"row\">JJA.*?</tr>", markup).group(0)
        self.assertIn("too few events: 2 El Ni\u00f1os", text(row))

    def test_past_el_ninos_are_each_named_and_this_year_so_far_set_beside_them(self):
        months, payload = self.record(wet_rain, warm_air, last=(2010, 10))
        got = self.run_js(r"""
var st = INPUT.state; st.got.monthly = powerMonths(INPUT.monthly);
var year = streetYear(st.got.monthly);
return {html: streetEventsHtml(st, st.got.monthly, year, streetAhead(Date.now())), ndj: year[11].p};""", payload,
                          state=self.state(), monthly=power(months))
        words = text(got["html"])
        self.assertIn("Past El Ni\u00f1os, November to January", words)
        for event in got["ndj"]["events"]:
            with self.subTest(tag=event["tag"]):
                self.assertIn(f"{event['tag']}-{(event['tag'] + 1) % 100:02d}", words)
        self.assertIn("This year so far: ASO 2010 here was ", words)

    def test_the_card_names_its_sources_as_they_ask_to_be_named(self):
        def index(y, m):
            if (y, m) >= (2010, 6):
                return [0.5, 0.8, 1.2, 1.6, 1.9, 2.1, 2.2][(y - 2010) * 12 + m - 6]
            return 1.3 if m == 1 and y % 4 == 0 else 0.1
        months, payload = self.record(wet_rain, warm_air, index=index)
        got = self.run_js("return streetMethodHtml(INPUT.state);", payload, state=self.state())
        words = text(got)
        self.assertIn('<a href="https://open-meteo.com/" target="_blank" rel="noopener">Weather data by Open-Meteo.com</a>',
                      got)
        self.assertIn("These data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded "
                      "through the NASA Earth Science/Applied Science Program.", words)
        self.assertIn("This service is based on data and products of the European Centre for Medium-Range Weather "
                      "Forecasts (ECMWF). Source www.ecmwf.int. ECMWF does not accept any liability whatsoever for any "
                      "error or omission in the data, their availability, or for any loss or damage arising from their "
                      "use.", words)
        self.assertIn("the El Ni\u00f1o under way since June 2010 is left out", words)
        self.assertIn(f"{atlas.DRY_FLOOR} mm a day or more", words)

    def test_the_method_says_the_latest_months_are_geos_it_s(self):
        # POWER's daily answer lists GEOS-IT beside MERRA-2: its newest days,
        # past where the monthly record reaches, are the other analysis.
        months, payload = self.record(wet_rain, warm_air)
        words = text(self.run_js("return streetMethodHtml(INPUT.state);", payload, state=self.state()))
        self.assertIn("The months its monthly record has yet to reach come from POWER\u2019s daily record, a month once "
                      "it has 25 days; POWER\u2019s newest days are NASA\u2019s GEOS-IT analysis, not MERRA-2, so this "
                      "year\u2019s latest months are one analysis set against another\u2019s neutral years.", words)
        self.assertIn("It is a model\u2019s grid cell, not a gauge on this street.", words)

    # ---- answers of another shape, and what is kept ---------------------------------

    ODD = [["ahead", {"monthly": {"time": "2026-10-01"}}],
           ["ahead", {"monthly": {"time": [None, "2026-11-01"]}}],
           ["ahead", {"monthly": {"time": ["2026-10-01"], "temperature_2m_anomaly": "x", "precipitation_mean": [1.5, "y"]}}],
           ["now", {"current": {"temperature_2m": 20.1, "time": "2026-10-09T10:00", "weather_code": "rain"},
                    "hourly": {"precipitation": "x"}, "timezone_abbreviation": "PET"}],
           ["now", {"current": "x"}],
           ["daily", {"header": {"fill_value": -999},
                      "properties": {"parameter": {"PRECTOTCORR": "x", "T2M": {"20261001": 20.5}}}}],
           ["daily", {"header": {"fill_value": "none"},
                      "properties": {"parameter": {"PRECTOTCORR": {"20261001": 1.2, "2026100": 3.0, "20261002": "wet"},
                                                   "T2M": {"20261001": 20.5, "x": 1}}}}],
           ["monthly", {"properties": {"parameter": {"PRECTOTCORR": "x", "T2M": "y"}}}],
           ["ahead", ["2026-10-01"]],
           ["now", None]]

    def test_an_answer_of_another_shape_has_nothing_for_the_point_and_the_card_still_writes(self):
        got = self.run_js(r"""
var trimmed = INPUT.odd.map(function (c) { return streetTrim(c[0], c[1]); });
var st = INPUT.state;
st.got.ahead = trimmed[2]; st.got.now = trimmed[3];
return {trimmed: trimmed, card: streetCardHtml(st)};""", state=self.state(), odd=self.ODD)
        self.assertEqual(got["trimmed"], [
            None, None,
            {"monthly": {"time": ["2026-10-01"], "precipitation_mean": [1.5]}},
            {"current": {"temperature_2m": 20.1, "time": "2026-10-09T10:00"}, "hourly": None,
             "timezone_abbreviation": "PET"},
            None, None,
            {"header": {"fill_value": None},
             "properties": {"parameter": {"PRECTOTCORR": {"20261001": 1.2}, "T2M": {"20261001": 20.5}}}},
            None, None, None])
        words = text(got["card"])
        self.assertIn("20.1 \u00b0C. ", words)
        self.assertIn("ECMWF\u2019s seasonal forecast has nothing for this point.", words)

    def test_an_answer_kept_is_read_again_as_itself(self):
        # What is kept is read again on the next load as an answer is read:
        # it must come out as it went in.
        months, payload = self.record(wet_rain, warm_air)
        days = power({f"2026{m:02d}{d:02d}": (1.0 + d / 10, 20.0 + d / 10) for m in (8, 9) for d in range(1, 31)},
                     daily=True)
        got = self.run_js(r"""
return [["now", INPUT.now], ["ahead", INPUT.ahead], ["daily", INPUT.daily]].map(function (c) {
  var kept = streetTrim(c[0], c[1]);
  return kept !== null && JSON.stringify(streetTrim(c[0], kept)) === JSON.stringify(kept);
}).concat([streetSound("monthly", powerMonths(INPUT.monthly)) !== null]);""", payload,
                          now=NOW_LIMA, ahead=AHEAD_LIMA, daily=days, monthly=power(months))
        self.assertEqual(got, [True, True, True, True])

    def test_a_kept_answer_of_another_shape_is_let_go(self):
        # The tab's session outlives the page: an answer kept by another
        # version of it, in another shape, is read again as an answer, and
        # let go where it says nothing; the card is written either way.
        got = self.run_js(r"""
var store = {}, removed = [], at = Date.now();
sessionStorage = {getItem: function (k) { return k in store ? store[k] : null; },
                  setItem: function (k, v) { store[k] = String(v); },
                  removeItem: function (k) { removed.push(k); delete store[k]; }};
store[STREET_STORE + "ahead|-12.05,-77.04"] = JSON.stringify({at: at, data: {monthly: {time: "2026-10-01"}}});
store[STREET_STORE + "now|-12.05,-77.04"] = JSON.stringify({at: at, data: {current: {temperature_2m: 20},
  hourly: {precipitation: "x"}, timezone_abbreviation: "PET"}});
store[STREET_STORE + "monthly|-12.05,-77.04"] = JSON.stringify({at: at, data: {from: "1981-01", p: "x", t: []}});
var st = streetState(-77.04, -12.05), card = streetCardHtml(st), calls = [];
fetch = function (url) {
  calls.push(url);
  return Promise.resolve({ok: true, status: 200, json: function () { return Promise.resolve(INPUT.reply); }});
};
return streetGet("ahead", -77.04, -12.05).then(function (again) {
  return {got: [st.got.monthly, st.got.now, st.got.ahead], removed: removed.sort(), card: typeof card,
          calls: calls.length, again: again.monthly.time.length};
});""", reply=AHEAD_LIMA)
        self.assertEqual(got["got"], [None, {"current": {"temperature_2m": 20}, "hourly": None,
                                             "timezone_abbreviation": "PET"}, None])
        self.assertEqual(got["removed"], ["elnino-street-1:ahead|-12.05,-77.04", "elnino-street-1:monthly|-12.05,-77.04"])
        self.assertEqual([got["card"], got["calls"], got["again"]], ["string", 1, 6])

    def test_a_card_that_cannot_be_written_says_so_and_offers_to_ask_again(self):
        got = self.run_js(r"""
var st = INPUT.state;
st.got.monthly = {from: "1981-01", p: null, t: null};
return [streetCardHtml(st), streetSentence(st)];""", state=self.state())
        self.assertEqual(got[0], '<h3 class="streethead" id="street-card-title">El Ni\u00f1o on this street</h3>'
                                 '<p class="streetfail">What the sources sent for this point could not be read. '
                                 '<button type="button" class="toolbtn" data-street="again">Ask again</button></p>')
        self.assertEqual(got[1], "RONI is +1.7 for JAS 2026: strong El Ni\u00f1o conditions, 4 seasons so far. "
                                 "What the sources sent for this point could not be read.")

    def test_the_record_and_the_forecast_are_asked_again_after_a_day(self):
        # A tab stays open for days: POWER's record gains its months, and
        # ECMWF runs its forecast each month.
        got = self.run_js(r"""
var calls = 0;
fetch = function () {
  calls++;
  return Promise.resolve({ok: true, status: 200, json: function () { return Promise.resolve(INPUT.reply); }});
};
STREET_KEPT["ahead|10.00,20.00"] = {at: Date.now() - 23 * 3600000, data: {monthly: {time: []}}};
STREET_KEPT["ahead|11.00,20.00"] = {at: Date.now() - 25 * 3600000, data: {monthly: {time: []}}};
return Promise.all([streetGet("ahead", 20, 10), streetGet("ahead", 20, 11)])
  .then(function (got) { return [calls, got[0].monthly.time.length, got[1].monthly.time.length]; });""",
                          reply=AHEAD_LIMA)
        self.assertEqual(got, [1, 0, 6])

    def test_the_tab_keeps_the_last_twenty_points_asked(self):
        # The session is the site's, shared with the follower's handover:
        # the street keeps the twenty points last answered, and fewer once
        # the session is full; what is not the street's is left alone.
        got = self.run_js(r"""
var store = {"someone-else": "kept"}, room = Infinity, t = Date.now();
sessionStorage = {
  get length() { return Object.keys(store).length; },
  key: function (i) { return Object.keys(store)[i]; },
  getItem: function (k) { return k in store ? store[k] : null; },
  setItem: function (k, v) {
    if (!(k in store) && Object.keys(store).length >= room) throw new Error("QuotaExceededError");
    store[k] = String(v);
  },
  removeItem: function (k) { delete store[k]; }
};
Date.now = function () { return t; };
function ask(i) {
  t += 60000;
  streetStore("ahead|" + i + ".00,0.00", {monthly: {time: []}});
  streetStore("now|" + i + ".00,0.00", {current: {}, hourly: null, timezone_abbreviation: ""});
}
for (var i = 0; i < 21; i++) ask(i);
var first = [Object.keys(STREET_KEPT).sort(), Object.keys(store).sort()];
room = Object.keys(store).length;
t += 60000;
streetStore("ahead|21.00,0.00", {monthly: {time: []}});
return [first, [Object.keys(STREET_KEPT).sort(), Object.keys(store).sort()]];""")

        def keys(points, prefix=""):
            return sorted(f"{prefix}{kind}|{p}.00,0.00" for p in points for kind in ("ahead", "now"))
        store = "elnino-street-1:"
        self.assertEqual(got[0], [keys(range(1, 21)), sorted(["someone-else"] + keys(range(1, 21), store))])
        self.assertEqual(got[1], [sorted(keys(range(2, 21)) + ["ahead|21.00,0.00"]),
                                  sorted(["someone-else", store + "ahead|21.00,0.00"] + keys([20], store))])


if __name__ == "__main__":
    unittest.main()
