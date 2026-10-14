# Hurricanes on the Street Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The street stage says what live tropical cyclones mean for the point, replays a live forecast or a past storm over Google's panorama, and counts the storms since 1950 by El Niño phase.

**Architecture:** A new module, `elnino/streetstorms.py`, holds the stage's storm panel: its markup, CSS, payload (`D.tc`), the tracks asset and its JS (taken into the desk's script at a new `/*STREETSTORMS*/` marker, sharing the desk's closure as street.py's does). `cyclones.hurdat_tracks` parses HURDAT2's tracks; `assets.py` gains a lazily loaded form; `street.py` gives the panel the chip's place and shares the rain canvas.

**Tech Stack:** Python 3.10 (local) / 3.12 (CI), standard library only; page JS in ES5 style inside the desk's closure; node for the JS tests; Playwright (Chrome, Firefox, WebKit) for the browser checks.

**Spec:** `docs/superpowers/specs/2026-10-14-hurricanes-on-the-street-design.md`

## Global Constraints

- Nothing of the page sits on Google's logo or terms: the canvas stays clear of the panorama's bottom 40 px and takes no pointer; no Google API, key or tile is used.
- Every time is UTC, written by the desk's `utc(ms)` ("18 Oct 09:00 UTC").
- Official values pass through as issued; anything worked out here says so in the method text.
- Local Python is 3.10: no nested same-quote f-strings.
- The page works opened as a file: the tracks load as a classic script.
- JS names in the new module start with `tc` (`tcOpen`, `TC_SPEEDS`), none shared with the desk's, the map's, then-and-now's or the street's.
- Comments and words follow the codebase's voice: plain, exact, British spelling of the page's own words.

## Review Focus

1. A point with no HURDAT2 storm nearby (Manila, Sydney): the history must say the record does not cover it, not "no storms".
2. A run taken in place while the panel plays a live forecast whose storm has dissipated: the panel falls back without throwing.
3. The tracks asset failing to load (offline, a portal page): the live part and live replay still work, Retry reloads.
4. A best track crossing the date line (EP storms into the west Pacific): closest approach and hourly path stay continuous.
5. Opening the El Niño replay while the storm replay plays (and back): one frame loop, one rain, the chip's head right.

Each has its test in the task that owns the code (Tasks 4, 5, 3, 1 and 4, 5).

---

### Task 1: HURDAT2 tracks

**Files:**
- Modify: `elnino/cyclones.py` (after `hurdat_seasons`; `CycloneState`; `build`)
- Test: `tests/test_streetstorms.py` (new)

**Interfaces:**
- Produces: `cyclones.BestFix(when: datetime, lat: float, lon: float, wind: int | None, status: str, radii: tuple | None)`; `cyclones.BestTrack(id: str, name: str, fixes: tuple)` with `.year` and `.peak`; `cyclones.hurdat_tracks(text: str, first: int = 1950) -> list[BestTrack]`; `CycloneState.tracks: dict[str, tuple[BestTrack, ...]]` (keys "AL", "EP") and `CycloneState.track_files: dict[str, str]`.

- [ ] **Step 1: Write the failing tests** (`TestHurdatTracks`): a two-storm Atlantic sample and a Pacific one, written as HURDAT2 writes them:
  - fixes read with time, position (W negative, E positive), wind, status; `-99` wind is None; a line with radii gives 12 ints, `-999` None; a line with no radius known gives `radii=None`.
  - the 1969 line `19690929, 0600,  , EX, 63.3N    7.5E,  70, -999, ...` reads as 63.3N 7.5E 70 kt.
  - a landfall record at `1630` keeps its minutes.
  - storms before `first` are skipped; a header's count is not trusted (an extra line still read, a missing one not looked for).
  - an unreadable line is skipped, not fatal.
  - `build()` on fetched AL and EP text fills `state.tracks` and `state.track_files` with the filenames from the index.
- [ ] **Step 2: Run, watch them fail** — `python -m pytest tests/test_streetstorms.py -q` → AttributeError: module 'elnino.cyclones' has no attribute 'hurdat_tracks'.
- [ ] **Step 3: Implement**:

