# El Niño Tracker

### **[→ Open the live dashboard](https://villaketh.github.io/elnino-tracker/)**

Free, no account, nothing to install, and no tracker on the page.

A diagnostic, forecast and impact system for the current El Niño, built on live
NOAA observations.

Every run downloads 34 feeds, diagnoses the ocean and the atmosphere separately,
maps where the event physically sits in the basin and at depth, projects it
forward with three methods whose weights come from its own cross-validated
hindcast, raises alerts against the previous run, and writes a terminal report,
an HTML dashboard and a JSON snapshot.

The dashboard opens on a globe. Spin it, zoom it, click any point on Earth, and
it tells you what this event is doing to that place now and what it is projected
to be doing at the peak.

Pure Python standard library — no `pip install`, no build step, no CDN, no API
key. Python 3.10 or newer.

```
python track.py                     # fetch live, print report, write dashboard + JSON
python track.py --open              # ...and open the dashboard
python track.py --brief             # alerts and headline state only
python track.py --section forecast  # print one section (repeatable)
python track.py --alerts-only       # exit non-zero if a WARNING or worse is open
python track.py --watch 60          # re-run every 60 minutes until interrupted
python track.py --offline           # re-run against the last download, no network
python track.py --history 20        # the last 20 recorded runs, from the database
python track.py --json-only         # the JSON snapshot on stdout, nothing else
```

Exit codes are meaningful, so this can be driven from a scheduler:

| Code | Meaning |
|---|---|
| 0 | ran; nothing above WATCH is open |
| 1 | ran; at least one WARNING or CRITICAL alert is open |
| 2 | could not run at all (no data and no cache) |
| 3 | ran, but the analysis was degraded by feed or parse failures |

On Windows, double-click **`update.bat`** to refresh and open the dashboard.

---

## What the system actually claims

Nine questions, answered separately, because collapsing them into one number is
how people get surprised.

| Question | Answered by |
|---|---|
| How big is it? | ONI, RONI, ranked against the record and the same season |
| Where is the warmth? | Four Niño regions, EP/CP flavour proxy |
| Where is it, on a map? | Gridded SST, depth section, Hovmöller, 3-D thermocline |
| Where is it, on the planet? | A rotatable globe, dragged and zoomed and clicked |
| Has the atmosphere responded? | 10-indicator Walker composite, coupling test |
| Is there fuel left? | Warm water volume, recharge-oscillator phase |
| Where is it going? | Three-method ensemble with verified error bars |
| How much is that forecast worth? | Leave-one-year-out hindcast over 77 years |
| What does it mean on the ground? | 28 teleconnections, gated on intensity and flavour |
| What does it mean *where I am*? | Click any point; that place scored now and at peak |

---

## 1. Intensity

The **ONI** is the 3-month running mean Niño-3.4 SST anomaly, and is the index
NOAA uses to declare episodes. Tiers are taken from the peak ONI:

| ONI | Classification |
|---|---|
| +0.5 to +0.9 | Weak |
| +1.0 to +1.4 | Moderate |
| +1.5 to +1.9 | Strong |
| ≥ +2.0 | Very Strong |

An El Niño **episode** requires five consecutive overlapping seasons at or above
+0.5 °C. Fewer than five means *conditions are present* but the episode is not
yet in the formal record — the tracker states which of the two applies and how
many seasons are still needed.

The **RONI** (Relative ONI) subtracts the tropical-mean SST anomaly, removing the
background warming trend. It is the fairer yardstick when comparing a present-day
event against 1982-83 or 1997-98, and CPC now frames historic-event thresholds in
RONI terms. Both are reported, and both are ranked — against the whole record and
against the *same calendar season*, because ENSO amplitude has a strong annual
cycle and a +1.8 in JJA is not the same animal as a +1.8 in DJF.

## 2. Scale and flavour

Four Niño regions are reported from the weekly CPC file, with a flavour proxy:

```
flavour index = Niño-1+2 anomaly − Niño-4 anomaly
```

Strongly positive means the warmth is concentrated in the eastern Pacific — a
canonical / EP event, as in 1982-83 and 1997-98. Negative means a central-Pacific
"Modoki" event, which teleconnects differently: this is why the hazard outlook
changes when the flavour changes. It is a simple proxy, not the formal E/C EOF
indices.

