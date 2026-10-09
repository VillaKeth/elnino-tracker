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
from datetime import date
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
# assets in, and the network, each request answered from ROUTES (text, an
# Error for no answer, or 404 for anything else). The worker's own text runs
# with these as its self, caches and fetch; Request, Response, URL and
# crypto are node's own, as a browser's.
WORKER = r"""
var HANDLERS = {}, FETCHED = [], STORE = [], ROUTES = {}, OPENED = [], NOTES = [];
var SITE = "https://villaketh.github.io/elnino-tracker/";
var SELF = {
  location: new URL(SITE + "sw.js"),
  addEventListener: function (type, f) { HANDLERS[type] = f; },
  skipWaiting: function () { NOTES.push("skipWaiting"); return Promise.resolve(); },
  clients: {claim: function () { NOTES.push("claim"); return Promise.resolve(); }}
};
function urlOf(r) { return typeof r === "string" ? r : r.url; }
var CACHE = {
  match: function (r) {
    var hit = STORE.filter(function (e) { return e.url === urlOf(r); })[0];
    return Promise.resolve(hit ? hit.res.clone() : undefined);
  },
  put: function (r, res) {
    var url = urlOf(r);
    return res.arrayBuffer().then(function (body) {
      STORE = STORE.filter(function (e) { return e.url !== url; });
      STORE.push({url: url, res: new Response(body, {headers: res.headers})});
    });
  },
  keys: function () { return Promise.resolve(STORE.map(function (e) { return new Request(e.url); })); },
  delete: function (r) {
    var n = STORE.length;
    STORE = STORE.filter(function (e) { return e.url !== urlOf(r); });
    return Promise.resolve(STORE.length < n);
  }
};
var CACHES = {open: function (name) { OPENED.push(name); return Promise.resolve(CACHE); }};
function FETCH(r) {
  var url = urlOf(r), answer = ROUTES[url];
  FETCHED.push(url);
  if (answer instanceof Error) return Promise.reject(answer);
  if (answer === undefined) return Promise.resolve(new Response("Not found", {status: 404}));
  return Promise.resolve(new Response(answer, {headers: {"Content-Type": "application/javascript; charset=utf-8"}}));
}
(function (self, caches, fetch) {
/*WORKER*/
})(SELF, CACHES, FETCH);
// A request a page makes: the worker's answer, or null where it leaves the
// request to the browser.
function ask(url, method) {
  var answered = null;
  HANDLERS.fetch({request: new Request(url, {method: method || "GET"}),
                  respondWith: function (p) { answered = Promise.resolve(p); }});
  if (!answered) return Promise.resolve(null);
  return answered.then(function (r) {
    return r.text().then(function (t) { return {status: r.status, type: r.headers.get("Content-Type"), text: t}; });
  });
}
// A page telling the worker what it names.
function tell(data) {
  var waits = [];
  HANDLERS.message({data: data, waitUntil: function (p) { waits.push(p); }});
  return Promise.all(waits);
}
function kept() { return STORE.map(function (e) { return e.url; }); }
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestTheServiceWorker(unittest.TestCase):
    """sw.js: GitHub Pages sends every file again after each publish, with a
    new date and tag, and a browser would fetch each asset again ten minutes
    on; the worker keeps the assets, named for their contents, once fetched."""

    SITE = "https://villaketh.github.io/elnino-tracker/"

    def named(self, name: str, text: str) -> str:
        return f"{self.SITE}assets/{name}.{hashlib.sha256(text.encode('utf-8')).hexdigest()[:10]}.js"

    def run_worker(self, body: str, **routes):
        script = (WORKER.replace("/*WORKER*/", assets.WORKER_JS)
                  + "ROUTES = " + json.dumps(routes) + ";\n(async function () {\n" + body
                  + "\n})().catch(function (e) { console.error(e && e.stack || e); process.exit(1); });\n")
        return _node_json(self, script)

    def test_an_asset_is_fetched_once_and_then_served_from_the_worker_s_cache(self):
        a = self.named("desk", "var desk = 1;\n")
        got = self.run_worker("""
var first = await ask(A), second = await ask(A);
console.log(JSON.stringify([first, second, FETCHED, kept(), OPENED[0]]));""".replace("A", json.dumps(a)),
                              **{a: "var desk = 1;\n"})
        answer = {"status": 200, "type": "application/javascript; charset=utf-8", "text": "var desk = 1;\n"}
        self.assertEqual(got, [answer, answer, [a], [a], "elnino-assets"])

    def test_pages_data_and_everything_else_are_left_to_the_browser(self):
        a = self.named("desk", "var desk = 1;\n")
        others = [self.SITE, self.SITE + "dashboard.html", self.SITE + "run.json", self.SITE + "sw.js",
                  self.SITE + "assets/mine.js", self.SITE + "assets/desk.0123456789.css",
                  self.SITE + "assets/Desk.0123456789.js", a + "?v=2",
                  "https://villaketh.github.io/other/assets/desk.0123456789.js",
                  "https://example.org/elnino-tracker/assets/desk.0123456789.js"]
        got = self.run_worker("""
var got = [];
for (var url of OTHERS) got.push(await ask(url));
got.push(await ask(A, "POST"));
console.log(JSON.stringify([got, FETCHED, kept()]));""".replace("OTHERS", json.dumps(others))
                              .replace("A,", json.dumps(a) + ","))
        self.assertEqual(got, [[None] * (len(others) + 1), [], []])

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
        # Asked once each: no answer is no answer, as without the worker.
        self.assertEqual(got, [404, "failed", [a, b], []])

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
        got = self.run_worker("""
await tell({keep: [A, B, "https://example.org/x.js", 5, SITE + "dashboard.html"]});
var first = [kept(), FETCHED.slice()];
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
