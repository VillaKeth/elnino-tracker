"""Drop into Street View, and see what El Nino does to that street.

The toolbar's figure, carried onto the map as Google Maps' figure is, opens
the street stage at the point it is let go: Google's own Street View embed in
the map's place, a minimap of the map's street tiles to move about on, and,
beside it, what El Nino does to that street.

A point the reader picks (the figure let go, the minimap tapped, Here's or
then and now's Street View) goes first to the nearest street, as Google Maps'
figure goes to its blue lines: Google's keyless embed looks only some tens of
metres about a point, and on 9 October 2026 one in a block in Lima found no
panorama and one in Sao Paulo a cafe's inside. FOSSGIS's OSRM names the
nearest road a car may take on OpenStreetMap, asked once a second at most and
credited as its operator asks. An address or the page's API opens exactly
where it says.

That is the street's own record, not the atlas's 2.5 degree cell: the point's
monthly rainfall and temperature since 1981 from NASA POWER, composited in the
page by the atlas composite's own rules (``tools/vendor_composite.py``) against
the tracker's own index; what ECMWF's seasonal forecast expects there for the
next six months, and the weather there now, from Open-Meteo. Each source is
keyless and sent with ``Access-Control-Allow-Origin: *``, as each answered on
9 October 2026, and none is asked anything until the reader drops in or asks.

ERA5 through Open-Meteo would be finer, and is not used: its free API counts
each fortnight of a point's record as a call, so the 47 years the card reads
would cost about 1,200 calls a drop against a limit of 10,000 a day. POWER
answers the whole record in one request.
"""

from __future__ import annotations

from datetime import date

from . import atlas, classify, worldmap
from .svg import esc

# The first month the card's record may read: the atlas composites from 1979,
# and POWER's monthly record starts in 1981.
FIRST_MONTH = date(1979, 1, 1)

# The atlas composite's rules, as tools/vendor_composite.py states them: a
# month is El Nino at RONI +1.0 or more and neutral strictly within 0.5; a
# season needs three events and six neutral years; t_crit is the two-sided 95%
# point of Student's t at the smaller sample less one, the table's last row
# past thirty.
WARM = 1.0
NEUTRAL = 0.5
MIN_EVENTS = 3
MIN_YEARS = 6
T975 = (12.706, 4.303, 3.182, 2.776, 2.571, 2.447, 2.365, 2.306, 2.262, 2.228,
        2.201, 2.179, 2.160, 2.145, 2.131, 2.120, 2.110, 2.101, 2.093, 2.086,
        2.080, 2.074, 2.069, 2.064, 2.060, 2.056, 2.052, 2.048, 2.045, 2.042)

# Where each source is asked, as each answered on 9 October 2026, the point
# written in at {lat} and {lon}:
# * NASA POWER's monthly and daily point APIs: MERRA-2 rainfall, corrected
#   against gauges and GPCP (PRECTOTCORR, mm a day), and 2 m temperature
#   (T2M, deg C), on MERRA-2's 0.5 by 0.625 degree grid; the monthly record
#   from 1981 to the month before last, the daily to three days ago.
# * Open-Meteo's forecast: the weather now and the next 24 hours' rain.
# * Open-Meteo's seasonal forecast: ECMWF's, by month for six months, as
#   anomalies from the model's own climate of past forecasts.
SOURCES = {
    "monthly": ("https://power.larc.nasa.gov/api/temporal/monthly/point?parameters=PRECTOTCORR,T2M"
                "&community=AG&longitude={lon}&latitude={lat}&start=1981&end={year}&format=JSON"),
    "daily": ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR,T2M"
              "&community=AG&longitude={lon}&latitude={lat}&start={start}&end={end}&format=JSON"),
    "now": ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,precipitation,weather_code,wind_speed_10m,wind_direction_10m,"
            "wind_gusts_10m&hourly=precipitation&forecast_hours=24&timezone=auto"),
    "ahead": ("https://seasonal-api.open-meteo.com/v1/seasonal?latitude={lat}&longitude={lon}"
              "&monthly=temperature_2m_anomaly,precipitation_mean,precipitation_anomaly,"
              "sea_surface_temperature_anomaly"),
}

