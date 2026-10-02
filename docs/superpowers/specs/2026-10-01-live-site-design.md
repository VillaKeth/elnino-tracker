# The live site: design

2026-10-01. Approved under the user's standing rule to work without
check-ins ("finish from one prompt"), as earlier rounds were.

## What was asked

> does the el nino tracker not update in real time, it should, make the el
> nino tracker update in real time make no mistakes use beautiful code

## Where it stands

The public site, villaketh.github.io/elnino-tracker, is one run: the one
`publish.py` last put on `gh-pages`. It changes only when someone runs
`publish.bat` on this machine. The storm desk and the map read themselves
again every five minutes when served, but on the site there is never anything
new to read, and the dashboard and the atlas never look at all.

## What "real time" can mean here

The tracker can be no fresher than its feeds. The fastest are the tropical
cyclone products: NHC and CPHC advisories every six hours with intermediates
between (03/09/15/21 and 00/06/12/18 UTC), their outlooks four times a day, and
JTWC's warnings six-hourly, all issued on or near the hour. The ENSO feeds
change daily at most. The satellite imagery under the storms is already live
in the browser.

So the site is kept current when:

1. a run happens soon after each hour's products, without anyone at this
   machine: the site is never more than about an hour, plus GitHub's queue,
   behind the feeds;
2. a page left open takes a new run within a minute or two of the site serving
   it, without a manual reload and without losing the reader's place;
3. what goes up is always one run, never pages of two;
4. nothing loops, nothing hammers NOAA or GitHub, and a failure leaves the
   last good run up and says so.

## Approaches

- **GitHub Actions runs the tracker every hour and publishes it (chosen).**
  Free for a public repository, needs no machine left on, and reuses
  `publish.py`, which is already tested and keeps this machine's identity out
  of the site.
- This machine runs `publish.bat /scheduled` every hour from Task Scheduler.
  It needs the PC on and awake around the clock. It stays documented as the
  local way.
- The pages fetch NOAA's feeds themselves. Most of the feeds send no CORS
  headers, and the analysis is Python: this cannot carry the tracker.

## Design

### 1. The hourly run: `.github/workflows/live.yml`

- **When:** `cron: "12 * * * *"`, every hour at twelve minutes past. The
  products land on the hour, and GitHub's own docs name the start of the hour
  as when scheduled runs queue longest. Also `workflow_dispatch`, to run it
  from the Actions tab or `gh workflow run live.yml`, and a `push` to `main`,
  so new code goes live at once.
- **One at a time:** `concurrency: {group: live-site, cancel-in-progress:
  false}`. Two runs never publish over each other or race on the state.
- **Token:** `permissions: contents: write`, to push `gh-pages`, and
  `actions: write`, for step 7. Nothing else.
- **Steps:**
  1. checkout, with `persist-credentials: false`;
  2. Python 3.12;
  3. restore the state;
  4. `gh auth setup-git` with `GH_TOKEN` set to the run's token, then
     `./publish.sh --remote https://github.com/$GITHUB_REPOSITORY.git`;
  5. map the exit code:
     - 0 is success;
     - 1 is success with a notice ("WARNING or CRITICAL alerts open");
     - 3 is success with a warning ("a degraded run");
     - anything else fails the job;
  6. save the state unless the run was cancelled;
  7. on a scheduled run, enable the workflow through GitHub's API, whatever
     became of the run. GitHub pauses the schedule of a public repository
     after 60 days without activity, and a workflow enabled from its own run
     does not pause. The step never fails the run.
- **Limit:** `timeout-minutes: 30`.
- Action versions are the current majors, checked on 2026-10-01: checkout v7,
  setup-python v7 and cache v6.

### 2. State from one run to the next

What a run reads back:

- `data/elnino.db`: the previous snapshot, and the alerts it reconciles
  against;
- `data/raw/*.cache` and `*.meta.json`: the copy a failed feed falls back on.

These are carried in the Actions cache:

