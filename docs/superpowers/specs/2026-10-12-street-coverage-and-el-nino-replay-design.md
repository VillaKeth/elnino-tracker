# Street View that finds its street, and El Niño's rain replayed on it

Written 12 October 2026, from the user's report and question: "ok street view
seems to work... but some places don't have it, some place in winter haven
florida didn't have it, additionally, how do i simulate the rainfall and effects
of elnino on the area", under the standing request to "drop in like in google
maps and see the streetview and the effects of el nino on the real world street
anywhere in the world". Self-approved under the user's standing rule to work
without check-ins.

## 1. Why Street View found nothing

Google's keyless embed (`output=svembed`) looks only some tens of metres about
the point it is given, and the page cannot see whether it found a panorama: the
frame is Google's, on another origin. A pick goes first to OSRM's nearest road a
car may take, taken when it lies within 24 pixels of the view (250 m at the
least). Thirty random drops over Winter Haven (27.98 to 28.07 N, 81.66 to
81.78 W), each loaded in Google's frame in headless Chrome on 12 October 2026:

| what the pick did | drops | with a panorama |
|---|---|---|
| went to a named road | 15 | 14 |
| went to an unnamed road (a driveway, a service road, a parking aisle) | 13 | 8, one a business's own tour |
| stayed where it was made (a lake, no road within 250 m) | 2 | 0 |

Unnamed ways are where Google's car did not go. Asked for its 100 nearest
stretches of road instead of one, OSRM names the nearest *named* road too; the
largest distance to one among the thirty drops was 645 m.

The rules compared on fifty drops (the thirty, and twenty places chosen to be
hard: a piazza and a canal quarter in Venice, Central Park, Hyde Park,
Trastevere, Gion, farmland in Kansas and Iowa, a village in Kenya, Dharavi, the
Everglades, Zermatt, the outback, a lake in Minnesota and city blocks on five
continents), each candidate loaded in Google's frame:

| rule | a panorama | Google's own imagery | a panorama, Winter Haven's 30 |
|---|---|---|---|
| A. the nearest road within reach, else the point (today) | 38 | 31 | 22 |
| B. the nearest *named* road within 1 km (or the reach, if further), else A | 45 | 41 | 28 |
| C. as B over OSRM's foot network | 46 | 41 | 29 |

B and C tie on Google's own imagery. C finds Google's trekker on Piazza San
Marco where B stays on a visitor's photo, but in Gion its 100 nearest footways
are all unnamed within 100 m and it lands on a photo where B finds
Higashiōji-dōri; in Central Park and Zermatt C lands on visitors' photos where B
finds Google's. B is chosen: the car network is where Google's cars drove.

Of B's nine drops without Google's own imagery, a later named road on OSRM's
list has it for six: the second for a Winter Haven subdivision Google never
drove (Martin Luther King Jr Boulevard, 483 m), the first in Trastevere, the
second in Reykjavík, the first in the Everglades (Loop Road, 1.25 km, past the
kilometre B allows), and the first for both Venice drops (Piazzale Roma, 1.1
and 1.7 km off, where B stayed on visitors' photos). Kansas's section roads,
the Kenyan village and one Winter Haven subdivision have none on the first
three. So the stage keeps the list, and **Next street** goes down it.

### The rule

- `ROADS` asks for `number=100`. FOSSGIS's server answered 100 waypoints in
  25 KB on 12 October 2026, its documented limit.
- From the answer: each waypoint with a finite position and distance; the
  named ones collapsed to the nearest stretch of each name, out to 5 km
  (`SNAP_FAR`), nearest first.
- The pick goes to the nearest named road within the larger of the reach and
  1 km (`SNAP_NAMED`); else to the nearest road of any name within the reach;
  else it stays where it was made, as today.
- The stage keeps the candidates: the one taken, the other named roads to
  5 km, nearest first, up to six roads in all, and last the point as picked
  (first, when the pick stayed). **Next street** in the stage's bar, shown when
  there is more than one, enters the next exactly, without asking OSRM, and
  after the last comes the first again. A new pick, an address, `#street=` or
  the page's API lets the list go.
- A line under the bar says where the stage is against the pick: "The nearest
  named street, 213 m from the point picked." or "Hoover Road, 227 m from the
  point picked (2 of 5)." or "The point as picked: no road within reach.", and
  what **Next street** tries next: "Next street: Martin Luther King Jr
  Boulevard, 483 m away." Distances are metres under a kilometre and tenths of
  a kilometre over it.
- The bar's standing note says: a point picked goes to the nearest named
  street within a kilometre, else the nearest road within reach; where Google
  has no panorama its frame says "No Street View available", and Next street
  tries the next one.

Kept as they are: OSRM asked once a second at most, the latest pick winning,
an answer for a stage since moved or left dropped, 2.5 s before a pick opens
where it was made, the credit under the minimap.

Not chosen: asking OSRM's foot network as well when the car network has no
road within a kilometre. It finds Google's trekker in car-free places (Venice),
at the price of a second request a second later; visitors' photos already
answer there, and Next street covers the rest.

## 2. El Niño's rain, replayed on the street

"How do I simulate the rainfall and effects of El Niño on the area": by
replaying it. The honest simulation for a point is its analogs: what the past
El Niños actually rained there, day by day, set against what neutral years
rained, with ECMWF's forecast for the season ahead beside them. A model run of
the point's weather is not something a page can do, and a stochastic weather
generator would be the page's own invention dressed as data.

### What it shows

**Replay El Niño's rain** in the stage's chip opens the replay in the chip's
place, under Street View:

- **Play** runs the window's days, a week a second by default (two weeks or a
  month a second as chosen), and a slider steps or drags through them. On
  Street View the day's rain falls, drawn by the page over Google's panorama:
  streaks as many and as fast as the day's rain is heavy, snow on days whose
  mean temperature is at or below 0 °C, and the sky dimmed by the day's rain.
  A badge over the panorama names the day.
