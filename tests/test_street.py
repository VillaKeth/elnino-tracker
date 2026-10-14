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

from elnino import atlas, stormdesk, street, streetstorms, thennow, worldmap  # noqa: E402
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
        self.assertEqual(set(sources), {"monthly", "daily", "now", "ahead", "days"})
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
        # ECMWF's run reaches seven months from the month it is made in; the
        # replay's six from next month need them all, and Open-Meteo gives
        # six unless asked (12 October 2026).
        self.assertTrue(sources["ahead"].endswith("&forecast_days=215"), sources["ahead"])
        self.assertIn("forecast_hours=24", sources["now"])
        # The replay's record: every day since 1981, as CSV, 342 KB where the
        # JSON was 547 for Winter Haven on 12 October 2026.
        self.assertEqual(sources["days"], "https://power.larc.nasa.gov/api/temporal/daily/point?parameters="
                         "PRECTOTCORR,T2M&community=AG&longitude={lon}&latitude={lat}&start=19810101&end={end}"
                         "&format=CSV")

    def test_a_picked_point_is_taken_to_a_road_on_osrm_s_car_network(self):
        # FOSSGIS's OSRM over OpenStreetMap, as it answered on 12 October
        # 2026: the 100 nearest stretches of road a car may take, each with
        # its name and how far it is, its documented limit, in 25 KB.
        self.assertEqual(street.payload(state_with(EVENT))["roads"],
                         "https://routing.openstreetmap.de/routed-car/nearest/v1/driving/{lon},{lat}?number=100")

    def test_a_pick_osrm_does_not_answer_is_asked_of_valhalla(self):
        # FOSSGIS's Valhalla over the same map, as it answered on 14 October
        # 2026: the roads a car may take within the radius, or the nearest,
        # each with its names and how far it is; sent with
        # Access-Control-Allow-Origin: *.
        self.assertEqual(street.payload(state_with(EVENT))["locate"],
                         "https://valhalla1.openstreetmap.de/locate?json={json}")


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
        # Next street, first of the ways on, shown when a pick has a list; and
        # the line saying where the stage is against the pick.
        self.assertIn('<p class="streetplace" id="street-place" aria-live="polite"></p>'
                      '<button type="button" class="toolbtn" id="street-next" hidden>Next street</button>'
                      '<button type="button" class="toolbtn" id="street-find" hidden>Find the street</button>'
                      '<button type="button" class="toolbtn" id="street-then">Then and now</button>', stage)
        self.assertIn('<p class="streetroads" id="street-roads" aria-live="polite"></p><p class="streetnote">',
                      stage)

    def test_what_google_shows_is_said_before_it_is_met(self):
        # Shown while no pick's line is - a point entered exactly, or its
        # street still being found - it says what a pick does.
        self.assertIn('<p class="streetnote">Street View shows Google\u2019s panorama nearest the stage\u2019s point. '
                      "A point picked (the figure dropped, the minimap tapped, or Street View pressed in Here or in "
                      "then and now) goes to the nearest named street within a kilometre, else the nearest road within "
                      "reach. Where Google "
                      "has no panorama of it, it says \u201cNo Street View available.\u201d, and where its nearest is a "
                      "photo someone took inside, it shows that: Next street tries the next. The minimap and the card "
                      "are this point\u2019s either way.</p>", street.map_parts())
        # The line about the pick, once there is one, says it for this point:
        # the note gives it the room.
        css = street.css()
        self.assertIn(".streetroads:empty { display: none; }", css)
        self.assertIn(".streetroads:not(:empty) + .streetnote { display: none; }", css)

    def test_the_nearest_street_is_credited_as_its_operator_and_openstreetmap_ask(self):
        self.assertIn('<p class="streetcredit">Nearest street: <a href="https://project-osrm.org/" target="_blank" '
                      'rel="noopener">OSRM</a> or <a href="https://valhalla.github.io/valhalla/" target="_blank" '
                      'rel="noopener">Valhalla</a> by FOSSGIS over <a href="https://www.openstreetmap.org/copyright" '
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
        # Under the live storms' line, which shows with a storm near; the
        # storm panel's button after the replay's.
        self.assertIn('<div class="streetchip" id="street-chip">' + streetstorms.chip_line() +
                      '<div class="streetchiphead" id="street-chip-head"><b>El Ni\u00f1o on this street</b><button '
                      'type="button" class="toolbtn streetreplay" id="street-replay">Replay El Ni\u00f1o\u2019s rain'
                      "</button>" + streetstorms.button() + '<button type="button" class="streetmore" '
                      'id="street-more">The whole card \u2193</button></div>', stage)
        self.assertIn('<p class="streetchipsaid" id="street-chip-said"></p>', stage)
        # The panorama is between the bar and the strip under it, so nothing
        # of the page sits on Google's own controls and credit.
        order = [stage.index(s) for s in ('class="streetbar"', 'id="street-pano"', 'class="streetfoot"')]
        self.assertEqual(order, sorted(order))

    def test_the_rain_lies_over_the_panorama_clear_of_google_s_foot(self):
        # The replay's rain and the badge naming its day lie over Google's
        # panorama, beside its frame and not in it, so a new frame keeps them.
        self.assertIn('<div class="streetview"><div class="streetpano" id="street-pano"></div>'
                      '<canvas class="streetrain" id="street-rain" aria-hidden="true" hidden></canvas>'
                      '<p class="streetday" id="street-day" aria-hidden="true" hidden></p></div>', street.map_parts())
        # Neither takes a pointer from the panorama; the rain stops 40 px above
        # its foot, Google's logo and terms, and fades out above them, and the
        # badge sits above them too.
        css = street.css()
        self.assertIn(".streetrain { position: absolute; left: 0; top: 0; width: 100%; height: calc(100% - 40px); "
                      "pointer-events: none;", css)
        self.assertIn("-webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 48px), transparent);", css)
        self.assertIn(" mask-image: linear-gradient(to bottom, #000 calc(100% - 48px), transparent);", css)
        self.assertIn(".streetday { position: absolute; left: 8px; bottom: 48px;", css)
        self.assertRegex(css, r"\.streetday \{[^}]*pointer-events: none;")

    def test_the_replay_opens_in_the_chip_with_its_controls(self):
        stage = street.map_parts()
        panel = stage[stage.index('<div class="streetsim" id="street-sim"'):]
        self.assertTrue(panel.startswith('<div class="streetsim" id="street-sim" role="group" '
                                         'aria-labelledby="street-sim-title" tabindex="-1" hidden>'))
        self.assertIn('<b id="street-sim-title">El Ni\u00f1o\u2019s rain, replayed here</b><button type="button" '
                      'class="streetmore" id="street-sim-back">Back to the card</button>', panel)
        # Its words say what it does, Play or Pause, and nothing more.
        self.assertIn('<button type="button" class="toolbtn" id="street-sim-play" disabled>Play</button>', panel)
        self.assertIn('<label>El Ni\u00f1o <select id="street-sim-event" disabled></select></label>', panel)
        # Six months from any month, and three speeds, a week a second first.
        starts = re.findall(r'<option value="(\d+)">([^<]*)</option>',
                            re.search(r'<select id="street-sim-start">(.*?)</select>', panel).group(1))
        self.assertEqual(len(starts), 12)
        self.assertEqual([starts[0], starts[9], starts[11]],
                         [("1", "January to June"), ("10", "October to March"), ("12", "December to May")])
        self.assertIn('<label>Speed <select id="street-sim-speed"><option value="7">a week a second</option>'
                      '<option value="14">two weeks a second</option><option value="30">a month a second</option>'
                      "</select></label>", panel)
        self.assertIn('<input type="range" class="streetsimday" id="street-sim-day" min="0" max="0" step="1" '
                      'value="0" aria-label="Day of the window" disabled>', panel)
        order = [panel.index('id="' + ident + '"') for ident in
                 ("street-sim-day", "street-sim-read", "street-sim-chart", "street-sim-key", "street-sim-said",
                  "street-sim-fail", "street-sim-table", "street-sim-method")]
        self.assertEqual(order, sorted(order))
        self.assertIn('<p class="streetfail" id="street-sim-fail" hidden><span id="street-sim-why"></span> <button '
                      'type="button" class="toolbtn" id="street-sim-retry">Retry</button></p>', panel)
        self.assertIn("<summary>Year by year</summary>", panel)
        self.assertIn("<summary>Method and sources</summary>", panel)
        # NASA POWER credited under it while it is open.
        self.assertIn('<p class="streetcredit" id="street-sim-credit" hidden>Daily rain: <a '
                      'href="https://power.larc.nasa.gov/" target="_blank" rel="noopener">NASA POWER</a>, NASA Langley '
                      "Research Center.</p>", stage)
        # Open, as the storm panel open, the chip stands taller and, on a
        # phone, takes the minimap's room; a finger across the chart seeks,
        # and up and down scrolls.
        css = street.css()
        self.assertIn(".streetstage.simon .streetchip, .streetstage.tcon .streetchip { max-height: none; }", css)
        self.assertIn("@media (max-width: 899px) { .streetstage.simon .streetmini, .streetstage.tcon .streetmini "
                      "{ display: none; } }", css)
        # On a phone the stage stands taller while it is open, so the
        # panorama, where the rain falls, keeps its room.
        # (of the viewport as it is with the browser's bars shown, where the
        # browser knows it).
        self.assertIn("@media (max-width: 899px) {\n  #map.streeton:has(.streetstage.simon), "
                      "#map.streeton:has(.streetstage.tcon) { height: 92vh; height: 92svh; }\n}", css)
        self.assertIn(".streetsimchart { position: relative; min-height: 170px; touch-action: pan-y;", css)

    def test_the_chart_s_line_rules_leave_its_labels_seen(self):
        # A line's class names its label too: a rule taking a line's fill
        # away is a path's, or the label at its end is drawn unseen.
        css = street.css()
        for cls in ("neutral", "ecmwf", "ev", "evfaint", "now"):
            with self.subTest(cls):
                self.assertNotRegex(css, r"\.streetsimsvg \.%s\b" % cls)
                self.assertRegex(css, r"\.streetsimsvg path\.%s \{ stroke: " % cls)
        self.assertIn(".streetsimsvg text { font: 10px var(--font); fill: var(--ink2); }", css)

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
# OSRM's answer for a point picked in Winter Haven, made as its answers come:
# two unnamed ways at the point, Hoover Road twice, Lake Shore Drive with
# spaces about its name and again without, a road 1.5 km off, one past 5 km,
# and two waypoints that cannot be read.
ROADS_WH = {"code": "Ok", "waypoints": [
    {"location": [-81.729997, 27.99967], "name": "", "distance": 4.2},
    {"location": [-81.7301, 27.9997], "name": "", "distance": 9.0},
    {"location": [-81.729659, 27.989109], "name": "Hoover Road", "distance": 227.4},
    {"location": [-81.7297, 27.9892], "name": "Hoover Road", "distance": 231.0},
    {"location": [-81.731, 27.991], "name": " Lake Shore Drive ", "distance": 310.0},
    {"location": [-81.735, 27.995], "name": "Lake Shore Drive", "distance": 330.0},
    {"location": [-81.701989, 28.047209], "name": "Martin Luther King Jr Boulevard", "distance": 1483.0},
    {"location": [-81.75, 28.0], "name": "Far Road", "distance": 5200.0},
    {"location": ["x", None], "name": "Broken", "distance": 20},
    {"location": [-81.74, 28.01], "name": "No Distance"}]}
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
                         "https://routing.openstreetmap.de/routed-car/nearest/v1/driving/-77.050283,-12.045154?number=100")
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

    def test_a_pick_goes_to_a_named_street_within_a_kilometre_else_a_road_within_reach_else_stays(self):
        def road(distance, name="Avenida Guillermo Dansey", location=(-77.050231, -12.045687)):
            return {"code": "Ok", "waypoints": [{"location": list(location), "name": name, "distance": distance}]}
        cases = [("a named road 400 m off at a street's zoom", 16, road(400)),
                 ("a named road 1.2 km off at a street's zoom", 16, road(1200)),
                 ("a named road 1.2 km off in a city's view", 11, road(1200)),
                 ("past 5 km at the world's", 3, road(6000)), ("a failure", 16, "error"), ("an error status", 16, 503),
                 ("no road", 16, {"code": "NoSegment", "message": "Could not find a matching segment"}),
                 ("a strange answer", 16, {"code": "Ok", "waypoints": [{"location": ["a", None], "distance": 5}]}),
                 ("no answer", 16, "hang"), ("an unnamed road", 16, road(5, name=""))]
        got = _run(self, r"""
          Date.now = function () { return NOW + CLOCK; };
          var out = [];
          async function pick(z, answer) {
            ROUTES = []; route("routed-car/nearest", answer === "error" ? new TypeError("Failed to fetch") : answer);
            streetPick(-77.050283, -12.045154, z);
            advance(1000); await flush();
            advance(6000); await flush();
            return [S.street.lon, S.street.lat, S.street.label, S.street.finding,
                    $("street-pano").innerHTML.indexOf("cbll=" + S.street.lat.toFixed(6) + "," + S.street.lon.toFixed(6)) > 0,
                    $("street-roads").textContent, $("street-next").hidden, $("street-find").hidden];
          }
          var cases = """ + json.dumps([[z, answer] for _, z, answer in cases]) + r""";
          for (var i = 0; i < cases.length; i++) out.push(await pick(cases[i][0], cases[i][1]));
          console.log(JSON.stringify(out));
        """)
        here, named = [-77.050283, -12.045154, "12.05S 77.05W"], "Avenida Guillermo Dansey, 12.05S 77.05W"
        # Neither street finder gave a road (Valhalla, asked next, has no
        # route here): the point as picked, saying so, and Find the street.
        lost = here + [False, True, "The nearest street could not be found: this is Google\u2019s panorama nearest "
                       "the point as picked, if it has one.", True, False]
        expected = [
            [-77.050231, -12.045687, named, False, True,
             "The nearest named street, 400 m from the point picked. No panorama of it? Next street: the point "
             "picked.", False, True],
            here + [False, True, "The point as picked: no named street within 1 km, nor any road within 250 m. "
                    "Next street: Avenida Guillermo Dansey, 1.2 km away.", False, True],
            [-77.050231, -12.045687, named, False, True,
             "The nearest named street, 1.2 km from the point picked. No panorama of it? Next street: the point "
             "picked.", False, True],
            here + [False, True, "The point as picked: no road within 5 km.", True, True],
            lost, lost, lost,
            # An answer whose roads cannot be read is no answer.
            lost,
            lost,
            [-77.050231, -12.045687, "12.05S 77.05W", False, True,
             "The nearest road, 5 m from the point picked. No panorama of it? Next street: the point picked.",
             False, True]]
        for (name, _, _), result, want in zip(cases, got, expected):
            with self.subTest(name):
                self.assertEqual(result, want)

    def test_next_street_goes_down_the_named_streets_nearest_first_then_to_the_point_picked(self):
        got = _run(self, r"""
          route("routed-car/nearest", """ + json.dumps(ROADS_WH) + r""");
          streetPick(-81.73, 27.9997, 16);
          advance(0); await flush();
          function at() {
            return [S.street.lon, S.street.lat, S.street.label, $("street-roads").textContent, $("street-next").hidden,
                    S.here.label];
          }
          var out = [at()];
          for (var i = 0; i < 4; i++) { $("street-next").fire("click"); out.push(at()); }
          console.log(JSON.stringify({out: out, roads: S.street.roads.map(function (r) { return r.point ? "*" : r.name; }),
            osrm: ASKED.filter(function (u) { return u.indexOf("routed-car") >= 0; }).length}));
        """)
        hoover = [-81.729659, 27.989109, "Hoover Road, 27.99N 81.73W",
                  "The nearest named street, 227 m from the point picked. No panorama of it? Next street: Lake Shore "
                  "Drive, 310 m away.", False, "Hoover Road, 27.99N 81.73W"]
        self.assertEqual(got["out"], [
            hoover,
            [-81.731, 27.991, "Lake Shore Drive, 27.99N 81.73W",
             "Lake Shore Drive, 310 m from the point picked (2 of 4). Next street: Martin Luther King Jr Boulevard, "
             "1.5 km away.", False, "Lake Shore Drive, 27.99N 81.73W"],
            [-81.701989, 28.047209, "Martin Luther King Jr Boulevard, 28.05N 81.70W",
             "Martin Luther King Jr Boulevard, 1.5 km from the point picked (3 of 4). Next street: the point picked.",
             False, "Martin Luther King Jr Boulevard, 28.05N 81.70W"],
            [-81.73, 27.9997, "28.00N 81.73W",
             "The point as picked (4 of 4). Next street: Hoover Road, 227 m away.", False, "28.00N 81.73W"],
            hoover])
        # Each name once, at its nearest stretch; the unnamed ways at the
        # point, the road past 5 km and the waypoints not read left out; and
        # OSRM asked once for the lot.
        self.assertEqual(got["roads"], ["Hoover Road", "Lake Shore Drive", "Martin Luther King Jr Boulevard", "*"])
        self.assertEqual(got["osrm"], 1)

    def test_a_road_of_any_name_within_reach_comes_before_named_ones_past_a_kilometre(self):
        answer = {"code": "Ok", "waypoints": [w for w in ROADS_WH["waypoints"]
                                              if w.get("name") in ("", "Martin Luther King Jr Boulevard")]}
        got = _run(self, r"""
          route("routed-car/nearest", """ + json.dumps(answer) + r""");
          streetPick(-81.73, 27.9997, 16);
          advance(0); await flush();
          console.log(JSON.stringify([S.street.lon, S.street.lat, S.street.label, $("street-roads").textContent,
            S.street.roads.map(function (r) { return r.point ? "*" : r.name || "-"; })]));
        """)
        self.assertEqual(got, [-81.729997, 27.99967, "28.00N 81.73W",
                               "The nearest road, 4 m from the point picked. No panorama of it? Next street: Martin "
                               "Luther King Jr Boulevard, 1.5 km away.", ["-", "Martin Luther King Jr Boulevard", "*"]])

    def test_valhalla_is_asked_when_osrm_fails_or_is_slow_and_the_first_road_given_is_taken(self):
        got = _run(self, r"""
          Date.now = function () { return NOW + CLOCK; };
          function at() { return [S.street.lon, S.street.lat, S.street.label, S.street.finding, $("street-roads").textContent,
                                  $("street-next").hidden, $("street-find").hidden]; }
          function asked(words) { return ASKED.filter(function (u) { return u.indexOf(words) >= 0; }); }
          var out = {};
          // OSRM fails: Valhalla at once.
          route("routed-car/nearest", new TypeError("Failed to fetch"));
          route("valhalla1.openstreetmap.de/locate", """ + json.dumps(LOCATE_SI) + r""");
          streetPick(-74.161517, 40.577058, 16);
          advance(0); await flush();
          out.failed = [at(), S.street.roads.map(function (r) { return r.point ? "*" : r.name; }), asked("locate").length];
          out.url = asked("locate")[0];
          $("street-next").fire("click");
          out.next = at();
          // OSRM silent: Valhalla once it has had 2.5 s, its road taken then.
          ROUTES = []; ASKED.length = 0;
          route("routed-car/nearest", "hang");
          route("valhalla1.openstreetmap.de/locate", """ + json.dumps(LOCATE_SI) + r""");
          streetPick(-74.161517, 40.577058, 16);
          advance(1000); await flush();
          advance(2499); await flush();
          out.waiting = [S.street.finding, asked("locate").length];
          advance(1); await flush();
          out.slow = [at(), asked("routed-car").length, asked("locate").length];
          // Both silent: the point as picked at 2.5 + 6 s, not before.
          ROUTES = []; ASKED.length = 0;
          route("routed-car/nearest", "hang");
          route("valhalla1.openstreetmap.de/locate", "hang");
          streetPick(-74.161517, 40.577058, 16);
          advance(1000); await flush();
          advance(2500); await flush();
          advance(5999); await flush();
          out.held = S.street.finding;
          advance(1); await flush();
          out.lost = at();
          console.log(JSON.stringify(out));
        """)
        windham = [-74.161517, 40.577058, "Windham Loop, 40.58N 74.16W", False,
                   "The nearest named street, 0 m from the point picked. No panorama of it? Next street: Rumson Road, "
                   "78 m away.", False, True]
        self.assertEqual(got["failed"], [windham, ["Windham Loop", "Rumson Road", "*"], 1])
        # Roads of a residential street's class or over, and none in a
        # tunnel or a ferry's: at the Battery on 14 October 2026 Valhalla's
        # nearest was the Brooklyn-Battery Tunnel, 38 m under the pick.
        self.assertEqual(got["url"], "https://valhalla1.openstreetmap.de/locate?json=%7B%22locations%22%3A%5B%7B%22lat"
                         "%22%3A40.577058%2C%22lon%22%3A-74.161517%2C%22radius%22%3A100%2C%22search_filter%22%3A%7B"
                         "%22min_road_class%22%3A%22residential%22%2C%22exclude_tunnel%22%3Atrue%2C%22exclude_ferry"
                         "%22%3Atrue%7D%7D%5D%2C%22costing%22%3A%22auto%22%2C%22verbose%22%3Atrue%7D")
        self.assertEqual(got["next"], [-74.160746, 40.576674, "Rumson Road, 40.58N 74.16W", False,
                                       "Rumson Road, 78 m from the point picked (2 of 3). Next street: the point "
                                       "picked.", False, True])
        self.assertEqual(got["waiting"], [True, 0])
        self.assertEqual(got["slow"], [windham, 1, 1])
        self.assertTrue(got["held"])
        self.assertEqual(got["lost"], [-74.161517, 40.577058, "40.58N 74.16W", False,
                                       "The nearest street could not be found: this is Google\u2019s panorama nearest "
                                       "the point as picked, if it has one.", True, False])

    def test_valhalla_is_not_asked_when_osrm_answers_in_time_and_osrm_late_still_counts(self):
        got = _run(self, r"""
          Date.now = function () { return NOW + CLOCK; };
          function locates() { return ASKED.filter(function (u) { return u.indexOf("/locate?") >= 0; }).length; }
          var out = {};
          // OSRM answers: Valhalla is never asked, though 2.5 s and more go by.
          route("routed-car/nearest", """ + json.dumps(ROADS_WH) + r""");
          route("valhalla1.openstreetmap.de/locate", """ + json.dumps(LOCATE_SI) + r""");
          streetPick(-81.73, 27.9997, 16);
          advance(0); await flush();
          advance(3000); await flush();
          advance(7000); await flush();
          out.answered = [S.street.label, locates()];
          // OSRM answers after Valhalla was asked at 2.5 s, Valhalla silent:
          // OSRM's street is taken when it comes.
          var answer = null, real = fetch;
          fetch = function (url, opts) {
            if (url.indexOf("routed-car") < 0) return real(url, opts);
            ASKED.push(url);
            return new Promise(function (ok) { answer = function () {
              ok({ok: true, status: 200, json: function () { return Promise.resolve(""" + json.dumps(ROADS_WH) + r"""); }});
            }; });
          };
          route("valhalla1.openstreetmap.de/locate", "hang");
          streetPick(-81.73, 27.9997, 16);
          advance(1000); await flush();
          advance(2500); await flush();
          out.hedged = [S.street.finding, locates()];
          advance(1000); answer(); await flush();
          out.late = [S.street.finding, S.street.label];
          fetch = real;
          console.log(JSON.stringify(out));
        """)
        self.assertEqual(got["answered"], ["Hoover Road, 27.99N 81.73W", 0])
        self.assertEqual(got["hedged"], [True, 1])
        self.assertEqual(got["late"], [False, "Hoover Road, 27.99N 81.73W"])

    def test_valhalla_is_asked_only_for_the_stage_s_own_pick_and_a_late_answer_is_dropped(self):
        got = _run(self, r"""
          Date.now = function () { return NOW + CLOCK; };
          function locates() {
            return ASKED.filter(function (u) { return u.indexOf("/locate?") >= 0; }).map(function (u) {
              return JSON.parse(decodeURIComponent(u.split("json=")[1])).locations[0].lon;
            });
          }
          var out = {};
          // OSRM silent and the stage left a second on: Valhalla is not asked
          // when 2.5 s have gone by.
          route("routed-car/nearest", "hang");
          route("valhalla1.openstreetmap.de/locate", """ + json.dumps(LOCATE_SI) + r""");
          streetPick(-81.73, 27.9997, 16);
          advance(0); await flush();
          advance(1000); streetLeave();
          advance(2000); await flush();
          out.left = [S.street, locates()];
          // A pick replaced 1.8 s on by one OSRM fails at once: Valhalla is
          // asked for the new one, and not for the old one at its 2.5 s.
          ASKED.length = 0;
          route("routed-car/nearest", function (url) {
            return url.indexOf("-81.730000") >= 0 ? "hang" : new TypeError("Failed to fetch");
          });
          advance(1000);
          streetPick(-81.73, 27.9997, 16);
          advance(0); await flush();
          advance(1800);
          streetPick(-81.70, 28.05, 16);
          advance(0); await flush();
          advance(1000); await flush();
          out.replaced = [S.street.label, locates()];
          // Valhalla answering for a stage since left: nothing changes.
          ASKED.length = 0;
          var answer = null, real = fetch;
          fetch = function (url, opts) {
            if (url.indexOf("/locate?") < 0) return real(url, opts);
            ASKED.push(url);
            return new Promise(function (ok) { answer = function () {
              ok({ok: true, status: 200, json: function () { return Promise.resolve(""" + json.dumps(LOCATE_SI) + r"""); }});
            }; });
          };
          route("routed-car/nearest", new TypeError("Failed to fetch"));
          advance(1000);
          streetPick(-81.60, 28.10, 16);
          advance(1000); await flush();
          var asked = locates().length;
          streetHashApply("#street=28.20000,-81.50000");
          answer(); await flush();
          out.dropped = [asked, S.street.lon, S.street.lat, S.street.roads];
          fetch = real;
          console.log(JSON.stringify(out));
        """)
        self.assertEqual(got["left"], [None, []])
        self.assertEqual(got["replaced"], ["Windham Loop, 40.58N 74.16W", [-81.7]])
        self.assertEqual(got["dropped"], [1, -81.5, 28.2, None])

    def test_valhalla_is_asked_once_a_second_at_most(self):
        got = _run(self, r"""
          Date.now = function () { return NOW + CLOCK; };
          function locates() {
            return ASKED.filter(function (u) { return u.indexOf("/locate?") >= 0; }).map(function (u) {
              return JSON.parse(decodeURIComponent(u.split("json=")[1])).locations[0].lon;
            });
          }
          // A's OSRM silent: Valhalla asked for A at its 2.5 s, and silent too.
          // B picked 0.1 s later, its OSRM failing at once: Valhalla is asked
          // for B a second after it was asked for A, not at once.
          route("routed-car/nearest", function (url) {
            return url.indexOf("-81.730000") >= 0 ? "hang" : new TypeError("Failed to fetch");
          });
          route("valhalla1.openstreetmap.de/locate", function (url) {
            return url.indexOf("-81.73") >= 0 ? "hang" : """ + json.dumps(LOCATE_SI) + r""";
          });
          streetPick(-81.73, 27.9997, 16);
          advance(0); await flush();
          advance(2500); await flush();
          var first = locates();
          advance(100);
          streetPick(-81.70, 28.05, 16);
          advance(0); await flush();
          var soon = locates();
          advance(899); await flush();
          var held = [locates(), S.street.finding];
          advance(1); await flush();
          console.log(JSON.stringify({first: first, soon: soon, held: held, then: locates(), label: S.street.label}));
        """)
        self.assertEqual(got["first"], [-81.73])
        self.assertEqual(got["soon"], [-81.73])
        self.assertEqual(got["held"], [[-81.73], True])
        self.assertEqual(got["then"], [-81.73, -81.7])
        self.assertEqual(got["label"], "Windham Loop, 40.58N 74.16W")

    def test_find_the_street_asks_again_and_goes_to_the_street_it_is_given(self):
        got = _run(self, r"""
          route("routed-car/nearest", 503);
          route("valhalla1.openstreetmap.de/locate", 503);
          streetPick(-81.73, 27.9997, 16);
          advance(0); await flush();
          var lost = [S.street.lon, S.street.lat, $("street-find").hidden,
                      ASKED.filter(function (u) { return /routed-car|locate/.test(u); }).length];
          route("routed-car/nearest", """ + json.dumps(ROADS_WH) + r""");
          var focused = [];
          $("street-stage").focus = function () { focused.push("street-stage"); };
          document.activeElement = $("street-find");
          $("street-find").fire("click");
          var finding = [S.street.finding, $("street-find").hidden, focused];
          advance(1000); await flush();
          console.log(JSON.stringify({lost: lost, finding: finding,
            found: [S.street.lon, S.street.lat, S.street.label, $("street-find").hidden, $("street-next").hidden],
            again: ASKED.filter(function (u) { return u.indexOf("routed-car") >= 0; }).length}));
        """)
        self.assertEqual(got["lost"], [-81.73, 27.9997, False, 2])
        self.assertEqual(got["finding"], [True, True, ["street-stage"]])
        self.assertEqual(got["found"], [-81.729659, 27.989109, "Hoover Road, 27.99N 81.73W", True, False])
        self.assertEqual(got["again"], 2)
        # An exact point, or a street found, has nothing to find again.
        got = _run(self, LIMA + r"""
          console.log(JSON.stringify([$("street-find").hidden, streetFind()]));
        """)
        self.assertEqual(got, [True, False])

    def test_six_streets_at_most_and_none_for_an_exact_point(self):
        many = {"code": "Ok", "waypoints": [{"location": [-81.73 + i / 1000, 28.0], "name": "Road %d" % i,
                                             "distance": 50 + 100 * i} for i in range(9)]}
        got = _run(self, r"""
          route("routed-car/nearest", """ + json.dumps(many) + r""");
          streetPick(-81.73, 28.0, 16);
          advance(0); await flush();
          var listed = S.street.roads.map(function (r) { return r.point ? "*" : r.name; });
          // An address, the page's API and a street kept across a load open
          // exactly where they say, with nothing to go down.
          streetHashApply("#street=28.10000,-81.70000");
          var linked = [S.street.roads, $("street-next").hidden, $("street-roads").textContent, streetNext()];
          console.log(JSON.stringify([listed, linked]));
        """)
        self.assertEqual(got, [["Road 0", "Road 1", "Road 2", "Road 3", "Road 4", "Road 5", "*"],
                               [None, True, "", False]])

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
        # The replay, open, tells its years apart again by the new run's index.
        self.assertIn("if (S.sim) simRetake();", _js_function(js, "takeRun"))

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
# 9 October 2026, the seven of October's run the page asks for (April's as it
# answered on the 12th, its other months the same) (Jakarta's sea surface made
# up, as at a point offshore), and Lima's weather that morning, its hours of
# rain made up.
_MONTHS_AHEAD = ["2026-10-01", "2026-11-01", "2026-12-01", "2027-01-01", "2027-02-01", "2027-03-01", "2027-04-01"]
AHEAD_LIMA = {"monthly": {"time": _MONTHS_AHEAD,
                          "temperature_2m_anomaly": [3.7, 4.3, 4.1, 3.7, 3.4, 3.4, 3.5],
                          "precipitation_mean": [4.7, 12.5, 20.4, 30.6, 20.9, 20.2, 9.0],
                          "precipitation_anomaly": [3.2, 10.4, 16.0, 21.4, 9.6, 7.7, 1.2],
                          "sea_surface_temperature_anomaly": [None] * 7}}
