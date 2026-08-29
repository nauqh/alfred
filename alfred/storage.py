"""The storage seam: a SQLite-backed track-play record, opened for the life of the bot.

Everything else in Alfred is stateless - the recap is the first feature that needs history, so
this module is deliberately the only place that touches disk. SQLite is stdlib, needs no
server, and the single file lives on a mounted volume so it survives container rebuilds.

Only plays are recorded. Guilds, users and config stay where they are - a play is one row,
and everything the weekly recap reads comes out of this one table.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from datetime import timedelta
from pathlib import Path

# How far back plays are kept. A recap needs a week; a month of history is plenty of buffer,
# and pruning keeps the file from growing without bound.
RETENTION_DAYS = 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY,
    guild_id INTEGER NOT NULL,
    track_title TEXT NOT NULL,
    track_author TEXT,
    track_uri TEXT,
    duration_ms INTEGER,
    requester_id INTEGER,
    played_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plays_week ON plays (guild_id, played_at);
"""


class PlayStore:
    """A SQLite-backed store of plays. One instance for the life of the bot."""

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(path)
        # Multi-statement schema needs executescript, not execute - sqlite3 refuses the
        # CREATE TABLE + CREATE INDEX pair in one execute call.
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def record_play(
        self,
        *,
        guild_id: int,
        title: str,
        author: str | None,
        uri: str | None,
        duration_ms: int | None,
        requester_id: int,
        played_at: datetime,
    ) -> None:
        """Record one play. Called on every track start, so a skip counts as a play."""
        self._conn.execute(
            "INSERT INTO plays (guild_id, track_title, track_author, track_uri, duration_ms, requester_id, played_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, title, author, uri, duration_ms, requester_id, played_at.isoformat(timespec="seconds")),
        )
        self._conn.commit()

    def weekly(self, guild_id: int, since: datetime, until: datetime | None = None) -> list[tuple]:
        """The week's plays for a guild, newest first. Until defaults to now."""
        rows = self._conn.execute(
            "SELECT track_title, track_author, track_uri, duration_ms, requester_id, played_at"
            " FROM plays WHERE guild_id = ? AND played_at >= ?"
            + (" AND played_at < ?" if until is not None else "")
            + " ORDER BY played_at DESC",
            self._params(guild_id, since, until),
        ).fetchall()
        return [tuple(row) for row in rows]

    def _params(self, guild_id: int, since: datetime, until: datetime | None) -> tuple:
        """The parameters for `weekly`, built to match its optional `until` clause."""
        values: list[object] = [guild_id, since.isoformat(timespec="seconds")]
        if until is not None:
            values.append(until.isoformat(timespec="seconds"))
        return tuple(values)

    def prune(self, before: datetime) -> int:
        """Delete plays older than `before`, returning how many rows were removed."""
        cursor = self._conn.execute("DELETE FROM plays WHERE played_at < ?", (before.isoformat(timespec="seconds"),))
        self._conn.commit()
        return cursor.rowcount


def retention_cutoff(now: datetime) -> datetime:
    """The oldest play worth keeping, for `prune`."""
    return now - timedelta(days=RETENTION_DAYS)