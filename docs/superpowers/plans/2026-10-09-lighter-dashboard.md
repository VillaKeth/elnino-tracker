# Lighter Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The dashboard carries each thing it draws once and compactly: about
540 KB gzip where it is 882, with nothing on it drawn differently.

**Architecture:** One path encoder (`svg.relative_d`) writes every coastline,
and its twin in the globe's script writes the globe's cells, coast and
graticule. A field drawn as a picture is one grey-index PNG coloured per theme
by filters defined once in the page (`fields.ramp_defs`); the globe reads its
classes from the global map's picture through a canvas. A field chart's hover
blocks are one element's data, read by the page's tooltip.

**Tech Stack:** Python 3 standard library; plain ES5-style browser JavaScript
in the page; node for the JS tests; headless Chrome and Playwright's Firefox
for checks.

**Spec:** `docs/superpowers/specs/2026-10-09-lighter-dashboard-design.md`

## Global Constraints

- Standard library only in Python; no build step; pages work served and from a file.
- Nothing on the page drawn differently: same vertices at the same tenth of a unit, same classes, same palette colours, same tooltip words.
- No new request: the globe reads a picture the page already carries.
- Every new JS function reachable by an existing node harness is added to that harness's list.
- Tests: `python <batches.py> <logdir> 8` all green; README test count updated.

## Review Focus

- The OS in dark mode with no theme chosen: the pictures take the dark palette through the media query, not only through the toggle.
- The globe dragged or clicked in the first instant after load, before its picture is read: the gesture applies once it is read; the globe never redraws without its cells.
- A pointer over a no-data block, between blocks or off the grid: no tooltip, and no stale one left showing.
- The chart scaled to a phone's width: the pointer finds the block under it through the screen-to-plot transform, not the raw offset.
- A browser that cannot read the picture through a canvas: the globe stays as the server drew it and a click still names its regions.

---

### Task 1: Coastlines as relative paths

**Files:** `elnino/svg.py` (`relative_d`); `elnino/fields.py` (`draw_coast`); `elnino/storms.py` (`_coast`); tests in `tests/test_tracker.py`.

**Produces:** `svg.relative_d(lines) -> str`: for each polyline of `(x, y)` plot
points, `M` and its first vertex, then `l` and each later vertex's step from the
one before, every vertex first rounded to a tenth as `f"{v:.1f}"` rounds it; a
step that rounds to nothing left out, and a line left with no step dropped;
numbers in their shortest form (`.5`, `-1.2`, `0`, `12`), a space between two
numbers unless the second starts with `-`.

- [ ] Tests: the path read back (running sum) is the vertices as `.1f` writes them, less repeats; the shortest forms; a line of one point, or of one point repeated, is not drawn; the global map's and the track map's coast read back to exactly the vertices the absolute paths had.
- [ ] Watch fail; implement; pass; suite.

### Task 2: The globe drawn as paths

**Files:** `elnino/globe.py` (`_cells`, `_coast`, `_graticule`, CSS, `GLOBE_JS` draw); tests in `tests/test_tracker.py`.

**Produces:** server `_cells(...) -> list[str]` one `<path d="..." fill="var(--dN)"/>` a class, each run a quad subpath; `_coast` and `_graticule` one `<path d="..."/>` each (empty list when nothing shows). JS `relD(lines)` (the same encoding, `Math.round(v * 10)`), `lineRuns(points, r)` (the visible runs as `[x, y]` lists); `draw()` writes the same three groups the same way.

- [ ] Tests: the server's first view has at most eleven cell paths and one coast and one graticule path, no polygon or polyline in them; CSS targets `path`; node: `relD` agrees with `relative_d`; node: the script's `draw()` at the home view, read back, has every cell quad, coast and graticule vertex of the server's within 0.11 units.
- [ ] Watch fail; implement; pass; suite.

### Task 3: One picture for both themes