## 3. Coupling — is the atmosphere listening?

A warm ocean alone produces nothing. 2014 is the cautionary case: a substantial
subsurface anomaly and a Kelvin wave, and the atmosphere never coupled, so the
event stalled. The tracker therefore reports the atmosphere **separately from SST
rather than blended into it**, so a decoupled warm ocean is visible instead of
averaged away.

Ten indicators are read, each re-signed so that **positive means El-Niño-like**
whatever its native convention, and standardized against its own calendar month:

- Southern Oscillation Index, and the equatorial SOI
- Darwin and Tahiti sea level pressure, separately
- OLR at the date line and over the central Pacific (convection proxy)
- 850 hPa trade winds, western / central / eastern Pacific
- 200 hPa zonal wind, east Pacific (the upper branch of the Walker cell)

These are combined into a weighted composite, reported with the **fraction of
indicators that agree with it** and with each dissenter named. A composite of
+1.5σ built on 55% agreement is a different animal from the same number on 90%
agreement, and the dashboard says which one you are looking at.

Also tracked: **westerly wind bursts** (sustained western-Pacific westerly
anomalies, the trigger for downwelling Kelvin waves), the **MJO** from the CPC
200 hPa velocity potential projections, the **QBO**, and the **tropical Atlantic**
— a warm Atlantic opposes the Pacific Walker response and is one reason ONI and
RONI diverge.

Any indicator whose latest value is more than two months old is marked **stale**
in the report, hatched on the dashboard, and excluded from the coupling verdict.

## 4. Subsurface — the recharge oscillator

The single most useful predictor at 2-3 season lead is not SST, it is the heat
stored below it. **Warm water volume** (WWV: the volume above the 20 °C isotherm,
5°N-5°S, from the PMEL TAO array) is the recharge-oscillator state variable.

The tracker:

- ranks the latest WWV against the whole record and the same calendar month;
- computes its tendency (still recharging, or discharging?);
- measures the WWV → Niño-3.4 **lead time and correlation from the data at run
  time**, rather than asserting "two to three seasons" from the literature;
- locates the event on the (T, h) phase plane and names the quadrant.

The system circles that plane **clockwise**: heat accumulates (cool, recharging)
→ converts to surface warmth (warm, recharged) → the warmth discharges heat
poleward (warm, discharging) → the ocean is left cool and discharged. Position on
the loop predicts what happens next far better than amplitude does — an event
that is already discharging while still warm is near its end, and one that is
still recharging while warm has not yet spent its fuel.

The dashboard draws this as a connected scatter with an age-faded trail, which is
the physical model made directly visible.

## 4b. Space — where the event physically is

An index is a number summarising a map, and two very different maps produce the
same number. +1.5 °C in Niño-3.4 can be a narrow tongue on the equator or a
basin-wide bulge, and they do not mean the same thing for the atmosphere. So the
maps are shipped alongside the indices, in eight views:

| View | What it shows | Source |
|---|---|---|
| **The globe (3-D)** | the whole planet, spun with the mouse; click anywhere and the panel beside it says what this event does *there*, now and at its projected peak | OISST v2.1 + the teleconnection catalogue |
| **SST anomaly map** | the tropical Pacific, with the four Niño boxes drawn on it and the 28 °C warm-pool edge marked | OISST v2.1, daily |
| **Thermocline surface (3-D)** | 20 °C isotherm depth over longitude *and* latitude, rotatable | TAO/TRITON daily array |
| **Depth section** | temperature against depth along the equator, 165E to 95W | TAO/TRITON monthly |
| **Hovmöller** | longitude across, time downward — eastward propagation reads as a right-leaning band | OISST and altimetry |
| **Sea-level anomaly** | upper-ocean heat content, seen from orbit and independent of the moorings | NESDIS altimetry |
| **Global map** | the same day worldwide, which is the reason relative ONI exists | OISST v2.1 |
| **Phase spiral (3-D)** | six years of the recharge oscillator with time as the third axis, so the orbits separate | derived |

Three numbers are read straight off the grids and printed in the terminal report
as well:

