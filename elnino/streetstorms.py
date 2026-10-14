"""Hurricanes on the street: what the live storms mean for the stage's point,
a storm's wind replayed over Google's panorama, and the storms that passed
the point since 1950, by El Nino's phase.

The street stage (elnino/street.py) puts Google's panorama between a bar and
a strip holding the minimap and the chip. When a live storm's official
forecast comes near the point, by Here's own rule, the chip says so; a button
beside the El Nino replay's opens a panel in the chip's place with the near
storms, a replay of a live forecast or of a past storm's best track, and the
record since 1950.

The record is HURDAT2, which the cyclone tier downloads every run for the
season panel's climatology (``cyclones.hurdat_tracks``): the North Atlantic
and the eastern and central North Pacific, each storm's track from 1950 with
its winds and, from 2004, its wind radii. Written for the page it is 1.8 MB
(280 KB as GitHub Pages compresses it), so it is an asset the page names to
load only when the panel is opened (``assets.Asset.lazy_tag``), never one it
runs.

A season's phase is the official index's ASO value as CPC prints it, El Nino
at +0.5 or more and La Nina at -0.5 or less, as the season panel takes it
(``cyclones.elnino_years``).
"""

from __future__ import annotations

from . import assets, classify, cyclones

# The record's first year, RONI's.
FIRST = 1950
# A storm counts from the tropical-storm threshold; one that never reached it
# is not sent.
STORM_KT = 34
# A season's phase, on the index as CPC prints it.
WARM, COOL = cyclones.EVENT_FLOOR, -cyclones.EVENT_FLOOR
# How near a storm's centre passes to count at the point, nautical miles: the
# choices offered, and the first. NHC's return periods count within 50, which
# leaves most points too few storms to set one phase against another.
RADII_NM, RADIUS_NM = (50, 100, 200), 100
# The replay's speeds, hours a second, and the first.
SPEEDS, SPEED = (3, 6, 12), 6
# A past storm is replayed over the hours its centre is within this of the
# point, kilometres, and a point no storm came this near is outside HURDAT2's
# basins.
NEAR_KM = 1000
# The surface wind's angle in towards the centre, degrees: a typical inflow
# angle near the surface, from which the page works out where the wind comes
# from.
INFLOW = 20
# HURDAT2's first season with wind radii: past storms are replayed from it.
REPLAY_FROM = 2004
# Within this of the centre, kilometres, where the wind comes from is not said.
CENTRE_KM = 10


def payload(state) -> dict:
    """What the desk's data carry for the panel (``D.tc``): the official
    index's ASO value as CPC prints it for each year from FIRST, null for a
    year without one, the index's name, and the panel's constants."""
    assessment = getattr(state, "assessment", None)
    series = getattr(assessment, "index_series", None) or ()
    aso = {item.year: classify.displayed(item.value) for item in series
           if item.season == cyclones.SEASON_KEY and item.year >= FIRST}
    years = range(FIRST, max(aso, default=FIRST - 1) + 1)
    return {"aso": {"from": FIRST, "values": [aso.get(year) for year in years]},
            "index": getattr(assessment, "index_name", None) or "RONI",
            "warm": WARM, "cool": COOL, "radii_nm": list(RADII_NM), "radius_nm": RADIUS_NM,
            "speeds": list(SPEEDS), "speed": SPEED, "near_km": NEAR_KM, "inflow": INFLOW,
            "first": FIRST, "replay_from": REPLAY_FROM, "centre_km": CENTRE_KM}


def tracks_payload(state) -> dict | None:
    """HURDAT2's tracks as the page reads them, or None with none to send.

    Each storm that reached STORM_KT from FIRST on, basin by basin as the
    files list them: its id, its name, its first fix's time ("YYYYMMDDHHMM"),
    and a row of integers a fix, each relative to the fix before (the first's
    position as it is): minutes, tenths of a degree of latitude, and of
    longitude carried on across the date line rather than wrapped; then the
    wind (null unknown), the status as an index into ``statuses``, and, on a
    row that knows any, the twelve radii (null unknown).
    """
    storms = getattr(state, "cyclones", None)
    tracks = getattr(storms, "tracks", None) or {}
    kept = [track for basin in sorted(tracks) for track in tracks[basin]
            if track.year >= FIRST and (track.peak or 0) >= STORM_KT]
    if not kept:
        return None
    statuses = sorted({fix.status for track in kept for fix in track.fixes})
    index = {status: number for number, status in enumerate(statuses)}
    return {"first": FIRST, "last": max(track.year for track in kept),
            "files": dict(getattr(storms, "track_files", None) or {}), "statuses": statuses,
            "storms": [[track.id, track.name, f"{track.fixes[0].when:%Y%m%d%H%M}",
                        _rows(track.fixes, index)] for track in kept]}