- **Key:** `tracker-state-<run_id>-<run_attempt>`.
- **Restore:** by the prefix `tracker-state-`, which brings back the newest.
- **Left out:** `data/raw/archive/` is a local audit trail that nothing reads
  back. Leaving it out keeps each entry to the ~114 MB the cache files take.

GitHub drops an entry unused for seven days, and past 10 GB it evicts the
oldest. After a gap of more than a week, the next run starts afresh: every
open alert reads as new, and no feed has a fallback copy for that run. The
README says so.

### 3. `publish.sh`

The POSIX twin of `publish.bat`, and what the hourly run calls:

- it runs `python3 track.py --brief`, and publishes with `python3 publish.py
  "$@"` when the tracker ran (exit 0, 1 or 3);
- it exits with the run's own code once published, 2 when the tracker did
  not run, and 4 when it ran but publishing failed;
- it is committed executable.

### 4. The run beacon: `run.json`

`{"run_at": "<the run's run_at>"}`, written by `track.py` after every other
file of the run. A reader that sees a new run in it finds every page of that
run already written, which matters to the local server: it serves `output/`
while `--watch` rewrites it in place. It is written by `live.write_run`.

### 5. Every page names its run

`dashboard.html`, `atlas.html`, `storms.html` and `map.html` carry
`<meta name="elnino-run" content="<run_at>">` in their heads, written by
`live.head`, with the small script that puts a kept theme back before the page
is first painted (section 6). A state with no run time writes no mark.
(Amended after the final review: beside it, `<meta name="elnino-code"
content="<code>">` names the code that wrote the page, the first 12 hex digits
of a SHA-256 over the package's `*.py`, each by its name and its text read with
Unix line endings; section 6.)

### 6. Pages follow the site

One script, `live.SCRIPT`, is in all four pages. It acts only over http(s),
on a page that names its run.

- **Asking:** it fetches `run.json` (relative to the page, `cache:
  "no-store"`) every 60 s. It also asks at once when the tab becomes visible
  again or the browser comes back online.