- A readout: the day, its rain (mm and inches) and mean temperature, the
  event's total so far and the neutral years' mean total by the same date
  (29 February counted with the 28th).
- A chart: rain accumulated over the window. The chosen El Niño bold in the
  site's El Niño red, the other El Niños faint in it, the neutral years' mean
  dashed with the band of their 10th to 90th percentiles, ECMWF's forecast for
  the coming window dashed in blue, and this year so far in ink when the
  window has begun; under it the chosen event's daily rain as bars. Each line
  is labelled at its end, and each faint one named under the pointer; a click
  or drag on the chart seeks the day, and a finger seeks where it lifts or as
  it drags across, scrolling the panel when it moves up or down.
- A summary: the event's total against the neutral mean, its days of 20 mm or
  more (ETCCDI's R20mm), its wettest day, its longest dry spell (consecutive
  days under 1 mm, ETCCDI's CDD) and its mean temperature against the neutral
  years'; what all the El Niños averaged and in how many of them the window
  was wetter than the neutral mean; and what ECMWF's forecast comes to.
- **Year by year**: a table of every El Niño with RONI's peak, the neutral
  mean and ECMWF's projection, with the same measures; **Method and sources**.

Choices: the event (each replayable El Niño, newest first, labelled with the
index's peak in the window's first season; the strongest chosen at first; and
this year so far, when the window has begun) and the window (six months from
any month, the six from next month at first, so in October November to
April). Open-Meteo is asked for the seven months of ECMWF's run
(`forecast_days=215`; it gives six unasked), so that window is the forecast's
whole once the month's run is out, on the 5th; before then the last month's run
covers five of its months, and the replay names them.

### The record and its method

- **Source**: NASA POWER's daily point API, `PRECTOTCORR` and `T2M` from
  1 January 1981 to today, in one request, asked only when the replay is
  opened. As CSV it is 342 KB (the JSON is 547 KB); neither is compressed.
  The answer is kept in memory for the last three points and not in the tab's
  session: a third of a megabyte a point would crowd out the card's answers.
- **Window**: the six calendar months from the chosen month, tagged by the
  year of its first month, and labelled as the site labels an episode
  ("1997-98" when it crosses the new year).
- **El Niños**: years whose window's first running season has a month at the
  index's El Niño bound (+1.0) or over it, as the card's composite takes its
  events for the season ahead; the event still under way is not among them.
  It is the index as the window opens, as a forecast made then would have it:
  a window from spring takes El Niños growing and fading alike.
- **Neutral years**: years whose first season's three months are all strictly
  within ±0.5. Stricter than the composite's months, because a replay plays
  whole windows: a year neutral in November and La Niña in December would
  bring December's La Niña into the neutral band.
- A window counts when all its days are in the record but five at most;
  missing days count as dry in the accumulation and are named in the method.
- **The band**: the neutral years' 10th to 90th percentiles of the rain
  accumulated by each date of the window, their days lined up as a year's
  without 29 February, which counts with the 28th; on its last day, their
  totals'.
- **ECMWF's projection**: for each month of the coming window that Open-Meteo's
  seasonal forecast covers, from the window's first month on, POWER's mean
  total for that calendar month over all complete years, scaled by ECMWF's
  forecast against the model's own climate of past forecasts where that
  climate is the atlas's dry floor (0.2 mm a day) or more, else with ECMWF's
  anomaly added (the delta method), never under zero; the base is POWER's
  all-years mean. It is drawn only for a window not yet begun.
- **This year so far**: the window under way, when at least seven of its days
  are in the record, against the same neutral band; it can be replayed.
- What it is not: a gauge. POWER's value is MERRA-2's 0.5° by 0.625° cell,
  about 55 km across, so a day's rain is the cell's mean, smoother than a
  gauge's; the rain drawn on Street View is the page's, scaled to that number,
  over Google's imagery, which is unaltered beneath it.

### The rain over Street View

A canvas over the panorama, never taking a pointer, leaves Google's logo and
terms at the panorama's foot uncovered (the bottom 40 px) and fades out above
them. The drawing's level is a pure function of the day's rain and
temperature: under 0.5 mm nothing; else a strength
`s = min(1, sqrt(mm / 50))` gives `20 + 380 s` streaks (or `30 + 270 s`
flakes) and a dimming of `0.08 + 0.3 s`. It runs at the display's frame rate
while the replay is open and it is raining on the day shown, and stops when
the day is dry, the replay is closed or the stage left. Under
`prefers-reduced-motion` the rain is drawn still, once a day; Play still steps
the days. The canvas is sized to its box at the device's pixel ratio, two at
most.

### Where it lives

The chip under the panorama, in place of the card's sentence; the minimap
stays beside it on a wide screen and gives its room on a phone. The credits
stay under it, with NASA POWER's added. **Back to the card** closes it; so do
Exit and Esc. Entering another point (Next street, the minimap) keeps the
replay open on the new point's record, asked again if it is another cell,
stopped where it was.

## 3. Checks

- Unit tests under node for every rule above: the candidates and Next street,
  the CSV read, the windows, events and neutral years, the measures, the band,
  ECMWF's projection, the words, playback and seeking, the rain's level.
- The offline build in Chrome, Firefox and WebKit, desktop and phone: a drop
  in Winter Haven goes to a named street; Next street moves; the replay opens,
  plays, seeks, draws rain over the panorama and leaves Google's foot clear;
  no errors.
- After the push: the live site, the same.

## 4. Measured after

The offline build, served as Pages serves it, on 12 October 2026, in Chrome,
Playwright's Firefox and WebKit, at 1280 by 900 and at 390 by 844 (two device
pixels a unit, touch), the figure pressed and the map tapped at 28.0222 N,
81.7330 W in Winter Haven:

