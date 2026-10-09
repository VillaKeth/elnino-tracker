"""The live site: pages that follow the run the site serves (elnino/live.py),
the beacon a run writes last, and the hourly run on GitHub that publishes it."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from elnino import assets, atlas, atlasview, dashboard, live, stormdesk, worldmap  # noqa: E402
# The helpers only: importing a TestCase class here would run it twice.
from test_tracker import _DeskFixtures, _js_function, _named_run, _node_json  # noqa: E402

RUN = "2026-10-01T11:12:00+00:00"


class TestTheBeaconAndTheHead(unittest.TestCase):
    """What a run writes for pages to follow, and what each page carries."""

    def test_the_beacon_names_the_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = live.write_run(RUN, Path(tmp) / live.BEACON)
            self.assertEqual(path.name, "run.json")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), {"run_at": RUN})

    def test_a_page_names_its_run_and_its_code_in_its_head(self):
        head = live.head(RUN)
        self.assertTrue(head.startswith(f'<meta name="elnino-run" content="{RUN}">\n'
                                        f'<meta name="elnino-code" content="{live.CODE}">\n<script>'), head)
        self.assertTrue(head.endswith("</script>"), head)

    def test_the_code_mark_is_the_source_s_whatever_its_line_endings(self):
        # A page taking runs in place takes only a run its own code wrote. The
        # mark is the package's source read as text: a checkout with Windows
        # line endings marks its pages as one with Unix line endings does.
        self.assertRegex(live.CODE, r"^[0-9a-f]{12}$")
        self.assertEqual(live.CODE, live.code_of(Path(live.__file__).parent))
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp)
            (src / "a.py").write_bytes(b"one\ntwo\n")
            (src / "b.py").write_bytes(b"three\n")
            (src / "notes.txt").write_bytes(b"not code\n")
            unix = live.code_of(src)
            (src / "a.py").write_bytes(b"one\r\ntwo\r\n")
            (src / "notes.txt").write_bytes(b"still not code\n")
            windows = live.code_of(src)
            (src / "b.py").write_bytes(b"four\n")
            changed = live.code_of(src)
            (src / "b.py").rename(src / "c.py")
            renamed = live.code_of(src)
        self.assertEqual(unix, windows)
        self.assertEqual(len({unix, changed, renamed}), 3)

    def test_the_run_is_written_as_an_attribute_value(self):
        self.assertIn('content="a&quot;&gt;&lt;b"', live.head('a"><b'))

    def test_a_page_with_no_run_time_carries_nothing(self):
        self.assertEqual(live.head(None), "")
        self.assertEqual(live.head(""), "")


class TestTheFollowerScript(unittest.TestCase):

    def test_it_asks_for_the_beacon_a_run_writes(self):
        self.assertIn(f'new URL("{live.BEACON}", location.href)', live.SCRIPT)

    def test_its_words_are_text_and_it_names_no_insecure_address(self):
        self.assertNotIn("innerHTML", live.SCRIPT)
        self.assertNotIn("http://", live.SCRIPT)


# The runs a test page shows and the site serves: the page's own, the next
# hour's and the one after.
RUN0, RUN1, RUN2 = RUN, "2026-10-01T12:12:00+00:00", "2026-10-01T13:12:00+00:00"
OFFER = ["The site has a new run, from 01 Oct 2026 12:12 UTC.", "Update now", "Later"]
ARRIVED = ["Now showing the run of 01 Oct 2026 12:12 UTC."]

# A browser for the follower: a clock the test moves, the site's run.json, a
# page with a body, a mark and sections, and the tab's sessionStorage.
PRELUDE = ("var RUN0 = " + json.dumps(RUN0) + ", RUN1 = " + json.dumps(RUN1)
           + ", RUN2 = " + json.dumps(RUN2) + ";\n") + r"""
var MINUTE = 60000, NOW = 0, TIMERS = [], SEQ = 0;
Date.now = function () { return NOW; };
function setTimeout(fn, ms) {
  var timer = {id: ++SEQ, at: NOW + Math.max(0, +ms || 0), fn: fn};
  TIMERS.push(timer);
  return timer.id;
}
function setInterval(fn, ms) {
  var timer = {id: ++SEQ, at: NOW + ms, fn: fn, every: ms};
  TIMERS.push(timer);
  return timer.id;
}
function clearTimeout(id) { TIMERS = TIMERS.filter(function (t) { return t.id !== id; }); }
var clearInterval = clearTimeout;
// Everything already promised is done: the site answered, takes finished.
function settled() { return new Promise(function (done) { setImmediate(done); }); }
// Time moves on: what was already promised settles first, as it would within
// moments in a browser; then each timer due runs in turn, and what it promised
// settles.
async function pass(ms) {
  var end = NOW + ms;
  await settled();
  for (;;) {
    var next = null;
    TIMERS.forEach(function (t) {
      if (t.at <= end && (!next || t.at < next.at || (t.at === next.at && t.id < next.id))) next = t;
    });
    if (!next) break;
    NOW = next.at;
    if (next.every) next.at += next.every;
    else TIMERS.splice(TIMERS.indexOf(next), 1);
    next.fn();
    await settled();
  }
  NOW = end;
  await settled();
}
// A hidden tab's timers frozen by the browser: time goes by and none run.
function freeze(ms) {
  NOW += ms;
  TIMERS.forEach(function (t) { if (t.at < NOW) t.at = NOW + (t.every || 0); });
}

// What run.json answers: a beacon, an HTTP status, "not JSON", an Error for no
// answer at all, or a function giving one of those each time it is asked.
var SITE = null, ASKED = [];
function fetch(url, init) {
  ASKED.push({url: String(url), cache: init && init.cache, at: NOW / MINUTE});
  var answer = typeof SITE === "function" ? SITE() : SITE;
  if (answer instanceof Error) return Promise.reject(answer);
  if (typeof answer === "number") return Promise.resolve({ok: false, status: answer});
  return Promise.resolve({ok: true, status: 200, json: function () {
    return answer === "not JSON" ? Promise.reject(new SyntaxError("Unexpected token"))
                                 : Promise.resolve(JSON.parse(JSON.stringify(answer)));
  }});
}

function El(tag) {
  this.tagName = tag.toUpperCase(); this.attrs = {}; this.children = []; this.on = {}; this.own = "";
  this.style = {overflowAnchor: ""};
}
El.prototype.setAttribute = function (name, value) { this.attrs[name] = String(value); };
El.prototype.getAttribute = function (name) { return name in this.attrs ? this.attrs[name] : null; };
El.prototype.appendChild = function (child) { this.children.push(child); child.parentNode = this; return child; };
El.prototype.addEventListener = function (type, fn) { (this.on[type] = this.on[type] || []).push(fn); };
El.prototype.click = function () { (this.on.click || []).forEach(function (fn) { fn({type: "click"}); }); };
El.prototype.find = function (tag) {
  for (var i = 0; i < this.children.length; i++) {
    var c = this.children[i];
    if (c.tagName === tag.toUpperCase()) return c;
    var deeper = c.find(tag);
    if (deeper) return deeper;
  }
  return null;
};
Object.defineProperty(El.prototype, "textContent", {
  get: function () { return this.own + this.children.map(function (c) { return c.textContent; }).join(""); },
  set: function (text) { this.own = String(text); this.children = []; }
});

var MARK = null, CODEMARK = null, ASSETS = [], SUMMARIES = [], LISTENING = {};
function listen(name, fn) { (LISTENING[name] = LISTENING[name] || []).push(fn); }
function fire(name, said) {
  var e = Object.assign({type: name}, said || {});
  (LISTENING[name] || []).forEach(function (fn) { fn(e); });
}
var document = {
  hidden: false,
  body: new El("body"),
  documentElement: new El("html"),
  createElement: function (tag) { return new El(tag); },
  querySelector: function (sel) {
    return sel === 'meta[name="elnino-run"]' ? MARK : sel === 'meta[name="elnino-code"]' ? CODEMARK : null;
  },
  getElementById: function (id) {
    for (var name in BOXES) { var found = BOXES[name].byId(id); if (found) return found; }
    return null;
  },
  querySelectorAll: function (sel) {
    if (sel === "details > summary") return SUMMARIES;
    if (sel === 'script[src^="assets/"]') return ASSETS;
    throw new Error("no fake for " + sel);
  },
  addEventListener: function (type, fn) { listen("document:" + type, fn); }
};
function hide(hidden) { document.hidden = hidden; fire("document:visibilitychange"); }
// The page's boxes, by id, laid out with the nodes in them: a node stands
// from top to bottom on the page, or in the content of the box that scrolls
// itself it is in, and the view reads it less the scroll above it; one hidden,
// or in one hidden, stands nowhere. A box notes when it is scrolled, and how
// the page's sections stand then.
var BOXES = {}, SCROLLS = [];
function Node(id, top, bottom, kids) {
  this.id = id; this.top = top; this.bottom = bottom; this.hidden = false; this.parentNode = null;
  this.children = kids; this.style = {overflowAnchor: ""}; this.scrollHeight = this.clientHeight = 0;
  kids.forEach(function (k) { k.parentNode = this; }, this);
}
function node(id, top, bottom) { return new Node(id, top, bottom, [].slice.call(arguments, 3)); }
function box(id, top, bottom) {
  var b = new Node(id, top || 0, bottom || 0, [].slice.call(arguments, 3)), scrollTop = 0;
  Object.defineProperty(b, "scrollTop", {
    get: function () { return scrollTop; },
    set: function (v) { scrollTop = v; SCROLLS.push([id, v, sections()]); }
  });
  return b;
}
Object.defineProperties(Node.prototype, {
  firstElementChild: {get: function () { return this.children[0] || null; }},
  nextElementSibling: {get: function () {
    var all = this.parentNode ? this.parentNode.children : [];
    return all[all.indexOf(this) + 1] || null;
  }}
});
Node.prototype.byId = function (id) {
  if (this.id === id) return this;
  for (var i = 0; i < this.children.length; i++) { var found = this.children[i].byId(id); if (found) return found; }
  return null;
};
Node.prototype.contains = function (n) { for (; n; n = n.parentNode) if (n === this) return true; return false; };
Node.prototype.getClientRects = function () {
  for (var n = this; n; n = n.parentNode) if (n.hidden) return [];
  var box = this.parentNode;
  while (box && !(box.scrollHeight > box.clientHeight)) box = box.parentNode;
  var off = box ? box.getBoundingClientRect().top - box.scrollTop : -window.scrollY;
  return [{top: this.top + off, bottom: this.bottom + off}];
};
Node.prototype.getBoundingClientRect = function () { return this.getClientRects()[0] || {top: 0, bottom: 0}; };
// A node and all in it moved down the page (up, for a negative px).
function lower(n, px) { n.top += px; n.bottom += px; n.children.forEach(function (k) { lower(k, px); }); }
// One node in place of another, as a take writes the new run's.
function swap(old, fresh) {
  var parent = old.parentNode;
  parent.children[parent.children.indexOf(old)] = fresh;
  fresh.parentNode = parent; old.parentNode = null;
  return fresh;
}
function anchoring() {
  return [document.documentElement.style.overflowAnchor].concat(Object.keys(BOXES).map(function (id) {
    return BOXES[id].style.overflowAnchor;
  }));
}

var DATA = {}, BLOCKED = false, FULL = false;
var STORE = {
  getItem: function (key) { return Object.prototype.hasOwnProperty.call(DATA, key) ? DATA[key] : null; },
  setItem: function (key, value) { if (FULL) throw new Error("QuotaExceededError"); DATA[key] = String(value); },
  removeItem: function (key) { delete DATA[key]; }
};
// The frames the browser is asked for, drawn when the test says.
var FRAMES = [];
var window = {
  scrollX: 0, scrollY: 0,
  scrollTo: function (x, y) { window.scrollX = x; window.scrollY = y; },
  scrollBy: function (x, y) { window.scrollX += x; window.scrollY += y; },
  // The tab's history entry, which a load keeps.
  history: {scrollRestoration: "auto"},
  requestAnimationFrame: function (fn) { FRAMES.push(fn); return FRAMES.length; },
  addEventListener: function (type, fn) { listen("window:" + type, fn); }
};
// A frame drawn: what asked for one is run, once. Says how many asked.
function frame() { var due = FRAMES; FRAMES = []; due.forEach(function (fn) { fn(); }); return due.length; }
Object.defineProperty(window, "sessionStorage", {get: function () {
  if (BLOCKED) throw new Error("SecurityError: the site's storage is blocked");
  return STORE;
}});

var RELOADS = [];
var location = {
  protocol: "https:", pathname: "/elnino-tracker/dashboard.html",
  href: "https://villaketh.github.io/elnino-tracker/dashboard.html",
  reload: function () { RELOADS.push(NOW / MINUTE); }
};
var KEY = "elnino-live:/elnino-tracker/dashboard.html";

