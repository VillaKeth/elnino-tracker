"""Code and data that are the same from run to run, in files beside the pages.

Every page carried all of its code and data inline, and every hourly run
rewrote every page, so a reader's browser fetched the gazetteer, the composite
grids and the scripts again each hour, for each page. Those parts go instead
in files named by their contents, ``assets/<name>.<sha256[:10]>.js``, which a
page names in its head as deferred classic scripts. A file's name changes only
when its text does, so a browser keeps each one across runs and across the
pages that share it; classic scripts load from a page opened as a file as
well as from one served.

The data set properties of one global, ``ELNINO``; the code is the follower
(elnino/live.py) and each page's own. A run writes the assets its pages name
before the pages (``write``) and lets go of those no page names any more
before it names itself in the beacon (``prune``); publish.py puts them up
beside the pages.

GitHub Pages sends every file again after each publish, with a new date and
tag, so a browser would fetch each asset again ten minutes after it last did.
A service worker beside the pages (``WORKER``, written by ``write_worker``)
keeps them instead: a file named for its contents is that file for good.
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
_TAG = re.compile(r'<script defer src="assets/([a-z][a-z0-9]*\.[0-9a-f]{10}\.js)"></script>')
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


def tags(items) -> str:
    """The tags naming these assets, in their order, one a line."""
    return "\n".join(item.tag() for item in items)


def page_assets(html: str) -> list[str]:
    """The asset files a page names, in the order it names them."""
    return _TAG.findall(html)


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


# The site's service worker, beside the pages so its scope is theirs. It
# answers only for the assets: a GET of assets/<name>.<sha256[:10]>.js under
# its own folder comes from its cache, or from the network and is kept there
# when its bytes are the ones its name was taken from; the two latest files
# of each name are kept, as a page cached from before a publish still names
# the last ones. A page tells it the assets it names (live.py), so they are
# kept from a first visit on. Pages, data and everything else go to the
# network as ever.
WORKER = "sw.js"
WORKER_JS = r"""// The El Nino tracker's service worker (elnino/assets.py): it keeps the
// assets the pages name, which are named for their contents.
"use strict";
var CACHE = "elnino-assets", KEEP = 2;
var HOME = new URL("assets/", self.location.href).href, NAMED = /^([a-z][a-z0-9]*)\.([0-9a-f]{10})\.js$/;
// An asset's name and hash from its address, or null for anything else.
function named(url) {
  var href = new URL(url, self.location.href).href;
  return href.indexOf(HOME) === 0 ? NAMED.exec(href.slice(HOME.length)) : null;
}
function hex(buffer) {
  return Array.prototype.map.call(new Uint8Array(buffer), function (b) { return (b < 16 ? "0" : "") + b.toString(16); }).join("");
}
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
// An asset from the network, kept when its bytes are the ones its name was
// taken from (a portal's page or a file cut off never is), and answered
// either way, as the network answered.
function fetchKept(cache, request, hash) {
  return fetch(request).then(function (response) {
    if (!response.ok) return response;
    return response.arrayBuffer().then(function (body) {
      var type = response.headers.get("Content-Type"), headers = type ? {"Content-Type": type} : {};
      return crypto.subtle.digest("SHA-256", body).then(function (sum) {
        if (hex(sum).slice(0, 10) !== hash) return null;
        return cache.put(request, new Response(body, {headers: headers})).then(function () { return prune(cache); });
      }).catch(function () { /* not kept: answered all the same */ }).then(function () {
        return new Response(body, {status: response.status, statusText: response.statusText, headers: headers});
      });
    });
  });
}
self.addEventListener("install", function (e) { e.waitUntil(self.skipWaiting()); });
self.addEventListener("activate", function (e) { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", function (e) {
  var m = e.request.method === "GET" && named(e.request.url);
  if (!m) return;
  function network() { return fetch(e.request); }
  e.respondWith(caches.open(CACHE).then(function (cache) {
    return cache.match(e.request, {ignoreVary: true}).then(function (hit) {
      return hit || fetchKept(cache, e.request, m[2]);
    }, network);
  }, network));
});
// A page names its assets: each not kept yet is fetched and kept.
self.addEventListener("message", function (e) {
  var urls = e.data && Array.isArray(e.data.keep) ? e.data.keep : [];
  urls = urls.filter(function (url) { return typeof url === "string" && named(url); });
  if (!urls.length) return;
  e.waitUntil(caches.open(CACHE).then(function (cache) {
    return Promise.all(urls.map(function (url) {
      return cache.match(url, {ignoreVary: true}).then(function (hit) {
        return hit || fetchKept(cache, url, named(url)[2]);
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