**Files:** `elnino/fields.py` (`grey`, `ramp_defs`, `ramp_css`, `_draw_picture`); `elnino/dashboard.py` (defs in the page's hidden SVG); `tests/test_png.py`; `tests/test_tracker.py` (picture regex).

**Produces:** `fields.grey(i, n) -> int` = `round((i + 0.5) * 255 / n)`;
`fields.ramp_defs() -> str` the filters `ramp-<prefix>-<theme>` (prefixes d, q,
p; `feComponentTransfer`, discrete tables `(c + 0.25) / 255` to five places,
`color-interpolation-filters="sRGB"`); one `<image class="cellimg ramp-<prefix>[ smooth]" ...>`
a field, its palette the greys and a seen-through last entry; CSS
`.cellimg.ramp-<p> { filter: url(#ramp-<p>-light) }` with the dark filter under
the OS's dark preference and under `[data-theme="dark"]`.

- [ ] Tests: one picture a field, its rows the class indices as before, its palette the greys; a table read back as bytes is the palette (light and dark, every prefix); the CSS picks each theme's filter in all three places; the dashboard defines the filters once; smoothing classes as before.
- [ ] Watch fail; implement; pass; suite.
- [ ] Browser: the built dashboard's pictures in each theme, OS dark and toggled, in Chrome and Firefox, colours sampled against the palette.

### Task 4: The globe reads the global map's picture

**Files:** `elnino/fields.py` (`global_ramp`, `as_picture`, `GLOBAL_PICTURE`, picture `id`); `elnino/globe.py` (payload, `_cells` classes, JS reader); tests.

**Produces:** `fields.global_ramp(grid) -> Ramp` (used by `global_map` and
`globe.card`); `fields.as_picture(grid) -> bool`; `fields.GLOBAL_PICTURE`
(`"global-sst"`), the id of the global map's image. Payload `grid` has
`"picture": GLOBAL_PICTURE, "levels": n` and no `"data"` when `as_picture`,
else `"data"` as now. JS `readField(g, done)` fills `g.cells` (`Uint8Array`,
255 for none, the payload's row order) from the picture; `sample` reads
`g.cells` or `g.data`; a draw asked for before the field is read waits for it;
a field that cannot be read leaves the globe as served.

- [ ] Tests: payload without characters for a picture-sized field, with them for a small one; the server's cells use the global ramp's classes; the dashboard's global map image carries the id the globe names; node with a stubbed Image and canvas fed the server's own picture: `g.cells` equals `encode()`'s classes cell for cell; a draw asked for early runs once the field is read; a failed read leaves the svg untouched and a click still reports.
- [ ] Watch fail; implement; pass; suite.

### Task 5: One hover grid a field chart

**Files:** `elnino/fields.py` (`_draw_hits`); `elnino/dashboard.py` (tooltip script, CSS); tests.

**Produces:** one `<rect class="hit hitgrid" x y width height fill="transparent" data-hits='{"x":[...],"y":[...],"xl":[...],"yl":[...],"v":[[...]],"u":"..."}'/>`
a field chart: block edges ascending in plot units, row and column labels in
that order, each block's range as written today or null. JS
`gridHit(el, clientX, clientY) -> {label, value} | null` through
`getScreenCTM().inverse()`; the tooltip shows it, hides on null.

- [ ] Tests: every block the old pass drew has its label and value in the grid, and no other; no-data blocks null; node: `gridHit` at each block's centre returns its words, off the grid or on a null block returns null, through a scaled CTM; the tooltip script hides on null.
- [ ] Watch fail; implement; pass; suite.
- [ ] Browser: hover on the global map, the Pacific map and the SST Hovmöller shows each block's words; a phone-width page too.

### Task 6: Measured, written up, published

- [ ] perf2.mjs phone and desktop, five visits each, no worker and worker, before (perf10 build) and after; README "What stays" and the spec's "Measured after".
- [ ] Full suite; final whole-branch review by a fresh reviewer; fixes red-green.
- [ ] Snapshot push; live run; live check of the dashboard in both engines.