function meta(run) { var m = new El("meta"); m.setAttribute("name", "elnino-run"); m.setAttribute("content", run); return m; }
function head() { /*HEAD*/ }
function follower() { /*SCRIPT*/ return elninoLive; }
// The page loaded afresh, naming `run` (null: no mark), with `sections` of
// [summary words, open] and `boxes`, each a box laid out or the id of an
// empty one: its head's script first, then the follower.
function load(run, options, sections, boxes) {
  TIMERS = []; LISTENING = {}; FRAMES = [];
  document.body = new El("body");
  document.documentElement = new El("html");
  MARK = run === null ? null : meta(run);
  SUMMARIES = (sections || []).map(function (s) {
    var summary = new El("summary");
    summary.textContent = s[0];
    summary.parentNode = {open: s[1]};
    return summary;
  });
  BOXES = {};
  (boxes || []).forEach(function (b) { b = typeof b === "string" ? box(b) : b; BOXES[b.id] = b; });
  window.scrollX = 0; window.scrollY = 0;
  head();
  var page = follower();
  page.follow(options);
  return page;
}
function notice() { return document.body.children.filter(function (c) { return c.className === "livenote"; })[0] || null; }
function said() {
  var n = notice(), p = n && n.children[0];
  return p ? [p.own].concat(p.children.map(function (c) { return c.textContent; })) : [];
}
function button() { var n = notice(); return n && n.find("button"); }
function buttons() {
  var n = notice(), p = n && n.children[0];
  return p ? p.children.filter(function (c) { return c.tagName === "BUTTON"; }) : [];
}
function sections() { return SUMMARIES.map(function (s) { return [s.textContent, s.parentNode.open]; }); }
"""


# The reader's place on a phone and on a wide screen, for the follower's tests.
PHONE = r"""
// A phone: the page scrolls, and the reader is 6,520 px down it, in the map's
// storm list, whose top is 2,400 px above the view's. Loaded again, the page
// above the list may stand short of where it will once it has settled.
function phone(short) {
  return box("panel", 1296 - short, 13000 - short,
             node("here", 1315 - short, 3377 - short),
             node("storm-list", 4120 - short, 11000 - short, node("", 4120 - short, 4600 - short)));
}
function list() { return document.getElementById("storm-list"); }
var BOXED = {boxes: ["panel", "legend"]};
"""
WIDE = r"""
// A wide screen's panel, 60 to 900 px down the view, which scrolls itself:
// the storms' rows, storm a's section, and storm b's, hidden.
function widePanel() {
  var p = box("panel", 60, 900, node("here", 0, 2340), node("enso-now", 2340, 3440),
              node("storm-list", 3440, 5340, node("", 3440, 3640), node("storm-a", 3640, 5340),
                   node("storm-b", 5340, 6000)));
  p.byId("storm-b").hidden = true;
  p.scrollHeight = 14000; p.clientHeight = 840;
  return p;
}
function list() { return document.getElementById("storm-list"); }
function noop() { return Promise.resolve(); }
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestFollowing(unittest.TestCase):
    """live.SCRIPT under node, in a page with a fake clock, site and storage."""

    def page(self, body: str):
        theme = re.fullmatch(r'(?:<meta [^>]*>\n)+<script>(.*)</script>', live.head(RUN), re.S).group(1)
        script = (PRELUDE.replace("/*SCRIPT*/", live.SCRIPT).replace("/*HEAD*/", theme)
                  + "(async function () {\n" + body + "\n})().catch(function (e) {\n"
                  "  console.error(e && e.stack || e); process.exit(1);\n});\n")
        return _node_json(self, script)

    def test_a_page_showing_the_site_s_run_only_asks(self):
        got = self.page(r"""
SITE = {run_at: RUN0};
load(RUN0);
await pass(3 * MINUTE);
console.log(JSON.stringify({asked: ASKED.map(function (a) { return a.at; }), cache: ASKED[0].cache,
                            reloads: RELOADS, said: said()}));
""")
        self.assertEqual(got, {"asked": [0, 1, 2, 3], "cache": "no-store", "reloads": [], "said": []})

    def test_a_page_from_a_file_or_naming_no_run_never_asks(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
location.protocol = "file:";
load(RUN0);
await pass(2 * MINUTE);
var fromFile = [ASKED.length, document.body.children.length];
location.protocol = "https:";
load(null);
await pass(2 * MINUTE);
console.log(JSON.stringify([fromFile, [ASKED.length, document.body.children.length], RELOADS]));
""")
        self.assertEqual(got, [[0, 0], [0, 0], []])

    # The site's worker, faked: what a page registers and tells it.
    WORKER = r"""
var REGISTERED = [], POSTED = [], REFUSE = false;
Object.defineProperty(globalThis, "navigator", {configurable: true, writable: true, value: {serviceWorker: {
  register: function (url) {
    REGISTERED.push(String(url));
    return REFUSE ? Promise.reject(new Error("SecurityError")) : Promise.resolve({});
  },
  ready: Promise.resolve({active: {postMessage: function (m) { POSTED.push(m); }}})
}}});
function script(src) { var s = new El("script"); s.setAttribute("src", src); return s; }
"""

    def test_a_served_page_has_the_site_s_worker_keep_the_assets_it_names(self):
        # GitHub Pages sends every file again after each publish; the worker
        # beside the pages (sw.js) keeps the assets, named for their
        # contents, told this page's at once so they are kept from a first
        # visit on.
        got = self.page(self.WORKER + r"""
SITE = {run_at: RUN0};
window.isSecureContext = true;
ASSETS = [script("assets/follower.0123456789.js"), script("assets/dashboard.abcdef0123.js")];
load(RUN0);
await settled();
console.log(JSON.stringify([REGISTERED, POSTED]));
""")
        self.assertEqual(got, [["sw.js"], [{"keep": [
            "https://villaketh.github.io/elnino-tracker/assets/follower.0123456789.js",
            "https://villaketh.github.io/elnino-tracker/assets/dashboard.abcdef0123.js"]}]])

    def test_a_page_from_a_file_or_an_insecure_origin_or_refused_a_worker_goes_on_without_one(self):
        got = self.page(self.WORKER + r"""
SITE = {run_at: RUN0};
ASSETS = [script("assets/follower.0123456789.js")];
location.protocol = "file:";
window.isSecureContext = true;
load(RUN0);
await settled();
var fromFile = REGISTERED.length;
location.protocol = "http:";
window.isSecureContext = false;
load(RUN0);
await settled();
var insecure = REGISTERED.length;
window.isSecureContext = true;
REFUSE = true;
load(RUN0);
await settled();
console.log(JSON.stringify([fromFile, insecure, REGISTERED.length, POSTED, ASKED.length > 0]));
""")
        # Refused, the page follows the site as before.
        self.assertEqual(got, [0, 0, 1, [], True])

    def test_a_page_taking_runs_in_place_takes_a_new_one_once(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
var takes = [];
load(RUN0, {take: function () {
  takes.push(NOW / MINUTE);
  MARK.setAttribute("content", RUN1);
  return Promise.resolve();
}});
await pass(5 * MINUTE);
console.log(JSON.stringify({takes: takes, reloads: RELOADS, said: said()}));
""")
        self.assertEqual(got, {"takes": [0], "reloads": [], "said": []})

    def test_a_run_a_page_cannot_take_in_place_is_loaded_once_the_reader_leaves_it_alone(self):
        # Another code's run: the page loads again for it, as the dashboard
        # does, its place handed over.
        got = self.page(r"""
SITE = {run_at: RUN1};
var takes = [];
load(RUN0, {take: function () { takes.push(NOW / MINUTE); return Promise.resolve(false); },
            keep: function () { return {view: "Lima"}; }});
await settled();
var offered = said();
await pass(1.5 * MINUTE);
var before = RELOADS.slice();
await pass(1 * MINUTE);
console.log(JSON.stringify({takes: takes, offered: offered, before: before, reloads: RELOADS,
                            handed: JSON.parse(DATA[KEY])}));
""")
        self.assertEqual(got, {"takes": [0], "offered": OFFER, "before": [], "reloads": [2], "handed": {
            "run": RUN1, "tries": 2, "next": 420000,
            "place": {"x": 0, "y": 0, "boxes": {}, "marks": [], "sections": [], "theme": None,
                      "kept": {"view": "Lima"}}}})

    def test_a_take_that_fails_part_way_is_loaded_with_no_later(self):
        # The take threw part way, leaving the page between two runs: it is
        # not kept as it is, so the run is offered without Later, and loaded
        # once the reader leaves the page alone.
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0, {take: function () { return Promise.reject(new Error("half taken")); }});
await settled();
var offered = said();
await pass(2 * MINUTE);
console.log(JSON.stringify({offered: offered, reloads: RELOADS}));
""")
        self.assertEqual(got, {"offered": ["The site has a new run, from 01 Oct 2026 12:12 UTC, which this page "
                                           "could take only in part.", "Update now"],
                               "reloads": [2]})

    def test_after_that_each_new_run_is_offered_not_taken(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
var takes = [];
load(RUN0, {take: function () { takes.push(NOW / MINUTE); return Promise.resolve(false); }});
await pass(1 * MINUTE);
SITE = {run_at: RUN2};
fire("window:pointermove");
await pass(1 * MINUTE);
console.log(JSON.stringify({takes: takes, said: said(), reloads: RELOADS}));
""")
        self.assertEqual(got, {"takes": [0], "reloads": [],
                               "said": ["The site has a new run, from 01 Oct 2026 13:12 UTC.", "Update now", "Later"]})

    def test_a_page_taking_runs_in_place_loaded_for_one_puts_its_place_back(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
var restored = [];
function options() {
  return {take: function () { return Promise.resolve(false); },
          keep: function () { return {view: [-77.04, -12.05, 9]}; },
          restore: function (kept) { restored.push(kept); }};
}
load(RUN0, options());
await settled();
button().click();
load(RUN1, options());
console.log(JSON.stringify({reloads: RELOADS, restored: restored, said: said(), kept: KEY in DATA}));
""")
        self.assertEqual(got, {"reloads": [0], "restored": [{"view": [-77.04, -12.05, 9]}], "said": ARRIVED,
                               "kept": False})

    def test_a_box_that_scrolls_itself_is_put_back_once_its_sections_are(self):
        # The storm desk's panel, on a wide screen: opening a table above the
        # part being read moves it down, so the panel is scrolled last.
        got = self.page(r"""
SITE = {run_at: RUN1};
var restored = [];
function options() {
  return {take: function () { return Promise.resolve(false); }, boxes: ["panel", "legend", "gone"],
          keep: function () { return {}; }, restore: function () { restored.push(sections()); }};
}
load(RUN0, options(), [["Table view", false]], ["panel", "legend"]);
BOXES.panel.scrollTop = 4449;
SUMMARIES[0].parentNode.open = true;
await settled();
button().click();
var handed = JSON.parse(DATA[KEY]).place.boxes;
SCROLLS = [];
load(RUN1, options(), [["Table view", false]], ["panel", "legend"]);
var scrolled = SCROLLS;
// What storage hands back is read like input: a box only from a number.
[{panel: "9", legend: null, gone: 5}, [["panel", 9]], "9"].forEach(function (boxes) {
  DATA[KEY] = JSON.stringify({run: RUN1, tries: 1, next: 0, place: {x: 0, y: 0, sections: [], boxes: boxes}});
  SCROLLS = [];
  load(RUN1, options(), [], ["panel", "legend"]);
  scrolled = scrolled.concat(SCROLLS);
});
console.log(JSON.stringify({handed: handed, restored: restored.slice(0, 1), scrolled: scrolled}));
""")
        self.assertEqual(got, {"handed": {"panel": 4449, "legend": 0},
                               "restored": [[["Table view", False]]],
                               "scrolled": [["panel", 4449, [["Table view", True]]],
                                            ["legend", 0, [["Table view", True]]]]})

    def test_a_page_loaded_again_is_put_back_by_what_stood_at_the_top_of_the_view(self):
        # Loaded again, then and now's words and Here's sea are still to come
        # above the list: the page there stands 62 px short, so the scroll
        # alone would show what was 62 px further down.
        got = self.page(PHONE + r"""
SITE = {run_at: RUN1};
load(RUN0, BOXED, [], [phone(0), "legend"]);
window.scrollTo(0, 6520);
await settled();
button().click();
var handed = JSON.parse(DATA[KEY]).place.marks;
load(RUN1, BOXED, [], [phone(62), "legend"]);
console.log(JSON.stringify({handed: handed, y: window.scrollY, at: list().getBoundingClientRect().top}));
""")
        self.assertEqual(got, {"handed": [{"box": "panel", "scrolls": False,
                                           "marks": [{"id": "storm-list", "at": -2400}]}],
                               "y": 6458, "at": -2400})

    def test_a_page_that_pins_its_menu_holds_the_reader_by_what_shows_below_it(self):
        # The dashboard pins its menu over the top of the view, and says how
        # far down that reaches (scroll-padding-top: 60px). A reader with the
        # globe's card 60 px down, where a link to it puts it, has the last
        # 40 px of the card above under the menu: what they are reading is
        # the globe's, and it stays where it stood when the card above comes
        # in 37 px taller.
        got = self.page(r"""
SITE = {run_at: RUN1};
window.getComputedStyle = function () { return {scrollPaddingTop: "60px"}; };
function dashboard(taller) {
  return box("page", 45, 20000, node("synopsis", 1000, 2000 + taller),
             node("globe", 2020 + taller, 4000 + taller));
}
load(RUN0, {boxes: ["page"]}, [], [dashboard(0)]);
window.scrollTo(0, 1960);
await settled();
button().click();
var handed = JSON.parse(DATA[KEY]).place.marks;
load(RUN1, {boxes: ["page"]}, [], [dashboard(37)]);
console.log(JSON.stringify({handed: handed, y: window.scrollY,
                            at: document.getElementById("globe").getBoundingClientRect().top}));
""")
        self.assertEqual(got, {"handed": [{"box": "page", "scrolls": False,
                                           "marks": [{"id": "globe", "at": 60}]}],
                               "y": 1997, "at": 60})

    def test_a_page_that_pins_nothing_holds_the_reader_by_the_top_of_the_view(self):
        # The desk, the map and the atlas pin nothing over their view, and a
        # browser says so ("auto"): what stands at the very top of the view is
        # held, the card whose foot the reader sees there.
        got = self.page(r"""
SITE = {run_at: RUN1};
window.getComputedStyle = function () { return {scrollPaddingTop: "auto"}; };
function phone(taller) {
  return box("page", 0, 20000, node("synopsis", 1000, 2000 + taller),
             node("globe", 2020 + taller, 4000 + taller));
}
load(RUN0, {boxes: ["page"]}, [], [phone(0)]);
window.scrollTo(0, 1960);
await settled();
button().click();
var handed = JSON.parse(DATA[KEY]).place.marks;
load(RUN1, {boxes: ["page"]}, [], [phone(37)]);
console.log(JSON.stringify({handed: handed, y: window.scrollY,
                            at: document.getElementById("globe").getBoundingClientRect().top}));
""")
        self.assertEqual(got, {"handed": [{"box": "page", "scrolls": False,
                                           "marks": [{"id": "synopsis", "at": -960}]}],
                               "y": 1960, "at": 97})

    def test_the_place_is_held_while_the_page_settles_until_the_view_moves_for_anything_else(self):
        # What is still to come comes: then and now's words (41 px) in a
        # browser that anchors the view itself, then Here's sea (21 px) in one
        # that does not (Safari before 27). Then the reader scrolls on.
        got = self.page(PHONE + r"""
SITE = {run_at: RUN1};
load(RUN0, BOXED, [], [phone(0), "legend"]);
window.scrollTo(0, 6520);
await settled();
button().click();
load(RUN1, BOXED, [], [phone(62), "legend"]);
var ys = [window.scrollY];
lower(list(), 41); window.scrollBy(0, 41); frame(); ys.push(window.scrollY);
lower(list(), 21); frame(); ys.push(window.scrollY);
window.scrollBy(0, 300); frame(); ys.push(window.scrollY);
lower(list(), 10);
console.log(JSON.stringify({ys: ys, drawn: frame(), y: window.scrollY}));
""")
        self.assertEqual(got, {"ys": [6458, 6499, 6520, 6820], "drawn": 0, "y": 6820})

    def test_the_place_is_held_for_fifteen_seconds_at_most(self):
        got = self.page(PHONE + r"""
SITE = {run_at: RUN1};
load(RUN0, BOXED, [], [phone(0), "legend"]);
window.scrollTo(0, 6520);
await settled();
button().click();
load(RUN1, BOXED, [], [phone(0), "legend"]);
await pass(14900);
lower(list(), 21); frame();
var held = window.scrollY;
await pass(100);
lower(list(), 21);
console.log(JSON.stringify({held: held, drawn: frame(), y: window.scrollY, asked: FRAMES.length}));
""")
        self.assertEqual(got, {"held": 6541, "drawn": 1, "y": 6541, "asked": 0})

    def test_what_stood_at_the_top_of_the_view_is_read_like_input(self):
        # Marks from storage: only a box by its id, and in it only a node by
        # its id, standing at a number. Anything else leaves the scroll as it
        # was handed, and nothing held.
        got = self.page(PHONE + r"""
var got = [];
[[{box: "panel", scrolls: false, marks: [{id: "storm-list", at: "-2400"}]}],
 [{box: "panel", scrolls: false, marks: [{id: "storm-list", at: null}]}],
 [{box: "panel", marks: "storm-list"}], [{box: 7, marks: []}], [null], "marks", {},
 [{box: "nowhere", marks: [{id: "storm-list", at: -2400}]}],
 [{box: "legend", marks: [{id: "storm-list", at: -2400}]}],
 [{box: "panel", marks: [{id: "gone", at: -2400}, {id: {}, at: -2400}]}]].forEach(function (marks) {
  DATA[KEY] = JSON.stringify({run: RUN1, tries: 1, next: 0, place: {x: 0, y: 6520, marks: marks}});
  load(RUN1, BOXED, [], [phone(62), "legend"]);
  got.push([window.scrollY, FRAMES.length]);
});
console.log(JSON.stringify(got));
""")
        self.assertEqual(got, [[6520, 0]] * 10)

    def test_a_take_puts_the_section_the_reader_is_in_back_where_it_stood(self):
        # A wide screen's panel, which scrolls itself, 4,000 px down: the
        # reader is in the first lines of storm a's section, under the storms'
        # rows. The take: a new storm's row above storm a puts it 120 px lower.
        got = self.page(WIDE + r"""
var page = load(RUN0, {take: noop, boxes: ["panel"]}, [], [widePanel()]);
var panel = BOXES.panel;
panel.scrollTop = 4000;
var putBack = page.hold(), during = anchoring();
swap(list(), node("storm-list", 3440, 5460, node("", 3440, 3760), node("storm-a", 3760, 5460)));
putBack();
var first = [panel.scrollTop, window.scrollY, during, anchoring()];
// A take that moves nothing scrolls nothing.
SCROLLS = [];
putBack = page.hold();
putBack();
console.log(JSON.stringify([first, panel.scrollTop, SCROLLS.length]));
""")
        self.assertEqual(got, [[4120, 0, ["none", "none"], ["", ""]], 4120, 0])

    def test_a_section_the_new_run_drops_or_hides_is_held_by_the_one_around_it(self):
        # The new run's list is 50 px lower and shows storm c, with storm a
        # gone, or hidden.
        got = self.page(WIDE + r"""
function take(a) {
  var page = load(RUN0, {take: noop, boxes: ["panel"]}, [], [widePanel()]);
  BOXES.panel.scrollTop = 4000;
  var putBack = page.hold();
  var fresh = node("storm-list", 3490, 5390, node("", 3490, 3690), node("storm-c", 3690, 5390));
  if (a) { a.hidden = true; fresh.children.push(a); a.parentNode = fresh; }
  swap(list(), fresh);
  putBack();
  return BOXES.panel.scrollTop;
}
console.log(JSON.stringify([take(null), take(node("storm-a", 3690, 5390))]));
""")
        self.assertEqual(got, [4050, 4050])

    def test_on_a_phone_a_take_holds_the_page_by_the_box_the_view_is_in(self):
        # Neither box scrolls itself: the page does. The reader is 5,600 px
        # down it, in storm a's section; the key above grows a line.
        got = self.page(WIDE + r"""
var legend = box("legend", 0, 600, node("enso-key", 0, 600));
var panel = box("panel", 600, 9600, node("here", 600, 2000),
                node("storm-list", 5100, 7000, node("", 5100, 5300), node("storm-a", 5400, 6400)));
var page = load(RUN0, {take: noop, boxes: ["panel", "legend"]}, [], [panel, legend]);
window.scrollTo(0, 5600);
var putBack = page.hold(), during = anchoring();
legend.bottom += 40; legend.children[0].bottom += 40; lower(panel, 40);
putBack();
console.log(JSON.stringify([window.scrollY, SCROLLS.length, during, anchoring()]));
""")
        self.assertEqual(got, [5640, 0, ["none", "none", "none"], ["", "", ""]])

    def test_a_box_below_the_top_of_the_view_is_not_held(self):
        # The reader is at the top of a phone's page, on the map: the panel
        # starts below, so nothing a take does there moves what they see.
        got = self.page(WIDE + r"""
var panel = box("panel", 1200, 9000, node("here", 1200, 1900));
var page = load(RUN0, {take: noop, boxes: ["panel"]}, [], [panel]);
var putBack = page.hold();
lower(panel.children[0], 60);
putBack();
console.log(JSON.stringify([window.scrollY, SCROLLS.length, FRAMES.length]));
""")
        self.assertEqual(got, [0, 0, 0])

    def test_a_reader_at_the_top_sees_what_comes_in_there(self):
        # As a browser anchors: a box at its top, or a page at its top, is
        # not held. A wide screen's panel at its top, Here shut: just after a
        # take the reader picks a place, and Here opens above the rest. And a
        # phone at the top of its page, where the run puts a banner first.
        got = self.page(WIDE + r"""
var p = box("panel", 60, 900, node("here", 0, 0), node("enso-now", 0, 1100),
            node("storm-list", 1100, 3000, node("storm-a", 1300, 3000)));
p.scrollHeight = 14000; p.clientHeight = 840;
var page = load(RUN0, {take: noop, boxes: ["panel"]}, [], [p]);
var putBack = page.hold();
putBack();
p.byId("here").bottom = 2340; lower(p.byId("enso-now"), 2340); lower(list(), 2340);
frame();
var wide = [p.scrollTop, FRAMES.length];
var top = box("page", 0, 5000, node("banner", 0, 0), node("card", 0, 800));
page = load(RUN0, {take: noop, boxes: ["page"]}, [], [top]);
putBack = page.hold();
putBack();
top.byId("banner").bottom = 60; lower(top.byId("card"), 60);
frame();
console.log(JSON.stringify([wide, [window.scrollY, FRAMES.length]]));
""")
        self.assertEqual(got, [[0, 0], [0, 0]])

    def test_the_reader_s_own_hand_ends_the_hold(self):
        # What moves after the reader presses, types, wheels or touches is
        # their doing (Here opened by a tap, a section opened); a pointer only
        # passing over the page is not a hand on it.
        got = self.page(WIDE + r"""
var got = [];
["pointerdown", "keydown", "wheel", "touchstart", "pointermove"].forEach(function (type) {
  var page = load(RUN0, {take: noop, boxes: ["panel"]}, [], [widePanel()]);
  BOXES.panel.scrollTop = 4000;
  var putBack = page.hold();
  putBack();
  fire("window:" + type);
  lower(list(), 120);
  var drawn = frame();
  got.push([type, BOXES.panel.scrollTop, drawn, FRAMES.length]);
});
console.log(JSON.stringify(got));
""")
        self.assertEqual(got, [["pointerdown", 4000, 1, 0], ["keydown", 4000, 1, 0], ["wheel", 4000, 1, 0],
                               ["touchstart", 4000, 1, 0], ["pointermove", 4120, 1, 1]])

    def test_a_slow_scroll_ends_the_hold(self):
        # The page's own smooth scroll, under a pixel a frame: no frame moves
        # the view by a pixel, but the view is moving, and is left to.
        got = self.page(WIDE + r"""
var panel = box("panel", 600, 9600, node("here", 600, 2000),
                node("storm-list", 5100, 7000, node("storm-a", 5400, 6400)));
var page = load(RUN0, {take: noop, boxes: ["panel"]}, [], [panel]);
window.scrollTo(0, 5600);
var putBack = page.hold();
putBack();
for (var i = 0; i < 20; i++) { window.scrollBy(0, 0.6); frame(); }
console.log(JSON.stringify(Math.round(window.scrollY * 10) / 10));
""")
        self.assertEqual(got, 5612)

    def test_a_hidden_page_holds_its_place_once_it_is_shown(self):
        # A hidden tab draws no frames, and one is loaded at once for a new
        # run: what comes in meanwhile (Here's sea) is put back when the
        # reader comes back to it, and the place is held from then on.
        got = self.page(PHONE + r"""
SITE = {run_at: RUN1};
load(RUN0, BOXED, [], [phone(0), "legend"]);
window.scrollTo(0, 6520);
await settled();
button().click();
document.hidden = true;
load(RUN1, BOXED, [], [phone(62), "legend"]);
var ys = [window.scrollY, FRAMES.length];
lower(list(), 21);
await pass(20000);
hide(false);
ys.push(window.scrollY);
lower(list(), 10); frame();
ys.push(window.scrollY);
console.log(JSON.stringify(ys));
""")
        self.assertEqual(got, [6458, 0, 6479, 6489])

    def test_after_a_take_the_place_is_held_while_the_page_settles(self):
        # Here's sea, asked again for the new run, answers after the take.
        got = self.page(WIDE + r"""
var panel = box("panel", 600, 9600, node("here", 600, 2000),
                node("storm-list", 5100, 7000, node("storm-a", 5400, 6400)));
var page = load(RUN0, {take: noop, boxes: ["panel"]}, [], [panel]);
window.scrollTo(0, 5600);
var putBack = page.hold();
putBack();
lower(document.getElementById("storm-list"), 21);
frame();
console.log(JSON.stringify(window.scrollY));
""")
        self.assertEqual(got, 5621)

    def test_the_browser_leaves_the_scroll_to_the_follower_until_the_page_has_loaded(self):
        # Chrome put a phone's page back at the scroll it was loaded from 20 ms
        # after the follower had put it back by its marks, undoing that. So
        # across the follower's own loads the browser leaves the scroll alone,
        # until the page loaded again has finished loading: then it keeps it
        # again, for the reader's own loads and for a tab it puts away and
        # brings back, which shows no page leaving to say so.
        got = self.page(PHONE + r"""
SITE = {run_at: RUN1};
load(RUN0, BOXED, [], [phone(0), "legend"]);
window.scrollTo(0, 6520);
await settled();
button().click();
var loading = window.history.scrollRestoration;
fire("window:pagehide");
var left = window.history.scrollRestoration;
load(RUN1, BOXED, [], [phone(62), "legend"]);
var arrived = window.history.scrollRestoration;
fire("window:load");
var loaded = window.history.scrollRestoration;
await pass(0);
console.log(JSON.stringify([RELOADS, loading, left, arrived, loaded, window.history.scrollRestoration]));
""")
        self.assertEqual(got, [[0], "manual", "manual", "manual", "manual", "auto"])

    def test_a_page_held_by_its_scroll_alone_leaves_it_to_the_browser(self):
        # No marks: the browser puts back the pixels the follower does, and
        # goes on trying as the page grows while it loads.
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0);
window.scrollTo(0, 900);
await settled();
button().click();
console.log(JSON.stringify([RELOADS, window.history.scrollRestoration]));
""")
        self.assertEqual(got, [[0], "auto"])

    def test_a_load_the_browser_never_made_is_given_up_when_the_page_is_shown_again(self):
        # The reader leaves the page while it offers a run: the load it then
        # asks for is not made, and the browser keeps the page as it was.
        # Shown again, the page keeps the scroll the browser's way, holds no
        # place for a load that did not happen, and offers the run as before.
        got = self.page(PHONE + r"""
SITE = {run_at: RUN1};
load(RUN0, BOXED, [], [phone(0), "legend"]);
window.scrollTo(0, 6520);
await settled();
hide(true);
var asked = [RELOADS.slice(), window.history.scrollRestoration];
fire("window:pagehide");
fire("window:pageshow", {persisted: true});
hide(false);
var shown = [window.history.scrollRestoration, KEY in DATA, said()];
await pass(2 * MINUTE);
console.log(JSON.stringify([asked, shown, RELOADS]));
""")
        self.assertEqual(got, [[[0], "manual"], ["auto", False, OFFER], [0, 2]])

    def test_a_load_with_no_place_handed_over_leaves_the_scroll_to_the_browser(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
BLOCKED = true;
load(RUN0);
await settled();
button().click();
console.log(JSON.stringify([RELOADS, window.history.scrollRestoration]));
""")
        self.assertEqual(got, [[0], "auto"])

    def test_a_page_knows_a_run_its_own_code_wrote(self):
        got = self.page(r"""
function codeMark(code) { var m = new El("meta"); m.setAttribute("content", code); return m; }
function doc(code) {
  return {querySelector: function (sel) { return sel === 'meta[name="elnino-code"]' && code ? codeMark(code) : null; },
          querySelectorAll: function () { return []; }};
}
var page = load(RUN0, {take: function () { return Promise.resolve(); }});
CODEMARK = codeMark("abc123");
var marked = [page.sameCode(doc("abc123")), page.sameCode(doc("def456")), page.sameCode(doc(null))];
CODEMARK = null;
console.log(JSON.stringify([marked, page.sameCode(doc(null))]));
""")
        self.assertEqual(got, [[True, False, False], False])

    def test_a_page_naming_other_assets_is_not_its_code_s_to_take(self):
        # Its markup was written for the code and data those assets hold
        # (elnino/assets.py), so the page loads again for it instead.
        got = self.page(r"""
function codeMark(code) { var m = new El("meta"); m.setAttribute("content", code); return m; }
function named(files) {
  return files.map(function (file) { var s = new El("script"); s.setAttribute("src", "assets/" + file); return s; });
}
function doc(code, files) {
  return {querySelector: function (sel) { return sel === 'meta[name="elnino-code"]' ? codeMark(code) : null; },
          querySelectorAll: function (sel) {
            if (sel === 'script[src^="assets/"]') return named(files);
            throw new Error("no fake for " + sel);
          }};
}
var page = load(RUN0, {take: function () { return Promise.resolve(); }});
CODEMARK = codeMark("abc123");
ASSETS = named(["places.0123456789.js", "desk.abcdef0123.js"]);
console.log(JSON.stringify([
  page.sameCode(doc("abc123", ["places.0123456789.js", "desk.abcdef0123.js"])),
  page.sameCode(doc("abc123", ["places.0123456789.js", "desk.fedcba9876.js"])),
  page.sameCode(doc("abc123", ["places.0123456789.js"])),
  page.sameCode(doc("abc123", []))]));
""")
        self.assertEqual(got, [True, False, False, False])

    def test_a_run_that_never_comes_is_gone_for_again_after_growing_pauses(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
var takes = [];
load(RUN0, {take: function () { takes.push(NOW / MINUTE); return Promise.resolve(); }});
await pass(50 * MINUTE);
console.log(JSON.stringify(takes));
""")
        self.assertEqual(got, [0, 2, 7, 17, 32, 47])

    def test_another_new_run_is_gone_for_at_once(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
var takes = [];
load(RUN0, {take: function () { takes.push([NOW / MINUTE, SITE.run_at]); return Promise.resolve(); }});
await pass(0.5 * MINUTE);
SITE = {run_at: RUN2};
await pass(1 * MINUTE);
console.log(JSON.stringify(takes));
""")
        self.assertEqual(got, [[0, RUN1], [1, RUN2]])

    def test_a_take_still_under_way_is_not_started_again(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
var takes = [];
load(RUN0, {take: function () {
  takes.push(NOW / MINUTE);
  return new Promise(function (done) { setTimeout(done, 3.5 * MINUTE); });
}});
await pass(5 * MINUTE);
console.log(JSON.stringify(takes));
""")
        self.assertEqual(got, [0, 4])

    def test_a_hidden_page_loads_a_new_run_at_once_handing_over_its_place(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
document.hidden = true;
load(RUN0, {}, [["ONI table", true], ["RONI table", false]]);
window.scrollTo(0, 1840);
await settled();
console.log(JSON.stringify({reloads: RELOADS, handed: JSON.parse(DATA[KEY])}));
""")
        self.assertEqual(got, {"reloads": [0], "handed": {
            "run": RUN1, "tries": 1, "next": 120000,
            "place": {"x": 0, "y": 1840, "boxes": {}, "marks": [],
                      "sections": [["ONI table", True], ["RONI table", False]], "theme": None, "kept": None}}})

    def test_a_page_in_view_offers_the_run_and_loads_it_once_left_alone(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0);
await settled();
var offered = said();
await pass(1 * MINUTE);
fire("window:pointermove");
await pass(1.5 * MINUTE);
var before = RELOADS.slice();
await pass(1 * MINUTE);
console.log(JSON.stringify({offered: offered, before: before, reloads: RELOADS}));
""")
        self.assertEqual(got, {"offered": OFFER, "before": [], "reloads": [3]})

    def test_update_now_loads_at_once(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0);
