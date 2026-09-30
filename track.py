#!/usr/bin/env python3
"""El Nino tracker - fetch live ENSO observations, diagnose, forecast, report.

    python track.py                     full run: report, dashboard, JSON
    python track.py --brief             alerts and headline state only
    python track.py --section forecast  print one section (repeatable)
    python track.py --alerts-only       exit non-zero if a WARNING or worse is open
    python track.py --watch             re-run on a schedule until interrupted
    python track.py --offline           use the last cached download, no network
    python track.py --history 20        show the last N runs from the database
    python track.py --open              open the dashboard when it is written
    python track.py --serve             run, then serve the storm desk on this machine
    python track.py --serve --lan       ... and to a tablet on the same network

Exit codes are meaningful, so this can be driven from a scheduler:
    0  ran, nothing above WATCH open
    1  ran, at least one WARNING or CRITICAL alert is open
    2  could not run at all (no data and no cache, or an unexpected error)
    3  ran, but the analysis was degraded by feed or parse failures

Pure standard library: no pip install, nothing to build.
"""

from __future__ import annotations

import argparse
import functools
import json
import socket
import sys
import threading
import time
import traceback
import webbrowser
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from elnino import atlasview, dashboard, pipeline, report, storage, stormdesk
from elnino.alerts import CRITICAL, WARNING

ROOT = Path(__file__).resolve().parent
RAW_DIR = ROOT / "data" / "raw"
DB_PATH = ROOT / "data" / "elnino.db"
OUT_DIR = ROOT / "output"

SERIOUS = (WARNING, CRITICAL)
SERVE_PORT = 8765


def _progress(quiet: bool):
    """Feed-by-feed progress on stderr, so a long fetch does not look hung."""
    if quiet:
        return None
    def report_one(done: int, total: int, key: str) -> None:
        print(f"  [{done:>2}/{total}] {key}", file=sys.stderr, flush=True)

    return report_one


def _show_history(limit: int) -> int:
    conn = storage.connect(DB_PATH)
    try:
        rows = storage.snapshot_history(conn, limit=limit)
        if not rows:
            print("No runs recorded yet.", file=sys.stderr)
            return 0
        print(f"{'run':<20} {'season':<9} {'ONI':>6} {'RONI':>6} {'power':>6} "
              f"{'WWV':>6} {'walker':>7} {'peak':>6}")
        for row in rows:
            def cell(key: str, fmt: str = "{:+.2f}", _row=row) -> str:
                value = _row.get(key)
                return fmt.format(value) if value is not None else "-"
            print(
                f"{row.run_at[:19]:<20} {str(row.get('oni_label') or '-'):<9} "
                f"{cell('oni'):>6} {cell('roni'):>6} "
                f"{cell('power_index', '{:.0f}'):>6} {cell('wwv_anomaly'):>6} "
                f"{cell('walker_index'):>7} {cell('forecast_peak'):>6}"
            )
        print("\nRevisions are tracked separately; a changed past value is an "
              "upstream restatement, not a bug here.", file=sys.stderr)
        return 0
    finally:
        conn.close()