def _rows(fixes, index: dict) -> list[list]:
    """A track's fixes as rows, each relative to the fix before."""
    rows, before = [], None
    for fix in fixes:
        lat, lon = round(fix.lat * 10), round(fix.lon * 10)
        if before is None:
            row = [0, lat, lon]
        else:
            when, last_lat, last_lon = before
            # The shorter way round: across the date line the longitude runs
            # on past 180 degrees rather than jumping back 359.
            step = lon - last_lon
            step -= 3600 * round(step / 3600)
            lon = last_lon + step
            row = [round((fix.when - when).total_seconds() / 60), lat - last_lat, step]
        row += [fix.wind, index[fix.status]]
        if fix.radii is not None:
            row += list(fix.radii)
        rows.append(row)
        before = (fix.when, lat, lon)
    return rows


# The asset made last and the tracks it was made of: the desk and the map,
# written from one run, name the one asset, written out once.
_made: tuple = (None, None)


def asset(state) -> assets.Asset | None:
    """The tracks as the asset setting ``ELNINO.tracks``, which the page names
    to load only when the panel is opened; None with none to send."""
    global _made
    tracks = getattr(getattr(state, "cyclones", None), "tracks", None)
    if not tracks:
        return None
    if _made[0] is not tracks:
        value = tracks_payload(state)
        _made = (tracks, assets.data("tracks", value) if value else None)
    return _made[1]


# How the panel's live part is known.
_METHOD = ("<p>The live storms are Here\u2019s: a storm is listed when its official forecast comes within "
           "1,500 km of this point, or, with no forecast this run, it is that close now, or the point is in its "
           "peak storm surge area or within 300 km of a coast under its watch or warning. When its wind reaches "
           "here is worked out from the official forecast hour by hour, centre, wind and wind radii interpolated "
           "linearly between forecast times, as the exposure table does, so a radius the forecast does not give "
           "is not forecast, never zero; this is not an official product. Distances are great-circle; every time "
           "is UTC.</p>")
# How the replay is known.
_REPLAY_METHOD = (
    "<p>The replay plays a live storm\u2019s official forecast hour by hour as Here reads it, or a past storm\u2019s "
    f"best track from HURDAT2 since {REPLAY_FROM}, the first season it gives wind radii, made hourly by the same "
    "rules: the centre and its wind interpolated linearly between fixes, a radius known where the file gives "
    "one, zero where the wind is under its threshold and unknown otherwise, interpolated only between two known "
    "ends. A past storm is replayed over the hours its centre is "
    f"within {NEAR_KM:,} km of here or its 34-kt wind is over here, six hours either side. Each hour the "
    "point\u2019s band is the strongest wind it is inside, the next said not forecast (not known, for a past "
    "storm) where no radius gives it. A wind radius is the furthest that wind reaches anywhere in its quadrant, "
    "so the band here is the most the forecast or the analysis allows; the wind at the point may be lower.</p>"
    "<p>Where the wind comes from is worked out here, not forecast: it blows round the centre, anticlockwise "
    f"north of the equator and clockwise south of it, and {INFLOW} degrees in towards it, a typical inflow angle "
    "near the surface over the sea; over land the angle is larger, so the wind there blows more nearly towards "
    f"the centre than shown; within {CENTRE_KM} km of the centre it is not given. The streaks over the panorama "
    "illustrate the band; they are not a rain forecast, and they do not turn when Google\u2019s view is turned, "
    "which the page cannot see.</p>")


def chip_line() -> str:
    """The storm line atop the stage's chip: what the official forecasts of
    the live storms nearest the point bring to it, written by the page, hidden
    with none near and while a panel is open in the chip."""
    return '<div class="streettcline" id="street-tc-line" role="status" hidden></div>'


def button() -> str:
    """The button beside the El Nino replay's that opens the panel; the page
    names the storms on it as the warning centres where the point is do."""
    return '<button type="button" class="toolbtn streetreplay" id="street-tc-open">Hurricanes here</button>'