# Where a picked point's street is asked, as FOSSGIS's OSRM answered on 9
# October 2026: the nearest point on OpenStreetMap's roads a car may take, the
# road's name and how far it is, the point written in at {lon} and {lat}.
ROADS = "https://routing.openstreetmap.de/routed-car/nearest/v1/driving/{lon},{lat}?number=1"


def months(series) -> dict:
    """The index by centre month, as CPC prints it, from its first season on
    record (January 1979 at the earliest) to its last; a month the record
    lacks is null, never its neighbour's value."""
    known = {}
    for season in series:
        centre = season.centre
        if centre >= FIRST_MONTH:
            known[(centre.year, centre.month)] = classify.displayed(season.value)
    if not known:
        return {"from": None, "values": []}
    (year, month), last = min(known), max(known)
    first, values = f"{year:04d}-{month:02d}", []
    while (year, month) <= last:
        values.append(known.get((year, month)))
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return {"from": first, "values": values}


def payload(state) -> dict:
    """What the card needs from the run: the index month by month, the atlas
    composite's rules, the atlas's dry floor (under it, rain is given in
    millimetres alone, never as a percentage), the sources' addresses and
    where a picked point's street is asked."""
    assessment = getattr(state, "assessment", None)
    series = list(getattr(assessment, "index_series", None) or [])
    return {"index": getattr(assessment, "index_name", None) or "RONI", "months": months(series),
            "warm": WARM, "neutral": NEUTRAL, "min_events": MIN_EVENTS, "min_years": MIN_YEARS,
            "t975": list(T975), "dry_floor": atlas.DRY_FLOOR, "sources": dict(SOURCES), "roads": ROADS}


# The minimap's tiles are the map's own street layer's, and its credit goes
# beside them.
_STREETS = next(layer for layer in worldmap.MAP_LAYERS if layer["id"] == "streets")


def map_parts() -> str:
    """The stage, on the map and over it while a point is dropped into: a bar
    with the place and the ways on, Google's panorama, and under it a strip
    with the minimap and the card's first lines, so nothing of the page sits
    on Google's own controls and credit; the minimap's tiles, the nearest
    street and the forecast the chip quotes are credited beside them. The
    stage takes the focus a pick gives it."""
    return ('<section class="streetstage ui" id="street-stage" aria-label="Street View" tabindex="-1" hidden>'
            '<div class="streetbar">'
            '<p class="streetplace" id="street-place" aria-live="polite"></p>'
            '<button type="button" class="toolbtn" id="street-then">Then and now</button>'
            '<button type="button" class="toolbtn" id="street-copy">Copy link</button>'
            '<a class="toolbtn" id="street-gmaps" href="https://www.google.com/maps" target="_blank" '
            'rel="noopener">Google Maps \u2197</a>'
            '<button type="button" class="toolbtn" id="street-exit">Exit</button>'
            '<p class="streetnote">A point picked goes first to the nearest street within reach, and Street '
            "View opens on Google\u2019s panorama there; where Google has none it says \u201cNo Street View "
            "available\u201d, and the minimap and the card are this point\u2019s either way.</p>"
            '<p class="streetlink" id="street-link" role="status"></p></div>'
            '<div class="streetpano" id="street-pano"></div>'
            '<div class="streetfoot">'
            '<div class="streetmini" id="street-mini" role="group" aria-label="Minimap: tap a street to move '
            'Street View there">'
            '<div class="streetminitiles" id="street-mini-tiles" aria-hidden="true"></div>'
            '<span class="streetminipin" aria-hidden="true"></span>'
            '<div class="streetminizoom">'
            '<button type="button" id="street-mini-in" aria-label="Zoom the minimap in">+</button>'
            '<button type="button" id="street-mini-out" aria-label="Zoom the minimap out">&minus;</button>'
            "</div></div>"
            '<div class="streetchip" id="street-chip"><div class="streetchiphead"><b>El Ni\u00f1o on this '
            'street</b><button type="button" class="streetmore" id="street-more">The whole card \u2193</button>'
            "</div>"
            '<p class="streetchipsaid" id="street-chip-said"></p>'
            '<p class="streetcredit">ECMWF\u2019s forecast: <a href="https://open-meteo.com/" target="_blank" '
            'rel="noopener">Weather data by Open-Meteo.com</a></p>'
            f'<p class="streetcredit">Minimap: {esc(_STREETS["credit"])}</p>'
            '<p class="streetcredit">Nearest street: <a href="https://project-osrm.org/" target="_blank" '
            'rel="noopener">OSRM</a> by FOSSGIS over <a href="https://www.openstreetmap.org/copyright" '
            'target="_blank" rel="noopener">\u00a9 OpenStreetMap contributors</a>; <a '
            'href="https://www.openstreetmap.org/fixthemap" target="_blank" rel="noopener">fix the map</a>.</p>'
            "</div></div></section>")


