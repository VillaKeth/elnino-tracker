// The El Nino tracker's service worker (elnino/assets.py): it keeps the
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
