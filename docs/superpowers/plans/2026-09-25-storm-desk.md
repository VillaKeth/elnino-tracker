# Storm Desk Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A touch-first storm page that zooms to the eye of every live storm on
live satellite imagery, shows every official formation outlook, tracks JTWC
basins beside NHC's, and gives each storm its official protective products and
an exposure table - served to a tablet from the tracker itself.

**Architecture:** Five new single-purpose modules (`kml`, `tcproducts`,
`jtwc`, `outlook`, `exposure`) feed the existing cyclone tier; a sixth
(`stormdesk`) renders `output/storms.html` and `output/storms.json`. The page
is vanilla JS on NASA GIBS Web Mercator tiles and discovers imagery times live.

**Tech Stack:** Python 3.10 standard library only; vanilla JS, inline SVG;
unittest; Playwright for browser checks.

**Spec:** `docs/superpowers/specs/2026-09-25-storm-desk-design.md`

**Execution:** inline in this session (the Agent tool is not permitted here).
Where this plan gives behaviour and exact assertions rather than full code, the
executor is the plan's author and holds the context; tests are still written
first and watched failing.

## Global Constraints

- Standard library only; Python 3.10.11; no CDN, no API key, no build step.
- Tests: `python -m unittest discover -s tests` from the repo root; all green
  before every commit (458 at start).
- Report stays pure ASCII, lines <= 78 columns; model strings ASCII
  ("degC", "kt"); the page converts through `svg.prose`.
- Page text wears text tokens, never series colours; legend for >= 2 series;
  a table for every chart or map layer; light and dark from tokens; categorical
  hues in fixed order; no dual axis.
- Official product colours kept for watches/warnings, surge and outlook
  chances, always beside a text label.
- Every product shows its issue time; derived numbers say how they were made.
- Commit messages end with
  `Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>`.
  Do not push.

## Review Focus

1. A storm or place either side of 180 degrees: interpolation, exposure,
   overlays and tile wrap must go the short way round, never across the world.
2. Southern hemisphere and Indian Ocean positions (`158S 0712E`): parsed with
   the right signs, drawn in the right place, labelled as JTWC's.
3. A product that is not issued (null link) versus one that failed to fetch:
   "none in effect" and "unavailable" are different statements.
4. Wind radii absent where the wind reaches the threshold (64 kt past 72 h):
   exposure says "not forecast", never "no hurricane-force wind".
5. The page with no network: tiles and the GIBS time query fail; the coast is
   drawn from the vendored copy and the page says imagery is unreachable,
   with zero console errors.

---

### Task 1: Binary-safe payload decoding

**Files:**
- Modify: `elnino/sources.py` (`_http_get`, new `decode_payload`)
- Test: `tests/test_tracker.py` (new `TestPayloadDecoding`)

**Interfaces:**
- Produces: `sources.decode_payload(payload: bytes, content_encoding: str | None = None) -> str`

- [ ] **Step 1: Write the failing tests**

```python
class TestPayloadDecoding(unittest.TestCase):
    def test_plain_text_passes_through(self):
        self.assertEqual(sources.decode_payload(b"abc\n"), "abc\n")

    def test_a_stored_gzip_is_unpacked(self):
        import gzip
        self.assertEqual(sources.decode_payload(gzip.compress(b"deck")), "deck")

    def test_a_kmz_arrives_as_its_kml_text(self):
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl54.png", b"\x89PNG")
            z.writestr("gtwo_atl.kml", "<kml>outlook</kml>")
        self.assertEqual(sources.decode_payload(buf.getvalue()), "<kml>outlook</kml>")

    def test_a_zip_without_kml_is_an_error_not_garbage(self):
        import io, zipfile
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("a.shp", b"\x00\x00")
        with self.assertRaises(ValueError):
            sources.decode_payload(buf.getvalue())
```

- [ ] **Step 2: Run to verify failure** - `python -m unittest tests.test_tracker.TestPayloadDecoding -v`; expected `AttributeError: ... no attribute 'decode_payload'`.
- [ ] **Step 3: Implement** `decode_payload`: gzip when the header says so or the magic is `1f 8b`; a zip (`PK\x03\x04`) returns the first member ending `.kml` (case-insensitive) decoded UTF-8, else `ValueError("zip carries no KML")`; otherwise UTF-8 with `errors="replace"`. `_http_get` calls it.
- [ ] **Step 4: Run to verify pass**, then the whole suite.
- [ ] **Step 5: Commit** `Fetch: read a KMZ as its KML text`.

### Task 2: KML reader

**Files:**
- Create: `elnino/kml.py`
- Test: `tests/test_tracker.py` (`TestKml`), fixtures `gtwo_pac.kml`, `ww_ep152026.kml`

**Interfaces:**
- Produces:
  - `kml.Placemark` (frozen): `name: str`, `style: str`, `description: str`,
    `data: dict[str, str]`, `points: tuple[tuple[float, float], ...]`,
    `lines: tuple[tuple[tuple[float, float], ...], ...]`,
    `polygons: tuple[tuple[tuple[float, float], ...], ...]` (outer rings), `folder: str`
  - `kml.placemarks(text: str) -> list[Placemark]` in document order
  - `kml.document_name(text: str) -> str`
  - `kml.simplify(ring, tolerance: float) -> tuple` (Douglas-Peucker, degrees)

