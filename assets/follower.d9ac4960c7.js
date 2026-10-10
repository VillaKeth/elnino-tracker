var elninoLive = (function () {
  "use strict";
  // The site is asked which run it serves every minute. A page that loads
  // again for a new run waits until the reader has left it alone for two
  // minutes, and names the run it then shows for six seconds. A run that does
  // not arrive is gone for again after 2, 5 and 10 minutes, then every 15.
  // The reader's place, once put back, is held for 15 seconds as the page settles.
  var ASK = 60000, QUIET = 120000, NOTE = 6000, HOLD = 15000, PAUSES = [2, 5, 10, 15];
  // The reader's hand on the page: what moves after it is their doing.
  var HANDS = ["pointerdown", "keydown", "wheel", "touchstart"];
  // Where a page hands its place to itself across a load, one key a page; the
  // script in the page's head (live.head) reads the theme from it.
  var KEY = "elnino-live:" + location.pathname;
  var MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  var opts = {}, store = null, note = null, timer = 0, quietSince = 0;
  var want = {run: null, tries: 0, next: 0};  // the run last gone for, and when it may be again
  var pending = null;                         // the run the notice offers
  var declined = null;                        // the run the reader put off with Later
  var inPlace = false;                        // a new run is taken in place, not loaded
  var taking = false;                         // a run is being taken in place
  var broken = false;                         // a take failed part way, leaving the page between runs
  var reloading = false;                      // the page is loading again, its place handed over
  var touched = 0;                            // the reader's hands on the page, counted
  var unshown = null;                         // the place a hidden page holds once it is shown

  function num(v) { return typeof v === "number" && isFinite(v) ? v : 0; }
  function mark() { return document.querySelector('meta[name="elnino-run"]'); }
  function shown() { var m = mark(); return m ? m.getAttribute("content") : null; }
  // One run however it is written: "...Z" and "...+00:00" are one moment.
  function same(a, b) {
    if (a === b) return true;
    var x = Date.parse(a), y = Date.parse(b);
    return !isNaN(x) && x === y;
  }
  // A run before another: the site answering from a cache its move has not
  // reached yet, or a run put back on purpose. Never a new run for the page.
  function older(a, b) {
    var x = Date.parse(a), y = Date.parse(b);
    return !isNaN(x) && !isNaN(y) && x < y;
  }
  function pad(n) { return (n < 10 ? "0" : "") + n; }
  function when(run) {
    var d = new Date(Date.parse(run));
    if (isNaN(d.getTime())) return run;
    return pad(d.getUTCDate()) + " " + MONTHS[d.getUTCMonth()] + " " + d.getUTCFullYear() + " " +
           pad(d.getUTCHours()) + ":" + pad(d.getUTCMinutes()) + " UTC";
  }

  // ---- the place a page hands itself ----------------------------------------
  // sessionStorage, when the browser keeps it for this page: a private window,
  // or a site whose data are blocked, may keep none.
  function storage() {
    try {
      var s = window.sessionStorage;
      s.setItem(KEY + "?", "1");
      s.removeItem(KEY + "?");
      return s;
    } catch (e) { return null; }
  }
  function handed() {
    try { return JSON.parse(store.getItem(KEY)); } catch (e) { return null; }
  }
  function hand(record) {
    try { store.setItem(KEY, JSON.stringify(record)); return true; } catch (e) { return false; }
  }
  function forget() {
    try { store.removeItem(KEY); } catch (e) { /* left, it is read once more and found stale */ }
  }
  // The page's own state, kept and put back by its own code: code that fails
  // costs the reader that state, never the following.
  function hook(name, arg) {
    try { return opts[name] ? opts[name](arg) : null; } catch (e) { return null; }
  }
  // Where the reader is: the scroll of the page and of each of its boxes,
  // what stands at the top of each (marks, below), the theme, each section
  // open or shut by its summary's words (a new run's page may have a section
  // more or fewer, so a count would set the wrong ones), and what the page
  // keeps of its own.
  function place() {
    var sections = [], tops = {}, list = document.querySelectorAll("details > summary");
    for (var i = 0; i < list.length; i++) sections.push([list[i].textContent, list[i].parentNode.open]);
    boxes().forEach(function (box) { tops[box.id] = box.scrollTop; });
    return {x: window.scrollX, y: window.scrollY, boxes: tops, marks: marks(), sections: sections,
            theme: document.documentElement.getAttribute("data-theme"), kept: hook("keep")};
  }
  // What storage hands back is read like input: the page's own state only
  // from an object, a section only from its words and a flag, the scroll only
  // from numbers. The page's own state comes first, as it may write what the
  // sections are in, and the scroll last, once what is above it stands: in
  // pixels, then by the marks, as what is above may stand short of where it
  // will (words still to wrap, a fetch still to answer), and is held so.
  function putBack(p) {
    if (!p || typeof p !== "object") return;
    if (p.kept && typeof p.kept === "object") hook("restore", p.kept);
    var left = Array.isArray(p.sections) ? p.sections.slice() : [];
    var list = document.querySelectorAll("details > summary");
    for (var i = 0; i < list.length; i++) {
      for (var j = 0; j < left.length; j++) {
        if (Array.isArray(left[j]) && left[j][0] === list[i].textContent && typeof left[j][1] === "boolean") {
          list[i].parentNode.open = left[j][1];
          left.splice(j, 1);
          break;
        }
      }
    }
    var tops = p.boxes && typeof p.boxes === "object" ? p.boxes : {};
    (opts.boxes || []).forEach(function (id) {
      var box = document.getElementById(id), top = tops[id];
      if (box && typeof top === "number" && isFinite(top)) box.scrollTop = top;
    });
    window.scrollTo(num(p.x), num(p.y));
    regain(p.marks);
    holdOn(p.marks);
  }

  // ---- what stands at the top of the view ------------------------------------
  // A place in pixels is lost when what is above it changes height: words that
  // wrap again, a fetch answered, a run with a storm more. So the place in each
  // of the page's boxes is held by marks too: nodes with an id, found again by
  // it whatever the page has become, each with where it stood.
  function boxes() {
    return (opts.boxes || []).map(function (id) { return document.getElementById(id); })
      .filter(function (box) { return box !== null; });
  }
  // The line a box's marks are found on: its top, in a box that scrolls
  // itself; in one the page scrolls, if the box is there, the top of what
  // the reader sees of the view, below what the page pins over it (the
  // dashboard's menu). A box, or a page, at its top has none: what comes in
  // above is the reader's to see, as a browser that anchors scrolling has it
  // (Here opened at the top of the panel, a banner at the top of the page).
  function topLine(box, scrolls) {
    var r = box.getBoundingClientRect();
    if (scrolls) return box.scrollTop > 0 ? r.top : null;
    var line = pinned();
    return window.scrollY > 0 && r.top <= line && r.bottom > line ? line : null;
  }
  // How far down the view the page pins something over it, in pixels, as it
  // tells the browser: its scroll-padding-top, or none where it gives none.
  function pinned() {
    var style = window.getComputedStyle ? window.getComputedStyle(document.documentElement) : null;
    var px = style ? parseFloat(style.scrollPaddingTop) : NaN;
    return isFinite(px) ? px : 0;
  }
  function marks() {
    return boxes().map(function (box) {
      var scrolls = box.scrollHeight > box.clientHeight, line = topLine(box, scrolls);
      var found = line === null ? [] : marksAt(box, line);
      return {box: box.id, scrolls: scrolls,
              marks: found.map(function (el) { return {id: el.id, at: standing(el, box, scrolls)}; })};
    }).filter(function (held) { return held.marks.length > 0; });
  }
  // The nodes with an id that a line across a box runs through, or the first
  // below it where it runs between two, deepest first: at each depth, the
  // first that reaches below the line.
  function marksAt(box, line) {
    var found = [];
    for (var el = box.firstElementChild; el; ) {
      if (el.getBoundingClientRect().bottom <= line) el = el.nextElementSibling;
      else { if (el.id) found.unshift(el); el = el.firstElementChild; }
    }
    return found;
  }
  // Where a node stands: from the top of its box, if that scrolls itself, or
  // of the view.
  function standing(el, box, scrolls) {
    return el.getBoundingClientRect().top - (scrolls ? box.getBoundingClientRect().top : 0);
  }
  // A box's marks as the page now stands: the deepest still shown, how far it
  // is from where it stood, and the scroll it is read against. What storage
  // hands back is read like input: a box and a mark only by an id, a mark
  // only standing at a number.
  function locate(held) {
    if (!held || typeof held !== "object" || typeof held.box !== "string" || !Array.isArray(held.marks)) return null;
    var box = document.getElementById(held.box), scrolls = held.scrolls === true;
    if (!box) return null;
    for (var i = 0; i < held.marks.length; i++) {
      var m = held.marks[i], el = m && typeof m.id === "string" ? document.getElementById(m.id) : null;
      if (el && box.contains(el) && el.getClientRects().length && typeof m.at === "number" && isFinite(m.at)) {
        return {box: box, scrolls: scrolls, off: standing(el, box, scrolls) - m.at,
                scroll: scrolls ? box.scrollTop : window.scrollY};
      }
    }
    return null;
  }
  function scrolled(held) { var s = locate(held); return s ? s.scroll : null; }
  function move(s) {
    if (s.scrolls) s.box.scrollTop += s.off;
    else window.scrollBy(0, s.off);
  }
  function holds(held) { return Array.isArray(held) ? held : []; }
  // Each box put back where its marks stood.
  function regain(held) {
    holds(held).forEach(function (h) {
      var s = locate(h);
      if (s && s.off) move(s);
    });
  }
  // A page goes on settling once its place is put back: words wrap again, a
  // fetch answers. A browser that anchors scrolling holds the view through
  // that itself, as Safari does only from 27, so for HOLD the marks hold it
  // too, each frame: a mark moved while the view stood still takes the view
  // with it. The view moved by anything else (the reader's scroll, or the
  // page's own, however slow), or the reader's hand on the page, ends the
  // hold. A hidden page draws no frames: its hold waits until it is shown.
  function holdOn(held) {
    held = holds(held);
    if (typeof window.requestAnimationFrame !== "function" ||
        !held.some(function (h) { return locate(h) !== null; })) return;
    if (document.hidden) { unshown = held; return; }
    var until = Date.now() + HOLD, hands = touched, last = held.map(scrolled);
    window.requestAnimationFrame(function frame() {
      if (Date.now() >= until || touched !== hands) return;
      for (var i = 0; i < held.length; i++) {
        var s = locate(held[i]);
        if (!s || Math.abs(s.off) < 1) continue;
        if (last[i] !== null && s.scroll !== last[i]) return;
        move(s);
      }
      last = held.map(scrolled);
      window.requestAnimationFrame(frame);
    });
  }
  // A hidden page shown again: what moved meanwhile put back, and the place
  // held from now.
  function shownAgain() {
    var held = unshown;
    unshown = null;
    if (held) { regain(held); holdOn(held); }
  }
  // A page taking a run in place holds the reader's place through the take.
  // Chrome holds it by a node it anchors to, and loses it when a take swaps
  // that node for the new run's: the view was thrown 238 px down the desk's
  // panel, and 3,050 px up a phone's page. So the browser's anchoring is off
  // through the take, and the function returned puts the place back by its
  // marks, then holds it as the page settles.
  function hold() {
    var held = marks(), anchored = [document.documentElement].concat(boxes());
    anchored.forEach(function (el) { el.style.overflowAnchor = "none"; });
    return function () {
      regain(held);
      anchored.forEach(function (el) { el.style.overflowAnchor = ""; });
      holdOn(held);
    };
  }

  // ---- the notice -------------------------------------------------------------
  // Its words are set as text, never as markup. A page a take left between
  // two runs is not one to keep as it is, so it offers no Later.
  function say(words, offer) {
    note.textContent = "";
    if (!words) return;
    var p = document.createElement("p");
    p.textContent = words;
    if (offer) {
      p.appendChild(button("Update now", function () { load(true); }));
      if (!broken) p.appendChild(button("Later", later));
    }
    note.appendChild(p);
  }
  function button(words, act) {
    var b = document.createElement("button");
    b.type = "button";
    b.textContent = words;
    b.addEventListener("click", act);
    return b;
  }

  // ---- following the site -------------------------------------------------------
  function due(run) { return run !== want.run || Date.now() >= want.next; }
  // Going for a run counts a try at it, and holds the next try back by a
  // pause that grows with them.
  function goFor(run) {
    var tries = run === want.run ? want.tries + 1 : 1;
    want = {run: run, tries: tries, next: Date.now() + PAUSES[Math.min(tries, PAUSES.length) - 1] * 60000};
  }
  function consider(run) {
    if (same(run, shown())) { withdraw(); return; }
    if (older(run, shown()) || older(run, pending) || same(run, declined)) return;
    if (run === pending || taking || !due(run)) return;
    if (inPlace) takeInPlace(run);
    else offer(run);
  }
  // A run offered, and loaded once the reader has left the page alone, or at
  // once if the page is put away; a page that may not load on its own only
  // offers it.
  function offer(run) {
    pending = run;
    var taken = broken ? ", which this page could take only in part." : ".";
    say("The site has a new run, from " + when(run) + taken, true);
    if (!mayLoad()) return;
    if (document.hidden) load(false);
    else settle();
  }
  // Whether the page may load again on its own: only with its place handed
  // over, and never for a reader saving data, who is only offered the run.
  function mayLoad() {
    var connection = window.navigator && window.navigator.connection;
    return store !== null && !(connection && connection.saveData);
  }
  // A page that cannot take a run in place answers false: another code wrote
  // it. That run is offered and loaded as on any other page, and so is each
  // after it. A take that throws failed part way, leaving the page between
  // two runs: so too, with no Later.
  function takeInPlace(run) {
    goFor(run);
    taking = true;
    Promise.resolve().then(opts.take).then(function (taken) {
      taking = false;
      if (taken === false) loadFor(run);
    }, function () {
      taking = false;
      broken = true;
      loadFor(run);
    });
  }
  function loadFor(run) {
    inPlace = false;
    offer(run);
  }
  // The run offered is loaded once the reader has left the page alone long
  // enough; a reader still at it puts it off.
  function settle() {
    clearTimeout(timer);
    var wait = quietSince + QUIET - Date.now();
    if (wait <= 0) load(false);
    else timer = setTimeout(settle, wait);
  }
  // Loading again for the run offered, its place and its pause handed over
  // first. Asked for, the page loads whatever storage does; on its own, only
  // when they were handed over, or it could load again and again.
  function load(asked) {
    clearTimeout(timer);
    goFor(pending);
    var where = place();
    var handedOver = store !== null && hand({run: want.run, tries: want.tries, next: want.next, place: where});
    if (handedOver) {
      reloading = true;
      if (where.marks.length) browserScrolls(false);
    }
    if (handedOver || asked) { location.reload(); return; }
    store = null;  // storage refused the write: from here on the page only offers
  }
  // The browser puts the scroll back on a load too, and its last try can come
  // after the follower's: on a phone, Chrome's came 20 ms later and undid the
  // place put back by its marks. So across a load that hands marks over the
  // browser leaves the scroll alone until the page loaded again has finished
  // loading, and keeps it again from then: for the reader's own loads, and
  // for a tab it puts away and brings back. A place in pixels alone it puts
  // back as the follower does, trying again as the page grows.
  function browserScrolls(yes) {
    try { window.history.scrollRestoration = yes ? "auto" : "manual"; }
    catch (e) { /* the browser keeps to its own way */ }
  }
  function withdraw() {
    if (pending === null) return;
    pending = null;
    clearTimeout(timer);
    say("");
  }
  // Later: the page stays as it is. The run offered is not offered, or
  // loaded, again; the next one is.
  function later() {
    declined = pending;
    withdraw();
  }
  // A page loaded again: the place handed over is put back, once, and either
  // the page shows the run it was loaded for and says so for a moment, or it
  // does not, and that run waits out its pause.
  function arrive() {
    var record = handed();
    if (!record || typeof record !== "object") return;
    putBack(record.place);
    onceLoaded(function () { browserScrolls(true); });
    var run = typeof record.run === "string" ? record.run : null;
    if (run !== null && !same(run, shown())) {
      want = {run: run, tries: Math.max(1, Math.floor(num(record.tries))),
              next: Math.min(num(record.next), Date.now() + PAUSES[PAUSES.length - 1] * 60000)};
      hand(want);
      return;
    }
    forget();
    if (run === null) return;
    say("Now showing the run of " + when(run) + ".");
    setTimeout(function () { if (pending === null) say(""); }, NOTE);
  }
  // Once the page has loaded, the browser's own tries to put its scroll back
  // over with it.
  function onceLoaded(fn) {
    function soon() { setTimeout(fn, 0); }
    if (document.readyState === "complete") soon();
    else window.addEventListener("load", soon);
  }
  // A load asked for as the reader left the page is not made: a page the
  // browser kept, and shows again, holds no place for it, keeps the scroll
  // the browser's way, and offers the run as before.
  function shownFromCache(e) {
    if (!e.persisted || !reloading) return;
    reloading = false;
    forget();
    browserScrolls(true);
    if (pending !== null && mayLoad()) settle();
  }
  // What the site answers is read like input: only a run named in words counts.
  function ask() {
    fetch(new URL("run.json", location.href), {cache: "no-store"})
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (beacon) {
        var run = beacon && beacon.run_at;
        if (typeof run === "string" && run) consider(run);
      });
  }

  // The assets a page names are named for their contents, and GitHub Pages
  // sends every file again after each publish: the site's service worker
  // (sw.js) keeps them, told this page's at once so they are kept from a
  // first visit on. It needs a secure origin; refused one, the page goes on
  // with the browser's own cache.
  function keepAssets() {
    var workers = window.isSecureContext && navigator.serviceWorker;
    if (!workers) return;
    var mine = assetsOf(document).split(" ").filter(Boolean).map(function (src) {
      return new URL(src, location.href).href;
    });
    workers.register("sw.js").then(function () { return workers.ready; }).then(function (reg) {
      if (reg && reg.active) reg.active.postMessage({keep: mine});
    }).catch(function () { /* no worker: the browser's own cache, as before */ });
  }

  function follow(options) {
    if (!/^https?:$/.test(location.protocol) || !shown()) return;
    keepAssets();
    opts = options || {};
    inPlace = !!opts.take;
    note = document.createElement("div");
    note.className = "livenote";
    note.setAttribute("role", "status");
    document.body.appendChild(note);
    store = storage();
    if (store) arrive();
    quietSince = Date.now();
    HANDS.concat(["pointermove", "scroll"]).forEach(function (type) {
      var hand = HANDS.indexOf(type) >= 0;
      window.addEventListener(type, function () {
        quietSince = Date.now();
        if (hand) touched += 1;
      }, {capture: true, passive: true});
    });
    // A page shown again asks at once, and gives a reader just come back to it
    // the time to read before it loads; a page put away loads what it offered.
    document.addEventListener("visibilitychange", function () {
      if (!document.hidden) { quietSince = Date.now(); shownAgain(); ask(); }
      else if (pending !== null && mayLoad()) load(false);
    });
    window.addEventListener("online", ask);
    window.addEventListener("pagehide", function () { if (!reloading) browserScrolls(true); });
    window.addEventListener("pageshow", shownFromCache);
    ask();
    setInterval(ask, ASK);
  }
  // A page that took a run in place names it, from the page it read.
  function shows(doc) {
    var mine = mark(), theirs = doc.querySelector('meta[name="elnino-run"]');
    if (mine && theirs) mine.setAttribute("content", theirs.getAttribute("content"));
  }
  // Whether a page read from the site was written by this page's own code and
  // names the same assets, the code and data that are the same from run to
  // run (elnino/assets.py): only then are its markup and data this page's to
  // take in place.
  function code(doc) {
    var m = doc.querySelector('meta[name="elnino-code"]');
    return m ? m.getAttribute("content") : null;
  }
  function assetsOf(doc) {
    return [].map.call(doc.querySelectorAll('script[src^="assets/"]'), function (s) {
      return s.getAttribute("src");
    }).join(" ");
  }
  function sameCode(doc) {
    var mine = code(document);
    return mine !== null && mine === code(doc) && assetsOf(document) === assetsOf(doc);
  }

  return {follow: follow, shows: shows, sameCode: sameCode, hold: hold};
})();