await settled();
button().click();
console.log(JSON.stringify({reloads: RELOADS, handed: JSON.parse(DATA[KEY]).run}));
""")
        self.assertEqual(got, {"reloads": [0], "handed": RUN1})

    def test_a_page_put_away_while_it_offers_a_run_loads_it(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0);
await pass(0.5 * MINUTE);
var before = RELOADS.slice();
hide(true);
console.log(JSON.stringify([before, RELOADS]));
""")
        self.assertEqual(got, [[], [0.5]])

    def test_a_page_loaded_for_a_new_run_puts_the_reader_back_and_says_so(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0, {}, [["ONI table", true], ["RONI table", false], ["WWV table", true]]);
document.documentElement.setAttribute("data-theme", "dark");
window.scrollTo(0, 1840);
await settled();
button().click();
load(RUN1, {}, [["RONI table", true], ["Nino 3.4 table", false], ["ONI table", false], ["WWV table", false]]);
var arrived = {theme: document.documentElement.getAttribute("data-theme"), y: window.scrollY,
               sections: sections(), said: said()};
await pass(7000);
console.log(JSON.stringify({arrived: arrived, after: said(), kept: KEY in DATA, reloads: RELOADS}));
""")
        self.assertEqual(got, {
            "arrived": {"theme": "dark", "y": 1840,
                        "sections": [["RONI table", False], ["Nino 3.4 table", False],
                                     ["ONI table", True], ["WWV table", True]],
                        "said": ARRIVED},
            "after": [], "kept": False, "reloads": [0]})

    def test_a_stale_copy_waits_out_the_pause_then_the_run_arrives(self):
        # Review Focus 2: a load that brought the page back as it was.
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0);
await settled();
button().click();
load(RUN0);
await settled();
var record = JSON.parse(DATA[KEY]);
await pass(1.5 * MINUTE);
var waited = {reloads: RELOADS.slice(), said: said()};
await pass(0.5 * MINUTE);
var again = JSON.parse(DATA[KEY]);
load(RUN1);
await settled();
console.log(JSON.stringify({record: record, waited: waited, reloads: RELOADS,
                            again: [again.tries, again.next], said: said(), kept: KEY in DATA}));
""")
        self.assertEqual(got, {"record": {"run": RUN1, "tries": 1, "next": 120000},
                               "waited": {"reloads": [0], "said": []}, "reloads": [0, 2],
                               "again": [2, 420000], "said": ARRIVED, "kept": False})

    def test_a_hand_over_that_would_hold_the_run_back_for_ever_is_read_like_input(self):
        # Left in the tab's storage by another version of the page, or by hand:
        # a pause past the longest is cut to it, and the tries counted from one.
        got = self.page(r"""
DATA[KEY] = JSON.stringify({run: RUN1, tries: "many", next: 1e15});
SITE = {run_at: RUN1};
load(RUN0);
await pass(16 * MINUTE);
console.log(JSON.stringify({reloads: RELOADS, tries: JSON.parse(DATA[KEY]).tries}));
""")
        self.assertEqual(got, {"reloads": [15], "tries": 2})

    def test_without_storage_a_page_only_offers(self):
        got = self.page(r"""
BLOCKED = true;
SITE = {run_at: RUN1};
load(RUN0);
await pass(10 * MINUTE);
hide(true);
var before = RELOADS.slice();
button().click();
console.log(JSON.stringify({said: said(), before: before, reloads: RELOADS}));
""")
        self.assertEqual(got, {"said": OFFER, "before": [], "reloads": [10]})

    def test_storage_refusing_the_write_leaves_the_page_offering_only(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0);