- **Area-weighted box means.** Computed from the gridded anomaly with cos(lat)
  weighting. These are *not* a replacement for the CPC index and will not match
  it to the decimal — a different method over a different grid. They are there to
  show what the map says, and a wide divergence is a broken grid, which the tests
  assert against.
- **Warm-pool east edge.** The easternmost equatorial longitude still at 28 °C.
  In a neutral Pacific that sits near the dateline; every degree it travels east
  drags the deep convection with it, and that convection is what every
  teleconnection in the hazard outlook is anchored to.
- **Thermocline tilt.** 20 °C isotherm depth at the western mooring minus the
  eastern one. A neutral Pacific runs near 100 m of tilt; a mature El Niño
  flattens it. The flattening *is* the event, not a symptom of it.

The spatial tier is strictly additive. Nothing in it feeds the classification,
the power index, the forecast or the alerts, so a spatial feed that fails costs a
picture and nothing else — the run continues and says which view is missing.

The three interactive panels — the globe, the thermocline surface and the phase
spiral — are rendered twice: once server-side as real SVG, so the page is
complete with JavaScript disabled, in a print and in a screenshot, and again by a
small inline script that re-projects the same geometry on drag. There is no
library and no network call; the projection is fifteen lines of arithmetic.

### The globe

The one panel that answers a question about *you* rather than about the Pacific.

- **Drag** to spin it. Any point on Earth can be brought to the front; the
  hemisphere behind the limb is culled rather than smeared, which is what an
  orthographic projection is for — it is the planet as seen from very far away,
  so it looks like the thing it is.
- **Ctrl-scroll** (⌘ on a Mac) to zoom to 6×, or use the buttons. A bare wheel
  scrolls the page, because trapping the scroll on a panel two thirds of the way
  down a long document is how a reader gets stuck.
- **Click any point** — or tab to it and use the arrow keys and Enter — and the
  panel beside the globe fills with every catalogued relationship covering that
  coordinate, most specific first, each one scored twice: at today's ONI and at
  the projected peak. Clicking Lima returns the coastal flood signal, the
  anchoveta fishery and highland malaria; clicking central Australia returns
  nothing, and says so, because silence is a finding.
- **Filter by polarity** — wetter, drier, warmer, cooler, storms, fisheries,
  health — to see that class of footprint picked out against the rest.
- Local SST anomaly is read off the same quantised field the globe is drawn
  from, so the number in the panel is exactly the colour under the pin — good to
  half a ramp step, which the tests bound.

Seven preset views (Pacific, Americas, Africa, Asia-Pacific, Atlantic, and each
pole) exist so the reader can get to a hemisphere without learning to drive. The globe ships as 2,922 pre-projected cells, 17 footprint
outlines, 107 coastline polylines and a 7.6 KB field payload; the payload is one
character per cell against an 11-step ramp rather than JSON numbers, which is the
difference between a 7 KB attribute and a 40 KB one on a page that has to stay a
single file.

## 5. Forecast

Three methods, combined:

1. **Analog ensemble.** Past events matched at the *same stage of development* —
   aligned on onset, not on calendar position — and weighted by `1 / (rmse + 0.1)`.
   Analogs that are too dissimilar are dropped rather than diluted in, and the
   report says how many were dropped and why. If the current event is running
   warmer than every analog at the same stage, the members are offset by that gap;
   without the shift the ensemble would systematically understate the projection,
   and the report states the shift it applied.

2. **Nonlinear recharge oscillator.** The two-variable system, fitted by least
   squares per calendar month from the full ONI and WWV records:

   ```
   dT/dt = a·T + b·h − e·T³
   dh/dt = c·T + d·h
   ```

   Fitting the coefficients *per calendar month* is what lets the model reproduce
   ENSO's seasonal phase locking — growth through boreal autumn, decay through
   spring — without that behaviour being hard-coded. The cubic term matters at
   this amplitude: the thermocline feedback saturates as the east Pacific warms
   and the thermocline flattens, and a linear model initialised from a record
   warm water volume will forecast an SST anomaly that has never been observed.
   An integration that diverges is dropped, not reported.

3. **Damped persistence**, with the damping estimated per target season from the
   observed autocorrelation.

