# Westerly Wind Events Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Track westerly wind events (Harrison and Vecchi 1997) day by day
from CCMP's near-real-time 10 m winds, on the dashboard, in latest.json, in
the report and as an alert.

**Architecture:** A vendored monthly base (`elnino/windclim.py`, built once
by `tools/vendor_winds.py` from CCMP v2.0) and one new feed (`wind_daily`,
180 days of 12-hourly analyses on 2.25-degree cells). `elnino/winds.py`
turns the feed into regional anomalies, smooths them, finds and classifies
the events and shapes the Hovmoller; `daily.wind_card` draws them with
`fields.hovmoller` and `daily._plot`, each gaining one optional parameter.

**Tech Stack:** Python 3.10+ standard library only; unittest; ERDDAP CSV.

**Spec:** `docs/superpowers/specs/2026-10-15-westerly-wind-events-design.md`

## Global Constraints

- Standard library only; Python 3.10 locally, 3.12 on CI.
- Repo files CRLF in the working tree (core.autocrlf true); edits keep it.
- Every number on the page comes from the data or the spec's measured facts.
- Text uses "El Nino" in ASCII where the module around it does.
- No new recurring trigger; no change to the classification or power index.

## Review Focus

1. A dataset whose last analysis is not 18Z (phase 00Z/12Z, or a gap inside
   the window): daily means and the filter must take any two analyses 12
   hours apart, and a gap must break runs, never bridge them.
2. An event under way at the window's end: the latest analysis is not
   smoothed; the event's day count and "under way" must agree with the
   smoothed series, and building runs must never be counted.
3. A feed that fails: its cached copy serves, the card's chip saying how far
   behind it is past four days; with no copy, or one with no value in any
   region, the card disappears, nothing else moves, and the JSON says none.
4. Overlap chains (W with C with E): each event counts as the strongest it
   overlaps, never as a weaker one.
5. A latest day long past (PIFSC stalled): the card says how far behind.

---

### Task 1: The vendored base

**Files:** Create `tools/vendor_winds.py`, generated `elnino/windclim.py`;
test `tests/test_winds.py` (class TestBase).

**Interfaces:**
- Produces `windclim.LATS: tuple[float, ...]` (14, -14.625..14.625 by 2.25),
  `windclim.LONS` (72, 120.125..279.875 by 2.25), `windclim.BASE = "1991-2018"`,
  `windclim.PRODUCT`, `windclim.MONTHLY[m][i][j] -> float | None` (m 0-11).

- [ ] Write TestBase: axes are the feed's cells; 12 months of 14 rows of 72;
  a known cell's January mean is easterly (-1.125S 165.125E within -6..+2);
  the parse of a block with `_` gives None. Run: FAIL (no module).
- [ ] Write the tool (one request per year of `ccmp-monthly-v2-0`, means by
  calendar month over the 28 years, `_` where a year lacks a value) and run it.
- [ ] Run TestBase: PASS. Commit.

### Task 2: The events

**Files:** Create `elnino/winds.py`; tests in `tests/test_winds.py`.

**Interfaces:**
- `Region(key, name, south, north, west, east)`; `.holds(lat, lon)`,
  `.span` ("155E-180"); `REGIONS` (NW, N, NE, W, C, E, S, SE); `EQUATORIAL`.
- `neighbours(a: Region, b: Region) -> bool`.
- `read(text) -> list[tuple[datetime, dict[tuple[float, float], float]]]`.
- `climate(when: datetime) -> list[list[float | None]]` on windclim's axes.
- `Event` (region, first, last, samples, centre, peak, point_peak, point,
  measure, ongoing, from_start, overlaps, counted_as; `.days`),
  `Building(region, since, samples, latest)`,
  `Winds(times, smoothed, daily, events, building, hovmoller, first, last)`.
- `analyse(text) -> Winds`.

- [ ] Tests first: regions and neighbours; interpolation; regional means
  weighted and refused under three quarters; the filter and its half power;
  runs of 6 and 5, strictly above 2, a gap; centre, peaks, point, measure;
  under way, from the start, building; overlaps and chains; the band and its
  rows; analyse on a synthetic feed. Run: FAIL.
- [ ] Implement. Run: PASS. Commit.

### Task 3: The feed and the run

**Files:** Modify `elnino/sources.py`, `elnino/grids.py`, `elnino/pipeline.py`.

**Interfaces:** `sources.CCMP_NRT`, `sources.SOURCES_BY_KEY["wind_daily"]`;
`grids.SpatialState.winds: winds.Winds | None`.

- [ ] Tests first: the query asks the base's cells and 360 analyses every
  other one back from the latest; tier spatial; not archived; 50 feeds; the
  run builds `winds`; a broken answer is a note and costs only itself.
  Run: FAIL.
- [ ] Implement. Run: PASS. Commit.

### Task 4: The card

**Files:** Modify `elnino/fields.py`, `elnino/daily.py`, `elnino/dashboard.py`.

**Interfaces:** `fields.hovmoller(..., outlines=(), months=fields.QUARTERS)`
with `outlines` of `(x0, x1, row0, row1, label)`; `daily._plot(..., bands=())`
with `bands` of `(first: date, last: date, colour)`; `daily.WINDS`;
`daily.wind_card(winds) -> str`.

- [ ] Tests first: outlines and month ticks drawn; bands shaded; the card's
  lines, mark, bands, hovers, caption (under way, latest, none, building,
  definition, base, TAO, monthly forcing), table, behind chip, no card under
  two days; the dashboard places it after the SOI's. Run: FAIL.
- [ ] Implement. Run: PASS. Commit.

### Task 5: JSON, report, alert

**Files:** Modify `elnino/dashboard.py`, `elnino/report.py`, `elnino/alerts.py`,
`elnino/pipeline.py`.

- [ ] Tests first: schema 12 and `spatial.wind_events`; None without the
  feed; the report's events and note; the INFO alert for an equatorial event
  under way, none otherwise. Run: FAIL.
- [ ] Implement. Run: PASS. Commit.

### Task 6: README and the whole

- [ ] README: feed row, the card, the method, the base and its checks, the
  schema, the test count. Full suite in batches; an offline build with a
  scratch copy of the live feed; a browser look at the card. Commit.
