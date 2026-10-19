"""Code and data that are the same from run to run, in files beside the pages.

Every page carried all of its code and data inline, and every run rewrote
every page, so a reader's browser fetched the gazetteer, the composite grids
and the scripts again after each run, for each page. Those parts go instead
in files named by their contents, ``assets/<name>.<sha256[:10]>.js``, which a
page names in its head as deferred classic scripts. A file's name changes only
when its text does, so a browser keeps each one across runs and across the
pages that share it; classic scripts load from a page opened as a file as
well as from one served. One that a page needs only when a reader asks for
it, the street's storm tracks, it names instead with a link no browser
fetches (``Asset.lazy_tag``), and its own code loads it then.

The data set properties of one global, ``ELNINO``; the code is the follower
(elnino/live.py) and each page's own. A run writes the assets its pages name
before the pages (``write``) and lets go of those no page names any more
before it names itself in the beacon (``prune``); publish.py puts them up
beside the pages.

GitHub Pages sends every file again after each publish, with a new date and
tag, so a browser would fetch each asset again ten minutes after it last did.
A service worker beside the pages (``WORKER``, written by ``write_worker``)
keeps them instead: a file named for its contents is that file for good. It
also answers for a run's pages and data from GitHub's raw copy of the site's
branch while Pages lags behind it, so an open page goes on following the runs.
"""

from __future__ import annotations

import functools
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path

# The folder beside the pages, as the pages name it.
FOLDER = "assets"
_NAME = re.compile(r"[a-z][a-z0-9]*")
_FILE = re.compile(r"[a-z][a-z0-9]*\.[0-9a-f]{10}\.js")
_TAG = re.compile(r'<script defer src="assets/([a-z][a-z0-9]*\.[0-9a-f]{10}\.js)"></script>'
                  r'|<link rel="elnino-lazy" href="assets/([a-z][a-z0-9]*\.[0-9a-f]{10}\.js)">')
# Every asset this process has made, by file: what a run writes is the text
# its pages were written against, never a file read back from anywhere.
_MADE: dict[str, Asset] = {}


@dataclass(frozen=True)
class Asset:
    """One script beside the pages: a plain word for its name, and its text."""

    name: str
    text: str

    def __post_init__(self):
        if not _NAME.fullmatch(self.name):
            raise ValueError(f"an asset's name is one plain word in lower case, not {self.name!r}")
        _MADE.setdefault(self.file, self)

    @functools.cached_property
    def file(self) -> str:
        """Its file: its name and the start of the SHA-256 of its text."""
        return f"{self.name}.{hashlib.sha256(self.text.encode('utf-8')).hexdigest()[:10]}.js"

    def tag(self) -> str:
        """How a page names it. Deferred, so it runs once the page is read, in
        the order the page names it; classic, so a page opened as a file loads
        it; relative, so it is found beside the page wherever that is."""
        return f'<script defer src="{FOLDER}/{self.file}"></script>'

    def lazy_tag(self) -> str:
        """How a page names it to load only when its own code asks: a link of
        a relation no browser knows, which no browser fetches, where the
        page's code finds it to load it as a classic script when wanted."""
        return f'<link rel="elnino-lazy" href="{FOLDER}/{self.file}">'


def tags(items) -> str:
    """The tags naming these assets, in their order, one a line."""
    return "\n".join(item.tag() for item in items)


def lazy_tags(items) -> str:
    """The links naming these assets to load when asked, in their order, one a line."""
    return "\n".join(item.lazy_tag() for item in items)


def page_assets(html: str) -> list[str]:
    """The asset files a page names, in the order it names them: those it
    runs and those it loads only when asked."""
    return [run or later for run, later in _TAG.findall(html)]


def made(file: str) -> Asset:
    """The asset made for this file. Raises KeyError for a file no asset of
    this process's was made for."""
    try:
        return _MADE[file]
    except KeyError:
        raise KeyError(f"no asset was made for {file}") from None


