"""The storage seam: SQLite-backed play history, opened for the life of the bot.

Everything else in Alfred is stateless - the recap is the first feature that needs history, so
this module is deliberately the only place that touches disk. SQLite is stdlib, needs no
server, and the single file lives on a mounted volume so it survives container rebuilds.

Two tables. `users` is one row per Discord user the bot has seen queue something, carrying the
name snapshot that lets the database answer "who" on its own - it records the user, not just a
snowflake. `plays` is the event log: one row per track start, pointing at the user who queued
it and carrying the track's details denormalized, because track metadata drifts and the recap
reads it as flat rows.

A legacy single-table schema (plays with a bare `requester_id`) is migrated in place on first
open: the distinct requesters become `users` rows and the plays keep their history.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from pathlib import Path

# How far back plays are kept. A recap needs a week; a month of history is plenty of buffer,
# and pruning keeps the file from growing without bound. User rows are never pruned - they are
# the names the plays point at, not history.
RETENTION_DAYS = 60

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL DEFAULT '',
    display_name TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS plays (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    guild_id INTEGER NOT NULL,
    track_title TEXT NOT NULL,
    track_author TEXT,
    track_uri TEXT,
    duration_ms INTEGER,
    played_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_plays_week ON plays (guild_id, played_at);
CREATE INDEX IF NOT EXISTS idx_plays_user ON plays (user_id, played_at);
"""

# The row shape `PlayStore.weekly` and `user_plays` return, kept as one tuple so every reader
# unpacks the same positions: title, author, uri, duration_ms, user_id(weekly only), played_at.
_PLAY_COLUMNS = "track_title, track_author, track_uri, duration_ms, played_at"


