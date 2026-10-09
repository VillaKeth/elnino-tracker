"""Then and now: entering a place on the map and comparing it before and
after El Nino (elnino/thennow.py, and its hooks in the desk's page)."""

from __future__ import annotations

import json
import re
import shutil
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from elnino import parsers, stormdesk, street, thennow, worldmap  # noqa: E402
from elnino.parsers import SeasonValue  # noqa: E402
# The helpers only: importing a TestCase class here would run it twice.
from test_tracker import _DeskFixtures, _js_function, _node_json  # noqa: E402


def seasons_from(season: str, year: int, values) -> list:
    """Consecutive seasons from one, as CPC's files list them."""
    order = parsers.ONI_SEASONS
    i, out = order.index(season), []
    for value in values:
        out.append(SeasonValue(order[i], year, value))
        i += 1
        if i == len(order):
            i, year = 0, year + 1
    return out


# SON 1999 to JJA 2001: a La Nina episode across the turn of 2000; a warm run
# of three seasons in 2000 (0.46 prints as 0.5); a very strong El Nino
# peaking JFM 2001; and two warm seasons still going at the end.
RECORD = seasons_from("SON", 1999, (
    -1.2, -1.4, -1.5, -1.3, -1.1, -0.8,     # SON 1999 - FMA 2000
    -0.4, 0.2, 0.46, 0.6, 0.5, 0.3, 0.0,    # MAM - SON 2000
    0.8, 1.2, 1.6, 2.1, 1.7, 0.9,           # OND 2000 - MAM 2001
    0.1, 0.7, 0.9))                         # AMJ - JJA 2001


def state_with(series, run_at="2001-09-29T12:00:00+00:00", index="RONI"):
    return SimpleNamespace(run_at=run_at, assessment=SimpleNamespace(
        index_name=index, index_series=list(series)))


class TestSeasonWords(unittest.TestCase):
    """Every season from DJF 2000 on, keyed by its centre month, with its
    value as CPC prints it and what it was."""

    def rows(self, series=RECORD):
        return {row[0]: row for row in thennow.season_rows(series)}

    def test_each_season_is_keyed_by_its_centre_month_from_january_2000(self):
        rows = thennow.season_rows(RECORD)
        self.assertEqual(rows[0][:3], ["2000-01", "DJF 2000", -1.3])
        self.assertEqual(rows[-1][:2], ["2001-07", "JJA 2001"])
        self.assertEqual(len(rows), 19)
        self.assertFalse([r for r in rows if r[0] < "2000-01"])

    def test_a_season_in_an_episode_names_its_strength_and_the_episode(self):
        rows = self.rows()
        self.assertEqual(rows["2000-01"][3], "moderate La Niña, the 1999-00 episode")
        self.assertEqual(rows["2000-02"][3], "moderate La Niña, the 1999-00 episode")
        self.assertEqual(rows["2000-03"][3], "weak La Niña, the 1999-00 episode")
        self.assertEqual(rows["2001-02"][2:], [2.1, "very strong El Niño, the 2000-01 episode"])
        self.assertEqual(rows["2001-04"][3], "weak El Niño, the 2000-01 episode")

    def test_a_run_short_of_five_seasons_is_conditions_short_of_an_episode(self):
        # MJJ 2000's 0.46 is printed 0.5, and counted, as CPC counts it.
        self.assertEqual(self.rows()["2000-06"][2:], [0.5, "weak El Niño conditions, short of an episode"])

    def test_the_run_still_going_counts_its_seasons_so_far(self):
        rows = self.rows()
        self.assertEqual(rows["2001-06"][3], "weak El Niño conditions, 2 seasons so far")
        self.assertEqual(rows["2001-07"][3], "weak El Niño conditions, 2 seasons so far")
        one = self.rows(RECORD[:-1])
        self.assertEqual(one["2001-06"][3], "weak El Niño conditions, 1 season so far")

    def test_an_episode_still_going_says_so(self):
        rows = self.rows(RECORD + seasons_from("JAS", 2001, (0.8, 1.0, 1.1)))
        self.assertEqual(rows["2001-10"][3], "moderate El Niño, the 2001 episode, still going")

    def test_everything_else_is_neutral(self):
        rows = self.rows()
        self.assertEqual(rows["2000-04"][2:], [-0.4, "neutral"])
        self.assertEqual(rows["2000-10"][2:], [0.0, "neutral"])

    def test_no_record_no_rows(self):
        self.assertEqual(thennow.season_rows([]), [])


class TestPresets(unittest.TestCase):
    """The event menu: a year ago against the latest, then each El Nino
    episode peaking since March 2000, newest first, before and after its peak."""

    def test_the_first_entry_is_a_year_ago_against_the_latest(self):
        first = thennow.presets(RECORD, date(2001, 9, 29))[0]
        self.assertEqual(first, {"id": "now", "group": "", "left": "2000-09-29",
                                 "right": "2001-09-29",
                                 "label": "A year ago → the latest (Sep 2000 → Sep 2001)"})

    def test_an_episode_gives_the_year_before_its_peak_and_the_year_after(self):
        got = thennow.presets(RECORD, date(2003, 1, 1))
        self.assertEqual([p["id"] for p in got], ["now", "ep0-before", "ep0-after"])
        before, after = got[1], got[2]
        self.assertEqual((before["left"], before["right"]), ("2000-02-15", "2001-02-15"))
        self.assertEqual((after["left"], after["right"]), ("2001-02-15", "2002-02-15"))
        self.assertEqual(before["group"], "2000-01 El Niño, peaking JFM 2001 at RONI +2.1")
        # Each choice names its episode itself: the menu, closed, shows only
        # the choice, cut short on a narrow screen, and not its group.
        self.assertEqual(before["label"], "2000-01 El Niño, developing: Feb 2000 → peak Feb 2001")
        self.assertEqual(after["label"], "2000-01 El Niño, decaying: peak Feb 2001 → Feb 2002")

    def test_a_choice_whose_dates_have_not_come_is_not_offered(self):
        got = thennow.presets(RECORD, date(2001, 9, 29))
        self.assertEqual([p["id"] for p in got], ["now", "ep0-before"])

    def test_episodes_come_newest_first(self):
        more = RECORD + seasons_from("JAS", 2001, (0.8, 1.0, 1.1, 1.3, 1.0, 0.6, 0.2))
        got = thennow.presets(more, date(2003, 6, 1))
        self.assertEqual([p["id"] for p in got],
                         ["now", "ep1-before", "ep1-after", "ep0-before", "ep0-after"])
        self.assertEqual(got[1]["right"], "2001-11-15")

    def test_a_peak_before_march_2000_and_la_nina_are_not_offered(self):
        early = seasons_from("MJJ", 1999, (0.6, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 1.1, 0.2))
        self.assertEqual([p["id"] for p in thennow.presets(early, date(2003, 1, 1))], ["now"])
        cool = seasons_from("MJJ", 2005, (-0.6, -0.8, -1.0, -1.2, -1.0, -0.6, 0.0))
        self.assertEqual([p["id"] for p in thennow.presets(cool, date(2008, 1, 1))], ["now"])


class TestThenPayload(unittest.TestCase):
    """What the page is sent: the sources, Esri's archive, the seasons, the
    menu and NASA's scales."""

    def test_the_five_sources_with_their_archives_first_days(self):
        got = thennow.payload(state_with(RECORD))["sources"]
        self.assertEqual([s["id"] for s in got], ["archive", "hls", "modis", "ndvi", "sst"])
        self.assertEqual([s["first"] for s in got],
                         ["2014-02-20", "2013-03-22", "2000-02-24", "2000-03-05", "2002-09-01"])
        self.assertEqual([s["enter"] for s in got], [16, 12, 8, 7, 4])
        self.assertEqual([s["zoom"] for s in got], [19, 13, 13, 13, 13])
        by = {s["id"]: s for s in got}
        self.assertEqual((by["modis"]["layer"], by["modis"]["tms"], by["modis"]["format"]),
                         ("MODIS_Terra_CorrectedReflectance_TrueColor",
                          "GoogleMapsCompatible_Level9", "jpeg"))
        self.assertEqual((by["ndvi"]["layer"], by["ndvi"]["tms"], by["ndvi"]["format"]),
                         ("MODIS_Terra_L3_NDVI_16Day", "GoogleMapsCompatible_Level9", "png"))
        self.assertEqual((by["sst"]["layer"], by["sst"]["tms"], by["sst"]["tile_zoom"]),
                         ("GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies",
                          "GoogleMapsCompatible_Level6", 6))
        for s in got:
            self.assertTrue(s["name"] and s["about"], s["id"])

    def test_esri_s_archive_is_asked_where_it_answered(self):
        w = thennow.payload(state_with(RECORD))["wayback"]
        self.assertEqual(w["config"], "https://s3-us-west-2.amazonaws.com/config.maptiles."
                                      "arcgis.com/waybackconfig.json")
        self.assertEqual(w["tilemap"], "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
                                       "World_Imagery/MapServer/tilemap/{release}/{z}/{y}/{x}")
        self.assertEqual(w["item"], "https://www.arcgis.com/sharing/rest/content/items/{id}?f=json")
        self.assertEqual((w["level"], w["metadata_layer"]), (16, 7))

    def test_the_seasons_menu_and_strip_come_from_the_official_index(self):
        got = thennow.payload(state_with(RECORD, index="ONI"))
        self.assertEqual(got["seasons"], thennow.season_rows(RECORD))
        self.assertEqual(got["presets"], thennow.presets(RECORD, date(2001, 9, 29), "ONI"))
        self.assertEqual(got["index"], "ONI")
        self.assertEqual((got["built"], got["strip"]), ("2001-09-29", {"from": "2000-01", "months": 21}))

    def test_a_run_without_the_index_still_offers_a_year_ago(self):
        got = thennow.payload(SimpleNamespace(run_at="2026-09-29T12:00:00+00:00"))
        self.assertEqual((got["seasons"], got["index"]), ([], "RONI"))
        self.assertEqual([p["id"] for p in got["presets"]], ["now"])
        self.assertEqual(got["strip"]["months"], 321)

    def test_the_payload_survives_json(self):
        got = thennow.payload(state_with(RECORD))
        self.assertEqual(json.loads(json.dumps(got)), got)

    def test_the_scales_are_nasa_s_own_bin_for_bin(self):
        scales = thennow.payload(state_with(RECORD))["scales"]
        self.assertEqual([(e["lo"], e["hi"], tuple(e["rgb"])) for e in scales["sst"]],
                         [(lo, hi, rgb) for lo, hi, rgb in worldmap.SST_COLOURS])
        self.assertEqual(scales["sst"][41]["label"], "+1.0 to +1.1 °C")
        ndvi = scales["ndvi"]
        self.assertEqual(len(ndvi), 140)
        self.assertEqual(ndvi[0], {"lo": 0.0, "hi": 0.005, "rgb": [241, 236, 236],
                                   "label": "NDVI 0.000 to 0.005"})
        self.assertEqual((ndvi[-1]["lo"], ndvi[-1]["hi"], ndvi[-1]["rgb"]), (0.99, 1.0, [0, 24, 1]))
        for before, after in zip(ndvi, ndvi[1:]):
            self.assertEqual(before["hi"], after["lo"])
        self.assertIn("NDVI 0.280 to 0.285", [e["label"] for e in ndvi])


# The 2014-16 event as CPC's ONI table printed it, DJF 2014 to NDJ 2016: the
# record the page's tests read.
EVENT = seasons_from("DJF", 2014, (
    -0.4, -0.5, -0.3, 0.0, 0.2, 0.1, 0.0, 0.1, 0.4, 0.5, 0.6, 0.7,
    0.5, 0.5, 0.5, 0.7, 0.9, 1.2, 1.5, 1.9, 2.2, 2.4, 2.6, 2.6,
    2.5, 2.1, 1.6, 0.9, 0.4, -0.1, -0.4, -0.5, -0.6, -0.7, -0.7, -0.6))


class TestThenMarkup(_DeskFixtures, unittest.TestCase):
    """The page's parts: the figure in the toolbar, the chips and hint on the
    map, the bar under it, and the script spliced in."""

    def page(self) -> str:
        state = self.state(self.polo())
        state.assessment = SimpleNamespace(index_name="RONI", index_series=list(EVENT))
        state.run_at = "2026-09-29T12:00:00+00:00"
        return stormdesk.page(state, focus="world")

    def test_the_figure_is_a_named_button_in_the_toolbar(self):
        html = self.page()
        tools = re.search(r'<nav class="desktools".*?</nav>', html, re.S).group(0)
        button = re.search(r'<button[^>]*id="then-enter"[^>]*>.*?</button>', tools, re.S).group(0)
        self.assertIn('aria-pressed="false"', button)
        self.assertIn('aria-describedby="then-enter-how"', button)
        self.assertIn('<svg class="thenfigsvg"', button)
        self.assertIn('aria-hidden="true"', button)
        self.assertTrue(button.endswith(" Street View</button>"))
        self.assertIn('id="then-enter-how">Drag the figure onto the map, or press it and tap a '
                      "place, to drop into Street View there and see what El Niño does to that "
                      "street.</span>", tools)
        self.assertIn('id="then-ghost" aria-hidden="true" hidden>', tools)

    def test_the_hint_chips_and_ring_are_on_the_map(self):
        html = self.page()
        mapped = html[html.index('<div class="deskmap" id="map"'):html.index('<div class="deskzoom ui">')]
        self.assertIn('<p class="thenhint ui" id="then-hint" role="status" hidden>Tap a place to '
                      "drop into Street View there, or press Enter for the middle of the view. "
                      "Esc cancels.</p>", mapped)
        for key in ("a", "b"):
            self.assertIn(f'<div class="thenchip ui" id="then-chip-{key}" hidden></div>', mapped)
        self.assertIn('<span class="thenring" id="then-ring" aria-hidden="true" hidden></span>', mapped)

    def test_the_bar_sits_under_the_map_hidden_with_every_control_named(self):
        html = self.page()
        self.assertLess(html.index('<div class="deskscrub">'), html.index('id="then-bar"'))
        self.assertLess(html.index('id="then-bar"'), html.index('class="desklegend"'))
        bar = re.search(r'<section class="thenbar" id="then-bar".*?</section>', html, re.S).group(0)
        self.assertIn('aria-label="Then and now" hidden>', bar)
        self.assertIn('<label class="thenfield">Source <select class="toolsel" id="then-source">', bar)
        self.assertIn('<label class="thenfield">Event <select class="toolsel" id="then-event">', bar)
        for words, ident in (("Street View", "then-street"), ("Copy link", "then-copy"),
                             ("Exit", "then-exit")):
            self.assertIn(f'<button type="button" class="toolbtn" id="{ident}">{words}</button>', bar)
        self.assertIn('<input type="checkbox" id="then-names" checked> Roads and names</label>', bar)
        for key, where in (("a", "left side"), ("b", "right side")):
            self.assertIn(f'role="group" aria-labelledby="then-head-{key}"', bar)
            self.assertIn(f'id="then-back-{key}" aria-label="Earlier, {where}">&#9664;</button>', bar)
            self.assertIn(f'id="then-next-{key}" aria-label="Later, {where}">&#9654;</button>', bar)
            self.assertIn(f'<input type="date" class="thendate" id="then-date-{key}" '
                          f'min="2000-01-01" max="2026-09-29" aria-label="Date, {where}">', bar)
            self.assertIn(f'id="then-cap-{key}" aria-label="Capture, {where}" hidden></select>', bar)
            self.assertIn(f'<p class="thenwords" id="then-words-{key}"></p>', bar)
        self.assertIn('<p class="thenread" id="then-read" role="status"></p>', bar)
        self.assertIn('<a id="then-gmaps" href="https://www.google.com/maps" target="_blank" '
                      'rel="noopener">', bar)

    def test_the_menus_offer_the_sources_and_the_events(self):
        bar = re.search(r'<section class="thenbar".*?</section>', self.page(), re.S).group(0)
        source = re.search(r'id="then-source">(.*?)</select>', bar).group(1)
        self.assertEqual(re.findall(r'<option value="(\w+)">', source),
                         ["archive", "hls", "modis", "ndvi", "sst"])
        event = re.search(r'id="then-event">(.*?)</select>', bar).group(1)
        self.assertTrue(event.startswith('<option value="now">A year ago → the latest '
                                         "(Sep 2025 → Sep 2026)</option>"))
        self.assertIn('<optgroup label="2014-16 El Niño, peaking OND 2015 at RONI +2.6">'
                      '<option value="ep0-before">2014-16 El Niño, developing: Nov 2014 → peak '
                      'Nov 2015</option><option value="ep0-after">2014-16 El Niño, decaying: peak '
                      "Nov 2015 → Nov 2016</option></optgroup>", event)
        self.assertTrue(event.endswith('<option value="">Dates of your own</option>'))

    def test_the_strip_draws_each_season_at_its_month(self):
        bar = re.search(r'<section class="thenbar".*?</section>', self.page(), re.S).group(0)
        strip = re.search(r'<svg class="thenstrip" id="then-strip".*?</svg>', bar, re.S).group(0)
        self.assertIn('viewBox="0 -30 321 60" preserveAspectRatio="none" role="img" '
                      'aria-label="RONI by season since January 2000', strip)
        # OND 2015, centred on November 2015: month 190, +2.6 drawn 26 units up.
        self.assertIn('<rect class="warm" x="190" y="-26" width="1" height="26"/>', strip)
        # JJA 2016's -0.4, centred on July 2016, short of the line; SON 2016's -0.7 below it.
        self.assertIn('<rect class="flat" x="198" y="0" width="1" height="4"/>', strip)
        self.assertIn('<rect class="cool" x="201" y="0" width="1" height="7"/>', strip)
        self.assertEqual(len(re.findall(r"<rect ", strip)), 34)   # the two zero seasons drawn as none
        for key in ("a", "b"):
            self.assertIn(f'<line class="thenline" id="then-line-{key}"', strip)
        years = re.search(r'<div class="thenyears" id="then-years" aria-hidden="true">(.*?)</div>',
                          bar).group(1)
        self.assertEqual(re.findall(r">(\d{4})<", years), ["2000", "2005", "2010", "2015", "2020", "2025"])
        self.assertIn('<span style="left:56.07%">2015</span>', years)

    def test_the_page_carries_the_payload_and_the_script(self):
        html = self.page()
        raw = re.search(r'<script id="desk-data" type="application/json">(.*?)</script>',
                        html, re.S).group(1)
        data = json.loads(raw)
        self.assertEqual([s["id"] for s in data["then"]["sources"]],
                         ["archive", "hls", "modis", "ndvi", "sst"])
        self.assertEqual(data["then"]["built"], "2026-09-29")
        js = stormdesk.script()
        self.assertNotIn("/*THENNOW*/", js)
        self.assertIn(thennow._JS, js)
        self.assertLess(js.index(worldmap._JS), js.index(thennow._JS))
        self.assertLess(js.index(thennow._JS), js.index("// ---- start ----"))
        self.assertIn("  S.then = null;", js)

    def test_the_styles_use_the_page_tokens_and_44_px_controls(self):
        css = thennow.css()
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", css), [])
        self.assertIn(".thenstep { width: 44px; height: 44px;", css)
        self.assertIn(".thendate { min-height: 44px;", css)
        self.assertIn(".thenfig { display: inline-flex; align-items: center; gap: 4px; "
                      "touch-action: none; }", css)
        self.assertIn("#map.arming { cursor: crosshair; }", css)
        self.assertIn(".thenstrip .warm { fill: var(--warm); }", css)
        self.assertIn(".thenstrip .cool { fill: var(--cool); }", css)
        self.assertIn(thennow.css(), self.page())

    def test_the_bar_s_link_is_a_44_px_target(self):
        self.assertIn(".thenlinks a { color: var(--s1); min-height: 44px; display: inline-flex;",
                      thennow.css())

    def test_the_hint_takes_the_pill_s_place_while_the_map_waits_for_a_tap(self):
        # Centred at the top, the hint lay over the pill in the map's corner
        # wherever the map was narrower than both side by side.
        css = thennow.css()
        self.assertIn(".thenhint { position: absolute; left: 10px; top: 10px; z-index: 10;\n"
                      "  margin: 0; max-width: min(480px, calc(100% - 76px));", css)
        self.assertIn("#map.arming #frame { visibility: hidden; }", css)
        self.assertNotIn("translateX", re.search(r"\.thenhint \{[^}]*\}", css).group(0))

    def test_a_chip_wraps_its_words_rather_than_cut_them(self):
        # At phone width a chip is under 160 px: "7 Feb 2024 · RONI +0.8, J…".
        chip = re.search(r"\.thenchip \{[^}]*\}", thennow.css()).group(0)
        self.assertNotIn("ellipsis", chip)
        self.assertNotIn("nowrap", chip)
        self.assertIn("line-height: 1.3;", chip)

    def test_while_entered_the_map_keeps_its_height_and_the_bar_scrolls(self):
        # On a page that fits the window, the bar under the map would take the
        # map's height: at 1280 by 720 the map was 90 px tall.
        css = thennow.css()
        self.assertIn("@media (min-width: 900px) {\n"
                      "  #map.thenon { min-height: 45vh; }\n"
                      "  #map.thenon ~ .desklegend { flex-shrink: 0; }\n"
                      "  .thenbar { flex: 0 1 auto; min-height: 0; overflow-y: auto; }\n"
                      "}", css)


