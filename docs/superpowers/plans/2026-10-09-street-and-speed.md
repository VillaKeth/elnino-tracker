# Street View and Speed Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The figure drops the reader into Street View with what El Niño does to
that street beside it, and every page loads its unchanging code and data once.

**Architecture:** A new `elnino/street.py` owns the stage, the card and their
payload, taken into the desk's script at a `/*STREET*/` marker as then-and-now
is; the card computes the atlas composite at the point in the browser from
NASA POWER and Open-Meteo. A new `elnino/assets.py` writes content-addressed
script files that pages name; `fields.draw_cells` draws large regular grids as
indexed PNGs written by a new `elnino/png.py`.

**Tech Stack:** Python 3 standard library; plain ES5-style browser JavaScript
in the page (no libraries); node for the JS tests; headless Chrome for checks.

**Spec:** `docs/superpowers/specs/2026-10-09-street-and-speed-design.md`

## Global Constraints

- Standard library only in Python; no build step; pages work served and from a file.
- No request to Google, NASA or Open-Meteo before the reader asks (a drop, a button).
- Open-Meteo's link text "Weather data by Open-Meteo.com", linked, wherever its data shows.
- Google's tiles never drawn in the page; its embed and documented Maps URLs only.
- Page text in the site's voice: plain sentences, units always, signs on anomalies.
- Every new JS function reachable by an existing node harness is added to that harness's list.
- Tests: `python <batches.py> <logdir> 8` all green; README test count updated.

## Review Focus

- A drop where Google has no panorama: the stage still works (minimap, card, Exit); the reader is told why it is grey.
- A point where POWER's neutral rainfall is near zero (coastal desert): rain shown in mm/day, never a 5000% share.
- A season with fewer than 3 events or 6 neutral years: said, not drawn as a signal.
- Months still under way in the RONI record, and the ongoing event: excluded exactly as the atlas excludes them.
- A run taken in place, or the page loaded again, while the stage is open: stage and card survive without refetching.

---

### Task 1: The street payload

**Files:** Create `elnino/street.py`; modify `elnino/stormdesk.py` (payload `data["street"]`); test `tests/test_street.py`.

**Produces:** `street.payload(state) -> dict` with
`index` (name), `months` (`{"from": "YYYY-MM", "values": [one decimal or null]}`, RONI by centre month from 1979),
`warm` 1.0, `neutral` 0.5, `min_events` 3, `min_years` 6, `t975` (list, df 1..30),
`seasons` (12 running seasons as `[label, [[dy, month] x3]]`, tag = year of the middle month),
`ahead` (the standard season the map calls next, e.g. "DJF").

- [ ] Write tests: values are RONI as CPC prints it (classify.displayed); a gap month is null; seasons DJF and NDJ offsets; t975 matches the composite tool's table; constants equal `tools/vendor_composite.py`'s.
- [ ] Run, watch fail; implement; run, pass.

### Task 2: The record at a point (JS)

**Files:** `elnino/street.py` (`_JS`); tests `tests/test_street.py` (node harness).

**Produces (JS):** `powerMonths(json) -> {first: "YYYY-MM", p: [...], t: [...]}` (null for -999, month 13 dropped);
`powerFill(months, dailyJson)` (complete months from daily, a month needs 25 days);
`phaseOf(y, m)`; `streetComposite(rec, seasonIndex) -> {usable, events: [{tag, p, t}], base: {p, t}, diff: {p, t}, tstat: {p, t}, crit, share}`;
`streetYear(rec)` (all 12); `streetLatest(rec)` (last complete season vs its neutral mean).

- [ ] Tests (node): Welch t against a hand computation; DJF December tagged to the next year, NDJ January to the previous; ongoing-event months left out; under 3 events unusable; share withheld under 0.1 mm/day; a POWER fill value is a gap, not a zero.
- [ ] Watch fail; implement; pass.

### Task 3: The card (JS + markup)

**Files:** `elnino/street.py`; `elnino/stormdesk.py` (Here writes the card's box; showHere keeps it).

**Produces (JS):** `streetCard(lon, lat, auto)`; `streetCardHtml(state)`; `streetSentence(state)`; fetchers `streetGet(kind, lon, lat)` with session cache; `seasonalRows(json)`; `weatherWords(code)`.

- [ ] Tests (node): the sentence for a wet-signal point, a no-signal point, a forecast-only point; seasonal share vs mm rule; the WMO words; the cache key rounds to 0.01 degrees; a failed source shows Retry and the others still show.
- [ ] Watch fail; implement; pass.

### Task 4: The stage

**Files:** `elnino/street.py` (markup, CSS, JS); `elnino/thennow.py` (figure label, drop target, then bar's Street View); `elnino/stormdesk.py` (stage markup in #map, `/*STREET*/` marker, Here buttons, tap while armed, hash, keep/restore, API, Esc).

**Produces (JS):** `streetEnter(lon, lat, label, opts)`, `streetLeave()`, `streetView()`, `miniTiles(lon, lat, z, w, h)`, `miniPoint(x, y)`, `figureLand(lon, lat)`.

- [ ] Tests (node): enter sets Here and the stage, leave puts the map on the point; then-and-now and street exclusive, dates kept across; the minimap's tiles cover its box and a tap at its centre is the point; `#street=` parsed and refused when malformed; keep/restore carry the street; Esc leaves.
- [ ] Watch fail; implement; pass.

### Task 5: Street, checked in a browser

- [ ] Offline build, served Pages-like; drag the figure onto Lima, Jakarta, the open Pacific: stage, iframe, minimap tiles, card numbers from the live APIs, no console errors; 390 px phone; then-and-now round trip; screenshots looked at.

### Task 6: Assets

**Files:** Create `elnino/assets.py`; modify `elnino/stormdesk.py`, `elnino/atlasview.py`, `elnino/dashboard.py`, `elnino/live.py`, `track.py`, `publish.py`; tests in `tests/test_tracker.py`, `tests/test_live.py`.

**Produces:** `assets.Asset(name, text)` with `.file` (`name.<sha10>.js`) and `.tag()`; `assets.page_assets(html) -> list[str]`; `assets.write(out_dir, used)` (writes, prunes stale `name.<hex10>.js`); builders memoized per name.

- [ ] Tests: names change with content only; a page names exactly its assets and they exist after a run; stale files pruned and others kept; publish copies a page's assets and refuses a missing one; the desk's take loads instead when assets differ; pages still open from a file (script src relative).
- [ ] Watch fail; implement; pass.

### Task 7: Maps as images

**Files:** Create `elnino/png.py`; modify `elnino/fields.py`, `elnino/dashboard.py` (CSS for theme images).

**Produces:** `png.indexed(width, height, rows, palette, transparent) -> bytes`; `fields.draw_cells` raster branch.

- [ ] Tests: PNG decodes (zlib) to the classes `ramp.index` gives each cell; None transparent; north-up and south-up grids land the right way; irregular or small grids stay vector; both themes present.
- [ ] Watch fail; implement; pass.

### Task 8: Measure, document, review, ship

- [ ] perf probe on the build before and after; README (street, card, sources, assets, test count); full suite; final whole-branch review on the most capable model; fixes; snapshot push; live check.
