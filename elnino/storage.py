"""SQLite persistence: the tracker's own memory of what it has seen.

Every run writes a snapshot of the headline state and every raised alert. That
turns a monitoring script into a record: it can say "the Walker index crossed
1.0 on this date", it can avoid shouting the same alert every morning, and if a
NOAA feed later revises a value the archive still holds what was published at
the time.

sqlite3 ships with Python, so this adds no dependency. The schema is created on
first use and migrated forward by adding columns, never by dropping them.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    run_at         TEXT PRIMARY KEY,
    observed_at    TEXT,
    status         TEXT,
    oni_label      TEXT,
    oni            REAL,
    roni           REAL,
    nino34_weekly  REAL,
    nino12_weekly  REAL,
    flavour_index  REAL,
    walker_index   REAL,
    wwv_anomaly    REAL,
    wwv_rank       INTEGER,
    power_index    REAL,
    forecast_peak  REAL,
    forecast_label TEXT,
    episode_length INTEGER,
    payload        TEXT
);

CREATE TABLE IF NOT EXISTS alerts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    code        TEXT NOT NULL,
    level       TEXT NOT NULL,
    title       TEXT NOT NULL,
    detail      TEXT,
    value       REAL,
    first_seen  TEXT NOT NULL,
    last_seen   TEXT NOT NULL,
    cleared_at  TEXT,
    raised_from TEXT,
    raised_at   TEXT,
    ladder_since TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS alerts_open
    ON alerts (code) WHERE cleared_at IS NULL;

CREATE TABLE IF NOT EXISTS series (
    key        TEXT NOT NULL,
    period     TEXT NOT NULL,
    value      REAL NOT NULL,
    recorded_at TEXT NOT NULL,
    PRIMARY KEY (key, period, recorded_at)
);

CREATE TABLE IF NOT EXISTS fetch_log (
    run_at   TEXT NOT NULL,
    key      TEXT NOT NULL,
    ok       INTEGER NOT NULL,
    cached   INTEGER NOT NULL,
    bytes    INTEGER,
    error    TEXT,
    PRIMARY KEY (run_at, key)
);
"""


@dataclass
class Snapshot:
    run_at: str
    values: dict

    def get(self, key: str, default=None):
        return self.values.get(key, default)


# The columns added to a table since it was first made, which a database made
# before them gains on connecting: the level an open alert last rose from, and
# when, and, for an alert raised a rung up its ladder, since when the ladder
# has stood.
ADDED = {"alerts": (("raised_from", "TEXT"), ("raised_at", "TEXT"), ("ladder_since", "TEXT"))}


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    for table, columns in ADDED.items():
        have = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, kind in columns:
            if name not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {kind}")
    conn.commit()
    return conn


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_snapshot(conn: sqlite3.Connection, run_at: str, values: dict) -> None:
    """Insert one run's headline state. Re-running in the same second replaces it."""
    columns = [
        "observed_at", "status", "oni_label", "oni", "roni", "nino34_weekly",
        "nino12_weekly", "flavour_index", "walker_index", "wwv_anomaly",
        "wwv_rank", "power_index", "forecast_peak", "forecast_label",
        "episode_length",
    ]
    payload = json.dumps(values, default=str)
    conn.execute(
        f"INSERT OR REPLACE INTO snapshots (run_at, {', '.join(columns)}, payload) "
        f"VALUES (?, {', '.join('?' * len(columns))}, ?)",
        [run_at] + [values.get(name) for name in columns] + [payload],
    )
    conn.commit()


def baseline(conn: sqlite3.Connection, run_at: str, hours: int = 24) -> Snapshot | None:
    """The state a day before a run, which the change alerts compare it with:
    the latest snapshot at least ``hours`` older than ``run_at``, or, with none
    so old, the earliest before it. Against the run before, a change was on the
    site until the next run, ten minutes at the live run's cadence; against the
    day before, it stays a day, whatever the cadence."""
    cutoff = (datetime.fromisoformat(run_at) - timedelta(hours=hours)).isoformat(timespec="seconds")
    row = conn.execute(
        "SELECT * FROM snapshots WHERE run_at <= ? ORDER BY run_at DESC LIMIT 1", (cutoff,)
    ).fetchone() or conn.execute(
        "SELECT * FROM snapshots WHERE run_at < ? ORDER BY run_at LIMIT 1", (run_at,)
    ).fetchone()
    if row is None:
        return None
    return Snapshot(row["run_at"], {key: row[key] for key in row.keys()})


def snapshot_history(conn: sqlite3.Connection, limit: int = 180) -> list[Snapshot]:
    rows = conn.execute(
        "SELECT * FROM snapshots ORDER BY run_at DESC LIMIT ?", (limit,)
    ).fetchall()
    return [Snapshot(row["run_at"], {k: row[k] for k in row.keys()}) for row in reversed(rows)]