```python
HURDAT_FIX = re.compile(
    r"^\s*(\d{8})\s*,\s*(\d{4})\s*,\s*([A-Z]?)\s*,\s*([A-Z]{2})\s*,"
    r"\s*(\d{1,2}\.\d)([NS])\s*,?\s*(\d{1,3}\.\d)([EW])\s*,(.*)$")
```
  The rest of the line split on commas: wind, pressure, then twelve radii and the radius of maximum wind; a radius is None for a negative value; `radii` None when none of the twelve is known or the line has fewer than fourteen numbers.
- [ ] **Step 4: Run, watch them pass.**
- [ ] **Step 5: Commit** "Read HURDAT2's tracks, not only its seasons".

### Task 2: The tracks asset and its lazy naming form

**Files:**
- Modify: `elnino/assets.py` (lazy form), `elnino/live.py` (`lazyOf`, `sameCode`), `elnino/stormdesk.py` (page names it; `D.tc`)
- Create: `elnino/streetstorms.py` (constants, `tracks_payload`, `asset`, `payload`)
- Test: `tests/test_streetstorms.py`, `tests/test_assets.py`, `tests/test_live.py`

**Interfaces:**
- Consumes: Task 1's `BestTrack`, `state.cyclones.tracks`, `state.cyclones.track_files`.
- Produces: `Asset.lazy_tag() -> str` (`<link rel="elnino-lazy" href="assets/<file>">`); `assets.lazy_tags(items) -> str`; `assets.page_assets(html)` returns both forms in page order; `streetstorms.tracks_payload(state) -> dict | None` = `{"first": 1950, "last": <year>, "files": {"AL": ..., "EP": ...}, "statuses": [...], "storms": [[id, name, "YYYYMMDDHHMM", rows], ...]}`, a row `[minutes since the last fix (0 first), lat10 change (absolute first), lon10 change unwrapped (absolute first), wind|null, status index, *12 radii (null unknown) only when any is known]`; `streetstorms.asset(state) -> Asset | None` (`assets.data("tracks", ...)`, one per tracks object); `streetstorms.payload(state) -> dict` = `{"aso": {"from": 1950, "values": [...]}, "warm": 0.5, "cool": -0.5, "radii_nm": [50, 100, 200], "radius_nm": 100, "speeds": [3, 6, 12], "near_km": 1000, "inflow": 20, "first": 1950}`.

- [ ] **Step 1: Failing tests**:
  - `tracks_payload` on Task 1's sample: storms under 34 kt dropped, rows decode (in Python, by summing) back to every fix to a tenth of a degree, a date-line crosser's longitude continuous (179.5E then 179.5W is +10 tenths, not -3590), radii only on rows that know one; None without tracks.
  - `payload` gives RONI's ASO values from 1950 on, null for a year without one.
  - `page_assets` finds a script and a lazy link in page order; `write` writes and `prune` keeps a lazy file; `publish._read_assets` reads one.
  - the desk page names the tracks with `lazy_tag` and never as a script; `D.tc` is in its data.
  - the follower (`live.SCRIPT`) under node: `sameCode` is false for a page whose lazy link differs, true when only the run differs; `keepAssets` posts scripts only.
- [ ] **Step 2: Run, watch them fail.**
- [ ] **Step 3: Implement.** `_TAG` becomes one pattern with two alternatives; `page_assets` flattens the matches in order. `live.js`: `function lazyOf(doc)` over `link[rel="elnino-lazy"]`, `sameCode` compares it too. `stormdesk.page`: `{assets.lazy_tags(_later(state))}` after the script tags; `data["tc"] = streetstorms.payload(state)`.
- [ ] **Step 4: Pass.** Whole suite green.
- [ ] **Step 5: Commit** "Name the storm tracks as an asset loaded when asked".

### Task 3: The stage's storm line, button and panel