# Taken into the desk's script at its /*STREET*/ marker, after then-and-now's.
_JS = r"""
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
  // answered 429").
  function streetFetch(url, wait) {
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
        r.json().then(function (json) { end(json, ""); }, function () { end(null, "sent something that is not data"); });
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
  // and the stage's chip while the street is.
  function streetShow(lon, lat) {
    var key = streetCacheKey("", lon, lat), box = $("street-card");
    if (box && S.here && streetCacheKey("", S.here.lon, S.here.lat) === key) {
      retake(box, streetCardHtml(streetState(S.here.lon, S.here.lat)));
    }
    if (S.street && streetCacheKey("", S.street.lon, S.street.lat) === key) streetChip();
  }
  document.addEventListener("click", function (e) {
    var el = e.target.closest ? e.target.closest("[data-street],[data-street-retry]") : null;
    if (!el || !S.here) return;
    if (el.hasAttribute("data-street-retry")) streetRetry(el.getAttribute("data-street-retry"), S.here.lon, S.here.lat);
    else if (el.getAttribute("data-street") === "ask") streetCard(S.here.lon, S.here.lat, true);
    else if (el.getAttribute("data-street") === "again") streetAgain(S.here.lon, S.here.lat);
  });

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
  // ECMWF's next six months at the point, each against the model's own normal.
  function streetAheadHtml(st, rows) {
    var html = ["<h4>The next six months, ECMWF</h4>"];
    if (!rows) return html.concat(streetWait(st, "ahead")).join("");
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
      "<p>These data were obtained from the NASA Langley Research Center (LaRC) POWER Project funded through the NASA " +
      "Earth Science/Applied Science Program.</p>" +
      "<p>This service is based on data and products of the European Centre for Medium-Range Weather Forecasts " +
      "(ECMWF). Source www.ecmwf.int. ECMWF does not accept any liability whatsoever for any error or omission in the " +
      "data, their availability, or for any loss or damage arising from their use.</p></details>";
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
                box: null, link: "", finding: !!opts.find, back: back};
    if (!opts.find) {
      hereAt(lon, lat, S.street.label);
      streetCard(lon, lat, true);
    }
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
    if (!st) { STREET_SRC = ""; pano.innerHTML = ""; return; }
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
    $("street-gmaps").setAttribute("href", googleLinks(st.lat, st.lon, S.z).street);
    setText($("street-link"), st.link);
    miniDraw();
    streetChip();
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
  // OSRM is asked for the nearest road a car may take, and one within reach
  // takes the point, with its name. Out of reach, or no answer within
  // SNAP_WAIT, and the point stays as picked. OSRM is asked once a second at
  // most, as its operator asks: a pick made meanwhile replaces the one
  // waiting, and an answer for a stage since moved or left is dropped.
  var SNAP_PX = 24, SNAP_NEAR = 250, SNAP_FAR = 5000, SNAP_WAIT = 2500, SNAP_GAP = 1000;
  var FINDING = "Finding the nearest street\u2026", snapAt = -Infinity, snapTimer = 0;
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
      snapRoad(st.lon, st.lat, snapReach(z, st.lat)).then(function (road) {
        if (S.street !== st) return;
        if (!road) streetEnter(st.lon, st.lat, st.label);
        else streetEnter(road.lon, road.lat, (road.name ? road.name + ", " : "") + placeLabel(road.lon, road.lat));
      });
    }, Math.max(0, snapAt + SNAP_GAP - Date.now()));
    return true;
  }
  // How far a picked point may go for its street, in metres: 24 px of the
  // view it was picked on (zoom z, at its latitude), from 250 m to 5 km.
  function snapReach(z, lat) {
    return clamp(SNAP_PX * CIRCUMFERENCE * 1000 * Math.cos(rad(lat)) / (TILE * Math.pow(2, z)), SNAP_NEAR, SNAP_FAR);
  }
  // The nearest road a car may take to a point, by OSRM: {lon, lat, name}
  // within reach (metres), or null, as for no answer or one not understood.
  function snapRoad(lon, lat, reach) {
    var url = D.street.roads.replace("{lon}", lon.toFixed(6)).replace("{lat}", lat.toFixed(6));
    return streetFetch(url, SNAP_WAIT).then(function (json) {
      var w = json && json.code === "Ok" && Array.isArray(json.waypoints) ? json.waypoints[0] : null;
      var at = w && Array.isArray(w.location) ? w.location : [];
      if (!finite(at[0]) || !finite(at[1]) || !finite(w.distance) || w.distance > reach) return null;
      return {lon: lonIn(at[0]), lat: clamp(at[1], -85, 85), name: typeof w.name === "string" ? w.name.trim() : ""};
    }, function () { return null; });
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
  $("street-exit").addEventListener("click", function () { streetLeave(); });
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
  // Esc leaves the street, unless then-and-now's keys took it first (to stop
  // the map waiting for a tap); keys typed into a field are its own.
  document.addEventListener("keydown", function (e) {
    var t = e.target, tag = t && t.tagName;
    if (e.defaultPrevented || e.key !== "Escape" || !S.street) return;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (t && t.closest && t.closest("#findform"))) return;
    e.preventDefault();
    streetLeave();
  });
"""