class PlayStore:
    """A SQLite-backed store of plays and the users who queued them."""

    def __init__(self, path: Path) -> None:
        self._conn = sqlite3.connect(path)
        # Foreign keys are off by default in SQLite; the plays->users reference is only real
        # if this connection enforces it.
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._migrate_legacy()
        # Multi-statement schema needs executescript, not execute - sqlite3 refuses the
        # CREATE TABLE + CREATE INDEX pair in one execute call.
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def _migrate_legacy(self) -> None:
        """
        Move a pre-users `plays` table (bare `requester_id`) onto the two-table model.

        Detected by the column set: the legacy table has `requester_id` and no `user_id`. The
        table is renamed out of the way, the new schema is created over its name, the legacy
        plays are copied across (distinct requesters become user rows), and the legacy table is
        dropped. No data is lost, and a fresh database never takes this path.

        `executescript` commits whatever transaction is open before it runs, so this deliberately
        does not wrap itself in a `with self._conn:` block - the commit at the end of `__init__`
        is the single point where the migration becomes durable.
        """
        columns = {row[1] for row in self._conn.execute("PRAGMA table_info(plays)")}
        if "user_id" in columns or "requester_id" not in columns:
            return

        self._conn.execute("ALTER TABLE plays RENAME TO plays_legacy")
        # The legacy table's index keeps its name when the table is renamed, and `IF NOT EXISTS`
        # would then skip creating one for the fresh `plays` - drop it so the schema re-creates it.
        self._conn.execute("DROP INDEX IF EXISTS idx_plays_week")
        self._conn.executescript(_SCHEMA)
        self._conn.execute(
            "INSERT INTO users (id) SELECT DISTINCT requester_id FROM plays_legacy WHERE requester_id IS NOT NULL"
        )
        self._conn.execute(
            "INSERT INTO plays (user_id, guild_id, track_title, track_author, track_uri, duration_ms, played_at)"
            " SELECT requester_id, guild_id, track_title, track_author, track_uri, duration_ms, played_at"
            " FROM plays_legacy WHERE requester_id IS NOT NULL"
        )
        self._conn.execute("DROP TABLE plays_legacy")

    def upsert_user(
        self,
        user_id: int,
        *,
        username: str = "",
        display_name: str = "",
        seen_at: datetime | None = None,
    ) -> None:
        """Record or refresh a user's name snapshot. Called when a command names the user."""
        now = (seen_at or datetime.now(timezone.utc)).isoformat(timespec="seconds")
        self._conn.execute(
            "INSERT INTO users (id, username, display_name, last_seen_at) VALUES (?, ?, ?, ?)"
            " ON CONFLICT(id) DO UPDATE SET username = excluded.username,"
            " display_name = excluded.display_name, last_seen_at = excluded.last_seen_at",
            (user_id, username, display_name, now),
        )
        self._conn.commit()

    def record_play(
        self,
        *,
        user_id: int,
        guild_id: int,
        title: str,
        author: str | None,
        uri: str | None,
        duration_ms: int | None,
        played_at: datetime,
    ) -> None:
        """
        Record one play. Called on every track start, so a skip counts as a play.

        The user row is created if this is the first time the store has seen the snowflake -
        the foreign key demands it, and the recorder only knows the id, never the name. Names
        arrive later, when the user next runs a slash command; the id is enough to answer "who
        played this" from the start.
        """
        iso = played_at.isoformat(timespec="seconds")
        with self._conn:
            self._conn.execute(
                "INSERT OR IGNORE INTO users (id, last_seen_at) VALUES (?, ?)",
                (user_id, iso),
            )
            self._conn.execute(
                "INSERT INTO plays (user_id, guild_id, track_title, track_author, track_uri, duration_ms, played_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, guild_id, title, author, uri, duration_ms, iso),
            )

    def weekly(self, guild_id: int, since: datetime, until: datetime | None = None) -> list[tuple]:
        """The week's plays for a guild, newest first. Until defaults to now."""
        rows = self._conn.execute(
            "SELECT track_title, track_author, track_uri, duration_ms, user_id, played_at"
            " FROM plays WHERE guild_id = ? AND played_at >= ?"
            + (" AND played_at < ?" if until is not None else "")
            + " ORDER BY played_at DESC",
            self._plays_params(guild_id, since, until),
        ).fetchall()
        return [tuple(row) for row in rows]

    def user_plays(
        self,
        user_id: int,
        *,
        guild_id: int | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
    ) -> list[tuple]:
        """Everything one user queued, newest first; optionally scoped to a guild or window."""
        clauses = ["user_id = ?"]
        values: list[object] = [user_id]
        if guild_id is not None:
            clauses.append("guild_id = ?")
            values.append(guild_id)
        if since is not None:
            clauses.append("played_at >= ?")
            values.append(since.isoformat(timespec="seconds"))
        if until is not None:
            clauses.append("played_at < ?")
            values.append(until.isoformat(timespec="seconds"))

        rows = self._conn.execute(
            f"SELECT {_PLAY_COLUMNS} FROM plays WHERE " + " AND ".join(clauses) + " ORDER BY played_at DESC",
            tuple(values),
        ).fetchall()
        return [tuple(row) for row in rows]

    def users(self) -> list[tuple]:
        """Every user the store has seen, most recent first, for inspection and embeds."""
        rows = self._conn.execute(
            "SELECT id, username, display_name, last_seen_at FROM users ORDER BY last_seen_at DESC"
        ).fetchall()
        return [tuple(row) for row in rows]

    def prune(self, before: datetime) -> int:
        """Delete plays older than `before`, returning how many rows were removed."""
        cursor = self._conn.execute("DELETE FROM plays WHERE played_at < ?", (before.isoformat(timespec="seconds"),))
        self._conn.commit()
        return cursor.rowcount

    def _plays_params(self, guild_id: int, since: datetime, until: datetime | None) -> tuple:
        """The parameters for `weekly`, built to match its optional `until` clause."""
        values: list[object] = [guild_id, since.isoformat(timespec="seconds")]
        if until is not None:
            values.append(until.isoformat(timespec="seconds"))
        return tuple(values)


def retention_cutoff(now: datetime) -> datetime:
    """The oldest play worth keeping, for `prune`."""
    return now - timedelta(days=RETENTION_DAYS)