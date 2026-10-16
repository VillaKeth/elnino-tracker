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
  LongPaddock, and PSL by date. PSL's tag ends "-gzip" and never matches, and
  asked by both tag and date it answers in full, as a server weighs the tag
  over the date; every server that gives a date answers 304 by it. CPC's
  `.shtml` pages and NHC's directory listings send no validators (4 KB each).
  ERDDAP's tables (TAO, 5.7 MB for the temperature record) are made afresh
  for each request: their Last-Modified is the moment of the answer, and they
  answer a conditional GET in full.
- **The record:** each run adds 50 rows to `fetch_log` and 48 to `series`
  (the last 24 ONI and RONI values, again), and nothing prunes them. Nothing
  reads either table back.
- **Change alerts:** `cpc_status_change` and `index_moved` compare the run with
  the run before. They stay up until the next run, so at ten minutes a change
  would be on the site for ten minutes. So would an alert's `NEW`, the level it
  rose from, and the list of alerts cleared, each marked on its run alone.

## The design

1. **A run every ten minutes.** `cron: "2,7,12,17,22,27,32,37,42,47,52,57 *
   * * *"`: every five minutes, GitHub's shortest, off the marks most schedules
   use, so each span has two slots of its own and only the first to come
   publishes: six Pages builds an hour, under the soft limit of ten with room
   for pushes. (First `2,12,...,52`; GitHub dropped the 14:22 and 14:32 slots
   on 16 October within the hour it went live.) The time is cut into ten-minute spans from :00 UTC. A
   scheduled run stands down when `gh-pages` was published in its span (by a
   push, a dispatch, or a run held into it); held into the next span it is that
   span's run. This is the old second chance generalised: every slot is one,
   with the hour replaced by ten minutes. Push and dispatch runs run, unless
   a later run takes their place while they wait. Any doubt runs it, a publish
   dated ahead of the clock among them. A good run on `main` lets go of the
   cached state it started from once its own is saved and listed.
2. **The nudge every ten minutes**, at 6 past each span: it dispatches when
   `gh-pages` was not published in the span and no run is queued or running.
   It lives on the user's machine (`%LOCALAPPDATA%\elnino-tracker\nudge.py`),
   outside the repository; the task is re-made as "ElNinoTracker Nudge" with a
   ten-minute repetition, and "ElNinoTracker Hourly" is deleted.
3. **Conditional requests.** A download records the server's `ETag` and
   `Last-Modified` with its copy. The next run asks with `If-Modified-Since`,
   or with no date `If-None-Match`, never both, only when its copy came from
   that address and reads back whole. A 304 serves the copy, unchanged since it was downloaded, as a
   griddap feed with no new day is. A 304 to a request that asked nothing is an
   error. A server without validators, or one that ignores them, is downloaded
   in full as before. The probe stays as it is. A server's word serves a day
   from the copy's download: a file put back from a backup keeps its older
   date, so a copy a day old, or whose record says no fair time, is asked for
   whole.
4. **ERDDAP's tables rest an hour.** A tabledap copy downloaded from the same
   address under an hour before serves without being asked again: ERDDAP cannot
   say whether a table changed, and TAO's moorings are averaged by the day and
   the month. Such a feed is `rested`, not `unchanged`, since nobody asked: the
   provenance card says "downloaded <time>, asked again hourly", the report
   counts it apart, and latest.json (schema 13) carries `rested` for each feed.
5. **Change alerts against the day before.** The two change rules compare
   with the latest snapshot at least 24 hours older than the run, or, with
   none that old, the earliest snapshot. A change stays on the site for a day,
   whatever the cadence. The words name the time of the state compared with,
   which is a day before unless the record is younger or has a gap.
5b. **An alert's news stays a day.** An alert is `NEW` for a day from when it
   was raised; a rise is said for a day while the alert stays above the level
   it rose from (the alerts table gains `raised_from` and `raised_at`, added to
   a database made before them), and both when it rose in the day it was
   raised; an alert cleared is listed for a day unless raised again. The page
   and the report say when each was raised, to the
   minute.
6. **A bounded record.** `fetch_log` keeps a week: 50 rows a run are 0.7 MB a
   day in the carried database, 20 MB over thirty days. `series` writes a value
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

- Conditional requests: a recorded date is sent back, or with none the tag; a 304 serves the
  copy as unchanged; a copy that does not read back, or came from another
  address, is not asked after; a 304 unasked is an error; a 200 answer to a
  conditional request replaces the copy and its validators.
- The span check's own script under bash (Linux-only, as the second chance's
  is): every event and age around the span's edges.
- The rest: a tabledap copy under an hour old serves as `rested`; an hour old,
  from another address, or not reading back, it is downloaded.
- The baseline snapshot: a day before, the earliest, none.
- An alert's news: raised, raised a level, cleared, each for a day; raised
  again; a database from before the news columns.
- `--watch`: no more often than every ten minutes, hourly without a number.
- The retention: a week of `fetch_log`; `series` only on change.
- A copy asked after for a day from its download, and whole after it.
- An alert raised and raised a level within the day, marked both ways; a day
  of cleared alerts wrapped in the report.
- The state let go of only after a good run on `main`.
- The README and the workflow text, as before.
