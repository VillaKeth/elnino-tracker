# Street Coverage and El Niño Replay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pick finds a street Google drove (the nearest named one), Next street
tries the others, and the stage replays a past El Niño's rain day by day on the
street, against neutral years and ECMWF's forecast.

**Architecture:** All in `elnino/street.py`: the payload's `ROADS` and a new
`days` source; the stage's markup (`map_parts`), its rules (`css`) and its
script (`_JS`), which gains the candidate list and Next street, POWER's daily
record read from CSV, the replay's model (pure functions), its panel in the
chip, and a canvas over the panorama for the rain.

**Tech Stack:** Python 3 standard library; plain ES5-style browser JavaScript;
node for the JS tests (the harness in `tests/test_thennow.py`); headless Chrome,
Playwright's Firefox and WebKit for checks.

**Spec:** `docs/superpowers/specs/2026-10-12-street-coverage-and-el-nino-replay-design.md`

## Global Constraints

- Standard library only in Python; no build step; pages work served and from a file.
- No source asked before the reader asks: OSRM on a pick, POWER's days only when the replay opens.
- OSRM once a second at most, credited as now; NASA POWER credited in its own words where its data shows.
- Nothing of the page covers Google's logo or terms; the rain canvas never takes a pointer.
- No name in the street's script is one of the page's (`TestStreetScript`).
- Every new JS function a node harness reaches is in reach of `_run` (it runs `street._JS` whole); page functions it calls are in `ENGINE`.
- Tests: `python <batches.py> <logdir> 8` all green; README test count updated.

## Review Focus

- OSRM's 100 waypoints all unnamed, or one name over and over, or names differing only in surrounding spaces: the candidates are distinct roads, the list is short and sane, and Next street is hidden when there is nothing else.
- A drop with no road within 5 km (open sea): the stage stays on the point, no Next street, the line says no street is within reach.
- The replay playing when Next street or the minimap moves the stage into another POWER cell: playback stops, the new point's record is asked, and an answer for a point since left is not shown.
- POWER's CSV with its columns in another order, `MO,DY` instead of `DOY`, fills of `-999` and `-999.0`, a blank last line, or an error page sent with 200: read right or refused, never a broken panel.
- A window across the new year with 29 February in it (December to May 2016): days, labels, totals and the neutral band right over windows of 182 and 183 days.

---

### Task 1: Next street

**Files:** `elnino/street.py` (`ROADS`, `map_parts`, `css`, `_JS`: `snapRoads`, `streetPick`, `streetEnter`, `streetDraw`, `streetNext`, `roadsLine`); `tests/test_street.py`.

**Produces:** `ROADS` ends `?number=100`. JS `SNAP_NAMED = 1000`, `SNAP_ROADS = 6`;
`snapRoads(lon, lat, reach) -> Promise<list|null>`, each entry
`{lon, lat, name, d, point}`; entry 0 is where the pick goes; `null` when OSRM
gave nothing usable within reach or 5 km. `S.street.roads`, `.road`, `.picked`
(`{lon, lat, label}`), set by `streetEnter(lon, lat, label, {roads, road, picked})`.
`streetNext() -> bool`. `roadsLine(st) -> string`; `roadDistance(m) -> "213 m" | "1.3 km"`.
Markup: `#street-next` (hidden), `#street-roads`.

- [ ] Tests: payload `roads` with `number=100`; the candidates for named and unnamed roads near and far, beyond 5 km, repeated and padded names, no answer; the label and Here of the road taken; Next street's order, wrap and its line; Next street hidden without a list and after an exact enter; the bar's markup and the note's words; the old snap tests brought to the new rule.
- [ ] Watch fail; implement; pass; suite.

### Task 2: POWER's days

**Files:** `elnino/street.py` (`SOURCES["days"]`, `_JS`: `streetFetch` text, `powerCsv`, `simGet`); tests.

**Produces:** `SOURCES["days"]` (CSV, `start=19810101&end={end}`). `streetFetch(url, wait, text)` resolves the body as text when `text`. `powerCsv(text) -> {from: "YYYY-MM-DD", p: [], t: []} | null` (daily from `from`, null for a fill or a day missing). `simGet(lon, lat) -> Promise<record>`, kept in memory for `SIM_POINTS = 3` points, one request a point at a time, failure in `SIM_WHY[key]`.

- [ ] Tests: the URL; `DOY` and `MO,DY` forms, column order, fills, gaps, blank lines, not-CSV; kept and let go after three points; one request for two asks; a failure's words.
- [ ] Watch fail; implement; pass; suite.

### Task 3: The replay's model

**Files:** `elnino/street.py` (`_JS`); tests.

**Produces:** `simWindow(start, year) -> {first, days, months, label}`;
`simRun(rec, start, year) -> run | null` with `{tag, label, p, t, cum, total, r20, wettest: {mm, day}, dry, tmean, missing}`;
`simYears(rec, start, nowMs) -> {events, neutral, now}` (events carry `peak`);
`simBand(runs) -> {mean, lo, hi}`; `simClimate(rec) -> [12 totals|null]`;
`simEcmwf(rows, start, clim, nowMs) -> {first, months, cum, total, base, label} | null`;
`simModel(rec, start, rows, nowMs) -> model`.

- [ ] Tests: windows and labels across the new year and in leap years; events, neutral years and the event under way by the index; measures (total, R20mm, wettest, longest dry spell, mean temperature, missing days); the 10th and 90th percentiles; the all-years climate; ECMWF's projection (covered months, the floor at zero, a window begun); a record too short.
- [ ] Watch fail; implement; pass; suite.

### Task 4: The replay's panel

**Files:** `elnino/street.py` (`map_parts`, `css`, `_JS`: `simOpen`, `simClose`, `simDraw`, `simDay`, `simPlay`, `simTick`, `simSeek`, `simWords`, `simChart`, `simTable`); `tests/test_thennow.py` (a frame clock in the prelude); tests.

**Produces:** chip button `#street-replay`; panel `#street-sim` in the chip; `S.sim`.

- [ ] Tests: opening asks POWER once and shows the panel in the chip's place; the choices (events newest first, the strongest chosen, window months); Play steps days at the speed chosen and stops at the end; the slider and the chart seek; the readout, the badge and the summary's words; the year-by-year table; failure and Retry; Back to the card, Exit and Esc close it; another point keeps it open and asks again; the chart's lines, labels and playhead.
- [ ] Watch fail; implement; pass; suite.

### Task 5: Rain over Street View

**Files:** `elnino/street.py` (`map_parts`, `css`, `_JS`: `rainLevel`, `rainSize`, `rainPaint`); tests.

**Produces:** `.streetview` holding `#street-pano`, `canvas#street-rain`, `#street-day`. `rainLevel(mm, t) -> {kind: "none"|"dry"|"rain"|"snow", drops, gloom}`.

- [ ] Tests: levels at the thresholds; snow at 0 °C; the canvas never takes a pointer and stops 40 px above the panorama's foot; drawn only while the replay is open; the loop stops on a dry day paused, on close and on leaving; reduced motion draws still.
- [ ] Watch fail; implement; pass; suite.

### Task 6: Docs and checks

**Files:** `README.md`; spec "Measured after".

- [ ] README: Street View's rule and Next street; the replay; the sources table; test count.
- [ ] Offline build; Chrome, Firefox and WebKit, desktop and phone: a Winter Haven drop to a named street, Next street, the replay played and seeked, rain drawn and Google's foot clear, no errors.
- [ ] Commit; final whole-branch review; fix pass; snapshot push; live check.
