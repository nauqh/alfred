"""The weekly recap: schedule math, storage, the embed, and the config."""

from __future__ import annotations

from datetime import datetime
from datetime import timezone

import pytest

from alfred import recap
from alfred.config import ConfigError
from alfred.config import _recap
from alfred.storage import PlayStore
from alfred.storage import retention_cutoff
from alfred.ui import embeds


def _now(year: int = 2026, month: int = 8, day: int = 28, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


# --- next_sunday ---------------------------------------------------------------------------


def test_sunday_morning_rolls_to_next_week() -> None:
    # 2026-08-30 is a Sunday 08:00 - before the 09:00 target, so next is TODAY.
    target = recap.next_sunday(_now(2026, 8, 30, 8), hour=9, tz="UTC")

    assert target == _now(2026, 8, 30, 9)


def test_sunday_before_hour_waits_until_today_at_hour() -> None:
    target = recap.next_sunday(_now(2026, 8, 30, 10), hour=9, tz="UTC")

    assert target == _now(2026, 9, 6, 9)


def test_a_weekday_moves_to_the_next_sunday() -> None:
    # 2026-08-28 is a Friday.
    target = recap.next_sunday(_now(2026, 8, 28, 12), hour=9, tz="UTC")

    assert target == _now(2026, 8, 30, 9)


def test_timezone_shifts_the_hour() -> None:
    # 09:00 GMT+7 is 02:00 UTC.
    target = recap.next_sunday(_now(2026, 8, 28, 12), hour=9, tz="Asia/Ho_Chi_Minh")

    assert target == datetime(2026, 8, 30, 2, tzinfo=timezone.utc)


def test_an_unknown_timezone_falls_back_to_utc() -> None:
    target = recap.next_sunday(_now(2026, 8, 28, 12), hour=9, tz="Not/AZone")

    # Same Sunday at 09:00 UTC - the fallback silently keeps the schedule going.
    assert target == _now(2026, 8, 30, 9)


# --- storage -------------------------------------------------------------------------------


def test_plays_are_recorded_and_read_back(tmp_path) -> None:
    store = PlayStore(tmp_path / "plays.db")
    store.record_play(
        guild_id=1,
        title="Song A",
        author="Artist",
        uri="https://song.a",
        duration_ms=200_000,
        requester_id=7,
        played_at=_now(2026, 8, 28, 10),
    )

    rows = store.weekly(guild_id=1, since=_now(2026, 8, 28, 0))

    assert len(rows) == 1
    assert rows[0][0] == "Song A" and rows[0][4] == 7


def test_weekly_respects_the_guild_and_the_since_window(tmp_path) -> None:
    store = PlayStore(tmp_path / "plays.db")
    for guild, title in ((1, "A"), (2, "B")):
        store.record_play(
            guild_id=guild, title=title, author=None, uri=None, duration_ms=1000,
            requester_id=7, played_at=_now(2026, 8, 28, 10),
        )
    store.record_play(
        guild_id=1, title="Old", author=None, uri=None, duration_ms=1000,
        requester_id=7, played_at=_now(2026, 8, 1, 0),
    )

    assert [row[0] for row in store.weekly(1, since=_now(2026, 8, 28, 0))] == ["A"]
    assert [row[0] for row in store.weekly(2, since=_now(2026, 8, 28, 0))] == ["B"]


def test_prune_removes_only_old_rows(tmp_path) -> None:
    store = PlayStore(tmp_path / "plays.db")
    store.record_play(
        guild_id=1, title="Old", author=None, uri=None, duration_ms=1000,
        requester_id=7, played_at=_now(2026, 1, 1, 0),
    )
    store.record_play(
        guild_id=1, title="New", author=None, uri=None, duration_ms=1000,
        requester_id=7, played_at=_now(2026, 8, 28, 0),
    )

    assert store.prune(retention_cutoff(_now(2026, 9, 1))) == 1
    assert [row[0] for row in store.weekly(1, since=_now(2026, 1, 1))] == ["New"]


# --- the embed -----------------------------------------------------------------------------


def _row(title: str, *, duration_ms: int = 200_000, requester: int = 7):
    return (title, "Artist", f"https://{title}.x", duration_ms, requester, _now(2026, 8, 28, 10).isoformat())


def test_a_busy_week_shows_top_tracks_and_totals() -> None:
    embed = embeds.recap_embed(
        [_row("A", requester=1), _row("A", requester=1), _row("B", requester=2)],
        since=_now(2026, 8, 21),
        now=_now(2026, 8, 28, 9),
    )

    assert embed.title == "🦇 Weekly recap"
    fields = {f.name: f.value for f in embed.fields}
    assert "1. **A** - 2 plays" in fields["🎵 Top tracks"]
    assert fields["📊 This week"] == "3 songs, 10:00 listening"
    assert fields["👥 Top listener"] == "<@1> (2 plays)"


def test_an_empty_week_posts_a_quiet_line() -> None:
    embed = embeds.recap_embed([], since=_now(2026, 8, 21), now=_now(2026, 8, 28, 9))

    assert embed.description == "Quiet week - no music played."
    assert embed.fields == []


def test_the_footer_dates_the_window() -> None:
    embed = embeds.recap_embed([], since=_now(2026, 8, 21), now=_now(2026, 8, 28, 9))

    assert embed.footer is not None and "21 Aug" in embed.footer.text and "28 Aug" in embed.footer.text


# --- config --------------------------------------------------------------------------------


def test_recap_is_off_without_a_channel() -> None:
    assert _recap({"DEFAULT_GUILDS": "123"}) is None


def test_recap_falls_back_to_the_startup_channel() -> None:
    cfg = _recap({"DEFAULT_GUILDS": "123", "STARTUP_CHANNEL_ID": "456"})

    assert cfg is not None
    assert cfg.channel_id == 456 and cfg.guild_id == 123


def test_recap_reads_hour_and_timezone() -> None:
    cfg = _recap(
        {"DEFAULT_GUILDS": "123", "RECAP_CHANNEL_ID": "456", "RECAP_HOUR": "7", "RECAP_TIMEZONE": "Asia/Ho_Chi_Minh"}
    )

    assert cfg is not None
    assert cfg.hour == 7 and cfg.timezone == "Asia/Ho_Chi_Minh"


def test_a_bad_recap_hour_is_rejected() -> None:
    with pytest.raises(ConfigError):
        _recap({"DEFAULT_GUILDS": "123", "RECAP_CHANNEL_ID": "456", "RECAP_HOUR": "25"})