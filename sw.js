// The El Nino tracker's service worker (elnino/assets.py). It keeps the
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
