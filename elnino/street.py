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
nearest roads a car may take on OpenStreetMap, asked once a second at most and
credited as its operator asks; the pick goes to the nearest named one within a
kilometre, as unnamed ways (driveways, service roads) are where Google's car
did not go, and Next street goes down the rest. FOSSGIS's Valhalla, over the
same map, is asked as well when OSRM has not answered in 2.5 seconds, or at
once when it fails; neither giving a road, the stage says so and Find the
street asks again. Every Street View the page offers is a pick: on 14 October
2026 Here's own frame of Google's, at the point as tapped, showed "No Street
View available." or a photo someone took inside for six of sixteen taps over
New York, where picks found Google's own panorama for thirty-one of
thirty-one. An address or the page's API opens exactly where it says.

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
# * Open-Meteo's seasonal forecast: ECMWF's, by month for the seven months
#   its run reaches from the month it is made in (Open-Meteo gives six unless
#   asked), as anomalies from the model's own climate of past forecasts: the
#   card gives six, and the replay's window from next month needs the seventh.
# * POWER's daily record again, every day since 1981, for the replay of El
#   Nino's rain on the street, asked only when the replay is opened: as CSV,
#   342 KB for Winter Haven on 12 October 2026, where the JSON was 547 (POWER
#   sends neither compressed).
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
              "sea_surface_temperature_anomaly&forecast_days=215"),
    "days": ("https://power.larc.nasa.gov/api/temporal/daily/point?parameters=PRECTOTCORR,T2M"
             "&community=AG&longitude={lon}&latitude={lat}&start=19810101&end={end}&format=CSV"),
}

# Where a picked point's street is asked, as FOSSGIS's OSRM answered on 12
# October 2026: the 100 nearest stretches of OpenStreetMap's roads a car may
# take (its documented limit, in 25 KB), each with its road's name and how far
# it is, the point written in at {lon} and {lat}.
ROADS = "https://routing.openstreetmap.de/routed-car/nearest/v1/driving/{lon},{lat}?number=100"

# Where a pick's street is asked when OSRM does not answer, as FOSSGIS's
# Valhalla answered on 14 October 2026: the roads a car may take within a
# radius of the point, or the nearest, each with its names and how far it
# is (28 KB within 100 m of Fifth Avenue), the question written in as JSON
# at {json}.
LOCATE = "https://valhalla1.openstreetmap.de/locate?json={json}"


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
    the two places a picked point's street is asked."""
    assessment = getattr(state, "assessment", None)
    series = list(getattr(assessment, "index_series", None) or [])
    return {"index": getattr(assessment, "index_name", None) or "RONI", "months": months(series),
            "warm": WARM, "neutral": NEUTRAL, "min_events": MIN_EVENTS, "min_years": MIN_YEARS,
            "t975": list(T975), "dry_floor": atlas.DRY_FLOOR, "sources": dict(SOURCES), "roads": ROADS,
            "locate": LOCATE}


# The minimap's tiles are the map's own street layer's, and its credit goes
# beside them.
_STREETS = next(layer for layer in worldmap.MAP_LAYERS if layer["id"] == "streets")


_MONTH_WORDS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                "November", "December")