def whole(file: str, data: bytes) -> bool:
    """Whether data are the bytes the asset file's name was taken from."""
    return (_FILE.fullmatch(file) is not None
            and hashlib.sha256(data).hexdigest()[:10] == file.split(".")[1])


# The site's service worker, beside the pages so its scope is theirs. A GET of
# assets/<name>.<sha256[:10]>.js under its own folder comes from its cache, or
# from the network and is kept there when its bytes are the ones its name was
# taken from; the two latest files of each name are kept, as a page cached
# from before a publish still names the last ones. A page tells it the assets
# it names (live.py), so they are kept from a first visit on.
#
# A run's pages and data, the files beside it, come from Pages as ever unless
# Pages lags behind the branch it deploys: in GitHub's incident of 19 October
# 2026 its deploys stalled while every run reached gh-pages, and the site
# served the run of 15:22 until 16:37. When Pages answers with a file deployed
# more than 12 minutes before, fails, or has not got the file, and the beacon
# of the branch's raw copy names a later run than Pages' beacon does, the
# worker answers with the copy's file; the copy's beacon is asked at most
# every two minutes. An asset Pages cannot give comes from the copy, when its
# bytes are the ones its name was taken from. Everything else goes to the
# network as ever, and so does everything on a site served anywhere but
# GitHub Pages.
WORKER = "sw.js"
WORKER_JS = r"""// The El Nino tracker's service worker (elnino/assets.py). It keeps the
// assets the pages name, which are named for their contents; and while GitHub
// Pages lags behind the branch it deploys the site from, it answers for a
// run's pages and data from GitHub's raw copy of that branch.
"use strict";
var CACHE = "elnino-assets", KEEP = 2;
var HOME = new URL("assets/", self.location.href).href, NAMED = /^([a-z][a-z0-9]*)\.([0-9a-f]{10})\.js$/;
var SCOPE = new URL("./", self.location.href).href, RUN = /^\w[\w.-]*\.(html|json)$/;
// The raw copy of a site at <owner>.github.io/<repo>/: its gh-pages branch,
// which each run pushes to and Pages deploys from in its own time. A site
// served anywhere else has none.
var COPY = (function () {
  var owner = /^([a-z0-9-]+)\.github\.io$/.exec(self.location.hostname);
  var repo = /^\/([^\/]+)\/sw\.js$/.exec(self.location.pathname);
  return owner && repo ? "https://raw.githubusercontent.com/" + owner[1] + "/" + repo[1] + "/gh-pages/" : null;
})();
// Pages lags when it answers with a file deployed more than 12 minutes before,
// as a run is deployed every 10. The copy's beacon is asked at most every 2
// minutes, what it said, or that it said nothing, kept in a cache of its own,
// which outlives the worker; the copy has 5 seconds to answer for its beacon
// and 20 for a page or its data, for which Pages' answer stands, and for an
// asset, which nothing else can give, as long as it takes.
var LATE = 12 * 60000, BEACON = "elnino-copy", AGAIN = 2 * 60000, BRIEF = 5000, LONG = 20000;
var TYPES = {html: "text/html; charset=utf-8", json: "application/json; charset=utf-8",
             js: "text/javascript; charset=utf-8"};

// An asset's name and hash from its address, or null for anything else.
function named(url) {
  var href = new URL(url, self.location.href).href;
  return href.indexOf(HOME) === 0 ? NAMED.exec(href.slice(HOME.length)) : null;
}
// A run's file, its name beside the pages and its kind, from its address, the
// folder's being index.html; or null for anything else.
function runFile(url) {
  var u = new URL(url, self.location.href), href = u.origin + u.pathname;
  return href.indexOf(SCOPE) === 0 ? RUN.exec(href.slice(SCOPE.length) || "index.html") : null;
}
function hex(buffer) {
  return Array.prototype.map.call(new Uint8Array(buffer), function (b) { return (b < 16 ? "0" : "") + b.toString(16); }).join("");
}
function reply(body, kind) { return new Response(body, {headers: {"Content-Type": TYPES[kind]}}); }

// ---- the assets -------------------------------------------------------------
// The two latest files of each name stay; the cache lists them as kept.
function prune(cache) {
  return cache.keys().then(function (requests) {
    var seen = {};
    return Promise.all(requests.reverse().map(function (r) {
      var m = named(r.url);
      if (!m) return null;
      seen[m[1]] = (seen[m[1]] || 0) + 1;
      return seen[m[1]] > KEEP ? cache.delete(r) : null;
    }));
  });
}
// Whether bytes are the ones an asset's name was taken from.
function whole(body, hash) {
  return crypto.subtle.digest("SHA-256", body).then(function (sum) { return hex(sum).slice(0, 10) === hash; });
}
// An asset kept, the cache pruned after it; one the cache refuses is not kept.
function keep(cache, request, body, type) {
  return cache.put(request, new Response(body, {headers: type ? {"Content-Type": type} : {}}))
    .then(function () { return prune(cache); })
    .catch(function () { /* not kept: answered all the same */ });
}
// An asset from Pages, kept when its bytes are the ones its name was taken
// from (a portal's page or a file cut off never is), and answered either way,
// as Pages answered. One Pages cannot give comes from the copy instead, as a
// page from the copy names the assets of a run Pages has not deployed.
function fetchKept(cache, request, m) {
  function copied() { return fromCopyKept(cache, request, m); }
  return fetch(request).then(function (response) {
    if (!response.ok) return copied().then(function (copy) { return copy || response; });
    return response.arrayBuffer().then(function (body) {
      var type = response.headers.get("Content-Type");
      return whole(body, m[2]).then(function (yes) { return yes && keep(cache, request, body, type); })
        .catch(function () { /* not kept: answered all the same */ })
        .then(function () {
          return new Response(body, {status: response.status, statusText: response.statusText,
                                     headers: type ? {"Content-Type": type} : {}});
        });
    });
  }, function (error) {
    return copied().then(function (copy) {
      if (copy) return copy;
      throw error;
    });
  });
}
// The copy's asset, kept and answered when its bytes are the ones its name
// was taken from; null when there is no copy, or no such asset in it.
function fromCopyKept(cache, request, m) {
  if (!COPY) return Promise.resolve(null);
  return fromCopy("assets/" + m[0]).then(function (body) {
    return whole(body, m[2]).then(function (yes) {
      return yes ? keep(cache, request, body, TYPES.js).then(function () { return reply(body, "js"); }) : null;
    });
  }).catch(function () { return null; });
}
// An asset from the cache, or else fetched and kept; with no cache to be had,
// from the network as it answers.
function asset(request, m) {
  function network() { return fetch(request); }
  return caches.open(CACHE).then(function (cache) {
    return cache.match(request, {ignoreVary: true}).then(function (hit) {
      return hit || fetchKept(cache, request, m);
    }, network);
  }, network);
}

// ---- a run's files ----------------------------------------------------------
// A file of the copy, whole, never from the browser's cache and with no
// cookies; given ms, one that has not come in ms is called off, and fails.
function fromCopy(name, ms) {
  var stop = new AbortController(), timer = ms ? setTimeout(function () { stop.abort(); }, ms) : 0;
  return fetch(COPY + name, {cache: "no-store", credentials: "omit", signal: stop.signal})
    .then(function (r) {
      if (!r.ok) throw new Error(name + ": " + r.status);
      return r.arrayBuffer();
    })
    .then(function (body) { clearTimeout(timer); return body; },
          function (error) { clearTimeout(timer); throw error; });
}
// The run a beacon names, or null: only a run named in words counts.
function runOf(text) {
  try {
    var run = JSON.parse(text).run_at;
    return typeof run === "string" && !isNaN(Date.parse(run)) ? run : null;
  } catch (e) {
    return null;
  }
}
// What the copy's beacon says, or "" when it says nothing: asked again once
// AGAIN has passed since it was last asked, or the clock was put back, and
// each time when no cache will keep it. While it is being asked, all who
// want it wait for that answer, as a page asks for itself and its data at
// once.
var asking = null;
function copyBeacon() {
  var now = Date.now(), key = COPY + "run.json";
  function ask(cache) {
    asking = asking || fromCopy("run.json", BRIEF)
      .then(function (body) { return new TextDecoder().decode(body); }, function () { return ""; })
      .then(function (text) {
        function asked() { asking = null; return text; }
        return cache ? cache.put(key, new Response(text, {headers: {"X-Asked": String(now)}})).then(asked, asked)
                     : asked();
      });
    return asking;
  }
  return caches.open(BEACON).then(function (cache) {
    return cache.match(key).then(function (hit) {
      var asked = hit ? Number(hit.headers.get("X-Asked")) : NaN;
      return now >= asked && now - asked < AGAIN ? hit.text() : ask(cache);
    }, function () { return ask(null); });
  }, function () { return ask(null); });
}
// The run Pages' beacon names, or null.
function pagesRun() {
  return fetch(SCOPE + "run.json", {cache: "no-store"})
    .then(function (r) { return r.ok ? r.text() : ""; })
    .then(runOf, function () { return null; });
}
// Whether Pages answered with a file deployed more than LATE before, both by
// its own clock (a file with no dates was not); and whether it answered with
// no file, as for one its deploy has not got, or as a server failing does.
function late(r) { return Date.parse(r.headers.get("Date")) - Date.parse(r.headers.get("Last-Modified")) > LATE; }
function failed(r) { return r.status === 404 || r.status >= 500; }
// A run's file from Pages, unless Pages lags, fails or has not got it, and the
// copy's beacon names a later run than Pages' does, or any run when Pages'
// names none: then the copy's file. What the copy cannot give leaves Pages'
// answer, or its failure, as it was.
function newest(request, file) {
  return fetch(request).then(function (pages) {
    if (!late(pages) && !failed(pages)) return pages;
    var shown = file[0] !== "run.json" ? pagesRun() : pages.ok ? pages.clone().text().then(runOf) : null;
    return fromCopyIfLater(file, shown).then(function (copy) { return copy || pages; });
  }, function (error) {
    return fromCopyIfLater(file, null).then(function (copy) {
      if (copy) return copy;
      throw error;
    });
  });
}
// The copy's file when its beacon names a later run than ``shown``, Pages'
// run, or any run when that is none; or null.
function fromCopyIfLater(file, shown) {
  return Promise.all([copyBeacon(), shown]).then(function (both) {
    var beacon = both[0], run = runOf(beacon), theirs = both[1];
    if (!run || (theirs && !(Date.parse(run) > Date.parse(theirs)))) return null;
    if (file[0] === "run.json") return reply(beacon, "json");
    return fromCopy(file[0], LONG).then(function (body) { return reply(body, file[1]); });
  }).catch(function () { return null; });
}

self.addEventListener("install", function (e) { e.waitUntil(self.skipWaiting()); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", function (e) {
  if (e.request.method !== "GET") return;
  var m = named(e.request.url), file = !m && COPY ? runFile(e.request.url) : null;
  if (m) e.respondWith(asset(e.request, m));
  else if (file) e.respondWith(newest(e.request, file));
});
// A page names its assets: each not kept yet is fetched and kept.
self.addEventListener("message", function (e) {
  var urls = e.data && Array.isArray(e.data.keep) ? e.data.keep : [];
  urls = urls.filter(function (url) { return typeof url === "string" && named(url); });
  if (!urls.length) return;
  e.waitUntil(caches.open(CACHE).then(function (cache) {
    return Promise.all(urls.map(function (url) {
      return cache.match(url, {ignoreVary: true}).then(function (hit) {
        return hit || fetchKept(cache, url, named(url));
      }).catch(function () { /* the page's own load fetches it */ });
    }));
  }));
});
"""