AHEAD_JAKARTA = {"monthly": {"time": _MONTHS_AHEAD,
                             "temperature_2m_anomaly": [1.5, 1.8, 1.3, 1.5, 1.5, 1.5, 1.5],
                             "precipitation_mean": [47.1, 149.9, 292.6, 337.0, 292.2, 307.7, 255.5],
                             "precipitation_anomaly": [-80.1, -76.0, 40.5, 66.8, 41.3, 49.7, 50.6],
                             "sea_surface_temperature_anomaly": [0.6, 0.5, 0.4, 0.4, 0.3, 0.3, 0.3]}}
# ECMWF's months as Open-Meteo would answer at the replay's clock, noon on 29
# September 2026: September's run, seven months from September (Jakarta's
# October to March, September's made up).
_JAKARTA = AHEAD_JAKARTA["monthly"]
AHEAD_SEPTEMBER = {"monthly": {"time": ["2026-09-01"] + _JAKARTA["time"][:6],
                               "temperature_2m_anomaly": [1.4] + _JAKARTA["temperature_2m_anomaly"][:6],
                               "precipitation_mean": [60.2] + _JAKARTA["precipitation_mean"][:6],
                               "precipitation_anomaly": [-61.0] + _JAKARTA["precipitation_anomaly"][:6],
                               "sea_surface_temperature_anomaly": [0.6] + _JAKARTA["sea_surface_temperature_anomaly"][:6]}}