**Files:**
- Modify: `elnino/streetstorms.py` (`chip_line()`, `button()`, `panel()`, `css()`, `_JS` part 1), `elnino/street.py` (`map_parts`, `css`, `_JS` hooks: `streetChip`, `streetEnter`, `streetLeave`, `streetDraw`, `simOpen`, `simDraw`, Esc), `elnino/stormdesk.py` (`script()` marker, CSS, `takeRun`, the API)
- Test: `tests/test_streetstorms.py` (node, the faked DOM of `test_thennow._run`, extended to take the new JS)

**Interfaces:**
- Consumes: the desk's `hereFor`, `nearHere`, `stormHere`, `utc`, `soon`, `kms`, `COMPASS8`, `STORMS`, `BYID`.
- Produces: JS `tcWord(lon, lat) -> "Hurricanes"|"Typhoons"|"Cyclones"`; `tcNear(lon, lat) -> [hereFor rows]`; `tcThreatHtml(rows) -> string`; `tcOpen() -> bool`, `tcClose(leaving) -> bool`, `tcDraw()`, `tcMoved()`, `tcRetake()`; `S.tc` = `{radius, speed, key, k, pos, playing, frame, last, seeking, touch, geo, rain, past, why, loading}`.

- [ ] **Step 1: Failing tests**:
  - `tcWord` at Miami, Manila, Mumbai, Darwin, Honolulu, Dublin.
  - the chip's line at Manzanillo on the live fixture (Trudy's arrival "04:00"-style hour from `hereFor`), at most two storms nearest first, hidden with none near and while a panel is open.
  - the button reads `tcWord`'s word; pressing it opens the panel in the chip's place (`#street-tc` shown, chip head and sentence hidden, stage class `tcon`), focus to the panel; Back closes it and returns focus to the button.
  - opening the El Niño replay closes the storm panel and the reverse; Esc closes the open panel, then leaves.
  - `streetLeave` closes it; `streetEnter` elsewhere keeps it open and rewrites it for the new point.
  - a run taken in place (`refresh` with a run without the storm) rewrites the line and the panel without throwing.
- [ ] **Step 2: Fail.** **Step 3: Implement.** **Step 4: Pass, suite green.**
- [ ] **Step 5: Commit** "Say on the street which storms threaten it, and open a storm panel there".

### Task 4: Since 1950

**Files:**
- Modify: `elnino/streetstorms.py` (`_JS` part 2)
- Test: `tests/test_streetstorms.py`

**Interfaces:**
- Consumes: `D.tc`, the lazy link, `ELNINO.tracks`.
- Produces: JS `tcLater(name) -> href|null`; `tcTracks() -> Promise<decoded>`; `tcDecode(raw) -> [{id, name, year, fixes: [{t, lat, lon, wind, status, radii}], box}]`; `tcRound(v)` (half to even, as Python); `tcClosest(track, lon, lat) -> {km, t, wind, status}`; `tcPhase(year) -> "warm"|"cool"|"neutral"|null`; `tcBinomial(e, l, se, sl) -> p|null`; `tcPast(tracks, lon, lat, km) -> {rows, counts, p, covered, radius_km}`; `tcPastHtml(past)`, `tcPastTable(past)`.

- [ ] **Step 1: Failing tests**:
  - `tcDecode` on Task 2's payload gives Task 1's fixes back.
  - `tcClosest` on a straight synthetic track (closest point mid-segment, wind interpolated), across the date line, and one fix only.
  - `tcBinomial(3, 8, 21, 21)` = 464/2048; against `math.comb` sums for (0, 5, 10, 30), (12, 2, 20, 25), (0, 0, ...) → null.
  - `tcPast` on a synthetic record: counting at 34 kt or more there, any status, by phase, seasons per phase over first..last with an ASO value; outside coverage when no storm within 1,000 km.
  - on the real record (`hurdat_*.cache` fixtures copied to `tests/fixtures/`? no: built from the raw cache when present, skipped otherwise), Manhattan, Miami and Cabo San Lucas at 100 n mi agree with an independent Python haversine computation of the same rule.
  - the panel loads the tracks once, shows "Reading the storm tracks…" then the history; a failed load shows the reason and Retry, which loads again; the radius choice recounts.
