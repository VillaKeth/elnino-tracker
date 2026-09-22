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
from datetime import datetime, timezone
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
    cleared_at  TEXT
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


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
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


def previous_snapshot(conn: sqlite3.Connection, before: str) -> Snapshot | None:
    row = conn.execute(
        "SELECT * FROM snapshots WHERE run_at < ? ORDER BY run_at DESC LIMIT 1",
        (before,),
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
    """Keep what each index said on each run, so revisions stay visible."""
    conn.executemany(
        "INSERT OR REPLACE INTO series (key, period, value, recorded_at) VALUES (?, ?, ?, ?)",
        [(key, period, value, recorded_at) for period, value in points],
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
    """Record an alert. Returns True only the first time it is raised.

    That return value is what stops a daily run from re-announcing a condition
    that has been true for a month.
    """
    row = conn.execute(
        "SELECT id FROM alerts WHERE code = ? AND cleared_at IS NULL", (code,)
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE alerts SET last_seen = ?, value = ?, detail = ? WHERE id = ?",
            (seen_at, value, detail, row["id"]),
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


def open_alerts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM alerts WHERE cleared_at IS NULL ORDER BY first_seen DESC"
    ).fetchall()


def alert_log(conn: sqlite3.Connection, limit: int = 50) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM alerts ORDER BY first_seen DESC LIMIT ?", (limit,)
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


def feed_reliability(conn: sqlite3.Connection, key: str, runs: int = 30) -> float:
    """Fraction of the last N runs in which a feed came back live."""
    rows = conn.execute(
        "SELECT ok, cached FROM fetch_log WHERE key = ? ORDER BY run_at DESC LIMIT ?",
        (key, runs),
    ).fetchall()
    if not rows:
        return 1.0
    live = sum(1 for row in rows if row["ok"] and not row["cached"])
    return live / len(rows)