FULL = true;
await pass(5 * MINUTE);
hide(true);
var before = RELOADS.slice();
button().click();
console.log(JSON.stringify({said: said(), before: before, reloads: RELOADS}));
""")
        self.assertEqual(got, {"said": OFFER, "before": [], "reloads": [5]})

    def test_an_offer_is_withdrawn_when_the_site_goes_back(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0);
await pass(0.5 * MINUTE);
var offered = said();
SITE = {run_at: RUN0};
await pass(1 * MINUTE);
var withdrawn = said();
await pass(5 * MINUTE);
console.log(JSON.stringify({offered: offered, withdrawn: withdrawn, reloads: RELOADS}));
""")
        self.assertEqual(got, {"offered": OFFER, "withdrawn": [], "reloads": []})

    def test_answers_that_name_no_run_are_passed_over(self):
        got = self.page(r"""
var answers = [new Error("offline"), 404, "not JSON", {}, {run_at: ""}, {run_at: 5}, null, ["x"],
               {run_at: RUN1}];
SITE = function () { return answers.shift(); };
load(RUN0);
await pass(8 * MINUTE);
console.log(JSON.stringify({asked: ASKED.length, said: said(), reloads: RELOADS}));
""")
        self.assertEqual(got, {"asked": 9, "said": OFFER, "reloads": [8]})

    def test_a_page_asks_at_once_when_shown_again_or_back_online(self):
        got = self.page(r"""
SITE = {run_at: RUN0};
load(RUN0);
await pass(0.25 * MINUTE);
hide(true);
hide(false);
fire("window:online");
await settled();
console.log(JSON.stringify(ASKED.map(function (a) { return a.at; })));
""")
        self.assertEqual(got, [0, 0.25, 0.25])

    def test_a_page_that_took_a_run_in_place_names_it(self):
        got = self.page(r"""
var page = load(RUN0, {take: function () { return Promise.resolve(); }});
page.shows({querySelector: function (sel) { return sel === 'meta[name="elnino-run"]' ? meta(RUN1) : null; }});
var named = MARK.getAttribute("content");
page.shows({querySelector: function () { return null; }});
console.log(JSON.stringify([named, MARK.getAttribute("content")]));
""")
        self.assertEqual(got, [RUN1, RUN1])

    def test_the_head_puts_back_only_a_theme_the_page_has(self):
        got = self.page(r"""
var themes = [];
[JSON.stringify({place: {theme: "dark"}}), JSON.stringify({place: {theme: "light"}}),
 JSON.stringify({place: {theme: "sepia"}}), JSON.stringify({place: {}}), JSON.stringify({run: RUN1}),
 "not JSON", null].forEach(function (raw) {
  DATA = {};
  if (raw !== null) DATA[KEY] = raw;
  document.documentElement = new El("html");
  head();
  themes.push(document.documentElement.getAttribute("data-theme"));
});
BLOCKED = true;
DATA[KEY] = JSON.stringify({place: {theme: "dark"}});
document.documentElement = new El("html");
head();
themes.push(document.documentElement.getAttribute("data-theme"));
console.log(JSON.stringify(themes));
""")
        self.assertEqual(got, ["dark", "light", None, None, None, None, None, None])

    def test_one_run_written_two_ways_is_the_page_s_own(self):
        # Review Focus 1.
        got = self.page(r"""
SITE = {run_at: "2026-10-01T11:12:00Z"};
var takes = [];
load(RUN0, {take: function () { takes.push(NOW); return Promise.resolve(); }});
await pass(2 * MINUTE);
var inPlace = takes.length;
load(RUN0);
await pass(3 * MINUTE);
console.log(JSON.stringify({inPlace: inPlace, said: said(), reloads: RELOADS}));
""")
        self.assertEqual(got, {"inPlace": 0, "said": [], "reloads": []})

    def test_a_tab_hidden_for_hours_takes_only_the_latest_run_once(self):
        # Review Focus 3: the browser froze the hidden tab's timers for three
        # hours while the site served two runs.
        got = self.page(r"""
SITE = {run_at: RUN0};
load(RUN0);
await settled();
hide(true);
freeze(180 * MINUTE);
SITE = {run_at: RUN2};
hide(false);
await settled();
var shown = {said: said(), reloads: RELOADS.slice()};
await pass(2 * MINUTE);
console.log(JSON.stringify({shown: shown, reloads: RELOADS, handed: JSON.parse(DATA[KEY]).run}));
""")
        self.assertEqual(got, {"shown": {"said": ["The site has a new run, from 01 Oct 2026 13:12 UTC.",
                                                  "Update now", "Later"], "reloads": []},
                               "reloads": [182], "handed": RUN2})

    def test_a_run_older_than_the_page_s_own_is_neither_taken_nor_offered(self):
        # A cache the site's move has not reached yet, or a run put back on
        # purpose with --allow-older, answers with a run before the page's.
        got = self.page(r"""
SITE = {run_at: RUN0};
var takes = [];
load(RUN1, {take: function () { takes.push(NOW / MINUTE); return Promise.resolve(); }});
await pass(3 * MINUTE);
var inPlace = takes.length;
load(RUN1);
await pass(5 * MINUTE);
var older = {said: said(), reloads: RELOADS.slice()};
SITE = {run_at: RUN2};
await pass(1 * MINUTE);
console.log(JSON.stringify({inPlace: inPlace, older: older, reloads: RELOADS}));
""")
        self.assertEqual(got, {"inPlace": 0, "older": {"said": [], "reloads": []}, "reloads": [9]})

    def test_an_offer_is_not_traded_for_an_older_run(self):
        got = self.page(r"""
SITE = {run_at: RUN2};
load(RUN0);
await settled();
fire("window:pointermove");
SITE = {run_at: RUN1};
await pass(1 * MINUTE);
button().click();
console.log(JSON.stringify({said: said(), handed: JSON.parse(DATA[KEY]).run}));
""")
        self.assertEqual(got, {"said": ["The site has a new run, from 01 Oct 2026 13:12 UTC.", "Update now",
                                        "Later"], "handed": RUN2})

    def test_later_keeps_the_page_as_it_is_until_the_next_run(self):
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0);
await settled();
var offered = said();
buttons()[1].click();
var put = said();
await pass(10 * MINUTE);
hide(true);
hide(false);
await settled();
var still = {said: said(), reloads: RELOADS.slice()};
SITE = {run_at: RUN2};
await pass(1 * MINUTE);
var next = said();
await pass(1 * MINUTE);
console.log(JSON.stringify({offered: offered, put: put, still: still, next: next, reloads: RELOADS}));
""")
        self.assertEqual(got, {"offered": OFFER, "put": [], "still": {"said": [], "reloads": []},
                               "next": ["The site has a new run, from 01 Oct 2026 13:12 UTC.", "Update now",
                                        "Later"],
                               "reloads": [12]})

    def test_a_reader_saving_data_is_only_offered_a_new_run(self):
        # Data Saver: a page left open is never loaded again unasked.
        got = self.page(r"""
window.navigator = {connection: {saveData: true}};
SITE = {run_at: RUN1};
document.hidden = true;
load(RUN0);
await pass(1 * MINUTE);
hide(false);
await pass(10 * MINUTE);
hide(true);
var before = RELOADS.slice();
hide(false);
button().click();
console.log(JSON.stringify({said: said(), before: before, reloads: RELOADS}));
""")
        self.assertEqual(got, {"said": OFFER, "before": [], "reloads": [11]})

    def test_a_page_whose_own_state_fails_still_follows_the_site(self):
        # keep() and restore() are the page's own code: one that throws costs
        # the reader that state, never the following.
        got = self.page(r"""
SITE = {run_at: RUN1};
load(RUN0, {keep: function () { throw new Error("keep"); }});
window.scrollTo(0, 1840);
await settled();
button().click();
var handed = JSON.parse(DATA[KEY]).place;
DATA[KEY] = JSON.stringify({run: RUN1, tries: 1, next: 120000,
                            place: {x: 0, y: 1840, sections: [], theme: null, kept: {view: {}}}});
load(RUN1, {restore: function () { throw new Error("restore"); }});
await settled();
console.log(JSON.stringify({reloads: RELOADS, kept: handed.kept, handedY: handed.y, y: window.scrollY,
                            said: said(), asked: ASKED.length}));
""")
        self.assertEqual(got, {"reloads": [0], "kept": None, "handedY": 1840, "y": 1840, "said": ARRIVED,
                               "asked": 2})

    def test_the_beacon_is_asked_beside_the_page_whatever_its_address(self):
        # Review Focus 4.
        got = self.page(r"""
SITE = {run_at: RUN0};
var asked = [];
["https://villaketh.github.io/elnino-tracker/",
 "https://villaketh.github.io/elnino-tracker/storms.html#view=-80.0,25.0,4",
 "http://127.0.0.1:8765/map.html?from=dashboard"].forEach(function (href) {
  var url = new URL(href);
  location.href = href; location.protocol = url.protocol; location.pathname = url.pathname;
  ASKED = [];
  load(RUN0);
  asked.push(ASKED[0].url);
});
console.log(JSON.stringify(asked));
""")
        self.assertEqual(got, ["https://villaketh.github.io/elnino-tracker/run.json",
                               "https://villaketh.github.io/elnino-tracker/run.json",
                               "http://127.0.0.1:8765/run.json"])


class TestTheRunEndsWithTheBeacon(unittest.TestCase):
    """track.py writes run.json after every other file of the run."""

    def run_tracker(self, *argv, page="<html></html>", before=()):
        """The run's files as they stand when the beacon is written, every
        page written as page, into a folder holding before's files."""
        import track

        state = SimpleNamespace(run_at=RUN, alert_set=SimpleNamespace(alerts=[]), degraded=False,
                                assessment=SimpleNamespace(headline="quiet"))
        real, seen = live.write_run, []

        def beacon(run_at, path):
            folder = Path(path).parent
            seen.extend(sorted(p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()))
            return real(run_at, path)

        def data(_state, path):
            Path(path).write_text("{}", encoding="utf-8")

        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        out = Path(tmp.name)
        for name, body in before:
            (out / name).parent.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(body)
        with (mock.patch.object(track.pipeline, "run", return_value=state),
              mock.patch.object(track.dashboard, "render", return_value=page),
              mock.patch.object(track.atlasview, "page", return_value=page),
              mock.patch.object(track.stormdesk, "page", return_value=page),
              mock.patch.object(track.dashboard, "write_json", side_effect=data),
              mock.patch.object(track.stormdesk, "write_json", side_effect=data),
              mock.patch.object(track.live, "write_run", side_effect=beacon),
              mock.patch("sys.stdout"), mock.patch("sys.stderr")):
            code = track.main(["--offline", "--quiet", "--out", str(out), *argv])
        return code, out, seen

    def test_the_beacon_is_written_last_and_names_the_run(self):
        code, out, seen = self.run_tracker()
        self.assertEqual(code, 0)
        self.assertEqual(seen, ["atlas.html", "dashboard.html", "latest.json", "map.html",
                                "storms.html", "storms.json", "sw.js"])
        self.assertEqual((out / "sw.js").read_bytes(), assets.WORKER_JS.encode("utf-8"))
        self.assertEqual(json.loads((out / "run.json").read_text(encoding="utf-8")), {"run_at": RUN})

    def test_the_assets_the_pages_name_are_in_place_and_the_stale_gone_before_it(self):
        # A page that finds the run in the beacon finds every asset it names;
        # one no page names any more is let go, and other files are left.
        follower = assets.follower()
        code, out, seen = self.run_tracker(page=f"<html><head>{follower.tag()}</head></html>",
                                           before=(("assets/desk.0123456789.js", b"old"),
                                                   ("assets/notes.txt", b"mine")))
        self.assertEqual(code, 0)
        self.assertEqual(seen, sorted([f"assets/{follower.file}", "assets/notes.txt", "atlas.html",
                                       "dashboard.html", "latest.json", "map.html", "storms.html",
                                       "storms.json", "sw.js"]))
        self.assertEqual((out / "assets" / follower.file).read_bytes(), follower.text.encode("utf-8"))

    def test_a_run_writing_no_files_writes_no_beacon(self):
        code, out, seen = self.run_tracker("--no-files")
        self.assertEqual((code, seen), (0, []))
        self.assertFalse((out / "run.json").exists())


