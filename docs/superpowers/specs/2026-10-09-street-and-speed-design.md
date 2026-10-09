# Street View, El Niño on the street, and a faster site

Written 9 October 2026, from the user's request: "make sure that this model
loads as optimally and works as well as possible; I want to be able to drop
in like in Google Maps and see the Street View and the effects of El Niño on
the real-world street, anywhere in the world." Self-approved under the user's
standing rule to work without check-ins.

## What the site does today

- The toolbar figure ("Enter") is dragged onto the map as Google Maps' figure
  is, but it lands in then-and-now: a satellite comparison of two dates with
  a bar of sources, events and dates under the map. Street View is a 347 by
  320 px frame at the foot of the side panel, which has to be scrolled to.
- What El Niño does at a point comes only from the atlas's composite grids,
  2.5 degrees for rainfall and 2 for temperature ("each value is the whole
  cell's, not this street's").
- Every page is one file with all its code and data inline. Measured on the
  live site on 9 October 2026 (phone: 1.6 Mbps, 150 ms, CPU slowed 4x):

  | page | gzip | phone, cold | phone, cached |
  |---|---|---|---|
  | dashboard | 1.45 MB | 7.7 s | 1.5 s |
  | El Niño Map | 683 KB | 4.4 s | 0.9 s |
  | Storm Desk | 683 KB | 4.1 s | 0.9 s |
  | atlas | 2.55 MB | 17.5 s | 0.8 s |

  Each hourly run rewrites every page, so the cache helps for an hour at
  most, and an open map or desk downloads its whole page again each hour to
  take the new run in place.

## 1. Drop into Street View

- The figure becomes **Street View**. Dragged onto the map, or pressed and a
  place tapped (Enter for the middle of the view, Esc to cancel, as now), it
  opens the **street stage** at that point.
- The stage covers the map. Google's own Street View embed fills it: the same
  keyless embed the page already opens, `maps.google.com/maps?layer=c&cbll=…
  &output=svembed`, loaded only on a drop. Over it:
  - a bar with the place, **Then and now**, **Copy link**, **Google Maps ↗**
    (the documented Maps URL for a panorama) and **Exit** (Esc too);
  - a **minimap** in the corner: Esri street tiles around the point, from the
    map's own layer list, with a pin, its own + and −, and a tap moving the
    figure there, as Google's minimap does; Esri's credit on it;
  - a **summary chip** with the first lines of the El Niño card, its button
    going to the whole card.
- Here moves to the point, so the side panel shows the place with the card at
  its top.
- Exit puts the map back on the point. Street and then-and-now are two views
  of an entered place and exclusive: **Then and now** in the stage enters it
  at the same point, coming back to the source and dates last used, and the
  then-and-now bar's **Street View** goes the other way.
- Here's **Enter here** becomes **Street View here** and **Then and now
  here**.
- `#street=<lat>,<lon>` opens the stage (Copy link writes it);
  `window.stormDesk.street(lon, lat)` and `stormDesk.leaveStreet()` drive it
  and `stormDesk.view().street` reports it. A run taken in place keeps the
  stage and the card; a page loaded again for a run hands it across with the
  rest of the reader's place.

## 2. El Niño on this street

The card is the point's own record, from public point data, computed by the
atlas composite's own method against the tracker's own index.

**Sources**, all keyless and sent with `Access-Control-Allow-Origin: *`, as
each answered on 9 October 2026:

| what | source | request |
|---|---|---|
| the record | NASA POWER, MERRA-2 at 0.5 x 0.625 deg | monthly PRECTOTCORR and T2M, 1981 to date (18 KB) |
| the latest months | NASA POWER daily | the same, for months the monthly API has not filled (3-day lag) |
| right now | Open-Meteo forecast | current conditions and the next 24 h of rain |
| the months ahead | Open-Meteo seasonal (ECMWF) | monthly temperature, rain and sea-surface anomalies, six months |
| the index | the tracker's RONI | shipped in the page, as CPC prints it |

ERA5 through Open-Meteo was the first choice and is not used: the free API
counts each fortnight of a point's record as a call, so 47 years a drop would
be about 1,200 calls against a limit of 10,000 a day. POWER answers the whole
record in one request. GloFAS river flow is left out for the same reason (a
climatology to compare a river with is 40 years of days).

**Method**, as `tools/vendor_composite.py` composites the atlas:

- a month is El Niño when RONI centred on it is +1.0 or more, neutral when it
  is within 0.5, and otherwise neither; the months of the event still under
  way are left out;
- per running three-month season (DJF to NDJ), an event contributes the mean
  of its El Niño months in the season and a neutral year the mean of its
  neutral months; a season is tagged by the year of its middle month;
- the composite is the mean of the events minus the mean of the neutral
  years, with Welch's t, and t_crit is the two-sided 95% point of Student's t
  at the smaller sample less one, from the composite's table; a season needs
  3 events and 6 neutral years;
- rainfall is also given as a percentage of the neutral mean, unless that
  mean is under the atlas's dry floor (`atlas.DRY_FLOOR`, 0.2 mm a day), when
  only millimetres a day mean anything; ECMWF's rain is held to the same
  floor against the model's normal.

**Card**, from the top:

1. A sentence: what El Niño is doing now, what past El Niños did here in the
   season ahead and how many agreed, and what ECMWF expects.
2. **Right now**: temperature, weather, wind, and the next 24 hours' rain.
3. **The next six months, ECMWF**: temperature anomaly and rain against the
   model's normal by month; the sea-surface anomaly too at a coast or at sea.
4. **El Niño's year here**: the composite for each running season, rain and
   temperature; seasons the t-test does not separate from ordinary years
   drawn faint.
5. **Past El Niños, <the season ahead>**: each event, and this year so far
   against the same neutral mean.
6. Method and sources, with Open-Meteo's required "Weather data by
   Open-Meteo.com" link, NASA POWER's and ECMWF's notices.

Charts are inline SVG in the page's tokens, each with its numbers in a table
for screen readers. Nothing goes to NASA or Open-Meteo until the reader drops
in or presses the card's button. Each source loads and fails on its own,
gives up after 20 s, offers Retry, and is kept for the session per point.

## 3. Faster loading

**Shared assets.** Code and data that do not change from run to run move out
of the pages into `assets/<name>.<sha256[:10]>.js`, written by the run beside
the pages and published with them, loaded as deferred classic scripts so they
work from a file as well as served. A file's name changes only when its
contents do, so the browser keeps it across runs and pages. The data parts
set properties of one global, `ELNINO`; the scripts are the follower, the
desk's engine and the atlas's. Shared by more than one page: the gazetteer
and the composite grids (desk, map and atlas) and the follower (all four).
Stale files are pruned from `output/assets` by the run that stops naming them.
The relief stays a data URI, inside its asset: the atlas reads its pixels
back, which a canvas allows for a data URI and not for a file opened from
disk.

An open desk takes a run in place by fetching its page again; a page without
its static data is about a tenth the size. Assets come from code, and a page
takes only runs of its own code, so a take never meets other assets; a run
whose pages name other assets is loaded instead, as a guard.

**Maps as images.** The dashboard's large fields are runs of SVG paths, one
per colour run: the global SST map alone is 2.4 MB. A regular grid of more
than 2,000 cells is drawn instead as an indexed PNG, one pixel a cell, one
for each theme, shown with `image-rendering: pixelated` so the cells stay
square; a picture whose cells are finer than a unit of its plot (the global
map's 1,440 columns in some 830 units) is left to the browser's smoothing,
as nearest-neighbour would drop whole columns of them. The hover blocks stay
vector. Small or irregular grids stay vector.

**Measured after**, by the same probe on a build served as Pages serves it
(phone: 1.6 Mbps, 150 ms, CPU slowed 4x; medians of repeated visits, 9 October
2026). Pages sends every file again after each publish, with a new date and
tag, so the visit that counts is the one after an hourly run: the page is new,
and without the service worker every asset is fetched again with it.

| page | before: one file, after a publish | first visit | after a publish, no worker | after a publish, with the worker |
|---|---|---|---|---|
| dashboard | 8.4 s | 7.4 s | 7.4 s | 5.8 s |
| El Niño Map | 4.9 s | 4.8 s | 4.8 s | 1.4 s |
| Storm Desk | 4.2 s | 4.1 s | 4.1 s | 0.7 s |
| atlas | 14.9 s | 14.2 s | 14.4 s | 0.8 s |

With the worker a visit after a publish fetches the page alone (gzip: 883 KB,
81 KB, 81 KB, 17 KB), `run.json` and the worker's own 1.3 KB check; the
assets come from its cache. Chrome's static routing (`addRoutes`), tried with
the assets served from the cache and everything else from the network, and
with navigations alone sent to the network, took the worker's start-up out of
the first byte (about 0.17 s on this phone) but moved the page's load by no
more than the visits' own spread, the map a quarter of a second slower with
the first; the worker stays a plain fetch handler.

## Out of scope

- Street View by date: neither Google's embed nor its Maps URLs take one.
  The link to Google Maps, whose "See more dates" holds older panoramas,
  stays.
- Google's tiles drawn in the page: Google's terms forbid it.
- Weather drawn over the panorama (rain, flood water): not data.
