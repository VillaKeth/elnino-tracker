# Westerly wind events day by day

Written 15 October 2026, under the user's "bro this needs to be real time as
soon as possible bro we need to track everything bro tf" and "keep going twin
lock in", after the westerly-wind-burst tracking offered on 15 October.
Self-approved under the user's standing rule to work without check-ins.

## 1. What the tracker lacks

The tracker's only westerly forcing is monthly: `atmosphere.detect_bursts`
counts months whose CPC 850 hPa western-Pacific trade index is strongly
westerly, and says itself that it is "not a true westerly wind burst: those
last days and need daily winds to resolve". Nothing in the tracker sees a
westerly wind event (WWE) as it happens, where it is, or how strong it is,
though WWEs are what launch the downwelling Kelvin waves that the Hovmoller
card then shows crossing the basin.

## 2. What the reader gets

**Westerly wind events day by day** (`id="wind-events"`), after the SOI day by
day, in the atmosphere's run of cards.

- A Hovmoller of the 10 m zonal wind anomaly averaged over 5S-5N, 120E-80W,
  a row a day for the last 180 days, time running down as on the other
  Hovmollers, westerly warm-coloured; each equatorial event (types W, C, E)
  outlined over its region's longitudes and its days; the date line dashed;
  a tick at each month.
- A chart of the three equatorial regions' smoothed anomaly day by day, with
  the +2 m/s threshold marked and each of their events shaded in its region's
  colour; a hover over every day.
- A table of every event in the 180 days, latest first, in all eight regions:
  type and region, first and last analysis past the threshold, duration,
  centre, the regional mean at the centre (Harrison and Vecchi's "maximum
  averaged anomaly"), the largest point anomaly in the region at the centre
  and where, the wind measure, and whether it overlapped another and counts
  as that one; an event still under way and one that began before the 180
  days say so.
- A caption: the product and its days, how far behind past four days; what
  is under way now (an event, with its day count and peak), or else the
  latest event, or none; runs past the threshold not yet three days long;
  the definition; the base; how the near-real-time product compares with the
  version the base is from and with TAO's moorings; and how these differ
  from the monthly westerly forcing on the coupling card.

`latest.json` goes to schema 12 with `spatial.wind_events`; the text report
gets the events after its monthly westerly forcing; an equatorial event
under way raises an INFO alert; README describes the feed, the method, the
vendored base and the schema.

## 3. Data

**The winds.** Remote Sensing Systems' Cross-Calibrated Multi-Platform
(CCMP) 10 m winds, version 2.1 near real time: a variational analysis of
satellite radiometer and scatterometer winds over NCEP's GFS 0.25-degree
background, no buoys, six-hourly on a quarter degree, from NOAA PIFSC's
OceanWatch ERDDAP (`ccmp-daily-v2-1-NRT`, despite the name six-hourly,
2015-01-16 to a day or two behind; 13 October 18Z on the 15th).
CoastWatch's copy of it stopped on 2 June 2026 and is no fallback. The feed
`wind_daily` asks `uwnd[last-718:2:last][(-14.625):9:(14.625)][(120.125):9:(279.875)]`:
the last 360 analyses, every other one back from the latest, which is 180
days twice a day 12 hours apart (06Z and 18Z while the dataset ends at 18Z);
and every ninth cell, 2.25 degrees apart, 14 latitudes from 14.625S to
14.625N, symmetric about the equator, by 72 longitudes from 120.125E to
279.875E. 362,880 rows, 16.8 MB of text, 3.2 MB gzipped on the wire, in 12 s
on 15 October. Not archived: each day's download repeats all but a day of the
day before's. The CCMP analysis has a value over land as over sea (no NaN in
the 15 October download); Harrison and Vecchi's ECMWF analysis did too, and
every cell counts.

**The base.** CCMP version 2.0's monthly means (`ccmp-monthly-v2-0`, the same
server, 1987-07 to 2019-04, over an ERA-Interim background) at the same
1008 cells, averaged by calendar month over 1991-2018, the 28 whole years of
version 2.0 inside the WMO's 1991-2020 normal. Vendored once by
`tools/vendor_winds.py` into `elnino/windclim.py` (integers in hundredths of
m/s, a line per latitude, as `composite.py` is), so a run asks nothing more
than the feed. At 72 analysis times both versions carry, 2016-01 to 2019-03,
the near-real-time product's regional means differ from version 2.0's by
0.20 m/s at most on average (NW; 0.12 at most in W, C and E), an order below
the threshold, and by 0.19-0.51 m/s rms analysis by analysis. Against TAO's
daily winds at its seven reporting equatorial moorings (165E to 95W), June to
September 2026, its daily zonal wind correlates at 0.88-0.95 mooring by
mooring; at 165E and 170W, westerly on average, it runs 0.7 m/s less westerly
than TAO's, and from 155W to 95W 0.2 m/s more easterly. TAO measures at 4 m
and CCMP is for 10 m: a neutral log profile, about 8%, leaves the east within
0.15 m/s and widens the west to 0.9 m/s. Both are measured in the scratch work
of this round and stated in README.

**The definition.** Harrison and Vecchi (1997; NOAA Tech. Memo. ERL
PMEL-109, Vecchi and Harrison 1997): eight regions of about 30 by 10
degrees; a WWE of type X is "any period of 3 or more days for which the 10-m
zonal wind anomaly, averaged over region X and smoothed by a three-point
triangle filter in time (half-power point at 2.75 days), exceeded 2 m/s",
on 12-hourly analyses, against a monthly climatology "linearly interpolated
in time" from mid-month. The regions, as McGregor et al. (2016) list them:
NW 5-15N 120-150E; N 5-15N 150-180E; NE 5-15N 180-150W; W 5S-5N 130-155E;
C 5S-5N 155E-180; E 5S-5N 180-150W; S 15-5S 150E-180; SE 15-5S 180-150W.
W and C are 25 degrees wide, not the memo's "about 30"; Chiodi, Harrison and
Vecchi (2014) give the equatorial three as 130E-155E, 155E-180 and 180-150W.