class TestTheDeskFollows(_DeskFixtures, unittest.TestCase):
    """storms.html and map.html take a new run in place."""

    def test_the_desk_and_the_map_name_their_run_and_take_new_runs_in_place(self):
        for focus in ("storms", "world"):
            with self.subTest(focus=focus):
                html = stormdesk.page(self.state(self.polo()), focus=focus)
                self.assertEqual(_named_run(html), "2026-09-25T16:04:00+00:00")
                self.assertEqual(assets.page_assets(html)[-2:], [assets.follower().file, assets.desk().file])
        script = stormdesk.script()
        self.assertEqual(script.count('  elninoLive.follow({take: refresh, keep: keepPlace, restore: restorePlace,\n'
                                      '                     boxes: ["panel", "legend"]});\n'), 1)
        self.assertEqual(script.count("setInterval(refresh"), 0)

    def test_a_theme_handed_over_is_set_before_the_page_is_styled(self):
        for focus in ("storms", "world"):
            with self.subTest(focus=focus):
                html = stormdesk.page(self.state(self.polo()), focus=focus)
                theme, style = html.find(live.head("2026-09-25T16:04:00+00:00")), html.find("<style>")
                self.assertTrue(0 <= theme < style, (theme, style))

    def test_the_header_s_stamp_is_one_a_refresh_can_replace(self):
        html = stormdesk.page(self.state(self.polo()))
        found = re.search(r'Built <span id="built">(<time datetime="[^"]*")', html)
        self.assertEqual(found and found.group(1), '<time datetime="2026-09-25T16:04:00Z"')

    def test_here_is_said_in_a_status_line_of_its_own(self):
        # Here as a whole was a live region, read out again on every take. A
        # line of its own, outside the panel a take writes, says which place
        # Here is on, and only when that changes.
        for focus in ("storms", "world"):
            with self.subTest(focus=focus):
                html = stormdesk.page(self.state(self.polo()), focus=focus)
                here = re.search(r'<section class="here" id="here"[^>]*>', html).group(0)
                self.assertNotIn("aria-live", here)
                self.assertEqual(html.count('</aside>\n<p class="heresaid" id="here-said" role="status"></p>\n'
                                            '</main>'), 1)
                self.assertIn(".findlabel, .heresaid {", html)

    def test_each_storm_s_row_is_named_by_its_storm(self):
        # The follower holds a reader by the part of the panel they are
        # reading, found again by its id: a storm's row in the list is one.
        html = stormdesk.page(self.state(self.polo()))
        rows = re.findall(r'<li class="stormrow"[^>]*>', html)
        named = re.findall(r'<li class="stormrow" id="row-([\w-]+)" data-row="([\w-]+)">', html)
        self.assertTrue(rows)
        self.assertEqual(len(named), len(rows), rows)
        self.assertTrue(all(row == storm for row, storm in named), named)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheDeskRefresh(unittest.TestCase):
    """refresh(), as the follower calls it: under node, with the page stubbed."""

    HARNESS = r"""
var CALLS = [], FETCHED = [];
function note(name) { CALLS.push(name); }
var D = {built: "2026-10-01T11:12:00Z", enso: {now: "SON"}};
var NEXT = {built: "2026-10-01T12:12:00Z", enso: {now: "DJF"}};
// The data the same on every run, as the page's assets set them.
var ELNINO = {places: [["Kingston", "Jamaica"]], coast: {lines: ["0,0"]}, grids: {PRECIP: {}, AIR: {}}};
var location = {href: "https://villaketh.github.io/elnino-tracker/storms.html#view=-80.0,25.0,4"};
function fetch(url, init) {
  FETCHED.push([url, init && init.cache]);
  return NEXT instanceof Error ? Promise.reject(NEXT)
    : Promise.resolve({ok: true, text: function () { return Promise.resolve("<html></html>"); }});
}
var PARSED = {
  "desk-data": function () { return {textContent: JSON.stringify(NEXT)}; },
  "panel": function () { return {innerHTML: "<p>the new run's panel</p>"}; },
  "legend": function () { return {innerHTML: "<p>the new run's key</p>"}; },
  "built": function () { return {innerHTML: '<time datetime="2026-10-01T12:12:00Z">1 Oct 12:12 UTC</time>'}; }
};
function DOMParser() {}
DOMParser.prototype.parseFromString = function () {
  return {getElementById: function (id) { return PARSED[id] ? PARSED[id]() : null; }};
};
var ELS = {};
function $(id) { return ELS[id] = ELS[id] || {id: id, innerHTML: "", querySelector: function () { return null; }}; }
// A storm's section in the panel: the page sets its tab as the reader left it.
var document = {querySelectorAll: function (sel) { return sel === "#panel section.storm" ? [{id: "storm-x"}] : []; }};
var S = {selected: null, then: null}, BYID = {}, STORMS = [];
var ensoSaid = "said", coastDone = 1, coastD = "M0", coastG = {innerHTML: "<path/>"};
function thenRefreshed() { note("thenRefreshed"); }
function prepare() { note("prepare"); }
function thenApply() { note("thenApply"); }
function tab() { note("tab"); }
function ensoControls() { note("ensoControls"); }
function render() { note("render"); }
var geoDirty = false;
function retake(box, html, keep) { note("retake " + box.id + (keep ? " around " + keep.id : "")); box.innerHTML = html; }
function select() { note("select"); }
function showHere() { note("showHere"); }
function ages() { note("ages"); }
function dirty() { note("dirty"); }
var SAME = true;
var elninoLive = {shows: function () { note("shows"); }, sameCode: function () { return SAME; },
                  hold: function () { note("hold"); return function () { note("put back"); }; }};
"""

    NAMES = ("refresh", "siteCopy", "newer", "takeRun", "withAssets")

    def refresh(self, body: str):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, name) for name in self.NAMES)
        return _node_json(self, self.HARNESS + functions + "\n" + body)

    def test_a_new_run_is_taken_and_named_once(self):
        got = self.refresh(r"""
var promised = refresh();
promised.then(function () {
  var first = {built: D.built, panel: $("panel").innerHTML, stamp: $("built").innerHTML, calls: CALLS.slice()};
  return refresh().then(function () {
    console.log(JSON.stringify({promised: typeof promised.then, first: first, calls: CALLS, fetched: FETCHED}));
  });
});
""")
        self.assertEqual(got["promised"], "function")
        self.assertEqual(got["first"]["built"], "2026-10-01T12:12:00Z")
        self.assertEqual(got["first"]["panel"], "<p>the new run's panel</p>")
        self.assertEqual(got["first"]["stamp"], '<time datetime="2026-10-01T12:12:00Z">1 Oct 12:12 UTC</time>')
        self.assertEqual(got["first"]["calls"][-1], "shows")
        self.assertEqual(got["calls"], got["first"]["calls"])
        self.assertEqual(got["fetched"], [["https://villaketh.github.io/elnino-tracker/storms.html", "no-store"]] * 2)

    def test_a_run_taken_reads_the_shared_data_from_the_page_s_assets(self):
        # The new run's page carries none of the data the same on every run
        # (elnino/assets.py): the page's own, which its assets set, go on.
        got = self.refresh(r"""
refresh().then(function () {
  console.log(JSON.stringify({built: D.built, now: D.enso.now, places: D.places === ELNINO.places,
                              coast: D.coast === ELNINO.coast, grids: D.enso.grids === ELNINO.grids}));
});
""")
        self.assertEqual(got, {"built": "2026-10-01T12:12:00Z", "now": "DJF", "places": True, "coast": True,
                               "grids": True})

    def test_a_refresh_that_fails_is_left_for_the_follower(self):
        got = self.refresh(r"""
NEXT = new Error("offline");
refresh().then(function () {
  console.log(JSON.stringify({built: D.built, calls: CALLS}));
}, function () { console.log(JSON.stringify("rejected")); });
""")
        self.assertEqual(got, {"built": "2026-10-01T11:12:00Z", "calls": []})

    def test_a_run_another_code_wrote_is_loaded_not_taken(self):
        got = self.refresh(r"""
SAME = false;
refresh().then(function (taken) { console.log(JSON.stringify({taken: taken, built: D.built, calls: CALLS})); });
""")
        self.assertEqual(got, {"taken": False, "built": "2026-10-01T11:12:00Z", "calls": []})

    def test_a_take_that_fails_part_way_fails_once_the_place_is_put_back(self):
        # The page is left between two runs: the promise fails, and the
        # follower loads the page for the run, with no Later to keep it so.
        got = self.refresh(r"""
prepare = function () { note("prepare"); throw new Error("a run this page cannot read"); };
refresh().then(function (taken) { console.log(JSON.stringify({taken: taken, last: CALLS.slice(-2)})); },
               function (err) { console.log(JSON.stringify({failed: err.message, last: CALLS.slice(-2)})); });
""")
        self.assertEqual(got, {"failed": "a run this page cannot read", "last": ["prepare", "put back"]})

    def test_only_a_newer_run_is_taken(self):
        # A copy older than the page's own run, as a CDN's edge can still
        # serve one, or the page's own run written another way, is passed
        # over: the follower asks again after a pause.
        got = self.refresh(r"""
var seen = [];
NEXT = {built: "2026-10-01T10:12:00Z"};
refresh().then(function (taken) {
  seen.push([taken, D.built]);
  NEXT = {built: "2026-10-01T11:12:00+00:00"};
  return refresh();
}).then(function (taken) {
  seen.push([taken, D.built]);
  console.log(JSON.stringify({seen: seen, calls: CALLS}));
});
""")
        self.assertEqual(got, {"seen": [[None, "2026-10-01T11:12:00Z"]] * 2, "calls": []})

    def test_the_panel_and_the_key_are_taken_as_the_reader_left_them(self):
        got = self.refresh(r"""
refresh().then(function () {
  console.log(JSON.stringify({calls: CALLS, panel: $("panel").innerHTML, key: $("legend").innerHTML}));
});
""")
        calls = got["calls"]
        # Here is the page's own: the panel is taken around it, and Here is
        # written from the new run once the run's data is in.
        self.assertEqual(calls[:3], ["hold", "retake panel around here", "retake legend"])
        self.assertEqual((got["panel"], got["key"]), ("<p>the new run's panel</p>", "<p>the new run's key</p>"))
        self.assertLess(calls.index("prepare"), calls.index("showHere"))
        # Each storm is on the tab the reader left it on: not put back on Now.
        self.assertNotIn("tab", calls)
        # Then and now follows the run against the new run's layers.
        self.assertLess(calls.index("prepare"), calls.index("thenRefreshed"))
        # The El Nino controls in the new panel (a region's Show) are as the
        # reader set them.
        self.assertLess(calls.index("retake panel around here"), calls.index("ensoControls"))

    def test_the_reader_s_place_is_held_until_the_new_run_is_drawn(self):
        got = self.refresh(r"""
refresh().then(function () { console.log(JSON.stringify({calls: CALLS, geo: geoDirty})); });
""")
        calls = got["calls"]
        # Drawn at once, keys and all, so the place is put back on the page as
        # it will stand; then the run is named.
        for step in ("showHere", "ages", "render"):
            self.assertLess(calls.index("hold"), calls.index(step))
            self.assertLess(calls.index(step), calls.index("put back"))
        self.assertEqual(calls[-2:], ["put back", "shows"])
        self.assertTrue(got["geo"])



