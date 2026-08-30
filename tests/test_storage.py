"""The storage model: users, plays, the migration from the legacy schema."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from datetime import timezone

from alfred.storage import PlayStore
from alfred.storage import retention_cutoff


def _now(year: int = 2026, month: int = 8, day: int = 28, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _record(
    store: PlayStore, *, user: int, guild: int = 1, title: str = "Song", played_at: datetime | None = None
) -> None:
    store.record_play(
        user_id=user,
        guild_id=guild,
        title=title,
        author="Artist",
        uri=f"https://song.{title}",
        duration_ms=200_000,
        played_at=played_at or _now(),
    )


def test_record_play_creates_the_user_row(tmp_path) -> None:
    store = PlayStore(tmp_path / "plays.db")
    _record(store, user=7)

    users = store.users()
    assert [(u[0], u[1]) for u in users] == [(7, "")]


def test_upsert_user_records_names(tmp_path) -> None:
    store = PlayStore(tmp_path / "plays.db")
    store.upsert_user(7, username="rick", display_name="Rick")

    assert store.users()[0][:3] == (7, "rick", "Rick")


def test_upsert_user_refreshes_names_not_last_seen(tmp_path) -> None:
    store = PlayStore(tmp_path / "plays.db")
    store.upsert_user(7, username="old", display_name="Old Name", seen_at=_now())
    store.upsert_user(7, username="new", display_name="New Name", seen_at=_now())

    assert store.users()[0][:3] == (7, "new", "New Name")


def test_recording_a_play_for_a_known_user_keeps_the_name(tmp_path) -> None:
    store = PlayStore(tmp_path / "plays.db")
    store.upsert_user(7, username="rick", display_name="Rick")
    _record(store, user=7)

    assert store.users()[0][1] == "rick"


def test_user_plays_lists_what_one_user_queued(tmp_path) -> None:
    store = PlayStore(tmp_path / "plays.db")
    _record(store, user=7, title="A")
    _record(store, user=7, title="B")
    _record(store, user=8, title="C")

    rows = store.user_plays(7)

    assert [r[0] for r in rows] == ["B", "A"]
    assert all(r[4].startswith("2026") for r in rows)


def test_user_plays_can_narrow_by_guild_and_window(tmp_path) -> None:
    store = PlayStore(tmp_path / "plays.db")
    _record(store, user=7, guild=1, title="Here", played_at=_now(2026, 8, 5))
    _record(store, user=7, guild=2, title="There", played_at=_now(2026, 8, 6))
    _record(store, user=7, guild=1, title="Old", played_at=_now(2026, 7, 1))

    # Only guild 1, only after the start of August.
    rows = store.user_plays(7, guild_id=1, since=_now(2026, 8, 1))

    assert [r[0] for r in rows] == ["Here"]


def test_prune_leaves_user_rows_alone(tmp_path) -> None:
    store = PlayStore(tmp_path / "plays.db")
    _record(store, user=7, played_at=_now(2026, 1, 1))
    store.upsert_user(8, username="ghost", display_name="Ghost")

    # 60 days before Sep 1 is early July - the January play is long past it, the users stay.
    removed = store.prune(retention_cutoff(_now(2026, 9, 1)))

    assert removed == 1
    assert [u[0] for u in store.users()] == [8, 7]


def test_a_legacy_database_is_migrated_in_place(tmp_path) -> None:
    """A pre-users plays table keeps its rows; requesters become user rows."""
    path = tmp_path / "plays.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE plays (
            id INTEGER PRIMARY KEY,
            guild_id INTEGER NOT NULL,
            track_title TEXT NOT NULL,
            track_author TEXT,
            track_uri TEXT,
            duration_ms INTEGER,
            requester_id INTEGER,
            played_at TEXT NOT NULL
        );
        CREATE INDEX idx_plays_week ON plays (guild_id, played_at);
        INSERT INTO plays (guild_id, track_title, track_author, track_uri, duration_ms, requester_id, played_at)
        VALUES (1, 'Song', 'Artist', 'https://song', 200000, 7, '2026-08-28T10:00:00'),
               (1, 'Song', 'Artist', 'https://song', 200000, NULL, '2026-08-28T11:00:00'),
               (1, 'Other', 'Someone', 'https://other', 100000, 7, '2026-08-28T12:00:00');
        """
    )
    conn.commit()
    conn.close()

    store = PlayStore(path)
    rows = store.weekly(guild_id=1, since=_now(2026, 8, 1))

    # Both of user 7's plays survived with the user attached; the requester-less one was
    # dropped (there is no user to own it).
    assert [(r[0], r[4]) for r in rows] == [("Other", 7), ("Song", 7)]
    assert [u[0] for u in store.users()] == [7]


def test_migrated_database_still_records_new_plays(tmp_path) -> None:
    path = tmp_path / "plays.db"
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE plays (
            id INTEGER PRIMARY KEY, guild_id INTEGER NOT NULL, track_title TEXT NOT NULL,
            track_author TEXT, track_uri TEXT, duration_ms INTEGER, requester_id INTEGER, played_at TEXT NOT NULL
        );
        """
    )
    conn.commit()
    conn.close()

    store = PlayStore(path)
    _record(store, user=9, title="New")

    assert [r[0] for r in store.user_plays(9)] == ["New"]