Method weights are **not chosen by hand** — they are the inverse-error weights
from the tracker's own cross-validated hindcast (currently analog 0.45,
recharge 0.29, persistence 0.26). The 10th-90th percentile band comes from the
verified RMSE at each lead, so the fan is as wide as the record says it should
be, not as wide as looks reassuring. Peak probabilities are computed by
integrating that distribution across the +1.0 / +1.5 / +2.0 / +2.5 °C thresholds.

## 6. Verification — how much is the forecast worth?

Every forecast method is scored by **leave-one-year-out cross-validation** over
the whole ONI record (77 years). The verification year is held out of the model
fit, so nothing reported here is in-sample. It reports:

- RMSE, anomaly correlation, bias and sample count at each lead;
- the same, broken down **by method**, which is where the weights come from;
- the **useful horizon**: the last lead whose anomaly correlation still reaches
  0.5, the usual bar for a useful ENSO forecast;
- correlation at 6-month lead **by target season**.

That last one measures the **spring predictability barrier** from the data rather
than asserting it from the literature. Forecasts that must cross boreal spring
currently lose 0.49 of correlation — the run reports MJJ/JJA/JAS/ASO as the
barrier seasons, which is the honest reason a forecast made in February is worth
less than one made in September.

## 7. Alerts

Rules are evaluated on every run against thresholds **and against the previous
run held in the local SQLite database**, so an alert fires once when a condition
appears, is marked `NEW` on that run only, and clears itself when the condition
lifts. Levels are CRITICAL / WARNING / WATCH / INFO. Each carries an icon and a
written level, never colour alone.

`python track.py --alerts-only` exits 1 if anything at WARNING or above is open,
which is enough to drive a cron job or a notifier.

## 8. Hazard outlook

28 documented teleconnections, each gated on a minimum intensity and, where it
matters, on the EP/CP flavour, with a stated confidence and a named exposure.
Likelihood is scaled by how far the *projected peak* clears each link's own
threshold.

This is the part that is easiest to misread, so the panel states its own limits
up front: these are **shifted odds from historical composites, not a forecast**.
ENSO changes the probability distribution of a season; it does not determine the
outcome, and vulnerability on the ground matters more than a rainfall percentile.
The links are keyed to the projected peak, not today's value, so if the event
underperforms the forecast the lower-margin entries drop out first.

**This tool is not a substitute for your national meteorological service.**

---

## Composite power index

**A derived diagnostic of this tracker, not a NOAA product.** It exists to answer
"how big is this thing overall" in one number, and its inputs are published so it
can be audited or ignored:

```
power = 0.40 × amplitude + 0.25 × coupling + 0.20 × basin_scale + 0.15 × momentum
```

- **amplitude** — mean of ONI and RONI, scaled so +2.5 °C reads as 100. That
  anchor is CPC's own bar for an event exceeding anything since 1950.
- **coupling** — mean of the SOI and MEI components, each scaled so a magnitude
  of 2.0 reads as 100.
- **basin_scale** — mean anomaly across the four Niño regions, scaled so a
  basin-wide +2.0 °C reads as 100. *Saturates at 100; above a basin-wide +2.0 °C
  it stops discriminating.*
- **momentum** — rate of change, where ±0.5 °C per season spans the full range.

Bands: Minimal <25, Low 25-40, Moderate 40-55, High 55-70, Very High 70-85,
Extreme ≥85.

---

## Data sources

All 34 feeds are fetched live on every run, in parallel, and archived under
`data/raw/archive/` with a daily snapshot, so past readings stay auditable.

### Index feeds (26)