@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheDeskKeepsThePlace(unittest.TestCase):
    """A run taken in place leaves the reader where they were: under node, on
    a small DOM where a string set as markup stands for the nodes a test lays
    out for it."""

    DOM = r"""
var MARKUP = {}, FOCUSED = [], ROOT = null;
function El(tag, attrs, kids) {
  this.tagName = tag.toUpperCase(); this.attrs = attrs || {}; this.childNodes = []; this.parentNode = null;
  this.words = ""; this.markup = ""; this.open = "open" in this.attrs; this.hidden = "hidden" in this.attrs;
  (kids || []).forEach(function (k) { if (typeof k === "string") this.words += k; else this.appendChild(k); }, this);
}
function h(tag, attrs) { return new El(tag, attrs, [].slice.call(arguments, 2)); }
Object.defineProperties(El.prototype, {
  id: {get: function () { return this.attrs.id || ""; }},
  attributes: {get: function () {
    var a = this.attrs;
    return Object.keys(a).map(function (k) { return {name: k, value: a[k]}; });
  }},
  textContent: {get: function () {
    return this.words + this.childNodes.map(function (k) { return k.textContent; }).join("");
  }},
  innerHTML: {
    get: function () { return this.markup; },
    set: function (html) {
      this.childNodes.slice().forEach(function (k) { this.removeChild(k); }, this);
      (MARKUP[html] ? MARKUP[html]() : []).forEach(function (k) { this.appendChild(k); }, this);
      this.markup = html;
    }
  }
});
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.appendChild = function (n) { return this.insertBefore(n, null); };
El.prototype.insertBefore = function (n, ref) {
  if (n.parentNode) n.parentNode.removeChild(n);
  var at = ref ? this.childNodes.indexOf(ref) : this.childNodes.length;
  if (at < 0) throw new Error("insertBefore: not a child");
  this.childNodes.splice(at, 0, n);
  n.parentNode = this;
  return n;
};
El.prototype.removeChild = function (n) {
  var at = this.childNodes.indexOf(n);
  if (at < 0) throw new Error("removeChild: not a child");
  this.childNodes.splice(at, 1);
  n.parentNode = null;
  return n;
};
El.prototype.contains = function (n) { for (; n; n = n.parentNode) if (n === this) return true; return false; };
El.prototype.matches = function (sel) {
  var el = this;
  return sel.split(",").some(function (one) {
    var m = /^\s*([a-z]*)((?:\.[\w-]+|\[[\w-]+(?:="[^"]*")?\])*)\s*$/.exec(one);
    if (!m) throw new Error("selector: " + one);
    if (m[1] && el.tagName !== m[1].toUpperCase()) return false;
    return (m[2].match(/\.[\w-]+|\[[^\]]+\]/g) || []).every(function (p) {
      if (p[0] === ".") return (" " + (el.attrs["class"] || "") + " ").indexOf(" " + p.slice(1) + " ") >= 0;
      var a = /^\[([\w-]+)(?:="([^"]*)")?\]$/.exec(p);
      return a[1] in el.attrs && (a[2] === undefined || el.attrs[a[1]] === a[2]);
    });
  });
};
El.prototype.querySelectorAll = function (sel) {
  var out = [];
  (function walk(el) { el.childNodes.forEach(function (k) { if (k.matches(sel)) out.push(k); walk(k); }); })(this);
  return out;
};
El.prototype.querySelector = function (sel) { return this.querySelectorAll(sel)[0] || null; };
El.prototype.closest = function (sel) {
  for (var el = this; el; el = el.parentNode) if (el.matches(sel)) return el;
  return null;
};
El.prototype.focus = function (opts) { document.activeElement = this; FOCUSED.push(opts); };
var document = {
  activeElement: null,
  createElement: function (tag) { return new El(tag); },
  getElementById: function (id) { return ROOT && ROOT.querySelector('[id="' + id + '"]'); },
  querySelectorAll: function (sel) { return ROOT ? ROOT.querySelectorAll(sel) : []; }
};
function $(id) { return document.getElementById(id); }
// A storm's section as the page writes it: its eye, its three tabs and
// panes, and its tables in the forecast pane, each [words, open].
function storm(id, tables) {
  var forecast = h("div", {"class": "pane", "data-pane": "forecast"});
  (tables || []).forEach(function (t) {
    forecast.appendChild(h("details", t[1] ? {"class": "tableview", open: ""} : {"class": "tableview"},
                           h("summary", {}, "Table view \u2014 " + t[0])));
  });
  return h("section", {id: "storm-" + id, "class": "storm", "data-storm": id},
    h("button", {"class": "eyebtn", "data-fly": id}, "Eye"),
    h("div", {"class": "tabs", role: "tablist"},
      h("button", {role: "tab", "data-tab": "now", "aria-selected": "true"}, "Now"),
      h("button", {role: "tab", "data-tab": "forecast", "aria-selected": "false"}, "Forecast"),
      h("button", {role: "tab", "data-tab": "protect", "aria-selected": "false"}, "Protect")),
    h("div", {"class": "pane", "data-pane": "now"}), forecast, h("div", {"class": "pane", "data-pane": "protect"}));
}
function shownTab(sec) {
  var on = sec.querySelector('[data-tab][aria-selected="true"]');
  var panes = sec.querySelectorAll("[data-pane]").filter(function (p) { return !p.hidden; });
  return [on && on.getAttribute("data-tab"), panes.map(function (p) { return p.getAttribute("data-pane"); })];
}
function opened(box) {
  return box.querySelectorAll("details").map(function (d) {
    return [d.closest("section").id, d.querySelector("summary").textContent, d.open];
  });
}
var S = {here: null, google: null};
"""
    NAMES = ("writeAround", "retake", "shownTabs", "knownAs", "tab", "hereWrite", "googlePressed", "hereSay")

    def run_js(self, body: str):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, name) for name in self.NAMES)
        return _node_json(self, self.DOM + functions + "\n" + body)

    def test_here_stays_and_the_rest_is_the_new_run_s_in_its_order(self):
        got = self.run_js(r"""
var frame = h("iframe", {src: "https://maps.google.com/maps?layer=c&output=svembed"});
var here = h("section", {id: "here"}, "Here: Lima", h("div", {id: "google-frame"}, frame));
var panel = h("aside", {id: "panel"}, here, h("section", {id: "enso-now"}, "run a's El Nino"),
              h("section", {id: "about"}, "run a's words"));
MARKUP["run b"] = function () {
  return [h("section", {id: "storm-x", "class": "storm"}, "run b's storm "), h("section", {id: "here", hidden: ""}),
          h("section", {id: "enso-now"}, "run b's El Nino")];
};
writeAround(panel, "run b", here);
console.log(JSON.stringify({ids: panel.childNodes.map(function (n) { return n.id; }),
                            here: panel.childNodes[1] === here, frame: here.querySelector("iframe") === frame,
                            words: panel.textContent}));
""")
        self.assertEqual(got, {"ids": ["storm-x", "here", "enso-now"], "here": True, "frame": True,
                               "words": "run b's storm Here: Limarun b's El Nino"})

    def test_a_box_without_the_node_to_keep_is_written_whole(self):
        got = self.run_js(r"""
MARKUP["run b"] = function () { return [h("p", {id: "here"}, "run b's here"), h("p", {}, "run b's words")]; };
var box = h("aside", {}, h("p", {id: "here"}, "run a's here")), old = box.childNodes[0];
writeAround(box, "run b", null);
var none = [box.textContent, box.childNodes[0] !== old];
// A node that is not the box's own (it went with a page written earlier).
var other = h("aside", {}, h("p", {}, "run a's words")), stray = h("p", {id: "here"});
writeAround(other, "run b", stray);
console.log(JSON.stringify([none, other.textContent, stray.parentNode === null]));
""")
        self.assertEqual(got, [["run b's hererun b's words", True], "run b's hererun b's words", True])

    def test_each_storm_stays_on_its_tab_and_a_new_one_opens_on_now(self):
        got = self.run_js(r"""
var panel = h("aside", {id: "panel"}, storm("a"), storm("b"));
ROOT = h("body", {}, panel);
tab($("storm-a"), "forecast");
tab($("storm-b"), "protect");
MARKUP["run b"] = function () { return [storm("a"), storm("c")]; };
retake(panel, "run b");
console.log(JSON.stringify([shownTab($("storm-a")), shownTab($("storm-c")), $("storm-b")]));
""")
        self.assertEqual(got, [["forecast", ["forecast"]], ["now", ["now"]], None])

    def test_each_table_stays_open_or_shut_and_one_with_new_words_opens_as_the_run_says(self):
        got = self.run_js(r"""
var panel = h("aside", {id: "panel"},
  storm("a", [["Best track", false], ["Official forecast", true], ["Wind speed probabilities, advisory 37", true]]),
  storm("b", [["Best track", false]]));
ROOT = h("body", {}, panel);
// The reader opens a's best track, shuts its forecast and its probabilities.
panel.querySelectorAll("details").forEach(function (d) {
  if (d.closest("section").id === "storm-a") d.open = !d.open;
});
MARKUP["run b"] = function () {
  return [storm("a", [["Best track", false], ["Official forecast", true], ["Wind speed probabilities, advisory 38", true]]),
          storm("b", [["Best track", false]])];
};
retake(panel, "run b");
console.log(JSON.stringify(opened(panel)));
""")
        self.assertEqual(got, [["storm-a", "Table view — Best track", True],
                               ["storm-a", "Table view — Official forecast", False],
                               ["storm-a", "Table view — Wind speed probabilities, advisory 38", True],
                               # The same words in another storm are that storm's own.
                               ["storm-b", "Table view — Best track", False]])

    def test_the_focus_stays_on_the_control_it_was_on(self):
        got = self.run_js(r"""
var panel = h("aside", {id: "panel"}, h("section", {id: "here"}, h("button", {"data-here": "show"}, "Show on map")),
              storm("a"), storm("b"));
ROOT = h("body", {}, panel);
MARKUP["run b"] = function () { return [h("section", {id: "here"}), storm("a")]; };
document.activeElement = $("storm-a").querySelector('[data-tab="forecast"]');
retake(panel, "run b", $("here"));
var tabbed = document.activeElement === $("storm-a").querySelector('[data-tab="forecast"]');
var moved = FOCUSED.slice();
// A control the new run does not have: the focus is not put anywhere else.
document.activeElement = $("storm-a").querySelector('[data-tab="now"]');
MARKUP["run c"] = function () { return [h("section", {id: "here"})]; };
FOCUSED = [];
retake(panel, "run c", $("here"));
var gone = FOCUSED.length;
// One in Here, which is not taken out, keeps it without being moved.
var inHere = $("here").querySelector("button");
document.activeElement = inHere;
retake(panel, "run b", $("here"));
console.log(JSON.stringify([tabbed, moved, gone, document.activeElement === inHere, FOCUSED.length]));
""")
        self.assertEqual(got, [True, [{"preventScroll": True}], 0, True, 0])

    def test_google_s_frame_open_on_here_is_never_taken_out(self):
        got = self.run_js(r"""
function here(words, pressed, frame) {
  return [h("h2", {id: "here-title"}, words),
          h("div", {"class": "herebtns"}, h("button", {"data-google": "map", "aria-pressed": "false"}, "Map"),
            h("button", {"data-google": "street", "aria-pressed": pressed ? "true" : "false"}, "Street View")),
          frame ? h("div", {id: "google-frame", "class": "gframe"}, frame) : h("div", {id: "google-frame", "class": "gframe", hidden: ""}),
          h("p", {"class": "links"}, "Google Maps")];
}
var frame = h("iframe", {src: "https://maps.google.com/maps?layer=c&cbll=-12.05,-77.04&output=svembed"});
var box = new El("section", {id: "here"}, here("Here: Lima", true, frame));
ROOT = h("body", {}, h("aside", {id: "panel"}, box));
S.here = {lon: -77.04, lat: -12.05, label: "Lima"};
S.google = {kind: "street", lon: -77.04, lat: -12.05};
MARKUP["Here, run b"] = function () { return here("Here: Lima, run b", false, null); };
hereWrite(box, "Here, run b");
var kept = [$("google-frame").childNodes[0] === frame, $("google-frame").hidden, $("here-title").textContent,
            document.querySelectorAll("[data-google]").map(function (b) { return b.getAttribute("aria-pressed"); }),
            S.google && S.google.kind];
// Here moved to another point: its frame is closed, as Google was asked of the last one.
S.here = {lon: -70.0, lat: -15.0, label: "Puno"};
hereWrite(box, "Here, run b");
console.log(JSON.stringify([kept, ROOT.contains(frame), $("google-frame").hidden, S.google]));
""")
        self.assertEqual(got, [[True, False, "Here: Lima, run b", ["false", "true"], "street"], False, True, None])

    def test_here_written_in_a_take_keeps_its_tables_and_the_focus(self):
        # As takeRun does it: the panel taken around Here, then Here written
        # from the new run around Google's frame. Events sampled stays open,
        # and the focus stays on Here's control, found again in the new run's
        # markup; the frame is the one there was.
        got = self.run_js(r"""
function here(words, frame) {
  return [h("h2", {id: "here-title"}, words),
          h("div", {"class": "herebtns"}, h("button", {"data-here": "show"}, "Show on map")),
          h("details", {}, h("summary", {}, "Events sampled")),
          frame ? h("div", {id: "google-frame"}, frame) : h("div", {id: "google-frame", hidden: ""})];
}
var frame = h("iframe", {src: "https://maps.google.com/maps?layer=c&cbll=-12.05,-77.04&output=svembed"});
var box = new El("section", {id: "here"}, here("Here: Lima", frame));
var panel = h("aside", {id: "panel"}, box, storm("a"));
ROOT = h("body", {}, panel);
S.here = {lon: -77.04, lat: -12.05, label: "Lima"};
S.google = {kind: "street", lon: -77.04, lat: -12.05};
box.querySelector("details").open = true;
document.activeElement = box.querySelector('[data-here="show"]');
MARKUP["run b"] = function () { return [h("section", {id: "here", hidden: ""}), storm("a")]; };
MARKUP["Here, run b"] = function () { return here("Here: Lima, run b", null); };
retake(panel, "run b", box);
hereWrite(box, "Here, run b");
console.log(JSON.stringify([box.querySelector("details").open,
                            document.activeElement === box.querySelector('[data-here="show"]'),
                            $("google-frame").childNodes[0] === frame, $("here-title").textContent]));
""")
        self.assertEqual(got, [True, True, True, "Here: Lima, run b"])

    def test_here_is_said_once_for_each_place(self):
        got = self.run_js(r"""
var line = h("p", {id: "here-said", role: "status"}), writes = 0;
Object.defineProperty(line, "textContent", {get: function () { return this.said || ""; },
                                            set: function (v) { writes++; this.said = v; }});
ROOT = h("body", {}, line);
hereSay("Here: Lima"); hereSay("Here: Lima"); hereSay("Here: Puno"); hereSay("");
console.log(JSON.stringify([line.textContent, writes]));
""")
        self.assertEqual(got, ["", 3])
        show = _js_function(stormdesk.script(), "showHere")
        self.assertIn('hereSay("Here: " + S.here.label);', show)
        self.assertIn('hereSay("");', show)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheDeskHandsItsPlaceOver(unittest.TestCase):
    """keepPlace() and restorePlace(): what the storm desk and the map hand
    themselves across a load for a run they cannot take in place, under node,
    with the page's setters saying what they are asked."""

    HARNESS = r"""
var CALLS = [];
function note(what) { CALLS.push(what); }
var MINZ = 1, anim = 0;
var LAYERS = {streets: {kind: "map"}, satellite: {kind: "map"}, geocolor: {kind: "imagery"},
              infrared: {kind: "imagery"}, "sst-ref": {kind: "reference"},
              "then-b": {kind: "imagery", then: true}};
var BYID = {ep152026: {}};
var D = {enso: {grids: {PRECIP: {}, AIR: {}}, season_label: {SON: "Sep-Nov", DJF: "Dec-Feb"},
                links: [{region: "Coastal Peru and Ecuador"}]}};
var S = {x: 0.5, y: 0.5, z: 3, layer: "streets", second: "infrared", compare: false, split: 0.5, scrub: 0,
         day: null, dayStepped: false, show: {cones: true, rings: true}, refs: {tropics: false},
         here: null, google: null, then: null, street: null, thenLast: null, selected: null, loop: false,
         loopWanted: false, frame: 0,
         enso: {variable: "PRECIP", season: "SON", mask: true, opacity: 0.6, tileOpacity: 0.8,
                tiles: {}, regions: false, boxes: true, shown: null}};
// A storm's section, on the tab `on` of the page's three.
function section(id, on) {
  function button(name) { return {getAttribute: function (k) { return k === "data-tab" ? name : null; }}; }
  return {id: id, on: on,
          querySelector: function (sel) { return sel === '[data-tab][aria-selected="true"]' ? button(this.on) : null; },
          querySelectorAll: function (sel) { return sel === "[data-tab]" ? ["now", "forecast", "protect"].map(button) : []; }};
}
// A box of the Overlays menu.
function overlay(attr, key, on) { return {checked: on, getAttribute: function (k) { return k === attr ? key : null; }}; }
var SECTIONS = [section("storm-ep152026", "forecast"), section("storm-al092026", "now")];
var PANEL = {querySelectorAll: function (sel) { return sel === "section.storm" ? SECTIONS : []; }};
var TICKS = {"[data-show]": [overlay("data-show", "cones", true), overlay("data-show", "rings", true)],
             "[data-ref]": [overlay("data-ref", "tropics", false)]};
var COMPARE = {value: "infrared"}, scrub = {value: "0"};
function $(id) { return id === "compare-layer" ? COMPARE : id === "panel" ? PANEL : null; }
var document = {querySelectorAll: function (sel) { return TICKS[sel] || []; }};
function readToggles() {
  TICKS["[data-show]"].forEach(function (b) { S.show[b.getAttribute("data-show")] = b.checked; });
  TICKS["[data-ref]"].forEach(function (b) { S.refs[b.getAttribute("data-ref")] = b.checked; });
  note("toggles " + JSON.stringify([S.show, S.refs]));
}
function setLayer(id) { note("layer " + id); S.layer = id; return true; }
function setCompare(on) { note("compare " + on + " with " + S.second); S.compare = on; return on; }
function thenSplit(v) { note("split " + v); S.split = v; }
function setEnso(patch) { note("enso " + JSON.stringify(patch)); }
function select(id) { note("select " + id); S.selected = id; }
function tab(sec, name) { note("tab " + sec.id + " " + name); }
function hereAt(lon, lat, label) { note("here " + lon + " " + lat + " " + label); S.here = {lon: lon, lat: lat, label: label}; }
function clearHere() { note("clear here"); S.here = null; }
// Google's map opens at the view's zoom.
function googleFrame(kind) { note("google " + kind + " at " + S.z); }
function thenEnter(lon, lat, label, opts) { note("enter " + JSON.stringify([lon, lat, label, opts])); S.then = {back: {}}; return true; }
// Leaving strips the address of the place, as the page's own does.
function thenLeave() {
  note("leave"); S.then = null;
  if (/^#then=/.test(location.hash)) history.replaceState(null, "", location.href.split("#")[0]);
}
var location = {href: "https://villaketh.github.io/elnino-tracker/map.html", hash: ""};
var history = {replaceState: function (s, t, url) {
  location.href = url; location.hash = url.indexOf("#") < 0 ? "" : url.slice(url.indexOf("#"));
}};
// The street entered and left, as the page's own leaves the address.
function streetEnter(lon, lat, label, opts) {
  note("street " + JSON.stringify([lon, lat, label, opts]));
  S.street = {lon: lon, lat: lat, back: {loop: false, playing: false}};
  return true;
}
function streetLeave() {
  note("street leave"); S.street = null;
  if (/^#street=/.test(location.hash)) history.replaceState(null, "", location.href.split("#")[0]);
}
function thenSrc(id) { return id === "modis" || id === "archive" ? {id: id} : null; }
function sideDay(T, k) { return T.want[k]; }
function realDay(text) { return /^\d{4}-\d\d-\d\d$/.test(text || ""); }
function ensoTileLayers() { return [{id: "sst"}, {id: "floods"}]; }
function maxZoom() { return 19; }
function cancelAnimationFrame() {}
function settle() { note("view " + [lonOf(S.x).toFixed(2), latOf(S.y).toFixed(2), S.z].join(" ")); }
function r6(x) { return Math.round(x * 1e6) / 1e6; }
// The loop's frames in view: one until GIBS has given the layer's.
var FRAMES = 1, loopTimer = 0;
function loopLength() { return FRAMES; }
function setTimeout() { return 1; }
function clearTimeout() {}
function dirty() {}
function tick() {}
"""
    NAMES = ("clamp", "wrap", "rad", "deg", "mx", "my", "lonOf", "latOf", "own", "finite", "drawable", "ticked",
             "ensoKept", "shownTabs", "keepPlace", "restorePlace", "setLoop", "loopWhenKnown", "streetView")
    TOGGLES = 'toggles [{"cones":true,"rings":true},{"tropics":false}]'

    def run_js(self, body: str):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, name) for name in self.NAMES)
        return _node_json(self, self.HARNESS + functions + "\n" + body)

    def test_what_the_reader_made_of_the_page_is_kept(self):
        got = self.run_js(r"""
S.x = mx(-77.04); S.y = my(-12.05); S.z = 9; S.layer = "satellite"; S.compare = true; S.second = "geocolor";
S.split = 0.4; S.scrub = 12; S.selected = "ep152026"; S.day = "2026-09-28"; S.dayStepped = true;
S.show.rings = false; S.loop = true;
S.here = {lon: -77.04, lat: -12.05, label: "Lima, Peru"}; S.google = {kind: "street", lon: -77.04, lat: -12.05};
// As the follower hands it over: written as JSON.
function kept() {
  var k = JSON.parse(JSON.stringify(keepPlace()));
  k.view = [r6(k.view.lon), r6(k.view.lat), k.view.z];
  return k;
}
var plain = kept();
// A day the reader did not step to is the page's own to find.
S.dayStepped = false;
var unstepped = kept().day;
// Entered: the map's own layers are the ones Exit goes back to.
S.layer = "then-a"; S.second = "then-b"; S.split = 0.7;
S.then = {lon: -77.04, lat: -12.05, label: "Lima, Peru", source: "modis", preset: "now", names: false,
          want: {a: "2025-10-01", b: "2026-10-01"},
          back: {layer: "satellite", second: "geocolor", compare: false, split: 0.4, loop: false}};
console.log(JSON.stringify([plain, unstepped, kept()]));
""")
        plain = {"view": [-77.04, -12.05, 9], "layer": "satellite", "second": "geocolor", "compare": True,
                 "split": 0.4, "scrub": 12, "day": "2026-09-28",
                 "show": {"cones": True, "rings": False}, "refs": {"tropics": False},
                 "enso": {"variable": "PRECIP", "season": "SON", "mask": True, "opacity": 0.6, "tileOpacity": 0.8,
                          "tiles": {}, "regions": False, "boxes": True, "shown": None},
                 "here": {"lon": -77.04, "lat": -12.05, "label": "Lima, Peru"}, "google": "street", "then": None,
                 "street": None, "thenLast": None,
                 "storm": "ep152026", "tabs": {"storm-ep152026": "forecast", "storm-al092026": "now"},
                 "loop": True}
        self.assertEqual(got[0], plain)
        self.assertIsNone(got[1])
        # Entered, the loop kept is the one Exit runs again.
        self.assertEqual(got[2], dict(plain, compare=False, day=None, loop=False, then={
            "lon": -77.04, "lat": -12.05, "label": "Lima, Peru", "source": "modis", "preset": "now",
            "a": "2025-10-01", "b": "2026-10-01", "names": False, "split": 0.7}))

    def test_what_was_kept_is_put_back(self):
        got = self.run_js(r"""
// The page opened on a place entered from its address.
S.then = {back: {}};
restorePlace({view: {lon: -77.04, lat: -12.05, z: 9}, layer: "satellite", second: "geocolor", compare: true,
              split: 0.4, scrub: 12, day: "2026-09-28",
              show: {cones: true, rings: false, gone: true}, refs: {tropics: true},
              enso: {variable: "AIR", season: "DJF", mask: false, opacity: 0.5, tileOpacity: 0.9,
                     tiles: {sst: true}, regions: false, boxes: true, shown: "Coastal Peru and Ecuador"},
              here: {lon: -77.04, lat: -12.05, label: "Lima, Peru"}, google: "street",
              then: {lon: -77.04, lat: -12.05, label: "Lima, Peru", source: "modis", preset: "now",
                     a: "2025-10-01", b: "2026-10-01", names: false, split: 0.7},
              storm: "ep152026", tabs: {"storm-ep152026": "forecast", "storm-al092026": "now"}, loop: true});
console.log(JSON.stringify({calls: CALLS, second: [S.second, COMPARE.value], scrub: [scrub.value, S.scrub],
                            day: [S.day, S.dayStepped], loop: [S.then.back.loop, S.loopWanted]}));
""")
        self.assertEqual(got["calls"], [
            "leave", "layer satellite", "compare true with geocolor", "split 0.4",
            'toggles [{"cones":true,"rings":false},{"tropics":true}]',
            'enso {"variable":"AIR","season":"DJF","mask":false,"regions":false,"boxes":true,"opacity":0.5,'
            '"tileOpacity":0.9,"tiles":{"sst":true,"floods":false},"shown":"Coastal Peru and Ecuador"}',
            "select ep152026", "tab storm-ep152026 forecast", "tab storm-al092026 now",
            "here -77.04 -12.05 Lima, Peru", "google street at 9",
            'enter [-77.04,-12.05,"Lima, Peru",{"source":"modis","preset":"now","a":"2025-10-01",'
            '"b":"2026-10-01","names":false,"instant":true}]', "split 0.7",
            "view -77.04 -12.05 9"])
        self.assertEqual({k: got[k] for k in ("second", "scrub", "day")},
                         {"second": ["geocolor", "geocolor"], "scrub": [12, 12], "day": ["2026-09-28", True]})
        # The place entered again: its Exit runs the loop again.
        self.assertEqual(got["loop"], [True, False])

    def test_a_loop_handed_over_runs_once_the_frames_in_view_are_known(self):
        # GIBS gives a layer's frames a moment after the page opens: the loop
        # waits for them, and runs from the latest once the map is drawn with
        # them in view. The reader's own Loop pressed meanwhile comes first.
        got = self.run_js(r"""
restorePlace({loop: true});
var waiting = [S.loop, S.loopWanted];
loopWhenKnown();
var drawn = [S.loop, S.loopWanted];
FRAMES = 12;
loopWhenKnown();
var running = [S.loop, S.frame, S.loopWanted];
setLoop(false); FRAMES = 1;
restorePlace({loop: true}); setLoop(false); FRAMES = 12; loopWhenKnown();
var pressed = [S.loop, S.loopWanted];
restorePlace({loop: "yes"});
console.log(JSON.stringify([waiting, drawn, running, pressed, S.loopWanted]));
""")
        self.assertEqual(got, [[False, True], [False, True], [True, 11, False], [False, False], False])
        self.assertIn("if (!moving) { S.inView = inView; loopWhenKnown(); }",
                      _js_function(stormdesk.script(), "tiles"))

    def test_what_is_not_the_page_s_own_is_left_as_the_page_opens(self):
        got = self.run_js(r"""
S.here = {lon: 0, lat: 0, label: "x"};
restorePlace({view: {lon: "x", lat: NaN, z: 9}, layer: "constructor", second: "then-b", compare: "yes",
              split: "0.4", scrub: Infinity, day: "yesterday", show: ["cones"], refs: {tropics: "on"},
              enso: {variable: "toString", season: "__proto__", mask: "no", opacity: "0.5", tiles: {sst: "on"},
                     shown: "Atlantis"},
              here: {lon: -77.04, lat: 120, label: "Lima"}, google: "earth",
              then: {lon: -77.04, lat: -12.05, source: "hubble"},
              storm: "hasOwnProperty", tabs: {"storm-ep152026": "radar", "storm-al092026": ["now"]}});
var first = CALLS.slice();
CALLS = [];
// Here's name, when it is not words, is the page's own for the point.
restorePlace({here: {lon: -77.04, lat: -12.05, label: {}}, google: "street"});
console.log(JSON.stringify({first: first, then: CALLS, second: [S.second, COMPARE.value], scrub: S.scrub,
                            day: S.day}));
""")
        self.assertEqual(got, {"first": [self.TOGGLES, 'enso {"tiles":{"sst":false,"floods":false}}'],
                               "then": [self.TOGGLES, "here -77.04 -12.05 ", "google street at 3"],
                               "second": ["infrared", "infrared"], "scrub": 0, "day": None})

    def test_a_place_the_reader_had_left_is_left_however_the_page_opened(self):
        got = self.run_js(r"""
S.here = {lon: 0, lat: 0, label: "x"}; S.then = {back: {}};
restorePlace({here: null, then: null});
console.log(JSON.stringify(CALLS));
""")
        self.assertEqual(got, ["leave", self.TOGGLES, "clear here"])

    def test_the_street_and_the_dates_last_compared_are_kept_and_put_back(self):
        got = self.run_js(r"""
S.street = {lon: -77.0428, lat: -12.0464, label: "Lima", mini: 17, box: {w: 220, h: 165}, link: "Link copied",
            back: {loop: false, playing: false}};
S.thenLast = {source: "modis", preset: "", a: "2014-11-15", b: "2015-11-15", names: false};
var k = JSON.parse(JSON.stringify(keepPlace()));
S.street = null; S.thenLast = null;
restorePlace(k);
console.log(JSON.stringify([k.street, k.thenLast, CALLS.filter(function (c) { return /^street/.test(c); }), S.thenLast]));
""")
        last = {"source": "modis", "preset": "", "a": "2014-11-15", "b": "2015-11-15", "names": False}
        self.assertEqual(got, [{"lon": -77.0428, "lat": -12.0464, "label": "Lima", "mini": 17}, last,
                               ['street [-77.0428,-12.0464,"Lima",{"mini":17}]'], last])

    def test_a_street_or_dates_not_the_page_s_own_are_left(self):
        got = self.run_js(r"""
var out = [];
[{street: {lon: "x", lat: 0}}, {street: {lon: -77.04, lat: 95}}, {street: "Lima"},
 {thenLast: {source: "hubble", a: "2014-11-15"}}, {thenLast: "modis"}].forEach(function (k) {
  CALLS = []; restorePlace(k); out.push(CALLS.filter(function (c) { return /^street/.test(c); }).length);
});
// A name that is not words is the page's own for the point.
CALLS = []; restorePlace({street: {lon: -77.04, lat: -12.05, label: {}, mini: "deep"}});
console.log(JSON.stringify([out, S.thenLast, CALLS.filter(function (c) { return /^street/.test(c); })]));
""")
        self.assertEqual(got, [[0, 0, 0, 0, 0], None, ['street [-77.04,-12.05,null,{"mini":"deep"}]']])

    def test_the_address_the_street_was_opened_from_is_kept(self):
        got = self.run_js(r"""
var linked = "https://villaketh.github.io/elnino-tracker/map.html#street=-12.04640,-77.04280";
history.replaceState(null, "", linked);
S.street = {lon: -77.0428, lat: -12.0464};
restorePlace({street: {lon: -77.0428, lat: -12.0464, label: "Lima", mini: 15}});
var opened = [location.href === linked, !!S.street, CALLS[0]];
S.street = {lon: -77.0428, lat: -12.0464};
restorePlace({street: null});
console.log(JSON.stringify([opened, location.href, S.street]));
""")
        self.assertEqual(got, [[True, True, "street leave"], "https://villaketh.github.io/elnino-tracker/map.html", None])

    def test_the_address_a_place_was_entered_from_is_kept(self):
        # Leaving the place the address opened on strips the address of it;
        # the place entered again, the address is put back as it was, so the
        # reader's own reload opens on it as before. A place the reader had
        # left stays left, and so does its address.
        got = self.run_js(r"""
var linked = "https://villaketh.github.io/elnino-tracker/map.html#then=-12.0500,-77.0400,9.00,modis,2025-10-01,2026-10-01";
history.replaceState(null, "", linked);
S.then = {back: {}};
restorePlace({then: {lon: -77.04, lat: -12.05, label: "Lima", source: "modis", preset: "now"}});
var entered = [location.href === linked, !!S.then];
S.then = {back: {}};
restorePlace({then: null});
console.log(JSON.stringify([entered, location.href, S.then]));
""")
        self.assertEqual(got, [[True, True], "https://villaketh.github.io/elnino-tracker/map.html", None])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestHereKeepsWhatNasaSaid(unittest.TestCase):
    """Here's lines read from NASA's tiles, which a take writes anew each run:
    a reading had is written as it is, not asked for again. Under node, with
    the tile and its pixel stubbed."""

    HARNESS = r"""
var S = {here: {lon: -77.04, lat: -12.05, label: "Lima"}, enso: {tiles: {sst: true, floods: false}}, imagery: "ok"};
var LAYERS = {sst: {id: "sst", zoom: 7}, floods: {id: "floods", zoom: 9}};
var D = {enso: {colours: {sst: [{rgb: [255, 0, 0], label: "+2.1 \u00b0C"}], floods: []}}};
var DAY = "2026-09-30", RGBA = [255, 0, 0, 255], TILES = [], NODES = {};
function ensoTileLayers() { return [LAYERS.sst, LAYERS.floods]; }
function source(id) { return {name: id}; }
function frameOf() { return {key: DAY}; }
function dayText(key) { return key; }
function ask() {}
function mx(lon) { return (lon + 180) / 360; }
function my() { return 0.5; }
function wrap(lon) { return lon; }
function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
function tileUrl(s, key) { return "https://gibs/" + s.name + "/" + key; }
function classify(entries, px) { return px[3] ? entries[0] : {transparent: true}; }
function esc(v) { return String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;"); }
function $(id) { return NODES[id] || null; }
// A tile is drawn on a canvas and read back as RGBA; asked for while RGBA
// is null, it fails, as when GIBS does not answer.
function Image() {}
Object.defineProperty(Image.prototype, "src", {set: function (url) {
  var img = this, rgba = RGBA;
  TILES.push(url);
  setImmediate(function () { if (rgba) img.onload(); else img.onerror(); });
}});
var document = {createElement: function () {
  return {getContext: function () {
    return {drawImage: function () {}, getImageData: function () { return {data: RGBA}; }};
  }};
}};
function settled() { return new Promise(function (done) { setImmediate(function () { setImmediate(done); }); }); }
"""
    NAMES = ("ensoWhat", "readEnso", "todayKey", "ensoTodayHtml", "ensoTodayRead")
    READ = "Ocean today (MUR SST anomaly, 2026-09-30): +2.1 \u00b0C at this pixel, on NASA\u2019s own colour scale"

    def run_js(self, body: str):
        js = worldmap._JS
        self.assertIn("\n  var TODAY = {};\n", js)
        functions = "\n".join(_js_function(js, name) for name in self.NAMES)
        return _node_json(self, self.HARNESS + "var TODAY = {};\n" + functions
                          + "\n(async function () {\n" + body + "\n})();\n")

    def test_a_reading_says_the_day_whose_pixel_was_read(self):
        got = self.run_js(r"""
var read = await readEnso("sst", -77.04, -12.05);
RGBA = null;
var failed = await readEnso("sst", -77.04, -12.05);
console.log(JSON.stringify([read, failed]));
""")
        self.assertEqual(got, [{"text": self.READ, "day": "2026-09-30"},
                               {"text": "Ocean today (MUR SST anomaly, 2026-09-30): NASA GIBS did not answer",
                                "day": ""}])

    def test_here_written_again_shows_the_reading_it_had_without_asking_again(self):
        got = self.run_js(r"""
var lon = S.here.lon, lat = S.here.lat, out = [];
out.push(ensoTodayHtml(lon, lat));
NODES["here-sst"] = {textContent: ""};
ensoTodayRead(lon, lat);
await settled();
out.push(NODES["here-sst"].textContent);
// A take writes Here anew: the reading is in it, and not asked for again.
out.push(ensoTodayHtml(lon, lat));
ensoTodayRead(lon, lat);
await settled();
out.push(TILES.length);
// The next day's tile is read afresh.
DAY = "2026-10-01";
out.push(ensoTodayHtml(lon, lat));
ensoTodayRead(lon, lat);
await settled();
out.push(TILES.length);
console.log(JSON.stringify(out));
""")
        head = "<h4>Today here, from NASA</h4>"
        self.assertEqual(got, [
            head + '<p id="here-sst">Ocean today (MUR SST anomaly, 2026-09-30): reading NASA\u2019s tile\u2026</p>',
            self.READ,
            head + '<p id="here-sst">' + self.READ + "</p>",
            1,
            head + '<p id="here-sst">Ocean today (MUR SST anomaly, 2026-10-01): reading NASA\u2019s tile\u2026</p>',
            2])

    def test_a_reading_that_failed_is_asked_for_again(self):
        got = self.run_js(r"""
var lon = S.here.lon, lat = S.here.lat;
NODES["here-sst"] = {textContent: ""};
RGBA = null;
ensoTodayRead(lon, lat);
await settled();
var said = NODES["here-sst"].textContent, again = ensoTodayHtml(lon, lat);
RGBA = [255, 0, 0, 255];
ensoTodayRead(lon, lat);
await settled();
console.log(JSON.stringify([said, again.indexOf("reading NASA") >= 0, TILES.length, NODES["here-sst"].textContent]));
""")
        self.assertEqual(got, ["Ocean today (MUR SST anomaly, 2026-09-30): NASA GIBS did not answer", True, 2,
                               self.READ])