def css() -> str:
    """The card's rules, over the page's tokens."""
    return """
.streetcard { margin: 10px 0 6px; padding: 10px 12px 8px; border: 1px solid var(--border);
  border-radius: 8px; background: var(--surface); }
.streetcard .streethead { margin: 0 0 4px; font-size: 0.92rem; }
.streetcard .streetsaid { margin: 0 0 6px; font-size: 0.86rem; line-height: 1.5; }
.streetcard h4 { margin: 12px 0 4px; }
.streetbars, .streetdots { display: block; width: 100%; height: auto; margin: 4px 0; }
.streetbars text, .streetdots text { font: 10px var(--font); fill: var(--ink2); }
.streetbars text.strong, .streetdots text.strong { font-weight: 700; fill: var(--ink); }
.streetbars .zero, .streetdots .zero { stroke: var(--axis); stroke-width: 1; }
.streetbars .faint { opacity: 0.32; }
.streettable { width: 100%; border-collapse: collapse; font-size: 0.74rem; font-variant-numeric: tabular-nums; }
.streettable th, .streettable td { text-align: left; padding: 3px 4px; border-bottom: 1px solid var(--border);
  vertical-align: top; font-weight: 400; }
.streettable th[scope="col"] { color: var(--muted); font-weight: 500; }
.streetfail .toolbtn { margin-left: 4px; }
.streetwait { color: var(--ink2); }
/* The stage: Google's panorama between the bar and a strip of the minimap and
   the card's first lines, so nothing of the page sits on Google's own
   controls and credit; its words can be selected, as the map's cannot. */
.streetstage { position: absolute; inset: 0; z-index: 20; display: flex; flex-direction: column;
  background: var(--surface); color: var(--ink); cursor: default; user-select: text; -webkit-user-select: text; }
.streetbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 8px; padding: 6px 10px;
  border-bottom: 1px solid var(--border); }
.streetplace { flex: 1 1 180px; min-width: 0; margin: 0; font: 600 0.92rem var(--font); }
.streetbar .toolbtn { min-height: 36px; padding: 0 10px; font-size: 0.8rem; }
.streetbar a.toolbtn { display: inline-flex; align-items: center; text-decoration: none; }
.streetnote, .streetlink { flex: 1 1 100%; margin: 0; font-size: 0.72rem; line-height: 1.35; color: var(--ink2); }
.streetlink { overflow-wrap: anywhere; }
.streetlink:empty { display: none; }
.streetpano { position: relative; flex: 1 1 auto; min-height: 140px; background: var(--plane); }
.streetframe { position: absolute; inset: 0; width: 100%; height: 100%; border: 0; }
.streetfinding { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
  margin: 0; padding: 0 16px; text-align: center; font-size: 0.86rem; color: var(--ink2); }
.streetfoot { display: flex; gap: 10px; padding: 8px 10px; border-top: 1px solid var(--border); }
.streetmini { position: relative; flex: 0 0 auto; width: 150px; height: 112px; overflow: hidden;
  border: 1px solid var(--border); border-radius: 8px; background: var(--plane); cursor: crosshair; }
.streetminitiles img { position: absolute; width: 256px; height: 256px; max-width: none; pointer-events: none; }
.streetminipin { position: absolute; left: 50%; top: 50%; width: 14px; height: 14px; margin: -7px 0 0 -7px;
  border-radius: 50%; background: var(--warm); border: 2px solid var(--surface);
  box-shadow: 0 0 0 1px var(--ink); pointer-events: none; }
.streetminizoom { position: absolute; right: 4px; top: 4px; display: flex; flex-direction: column; gap: 4px; }
.streetminizoom button { width: 32px; height: 32px; border-radius: 8px; border: 1px solid var(--border);
  background: var(--surface); color: var(--ink); font: 600 0.95rem var(--font); cursor: pointer; }
.streetminizoom button:disabled { opacity: 0.45; cursor: default; }
.streetchip { flex: 1 1 auto; min-width: 0; max-height: 112px; overflow-y: auto; font-size: 0.8rem;
  line-height: 1.45; }
.streetchiphead { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 10px; }
.streetmore { min-height: 32px; padding: 0; border: 0; background: none; color: var(--ink2); cursor: pointer;
  font: 600 0.76rem var(--font); text-decoration: underline; }
.streetmore:focus-visible, .streetminizoom button:focus-visible { outline: 2px solid var(--s1); outline-offset: 2px; }
.streetchipsaid { margin: 2px 0 4px; }
.streetcredit { margin: 0; font-size: 0.62rem; color: var(--ink2); }
.streetcredit a { color: inherit; }
/* Open, the map lets a finger on the stage scroll the page, and on a phone
   stands taller, for the panorama; the stage takes the room of the map's
   scrubber and key too, both the hidden map's. */
#map.streeton { touch-action: pan-y; cursor: default; }
.deskmapcol:has(#map.streeton) .deskscrub, .deskmapcol:has(#map.streeton) .desklegend { display: none; }
@media (max-width: 899px) { #map.streeton { height: 78vh; min-height: 440px; } }
@media (min-width: 900px) {
  .streetmini { width: 220px; height: 165px; }
  .streetchip { max-height: 165px; }
}
"""