def record_series(
    conn: sqlite3.Connection, recorded_at: str, key: str, points: list[tuple[str, float]]
) -> None:
    """Keep each value an index gives a period, from the run that first saw it,
    so revisions stay visible. A value its period's latest record already holds
    is not written again: every run gave the last 24 seasons, the same values,
    7,000 rows a day at a run every ten minutes."""
    latest = {
        row["period"]: row["value"]
        for row in conn.execute(
            "SELECT period, value FROM series AS s WHERE key = ? AND recorded_at = "
            "(SELECT MAX(recorded_at) FROM series WHERE key = s.key AND period = s.period)",
            (key,),
        )
    }
    conn.executemany(
        "INSERT OR REPLACE INTO series (key, period, value, recorded_at) VALUES (?, ?, ?, ?)",
        [(key, period, value, recorded_at) for period, value in points
         if latest.get(period) != value],
    )
    conn.commit()


def revisions(conn: sqlite3.Connection, key: str, period: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT value, recorded_at FROM series WHERE key = ? AND period = ? "
        "ORDER BY recorded_at",
        (key, period),
    ).fetchall()


def upsert_alert(
    conn: sqlite3.Connection,
    code: str,
    level: str,
    title: str,
    detail: str,
    value: float | None,
    seen_at: str,
) -> bool:
    """Record an alert. Returns True when it is raised, False when it stands.

    A standing alert's level and title are brought up to date - a cyclone
    threat that went from a watch to a strike used to stay logged as the watch
    it was first raised as.
    """
    row = conn.execute(
        "SELECT id FROM alerts WHERE code = ? AND cleared_at IS NULL", (code,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE alerts SET last_seen = ?, value = ?, detail = ?, level = ?, "
            "title = ? WHERE id = ?",
            (seen_at, value, detail, level, title, row["id"]),
        )
        conn.commit()
        return False
    conn.execute(
        "INSERT INTO alerts (code, level, title, detail, value, first_seen, last_seen) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (code, level, title, detail, value, seen_at, seen_at),
    )
    conn.commit()
    return True


def clear_missing_alerts(
    conn: sqlite3.Connection, active_codes: set[str], seen_at: str
) -> list[str]:
    """Close any open alert whose condition no longer holds."""
    open_rows = conn.execute(
        "SELECT id, code FROM alerts WHERE cleared_at IS NULL"
    ).fetchall()
    cleared = []
    for row in open_rows:
        if row["code"] not in active_codes:
            conn.execute(
                "UPDATE alerts SET cleared_at = ? WHERE id = ?", (seen_at, row["id"])
            )
            cleared.append(row["code"])
    if cleared:
        conn.commit()
    return cleared


def raise_alert(conn: sqlite3.Connection, code: str, was: str, seen_at: str) -> None:
    """Note that the open alert ``code`` rose from the level ``was`` at
    ``seen_at``."""
    conn.execute(
        "UPDATE alerts SET raised_from = ?, raised_at = ? WHERE code = ? AND cleared_at IS NULL",
        (was, seen_at, code),
    )
    conn.commit()


def step_alert(conn: sqlite3.Connection, code: str, first_seen: str | None = None,
               ladder_since: str | None = None) -> None:
    """Note of the open alert ``code``, raised as a rung of a ladder in place
    of another, since when it stands, ``first_seen``, as a rung below the one
    it replaced, or since when its ladder has stood, ``ladder_since``, as a
    rung above it."""
    conn.execute(
        "UPDATE alerts SET first_seen = COALESCE(?, first_seen), "
        "ladder_since = COALESCE(?, ladder_since) WHERE code = ? AND cleared_at IS NULL",
        (first_seen, ladder_since, code),
    )
    conn.commit()


def cleared_since(conn: sqlite3.Connection, seen_at: str, span: timedelta) -> list[sqlite3.Row]:
    """The alerts cleared less than ``span`` before ``seen_at``, the latest
    first."""
    since = (datetime.fromisoformat(seen_at) - span).isoformat(timespec="seconds")
    return conn.execute(
        "SELECT * FROM alerts WHERE cleared_at > ? ORDER BY cleared_at DESC", (since,)
    ).fetchall()


def open_alerts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM alerts WHERE cleared_at IS NULL ORDER BY first_seen DESC"
    ).fetchall()


def record_fetches(conn: sqlite3.Connection, run_at: str, fetched: dict) -> None:
    conn.executemany(
        "INSERT OR REPLACE INTO fetch_log (run_at, key, ok, cached, bytes, error) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        [
            (run_at, key, int(item.ok), int(item.from_cache), len(item.text), item.error)
            for key, item in fetched.items()
        ],
    )
    conn.commit()


# How long the fetch log keeps a run's rows. Nothing reads them back but a
# person asking the database. A row a feed a run is 7,200 rows a day at a run
# every ten minutes, 0.7 MB a day in the database the live run carries from
# one run to the next: 20 MB over thirty days, 5 MB over a week.
FETCH_LOG_DAYS = 7


def prune(conn: sqlite3.Connection, run_at: str) -> None:
    """Let go of the fetch log's rows from more than FETCH_LOG_DAYS before
    ``run_at``."""
    cutoff = (datetime.fromisoformat(run_at) - timedelta(days=FETCH_LOG_DAYS)).isoformat(timespec="seconds")
    conn.execute("DELETE FROM fetch_log WHERE run_at < ?", (cutoff,))
    conn.commit()