class TestTheDashboardFollows(unittest.TestCase):

    def test_the_dashboard_loads_again_for_a_new_run(self):
        self.assertTrue(dashboard._js().endswith("\n  elninoLive.follow({ boxes: ['page'] });\n})();\n"))

    def test_every_page_styles_the_notice(self):
        # One stylesheet serves the dashboard, the atlas and the desk: the
        # notice sits at the foot of the screen, clear of a phone's home bar,
        # and stays off paper.
        css = dashboard._css()
        self.assertEqual(css.count(".livenote { position: fixed;"), 1)
        self.assertEqual(css.count("bottom: calc(16px + env(safe-area-inset-bottom, 0px));"), 1)
        self.assertEqual(css.count(".livenote button:focus-visible {"), 1)
        self.assertEqual(css.count(".livenote button + button { border-color: transparent;"), 1)
        self.assertEqual(css.count("@media print { .livenote { display: none; } }"), 1)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheDashboardAges(unittest.TestCase):

    def test_the_run_s_time_ages_while_the_page_is_open(self):
        js = dashboard._js()
        self.assertEqual(js.count("  ages();\n  setInterval(ages, 60000);\n"), 1)
        functions = "\n".join(_js_function(js, name) for name in ("span", "ago", "ages"))
        got = _node_json(self, functions + r"""
var STAMP = {attrs: {"datetime": "2026-10-01T11:12:00+00:00", "data-age": "01 Oct 2026 11:12 UTC"},
             textContent: ""};
STAMP.getAttribute = function (name) { return this.attrs[name]; };
var document = {querySelectorAll: function (sel) { return sel === "time[data-age]" ? [STAMP] : []; }};
var said = [];
[0, 12, 185, 4320].forEach(function (minutes) {
  Date.now = function () { return Date.parse("2026-10-01T11:12:00Z") + minutes * 60000; };
  ages();
  said.push(STAMP.textContent);
});
console.log(JSON.stringify(said));
""")
        self.assertEqual(got, ["01 Oct 2026 11:12 UTC (0 min ago)", "01 Oct 2026 11:12 UTC (12 min ago)",
                               "01 Oct 2026 11:12 UTC (3 h 5 min ago)", "01 Oct 2026 11:12 UTC (3 days ago)"])


