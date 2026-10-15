# The Dipole and the SOI Day by Day Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Indian Ocean Dipole and the SOI day by day on the dashboard, in `latest.json` (schema 11) and in the report, from OISST's daily analyses and LongPaddock's daily SOI.

**Architecture:** Three feeds in `sources.py`; the poles reuse `grids.daily_box_means` with `IOD_BOXES` and gain the DMI in `grids.dipole`; the SOI file is parsed by `parsers.parse_daily_soi`, which works out the 30- and 90-day SOI. A new module, `elnino/daily.py`, takes the Nino card's plot out of `fields.py`, generalised over a `Chart`, and holds the three day-by-day cards.

**Tech Stack:** Python 3.10 locally, 3.12 in CI, standard library only; pytest.

**Spec:** `docs/superpowers/specs/2026-10-14-dipole-and-soi-day-by-day-design.md`

## Global Constraints

- The Nino card's markup is unchanged byte for byte by the move to `daily.py`.
- Text on the page and in the report spells Nino and Nina in ASCII, as the Nino card does; values are written `{:+.2f}` (degC) or `{:+.1f}` (SOI).
- Every source file is CRLF; edits go through `$W/r25/tools/ed.py` scripts, dry-run first.
- Local Python is 3.10: no nested same-quote f-strings.
- Never run `track.py`; live checks fetch into a scratch directory.
- Comments and words follow the codebase's voice: plain, exact, British spelling.

## Review Focus

1. LongPaddock's latest day missing or a fill value: the 30- and 90-day lines must not vanish for a month (the 3/5 rule tolerates it).
2. A run where only the dipole's preliminary arrives: the card stands on it alone, shaded.
3. A pole with no ocean cell on a day (all NaN): the day has no DMI and breaks the line, never a DMI of one pole.
4. The SOI file served as an HTML error page with status 200: the header check refuses it and the run says so.
5. A day of the year past the year's end (366 in a common year): left out, not wrapped into the next year.

---

### Task 1: The dipole's feeds, poles and DMI

**Files:** Modify `elnino/sources.py`, `elnino/grids.py`, `elnino/pipeline.py`; Test `tests/test_realtime.py` (feed tests) and new `tests/test_daily.py`.

**Interfaces:**
- Produces: `sources._IOD_CELLS = "[(-9.875):2:(9.625)][(50.125):2:(109.625)]"`; sources `iod_daily`, `iod_daily_recent`; `grids.IOD_BOXES = (Box("west", "West pole", 50.0, 70.0, -10.0, 10.0), Box("east", "East pole", 90.0, 110.0, -10.0, 0.0))`; `grids.dipole(days: list[BoxDay]) -> list[BoxDay]` adding `means["dmi"]`; `SpatialState.iod_daily: tuple[BoxDay, ...]`, `SpatialState.iod_revision: dict[str, Revision]`.

- [ ] Step 1: tests. In `test_realtime.py`: the seconded set, the agency map (`"iod"`), the not-archived set and the new-feed list gain the two keys; the NCEI-windows test covers `iod_daily_recent`. In `test_daily.py`, `TestDipole`:
  - `test_the_poles_are_asked_for_on_half_degree_cells_holding_both`: queries `anom[last-89:1:last][(0.0)]` + cells and `anom[last-27:1:last][(0.0)]` + cells, final on `OISST_FINAL`, recent on `OISST_NRT`.
  - `test_each_pole_is_the_cosine_weighted_mean_of_its_cells_and_the_dmi_their_difference`: a CSV over the 40 x 120 cells, value 1.0 in the west pole, 0.25 in the east, 9.0 between them; `dipole(daily_box_means(text, grids.IOD_BOXES))` gives west 1.0, east 0.25, dmi 0.75, and the 70-90E cells weigh nothing.
  - `test_a_day_with_one_pole_has_no_dmi`.
  - `test_the_run_splices_the_poles_and_measures_what_the_final_changed`: `build_spatial` with both feeds; days final then preliminary; `iod_revision["dmi"]` measured.
  - `test_the_dipole_stands_on_the_preliminary_alone` and `test_a_broken_dipole_answer_costs_only_itself` (note "daily dipole").
  - `test_the_dipole_alone_makes_a_spatial_section`.
- [ ] Step 2: run `python -m pytest tests/test_daily.py tests/test_realtime.py -q`; expect failures on the missing names and sets.
- [ ] Step 3: implement as the Interfaces say; `build_spatial` takes both sets of boxes through one local helper, `daily(key, label, boxes) -> (record, recent)`, the Nino block's note labels unchanged.
- [ ] Step 4: rerun; all pass.
- [ ] Step 5: commit "Track the Indian Ocean Dipole day by day from OISST".

### Task 2: The daily SOI

**Files:** Modify `elnino/sources.py`, `elnino/parsers.py`, `elnino/pipeline.py`; Test `tests/test_daily.py`.

**Interfaces:**
- Produces: source `soi_daily` (tier `atmosphere`, `archive=False`, URL `sources.LONGPADDOCK_SOI`); `parsers.SoiDay(day: str, tahiti: float, darwin: float, soi: float, soi30: float | None = None, soi90: float | None = None)`; `parsers.parse_daily_soi(text: str) -> list[SoiDay]`; `series["soi_daily"]`.

