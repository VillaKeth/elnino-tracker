# Enter a Place, Then and Now — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A Google-Maps-style "Enter" on the desk's map that drops into any point and shows the same ground at two dates either side of the divider, each date named with the RONI season around it, with one-step choices for every El Niño since 2000.

**Architecture:** A new module `elnino/thennow.py` holds the sources, the Python that turns the RONI record into season words and event presets, the markup, the CSS and a script spliced into the desk's script at a `/*THENNOW*/` marker, as `worldmap._JS` is at `/*WORLDMAP*/`. Each side of the divider is registered as a layer of the page's own kind (`LAYERS["then-a"]`, `LAYERS["then-b"]`), so the existing compare view draws the two dates; `stormdesk.py` and `worldmap.py` gain one-line hooks that ask `S.then` (a property, so the existing tests that lift single engine functions out to run under node still run them alone).

**Tech Stack:** Python 3.10 standard library; the page's ES5 script; `unittest`, with the page's own functions run under node (skipped where node is absent).

**Spec:** `docs/superpowers/specs/2026-09-29-then-and-now-design.md`

## Global Constraints

- Python standard library only: no new dependency, no build step (the tracker keeps working with no `pip install`).
- The page script stays ES5, as the rest of `_JS`: `var`, `function`, no arrow functions, no classes, no template strings.
- Every control is at least 44 px and has a name (its text, a `<label>` or `aria-label`); colours come from the page's tokens (`--ink`, `--ink2`, `--surface`, `--plane`, `--border`, `--warm`, `--cool`), so dark mode follows.
- No count is printed with a lazy "(s)" plural (TestWording scans every string in `elnino/*.py`).
- Google: its embed and its Maps URLs only; no Google tile is drawn on the page.
- Esri's Wayback runs under the Esri Master License Agreement, as World Imagery does: tiles drawn as the page is viewed, never exported; each release credited in its own words.
- URLs exactly as verified on 29 Sep 2026 (the spec's table): Wayback config `https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/waybackconfig.json`, tilemap `https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tilemap/{release}/{z}/{y}/{x}`, item `https://www.arcgis.com/sharing/rest/content/items/{id}?f=json`, metadata `{metadataLayerUrl}/7/query?...`; GIBS layers `MODIS_Terra_CorrectedReflectance_TrueColor` (Level9, jpeg), `MODIS_Terra_L3_NDVI_16Day` (Level9, png), `GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies` (Level6, png), and the desk's two HLS layers.
- Merge to main, and any push, wait for the user's word.
- Test command: `python -m unittest discover -s tests` (whole suite); per task `python -m unittest tests.test_thennow` or a class of it, run from the repository root.

## Review Focus

1. **A pin near the antimeridian** (entering at 179.99E, then tapping at 179.99W): the tile walked in Esri's archive, the pixel read and the tiles drawn must be the ones under the pin, never a column outside 0..2^z-1. Tests: `TestThenArchiveRuns.test_the_pin_s_tile_wraps_at_the_date_line` (Task 4), `TestThenBarRuns.test_the_pixel_read_wraps_at_the_date_line` (Task 7).
2. **Esri's metadata never answering** (a query that hangs, as one did for 60 s on 29 Sep 2026): the versions stay usable, named by release date, and the bar says the capture dates were not given. Tests: `TestThenArchiveRuns.test_a_metadata_query_that_hangs_is_given_up_after_20_s` (Task 4), `TestThenBarRuns.test_versions_without_capture_dates_are_named_by_release` (Task 7).
3. **A cleared or impossible date typed into a side's field** (`""`, `2015-02-30`): ignored, nothing thrown, the side keeps its date. Test: `TestThenBarRuns.test_a_cleared_or_impossible_date_is_ignored` (Task 7).
4. **Entering while the loop runs or the forecast scrubber is moved**: the loop stops while entered and runs again on Exit; the scrubber is hidden and keeps its hour. Test: `TestThenEnterRuns.test_the_loop_stops_while_entered_and_runs_again_after` (Task 8).
5. **The served page's five-minute refresh while entered**: `prepare()` rebuilds `LAYERS` from the new data and would drop the two sides; they are registered again. Test: `TestThenEnterRuns.test_a_refresh_while_entered_draws_the_sides_again` (Task 8).

## Files

- Create `elnino/thennow.py`: sources, Wayback constants, NDVI colours, season words, presets, payload, markup (`enter_button`, `map_parts`, `bar`, `legend`), `css()`, `_JS`.
- Modify `elnino/stormdesk.py`: import; `_map()` takes `thennow.map_parts()`; `page()` adds `data["then"]`, the CSS, the Enter button, the bar; `_legend()` takes `thennow.legend()`; `script()` splices `/*THENNOW*/`; hooks in `_JS` (cells, xyzCells, TileSet.draw, tileFailed, labelled, baseDown, tilesDown, overSpecs, tiles, buildGeo, drawMarks, pills, downWord, render, retry, setLayer, setCompare, swap and compare-layer listeners, flyTo, go, applyHash, tap, showHere, the click handler, `clearHere`, refresh, `window.stormDesk`).
- Modify `elnino/worldmap.py`: hooks in `_JS` (drawComposite, ensoLegend, ensoTileLegend, ensoTileSpecs, showRegion, setEnso).
- Create `tests/test_thennow.py`.
- Modify `README.md`: a "Then and now" section under section 13, the layout line and the test count.

---

### Task 1: Season words, presets and the payload (Python)

**Files:**
- Create: `elnino/thennow.py`
- Test: `tests/test_thennow.py` (create)

**Interfaces:**
- Consumes: `classify.displayed`, `classify.intensity_tier`, `classify.find_episodes`, `Episode.name/.peak/.qualifies/.latest/.length/.seasons`, `SeasonValue.centre/.label/.value`, `worldmap._built_day(state)`, `worldmap.SST_COLOURS`, `worldmap._sst_label(lo, hi)`.
- Produces: `thennow.SOURCES` (tuple of dicts: `id, kind, name, about, first, zoom, enter`, GIBS ones also `layer, tms, tile_zoom, format, pixel_km, credit`), `thennow.WAYBACK` (dict: `config, tilemap, item, level, metadata_layer, credit`), `thennow.NAMES_CREDIT`, `thennow.NDVI_COLOURS`, `thennow.season_rows(series) -> list[[key, label, shown, words]]`, `thennow.presets(series, built: date, index="RONI") -> list[{id, group, label, left, right}]`, `thennow.payload(state) -> dict` with keys `sources, wayback, names_credit, index, seasons, presets, built, strip {from, months}, scales {sst, ndvi}`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_thennow.py`:

```python
"""Then and now: entering a place on the map and comparing it before and
after El Nino (elnino/thennow.py, and its hooks in the desk's page)."""

from __future__ import annotations

import json
import re
import shutil
import sys
import unittest
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from elnino import parsers, stormdesk, thennow, worldmap  # noqa: E402
from elnino.parsers import SeasonValue  # noqa: E402
# The helpers only: importing a TestCase class here would run it twice.
from test_tracker import _DeskFixtures, _js_function, _node_json  # noqa: E402


def seasons_from(season: str, year: int, values) -> list:
    """Consecutive seasons from one, as CPC's files list them."""
    order = parsers.ONI_SEASONS
    i, out = order.index(season), []
    for value in values:
        out.append(SeasonValue(order[i], year, value))
        i += 1
        if i == len(order):
            i, year = 0, year + 1
    return out


# SON 1999 to JJA 2001: a La Nina episode across the turn of 2000; a warm run
# of three seasons in 2000 (0.46 prints as 0.5); a very strong El Nino
# peaking JFM 2001; and two warm seasons still going at the end.
RECORD = seasons_from("SON", 1999, (
    -1.2, -1.4, -1.5, -1.3, -1.1, -0.8,     # SON 1999 - FMA 2000
    -0.4, 0.2, 0.46, 0.6, 0.5, 0.3, 0.0,    # MAM - SON 2000
    0.8, 1.2, 1.6, 2.1, 1.7, 0.9,           # OND 2000 - MAM 2001
    0.1, 0.7, 0.9))                         # AMJ - JJA 2001


def state_with(series, run_at="2001-09-29T12:00:00+00:00", index="RONI"):
    return SimpleNamespace(run_at=run_at, assessment=SimpleNamespace(
        index_name=index, index_series=list(series)))


class TestSeasonWords(unittest.TestCase):
    """Every season from DJF 2000 on, keyed by its centre month, with its
    value as CPC prints it and what it was."""

    def rows(self, series=RECORD):
        return {row[0]: row for row in thennow.season_rows(series)}

    def test_each_season_is_keyed_by_its_centre_month_from_january_2000(self):
        rows = thennow.season_rows(RECORD)
        self.assertEqual(rows[0][:3], ["2000-01", "DJF 2000", -1.3])
        self.assertEqual(rows[-1][:2], ["2001-07", "JJA 2001"])
        self.assertEqual(len(rows), 19)
        self.assertFalse([r for r in rows if r[0] < "2000-01"])

    def test_a_season_in_an_episode_names_its_strength_and_the_episode(self):
        rows = self.rows()
        self.assertEqual(rows["2000-01"][3], "moderate La Niña, the 1999-00 episode")
        self.assertEqual(rows["2000-02"][3], "moderate La Niña, the 1999-00 episode")
        self.assertEqual(rows["2000-03"][3], "weak La Niña, the 1999-00 episode")
        self.assertEqual(rows["2001-02"][2:], [2.1, "very strong El Niño, the 2000-01 episode"])
        self.assertEqual(rows["2001-04"][3], "weak El Niño, the 2000-01 episode")

    def test_a_run_short_of_five_seasons_is_conditions_short_of_an_episode(self):
        # MJJ 2000's 0.46 is printed 0.5, and counted, as CPC counts it.
        self.assertEqual(self.rows()["2000-06"][2:], [0.5, "weak El Niño conditions, short of an episode"])

    def test_the_run_still_going_counts_its_seasons_so_far(self):
        rows = self.rows()
        self.assertEqual(rows["2001-06"][3], "weak El Niño conditions, 2 seasons so far")
        self.assertEqual(rows["2001-07"][3], "weak El Niño conditions, 2 seasons so far")
        one = self.rows(RECORD[:-1])
        self.assertEqual(one["2001-06"][3], "weak El Niño conditions, 1 season so far")

    def test_an_episode_still_going_says_so(self):
        rows = self.rows(RECORD + seasons_from("JAS", 2001, (0.8, 1.0, 1.1)))
        self.assertEqual(rows["2001-10"][3], "moderate El Niño, the 2001 episode, still going")

    def test_everything_else_is_neutral(self):
        rows = self.rows()
        self.assertEqual(rows["2000-04"][2:], [-0.4, "neutral"])
        self.assertEqual(rows["2000-10"][2:], [0.0, "neutral"])

    def test_no_record_no_rows(self):
        self.assertEqual(thennow.season_rows([]), [])


class TestPresets(unittest.TestCase):
    """The event menu: a year ago against the latest, then each El Nino
    episode peaking since March 2000, newest first, before and after its peak."""

    def test_the_first_entry_is_a_year_ago_against_the_latest(self):
        first = thennow.presets(RECORD, date(2001, 9, 29))[0]
        self.assertEqual(first, {"id": "now", "group": "", "left": "2000-09-29",
                                 "right": "2001-09-29",
                                 "label": "A year ago → the latest (Sep 2000 → Sep 2001)"})

    def test_an_episode_gives_the_year_before_its_peak_and_the_year_after(self):
        got = thennow.presets(RECORD, date(2003, 1, 1))
        self.assertEqual([p["id"] for p in got], ["now", "ep0-before", "ep0-after"])
        before, after = got[1], got[2]
        self.assertEqual((before["left"], before["right"]), ("2000-02-15", "2001-02-15"))
        self.assertEqual((after["left"], after["right"]), ("2001-02-15", "2002-02-15"))
        self.assertEqual(before["group"], "2000-01 El Niño, peaking JFM 2001 at RONI +2.1")
        self.assertEqual(before["label"], "A year before the peak → the peak (Feb 2000 → Feb 2001)")
        self.assertEqual(after["label"], "The peak → a year after (Feb 2001 → Feb 2002)")

    def test_a_choice_whose_dates_have_not_come_is_not_offered(self):
        got = thennow.presets(RECORD, date(2001, 9, 29))
        self.assertEqual([p["id"] for p in got], ["now", "ep0-before"])

    def test_episodes_come_newest_first(self):
        more = RECORD + seasons_from("JAS", 2001, (0.8, 1.0, 1.1, 1.3, 1.0, 0.6, 0.2))
        got = thennow.presets(more, date(2003, 6, 1))
        self.assertEqual([p["id"] for p in got],
                         ["now", "ep1-before", "ep1-after", "ep0-before", "ep0-after"])
        self.assertEqual(got[1]["right"], "2001-11-15")

    def test_a_peak_before_march_2000_and_la_nina_are_not_offered(self):
        early = seasons_from("MJJ", 1999, (0.6, 0.8, 1.0, 1.2, 1.5, 1.8, 2.0, 1.1, 0.2))
        self.assertEqual([p["id"] for p in thennow.presets(early, date(2003, 1, 1))], ["now"])
        cool = seasons_from("MJJ", 2005, (-0.6, -0.8, -1.0, -1.2, -1.0, -0.6, 0.0))
        self.assertEqual([p["id"] for p in thennow.presets(cool, date(2008, 1, 1))], ["now"])


class TestThenPayload(unittest.TestCase):
    """What the page is sent: the sources, Esri's archive, the seasons, the
    menu and NASA's scales."""

    def test_the_five_sources_with_their_archives_first_days(self):
        got = thennow.payload(state_with(RECORD))["sources"]
        self.assertEqual([s["id"] for s in got], ["archive", "hls", "modis", "ndvi", "sst"])
        self.assertEqual([s["first"] for s in got],
                         ["2014-02-20", "2013-03-22", "2000-02-24", "2000-03-05", "2002-09-01"])
        self.assertEqual([s["enter"] for s in got], [16, 12, 8, 7, 4])
        self.assertEqual([s["zoom"] for s in got], [19, 13, 13, 13, 13])
        by = {s["id"]: s for s in got}
        self.assertEqual((by["modis"]["layer"], by["modis"]["tms"], by["modis"]["format"]),
                         ("MODIS_Terra_CorrectedReflectance_TrueColor",
                          "GoogleMapsCompatible_Level9", "jpeg"))
        self.assertEqual((by["ndvi"]["layer"], by["ndvi"]["tms"], by["ndvi"]["format"]),
                         ("MODIS_Terra_L3_NDVI_16Day", "GoogleMapsCompatible_Level9", "png"))
        self.assertEqual((by["sst"]["layer"], by["sst"]["tms"], by["sst"]["tile_zoom"]),
                         ("GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies",
                          "GoogleMapsCompatible_Level6", 6))
        for s in got:
            self.assertTrue(s["name"] and s["about"], s["id"])

    def test_esri_s_archive_is_asked_where_it_answered(self):
        w = thennow.payload(state_with(RECORD))["wayback"]
        self.assertEqual(w["config"], "https://s3-us-west-2.amazonaws.com/config.maptiles."
                                      "arcgis.com/waybackconfig.json")
        self.assertEqual(w["tilemap"], "https://wayback.maptiles.arcgis.com/arcgis/rest/services/"
                                       "World_Imagery/MapServer/tilemap/{release}/{z}/{y}/{x}")
        self.assertEqual(w["item"], "https://www.arcgis.com/sharing/rest/content/items/{id}?f=json")
        self.assertEqual((w["level"], w["metadata_layer"]), (16, 7))

    def test_the_seasons_menu_and_strip_come_from_the_official_index(self):
        got = thennow.payload(state_with(RECORD, index="ONI"))
        self.assertEqual(got["seasons"], thennow.season_rows(RECORD))
        self.assertEqual(got["presets"], thennow.presets(RECORD, date(2001, 9, 29), "ONI"))
        self.assertEqual(got["index"], "ONI")
        self.assertEqual((got["built"], got["strip"]), ("2001-09-29", {"from": "2000-01", "months": 21}))

    def test_a_run_without_the_index_still_offers_a_year_ago(self):
        got = thennow.payload(SimpleNamespace(run_at="2026-09-29T12:00:00+00:00"))
        self.assertEqual((got["seasons"], got["index"]), ([], "RONI"))
        self.assertEqual([p["id"] for p in got["presets"]], ["now"])
        self.assertEqual(got["strip"]["months"], 321)

    def test_the_payload_survives_json(self):
        got = thennow.payload(state_with(RECORD))
        self.assertEqual(json.loads(json.dumps(got)), got)

    def test_the_scales_are_nasa_s_own_bin_for_bin(self):
        scales = thennow.payload(state_with(RECORD))["scales"]
        self.assertEqual([(e["lo"], e["hi"], tuple(e["rgb"])) for e in scales["sst"]],
                         [(lo, hi, rgb) for lo, hi, rgb in worldmap.SST_COLOURS])
        self.assertEqual(scales["sst"][41]["label"], "+1.0 to +1.1 °C")
        ndvi = scales["ndvi"]
        self.assertEqual(len(ndvi), 140)
        self.assertEqual(ndvi[0], {"lo": 0.0, "hi": 0.005, "rgb": [241, 236, 236],
                                   "label": "NDVI 0.000 to 0.005"})
        self.assertEqual((ndvi[-1]["lo"], ndvi[-1]["hi"], ndvi[-1]["rgb"]), (0.99, 1.0, [0, 24, 1]))
        for before, after in zip(ndvi, ndvi[1:]):
            self.assertEqual(before["hi"], after["lo"])
        self.assertIn("NDVI 0.280 to 0.285", [e["label"] for e in ndvi])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow -v`
Expected: ERROR, `ImportError: cannot import name 'thennow' from 'elnino'`.

- [ ] **Step 3: Print NASA's NDVI colour map as Python rows**

Run (the colour map saved on 29 Sep 2026 from `https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_L3_NDVI.xml`; fetch it again to the same path if the scratchpad copy is gone):

```bash
python - <<'EOF'
import re
path = r"<scratchpad>\r15\cm_MODIS_L3_NDVI.xml"
text = open(path, encoding="utf-8").read()
rows = re.findall(r'<ColorMapEntry rgb="(\d+),(\d+),(\d+)" transparent="(true|false)"[^>]*'
                  r'value="\[([-\d.]+),([-\d.]+)\)"', text)
cells = [f"({round(float(lo), 3)}, {round(float(hi), 3)}, ({r}, {g}, {b}))"
         for r, g, b, clear, lo, hi in rows if clear == "false"]
print(len(cells), cells[0], cells[-1])
line = "   "
for cell in cells:
    if len(line) + len(cell) + 2 > 96:
        print(line)
        line = "   "
    line += " " + cell + ","
print(line)
EOF
```

Expected: first line `140 (0.0, 0.005, (241, 236, 236)) (0.99, 1.0, (0, 24, 1))`, then the rows wrapped under 96 columns. Paste the rows (not the first line) as the body of `NDVI_COLOURS` in Step 4.

- [ ] **Step 4: Write `elnino/thennow.py`**

```python
"""Enter a place and see it before and after El Nino.

"Enter" drops into a point of the map as Google Maps' figure does, and shows
the same ground at two dates either side of the divider, the earlier on the
left, each date named with what ENSO was doing in the season around it: the
tracker's own record of the official index, RONI. Five archives hold the
dates, every one keyless and sent with CORS, as each answered on 29 September
2026:

* Esri's World Imagery Wayback: every release of World Imagery since
  February 2014, sub-metre where Esri has it, under the Esri Master License
  Agreement the map's World Imagery already runs under: drawn as the page is
  viewed, never exported. A release's tilemap names the release a tile last
  changed in, which is how Esri's own Wayback app finds the versions of one
  place, and its metadata service names when and by whom each was taken.
* NASA GIBS: Landsat and Sentinel-2 at 30 m (HLS, 2013 on), MODIS Terra's
  daily true colour (250 m, 2000 on), MODIS Terra's 16-day vegetation index
  (2000 on) and GHRSST MUR25's daily sea surface temperature anomaly (2002
  on).

Google's Street View cannot be had for a date: neither its embed nor its Maps
URLs take one. It stays one press away, and Google Maps' own "See more dates"
holds its older panoramas.
"""

from __future__ import annotations

from datetime import date

from . import classify, worldmap
from .svg import esc

# Esri's World Imagery Wayback as it answered on 29 September 2026: 196
# releases from 2014-02-20 to 2026-08-05, each with its item, its tiles and
# its metadata service, all sent with Access-Control-Allow-Origin: *.
WAYBACK = {
    "config": ("https://s3-us-west-2.amazonaws.com/config.maptiles.arcgis.com/"
               "waybackconfig.json"),
    "tilemap": ("https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/"
                "MapServer/tilemap/{release}/{z}/{y}/{x}"),
    "item": "https://www.arcgis.com/sharing/rest/content/items/{id}?f=json",
    # The pin's tile is walked at zoom 16. The metadata layer for a zoom is
    # 23 minus the zoom, 0 to 13, as Esri's Wayback app reads it: layer 7,
    # 2.4 m, at zoom 16.
    "level": 16,
    "metadata_layer": 7,
    # World Imagery's own credit, until a release's item page gives its own.
    "credit": "Esri, Vantor, Earthstar Geographics, and the GIS User Community",
}
NAMES_CREDIT = ("Roads and names: Esri, HERE, Garmin, (c) OpenStreetMap contributors, "
                "and the GIS user community.")

# Each source: what it is, its first day, the zoom it is drawn to and the
# zoom a place is entered at, as the spec's table has them.
SOURCES = (
    {"id": "archive", "kind": "wayback", "name": "Satellite archive (Esri)",
     "about": ("Esri World Imagery as each Wayback release since February 2014 showed it: "
               "sub-metre where Esri has it, each version named by the day its imagery "
               "was taken and by whom."),
     "first": "2014-02-20", "zoom": 19, "enter": 16},
    {"id": "hls", "kind": "hls", "name": "Landsat and Sentinel-2, 30 m",
     "about": ("NASA's Harmonized Landsat and Sentinel-2: a day's passes at 30 m, clouds as "
               "seen. Each side shows the nearest day with an image at the pin."),
     "first": "2013-03-22", "zoom": 13, "enter": 12, "pixel_km": 0.03,
     "credit": "HLS: NASA, from USGS Landsat and ESA Copernicus Sentinel-2."},
    {"id": "modis", "kind": "gibs", "name": "True colour, daily (MODIS Terra)",
     "about": "MODIS on Terra, one morning pass a day at 250 m, since February 2000.",
     "layer": "MODIS_Terra_CorrectedReflectance_TrueColor",
     "tms": "GoogleMapsCompatible_Level9", "tile_zoom": 9, "format": "jpeg",
     "first": "2000-02-24", "zoom": 13, "enter": 8, "pixel_km": 0.25,
     "credit": "MODIS Terra: NASA."},
    {"id": "ndvi", "kind": "gibs", "name": "Vegetation (MODIS NDVI, 16-day)",
     "about": ("MODIS Terra's vegetation index, a 16-day composite at 250 m: brown bare "
               "ground to dark green canopy; water and gaps are left clear."),
     "layer": "MODIS_Terra_L3_NDVI_16Day",
     "tms": "GoogleMapsCompatible_Level9", "tile_zoom": 9, "format": "png",
     "first": "2000-03-05", "zoom": 13, "enter": 7, "pixel_km": 0.25,
     "credit": "NDVI: MODIS Terra, NASA."},
    {"id": "sst", "kind": "gibs", "name": "Ocean temperature anomaly (MUR25)",
     "about": ("GHRSST MUR25: the daily sea surface temperature anomaly on a quarter-degree "
               "grid, since September 2002, against MUR's own climatology."),
     "layer": "GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies",
     "tms": "GoogleMapsCompatible_Level6", "tile_zoom": 6, "format": "png",
     "first": "2002-09-01", "zoom": 13, "enter": 4, "pixel_km": 25.0,
     "credit": "SST: GHRSST MUR25, NASA JPL."},
)

# The first season the page carries, DJF 2000, centred on January 2000: no
# archive here starts earlier. Events are offered for peaks from March 2000,
# MODIS's first full month.
FIRST_MONTH = date(2000, 1, 1)
PRESETS_FROM = date(2000, 3, 1)

# NASA's colour map for the 16-day NDVI, bin for bin, so a pixel reads back
# to its value: https://gibs.earthdata.nasa.gov/colormaps/v1.3/MODIS_L3_NDVI.xml,
# 29 Sep 2026. (low, high, rgb), [low, high); its fill and the bins below
# zero are drawn clear, and are not listed.
NDVI_COLOURS = (
    # the rows printed in Step 3
)


def _tier_words(value: float) -> str:
    """classify's tier as words: "very strong El Niño", "weak La Niña", "neutral"."""
    tier = classify.intensity_tier(value)
    for ascii_name, name in (("El Nino", "El Ni\u00f1o"), ("La Nina", "La Ni\u00f1a")):
        if tier.endswith(ascii_name):
            return tier[: -len(ascii_name)].lower() + name
    return "neutral"


def _month_index(key: str) -> int:
    """Months from January 2000 to a "YYYY-MM" key."""
    return (int(key[:4]) - FIRST_MONTH.year) * 12 + int(key[5:7]) - 1


def season_rows(series) -> list:
    """Each season from DJF 2000 on as [centre month, label, value as CPC
    prints it, what it was]: its strength, and the episode it belonged to,
    the run of conditions still going and how long, or conditions short of
    an episode; otherwise neutral."""
    if not series:
        return []
    last = series[-1].centre
    member = {}
    for warm in (True, False):
        for episode in classify.find_episodes(series, warm):
            for season in episode.seasons:
                member[season.centre] = (episode, episode.latest.centre == last)
    rows = []
    for season in series:
        if season.centre < FIRST_MONTH:
            continue
        words = _tier_words(season.value)
        got = member.get(season.centre)
        if got:
            episode, going = got
            if episode.qualifies:
                words += f", the {episode.name} episode" + (", still going" if going else "")
            elif going:
                n = episode.length
                words += f" conditions, {n} season{'s' if n != 1 else ''} so far"
            else:
                words += " conditions, short of an episode"
        rows.append([f"{season.centre:%Y-%m}", season.label, classify.displayed(season.value), words])
    return rows


def _month(day: date) -> str:
    return f"{day:%b %Y}"


def _years_on(day: date, years: int) -> date:
    """The same day some years on (back, when negative); 29 February becomes the 28th."""
    try:
        return day.replace(year=day.year + years)
    except ValueError:
        return day.replace(year=day.year + years, day=28)


def presets(series, built: date, index: str = "RONI") -> list:
    """The event menu, each entry two ISO dates for the sides.

    First "a year ago -> the latest", for the event now. Then, newest first,
    each El Nino episode whose peak season is centred on March 2000 or later:
    "a year before the peak -> the peak" and "the peak -> a year after", the
    peak taken as the 15th of its season's centre month, each offered once
    both its dates have come."""
    year_ago = _years_on(built, -1)
    out = [{"id": "now", "group": "", "left": year_ago.isoformat(), "right": built.isoformat(),
            "label": f"A year ago \u2192 the latest ({_month(year_ago)} \u2192 {_month(built)})"}]
    episodes = [e for e in classify.find_episodes(series, True)
                if e.qualifies and e.peak.centre >= PRESETS_FROM]
    for n, episode in reversed(list(enumerate(episodes))):
        peak = episode.peak.centre.replace(day=15)
        before, after = _years_on(peak, -1), _years_on(peak, 1)
        group = (f"{episode.name} El Ni\u00f1o, peaking {episode.peak.label} at {index} "
                 f"{classify.displayed(episode.peak.value):+.1f}")
        for key, left, right, words in (
                ("before", before, peak, "A year before the peak \u2192 the peak "
                                         f"({_month(before)} \u2192 {_month(peak)})"),
                ("after", peak, after, "The peak \u2192 a year after "
                                       f"({_month(peak)} \u2192 {_month(after)})")):
            if right <= built:
                out.append({"id": f"ep{n}-{key}", "group": group, "left": left.isoformat(),
                            "right": right.isoformat(), "label": words})
    return out


def _scales() -> dict:
    """NASA's colour maps as the page reads a pixel back: the ocean's (the
    map's own, worldmap.SST_COLOURS) and the vegetation index's."""
    return {"sst": [{"lo": lo, "hi": hi, "rgb": list(rgb), "label": worldmap._sst_label(lo, hi)}
                    for lo, hi, rgb in worldmap.SST_COLOURS],
            "ndvi": [{"lo": lo, "hi": hi, "rgb": list(rgb), "label": f"NDVI {lo:.3f} to {hi:.3f}"}
                     for lo, hi, rgb in NDVI_COLOURS]}


def payload(state) -> dict:
    """What the page needs to compare dates: the sources, Esri's archive, the
    index's seasons with their words, the event menu and NASA's scales."""
    a = getattr(state, "assessment", None)
    series = list(getattr(a, "index_series", None) or [])
    index = getattr(a, "index_name", None) or "RONI"
    built = worldmap._built_day(state)
    return {"sources": [dict(s) for s in SOURCES], "wayback": dict(WAYBACK),
            "names_credit": NAMES_CREDIT, "index": index,
            "seasons": season_rows(series), "presets": presets(series, built, index),
            "built": built.isoformat(),
            "strip": {"from": f"{FIRST_MONTH:%Y-%m}",
                      "months": _month_index(f"{built:%Y-%m}") + 1},
            "scales": _scales()}
```

(`esc` is imported now for the markup of Task 2.)

- [ ] **Step 5: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 18 tests, OK.

- [ ] **Step 6: Mutation check**

Change `if right <= built:` to `if True:` in `presets`; run `python -m unittest tests.test_thennow.TestPresets`; expected FAIL in `test_a_choice_whose_dates_have_not_come_is_not_offered`. Put it back; run again; expected OK.

- [ ] **Step 7: Commit**

```bash
git add elnino/thennow.py tests/test_thennow.py
git commit -m "Then and now: season words, presets and the payload" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: The Enter button, the bar, the map's parts and the splice

**Files:**
- Modify: `elnino/thennow.py` (markup, CSS, the first lines of `_JS`)
- Modify: `elnino/stormdesk.py:25` (import), `:1290-1326` (`_map`), `:1612-1672` (`page`), `:1675-1677` (`script`), `:3825` (the marker)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: `thennow.payload(state)` (Task 1), `thennow._month_index(key)`.
- Produces: `thennow.enter_button() -> str`, `thennow.map_parts() -> str`, `thennow.bar(then: dict) -> str`, `thennow.css() -> str`, `thennow._JS` (spliced at `  /*THENNOW*/\n`), in the page: element ids `then-enter`, `then-enter-how`, `then-ghost`, `then-hint`, `then-chip-a`, `then-chip-b`, `then-ring`, `then-bar`, `then-source`, `then-event`, `then-street`, `then-copy`, `then-names`, `then-exit`, `then-head-{a,b}`, `then-back-{a,b}`, `then-date-{a,b}`, `then-cap-{a,b}`, `then-next-{a,b}`, `then-words-{a,b}`, `then-strip`, `then-line-{a,b}`, `then-read`, `then-note`, `then-gmaps`; in the script: `S.then` (null until entered), `thenSrc(id) -> source dict | null`; `D.then` = the payload.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
# The 2014-16 event as CPC's ONI table printed it, DJF 2014 to NDJ 2016: the
# record the page's tests read.
EVENT = seasons_from("DJF", 2014, (
    -0.4, -0.5, -0.3, 0.0, 0.2, 0.1, 0.0, 0.1, 0.4, 0.5, 0.6, 0.7,
    0.5, 0.5, 0.5, 0.7, 0.9, 1.2, 1.5, 1.9, 2.2, 2.4, 2.6, 2.6,
    2.5, 2.1, 1.6, 0.9, 0.4, -0.1, -0.4, -0.5, -0.6, -0.7, -0.7, -0.6))


class TestThenMarkup(_DeskFixtures, unittest.TestCase):
    """The page's parts: the figure in the toolbar, the chips and hint on the
    map, the bar under it, and the script spliced in."""

    def page(self) -> str:
        state = self.state(self.polo())
        state.assessment = SimpleNamespace(index_name="RONI", index_series=list(EVENT))
        state.run_at = "2026-09-29T12:00:00+00:00"
        return stormdesk.page(state, focus="world")

    def test_the_figure_is_a_named_button_in_the_toolbar(self):
        html = self.page()
        tools = re.search(r'<nav class="desktools".*?</nav>', html, re.S).group(0)
        button = re.search(r'<button[^>]*id="then-enter"[^>]*>.*?</button>', tools, re.S).group(0)
        self.assertIn('aria-pressed="false"', button)
        self.assertIn('aria-describedby="then-enter-how"', button)
        self.assertIn('<svg class="thenfigsvg"', button)
        self.assertIn('aria-hidden="true"', button)
        self.assertTrue(button.endswith(" Enter</button>"))
        self.assertIn('id="then-enter-how">Drag the figure onto the map, or press it and tap a '
                      "place, to see that place before and after El Niño.</span>", tools)
        self.assertIn('id="then-ghost" aria-hidden="true" hidden>', tools)

    def test_the_hint_chips_and_ring_are_on_the_map(self):
        html = self.page()
        mapped = html[html.index('<div class="deskmap" id="map"'):html.index('<div class="deskzoom ui">')]
        self.assertIn('<p class="thenhint ui" id="then-hint" role="status" hidden>Tap a place to '
                      "enter it, or press Enter for the middle of the view. Esc cancels.</p>", mapped)
        for key in ("a", "b"):
            self.assertIn(f'<div class="thenchip ui" id="then-chip-{key}" hidden></div>', mapped)
        self.assertIn('<span class="thenring" id="then-ring" aria-hidden="true" hidden></span>', mapped)

    def test_the_bar_sits_under_the_map_hidden_with_every_control_named(self):
        html = self.page()
        self.assertLess(html.index('<div class="deskscrub">'), html.index('id="then-bar"'))
        self.assertLess(html.index('id="then-bar"'), html.index('class="desklegend"'))
        bar = re.search(r'<section class="thenbar" id="then-bar".*?</section>', html, re.S).group(0)
        self.assertIn('aria-label="Then and now" hidden>', bar)
        self.assertIn('<label class="thenfield">Source <select class="toolsel" id="then-source">', bar)
        self.assertIn('<label class="thenfield">Event <select class="toolsel" id="then-event">', bar)
        for words, ident in (("Street View", "then-street"), ("Copy link", "then-copy"),
                             ("Exit", "then-exit")):
            self.assertIn(f'<button type="button" class="toolbtn" id="{ident}">{words}</button>', bar)
        self.assertIn('<input type="checkbox" id="then-names" checked> Roads and names</label>', bar)
        for key, where in (("a", "left side"), ("b", "right side")):
            self.assertIn(f'role="group" aria-labelledby="then-head-{key}"', bar)
            self.assertIn(f'id="then-back-{key}" aria-label="Earlier, {where}">&#9664;</button>', bar)
            self.assertIn(f'id="then-next-{key}" aria-label="Later, {where}">&#9654;</button>', bar)
            self.assertIn(f'<input type="date" class="thendate" id="then-date-{key}" '
                          f'min="2000-01-01" max="2026-09-29" aria-label="Date, {where}">', bar)
            self.assertIn(f'id="then-cap-{key}" aria-label="Capture, {where}" hidden></select>', bar)
            self.assertIn(f'<p class="thenwords" id="then-words-{key}"></p>', bar)
        self.assertIn('<p class="thenread" id="then-read" role="status"></p>', bar)
        self.assertIn('<a id="then-gmaps" href="https://www.google.com/maps" target="_blank" '
                      'rel="noopener">', bar)

    def test_the_menus_offer_the_sources_and_the_events(self):
        bar = re.search(r'<section class="thenbar".*?</section>', self.page(), re.S).group(0)
        source = re.search(r'id="then-source">(.*?)</select>', bar).group(1)
        self.assertEqual(re.findall(r'<option value="(\w+)">', source),
                         ["archive", "hls", "modis", "ndvi", "sst"])
        event = re.search(r'id="then-event">(.*?)</select>', bar).group(1)
        self.assertTrue(event.startswith('<option value="now">A year ago → the latest '
                                         "(Sep 2025 → Sep 2026)</option>"))
        self.assertIn('<optgroup label="2014-16 El Niño, peaking OND 2015 at RONI +2.6">'
                      '<option value="ep0-before">A year before the peak → the peak '
                      "(Nov 2014 → Nov 2015)</option><option value=\"ep0-after\">The peak → a "
                      "year after (Nov 2015 → Nov 2016)</option></optgroup>", event)
        self.assertTrue(event.endswith('<option value="">Dates of your own</option>'))

    def test_the_strip_draws_each_season_at_its_month(self):
        bar = re.search(r'<section class="thenbar".*?</section>', self.page(), re.S).group(0)
        strip = re.search(r'<svg class="thenstrip" id="then-strip".*?</svg>', bar, re.S).group(0)
        self.assertIn('viewBox="0 -30 321 60" preserveAspectRatio="none" role="img" '
                      'aria-label="RONI by season since January 2000', strip)
        # OND 2015, centred on November 2015: month 190, +2.6 drawn 26 units up.
        self.assertIn('<rect class="warm" x="190" y="-26" width="1" height="26"/>', strip)
        # JJA 2016's -0.4, centred on July 2016, short of the line; SON 2016's -0.7 below it.
        self.assertIn('<rect class="flat" x="198" y="0" width="1" height="4"/>', strip)
        self.assertIn('<rect class="cool" x="201" y="0" width="1" height="7"/>', strip)
        self.assertEqual(len(re.findall(r"<rect ", strip)), 34)   # the two zero seasons drawn as none
        for key in ("a", "b"):
            self.assertIn(f'<line class="thenline" id="then-line-{key}"', strip)
        years = re.search(r'<div class="thenyears" aria-hidden="true">(.*?)</div>', bar).group(1)
        self.assertEqual(re.findall(r">(\d{4})<", years), ["2000", "2005", "2010", "2015", "2020", "2025"])
        self.assertIn('<span style="left:56.07%">2015</span>', years)

    def test_the_page_carries_the_payload_and_the_script(self):
        html = self.page()
        raw = re.search(r'<script id="desk-data" type="application/json">(.*?)</script>',
                        html, re.S).group(1)
        data = json.loads(raw)
        self.assertEqual([s["id"] for s in data["then"]["sources"]],
                         ["archive", "hls", "modis", "ndvi", "sst"])
        self.assertEqual(data["then"]["built"], "2026-09-29")
        js = stormdesk.script()
        self.assertNotIn("/*THENNOW*/", js)
        self.assertIn(thennow._JS, js)
        self.assertLess(js.index(worldmap._JS), js.index(thennow._JS))
        self.assertLess(js.index(thennow._JS), js.index("// ---- start ----"))
        self.assertIn("  S.then = null;", js)

    def test_the_styles_use_the_page_tokens_and_44_px_controls(self):
        css = thennow.css()
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", css), [])
        self.assertIn(".thenstep { width: 44px; height: 44px;", css)
        self.assertIn(".thendate { min-height: 44px;", css)
        self.assertIn(".thenfig { display: inline-flex; align-items: center; gap: 4px; "
                      "touch-action: none; }", css)
        self.assertIn("#map.arming { cursor: crosshair; }", css)
        self.assertIn(".thenstrip .warm { fill: var(--warm); }", css)
        self.assertIn(".thenstrip .cool { fill: var(--cool); }", css)
        self.assertIn(thennow.css(), self.page())
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenMarkup -v`
Expected: 7 tests ERROR, `AttributeError: module 'elnino.thennow' has no attribute 'css'` in the CSS test and missing `id="then-enter"` (AttributeError on `.group` of None) in the others.

- [ ] **Step 3: Add the markup, the CSS and the script's first lines to `elnino/thennow.py`**

Append to `elnino/thennow.py`:

```python
# ----------------------------------------------------------------------------
# the page's parts
# ----------------------------------------------------------------------------
# The figure on the Enter button, and under the pointer while it is carried.
_FIGURE = ('<svg class="thenfigsvg" viewBox="0 0 24 24" width="20" height="20" '
           'aria-hidden="true" focusable="false"><circle cx="12" cy="4.6" r="3.1"/>'
           '<path d="M8.6 9.4h6.8l-1 7.2h-1.4l-.6 6.2h-2.8l-.6-6.2H9.6z"/></svg>')


def enter_button() -> str:
    """The toolbar's figure: pressed, it arms the map for a tap; carried, it
    is let go over the place to enter."""
    return ('<button type="button" class="toolbtn thenfig" id="then-enter" aria-pressed="false" '
            f'aria-describedby="then-enter-how">{_FIGURE} Enter</button>'
            '<span class="thenhow" id="then-enter-how">Drag the figure onto the map, or press '
            "it and tap a place, to see that place before and after El Niño.</span>"
            f'<span class="thenghost" id="then-ghost" aria-hidden="true" hidden>{_FIGURE}</span>')


def map_parts() -> str:
    """What Enter puts on the map: the hint while armed, a chip either side of
    the divider naming its date, and the ring under a carried figure."""
    return ('<p class="thenhint ui" id="then-hint" role="status" hidden>Tap a place to enter it, '
            "or press Enter for the middle of the view. Esc cancels.</p>"
            '<div class="thenchip ui" id="then-chip-a" hidden></div>'
            '<div class="thenchip ui" id="then-chip-b" hidden></div>'
            '<span class="thenring" id="then-ring" aria-hidden="true" hidden></span>')


def _events(presets) -> str:
    """The event menu: now first, each El Nino's two choices under its name,
    and the reader's own dates last."""
    out, group = [], None
    for p in presets:
        if p["group"] != group:
            if group:
                out.append("</optgroup>")
            if p["group"]:
                out.append(f'<optgroup label="{esc(p["group"])}">')
            group = p["group"]
        out.append(f'<option value="{esc(p["id"])}">{esc(p["label"])}</option>')
    if group:
        out.append("</optgroup>")
    out.append('<option value="">Dates of your own</option>')
    return "".join(out)


def _side(key: str, head: str, where: str, built: str) -> str:
    """One side's date: a step back, the date (or the archive's captures), a
    step on, and the season around it beneath."""
    return (f'<div class="thenside" role="group" aria-labelledby="then-head-{key}">'
            f'<span class="thenhead" id="then-head-{key}">{head}</span><div class="thenpick">'
            f'<button type="button" class="thenstep" id="then-back-{key}" '
            f'aria-label="Earlier, {where}">&#9664;</button>'
            f'<input type="date" class="thendate" id="then-date-{key}" min="2000-01-01" '
            f'max="{built}" aria-label="Date, {where}">'
            f'<select class="toolsel thencap" id="then-cap-{key}" aria-label="Capture, {where}" '
            "hidden></select>"
            f'<button type="button" class="thenstep" id="then-next-{key}" '
            f'aria-label="Later, {where}">&#9654;</button></div>'
            f'<p class="thenwords" id="then-words-{key}"></p></div>')


def _strip(then: dict) -> str:
    """The index by season from January 2000, one unit a month and ten a
    degree: warm bars up, cool bars down, the ones short of 0.5 flat grey, the
    +/-0.5 lines dashed, and a line at each side's date; the years beneath."""
    n = then["strip"]["months"]
    rects = []
    for key, _label, shown, _words in then["seasons"]:
        x = _month_index(key)
        if not 0 <= x < n or not shown:
            continue
        kind = "warm" if shown >= 0.5 else "cool" if shown <= -0.5 else "flat"
        height = round(min(abs(shown), 3.0) * 10, 1)
        top = -height if shown > 0 else 0
        rects.append(f'<rect class="{kind}" x="{x}" y="{top:g}" width="1" height="{height:g}"/>')
    first = int(then["strip"]["from"][:4])
    years = "".join(f'<span style="left:{_month_index(f"{y}-01") / n * 100:.2f}%">{y}</span>'
                    for y in range(first, first + (n - 1) // 12 + 1, 5))
    return (f'<div class="thenstripbox"><svg class="thenstrip" id="then-strip" '
            f'viewBox="0 -30 {n} 60" preserveAspectRatio="none" role="img" '
            f'aria-label="{esc(then["index"])} by season since January 2000: warm above zero, '
            "cool below, the plus and minus 0.5 lines dashed, a line at each side’s date. "
            'Tap a month to move the nearer side there.">'
            f'<line class="thenhalf" x1="0" x2="{n}" y1="-5" y2="-5"/>'
            f'<line class="thenhalf" x1="0" x2="{n}" y1="5" y2="5"/>'
            + "".join(rects)
            + f'<line class="thenzero" x1="0" x2="{n}" y1="0" y2="0"/>'
            '<line class="thenline" id="then-line-a" x1="-1" x2="-1" y1="-30" y2="30"/>'
            '<line class="thenline" id="then-line-b" x1="-1" x2="-1" y1="-30" y2="30"/>'
            f'</svg><div class="thenyears" aria-hidden="true">{years}</div></div>')


def bar(then: dict) -> str:
    """The bar under the map while a place is entered, in the scrubber's
    place: the source, the event, Street View, the link, the names and Exit;
    each side's date with the season around it; the strip; the readout."""
    sources = "".join(f'<option value="{esc(s["id"])}">{esc(s["name"])}</option>'
                      for s in then["sources"])
    return ('<section class="thenbar" id="then-bar" aria-label="Then and now" hidden>'
            '<div class="thenrow">'
            f'<label class="thenfield">Source <select class="toolsel" id="then-source">{sources}'
            "</select></label>"
            '<label class="thenfield">Event <select class="toolsel" id="then-event">'
            f'{_events(then["presets"])}</select></label>'
            '<button type="button" class="toolbtn" id="then-street">Street View</button>'
            '<button type="button" class="toolbtn" id="then-copy">Copy link</button>'
            '<label class="check"><input type="checkbox" id="then-names" checked> Roads and names'
            "</label>"
            '<button type="button" class="toolbtn" id="then-exit">Exit</button></div>'
            '<div class="thensides">'
            + _side("a", "Left: the earlier date", "left side", then["built"])
            + _side("b", "Right: the later date", "right side", then["built"])
            + "</div>" + _strip(then)
            + '<p class="thenread" id="then-read" role="status"></p>'
            '<p class="thennote" id="then-note"></p>'
            '<p class="thenlinks"><a id="then-gmaps" href="https://www.google.com/maps" '
            'target="_blank" rel="noopener">Street View in Google Maps, where “See more '
            "dates” holds its older panoramas ↗</a></p>"
            "</section>")


def css() -> str:
    """The bar's, the chips' and the figure's rules, over the page's tokens."""
    return """
.thenfig { display: inline-flex; align-items: center; gap: 4px; touch-action: none; }
.thenfigsvg { fill: currentColor; }
.thenhow { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%);
  white-space: nowrap; }
.thenghost { position: fixed; left: 0; top: 0; z-index: 60; margin: -34px 0 0 -10px;
  color: var(--ink); pointer-events: none; }
#map.arming { cursor: crosshair; }
.thenhint { position: absolute; left: 50%; top: 10px; transform: translateX(-50%); z-index: 10;
  margin: 0; max-width: calc(100% - 140px); padding: 8px 12px; border-radius: 10px;
  background: var(--ink); color: var(--surface); font-size: 0.8rem; }
.thenring { position: absolute; left: 0; top: 0; z-index: 8; width: 30px; height: 30px;
  margin: -15px 0 0 -15px; border-radius: 50%; border: 2px solid var(--ink);
  box-shadow: 0 0 0 2px var(--surface); pointer-events: none; }
.thenchip { position: absolute; bottom: 26px; z-index: 9; max-width: calc(50% - 44px);
  padding: 4px 8px; border-radius: 8px; border: 1px solid var(--border);
  background: color-mix(in srgb, var(--surface) 90%, transparent); color: var(--ink);
  font: 600 0.74rem var(--font); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.thenbar { background: var(--surface); border-top: 1px solid var(--border); padding: 6px 16px 8px;
  font-size: 0.82rem; color: var(--ink); }
.thenrow { display: flex; flex-wrap: wrap; gap: 6px 10px; align-items: center; }
.thenfield { display: inline-flex; align-items: center; gap: 6px; color: var(--ink2); }
.thenfield .toolsel { max-width: min(62vw, 380px); }
.thensides { display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
  gap: 6px 16px; margin: 6px 0 2px; }
.thenside { min-width: 0; }
.thenhead { font-size: 0.76rem; font-weight: 600; color: var(--ink2); }
.thenpick { display: flex; align-items: center; gap: 4px; }
.thenstep { width: 44px; height: 44px; border-radius: 10px; border: 1px solid var(--border);
  background: var(--surface); color: var(--ink); cursor: pointer; flex: 0 0 auto; }
.thenstep:disabled { opacity: 0.45; cursor: default; }
.thendate { min-height: 44px; padding: 0 8px; border-radius: 10px; border: 1px solid var(--border);
  background: var(--surface); color: var(--ink); font: 500 0.85rem var(--font); min-width: 0; }
.thencap { flex: 1 1 auto; min-width: 0; }
.thenwords { margin: 2px 0 0; color: var(--ink); }
.thenstripbox { position: relative; margin: 8px 0 18px; cursor: pointer; }
.thenstrip { display: block; width: 100%; height: 60px; background: var(--plane);
  border-radius: 6px; }
.thenstrip .warm { fill: var(--warm); }
.thenstrip .cool { fill: var(--cool); }
.thenstrip .flat { fill: var(--ink2); opacity: 0.45; }
.thenstrip line { vector-effect: non-scaling-stroke; }
.thenhalf { stroke: var(--ink2); stroke-width: 1px; stroke-dasharray: 3 3; opacity: 0.7; }
.thenzero { stroke: var(--ink2); stroke-width: 1px; }
.thenline { stroke: var(--ink); stroke-width: 2px; }
.thenyears { position: absolute; left: 0; right: 0; top: 62px; height: 14px;
  font-size: 0.66rem; color: var(--ink2); }
.thenyears span { position: absolute; transform: translateX(-50%); }
.thenread, .thennote { margin: 4px 0; color: var(--ink2); }
.thenread:empty, .thennote:empty { display: none; }
.thenlinks { margin: 4px 0 0; }
.thenlinks a { color: var(--s1); min-height: 32px; display: inline-flex; align-items: center; }
"""


# Taken into the desk's script at its /*THENNOW*/ marker, after the map's.
_JS = r"""
  // ---- then and now: a place before and after El Nino (thennow.py) ---------
  // Enter drops into a point of the map, as Google Maps' figure does, and
  // shows the same ground at two dates either side of the divider, the
  // earlier on the left, each named with the season of the index around it.
  // Each side is a layer of the page's own kinds, LAYERS["then-a"] and
  // LAYERS["then-b"], so the compare view draws them; the engine asks
  // S.then wherever it must not draw today's storms, tiles and composite
  // over another day.
  S.then = null;
  function thenSrc(id) {
    var list = (D.then && D.then.sources) || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === id) return list[i];
    return null;
  }
"""
```

- [ ] **Step 4: Put the parts into the page (`elnino/stormdesk.py`)**

Line 25, the import:

```python
from . import alerts, coastline, cyclones, exposure, fields, outlook, thennow, worldmap
```

In `_map()`, before the zoom buttons: replace

```python
        '<button type="button" class="deskpill herepill ui" id="herego" hidden>'
        '</button>'
        '<div class="deskzoom ui">'
```

with

```python
        '<button type="button" class="deskpill herepill ui" id="herego" hidden>'
        '</button>'
        + thennow.map_parts() +
        '<div class="deskzoom ui">'
```

In `page()`, after `data["enso"] = worldmap.payload(state)`:

```python
    data["then"] = thennow.payload(state)
```

replace `enso = worldmap.controls(focus, data["enso"]["now"], data["enso"]["next"])` with

```python
    enso = thennow.enter_button() + worldmap.controls(focus, data["enso"]["now"],
                                                        data["enso"]["next"])
```

replace `<style>{shell_css()}{fields.ramp_css()}{css()}{worldmap.css()}</style>` with

```python
<style>{shell_css()}{fields.ramp_css()}{css()}{worldmap.css()}{thennow.css()}</style>
```

and replace

```python
{_map()}
{_scrubber()}
```

with

```python
{_map()}
{_scrubber()}
{thennow.bar(data["then"])}
```

Replace `script()`:

```python
def script() -> str:
    """The page's script: the desk's, with the map's and the then-and-now
    view's taken in at their markers."""
    return (_JS.replace("  /*WORLDMAP*/\n", worldmap._JS)
            .replace("  /*THENNOW*/\n", thennow._JS))
```

and in `_JS`, replace

```js
  /*WORLDMAP*/
  // ---- start ------------------------------------------------------------------
```

with

```js
  /*WORLDMAP*/
  /*THENNOW*/
  // ---- start ------------------------------------------------------------------
```

- [ ] **Step 5: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 25 tests, OK.

- [ ] **Step 6: Run the desk's page tests**

Run: `python -m unittest tests.test_tracker.TestStormDeskPage tests.test_tracker.TestWording -v`
Expected: OK (the page's own tests unchanged).

- [ ] **Step 7: Mutation check**

Delete `+ thennow.map_parts() +` from `_map()` (leave the two strings joined); run `python -m unittest tests.test_thennow.TestThenMarkup`; expected FAIL in `test_the_hint_chips_and_ring_are_on_the_map`. Put it back; run again; expected OK.

- [ ] **Step 8: Commit**

```bash
git add elnino/thennow.py elnino/stormdesk.py tests/test_thennow.py
git commit -m "Then and now: the Enter figure, the bar, the map's chips and the script's place" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: The script's calendar: GIBS's times, real days and the season around a date

**Files:**
- Modify: `elnino/thennow.py` (`_JS`, appended)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: the payload `D.then` (Task 1: `seasons` rows `[key, label, shown, words]`, `presets` `{id, group, label, left, right}`, `index`, `strip {from, months}`); `thenSrc(id)` (Task 2); the page's `dayZ(t)`, `stamp(key)`, `shiftDay(key, n)`, `dayText(key)`, `signedText(v, digits)`, `MONTHS`.
- Produces: `DAY` (ms); `dayNo(key) -> int` (days since 1970); `keyOf(n) -> "YYYY-MM-DD"`; `realDay(text) -> bool`; `parseSpans(xmlText) -> [[first, last, stepDays]]` sorted, whole days; `snapTime(spans, key) -> key | null` (nearest listed time, the earlier on a tie); `stepTime(spans, key, by) -> key | null` (by -1 or +1); `monthIndex(key) -> int` (months since Jan 2000); `monthText(key)`; `seasonAt(key) -> row | null`; `ensoWords(key) -> str`; `ensoShort(key) -> str`; `presetOf(id) -> preset | null`. For the tests: the node harness `PRELUDE`, `ENGINE`, `THEN`, `_d(then)`, `_run(case, body, then=None, extra="")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
# ----------------------------------------------------------------------------
# the page's script, run under node
# ----------------------------------------------------------------------------
# thennow._JS runs whole, as the page runs it, strict, over a DOM of plain
# objects, a clock that moves only when told and a network that answers from
# a table. The page's own functions it calls are taken from the page's script
# as written; what would draw, fly or change the layer is recorded instead.
PRELUDE = r"""
var NODES = {}, LISTS = {}, SELECTED = {}, DOC = {}, ASKED = [], IMAGES = [], COPIED = [], CALLS = [];
function note(what) { CALLS.push(what); }
function El(id, tag) {
  var own = {};
  this.id = id || ""; this.tagName = (tag || "div").toUpperCase(); this.attrs = {}; this.style = {};
  this.hidden = false; this.value = ""; this.checked = false; this.disabled = false;
  this.textContent = ""; this.innerHTML = ""; this.listeners = {};
  this.box = {left: 0, top: 0, width: 800, height: 600};
  this.classList = {
    add: function (c) { own[c] = true; }, remove: function (c) { delete own[c]; },
    contains: function (c) { return !!own[c]; },
    toggle: function (c, on) { on = on === undefined ? !own[c] : !!on; if (on) own[c] = true; else delete own[c]; return on; }
  };
}
El.prototype.setAttribute = function (k, v) { this.attrs[k] = String(v); };
El.prototype.getAttribute = function (k) { return k in this.attrs ? this.attrs[k] : null; };
El.prototype.hasAttribute = function (k) { return k in this.attrs; };
El.prototype.removeAttribute = function (k) { delete this.attrs[k]; };
El.prototype.addEventListener = function (type, f) { (this.listeners[type] = this.listeners[type] || []).push(f); };
El.prototype.fire = function (type, e) {
  e = e || {};
  e.type = type; e.target = e.target || this; e.currentTarget = this;
  e.preventDefault = function () { e.defaultPrevented = true; };
  e.stopPropagation = function () {};
  (this.listeners[type] || []).forEach(function (f) { f(e); });
  return e;
};
El.prototype.getBoundingClientRect = function () {
  var b = this.box;
  return {left: b.left, top: b.top, width: b.width, height: b.height, right: b.left + b.width, bottom: b.top + b.height};
};
El.prototype.closest = function () { return null; };
El.prototype.querySelector = function () { return null; };
El.prototype.querySelectorAll = function () { return []; };
El.prototype.setPointerCapture = function () {};
El.prototype.scrollIntoView = function () { note("scroll " + this.id); };
El.prototype.appendChild = function (c) { return c; };
El.prototype.remove = function () {};
// A canvas reads back the colour of the last image drawn on it.
var CTX = {rgba: [0, 0, 0, 0], at: null, drawImage: function (img) { CTX.rgba = img._rgba || [0, 0, 0, 0]; },
           clearRect: function () {},
           getImageData: function (x, y, w, h) {
             CTX.at = [x, y, w, h];
             var out = [];
             for (var i = 0; i < w * h; i++) out.push(CTX.rgba[0], CTX.rgba[1], CTX.rgba[2], CTX.rgba[3]);
             return {data: out};
           }};
var document = {
  activeElement: null, documentElement: new El("html"), body: new El("body"),
  getElementById: function (id) { return NODES[id] || (NODES[id] = new El(id)); },
  createElement: function (tag) {
    var el = new El("", tag);
    if (tag === "canvas") el.getContext = function () { return CTX; };
    return el;
  },
  querySelector: function (sel) { return SELECTED[sel] || null; },
  querySelectorAll: function (sel) { return LISTS[sel] || []; },
  addEventListener: function (type, f) { (DOC[type] = DOC[type] || []).push(f); }
};
// A key pressed with the focus on an element (the page's body by default).
function press(key, target) {
  var e = {key: key, target: target || document.body, defaultPrevented: false};
  e.preventDefault = function () { e.defaultPrevented = true; };
  (DOC.keydown || []).forEach(function (f) { f(e); });
  return e;
}
var window = {innerHeight: 900, addEventListener: function () {}, matchMedia: function () { return {matches: false}; }};
var location = {href: "file:///C:/elnino/output/map.html", hash: "", protocol: "file:"};
var history = {replaceState: function (s, t, url) { note("replaceState " + url); location.href = url; location.hash = ""; }};
var navigator = {onLine: true, clipboard: {writeText: function (text) { COPIED.push(text); return Promise.resolve(); }}};
// The clock: Date.now is fixed; timers run when advance() passes them.
var NOW = Date.parse("2026-09-29T12:00:00Z"), TIMERS = [], TIMER = 0, CLOCK = 0;
Date.now = function () { return NOW; };
function setTimeout(f, ms) { TIMERS.push({id: ++TIMER, at: CLOCK + (ms || 0), f: f}); return TIMER; }
function clearTimeout(id) { TIMERS = TIMERS.filter(function (t) { return t.id !== id; }); }
function advance(ms) {
  CLOCK += ms;
  var due = TIMERS.filter(function (t) { return t.at <= CLOCK; });
  TIMERS = TIMERS.filter(function (t) { return t.at > CLOCK; });
  due.forEach(function (t) { t.f(); });
}
// Every answer and image load waiting to happen, let happen.
function flush(rounds) {
  return new Promise(function (done) {
    var n = rounds || 60;
    (function next() { if (n-- <= 0) done(); else setImmediate(next); })();
  });
}
// The network: the latest route whose words are in the URL answers. An
// object is JSON, a string text, a number a status, an Error a failure,
// "hang" no answer until the request is given up, a function its result.
var ROUTES = [];
function route(words, answer) { ROUTES.unshift([words, answer]); }
function fetch(url, opts) {
  ASKED.push(url);
  var answer = 404;
  for (var i = 0; i < ROUTES.length; i++) if (url.indexOf(ROUTES[i][0]) >= 0) { answer = ROUTES[i][1]; break; }
  if (typeof answer === "function") answer = answer(url);
  if (answer === "hang") return new Promise(function (ok, no) {
    if (opts && opts.signal) opts.signal.addEventListener("abort", function () { no(new Error("aborted")); });
  });
  if (answer instanceof Error) return Promise.reject(answer);
  var status = typeof answer === "number" ? answer : 200, body = typeof answer === "number" ? "" : answer;
  return Promise.resolve({ok: status >= 200 && status < 300, status: status,
    json: function () { return Promise.resolve(typeof body === "string" ? JSON.parse(body) : JSON.parse(JSON.stringify(body))); },
    text: function () { return Promise.resolve(typeof body === "string" ? body : JSON.stringify(body)); }});
}
// Images: the latest rule whose words are in the URL paints it with an
// RGBA (as a canvas reads it back); false, or no rule, and it fails.
var PAINT = [];
function paint(words, rgba) { PAINT.unshift([words, rgba]); }
function Image() {}
Object.defineProperty(Image.prototype, "src", {
  get: function () { return this._src; },
  set: function (url) {
    var img = this, rgba = false;
    this._src = url; IMAGES.push(url);
    for (var i = 0; i < PAINT.length; i++) if (url.indexOf(PAINT[i][0]) >= 0) { rgba = PAINT[i][1]; break; }
    setImmediate(function () {
      if (rgba) { img._rgba = rgba; if (img.onload) img.onload(); }
      else if (img.onerror) img.onerror();
    });
  }
});
function $(id) { return document.getElementById(id); }
var map = $("map"), divider = $("divider"), statusPill = $("status");
var TILE = 256, MINZ = 1, MAXZ = 13, UNIT = 1048576, HOUR = 3600000, NM = 1.852;
var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
var NODATA = {}, MAPS = {}, GOT = {}, DOM = {}, AGAIN = {}, looks = {}, NO_ANSWER = "no answer", anim = 0;
var S = {x: 0.5, y: 0.5, z: 3, w: 800, h: 600, layer: "streets", second: "infrared", compare: false,
         split: 0.3, loop: false, frame: 0, scrub: 0, inView: {}, inViewB: null, show: {}, refs: {},
         pin: null, here: null, google: null, day: null, imagery: "ok",
         enso: {variable: "PRECIP", season: "SON", tiles: {}}};
var LAYERS = {
  streets: {id: "streets", kind: "map", name: "Streets", source: "Esri World Street Map",
            tiles: "https://streets/{z}/{y}/{x}", zoom: 19, grey: true, credit: "Streets: Esri."},
  satellite: {id: "satellite", kind: "map", name: "Satellite", source: "Esri World Imagery",
              tiles: "https://imagery/{z}/{y}/{x}", over: ["https://roads/{z}/{y}/{x}", "https://places/{z}/{y}/{x}"],
              zoom: 19, grey: true, credit: "Imagery: Esri."},
  infrared: {id: "infrared", kind: "imagery", name: "Infrared", satellites: {}, tms: "GoogleMapsCompatible_Level6",
             zoom: 6, format: "png", step: "PT10M"},
  detail: {id: "detail", kind: "imagery", name: "Detail (30 m)", stack: ["HLS_L30", "HLS_S30"],
           tms: "GoogleMapsCompatible_Level12", zoom: 12, format: "png", step: "P1D", pixel_km: 0.03,
           credit: "HLS: NASA."}
};
var PLACES = [["Manaus", "Brazil", "Amazonas", 2219580, -60.025, -3.1, 0],
              ["Suva", "Fiji", "Central", 93970, 178.44, -18.14, 1]];
// What the script calls on the page, recorded.
var FLIGHTS = [], LAND = {};
function dirty() { note("dirty"); }
function requestRender() { note("render"); }
function ask(s) {}
function owners() { return []; }
function frameOf() { return null; }
function cancelAnimationFrame() {}
function animate(to, ms) { FLIGHTS.push({x: to.x, y: to.y, z: to.z, ms: ms}); S.x = to.x; S.y = to.y; S.z = to.z; }
function settle() { note("settle"); }
function setLayer(id) { note("setLayer " + id); S.layer = id; return true; }
function setCompare(on) { note("setCompare " + on); S.compare = !!on; return S.compare; }
function setLoop(on) { note("setLoop " + on); S.loop = !!on; return S.loop; }
function hereAt(lon, lat, label) { note("hereAt " + label); S.here = {lon: lon, lat: lat, label: label}; }
function googleFrame(kind) { note("googleFrame " + kind); }
function tileFailed() { note("tileFailed " + this._name); }
function cellAt(name, season, lon, lat) { return {value: LAND[Math.round(lon) + "," + Math.round(lat)] ? 1 : null}; }
"""

# The page's functions the script calls, as the page's script has them.
ENGINE = ("clamp", "wrap", "rad", "deg", "mx", "my", "lonOf", "latOf", "world", "origin", "near",
          "toWorld", "km", "pad2", "dayZ", "stamp", "shiftDay", "dayText", "esc", "named", "where",
          "kms", "nearestPlace", "pin", "signedText", "classify", "wrap180", "googleZoom",
          "googleLinks", "tileUrl", "xyzUrl", "present", "xyzCells", "source", "timed", "cells",
          "labelled", "labelledBase", "overSpecs", "gotKey", "tilesDown", "look", "covered", "imageOn",
          "mapDown", "nasaDown", "baseDown")

# The page's payload for the 2014-16 event, built on 29 September 2026.
THEN = thennow.payload(state_with(EVENT, run_at="2026-09-29T12:00:00+00:00"))


def _d(then) -> dict:
    """The page's data as the script reads it: the then-and-now payload and
    GIBS's addresses, with test hosts."""
    return {"then": then, "enso": {"now": "SON", "hide_above": 12}, "layers": [],
            "gibs": {"domains": "https://gibs/{layer}/{tms}/{start}--{end}.xml",
                     "tiles": "https://gibs/{layer}/{time}/{tms}/{z}/{y}/{x}.{ext}",
                     "static": "https://gibs/{layer}/{tms}/{z}/{y}/{x}.{ext}",
                     "acknowledge": "We acknowledge the use of imagery from NASA's GIBS.",
                     "satellites": {}}}


def _run(case, body: str, then=None, extra: str = ""):
    """What an async body prints as JSON, run after the whole script."""
    js = stormdesk.script()
    functions = "\n".join(_js_function(js, name) for name in ENGINE)
    script = ('(function () {\n"use strict";\n' + PRELUDE + "var D = " + json.dumps(_d(then or THEN)) + ";\n"
              + functions + "\n" + extra + "\n" + thennow._JS
              + "\n(async function () {\n  try {\n" + body + "\n  } catch (err) {\n"
              "    console.log(JSON.stringify({error: String(err && err.stack || err)}));\n  }\n})();\n})();\n")
    return _node_json(case, script)


class TestThenScript(unittest.TestCase):
    """The script's own names: one that is also the page's would replace the
    page's function for the whole page."""

    @staticmethod
    def top_names(js: str) -> set:
        return set(re.findall(r"^  function ([A-Za-z_$][\w$]*)", js, re.M)) | {
            name for line in re.findall(r"^  var (.*)$", js, re.M)
            for name in re.findall(r"(?:^|, )([A-Za-z_$][\w$]*) =", line)}

    def test_no_name_of_the_script_is_one_of_the_page_s(self):
        mine = self.top_names(thennow._JS)
        self.assertIn("thenSrc", mine)
        self.assertEqual(sorted(mine & (self.top_names(stormdesk._JS) | self.top_names(worldmap._JS))), [])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenTimesRuns(unittest.TestCase):
    """GIBS's times read and stepped through, a date checked, and the season
    around a date put in words."""

    S16 = '[["2015-01-01", "2015-12-19", 16], ["2016-01-01", "2016-12-18", 16]]'

    def test_gibs_times_are_read_as_spans_of_whole_days(self):
        got = _run(self, r"""
          var text = "<Domain>2001-01-01/2001-12-19/P16D,2000-03-05T00:00:00Z/2000-12-18T00:00:00Z/P16D," +
                     "2015-06-01,2016-01-01/2016-02-01/PT10M,2016-03-01/2016-02-01/P1D," +
                     "2016-02-30/2016-03-05/P1D</Domain>";
          console.log(JSON.stringify([parseSpans(text), parseSpans("<Domain></Domain>"), parseSpans("nonsense")]));
        """)
        self.assertEqual(got, [[["2000-03-05", "2000-12-18", 16], ["2001-01-01", "2001-12-19", 16],
                                ["2015-06-01", "2015-06-01", 1]], [], []])

    def test_a_date_snaps_to_the_nearest_time_listed_the_earlier_on_a_tie(self):
        got = _run(self, "var s = " + self.S16 + r""";
          console.log(JSON.stringify(["2015-01-05", "2015-01-10", "2015-12-31", "2015-12-25", "2014-06-01",
                                      "2017-03-01", "2015-01-09"].map(function (d) { return snapTime(s, d); })
                                     .concat([snapTime([], "2015-01-01")])));
        """)
        self.assertEqual(got, ["2015-01-01", "2015-01-17", "2016-01-01", "2015-12-19", "2015-01-01",
                               "2016-12-18", "2015-01-01", None])

    def test_a_step_goes_to_the_time_before_or_after_across_the_turn_of_a_year(self):
        got = _run(self, "var s = " + self.S16 + r""";
          console.log(JSON.stringify([["2016-01-01", -1], ["2015-12-19", 1], ["2014-06-01", 1], ["2015-01-01", 1],
                                      ["2015-01-20", 1], ["2016-12-18", 1], ["2015-01-01", -1], ["2015-01-17", -1],
                                      ["2015-01-10", -1], ["2017-05-01", -1]].map(function (p) {
            return stepTime(s, p[0], p[1]);
          })));
        """)
        self.assertEqual(got, ["2015-12-19", "2016-01-01", "2015-01-01", "2015-01-17", "2015-02-02", None,
                               None, "2015-01-01", "2015-01-01", "2016-12-18"])

    def test_a_daily_layer_with_a_gap_snaps_and_steps_over_it(self):
        got = _run(self, r"""
          var s = [["2000-02-24", "2000-04-25", 1], ["2000-04-27", "2000-06-01", 1]];
          console.log(JSON.stringify([snapTime(s, "2000-04-26"), stepTime(s, "2000-04-25", 1),
                                      stepTime(s, "2000-04-27", -1), snapTime(s, "1999-01-01"),
                                      stepTime(s, "2000-03-01", 1)]));
        """)
        self.assertEqual(got, ["2000-04-25", "2000-04-27", "2000-04-25", "2000-02-24", "2000-03-02"])

    def test_a_day_of_the_calendar_is_told_from_one_that_is_not(self):
        got = _run(self, r"""
          console.log(JSON.stringify(["2015-02-28", "2015-02-30", "", "2015-2-3", null, "2016-02-29",
                                      "2015-02-29", "2015-13-01"].map(realDay)));
        """)
        self.assertEqual(got, [True, False, False, False, False, True, False, False])

    def test_a_date_is_named_with_the_season_around_it(self):
        got = _run(self, r"""
          console.log(JSON.stringify(["2015-11-20", "2014-11-15", "2016-11-15", "2014-07-01", "2017-03-01",
                                      "2013-05-01"].map(ensoWords)));
        """)
        self.assertEqual(got, [
            "OND 2015, centred on Nov 2015: RONI +2.6, very strong El Niño, the 2014-16 episode",
            "OND 2014, centred on Nov 2014: RONI +0.6, weak El Niño, the 2014-16 episode",
            "OND 2016, centred on Nov 2016: RONI −0.7, weak La Niña, the 2016 episode, still going",
            "JJA 2014, centred on Jul 2014: RONI 0.0, neutral",
            "after the latest season on record, NDJ 2016 (RONI −0.6, weak La Niña, the 2016 episode, "
            "still going)",
            "no RONI season on record for May 2013"])

    def test_a_chip_names_the_season_short_and_the_latest_after_the_record(self):
        got = _run(self, r"""
          console.log(JSON.stringify(["2015-11-20", "2017-03-01", "2013-05-01"].map(ensoShort)));
        """)
        self.assertEqual(got, ["RONI +2.6, OND 2015", "latest RONI −0.6, NDJ 2016", ""])

    def test_months_on_the_strip_and_the_menu_s_events(self):
        got = _run(self, r"""
          var p = presetOf("ep0-after");
          console.log(JSON.stringify([monthIndex("2015-11-15"), monthIndex("2000-01-31"), monthText("2015-11-15"),
                                      [p.left, p.right], presetOf("nope")]));
        """)
        self.assertEqual(got, [190, 0, "Nov 2015", ["2015-11-15", "2016-11-15"], None])

    def test_the_seasons_are_read_again_when_a_refresh_brings_new_ones(self):
        got = _run(self, r"""
          var first = ensoShort("2015-11-20");
          D.then = JSON.parse(JSON.stringify(D.then));
          D.then.seasons.forEach(function (row) { if (row[0] === "2015-11") row[2] = 2.7; });
          console.log(JSON.stringify([first, ensoShort("2015-11-20")]));
        """)
        self.assertEqual(got, ["RONI +2.6, OND 2015", "RONI +2.7, OND 2015"])
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenScript tests.test_thennow.TestThenTimesRuns -v`
Expected: 10 tests: `TestThenScript` passes (no name of the script is the page's); the 9 `TestThenTimesRuns` FAIL, each having printed `{'error': 'ReferenceError: parseSpans is not defined ...'}` or the like for the function it calls first. `FAILED (failures=9)`.

- [ ] **Step 3: Add the script**

Append to `_JS` in `elnino/thennow.py`, just before its closing `"""`:

```js
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
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 35 tests, OK.

- [ ] **Step 5: Mutation check**

In `ensoShort`, change `key.slice(0, 7) > last[0]` to `key.slice(0, 7) < last[0]`; run `python -m unittest tests.test_thennow.TestThenTimesRuns`; expected FAIL in `test_a_chip_names_the_season_short_and_the_latest_after_the_record`. Put it back; run again; expected OK.

- [ ] **Step 6: Commit**

```bash
git add elnino/thennow.py tests/test_thennow.py
git commit -m "Then and now: GIBS's times, real days and the season around a date" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


---

### Task 4: Esri's archive, walked as Esri's Wayback app walks it

**Files:**
- Modify: `elnino/thennow.py` (`_JS`, appended)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: `D.then.wayback` (Task 1: `config`, `tilemap`, `item`, `level` 16, `metadata_layer` 7, `credit`); `dayNo`, `realDay` (Task 3); the page's `mx`, `my`, `wrap`, `clamp`, `dayZ`.
- Produces: `WAIT` (20000 ms); `fetchWait(url, text) -> Promise` (JSON, or text when `text`; rejects on a status that is not ok or after `WAIT`); `wbReleases() -> Promise<[{id, day, item, tiles, meta}]>` newest first, asked once; `wbTile(lon, lat) -> {z: 16, x, y}` wrapped; `wbWalk(all, t) -> Promise<{list: [release], stopped: "" | "failed" | "unknown"}>` (only a complete walk is kept); `wbCapture(release, lon, lat) -> Promise<{day, res, sensor, provider} | null>`; `wbVersions(lon, lat) -> Promise<{list: [{id, day, item, tiles, capture, when, credit}], stopped}>` newest capture first, one per capture, `stopped: "config"` when the release list failed; `wbNearest(list, key) -> version | null`; `wbCredit(item) -> Promise<string>`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
# Esri's archive as the tests' network holds it: five releases, newest
# first 100, 90, 300 (older than 90 though numbered higher), 80 and 70, and
# one whose title has no date. At the pin, release 100's tilemap says the tile
# last changed in 90; 300's names no release, so it is 300's own; 80's is
# 80's; 70 has no tile there. 90 and 300 show one capture, taken 31 Oct 2021;
# 80's metadata has nothing at the pin.
WB_CONFIG = {str(n): {"itemID": f"i{n}", "itemTitle": f"World Imagery (Wayback {day})",
                      "itemURL": f"https://wb/tile/{n}/{{level}}/{{row}}/{{col}}",
                      "metadataLayerUrl": f"https://md/{day[:4]}_r{n}/MapServer"}
             for n, day in ((100, "2026-08-05"), (90, "2024-03-01"), (300, "2022-01-12"),
                            (80, "2019-06-26"), (70, "2014-02-20"))}
WB_CONFIG["5"] = {"itemID": "i5", "itemTitle": "World Imagery (Wayback)",
                  "itemURL": "https://wb/tile/5/{level}/{row}/{col}",
                  "metadataLayerUrl": "https://md/x_r5/MapServer"}
WB_CAPTURE = {"features": [{"attributes": {"SRC_DATE": 20211031, "SRC_RES": 0.5, "SRC_DESC": "WV02",
                                           "NICE_DESC": "Maxar"}}]}
WB_ROUTES = ("route('waybackconfig.json', " + json.dumps(WB_CONFIG) + ");\n"
             "route('tilemap/100/', {data: [1], select: [90]});\n"
             "route('tilemap/300/', {data: [1]});\n"
             "route('tilemap/80/', {data: [1], select: [80]});\n"
             "route('tilemap/70/', {data: [0]});\n"
             "route('md/2024_r90/', " + json.dumps(WB_CAPTURE) + ");\n"
             "route('md/2022_r300/', " + json.dumps(WB_CAPTURE) + ");\n"
             "route('md/2019_r80/', {features: []});\n")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenArchiveRuns(unittest.TestCase):
    """Esri's archive walked as Esri's Wayback app walks it: the releases,
    the versions of the tile under the pin, when each was taken, the one
    nearest a date, and each release's own credit."""

    def test_the_releases_come_newest_first_with_their_tiles(self):
        got = _run(self, WB_ROUTES + r"""
          var all = await wbReleases();
          console.log(JSON.stringify({ids: all.map(function (r) { return r.id; }),
                                      days: all.map(function (r) { return r.day; }),
                                      tiles: all[0].tiles, meta: all[0].meta, item: all[0].item,
                                      again: (await wbReleases()) === all, asked: ASKED.length}));
        """)
        self.assertEqual(got, {"ids": [100, 90, 300, 80, 70],
                               "days": ["2026-08-05", "2024-03-01", "2022-01-12", "2019-06-26", "2014-02-20"],
                               "tiles": "https://wb/tile/100/{z}/{y}/{x}", "meta": "https://md/2026_r100/MapServer",
                               "item": "i100", "again": True, "asked": 1})

    def test_a_list_that_did_not_come_is_asked_for_again(self):
        got = _run(self, r"""
          route('waybackconfig.json', 500);
          var first = await wbVersions(-60.025, -3.1);
          """ + WB_ROUTES + r"""
          var second = await wbVersions(-60.025, -3.1);
          console.log(JSON.stringify([first, second.list.map(function (v) { return v.id; })]));
        """)
        self.assertEqual(got, [{"list": [], "stopped": "config"}, [90, 80]])

    def test_the_walk_finds_each_release_the_tile_changed_in(self):
        got = _run(self, WB_ROUTES + r"""
          var walk = await wbWalk(await wbReleases(), wbTile(-60.025, -3.1));
          var asked = ASKED.filter(function (u) { return u.indexOf("tilemap") >= 0; });
          var again = await wbWalk(await wbReleases(), wbTile(-60.025, -3.1));
          console.log(JSON.stringify({ids: walk.list.map(function (r) { return r.id; }), stopped: walk.stopped,
                                      asked: asked, kept: again === walk,
                                      more: ASKED.filter(function (u) { return u.indexOf("tilemap") >= 0; }).length}));
        """)
        base = "https://wayback.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tilemap/"
        self.assertEqual(got, {"ids": [90, 300, 80], "stopped": "", "kept": True, "more": 4,
                               "asked": [base + f"{n}/16/33332/21840" for n in (100, 300, 80, 70)]})

    def test_a_walk_cut_short_says_why_and_is_walked_again(self):
        got = _run(self, WB_ROUTES + r"""
          route('tilemap/300/', 500);
          var failed = await wbWalk(await wbReleases(), wbTile(-60.025, -3.1));
          route('tilemap/300/', {data: [1], select: [999]});
          var unknown = await wbWalk(await wbReleases(), wbTile(-60.025, -3.1));
          console.log(JSON.stringify([failed.list.map(function (r) { return r.id; }), failed.stopped,
                                      unknown.list.map(function (r) { return r.id; }), unknown.stopped]));
        """)
        self.assertEqual(got, [[90], "failed", [90], "unknown"])

    def test_versions_sharing_a_capture_are_one_and_the_newest_capture_is_first(self):
        got = _run(self, WB_ROUTES + r"""
          var v = await wbVersions(-60.025, -3.1);
          console.log(JSON.stringify({list: v.list, stopped: v.stopped, asked: ASKED.length,
                                      query: ASKED.filter(function (u) { return u.indexOf("md/2024_r90") >= 0; })[0]}));
        """)
        self.assertEqual(got["stopped"], "")
        self.assertEqual(got["asked"], 8)
        self.assertEqual(got["query"], "https://md/2024_r90/MapServer/7/query?geometry=-60.025000,-3.100000"
                                       "&geometryType=esriGeometryPoint&inSR=4326"
                                       "&spatialRel=esriSpatialRelIntersects&outFields=*"
                                       "&returnGeometry=false&f=json")
        self.assertEqual(got["list"], [
            {"id": 90, "day": "2024-03-01", "item": "i90", "tiles": "https://wb/tile/90/{z}/{y}/{x}",
             "capture": {"day": "2021-10-31", "provider": "Maxar", "sensor": "WV02", "res": 0.5},
             "when": "2021-10-31", "credit": ""},
            {"id": 80, "day": "2019-06-26", "item": "i80", "tiles": "https://wb/tile/80/{z}/{y}/{x}",
             "capture": None, "when": "2019-06-26", "credit": ""}])

    def test_a_metadata_query_that_hangs_is_given_up_after_20_s(self):
        got = _run(self, WB_ROUTES + r"""
          route('md/', 'hang');
          var done = null;
          wbVersions(-60.025, -3.1).then(function (v) { done = v; });
          await flush();
          advance(19999); await flush();
          var waiting = done === null;
          advance(1); await flush();
          """ + WB_ROUTES + r"""
          var again = await wbVersions(-60.025, -3.1);
          console.log(JSON.stringify({waiting: waiting, when: done.list.map(function (v) { return v.when; }),
                                      caps: done.list.map(function (v) { return v.capture; }),
                                      again: again.list.map(function (v) { return v.when; })}));
        """)
        # Given up, each version goes by its release; a failure is not kept,
        # so the next look asks again and has the capture.
        self.assertEqual(got, {"waiting": True, "when": ["2024-03-01", "2022-01-12", "2019-06-26"],
                               "caps": [None, None, None], "again": ["2021-10-31", "2019-06-26"]})

    def test_the_version_nearest_a_date_the_earlier_on_a_tie(self):
        got = _run(self, r"""
          var list = [{id: 90, when: "2021-10-31"}, {id: 80, when: "2019-06-26"}, {id: 70, when: "2014-02-20"}];
          console.log(JSON.stringify(["2016-01-01", "2020-08-13", "2020-08-28", "2020-08-29", "2030-01-01"].map(
            function (d) { return wbNearest(list, d).id; }).concat([wbNearest([], "2020-01-01")])));
        """)
        self.assertEqual(got, [70, 80, 80, 90, 90, None])

    def test_the_pin_s_tile_wraps_at_the_date_line(self):
        got = _run(self, r"""
          console.log(JSON.stringify([[179.99, -18.14], [-179.99, -18.14], [180, 0], [-180, 0], [540.5, 0],
                                      [-60.025, -3.1]].map(function (p) { var t = wbTile(p[0], p[1]); return [t.z, t.x, t.y]; })));
        """)
        self.assertEqual(got, [[16, 65534, 36126], [16, 1, 36126], [16, 0, 32768], [16, 0, 32768],
                               [16, 91, 32768], [16, 21840, 33332]])

    def test_each_release_is_credited_in_its_own_words(self):
        got = _run(self, r"""
          route('items/i90?', {accessInformation: " Esri, Maxar, Earthstar Geographics, and the GIS User Community "});
          route('items/i80?', 500);
          route('items/i70?', {accessInformation: ""});
          var words = [await wbCredit("i90"), await wbCredit("i80"), await wbCredit("i70")];
          var asked = ASKED.length;
          await wbCredit("i90"); await wbCredit("i80");
          console.log(JSON.stringify({words: words, asked: [asked, ASKED.length], url: ASKED[0]}));
        """)
        default = thennow.WAYBACK["credit"]
        self.assertEqual(got, {"words": ["Esri, Maxar, Earthstar Geographics, and the GIS User Community",
                                         default, default],
                               "asked": [3, 4],
                               "url": "https://www.arcgis.com/sharing/rest/content/items/i90?f=json"})
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenArchiveRuns -v`
Expected: 9 tests: 8 FAIL and 1 ERROR, each for a function not yet defined (`ReferenceError: wbReleases is not defined` and the like). `FAILED (failures=8, errors=1)`.

- [ ] **Step 3: Add the script**

Append to `_JS` in `elnino/thennow.py`, just before its closing `"""`:

```js
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
  // capture first. A version whose capture is not given goes by its release.
  function wbVersions(lon, lat) {
    return wbReleases().then(function (all) {
      return wbWalk(all, wbTile(lon, lat)).then(function (walk) {
        return Promise.all(walk.list.map(function (r) { return wbCapture(r, lon, lat); })).then(function (caps) {
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
        });
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
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 44 tests, OK.

- [ ] **Step 5: Mutation check**

Change `var WAIT = 20000,` to `var WAIT = 60000,`; run `python -m unittest tests.test_thennow.TestThenArchiveRuns`; expected FAIL in `test_a_metadata_query_that_hangs_is_given_up_after_20_s`. Put it back; run again; expected OK.

- [ ] **Step 6: Commit**

```bash
git add elnino/thennow.py tests/test_thennow.py
git commit -m "Then and now: Esri's archive walked as Wayback walks it" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


---

### Task 5: Each side a layer of the page's own kinds, and today's layers standing aside

**Files:**
- Modify: `elnino/thennow.py` (`_JS`, appended)
- Modify: `elnino/stormdesk.py` (`_JS`: `xyzCells`, `labelled`, `tilesDown`, `tileFailed`, `TileSet.draw`, `cells`, `overSpecs`, `tiles`, `buildGeo`, `baseDown`, `drawMarks`)
- Modify: `elnino/worldmap.py` (`_JS`: `drawComposite`, `ensoLegend`, `ensoTileLegend`, `ensoTileSpecs`)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: `thenSrc(id)` (Task 2); `wbNearest`, `wbTile`, `fetchWait`, `WB` (Task 4); `D.then.names_credit`, `D.then.wayback`; the page's `LAYERS`, `S`, `NODATA`, `MAPS`, `tally`, `againIn`.
- Produces: `thenFresh({lon, lat, label, source, back}) -> T` with `preset "now"`, `want/got/note/look {a, b}`, `ask {a, b}`, `read`, `readKey`, `apart`, `versions`, `stopped`, `names` (true), `fail {gibs, wayback}`, `link`, `back`; `thenVersion(T, id) -> version | null`; `thenLayer(T, k) -> layer | null`; `thenApply()` (registers `LAYERS["then-a"]`, `LAYERS["then-b"]` and sets `S.layer = "then-a"`, `S.second = "then-b"`, `S.compare = true`); `wbAsk(img)`; a then layer has `then: true`, `time` (a GIBS side) or `tiles` + `wayback` (an archive side), `over` (Esri's names, or null), `overCredit`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
# Two versions of Manaus in Esri's archive, for the sides to show.
VERSIONS = ('[{id: 90, day: "2024-03-01", item: "i90", tiles: "https://wb/tile/90/{z}/{y}/{x}", '
            'capture: {day: "2021-10-31", provider: "Maxar", sensor: "WV02", res: 0.5}, when: "2021-10-31", '
            'credit: "Esri, Maxar, Earthstar Geographics, and the GIS User Community"}, '
            '{id: 80, day: "2019-06-26", item: "i80", tiles: "https://wb/tile/80/{z}/{y}/{x}", capture: null, '
            'when: "2019-06-26", credit: ""}]')


def _entered(source: str, a, b, z: float = 12) -> str:
    """The script's state with Manaus entered from a source, its two sides at
    a and b, and the view on the pin at zoom z."""
    return (f"S.then = thenFresh({{lon: -60.025, lat: -3.1, label: 'Manaus', source: '{source}', back: {{}}}});\n"
            f"S.then.versions = {VERSIONS};\n"
            f"S.then.got = {{a: {json.dumps(a)}, b: {json.dumps(b)}}};\n"
            f"S.x = mx(-60.025); S.y = my(-3.1); S.z = {z};\n"
            "thenApply();\n")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenLayerRuns(unittest.TestCase):
    """Each side a layer of the page's own kinds, drawn by the page's own tile
    code at its own date, never at today's."""

    def test_the_two_sides_are_compared_at_the_divider(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15") + r"""
          var a = LAYERS["then-a"];
          console.log(JSON.stringify([S.layer, S.second, S.compare, a.kind, a.global, a.time, a.zoom, a.then,
                                      LAYERS["then-b"].time]));
        """)
        self.assertEqual(got, ["then-a", "then-b", True, "imagery", "MODIS_Terra_CorrectedReflectance_TrueColor",
                               "2014-11-15", 9, True, "2015-11-15"])

    def test_each_nasa_side_is_drawn_at_its_own_day(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=3) + r"""
          S.x = 0.5; S.y = 0.5;
          function keys(c) { return c.cells.map(function (x) { return x.key; }).filter(function (k, i, all) { return all.indexOf(k) === i; }); }
          var a = cells("then-a", 0), b = cells("then-b", 0);
          console.log(JSON.stringify([keys(a), keys(b), a.cells.length, a.cells[0].url, Object.keys(a.used)]));
        """)
        self.assertEqual(got, [["2014-11-15"], ["2015-11-15"], 16,
                               "https://gibs/MODIS_Terra_CorrectedReflectance_TrueColor/2014-11-15/"
                               "GoogleMapsCompatible_Level9/3/2/2.jpeg",
                               ["MODIS_Terra_CorrectedReflectance_TrueColor"]])

    def test_a_side_with_no_day_draws_nothing_not_the_latest(self):
        got = _run(self, _entered("modis", None, "2015-11-15", z=3) + r"""
          // GIBS lists a latest day: the page's other layers draw it.
          frameOf = function () { return {t: 0, key: "2026-09-28"}; };
          var a = cells("then-a", 0), b = cells("then-b", 0);
          console.log(JSON.stringify([a.cells.length, Object.keys(a.used), b.cells[0].key]));
        """)
        self.assertEqual(got, [0, [], "2015-11-15"])

    def test_landsat_and_sentinel_2_sides_draw_both_imagers_at_their_own_days(self):
        got = _run(self, _entered("hls", "2014-11-13", "2015-11-20") + r"""
          function what(c) {
            var names = {}, keys = {};
            c.cells.forEach(function (x) { names[x.name] = true; keys[x.key] = true; });
            return [Object.keys(names).sort(), Object.keys(keys)];
          }
          console.log(JSON.stringify([what(cells("then-a", 0)), what(cells("then-b", 0)), S.day]));
        """)
        self.assertEqual(got, [[["HLS_L30", "HLS_S30"], ["2014-11-13"]], [["HLS_L30", "HLS_S30"], ["2015-11-20"]],
                               None])

    def test_archive_sides_draw_their_own_release_s_tiles(self):
        got = _run(self, _entered("archive", 80, 90, z=16) + r"""
          var a = cells("then-a", 0), l = LAYERS["then-a"];
          var at = a.cells.filter(function (c) { return c.c === 21840 && c.r === 33332; })[0];
          console.log(JSON.stringify({url: at.url, name: at.name, map: at.map, wb: at.wb, credit: at.credit,
                                      all: a.cells.every(function (c) { return c.url.indexOf("https://wb/tile/80/16/") === 0; }),
                                      zoom: l.zoom, right: LAYERS["then-b"].credit, used: Object.keys(a.used)}));
        """)
        esri = "Powered by Esri. Source: "
        self.assertEqual(got, {"url": "https://wb/tile/80/16/33332/21840", "name": "wb80", "map": "then-a",
                               "wb": 80, "credit": esri + thennow.WAYBACK["credit"], "all": True, "zoom": 19,
                               "right": esri + "Esri, Maxar, Earthstar Geographics, and the GIS User Community",
                               "used": ["then-a"]})

    def test_an_archive_side_with_no_version_draws_nothing(self):
        got = _run(self, _entered("archive", None, 90, z=16) + r"""
          console.log(JSON.stringify([cells("then-a", 0).cells.length, cells("then-b", 0).cells.length > 0]));
        """)
        self.assertEqual(got, [0, True])

    def test_roads_and_names_go_over_either_side_credited_in_esri_s_words(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15") + r"""
          var on = overSpecs("then-a"), named = [labelled("then-a"), labelled("then-b")];
          S.then.source = "archive"; S.then.got = {a: 80, b: 90}; thenApply();
          var archive = overSpecs("then-b")[0].cells[0].credit;
          S.then.names = false; thenApply();
          console.log(JSON.stringify({keys: on.map(function (s) { return s.key; }), z: on[0].cells[0].z,
                                      url: on[1].cells[0].url.split("/")[2], map: on[0].cells[0].map,
                                      credit: on[0].cells[0].credit, archive: archive, named: named,
                                      off: [overSpecs("then-a").length, labelled("then-a")]}));
        """)
        self.assertEqual(got, {"keys": ["o0", "o1"], "z": 12, "url": "places", "map": "then-a-names",
                               "credit": "Powered by Esri. " + thennow.NAMES_CREDIT,
                               "archive": thennow.NAMES_CREDIT, "named": [True, True], "off": [0, False]})

    def test_a_side_s_failed_tiles_bring_the_coastline_and_its_words(self):
        got = _run(self, _entered("hls", "2014-11-13", "2015-11-20") + r"""
          S.inView = cells("then-a", 0).used;
          var before = [baseDown(), nasaDown(S.inView)];
          GOT["HLS_L30/2014-11-13"] = {ok: 0, failed: 3}; GOT["HLS_S30/2014-11-13"] = {ok: 0, failed: 2};
          var after = [baseDown(), nasaDown(S.inView)];
          S.then.source = "archive"; S.then.got = {a: 80, b: 90}; thenApply();
          var map = [baseDown()];
          MAPS["then-a"] = {ok: 0, failed: 4};
          map.push(baseDown());
          console.log(JSON.stringify([before, after, map]));
        """)
        self.assertEqual(got, [[False, False], [True, True], [False, True]])

    def test_an_archive_tile_past_zoom_13_that_esri_has_not_is_drawn_coarser(self):
        js = stormdesk.script()
        extra = "\n".join(_js_function(js, n) for n in ("tally", "againIn", "tileFailed"))
        got = _run(self, r"""
          route("tilemap/80/17/", {data: [0]});
          route("tilemap/80/18/", {data: [1]});
          function tile(z, c, r, url) { return {_wb: 80, _z: z, _c: c, _r: r, _name: "wb80", _map: "then-a", _url: url, style: {}}; }
          tileFailed.call(tile(17, -3, 70000, "u17"));
          tileFailed.call(tile(18, 5, 7, "u18"));
          tileFailed.call(tile(13, 5, 7, "u13"));
          await flush();
          console.log(JSON.stringify({nodata: Object.keys(NODATA), failed: MAPS["then-a"].failed,
                                      asked: ASKED.map(function (u) { return u.split("/MapServer/")[1]; })}));
        """, extra=extra)
        # Esri has no tile at zoom 17 there: the zoom-16 tile is drawn. At 18
        # it has one, and at 13 it is not asked: each fails as any map tile does.
        self.assertEqual(got, {"nodata": ["wb80/17/131069/70000"], "failed": 2,
                               "asked": ["tilemap/80/17/70000/131069", "tilemap/80/18/7/5"]})


class TestThenHooks(unittest.TestCase):
    """Entered, nothing of today's is drawn over another day's ground: the
    storms, the outlook, the invests, the regions, NASA's reference overlays,
    the ocean and flood tiles, and the El Nino composite and its keys."""

    def test_the_composite_its_keys_and_nasa_s_tiles_stand_aside(self):
        js = worldmap._JS
        self.assertIn("var name = S.then ? null : S.enso.variable;", _js_function(js, "drawComposite"))
        self.assertIn('name = S.then ? null : S.enso.variable;', _js_function(js, "ensoLegend"))
        self.assertIn("on = !!S.enso.tiles[l.id] && !S.then;", _js_function(js, "ensoTileLegend"))
        self.assertIn("if (S.z > D.enso.hide_above || S.then) return specs;", _js_function(js, "ensoTileSpecs"))
        self.assertIn('S.refs[l.id] && S.imagery === "ok" && !S.then', _js_function(stormdesk._JS, "tiles"))

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_entered_the_marks_are_the_pin_and_the_towns(self):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "origin", "near", "copies", "clamp", "mx", "my", "rad", "esc", "pct",
            "labelled", "labelledBase", "namedAt", "townsWhy", "drawMarks", "ensoLabels"))
        got = _node_json(self, r"""
var TILE = 256, HOUR = 3600000, NM = 1.852, CIRCUMFERENCE = 40075.017;
var LAYERS = {"then-a": {kind: "imagery", then: true, over: null}, "then-b": {kind: "imagery", then: true, over: null}};
var PLACES = [["Itacoatiara", "Brazil", "", 100000, -58.44, -3.14, false]], BYPOP = null;
var D = {outlook: [{key: "a1", lon: -61, lat: -2, level: "high", label: "Area", centre: "NHC",
                    chance_2day: 40, chance_7day: 60}],
         invests: [{name: "Invest 90L", lon: -59, lat: -4, wind: 25, track: []}], style: {outlook: {}},
         enso: {boxes: [{lon0: -61, lon1: -59, lat0: -4, lat1: -2, label: "Box", anomaly: null}]}};
var drawn = 0;
var st = {id: "al01", x0: mx(-60), hue: "red", d: {id: "al01", title: "Storm", lon: -60, lat: -3,
          forecast: [{lon: -60.5, lat: -3.5, hour: 24}], exposure: [{place: "Town", lon: -60.2, lat: -3.2}],
          watches: [], surge: [], view: {}}};
var STORMS = [st], BYID = {al01: st}, marksG = {innerHTML: ""};
function base() { drawn++; return {t: 0, image: false}; }
function centreAt() { return {lon: -60, lat: -3, category: 1, wind: 60, radii: {}}; }
function inside() { return 0; }
function when() { return 0; }
""" + functions + r"""
var S = {x: mx(-60), y: my(-3), z: 7, w: 800, h: 600, scrub: 0, selected: "al01",
         show: {towns: true, outlook: true, places: true, watches: true, surge: true},
         pin: {lon: -60.025, lat: -3.1, label: "Manaus"}, enso: {boxes: true, regions: false},
         layer: "then-a", second: "then-b", compare: true, split: 0.5};
function marks(then) {
  S.then = then; drawn = 0; drawMarks();
  var h = marksG.innerHTML;
  return {pin: h.indexOf('class="pin"') >= 0, town: h.indexOf(">Itacoatiara<") >= 0, storm: h.indexOf("data-storm") >= 0,
          dots: h.indexOf('class="dot"') >= 0, area: h.indexOf("data-area") >= 0, invest: h.indexOf("Invest 90L") >= 0,
          box: h.indexOf(">Box<") >= 0, places: h.indexOf(">Town<") >= 0, base: drawn};
}
console.log(JSON.stringify([marks({}), marks(null)]));
""")
        self.assertEqual(got[0], {"pin": True, "town": True, "storm": False, "dots": False, "area": False,
                                  "invest": False, "box": False, "places": False, "base": 0})
        self.assertEqual(got[1], {"pin": True, "town": True, "storm": True, "dots": True, "area": True,
                                  "invest": True, "box": True, "places": True, "base": 1})

    @unittest.skipUnless(shutil.which("node"), "node is not installed")
    def test_entered_no_geometry_of_today_s_is_drawn(self):
        js = stormdesk.script()
        functions = "\n".join(_js_function(js, n) for n in (
            "world", "clamp", "rad", "mx", "my", "near", "X", "Y", "line", "pt", "geoReach", "repeated", "buildGeo"))
        got = _node_json(self, r"""
var TILE = 256, UNIT = 1048576, NM = 1.852, THRESHOLDS = ["34", "50", "64"], ORDER = [];
var geoDirty = true, geoRef = null, geoCopies = 0, geoLo = 0, geoHi = 0, geoExt = null, geoG = {innerHTML: ""};
var D = {outlook: [{lon: -61, lat: -2, level: "high", area: [[-62, -1], [-60, -1], [-60, -3]], arrow: []}],
         invests: [], style: {outlook: {}, products: {}}};
var STORMS = [{x0: mx(-60), hue: "red", d: {track: [{lon: -58, lat: -2}, {lon: -60, lat: -3}],
               forecast: [{lon: -61, lat: -4}], cone: null, surge: null, watches: null}}];
var geo = 0;
function ensoGeo() { geo++; return '<path class="region"/>'; }
""" + functions + r"""
var S = {x: mx(-60), y: my(-3), z: 5, w: 800, h: 600, show: {outlook: true, radii: false}};
function draw(then) { S.then = then; buildGeo(); var h = geoG.innerHTML;
  return [h.indexOf('class="track"') >= 0, h.indexOf('class="area"') >= 0, h.indexOf('class="region"') >= 0, geoCopies]; }
console.log(JSON.stringify([draw({}), draw(null)]));
""")
        self.assertEqual(got, [[False, False, False, 0], [True, True, True, 0]])
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenLayerRuns tests.test_thennow.TestThenHooks -v`
Expected: 12 tests FAIL: the layer tests on `ReferenceError: thenFresh is not defined`; the hook tests on the engine's text and marks as they are today. `FAILED (failures=12)`.

- [ ] **Step 3: Add the script**

Append to `_JS` in `elnino/thennow.py`, just before its closing `"""`:

```js
  // ---- the two sides, as layers of the page's own kinds -----------------------
  // A place entered: where, what shows it, the dates asked for (want) and
  // found (got) on each side, and what the map showed before (back).
  function thenFresh(o) {
    return {lon: o.lon, lat: o.lat, label: o.label, source: o.source, preset: "now",
            want: {a: null, b: null}, got: {a: null, b: null}, note: {a: "", b: ""},
            look: {a: "", b: ""}, ask: {a: 0, b: 0}, read: null, readKey: "", apart: "",
            versions: null, stopped: "", names: true, fail: {gibs: false, wayback: false},
            link: "", back: o.back};
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
      var v = thenVersion(T, got);
      l = {kind: "map", name: src.name, source: src.name, zoom: src.zoom, grey: false,
           wayback: v ? v.id : 0, tiles: v ? v.tiles : null, nodata: v ? "wb" + v.id : "wb",
           credit: "Powered by Esri. Source: " + ((v && v.credit) || D.then.wayback.credit)};
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
```

- [ ] **Step 4: Hook the page**

Each edit's first text is found exactly once in its file; replace it with the second.

1. `elnino/stormdesk.py`, `xyzCells`: replace

```js
                url: xyzUrl(template, t.z, ((t.c % m) + m) % m, t.r), check: false, grey: !!l.grey,
                credit: l.credit, nasa: false});
```

   with

```js
                url: xyzUrl(template, t.z, ((t.c % m) + m) % m, t.r), check: false, grey: !!l.grey,
                credit: l.credit, nasa: false, wb: l.wayback || 0});
```

2. `elnino/stormdesk.py`, `labelled`: replace

```js
  function labelled(id) { var l = LAYERS[id]; return !!(l && l.kind === "map"); }
```

   with

```js
  // A then-and-now side (thennow.py) names its places while Esri's names are over it.
  function labelled(id) { var l = LAYERS[id]; return !!(l && (l.then ? !!l.over : l.kind === "map")); }
```

3. `elnino/stormdesk.py`, `tilesDown`: replace

```js
  function tilesDown(s) {
    var l = s.layer || {}, f = s.step && !l.stack && !l.time ? frameOf(s, S.frame) : null;
    var g = GOT[gotKey(s.name, l.stack ? S.day : l.time || (f && f.key))];
```

   with

```js
  function tilesDown(s) {
    var l = s.layer || {}, f = s.step && !l.stack && !l.time && !l.then ? frameOf(s, S.frame) : null;
    var g = GOT[gotKey(s.name, l.then ? l.time : l.stack ? S.day : l.time || (f && f.key))];
```

4. `elnino/stormdesk.py`, `tileFailed`: replace

```js
  function tileFailed() {
    this.style.visibility = "hidden";
    this._failed = true;
    if (this._map) {
```

   with

```js
  function tileFailed() {
    this.style.visibility = "hidden";
    this._failed = true;
    // A tile of Esri's archive past zoom 13 is asked after in its release's
    // tilemap first (thennow.py): if Esri has none there, the coarser is drawn.
    if (this._wb && this._z > 13 && !this._asked) { wbAsk(this); return; }
    if (this._map) {
```

5. `elnino/stormdesk.py`, `TileSet.draw`: replace

```js
        img._credit = cell.credit; img._nasa = !!cell.nasa; img._cut = cell.cut || [0, 0];
```

   with

```js
        img._credit = cell.credit; img._nasa = !!cell.nasa; img._cut = cell.cut || [0, 0]; img._wb = cell.wb || 0;
```

6. `elnino/stormdesk.py`, `cells`: replace

```js
      var list = xyzCells(l, l.tiles, l.id), wanted = clamp(Math.round(S.z), 0, l.zoom), coarser = null;
```

   with

```js
      var list = l.tiles ? xyzCells(l, l.tiles, l.nodata || l.id) : [], wanted = clamp(Math.round(S.z), 0, l.zoom), coarser = null;
```

7. `elnino/stormdesk.py`, `cells`: replace

```js
          if (l.stack) {
            // Every part at the day found for the centre of the view.
            ask(s);
            used[s.name] = s;
            if (!S.day || S.imagery !== "ok") continue;
            key = S.day;
          } else if (l.time) {
            if (S.imagery !== "ok") continue;
```

   with

```js
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
```

8. `elnino/stormdesk.py`, `overSpecs`: replace

```js
  function overSpecs(id) {
    var l = LAYERS[id];
    return
```

   with

```js
  function overSpecs(id) {
    var l = LAYERS[id];
    // Over a then-and-now side, Esri's roads and names as over World
    // Imagery: to their own zoom, credited in their own words.
    if (l && l.then) l = l.over ? {id: l.id + "-names", over: l.over, zoom: 19, grey: true, credit: l.overCredit} : null;
    return
```

9. `elnino/stormdesk.py`, `tiles`: replace

```js
      if (l.kind === "overlay" && S.refs[l.id] && S.imagery === "ok") refs.push(
```

   with

```js
      if (l.kind === "overlay" && S.refs[l.id] && S.imagery === "ok" && !S.then) refs.push(
```

10. `elnino/stormdesk.py`, `buildGeo`: replace

```js
    var h = [ensoGeo()], style = D.style;
```

   with

```js
    var h = [ensoGeo()], style = D.style;
    // Entered (thennow.py), no geometry of today's is drawn over another day's ground.
    if (S.then) { geoExt = null; geoCopies = geoReach(); geoG.innerHTML = ""; return; }
```

11. `elnino/stormdesk.py`, `baseDown`: replace

```js
    return labelledBase() ? mapDown(S.layer) : S.imagery === "unreachable" || nasaDown(S.inView);
```

   with

```js
    var l = LAYERS[S.layer];
    return l && l.kind === "map" ? mapDown(S.layer) : S.imagery === "unreachable" || nasaDown(S.inView);
```

12. `elnino/stormdesk.py`, `drawMarks`: replace

```js
    var drawn = [];
    STORMS.forEach(function (st) {
```

   with

```js
    // Entered (thennow.py), the ground is another day's: today's storms,
    // outlook areas, invests and regions are not drawn on it.
    var drawn = [], live = !S.then;
    if (live) STORMS.forEach(function (st) {
```

13. `elnino/stormdesk.py`, `drawMarks`: replace

```js
    if (S.z >= 6) STORMS.forEach(function (st) {
```

   with

```js
    if (live && S.z >= 6) STORMS.forEach(function (st) {
```

14. `elnino/stormdesk.py`, `drawMarks`: replace

```js
    STORMS.forEach(function (st) {
      var s = st.d, selected = st.id === S.selected;
```

   with

```js
    if (live) STORMS.forEach(function (st) {
      var s = st.d, selected = st.id === S.selected;
```

15. `elnino/stormdesk.py`, `drawMarks`: replace

```js
    if (sel && S.show.places) {
```

   with

```js
    if (live && sel && S.show.places) {
```

16. `elnino/stormdesk.py`, `drawMarks`: replace

```js
    if (S.show.outlook) D.outlook.forEach(function (a) {
      var colour = D.style.outlook[a.level] || "var(--ink2)";
```

   with

```js
    if (live && S.show.outlook) D.outlook.forEach(function (a) {
      var colour = D.style.outlook[a.level] || "var(--ink2)";
```

17. `elnino/stormdesk.py`, `drawMarks`: replace

```js
    (D.invests || []).forEach(function (v) {
      copies(mx(v.lon), 200).forEach(function (k) {
```

   with

```js
    if (live) (D.invests || []).forEach(function (v) {
      copies(mx(v.lon), 200).forEach(function (k) {
```

18. `elnino/stormdesk.py`, `drawMarks`: replace

```js
    ensoLabels(sx, sy, off, label).forEach(function (words) { out.push(words); });
```

   with

```js
    if (live) ensoLabels(sx, sy, off, label).forEach(function (words) { out.push(words); });
```

19. `elnino/worldmap.py`, `drawComposite`: replace

```js
    var name = S.enso.variable;
    if (ensoCanvas.hidden !== !name) ensoCanvas.hidden = !name;
```

   with

```js
    // Entered (thennow.py), the composite of today's season stands aside.
    var name = S.then ? null : S.enso.variable;
    if (ensoCanvas.hidden !== !name) ensoCanvas.hidden = !name;
```

20. `elnino/worldmap.py`, `ensoLegend`: replace

```js
    var key = $("enso-key"), name = S.enso.variable;
```

   with

```js
    var key = $("enso-key"), name = S.then ? null : S.enso.variable;
```

21. `elnino/worldmap.py`, `ensoTileLegend`: replace

```js
      var key = $("enso-" + l.id + "-key"), on = !!S.enso.tiles[l.id];
```

   with

```js
      var key = $("enso-" + l.id + "-key"), on = !!S.enso.tiles[l.id] && !S.then;
```

22. `elnino/worldmap.py`, `ensoTileSpecs`: replace

```js
    if (S.z > D.enso.hide_above) return specs;
```

   with

```js
    if (S.z > D.enso.hide_above || S.then) return specs;
```


- [ ] **Step 5: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 56 tests, OK.

- [ ] **Step 6: Run the page's own tests the hooks touch**

Run: `python -m unittest tests.test_tracker.TestStormDeskPayload tests.test_tracker.TestStormDeskPage tests.test_tracker.TestDaySearchRuns tests.test_tracker.TestStreetMaps tests.test_tracker.TestStreetMapRuns tests.test_tracker.TestCompositeOnTheMapRuns tests.test_tracker.TestEnsoHere tests.test_tracker.TestEnsoHereRuns tests.test_tracker.TestEnsoTiles tests.test_tracker.TestEnsoTilesRuns tests.test_tracker.TestEnsoNow tests.test_tracker.TestEnsoShapesRuns tests.test_tracker.TestGoogleHere tests.test_tracker.TestTwoPages tests.test_tracker.TestHashRuns tests.test_tracker.TestAddressSearchRuns tests.test_tracker.TestAddressSearch tests.test_tracker.TestMapDocumented tests.test_tracker.TestNoWayBackRuns tests.test_tracker.TestLayerChoiceRuns tests.test_tracker.TestWorldCopiesRuns tests.test_tracker.TestEsriCoverageRuns tests.test_tracker.TestGlobePanel tests.test_tracker.TestImageryGeometry tests.test_tracker.TestRegressions`
Expected: 163 tests, OK (the page's behaviour unchanged when nothing is entered).

- [ ] **Step 7: Mutation check**

In `tiles()`, drop ` && !S.then` from `S.refs[l.id] && S.imagery === "ok" && !S.then`; run `python -m unittest tests.test_thennow.TestThenHooks`; expected FAIL in `test_the_composite_its_keys_and_nasa_s_tiles_stand_aside`. Put it back; run again; expected OK.

- [ ] **Step 8: Commit**

```bash
git add elnino/thennow.py elnino/stormdesk.py elnino/worldmap.py tests/test_thennow.py
git commit -m "Then and now: each side a layer at its own date; today's layers stand aside" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


---

### Task 6: Each side's date found in its archive

**Files:**
- Modify: `elnino/thennow.py` (`_JS`, appended)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: `parseSpans`, `snapTime`, `stepTime`, `dayNo` (Task 3); `wbVersions`, `wbNearest`, `wbCredit`, `fetchWait` (Task 4); `thenVersion`, `thenApply` (Task 5); the page's `imageOn(day, t)`, `looks`, `dayText`, `shiftDay`, `NO_ANSWER`, `S.imagery`.
- Produces: `SPANS`, `SPANS_GOT` (spans by source id); `thenSpans(src) -> Promise<spans>`; `clampNote(first, last, key) -> str`; `thenApart(T, older, what)`; `thenOrder(T)` (the earlier on the left); `sideDay(T, k) -> key | null` (an archive side's capture day); `thenGibs(T, src)`; `thenArchive(T)`; `thenCredits(T)`; `hlsTile(lon, lat)`; `hlsDays(from, by, first, last)`; `hlsHunt(days, t, still)`; `thenHls(T, k, by)`; `thenResolve()`; `thenChanged()` (Task 7 adds `thenRead()` to it). `T.look[k]` is `""`, `"asking"`, `"looking"`, `NO_ANSWER` or `"none"`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
def _want(source: str, a: str, b: str, preset: str = "") -> str:
    """Manaus entered from a source, asking for dates a and b; preset names
    the event they came from, "" for the reader's own."""
    return (f"S.then = thenFresh({{lon: -60.025, lat: -3.1, label: 'Manaus', source: '{source}', back: {{}}}});\n"
            f"S.then.want = {{a: '{a}', b: '{b}'}}; S.then.preset = '{preset}';\n"
            "S.x = mx(-60.025); S.y = my(-3.1); S.z = 8;\n")


# What the tests read of the entered place after it is resolved.
SHOWN = ("function shown() { var T = S.then; return JSON.parse(JSON.stringify({got: T.got, want: T.want, "
         "look: T.look, note: T.note, apart: T.apart, fail: T.fail})); }\n")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenResolveRuns(unittest.TestCase):
    """Each side's date found in its archive: the time GIBS lists nearest it,
    the version of the place Esri captured nearest it, or the nearest day
    with an image at the pin; the earlier on the left."""

    def test_nasa_sides_take_the_day_gibs_lists_nearest_their_dates(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + SHOWN + r"""
          route("gibs/MODIS_Terra_CorrectedReflectance_TrueColor/", "<Domain>2000-02-24/2026-09-28/P1D</Domain>");
          thenResolve();
          var asking = [S.then.look.a, S.then.look.b];
          await flush();
          var first = shown();
          thenResolve(); await flush();
          console.log(JSON.stringify({asking: asking, first: first, asked: ASKED, layer: LAYERS["then-b"].time,
                                      imagery: S.imagery}));
        """)
        self.assertEqual(got["asking"], ["asking", "asking"])
        self.assertEqual(got["first"], {"got": {"a": "2014-11-15", "b": "2015-11-15"},
                                        "want": {"a": "2014-11-15", "b": "2015-11-15"},
                                        "look": {"a": "", "b": ""}, "note": {"a": "", "b": ""}, "apart": "",
                                        "fail": {"gibs": False, "wayback": False}})
        # Asked once a visit, from the archive's first day to tomorrow.
        self.assertEqual(got["asked"], ["https://gibs/MODIS_Terra_CorrectedReflectance_TrueColor/"
                                        "GoogleMapsCompatible_Level9/2000-02-24--2026-09-30.xml"])
        self.assertEqual((got["layer"], got["imagery"]), ("2015-11-15", "ok"))

    def test_vegetation_sides_take_the_16_day_composite_nearest(self):
        got = _run(self, _want("ndvi", "2014-11-15", "2015-11-15") + SHOWN + r"""
          route("gibs/MODIS_Terra_L3_NDVI_16Day/",
                "<Domain>2014-01-01/2014-12-19/P16D,2015-01-01/2015-12-19/P16D</Domain>");
          thenResolve(); await flush();
          console.log(JSON.stringify(shown().got));
        """)
        self.assertEqual(got, {"a": "2014-11-17", "b": "2015-11-17"})

    def test_a_date_outside_the_archive_takes_its_nearest_end_and_says_so(self):
        got = _run(self, _want("sst", "2001-03-15", "2026-09-29") + SHOWN + r"""
          route("gibs/GHRSST", "<Domain>2002-09-01/2026-09-27/P1D</Domain>");
          thenResolve(); await flush();
          var latest = shown();
          route("gibs/GHRSST", "<Domain>2002-09-01/2026-06-30/P1D</Domain>");
          SPANS = {};
          thenResolve(); await flush();
          console.log(JSON.stringify([latest.got, latest.note, shown().got.b, shown().note.b]));
        """)
        self.assertEqual(got, [{"a": "2002-09-01", "b": "2026-09-27"},
                               {"a": "asked for 15 Mar 2001, before the first it holds, 1 Sep 2002", "b": ""},
                               "2026-06-30", "asked for 29 Sep 2026, after the latest it holds, 30 Jun 2026"])

    def test_an_event_s_dates_on_one_image_move_the_left_to_the_one_before(self):
        domain = 'route("gibs/MODIS_Terra_Corr", "<Domain>2010-01-01,2012-01-01</Domain>");\n'
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15", preset="ep0-before") + SHOWN + domain + r"""
          thenResolve(); await flush();
          var event = shown();
          S.then.preset = ""; thenResolve(); await flush();
          console.log(JSON.stringify([event.got, event.apart, shown().got, shown().apart]));
        """)
        self.assertEqual(got, [{"a": "2010-01-01", "b": "2012-01-01"},
                               "Both dates fell on the same image, so the left side shows the one before it.",
                               {"a": "2012-01-01", "b": "2012-01-01"}, ""])

    def test_the_earlier_date_goes_on_the_left(self):
        got = _run(self, _want("modis", "2015-11-15", "2014-11-15") + SHOWN + r"""
          route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-28/P1D</Domain>");
          thenResolve(); await flush();
          console.log(JSON.stringify([shown().got, shown().want]));
        """)
        self.assertEqual(got, [{"a": "2014-11-15", "b": "2015-11-15"}, {"a": "2014-11-15", "b": "2015-11-15"}])

    def test_gibs_not_answering_is_said_on_each_side_and_asked_again(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + SHOWN + r"""
          route("gibs/MODIS_Terra_Corr", 500);
          thenResolve(); await flush();
          var failed = shown();
          route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-28/P1D</Domain>");
          thenResolve(); await flush();
          console.log(JSON.stringify([failed.look, failed.fail.gibs, failed.got, shown().got, shown().fail.gibs,
                                      ASKED.length]));
        """)
        self.assertEqual(got, [{"a": "no answer", "b": "no answer"}, True, {"a": None, "b": None},
                               {"a": "2014-11-15", "b": "2015-11-15"}, False, 2])

    def test_archive_sides_take_the_versions_captured_nearest_their_dates(self):
        got = _run(self, WB_ROUTES + _want("archive", "2019-01-01", "2022-01-01") + SHOWN + r"""
          route("items/i90?", {accessInformation: "Esri, Maxar, Earthstar Geographics, and the GIS User Community"});
          thenResolve();
          var asking = [S.then.look.a, S.then.look.b];
          await flush();
          console.log(JSON.stringify({asking: asking, shown: shown(), versions: S.then.versions.length,
                                      right: LAYERS["then-b"].credit, left: LAYERS["then-a"].tiles}));
        """)
        self.assertEqual(got["asking"], ["asking", "asking"])
        self.assertEqual(got["shown"]["got"], {"a": 80, "b": 90})
        self.assertEqual(got["shown"]["note"], {"a": "asked for 1 Jan 2019, before the first it holds, 26 Jun 2019",
                                                "b": "asked for 1 Jan 2022, after the latest it holds, 31 Oct 2021"})
        self.assertEqual((got["versions"], got["left"]), (2, "https://wb/tile/80/{z}/{y}/{x}"))
        self.assertEqual(got["right"], "Powered by Esri. Source: Esri, Maxar, Earthstar Geographics, and the GIS "
                                       "User Community")

    def test_an_event_s_dates_on_one_capture_move_the_left_to_the_older(self):
        got = _run(self, WB_ROUTES + _want("archive", "2025-09-29", "2026-09-29", preset="now") + SHOWN + r"""
          thenResolve(); await flush();
          console.log(JSON.stringify([shown().got, shown().apart]));
        """)
        self.assertEqual(got, [{"a": 80, "b": 90},
                               "Both dates fell on the same capture, so the left side shows the one before it."])

    def test_esri_s_archive_not_answering_or_holding_nothing_is_said(self):
        got = _run(self, _want("archive", "2019-01-01", "2022-01-01") + SHOWN + r"""
          route("waybackconfig.json", 500);
          thenResolve(); await flush();
          var down = shown();
          """ + WB_ROUTES + r"""
          route("tilemap/100/", {data: [0]});
          thenResolve(); await flush();
          console.log(JSON.stringify([down.look, down.fail.wayback, shown().look, shown().got, shown().fail.wayback]));
        """)
        self.assertEqual(got, [{"a": "no answer", "b": "no answer"}, True, {"a": "none", "b": "none"},
                               {"a": None, "b": None}, False])

    def test_landsat_and_sentinel_2_sides_take_the_nearest_day_with_an_image(self):
        got = _run(self, _want("hls", "2014-11-15", "2015-11-15") + SHOWN + r"""
          paint("HLS_", [0, 0, 0, 0]);
          paint("HLS_S30/2014-11-13/", [10, 20, 30, 255]);
          paint("HLS_S30/2014-11-17/", [10, 20, 30, 255]);
          paint("HLS_L30/2015-11-20/", [10, 20, 30, 255]);
          S.imagery = "pending";
          thenResolve();
          var looking = [S.then.look.a, S.then.look.b];
          await flush(400);
          console.log(JSON.stringify({looking: looking, got: shown().got, look: shown().look, imagery: S.imagery,
                                      first: IMAGES[0]}));
        """)
        # 13 Nov is two days back and 17 Nov two on: the list is looked at
        # day, a day back, a day on, and so on, so the earlier comes first.
        self.assertEqual(got, {"looking": ["looking", "looking"], "got": {"a": "2014-11-13", "b": "2015-11-20"},
                               "look": {"a": "", "b": ""}, "imagery": "ok",
                               "first": "https://gibs/HLS_L30/2014-11-15/GoogleMapsCompatible_Level12/12/2083/1365.png"})

    def test_no_image_within_20_days_or_no_answer_is_said(self):
        got = _run(self, _want("hls", "2014-11-15", "2015-11-15") + SHOWN + r"""
          paint("HLS_", [0, 0, 0, 0]);
          thenResolve(); await flush(400);
          var none = shown();
          PAINT = []; looks = {};
          thenResolve(); await flush(400);
          console.log(JSON.stringify([none.look, none.got, shown().look, shown().fail.gibs]));
        """)
        self.assertEqual(got, [{"a": "none", "b": "none"}, {"a": None, "b": None},
                               {"a": "no answer", "b": "no answer"}, True])

    def test_offline_nothing_is_asked(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + SHOWN + r"""
          S.imagery = "offline";
          thenResolve(); await flush();
          console.log(JSON.stringify([ASKED.length, shown().fail]));
        """)
        self.assertEqual(got, [0, {"gibs": True, "wayback": False}])
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenResolveRuns -v`
Expected: 12 tests: 10 FAIL and 2 ERROR, on `ReferenceError: thenResolve is not defined`. `FAILED (failures=10, errors=2)`.

- [ ] **Step 3: Add the script**

Append to `_JS` in `elnino/thennow.py`, just before its closing `"""`:

```js
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
  // The earlier date on the left, once neither side is still being found.
  function thenOrder(T) {
    if (T.look.a || T.look.b) return;
    var a = sideDay(T, "a"), b = sideDay(T, "b");
    if (!a || !b || a <= b) return;
    ["want", "got", "note", "look"].forEach(function (f) { var v = T[f].a; T[f].a = T[f].b; T[f].b = v; });
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
  // nearest its date.
  function thenGibs(T, src) {
    var q = {a: ++T.ask.a, b: ++T.ask.b};
    T.look.a = T.look.b = "asking";
    thenChanged();
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
      if (T !== S.then || T.source !== src.id) return;
      T.fail.gibs = true;
      ["a", "b"].forEach(function (k) { if (q[k] === T.ask[k]) T.look[k] = NO_ANSWER; });
      thenChanged();
    });
  }
  // Esri's archive: the versions of the place, and on each side the one
  // captured nearest its date. The versions already drawn stay while a
  // moved pin's are found.
  function thenArchive(T) {
    var lon = T.lon, lat = T.lat, q = {a: ++T.ask.a, b: ++T.ask.b};
    if (!T.versions) T.look.a = T.look.b = "asking";
    thenChanged();
    wbVersions(lon, lat).then(function (got) {
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
    });
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
  function thenHls(T, k, by) {
    var src = thenSrc("hls"), q = ++T.ask[k], lon = T.lon, lat = T.lat, today = dayZ(Date.now());
    var from = by ? T.got[k] : T.want[k];
    if (!from) return;
    if (!by) {
      T.note[k] = clampNote(src.first, today, from);
      from = from < src.first ? src.first : from > today ? today : from;
    }
    function still() { return T === S.then && T.source === "hls" && T.ask[k] === q && T.lon === lon && T.lat === lat; }
    T.look[k] = "looking";
    thenChanged();
    hlsHunt(hlsDays(from, by, src.first, today), hlsTile(lon, lat), still).then(function (day) {
      if (!still()) return;
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
  function thenChanged() { thenApply(); dirty(); }
```

- [ ] **Step 4: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 68 tests, OK.

- [ ] **Step 5: Mutation check**

In `clampNote`, change `> 31) return "asked for "` to `> 0) return "asked for "`; run `python -m unittest tests.test_thennow.TestThenResolveRuns`; expected FAIL in `test_a_date_outside_the_archive_takes_its_nearest_end_and_says_so`. Put it back; run again; expected OK.

- [ ] **Step 6: Commit**

```bash
git add elnino/thennow.py tests/test_thennow.py
git commit -m "Then and now: each side's date found in its archive" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


---

### Task 7: The bar, the chips and the readout at the pin

**Files:**
- Modify: `elnino/thennow.py` (`_JS`: appended; `thenChanged`)
- Modify: `elnino/stormdesk.py` (`_JS`: `render`)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: everything of Tasks 3-6; `D.then.scales` (Task 1); the page's `classify(scale, rgba)`, `googleLinks(lat, lon, z)`, `tileUrl(s, key, z, row, col)`, `esc`, `signedText`, `monthIndex` (Task 3).
- Produces: `lookWords(T, k)`, `chipText(T, k)`, `sideWords(T, k)`; `setText(el, text)`, `setHidden(el, on)`, `setValue(el, v)` (write only on change); `thenCan(T, k, by) -> bool`; `resText(m)`, `captureShort(v)`, `captureText(v)`; `thenCaptures(T, select, k)`; `thenReadText(T)`; `HIDDEN`; `thenNotes(T)`; `thenPixel(src, day, lon, lat) -> Promise<rgba | null | false>`; `binMid(bin)`; `readOne(src, day, lon, lat)`; `thenRead()`; `thenRender()` (called by `render()` while entered); `thenStep(k, by)`; `thenSetWant(k, text)`; `thenCapture(k, id)`; `thenPreset(id)`; `thenSource(id)`; `thenStripAt(frac)`; `flightMs(z)`. For the tests: `MODIS_DAYS`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
MODIS_DAYS = 'route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-28/P1D</Domain>");\n'


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenBarRuns(unittest.TestCase):
    """The bar and the chips: each side's date and the season around it,
    what a side waits on, the archive's captures, the readout at the pin,
    and the controls that move the dates."""

    def test_each_side_s_chip_date_and_words_name_its_season(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=8) + r"""
          thenRender();
          function side(k) {
            return {chip: $("then-chip-" + k).textContent, hidden: $("then-chip-" + k).hidden,
                    words: $("then-words-" + k).textContent, date: $("then-date-" + k).value,
                    cap: $("then-cap-" + k).hidden, line: $("then-line-" + k).getAttribute("x1")};
          }
          console.log(JSON.stringify({a: side("a"), b: side("b"), right: $("then-chip-a").style.right,
                                      left: $("then-chip-b").style.left, source: $("then-source").value,
                                      street: $("then-gmaps").getAttribute("href")}));
        """)
        self.assertEqual(got["a"], {"chip": "15 Nov 2014 · RONI +0.6, OND 2014", "hidden": False,
                                    "words": "OND 2014, centred on Nov 2014: RONI +0.6, weak El Niño, the "
                                             "2014-16 episode.",
                                    "date": "2014-11-15", "cap": True, "line": "178.5"})
        self.assertEqual(got["b"]["chip"], "15 Nov 2015 · RONI +2.6, OND 2015")
        self.assertEqual(got["b"]["line"], "190.5")
        # The divider sits at 30 % of 800 px: each chip keeps 26 px from it.
        self.assertEqual((got["right"], got["left"]), ("586px", "266px"))
        self.assertEqual(got["source"], "modis")
        self.assertEqual(got["street"], "https://www.google.com/maps/@?api=1&map_action=pano"
                                        "&viewpoint=-3.100000,-60.025000")

    def test_a_side_still_being_found_says_what_it_waits_on(self):
        got = _run(self, _entered("modis", None, None) + r"""
          S.then.want = {a: "2014-11-15", b: "2015-11-15"};
          var out = [];
          function say(source, look) {
            S.then.source = source; S.then.look = {a: look, b: ""};
            out.push([chipText(S.then, "a"), sideWords(S.then, "a")]);
          }
          say("modis", "asking"); say("modis", "no answer"); say("hls", "looking"); say("hls", "none");
          say("archive", "asking"); say("archive", "no answer"); say("archive", "none");
          console.log(JSON.stringify(out));
        """)
        self.assertEqual(got, [
            ["15 Nov 2014 · asking NASA GIBS for its days", "Asking NASA GIBS for its days."],
            ["15 Nov 2014 · NASA GIBS did not answer", "NASA GIBS did not answer."],
            ["15 Nov 2014 · looking for a day with an image here", "Looking for a day with an image here."],
            ["15 Nov 2014 · no image here within 20 days of 15 Nov 2014",
             "No image here within 20 days of 15 Nov 2014."],
            ["15 Nov 2014 · asking Esri’s archive for the versions here",
             "Asking Esri’s archive for the versions here."],
            ["15 Nov 2014 · Esri’s archive did not answer", "Esri’s archive did not answer."],
            ["15 Nov 2014 · Esri’s archive has no imagery here", "Esri’s archive has no imagery here."]])

    def test_the_archive_s_versions_are_a_menu_and_each_capture_is_told(self):
        got = _run(self, _entered("archive", 80, 90, z=16) + r"""
          thenRender();
          console.log(JSON.stringify({menu: $("then-cap-a").innerHTML, value: [$("then-cap-a").value, $("then-cap-b").value],
                                      hidden: [$("then-cap-a").hidden, $("then-date-a").hidden],
                                      steps: [$("then-back-a").disabled, $("then-next-a").disabled,
                                              $("then-back-b").disabled, $("then-next-b").disabled],
                                      chips: [$("then-chip-a").textContent, $("then-chip-b").textContent],
                                      read: $("then-read").textContent}));
        """)
        self.assertEqual(got["menu"], '<option value="90">31 Oct 2021</option>'
                                      '<option value="80">26 Jun 2019 (release)</option>')
        self.assertEqual(got["value"], ["80", "90"])
        self.assertEqual(got["hidden"], [False, True])
        # The left holds the oldest version: it can only step on; the right the newest.
        self.assertEqual(got["steps"], [True, False, False, True])
        self.assertEqual(got["chips"], ["26 Jun 2019 · latest RONI −0.6, NDJ 2016",
                                        "31 Oct 2021 · latest RONI −0.6, NDJ 2016"])
        self.assertEqual(got["read"], "Left: capture date not given, first shown in the 26 Jun 2019 release. "
                                      "Right: taken 31 Oct 2021 by Maxar, WV02 at 50 cm, first shown in the "
                                      "1 Mar 2024 release.")

    def test_versions_without_capture_dates_are_named_by_release(self):
        got = _run(self, _entered("archive", 80, 90, z=16) + r"""
          S.then.versions.forEach(function (v) { v.capture = null; v.when = v.day; });
          thenRender();
          console.log(JSON.stringify([$("then-cap-b").innerHTML, $("then-chip-b").textContent,
                                      $("then-note").textContent]));
        """)
        self.assertEqual(got[0], '<option value="90">1 Mar 2024 (release)</option>'
                                 '<option value="80">26 Jun 2019 (release)</option>')
        self.assertTrue(got[1].startswith("1 Mar 2024 · "))
        self.assertTrue(got[2].startswith("A version whose capture date Esri’s metadata did not give is named "
                                          "by the release that first showed it. While a place is entered, "
                                          "today’s storms"))

    def test_the_ocean_s_temperature_is_read_at_the_pin_on_both_sides(self):
        got = _run(self, _want("sst", "2014-11-15", "2015-11-15") + r"""
          route("gibs/GHRSST", "<Domain>2002-09-01/2026-09-27/P1D</Domain>");
          paint("Anomalies/2014-11-15/", [237, 237, 152, 255]);
          paint("Anomalies/2015-11-15/", [249, 1, 19, 255]);
          // Read as soon as both sides have their days: nothing else asks.
          thenResolve(); await flush();
          thenRender();
          var warm = $("then-read").textContent;
          S.then.got = {a: "2014-11-16", b: "2015-11-16"};
          paint("Anomalies/2014-11-16/", [0, 0, 0, 0]);
          thenRead(); await flush(); thenRender();
          var gaps = $("then-read").textContent;
          S.then.got = {a: "2014-11-17", b: "2015-11-17"};
          paint("Anomalies/2014-11-17/", [107, 0, 219, 255]); paint("Anomalies/2015-11-17/", [128, 0, 0, 255]);
          thenRead(); await flush(); thenRender();
          console.log(JSON.stringify([warm, gaps, $("then-read").textContent, IMAGES[0]]));
        """)
        self.assertEqual(got[0], "At the pin, left: +0.3 to +0.4 °C; right: +2.0 to +2.1 °C; a change of about "
                                 "+1.7 °C.")
        self.assertEqual(got[1], "At the pin, left: no data (land, ice or a gap); right: its tile did not arrive.")
        self.assertEqual(got[2], "At the pin, left: below −3.0 °C; right: +3.0 °C or more; the change runs past "
                                 "the end of NASA’s scale.")
        self.assertEqual(got[3], "https://gibs/GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies/2014-11-15/"
                                 "GoogleMapsCompatible_Level6/6/32/21.png")

    def test_vegetation_is_read_to_three_places(self):
        left = next(rgb for lo, hi, rgb in thennow.NDVI_COLOURS if lo == 0.8)
        right = next(rgb for lo, hi, rgb in thennow.NDVI_COLOURS if lo == 0.6)
        got = _run(self, _entered("ndvi", "2014-11-17", "2015-11-17", z=7) + r"""
          paint("NDVI_16Day/2014-11-17/", %s);
          paint("NDVI_16Day/2015-11-17/", %s);
          thenRead(); await flush(); thenRender();
          console.log(JSON.stringify($("then-read").textContent));
        """ % (json.dumps(list(left) + [255]), json.dumps(list(right) + [255])))
        self.assertEqual(got, "At the pin, left: NDVI 0.800 to 0.810; right: NDVI 0.600 to 0.610; a change of "
                              "about −0.200.")

    def test_the_pixel_read_wraps_at_the_date_line(self):
        got = _run(self, r"""
          var src = thenSrc("sst"), at = [];
          paint("Anomalies/", [237, 237, 152, 255]);
          for (var lon of [179.99, -179.99, 540.5]) {
            await thenPixel(src, "2015-11-15", lon, -18.14);
            at.push(CTX.at);
          }
          console.log(JSON.stringify([IMAGES.map(function (u) { return u.split("Level6/")[1]; }), at]));
        """)
        # Either side of 180 degrees: the last column's last pixel, then the
        # first column's first; 540.5 is -179.5, 22 pixels into the first.
        self.assertEqual(got, [["6/35/63.png", "6/35/0.png", "6/35/0.png"],
                               [[255, 71, 1, 1], [0, 71, 1, 1], [22, 71, 1, 1]]])

    def test_a_cleared_or_impossible_date_is_ignored(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15", preset="ep0-before") + MODIS_DAYS + r"""
          thenResolve(); await flush();
          var asked = ASKED.length, calls = CALLS.length, field = $("then-date-a");
          ["", "2015-02-30", "0201-11-15", "2031-01-01", "1999-12-31", "2014-11-15"].forEach(function (text) {
            field.fire("change", {target: {value: text}});
          });
          await flush();
          var kept = [S.then.want.a, S.then.got.a, S.then.preset, ASKED.length === asked, CALLS.length === calls];
          field.fire("change", {target: {value: "2015-01-10"}}); await flush();
          console.log(JSON.stringify([kept, S.then.want.a, S.then.got.a, S.then.preset]));
        """)
        self.assertEqual(got, [["2014-11-15", "2014-11-15", "ep0-before", True, True], "2015-01-10", "2015-01-10", ""])

    def test_a_typed_date_is_not_overwritten_while_it_is_typed(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15") + r"""
          var field = $("then-date-a");
          field.value = "2015-0"; document.activeElement = field;
          thenRender();
          var typing = field.value;
          document.activeElement = null; thenRender();
          console.log(JSON.stringify([typing, field.value]));
        """)
        self.assertEqual(got, ["2015-0", "2014-11-15"])

    def test_a_step_moves_a_side_to_the_next_time_or_version(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15", preset="ep0-before") + MODIS_DAYS + r"""
          thenResolve(); await flush();
          $("then-back-a").fire("click"); await flush();
          var daily = [S.then.got.a, S.then.want.a, S.then.preset];
          S.then.got.b = "2026-09-28"; thenRender();
          var end = [$("then-next-b").disabled, $("then-back-b").disabled];
          """ + _entered("archive", 80, 90, z=16) + r"""
          thenStep("a", 1);
          var archive = [S.then.got.a, S.then.want.a];
          thenStep("a", 1);
          console.log(JSON.stringify([daily, end, archive, S.then.got.a]));
        """)
        # The archive's left steps on to the newer version, and no further.
        self.assertEqual(got, [["2014-11-14", "2014-11-14", ""], [True, False], [90, "2021-10-31"], 90])

    def test_an_event_s_choice_moves_both_sides_and_own_dates_keep_them(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + MODIS_DAYS + r"""
          thenResolve(); await flush();
          $("then-event").fire("change", {target: {value: "ep0-after"}}); await flush();
          var event = [S.then.preset, S.then.got.a, S.then.got.b];
          $("then-event").fire("change", {target: {value: ""}}); await flush();
          console.log(JSON.stringify([event, S.then.preset, S.then.got.a, S.then.got.b]));
        """)
        self.assertEqual(got, [["ep0-after", "2015-11-15", "2016-11-15"], "", "2015-11-15", "2016-11-15"])

    def test_another_source_is_flown_to_at_its_own_zoom(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + MODIS_DAYS + r"""
          route("gibs/GHRSST", "<Domain>2002-09-01/2026-09-27/P1D</Domain>");
          thenResolve(); await flush();
          $("then-source").fire("change", {target: {value: "sst"}});
          var flight = FLIGHTS[FLIGHTS.length - 1], layer = LAYERS["then-a"].global;
          await flush();
          console.log(JSON.stringify([flight.z, flight.ms, layer, S.then.got]));
        """)
        self.assertEqual(got, [4, 1400, "GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies",
                               {"a": "2014-11-15", "b": "2015-11-15"}])

    def test_a_tap_on_the_strip_moves_the_nearer_side_to_that_month(self):
        got = _run(self, _want("modis", "2014-11-15", "2016-11-15") + MODIS_DAYS + r"""
          thenResolve(); await flush();
          var strip = $("then-strip");
          strip.box = {left: 10, top: 0, width: 321, height: 60};
          strip.fire("click", {clientX: 10 + 190.5}); await flush();
          var one = [S.then.got.a, S.then.got.b];
          strip.fire("click", {clientX: 10 + 320.9}); await flush();
          console.log(JSON.stringify([one, S.then.got.b]));
        """)
        # November 2015 is a day nearer the left's November 2014 than the
        # right's November 2016; September 2026 is nearer the right.
        self.assertEqual(got, [["2015-11-15", "2016-11-15"], "2026-09-15"])

    def test_the_names_switch_takes_esri_s_names_off_both_sides(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15") + r"""
          var on = [!!LAYERS["then-a"].over, !!LAYERS["then-b"].over];
          $("then-names").fire("change", {target: {checked: false}});
          console.log(JSON.stringify([on, !!LAYERS["then-a"].over, !!LAYERS["then-b"].over, S.then.names]));
        """)
        self.assertEqual(got, [[True, True], False, False, False])

    def test_the_bar_is_drawn_with_the_map(self):
        self.assertIn("dayControls();\n    if (S.then) thenRender();", _js_function(stormdesk._JS, "render"))
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenBarRuns -v`
Expected: 15 tests: 11 FAIL and 4 ERROR, on functions not yet defined (`chipText`, `thenRender`, `thenPixel`, `thenRead`), listeners not yet added, and `render` without its hook. `FAILED (failures=11, errors=4)`.

- [ ] **Step 3: Add the script**

Append to `_JS` in `elnino/thennow.py`, just before its closing `"""`:

```js
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
  var HIDDEN = "While a place is entered, today’s storms, outlook areas, NASA’s reference overlays, " +
    "the ocean and flood tiles and the El Niño composite are not drawn: they belong to today, not to either date.";
  function thenNotes(T) {
    var src = thenSrc(T.source), names = {a: "Left", b: "Right"}, out = [];
    ["a", "b"].forEach(function (k) { if (T.note[k]) out.push(names[k] + ": " + T.note[k] + "."); });
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
    setValue($("then-source"), T.source);
    setValue($("then-event"), T.preset);
    if ($("then-names").checked !== T.names) $("then-names").checked = T.names;
    ["a", "b"].forEach(function (k) {
      var date = $("then-date-" + k), cap = $("then-cap-" + k), day = sideDay(T, k);
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
      var line = $("then-line-" + k), x = String(day ? monthIndex(day) + 0.5 : -1);
      if (line.getAttribute("x1") !== x) { line.setAttribute("x1", x); line.setAttribute("x2", x); }
    });
    setText($("then-read"), thenReadText(T));
    setText($("then-note"), thenNotes(T));
    var href = googleLinks(T.lat, T.lon, S.z).street;
    if ($("then-gmaps").getAttribute("href") !== href) $("then-gmaps").setAttribute("href", href);
  }
  // ---- the bar's controls --------------------------------------------------------
  // A side a step back or on: the day before or after with an image here;
  // the older or newer version; the time GIBS lists before or after.
  function thenStep(k, by) {
    var T = S.then;
    if (!T || !thenCan(T, k, by)) return;
    var src = thenSrc(T.source);
    T.preset = ""; T.apart = "";
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
  // today, or nothing is done, and the field shows the side's date again.
  function thenSetWant(k, text) {
    var T = S.then;
    if (!T || !realDay(text) || text < "2000-01-01" || text > dayZ(Date.now()) || text === T.want[k]) return;
    T.want[k] = text; T.preset = ""; T.apart = "";
    if (thenSrc(T.source).kind === "hls") thenHls(T, k, 0); else thenResolve();
  }
  function thenCapture(k, id) {
    var T = S.then, v = T && thenVersion(T, +id);
    if (!v) return;
    T.ask[k]++;
    T.got[k] = v.id; T.want[k] = v.when; T.note[k] = ""; T.preset = ""; T.apart = "";
    thenOrder(T);
    thenCredits(T);
    thenChanged();
  }
  // An event's two dates; "" keeps the dates as they are, as the reader's own.
  function thenPreset(id) {
    var T = S.then, p = presetOf(id);
    if (!T) return;
    T.preset = p ? id : ""; T.apart = "";
    if (!p) { thenChanged(); return; }
    T.want = {a: p.left, b: p.right};
    thenResolve();
  }
  // Another archive for the same place and dates, flown to its own zoom.
  function thenSource(id) {
    var T = S.then, src = thenSrc(id);
    if (!T || !src || id === T.source) return;
    T.source = id;
    T.got = {a: null, b: null}; T.note = {a: "", b: ""}; T.look = {a: "", b: ""};
    T.read = null; T.readKey = ""; T.apart = ""; T.fail = {gibs: false, wayback: false};
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
```

- [ ] **Step 4: Hook the page**

Each edit's first text is found exactly once in its file; replace it with the second.

1. `elnino/stormdesk.py`, `render`: replace

```js
    dayControls();
    scrubRead.textContent
```

   with

```js
    dayControls();
    if (S.then) thenRender();
    scrubRead.textContent
```

2. `elnino/thennow.py`, `thenChanged`: replace

```js
  function thenChanged() { thenApply(); dirty(); }
```

   with

```js
  function thenChanged() { thenApply(); thenRead(); dirty(); }
```


- [ ] **Step 5: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 83 tests, OK.

- [ ] **Step 6: Run the page's own tests the hooks touch**

Run: `python -m unittest tests.test_tracker.TestStormDeskPayload tests.test_tracker.TestStormDeskPage tests.test_tracker.TestDaySearchRuns tests.test_tracker.TestStreetMaps tests.test_tracker.TestStreetMapRuns tests.test_tracker.TestCompositeOnTheMapRuns tests.test_tracker.TestEnsoHere tests.test_tracker.TestEnsoHereRuns tests.test_tracker.TestEnsoTiles tests.test_tracker.TestEnsoTilesRuns tests.test_tracker.TestEnsoNow tests.test_tracker.TestEnsoShapesRuns tests.test_tracker.TestGoogleHere tests.test_tracker.TestTwoPages tests.test_tracker.TestHashRuns tests.test_tracker.TestAddressSearchRuns tests.test_tracker.TestAddressSearch tests.test_tracker.TestMapDocumented tests.test_tracker.TestNoWayBackRuns tests.test_tracker.TestLayerChoiceRuns tests.test_tracker.TestWorldCopiesRuns tests.test_tracker.TestEsriCoverageRuns tests.test_tracker.TestGlobePanel tests.test_tracker.TestImageryGeometry tests.test_tracker.TestRegressions`
Expected: 163 tests, OK (the page's behaviour unchanged when nothing is entered).

- [ ] **Step 7: Mutation check**

Take `thenRead(); ` back out of `thenChanged`; run `python -m unittest tests.test_thennow.TestThenBarRuns`; expected FAIL in `test_the_ocean_s_temperature_is_read_at_the_pin_on_both_sides`. Put it back; run again; expected OK.

- [ ] **Step 8: Commit**

```bash
git add elnino/thennow.py elnino/stormdesk.py tests/test_thennow.py
git commit -m "Then and now: the bar, the chips and the readout at the pin" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


---

### Task 8: Entering a place and leaving it

**Files:**
- Modify: `elnino/thennow.py` (`_JS`, appended)
- Modify: `elnino/stormdesk.py` (`_JS`: `setLayer`, `setCompare`, `flyTo`, `go`, `applyHash`, the `#compare-layer` and `#swap` listeners, `refresh`, `showHere`, the click listener, `clearHere`, `window.stormDesk`)
- Modify: `elnino/worldmap.py` (`_JS`: `setEnso`, `showRegion`)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: `thenFresh`, `thenApply` (Task 5); `thenResolve`, `sideDay` (Task 6); `setHidden`, `flightMs` (Task 7); `realDay`, `presetOf` (Task 3); the page's `nearestPlace`, `named`, `kms`, `where`, `cellAt`, `pin`, `animate`, `settle`, `setLayer`, `setCompare`, `setLoop`.
- Produces: `placeLabel(lon, lat)`; `thenPick(lon, lat) -> "archive" | "sst"`; `thenShow(on)`; `lonIn(lon)`; `thenEnter(lon, lat, label, opts) -> true` (`opts`: `source`, `a`, `b` (both real days, or neither is taken), `z`, `instant`); `thenLeave() -> bool`; `thenMove(lon, lat)`; `thenView() -> {lon, lat, label, source, preset, left, right, look} | null`; `stormDesk.enter(lon, lat, opts)`, `stormDesk.leave()`, `stormDesk.view().then`. For the tests: `MANAUS`, `BEFORE`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
# Manaus entered on MODIS, the two sides at 15 November 2014 and 2015.
MANAUS = 'thenEnter(-60.025, -3.1, "Manaus", {source: "modis", a: "2014-11-15", b: "2015-11-15"});\n'
# The map as the reader left it before entering.
BEFORE = 'S.layer = "satellite"; S.second = "infrared"; S.compare = false; S.split = 0.3;\n'


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenEnterRuns(unittest.TestCase):
    """Into a place and out again: the pin, the two sides at the divider and
    the flight in; the map as it was on the way out; the place moved by a
    tap; the page's other controls leaving first."""

    def test_entering_flies_in_and_compares_two_dates_at_the_pin(self):
        got = _run(self, BEFORE + r"""
          LAND["-60,-3"] = true; S.z = 3;
          var scrubRow = SELECTED[".deskscrub"] = new El("scrubrow"), button = new El("b");
          button.setAttribute("aria-pressed", "true"); LISTS["[data-layer]"] = [button];
          var done = thenEnter(-60.025, -3.1), T = S.then, f = FLIGHTS[0];
          console.log(JSON.stringify({done: done, source: T.source, label: T.label, preset: T.preset, want: T.want,
                                      look: T.look, back: T.back, map: [S.layer, S.second, S.compare, S.split],
                                      pin: [S.pin.lon.toFixed(6), S.pin.lat, S.pin.label],
                                      flight: [f.x === mx(-60.025), f.y === my(-3.1), f.z, f.ms],
                                      bar: $("then-bar").hidden, scrub: scrubRow.hidden,
                                      pressed: button.getAttribute("aria-pressed")}));
        """)
        self.assertEqual(got["done"], True)
        self.assertEqual((got["source"], got["label"]), ("archive", "Manaus, Amazonas, Brazil"))
        # A year ago on the left, the latest on the right, until chosen.
        self.assertEqual((got["preset"], got["want"]), ("now", {"a": "2025-09-29", "b": "2026-09-29"}))
        self.assertEqual(got["look"], {"a": "asking", "b": "asking"})
        self.assertEqual(got["back"], {"layer": "satellite", "second": "infrared", "compare": False, "split": 0.3,
                                       "loop": False})
        self.assertEqual(got["map"], ["then-a", "then-b", True, 0.5])
        self.assertEqual(got["pin"], ["-60.025000", -3.1, "Manaus, Amazonas, Brazil"])
        # From zoom 3 to the archive's 16: the longest flight, 2 s.
        self.assertEqual(got["flight"], [True, True, 16, 2000])
        self.assertEqual((got["bar"], got["scrub"], got["pressed"]), (False, True, "false"))

    def test_a_point_at_sea_opens_on_the_ocean_and_on_land_on_the_archive(self):
        got = _run(self, r"""
          LAND["-60,-3"] = true;
          var picks = [thenPick(-60.025, -3.1), thenPick(-140, 0), thenPick(178.5, -18.2)];
          // Without the composite's grid, a town within 30 km decides.
          cellAt = function () { throw new Error("no grid"); };
          picks.push(thenPick(-60.025, -3.1), thenPick(-140, 0));
          thenEnter(-140, 0);
          console.log(JSON.stringify([picks, S.then.source, S.then.label, FLIGHTS[0].z, FLIGHTS[0].ms]));
        """)
        self.assertEqual(got, [["archive", "sst", "archive", "archive", "sst"], "sst", "0.00N 140.00W", 4, 800])

    def test_exit_restores_the_layers_and_leaves_the_view_where_it_is(self):
        got = _run(self, BEFORE + r"""
          var scrubRow = SELECTED[".deskscrub"] = new El("scrubrow");
          """ + MANAUS + r"""
          var during = [scrubRow.hidden, $("then-bar").hidden];
          S.z = 11.5; S.x = 0.34; CALLS = [];
          $("then-exit").fire("click");
          console.log(JSON.stringify({during: during, then: S.then, sides: [!!LAYERS["then-a"], !!LAYERS["then-b"]],
                                      map: [S.layer, S.second, S.compare, S.split], view: [S.x, S.z], pin: S.pin,
                                      calls: CALLS, bar: $("then-bar").hidden, scrub: scrubRow.hidden,
                                      chips: [$("then-chip-a").hidden, $("then-chip-b").hidden], again: thenLeave()}));
        """)
        self.assertEqual(got, {"during": [True, False], "then": None, "sides": [False, False],
                               "map": ["satellite", "infrared", False, 0.3], "view": [0.34, 11.5], "pin": None,
                               "calls": ["setLayer satellite", "setCompare false", "dirty"], "bar": True,
                               "scrub": False, "chips": [True, True], "again": False})

    def test_leaving_takes_the_entered_place_out_of_the_address(self):
        got = _run(self, MANAUS + r"""
          location.hash = "#then=-3.1000,-60.0250,8.00,modis,2014-11-15,2015-11-15";
          location.href = "file:///C:/elnino/output/map.html" + location.hash;
          thenLeave();
          function replaced() { return CALLS.filter(function (c) { return c.indexOf("replaceState") === 0; }); }
          var cleared = [replaced(), location.hash];
          """ + MANAUS + r"""
          location.hash = "#at=-3.1,-60.0"; CALLS = [];
          thenLeave();
          console.log(JSON.stringify([cleared, replaced(), location.hash]));
        """)
        self.assertEqual(got, [[["replaceState file:///C:/elnino/output/map.html"], ""], [], "#at=-3.1,-60.0"])

    def test_here_s_pin_comes_back_after_and_clear_keeps_the_entered_pin(self):
        extra = _js_function(stormdesk.script(), "clearHere") + '\nfunction showHere() { note("showHere"); }\n'
        got = _run(self, r"""
          S.here = {lon: 178.44, lat: -18.14, label: "Suva"}; S.pin = {lon: 178.44, lat: -18.14, label: "Suva"};
          """ + MANAUS + r"""
          var entered = S.pin.label;
          thenLeave();
          var back = S.pin.label;
          """ + MANAUS + r"""
          clearHere();
          var cleared = [S.here, S.pin && S.pin.label];
          thenLeave();
          console.log(JSON.stringify([entered, back, cleared, S.pin]));
        """, extra=extra)
        self.assertEqual(got, ["Manaus", "Suva", [None, "Manaus"], None])

    def test_the_loop_stops_while_entered_and_runs_again_after(self):
        got = _run(self, r"""
          S.loop = true; S.scrub = 6;
          var scrubRow = SELECTED[".deskscrub"] = new El("scrubrow");
          """ + MANAUS + r"""
          var during = [S.loop, S.then.back.loop, scrubRow.hidden];
          thenLeave();
          var after = [S.loop, S.scrub, scrubRow.hidden];
          S.loop = false;
          """ + MANAUS + r"""
          thenLeave();
          console.log(JSON.stringify([during, after, S.loop,
                                      CALLS.filter(function (c) { return c.indexOf("setLoop") === 0; })]));
        """)
        # The scrubber is hidden while entered and keeps its hour; a loop
        # left off stays off.
        self.assertEqual(got, [[False, True, True], [True, 6, False], False, ["setLoop false", "setLoop true"]])

    def test_entering_again_moves_the_place_and_keeps_the_source_dates_and_way_back(self):
        got = _run(self, BEFORE + MANAUS + r"""
          S.split = 0.7; S.then.names = false;
          thenEnter(178.44, -18.14);
          var T = S.then;
          console.log(JSON.stringify([T.label, T.source, T.want, T.preset, T.names, T.back, S.split, S.pin.label,
                                      FLIGHTS.length]));
        """)
        self.assertEqual(got, ["Suva, Central, Fiji", "modis", {"a": "2014-11-15", "b": "2015-11-15"}, "", False,
                               {"layer": "satellite", "second": "infrared", "compare": False, "split": 0.3,
                                "loop": False}, 0.7, "Suva, Central, Fiji", 2])

    def test_a_tap_while_entered_moves_the_pin_and_keeps_the_dates(self):
        got = _run(self, MODIS_DAYS + MANAUS + r"""
          await flush();
          var asked = ASKED.length;
          thenMove(-61.5, -3.3);
          await flush();
          console.log(JSON.stringify([S.then.label, S.pin.label, [S.then.lon, S.then.lat], S.then.got,
                                      ASKED.length - asked, FLIGHTS.length]));
        """)
        self.assertEqual(got, ["165 km from Manaus, Amazonas, Brazil", "165 km from Manaus, Amazonas, Brazil",
                               [-61.5, -3.3], {"a": "2014-11-15", "b": "2015-11-15"}, 0, 1])

    def test_a_move_keeps_the_archive_s_versions_drawn_until_the_new_walk_answers(self):
        got = _run(self, WB_ROUTES + r"""
          thenEnter(-60.025, -3.1, "Manaus", {source: "archive", a: "2019-01-01", b: "2022-01-01"});
          await flush();
          var before = [S.then.got.a, S.then.got.b], asked = ASKED.length;
          thenMove(-60.2, -3.3);
          var moving = [S.then.look.a, S.then.look.b, LAYERS["then-a"].tiles, S.then.versions.length];
          await flush();
          console.log(JSON.stringify([before, moving, [S.then.got.a, S.then.got.b], ASKED.length > asked]));
        """)
        self.assertEqual(got, [[80, 90], ["", "", "https://wb/tile/80/{z}/{y}/{x}", 2], [80, 90], True])

    def test_choosing_a_layer_or_the_comparison_while_entered_leaves_first(self):
        extra = "\n".join(_js_function(stormdesk.script(), n) for n in ("setLayer", "setCompare"))
        got = _run(self, r"""
          S.layer = "satellite"; S.second = "infrared"; S.compare = true; S.split = 0.3;
          """ + MANAUS + r"""
          var ok = setLayer("streets");
          var one = [S.then, S.layer, S.second, S.compare, S.split, !!LAYERS["then-a"]];
          """ + MANAUS + r"""
          setCompare(false);
          console.log(JSON.stringify([ok, one, S.then, S.layer, S.compare]));
        """, extra=extra)
        self.assertEqual(got, [True, [None, "streets", "infrared", True, 0.3, False], None, "streets", False])

    def test_the_page_s_other_controls_leave_first(self):
        js = stormdesk.script()
        for name in ("setLayer", "setCompare", "flyTo", "setEnso", "showRegion"):
            self.assertEqual(_js_function(js, name).split("\n")[1], "    if (S.then) thenLeave();", name)
        self.assertIn('if (r.kind === "search") { geocode(r.q); return true; }\n    if (S.then) thenLeave();',
                      _js_function(js, "go"))
        self.assertIn("if (!h) return false;\n    if (S.then) thenLeave();", _js_function(js, "applyHash"))
        for control in ('$("swap").addEventListener("click", function () {',
                        '$("compare-layer").addEventListener("change", function (e) {'):
            self.assertIn(control + "\n    if (S.then) thenLeave();", js)

    def test_a_refresh_while_entered_draws_the_sides_again(self):
        extra = _js_function(stormdesk.script(), "refresh") + r"""
function prepare() { note("prepare"); LAYERS = {streets: {id: "streets", kind: "map"}}; }
function select() {}
function showHere() {}
function ages() {}
function tab() {}
var ensoSaid = "", coastDone = 1, coastD = "M0", coastG = {innerHTML: ""}, STORMS = [], BYID = {}, NEXT = null;
function DOMParser() {}
DOMParser.prototype.parseFromString = function () {
  return {getElementById: function (id) { return id === "desk-data" ? {textContent: JSON.stringify(NEXT)} : null; }};
};
"""
        got = _run(self, MODIS_DAYS + MANAUS + r"""
          await flush();
          NEXT = JSON.parse(JSON.stringify(D)); NEXT.built = "later";
          route("map.html", "<html></html>");
          refresh(); await flush();
          console.log(JSON.stringify([CALLS.indexOf("prepare") >= 0, S.layer, S.second,
                                      LAYERS["then-a"] && LAYERS["then-a"].time, LAYERS["then-b"] && LAYERS["then-b"].time]));
        """, extra=extra)
        self.assertEqual(got, [True, "then-a", "then-b", "2014-11-15", "2015-11-15"])

    def test_here_offers_to_enter_the_point_it_shows(self):
        js = stormdesk.script()
        self.assertIn('data-here="enter">Enter here</button>', _js_function(js, "showHere"))
        self.assertIn('if (el.getAttribute("data-here") === "enter") { if (S.here) thenEnter(S.here.lon, S.here.lat, '
                      'S.here.label); }', js)

    def test_the_page_s_api_enters_leaves_and_tells_what_is_entered(self):
        js = stormdesk.script()
        self.assertIn("enter: function (lon, lat, opts) { return thenEnter(lon, lat, null, opts || {}); },", js)
        self.assertIn("leave: function () { return thenLeave(); },", js)
        self.assertIn("dayState: S.dayState, then: thenView()};", js)
        got = _run(self, MODIS_DAYS + r"""
          var none = thenView();
          thenEnter(-60.025, -3.1, null, {source: "modis", a: "2015-11-15", b: "2014-11-15"});
          await flush();
          var view = thenView();
          thenLeave();
          // Dates that are not days of the calendar are not taken.
          thenEnter(-60.025, -3.1, null, {source: "modis", a: "2015-02-30", b: "2014-11-15"});
          console.log(JSON.stringify([none, view, S.then.preset, S.then.want]));
        """)
        self.assertEqual(got, [None, {"lon": -60.025, "lat": -3.1, "label": "Manaus, Amazonas, Brazil",
                                      "source": "modis", "preset": "", "left": "2014-11-15", "right": "2015-11-15",
                                      "look": {"a": "", "b": ""}},
                               "now", {"a": "2025-09-29", "b": "2026-09-29"}])
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenEnterRuns -v`
Expected: 14 tests: 13 FAIL and 1 ERROR, on `ReferenceError: thenEnter is not defined` (`thenPick` in one) and the engine's text without its hooks. `FAILED (failures=13, errors=1)`.

- [ ] **Step 3: Add the script**

Append to `_JS` in `elnino/thennow.py`, just before its closing `"""`:

```js
  // ---- entering a place, and leaving it ----------------------------------------
  // A point named as Here names one: the town it is in, the distance from
  // the nearest, or its latitude and longitude.
  function placeLabel(lon, lat) {
    var p = nearestPlace(lon, lat);
    return p && p.km <= 25 ? named(p.p) : p && p.km <= 400 ? kms(p.km) + " from " + named(p.p) : where(lon, lat);
  }
  // The archive first on land and near a town; the ocean's temperature at sea.
  function thenPick(lon, lat) {
    var land = false;
    try { land = cellAt("AIR", D.enso.now, lon, lat).value !== null; } catch (err) { /* no grid: towns decide */ }
    var p = nearestPlace(lon, lat);
    return land || (p && p.km <= 30) ? "archive" : "sst";
  }
  function thenShow(on) {
    setHidden($("then-bar"), !on);
    var scrubRow = document.querySelector(".deskscrub");
    if (scrubRow) setHidden(scrubRow, on);
    if (!on) { setHidden($("then-chip-a"), true); setHidden($("then-chip-b"), true); }
    else document.querySelectorAll("[data-layer]").forEach(function (b) { b.setAttribute("aria-pressed", "false"); });
  }
  // A longitude brought into -180 to 180, and left as it is when it is
  // already there, so the place entered is the place asked for.
  function lonIn(lon) { return lon >= -180 && lon < 180 ? lon : wrap(lon); }
  // Into a place: the pin, the two sides compared at the divider, and a
  // flight to the source's zoom. Entered already, the place moves and the
  // source, the dates and what Exit goes back to are kept.
  function thenEnter(lon, lat, label, opts) {
    opts = opts || {};
    lon = lonIn(lon); lat = clamp(lat, -85, 85);
    var old = S.then, src = thenSrc(opts.source) || (old && thenSrc(old.source)) || thenSrc(thenPick(lon, lat));
    var back = old ? old.back : {layer: S.layer, second: S.second, compare: S.compare, split: S.split, loop: S.loop};
    if (S.loop) setLoop(false);
    var T = thenFresh({lon: lon, lat: lat, label: label || placeLabel(lon, lat), source: src.id, back: back});
    if (realDay(opts.a) && realDay(opts.b)) { T.preset = ""; T.want = {a: opts.a, b: opts.b}; }
    else if (old) { T.preset = old.preset; T.want = {a: old.want.a, b: old.want.b}; T.names = old.names; }
    else { var p = presetOf("now"); T.want = {a: p.left, b: p.right}; }
    if (!old) S.split = 0.5;
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
    delete LAYERS["then-a"]; delete LAYERS["then-b"];
    var b = T.back;
    S.second = b.second; S.compare = b.compare; S.split = b.split;
    setLayer(b.layer);
    setCompare(b.compare);
    if (b.loop) setLoop(true);
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
    T.read = null; T.readKey = ""; T.apart = "";
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
```

- [ ] **Step 4: Hook the page**

Each edit's first text is found exactly once in its file; replace it with the second.

1. `elnino/stormdesk.py`, `setLayer`: replace

```js
  function setLayer(id) {
```

   with

```js
  function setLayer(id) {
    if (S.then) thenLeave();
```

2. `elnino/stormdesk.py`, `setCompare`: replace

```js
  function setCompare(on) {
```

   with

```js
  function setCompare(on) {
    if (S.then) thenLeave();
```

3. `elnino/stormdesk.py`, `flyTo`: replace

```js
  function flyTo(id) {
```

   with

```js
  function flyTo(id) {
    if (S.then) thenLeave();
```

4. `elnino/stormdesk.py`, `go`: replace

```js
    if (r.kind === "search") { geocode(r.q); return true; }
```

   with

```js
    if (r.kind === "search") { geocode(r.q); return true; }
    if (S.then) thenLeave();
```

5. `elnino/stormdesk.py`, `applyHash`: replace

```js
    if (!h) return false;
    cancelAnimationFrame(anim); anim = 0;
```

   with

```js
    if (!h) return false;
    if (S.then) thenLeave();
    cancelAnimationFrame(anim); anim = 0;
```

6. `elnino/stormdesk.py`, the `#compare-layer` change listener: replace

```js
  $("compare-layer").addEventListener("change", function (e) {
```

   with

```js
  $("compare-layer").addEventListener("change", function (e) {
    if (S.then) thenLeave();
```

7. `elnino/stormdesk.py`, the `#swap` click listener: replace

```js
  $("swap").addEventListener("click", function () {
```

   with

```js
  $("swap").addEventListener("click", function () {
    if (S.then) thenLeave();
```

8. `elnino/worldmap.py`, `setEnso`: replace

```js
  function setEnso(patch) {
```

   with

```js
  function setEnso(patch) {
    if (S.then) thenLeave();
```

9. `elnino/worldmap.py`, `showRegion`: replace

```js
  function showRegion(name) {
```

   with

```js
  function showRegion(name) {
    if (S.then) thenLeave();
```

10. `elnino/stormdesk.py`, `refresh`: replace

```js
      prepare();
      coastDone = 0;
```

   with

```js
      prepare();
      if (S.then) thenApply();
      coastDone = 0;
```

11. `elnino/stormdesk.py`, `showHere`: replace

```js
'<div class="herebtns"><button type="button" class="toolbtn" data-here="show">Show on map</button>' +
```

   with

```js
'<div class="herebtns"><button type="button" class="toolbtn" data-here="show">Show on map</button>' +
              '<button type="button" class="toolbtn" data-here="enter">Enter here</button>' +
```

12. `elnino/stormdesk.py`, the page's click listener: replace

```js
      if (el.getAttribute("data-here") === "clear") clearHere();
```

   with

```js
      if (el.getAttribute("data-here") === "clear") clearHere();
      else if (el.getAttribute("data-here") === "enter") { if (S.here) thenEnter(S.here.lon, S.here.lat, S.here.label); }
```

13. `elnino/stormdesk.py`, `clearHere`: replace

```js
  function clearHere() { S.here = null; S.pin = null; showHere(); requestRender(); }
```

   with

```js
  function clearHere() { S.here = null; if (!S.then) S.pin = null; showHere(); requestRender(); }
```

14. `elnino/stormdesk.py`, `window.stormDesk`: replace

```js
    here: function (lon, lat, open) { if (open) hereAt(lon, lat); return hereFor(lon, lat); },
```

   with

```js
    here: function (lon, lat, open) { if (open) hereAt(lon, lat); return hereFor(lon, lat); },
    enter: function (lon, lat, opts) { return thenEnter(lon, lat, null, opts || {}); },
    leave: function () { return thenLeave(); },
```

15. `elnino/stormdesk.py`, `window.stormDesk`: replace

```js
              day: S.day, dayState: S.dayState};
```

   with

```js
              day: S.day, dayState: S.dayState, then: thenView()};
```


- [ ] **Step 5: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 97 tests, OK.

- [ ] **Step 6: Run the page's own tests the hooks touch**

Run: `python -m unittest tests.test_tracker.TestStormDeskPayload tests.test_tracker.TestStormDeskPage tests.test_tracker.TestDaySearchRuns tests.test_tracker.TestStreetMaps tests.test_tracker.TestStreetMapRuns tests.test_tracker.TestCompositeOnTheMapRuns tests.test_tracker.TestEnsoHere tests.test_tracker.TestEnsoHereRuns tests.test_tracker.TestEnsoTiles tests.test_tracker.TestEnsoTilesRuns tests.test_tracker.TestEnsoNow tests.test_tracker.TestEnsoShapesRuns tests.test_tracker.TestGoogleHere tests.test_tracker.TestTwoPages tests.test_tracker.TestHashRuns tests.test_tracker.TestAddressSearchRuns tests.test_tracker.TestAddressSearch tests.test_tracker.TestMapDocumented tests.test_tracker.TestNoWayBackRuns tests.test_tracker.TestLayerChoiceRuns tests.test_tracker.TestWorldCopiesRuns tests.test_tracker.TestEsriCoverageRuns tests.test_tracker.TestGlobePanel tests.test_tracker.TestImageryGeometry tests.test_tracker.TestRegressions`
Expected: 163 tests, OK (the page's behaviour unchanged when nothing is entered).

- [ ] **Step 7: Mutation check**

Take `      if (S.then) thenApply();` back out of `refresh`; run `python -m unittest tests.test_thennow.TestThenEnterRuns`; expected FAIL in `test_a_refresh_while_entered_draws_the_sides_again`. Put it back; run again; expected OK.

- [ ] **Step 8: Commit**

```bash
git add elnino/thennow.py elnino/stormdesk.py elnino/worldmap.py tests/test_thennow.py
git commit -m "Then and now: entering a place and leaving it" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


---

### Task 9: The figure: pressed and then a tap, or carried onto the map

**Files:**
- Modify: `elnino/thennow.py` (`_JS`, appended)
- Modify: `elnino/stormdesk.py` (`_JS`: `tap`)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: `thenEnter`, `thenLeave`, `thenMove` (Task 8); `setHidden` (Task 7); the page's `map`, `toWorld`, `lonOf`, `latOf`.
- Produces: `S.arming`; `arm(on)`; `overMap(e)`; `carryEnd(e, drop)`; the figure's pointer and click listeners; the document's Esc and Enter keys. For the tests: `SCREEN`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
# Where Manaus is on an 800 by 600 map centred on 0, 0 at zoom 3, and the
# figure and its ghost and ring hidden, as the page's markup has them.
SCREEN = (r"""
          var W = world(), spot = {x: (mx(-60.025) - S.x) * W + S.w / 2, y: (my(-3.1) - S.y) * W + S.h / 2};
          $("then-ghost").hidden = true; $("then-ring").hidden = true; $("then-hint").hidden = true;
          LAND["-60,-3"] = true;
""")


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenFigureRuns(unittest.TestCase):
    """The figure, as Google's: pressed, the map waits for a tap, or Enter
    for the middle of the view; carried onto the map, it enters where it is
    let go. Esc stops waiting, or leaves."""

    def test_pressing_the_figure_waits_for_a_tap_and_pressing_again_stops(self):
        got = _run(self, SCREEN + r"""
          var fig = $("then-enter");
          function state() { return [S.arming, map.classList.contains("arming"), $("then-hint").hidden,
                                     fig.getAttribute("aria-pressed")]; }
          fig.fire("click");
          var armed = state();
          fig.fire("click");
          console.log(JSON.stringify([armed, state(), S.then]));
        """)
        self.assertEqual(got, [[True, True, False, "true"], [False, False, True, "false"], None])

    def test_enter_while_waiting_enters_the_middle_of_the_view_and_esc_stops_waiting(self):
        got = _run(self, SCREEN + r"""
          S.x = mx(-60.025); S.y = my(-3.1);
          $("then-enter").fire("click");
          var esc = press("Escape");
          var stopped = [S.arming, esc.defaultPrevented, S.then];
          $("then-enter").fire("click");
          var enter = press("Enter");
          console.log(JSON.stringify([stopped, enter.defaultPrevented, S.arming, S.then.label, S.then.source]));
        """)
        self.assertEqual(got, [[False, True, None], True, False, "Manaus, Amazonas, Brazil", "archive"])

    def test_esc_leaves_the_place_and_keys_typed_in_a_field_are_its_own(self):
        got = _run(self, r"""
          thenEnter(-60.025, -3.1, "Manaus", {source: "modis", a: "2014-11-15", b: "2015-11-15"});
          var inForm = new El("go", "button");
          inForm.closest = function (sel) { return sel === "#findform" ? this : null; };
          var own = [press("Escape", new El("x", "input")), press("Escape", new El("s", "select")),
                     press("Escape", new El("t", "textarea")), press("Escape", inForm)];
          var stayed = [!!S.then].concat(own.map(function (e) { return e.defaultPrevented; }));
          var out = press("Escape");
          var again = press("Escape");
          console.log(JSON.stringify([stayed, out.defaultPrevented, S.then, again.defaultPrevented]));
        """)
        # Esc with nothing to stop or leave is the page's.
        self.assertEqual(got, [[True, False, False, False, False], True, None, False])

    def test_a_tap_while_waiting_enters_there_and_one_while_entered_moves_the_place(self):
        extra = _js_function(stormdesk.script(), "tap") + r"""
var tapTimer = 0, lastTap = null;
function zoomBy() { note("zoomBy"); }
function flyTo() { note("flyTo"); }
function flyToArea() { note("flyToArea"); }
"""
        got = _run(self, SCREEN + r"""
          $("then-enter").fire("click");
          tap({x: spot.x, y: spot.y, target: map}, 1000);
          var entered = [S.arming, S.then && S.then.label, S.then && S.then.source];
          // Entered, a tap asks nothing of Here: it moves the place.
          S.x = 0.5; S.y = 0.5; S.z = 3;
          tap({x: 400, y: 300, target: map}, 5000); advance(330);
          var moved = [S.then.label, CALLS.filter(function (c) { return c.indexOf("hereAt") === 0; }).length];
          thenLeave();
          tap({x: 400, y: 300, target: map}, 9000); advance(330);
          console.log(JSON.stringify([entered, moved, CALLS.filter(function (c) { return c.indexOf("hereAt") === 0; })]));
        """, extra=extra)
        self.assertEqual(got, [[False, "Manaus, Amazonas, Brazil", "archive"], ["0.00N 0.00E", 0], ["hereAt undefined"]])

    def test_the_figure_carried_onto_the_map_enters_where_it_is_let_go(self):
        got = _run(self, SCREEN + r"""
          map.box = {left: 100, top: 50, width: 800, height: 600};
          var fig = $("then-enter");
          fig.fire("pointerdown", {pointerId: 7, pointerType: "mouse", button: 0, clientX: 20, clientY: 20});
          // Under 8 px it is a press, not yet carried.
          fig.fire("pointermove", {pointerId: 7, clientX: 24, clientY: 25});
          var still = [$("then-ghost").hidden, $("then-ring").hidden];
          fig.fire("pointermove", {pointerId: 7, clientX: 100 + spot.x, clientY: 50 + spot.y});
          var carrying = [$("then-ghost").hidden, $("then-ghost").style.transform, $("then-ring").hidden,
                          $("then-ring").style.transform];
          fig.fire("pointerup", {pointerId: 7, clientX: 100 + spot.x, clientY: 50 + spot.y});
          // The click that follows letting go does not press the figure.
          fig.fire("click");
          console.log(JSON.stringify([still, carrying, [$("then-ghost").hidden, $("then-ring").hidden],
                                      S.then && S.then.label, S.arming]));
        """)
        self.assertEqual(got, [[True, True], [False, "translate(159px,368px)", False, "translate(59px,318px)"],
                               [True, True], "Manaus, Amazonas, Brazil", False])

    def test_the_figure_let_go_off_the_map_or_cancelled_enters_nowhere(self):
        got = _run(self, SCREEN + r"""
          map.box = {left: 100, top: 50, width: 800, height: 600};
          var fig = $("then-enter");
          // A right button is not a carry.
          fig.fire("pointerdown", {pointerId: 1, pointerType: "mouse", button: 2, clientX: 20, clientY: 20});
          fig.fire("pointermove", {pointerId: 1, clientX: 400, clientY: 300});
          var right = $("then-ghost").hidden;
          fig.fire("pointerdown", {pointerId: 3, pointerType: "touch", clientX: 20, clientY: 20});
          fig.fire("pointermove", {pointerId: 3, clientX: 60, clientY: 30});
          var off = [$("then-ghost").hidden, $("then-ring").hidden];
          fig.fire("pointerup", {pointerId: 3, clientX: 60, clientY: 30});
          fig.fire("click");
          off.push(S.then, S.arming, $("then-ghost").hidden);
          fig.fire("pointerdown", {pointerId: 4, pointerType: "touch", clientX: 20, clientY: 20});
          fig.fire("pointermove", {pointerId: 4, clientX: 400, clientY: 300});
          fig.fire("pointercancel", {pointerId: 4, clientX: 400, clientY: 300});
          fig.fire("click");
          console.log(JSON.stringify([right, off, S.then, S.arming, $("then-ghost").hidden, $("then-ring").hidden]));
        """)
        self.assertEqual(got, [True, [False, True, None, False, True], None, False, True, True])
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenFigureRuns -v`
Expected: 6 tests FAIL: nothing listens to the figure yet, and `tap` has no hook. `FAILED (failures=6)`.

- [ ] **Step 3: Add the script**

Append to `_JS` in `elnino/thennow.py`, just before its closing `"""`:

```js
  // ---- the figure: pressed, then a tap; or carried onto the map ---------------------
  // Pressed, the map waits for a tap (or Enter, for the middle of the view);
  // carried, a ring shows where it would land, and letting go there enters.
  S.arming = false;
  var fig = $("then-enter"), ghost = $("then-ghost"), landing = $("then-ring"), carry = null, carried = false;
  function arm(on) {
    S.arming = !!on;
    map.classList.toggle("arming", S.arming);
    setHidden($("then-hint"), !S.arming);
    fig.setAttribute("aria-pressed", S.arming ? "true" : "false");
  }
  // A pointer's place on the map, or null off it.
  function overMap(e) {
    var r = map.getBoundingClientRect(), x = e.clientX - r.left, y = e.clientY - r.top;
    return x >= 0 && y >= 0 && x < r.width && y < r.height ? {x: x, y: y} : null;
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
    thenEnter(lonOf(w.x), latOf(w.y));
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
    arm(!S.arming);
  });
  // Esc stops waiting for a tap, or leaves the place; Enter while waiting
  // enters the middle of the view. Keys typed into a field are its own.
  document.addEventListener("keydown", function (e) {
    var t = e.target, tag = t && t.tagName;
    if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA" || (t && t.closest && t.closest("#findform"))) return;
    if (e.key === "Escape") {
      if (S.arming) { arm(false); e.preventDefault(); }
      else if (S.then) { thenLeave(); e.preventDefault(); }
    } else if (e.key === "Enter" && S.arming) {
      e.preventDefault();
      arm(false);
      thenEnter(lonOf(S.x), latOf(S.y));
    }
  });
```

- [ ] **Step 4: Hook the page**

Each edit's first text is found exactly once in its file; replace it with the second.

1. `elnino/stormdesk.py`, `tap`: replace

```js
  function tap(q, time) {
    clearTimeout(tapTimer);
```

   with

```js
  function tap(q, time) {
    clearTimeout(tapTimer);
    if (S.arming) { var w = toWorld(q.x, q.y); arm(false); thenEnter(lonOf(w.x), latOf(w.y)); return; }
```

2. `elnino/stormdesk.py`, `tap`: replace

```js
      tapTimer = setTimeout(function () { hereAt(lonOf(a.x), latOf(a.y)); }, 330);
```

   with

```js
      tapTimer = setTimeout(function () {
        if (S.then) thenMove(lonOf(a.x), latOf(a.y)); else hereAt(lonOf(a.x), latOf(a.y));
      }, 330);
```


- [ ] **Step 5: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 103 tests, OK.

- [ ] **Step 6: Run the page's own tests the hooks touch**

Run: `python -m unittest tests.test_tracker.TestStormDeskPayload tests.test_tracker.TestStormDeskPage tests.test_tracker.TestDaySearchRuns tests.test_tracker.TestStreetMaps tests.test_tracker.TestStreetMapRuns tests.test_tracker.TestCompositeOnTheMapRuns tests.test_tracker.TestEnsoHere tests.test_tracker.TestEnsoHereRuns tests.test_tracker.TestEnsoTiles tests.test_tracker.TestEnsoTilesRuns tests.test_tracker.TestEnsoNow tests.test_tracker.TestEnsoShapesRuns tests.test_tracker.TestGoogleHere tests.test_tracker.TestTwoPages tests.test_tracker.TestHashRuns tests.test_tracker.TestAddressSearchRuns tests.test_tracker.TestAddressSearch tests.test_tracker.TestMapDocumented tests.test_tracker.TestNoWayBackRuns tests.test_tracker.TestLayerChoiceRuns tests.test_tracker.TestWorldCopiesRuns tests.test_tracker.TestEsriCoverageRuns tests.test_tracker.TestGlobePanel tests.test_tracker.TestImageryGeometry tests.test_tracker.TestRegressions`
Expected: 163 tests, OK (the page's behaviour unchanged when nothing is entered).

- [ ] **Step 7: Mutation check**

In the figure's `pointermove` listener, change `< 8) return;` to `< 1) return;`; run `python -m unittest tests.test_thennow.TestThenFigureRuns`; expected FAIL in `test_the_figure_carried_onto_the_map_enters_where_it_is_let_go`. Put it back; run again; expected OK.

- [ ] **Step 8: Commit**

```bash
git add elnino/thennow.py elnino/stormdesk.py tests/test_thennow.py
git commit -m "Then and now: the figure, pressed or carried onto the map" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


---

### Task 10: The pill, the status line, the address, Copy link and Street View

**Files:**
- Modify: `elnino/thennow.py` (`_JS`, appended)
- Modify: `elnino/stormdesk.py` (`_JS`: `pills`, `downWord`, `retry`, `applyHash`)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: `lookWords`, `captureText` (Task 7); `thenEnter`, `lonIn` (Task 8); `sideDay`, `thenResolve` (Task 6); the page's `mapDown`, `nasaDown`, `hereAt`, `googleFrame`, `S.google`.
- Produces: `thenPill(head, more)`; `thenDown() -> str`; `thenRetry()`; `thenHash() -> "#then=..."`; `parseThen(text) -> {lat, lon, z, source, a, b} | null`; `thenHashApply(text) -> bool`; `thenCopy()`; `thenStreet()`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenWordsRuns(unittest.TestCase):
    """What the map says while a place is entered: the pill, the status line
    and Retry; the address that opens the place again, the link copied, and
    Google's Street View of the place."""

    def test_the_pill_names_the_place_the_source_and_each_side(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=11) + r"""
          var out = [];
          function said() { var head = [], more = []; thenPill(head, more); out.push([head, more]); }
          said();
          S.then.got.a = null; S.then.want.a = "2014-11-15"; S.then.look.a = "no answer"; S.imagery = "offline";
          said();
          """ + _entered("archive", 80, 90, z=16) + r"""
          S.imagery = "ok"; S.inView = {"then-a": {coarser: 16}}; S.inViewB = {"then-b": {coarser: null}};
          said();
          console.log(JSON.stringify(out));
        """)
        self.assertEqual(got[0], [["Manaus: True colour, daily (MODIS Terra), then and now"], [
            "Left: 15 Nov 2014, OND 2014, centred on Nov 2014: RONI +0.6, weak El Niño, the 2014-16 episode.",
            "Right: 15 Nov 2015, OND 2015, centred on Nov 2015: RONI +2.6, very strong El Niño, the 2014-16 episode.",
            "Enlarged 4.0 times past its 250 m pixels."]])
        self.assertEqual(got[1][0], ["Offline: True colour, daily (MODIS Terra) needs the network; the tiles already "
                                     "loaded stay."])
        self.assertEqual(got[1][1][0], "Left: 15 Nov 2014, NASA GIBS did not answer.")
        self.assertEqual(got[2], [["Manaus: Satellite archive (Esri), then and now"], [
            "Left: 26 Jun 2019, after the latest season on record, NDJ 2016 (RONI −0.6, weak La Niña, the 2016 "
            "episode, still going); capture date not given, first shown in the 26 Jun 2019 release.",
            "Right: 31 Oct 2021, after the latest season on record, NDJ 2016 (RONI −0.6, weak La Niña, the 2016 "
            "episode, still going); taken 31 Oct 2021 by Maxar, WV02 at 50 cm, first shown in the 1 Mar 2024 release.",
            "Left: Esri’s archive has nothing finer than zoom 16 for part of this view; that part is its zoom-16 tile, "
            "enlarged."]])

    def test_the_status_says_which_archive_did_not_answer(self):
        got = _run(self, _want("modis", "2014-11-15", "2015-11-15") + r"""
          route("gibs/MODIS_Terra_Corr", 500);
          thenResolve(); await flush();
          var gibs = thenDown();
          route("gibs/MODIS_Terra_Corr", "<Domain>2000-02-24/2026-09-28/P1D</Domain>");
          thenRetry(); await flush();
          var back = [thenDown(), S.then.got.a, S.then.fail.gibs];
          S.then.source = "archive"; S.then.fail.wayback = true;
          var esri = thenDown();
          S.then.fail.wayback = false; MAPS["then-b"] = {ok: 0, failed: 3};
          console.log(JSON.stringify([gibs, back, esri, thenDown()]));
        """)
        self.assertEqual(got, ["Imagery unreachable.", ["", "2014-11-15", False], "Esri’s archive unreachable.",
                               "Esri’s archive unreachable."])

    def test_the_pill_and_the_status_speak_of_the_place_while_entered(self):
        js = stormdesk.script()
        extra = "\n".join(_js_function(js, n) for n in ("pills", "downWord", "retry")) + r"""
var framePill = $("pill"), pillOpen = true, pillHtml = "", COMPASS = [], BYID = {al01: {d: {title: "Storm", view: {}}}};
statusPill.firstChild = {textContent: ""};
function ensoTileMore() { return ["The El Niño tiles."]; }
function nasaWanted() { return false; }
function dayWords() { return "a day"; }
function sourceWords() { return "another source"; }
function utc() { return "now"; }
function base() { return {t: 0, image: false}; }
function centreAt() { return {lon: 0, lat: 0}; }
function askGibsAgain() { note("askGibsAgain"); }
function forgetMaps() { note("forgetMaps"); }
"""
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=11) + MODIS_DAYS + r"""
          S.selected = "al01"; S.inViewB = {x: {name: "x", layer: {name: "Other"}}};
          S.then.fail.gibs = true;
          pills();
          var pill = framePill.innerHTML, status = [statusPill.hidden, statusPill.innerHTML];
          retry(); await flush();
          pills();
          console.log(JSON.stringify([pill, status, S.then.fail.gibs, statusPill.hidden, CALLS.indexOf("askGibsAgain") >= 0]));
        """, extra=extra)
        self.assertIn("<div>Manaus: True colour, daily (MODIS Terra), then and now</div>", got[0])
        self.assertIn("Enlarged 4.0 times past its 250 m pixels.", got[0])
        # Nothing of today's: the storm, the compared layer, the El Nino tiles.
        for today in ("Storm", "Compared, right of the divider", "The El Niño tiles."):
            self.assertNotIn(today, got[0])
        self.assertEqual(got[1], [False, '<span>Imagery unreachable.</span><button type="button" class="toolbtn" '
                                         'id="retry">Retry</button>'])
        self.assertEqual(got[2:], [False, True, True])

    def test_the_address_holds_the_place_the_zoom_the_source_and_both_dates(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=8) + r"""
          var hash = thenHash();
          console.log(JSON.stringify([hash, [hash, "#then=-18.1400,181.5000,20,archive,2019-06-26,2021-10-31",
                                             "#then=-18.1400,538.5000,8,archive,2019-06-26,2021-10-31",
                                             "#then=-3.1,-60.025,8,nope,2014-11-15,2015-11-15",
                                             "#then=95,-60,8,modis,2014-11-15,2015-11-15",
                                             "#then=-3.1,-60.025,8,modis,2014-11-15,2015-02-30",
                                             "#then=-3.1,-60.025,8,modis,2014-11-15", "#at=-3.1,-60.025",
                                             null].map(parseThen)]));
        """)
        self.assertEqual(got[0], "#then=-3.1000,-60.0250,8.00,modis,2014-11-15,2015-11-15")
        self.assertEqual(got[1], [
            {"lat": -3.1, "lon": -60.025, "z": 8, "source": "modis", "a": "2014-11-15", "b": "2015-11-15"},
            # Past 180 degrees east, -178.5, as #at= reads it; past the
            # archive's zoom, its zoom. Past 360 degrees, as for #at=, nothing.
            {"lat": -18.14, "lon": -178.5, "z": 19, "source": "archive", "a": "2019-06-26", "b": "2021-10-31"},
            None, None, None, None, None, None, None])

    def test_an_address_opens_entered_and_a_malformed_one_is_ignored(self):
        js = stormdesk.script()
        extra = "\n".join(_js_function(js, n) for n in ("parseHash", "maxZoom", "applyHash"))
        got = _run(self, MODIS_DAYS + r"""
          var ok = applyHash("#then=-3.1000,-60.0250,10.50,modis,2014-11-15,2015-11-15");
          await flush();
          var entered = [ok, S.then.label, S.then.source, S.then.preset, S.then.got, S.z, FLIGHTS.length,
                         CALLS.indexOf("settle") >= 0];
          var at = applyHash("#at=-18.14,178.44");
          var bad = [applyHash("#then=-3.1,-60.025,8,nope,2014-11-15,2015-11-15"), S.then];
          console.log(JSON.stringify([entered, at, S.then, CALLS.filter(function (c) { return c.indexOf("hereAt") === 0; }),
                                      bad]));
        """, extra=extra)
        # Opened from the address, the place is there at once: no flight.
        self.assertEqual(got, [[True, "Manaus, Amazonas, Brazil", "modis", "", {"a": "2014-11-15", "b": "2015-11-15"},
                                10.5, 0, True], True, None, ["hereAt undefined"], [False, None]])

    def test_copy_link_puts_the_address_on_the_clipboard_and_in_the_bar(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15", z=8) + r"""
          $("then-copy").fire("click");
          var shown = S.then.link;
          await flush();
          thenRender();
          var copied = [S.then.link, COPIED.slice(), $("then-note").textContent.indexOf("Link copied: ") === 0];
          navigator.clipboard.writeText = function () { return Promise.reject(new Error("denied")); };
          thenCopy(); await flush();
          var refused = S.then.link;
          navigator.clipboard = undefined;
          thenCopy(); await flush();
          console.log(JSON.stringify([shown, copied, refused, S.then.link]));
        """)
        url = "file:///C:/elnino/output/map.html#then=-3.1000,-60.0250,8.00,modis,2014-11-15,2015-11-15"
        self.assertEqual(got, ["Copy this link: " + url, ["Link copied: " + url, [url], True],
                               "Copy this link: " + url, "Copy this link: " + url])

    def test_street_view_opens_google_s_view_of_the_place_once(self):
        got = _run(self, _entered("modis", "2014-11-15", "2015-11-15") + r"""
          function asked() { return CALLS.filter(function (c) { return /^(hereAt|googleFrame|scroll)/.test(c); }); }
          $("then-street").fire("click");
          var first = asked();
          S.google = {kind: "street"}; $("google-frame").hidden = false; CALLS = [];
          $("then-street").fire("click");
          console.log(JSON.stringify([first, S.here, asked()]));
        """)
        # Already open on the street, it is not closed by a second press.
        self.assertEqual(got, [["hereAt Manaus", "googleFrame street", "scroll google-frame"],
                               {"lon": -60.025, "lat": -3.1, "label": "Manaus"}, ["hereAt Manaus", "scroll google-frame"]])
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenWordsRuns -v`
Expected: 7 tests: 5 FAIL and 2 ERROR, on `thenPill`, `thenDown`, `thenCopy`, `parseThen` not defined and the engine's pill, status and address as they are today. `FAILED (failures=5, errors=2)`.

- [ ] **Step 3: Add the script**

Append to `_JS` in `elnino/thennow.py`, just before its closing `"""`:

```js
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
  // The status pill's words while entered.
  function thenDown() {
    var T = S.then;
    if (T.fail.wayback || mapDown("then-a") || mapDown("then-b")) return "Esri’s archive unreachable.";
    if (T.fail.gibs || nasaDown(S.inView) || (S.inViewB && nasaDown(S.inViewB))) return "Imagery unreachable.";
    return "";
  }
  // Retry: each side found again.
  function thenRetry() {
    S.then.fail = {gibs: false, wayback: false};
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
  // browser allows it, and shown in the bar either way.
  function thenCopy() {
    var T = S.then;
    if (!T) return;
    var url = location.href.split("#")[0] + thenHash();
    T.link = "Copy this link: " + url;
    try {
      navigator.clipboard.writeText(url).then(function () {
        if (S.then === T) { T.link = "Link copied: " + url; dirty(); }
      }, function () { /* the link stays shown, to copy by hand */ });
    } catch (err) { /* no clipboard: the link stays shown */ }
    dirty();
  }
  // Google's Street View of the place, in the Here panel's frame.
  function thenStreet() {
    var T = S.then;
    if (!T) return;
    hereAt(T.lon, T.lat, T.label);
    var g = S.google, box = $("google-frame");
    if (!(g && g.kind === "street" && box && !box.hidden)) googleFrame("street");
    box = $("google-frame");
    if (box && box.scrollIntoView) box.scrollIntoView({block: "nearest"});
  }
  $("then-copy").addEventListener("click", function () { thenCopy(); });
  $("then-street").addEventListener("click", function () { thenStreet(); });
```

- [ ] **Step 4: Hook the page**

Each edit's first text is found exactly once in its file; replace it with the second.

1. `elnino/stormdesk.py`, `pills`: replace

```js
    var head = [], more = [], layer = LAYERS[S.layer], st = BYID[S.selected];
```

   with

```js
    var head = [], more = [], layer = LAYERS[S.layer], st = BYID[S.selected], then = !!S.then;
```

2. `elnino/stormdesk.py`, `pills`: replace

```js
    if (layer && layer.kind === "map") {
      // A map comes from its own service
```

   with

```js
    if (then) thenPill(head, more);
    else if (layer && layer.kind === "map") {
      // A map comes from its own service
```

3. `elnino/stormdesk.py`, `pills`: replace

```js
    if (S.compare && S.inViewB) {
      var two = []
```

   with

```js
    if (S.compare && S.inViewB && !then) {
      var two = []
```

4. `elnino/stormdesk.py`, `pills`: replace

```js
    if (st) {
      var b = base(st), v = st.d.view || {}, T = b.t
```

   with

```js
    if (st && !then) {
      var b = base(st), v = st.d.view || {}, T = b.t
```

5. `elnino/stormdesk.py`, `pills`: replace

```js
    ensoTileMore().forEach(function (l) { more.push(l); });
```

   with

```js
    if (!then) ensoTileMore().forEach(function (l) { more.push(l); });
```

6. `elnino/stormdesk.py`, `downWord`: replace

```js
    if (S.imagery === "offline") return "";
    if (labelledBase()
```

   with

```js
    if (S.imagery === "offline") return "";
    if (S.then) return thenDown();
    if (labelledBase()
```

7. `elnino/stormdesk.py`, `retry`: replace

```js
  function retry() { statusPill.innerHTML = ""; askGibsAgain(); forgetMaps(); dirty(); }
```

   with

```js
  function retry() { statusPill.innerHTML = ""; askGibsAgain(); forgetMaps(); if (S.then) thenRetry(); dirty(); }
```

8. `elnino/stormdesk.py`, `applyHash`: replace

```js
  function applyHash(text) {
    var h = parseHash(text);
```

   with

```js
  function applyHash(text) {
    if (/^#then=/.test(text || "") && thenHashApply(text)) return true;
    var h = parseHash(text);
```


- [ ] **Step 5: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 110 tests, OK.

- [ ] **Step 6: Run the page's own tests the hooks touch**

Run: `python -m unittest tests.test_tracker.TestStormDeskPayload tests.test_tracker.TestStormDeskPage tests.test_tracker.TestDaySearchRuns tests.test_tracker.TestStreetMaps tests.test_tracker.TestStreetMapRuns tests.test_tracker.TestCompositeOnTheMapRuns tests.test_tracker.TestEnsoHere tests.test_tracker.TestEnsoHereRuns tests.test_tracker.TestEnsoTiles tests.test_tracker.TestEnsoTilesRuns tests.test_tracker.TestEnsoNow tests.test_tracker.TestEnsoShapesRuns tests.test_tracker.TestGoogleHere tests.test_tracker.TestTwoPages tests.test_tracker.TestHashRuns tests.test_tracker.TestAddressSearchRuns tests.test_tracker.TestAddressSearch tests.test_tracker.TestMapDocumented tests.test_tracker.TestNoWayBackRuns tests.test_tracker.TestLayerChoiceRuns tests.test_tracker.TestWorldCopiesRuns tests.test_tracker.TestEsriCoverageRuns tests.test_tracker.TestGlobePanel tests.test_tracker.TestImageryGeometry tests.test_tracker.TestRegressions`
Expected: 163 tests, OK (the page's behaviour unchanged when nothing is entered).

- [ ] **Step 7: Mutation check**

In `parseThen`, delete `    lon = lonIn(lon);`; run `python -m unittest tests.test_thennow.TestThenWordsRuns`; expected FAIL in `test_the_address_holds_the_place_the_zoom_the_source_and_both_dates`. Put it back; run again; expected OK.

- [ ] **Step 8: Commit**

```bash
git add elnino/thennow.py elnino/stormdesk.py tests/test_thennow.py
git commit -m "Then and now: the pill, the status line, the address and Street View" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


---

### Task 11: The map's key: NASA's scale for the source the readout reads

**Files:**
- Modify: `elnino/thennow.py` (`legend()`, new, before `css()`; `css()`; `_JS`: appended; `thenRender`, `thenShow`)
- Modify: `elnino/stormdesk.py` (`_legend()`, the Python that writes the key)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: `worldmap.SST_COLOURS`, `worldmap._sst_label(lo, hi)`, `NDVI_COLOURS`, `payload()["scales"]` (Task 1); the test class `TestThenMarkup` and its `page()` (Task 2); `setHidden`, `thenRender`, the `#then-source` change listener (Task 7); `thenEnter`, `thenLeave`, `thenShow` (Task 8); the page's `.keygroup`, `.ensokey`, `.ensoramp` and `.sstramp` rules (`stormdesk.css()`, `worldmap.css()`).
- Produces: `thennow.legend() -> str`: two hidden keygroups, `#then-sst-key` (NASA's 62 steps) and `#then-ndvi-key` (its 140), in the page's key after `worldmap.legend()`; `thenKey(id)` shows the key for `id` and hides the other (`""` hides both); `thenRender()` calls `thenKey(T.source)` and `thenShow(false)` calls `thenKey("")`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
class TestThenKey(_DeskFixtures, unittest.TestCase):
    """The map's key while a place is entered on the ocean or the vegetation
    index: NASA's own scale, the one the readout reads each pixel back in."""

    page = TestThenMarkup.page

    def test_each_key_is_nasa_s_scale_swatch_for_swatch(self):
        html = thennow.legend()
        for key, head, ends in (
                ("sst", "Then and now: sea surface temperature anomaly, GHRSST MUR25",
                 "below −3.0 °C to +3.0 °C or more, in 0.1 °C steps: NASA's own scale, against MUR's own "
                 "climatology; land, ice and gaps are left clear"),
                ("ndvi", "Then and now: vegetation index, MODIS Terra NDVI, 16-day",
                 "NDVI 0.000, bare ground, to 1.000, dense canopy, in NASA's own 140 steps; water, cloud and "
                 "gaps are left clear")):
            group = re.search(f'<div class="keygroup ensokey" id="then-{key}-key" hidden>(.*?)</div>',
                              html).group(1)
            self.assertIn(f'<span class="keyhead">{head}</span>', group)
            swatches = re.findall(r'<i style="background:rgb\((\d+),(\d+),(\d+)\)"></i>', group)
            self.assertEqual([[int(v) for v in s] for s in swatches], [b["rgb"] for b in THEN["scales"][key]])
            self.assertIn(f"<span>{ends}</span>", group)

    def test_the_map_s_key_holds_both_after_the_composite_s(self):
        html = self.page()
        legend = html[html.index('<div class="desklegend" id="legend"'):html.index("<!--legend-->")]
        self.assertIn('id="then-sst-key"', legend)
        self.assertLess(legend.index('id="enso-key"'), legend.index('id="then-sst-key"'))
        self.assertIn(thennow.legend(), legend)
        # 140 swatches of 2 px, 280 px: inside a 360 px phone less its 16 px gutters.
        self.assertIn(".ndviramp i { width: 2px; }", thennow.css())


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class TestThenKeyRuns(unittest.TestCase):
    """The key follows the source: the ocean's scale, the vegetation index's,
    none for the imagery, and none once the place is left."""

    def test_the_key_follows_the_source_and_leaves_with_it(self):
        got = _run(self, r"""
          function keys() { thenRender(); return [$("then-sst-key").hidden, $("then-ndvi-key").hidden]; }
          thenEnter(-140, 0);
          var shown = [S.then.source, keys()];
          ["ndvi", "archive", "modis", "hls", "sst"].forEach(function (id) {
            $("then-source").fire("change", {target: {value: id}});
            shown.push(keys());
          });
          thenLeave();
          shown.push([$("then-sst-key").hidden, $("then-ndvi-key").hidden]);
          console.log(JSON.stringify(shown));
        """)
        self.assertEqual(got, ["sst", [False, True], [True, False], [True, True], [True, True], [True, True],
                               [False, True], [True, True]])
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenKey tests.test_thennow.TestThenKeyRuns -v`
Expected: 3 tests: 1 ERROR (`AttributeError: module 'elnino.thennow' has no attribute 'legend'`) and 2 FAIL (the page's key has no `then-sst-key`; under node both keys stay shown whatever the source). `FAILED (failures=2, errors=1)`.

- [ ] **Step 3: Add the script**

Append to `_JS` in `elnino/thennow.py`, just before its closing `"""`:

```js
  // ---- the key -------------------------------------------------------------------
  // The key under the map while a place is entered: NASA's own scale for the
  // source the readout reads, the ocean's or the vegetation index's; none
  // for the imagery, which has none.
  function thenKey(id) {
    ["sst", "ndvi"].forEach(function (k) { setHidden($("then-" + k + "-key"), k !== id); });
  }
```

- [ ] **Step 4: Hook the page**

Each edit's first text is found exactly once in its file; replace it with the second.

1. `elnino/thennow.py`, the Python, before `css()`: replace

```python
def css() -> str:
```

   with

```python
def legend() -> str:
    """The key while a place is entered on the ocean or the vegetation index:
    NASA's own scale, the one the readout reads each side's pixel back in.
    The page shows the one for the source shown, and neither for imagery."""
    sst = "".join(f'<i style="background:rgb({r},{g},{b})"></i>' for _, _, (r, g, b) in worldmap.SST_COLOURS)
    ndvi = "".join(f'<i style="background:rgb({r},{g},{b})"></i>' for _, _, (r, g, b) in NDVI_COLOURS)
    return ('<div class="keygroup ensokey" id="then-sst-key" hidden>'
            '<span class="keyhead">Then and now: sea surface temperature anomaly, GHRSST MUR25</span>'
            f'<span class="ensoramp sstramp">{sst}</span>'
            f"<span>{worldmap._sst_label(None, -3.0)} to {worldmap._sst_label(3.0, None)}, in 0.1 °C steps: "
            "NASA's own scale, against MUR's own climatology; land, ice and gaps are left clear</span></div>"
            '<div class="keygroup ensokey" id="then-ndvi-key" hidden>'
            '<span class="keyhead">Then and now: vegetation index, MODIS Terra NDVI, 16-day</span>'
            f'<span class="ensoramp ndviramp">{ndvi}</span>'
            f"<span>NDVI 0.000, bare ground, to 1.000, dense canopy, in NASA's own {len(NDVI_COLOURS)} steps; "
            "water, cloud and gaps are left clear</span></div>")


def css() -> str:
```

2. `elnino/thennow.py`, `css()`: replace

```css
.thenlinks a { color: var(--s1); min-height: 32px; display: inline-flex; align-items: center; }
```

   with

```css
.thenlinks a { color: var(--s1); min-height: 32px; display: inline-flex; align-items: center; }
.ndviramp i { width: 2px; }
```

3. `elnino/thennow.py`, `thenRender`: replace

```js
    if ($("then-gmaps").getAttribute("href") !== href) $("then-gmaps").setAttribute("href", href);
  }
```

   with

```js
    if ($("then-gmaps").getAttribute("href") !== href) $("then-gmaps").setAttribute("href", href);
    thenKey(T.source);
  }
```

4. `elnino/thennow.py`, `thenShow`: replace

```js
    if (!on) { setHidden($("then-chip-a"), true); setHidden($("then-chip-b"), true); }
```

   with

```js
    if (!on) { setHidden($("then-chip-a"), true); setHidden($("then-chip-b"), true); thenKey(""); }
```

5. `elnino/stormdesk.py`, `_legend()`, the Python that writes the key: replace

```python
            + worldmap.legend() +
```

   with

```python
            + worldmap.legend() + thennow.legend() +
```


- [ ] **Step 5: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 113 tests, OK.

- [ ] **Step 6: Run the page's own tests the hooks touch**

Run: `python -m unittest tests.test_tracker.TestStormDeskPayload tests.test_tracker.TestStormDeskPage tests.test_tracker.TestDaySearchRuns tests.test_tracker.TestStreetMaps tests.test_tracker.TestStreetMapRuns tests.test_tracker.TestCompositeOnTheMapRuns tests.test_tracker.TestEnsoHere tests.test_tracker.TestEnsoHereRuns tests.test_tracker.TestEnsoTiles tests.test_tracker.TestEnsoTilesRuns tests.test_tracker.TestEnsoNow tests.test_tracker.TestEnsoShapesRuns tests.test_tracker.TestGoogleHere tests.test_tracker.TestTwoPages tests.test_tracker.TestHashRuns tests.test_tracker.TestAddressSearchRuns tests.test_tracker.TestAddressSearch tests.test_tracker.TestMapDocumented tests.test_tracker.TestNoWayBackRuns tests.test_tracker.TestLayerChoiceRuns tests.test_tracker.TestWorldCopiesRuns tests.test_tracker.TestEsriCoverageRuns tests.test_tracker.TestGlobePanel tests.test_tracker.TestImageryGeometry tests.test_tracker.TestRegressions`
Expected: 163 tests, OK (the page's behaviour unchanged when nothing is entered).

- [ ] **Step 7: Mutation check**

In `thenRender`, delete `    thenKey(T.source);`; run `python -m unittest tests.test_thennow.TestThenKeyRuns`; expected FAIL in `test_the_key_follows_the_source_and_leaves_with_it`. Put it back; run again; expected OK.

- [ ] **Step 8: Commit**

```bash
git add elnino/thennow.py elnino/stormdesk.py tests/test_thennow.py
git commit -m "Then and now: the map's key shows NASA's scale for the source" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```


---

### Task 12: The README

**Files:**
- Modify: `README.md` (section 13, the sources table, the layout, the tests)
- Test: `tests/test_thennow.py`

**Interfaces:**
- Consumes: what Tasks 1-11 built, as the tests pin it.
- Produces: README's "Then and now: entering a place" section; the count of tests, held to the suite by a test.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_thennow.py`, above `if __name__ == "__main__":`:

```python
class TestThenDocumented(unittest.TestCase):
    """The README says what entering a place does and where each side comes
    from, and counts the tests there are."""

    def setUp(self):
        self.readme = (ROOT / "README.md").read_text(encoding="utf-8")

    def test_the_readme_has_then_and_now_in_the_map_s_section(self):
        at = self.readme.index("### Then and now")
        self.assertLess(self.readme.index("## 13. The map"), at)
        self.assertLess(at, self.readme.index("## Composite power index"))
        for words in ("map.html#then=LAT,LON,ZOOM,SOURCE,LEFT,RIGHT", "waybackconfig.json", "tilemap",
                      "MODIS_Terra_CorrectedReflectance_TrueColor", "MODIS_Terra_L3_NDVI_16Day",
                      "GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies", "Esri World Imagery Wayback",
                      "elnino/thennow.py", "they do not attribute"):
            self.assertIn(words, self.readme)

    def test_the_readme_counts_the_tests_there_are(self):
        n = sum(len(re.findall(r"^    def test_", p.read_text(encoding="utf-8"), re.M))
                for p in (ROOT / "tests").glob("test_*.py"))
        self.assertIn(f"tests/                   {n} tests over", self.readme)
        self.assertIn(f"\n{n} tests, no network required.", self.readme)
```

- [ ] **Step 2: Run the tests to watch them fail**

Run: `python -m unittest tests.test_thennow.TestThenDocumented -v`
Expected: 2 tests: 1 ERROR (`ValueError: substring not found`, no "### Then and now") and 1 FAIL (the README says 781 tests). `FAILED (failures=1, errors=1)`.

- [ ] **Step 3: Write the README**

Each edit's first text is found exactly once in its file; replace it with the second.

1. `README.md`, section 13, before "Offline, and what the map is not": replace

```markdown
### Offline, and what the map is not
```

   with

```markdown
### Then and now: entering a place

The **Enter** figure in the toolbar drops into a place as Google's Pegman does:
drag it onto the map and let go, or press it and tap a place (Enter takes the
middle of the view, Esc stops waiting); *Here* offers **Enter here** for the
point it shows. The map flies to the place at its source's own zoom and shows
that source on both sides of the divider at two dates, the earlier on the left,
with a chip either side giving each date and the RONI season centred on its
month. Esc or **Exit** leaves, putting back the layers, the comparison, the
divider and the loop as they were and leaving the view where it is. A tap while
entered moves the place and keeps the dates.

| Source | From | Detail | Each side shows |
|---|---|---|---|
| Satellite archive (Esri World Imagery Wayback) | 20 Feb 2014 | sub-metre where Esri has it, to zoom 19 | the version of the place captured nearest its date |
| Landsat and Sentinel-2 (NASA HLS) | 22 Mar 2013 | 30 m | the nearest day with an image at the pin, within 20 days |
| True colour, daily (MODIS Terra, `MODIS_Terra_CorrectedReflectance_TrueColor`) | 24 Feb 2000 | 250 m | the day nearest its date |
| Vegetation (MODIS NDVI, `MODIS_Terra_L3_NDVI_16Day`) | 5 Mar 2000 | 250 m, 16-day | the composite nearest its date |
| Ocean temperature anomaly (`GHRSST_L4_MUR25_Sea_Surface_Temperature_Anomalies`) | 1 Sep 2002 | 0.25° | the day nearest its date |

A point on land (a cell of the composite's land-only temperature grid, or a
town within 30 km) opens on the archive; one at sea on the ocean's anomaly.

The event menu offers a year ago against the latest and, for every El Niño
episode with its peak since March 2000, a year before the peak against the peak
and the peak against a year after. Each side's date can also be typed (a day
from 1 January 2000 to today; anything else is ignored), stepped with ◀ and ▶
to the previous or next time its archive holds, or set by tapping the RONI
strip, which moves the nearer side to the 15th of that month. A date outside an
archive is brought to its nearest end, and the bar says so; when an event's two
dates land on the same image or capture and an older one exists, the left side
steps back one, and the bar says why. Every date carries the season's words as
the tracker's own index gives them: "OND 2015, centred on Nov 2015: RONI +2.6,
very strong El Niño, the 2014-16 episode".

Esri's archive is read as Esri's own Wayback app reads it. The release list
(`waybackconfig.json`) comes first; then the release tilemap
(`MapServer/tilemap/{release}/{z}/{y}/{x}`) is walked back from the newest
release, each answer naming the release the tile under the pin last changed
in, so only the versions that differ at the pin are visited. Each version is
dated by its capture (day, resolution, sensor and provider at the pin) where
its release's metadata service answers within 20 s, and by its release
otherwise, and each is credited in its release's own words. Past zoom 13, where
Esri holds no tile at a zoom (open water at zoom 17, say), the nearest coarser
tile is drawn and the pill says so.

For vegetation and the ocean, the bar reads each side's value at the pin from
the tile the map draws, its colour looked up bin for bin in NASA's colour map,
and gives both and the change: "At the pin, left: +0.3 to +0.4 °C; right: +2.0
to +2.1 °C; a change of about +1.7 °C." The key under the map shows that colour
map. A clear pixel is no data: land, ice or a gap for the ocean, water, cloud
or a gap for vegetation. For the imagery it names each side's capture or day.

While a place is entered, what belongs to today is not drawn: the storms, the
outlook areas, NASA's reference overlays, the ocean and flood tiles and the El
Niño composite. Esri's roads and place names can go over either side. The
status line says when NASA GIBS or Esri's archive did not answer, and Retry
asks again; offline, the pill says the source needs the network, and what is
drawn stays. **Copy link** gives
`map.html#then=LAT,LON,ZOOM,SOURCE,LEFT,RIGHT`, which opens the page entered
there (a malformed one is ignored, as a malformed `#at=` is), and **Street
View** opens Google's Street View of the place in *Here*'s frame. Scripts have
`stormDesk.enter(lon, lat, {source, a, b, z})`, `stormDesk.leave()` and
`stormDesk.view().then`.

What differs between the two sides is not El Niño's doing alone. Two dates
differ by season, unless they are whole years apart; by cloud, sun angle and
sensor; and by whatever was built, cleared, burned or flooded between them. The
season words say what ENSO was at each date; they do not attribute the
difference to it. That is the composite's job (section 11): what El Niño
seasons did, on average, against neutral ones.

### Offline, and what the map is not
```

2. `README.md`, the sources table, NASA GIBS's row: replace

```markdown
| geostationary and polar imagery and its frame times; the MUR SST anomaly; MODIS's three-day floods |
```

   with

```markdown
| geostationary and polar imagery and its frame times; the MUR SST anomaly; MODIS's three-day floods; MODIS Terra's true colour and NDVI and HLS's 30 m passes, for then and now |
```

3. `README.md`, the sources table, after the geocoder's row: replace

```markdown
| streets and addresses, only when the reader asks | keyless; not stored (no `forStorage`) |
```

   with

```markdown
| streets and addresses, only when the reader asks | keyless; not stored (no `forStorage`) |
| [Esri World Imagery Wayback](https://livingatlas.arcgis.com/wayback/): `waybackconfig.json`, the release tilemaps and metadata services, each release's item | then and now: the archive's releases, the versions of a place and when each was taken, each release's credit | keyless; Esri Master License Agreement, as World Imagery; not for use offline |
```

4. `README.md`, the layout: replace

```markdown
                         what a point is told, Google on request, the geocoder
```

   with

```markdown
                         what a point is told, Google on request, the geocoder
elnino/thennow.py        then and now: its sources, every month's RONI season, the events,
                         the bar, and the script that enters a place and compares two dates
```

5. `README.md`, the layout's count of tests: replace

```markdown
tests/                   781 tests over
```

   with

```markdown
tests/                   896 tests over
```

6. `README.md`, the Tests section's count: replace

```markdown

781 tests, no network required.
```

   with

```markdown

896 tests, no network required.
```

7. `README.md`, the Tests section's list: replace

```markdown
- **the server**: it refuses `..` however it is spelled, lists no directory,
```

   with

```markdown
- **then and now**: the season words for runs of every kind; the events for
  past, current and absent episodes; GIBS's times read, snapped and stepped
  across a year's seam and a gap; Esri's archive walked against a stubbed
  network (a chain of releases, a stop, a failure, a query given up after
  20 s); each side drawn at its own date, never at today's; entering and
  leaving putting the map back; the figure pressed, tapped and carried; the
  readouts' colour lookups and the key that shows their scale; both sides of
  the date line; and the address;
- **the server**: it refuses `..` however it is spelled, lists no directory,
```


- [ ] **Step 4: Run the tests to watch them pass**

Run: `python -m unittest tests.test_thennow -v`
Expected: 115 tests, OK.

- [ ] **Step 5: Run the map's documentation tests**

Run: `python -m unittest tests.test_tracker.TestMapDocumented -v`
Expected: 3 tests, OK.

- [ ] **Step 6: Mutation check**

In `README.md`, change `896 tests over` to `895 tests over`; run `python -m unittest tests.test_thennow.TestThenDocumented`; expected FAIL in `test_the_readme_counts_the_tests_there_are`. Put it back; run again; expected OK.

- [ ] **Step 7: Commit**

```bash
git add README.md tests/test_thennow.py
git commit -m "README: then and now, and the count of tests; 896 tests" -m "Co-Authored-By: Claude Opus 5.5 (1M context) <noreply@anthropic.com>"
```