# ----------------------------------------------------------------------------
# the page's script, run under node
# ----------------------------------------------------------------------------
# thennow._JS runs whole, as the page runs it, strict, over a DOM of plain
# objects, a clock that moves only when told and a network that answers from
# a table. The page's own functions it calls are taken from the page's script
# as written; what would draw, fly or change the layer is recorded instead.
PRELUDE = r"""
var NODES = {}, LISTS = {}, SELECTED = {}, DOC = {}, ASKED = [], IMAGES = [], COPIED = [], CALLS = [];
function note(what) { CALLS.push(what); }
function El(id, tag) {
  var own = {};
  this.id = id || ""; this.tagName = (tag || "div").toUpperCase(); this.attrs = {}; this.style = {};
  this.hidden = false; this.value = ""; this.checked = false; this.disabled = false;
  this.textContent = ""; this.innerHTML = ""; this.listeners = {};
  this.box = {left: 0, top: 0, width: 800, height: 600};
  this.classList = {
    add: function (c) { own[c] = true; }, remove: function (c) { delete own[c]; },
    contains: function (c) { return !!own[c]; },
    toggle: function (c, on) { on = on === undefined ? !own[c] : !!on; if (on) own[c] = true; else delete own[c]; return on; }
  };
}
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.hasAttribute = function (k) { return k in this.attrs; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (type, f) { (this.listeners[type] = this.listeners[type] || []).push(f); };
El.prototype.fire = function (type, e) {
  e = e || {};
  e.type = type; e.target = e.target || this; e.currentTarget = this;
  e.preventDefault = function () { e.defaultPrevented = true; };
  e.stopPropagation = function () {};
  (this.listeners[type] || []).forEach(function (f) { f(e); });
  return e;
};
El.prototype.getBoundingClientRect = function () {
  var b = this.box;
  return {left: b.left, top: b.top, width: b.width, height: b.height, right: b.left + b.width, bottom: b.top + b.height};
};
El.prototype.closest = function () { return null; };
El.prototype.querySelector = function () { return null; };
El.prototype.querySelectorAll = function () { return []; };
El.prototype.setPointerCapture = function () {};
El.prototype.scrollIntoView = function () { note("scroll " + this.id); };
El.prototype.appendChild = function (c) { return c; };
El.prototype.remove = function () {};
// A canvas reads back the colour of the last image drawn on it.
var CTX = {rgba: [0, 0, 0, 0], at: null, drawImage: function (img) { CTX.rgba = img._rgba || [0, 0, 0, 0]; },
           clearRect: function () {},
           getImageData: function (x, y, w, h) {
             CTX.at = [x, y, w, h];
             var out = [];
             for (var i = 0; i < w * h; i++) out.push(CTX.rgba[0], CTX.rgba[1], CTX.rgba[2], CTX.rgba[3]);
             return {data: out};
           }};
var document = {
  activeElement: null, documentElement: new El("html"), body: new El("body"),
  getElementById: function (id) { return NODES[id] || (NODES[id] = new El(id)); },
  createElement: function (tag) {
    var el = new El("", tag);
    if (tag === "canvas") el.getContext = function () { return CTX; };
    return el;
  },
  querySelector: function (sel) { return SELECTED[sel] || null; },
  querySelectorAll: function (sel) { return LISTS[sel] || []; },
  addEventListener: function (type, f) { (DOC[type] = DOC[type] || []).push(f); }
};
// A key pressed with the focus on an element (the page's body by default).
function press(key, target) {
  var e = {key: key, target: target || document.body, defaultPrevented: false};
  e.preventDefault = function () { e.defaultPrevented = true; };
  (DOC.keydown || []).forEach(function (f) { f(e); });
  return e;
}
var window = {innerHeight: 900, addEventListener: function () {}, matchMedia: function () { return {matches: false}; }};
var location = {href: "file:///C:/elnino/output/map.html", hash: "", protocol: "file:"};
var history = {replaceState: function (s, t, url) { note("replaceState " + url); location.href = url; location.hash = ""; }};
var navigator = {onLine: true, clipboard: {writeText: function (text) { COPIED.push(text); return Promise.resolve(); }}};
// The clock: Date.now is fixed; timers run when advance() passes them.
var NOW = Date.parse("2026-09-29T12:00:00Z"), TIMERS = [], TIMER = 0, CLOCK = 0;
Date.now = function () { return NOW; };
function setTimeout(f, ms) { TIMERS.push({id: ++TIMER, at: CLOCK + (ms || 0), f: f}); return TIMER; }
function clearTimeout(id) { TIMERS = TIMERS.filter(function (t) { return t.id !== id; }); }
function advance(ms) {
  CLOCK += ms;
  var due = TIMERS.filter(function (t) { return t.at <= CLOCK; });
  TIMERS = TIMERS.filter(function (t) { return t.at > CLOCK; });
  due.forEach(function (t) { t.f(); });
}
// Every answer and image load waiting to happen, let happen.
function flush(rounds) {
  return new Promise(function (done) {
    var n = rounds || 60;
    (function next() { if (n-- <= 0) done(); else setImmediate(next); })();
  });
}
// The network: the latest route whose words are in the URL answers. An
// object is JSON, a string text, a number a status, an Error a failure,
// "hang" no answer until the request is given up, a function its result.
var ROUTES = [];
function route(words, answer) { ROUTES.unshift([words, answer]); }
function fetch(url, opts) {
  ASKED.push(url);
  var answer = 404;
  for (var i = 0; i < ROUTES.length; i++) if (url.indexOf(ROUTES[i][0]) >= 0) { answer = ROUTES[i][1]; break; }
  if (typeof answer === "function") answer = answer(url);
  if (answer === "hang") return new Promise(function (ok, no) {
    if (opts && opts.signal) opts.signal.addEventListener("abort", function () { no(new Error("aborted")); });
  });
  if (answer instanceof Error) return Promise.reject(answer);
  var status = typeof answer === "number" ? answer : 200, body = typeof answer === "number" ? "" : answer;
  return Promise.resolve({ok: status >= 200 && status < 300, status: status,
    json: function () { return Promise.resolve(typeof body === "string" ? JSON.parse(body) : JSON.parse(JSON.stringify(body))); },
    text: function () { return Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)); }});
}
// Images: the latest rule whose words are in the URL paints it with an
// RGBA (as a canvas reads it back); false, or no rule, and it fails.
var PAINT = [];
function paint(words, rgba) { PAINT.unshift([words, rgba]); }
function Image() {}
Object.defineProperty(Image.prototype, "src", {
  get: function () { return this._src; },
  set: function (url) {
    var img = this, rgba = false;
    this._src = url; IMAGES.push(url);
    for (var i = 0; i < PAINT.length; i++) if (url.indexOf(PAINT[i][0]) >= 0) { rgba = PAINT[i][1]; break; }
    setImmediate(function () {
      if (rgba) { img._rgba = rgba; if (img.onload) img.onload(); }
      else if (img.onerror) img.onerror();
    });
  }
});
function $(id) { return document.getElementById(id); }
var map = $("map"), divider = $("divider"), statusPill = $("status");
var TILE = 256, MINZ = 1, MAXZ = 13, UNIT = 1048576, HOUR = 3600000, NM = 1.852, CIRCUMFERENCE = 40075.017;
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
var NODATA = {}, MAPS = {}, GOT = {}, DOM = {}, AGAIN = {}, looks = {}, NO_ANSWER = "no answer", anim = 0;
var S = {x: 0.5, y: 0.5, z: 3, w: 800, h: 600, layer: "streets", second: "infrared", compare: false,
         split: 0.3, loop: false, frame: 0, scrub: 0, inView: {}, inViewB: null, show: {}, refs: {},
         pin: null, here: null, google: null, day: null, imagery: "ok",
         enso: {variable: "PRECIP", season: "SON", tiles: {}}};
var LAYERS = {
  streets: {id: "streets", kind: "map", name: "Streets", source: "Esri World Street Map",
            tiles: "https://streets/{z}/{y}/{x}", zoom: 19, grey: true, credit: "Streets: Esri."},
  satellite: {id: "satellite", kind: "map", name: "Satellite", source: "Esri World Imagery",
              tiles: "https://imagery/{z}/{y}/{x}", over: ["https://roads/{z}/{y}/{x}", "https://places/{z}/{y}/{x}"],
              zoom: 19, grey: true, credit: "Imagery: Esri."},
  infrared: {id: "infrared", kind: "imagery", name: "Infrared", satellites: {}, tms: "GoogleMapsCompatible_Level6",
             zoom: 6, format: "png", step: "PT10M"},
  detail: {id: "detail", kind: "imagery", name: "Detail (30 m)", stack: ["HLS_L30", "HLS_S30"],
           tms: "GoogleMapsCompatible_Level12", zoom: 12, format: "png", step: "P1D", pixel_km: 0.03,
           credit: "HLS: NASA."}
};
var PLACES = [["Manaus", "Brazil", "Amazonas", 2219580, -60.025, -3.1, 0],
              ["Suva", "Fiji", "Central", 93970, 178.44, -18.14, 1]];
// What the script calls on the page, recorded.
var FLIGHTS = [], LAND = {};
function dirty() { note("dirty"); }
function requestRender() { note("render"); }
function ask(s) {}
function owners() { return []; }
function frameOf() { return null; }
function cancelAnimationFrame() {}
function animate(to, ms) { FLIGHTS.push({x: to.x, y: to.y, z: to.z, ms: ms}); S.x = to.x; S.y = to.y; S.z = to.z; }
function settle() { note("settle"); }
function setLayer(id) { note("setLayer " + id); S.layer = id; return true; }
function setCompare(on) { note("setCompare " + on); S.compare = !!on; return S.compare; }
function setLoop(on) { note("setLoop " + on); S.loop = !!on; return S.loop; }
function hereAt(lon, lat, label) { note("hereAt " + label); S.here = {lon: lon, lat: lat, label: label}; }
function googleFrame(kind) { note("googleFrame " + kind); }
function tileFailed() { note("tileFailed " + this._name); }
function cellAt(name, season, lon, lat) { return {value: LAND[Math.round(lon) + "," + Math.round(lat)] ? 1 : null}; }
// A box written again as the page's retake writes it: whole.
function retake(box, html) { box.innerHTML = html; }
var COMPASS8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
"""

# The page's functions the script calls, as the page's script has them.
ENGINE = ("clamp", "wrap", "rad", "deg", "mx", "my", "lonOf", "latOf", "world", "origin", "near",
          "toWorld", "km", "pad2", "dayZ", "stamp", "shiftDay", "dayText", "esc", "named", "where",
          "kms", "nearestPlace", "placeLabel", "pin", "signedText", "classify", "wrap180", "googleZoom",
          "googleLinks", "tileUrl", "xyzUrl", "present", "xyzCells", "source", "timed", "cells",
          "labelled", "labelledBase", "overSpecs", "gotKey", "tilesDown", "look", "covered", "imageOn",
          "mapDown", "nasaDown", "baseDown", "googleEmbed", "maxZoom", "finite")

# The page's payload for the 2014-16 event, built on 29 September 2026, and
# the street's from the same run.
THEN = thennow.payload(state_with(EVENT, run_at="2026-09-29T12:00:00+00:00"))
STREET = street.payload(state_with(EVENT, run_at="2026-09-29T12:00:00+00:00"))


def _d(then) -> dict:
    """The page's data as the script reads it: the then-and-now and street
    payloads and GIBS's addresses, with test hosts."""
    return {"then": then, "street": STREET, "enso": {"now": "SON", "hide_above": 12}, "layers": [],
            "gibs": {"domains": "https://gibs/{layer}/{tms}/{start}--{end}.xml",
                     "tiles": "https://gibs/{layer}/{time}/{tms}/{z}/{y}/{x}.{ext}",
                     "static": "https://gibs/{layer}/{tms}/{z}/{y}/{x}.{ext}",
                     "acknowledge": "We acknowledge the use of imagery from NASA's GIBS.",
                     "satellites": {}}}


def _run(case, body: str, then=None, extra: str = ""):
    """What an async body prints as JSON, run after then-and-now's script and
    the street's, taken in as the page takes them."""
    js = stormdesk.script()
    functions = "\n".join(_js_function(js, name) for name in ENGINE)
    script = ('(function () {\n"use strict";\n' + PRELUDE + "var D = " + json.dumps(_d(then or THEN)) + ";\n"
              + functions + "\n" + extra + "\n" + thennow._JS + "\n" + street._JS
              + "\n(async function () {\n  try {\n" + body + "\n  } catch (err) {\n"
              "    console.log(JSON.stringify({error: String(err && err.stack || err)}));\n  }\n})();\n})();\n")
    return _node_json(case, script)