def panel() -> str:
    """The panel, in the chip's place while it is open, as the El Nino
    replay's is: the live storms near the point as Here lists them; the
    replay of a storm's wind here hour by hour - Play, the storm and the
    speed, a slider through the hours, the hour's readout, the chart with its
    key, the words and the hours in a table, all written by the page; the
    storms that passed within the distance chosen since 1950, counted once the
    page has read the tracks, with what went wrong and a Retry, and storm by
    storm; and how all are known, the history's part written by the page, as
    it names the run's index."""
    radii = "".join(f'<option value="{nm}"{" selected" if nm == RADIUS_NM else ""}>{nm} n mi '
                    f"({round(nm * cyclones.KT_TO_KMH)} km)</option>" for nm in RADII_NM)
    speeds = "".join(f'<option value="{s}"{" selected" if s == SPEED else ""}>{s} hours a second</option>'
                     for s in SPEEDS)
    return ('<div class="streettc" id="street-tc" role="group" aria-labelledby="street-tc-title" tabindex="-1" '
            'hidden><div class="streetchiphead"><b id="street-tc-title">Hurricanes here</b>'
            '<button type="button" class="streetmore" id="street-tc-back">Back to the card</button></div>'
            '<h4>Live storms</h4><div id="street-tc-live"></div>'
            '<h4>Replay</h4><div class="streetsimbar">'
            '<button type="button" class="toolbtn" id="street-tc-play" disabled>Play</button>'
            '<label>Storm <select id="street-tc-run" disabled></select></label>'
            f'<label>Speed <select id="street-tc-speed">{speeds}</select></label></div>'
            '<input type="range" class="streetsimday" id="street-tc-hour" min="0" max="0" step="1" value="0" '
            'aria-label="Hour of the replay" disabled>'
            '<p class="streetsimread" id="street-tc-read"></p><div class="streetsimchart" id="street-tc-chart"></div>'
            '<p class="streetsimkey" id="street-tc-key"></p>'
            '<div class="streetsimsaid" id="street-tc-said" aria-live="polite"></div>'
            '<details class="streetsimmore" id="street-tc-every" hidden><summary>Hour by hour</summary>'
            '<div class="streetsimtable" id="street-tc-hours"></div></details>'
            f'<h4>Since {FIRST}</h4><div class="streetsimbar"><label>Within <select id="street-tc-radius">{radii}'
            "</select> of here</label></div>"
            '<div class="streettcpast" id="street-tc-past" aria-live="polite"></div>'
            '<p class="streetfail" id="street-tc-fail" hidden><span id="street-tc-why"></span> '
            '<button type="button" class="toolbtn" id="street-tc-retry">Retry</button></p>'
            '<details class="streetsimmore" id="street-tc-each" hidden><summary>Storm by storm</summary>'
            '<div class="streetsimtable" id="street-tc-table"></div></details>'
            '<details class="streetsimmore"><summary>Method and sources</summary>'
            f'<div>{_METHOD}{_REPLAY_METHOD}<div id="street-tc-method"></div></div></details></div>')


def credit() -> str:
    """HURDAT2's credit in the stage's strip, shown while the panel is open,
    as NASA POWER's is while the El Nino replay is."""
    return ('<p class="streetcredit" id="street-tc-credit" hidden>Storm tracks: <a '
            'href="https://www.nhc.noaa.gov/data/#hurdat" target="_blank" rel="noopener">HURDAT2</a>, NOAA National '
            "Hurricane Center.</p>")


def css() -> str:
    """The line's and the panel's rules, over the page's tokens."""
    return """
/* The storm line atop the stage's chip, each storm with its hue; the panel in
   the chip's place, as the El Nino replay is (street.css). */
.streettcline { margin: 0 0 4px; padding: 3px 8px; border-left: 3px solid var(--warning);
  border-radius: 0 6px 6px 0; background: color-mix(in srgb, var(--warning) 9%, var(--surface)); }
.streettcline p { margin: 0; }
.streettcline p + p { margin-top: 2px; }
.streettcline .swatch { display: inline-block; width: 10px; height: 10px; border-radius: 3px; margin-right: 6px;
  vertical-align: baseline; }
.streettc { display: flex; flex-direction: column; gap: 6px; padding-bottom: 4px; }
.streettc:focus { outline: none; }
.streettc h4 { margin: 2px 0 0; font-size: 0.78rem; }
.streettc .herestorms li { padding: 6px 0; font-size: 0.78rem; }
.streettcpast { display: flex; flex-direction: column; gap: 4px; }
.streettcpast p, .streettc .streetfail { margin: 0; }
/* The replay: the hour's slider in the warning hue, the storm's menu as
   wide as the panel lets it be, the words a paragraph each; on the chart the
   centre's distance, and a strip a threshold, filled in the storm's hue where
   that wind is here, deeper for the stronger, and hatched where it is not
   known; now dashed; the key's swatches to match. */
.streettc .streetsimday { accent-color: var(--warning); }
.streettc #street-tc-run { max-width: 100%; }
.streettc .streetsimsaid p { margin: 0 0 4px; }
.streettcsvg .dist { fill: none; stroke: var(--ink); stroke-width: 1.75; stroke-linejoin: round; }
.streettcsvg .lane { fill: var(--border); fill-opacity: 0.35; }
.streettcsvg .b34 { fill-opacity: 0.35; }
.streettcsvg .b50 { fill-opacity: 0.6; }
.streettcsvg .b64 { fill-opacity: 0.9; }
.streettcsvg line.tcnow { stroke: var(--ink2); stroke-width: 1; stroke-dasharray: 3 3; }
.streettcsvg .dot { fill: var(--ink); }
.streetsimkey .dist::before { border-top-color: var(--ink); }
.streetsimkey .wind::before, .streetsimkey .unk::before { width: 10px; height: 9px; border: 0; }
.streetsimkey .wind::before { background: var(--hue); opacity: 0.6; }
.streetsimkey .unk::before { background: repeating-linear-gradient(135deg, var(--hue) 0 1.5px, transparent 1.5px 4px); }
.streetsimkey .tcnow::before { border-top: 1.5px dashed var(--ink2); }
"""


# Taken into the desk's script at its /*STREETSTORMS*/ marker, after the
# street's, in the page's one scope: its names start with tc.
_JS = r"""
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
"""