- Anomaly: each cell's analysis less its calendar month's mean, linearly
  interpolated between months' middles (a month's middle is half its length
  after its first instant).
- A region's anomaly at an analysis: the cosine-weighted mean over its
  cells; none when fewer than three quarters of its cells have a value.
- Smoothed: 1/4, 1/2, 1/4 over the analysis and the ones 12 hours either
  side; none where either is missing or not 12 hours away. The filter's
  response is 1/2 + 1/2 cos(2 pi f dt), half power at 5.49 dt, 2.75 days at
  12 hours: the memo's filter on 12-hourly analyses. The latest analysis is
  smoothed when the next one comes.
- An event: a run of consecutive smoothed analyses, each 12 hours after the
  last, every one above +2 m/s (strictly), at least 6 of them (3 days). Its
  duration is 12 hours an analysis, from the first meeting the criterion to
  the first not meeting it. Its centre is the analysis of the largest
  smoothed value (the first of equals); its maximum averaged anomaly that
  value; its maximum point anomaly the largest unsmoothed cell anomaly in
  the region at the centre; its wind measure the sum of its smoothed values
  times 12 hours, in metres (the memo's composites: 1.1-1.6 x 10^6 m).
- Overlap: two events in regions sharing more than half of the shorter of
  their facing edges, centred within 3 days of each other, overlap; each
  counts as the region of the largest maximum averaged anomaly among it and
  those it overlaps. The neighbours this gives: NW-N, N-NE, NW-W, N-C,
  NE-E, W-C, C-E, C-S, E-SE, S-SE (N-W and W-S share 5 degrees, no more).
- Under way: a run including the region's latest smoothed analysis. A run
  under way short of 6 analyses is building, said in the caption and the
  JSON, never counted.
- The window: a run including the first smoothed analysis began before the
  180 days and says so.
- Sustained: a run longer than any of Harrison and Vecchi's 351 events of
  1986-1995 (the memo's Table 1, the longest 32.5 days) is called a
  sustained westerly anomaly more than a burst in the caption, the report
  and the alert; it is still an event.
- Refused: a feed with no smoothed value in any region is refused (noted,
  no card), never read as no event; an analysis with no value at all is not
  read.
- The Hovmoller: a row a day, the mean of the day's analyses, two, or one on
  the window's first and last days when it ends at 00Z or 06Z.

## 4. Code

- `tools/vendor_winds.py` writes `elnino/windclim.py`: `LATS`, `LONS`,
  `SCALE`, `BASE = "1991-2018"`, `PRODUCT`, and `U_<MON>` blocks; parsed at
  import into `MONTHLY[month][lat][lon]` (float or None).
- `elnino/winds.py` (new): `Region` and `REGIONS`; `neighbours(a, b)`;
  `read(text)`; `climate(time)` (the interpolated grid); `Event`,
  `Building`, `Winds`; `regional`, `smooth`, `runs`, `events`, `overlaps`,
  `band(…)` (the Hovmoller `grids.Field`); `analyse(text) -> Winds`.
- `sources.py`: `CCMP_NRT`, `_WIND_DAYS`, `_WIND_CELLS`; `wind_daily` (tier
  spatial, `archive=False`); 50 feeds; the docstring names Remote Sensing
  Systems and PIFSC.
- `grids.SpatialState.winds`; `pipeline.build_spatial` builds it with
  `attempt`, so a broken answer costs only the card.
- `fields.hovmoller(…, outlines=(), months=QUARTERS)`: outlined rectangles
  with a type letter, and month ticks; `daily._plot(…, bands=())`: shaded
  day spans; `daily.WINDS` chart and `daily.wind_card(winds)`.
- `dashboard`: the card after the SOI's; `spatial.wind_events` in
  `latest.json`, schema 12.
- `report`: the events after "Westerly forcing".
- `alerts.wind_rules(winds)` from `evaluate(…, winds=None)`: INFO
  `wwe_<type>` for an equatorial event under way.

## 5. Tests (tests/test_winds.py, beside the others)

The vendored base's axes are the feed's cells; its parse; land and sea both
valued. Regions and neighbours from geometry. Interpolation at a month's
middle is the month, halfway is the mean, across the year's end. Region means
cosine-weighted and refused short of three quarters. The filter's weights
and its half power at 2.75 days. Events: a run of 6 counts and of 5 does
not; strictly above 2; a gap breaks a run; the centre, peaks, point and
measure; under way and from the start; building. Overlaps: neighbours
centred within 3 days count as the stronger; 4 days apart do not; non
neighbours do not. The Hovmoller's rows, band mean and outlines. The source's
query, tier, archive flag. The pipeline builds the card and a broken answer
costs only itself. The card: lines, mark, bands, hovers, caption parts,
table, building, the behind chip, nothing under two days. JSON schema 12 and
the block. The report's lines. The alert for an equatorial event under way
and none for an off-equatorial one or a finished one.

## 6. Out of scope

A faster cadence (a new recurring trigger needs the user's explicit yes);
MJO phase at each event; easterly wind surges; regions east of 150W (the
Hovmoller shows them, the definition stops there); a land mask.