- [ ] **Step 1: Failing tests**

```python
class TestKml(unittest.TestCase):
    def test_placemarks_keep_document_order_and_extended_data(self):
        marks = kml.placemarks(fixture("gtwo_pac.kml"))
        first = marks[0]
        self.assertEqual(first.style, "#3")
        self.assertEqual(first.data["2day_percentage"], "40%")
        self.assertEqual(first.data["7day_category"], "High")
        self.assertEqual(len(first.polygons), 1)
        point = marks[1]
        self.assertAlmostEqual(point.points[0][0], -92.689, places=3)
        self.assertAlmostEqual(point.points[0][1], 10.868, places=3)
        self.assertEqual(len(marks[2].lines), 1)

    def test_a_namespace_does_not_hide_anything(self):
        marks = kml.placemarks(fixture("ww_ep152026.kml"))
        self.assertIn("Hurricane Watch", {m.name for m in marks})
        self.assertTrue(all(m.data.get("atcfid") == "EP152026" for m in marks))

    def test_simplify_keeps_the_ends_and_drops_the_straight_middle(self):
        ring = ((0.0, 0.0), (1.0, 0.001), (2.0, 0.0), (2.0, 2.0), (0.0, 0.0))
        out = kml.simplify(ring, 0.01)
        self.assertEqual(out[0], ring[0]); self.assertEqual(out[-1], ring[-1])
        self.assertNotIn((1.0, 0.001), out)
```

- [ ] **Step 2: Verify failure** (`ImportError`).
- [ ] **Step 3: Implement** with `xml.etree.ElementTree`, stripping `{ns}` from every tag; coordinates split on whitespace, each `lon,lat[,alt]`; `folder` is the nearest enclosing `Folder/name`.
- [ ] **Step 4: Verify pass**, whole suite.
- [ ] **Step 5: Commit** `KML: placemarks, extended data, simplification`.

### Task 3: Wind radii on every ATCF fix

**Files:**
- Modify: `elnino/cyclones.py` (`Fix`, `parse_atcf`)
- Test: `tests/test_tracker.py` (`TestWindRadii`)

**Interfaces:**
- Produces: `Fix.radii: tuple = ()` as `((34, (ne, se, sw, nw)), (50, ...), (64, ...))`,
  sorted by threshold, nautical miles, `None` for an unreported quadrant;
  `Fix.radius(threshold) -> tuple | None`.

