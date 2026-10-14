# Hurricanes on the street

Written 14 October 2026, from the user's question: "how do i use street view to
see how hurricanes will affect the area", under the standing request to "drop in
like in google maps and see the streetview and the effects of el nino on the
real world street anywhere in the world". Self-approved under the user's
standing rule to work without check-ins.

## 1. What the stage does today, and what it lacks

The street stage (elnino/street.py) puts Google's panorama between a bar and a
strip holding the minimap and the chip, "El Niño on this street", whose replay
draws a past El Niño's daily rain over the panorama. The desk already knows
everything about the live storms that a point needs: Here's `hereFor(lon, lat)`
gives, for every live storm, when its official forecast brings 34, 50 and 64 kt
winds to the point, its closest approach, the cone, the nearest coastal watch or
warning, the surge areas the point lies in and the centre's own wind chances for
the town. None of it reaches the stage: a reader standing in Street View in
Manzanillo while Trudy is forecast to pass 125 km offshore as a major hurricane
sees the chip's El Niño sentence and nothing else. And for a point no storm
threatens today, the page has nothing to say about hurricanes there at all,
though the tracker's own subject, El Niño, is the strongest known control on
how many reach a coast.

On 14 October 2026 at 15:31 UTC the desk carried Hurricane Simon (85 kt, a
Hurricane Watch on Baja California Sur), Tropical Storm Trudy (45 kt, forecast
to 115 kt off Michoacán and Colima), Typhoon Koguma and two depressions.

## 2. What the reader gets

**A storm line on the chip.** When any live storm is near the stage's point by
Here's own rule (`nearHere`: its forecast comes within 1,500 km, or with no
forecast it is that close now, or the point is under a watch or in the surge),
the chip says so above its El Niño sentence, at most two storms, nearest first:

> Trudy (NHC): tropical-storm-force wind here from 04:00 UTC 18 Oct (in about
> 85 h) on the official forecast; closest 125 km at 09:00 UTC 18 Oct.

The words are built from `hereFor`'s numbers, so they are Here's to the hour.

**A button, "Hurricanes here".** Beside "Replay El Niño's rain"; it says
"Typhoons here" in the north-west Pacific (north of the equator, 100°E to
180°) and "Cyclones here" in the north Indian Ocean (north of the equator, 30°E
to 100°E) and south of the equator, the names the warning centres there use.
It opens a panel in the chip's place, as the El Niño replay does (the two never
open together):

1. **Live storms.** Here's own list items (`stormHere`) for the near storms,
   or "No live storm's official forecast comes within 1,500 km of here."
2. **The replay.** Play, a choice of storm, a speed (3, 6 or 12 hours a
   second, 6 first), a slider through the hours, the hour's readout, a chart
   and words; the wind band drawn over the panorama. The choices are the near
   live storms' official forecasts, then every past storm since 2004 whose
   analysed 34-kt wind reached the point or whose centre passed within the
   history's radius, newest first.
3. **Since 1950.** HURDAT2's storms whose centres passed within a radius of
   the point (50, 100 or 200 nautical miles; 100 first), counted by the ENSO
   phase of their season, with the test of whether El Niño's count differs
   from La Niña's by more than chance; storm by storm in a table.
4. **Method and sources**, and HURDAT2's credit while the panel is open.

## 3. The replay

**The path.** A live storm's is the desk's own `path` from the advisory's
analysis on (the official forecast hour by hour, centre and quadrant radii
interpolated linearly, `exposure.timeline`). A past storm's is HURDAT2's best
track (six-hourly, plus its special records at landfall and peaks) made hourly
in the page by `exposure._blend`'s rules exactly: a radius known where the file
gives one, zero where the wind is under the threshold, unknown otherwise;
interpolated only between two known ends; a threshold whose quadrants all come
to zero left out. A past storm's window is the hours its centre is within
1,000 km of the point, six hours either side, within the track.