- [ ] **Step 2: Fail.** **Step 3: Implement.** **Step 4: Pass.**
- [ ] **Step 5: Commit** "Count the storms that passed each street since 1950, by El Niño phase".

### Task 5: The replay

**Files:**
- Modify: `elnino/streetstorms.py` (`_JS` part 3), `elnino/street.py` (`rainNow`, `rainSet`, `rainPaint`'s slant and gusts)
- Test: `tests/test_streetstorms.py`, `tests/test_street.py` (the rain tests stay green)

**Interfaces:**
- Consumes: Task 3's panel, Task 4's tracks; the desk's `insideAt`, `bearing`, `km`, `THRESHOLDS`.
- Produces: JS `tcHourly(fixes) -> [{t, lat, lon, wind, radii, status}]`; `tcBand(p, lon, lat) -> {kt, unknown, inside}`; `tcFrom(p, lon, lat) -> degrees|null`; `tcChoices(lon, lat) -> [{key, label}]`; `tcRun(key) -> run`; `tcPlay(on)`, `tcFrame()`, `tcTick(ts)`, `tcHour(k)`, `tcSeek(x)`, `tcSeekHour(k)`, `tcSeekFrom(e)`, `tcHead()`; `tcChart(run, w) -> {svg, geo}`; `tcRead(run, k)`, `tcWords(run)`, `tcKey(run)`, `tcHours(run)`, `tcLevel(band) -> rain level`, `tcBadge(run, k)`; street.py's `rainNow()`, `rainSet(holder, level, when)`.

- [ ] **Step 1: Failing tests**:
  - `tcHourly` equals `exposure.timeline` on the same fixes (radii, wind and position, the .5 cases rounded half to even).
  - `tcBand` per hour of Trudy's forecast at Manzanillo: arrival hours equal `hereFor`'s; 64 kt "not forecast" past 72 h.
  - `tcFrom` north and south of the equator, east and west of the centre; null within 10 km.
  - the choices: live first, then past storms since 2004 newest first; the default the live one, else the strongest band.
  - Play steps hours at the speed chosen, stops at the end; the slider and the chart seek; frames held back count a quarter second at most.
  - the canvas draws the band (no drops under 34 kt, 160/260/380 above), the badge names the hour; still under reduced motion; one frame loop when switching panels.
  - the chart's strips, hatching for "not forecast", the now line; the words and the hour-by-hour table.
- [ ] **Step 2: Fail.** **Step 3: Implement.** **Step 4: Pass, suite green.**
- [ ] **Step 5: Commit** "Replay a storm's wind over the street: a live forecast or a past storm".

### Task 6: Naming a point by the people in a place

**Files:**
- Modify: `elnino/stormdesk.py` (`placeLabel`)
- Test: `tests/test_streetstorms.py` (or the desk's tests)

- [ ] **Step 1: Failing test:** Staten Island (40.58N 74.15W) is "New York, New York, United States of America"; central Newark is Newark; a point 5 km from a town of 10,000 is "5 km from" it; open sea is its position.
- [ ] **Step 2: Fail. Step 3: Implement** `placeReach(pop) = clamp(sqrt(pop / (π·2000)), 1.5, 30)`. **Step 4: Pass. Step 5: Commit** "Name a point by the town whose people reach it".

### Task 7: Words, docs and the browsers

**Files:** `README.md`, `elnino/stormdesk.py` (`METHODS`?), the method text in the panel.

- [ ] README: the stage's storm line, the panel, the replay, the history, the asset; the feed table's HURDAT2 row says the tracks are used; test count.
- [ ] Build the site offline from the scratch cache with the live storms.json's storms (perfbuild), load it in Chrome, Firefox and WebKit: Manzanillo (live line, forecast replay), Manhattan (history, Sandy), Manila (coverage), phone width, dark, reduced motion; screenshots looked at.
- [ ] Final whole-branch review by a fresh reviewer; fix everything; merge; push the snapshot; live check.