| Feed | What it is for |
|---|---|
| [`oni.ascii.txt`](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt) | the episode index |
| [`RONI.ascii.txt`](https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt) | trend-adjusted intensity |
| [`wksst9120.for`](https://www.cpc.ncep.noaa.gov/data/indices/wksst9120.for) | weekly Niño regions |
| [`sstoi.indices`](https://www.cpc.ncep.noaa.gov/data/indices/sstoi.indices) | monthly Niño regions |
| [`rel_wksst9120.txt`](https://www.cpc.ncep.noaa.gov/data/indices/rel_wksst9120.txt) | weekly relative SST |
| [`rel_mthsst9120.txt`](https://www.cpc.ncep.noaa.gov/data/indices/rel_mthsst9120.txt) | monthly relative SST |
| [`detrend.nino34.ascii.txt`](https://www.cpc.ncep.noaa.gov/data/indices/detrend.nino34.ascii.txt) | detrended Niño-3.4 |
| [`Rnino34.ascii.txt`](https://www.cpc.ncep.noaa.gov/data/indices/Rnino34.ascii.txt) | relative Niño-3.4 |
| [`wwv.dat`](https://www.pmel.noaa.gov/tao/wwv/data/wwv.dat) | warm water volume (PMEL/TAO) |
| [`wwv_west.dat`](https://www.pmel.noaa.gov/tao/wwv/data/wwv_west.dat) | western WWV; has the heat moved east? |
| [`soi`](https://www.cpc.ncep.noaa.gov/data/indices/soi) | Southern Oscillation Index |
| [`reqsoi.for`](https://www.cpc.ncep.noaa.gov/data/indices/reqsoi.for) | equatorial SOI |
| [`darwin`](https://www.cpc.ncep.noaa.gov/data/indices/darwin) / [`tahiti`](https://www.cpc.ncep.noaa.gov/data/indices/tahiti) | the two SLP stations, separately |
| [`olr`](https://www.cpc.ncep.noaa.gov/data/indices/olr) | convection at the date line |
| [`cpolr.mth.91-20.ascii`](https://www.cpc.ncep.noaa.gov/data/indices/cpolr.mth.91-20.ascii) | central Pacific OLR |
| [`wpac850`](https://www.cpc.ncep.noaa.gov/data/indices/wpac850) / [`cpac850`](https://www.cpc.ncep.noaa.gov/data/indices/cpac850) / [`epac850`](https://www.cpc.ncep.noaa.gov/data/indices/epac850) | 850 hPa trades |
| [`zwnd200`](https://www.cpc.ncep.noaa.gov/data/indices/zwnd200) | 200 hPa zonal wind |
| [`proj_norm_order.ascii`](https://www.cpc.ncep.noaa.gov/products/precip/CWlink/daily_mjo_index/proj_norm_order.ascii) | MJO velocity potential |
| [`qbo.u30.index`](https://www.cpc.ncep.noaa.gov/data/indices/qbo.u30.index) / [`qbo.u50.index`](https://www.cpc.ncep.noaa.gov/data/indices/qbo.u50.index) | QBO |
| [`sstoi.atl.indices`](https://www.cpc.ncep.noaa.gov/data/indices/sstoi.atl.indices) | tropical Atlantic |
| [`meiv2.data`](https://psl.noaa.gov/enso/mei/data/meiv2.data) | MEI.v2 |
| [ENSO Diagnostic Discussion](https://www.cpc.ncep.noaa.gov/products/analysis_monitoring/enso_advisory/ensodisc.shtml) | the operational authority |

### Gridded and mooring feeds (8)

These are ERDDAP queries rather than static files: the subset — variable, time
slice, latitude band, longitude range and stride — is encoded in the URL, so the
server does the decimation and a map arrives as a few hundred kilobytes of CSV
instead of a NetCDF archive. Every one of them is optional.

| Feed | What it is for |
|---|---|
| [`ncdcOisst21Agg`](https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg.html) — Pacific | the anomaly field the Niño indices are averaged out of |
| [`ncdcOisst21Agg`](https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg.html) — global | basin-wide context |
| [`ncdcOisst21Agg`](https://coastwatch.pfeg.noaa.gov/erddap/griddap/ncdcOisst21Agg.html) — equatorial strip | the SST Hovmöller, weekly samples |
| [`pmelTaoMonT`](https://coastwatch.pfeg.noaa.gov/erddap/tabledap/pmelTaoMonT.html) | the equatorial depth section, full record so it can be an anomaly |
| [`pmelTaoMonIso`](https://coastwatch.pfeg.noaa.gov/erddap/tabledap/pmelTaoMonIso.html) | 20 °C isotherm depth; Kelvin wave propagation |
| [`pmelTaoDyIso`](https://www.pmel.noaa.gov/erddap/tabledap/pmelTaoDyIso.html) | the off-equatorial rows, for the 3-D thermocline surface |
| [`nesdisSSH1day_Lon0360`](https://coastwatch.pfeg.noaa.gov/erddap/griddap/nesdisSSH1day_Lon0360.html) — map | sea-level anomaly; heat content from orbit |
| [`nesdisSSH1day_Lon0360`](https://coastwatch.pfeg.noaa.gov/erddap/griddap/nesdisSSH1day_Lon0360.html) — equator | Kelvin and Rossby waves, independent of the moorings |

Two traps in this group. The altimetry product is experimental and is routinely
weeks to months behind the SST fields, so each spatial view carries the age of
its own data rather than the run date, and anything over 45 days behind is
labelled stale in both the dashboard and the report. And the mooring array has
moved over its lifetime: 143E, 156E and 152W reported for years and are gone.
Their columns are not gaps, they are longitudes that no longer exist, so a
longitude present in under half the window is dropped rather than drawn as an
empty stripe.

Note the weekly file: CPC's older `wksst8110.for` (1981-2010 base period) stopped
updating in early 2021 and is a trap. This tracker uses `wksst9120.for`, on the
current 1991-2020 base period.

**Update rhythm.** The weekly SST file refreshes Monday; ONI, RONI and the
monthly indices update early each month; WWV updates monthly; the MJO index is
daily; the Diagnostic Discussion is issued on the second Thursday. Running more
often than daily gains nothing, which is why `--watch` refuses intervals under
15 minutes.

If a feed is unreachable the tracker falls back to the last cached copy and says
so, in the report, in the dashboard's provenance panel, and in the exit code
(3 = degraded). It only fails hard if ONI or the weekly SST file is unavailable
with no cache at all.

---

## Persistence

Every run is written to `data/elnino.db` (SQLite, stdlib):

- **snapshots** — the headline numbers of each run, so `--history` can show drift;
- **series** — what each index said on each run, so an upstream **revision** to a
  past value is visible as a revision rather than silently replacing history;
- **alerts** — open alerts with their first-seen time, which is what makes
  `NEW` and `cleared` meaningful;
- **fetches** — per-feed success, so feed reliability is measurable.

---

## Layout

```
track.py                 CLI entry point, exit codes, watch loop
elnino/sources.py        34-feed registry, parallel fetch, retry, cache + archive
elnino/parsers.py        one parser per NOAA format, each with its quirks documented
elnino/classify.py       episodes, ranking, scale, flavour, analogs, power index
elnino/subsurface.py     WWV ranking, tendency, measured lead, phase-space position
elnino/atmosphere.py     10 indicators, Walker composite, bursts, MJO, coupling
elnino/forecast.py       analog ensemble, nonlinear recharge oscillator, persistence
elnino/verification.py   leave-one-year-out hindcast, spring barrier, method weights
elnino/impacts.py        28 teleconnections, gated on intensity and flavour
elnino/geo.py            where each of those 28 lands, as lon/lat boxes
elnino/alerts.py         threshold and change rules, reconciled against the last run
elnino/history.py        13 catalogued historical events
elnino/storage.py        SQLite: snapshots, series revisions, alerts, feed health
elnino/pipeline.py       one run: fetch -> parse -> diagnose -> forecast -> alert
elnino/grids.py          ERDDAP CSV -> gridded fields, sections, profiles, meshes
elnino/coastline.py      vendored coastline, re-wrapped to any longitude frame
elnino/report.py         78-column ASCII terminal report, section-addressable
elnino/svg.py            validated palette and plotting primitives
elnino/panels.py         the advanced chart panels
elnino/fields.py         maps, Hovmöller diagrams and depth sections
elnino/space3d.py        orthographic 3-D: thermocline surface and phase spiral
elnino/globe.py          the interactive globe and the per-location dossier
elnino/dashboard.py      self-contained HTML + inline SVG, and the JSON payload
tests/                   167 tests over parsers, numerics, grids, renderers, a full run
data/raw/                cached downloads + dated archive
data/elnino.db           run history, revisions, alert state
output/                  dashboard.html, latest.json
docs/                    the published build, served at the link above
```

`docs/` is a build committed for publishing, not a second copy of the code:
`docs/index.html` is a `dashboard.html` from a dated run and `docs/latest.json`
is that same run as data. It is a snapshot, stamped at the top of the page, and
it does not refresh itself — re-run `track.py` and copy the two files over to
update it.

`output/latest.json` (schema 4) is the machine-readable snapshot: classification,
every diagnostic behind it, the spatial block (each field's stamp, age and
coverage; the map-derived box means; the warm-pool edge; the isotherm profile),
the forecast with its verified error bars, open alerts, active impacts, and the
health of every feed. Schema 4 adds `footprints`: the same 28 teleconnections
keyed by coordinate, so a consumer can answer "what does this event do at my
location" without the dashboard. A value that could not be
computed is `null` rather than absent, so a consumer never has to distinguish
"missing" from "not applicable".

---

## Scheduling a daily refresh

Not set up automatically. To have Windows refresh it every morning at 07:30:

```powershell
schtasks /create /tn "El Nino Tracker" /tr "\"%LOCALAPPDATA%\Programs\Python\Python310\python.exe\" \"%USERPROFILE%\Desktop\elnino-tracker\track.py\" --quiet" /sc daily /st 07:30
```

Adjust the Python path to match `where python`.

---

## Tests

```
python -m unittest discover -s tests -v
```

167 tests, no network required. They cover:

- **every parser**, against checked-in fixtures of each NOAA format, including
  the awkward cases: negative anomalies glued to the preceding column
  (`22.2-1.3`), `-999.9` and `+999.9` fill, PMEL's Fortran floats with no leading
  zero (`-.4883405E+14`), the MJO file's `*****` fill, stacked multi-section
  grids, files with no header at all, and the two *different* column orders in
  the weekly and monthly relative-SST files;
- **the numerics**: the recharge fit recovers a planted oscillation, a diverged
  integration is dropped, holding a year out really removes it, per-calendar-month
  standardization removes an annual cycle, and the measured WWV lead recovers a
  planted lead;
- **that verification scores the model production uses** — not a copy of it that
  could drift;
- **the level tables**, because a mismatch between a lowercase level constant and
  an uppercase lookup key does not raise, it just renders a critical alert in the
  colour of an informational one;
- **the grid layer**: ERDDAP's units row is dropped, `NaN` becomes `None` rather
  than a number, axes are rebuilt from the distinct values because the response
  is not guaranteed sorted, box means are cosine-weighted, neither the depth
  interpolation nor the longitude interpolation extrapolates past the outermost
  mooring, a decommissioned longitude is dropped from the Hovmöller, and the
  thermocline tilt averages both ends, skips a mooring that never crossed 20 °C
  and declines rather than averaging one end with itself;
- **the renderers**: run-length encoding really collapses a 1,200-cell field to
  20 rectangles and breaks a run on both a colour change and a gap, cells are
  clipped to the frame, two plots on one page get two clip ids, a diverging ramp
  is symmetric about zero, and the colour-bar precision follows the span — so
  sea-level height does not print "-0.1, -0.1, +0.0";
- **the projection**: it is orthographic, with no perspective divide, so two
  equal anomalies measure the same wherever they sit; the fit keeps the whole
  cloud inside the frame at every tested angle while still filling it; and the
  inline script carries the same fit and the same painter ordering as the server
  renderer, because a mismatch makes the scene jump on the first drag;
- **storage**: snapshot round-trips, and an alert keeping its first-seen time
  across runs and clearing when it stops firing;
- **the geography**: every teleconnection has a footprint and every footprint a
  teleconnection, longitudes wrap into a single half-open range, a region
  straddling the antimeridian is found from both sides, the most specific claim
  is listed first, and a place with no catalogued relationship returns nothing
  rather than something vague;
- **the globe**: four thousand points survive the trip through the inverse
  projection, the far side is culled, a click that misses the disc is not a
  location, the quantised field is exactly one character per cell and reads back
  within half a step, the catalogue is scored at today as well as at the peak
  using the *same* gating rules the report uses, and the embedded payload
  survives being an HTML attribute — one catalogue entry contains an apostrophe,
  and unescaped it silently turns the whole panel inert;
- **a full offline run** end to end, then every report section, the 78-column and
  ASCII-only guarantees, dashboard self-containment, a table view for every
  chart, all eight spatial panels reaching the page, the map-derived Niño-3.4
  mean agreeing with the published index to within 1 °C, the terminal report
  and the dashboard quoting the *same* thermocline tilt, and a JSON payload that
  round-trips.

If NOAA changes a format, these fail before a bad number reaches the dashboard.

---

## Design notes

Charts follow a validated palette: categorical hues assigned in fixed order for
identity, a blue/red diverging pair for polarity, one hue light-to-dark for
magnitude, and a reserved status palette that is never reused as a series colour.
Adjacent-pair colourblind separation was checked by running a validator, not by
eye; light mode returns a contrast warning on three categorical slots, which is
why every chart carries direct labels and a table view, so no value is ever
reachable by colour alone. Light and dark themes are separately stepped against
their own surfaces.

The field ramps are the same discipline applied to gridded data, which is where
operational SST charts usually give up and reach for a rainbow. There is no
rainbow here. A rainbow puts its sharpest perceptual edges at arbitrary values —
the green-to-yellow step reads as a boundary whether or not anything happens
there — and it is close to unreadable for a red-green colourblind reader.
Anomalies get a diverging blue/red ramp with a neutral midpoint, so the *sign* is
the first thing the eye resolves; absolute temperature and isotherm depth get a
single hue, monotone in lightness. Every field carries a labelled discrete colour
bar and a decimated numeric table, so no cell is reachable by colour alone.

Seven decisions worth stating because they look like omissions:

- **No dual-axis charts anywhere.** WWV against Niño-3.4 is drawn as small
  multiples on one shared time axis. On a dual axis the choice of the two scales
  can manufacture any apparent lead you like, and a lead is exactly what this
  chart is used to judge.
- **Nothing is standardized against a window that slides with the view.** The
  phase-space z-scores are computed over the full trajectory, so the axes do not
  rescale as the window moves and two runs remain comparable.
- **The 3-D views re-fit on every frame instead of once.** A rotation-invariant
  fit has to be sized for the worst angle — looking straight down — and every
  other angle then sits in a box two thirds empty. Re-fitting per view means the
  surface grows and shrinks slightly as it is dragged; that is the cost, and it
  buys a picture that is readable at every angle rather than at one. The depth
  axis is labelled at every angle, so the scale is never inferred from the size.
- **Footprints are boxes, not polygons.** A teleconnection is a shift in a
  seasonal probability distribution over a broad region; drawing it as a
  coastline-accurate polygon would claim a spatial precision the underlying
  composites do not have, and would invite reading a sharp edge where there is a
  gradient. A box says "this signal is about this area" and lets the panel say
  the rest.
- **The globe's footprints carry no colour of their own.** There are seven
  polarities — wetter, drier, warmer, cooler, storms, fisheries, health — and a
  validated categorical theme is five hues assigned in fixed order. Inventing two
  more would have broken the thing that makes the rest of the page readable. So
  every footprint is drawn in the same recessive neutral outline, one polarity at
  a time is picked out on demand, and the polarity itself travels as a word and a
  shape in the panel, where it can be read in greyscale, in print, and by a
  reader who sees no colour at all.
- **The globe's dossier is scored on the server, not in the browser.** The
  likelihood gating depends on ONI thresholds and on EP/CP flavour, and a second
  copy of those rules in JavaScript would drift from the copy the terminal report
  uses. The inline script re-projects geometry and nothing else; every number it
  displays was computed by `impacts.evaluate`.
- **Map cells are run-length encoded, not drawn one per cell.** A one-degree
  Pacific map is twelve thousand cells; one rectangle each would add about a
  megabyte to a page whose whole point is being a single self-contained file.
  Horizontally adjacent cells in the same colour class merge into one run, which
  changes nothing about what is drawn because they were already the same colour.

---

## Caveat

This system describes what the observing network reports, projects it forward
with methods whose skill it measures and publishes, and translates that into
shifted odds from historical composites. It is not an operational forecast, and
it is not a dynamical model.

For operational forecasts and probabilistic outlooks, the CPC/IRI ENSO Diagnostic
Discussion is the authority — it is fetched, quoted and linked on every run. For
decisions with lives attached, your national meteorological service is the
authority, and this tool is at best an early flag to go and read them.