class TestTheAtlasFollows(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.html = atlasview.page(SimpleNamespace(
            atlas=atlas.evaluate(), cyclones=SimpleNamespace(storms=(), available=False),
            generated=date(2026, 9, 23), run_at=RUN))

    def test_the_atlas_names_its_run(self):
        self.assertEqual(_named_run(self.html), RUN)

    def test_a_theme_handed_over_is_set_before_the_atlas_is_styled(self):
        theme, style = self.html.find(live.head(RUN)), self.html.find("<style>")
        self.assertTrue(0 <= theme < style, (theme, style))

    def test_it_loads_again_for_a_new_run_keeping_its_own_state(self):
        self.assertEqual(assets.page_assets(self.html)[-2:], [assets.follower().file, assets.atlas().file])
        self.assertTrue(atlasview._JS.rstrip().endswith(
            "  fromHash();\n  elninoLive.follow({ keep: keep, restore: restore });\n})();"))


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheAtlasKeepsItsPlace(unittest.TestCase):
    """keep() and restore(), under node, with the atlas's state stubbed."""

    HARNESS = r"""
var D = {grids: {PRECIP: {}, AIR: {}}, seasons: ["DJF", "MAM", "JJA", "SON"]};
var BASE = {relief: {}, imagery: {}, sst: {}};
var view = {lon: 150, lat: 0, dpp: 1.2}, variable = "PRECIP", season = "DJF", fade = true;
var show = {borders: true, rivers: true, places: true}, marked = null, base = "relief", composite = true;
var panel = {scrollTop: 0}, CALLS = [];
function clampView() { CALLS.push("clampView"); }
function pick(lon, lat) { CALLS.push(["pick", lon, lat]); marked = {lon: lon, lat: lat, box: null}; panel.scrollTop = 0; }
function syncBar() { CALLS.push("syncBar"); }
function schedule() { CALLS.push("schedule"); }
"""

    def page(self, body: str):
        functions = "\n".join(_js_function(atlasview._JS, name)
                              for name in ("own", "finite", "lon180", "keep", "restore"))
        return _node_json(self, self.HARNESS + functions + "\n" + body)

    def test_the_view_the_layers_and_the_point_come_back(self):
        got = self.page(r"""
view = {lon: -75.5, lat: 12.25, dpp: 0.05}; variable = "AIR"; season = "JJA"; fade = false;
show = {borders: false, rivers: true, places: false}; base = "sst"; composite = false;
marked = {lon: -74, lat: 11, box: [0, 1, 2, 3]}; panel.scrollTop = 340;
var kept = JSON.parse(JSON.stringify(keep()));
view = {lon: 150, lat: 0, dpp: 1.2}; variable = "PRECIP"; season = "DJF"; fade = true;
show = {borders: true, rivers: true, places: true}; base = "relief"; composite = true;
marked = null; panel.scrollTop = 0;
restore(kept);
console.log(JSON.stringify({view: view, variable: variable, season: season, fade: fade, show: show,
                            base: base, composite: composite, marked: [marked.lon, marked.lat],
                            dossier: panel.scrollTop, calls: CALLS}));
""")
        self.assertEqual(got, {"view": {"lon": -75.5, "lat": 12.25, "dpp": 0.05}, "variable": "AIR",
                               "season": "JJA", "fade": False,
                               "show": {"borders": False, "rivers": True, "places": False},
                               "base": "sst", "composite": False, "marked": [-74, 11], "dossier": 340,
                               "calls": ["clampView", ["pick", -74, 11], "syncBar", "schedule"]})

    def test_a_view_turned_any_number_of_times_comes_back_on_the_world(self):
        # clampView() wraps a longitude a turn at a time: a view handed back
        # turned 1e300 degrees would never be done wrapping, and the tab would hang.
        got = self.page(r"""
var lons = [];
[190, -190, 540, 1e300, -1e300].forEach(function (lon) {
  restore({view: {lon: lon, lat: 0, dpp: 1}});
  lons.push(view.lon);
});
console.log(JSON.stringify(lons));
""")
        self.assertEqual(got[:3], [-170, 170, -180])
        self.assertTrue(all(-180 <= lon < 180 for lon in got), got)

    def test_what_is_not_the_atlas_s_own_is_left_as_the_page_opens(self):
        got = self.page(r"""
restore({variable: "toString", season: "Monsoon", fade: "no", composite: 0, base: "__proto__",
         show: {borders: "off", rivers: false, lakes: true}, view: {lon: 1e999, lat: 0, dpp: 1},
         marked: {lon: 10, lat: 95}, dossier: 99});
var out = {view: view, variable: variable, season: season, fade: fade, show: show, base: base,
           composite: composite, marked: marked, dossier: panel.scrollTop, calls: CALLS};
CALLS = [];
restore({view: {lon: 10, lat: 5, dpp: 0}, marked: {lon: "10", lat: 5}});
out.again = {view: view, calls: CALLS};
console.log(JSON.stringify(out));
""")
        self.assertEqual(got, {"view": {"lon": 150, "lat": 0, "dpp": 1.2}, "variable": "PRECIP",
                               "season": "DJF", "fade": True,
                               "show": {"borders": True, "rivers": False, "places": True},
                               "base": "relief", "composite": True, "marked": None, "dossier": 0,
                               "calls": ["syncBar", "schedule"],
                               "again": {"view": {"lon": 150, "lat": 0, "dpp": 1.2},
                                         "calls": ["syncBar", "schedule"]}})


class TestTheHourlyRun(unittest.TestCase):
    """.github/workflows/live.yml and tests.yml, read as text."""

    def setUp(self):
        workflows = ROOT / ".github" / "workflows"
        self.live = (workflows / "live.yml").read_text(encoding="utf-8")
        self.tests = (workflows / "tests.yml").read_text(encoding="utf-8")

    def test_it_runs_every_hour_by_hand_and_on_new_code(self):
        self.assertIn('    - cron: "12 * * * *"\n', self.live)
        self.assertIn("  workflow_dispatch:\n", self.live)
        self.assertIn("  push:\n    branches: [main]\n", self.live)

    def test_a_dropped_hour_has_a_second_chance_at_42_past(self):
        # GitHub may hold a scheduled run under load, or drop it, as it dropped
        # the first of all. The run waits on the check that decides.
        self.assertIn('    - cron: "42 * * * *"\n', self.live)
        self.assertIn("  run:\n    needs: due\n"
                      "    if: ${{ !cancelled() && needs.due.outputs.skip != 'true' }}\n", self.live)
        self.assertIn("--jq '(now - (.commit.committer.date | fromdateiso8601)) / 60 | floor'", self.live)

    @unittest.skipIf(sys.platform == "win32", "the hourly run is Linux")
    def test_the_second_chance_is_skipped_only_once_the_hour_s_run_is_out(self):
        # The check's own script, under bash as the run has it, with a gh that
        # answers how many minutes ago gh-pages was published, or fails.
        body = self.live.split("        id: age\n", 1)[1].split("        run: |\n", 1)[1]
        lines = []
        for line in body.splitlines():
            if line.strip() and not line.startswith(" " * 10):
                break
            lines.append(line[10:])
        with tempfile.TemporaryDirectory() as tmp:
            here = Path(tmp)
            (here / "check.sh").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            gh = here / "gh"
            gh.write_text('#!/bin/sh\necho "$*" >> "$CALLS"\n[ -n "$AGO" ] || exit 1\necho "$AGO"\n',
                          encoding="utf-8", newline="\n")
            gh.chmod(0o755)
            out, calls = here / "output", here / "calls"
            for slot, ago, skip in (("", "5", "false"), ("12 * * * *", "5", "false"),
                                    ("42 * * * *", "5", "true"), ("42 * * * *", "44", "true"),
                                    ("42 * * * *", "45", "false"), ("42 * * * *", "90", "false"),
                                    ("42 * * * *", "", "false"), ("42 * * * *", "soon", "false")):
                with self.subTest(slot=slot, ago=ago):
                    out.write_text("", encoding="utf-8")
                    calls.unlink(missing_ok=True)
                    env = dict(os.environ, PATH=f"{here}{os.pathsep}{os.environ['PATH']}", SLOT=slot, AGO=ago,
                               CALLS=str(calls), GITHUB_OUTPUT=str(out), GITHUB_REPOSITORY="owner/repo")
                    done = subprocess.run(["bash", "--noprofile", "--norc", "-eo", "pipefail", str(here / "check.sh")],
                                          env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                                          timeout=60)
                    self.assertEqual(done.returncode, 0, done.stderr)
                    self.assertEqual(out.read_text(encoding="utf-8"), f"skip={skip}\n")
                    # Only the second chance asks GitHub anything.
                    asked = calls.read_text(encoding="utf-8") if calls.exists() else ""
                    self.assertEqual(asked.startswith("api repos/owner/repo/commits/gh-pages --jq "),
                                     slot == "42 * * * *", asked)

    def test_one_runs_at_a_time_and_none_is_cancelled(self):
        self.assertIn("concurrency:\n  group: live-site\n  cancel-in-progress: false\n", self.live)

    def test_its_token_may_push_the_site_and_keep_the_schedule_and_no_checkout_keeps_it(self):
        block = re.search(r"\npermissions:\n((?:  .*\n)+)", self.live).group(1)
        self.assertEqual(sorted(re.findall(r"^  ([\w-]+): (\w+)", block, re.M)),
                         [("actions", "write"), ("contents", "write")])
        self.assertRegex(self.live, r"uses: actions/checkout@[0-9a-f]{40} # v7\.\d+\.\d+\n"
                                    r"        with:\n          persist-credentials: false\n")

    def test_the_state_is_the_tracker_s_own_and_leaves_the_archive_out(self):
        paths = "            data/elnino.db\n            data/raw/*.cache\n            data/raw/*.meta.json\n"
        self.assertEqual(self.live.count("          path: |\n" + paths), 2)
        self.assertEqual(self.live.count("key: tracker-state-${{ github.run_id }}-${{ github.run_attempt }}\n"), 2)
        self.assertIn("restore-keys: tracker-state-\n", self.live)
        self.assertRegex(self.live, r"if: \$\{\{ !cancelled\(\) \}\}\n"
                                    r"        uses: actions/cache/save@[0-9a-f]{40} # v6\.\d+\.\d+\n")

    def test_it_publishes_to_its_own_repository_over_https(self):
        self.assertIn("GH_TOKEN: ${{ github.token }}\n", self.live)
        self.assertIn("gh auth setup-git\n", self.live)
        self.assertIn('./publish.sh --remote "https://github.com/$GITHUB_REPOSITORY.git" || code=$?\n', self.live)

    def test_open_alerts_and_a_degraded_run_are_published_and_said(self):
        for line in ("0) ;;", '1) echo "::notice title=Alerts open::', '3) echo "::warning title=Degraded run::',
                     '*) exit "$code" ;;'):
            self.assertIn(line, self.live)

    def test_the_schedule_is_kept_from_pausing_without_failing_the_run(self):
        step = self.live.split("- name: Keep the schedule from pausing\n", 1)[1]
        self.assertIn("if: ${{ !cancelled() && github.event_name == 'schedule' }}\n", step)
        self.assertIn("continue-on-error: true\n", step)
        self.assertIn('gh api --method PUT "repos/$GITHUB_REPOSITORY/actions/workflows/live.yml/enable"', step)

    def test_the_suite_runs_on_the_python_the_hourly_run_uses(self):
        self.assertEqual(re.findall(r'python-version: "([\d.]+)"', self.live + self.tests), ["3.12", "3.12"])
        self.assertIn("run: python -m unittest discover -s tests -v\n", self.tests)
        self.assertIn("permissions:\n  contents: read\n", self.tests)
        self.assertIn("persist-credentials: false\n", self.tests)

    def test_the_suite_names_the_node_its_page_tests_run_under(self):
        # The page tests run each page's script under node and skip without it;
        # the runner's own node changes with its image, so the suite names one.
        self.assertRegex(self.tests, r'uses: actions/setup-node@[0-9a-f]{40} # v7\.\d+\.\d+\n'
                                     r'        with:\n          node-version: "24"\n')

    def test_every_action_is_pinned_to_a_commit_and_names_its_release(self):
        # A tag can be moved to other code; a commit cannot. The hourly run's
        # token may push to this repository.
        for name, text in (("live.yml", self.live), ("tests.yml", self.tests)):
            uses = re.findall(r"uses: (.*)", text)
            with self.subTest(name):
                self.assertTrue(uses)
                for use in uses:
                    self.assertRegex(use, r"^actions/[\w-]+(/[\w-]+)?@[0-9a-f]{40} # v\d+\.\d+\.\d+$")

    def test_a_run_is_given_half_an_hour_and_nothing_from_a_fork_starts_one(self):
        self.assertEqual(self.live.count("    timeout-minutes: 30\n"), 1)
        self.assertEqual(self.tests.count("    timeout-minutes: 30\n"), 1)
        # A pull request's code never runs with the live run's token.
        self.assertNotIn("pull_request", self.live)
