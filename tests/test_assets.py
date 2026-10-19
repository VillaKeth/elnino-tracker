"""Code and data that are the same from run to run, in files beside the pages
(elnino/assets.py): their names, how a page names them, and how a run writes
them and lets go of those no page names any more."""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from elnino import assets, atlas, atlasview, dashboard, live, stormdesk  # noqa: E402
from test_tracker import _DeskFixtures, _asset_value, _node_json  # noqa: E402

RUN = "2026-10-09T15:00:00+00:00"


class TestAnAsset(unittest.TestCase):
    """A file named by its contents, as a page names it."""

    def test_its_name_changes_with_its_text_and_only_with_it(self):
        first, again = assets.Asset("probe", "var x = 1;\n"), assets.Asset("probe", "var x = 1;\n")
        other = assets.Asset("probe", "var x = 2;\n")
        self.assertEqual(first.file, "probe." + hashlib.sha256(b"var x = 1;\n").hexdigest()[:10] + ".js")
        self.assertEqual(first.file, again.file)
        self.assertNotEqual(first.file, other.file)
        self.assertRegex(other.file, r"^probe\.[0-9a-f]{10}\.js$")

    def test_a_page_names_it_as_a_deferred_classic_script_beside_it(self):
        # Classic, so a page opened as a file loads it; deferred, so it runs
        # once the page is parsed, in the order the page names it; relative,
        # so the page finds it wherever the page is.
        one, two = assets.Asset("probe", "var x = 1;\n"), assets.Asset("other", "var y = 1;\n")
        self.assertEqual(one.tag(), f'<script defer src="assets/{one.file}"></script>')
        self.assertEqual(assets.tags((one, two)), one.tag() + "\n" + two.tag())
        self.assertEqual(assets.page_assets(f"<head>{assets.tags((one, two))}</head><body>"
                                            f'<script src="https://elsewhere/{one.file}"></script></body>'),
                         [one.file, two.file])

    def test_a_page_names_one_to_load_only_when_asked_as_a_link_no_browser_fetches(self):
        one, later, two = (assets.Asset("probe", "var x = 4;\n"), assets.Asset("later", "var z = 1;\n"),
                           assets.Asset("other", "var y = 4;\n"))
        self.assertEqual(later.lazy_tag(), f'<link rel="elnino-lazy" href="assets/{later.file}">')
        self.assertEqual(assets.lazy_tags((later, one)), later.lazy_tag() + "\n" + one.lazy_tag())
        self.assertEqual(assets.page_assets(f"<head>{one.tag()}\n{later.lazy_tag()}\n{two.tag()}</head>"),
                         [one.file, later.file, two.file])

    def test_a_name_is_one_plain_word(self):
        for bad in ("", "Probe", "two words", "../up", "probe.js", "1st"):
            with self.subTest(bad), self.assertRaises(ValueError):
                assets.Asset(bad, "var x = 1;\n")

    def test_data_set_a_property_of_the_one_global(self):
        probe = assets.data("probe", {"a": [1, 2], "name": "Bogotá</script>"})
        self.assertEqual(probe.name, "probe")
        self.assertEqual(probe.text, '(window.ELNINO = window.ELNINO || {}).probe = '
                                     '{"a":[1,2],"name":"Bogot\\u00e1</script>"};\n')
        self.assertEqual(_asset_value(probe), {"a": [1, 2], "name": "Bogotá</script>"})
        # Run as a page runs them, one after another.
        got = _node_json(self, "var window = globalThis;\n" + assets.data("other", 1).text + probe.text
                         + "console.log(JSON.stringify(window.ELNINO));\n")
        self.assertEqual(got, {"other": 1, "probe": {"a": [1, 2], "name": "Bogotá</script>"}})