- [ ] Step 1: tests, `TestDailySoi`: the header refused when absent (an HTML page); rows to days by year and day of the year (2024's 366th is 31 December; a common year's 366th left out); the -999.9 fill left out; a day given again left out, the first standing; the 30-day mean of the days; a window lacking six days, or four in a row, has none, and one lacking five with three in a row has one; the source's address, tier and archive flag; `parse_all` puts the days in `series["soi_daily"]` and a broken file in `warnings`.
- [ ] Step 2: run; expect failures.
- [ ] Step 3: implement (`PRESSURE_RANGE = (870.0, 1090.0)`, `MOST_MISSING, MOST_IN_A_ROW = 5, 3`, `_window_mean(by_day, last, length)`).
- [ ] Step 4: rerun; all pass.
- [ ] Step 5: commit "Read the Bureau's SOI day by day from LongPaddock".

### Task 3: `daily.py`, the Nino card's plot generalised

**Files:** Create `elnino/daily.py`; Modify `elnino/fields.py` (the day-by-day section leaves), `elnino/dashboard.py` (call), `tests/test_realtime.py` (six calls).

**Interfaces:**
- Produces: `daily.Line(key, name, colour, width=2.0, opacity=1.0)`, `daily.Mark(value, label, colour)`, `daily.Chart(lines, marks, unit, digits, floor, missing="not analysed")` with `Chart.fmt(value)`; `daily._plot(values: dict[date, dict[str, float]], chart, preliminary=frozenset(), dots=(), notes=None) -> Plot`; `daily.NINO`; `daily.nino_card(days, weeks, revision=None)`.

- [ ] Step 1: before the move, write each of six Nino cards (with and without weeks, revision, a gap, preliminary days, an old latest day) to `$W/r39/golden/` from `fields.nino_daily_card`.
- [ ] Step 2: retarget `TestDailyCard`'s six calls to `daily.nino_card` and run them: they fail on the missing module. (The golden pages carry today's date in the behind-chip, so the byte comparison stays a scratch check.)
- [ ] Step 3: move and generalise; `fields.py` keeps `OISST_BASE`, `_behind`.
- [ ] Step 4: `TestDailyCard` passes; the scratch check compares all six pages byte for byte.
- [ ] Step 5: commit "Draw the days of any series with the Nino card's plot".

### Task 4: The dipole's and the SOI's cards

**Files:** Modify `elnino/daily.py`, `elnino/dashboard.py`; Test `tests/test_daily.py`, `tests/test_realtime.py` (`_realtime_fetch_all`, placement).

**Interfaces:**
- Produces: `daily.DIPOLE`, `daily.SOI`, `daily.SOI_DAYS = 120`, `daily.dipole_card(days, revision=None)`, `daily.soi_card(days)`.

- [ ] Step 1: tests, `TestDipoleCard`: id `iod-daily`; three lines in `--s1..--s3`; marks `positive IOD +0.4` and `negative IOD -0.4` drawn over the lines; preliminary shaded; hover `data-value="DMI +0.75 °C"` with the poles; the caption's latest DMI, week change, boxes, thresholds and base; the revision in the DMI with "higher"/"lower"; table columns; fewer than two days draw nothing. `TestSoiCard`: id `soi-daily`; 120 days of a longer record; the faint day line (`stroke-width="1"` and `opacity="0.5"`); marks `El Nino-like -7` and `La Nina-like +7`; hover with the pressures; caption's 30- and 90-day values; a day with no 30-day mean says `not worked out`; table of 120 rows latest first. Placement in the whole-run test: `iod-daily` after `nino-daily`, `soi-daily` after the Walker chart.
- [ ] Step 2: run; expect failures.
- [ ] Step 3: implement; place the cards.
- [ ] Step 4: rerun; all pass.
- [ ] Step 5: commit "Show the dipole and the SOI day by day".

### Task 5: `latest.json` schema 11 and the report

**Files:** Modify `elnino/dashboard.py`, `elnino/report.py`; Test `tests/test_realtime.py` (whole run), `tests/test_daily.py`.

- [ ] Step 1: tests: schema 11; `spatial.iod_daily` rows' keys `day, preliminary, west, east, dmi`; `spatial.iod_revision`; `atmosphere.soi_daily` the last 120 days with `day, tahiti, darwin, soi, soi30, soi90`; the report's dipole table after the Nino days and its SOI table in the atmosphere's section.
- [ ] Step 2: run; expect failures.
- [ ] Step 3: implement, the days' and revisions' JSON through one helper each, the Nino keys' output unchanged.
- [ ] Step 4: rerun; all pass.
- [ ] Step 5: commit "Give the dipole and the SOI day by day to the JSON and the report".

### Task 6: README and the whole suite

- [ ] Step 1: README: the feature rows, 49 feeds, the ERDDAP rows for the poles, LongPaddock's row, the traps and the 3/5 rule, schema 11, the tests list and count.
- [ ] Step 2: full suite (`timeout 590 python -m pytest -q`), output to `$W/r39/suite_*.txt`.
- [ ] Step 3: live smoke: the three feeds fetched into a scratch directory, the cards rendered, the numbers read.
- [ ] Step 4: commit "Describe the dipole and the SOI day by day".