def _run_once(args) -> int:
    out_dir: Path = args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    quiet = args.quiet or args.json_only or args.alerts_only

    if not quiet:
        source = "cache" if args.offline else "NOAA"
        print(f"Fetching ENSO observations from {source}...", file=sys.stderr)

    try:
        state = pipeline.run(
            RAW_DIR,
            DB_PATH,
            offline=args.offline,
            progress=_progress(quiet),
            leads=args.leads,
        )
    except RuntimeError as exc:
        print(f"FATAL: {exc}", file=sys.stderr)
        return 2

    html_path = out_dir / "dashboard.html"
    json_path = out_dir / "latest.json"
    # The atlas is its own file rather than another card. It wants the whole
    # viewport and it ships its own copy of the composite grids and the
    # gazetteer, which is several megabytes a reader who only wanted the ONI
    # should not have to download.
    atlas_path = out_dir / "atlas.html"
    # The storm desk and the map are one page written twice, opened on the
    # storms or on El Nino's effects. Each reads itself again while it is
    # open, so a served page follows each --watch run without being reloaded.
    desk_path = out_dir / "storms.html"
    map_path = out_dir / "map.html"
    desk_json = out_dir / "storms.json"
    if not args.no_files:
        html_path.write_text(dashboard.render(state), encoding="utf-8")
        atlas_path.write_text(atlasview.page(state), encoding="utf-8")
        desk_path.write_text(stormdesk.page(state), encoding="utf-8")
        map_path.write_text(stormdesk.page(state, focus="world"), encoding="utf-8")
        dashboard.write_json(state, json_path)
        stormdesk.write_json(state, desk_json)

    if args.json_only:
        print(json.dumps(dashboard.payload(state), indent=2))
    elif args.alerts_only:
        for alert in state.alert_set.alerts:
            if alert.level in SERIOUS or args.verbose:
                flag = (" NEW" if alert.is_new
                        else f" ESCALATED from {alert.escalated_from.upper()}"
                        if alert.escalated_from else "")
                print(f"{alert.level:<8} {alert.title}{flag}")
    elif args.quiet:
        print(state.assessment.headline)
    elif args.brief:
        print(report.brief(state))
    else:
        sections = tuple(args.section) if args.section else report.SECTIONS
        print(report.render(state, sections=sections))
        if not args.no_files:
            print(f"\nDashboard : {html_path}")
            print(f"Atlas     : {atlas_path}")
            print(f"Storm desk: {desk_path}")
            print(f"El Nino map: {map_path}")
            print(f"JSON      : {json_path}")
            print(f"Database  : {DB_PATH}")

    if args.open_browser and not args.no_files:
        webbrowser.open(html_path.resolve().as_uri())

    if any(alert.level in SERIOUS for alert in state.alert_set.alerts):
        return 1
    if state.degraded:
        return 3
    return 0


def _guarded(args) -> int:
    """One run, with an unexpected failure reported as "could not run".

    Python exits 1 on an uncaught exception, and 1 already means "ran, and a
    serious alert is open" - so a crash would read to a scheduler as a
    successful run with alerts. Caught here, it prints its traceback and
    exits 2; in watch mode the next cycle still runs.
    """
    try:
        return _run_once(args)
    except Exception:  # noqa: BLE001 - reported in full, then mapped to 2
        traceback.print_exc()
        print("FATAL: the run failed unexpectedly; see the traceback above.",
              file=sys.stderr)
        return 2