- [ ] **Step 1: Failing tests** (rows copied from today's `ep152026.fst`)

```python
FST = """\
EP, 15, 2026092512, 03, OFCL,  12, 167N, 1553W,  90,    0, HU,  34, NEQ,  100,   90,   80,  110,    0,    0,   0, 110,   0,    ,   0, ESB,  15,   5,
EP, 15, 2026092512, 03, OFCL,  12, 167N, 1553W,  90,    0, HU,  50, NEQ,   60,   50,   40,   50,    0,    0,   0, 110,   0,    ,   0, ESB,  15,   5,
EP, 15, 2026092512, 03, OFCL,  12, 167N, 1553W,  90,    0, HU,  64, NEQ,   40,   35,   25,   30,    0,    0,   0, 110,   0,    ,   0, ESB,  15,   5,
EP, 15, 2026092512, 03, OFCL,  96, 202N, 1643W, 100,    0, HU,  34, NEQ,  120,   90,   70,   90,    0,    0,   0, 120,   0,    ,   0, ESB, 320,   9,
EP, 15, 2026092512, 03, OFCL,  96, 202N, 1643W, 100,    0, HU,  50, NEQ,   50,   40,   30,   40,    0,    0,   0, 120,   0,    ,   0, ESB, 320,   9,
"""

class TestWindRadii(unittest.TestCase):
    def test_radii_rows_merge_onto_one_fix(self):
        fixes = cyclones.parse_atcf(FST)
        self.assertEqual(len(fixes), 2)
        self.assertEqual(fixes[0].radius(34), (100, 90, 80, 110))
        self.assertEqual(fixes[0].radius(64), (40, 35, 25, 30))

    def test_a_threshold_the_forecast_does_not_carry_is_absent(self):
        day4 = cyclones.parse_atcf(FST)[1]
        self.assertEqual(day4.radius(50), (50, 40, 30, 40))
        self.assertIsNone(day4.radius(64))

    def test_a_full_circle_radius_fills_all_four_quadrants(self):
        row = ("AL, 06, 2026092512,   , BEST,   0, 301N,  425W,  50, 1002, TS,"
               "  34, AAA,   60,    0,    0,    0, 1012,  150,  30,")
        self.assertEqual(cyclones.parse_atcf(row)[0].radius(34), (60, 60, 60, 60))

    def test_rebasing_keeps_the_radii(self):
        fix = cyclones.parse_atcf(FST)[0]
        moved = cyclones.rebase((fix,), "2026092518")[0]
        self.assertEqual(moved.radius(50), (60, 50, 40, 50))
```

- [ ] **Step 2: Verify failure** (`AttributeError: 'Fix' object has no attribute 'radius'`).
- [ ] **Step 3: Implement**: collect per `(stamp, tau, tech)` key the first row's scalar fields and every row's `(RAD, WINDCODE, RAD1..4)`; `NEQ` gives four quadrants, `AAA` repeats `RAD1`; a zero quadrant is 0 (a real radius of none), a threshold with all four zero and wind below it is dropped. Build `Fix` once per key after the loop.
- [ ] **Step 4: Verify pass**, whole suite (ACE, STORMFURY and threat tests must not move).
- [ ] **Step 5: Commit** `ATCF: keep the wind radii`.

### Task 4: NHC per-storm protective products

**Files:**
- Create: `elnino/tcproducts.py`
- Test: `TestProtectiveProducts`; fixtures `ww_ep152026.kml`, `cone_ep152026.kml`, `surge_ep152026.kml`, `pws_ep152026.shtml`

**Interfaces:**
- Produces:
  - `WarningSegment(kind: str, coords: tuple)`; `watches_warnings(text) -> list[WarningSegment]`; `WW_ORDER` = ("Hurricane Warning", "Hurricane Watch", "Tropical Storm Warning", "Tropical Storm Watch")
  - `cone(text, tolerance=0.02) -> tuple[tuple[float, float], ...]`
  - `SurgeArea(label: str, feet: str, ring: tuple)`; `peak_surge(text, tolerance=0.005) -> list[SurgeArea]`
  - `WindProbability(place: str, threshold: int, cumulative: tuple[int, ...])` with `.total`; `WindTable(issued: str, advisory: str, hours: tuple[int, ...], rows: tuple)`; `wind_probabilities(text) -> WindTable | None`
  - `advisory_of(text) -> str` (the `advisoryNum` in a KML, or the "NUMBER nn" in the text)
  - `Products` (frozen): `watches: tuple | None`, `cone: tuple | None`,
    `surge: tuple | None`, `winds: WindTable | None`, `advisory: str`,
    `notes: tuple[str, ...]`. `()` means "none issued"; `None` means the
    product was linked but could not be fetched or read, with a note saying so.

- [ ] **Step 1: Failing tests**

```python
class TestProtectiveProducts(unittest.TestCase):
    def test_watches_and_warnings_by_kind(self):
        segments = tcproducts.watches_warnings(fixture("ww_ep152026.kml"))
        kinds = {s.kind for s in segments}
        self.assertEqual(kinds, {"Hurricane Watch", "Tropical Storm Warning",
                                 "Tropical Storm Watch"})
        self.assertTrue(all(len(s.coords) >= 2 for s in segments))
        self.assertEqual(tcproducts.advisory_of(fixture("ww_ep152026.kml")), "20")

    def test_the_cone_is_one_closed_ring_over_the_storm(self):
        ring = tcproducts.cone(fixture("cone_ep152026.kml"))
        self.assertEqual(ring[0], ring[-1])
        lons = [p[0] for p in ring]; lats = [p[1] for p in ring]
        self.assertTrue(min(lons) < -155.5 < max(lons))
        self.assertTrue(min(lats) < 16.0 < max(lats))

    def test_peak_surge_areas_carry_their_range(self):
        areas = tcproducts.peak_surge(fixture("surge_ep152026.kml"))
        self.assertEqual(len(areas), 4)
        self.assertEqual({a.feet for a in areas}, {"1-3 ft"})
        self.assertIn("Southeast coast of Hawaii", {a.label for a in areas})

    def test_wind_probabilities_read_as_cumulative_by_hour(self):
        table = tcproducts.wind_probabilities(fixture("pws_ep152026.shtml"))
        self.assertEqual(table.hours, (12, 24, 36, 48, 72, 96, 120))
        self.assertEqual(table.advisory, "20")
        self.assertIn("1500 UTC FRI SEP 25 2026", table.issued)
        rows = {(r.place, r.threshold): r for r in table.rows}
        self.assertEqual(rows[("SOUTH POINT", 34)].cumulative, (1, 29, 49, 50, 50, 50, 50))
        self.assertEqual(rows[("HILO", 34)].cumulative, (0, 3, 6, 6, 7, 7, 7))
        self.assertEqual(rows[("FR FRIG SHOALS", 64)].total, 7)
        self.assertEqual(rows[("BUOY 51002", 64)].total, 57)
```

- [ ] **Step 2: Verify failure** (`ImportError`).
- [ ] **Step 3: Implement** on `kml.placemarks`. Wind table: strip HTML, find the `FORECAST HOUR` line for the hours; each data row matches `^(?P<name>\S.*?)\s+(?P<kt>34|50|64)\s+(?P<first>X|\d+)\s+(?P<rest>.*)$`, cumulative = first then each `(cp)`; `X` is 0 (below 1%, printed "<1%").
- [ ] **Step 4: Verify pass**, suite.
- [ ] **Step 5: Commit** `NHC products: watches and warnings, cone, peak surge, wind probabilities`.

### Task 5: JTWC warnings and advisories

**Files:**
- Create: `elnino/jtwc.py`
- Modify: `elnino/cyclones.py` (basin names, labels for TY/ST/TC)
- Test: `TestJtwc`; fixtures `jtwc.rss`, `jtwc_wp2526.tcw`, `jtwc_sh0326.tcw`

**Interfaces:**
- Consumes: `cyclones.Fix`, `cyclones.Storm`
- Produces:
  - `jtwc.warning_files(rss: str) -> list[str]` -> `["wp2526.tcw"]` (west Pacific, Indian Ocean and southern hemisphere only)
  - `jtwc.parse_tcw(text: str, url: str = "") -> cyclones.Storm | None`, `storm.centre == "JTWC"`
  - `cyclones.BASIN_NAMES` gains `WP`, `IO`, `SH`; `intensity_label` names typhoons, super typhoons and cyclones

- [ ] **Step 1: Failing tests**

```python
class TestJtwc(unittest.TestCase):
    def test_the_rss_lists_only_jtwc_basins(self):
        self.assertEqual(jtwc.warning_files(fixture("jtwc.rss")), ["wp2526.tcw"])

    def test_a_warning_becomes_a_storm_with_history_and_forecast(self):
        storm = jtwc.parse_tcw(fixture("jtwc_wp2526.tcw"))
        self.assertEqual((storm.basin, storm.number, storm.year), ("WP", 25, 2026))
        self.assertEqual(storm.name, "Surigae")
        self.assertEqual(storm.centre, "JTWC")
        now = storm.latest
        self.assertEqual((now.stamp, now.lat, now.lon, now.wind), ("2026092512", 21.4, 128.2, 50))
        self.assertEqual(now.radius(34), (60, 35, 45, 70))
        self.assertEqual(len([f for f in storm.track if f.tau == 0]), 22)
        self.assertEqual(storm.track[0].stamp, "2026092006")
        day1 = [f for f in storm.forecast if f.tau == 24][0]
        self.assertEqual((day1.lat, day1.lon, day1.wind), (23.6, 127.0, 70))
        self.assertEqual(day1.radius(64), (0, 0, 0, 10))
        self.assertEqual([f.stage for f in storm.forecast if f.tau == 120], ["EX"])
        self.assertEqual(storm.advisory["advisory"], "10")

    def test_southern_hemisphere_positions_are_signed(self):
        storm = jtwc.parse_tcw(fixture("jtwc_sh0326.tcw"))
        self.assertEqual(storm.basin, "SH")
        self.assertEqual((storm.latest.lat, storm.latest.lon), (-15.8, 71.2))
        self.assertEqual(storm.track[0].stamp, "2026011318")

    def test_a_typhoon_is_named_as_one(self):
        self.assertEqual(cyclones.intensity_label(100, "TY"), "Category 3-equivalent typhoon")
        self.assertEqual(cyclones.intensity_label(140, "ST"), "Category 5-equivalent super typhoon")
```

- [ ] **Step 2: Verify failure.**
- [ ] **Step 3: Implement.** Header line 3: `DTG ID NAME ... NNN`; `T(\d{3})` lines with `R(\d{3})` groups of four `NE QD/SE QD/SW QD/NW QD`; `AMP` remarks `(\d+)HR BECOMING EXTRATROPICAL` set stage `EX`; history lines `^(\d\d)(\d{8})\s+(\d+[NS])(\d+[EW])\s+(\d+)` with year `20YY`. Stage from wind: TD < 34, TS < 64, then `TY`/`ST` (>= 130) in WP and `TC` elsewhere.
- [ ] **Step 4: Verify pass**, suite.
- [ ] **Step 5: Commit** `JTWC: warnings as storms`.

### Task 6: Formation outlooks and invests

**Files:**
- Create: `elnino/outlook.py`
- Modify: `elnino/jtwc.py` (`disturbances`)
- Test: `TestOutlook`; fixtures `gtwo_pac.kml`, `gtwo_cpac.kml`, `gtwo_atl.kml`, `atcf_btk_listing.html`, `jtwc_abpw.txt`, `jtwc_abpw_invests.txt`

**Interfaces:**
- Produces:
  - `Disturbance` (frozen): `centre, basin, label, lon, lat, chance_2day: int | None, chance_7day: int | None, potential: str, text: str, area: tuple, arrow: tuple, alert: bool, issued: str`
  - `nhc(text: str, basin: str) -> tuple[str, list[Disturbance]]` (issued, areas); `basin` in AL/EP/CP
  - `aor(lon: float, lat: float) -> str`
  - `merge(*groups) -> list[Disturbance]` (dedupe within 1 degree, the responsible centre wins; highest 7-day chance first, then JTWC by potential)
  - `invest_candidates(listing: str) -> list[str]` (ids 90-99 of the listed season)
  - `jtwc.disturbances(text: str) -> list[Disturbance]`

- [ ] **Step 1: Failing tests**

```python
class TestOutlook(unittest.TestCase):
    def test_the_east_pacific_outlook(self):
        issued, areas = outlook.nhc(fixture("gtwo_pac.kml"), "EP")
        self.assertIn("Fri Sep 25", issued)
        self.assertEqual([(a.chance_2day, a.chance_7day) for a in areas], [(40, 90), (20, 50)])
        self.assertEqual(areas[0].potential, "high")
        self.assertIn("Gulf of Tehuantepec", areas[0].text)
        self.assertTrue(areas[0].area and areas[0].arrow)

    def test_nothing_expected_is_an_empty_list(self):
        issued, areas = outlook.nhc(fixture("gtwo_atl.kml"), "AL")
        self.assertEqual(areas, [])

    def test_a_system_both_centres_list_is_kept_once_by_its_owner(self):
        _, ep = outlook.nhc(fixture("gtwo_pac.kml"), "EP")
        _, cp = outlook.nhc(fixture("gtwo_cpac.kml"), "CP")
        merged = outlook.merge(ep, cp)
        self.assertEqual(len(merged), 2)
        hawaii = [d for d in merged if d.lon < -140][0]
        self.assertEqual((hawaii.centre, hawaii.basin), ("CPHC", "CP"))

    def test_areas_of_responsibility(self):
        self.assertEqual(outlook.aor(-45.0, 20.0), "AL")
        self.assertEqual(outlook.aor(-120.0, 15.0), "EP")
        self.assertEqual(outlook.aor(-150.0, 15.0), "CP")
        self.assertEqual(outlook.aor(-90.0, 10.0), "EP")   # Pacific side of Central America
        self.assertEqual(outlook.aor(-80.0, 20.0), "AL")   # Caribbean

    def test_invests_come_from_the_listing(self):
        self.assertEqual(outlook.invest_candidates(fixture("atcf_btk_listing.html")),
                         ["al902026", "ep992026"])

    def test_jtwc_advisory_disturbances(self):
        self.assertEqual(jtwc.disturbances(fixture("jtwc_abpw.txt")), [])
        found = jtwc.disturbances(fixture("jtwc_abpw_invests.txt"))
        self.assertEqual([d.label for d in found], ["Invest 97W", "Invest 98W", "Invest 91P"])
        self.assertEqual([d.potential for d in found], ["low", "high", "medium"])
        self.assertEqual((found[0].lat, found[0].lon), (14.6, 147.4))
        self.assertEqual((found[2].lat, found[2].lon), (-13.4, -172.9))
        self.assertTrue(found[1].alert)       # it cites a formation alert
        self.assertEqual(found[0].centre, "JTWC")
```

- [ ] **Step 2: Verify failure.**
- [ ] **Step 3: Implement.** Areas: polygon placemark with `Disturbance` number; the point placemark with the same number gives the position; the following `LineString` placemark (no data) is the arrow. `aor(lon, lat)` for the northern hemisphere: west of 140 W is `CP`; west of 100 W is `EP`; from 100 W to 77.2 W a point is `EP` when south of the Pacific shore of the isthmus, the piecewise-linear line through (-100, 17.0), (-95, 16.0), (-92, 14.5), (-88, 13.2), (-86, 11.8), (-84, 9.7), (-80, 7.5), (-77.2, 7.0), and `AL` otherwise; east of 77.2 W is `AL`. JTWC advisories: whitespace-normalised paragraphs `(n) ...` under "TROPICAL DISTURBANCE SUMMARY"; position from `NOW LOCATED NEAR` else the first `NEAR lat lon`; potential = the last LOW/MEDIUM/HIGH after "POTENTIAL FOR THE DEVELOPMENT"; `alert` when the paragraph cites a `WTPN2`/`WTIO2`/`WTXS2` formation alert.
- [ ] **Step 4: Verify pass**, suite.
- [ ] **Step 5: Commit** `Outlooks: NHC areas, JTWC disturbances, invests`.

### Task 7: Exposure and viewing geometry

**Files:**
- Create: `elnino/exposure.py`
- Test: `TestExposure`, `TestViewGeometry`

**Interfaces:**
- Consumes: `cyclones.Fix` (`radius`), `cyclones.great_circle`, `atlasdata.PLACES`
- Produces:
  - `bearing(lon1, lat1, lon2, lat2) -> float`
  - `radius_toward(radii4, bearing) -> int | None`
  - `inside(fix, lon, lat, threshold) -> bool | None` (None = not forecast)
  - `timeline(analysis: Fix | None, forecast, step=1) -> list[Fix]` hourly, radii interpolated
  - `Exposure(place, country, population, lon, lat, arrival: dict[int, str | None], unknown: tuple[int, ...], closest_km, closest_stamp)`
  - `exposures(storm, places=None, horizon=120) -> list[Exposure]`
  - `SATELLITES`; `view_zenith(lon, lat, sub_lon) -> float | None`; `best_satellite(lon, lat, limit=70.0) -> tuple[str, float] | None`
  - `parallax(lon, lat, sub_lon, height_km=15.0) -> tuple[float, float]` (apparent lon, lat)
  - `centre_at(path: list[tuple[float, float, float]], when: float) -> tuple[float, float] | None` (epoch seconds, lon, lat)

- [ ] **Step 1: Failing tests**

```python
def _radii_fix(stamp, tau, lat, lon, wind, r34=None, r64=None):
    radii = tuple(pair for pair in ((34, r34), (64, r64)) if pair[1])
    return cyclones.Fix(stamp=stamp, tau=tau, lat=lat, lon=lon, wind=wind,
                        pressure=None, stage="HU", tech="OFCL", radii=radii)

class TestExposure(unittest.TestCase):
    def storm(self):
        now = _radii_fix("2026092512", 0, 15.0, -150.0, 90, (60,)*4, (20,)*4)
        ahead = (_radii_fix("2026092512", 12, 16.0, -150.0, 90, (60,)*4, (20,)*4),
                 _radii_fix("2026092512", 24, 17.0, -150.0, 90, (60,)*4, (20,)*4))
        return cyclones.Storm(basin="CP", number=1, year=2026, name="Test",
                              track=(now,), forecast=ahead, advisory={"x": 1})

    def test_quadrants(self):
        radii = (10, 20, 30, 40)
        self.assertEqual([exposure.radius_toward(radii, b) for b in (45, 135, 225, 315)],
                         [10, 20, 30, 40])

    def test_arrival_of_each_threshold_along_the_official_track(self):
        place = atlasdata.Place("Here", "Nowhere", "", 1000, -150.0, 16.55, False)
        [hit] = exposure.exposures(self.storm(), places=(place,))
        self.assertEqual(hit.arrival[34], "2026092519")
        self.assertEqual(hit.arrival[64], "2026092603")

    def test_unforecast_radii_are_unknown_not_calm(self):
        fix = _radii_fix("2026092512", 96, 16.0, -150.0, 100, (60,)*4, None)
        self.assertIsNone(exposure.inside(fix, -150.0, 16.1, 64))
        weak = _radii_fix("2026092512", 96, 16.0, -150.0, 50, (60,)*4, None)
        self.assertFalse(exposure.inside(weak, -150.0, 16.1, 64))

    def test_the_antimeridian_is_crossed_the_short_way(self):
        path = [(0.0, 179.5, 10.0), (43200.0, -179.5, 10.0)]
        lon, lat = exposure.centre_at(path, 21600.0)
        self.assertAlmostEqual(abs(lon), 180.0, places=6)
        self.assertIsNone(exposure.centre_at(path, 50000.0))

class TestViewGeometry(unittest.TestCase):
    def test_zenith_angles(self):
        self.assertAlmostEqual(exposure.view_zenith(-108.5, 17.1, -137.0), 38.24, places=1)
        self.assertIsNone(exposure.view_zenith(10.0, 0.0, -137.0))  # below the horizon

    def test_the_best_view(self):
        self.assertEqual(exposure.best_satellite(-108.5, 17.1)[0], "GOES-West")
        self.assertEqual(exposure.best_satellite(-22.7, 15.1)[0], "GOES-East")
        self.assertEqual(exposure.best_satellite(128.2, 21.4)[0], "Himawari")
        self.assertIsNone(exposure.best_satellite(71.2, -15.8))

    def test_parallax_moves_cloud_tops_away_from_the_satellite(self):
        lon, lat = exposure.parallax(-108.5, 17.1, -137.0)
        km = cyclones.great_circle(-108.5, 17.1, lon, lat)
        self.assertAlmostEqual(km, 11.8, delta=0.3)
        self.assertGreater(lon, -108.5); self.assertGreater(lat, 17.1)
```

- [ ] **Step 2: Verify failure.**
- [ ] **Step 3: Implement.** Zenith: `g = acos(cos lat cos dlon)`, `tan z = sin g / (cos g - 6378.137/42164)`, None when the denominator <= 0. Parallax: distance `h tan z` along the bearing from the sub-satellite point through the place, destination on the sphere. Exposure: timeline from the analysis (it starts the line only when its stamp equals the forecast's) at 1 h steps; linear interpolation of lat, wrapped lon, wind, and each quadrant radius; a radius missing where the wind is below the threshold is 0, missing where it is at or above is unknown; places pre-filtered to within the largest 34-kt radius plus 1 degree of any timeline point.
- [ ] **Step 4: Verify pass**, suite.
- [ ] **Step 5: Commit** `Exposure: arrival of each wind threshold; satellite view and parallax`.

### Task 8: Wire it into the cyclone tier

**Files:**
- Modify: `elnino/sources.py` (registry: `nhc_outlook_at`, `nhc_outlook_ep`, `nhc_outlook_cp`, `jtwc_rss`, `jtwc_abpw`, `jtwc_abio`; `product_source(kind, storm_id, url, name)`, `jtwc_source(filename)`)
- Modify: `elnino/cyclones.py` (`parse_current` keeps product URLs and advisory numbers; `Storm.centre`, `Storm.products`, `Storm.invest`; `CycloneState.others`, `.invests`, `.outlook`, `.outlook_issued`; `storms` includes `others`; `build` fetches products, JTWC, invests)
- Test: `TestStormProductsWiring` with a fake fetcher

**Interfaces:**
- Produces: `storm.products` = `tcproducts.Products(watches, cone, surge, winds, advisory, notes)`, each field `None` when not issued and a note when it failed; `CycloneState.outlook: list[Disturbance]`.

- [ ] **Step 1: Failing tests** - a fake fetcher keyed on URL returning fixtures:
  CurrentStorms with one storm whose `windWatchesWarnings.kmzFile`, `trackCone.kmzFile`, `windSpeedProbabilities.url`, `peakSurgeKML.peakSurgeKMLFile` point at fixture names; assert `storm.products.watches` non-empty, `cone` closed, `winds.advisory == "20"`, `surge` four areas; a storm with `windWatchesWarnings: null` has `watches == ()` and no note ("none in effect"); a 404 gives `watches is None` and a note ("unavailable"); the JTWC storm from the RSS lands in `state.others` and in `state.active`, not in `state.basins`; outlook merged from the three KMZ keys.
- [ ] **Step 2: Verify failure.**
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Verify pass**, suite; one live run (`python track.py --brief`) to confirm the feeds land.
- [ ] **Step 5: Commit** `Cyclone tier: protective products, JTWC basins, outlooks, invests`.

### Task 9: Alerts from official products

**Files:** Modify `elnino/alerts.py`; Test `TestProductAlerts`

**Interfaces:** `alerts.product_rules(storms) -> list[Alert]`, codes `tc_ww_<key>_<kind>` and `tc_formation_<basin>_<n>`.

- [ ] **Step 1: Failing tests** - hurricane warning -> CRITICAL, hurricane watch -> WARNING, TS warning -> WARNING, TS watch -> WATCH, 7-day 90% -> WATCH, 50% -> nothing, JTWC high -> WATCH; the detail names the coast (first and last segment endpoints to the nearest gazetteer place) and the advisory number.
- [ ] **Steps 2-5:** fail, implement, pass + suite, commit `Alerts: official watches, warnings and formation chances`.

### Task 10: Storm desk data

**Files:** Create `elnino/stormdesk.py` (`payload(state) -> dict`, `write_json`); Test `TestStormDeskPayload`

**Interfaces:**
- Produces: `payload(state)` with `schema: 1`, `built`, `storms[]` (`id, name, title, centre, basin, label, category, wind, pressure, lat, lon, motion, advisory, issued, rmw, eye, radii, track[], forecast[], path[], cone, watches[], surge[], winds, exposure[], view: {satellite, zenith, parallax: [lon, lat]}, links`), `invests[]`, `outlook[]`, `layers[]`, `satellites[]`, `gibs`, `coast`, `notes`.

- [ ] **Step 1: Failing tests** - JSON round-trip; a storm's `path` is ascending in time and ends at the last forecast point; a synthetic storm crossing 180 has `path` and `forecast` longitudes continuous (consecutive differences under 180, so the page never draws a line round the world); `view.satellite` for Polo's position is GOES-West; `links` carry the advisory URL and the responsible centre; every forecast point has a valid ISO time; a JTWC storm has `cone: null` and `centre: "JTWC"`; the payload carries `actions` for people and for animals, each with its source URL.
- [ ] **Steps 2-5:** fail, implement, pass + suite, commit `Storm desk: data`.

### Task 11: Storm desk page

**Files:** Modify `elnino/stormdesk.py` (`page(state) -> str`, CSS, JS); Test `TestStormDeskPage`

**Interfaces:** element ids `map`, `tiles`, `tiles-b`, `overlay`, `divider`, `layer-*`, `compare`, `loop`, `scrub`, `panel`, `storm-list`, `outlook-list`; `window.stormDesk` exposing `flyTo(id)`, `setLayer(id)`, `view()` for browser tests.

- [ ] **Step 1: Failing tests** - page embeds the payload; has the controls above; a legend for storms, wind radii, watches/warnings, outlook; tables for forecast, wind probabilities, exposure; no `<script src`; no `http://`; `touch-action: none` on the map only.
- [ ] **Step 2: Verify failure.**
- [ ] **Step 3: Implement.** Web Mercator tile math (`x = (lon+180)/360 * 2^z`, `y = (1 - ln(tan φ + sec φ)/π)/2 * 2^z`), world wrap by tile column modulo; GIBS REST `.../{layer}/default/{time}/{tms}/{z}/{y}/{x}.png`; describeDomains per layer for frame times; pointers in a Map: one pans, two pinch about their midpoint; double-tap and wheel zoom; swipe via `clip-path` on the top layer; loop over the last 13 frames; scrubber 0..120 h moving the storm, its radii and highlighting exposed places; panel tabs Now / Forecast / Protect (warnings with the NWS definitions, official wind probabilities, surge, exposure, actions for people and for animals, responsible centres); outlook list; offline coast fallback; when served over http(s), `storms.json` re-read every 5 minutes without moving the view; `window.stormDesk` hooks.
- [ ] **Step 4: Verify pass**, suite; then Playwright at 1024x768, 768x1024, 390x844, light and dark: tap to eye, pinch (synthetic pointers), swipe, loop, scrub, zero console errors, no page overflow; once more with every request outside the page blocked (coast drawn, "imagery unreachable" shown, zero console errors); screenshots under `.playwright-mcp/`.
- [ ] **Step 5: Commit** `Storm desk: the page`.

### Task 12: Dashboard card, and pinch on the atlas and globe

**Files:** Modify `elnino/dashboard.py`, `elnino/atlasview.py`, `elnino/globe.py`; Test `TestTouchZoom`, `TestStormDeskLink`

- [ ] **Step 1: Failing tests** - dashboard links `storms.html` in the cyclone section; atlas and globe JS track pointers in a map and handle two (grep for the pinch handler); schema 9 in `dashboard.payload` with `outlook` and `storm_desk`.
- [ ] **Steps 2-5:** fail, implement, pass + suite + Playwright pinch on the atlas, commit `Touch: real pinch on the atlas and globe; the storm desk from the dashboard`.

### Task 13: Report

**Files:** Modify `elnino/report.py` (new section `outlook`; protective lines under each storm); Test `TestReportOutlook`

- [ ] **Step 1: Failing tests** - `outlook` in `SECTIONS`; it lists each area with its 2-day and 7-day chance and each JTWC disturbance with its potential; a storm with a watch prints the kinds; top official wind probabilities printed; ASCII and 78 columns.
- [ ] **Steps 2-5:** fail, implement, pass + suite, commit `Report: formation outlook and protective products`.

### Task 14: Files and serving

**Files:** Modify `track.py`, `.gitignore`; Test `TestServe`

**Interfaces:** `track.main` flags `--serve [PORT]` (default 8765) and `--lan`; `track.serve(directory: Path, port: int, lan: bool) -> ThreadingHTTPServer` (returned, not run, so a test can start and stop it); `/` redirects to `storms.html`.

- [ ] **Step 1: Failing tests** - the server serves `storms.html` from a temp directory, refuses `../`, binds 127.0.0.1 unless `--lan`; `storms.html` and `storms.json` written by a run.
- [ ] **Steps 2-5:** fail, implement, pass + suite, commit `Serve the storm desk to a tablet`.

### Task 15: Find a place

**Files:** Modify `elnino/stormdesk.py`; Test `TestStormDeskFind`

**Interfaces:** page data `places` = `atlasview._places_payload()` rows `[name, country, region, population, lon, lat, capital]`, in `storms.html` only, not `storms.json`; `window.stormDesk.find(text) -> [{kind, label, lon, lat, zoom}]`, `window.stormDesk.go(text)`.

- [ ] **Step 1: Failing tests** - the page embeds the gazetteer rows in the atlas's format and `storms.json` does not; the toolbar has a search form with a labelled input and a results listbox.
- [ ] **Steps 2-5:** fail, implement (search: town, region, country, coordinate; accent- and case-insensitive; fly and pin), Playwright ("Kingston", "sao paulo", "Jamaica", "Florida", "18N 77W"), suite, commit `Storm desk: find a place`.

### Task 16: Here, for any point

**Files:** Modify `elnino/stormdesk.py`, `elnino/atlasview.py`; Test `TestStormDeskHere`

**Interfaces:** a hidden `<section id="here">` at the head of the panel, filled by the page; `METHODS["here"]`; `window.stormDesk.here(lon, lat) -> {place, storms: [{id, now_km, bearing, closest_km, closest, arrival, unknown, cone, watches, surge}], areas}`; `atlas.html#at=LAT,LON` picks that point.

- [ ] **Step 1: Failing tests** - the Here section and its method; the atlas reads `#at=`.
- [ ] **Steps 2-5:** fail, implement, Playwright (tap a town in a storm's path; every exposure-table row of every storm gives the same arrivals through `here`), suite, commit `Storm desk: what the storms mean here`.

### Task 17: Close in

**Files:** Modify `elnino/stormdesk.py`; Test `TestStormDeskCloseIn`

**Interfaces:** `LAYERS` gains `detail` (stack `HLS_L30_Nadir_BRDF_Adjusted_Reflectance`, `HLS_S30_Nadir_BRDF_Adjusted_Reflectance`; `GoogleMapsCompatible_Level12`; png; P1D), `lights` (`VIIRS_Black_Marble`, time `2016-01-01`, Level8, png) and the overlay `builtup` (`Landsat_Human_Built-up_And_Settlement_Extent`, Level12, png); `MAXZ = 13`; `data-show="towns"`; day steps `#day-earlier`, `#day-later`.

- [ ] **Step 1: Failing tests** - layer names as GIBS's capabilities list them, MAXZ 13, the towns toggle and the day steps.
- [ ] **Steps 2-5:** fail, implement, Playwright (Kingston at level 11: a day with an image found, earlier and later steps, towns drawn, no overflow at 390, zero script errors), suite, commit `Storm desk: close in on a town`.

### Task 18: Documentation and verification

- [ ] README: storm desk section; feeds table; layout; schema 9; tests count; tablet serving.
- [ ] Full suite, compileall, live run, offline run, report width, JSON schema, Playwright pass over all three pages.
- [ ] Commit `Storm desk: documentation`.