class TestThenScript(unittest.TestCase):
    """The script's own names: one that is also the page's would replace the
    page's function for the whole page."""

    @staticmethod
    def top_names(js: str) -> set:
        return set(re.findall(r"^  function ([A-Za-z_$][\w$]*)", js, re.M)) | {
            name for line in re.findall(r"^  var (.*)$", js, re.M)
            for name in re.findall(r"(?:^|, )([A-Za-z_$][\w$]*) =", line)}

    def test_no_name_of_the_script_is_one_of_the_page_s(self):
        mine = self.top_names(thennow._JS)
        self.assertIn("thenSrc", mine)
        self.assertEqual(sorted(mine & (self.top_names(stormdesk._JS) | self.top_names(worldmap._JS))), [])

    def test_a_point_is_named_by_the_page_s_one_rule_for_it(self):
        # Here's label and the entered place's were two copies of one rule.
        self.assertNotIn("function placeLabel", thennow._JS)
        self.assertIn("  function placeLabel(lon, lat) {", stormdesk._JS)
        self.assertIn("if (!label) label = placeLabel(lon, lat);", _js_function(stormdesk.script(), "hereAt"))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenTimesRuns(unittest.TestCase):
    """GIBS's times read and stepped through, a date checked, and the season
    around a date put in words."""

    S16 = '[["2015-01-01", "2015-12-19", 16], ["2016-01-01", "2016-12-18", 16]]'

    def test_gibs_times_are_read_as_spans_of_whole_days(self):
        got = _run(self, r"""
          var text = "<Domain>2001-01-01/2001-12-19/P16D,2000-03-05T00:00:00Z/2000-12-18T00:00:00Z/P16D," +
                     "2015-06-01,2016-01-01/2016-02-01/PT10M,2016-03-01/2016-02-01/P1D," +
                     "2016-02-30/2016-03-05/P1D</Domain>";
          console.log(JSON.stringify([parseSpans(text), parseSpans("<Domain></Domain>"), parseSpans("nonsense")]));
        """)
        self.assertEqual(got, [[["2000-03-05", "2000-12-18", 16], ["2001-01-01", "2001-12-19", 16],
                                ["2015-06-01", "2015-06-01", 1]], [], []])

    def test_a_date_snaps_to_the_nearest_time_listed_the_earlier_on_a_tie(self):
        got = _run(self, "var s = " + self.S16 + r""";
          console.log(JSON.stringify(["2015-01-05", "2015-01-10", "2015-12-31", "2015-12-25", "2014-06-01",
                                      "2017-03-01", "2015-01-09"].map(function (d) { return snapTime(s, d); })
                                     .concat([snapTime([], "2015-01-01")])));
        """)
        self.assertEqual(got, ["2015-01-01", "2015-01-17", "2016-01-01", "2015-12-19", "2015-01-01",
                               "2016-12-18", "2015-01-01", None])

    def test_a_step_goes_to_the_time_before_or_after_across_the_turn_of_a_year(self):
        got = _run(self, "var s = " + self.S16 + r""";
          console.log(JSON.stringify([["2016-01-01", -1], ["2015-12-19", 1], ["2014-06-01", 1], ["2015-01-01", 1],
                                      ["2015-01-20", 1], ["2016-12-18", 1], ["2015-01-01", -1], ["2015-01-17", -1],
                                      ["2015-01-10", -1], ["2017-05-01", -1]].map(function (p) {
            return stepTime(s, p[0], p[1]);
          })));
        """)
        self.assertEqual(got, ["2015-12-19", "2016-01-01", "2015-01-01", "2015-01-17", "2015-02-02", None,
                               None, "2015-01-01", "2015-01-01", "2016-12-18"])

    def test_a_daily_layer_with_a_gap_snaps_and_steps_over_it(self):
        got = _run(self, r"""
          var s = [["2000-02-24", "2000-04-25", 1], ["2000-04-27", "2000-06-01", 1]];
          console.log(JSON.stringify([snapTime(s, "2000-04-26"), stepTime(s, "2000-04-25", 1),
                                      stepTime(s, "2000-04-27", -1), snapTime(s, "1999-01-01"),
                                      stepTime(s, "2000-03-01", 1)]));
        """)
        self.assertEqual(got, ["2000-04-25", "2000-04-27", "2000-04-25", "2000-02-24", "2000-03-02"])

    def test_a_day_of_the_calendar_is_told_from_one_that_is_not(self):
        got = _run(self, r"""
          console.log(JSON.stringify(["2015-02-28", "2015-02-30", "", "2015-2-3", null, "2016-02-29",
                                      "2015-02-29", "2015-13-01"].map(realDay)));
        """)
        self.assertEqual(got, [True, False, False, False, False, True, False, False])

    def test_a_date_is_named_with_the_season_around_it(self):
        got = _run(self, r"""
          console.log(JSON.stringify(["2015-11-20", "2014-11-15", "2016-11-15", "2014-07-01", "2017-03-01",
                                      "2013-05-01"].map(ensoWords)));
        """)
        self.assertEqual(got, [
            "OND 2015, centred on Nov 2015: RONI +2.6, very strong El Niño, the 2014-16 episode",
            "OND 2014, centred on Nov 2014: RONI +0.6, weak El Niño, the 2014-16 episode",
            "OND 2016, centred on Nov 2016: RONI −0.7, weak La Niña, the 2016 episode, still going",
            "JJA 2014, centred on Jul 2014: RONI 0.0, neutral",
            "after the latest season on record, NDJ 2016 (RONI −0.6, weak La Niña, the 2016 episode, "
            "still going)",
            "no RONI season on record for May 2013"])

    def test_a_chip_names_the_season_short_and_the_latest_after_the_record(self):
        got = _run(self, r"""
          console.log(JSON.stringify(["2015-11-20", "2017-03-01", "2013-05-01"].map(ensoShort)));
        """)
        self.assertEqual(got, ["RONI +2.6, OND 2015", "latest RONI −0.6, NDJ 2016", ""])

    def test_months_on_the_strip_and_the_menu_s_events(self):
        got = _run(self, r"""
          var p = presetOf("ep0-after");
          console.log(JSON.stringify([monthIndex("2015-11-15"), monthIndex("2000-01-31"), monthText("2015-11-15"),
                                      [p.left, p.right], presetOf("nope")]));
        """)
        self.assertEqual(got, [190, 0, "Nov 2015", ["2015-11-15", "2016-11-15"], None])

    def test_the_seasons_are_read_again_when_a_refresh_brings_new_ones(self):
        got = _run(self, r"""
          var first = ensoShort("2015-11-20");
          D.then = JSON.parse(JSON.stringify(D.then));
          D.then.seasons.forEach(function (row) { if (row[0] === "2015-11") row[2] = 2.7; });
          console.log(JSON.stringify([first, ensoShort("2015-11-20")]));
        """)
        self.assertEqual(got, ["RONI +2.6, OND 2015", "RONI +2.7, OND 2015"])


# Esri's archive as the tests' network holds it: five releases, newest
# first 100, 90, 300 (older than 90 though numbered higher), 80 and 70, and
# one whose title has no date. At the pin, release 100's tilemap says the tile
# last changed in 90; 300's names no release, so it is 300's own; 80's is
# 80's; 70 has no tile there. 90 and 300 show one capture, taken 31 Oct 2021;
# 80's metadata has nothing at the pin.
WB_CONFIG = {str(n): {"itemID": f"i{n}", "itemTitle": f"World Imagery (Wayback {day})",
                      "itemURL": f"https://wb/tile/{n}/{{level}}/{{row}}/{{col}}",
                      "metadataLayerUrl": f"https://md/{day[:4]}_r{n}/MapServer"}
             for n, day in ((100, "2026-08-05"), (90, "2024-03-01"), (300, "2022-01-12"),
                            (80, "2019-06-26"), (70, "2014-02-20"))}
WB_CONFIG["5"] = {"itemID": "i5", "itemTitle": "World Imagery (Wayback)",
                  "itemURL": "https://wb/tile/5/{level}/{row}/{col}",
                  "metadataLayerUrl": "https://md/x_r5/MapServer"}
WB_CAPTURE = {"features": [{"attributes": {"SRC_DATE": 20211031, "SRC_RES": 0.5, "SRC_DESC": "WV02",
                                           "NICE_DESC": "Maxar"}}]}
WB_ROUTES = ("route('waybackconfig.json', " + json.dumps(WB_CONFIG) + ");\n"
             "route('tilemap/100/', {data: [1], select: [90]});\n"
             "route('tilemap/300/', {data: [1]});\n"
             "route('tilemap/80/', {data: [1], select: [80]});\n"
             "route('tilemap/70/', {data: [0]});\n"
             "route('md/2024_r90/', " + json.dumps(WB_CAPTURE) + ");\n"
             "route('md/2022_r300/', " + json.dumps(WB_CAPTURE) + ");\n"
             "route('md/2019_r80/', {features: []});\n")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenArchiveRuns(unittest.TestCase):
    """Esri's archive walked as Esri's Wayback app walks it: the releases,
    the versions of the tile under the pin, when each was taken, the one
    nearest a date, and each release's own credit."""

    def test_the_releases_come_newest_first_with_their_tiles(self):
        got = _run(self, WB_ROUTES + r"""
          var all = await wbReleases();
          console.log(JSON.stringify({ids: all.map(function (r) { return r.id; }),
                                      days: all.map(function (r) { return r.day; }),
                                      tiles: all[0].tiles, meta: all[0].meta, item: all[0].item,
                                      again: (await wbReleases()) === all, asked: ASKED.length}));
        """)
        self.assertEqual(got, {"ids": [100, 90, 300, 80, 70],
                               "days": ["2026-08-05", "2024-03-01", "2022-01-12", "2019-06-26", "2014-02-20"],
                               "tiles": "https://wb/tile/100/{z}/{y}/{x}", "meta": "https://md/2026_r100/MapServer",
                               "item": "i100", "again": True, "asked": 1})

    def test_a_list_that_did_not_come_is_asked_for_again(self):
        got = _run(self, r"""
          route('waybackconfig.json', 500);
          var first = await wbVersions(-60.025, -3.1);
          """ + WB_ROUTES + r"""
          var second = await wbVersions(-60.025, -3.1);
          console.log(JSON.stringify([first, second.list.map(function (v) { return v.id; })]));
        """)
        self.assertEqual(got, [{"list": [], "stopped": "config"}, [90, 80]])

    def test_the_walk_finds_each_release_the_tile_changed_in(self):
        got = _run(self, WB_ROUTES + r"""
          var walk = await wbWalk(await wbReleases(), wbTile(-60.025, -3.1));
          var asked = ASKED.filter(function (u) { return u.indexOf("tilemap") >= 0; });
          var again = await wbWalk(await wbReleases(), wbTile(-60.025, -3.1));
          console.log(JSON.stringify({ids: walk.list.map(function (r) { return r.id; }), stopped: walk.stopped,
                                      asked: asked, kept: again === walk,
                                      more: ASKED.filter(function (u) { return u.indexOf("tilemap") >= 0; }).length}));
        """)
        base = "https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tilemap/"
        self.assertEqual(got, {"ids": [90, 300, 80], "stopped": "", "kept": True, "more": 4,
                               "asked": [base + f"{n}/16/33332/21840" for n in (100, 300, 80, 70)]})

    def test_a_walk_cut_short_says_why_and_is_walked_again(self):
        got = _run(self, WB_ROUTES + r"""
          route('tilemap/300/', 500);
          var failed = await wbWalk(await wbReleases(), wbTile(-60.025, -3.1));
          route('tilemap/300/', {data: [1], select: [999]});
          var unknown = await wbWalk(await wbReleases(), wbTile(-60.025, -3.1));
          console.log(JSON.stringify([failed.list.map(function (r) { return r.id; }), failed.stopped,
                                      unknown.list.map(function (r) { return r.id; }), unknown.stopped]));
        """)
        self.assertEqual(got, [[90], "failed", [90], "unknown"])

    def test_versions_sharing_a_capture_are_one_and_the_newest_capture_is_first(self):
        got = _run(self, WB_ROUTES + r"""
          var v = await wbVersions(-60.025, -3.1);
          console.log(JSON.stringify({list: v.list, stopped: v.stopped, asked: ASKED.length,
                                      query: ASKED.filter(function (u) { return u.indexOf("md/2024_r90") >= 0; })[0]}));
        """)
        self.assertEqual(got["stopped"], "")
        self.assertEqual(got["asked"], 8)
        self.assertEqual(got["query"], "https://md/2024_r90/MapServer/7/query?geometry=-60.025000,-3.100000"
                                       "&geometryType=esriGeometryPoint&inSR=4326"
                                       "&spatialRel=esriSpatialRelIntersects&outFields=*"
                                       "&returnGeometry=false&f=json")
        self.assertEqual(got["list"], [
            {"id": 90, "day": "2024-03-01", "item": "i90", "tiles": "https://wb/tile/90/{z}/{y}/{x}",
             "capture": {"day": "2021-10-31", "provider": "Maxar", "sensor": "WV02", "res": 0.5},
             "when": "2021-10-31", "credit": ""},
            {"id": 80, "day": "2019-06-26", "item": "i80", "tiles": "https://wb/tile/80/{z}/{y}/{x}",
             "capture": None, "when": "2019-06-26", "credit": ""}])

    def test_a_metadata_query_that_hangs_is_given_up_after_20_s(self):
        got = _run(self, WB_ROUTES + r"""
          route('md/', 'hang');
          var done = null;
          wbVersions(-60.025, -3.1).then(function (v) { done = v; });
          await flush();
          advance(19999); await flush();
          var waiting = done === null;
          advance(1); await flush();
          """ + WB_ROUTES + r"""
          var again = await wbVersions(-60.025, -3.1);
          console.log(JSON.stringify({waiting: waiting, when: done.list.map(function (v) { return v.when; }),
                                      caps: done.list.map(function (v) { return v.capture; }),
                                      again: again.list.map(function (v) { return v.when; })}));
        """)
        # Given up, each version goes by its release; a failure is not kept,
        # so the next look asks again and has the capture.
        self.assertEqual(got, {"waiting": True, "when": ["2024-03-01", "2022-01-12", "2019-06-26"],
                               "caps": [None, None, None], "again": ["2021-10-31", "2019-06-26"]})

    def test_the_version_nearest_a_date_the_earlier_on_a_tie(self):
        got = _run(self, r"""
          var list = [{id: 90, when: "2021-10-31"}, {id: 80, when: "2019-06-26"}, {id: 70, when: "2014-02-20"}];
          console.log(JSON.stringify(["2016-01-01", "2020-08-13", "2020-08-28", "2020-08-29", "2030-01-01"].map(
            function (d) { return wbNearest(list, d).id; }).concat([wbNearest([], "2020-01-01")])));
        """)
        self.assertEqual(got, [70, 80, 80, 90, 90, None])

    def test_the_pin_s_tile_wraps_at_the_date_line(self):
        got = _run(self, r"""
          console.log(JSON.stringify([[179.99, -18.14], [-179.99, -18.14], [180, 0], [-180, 0], [540.5, 0],
                                      [-60.025, -3.1]].map(function (p) { var t = wbTile(p[0], p[1]); return [t.z, t.x, t.y]; })));
        """)
        self.assertEqual(got, [[16, 65534, 36126], [16, 1, 36126], [16, 0, 32768], [16, 0, 32768],
                               [16, 91, 32768], [16, 21840, 33332]])

    def test_each_release_is_credited_in_its_own_words(self):
        got = _run(self, r"""
          route('items/i90?', {accessInformation: " Esri, Maxar, Earthstar Geographics, and the GIS User Community "});
          route('items/i80?', 500);
          route('items/i70?', {accessInformation: ""});
          var words = [await wbCredit("i90"), await wbCredit("i80"), await wbCredit("i70")];
          var asked = ASKED.length;
          await wbCredit("i90"); await wbCredit("i80");
          console.log(JSON.stringify({words: words, asked: [asked, ASKED.length], url: ASKED[0]}));
        """)
        default = thennow.WAYBACK["credit"]
        self.assertEqual(got, {"words": ["Esri, Maxar, Earthstar Geographics, and the GIS User Community",
                                         default, default],
                               "asked": [3, 4],
                               "url": "https://www.arcgis.com/sharing/rest/content/items/i90?f=json"})


# Two versions of Manaus in Esri's archive, for the sides to show.
VERSIONS = ('[{id: 90, day: "2024-03-01", item: "i90", tiles: "https://wb/tile/90/{z}/{y}/{x}", '
            'capture: {day: "2021-10-31", provider: "Maxar", sensor: "WV02", res: 0.5}, when: "2021-10-31", '
            'credit: "Esri, Maxar, Earthstar Geographics, and the GIS User Community"}, '
            '{id: 80, day: "2019-06-26", item: "i80", tiles: "https://wb/tile/80/{z}/{y}/{x}", capture: null, '
            'when: "2019-06-26", credit: ""}]')