**The band at the point.** Each hour, each threshold is `insideAt(p, lon, lat,
t)`: inside, outside, or not known (a radius the forecast does not give,
NHC's 64-kt radius past 72 h). The point's band is the strongest threshold it is
inside: under 34 kt, 34 to 49, 50 to 63, 64 kt or more, the next threshold said
"not forecast" when it is not known. So the hour tropical-storm-force wind
arrives in the replay is the hour Here and the exposure table give.

**The wind's direction** is worked out from where the centre is: the wind
blows round the centre (anticlockwise north of the equator, clockwise south of
it) and 20 degrees in towards it, a typical inflow angle near the surface; it
comes from 70 degrees clockwise of the bearing from the centre to the point in
the north, 70 anticlockwise in the south. Within 10 km of the centre it is not
given. The method says it is worked out here, not forecast.

**The drawing.** The El Niño replay's canvas over the panorama, clear of
Google's logo and terms (its bottom 40 px) and never taking a pointer, draws
the band: nothing under 34 kt; 160 streaks at 34 to 49 kt, 260 at 50 to 63, 380
at 64 or more, faster, darker and leaning further at each step, with gusts at
hurricane force; a band whose upper threshold is not known is drawn as the band
known. The badge over the panorama names the hour, where the centre is and the
band ("Sat 18 Oct 09:00 UTC · centre 125 km SSW · 34–49 kt, from the E"). The
drawing illustrates the band: it is not a rain forecast, and it does not turn
when the reader turns Google's view, which the page cannot see. The method says
both. Under `prefers-reduced-motion` it is drawn still.

**The chart.** The hours across, ticks every 12 hours with the day at 00 UTC;
the distance from the centre to the point as a line, 0 at the foot; under it
three strips, 34, 50 and 64 kt, filled in the storm's hue where the point is
inside, deeper for the stronger, hatched where not known; "now" marked on a
forecast; the playhead. Its geometry kept to place the playhead and to seek,
as the El Niño chart's is.

**The words.** When each band arrives and leaves and how long it lasts; the
closest approach, its time and the forecast wind there; the centre's own chance
for the town where its product names it; and what the replay is not: it follows
the official track exactly, and the cone and the chances carry the forecast's
uncertainty. For a past storm: HURDAT2's analysed track and radii.

**Hour by hour**, a table every three hours: the time, the distance and
bearing to the centre, the centre's wind, the band and the wind's direction.

## 4. Since 1950

**The record.** HURDAT2, which the tracker already downloads every run for
the season panel's climatology: the Atlantic from 1851 and the eastern and
central North Pacific from 1949, through 2025, each storm's six-hourly track
with its status, maximum wind and, from 2004, its 34, 50 and 64 kt radii by
quadrant. Kept: every storm from 1950, RONI's first year, whose maximum wind
reached 34 kt. The parser reads each line's position by its own pattern, not by
counting commas: the Atlantic file's 29 September 1969 06 UTC line for that
year's storm off Norway reads `63.3N    7.5E` with no comma between.

**Counting.** A storm counts at a point when its track, between fixes, passes
the point within the radius, at 34 kt or more there, whatever its status: Sandy
was post-tropical when it reached New Jersey. Its closest approach is the
nearest point of the track (on a plane about the point, as `toLine` measures),
its wind there interpolated, its status the nearer fix's. The table says each
storm's status at that point.

**The phase** of a season is RONI's ASO value for its year, compared on the
value CPC prints, as the season panel compares it: El Niño at +0.5 or more,
La Niña at -0.5 or less, neutral between. From 1950 to 2025: 21 El Niño
seasons, 21 La Niña and 34 neutral.

**The test.** With E storms in s_E El Niño seasons and L in s_L La Niña ones,
under no difference between the two each of the E + L storms falls in an El
Niño season with chance s_E / (s_E + s_L); the two-sided exact binomial
p-value of E says how often chance alone splits them at least as unevenly. Said
in words: "chance alone splits them this unevenly N% of the time". At
Manhattan, within 100 n mi: 3 storms in 21 El Niño seasons, 8 in 21 La Niña,
14 in 34 neutral; chance alone splits 3 against 8 this unevenly 23% of the
time.

**Coverage.** HURDAT2 holds the North Atlantic and the eastern and central
North Pacific. A point no HURDAT2 storm passed within 1,000 km of is said to be
outside its basins: the west Pacific's, the Indian Ocean's and the southern
hemisphere's storms are not in it. The method says the record before the
satellite era (about 1966 in the Atlantic, 1971 in the eastern Pacific) misses
storms that stayed far from land.

## 5. The tracks as an asset loaded later

The tracks are 1.4 MB as JSON (2,442 storms, 65,679 fixes, the radii from
2004), 269 KB compressed: as much as the composite grids, which every desk
visit loads. They load only when the panel is opened, from an asset file named
for its contents (`assets/tracks.<sha256[:10]>.js`, setting `ELNINO.tracks`),
which the page names with a new form, `<link rel="elnino-lazy"
href="assets/tracks....js">`: a link of an unknown relation is not fetched. The
run writes, keeps and publishes it as it does every asset (`page_assets` finds
both forms); the service worker keeps it once fetched, as it keeps any asset; a
page tells the worker only its scripts, so no visit fetches the tracks unasked.
The follower counts the lazy links as the page's code: a run whose tracks
changed (once a year, when NHC reissues HURDAT2) loads the page again rather
than taking the run in place.

Each storm: its id, name, first fix time, and its fixes as integers, each
relative to the one before: minutes, tenths of a degree of latitude and of
longitude (unwrapped across the date line), the wind, the status, and the
twelve radii where the file gives any. HURDAT2's -999 is null.

## 6. Naming a point

Here's name for a point (`placeLabel`) calls it "in" the nearest gazetteer
place within 25 km, so a point on Staten Island (40.58N 74.15W), 13.4 km from
Newark's point and 20.4 km from New York's, was "Newark, New Jersey". The
gazetteer is Natural Earth's populated places, whose populations are those of
the urban area (New York 19,040,000; Newark 280,123). A place's reach scales
with its people instead: the radius of a disc of its population at 2,000 people
a square kilometre, from 1.5 to 30 km (New York 30, Newark 6.7). A point is in
the place it is nearest to as a fraction of reach, among those that reach it;
else, as before, so many kilometres from the nearest place within 400 km, else
its latitude and longitude.

## 7. When things go wrong

- The tracks do not load: the panel says so with a Retry; the live part and
  the replay of a live storm work without them.
- No live storm near and no past storm to replay: the replay's controls are
  disabled and say why.
- A run taken in place: the chip's line and the panel are written from the new
  run; a live replay keeps its hour by its time where the new advisory still
  has it; a storm gone from the run falls back to the first choice.
- Leaving the stage, picking another street, or opening the El Niño replay
  closes or rebuilds the panel as the El Niño replay does.

## 8. Testing

Python: the track parser (the 1969 line, -999, landfall minutes, the date
line, the year floor, storms under 34 kt dropped), the encoding, the asset's
naming form through write, prune, publish and the follower. Node, on the page's
own functions: the band per hour against `hereFor`'s arrival times on the live
fixture; the hourly best track against Python's `exposure.timeline` on the same
fixes; the wind's direction north and south; the closest approach and counts
on a synthetic record and on the real one at Manhattan, Miami and Cabo San
Lucas against an independent Python computation; the binomial test against
exact values; the panel's open, close and retake under the faked DOM. Browsers:
Chrome, Firefox and WebKit on the built site with the live storms.json: the
chip's line at Manzanillo, the forecast replay, the history and Sandy's replay
at Manhattan, phone width, dark mode, reduced motion, nothing over Google's
logo and terms.