def _sim_panel() -> str:
    """The replay of El Nino's rain, in the chip's place while it is open:
    Play, the El Nino, the six months and the speed; a slider through the
    days, the day's readout, the chart with its key, and the words; what
    went wrong, with a Retry; the years side by side, and how it is known."""
    starts = "".join(f'<option value="{m + 1}">{_MONTH_WORDS[m]} to {_MONTH_WORDS[(m + 5) % 12]}</option>'
                     for m in range(12))
    return ('<div class="streetsim" id="street-sim" role="group" aria-labelledby="street-sim-title" tabindex="-1" '
            'hidden><div class="streetchiphead"><b id="street-sim-title">El Ni\u00f1o\u2019s rain, replayed here</b>'
            '<button type="button" class="streetmore" id="street-sim-back">Back to the card</button></div>'
            '<div class="streetsimbar">'
            '<button type="button" class="toolbtn" id="street-sim-play" disabled>Play</button>'
            '<label>El Ni\u00f1o <select id="street-sim-event" disabled></select></label>'
            f'<label>Months <select id="street-sim-start">{starts}</select></label>'
            '<label>Speed <select id="street-sim-speed"><option value="7">a week a second</option>'
            '<option value="14">two weeks a second</option><option value="30">a month a second</option></select>'
            "</label></div>"
            '<input type="range" class="streetsimday" id="street-sim-day" min="0" max="0" step="1" value="0" '
            'aria-label="Day of the window" disabled>'
            '<p class="streetsimread" id="street-sim-read"></p>'
            '<div class="streetsimchart" id="street-sim-chart"></div>'
            '<p class="streetsimkey" id="street-sim-key"></p>'
            '<p class="streetsimsaid" id="street-sim-said" aria-live="polite"></p>'
            '<p class="streetfail" id="street-sim-fail" hidden><span id="street-sim-why"></span> '
            '<button type="button" class="toolbtn" id="street-sim-retry">Retry</button></p>'
            '<details class="streetsimmore"><summary>Year by year</summary>'
            '<div class="streetsimtable" id="street-sim-table"></div></details>'
            '<details class="streetsimmore"><summary>Method and sources</summary>'
            '<div id="street-sim-method"></div></details></div>')