class TestWritingAssets(unittest.TestCase):
    """A run writes the assets its pages name, and lets go of the rest."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.out = Path(tmp.name)

    def test_each_named_asset_is_written_beside_the_pages_byte_for_byte(self):
        probe = assets.Asset("probe", "var x = 1;\nvar y = 'ü';\n")
        paths = assets.write(self.out, [probe.file])
        self.assertEqual(paths, [self.out / "assets" / probe.file])
        # The bytes its name was taken from, with Unix line ends on any system.
        self.assertEqual(paths[0].read_bytes(), probe.text.encode("utf-8"))

    def test_one_already_written_is_left_as_it_is(self):
        probe = assets.Asset("probe", "var x = 3;\n")
        path, = assets.write(self.out, [probe.file])
        older = path.stat().st_mtime_ns - 5_000_000_000
        os.utime(path, ns=(older, older))
        assets.write(self.out, [probe.file, probe.file])
        self.assertEqual(path.stat().st_mtime_ns, older)

    def test_a_file_no_asset_was_made_for_is_refused(self):
        with self.assertRaisesRegex(KeyError, r"probe\.0123456789\.js"):
            assets.write(self.out, ["probe.0123456789.js"])

    def test_assets_no_page_names_are_let_go_and_other_files_kept(self):
        kept = assets.Asset("probe", "var kept = 1;\n")
        assets.write(self.out, [kept.file])
        folder = self.out / "assets"
        for name in ("probe.0123456789.js", "desk.abcdef0123.js", "notes.txt", "mine.js", "desk.abc.js"):
            (folder / name).write_text("x", encoding="utf-8")
        self.assertEqual(sorted(assets.prune(self.out, [kept.file])), ["desk.abcdef0123.js", "probe.0123456789.js"])
        self.assertEqual(sorted(p.name for p in folder.iterdir()),
                         sorted([kept.file, "desk.abc.js", "mine.js", "notes.txt"]))

    def test_one_loaded_only_when_asked_is_written_kept_and_published(self):
        import publish

        later = assets.data("later", {"storms": [1, 2]})
        html = f"<head>{later.lazy_tag()}</head>"
        named = assets.page_assets(html)
        self.assertEqual(assets.write(self.out, named), [self.out / "assets" / later.file])
        self.assertEqual(assets.prune(self.out, named), [])
        self.assertEqual(publish._read_assets(self.out, {"storms.html": html.encode("utf-8")}),
                         {later.file: later.text.encode("utf-8")})

    def test_with_no_folder_there_is_nothing_to_let_go(self):
        self.assertEqual(assets.prune(self.out, []), [])

    def test_the_service_worker_is_written_beside_the_pages_byte_for_byte(self):
        path = assets.write_worker(self.out)
        self.assertEqual(path, self.out / assets.WORKER)
        self.assertEqual(assets.WORKER, "sw.js")
        self.assertEqual(path.read_bytes(), assets.WORKER_JS.encode("utf-8"))
        older = path.stat().st_mtime_ns - 5_000_000_000
        os.utime(path, ns=(older, older))
        assets.write_worker(self.out)
        self.assertEqual(path.stat().st_mtime_ns, older)


class TestTheAssets(unittest.TestCase):
    """What goes out of the pages: the follower, each page's code, and the
    data that are the same from run to run."""

    BUILDERS = (assets.follower, assets.places, assets.grids, assets.coast, assets.desk,
                assets.atlasgeo, assets.relief, assets.atlas, assets.dashboard)

    def test_each_is_made_once_and_named_as_it_is_built(self):
        for build in self.BUILDERS:
            with self.subTest(build.__name__):
                self.assertIs(build(), build())
                self.assertEqual(build().name, build.__name__)
                self.assertIs(assets.made(build().file), build())

    def test_the_code_is_the_pages_code(self):
        self.assertEqual(assets.follower().text, live.SCRIPT)
        self.assertEqual(assets.desk().text, stormdesk.script())
        self.assertEqual(assets.atlas().text, atlasview._JS)
        self.assertEqual(assets.dashboard().text, dashboard._js())

    def test_the_data_are_what_the_pages_carried(self):
        self.assertEqual(_asset_value(assets.places()), atlasview._places_payload())
        self.assertEqual(_asset_value(assets.grids()), json.loads(json.dumps(atlasview._grid_payload())))
        self.assertEqual(_asset_value(assets.coast()), json.loads(json.dumps(stormdesk._coast())))
        self.assertEqual(_asset_value(assets.atlasgeo()), json.loads(json.dumps(atlasview._geo_payload())))
        self.assertEqual(sorted(_asset_value(assets.atlasgeo())), ["borders", "coast", "lakes", "rivers"])
        # The relief stays a data address inside its asset: the atlas reads its
        # pixels back, which a canvas allows for one and not for a file opened
        # from disk.
        self.assertTrue(_asset_value(assets.relief()).startswith("data:image/png;base64,"))


# A browser for the service worker: its scope, the Cache Storage it keeps
# files in, its clock, its timers, and the network, each request answered
# from ROUTES: text, as an asset is; an Error, or {error}, for no answer;
# {hang} for one that never comes until the request is called off;
# {after: true, status, headers, body} for one that comes only once the
# worker's timers have run, slower than any of them, and never once called off;
# {status, headers, body} as given; or 404 for anything else. The worker's
# own text runs with these as its self, caches, fetch, setTimeout and
# clearTimeout; Request, Response, URL, AbortController, TextDecoder and
# crypto are node's own, as a browser's.
WORKER = r"""
var HANDLERS = {}, FETCHED = [], ASKED = [], ROUTES = {}, OPENED = [], NOTES = [], TIMERS = [], AFTER = [];
var SITE = "https://villaketh.github.io/elnino-tracker/";
var NOW = Date.parse("2026-10-19T16:30:00Z");
Date.now = function () { return NOW; };
var SELF = {
  location: new URL(SITE + "sw.js"),
  addEventListener: function (type, f) { HANDLERS[type] = f; },
  skipWaiting: function () { NOTES.push("skipWaiting"); return Promise.resolve(); },
  clients: {claim: function () { NOTES.push("claim"); return Promise.resolve(); }}
};
function urlOf(r) { return typeof r === "string" ? r : r.url; }
function Store() { this.entries = []; }
Store.prototype.match = function (r) {
  var hit = this.entries.filter(function (e) { return e.url === urlOf(r); })[0];
  return Promise.resolve(hit ? hit.res.clone() : undefined);
};
Store.prototype.put = function (r, res) {
  var url = urlOf(r), store = this;
  return res.arrayBuffer().then(function (body) {
    store.entries = store.entries.filter(function (e) { return e.url !== url; });
    store.entries.push({url: url, res: new Response(body, {headers: res.headers})});
  });
};
Store.prototype.keys = function () {
  return Promise.resolve(this.entries.map(function (e) { return new Request(e.url); }));
};
Store.prototype.delete = function (r) {
  var n = this.entries.length;
  this.entries = this.entries.filter(function (e) { return e.url !== urlOf(r); });
  return Promise.resolve(this.entries.length < n);
};
// The assets' cache, and each other the worker opens, by its name.
var CACHE = new Store(), STORES = {"elnino-assets": CACHE};
var CACHES = {open: function (name) {
  OPENED.push(name);
  return Promise.resolve(STORES[name] = STORES[name] || new Store());
}};
function FETCH(r, init) {
  var url = urlOf(r), answer = ROUTES[url];
  init = init || {};
  FETCHED.push(url);
  ASKED.push({url: url, cache: init.cache || "default", credentials: init.credentials || "same-origin"});
  if (answer instanceof Error) return Promise.reject(answer);
  if (answer === undefined) return Promise.resolve(new Response("Not found", {status: 404}));
  if (typeof answer === "string") {
    return Promise.resolve(new Response(answer, {headers: {"Content-Type": "application/javascript; charset=utf-8"}}));
  }
  if (answer.error) return Promise.reject(new TypeError(answer.error));
  if (answer.hang || answer.after) {
    return new Promise(function (resolve, reject) {
      if (init.signal) init.signal.addEventListener("abort", function () { reject(new Error("aborted")); });
      if (answer.after) {
        AFTER.push(function () {
          resolve(new Response(answer.body, {status: answer.status || 200, headers: answer.headers || {}}));
        });
      }
    });
  }
  return Promise.resolve(new Response(answer.body, {status: answer.status || 200, headers: answer.headers || {}}));
}
// The worker's timers: each noted, and run when what the worker answers
// waits on them, as the time they were set for passes; then the answers
// slower than any of them come.
var TIMER = {
  set: function (fn, ms) { TIMERS.push({fn: fn, ms: ms, done: false}); return TIMERS.length; },
  clear: function (id) { if (TIMERS[id - 1]) TIMERS[id - 1].done = true; }
};
function fire() {
  TIMERS.forEach(function (t) { if (!t.done) { t.done = true; t.fn(); } });
  AFTER.splice(0).forEach(function (come) { come(); });
}
(function (self, caches, fetch, setTimeout, clearTimeout) {
/*WORKER*/
})(SELF, CACHES, FETCH, TIMER.set, TIMER.clear);
function settle(p) {
  var done = false, failed = false, value;
  p.then(function (v) { done = true; value = v; }, function (e) { done = true; failed = true; value = e; });
  return (async function () {
    for (var i = 0; i < 100 && !done; i++) {
      await new Promise(function (r) { setImmediate(r); });
      if (!done) fire();
    }
    if (!done) throw new Error("the worker never answered");
    if (failed) throw value;
    return value;
  })();
}
// A request a page makes: the worker's answer, or null where it leaves the
// request to the browser.
function ask(url, method) {
  var answered = null;
  HANDLERS.fetch({request: new Request(url, {method: method || "GET"}),
                  respondWith: function (p) { answered = Promise.resolve(p); }});
  if (!answered) return Promise.resolve(null);
  return settle(answered.then(function (r) {
    return r.text().then(function (t) { return {status: r.status, type: r.headers.get("Content-Type"), text: t}; });
  }));
}
// A page telling the worker what it names.
function tell(data) {
  var waits = [];
  HANDLERS.message({data: data, waitUntil: function (p) { waits.push(p); }});
  return settle(Promise.all(waits));
}
function kept() { return CACHE.entries.map(function (e) { return e.url; }); }
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheServiceWorker(unittest.TestCase):
    """sw.js: GitHub Pages sends every file again after each publish, with a
    new date and tag, and a browser would fetch each asset again ten minutes
    on; the worker keeps the assets, named for their contents, once fetched."""

    SITE = "https://villaketh.github.io/elnino-tracker/"

    def named(self, name: str, text: str) -> str:
        return f"{self.SITE}assets/{name}.{hashlib.sha256(text.encode('utf-8')).hexdigest()[:10]}.js"

    def run_worker(self, body: str, site: str | None = None, **routes):
        """What ``body`` prints, run with the worker at ``site`` (the tracker's
        by default) and the network answering from ``routes``."""
        harness = WORKER.replace("/*WORKER*/", assets.WORKER_JS)
        if site is not None:
            mine = f"var SITE = {json.dumps(self.SITE)};"
            self.assertEqual(harness.count(mine), 1)
            harness = harness.replace(mine, f"var SITE = {json.dumps(site)};")
        script = (harness + "ROUTES = " + json.dumps(routes) + ";\n(async function () {\n" + body
                  + "\n})().catch(function (e) { console.error(e && e.stack || e); process.exit(1); });\n")
        return _node_json(self, script.replace("$COPY", self.COPY))

    def test_an_asset_is_fetched_once_and_then_served_from_the_worker_s_cache(self):
        a = self.named("desk", "var desk = 1;\n")
        got = self.run_worker("""
var first = await ask(A), second = await ask(A);
console.log(JSON.stringify([first, second, FETCHED, kept(), OPENED[0]]));""".replace("A", json.dumps(a)),
                              **{a: "var desk = 1;\n"})
        answer = {"status": 200, "type": "application/javascript; charset=utf-8", "text": "var desk = 1;\n"}
        self.assertEqual(got, [answer, answer, [a], [a], "elnino-assets"])

    def test_all_but_the_assets_and_a_run_s_files_is_left_to_the_browser(self):
        a = self.named("desk", "var desk = 1;\n")
        others = [self.SITE + "sw.js", self.SITE + "favicon.ico", self.SITE + "data/run.json",
                  self.SITE + "storms/index.html", self.SITE + "dashboard.htm",
                  "https://villaketh.github.io/other/run.json", "https://example.org/elnino-tracker/run.json",
                  self.SITE + "assets/mine.js", self.SITE + "assets/desk.0123456789.css",
                  self.SITE + "assets/Desk.0123456789.js", a + "?v=2",
                  "https://villaketh.github.io/other/assets/desk.0123456789.js",
                  "https://example.org/elnino-tracker/assets/desk.0123456789.js"]
        got = self.run_worker("""
var got = [];
for (var url of OTHERS) got.push(await ask(url));
got.push(await ask(A, "POST"));
got.push(await ask(SITE + "run.json", "POST"));
console.log(JSON.stringify([got, FETCHED, kept()]));""".replace("OTHERS", json.dumps(others))
                              .replace("A,", json.dumps(a) + ","))
        self.assertEqual(got, [[None] * (len(others) + 2), [], []])

    def test_a_file_that_is_not_the_one_its_name_was_taken_from_is_served_and_not_kept(self):
        # A portal's page, or a file cut off: kept, it would stand for good.
        a = self.named("desk", "var desk = 1;\n")
        got = self.run_worker("""
var first = await ask(A), second = await ask(A);
console.log(JSON.stringify([first.text, second.text, FETCHED.length, kept()]));""".replace("A", json.dumps(a)),
                              **{a: "<html>Sign in to the network</html>"})
        self.assertEqual(got, ["<html>Sign in to the network</html>"] * 2 + [2, []])

    def test_a_failed_answer_is_passed_on_and_not_kept(self):
        a, b = self.named("desk", "var desk = 1;\n"), self.named("atlas", "var atlas = 1;\n")
        got = self.run_worker("""
var missing = await ask(A);
ROUTES[B] = new Error("offline");
var offline = await ask(B).then(function () { return "answered"; }, function () { return "failed"; });
console.log(JSON.stringify([missing.status, offline, FETCHED, kept()]));""".replace("A", json.dumps(a))
                              .replace("B", json.dumps(b)))
        # Asked once each, and then the copy, which has neither: no answer
        # is no answer, as without the worker.
        self.assertEqual(got, [404, "failed", [a, self.copied(a), b, self.copied(b)], []])

    def test_a_cache_that_refuses_to_keep_still_has_every_asset_answered(self):
        # Chrome's Cache Storage can refuse every put ("Entry already exists",
        # seen with a profile deeper than Windows' path limit): each asset is
        # then answered from the network, asked by a page or named by one.
        a = self.named("desk", "var desk = 1;\n")
        got = self.run_worker("""
CACHE.put = function () { return Promise.reject(new Error("Entry already exists.")); };
var first = await ask(DESK), second = await ask(DESK);
await tell({keep: [DESK]});
console.log(JSON.stringify([first.text, second.text, FETCHED.length, kept()]));""".replace("DESK", json.dumps(a)),
                              **{a: "var desk = 1;\n"})
        self.assertEqual(got, ["var desk = 1;\n"] * 2 + [3, []])

    def test_a_page_tells_it_the_assets_it_names_and_they_are_kept_from_a_first_visit(self):
        a, b = self.named("desk", "var desk = 1;\n"), self.named("follower", "var follower = 1;\n")
        # Kept in the order their digests come back, which on a busy machine
        # is the thread pool's: the two were once kept follower first.
        got = self.run_worker("""
await tell({keep: [A, B, "https://example.org/x.js", 5, SITE + "dashboard.html"]});
var first = [kept().sort(), FETCHED.slice()];
await tell({keep: [A, B]});
await tell({});
await tell("nonsense");
var served = await ask(A);
console.log(JSON.stringify([first, FETCHED, served.text]));""".replace("A", json.dumps(a)).replace("B", json.dumps(b)),
                              **{a: "var desk = 1;\n", b: "var follower = 1;\n"})
        self.assertEqual(got, [[[a, b], [a, b]], [a, b], "var desk = 1;\n"])

    def test_the_two_latest_files_of_each_name_are_kept(self):
        # A page cached from before a publish still names the last ones.
        texts = ["var desk = 1;\n", "var follower = 1;\n", "var desk = 2;\n", "var desk = 3;\n"]
        urls = [self.named(t.split()[1], t) for t in texts]
        got = self.run_worker("""
for (var url of URLS) await ask(url);
console.log(JSON.stringify(kept()));""".replace("URLS", json.dumps(urls)), **dict(zip(urls, texts)))
        self.assertEqual(got, [urls[1], urls[2], urls[3]])

    # ---- while Pages lags behind its branch -----------------------------------
    # GitHub's incident of 19 October 2026 held Pages' deploys back from 15:22
    # to 16:37 while every run reached gh-pages, whose raw copy kept up.
    COPY = "https://raw.githubusercontent.com/villaketh/elnino-tracker/gh-pages/"
    ANSWERED = datetime(2026, 10, 19, 16, 30, tzinfo=timezone.utc)
    SHOWN, LATER = "2026-10-19T15:21:03+00:00", "2026-10-19T16:21:03+00:00"
    HTML, JSON = "text/html; charset=utf-8", "application/json; charset=utf-8"

    def copied(self, url: str) -> str:
        """The copy's address for a file beside the pages."""
        return self.COPY + url[len(self.SITE):]

    def pages(self, body: str, age: float = 5, status: int = 200, type: str = HTML) -> dict:
        """Pages' answer: a file deployed ``age`` minutes before Pages answered."""
        return {"status": status, "body": body, "headers": {
            "Content-Type": type, "Date": format_datetime(self.ANSWERED, usegmt=True),
            "Last-Modified": format_datetime(self.ANSWERED - timedelta(minutes=age), usegmt=True)}}

    def beacon(self, run: str, age: float = 5) -> dict:
        return self.pages(json.dumps({"run_at": run}), age, type=self.JSON)

    def raw(self, body: str, status: int = 200) -> dict:
        """The copy's answer, as raw.githubusercontent.com gives every file."""
        return {"status": status, "body": body, "headers": {
            "Content-Type": "text/plain; charset=utf-8", "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; sandbox"}}

    def lagging(self, copy_run: str | None = None, **routes) -> dict:
        """Pages 75 minutes behind, on the run of 15:21; the copy on 16:21's."""
        site = {"run.json": self.beacon(self.SHOWN, 75), "": self.pages("<p>index 15:21</p>", 75),
                "dashboard.html": self.pages("<p>15:21</p>", 75),
                "dashboard.html?from=desk": self.pages("<p>15:21</p>", 75)}
        copy = {"run.json": self.raw(json.dumps({"run_at": copy_run or self.LATER})),
                "index.html": self.raw("<p>index 16:21</p>"), "dashboard.html": self.raw("<p>16:21</p>")}
        return {**{self.SITE + k: v for k, v in site.items()}, **{self.COPY + k: v for k, v in copy.items()},
                **routes}

    def texts(self, *urls, **routes):
        """What each address is answered with, in turn, and every address asked."""
        return self.run_worker("""
var got = [];
for (var url of URLS) {
  got.push(await ask(url).then(function (r) { return r && [r.status, r.type, r.text]; },
                               function (e) { return "failed: " + e.message; }));
}
console.log(JSON.stringify([got, FETCHED]));""".replace("URLS", json.dumps(urls)), **routes)

    def test_a_run_s_files_come_from_pages_while_pages_keeps_up(self):
        # Deployed 11 minutes before, or with no dates at all: Pages keeps up,
        # and the copy is not asked.
        storms = {"status": 200, "body": "{}", "headers": {"Content-Type": self.JSON}}
        routes = {self.SITE + "run.json": self.beacon(self.LATER, 11), self.SITE: self.pages("<p>index</p>", 11),
                  self.SITE + "dashboard.html": self.pages("<p>16:21</p>", 12), self.SITE + "storms.json": storms}
        got, asked = self.texts(*routes, **routes)
        self.assertEqual(got, [[200, self.JSON, json.dumps({"run_at": self.LATER})], [200, self.HTML, "<p>index</p>"],
                               [200, self.HTML, "<p>16:21</p>"], [200, self.JSON, "{}"]])
        self.assertEqual(asked, list(routes))

    def test_while_pages_lags_behind_a_later_run_the_copy_answers_for_the_run_s_files(self):
        got, asked = self.texts(self.SITE + "run.json", self.SITE, self.SITE + "dashboard.html?from=desk",
                                **self.lagging())
        # As the pages and their data, not as raw's text, which a browser
        # would not run.
        self.assertEqual(got, [[200, self.JSON, json.dumps({"run_at": self.LATER})],
                               [200, self.HTML, "<p>index 16:21</p>"], [200, self.HTML, "<p>16:21</p>"]])
        # The copy's beacon once, and each page; Pages' beacon for each page.
        self.assertEqual(asked, [self.SITE + "run.json", self.COPY + "run.json",
                                 self.SITE, self.SITE + "run.json", self.COPY + "index.html",
                                 self.SITE + "dashboard.html?from=desk", self.SITE + "run.json",
                                 self.COPY + "dashboard.html"])

    def test_the_copy_is_asked_afresh_with_no_cookies(self):
        got = self.run_worker("""
await ask(SITE + "dashboard.html");
console.log(JSON.stringify(ASKED.filter(function (a) { return a.url.indexOf("$COPY") === 0; })));""",
                              **self.lagging())
        self.assertEqual(got, [{"url": self.COPY + name, "cache": "no-store", "credentials": "omit"}
                               for name in ("run.json", "dashboard.html")])

    def test_pages_lags_when_its_file_was_deployed_more_than_twelve_minutes_before(self):
        for age, served in ((12, "<p>15:21</p>"), (12.02, "<p>16:21</p>")):
            with self.subTest(age=age):
                got, _ = self.texts(self.SITE + "dashboard.html",
                                    **self.lagging(**{self.SITE + "dashboard.html": self.pages("<p>15:21</p>", age)}))
                self.assertEqual(got[0][2], served)

    def test_while_pages_lags_with_no_later_run_in_the_copy_pages_answers(self):
        got, asked = self.texts(self.SITE + "run.json", self.SITE + "dashboard.html",
                                **self.lagging(copy_run=self.SHOWN))
        self.assertEqual([g[2] for g in got], [json.dumps({"run_at": self.SHOWN}), "<p>15:21</p>"])
        self.assertEqual(asked, [self.SITE + "run.json", self.COPY + "run.json",
                                 self.SITE + "dashboard.html", self.SITE + "run.json"])

    def test_a_copy_that_cannot_say_its_run_leaves_pages_answers_as_they_were(self):
        # Its beacon missing, refused (raw limits those who ask too often),
        # not a beacon, naming no run, or too slow, which is 5 seconds.
        for case, beacon in (("missing", self.raw("404: Not Found", 404)), ("refused", self.raw("", 429)),
                             ("not a beacon", self.raw("<html>Sign in</html>")),
                             ("no run", self.raw(json.dumps({"run_at": None}))), ("slow", {"hang": True})):
            with self.subTest(case):
                got = self.run_worker("""
var got = [await ask(SITE + "run.json"), await ask(SITE + "dashboard.html")];
console.log(JSON.stringify([got.map(function (g) { return g.text; }), TIMERS.map(function (t) { return t.ms; })]));""",
                                      **self.lagging(**{self.COPY + "run.json": beacon}))
                self.assertEqual(got, [[json.dumps({"run_at": self.SHOWN}), "<p>15:21</p>"], [5000]])

    def test_a_later_run_s_page_the_copy_cannot_give_leaves_pages_page(self):
        # Missing, or too slow, which is 20 seconds: the beacon still names
        # the later run, which the page then goes for again after a pause.
        for case, page in (("missing", self.raw("404: Not Found", 404)), ("slow", {"hang": True})):
            with self.subTest(case):
                got = self.run_worker("""
var got = [await ask(SITE + "run.json"), await ask(SITE + "dashboard.html")];
console.log(JSON.stringify([got.map(function (g) { return g.text; }), TIMERS.map(function (t) { return t.ms; })]));""",
                                      **self.lagging(**{self.COPY + "dashboard.html": page}))
                self.assertEqual(got, [[json.dumps({"run_at": self.LATER}), "<p>15:21</p>"], [5000, 20000]])

    def test_pages_failing_or_without_the_file_the_copy_answers(self):
        got, _ = self.texts(self.SITE + "run.json", self.SITE + "dashboard.html", self.SITE + "atlas.html",
                            **self.lagging(**{
                                self.SITE + "run.json": {"error": "Failed to fetch"},
                                self.SITE + "dashboard.html": self.pages("Service Unavailable", status=503),
                                # A page the deploy Pages serves has not got.
                                self.SITE + "atlas.html": self.pages("Not Found", status=404),
                                self.COPY + "atlas.html": self.raw("<p>atlas 16:21</p>")}))
        self.assertEqual(got, [[200, self.JSON, json.dumps({"run_at": self.LATER})],
                               [200, self.HTML, "<p>16:21</p>"], [200, self.HTML, "<p>atlas 16:21</p>"]])

    def test_pages_and_the_copy_failing_is_pages_failure(self):
        got, _ = self.texts(self.SITE + "run.json", self.SITE + "dashboard.html",
                            **self.lagging(**{self.SITE + "run.json": {"error": "Failed to fetch"},
                                              self.SITE + "dashboard.html": self.pages("Busy", status=503),
                                              self.COPY + "run.json": {"error": "Failed to fetch"}}))
        self.assertEqual(got, ["failed: Failed to fetch", [503, self.HTML, "Busy"]])

    def test_the_copy_s_beacon_is_asked_at_most_every_two_minutes(self):
        # What it said, or that it said nothing, stands two minutes, unless
        # the clock is put back.
        got = self.run_worker("""
function copies() { return FETCHED.filter(function (u) { return u === "$COPY" + "run.json"; }).length; }
var seen = [];
async function poll(ms) { NOW += ms; await ask(SITE + "run.json"); seen.push(copies()); }
await poll(0);
await poll(119999);
await poll(1);
await poll(-600000);
ROUTES["$COPY" + "run.json"] = {error: "Failed to fetch"};
await poll(120000);
await poll(60000);
console.log(JSON.stringify(seen));""", **self.lagging())
        self.assertEqual(got, [1, 1, 2, 3, 4, 4])

    def test_the_copy_s_beacon_is_asked_once_for_all_who_want_it_at_once(self):
        # A page loaded while Pages lags asks for itself and the beacon at once.
        got = self.run_worker("""
var got = await Promise.all([ask(SITE + "run.json"), ask(SITE), ask(SITE + "dashboard.html")]);
console.log(JSON.stringify([got.map(function (g) { return g.text; }),
                            FETCHED.filter(function (u) { return u === "$COPY" + "run.json"; }).length]));""",
                              **self.lagging())
        self.assertEqual(got, [[json.dumps({"run_at": self.LATER}), "<p>index 16:21</p>", "<p>16:21</p>"], 1])

    def test_an_asset_pages_cannot_give_comes_from_the_copy_when_its_bytes_are_its_name_s(self):
        # A page from the copy names the assets of its run, which the deploy
        # Pages serves may not have.
        desk, atlas = self.named("desk", "var desk = 2;\n"), self.named("atlas", "var atlas = 2;\n")
        got = self.run_worker("""
var first = await ask(DESK), again = await ask(DESK);
var atlas = await ask(ATLAS).then(function (r) { return r.status; }, function () { return "failed"; });
console.log(JSON.stringify([first, again, atlas, kept(), FETCHED]));""".replace("DESK", json.dumps(desk))
                              .replace("ATLAS", json.dumps(atlas)),
                              **{self.copied(desk): self.raw("var desk = 2;\n"), atlas: {"error": "Failed to fetch"},
                                 self.copied(atlas): self.raw("<html>Sign in to the network</html>")})
        answer = {"status": 200, "type": "text/javascript; charset=utf-8", "text": "var desk = 2;\n"}
        self.assertEqual(got, [answer, answer, "failed", [desk], [desk, self.copied(desk), atlas, self.copied(atlas)]])

    def test_an_asset_the_copy_gives_slowly_is_waited_for(self):
        # Nothing else can give it: the copy has as long as Pages would.
        desk = self.named("desk", "var desk = 2;\n")
        got = self.run_worker("""
var first = await ask(DESK);
console.log(JSON.stringify([first, kept(), TIMERS.length]));""".replace("DESK", json.dumps(desk)),
                              **{self.copied(desk): {**self.raw("var desk = 2;\n"), "after": True}})
        answer = {"status": 200, "type": "text/javascript; charset=utf-8", "text": "var desk = 2;\n"}
        self.assertEqual(got, [answer, [desk], 0])

    def test_off_github_pages_there_is_no_copy_and_pages_answers_alone(self):
        for site in ("http://localhost:8731/", "https://example.org/elnino-tracker/", "https://villaketh.github.io/"):
            with self.subTest(site=site):
                a = site + "assets/desk." + hashlib.sha256(b"var desk = 1;\n").hexdigest()[:10] + ".js"
                got = self.run_worker("""
var got = [await ask(SITE + "run.json"), await ask(SITE), await ask(SITE + "dashboard.html"), (await ask(A)).status];
console.log(JSON.stringify([got, FETCHED]));""".replace("A)", json.dumps(a) + ")"), site=site)
                self.assertEqual(got, [[None, None, None, 404], [a]])

    def test_it_takes_the_pages_over_at_once(self):
        got = self.run_worker("""
var waits = [];
HANDLERS.install({waitUntil: function (p) { waits.push(p); }});
HANDLERS.activate({waitUntil: function (p) { waits.push(p); }});
await Promise.all(waits);
console.log(JSON.stringify(NOTES));""")
        self.assertEqual(got, ["skipWaiting", "claim"])


