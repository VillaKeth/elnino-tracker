# El Niño Tracker

### **[→ Open the live dashboard](https://villaketh.github.io/elnino-tracker/)**

[Storm Desk](https://villaketh.github.io/elnino-tracker/storms.html) ·
[El Niño Map](https://villaketh.github.io/elnino-tracker/map.html) ·
[Atlas](https://villaketh.github.io/elnino-tracker/atlas.html) ·
[latest.json](https://villaketh.github.io/elnino-tracker/latest.json) ·
[storms.json](https://villaketh.github.io/elnino-tracker/storms.json)

Free, no account, nothing to install. The site refreshes itself every hour:
GitHub runs the tracker and publishes the run, and a page left open takes each
new run on its own. The dashboard, the storm desk and the map say when their
run was. Every page opens on one menu of the four, Dashboard, El Niño Map,
Storm Desk and Atlas, so each is a click from any other; on the dashboard it
stays at the top as you scroll. The mark beside the site's name, which is also
every page's icon, is El Niño's warm tongue reaching west along the equatorial
Pacific.

A diagnostic, forecast and impact system for the current El Niño, built on live
NOAA observations.

Every run downloads 43 feeds, diagnoses the ocean and the atmosphere separately,
maps where the event physically sits in the basin and at depth, tracks every
tropical cyclone NHC, CPHC or JTWC is warning on, worldwide, projects the event
forward with three methods whose weights come from its own cross-validated
hindcast, raises alerts against the previous run, and writes a terminal report, an
HTML dashboard, a storm desk, a world map and JSON snapshots.

The dashboard opens on a globe. Spin it, zoom it, click any point on Earth, and
it tells you what this event is doing to that place now and what it is projected
to be doing at the peak. Live storms are drawn on it as you spin.

Beside it, `output/atlas.html` is a flat world you can drag down to a street's
worth of detail. Click any cell and it answers with what forty years of El Niño
events actually did there: the rainfall and temperature difference against a
neutral year, every season, with the statistic that says whether the difference
is real.

And `output/storms.html` is the storm desk: every live storm on geostationary
imagery about 45 minutes old, under the cone, the wind radii, the watches and
warnings and the formation outlook the warning centres have issued. Find a town
or tap anywhere, and it says what each storm means there, hour by hour; close in
on 30 m imagery of the place. `--serve --lan` puts it on a tablet.

And `output/map.html` is the same page opened on El Niño: the whole planet on a
street map, down to a single street, under the rainfall or temperature composite
for the season now, with today's sea surface temperature anomaly, the last three
days' floods, the Niño regions with this week's anomalies and, a tick away, the
impact regions this event puts in play. Tap any point, or find an address, for what the El Niño
seasons since 1979 did there, and Google's own map, satellite view and Street
View of it on request.

Pure Python standard library — no `pip install`, no build step, no CDN, no API
key. Python 3.10 or newer.

```
python track.py                     # fetch live, print report, write dashboard + atlas + JSON
python track.py --open              # ...and open the dashboard
python track.py --brief             # alerts and headline state only
python track.py --section forecast  # print one section (repeatable)
python track.py --alerts-only       # exit non-zero if a WARNING or worse is open
python track.py --watch 60          # re-run every 60 minutes until interrupted
python track.py --offline           # re-run against the last download, no network
python track.py --history 20        # the last 20 recorded runs, from the database
python track.py --json-only         # the JSON snapshot on stdout, nothing else
python track.py --serve             # ...then serve the storm desk and the map on http://127.0.0.1:8765/
python track.py --serve --lan       # ...to a tablet on this network
```

Exit codes are meaningful, so this can be driven from a scheduler:

| Code | Meaning |
|---|---|
| 0 | ran; nothing above WATCH is open |
| 1 | ran; at least one WARNING or CRITICAL alert is open |
| 2 | could not run at all (no data and no cache) |
| 3 | ran, but the analysis was degraded by feed or parse failures — a missing RONI or ONI among them |

On Windows, double-click **`update.bat`** to refresh and open the dashboard, or
**`publish.bat`** to refresh and put the run up as the site (see *Publishing the
site*); `./publish.sh` does the same on Linux or macOS.

---

## What the system actually claims

Fourteen questions, answered separately, because collapsing them into one
number is how people get surprised.

| Question | Answered by |
|---|---|
| How big is it? | RONI, the official index, with the legacy ONI beside it; ranked against the record and the same season |
| Where is the warmth? | Four Niño regions, EP/CP flavour proxy |
| Where is it, on a map? | Gridded SST, depth section, Hovmöller, 3-D thermocline |
| Where is it, on the planet? | A rotatable globe, dragged and zoomed and clicked |
| Has the atmosphere responded? | 10-indicator Walker composite, coupling test |
| Is there fuel left? | Warm water volume, recharge-oscillator phase |
| Where is it going? | Three-method ensemble with verified error bars |
| How much is that forecast worth? | Cross-validated hindcast of all three methods over 77 years |
| What does it mean on the ground? | 28 teleconnections, gated on intensity and flavour |
| What does it mean *where I am*? | Click any point; that place scored now and at peak |
| What has it *actually done* here before? | The atlas: measured composite for that cell, with Welch's t |
| What does that look like, street by street? | The map: the composites, today's ocean and floods, and the impact regions, over street maps and satellite |
| What is spinning right now? | Every live cyclone, ATCF best track + official forecast |
| Is the ENSO storm signal verifying? | Season ACE against date-matched climatology, scored in public |

---

## 1. Intensity

Since February 2026 the official index is the **RONI**, the Relative ONI (NWS
PIS 26-05): the 3-month running Niño-3.4 anomaly minus the tropical-mean anomaly,
rescaled. Taking out the tropical mean removes the background warming that a
fixed-base index reads as El Niño, so a present-day event is measured on the same
footing as 1982-83 or 1997-98. Every tier, episode, ranking, alert, forecast and
hazard gate in the tracker runs on it.

The **ONI** is kept beside it as the legacy index. CPC classified on it until
February 2026, and the gap between the two is a diagnostic in its own right — in
a warming ocean the ONI reads warm of the RONI, and an alert fires when the gap
grows. If either index fails to arrive the other carries the run, and the run is
reported as degraded; only losing both stops it.

Tiers follow the value CPC prints: one decimal, halves rounded away from zero, so
+1.46 and +1.45 both print +1.5 and both are Strong.

| Index, as printed | Classification |
|---|---|
| +0.5 to +0.9 | Weak |
| +1.0 to +1.4 | Moderate |
| +1.5 to +1.9 | Strong |
| ≥ +2.0 | Very Strong |

An El Niño **episode** requires five consecutive overlapping seasons at or above
+0.5 °C. Fewer than five means *conditions are present* but the episode is not
yet in the formal record — the tracker states which of the two applies and how
many seasons are still needed.

Both indices are ranked — against the whole record and against the *same
calendar season*, because ENSO amplitude has a strong annual cycle and a +1.8 in
JJA is not the same animal as a +1.8 in DJF.

## 2. Scale and flavour

Four Niño regions are reported from the weekly CPC files — on the relative
anomalies, tropical mean removed, wherever CPC publishes them, so the regions sit
on the same footing as the official index — with a flavour proxy:

```
flavour index = Niño-1+2 anomaly − Niño-4 anomaly
```

At **+1.0 or above** the warmth is concentrated in the eastern Pacific — a
canonical / EP event, as in 1982-83 and 1997-98. At **−0.5 or below** it is a
central-Pacific "Modoki" event, which teleconnects differently: this is why the
hazard outlook changes when the flavour changes. The cuts are not symmetric
because the two regions do not swing alike. Niño-1+2 runs to +3.7 in an
east-Pacific peak while Niño-4 rarely passes +1.1, so the difference goes far
positive in 1982-83 and 1997-98 (+2.4 and +3.5 on the relative indices, OND) and
only a little negative in central-Pacific events: 2009-10, the textbook Modoki
case, averaged −0.91 over OND 2009, and at −1.0 no El Niño since 1982 would be
central-Pacific. The scale card and the hazard outlook read one definition, so
the page cannot call one event two things. It is a simple proxy, not the formal
E/C EOF indices.

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
- **Ctrl-scroll** (⌘ on a Mac) to zoom to 10×, or use the buttons. A bare wheel
  scrolls the page, because trapping the scroll on a panel two thirds of the way
  down a long document is how a reader gets stuck. Detail is re-chosen at every
  zoom step — see *Level of detail* below — so the Hawaiian chain arrives as
  eight separate islands rather than one blob.
- **Click any point** — or tab to it and use the arrow keys and Enter — and the
  panel beside the globe fills with every catalogued relationship covering that
  coordinate, most specific first, each one scored twice: at today's RONI and at
  the projected peak. Clicking Lima returns the coastal flood signal, the
  anchoveta fishery and highland malaria; clicking central Australia returns
  nothing, and says so, because silence is a finding.
- **Filter by polarity** — wetter, drier, warmer, cooler, storms, fisheries,
  health — to see that class of footprint picked out against the rest.
- Local SST anomaly is read off the same quantised field the globe is drawn
  from, so the number in the panel is exactly the colour under the pin — good to
  half a ramp step, which the tests bound.

- **Live storms are drawn on the sphere**: the observed track, the official
  forecast track, the ensemble members faint in the storm's colour, the current
  position sized by category, and a chip per storm above the panel. They rotate
  and cull with everything else.

Seven preset views (Pacific, Americas, Africa, Asia-Pacific, Atlantic, and each
pole) exist so the reader can get to a hemisphere without learning to drive.

The field behind the globe is OISST at its own quarter-degree resolution —
1,440 × 632 cells — and the coastline is Natural Earth 10m, 130,010 vertices.
Neither is drawn in full, ever. The payload is one character per cell against an
11-step ramp rather than JSON numbers, which is the difference between a 0.9 MB
attribute and a 5 MB one.

#### Level of detail

A 640-pixel globe unzoomed has about 0.6 degrees to a pixel; the same globe at
10× has 0.03. Drawing for the second case in the first costs a second a frame and
buys nothing the eye can resolve, and drawing for the first case in the second is
the polygon the reader complains about. So three things are recomputed on every
frame, server-side for the first paint and in the browser after that:

- **The visible window.** In an orthographic projection the near hemisphere lands
  within one unit of the centre, so the visible cap radius is
  `asin(min(1, (size/2) / (radius × zoom)))`, and the longitude reach along a
  parallel is that over `cos(lat)`. Rows and columns outside it are never
  visited, and a coastline polyline whose bounding box misses it is rejected
  before a single vertex is projected.
- **A draw budget.** The stride through the field is the coarsest one whose
  visible cell count stays under 65,000. Zoomed out that is a decimated view;
  zoomed in, where the window is a five-hundredth of the sphere, it is every cell
  at 0.25°. Cost per frame stays flat and detail follows the zoom, which is the
  opposite of drawing everything and hoping.
- **A coastline level.** Douglas-Peucker is *hierarchical* — the points surviving
  tolerance T are exactly those whose split distance is at least T — so four
  levels are one array with a level digit per point rather than four copies of
  the world. The level tracks degrees-per-pixel, and drops one while dragging,
  where nobody is reading an estuary.

| Level | Tolerance | Points | For |
|---|---|---|---|
| 0 | 0.30° | 5,111 | an inset |
| 1 | 0.08° | 24,147 | the whole globe, unzoomed *(the default)* |
| 2 | 0.035° | 58,732 | a basin |
| 3 | 0.015° | 130,010 | a landfall, at full zoom |

Adjacent cells of the same colour along a parallel merge into one quad, capped at
6° of span so a merged quad's chord cannot leave the sphere. The result is 7,700
polygons unzoomed at an effective 1.0°, falling to a few hundred at native 0.25°
when zoomed, and seven zoom redraws measured at 186 ms total.

## 5. Forecast

Three methods, each forecasting the official index, combined:

1. **Analog ensemble, matched on the calendar.** The past years whose RONI ran
   most like this one over the *same four calendar seasons* ending with the
   latest — MAM to JJA for a JJA start — each continued forward through the real
   record from that same season. ENSO is phase-locked to the calendar: events
   grow through boreal summer and autumn, peak near December and decay through
   spring, so an analog is only an analog at the same time of year. The ten
   closest go to a quality gate that drops any member worse than
   `max(0.45, 1.6 × best)` RMSE, the rest are weighted by `1 / (rmse + 0.1)`, and
   each continuation is offset to start from today's value — the member tracks
   are drawn shifted, exactly as they enter the mean. The start year is held
   out, and so are the year before it, whose continuation runs through the
   current record, and the two after, which in the hindcast hold the truth being
   forecast.

   This replaced matching past events on their first seasons after onset,
   whatever the month. That version continued an autumn-onset event from its
   winter peak into its decay and set it against a summer event with its growth
   season still ahead; cross-validated over 1956-2026 it was the worst method at
   every lead past the first — RMSE 0.90 at six months inside El Niño against
   0.78 for damped persistence — while carrying 45% of the weight unverified.
   Matched on the calendar, the analogs score 0.66.

2. **Nonlinear recharge oscillator.** The two-variable system, fitted by least
   squares per calendar month from the monthly series the official index is the
   three-month mean of (`Rnino34` for RONI) and the WWV record:

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

3. **Damped persistence**, regressing each target season on today's value with a
   separate fit for each target season, so the spring barrier and the autumn
   growth are in the numbers rather than asserted.

Method weights are **not chosen by hand**. All three methods are scored in the
same cross-validated hindcast (section 6), and each one's weight is the inverse
of its mean squared error there — currently analog 35%, recharge 37%,
persistence 28%, printed with the forecast on the page and in the report. The
fallback weights are used only when there is no record to verify against.

The 10th-90th percentile band is the wider of the analog members' own 10-90%
spread and a normal 80% interval whose σ is the verified RMSE at that lead
combined with half the spread between the methods, so the fan is as wide as the
record says it should be, not as wide as looks reassuring, and widens when the
methods disagree. Each peak probability is that of the season likeliest to clear
the bar, judged on the value CPC prints (+1.95 prints +2.0) — a floor on the
chance that some season clears it. Run on 24 September 2026 from JJA: peak
**+2.25 in NDJ 2026**, 80% range +1.62 to +2.88; P(≥ +2.0) 73%, P(≥ +2.5) 34%.

## 6. Verification — how much is the forecast worth?

All three methods, and the weighted ensemble exactly as it is issued, are scored
by **cross-validation over the whole RONI record** (77 years). Each hindcast
starts from the moment its start season's value exists, with the start year and
the year after it — the year a long-lead forecast verifies in — held out of every
fit, and the analog years around it held out as the live forecast holds them
out. Nothing reported here is in-sample. It reports:

- RMSE, anomaly correlation, bias and sample count at each lead;
- RMSE **by method** at each lead — analog, recharge and persistence side by
  side — which is where the weights come from. A method with too few forecasts
  at a lead to score shows no score, not a perfect one;
- the **useful horizon**: the last lead whose anomaly correlation still reaches
  0.5, the usual bar for a useful ENSO forecast. When every lead scored clears
  it — as now, 0.59 at +9 — the horizon is stated as a lower bound, "at least
  9 months": that is where the scoring stopped, not where the skill did;
- correlation at 6-month lead **by target season**.

That last one measures the **spring predictability barrier** from the data rather
than asserting it from the literature. Forecasts of MJJ and JJA, started six
months earlier and carried across boreal spring, are the weakest — 0.43 of
correlation below the best target season, NDJ at 0.88 — which is the honest
reason a forecast made in winter is worth less than one made in September.

## 7. Alerts

Rules are evaluated on every run against thresholds **and against the previous
run held in the local SQLite database**, so an alert fires once when a condition
appears, is marked `NEW` on that run only, and clears itself when the condition
lifts. A standing alert whose level rises is news even though its condition is
not — a threat that was a watch yesterday and a strike today — so it is marked
with the level it rose from. Levels are CRITICAL / WARNING / WATCH / INFO. Each
carries an icon and a written level, never colour alone. Alert text is written
once, in ASCII for the report and the console ("+1.0 degC", "x10^14 m3"), and the
page prints the same sentences with their units signed: °C, × 10¹⁴ m³, σ.

`python track.py --alerts-only` exits 1 if anything at WARNING or above is open,
which is enough to drive a cron job or a notifier.

## 8. Hazard outlook

28 documented teleconnections, each gated on a minimum intensity and, where it
matters, on the EP/CP flavour, with a stated confidence and a named exposure.
Likelihood is scaled by how far the *projected peak* clears each link's own
threshold: 0.4 past it is probable, the bar for the outlook, and 1.0 past it is
likely; an event of the wrong flavour needs 0.75 more for a flavour-gated link.
A link below the bar is not dropped silently — it is listed on watch, with the
peak it would need, and a contested one (the Indian monsoon) is rated possible
at most, however strong the event.

This is the part that is easiest to misread, so the panel states its own limits
up front: these are **shifted odds from historical composites, not a forecast**.
ENSO changes the probability distribution of a season; it does not determine the
outcome, and vulnerability on the ground matters more than a rainfall percentile.
The links are keyed to the projected peak, not today's value, so if the event
underperforms the forecast the lower-margin entries drop out first.

**This tool is not a substitute for your national meteorological service.**

---

## 9. Tropical cyclones

**On stopping one: it cannot be done, and the attempt has been made.** A
Category 4 releases on the order of 10^19 joules a day as latent heat, several
hundred times world electricity generation. Nothing that can be flown into a
storm changes a number of that size. The experiment that tried is recreated in
full in section 10 rather than cited here, because an assertion is not an
argument and the argument is computable from the decks this tier already holds.

What *can* be delivered is lead time, and that is what this tier is. It is stated
in the terminal report and on the dashboard panel in those words, so nobody reads
the tracks and infers a capability that does not exist.

**Three ATCF decks per live storm**, fetched in a second wave once the index of
active systems is known:

| Deck | What it is | Cadence |
|---|---|---|
| **b-deck** | best track — the analysed position and intensity | every six hours |
| **f-deck** | the official NHC/CPHC forecast | every advisory |
| **a-deck** | model guidance, including the ensemble members | every six hours |

Traps handled, because ATCF is a fixed-width format with a long history:

- Latitude and longitude are **tenths with a hemisphere letter glued on**
  (`234N`, `1207W`), not signed decimals.
- The a-deck is **gzipped**, the other two are not.
- A deck carries **many techs interleaved**; the official forecast is `OFCL` and
  the ensemble members match `^(AP|AC|EP|EE|EC)\d\d$`. Reading a deck without
  filtering gives you forty overlaid tracks.
- The b-deck contains **intermediate landfall fixes** at off-synoptic hours and
  **post-tropical** entries. Both are real and both must be excluded from ACE, or
  the number comes out high.
- The same storm can appear in **two basins** as it crosses 140W, under two ids.

From those, per storm: current intensity and Saffir-Simpson category (64/83/96/
113/137 kt), central pressure, the radius of maximum wind and the eye
diameter where the deck reports them (columns 19 and 21, which are `0` rather
than blank when unobserved), 24-hour intensification against the 30 kt
**rapid-intensification** threshold, motion, distance to the nearest coast, the
nearest catalogued place, and the official forecast out to `HORIZON = 120` hours
with the guidance envelope drawn around it.

**Every forecast is timed from the latest analysis.** The official forecast,
the guidance and the ensemble come from cycles that can be hours older than the
newest best-track fix — on 24 September 2026 Polo's forecast was the 06Z
advisory while the best track ran to 12Z — and a lead counted from its own cycle
is not a time from now. Each forecast fix is re-based to hours after the latest
analysis, a fix already valid at or before it is dropped because the analysis
supersedes it, and members from different cycles are compared at the same valid
time. Every threat names its valid time in UTC beside the lead.

**A closest approach is measured along the forecast line**, not only at the
forecast points: the nearest point of each leg to the place, with position,
time and wind interpolated along it. Forecast points twelve to twenty-four hours
apart can fall either side of a place the line itself runs over. Where the
analysis itself is the closest point the storm is already moving away, and the
alert says so.

**Ensemble spread is the members' mean great-circle distance from their mean
position** — the mean taken as unit vectors, so members either side of 180°
average to 180° — the conventional measure, and the one the spread-skill
literature sets against the ensemble-mean track error. A threat six hours out
is quoted the spread six hours out, from the nearest lead the members share,
not the spread at day five.

**The maps are true shape.** A degree of latitude is drawn as long as a degree
of longitude; the window used to be stretched to a fixed frame, and on
24 September 2026 the storms from Hawaii to the mid-Atlantic came out 2.17 times
too tall, with Polo's west-north-west track reading as north-west.

**How the track map draws a storm.** The best track is a line with a dot at
each six-hourly fix, so the spacing is the storm's speed, and one marker where
the storm is now, the size of its category. The official forecast runs on from
it dashed, each point badged with what the storm is forecast to be there, as
NHC's track graphic marks its points: the category's number for a hurricane or
its equivalent, S for a storm, D for a depression. Where the system is not a
tropical cyclone (post-tropical, a remnant low, a disturbance or a wave) the
point is drawn open, its ring dashed, and lettered by its wind as NHC letters
it, D, S, H at hurricane force and M from 96 kt; a subtropical storm keeps
NHC's letter too, Saffir-Simpson being a hurricane's scale. A point whose
badge would cover the storm's marker or another badge keeps a plain dot, and no
label is written over a badge. Underneath, the ensemble members (the models'
guidance, where a deck carried no ensemble) run from where the storm is now, in
its colour and fainter with each day of lead, as smooth curves through their
points: centripetal Catmull-Rom splines, which never loop or cusp on a short
step beside a long one as a uniform spline does. Until 8 October 2026 they were
one grey cloud of straight segments for every storm, each starting wherever its
cycle put it; where two storms' clouds cross, which storm a member belongs to
is the information. The globe draws each storm's members in its colour too.

**Accumulated cyclone energy** is computed the way the definition reads and not
loosely: 10^-4 × Σ v² over six-hourly synoptic fixes at 34 kt or above, warm-core
stages only. That is the quantity the season verdict rests on, so the tests pin
it against a hand-worked example including a fix of each kind that must *not*
count.

**The season is scored against date-matched climatology.** Comparing a season's
ACE in September against a full-season normal is meaningless, so the normal is
recomputed from HURDAT2 through the same calendar date, 1991-2020 base period,
alongside an El Niño-year composite over the same window. The panel then states
what this event's official index and flavour predict for each basin — Atlantic suppressed,
east and central Pacific enhanced, the two most reliable seasonal signals ENSO
has — and prints whether that is verifying.

This is the one place in the system where a forecast it made is scored against an
outcome in the same season, in public, rather than asserted.

**Beyond the decks.** Three more sources joined the tier in September 2026:

- **JTWC's warnings** for the west Pacific, the north Indian Ocean and the
  southern hemisphere, read from the `.tcw` files its RSS feed links into the
  same storm records the ATCF decks make. A storm both centres list is NHC's,
  the authority on it. ATCF's longitudes run 180 W to 180 E, so a track or an
  ensemble member that crosses the date line jumps 360 degrees; every map takes
  each longitude the short way, beside the storm, or the map of the live tracks
  comes out wider than the world and a track is drawn the whole way round it.
- **NHC's protective products**, as the active-storm index links them for each
  storm: coastal watches and warnings, the forecast cone, peak storm surge, the
  wind speed probabilities and the public advisory. Where each watch and warning
  is in effect is given in the advisory's own words, "Hawaii County"; the lines
  in the watches file draw them on the map, and name the coast only where the
  advisory did not come - a line round an island by the towns along it, a
  stretch from one town to another only where both ends are within 40 km of
  one, and otherwise by the town nearest its middle. A product the index does not link was not issued
  and nothing is said about it; one that cannot be fetched or read says so. Each
  keeps its own advisory number, and one a later advisory has superseded is
  kept, with a note saying which. An intermediate advisory, 20A, reissues the
  watches and the cone but not the surge or the wind probabilities, so under 20A
  those of 20 are still the latest and are not called old. An east Pacific
  storm past 140W is CPHC's, and its products are credited to CPHC.
- **Formation outlooks**: NHC's and CPHC's areas with their 2- and 7-day chances,
  JTWC's disturbances with their 24-hour potential, and the invests until they
  are numbered. A JTWC paragraph on an area it no longer rates - dissipated, or
  developed into a numbered storm - is not listed. JTWC's tropical cyclone
  formation alerts, `.tcw` files in ATCF's "ALERT" format that its RSS feed
  links beside the warnings, are read from their prose: the area (the stated
  distance either side of a line, or round a point), the time by which the
  alert is reissued, upgraded or cancelled, and the system's motion (moving,
  tracking, drifting or quasi-stationary), winds and pressure. Each is laid on
  the advisory's area for its invest, whichever of the two is newer placing the
  system; an advisory reissued since that cites no alert says it is over, a
  cancellation clears it, and so does a storm's first warning that "supersedes
  and cancels" it, though the feed still links the alert. An alert that gives no
  issue time cannot be put before or after the advisory, so it is kept, with a
  note saying so; one that names no invest is keyed by where it is. Past the
  time it gave, with nothing newer read, an alert is said everywhere to have
  run out to that time, since JTWC will have reissued, upgraded or cancelled it
  and which is not known. A low that has never
  been a tropical cyclone is a low (a non-tropical one for ATCF's EX); after
  genesis it is a remnant low, or post-tropical. An invest within 150 km of a numbered storm at the same analysis
  time is that storm, and the report says what it became — Invest 90L became
  Gonzalo (AL07) on 25 September 2026.

Alerts are raised from the official watches, warnings and formation chances, and
all of it is drawn on the storm desk, section 12.


---

## 10. Project STORMFURY, recreated

The 1962-83 hurricane modification experiment, rebuilt as a **decision procedure
and two measurements** and run against whatever is spinning right now. Not a
history lesson: the criteria are evaluated against live storms, the hypothesis is
computed, and the confound that ended the programme is measured on this season's
decks rather than quoted from the literature.

It is kept separate from section 9 for a reason. Three things failed, and they
failed *independently* — fixing any one of them leaves the other two standing,
which is why this is not an engineering problem waiting on a better aircraft.

**The mechanism, which was never the part that was wrong.** Seeding the region
outside the eyewall was supposed to build a new eyewall further out. Air arriving
at a larger radius carrying the same absolute angular momentum must turn more
slowly:

```
M = r·v + |f|·r²/2          f = 2Ω sin φ,  Ω = 7.292115e-5 s^-1
v₂ = (M − |f|·r₂²/2) / r₂
```

The Coriolis parameter enters as a magnitude because the wind enters as a speed;
a southern-hemisphere cyclone turns the other way, so both are negative in the
signed convention and the product is unchanged. The panel tabulates the
prediction for the strongest live storm at 1.25×, 1.5×, 1.75× and 2× eyewall
expansion. At the equator, where the planetary term vanishes, it reduces to pure
`1/r` — which is what the test asserts. **The arithmetic genuinely predicts a
drop about the size STORMFURY reported for Debbie.** That part held up.

**The trigger, which is absent.** Silver iodide works by freezing supercooled
liquid water. Hurricane eyewall updrafts are already glaciated at seeding
altitude — warm-rain coalescence strips the liquid out below the freezing level —
so there is nearly nothing for the agent to act on (Willoughby et al., *Bull. Am.
Meteorol. Soc.*, 1985). The panel prints the layer the hypothesis needed, derived
from a 6.5 K/km lapse rate over a 28.5 °C sea surface: roughly 5.0 to 7.5 km,
about 2.5 km deep, above a freezing level near 4.4 km. **This criterion fails for
every storm, in every season, and no aircraft fixes it.**

**The magnitude, scored rather than assumed.** This is the part that is not in
the literature, because it comes out of this season's b-decks. Hurricanes
relocate their own eyewalls unaided several times a season, so every natural
expansion is a free test of the formula above: ask what conserving angular
momentum says the wind should become, then compare it with the wind the storm
actually had six hours later. On the decks in the cache as this was written, over
20 natural expansions in 6 hurricanes, **angular momentum predicted a mean 24.5%
wind drop and the storms gave up 4.4% — an overstatement of 5.5×, with 9 of the
20 holding or strengthening while the eyewall expanded.** A hurricane is not a
spinning-down flywheel; it is fed high-momentum air continuously through the
boundary-layer inflow, and the vortex restores itself while the eyewall moves. A
closed-system momentum argument is an **upper bound, not a forecast** — and
STORMFURY's expected effect came from exactly that calculation.

Measured only where there is an eyewall to move: hurricane force or above, a
radius tight enough to be an eyewall rather than a wind field (`MAX_EYEWALL_NM =
60`), and an expansion small enough to be structure rather than re-analysis
(`MAX_RELOCATION = 3.0`). Without those gates the column fills with disorganised
tropical storms whose "radius of maximum wind" wandered two hundred miles, and
then reports a confident number about an eyewall that never existed.

**The measurement problem, which is what actually closed it.** Debbie's headline
was a 31% wind reduction. The panel histograms every 24-hour intensity change in
every *unseeded* hurricane this season on the same axis, with ±31% marked. On the
current cache: **5 of 148 intervals (3.4%) weakened by at least that much, and 17
(11.5%) moved that far in one direction or the other.** An effect that has to be
picked out of that distribution, from a sample of four storms, was never
separable from what hurricanes do untouched.

**Would it have been allowed to fly?** Four criteria per live storm:

| Criterion | Rule as applied |
|---|---|
| Within aircraft range | ≤ 2,040 km (about 1,100 nm) from Roosevelt Roads, Andersen AFB or Lakeland |
| Coherent eyewall | ≥ 64 kt, with an RMW reported and ≤ 60 nm |
| Clear of land for 24 h | ≤ 10% of tracks within 50 miles of land inside 24 hours |
| Supercooled water to seed | the trigger above — fails always |

A criterion the decks cannot answer reports **unknown**, not pass. The east
Pacific routinely fails the range rule, which is not an artefact: it is the real
historical constraint, and it is most of why only four storms were seeded in
twenty-one years.

**The record**, printed with what each run actually claimed: Esther (1961, ~10%),
Beulah (1963, eyewall dissipated and reformed further out), Debbie (1969, 31%
then 15%) and Ginger (1971, no measurable effect). Ginger was a large diffuse
storm with no coherent eyewall to move, seeded because it was what was available
— which is itself a statement about how rarely the criteria above are met.

**What the programme did buy:** twenty years of research aircraft inside
hurricanes. The eyewall replacement cycle, the modern understanding of hurricane
structure, and the reconnaissance programme that still flies are all products of
STORMFURY's observing arm. The measurement outlived the experiment it was built
to serve.

Every number above is recomputed on each run from data already in hand, so the
figures quoted here are the ones from the cache at the time of writing and will
move with the season. The module computes; `storms.fury_card` and
`report._section_stormfury` draw. Nothing in it fetches anything.

---

## 11. The atlas — what El Niño did to this exact point

Every tier above answers "how big is this event". This one answers the question
a reader actually arrives with: **what does it do where I live.** Open
`output/atlas.html`, drag, zoom, and click anywhere on Earth. The page replies
with what the last forty years of El Niño events measurably did at that cell.

### What a click returns

- **The difference itself** — El Niño mean minus neutral mean, in mm/day for
  rainfall and °C for surface temperature, for all four seasons.
- **The ordinary year it is a difference from**, so the number is readable. A
  percentage is printed for rainfall only: a percentage of a temperature is
  arithmetic on an interval scale and means nothing.
- **Welch's *t*** for that cell, and the verdict it supports. A cell is called
  wetter or drier only where |*t*| passes the two-sided 95% point of Student's
  *t* for its season's sample — 2.26 for SON's ten events, 3.18 for JJA's four —
  and the page quotes the |*t*| each season needs. Everywhere else it says *no
  clear signal*, which is the honest answer far more often than a coloured map
  suggests.
- **The catalogued teleconnections whose footprint covers the point**, narrowest
  scope first, so a regional claim sits above the global one that is true of
  every click.
- **The five nearest named places**, with distances, and the live cyclones
  within reach.
- **The ground it all lands on** — height or depth from vendored ETOPO1, with a
  button that measures the exact point against a 90 m DEM and says how far it
  is from the cell average.
- **Four ways out of the page** — Google Maps satellite, Google Earth, NASA
  Worldview and OpenStreetMap, all centred on the point.

### The composite, and how it was built

`tools/vendor_composite.py` computes it once from NOAA PSL and writes
`elnino/composite.py`; nothing is fetched at run time.

- **Phase is read from RONI**, the official index, as CPC prints it. **El Niño
  months** are those at +1.0 or above — the weak-event tail is where a
  teleconnection is least reliable; **neutral** is inside ±0.5, NOAA's own
  definition of neither phase. La Niña months are in neither sample. December is
  tagged to the following year, so DJF is a season and not three unrelated
  months.
- **The sample unit is an event, not a month.** Each event contributes the mean
  of its El Niño months in the season, and each neutral year the mean of its
  neutral months. The months inside one event share one ocean and are not
  independent draws; counted as if they were, the degrees of freedom were
  overstated about threefold, and cells the record cannot separate from an
  ordinary year were coloured as if it could.
- **Since 1979**: DJF has 9 events against 18 neutral years (1983, 1987, 1992,
  1995, 1998, 2003, 2010, 2016, 2024); MAM 6 against 33; JJA 4 against 33
  (1982, 1987, 1997, 2015); SON 10 against 20. The event under way when the
  grids were built, 2026, is left out: the composite is what past events did.
- **Rainfall** is GPCP v2.3, 2.5° — 72 × 144. **Surface temperature** is
  GHCN-CAMS, 0.5° strided by four to 2° — 90 × 180.
- Per cell, per season: the difference, the neutral mean, Welch's *t*, and the
  |*t*| that season's sample needs.

It reproduces the physics it should, which is the only external check available
for a composite computed in-house:

```
place        season  mm/day of normal      t needs  verdict             degC
Jakarta         JJA   -2.62      -61%  -8.97  3.18  drier            (-0.31)
Darwin          MAM   +1.80      +42%  +1.29  2.57  no clear signal        -
Manila          MAM   -1.95      -62%  -4.76  2.57  drier            (-0.48)
Nairobi         MAM   -1.56      -36%  -3.74  2.57  drier            (+0.87)
Harare          DJF   -2.13      -40%  -4.26  2.31  drier              +0.79
Lima            MAM   +1.28      +55%  +2.75  2.57  wetter                 -
Guayaquil       MAM   +3.66      +53%  +4.38  2.57  wetter           (+0.13)
Fortaleza       DJF   -1.43      -41%  -1.86  2.31  no clear signal  (+0.51)
Los Angeles     SON   +0.29      +63%  +1.69  2.26  no clear signal  (-1.14)
Sydney          DJF   -0.16       -5%  -0.26  2.31  no clear signal  (-0.08)
```

Each place is shown in the season its rainfall record is surest about; a
temperature in parentheses does not pass the test the rainfall beside it
passes. Maritime Continent dry-season drought, Philippine post-event spring
drought, southern African summer drought and coastal Ecuador and Peru flooding
all come back in the right place with the right sign, and so do the East
African short rains — Nairobi's SON is +56% at *t* +2.70 against the 2.26 it
needs, though its surest season is the drier long rains that follow. Nordeste
has the right sign, −41% in DJF, and at *t* −1.86 not the sample to prove it.
Sydney is flat because the Australian signal is inland and winter–spring, not
coastal and summer.

### The ground under the composite

A composite drawn over a coastline says where a difference lands. It does not
say what it lands on, and a rainfall deficit over the Sunda Shelf and the same
deficit over the Barisan range are not the same event. So the solid Earth goes
under the data.

**ETOPO1 global relief**, NOAA NCEI, resampled to a quarter degree and
**vendored into the repository** — 721 × 1441 cells, every one of them a height
or a depth, from the Mariana Trench at −10,750 m to 6,407 m in the Himalaya.
34% of the planet is land and the mean sea floor is 3,434 m down, which the
tests check as a way of catching an inverted sign or an unremoved bias.

It is stored as a PNG inside the Python module, as **two stacked eight-bit
greyscale planes**, high byte above low byte, elevations biased by 11,000 so
every number is positive. Not because 16-bit PNG does not exist, but because
`getImageData` hands back eight bits a channel whatever the file declares, so a
16-bit image would arrive quantised. Split into two planes it arrives intact,
and the browser does the decoding with the decoder it already has. Every row is
written with filter type 2, so the Python side is `zlib.decompress` and one
subtraction a byte. 1.25 bytes a cell, whole planet, no network.

From it the page draws a **hillshade** — Lambertian, sun from the north-west at
45°, the cartographic convention, because lit from anywhere else every reader
reads the valleys as ridges. Gradients are taken in metres, so the vertical
exaggeration means the same thing at the equator and at 70°N.

And a click reports the height or the depth of the cell under it, with the
caveat attached: a quarter degree is 28 km, so it is the height of a landscape
and not of an address. A button measures the **exact point** against Copernicus
GLO-90 and says how far the point is from the cell average — 900 m apart means
the cell was an average of a mountainside, and so was the composite for it.

### On Google Maps, and what is here instead

Google's and Mapbox's basemaps are **keyed and billed per tile**: using one
means a credential committed to this repository and a page that goes blank the
day a key is revoked or a quota is hit. Esri's answer with no key, but they are
**licensed, not keyed**, and the licence rules out exporting their tiles for use
offline. The atlas's premise is that it works from a USB stick on a plane, so by
choice it keeps no basemap of anyone's — its tiles are not Google's, but the
imagery is real and Google is one click away. **The street data lives on the
map** (section 13), which draws Esri's street, satellite and terrain maps while
it has the network and says so when it does not.

**Three basemaps, all NASA GIBS, keyless, public domain, and in EPSG:4326,
which is the projection already on the page** — so a tile is a rectangle in
degrees and lands where the arithmetic says, with no reprojection:

| Base | Layer | What it is |
|---|---|---|
| Blue Marble | `BlueMarble_ShadedRelief_Bathymetry` | cloud-free composite: the land itself, not a day |
| Satellite | `VIIRS_SNPP_CorrectedReflectance_TrueColor` | an actual photograph of the Earth, 250 m, two days back |
| SST anomaly | `GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies` | today's ocean against its own climatology, 1 km |

That last one is the event itself rather than the forty-year composite, which
is why choosing it **puts the composite away**: two diverging scales stacked on
one map is a picture of nothing. Its legend is NASA's own colour map, read from
their published `.xml` and drawn as a ramp, because describing a spectral scale
in words as "blue to red" is a wrong legend, and a wrong legend is worse than
none.

**GIBS's 4326 pyramid is not the power-of-two scheme every other tile server
uses.** Its top level is 288° to a 512-pixel tile, halving from there, so two
tiles span 576° of a 360° planet and the edge tiles are padded with black.
Assuming 180° at the top puts every tile above level zero in the wrong place at
the wrong size — which is what the first build of this did, and it showed as a
black band across the Pacific. The page now computes the matrix with a `ceil`,
draws one whole copy of the world per wrap rather than taking a column modulo
the matrix width, and clips the padding off the edge tiles.

**Then the ways out.** A click offers four, because the questions a composite
cannot answer are exactly the ones these answer, and they are better opened
where they are maintained than copied in behind a key:

- **Google Maps, satellite** — centred on the point, at a zoom matched to the
  map's own
- **Google Earth** — the same point, oblique
- **NASA Worldview** — the current viewport, today, in the full imagery archive
- **OpenStreetMap** — what is actually built there

Natural Earth is still underneath all of it: coastline, borders, rivers, lakes
and the **7,342-place gazetteer**, four levels of detail, vendored whole. And
the page still opens on the relief, which needs no network at all. Imagery is
the one layer that does, and if it cannot be reached the credit line says so
rather than leaving an empty rectangle.

The substitute for photographs was always **measurement**: "effects on the
local area" is a number with a statistic attached, for the exact cell under the
cursor. The photographs are now there too, so the reader can see what the
number landed on.

### What the map draws

Plate carrée, because the data is on a regular lat/lon grid and a projection
that fixed the shapes would misplace the cells. Panning is a transform on what
is already drawn — a million hillshaded pixels, the vector map and forty tiles
cannot be rebuilt at sixty frames a second — and zooming is a full redraw on
the next animation frame. The map is measured again whenever its box changes,
not only when the window does, so the composite, the relief and the vector map
stay on one another when the bar above the map wraps to another line.

- **The composite is a field, not a square per cell.** Painted a square per
  cell, the 2.5° grid read as a mosaic of big pixels. At each point the four
  cell centres around it are blended by how near each is (bilinear), a cell
  with no record taking no part; the blend is coloured in the ramp's eleven
  steps, worked out every two CSS pixels on a lattice fixed to the ground, so
  the steps' edges hold still as the map pans, and drawn up with the browser's
  smoothing, so the steps meet along soft lines as a filled contour map's do.
  At a centre the field is that cell's value, and a click still reads the
  whole cell. The land-only temperature grid fades out over the cell past the
  coast. The map draws the same field with the same code.
- **Colour** is the diverging ramp, inverted for rainfall so the dry end reads
  warm; the legend strip turns round with it.
- **Cells that fail the significance test** keep their hue and lose their
  weight, drawn at a sixth of the opacity, the fade blending from a cell that
  passes to one that does not. Colouring them confidently would claim a
  difference the record cannot distinguish from an ordinary year; dropping
  them would claim the cell was never measured. A toggle removes the mask for a
  reader comparing pattern shapes to a published composite.
- **Past about 90 pixels a cell the field fades**, and the scale bar says how
  wide one cell is on the ground. A 2.5° cell is 278 km at the equator; at deep
  zoom it fills the screen, and a wall of confident colour would be a lie about
  the resolution. The dashed outline of the cell under a click is drawn where
  the point is, across the date line too, and while any of the cell is on the
  page, whether or not the point is; not at all once the cell is wider or
  taller than the page, where all that would show of it is a lone line or two.
  A new field or season answers the clicked point again, and a tap beyond the
  poles, where a window taller than the world has only the page, opens nothing.
- **Labels are placed greedily** against a measured text box, storms claiming
  space before cities. A name that will not fit flips to the other side of its
  dot, and a dot whose name will not fit either stays, faintly.

The atlas is its own file rather than another dashboard card: it wants the whole
viewport, and it ships its own copy of the grids and the gazetteer, which is
several megabytes a reader who only wanted the index should not have to download.

---

## 12. The storm desk — every live storm, on today's imagery

`output/storms.html` is written by every run beside the dashboard, whose storm-desk
card opens it. It is built for a tablet as much as a desk: drag, pinch, double-tap
to close in, tap a storm to fly to its eye, tap anywhere else to ask what the
storms mean there.

**The imagery is live, and it is NASA's.** NASA GIBS serves the geostationary
imagers' frames every ten minutes, keyless, over https with CORS open, in Web
Mercator. The page asks for the tiles and for the frame times itself; a run
downloads none of it. Layer names, tile matrix sets and cadences are as GIBS's
capabilities listed them on 25 September 2026.

| Layer | From GIBS | Pixel | New image |
|---|---|---|---|
| GeoColor | GOES-East and GOES-West ABI GeoColor; Himawari falls back to infrared, as GIBS carries no GeoColor for it | 1 km | every 10 min |
| Visible | ABI band 2, AHI band 3 | 1 km | every 10 min |
| Infrared | ABI and AHI band 13, the clean longwave window | 2 km | every 10 min |
| Air mass | ABI and AHI air-mass RGB | 2 km | every 10 min |
| Rain rate | GPM IMERG | 11 km | every 30 min, hours behind |
| True colour | NOAA-20 VIIRS corrected reflectance | | one pass a day |
| Blue Marble | shaded relief and bathymetry | | none: orientation only |
| Detail | Harmonized Landsat 8/9 (L30) and Sentinel-2 (S30) | 30 m | the passes of a day |
| Night lights | VIIRS Black Marble | 500 m | the 2016 composite |

Three reference overlays wait to be asked for, because on 25 September 2026
GIBS answered its reference tiles with HTTP 500 at random: roads and borders,
coastlines, and built-up areas (Landsat HBASE, 2010, 30 m).

**Each imager keeps the longitudes it sees best.** The borders are the meridians
halfway between the sub-satellite points of GOES-East, GOES-West and Himawari; a
tile across one is drawn from both imagers, each clipped to its side. Where no
imager sees part of the view within 70° of zenith, the page says so rather than
stretching a limb view over it.

**A frame is shown once it is finished.** GIBS lists a frame before all its tiles
are made — a GOES GeoColor frame was half white 35 minutes on — so the newest
frame shown is the newest older than 45 minutes, and a frame whose tiles come back
missing or white is set aside for the one before it, so one imager never shows
two times at once. The loop runs the last two hours of frames; Compare puts two
layers either side of a divider you drag, and Swap trades them. Each side draws
its own newest finished frame, which can be another time, and the status line's
details give the compared side's as well as the base's.

**The eye is where the satellite sees it.** Cloud tops 15 km up are displaced by
the viewing angle, by tens of kilometres at a high zenith angle. For each storm
the page names the imager that sees it most nearly overhead, its zenith angle and
the parallax offset, and rings the place the eye appears on the image.

**What is drawn over it is what the centres issued**: the analysed track, the
official forecast and its cone, the 34, 50 and 64 kt radii by quadrant, the coast
under each kind of watch and warning, and the peak storm surge areas with NHC's
depths. The forecast slider moves every storm along its official forecast hour by
hour, and **Play** runs it on an hour at a time to the end of the forecast of the
storm picked (of every storm, with none picked) and stops there, or starts again
from now when it is at the end already, and is greyed with no forecast ahead to
play. The map stays the reader's while it plays, and a storm picked meanwhile
plays on from the hour shown, or from now when that is past the end of its
forecast. Play and the satellite loop take turns, the one started last running:
leaving a place brings back a loop that ran before only if Play has not been
pressed since. The slider moved by hand, or an address followed, stops Play.
On a phone the slider has a line of its own, the width of the screen, under
Play and the time it reads.
Each storm is named on the map for its wind at the hour shown, as the centres
name it: "Cat 4 · 115 kt" now, "Cat 2 · 95 kt at +48 h" ahead. Each point of its
forecast is marked with what it is forecast to be there, as NHC's track graphic
marks its points: the category's number for a hurricane or its equivalent, S
for a storm, D for a depression, and where it is not a tropical cyclone NHC's
letter for its wind (D, S, H, M) in a dashed ring; a point keeps a plain dot
where its mark would cover a storm's marker, a name or another mark. A storm
forecast to strengthen says in its row what it
peaks at and when, and its *Now* tab the peak in full.
The formation outlook draws NHC's and CPHC's areas with their chances and
JTWC's disturbances with their potential, a formation alert's box in its colour
with the time it runs to and the system's winds, pressure and motion, and the
invests are marked. An alert whose time passes, even while the page is open, is
reworded as having run out to it and its box drawn faded and dashed, until a
newer run reads what JTWC did.

**Beside the map, for each storm:** the advisory position, motion and intensity;
the official forecast; NHC's wind speed probabilities for its named places; the
exposure table — every gazetteer place the forecast wind field reaches, and when
34, 50 and 64 kt first arrive there, derived hour by hour from the official radii,
with a radius the forecast does not give reported as not forecast rather than as
calm; the watches and warnings by coast; the surge areas; what people and animal
owners are advised to do, each line linked to where it comes from; and who is
responsible for warnings there — the country's national meteorological service,
not this page.

**Find a place, and what the storms mean for it.** The search box takes a town, a
first-level region, a country or a position (`18.0N 76.8W`, `18.0, -76.8`), from
the page's own copy of the 7,342-place gazetteer, accents and case ignored and
nothing sent anywhere as you type; a street or an address comes from Esri's
geocoder, and only when asked (section 13). Choosing one, or tapping anywhere on the map, pins the
point and opens *Here*: for each live storm the distance and bearing now, the
closest approach on the official forecast, when each wind threshold arrives,
whether the point is in the cone, the nearest coast under each watch and warning,
any surge area it is in; the formation areas near it; who warns for it; and a
link to the atlas at that point, `atlas.html#at=LAT,LON`. A storm with no
official forecast this run is said to have none, and a watch, cone or surge
product that could not be fetched is said to be missing - with what the public
advisory says is in effect, where it came - never left to read as nothing in
effect. The exposure table says the same of a storm with no forecast. *Here* follows the
exposure table's timeline and rules exactly, and the path the page carries keeps
the forecast centres unrounded for that reason: on 25 September 2026 it gave the
table's arrivals, unknowns and closest approaches at every one of 16,104 test
points around the six live storms.

**Close in.** On NASA's imagery the desk zooms to level 13, and on the street
maps to 19 (section 13). The Detail layer shows Landsat and
Sentinel-2 at 30 m for the newest day with an image at the centre of the view.
GIBS lists the same days for everywhere, so the page looks at the tile there, a
day at a time back from the newest, 40 days at most; the arrows step to the next
earlier or later day with an image. A day GIBS does not answer for at all is not
taken for a day without one: the page says GIBS did not answer, and looks again
in a minute. Sentinel-2 is drawn over Landsat, and where their granules meet the
clouds differ by the hours between the passes. Thirty
metres is fields, runways, reservoirs and the outline of a town. It is not
streets or houses; for those, Esri's street and satellite maps are one tap away
on the same toolbar, and go to zoom 19. Town names fill
in as the view closes in, night lights show where people live, and the built-up
overlay shows how far a town extends.

**Offline, it still draws.** Without GIBS the page draws the vendored Natural
Earth coastline and every storm, says the imagery is unreachable, and offers to
try again. The same holds when GIBS lists its frames and then sends none of
their tiles: a frame whose tiles never came is not named as if it were on the
screen, an imager whose tiles alone failed says so on its line, and trying again
asks afresh for every tile that failed.

**On a tablet**, serve it from the machine that runs the tracker:

```
python track.py --serve                    # run, then serve output/ at http://127.0.0.1:8765/
python track.py --serve 8800 --lan         # ...on port 8800, to devices on this network
python track.py --watch 60 --serve --lan   # keep running every hour while it serves
```

With `--lan` it prints the address to type on the tablet. Anyone on that network
can read the pages, so use it on one you trust; the first time, Windows may ask
whether Python may accept connections — allow private networks only. The server
lists no directories, refuses any `..` in a path however it is spelled, and marks
every page no-cache, so the browser asks for a newer copy each time. A served page
also asks each minute which run the server has (`run.json`) and takes up a newer
one in place, keeping the view, the part of the panel being read, the storm
chosen and its tab, the tables opened, the focus and the place pinned, with
Google's frame in *Here* left as it is, so a tablet left open follows the runs.
A run that updated code wrote is loaded instead, once the tablet is left alone,
and the page comes back where it was.

`output/storms.json` (schema 1) is the same content as plain JSON: every live storm
with its advisory, track, hourly path, cone, watches and warnings, surge areas,
wind speed probabilities and exposure table; the invests; the outlook areas; the
imagery layers and endpoints; and, under `methods`, how every derived number was
worked out. Every time is ISO 8601 UTC, and each storm's longitudes are written
within 180° of its centre, so a storm on the date line runs from 179.4W to
180.8W rather than jumping to 179.2E.

**Nothing on this page changes what a storm does.** It shows what the warning
centres have issued, on imagery under an hour old, and turns it into lead time for
one place. The warnings for a coast are its national meteorological service's.

---

## 13. The map — El Niño's effects, street by street

`output/map.html` is written by every run beside the storm desk, and it is the
same page opened another way: on the whole planet across the width, the Pacific
in the middle, a street map under the El Niño rainfall composite for the season
containing the build date. It zooms from level 1 to 19, the planet to a single
street, and drags, pinches and double-taps as the desk does. Zoomed out on a
wide screen the world repeats side by side, as the tiles do, and everything on
it repeats with it: the regions, the boxes, the tracks and cones, every storm,
the outlook areas, the pin, the names and, offline, the page's own coastline. A
tap on any copy flies to the one nearest the view, across the date line if that
is shorter. Every storm is on
it, and `storms.html` carries everything the map has, with the composites off
until asked for. Each page's menu links to the other and carries the view,
the storm picked and the forecast's hour across
(`map.html#view=LAT,LON,ZOOM&storm=ID&hour=H`); `map.html#at=LAT,LON` opens *Here* at a
point, which is how the atlas's dossier hands a point over. The dashboard's map
card, its storm-desk card and every page's menu link to it.

### The maps under it

| Map | From | Deepest zoom |
|---|---|---|
| Streets | Esri World Street Map | 19 |
| Satellite | Esri World Imagery, with Esri's World Transportation and World Boundaries and Places drawn over it | 19 |
| Terrain | Esri World Topographic Map | 19 |
| OpenStreetMap | `tile.openstreetmap.org`, offered only when the page is served | 19 |
| GeoColor, Visible, Infrared, … | NASA GIBS, as in section 12 | 13 |

**Esri's tiles need no key.** `server.arcgisonline.com/ArcGIS/rest/services/…/MapServer/tile/{z}/{y}/{x}`
answered 200 with no key and `Access-Control-Allow-Origin: *` on 28 September
2026. They are licensed, not keyed: used under the Esri Master License
Agreement, with each service's credit shown on the map as the service publishes
it, drawn as the page is viewed and never exported for use offline. The
satellite map is one metre or better in many parts of the world, by Esri's own
description — single buildings at zoom 17 in Washington — and coarser elsewhere. Switching to a NASA layer from
deeper than 13 zooms out to 13.

**Past its coverage Esri answers with a picture of nothing.** Beyond the zoom a
place has data for, the tile server does not say 404: it says 200, with a grey
JPEG reading "Map data not yet available" — open Pacific from zoom 16, Amazon
imagery from 18, Lima from 20. Drawn, that is a grey square where the map
should be. So each map tile is sampled 16 × 16 once it has loaded, which the
open CORS header allows, and a tile with at least 200 of its 256 samples within
3 of RGB 204,204,204 is the placeholder: it is hidden, remembered, and that part
of the view is drawn from the parent tile, up the pyramid until a real tile
answers. A placeholder at one level means no level under it has imagery either,
so the page asks for nothing deeper there once it has seen one, and only the
tiles are redrawn for it, not the marks. A cream empty street tile, open sea,
cloud, a transparent tile and a
tile that failed to load are none of them the placeholder. The status line says
when part of the view is a coarser tile, enlarged.

**OpenStreetMap only when served.** Its tile servers answer a page opened from a
file — which sends no Referer — with an "Access blocked" image, and a served
page, which does send one, with real tiles. Opened from a file, the button is
greyed, and pressing it says why in a line under the buttons, which a screen
reader reads out, with the command that serves the page; the compare menu lists
it as needing the page served.
CARTO's basemaps were tried too, and answer with an "API KEY REQUIRED" image.

**Compare works across both kinds.** Its menu offers the street maps and NASA's
layers alike, grouped, so a street map can sit beside today's infrared with the
divider between them, and Swap trades them. Each layer is drawn on its own side
of the divider only — where the base has nothing, past an imager's disc or under
a tile not yet come, the other does not show through — and the satellite map
brings its roads and names to whichever side it is on. The status line's details
say what the compared side shows: its source, its own frame's time, or that its
server did not answer, with Retry.

**Every name on the map says where it comes from.** The credit line carries the
credit of each map drawn, as Esri publishes it, and for each NASA layer drawn
"Imagery: NASA GIBS." with the mission behind it: GOES: NOAA and Himawari: JMA
for the imagers in view, IMERG: NASA GPM, VIIRS: NASA and NOAA, HLS: NASA, from
USGS Landsat and ESA Copernicus Sentinel-2, the Earth Observatory's Blue and
Black Marble, SEDAC's HBASE, GHRSST MUR from NASA JPL for the ocean and MODIS
from NASA LANCE for the floods. The line is read off the tiles on the screen,
each on its side of the divider, loaded and not hidden: a layer not drawn, a
tile that failed and an imager out of view are not credited.

**The town names know when to stay out.** Esri's maps and OpenStreetMap name
their own towns (the satellite map by Esri's places drawn over it), so the
page's names are not drawn over them, and on NASA's imagery they start at zoom
4; the Towns switch says which, beside itself, rather than doing nothing.
Compared, each side of the divider decides for itself: the names are drawn over
NASA's imagery on its side and not over a map on the other, nor across the
divider onto it.

**Google is here, but never under the page's own layers.** Google's terms forbid
drawing its tiles inside another map, and its own embed gives the same data
legitimately. *Here* has Map, Satellite and Street View buttons that load
Google's embed (`maps.google.com/maps?q=…&output=embed`, and `output=svembed`
for Street View) in a frame beneath; nothing is requested from Google until one
is pressed. Beside them, links open Google Maps, Street View and Google Earth at
the point, by Google's documented Maps URLs. Neither needs a key.

### El Niño on it

**Rainfall and temperature composites**, drawn exactly as the atlas draws them
(section 11): the same grids, the same 11-step diverging ramp inverted for
rainfall, full scale ±3.0 mm/day and ±1.6 °C, a cell that fails its season's
*t* test at 0.16 of full weight unless the mask is turned off, and past 90 screen
pixels a cell the colour yielding to `max(0.42, 1 − (px − 90)/420)` so the
streets show through it. The composite is the atlas's field, by the atlas's own
code: blended between the cell centres and coloured in the ramp's steps, worked
out every two CSS pixels on a lattice fixed to the world, so the steps' edges
hold still as the map pans (coarser on a screen so big that would be more than
a quarter of a million points a frame), and drawn up with the browser's
smoothing on a canvas under the map's names and marks, across the date line and
Greenwich without a seam, in the ramp of the theme on the page, whichever switch
changed it. A tap still reads the whole cell, and the outline of the cell under
the pin is hidden once the cell is wider or taller than the view: Mercator draws
a cell at 60° N twice as tall as it is wide. The El Niño
menu picks rainfall, temperature or neither, the season (the one containing the
build date first, the next one marked), the mask and the strength. The key reads
the cell under the centre of the view by the same rule as a tap, and from zoom 7
says how many kilometres one cell is across there: a 2.5° cell is 278 km at the
equator, and at street zoom the colour on the screen is a blend of cells that far
apart, not the street's, and the value read is the whole cell's. The reading has a line of its own that only grows while the window
keeps its width, so the map above it does not jump as the view moves.

**The ocean today** is the GHRSST MUR L4 sea surface temperature anomaly, daily,
from NASA GIBS (`GHRSST_L4_MUR_Sea_Surface_Temperature_Anomalies`, level 7).
**Floods, the last three days** are MODIS Terra and Aqua's combined flood
product (`MODIS_Combined_Flood_3-Day`, level 9). Both are off until ticked, and
drawn at 0.8 strength by a slider of their own, apart from the composite's, so
the ocean can be read through the rainfall or the other way round. A
tap reads the pixel under the point back through NASA's own colour map, parsed
from the published `.xml` — 62 bins of 0.1 °C from below −3.0 to +3.0 °C or
more, or MODIS's classes — so the answer is NASA's bin and not a guess from a
colour. MODIS delivers "surface water" (the sea itself, near a coast) and
cloud-bound "insufficient data" as whole granules, over the ocean too, so those
two classes are drawn at a fifth of their strength and do not hide the sea
beneath; flood and recurring flood stay at full strength. Past zoom 12 both
layers are hidden, and the key says why in numbers: at 13 an MUR pixel would be
64 screen pixels across.

**The Niño regions** — CPC's four boxes — carry this week's anomaly: relative to
the tropical mean when CPC's relative weekly file has the week, as CPC now
quotes it, else the traditional anomaly, else no number. Each is named above its
northwest corner, or under the box where a neighbour's name has the room above,
as Niño 3.4's has Niño 3's at zoom 3; they are on for the map and off for the
storm desk. **The impact regions** are the 28 documented teleconnections'
footprints, dashed, and solid where this event's hazard outlook puts the effect
in play. They wait to be ticked, on the map and the desk alike: twenty-odd grey
boxes over the composite read as more big pixels. Show, beside an effect with a
place to show, flies to its region, draws that one alone and stays pressed while
it does; pressed again, or with the regions ticked on or off, it puts the region
away. An effect true of everywhere, such as the global mean temperature, has no
Show.

**El Niño now**, in the side panel: the index and its tier, with the legacy ONI
beside RONI; CPC's status; this week's Niño 3.4; the forecast peak and its 10 to
90% range; the effects this event puts in play and the watch list, each with a
place to show with a Show button that flies to its footprint and draws it, and
pressed again puts it away; and what every layer is and where it comes from. A piece that did not arrive this run is one sentence saying so.

### What a tap gives

Tap anywhere, or find a place, and *Here* adds to what the storms mean there:

- **El Niño here**: for each season, rainfall and temperature — the difference,
  the ordinary season it differs from (a percentage for rainfall only, and only
  where the ordinary season has at least 0.2 mm/day), |*t*| against what that
  season needs, and the verdict: wetter, drier, warmer, cooler, no clear signal,
  or no record. It is `atlas.sample`, cell for cell, and the verdict is
  `atlas.verdict`'s rule, so the dossier, the key and *Here* cannot disagree; the
  tests hold the page to Python at 798 points in every season for both
  variables, both sides of the date line and just west of Greenwich among them.
  Then the cell's size in kilometres, and the events sampled.
- **The documented effects** whose footprints take in the point, narrowest
  first, each marked in play or on the watch list for this event.
- **Today here, from NASA**, while the ocean or the flood layer is on: the value
  or the class at that pixel.
- **Google Maps here**, as above.

It is the record of past events, not this season's forecast: what the El Niño
seasons since 1979 (RONI +1.0 or more) did against the neutral ones (RONI
within 0.5). The forecast is CPC's and the national services' outlooks.

### Streets and addresses

The search box finds a town, region, country or position from the page's own
gazetteer as you type, and sends nothing anywhere doing it. Its last row offers
**Search streets and addresses for "…"**, and only when that row is chosen are
the words sent: to Esri's World Geocoder, `findAddressCandidates`, as
`SingleLine`, six candidates at most, with no key and no `forStorage`, so the
answer is shown and not kept. Each candidate flies to its extent — the short way
round across the date line — as close as the street map goes, and switches
NASA's imagery for the street map, because no GIBS layer shows a street. If the
geocoder does not answer, offline or blocked, the note says so and the
gazetteer still works.

### Then and now: entering a place

The **Enter** figure in the toolbar drops into a place as Google's Pegman does:
drag it onto the map and let go, or press it and tap a place (Enter takes the
middle of the view, Esc stops waiting; let go over a control on the map and it
enters nowhere); *Here* offers **Enter here** for the point it shows. The map flies to the place at its source's own zoom and shows
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
episode with its peak since March 2000, its developing year (a year before the
peak against the peak) and its decaying year (the peak against a year after),
each named for its episode. Each side's date can also be typed (a day from 1
January 2000 to today; a day before that or still to come is said in the bar
and not taken, and a date typed earlier than the other side's changes places
with it and the bar says so), stepped with ◀ and ▶ to the previous or next time
its archive holds, or set by tapping the RONI strip, which moves the nearer side
to the 15th of that month. A date outside an
archive is brought to its nearest end, and the bar says so; when an event's two
dates land on the same image or capture and an older one exists, the left side
steps back one, and the bar says why. Every date carries the season's words as
the tracker's own index gives them: "OND 2015, centred on Nov 2015: RONI +2.6,
very strong El Niño, the 2014-16 episode". A new run taken while a place is
entered (*The live site*) moves sides set from the event menu to that run's
dates for the event: a year ago against the latest moves on each day, and an
episode's peak while it is still rising. Dates that stand, the reader's own
among them, have NASA asked again for their days (the times GIBS lists, and the
days with a Landsat or Sentinel-2 image at the pin), so the latest is the
latest; the sides stand as they are meanwhile, words and reading too, until an
answer moves one, and no answer leaves them. Esri's captures stay as they were
found. The event menu is written again only when the new run changes it, so one
open stays open.

Esri's archive is read as Esri's own Wayback app reads it. The release list
(`waybackconfig.json`) comes first; then the release tilemap
(`MapServer/tilemap/{release}/{z}/{y}/{x}`) is walked back from the newest
release, each answer naming the release the tile under the pin last changed
in, so only the versions that differ at the pin are visited. Each version is
dated by its capture (day, resolution, sensor and provider at the pin) where
its release's metadata service answers within 20 s, and by its release
otherwise, and each is credited in its release's own words. The sides are
drawn once every capture has answered or 3 s after the walk, whichever comes
first; a version still waiting goes by its release until its capture comes.
Past zoom 13, where Esri holds no tile at a zoom (open water at zoom 17, say),
the nearest coarser tile is drawn and the pill says so.

For vegetation and the ocean, the bar reads each side's value at the pin from
the tile the map draws, its colour looked up bin for bin in NASA's colour map,
and gives both and the change: "At the pin, left: +0.3 to +0.4 °C; right: +2.0
to +2.1 °C; a change of about +1.7 °C." The key under the map shows that colour
map. A clear pixel is no data: land, ice or a gap for the ocean, water, cloud
or a gap for vegetation. For the imagery it names each side's capture or day.

While a place is entered, the storm picked stays, with its track, forecast,
cone and winds, the slider and **Play**, and the key to its marks, so its
forecast can be played out over the place. The rest of what belongs to today is
not drawn: the other storms and the key to them, the outlook areas, NASA's
reference overlays, the ocean and flood tiles and the El Niño composite. Esri's
roads and place names can go over either side. The status line says when NASA GIBS or Esri's archive did not answer, or
answered only in part, and Retry asks again; offline, the pill says the source
needs the network, and what is drawn stays. **Copy link** (once both sides are
found) gives
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

Offline, the page still draws the coastline, every storm, the composites, the
impact regions and the Niño boxes, all of which ship in the page, and says which
layers need the network instead of leaving grey rectangles. The map is **not a
forecast** of this season; the composite is what past events did. It shows
nothing as finer than its data: a composite cell is labelled with its size from
zoom 7, and NASA's 1 km and 250 m layers hide before a pixel fills the view.
And **nothing on it changes what a storm does**: storms cannot be steered or
stopped, as section 10 sets out.

---

## Composite power index

**A derived diagnostic of this tracker, not a NOAA product.** It exists to answer
"how big is this thing overall" in one number, and its inputs are published so it
can be audited or ignored:

```
power = 0.40 × amplitude + 0.25 × coupling + 0.20 × basin_scale + 0.15 × momentum
```

- **amplitude** — the official index, RONI, scaled so +2.5 °C reads as 100: a
  level RONI has not reached since 1950, its record season being +2.4 in
  1982-83. Averaging in the legacy ONI would put back the tropical-mean warming
  the official index exists to take out.
- **coupling** — mean of the SOI and MEI components, each scaled so a magnitude
  of 2.0 reads as 100.
- **basin_scale** — mean anomaly across the four Niño regions, relative where
  CPC publishes the relative series, scaled so a basin-wide +2.0 °C reads as 100. *Saturates at 100; above a basin-wide +2.0 °C
  it stops discriminating.*
- **momentum** — rate of change, where ±0.5 °C per season spans the full range.

Bands: Minimal <25, Low 25-40, Moderate 40-55, High 55-70, Very High 70-85,
Extreme ≥85.

---

## Data sources

All 43 feeds are fetched live on every run, in parallel, and archived under
`data/raw/archive/` with a daily snapshot, so past readings stay auditable. The
cyclone decks and products are a second wave on top of that — three ATCF decks and
up to five NHC products for each NHC or CPHC storm, one warning for each JTWC
storm — and which storms exist is not known until the first wave lands.

### Index feeds (26)

| Feed | What it is for |
|---|---|
| [`RONI.ascii.txt`](https://www.cpc.ncep.noaa.gov/data/indices/RONI.ascii.txt) | the official index since February 2026 |
| [`oni.ascii.txt`](https://www.cpc.ncep.noaa.gov/data/indices/oni.ascii.txt) | the legacy index, kept for comparison with the record |
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

### Cyclone feeds (9, plus a second wave per live storm)

| Feed | What it is for |
|---|---|
| [NHC active cyclones](https://www.nhc.noaa.gov/CurrentStorms.json) | which systems are live right now, with their ATCF ids and their products' links |
| [ATCF best-track listing](https://ftp.nhc.noaa.gov/atcf/btk/) | the directory, so a storm that has dropped off the active list is still reachable |
| [HURDAT2](https://www.nhc.noaa.gov/data/hurdat/) | the 1851- best-track archive, for date-matched climatology and the El Niño composite |
| NHC outlook, [Atlantic](https://www.nhc.noaa.gov/xgtwo/gtwo_atl.kmz) / [east Pacific](https://www.nhc.noaa.gov/xgtwo/gtwo_pac.kmz) / [central Pacific](https://www.nhc.noaa.gov/xgtwo/gtwo_cpac.kmz) | the formation areas and their 2- and 7-day chances |
| [JTWC RSS](https://www.metoc.navy.mil/jtwc/rss/jtwc.rss) | JTWC's live warnings, and the links to their `.tcw` files |
| JTWC significant tropical weather, [west Pacific](https://www.metoc.navy.mil/jtwc/products/abpwweb.txt) / [Indian Ocean](https://www.metoc.navy.mil/jtwc/products/abioweb.txt) | disturbances and their 24-hour potential |
| JTWC formation alert, a `.tcw` in ATCF's "ALERT" format the RSS feed links | the alert's area, its valid time, and the system's motion, winds and pressure |

| Second wave, per live storm | What it is for |
|---|---|
| ATCF b-, f- and a-deck | best track, official forecast, guidance (NHC and CPHC storms) |
| NHC watches and warnings, cone, peak surge (KMZ and KML) | the protective products, as the active-storm index links them |
| NHC wind speed probabilities (text) | the official chance of each wind at named places |
| JTWC `.tcw` warning | position, intensity, forecast and wind radii of a JTWC storm |

### Maps, imagery and search (the pages', not the run's)

The storm desk and the map ask for these from the browser, over https; a run
downloads none of them, and both pages still draw without them (sections 12 and
13).

| Source | What it is for | Terms |
|---|---|---|
| [NASA GIBS](https://nasa-gibs.github.io/gibs-api-docs/) | geostationary and polar imagery and its frame times; the MUR SST anomaly; MODIS's three-day floods; MODIS Terra's true colour and NDVI and HLS's 30 m passes, for then and now | keyless, public domain |
| [Esri World Street Map, World Imagery, World Topographic Map](https://server.arcgisonline.com/ArcGIS/rest/services/), with World Transportation and World Boundaries and Places | the map's streets, satellite and terrain | keyless; Esri Master License Agreement, credit shown on the map, not for use offline |
| [Esri World Geocoder](https://geocode.arcgis.com/arcgis/rest/services/World/GeocodeServer/findAddressCandidates) | streets and addresses, only when the reader asks | keyless; not stored (no `forStorage`) |
| [Esri World Imagery Wayback](https://livingatlas.arcgis.com/wayback/): `waybackconfig.json`, the release tilemaps and metadata services, each release's item | then and now: the archive's releases, the versions of a place and when each was taken, each release's credit | keyless; Esri Master License Agreement, as World Imagery; not for use offline |
| [OpenStreetMap](https://tile.openstreetmap.org/) | the standard map, when the page is served | OSM's tile usage policy; © OpenStreetMap contributors |
| Google's embed and [Maps URLs](https://developers.google.com/maps/documentation/urls/get-started) | Google's own map, satellite view and Street View of a point, on request | no key; Google's own frame |

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
daily; the Diagnostic Discussion is issued on the second Thursday. For the ENSO
state alone, running more often than daily gains nothing. The tropical cyclone
products change faster: advisories every six hours with intermediates between,
outlooks four times a day, JTWC's warnings six-hourly. That is why the site runs
every hour (*The live site*); `--watch` refuses only intervals under 15 minutes,
which would be load on NOAA for nothing new.

If a feed is unreachable the tracker falls back to the last cached copy and says
so, in the report, in the dashboard's provenance panel, and in the exit code
(3 = degraded). It only fails hard if neither RONI nor ONI is available, live or
cached. Cached copies are stored with LF line endings and written without
translation: through Windows text mode every CRLF a feed sent became CR CR LF,
which read back as two lines, and the archive's digest, taken over the text,
never matched the translated file, so every snapshot was rewritten on every run.

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
track.py                 CLI entry point, exit codes, watch loop, storm desk server
publish.py               puts output/ up as the site on GitHub Pages, under the site's name
publish.sh               runs the tracker, then publishes the run: what the hourly run calls
.github/workflows/       live.yml, the hourly run that keeps the site live; tests.yml
elnino/sources.py        43-feed registry, parallel fetch, retry, cache + archive
elnino/parsers.py        one parser per NOAA format, each with its quirks documented
elnino/classify.py       episodes, ranking, scale, flavour, analogs, power index
elnino/subsurface.py     WWV ranking, tendency, measured lead, phase-space position
elnino/atmosphere.py     10 indicators, Walker composite, bursts, MJO, coupling
elnino/forecast.py       analog ensemble, nonlinear recharge oscillator, persistence
elnino/verification.py   cross-validated hindcast of all three methods, barrier, weights
elnino/impacts.py        28 teleconnections, gated on intensity and flavour
elnino/geo.py            where each of those 28 lands, as lon/lat boxes
elnino/cyclones.py       ATCF decks, ACE, categories, landfall gazetteer, climatology
elnino/kml.py            KML and KMZ: placemarks, extended data, simplification
elnino/tcproducts.py     NHC's watches and warnings, cone, surge, wind probabilities
elnino/jtwc.py           JTWC warnings and disturbances, as storms and areas
elnino/outlook.py        formation outlooks across the centres, invests, who warns where
elnino/exposure.py       wind arrival times at places; satellite zenith and parallax
elnino/alerts.py         threshold and change rules, reconciled against the last run
elnino/history.py        13 catalogued historical events
elnino/storage.py        SQLite: snapshots, series revisions, alerts, feed health
elnino/pipeline.py       one run: fetch -> parse -> diagnose -> forecast -> alert
elnino/grids.py          ERDDAP CSV -> gridded fields, sections, profiles, meshes
elnino/coastline.py      Natural Earth 10m coastline, four levels of detail
elnino/report.py         78-column ASCII terminal report, section-addressable
elnino/svg.py            validated palette and plotting primitives
elnino/panels.py         the advanced chart panels
elnino/fields.py         maps, Hovmöller diagrams and depth sections
elnino/space3d.py        orthographic 3-D: thermocline surface and phase spiral
elnino/globe.py          the interactive globe, the storm overlay, the dossier
elnino/atlas.py          the point dossier: cell, statistic, footprints, neighbours
elnino/atlasdata.py      Natural Earth borders, rivers, lakes, 7,342-place gazetteer
elnino/atlasview.py      the atlas page: pan, zoom, click, and the dashboard card
elnino/composite.py      the vendored El Nino minus neutral grids, diff / t / base
elnino/relief.py         vendored ETOPO1: land height and sea-floor depth, 0.25 deg
tools/                   one-off vendoring: composites, coastline, gazetteer, relief
elnino/stormfury.py      the STORMFURY recreation: criteria, momentum, confound
elnino/storms.py         the three cyclone cards: tracks, season verdict, STORMFURY
elnino/dashboard.py      self-contained HTML + inline SVG, and the JSON payload
elnino/live.py           pages that follow the site: run.json, each page's run and code, the follower
elnino/sitenav.py        the site's menu: the four pages, the first thing on each
elnino/stormdesk.py      the storm desk: live imagery, products, find, here, close in
elnino/worldmap.py       the map: street maps, El Nino's composites and tiles, El Nino now,
                         what a point is told, Google on request, the geocoder
elnino/thennow.py        then and now: its sources, every month's RONI season, the events,
                         the bar, and the script that enters a place and compares two dates
tests/                   1227 tests over parsers, numerics, grids, renderers, a full run
data/raw/                cached downloads + dated archive
data/elnino.db           run history, revisions, alert state
output/                  dashboard.html, atlas.html, storms.html, map.html, latest.json,
                         storms.json, run.json
```

`output/latest.json` (schema 9) is the machine-readable snapshot: classification,
every diagnostic behind it, the spatial block (each field's stamp, age and
coverage; the map-derived box means; the warm-pool edge; the isotherm profile),
the forecast with its verified error bars, open alerts, active impacts, and the
health of every feed. Schema 4 added `footprints`: the same 28 teleconnections
keyed by coordinate, so a consumer can answer "what does this event do at my
location" without the dashboard. Schema 5 adds `cyclones`: every live storm with
its fixes, official forecast and derived quantities, and the per-basin season
scored against date-matched climatology. Schema 6 adds `stormfury`: the verdict
and its three reasons, the criteria per live storm with each one's pass/fail/
unknown and its detail, the momentum table, every natural eyewall relocation with
what the hypothesis predicted beside what the storm did, and the unseeded-swing
distribution — enough to re-derive the whole argument without this code.
Schema 7 adds `atlas`: the composite method and its sample sizes, and for each
anchor point the four seasonal differences with their neutral means and Welch's
*t*. Rainfall carries `percent_of_normal` and temperature does not, because a
percentage of a temperature is arithmetic on an interval scale.

Schema 8 follows RONI becoming the official index. `index` is the official
index — name, season, value, tier — and `ranking` ranks it; `oni` is the legacy
index and is `null` when its file did not arrive. `scale` says whether the
region anomalies are relative or traditional. The forecast carries the method
`weights` it combined with, and `skill` says whether `useful_horizon_months` is a
lower bound (`useful_horizon_is_lower_bound`). An alert that rose a level
carries `escalated_from`. Impacts carry `threshold`, on the official index, where
they carried `oni_threshold`, and `impacts_watch` lists the links below the
outlook's bar with the peak each one `needs`. The atlas block carries per-season
`samples` — events, months, neutral years and the |*t*| needed — in place of one
significance threshold, each cell's `t_needed`, and the event left out as
`in_progress`.

Schema 9 adds `outlook`, NHC's and JTWC's formation areas as the storm desk carries
them — centre, basin, chances or potential, and the area — and `storm_desk`, the
page and data file the run wrote beside it and the data file's own schema.
`cyclones.active` now carries JTWC's storms beside NHC's and CPHC's, and
`cyclones.upgrades` says which invests have been numbered since their last fix;
it is news, kept apart from `cyclones.notes`, which are problems and make the
run a degraded one. The storm
desk's own data file is `output/storms.json`, described in section 12.
`output/run.json`, written after every other file of a run, names that run and
nothing else: an open page asks for it to learn whether the site has a newer one
(*The live site*).

A value that could not be computed is `null` rather than absent, so a consumer
never has to distinguish "missing" from "not applicable".

---

## Scheduling a daily refresh

The published site needs none of this: GitHub refreshes it every hour (*The live
site*). On this machine nothing is set up automatically. To have Windows refresh it
every morning at 07:30, from a Command Prompt (the quoting is cmd's, not
PowerShell's):

```bat
schtasks /create /tn "El Nino Tracker" /tr "\"%LOCALAPPDATA%\Programs\Python\Python310\python.exe\" \"%USERPROFILE%\Desktop\elnino-tracker\track.py\" --quiet" /sc daily /st 07:30
```

Adjust the Python path to match `where python`. To publish this machine's runs
as well, have the task run `publish.bat /scheduled` instead, which runs the
tracker, publishes the run and never waits for a key (`/f` replaces the task
above); a run older than the one the site shows is not published over it:

```bat
schtasks /create /f /tn "El Nino Tracker" /tr "\"%USERPROFILE%\Desktop\elnino-tracker\publish.bat\" /scheduled" /sc daily /st 07:30
```

`publish.bat` runs the `python` that `where python` finds first.

---

## Publishing the site

The pages are published at **<https://villaketh.github.io/elnino-tracker/>**: the
dashboard, with the storm desk, the map, the atlas, both JSON files and the run's
`run.json` beside it, served by GitHub Pages from this repository's `gh-pages`
branch. GitHub puts each hour's run there (*The live site*); to put this
machine's last run there:

```
python publish.py                 # publish the pages output/ holds now
python publish.py --dry-run       # lay the site out and check it; push nothing
python publish.py --allow-older   # publish even though the site shows a later run
```

or double-click **`publish.bat`**, which runs the tracker and then publishes it
(`./publish.sh` is its twin for Linux and macOS, and what the hourly run calls). A
run with open alerts (exit 1) or failed feeds (exit 3) is published, and its pages
say so; a run that could not happen publishes nothing. `publish.bat` exits with
the run's own code once it is published, 2 when the tracker did not run, and 4
when it ran but publishing failed; `publish.bat /scheduled` does the same without
waiting for a key, for Task Scheduler (see *Scheduling a daily refresh*).

Each publish replaces `gh-pages` with one commit holding exactly that run's pages,
byte for byte, as `output/` keeps no history either. The commit is made under the
site's own name and GitHub no-reply address, never this machine's git identity,
in a repository sealed off from this machine's git setup, so no personal address,
hook, signature or ignore rule reaches the public repository. Before anything is
pushed, the publish refuses a run with a page missing, empty, cut off or
unreadable; a page naming this machine's home folder in any spelling (either
slash, any case, %-escaped, with or without the drive); a page of another run
than latest.json's, or naming none (each page names its run in its head,
`storms.json` and `run.json` under keys of their own, all compared as moments),
so the site is always one run and no open page loads again for a run it can
never find; and a run older than the one the site already shows, unless
`--allow-older` says so. `main` and `master` are never published over. The push
goes only over HTTPS (an address, or an `insteadOf` rewrite, that turns it to SSH
or anything else is refused), with the credential git has for GitHub
(`gh auth setup-git` hands it the GitHub CLI's login), so the account
`gh auth status` shows must be able to write to the repository; without a
credential the push fails at once rather than waiting on a password prompt.
GitHub serves the new pages a minute or two after the push.

Served from GitHub, the pages draw everything the local ones do (*Maps, imagery
and search*, under *Data sources*), OpenStreetMap included, which refuses a page
opened from a file. The site's data are the last run's: the imagery under the
storms is live, but the storms, the outlooks and the ENSO state are as that run
found them, within the hour while the hourly run keeps up, and each page says
when that was.

---

## The live site

GitHub runs the tracker every hour and publishes the run, so the site is never
much more than an hour, plus GitHub's queue, behind the feeds
(`.github/workflows/live.yml`):

- **The run.** At twelve minutes past each hour (the products land on the hour,
  and GitHub queues scheduled runs longest at the top of it), on every push to
  `main`, and on request. GitHub may hold a scheduled run under load, or drop
  it, as it dropped the first of all, so 42 past is a second chance: it asks
  when `gh-pages` was last published and stands down if that was under 45
  minutes ago, running on any doubt. One runs at a time. Each calls
  `./publish.sh`, which runs `track.py --brief` and then publishes the run with
  `publish.py`, its refusals and all, under the run's own short-lived token.
- **The state.** `data/elnino.db` and the cached downloads are carried from one
  run to the next in the Actions cache, so the alerts are reconciled against the
  last run and a failed feed falls back on its last copy. The dated archive is
  left out: nothing reads it back. GitHub drops a cache unused for seven days, so
  after a longer gap the next run starts afresh: every open alert reads as new,
  and no feed has a copy to fall back on for that run.
- **Pages that follow it.** Every page names its run, and the code that wrote
  it, in its head and asks the site for `run.json` each minute, and at once when
  it is shown again or the browser is back online. The storm desk and the map
  take a newer run in place, keeping the view and the panel as the reader left
  it: the part being read, a storm's row among them, held where it stood on the
  screen as the page settles, for 15 seconds at most or until the reader's own
  hand is on the page (the browser's own scroll anchoring loses the nodes a take
  swaps, and Safari before 27 has none; a panel or a page at its top is left to
  show what comes in there, as a browser leaves it), each storm's tab, the
  tables open or shut and the focus, in *Here* too, the region shown, and
  *Here*, whose Google frame is not loaded again (Street View stays where the
  reader walked it), whose readings of NASA's tiles stand, and whose place a
  screen reader hears once, not with every run. The dashboard and the atlas load
  again: at once in a tab that is not shown; otherwise once the reader has left
  the page alone for two minutes, saying meanwhile that a newer run is in, with
  **Update now**, and **Later**, which keeps the page as it is until the run
  after. So do the storm desk and the map for a run another code wrote (pushed
  since the page was opened: its markup and data are not the open page's script
  to read), and for each run after it, and for a run whose take failed part way,
  which leaves the page between two runs and so is offered without **Later**.
  They come back where the reader was: the scroll, the theme and the open
  sections, and the part being read, put back where it stood and held there
  while what is above it comes in (on the dashboard, the card); on the atlas
  also the view, the point picked, the variable, the season and the layers; on
  the desk and the map also the view, the layers, the comparison and the loop,
  the hour and the day, the overlays, El Niño's map, *Here* and its Google
  frame, the place entered in then and now on its event, with the address it was
  opened from, and the storm and its tab. Each says for a few seconds which run
  it now shows, and a tab loaded while hidden holds its place from when it is
  shown. A run that does not arrive is tried again after 2, 5 and 10 minutes,
  then every 15. A run older than the page's own (a cache the site's move has
  not reached yet, or a run put back with `--allow-older`) is never taken,
  whether `run.json` names it or the page read again holds it. A browser that
  keeps no session storage, or a reader saving data (Data Saver), is only ever
  offered the update.

Run it now from the Actions tab (*Live site*, then *Run workflow*) or with
`gh workflow run live.yml`; pause it with *Disable workflow* there, or with
`gh workflow disable live.yml`. A run that could not happen or could not publish
fails, and GitHub notifies the repository's owner; the site keeps its last run.
A run with open alerts or failed feeds is published, with a notice or a warning
on the run, as its pages say. GitHub pauses the schedules of a public repository
after 60 days without activity: each scheduled run enables its own workflow
again, which keeps that pause off, and should it ever be paused, the Actions tab
turns it back on.

On this machine, `python track.py --serve --watch` does the same for a tablet: a
run every hour, and served pages that follow it.

---

## Tests

```
python -m unittest discover -s tests -v
```

1227 tests, no network required. They cover:

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
- **the calendar analogs**: members are the same season of other years ranked by
  likeness, a hindcast start holds out its neighbours, a winter start is named
  for its winter, the hindcast scores the analogs and weights every method by the
  inverse of its own error, and the member tracks drawn are the ones in the band;
- **the numbers as CPC prints them**: one decimal, ties away from zero, taken
  through the decimal representation so that 0.15 prints 0.2 as CPC's does and
  not 0.1 as a binary `round` would;
- **the words on the page**: every unit written as its sign (°C, σ, × 10¹⁴ m³),
  no count printed with a lazy "(s)" plural, no signed zero on an axis, words
  aligned left and numbers right in every table with sentences wrapped, and
  chart labels placed clear of each other and of the lines they annotate;
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
- **the cyclone decks**: hemisphere-lettered tenths parse to signed degrees,
  a gzipped a-deck is read, `OFCL` is picked out of forty interleaved techs and
  the ensemble members matched separately, ACE counts only six-hourly warm-core
  fixes at 34 kt or above — an intermediate landfall fix, a post-tropical one, a
  sub-gale one and a forecast one are each present in the fixture and each
  excluded — rapid intensification is measured over a true 24 hours rather than
  over four rows, category floors land on the Saffir-Simpson boundaries exactly,
  each forecast point is marked as NHC's track graphic marks it (a category's
  number, else NHC's letter for its wind, drawn open where the system is not a
  tropical cyclone, never a category for a subtropical storm, nothing without a
  wind), the forecast's peak is its first
  strongest point, and a storm crossing 140W under two ids is one storm;
- **the season verdict**: climatology is cut at the same calendar date rather
  than compared against a full-season normal, a year with no storms is a zero
  and not a gap, and the El Niño composite excludes the year being scored;
- **the storm overlay**: tracks project onto the globe and cull with it, a
  forecast track is drawn dashed and distinctly from the observed one, and a
  chip's status colour never travels without its label;
- **the track map**: each member a curve in its storm's colour from where the
  storm is now, cut where each day of lead ends and fainter with each, nothing
  past the horizon; the curve through every point, never looping on a short
  step beside a long one nor dividing by a point given twice; the best track a
  line with a bead at each synoptic fix and one marker, now, the size of its
  category; each forecast point badged with its category where the badge
  clears the storm's marker and the other badges, lettered by its wind and
  dashed where it is not a tropical cyclone, and no label over a badge; the
  card saying what each mark is, the ensemble's members or the models'
  guidance as the decks carried them; and the globe's spread in its storm's
  colour, its keys in the legend's ink;
- **level of detail**: the visible-cap radius matches a hand-computed
  orthographic window, the stride keeps the visible cell count under budget at
  every zoom, a coastline level is a strict subset of the level below it — which
  is what makes one array with a level digit equivalent to four copies — the
  Python and JavaScript unpackers return identical geometry, and a merged run
  never spans more than 6°;
- **the STORMFURY recreation**: relocation reduces to pure `1/r` at the equator
  and the planetary term bites equally hard on both sides of it, a relocation too
  large for the momentum budget reports nothing rather than a negative wind, a
  30 kt system and a 65 nm wind maximum are both refused an eyewall, a
  hurricane that passes every other rule is still blocked by the trigger, a
  depression's genesis is not counted as an intensity swing, an RMW that
  quintuples between two analyses is a re-analysis and not a relocation, and a
  card with no decks behind it omits the two evidence blocks rather than
  printing a conclusion over an empty table;
- **the atlas tier**: every composite plane decodes to the shape its axes
  claim, a difference and its statistic are missing in exactly the same cells so
  no cell is ever drawn as certain without one, the surface-temperature baseline
  is Celsius and not the Kelvin the source publishes, a longitude past the
  dateline resolves to the same cell as its western twin, the Maritime Continent
  drought and the coastal Ecuador flooding both come back out of the grids, a
  percentage is refused where an ordinary year is under 0.2 mm/day, a storm with
  no analysis fix is skipped rather than crashing the map, vector detail never
  drops as the level rises, and the page requests nothing *in order to draw
  itself*; the composite is painted as a field, every pixel the blend of the
  cell centres around its point in the atlas's own colour step and nothing
  beyond the poles, by the same functions the map runs; the dashed outline of a
  clicked cell is drawn where the point is across the date line, while any of
  the cell is on the page though its point is not, and not at all once the
  cell is wider or taller than the page; a tap beyond the poles opens nothing
  and the readout there is a dash,
  a longitude is taken into one turn of the world, and a new field or season
  answers the marked point again; the field holds still on the ground as the
  view pans, is held to the size the map was measured at, moves with the
  ground under a gesture and gives way over imagery; the page is measured again
  whenever the map's box changes; a press on +, − or Fit is the button's, not
  the start of a drag; and either theme switch reads the ramp again;
- **the physical tier**: the relief PNG is two stacked eight-bit planes of
  exactly the declared size, the grid decodes to one elevation a cell, its
  extremes are the ones the generator recorded, and eight spot checks land in
  the range the world says they should — Everest massif, Mariana Trench,
  central Pacific floor, Sahara, Amazon lowland, Dead Sea rift, Arctic Ocean,
  East Antarctic ice sheet — with a longitude past the dateline resolving to
  its western twin;
- **the imagery geometry**: NASA's nine published matrix sizes come back out of
  the 288° top level, the matrix covers the world with less than a tile to
  spare, the top levels end in a partial tile (which is why a column cannot be
  taken modulo the matrix width), every dated layer asks for a day that has
  finished processing, and the page carries that number and clips the padding;
- **the physical readout**: nothing in the page is a credential, every address
  it can reach is on a list of seven known public ones and all of them https,
  the elevation service is one that answers a browser with a CORS header, the
  measurement is offered only where there is land to measure, and the reader is
  told the cell is a landscape and not a street;
- **the diverging ramp**, checked as a diverging ramp and not as a categorical
  palette: the midpoint is the only neutral step, chroma falls to it and rises
  out of it, lightness is monotone from each end to the middle in whichever
  direction that mode's surface demands, and the two halves are two hues more
  than 100° apart rather than a rainbow;
- **the new cyclone sources**: a KMZ is read as its KML text; NHC's watches and
  warnings come out as coast segments by kind, the cone as a polygon, the surge
  areas with their depths, and the wind speed probabilities by place, wind and
  lead; JTWC's `.tcw` warnings become storms with their radii and its
  disturbances become areas, a formation alert (or its cancellation) is read
  from its prose and laid on its invest's area, a first warning that cancels
  an alert is still a warning and ends that alert, an alert with no issue time
  is kept and one past its time is said to have run out; a storm both centres list is NHC's; an
  invest that has been numbered is reported as the storm it became; and a low
  before genesis is a low, not a remnant;
- **the exposure rules**: the timeline is hourly from the latest analysis, centre
  and radii straight between forecast times; a radius the forecast does not give
  is unknown and never calm, while a place outside the gale field is outside the
  hurricane field; the quadrant follows the bearing from the centre; and a point
  a rounding error from a centre is at the centre;
- **the site's menu**: the first thing on every page, naming the four pages in
  one order with the reader's own marked (underlined where colours are
  forced), the site's name leading to the front page, and each page's main
  part a landmark past it; on the dashboard pinned, outside the part the
  follower holds a reader by; never squeezed on the pages laid out as a
  column, fitting a phone 320 px wide, every link 44 px high, and left off
  paper; its mark El Niño's warm tongue, and every page's icon; the desk and
  the map handing the view, the storm picked and the hour across through it;
  and a page the site does not have refused;
- **the storm desk**: its data survive a JSON round trip; each storm's
  longitudes stay within 180° of its centre across the date line; every imagery
  layer is named as GIBS's capabilities list it, and every reference overlay
  waits to be asked for; the search box is labelled and lists what it finds; the
  path carries the forecast centres unrounded, so that *Here* and the exposure
  table agree to the hour; each storm is named on the map for its wind at the
  hour shown as `short_label` names it, at every wind and stage, a low ahead
  named for whether the system will have formed by then, and each forecast
  point marked with its category where the mark clears every storm's marker,
  name and other marks (not the point three hours on, under the storm's own),
  drawn open where the system is not a tropical cyclone; Play runs the
  forecast to the end of the storm picked's, or every storm's with none picked,
  and stops, starts again from now at the end, holds when paused, is greyed
  with nothing to play, plays on for a storm picked meanwhile and takes turns
  with the satellite loop, the one started last running; an address followed
  stops it; a name every object answers to ("constructor") picks no storm, and
  a run with no storm left picks none; a storm forecast to strengthen says its
  peak in its row and its Now tab; and the dashboard links to the desk;
- **the map**: every street map is a keyless https tile address, to zoom 19,
  with a credit, and OpenStreetMap's is offered only to a served page; only
  Esri's grey placeholder is set aside for a coarser
  tile, never an empty street tile, sea, cloud or a failed load; the composites
  are drawn as a field, every pixel the blend of the cell centres around it in
  the atlas's colour step, worked out on no more than a quarter of a million
  points on a lattice that holds still on the ground as the view pans, in the
  theme's ramp after either switch, and read back as `atlas.sample` does at 798
  points, verdict and percentage included;
  NASA's SST and flood tiles read back through NASA's own colour maps; the Niño
  boxes cross the date line the short way; `#at=` and `#view=` accept a place
  or a view and nothing else; nothing goes to Google or the geocoder until asked
  for, and Google's links carry the zoom the view settles on; a street tile that
  failed is asked for again after a wait that doubles; Retry is offered whenever
  anything drawn needs NASA, and asks GIBS again whatever the base; a NASA frame
  whose tiles never came is said to be down, the coastline drawn and every
  failed tile asked for again on Retry, a failure that set its frame aside
  excepted; an Esri
  placeholder rules out every level under it and redraws the tiles, not the
  marks; the compare menu offers every layer it can show; a layer that needs
  the page served says so where it is pressed; the Towns switch says why its
  names are not drawn, and each side of the divider names towns for itself,
  none of them across it onto a map; each
  layer is drawn on its own side of the divider only, the satellite map's roads
  and names with it, and the status line says what the compared side shows; the
  credit line names the source of each layer drawn and of nothing else; a tap on
  any copy of the world flies the short way; a Niño box's name with no room
  above goes under the box; NASA's tiles have a strength of their own; the
  composite's field runs across the date line and Greenwich unbroken, fading
  out at the coast and where its cells stop passing the *t* test, and the cell
  on the date line reads as one cell from either side; the outline of the cell
  under the pin is drawn only while the cell fits the view, across and down;
  the impact regions wait to be ticked, Show draws its region alone and says
  so, pressed again puts it away, and is not offered for an effect true of
  everywhere; zoomed out, every copy of
  the world in view carries the geometry and the marks, as markup the page's
  stylesheet reaches, never as a copy made by an SVG `use` element; and both
  pages build with the index, the weeks, the forecast or the impacts missing;
- **then and now**: the season words for runs of every kind; the events for
  past, current and absent episodes; GIBS's times read, snapped and stepped
  across a year's seam and a gap; Esri's archive walked against a stubbed
  network (a chain of releases, a stop, a failure, a query given up after
  20 s); each side drawn at its own date, never at today's; entering and
  leaving putting the map back; the figure pressed, tapped and carried; the
  readouts' colour lookups and the key that shows their scale; the storm
  picked staying, its forecast and slider with it, and the key to its marks;
  Exit keeping Play, pressed while entered, over the loop that ran before;
  both sides of the date line; and the address;
- **the server**: it refuses `..` however it is spelled, lists no directory,
  marks every page no-cache, answers `/` with the desk, names the map's address
  beside it, and listens beyond this machine only when `--lan` says so;
- **publishing**, against a local bare repository (skipped without git): the site
  opens on the dashboard, carries `.nojekyll` and goes up byte for byte; the
  commit is made under the site's name whatever git identity this machine sets,
  and none of this machine's hooks, signing, commit encoding, ignore rules or git
  environment reaches it; each publish leaves one commit and names its run; `main`
  and `master` are never published over, and an address turned away from HTTPS is
  refused; a page missing, empty, cut off or unreadable, a `latest.json` with no
  run time, or a page naming the home folder in any of its spellings stops the
  publish with nothing pushed, while a folder only named like it does not; a run
  older than the site's needs `--allow-older`; `--dry-run` says which run it
  checked and pushes nothing; a refused publish exits 2; a page of another run,
  or naming none in its head or its own key, is refused, one moment written two
  ways is one run, and `run.json` goes up with the pages; `publish.bat` publishes
  exactly the runs that happened, exits 2 or 4 when the tracker or the publish
  failed, and never waits when scheduled; and `publish.sh` does the same under
  `sh`, passes its options on, and is committed executable with LF endings;
- **the live site**: `run.json` written after every other file of a run, and the
  run and the code each page names in its head (the code the same whatever the
  checkout's line endings); under node, with a fake clock, site, page and
  storage, a page that takes a new run in place and one that loads again for it
  (at once when hidden, after two minutes left alone when in view, at once on
  **Update now**, not for the run put off with **Later**, never on its own
  without storage or for a reader saving data), a page taking runs in place that
  loads for one it cannot take and offers each run after it, and one whose take
  failed part way offered with no Later, a page knowing a run its own code
  wrote, its place handed over and put back (the scroll, the theme before first
  paint, each section by its words, a box that scrolls itself once its sections
  are open, what stood at the top of the view, below what the page pins over it,
  put back where it stood and held as the page settles, until the view moves for
  anything else, however slowly, the reader's own hand is on the page or 15
  seconds have passed, a page or a box at its top left to show what comes in
  there, a hidden page holding its place once it is shown, junk refused, the
  browser's own scroll restoring left out of the follower's loads until the page
  loaded again has loaded and left to the browser for a page held by its scroll
  alone, and a load the browser never made given up when the page is shown
  again), the page's own state failing
  without stopping the following, a run that does not arrive gone for again
  after 2, 5, 10 and 15 minutes, a run older than the page's or than the one
  offered passed over, a take never started twice, answers that name no run
  passed over, a hand-over left in storage read like input, one run written two
  ways, a tab frozen for hours, and the beacon found beside any address; every
  page setting a theme handed over before it is styled; the desk's refresh
  loading for a run another code wrote, failing for a take that fails part way
  once its place is put back, passing over a copy no newer than its own, and
  naming the run it took and leaving the panel as the reader left it (*Here* and
  Google's frame in it never taken out of the page, *Here* keeping its tables
  and its focus, saying its place once in a line of its own and keeping its
  readings of NASA's tiles for their day and point, a failed one asked again,
  each storm's tab, each table open or shut by its section and words, the focus
  on the same control, the region shown still pressed, the reading under the map
  keeping its height, each storm's row named) and the reader's place held
  through it (the section being read put back where it stood, in a panel that
  scrolls itself or down a phone's page, by the box around it when the new run
  drops or hides it, a box below the top of the view left alone, the page drawn
  before the place is put back, and the place held as the page settles); the
  desk's and the map's place handed across a load (the view, the layers and the
  loop as the map's own while a place is entered, the loop run once GIBS gives
  its frames, on Exit too, the hour, the day stepped to, the overlays, El Niño's
  map, *Here* and its frame, then and now on its event and its names and the
  address it was entered from, the storm and its tabs) with junk refused, and a
  place the reader had left left though the address opened on it; then and now
  following the run (an event's sides moved to the new build's dates for it, an
  event no longer offered left as the reader's own dates, NASA asked again for
  the days that stand, quietly, the days with a Landsat or Sentinel-2 image
  looked for again, Esri's captures kept, and menus the new build left as they
  were not written again); the dashboard's run time ageing, and its body named
  to the follower, every part of it wearing an id of its own; the atlas's view
  and layers kept, junk refused and a view turned any number of times put back
  on the world; and the hourly run's schedule, token, state, remote, keep-alive,
  time limit and actions pinned to commits, no pull request starting it, and the
  suite's Python and node, read as text, and its second chance at 42 past, whose
  check runs under bash against a gh that answers or fails;
- **a full offline run** end to end, then every report section, the 78-column and
  ASCII-only guarantees, dashboard self-containment, a table view for every
  chart, all eight spatial panels and both cyclone cards reaching the page, the
  map-derived Niño-3.4 mean agreeing with the published index to within 1 °C,
  the terminal report and the dashboard quoting the *same* thermocline tilt, the
  *same* storm intensities and the *same* STORMFURY verdict, and a JSON payload
  that round-trips; then every page naming that run, the dashboard dated by it,
  and its pages published as one run naming no path of this machine.

If NOAA changes a format, these fail before a bad number reaches the dashboard.

The tests that run a page's script need node and are skipped without it; those
that read the downloads a run of `track.py` leaves in `data/raw/` are skipped on
a fresh checkout. GitHub runs the suite on every push to `main` and every pull
request, on Ubuntu with Python 3.12 and node 24 (`.github/workflows/tests.yml`).

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

Nine decisions worth stating because they look like omissions:

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
  likelihood gating depends on index thresholds and on EP/CP flavour, and a second
  copy of those rules in JavaScript would drift from the copy the terminal report
  uses. The inline script re-projects geometry and nothing else; every number it
  displays was computed by `impacts.evaluate`.
- **Resolution is spent on the field, not on the markup.** A half-degree
  Pacific map is forty-eight thousand cells, and the globe's field is nine
  hundred thousand. Three things make drawing them at their own resolution
  affordable rather than decimating them to something the page can carry.
  Horizontally adjacent cells in the same colour class merge into one run, which
  changes nothing about what is drawn because they were already the same colour.
  The runs of a class then accumulate into a **single `<path>`** rather than a
  rectangle each — eleven classes is eleven elements instead of thirty thousand,
  a third of the bytes and an order of magnitude off the browser's layout cost.
  And the per-element hints that made a rectangle expensive (`shape-rendering`,
  and the hover attributes) move to a group rule and a separate layer.
- **Hover targets are pooled to finger size, and report a range.** At half-degree
  spacing a Pacific map draws cells about two pixels wide, and nobody points at
  two pixels — least of all on a phone. Colour is drawn at the field's own
  resolution; hit areas are pooled to at least 11 pixels and each one reports the
  *range* of the cells under it, so the tooltip says "-0.3 to +0.1" where the
  field is not uniform and a single number where it is. Claiming one cell's value
  for an area the reader cannot actually point at would be the lie.
- **Detail is chosen per frame, not shipped per zoom.** The alternative to the
  level-of-detail machinery above was four copies of the coastline and a fixed
  grid stride. Four copies is three megabytes of duplicated world; a fixed stride
  is either a polygon at 10× or a stalled browser at 1×. Because Douglas-Peucker
  is hierarchical, one array with a level digit per point *is* the four copies,
  and because an orthographic window is computable, the stride can follow the
  zoom instead of being guessed. The page is 7.4 MB and still a single file with
  no network dependency — that is the cost, and it buys a coastline that resolves
  individual Hawaiian islands at full zoom rather than a four-point blob.

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