# Valhalla's locate at Staten Island on 14 October 2026: the roads it gave,
# two directions of Windham Loop at the point, Rumson Road 78 m off and an
# unnamed road, and one whose position cannot be read; a road of a class
# under residential is not asked for.
LOCATE_SI = [{"input_lat": 40.577058, "input_lon": -74.161517, "edges": [
    {"correlated_lat": 40.577058, "correlated_lon": -74.161517, "distance": 0.0,
     "edge_info": {"names": ["Windham Loop"]}},
    {"correlated_lat": 40.577058, "correlated_lon": -74.161517, "distance": 0.0,
     "edge_info": {"names": ["Windham Loop"]}},
    {"correlated_lat": 40.576674, "correlated_lon": -74.160746, "distance": 78.0,
     "edge_info": {"names": ["Rumson Road"]}},
    {"correlated_lat": 40.5771, "correlated_lon": -74.1622, "distance": 60.0, "edge_info": {}},
    {"correlated_lat": "x", "correlated_lon": -74.1622, "distance": 1.0, "edge_info": {"names": ["Bad"]}}]}]

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
        self.assertEqual(got, {"calls": 1, "same": True, "again": 7, "stored": ["elnino-street-1:ahead|-12.05,-77.04"],
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
        self.assertEqual([r["sst"] for r in lima], [None] * 7)
        self.assertEqual(jakarta[0]["sst"], 0.6)
        self.assertEqual((holed[5]["rain"], holed[5]["normal"], holed[5]["percent"]), (None, None, None))
        self.assertAlmostEqual(holed[5]["anom"], 7.7 / 31)

    def test_the_card_gives_ecmwf_s_six_months_from_the_reader_s(self):
        # Seven months asked for, from the month the run was made in: the card
        # gives six from the reader's - on 2 November, before November's run
        # is out, October's from November on.
        body = "return streetAheadHtml(INPUT.state, seasonalRows(INPUT.ahead));"
        october = self.run_js(body, state=self.state(), ahead=AHEAD_LIMA)
        november = self.run_js(body, state=self.state(), ahead=AHEAD_LIMA, at="2026-11-02T09:00:00Z")
        self.assertEqual(re.findall(r'<th scope="row">([^<]*)</th>', october),
                         ["Oct 2026", "Nov 2026", "Dec 2026", "Jan 2027", "Feb 2027", "Mar 2027"])
        self.assertEqual(re.findall(r'<th scope="row">([^<]*)</th>', november),
                         ["Nov 2026", "Dec 2026", "Jan 2027", "Feb 2027", "Mar 2027", "Apr 2027"])
        self.assertIn("<h4>The next six months, ECMWF</h4>", october)

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
        self.assertEqual([got["card"], got["calls"], got["again"]], ["string", 1, 7])

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
        self.assertEqual(got, [1, 0, 7])

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


# POWER's daily record as its CSV comes, header and all, as it answered for
# Winter Haven on 12 October 2026, cut to a few days: the third day missing,
# a temperature and a rainfall filled, and the last day nothing but fills.
POWER_CSV = (
    "-BEGIN HEADER-\n"
    "NASA/POWER Source Native Resolution Daily Data \n"
    "Dates (month/day/year): 01/01/1981 through 01/06/1981 in LST\n"
    "Location: latitude  28.02   longitude -81.73 \n"
    "The value for missing source data that cannot be computed or is outside of the sources availability "
    "range: -999 \n"
    "parameter(s): \n"
    "PRECTOTCORR     MERRA-2 Precipitation Corrected (mm/day) \n"
    "T2M             MERRA-2 Temperature at 2 Meters (C) \n"
    "-END HEADER-\n"
    "YEAR,DOY,PRECTOTCORR,T2M\n"
    "1981,1,0.01,11.68\n"
    "1981,2,0.0,9.2\n"
    "1981,4,25.5,-999.0\n"
    "1981,5,-999.0,12.25\n"
    "1981,6,-999.0,-999.0\n")


# A point's days and the index, 1981 to 1990, made so that every number the
# replay gives can be worked out by hand. The index is neutral (0.0) but for
# El Ninos in NDJ 1982-83 (peaking +2.2) and 1987-88 (+1.1 in November
# alone), a La Nina in NDJ 1988-89, a warm-neutral November 1984 (+0.6), and
# an El Nino under way from June 1990 to the record's end. It rains 1 mm a
# day, 20 deg C; in the two El Ninos' November to April, 3 mm a day, 25 mm on
# each month's first, at 18 deg C. 15 March 1983 is missing, 1 to 7 December
# 1986 too, and 5 to 24 January 1986 is dry.
REPLAY_SETUP = r"""
  var DAY = 86400000, index = [];
  for (var y = 1981; y <= 1990; y++) for (var m = 1; m <= 12; m++) {
    var v = 0.0, key = y + "-" + pad2(m);
    if (key === "1982-11") v = 2.0; else if (key === "1982-12") v = 2.2; else if (key === "1983-01") v = 2.1;
    else if (key === "1987-11") v = 1.1; else if (key === "1987-12") v = 0.9; else if (key === "1988-01") v = 0.7;
    else if (key >= "1988-11" && key <= "1989-01") v = -1.5;
    else if (key === "1984-11") v = 0.6;
    else if (key >= "1990-06") v = 0.6 + (m - 6) / 10;
    index.push(v);
  }
  D.street = Object.assign({}, D.street, {months: {from: "1981-01", values: index}});
  function warmDay(d) {
    var y = d.getUTCFullYear(), m = d.getUTCMonth() + 1, tag = m >= 11 ? y : y - 1;
    return (tag === 1982 || tag === 1987) && (m >= 11 || m <= 4);
  }
  var REC = {from: "1981-01-01", p: [], t: []};
  for (var ms = Date.UTC(1981, 0, 1); ms < Date.UTC(1991, 0, 1); ms += DAY) {
    var d = new Date(ms), iso = d.toISOString().slice(0, 10), warm = warmDay(d);
    var p = warm ? (d.getUTCDate() === 1 ? 25 : 3) : 1;
    if (iso === "1983-03-15" || (iso >= "1986-12-01" && iso <= "1986-12-07")) p = null;
    if (iso >= "1986-01-05" && iso <= "1986-01-24") p = 0;
    REC.p.push(p);
    REC.t.push(warm ? 18 : 20);
  }
  function brief(r) {
    return r && {tag: r.tag, label: r.label, days: r.p.length, total: Math.round(r.total * 1000) / 1000, r20: r.r20,
                 wettest: r.wettest, dry: r.dry, tmean: r.tmean, missing: r.missing, partial: r.partial,
                 peak: r.peak === undefined ? null : r.peak};
  }
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestStreetReplayRuns(unittest.TestCase):
    """El Nino's rain replayed on the street, run under node as the page runs
    it: POWER's days read and kept, the replay's model, its panel and the rain
    drawn over the panorama."""

    def test_the_rain_s_level_follows_the_day_s_rain_and_snows_at_or_below_freezing(self):
        got = _run(self, r"""
          console.log(JSON.stringify([[null, 20], [0.49, 20], [0.5, 20], [12.5, 20], [50, 20], [200, 20],
                                      [12.5, 0], [12.5, 0.1], [12.5, null], [0, -5]].map(function (d) {
            return rainLevel(d[0], d[1]);
          })));
        """)
        none = {"kind": "none", "drops": 0, "gloom": 0, "speed": 0}
        dry = {"kind": "dry", "drops": 0, "gloom": 0, "speed": 0}
        self.assertEqual(got, [
            none, dry,
            # From half a millimetre, a strength s, the root of the rain
            # against 50 mm, up to 1: 20 + 380 s streaks falling 1 + 1.2 s of
            # the view a second, and the sky dimmed by 0.08 + 0.3 s.
            {"kind": "rain", "drops": 58, "gloom": 0.11, "speed": 1.12},
            {"kind": "rain", "drops": 210, "gloom": 0.23, "speed": 1.6},
            {"kind": "rain", "drops": 400, "gloom": 0.38, "speed": 2.2},
            {"kind": "rain", "drops": 400, "gloom": 0.38, "speed": 2.2},
            # At or below 0 deg C, 30 + 270 s flakes, falling 0.12 + 0.12 s.
            {"kind": "snow", "drops": 165, "gloom": 0.23, "speed": 0.18},
            {"kind": "rain", "drops": 210, "gloom": 0.23, "speed": 1.6},
            {"kind": "rain", "drops": 210, "gloom": 0.23, "speed": 1.6},
            dry])

    def test_power_s_days_are_read_from_its_csv(self):
        got = _run(self, "console.log(JSON.stringify(powerCsv(" + json.dumps(POWER_CSV) + ")));")
        # Day by day from the first, the missing day and the fills null, the
        # days after the last with a value left off.
        self.assertEqual(got, {"from": "1981-01-01", "p": [0.01, 0, None, 25.5, None],
                               "t": [11.68, 9.2, None, None, 12.25]})

    def test_power_s_days_by_month_and_day_and_in_another_order(self):
        csv = ("-BEGIN HEADER-\n-END HEADER-\r\n"
               "YEAR,MO,DY,T2M,PRECTOTCORR\r\n"
               "2015,12,31,20.5,1.25\r\n"
               "2016,1,1,19.0,0.0\r\n"
               "2016,2,30,1,1\r\n"
               "2015,13,1,1,1\r\n"
               "abc,1,2,1,1\r\n"
               "2016,1,2,x,-0.5\r\n"
               "2016,1,3,18.0,3.5\r\n"
               "2016,1,4,,\r\n"
               "\r\n")
        got = _run(self, "console.log(JSON.stringify(powerCsv(" + json.dumps(csv) + ")));")
        # 30 February, a thirteenth month and a year that is not one are not
        # days; what is not a number, or a rainfall under nothing, is no value.
        self.assertEqual(got, {"from": "2015-12-31", "p": [1.25, 0, None, 3.5], "t": [20.5, 19, None, 18]})

    def test_power_s_days_with_columns_before_the_year(self):
        csv = ("-BEGIN HEADER-\n-END HEADER-\n"
               "LAT,LON,YEAR,DOY,T2M,PRECTOTCORR\n"
               "28.0,-81.875,1981,1,11.68,0.01\n"
               "28.0,-81.875,1981,2,9.2,0.0\n")
        got = _run(self, "console.log(JSON.stringify(powerCsv(" + json.dumps(csv) + ")));")
        self.assertEqual(got, {"from": "1981-01-01", "p": [0.01, 0], "t": [11.68, 9.2]})

    def test_an_answer_that_is_not_power_s_days_is_no_record(self):
        answers = ["<html><body>Service Unavailable</body></html>", "", None, 42,
                   "-BEGIN HEADER-\n-END HEADER-\nYEAR,DOY,T2M\n1981,1,12.0\n",
                   "YEAR,PRECTOTCORR,T2M\n1981,1.0,12.0\n",
                   "YEAR,DOY,PRECTOTCORR,T2M\n",
                   "YEAR,DOY,PRECTOTCORR,T2M\n1981,366,1.0,12.0\n1981,0,1.0,12.0\n1981,1,-999,-999\n"]
        got = _run(self, "console.log(JSON.stringify(" + json.dumps(answers) + ".map(powerCsv)));")
        self.assertEqual(got, [None] * len(answers))

    def test_power_s_cell_is_merra_2_s_grid_point_nearest_the_place(self):
        got = _run(self, r"""
          console.log(JSON.stringify([[-81.73, 28.24], [-81.73, 28.26], [-81.73, 28.49], [-81.73, 28.51],
                                      [-81.55, 28.02], [-81.57, 28.02], [-81.24, 28.02], [-81.26, 28.02],
                                      [179.9, -0.1], [-180, 0], [540.2, 45.2]].map(function (p) {
            return simCell(p[0], p[1]);
          })));
        """)
        # POWER answered differently either side of 28.25 N and of 81.5625 W
        # on 12 October 2026, and alike either side of 28.5 N and of 81.25 W:
        # each cell is about its grid point.
        self.assertEqual([[c["lon"], c["lat"]] for c in got], [
            ["-81.875", "28.0"], ["-81.875", "28.5"], ["-81.875", "28.5"], ["-81.875", "28.5"],
            ["-81.250", "28.0"], ["-81.875", "28.0"], ["-81.250", "28.0"], ["-81.250", "28.0"],
            ["-180.000", "0.0"], ["-180.000", "0.0"], ["-180.000", "45.0"]])
        self.assertEqual(got[0]["key"], "days|28.0,-81.875")

    def test_the_days_are_asked_once_a_cell_kept_for_three_cells_and_a_failure_said(self):
        got = _run(self, r"""
          route("format=CSV", """ + json.dumps(POWER_CSV) + r""");
          function asked() { return ASKED.filter(function (u) { return u.indexOf("format=CSV") >= 0; }); }
          var a = simGet(-81.73, 28.02), b = simGet(-81.70, 28.05), same = a === b, rec = await a;
          var first = asked();
          await simGet(-81, 28); await simGet(-80, 28); await simGet(-79, 28);
          var kept = Object.keys(SIM_KEPT).sort();
          await simGet(-81.73, 28.02);
          route("longitude=-70.000", 503);
          var why = null;
          try { await simGet(-70, 28); } catch (err) { why = err.why; }
          console.log(JSON.stringify({same: same, from: rec.from, first: first, kept: kept, n: asked().length, why: why,
                                      said: SIM_WHY["days|28.0,-70.000"], left: Object.keys(SIM_ASKED)}));
        """)
        # Two places 5 km apart in one cell: one request, for its grid point,
        # so POWER is sent no closer a position than the cell's.
        self.assertTrue(got["same"])
        self.assertEqual(got["from"], "1981-01-01")
        self.assertEqual(got["first"], ["https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR,"
                                        "T2M&community=AG&longitude=-81.875&latitude=28.0&start=19810101&end=20260929"
                                        "&format=CSV"])
        # The last three cells kept; the first, asked again, is asked again:
        # five answers, and the one that failed.
        self.assertEqual(got["kept"], ["days|28.0,-78.750", "days|28.0,-80.000", "days|28.0,-81.250"])
        self.assertEqual(got["n"], 6)
        self.assertEqual([got["why"], got["said"], got["left"]], ["answered 503", "answered 503", []])

    def test_a_window_is_six_months_from_its_first_named_as_the_site_names_an_episode(self):
        got = _run(self, r"""
          console.log(JSON.stringify([[11, 1997], [12, 2015], [1, 1998], [7, 1999], [8, 1999]].map(function (a) {
            var w = simWindow(a[0], a[1]);
            return [new Date(w.first).toISOString().slice(0, 10), new Date(w.end).toISOString().slice(0, 10), w.days,
                    w.months, w.label];
          })));
        """)
        self.assertEqual(got, [
            ["1997-11-01", "1998-05-01", 181, ["1997-11", "1997-12", "1998-01", "1998-02", "1998-03", "1998-04"],
             "1997-98"],
            # Across the new year, 29 February 2016 in it.
            ["2015-12-01", "2016-06-01", 183, ["2015-12", "2016-01", "2016-02", "2016-03", "2016-04", "2016-05"],
             "2015-16"],
            ["1998-01-01", "1998-07-01", 181, ["1998-01", "1998-02", "1998-03", "1998-04", "1998-05", "1998-06"], "1998"],
            ["1999-07-01", "2000-01-01", 184, ["1999-07", "1999-08", "1999-09", "1999-10", "1999-11", "1999-12"], "1999"],
            ["1999-08-01", "2000-02-01", 184, ["1999-08", "1999-09", "1999-10", "1999-11", "1999-12", "2000-01"],
             "1999-00"]])

    def test_a_window_s_days_and_what_they_come_to(self):
        got = _run(self, REPLAY_SETUP + r"""
          var r = simRun(REC, 11, 1982);
          console.log(JSON.stringify([brief(r), r.cum.slice(0, 3), r.cum[180], r.p[0], r.p[134],
                                      brief(simRun(REC, 11, 1985)), brief(simRun(REC, 11, 1986)),
                                      simRun(REC, 11, 1990), simRun(REC, 11, 1980)]));
        """)
        el_nino, cum, last, first_day, missing_day, dry, gappy, past_end, before = got
        # 174 days of 3 mm, six firsts of 25 and 15 March missing, counted
        # dry: 672 mm; the wettest day the first, 1 November 1982.
        self.assertEqual(el_nino, {"tag": 1982, "label": "1982-83", "days": 181, "total": 672, "r20": 6,
                                   "wettest": {"mm": 25, "day": 0}, "dry": 1, "tmean": 18, "missing": 1,
                                   "partial": False, "peak": None})
        self.assertEqual([cum, last, first_day, missing_day], [[25, 28, 31], 672, 25, None])
        # Twenty days without rain in January 1986.
        self.assertEqual(dry, {"tag": 1985, "label": "1985-86", "days": 181, "total": 161, "r20": 0,
                               "wettest": {"mm": 1, "day": 0}, "dry": 20, "tmean": 20, "missing": 0,
                               "partial": False, "peak": None})
        # Seven days missing are too many; a window past the record's end, or
        # before its start, is none.
        self.assertEqual([gappy, past_end, before], [None, None, None])

    def test_el_ninos_and_neutral_years_are_told_by_the_index_in_the_window_s_first_season(self):
        got = _run(self, REPLAY_SETUP + r"""
          var y = simYears(REC, 11, Date.UTC(2026, 8, 29));
          console.log(JSON.stringify({events: y.events.map(brief), neutral: y.neutral.map(function (r) { return r.tag; }),
                                      now: y.now}));
        """)
        # Newest first, each with the index's peak in NDJ; La Nina, the warm
        # November and the event under way are neither; 1986-87 has too many
        # days missing; 1990-91 runs past the record.
        self.assertEqual([e["tag"] for e in got["events"]], [1987, 1982])
        self.assertEqual([e["peak"] for e in got["events"]], [1.1, 2.2])
        self.assertEqual(got["events"][0], {"tag": 1987, "label": "1987-88", "days": 182, "total": 678, "r20": 6,
                                            "wettest": {"mm": 25, "day": 0}, "dry": 0, "tmean": 18, "missing": 0,
                                            "partial": False, "peak": 1.1})
        self.assertEqual(got["neutral"], [1981, 1983, 1985, 1989])
        self.assertIsNone(got["now"])

    def test_this_year_so_far_is_the_window_under_way(self):
        got = _run(self, REPLAY_SETUP + r"""
          var at = Date.UTC(1991, 0, 20), y = simYears(REC, 11, at), z = simYears(REC, 11, Date.UTC(1990, 10, 6));
          console.log(JSON.stringify([brief(y.now), y.now.cum.length, brief(z.now),
                                      y.events.map(function (r) { return r.tag; })]));
        """)
        # On 20 January 1991 the window from November 1990 is under way: its
        # days to the record's last; the El Nino under way is not among the
        # past ones. Five days in, it is too soon.
        self.assertEqual(got[0], {"tag": 1990, "label": "1990-91", "days": 61, "total": 61, "r20": 0,
                                  "wettest": {"mm": 1, "day": 0}, "dry": 0, "tmean": 20, "missing": 0,
                                  "partial": True, "peak": None})
        self.assertEqual(got[1:], [61, None, [1987, 1982]])

    def test_a_window_ended_inside_the_el_nino_under_way_is_this_year_s(self):
        got = _run(self, REPLAY_SETUP + r"""
          var y = simYears(REC, 6, Date.UTC(1991, 0, 20));
          console.log(JSON.stringify([brief(y.now), y.events.length, y.neutral.length]));
        """)
        # June to November 1990 has ended, its first season inside the El Nino
        # under way since June: not a past El Nino, nor gone, but this year's,
        # whole.
        self.assertEqual(got, [{"tag": 1990, "label": "1990", "days": 183, "total": 183, "r20": 0,
                                "wettest": {"mm": 1, "day": 0}, "dry": 0, "tmean": 20, "missing": 0,
                                "partial": False, "peak": None}, 0, 9])

    def test_the_neutral_band_is_their_mean_and_10th_to_90th_percentiles_date_by_date(self):
        got = _run(self, REPLAY_SETUP + r"""
          var y = simYears(REC, 11, Date.UTC(2026, 8, 29)), b = simBand(y.neutral);
          function at(k) { return [b.mean[k], b.lo[k], b.hi[k]].map(function (v) { return Math.round(v * 1000) / 1000; }); }
          console.log(JSON.stringify([b.mean.length, at(0), at(119), at(180)]));
        """)
        # The four years lined up date by date, 29 February counted with the
        # 28th: as many days as a year without it has, 181. On 28 February,
        # 120, 121 (1984's 29th with it), 100 (twenty dry days in January
        # 1986) and 120: the 10th percentile 0.3 of the way from 100 to 120.
        # On the last day their totals, 181, 182, 161 and 181: their mean the
        # neutral years' mean.
        self.assertEqual(got, [181, [1, 1, 1], [115.25, 106, 120.7], [176.25, 167, 181.7]])

    def test_the_band_s_last_day_is_the_neutral_totals_in_windows_of_182_and_183_days(self):
        got = _run(self, REPLAY_SETUP + r"""
          var m = simModel(REC, 12, null, Date.UTC(2026, 8, 29));
          function on(first, k) {
            var b = simBandOn(m, first, k);
            return [b.mean, b.lo, b.hi].map(function (v) { return Math.round(v * 1000) / 1000; });
          }
          var leap = Date.UTC(2015, 11, 1), plain = Date.UTC(2014, 11, 1);
          console.log(JSON.stringify([m.neutral.map(function (r) { return [r.tag, r.p.length, r.total]; }), m.base.total,
                                      on(leap, 182), on(plain, 181), on(leap, 89), on(leap, 90), on(plain, 89),
                                      on(leap, 91), on(plain, 90), simBandOn(m, leap, 183)]));
        """)
        neutral, mean, leap_end, plain_end, feb28, feb29, plain_feb28, mar1, plain_mar1, past = got
        # December to May: 1983-84's has 29 February in it, 183 days, the
        # others 182.
        self.assertEqual(neutral, [[1981, 182, 182], [1983, 183, 183], [1984, 182, 182], [1985, 182, 162],
                                   [1989, 182, 182]])
        # On 31 May, the last day of a window of 183 days or of 182, the
        # neutral years' totals: their mean, 178.2, and percentiles.
        self.assertEqual(mean, 178.2)
        self.assertEqual(leap_end, [178.2, 170, 182.6])
        self.assertEqual(plain_end, leap_end)
        # 29 February counted with the 28th; from 1 March, date by date.
        self.assertEqual([feb29, plain_feb28], [feb28, feb28])
        self.assertEqual(mar1, plain_mar1)
        self.assertIsNone(past)

    def test_the_point_s_climate_is_each_calendar_month_s_mean_over_its_complete_years(self):
        got = _run(self, REPLAY_SETUP + r"""
          var c = simClimate(REC);
          console.log(JSON.stringify(c.map(function (v) { return v === null ? null : Math.round(v * 1000) / 1000; })));
        """)
        # November: 112 mm in the two El Ninos, 30 in the other eight.
        # December 1986 has days missing: nine Decembers, two of 115.
        self.assertEqual(got[10], 46.4)
        self.assertEqual(got[11], round(447 / 9, 3))
        self.assertEqual(got[5], 30)

    def test_ecmwf_s_projection_scales_the_climate_by_its_forecast_or_adds_its_anomaly_where_dry(self):
        got = _run(self, REPLAY_SETUP + r"""
          var rows = [{month: "1990-11", days: 30, anom: 1.0, percent: 50}, {month: "1990-12", days: 31, anom: -10.0, percent: null},
                      {month: "1991-01", days: 31, anom: null, percent: null}, {month: "1991-02", days: 28, anom: 1.0, percent: 50}];
          var clim = simClimate(REC), at = Date.UTC(1990, 9, 15), e = simEcmwf(rows, 11, clim, at);
          function r(v) { return Math.round(v * 1000) / 1000; }
          console.log(JSON.stringify([e.label, e.months, e.cum.length, r(e.cum[0]), r(e.cum[29]), r(e.cum[60]), r(e.total),
                                      r(e.base), simEcmwf(rows, 11, clim, Date.UTC(1990, 10, 2)),
                                      simEcmwf([], 11, clim, at)]));
        """)
        # November: the point's 46.4 mm and half as much again, as the model
        # forecasts 50% over its normal; December's normal is under the dry
        # floor, so its anomaly is added: 49.7 less 310, held at nothing.
        # January has no anomaly, so the projection stops there. A window
        # begun has none, and so has a forecast without its months.
        self.assertEqual(got, ["1990-91", ["1990-11", "1990-12"], 61, round(69.6 / 30, 3), 69.6, 69.6, 69.6,
                               round(46.4 + 447 / 9, 3), None, None])

    def test_the_model_gathers_the_window_s_years_the_neutral_means_and_the_strongest_event(self):
        got = _run(self, REPLAY_SETUP + r"""
          var mdl = simModel(REC, 11, null, Date.UTC(2026, 8, 29));
          console.log(JSON.stringify([mdl.start, mdl.words, mdl.strongest, mdl.events.length, mdl.neutral.length,
                                      mdl.base, mdl.ecmwf, mdl.band.mean.length]));
        """)
        # The band as many days long as November to April without 29 February.
        self.assertEqual(got, [11, "November to April", 1982, 2, 4,
                               {"total": 176.25, "r20": 0, "dry": 5, "tmean": 20, "years": 4}, None, 181])

    def test_days_that_are_not_power_s_are_said_to_be_nothing_for_the_point(self):
        got = _run(self, r"""
          route("format=CSV", "<html>Maintenance</html>");
          var why = null;
          try { await simGet(-81.73, 28.02); } catch (err) { why = err.why; }
          console.log(JSON.stringify([why, Object.keys(SIM_KEPT)]));
        """)
        self.assertEqual(got, ["has nothing for this point", []])


# OSRM's answer for a pick by the edge of two of POWER's cells, 81.5625 W:
# the nearest named road in the western cell, the next in the eastern.
ROADS_EDGE = {"code": "Ok", "waypoints": [
    {"location": [-81.5652, 28.0201], "name": "West Road", "distance": 20.0},
    {"location": [-81.5600, 28.0200], "name": "East Road", "distance": 500.0}]}

# The replay's panel on Winter Haven, its record REPLAY_SETUP's as POWER's
# CSV gives it. At noon on 29 September 2026 the window is October to March:
# 1982-83 the stronger of its two El Ninos, beside four neutral years.
PANEL_SETUP = REPLAY_SETUP + r"""
  function csvOf(rec, plus) {
    var lines = ["-BEGIN HEADER-", "-END HEADER-", "YEAR,DOY,PRECTOTCORR,T2M"], from = Date.parse(rec.from + "T00:00:00Z");
    rec.p.forEach(function (p, i) {
      var d = new Date(from + i * DAY), y = d.getUTCFullYear(), doy = Math.round((d - Date.UTC(y, 0, 1)) / DAY) + 1;
      lines.push(y + "," + doy + "," + (p === null ? -999 : p + (plus || 0)) + "," + rec.t[i]);
    });
    return lines.join("\n") + "\n";
  }
  var CSV = csvOf(REC);
  route("format=CSV", CSV);
  streetEnter(-81.73, 28.02, "Winter Haven");
  function csvAsked() { return ASKED.filter(function (u) { return u.indexOf("format=CSV") >= 0; }); }
"""
LOADING = "Reading NASA POWER\u2019s days for this place, every one since 1981\u2026"

# The rain's canvas with a 2D context that notes what is drawn on it; the
# replay's frames among those asked for; and how often a thing was drawn.
RAIN_CTX = r"""
  var OPS = [];
  var CTX = {setTransform: function () {}, clearRect: function () { OPS.push("clear"); },
             fillRect: function () { OPS.push("dim"); }, beginPath: function () {},
             moveTo: function () { OPS.push("drop"); }, lineTo: function () {}, arc: function () {},
             stroke: function () { OPS.push("stroke"); }, fill: function () { OPS.push("fill"); }};
  $("street-rain").getContext = function (kind) { return kind === "2d" ? CTX : null; };
  function ticking() { return FRAMES.filter(function (t) { return t.f === simTick; }).length; }
  function count(op) { return OPS.filter(function (o) { return o === op; }).length; }
"""


def table_rows(markup: str) -> list:
    """A table's rows, each a list of its cells' words."""
    return [[re.sub(r"<[^>]+>", "", c) for c in re.findall(r"<t[hd][^>]*>(.*?)</t[hd]>", r)]
            for r in re.findall(r"<tr[^>]*>(.*?)</tr>", markup)]


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestStreetReplayPanelRuns(unittest.TestCase):
    """The replay's panel in the stage's chip, run under node as the page runs
    it: opened, chosen, played, sought, said, failed, closed and moved."""

    def test_the_replay_opens_in_the_chip_s_place_and_asks_power_once_for_the_cell(self):
        got = _run(self, PANEL_SETUP + r"""
          function shown() {
            return [$("street-sim").hidden, $("street-chip-head").hidden, $("street-chip-said").hidden,
                    $("street-sim-credit").hidden, $("street-stage").classList.contains("simon")];
          }
          var before = shown();
          $("street-replay").fire("click");
          var asking = [shown(), $("street-sim-said").innerHTML, $("street-sim-play").disabled,
                        $("street-sim-event").disabled, $("street-sim-day").disabled];
          await flush();
          var open = [shown(), $("street-sim-play").disabled, $("street-sim-event").disabled, $("street-sim-day").disabled];
          simOpen();
          streetEnter(-81.70, 28.05, "Nearby");
          await flush();
          console.log(JSON.stringify({before: before, asking: asking, open: open, asked: csvAsked(), key: S.sim.key,
                                      model: !!S.sim.model}));
        """)
        self.assertEqual(got["before"], [True, False, False, True, False])
        self.assertEqual(got["asking"], [[False, True, True, False, True], LOADING, True, True, True])
        self.assertEqual(got["open"], [[False, True, True, False, True], False, False, False])
        # Asked once, for MERRA-2's grid point nearest the place; opened again,
        # or moved within the cell, it asks nothing more.
        self.assertEqual(got["asked"], ["https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR,"
                                        "T2M&community=AG&longitude=-81.875&latitude=28.0&start=19810101&end=20260929"
                                        "&format=CSV"])
        self.assertEqual([got["key"], got["model"]], ["days|28.0,-81.875", True])

    def test_the_choices_are_the_el_ninos_newest_first_the_strongest_chosen_from_next_month(self):
        got = _run(self, PANEL_SETUP + r"""
          simOpen();
          await flush();
          var first = [$("street-sim-event").innerHTML, $("street-sim-event").value, $("street-sim-start").value,
                       $("street-sim-speed").value, $("street-sim-day").max, $("street-sim-day").value, S.sim.model.words];
          $("street-sim-start").value = "11";
          $("street-sim-start").fire("change");
          var nov = [$("street-sim-event").value, $("street-sim-day").max, S.sim.model.words];
          $("street-sim-event").value = "1987";
          $("street-sim-event").fire("change");
          console.log(JSON.stringify({first: first, nov: nov, chosen: [S.sim.tag, $("street-sim-day").max]}));
        """)
        # On 29 September, the six months from October; each El Nino with the
        # index's peak in October to December, 1982-83 the strongest.
        self.assertEqual(got["first"], ['<option value="1987">1987-88 (+1.1)</option>'
                                        '<option value="1982">1982-83 (+2.2)</option>',
                                        "1982", "10", "7", "181", "0", "October to March"])
        self.assertEqual(got["nov"], ["1982", "180", "November to April"])
        # 1987-88's November to April has 29 February in it.
        self.assertEqual(got["chosen"], ["1987", "181"])

    def test_play_steps_the_days_at_the_speed_chosen_and_stops_at_the_end(self):
        got = _run(self, PANEL_SETUP + r"""
          simOpen();
          await flush();
          var play = $("street-sim-play");
          play.fire("click");
          var on = [S.sim.playing, play.textContent, play.getAttribute("aria-pressed"), FRAMES.length];
          frames(125, 1);
          frames(125, 8);
          var week = S.sim.day;
          frames(5000, 1);
          var held = S.sim.day;
          $("street-sim-speed").value = "30";
          $("street-sim-speed").fire("change");
          frames(125, 8);
          var month = S.sim.day;
          frames(125, 100);
          var end = [S.sim.day, S.sim.playing, play.textContent, play.getAttribute("aria-pressed"), FRAMES.length];
          play.fire("click");
          var again = [S.sim.day, S.sim.playing];
          play.fire("click");
          console.log(JSON.stringify({on: on, week: week, held: held, month: month, end: end, again: again,
                                      paused: [S.sim.playing, FRAMES.length]}));
        """)
        self.assertEqual(got["on"], [True, "Pause", None, 1])
        # A week a second; a frame held back (a tab in the background) counts
        # a quarter of a second at most; then a month a second.
        self.assertEqual([got["week"], got["held"], got["month"]], [7, 8, 38])
        # Stopped on the last day, whose rain still falls: its frames go on.
        self.assertEqual(got["end"], [181, False, "Play", None, 1])
        # Played again from the last day, it starts over.
        self.assertEqual(got["again"], [0, True])
        self.assertEqual(got["paused"], [False, 1])

    def test_the_slider_and_the_chart_seek_the_day(self):
        got = _run(self, PANEL_SETUP + r"""
          simOpen();
          await flush();
          var slider = $("street-sim-day"), chart = $("street-sim-chart"), out = [];
          slider.value = "40";
          slider.fire("input");
          out.push([S.sim.day, slider.getAttribute("aria-valuetext")]);
          chart.fire("pointerdown", {clientX: 36, pointerId: 1});
          out.push(S.sim.day);
          chart.fire("pointermove", {clientX: 386, pointerId: 1});
          out.push(S.sim.day);
          chart.fire("pointerup", {pointerId: 1});
          chart.fire("pointermove", {clientX: 600, pointerId: 1});
          out.push(S.sim.day);
          chart.fire("pointerdown", {clientX: 5000, pointerId: 2});
          out.push([S.sim.day, S.sim.pos]);
          console.log(JSON.stringify(out));
        """)
        # 10 November 1982, a day of 3 mm in the El Nino's months. The chart,
        # 800 px across with 36 for its scale and 66 for its labels, is 183
        # days wide (1983-84's window has 29 February); past its end is the
        # run's own last day, and a move with no button down seeks nothing.
        self.assertEqual(got, [[40, "10 November 1982: 3.0 mm"], 0, 91, 91, [181, 181]])

    def test_a_finger_on_the_chart_seeks_on_a_tap_or_a_drag_across_and_scrolls_up_and_down(self):
        got = _run(self, PANEL_SETUP + r"""
          simOpen();
          await flush();
          var chart = $("street-sim-chart"), out = [];
          function touch(type, x, y) { chart.fire(type, {pointerId: 5, pointerType: "touch", clientX: x, clientY: y}); }
          touch("pointerdown", 386, 50);
          out.push(S.sim.day);
          touch("pointermove", 388, 80);
          touch("pointercancel", 388, 80);
          out.push(S.sim.day);
          touch("pointerdown", 386, 50);
          touch("pointerup", 386, 51);
          out.push(S.sim.day);
          touch("pointerdown", 36, 50);
          touch("pointermove", 60, 52);
          out.push(S.sim.day);
          touch("pointermove", 211, 90);
          out.push(S.sim.day);
          touch("pointerup", 211, 90);
          touch("pointermove", 600, 90);
          out.push(S.sim.day);
          console.log(JSON.stringify(out));
        """)
        # Down, nothing yet; moved up and down, it is the panel's scroll, which
        # the browser takes (pointercancel): nothing sought. A tap seeks where
        # it is let go; a drag seeks once it goes across more than up or down,
        # and on as it moves, until it is let go.
        self.assertEqual(got, [0, 0, 91, 6, 45, 45])

    def test_on_the_window_s_last_day_the_neutral_years_are_their_totals_with_29_february_or_without(self):
        got = _run(self, PANEL_SETUP + r"""
          simOpen();
          await flush();
          simDay(181);
          var plain = $("street-sim-read").textContent;
          simPick("1987");
          simDay(182);
          console.log(JSON.stringify([plain, $("street-sim-read").textContent]));
        """)
        # October to March: 1987-88's has 29 February, 183 days, 1982-83's
        # 182. On 31 March both stand against the neutral years' totals - 182,
        # 183, 162 and 182 - their mean the neutral years' mean, 177 mm.
        self.assertTrue(got[0].startswith("31 March 1983: "), got[0])
        self.assertTrue(got[1].startswith("31 March 1988: "), got[1])
        for said in got:
            self.assertTrue(said.endswith("; neutral years by this day 177 mm (10th to 90th percentile 168 to 183 mm)."),
                            said)

    def test_the_readout_and_the_words_set_the_el_nino_against_the_neutral_years(self):
        got = _run(self, PANEL_SETUP + r"""
          simOpen();
          await flush();
          simDay(31);
          var day = $("street-sim-read").textContent;
          simDay(165);
          console.log(JSON.stringify([day, $("street-sim-read").textContent, $("street-sim-day").getAttribute("aria-valuetext"),
                                      $("street-sim-said").innerHTML]));
        """)
        self.assertEqual(got[0], "1 November 1982: 25 mm (0.98 in) of rain, 18.0 \u00b0C. So far 56 mm (2.2 in); "
                                 "neutral years by this day 32 mm (10th to 90th percentile 32 to 32 mm).")
        # 15 March 1983 is missing, and counted dry.
        self.assertTrue(got[1].startswith("15 March 1983: rain not on record, 18.0 \u00b0C. So far 543 mm (21.4 in);"),
                        got[1])
        self.assertEqual(got[2], "15 March 1983: rain not on record")
        self.assertEqual(got[3], "<b>October to March 1982-83</b> brought 591 mm here, 333% of the neutral years\u2019 "
                                 "mean of 177 mm (4 years). 5 days of 20 mm or more (neutral years: 0 on average). "
                                 "Wettest day: 25 mm on 1 November 1982. Longest dry spell: 1 day (neutral years: 5 "
                                 "days). Mean temperature 18.3 \u00b0C, 1.7 \u00b0C cooler than the neutral years\u2019 "
                                 "20.0 \u00b0C. 1 day missing from POWER\u2019s record is counted dry. Over the 2 El "
                                 "Ni\u00f1os replayable here since 1981, these months brought 594 mm on average, more "
                                 "than the neutral mean in 2 of them.")

    def test_year_by_year_sets_every_el_nino_beside_the_neutral_mean(self):
        got = _run(self, PANEL_SETUP + r"""
          simOpen();
          await flush();
          console.log(JSON.stringify($("street-sim-table").innerHTML));
        """)
        self.assertEqual(table_rows(got), [
            ["Window", "RONI peak", "Rain", "Of neutral", "Days of 20 mm+", "Wettest day", "Longest dry spell",
             "Mean temperature", "Days missing"],
            ["1987-88", "+1.1", "597 mm", "337%", "5", "25 mm", "0 days", "18.3 \u00b0C", "0"],
            ["1982-83", "+2.2", "591 mm", "333%", "5", "25 mm", "1 day", "18.3 \u00b0C", "1"],
            ["Neutral years\u2019 mean (4)", "", "177 mm", "100%", "0", "", "5 days", "20.0 \u00b0C", ""]])
        # The run shown stands out.
        self.assertIn('<tr class="strong"><th scope="row">1982-83</th>', got)

    def test_a_record_that_cannot_be_read_is_said_with_a_retry(self):
        got = _run(self, PANEL_SETUP + r"""
          route("format=CSV", 503);
          simOpen();
          await flush();
          var failed = [$("street-sim-fail").hidden, $("street-sim-why").textContent, $("street-sim-said").innerHTML,
                        $("street-sim-play").disabled];
          route("format=CSV", CSV);
          $("street-sim-retry").fire("click");
          var again = [$("street-sim-fail").hidden, $("street-sim-said").innerHTML];
          await flush();
          console.log(JSON.stringify({failed: failed, again: again, asked: csvAsked().length,
                                      now: [$("street-sim-fail").hidden, S.sim.model.events.length, $("street-sim-play").disabled]}));
        """)
        self.assertEqual(got["failed"], [False, "NASA POWER\u2019s days for this place could not be read (answered 503).",
                                         "", True])
        self.assertEqual(got["again"], [True, LOADING])
        self.assertEqual([got["asked"], got["now"]], [2, [True, 2, False]])

    def test_back_to_the_card_exit_and_esc_close_it(self):
        got = _run(self, PANEL_SETUP + r"""
          simOpen();
          await flush();
          $("street-sim-play").fire("click");
          $("street-sim-back").fire("click");
          var back = [S.sim, $("street-sim").hidden, $("street-chip-said").hidden,
                      $("street-stage").classList.contains("simon"), FRAMES.length];
          simOpen();
          await flush();
          var kept = [!!S.sim.model, csvAsked().length];
          var e = press("Escape");
          var esc = [S.sim, !!S.street, e.defaultPrevented];
          press("Escape");
          var left = S.street;
          streetEnter(-81.73, 28.02, "Winter Haven");
          simOpen();
          $("street-exit").fire("click");
          console.log(JSON.stringify({back: back, kept: kept, esc: esc, left: left,
                                      exit: [S.sim, S.street, $("street-sim").hidden]}));
        """)
        self.assertEqual(got["back"], [None, True, False, False, 0])
        # The record kept: opened again, it is there at once.
        self.assertEqual(got["kept"], [True, 1])
        # Esc closes the replay first, and leaves the street after.
        self.assertEqual(got["esc"], [None, True, True])
        self.assertIsNone(got["left"])
        self.assertEqual(got["exit"], [None, None, True])

    def test_another_point_keeps_it_open_stopped_and_asks_again_only_for_another_cell(self):
        got = _run(self, PANEL_SETUP + r"""
          route("longitude=-81.250", csvOf(REC, 1));
          simOpen();
          await flush();
          var first = S.sim.model.base.total;
          $("street-sim-play").fire("click");
          frames(125, 1); frames(125, 8);
          streetEnter(-81.70, 28.05, "Nearby");
          var same = [S.sim.playing, S.sim.day, S.sim.model.base.total, FRAMES.length];
          streetEnter(-81.40, 28.02, "East");
          var moving = [S.sim.model, $("street-sim-said").innerHTML, S.sim.day, $("street-sim").hidden];
          streetEnter(-81.73, 28.02, "Back");
          await flush();
          var back = [S.sim.key, S.sim.model.base.total, S.sim.day];
          streetEnter(-81.40, 28.02, "East");
          await flush();
          console.log(JSON.stringify({first: first, same: same, moving: moving, back: back,
            east: [S.sim.key, S.sim.model.base.total, S.sim.day, $("street-sim").hidden],
            asked: csvAsked().map(function (u) { return u.split("longitude=")[1].split("&")[0]; })}));
        """)
        self.assertEqual(got["first"], 177.25)
        # Within the cell: stopped where it was, its rain still falling, and
        # nothing asked.
        self.assertEqual(got["same"], [False, 7, 177.25, 1])
        # Into another: its record asked, the panel open and waiting on it.
        self.assertEqual(got["moving"], [None, LOADING, 7, False])
        # Back before it came: the first cell's record, and the other's answer
        # not shown when it came.
        self.assertEqual(got["back"], ["days|28.0,-81.875", 177.25, 7])
        # In the other cell, its own record, a millimetre a day wetter.
        self.assertEqual(got["east"], ["days|28.0,-81.250", 359.5, 7, False])
        self.assertEqual(got["asked"], ["-81.875", "-81.250"])

    def test_next_street_and_the_minimap_move_it_stopped_onto_the_new_cell_s_record(self):
        got = _run(self, PANEL_SETUP + r"""
          route("longitude=-81.250", csvOf(REC, 1));
          route("routed-car/nearest", """ + json.dumps(ROADS_EDGE) + r""");
          streetPick(-81.565, 28.02, 16);
          advance(1000); await flush();
          simOpen();
          await flush();
          function play() { $("street-sim-play").fire("click"); frames(125, 1); frames(125, 8); return [S.sim.playing, S.sim.day]; }
          var west = [S.street.label, S.sim.key, play()];
          $("street-next").fire("click");
          var next = [S.street.label, S.sim.playing, S.sim.model, $("street-sim-said").innerHTML, $("street-sim-play").disabled];
          await flush();
          var east = [S.sim.key, S.sim.model.base.total, S.sim.day, play()];
          $("street-mini").fire("click", {clientX: 400, clientY: 300});
          var finding = [S.street.finding, S.sim.playing, $("street-sim-play").disabled, $("street-sim-day").disabled,
                         $("street-sim-event").disabled, simPlay(true), simSeekDay(3), S.sim.day];
          advance(1000); await flush();
          console.log(JSON.stringify({west: west, next: next, east: east, finding: finding,
            back: [S.street.label, S.sim.key, S.sim.model.base.total, S.sim.day, $("street-sim-play").disabled],
            asked: csvAsked().map(function (u) { return u.split("longitude=")[1].split("&")[0]; })}));
        """)
        self.assertEqual(got["west"], ["West Road, 28.02N 81.57W", "days|28.0,-81.875", [True, 7]])
        # Next street into the eastern cell: Play stopped, its record asked
        # and the panel waiting on it; then the cell's own, on the same day.
        self.assertEqual(got["next"], ["East Road, 28.02N 81.56W", False, None, LOADING, True])
        self.assertEqual(got["east"], ["days|28.0,-81.250", 359.5, 7, [True, 14]])
        # The minimap tapped while it plays: stopped, and nothing to play or
        # seek while the pick's street is being found.
        self.assertEqual(got["finding"], [True, False, True, True, True, False, False, 14])
        # Found in the western cell: its record, kept, at once.
        self.assertEqual(got["back"], ["West Road, 28.02N 81.57W", "days|28.0,-81.875", 177.25, 14, False])
        self.assertEqual(got["asked"], ["-81.875", "-81.250"])

    def test_a_run_taken_in_place_tells_the_replay_s_years_again_by_its_index(self):
        got = _run(self, PANEL_SETUP + r"""
          simOpen();
          await flush();
          simPick("1987");
          simDay(40);
          var before = [S.sim.model.events.map(function (r) { return r.tag; }), S.sim.tag];
          // The new run's index: November 1987 at +0.9, under El Nino's bound.
          var values = D.street.months.values.slice();
          values[(1987 - 1981) * 12 + 10] = 0.9;
          D.street = Object.assign({}, D.street, {months: {from: "1981-01", values: values}});
          var retook = simRetake();
          console.log(JSON.stringify([before, retook, S.sim.model.events.map(function (r) { return r.tag; }), S.sim.tag,
                                      S.sim.day, $("street-sim-event").value]));
        """)
        # 1987-88 is no El Nino by the new run's index: the strongest left is
        # shown, on the same day.
        self.assertEqual(got, [[[1987, 1982], "1987"], True, [1982], "1982", 40, "1982"])

    def test_with_nothing_to_replay_it_says_whether_this_year_s_window_has_begun(self):
        got = _run(self, PANEL_SETUP + r"""
          NOW = Date.UTC(1990, 5, 5, 12);
          simOpen();
          await flush();
          var july = [$("street-sim-said").innerHTML, $("street-sim-play").disabled];
          $("street-sim-start").value = "6";
          $("street-sim-start").fire("change");
          console.log(JSON.stringify([july, [$("street-sim-said").innerHTML, $("street-sim-play").disabled]]));
        """)
        # On 5 June 1990 no El Nino ever began a window from July or June;
        # July's window has not begun, and June's has four days on record.
        self.assertEqual(got, [
            ["No El Ni\u00f1o since 1981 reached +1.0 in July to September with POWER\u2019s record of its window whole "
             "here, and this year\u2019s has not begun: there is nothing to replay for July to December.", True],
            ["No El Ni\u00f1o since 1981 reached +1.0 in June to August with POWER\u2019s record of its window whole "
             "here, and this year\u2019s has fewer than 7 days on POWER\u2019s record yet: there is nothing to replay "
             "for June to November.", True]])

    def test_ecmwf_s_forecast_short_of_the_window_names_its_months(self):
        # September's run as Open-Meteo gives it unasked: six months, to
        # February, one short of October to March.
        short = {"monthly": {k: v[:6] for k, v in AHEAD_SEPTEMBER["monthly"].items()}}
        got = _run(self, 'route("v1/seasonal", ' + json.dumps(short) + ");" + PANEL_SETUP + r"""
          await flush();
          simOpen();
          await flush();
          console.log(JSON.stringify({key: $("street-sim-key").innerHTML, said: $("street-sim-said").innerHTML,
                                      rows: $("street-sim-table").innerHTML}));
        """)
        self.assertIn('<span class="ecmwf">ECMWF 2026-27, October to February</span>', got["key"])
        self.assertIn("ECMWF\u2019s forecast for October to February 2026-27, the months it reaches, comes to ", got["said"])
        self.assertEqual(table_rows(got["rows"])[-1][0], "ECMWF\u2019s forecast, 2026-27 (October to February only)")

    def test_the_method_says_how_it_is_known_in_the_sources_own_words(self):
        got = _run(self, PANEL_SETUP + r"""
          simOpen();
          await flush();
          console.log(JSON.stringify($("street-sim-method").innerHTML));
        """)
        words = re.sub(r"<[^>]+>", "", got)
        self.assertIn("about 55 by 61 km here, from 1 January 1981 to 31 December 1990.", words)
        self.assertIn("A window is the six months from the first of the month chosen, named for its year, or for the "
                      "two it spans (\u201c1997-98\u201d). It is an El Ni\u00f1o\u2019s when RONI centred on one of its "
                      "first three months is +1.0 or more (its peak the highest of the three)", words)
        self.assertIn("It is the index as the window opens, as a forecast made then would have it: a window from "
                      "spring takes El Ni\u00f1os growing and fading alike.", words)
        self.assertIn("ECMWF\u2019s forecast comes to the place by the delta method: for each month of the coming "
                      "window it forecasts, POWER\u2019s mean for that calendar month over every complete year here "
                      "since 1981, scaled by the model\u2019s forecast against its own climate of past forecasts "
                      "where that climate is 0.2 mm a day or more, else with the model\u2019s anomaly added, never "
                      "under nothing.", words)
        self.assertIn("POWER is sent the cell\u2019s grid point, not the place.", words)
        self.assertIn("the El Ni\u00f1o under way since June 1990 is this year\u2019s, not a past one", words)
        self.assertIn("These data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded "
                      "through the NASA Earth Science/Applied Science Program.", words)
        self.assertIn("ECMWF does not accept any liability whatsoever", words)
        self.assertIn('<a href="https://power.larc.nasa.gov/" target="_blank" rel="noopener">NASA POWER \u2197</a>', got)
        self.assertIn("The rain over Street View is the page\u2019s drawing, not Google\u2019s: nothing under 0.5 mm, "
                      "and above it streaks as many and as fast as the day\u2019s rain is heavy, up to 50 mm, with the "
                      "sky dimmed to match; snow where the day\u2019s mean temperature is at or below 0 \u00b0C. "
                      "Google\u2019s imagery under it is as Google took it.", words)

    def test_the_chart_draws_each_line_labels_them_and_marks_the_day(self):
        # ECMWF's months answered when the drop asks the card's sources.
        got = _run(self, 'route("v1/seasonal", ' + json.dumps(AHEAD_SEPTEMBER) + ");" + PANEL_SETUP + r"""
          await flush();
          simOpen();
          await flush();
          simDay(91);
          console.log(JSON.stringify({svg: $("street-sim-chart").innerHTML, key: $("street-sim-key").innerHTML,
            said: $("street-sim-said").innerHTML, head: [$("street-sim-head").getAttribute("x1"),
            $("street-sim-head").getAttribute("x2"), $("street-sim-dot").getAttribute("cx"),
            $("street-sim-dot").getAttribute("cy")], rows: $("street-sim-table").innerHTML}));
        """)
        svg = got["svg"]
        self.assertTrue(svg.startswith('<svg class="streetsimsvg" viewBox="0 0 800 170" width="800" height="170" '
                                       'role="img" aria-label="'), svg[:200])
        count = {cls: len(re.findall(r'class="%s"' % cls, svg)) for cls in ("band", "neutral", "evfaint", "ev",
                                                                             "ecmwf", "now", "bars")}
        self.assertEqual(count, {"band": 1, "neutral": 1, "evfaint": 1, "ev": 1, "ecmwf": 1, "now": 0, "bars": 1})
        # A bar for each day of rain: 182 days, one missing.
        self.assertEqual(re.search(r'<path class="bars" d="([^"]*)"', svg).group(1).count("M"), 181)
        # The band and the neutral mean drawn over 1982-83's 182 days, each
        # day the same date in the neutral years.
        self.assertEqual(re.search(r'<path class="band" d="([^"]*)"', svg).group(1).count("L"), 364)
        self.assertEqual(re.search(r'<path class="neutral" d="([^"]*)"', svg).group(1).count("L"), 182)
        # The other El Ninos, faint, each named where a pointer rests on it.
        self.assertRegex(svg, r'<path class="evfaint" d="[^"]*"><title>1987-88 \(\+1\.1\): 597 mm</title></path>')
        for label in ("1982-83", "Neutral", "ECMWF", "0", "300", "600", "Oct", "Nov", "Dec", "Jan", "Feb", "Mar"):
            self.assertIn(">" + label + "</text>", svg)
        # Day 91, 31 December 1982, the 92nd of 183 across 698 px: 258 mm so
        # far, on a scale to 600 over 112 px.
        self.assertEqual(got["head"], ["386.9", "386.9", "386.9", "71.8"])
        self.assertEqual(got["key"], '<span class="ev">1982-83</span><span class="faint">other El Ni\u00f1os</span>'
                                     '<span class="neutral">neutral years\u2019 mean, 10th to 90th percentile shaded'
                                     '</span><span class="ecmwf">ECMWF 2026-27</span><span class="bars">bars: '
                                     "1982-83\u2019s rain each day</span>")
        # ECMWF's months on POWER's, each the point's climate scaled by the
        # model's forecast against its own: 37% of October's 31 mm, 66% of
        # November's 46.4, then 116%, 125%, 116% and 119%.
        self.assertIn("ECMWF\u2019s forecast for October to March 2026-27 comes to 256 mm here, against 257 mm in an "
                      "average year and 177 mm in the neutral years\u2019 mean.", got["said"])
        self.assertEqual(table_rows(got["rows"])[-1], ["ECMWF\u2019s forecast, 2026-27", "", "256 mm", "145%", "", "",
                                                       "", "", ""])

    def test_the_rain_falls_over_the_panorama_while_the_replay_shows_a_wet_day(self):
        got = _run(self, PANEL_SETUP + RAIN_CTX + r"""
          window.devicePixelRatio = 3;
          var shut = [$("street-rain").hidden, $("street-day").hidden];
          simOpen();
          await flush();
          var open = [$("street-rain").hidden, $("street-day").hidden, $("street-day").textContent, ticking(),
                      count("clear"), count("drop")];
          OPS = [];
          frames(16);
          var first = [count("clear"), count("dim"), count("drop"), count("stroke") > 0, count("fill"), ticking()];
          OPS = [];
          frames(16, 2);
          console.log(JSON.stringify({shut: shut, open: open, first: first, more: [count("clear"), count("drop")],
                                      size: [$("street-rain").width, $("street-rain").height]}));
        """)
        # Hidden until the replay shows a day; then the badge names it, the
        # day's rain is drawn at once, and a frame is asked for while it rains.
        self.assertEqual(got["shut"], [True, True])
        self.assertEqual(got["open"], [False, False, "1 October 1982: 1.0 mm", 1, 1, 74])
        # Each frame clears the canvas, dims the sky and draws a streak for
        # each of the day's 74 drops (1 mm: s = 0.141), and asks for the next.
        self.assertEqual(got["first"], [1, 1, 74, True, 0, 1])
        self.assertEqual(got["more"], [2, 148])
        # At the device's pixel ratio, two at most.
        self.assertEqual(got["size"], [1600, 1200])

    def test_snow_falls_on_a_day_at_or_below_freezing(self):
        got = _run(self, PANEL_SETUP + RAIN_CTX + r"""
          REC.t[Math.round((Date.UTC(1982, 9, 1) - Date.UTC(1981, 0, 1)) / DAY)] = -2;
          route("format=CSV", csvOf(REC));
          simOpen();
          await flush();
          OPS = [];
          frames(16);
          console.log(JSON.stringify([count("drop"), count("fill") > 0, count("stroke")]));
        """)
        # 30 + 270 s flakes, filled, not stroked.
        self.assertEqual(got, [68, True, 0])

    def test_the_rain_stops_on_a_dry_day_paused_on_close_and_on_leaving(self):
        got = _run(self, PANEL_SETUP + RAIN_CTX + r"""
          REC.p[Math.round((Date.UTC(1982, 9, 2) - Date.UTC(1981, 0, 1)) / DAY)] = 0.2;
          route("format=CSV", csvOf(REC));
          simOpen();
          await flush();
          var wet = ticking();
          simSeekDay(1);
          var dry = [ticking(), $("street-day").textContent, $("street-rain").hidden, $("street-day").hidden];
          simSeekDay(0);
          var again = [ticking(), $("street-rain").hidden];
          $("street-sim-play").fire("click");
          simSeekDay(1);
          var playing = ticking();
          $("street-sim-play").fire("click");
          var paused = ticking();
          simSeekDay(0);
          simClose();
          var closed = [ticking(), $("street-rain").hidden, $("street-day").hidden];
          simOpen();
          await flush();
          var reopened = ticking();
          streetLeave();
          console.log(JSON.stringify([wet, dry, again, playing, paused, closed, reopened,
                                      [ticking(), $("street-rain").hidden, $("street-day").hidden]]));
        """)
        # 2 October 1982, 0.2 mm, is dry: the canvas hidden, the badge naming
        # the day still, and, paused, no frame asked for; playing, Play's
        # frames go on. A canvas cleared and drawn on no more can go on showing
        # what it drew last (Chrome, 12 October 2026): it is shown only while
        # it rains.
        self.assertEqual(got, [1, [0, "2 October 1982: 0.2 mm", True, False], [1, False], 1, 0, [0, True, True], 1,
                               [0, True, True]])

    def test_under_reduced_motion_the_rain_is_drawn_still_once_a_day(self):
        got = _run(self, PANEL_SETUP + RAIN_CTX + r"""
          window.matchMedia = function (q) { return {matches: /reduce/.test(q)}; };
          simOpen();
          await flush();
          var still = [ticking(), count("clear"), count("drop")];
          $("street-sim-play").fire("click");
          frames(250, 4);
          console.log(JSON.stringify([still, [S.sim.day, count("clear"), ticking()]]));
        """)
        # Drawn once, still, and no frame asked for; Play still steps the
        # days, a week a second, and each day it reaches is drawn once.
        self.assertEqual(got, [[0, 1, 74], [5, 4, 1]])

    def test_this_year_so_far_is_a_choice_drawn_in_ink(self):
        got = _run(self, PANEL_SETUP + r"""
          NOW = Date.UTC(1991, 0, 20, 12);
          simOpen();
          await flush();
          $("street-sim-start").value = "11";
          $("street-sim-start").fire("change");
          var options = $("street-sim-event").innerHTML, strongest = $("street-sim-event").value;
          $("street-sim-event").value = "now";
          $("street-sim-event").fire("change");
          var svg = $("street-sim-chart").innerHTML;
          console.log(JSON.stringify({options: options, strongest: strongest, max: $("street-sim-day").max,
            said: $("street-sim-said").innerHTML, key: $("street-sim-key").innerHTML,
            lines: ["now", "ev", "evfaint"].map(function (c) {
              return (svg.match(new RegExp('class="' + c + '"', "g")) || []).length;
            })}));
        """)
        self.assertEqual(got["options"], '<option value="now">This year so far, 1990-91</option>'
                                         '<option value="1987">1987-88 (+1.1)</option>'
                                         '<option value="1982">1982-83 (+2.2)</option>')
        self.assertEqual([got["strongest"], got["max"], got["lines"]], ["1982", "60", [1, 0, 2]])
        self.assertEqual(got["said"], "<b>November to April 1990-91 so far</b>, 61 days to 31 December 1990: 61 mm, "
                                      "against a mean of 61 mm by the same day in the neutral years and 227 mm in "
                                      "the El Ni\u00f1os.")
        self.assertEqual(got["key"], '<span class="faint">El Ni\u00f1os</span><span class="neutral">neutral years\u2019 '
                                     'mean, 10th to 90th percentile shaded</span><span class="now">this year so far'
                                     '</span><span class="bars">bars: this year\u2019s rain each day</span>')


if __name__ == "__main__":
    unittest.main()