class TestPagesNameTheirAssets(_DeskFixtures, unittest.TestCase):
    """Each page names its assets in its head, in the order they run: the
    data, the follower, then its own code; nothing they carry is left in it."""

    def desk_data(self, html: str) -> dict:
        return json.loads(re.search(r'<script id="desk-data" type="application/json">(.*?)</script>',
                                    html, re.S).group(1))

    def test_the_desk_and_the_map_name_the_shared_data_the_follower_and_their_engine(self):
        named = (assets.places(), assets.grids(), assets.coast(), assets.follower(), assets.desk())
        for focus in ("storms", "world"):
            with self.subTest(focus):
                html = stormdesk.page(self.state(self.polo()), focus=focus)
                self.assertEqual(assets.page_assets(html), [a.file for a in named])
                self.assertIn(assets.tags(named) + "\n</head>", html)
                self.assertNotIn(live.SCRIPT, html)
                self.assertNotIn(stormdesk.script(), html)
                data = self.desk_data(html)
                self.assertNotIn("places", data)
                self.assertNotIn("coast", data)
                self.assertNotIn("grids", data["enso"])
                self.assertEqual((data["enso"]["now"], data["focus"]), ("SON", focus))

    def test_the_desk_reads_the_shared_data_where_the_run_s_own_had_them(self):
        js = stormdesk.script()
        self.assertIn('  var D = withAssets(JSON.parse(document.getElementById("desk-data").textContent));\n', js)
        self.assertIn("    d.places = ELNINO.places; d.coast = ELNINO.coast; d.enso.grids = ELNINO.grids;\n", js)

    def test_the_atlas_names_the_shared_data_its_own_the_follower_and_its_engine(self):
        html = atlasview.page(SimpleNamespace(
            atlas=atlas.evaluate(), cyclones=SimpleNamespace(storms=(), available=False),
            generated=date(2026, 9, 23), run_at=RUN))
        named = (assets.places(), assets.grids(), assets.atlasgeo(), assets.relief(), assets.follower(),
                 assets.atlas())
        self.assertEqual(assets.page_assets(html), [a.file for a in named])
        self.assertIn(assets.tags(named) + "\n</head>", html)
        self.assertNotIn("var RELIEF", html)
        self.assertNotIn(atlasview._JS, html)
        data = json.loads(re.search(r"<script>var ATLAS=(.*?);</script>", html, re.S).group(1).replace("<\\/", "</"))
        for key in ("grids", "places", "coast", "borders", "rivers", "lakes"):
            self.assertNotIn(key, data)
        self.assertEqual(data["storms"], [])
        self.assertEqual(data["wide"], atlasview.WIDE)
        self.assertIn("  var D = ATLAS;\n  D.grids = ELNINO.grids; D.places = ELNINO.places;\n", atlasview._JS)
        self.assertIn("  var RELIEF = ELNINO.relief;\n", atlasview._JS)


if __name__ == "__main__":
    unittest.main()