class DeskHandler(SimpleHTTPRequestHandler):
    """The output directory, read-only: "/" opens the storm desk, nothing is listed."""

    def send_head(self):
        path = unquote(urlsplit(self.path).path)
        if ".." in path.replace("\\", "/").split("/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return None
        if path == "/":
            self.send_response(HTTPStatus.FOUND)
            self.send_header("Location", "/storms.html")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return None
        return super().send_head()

    def list_directory(self, path):
        self.send_error(HTTPStatus.NOT_FOUND)
        return None

    def end_headers(self):
        # --watch rewrites the files in place; a copy kept from an earlier run
        # would show a tablet a desk that is hours old.
        self.send_header("Cache-Control", "no-cache")
        super().end_headers()


def serve(directory: Path, port: int, lan: bool) -> ThreadingHTTPServer:
    """A server for the output directory, bound but not yet running.

    It answers this machine only unless ``lan`` is set; then anyone on the
    network can read the pages, which hold nothing but public data.
    """
    handler = functools.partial(DeskHandler, directory=str(directory))
    return ThreadingHTTPServer(("0.0.0.0" if lan else "127.0.0.1", port), handler)


def _lan_address() -> str:
    """This machine's address on the local network, as a tablet would reach it."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
        try:
            # Connecting a UDP socket sends nothing; it only picks the route.
            probe.connect(("192.0.2.1", 9))
            return probe.getsockname()[0]
        except OSError:
            return "this-computer"


def _where(server, lan: bool) -> str:
    port = server.server_address[1]
    if lan:
        home = f"http://{_lan_address()}:{port}/"
        return (f"Storm desk: {home} and El Nino map: {home}map.html from any device on "
                "this network (anyone on it can read the pages). Ctrl-C to stop.")
    home = f"http://127.0.0.1:{port}/"
    return (f"Storm desk: {home} and El Nino map: {home}map.html on this machine; add "
            "--lan for a tablet. Ctrl-C to stop.")


def _watch(args) -> int:
    """Re-run on a schedule until interrupted."""
    # The upstream feeds update daily at most, so anything under about half
    # an hour is pure load on NOAA for no new information.
    interval = max(args.watch, 15) * 60
    print(f"Watching: re-running every {interval // 60} minutes. Ctrl-C to stop.",
          file=sys.stderr)
    code = 0
    try:
        while True:
            code = _guarded(args)
            print(f"--- next run in {interval // 60} minutes ---", file=sys.stderr)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopped.", file=sys.stderr)
    return code


def _serve(args) -> int:
    """Run, then serve the output directory; with --watch, keep both going."""
    # Bound before the run, so a port already in use is said now rather than
    # after a two-minute fetch.
    try:
        server = serve(args.out, args.serve, args.lan)
    except OSError as exc:
        print(f"FATAL: cannot serve on port {args.serve}: {exc}", file=sys.stderr)
        return 2
    with server:
        if args.watch is not None:
            # The pages already on disk are served while each run fetches.
            threading.Thread(target=server.serve_forever, daemon=True).start()
            print(_where(server, args.lan), file=sys.stderr)
            try:
                return _watch(args)
            finally:
                server.shutdown()
        code = _guarded(args)
        print(_where(server, args.lan), file=sys.stderr)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopped.", file=sys.stderr)
        return code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Track the scale, intensity and likely course of El Nino.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--offline", action="store_true",
                        help="use cached downloads only, no network")
    parser.add_argument("--open", dest="open_browser", action="store_true",
                        help="open the dashboard when it is written")
    parser.add_argument("--brief", action="store_true",
                        help="alerts and headline state only")
    parser.add_argument("--section", action="append", choices=report.SECTIONS,
                        help="print only this section; repeatable")
    parser.add_argument("--alerts-only", action="store_true",
                        help="print open alerts and nothing else")
    parser.add_argument("--verbose", action="store_true",
                        help="with --alerts-only, include INFO and WATCH")
    parser.add_argument("--json-only", action="store_true",
                        help="print the JSON snapshot only")
    parser.add_argument("--quiet", action="store_true",
                        help="write files, print one line")
    parser.add_argument("--no-files", action="store_true",
                        help="skip writing the dashboard and JSON")
    parser.add_argument("--history", type=int, metavar="N",
                        help="print the last N recorded runs and exit")
    parser.add_argument("--watch", type=int, nargs="?", const=60, metavar="MINUTES",
                        help="re-run every N minutes until interrupted")
    parser.add_argument("--leads", type=int, default=9, metavar="N",
                        help="forecast this many seasons ahead (default 9)")
    parser.add_argument("--out", type=Path, default=OUT_DIR, help="output directory")
    parser.add_argument("--serve", type=int, nargs="?", const=SERVE_PORT, metavar="PORT",
                        help=f"after the run, serve the storm desk (default port {SERVE_PORT})")
    parser.add_argument("--lan", action="store_true",
                        help="with --serve, answer other devices on this network")
    args = parser.parse_args(argv)
    if args.lan and args.serve is None:
        parser.error("--lan needs --serve")

    if args.history is not None:
        return _show_history(args.history)
    if args.serve is not None:
        return _serve(args)
    if args.watch is None:
        return _guarded(args)
    return _watch(args)


if __name__ == "__main__":
    raise SystemExit(main())