- **Taking a new run:** when `run.json` names a run newer than the one the
  page shows, the page takes it in its own way (amended after the final
  review: an older run, from a cache the site's move has not reached or a
  run put back with `--allow-older`, is never taken, nor one older than the
  run already offered):
  - **In place** (the storm desk and the map): the page reads itself again and
    swaps its data and panel, keeping the view. This is the existing
    `refresh()`, which now returns its promise and, having swapped the data,
    names the new run through `elninoLive.shows(doc)`. The blind five-minute
    re-read goes: a 2.3 MB page is fetched only when the run has changed.
    (Amended for the map's exploration, after the final review: the panel is
    swapped as the reader left it. *Here*, with Google's frame in it, is never
    taken out of the page, so the frame is not loaded again; each storm keeps
    its tab, each `<details>` its open state, found by its section and its
    summary's words, and the focus its control. In then and now, NASA's days
    are asked for again, and sides set by an event go to the new build's
    dates for it, or become the reader's own when it is no longer offered.
    Chrome's scroll anchoring lost the swapped nodes and threw the view, so
    the page holds the reader's place itself: anchoring is off through the
    take, the nodes with an id at the top of what the reader sees are found
    again by id once the run is drawn, and the deepest still shown is put
    back where it stood. A region's Show stays pressed, and the reading under
    the map keeps the height it held.)
    (Amended for a load, below: the follower holds the place, through
    `elninoLive.hold()` for a take, by the boxes the page names, and holds it
    for 15 seconds more as the page settles, each frame: a mark moved while
    the view stood still takes the view with it, as a browser that anchors
    scrolling does by itself and Safari before 27 does not, and one moved with
    the view, the reader's hand or the page's own doing, ends the hold.)
    (Amended after the final review, for a push of new code: a page that never
    loads would run its first script against every later build's markup and
    data. The desk and the map take in place only a run their own code wrote,
    by the code mark (section 5). For one another code wrote, or one whose take
    fails part way and so leaves the page between two runs, `refresh()`
    answers false, and the page loads again as the dashboard does, below, for
    that run and every run after it. Its place is handed across: the view; the
    layers, the comparison and the divider as the map's own; the hour
    scrubbed to and the day stepped to; the overlays; El Nino's map; *Here*
    and Google's frame in it; the place entered in then and now, on its event
    or its dates, with Esri's names as they were; the storm chosen and each
    storm's tab; and, kept by the follower and put back after the sections,
    the scroll of the panel and the key, which scroll themselves, then the
    marks at the top of the view, as for a take: the pixels alone were 62 px
    off on a phone, where then and now's words and *Here*'s sea come in above
    the part being read after the place is put back. The browser's own
    scroll restoring is off across the follower's loads
    (`history.scrollRestoration`): Chrome's last try came 20 ms after the
    follower's and undid it. It is on again once the reader leaves the page,
    for their own loads and their way back.)
    (Amended after the second final review. The hold copies anchoring more
    closely: a box at its scroll top, or the page at its top, gives no marks,
    as a browser clears its anchor there, so what comes in at the top (*Here*
    opening above the panel's first section) is seen; the reader's own
    pointerdown, keydown, wheel or touchstart ends the hold, as does a scroll
    the layout does not explain, however slow; and a hidden page, which draws
    no frames, holds its place from when it is shown again, the place first
    put back. The browser's own scroll restoring is off only across a load
    that hands marks over, and on again once the page loaded again has
    finished loading (the window's load event, then a task), or when a page
    asked to load is shown again from the back-forward cache instead.
    `refresh()` takes only a copy newer than the page's own run, so an older
    one a CDN's edge still serves is passed over; a take that fails part way
    throws once the place is put back, and the follower offers that run
    without Later ("…, which this page could take only in part."), loading it
    once the reader leaves the page alone, or at once if it is hidden. *Here*
    is written as the panel is, its tables and its focus kept, and is no
    longer a live region: a status line outside the panel (`#here-said`) says
    which place it is on, only when that changes; its readings of NASA's
    tiles are kept by layer, day and point. Each storm's row has an id
    (`row-<storm>`), so it can be a mark. In then and now, dates that stand
    have NASA asked again quietly: GIBS's times, and the days with a Landsat
    or Sentinel-2 image at the pin (the page forgets the tiles it looked at);
    the sides stand, words and reading too, until an answer moves one, and no
    answer leaves them; Esri's captures stay as they were found; the event
    menu, the strip and the years are written only when the new build changes
    them. Across a load the loop is handed over, the map's own or Exit's, and
    runs once GIBS gives the layer's frames; the `#then=` address a place was
    entered from is put back once the place is entered again.)
  - **By loading again** (the dashboard and the atlas):
    - at once if the tab is hidden;
    - otherwise once the reader has been idle for two minutes (no pointer,
      key, wheel, touch or scroll). Until then a small notice says a newer
      run is in ("The site has a new run, from 01 Oct 2026 11:12 UTC.") and
      offers **Update now**, and **Later**, which keeps the page as it is
      until the run after (amended after the final review). The notice is a
      polite live region, and its words are set as text, never as markup.
    - Before loading, the page's place is kept in `sessionStorage` with the
      run it wants:
      - for every page: the scroll, the theme and which `<details>` are open,
      found again by their summaries' text (a run's page may have a section
      more or fewer, so a count would open the wrong one);
      - for the atlas, also: the view, the picked point, variable, season,
        fade, base map and layers;
      - for the dashboard, also: the marks at the top of the view in its
        body, every part of which (the hero, the indices, each card) wears an
        id, so the card being read is put back where it stood. (Amended after
        the second final review: the "Generated ... (x ago)" line above it
        wraps to a line more or fewer from one run to the next, and the scroll
        alone left a phone's reader 21 px off.)
    - After loading, the place is restored, and for six seconds a note names
      the run the page now shows ("Now showing the run of …"). What storage
      hands back is checked like input: a value that is not one of the
      page's own is left as the page opens.
    - A head script (`live.head`) applies a kept theme before first paint.
- **Never loops:**
  - If, after taking a run, the page still names another, that run is not
    tried again for 2, then 5, then 10, then every 15 minutes. The back-off
    is kept in `sessionStorage` across loads, and in memory for the pages
    that update in place.
  - Without `sessionStorage`, or when it refuses a write, a page that would
    load again never does so on its own; it only offers **Update now**. So
    too for a reader saving data (`navigator.connection.saveData`; amended
    after the final review). The page's own `keep()` and `restore()` failing
    costs that state, never the following.
- **Age:** the dashboard's "Generated" line is the run's own time, not the
  moment the page was rendered, and ticks its age each minute ("(12 min
  ago)"), as the desk's stamps already do.

### 7. Only one run goes up

`publish.py` publishes `run.json` with the pages. It refuses the set unless
every page names latest.json's run: each HTML page's `elnino-run`,
`storms.json`'s `built`, and `run.json`'s `run_at`, compared as moments. This
also stops a page from reloading forever against a `run.json` it can never
match.

### 8. Tests on GitHub: `.github/workflows/tests.yml`

The unit suite runs on Ubuntu with Python 3.12, read-only token, on pushes to
`main`, on pull requests and by hand. The hourly run is Linux, and so far the
suite has only ever run on Windows.

### 9. The README

- The hero says the site refreshes itself every hour.
- A new section, "The live site", covers:
  - the run, the state and how pages follow;
  - running it now, and pausing it;
  - what a failure looks like;
  - GitHub's 60-day pause of schedules in a repository with no activity,
    which step 7 keeps off; if it is ever paused, the Actions tab turns it
    back on.
  - `python track.py --serve --watch` as the same thing on this machine.
- Layout, outputs and the test list are updated, and the update-rhythm note
  says why the site runs hourly although the ENSO feeds change daily at most:
  the tropical cyclone products change every three to six hours.

## Errors

| What happens | What the site does | What the run says |
|---|---|---|
| The tracker cannot run (exit 2) | Keeps its last run | The job fails, and GitHub emails the owner |
| A degraded run (3), or open alerts (1) | Published, and the pages say so | A warning or notice on the run |
| Publishing refused or failed (exit 4) | Keeps its last run | The job fails |
| The state is evicted | The next run starts afresh | Nothing |
| `run.json` unreachable or malformed | Ignored until the next minute | Nothing |
| Enabling the workflow fails | Nothing changes | That step is marked failed; the run is not |

## Testing

- **`live.py`:**
  - the beacon's content and the head's meta;
  - under node, with a fake clock, fetch, document and storage:
    - taking a run in place;
    - loading again when hidden, and when idle but not before;
    - the notice and **Update now**;
    - back-off after a stale take;
    - nothing done on `file:` or on a page with no run;
    - no automatic load without storage;
    - keep and restore round-tripping;
    - the theme applied by the head script.
- **Pages:**
  - each carries its run;
  - each includes the follower in its mode;
  - the dashboard's age stamp;
  - the atlas's keep and restore under node.
- **`track.py`:** `run.json` is written last, and names latest.json's run.
- **`publish.py`:** `run.json` is published; a page from another run, or one
  naming no run, is refused.
- **`publish.sh`:** under bash with stub `track.py` and `publish.py`, the same
  cases as `publish.bat`.
- **The workflows** (as text):
  - the schedule;
  - one run at a time;
  - the token's permissions, and no checkout keeping it;
  - state paths that are the tracker's own and leave the archive out;
  - the remote;
  - the same Python in both;
  - the schedule kept from pausing, on scheduled runs only, never failing
    the run.
- **The whole suite:** on Windows (3.10, batches) and on Linux (WSL Ubuntu,
  Python 3.12, the version the workflows use).

## Rollout

1. Merge locally. Snapshot `main` to GitHub under the no-reply identity.
   Pushing `.github/workflows/` needs the gh token's `workflow` scope, which
   only the user can grant: `gh auth refresh -h github.com -s workflow`, with
   the browser signed in to GitHub as VillaKeth.
2. The push starts `live.yml`. Verify:
   - the run;
   - the Pages build after its push;
   - that the served `run.json` and pages name the new run;
   - that an open page takes the run.