def _entered(source: str, a, b, z: float = 12) -> str:
    """The script's state with Manaus entered from a source, its two sides at
    a and b, and the view on the pin at zoom z."""
    return (f"S.then = thenFresh({{lon: -60.025, lat: -3.1, label: 'Manaus', source: '{source}', back: {{}}}});\n"
            f"S.then.versions = {VERSIONS};\n"
            f"S.then.got = {{a: {json.dumps(a)}, b: {json.dumps(b)}}};\n"
            f"S.x = mx(-60.025); S.y = my(-3.1); S.z = {z};\n"
            "thenApply();\n")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenLayerRuns(unittest.TestCase):
    """Each side a layer of the page's own kinds, drawn by the page's own tile
    code at its own date, never at today's."""

    def test_the_two_sides_are_compared_at_the_divider(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15") + r"""
          var a = LAYERS["then-a"];
          console.log(JSON.stringify([S.layer, S.second, S.compare, a.kind, a.global, a.time, a.zoom, a.then,
                                      LAYERS["then-b"].time]));
        """)
        self.assertEqual(got, ["then-a", "then-b", True, "imagery", "MODIS_Terra_CorrectedReflectance_TrueColor",
                               "2014-11-15", 9, True, "2015-11-15"])

    def test_each_nasa_side_is_drawn_at_its_own_day(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=3) + r"""
          S.x = 0.5; S.y = 0.5;
          function keys(c) { return c.cells.map(function (x) { return x.key; }).filter(function (k, i, all) { return all.indexOf(k) === i; }); }
          var a = cells("then-a", 0), b = cells("then-b", 0);
          console.log(JSON.stringify([keys(a), keys(b), a.cells.length, a.cells[0].url, Object.keys(a.used)]));
        """)
        self.assertEqual(got, [["2014-11-15"], ["2015-11-15"], 16,
                               "https://gibs/MODIS_Terra_CorrectedReflectance_TrueColor/2014-11-15/"
                               "GoogleMapsCompatible_Level9/3/2/2.jpeg",
                               ["MODIS_Terra_CorrectedReflectance_TrueColor"]])

    def test_a_side_with_no_day_draws_nothing_not_the_latest(self):
        got = _run(self, _entered("modis", None, "2015-11-15", z=3) + r"""
          // GIBS lists a latest day: the page's other layers draw it.
          frameOf = function () { return {t: 0, key: "2026-09-28"}; };
          var a = cells("then-a", 0), b = cells("then-b", 0);
          console.log(JSON.stringify([a.cells.length, Object.keys(a.used), b.cells[0].key]));
        """)
        self.assertEqual(got, [0, [], "2015-11-15"])

    def test_landsat_and_sentinel_2_sides_draw_both_imagers_at_their_own_days(self):
        got = _run(self, _entered("hls", "2014-11-13", "2015-11-20") + r"""
          function what(c) {
            var names = {}, keys = {};
            c.cells.forEach(function (x) { names[x.name] = true; keys[x.key] = true; });
            return [Object.keys(names).sort(), Object.keys(keys)];
          }
          console.log(JSON.stringify([what(cells("then-a", 0)), what(cells("then-b", 0)), S.day]));
        """)
        self.assertEqual(got, [[["HLS_L30", "HLS_S30"], ["2014-11-13"]], [["HLS_L30", "HLS_S30"], ["2015-11-20"]],
                               None])

    def test_archive_sides_draw_their_own_release_s_tiles(self):
        got = _run(self, _entered("archive", 80, 90, z=16) + r"""
          var a = cells("then-a", 0), l = LAYERS["then-a"];
          var at = a.cells.filter(function (c) { return c.c === 21840 && c.r === 33332; })[0];
          console.log(JSON.stringify({url: at.url, name: at.name, map: at.map, wb: at.wb, credit: at.credit,
                                      all: a.cells.every(function (c) { return c.url.indexOf("https://wb/tile/80/16/") === 0; }),
                                      zoom: l.zoom, right: LAYERS["then-b"].credit, used: Object.keys(a.used)}));
        """)
        esri = "Powered by Esri. Source: "
        self.assertEqual(got, {"url": "https://wb/tile/80/16/33332/21840", "name": "wb80", "map": "then-a",
                               "wb": 80, "credit": esri + thennow.WAYBACK["credit"] + ".", "all": True, "zoom": 19,
                               "right": esri + "Esri, Maxar, Earthstar Geographics, and the GIS User Community.",
                               "used": ["then-a"]})

    def test_an_archive_side_s_credit_ends_its_sentence_before_the_names_credit(self):
        # Joined with the names' credit, it ran on: "...GIS User Community Roads and names: ...".
        got = _run(self, _entered("archive", 80, 90, z=16) + r"""
          var before = [LAYERS["then-a"].credit, LAYERS["then-b"].credit];
          S.then.versions[0].credit = "Esri and the GIS User Community.";
          thenApply();
          console.log(JSON.stringify([before, LAYERS["then-b"].credit]));
        """)
        self.assertEqual(got, [["Powered by Esri. Source: " + thennow.WAYBACK["credit"] + ".",
                                "Powered by Esri. Source: Esri, Maxar, Earthstar Geographics, and the GIS User "
                                "Community."],
                               "Powered by Esri. Source: Esri and the GIS User Community."])

    def test_an_archive_side_with_no_version_draws_nothing(self):
        got = _run(self, _entered("archive", None, 90, z=16) + r"""
          console.log(JSON.stringify([cells("then-a", 0).cells.length, cells("then-b", 0).cells.length > 0]));
        """)
        self.assertEqual(got, [0, True])

    def test_roads_and_names_go_over_either_side_credited_in_esri_s_words(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15") + r"""
          var on = overSpecs("then-a"), named = [labelled("then-a"), labelled("then-b")];
          S.then.source = "archive"; S.then.got = {a: 80, b: 90}; thenApply();
          var archive = overSpecs("then-b")[0].cells[0].credit;
          S.then.names = false; thenApply();
          console.log(JSON.stringify({keys: on.map(function (s) { return s.key; }), z: on[0].cells[0].z,
                                      url: on[1].cells[0].url.split("/")[2], map: on[0].cells[0].map,
                                      credit: on[0].cells[0].credit, archive: archive, named: named,
                                      off: [overSpecs("then-a").length, labelled("then-a")]}));
        """)
        self.assertEqual(got, {"keys": ["o0", "o1"], "z": 12, "url": "places", "map": "then-a-names",
                               "credit": "Powered by Esri. " + thennow.NAMES_CREDIT,
                               "archive": thennow.NAMES_CREDIT, "named": [True, True], "off": [0, False]})

    def test_a_side_s_failed_tiles_bring_the_coastline_and_its_words(self):
        got = _run(self, _entered("hls", "2014-11-13", "2015-11-20") + r"""
          S.inView = cells("then-a", 0).used;
          var before = [baseDown(), nasaDown(S.inView)];
          GOT["HLS_L30/2014-11-13"] = {ok: 0, failed: 3}; GOT["HLS_S30/2014-11-13"] = {ok: 0, failed: 2};
          var after = [baseDown(), nasaDown(S.inView)];
          S.then.source = "archive"; S.then.got = {a: 80, b: 90}; thenApply();
          var map = [baseDown()];
          MAPS["then-a"] = {ok: 0, failed: 4};
          map.push(baseDown());
          console.log(JSON.stringify([before, after, map]));
        """)
        self.assertEqual(got, [[False, False], [True, True], [False, True]])

    def test_an_archive_tile_past_zoom_13_that_esri_has_not_is_drawn_coarser(self):
        js = stormdesk.script()
        extra = "\n".join(_js_function(js, n) for n in ("tally", "againIn", "tileFailed"))
        got = _run(self, r"""
          route("tilemap/80/17/", {data: [0]});
          route("tilemap/80/18/", {data: [1]});
          function tile(z, c, r, url) { return {_wb: 80, _z: z, _c: c, _r: r, _name: "wb80", _map: "then-a", _url: url, style: {}}; }
          tileFailed.call(tile(17, -3, 70000, "u17"));
          tileFailed.call(tile(18, 5, 7, "u18"));
          tileFailed.call(tile(13, 5, 7, "u13"));
          await flush();
          console.log(JSON.stringify({nodata: Object.keys(NODATA), failed: MAPS["then-a"].failed,
                                      asked: ASKED.map(function (u) { return u.split("/MapServer/")[1]; })}));
        """, extra=extra)
        # Esri has no tile at zoom 17 there: the zoom-16 tile is drawn. At 18
        # it has one, and at 13 it is not asked: each fails as any map tile does.
        self.assertEqual(got, {"nodata": ["wb80/17/131069/70000"], "failed": 2,
                               "asked": ["tilemap/80/17/70000/131069", "tilemap/80/18/7/5"]})


class TestThenHooks(unittest.TestCase):
    """Entered, nothing of today's is drawn over another day's ground: the
    storms, the outlook, the invests, the regions, NASA's reference overlays,
    the ocean and flood tiles, and the El Nino composite and its keys."""

    def test_the_composite_its_keys_and_nasa_s_tiles_stand_aside(self):
        js = worldmap._JS
        self.assertIn("var name = S.then ? null : S.enso.variable;", _js_function(js, "drawComposite"))
        self.assertIn('name = S.then ? null : S.enso.variable;', _js_function(js, "ensoLegend"))
        self.assertIn("on = !!S.enso.tiles[l.id] && !S.then;", _js_function(js, "ensoTileLegend"))
        self.assertIn("if (S.z > D.enso.hide_above || S.then) return specs;", _js_function(js, "ensoTileSpecs"))
        self.assertIn('S.refs[l.id] && S.imagery === "ok" && !S.then', _js_function(stormdesk._JS, "tiles"))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_entered_the_marks_are_the_pin_the_towns_and_the_storm_picked(self):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "origin", "near", "copies", "clamp", "mx", "my", "rad", "esc", "pct",
            "labelled", "labelledBase", "namedAt", "townsWhy", "drawMarks", "ensoLabels",
            "categoryOf", "shortAt", "pad2", "zulu"))
        got = _node_json(self, r"""
var TILE = 256, HOUR = 3600000, NM = 1.852, CIRCUMFERENCE = 40075.017;
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
var LAYERS = {"then-a": {kind: "imagery", then: true, over: null}, "then-b": {kind: "imagery", then: true, over: null}};
var PLACES = [["Itacoatiara", "Brazil", "", 100000, -58.44, -3.14, false]], BYPOP = null;
var D = {outlook: [{key: "a1", lon: -61, lat: -2, level: "high", label: "Area", centre: "NHC",
                    chance_2day: 40, chance_7day: 60}],
         invests: [{name: "Invest 90L", lon: -59, lat: -4, wind: 25, track: []}], style: {outlook: {}},
         enso: {boxes: [{lon0: -61, lon1: -59, lat0: -4, lat1: -2, label: "Box", anomaly: null}]}};
var drawn = 0;
var st = {id: "al01", x0: mx(-60), hue: "red", d: {id: "al01", title: "Storm", lon: -60, lat: -3,
          forecast: [{lon: -60.5, lat: -3.5, hour: 24, day: true, t: "2026-10-09T12:00:00Z"}],
          exposure: [{place: "Town", lon: -60.2, lat: -3.2}],
          watches: [], surge: [], view: {}}};
var STORMS = [st], BYID = {al01: st}, marksG = {innerHTML: ""};
function base() { drawn++; return {t: 0, image: false}; }
function centreAt() { return {lon: -60, lat: -3, category: 1, wind: 60, radii: {}}; }
function inside() { return 0; }
function when() { return 0; }
""" + functions + r"""
var S = {x: mx(-60), y: my(-3), z: 7, w: 800, h: 600, scrub: 0, selected: "al01",
         show: {towns: true, outlook: true, places: true, watches: true, surge: true},
         pin: {lon: -60.025, lat: -3.1, label: "Manaus"}, enso: {boxes: true, regions: false},
         layer: "then-a", second: "then-b", compare: true, split: 0.5};
function marks(then) {
  S.then = then; drawn = 0; drawMarks();
  var h = marksG.innerHTML;
  return {pin: h.indexOf('class="pin"') >= 0, town: h.indexOf(">Itacoatiara<") >= 0, storm: h.indexOf("data-storm") >= 0,
          dots: h.indexOf('class="dot"') >= 0, area: h.indexOf("data-area") >= 0, invest: h.indexOf("Invest 90L") >= 0,
          box: h.indexOf(">Box<") >= 0, places: h.indexOf(">Town<") >= 0, day: h.indexOf(">9 Oct 12Z<") >= 0,
          base: drawn};
}
var entered = marks({}), out = marks(null);
S.selected = null;
console.log(JSON.stringify([entered, out, marks({})]));
""")
        # Entered, the storm picked stays, with its forecast and its days, to
        # be played over the place; nothing else of today's is drawn.
        self.assertEqual(got[0], {"pin": True, "town": True, "storm": True, "dots": True, "area": False,
                                  "invest": False, "box": False, "places": False, "day": True, "base": 1})
        self.assertEqual(got[1], {"pin": True, "town": True, "storm": True, "dots": True, "area": True,
                                  "invest": True, "box": True, "places": True, "day": True, "base": 1})
        self.assertEqual(got[2], {"pin": True, "town": True, "storm": False, "dots": False, "area": False,
                                  "invest": False, "box": False, "places": False, "day": False, "base": 0})

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_entered_no_geometry_of_today_s_is_drawn_but_the_storm_picked(self):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "clamp", "rad", "mx", "my", "near", "X", "Y", "line", "pt", "geoReach", "repeated", "buildGeo"))
        got = _node_json(self, r"""
var TILE = 256, UNIT = 1048576, NM = 1.852, THRESHOLDS = ["34", "50", "64"], ORDER = [];
var geoDirty = true, geoRef = null, geoCopies = 0, geoLo = 0, geoHi = 0, geoExt = null, geoG = {innerHTML: ""};
var D = {outlook: [{lon: -61, lat: -2, level: "high", area: [[-62, -1], [-60, -1], [-60, -3]], arrow: []}],
         invests: [], style: {outlook: {}, products: {}}};
var STORMS = [{id: "al01", x0: mx(-60), hue: "red", d: {track: [{lon: -58, lat: -2}, {lon: -60, lat: -3}],
               forecast: [{lon: -61, lat: -4}], cone: null, surge: null, watches: null}}];
var BYID = {al01: STORMS[0]};
var geo = 0;
function ensoGeo() { geo++; return '<path class="region"/>'; }
""" + functions + r"""
var S = {x: mx(-60), y: my(-3), z: 5, w: 800, h: 600, show: {outlook: true, radii: false}, selected: null};
function draw(then) { S.then = then; buildGeo(); var h = geoG.innerHTML;
  return [h.indexOf('class="track"') >= 0, h.indexOf('class="area"') >= 0, h.indexOf('class="region"') >= 0, geoCopies]; }
var none = draw({}), out = draw(null);
S.selected = "al01";
console.log(JSON.stringify([none, out, draw({})]));
""")
        # Entered, the storm picked is drawn, its track and forecast, and no
        # other geometry of today's: not the outlook, not El Nino's regions.
        self.assertEqual(got, [[False, False, False, 0], [True, True, True, 0], [True, False, False, 0]])


def _want(source: str, a: str, b: str, preset: str = "") -> str:
    """Manaus entered from a source, asking for dates a and b; preset names
    the event they came from, "" for the reader's own."""
    return (f"S.then = thenFresh({{lon: -60.025, lat: -3.1, label: 'Manaus', source: '{source}', back: {{}}}});\n"
            f"S.then.want = {{a: '{a}', b: '{b}'}}; S.then.preset = '{preset}';\n"
            "S.x = mx(-60.025); S.y = my(-3.1); S.z = 8;\n")


# What the tests read of the entered place after it is resolved.
SHOWN = ("function shown() { var T = S.then; return JSON.parse(JSON.stringify({got: T.got, want: T.want, "
         "look: T.look, note: T.note, apart: T.apart, fail: T.fail})); }\n")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenResolveRuns(unittest.TestCase):
    """Each side's date found in its archive: the time GIBS lists nearest it,
    the version of the place Esri captured nearest it, or the nearest day
    with an image at the pin; the earlier on the left."""

    def test_nasa_sides_take_the_day_gibs_lists_nearest_their_dates(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + SHOWN + r"""
          route("gibs/MODIS_Terra_CorrectedReflectance_TrueColor/", "<Domain>2000-02-24/2026-09-28/P1D</Domain>");
          thenResolve();
          var asking = [S.then.look.a, S.then.look.b];
          await flush();
          var first = shown();
          thenResolve(); await flush();
          console.log(JSON.stringify({asking: asking, first: first, asked: ASKED, layer: LAYERS["then-b"].time,
                                      imagery: S.imagery}));
        """)
        self.assertEqual(got["asking"], ["asking", "asking"])
        self.assertEqual(got["first"], {"got": {"a": "2014-11-15", "b": "2015-11-15"},
                                        "want": {"a": "2014-11-15", "b": "2015-11-15"},
                                        "look": {"a": "", "b": ""}, "note": {"a": "", "b": ""}, "apart": "",
                                        "fail": {"gibs": False, "wayback": False}})
        # Asked once a visit, from the archive's first day to tomorrow.
        self.assertEqual(got["asked"], ["https://gibs/MODIS_Terra_CorrectedReflectance_TrueColor/"
                                        "GoogleMapsCompatible_Level9/2000-02-24--2026-09-30.xml"])
        self.assertEqual((got["layer"], got["imagery"]), ("2015-11-15", "ok"))

    def test_vegetation_sides_take_the_16_day_composite_nearest(self):
        got = _run(self, _want("ndvi", "2014-11-15", "2015-11-15") + SHOWN + r"""
          route("gibs/MODIS_Terra_L3_NDVI_16Day/",
                "<Domain>2014-01-01/2014-12-19/P16D,2015-01-01/2015-12-19/P16D</Domain>");
          thenResolve(); await flush();
          console.log(JSON.stringify(shown().got));
        """)
        self.assertEqual(got, {"a": "2014-11-17", "b": "2015-11-17"})

    def test_a_date_outside_the_archive_takes_its_nearest_end_and_says_so(self):
        got = _run(self, _want("sst", "2001-03-15", "2026-09-29") + SHOWN + r"""
          route("gibs/GHRSST", "<Domain>2002-09-01/2026-09-27/P1D</Domain>");
          thenResolve(); await flush();
          var latest = shown();
          route("gibs/GHRSST", "<Domain>2002-09-01/2026-06-30/P1D</Domain>");
          SPANS = {};
          thenResolve(); await flush();
          console.log(JSON.stringify([latest.got, latest.note, shown().got.b, shown().note.b]));
        """)
        self.assertEqual(got, [{"a": "2002-09-01", "b": "2026-09-27"},
                               {"a": "asked for 15 Mar 2001, before the first it holds, 1 Sep 2002", "b": ""},
                               "2026-06-30", "asked for 29 Sep 2026, after the latest it holds, 30 Jun 2026"])

    def test_an_event_s_dates_on_one_image_move_the_left_to_the_one_before(self):
        domain = 'route("gibs/MODIS_Terra_Corr", "<Domain>2010-01-01,2012-01-01</Domain>");\n'
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15", preset="ep0-before") + SHOWN + domain + r"""
          thenResolve(); await flush();
          var event = shown();
          S.then.preset = ""; thenResolve(); await flush();
          console.log(JSON.stringify([event.got, event.apart, shown().got, shown().apart]));
        """)
        self.assertEqual(got, [{"a": "2010-01-01", "b": "2012-01-01"},
                               "Both dates fell on the same image, so the left side shows the one before it.",
                               {"a": "2012-01-01", "b": "2012-01-01"}, ""])

    def test_the_earlier_date_goes_on_the_left(self):
        got = _run(self, _want("modis", "2015-11-15", "2014-11-15") + SHOWN + r"""
          route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-28/P1D</Domain>");
          thenResolve(); await flush();
          console.log(JSON.stringify([shown().got, shown().want]));
        """)
        self.assertEqual(got, [{"a": "2014-11-15", "b": "2015-11-15"}, {"a": "2014-11-15", "b": "2015-11-15"}])

    def test_a_date_typed_earlier_than_the_other_side_s_changes_places_and_says_so(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + MODIS_DAYS + r"""
          thenResolve(); await flush();
          function said() { return thenNotes(S.then).replace(HIDDEN, "").trim(); }
          $("then-date-b").fire("change", {target: {value: "2013-11-15"}}); await flush();
          var swapped = [S.then.got.a, S.then.got.b, said()];
          $("then-date-a").fire("change", {target: {value: "2013-12-01"}}); await flush();
          console.log(JSON.stringify([swapped, S.then.got.a, said()]));
        """)
        # Typed on the right, the earlier date goes to the left; the next date
        # typed, put where it was typed, takes the words away.
        self.assertEqual(got, [["2013-11-15", "2014-11-15",
                                "The earlier date goes on the left, so the two sides changed places."],
                               "2013-12-01", ""])

    def test_an_event_s_side_moved_apart_keeps_its_date_once_the_dates_are_the_reader_s(self):
        domain = 'route("gibs/MODIS_Terra_Corr", "<Domain>2010-01-01,2012-01-01,2013-01-01</Domain>");\n'
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15", preset="ep0-before") + domain + r"""
          thenResolve(); await flush();
          var event = [S.then.got.a, S.then.got.b];
          $("then-date-b").fire("change", {target: {value: "2013-02-01"}}); await flush();
          console.log(JSON.stringify([event, S.then.got, S.then.want.a, S.then.preset]));
        """)
        # Both of the event's dates fell on 1 Jan 2013, so the left showed the
        # image before. A date typed on the right asks both sides again: the
        # left stays on the image it showed, not on the one both shared.
        self.assertEqual(got, [["2012-01-01", "2013-01-01"], {"a": "2012-01-01", "b": "2013-01-01"},
                               "2012-01-01", ""])

    def test_a_walk_cut_short_brings_retry_which_walks_again(self):
        got = _run(self, WB_ROUTES + _want("archive", "2019-01-01", "2022-01-01") + r"""
          route('tilemap/300/', 500);
          thenResolve(); await flush();
          var cut = [thenDown(), S.then.stopped, S.then.versions.length];
          route('tilemap/300/', {data: [1]});
          thenRetry(); await flush();
          var whole = [thenDown(), S.then.stopped, S.then.versions.length];
          // A release the list does not hold: Retry asks for the list again.
          route('tilemap/300/', {data: [1], select: [999]});
          WB.walks = {}; thenResolve(); await flush();
          var unknown = [thenDown(), S.then.stopped];
          function lists() { return ASKED.filter(function (u) { return u.indexOf("waybackconfig") >= 0; }).length; }
          var before = lists();
          thenRetry(); await flush();
          console.log(JSON.stringify([cut, whole, unknown, lists() - before]));
        """)
        self.assertEqual(got, [["Esri’s archive answered in part.", "failed", 1], ["", "", 2],
                               ["Esri’s archive answered in part.", "unknown"], 1])

    def test_gibs_not_answering_is_said_on_each_side_and_asked_again(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + SHOWN + r"""
          route("gibs/MODIS_Terra_Corr", 500);
          thenResolve(); await flush();
          var failed = shown();
          route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-28/P1D</Domain>");
          thenResolve(); await flush();
          console.log(JSON.stringify([failed.look, failed.fail.gibs, failed.got, shown().got, shown().fail.gibs,
                                      ASKED.length]));
        """)
        self.assertEqual(got, [{"a": "no answer", "b": "no answer"}, True, {"a": None, "b": None},
                               {"a": "2014-11-15", "b": "2015-11-15"}, False, 2])

    def test_archive_sides_take_the_versions_captured_nearest_their_dates(self):
        got = _run(self, WB_ROUTES + _want("archive", "2019-01-01", "2022-01-01") + SHOWN + r"""
          route("items/i90?", {accessInformation: "Esri, Maxar, Earthstar Geographics, and the GIS User Community"});
          thenResolve();
          var asking = [S.then.look.a, S.then.look.b];
          await flush();
          console.log(JSON.stringify({asking: asking, shown: shown(), versions: S.then.versions.length,
                                      right: LAYERS["then-b"].credit, left: LAYERS["then-a"].tiles}));
        """)
        self.assertEqual(got["asking"], ["asking", "asking"])
        self.assertEqual(got["shown"]["got"], {"a": 80, "b": 90})
        self.assertEqual(got["shown"]["note"], {"a": "asked for 1 Jan 2019, before the first it holds, 26 Jun 2019",
                                                "b": "asked for 1 Jan 2022, after the latest it holds, 31 Oct 2021"})
        self.assertEqual((got["versions"], got["left"]), (2, "https://wb/tile/80/{z}/{y}/{x}"))
        self.assertEqual(got["right"], "Powered by Esri. Source: Esri, Maxar, Earthstar Geographics, and the GIS "
                                       "User Community.")

    def test_an_event_s_dates_on_one_capture_move_the_left_to_the_older(self):
        got = _run(self, WB_ROUTES + _want("archive", "2025-09-29", "2026-09-29", preset="now") + SHOWN + r"""
          thenResolve(); await flush();
          console.log(JSON.stringify([shown().got, shown().apart]));
        """)
        self.assertEqual(got, [{"a": 80, "b": 90},
                               "Both dates fell on the same capture, so the left side shows the one before it."])

    def test_a_capture_slow_to_answer_leaves_its_version_to_its_release_meanwhile(self):
        got = _run(self, WB_ROUTES + _want("archive", "2019-01-01", "2022-01-01") + SHOWN + r"""
          route("md/2024_r90/", "hang");
          thenResolve(); await flush();
          var waiting = shown().look;
          advance(2999); await flush();
          var still = shown().look;
          advance(1); await flush();
          var early = [shown().got, shown().look, LAYERS["then-b"].tiles,
                       (S.then.versions || []).map(function (v) { return v.when; })];
          advance(17000); await flush();
          console.log(JSON.stringify({waiting: waiting, still: still, early: early, late: shown().got}));
        """)
        # The walk has answered and release 90's capture has not: three seconds
        # on, both sides are drawn, 90 going by its release, 1 Mar 2024, and
        # 300's capture of 31 Oct 2021 the nearest the right's date.
        self.assertEqual(got["waiting"], {"a": "asking", "b": "asking"})
        self.assertEqual(got["still"], {"a": "asking", "b": "asking"})
        self.assertEqual(got["early"], [{"a": 80, "b": 300}, {"a": "", "b": ""}, "https://wb/tile/300/{z}/{y}/{x}",
                                        ["2024-03-01", "2021-10-31", "2019-06-26"]])
        # Given up at 20 s, 90's capture is not given: the sides stay as drawn.
        self.assertEqual(got["late"], {"a": 80, "b": 300})

    def test_esri_s_archive_not_answering_or_holding_nothing_is_said(self):
        got = _run(self, _want("archive", "2019-01-01", "2022-01-01") + SHOWN + r"""
          route("waybackconfig.json", 500);
          thenResolve(); await flush();
          var down = shown();
          """ + WB_ROUTES + r"""
          route("tilemap/100/", {data: [0]});
          thenResolve(); await flush();
          console.log(JSON.stringify([down.look, down.fail.wayback, shown().look, shown().got, shown().fail.wayback]));
        """)
        self.assertEqual(got, [{"a": "no answer", "b": "no answer"}, True, {"a": "none", "b": "none"},
                               {"a": None, "b": None}, False])

    def test_landsat_and_sentinel_2_sides_take_the_nearest_day_with_an_image(self):
        got = _run(self, _want("hls", "2014-11-15", "2015-11-15") + SHOWN + r"""
          paint("HLS_", [0, 0, 0, 0]);
          paint("HLS_S30/2014-11-13/", [10, 20, 30, 255]);
          paint("HLS_S30/2014-11-17/", [10, 20, 30, 255]);
          paint("HLS_L30/2015-11-20/", [10, 20, 30, 255]);
          S.imagery = "pending";
          thenResolve();
          var looking = [S.then.look.a, S.then.look.b];
          await flush(400);
          console.log(JSON.stringify({looking: looking, got: shown().got, look: shown().look, imagery: S.imagery,
                                      first: IMAGES[0]}));
        """)
        # 13 Nov is two days back and 17 Nov two on: the list is looked at
        # day, a day back, a day on, and so on, so the earlier comes first.
        self.assertEqual(got, {"looking": ["looking", "looking"], "got": {"a": "2014-11-13", "b": "2015-11-20"},
                               "look": {"a": "", "b": ""}, "imagery": "ok",
                               "first": "https://gibs/HLS_L30/2014-11-15/GoogleMapsCompatible_Level12/12/2083/1365.png"})

    def test_no_image_within_20_days_or_no_answer_is_said(self):
        got = _run(self, _want("hls", "2014-11-15", "2015-11-15") + SHOWN + r"""
          paint("HLS_", [0, 0, 0, 0]);
          thenResolve(); await flush(400);
          var none = shown();
          PAINT = []; looks = {};
          thenResolve(); await flush(400);
          console.log(JSON.stringify([none.look, none.got, shown().look, shown().fail.gibs]));
        """)
        self.assertEqual(got, [{"a": "none", "b": "none"}, {"a": None, "b": None},
                               {"a": "no answer", "b": "no answer"}, True])

    def test_offline_nothing_is_asked(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + SHOWN + r"""
          S.imagery = "offline";
          thenResolve(); await flush();
          console.log(JSON.stringify([ASKED.length, shown().fail]));
        """)
        self.assertEqual(got, [0, {"gibs": True, "wayback": False}])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenFollowsTheRun(unittest.TestCase):
    """A run taken in place while a place is entered: sides set by an event go
    to the dates the new build gives it, NASA's days are asked for again, and
    the reader's own dates stand."""

    NO_PARTS = "var doc = {getElementById: function () { return null; }};\n"

    def test_sides_set_by_an_event_go_to_the_new_build_s_dates_for_it(self):
        # Built on 29 September: a year ago and the latest moved on a day.
        got = _run(self, _want("modis", "2025-09-28", "2026-09-28", preset="now") + SHOWN + self.NO_PARTS + r"""
          route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-29/P1D</Domain>");
          thenResolve(); await flush();
          var before = shown();
          thenRefreshed(doc); await flush();
          console.log(JSON.stringify([before.got, shown().want, shown().got, S.then.preset]));
        """)
        self.assertEqual(got, [{"a": "2025-09-28", "b": "2026-09-28"}, {"a": "2025-09-29", "b": "2026-09-29"},
                               {"a": "2025-09-29", "b": "2026-09-29"}, "now"])

    def test_nasa_s_days_are_asked_for_again_so_the_latest_is_the_latest(self):
        got = _run(self, _want("modis", "2025-09-29", "2026-09-29") + SHOWN + self.NO_PARTS + r"""
          route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-27/P1D</Domain>");
          thenResolve(); await flush();
          var first = shown().got.b;
          route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-29/P1D</Domain>");
          thenRefreshed(doc); await flush();
          console.log(JSON.stringify([first, shown().got.b, shown().want,
                                      ASKED.filter(function (u) { return u.indexOf("MODIS_Terra_Corr") >= 0; }).length]));
        """)
        # The reader's own dates stand, and the latest day NASA has given since is shown.
        self.assertEqual(got, ["2026-09-27", "2026-09-29", {"a": "2025-09-29", "b": "2026-09-29"}, 2])

    def test_the_sides_stand_as_they_are_while_nasa_is_asked_again(self):
        # Their words and the reading at the pin too: nothing is said to be
        # asked for, and nothing read again, unless an answer moves a side;
        # no answer leaves them as they were.
        got = _run(self, _want("sst", "2014-11-15", "2015-11-15") + SHOWN + self.NO_PARTS + r"""
          route("gibs/GHRSST", "<Domain>2002-09-01/2026-09-27/P1D</Domain>");
          paint("Anomalies/2014-11-15/", [237, 237, 152, 255]);
          paint("Anomalies/2015-11-15/", [249, 1, 19, 255]);
          thenResolve(); await flush();
          var read = S.then.read, images = IMAGES.length;
          thenRefreshed(doc);
          var asking = shown().look;
          await flush();
          var answered = [shown().look, S.then.read === read, IMAGES.length - images];
          route("gibs/GHRSST", new Error("GIBS is down"));
          thenRefreshed(doc); await flush();
          console.log(JSON.stringify([asking, answered, shown().look, shown().got, shown().fail.gibs,
                                      S.then.read === read,
                                      ASKED.filter(function (u) { return u.indexOf("GHRSST") >= 0; }).length]));
        """)
        self.assertEqual(got, [{"a": "", "b": ""}, [{"a": "", "b": ""}, True, 0], {"a": "", "b": ""},
                               {"a": "2014-11-15", "b": "2015-11-15"}, False, True, 3])

    def test_landsat_and_sentinel_2_days_are_looked_for_again_as_quietly(self):
        # A day NASA had not given when the side was found, given since. A
        # look that finds no image, or no answer, leaves the sides as they are.
        got = _run(self, _want("hls", "2014-11-15", "2015-11-15") + SHOWN + self.NO_PARTS + r"""
          paint("HLS_", [0, 0, 0, 0]);
          paint("HLS_S30/2014-11-15/", [10, 20, 30, 255]);
          paint("HLS_L30/2015-11-20/", [10, 20, 30, 255]);
          thenResolve(); await flush(400);
          var first = shown().got;
          paint("HLS_S30/2015-11-15/", [10, 20, 30, 255]);
          thenRefreshed(doc);
          var looking = shown().look;
          await flush(400);
          var moved = [shown().got, shown().look];
          PAINT = []; paint("HLS_", [0, 0, 0, 0]);
          thenRefreshed(doc); await flush(400);
          var none = [shown().got, shown().look];
          PAINT = [];
          thenRefreshed(doc); await flush(400);
          console.log(JSON.stringify([first, looking, moved, none, [shown().got, shown().look, shown().fail.gibs]]));
        """)
        sides, quiet = {"a": "2014-11-15", "b": "2015-11-15"}, {"a": "", "b": ""}
        self.assertEqual(got, [{"a": "2014-11-15", "b": "2015-11-20"}, quiet, [sides, quiet], [sides, quiet],
                               [sides, quiet, False]])

    def test_esri_s_captures_stay_as_they_were_found(self):
        got = _run(self, _entered("archive", 80, 90) + self.NO_PARTS + r"""
          S.then.preset = ""; S.then.want = {a: "2019-06-26", b: "2024-03-01"};
          thenRefreshed(doc); await flush();
          console.log(JSON.stringify([ASKED.length, IMAGES.length]));
        """)
        self.assertEqual(got, [0, 0])

    def test_sides_on_an_event_whose_dates_stand_are_left_as_they_are(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15", preset="ep0-before") + SHOWN + MODIS_DAYS
                   + self.NO_PARTS + r"""
          thenResolve(); await flush();
          var before = [shown(), ASKED.length];
          thenRefreshed(doc); await flush();
          console.log(JSON.stringify([before[0].got, before[1], shown().got, ASKED.length, S.then.preset]));
        """)
        # NASA is asked again, and its answer leaves them where they are.
        self.assertEqual(got, [{"a": "2014-11-15", "b": "2015-11-15"}, 1,
                               {"a": "2014-11-15", "b": "2015-11-15"}, 2, "ep0-before"])

    def test_sides_on_an_event_the_new_build_no_longer_offers_keep_their_dates(self):
        got = _run(self, _want("modis", "2009-07-15", "2010-07-15", preset="ep5-before") + SHOWN + MODIS_DAYS
                   + self.NO_PARTS + r"""
          thenResolve(); await flush();
          var asked = ASKED.length;
          thenRefreshed(doc); await flush();
          console.log(JSON.stringify([shown().want, shown().got, ASKED.length - asked, S.then.preset]));
        """)
        self.assertEqual(got, [{"a": "2009-07-15", "b": "2010-07-15"}, {"a": "2009-07-15", "b": "2010-07-15"}, 1, ""])

    def test_menus_the_new_build_left_as_they_were_are_not_written_again(self):
        # The event menu, open as the run is taken, stays open: only a change
        # is written.
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15", preset="ep0-before") + MODIS_DAYS + r"""
          var writes = {};
          ["then-event", "then-strip", "then-years"].forEach(function (id) {
            var el = $(id);
            el.markup = "<option>" + id + "</option>"; writes[id] = 0;
            Object.defineProperty(el, "innerHTML", {get: function () { return this.markup; },
                                                    set: function (html) { writes[id]++; this.markup = html; }});
          });
          function build(html) {
            return {getElementById: function (id) {
              return {innerHTML: html(id), getAttribute: function () { return "0 0 320 40"; }};
            }};
          }
          thenRefreshed(build(function (id) { return $(id).innerHTML; })); await flush();
          var same = JSON.parse(JSON.stringify(writes));
          thenRefreshed(build(function (id) { return "<option>" + id + ", the next build's</option>"; })); await flush();
          console.log(JSON.stringify([same, writes]));
        """)
        self.assertEqual(got, [{"then-event": 0, "then-strip": 0, "then-years": 0},
                               {"then-event": 1, "then-strip": 1, "then-years": 1}])


MODIS_DAYS = 'route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-28/P1D</Domain>");\n'


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenBarRuns(unittest.TestCase):
    """The bar and the chips: each side's date and the season around it,
    what a side waits on, the archive's captures, the readout at the pin,
    and the controls that move the dates."""

    def test_each_side_s_chip_date_and_words_name_its_season(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=8) + r"""
          thenRender();
          function side(k) {
            return {chip: $("then-chip-" + k).textContent, hidden: $("then-chip-" + k).hidden,
                    words: $("then-words-" + k).textContent, date: $("then-date-" + k).value,
                    cap: $("then-cap-" + k).hidden, line: $("then-line-" + k).getAttribute("x1")};
          }
          console.log(JSON.stringify({a: side("a"), b: side("b"), right: $("then-chip-a").style.right,
                                      left: $("then-chip-b").style.left, source: $("then-source").value,
                                      street: $("then-gmaps").getAttribute("href")}));
        """)
        self.assertEqual(got["a"], {"chip": "15 Nov 2014 · RONI +0.6, OND 2014", "hidden": False,
                                    "words": "OND 2014, centred on Nov 2014: RONI +0.6, weak El Niño, the "
                                             "2014-16 episode.",
                                    "date": "2014-11-15", "cap": True, "line": "178.5"})
        self.assertEqual(got["b"]["chip"], "15 Nov 2015 · RONI +2.6, OND 2015")
        self.assertEqual(got["b"]["line"], "190.5")
        # The divider sits at 30 % of 800 px: each chip keeps 26 px from it.
        self.assertEqual((got["right"], got["left"]), ("586px", "266px"))
        self.assertEqual(got["source"], "modis")
        self.assertEqual(got["street"], "https://www.google.com/maps/@?api=1&map_action=pano"
                                        "&viewpoint=-3.100000,-60.025000")

    def test_the_chips_stand_clear_of_the_credit_however_many_lines_it_takes(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=8) + r"""
          var out = [];
          [17, 33, 48].forEach(function (h) {
            $("credit").offsetHeight = h;
            thenRender();
            out.push([$("then-chip-a").style.bottom, $("then-chip-b").style.bottom]);
          });
          console.log(JSON.stringify(out));
        """)
        # A credit of one line leaves the chips 26 px up, as before; wrapped
        # to two or three lines on a narrow map, it would cover them.
        self.assertEqual(got, [["26px", "26px"], ["42px", "42px"], ["57px", "57px"]])

    def test_a_side_still_being_found_says_what_it_waits_on(self):
        got = _run(self, _entered("modis", None, None) + r"""
          S.then.want = {a: "2014-11-15", b: "2015-11-15"};
          var out = [];
          function say(source, look) {
            S.then.source = source; S.then.look = {a: look, b: ""};
            out.push([chipText(S.then, "a"), sideWords(S.then, "a")]);
          }
          say("modis", "asking"); say("modis", "no answer"); say("hls", "looking"); say("hls", "none");
          say("archive", "asking"); say("archive", "no answer"); say("archive", "none");
          console.log(JSON.stringify(out));
        """)
        self.assertEqual(got, [
            ["15 Nov 2014 · asking NASA GIBS for its days", "Asking NASA GIBS for its days."],
            ["15 Nov 2014 · NASA GIBS did not answer", "NASA GIBS did not answer."],
            ["15 Nov 2014 · looking for a day with an image here", "Looking for a day with an image here."],
            ["15 Nov 2014 · no image here within 20 days of 15 Nov 2014",
             "No image here within 20 days of 15 Nov 2014."],
            ["15 Nov 2014 · asking Esri’s archive for the versions here",
             "Asking Esri’s archive for the versions here."],
            ["15 Nov 2014 · Esri’s archive did not answer", "Esri’s archive did not answer."],
            ["15 Nov 2014 · Esri’s archive has no imagery here", "Esri’s archive has no imagery here."]])

    def test_the_archive_s_versions_are_a_menu_and_each_capture_is_told(self):
        got = _run(self, _entered("archive", 80, 90, z=16) + r"""
          thenRender();
          console.log(JSON.stringify({menu: $("then-cap-a").innerHTML, value: [$("then-cap-a").value, $("then-cap-b").value],
                                      hidden: [$("then-cap-a").hidden, $("then-date-a").hidden],
                                      steps: [$("then-back-a").disabled, $("then-next-a").disabled,
                                              $("then-back-b").disabled, $("then-next-b").disabled],
                                      chips: [$("then-chip-a").textContent, $("then-chip-b").textContent],
                                      read: $("then-read").textContent}));
        """)
        self.assertEqual(got["menu"], '<option value="90">31 Oct 2021</option>'
                                      '<option value="80">26 Jun 2019 (release)</option>')
        self.assertEqual(got["value"], ["80", "90"])
        self.assertEqual(got["hidden"], [False, True])
        # The left holds the oldest version: it can only step on; the right the newest.
        self.assertEqual(got["steps"], [True, False, False, True])
        self.assertEqual(got["chips"], ["26 Jun 2019 · latest RONI −0.6, NDJ 2016",
                                        "31 Oct 2021 · latest RONI −0.6, NDJ 2016"])
        self.assertEqual(got["read"], "Left: capture date not given, first shown in the 26 Jun 2019 release. "
                                      "Right: taken 31 Oct 2021 by Maxar, WV02 at 50 cm, first shown in the "
                                      "1 Mar 2024 release.")

    def test_versions_without_capture_dates_are_named_by_release(self):
        got = _run(self, _entered("archive", 80, 90, z=16) + r"""
          S.then.versions.forEach(function (v) { v.capture = null; v.when = v.day; });
          thenRender();
          console.log(JSON.stringify([$("then-cap-b").innerHTML, $("then-chip-b").textContent,
                                      $("then-note").textContent]));
        """)
        self.assertEqual(got[0], '<option value="90">1 Mar 2024 (release)</option>'
                                 '<option value="80">26 Jun 2019 (release)</option>')
        self.assertTrue(got[1].startswith("1 Mar 2024 · "))
        self.assertTrue(got[2].startswith("A version whose capture date Esri’s metadata did not give is named "
                                          "by the release that first showed it. While a place is entered, "
                                          "the storm picked stays"))

    def test_the_ocean_s_temperature_is_read_at_the_pin_on_both_sides(self):
        got = _run(self, _want("sst", "2014-11-15", "2015-11-15") + r"""
          route("gibs/GHRSST", "<Domain>2002-09-01/2026-09-27/P1D</Domain>");
          paint("Anomalies/2014-11-15/", [237, 237, 152, 255]);
          paint("Anomalies/2015-11-15/", [249, 1, 19, 255]);
          // Read as soon as both sides have their days: nothing else asks.
          thenResolve(); await flush();
          thenRender();
          var warm = $("then-read").textContent;
          S.then.got = {a: "2014-11-16", b: "2015-11-16"};
          paint("Anomalies/2014-11-16/", [0, 0, 0, 0]);
          thenRead(); await flush(); thenRender();
          var gaps = $("then-read").textContent;
          S.then.got = {a: "2014-11-17", b: "2015-11-17"};
          paint("Anomalies/2014-11-17/", [107, 0, 219, 255]); paint("Anomalies/2015-11-17/", [128, 0, 0, 255]);
          thenRead(); await flush(); thenRender();
          console.log(JSON.stringify([warm, gaps, $("then-read").textContent, IMAGES[0]]));
        """)
        self.assertEqual(got[0], "At the pin, left: +0.3 to +0.4 °C; right: +2.0 to +2.1 °C; a change of about "
                                 "+1.7 °C.")
        self.assertEqual(got[1], "At the pin, left: no data (land, ice or a gap); right: its tile did not arrive.")
        self.assertEqual(got[2], "At the pin, left: below −3.0 °C; right: +3.0 °C or more; the change runs past "
                                 "the end of NASA’s scale.")
        self.assertEqual(got[3], "https://gibs/GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies/2014-11-15/"
                                 "GoogleMapsCompatible_Level6/6/32/21.png")

    def test_vegetation_is_read_to_three_places(self):
        left = next(rgb for lo, hi, rgb in thennow.NDVI_COLOURS if lo == 0.8)
        right = next(rgb for lo, hi, rgb in thennow.NDVI_COLOURS if lo == 0.6)
        got = _run(self, _entered("ndvi", "2014-11-17", "2015-11-17", z=7) + r"""
          paint("NDVI_16Day/2014-11-17/", %s);
          paint("NDVI_16Day/2015-11-17/", %s);
          thenRead(); await flush(); thenRender();
          console.log(JSON.stringify($("then-read").textContent));
        """ % (json.dumps(list(left) + [255]), json.dumps(list(right) + [255])))
        self.assertEqual(got, "At the pin, left: NDVI 0.800 to 0.810; right: NDVI 0.600 to 0.610; a change of "
                              "about −0.200.")

    def test_the_pixel_read_wraps_at_the_date_line(self):
        got = _run(self, r"""
          var src = thenSrc("sst"), at = [];
          paint("Anomalies/", [237, 237, 152, 255]);
          for (var lon of [179.99, -179.99, 540.5]) {
            await thenPixel(src, "2015-11-15", lon, -18.14);
            at.push(CTX.at);
          }
          console.log(JSON.stringify([IMAGES.map(function (u) { return u.split("Level6/")[1]; }), at]));
        """)
        # Either side of 180 degrees: the last column's last pixel, then the
        # first column's first; 540.5 is -179.5, 22 pixels into the first.
        self.assertEqual(got, [["6/35/63.png", "6/35/0.png", "6/35/0.png"],
                               [[255, 71, 1, 1], [0, 71, 1, 1], [22, 71, 1, 1]]])

    def test_a_cleared_or_impossible_date_is_ignored(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15", preset="ep0-before") + MODIS_DAYS + r"""
          thenResolve(); await flush();
          var asked = ASKED.length, calls = CALLS.length, field = $("then-date-a");
          // 0201 is a year still being typed, on the way to 2015.
          ["", "2015-02-30", "0201-11-15", "2014-11-15"].forEach(function (text) {
            field.fire("change", {target: {value: text}});
          });
          await flush();
          var kept = [S.then.want.a, S.then.got.a, S.then.preset, ASKED.length === asked, CALLS.length === calls];
          field.fire("change", {target: {value: "2015-01-10"}}); await flush();
          console.log(JSON.stringify([kept, S.then.want.a, S.then.got.a, S.then.preset]));
        """)
        self.assertEqual(got, [["2014-11-15", "2014-11-15", "ep0-before", True, True], "2015-01-10", "2015-01-10", ""])

    def test_a_date_before_2000_or_still_to_come_is_said_and_not_taken(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + MODIS_DAYS + r"""
          thenResolve(); await flush();
          var asked = ASKED.length, field = $("then-date-a"), out = [];
          ["1999-12-31", "0201-11-15", "2026-10-01"].forEach(function (text) {
            field.fire("change", {target: {value: text}});
            out.push(S.then.note.a);
          });
          await flush(); thenRender();
          console.log(JSON.stringify([out, S.then.want.a, S.then.got.a, ASKED.length === asked,
                                      $("then-note").textContent.split(" While")[0]]));
        """)
        self.assertEqual(got, [["asked for 31 Dec 1999, before the first day the page offers, 1 Jan 2000",
                                "asked for 31 Dec 1999, before the first day the page offers, 1 Jan 2000",
                                "asked for 1 Oct 2026, a day still to come"],
                               "2014-11-15", "2014-11-15", True, "Left: asked for 1 Oct 2026, a day still to come."])

    def test_the_date_fields_reach_today_on_a_page_opened_days_ago(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15") + r"""
          thenRender();
          var built = $("then-date-a").getAttribute("max");
          NOW = Date.parse("2026-10-04T08:00:00Z");
          thenRender();
          console.log(JSON.stringify([built, $("then-date-a").getAttribute("max"), $("then-date-b").getAttribute("max")]));
        """)
        self.assertEqual(got, ["2026-09-29", "2026-10-04", "2026-10-04"])

    def test_a_refresh_brings_the_new_build_s_event_menu_and_strip(self):
        self.assertIn("thenRefreshed(doc);", _js_function(stormdesk.script(), "takeRun"))
        got = _run(self, r"""
          var fresh = {"then-event": new El("then-event", "select"), "then-strip": new El("then-strip", "svg"),
                       "then-years": new El("then-years")};
          fresh["then-event"].innerHTML = '<option value="now">A year ago → the latest (Oct 2025 → Oct 2026)</option>';
          fresh["then-strip"].innerHTML = '<rect class="warm" x="321" y="-6" width="1" height="6"/>';
          fresh["then-strip"].setAttribute("viewBox", "0 -30 322 60");
          fresh["then-years"].innerHTML = '<span style="left:0.00%">2000</span>';
          thenRefreshed({getElementById: function (id) { return fresh[id] || null; }});
          var got = [$("then-event").innerHTML, $("then-strip").innerHTML, $("then-strip").getAttribute("viewBox"),
                     $("then-years").innerHTML];
          // A page without the parts leaves them as they are.
          thenRefreshed({getElementById: function () { return null; }});
          console.log(JSON.stringify([got, $("then-event").innerHTML === got[0]]));
        """)
        self.assertEqual(got, [['<option value="now">A year ago → the latest (Oct 2025 → Oct 2026)</option>',
                                '<rect class="warm" x="321" y="-6" width="1" height="6"/>', "0 -30 322 60",
                                '<span style="left:0.00%">2000</span>'], True])

    def test_a_typed_date_is_not_overwritten_while_it_is_typed(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15") + r"""
          var field = $("then-date-a");
          field.value = "2015-0"; document.activeElement = field;
          thenRender();
          var typing = field.value;
          document.activeElement = null; thenRender();
          console.log(JSON.stringify([typing, field.value]));
        """)
        self.assertEqual(got, ["2015-0", "2014-11-15"])

    def test_a_step_moves_a_side_to_the_next_time_or_version(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15", preset="ep0-before") + MODIS_DAYS + r"""
          thenResolve(); await flush();
          $("then-back-a").fire("click"); await flush();
          var daily = [S.then.got.a, S.then.want.a, S.then.preset];
          S.then.got.b = "2026-09-28"; thenRender();
          var end = [$("then-next-b").disabled, $("then-back-b").disabled];
          """ + _entered("archive", 80, 90, z=16) + r"""
          thenStep("a", 1);
          var archive = [S.then.got.a, S.then.want.a];
          thenStep("a", 1);
          console.log(JSON.stringify([daily, end, archive, S.then.got.a]));
        """)
        # The archive's left steps on to the newer version, and no further.
        self.assertEqual(got, [["2014-11-14", "2014-11-14", ""], [True, False], [90, "2021-10-31"], 90])

    def test_an_event_s_choice_moves_both_sides_and_own_dates_keep_them(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + MODIS_DAYS + r"""
          thenResolve(); await flush();
          $("then-event").fire("change", {target: {value: "ep0-after"}}); await flush();
          var event = [S.then.preset, S.then.got.a, S.then.got.b];
          $("then-event").fire("change", {target: {value: ""}}); await flush();
          console.log(JSON.stringify([event, S.then.preset, S.then.got.a, S.then.got.b]));
        """)
        self.assertEqual(got, [["ep0-after", "2015-11-15", "2016-11-15"], "", "2015-11-15", "2016-11-15"])

    def test_another_source_is_flown_to_at_its_own_zoom(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + MODIS_DAYS + r"""
          route("gibs/GHRSST", "<Domain>2002-09-01/2026-09-27/P1D</Domain>");
          thenResolve(); await flush();
          $("then-source").fire("change", {target: {value: "sst"}});
          var flight = FLIGHTS[FLIGHTS.length - 1], layer = LAYERS["then-a"].global;
          await flush();
          console.log(JSON.stringify([flight.z, flight.ms, layer, S.then.got]));
        """)
        self.assertEqual(got, [4, 1400, "GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies",
                               {"a": "2014-11-15", "b": "2015-11-15"}])

    def test_a_tap_on_the_strip_moves_the_nearer_side_to_that_month(self):
        got = _run(self, _want("modis", "2014-11-15", "2016-11-15") + MODIS_DAYS + r"""
          thenResolve(); await flush();
          var strip = $("then-strip");
          strip.box = {left: 10, top: 0, width: 321, height: 60};
          strip.fire("click", {clientX: 10 + 190.5}); await flush();
          var one = [S.then.got.a, S.then.got.b];
          strip.fire("click", {clientX: 10 + 320.9}); await flush();
          console.log(JSON.stringify([one, S.then.got.b]));
        """)
        # November 2015 is a day nearer the left's November 2014 than the
        # right's November 2016; September 2026 is nearer the right.
        self.assertEqual(got, [["2015-11-15", "2016-11-15"], "2026-09-15"])

    def test_the_names_switch_takes_esri_s_names_off_both_sides(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15") + r"""
          var on = [!!LAYERS["then-a"].over, !!LAYERS["then-b"].over];
          $("then-names").fire("change", {target: {checked: false}});
          console.log(JSON.stringify([on, !!LAYERS["then-a"].over, !!LAYERS["then-b"].over, S.then.names]));
        """)
        self.assertEqual(got, [[True, True], False, False, False])

    def test_the_bar_is_drawn_with_the_map(self):
        self.assertIn("dayControls();\n    if (S.then) thenRender();", _js_function(stormdesk._JS, "render"))


# Manaus entered on MODIS, the two sides at 15 November 2014 and 2015.
MANAUS = 'thenEnter(-60.025, -3.1, "Manaus", {source: "modis", a: "2014-11-15", b: "2015-11-15"});\n'
# The map as the reader left it before entering.
BEFORE = 'S.layer = "satellite"; S.second = "infrared"; S.compare = false; S.split = 0.3;\n'


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenEnterRuns(unittest.TestCase):
    """Into a place and out again: the pin, the two sides at the divider and
    the flight in; the map as it was on the way out; the place moved by a
    tap; the page's other controls leaving first."""

    def test_a_place_is_entered_again_on_its_event_and_its_names(self):
        # As a page loaded again for a run puts back the place the reader had
        # entered: on its event, at the dates this build gives it, with Esri's
        # names as they were.
        got = _run(self, r"""
          thenEnter(-60.025, -3.1, null, {preset: "ep0-before", a: "2001-01-01", b: "2002-01-01", names: false});
          var on = [S.then.preset, S.then.want.a, S.then.want.b, S.then.names, !!LAYERS["then-a"].over];
          thenEnter(-60.025, -3.1, null, {preset: "ep7-gone", a: "2001-01-01", b: "2002-01-01"});
          console.log(JSON.stringify([on, [S.then.preset, S.then.want.a, S.then.want.b]]));
        """)
        # An event the build no longer offers: its dates kept, as the reader's own.
        self.assertEqual(got, [["ep0-before", "2014-11-15", "2015-11-15", False, False],
                               ["", "2001-01-01", "2002-01-01"]])

    def test_entering_flies_in_and_compares_two_dates_at_the_pin(self):
        got = _run(self, BEFORE + r"""
          LAND["-60,-3"] = true; S.z = 3;
          var scrubRow = SELECTED[".deskscrub"] = new El("scrubrow"), button = new El("b");
          button.setAttribute("aria-pressed", "true"); LISTS["[data-layer]"] = [button];
          var done = thenEnter(-60.025, -3.1), T = S.then, f = FLIGHTS[0];
          console.log(JSON.stringify({done: done, source: T.source, label: T.label, preset: T.preset, want: T.want,
                                      look: T.look, back: T.back, map: [S.layer, S.second, S.compare, S.split],
                                      pin: [S.pin.lon.toFixed(6), S.pin.lat, S.pin.label],
                                      flight: [f.x === mx(-60.025), f.y === my(-3.1), f.z, f.ms],
                                      bar: $("then-bar").hidden, scrub: scrubRow.hidden,
                                      pressed: button.getAttribute("aria-pressed")}));
        """)
        self.assertEqual(got["done"], True)
        self.assertEqual((got["source"], got["label"]), ("archive", "Manaus, Amazonas, Brazil"))
        # A year ago on the left, the latest on the right, until chosen.
        self.assertEqual((got["preset"], got["want"]), ("now", {"a": "2025-09-29", "b": "2026-09-29"}))
        self.assertEqual(got["look"], {"a": "asking", "b": "asking"})
        self.assertEqual(got["back"], {"layer": "satellite", "second": "infrared", "compare": False, "split": 0.3,
                                       "loop": False})
        self.assertEqual(got["map"], ["then-a", "then-b", True, 0.5])
        self.assertEqual(got["pin"], ["-60.025000", -3.1, "Manaus, Amazonas, Brazil"])
        # From zoom 3 to the archive's 16: the longest flight, 2 s.
        self.assertEqual(got["flight"], [True, True, 16, 2000])
        # The slider stays, for the storm picked.
        self.assertEqual((got["bar"], got["scrub"], got["pressed"]), (False, False, "false"))

    def test_a_point_at_sea_opens_on_the_ocean_and_on_land_on_the_archive(self):
        got = _run(self, r"""
          LAND["-60,-3"] = true;
          var picks = [thenPick(-60.025, -3.1), thenPick(-140, 0), thenPick(178.5, -18.2)];
          // Without the composite's grid, a town within 30 km decides.
          cellAt = function () { throw new Error("no grid"); };
          picks.push(thenPick(-60.025, -3.1), thenPick(-140, 0));
          thenEnter(-140, 0);
          console.log(JSON.stringify([picks, S.then.source, S.then.label, FLIGHTS[0].z, FLIGHTS[0].ms]));
        """)
        self.assertEqual(got, [["archive", "sst", "archive", "archive", "sst"], "sst", "0.00N 140.00W", 4, 800])

    def test_exit_restores_the_layers_and_leaves_the_view_where_it_is(self):
        got = _run(self, BEFORE + r"""
          var scrubRow = SELECTED[".deskscrub"] = new El("scrubrow");
          """ + MANAUS + r"""
          var during = [scrubRow.hidden, $("then-bar").hidden];
          S.z = 11.5; S.x = 0.34; CALLS = [];
          $("then-exit").fire("click");
          console.log(JSON.stringify({during: during, then: S.then, sides: [!!LAYERS["then-a"], !!LAYERS["then-b"]],
                                      map: [S.layer, S.second, S.compare, S.split], view: [S.x, S.z], pin: S.pin,
                                      calls: CALLS, bar: $("then-bar").hidden, scrub: scrubRow.hidden,
                                      chips: [$("then-chip-a").hidden, $("then-chip-b").hidden], again: thenLeave()}));
        """)
        self.assertEqual(got, {"during": [False, False], "then": None, "sides": [False, False],
                               "map": ["satellite", "infrared", False, 0.3], "view": [0.34, 11.5], "pin": None,
                               "calls": ["setLayer satellite", "setCompare false", "dirty"], "bar": True,
                               "scrub": False, "chips": [True, True], "again": False})

    def test_the_divider_says_where_it_is_after_entering_and_leaving(self):
        got = _run(self, BEFORE + r"""
          divider.setAttribute("aria-valuenow", "30");
          """ + MANAUS + r"""
          var during = divider.getAttribute("aria-valuenow");
          thenLeave();
          console.log(JSON.stringify([during, divider.getAttribute("aria-valuenow")]));
        """)
        self.assertEqual(got, ["50", "30"])

    def test_compare_pressed_while_entered_leaves_and_compares_as_its_button_showed(self):
        js = stormdesk.script()
        self.assertIn('$("compare").addEventListener("click", pressCompare);', js)
        extra = "\n".join(_js_function(js, n) for n in ("setLayer", "setCompare", "pressCompare"))
        got = _run(self, BEFORE + MANAUS + r"""
          pressCompare();
          var off = [S.then, S.compare];
          S.compare = true; S.split = 0.3;
          """ + MANAUS + r"""
          pressCompare();
          console.log(JSON.stringify([off, S.then, S.compare]));
        """, extra=extra)
        # Unpressed before entering, a press compares; pressed, a press stops.
        self.assertEqual(got, [[None, True], None, False])

    def test_the_map_is_marked_while_entered_so_it_keeps_its_height(self):
        got = _run(self, MANAUS + r"""
          var during = map.classList.contains("thenon");
          thenLeave();
          console.log(JSON.stringify([during, map.classList.contains("thenon")]));
        """)
        self.assertEqual(got, [True, False])

    def test_leaving_takes_the_entered_place_out_of_the_address(self):
        got = _run(self, MANAUS + r"""
          location.hash = "#then=-3.1000,-60.0250,8.00,modis,2014-11-15,2015-11-15";
          location.href = "file:///C:/elnino/output/map.html" + location.hash;
          thenLeave();
          function replaced() { return CALLS.filter(function (c) { return c.indexOf("replaceState") === 0; }); }
          var cleared = [replaced(), location.hash];
          """ + MANAUS + r"""
          location.hash = "#at=-3.1,-60.0"; CALLS = [];
          thenLeave();
          console.log(JSON.stringify([cleared, replaced(), location.hash]));
        """)
        self.assertEqual(got, [[["replaceState file:///C:/elnino/output/map.html"], ""], [], "#at=-3.1,-60.0"])

    def test_here_s_pin_comes_back_after_and_clear_keeps_the_entered_pin(self):
        extra = _js_function(stormdesk.script(), "clearHere") + '\nfunction showHere() { note("showHere"); }\n'
        got = _run(self, r"""
          S.here = {lon: 178.44, lat: -18.14, label: "Suva"}; S.pin = {lon: 178.44, lat: -18.14, label: "Suva"};
          """ + MANAUS + r"""
          var entered = S.pin.label;
          thenLeave();
          var back = S.pin.label;
          """ + MANAUS + r"""
          clearHere();
          var cleared = [S.here, S.pin && S.pin.label];
          thenLeave();
          console.log(JSON.stringify([entered, back, cleared, S.pin]));
        """, extra=extra)
        self.assertEqual(got, ["Manaus", "Suva", [None, "Manaus"], None])

    def test_the_loop_stops_while_entered_and_runs_again_after(self):
        got = _run(self, r"""
          S.loop = true; S.scrub = 6;
          var scrubRow = SELECTED[".deskscrub"] = new El("scrubrow");
          """ + MANAUS + r"""
          var during = [S.loop, S.then.back.loop, scrubRow.hidden];
          thenLeave();
          var after = [S.loop, S.scrub, scrubRow.hidden];
          S.loop = false;
          """ + MANAUS + r"""
          thenLeave();
          console.log(JSON.stringify([during, after, S.loop,
                                      CALLS.filter(function (c) { return c.indexOf("setLoop") === 0; })]));
        """)
        # The slider stays while entered, for the storm picked, and keeps its
        # hour; a loop left off stays off.
        self.assertEqual(got, [[False, True, False], [True, 6, False], False, ["setLoop false", "setLoop true"]])

    def test_exit_with_play_running_leaves_the_loop_off(self):
        # Play pressed while entered is the reader's latest word: Exit keeps
        # it running, and does not start the loop that ran before.
        got = _run(self, r"""
          S.loop = true;
          """ + MANAUS + r"""
          S.playing = true;
          thenLeave();
          console.log(JSON.stringify([S.loop, S.playing,
                                      CALLS.filter(function (c) { return c.indexOf("setLoop") === 0; })]));
        """)
        self.assertEqual(got, [False, True, ["setLoop false"]])

    def test_exit_runs_the_page_s_own_loop_again_over_the_layer_put_back(self):
        # The page's own loop, which runs only over frames in view: until the
        # map is drawn again, what is in view is the entered place's sides.
        extra = ("\n".join(_js_function(stormdesk.script(), name)
                           for name in ("setLoop", "loopLength", "timed", "framesOf"))
                 + "\nvar loopTimer = 0;\nfunction tick() {}\n")
        got = _run(self, r"""
          LAYERS.loopy = {id: "loopy", kind: "imagery", name: "Loopy", global: "LOOPY", tms: "GoogleMapsCompatible_Level6",
                          zoom: 6, format: "png", step: "PT10M"};
          DOM.LOOPY = {frames: [{t: 1, key: "k1"}, {t: 2, key: "k2"}, {t: 3, key: "k3"}]};
          S.layer = "loopy"; S.inView = cells("loopy", 0).used;
          var before = setLoop(true);
          """ + MANAUS + r"""
          var during = S.loop;
          S.inView = cells("then-a", 0).used;
          thenLeave();
          console.log(JSON.stringify([before, during, S.layer, S.loop, S.frame]));
        """, extra=extra)
        self.assertEqual(got, [True, False, "loopy", True, 2])

    def test_exit_before_gibs_has_given_the_layer_s_frames_runs_the_loop_once_it_has(self):
        # A place entered across a load: the layer Exit goes back to has had
        # no frames asked for yet, so its loop runs once GIBS gives them.
        extra = ("\n".join(_js_function(stormdesk.script(), name)
                           for name in ("setLoop", "loopWhenKnown", "loopLength", "timed", "framesOf"))
                 + "\nvar loopTimer = 0;\nfunction tick() {}\n")
        got = _run(self, r"""
          LAYERS.loopy = {id: "loopy", kind: "imagery", name: "Loopy", global: "LOOPY", tms: "GoogleMapsCompatible_Level6",
                          zoom: 6, format: "png", step: "PT10M"};
          S.layer = "loopy";
          """ + MANAUS + r"""
          S.then.back.loop = true;
          thenLeave();
          var waiting = [S.layer, S.loop, S.loopWanted];
          DOM.LOOPY = {frames: [{t: 1, key: "k1"}, {t: 2, key: "k2"}, {t: 3, key: "k3"}]};
          S.inView = cells("loopy", 0).used;
          loopWhenKnown();
          console.log(JSON.stringify([waiting, [S.loop, S.frame, S.loopWanted]]));
        """, extra=extra)
        self.assertEqual(got, [["loopy", False, True], [True, 2, False]])

    def test_entering_again_moves_the_place_and_keeps_the_source_dates_and_way_back(self):
        got = _run(self, BEFORE + MANAUS + r"""
          S.split = 0.7; S.then.names = false;
          thenEnter(178.44, -18.14);
          var T = S.then;
          console.log(JSON.stringify([T.label, T.source, T.want, T.preset, T.names, T.back, S.split, S.pin.label,
                                      FLIGHTS.length]));
        """)
        self.assertEqual(got, ["Suva, Central, Fiji", "modis", {"a": "2014-11-15", "b": "2015-11-15"}, "", False,
                               {"layer": "satellite", "second": "infrared", "compare": False, "split": 0.3,
                                "loop": False}, 0.7, "Suva, Central, Fiji", 2])

    def test_a_tap_while_entered_moves_the_pin_and_keeps_the_dates(self):
        got = _run(self, MODIS_DAYS + MANAUS + r"""
          await flush();
          var asked = ASKED.length;
          thenMove(-61.5, -3.3);
          await flush();
          console.log(JSON.stringify([S.then.label, S.pin.label, [S.then.lon, S.then.lat], S.then.got,
                                      ASKED.length - asked, FLIGHTS.length]));
        """)
        self.assertEqual(got, ["165 km from Manaus, Amazonas, Brazil", "165 km from Manaus, Amazonas, Brazil",
                               [-61.5, -3.3], {"a": "2014-11-15", "b": "2015-11-15"}, 0, 1])

    def test_a_move_keeps_the_archive_s_versions_drawn_until_the_new_walk_answers(self):
        got = _run(self, WB_ROUTES + r"""
          thenEnter(-60.025, -3.1, "Manaus", {source: "archive", a: "2019-01-01", b: "2022-01-01"});
          await flush();
          var before = [S.then.got.a, S.then.got.b], asked = ASKED.length;
          thenMove(-60.2, -3.3);
          var moving = [S.then.look.a, S.then.look.b, LAYERS["then-a"].tiles, S.then.versions.length];
          await flush();
          console.log(JSON.stringify([before, moving, [S.then.got.a, S.then.got.b], ASKED.length > asked]));
        """)
        self.assertEqual(got, [[80, 90], ["", "", "https://wb/tile/80/{z}/{y}/{x}", 2], [80, 90], True])

    def test_choosing_a_layer_or_the_comparison_while_entered_leaves_first(self):
        extra = "\n".join(_js_function(stormdesk.script(), n) for n in ("setLayer", "setCompare"))
        got = _run(self, r"""
          S.layer = "satellite"; S.second = "infrared"; S.compare = true; S.split = 0.3;
          """ + MANAUS + r"""
          var ok = setLayer("streets");
          var one = [S.then, S.layer, S.second, S.compare, S.split, !!LAYERS["then-a"]];
          """ + MANAUS + r"""
          setCompare(false);
          console.log(JSON.stringify([ok, one, S.then, S.layer, S.compare]));
        """, extra=extra)
        self.assertEqual(got, [True, [None, "streets", "infrared", True, 0.3, False], None, "streets", False])

    def test_the_page_s_other_controls_leave_first(self):
        js = stormdesk.script()
        for name in ("setLayer", "setCompare", "flyTo", "setEnso", "showRegion"):
            self.assertEqual(_js_function(js, name).split("\n")[1], "    if (S.then) thenLeave();", name)
        self.assertIn('if (r.kind === "search") { geocode(r.q); return true; }\n    if (S.then) thenLeave();',
                      _js_function(js, "go"))
        self.assertIn("if (!h) return false;\n    if (S.then) thenLeave();", _js_function(js, "applyHash"))
        for control in ('$("swap").addEventListener("click", function () {',
                        '$("compare-layer").addEventListener("change", function (e) {'):
            self.assertIn(control + "\n    if (S.then) thenLeave();", js)

    def test_a_refresh_while_entered_draws_the_sides_again(self):
        js = stormdesk.script()
        names = ("refresh", "siteCopy", "newer", "takeRun", "withAssets")
        extra = "\n".join(_js_function(js, name) for name in names) + r"""
function prepare() { note("prepare"); LAYERS = {streets: {id: "streets", kind: "map"}}; }
function select() {}
function showHere() {}
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
        got = _run(self, MODIS_DAYS + MANAUS + r"""
          await flush();
          D.built = "2026-09-29T11:00:00Z";
          NEXT = JSON.parse(JSON.stringify(D)); NEXT.built = "2026-09-29T12:00:00Z";
          route("map.html", "<html></html>");
          refresh(); await flush();
          console.log(JSON.stringify([CALLS.indexOf("prepare") >= 0, S.layer, S.second,
                                      LAYERS["then-a"] && LAYERS["then-a"].time, LAYERS["then-b"] && LAYERS["then-b"].time]));
        """, extra=extra)
        self.assertEqual(got, [True, "then-a", "then-b", "2014-11-15", "2015-11-15"])

    def test_here_offers_then_and_now_of_the_point_it_shows(self):
        js = stormdesk.script()
        self.assertIn('<button type="button" class="toolbtn" data-here="then">Then and now here</button>',
                      _js_function(js, "showHere"))
        self.assertIn('else if (h && what === "then") thenEnter(h.lon, h.lat, h.label);', js)

    def test_the_page_s_api_enters_leaves_and_tells_what_is_entered(self):
        js = stormdesk.script()
        self.assertIn("enter: function (lon, lat, opts) { return thenEnter(lon, lat, null, opts || {}); },", js)
        self.assertIn("leave: function () { return thenLeave(); },", js)
        self.assertIn("dayState: S.dayState, then: thenView(), street: streetView()};", js)
        got = _run(self, MODIS_DAYS + r"""
          var none = thenView();
          thenEnter(-60.025, -3.1, null, {source: "modis", a: "2015-11-15", b: "2014-11-15"});
          await flush();
          var view = thenView();
          thenLeave();
          // Dates that are not days of the calendar are not taken.
          thenEnter(-60.025, -3.1, null, {source: "modis", a: "2015-02-30", b: "2014-11-15"});
          console.log(JSON.stringify([none, view, S.then.preset, S.then.want]));
        """)
        self.assertEqual(got, [None, {"lon": -60.025, "lat": -3.1, "label": "Manaus, Amazonas, Brazil",
                                      "source": "modis", "preset": "", "left": "2014-11-15", "right": "2015-11-15",
                                      "look": {"a": "", "b": ""}},
                               "now", {"a": "2025-09-29", "b": "2026-09-29"}])


# Where Manaus is on an 800 by 600 map centred on 0, 0 at zoom 3, and the
# figure and its ghost and ring hidden, as the page's markup has them.
SCREEN = (r"""
          var W = world(), spot = {x: (mx(-60.025) - S.x) * W + S.w / 2, y: (my(-3.1) - S.y) * W + S.h / 2};
          $("then-ghost").hidden = true; $("then-ring").hidden = true; $("then-hint").hidden = true;
          LAND["-60,-3"] = true;
""")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenFigureRuns(unittest.TestCase):
    """The figure, as Google's: pressed, the map waits for a tap, or Enter
    for the middle of the view; carried onto the map, it drops into Street
    View where it is let go. Esc stops waiting, or leaves."""

    def test_pressing_the_figure_waits_for_a_tap_and_pressing_again_stops(self):
        got = _run(self, SCREEN + r"""
          var fig = $("then-enter");
          function state() { return [S.arming, map.classList.contains("arming"), $("then-hint").hidden,
                                     fig.getAttribute("aria-pressed")]; }
          fig.fire("click");
          var armed = state();
          fig.fire("click");
          console.log(JSON.stringify([armed, state(), S.then]));
        """)
        self.assertEqual(got, [[True, True, False, "true"], [False, False, True, "false"], None])

    def test_enter_while_waiting_enters_the_middle_of_the_view_and_esc_stops_waiting(self):
        got = _run(self, SCREEN + r"""
          S.x = mx(-60.025); S.y = my(-3.1);
          $("then-enter").fire("click");
          var esc = press("Escape");
          var stopped = [S.arming, esc.defaultPrevented, S.then];
          $("then-enter").fire("click");
          var enter = press("Enter");
          console.log(JSON.stringify([stopped, enter.defaultPrevented, S.arming, S.street.label, S.then]));
        """)
        self.assertEqual(got, [[False, True, None], True, False, "Manaus, Amazonas, Brazil", None])

    def test_esc_leaves_the_place_and_keys_typed_in_a_field_are_its_own(self):
        got = _run(self, r"""
          thenEnter(-60.025, -3.1, "Manaus", {source: "modis", a: "2014-11-15", b: "2015-11-15"});
          var inForm = new El("go", "button");
          inForm.closest = function (sel) { return sel === "#findform" ? this : null; };
          var own = [press("Escape", new El("x", "input")), press("Escape", new El("s", "select")),
                     press("Escape", new El("t", "textarea")), press("Escape", inForm)];
          var stayed = [!!S.then].concat(own.map(function (e) { return e.defaultPrevented; }));
          var out = press("Escape");
          var again = press("Escape");
          console.log(JSON.stringify([stayed, out.defaultPrevented, S.then, again.defaultPrevented]));
        """)
        # Esc with nothing to stop or leave is the page's.
        self.assertEqual(got, [[True, False, False, False, False], True, None, False])

    def test_a_tap_while_waiting_drops_into_the_street_and_one_while_entered_moves_the_place(self):
        extra = _js_function(stormdesk.script(), "tap") + r"""
var tapTimer = 0, lastTap = null;
function zoomBy() { note("zoomBy"); }
function flyTo() { note("flyTo"); }
function flyToArea() { note("flyToArea"); }
"""
        got = _run(self, SCREEN + r"""
          $("then-enter").fire("click");
          tap({x: spot.x, y: spot.y, target: map}, 1000);
          var dropped = [S.arming, S.street && S.street.label, S.then];
          // In then and now, a tap asks nothing of Here: it moves the place.
          streetLeave();
          """ + MANAUS + r"""
          S.x = 0.5; S.y = 0.5; S.z = 3; CALLS = [];
          tap({x: 400, y: 300, target: map}, 5000); advance(330);
          var moved = [S.then.label, CALLS.filter(function (c) { return c.indexOf("hereAt") === 0; }).length];
          thenLeave();
          tap({x: 400, y: 300, target: map}, 9000); advance(330);
          console.log(JSON.stringify([dropped, moved, CALLS.filter(function (c) { return c.indexOf("hereAt") === 0; })]));
        """, extra=extra)
        self.assertEqual(got, [[False, "Manaus, Amazonas, Brazil", None], ["0.00N 0.00E", 0], ["hereAt undefined"]])

    def test_the_figure_carried_onto_the_map_drops_into_the_street_where_it_is_let_go(self):
        got = _run(self, SCREEN + r"""
          map.box = {left: 100, top: 50, width: 800, height: 600};
          var fig = $("then-enter");
          fig.fire("pointerdown", {pointerId: 7, pointerType: "mouse", button: 0, clientX: 20, clientY: 20});
          // Under 8 px it is a press, not yet carried.
          fig.fire("pointermove", {pointerId: 7, clientX: 24, clientY: 25});
          var still = [$("then-ghost").hidden, $("then-ring").hidden];
          fig.fire("pointermove", {pointerId: 7, clientX: 100 + spot.x, clientY: 50 + spot.y});
          var carrying = [$("then-ghost").hidden, $("then-ghost").style.transform, $("then-ring").hidden,
                          $("then-ring").style.transform];
          fig.fire("pointerup", {pointerId: 7, clientX: 100 + spot.x, clientY: 50 + spot.y});
          // The click that follows letting go does not press the figure.
          fig.fire("click");
          console.log(JSON.stringify([still, carrying, [$("then-ghost").hidden, $("then-ring").hidden],
                                      S.street && S.street.label, S.arming]));
        """)
        self.assertEqual(got, [[True, True], [False, "translate(159px,368px)", False, "translate(59px,318px)"],
                               [True, True], "Manaus, Amazonas, Brazil", False])

    def test_the_figure_let_go_off_the_map_or_cancelled_enters_nowhere(self):
        got = _run(self, SCREEN + r"""
          map.box = {left: 100, top: 50, width: 800, height: 600};
          var fig = $("then-enter");
          // A right button is not a carry.
          fig.fire("pointerdown", {pointerId: 1, pointerType: "mouse", button: 2, clientX: 20, clientY: 20});
          fig.fire("pointermove", {pointerId: 1, clientX: 400, clientY: 300});
          var right = $("then-ghost").hidden;
          fig.fire("pointerdown", {pointerId: 3, pointerType: "touch", clientX: 20, clientY: 20});
          fig.fire("pointermove", {pointerId: 3, clientX: 60, clientY: 30});
          var off = [$("then-ghost").hidden, $("then-ring").hidden];
          fig.fire("pointerup", {pointerId: 3, clientX: 60, clientY: 30});
          fig.fire("click");
          off.push(S.street, S.arming, $("then-ghost").hidden);
          fig.fire("pointerdown", {pointerId: 4, pointerType: "touch", clientX: 20, clientY: 20});
          fig.fire("pointermove", {pointerId: 4, clientX: 400, clientY: 300});
          fig.fire("pointercancel", {pointerId: 4, clientX: 400, clientY: 300});
          fig.fire("click");
          console.log(JSON.stringify([right, off, S.street, S.arming, $("then-ghost").hidden, $("then-ring").hidden]));
        """)
        self.assertEqual(got, [True, [False, True, None, False, True], None, False, True, True])

    def test_the_figure_let_go_over_a_control_on_the_map_enters_nowhere(self):
        got = _run(self, SCREEN + r"""
          map.box = {left: 100, top: 50, width: 800, height: 600};
          var zoom = new El("zoomin", "button");
          zoom.closest = function (sel) { return sel === ".ui" ? this : null; };
          document.elementFromPoint = function () { return zoom; };
          var fig = $("then-enter");
          fig.fire("pointerdown", {pointerId: 5, pointerType: "mouse", button: 0, clientX: 20, clientY: 20});
          fig.fire("pointermove", {pointerId: 5, clientX: 100 + spot.x, clientY: 50 + spot.y});
          var ring = $("then-ring").hidden;
          fig.fire("pointerup", {pointerId: 5, clientX: 100 + spot.x, clientY: 50 + spot.y});
          fig.fire("click");
          var over = [ring, S.street, S.arming];
          // The same place with the map itself under the pointer.
          document.elementFromPoint = function () { return map; };
          fig.fire("pointerdown", {pointerId: 6, pointerType: "mouse", button: 0, clientX: 20, clientY: 20});
          fig.fire("pointermove", {pointerId: 6, clientX: 100 + spot.x, clientY: 50 + spot.y});
          fig.fire("pointerup", {pointerId: 6, clientX: 100 + spot.x, clientY: 50 + spot.y});
          console.log(JSON.stringify([over, S.street && S.street.label]));
        """)
        # Over a control there is no ring and no drop, as over the toolbar.
        self.assertEqual(got, [[True, None, False], "Manaus, Amazonas, Brazil"])

    def test_entering_by_here_a_link_or_the_api_stops_waiting_for_a_tap(self):
        got = _run(self, SCREEN + r"""
          var fig = $("then-enter"), out = [];
          function state() { return [S.arming, map.classList.contains("arming"), $("then-hint").hidden,
                                     fig.getAttribute("aria-pressed")]; }
          fig.fire("click");
          var armed = state();
          thenEnter(-60.025, -3.1, "Manaus");
          out.push(state());
          thenLeave(); fig.fire("click");
          thenHashApply("#then=-3.1000,-60.0250,8.00,modis,2014-11-15,2015-11-15");
          out.push(state());
          thenLeave(); fig.fire("click");
          streetEnter(-60.025, -3.1, "Manaus");
          out.push(state());
          console.log(JSON.stringify([armed, out]));
        """)
        self.assertEqual(got, [[True, True, False, "true"], [[False, False, True, "false"],
                                                             [False, False, True, "false"],
                                                             [False, False, True, "false"]]])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenWordsRuns(unittest.TestCase):
    """What the map says while a place is entered: the pill, the status line
    and Retry; the address that opens the place again, the link copied, and
    Google's Street View of the place."""

    def test_the_pill_names_the_place_the_source_and_each_side(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=11) + r"""
          var out = [];
          function said() { var head = [], more = []; thenPill(head, more); out.push([head, more]); }
          said();
          S.then.got.a = null; S.then.want.a = "2014-11-15"; S.then.look.a = "no answer"; S.imagery = "offline";
          said();
          """ + _entered("archive", 80, 90, z=16) + r"""
          S.imagery = "ok"; S.inView = {"then-a": {coarser: 16}}; S.inViewB = {"then-b": {coarser: null}};
          said();
          console.log(JSON.stringify(out));
        """)
        self.assertEqual(got[0], [["Manaus: True colour, daily (MODIS Terra), then and now"], [
            "Left: 15 Nov 2014, OND 2014, centred on Nov 2014: RONI +0.6, weak El Niño, the 2014-16 episode.",
            "Right: 15 Nov 2015, OND 2015, centred on Nov 2015: RONI +2.6, very strong El Niño, the 2014-16 episode.",
            "Enlarged 4.0 times past its 250 m pixels."]])
        self.assertEqual(got[1][0], ["Offline: True colour, daily (MODIS Terra) needs the network; the tiles already "
                                     "loaded stay."])
        self.assertEqual(got[1][1][0], "Left: 15 Nov 2014, NASA GIBS did not answer.")
        self.assertEqual(got[2], [["Manaus: Satellite archive (Esri), then and now"], [
            "Left: 26 Jun 2019, after the latest season on record, NDJ 2016 (RONI −0.6, weak La Niña, the 2016 "
            "episode, still going); capture date not given, first shown in the 26 Jun 2019 release.",
            "Right: 31 Oct 2021, after the latest season on record, NDJ 2016 (RONI −0.6, weak La Niña, the 2016 "
            "episode, still going); taken 31 Oct 2021 by Maxar, WV02 at 50 cm, first shown in the 1 Mar 2024 release.",
            "Left: Esri’s archive has nothing finer than zoom 16 for part of this view; that part is its zoom-16 tile, "
            "enlarged."]])

    def test_the_status_says_which_archive_did_not_answer(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + r"""
          route("gibs/MODIS_Terra_Corr", 500);
          thenResolve(); await flush();
          var gibs = thenDown();
          route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-28/P1D</Domain>");
          thenRetry(); await flush();
          var back = [thenDown(), S.then.got.a, S.then.fail.gibs];
          S.then.source = "archive"; S.then.fail.wayback = true;
          var esri = thenDown();
          S.then.fail.wayback = false; MAPS["then-b"] = {ok: 0, failed: 3};
          console.log(JSON.stringify([gibs, back, esri, thenDown()]));
        """)
        self.assertEqual(got, ["Imagery unreachable.", ["", "2014-11-15", False], "Esri’s archive unreachable.",
                               "Esri’s archive unreachable."])

    def test_the_pill_and_the_status_speak_of_the_place_while_entered(self):
        js = stormdesk.script()
        extra = "\n".join(_js_function(js, n) for n in ("pills", "downWord", "retry")) + r"""
var framePill = $("pill"), pillOpen = true, pillHtml = "", COMPASS = [], BYID = {al01: {d: {title: "Storm", view: {}}}};
statusPill.firstChild = {textContent: ""};
function ensoTileMore() { return ["The El Niño tiles."]; }
function nasaWanted() { return false; }
function dayWords() { return "a day"; }
function sourceWords() { return "another source"; }
function utc() { return "now"; }
function base() { return {t: 0, image: false}; }
function centreAt() { return {lon: 0, lat: 0}; }
function askGibsAgain() { note("askGibsAgain"); }
function forgetMaps() { note("forgetMaps"); }
"""
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=11) + MODIS_DAYS + r"""
          S.selected = "al01"; S.inViewB = {x: {name: "x", layer: {name: "Other"}}};
          S.then.fail.gibs = true;
          pills();
          var pill = framePill.innerHTML, status = [statusPill.hidden, statusPill.innerHTML];
          retry(); await flush();
          pills();
          console.log(JSON.stringify([pill, status, S.then.fail.gibs, statusPill.hidden, CALLS.indexOf("askGibsAgain") >= 0]));
        """, extra=extra)
        self.assertIn("<div>Manaus: True colour, daily (MODIS Terra), then and now</div>", got[0])
        self.assertIn("Enlarged 4.0 times past its 250 m pixels.", got[0])
        # Nothing of today's: the storm, the compared layer, the El Nino tiles.
        for today in ("Storm", "Compared, right of the divider", "The El Niño tiles."):
            self.assertNotIn(today, got[0])
        self.assertEqual(got[1], [False, '<span>Imagery unreachable.</span><button type="button" class="toolbtn" '
                                         'id="retry">Retry</button>'])
        self.assertEqual(got[2:], [False, True, True])

    def test_the_address_holds_the_place_the_zoom_the_source_and_both_dates(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=8) + r"""
          var hash = thenHash();
          console.log(JSON.stringify([hash, [hash, "#then=-18.1400,181.5000,20,archive,2019-06-26,2021-10-31",
                                             "#then=-18.1400,538.5000,8,archive,2019-06-26,2021-10-31",
                                             "#then=-3.1,-60.025,8,nope,2014-11-15,2015-11-15",
                                             "#then=95,-60,8,modis,2014-11-15,2015-11-15",
                                             "#then=-3.1,-60.025,8,modis,2014-11-15,2015-02-30",
                                             "#then=-3.1,-60.025,8,modis,2014-11-15", "#at=-3.1,-60.025",
                                             null].map(parseThen)]));
        """)
        self.assertEqual(got[0], "#then=-3.1000,-60.0250,8.00,modis,2014-11-15,2015-11-15")
        self.assertEqual(got[1], [
            {"lat": -3.1, "lon": -60.025, "z": 8, "source": "modis", "a": "2014-11-15", "b": "2015-11-15"},
            # Past 180 degrees east, -178.5, as #at= reads it; past the
            # archive's zoom, its zoom. Past 360 degrees, as for #at=, nothing.
            {"lat": -18.14, "lon": -178.5, "z": 19, "source": "archive", "a": "2019-06-26", "b": "2021-10-31"},
            None, None, None, None, None, None, None])

    def test_an_address_opens_entered_and_a_malformed_one_is_ignored(self):
        js = stormdesk.script()
        extra = "\n".join(_js_function(js, n) for n in ("parseHash", "maxZoom", "applyHash"))
        got = _run(self, MODIS_DAYS + r"""
          var ok = applyHash("#then=-3.1000,-60.0250,10.50,modis,2014-11-15,2015-11-15");
          await flush();
          var entered = [ok, S.then.label, S.then.source, S.then.preset, S.then.got, S.z, FLIGHTS.length,
                         CALLS.indexOf("settle") >= 0];
          var at = applyHash("#at=-18.14,178.44");
          var bad = [applyHash("#then=-3.1,-60.025,8,nope,2014-11-15,2015-11-15"), S.then];
          console.log(JSON.stringify([entered, at, S.then, CALLS.filter(function (c) { return c.indexOf("hereAt") === 0; }),
                                      bad]));
        """, extra=extra)
        # Opened from the address, the place is there at once: no flight.
        self.assertEqual(got, [[True, "Manaus, Amazonas, Brazil", "modis", "", {"a": "2014-11-15", "b": "2015-11-15"},
                                10.5, 0, True], True, None, ["hereAt undefined"], [False, None]])

    def test_copy_link_puts_the_address_on_the_clipboard_and_in_the_bar(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=8) + r"""
          $("then-copy").fire("click");
          var shown = S.then.link;
          await flush();
          thenRender();
          var copied = [S.then.link, COPIED.slice(), $("then-note").textContent.indexOf("Link copied: ") === 0];
          navigator.clipboard.writeText = function () { return Promise.reject(new Error("denied")); };
          thenCopy(); await flush();
          var refused = S.then.link;
          navigator.clipboard = undefined;
          thenCopy(); await flush();
          console.log(JSON.stringify([shown, copied, refused, S.then.link]));
        """)
        url = "file:///C:/elnino/output/map.html#then=-3.1000,-60.0250,8.00,modis,2014-11-15,2015-11-15"
        self.assertEqual(got, ["Copy this link: " + url, ["Link copied: " + url, [url], True],
                               "Copy this link: " + url, "Copy this link: " + url])

    def test_a_link_asked_for_while_the_sides_are_found_is_copied_once_they_are(self):
        got = _run(self, WB_ROUTES + _want("archive", "2025-09-29", "2026-09-29", preset="now") + r"""
          thenResolve();
          $("then-copy").fire("click");
          var waiting = [S.then.link, COPIED.length];
          await flush();
          console.log(JSON.stringify([waiting, COPIED, S.then.link]));
        """)
        # Copied at once, the link held the event's dates asked for; opened,
        # they were the reader's own and both sides showed one capture.
        url = "file:///C:/elnino/output/map.html#then=-3.1000,-60.0250,8.00,archive,2019-06-26,2021-10-31"
        self.assertEqual(got, [["The link is copied once both sides are found.", 0], [url], "Link copied: " + url])

    def test_street_view_takes_the_place_into_the_street(self):
        got = _run(self, MODIS_DAYS + MANAUS + r"""
          await flush();
          $("then-street").fire("click");
          advance(0);
          await flush();
          console.log(JSON.stringify([S.then, S.street && S.street.label, S.here, $("street-stage").hidden,
                                      CALLS.filter(function (c) { return /^googleFrame/.test(c); }),
                                      ASKED.filter(function (u) { return u.indexOf("routed-car") >= 0; }).length]));
        """)
        # The stage is Google's view of it now: Here's own frame is not opened.
        # Its street was asked for as a pick's is; with no answer, it stayed.
        self.assertEqual(got, [None, "Manaus", {"lon": -60.025, "lat": -3.1, "label": "Manaus"}, False, [], 1])


