
(function () {
  "use strict";
  // The run's data, from the page, with what is the same on every run.
  var D = withAssets(JSON.parse(document.getElementById("desk-data").textContent));
  function $(id) { return document.getElementById(id); }
  var map = $("map"), svgEl = $("overlay"), coastG = $("coast"), geoG = $("geo"), marksG = $("marks");
  var divider = $("divider"), framePill = $("frame"), statusPill = $("status");
  var scrub = $("scrub"), scrubRead = $("scrub-read"), playBtn = $("play");
  var TILE = 256, MINZ = 1, MAXZ = 13, UNIT = 1048576, HOUR = 3600000, NM = 1.852, ASIDE = 900000, SETTLE = 2700000;
  var EARTH_KM = 6378.137, GEO_KM = 42164.0, CIRCUMFERENCE = 40075.017;
  var THRESHOLDS = ["34", "50", "64"];
  var ORDER = ["Tropical Storm Watch", "Tropical Storm Warning", "Hurricane Watch", "Hurricane Warning"];
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
  var COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE", "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
  var LAYERS = {}, STORMS = [], BYID = Object.create(null), DOM = {};
  var S = {
    x: 0.5, y: 0.45, z: 3, w: 1, h: 1,
    layer: "geocolor", second: "infrared", compare: false, split: 0.5,
    loop: false, loopWanted: false, frame: 0, scrub: 0, playing: false, selected: null, inView: {},
    show: {}, refs: {}, pin: null, day: null, dayState: "idle", dayStepped: false,
    imagery: navigator.onLine === false ? "offline" : "pending"
  };

  // ---- small things -------------------------------------------------------
  function esc(v) {
    return String(v == null ? "" : v).replace(/[&<>"']/g, function (c) {
      return {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c];
    });
  }
  function clamp(v, lo, hi) { return Math.max(lo, Math.min(hi, v)); }
  function wrap(lon) { return ((lon + 180) % 360 + 360) % 360 - 180; }
  function rad(d) { return d * Math.PI / 180; }
  function deg(r) { return r * 180 / Math.PI; }
  function mx(lon) { return (lon + 180) / 360; }
  function my(lat) {
    var p = rad(clamp(lat, -85.0511, 85.0511));
    return (1 - Math.log(Math.tan(p) + 1 / Math.cos(p)) / Math.PI) / 2;
  }
  function lonOf(x) { return x * 360 - 180; }
  function latOf(y) { return deg(Math.atan(Math.sinh(Math.PI * (1 - 2 * y)))); }
  // A name a table has of its own: words, and not one every object inherits
  // ("constructor").
  function own(table, key) { return typeof key === "string" && Object.prototype.hasOwnProperty.call(table, key); }
  function finite(x) { return typeof x === "number" && isFinite(x); }
  function world() { return TILE * Math.pow(2, S.z); }
  function km(lon1, lat1, lon2, lat2) {
    var p1 = rad(lat1), p2 = rad(lat2), dp = p2 - p1, dl = rad(lon2 - lon1);
    var a = Math.sin(dp / 2) * Math.sin(dp / 2) +
            Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) * Math.sin(dl / 2);
    return 2 * 6371 * Math.asin(Math.min(1, Math.sqrt(a)));
  }
  function bearing(lon1, lat1, lon2, lat2) {
    var dl = rad(lon2 - lon1), p1 = rad(lat1), p2 = rad(lat2);
    var y = Math.sin(dl) * Math.cos(p2);
    var x = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
    return (deg(Math.atan2(y, x)) + 360) % 360;
  }
  // Where a heading and a distance lead; the longitude is left unwrapped so a
  // storm's rings stay in the storm's own frame across the date line.
  function dest(lon, lat, heading, dist) {
    var d = dist / 6371, p1 = rad(lat), t = rad(heading);
    var p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(t));
    var dl = Math.atan2(Math.sin(t) * Math.sin(d) * Math.cos(p1), Math.cos(d) - Math.sin(p1) * Math.sin(p2));
    return [lon + deg(dl), deg(p2)];
  }
  function zenith(lon, lat, sub) {
    var g = Math.acos(clamp(Math.cos(rad(lat)) * Math.cos(rad(wrap(lon - sub))), -1, 1));
    var below = Math.cos(g) - EARTH_KM / GEO_KM;
    return below <= 0 ? null : deg(Math.atan2(Math.sin(g), below));
  }
  function pad2(n) { return (n < 10 ? "0" : "") + n; }
  function utc(ms) {
    var d = new Date(ms);
    return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + " " +
           pad2(d.getUTCHours()) + ":" + pad2(d.getUTCMinutes()) + " UTC";
  }
  // The same, as the map writes it beside a forecast point, where room is
  // short: forecast points fall on the hour.
  function zulu(ms) {
    var d = new Date(ms);
    return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + " " + pad2(d.getUTCHours()) + "Z";
  }
  function isoZ(ms) { return new Date(ms).toISOString().slice(0, 19) + "Z"; }
  function dayZ(ms) { return new Date(ms).toISOString().slice(0, 10); }
  function span(min) {
    if (min < 60) return min + " min";
    var h = Math.floor(min / 60), m = min % 60;
    if (h < 48) return h + " h" + (m ? " " + m + " min" : "");
    return Math.round(h / 24) + " days";
  }
  function ago(ms) {
    var m = Math.round((Date.now() - ms) / 60000);
    return m < 0 ? "in " + span(-m) : span(m) + " ago";
  }
  function pct(v) { return v == null ? "not given" : v + "%"; }
  // A formation alert holds until the time JTWC said it would reissue,
  // upgrade or cancel it by; past that, with nothing newer read, it ran out,
  // and which of the three JTWC did is not known here. A map label is short.
  function lapsed(until) { var t = Date.parse(until || ""); return !isNaN(t) && t <= Date.now(); }
  function alertWords(until, short) {
    var t = Date.parse(until || "");
    if (isNaN(t)) return "formation alert in effect";
    if (t > Date.now()) return "formation alert until " + utc(t);
    return "formation alert ran to " + utc(t) + (short ? "" : "; nothing newer read");
  }
  function alertHtml(until) {
    return until ? '<span data-until="' + esc(until) + '">' + esc(alertWords(until)) + "</span>" : esc(alertWords(until));
  }
  var lapsedNow = "";
  function ages() {
    var list = document.querySelectorAll("time[data-age]");
    for (var i = 0; i < list.length; i++) {
      var ms = Date.parse(list[i].getAttribute("datetime"));
      if (!isNaN(ms)) list[i].textContent = list[i].getAttribute("data-age") + " (" + ago(ms) + ")";
    }
    // An alert that runs out while the page is open is reworded, and its box redrawn.
    var spans = document.querySelectorAll("[data-until]");
    for (var j = 0; j < spans.length; j++) spans[j].textContent = alertWords(spans[j].getAttribute("data-until"));
    var out = D.outlook.filter(function (a) { return a.alert && a.formation && lapsed(a.formation.until); })
                       .map(function (a) { return a.key; }).join(" ");
    if (out !== lapsedNow) { lapsedNow = out; dirty(); }
  }

  // ---- the storms ---------------------------------------------------------
  function prepare() {
    bands();
    LAYERS = {};
    D.layers.forEach(function (l) { LAYERS[l.id] = l; });
    // Kept in a table that answers to no name every object has
    // ("constructor"), as an address can name any.
    STORMS = []; BYID = Object.create(null);
    D.storms.forEach(function (s) {
      var nodes = [];
      s.path.forEach(function (p) {
        var t = Date.parse(p.t);
        if (!isNaN(t)) nodes.push({t: t, lon: p.lon, lat: p.lat, wind: p.wind, radii: p.radii || {},
                                   label: p.label, category: p.category, stage: p.stage,
                                   formed: p.formed !== false});
      });
      // The advisory's own position replaces the path's at the advisory time.
      var fix = s.advisory_fix;
      if (fix) {
        var at = Date.parse(fix.t);
        for (var i = 0; i < nodes.length; i++) {
          if (nodes[i].t === at) { nodes[i].lon = fix.lon; nodes[i].lat = fix.lat; break; }
          if (nodes[i].t > at && i > 0) {
            nodes.splice(i, 0, {t: at, lon: fix.lon, lat: fix.lat, wind: fix.wind,
                                radii: nodes[i - 1].radii, label: nodes[i - 1].label,
                                category: nodes[i - 1].category, stage: nodes[i - 1].stage,
                                formed: nodes[i - 1].formed});
            break;
          }
        }
      }
      var st = {d: s, id: s.id, hue: (D.style.hues || {})[s.id] || "var(--ink2)",
                nodes: nodes, x0: mx(s.lon)};
      STORMS.push(st); BYID[s.id] = st;
    });
  }
  // The centre and radii at a time, straight between the nodes either side;
  // nothing before the first node or after the last forecast point.
  function centreAt(st, T) {
    var n = st.nodes;
    if (!n.length || T < n[0].t || T > n[n.length - 1].t) return null;
    var i = 0;
    while (i < n.length - 2 && n[i + 1].t < T) i++;
    var a = n[i], b = n[Math.min(i + 1, n.length - 1)];
    var f = b.t > a.t ? clamp((T - a.t) / (b.t - a.t), 0, 1) : 0;
    var radii = {};
    THRESHOLDS.forEach(function (k) {
      var ra = a.radii[k], rb = b.radii[k];
      radii[k] = ra && rb ? ra.map(function (v, q) { return v + (rb[q] - v) * f; })
               : (f === 0 ? ra || null : (f === 1 ? rb || null : null));
    });
    var near = f < 0.5 ? a : b;
    return {t: T, lon: a.lon + (b.lon - a.lon) * f, lat: a.lat + (b.lat - a.lat) * f,
            wind: a.wind != null && b.wind != null ? a.wind + (b.wind - a.wind) * f : near.wind,
            radii: radii, label: near.label, category: near.category, stage: near.stage,
            formed: near.formed};
  }
  // Saffir-Simpson from a wind as a label writes it (cyclones.CATEGORY_FLOOR,
  // carried in the page's data): 0 short of a hurricane.
  function categoryOf(kt) {
    var floors = D.style.categories || [];
    for (var i = 0; i < floors.length; i++) if (kt >= floors[i][0]) return floors[i][1];
    return 0;
  }
  // What a storm is called at a wind, as cyclones.short_label calls it: the
  // map names a storm as its forecast runs, at winds no advisory gave.
  function shortAt(kt, stage, formed) {
    if (kt == null) return "unknown";
    if (!formed && (stage === "EX" || stage === "LO")) return stage === "EX" ? "non-trop low" : "low";
    var gone = {EX: "post-trop", LO: "rem low", DB: "disturbance", WV: "wave", DS: "dissipating"};
    if (Object.prototype.hasOwnProperty.call(gone, stage)) return gone[stage];
    if (stage === "SD" || stage === "SS") return kt >= 34 ? "subtrop storm" : "subtrop dep";
    var n = categoryOf(kt);
    if (n) return "Cat " + n;
    return kt >= 34 ? "trop storm" : "trop dep";
  }
  function inside(c, lon, lat) {
    var d = km(c.lon, c.lat, lon, lat), q = Math.floor(bearing(c.lon, c.lat, lon, lat) / 90) % 4;
    var found = 0;
    THRESHOLDS.forEach(function (t) { var r = c.radii[t]; if (r && d <= r[q] * NM) found = +t; });
    return found;
  }

  // ---- imagery: which layer, which frames ---------------------------------
  function source(id, sat) {
    var l = LAYERS[id];
    if (!l) return null;
    if (l.stack) return l.stack.indexOf(sat) >= 0 ?
      {name: sat, tms: l.tms, zoom: l.zoom, ext: l.format, step: l.step, sat: null, layer: l, note: ""} : null;
    if (l.global) return {name: l.global, tms: l.tms, zoom: l.zoom, ext: l.format, step: l.step,
                          sat: null, layer: l, note: ""};
    // A street map has no imager and no frames: a storm over it is drawn at the clock's time.
    if (!sat || !l.satellites) return null;
    var name = l.satellites[sat];
    if (name) return {name: name, tms: l.tms, zoom: l.zoom, ext: l.format, step: l.step,
                      sat: sat, layer: l, note: ""};
    var ir = LAYERS.infrared;   // GIBS carries no GeoColor from Himawari
    return {name: ir.satellites[sat], tms: ir.tms, zoom: ir.zoom, ext: ir.format, step: ir.step,
            sat: sat, layer: ir, note: "GIBS has no " + sat + " " + l.name + ": infrared instead"};
  }
  function timed(s) { return !!(s && s.step && s.step.indexOf("D") < 0); }
  function framesOf(s) { var d = s && DOM[s.name]; return d && d.frames.length ? d.frames : null; }
  function frameOf(s, i) { var f = framesOf(s); return f ? f[Math.min(i, f.length - 1)] : null; }
  // The time a storm is drawn for: the frame on screen from the imager that
  // sees it, or the clock where there is no such frame.
  function base(st) {
    var s = source(S.layer, st.d.view && st.d.view.satellite);
    if (timed(s)) {
      ask(s);
      var f = frameOf(s, S.frame);
      if (f) return {t: f.t, image: true};
    }
    return {t: Date.now(), image: false};
  }
  function when(st) { return base(st).t + S.scrub * HOUR; }
  function duration(text) {
    var m = /^P(?:(\d+)D)?(?:T(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?)?$/.exec(text || "");
    if (!m) return 0;
    return ((((+m[1] || 0) * 24 + (+m[2] || 0)) * 60 + (+m[3] || 0)) * 60 + (+m[4] || 0)) * 1000;
  }
  function stamp(text) { return Date.parse(/^\d{4}-\d\d-\d\d$/.test(text) ? text + "T00:00:00Z" : text); }
  // GIBS answers with start/end/period ranges; the frames are counted back
  // from each range's end, which is always a frame that exists. A frame
  // younger than SETTLE can still be part made (GOES GeoColor half white at
  // 35 minutes, 25 Sep 2026), so the newest frame shown is the newest older
  // than that, where GIBS lists one.
  function parseDomain(text, daily) {
    var m = /<Domain>([^<]*)<\/Domain>/.exec(text), times = [];
    if (!m) return [];
    m[1].split(",").forEach(function (part) {
      var bits = part.trim().split("/");
      if (bits.length === 3) {
        var a = stamp(bits[0]), b = stamp(bits[1]), step = duration(bits[2]);
        if (isNaN(a) || isNaN(b) || !step) return;
        for (var t = b, n = 0; t >= a && n < 400; t -= step, n++) times.push(t);
      } else if (bits[0]) {
        var one = stamp(bits[0]);
        if (!isNaN(one)) times.push(one);
      }
    });
    times.sort(function (p, q) { return q - p; });
    var settled = times.filter(function (t) { return Date.now() - t >= SETTLE; });
    if (!daily && settled.length) times = settled;
    if (!times.length) return [];
    var latest = times[0], keep = [];
    times.forEach(function (t) {
      if (keep.length && keep[keep.length - 1].t === t) return;
      if (daily ? !keep.length : latest - t <= 2 * HOUR) keep.push({t: t, key: daily ? dayZ(t) : isoZ(t)});
    });
    return keep;
  }
  // One question goes out first; the rest wait for its answer, so a page
  // that cannot reach GIBS makes one failed request, not one per imager.
  var probing = false;
  function ask(s) {
    if (!s || !s.step || S.imagery === "offline" || S.imagery === "unreachable") return;
    if (S.imagery === "pending" && probing) return;
    var known = DOM[s.name];
    if (known && !known.stale) return;
    if (known) known.stale = false; else DOM[s.name] = {frames: [], stale: false, failed: false, unanswered: false, aside: {}};
    if (S.imagery === "pending") probing = true;
    var daily = s.step.indexOf("D") >= 0, now = Date.now();
    var back = daily ? 240 : (s.step === "PT10M" ? 6 : 24), fmt = daily ? dayZ : isoZ;
    var url = D.gibs.domains.replace("{layer}", s.name).replace("{tms}", s.tms)
      .replace("{start}", fmt(now - back * HOUR)).replace("{end}", fmt(now + HOUR));
    fetch(url).then(function (r) {
      if (!r.ok) throw new Error("GIBS " + r.status);
      return r.text();
    }).then(function (text) {
      var aside = DOM[s.name].aside, since = Date.now() - ASIDE;
      var frames = parseDomain(text, daily).filter(function (f) { return !(aside[f.key] > since); });
      if (frames.length) DOM[s.name].frames = frames;
      DOM[s.name].failed = !frames.length && !DOM[s.name].frames.length;
      DOM[s.name].unanswered = false;
      S.imagery = "ok";
      probing = false;
      dirty();
    }).catch(function () {
      // No answer is not "no frames": the ten-minute refresh asks again.
      DOM[s.name].unanswered = !DOM[s.name].frames.length;
      if (S.imagery !== "ok") S.imagery = "unreachable";
      probing = false;
      dirty();
    });
  }
  // GIBS asked again from the start, with the page's opening question: under
  // a street map with only NASA's overlays on, no other question would go.
  function askGibsAgain() {
    DOM = {}; S.imagery = "pending"; probing = false;
    ask(source("geocolor", "GOES-East"));
  }
  function retry() { statusPill.innerHTML = ""; askGibsAgain(); forgetMaps(); if (S.then) thenRetry(); dirty(); }

  // ---- tiles ----------------------------------------------------------------
  function tileUrl(s, key, z, row, col) {
    return (key ? D.gibs.tiles : D.gibs.static).replace("{layer}", s.name).replace("{time}", key || "")
      .replace("{tms}", s.tms).replace("{z}", z).replace("{y}", row).replace("{x}", col)
      .replace("{ext}", s.ext);
  }
  // Street maps: XYZ tiles from a template, never deeper than the layer goes.
  var NODATA = {}, MAPS = {};
  function xyzUrl(template, z, x, y) {
    return template.replace("{z}", z).replace("{y}", y).replace("{x}", x);
  }
  // Past its coverage Esri answers 200 with a grey "Map data not yet
  // available" JPEG (open Pacific from zoom 16, Amazon imagery from 18, Lima
  // from 20; 28 Sep 2026): 240 of 256 samples exactly 204,204,204.
  function placeholder(px) {
    var grey = 0;
    for (var i = 0; i + 3 < px.length; i += 4) {
      if (px[i + 3] >= 250 && Math.abs(px[i] - 204) <= 3 && Math.abs(px[i + 1] - 204) <= 3 &&
          Math.abs(px[i + 2] - 204) <= 3) grey++;
    }
    return grey >= 200;
  }
  // The tile to draw for one asked for: itself, or where Esri has answered
  // with its placeholder, the nearest coarser tile it has not. A placeholder
  // at one level means no level under it has imagery either, so the
  // shallowest level known to have none decides, and zooming further in
  // asks for nothing already known to be missing.
  function present(name, z, c, r) {
    var at = {z: z, c: c, r: r};
    for (; z > 0; z--, c = Math.floor(c / 2), r = Math.floor(r / 2)) {
      var m = Math.pow(2, z);
      if (NODATA[name + "/" + z + "/" + (((c % m) + m) % m) + "/" + r]) at = {z: z - 1, c: Math.floor(c / 2), r: Math.floor(r / 2)};
    }
    return at;
  }
  function xyzCells(l, template, name) {
    var out = [], seen = {};
    var gz = clamp(Math.round(S.z), 0, l.zoom), n = Math.pow(2, gz), o = origin(), size = o.W / n;
    var c0 = Math.floor(-o.left / size), c1 = Math.floor((S.w - o.left - 0.01) / size);
    var r0 = Math.max(0, Math.floor(-o.top / size)), r1 = Math.min(n - 1, Math.floor((S.h - o.top - 0.01) / size));
    for (var r = r0; r <= r1; r++) for (var c = c0; c <= c1; c++) {
      var t = present(name, gz, c, r), m = Math.pow(2, t.z), id = name + "/" + t.z + "/" + t.c + "/" + t.r;
      if (seen[id]) continue;
      seen[id] = true;
      out.push({id: id, z: t.z, c: t.c, r: t.r, clip: "", name: name, key: null, map: l.id,
                url: xyzUrl(template, t.z, ((t.c % m) + m) % m, t.r), check: false, grey: !!l.grey,
                credit: l.credit, nasa: false, wb: l.wayback || 0});
    }
    return out;
  }
  function maxZoom() { var l = LAYERS[S.layer]; return l && l.kind === "map" ? l.zoom : MAXZ; }
  function servedOnly(protocol) { return /^https?:$/.test(protocol); }
  // A then-and-now side (thennow.py) names its places while Esri's names are over it.
  function labelled(id) { var l = LAYERS[id]; return !!(l && (l.then ? !!l.over : l.kind === "map")); }
  function labelledBase() { return labelled(S.layer); }
  // Whether the map under a point on the screen names its own places: with
  // two layers compared, the second is the one right of the divider.
  function namedAt(x) { return labelled(S.compare && x >= S.split * S.w ? S.second : S.layer); }
  function mapDown(id) { var m = MAPS[id]; return !!(m && m.failed && !m.ok); }
  // NASA's tiles are counted by layer and frame: GIBS can list a frame and not
  // send its tiles. A failure that set its frame aside is not counted, as the
  // frame before it is drawn instead.
  var GOT = {};
  function gotKey(name, key) { return name + "/" + (key || "-"); }
  function tallyNasa(img, what) {
    var k = gotKey(img._name, img._key), g = GOT[k] || (GOT[k] = {ok: 0, failed: 0});
    g[what]++;
  }
  // Whether none of the tiles of a source's frame on show arrived, and some failed.
  function tilesDown(s) {
    var l = s.layer || {}, f = s.step && !l.stack && !l.time && !l.then ? frameOf(s, S.frame) : null;
    var g = GOT[gotKey(s.name, l.then ? l.time : l.stack ? S.day : l.time || (f && f.key))];
    return !!(g && g.failed && !g.ok);
  }
  // Every NASA source of one side's layer in view has had its tiles fail.
  function nasaDown(view) {
    var any = false;
    for (var k in view || {}) {
      var s = view[k];
      if (!s || !s.name || s.map) continue;
      if (!tilesDown(s)) return false;
      any = true;
    }
    return any;
  }
  function tally(img, what) {
    var m = MAPS[img._map] || (MAPS[img._map] = {ok: 0, failed: 0});
    m[what]++;
  }
  // A map tile that did not arrive is asked for again 30 s after its address
  // first failed, and after twice the wait each time since, up to 16 minutes:
  // one lost answer from a map's server does not leave a hole for the visit.
  var AGAIN = {};
  function againIn(fails) { return Math.min(30000 * Math.pow(2, Math.max(0, fails - 1)), 960000); }
  function askAgain(img, now) { return !!(img._map && img._failed && now - img._failedAt >= againIn(AGAIN[img._url] || 1)); }
  // Once the network is back or Retry is pressed, every tile that failed, a
  // map's or NASA's, is asked for again at once, and the waits start over.
  function forgetMaps() {
    MAPS = {};
    AGAIN = {};
    GOT = {};
    [panes.a, panes.b, panes.o, panes.ob, panes.r, panes.e].forEach(function (pane) {
      for (var k in pane.sets) {
        var imgs = pane.sets[k].imgs;
        for (var id in imgs) if (imgs[id]._failed) { imgs[id].remove(); delete imgs[id]; }
      }
    });
  }
  function TileSet(parent, ref) {
    this.el = document.createElement("div");
    this.el.className = "gibsset";
    parent.appendChild(this.el);
    this.imgs = {};
    this.ref = !!ref;
  }
  function origin() { var W = world(); return {W: W, left: S.w / 2 - S.x * W, top: S.h / 2 - S.y * W}; }
  function place(img, o) {
    var size = o.W / Math.pow(2, img._z);
    img.style.transform = "translate(" + (o.left + img._c * size).toFixed(1) + "px," +
                          (o.top + img._r * size).toFixed(1) + "px)";
    img.style.width = img.style.height = (size + 0.6).toFixed(1) + "px";
  }
  function inside_view(img, o) {
    var size = o.W / Math.pow(2, img._z), x = o.left + img._c * size, y = o.top + img._r * size;
    return x < S.w && y < S.h && x + size > 0 && y + size > 0;
  }
  // GIBS sends its tiles with CORS, so a tile can be looked at: 16 by 16
  // samples, the share that is solid black and, of the opaque ones, the share
  // that is pure white.
  var sampler = null;
  // A tile as 16 by 16 RGBA samples; null where it cannot be read.
  function pixels(img) {
    try {
      sampler = sampler || document.createElement("canvas");
      sampler.width = sampler.height = 16;
      var cx = sampler.getContext("2d", {willReadFrequently: true});
      cx.clearRect(0, 0, 16, 16);
      cx.drawImage(img, 0, 0, 16, 16);
      return cx.getImageData(0, 0, 16, 16).data;
    } catch (err) { return null; }
  }
  function sample(img) {
    var px = pixels(img), black = 0, white = 0, opaque = 0;
    if (!px) return null;
    for (var i = 0; i < px.length; i += 4) {
      if (px[i + 3] < 250) continue;
      opaque++;
      if (Math.max(px[i], px[i + 1], px[i + 2]) <= 8) black++;
      if (Math.min(px[i], px[i + 1], px[i + 2]) >= 252) white++;
    }
    return {black: black / 256, white: opaque ? white / opaque : 0};
  }
  // GIBS lists a frame before all its tiles are made. A tile of an unfinished
  // frame is missing (Himawari, 20 minutes on), or is served with white where
  // the data will go (GOES, 45 minutes on; real cloud tops sample no pure
  // white at all). Either sets the frame aside if it is one of the imager's
  // three newest, and every tile of that imager falls back to the frame
  // before it, so one imager never shows two times at once. No more than
  // three frames an imager are set aside in a quarter of an hour, so a
  // network that fails every tile costs three requests a tile, not thirteen.
  function setAside(img) {
    var d = DOM[img._name], recent = 0, since = Date.now() - ASIDE;
    if (!d || !img._key) return;
    for (var k in d.aside) if (d.aside[k] > since) recent++;
    if (recent >= 3) return;
    for (var i = 0; i < Math.min(3, d.frames.length - 1); i++) {
      if (d.frames[i].key !== img._key) continue;
      d.aside[img._key] = Date.now();
      d.frames.splice(i, 1);
      dirty();
      return true;
    }
    return false;
  }
  function tileLoaded() {
    // A class NASA paints too strongly for an overlay is faded, and the tile drawn again.
    if (this._faint && !this._faded && fadeTile(this)) return;
    if (this._map) tally(this, "ok"); else tallyNasa(this, "ok");
    // Esri's placeholder is an answer that it has nothing finer here: the
    // tile is hidden and the next draw asks for the one above it. Only the
    // tiles change, so nothing else is rebuilt.
    if (this._grey) {
      var px = pixels(this);
      if (px && placeholder(px)) {
        var m = Math.pow(2, this._z);
        this.style.visibility = "hidden";
        NODATA[this._name + "/" + this._z + "/" + (((this._c % m) + m) % m) + "/" + this._r] = true;
        requestRender();
        return;
      }
    }
    var got = this._ref || this._check ? sample(this) : null;
    // Where a reference layer has nothing, GIBS can answer with an opaque
    // black square (the same 921-byte PNG everywhere; coastlines at 7/58/24).
    if (got && this._ref && got.black === 1) this.style.visibility = "hidden";
    if (got && this._check && got.white > 0.2) { this.style.visibility = "hidden"; setAside(this); }
    requestRender();
  }
  function tileFailed() {
    this.style.visibility = "hidden";
    this._failed = true;
    // A tile of Esri's archive past zoom 13 is asked after in its release's
    // tilemap first (thennow.py): if Esri has none there, the coarser is drawn.
    if (this._wb && this._z > 13 && !this._asked) { wbAsk(this); return; }
    if (this._map) {
      this._failedAt = Date.now(); tally(this, "failed");
      AGAIN[this._url] = (AGAIN[this._url] || 0) + 1;
      setTimeout(requestRender, againIn(AGAIN[this._url]) + 100);
      requestRender();
    } else if (!setAside(this)) {
      tallyNasa(this, "failed");
      requestRender();
    }
  }
  TileSet.prototype.draw = function (cells) {
    var o = origin(), want = {}, ready = true;
    for (var i = 0; i < cells.length; i++) {
      var cell = cells[i], img = this.imgs[cell.id];
      if (img && askAgain(img, Date.now())) { img.remove(); delete this.imgs[cell.id]; img = null; }
      if (!img) {
        img = document.createElement("img");
        img.alt = ""; img.draggable = false; img.decoding = "async"; img.className = "gibstile";
        img._z = cell.z; img._c = cell.c; img._r = cell.r; img._name = cell.name; img._key = cell.key;
        if (cell.clip) img.style.clipPath = cell.clip;
        img.crossOrigin = "anonymous"; img._ref = this.ref; img._check = cell.check;
        img._grey = cell.grey; img._map = cell.map; img._faint = cell.faint; img._url = cell.url;
        img._credit = cell.credit; img._nasa = !!cell.nasa; img._cut = cell.cut || [0, 0]; img._wb = cell.wb || 0;
        img.onload = tileLoaded; img.onerror = tileFailed;
        img.src = cell.url;
        this.el.appendChild(img);
        this.imgs[cell.id] = img;
      }
      // Finer tiles over coarser ones standing in beneath them.
      img.style.zIndex = 10 + cell.z;
      want[cell.id] = true;
      if (!img.complete) ready = false;
      place(img, o);
    }
    // Tiles from the last zoom or layer stay under the new ones until those arrive.
    for (var k in this.imgs) {
      if (want[k]) continue;
      var old = this.imgs[k];
      if (!ready && old.complete && old.naturalWidth && inside_view(old, o)) { old.style.zIndex = 1; place(old, o); }
      else { old.remove(); delete this.imgs[k]; }
    }
  };
  TileSet.prototype.move = function () {
    var o = origin();
    for (var k in this.imgs) {
      var img = this.imgs[k];
      if (inside_view(img, o)) place(img, o); else { img.remove(); delete this.imgs[k]; }
    }
  };
  TileSet.prototype.drop = function () { this.el.remove(); this.imgs = {}; };
  var panes = {a: {el: $("tiles"), sets: {}}, b: {el: $("tiles-b"), sets: {}}, r: {el: $("refs"), sets: {}},
               o: {el: $("over"), sets: {}}, ob: {el: $("over-b"), sets: {}}, e: {el: $("enso-tiles"), sets: {}}};
  function drawPane(pane, specs, moving) {
    var keep = {};
    specs.forEach(function (sp) {
      var set = pane.sets[sp.key] || (pane.sets[sp.key] = new TileSet(pane.el, pane === panes.r));
      if (moving) set.move(); else set.draw(sp.cells);
      set.el.style.visibility = sp.visible ? "" : "hidden";
      set.el.style.zIndex = sp.z || 0;
      keep[sp.key] = true;
    });
    for (var k in pane.sets) if (!keep[k]) { pane.sets[k].drop(); delete pane.sets[k]; }
  }
  // Each imager keeps the longitudes nearer its sub-point than any other's,
  // which it sees most nearly overhead. Geostationary sub-points lie on the
  // equator, so the borders are the meridians halfway between them, and a
  // tile across a border is drawn from both imagers, each clipped to its side.
  var BANDS = [];
  function bands() {
    var sats = D.satellites.slice().sort(function (a, b) { return a.lon - b.lon; }), n = sats.length;
    BANDS = sats.map(function (s, i) {
      var west = sats[(i + n - 1) % n], east = sats[(i + 1) % n];
      var toW = n > 1 ? ((s.lon - west.lon) % 360 + 360) % 360 : 360;
      var toE = n > 1 ? ((east.lon - s.lon) % 360 + 360) % 360 : 360;
      return {name: s.name, lon: s.lon, w: s.lon - toW / 2, e: s.lon + toE / 2};
    });
  }
  // The imagers owning parts of longitudes lo..hi, in that frame, and whether
  // each sees any of its part within 70 degrees of zenith between the
  // latitudes south..north.
  function owners(lo, hi, south, north) {
    var out = [], lat = south > 0 ? south : (north < 0 ? north : 0);
    BANDS.forEach(function (b) {
      for (var k = Math.ceil((lo - b.e) / 360); b.w + 360 * k < hi; k++) {
        var w = Math.max(lo, b.w + 360 * k), e = Math.min(hi, b.e + 360 * k);
        if (e - w < 1e-9) continue;
        var z = zenith(clamp(b.lon + 360 * k, w, e), lat, b.lon);
        out.push({name: b.name, w: b.w + 360 * k, e: b.e + 360 * k, seen: z !== null && z <= 70});
      }
    });
    return out;
  }
  // The tiles of one layer in view, each at the frame GIBS lists for its imager.
  function cells(id, frame) {
    var l = LAYERS[id], out = [], used = {}, seen = {};
    if (!l) return {cells: out, used: used};
    if (l.kind === "map") {
      // The coarsest zoom drawn where Esri had nothing finer, for the pill to say.
      var list = l.tiles ? xyzCells(l, l.tiles, l.nodata || l.id) : [], wanted = clamp(Math.round(S.z), 0, l.zoom), coarser = null;
      list.forEach(function (t) { if (t.z < wanted && (coarser === null || t.z < coarser)) coarser = t.z; });
      used[l.id] = {name: l.id, layer: l, map: true, coarser: coarser};
      return {cells: list, used: used};
    }
    var gz = clamp(Math.round(S.z), 0, l.zoom), n = Math.pow(2, gz), o = origin(), size = o.W / n;
    var c0 = Math.floor(-o.left / size), c1 = Math.floor((S.w - o.left - 0.01) / size);
    var r0 = Math.max(0, Math.floor(-o.top / size)), r1 = Math.min(n - 1, Math.floor((S.h - o.top - 0.01) / size));
    for (var r = r0; r <= r1; r++) {
      for (var c = c0; c <= c1; c++) {
        var parts = l.stack ? l.stack.map(function (name) { return {name: name, seen: true, stack: true}; })
                  : l.global ? [{name: null, seen: true}] : owners(lonOf(c / n), lonOf((c + 1) / n), latOf((r + 1) / n), latOf(r / n));
        for (var j = 0; j < parts.length; j++) {
          var p = parts[j];
          if (!p.seen) { used.none = true; continue; }
          var s = source(id, p.name), key = null;
          if (!s) continue;
          if (l.stack) {
            // Every part at the day found for the centre of the view; a
            // then-and-now side's at its own day.
            ask(s);
            used[s.name] = s;
            var day = l.then ? l.time : S.day;
            if (!day || S.imagery !== "ok") continue;
            key = day;
          } else if (l.time || l.then) {
            // A then-and-now side with no day draws nothing, never the latest.
            if (S.imagery !== "ok" || !l.time) continue;
            used[s.name] = s;
            key = l.time;
          } else if (s.step) {
            ask(s);
            var f = frameOf(s, frame);
            used[s.name] = s;
            if (!f) continue;
            key = f.key;
          } else {
            if (S.imagery !== "ok") continue;
            used[s.name] = s;
          }
          var z = Math.min(gz, s.zoom), k = Math.pow(2, gz - z);
          var cc = Math.floor(c / k), rr = Math.floor(r / k), m = Math.pow(2, z), clip = "", left = 0, right = 0;
          if (p.name && !p.stack) {
            // The imager's side of the tile, a hair wide so no seam shows.
            var P0 = lonOf(cc / m), P1 = lonOf((cc + 1) / m);
            left = Math.max(0, (p.w - P0) / (P1 - P0) * 100 - 0.1); right = Math.max(0, (P1 - p.e) / (P1 - P0) * 100 - 0.1);
            if (left > 0 || right > 0) clip = "inset(0 " + right.toFixed(2) + "% 0 " + left.toFixed(2) + "%)";
          }
          var id2 = s.name + "/" + (key || "-") + "/" + z + "/" + cc + "/" + rr + (clip ? "/" + clip : "");
          if (seen[id2]) continue;
          seen[id2] = true;
          out.push({id: id2, z: z, c: cc, r: rr, clip: clip, name: s.name, key: key,
                    url: tileUrl(s, key, z, rr, ((cc % m) + m) % m), faint: l.faint || null,
                    credit: (s.sat && D.gibs.satellites[s.sat]) || l.credit, nasa: true, cut: [left / 100, right / 100],
                    check: timed(s)});
        }
      }
    }
    return {cells: out, used: used};
  }
  function loopLength() {
    var n = 1;
    for (var k in S.inView) {
      var s = S.inView[k];
      if (s && s.name && timed(s)) { var f = framesOf(s); if (f) n = Math.max(n, f.length); }
    }
    return n;
  }
  function overSpecs(id) {
    var l = LAYERS[id];
    // Over a then-and-now side, Esri's roads and names as over World
    // Imagery: to their own zoom, credited in their own words.
    if (l && l.then) l = l.over ? {id: l.id + "-names", over: l.over, zoom: 19, grey: true, credit: l.overCredit} : null;
    return ((l && l.over) || []).map(function (template, j) {
      return {key: "o" + j, cells: xyzCells(l, template, l.id + "+" + j), visible: true, z: j};
    });
  }
  function tiles(moving) {
    // Offline, the tiles already here stay and move with the map; none are asked for.
    moving = moving || S.imagery === "offline";
    var specs = [], inView = {}, count = S.loop ? loopLength() : 1;
    for (var i = 0; i < count; i++) {
      var fi = S.loop ? i : S.frame, got = cells(S.layer, fi);
      for (var k in got.used) inView[k] = got.used[k];
      specs.push({key: "f" + fi, cells: got.cells, visible: fi === S.frame});
    }
    drawPane(panes.a, specs, moving);
    // Each layer on its side of the divider only: the compared one, under the
    // base, does not show through where the base has drawn nothing.
    if (S.compare) {
      var second = cells(S.second, S.frame);
      drawPane(panes.b, [{key: "b", cells: second.cells, visible: true}], moving);
      if (!moving) S.inViewB = second.used;
      panes.a.el.style.clipPath = "inset(0 " + Math.max(0, S.w - S.split * S.w).toFixed(1) + "px 0 0)";
      panes.b.el.style.clipPath = "inset(0 0 0 " + (S.split * S.w).toFixed(1) + "px)";
    } else {
      drawPane(panes.b, [], moving);
      S.inViewB = null;
      panes.a.el.style.clipPath = panes.b.el.style.clipPath = "";
    }
    // A map's own roads and names, over the NASA overlays, on its side of the divider.
    drawPane(panes.o, overSpecs(S.layer), moving);
    panes.o.el.style.clipPath = panes.a.el.style.clipPath;
    drawPane(panes.ob, S.compare ? overSpecs(S.second) : [], moving);
    panes.ob.el.style.clipPath = panes.b.el.style.clipPath;
    var refs = [];
    D.layers.forEach(function (l) {
      if (l.kind === "overlay" && S.refs[l.id] && S.imagery === "ok" && !S.then) refs.push({key: l.id, cells: cells(l.id, 0).cells, visible: true, z: refs.length});
    });
    drawPane(panes.r, refs, moving);
    // NASA's ocean and flood tiles, over the whole map, both sides of the divider.
    drawPane(panes.e, ensoTileSpecs(), moving);
    if (!moving) { S.inView = inView; loopWhenKnown(); }
    // Under a dark picture, its own dark space where it has no tile: the
    // page's plane showed there, white in the light theme, under the El Nino
    // composite in the dark picture's ramp. Where the picture cannot be had
    // at all, the page's plane, under the page's coastline.
    panes.a.el.classList.toggle("space", groundOf(S.layer, S.inView) === "dark");
    panes.b.el.classList.toggle("space", !!(S.compare && groundOf(S.second, S.inViewB) === "dark"));
  }

  // ---- drawing in world units -------------------------------------------------
  var geoDirty = true, geoRef = null, coastDone = 0, coastD = "", geoCopies = 0, geoLo = 0, geoHi = 0, geoExt = null;
  // Every x of the geometry passes here, which keeps the span it reaches.
  function X(lon, k) {
    var x = Math.round((mx(lon) + k) * UNIT);
    if (x < geoLo) geoLo = x;
    if (x > geoHi) geoHi = x;
    return x;
  }
  function Y(lat) { return Math.round(my(lat) * UNIT); }
  function line(points, k, close) {
    var out = "";
    for (var i = 0; i < points.length; i++) out += (i ? "L" : "M") + X(points[i][0], k) + " " + Y(points[i][1]);
    return out && close ? out + "Z" : out;
  }
  function pt(p) { return [p.lon, p.lat]; }
  function ring(c, quads) {
    var pts = [];
    for (var q = 0; q < 4; q++) {
      var r = quads[q] * NM;
      if (!(r > 0)) { pts.push([c.lon, c.lat]); continue; }
      for (var b = q * 90; b <= q * 90 + 90; b += 5) pts.push(dest(c.lon, c.lat, b, r));
    }
    return pts;
  }
  function near(x0) { return Math.round(S.x - x0); }
  // Zoomed out on a wide screen the world repeats, as the tiles and the
  // composite do. A mark shows on every copy in view: the nearest, then a
  // world either side, as many as the view is wide, with px of margin for
  // what runs past the mark.
  function copies(x0, px) {
    var W = world(), reach = Math.max(0, Math.ceil(S.w / (2 * W) + px / W - 0.5)), k = near(x0), out = [k];
    for (var j = 1; j <= reach; j++) out.push(k - j, k + j);
    return out;
  }
  // The geometry is built once, round the copy nearest the view, and drawn
  // again a world to either side as often as the view needs: it is rebuilt
  // only a quarter of a world on, so a copy is drawn wherever what it holds,
  // as far from the centre as the farthest point built, could be brought
  // into view by then.
  function geoReach() { return geoExt === null ? 0 : Math.max(0, Math.floor(S.w / (2 * world()) + 0.25 + geoExt)); }
  // The markup again, a world to either side, reach times over. Each copy
  // is markup of its own and not an SVG use element: the page's stylesheet
  // does not reach into what one of those draws, and Chrome filled every
  // region and coast on such a copy black.
  function repeated(markup, reach) {
    var out = markup;
    for (var j = 1; j <= reach; j++) {
      out += '<g transform="translate(' + j * UNIT + ' 0)">' + markup + "</g>" +
             '<g transform="translate(' + (-j * UNIT) + ' 0)">' + markup + "</g>";
    }
    return out;
  }
  function buildGeo() {
    geoDirty = false; geoRef = S.x; geoLo = Infinity; geoHi = -Infinity;
    var entered = !!S.then, h = entered ? [] : [ensoGeo()], style = D.style;
    // Entered (thennow.py), no geometry of today's is drawn over another
    // day's ground but the storm picked's: its track, forecast and winds.
    var storms = entered ? (BYID[S.selected] ? [BYID[S.selected]] : []) : STORMS;
    if (entered && !storms.length) { geoExt = null; geoCopies = geoReach(); geoG.innerHTML = ""; return; }
    if (S.show.outlook && !entered) D.outlook.forEach(function (a) {
      var k = near(mx(a.lon)), colour = style.outlook[a.level] || "var(--ink2)";
      var ran = a.alert && a.formation && lapsed(a.formation.until);
      if (a.area && a.area.length > 2) h.push('<path class="area' + (ran ? " lapsed" : "") + '" d="' + line(a.area, k, true) + '" style="fill:' + colour + ";stroke:" + colour + '"/>');
      if (a.arrow && a.arrow.length > 1) h.push('<path class="arrow" d="' + line(a.arrow, k) + '" style="stroke:' + colour + '"/>');
    });
    storms.forEach(function (st) {
      var s = st.d, k = near(st.x0);
      if (S.show.cone && s.cone && s.cone.length > 2) h.push('<path class="cone" d="' + line(s.cone, k, true) + '"/>');
      if (S.show.surge && s.surge) s.surge.forEach(function (a) { h.push('<path class="surge" d="' + line(a.ring, k, true) + '"/>'); });
      if (S.show.watches && s.watches) ORDER.forEach(function (kind) {
        s.watches.forEach(function (w) {
          if (w.kind !== kind) return;
          var d = line(w.coords, k);
          h.push('<path class="wwcase" d="' + d + '"/><path class="ww" d="' + d + '" style="stroke:' + (style.products[kind] || "var(--ink)") + '"/>');
        });
      });
    });
    if (!entered) (D.invests || []).forEach(function (v) {
      if (v.track.length > 1) h.push('<path class="investtrack" d="' + line(v.track.map(pt), near(mx(v.lon))) + '"/>');
    });
    storms.forEach(function (st) {
      var s = st.d, k = near(st.x0), past = s.track.map(pt);
      var ahead = (past.length ? [past[past.length - 1]] : []).concat(s.forecast.map(pt));
      if (past.length > 1) {
        var dp = line(past, k);
        h.push('<path class="trackcase" d="' + dp + '"/><path class="track" d="' + dp + '" style="stroke:' + st.hue + '"/>');
      }
      if (ahead.length > 1) {
        var df = line(ahead, k);
        h.push('<path class="trackcase" d="' + df + '"/><path class="forecast" d="' + df + '" style="stroke:' + st.hue + '"/>');
      }
      if (!S.show.radii) return;
      var c = centreAt(st, when(st));
      if (!c) return;
      THRESHOLDS.forEach(function (t) {
        var q = c.radii[t];
        if (!q || !(q[0] || q[1] || q[2] || q[3])) return;
        h.push('<path class="radii r' + t + '" data-radii="' + esc(st.id) + '" data-kt="' + t + '" d="' +
               line(ring(c, q), k, true) + '" style="fill:' + st.hue + ";stroke:" + st.hue + '"/>');
      });
    });
    geoExt = geoLo > geoHi ? null : Math.max(geoRef - geoLo / UNIT, geoHi / UNIT - geoRef);
    geoCopies = geoReach();
    geoG.innerHTML = repeated(h.join(""), geoCopies);
  }
  // The page's own coastline, drawn only when what lies under the marks cannot
  // be had: offline, the map's service not answering, or, under a NASA layer,
  // GIBS not answering or none of its tiles arriving.
  function baseDown() { return sideDown(S.layer, S.inView); }
  // Whether a layer's picture cannot be had, its sources in `view`: either
  // side of the divider, as baseDown says of the base.
  function sideDown(id, view) {
    if (S.imagery === "offline") return true;
    var l = LAYERS[id];
    return l && l.kind === "map" ? mapDown(id) : S.imagery === "unreachable" || nasaDown(view);
  }
  // It runs from 0 to 1 in x and moves whole worlds with the view (placeWorld),
  // so it is drawn again as many worlds either side as half the view is wide.
  function coastReach() { return Math.ceil(S.w / (2 * world())); }
  function buildCoast() {
    var want = baseDown() ? coastReach() : 0;
    if (want === coastDone) return;
    coastDone = want;
    if (!want) { coastG.innerHTML = ""; return; }
    if (!coastD) {
      var parts = [];
      D.coast.lines.forEach(function (text) {
        var v = text.split(","), x = 0, y = 0, s = "";
        for (var i = 0; i + 1 < v.length; i += 2) {
          x += +v[i]; y += +v[i + 1];
          s += (i ? "L" : "M") + Math.round(mx(x / 100) * UNIT) + " " + Math.round(my(y / 100) * UNIT);
        }
        parts.push(s);
      });
      coastD = parts.join("");
    }
    coastG.innerHTML = repeated('<path class="coast" d="' + coastD + '"/>', want);
  }
  function placeWorld() {
    var o = origin(), k = o.W / UNIT, at = function (left) {
      return "matrix(" + k + " 0 0 " + k + " " + left.toFixed(2) + " " + o.top.toFixed(2) + ")";
    };
    geoG.setAttribute("transform", at(o.left));
    // The coastline's own world is the one under the view, however far a drag has run.
    coastG.setAttribute("transform", at(o.left + Math.floor(S.x) * o.W));
  }

  // ---- drawing on the screen -------------------------------------------------
  function drawMarks() {
    var o = origin(), out = [], top = [], boxes = [];
    function sx(lon, k) { return (mx(lon) + k) * o.W + o.left; }
    function sy(lat) { return my(lat) * o.W + o.top; }
    function off(x, y, m) { return x < -m || y < -m || x > S.w + m || y > S.h + m; }
    function free(x, y, w, hgt) {
      for (var i = 0; i < boxes.length; i++) {
        var b = boxes[i];
        if (x < b[2] && b[0] < x + w && y < b[3] && b[1] < y + hgt) return false;
      }
      boxes.push([x, y, x + w, y + hgt]);
      return true;
    }
    // A label to the right of its mark, else to the left, else left out:
    // the mark keeps its place and a tap still names it. A label that must
    // keep to part of the screen says which spans it may take (fits). Each
    // line takes the room of its face: a name's 12.5 px, the rest 11 px.
    function label(x, y, r, lines, always, fits) {
      var w = 0;
      lines.forEach(function (l) { w = Math.max(w, l[0].length * (l[1] === "dl" ? 7.2 : 6.2)); });
      var hgt = lines.length * 14, top = y - 10;
      var right = x + r + 5, left = x - r - 5 - w;
      var at = (!fits || fits(right, right + w)) && free(right, top, w, hgt) ? [right, "start", right]
             : (!fits || fits(left, left + w)) && free(left, top, w, hgt) ? [left, "end", x - r - 5]
             : null;
      // One that must be written goes on the right, over what is there, and
      // keeps its room from whatever is placed after it.
      if (!at && always) { boxes.push([right, top, right + w, top + hgt]); at = [right, "start", right]; }
      if (!at) return "";
      return lines.map(function (l, i) {
        return '<text x="' + at[2].toFixed(1) + '" y="' + (y + 3 + i * 14).toFixed(1) + '" text-anchor="' + at[1] + '" class="' + l[1] + '">' + esc(l[0]) + "</text>";
      }).join("");
    }
    function cross(x, y, colour) {
      var d = "M" + (x - 6) + " " + (y - 6) + "L" + (x + 6) + " " + (y + 6) + "M" + (x + 6) + " " + (y - 6) + "L" + (x - 6) + " " + (y + 6);
      return '<path class="xcase" d="' + d + '"/><path class="x" d="' + d + '" style="stroke:' + colour + '"/>';
    }
    // Storms are placed first, so their names win any contest for the space,
    // and drawn last, over every other mark: the storm picked is named first
    // of them, so the others' names give way to its own, and drawn last of
    // them, over the others.
    // Entered (thennow.py), the ground is another day's: of today's storms,
    // outlook areas, invests and regions, only the storm picked is drawn on
    // it, so its forecast can be played over the place.
    var drawn = [], live = !S.then, picked = BYID[S.selected];
    var shown = live ? STORMS : (picked ? [picked] : []);
    shown.forEach(function (st) {
      var b = base(st), c = centreAt(st, b.t + S.scrub * HOUR);
      if (!c) return;
      copies(st.x0, 200).forEach(function (k) {
        var x = sx(c.lon, k), y = sy(c.lat);
        if (off(x, y, 200)) return;
        // Close in, the centre is a hollow ring, so the eye under it shows.
        var close = S.z >= 6, R = close ? 6 : [5, 6.5, 7.5, 8.5, 9.5, 11][clamp(c.category || 0, 0, 5)];
        free(x - R, y - R, 2 * R, 2 * R);
        drawn.push({st: st, c: c, x: x, y: y, R: R, image: b.image, close: close});
      });
    });
    drawn.sort(function (a, b) { return (b.st === picked) - (a.st === picked); });
    var over = [];
    drawn.forEach(function (m) {
      var s = m.st.d, selected = m.st.id === S.selected, pieces = [];
      if (m.image && !S.scrub && s.view && s.view.parallax) {
        var dx = (mx(s.view.parallax[0]) - mx(s.lon)) * o.W, dy = (my(s.view.parallax[1]) - my(s.lat)) * o.W;
        var nm = s.eye > 0 ? s.eye / 2 : (s.rmw > 0 ? s.rmw : 8);
        var r = nm * NM / (CIRCUMFERENCE * Math.cos(rad(m.c.lat)) / o.W);
        if (r >= 3) {
          var cx = (m.x + dx).toFixed(1), cy = (m.y + dy).toFixed(1);
          pieces.push('<circle class="ringcase" cx="' + cx + '" cy="' + cy + '" r="' + r.toFixed(1) + '"/>' +
                      '<circle class="ring" cx="' + cx + '" cy="' + cy + '" r="' + r.toFixed(1) + '"/>');
        }
      }
      // Now, the centre's own figure; ahead, the forecast's, between its
      // times. The wind is written as the centres write theirs, to 5 kt, and
      // the storm named for that wind: its category, now or to come.
      var fix = s.advisory_fix, kt = S.scrub ? m.c.wind : (fix && fix.wind != null ? fix.wind : s.wind);
      var kt5 = kt != null ? Math.round(kt / 5) * 5 : null;
      var wind = kt5 == null ? "" :
        shortAt(kt5, S.scrub ? m.c.stage : s.stage,
                S.scrub ? m.c.formed !== false : s.formed !== false) + " \u00b7 " + kt5 + " kt";
      (selected ? over : top).push(pieces.join("") + '<g class="hit" data-storm="' + esc(m.st.id) + '">' +
        '<circle class="pad" cx="' + m.x.toFixed(1) + '" cy="' + m.y.toFixed(1) + '" r="24"/>' +
        (m.close ? '<circle class="eyecase" cx="' + m.x.toFixed(1) + '" cy="' + m.y.toFixed(1) + '" r="' + m.R + '"/>' +
                   '<circle class="eye hollow" cx="' + m.x.toFixed(1) + '" cy="' + m.y.toFixed(1) + '" r="' + m.R + '" style="stroke:' + m.st.hue + '"/>'
                 : '<circle class="eye" cx="' + m.x.toFixed(1) + '" cy="' + m.y.toFixed(1) + '" r="' + m.R + '" style="fill:' + m.st.hue + '"/>') +
        label(m.x, m.y, m.R, [[s.title, "dl"], [wind + (S.scrub ? " at +" + S.scrub + " h" : ""), "dl2"]], selected) + "</g>");
    });
    top.push.apply(top, over);
    // Close in, each watch or warning and each surge area says what it is
    // beside its official colour.
    if (S.z >= 6) shown.forEach(function (st) {
      var s = st.d;
      copies(st.x0, 200).forEach(function (k) {
        if (S.show.watches && s.watches) s.watches.forEach(function (w) {
          var n = w.coords.length, a = w.coords[Math.floor((n - 1) / 2)], b = w.coords[Math.ceil((n - 1) / 2)];
          if (!a) return;
          var x = sx((a[0] + b[0]) / 2, k), y = sy((a[1] + b[1]) / 2);
          if (!off(x, y, 0)) out.push(label(x, y, 6, [[w.kind, "dl2"]]));
        });
        if (S.show.surge && s.surge) s.surge.forEach(function (area) {
          var lon = 0, lat = 0, n = area.ring.length;
          if (!n) return;
          area.ring.forEach(function (p) { lon += p[0] / n; lat += p[1] / n; });
          var x = sx(lon, k), y = sy(lat);
          if (!off(x, y, 0)) out.push(label(x, y, 4, [[area.feet + " surge", "dl2"]]));
        });
      });
    });
    // Each forecast point marked with what the storm is forecast to be there
    // (cyclones.badge): its category's number, or NHC's letter for its wind,
    // open where it is not a tropical cyclone (cyclones.hollow). A point
    // whose mark would cover a storm's marker, a name or another mark keeps
    // a plain dot, as on the dashboard's track map (storms._marks): NHC's
    // forecast has a point three hours on, under the storm's own marker at
    // the zooms the desk opens on. So does a point with no mark to give.
    var days = [];
    shown.forEach(function (st) {
      var s = st.d, selected = st.id === S.selected;
      copies(st.x0, 200).forEach(function (k) {
        s.forecast.forEach(function (p) {
          var x = sx(p.lon, k), y = sy(p.lat), cx = x.toFixed(1), cy = y.toFixed(1);
          if (off(x, y, 20)) return;
          var room = !!p.badge && free(x - 7.5, y - 7.5, 15, 15);
          if (room) {
            out.push('<g class="badge' + (p.hollow ? " hollow" : "") + '"><circle cx="' + cx + '" cy="' + cy + '" r="7.5" style="stroke:' + st.hue + '"/>' +
                     '<text x="' + cx + '" y="' + (y + 3.5).toFixed(1) + '" text-anchor="middle">' + esc(p.badge) + "</text></g>");
          } else {
            out.push('<circle class="dot" cx="' + cx + '" cy="' + cy + '" r="3.5" style="stroke:' + st.hue + '"/>');
          }
          if (selected && p.day) days.push([x, y, room ? 8 : 4, Date.parse(p.t)]);
        });
      });
    });
    // The picked storm's days (stormdesk._day), each written as the time it
    // is valid, as the slider's readout gives time: a lead counts from the
    // latest analysis, the slider from the frame on screen or the clock.
    // Written where the marks leave room, since what the storm will be
    // matters more than the hour it is that; a time not known is not written.
    days.forEach(function (d) { if (!isNaN(d[3])) out.push(label(d[0], d[1], d[2], [[zulu(d[3]), "dl2"]])); });
    // The place found or tapped: over everything, and always named, in full
    // where that fits beside it on the map, else by its first part.
    var pins = [], named = [];
    if (S.pin) copies(mx(S.pin.lon), 200).forEach(function (k) {
      var px = sx(S.pin.lon, k), py = sy(S.pin.lat);
      if (off(px, py, 30)) return;
      pins.push([px, py]);
      var text = S.pin.label, w = text.length * 7.2;
      if (w > Math.max(S.w - px, px) - 20) { text = text.split(", ")[0]; w = text.length * 7.2; }
      var right = px + 16 + w <= S.w - 4 || px - 16 - w < 4 && S.w - px >= px;
      free(right ? px + 16 : px - 16 - w, py - 10, w, 14);
      top.push('<circle class="pincase" cx="' + px.toFixed(1) + '" cy="' + py.toFixed(1) + '" r="11"/>' +
        '<circle class="pin" cx="' + px.toFixed(1) + '" cy="' + py.toFixed(1) + '" r="6"/>' +
        '<text x="' + (right ? px + 16 : px - 16).toFixed(1) + '" y="' + (py + 3).toFixed(1) +
        '" text-anchor="' + (right ? "start" : "end") + '" class="dl">' + esc(text) + "</text>");
    });
    function underPin(x, y) { return pins.some(function (p) { return Math.abs(x - p[0]) < 3 && Math.abs(y - p[1]) < 3; }); }
    var sel = BYID[S.selected];
    if (live && sel && S.show.places) {
      var c = centreAt(sel, when(sel));
      copies(sel.x0, 200).forEach(function (k) {
        sel.d.exposure.forEach(function (pl) {
          var x = sx(pl.lon, k), y = sy(pl.lat);
          if (off(x, y, 10)) return;
          var level = c ? inside(c, pl.lon, pl.lat) : 0;
          // A town under the pin is named by the pin.
          named.push([x, y]);
          out.push('<circle class="place' + (level ? " in" + level : "") + '" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="' + (level ? 5.5 : 4) + '"/>' +
                   (underPin(x, y) ? "" : label(x, y, 5, [[pl.place + (level ? ": inside " + level + " kt" : ""), "dl2"]], !!level)));
        });
      });
    }
    if (live && S.show.outlook) D.outlook.forEach(function (a) {
      var colour = D.style.outlook[a.level] || "var(--ink2)";
      var words = a.centre === "JTWC" ? (a.level || "unrated") + " potential in 24 h"
                : pct(a.chance_2day) + " in 2 days, " + pct(a.chance_7day) + " in 7";
      var lines = [[a.label, "dl2"], [words, "dl2"]];
      if (a.centre === "JTWC" && a.alert) lines.push([alertWords(a.formation && a.formation.until, true), "dl2"]);
      copies(mx(a.lon), 200).forEach(function (k) {
        var x = sx(a.lon, k), y = sy(a.lat);
        if (off(x, y, 10)) return;
        out.push('<g class="hit" data-area="' + esc(a.key) + '"><circle class="pad" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="22"/>' +
                 cross(x, y, colour) + label(x, y, 7, lines) + "</g>");
      });
    });
    if (live) (D.invests || []).forEach(function (v) {
      copies(mx(v.lon), 200).forEach(function (k) {
        var x = sx(v.lon, k), y = sy(v.lat);
        if (off(x, y, 10)) return;
        out.push('<circle class="invest" cx="' + x.toFixed(1) + '" cy="' + y.toFixed(1) + '" r="6"/>' +
                 label(x, y, 6, [[v.name + (v.wind != null ? ", " + v.wind + " kt" : ""), "dl2"]]));
      });
    });
    // The Nino regions with this week's anomalies, the regions in play while
    // they are ticked, and the one Show asked for.
    if (live) ensoLabels(sx, sy, off, label).forEach(function (words) { out.push(words); });
    // The gazetteer's towns, the most populous first and more as the view
    // closes in, wherever a name fits; capitals from the first level shown.
    // A map carries its own names, so over one the gazetteer's stand aside,
    // on its own side of the divider when two layers are compared.
    if (S.show.towns && !townsWhy()) {
      if (!BYPOP) BYPOP = PLACES.map(function (p, i) { return i; }).sort(function (a, b) { return PLACES[b][3] - PLACES[a][3]; });
      var least = S.z >= 9 ? 0 : S.z >= 8 ? 20000 : S.z >= 7 ? 60000 : S.z >= 6 ? 200000 : S.z >= 5 ? 600000 : 2000000;
      pins.forEach(function (p) { named.push(p); });
      for (var i = 0, shown = 0; i < BYPOP.length && shown < 120; i++) {
        var pl = PLACES[BYPOP[i]];
        if (pl[3] < least && !pl[6]) continue;
        var ks = copies(mx(pl[4]), 200);
        for (var j = 0; j < ks.length && shown < 120; j++) {
          var tx = sx(pl[4], ks[j]), ty = sy(pl[5]);
          if (off(tx, ty, -2) || namedAt(tx) || named.some(function (q) { return Math.abs(q[0] - tx) < 3 && Math.abs(q[1] - ty) < 3; })) continue;
          // Its name lies wholly on imagery, not across the divider on a map.
          var words = label(tx, ty, 3, [[pl[0], "dl2"]], false, function (a, b) { return !namedAt(a) && !namedAt(b); });
          if (!words) continue;
          out.push('<circle class="town" cx="' + tx.toFixed(1) + '" cy="' + ty.toFixed(1) + '" r="' + (pl[6] ? 3.2 : 2.4) + '"/>' + words);
          shown++;
        }
      }
    }
    marksG.innerHTML = out.join("") + top.join("");
  }
  // The gazetteer's town names are drawn over NASA's imagery from zoom 4; a
  // map names its own. Their box says which holds while they are not drawn:
  // compared, while neither side of the divider is imagery.
  function townsWhy() {
    if (labelledBase() && (!S.compare || labelled(S.second))) return "(the map names its own)";
    return S.z < 4 ? "(from zoom 4)" : "";
  }
  var townsSaid = null;
  function townsNote() {
    var el = $("why-towns"), text = townsWhy();
    if (el && text !== townsSaid) { el.textContent = text; townsSaid = text; }
  }

  // ---- the detail layer's day --------------------------------------------------
  // HLS is each day's Landsat and Sentinel-2 passes, swath by swath, and GIBS
  // lists every day for everywhere, so the day with an image at the centre of
  // the view is found by looking at the tile there: the newest day GIBS lists
  // first, then a day at a time back, DAYS_BACK at most. A day stepped to stays
  // while the centre still has an image on it; otherwise the newest there is
  // found again once the view settles. A day GIBS does not answer for at all
  // is no answer, not no image: the search stops there, says so, and looks
  // again in a minute.
  var DAYS_BACK = 40, NO_ANSWER = "no answer", looks = {}, dayAt = "", dayRetry = 0, quest = 0;
  function detailOn() { return S.layer === "detail" || (S.compare && S.second === "detail"); }
  function newestDay() {
    var best = null;
    (LAYERS.detail ? LAYERS.detail.stack : []).forEach(function (name) {
      var d = DOM[name];
      if (d && d.frames.length && (!best || d.frames[0].key > best)) best = d.frames[0].key;
    });
    return best;
  }
  function shiftDay(day, n) { return dayZ(stamp(day) + n * 24 * HOUR); }
  function dayText(day) { var d = new Date(stamp(day)); return d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] + " " + d.getUTCFullYear(); }
  function centreTile() {
    var z = clamp(Math.round(S.z), 0, LAYERS.detail.zoom), n = Math.pow(2, z);
    var x = (((S.x % 1) + 1) % 1) * n, y = clamp(S.y, 0, 1 - 1e-9) * n;
    return {z: z, c: Math.floor(x), r: Math.floor(y), fx: x - Math.floor(x), fy: y - Math.floor(y)};
  }
  // One imager's tile for a day, as 32 by 32 pixels; it is the tile the map
  // draws, so the browser asks for it once. A tile that does not load is
  // false: no answer, which a blank tile is not.
  function look(name, day, t) {
    var key = name + "/" + day + "/" + t.z + "/" + t.c + "/" + t.r;
    if (!looks[key]) looks[key] = new Promise(function (done) {
      var img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = function () {
        try {
          var cv = document.createElement("canvas");
          cv.width = cv.height = 32;
          var cx = cv.getContext("2d", {willReadFrequently: true});
          cx.drawImage(img, 0, 0, 32, 32);
          done(cx.getImageData(0, 0, 32, 32).data);
        } catch (err) { done(null); }
      };
      img.onerror = function () { delete looks[key]; done(false); };
      img.src = tileUrl(source("detail", name), day, t.z, t.r, t.c);
    });
    return looks[key];
  }
  function covered(px, t) {
    if (!px) return false;
    var cx = Math.floor(t.fx * 32), cy = Math.floor(t.fy * 32);
    for (var dy = -1; dy <= 1; dy++) for (var dx = -1; dx <= 1; dx++) {
      if (px[(clamp(cy + dy, 0, 31) * 32 + clamp(cx + dx, 0, 31)) * 4 + 3] > 0) return true;
    }
    return false;
  }
  // true: an image here that day. false: none, from the imagers that
  // answered; a 500 for Landsat's day while Sentinel-2 answers is still none.
  // null: none, and no imager answered at all.
  function imageOn(day, t) {
    return Promise.all(LAYERS.detail.stack.map(function (name) { return look(name, day, t); }))
      .then(function (all) {
        if (all.some(function (px) { return covered(px, t); })) return true;
        return all.every(function (px) { return px === false; }) ? null : false;
      });
  }
  function hunt(day, by, last, t, q) {
    if (q !== quest || (by < 0 ? day < last : day > last)) return Promise.resolve(null);
    return imageOn(day, t).then(function (yes) {
      if (q !== quest) return null;
      if (yes === null) return NO_ANSWER;
      return yes ? day : hunt(shiftDay(day, by), by, last, t, q);
    });
  }
  // by: 0 the newest day with an image here, -1 the one before the day shown, +1 after.
  function findDay(by) {
    var newest = newestDay(), t = centreTile(), q = ++quest;
    if (!newest) return;
    var from = by ? shiftDay(S.day || newest, by) : newest;
    S.dayState = "looking";
    requestRender();
    hunt(from, by > 0 ? 1 : -1, by > 0 ? newest : shiftDay(newest, -DAYS_BACK), t, q).then(function (day) {
      if (q !== quest) return;
      if (day === NO_ANSWER) noAnswer(!by);
      else if (day) { S.day = day; S.dayState = "ok"; S.dayStepped = !!by; }
      else if (by) S.dayState = by < 0 ? "none earlier" : "none later";
      else { S.day = null; S.dayState = "none"; }
      dirty();
    });
  }
  // GIBS did not answer here: said as that, and the place looked at again in a
  // minute, or at once if the view moves. A day already shown stays shown.
  function noAnswer(forget) {
    if (forget) S.day = null;
    S.dayState = NO_ANSWER;
    clearTimeout(dayRetry);
    dayRetry = setTimeout(function () {
      if (S.dayState === NO_ANSWER) { dayAt = ""; requestRender(); }
    }, 60000);
  }
  function dayCheck() {
    if (!detailOn() || S.imagery !== "ok") return;
    var t = centreTile(), at = [t.z, t.c, t.r, Math.floor(t.fx * 8), Math.floor(t.fy * 8)].join("/");
    if (at === dayAt) return;
    if (!newestDay()) {
      LAYERS.detail.stack.forEach(function (name) { ask(source("detail", name)); });
      return;
    }
    dayAt = at;
    if (!S.day || !S.dayStepped) { findDay(0); return; }
    var q = ++quest, day = S.day;
    imageOn(day, t).then(function (yes) {
      if (q !== quest) return;
      if (yes === null) { noAnswer(false); dirty(); }
      else if (yes) { S.dayState = "ok"; dirty(); }
      else { S.dayStepped = false; findDay(0); }
    });
  }
  function dayWords() {
    if (S.dayState === "looking") return "looking for a day with an image here";
    if (S.dayState === NO_ANSWER) return (S.day ? dayText(S.day) + "; " : "") + "NASA GIBS did not answer, so " +
      (S.day ? "no other day" : "no day") + " could be checked here; looking again in a minute";
    if (!S.day) return S.dayState === "none" && newestDay()
      ? "no image here in the " + DAYS_BACK + " days to " + dayText(newestDay()) : "asking NASA GIBS for the days";
    var age = Math.round((stamp(dayZ(Date.now())) - stamp(S.day)) / (24 * HOUR));
    return dayText(S.day) + (age > 0 ? ", " + age + (age === 1 ? " day" : " days") + " ago" : "") +
      (S.dayState === "none earlier" ? "; no earlier day with an image here" :
       S.dayState === "none later" ? "; no later day with an image here" : "");
  }
  function dayControls() {
    var box = $("days"), on = detailOn() && S.imagery === "ok";
    if (box.hidden !== !on) box.hidden = !on;
    if (!on) return;
    var words = S.dayState === "looking" ? "Looking\u2026" : S.day ? dayText(S.day) : S.dayState === "none" ? "No image here" : S.dayState === NO_ANSWER ? "No answer" : "Asking GIBS\u2026";
    if ($("day-now").textContent !== words) $("day-now").textContent = words;
    var busy = S.dayState === "looking" || !S.day, newest = newestDay();
    $("day-earlier").disabled = busy || S.dayState === "none earlier";
    $("day-later").disabled = busy || S.dayState === "none later" || !newest || S.day >= newest;
  }

  // ---- what the map is showing, in words -------------------------------------
  // Two lines show: the imagery under the selected storm, and when and where
  // that storm is drawn. Every other imager and note is one tap away.
  var pillOpen = false, pillHtml = "";
  // Anything drawn from NASA: imagery under or beside the map, its overlays,
  // and the El Nino tiles over it.
  function nasaWanted() {
    var l = LAYERS[S.layer], two = S.compare ? LAYERS[S.second] : null, k;
    if (!l || l.kind !== "map" || (two && two.kind !== "map")) return true;
    for (k in S.refs) if (S.refs[k]) return true;
    for (k in (S.enso && S.enso.tiles) || {}) if (S.enso.tiles[k]) return true;
    return false;
  }
  // The status pill's words, beside its Retry: a map whose server is not
  // answering, on either side of the divider; GIBS not answering while
  // anything drawn needs it, or none of the tiles of a side's NASA layer arriving.
  function downWord() {
    if (S.imagery === "offline") return "";
    if (S.then) return thenDown();
    if (labelledBase() && mapDown(S.layer) || S.compare && labelled(S.second) && mapDown(S.second)) return "Map unreachable.";
    if (S.imagery === "ok" && (nasaDown(S.inView) || S.compare && nasaDown(S.inViewB))) return "Imagery unreachable.";
    return S.imagery === "unreachable" && nasaWanted() ? "Imagery unreachable." : "";
  }
  // One NASA source drawn, as the pill names it: its imager and layer, and
  // the time of its frame on show, or why there is none.
  function sourceWords(s) {
    var words = (s.sat ? s.sat + " " : "") + s.layer.name + (s.note ? " (" + s.note + ")" : "");
    if (tilesDown(s)) return words + ": its tiles did not arrive";
    if (s.layer.time) return words + ": VIIRS, " + s.layer.time.slice(0, 4) + ", 500 m";
    if (!s.step) return words;
    var f = frameOf(s, S.frame), d = DOM[s.name];
    return words + (f ? ": " + (timed(s) ? utc(f.t) + ", " + ago(f.t) : f.key + ", daily")
                      : d && d.unanswered ? ": GIBS did not answer" : d && d.failed ? ": no frames from GIBS" : ": loading");
  }
  function pills() {
    var head = [], more = [], layer = LAYERS[S.layer], st = BYID[S.selected], then = !!S.then;
    var mine = st && st.d.view ? st.d.view.satellite : null;
    if (then) thenPill(head, more);
    else if (layer && layer.kind === "map") {
      // A map comes from its own service, not from GIBS, and is spoken of as that.
      if (S.imagery === "offline") head.push("Offline: street and satellite maps need the network; the tiles already loaded stay. The coastline is the page's own copy.");
      else if (mapDown(layer.id)) head.push("Map unreachable: " + layer.source + " did not answer. The coastline is the page's own copy.");
      else head.push("Map: " + layer.source + (layer.over ? ", with Esri's roads and place names" : ""));
      var drawn = S.inView[layer.id];
      if (drawn && drawn.coarser !== null && drawn.coarser !== undefined) {
        more.push(layer.source + " has nothing finer than zoom " + drawn.coarser + " for part of this view; that part is its zoom-" +
                  drawn.coarser + " tile, enlarged.");
      }
    }
    else if (S.imagery === "offline") head.push(document.querySelector("#tiles img") ? "Offline: the imagery already loaded stays; no new frames. The coastline is the page's own copy." : "Offline: no imagery. The coastline is the page's own copy.");
    else if (S.imagery === "unreachable") head.push("Imagery unreachable: NASA GIBS did not answer. The coastline is the page's own copy.");
    else if (S.imagery === "pending") head.push("Imagery: asking NASA GIBS for the latest frames");
    else {
      var lines = [];
      var stacked = false;
      Object.keys(S.inView).forEach(function (name) {
        var s = S.inView[name];
        if (!s || !s.name) return;
        if (s.layer.stack) {
          if (!stacked) lines.push("Landsat and Sentinel-2, 30 m: " + dayWords());
          stacked = true;
          return;
        }
        var words = sourceWords(s);
        if (mine && s.sat === mine) lines.unshift(words); else lines.push(words);
      });
      if (!lines.length) lines.push(layer.name + ": nothing in view");
      if (nasaDown(S.inView)) head.push("Imagery unreachable: NASA GIBS sent none of the tiles in view. The coastline is the page's own copy.");
      else { head.push(lines.shift()); more = lines; }
      if (S.inView.none) more.push("No geostationary imagery in GIBS for part of this view: no imager within 70 degrees of zenith.");
      if (layer.pixel_km && S.z > layer.zoom + 0.2) more.push("Enlarged " + Math.pow(2, S.z - layer.zoom).toFixed(1) + " times past its " + (layer.pixel_km < 1 ? Math.round(layer.pixel_km * 1000) + " m" : layer.pixel_km + " km") + " pixels.");
    }
    // The compared layer draws its own frame, which can be another time.
    if (S.compare && S.inViewB && !then) {
      var two = [], stacked2 = false;
      Object.keys(S.inViewB).forEach(function (name) {
        var s = S.inViewB[name];
        if (!s || !s.name) return;
        if (s.map) two.push(s.layer.source + (mapDown(s.name) && S.imagery !== "offline" ? " did not answer" : ""));
        else if (S.imagery !== "ok") return;
        else if (s.layer.stack) { if (!stacked2) two.push("Landsat and Sentinel-2, 30 m: " + dayWords()); stacked2 = true; }
        else two.push(sourceWords(s));
      });
      if (two.length) more.push("Compared, right of the divider: " + two.join("; ") + ".");
    }
    if (st && !then) {
      var b = base(st), v = st.d.view || {}, T = b.t + S.scrub * HOUR, toward = COMPASS[Math.round(v.toward / 22.5) % 16];
      var said = st.d.title + " drawn for " + utc(T);
      if (!centreAt(st, T)) said = st.d.title + ": nothing drawn for " + utc(T) + ", past the last forecast point";
      else if (b.image && !S.scrub) said = st.d.title + " at the image time, " + utc(T);
      if (v.satellite && b.image && !S.scrub && centreAt(st, T)) {
        said += "; eye appears " + v.offset_km + " km " + toward + " (ring)";
        more.push("Parallax: cloud tops 15 km up appear " + v.offset_km + " km " + toward + " of the centre, seen by " + v.satellite + " at zenith " + v.zenith + " degrees.");
      }
      head.push(said);
    }
    if (!then) ensoTileMore().forEach(function (l) { more.push(l); });
    var html = head.map(function (l) { return "<div>" + esc(l) + "</div>"; }).join("") +
      (more.length ? '<div class="more"' + (pillOpen ? "" : " hidden") + ">" +
        more.map(function (l) { return '<div class="muted">' + esc(l) + "</div>"; }).join("") + "</div>" +
        '<button type="button" class="pillmore" aria-expanded="' + pillOpen + '">' + (pillOpen ? "Less" : more.length + " more") + "</button>" : "");
    if (html !== pillHtml) { framePill.innerHTML = html; pillHtml = html; }
    var down = downWord();
    statusPill.hidden = !down;
    if (down && (!$("retry") || statusPill.firstChild.textContent !== down)) statusPill.innerHTML = "<span>" + down + '</span><button type="button" class="toolbtn" id="retry">Retry</button>';
  }
  // Every layer drawn is credited as its source asks, and nothing that is
  // not drawn: the words are read off the tiles on the screen, each on its
  // side of the divider, loaded and not hidden. A map is credited in its own
  // service's words; NASA's imagery, overlays and tiles by GIBS's and their
  // own, an imager's only where a tile of its is in view.
  var creditEl = $("credit"), creditSaid = "";
  // Whether the part of a tile its imager draws lies on the screen between x0 and x1.
  function shows(img, o, x0, x1) {
    var size = o.W / Math.pow(2, img._z), x = o.left + img._c * size, y = o.top + img._r * size, cut = img._cut || [0, 0];
    return x + cut[0] * size < x1 && x + size - cut[1] * size > x0 && y < S.h && y + size > 0;
  }
  function credit() {
    var said = [], o = origin(), cut = S.compare ? S.split * S.w : S.w;
    function from(pane, x0, x1) {
      var maps = [], nasa = [];
      for (var k in pane.sets) {
        var set = pane.sets[k];
        if (set.el.style.visibility === "hidden") continue;
        for (var id in set.imgs) {
          var t = set.imgs[id], list = t._nasa ? nasa : maps;
          if (!t._credit || !t.complete || !t.naturalWidth || t.style.visibility === "hidden" || !shows(t, o, x0, x1)) continue;
          if (list.indexOf(t._credit) < 0) list.push(t._credit);
        }
      }
      maps.sort().forEach(function (w) { if (said.indexOf(w) < 0) said.push(w); });
      if (nasa.length && said.indexOf(D.gibs.acknowledge) < 0) said.push(D.gibs.acknowledge);
      nasa.sort().forEach(function (w) { if (said.indexOf(w) < 0) said.push(w); });
    }
    from(panes.a, 0, cut);
    from(panes.o, 0, cut);
    if (S.compare) { from(panes.b, cut, S.w); from(panes.ob, cut, S.w); }
    from(panes.r, 0, S.w);
    from(panes.e, 0, S.w);
    var text = said.join(" ");
    if (text !== creditSaid) { creditEl.textContent = text; creditSaid = text; }
  }
  function scrubText() {
    var st = BYID[S.selected];
    if (!st) return S.scrub ? "+" + S.scrub + " h" : "Now";
    var T = when(st);
    if (!S.scrub) return "Now: " + utc(T);
    return "+" + S.scrub + " h: " + utc(T) + (centreAt(st, T) ? "" : ", past the forecast");
  }

  // ---- the frame loop ------------------------------------------------------
  var raf = 0, anim = 0, loopTimer = 0;
  function requestRender() { if (!raf) raf = requestAnimationFrame(function () { raf = 0; render(); }); }
  function dirty() { geoDirty = true; requestRender(); }
  function measure() {
    var r = map.getBoundingClientRect();
    S.w = Math.max(1, r.width); S.h = Math.max(1, r.height);
    svgEl.setAttribute("viewBox", "0 0 " + S.w + " " + S.h);
  }
  function render() {
    S.z = clamp(S.z, MINZ, maxZoom());
    var W = world(), half = S.h / 2 / W;
    S.y = W > S.h ? clamp(S.y, half, 1 - half) : 0.5;
    tiles(anim !== 0);
    drawComposite();
    // Close in, the rings and cone are outlines, so the imagery shows through.
    svgEl.classList.toggle("close", S.z >= 6);
    if (geoDirty || geoRef === null || Math.abs(S.x - geoRef) > 0.25 || geoReach() !== geoCopies) buildGeo();
    buildCoast();
    placeWorld();
    drawMarks();
    pills();
    townsNote();
    ensoLegend();
    ensoTileLegend();
    credit();
    if (!anim && !pointers.size) dayCheck();
    dayControls();
    if (S.then) thenRender();
    scrubRead.textContent = scrubText();
    showPlay();
    divider.hidden = !S.compare;
    if (S.compare) divider.style.left = (S.split * S.w).toFixed(1) + "px";
    $("loop").setAttribute("aria-pressed", S.loop ? "true" : "false");
  }
  function settle() {
    if (S.x < 0 || S.x >= 1) { S.x -= Math.floor(S.x); geoDirty = true; }
    render();
    carryView();
    googleRelink();
  }
  function animate(to, ms) {
    cancelAnimationFrame(anim);
    var from = {x: S.x, y: S.y, z: S.z}, t0 = 0, dur = ms || 650;
    function step(now) {
      if (!t0) t0 = now;
      var f = clamp((now - t0) / dur, 0, 1), e = f < 0.5 ? 2 * f * f : 1 - Math.pow(-2 * f + 2, 2) / 2;
      S.x = from.x + (to.x - from.x) * e; S.y = from.y + (to.y - from.y) * e; S.z = from.z + (to.z - from.z) * e;
      render();
      if (f < 1) anim = requestAnimationFrame(step); else { anim = 0; settle(); }
    }
    anim = requestAnimationFrame(step);
  }
  function toWorld(px, py) { var W = world(); return {x: S.x + (px - S.w / 2) / W, y: S.y + (py - S.h / 2) / W}; }
  function zoomBy(dz, px, py) {
    px = px == null ? S.w / 2 : px; py = py == null ? S.h / 2 : py;
    var a = toWorld(px, py), z = clamp(S.z + dz, MINZ, maxZoom()), W = TILE * Math.pow(2, z);
    animate({x: a.x - (px - S.w / 2) / W, y: a.y - (py - S.h / 2) / W, z: z}, 300);
  }
  function setLoop(on) {
    clearTimeout(loopTimer);
    S.loopWanted = false;
    S.loop = !!on && loopLength() > 1;
    if (S.loop && S.playing) setPlay(false);
    S.frame = S.loop ? loopLength() - 1 : 0;
    if (S.loop) loopTimer = setTimeout(tick, 450);
    dirty();
    return S.loop;
  }
  function tick() {
    if (!S.loop) return;
    var n = loopLength();
    S.frame = S.frame > 0 ? Math.min(S.frame - 1, n - 1) : n - 1;
    dirty();
    loopTimer = setTimeout(tick, S.frame === 0 ? 1400 : 450);
  }
  // A loop waiting on GIBS's frames: one handed across a load, or kept while
  // a place was entered. It runs once the map is drawn with the frames in
  // view; the reader's own Loop, pressed meanwhile, comes first.
  function loopWhenKnown() {
    if (S.loopWanted && loopLength() > 1) setLoop(true);
  }

  // ---- playing the forecast --------------------------------------------------
  // Play runs the forecast slider on an hour at a time, PLAY_MS an hour, from
  // where it stands to the end of the forecast of the storm picked (of every
  // storm on the map, with none picked), and stops there; at the end already,
  // it starts again from now, and with no forecast ahead to play it is
  // greyed. The map stays the reader's as it runs: they pan, zoom, change
  // layer, pick another storm or enter a place. Play and the satellite loop,
  // which would carry the storms back and forth under it, take turns: the
  // one the reader started last runs. The slider moved by hand, or an
  // address followed, stops it.
  var PLAY_MS = 110, playTimer = 0;
  function playEnd() {
    var st = BYID[S.selected], end = null;
    (st ? [st] : STORMS).forEach(function (s) {
      var n = s.nodes;
      if (!n.length) return;
      var h = Math.floor((n[n.length - 1].t - base(s).t) / HOUR);
      end = end === null ? h : Math.max(end, h);
    });
    return clamp(end === null ? 0 : end, 0, +scrub.max);
  }
  function setScrub(h) { S.scrub = h; scrub.value = String(h); dirty(); carryView(); }
  function setPlay(on) {
    clearTimeout(playTimer); playTimer = 0;
    var end = playEnd();
    S.playing = !!on && end > 0;
    if (S.playing) {
      S.loopWanted = false;
      if (S.loop) setLoop(false);
      if (S.scrub >= end) setScrub(0);
      playTimer = setTimeout(playStep, PLAY_MS);
    }
    showPlay();
    return S.playing;
  }
  // The button says what pressing it does, greyed with nothing to play.
  function showPlay() {
    var text = S.playing ? "Pause" : "Play", off = !S.playing && playEnd() === 0;
    if (playBtn.textContent !== text) playBtn.textContent = text;
    if (playBtn.disabled !== off) playBtn.disabled = off;
  }
  function playStep() {
    if (!S.playing) return;
    var end = playEnd();
    setScrub(Math.min(S.scrub + 1, end));
    if (S.scrub >= end) setPlay(false);
    else playTimer = setTimeout(playStep, PLAY_MS);
  }

  // ---- choosing what to show ------------------------------------------------------
  // The storm picked, or none (null); a name the page has no storm by
  // changes nothing. Picked while Play runs past the end of its forecast,
  // Play starts again from now, as pressed at the end it does.
  function select(id) {
    if (id !== null && !own(BYID, id)) return;
    S.selected = id;
    if (S.playing && S.scrub >= playEnd()) setScrub(0);
    document.querySelectorAll("#panel section.storm").forEach(function (sec) { sec.hidden = sec.getAttribute("data-storm") !== id; });
    document.querySelectorAll("#panel .stormrow").forEach(function (row) { row.setAttribute("aria-current", row.getAttribute("data-row") === id ? "true" : "false"); });
    dirty();
    carryView();
  }
  function tab(section, name) {
    section.querySelectorAll("[data-tab]").forEach(function (b) { b.setAttribute("aria-selected", b.getAttribute("data-tab") === name ? "true" : "false"); });
    section.querySelectorAll("[data-pane]").forEach(function (p) { p.hidden = p.getAttribute("data-pane") !== name; });
  }
  // A layer whose servers refuse a page opened from a file is offered only
  // when the page is served. Its button stays, dimmed, and says why when
  // pressed, where a tablet shows it; the compare menu greys it out.
  function servedWhy(l) {
    return l.name + " needs this page served: its servers refuse a page opened from a file. " +
           "Run python track.py --serve (add --lan for a tablet) and open the address it prints.";
  }
  function unserved() {
    D.layers.forEach(function (l) {
      if (!l.served_only || servedOnly(location.protocol)) return;
      var b = $("layer-" + l.id), o = document.querySelector('#compare-layer option[value="' + l.id + '"]');
      if (b) { b.setAttribute("aria-disabled", "true"); b.title = servedWhy(l); }
      if (o) { o.disabled = true; o.textContent = l.name + " (needs the page served)"; }
    });
  }
  function pressLayer(id) {
    var ok = setLayer(id), l = LAYERS[id], note = $("layer-note");
    if (note && !ok && l && l.served_only) note.textContent = servedWhy(l);
    return ok;
  }
  // The layer shown. Whatever changes it, a button, Swap, a found address or
  // a storm's own imagery, the reason a layer could not be had is done with.
  function setLayer(id) {
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    var l = LAYERS[id], note = $("layer-note");
    if (!l || (l.kind !== "imagery" && l.kind !== "map")) return false;
    if (l.served_only && !servedOnly(location.protocol)) return false;
    if (note) note.textContent = "";
    if (S.compare && id === S.second) S.second = S.layer;
    S.layer = id;
    if (id === "detail") { S.dayStepped = false; dayAt = ""; }
    document.querySelectorAll("[data-layer]").forEach(function (b) { b.setAttribute("aria-pressed", b.getAttribute("data-layer") === id ? "true" : "false"); });
    $("compare-layer").value = S.second;
    dirty();
    return true;
  }
  // Compare pressed: the button as it shows. While a place is entered the
  // two dates are compared, but the button shows the comparison there was
  // before, and a press turns that one.
  function pressCompare() { setCompare(!(S.then ? S.then.back.compare : S.compare)); }
  function setCompare(on) {
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    S.compare = !!on;
    if (S.compare && S.second === S.layer) S.second = S.layer === "infrared" ? "geocolor" : "infrared";
    $("compare").setAttribute("aria-pressed", S.compare ? "true" : "false");
    $("compare-layer").value = S.second;
    dirty();
    return S.compare;
  }
  function flyToArea(key) {
    var a = D.outlook.filter(function (x) { return x.key === key; })[0];
    if (!a) return false;
    animate({x: mx(a.lon) + near(mx(a.lon)), y: my(a.lat), z: Math.max(S.z, 5)});
    return true;
  }
  function flyTo(id) {
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    if (String(id).indexOf("area:") === 0) return flyToArea(String(id).slice(5));
    var st = BYID[id];
    if (!st) return false;
    select(id);
    if (!(st.d.view && st.d.view.satellite) && LAYERS[S.layer].satellites) setLayer("truecolor");
    var c = centreAt(st, when(st)) || {lon: st.d.lon, lat: st.d.lat};
    animate({x: mx(c.lon) + near(mx(c.lon)), y: my(c.lat), z: 7});
    var box = map.getBoundingClientRect();
    if (box.top < 0 || box.bottom > window.innerHeight) map.scrollIntoView({block: "start", behavior: "smooth"});
    return true;
  }
  function fit(instant) {
    var xs = [], ys = [], ref = null;
    function add(lon, lat) { var x = mx(lon); if (ref === null) ref = x; xs.push(x + Math.round(ref - x)); ys.push(my(lat)); }
    STORMS.forEach(function (st) { var c = centreAt(st, when(st)) || {lon: st.d.lon, lat: st.d.lat}; add(c.lon, c.lat); });
    if (!xs.length) D.outlook.forEach(function (a) { add(a.lon, a.lat); });
    var to = {x: mx(-60), y: my(20), z: 3};
    if (xs.length) {
      var x0 = Math.min.apply(null, xs), x1 = Math.max.apply(null, xs), y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
      var z = Math.log(Math.min(S.w / Math.max((x1 - x0) * TILE, 1e-9), S.h / Math.max((y1 - y0) * TILE, 1e-9))) / Math.LN2 - 0.7;
      to = {x: (x0 + x1) / 2, y: (y0 + y1) / 2, z: clamp(z, MINZ, 5)};
    }
    if (instant) { S.x = to.x; S.y = to.y; S.z = to.z; settle(); } else animate(to);
  }
  // The map page opens on the whole planet across the width with the Pacific
  // in the middle: the ocean El Nino lives in, and every coast it reaches.
  function planet() {
    S.x = mx(-150); S.y = my(0);
    S.z = clamp(Math.log(S.w / TILE) / Math.LN2, Math.max(MINZ, 1), maxZoom());
    settle();
  }
  // A place or a view in the address: #at=lat,lon opens Here there, and
  // #view=lat,lon,zoom shows that view, with the storm picked and the
  // forecast's hour after it as the other page hands them across
  // (&storm=id&hour=n). Anything else is no place at all.
  function parseHash(text) {
    var m = /^#(at|view)=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)(?:,(-?\d+(?:\.\d+)?))?(?:&storm=([a-z0-9]{1,16}))?(?:&hour=(\d{1,3}))?$/.exec(text || "");
    if (!m || (m[1] === "at") !== (m[4] === undefined) || (m[1] === "at" && (m[5] || m[6]))) return null;
    var lat = +m[2], lon = +m[3];
    if (Math.abs(lat) > 90 || Math.abs(lon) > 360) return null;
    // A longitude inside the world is kept as written: wrap() would make
    // -77.04 into -77.04000000000002.
    if (lon < -180 || lon >= 180) lon = wrap(lon);
    if (m[1] === "at") return {at: [lat, lon]};
    var h = {view: [lat, lon, clamp(+m[4], 1, 19)]};
    if (m[5]) h.storm = m[5];
    if (m[6]) h.hour = +m[6];
    return h;
  }
  function viewHash() {
    return "#view=" + latOf(S.y).toFixed(4) + "," + wrap(lonOf(S.x)).toFixed(4) + "," + S.z.toFixed(2) +
      (S.selected ? "&storm=" + S.selected : "") + (S.scrub ? "&hour=" + S.scrub : "");
  }
  // The other page's link opens it on this view.
  function carryView() {
    var hash = viewHash();
    document.querySelectorAll("a[data-carry]").forEach(function (a) {
      a.setAttribute("href", a.getAttribute("data-carry") + hash);
    });
  }
  // The street's address and then and now's open their own views; any
  // other place or view leaves them. A link passed through a mail or chat
  // app can come back with its commas and ampersands written out (%2C,
  // %26): it is read as typed.
  function applyHash(text) {
    text = text || "";
    try { text = decodeURIComponent(text); } catch (err) { /* no escape: as it is */ }
    if (/^#street=/.test(text) && streetHashApply(text)) return true;
    if (/^#then=/.test(text) && thenHashApply(text)) return true;
    var h = parseHash(text);
    if (!h) return false;
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    // An address followed, as the slider moved by hand, stops Play.
    if (S.playing) setPlay(false);
    cancelAnimationFrame(anim); anim = 0;
    var p = h.at || h.view;
    S.x = mx(p[1]); S.y = my(p[0]); S.z = clamp(h.view ? p[2] : 10, MINZ, maxZoom());
    settle();
    if (h.at) hereAt(p[1], p[0]);
    if (h.storm && own(BYID, h.storm)) select(h.storm);
    if (h.hour != null) setScrub(clamp(h.hour, 0, +scrub.max));
    return true;
  }
  function readToggles() {
    document.querySelectorAll("[data-show]").forEach(function (box) { S.show[box.getAttribute("data-show")] = box.checked; });
    document.querySelectorAll("[data-ref]").forEach(function (box) { S.refs[box.getAttribute("data-ref")] = box.checked; });
  }

  // ---- finding a place ------------------------------------------------------------
  // The gazetteer ships in the page as the atlas ships it: [name, country,
  // region, population, lon, lat, capital], most populous first. Matching
  // ignores case and accents, so "sao paulo" finds Sao Paulo with its tilde.
  var PLACES = D.places || [], FOLDED = null, BYPOP = null, found = [], active = -1;
  var findForm = $("findform"), findBox = $("find"), findList = $("find-list"), findNote = $("find-note");
  function fold(text) {
    return String(text || "").normalize("NFD").replace(/[\u0300-\u036f]/g, "")
      .toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  }
  function folded() {
    return FOLDED || (FOLDED = PLACES.map(function (p) { return [fold(p[0]), fold(p[2]), fold(p[1])]; }));
  }
  function named(p) {
    var bits = [p[0]];
    if (p[2] && p[2] !== p[0]) bits.push(p[2]);
    if (p[1]) bits.push(p[1]);
    return bits.join(", ");
  }
  function where(lon, lat) {
    var w = wrap(lon);
    return Math.abs(lat).toFixed(2) + (lat >= 0 ? "N" : "S") + " " + Math.abs(w).toFixed(2) + (w < 0 ? "W" : "E");
  }
  function people(n) { return n > 0 ? n.toLocaleString("en-US") : ""; }
  // The nearest town's people, named unless Here is that town: an address in
  // Lima is not home to all of Lima.
  function peopleFact(label, place) {
    return (String(label).split(", ")[0] === place.name ? "" : esc(place.name) + ": ") +
      people(place.population) + " people (Natural Earth)";
  }
  // Latitude first, as positions are written: "18.0N 76.8W", "18.0, -76.8".
  function coordinate(text) {
    var m = /^\s*([+-]?\d{1,2}(?:\.\d+)?)\s*\u00b0?\s*([NSns])?\s*(?:[,;]\s*|\s+)([+-]?\d{1,3}(?:\.\d+)?)\s*\u00b0?\s*([EWew])?\s*$/.exec(text);
    if (!m) return null;
    var lat = +m[1], lon = +m[3];
    if (m[2] && /s/i.test(m[2])) lat = -Math.abs(lat);
    if (m[4] && /w/i.test(m[4])) lon = -Math.abs(lon);
    if (Math.abs(lat) > 90 || Math.abs(lon) > 180) return null;
    return {kind: "point", label: where(lon, lat), sub: "A position", lon: lon, lat: lat, zoom: 9};
  }
  function gather(groups, key, i, rank) {
    var g = groups[key] || (groups[key] = {rank: rank, first: i, members: []});
    g.rank = Math.min(g.rank, rank);
    g.members.push(i);
  }
  // A region's or a country's places within reach of its largest, so islands
  // half a world away do not set the view.
  function extent(g, reach) {
    var p0 = PLACES[g.first], x0 = mx(p0[4]), xs = [], ys = [];
    g.members.forEach(function (i) {
      var p = PLACES[i];
      if (km(p0[4], p0[5], p[4], p[5]) > reach) return;
      var x = mx(p[4]);
      xs.push(x + Math.round(x0 - x)); ys.push(my(p[5]));
    });
    return {x0: Math.min.apply(null, xs), x1: Math.max.apply(null, xs),
            y0: Math.min.apply(null, ys), y1: Math.max.apply(null, ys)};
  }
  function find(text) {
    var c = coordinate(text);
    if (c) return [c];
    var q = fold(text);
    if (q.length < 2) return [];
    var F = folded(), out = [], regions = {}, countries = {};
    for (var i = 0; i < PLACES.length; i++) {
      var f = F[i], p = PLACES[i];
      var r = f[0] === q ? 0 : f[0].indexOf(q) === 0 ? 1 : (" " + f[0]).indexOf(" " + q) >= 0 ? 2 : -1;
      if (r >= 0) out.push({kind: "town", rank: r, weight: p[3], label: named(p),
                            sub: [p[6] ? "Capital" : "Town", p[3] ? people(p[3]) + " people" : ""].filter(Boolean).join(", "),
                            lon: p[4], lat: p[5], zoom: 10, place: i});
      if (f[1] && f[1] !== f[0] && f[1].indexOf(q) === 0) gather(regions, p[2] + "|" + p[1], i, f[1] === q ? 0 : 1);
      if (f[2] && f[2].indexOf(q) === 0) gather(countries, p[1], i, f[2] === q ? 0 : 1);
    }
    function add(groups, kind, reach) {
      Object.keys(groups).forEach(function (k) {
        var g = groups[k], p = PLACES[g.first], n = g.members.length;
        out.push({kind: kind, rank: g.rank, weight: p[3],
                  label: kind === "country" ? p[1] : p[2] + ", " + p[1],
                  sub: (kind === "country" ? "Country" : "Region") + ", " + n + (n === 1 ? " place" : " places") + " in the gazetteer",
                  lon: p[4], lat: p[5], zoom: 7, box: extent(g, reach), place: g.first});
      });
    }
    add(regions, "region", 1500);
    add(countries, "country", 2500);
    out.sort(function (a, b) { return a.rank - b.rank || b.weight - a.weight; });
    return out.slice(0, 8);
  }
  function viewFor(r) {
    if (!r.box) { var x = mx(r.lon); return {x: x + near(x), y: my(clamp(r.lat, -85, 85)), z: Math.min(r.zoom, maxZoom())}; }
    var b = r.box, cx = (b.x0 + b.x1) / 2;
    var z = Math.log(Math.min(S.w / Math.max((b.x1 - b.x0) * TILE, 1e-9),
                              S.h / Math.max((b.y1 - b.y0) * TILE, 1e-9))) / Math.LN2 - 0.5;
    // A street or an address found by the geocoder goes as close as the map
    // does; a region or a country of the gazetteer's stops at 9.
    return {x: cx + near(cx), y: (b.y0 + b.y1) / 2, z: clamp(z, 3, r.deep ? maxZoom() : 9)};
  }
  function pin(lon, lat, text) {
    S.pin = {lon: wrap(lon), lat: clamp(lat, -85, 85), label: text};
    // The composite cell under the pin is outlined in the geometry.
    dirty();
  }
  function go(r) {
    if (!r) return false;
    // The geocoder's row sends the words, and lists what comes back.
    if (r.kind === "search") { geocode(r.q); return true; }
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    closeList();
    findBox.value = r.label;
    findBox.blur();
    // NASA's imagery stops short of a street: an address opens on the street map.
    if (r.deep && LAYERS[S.layer] && LAYERS[S.layer].kind === "imagery") setLayer("streets");
    hereAt(r.lon, r.lat, r.kind === "town" || r.kind === "point" || r.kind === "address" ? r.label : named(PLACES[r.place]));
    animate(viewFor(r));
    var box = map.getBoundingClientRect();
    if (box.top < 0 || box.bottom > window.innerHeight) map.scrollIntoView({block: "start", behavior: "smooth"});
    return true;
  }
  function closeList() {
    findList.hidden = true; findNote.hidden = true;
    findBox.setAttribute("aria-expanded", "false");
    findBox.removeAttribute("aria-activedescendant");
  }
  function highlight(i) {
    active = i;
    findList.querySelectorAll("[role=option]").forEach(function (li, j) {
      li.setAttribute("aria-selected", j === i ? "true" : "false");
      if (j === i && li.scrollIntoView) li.scrollIntoView({block: "nearest"});
    });
    if (i >= 0) findBox.setAttribute("aria-activedescendant", "find-opt-" + i);
  }
  function showFound() {
    active = found.length ? 0 : -1;
    findList.innerHTML = found.map(function (r, i) {
      return '<li role="option" id="find-opt-' + i + '" data-find="' + i + '" aria-selected="' + (i === 0) + '">' +
        '<span class="findname">' + esc(r.label) + '</span><span class="findsub">' + esc(r.sub) + "</span></li>";
    }).join("");
    findList.hidden = !found.length;
    findBox.setAttribute("aria-expanded", found.length ? "true" : "false");
    if (found.length) findBox.setAttribute("aria-activedescendant", "find-opt-0");
    else findBox.removeAttribute("aria-activedescendant");
  }
  function listFound(text, asked) {
    // New words set aside an answer still on its way for the old ones.
    geocoding++;
    found = find(text);
    // Last, after the gazetteer's own: the offer to ask Esri's geocoder.
    var offer = searchRow(text);
    if (offer) found.push(offer);
    showFound();
    var say = !found.length && (asked || fold(text).length >= 3);
    findNote.hidden = !say;
    findNote.textContent = say ? "Nothing called \u201c" + text.trim() + "\u201d in the desk\u2019s gazetteer of " +
      PLACES.length.toLocaleString("en-US") + " places. Try a town, a region, a country, or a position such as 18.0N 76.8W." : "";
  }
  findBox.addEventListener("input", function () { listFound(findBox.value, false); });
  findBox.addEventListener("keydown", function (e) {
    if (e.key === "ArrowDown" && found.length) { highlight(Math.min(active + 1, found.length - 1)); e.preventDefault(); }
    else if (e.key === "ArrowUp" && found.length) { highlight(Math.max(active - 1, 0)); e.preventDefault(); }
    else if (e.key === "Escape") closeList();
  });
  findForm.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!found.length || findList.hidden) listFound(findBox.value, true);
    if (found.length) go(found[Math.max(0, active)]);
  });
  findList.addEventListener("click", function (e) {
    var li = e.target.closest ? e.target.closest("[data-find]") : null;
    if (li) go(found[+li.getAttribute("data-find")]);
  });
  document.addEventListener("pointerdown", function (e) {
    if (!(e.target.closest && e.target.closest("#findform"))) closeList();
  });

  // ---- here: what the storms mean for one point ----------------------------------
  // Read from each storm's own payload: its advisory position, its official
  // forecast hour by hour with the wind radii (the path the exposure table is
  // computed from), its cone, watches and warnings and surge areas, and the
  // outlook. The wind rules are Python's exposure.inside, rule for rule, so a
  // town in a storm's exposure table gets the same times here.
  var COMPASS8 = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"];
  function within(p, lon, lat, quads) {
    // At the centre is inside, as in Python; a millimetre allows for the
    // longitude having been written about the storm's own meridian.
    var d = km(p.lon, p.lat, lon, lat);
    if (d < 1e-6) return true;
    return d <= quads[Math.floor(bearing(p.lon, p.lat, lon, lat) / 90) % 4] * NM;
  }
  function insideAt(p, lon, lat, t) {
    var r = p.radii || {}, quads = r[t];
    if (quads) return within(p, lon, lat, quads);
    if (p.wind != null && p.wind < +t) return false;
    for (var i = 0; i < THRESHOLDS.length; i++) {
      var o = THRESHOLDS[i], known = r[o];
      if (!known) continue;
      if (+o < +t && !within(p, lon, lat, known)) return false;
      if (+o > +t && within(p, lon, lat, known)) return true;
    }
    return null;
  }
  function frameLon(lon, ref) { return lon + 360 * Math.round((ref - lon) / 360); }
  function inRing(ring, lon, lat) {
    if (!ring || ring.length < 3) return false;
    var x = frameLon(lon, ring[0][0]), inside = false;
    for (var i = 0, j = ring.length - 1; i < ring.length; j = i++) {
      var xi = ring[i][0], yi = ring[i][1], xj = ring[j][0], yj = ring[j][1];
      if ((yi > lat) !== (yj > lat) && x < (xj - xi) * (lat - yi) / (yj - yi) + xi) inside = !inside;
    }
    return inside;
  }
  // Kilometres to the nearest point of a line, on a plane about the point:
  // close enough within the few hundred kilometres it is asked about.
  function toLine(coords, lon, lat) {
    var kx = 111.32 * Math.cos(rad(lat)), ky = 110.57, best = Infinity, prev = null;
    coords.forEach(function (c) {
      var q = [(frameLon(c[0], lon) - lon) * kx, (c[1] - lat) * ky];
      if (prev) {
        var dx = q[0] - prev[0], dy = q[1] - prev[1], L = dx * dx + dy * dy;
        var f = L ? clamp(-(prev[0] * dx + prev[1] * dy) / L, 0, 1) : 0;
        best = Math.min(best, Math.hypot(prev[0] + f * dx, prev[1] + f * dy));
      } else best = Math.hypot(q[0], q[1]);
      prev = q;
    });
    return best;
  }
  function nearestPlace(lon, lat) {
    var best = null;
    for (var i = 0; i < PLACES.length; i++) {
      var p = PLACES[i];
      if (Math.abs(p[5] - lat) > 8) continue;
      if (Math.abs(((p[4] - lon + 540) % 360) - 180) * Math.cos(rad(lat)) > 10) continue;
      var d = km(lon, lat, p[4], p[5]);
      if (!best || d < best.km) best = {km: d, p: p};
    }
    return best;
  }
  function hereFor(lon, lat) {
    lon = wrap(lon);
    var place = nearestPlace(lon, lat), local = place && place.km <= 25 ? place.p : null;
    var out = {lon: lon, lat: lat, place: place ? {name: place.p[0], region: place.p[2], country: place.p[1],
               population: place.p[3], km: place.km} : null, storms: [], areas: []};
    STORMS.forEach(function (st) {
      var s = st.d, fx = s.advisory_fix || {t: s.t, lon: s.lon, lat: s.lat, wind: s.wind};
      var r = {id: s.id, title: s.title, centre: s.centre, advisory: s.advisory, hue: st.hue,
               now: fx.t, now_km: km(fx.lon, fx.lat, lon, lat), bearing: bearing(lon, lat, fx.lon, fx.lat),
               now_wind: fx.wind, closest_km: null, closest: null, closest_wind: null, receding: false,
               arrival: {}, unknown: [], cone: null, watches: [], surge: [], official: null};
      // As far as the exposure table looks: the widest gale radius anywhere
      // on the forecast, plus a degree.
      var line = s.path.filter(function (p) { return p.hour != null && p.hour >= 0; });
      // Without an official forecast there is nothing to say of where it goes
      // or when its wind arrives: the analysed position alone is not one.
      r.forecast = line.some(function (p) { return p.hour > 0; });
      if (!r.forecast) line = [];
      var gale = 0, south = Infinity, north = -Infinity, best = null, unknown = {};
      line.forEach(function (p) {
        var q = (p.radii || {})["34"];
        if (q) gale = Math.max.apply(null, [gale].concat(q));
        south = Math.min(south, p.lat); north = Math.max(north, p.lat);
        var d = km(p.lon, p.lat, lon, lat);
        if (!best || d < best.km) best = {km: d, p: p};
      });
      var reach = gale * NM + 111.2, pad = reach / 111.2;
      r.gale = gale > 0;
      r.reached = lat >= south - pad && lat <= north + pad &&
                  line.some(function (p) { return km(p.lon, p.lat, lon, lat) <= reach; });
      if (r.reached) line.forEach(function (p) {
        THRESHOLDS.forEach(function (t) {
          if (r.arrival[t]) return;
          var got = insideAt(p, lon, lat, t);
          if (got) r.arrival[t] = p.t;
          else if (got === null) unknown[t] = true;
        });
      });
      if (best) {
        r.closest_km = best.km; r.closest = best.p.t; r.closest_wind = best.p.wind;
        r.receding = best.p === line[0];
      }
      r.unknown = THRESHOLDS.filter(function (t) { return unknown[t] && !r.arrival[t]; }).map(Number);
      if (s.cone && s.cone.length > 2) r.cone = inRing(s.cone, lon, lat);
      // A product that could not be fetched is said to be missing, never left
      // to read as nothing in effect.
      r.lost = ["watches", "cone", "surge"].filter(function (k) { return (s.products || {})[k] === "unavailable"; });
      r.in_effect = s.in_effect || {};
      var byKind = {};
      (s.watches || []).forEach(function (w) {
        var d = toLine(w.coords, lon, lat);
        if (!(w.kind in byKind) || d < byKind[w.kind]) byKind[w.kind] = d;
      });
      ORDER.slice().reverse().concat(Object.keys(byKind).filter(function (k) { return ORDER.indexOf(k) < 0; }))
        .forEach(function (kind) { if (kind in byKind && byKind[kind] <= 300) r.watches.push({kind: kind, km: byKind[kind]}); });
      (s.surge || []).forEach(function (a) { if (inRing(a.ring, lon, lat)) r.surge.push({label: a.label, feet: a.feet}); });
      // The centre's own chances, where its product names the town the point is in.
      if (local && s.winds && s.winds.rows) {
        var name = fold(local[0]), got = {};
        s.winds.rows.forEach(function (row) { if (fold(row.place) === name) got[row.threshold] = row.total; });
        if (Object.keys(got).length) r.official = {place: local[0], chances: got,
          hours: s.winds.hours && s.winds.hours.length ? s.winds.hours[s.winds.hours.length - 1] : null,
          advisory: s.winds.advisory, issued: s.winds.issued};
      }
      out.storms.push(r);
    });
    out.storms.sort(function (a, b) { return (a.closest_km == null ? 1e9 : a.closest_km) - (b.closest_km == null ? 1e9 : b.closest_km); });
    D.outlook.forEach(function (a) {
      var polygon = a.area && a.area.length > 2, inside = polygon && inRing(a.area, lon, lat);
      var d = inside ? 0 : polygon ? toLine(a.area, lon, lat) : km(a.lon, a.lat, lon, lat);
      if (inside || d <= (polygon ? 300 : 600)) out.areas.push({key: a.key, centre: a.centre, label: a.label,
        inside: !!inside, km: d, polygon: !!polygon, chance_2day: a.chance_2day, chance_7day: a.chance_7day,
        potential: a.potential, alert: a.alert, until: a.formation ? a.formation.until : ""});
    });
    return out;
  }
  function soon(t) {
    var h = Math.round((Date.parse(t) - Date.now()) / HOUR);
    return h > 0 ? "in about " + h + " h" : h === 0 ? "about now" : -h + " h ago";
  }
  function kms(v) { return Math.round(v).toLocaleString("en-US") + " km"; }
  // A storm Here speaks of: its forecast comes within 1,500 km of the point,
  // or with no forecast it is that close now, or the point is under a watch
  // or in the surge.
  function nearHere(r) {
    var d = r.forecast ? r.closest_km : r.now_km;
    return d != null && d <= 1500 || r.surge.length > 0 || r.watches.length > 0;
  }
  function stormHere(r) {
    var lines = [], near = r.closest_km != null && r.closest_km <= 1500;
    var LOST = {watches: "The watches and warnings could not be fetched this run; read the advisory.",
                cone: "The forecast cone could not be fetched this run; read the advisory.",
                surge: "The peak storm surge forecast could not be fetched this run; read the advisory."};
    lines.push("At " + utc(Date.parse(r.now)) + " (advisory " + esc(r.advisory) + ") " + esc(r.title) + " was " +
               kms(r.now_km) + " " + COMPASS8[Math.round(r.bearing / 45) % 8] + " of here" +
               (r.now_wind != null ? ", " + r.now_wind + " kt." : "."));
    if (!r.forecast) lines.push("No official forecast this run, so how close it comes and when its wind " +
                                "would reach here are not known; read the advisory.");
    if (r.closest != null) lines.push(r.receding ? "Its official forecast takes it no closer than that."
      : "On the official forecast it comes closest at " + utc(Date.parse(r.closest)) + " (" + soon(r.closest) + "), " +
        kms(r.closest_km) + " away" + (r.closest_wind != null ? ", forecast " + r.closest_wind + " kt." : "."));
    var reach = THRESHOLDS.map(function (t) {
      if (r.arrival[t]) return t + " kt from " + utc(Date.parse(r.arrival[t])) + " (" + soon(r.arrival[t]) + ")";
      if (r.unknown.indexOf(+t) >= 0) return t + " kt not forecast";
      return t + " kt does not reach here";
    });
    if (r.arrival["34"] || r.unknown.length) lines.push("Wind here on that forecast: " + reach.join("; ") + ".");
    else if (near) lines.push(r.gale ? "Its forecast gale radius does not reach here."
      : r.reached ? "Its forecast keeps it below gale force, 34 kt."
      : "Its forecast gives no gale radius; the exposure table looks a degree either side " +
        "of its track, and here is further.");
    if (r.cone !== null && near) lines.push(r.cone ? "Inside the forecast cone." : "Outside the forecast cone.");
    r.watches.forEach(function (w) {
      lines.push('<span class="linekey" style="background:' + (D.style.products[w.kind] || "var(--ink)") + '"></span>' +
                 "Nearest coast under a " + esc(w.kind) + ": " + kms(w.km) + ".");
    });
    r.surge.forEach(function (a) { lines.push("Inside the peak storm surge area \u201c" + esc(a.label) + "\u201d: " + esc(a.feet) + "."); });
    r.lost.forEach(function (k) {
      var said = Object.keys(r.in_effect);
      lines.push(k === "watches" && said.length
        ? "The lines of the watches and warnings could not be fetched this run; the public advisory has in effect: " +
          said.map(function (kind) { return esc(kind) + " for " + esc(r.in_effect[kind].join("; ")); }).join("; ") + "."
        : LOST[k]);
    });
    if (r.official) {
      var c = r.official.chances;
      lines.push(esc(r.centre) + "\u2019s own chance at " + esc(r.official.place.toUpperCase()) +
                 (r.official.hours ? " within " + r.official.hours + " h" : "") + ": " +
                 THRESHOLDS.map(function (t) { return t + " kt " + (c[t] == null ? "not listed" : c[t] === 0 ? "<1%" : c[t] + "%"); }).join(", ") + ".");
    }
    return '<li><b><span class="swatch" style="background:' + r.hue + '"></span>' + esc(r.title) + "</b> " +
           '<span class="muted">' + esc(r.centre) + "</span>" +
           lines.map(function (l) { return "<p>" + l + "</p>"; }).join("") + "</li>";
  }
  function showHere() {
    var box = $("here");
    if (!box) return;
    if (!S.here) {
      box.hidden = true; box.innerHTML = ""; $("herego").hidden = true; S.google = null;
      hereSay("");
      return;
    }
    var h = hereFor(S.here.lon, S.here.lat), html = [], place = h.place;
    html.push('<h2 class="panelhead" id="here-title">Here: ' + esc(S.here.label) + "</h2>");
    var facts = [where(h.lon, h.lat)], fact = placeFact(h.lon, h.lat, S.here.label);
    if (fact) facts.push(fact);
    html.push('<p class="herewhere">' + facts.join(" \u00b7 ") + "</p>");
    html.push('<div class="herebtns"><button type="button" class="toolbtn" data-here="show">Show on map</button>' +
              '<button type="button" class="toolbtn" data-here="street">Street View here</button>' +
              '<button type="button" class="toolbtn" data-here="then">Then and now here</button>' +
              '<button type="button" class="toolbtn" data-here="clear">Clear</button></div>');
    html.push('<div class="streetcard" id="street-card">' + streetCardHtml(streetState(S.here.lon, S.here.lat)) + "</div>");
    var near = h.storms.filter(nearHere);
    var far = h.storms.filter(function (r) { return near.indexOf(r) < 0; });
    html.push("<h4>Live storms</h4>");
    if (!h.storms.length) html.push("<p>No live tropical cyclones.</p>");
    if (near.length) html.push('<ul class="herestorms">' + near.map(stormHere).join("") + "</ul>");
    else if (h.storms.length) html.push("<p>No live storm\u2019s official forecast comes within 1,500 km of here.</p>");
    if (far.length) html.push("<p>Further away, closest on their forecasts: " + far.map(function (r) {
      return esc(r.title) + " " + (r.closest_km == null ? "no forecast" : kms(r.closest_km));
    }).join(", ") + ".</p>");
    html.push("<h4>Formation outlook</h4>");
    if (!h.areas.length) html.push("<p>No area the warning centres are watching for formation is near here.</p>");
    h.areas.forEach(function (a) {
      var chance = a.centre === "JTWC" ? (a.potential || "unrated") + " potential in 24 h" + (a.alert ? ", " + alertHtml(a.until) : "")
                 : pct(a.chance_2day) + " in 2 days, " + pct(a.chance_7day) + " in 7 days";
      html.push("<p>" + (a.inside ? "Inside " : kms(a.km) + " from ") + esc(a.centre) + "\u2019s " +
                (a.centre !== "JTWC" ? "formation area " : a.polygon ? "formation alert area " : "") + "\u201c" + esc(a.label) + "\u201d: " + chance + ".</p>");
    });
    html.push("<h4>Who warns here</h4>");
    html.push("<p>" + (place && place.km <= 400 && place.country
      ? "Warnings for " + esc(place.country) + "\u2019s coast come from its national meteorological service. "
      : "Out at sea, far from any named place. ") +
      "Each storm\u2019s advisories come from the centre named beside it.</p>");
    html.push(ensoHereHtml(ensoHere(h.lon, h.lat)));
    html.push(ensoTodayHtml(S.here.lon, S.here.lat));
    html.push(googleHtml(h.lat, h.lon, S.z));
    html.push('<p><a href="atlas.html#at=' + h.lat.toFixed(2) + "," + h.lon.toFixed(2) + '">What El Ni\u00f1o usually does here, season by season &rarr;</a></p>');
    html.push('<p class="method">' + esc(D.methods.here || "") + "</p>");
    hereWrite(box, html.join(""));
    box.hidden = false;
    hereSay("Here: " + S.here.label);
    ensoTodayRead(S.here.lon, S.here.lat);
    if (streetAsked(S.here.lon, S.here.lat)) streetCard(S.here.lon, S.here.lat, true);
    if (S.street) streetChip();
    var go2 = $("herego");
    go2.textContent = S.here.label.split(", ")[0] + (D.focus === "world" ? ": El Ni\u00f1o here \u2193" : ": what the storms mean here \u2193");
    go2.hidden = false;
  }
  // Here written anew, as the reader left it: its tables open or shut, and
  // the focus on its control (retake). Google's frame open on this point is
  // left where it is, never loaded again, so the place the reader has gone to
  // in it (Street View walked on, Google's map moved) stays; a frame of
  // another point closes.
  function hereWrite(box, html) {
    var frame = S.google && S.google.lon === S.here.lon && S.google.lat === S.here.lat ? $("google-frame") : null;
    retake(box, html, frame);
    if (frame) googlePressed(S.google.kind);
    else S.google = null;
  }
  // Which place Here is on, said by the line kept for it outside the panel:
  // written only when that changes, so Here written anew (each take writes
  // it) is not read out again.
  function hereSay(words) {
    var line = $("here-said");
    if (line && line.textContent !== words) line.textContent = words;
  }
  // How far a town's people reach, km: as far as a disc of them at 2,000 a
  // square kilometre would, from 1.5 to 30 km. Natural Earth's are an urban
  // area's people: New York's 19 million reach 30 km, Newark's 280,123 people
  // 6.7 km.
  function placeReach(people) { return clamp(Math.sqrt((people || 0) / (Math.PI * 2000)), 1.5, 30); }
  // The town a point is in: the nearest of those whose people reach it, or
  // null. Only a town within 30 km, the farthest any reaches, can.
  function placeIn(lon, lat) {
    var best = null;
    for (var i = 0; i < PLACES.length; i++) {
      var p = PLACES[i];
      if (Math.abs(p[5] - lat) > 0.3) continue;
      if (Math.abs(((p[4] - lon + 540) % 360) - 180) * Math.cos(rad(lat)) > 0.3) continue;
      var d = km(lon, lat, p[4], p[5]);
      if (d <= placeReach(p[3]) && (!best || d < best.km)) best = {km: d, p: p};
    }
    return best;
  }
  // A point named: the town it is in, the distance from the nearest place
  // within 400 km, or its latitude and longitude. Here's name for it, and an
  // entered place's.
  function placeLabel(lon, lat) {
    var inside = placeIn(lon, lat), p = inside || nearestPlace(lon, lat);
    if (inside) return named(inside.p);
    return p && p.km <= 400 ? kms(p.km) + " from " + named(p.p) : where(lon, lat);
  }
  // What Here's line says after the position, as its name does: the people
  // of the town the point is in, or how far the nearest place within 400 km
  // is.
  function placeFact(lon, lat, label) {
    var inside = placeIn(lon, lat), p = inside ? null : nearestPlace(lon, lat);
    if (inside) return inside.p[3] ? peopleFact(label, {name: inside.p[0], population: inside.p[3]}) : "";
    return p && p.km <= 400 ? kms(p.km) + " from " + esc(p.p[0]) : "";
  }
  function hereAt(lon, lat, label) {
    lon = wrap(lon); lat = clamp(lat, -85, 85);
    if (!label) label = placeLabel(lon, lat);
    S.here = {lon: lon, lat: lat, label: label};
    pin(lon, lat, label);
    showHere();
    var panel = $("panel");
    if (panel && window.matchMedia && window.matchMedia("(min-width: 900px)").matches) panel.scrollTop = 0;
  }
  function clearHere() { if (S.street) streetLeave(); S.here = null; if (!S.then) S.pin = null; showHere(); requestRender(); }

  // ---- touch, mouse and keys ------------------------------------------------------
  var pointers = new Map(), gesture = null, lastTap = null, wheelTimer = 0, dragging = false, tapTimer = 0;
  function local(e) { var r = map.getBoundingClientRect(); return {x: e.clientX - r.left, y: e.clientY - r.top}; }
  function begin() {
    var pts = Array.from(pointers.values());
    if (!pts.length) return null;
    var g = {multi: pts.length > 1 || !!(gesture && gesture.multi)};
    if (pts.length === 1) g.a = toWorld(pts[0].x, pts[0].y);
    else {
      var m = {x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2};
      g.a = toWorld(m.x, m.y); g.z0 = S.z;
      g.d0 = Math.max(1, Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y));
    }
    return g;
  }
  map.addEventListener("pointerdown", function (e) {
    if (e.target.closest && e.target.closest(".ui")) return;
    if (e.pointerType === "mouse" && e.button !== 0) return;
    // A synthetic pointer has nothing to capture; the gesture works without it.
    try { map.setPointerCapture(e.pointerId); } catch (err) { /* nothing to capture */ }
    var p = local(e);
    pointers.set(e.pointerId, {x: p.x, y: p.y, x0: p.x, y0: p.y, t0: e.timeStamp, target: e.target});
    cancelAnimationFrame(anim); anim = 0;
    gesture = begin();
    map.classList.add("dragging");
  });
  map.addEventListener("pointermove", function (e) {
    var q = pointers.get(e.pointerId);
    if (!q || !gesture) return;
    var p = local(e);
    q.x = p.x; q.y = p.y;
    var pts = Array.from(pointers.values()), W;
    if (pointers.size === 1) {
      W = world();
      S.x = gesture.a.x - (q.x - S.w / 2) / W; S.y = gesture.a.y - (q.y - S.h / 2) / W;
    } else {
      // Two fingers: the zoom follows their spread, about their midpoint.
      var d = Math.max(1, Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y));
      var m = {x: (pts[0].x + pts[1].x) / 2, y: (pts[0].y + pts[1].y) / 2};
      S.z = clamp(gesture.z0 + Math.log(d / gesture.d0) / Math.LN2, MINZ, maxZoom());
      W = world();
      S.x = gesture.a.x - (m.x - S.w / 2) / W; S.y = gesture.a.y - (m.y - S.h / 2) / W;
    }
    requestRender();
  });
  function tap(q, time) {
    clearTimeout(tapTimer);
    if (S.arming) { var w = toWorld(q.x, q.y); arm(false); figureLand(lonOf(w.x), latOf(w.y)); return; }
    if (lastTap && time - lastTap.t < 320 && Math.hypot(q.x - lastTap.x, q.y - lastTap.y) < 30) {
      lastTap = null;
      zoomBy(1, q.x, q.y);
      return;
    }
    lastTap = {t: time, x: q.x, y: q.y};
    var hit = q.target && q.target.closest ? q.target.closest("[data-storm],[data-area]") : null;
    if (!hit) {
      // Anywhere else is a place to ask about, once it is clear the tap is
      // not the first of a double tap.
      var a = toWorld(q.x, q.y);
      tapTimer = setTimeout(function () {
        if (S.then) thenMove(lonOf(a.x), latOf(a.y)); else hereAt(lonOf(a.x), latOf(a.y));
      }, 330);
      return;
    }
    if (hit.getAttribute("data-storm")) flyTo(hit.getAttribute("data-storm"));
    else flyToArea(hit.getAttribute("data-area"));
  }
  function release(e) {
    var q = pointers.get(e.pointerId);
    if (!q) return;
    pointers.delete(e.pointerId);
    var multi = gesture && gesture.multi;
    if (e.type === "pointerup" && !pointers.size && !multi &&
        Math.hypot(q.x - q.x0, q.y - q.y0) < 10 && e.timeStamp - q.t0 < 600) tap(q, e.timeStamp);
    gesture = pointers.size ? begin() : null;
    if (gesture && multi) gesture.multi = true;
    if (!pointers.size) { map.classList.remove("dragging"); settle(); }
  }
  map.addEventListener("pointerup", release);
  map.addEventListener("pointercancel", release);
  map.addEventListener("wheel", function (e) {
    e.preventDefault();
    var p = local(e), a = toWorld(p.x, p.y);
    var dz = -e.deltaY * (e.deltaMode === 1 ? 0.05 : e.deltaMode === 2 ? 1 : 0.002);
    S.z = clamp(S.z + clamp(dz, -1, 1), MINZ, maxZoom());
    var W = world();
    S.x = a.x - (p.x - S.w / 2) / W; S.y = a.y - (p.y - S.h / 2) / W;
    requestRender();
    clearTimeout(wheelTimer);
    wheelTimer = setTimeout(settle, 200);
  }, {passive: false});
  map.addEventListener("keydown", function (e) {
    if (e.target !== map) return;
    var step = 80 / world(), done = true;
    if (e.key === "ArrowLeft") S.x -= step;
    else if (e.key === "ArrowRight") S.x += step;
    else if (e.key === "ArrowUp") S.y -= step;
    else if (e.key === "ArrowDown") S.y += step;
    else if (e.key === "+" || e.key === "=") { zoomBy(1); return e.preventDefault(); }
    else if (e.key === "-" || e.key === "_") { zoomBy(-1); return e.preventDefault(); }
    else done = false;
    if (done) { e.preventDefault(); settle(); }
  });
  divider.addEventListener("pointerdown", function (e) {
    dragging = true;
    try { divider.setPointerCapture(e.pointerId); } catch (err) { /* synthetic */ }
    e.stopPropagation();
  });
  divider.addEventListener("pointermove", function (e) {
    if (!dragging) return;
    S.split = clamp(local(e).x / S.w, 0.05, 0.95);
    divider.setAttribute("aria-valuenow", String(Math.round(S.split * 100)));
    requestRender();
  });
  function stopDrag() { dragging = false; }
  divider.addEventListener("pointerup", stopDrag);
  divider.addEventListener("pointercancel", stopDrag);
  divider.addEventListener("keydown", function (e) {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    S.split = clamp(S.split + (e.key === "ArrowLeft" ? -0.05 : 0.05), 0.05, 0.95);
    divider.setAttribute("aria-valuenow", String(Math.round(S.split * 100)));
    e.preventDefault();
    requestRender();
  });
  document.querySelectorAll("[data-layer]").forEach(function (b) {
    b.addEventListener("click", function () { pressLayer(b.getAttribute("data-layer")); });
  });
  document.querySelectorAll("[data-show],[data-ref]").forEach(function (box) {
    box.addEventListener("change", function () { readToggles(); dirty(); });
  });
  document.querySelectorAll("[data-zoom]").forEach(function (b) {
    b.addEventListener("click", function () { zoomBy(+b.getAttribute("data-zoom")); });
  });
  document.querySelectorAll("[data-fit]").forEach(function (b) {
    b.addEventListener("click", function () { fit(false); });
  });
  $("compare").addEventListener("click", pressCompare);
  $("day-earlier").addEventListener("click", function () { findDay(-1); });
  $("day-later").addEventListener("click", function () { findDay(1); });
  $("compare-layer").addEventListener("change", function (e) {
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    S.second = e.target.value;
    if (S.second === "detail") { S.dayStepped = false; dayAt = ""; }
    if (S.second === S.layer) setLayer(S.layer === "infrared" ? "geocolor" : "infrared");
    dirty();
  });
  $("swap").addEventListener("click", function () {
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    var top = S.layer, under = S.second;
    S.second = top;
    setLayer(under);
    $("compare-layer").value = S.second;
  });
  // The loop runs on the map: pressed in the street, it leaves for the map.
  $("loop").addEventListener("click", function () { var on = !S.loop; if (S.street) streetLeave(); setLoop(on); });
  scrub.addEventListener("input", function () { if (S.playing) setPlay(false); setScrub(+scrub.value); });
  playBtn.addEventListener("click", function () { setPlay(!S.playing); });
  framePill.addEventListener("click", function () {
    var had = document.activeElement && document.activeElement.classList.contains("pillmore");
    pillOpen = !pillOpen;
    pills();
    if (had && framePill.querySelector(".pillmore")) framePill.querySelector(".pillmore").focus();
  });
  var root = document.documentElement, themeBtn = $("theme");
  function darkNow() {
    var t = root.getAttribute("data-theme");
    return t ? t === "dark" : !!(window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches);
  }
  function themeLabel() { themeBtn.textContent = darkNow() ? "Light" : "Dark"; }
  themeBtn.addEventListener("click", function () { root.setAttribute("data-theme", darkNow() ? "light" : "dark"); themeLabel(); });
  document.addEventListener("click", function (e) {
    var el = e.target.closest ? e.target.closest("[data-fly],[data-select],[data-tab],[data-here],[data-google],[data-show-region],#retry,#herego") : null;
    if (!el) return;
    if (el.hasAttribute("data-show-region")) { showRegion(el.getAttribute("data-show-region")); return; }
    if (el.hasAttribute("data-google")) { googleFrame(el.getAttribute("data-google")); return; }
    if (el.id === "herego") { var hb = $("here"); if (hb && !hb.hidden) hb.scrollIntoView({block: "start"}); return; }
    if (el.hasAttribute("data-here")) {
      var what = el.getAttribute("data-here"), h = S.here;
      if (what === "clear") clearHere();
      else if (h && what === "street") streetPick(h.lon, h.lat, S.z, h.label);
      else if (h && what === "then") thenEnter(h.lon, h.lat, h.label);
      else if (h) {
        // Shown on the map: out of the street, which covers it.
        if (S.street) streetLeave();
        map.scrollIntoView({block: "nearest"});
        animate({x: mx(h.lon) + near(mx(h.lon)), y: my(h.lat), z: Math.max(S.z, 9)});
      }
      return;
    }
    if (el.id === "retry") { retry(); return; }
    if (el.hasAttribute("data-fly")) { flyTo(el.getAttribute("data-fly")); return; }
    if (el.hasAttribute("data-select")) { select(el.getAttribute("data-select")); return; }
    var sec = el.closest("section.storm");
    if (sec) tab(sec, el.getAttribute("data-tab"));
  });

  // ---- a run taken where the reader is ---------------------------------------
  // A box written anew around one node of it, which is left where it is: the
  // new markup's node of the same id marks its place. A frame taken out of
  // the page loads again, so Google's frame, and Here, which holds it, never
  // are. Without that node, or with one that is not the box's, the box is
  // written whole.
  function writeAround(box, html, keep) {
    if (!keep || keep.parentNode !== box) { box.innerHTML = html; return; }
    var fresh = document.createElement("div"), before = true;
    fresh.innerHTML = html;
    Array.prototype.slice.call(box.childNodes).forEach(function (n) { if (n !== keep) box.removeChild(n); });
    Array.prototype.slice.call(fresh.childNodes).forEach(function (n) {
      if (n.id === keep.id) before = false;
      else box.insertBefore(n, before ? keep : null);
    });
  }
  // A new run's markup put in a box as the reader left it: each storm on the
  // tab it showed, each <details> open or shut as it was, and the focus on
  // the control it was on, each found again by knownAs(). The node kept
  // (Here) keeps its own.
  function retake(box, html, keep) {
    var tabs = shownTabs(box), open = {}, on = document.activeElement;
    var focus = on && on !== box && box.contains(on) && !(keep && keep.contains(on)) ? knownAs(on) : "";
    box.querySelectorAll("details").forEach(function (d) { open[knownAs(d)] = d.open; });
    writeAround(box, html, keep);
    box.querySelectorAll("section.storm").forEach(function (sec) { tab(sec, tabs[sec.id] || "now"); });
    box.querySelectorAll("details").forEach(function (d) {
      var k = knownAs(d);
      if (k in open) d.open = open[k];
    });
    if (!focus) return;
    var again = box.querySelectorAll("a[href], button, summary, input, select");
    for (var i = 0; i < again.length; i++) {
      if (knownAs(again[i]) === focus) { again[i].focus({preventScroll: true}); return; }
    }
  }
  // Each storm's tab as the reader left it, by its section's id.
  function shownTabs(root) {
    var tabs = {};
    root.querySelectorAll("section.storm").forEach(function (sec) {
      var on = sec.querySelector('[data-tab][aria-selected="true"]');
      if (on) tabs[sec.id] = on.getAttribute("data-tab");
    });
    return tabs;
  }
  // A control, or a <details> by its summary, known by what it is and not by
  // where it stands: its section, then its id, address and data-* actions,
  // or its words where it has none (a summary's, as live.py finds a section
  // across a load).
  function knownAs(el) {
    var sec = el.closest("section[id]"), named = el.tagName === "DETAILS" ? el.querySelector("summary") : el;
    if (!named) return "";
    var says = Array.prototype.filter.call(named.attributes, function (a) {
      return a.name === "id" || a.name === "href" || a.name.slice(0, 5) === "data-";
    }).map(function (a) { return a.name + "=" + a.value; });
    return (sec ? sec.id : "") + "|" + named.tagName + "|" + (says.length ? says.join(" ") : named.textContent.trim());
  }

  // ---- keeping current -----------------------------------------------------------
  // A new run is read from the page itself, map data and panel together, and
  // the view is left where it is. Served, the page asks the site each minute
  // which run it serves (elninoLive, in live.py) and comes here only for a run
  // it does not show; the promise says when the page has taken it, and the
  // page then names the run in its head. A run another code wrote, or whose
  // page names other assets, is not this script's to read: the promise says
  // false, and the follower loads the page again for it, the reader's place
  // handed across (keepPlace, below). A copy no newer than the page's own run
  // (a CDN's edge can still serve an older one) is passed over, and the
  // follower goes for the run again after a pause.
  function refresh() {
    return siteCopy().then(function (copy) {
      if (copy === false) return false;
      if (copy && newer(copy.data.built, D.built)) return takeRun(copy.doc, copy.data);
    });
  }
  // The site's copy of this page and its data, read: false when another code
  // wrote it; null when it could not be had or read.
  function siteCopy() {
    return fetch(location.href.split("#")[0], {cache: "no-store"}).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.text();
    }).then(function (text) {
      var doc = new DOMParser().parseFromString(text, "text/html");
      if (!elninoLive.sameCode(doc)) return false;
      var node = doc.getElementById("desk-data");
      return node ? {doc: doc, data: JSON.parse(node.textContent)} : null;
    }).catch(function () { return null; });
  }
  // Whether one run is later than another, however each is written.
  function newer(a, b) { return Date.parse(a) > Date.parse(b); }
  // A run's data with what is the same on every run, which the page leaves to
  // the assets it names (elnino/assets.py): the gazetteer, the coast and the
  // composite grids. A run is taken only from a page naming the same assets,
  // so this page's are the run's.
  function withAssets(d) {
    d.places = ELNINO.places; d.coast = ELNINO.coast; d.enso.grids = ELNINO.grids;
    return d;
  }
  // The new run taken where the reader is, the place in the panel and the key
  // held by the follower (elninoLive.hold). A take that fails part way leaves
  // the page between two runs: it throws once the place is put back, and the
  // follower loads the page for the run.
  function takeRun(doc, next) {
    var panel = doc.getElementById("panel"), legend = doc.getElementById("legend");
    var stamp = doc.getElementById("built");
    var putPlaceBack = elninoLive.hold();
    try {
      D = withAssets(next);
      // The panel and the key as the reader left them. Here is the page's own:
      // showHere, below, writes it from the new run around Google's frame.
      if (panel) retake($("panel"), panel.innerHTML, $("here"));
      // The header's stamp is the new run's, as the panel's is.
      if (stamp) $("built").innerHTML = stamp.innerHTML;
      // The legend comes back empty, so the El Nino key is written again.
      if (legend) { retake($("legend"), legend.innerHTML); ensoSaid = ""; }
      // The regions' Show in the new panel, pressed as the reader left them.
      ensoControls();
      prepare();
      thenRefreshed(doc);
      if (S.then) thenApply();
      coastDone = 0; coastD = ""; coastG.innerHTML = "";
      select(BYID[S.selected] ? S.selected : (STORMS[0] ? STORMS[0].id : null));
      showHere();
      // The replay's years told again by the new run's index; the storm line
      // and panel written from its storms.
      if (S.sim) simRetake();
      tcRetake();
      ages();
      // Drawn now, keys and all, so the reader's place is put back on the page
      // as it will stand.
      geoDirty = true;
      render();
    } finally {
      putPlaceBack();
    }
    elninoLive.shows(doc);
  }

  // ---- a run loaded where the reader was ------------------------------------------
  // A run the page cannot take in place is loaded, and the reader's place
  // handed across: the view; the layers, the comparison, the divider and the
  // loop as the map's own (Exit's, while a place or the street is entered); the hour scrubbed to,
  // the day stepped to, the overlays and El Nino's map; Here, and Google's
  // frame in it; the place entered, on its event or its dates, or the street
  // dropped into, with the dates then and now last showed; the storm chosen
  // and each storm's tab. The follower keeps the panel's scroll, its tables
  // open or shut and the theme.
  function keepPlace() {
    var T = S.then, layers = T ? T.back : S;
    return {view: {lon: wrap(lonOf(S.x)), lat: latOf(S.y), z: S.z},
            layer: layers.layer, second: layers.second, compare: layers.compare, split: layers.split,
            loop: T ? T.back.loop : S.street ? S.street.back.loop : S.loop, scrub: S.scrub,
            day: S.dayStepped ? S.day : null,
            show: S.show, refs: S.refs, enso: S.enso,
            here: S.here, google: S.google ? S.google.kind : null,
            then: T ? {lon: T.lon, lat: T.lat, label: T.label, source: T.source, preset: T.preset,
                       a: sideDay(T, "a"), b: sideDay(T, "b"), names: T.names, split: S.split} : null,
            street: streetView(), thenLast: S.thenLast,
            storm: S.selected, tabs: shownTabs($("panel"))};
  }
  // The place handed across, put back over the page as it opened. It is
  // read like input, and only what is this page's own is put back: a layer
  // it draws, a storm it shows, a region it names, a day that is one. A
  // place the reader had left stays left, though the address opened on it.
  function restorePlace(k) {
    function point(p) { return !!p && typeof p === "object" && finite(p.lon) && finite(p.lat) && Math.abs(p.lat) <= 90; }
    // Leaving the place the address opened on strips the address of it: the
    // place entered again, the address is put back as it was.
    var address = /^#(then|street)=/.test(location.hash) ? location.href : null;
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    if (drawable(k.layer)) setLayer(k.layer);
    if (drawable(k.second) && k.second !== S.layer) { S.second = k.second; $("compare-layer").value = S.second; }
    if (typeof k.compare === "boolean") setCompare(k.compare);
    if (finite(k.split)) thenSplit(clamp(k.split, 0.05, 0.95));
    if (finite(k.scrub)) { scrub.value = k.scrub; S.scrub = +scrub.value; }
    if (realDay(k.day)) { S.day = k.day; S.dayStepped = true; }
    ticked(k.show, "data-show");
    ticked(k.refs, "data-ref");
    readToggles();
    var enso = ensoKept(k.enso);
    if (Object.keys(enso).length) setEnso(enso);
    if (own(BYID, k.storm)) select(k.storm);
    var tabs = k.tabs && typeof k.tabs === "object" ? k.tabs : {};
    $("panel").querySelectorAll("section.storm").forEach(function (sec) {
      var name = own(tabs, sec.id) ? tabs[sec.id] : null;
      if (Array.prototype.some.call(sec.querySelectorAll("[data-tab]"), function (b) {
        return b.getAttribute("data-tab") === name;
      })) tab(sec, name);
    });
    // The view before Here, so Google's map opens at the reader's zoom, and
    // again last, over the flight into a place entered.
    var h = k.here, t = k.then, s = k.street, v = k.view;
    var seen = !!v && typeof v === "object" && finite(v.lon) && finite(v.lat) && finite(v.z);
    function look() {
      cancelAnimationFrame(anim); anim = 0;
      S.x = mx(wrap(v.lon)); S.y = my(clamp(v.lat, -85, 85)); S.z = clamp(v.z, MINZ, maxZoom());
    }
    if (seen) look();
    if (point(h)) {
      hereAt(h.lon, h.lat, typeof h.label === "string" ? h.label : "");
      // Street View, once one of Google's frames here, is a pick into the
      // street now: a frame of it kept by a page from before is let go.
      if (k.google === "map" || k.google === "satellite") googleFrame(k.google);
    } else if (h === null && S.here) clearHere();
    if (point(t) && thenSrc(t.source)) {
      thenEnter(t.lon, t.lat, typeof t.label === "string" && t.label ? t.label : null,
                {source: t.source, preset: t.preset, a: t.a, b: t.b, names: t.names, instant: true});
      if (finite(t.split)) thenSplit(clamp(t.split, 0.05, 0.95));
    }
    var last = k.thenLast;
    if (last && typeof last === "object" && thenSrc(last.source)) {
      S.thenLast = {source: last.source, preset: last.preset, a: last.a, b: last.b, names: last.names};
    }
    if (point(s)) streetEnter(s.lon, s.lat, typeof s.label === "string" && s.label ? s.label : null, {mini: s.mini});
    // A loop runs over frames GIBS has yet to give: on Exit, while a place or
    // the street is entered, and else once they are in view (loopWhenKnown).
    if (k.loop === true) {
      if (S.then) S.then.back.loop = true;
      else if (S.street) S.street.back.loop = true;
      else S.loopWanted = true;
    }
    if (seen) { look(); settle(); }
    if (address && (S.then || S.street)) {
      try { history.replaceState(null, "", address); } catch (err) { /* the address stays without it */ }
    }
  }
  // A layer the map can show, as its base or beside it: one of its maps, or
  // NASA's imagery; not a side of then and now.
  function drawable(id) {
    var l = own(LAYERS, id) ? LAYERS[id] : null;
    return !!l && (l.kind === "map" || l.kind === "imagery") && !l.then;
  }
  // The Overlays menu's boxes of one kind, ticked as they were kept, each by
  // its name; a name the page no longer has is passed over.
  function ticked(kept, attr) {
    if (!kept || typeof kept !== "object") return;
    document.querySelectorAll("[" + attr + "]").forEach(function (box) {
      var name = box.getAttribute(attr);
      if (own(kept, name) && typeof kept[name] === "boolean") box.checked = kept[name];
    });
  }
  // El Nino's map as it was kept, as a change of what this page has: a
  // variable it draws (or none), a season it has, its switches, strengths
  // from 0 to 1, each of NASA's layers it offers, a region it names.
  function ensoKept(e) {
    var patch = {};
    if (!e || typeof e !== "object") return patch;
    if (e.variable === null || own(D.enso.grids, e.variable)) patch.variable = e.variable;
    if (own(D.enso.season_label, e.season)) patch.season = e.season;
    ["mask", "regions", "boxes"].forEach(function (key) { if (typeof e[key] === "boolean") patch[key] = e[key]; });
    ["opacity", "tileOpacity"].forEach(function (key) { if (finite(e[key])) patch[key] = clamp(e[key], 0, 1); });
    if (e.tiles && typeof e.tiles === "object") {
      patch.tiles = {};
      ensoTileLayers().forEach(function (l) { patch.tiles[l.id] = own(e.tiles, l.id) && e.tiles[l.id] === true; });
    }
    if (e.shown === null || (D.enso.links || []).some(function (l) { return l.region === e.shown; })) patch.shown = e.shown;
    return patch;
  }
  window.addEventListener("offline", function () { S.imagery = "offline"; dirty(); });
  window.addEventListener("online", function () {
    forgetMaps();
    if (S.imagery === "ok") { dirty(); return; }
    askGibsAgain(); dirty();
  });
  if (window.ResizeObserver) new ResizeObserver(function () { measure(); dirty(); }).observe(map);
  else window.addEventListener("resize", function () { measure(); dirty(); });


  // ---- the map: El Nino's effects, street by street (worldmap.py) ----------
  // The atlas's composites: the El Nino seasons since 1979 minus the ordinary
  // ones, per 2.5 degree (rainfall) or 2 degree (temperature) cell, drawn as
  // the atlas's field, blended between the cell centres, on a canvas under the
  // map's own names, in the atlas's colours to its full scale.
  var GRIDS = {}, RAMP_RGB = [];
  var ensoFirst = document.querySelector('[data-enso-var][aria-pressed="true"]');
  function geoOn(key) { var b = document.querySelector('[data-enso-geo="' + key + '"]'); return !!(b && b.checked); }
  S.enso = {variable: (ensoFirst && ensoFirst.getAttribute("data-enso-var")) || null,
            season: D.enso.now, mask: true, opacity: D.enso.opacity, tileOpacity: D.enso.tile_opacity,
            tiles: {}, regions: geoOn("regions"), boxes: geoOn("boxes"), shown: null};
  if ($("enso-tiles")) $("enso-tiles").style.opacity = S.enso.tileOpacity;
  function gridAxis(text) { return String(text).split(",").map(Number); }
  function gridPlane(name, season, kind) {
    var key = name + season + kind, v = D.enso.grids[name];
    if (GRIDS[key]) return GRIDS[key];
    return (GRIDS[key] = v.seasons[season][kind].split("\n").filter(Boolean).map(function (row) {
      return row.split(",").map(function (c) { return c === "_" ? null : +c / v.scale; });
    }));
  }
  function gridAxes(name) {
    var key = name + "@axes", v = D.enso.grids[name];
    return GRIDS[key] || (GRIDS[key] = [gridAxis(v.lats), gridAxis(v.lons)]);
  }
  // Python's atlas._index and atlas._nearest_lon, step for step.
  function nearestAt(values, target) {
    var best = Infinity, at = 0;
    for (var i = 0; i < values.length; i++) { var g = Math.abs(values[i] - target); if (g < best) { best = g; at = i; } }
    return at;
  }
  function nearestLon(values, target) {
    var best = Infinity, at = 0;
    for (var i = 0; i < values.length; i++) {
      var g = Math.abs(((values[i] - target + 180) % 360 + 360) % 360 - 180);
      if (g < best) { best = g; at = i; }
    }
    return at;
  }
  function wrap180(lon) { var v = ((lon + 180) % 360 + 360) % 360 - 180; return v === -180 ? 180 : v; }
  function critOf(name, season) { var c = D.enso.significant[name][season]; return c == null ? Infinity : c; }
  // One cell at a point, as atlas.sample reads it.
  function cellAt(name, season, lon, lat) {
    var ax = gridAxes(name), lats = ax[0], lons = ax[1];
    var r = nearestAt(lats, lat), c = nearestLon(lons, ((lon % 360) + 360) % 360);
    var dy = lats.length > 1 ? Math.abs(lats[1] - lats[0]) / 2 : 0;
    var dx = lons.length > 1 ? Math.abs(lons[1] - lons[0]) / 2 : 0;
    return {value: gridPlane(name, season, "diff")[r][c], base: gridPlane(name, season, "base")[r][c],
            t: gridPlane(name, season, "t")[r][c], crit: critOf(name, season),
            lon0: wrap180(lons[c] - dx), lon1: wrap180(lons[c] + dx),
            lat0: Math.min(lats[r] - dy, lats[r] + dy), lat1: Math.max(lats[r] - dy, lats[r] + dy)};
  }
  // atlas.verdict and Cell.percent, rule for rule.
  function verdictOf(name, cell) {
    if (cell.value === null) return "no record";
    if (cell.t === null || Math.abs(cell.t) < cell.crit) return "no clear signal";
    if (name === "PRECIP") return cell.value > 0 ? "wetter" : "drier";
    return cell.value > 0 ? "warmer" : "cooler";
  }
  function percentOf(name, cell) {
    if (name !== "PRECIP" || cell.value === null || cell.base === null || cell.base < D.enso.dry_floor) return null;
    return cell.value / cell.base * 100;
  }
  // The documented effects whose footprints cover a point: regional, then
  // basin, then those true of everywhere; within each, the smallest box first,
  // as geo.at orders them (no box crosses the date line).
  function regionsAt(lon, lat) {
    var w = wrap180(lon), found = [], rank = {regional: 0, basin: 1, global: 2};
    (D.enso.links || []).forEach(function (l, i) {
      var area = Infinity;
      l.boxes.forEach(function (b) {
        if (w >= b[0] && w <= b[1] && lat >= b[2] && lat <= b[3]) area = Math.min(area, (b[1] - b[0]) * (b[3] - b[2]));
      });
      if (area < Infinity) found.push({link: l, area: area, i: i});
    });
    return found.sort(function (a, b) {
      return (rank[a.link.scope] || 0) - (rank[b.link.scope] || 0) || a.area - b.area || a.i - b.i;
    }).map(function (f) { return f.link; });
  }
  // Everything the record says of one point: each season's rainfall and
  // temperature cell with its verdict, the cells' size there, and the regions.
  function ensoHere(lon, lat) {
    var out = {lon: wrap180(lon), lat: lat, seasons: [], sizes: {}, regions: regionsAt(lon, lat)};
    D.enso.seasons.forEach(function (s) {
      var row = {season: s, now: s === D.enso.now, next: s === D.enso.next};
      ["PRECIP", "AIR"].forEach(function (n) {
        var c = cellAt(n, s, lon, lat);
        row[n] = {cell: c, verdict: verdictOf(n, c), percent: percentOf(n, c)};
      });
      out.seasons.push(row);
    });
    ["PRECIP", "AIR"].forEach(function (n) {
      var c = cellAt(n, D.enso.now, lon, lat), dx = (c.lon1 - c.lon0 + 360) % 360 || 360, dy = c.lat1 - c.lat0;
      out.sizes[n] = {dx: dx, dy: dy, kmx: dx * 111.32 * Math.cos(rad(lat)), kmy: dy * 110.57};
    });
    return out;
  }
  function ensoCellText(name, got) {
    var c = got.cell, unit = D.enso.grids[name].unit;
    if (c.value === null) return name === "AIR" ? "no record: the temperature grid is land only" : "no record";
    var text = signedText(c.value, 2) + " " + unit;
    if (name === "PRECIP" && c.base !== null) {
      text += " against an ordinary " + c.base.toFixed(2) + (got.percent === null ? "" : " (" + signedText(got.percent, 0) + "%)");
    }
    text += ", |t| " + (c.t === null ? "n/a" : Math.abs(c.t).toFixed(2));
    text += isFinite(c.crit) ? ", needs " + c.crit.toFixed(2) : ", too few events to test";
    return esc(text) + ": <b>" + esc(got.verdict) + "</b>";
  }
  function ensoHereHtml(h) {
    var html = ["<h4>El Niño here</h4>",
      '<p class="method">What the El Niño seasons since 1979 (RONI +1.0 or more) did here against the neutral ones ' +
      "(RONI within 0.5), season by season. " +
      "It is the record of past events, not this season’s forecast.</p>",
      '<table class="ensohere"><thead><tr><th>Season</th><th>Rainfall</th><th>Temperature</th></tr></thead><tbody>'];
    h.seasons.forEach(function (row) {
      var mark = row.now ? " (now)" : row.next ? " (next)" : "";
      html.push("<tr><th scope=\"row\">" + esc(row.season + mark) + '<span class="muted"> ' +
                esc(D.enso.season_label[row.season]) + "</span></th><td>" + ensoCellText("PRECIP", row.PRECIP) +
                "</td><td>" + ensoCellText("AIR", row.AIR) + "</td></tr>");
    });
    html.push("</tbody></table>");
    var p = h.sizes.PRECIP, a = h.sizes.AIR;
    html.push('<p class="method">Rainfall is one ' + p.dx.toFixed(1) + "° by " + p.dy.toFixed(1) + "° cell, about " +
              Math.round(p.kmx) + " by " + Math.round(p.kmy) + " km here; temperature one " + a.dx.toFixed(1) + "° by " +
              a.dy.toFixed(1) + "° cell, about " + Math.round(a.kmx) + " by " + Math.round(a.kmy) +
              " km. Each value is the whole cell’s, not this street’s.</p>");
    html.push("<details><summary>Events sampled</summary>");
    D.enso.seasons.forEach(function (s) {
      var m = D.enso.grids.PRECIP.meta[s];
      html.push('<p class="method">' + esc(s) + ": " + m.warm_events.length + " El Niños (" + m.warm_months +
                " months) against " + m.base_years + " neutral years: " + esc(m.warm_events.join(", ")) + ".</p>");
    });
    html.push("</details>");
    var local = h.regions.filter(function (l) { return l.scope !== "global"; });
    var everywhere = h.regions.filter(function (l) { return l.scope === "global"; });
    function region(l) {
      var said = l.status === "in play" ? "In play this event: " + l.likelihood + (l.timing ? ", " + l.timing : "") + "."
               : l.status === "watch" ? "On the watch list this event." : "";
      return "<li><b>" + esc(l.region) + "</b>: " + esc(l.effect) + " (" + esc(l.window) + ", " + esc(l.confidence) +
             " confidence)." + (said ? " <b>" + esc(said) + "</b>" : "") + "</li>";
    }
    html.push("<h4>Documented effects here</h4>");
    html.push(local.length ? '<ul class="wwlist">' + local.map(region).join("") + "</ul>"
                           : "<p>No regional effect in the catalogue has a footprint here.</p>");
    if (everywhere.length) html.push("<p>Everywhere:</p><ul class=\"wwlist\">" + everywhere.map(region).join("") + "</ul>");
    return html.join("");
  }
  // ---- Google's own map of the point, on request ---------------------------
  // Google's tiles are not drawn on this map (its terms allow them only
  // through its own map); its embed and its Maps URLs are, and nothing is
  // asked of Google until a button is pressed.
  function googleZoom(z) { return Math.max(3, Math.min(21, Math.round(z))); }
  function googleEmbed(kind, lat, lon, z) {
    var at = lat.toFixed(6) + "," + wrap180(lon).toFixed(6);
    if (kind === "street") return "https://maps.google.com/maps?layer=c&cbll=" + at + "&cbp=12,0,0,0,0&output=svembed";
    return "https://maps.google.com/maps?q=" + at + "&t=" + (kind === "satellite" ? "k" : "m") +
           "&z=" + googleZoom(z) + "&output=embed";
  }
  function googleLinks(lat, lon, z) {
    var at = lat.toFixed(6) + "," + wrap180(lon).toFixed(6), zoom = googleZoom(z);
    var maps = "https://www.google.com/maps/@?api=1&map_action=map&center=" + at + "&zoom=" + zoom + "&basemap=";
    return {map: maps + "roadmap", satellite: maps + "satellite",
            street: "https://www.google.com/maps/@?api=1&map_action=pano&viewpoint=" + at,
            earth: "https://earth.google.com/web/@" + at + ",0a," +
                   Math.round(591657550.5 / Math.pow(2, zoom)) + "d,35y,0h,0t,0r"};
  }
  // Street View is a pick, as the figure's is (streetPick): Google's frame at
  // the point as tapped found "No Street View available." or a photo someone
  // took inside for six of sixteen taps over New York on 14 October 2026.
  // Its button's data-row tells it from Here's own Street View here, which
  // does the same, so the focus on it is found on it again as Here is
  // rewritten.
  function googleHtml(lat, lon, z) {
    var l = googleLinks(lat, lon, z);
    var kinds = [["map", "Map"], ["satellite", "Satellite"]];
    return "<h4>Google Maps here</h4>" +
      '<div class="herebtns">' + kinds.map(function (k) {
        return '<button type="button" class="toolbtn" data-google="' + k[0] + '" aria-pressed="false">' + k[1] + "</button>";
      }).join("") + '<button type="button" class="toolbtn" data-here="street" data-row="google">Street View' +
      "</button></div>" +
      '<div id="google-frame" class="gframe" hidden></div>' +
      '<p class="method">Nothing goes to Google until a button is pressed; then Google’s own map loads here and ' +
      "Google receives this position. Street View drops into the nearest street, found by FOSSGIS’s OSRM or " +
      "Valhalla, as the figure does.</p>" +
      '<p class="links">' + [["map", "Google Maps"], ["satellite", "Google satellite"], ["street", "Street View"],
                             ["earth", "Google Earth"]].map(function (k) {
        return '<a href="' + esc(l[k[0]]) + '" target="_blank" rel="noopener" data-glink="' + k[0] + '">' + k[1] + " ↗</a>";
      }).join("") + "</p>";
  }
  // Here is written as a flight to a found place begins, so its links to
  // Google take the zoom of each view the map settles on.
  function googleRelink() {
    if (!S.here) return;
    var l = googleLinks(S.here.lat, S.here.lon, S.z);
    document.querySelectorAll("#here a[data-glink]").forEach(function (a) { a.setAttribute("href", l[a.getAttribute("data-glink")]); });
  }
  // The Google buttons, the one whose frame is open pressed ("" for none).
  function googlePressed(kind) {
    document.querySelectorAll("[data-google]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-google") === kind ? "true" : "false");
    });
  }
  // Google's own map of S.here, at the view's zoom; the pressed button again
  // closes it.
  function googleFrame(kind) {
    var box = $("google-frame");
    if (!box || !S.here) return;
    var closing = !!S.google && S.google.kind === kind && !box.hidden;
    googlePressed(closing ? "" : kind);
    box.innerHTML = "";
    if (closing) { S.google = null; box.hidden = true; return; }
    S.google = {kind: kind, lon: S.here.lon, lat: S.here.lat};
    var frame = document.createElement("iframe");
    frame.setAttribute("title", {map: "Google Maps", satellite: "Google Maps satellite view"}[kind] +
                                " of " + S.here.label);
    frame.setAttribute("loading", "lazy");
    frame.setAttribute("referrerpolicy", "no-referrer-when-downgrade");
    frame.setAttribute("allowfullscreen", "");
    frame.setAttribute("src", googleEmbed(kind, S.here.lat, S.here.lon, S.z));
    box.appendChild(frame);
    box.hidden = false;
  }
  // ---- the Nino regions and the impact regions -------------------------------
  // A box in world units, west edge to east edge: Nino-4's 160E to 210E runs
  // east across the date line, not west across the world.
  function boxPath(lon0, lon1, lat0, lat1, k) {
    return "M" + X(lon0, k) + " " + Y(lat1) + "H" + X(lon1, k) + "V" + Y(lat0) + "H" + X(lon0, k) + "Z";
  }
  // A region's boxes as one place, in world fractions: each box is taken on
  // the side of the date line nearer the first, so the Pacific islands'
  // boxes either side of 180 make one view, not the width of the world.
  function regionBox(l) {
    var ref = (l.boxes[0][0] + l.boxes[0][1]) / 2, x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    l.boxes.forEach(function (b) {
      var shift = Math.round((ref - (b[0] + b[1]) / 2) / 360) * 360;
      x0 = Math.min(x0, mx(b[0] + shift)); x1 = Math.max(x1, mx(b[1] + shift));
      y0 = Math.min(y0, my(clamp(b[3], -85, 85))); y1 = Math.max(y1, my(clamp(b[2], -85, 85)));
    });
    return {x0: x0, x1: x1, y0: y0, y1: y1};
  }
  // The regions under everything else drawn: the impact regions (the ones
  // true of everywhere left out), every one while they are ticked, else the
  // one Show asked for alone, solid where this event puts it in play; CPC's
  // boxes; and the composite cell under the pin while one is shown.
  function ensoGeo() {
    var h = [];
    if (S.enso.regions || S.enso.shown) (D.enso.links || []).forEach(function (l) {
      if (l.scope === "global" || !(S.enso.regions || l.region === S.enso.shown)) return;
      var cls = l.status === "in play" ? "region play" : "region";
      l.boxes.forEach(function (b) {
        h.push('<path class="' + cls + '" d="' + boxPath(b[0], b[1], b[2], b[3], near(mx((b[0] + b[1]) / 2))) + '"/>');
      });
    });
    // Each box on a light case, so the dashes show over dark imagery too.
    if (S.enso.boxes) (D.enso.boxes || []).forEach(function (b) {
      var d = boxPath(b.lon0, b.lon1, b.lat0, b.lat1, near(mx((b.lon0 + b.lon1) / 2)));
      h.push('<path class="ninocase" d="' + d + '"/><path class="ninobox" d="' + d + '"/>');
    });
    if (S.enso.variable && S.pin) {
      var c = cellAt(S.enso.variable, S.enso.season, S.pin.lon, S.pin.lat);
      var lon1 = c.lon1 < c.lon0 ? c.lon1 + 360 : c.lon1, d = boxPath(c.lon0, lon1, c.lat0, c.lat1, near(mx((c.lon0 + lon1) / 2)));
      h.push('<path class="pinnedcase" d="' + d + '"/><path class="pinned" d="' + d + '"/>');
    }
    return h.join("");
  }
  // Each box named with this week's anomaly, above its northwest corner, or
  // under the box where a neighbour's name has the room above; each region
  // in play named at its anchor from zoom 3, where a name fits, and the one
  // Show asked for, whatever its status.
  function ensoLabels(sx, sy, off, label) {
    var out = [];
    if (S.enso.boxes) (D.enso.boxes || []).forEach(function (b) {
      copies(mx((b.lon0 + b.lon1) / 2), 200).forEach(function (k) {
        var x = sx(b.lon0, k), y = sy(b.lat1) - 9, under = sy(b.lat0) + 13;
        var lines = [[b.label + (b.anomaly === null ? "" : " " + signedText(b.anomaly, 2) + " °C"), "dl2"]];
        if (off(x, y, 0)) return;
        out.push(label(x, y, 0, lines) || (off(x, under, 0) ? "" : label(x, under, 0, lines)));
      });
    });
    if ((S.enso.regions || S.enso.shown) && S.z >= 3) (D.enso.links || []).forEach(function (l) {
      if (l.scope === "global") return;
      if (l.region !== S.enso.shown && !(S.enso.regions && l.status === "in play")) return;
      var b = l.boxes[0], lon = (b[0] + b[1]) / 2;
      copies(mx(lon), 200).forEach(function (k) {
        var x = sx(lon, k), y = sy((b[2] + b[3]) / 2);
        if (off(x, y, 0)) return;
        out.push(label(x, y, 0, [[l.region, "dl2"]]));
      });
    });
    return out;
  }
  // The map flown to a region's boxes, drawn alone unless every region is on;
  // asked again, the region put away and the map left where it is.
  function showRegion(name) {
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    var l = (D.enso.links || []).filter(function (x) { return x.region === name; })[0];
    if (!l) return false;
    if (S.enso.shown === name) { setEnso({shown: null}); return true; }
    setEnso({shown: name});
    animate(viewFor({box: regionBox(l)}));
    var box = map.getBoundingClientRect();
    if (box.top < 0 || box.bottom > window.innerHeight) map.scrollIntoView({block: "start", behavior: "smooth"});
    return true;
  }
  // ---- NASA's own tiles: today's ocean, the last three days' floods ----------
  // A pixel back to the entry of NASA's colour map it was painted from: the
  // nearest within a hair (the PNGs are paletted, so a pixel is exact unless
  // a browser's colour handling moves it), transparent where nothing is mapped.
  function classify(entries, px) {
    if (px[3] < 128) return {transparent: true};
    var best = null, bestd = 7;
    for (var i = 0; i < entries.length; i++) {
      var e = entries[i].rgb, d = Math.abs(e[0] - px[0]) + Math.abs(e[1] - px[1]) + Math.abs(e[2] - px[2]);
      if (d < bestd) { bestd = d; best = entries[i]; }
    }
    return best;
  }
  // The classes drawn faint: their pixels' alpha cut to the given strength.
  function fadePixels(data, rgbs, strength) {
    var n = 0, a = Math.round(255 * strength);
    for (var i = 0; i + 3 < data.length; i += 4) {
      if (data[i + 3] < 128) continue;
      for (var j = 0; j < rgbs.length; j++) {
        var c = rgbs[j];
        if (Math.abs(data[i] - c[0]) + Math.abs(data[i + 1] - c[1]) + Math.abs(data[i + 2] - c[2]) < 7) { data[i + 3] = a; n++; break; }
      }
    }
    return n;
  }
  // A tile with a class to draw faint is drawn again from a canvas, once.
  function fadeTile(img) {
    img._faded = true;
    try {
      var cv = document.createElement("canvas");
      cv.width = img.naturalWidth || 256; cv.height = img.naturalHeight || 256;
      var cx = cv.getContext("2d", {willReadFrequently: true});
      cx.drawImage(img, 0, 0);
      var data = cx.getImageData(0, 0, cv.width, cv.height);
      if (!fadePixels(data.data, img._faint, D.enso.faint)) return false;
      cx.putImageData(data, 0, 0);
      img.src = cv.toDataURL();
      return true;
    } catch (err) { return false; }   // drawn as NASA made it
  }
  function ensoTileLayers() { return D.layers.filter(function (l) { return l.kind === "enso"; }); }
  // The switched-on tile layers, each at the latest day GIBS lists; none past
  // zoom 12, where one of their pixels would fill much of the view.
  function ensoTileSpecs() {
    var specs = [];
    if (S.z > D.enso.hide_above || S.then) return specs;
    D.layers.filter(function (l) { return l.kind === "enso"; }).forEach(function (l, i) {
      if (S.enso.tiles[l.id]) specs.push({key: l.id, cells: cells(l.id, 0).cells, visible: true, z: i});
    });
    return specs;
  }
  function ensoHiddenText(l) {
    var size = l.pixel_km >= 1 ? l.pixel_km + " km" : Math.round(l.pixel_km * 1000) + " m";
    return l.name + " hidden past zoom " + D.enso.hide_above + ": its " + size + " pixels would be " +
           Math.round(Math.pow(2, S.z - l.zoom)) + " screen pixels across.";
  }
  // Where a switched-on tile layer stands, for its key.
  function ensoTileState(l) {
    if (S.z > D.enso.hide_above) return ensoHiddenText(l);
    var s = source(l.id), f = frameOf(s, 0), d = s && DOM[s.name];
    if (f) return (l.id === "floods" ? "Three days to " : "Day of ") + dayText(f.key) + ". Tap a point to read it.";
    if (S.imagery === "offline") return "Offline: NASA's tiles need the network.";
    if ((d && d.unanswered) || S.imagery === "unreachable") return "NASA GIBS did not answer.";
    if (d && d.failed) return "NASA GIBS lists no recent day for it.";
    return "Asking NASA GIBS for the latest day.";
  }
  function ensoTileLegend() {
    ensoTileLayers().forEach(function (l) {
      var key = $("enso-" + l.id + "-key"), on = !!S.enso.tiles[l.id] && !S.then;
      if (!key) return;
      if (key.hidden !== !on) key.hidden = !on;
      if (!on) return;
      var out = key.querySelector("output"), text = ensoTileState(l);
      if (out && out.textContent !== text) out.textContent = text;
    });
  }
  // For the pill: the switched-on layers hidden at this zoom.
  function ensoTileMore() {
    if (S.z <= D.enso.hide_above) return [];
    return ensoTileLayers().filter(function (l) { return S.enso.tiles[l.id]; }).map(ensoHiddenText);
  }
  // For the credit line: NASA's words for each layer drawn.
  function ensoWhat(l, f) {
    var day = f ? dayText(f.key) : "the latest day";
    return l.id === "floods" ? "Floods, 3 days to " + day : "Ocean today (MUR SST anomaly, " + day + ")";
  }
  // One pixel of the day's tile under a point, at the layer's own zoom, read
  // back to NASA's own bin or class: a sentence, never a rejection, and the
  // day whose pixel it read ("" when none was).
  function readEnso(id, lon, lat) {
    var l = LAYERS[id], s = source(id), entries = D.enso.colours[id];
    return new Promise(function (resolve) {
      function answer(text, day) { resolve({text: text, day: day || ""}); }
      if (!l || !s || !entries) { answer(""); return; }
      function attempt(tries) {
        var f = frameOf(s, 0);
        if (!f) {
          ask(s);
          if (tries > 0 && S.imagery !== "offline" && S.imagery !== "unreachable") {
            setTimeout(function () { attempt(tries - 1); }, 1000);
            return;
          }
          answer(ensoWhat(l, null) + ": " + (S.imagery === "offline" ? "offline, NASA's tiles need the network" : "NASA GIBS did not answer"));
          return;
        }
        var n = Math.pow(2, l.zoom), x = mx(wrap(lon)) * n, y = clamp(my(lat), 0, 0.9999999) * n;
        var col = Math.floor(x), row = Math.floor(y), img = new Image();
        img.crossOrigin = "anonymous";
        img.onload = function () {
          var px = null;
          try {
            var cv = document.createElement("canvas");
            cv.width = cv.height = 256;
            var cx = cv.getContext("2d", {willReadFrequently: true});
            cx.drawImage(img, 0, 0, 256, 256);
            px = cx.getImageData(Math.min(255, Math.floor((x - col) * 256)), Math.min(255, Math.floor((y - row) * 256)), 1, 1).data;
          } catch (err) { px = null; }
          if (!px) { answer(ensoWhat(l, f) + ": the tile could not be read"); return; }
          var got = classify(entries, px), said;
          if (got === null) said = "a colour not on NASA’s scale";
          else if (got.transparent) said = l.id === "floods" ? "nothing mapped here: no water seen, or no data" : "nothing mapped here: land, ice or no data";
          else said = l.id === "floods" ? got.label : got.label + " at this pixel, on NASA’s own colour scale";
          answer(ensoWhat(l, f) + ": " + said, f.key);
        };
        img.onerror = function () { answer(ensoWhat(l, f) + ": NASA GIBS did not answer"); };
        img.src = tileUrl(s, f.key, l.zoom, row, ((col % n) + n) % n);
      }
      attempt(8);
    });
  }
  // Here's readings of NASA's tiles, by layer, day and point: Here written
  // anew (each take writes it) shows a reading it has had, not asked again.
  var TODAY = {};
  function todayKey(id, day, lon, lat) { return [id, day, lon, lat].join("|"); }
  // Here: a line for each switched-on tile layer, filled once its pixel is
  // read, or at once with the reading of the day's pixel already had.
  function ensoTodayHtml(lon, lat) {
    var on = ensoTileLayers().filter(function (l) { return S.enso.tiles[l.id]; });
    if (!on.length) return "";
    return "<h4>Today here, from NASA</h4>" + on.map(function (l) {
      var f = frameOf(source(l.id), 0), had = f && TODAY[todayKey(l.id, f.key, lon, lat)];
      return '<p id="here-' + l.id + '">' + esc(had || ensoWhat(l, f) + ": reading NASA’s tile…") + "</p>";
    }).join("");
  }
  function ensoTodayRead(lon, lat) {
    ensoTileLayers().forEach(function (l) {
      var f = frameOf(source(l.id), 0);
      if (!S.enso.tiles[l.id] || (f && TODAY[todayKey(l.id, f.key, lon, lat)])) return;
      readEnso(l.id, lon, lat).then(function (got) {
        if (got.day) TODAY[todayKey(l.id, got.day, lon, lat)] = got.text;
        var p = $("here-" + l.id);
        if (p && got.text && S.here && S.here.lon === lon && S.here.lat === lat) p.textContent = got.text;
      });
    });
  }
  // Past 90 pixels a cell the colour yields, down to 0.42, so the streets
  // show through a cell that is now most of the screen.
  function cellWeight(px) { var f = D.enso.fade; return px < f[0] ? 1 : Math.max(f[2], 1 - (px - f[0]) / f[1]); }
  // How wide one of the grid's cells is on a world W pixels across.
  function cellPx(name, W) {
    var lons = gridAxes(name)[1];
    return (lons.length > 1 ? Math.abs(lons[1] - lons[0]) : 2) / 360 * W;
  }
  // Whether a cell fits a view w by h pixels. The cell under the pin is
  // outlined only while it does: wider or taller, its outline is a lone line
  // or two across the streets, with no edge of colour beside them to be the
  // edge of. Mercator draws a cell taller the further it is from the equator:
  // at 60 N, twice as tall as it is wide.
  function cellFits(name, W, w, h, cell) {
    return cellPx(name, W) <= w && (my(cell.lat0) - my(cell.lat1)) * W <= h;
  }
  // ---- the composite as a field -----------------------------------------------
  // The atlas's field, taken in here from atlasview.FIELD_JS: blended between
  // the cell centres, while a tap still reads the whole cell (cellAt).

  // -- the composite as a field ----------------------------------------------
  // One value per 2.5 degree (rainfall) or 2 degree (temperature) cell,
  // painted a square per cell, reads as a mosaic of big pixels. The atlas and
  // the map draw a field instead: at each point the four cell centres around
  // it, blended by how near each is (bilinear), a cell with no record taking
  // no part. At a centre the field is that cell's value, and a click still
  // reads the whole cell. The share of the blend with a record fades the
  // land-only temperature grid out at the coast; the share of that the t test
  // passed fades a signal out where its cells stop passing.

  // A season's grid made ready to blend: its values in one array, NaN where a
  // cell has no record, and a 1 for each cell whose |t| reaches `crit`.
  function fieldOf(lats, lons, diff, tv, crit) {
    var nr = lats.length, nc = lons.length;
    var val = new Float64Array(nr * nc), sig = new Float64Array(nr * nc), r, c;
    for (r = 0; r < nr; r++) {
      for (c = 0; c < nc; c++) {
        var v = diff[r][c], t = tv[r][c];
        val[r * nc + c] = v === null ? NaN : v;
        sig[r * nc + c] = t !== null && Math.abs(t) >= crit ? 1 : 0;
      }
    }
    return { lat0: lats[0], dlat: nr > 1 ? lats[1] - lats[0] : 1, nr: nr,
             lon0: lons[0], dlon: nc > 1 ? lons[1] - lons[0] : 360, nc: nc,
             val: val, sig: sig };
  }
  // A latitude as the rows of centres either side and the share of the
  // second; past the first or the last row, that row alone.
  function fieldRow(g, lat) {
    var v = (lat - g.lat0) / g.dlat, r0 = Math.floor(v);
    if (r0 < 0) { return [0, 0, 0]; }
    if (r0 >= g.nr - 1) { return [g.nr - 1, g.nr - 1, 0]; }
    return [r0, r0 + 1, v - r0];
  }
  // A longitude as the columns either side and the share of the second, the
  // grid wrapping round the world: no seam at the date line or at Greenwich.
  function fieldCol(g, lon) {
    var u = (lon - g.lon0) / g.dlon, c0 = Math.floor(u), f = u - c0;
    c0 = ((c0 % g.nc) + g.nc) % g.nc;
    return [c0, (c0 + 1) % g.nc, f];
  }
  // The field at one point: its value (null where no cell near has a record),
  // the share of the blend with a record, and the share of that which passed.
  function fieldAt(g, lon, lat) {
    var rw = fieldRow(g, lat), cl = fieldCol(g, lon), cover = 0, sum = 0, pass = 0, i;
    var parts = [[rw[0], cl[0], (1 - rw[2]) * (1 - cl[2])],
                 [rw[0], cl[1], (1 - rw[2]) * cl[2]],
                 [rw[1], cl[0], rw[2] * (1 - cl[2])],
                 [rw[1], cl[1], rw[2] * cl[2]]];
    for (i = 0; i < 4; i++) {
      var k = parts[i][0] * g.nc + parts[i][1], w = parts[i][2], v = g.val[k];
      if (w > 0 && v === v) { cover += w; sum += w * v; pass += w * g.sig[k]; }
    }
    return cover > 0 ? { value: sum / cover, cover: cover, sig: pass / cover }
                     : { value: null, cover: 0, sig: 0 };
  }
  // The field as RGBA, a pixel for each longitude in `lons` across by each
  // latitude in `lats` down (NaN for a row off the world, left clear): each
  // pixel fieldAt its point, in the ramp's colour for the value - tone.rgb
  // the ramp as numbers, tone.invert and tone.lim the atlas's rampIndex -
  // and clear where no cell near has a record. While tone.mask is on, what
  // the t test does not pass is drawn at tone.dim of its strength. With
  // tone.clear, for a field over a picture, the middle step is left clear:
  // within half a step of nothing, grey there only veiled the streets or the
  // photograph under it. tone.right, {from, rgb}, is a second ramp from
  // column `from` on: compared, the layer right of the divider is a ground of
  // its own. `into` is a buffer to fill again. fieldAt's sums, in its order,
  // so a pixel is exactly it.
  function paintField(g, lons, lats, tone, into) {
    var fw = lons.length, fh = lats.length, n = fw * fh * 4;
    var data = into && into.length === n ? into : new Uint8ClampedArray(n);
    if (data === into) { data.fill(0); }
    var nc = g.nc, val = g.val, sig = g.sig, rgb = tone.rgb, lim = tone.lim, dim = tone.dim;
    var clear = !!tone.clear, from = tone.right ? tone.right.from : fw;
    var rgbR = tone.right ? tone.right.rgb : rgb;
    var c0s = new Int32Array(fw), c1s = new Int32Array(fw), fus = new Float64Array(fw), i, j;
    for (i = 0; i < fw; i++) {
      var cl = fieldCol(g, lons[i]);
      c0s[i] = cl[0]; c1s[i] = cl[1]; fus[i] = cl[2];
    }
    for (j = 0; j < fh; j++) {
      if (lats[j] !== lats[j]) { continue; }
      var rw = fieldRow(g, lats[j]), a0 = rw[0] * nc, a1 = rw[1] * nc, fv = rw[2];
      var row = j * fw * 4;
      for (i = 0; i < fw; i++) {
        var fu = fus[i], c0 = c0s[i], c1 = c1s[i], cover = 0, sum = 0, pass = 0, k, w, v;
        w = (1 - fv) * (1 - fu); k = a0 + c0; v = val[k];
        if (w > 0 && v === v) { cover += w; sum += w * v; pass += w * sig[k]; }
        w = (1 - fv) * fu; k = a0 + c1; v = val[k];
        if (w > 0 && v === v) { cover += w; sum += w * v; pass += w * sig[k]; }
        w = fv * (1 - fu); k = a1 + c0; v = val[k];
        if (w > 0 && v === v) { cover += w; sum += w * v; pass += w * sig[k]; }
        w = fv * fu; k = a1 + c1; v = val[k];
        if (w > 0 && v === v) { cover += w; sum += w * v; pass += w * sig[k]; }
        if (!(cover > 0)) { continue; }
        var value = sum / cover, x = tone.invert ? -value : value;
        var s = Math.floor((x + lim) / (2 * lim) * 11);
        if (clear && s === 5) { continue; }
        var c = (i < from ? rgb : rgbR)[s < 0 ? 0 : (s > 10 ? 10 : s)];
        var a = cover * (tone.mask ? dim + (1 - dim) * (pass / cover) : 1), at = row + i * 4;
        data[at] = c[0]; data[at + 1] = c[1]; data[at + 2] = c[2];
        data[at + 3] = Math.round(a * 255);
      }
    }
    return { w: fw, h: fh, data: data };
  }
  // The field is worked out every few css pixels and drawn up to the page's
  // size with the browser's smoothing, so the ramp's steps meet along soft
  // lines, as a filled contour map's do. Its points are a lattice fixed to the
  // world, `origin` the page's place of the world's corner: worked out from
  // the page's corner instead, they slid over the ground as the view panned
  // and the steps' edges shimmered. The field starts on the lattice up to a
  // step before the page's edge,
  function fieldStart(origin, step) { return ((origin % step) + step) % step - step; }
  // and this many points from there cover `span` css pixels, however panned.
  function fieldSpan(span, step) { return Math.ceil(span / step) + 1; }
  // Two pixels apart, or wider on a page so big that would be more than a
  // quarter of a million points a frame.
  function fieldStep(w, h) {
    var step = Math.max(2, Math.ceil(Math.sqrt(w * h / 250000)));
    while (fieldSpan(w, step) * fieldSpan(h, step) > 250000) { step++; }
    return step;
  }
  // A ramp token's colour as numbers: "#rrggbb", "#rgb" or "rgb(r, g, b)",
  // else a mid grey.
  function hexRgb(text) {
    var s = String(text || "").trim(), m = /^#([0-9a-f]{6})$/i.exec(s);
    if (m) {
      return [parseInt(m[1].slice(0, 2), 16), parseInt(m[1].slice(2, 4), 16),
              parseInt(m[1].slice(4, 6), 16)];
    }
    m = /^#([0-9a-f])([0-9a-f])([0-9a-f])$/i.exec(s);
    if (m) {
      return [parseInt(m[1] + m[1], 16), parseInt(m[2] + m[2], 16),
              parseInt(m[3] + m[3], 16)];
    }
    m = /^rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)/i.exec(s);
    return m ? [+m[1], +m[2], +m[3]] : [136, 136, 136];
  }
  // -- the ground under the field --------------------------------------------
  // A base that is someone else's picture keeps its own tones whatever the
  // page's theme: Esri's street map is light, a photograph of the Earth
  // dark. Painted in the theme's ramp, the steps nearest nothing - made to
  // sink into the theme's own ground - stood out of a ground of the other
  // tone as blocks: grey and brown over the street map in the dark theme,
  // white over a photograph in the light. So the field takes the ramp made
  // for its ground; on the page's own (no base, one drawn in the page's
  // tones, or one mostly clear), `page`, the page's ramp.
  var GROUND_RAMPS = {"light":[[0,69,175],[34,105,189],[88,137,202],[135,169,213],[183,200,223],[232,232,232],[231,188,184],[225,144,137],[214,97,92],[200,34,44],[163,0,0]],"dark":[[97,166,255],[86,140,209],[76,114,164],[65,89,121],[54,65,80],[42,42,42],[85,57,55],[129,71,67],[175,85,80],[223,97,92],[255,109,104]]};
  function groundRamp(ground, page) {
    return ground === "light" || ground === "dark" ? GROUND_RAMPS[ground] : page;
  }
  // A key's eleven swatches in the colours the field is drawn in: its
  // ground's ramp, else the page's tokens, which follow the theme by
  // themselves; the middle one an outline where the field leaves it clear.
  function keySteps(strip, ground, clear) {
    var rgb = groundRamp(ground, null), steps = strip.children, i;
    for (i = 0; i < steps.length; i++) {
      var mid = !!clear && i === 5;
      steps[i].classList.toggle("clear", mid);
      steps[i].style.background = mid ? "transparent"
        : (rgb ? "rgb(" + rgb[i].join(", ") + ")" : "var(--d" + i + ")");
    }
  }
  function fieldGrid(name, season) {
    var key = name + season + "@field", ax = gridAxes(name);
    return GRIDS[key] || (GRIDS[key] = fieldOf(ax[0], ax[1], gridPlane(name, season, "diff"),
                                               gridPlane(name, season, "t"), critOf(name, season)));
  }
  // The field over a view w by h css pixels, a pixel every `step` of them on
  // the lattice fixed at the world's corner, at its centre's longitude and
  // latitude, clear off the top and bottom of the world: `rgb` the ramp as
  // numbers, `dim` the strength of what the t test does not pass while `mask`
  // is on, `into` a buffer to fill again, `clear` the middle step left
  // clear, and `right`, {x, rgb}, a second ramp from the first point at or
  // right of x css pixels on. x and y are where it starts.
  function compositeField(name, season, mask, o, w, h, step, rgb, dim, into, clear, right) {
    var x0 = fieldStart(o.left, step), y0 = fieldStart(o.top, step), fw = fieldSpan(w, step), fh = fieldSpan(h, step);
    var lons = new Float64Array(fw), lats = new Float64Array(fh), i, j;
    for (i = 0; i < fw; i++) lons[i] = lonOf((x0 + (i + 0.5) * step - o.left) / o.W);
    for (j = 0; j < fh; j++) {
      var wy = (y0 + (j + 0.5) * step - o.top) / o.W;
      lats[j] = wy < 0 || wy > 1 ? NaN : latOf(wy);
    }
    var tone = {invert: D.enso.grids[name].invert, lim: D.enso.limits[name], rgb: rgb, mask: mask, dim: dim,
                clear: !!clear};
    if (right) tone.right = {from: Math.max(0, Math.ceil((right.x - x0) / step - 0.5)), rgb: right.rgb};
    var f = paintField(fieldGrid(name, season), lons, lats, tone, into);
    f.x = x0; f.y = y0;
    return f;
  }
  // The page's ramp, for a layer with no ground of its own, is the page's
  // own tokens, read again when the theme changes, by the button or the
  // system's own: read once, the composite stayed in the light theme's
  // colours under the dark theme's legend.
  function readRamp() {
    var cs = getComputedStyle(document.documentElement);
    RAMP_RGB = [];
    for (var i = 0; i < 11; i++) RAMP_RGB.push(hexRgb(cs.getPropertyValue("--d" + i)));
  }
  function rethemed() { RAMP_RGB = []; requestRender(); }
  if (window.MutationObserver) {
    new MutationObserver(rethemed).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
  }
  if (window.matchMedia) {
    var darkScheme = window.matchMedia("(prefers-color-scheme: dark)");
    if (darkScheme.addEventListener) darkScheme.addEventListener("change", rethemed);
    else if (darkScheme.addListener) darkScheme.addListener(rethemed);
  }
  var ensoCanvas = $("enso-cells"), ensoCtx = ensoCanvas && ensoCanvas.getContext ? ensoCanvas.getContext("2d") : null;
  var fieldCanvas = null, fieldCtx = null, fieldImage = null;
  // The ground under a layer, its sources in `view`: the tone of its own
  // picture. One that says none (IMERG's rain rate, clear where it does not
  // rain), and one whose picture cannot be had (sideDown: offline, its
  // server not answering, none of its tiles arriving), is the page's: the
  // page's plane is what is under the field there.
  function groundOf(id, view) {
    var l = LAYERS[id];
    return l && l.ground && !sideDown(id, view) ? l.ground : "page";
  }
  // The ground left of the divider, the base layer's, and right of it, the
  // compared layer's, or the base's again with nothing compared.
  function groundSides() {
    var a = groundOf(S.layer, S.inView);
    return {left: a, right: S.compare ? groundOf(S.second, S.inViewB) : a, cut: S.split * S.w};
  }
  // Whether two grounds take one ramp: the page's is the light ramp in the
  // light theme and the dark in the dark.
  function sameRamp(a, b) { return String(groundRamp(a, RAMP_RGB)) === String(groundRamp(b, RAMP_RGB)); }
  function drawComposite() {
    if (!ensoCtx) return;
    // Entered (thennow.py), the composite of today's season stands aside.
    var name = S.then ? null : S.enso.variable;
    if (ensoCanvas.hidden !== !name) ensoCanvas.hidden = !name;
    if (!name) return;
    var dpr = window.devicePixelRatio || 1, w = Math.round(S.w * dpr), h = Math.round(S.h * dpr);
    if (ensoCanvas.width !== w || ensoCanvas.height !== h) { ensoCanvas.width = w; ensoCanvas.height = h; }
    ensoCtx.clearRect(0, 0, w, h);
    ensoCanvas.style.opacity = S.enso.opacity;
    if (!RAMP_RGB.length) readRamp();
    var o = origin(), step = fieldStep(S.w, S.h);
    var pin = S.pin ? cellAt(name, S.enso.season, S.pin.lon, S.pin.lat) : null;
    svgEl.classList.toggle("bigcell", !!pin && !cellFits(name, o.W, S.w, S.h, pin));
    // The field in the ramp made for the ground under it, the middle step
    // left clear: the map is always over a picture, or the page's plane.
    // Compared on two grounds, the right side's ramp from the divider on,
    // in the one pass: the lattice is painted once a frame, whatever is
    // compared.
    var sides = groundSides(), left = groundRamp(sides.left, RAMP_RGB);
    var right = sameRamp(sides.left, sides.right) ? null : {x: sides.cut, rgb: groundRamp(sides.right, RAMP_RGB)};
    var f = compositeField(name, S.enso.season, S.enso.mask, o, S.w, S.h, step, left, D.enso.mask,
                           fieldImage ? fieldImage.data : null, true, right);
    if (!fieldCanvas) { fieldCanvas = document.createElement("canvas"); fieldCtx = fieldCanvas.getContext("2d"); }
    if (!fieldImage || fieldImage.data !== f.data || fieldImage.width !== f.w) {
      fieldCanvas.width = f.w; fieldCanvas.height = f.h; fieldImage = new ImageData(f.data, f.w, f.h);
    }
    fieldCtx.putImageData(fieldImage, 0, 0);
    ensoCtx.imageSmoothingEnabled = true;
    ensoCtx.imageSmoothingQuality = "high";
    ensoCtx.globalAlpha = cellWeight(cellPx(name, o.W));
    ensoCtx.drawImage(fieldCanvas, f.x * dpr, f.y * dpr, f.w * step * dpr, f.h * step * dpr);
    ensoCtx.globalAlpha = 1;
  }
  function signedText(v, digits) { return (v > 0 ? "+" : v < 0 ? "−" : "") + Math.abs(v).toFixed(digits); }
  var ensoSaid = "";
  // The reading changes as the view moves. On a line of its own, it only grows
  // while the key keeps its width, so the map above does not jump by a line,
  // and redraw all it holds, each time the centre crosses into a cell with
  // more or fewer words. A reading written anew, by a run taken in place,
  // keeps the height held.
  var readTall = 0, readWide = 0;
  function holdHeight(el) {
    var wide = el.parentNode ? el.parentNode.clientWidth : 0;
    if (wide !== readWide) { readWide = wide; readTall = 0; el.style.minHeight = ""; }
    readTall = Math.max(readTall, el.offsetHeight);
    if (el.style.minHeight !== readTall + "px") el.style.minHeight = readTall + "px";
  }
  // A new width is read again, whatever the words.
  window.addEventListener("resize", function () { ensoSaid = ""; });
  // The key: what is drawn, which end is which, and the cell under the centre
  // of the view, read by the same rule as a tap.
  function ensoLegend() {
    var key = $("enso-key"), name = S.then ? null : S.enso.variable;
    if (!key) return;
    if (key.hidden !== !name) key.hidden = !name;
    if (!name) return;
    var g = D.enso.grids[name], lim = D.enso.limits[name], season = S.enso.season, crit = critOf(name, season);
    var lon = wrap180(lonOf(S.x)), lat = latOf(S.y), c = cellAt(name, season, lon, lat);
    var word = verdictOf(name, c), read;
    if (c.value === null) read = "Centre of the view: no record" + (name === "AIR" ? " (the temperature grid is land only)." : ".");
    else {
      var pct = percentOf(name, c);
      read = "Centre of the view: " + signedText(c.value, 2) + " " + g.unit +
        (pct === null ? "" : " (" + signedText(pct, 0) + "% of an ordinary " + c.base.toFixed(2) + ")") + ", " + word +
        (c.t === null ? "" : "; |t| " + Math.abs(c.t).toFixed(2) + (isFinite(crit) ? ", needs " + crit.toFixed(2) : ", too few events to test")) + ".";
    }
    if (S.z >= 7) {
      var deg = (c.lon1 - c.lon0 + 360) % 360 || 360, across = Math.round(deg * 111.32 * Math.cos(rad(lat)));
      read += " One " + deg.toFixed(1) + "° cell is about " + across + " km across here: the colours blend between cell centres, and the value read is the whole cell's.";
    }
    var ends = name === "PRECIP" ? "−" + lim + " " + g.unit + " drier to +" + lim + " wetter"
             : "−" + lim + " " + g.unit + " cooler to +" + lim + " warmer";
    // "Clear" is this key's word for what the t test passes: the middle
    // step is "nothing drawn". Compared on two grounds, the strip is the
    // left side's.
    ends += ", nothing drawn within ±" + (lim / 11).toFixed(2);
    var sides = groundSides();
    if (!sameRamp(sides.left, sides.right)) ends += "; colours as drawn left of the divider";
    if (S.enso.mask) ends += "; faint where |t| is under " + (isFinite(crit) ? crit.toFixed(2) : "any value") + ", not told apart from an ordinary year";
    var said = [g.label + ", " + D.enso.season_label[season] + ": El Niño minus ordinary years", ends, read, sides.left].join("|");
    if (said === ensoSaid) return;
    ensoSaid = said;
    $("enso-name").textContent = g.label + ", " + D.enso.season_label[season] + ": El Niño minus ordinary years";
    // Rainfall reads the ramp backwards, so its strip is turned round, as the atlas turns it.
    $("enso-ramp").style.flexDirection = g.invert ? "row-reverse" : "row";
    // Its swatches in the colours drawn, the base's ground's (keySteps).
    keySteps($("enso-ramp"), sides.left, true);
    $("enso-ends").textContent = ends;
    $("enso-read").textContent = read;
    holdHeight($("enso-read"));
  }
  // The El Nino controls as S.enso has them: the menu's, and the regions'
  // Show, which a run taken in place brings anew in the panel.
  function ensoControls() {
    document.querySelectorAll("[data-enso-var]").forEach(function (b) {
      b.setAttribute("aria-pressed", (b.getAttribute("data-enso-var") || null) === S.enso.variable ? "true" : "false");
    });
    document.querySelectorAll("[data-enso-season]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-enso-season") === S.enso.season ? "true" : "false");
    });
    if ($("enso-mask")) $("enso-mask").checked = !!S.enso.mask;
    if ($("enso-opacity")) $("enso-opacity").value = S.enso.opacity;
    if ($("enso-tile-opacity")) $("enso-tile-opacity").value = S.enso.tileOpacity;
    if ($("enso-tiles")) $("enso-tiles").style.opacity = S.enso.tileOpacity;
    document.querySelectorAll("[data-enso-tile]").forEach(function (b) {
      b.checked = !!S.enso.tiles[b.getAttribute("data-enso-tile")];
    });
    document.querySelectorAll("[data-enso-geo]").forEach(function (b) {
      b.checked = !!S.enso[b.getAttribute("data-enso-geo")];
    });
    document.querySelectorAll("[data-show-region]").forEach(function (b) {
      b.setAttribute("aria-pressed", b.getAttribute("data-show-region") === S.enso.shown ? "true" : "false");
    });
  }
  function setEnso(patch) {
    if (S.then) thenLeave();
    if (S.street) streetLeave();
    for (var k in patch) S.enso[k] = patch[k];
    ensoControls();
    dirty();
    if ("tiles" in patch && S.here) showHere();
    return S.enso;
  }
  document.querySelectorAll("[data-enso-var]").forEach(function (b) {
    b.addEventListener("click", function () { setEnso({variable: b.getAttribute("data-enso-var") || null}); });
  });
  document.querySelectorAll("[data-enso-season]").forEach(function (b) {
    b.addEventListener("click", function () { setEnso({season: b.getAttribute("data-enso-season")}); });
  });
  if ($("enso-mask")) $("enso-mask").addEventListener("change", function (e) { setEnso({mask: e.target.checked}); });
  if ($("enso-opacity")) $("enso-opacity").addEventListener("input", function (e) { setEnso({opacity: +e.target.value}); });
  if ($("enso-tile-opacity")) $("enso-tile-opacity").addEventListener("input", function (e) { setEnso({tileOpacity: +e.target.value}); });
  document.querySelectorAll("[data-enso-geo]").forEach(function (b) {
    b.addEventListener("change", function () {
      var patch = {}, key = b.getAttribute("data-enso-geo");
      patch[key] = b.checked;
      // Every region ticked on or off: one shown alone is shown no longer.
      if (key === "regions") patch.shown = null;
      setEnso(patch);
    });
  });
  document.querySelectorAll("[data-enso-tile]").forEach(function (b) {
    b.addEventListener("change", function () {
      var tiles = {};
      for (var k in S.enso.tiles) tiles[k] = S.enso.tiles[k];
      tiles[b.getAttribute("data-enso-tile")] = b.checked;
      setEnso({tiles: tiles});
    });
  });
  function ramped() { readRamp(); dirty(); }
  if (window.MutationObserver) new MutationObserver(ramped).observe(document.documentElement, {attributes: true, attributeFilter: ["data-theme"]});
  if (window.matchMedia) {
    var schemeQuery = window.matchMedia("(prefers-color-scheme: dark)");
    if (schemeQuery.addEventListener) schemeQuery.addEventListener("change", ramped);
    else if (schemeQuery.addListener) schemeQuery.addListener(ramped);
  }

  // ---- streets and addresses: Esri's World Geocoder, only when asked ----------
  // The gazetteer answers as the reader types and sends nothing anywhere. The
  // geocoder is its last row: the words go to Esri only when that row is
  // chosen, for a single search whose answer is shown and not kept.
  var GEOCODER = "https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates";
  function geocodeUrl(q) {
    return GEOCODER + "?SingleLine=" + encodeURIComponent(q) + "&maxLocations=6&outFields=Match_addr,Type&f=json";
  }
  // Esri's candidates as places to fly to. An extent whose east edge is west
  // of its west edge crosses the date line, and is taken the short way round.
  function geocoded(answer) {
    var list = answer && answer.candidates;
    if (!Array.isArray(list)) return [];
    return list.slice(0, 6).filter(function (c) {
      return c && c.location && Number.isFinite(c.location.x) && Number.isFinite(c.location.y);
    }).map(function (c) {
      var a = c.attributes || {}, e = c.extent, box = null;
      if (e && [e.xmin, e.xmax, e.ymin, e.ymax].every(Number.isFinite)) {
        box = {x0: mx(e.xmin), x1: mx(e.xmax), y0: my(e.ymax), y1: my(e.ymin)};
        if (box.x1 < box.x0) box.x1 += 1;
      }
      return {kind: "address", label: a.Match_addr || c.address || "", deep: true, zoom: 16,
              sub: (a.Type || "Address") + " · Esri World Geocoder",
              lon: c.location.x, lat: c.location.y, box: box};
    });
  }
  function searchRow(text) {
    var q = String(text || "").trim();
    if (fold(q).length < 3 || coordinate(q)) return null;
    return {kind: "search", q: q, label: "Search streets and addresses for “" + q + "”",
            sub: "Sends these words to Esri’s World Geocoder"};
  }
  var geocoding = 0;
  function geocode(q) {
    var ticket = ++geocoding;
    closeList();
    findNote.hidden = false;
    findNote.textContent = "Asking Esri’s geocoder…";
    fetch(geocodeUrl(q)).then(function (r) {
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }).then(function (answer) {
      if (ticket !== geocoding) return;
      if (!answer || answer.error) throw new Error("refused");
      var got = geocoded(answer);
      if (!got.length) { findNote.textContent = "Esri’s geocoder found nothing for “" + q + "”."; return; }
      findNote.hidden = true;
      found = got;
      showFound();
    }).catch(function () {
      if (ticket !== geocoding) return;
      findNote.hidden = false;
      findNote.textContent = "Esri’s geocoder did not answer (offline, or blocked); the gazetteer still works.";
    });
  }

  // ---- then and now: a place before and after El Nino (thennow.py) ---------
  // A point of the map, entered from Here, from Street View or by its link,
  // shown as the same ground at two dates either side of the divider, the
  // earlier on the left, each named with the season of the index around it.
  // Each side is a layer of the page's own kinds, LAYERS["then-a"] and
  // LAYERS["then-b"], so the compare view draws them; the engine asks
  // S.then wherever it must not draw today's storms, tiles and composite
  // over another day.
  S.then = null;
  // The source and dates of the place last left, which Street View's Then
  // and now comes back to.
  S.thenLast = null;
  function thenSrc(id) {
    var list = (D.then && D.then.sources) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  // ---- each archive's times, and the season around a date --------------------
  // GIBS lists a layer's times as spans of start, end and period, kept here
  // as [start, end, step in days], oldest first: a single time is a span of
  // one day, and a period that is not whole days belongs to no layer here.
  var DAY = 24 * HOUR;
  function dayNo(key) { return Math.round(stamp(key) / DAY); }
  function keyOf(n) { return dayZ(n * DAY); }
  // A date as written, that is a day of the calendar: not "", not 2015-02-30.
  function realDay(text) {
    if (!/^\d{4}-\d\d-\d\d$/.test(text || "")) return false;
    var t = stamp(text);
    return !isNaN(t) && dayZ(t) === text;
  }
  function parseSpans(text) {
    var m = /<Domain>([^<]*)<\/Domain>/.exec(text || ""), out = [];
    if (!m) return out;
    m[1].split(",").forEach(function (part) {
      var bits = part.trim().split("/"), a = (bits[0] || "").slice(0, 10);
      var b = (bits.length === 3 ? bits[1] : bits[0] || "").slice(0, 10);
      var step = bits.length === 3 ? /^P([1-9]\d*)D$/.exec(bits[2]) : null;
      if ((bits.length !== 1 && !step) || !realDay(a) || !realDay(b) || b < a) return;
      out.push([a, b, step ? +step[1] : 1]);
    });
    return out.sort(function (p, q) { return p[0] < q[0] ? -1 : p[0] > q[0] ? 1 : 0; });
  }
  // The time listed nearest a date, the earlier on a tie; null with none.
  function snapTime(spans, key) {
    var t = dayNo(key), best = null, gap = Infinity;
    function consider(n) {
      var d = Math.abs(n - t);
      if (d < gap || (d === gap && n < best)) { gap = d; best = n; }
    }
    spans.forEach(function (s) {
      var a = dayNo(s[0]), b = dayNo(s[1]), step = s[2];
      if (t <= a) consider(a);
      else if (t >= b) consider(b);
      else {
        var lo = a + Math.floor((t - a) / step) * step;
        consider(lo);
        if (lo + step <= b) consider(lo + step);
      }
    });
    return best === null ? null : keyOf(best);
  }
  // The time listed before (by -1) or after (by +1) a date, null past the
  // ends. Each 16-day span starts on its own 1 January, so a step across the
  // turn of a year lands on the next span's first composite.
  function stepTime(spans, key, by) {
    var t = dayNo(key), best = null;
    spans.forEach(function (s) {
      var a = dayNo(s[0]), b = dayNo(s[1]), step = s[2], n = null;
      if (by > 0) {
        if (t < a) n = a;
        else if (t < b) { n = a + (Math.floor((t - a) / step) + 1) * step; if (n > b) n = null; }
      } else if (t > b) n = a + Math.floor((b - a) / step) * step;
      else if (t > a) n = a + (Math.ceil((t - a) / step) - 1) * step;
      if (n !== null && (best === null || (by > 0 ? n < best : n > best))) best = n;
    });
    return best === null ? null : keyOf(best);
  }
  // Months from the strip's first to a date's, and a date's month in words.
  function monthIndex(key) {
    var from = D.then.strip.from;
    return (+key.slice(0, 4) - +from.slice(0, 4)) * 12 + (+key.slice(5, 7) - +from.slice(5, 7));
  }
  function monthText(key) { return MONTHS[+key.slice(5, 7) - 1] + " " + key.slice(0, 4); }
  // The season of the index centred on a date's month, as the tracker's
  // record has it: [centre month, label, value as CPC prints it, words].
  var SEASONS = {}, SEASONS_OF = null;
  function seasonAt(key) {
    if (SEASONS_OF !== D.then) {
      SEASONS = {}; SEASONS_OF = D.then;
      D.then.seasons.forEach(function (row) { SEASONS[row[0]] = row; });
    }
    return SEASONS[key.slice(0, 7)] || null;
  }
  // What ENSO was doing around a date: the season centred on its month; after
  // the record, the latest season; before it, that there is none.
  function ensoWords(key) {
    var row = seasonAt(key), list = D.then.seasons, last = list[list.length - 1], index = D.then.index;
    if (row) return row[1] + ", centred on " + monthText(row[0]) + ": " + index + " " + signedText(row[2], 1) + ", " + row[3];
    if (last && key.slice(0, 7) > last[0]) {
      return "after the latest season on record, " + last[1] + " (" + index + " " + signedText(last[2], 1) + ", " + last[3] + ")";
    }
    return "no " + index + " season on record for " + monthText(key);
  }
  // The same, short, for a chip on the map; after the record, the latest.
  function ensoShort(key) {
    var row = seasonAt(key), list = D.then.seasons, last = list[list.length - 1];
    if (row) return D.then.index + " " + signedText(row[2], 1) + ", " + row[1];
    if (last && key.slice(0, 7) > last[0]) return "latest " + D.then.index + " " + signedText(last[2], 1) + ", " + last[1];
    return "";
  }
  function presetOf(id) {
    var list = D.then.presets;
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  // ---- Esri's archive: the versions of one place ------------------------------
  // Found as Esri's own Wayback app finds them: the tilemap of the newest
  // release names the release the tile at the pin last changed in; asked
  // again just older than that, it names the one before; and so on until the
  // tilemap has no tile there. Each version's metadata names the day its
  // imagery was taken, by whom and how sharp.
  var WAIT = 20000, WB = {all: null, asking: null, byId: {}, walks: {}, caps: {}, credits: {}};
  // An answer read as JSON (or text), or a rejection: a failure, a status
  // that is not OK, or no answer in 20 s (one metadata query took 60 s on
  // 29 Sep 2026), after which the request is given up.
  function fetchWait(url, text) {
    var ctl = typeof AbortController === "function" ? new AbortController() : null;
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { if (ctl) ctl.abort(); reject(new Error("no answer in 20 s")); }, WAIT);
      fetch(url, ctl ? {signal: ctl.signal} : undefined).then(function (r) {
        if (!r.ok) throw new Error("HTTP " + r.status);
        return text ? r.text() : r.json();
      }).then(function (v) { clearTimeout(timer); resolve(v); }, function (err) { clearTimeout(timer); reject(err); });
    });
  }
  // The releases, newest first, each with its id, its day, its item, its
  // metadata service and its tile template. Asked once; again after a failure.
  function wbReleases() {
    if (WB.all) return Promise.resolve(WB.all);
    if (WB.asking) return WB.asking;
    WB.asking = fetchWait(D.then.wayback.config).then(function (cfg) {
      var all = [];
      Object.keys(cfg || {}).forEach(function (id) {
        var e = cfg[id], m = /(\d{4}-\d\d-\d\d)/.exec((e && e.itemTitle) || "");
        if (!m || !e.itemURL || !e.metadataLayerUrl) return;
        all.push({id: +id, day: m[1], item: e.itemID, meta: e.metadataLayerUrl,
                  tiles: e.itemURL.replace("{level}", "{z}").replace("{row}", "{y}").replace("{col}", "{x}")});
      });
      if (!all.length) throw new Error("no releases");
      all.sort(function (p, q) { return p.day < q.day ? 1 : p.day > q.day ? -1 : 0; });
      WB.byId = {};
      all.forEach(function (r, i) { r.i = i; WB.byId[r.id] = r; });
      WB.all = all;
      return all;
    });
    WB.asking.catch(function () { WB.asking = null; });
    return WB.asking;
  }
  // The tile under the pin at the zoom it is walked at, its column in the world.
  function wbTile(lon, lat) {
    var z = D.then.wayback.level, n = Math.pow(2, z);
    var x = Math.floor(mx(wrap(lon)) * n), y = Math.floor(clamp(my(lat), 0, 1 - 1e-9) * n);
    return {z: z, x: ((x % n) + n) % n, y: y};
  }
  // The releases whose imagery changed at the tile, newest first, and why the
  // walk stopped short if it did: "failed" (a tilemap did not answer) or
  // "unknown" (it named a release the list does not hold). A whole walk is
  // kept; one cut short is walked again.
  function wbWalk(all, t) {
    var key = t.z + "/" + t.y + "/" + t.x, found = [], i = 0;
    if (WB.walks[key]) return Promise.resolve(WB.walks[key]);
    function next() {
      if (i >= all.length) return Promise.resolve("");
      var rel = all[i], url = D.then.wayback.tilemap.replace("{release}", rel.id)
        .replace("{z}", t.z).replace("{y}", t.y).replace("{x}", t.x);
      return fetchWait(url).then(function (tm) {
        if (!tm || !tm.data || tm.data[0] !== 1) return "";
        var sel = tm.select && tm.select.length ? WB.byId[tm.select[0]] : rel;
        if (!sel) return "unknown";
        if (found.indexOf(sel) < 0) found.push(sel);
        i = Math.max(sel.i, i) + 1;
        return next();
      }, function () { return "failed"; });
    }
    return next().then(function (stopped) {
      var walk = {list: found, stopped: stopped};
      if (!stopped) WB.walks[key] = walk;
      return walk;
    });
  }
  // When, by whom and how sharp a version's imagery at a point is, from its
  // metadata at the walk's zoom; null where it does not say. An answer is
  // kept; a failure is asked again next time.
  function wbCapture(v, lon, lat) {
    var key = v.id + "@" + lon.toFixed(5) + "," + lat.toFixed(5);
    if (key in WB.caps) return Promise.resolve(WB.caps[key]);
    var url = v.meta + "/" + D.then.wayback.metadata_layer + "/query?geometry=" + wrap(lon).toFixed(6) + "," +
      lat.toFixed(6) + "&geometryType=esriGeometryPoint&inSR=4326&spatialRel=esriSpatialRelIntersects" +
      "&outFields=*&returnGeometry=false&f=json";
    return fetchWait(url).then(function (got) {
      var a = got && got.features && got.features[0] && got.features[0].attributes;
      var m = a && /^(\d{4})(\d\d)(\d\d)$/.exec(String(a.SRC_DATE));
      var cap = m ? {day: m[1] + "-" + m[2] + "-" + m[3], provider: a.NICE_DESC || "", sensor: a.SRC_DESC || "",
                     res: typeof a.SRC_RES === "number" ? a.SRC_RES : null} : null;
      WB.caps[key] = cap;
      return cap;
    }, function () { return null; });
  }
  // The versions at a point: each release walked, with its capture; those
  // sharing a capture day are one, kept as the newest release; newest
  // capture first. A version whose capture is not given goes by its release,
  // and so does one whose capture has not answered 3 s after the walk: the
  // versions as they stand then go to early(), before the last capture.
  var CAPS_WAIT = 3000;
  function wbVersions(lon, lat, early) {
    return wbReleases().then(function (all) {
      return wbWalk(all, wbTile(lon, lat)).then(function (walk) {
        var caps = walk.list.map(function () { return null; }), timer = 0;
        function listed() {
          var list = [], days = {};
          walk.list.forEach(function (r, j) {
            var cap = caps[j];
            if (cap && days[cap.day]) return;
            if (cap) days[cap.day] = true;
            list.push({id: r.id, day: r.day, item: r.item, tiles: r.tiles, capture: cap,
                       when: cap ? cap.day : r.day, credit: WB.credits[r.item] || ""});
          });
          list.sort(function (p, q) { return p.when < q.when ? 1 : p.when > q.when ? -1 : 0; });
          return {list: list, stopped: walk.stopped};
        }
        if (early) timer = setTimeout(function () { early(listed()); }, CAPS_WAIT);
        return Promise.all(walk.list.map(function (r, j) {
          return wbCapture(r, lon, lat).then(function (cap) { caps[j] = cap; });
        })).then(function () { clearTimeout(timer); return listed(); });
      });
    }, function () { return {list: [], stopped: "config"}; });
  }
  // The version captured nearest a date, the earlier on a tie.
  function wbNearest(list, key) {
    var best = null, gap = Infinity, t = dayNo(key);
    (list || []).forEach(function (v) {
      var d = Math.abs(dayNo(v.when) - t);
      if (d < gap || (d === gap && v.when < best.when)) { gap = d; best = v; }
    });
    return best;
  }
  // A release's own credit, from its item; World Imagery's until that answers.
  function wbCredit(item) {
    if (WB.credits[item]) return Promise.resolve(WB.credits[item]);
    return fetchWait(D.then.wayback.item.replace("{id}", item)).then(function (got) {
      var words = got && typeof got.accessInformation === "string" ? got.accessInformation.trim() : "";
      if (words) WB.credits[item] = words;
      return words || D.then.wayback.credit;
    }, function () { return D.then.wayback.credit; });
  }
  // ---- the two sides, as layers of the page's own kinds -----------------------
  // A place entered: where, what shows it, the dates asked for (want) and
  // found (got) on each side, and what the map showed before (back).
  function thenFresh(o) {
    return {lon: o.lon, lat: o.lat, label: o.label, source: o.source, preset: "now",
            want: {a: null, b: null}, got: {a: null, b: null}, note: {a: "", b: ""},
            look: {a: "", b: ""}, ask: {a: 0, b: 0}, read: null, readKey: "", apart: "", order: "",
            versions: null, stopped: "", names: true, fail: {gibs: false, wayback: false},
            link: "", copy: false, back: o.back};
  }
  function thenVersion(T, id) {
    var list = (T && T.versions) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
  // One side as a layer: Esri's archive as a map of one release's tiles;
  // Landsat and Sentinel-2 as the desk's two HLS layers at the side's day;
  // NASA's others as one GIBS layer at the side's time. A side with no time
  // draws nothing: never today's.
  function thenLayer(T, k) {
    var src = thenSrc(T.source), got = T.got[k], l;
    if (src.kind === "wayback") {
      // The release's credit is a sentence of its own before the names' credit.
      var v = thenVersion(T, got), words = (v && v.credit) || D.then.wayback.credit;
      l = {kind: "map", name: src.name, source: src.name, zoom: src.zoom, grey: false,
           wayback: v ? v.id : 0, tiles: v ? v.tiles : null, nodata: v ? "wb" + v.id : "wb",
           credit: "Powered by Esri. Source: " + words + (/[.!?]$/.test(words) ? "" : ".")};
    } else if (src.kind === "hls") {
      var d = LAYERS.detail || {};
      l = {kind: "imagery", name: src.name, stack: d.stack, tms: d.tms, zoom: d.zoom, format: d.format,
           step: "P1D", pixel_km: src.pixel_km, credit: src.credit, time: got || null};
    } else {
      l = {kind: "imagery", name: src.name, global: src.layer, tms: src.tms, zoom: src.tile_zoom,
           format: src.format, step: "P1D", pixel_km: src.pixel_km, credit: src.credit, time: got || null};
    }
    l.id = "then-" + k;
    l.then = true;
    // Esri's roads and names over either side while the switch is on,
    // credited with Esri's words where the side is not Esri's own.
    l.over = T.names && LAYERS.satellite ? LAYERS.satellite.over : null;
    l.overCredit = (src.kind === "wayback" ? "" : "Powered by Esri. ") + D.then.names_credit;
    return l;
  }
  // The two sides registered and compared; again after a refresh rebuilds LAYERS.
  function thenApply() {
    var T = S.then;
    if (!T) return;
    LAYERS["then-a"] = thenLayer(T, "a");
    LAYERS["then-b"] = thenLayer(T, "b");
    S.layer = "then-a"; S.second = "then-b"; S.compare = true;
  }
  // A tile of Esri's archive that did not come, past zoom 13: its release's
  // tilemap says whether it has a tile there. None is Esri's answer that it
  // has nothing finer, and the coarser tile is drawn, as for World Imagery's
  // grey tile; anything else, no answer included, fails as any map tile does.
  function wbAsk(img) {
    img._asked = true;
    var m = Math.pow(2, img._z), c = ((img._c % m) + m) % m;
    var url = D.then.wayback.tilemap.replace("{release}", img._wb).replace("{z}", img._z)
      .replace("{y}", img._r).replace("{x}", c);
    fetchWait(url).then(function (tm) { return !(tm && tm.data && tm.data[0] === 1); },
                        function () { return false; }).then(function (gone) {
      if (!gone) { tileFailed.call(img); return; }
      NODATA[img._name + "/" + img._z + "/" + c + "/" + img._r] = true;
      requestRender();
    });
  }
  // ---- each side's date found in its archive ----------------------------------
  // A layer's times from GIBS, from the archive's first day to tomorrow:
  // asked once a visit, and again after a failure.
  var SPANS = {}, SPANS_GOT = {};
  function thenSpans(src) {
    if (SPANS[src.id]) return SPANS[src.id];
    var url = D.gibs.domains.replace("{layer}", src.layer).replace("{tms}", src.tms)
      .replace("{start}", src.first).replace("{end}", dayZ(Date.now() + DAY));
    SPANS[src.id] = fetchWait(url, true).then(function (text) {
      var spans = parseSpans(text);
      if (!spans.length) throw new Error("no times");
      SPANS_GOT[src.id] = spans;
      S.imagery = "ok";
      return spans;
    });
    SPANS[src.id].catch(function () { delete SPANS[src.id]; });
    return SPANS[src.id];
  }
  // A date outside what an archive holds, said as that. A date past the
  // latest by a month or less is the latest, as "the latest" means.
  function clampNote(first, last, key) {
    if (key < first) return "asked for " + dayText(key) + ", before the first it holds, " + dayText(first);
    if (dayNo(key) - dayNo(last) > 31) return "asked for " + dayText(key) + ", after the latest it holds, " + dayText(last);
    return "";
  }
  // An event's two dates that land on the same image or capture: the left
  // side takes the one before it, where there is one, and says so. A pair
  // the reader chose is left as chosen.
  function thenApart(T, older, what) {
    T.apart = "";
    if (!T.preset || T.got.a === null || T.got.a !== T.got.b) return;
    var before = older(T.got.a);
    if (before === null) return;
    T.got.a = before;
    T.apart = "Both dates fell on the same " + what + ", so the left side shows the one before it.";
  }
  // The earlier date on the left, once neither side is still being found;
  // the sides changing places is said, until the reader's next date.
  function thenOrder(T) {
    if (T.look.a || T.look.b) return;
    var a = sideDay(T, "a"), b = sideDay(T, "b");
    if (!a || !b || a <= b) return;
    ["want", "got", "note", "look"].forEach(function (f) { var v = T[f].a; T[f].a = T[f].b; T[f].b = v; });
    T.order = "The earlier date goes on the left, so the two sides changed places.";
  }
  // The event's dates given up for the reader's own: a side the event moved
  // apart keeps the date it shows, so asking both sides again does not put
  // them back on one image.
  function thenOwnDates(T) {
    if (T.apart && !T.look.a && T.got.a !== null) T.want.a = sideDay(T, "a");
    T.preset = ""; T.apart = ""; T.order = "";
  }
  // The day shown on a side: its capture's for Esri's archive, else its
  // time; the date asked for until one is found.
  function sideDay(T, k) {
    if (thenSrc(T.source).kind === "wayback") {
      var v = thenVersion(T, T.got[k]);
      return v ? v.when : T.want[k];
    }
    return T.got[k] || T.want[k];
  }
  // NASA's daily and 16-day layers: each side at the time GIBS lists
  // nearest its date. Asked again quietly (thenAskAgain), the sides stand as
  // they are until GIBS answers, and stay so if it does not.
  function thenGibs(T, src, quiet) {
    var q = {a: ++T.ask.a, b: ++T.ask.b};
    if (!quiet) {
      T.look.a = T.look.b = "asking";
      thenChanged();
    }
    thenSpans(src).then(function (spans) {
      if (T !== S.then || T.source !== src.id) return;
      T.fail.gibs = false;
      ["a", "b"].forEach(function (k) {
        if (q[k] !== T.ask[k]) return;
        T.got[k] = snapTime(spans, T.want[k]);
        T.note[k] = clampNote(spans[0][0], spans[spans.length - 1][1], T.want[k]);
        T.look[k] = "";
      });
      thenApart(T, function (key) { return stepTime(spans, key, -1); }, "image");
      thenOrder(T);
      thenChanged();
    }, function () {
      if (T !== S.then || T.source !== src.id || quiet) return;
      T.fail.gibs = true;
      ["a", "b"].forEach(function (k) { if (q[k] === T.ask[k]) T.look[k] = NO_ANSWER; });
      thenChanged();
    });
  }
  // Esri's archive: the versions of the place, and on each side the one
  // captured nearest its date. The versions already drawn stay while a
  // moved pin's are found; a capture slow to answer is found again when it does.
  function thenArchive(T) {
    var lon = T.lon, lat = T.lat, q = {a: ++T.ask.a, b: ++T.ask.b};
    if (!T.versions) T.look.a = T.look.b = "asking";
    thenChanged();
    function show(got) {
      if (T !== S.then || T.source !== "archive" || T.lon !== lon || T.lat !== lat) return;
      var list = got.list;
      T.versions = list; T.stopped = got.stopped;
      T.fail.wayback = got.stopped === "config" || (got.stopped === "failed" && !list.length);
      ["a", "b"].forEach(function (k) {
        // A capture picked while the versions were asked for stands, if it is one of them.
        if (q[k] !== T.ask[k] && thenVersion(T, T.got[k])) return;
        var v = wbNearest(list, T.want[k]);
        T.got[k] = v ? v.id : null;
        T.look[k] = T.fail.wayback ? NO_ANSWER : v ? "" : "none";
        T.note[k] = v ? clampNote(list[list.length - 1].when, list[0].when, T.want[k]) : "";
      });
      thenApart(T, function (id) {
        var i = list.indexOf(thenVersion(T, id));
        return i >= 0 && i + 1 < list.length ? list[i + 1].id : null;
      }, "capture");
      thenOrder(T);
      thenCredits(T);
      thenChanged();
    }
    wbVersions(lon, lat, show).then(show);
  }
  // Each version shown credited in its release's own words.
  function thenCredits(T) {
    ["a", "b"].forEach(function (k) {
      var v = thenVersion(T, T.got[k]);
      if (!v || v.credit) return;
      wbCredit(v.item).then(function (words) {
        v.credit = words;
        if (T === S.then) thenChanged();
      });
    });
  }
  // Landsat and Sentinel-2: the pin's tile at the detail layer's zoom, and
  // on each side the nearest day with an image there, looked for as the
  // detail layer looks: the tile the map draws, read at the pin.
  function hlsTile(lon, lat) {
    var z = LAYERS.detail.zoom, n = Math.pow(2, z);
    var x = mx(wrap(lon)) * n, y = clamp(my(lat), 0, 1 - 1e-9) * n;
    return {z: z, c: ((Math.floor(x) % n) + n) % n, r: Math.floor(y), fx: x - Math.floor(x), fy: y - Math.floor(y)};
  }
  // The days to look at: from a date, the day itself, then a day either side
  // at a time to 20 days (by 0); or the 60 days one way (by -1 or +1).
  function hlsDays(from, by, first, last) {
    var out = [], i;
    if (!by) {
      out.push(from);
      for (i = 1; i <= 20; i++) out.push(shiftDay(from, -i), shiftDay(from, i));
    } else for (i = 1; i <= 60; i++) out.push(shiftDay(from, by * i));
    return out.filter(function (d) { return d >= first && d <= last; });
  }
  // The first day of the list with an image at the pin, six days asked at a
  // time; NO_ANSWER where a whole six went unanswered; null for none.
  function hlsHunt(days, t, still) {
    var batch = days.slice(0, 6);
    if (!batch.length || !still()) return Promise.resolve(null);
    return Promise.all(batch.map(function (day) { return imageOn(day, t); })).then(function (all) {
      for (var i = 0; i < all.length; i++) if (all[i] === true) return batch[i];
      if (all.every(function (a) { return a === null; })) return NO_ANSWER;
      return hlsHunt(days.slice(6), t, still);
    });
  }
  // Asked again quietly (thenAskAgain), a side moves only to a day found.
  function thenHls(T, k, by, quiet) {
    var src = thenSrc("hls"), q = ++T.ask[k], lon = T.lon, lat = T.lat, today = dayZ(Date.now());
    var from = by ? T.got[k] : T.want[k];
    if (!from) return;
    if (!by) {
      T.note[k] = clampNote(src.first, today, from);
      from = from < src.first ? src.first : from > today ? today : from;
    }
    function still() { return T === S.then && T.source === "hls" && T.ask[k] === q && T.lon === lon && T.lat === lat; }
    if (!quiet) {
      T.look[k] = "looking";
      thenChanged();
    }
    hlsHunt(hlsDays(from, by, src.first, today), hlsTile(lon, lat), still).then(function (day) {
      if (!still() || (quiet && (day === null || day === NO_ANSWER))) return;
      T.look[k] = "";
      if (day === NO_ANSWER) { T.look[k] = NO_ANSWER; T.fail.gibs = true; }
      else if (day) {
        T.got[k] = day; T.fail.gibs = false; S.imagery = "ok";
        if (by) { T.want[k] = day; T.note[k] = ""; }
      } else if (by) T.note[k] = "no " + (by < 0 ? "earlier" : "later") + " day with an image here within 60 days";
      else { T.got[k] = null; T.look[k] = "none"; }
      thenOrder(T);
      thenChanged();
    });
  }
  // Each side found again in the source's archive.
  function thenResolve() {
    var T = S.then;
    if (!T) return;
    var src = thenSrc(T.source);
    if (S.imagery === "offline") {
      T.fail[src.kind === "wayback" ? "wayback" : "gibs"] = true;
      thenChanged();
      return;
    }
    if (src.kind === "wayback") thenArchive(T);
    else if (src.kind === "hls") { thenHls(T, "a", 0); thenHls(T, "b", 0); }
    else thenGibs(T, src);
  }
  // NASA asked again for each side's day after a refresh, so the latest is
  // the latest: quietly, the sides standing as they are, words and reading
  // too, until an answer moves one; no answer leaves them. Esri's captures
  // stay as they were found.
  function thenAskAgain(T) {
    var src = thenSrc(T.source);
    if (src.kind === "wayback" || S.imagery === "offline" || thenFinding(T)) return;
    if (src.kind === "hls") { thenHls(T, "a", 0, true); thenHls(T, "b", 0, true); }
    else thenGibs(T, src, true);
  }
  function thenChanged() {
    thenApply(); thenRead(); dirty();
    // A link asked for while the sides were being found is made now they are.
    if (S.then && S.then.copy && !thenFinding(S.then)) thenCopy();
  }
  // Whether a side is still being found.
  function thenFinding(T) {
    return ["a", "b"].some(function (k) { return T.look[k] === "asking" || T.look[k] === "looking"; });
  }
  // ---- the bar: each side's date and the season around it ---------------------
  // What a side is waiting on, or why it has nothing, in words.
  function lookWords(T, k) {
    var kind = thenSrc(T.source).kind, look = T.look[k];
    if (kind === "wayback") {
      return look === "asking" ? "asking Esri’s archive for the versions here"
           : look === NO_ANSWER ? "Esri’s archive did not answer" : "Esri’s archive has no imagery here";
    }
    if (look === "asking") return "asking NASA GIBS for its days";
    if (look === "looking") return "looking for a day with an image here";
    if (look === NO_ANSWER) return "NASA GIBS did not answer";
    return "no image here within 20 days of " + dayText(T.want[k]);
  }
  // The chip on the map: the side's date, and the season around it.
  function chipText(T, k) {
    var day = sideDay(T, k);
    if (!day) return "";
    var extra = T.look[k] ? lookWords(T, k) : ensoShort(day);
    return dayText(day) + (extra ? " · " + extra : "");
  }
  // Under a side's date in the bar: the season in full.
  function sideWords(T, k) {
    var day = sideDay(T, k), words = T.look[k] ? lookWords(T, k) : day ? ensoWords(day) : "";
    return words ? words.charAt(0).toUpperCase() + words.slice(1) + "." : "";
  }
  // Written only when changed, so a control being used is not disturbed.
  function setText(el, text) { if (el.textContent !== text) el.textContent = text; }
  function setMarkup(el, html) { if (el.innerHTML !== html) el.innerHTML = html; }
  function setHidden(el, on) { if (el.hidden !== on) el.hidden = on; }
  function setValue(el, v) { if (el.value !== v) el.value = v; }
  // Whether a side can step back (by -1) or on (by +1) from its date.
  function thenCan(T, k, by) {
    var src = thenSrc(T.source), got = T.got[k];
    if (got === null || T.look[k]) return false;
    if (src.kind === "wayback") {
      var list = T.versions || [], i = list.indexOf(thenVersion(T, got));
      return i >= 0 && (by < 0 ? i < list.length - 1 : i > 0);
    }
    if (src.kind === "hls") return by < 0 ? got > src.first : got < dayZ(Date.now());
    var spans = SPANS_GOT[src.id];
    return !!spans && stepTime(spans, got, by) !== null;
  }
  // A version as its menu names it, and in full.
  function resText(m) { return m < 1 ? Math.round(m * 100) + " cm" : Math.round(m * 10) / 10 + " m"; }
  function captureShort(v) { return dayText(v.when) + (v.capture ? "" : " (release)"); }
  function captureText(v) {
    var c = v.capture;
    if (!c) return "capture date not given, first shown in the " + dayText(v.day) + " release";
    var by = [c.provider, c.sensor].filter(Boolean).join(", ");
    return "taken " + dayText(c.day) + (by ? " by " + by : "") + (c.res !== null ? " at " + resText(c.res) : "") +
      ", first shown in the " + dayText(v.day) + " release";
  }
  function thenCaptures(T, cap, k) {
    var list = T.versions || [], key = list.map(function (v) { return v.id + ":" + v.when; }).join(",");
    if (cap._key !== key) {
      cap._key = key;
      cap.innerHTML = list.map(function (v) {
        return '<option value="' + v.id + '">' + esc(captureShort(v)) + "</option>";
      }).join("");
    }
    setValue(cap, T.got[k] === null ? "" : String(T.got[k]));
  }
  // What was read at the pin on the two sides: the archive's captures, the
  // days found, or the value of NASA's scale under the pin and the change.
  function thenReadText(T) {
    var src = thenSrc(T.source), names = {a: "Left", b: "Right"}, out = [];
    if (src.kind === "wayback") {
      ["a", "b"].forEach(function (k) {
        var v = thenVersion(T, T.got[k]);
        if (v) out.push(names[k] + ": " + captureText(v) + ".");
      });
      return out.join(" ");
    }
    if (src.kind === "hls") {
      ["a", "b"].forEach(function (k) {
        var got = T.got[k], want = T.want[k];
        if (!got || T.look[k]) return;
        out.push(names[k] + ": " + (got === want ? "an image here on " + dayText(got)
          : "the nearest day with an image here to " + dayText(want) + " is " + dayText(got)) + ".");
      });
      return out.join(" ");
    }
    var r = T.read;
    if (!r) return "";
    var digits = src.id === "sst" ? 1 : 3, unit = src.id === "sst" ? " °C" : "";
    var text = "At the pin, left: " + (r.a.label || r.a.none) + "; right: " + (r.b.label || r.b.none);
    if (r.a.label && r.b.label) {
      text += r.a.open || r.b.open ? "; the change runs past the end of NASA’s scale"
        : "; a change of about " + signedText(r.b.mid - r.a.mid, digits) + unit;
    }
    return text + ".";
  }
  // The rest the reader should know: dates outside an archive, a side moved
  // apart, how much Esri's archive answered, the link, and what is not drawn.
  var HIDDEN = "While a place is entered, the storm picked stays, with its forecast to play over the place; " +
    "today’s other storms, outlook areas, NASA’s reference overlays, the ocean and flood tiles and " +
    "the El Niño composite are not drawn: they belong to today, not to either date.";
  function thenNotes(T) {
    var src = thenSrc(T.source), names = {a: "Left", b: "Right"}, out = [];
    ["a", "b"].forEach(function (k) { if (T.note[k]) out.push(names[k] + ": " + T.note[k] + "."); });
    if (T.order) out.push(T.order);
    if (T.apart) out.push(T.apart);
    if (src.kind === "wayback" && T.versions) {
      if (T.versions.length === 1) out.push("Esri’s archive holds one version of this place, so both sides show it.");
      if (T.stopped === "failed") out.push("Esri’s archive stopped answering partway, so older versions may be missing.");
      if (T.stopped === "unknown") out.push("Esri’s archive named a release its list does not hold, so older versions may be missing.");
      if (T.versions.some(function (v) { return !v.capture; })) {
        out.push("A version whose capture date Esri’s metadata did not give is named by the release that first showed it.");
      }
    }
    if (T.link) out.push(T.link);
    out.push(HIDDEN);
    return out.join(" ");
  }
  // One pixel of a NASA tile at a point: its RGBA; null where the tile
  // cannot be read; false where it did not come.
  function thenPixel(src, day, lon, lat) {
    var z = src.tile_zoom, n = Math.pow(2, z), x = mx(wrap(lon)) * n, y = clamp(my(lat), 0, 1 - 1e-9) * n;
    var c = ((Math.floor(x) % n) + n) % n, r = Math.floor(y);
    var px = Math.floor((x - Math.floor(x)) * 256), py = Math.floor((y - Math.floor(y)) * 256);
    return new Promise(function (done) {
      var img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = function () {
        try {
          var cv = document.createElement("canvas");
          cv.width = cv.height = 256;
          var cx = cv.getContext("2d", {willReadFrequently: true});
          cx.drawImage(img, 0, 0, 256, 256);
          done(cx.getImageData(px, py, 1, 1).data);
        } catch (err) { done(null); }
      };
      img.onerror = function () { done(false); };
      img.src = tileUrl({name: src.layer, tms: src.tms, ext: src.format}, day, z, r, c);
    });
  }
  function binMid(e) { return e.lo === null ? e.hi : e.hi === null ? e.lo : (e.lo + e.hi) / 2; }
  function readOne(src, day, lon, lat) {
    return thenPixel(src, day, lon, lat).then(function (px) {
      if (px === false) return {none: "its tile did not arrive"};
      if (!px) return {none: "its tile could not be read"};
      var e = classify(D.then.scales[src.id], px);
      if (!e) return {none: "a colour off NASA’s scale"};
      if (e.transparent) return {none: src.id === "sst" ? "no data (land, ice or a gap)" : "no data (water, cloud or a gap)"};
      return {label: e.label, mid: binMid(e), open: e.lo === null || e.hi === null};
    });
  }
  // The two sides read at the pin, once for each pair of dates and place.
  function thenRead() {
    var T = S.then;
    if (!T) return;
    var src = thenSrc(T.source);
    if (!D.then.scales[src.id] || !T.got.a || !T.got.b || T.look.a || T.look.b) { T.read = null; T.readKey = ""; return; }
    var key = src.id + "|" + T.got.a + "|" + T.got.b + "|" + T.lon.toFixed(4) + "|" + T.lat.toFixed(4);
    if (key === T.readKey) return;
    T.readKey = key; T.read = null;
    Promise.all([readOne(src, T.got.a, T.lon, T.lat), readOne(src, T.got.b, T.lon, T.lat)]).then(function (two) {
      if (S.then !== T || T.readKey !== key) return;
      T.read = {a: two[0], b: two[1]};
      dirty();
    });
  }
  // The bar and the chips, drawn with the map.
  function thenRender() {
    var T = S.then, src = thenSrc(T.source), archive = src.kind === "wayback", cut = S.split * S.w;
    // The chips stand clear of the credit, however many lines it wraps to.
    var creditBox = $("credit"), lift = Math.round(((creditBox && creditBox.offsetHeight) || 17) + 9) + "px";
    // The picker reaches today, however many days ago the page was built.
    var today = dayZ(Date.now());
    setValue($("then-source"), T.source);
    setValue($("then-event"), T.preset);
    if ($("then-names").checked !== T.names) $("then-names").checked = T.names;
    ["a", "b"].forEach(function (k) {
      var date = $("then-date-" + k), cap = $("then-cap-" + k), day = sideDay(T, k);
      if (date.getAttribute("max") !== today) date.setAttribute("max", today);
      setHidden(date, archive);
      setHidden(cap, !archive);
      if (!archive && document.activeElement !== date) setValue(date, day || "");
      if (archive) thenCaptures(T, cap, k);
      $("then-back-" + k).disabled = !thenCan(T, k, -1);
      $("then-next-" + k).disabled = !thenCan(T, k, 1);
      setText($("then-words-" + k), sideWords(T, k));
      var chip = $("then-chip-" + k), text = chipText(T, k);
      setText(chip, text);
      setHidden(chip, !text);
      if (k === "a") chip.style.right = Math.round(S.w - cut + 26) + "px";
      else chip.style.left = Math.round(cut + 26) + "px";
      chip.style.bottom = lift;
      var line = $("then-line-" + k), x = String(day ? monthIndex(day) + 0.5 : -1);
      if (line.getAttribute("x1") !== x) { line.setAttribute("x1", x); line.setAttribute("x2", x); }
    });
    setText($("then-read"), thenReadText(T));
    setText($("then-note"), thenNotes(T));
    var href = googleLinks(T.lat, T.lon, S.z).street;
    if ($("then-gmaps").getAttribute("href") !== href) $("then-gmaps").setAttribute("href", href);
    thenKey(T.source);
  }
  // ---- the bar's controls --------------------------------------------------------
  // A side a step back or on: the day before or after with an image here;
  // the older or newer version; the time GIBS lists before or after.
  function thenStep(k, by) {
    var T = S.then;
    if (!T || !thenCan(T, k, by)) return;
    var src = thenSrc(T.source);
    thenOwnDates(T);
    if (src.kind === "hls") { thenHls(T, k, by); return; }
    T.ask[k]++;
    if (src.kind === "wayback") {
      var list = T.versions, v = list[list.indexOf(thenVersion(T, T.got[k])) - by];
      T.got[k] = v.id; T.want[k] = v.when;
    } else T.got[k] = T.want[k] = stepTime(SPANS_GOT[src.id], T.got[k], by);
    T.note[k] = "";
    thenOrder(T);
    if (src.kind === "wayback") thenCredits(T);
    thenChanged();
  }
  // A date typed or picked for a side: a day of the calendar from 2000 to
  // today. One before 2000 or still to come is said and not taken; one that
  // is not a day, or a year still being typed (0201 on the way to 2015), is
  // let be. Either way the field shows the side's date again.
  function thenSetWant(k, text) {
    var T = S.then;
    if (!T || !realDay(text) || text === T.want[k]) return;
    if (text < "2000-01-01" || text > dayZ(Date.now())) {
      if (text < "1900") return;
      T.note[k] = "asked for " + dayText(text) + (text < "2000-01-01"
        ? ", before the first day the page offers, " + dayText("2000-01-01") : ", a day still to come");
      dirty();
      return;
    }
    thenOwnDates(T);
    T.want[k] = text;
    if (thenSrc(T.source).kind === "hls") thenHls(T, k, 0); else thenResolve();
  }
  function thenCapture(k, id) {
    var T = S.then, v = T && thenVersion(T, +id);
    if (!v) return;
    thenOwnDates(T);
    T.ask[k]++;
    T.got[k] = v.id; T.want[k] = v.when; T.note[k] = "";
    thenOrder(T);
    thenCredits(T);
    thenChanged();
  }
  // An event's two dates; "" keeps the dates as they are, as the reader's own.
  function thenPreset(id) {
    var T = S.then, p = presetOf(id);
    if (!T) return;
    if (!p) { thenOwnDates(T); thenChanged(); return; }
    T.preset = id; T.apart = ""; T.order = "";
    T.want = {a: p.left, b: p.right};
    thenResolve();
  }
  // Another archive for the same place and dates, flown to its own zoom.
  function thenSource(id) {
    var T = S.then, src = thenSrc(id);
    if (!T || !src || id === T.source) return;
    T.source = id;
    T.got = {a: null, b: null}; T.note = {a: "", b: ""}; T.look = {a: "", b: ""};
    T.read = null; T.readKey = ""; T.apart = ""; T.order = ""; T.fail = {gibs: false, wayback: false};
    T.ask.a++; T.ask.b++;
    thenApply();
    var z = clamp(src.enter, MINZ, src.zoom);
    animate({x: mx(T.lon) + near(mx(T.lon)), y: my(T.lat), z: z}, flightMs(z));
    thenResolve();
  }
  // A tap on the strip moves the nearer side to the 15th of that month.
  function thenStripAt(frac) {
    var T = S.then;
    if (!T) return;
    var n = D.then.strip.months, i = clamp(Math.floor(frac * n), 0, n - 1), from = D.then.strip.from;
    var m0 = +from.slice(5, 7) - 1 + i, key = (+from.slice(0, 4) + Math.floor(m0 / 12)) + "-" + pad2(m0 % 12 + 1) + "-15";
    var today = dayZ(Date.now());
    if (key > today) key = today;
    var a = sideDay(T, "a"), b = sideDay(T, "b");
    var k = !a ? "a" : !b ? "b" : Math.abs(dayNo(key) - dayNo(a)) <= Math.abs(dayNo(key) - dayNo(b)) ? "a" : "b";
    thenSetWant(k, key);
  }
  // A flight's length: longer the more zoom it crosses.
  function flightMs(z) { return clamp(600 + 200 * Math.abs(z - S.z), 600, 2000); }
  // A refresh brings a new build's event menu (its "now" names the new
  // build's months) and strip (its new seasons); the controls themselves,
  // and what listens to them, stay, and what the new build left as it was is
  // not written again, so a menu open stays open. Sides set by an event go to
  // the dates the new build gives it (a year ago and the latest move on each
  // day, a peak still to settle moves with it); sides on an event it no
  // longer offers keep their dates, as the reader's own. Dates that stand
  // have NASA asked again for their days, which the page forgets (the times
  // GIBS lists, the days with an image at the pin), so the latest is the latest.
  function thenRefreshed(doc) {
    var events = doc.getElementById("then-event"), strip = doc.getElementById("then-strip");
    var years = doc.getElementById("then-years");
    if (events) setMarkup($("then-event"), events.innerHTML);
    if (strip) {
      setMarkup($("then-strip"), strip.innerHTML);
      $("then-strip").setAttribute("viewBox", strip.getAttribute("viewBox"));
    }
    if (years) setMarkup($("then-years"), years.innerHTML);
    SPANS = {}; looks = {};
    var T = S.then, p = T && T.preset ? presetOf(T.preset) : null;
    if (!T) return;
    if (p && (p.left !== T.want.a || p.right !== T.want.b)) { thenPreset(p.id); return; }
    if (T.preset && !p) { thenOwnDates(T); thenChanged(); }
    thenAskAgain(T);
  }
  $("then-source").addEventListener("change", function (e) { thenSource(e.target.value); });
  $("then-event").addEventListener("change", function (e) { thenPreset(e.target.value); });
  $("then-names").addEventListener("change", function (e) {
    if (!S.then) return;
    S.then.names = e.target.checked;
    thenChanged();
  });
  ["a", "b"].forEach(function (k) {
    $("then-back-" + k).addEventListener("click", function () { thenStep(k, -1); });
    $("then-next-" + k).addEventListener("click", function () { thenStep(k, 1); });
    $("then-date-" + k).addEventListener("change", function (e) { thenSetWant(k, e.target.value); });
    $("then-date-" + k).addEventListener("blur", function () { requestRender(); });
    $("then-cap-" + k).addEventListener("change", function (e) { thenCapture(k, e.target.value); });
  });
  $("then-strip").addEventListener("click", function (e) {
    var r = $("then-strip").getBoundingClientRect();
    if (r.width > 0) thenStripAt((e.clientX - r.left) / r.width);
  });
  // ---- entering a place, and leaving it ----------------------------------------
  // A point is named by the page's placeLabel, as Here names one.
  // The archive first on land and near a town; the ocean's temperature at sea.
  function thenPick(lon, lat) {
    var land = false;
    try { land = cellAt("AIR", D.enso.now, lon, lat).value !== null; } catch (err) { /* no grid: towns decide */ }
    var p = nearestPlace(lon, lat);
    return land || (p && p.km <= 30) ? "archive" : "sst";
  }
  function thenShow(on) {
    setHidden($("then-bar"), !on);
    // Marked, the map keeps its height over the bar on a page that fits the window.
    map.classList.toggle("thenon", !!on);
    if (!on) { setHidden($("then-chip-a"), true); setHidden($("then-chip-b"), true); thenKey(""); }
    else document.querySelectorAll("[data-layer]").forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
  }
  // A longitude brought into -180 to 180, and left as it is when it is
  // already there, so the place entered is the place asked for.
  function lonIn(lon) { return lon >= -180 && lon < 180 ? lon : wrap(lon); }
  // The divider set by entering or leaving, and said where it is.
  function thenSplit(v) {
    S.split = v;
    divider.setAttribute("aria-valuenow", String(Math.round(v * 100)));
  }
  // Into a place: the pin, the two sides compared at the divider, and a
  // flight to the source's zoom. Entered already, the place moves and the
  // source, the dates and what Exit goes back to are kept. Asked for, an
  // event (opts.preset) sets the dates this build gives it; two dates
  // (opts.a, opts.b) are the reader's own; opts.names sets Esri's names.
  function thenEnter(lon, lat, label, opts) {
    opts = opts || {};
    lon = lonIn(lon); lat = clamp(lat, -85, 85);
    // Street View is the place's other view: entering this one leaves it.
    if (S.street) streetLeave();
    var old = S.then, src = thenSrc(opts.source) || (old && thenSrc(old.source)) || thenSrc(thenPick(lon, lat));
    var back = old ? old.back : {layer: S.layer, second: S.second, compare: S.compare, split: S.split, loop: S.loop};
    if (S.loop) setLoop(false);
    // However it is entered (a tap, Here, a link, the page's API), the map
    // stops waiting for a tap.
    if (S.arming) arm(false);
    var T = thenFresh({lon: lon, lat: lat, label: label || placeLabel(lon, lat), source: src.id, back: back});
    var p = presetOf(opts.preset);
    if (p) { T.preset = p.id; T.want = {a: p.left, b: p.right}; }
    else if (realDay(opts.a) && realDay(opts.b)) { T.preset = ""; T.want = {a: opts.a, b: opts.b}; }
    else if (old) { T.preset = old.preset; T.want = {a: old.want.a, b: old.want.b}; T.names = old.names; }
    else { p = presetOf("now"); T.want = {a: p.left, b: p.right}; }
    if (typeof opts.names === "boolean") T.names = opts.names;
    if (!old) thenSplit(0.5);
    S.then = T;
    thenApply();
    pin(lon, lat, T.label);
    thenShow(true);
    var z = clamp(opts.z || src.enter, MINZ, src.zoom), to = {x: mx(lon) + near(mx(lon)), y: my(lat), z: z};
    if (opts.instant) { cancelAnimationFrame(anim); anim = 0; S.x = to.x; S.y = to.y; S.z = to.z; settle(); }
    else animate(to, flightMs(z));
    thenResolve();
    return true;
  }
  // Out again, to the layers, comparison, divider and loop there were before.
  function thenLeave() {
    var T = S.then;
    if (!T) return false;
    S.then = null;
    S.thenLast = {source: T.source, preset: T.preset, a: T.want.a, b: T.want.b, names: T.names};
    delete LAYERS["then-a"]; delete LAYERS["then-b"];
    var b = T.back;
    S.second = b.second; S.compare = b.compare; thenSplit(b.split);
    setLayer(b.layer);
    setCompare(b.compare);
    // The loop that ran before, unless Play has been pressed since: of the
    // two, the reader's latest word is the one kept.
    if (b.loop && !S.playing) {
      // The loop runs over the frames in view, which are the sides' until the
      // map is drawn again: the layer put back is looked at first. Frames GIBS
      // has yet to give (a place entered across a load) start it once in view.
      S.inView = cells(S.layer, S.frame).used;
      if (!setLoop(true)) S.loopWanted = true;
    }
    if (S.here) pin(S.here.lon, S.here.lat, S.here.label); else S.pin = null;
    if (/^#then=/.test(location.hash)) {
      try { history.replaceState(null, "", location.href.split("#")[0]); } catch (err) { /* the address keeps it */ }
    }
    thenShow(false);
    dirty();
    return true;
  }
  // A tap while entered: the same dates at another place.
  function thenMove(lon, lat) {
    var T = S.then;
    if (!T) return;
    T.lon = lonIn(lon); T.lat = clamp(lat, -85, 85); T.label = placeLabel(T.lon, T.lat);
    T.read = null; T.readKey = ""; T.apart = ""; T.order = "";
    pin(T.lon, T.lat, T.label);
    thenResolve();
  }
  // For the page's API: where and what is entered.
  function thenView() {
    var T = S.then;
    return T ? {lon: T.lon, lat: T.lat, label: T.label, source: T.source, preset: T.preset,
                left: sideDay(T, "a"), right: sideDay(T, "b"), look: {a: T.look.a, b: T.look.b}} : null;
  }
  $("then-exit").addEventListener("click", function () { thenLeave(); });
  // ---- the figure: pressed, then a tap; or carried onto the map ---------------------
  // Pressed, the map waits for a tap (or Enter, for the middle of the view);
  // carried, a ring shows where it would land, and letting go there drops
  // into Street View (figureLand, street.py).
  S.arming = false;
  var fig = $("then-enter"), ghost = $("then-ghost"), landing = $("then-ring"), carry = null, carried = false;
  function arm(on) {
    S.arming = !!on;
    map.classList.toggle("arming", S.arming);
    setHidden($("then-hint"), !S.arming);
    fig.setAttribute("aria-pressed", S.arming ? "true" : "false");
  }
  // A pointer's place on the map, or null off it or over one of the map's
  // own controls (a pill, a chip, the zoom buttons): the figure is let go
  // there as over the toolbar, and enters nowhere.
  function overMap(e) {
    var r = map.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    if (!(x >= 0 && y >= 0 && x < r.width && y < r.height)) return null;
    var under = document.elementFromPoint ? document.elementFromPoint(e.clientX, e.clientY) : null;
    return under && under.closest && under.closest(".ui") ? null : {x: x, y: y};
  }
  function carryEnd(e, drop) {
    if (!carry || e.pointerId !== carry.id) return;
    var moved = carry.moved;
    carry = null;
    setHidden(ghost, true);
    setHidden(landing, true);
    if (!moved) return;
    // The click that follows letting go is not a press.
    carried = true;
    var at = drop ? overMap(e) : null;
    if (!at) return;
    var w = toWorld(at.x, at.y);
    arm(false);
    figureLand(lonOf(w.x), latOf(w.y));
  }
  fig.addEventListener("pointerdown", function (e) {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    carry = {id: e.pointerId, x0: e.clientX, y0: e.clientY, moved: false};
    carried = false;
    try { fig.setPointerCapture(e.pointerId); } catch (err) { /* a synthetic pointer */ }
  });
  fig.addEventListener("pointermove", function (e) {
    if (!carry || e.pointerId !== carry.id) return;
    if (!carry.moved && Math.hypot(e.clientX - carry.x0, e.clientY - carry.y0) < 8) return;
    // Picked up in the street, the figure is carried over the map.
    if (!carry.moved && S.street) streetLeave();
    carry.moved = true;
    setHidden(ghost, false);
    ghost.style.transform = "translate(" + Math.round(e.clientX) + "px," + Math.round(e.clientY) + "px)";
    var at = overMap(e);
    setHidden(landing, !at);
    if (at) landing.style.transform = "translate(" + Math.round(at.x) + "px," + Math.round(at.y) + "px)";
  });
  fig.addEventListener("pointerup", function (e) { carryEnd(e, true); });
  fig.addEventListener("pointercancel", function (e) { carryEnd(e, false); });
  fig.addEventListener("click", function () {
    if (carried) { carried = false; return; }
    // Pressed in the street, the map comes back to tap a place on.
    if (S.street) streetLeave();
    arm(!S.arming);
  });
  // Esc stops waiting for a tap, or leaves the place; Enter while waiting
  // drops into the middle of the view. Keys typed into a field are its own.
  document.addEventListener("keydown", function (e) {
    var t = e.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (t && t.closest && t.closest("#findform"))) return;
    if (e.key === "Escape") {
      if (S.arming) { arm(false); e.preventDefault(); }
      else if (S.then) { thenLeave(); e.preventDefault(); }
    } else if (e.key === "Enter" && S.arming) {
      e.preventDefault();
      arm(false);
      figureLand(lonOf(S.x), latOf(S.y));
    }
  });
  // ---- the pill, the status, the address ------------------------------------------
  // The pill while a place is entered: the place and the source, then one
  // line a side, and how far the view is past the source's own detail.
  function thenPill(head, more) {
    var T = S.then, src = thenSrc(T.source), names = {a: "Left", b: "Right"};
    if (S.imagery === "offline") head.push("Offline: " + src.name + " needs the network; the tiles already loaded stay.");
    else head.push(T.label + ": " + src.name + ", then and now");
    ["a", "b"].forEach(function (k) {
      var day = sideDay(T, k), v = src.kind === "wayback" ? thenVersion(T, T.got[k]) : null;
      more.push(names[k] + ": " + (day ? dayText(day) : "no date") +
                (T.look[k] ? ", " + lookWords(T, k) : day ? ", " + ensoWords(day) : "") +
                (v ? "; " + captureText(v) : "") + ".");
    });
    var l = LAYERS["then-a"];
    if (l && l.pixel_km && S.z > l.zoom + 0.2) {
      more.push("Enlarged " + Math.pow(2, S.z - l.zoom).toFixed(1) + " times past its " +
                (l.pixel_km < 1 ? Math.round(l.pixel_km * 1000) + " m" : l.pixel_km + " km") + " pixels.");
    }
    [S.inView["then-a"], S.inViewB && S.inViewB["then-b"]].forEach(function (drawn, i) {
      if (drawn && drawn.coarser !== null && drawn.coarser !== undefined) {
        more.push((i ? "Right" : "Left") + ": Esri’s archive has nothing finer than zoom " + drawn.coarser +
                  " for part of this view; that part is its zoom-" + drawn.coarser + " tile, enlarged.");
      }
    });
  }
  // The status pill's words while entered. A walk of Esri's archive cut
  // short may have missed older versions: the pill says so, with Retry.
  function thenDown() {
    var T = S.then;
    if (T.fail.wayback || mapDown("then-a") || mapDown("then-b")) return "Esri’s archive unreachable.";
    if (T.fail.gibs || nasaDown(S.inView) || (S.inViewB && nasaDown(S.inViewB))) return "Imagery unreachable.";
    if (thenSrc(T.source).kind === "wayback" && T.stopped && T.versions && T.versions.length) {
      return "Esri’s archive answered in part.";
    }
    return "";
  }
  // Retry: each side found again. A walk cut short is walked again, and one
  // that met a release the list does not hold asks for the list again.
  function thenRetry() {
    var T = S.then;
    if (T.stopped === "unknown") { WB.all = null; WB.asking = null; }
    T.fail = {gibs: false, wayback: false};
    thenResolve();
  }
  // The place, zoom, source and both dates, as an address to open again:
  // #then=lat,lon,zoom,source,left,right.
  function thenHash() {
    var T = S.then;
    return "#then=" + T.lat.toFixed(4) + "," + T.lon.toFixed(4) + "," + S.z.toFixed(2) + "," + T.source + "," +
      (sideDay(T, "a") || "") + "," + (sideDay(T, "b") || "");
  }
  function parseThen(text) {
    var m = /^#then=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?),(\d+(?:\.\d+)?),([a-z]+),(\d{4}-\d\d-\d\d),(\d{4}-\d\d-\d\d)$/.exec(text || "");
    if (!m) return null;
    var lat = +m[1], lon = +m[2], src = thenSrc(m[4]);
    if (!src || Math.abs(lat) > 90 || Math.abs(lon) > 360 || !realDay(m[5]) || !realDay(m[6])) return null;
    // A longitude inside the world is kept as written, as parseHash keeps it.
    lon = lonIn(lon);
    return {lat: lat, lon: lon, z: clamp(+m[3], MINZ, src.zoom), source: src.id, a: m[5], b: m[6]};
  }
  function thenHashApply(text) {
    var h = parseThen(text);
    if (!h) return false;
    return thenEnter(h.lon, h.lat, null, {source: h.source, a: h.a, b: h.b, z: h.z, instant: true});
  }
  // The link to this place and these dates: to the clipboard where the
  // browser allows it, and shown in the bar either way. Asked for while a
  // side is still being found, it is made once both are, so it holds the
  // dates the sides show, not the dates asked for: opened, those are the
  // reader's own, and an event's two sides on one capture stay on it.
  function thenCopy() {
    var T = S.then;
    if (!T) return;
    T.copy = thenFinding(T);
    if (T.copy) { T.link = "The link is copied once both sides are found."; dirty(); return; }
    var url = location.href.split("#")[0] + thenHash();
    T.link = "Copy this link: " + url;
    try {
      navigator.clipboard.writeText(url).then(function () {
        if (S.then === T) { T.link = "Link copied: " + url; dirty(); }
      }, function () { /* the link stays shown, to copy by hand */ });
    } catch (err) { /* no clipboard: the link stays shown */ }
    dirty();
  }
  // The place in Street View: the stage's Then and now the other way round,
  // its street found as a pick's is.
  function thenStreet() {
    var T = S.then;
    return T ? streetPick(T.lon, T.lat, S.z, T.label) : false;
  }
  $("then-copy").addEventListener("click", function () { thenCopy(); });
  $("then-street").addEventListener("click", function () { thenStreet(); });
  // ---- the key -------------------------------------------------------------------
  // The key under the map while a place is entered: NASA's own scale for the
  // source the readout reads, the ocean's or the vegetation index's; none
  // for the imagery, which has none. Today's storms and the marks the key to
  // the map explains are not drawn over another day, and their keys stand
  // aside with them (again after a refresh writes the key anew).
  function thenKey(id) {
    ["sst", "ndvi"].forEach(function (k) { setHidden($("then-" + k + "-key"), k !== id); });
    // Entered, today's storms stand aside but the one picked, which the map
    // still draws with its forecast badged, so the key to its marks stays.
    if ($("storm-key")) setHidden($("storm-key"), !!S.then);
    if ($("key-more")) setHidden($("key-more"), !!S.then && !S.selected);
  }

  // ---- the street: what El Nino does to the street dropped into (street.py) ----
  // The point's record, from POWER: one series a variable from the first
  // month on file, rec.from ("YYYY-MM"), rec.p rainfall in mm a day and rec.t
  // temperature in deg C, null for a month POWER has no value for.
  var SEASON_NAMES = ["DJF", "JFM", "FMA", "MAM", "AMJ", "MJJ", "JJA", "JAS", "ASO", "SON", "OND", "NDJ"];
  var MONTH_WORDS = "January February March April May June July August September October November December".split(" ");
  // A month of POWER's days is a month with this many of them.
  var DAYS_FULL = 25;
  function streetMean(list) {
    var sum = 0;
    list.forEach(function (v) { sum += v; });
    return sum / list.length;
  }
  function streetKey(y, m) { return y + "-" + pad2(m); }
  // Where a month ("YYYY-MM") falls in a series that starts at `from`.
  function streetIndexOf(from, key) {
    return (+key.slice(0, 4) - +from.slice(0, 4)) * 12 + (+key.slice(5, 7) - +from.slice(5, 7));
  }
  // One of POWER's values, null for its fill value or for anything else not
  // a number.
  function powerRead(v, fill) { return typeof v === "number" && isFinite(v) && v !== fill ? v : null; }
  // POWER's monthly answer as the record. Its thirteenth month, the year's
  // mean, is not a month; null when the answer holds no record.
  function powerMonths(json) {
    var par = json && json.properties && json.properties.parameter;
    var fill = json && json.header && typeof json.header.fill_value === "number" ? json.header.fill_value : -999;
    if (!par || !par.PRECTOTCORR || !par.T2M) return null;
    var keys = Object.keys(par.PRECTOTCORR).filter(function (k) {
      return /^\d{6}$/.test(k) && +k.slice(4) >= 1 && +k.slice(4) <= 12;
    }).sort();
    if (!keys.length) return null;
    var y = +keys[0].slice(0, 4), m = +keys[0].slice(4), last = keys[keys.length - 1];
    var rec = {from: streetKey(y, m), p: [], t: []};
    while (String(y) + pad2(m) <= last) {
      var k = String(y) + pad2(m);
      rec.p.push(powerRead(par.PRECTOTCORR[k], fill));
      rec.t.push(powerRead(par.T2M[k], fill));
      if (++m > 12) { m = 1; y++; }
    }
    return rec;
  }
  // The months the monthly record has not filled yet, from POWER's daily
  // answer: a month of DAYS_FULL days or more is the mean of its days; the
  // month under way is not a month yet, and stays empty.
  function powerFill(rec, json) {
    var par = json && json.properties && json.properties.parameter;
    var fill = json && json.header && typeof json.header.fill_value === "number" ? json.header.fill_value : -999;
    if (!rec || !par || !par.PRECTOTCORR || !par.T2M) return rec;
    var sums = {};
    Object.keys(par.PRECTOTCORR).forEach(function (k) {
      if (!/^\d{8}$/.test(k)) return;
      var key = k.slice(0, 4) + "-" + k.slice(4, 6), s = sums[key] || (sums[key] = {p: [], t: []});
      var p = powerRead(par.PRECTOTCORR[k], fill), t = powerRead(par.T2M[k], fill);
      if (p !== null) s.p.push(p);
      if (t !== null) s.t.push(t);
    });
    Object.keys(sums).sort().forEach(function (key) {
      var s = sums[key], i = streetIndexOf(rec.from, key);
      if (i < 0) return;
      while (rec.p.length <= i) { rec.p.push(null); rec.t.push(null); }
      if (rec.p[i] === null && s.p.length >= DAYS_FULL) rec.p[i] = streetMean(s.p);
      if (rec.t[i] === null && s.t.length >= DAYS_FULL) rec.t[i] = streetMean(s.t);
    });
    return rec;
  }
  // ---- the composite at the point, by the atlas composite's rules -------------------
  // The index centred on a month, as CPC prints it; null where it has none.
  function indexAt(y, m) {
    var I = D.street.months;
    if (!I.from) return null;
    var v = I.values[streetIndexOf(I.from, streetKey(y, m))];
    return typeof v === "number" ? v : null;
  }
  // The first month of the El Nino still under way, as the composite leaves
  // it out: from the last month on record back while the index stays at the
  // neutral bound or over it. Null when the record does not end in one.
  function ongoingFrom() {
    var I = D.street.months, v = I.values, i, from = null;
    for (i = v.length - 1; i >= 0; i--) {
      if (v[i] === null) continue;
      if (v[i] < D.street.neutral) break;
      from = i;
    }
    if (from === null) return null;
    var n = +I.from.slice(5, 7) - 1 + from;
    return streetKey(+I.from.slice(0, 4) + Math.floor(n / 12), n % 12 + 1);
  }
  // A month's phase: "warm" at the El Nino bound or over it, "base" strictly
  // inside the neutral one, else "skip", as is a month with no index or one
  // of the event under way (from `since` on).
  function phaseAt(y, m, since) {
    var v = indexAt(y, m);
    if (v === null || (since && streetKey(y, m) >= since)) return "skip";
    return v >= D.street.warm ? "warm" : Math.abs(v) < D.street.neutral ? "base" : "skip";
  }
  // The months of running season i (0 DJF to 11 NDJ), each as [its calendar
  // month, the years it lies from the season's middle month], which tags the
  // season: December's DJF is the next year's, January's NDJ the year before's.
  function seasonMonths(i) {
    return [-1, 0, 1].map(function (k) {
      var m = i + 1 + k;
      return m < 1 ? [12, -1] : m > 12 ? [1, 1] : [m, 0];
    });
  }
  // Season i at the point, rain (p) and temperature (t) apart: each El Nino
  // the mean of its El Nino months in the season and each neutral year the
  // mean of its neutral ones; the events' mean less the neutral years', with
  // Welch's t and the two-sided 95% point of Student's t at the smaller
  // sample less one. Short of the composite's events or years it says so and
  // gives the neutral mean alone. Rain's difference is given as a percentage
  // of the neutral mean too, as the atlas's percentOf gives it, where that
  // mean is the atlas's dry floor or more.
  function seasonOf(rec, i) {
    var R = D.street, since = ongoingFrom(), want = seasonMonths(i), warm = {}, base = {};
    var y0 = +rec.from.slice(0, 4), m0 = +rec.from.slice(5, 7) - 1;
    rec.p.forEach(function (_, n) {
      var y = y0 + Math.floor((m0 + n) / 12), m = (m0 + n) % 12 + 1;
      want.forEach(function (w) {
        if (w[0] !== m) return;
        var phase = phaseAt(y, m, since), into = phase === "warm" ? warm : phase === "base" ? base : null;
        if (into) (into[y - w[1]] || (into[y - w[1]] = [])).push(n);
      });
    });
    function samples(tags, v) {
      return Object.keys(tags).map(Number).sort(function (a, b) { return a - b; }).map(function (tag) {
        var got = tags[tag].map(function (n) { return rec[v][n]; }).filter(function (x) { return x !== null; });
        return got.length ? {tag: tag, value: streetMean(got)} : null;
      }).filter(Boolean);
    }
    function compare(v) {
      var w = samples(warm, v), b = samples(base, v);
      var out = {events: w, years: b.length, base: b.length ? streetMean(b.map(function (s) { return s.value; })) : null,
                 usable: false, diff: null, t: null, crit: null, percent: null};
      if (w.length < R.min_events || b.length < R.min_years) return out;
      var mw = streetMean(w.map(function (s) { return s.value; })), mb = out.base, vw = 0, vb = 0;
      w.forEach(function (s) { vw += (s.value - mw) * (s.value - mw); });
      b.forEach(function (s) { vb += (s.value - mb) * (s.value - mb); });
      vw /= Math.max(w.length - 1, 1); vb /= Math.max(b.length - 1, 1);
      var se = Math.sqrt(vw / w.length + vb / b.length);
      out.usable = true;
      out.diff = mw - mb;
      out.t = se > 1e-12 ? (mw - mb) / se : 0;
      out.crit = R.t975[Math.min(Math.max(Math.min(w.length, b.length) - 1, 1), R.t975.length) - 1];
      if (v === "p" && mb >= R.dry_floor) out.percent = (mw - mb) / mb * 100;
      return out;
    }
    return {season: i, name: SEASON_NAMES[i], p: compare("p"), t: compare("t")};
  }
  // Every running season at the point, DJF to NDJ.
  function streetYear(rec) { return SEASON_NAMES.map(function (_, i) { return seasonOf(rec, i); }); }
  // The latest running season the record has every month of, rain and
  // temperature both: this year so far, as season i of year `tag`.
  function streetLatest(rec) {
    var y0 = +rec.from.slice(0, 4), m0 = +rec.from.slice(5, 7) - 1;
    for (var n = rec.p.length - 1; n >= 2; n--) {
      var p = [rec.p[n - 2], rec.p[n - 1], rec.p[n]], t = [rec.t[n - 2], rec.t[n - 1], rec.t[n]];
      if (p.indexOf(null) >= 0 || t.indexOf(null) >= 0) continue;
      var mid = m0 + n - 1, i = mid % 12;
      return {season: i, name: SEASON_NAMES[i], tag: y0 + Math.floor(mid / 12), p: streetMean(p), t: streetMean(t)};
    }
    return null;
  }
  // An event named by the years its season spans, as the site names an
  // episode: DJF 1998 and NDJ 1997 are both 1997-98.
  function eventLabel(i, tag) {
    if (i === 0) return (tag - 1) + "-" + pad2(tag % 100);
    if (i === 11) return tag + "-" + pad2((tag + 1) % 100);
    return String(tag);
  }
  // ---- the card's sources, asked when the reader asks ------------------------------
  // Each source answers for the point to a hundredth of a degree, about a
  // kilometre, and its answer is kept for the tab's session, in memory and in
  // the tab's sessionStorage: a run taken in place, or the page loaded again
  // for one, shows the card it had without asking again. The weather now is
  // kept a quarter of an hour, as often as Open-Meteo's current conditions
  // change.
  var STREET_KINDS = ["monthly", "daily", "now", "ahead"], STREET_WAIT = 20000, NOW_KEPT = 900000, RECORD_KEPT = 86400000;
  var STREET_KEPT = {}, STREET_ASKED = {}, STREET_WHY = {}, STREET_STORE = "elnino-street-1:", STREET_POINTS = 20;
  // The point as each source is asked for it: to a hundredth of a degree, the
  // longitude from -180 (179.996 east is -180.00, and 0.004 south is 0.00).
  function streetPoint(lon, lat) {
    var x = Math.round(wrap(lon) * 100), y = Math.round(lat * 100);
    if (x >= 18000) x -= 36000;
    return {lon: ((x || 0) / 100).toFixed(2), lat: ((y || 0) / 100).toFixed(2)};
  }
  function streetCacheKey(kind, lon, lat) { var p = streetPoint(lon, lat); return kind + "|" + p.lat + "," + p.lon; }
  // Where a source is asked for a point, by the reader's own clock: POWER's
  // monthly record to this year, its daily one from the first of the month
  // three months back, past the months the monthly has yet to fill.
  function streetUrl(kind, lon, lat) {
    var p = streetPoint(lon, lat), now = new Date(Date.now());
    var back = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 3, 1));
    function day(d) { return d.getUTCFullYear() + pad2(d.getUTCMonth() + 1) + pad2(d.getUTCDate()); }
    return D.street.sources[kind].replace("{lat}", p.lat).replace("{lon}", p.lon)
      .replace("{year}", now.getUTCFullYear()).replace("{start}", day(back)).replace("{end}", day(now));
  }
  // One source asked, and given up after STREET_WAIT or the wait given; what
  // went wrong said as the card says it after the source's name ("Open-Meteo
  // answered 429"). Its answer read as JSON, or with `text` as text.
  function streetFetch(url, wait, text) {
    wait = wait || STREET_WAIT;
    return new Promise(function (resolve, reject) {
      var ctl = typeof AbortController === "function" ? new AbortController() : null, done = false;
      var timer = setTimeout(function () {
        if (ctl) ctl.abort();
        end(null, "did not answer within " + wait / 1000 + " s");
      }, wait);
      function end(json, why) {
        if (done) return;
        done = true;
        clearTimeout(timer);
        if (why) reject(streetFailure(why)); else resolve(json);
      }
      fetch(url, ctl ? {signal: ctl.signal} : undefined).then(function (r) {
        if (!r.ok) { end(null, "answered " + r.status); return; }
        (text ? r.text() : r.json()).then(function (body) { end(body, ""); },
                                          function () { end(null, "sent something that is not data"); });
      }, function () { end(null, "could not be reached"); });
    });
  }
  function streetFailure(why) { var e = new Error(why); e.why = why; return e; }
  // What is kept of each answer, in the shape the card reads: the record
  // read, POWER's days, the weather now with the next day's rain, ECMWF's
  // months; null for an answer with nothing for the point. Anything not a
  // number where one goes is no value, so an answer of another shape cannot
  // break the card; and what is kept reads again as itself.
  function streetTrim(kind, json) {
    if (!streetTable(json)) return null;
    if (kind === "monthly") return powerMonths(json);
    if (kind === "daily") {
      var par = json.properties && json.properties.parameter;
      if (!par || !streetTable(par.PRECTOTCORR) || !streetTable(par.T2M)) return null;
      return {header: {fill_value: streetTable(json.header) ? streetNumber(json.header.fill_value) : null},
              properties: {parameter: {PRECTOTCORR: streetDays(par.PRECTOTCORR), T2M: streetDays(par.T2M)}}};
    }
    if (kind === "now") {
      var c = json.current, h = json.hourly, now = {};
      if (!streetTable(c)) return null;
      ["time", "temperature_2m", "weather_code", "wind_speed_10m", "wind_direction_10m", "wind_gusts_10m"].forEach(function (k) {
        var v = k === "time" ? (typeof c[k] === "string" ? c[k] : null) : streetNumber(c[k]);
        if (v !== null) now[k] = v;
      });
      return {current: now, hourly: streetTable(h) && Array.isArray(h.precipitation) ? {precipitation: streetNumbers(h.precipitation)} : null,
              timezone_abbreviation: typeof json.timezone_abbreviation === "string" ? json.timezone_abbreviation : ""};
    }
    var m = json.monthly, out = {};
    if (!streetTable(m) || !Array.isArray(m.time)) return null;
    if (!m.time.every(function (t) { return typeof t === "string" && /^\d{4}-\d{2}/.test(t); })) return null;
    out.time = m.time.slice();
    ["temperature_2m_anomaly", "precipitation_mean", "precipitation_anomaly", "sea_surface_temperature_anomaly"].forEach(function (k) {
      if (Array.isArray(m[k])) out[k] = m.time.map(function (_, i) { return streetNumber(m[k][i]); });
    });
    return {monthly: out};
  }
  function streetTable(v) { return !!v && typeof v === "object" && !Array.isArray(v); }
  function streetNumber(v) { return typeof v === "number" && isFinite(v) ? v : null; }
  function streetNumbers(list) { return list.map(function (v) { return streetNumber(v); }); }
  // POWER's days: a value a "YYYYMMDD", the rest left out.
  function streetDays(table) {
    var out = {};
    Object.keys(table).forEach(function (k) { if (/^\d{8}$/.test(k) && streetNumber(table[k]) !== null) out[k] = table[k]; });
    return out;
  }
  // A kept answer as the card reads it, or null: the record checked month
  // by month, the rest read again as an answer.
  function streetSound(kind, data) {
    if (kind !== "monthly") return streetTrim(kind, data);
    function series(list) { return Array.isArray(list) && list.every(function (v) { return v === null || streetNumber(v) !== null; }); }
    return streetTable(data) && typeof data.from === "string" && /^\d{4}-(0[1-9]|1[0-2])$/.test(data.from) &&
           series(data.p) && series(data.t) && data.p.length > 0 && data.p.length === data.t.length ? data : null;
  }
  // A source's answer kept for a point, from memory or from the tab's
  // session. The session outlives the page: what it kept is read as the
  // card reads an answer, and let go where it says nothing.
  function streetStored(key) {
    var text = null, had = null, data = null;
    if (STREET_KEPT[key]) return STREET_KEPT[key];
    try { text = sessionStorage.getItem(STREET_STORE + key); } catch (err) { return null; /* no storage: memory alone */ }
    if (text === null) return null;
    try { had = JSON.parse(text); } catch (err) { /* not data */ }
    if (had && typeof had.at === "number") data = streetSound(key.slice(0, key.indexOf("|")), had.data);
    if (data !== null) return (STREET_KEPT[key] = {at: had.at, data: data});
    streetForget(key);
    return null;
  }
  // An answer kept, in memory and in the tab's session; the session full,
  // it keeps the latest point's answers and this one, if it then fits.
  function streetStore(key, data) {
    STREET_KEPT[key] = {at: Date.now(), data: data};
    var text = JSON.stringify(STREET_KEPT[key]);
    try {
      sessionStorage.setItem(STREET_STORE + key, text);
    } catch (err) {
      streetPrune(1);
      try { sessionStorage.setItem(STREET_STORE + key, text); } catch (err2) { /* full, or none: memory alone */ }
    }
    streetPrune(STREET_POINTS);
    return data;
  }
  // A point's answer let go, from memory and from the tab's session.
  function streetForget(key) {
    delete STREET_KEPT[key];
    try { sessionStorage.removeItem(STREET_STORE + key); } catch (err) { /* no storage here */ }
  }
  // The tab keeps the answers of the STREET_POINTS points last answered: in
  // memory, and in the session up to `stored` of them. The session is the
  // site's (the follower hands its place across a load in it): what is not
  // the street's is left alone.
  function streetPrune(stored) {
    streetOldest(Object.keys(STREET_KEPT), function (key) { return STREET_KEPT[key].at; }, STREET_POINTS)
      .forEach(function (key) { delete STREET_KEPT[key]; });
    try {
      var keys = [];
      for (var i = 0; i < sessionStorage.length; i++) {
        var k = sessionStorage.key(i);
        if (k && k.indexOf(STREET_STORE) === 0) keys.push(k);
      }
      // Each is kept as {"at":<ms>,"data":...}: its time read off the front.
      streetOldest(keys, function (key) {
        var at = /^\{"at":(\d+)[,}]/.exec(sessionStorage.getItem(key) || "");
        return at ? +at[1] : 0;
      }, stored).forEach(function (key) { sessionStorage.removeItem(key); });
    } catch (err) { /* no storage here */ }
  }
  // The keys of every point past the `keep` last answered, a point answered
  // when its latest source was.
  function streetOldest(keys, atOf, keep) {
    var last = {}, gone = {};
    keys.forEach(function (key) {
      var p = key.slice(key.indexOf("|") + 1), at = atOf(key);
      if (!(p in last) || at > last[p]) last[p] = at;
    });
    Object.keys(last).sort(function (a, b) { return last[b] - last[a]; }).slice(keep)
      .forEach(function (p) { gone[p] = true; });
    return keys.filter(function (key) { return gone[key.slice(key.indexOf("|") + 1)]; });
  }
  // Whether a kept answer still stands: the weather now a quarter of an
  // hour; the record and the forecast a day, as a tab stays open for days
  // while POWER's record gains its months and ECMWF runs each month.
  function streetFresh(kind, had) { return Date.now() - had.at < (kind === "now" ? NOW_KEPT : RECORD_KEPT); }
  // A source's answer for a point: the one kept, or asked for once however
  // many ask while it comes; what went wrong is kept beside the point.
  function streetGet(kind, lon, lat) {
    var key = streetCacheKey(kind, lon, lat), had = streetStored(key);
    if (had && streetFresh(kind, had)) return Promise.resolve(had.data);
    if (!STREET_ASKED[key]) {
      STREET_ASKED[key] = streetFetch(streetUrl(kind, lon, lat)).then(function (json) {
        var data = streetTrim(kind, json);
        if (data === null) throw streetFailure("has nothing for this point");
        delete STREET_ASKED[key];
        delete STREET_WHY[key];
        return streetStore(key, data);
      }).catch(function (err) {
        delete STREET_ASKED[key];
        STREET_WHY[key] = err && err.why || "could not be read";
        throw err;
      });
    }
    return STREET_ASKED[key];
  }
  // What the card has for a point: each source's answer, what went wrong with
  // it, whether it is coming; asked, once the reader has asked for any.
  function streetState(lon, lat) {
    var st = {lon: lon, lat: lat, asked: false, got: {}, why: {}, asking: {}};
    STREET_KINDS.forEach(function (kind) {
      var key = streetCacheKey(kind, lon, lat), had = streetStored(key);
      st.got[kind] = had ? had.data : null;
      st.why[kind] = STREET_WHY[key] || "";
      st.asking[kind] = !!STREET_ASKED[key];
      if (had || st.why[kind] || st.asking[kind]) st.asked = true;
    });
    return st;
  }
  function streetAsked(lon, lat) { return streetState(lon, lat).asked; }
  // The card for a point: with `ask`, each source it lacks, or whose weather
  // now has gone stale, asked for, and the card written again as each answers.
  function streetCard(lon, lat, ask) {
    var asked = false;
    if (ask) {
      STREET_KINDS.forEach(function (kind) {
        var key = streetCacheKey(kind, lon, lat), had = streetStored(key);
        if (STREET_ASKED[key] || (had && streetFresh(kind, had))) return;
        delete STREET_WHY[key];
        asked = true;
        streetGet(kind, lon, lat).then(function () { streetShow(lon, lat); }, function () { streetShow(lon, lat); });
      });
    }
    if (asked || !ask) streetShow(lon, lat);
  }
  // One source asked for again, by its Retry.
  function streetRetry(kind, lon, lat) {
    if (STREET_KINDS.indexOf(kind) < 0) return;
    delete STREET_WHY[streetCacheKey(kind, lon, lat)];
    streetGet(kind, lon, lat).then(function () { streetShow(lon, lat); }, function () { streetShow(lon, lat); });
    streetShow(lon, lat);
  }
  // Every source asked again for a point, by the card's Ask again: what was
  // kept of it and what went wrong let go first.
  function streetAgain(lon, lat) {
    STREET_KINDS.forEach(function (kind) {
      var key = streetCacheKey(kind, lon, lat);
      if (STREET_ASKED[key]) return;
      streetForget(key);
      delete STREET_WHY[key];
    });
    streetCard(lon, lat, true);
  }
  // The card written again where Here shows it, while Here is on its point,
  // and the stage's chip while the street is, with the replay, which takes
  // ECMWF's months from the card's answers.
  function streetShow(lon, lat) {
    var key = streetCacheKey("", lon, lat), box = $("street-card");
    if (box && S.here && streetCacheKey("", S.here.lon, S.here.lat) === key) {
      retake(box, streetCardHtml(streetState(S.here.lon, S.here.lat)));
    }
    if (S.street && streetCacheKey("", S.street.lon, S.street.lat) === key) {
      streetChip();
      if (S.sim && S.sim.rec) { simBuild(); simDraw(); }
    }
  }
  document.addEventListener("click", function (e) {
    var el = e.target.closest ? e.target.closest("[data-street],[data-street-retry]") : null;
    if (!el || !S.here) return;
    if (el.hasAttribute("data-street-retry")) streetRetry(el.getAttribute("data-street-retry"), S.here.lon, S.here.lat);
    else if (el.getAttribute("data-street") === "ask") streetCard(S.here.lon, S.here.lat, true);
    else if (el.getAttribute("data-street") === "again") streetAgain(S.here.lon, S.here.lat);
  });

  // ---- the replay's record: POWER's days since 1981 ----------------------------------
  // POWER's daily record as CSV: a header, a line naming the columns (YEAR
  // and DOY, or YEAR, MO and DY, and the parameters, in any order) and a line
  // a day. Read as {from: "YYYY-MM-DD", p: [mm], t: [deg C]}, a value a day
  // from the first day with one: null for POWER's fill value (-999), for a
  // day the answer does not give, and for what is not a number (or is a
  // rainfall under nothing); the fills after the last day with a value left
  // off. Null for an answer with no day in it.
  function powerCsv(text) {
    if (typeof text !== "string") return null;
    var lines = text.split(/\r?\n/), at = -1, cols = null, days = {}, lo = Infinity, hi = -Infinity, i;
    for (i = 0; i < lines.length && !cols; i++) if (lines[i].split(",").indexOf("YEAR") >= 0) { at = i; cols = lines[i].split(","); }
    if (!cols) return null;
    var Y = cols.indexOf("YEAR"), J = cols.indexOf("DOY"), M = cols.indexOf("MO"), DY = cols.indexOf("DY");
    var P = cols.indexOf("PRECTOTCORR"), T = cols.indexOf("T2M");
    if (P < 0 || T < 0 || (J < 0 && (M < 0 || DY < 0))) return null;
    function num(s) { return /^-?\d+(\.\d+)?$/.test(s) && +s !== -999 ? +s : null; }
    function whole(s) { return /^\d{1,3}$/.test(s) ? +s : NaN; }
    for (i = at + 1; i < lines.length; i++) {
      var c = lines[i].split(",");
      if (c.length !== cols.length || !/^\d{4}$/.test(c[Y])) continue;
      var y = +c[Y], m = J >= 0 ? 1 : whole(c[M]), d = J >= 0 ? whole(c[J]) : whole(c[DY]);
      var ms = Date.UTC(y, m - 1, d), day = new Date(ms);
      if (!(d >= 1) || day.getUTCFullYear() !== y || (J < 0 && (day.getUTCMonth() !== m - 1 || day.getUTCDate() !== d))) continue;
      var p = num(c[P]), t = num(c[T]), n = Math.round(ms / 86400000);
      if (p !== null && p < 0) p = null;
      if (p === null && t === null) continue;
      days[n] = [p, t];
      lo = Math.min(lo, n);
      hi = Math.max(hi, n);
    }
    if (!isFinite(lo)) return null;
    var rec = {from: new Date(lo * 86400000).toISOString().slice(0, 10), p: [], t: []};
    for (var k = lo; k <= hi; k++) {
      var v = days[k] || [null, null];
      rec.p.push(v[0]);
      rec.t.push(v[1]);
    }
    return rec;
  }
  // POWER's cell for a place: MERRA-2's grid, 0.5 deg by 0.625 deg, each
  // cell about its grid point (POWER answered differently either side of
  // 28.25 N and of 81.5625 W on 12 October 2026, and alike either side of
  // 28.5 N and of 81.25 W). The replay asks for the grid point: POWER is sent
  // no closer a position than the cell's, and a move within it asks nothing.
  function simCell(lon, lat) {
    var i = Math.round((wrap(lon) + 180) / 0.625) % 576, j = Math.round(clamp(lat, -90, 90) / 0.5);
    var c = {lon: (i * 0.625 - 180).toFixed(3), lat: (j * 0.5).toFixed(1)};
    c.key = "days|" + c.lat + "," + c.lon;
    return c;
  }
  function simUrl(c) {
    var d = new Date(Date.now());
    return D.street.sources.days.replace("{lon}", c.lon).replace("{lat}", c.lat)
      .replace("{end}", d.getUTCFullYear() + pad2(d.getUTCMonth() + 1) + pad2(d.getUTCDate()));
  }
  // POWER's days for a cell, a third of a megabyte: kept in memory for the
  // SIM_POINTS cells last asked, for a day, and never in the tab's session,
  // where it would crowd out the card's answers; asked once however many ask
  // while it comes, and what went wrong kept beside the cell.
  var SIM_POINTS = 3, SIM_KEPT = {}, SIM_ASKED = {}, SIM_WHY = {}, SIM_SEQ = 0;
  function simGet(lon, lat) {
    var cell = simCell(lon, lat), key = cell.key, had = SIM_KEPT[key];
    if (had && Date.now() - had.at < RECORD_KEPT) { had.seq = ++SIM_SEQ; return Promise.resolve(had.data); }
    if (!SIM_ASKED[key]) {
      delete SIM_WHY[key];
      SIM_ASKED[key] = streetFetch(simUrl(cell), STREET_WAIT, true).then(function (text) {
        var rec = powerCsv(text);
        if (!rec) throw streetFailure("has nothing for this point");
        delete SIM_ASKED[key];
        SIM_KEPT[key] = {at: Date.now(), seq: ++SIM_SEQ, data: rec};
        Object.keys(SIM_KEPT).sort(function (a, b) { return SIM_KEPT[b].seq - SIM_KEPT[a].seq; }).slice(SIM_POINTS)
          .forEach(function (k) { delete SIM_KEPT[k]; });
        return rec;
      }).catch(function (err) {
        delete SIM_ASKED[key];
        SIM_WHY[key] = err && err.why || "could not be read";
        throw err;
      });
    }
    return SIM_ASKED[key];
  }
  // ---- the replay's model: past El Ninos' windows against neutral years' ---------------
  // A window is SIM_MONTHS months; one missing more than SIM_MISSING days is
  // not replayed, and the window under way is shown from SIM_SOON days.
  var SIM_DAY = 86400000, SIM_MONTHS = 6, SIM_MISSING = 5, SIM_SOON = 7;
  // The window of SIM_MONTHS months from the first of month `start` (1 to
  // 12) of `year`: its first day and the day after its last (ms), its length
  // in days, its months ("YYYY-MM"), and its name as the site names an
  // episode, "1997-98" across the new year.
  function simWindow(start, year) {
    var first = Date.UTC(year, start - 1, 1), end = Date.UTC(year, start - 1 + SIM_MONTHS, 1), months = [];
    for (var k = 0; k < SIM_MONTHS; k++) {
      var d = new Date(Date.UTC(year, start - 1 + k, 1));
      months.push(streetKey(d.getUTCFullYear(), d.getUTCMonth() + 1));
    }
    return {first: first, end: end, days: Math.round((end - first) / SIM_DAY), months: months,
            label: start - 1 + SIM_MONTHS > 12 ? year + "-" + pad2((year + 1) % 100) : String(year)};
  }
  // A window's days at the point and what they come to: rain day by day (p,
  // null where the record has none) and temperature (t); the rain
  // accumulated (cum) and its total, a day missing counted dry; its days of
  // 20 mm or more (ETCCDI's R20mm); its wettest day; its longest run of days
  // under 1 mm (ETCCDI's CDD, a day missing counted dry); its mean
  // temperature; and how many days it misses. Null when the record does not
  // hold the whole window or misses more than SIM_MISSING of its days. With
  // `before` (ms), the window under way: the days before then that the
  // record holds, SIM_SOON of them at least.
  function simRun(rec, start, year, before) {
    var w = simWindow(start, year), from = Date.parse(rec.from + "T00:00:00Z");
    var i0 = Math.round((w.first - from) / SIM_DAY), n = w.days, partial = before !== undefined;
    if (i0 < 0) return null;
    if (partial) n = Math.min(n, rec.p.length - i0, Math.floor((before - w.first) / SIM_DAY));
    else if (i0 + n > rec.p.length) return null;
    var run = {tag: year, label: w.label, first: w.first, p: [], t: [], cum: [], total: 0, r20: 0, wettest: null, dry: 0,
               tmean: null, missing: 0, partial: partial}, spell = 0, tsum = 0, tn = 0;
    for (var k = 0; k < n; k++) {
      var p = rec.p[i0 + k], t = rec.t[i0 + k];
      run.p.push(p);
      run.t.push(t);
      if (p === null) run.missing++;
      run.total += p || 0;
      run.cum.push(run.total);
      if (p !== null && p >= 20) run.r20++;
      if (p !== null && (!run.wettest || p > run.wettest.mm)) run.wettest = {mm: p, day: k};
      spell = p === null || p < 1 ? spell + 1 : 0;
      run.dry = Math.max(run.dry, spell);
      if (t !== null) { tsum += t; tn++; }
    }
    if (tn) run.tmean = tsum / tn;
    if (partial ? n - run.missing < SIM_SOON : run.missing > SIM_MISSING) return null;
    return run;
  }
  // The record's windows from month `start`, told apart by the index in each
  // window's first running season, as the card's composite takes its events
  // for the season ahead: El Ninos, a month of it at the index's El Nino
  // bound or over it (the season's peak kept), newest first; neutral years,
  // all three months strictly within the neutral bound - stricter than the
  // composite's months, since a replay plays whole windows; and this year's
  // apart: the window under way at nowMs (begun, with days enough on record
  // to replay or not), or else the last one ended inside the El Nino still
  // under way, which is never a past one.
  function simYears(rec, start, nowMs) {
    var R = D.street, since = ongoingFrom(), out = {events: [], neutral: [], now: null, begun: false};
    for (var y = +rec.from.slice(0, 4), last = new Date(nowMs).getUTCFullYear(); y <= last; y++) {
      var w = simWindow(start, y);
      if (w.first > nowMs) break;
      if (nowMs < w.end) { out.now = simRun(rec, start, y, nowMs); out.begun = true; continue; }
      var season = w.months.slice(0, 3), run = simRun(rec, start, y);
      if (since && season[2] >= since) { out.now = run || out.now; continue; }
      if (!run) continue;
      var known = season.map(function (k) { return indexAt(+k.slice(0, 4), +k.slice(5, 7)); })
        .filter(function (v) { return v !== null; });
      if (known.some(function (v) { return v >= R.warm; })) {
        run.peak = Math.max.apply(null, known);
        out.events.unshift(run);
      } else if (known.length === 3 && known.every(function (v) { return Math.abs(v) < R.neutral; })) {
        out.neutral.push(run);
      }
    }
    return out;
  }
  // The neutral years' rain accumulated by each date of the window, their
  // days lined up as a year's without 29 February (simOnDay): the mean and
  // the 10th and 90th percentiles (straight between the years either side).
  // Its last day is their totals'.
  function simBand(runs) {
    var n = Math.min.apply(null, runs.map(function (r) { return r.cum.length - (simLeap(r.first) < 0 ? 0 : 1); }));
    var out = {mean: [], lo: [], hi: []};
    for (var j = 0; j < n; j++) {
      var v = runs.map(function (r) { return simCumOn(r, j); }).sort(function (a, b) { return a - b; });
      out.mean.push(streetMean(v));
      out.lo.push(simQuantile(v, 0.1));
      out.hi.push(simQuantile(v, 0.9));
    }
    return out;
  }
  // Where 29 February falls in the window from `first` (ms), as a day of it,
  // or -1 for a window without it.
  function simLeap(first) {
    var d = new Date(first), end = Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + SIM_MONTHS, 1);
    for (var y = d.getUTCFullYear(); y <= d.getUTCFullYear() + 1; y++) {
      var t = Date.UTC(y, 1, 29);
      if (new Date(t).getUTCDate() === 29 && t >= first && t < end) return Math.round((t - first) / SIM_DAY);
    }
    return -1;
  }
  // Day k of the window from `first` as the band counts its days: a year's
  // without 29 February, which goes with the 28th.
  function simOnDay(first, k) {
    var z = simLeap(first);
    return z >= 0 && k >= z ? k - 1 : k;
  }
  // A run's rain accumulated by day j as the band counts its days (by 28
  // February, its 29th too), or null past the run's last day.
  function simCumOn(r, j) {
    var z = simLeap(r.first), i = z >= 0 && j >= z - 1 ? j + 1 : j;
    return i < r.cum.length ? r.cum[i] : null;
  }
  // The band on day k of the window from `first`: the neutral years' mean and
  // percentiles by its date, or null past the band's end.
  function simBandOn(m, first, k) {
    var b = m.band, j = simOnDay(first, k);
    return b && j >= 0 && j < b.mean.length ? {mean: b.mean[j], lo: b.lo[j], hi: b.hi[j]} : null;
  }
  function simQuantile(sorted, q) {
    var at = q * (sorted.length - 1), i = Math.floor(at);
    return i + 1 < sorted.length ? sorted[i] + (at - i) * (sorted[i + 1] - sorted[i]) : sorted[i];
  }
  // The point's climate: each calendar month's mean total over the years
  // the record holds every day of it; null for a month it never does.
  function simClimate(rec) {
    var from = Date.parse(rec.from + "T00:00:00Z"), sums = {}, totals = [[], [], [], [], [], [], [], [], [], [], [], []];
    rec.p.forEach(function (p, i) {
      var d = new Date(from + i * SIM_DAY), key = streetKey(d.getUTCFullYear(), d.getUTCMonth() + 1);
      var s = sums[key] || (sums[key] = {mm: 0, days: 0, gap: false, y: d.getUTCFullYear(), m: d.getUTCMonth()});
      if (p === null) s.gap = true; else s.mm += p;
      s.days++;
    });
    Object.keys(sums).forEach(function (key) {
      var s = sums[key];
      if (!s.gap && s.days === new Date(Date.UTC(s.y, s.m + 1, 0)).getUTCDate()) totals[s.m].push(s.mm);
    });
    return totals.map(function (list) { return list.length ? streetMean(list) : null; });
  }
  // ECMWF's forecast for the coming window from month `start` - the next not
  // yet begun - by the delta method: each month's total is the point's
  // climate for it scaled by the model's forecast against the model's own
  // climate of past forecasts, where that climate is the dry floor or more
  // (where the card gives it as a percentage), else with the model's anomaly
  // added, never under nothing; for the months from the window's first that
  // the forecast covers. The rain accumulated day by day, its total and the
  // climate it stands on; null when the forecast does not reach the window's
  // first month.
  function simEcmwf(rows, start, clim, nowMs) {
    var y = new Date(nowMs).getUTCFullYear(), w = simWindow(start, y);
    if (w.first <= nowMs) w = simWindow(start, y + 1);
    var out = {first: w.first, label: w.label, months: [], cum: [], total: 0, base: 0};
    for (var k = 0; k < w.months.length; k++) {
      var key = w.months[k], m = +key.slice(5, 7), row = null;
      (rows || []).forEach(function (r) { if (r && r.month === key) row = r; });
      if (!row || row.anom === null || clim[m - 1] === null) break;
      var days = new Date(Date.UTC(+key.slice(0, 4), m, 0)).getUTCDate();
      var mm = Math.max(0, typeof row.percent === "number" ? clim[m - 1] * (1 + row.percent / 100)
                                                           : clim[m - 1] + row.anom * days);
      for (var d = 0; d < days; d++) out.cum.push(out.total + mm * (d + 1) / days);
      out.months.push(key);
      out.total += mm;
      out.base += clim[m - 1];
    }
    return out.months.length ? out : null;
  }
  // The replay's model of the window from month `start`: past El Ninos,
  // neutral years with their band and means, the window under way, ECMWF's
  // projection, the strongest El Nino and the window's months in words.
  function simModel(rec, start, rows, nowMs) {
    var y = simYears(rec, start, nowMs), N = y.neutral, strongest = null;
    function mean(key) {
      var v = N.map(function (r) { return r[key]; }).filter(function (x) { return x !== null; });
      return v.length ? streetMean(v) : null;
    }
    y.events.forEach(function (r) { if (!strongest || r.peak > strongest.peak) strongest = r; });
    return {start: start, words: MONTH_WORDS[start - 1] + " to " + MONTH_WORDS[(start + SIM_MONTHS - 2) % 12],
            events: y.events, neutral: N, now: y.now, begun: y.begun, band: N.length ? simBand(N) : null,
            base: N.length ? {total: mean("total"), r20: mean("r20"), dry: mean("dry"), tmean: mean("tmean"),
                              years: N.length} : null,
            ecmwf: rows ? simEcmwf(rows, start, simClimate(rec), nowMs) : null, strongest: strongest ? strongest.tag : null};
  }

  // ---- the card ------------------------------------------------------------------------
  // Open-Meteo's own words for its credit, linked, wherever its data shows.
  function openMeteo() {
    return '<a href="https://open-meteo.com/" target="_blank" rel="noopener">Weather data by Open-Meteo.com</a>';
  }
  // Rain in mm a day, to two places under a millimetre and to one over it.
  function streetMm(v) { return Math.abs(v).toFixed(Math.abs(v) >= 1 ? 1 : 2) + " mm a day"; }
  function streetMmSigned(v) { return signedText(v, Math.abs(v) >= 1 ? 1 : 2) + " mm a day"; }
  function streetC(v) { return signedText(v, 1) + " \u00b0C"; }
  function streetMonthWords(key) { return MONTH_WORDS[+key.slice(5, 7) - 1] + " " + key.slice(0, 4); }
  // A source's line while it comes, or what went wrong with it and its Retry.
  function streetWait(st, kind) {
    var name = kind === "now" || kind === "ahead" ? "Open-Meteo"
             : kind === "daily" ? "NASA POWER\u2019s daily record, for the latest months," : "NASA POWER";
    if (st.asking[kind]) return kind === "daily" ? "" : '<p class="streetwait">Asking ' + name + "\u2026</p>";
    if (!st.why[kind]) return "";
    return '<p class="streetfail">' + name + " " + esc(st.why[kind]) + '. <button type="button" class="toolbtn" ' +
           'data-street-retry="' + kind + '">Retry</button></p>';
  }
  // The season ahead: the running season of the three months from next month.
  function streetAhead(ms) {
    var d = new Date(ms), y = d.getUTCFullYear(), m = d.getUTCMonth() + 1, months = [];
    for (var k = 0; k < 3; k++) months.push(streetKey(y + Math.floor((m + k) / 12), (m + k) % 12 + 1));
    var i = (m + 1) % 12;
    return {season: i, name: SEASON_NAMES[i], months: months,
            words: MONTH_WORDS[+months[0].slice(5) - 1] + " to " + MONTH_WORDS[+months[2].slice(5) - 1]};
  }
  // ECMWF's months, as Open-Meteo gives them: the temperature anomaly (its
  // kelvin are degrees), rain from the month's total to mm a day with the
  // model's normal (the mean less the anomaly) and the anomaly as a
  // percentage of it where that is the atlas's dry floor or more, and the sea
  // surface where the model's point is sea.
  function seasonalRows(json) {
    var m = json && json.monthly;
    if (!m || !Array.isArray(m.time)) return [];
    function at(name, i) { var v = m[name] && m[name][i]; return typeof v === "number" && isFinite(v) ? v : null; }
    return m.time.map(function (time, i) {
      var y = +time.slice(0, 4), mo = +time.slice(5, 7), days = new Date(Date.UTC(y, mo, 0)).getUTCDate();
      var mean = at("precipitation_mean", i), anom = at("precipitation_anomaly", i);
      var row = {month: time.slice(0, 7), label: MONTHS[mo - 1] + " " + y, days: days, t: at("temperature_2m_anomaly", i),
                 rain: mean === null ? null : mean / days, anom: anom === null ? null : anom / days,
                 normal: null, percent: null, sst: at("sea_surface_temperature_anomaly", i)};
      if (mean !== null && anom !== null) {
        row.normal = (mean - anom) / days;
        if (row.normal >= D.street.dry_floor) row.percent = row.anom / row.normal * 100;
      }
      return row;
    });
  }
  // Open-Meteo's weather code, WMO's, in words.
  function weatherWords(code) {
    var words = {0: "clear sky", 1: "mainly clear", 2: "partly cloudy", 3: "overcast", 45: "fog", 48: "freezing fog",
                 51: "light drizzle", 53: "drizzle", 55: "heavy drizzle", 56: "light freezing drizzle",
                 57: "freezing drizzle", 61: "light rain", 63: "rain", 65: "heavy rain", 66: "light freezing rain",
                 67: "freezing rain", 71: "light snow", 73: "snow", 75: "heavy snow", 77: "snow grains",
                 80: "light showers", 81: "showers", 82: "violent showers", 85: "light snow showers",
                 86: "heavy snow showers", 95: "thunderstorm", 96: "thunderstorm with hail",
                 99: "thunderstorm with heavy hail"};
    return Object.prototype.hasOwnProperty.call(words, code) ? words[code] : "weather code " + code;
  }
  // Everything the card reads from what it has: the season ahead, the record
  // with its latest months filled in, El Nino's year at the point, and
  // ECMWF's months.
  function streetRead(st) {
    var m = st.got.monthly, rec = m ? powerFill({from: m.from, p: m.p.slice(), t: m.t.slice()}, st.got.daily) : null;
    return {ahead: streetAhead(Date.now()), rec: rec, year: rec ? streetYear(rec) : null,
            rows: st.got.ahead ? seasonalRows(st.got.ahead) : null};
  }
  // The card, from the top: what El Nino means for the point in a sentence,
  // the weather now, ECMWF's next six months, El Nino's year here, past El
  // Ninos in the season ahead with this year so far, and how it is known.
  // Until the reader asks, the sentence and the button that asks. What the
  // sources sent read wrong takes neither Here nor the stage down with it:
  // the card says so, with a button that asks them again.
  var STREET_UNREAD = "What the sources sent for this point could not be read.";
  function streetCardHtml(st) {
    try {
      var x = streetRead(st);
      var html = ['<h3 class="streethead" id="street-card-title">El Ni\u00f1o on this street</h3>',
                  '<p class="streetsaid">' + streetSentence(st, x) + "</p>"];
      if (!st.asked) {
        html.push('<p><button type="button" class="toolbtn" data-street="ask">What El Ni\u00f1o does here</button></p>',
                  '<p class="method">This point\u2019s record since 1981 from NASA POWER, and ECMWF\u2019s seasonal ' +
                  "forecast and the weather now from Open-Meteo. Nothing goes to either until the button is pressed; " +
                  "then they receive this position, to a hundredth of a degree.</p>");
        return html.join("");
      }
      html.push(streetNowHtml(st), streetAheadHtml(st, x.rows), streetYearHtml(st, x.year, x.ahead),
                streetEventsHtml(st, x.rec, x.year, x.ahead), streetMethodHtml(st));
      return html.join("");
    } catch (err) {
      return '<h3 class="streethead" id="street-card-title">El Ni\u00f1o on this street</h3><p class="streetfail">' +
             STREET_UNREAD + ' <button type="button" class="toolbtn" data-street="again">Ask again</button></p>';
    }
  }
  // The card's sentence: El Nino now, what past El Ninos did here in the
  // season ahead and how many of them agreed, and what ECMWF expects of it;
  // the chip's too, so it is read as safely as the card.
  function streetSentence(st, x) {
    var rows = D.then && D.then.seasons, last = rows && rows.length ? rows[rows.length - 1] : null, said = [];
    if (last) said.push(esc(D.street.index) + " is " + signedText(last[2], 1) + " for " + esc(last[1]) + ": " + esc(last[3]) + ".");
    try {
      x = x || streetRead(st);
      said.push(streetPastSaid(st, x), streetAheadSaid(st, x));
    } catch (err) {
      said.push(STREET_UNREAD);
    }
    return said.filter(Boolean).join(" ");
  }
  function streetPastSaid(st, x) {
    if (!x.year) {
      if (st.asking.monthly) return "Reading NASA POWER\u2019s record of this place\u2026";
      return st.why.monthly ? "NASA POWER\u2019s record of this place could not be read (" + esc(st.why.monthly) +
                              "), so what past El Ni\u00f1os did here is not shown." : "";
    }
    var s = x.year[x.ahead.season], p = s.p, t = s.t, words = x.ahead.words, said = [];
    if (!p.usable && !t.usable) {
      return "Too few past El Ni\u00f1os fall in " + words + " to say what they did here (" + p.events.length +
             " El Ni\u00f1os against " + p.years + " neutral years; the composite needs " + D.street.min_events + " and " +
             D.street.min_years + ").";
    }
    if (streetSignal(p)) {
      said.push((p.diff > 0 ? "wetter" : "drier") + " by " + streetMm(p.diff) + " (" +
                (p.percent === null ? "" : signedText(p.percent, 0) + "%; ") + streetAgree(p) + " events)");
    }
    if (streetSignal(t)) {
      said.push((t.diff > 0 ? "warmer" : "cooler") + " by " + Math.abs(t.diff).toFixed(1) + " \u00b0C (" +
                streetAgree(t) + " events)");
    }
    if (!said.length) {
      return "Past El Ni\u00f1os left no clear mark on " + words + " here: rain and temperature were within what " +
             "chance gives against " + p.years + " neutral years.";
    }
    return "In past El Ni\u00f1os, " + words + " here was " + said.join(" and ") + " than in neutral years.";
  }
  function streetAheadSaid(st, x) {
    if (!x.rows) {
      if (st.asking.ahead) return "Asking Open-Meteo for ECMWF\u2019s forecast\u2026";
      return st.why.ahead ? "ECMWF\u2019s forecast could not be read (Open-Meteo " + esc(st.why.ahead) + ")." : "";
    }
    var got = x.rows.filter(function (r) { return x.ahead.months.indexOf(r.month) >= 0 && r.anom !== null && r.t !== null; });
    if (got.length < 3) return "ECMWF\u2019s forecast here does not reach " + x.ahead.words + ".";
    var mm = 0, days = 0, t = 0;
    got.forEach(function (r) { mm += r.anom * r.days; days += r.days; t += r.t; });
    return "ECMWF expects " + streetMmSigned(mm / days) + " and " + streetC(t / got.length) + " against its normal for " +
           x.ahead.words + ".";
  }
  // Whether a season's difference is one: the composite has the events and
  // years for it and Welch's t passes its 95% point, as the atlas marks one.
  function streetSignal(c) { return c.usable && Math.abs(c.t) >= c.crit; }
  // How many of the El Ninos went the composite's way.
  function streetAgree(c) {
    return c.events.filter(function (e) { return (e.value - c.base) * c.diff > 0; }).length + " of " + c.events.length;
  }
  // Right now: the temperature, the weather, the wind and the next day's
  // rain, by the point's own clock.
  function streetNowHtml(st) {
    var n = st.got.now, html = ["<h4>Right now</h4>"];
    if (!n) return html.concat(streetWait(st, "now")).join("");
    var c = n.current || {}, said = [];
    if (typeof c.temperature_2m === "number") said.push(c.temperature_2m.toFixed(1) + " \u00b0C");
    if (typeof c.weather_code === "number") said.push(weatherWords(c.weather_code));
    said.push(streetWind(c));
    said = said.filter(Boolean).join(", ");
    html.push("<p>" + (said ? esc(said.charAt(0).toUpperCase() + said.slice(1)) + ". " : "") + streetRain24(n.hourly) + "</p>");
    html.push('<p class="method">Open-Meteo\u2019s forecast for ' + esc(String(c.time || "").slice(11, 16)) + " local time" +
              (n.timezone_abbreviation ? " (" + esc(n.timezone_abbreviation) + ")" : "") + ". " + openMeteo() + "</p>");
    return html.join("");
  }
  function streetWind(c) {
    var v = c.wind_speed_10m, g = c.wind_gusts_10m, d = c.wind_direction_10m;
    if (typeof v !== "number") return "";
    if (v < 1) return "calm";
    return "wind " + Math.round(v) + " km/h" + (typeof d === "number" ? " from the " + COMPASS8[Math.round(d / 45) % 8] : "") +
           (typeof g === "number" && g >= v + 5 ? " with gusts of " + Math.round(g) + " km/h" : "");
  }
  function streetRain24(h) {
    var mm = 0, n = 0;
    (h && Array.isArray(h.precipitation) ? h.precipitation : []).forEach(function (v) {
      if (typeof v === "number") { mm += v; n++; }
    });
    if (!n) return "";
    if (mm < 0.05) return "No rain forecast in the next 24 hours.";
    if (mm < 0.1) return "A trace of rain forecast in the next 24 hours.";
    return mm.toFixed(1) + " mm of rain forecast in the next 24 hours.";
  }
  // ECMWF's next six months at the point, from the reader's month, each
  // against the model's own normal.
  function streetAheadHtml(st, rows) {
    var html = ["<h4>The next six months, ECMWF</h4>"], d = new Date(Date.now());
    if (!rows) return html.concat(streetWait(st, "ahead")).join("");
    var from = streetKey(d.getUTCFullYear(), d.getUTCMonth() + 1);
    rows = rows.filter(function (r) { return r.month >= from; }).slice(0, 6);
    if (!rows.some(function (r) { return r.t !== null || r.anom !== null; })) {
      return html.concat("<p>ECMWF\u2019s seasonal forecast has nothing for this point.</p>").join("");
    }
    var sea = rows.some(function (r) { return r.sst !== null; });
    function bars(key) {
      return rows.map(function (r) {
        return r[key] === null ? null : {v: r[key], title: r.label + ": " + (key === "anom" ? streetMmSigned(r[key]) : streetC(r[key]))};
      });
    }
    var series = [{key: "t", name: "Air", unit: "\u00b0C", warm: true, values: bars("t")},
                  {key: "p", name: "Rain", unit: "mm a day", values: bars("anom")}];
    if (sea) series.push({key: "sst", name: "Sea", unit: "\u00b0C", warm: true, values: bars("sst")});
    html.push(streetBarsSvg(rows.map(function (r) { return {label: MONTHS[+r.month.slice(5, 7) - 1]}; }), series));
    html.push('<details><summary>Month by month</summary><table class="streettable"><thead><tr><th scope="col">Month</th>' +
              '<th scope="col">Temperature</th><th scope="col">Rain</th>' + (sea ? '<th scope="col">Sea surface</th>' : "") +
              "</tr></thead><tbody>" + rows.map(function (r) {
                return '<tr><th scope="row">' + esc(r.label) + "</th><td>" + streetCText(r.t) + "</td><td>" +
                       streetRainText(r) + "</td>" + (sea ? "<td>" + streetCText(r.sst) + "</td>" : "") + "</tr>";
              }).join("") + "</tbody></table></details>");
    html.push('<p class="method">Each month against ECMWF\u2019s own climate of past forecasts for it; rain is the ' +
              "month\u2019s total as mm a day. " + openMeteo() + "</p>");
    return html.join("");
  }
  function streetCText(v) { return v === null ? "no value" : streetC(v); }
  function streetRainText(r) {
    if (r.anom === null) return "no value";
    return streetMmSigned(r.anom) + (r.percent === null ? "" : " (" + signedText(r.percent, 0) + "%)") +
           (r.normal === null ? "" : " on a normal of " + streetMm(r.normal));
  }
  // El Nino's year at the point: the composite of each running season, rain
  // and temperature, faint where the t-test does not tell El Ninos from
  // neutral years, and nothing drawn where too few El Ninos fall in it.
  function streetYearHtml(st, year, ahead) {
    var html = ["<h4>El Ni\u00f1o\u2019s year here</h4>"];
    if (!year) return html.concat(streetWait(st, "monthly")).join("");
    function bars(key) {
      return year.map(function (s) {
        var c = s[key];
        return c.usable ? {v: c.diff, faint: !streetSignal(c),
                           title: s.name + ": " + (key === "p" ? streetMmSigned(c.diff) : streetC(c.diff))} : null;
      });
    }
    html.push('<p class="method">Past El Ni\u00f1os less neutral years, season by season since 1981; faint where the ' +
              "t-test does not tell them apart, blank where too few El Ni\u00f1os fall in the season.</p>");
    html.push(streetBarsSvg(year.map(function (s) { return {label: s.name, strong: s.season === ahead.season}; }),
                            [{key: "p", name: "Rain", unit: "mm a day", values: bars("p")},
                             {key: "t", name: "Air", unit: "\u00b0C", warm: true, values: bars("t")}]));
    html.push('<details><summary>Season by season</summary><table class="streettable"><thead><tr><th scope="col">Season</th>' +
              '<th scope="col">Rain</th><th scope="col">Temperature</th></tr></thead><tbody>' + year.map(function (s) {
                return '<tr><th scope="row">' + esc(s.name) + "</th><td>" + streetCompText(s.p, "p") + "</td><td>" +
                       streetCompText(s.t, "t") + "</td></tr>";
              }).join("") + "</tbody></table></details>");
    html.push(streetWait(st, "daily"));
    return html.join("");
  }
  // One season's composite in words, as Here's table words an atlas cell.
  function streetCompText(c, key) {
    if (!c.usable) return "too few events: " + c.events.length + " El Ni\u00f1os against " + c.years + " neutral years";
    var said = signedText(c.diff, 2) + (key === "p" ? " mm a day" : " \u00b0C") + " against an ordinary " +
               c.base.toFixed(key === "p" ? 2 : 1) + (c.percent === null ? "" : " (" + signedText(c.percent, 0) + "%)") +
               ", |t| " + Math.abs(c.t).toFixed(2) + ", needs " + c.crit.toFixed(2) + ", " + c.events.length + " El Ni\u00f1os";
    var verdict = !streetSignal(c) ? "no clear signal" : key === "p" ? (c.diff > 0 ? "wetter" : "drier")
                : (c.diff > 0 ? "warmer" : "cooler");
    return esc(said) + ": <b>" + verdict + "</b>";
  }
  // Past El Ninos in the season ahead, each against the neutral years' mean,
  // and this year so far: the latest season on record against its own.
  function streetEventsHtml(st, rec, year, ahead) {
    if (!year) return "";
    var s = year[ahead.season], p = s.p, t = s.t, html = ["<h4>Past El Ni\u00f1os, " + esc(ahead.words) + "</h4>"];
    if (!p.events.length) {
      html.push("<p>No El Ni\u00f1o since 1981 reached +" + D.street.warm.toFixed(1) + " in " + esc(ahead.words) + ".</p>");
    } else {
      var temps = {};
      t.events.forEach(function (e) { temps[e.tag] = e.value; });
      var rows = p.events.map(function (e) {
        return {label: eventLabel(ahead.season, e.tag), p: p.base === null ? null : e.value - p.base,
                t: t.base === null || !(e.tag in temps) ? null : temps[e.tag] - t.base};
      });
      if (p.usable) rows.push({label: "Mean", p: p.diff, t: t.usable ? t.diff : null, mean: true});
      html.push(streetDotsSvg(rows));
      html.push('<details><summary>Event by event</summary><table class="streettable"><thead><tr><th scope="col">El Ni\u00f1o</th>' +
                '<th scope="col">Rain</th><th scope="col">Temperature</th></tr></thead><tbody>' + rows.map(function (r) {
                  return '<tr><th scope="row">' + esc(r.label) + "</th><td>" + (r.p === null ? "no value" : streetMmSigned(r.p)) +
                         "</td><td>" + (r.t === null ? "no value" : streetC(r.t)) + "</td></tr>";
                }).join("") + "</tbody></table></details>");
      html.push('<p class="method">Each El Ni\u00f1o\u2019s ' + esc(s.name) + " against the mean of " + p.years +
                " neutral years.</p>");
    }
    var latest = rec && streetLatest(rec), now = latest && year[latest.season];
    if (now && now.p.base !== null && now.t.base !== null) {
      var dp = latest.p - now.p.base, pct = now.p.base >= D.street.dry_floor ? dp / now.p.base * 100 : null;
      html.push("<p>This year so far: " + esc(latest.name) + " " + latest.tag + " here was " + streetMmSigned(dp) +
                (pct === null ? "" : " (" + signedText(pct, 0) + "%)") + " and " + streetC(latest.t - now.t.base) +
                " against its neutral years" + (now.p.usable && now.t.usable ? "; past El Ni\u00f1os\u2019 " +
                esc(latest.name) + ": " + streetMmSigned(now.p.diff) + " and " + streetC(now.t.diff) : "") + ".</p>");
    }
    return html.join("");
  }
  // How the card knows what it says, and whose data it is, in the words each
  // source asks for.
  function streetMethodHtml(st) {
    var since = ongoingFrom(), R = D.street, km = Math.round(0.625 * 111.32 * Math.cos(st.lat * Math.PI / 180));
    return '<details class="streetmethod"><summary>Method and sources</summary>' +
      "<p>The record is NASA POWER\u2019s for this point: MERRA-2\u2019s monthly rainfall, corrected against gauges " +
      "(PRECTOTCORR), and 2 m temperature, on a 0.5\u00b0 by 0.625\u00b0 grid, about 55 by " + km + " km here, from 1981. " +
      "The months its monthly record has yet to reach come from POWER\u2019s daily record, a month once it has " +
      DAYS_FULL + " days; POWER\u2019s newest days are NASA\u2019s GEOS-IT analysis, not MERRA-2, so this year\u2019s " +
      "latest months are one analysis set against another\u2019s neutral years. It is a model\u2019s grid cell, not a " +
      "gauge on this street.</p>" +
      "<p>Each running season is composited as the atlas\u2019s maps are: a month is El Ni\u00f1o when " + esc(R.index) +
      " centred on it is +" + R.warm.toFixed(1) + " or more and neutral within " + R.neutral.toFixed(1) + "; each El " +
      "Ni\u00f1o gives the mean of its El Ni\u00f1o months in the season, each neutral year the mean of its neutral ones" +
      (since ? "; the El Ni\u00f1o under way since " + streetMonthWords(since) + " is left out" : "") + ". The difference " +
      "is tested with Welch\u2019s t against the two-sided 95% point of Student\u2019s t at the smaller sample less one, " +
      "and a season needs " + R.min_events + " El Ni\u00f1os and " + R.min_years + " neutral years. Rain is given as a " +
      "percentage of the neutral mean only where that mean is " + R.dry_floor + " mm a day or more.</p>" +
      "<p>The next six months are ECMWF\u2019s seasonal forecast, through Open-Meteo, each month against the model\u2019s " +
      "own climate of past forecasts. Right now is Open-Meteo\u2019s forecast for the quarter hour.</p>" +
      '<p class="links">' + openMeteo() + '<a href="https://power.larc.nasa.gov/" target="_blank" rel="noopener">' +
      'NASA POWER \u2197</a><a href="https://www.ecmwf.int/" target="_blank" rel="noopener">ECMWF \u2197</a></p>' +
      streetAcknowledged() + "</details>";
  }
  // NASA POWER's and ECMWF's words, as each asks for them where its data show.
  function streetAcknowledged() {
    return "<p>These data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded through the " +
      "NASA Earth Science/Applied Science Program.</p>" +
      "<p>This service is based on data and products of the European Centre for Medium-Range Weather Forecasts " +
      "(ECMWF). Source www.ecmwf.int. ECMWF does not accept any liability whatsoever for any error or omission in the " +
      "data, their availability, or for any loss or damage arising from their use.</p>";
  }
  // ---- the card's charts ---------------------------------------------------------------
  // A row's scale: the nice number at or over its largest value, and at least
  // `floor`, so a row of small differences is not drawn as large ones.
  function streetLimit(values, floor) {
    var top = floor;
    values.forEach(function (v) { if (v !== null && Math.abs(v) > top) top = Math.abs(v); });
    var p = Math.pow(10, Math.floor(Math.log(top) / Math.LN10)), steps = [1, 1.5, 2, 3, 5, 10];
    for (var i = 0; i < steps.length; i++) if (steps[i] * p >= top - 1e-9) return steps[i] * p;
    return 10 * p;
  }
  function streetNum(v) { return String(Math.round(v * 1000) / 1000); }
  // A bar from the zero line at y0 to y1, its far end rounded; a value of
  // nothing is a sliver, so what is drawn is seen to be drawn.
  function streetBarPath(x, w, y0, y1) {
    if (Math.abs(y1 - y0) < 1) y1 = y0 + (y1 < y0 ? -1 : 1);
    var r = Math.min(3, w / 2, Math.abs(y1 - y0)), e = y1 < y0 ? y1 + r : y1 - r;
    function f(v) { return Math.round(v * 10) / 10; }
    return "M" + f(x) + " " + f(y0) + "V" + f(e) + "Q" + f(x) + " " + f(y1) + " " + f(x + r) + " " + f(y1) +
           "H" + f(x + w - r) + "Q" + f(x + w) + " " + f(y1) + " " + f(x + w) + " " + f(e) + "V" + f(y0) + "Z";
  }
  // Bars in rows, a row a series and a column each: up for more, down for
  // less, each row on its own scale written at its left; a value faint where
  // the t-test does not pass it, and none where there is nothing to say.
  // Warmth is the ramp's red, rain its blue.
  function streetBarsSvg(cols, series) {
    var W = 320, L = 64, R = 4, band = 52, top = 4, cw = (W - L - R) / cols.length, bw = Math.min(16, cw * 0.62);
    var h = top + series.length * band + 16, out = ['<svg class="streetbars" viewBox="0 0 ' + W + " " + h + '" aria-hidden="true">'];
    series.forEach(function (s, k) {
      var y0 = top + k * band + band / 2, half = band / 2 - 6;
      var lim = streetLimit(s.values.map(function (b) { return b ? b.v : null; }), s.key === "p" ? 0.2 : 0.5);
      out.push('<text x="0" y="' + (y0 - 3) + '">' + esc(s.name) + '</text><text x="0" y="' + (y0 + 10) + '">\u00b1' +
               streetNum(lim) + " " + esc(s.unit) + "</text>");
      out.push('<line class="zero" x1="' + L + '" x2="' + (W - R) + '" y1="' + y0 + '" y2="' + y0 + '"/>');
      s.values.forEach(function (b, i) {
        if (!b) return;
        var x = L + i * cw + (cw - bw) / 2, y1 = y0 - Math.max(-1, Math.min(1, b.v / lim)) * half;
        out.push('<path class="bar' + (b.faint ? " faint" : "") + '" data-col="' + i + '" data-series="' + s.key + '" d="' +
                 streetBarPath(x, bw, y0, y1) + '" fill="' + ((b.v > 0) === !!s.warm ? "var(--d8)" : "var(--d2)") +
                 '"><title>' + esc(b.title || "") + "</title></path>");
      });
    });
    cols.forEach(function (c, i) {
      out.push('<text x="' + (Math.round((L + i * cw + cw / 2) * 10) / 10) + '" y="' + (top + series.length * band + 11) +
               '" text-anchor="middle"' + (c.strong ? ' class="strong"' : "") + ">" + esc(c.label) + "</text>");
    });
    out.push("</svg>");
    return out.join("");
  }
  // Past El Ninos as dots, a row each, rain and temperature side by side,
  // each about the neutral years' mean; the composite's mean a diamond.
  function streetDotsSvg(rows) {
    var W = 320, L = 56, G = 14, P = (W - L - G) / 2, H = 15, top = 16, h = top + rows.length * H + 2;
    var out = ['<svg class="streetdots" viewBox="0 0 ' + W + " " + h + '" aria-hidden="true">'];
    [{key: "p", name: "Rain", unit: "mm a day", x: L}, {key: "t", name: "Air", unit: "\u00b0C", x: L + P + G, warm: true}]
      .forEach(function (pn) {
        var lim = streetLimit(rows.map(function (r) { return r[pn.key]; }), pn.key === "p" ? 0.2 : 0.5), mid = pn.x + P / 2;
        out.push('<text x="' + mid + '" y="10" text-anchor="middle">' + esc(pn.name) + ", \u00b1" + streetNum(lim) + " " +
                 esc(pn.unit) + "</text>");
        out.push('<line class="zero" x1="' + mid + '" x2="' + mid + '" y1="' + (top - 2) + '" y2="' + h + '"/>');
        rows.forEach(function (r, i) {
          var v = r[pn.key];
          if (v === null) return;
          var cx = Math.round((mid + Math.max(-1, Math.min(1, v / lim)) * (P / 2 - 5)) * 10) / 10, cy = top + i * H + H / 2;
          var hue = (v > 0) === !!pn.warm ? "var(--d8)" : "var(--d2)";
          var title = "<title>" + esc(r.label + ": " + (pn.key === "p" ? streetMmSigned(v) : streetC(v))) + "</title>";
          out.push(r.mean ? '<path d="M' + cx + " " + (cy - 5) + 'l5 5-5 5-5-5z" fill="' + hue + '" stroke="var(--ink)">' +
                            title + "</path>"
                          : '<circle cx="' + cx + '" cy="' + cy + '" r="4" fill="' + hue +
                            '" stroke="var(--surface)" stroke-width="1.5">' + title + "</circle>");
        });
      });
    rows.forEach(function (r, i) {
      out.push('<text x="0" y="' + (top + i * H + H / 2 + 3.5) + '"' + (r.mean ? ' class="strong"' : "") + ">" + esc(r.label) +
               "</text>");
    });
    out.push("</svg>");
    return out.join("");
  }

  // ---- the stage: Street View where the figure is let go -------------------------------
  // The stage covers the map: Google's own Street View embed of the point,
  // the keyless one Here's frame opens, between a bar of the place and the
  // ways on and a strip with a minimap of the map's street tiles and the
  // card's sentence. Here moves to the point, so the side panel shows its
  // card at the top. Then and now is the same place's other view: entering
  // either leaves the other. S.street is the point, its name, the minimap's
  // zoom and box, the link last copied, and the loop or Play it stopped.
  // The minimap opens on a neighbourhood, as Google's does: Esri's street map
  // is drawn to zoom 15 even in mid-ocean, where its deeper tiles are grey.
  // On the way out, the map is at a street's zoom.
  var MINI_Z = 15, MINI_MIN = 3, MINI_MAX = 18, STREET_MAP_Z = 16, STREET_SRC = "";
  S.street = null;
  // Into the street at a point, however it is asked (the figure, Here, a
  // link, the page's API): the map stops waiting for a tap, then and now is
  // left, Here moves to the point and its card is asked for, as the drop is
  // the reader asking. Entered already, the stage moves and its minimap
  // keeps its zoom. Entered to find the point's street (opts.find), the
  // stage shows the point while Here, the card and Google's frame wait.
  // Entered on a pick's street, it keeps the pick's list (opts.roads, the
  // entry it is on, opts.road, and the point picked, opts.picked) for Next
  // street; entered any other way, it has none. Entered on a pick whose
  // street was not found, it keeps the pick's zoom (opts.unfound) for Find
  // the street.
  function streetEnter(lon, lat, label, opts) {
    opts = opts || {};
    lon = lonIn(lon); lat = clamp(lat, -85, 85);
    if (S.arming) arm(false);
    if (S.then) thenLeave();
    var was = S.street, back = was ? was.back : {loop: !!(S.loop || S.loopWanted), playing: !!S.playing};
    if (!was) {
      // The loop and Play run over the map, which the stage hides: both
      // stop, and Exit runs again what ran.
      if (S.loop) setLoop(false);
      S.loopWanted = false;
      if (S.playing) setPlay(false);
    }
    S.street = {lon: lon, lat: lat, label: label || placeLabel(lon, lat),
                mini: finite(opts.mini) ? clamp(Math.round(opts.mini), MINI_MIN, MINI_MAX) : was ? was.mini : MINI_Z,
                box: null, link: "", finding: !!opts.find, back: back, roads: opts.roads || null,
                road: opts.roads ? opts.road || 0 : 0, picked: opts.roads ? opts.picked : null,
                unfound: finite(opts.unfound) ? opts.unfound : null};
    if (!opts.find) {
      hereAt(lon, lat, S.street.label);
      streetCard(lon, lat, true);
    }
    // The replay stays open on the new point, stopped where it was, on the
    // record of its cell; the storm panel stays open, for the new point.
    if (S.sim) { simPlay(false); simLoad(); }
    tcMoved();
    streetDraw();
    return true;
  }
  // Out of the street, onto the map at the point, at a street's zoom or the
  // deepest the map's layer goes, with the loop or Play it stopped; the
  // address that opened it let go, and the focus, if it was on the stage, on
  // the map.
  function streetLeave() {
    var st = S.street, stage = $("street-stage"), on = document.activeElement;
    if (!st) return false;
    var focused = !!on && !!stage.contains && stage.contains(on);
    simClose(true);
    tcClose(true);
    S.street = null;
    clearTimeout(snapTimer);
    cancelAnimationFrame(anim); anim = 0;
    S.x = mx(st.lon) + near(mx(st.lon)); S.y = my(st.lat); S.z = clamp(Math.max(S.z, STREET_MAP_Z), MINZ, maxZoom());
    // The loop over the frames in view where the map now is (once GIBS
    // gives them, if it has yet to), as then and now's Exit runs it.
    if (st.back.loop && !S.playing) {
      S.inView = cells(S.layer, S.frame).used;
      if (!setLoop(true)) S.loopWanted = true;
    } else if (st.back.playing) setPlay(true);
    if (/^#street=/.test(location.hash)) {
      try { history.replaceState(null, "", location.href.split("#")[0]); } catch (err) { /* the address keeps it */ }
    }
    streetDraw();
    if (focused && map.focus) map.focus({preventScroll: true});
    settle();
    return true;
  }
  // The stage as S.street has it. Google's frame is loaded only when the
  // point changes, so the walk the reader has taken in it stays, and not
  // while the point's street is being found.
  function streetDraw() {
    var st = S.street, pano = $("street-pano");
    setHidden($("street-stage"), !st);
    map.classList.toggle("streeton", !!st);
    if (!st) { STREET_SRC = ""; pano.innerHTML = ""; tcDraw(); return; }
    if (st.finding) {
      STREET_SRC = "";
      pano.innerHTML = '<p class="streetfinding">' + FINDING + "</p>";
    } else {
      var src = googleEmbed("street", st.lat, st.lon, S.z);
      if (src !== STREET_SRC) {
        STREET_SRC = src;
        pano.innerHTML = '<iframe class="streetframe" title="' + esc("Google Street View of " + st.label) +
                         '" src="' + esc(src) + '" allowfullscreen referrerpolicy="no-referrer-when-downgrade"></iframe>';
      }
    }
    setText($("street-place"), st.label);
    setHidden($("street-next"), !(st.roads && st.roads.length > 1));
    setHidden($("street-find"), !finite(st.unfound));
    setText($("street-roads"), roadsLine(st));
    $("street-gmaps").setAttribute("href", googleLinks(st.lat, st.lon, S.z).street);
    setText($("street-link"), st.link);
    miniDraw();
    streetChip();
    simDraw();
    tcDraw();
  }
  // For the page's API: where the street is.
  function streetView() {
    var st = S.street;
    return st ? {lon: st.lon, lat: st.lat, label: st.label, mini: st.mini} : null;
  }
  // The minimap's tiles: the map's own street layer around a point at zoom
  // z, each placed in a w by h box with the point at its middle; columns go
  // round the world, and past its top or bottom there is none.
  function miniTiles(lon, lat, z, w, h) {
    var n = Math.pow(2, z), left = mx(lon) * n * TILE - w / 2, top = my(lat) * n * TILE - h / 2, out = [];
    for (var row = Math.floor(top / TILE); row * TILE < top + h; row++) {
      if (row < 0 || row >= n) continue;
      for (var col = Math.floor(left / TILE); col * TILE < left + w; col++) {
        var x = (col % n + n) % n;
        out.push({x: x, y: row, z: z, left: Math.round(col * TILE - left), top: Math.round(row * TILE - top),
                  url: xyzUrl(LAYERS.streets.tiles, z, x, row)});
      }
    }
    return out;
  }
  // The point under a place on the minimap, x and y from its top left, as
  // its tiles were last drawn.
  function miniPoint(x, y) {
    var st = S.street, W = TILE * Math.pow(2, st.mini);
    return {lon: lonIn(lonOf(mx(st.lon) + (x - st.box.w / 2) / W)), lat: latOf(my(st.lat) + (y - st.box.h / 2) / W)};
  }
  // The minimap drawn at the size it shows, so a tap reads the tiles under
  // it; its buttons stop at the ends of its zoom.
  function miniDraw() {
    var st = S.street, r = $("street-mini").getBoundingClientRect();
    st.box = {w: Math.round(r.width) || 150, h: Math.round(r.height) || 112};
    setMarkup($("street-mini-tiles"), miniTiles(st.lon, st.lat, st.mini, st.box.w, st.box.h).map(function (t) {
      return '<img src="' + esc(t.url) + '" alt="" draggable="false" style="left:' + t.left + "px;top:" + t.top + 'px">';
    }).join(""));
    $("street-mini-in").disabled = st.mini >= MINI_MAX;
    $("street-mini-out").disabled = st.mini <= MINI_MIN;
  }
  function miniZoom(by) {
    if (!S.street) return;
    S.street.mini = clamp(S.street.mini + by, MINI_MIN, MINI_MAX);
    miniDraw();
  }
  // The chip: the card's sentence, as the card has it now, or that the
  // point's street is being found.
  function streetChip() {
    var st = S.street;
    if (st) setMarkup($("street-chip-said"), st.finding ? FINDING : streetSentence(streetState(st.lon, st.lat)));
  }
  // The chip's button: the whole card, at the top of Here, with Here put
  // back on the street's point first if it has moved since.
  function streetMore() {
    var st = S.street;
    if (!st) return;
    if (!S.here || streetCacheKey("", S.here.lon, S.here.lat) !== streetCacheKey("", st.lon, st.lat)) {
      hereAt(st.lon, st.lat, st.label);
    }
    var card = $("street-card");
    if (card && card.scrollIntoView) card.scrollIntoView({block: "start"});
  }
  // Then and now of the street's point, on the source and dates it showed
  // last (the first time, its own choice for the point).
  function streetThen() {
    var st = S.street, last = S.thenLast || {};
    if (!st) return false;
    return thenEnter(st.lon, st.lat, st.label, {source: last.source, preset: last.preset, a: last.a, b: last.b,
                                                  names: last.names});
  }
  // A point the reader picks - the figure let go, the minimap tapped, Here's
  // or then and now's Street View - goes first to the nearest street, as
  // Google Maps' figure goes to its blue lines: Google's embed looks only some
  // tens of metres about a point, so one in a block or a park found nothing,
  // or a shop's photo of its inside. The stage opens on the point at once;
  // OSRM is asked for the nearest roads a car may take, and the pick goes to
  // the nearest named one within SNAP_NAMED (or the reach, if further), else
  // the nearest of any name within reach: of thirty drops over Winter Haven
  // on 12 October 2026, eight of the thirteen that went to an unnamed way (a
  // driveway, a service road) found a panorama, and fourteen of the fifteen
  // that went to a named road. Next street goes down the other named roads,
  // to SNAP_FAR, and to the point as picked. OSRM not answering within
  // SNAP_HEDGE, or failing, Valhalla is asked too, and the first list either
  // gives is taken; each waits SNAP_WAIT at most, and neither giving one, the
  // point stays as picked, the stage says so and Find the street asks again.
  // Each is asked once a second at most, as their operator asks: a pick made
  // meanwhile replaces the one waiting for OSRM, Valhalla is asked only for
  // the pick the stage still has, and an answer for a stage since moved or
  // left is dropped.
  var SNAP_PX = 24, SNAP_NEAR = 250, SNAP_FAR = 5000, SNAP_WAIT = 6000, SNAP_HEDGE = 2500, SNAP_GAP = 1000;
  var SNAP_NAMED = 1000, SNAP_ROADS = 6, SNAP_RADIUS = 100, FINDING = "Finding the nearest street\u2026";
  var snapAt = -Infinity, locateAt = -Infinity, snapTimer = 0;
  function streetPick(lon, lat, z, label) {
    var fresh = !S.street, stage = $("street-stage");
    streetEnter(lon, lat, label, {find: true});
    // The stage covers the map: a pick that opens it takes the focus into
    // it, so keys go to the street and not to the map under it.
    if (fresh && stage.focus) stage.focus({preventScroll: true});
    var st = S.street;
    clearTimeout(snapTimer);
    snapTimer = setTimeout(function () {
      if (S.street !== st) return;
      snapAt = Date.now();
      snapStreet(st.lon, st.lat, snapReach(z, st.lat), function () { return S.street === st; }).then(function (roads) {
        if (S.street !== st) return;
        var picked = {lon: st.lon, lat: st.lat, label: st.label}, e = roads && roads[0];
        if (!e) streetEnter(st.lon, st.lat, st.label, {unfound: z});
        else streetEnter(e.lon, e.lat, roadLabel(e, picked), {roads: roads, road: 0, picked: picked});
      });
    }, Math.max(0, snapAt + SNAP_GAP - Date.now()));
    return true;
  }
  // How far a picked point may go for its street, in metres: 24 px of the
  // view it was picked on (zoom z, at its latitude), from 250 m to 5 km.
  function snapReach(z, lat) {
    return clamp(SNAP_PX * CIRCUMFERENCE * 1000 * Math.cos(rad(lat)) / (TILE * Math.pow(2, z)), SNAP_NEAR, SNAP_FAR);
  }
  // The list a pick goes down (roadList) from the first street finder to
  // give one: OSRM; and Valhalla too once OSRM has had SNAP_HEDGE, or as
  // soon as OSRM fails, while live() says the pick is still the stage's, a
  // second at least after Valhalla was last asked. Null when neither gives
  // one, or the pick has gone before Valhalla's turn.
  function snapStreet(lon, lat, reach, live) {
    return new Promise(function (resolve) {
      var asked = 1, failed = 0, done = false, hedge = 0, gap = 0;
      function finish(list) { done = true; clearTimeout(hedge); clearTimeout(gap); resolve(list); }
      function second() {
        asked = 2;
        var wait = locateAt + SNAP_GAP - Date.now();
        if (wait > 0) gap = setTimeout(locate, wait); else locate();
      }
      function locate() {
        if (done) return;
        if (!live()) { finish(null); return; }
        locateAt = Date.now();
        snapLocate(lon, lat, reach).then(end);
      }
      function end(list) {
        if (done) return;
        if (list) finish(list);
        else if (++failed === 2) finish(null);
        else if (asked === 1) { clearTimeout(hedge); second(); }
      }
      snapRoads(lon, lat, reach).then(end);
      hedge = setTimeout(function () { if (!done && asked === 1) second(); }, SNAP_HEDGE);
    });
  }
  // OSRM's nearest roads a car may take, as roadList's list; null for no
  // answer, or one not understood.
  function snapRoads(lon, lat, reach) {
    var url = D.street.roads.replace("{lon}", lon.toFixed(6)).replace("{lat}", lat.toFixed(6));
    return streetFetch(url, SNAP_WAIT).then(function (json) {
      if (!json || json.code !== "Ok" || !Array.isArray(json.waypoints)) return null;
      return roadList(json.waypoints.map(function (w) {
        var at = w && Array.isArray(w.location) ? w.location : [];
        return {lon: at[0], lat: at[1], name: w && w.name, d: w && w.distance};
      }), lon, lat, reach);
    }, function () { return null; });
  }
  // Valhalla's roads a car may take within SNAP_RADIUS of the point (else
  // its nearest), of a residential street's class or over and in no tunnel
  // or ferry, as roadList's list: a service road, a driveway or a car park's
  // aisle is where Google's car seldom went, and at the Battery on 14 October
  // 2026 the nearest road was the Brooklyn-Battery Tunnel, 38 m under the
  // pick. Null for no answer, or one not understood.
  function snapLocate(lon, lat, reach) {
    var ask = {locations: [{lat: +lat.toFixed(6), lon: +lon.toFixed(6), radius: SNAP_RADIUS,
                            search_filter: {min_road_class: "residential", exclude_tunnel: true, exclude_ferry: true}}],
               costing: "auto", verbose: true};
    return streetFetch(D.street.locate.replace("{json}", encodeURIComponent(JSON.stringify(ask))), SNAP_WAIT)
      .then(function (json) {
        var edges = Array.isArray(json) && json[0] && Array.isArray(json[0].edges) ? json[0].edges : null;
        return edges && roadList(edges.map(function (e) {
          var names = e && e.edge_info && Array.isArray(e.edge_info.names) ? e.edge_info.names : [];
          return {lon: e && e.correlated_lon, lat: e && e.correlated_lat, name: names[0], d: e && e.distance};
        }), lon, lat, reach);
      }, function () { return null; });
  }
  // Where a picked point may go, from a street finder's roads ({lon, lat,
  // name, d}: d in metres from the point), as a list of {lon, lat, name, d,
  // point}: first where the pick goes - the nearest named road within
  // SNAP_NAMED or the reach, whichever is further, else the nearest road of
  // any name within reach - then the other named roads to SNAP_FAR, each
  // name once at its nearest stretch, nearest first, SNAP_ROADS roads in all;
  // and the point as picked, last, or first when no road is taken. Null when
  // no road can be read.
  function roadList(roads, lon, lat, reach) {
    var named = {}, any = null;
    roads.forEach(function (w) {
      if (!finite(w.lon) || !finite(w.lat) || !finite(w.d) || w.d < 0) return;
      var r = {lon: lonIn(w.lon), lat: clamp(w.lat, -85, 85), name: typeof w.name === "string" ? w.name.trim() : "",
               d: w.d, point: false};
      if (!any || r.d < any.d) any = r;
      if (r.name && r.d <= SNAP_FAR && !(named[r.name] && named[r.name].d <= r.d)) named[r.name] = r;
    });
    if (!any) return null;
    var list = Object.keys(named).map(function (k) { return named[k]; }).sort(function (a, b) { return a.d - b.d; });
    var first = list.length && list[0].d <= Math.max(reach, SNAP_NAMED) ? list[0] : any && any.d <= reach ? any : null;
    var rest = list.filter(function (r) { return r !== first; }), point = {lon: lon, lat: lat, name: "", d: 0, point: true,
                                                                          reach: reach};
    return first ? [first].concat(rest.slice(0, SNAP_ROADS - 1), [point]) : [point].concat(rest.slice(0, SNAP_ROADS));
  }
  // An entry of a pick's list by name, as the stage's bar names it.
  function roadLabel(e, picked) { return e.point ? picked.label : (e.name ? e.name + ", " : "") + placeLabel(e.lon, e.lat); }
  // A distance in metres, as the line about a pick gives it: to the metre
  // under a kilometre, to a tenth of one over it.
  function roadDistance(m) {
    var r = Math.round(m);
    return r < 1000 ? r + " m" : (m / 1000).toFixed(1).replace(/\.0$/, "") + " km";
  }
  // The line about a pick: where the stage is against the point picked, and
  // where Next street goes from it, or that its street was not found.
  // Nothing for a point entered exactly.
  function roadsLine(st) {
    var list = st && st.roads;
    if (st && finite(st.unfound)) {
      return "The nearest street could not be found: this is Google\u2019s panorama nearest the point as picked, " +
             "if it has one.";
    }
    if (!list) return "";
    var k = st.road, e = list[k], n = list.length, said;
    if (e.point) {
      var named = Math.max(e.reach, SNAP_NAMED);
      said = "The point as picked" + (k > 0 ? " (" + (k + 1) + " of " + n + ")"
           : named > e.reach ? ": no named street within " + roadDistance(named) + ", nor any road within " +
                               roadDistance(e.reach) : ": no road within " + roadDistance(e.reach)) + ".";
    } else if (k === 0) {
      said = (e.name ? "The nearest named street, " : "The nearest road, ") + roadDistance(e.d) + " from the point picked." +
             (n > 1 ? " No panorama of it?" : "");
    } else {
      said = (e.name || "An unnamed road") + ", " + roadDistance(e.d) + " from the point picked (" + (k + 1) + " of " + n + ").";
    }
    if (n > 1) {
      var next = list[(k + 1) % n];
      said += " Next street: " + (next.point ? "the point picked" : (next.name || "an unnamed road") + ", " +
                                  roadDistance(next.d) + " away") + ".";
    }
    return said;
  }
  // Next street: the next entry of the pick's list, entered exactly, and
  // after the last the first again.
  function streetNext() {
    var st = S.street;
    if (!st || !st.roads || st.roads.length < 2) return false;
    var k = (st.road + 1) % st.roads.length, e = st.roads[k];
    return streetEnter(e.lon, e.lat, roadLabel(e, st.picked), {roads: st.roads, road: k, picked: st.picked});
  }
  // Find the street: a pick whose street was not found, asked again. Its
  // button goes as the search begins, and the focus on it goes to the stage,
  // as a pick's does.
  function streetFind() {
    var st = S.street, button = $("street-find"), stage = $("street-stage");
    if (!st || !finite(st.unfound)) return false;
    if (document.activeElement === button && stage.focus) stage.focus({preventScroll: true});
    return streetPick(st.lon, st.lat, st.unfound, st.label);
  }
  // The figure let go over the map, or a tap or Enter while it waits: a pick.
  function figureLand(lon, lat) { return streetPick(lon, lat, S.z); }
  // The point as an address to open again, to about a metre: #street=lat,lon.
  function streetHash() { return "#street=" + S.street.lat.toFixed(5) + "," + S.street.lon.toFixed(5); }
  function parseStreet(text) {
    var m = /^#street=(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)$/.exec(text || "");
    if (!m) return null;
    var lat = +m[1], lon = +m[2];
    if (Math.abs(lat) > 90 || Math.abs(lon) > 360) return null;
    return {lat: lat, lon: lonIn(lon)};
  }
  function streetHashApply(text) {
    var h = parseStreet(text);
    return h ? streetEnter(h.lon, h.lat) : false;
  }
  // The link to the point: to the clipboard where the browser allows it,
  // and shown in the bar either way.
  function streetCopy() {
    var st = S.street;
    if (!st) return;
    var url = location.href.split("#")[0] + streetHash();
    st.link = "Copy this link: " + url;
    setText($("street-link"), st.link);
    try {
      navigator.clipboard.writeText(url).then(function () {
        if (S.street === st) { st.link = "Link copied: " + url; setText($("street-link"), st.link); }
      }, function () { /* the link stays shown, to copy by hand */ });
    } catch (err) { /* no clipboard: the link stays shown */ }
  }
  // ---- the replay: El Nino's rain, day by day, on the street ---------------------------
  // The replay, in the chip's place while it is open. S.sim is the window's
  // first month (start, 1 to 12), the run shown (tag: a past El Nino's year
  // as text, or "now" for this year's), the day shown and how far Play has
  // run towards the next (pos), the speed in days a second, whether it
  // plays, the POWER cell it is for (key) with the record and the model once
  // they come or what went wrong (why), the frame asked for and the time of
  // the last, whether a pointer seeks on the chart and a finger down on it
  // not yet seeking (touch), and the chart's geometry as last drawn. A finger
  // seeks once it goes SIM_SLOP px across, more than up or down.
  S.sim = null;
  var SIM_SPEEDS = [7, 14, 30], SIM_HELD = 250, SIM_SLOP = 8;
  var SIM_LOADING = "Reading NASA POWER\u2019s days for this place, every one since 1981\u2026";
  // The replay opened on the stage's point at next month's window, the storm
  // panel closed first, its record asked if it has not got the cell's, the
  // focus on the panel.
  function simOpen() {
    if (!S.street) return false;
    if (S.tc) tcClose();
    if (!S.sim) {
      var start = new Date(Date.now()).getUTCMonth() + 2;
      S.sim = {start: start > 12 ? start - 12 : start, tag: null, day: 0, pos: 0, speed: SIM_SPEEDS[0],
               playing: false, key: "", rec: null, model: null, why: "", frame: 0, last: 0, seeking: false, touch: null,
               geo: null};
    }
    simLoad();
    simDraw();
    tcDraw();
    var panel = $("street-sim");
    if (panel.focus) panel.focus({preventScroll: true});
    return true;
  }
  // The replay closed: Play stopped, the card's chip back, and the focus, if
  // it was in the panel, on the button that opens it - unless the stage is
  // being left, which puts it on the map.
  function simClose(leaving) {
    var sim = S.sim, panel = $("street-sim"), on = document.activeElement;
    if (!sim) return false;
    var inside = !!on && !!panel.contains && panel.contains(on), opener = $("street-replay");
    if (sim.frame) cancelAnimationFrame(sim.frame);
    S.sim = null;
    simDraw();
    tcDraw();
    if (inside && !leaving && opener.focus) opener.focus({preventScroll: true});
    return true;
  }
  // The record of the stage's cell, asked when it is not the replay's: an
  // answer for a cell since left is not shown, and the replay, moved, stops
  // where it was.
  function simLoad() {
    var sim = S.sim, st = S.street;
    if (!sim || !st || st.finding) return;
    var cell = simCell(st.lon, st.lat);
    if (cell.key === sim.key) return;
    simPlay(false);
    sim.key = cell.key; sim.rec = null; sim.model = null; sim.why = "";
    simGet(st.lon, st.lat).then(function (rec) {
      if (S.sim !== sim || sim.key !== cell.key) return;
      sim.rec = rec;
      simBuild();
      simDraw();
    }, function (err) {
      if (S.sim !== sim || sim.key !== cell.key) return;
      sim.why = err && err.why || "could not be read";
      simDraw();
    });
  }
  // The record asked for again, by the panel's Retry.
  function simRetry() {
    if (!S.sim) return false;
    S.sim.key = "";
    simLoad();
    simDraw();
    return true;
  }
  // The replay's model from its record, ECMWF's months as the card has them
  // for the point, and the reader's clock.
  function simBuild() {
    var sim = S.sim, st = S.street, ahead = st ? streetState(st.lon, st.lat).got.ahead : null;
    sim.model = simModel(sim.rec, sim.start, ahead ? seasonalRows(ahead) : null, Date.now());
    simFit();
  }
  // The model built again on the record it has, as a run taken in place
  // brings a new index: the run and the day shown kept where it still has
  // them.
  function simRetake() {
    var sim = S.sim;
    if (!sim || !sim.rec) return false;
    simBuild();
    simDraw();
    return true;
  }
  // The run shown kept if the model has it, else the strongest El Nino, else
  // this year's; the day shown within it.
  function simFit() {
    var sim = S.sim, m = sim.model;
    var tags = m.events.map(function (r) { return String(r.tag); }).concat(m.now ? ["now"] : []);
    if (tags.indexOf(sim.tag) < 0) sim.tag = m.strongest !== null ? String(m.strongest) : m.now ? "now" : null;
    var run = simChosen();
    sim.day = run ? clamp(sim.day, 0, run.p.length - 1) : 0;
    sim.pos = sim.day;
  }
  // Whether the replay can be played, sought or chosen: it has a run to show
  // and the stage's street is not being found, the record shown being the
  // last point's.
  function simLive() { return !!simChosen() && !!S.street && !S.street.finding; }
  // The run the replay shows: the past El Nino chosen, or this year's.
  function simChosen() {
    var sim = S.sim, m = sim && sim.model;
    if (!m || sim.tag === null) return null;
    if (sim.tag === "now") return m.now;
    for (var i = 0; i < m.events.length; i++) if (String(m.events[i].tag) === sim.tag) return m.events[i];
    return null;
  }
  // Another run shown, on the same day of the window; another window, from
  // its first day.
  function simPick(tag) {
    var sim = S.sim;
    if (!sim || !sim.model) return false;
    sim.tag = String(tag);
    simFit();
    simDraw();
    return true;
  }
  function simStart(start) {
    var sim = S.sim;
    if (!sim || !(start >= 1 && start <= 12)) return false;
    simPlay(false);
    sim.start = Math.round(start);
    sim.day = 0;
    if (sim.rec) simBuild();
    simDraw();
    return true;
  }
  // The panel as S.sim has it, in the chip's place, with the rain over the
  // panorama, or the card's chip back.
  function simDraw() {
    var sim = S.sim, on = !!sim && !!S.street, covered = on || !!S.tc && !!S.street;
    $("street-stage").classList.toggle("simon", on);
    setHidden($("street-sim"), !on);
    setHidden($("street-sim-credit"), !on);
    // The chip's head and sentence give their place to either panel.
    setHidden($("street-chip-head"), covered);
    setHidden($("street-chip-said"), covered);
    if (!on) { rainDay(""); return; }
    var m = sim.model, run = simChosen(), live = simLive(), pick = $("street-sim-event"), slider = $("street-sim-day");
    setValue($("street-sim-start"), String(sim.start));
    setValue($("street-sim-speed"), String(sim.speed));
    setMarkup(pick, m ? simOptions(m) : "");
    setValue(pick, sim.tag === null ? "" : sim.tag);
    pick.disabled = !live;
    $("street-sim-play").disabled = !live;
    slider.max = String(run ? run.p.length - 1 : 0);
    slider.disabled = !live;
    setHidden($("street-sim-fail"), !sim.why);
    setText($("street-sim-why"), sim.why ? "NASA POWER\u2019s days for this place could not be read (" + sim.why + ")." : "");
    setMarkup($("street-sim-said"), sim.why ? "" : m ? simWords(m, run) : SIM_LOADING);
    setMarkup($("street-sim-key"), m && run ? simKey(m, run) : "");
    setMarkup($("street-sim-table"), m ? simTable(m, run) : "");
    setMarkup($("street-sim-method"), simMethod(sim.rec));
    simChartDraw();
    simDay(sim.day);
  }
  // The runs to choose from: this year's first, then the El Ninos, newest
  // first, each with the index's peak in the window's first season.
  function simOptions(m) {
    var out = m.now ? ['<option value="now">' + esc((m.now.partial ? "This year so far, " : "This year, ") + m.now.label) +
                       "</option>"] : [];
    m.events.forEach(function (r) {
      out.push('<option value="' + r.tag + '">' + esc(r.label + " (" + signedText(r.peak, 1) + ")") + "</option>");
    });
    return out.join("");
  }
  // The day shown: the slider, the readout, the playhead, and the rain over
  // the panorama with the badge naming the day.
  function simDay(k) {
    var sim = S.sim, run = simChosen(), slider = $("street-sim-day");
    if (!sim) return;
    if (!run) {
      setText($("street-sim-read"), "");
      slider.removeAttribute("aria-valuetext");
      rainDay("");
      return;
    }
    sim.day = clamp(Math.floor(k) || 0, 0, run.p.length - 1);
    var p = run.p[sim.day], when = simDate(run.first + sim.day * SIM_DAY) + ": " + (p === null ? "rain not on record" : simMm(p));
    setValue(slider, String(sim.day));
    if (slider.getAttribute("aria-valuetext") !== when) slider.setAttribute("aria-valuetext", when);
    setText($("street-sim-read"), simRead(sim.model, run, sim.day));
    simHead();
    rainDay(when);
  }
  // The readout: the day, its rain and temperature, and the rain so far
  // against the neutral years' by the same date.
  function simRead(m, run, k) {
    var p = run.p[k], t = run.t[k], b = simBandOn(m, run.first, k);
    return simDate(run.first + k * SIM_DAY) + ": " + (p === null ? "rain not on record" : simMm(p) + " (" + simIn(p) +
      ") of rain") + (t === null ? "" : ", " + simC(t)) + ". So far " + simMm(run.cum[k]) + " (" + simIn(run.cum[k]) + ")" +
      (b ? "; neutral years by this day " + simMm(b.mean) + " (10th to 90th percentile " + simNum(b.lo) + " to " +
       simMm(b.hi) + ")" : "") + ".";
  }
  // Play or pause, from the day shown, or from the first when the last is
  // shown.
  function simPlay(on) {
    var sim = S.sim, run = simChosen(), button = $("street-sim-play");
    if (!sim) return false;
    on = !!on && simLive();
    if (on && !sim.playing) {
      if (sim.day >= run.p.length - 1) simDay(0);
      sim.pos = sim.day;
    }
    sim.playing = on;
    sim.last = 0;
    setText(button, on ? "Pause" : "Play");
    simFrame();
    return on;
  }
  // A frame asked for while the replay plays or its rain falls, and none
  // while neither does.
  function simFrame() {
    var sim = S.sim;
    if (!sim) return;
    var want = sim.playing || rainOn();
    if (want && !sim.frame) sim.frame = requestAnimationFrame(simTick);
    else if (!want && sim.frame) { cancelAnimationFrame(sim.frame); sim.frame = 0; }
  }
  // A frame: Play's days moved on by the time since the last at the speed
  // chosen - a frame held back, as in a tab in the background, counting
  // SIM_HELD at most - to the window's end, where Play stops; and the rain,
  // while it falls, drawn.
  function simTick(ts) {
    var sim = S.sim;
    if (!sim) return;
    sim.frame = 0;
    if (sim.playing) {
      var run = simChosen(), end = run ? run.p.length - 1 : 0;
      if (sim.last) sim.pos = Math.min(end, sim.pos + Math.min(ts - sim.last, SIM_HELD) / 1000 * sim.speed);
      sim.last = ts;
      if (Math.floor(sim.pos) !== sim.day) simDay(sim.pos);
      if (!run || sim.pos >= end) simPlay(false);
    }
    if (rainOn()) rainPaint(ts);
    simFrame();
  }
  // The day under a pointer on the chart, or a step of the slider.
  function simSeek(clientX) {
    var sim = S.sim, g = sim && sim.geo;
    if (!g || !simLive()) return false;
    var r = $("street-sim-chart").getBoundingClientRect(), x = (clientX - r.left) * g.width / (r.width || g.width);
    simDay(Math.floor((x - g.L) / g.W * g.N));
    sim.pos = sim.day;
    return true;
  }
  function simSeekDay(k) {
    if (!S.sim || !simLive()) return false;
    simDay(k);
    S.sim.pos = S.sim.day;
    return true;
  }
  // The chart sought from a pointer's event, the chart holding the pointer
  // until it is let go.
  function simSeekFrom(e) {
    if (!simSeek(e.clientX)) return false;
    S.sim.seeking = true;
    try { if (e.pointerId !== undefined) e.currentTarget.setPointerCapture(e.pointerId); } catch (err) { /* seeks while over it */ }
    return true;
  }
  // A replay's chart sought by its pointers (box), the replay's state as
  // panel() has it, null while it is closed. A mouse or pen down on the chart
  // seeks (seekFrom), and seeks as it moves until it is let go. A finger
  // seeks where it is lifted, or once it goes across (SIM_SLOP) and on as it
  // moves; moving up or down first, it scrolls the panel (pan-y, the
  // browser's) and seeks nothing.
  function simPointers(box, panel, seek, seekFrom) {
    box.addEventListener("pointerdown", function (e) {
      var p = panel();
      if (!p || (e.button !== undefined && e.button !== 0)) return;
      if (e.pointerType === "touch") p.touch = {id: e.pointerId, x: e.clientX, y: e.clientY};
      else seekFrom(e);
    });
    box.addEventListener("pointermove", function (e) {
      var p = panel(), t = p && p.touch;
      if (p && p.seeking) { seek(e.clientX); return; }
      if (!t || t.id !== e.pointerId) return;
      var across = Math.abs(e.clientX - t.x), up = Math.abs(e.clientY - t.y);
      if (across > SIM_SLOP && across > up) { p.touch = null; seekFrom(e); }
      else if (up > SIM_SLOP) p.touch = null;
    });
    box.addEventListener("pointerup", function (e) {
      var p = panel();
      if (!p) return;
      if (p.touch && p.touch.id === e.pointerId) seek(e.clientX);
      p.touch = null;
      p.seeking = false;
    });
    box.addEventListener("pointercancel", function () {
      var p = panel();
      if (p) { p.touch = null; p.seeking = false; }
    });
  }
  // The chart drawn at the width it has, and the playhead on the day shown.
  function simChartDraw() {
    var sim = S.sim, box = $("street-sim-chart"), run = simChosen();
    if (!sim || !sim.model || !run) { setMarkup(box, ""); if (sim) sim.geo = null; return; }
    var c = simChart(sim.model, run, Math.round(box.getBoundingClientRect().width) || 320);
    sim.geo = c.geo;
    setMarkup(box, c.svg);
  }
  function simHead() {
    var sim = S.sim, g = sim && sim.geo, run = simChosen(), head = $("street-sim-head"), dot = $("street-sim-dot");
    if (!g || !run || !head || !dot) return;
    var x = Math.round((g.L + (sim.day + 1) * g.W / g.N) * 10) / 10;
    head.setAttribute("x1", x);
    head.setAttribute("x2", x);
    dot.setAttribute("cx", x);
    dot.setAttribute("cy", Math.round((g.T + g.PH * (1 - run.cum[sim.day] / g.top)) * 10) / 10);
  }
  // The chart, w px wide: the rain accumulated over the window day by day -
  // the neutral years' mean dashed over the band of their 10th to 90th
  // percentiles, by the same dates as the run shown, the El Ninos faint in El
  // Nino's red, each named where a pointer rests on it, and the one shown bold,
  // ECMWF's projection dashed blue, this year's in ink - each named line
  // labelled at its end, those at the window's end kept apart; under it the
  // run's rain each day as bars, the months along the foot, and the
  // playhead. Its geometry kept, to place the playhead and to seek.
  function simChart(m, run, w) {
    var L = 36, R = 66, T = 8, PH = 112, BT = 128, BH = 26, H = 170, W = Math.max(40, w - L - R), N = 1, top = 10;
    var e = m.ecmwf, shown = run === m.now, out = [], labels = [], i, k;
    function r1(v) { return Math.round(v * 10) / 10; }
    function x(d) { return r1(L + d * W / N); }
    function y(v) { return r1(T + PH * (1 - v / top)); }
    function mark(v) { return v % 1 === 0 ? simNum(v) : v.toFixed(1); }
    function path(c) {
      var d = "M" + L + "," + y(0);
      for (var j = 0; j < c.length; j++) d += "L" + x(j + 1) + "," + y(c[j]);
      return d;
    }
    function label(c, text, cls) {
      var edge = c.length >= N - 2;
      labels.push({x: edge ? L + W + 4 : x(c.length) + 4, y: y(c[c.length - 1]) + 3.5, text: text, cls: cls, edge: edge});
    }
    m.events.concat(m.now ? [m.now] : []).forEach(function (r) {
      N = Math.max(N, r.partial ? simWindow(m.start, r.tag).days : r.cum.length);
      top = Math.max(top, r.total);
    });
    var bm = [], bl = [], bh = [], days = simWindow(m.start, run.tag).days;
    for (k = 0; k < days; k++) {
      var on = simBandOn(m, run.first, k);
      if (!on) break;
      bm.push(on.mean); bl.push(on.lo); bh.push(on.hi);
    }
    if (bm.length) { N = Math.max(N, bm.length); top = Math.max(top, bh[bh.length - 1]); }
    if (e) { N = Math.max(N, e.cum.length); top = Math.max(top, e.total); }
    top = simCeil(top);
    out.push('<svg class="streetsimsvg" viewBox="0 0 ' + w + " " + H + '" width="' + w + '" height="' + H +
             '" role="img" aria-label="' + esc(simChartSaid(m, run)) + '">');
    [0, top / 2, top].forEach(function (v) {
      out.push('<line class="grid" x1="' + L + '" x2="' + (L + W) + '" y1="' + y(v) + '" y2="' + y(v) + '"/><text x="' +
               (L - 4) + '" y="' + r1(y(v) + 3.5) + '" text-anchor="end">' + mark(v) + "</text>");
    });
    out.push('<text x="' + (L + 4) + '" y="' + (T + 9) + '">rain so far, mm</text>');
    if (bm.length) {
      var band = "M" + L + "," + y(0);
      for (k = 0; k < bl.length; k++) band += "L" + x(k + 1) + "," + y(bl[k]);
      for (k = bh.length - 1; k >= 0; k--) band += "L" + x(k + 1) + "," + y(bh[k]);
      out.push('<path class="band" d="' + band + 'Z"/>');
    }
    m.events.forEach(function (r) {
      if (r === run) return;
      out.push('<path class="evfaint" d="' + path(r.cum) + '"><title>' + esc(r.label + " (" + signedText(r.peak, 1) +
               "): " + simMm(r.total)) + "</title></path>");
    });
    if (bm.length) { out.push('<path class="neutral" d="' + path(bm) + '"/>'); label(bm, "Neutral", "neutral"); }
    if (e) { out.push('<path class="ecmwf" d="' + path(e.cum) + '"/>'); label(e.cum, "ECMWF", "ecmwf"); }
    if (m.now) {
      out.push('<path class="now" d="' + path(m.now.cum) + '"' + (shown ? ' style="stroke-width:2.75px"' : "") + "/>");
      label(m.now.cum, "This year", "now");
    }
    if (!shown) { out.push('<path class="ev" d="' + path(run.cum) + '"/>'); label(run.cum, run.label, "ev"); }
    var most = 1, bars = "", bw = W / N, gap = bw > 3 ? 1 : 0;
    run.p.forEach(function (p) { if (p !== null && p > most) most = p; });
    most = simCeil(most);
    run.p.forEach(function (p, d) {
      if (p === null || p <= 0) return;
      var h = r1(Math.max(0.5, p / most * BH));
      bars += "M" + r1(L + d * bw + gap / 2) + "," + r1(BT + BH - h) + "h" + r1(bw - gap) + "v" + h + "h" + r1(gap - bw) + "z";
    });
    out.push('<path class="bars" d="' + bars + '"/><text x="' + (L - 4) + '" y="' + (BT + 7) + '" text-anchor="end">' +
             mark(most) + "</text>");
    var first = new Date(run.first);
    for (i = 0; i < SIM_MONTHS; i++) {
      var at = Date.UTC(first.getUTCFullYear(), first.getUTCMonth() + i, 1), tx = x((at - run.first) / SIM_DAY);
      out.push('<line class="tick" x1="' + tx + '" x2="' + tx + '" y1="' + (BT + BH) + '" y2="' + (BT + BH + 4) +
               '"/><text x="' + r1(tx + 2) + '" y="' + (H - 2) + '">' + MONTHS[new Date(at).getUTCMonth()] + "</text>");
    }
    var edge = labels.filter(function (l) { return l.edge; }).sort(function (a, c) { return a.y - c.y; });
    for (i = 1; i < edge.length; i++) edge[i].y = Math.max(edge[i].y, edge[i - 1].y + 11);
    var over = edge.length ? edge[edge.length - 1].y - (T + PH + 3.5) : 0;
    if (over > 0) edge.forEach(function (l) { l.y -= over; });
    labels.forEach(function (l) {
      out.push('<text class="lab ' + l.cls + '" x="' + r1(l.x) + '" y="' + r1(l.y) + '">' + esc(l.text) + "</text>");
    });
    out.push('<line id="street-sim-head" class="head" x1="' + L + '" x2="' + L + '" y1="' + T + '" y2="' + (BT + BH) +
             '"/><circle id="street-sim-dot" class="dot' + (shown ? " ink" : "") + '" r="3.5" cx="' + L + '" cy="' + y(0) +
             '"/></svg>');
    return {svg: out.join(""), geo: {L: L, W: W, N: N, T: T, PH: PH, top: top, width: w}};
  }
  // What the chart shows, in words, for a reader who cannot see it.
  function simChartSaid(m, run) {
    var said = [(run === m.now ? (run.partial ? "this year so far " : "this year ") : run.label + " ") + simMm(run.total)];
    if (m.base) said.push("the neutral years\u2019 mean " + simMm(m.base.total));
    if (m.ecmwf) said.push("ECMWF\u2019s forecast " + simMm(m.ecmwf.total));
    return "Rain accumulated, " + m.words + ": " + said.join("; ") + ".";
  }
  // A scale's top: the value rounded up to 1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6 or
  // 8 of its power of ten.
  function simCeil(v) {
    var p = Math.pow(10, Math.floor(Math.log(v) / Math.LN10)), steps = [1, 1.2, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10];
    for (var i = 0; i < steps.length; i++) if (steps[i] * p >= v - 1e-9) return Math.round(steps[i] * p * 1000) / 1000;
    return 10 * p;
  }
  // The chart's key: each line it draws, and whose rain the bars are.
  function simKey(m, run) {
    var shown = run === m.now, out = [], others = m.events.length - (shown ? 0 : 1);
    if (!shown) out.push('<span class="ev">' + esc(run.label) + "</span>");
    if (others > 0) out.push('<span class="faint">' + (shown ? "El Ni\u00f1os" : "other El Ni\u00f1os") + "</span>");
    if (m.band) out.push('<span class="neutral">neutral years\u2019 mean, 10th to 90th percentile shaded</span>');
    if (m.ecmwf) {
      out.push('<span class="ecmwf">ECMWF ' + esc(m.ecmwf.label + (m.ecmwf.months.length === SIM_MONTHS ? "" : ", " +
               simSpan(m.ecmwf.months))) + "</span>");
    }
    if (m.now) out.push('<span class="now">' + (m.now.partial ? "this year so far" : "this year") + "</span>");
    out.push('<span class="bars">bars: ' + esc(shown ? "this year" : run.label) + "\u2019s rain each day</span>");
    return out.join("");
  }
  // The replay's words: the run shown against the neutral years - its rain,
  // its days of 20 mm or more, its wettest day, its longest dry spell and its
  // warmth - what the El Ninos brought on average and how many were wetter,
  // and what ECMWF's forecast comes to; this year so far against both by the
  // same day.
  function simWords(m, run) {
    var b = m.base, out = [];
    if (!run) {
      return "No El Ni\u00f1o since 1981 reached +" + D.street.warm.toFixed(1) + " in " + esc(simSeason(m.start)) +
        " with POWER\u2019s record of its window whole here, and this year\u2019s " + (m.begun ? "has fewer than " +
        SIM_SOON + " days on POWER\u2019s record yet" : "has not begun") + ": there is nothing to replay for " +
        esc(m.words) + ".";
    }
    if (run.partial) {
      var k = run.cum.length - 1, j = simOnDay(run.first, k), on = simBandOn(m, run.first, k), against = [];
      var evs = m.events.map(function (r) { return simCumOn(r, j); }).filter(function (v) { return v !== null; });
      if (on) against.push(simMm(on.mean) + " by the same day in the neutral years");
      if (evs.length) against.push(simMm(streetMean(evs)) + " in the El Ni\u00f1os");
      return "<b>" + esc(m.words + " " + run.label) + " so far</b>, " + simDays(k + 1) + " to " +
        simDate(run.first + k * SIM_DAY) + ": " + simMm(run.total) +
        (against.length ? ", against a mean of " + against.join(" and ") : "") + ".";
    }
    out.push("<b>" + esc(m.words + " " + run.label) + "</b>" + (run === m.now ? ", in the El Ni\u00f1o under way," : "") +
             " brought " + simMm(run.total) + " here" + (b && b.total > 0 ? ", " + Math.round(run.total / b.total * 100) +
             "% of the neutral years\u2019 mean of " + simMm(b.total) + " (" + b.years + " years)" : "") + ".");
    out.push(simDays(run.r20) + " of 20 mm or more" + (b ? " (neutral years: " + simCount(b.r20) + " on average)" : "") + ".");
    if (run.wettest) {
      out.push("Wettest day: " + simMm(run.wettest.mm) + " on " + simDate(run.first + run.wettest.day * SIM_DAY) + ".");
    }
    out.push("Longest dry spell: " + simDays(run.dry) + (b ? " (neutral years: " + simDays(b.dry) + ")" : "") + ".");
    if (run.tmean !== null) {
      out.push("Mean temperature " + simC(run.tmean) + (b && b.tmean !== null ? ", " + simWarmer(run.tmean - b.tmean) +
               " the neutral years\u2019 " + simC(b.tmean) : "") + ".");
    }
    if (run.missing) {
      out.push(simDays(run.missing) + " missing from POWER\u2019s record " + (run.missing === 1 ? "is" : "are") +
               " counted dry.");
    }
    if (b && m.events.length > 1) {
      out.push("Over the " + m.events.length + " El Ni\u00f1os replayable here since 1981, these months brought " +
               simMm(streetMean(m.events.map(function (r) { return r.total; }))) + " on average, more than the neutral " +
               "mean in " + m.events.filter(function (r) { return r.total > b.total; }).length + " of them.");
    }
    if (m.ecmwf) {
      var e = m.ecmwf, whole = e.months.length === SIM_MONTHS, by = simBandOn(m, e.first, e.cum.length - 1);
      out.push("ECMWF\u2019s forecast for " + esc((whole ? m.words : simSpan(e.months)) + " " + e.label) +
               (whole ? "" : ", the months it reaches,") + " comes to " + simMm(e.total) + " here, against " +
               simMm(e.base) + " in an average year" + (by ? " and " + simMm(by.mean) + " in the neutral years\u2019 mean" :
               "") + ".");
    }
    return out.join(" ");
  }
  // A difference of temperature in words: "1.7 deg C cooler than".
  function simWarmer(d) {
    var r = Math.round(d * 10) / 10;
    return r === 0 ? "the same as" : Math.abs(r).toFixed(1) + " \u00b0C " + (r > 0 ? "warmer" : "cooler") + " than";
  }
  // A window's first season, and the months from the first to the last of
  // a list, in words.
  function simSeason(start) { return MONTH_WORDS[start - 1] + " to " + MONTH_WORDS[(start + 1) % 12]; }
  function simSpan(months) {
    var a = MONTH_WORDS[+months[0].slice(5) - 1], z = MONTH_WORDS[+months[months.length - 1].slice(5) - 1];
    return months.length > 1 ? a + " to " + z : a;
  }
  // Year by year: this year's, each El Nino's and the neutral mean, with the
  // same measures, and ECMWF's sum.
  function simTable(m, run) {
    var b = m.base, rows = [];
    var head = ["Window", D.street.index + " peak", "Rain", "Of neutral", "Days of 20 mm+", "Wettest day",
                "Longest dry spell", "Mean temperature", "Days missing"];
    function pct(v, base) { return base > 0 ? Math.round(v / base * 100) + "%" : ""; }
    function row(cls, name, cells) {
      return "<tr" + (cls ? ' class="' + cls + '"' : "") + '><th scope="row">' + esc(name) + "</th>" +
             cells.map(function (c) { return "<td>" + esc(c) + "</td>"; }).join("") + "</tr>";
    }
    function line(r, name, peak) {
      var by = r.partial ? simBandOn(m, r.first, r.cum.length - 1) : null;
      var base = r.partial ? (by ? by.mean : 0) : b ? b.total : 0;
      return row(r === run ? "strong" : "", name, [peak, simMm(r.total), pct(r.total, base), String(r.r20),
                 r.wettest ? simMm(r.wettest.mm) : "", simDays(r.dry), r.tmean === null ? "" : simC(r.tmean),
                 String(r.missing)]);
    }
    if (m.now) rows.push(line(m.now, (m.now.partial ? "This year so far, " : "This year, ") + m.now.label, ""));
    m.events.forEach(function (r) { rows.push(line(r, r.label, signedText(r.peak, 1))); });
    if (b) {
      rows.push(row("", "Neutral years\u2019 mean (" + b.years + ")", ["", simMm(b.total), "100%", simCount(b.r20), "",
                                                                     simDays(b.dry), b.tmean === null ? "" : simC(b.tmean), ""]));
    }
    if (m.ecmwf) {
      var e = m.ecmwf, whole = e.months.length === SIM_MONTHS, at = simBandOn(m, e.first, e.cum.length - 1);
      rows.push(row("", "ECMWF\u2019s forecast, " + e.label + (whole ? "" : " (" + simSpan(e.months) + " only)"),
                    ["", simMm(e.total), pct(e.total, at ? at.mean : 0), "", "", "", "", ""]));
    }
    return '<table class="streettable"><thead><tr>' + head.map(function (h) {
      return '<th scope="col">' + esc(h) + "</th>";
    }).join("") + "</tr></thead><tbody>" + rows.join("") + "</tbody></table>";
  }
  // How the replay knows what it plays, and whose data it is, in the words
  // each source asks for.
  function simMethod(rec) {
    var st = S.street, R = D.street, since = ongoingFrom(), from = rec ? Date.parse(rec.from + "T00:00:00Z") : 0;
    var km = st ? Math.round(0.625 * 111.32 * Math.cos(st.lat * Math.PI / 180)) : 0;
    return "<p>The replay plays what fell. Its days are NASA POWER\u2019s daily record for this place\u2019s grid cell: " +
      "MERRA-2\u2019s rainfall, corrected against gauges (PRECTOTCORR), and 2 m temperature (T2M), on a 0.5\u00b0 by " +
      "0.625\u00b0 grid, about 55 by " + km + " km here" + (rec ? ", from " + simDate(from) + " to " +
      simDate(from + (rec.p.length - 1) * SIM_DAY) : "") + ". A day is the cell\u2019s mean, smoother than a " +
      "gauge\u2019s, and POWER\u2019s newest days are NASA\u2019s GEOS-IT analysis, not MERRA-2. POWER is sent the " +
      "cell\u2019s grid point, not the place.</p>" +
      "<p>A window is the six months from the first of the month chosen, named for its year, or for the two it spans " +
      "(\u201c1997-98\u201d). It is an El Ni\u00f1o\u2019s when " + esc(R.index) + " centred on one of its first three " +
      "months is +" + R.warm.toFixed(1) + " or more (its peak the highest of the three), as the card takes its El " +
      "Ni\u00f1os for the season ahead, and a neutral year\u2019s when all three are within \u00b1" + R.neutral.toFixed(1) +
      (since ? "; the El Ni\u00f1o under way since " + streetMonthWords(since) + " is this year\u2019s, not a past one" :
       "") + ". It is the index as the window opens, as a forecast made then would have it: a window from spring " +
      "takes El Ni\u00f1os growing and fading alike. A window counts when the record has all its days but five at " +
      "most, and a day missing counts as dry. Days of 20 mm or more are ETCCDI\u2019s R20mm; the longest dry spell, " +
      "its CDD, is the most days running under 1 mm. The band is the neutral years\u2019 10th to 90th percentile of " +
      "the rain accumulated by each date of the window, 29 February counted with the 28th.</p>" +
      "<p>ECMWF\u2019s forecast comes to the place by the delta method: for each month of the coming window it " +
      "forecasts, POWER\u2019s mean for that calendar month over every complete year here since 1981, scaled by the " +
      "model\u2019s forecast against its own climate of past forecasts where that climate is " + R.dry_floor +
      " mm a day or more, else with the model\u2019s anomaly added, never under nothing. It is drawn only for a " +
      "window not yet begun.</p>" +
      "<p>The rain over Street View is the page\u2019s drawing, not Google\u2019s: nothing under 0.5 mm, and above it " +
      "streaks as many and as fast as the day\u2019s rain is heavy, up to 50 mm, with the sky dimmed to match; snow " +
      "where the day\u2019s mean temperature is at or below 0 \u00b0C. Google\u2019s imagery under it is as Google took " +
      "it.</p>" +
      '<p class="links"><a href="https://power.larc.nasa.gov/" target="_blank" rel="noopener">NASA POWER \u2197</a>' +
      openMeteo() + '<a href="https://www.ecmwf.int/" target="_blank" rel="noopener">ECMWF \u2197</a></p>' +
      streetAcknowledged();
  }
  // Numbers as the replay says them: millimetres to a tenth under 10 and
  // whole over it, thousands set apart; inches; counts; days; degrees; dates.
  function simNum(v) {
    if (v === 0) return "0";
    if (Math.abs(v) < 10) return v.toFixed(1);
    return String(Math.round(v)).replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  }
  function simMm(v) { return simNum(v) + " mm"; }
  function simIn(v) { var x = v / 25.4; return x.toFixed(x < 1 ? 2 : 1) + " in"; }
  function simCount(v) { return v % 1 === 0 ? String(v) : v.toFixed(1); }
  function simDays(n) { return simCount(n) + (n === 1 ? " day" : " days"); }
  function simC(v) { var r = Math.round(v * 10) / 10; return (r < 0 ? "\u2212" : "") + Math.abs(r).toFixed(1) + " \u00b0C"; }
  function simDate(ms) {
    var d = new Date(ms);
    return d.getUTCDate() + " " + MONTH_WORDS[d.getUTCMonth()] + " " + d.getUTCFullYear();
  }
  // ---- the rain over Street View ---------------------------------------------------------
  // The rain the page draws over Google's panorama for a day of the replay,
  // from the day's rain (mm) and mean temperature (deg C): none for a day
  // the record does not have, dry under half a millimetre, else a strength
  // s, the root of the rain against 50 mm, up to 1, giving 20 + 380 s
  // streaks falling 1 + 1.2 s of the view a second - or, at or below 0 deg
  // C, 30 + 270 s flakes falling 0.12 + 0.12 s - and the sky dimmed by
  // 0.08 + 0.3 s.
  function rainLevel(mm, t) {
    if (typeof mm !== "number" || !isFinite(mm)) return {kind: "none", drops: 0, gloom: 0, speed: 0};
    if (mm < 0.5) return {kind: "dry", drops: 0, gloom: 0, speed: 0};
    var s = Math.min(1, Math.sqrt(mm / 50)), snow = typeof t === "number" && t <= 0;
    return {kind: snow ? "snow" : "rain", drops: Math.round(snow ? 30 + 270 * s : 20 + 380 * s),
            gloom: Math.round((0.08 + 0.3 * s) * 1000) / 1000,
            speed: Math.round((snow ? 0.12 + 0.12 * s : 1 + 1.2 * s) * 1000) / 1000};
  }
  // A streak is as long as its drop falls in RAIN_BLUR seconds, and leans
  // RAIN_SLANT across for each pixel down, as its drop drifts on the wind -
  // or as far as the storm replay's band leans it (streetstorms.py).
  var RAIN_BLUR = 0.03, RAIN_SLANT = 0.12, RAIN_STILL = null;
  // Whether the reader asks for less motion, asked of the browser once.
  function rainStill() {
    if (RAIN_STILL === null) {
      RAIN_STILL = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : false;
    }
    return !!(RAIN_STILL && RAIN_STILL.matches);
  }
  // What is drawn over the panorama: the El Nino replay's rain for its day,
  // or the storm replay's wind for its hour (streetstorms.py); the two
  // panels are never open together.
  function rainNow() { return (S.sim && S.sim.rain) || (S.tc && S.tc.rain) || null; }
  // Whether drops fall, to be drawn frame by frame.
  function rainOn() {
    var rain = rainNow();
    return !!rain && rain.drops > 0 && !rainStill();
  }
  // The rain for the day the replay shows, and the badge naming it (when, in
  // the slider's words), while the replay shows a day of a street found; the
  // frames run while it rains, unless the reader asks for less motion.
  function rainDay(when) {
    var sim = S.sim, run = simChosen(), st = S.street, on = !!run && !!st && !st.finding;
    rainSet(sim, on ? rainLevel(run.p[sim.day], run.t[sim.day]) : null, when);
    simFrame();
  }
  // What a replay (holder: S.sim, or S.tc for the storm replay) draws over
  // the panorama at a level, and the badge naming its moment (when). With
  // no level both are hidden and the canvas let go, unless the other replay
  // draws. The canvas is shown only while drops fall: one cleared and drawn
  // on no more can go on showing what it drew last (Chrome, 12 October
  // 2026). The drops are kept while their kind is, as many as the level
  // asks, and drawn at once; the holder asks for its frames.
  function rainSet(holder, level, when) {
    var canvas = $("street-rain"), badge = $("street-day");
    if (holder && !level) holder.rain = null;
    if (!level) {
      if (rainNow()) return;
      setHidden(canvas, true);
      setHidden(badge, true);
      if (canvas.width) { canvas.width = 0; canvas.height = 0; }
      return;
    }
    setHidden(canvas, !level.drops);
    setHidden(badge, false);
    setText(badge, when);
    var key = when + "|" + level.kind + "|" + level.drops, was = holder.rain;
    if (was && was.key === key) return;
    var drops = was && was.kind === level.kind ? was.parts : [];
    while (drops.length > level.drops) drops.pop();
    while (drops.length < level.drops) {
      drops.push({x: Math.random(), y: Math.random(), z: 0.4 + 0.6 * Math.random(), w: Math.random() * 2 * Math.PI});
    }
    holder.rain = {key: key, kind: level.kind, drops: level.drops, gloom: level.gloom, speed: level.speed,
                   slant: level.slant || RAIN_SLANT, gusts: !!level.gusts, parts: drops, last: was ? was.last : 0};
    if (level.drops) rainPaint(0);
  }
  // The canvas sized to its box at the device's pixel ratio, two at most.
  function rainSize(canvas) {
    var r = canvas.getBoundingClientRect(), dpr = Math.min(2, window.devicePixelRatio || 1);
    var w = Math.max(1, Math.round(r.width)), h = Math.max(1, Math.round(r.height));
    if (canvas.width !== Math.round(w * dpr)) canvas.width = Math.round(w * dpr);
    if (canvas.height !== Math.round(h * dpr)) canvas.height = Math.round(h * dpr);
    return {w: w, h: h, dpr: dpr};
  }
  // A frame of the rain at time ts, or the rain as it is (no ts), its clock
  // left where it was: the drops moved on by the time since the last frame,
  // the sky dimmed, and each drop drawn at one of three depths, the nearer
  // faster, bigger and brighter - rain as streaks leaning with the wind, as
  // long as they are fast, a storm's gusting at hurricane force; snow as
  // flakes swaying as they fall - a path a depth.
  function rainPaint(ts) {
    var rain = rainNow(), canvas = $("street-rain");
    var ctx = rain && canvas.getContext ? canvas.getContext("2d") : null;
    if (!ctx) return false;
    var box = rainSize(canvas), w = box.w, h = box.h, snow = rain.kind === "snow", sway = (ts || rain.last) / 1000;
    var dt = ts && rain.last ? Math.min(ts - rain.last, SIM_HELD) / 1000 : 0, depths = [[], [], []];
    var gust = rain.gusts ? rainGust(sway) : 1, slant = rain.slant * Math.sqrt(gust);
    if (ts) rain.last = ts;
    ctx.setTransform(box.dpr, 0, 0, box.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!rain.parts.length) return true;
    ctx.fillStyle = "rgba(14, 22, 33, " + rain.gloom + ")";
    ctx.fillRect(0, 0, w, h);
    rain.parts.forEach(function (d) {
      var v = rain.speed * d.z * gust;
      d.y += v * dt;
      if (!snow) d.x += slant * v * dt * h / w;
      if (d.y > 1.08) { d.y -= 1.16; d.x = Math.random(); }
      d.x -= Math.floor(d.x);
      depths[d.z < 0.6 ? 0 : d.z < 0.8 ? 1 : 2].push(d);
    });
    depths.forEach(function (list, k) {
      if (!list.length) return;
      ctx.beginPath();
      list.forEach(function (d) {
        var x = d.x * w, y = d.y * h;
        if (snow) {
          var r = 0.8 + 1.6 * d.z;
          x += Math.sin(d.w + sway * (0.6 + d.z)) * 10 * d.z;
          ctx.moveTo(x + r, y);
          ctx.arc(x, y, r, 0, 2 * Math.PI);
        } else {
          var len = rain.speed * gust * d.z * h * RAIN_BLUR;
          ctx.moveTo(x, y);
          ctx.lineTo(x - slant * len, y - len);
        }
      });
      if (snow) {
        ctx.fillStyle = "rgba(255, 255, 255, " + (0.5 + 0.2 * k) + ")";
        ctx.fill();
      } else {
        ctx.strokeStyle = "rgba(214, 226, 240, " + (0.28 + 0.16 * k) + ")";
        ctx.lineWidth = 0.8 + 0.4 * k;
        ctx.stroke();
      }
    });
    return true;
  }
  // A storm's gusts at hurricane force: its wind's strength, 1 to 1.6,
  // rising and falling on two slow beats a few seconds long.
  function rainGust(s) { return 1 + 0.3 * Math.max(0, Math.sin(s * 1.7) + Math.sin(s * 0.63 + 1.3)); }
  $("street-exit").addEventListener("click", function () { streetLeave(); });
  $("street-next").addEventListener("click", function () { streetNext(); });
  $("street-find").addEventListener("click", function () { streetFind(); });
  $("street-then").addEventListener("click", function () { streetThen(); });
  $("street-copy").addEventListener("click", function () { streetCopy(); });
  $("street-more").addEventListener("click", function () { streetMore(); });
  $("street-mini-in").addEventListener("click", function () { miniZoom(1); });
  $("street-mini-out").addEventListener("click", function () { miniZoom(-1); });
  // A tap on the minimap moves the street there, as on Google's: a pick.
  $("street-mini").addEventListener("click", function (e) {
    if (!S.street || (e.target && e.target.closest && e.target.closest("button"))) return;
    var r = $("street-mini").getBoundingClientRect(), p = miniPoint(e.clientX - r.left, e.clientY - r.top);
    streetPick(p.lon, p.lat, S.street.mini);
  });
  // A wheel over the stage is the stage's (the chip scrolls), not the map's.
  $("street-stage").addEventListener("wheel", function (e) { e.stopPropagation(); }, {passive: true});
  if (window.ResizeObserver) new ResizeObserver(function () { if (S.street) miniDraw(); }).observe($("street-mini"));
  // The replay's controls, and its chart's pointers (simPointers).
  $("street-replay").addEventListener("click", function () { simOpen(); });
  $("street-sim-back").addEventListener("click", function () { simClose(); });
  $("street-sim-retry").addEventListener("click", function () { simRetry(); });
  $("street-sim-play").addEventListener("click", function () { if (S.sim) simPlay(!S.sim.playing); });
  $("street-sim-event").addEventListener("change", function (e) { simPick(e.target.value); });
  $("street-sim-start").addEventListener("change", function (e) { simStart(+e.target.value); });
  $("street-sim-speed").addEventListener("change", function (e) {
    var v = +e.target.value;
    if (S.sim && SIM_SPEEDS.indexOf(v) >= 0) S.sim.speed = v;
  });
  $("street-sim-day").addEventListener("input", function (e) { simSeekDay(+e.target.value); });
  simPointers($("street-sim-chart"), function () { return S.sim; }, simSeek, simSeekFrom);
  if (window.ResizeObserver) new ResizeObserver(function () {
    var sim = S.sim;
    if (sim && sim.geo && Math.round($("street-sim-chart").getBoundingClientRect().width) !== sim.geo.width) {
      simChartDraw();
      simHead();
    }
  }).observe($("street-sim-chart"));
  // The rain drawn again at the canvas's new size.
  if (window.ResizeObserver) new ResizeObserver(function () { if (rainNow()) rainPaint(0); })
    .observe($("street-rain"));
  // Esc closes the replay or the storm panel, and leaves the street when
  // neither is open, unless then-and-now's keys took it first (to stop the
  // map waiting for a tap); keys typed into a field are its own, but for the
  // panels' own controls.
  document.addEventListener("keydown", function (e) {
    var t = e.target, tag = t && t.tagName;
    function inPart(sel) { return !!(t && t.closest && t.closest(sel)); }
    var mine = !!S.sim && inPart("#street-sim") || !!S.tc && inPart("#street-tc");
    if (e.defaultPrevented || e.key !== "Escape" || !S.street) return;
    if (!mine && (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || inPart("#findform"))) return;
    e.preventDefault();
    if (S.sim) simClose(); else if (S.tc) tcClose(); else streetLeave();
  });

  // ---- hurricanes on the street: the live storms near the stage's point, and the storms that
  // passed it since 1950 (streetstorms.py) ----
  // The panel, open in the chip's place, as S.tc: the history's radius in
  // nautical miles and the replay's speed in hours a second; the storm
  // replayed (key) and its run, the hour shown (k) and Play's place between
  // hours (pos), whether it plays, the frame asked for and the time of the
  // last; whether a pointer seeks on the chart and a finger down on it not
  // yet seeking (touch), and the chart's geometry as last drawn; the wind
  // drawn over the panorama (rain); the replay's choices at the point and
  // whether the tracks were read when they were made (tracks); the storms
  // since 1950 worked out for the point (past); and the tracks' load, under
  // way (loading) or failed (why), or the run having sent none (none).
  S.tc = null;
  // The storms on the chip's line, at most.
  var TC_LINE = 2;
  // The forecast's winds the line names after the first, by threshold.
  var TC_FORCE = {"50": "50 kt", "64": "hurricane-force"};
  // A past storm counts at a point at the tropical-storm threshold, the one
  // the tracks are kept at (streetstorms.STORM_KT).
  var TC_KT = 34;
  var TC_READING = "Reading the storm tracks\u2026";
  // HURDAT2's statuses, and the phases in the history's order, in words.
  // ET is the eastern Pacific file's, on two of its fixes.
  var TC_STATUS = {HU: "hurricane", TS: "tropical storm", TD: "tropical depression", EX: "extratropical",
                   ET: "extratropical", SS: "subtropical storm", SD: "subtropical depression", LO: "low",
                   WV: "tropical wave", DB: "disturbance"};
  var TC_PHASES = {warm: "El Ni\u00f1o", cool: "La Ni\u00f1a", neutral: "neutral"};
  // HURDAT2's basins, a file each, in words.
  var TC_BASINS = {AL: "the North Atlantic\u2019s", EP: "the eastern and central North Pacific\u2019s"};
  // The tracks' load once asked for, let go if it fails; the tracks once
  // read, and the file each basin's came from (streetstorms.tracks_payload).
  var TC_TRACKS = null, TC_DECODED = null, TC_FILES = null;
  // The storms as the warning centres where a point is name them: typhoons in
  // the north-west Pacific (north of the equator, 100E to 180), cyclones in
  // the north Indian Ocean (30E to 100E) and south of the equator, and
  // hurricanes elsewhere.
  function tcWord(lon, lat) {
    var w = wrap(lon);
    if (lat < 0) return "Cyclones";
    if (w >= 100 || w === -180) return "Typhoons";
    return w >= 30 ? "Cyclones" : "Hurricanes";
  }
  // Whether HURDAT2 holds the storms where a point is: where they are
  // hurricanes, the North Atlantic's and the eastern and central North
  // Pacific's. Of the north-west Pacific's it holds only the few that crossed
  // 180 degrees from the east, which must not pass for its record there.
  function tcHeld(lon, lat) { return tcWord(lon, lat) === "Hurricanes"; }
  // Here's live storms near a point (nearHere), nearest first: by how close
  // the official forecast brings each, or, with none, by how close it is now.
  function tcNear(lon, lat) {
    function far(r) {
      var d = r.forecast ? r.closest_km : r.now_km;
      return d == null ? Infinity : d;
    }
    return hereFor(lon, lat).storms.filter(nearHere).sort(function (a, b) { return far(a) - far(b); });
  }
  // The chip's line, in Here's own numbers: for each of the nearest storms,
  // TC_LINE at most, the first of its forecast's winds to come here and the
  // strongest after it, how close it comes, the most severe watch or warning
  // on the coast near and the surge area the point is in.
  function tcThreatHtml(rows) {
    return rows.slice(0, TC_LINE).map(function (r) {
      function when(t) { return utc(Date.parse(t)) + " (" + soon(t) + ")"; }
      var said = [], a = r.arrival, top = a["64"] ? "64" : a["50"] ? "50" : null;
      var going = kms(r.now_km) + " away now, and the official forecast takes it no closer";
      if (!r.forecast) {
        said.push(kms(r.now_km) + " " + COMPASS8[Math.round(r.bearing / 45) % 8] + " of here at " +
                  utc(Date.parse(r.now)) + "; no official forecast this run");
      } else if (a["34"]) {
        said.push("tropical-storm-force wind here from " + when(a["34"]) +
                  (top ? ", " + TC_FORCE[top] + " from " + when(a[top]) : "") + " on the official forecast");
        said.push(r.receding ? going : "closest " + kms(r.closest_km) + " at " + utc(Date.parse(r.closest)));
      } else {
        said.push(r.receding ? going : "closest " + kms(r.closest_km) + " at " + when(r.closest) +
                  " on the official forecast");
        if (r.unknown.indexOf(34) >= 0) said.push("its wind here is not forecast");
        else if (r.gale) said.push("its tropical-storm-force wind does not reach here");
      }
      if (r.watches.length) {
        var w = r.watches[0];
        said.push(Math.round(w.km) ? "nearest coast under a " + esc(w.kind) + " " + kms(w.km) + " away"
                                   : "a " + esc(w.kind) + " on the coast here");
      }
      r.surge.forEach(function (s) {
        said.push("inside the peak storm surge area \u201c" + esc(s.label) + "\u201d: " + esc(s.feet));
      });
      return '<p><span class="swatch" style="background:' + r.hue + '"></span><b>' + esc(r.title) + "</b> (" +
             esc(r.centre) + "): " + said.join("; ") + ".</p>";
    }).join("");
  }
  // The panel's live part: Here's own items for the storms near, or why
  // there are none, in Here's words.
  function tcLiveHtml(near) {
    if (near.length) return '<ul class="herestorms">' + near.map(stormHere).join("") + "</ul>";
    return "<p>" + (STORMS.length ? "No live storm\u2019s official forecast comes within 1,500 km of here."
                                  : "No live tropical cyclones.") + "</p>";
  }
  // The line, the button and the panel as the stage and S.tc have them. The
  // chip's head and sentence give their place to either panel, as does the
  // line, which shows only with a storm near; HURDAT2's credit shows with the
  // panel, and the replay's wind over the panorama goes with it.
  function tcDraw() {
    var st = S.street, on = !!S.tc && !!st, covered = !!st && (on || !!S.sim);
    var line = $("street-tc-line"), near = st ? tcNear(st.lon, st.lat) : [];
    setMarkup(line, tcThreatHtml(near));
    setHidden(line, !near.length || covered);
    setHidden($("street-chip-head"), covered);
    setHidden($("street-chip-said"), covered);
    $("street-stage").classList.toggle("tcon", on);
    setHidden($("street-tc"), !on);
    setHidden($("street-tc-credit"), !on);
    if (!on) rainSet(S.tc, null, "");
    if (!st) return;
    var word = tcWord(st.lon, st.lat) + " here";
    setText($("street-tc-open"), word);
    if (!on) return;
    setText($("street-tc-title"), word);
    setMarkup($("street-tc-live"), tcLiveHtml(near));
    tcReplayDraw(st);
    tcPastDraw(st);
  }
  // The panel opened on the stage's point in the chip's place, the El Nino
  // replay closed first, and the tracks asked for; the focus on the panel.
  function tcOpen() {
    if (!S.street) return false;
    if (S.sim) simClose();
    if (!S.tc) {
      S.tc = {radius: D.tc.radius_nm, speed: D.tc.speed, key: "", k: 0, pos: 0, playing: false, frame: 0, last: 0,
              seeking: false, touch: null, geo: null, rain: null, choices: null, run: null, tracks: false,
              past: null, why: "", loading: false, none: false};
    }
    tcLoad();
    tcDraw();
    var panel = $("street-tc");
    if (panel.focus) panel.focus({preventScroll: true});
    return true;
  }
  // The panel closed: Play stopped, the chip back, and the focus, if it was
  // in the panel, on the button that opens it - unless the stage is being
  // left, which puts it on the map.
  function tcClose(leaving) {
    var tc = S.tc, panel = $("street-tc"), on = document.activeElement;
    if (!tc) return false;
    var inside = !!on && !!panel.contains && panel.contains(on), opener = $("street-tc-open");
    if (tc.frame) cancelAnimationFrame(tc.frame);
    S.tc = null;
    tcDraw();
    if (inside && !leaving && opener.focus) opener.focus({preventScroll: true});
    return true;
  }
  // The stage moved to another point with the panel open: the replay stops
  // where it was, as the El Nino replay does, what was worked out for the
  // last point is let go, and streetDraw writes the panel for the new one -
  // the replay's choices made again and the storms since 1950 counted.
  function tcMoved() {
    if (!S.tc) return;
    tcPlay(false);
    S.tc.choices = null;
    S.tc.past = null;
  }
  // A run taken in place: the line and the panel written from its storms,
  // the replay's choices made again from them and the storms since 1950
  // counted again by its seasons.
  function tcRetake() {
    if (S.tc) { S.tc.choices = null; S.tc.past = null; }
    if (S.street) tcDraw();
  }
  // For the page's API: the panel on the street, null off it.
  function tcView() {
    var st = S.street;
    return st ? {open: !!S.tc, word: tcWord(st.lon, st.lat),
                 near: tcNear(st.lon, st.lat).map(function (r) { return r.id; })} : null;
  }
  // ---- the storms that passed the point since 1950 ----
  // The whole address of an asset the page names to load only when asked (a
  // link of rel "elnino-lazy", elnino/assets.py), null if it names none.
  // Whole, as the browser resolves the link: a script added at "assets/..."
  // would pass for one of the assets the page runs, which the follower
  // compares with a new run's before taking it in place (elnino/live.py).
  function tcLater(name) {
    var links = document.querySelectorAll('link[rel="elnino-lazy"]');
    for (var i = 0; i < links.length; i++) {
      if ((links[i].getAttribute("href") || "").split("/").pop().indexOf(name + ".") === 0) return links[i].href;
    }
    return null;
  }
  // The tracks (ELNINO.tracks), loaded as a classic script the first time
  // they are asked for, so a page opened as a file loads them too, and read
  // once, the asset's copy let go; a load that fails is let go, so the next
  // ask loads them again. A run that sent none fails saying so (none).
  function tcTracks() {
    if (!TC_TRACKS) {
      TC_TRACKS = new Promise(function (done, fail) {
        function had() { return window.ELNINO && window.ELNINO.tracks; }
        var src = tcLater("tracks"), script;
        if (had()) { done(had()); return; }
        if (!src) { fail(Object.assign(streetFailure("this run sent none"), {none: true})); return; }
        script = document.createElement("script");
        script.src = src;
        script.onload = function () {
          if (had()) done(had());
          else fail(streetFailure("the file held no tracks"));
        };
        script.onerror = function () {
          script.remove();
          fail(streetFailure("the file did not load"));
        };
        document.head.appendChild(script);
      }).then(function (raw) {
        TC_FILES = raw.files || null;
        TC_DECODED = tcDecode(raw);
        delete window.ELNINO.tracks;
        return TC_DECODED;
      });
      TC_TRACKS.catch(function () { TC_TRACKS = null; });
    }
    return TC_TRACKS;
  }
  // The tracks as the asset carries them (streetstorms.tracks_payload), each
  // storm's fixes summed back from their rows: its time in milliseconds, its
  // position, the longitude carried on across the date line as the rows
  // carry it, its wind (null unknown), its status and its wind radii as Here
  // keeps a forecast point's; and its season, the year in its id.
  function tcDecode(raw) {
    return raw.storms.map(function (s) {
      var d = s[2], lat = 0, lon = 0;
      var t = Date.UTC(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8), +d.slice(8, 10), +d.slice(10, 12));
      return {id: s[0], name: s[1], year: +s[0].slice(4, 8), fixes: s[3].map(function (r) {
        t += r[0] * 60000;
        lat += r[1];
        lon += r[2];
        return {t: t, lat: lat / 10, lon: lon / 10, wind: r[3], status: raw.statuses[r[4]], radii: tcRadii(r)};
      })};
    });
  }
  // A row's wind radii, nautical miles by quadrant (NE, SE, SW, NW), by
  // threshold: those whose four quadrants it knows, null with none.
  function tcRadii(row) {
    var out = null;
    THRESHOLDS.forEach(function (kt, i) {
      var quads = row.slice(5 + 4 * i, 9 + 4 * i);
      if (quads.length === 4 && quads.every(function (v) { return v != null; })) (out = out || {})[kt] = quads;
    });
    return out;
  }
  // A number rounded as Python rounds it, a half to the even side.
  function tcRound(v) {
    var r = Math.round(v);
    return Math.abs(v % 1) === 0.5 && r % 2 ? r - 1 : r;
  }
  // A track's closest approach to a point: the nearest point of its path,
  // drawn straight from fix to fix, found on a plane about the point as
  // toLine finds a line's, each leg placed about the point by its first fix
  // so that the date line breaks none; its distance great-circle, its time
  // and wind interpolated (unknown where a fix either side does not know it)
  // and its status the nearer fix's, the earlier's at half way.
  function tcClosest(track, lon, lat) {
    var f = track.fixes, kx = 111.32 * Math.cos(rad(lat)), ky = 110.57, best = {d: Infinity};
    for (var i = 0; i < Math.max(f.length - 1, 1); i++) {
      var a = f[i], b = f[i + 1] || a;
      var x = (frameLon(a.lon, lon) - lon) * kx, y = (a.lat - lat) * ky;
      var dx = (b.lon - a.lon) * kx, dy = (b.lat - a.lat) * ky, L = dx * dx + dy * dy;
      var s = L ? clamp(-(x * dx + y * dy) / L, 0, 1) : 0, d = Math.hypot(x + s * dx, y + s * dy);
      if (d < best.d) best = {d: d, a: a, b: b, s: s};
    }
    var p = best.a, q = best.b, at = best.s;
    return {km: km(lon, lat, p.lon + at * (q.lon - p.lon), p.lat + at * (q.lat - p.lat)), t: p.t + at * (q.t - p.t),
            wind: at === 0 ? p.wind : at === 1 ? q.wind :
                  p.wind == null || q.wind == null ? null : p.wind + at * (q.wind - p.wind),
            status: (at <= 0.5 ? p : q).status};
  }
  // A track's strongest wind while it is within radius km of a point: each
  // leg, drawn straight from fix to fix and placed on the plane about the
  // point as tcClosest places it, cut where it crosses the circle. The wind
  // is interpolated along a leg, so it is strongest at one end of the part
  // inside, and known there only where both fixes know theirs, or at a fix
  // itself. Null where no part is inside or no wind there is known.
  function tcWithin(track, lon, lat, radius) {
    var f = track.fixes, kx = 111.32 * Math.cos(rad(lat)), ky = 110.57, top = null;
    function wind(a, b, s) {
      if (s === 0 || s === 1) return s ? b.wind : a.wind;
      return a.wind == null || b.wind == null ? null : a.wind + s * (b.wind - a.wind);
    }
    function keep(w) { if (w != null && (top === null || w > top)) top = w; }
    for (var i = 0; i < Math.max(f.length - 1, 1); i++) {
      var a = f[i], b = f[i + 1] || a, s0 = 0, s1 = 1;
      var x = (frameLon(a.lon, lon) - lon) * kx, y = (a.lat - lat) * ky;
      var dx = (b.lon - a.lon) * kx, dy = (b.lat - a.lat) * ky, A = dx * dx + dy * dy;
      var B = x * dx + y * dy, C = x * x + y * y - radius * radius, disc = B * B - A * C;
      if (A ? disc < 0 : C > 0) continue;
      if (A) {
        s0 = Math.max(0, (-B - Math.sqrt(disc)) / A);
        s1 = Math.min(1, (-B + Math.sqrt(disc)) / A);
        if (s0 > s1) continue;
      }
      keep(wind(a, b, s0));
      keep(wind(a, b, s1));
    }
    return top;
  }
  // A season's phase by the index's ASO value as CPC prints it, null for a
  // year without one.
  function tcPhase(year) {
    var aso = D.tc.aso, v = aso.values[year - aso.from];
    if (v == null) return null;
    return v >= D.tc.warm ? "warm" : v <= D.tc.cool ? "cool" : "neutral";
  }
  // The two-sided exact binomial test of e storms in El Nino's se seasons
  // against l in La Nina's sl: were the phases alike, each of the e + l
  // storms would fall in an El Nino season with chance se / (se + sl); the
  // chances of the splits no likelier than this one, summed, with R's
  // allowance for rounding (binom.test). Null with no storm, or no season of
  // a phase, to split them by.
  function tcBinomial(e, l, se, sl) {
    var n = e + l, logs = [];
    if (!n || !se || !sl) return null;
    var p = se / (se + sl), up = Math.log(p) - Math.log(1 - p);
    for (var k = 0, at = n * Math.log(1 - p); k <= n; k++) {
      logs.push(at);
      if (k < n) at += Math.log((n - k) / (k + 1)) + up;
    }
    var edge = logs[e] + Math.log(1 + 1e-7);
    return Math.min(1, logs.reduce(function (sum, v) { return v <= edge ? sum + Math.exp(v) : sum; }, 0));
  }
  // The storms since 1950 that passed a point within radius km with TC_KT
  // or more while within it, whatever their status, newest first, each with
  // its closest approach, its strongest wind within (top) and its season's
  // phase; how many passed in each phase's seasons and how many seasons each
  // phase had from the first year to the record's
  // last; the test of El Nino's count against La Nina's; and whether the
  // point is in the record's basins (held) and any of its storms came within
  // near_km of it (covered), without both of which nothing is counted there.
  function tcPast(tracks, lon, lat, radius) {
    var T = D.tc, rows = [], counts = {}, held = tcHeld(lon, lat), near = false, last = T.first;
    Object.keys(TC_PHASES).forEach(function (phase) { counts[phase] = {storms: 0, seasons: 0}; });
    tracks.forEach(function (track) {
      last = Math.max(last, track.year);
      if (!held) return;
      var c = tcClosest(track, lon, lat);
      if (c.km <= T.near_km) near = true;
      if (c.km > radius) return;
      // The closest point is within the distance, measured great-circle,
      // though on the plane it may lie just outside the circle.
      var top = tcWithin(track, lon, lat, radius);
      if (c.wind != null && (top === null || c.wind > top)) top = c.wind;
      if (top === null || top < TC_KT) return;
      var phase = tcPhase(track.year);
      rows.push({id: track.id, name: track.name, year: track.year, km: c.km, t: c.t, wind: c.wind, top: top,
                 status: c.status, phase: phase});
      if (phase) counts[phase].storms++;
    });
    for (var year = T.first; year <= last; year++) {
      var seen = tcPhase(year);
      if (seen) counts[seen].seasons++;
    }
    rows.sort(function (a, b) { return b.t - a.t; });
    return {rows: rows, counts: counts, covered: held && near, held: held, radius_km: radius, last: last,
            p: tcBinomial(counts.warm.storms, counts.cool.storms, counts.warm.seasons, counts.cool.seasons)};
  }
  // The basins whose tracks the run could not read, in words; "" with every
  // basin read, or before the tracks are.
  function tcMissing() {
    return tcList(Object.keys(TC_BASINS).filter(function (b) { return !!TC_FILES && !TC_FILES[b]; })
                  .map(function (b) { return TC_BASINS[b]; }));
  }
  function tcStorms(n) { return n + (n === 1 ? " storm" : " storms"); }
  function tcSeasons(n, phase) { return n + " " + TC_PHASES[phase] + (n === 1 ? " season" : " seasons"); }
  // How often chance alone splits the storms as unevenly as they fell.
  function tcChance(p) {
    if (p >= 1 - 1e-9) return "the split chance alone makes most often";
    var pc = tcRound(100 * p);
    return "chance alone splits them this unevenly " + (pc < 1 ? "less than 1%" : pc > 99 ? "more than 99%" : pc + "%") +
           " of the time";
  }
  // One of the history's tables, from its head and its rows.
  function tcTable(head, rows) {
    return '<table class="streettable"><thead><tr>' + head.map(function (h) {
      return '<th scope="col">' + h + "</th>";
    }).join("") + "</tr></thead><tbody>" + rows.join("") + "</tbody></table>";
  }
  // The storms since 1950 in words, with a table of the phases: how many
  // passed within the distance chosen with TC_KT or more, how many in each
  // phase's seasons and a season's worth, and how often chance alone splits
  // El Nino's from La Nina's as unevenly; or that the record does not cover
  // the point, or reach it - first, in its basins, any basin whose tracks the
  // run could not read, whose storms the count leaves out.
  function tcPastHtml(past) {
    var T = D.tc, c = past.counts, n = past.rows.length, phased = 0, seasons = 0, gone = tcMissing();
    if (!past.held) {
      return "<p>HURDAT2 does not cover here. It holds the North Atlantic\u2019s storms and the eastern and central " +
             "North Pacific\u2019s, east of 180\u00b0; of the north-west Pacific\u2019s it holds only the few that " +
             "crossed 180\u00b0 from the east, and none of the north Indian Ocean\u2019s or the southern " +
             "hemisphere\u2019s.</p>";
    }
    var note = gone ? "<p>This run could not read " + gone + " tracks: those storms are not counted.</p>" : "";
    if (!past.covered) {
      return note + (gone ? "<p>None of the storms this run has passed within " + kms(T.near_km) + ".</p>"
                          : "<p>HURDAT2 does not reach here: none of its storms passed within " + kms(T.near_km) +
                            ".</p>");
    }
    var said = " passed within " + tcRound(past.radius_km / NM) + " n mi (" + kms(past.radius_km) + ") of here at " +
               TC_KT + " kt or more in the " + (past.last - T.first + 1) + " seasons from " + T.first + " to " +
               past.last + ".</p>";
    if (!n) return note + "<p>No storm" + said;
    Object.keys(TC_PHASES).forEach(function (phase) {
      phased += c[phase].storms;
      seasons += c[phase].seasons;
    });
    var out = note + "<p><b>" + tcStorms(n) + "</b>" + said;
    if (!seasons) return out + "<p>This run has no ASO value for any season, so the storms are not counted by phase.</p>";
    out += tcTable(["Phase", "Seasons", "Storms", "A season"], Object.keys(TC_PHASES).map(function (phase) {
      var k = c[phase], name = TC_PHASES[phase];
      return '<tr><th scope="row">' + name.charAt(0).toUpperCase() + name.slice(1) + "</th><td>" + k.seasons +
             "</td><td>" + k.storms + "</td><td>" + (k.seasons ? (k.storms / k.seasons).toFixed(2) : "") + "</td></tr>";
    }));
    if (n > phased) {
      out += "<p>" + (n - phased) + " of them came in " + (n - phased === 1 ? "a season" : "seasons") +
             " with no ASO value, so in no phase.</p>";
    }
    if (past.p != null) {
      return out + "<p>" + tcStorms(c.warm.storms) + " in " + tcSeasons(c.warm.seasons, "warm") + " against " +
             c.cool.storms + " in " + tcSeasons(c.cool.seasons, "cool") + ": " + tcChance(past.p) + ".</p>";
    }
    if (!c.warm.storms && !c.cool.storms) {
      return out + "<p>None of them came in an El Ni\u00f1o or a La Ni\u00f1a season, so the two are not set " +
             "against each other.</p>";
    }
    return out + "<p>With no " + TC_PHASES[c.warm.seasons ? "cool" : "warm"] + " season in the run, the two are " +
           "not set against each other.</p>";
  }
  // The storms since 1950 storm by storm, newest first: the season and its
  // phase, the storm, how near and when it passed, to the hour, its wind, to
  // the knot, and status there, and its strongest wind within the distance
  // where that was more, or its wind there is not known.
  function tcPastTable(past) {
    var nm = tcRound(past.radius_km / NM);
    return tcTable(["Season", "Storm", "Closest", "Wind", "Status"], past.rows.map(function (r) {
      var wind = r.wind == null ? "not known" : tcRound(r.wind) + " kt";
      if (r.wind == null || tcRound(r.top) > tcRound(r.wind)) {
        wind += " (" + tcRound(r.top) + " kt within " + nm + " n mi)";
      }
      return "<tr><td>" + r.year + (r.phase ? ", " + TC_PHASES[r.phase] : "") + "</td><td>" + esc(tcName(r.name)) +
             "</td><td>" + kms(r.km) + ", " + utc(Math.round(r.t / HOUR) * HOUR) + "</td><td>" + wind + "</td><td>" +
             esc(TC_STATUS[r.status] || r.status) + "</td></tr>";
    }));
  }
  // A HURDAT2 name as the page writes it: SANDY as Sandy, ONE-E as One-E.
  function tcName(name) {
    return name.toLowerCase().replace(/(^|[\s-])([a-z])/g, function (all, before, first) {
      return before + first.toUpperCase();
    });
  }
  // How the storms since 1950 are known, naming the run's index.
  function tcMethod() {
    var T = D.tc;
    return "<p>The storms since " + T.first + " are HURDAT2\u2019s, the National Hurricane Center\u2019s best tracks " +
      "of the North Atlantic and the eastern and central North Pacific: every storm from " + T.first + " that " +
      "reached " + TC_KT + " kt, a fix every six hours. A storm counts here when its track, drawn straight from fix " +
      "to fix, passes within the distance chosen and its wind, interpolated between the fixes, is " + TC_KT + " kt " +
      "or more somewhere within it, whatever its status: Sandy was post-tropical when it reached New Jersey. Storm " +
      "by storm, each is listed at its closest approach, with its wind and status there, and the strongest wind it " +
      "had within the distance where that was more. The closest approach and the part of the track within the " +
      "distance are found on a plane about this point, the closest approach\u2019s distance measured great-circle; " +
      "the status there is the nearer fix\u2019s.</p>" +
      "<p>A season\u2019s phase is " + esc(T.index) + "\u2019s August\u2013October value as CPC prints it, as the " +
      "season panel takes it: El Ni\u00f1o at " + signedText(T.warm, 1) + " or more, La Ni\u00f1a at " +
      signedText(T.cool, 1) + " or less, neutral between. Were El Ni\u00f1o\u2019s seasons and La Ni\u00f1a\u2019s " +
      "alike here, each of their storms would fall in an El Ni\u00f1o season with the chance of El Ni\u00f1o\u2019s " +
      "share of their seasons; the exact two-sided binomial test says how often chance alone splits them at least " +
      "as unevenly. It counts storms, not how strong they were, and takes each as falling independently of the " +
      "others, but storms come in clusters within a season, so chance alone splits them this unevenly more often " +
      "than it says.</p>" +
      "<p>A point south of the equator, or north of it between 30\u00b0E and 180\u00b0, is outside HURDAT2\u2019s " +
      "basins, whatever storms crossed into it, and one in them that none of its storms passed within " +
      kms(T.near_km) + " of is beyond their reach: neither is counted. Before the " +
      "satellite era, about 1966 in the Atlantic and 1971 in the eastern Pacific, a storm that stayed far from " +
      "land could go unrecorded, and every position and wind in the record is an analysis with its own " +
      "uncertainty. This is worked out here; it is not an official product.</p>" +
      "<p>HURDAT2: Landsea, C. W., and J. L. Franklin, 2013: Atlantic hurricane database uncertainty and " +
      "presentation of a new database format. Monthly Weather Review, 141, 3576\u20133592.</p>" +
      '<p class="links"><a href="https://www.nhc.noaa.gov/data/#hurdat" target="_blank" rel="noopener">HURDAT2 ' +
      "\u2197</a></p>";
  }
  // The tracks asked for while the panel is open: read once, the history
  // drawn when they are, why not and a Retry if they cannot be - or, for a
  // run that sent none, which a Retry cannot bring, that it has none.
  function tcLoad() {
    var tc = S.tc;
    if (!tc || TC_DECODED || tc.loading || tc.none) return;
    tc.loading = true;
    tc.why = "";
    tcTracks().then(function () {
      tc.loading = false;
      if (S.tc === tc) tcDraw();
    }, function (err) {
      tc.loading = false;
      tc.none = !!(err && err.none);
      tc.why = tc.none ? "" : err && err.why || "the file could not be read";
      if (S.tc === tc) tcDraw();
    });
  }
  function tcRetry() {
    if (!S.tc) return;
    tcLoad();
    tcDraw();
  }
  // Another distance chosen: the storms since 1950 counted again, and the
  // past storms the replay offers chosen again.
  function tcRadius(nm) {
    if (!S.tc) return;
    S.tc.radius = nm;
    S.tc.choices = null;
    S.tc.past = null;
    tcDraw();
  }
  // The history in the open panel: the storms since 1950 at the stage's
  // point, counted once the tracks are read and again for a new point,
  // distance or run, or "Reading the storm tracks..." until they are, or why
  // they cannot be with a Retry, or that the run sent none; storm by storm;
  // and how it is known.
  function tcPastDraw(st) {
    var tc = S.tc, pick = $("street-tc-radius");
    if (!tc.past && TC_DECODED) tc.past = tcPast(TC_DECODED, st.lon, st.lat, tc.radius * NM);
    var past = tc.past, listed = !!past && past.rows.length > 0;
    if (pick.value !== String(tc.radius)) pick.value = String(tc.radius);
    setMarkup($("street-tc-past"), past ? tcPastHtml(past)
                                        : tc.none ? "<p>This run has no storm tracks: HURDAT2 could not be read when " +
                                                    "it was made.</p>"
                                        : tc.why ? "" : '<p class="streetwait">' + TC_READING + "</p>");
    setHidden($("street-tc-fail"), !tc.why);
    setText($("street-tc-why"), tc.why ? "The storm tracks could not be read (" + tc.why + ")." : "");
    setHidden($("street-tc-each"), !listed);
    setMarkup($("street-tc-table"), listed ? tcPastTable(past) : "");
    setMarkup($("street-tc-method"), tcMethod());
  }
  // ---- the replay: a storm's wind over the street, hour by hour ----
  // A run is a live storm's official forecast - Here's own path, from the
  // analysis on - or a past storm's best track made hourly; at each of its
  // hours (at) where the centre is from the point (km, and toward it), the
  // point's band and where the wind there comes from; its strongest band
  // (top) and the hour it comes nearest (near). The hours a past storm is
  // replayed either side of those that bring it near (TC_EDGE); the table's
  // step and the chart's ticks, in hours of UTC; how far, km, a closest
  // approach found leg by leg may miss the hourly track's (TC_SLACK); and
  // what is drawn over the panorama at each band: streaks, the sky's gloom,
  // their speed in views a second and their lean, gusting at hurricane force.
  var TC_EDGE = 6, TC_EVERY = 3, TC_TICK = 12, TC_SLACK = 50;
  var TC_LEVELS = {"34": {drops: 160, gloom: 0.22, speed: 2, slant: 0.45},
                   "50": {drops: 260, gloom: 0.3, speed: 2.6, slant: 0.75},
                   "64": {drops: 380, gloom: 0.38, speed: 3.2, slant: 1.1, gusts: true}};
  // A track made hourly by the exposure table's rules (exposure._blend):
  // each whole hour of UTC from its first fix to its last, a fix's own hour
  // the fix itself and any other between the fixes either side, so that a
  // landfall off the hour shapes the hours either side of it.
  function tcHourly(fixes) {
    var out = [], n = fixes.length, i = 0;
    if (!n) return out;
    for (var t = Math.ceil(fixes[0].t / HOUR) * HOUR; t <= fixes[n - 1].t; t += HOUR) {
      while (i < n - 1 && fixes[i + 1].t <= t) i++;
      var a = fixes[i];
      out.push(a.t === t ? a : tcBlend(a, fixes[i + 1], (t - a.t) / (fixes[i + 1].t - a.t), t));
    }
    return out;
  }
  // A fix's radii at a threshold: as given, zero where its wind is under it,
  // else unknown (exposure._known).
  function tcKnown(fix, kt) {
    var q = fix.radii && fix.radii[kt];
    return q ? q : fix.wind != null && fix.wind < +kt ? [0, 0, 0, 0] : null;
  }
  // The fix a fraction f of the way from a to b, at time t: the centre and
  // the wind interpolated, the wind unknown where either end's is; each
  // threshold's radii where both ends know them, rounded as Python rounds and
  // left out where they come to nothing; the status the first fix's.
  function tcBlend(a, b, f, t) {
    var radii = null;
    THRESHOLDS.forEach(function (kt) {
      var qa = tcKnown(a, kt), qb = tcKnown(b, kt);
      if (!qa || !qb) return;
      var q = qa.map(function (x, j) { return tcRound(x + (qb[j] - x) * f); });
      if (q.some(function (v) { return v !== 0; })) (radii = radii || {})[kt] = q;
    });
    return {t: t, lat: a.lat + (b.lat - a.lat) * f, lon: a.lon + (b.lon - a.lon) * f,
            wind: a.wind == null || b.wind == null ? null : tcRound(a.wind + (b.wind - a.wind) * f),
            status: a.status, radii: radii};
  }
  // The point's band at an hour: whether it is inside each threshold's wind
  // (insideAt; null where no radius says), the strongest it is inside (0 for
  // none) and the next up where that is not known there.
  function tcBand(p, lon, lat) {
    var inside = {}, kt = 0;
    THRESHOLDS.forEach(function (t) {
      inside[t] = insideAt(p, lon, lat, t);
      if (inside[t]) kt = +t;
    });
    var next = THRESHOLDS[THRESHOLDS.indexOf(String(kt)) + 1];
    return {kt: kt, unknown: next && inside[next] === null ? +next : null, inside: inside};
  }
  // Where the wind at the point comes from at an hour, degrees: round the
  // centre, anticlockwise north of the equator and clockwise south of it,
  // turned in towards it by the inflow angle; null within centre_km of the
  // centre, where it cannot be said. Worked out here, not forecast.
  function tcFrom(p, lon, lat) {
    if (km(p.lon, p.lat, lon, lat) <= D.tc.centre_km) return null;
    var turn = 90 - D.tc.inflow;
    return (bearing(p.lon, p.lat, lon, lat) + (p.lat < 0 ? -turn : turn) + 360) % 360;
  }
  // What is drawn over the panorama at a band: TC_LEVELS' streaks from 34 kt,
  // and nothing under it or where the wind here is not known.
  function tcLevel(band) {
    var at = TC_LEVELS[band.kt];
    return at ? {kind: "storm", drops: at.drops, gloom: at.gloom, speed: at.speed, slant: at.slant, gusts: !!at.gusts}
              : {kind: "calm", drops: 0, gloom: 0, speed: 0, slant: 0, gusts: false};
  }
  // A run's hours read at the point.
  function tcAlong(run, lon, lat) {
    var best = Infinity;
    run.top = 0;
    run.near = 0;
    run.at = run.hours.map(function (p, k) {
      var d = km(p.lon, p.lat, lon, lat), band = tcBand(p, lon, lat);
      if (d < best) { best = d; run.near = k; }
      run.top = Math.max(run.top, band.kt);
      return {km: d, toward: bearing(lon, lat, p.lon, p.lat), band: band, from: tcFrom(p, lon, lat)};
    });
    return run;
  }
  // A live storm's official forecast as a run at the point, from the
  // analysis on, as Here reads it; null for a storm not in the run or with
  // no forecast this run.
  function tcForecast(id, lon, lat) {
    var st = BYID[id], r = st ? hereFor(lon, lat).storms.filter(function (x) { return x.id === id; })[0] : null;
    if (!r || !r.forecast) return null;
    var s = st.d, hours = s.path.filter(function (p) { return p.hour != null && p.hour >= 0; }).map(function (p) {
      return {t: Date.parse(p.t), lat: p.lat, lon: p.lon, wind: p.wind, radii: p.radii, status: p.stage, hour: p.hour};
    });
    return tcAlong({key: "live:" + id, live: true, id: id, title: s.title, centre: s.centre, advisory: s.advisory,
                    hue: st.hue, official: r.official, hours: hours}, lon, lat);
  }
  // A past storm's best track as a run at the point: made hourly, over the
  // hours its centre is within near_km of the point or its 34-kt wind is over
  // it, TC_EDGE either side within the track; null where neither ever is.
  function tcBest(track, lon, lat) {
    var hours = tcHourly(track.fixes), first = -1, last = -1;
    hours.forEach(function (p, k) {
      if (km(p.lon, p.lat, lon, lat) <= D.tc.near_km || insideAt(p, lon, lat, THRESHOLDS[0])) {
        if (first < 0) first = k;
        last = k;
      }
    });
    if (first < 0) return null;
    return tcAlong({key: "past:" + track.id, live: false, id: track.id, name: track.name, year: track.year,
                    hue: "var(--ink2)", hours: hours.slice(Math.max(0, first - TC_EDGE), last + TC_EDGE + 1)},
                   lon, lat);
  }
  // How far a track's winds ever reached from its centre, km: its largest
  // radius.
  function tcReach(track) {
    var most = 0;
    track.fixes.forEach(function (f) {
      THRESHOLDS.forEach(function (t) {
        var q = f.radii && f.radii[t];
        if (q) most = Math.max(most, q[0], q[1], q[2], q[3]);
      });
    });
    return most * NM;
  }
  // What the replay offers at a point: the live storms near it with an
  // official forecast, nearest first; then, once the tracks are read, the
  // storms since replay_from whose 34-kt wind came here or whose centre
  // passed within the history's distance, newest first - each with its run
  // and its name in the menu.
  function tcChoices(lon, lat) {
    var live = [], past = [], radius = (S.tc ? S.tc.radius : D.tc.radius_nm) * NM;
    tcNear(lon, lat).forEach(function (r) {
      var run = r.forecast ? tcForecast(r.id, lon, lat) : null;
      if (run) live.push({key: run.key, label: tcLabel(run), run: run});
    });
    (TC_DECODED || []).forEach(function (track) {
      if (track.year < D.tc.replay_from) return;
      var c = tcClosest(track, lon, lat);
      if (c.km - TC_SLACK > Math.max(radius, tcReach(track))) return;
      var run = tcBest(track, lon, lat);
      if (run && (run.top >= TC_KT || c.km <= radius)) past.push({key: run.key, label: tcLabel(run), run: run, t: c.t});
    });
    past.sort(function (a, b) { return b.t - a.t; });
    return live.concat(past);
  }
  // A run as the menu names it: the live storm and whose forecast it is, or
  // the past storm and the month and year it came nearest; and the strongest
  // wind it brings here.
  function tcLabel(run) {
    var near = new Date(run.hours[run.near].t);
    var name = run.live ? run.title + ", " + run.centre + " forecast"
                        : tcName(run.name) + ", " + MONTHS[near.getUTCMonth()] + " " + near.getUTCFullYear();
    return name + (run.top ? " (" + run.top + " kt here)" : "");
  }
  // The run first shown: the nearest live storm's forecast, else the past
  // storm that brought the strongest wind here, the newest of those.
  function tcDefault(choices) {
    if (!choices.length) return null;
    return choices[0].run.live ? choices[0]
                               : choices.reduce(function (best, c) { return c.run.top > best.run.top ? c : best; });
  }
  // The menu: the live storms' forecasts, then the storms since replay_from.
  function tcOptions(choices) {
    function group(label, list) {
      return list.length ? '<optgroup label="' + esc(label) + '">' + list.map(function (c) {
        return '<option value="' + esc(c.key) + '">' + esc(c.label) + "</option>";
      }).join("") + "</optgroup>" : "";
    }
    return group("Official forecasts", choices.filter(function (c) { return c.run.live; })) +
           group("Since " + D.tc.replay_from, choices.filter(function (c) { return !c.run.live; }));
  }
  // The hour of a run nearest a time.
  function tcNearest(run, t) { return clamp(Math.round((t - run.hours[0].t) / HOUR), 0, run.hours.length - 1); }
  // The choices made again at the stage's point - for a new point, a run
  // taken in place, the tracks read or another distance: the run shown kept,
  // at the same time, while it is a choice still; else Play stopped and the
  // first choice shown.
  function tcChoose(st) {
    var tc = S.tc, t = tc.run ? tc.run.hours[tc.k].t : null;
    tc.choices = tcChoices(st.lon, st.lat);
    tc.tracks = !!TC_DECODED;
    var pick = tc.choices.filter(function (c) { return c.key === tc.key; })[0];
    if (!pick) {
      tcPlay(false);
      pick = tcDefault(tc.choices);
      t = null;
    }
    tcShow(pick, t);
  }
  // A choice shown at a time, else where it opens: a live storm's forecast at
  // the hour now, a past storm where its wind is first here.
  function tcShow(pick, t) {
    var tc = S.tc, run = pick ? pick.run : null;
    tc.key = pick ? pick.key : "";
    tc.run = run;
    tc.k = !run ? 0 : t !== null ? tcNearest(run, t) : run.live ? tcNearest(run, Date.now()) : tcOpening(run);
    tc.pos = tc.k;
  }
  // The hour a past storm opens at: its first with 34-kt wind here, not an
  // empty street hours before it, else, its gales never here, its closest.
  function tcOpening(run) {
    for (var k = 0; k < run.at.length; k++) if (run.at[k].band.kt) return k;
    return run.near;
  }
  // Another run chosen in the menu, shown where it opens.
  function tcPick(key) {
    var tc = S.tc, pick = tc && tc.choices ? tc.choices.filter(function (c) { return c.key === key; })[0] : null;
    if (!pick) return false;
    tcPlay(false);
    tcShow(pick, null);
    tcDraw();
    return true;
  }
  // Whether there is a run to play, on a street found.
  function tcReady() { return !!S.tc && !!S.tc.run && !!S.street && !S.street.finding; }
  // Play or pause, from the hour shown, or from the first when the last is
  // shown.
  function tcPlay(on) {
    var tc = S.tc;
    if (!tc) return false;
    on = !!on && tcReady();
    if (on && !tc.playing) {
      if (tc.k >= tc.run.hours.length - 1) tcHour(0);
      tc.pos = tc.k;
    }
    tc.playing = on;
    tc.last = 0;
    setText($("street-tc-play"), on ? "Pause" : "Play");
    tcFrame();
    return on;
  }
  // A frame asked for while the replay plays or its wind is drawn moving,
  // and none while neither is.
  function tcFrame() {
    var tc = S.tc;
    if (!tc) return;
    var want = tc.playing || rainOn();
    if (want && !tc.frame) tc.frame = requestAnimationFrame(tcTick);
    else if (!want && tc.frame) { cancelAnimationFrame(tc.frame); tc.frame = 0; }
  }
  // A frame: Play's hours moved on by the time since the last at the speed
  // chosen - a frame held back counting SIM_HELD at most - to the run's end,
  // where Play stops; and the wind, while it is drawn, drawn.
  function tcTick(ts) {
    var tc = S.tc;
    if (!tc) return;
    tc.frame = 0;
    if (tc.playing) {
      var end = tc.run ? tc.run.hours.length - 1 : 0;
      if (tc.last) tc.pos = Math.min(end, tc.pos + Math.min(ts - tc.last, SIM_HELD) / 1000 * tc.speed);
      tc.last = ts;
      if (Math.floor(tc.pos) !== tc.k) tcHour(tc.pos);
      if (!tc.run || tc.pos >= end) tcPlay(false);
    }
    if (rainOn()) rainPaint(ts);
    tcFrame();
  }
  // The hour shown: the slider, the readout, the playhead, and the wind over
  // the panorama with the badge naming the hour, while the street is found.
  function tcHour(k) {
    var tc = S.tc, run = tc && tc.run, st = S.street, slider = $("street-tc-hour");
    if (!tc) return;
    if (!run) {
      setText($("street-tc-read"), "");
      slider.removeAttribute("aria-valuetext");
      rainSet(tc, null, "");
      tcFrame();
      return;
    }
    tc.k = clamp(Math.floor(k) || 0, 0, run.hours.length - 1);
    var badge = tcBadge(run, tc.k);
    setValue(slider, String(tc.k));
    if (slider.getAttribute("aria-valuetext") !== badge) slider.setAttribute("aria-valuetext", badge);
    setText($("street-tc-read"), tcRead(run, tc.k));
    tcHead();
    rainSet(tc, st && !st.finding ? tcLevel(run.at[tc.k].band) : null, badge);
    tcFrame();
  }
  // The hour under a pointer on the chart, or a step of the slider.
  function tcSeek(clientX) {
    var tc = S.tc, g = tc && tc.geo;
    if (!g || !tcReady()) return false;
    var r = $("street-tc-chart").getBoundingClientRect(), x = (clientX - r.left) * g.width / (r.width || g.width);
    tcHour(Math.round((x - g.L) / g.W * (g.N - 1)));
    tc.pos = tc.k;
    return true;
  }
  function tcSeekHour(k) {
    if (!tcReady()) return false;
    tcHour(k);
    S.tc.pos = S.tc.k;
    return true;
  }
  // The chart sought from a pointer's event, the chart holding the pointer
  // until it is let go.
  function tcSeekFrom(e) {
    if (!tcSeek(e.clientX)) return false;
    S.tc.seeking = true;
    try { if (e.pointerId !== undefined) e.currentTarget.setPointerCapture(e.pointerId); } catch (err) { /* seeks while over it */ }
    return true;
  }
  // The chart drawn at the width it has, and the playhead on the hour shown.
  function tcChartDraw() {
    var tc = S.tc, box = $("street-tc-chart");
    if (!tc || !tc.run) { setMarkup(box, ""); if (tc) tc.geo = null; return; }
    var c = tcChart(tc.run, Math.round(box.getBoundingClientRect().width) || 320);
    tc.geo = c.geo;
    setMarkup(box, c.svg);
  }
  function tcHead() {
    var tc = S.tc, g = tc && tc.geo, run = tc && tc.run, head = $("street-tc-head"), dot = $("street-tc-dot");
    if (!g || !run || !head || !dot) return;
    var x = Math.round((g.L + tc.k * g.W / Math.max(1, g.N - 1)) * 10) / 10;
    head.setAttribute("x1", x);
    head.setAttribute("x2", x);
    dot.setAttribute("cx", x);
    dot.setAttribute("cy", Math.round((g.T + g.PH * (1 - Math.min(run.at[tc.k].km, g.top) / g.top)) * 10) / 10);
  }
  // The replay in the open panel: its choices made when they are wanted; the
  // menu, Play and the slider, off with nothing to replay or while the
  // street is being found; the words, or why there is nothing to replay; the
  // chart, its key and the hours in a table; and the hour shown.
  function tcReplayDraw(st) {
    var tc = S.tc, pick = $("street-tc-run"), slider = $("street-tc-hour");
    if (!tc.choices || tc.tracks !== !!TC_DECODED) tcChoose(st);
    var run = tc.run;
    setValue($("street-tc-speed"), String(tc.speed));
    setMarkup(pick, tcOptions(tc.choices));
    setValue(pick, tc.key);
    pick.disabled = !tc.choices.length || !!st.finding;
    $("street-tc-play").disabled = !tcReady();
    slider.max = String(run ? run.hours.length - 1 : 0);
    slider.disabled = !tcReady();
    setMarkup($("street-tc-said"), run ? tcWords(run) : "<p>" + tcNothing(st) + "</p>");
    setMarkup($("street-tc-key"), run ? tcKey(run) : "");
    setHidden($("street-tc-every"), !run);
    setMarkup($("street-tc-hours"), run ? tcHours(run) : "");
    tcChartDraw();
    tcHour(tc.k);
  }
  // Why there is nothing to replay: no live storm near with an official
  // forecast, and no storm since replay_from that came near, with any basin
  // whose tracks the run could not read; or none held where the point is; or
  // the tracks not read yet, or not readable, or not sent.
  function tcNothing(st) {
    var T = D.tc, tc = S.tc, since = "the storms since " + T.replay_from, gone = tcMissing();
    var live = tcNear(st.lon, st.lat).length ? "No live storm near here has an official forecast this run"
             : STORMS.length ? "No live storm\u2019s official forecast comes within 1,500 km of here"
             : "No live tropical cyclones";
    if (tc.none) return live + ", and this run has no storm tracks: HURDAT2 could not be read when it was made.";
    if (!TC_DECODED) {
      return live + (tc.why ? ", and the storm tracks, for " + since + ", could not be read."
                            : "; " + since + " come when the storm tracks are read.");
    }
    if (!tcHeld(st.lon, st.lat)) return live + ", and " + since + " come from HURDAT2, which does not cover here.";
    return live + ", and no storm since " + T.replay_from + " passed within " + tc.radius + " n mi (" +
           kms(tc.radius * NM) + ") of here or brought its " + TC_KT + "-kt wind here." +
           (gone ? " This run could not read " + gone + " tracks." : "");
  }
  // Items in words: "50", "50 and 64", "34, 50 and 64".
  function tcList(items) {
    return items.length > 2 ? items.slice(0, -1).join(", ") + " and " + items[items.length - 1] : items.join(" and ");
  }
  function tcStatus(p) { return TC_STATUS[p.status] || p.status; }
  function tcCompass(degrees) { return COMPASS[Math.round(degrees / 22.5) % 16]; }
  // Where the centre is from the point at an hour: how far and which way, or
  // over here within half a kilometre.
  function tcWhere(run, k) {
    var a = run.at[k];
    return Math.round(a.km) ? kms(a.km) + " " + tcCompass(a.toward) : "over here";
  }
  // The centre's wind at an hour, forecast past the analysis.
  function tcWind(run, k) {
    var p = run.hours[k];
    return p.wind == null ? "its wind not known" : (run.live && p.hour > 0 ? "forecast " : "") + p.wind + " kt";
  }
  // Where the wind here comes from at an hour, inside the gales.
  function tcFromWords(a) { return a.band.kt && a.from != null ? ", from the " + tcCompass(a.from) : ""; }
  // The wind here at an hour in words: its band, the next threshold not
  // forecast (not known, for a past storm) where no radius gives it.
  function tcBandWords(b, live) {
    var nk = live ? "not forecast" : "not known", next = THRESHOLDS[THRESHOLDS.indexOf(String(b.kt)) + 1];
    if (!b.kt) return b.unknown ? nk : "under " + next + " kt";
    if (!next) return b.kt + " kt or more";
    return b.unknown ? b.kt + " kt or more (" + next + " kt " + nk + ")" : b.kt + "\u2013" + (next - 1) + " kt";
  }
  // The readout at an hour: the time, where the centre is and its wind (and
  // a past storm's status), the wind here and, inside the gales, where it
  // comes from.
  function tcRead(run, k) {
    var p = run.hours[k], a = run.at[k], b = a.band;
    return utc(p.t) + ": the centre " + tcWhere(run, k) + ", " + tcWind(run, k) + (run.live ? "" : ", " + tcStatus(p)) +
           "; " + (b.kt || !b.unknown ? "here " : "the wind here ") + tcBandWords(b, run.live) + tcFromWords(a) + ".";
  }
  // The badge over the panorama at an hour, the slider's words for it.
  function tcBadge(run, k) {
    var a = run.at[k], b = a.band;
    return utc(run.hours[k].t) + " \u00b7 centre " + tcWhere(run, k) + " \u00b7 " +
           (b.kt || !b.unknown ? "" : "wind ") + tcBandWords(b, run.live) + tcFromWords(a);
  }
  // The replay's words: when each wind comes here and goes, and for how
  // long, hour by hour as the exposure table times it - a wind here at the
  // run's first hour was here already, and one to its end is counted to its
  // last hour; a wind that never comes, part by part where it is known not
  // to reach here and where it is not known, thresholds said alike said
  // together; how near the centre comes, when and at what wind; the warning
  // centre's own chance where its product names the town; and what the
  // replay is not.
  function tcWords(run) {
    var nk = run.live ? "not forecast" : "not known", n = run.hours.length, said = [], alike = null;
    function at(t, k) { return run.at[k].band.inside[t]; }
    function never(t, verb) {
      var parts = [];
      for (var k = 0; k < n;) {
        var state = at(t, k);
        while (k < n && at(t, k) === state) k++;
        parts.push((state === null ? nk : verb + " not reach here") + (k < n ? " until " + utc(run.hours[k].t) : ""));
      }
      return parts.join(", then ");
    }
    function sayAlike() {
      if (alike) said.push(tcList(alike) + " kt " + never(alike[0], alike.length > 1 ? "do" : "does"));
      alike = null;
    }
    THRESHOLDS.forEach(function (t) {
      var spells = [], hours = 0;
      for (var k = 0; k < n; k++) {
        if (!at(t, k)) continue;
        var from = k;
        while (k < n && at(t, k)) k++;
        hours += (k === n ? n - 1 : k) - from;
        spells.push((from ? utc(run.hours[from].t) + (at(t, from - 1) === null ? " (" + nk + " before)" : "")
                          : (run.live ? "the analysis" : "the track\u2019s start") + " (" + utc(run.hours[0].t) + ")") +
                    (k === n ? " to the " + (run.live ? "forecast" : "track") + "\u2019s end"
                             : " until " + utc(run.hours[k].t) + (at(t, k) === null ? " (then " + nk + ")" : "")));
      }
      if (spells.length) {
        sayAlike();
        said.push(t + " kt from " + spells.join(", from ") + ", " + hours + " h" +
                  (spells.length > 1 ? " in all" : ""));
      } else if (alike && never(alike[0], "does") === never(t, "does")) {
        alike.push(t);
      } else {
        sayAlike();
        alike = [t];
      }
    });
    sayAlike();
    var c = run.near, p = run.hours[c], o = run.live && run.official;
    var head = run.live ? esc(run.title) + " on " + esc(run.centre) + "\u2019s official forecast (advisory " +
                          esc(run.advisory) + ")"
                        : esc(tcName(run.name)) + " (" + run.year + ") on HURDAT2\u2019s best track";
    return "<p><b>" + head + "</b>. Wind here: " + said.join("; ") + ". Closest " + kms(run.at[c].km) + " at " +
      utc(p.t) + ", " + tcWind(run, c) + " there" + (run.live ? "" : " (" + esc(tcStatus(p)) + ")") + ".</p>" +
      (o ? "<p>" + esc(run.centre) + "\u2019s own chance at " + esc(o.place.toUpperCase()) +
           (o.hours ? " within " + o.hours + " h" : "") + ": " + THRESHOLDS.map(function (t) {
             var v = o.chances[t];
             return t + " kt " + (v == null ? "not listed" : v === 0 ? "&lt;1%" : v + "%");
           }).join(", ") + ".</p>" : "") +
      (run.live ? "<p>The replay follows the official track and wind radii exactly, hour by hour; the cone and the " +
                  "chances carry the forecast\u2019s uncertainty, and it shows neither.</p>"
                : "<p>The replay follows HURDAT2\u2019s analysed track and wind radii, made hourly; each is an " +
                  "analysis with its own uncertainty.</p>");
  }
  // The run every TC_EVERY hours of UTC: the time, where the centre is and
  // its wind, the wind here and, inside the gales, where it comes from.
  function tcHours(run) {
    var rows = [];
    run.hours.forEach(function (p, k) {
      if (new Date(p.t).getUTCHours() % TC_EVERY) return;
      var a = run.at[k];
      rows.push("<tr><td>" + utc(p.t) + "</td><td>" + tcWhere(run, k) + "</td><td>" +
                (p.wind == null ? "not known" : p.wind + " kt") + "</td><td>" + tcBandWords(a.band, run.live) +
                "</td><td>" + (a.band.kt && a.from != null ? tcCompass(a.from) : "") + "</td></tr>");
    });
    return tcTable(["Time", "Centre from here", "Wind at the centre", "Wind here", "From"], rows);
  }
  // Whether any hour of a run leaves a threshold's wind here not known.
  function tcUnknown(run) {
    return run.at.some(function (a) { return THRESHOLDS.some(function (t) { return a.band.inside[t] === null; }); });
  }
  // Where now falls on a live run, hours from its first; null off it.
  function tcNowAt(run) {
    var at = run.live ? (Date.now() - run.hours[0].t) / HOUR : -1;
    return at >= 0 && at <= run.hours.length - 1 ? at : null;
  }
  // The chart's key: the distance, a filled strip, the hatching where there
  // is any, and now on a forecast.
  function tcKey(run) {
    var hue = ' style="--hue:' + esc(run.hue) + '"';
    return '<span class="dist">the centre\u2019s distance</span><span class="wind"' + hue +
           ">filled: that wind here</span>" + (tcUnknown(run) ? '<span class="unk"' + hue + ">hatched: " +
           (run.live ? "not forecast" : "not known") + "</span>" : "") +
           (tcNowAt(run) !== null ? '<span class="tcnow">now</span>' : "");
  }
  // The chart, w px wide: the centre's distance from the point hour by hour,
  // 0 at the foot; under it a strip a threshold, filled in the storm's hue
  // where that wind is here, deeper for the stronger, and hatched where it
  // is not known; the hours along the foot, ticked every TC_TICK hours of UTC
  // with the day named at 00 UTC where there is room; now on a forecast; and
  // the playhead. Its geometry kept, to place the playhead and to seek; on
  // the left, room for the scale's widest label, "1,000 km" and more.
  function tcChart(run, w) {
    var L = 50, R = 12, T = 8, PH = 72, SH = 10, SG = 3, S0 = T + PH + 10, B = S0 + 3 * SH + 2 * SG, H = B + 18;
    var W = Math.max(40, w - L - R), N = run.hours.length, top = 100, out = [], named = -Infinity, now = tcNowAt(run);
    function r1(v) { return Math.round(v * 10) / 10; }
    function x(k) { return r1(L + clamp(k, 0, N - 1) * W / Math.max(1, N - 1)); }
    function y(v) { return r1(T + PH * (1 - v / top)); }
    run.at.forEach(function (a) { top = Math.max(top, a.km); });
    top = simCeil(top);
    out.push('<svg class="streetsimsvg streettcsvg" viewBox="0 0 ' + w + " " + H + '" width="' + w + '" height="' + H +
             '" role="img" aria-label="' + esc(tcChartSaid(run)) + '">');
    if (tcUnknown(run)) {
      out.push('<defs><pattern id="street-tc-hatch" width="4" height="4" patternUnits="userSpaceOnUse"><path ' +
               'd="M-1,1 l2,-2 M0,4 l4,-4 M3,5 l2,-2" style="stroke:' + esc(run.hue) + '" stroke-width="1.2"/>' +
               "</pattern></defs>");
    }
    [0, top / 2, top].forEach(function (v) {
      out.push('<line class="grid" x1="' + L + '" x2="' + (L + W) + '" y1="' + y(v) + '" y2="' + y(v) + '"/><text x="' +
               (L - 4) + '" y="' + r1(y(v) + 3.5) + '" text-anchor="end">' + v.toLocaleString("en-US") +
               (v === top ? " km" : "") + "</text>");
    });
    THRESHOLDS.forEach(function (t, i) {
      var sy = S0 + i * (SH + SG);
      out.push('<rect class="lane" x="' + L + '" y="' + sy + '" width="' + W + '" height="' + SH + '"/><text x="' +
               (L - 4) + '" y="' + r1(sy + SH / 2 + 3.5) + '" text-anchor="end">' + t + " kt</text>");
      for (var k = 0; k < N;) {
        var state = run.at[k].band.inside[t], from = k;
        while (k < N && run.at[k].band.inside[t] === state) k++;
        if (state === false) continue;
        out.push('<rect class="' + (state ? "b" + t : "unk") + '" x="' + x(from - 0.5) + '" y="' + sy + '" width="' +
                 r1(x(k - 0.5) - x(from - 0.5)) + '" height="' + SH + '" style="fill:' +
                 (state ? esc(run.hue) : "url(#street-tc-hatch)") + '"/>');
      }
    });
    out.push('<path class="dist" d="' + run.at.map(function (a, k) {
      return (k ? "L" : "M") + x(k) + "," + y(a.km);
    }).join("") + '"/>');
    run.hours.forEach(function (p, k) {
      var d = new Date(p.t), tx = x(k);
      if (d.getUTCHours() % TC_TICK) return;
      out.push('<line class="tick" x1="' + tx + '" x2="' + tx + '" y1="' + B + '" y2="' + (B + 4) + '"/>');
      if (d.getUTCHours() || tx - named < 40 || tx > L + W - 28) return;
      named = tx;
      out.push('<text x="' + r1(tx + 2) + '" y="' + (H - 2) + '">' + d.getUTCDate() + " " + MONTHS[d.getUTCMonth()] +
               "</text>");
    });
    if (now !== null) {
      var nx = x(now), end = nx > L + W - 30;
      out.push('<line class="tcnow" x1="' + nx + '" x2="' + nx + '" y1="' + T + '" y2="' + B + '"/>' +
               '<text class="tcnow" x="' + r1(end ? nx - 3 : nx + 3) + '" y="' + (T + PH - 3) + '"' +
               (end ? ' text-anchor="end"' : "") + ">now</text>");
    }
    out.push('<line id="street-tc-head" class="head" x1="' + L + '" x2="' + L + '" y1="' + T + '" y2="' + B +
             '"/><circle id="street-tc-dot" class="dot" r="3.5" cx="' + L + '" cy="' + y(0) + '"/></svg>');
    return {svg: out.join(""), geo: {L: L, W: W, N: N, T: T, PH: PH, top: top, width: w}};
  }
  // What the chart shows, in words, for a reader who cannot see it.
  function tcChartSaid(run) {
    var c = run.near, last = run.hours.length - 1;
    return (run.live ? run.title : tcName(run.name)) + "\u2019s centre from here and its wind here, hour by hour " +
           "from " + utc(run.hours[0].t) + " to " + utc(run.hours[last].t) + ": closest " + kms(run.at[c].km) +
           " at " + utc(run.hours[c].t) + "; " + (run.top ? "at its strongest here, " +
           tcBandWords({kt: run.top, unknown: null}, run.live) : "never " + TC_KT + " kt or more here" +
           (tcUnknown(run) ? " where its wind is known" : "")) + ".";
  }
  $("street-tc-open").addEventListener("click", function () { tcOpen(); });
  $("street-tc-back").addEventListener("click", function () { tcClose(); });
  $("street-tc-radius").addEventListener("change", function () { tcRadius(+$("street-tc-radius").value); });
  $("street-tc-retry").addEventListener("click", function () { tcRetry(); });
  $("street-tc-play").addEventListener("click", function () { if (S.tc) tcPlay(!S.tc.playing); });
  $("street-tc-run").addEventListener("change", function (e) { tcPick(e.target.value); });
  $("street-tc-speed").addEventListener("change", function (e) {
    var v = +e.target.value;
    if (S.tc && D.tc.speeds.indexOf(v) >= 0) S.tc.speed = v;
  });
  $("street-tc-hour").addEventListener("input", function (e) { tcSeekHour(+e.target.value); });
  simPointers($("street-tc-chart"), function () { return S.tc; }, tcSeek, tcSeekFrom);
  if (window.ResizeObserver) new ResizeObserver(function () {
    var tc = S.tc;
    if (tc && tc.geo && Math.round($("street-tc-chart").getBoundingClientRect().width) !== tc.geo.width) {
      tcChartDraw();
      tcHead();
    }
  }).observe($("street-tc-chart"));
  // ---- start ------------------------------------------------------------------
  prepare();
  unserved();
  readToggles();
  measure();
  themeLabel();
  document.querySelectorAll("#panel section.storm").forEach(function (sec) { tab(sec, "now"); });
  if (STORMS.length) select(STORMS[0].id);
  // The page's first layer is the one its toolbar shows pressed: the street
  // map on map.html, GeoColor on storms.html. A place or a view in the
  // address comes before the page's own opening view.
  var firstLayer = document.querySelector('.desktools [data-layer][aria-pressed="true"]');
  if (firstLayer) setLayer(firstLayer.getAttribute("data-layer"));
  if (!applyHash(location.hash)) { if (D.focus === "world") planet(); else fit(true); }
  window.addEventListener("hashchange", function () { applyHash(location.hash); });
  if (S.imagery === "pending" && !Object.keys(DOM).length) ask(source("geocolor", "GOES-East"));
  ages();
  setInterval(ages, 60000);
  // GIBS adds a geostationary frame every ten minutes.
  setInterval(function () {
    if (S.imagery !== "ok") return;
    for (var k in DOM) DOM[k].stale = true;
    dirty();
  }, 600000);
  // A new run is taken in place while the page is open (see refresh); one it
  // cannot take is loaded, the reader's place handed across (see keepPlace).
  elninoLive.follow({take: refresh, keep: keepPlace, restore: restorePlace,
                     boxes: ["panel", "legend"]});

  window.stormDesk = {
    flyTo: function (id) { return flyTo(id); },
    setLayer: function (id) { return setLayer(id); },
    enso: function (patch) { return setEnso(patch || {}); },
    compare: function (on) { return setCompare(on); },
    loop: function (on) { return setLoop(on); },
    scrub: function (hours) { scrub.value = hours; if (S.playing) setPlay(false); setScrub(+scrub.value); return S.scrub; },
    find: function (text) {
      return find(text).map(function (r) { return {kind: r.kind, label: r.label, lon: r.lon, lat: r.lat, zoom: r.zoom}; });
    },
    go: function (text) { var r = find(text); return r.length ? go(r[0]) : false; },
    here: function (lon, lat, open) { if (open) hereAt(lon, lat); return hereFor(lon, lat); },
    enter: function (lon, lat, opts) { return thenEnter(lon, lat, null, opts || {}); },
    leave: function () { return thenLeave(); },
    street: function (lon, lat) { return streetEnter(lon, lat); },
    leaveStreet: function () { return streetLeave(); },
    streetStorms: function (open) { if (open === true) tcOpen(); else if (open === false) tcClose(); return tcView(); },
    view: function () {
      var st = BYID[S.selected], b = st ? base(st) : null;
      return {lon: wrap(lonOf(S.x)), lat: latOf(S.y), zoom: S.z, layer: S.layer,
              compare: S.compare, second: S.second, split: S.split, loop: S.loop,
              frame: S.frame, frames: loopLength(), scrub: S.scrub, selected: S.selected,
              imagery: S.imagery, imageTime: b && b.image ? isoZ(b.t) : null,
              sources: Object.keys(S.inView).filter(function (k) { return k !== "none"; }),
              tiles: document.querySelectorAll("#tiles img").length, pin: S.pin,
              day: S.day, dayState: S.dayState, then: thenView(), street: streetView()};
    }
  };
})();