def map_parts() -> str:
    """The stage, on the map and over it while a point is dropped into: a bar
    with the place and the ways on, Google's panorama, and under it a strip
    with the minimap and the card's first lines, or the replay of El Nino's
    rain in their place, so nothing of the page sits on Google's own controls
    and credit; the replay's rain and the badge naming its day lie over the
    panorama, clear of its foot and never taking a pointer. The minimap's
    tiles, the nearest street, the forecast the chip quotes and the replay's
    record are credited beside them. The stage takes the focus a pick gives
    it."""
    return ('<section class="streetstage ui" id="street-stage" aria-label="Street View" tabindex="-1" hidden>'
            '<div class="streetbar">'
            '<p class="streetplace" id="street-place" aria-live="polite"></p>'
            '<button type="button" class="toolbtn" id="street-next" hidden>Next street</button>'
            '<button type="button" class="toolbtn" id="street-find" hidden>Find the street</button>'
            '<button type="button" class="toolbtn" id="street-then">Then and now</button>'
            '<button type="button" class="toolbtn" id="street-copy">Copy link</button>'
            '<a class="toolbtn" id="street-gmaps" href="https://www.google.com/maps" target="_blank" '
            'rel="noopener">Google Maps \u2197</a>'
            '<button type="button" class="toolbtn" id="street-exit">Exit</button>'
            '<p class="streetroads" id="street-roads" aria-live="polite"></p>'
            '<p class="streetnote">Street View shows Google\u2019s panorama nearest the stage\u2019s point. A point '
            "picked (the figure dropped, the minimap tapped, or Street View pressed in Here or in then and now) goes "
            "to the nearest named street within a kilometre, else the nearest road within reach. Where Google has no "
            "panorama of it, it "
            "says \u201cNo Street View available.\u201d, and where its nearest is a photo someone took inside, it "
            "shows that: Next street tries the next. The minimap and the card are this point\u2019s either way.</p>"
            '<p class="streetlink" id="street-link" role="status"></p></div>'
            '<div class="streetview"><div class="streetpano" id="street-pano"></div>'
            '<canvas class="streetrain" id="street-rain" aria-hidden="true" hidden></canvas>'
            '<p class="streetday" id="street-day" aria-hidden="true" hidden></p></div>'
            '<div class="streetfoot">'
            '<div class="streetmini" id="street-mini" role="group" aria-label="Minimap: tap a street to move '
            'Street View there">'
            '<div class="streetminitiles" id="street-mini-tiles" aria-hidden="true"></div>'
            '<span class="streetminipin" aria-hidden="true"></span>'
            '<div class="streetminizoom">'
            '<button type="button" id="street-mini-in" aria-label="Zoom the minimap in">+</button>'
            '<button type="button" id="street-mini-out" aria-label="Zoom the minimap out">&minus;</button>'
            "</div></div>"
            '<div class="streetchip" id="street-chip"><div class="streetchiphead" id="street-chip-head"><b>El '
            'Ni\u00f1o on this street</b><button type="button" class="toolbtn streetreplay" id="street-replay">'
            'Replay El Ni\u00f1o\u2019s rain</button><button type="button" class="streetmore" id="street-more">The '
            "whole card \u2193</button></div>"
            '<p class="streetchipsaid" id="street-chip-said"></p>'
            + _sim_panel() +
            '<p class="streetcredit">ECMWF\u2019s forecast: <a href="https://open-meteo.com/" target="_blank" '
            'rel="noopener">Weather data by Open-Meteo.com</a></p>'
            '<p class="streetcredit" id="street-sim-credit" hidden>Daily rain: <a href="https://power.larc.nasa.gov/" '
            'target="_blank" rel="noopener">NASA POWER</a>, NASA Langley Research Center.</p>'
            f'<p class="streetcredit">Minimap: {esc(_STREETS["credit"])}</p>'
            '<p class="streetcredit">Nearest street: <a href="https://project-osrm.org/" target="_blank" '
            'rel="noopener">OSRM</a> or <a href="https://valhalla.github.io/valhalla/" target="_blank" '
            'rel="noopener">Valhalla</a> by FOSSGIS over <a href="https://www.openstreetmap.org/copyright" '
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
    // record of its cell.
    if (S.sim) { simPlay(false); simLoad(); }
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
    setHidden($("street-next"), !(st.roads && st.roads.length > 1));
    setHidden($("street-find"), !finite(st.unfound));
    setText($("street-roads"), roadsLine(st));
    $("street-gmaps").setAttribute("href", googleLinks(st.lat, st.lon, S.z).street);
    setText($("street-link"), st.link);
    miniDraw();
    streetChip();
    simDraw();
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
  // The replay opened on the stage's point at next month's window, its
  // record asked if it has not got the cell's, the focus on the panel.
  function simOpen() {
    if (!S.street) return false;
    if (!S.sim) {
      var start = new Date(Date.now()).getUTCMonth() + 2;
      S.sim = {start: start > 12 ? start - 12 : start, tag: null, day: 0, pos: 0, speed: SIM_SPEEDS[0],
               playing: false, key: "", rec: null, model: null, why: "", frame: 0, last: 0, seeking: false, touch: null,
               geo: null};
    }
    simLoad();
    simDraw();
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
    var sim = S.sim, on = !!sim && !!S.street;
    $("street-stage").classList.toggle("simon", on);
    setHidden($("street-sim"), !on);
    setHidden($("street-sim-credit"), !on);
    setHidden($("street-chip-head"), on);
    setHidden($("street-chip-said"), on);
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
  // RAIN_SLANT across for each pixel down, as its drop drifts on the wind.
  var RAIN_BLUR = 0.03, RAIN_SLANT = 0.12, RAIN_STILL = null;
  // Whether the reader asks for less motion, asked of the browser once.
  function rainStill() {
    if (RAIN_STILL === null) {
      RAIN_STILL = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : false;
    }
    return !!(RAIN_STILL && RAIN_STILL.matches);
  }
  // Whether rain falls on the day the replay shows, to be drawn frame by frame.
  function rainOn() {
    var rain = S.sim && S.sim.rain;
    return !!rain && rain.drops > 0 && !rainStill();
  }
  // The rain for the day the replay shows, and the badge naming it (when, in
  // the slider's words): both hidden, and the canvas let go, while the replay
  // shows no day or the street is being found. The canvas is shown only while
  // it rains: one cleared and drawn on no more can go on showing what it drew
  // last (Chrome, 12 October 2026). The drops are kept while the day's kind
  // of rain is, as many as the day asks; a wet day is drawn at once, and the
  // frames run while it rains, unless the reader asks for less motion.
  function rainDay(when) {
    var sim = S.sim, run = simChosen(), st = S.street, canvas = $("street-rain"), badge = $("street-day");
    var on = !!run && !!st && !st.finding, level = on ? rainLevel(run.p[sim.day], run.t[sim.day]) : null;
    setHidden(canvas, !(level && level.drops));
    setHidden(badge, !on);
    if (!on) {
      if (canvas.width) { canvas.width = 0; canvas.height = 0; }
      if (sim && sim.rain) { sim.rain = null; simFrame(); }
      return;
    }
    setText(badge, when);
    var key = when + "|" + level.kind + "|" + level.drops, was = sim.rain;
    if (was && was.key === key) return;
    var drops = was && was.kind === level.kind ? was.parts : [];
    while (drops.length > level.drops) drops.pop();
    while (drops.length < level.drops) {
      drops.push({x: Math.random(), y: Math.random(), z: 0.4 + 0.6 * Math.random(), w: Math.random() * 2 * Math.PI});
    }
    sim.rain = {key: key, kind: level.kind, drops: level.drops, gloom: level.gloom, speed: level.speed, parts: drops,
                last: was ? was.last : 0};
    if (level.drops) rainPaint(0);
    simFrame();
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
  // long as they are fast; snow as flakes swaying as they fall - a path a
  // depth.
  function rainPaint(ts) {
    var rain = S.sim && S.sim.rain, canvas = $("street-rain");
    var ctx = rain && canvas.getContext ? canvas.getContext("2d") : null;
    if (!ctx) return false;
    var box = rainSize(canvas), w = box.w, h = box.h, snow = rain.kind === "snow", sway = (ts || rain.last) / 1000;
    var dt = ts && rain.last ? Math.min(ts - rain.last, SIM_HELD) / 1000 : 0, depths = [[], [], []];
    if (ts) rain.last = ts;
    ctx.setTransform(box.dpr, 0, 0, box.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!rain.parts.length) return true;
    ctx.fillStyle = "rgba(14, 22, 33, " + rain.gloom + ")";
    ctx.fillRect(0, 0, w, h);
    rain.parts.forEach(function (d) {
      var v = rain.speed * d.z;
      d.y += v * dt;
      if (!snow) d.x += RAIN_SLANT * v * dt * h / w;
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
          var len = rain.speed * d.z * h * RAIN_BLUR;
          ctx.moveTo(x, y);
          ctx.lineTo(x - RAIN_SLANT * len, y - len);
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
  // The replay's controls. A mouse or pen down on the chart seeks, and seeks
  // as it moves until it is let go. A finger seeks where it is lifted, or
  // once it goes across (SIM_SLOP) and on as it moves; moving up or down
  // first, it scrolls the panel (pan-y, the browser's) and seeks nothing.
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
  $("street-sim-chart").addEventListener("pointerdown", function (e) {
    if (!S.sim || (e.button !== undefined && e.button !== 0)) return;
    if (e.pointerType === "touch") S.sim.touch = {id: e.pointerId, x: e.clientX, y: e.clientY};
    else simSeekFrom(e);
  });
  $("street-sim-chart").addEventListener("pointermove", function (e) {
    var sim = S.sim, t = sim && sim.touch;
    if (sim && sim.seeking) { simSeek(e.clientX); return; }
    if (!t || t.id !== e.pointerId) return;
    var across = Math.abs(e.clientX - t.x), up = Math.abs(e.clientY - t.y);
    if (across > SIM_SLOP && across > up) { sim.touch = null; simSeekFrom(e); }
    else if (up > SIM_SLOP) sim.touch = null;
  });
  $("street-sim-chart").addEventListener("pointerup", function (e) {
    var sim = S.sim;
    if (!sim) return;
    if (sim.touch && sim.touch.id === e.pointerId) simSeek(e.clientX);
    sim.touch = null;
    sim.seeking = false;
  });
  $("street-sim-chart").addEventListener("pointercancel", function () { if (S.sim) { S.sim.touch = null; S.sim.seeking = false; } });
  if (window.ResizeObserver) new ResizeObserver(function () {
    var sim = S.sim;
    if (sim && sim.geo && Math.round($("street-sim-chart").getBoundingClientRect().width) !== sim.geo.width) {
      simChartDraw();
      simHead();
    }
  }).observe($("street-sim-chart"));
  // The rain drawn again at the canvas's new size.
  if (window.ResizeObserver) new ResizeObserver(function () { if (S.sim && S.sim.rain) rainPaint(0); })
    .observe($("street-rain"));
  // Esc closes the replay, and leaves the street when it is closed, unless
  // then-and-now's keys took it first (to stop the map waiting for a tap);
  // keys typed into a field are its own, but for the replay's own controls.
  document.addEventListener("keydown", function (e) {
    var t = e.target, tag = t && t.tagName, mine = !!S.sim && !!(t && t.closest && t.closest("#street-sim"));
    if (e.defaultPrevented || e.key !== "Escape" || !S.street) return;
    if (!mine && (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (t && t.closest && t.closest("#findform")))) {
      return;
    }
    e.preventDefault();
    if (S.sim) simClose(); else streetLeave();
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
.streetnote, .streetlink, .streetroads { flex: 1 1 100%; margin: 0; font-size: 0.72rem; line-height: 1.35;
  color: var(--ink2); }
.streetroads { color: var(--ink); }
.streetlink { overflow-wrap: anywhere; }
.streetlink:empty { display: none; }
/* The line about a pick says it for this point: the note gives it the room. */
.streetroads:empty { display: none; }
.streetroads:not(:empty) + .streetnote { display: none; }
.streetview { position: relative; flex: 1 1 auto; min-height: 140px; }
.streetpano { position: absolute; inset: 0; background: var(--plane); }
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
/* The replay, in the chip's place: the chip stands taller and, on a phone,
   takes the minimap's room, and the stage stands taller, so the panorama,
   where the rain falls, keeps its room; its chart is drawn to the width it
   has, a finger across it seeking and up and down scrolling. */
.streetreplay { min-height: 32px; padding: 0 10px; font-size: 0.76rem; }
.streetstage.simon .streetfoot { max-height: 52%; }
.streetstage.simon .streetchip { max-height: none; }
@media (max-width: 899px) { .streetstage.simon .streetmini { display: none; } }
@media (max-width: 899px) { #map.streeton:has(.streetstage.simon) { height: 92vh; height: 92svh; } }
.streetsim { display: flex; flex-direction: column; gap: 6px; padding-bottom: 4px; }
.streetsim:focus { outline: none; }
.streetsimbar { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; }
.streetsimbar label { display: inline-flex; align-items: center; gap: 4px; font-size: 0.74rem; color: var(--ink2); }
.streetsimbar select { min-height: 32px; max-width: 13em; padding: 0 4px; border: 1px solid var(--border);
  border-radius: 6px; background: var(--surface); color: var(--ink); font: 0.76rem var(--font); }
.streetsimbar .toolbtn { min-height: 32px; min-width: 5.5em; }
.streetsimday { width: 100%; margin: 0; accent-color: var(--warm); }
.streetsimread, .streetsimsaid, .streetsimkey, .streetsim .streetfail { margin: 0; }
.streetsimread { min-height: 2.9em; font-variant-numeric: tabular-nums; }
.streetsimchart { position: relative; min-height: 170px; touch-action: pan-y; cursor: col-resize; }
.streetsimsvg { display: block; width: 100%; height: auto; }
.streetsimsvg text { font: 10px var(--font); fill: var(--ink2); }
.streetsimsvg .lab { font-weight: 700; }
.streetsimsvg .lab.ev { fill: var(--warm); }
.streetsimsvg .lab.ecmwf { fill: var(--s1); }
.streetsimsvg .lab.now { fill: var(--ink); }
.streetsimsvg .grid { stroke: var(--border); stroke-width: 1; }
.streetsimsvg .tick { stroke: var(--axis); stroke-width: 1; }
.streetsimsvg .band { fill: var(--ink2); fill-opacity: 0.14; stroke: none; }
/* A line's class names its label too: its rules are its path's. */
.streetsimsvg path.neutral, .streetsimsvg path.ecmwf, .streetsimsvg path.ev, .streetsimsvg path.evfaint,
.streetsimsvg path.now { fill: none; stroke-linejoin: round; stroke-linecap: round; }
.streetsimsvg path.neutral { stroke: var(--ink2); stroke-width: 1.5; stroke-dasharray: 4 3; }
.streetsimsvg path.ecmwf { stroke: var(--s1); stroke-width: 2; stroke-dasharray: 6 3; }
.streetsimsvg path.evfaint { stroke: var(--warm); stroke-width: 1.25; stroke-opacity: 0.3; }
.streetsimsvg path.ev { stroke: var(--warm); stroke-width: 2.75; }
.streetsimsvg path.now { stroke: var(--ink); stroke-width: 1.75; }
.streetsimsvg .bars { fill: var(--warm); fill-opacity: 0.75; }
.streetsimsvg .head { stroke: var(--ink); stroke-width: 1; }
.streetsimsvg .dot { fill: var(--warm); stroke: var(--surface); stroke-width: 1.5; }
.streetsimsvg .dot.ink { fill: var(--ink); }
.streetsimkey { display: flex; flex-wrap: wrap; gap: 2px 12px; font-size: 0.7rem; color: var(--ink2); }
.streetsimkey span::before { content: ""; display: inline-block; width: 14px; margin: 0 4px 3px 0;
  vertical-align: middle; border-top: 2px solid var(--ink2); }
.streetsimkey .ev::before { border-top: 3px solid var(--warm); }
.streetsimkey .faint::before { border-top-color: var(--warm); opacity: 0.4; }
.streetsimkey .neutral::before { border-top-style: dashed; }
.streetsimkey .ecmwf::before { border-top: 2px dashed var(--s1); }
.streetsimkey .now::before { border-top-color: var(--ink); }
.streetsimkey .bars::before { width: 6px; height: 9px; border: 0; background: var(--warm); opacity: 0.75; }
.streetsimmore summary { min-height: 32px; display: flex; align-items: center; cursor: pointer; font-weight: 600;
  font-size: 0.76rem; }
.streetsimmore p { margin: 4px 0 8px; font-size: 0.74rem; }
.streetsimtable { overflow-x: auto; }
.streetsimtable tr.strong th, .streetsimtable tr.strong td { font-weight: 700; }
/* The replay's rain over the panorama: the page's drawing, never taking a
   pointer, clear of Google's logo and terms in the panorama's bottom 40 px
   and fading out above them; the badge naming its day sits above them too. */
.streetrain { position: absolute; left: 0; top: 0; width: 100%; height: calc(100% - 40px); pointer-events: none;
  -webkit-mask-image: linear-gradient(to bottom, #000 calc(100% - 48px), transparent);
  mask-image: linear-gradient(to bottom, #000 calc(100% - 48px), transparent); }
.streetday { position: absolute; left: 8px; bottom: 48px; max-width: calc(100% - 16px); margin: 0; padding: 3px 8px;
  border-radius: 6px; background: var(--surface); color: var(--ink); font: 600 0.74rem var(--font);
  font-variant-numeric: tabular-nums; box-shadow: 0 1px 3px rgba(0, 0, 0, 0.35); pointer-events: none; }
"""
