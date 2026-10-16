# Ten-minute runs: design

Approved 2026-10-16: "yes faster cadence faster everything we need immediate
el nino updates now and ever and always". The user works autonomously (no
check-ins), so this spec is self-approved under that standing rule.

## Where it stands

`.github/workflows/live.yml` runs at 12 past each hour with a second chance at
42 past, and on each push to `main`. GitHub fires about one scheduled slot
in five (8 to 11 runs a day of 48 slots, 6 to 15 October), some late (12:22,
11:55, 07:06 on 16 October), so a Windows task on the
user's machine ("ElNinoTracker Hourly", `nudge.py`) dispatches a run at 25
past any hour with none. A run takes under a minute (16 October 13:25Z: 53 s,
of which the tracker 29 s and its 50 feeds 3 s); GitHub Pages deploys in about
20 s; open pages ask for `run.json` each minute. So the site trails a new
product by up to an hour and a half, and Trudy's advisories are on it up to an
hour late.

## The constraints

- **GitHub Pages:** "a *soft* limit of 10 builds per hour" for a site published
  from a branch, as this one is (`gh-pages`); "This limit does not apply if you
  build and publish your site with a custom GitHub Actions workflow."
- **GitHub's schedule:** "The shortest interval you can run scheduled workflows
  is once every 5 minutes"; it "can be delayed during periods of high loads...
  High load times include the start of every hour", and "some queued jobs may
  be dropped".
- **The feeds' servers:** every run downloads every feed that is not a griddap
  subset again in full: HURDAT2's two files (11 MB) and each active storm's
  a-deck (up to 16 MB) among them. Six times as many runs would be six times
  that load. Asked on 16 October, the static servers answer a conditional
  GET with 304 Not Modified: CPC's text files, NHC's www and ftp, JTWC, PMEL,
  LongPaddock, and PSL by date (its tag ends "-gzip" and never matches). CPC's
  `.shtml` pages and NHC's directory listings send no validators (4 KB each).
  ERDDAP's tables (TAO, 5.7 MB for the temperature record) are made afresh
  for each request: their Last-Modified is the moment of the answer, and they
  answer a conditional GET in full.
- **The record:** each run adds ~125 rows to `fetch_log` and 48 to `series`
  (the last 24 ONI and RONI values, again), and nothing prunes them. Nothing
  reads either table back.
- **Change alerts:** `cpc_status_change` and `index_moved` compare the run with
  the run before. They stay up until the next run, so at ten minutes a change
  would be on the site for ten minutes.

## The design

1. **A run every ten minutes.** `cron: "2,12,22,32,42,52 * * * *"`: clear of
   the hour, and six Pages builds an hour, under the soft limit of ten with
   room for pushes. The time is cut into ten-minute spans from :00 UTC. A
   scheduled run stands down when `gh-pages` was published in its span (by a
   push, a dispatch, or a run held into it); held into the next span it is that
   span's run. This is the old second chance generalised: every slot is one,
   with the hour replaced by ten minutes. Push and dispatch runs always run.
   Any doubt runs it.
2. **The nudge every ten minutes**, at 6 past each span: it dispatches when
   `gh-pages` was not published in the span and no run is queued or running.
   It lives on the user's machine (`%LOCALAPPDATA%\elnino-tracker\nudge.py`),
   outside the repository; the task is re-made as "ElNinoTracker Nudge" with a
   ten-minute repetition, and "ElNinoTracker Hourly" is deleted.
3. **Conditional requests.** A download records the server's `ETag` and
   `Last-Modified` with its copy. The next run asks with `If-None-Match` and
   `If-Modified-Since`, only when its copy came from that address and reads
   back whole. A 304 serves the copy, unchanged since it was downloaded, as a
   griddap feed with no new day is. A 304 to a request that asked nothing is an
   error. A server without validators, or one that ignores them, is downloaded
   in full as before. The probe stays as it is.
4. **ERDDAP's tables rest an hour.** A tabledap copy downloaded from the same
   address under an hour before serves without being asked again: ERDDAP cannot
   say whether a table changed, and TAO's moorings are averaged by the day and
   the month. Such a feed is `rested`, not `unchanged`, since nobody asked: the
   provenance card says "downloaded <time>, asked again hourly", the report
   counts it apart, and latest.json (schema 13) carries `rested` for each feed.
5. **Change alerts against the day before.** The two change rules compare
   with the latest snapshot at least 24 hours older than the run, or, with
   none that old, the earliest snapshot. A change stays on the site for a day,
   whatever the cadence. The words say "in the last day", not "since the last
   run".
6. **A bounded record.** `fetch_log` keeps 30 days. `series` writes a value
   only when it is not the latest recorded for its key and period, so each
   revision is still kept, with the run that first saw it. `snapshots` keeps
   every run: about 0.1 MB a day at this cadence.
7. **`--watch`** refuses intervals under ten minutes (fifteen before): the
   site's own cadence, which conditional requests make cheap.
8. **The follower keeps asking each minute.** Against a ten-minute cadence
   that adds 30 s on average. Asking every 30 s would gain 15 s and retime
   the follower's 46 timed test steps.

## Not done (and why)

- **Five-minute runs.** That would be twelve Pages builds an hour, past the
  soft limit, while Pages builds from `gh-pages`. Deploying from an Actions
  artifact lifts the limit, but it would change how `publish.py`, `publish.bat`,
  the second chance and the nudge each know the site's age. That is its own
  change.
- **Skipping a run that found nothing new.** The cyclone tier fetches each
  storm's products deep in the pipeline, so "nothing new" is known only at the
  end; and each page's run time is what tells a reader the site is live.

## Staging

The schedule goes first, alone (designs 1 and 2), so the site runs every ten
minutes within the hour: until the rest lands, a run downloads what an hourly
run did, about 66 MB an hour more from NHC's CDN and 6 MB from CoastWatch.
Designs 3 to 8 follow on the same branch.

## Testing

- Conditional requests: a recorded tag and date are sent back; a 304 serves the
  copy as unchanged; a copy that does not read back, or came from another
  address, is not asked after; a 304 unasked is an error; a 200 answer to a
  conditional request replaces the copy and its validators.
- The span check's own script under bash (Linux-only, as the second chance's
  is): every event and age around the span's edges.
- The rest: a tabledap copy under an hour old serves as `rested`; an hour old,
  from another address, or not reading back, it is downloaded.
- The baseline snapshot: a day before, the earliest, none.
- The retention: 30 days of `fetch_log`; `series` only on change.
- The README and the workflow text, as before.