class TestThenKey(_DeskFixtures, unittest.TestCase):
    """The map's key while a place is entered on the ocean or the vegetation
    index: NASA's own scale, the one the readout reads each pixel back in."""

    page = TestThenMarkup.page

    def test_each_key_is_nasa_s_scale_swatch_for_swatch(self):
        html = thennow.legend()
        for key, head, ends in (
                ("sst", "Then and now: sea surface temperature anomaly, GHRSST MUR25",
                 "below −3.0 °C to +3.0 °C or more, in 0.1 °C steps: NASA's own scale, against MUR's own "
                 "climatology; land, ice and gaps are left clear"),
                ("ndvi", "Then and now: vegetation index, MODIS Terra NDVI, 16-day",
                 "NDVI 0.000, bare ground, to 1.000, dense canopy, in NASA's own 140 steps; water, cloud and "
                 "gaps are left clear")):
            group = re.search(f'<div class="keygroup ensokey" id="then-{key}-key" hidden>(.*?)</div>',
                              html).group(1)
            self.assertIn(f'<span class="keyhead">{head}</span>', group)
            swatches = re.findall(r'<i style="background:rgb\((\d+),(\d+),(\d+)\)"></i>', group)
            self.assertEqual([[int(v) for v in s] for s in swatches], [b["rgb"] for b in THEN["scales"][key]])
            self.assertIn(f"<span>{ends}</span>", group)

    def test_the_map_s_key_holds_both_after_the_composite_s(self):
        html = self.page()
        legend = html[html.index('<div class="desklegend" id="legend"'):html.index("<!--legend-->")]
        self.assertIn('id="then-sst-key"', legend)
        self.assertLess(legend.index('id="enso-key"'), legend.index('id="then-sst-key"'))
        # Named, so they can stand aside while a place is entered.
        self.assertIn('<div class="keygroup" id="storm-key"><span class="keyhead">Storms</span>', legend)
        self.assertIn('<details class="keymore" id="key-more"><summary>Key to the map</summary>', legend)
        self.assertIn(thennow.legend(), legend)
        # 140 swatches of 2 px, 280 px: inside a 360 px phone less its 16 px gutters.
        self.assertIn(".ndviramp i { width: 2px; }", thennow.css())


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenKeyRuns(unittest.TestCase):
    """The key follows the source: the ocean's scale, the vegetation index's,
    none for the imagery, and none once the place is left."""

    def test_the_key_follows_the_source_and_leaves_with_it(self):
        got = _run(self, r"""
          function keys() { thenRender(); return [$("then-sst-key").hidden, $("then-ndvi-key").hidden]; }
          thenEnter(-140, 0);
          var shown = [S.then.source, keys()];
          ["ndvi", "archive", "modis", "hls", "sst"].forEach(function (id) {
            $("then-source").fire("change", {target: {value: id}});
            shown.push(keys());
          });
          thenLeave();
          shown.push([$("then-sst-key").hidden, $("then-ndvi-key").hidden]);
          console.log(JSON.stringify(shown));
        """)
        self.assertEqual(got, ["sst", [False, True], [True, False], [True, True], [True, True], [True, True],
                               [False, True], [True, True]])

    def test_today_s_storm_key_stands_aside_while_entered_and_the_marks_key_with_none_picked(self):
        # The storm picked is still drawn over the place, its forecast
        # badged, so the key to its marks stays; the key to today's storms,
        # most of them not drawn, stands aside.
        got = _run(self, r"""
          function hidden() { return [$("storm-key").hidden, $("key-more").hidden]; }
          var out = [hidden()];
          [undefined, "al01"].forEach(function (id) {
            S.selected = id;
            thenEnter(-60.025, -3.1, "Manaus", {source: "modis", a: "2014-11-15", b: "2015-11-15"});
            thenRender();
            out.push(hidden());
            thenLeave();
            out.push(hidden());
          });
          console.log(JSON.stringify(out));
        """)
        self.assertEqual(got, [[False, False], [True, True], [False, False],
                               [True, False], [False, False]])


class TestThenDocumented(unittest.TestCase):
    """The README says what entering a place does and where each side comes
    from, and counts the tests there are."""

    def setUp(self):
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_the_readme_has_then_and_now_in_the_map_s_section(self):
        at = self.readme.index("### Then and now")
        self.assertLess(self.readme.index("## 13. The map"), at)
        self.assertLess(at, self.readme.index("## Composite power index"))
        for words in ("map.html#then=LAT,LON,ZOOM,SOURCE,LEFT,RIGHT", "waybackconfig.json", "tilemap",
                      "MODIS_Terra_CorrectedReflectance_TrueColor", "MODIS_Terra_L3_NDVI_16Day",
                      "GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies", "Esri World Imagery Wayback",
                      "elnino/thennow.py", "they do not attribute"):
            self.assertIn(words, self.readme)

    def test_the_readme_counts_the_tests_there_are(self):
        n = sum(len(re.findall(r"^    def test_", p.read_text(encoding="utf-8"), re.M))
                for p in (ROOT / "tests").glob("test_*.py"))
        self.assertIn(f"tests/                   {n} tests over", self.readme)
        self.assertIn(f"\n{n} tests, no network required.", self.readme)


if __name__ == "__main__":
    unittest.main()