def write_worker(out_dir: Path) -> Path:
    """Write the service worker beside the pages as the bytes of WORKER_JS,
    and return its path; one already there as it should be is left as it is."""
    path, body = Path(out_dir) / WORKER, WORKER_JS.encode("utf-8")
    if not (path.is_file() and path.read_bytes() == body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return path


def data(name: str, value) -> Asset:
    """An asset setting ``ELNINO[name]`` to value, written as JSON."""
    return Asset(name, f"(window.ELNINO = window.ELNINO || {{}}).{name} = "
                       + json.dumps(value, separators=(",", ":")) + ";\n")


def write(out_dir: Path, files) -> list[Path]:
    """Write each asset named in files into out_dir's assets folder as the
    bytes its name was taken from, and return their paths. One already there
    as it should be is left as it is. Raises KeyError, having written nothing,
    for a file no asset was made for."""
    chosen = [made(file) for file in dict.fromkeys(files)]
    if not chosen:
        return []
    folder = Path(out_dir) / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for asset in chosen:
        path, body = folder / asset.file, asset.text.encode("utf-8")
        # Bytes, not text: written as text on Windows its line ends would
        # change, and the file would no longer be the one its name says.
        if not (path.is_file() and path.read_bytes() == body):
            path.write_bytes(body)
        paths.append(path)
    return paths


def prune(out_dir: Path, keep) -> list[str]:
    """Remove from out_dir's assets folder every asset file not in keep, and
    return their names; any other file there is left alone."""
    folder = Path(out_dir) / FOLDER
    if not folder.is_dir():
        return []
    keep, gone = set(keep), []
    for path in sorted(folder.iterdir()):
        if path.name not in keep and _FILE.fullmatch(path.name) and path.is_file():
            path.unlink()
            gone.append(path.name)
    return gone


# --- the assets --------------------------------------------------------------
# Each made once a process, on first use. The modules are imported here rather
# than at the top: the pages import this one.

@functools.cache
def follower() -> Asset:
    """The follower, every page's, run before the page's own code."""
    from . import live
    return Asset("follower", live.SCRIPT)


@functools.cache
def places() -> Asset:
    """The gazetteer, in the atlas's rows: the desk's, the map's and the atlas's."""
    from .atlasview import _places_payload
    return data("places", _places_payload())


@functools.cache
def grids() -> Asset:
    """The composite grids: the desk's, the map's and the atlas's."""
    from .atlasview import _grid_payload
    return data("grids", _grid_payload())


@functools.cache
def coast() -> Asset:
    """The coastline the desk and the map draw."""
    from .stormdesk import _coast
    return data("coast", _coast())


@functools.cache
def desk() -> Asset:
    """The desk's and the map's code."""
    from .stormdesk import script
    return Asset("desk", script())


@functools.cache
def atlasgeo() -> Asset:
    """The coast, borders, rivers and lakes the atlas draws."""
    from .atlasview import _geo_payload
    return data("atlasgeo", _geo_payload())


@functools.cache
def relief() -> Asset:
    """The atlas's shaded relief. It stays a data address inside its asset:
    the atlas reads its pixels back, which a canvas allows for one and not for
    an image file of a page opened from disk."""
    from . import relief as shaded
    return data("relief", shaded.png())


@functools.cache
def atlas() -> Asset:
    """The atlas's code."""
    from .atlasview import _JS
    return Asset("atlas", _JS)


@functools.cache
def dashboard() -> Asset:
    """The dashboard's code: its charts' tooltips, the globe and the theme."""
    from .dashboard import _js
    return Asset("dashboard", _js())
