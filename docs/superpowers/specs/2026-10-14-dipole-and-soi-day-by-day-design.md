# The dipole and the SOI day by day

Written 14 October 2026, under the user's "bro this needs to be real time as
soon as possible bro we need to track everything bro tf". Self-approved under
the user's standing rule to work without check-ins.

## 1. What the tracker lacks

The tracker's atmosphere is monthly: CPC's SOI, Darwin, Tahiti, OLR and the
trade-wind indices, each value a month's mean. The Southern Oscillation is
measured every day, and the Bureau of Meteorology quotes 30- and 90-day SOI
values; the tracker shows neither. And it has no Indian Ocean at all, though a
positive Indian Ocean Dipole often develops beside an El Nino in the austral
winter and spring, and with it changes what the El Nino does to Australia and
East Africa. The Nino boxes already go day by day from OISST
(`nino_daily`, `nino_daily_recent`); the dipole's poles are the same product
over other cells.

## 2. What the reader gets

**The Indian Ocean Dipole day by day** (`id="iod-daily"`), straight under the
Nino boxes' card. The Dipole Mode Index each day, the west pole's
area-weighted SST anomaly less the east pole's, with each pole's own line: the
final analysis's last 90 days, then the preliminary's days since, shaded, as
the Nino card has them. Lines at +0.4 and -0.4 degC, the Bureau's thresholds
for positive and negative IOD values. A caption with the latest DMI and its
change on the week, the day's analysis, how far behind it is past four days,
what the final changed in the DMI on the days both analyses carry, and the
base: OISST's own 1971-2000 climatology, a warming common to both poles
cancelling in their difference. A hover over every day with the DMI and the
poles; a table of every day, latest first.

**The SOI day by day** (`id="soi-daily"`), after the Walker circulation chart.
The 30-day SOI, the 90-day SOI and each day's own, faint, over the last 120
days. Lines at +7 and -7, the Bureau's thresholds for sustained La Nina-like
and El Nino-like values. A caption with the latest 30- and 90-day SOI, the
latest day, how far behind past four days, and what the SOI is: ten times the
standardised Tahiti less Darwin pressure difference, against 1933-1992. A
hover over every day with the three values and the day's Tahiti and Darwin
pressures; a table of the 120 days, latest first.

`latest.json` goes to schema 11 with both series; the text report gets both;
README describes both feeds, their traps and the schema.

## 3. Data

**The dipole.** West pole 50-70E, 10S-10N; east pole 90-110E, 10S-0 (Saji et
al. 1999, the Bureau's boxes). OISST v2.1 `anom` on half-degree cells, as the
Nino boxes are, over the rectangle holding both poles:
`[(-9.875):2:(9.625)][(50.125):2:(109.625)]`, 40 latitudes by 120 longitudes.
Measured on 13 October's preliminary field against all its quarter-degree
cells, half a degree puts the DMI 0.009 degC off the full grid and one degree
0.027 off; half a degree it is, as for the Nino boxes.
Two feeds, as the Nino boxes': `iod_daily`, the final's last 90 days
(`[last-89:1:last]`, about 19 MB), with NCEI's final behind CoastWatch's; and
`iod_daily_recent`, the preliminary's last 28 days (`[last-27:1:last]`, about
6 MB), with NCEI's preliminary windows behind CoastWatch's. Neither is
archived: each day's download repeats all but a day of the day before's, of a
product NOAA keeps every day of itself. Each pole's mean is
`daily_box_means`'s cos-weighted mean over the cells with a value; the DMI is
west less east on a day both poles have one. The final and the preliminary
are spliced as the Nino boxes are, and `revisions` measures what the final
changed in each pole and in the DMI on the days both carry.

**The SOI.** The Queensland Government's LongPaddock file
`https://data.longpaddock.qld.gov.au/SeasonalClimateOutlook/SouthernOscillationIndex/SOIDataFiles/DailySOI1933-1992Base.txt`:
a header `Year Day  Tahiti  Darwin     SOI`, then a row a day from 1 January
1999 to yesterday (10,148 rows, 341 kB on 14 October), the day given as its
year and its day of the year, the pressures in hPa. Two traps, both in the
file on 14 October:

- **A fill value.** 20 December 2015 has Darwin at -999.9 and an SOI of
  224.84. A row whose pressures are not both within 870-1090 hPa, the range
  of sea-level pressure ever observed, is left out: that day has no SOI.
- **A day given twice.** 2012's day 328 comes twice, with different values,
  and day 329 not at all. A day that is not later than the day before it is
  left out, so the first row stands and the record runs forward.

The 30- and 90-day SOI on a day are the means of the daily SOI over the 30
and 90 days to it, as LongPaddock and the Bureau quote them, when the window
lacks no more than five days and no more than three in a row (the WMO's 3/5
rule for a month's mean, kept for both windows); otherwise none. The file is
fetched whole each run and not archived: it holds every day since 1999
itself.

## 4. Code

- `sources.py`: `_IOD_CELLS`; `iod_daily`, `iod_daily_recent` (tier
  spatial) and `soi_daily` (tier atmosphere, `archive=False`); 49 feeds.
- `grids.py`: `IOD_BOXES` (`west`, `east`); `dipole(days)`, each day with
  `dmi` added where both poles have a value; `SpatialState.iod_daily` and
  `iod_revision`, and `available` counting the dipole.
- `parsers.py`: `SoiDay(day, tahiti, darwin, soi, soi30, soi90)` and
  `parse_daily_soi(text)`.
- `pipeline.py`: the dipole built as the Nino boxes are; `series["soi_daily"]`.
- `days.py`, new: series day by day. The Nino card's plot, generalised over a
  `Chart` (its lines, the first the one the caption leads with, its marks,
  its unit and digits, its floor), moves here from `fields.py` with
  `nino_daily_card`, whose page is unchanged byte for byte; `iod_daily_card`
  and `soi_daily_card` beside it.
- `dashboard.py`: the two cards placed; `latest.json` schema 11 with
  `spatial.iod_daily`, `spatial.iod_revision` and `atmosphere.soi_daily`.
- `report.py`: the dipole after the Nino boxes' days, the SOI in the
  atmosphere's section.
- README: what each card shows, the three feeds, the traps, schema 11, the
  tests, and the counts.

## 5. Tests

Feeds' addresses and servers; the poles' means and the DMI on a synthetic
field; splice and revision through `build_spatial`; the SOI parser on the
header, the fill, the repeated day, a day of the year past a year's end, and
the 3/5 rule; the Nino card byte for byte against its page before the move;
each new card's lines, marks, shading, hover, table, caption words and
emptiness; the JSON's new keys and schema; the report's lines.

## 6. Not in this change

Westerly wind bursts. No free near-real-time equatorial wind analysis is
readable without a GRIB decoder today: TAO's daily winds end 28 September,
NCEP/NCAR R1's daily averages at PSL end 17 March 2026 and R2's 28 February,
NCEI's blended near-real-time winds on CoastWatch's ERDDAP ended in March
2023, and UCAR's THREDDS keeps a week of GFS analyses, which a store of the
tracker's own could grow into a record. Reported to the user with the
options.