| | measured |
|---|---|
| the pick | 6th Street Southwest, the nearest named street, 7 m from the tap, in all six; OSRM answered in about half a second |
| Next street | West Central Avenue, 12 to 14 m away ("2 of 6"), its panorama Google's |
| the replay | POWER's days for the cell in 0.46 to 0.86 s; November to April at first; ten El Niños replayable, 2023-24 back to 1982-83, against nine neutral years; 1982-83, the strongest, chosen: 609 mm, 174% of the neutral mean of 349 mm; ECMWF's October run over the whole window (seven months asked): 737 mm, against 362 mm in an average year, 211% of the neutral mean, its mean about twice its own climate in every month |
| Play | ten days in a second and a half, a week a second |
| the rain | drawn at the device's pixel ratio (900 by 216 and 780 by 402); no pointer taken (the panorama's frame is under it); its foot 40 px above the panorama's, the badge's 48 px; a dry day's canvas hidden |
| the room | desktop: the stage 690 px, its panorama 256 px and the replay's strip 359 px; phone: the stage 776 px (92svh while the replay is open, 92vh where svh is unknown), its panorama 241 px and the strip 404 px |
| a finger | on the phone, a tap three tenths across the chart seeks day 50 where it lifts, in all three engines |
| the card | ECMWF's six months from October, October 2026 to March 2027 |
| Esc | the replay closed, the focus on its button; again, the street left |
| errors | none on the page; Chrome logs a permissions-policy notice (accelerometer) from Google's frame |

Found by these checks and fixed, each with its test: in Chrome, a canvas whose
only drawing after frames already shown is a clearRect of the whole of it went
on showing the last frame, so a dry day's rain stayed; the canvas is now shown
only while it rains. The chart's line rules took the fill from the label of
the line of the same class, so "Neutral" was drawn unseen; they are now the
paths' alone. On a phone the panorama had 184 px under the replay's strip; the
stage stands at 92vh while the replay is open. Headless WebKit draws Google's
panorama black (no WebGL there); the page's parts over it are as in the others.

Found by the final review and fixed, each with its test, and measured again
in the three engines on the same day:

- The band lined the neutral years up by day of the window, so a leap year's
  29 February stood against the others' 1 March, and its last day was the mean
  of the leap years alone. It is by date now, 29 February counted with the
  28th, and its last day is the neutral totals'.
- Open-Meteo gives six months of ECMWF's run unless asked, from the month it
  is asked in, so the window from next month had five, said as the whole. It
  is asked for seven; the card shows six from the reader's month, and a
  forecast short of the window is named by its months in the key, the words
  and the table.
- The projection added ECMWF's anomaly in millimetres to POWER's climate, so
  where the model's own climate is wetter or drier than POWER's the anomaly
  was too big or too small for the place, and a dry one could take a month
  under nothing. It scales POWER's climate by the model's forecast against its
  own climate where that climate is the dry floor or more, and adds the
  anomaly below it, as the card's percentages do.
- A finger put on the chart to scroll the panel sought the day it landed on;
  it now seeks on a tap or a drag across. Play, the slider and the choice of
  El Niño wait while a pick's street is found. A run taken in place tells the
  replay's years again by its index. With nothing to replay, the words say
  whether this year's window has yet to begin or has too few days on record.
  An answer from OSRM with no road it can read counts as no answer; POWER's
  CSV may have its year in any column; the bar's note says what Street View
  shows before what a pick does; Play's button says Play or Pause and no
  longer also claims to be pressed; the table's peak is named RONI's; each
  faint El Niño is named under the pointer; the phone's stage takes the small
  viewport's height; the method says how a window is named and that the index
  is the one at the window's opening.
