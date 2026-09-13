"""Rendering, tested apart from queueing.

These assertions used to live in `test_service`, against the embed `enqueue` returned. Now
that `enqueue` reports what it queued and this module renders it, the two are testable
separately - and the card can be checked without a player, a client or a load result.
"""

from __future__ import annotations

import pytest

from alfred.changelog import Category
from alfred.changelog import Entry
from alfred.music.player import AlfredPlayer
from alfred.music.player import PlaylistRef
from alfred.music.service import Queued
from alfred.ui import embeds
from tests.conftest import confirm_playback
from tests.conftest import make_track

REQUESTER = 42


def test_a_single_track_renders_as_the_track_added_card() -> None:
    track = make_track("Some Song")

    embed = embeds.queued(Queued(requester_id=REQUESTER, tracks=(track,), artwork_url=track.artwork_url))

    assert embed.title == "Track added"
    assert embed.description is not None and "Some Song" in embed.description


def test_an_album_is_titled_and_credited() -> None:
    embed = embeds.queued(
        Queued(
            requester_id=REQUESTER,
            tracks=(make_track("a"),),
            playlist=PlaylistRef(name="An Album", url="https://open.spotify.com/album/1"),
            result_type="album",
            artwork_url="https://example.com/art.png",
            author="Some Artist",
        )
    )

    assert embed.title == "Album added"
    assert embed.description is not None and "Some Artist" in embed.description
    assert embed.thumbnail is not None


def test_an_artist_is_shouted() -> None:
    """The artist case upper-cases the name - a deliberate difference from an album."""
    embed = embeds.queued(
        Queued(
            requester_id=REQUESTER,
            tracks=(make_track("a"),),
            playlist=PlaylistRef(name="Top Tracks", url="https://open.spotify.com/artist/1"),
            result_type="artist",
            author="Some Artist",
        )
    )

    assert embed.title == "Artist added"
    assert embed.description is not None and "SOME ARTIST" in embed.description


def test_a_playlist_without_an_author_still_counts_its_tracks() -> None:
    embed = embeds.queued(
        Queued(
            requester_id=REQUESTER,
            tracks=tuple(make_track(f"t{i}") for i in range(12)),
            playlist=PlaylistRef(name="Road Trip", url=None),
            result_type="playlist",
        )
    )

    assert embed.description is not None
    assert "12 tracks" in embed.description
    # No URL on the playlist, so the link falls back rather than rendering an empty target.
    assert "(#)" in embed.description


@pytest.mark.parametrize("result_type", ["playlist", "album", "artist"])
def test_the_requester_is_always_mentioned(result_type: str) -> None:
    embed = embeds.queued(
        Queued(
            requester_id=REQUESTER,
            tracks=(make_track("a"),),
            playlist=PlaylistRef(name="Something", url=None),
            result_type=result_type,
            author="An Author",
        )
    )

    assert embed.description is not None and f"<@{REQUESTER}>" in embed.description


def playing(player: AlfredPlayer, queued: int) -> AlfredPlayer:
    """A player on its first track, with ``queued`` more waiting behind it."""
    player.add(track=make_track("Playing Now"), requester=REQUESTER)
    player._next = player.queue.pop(0)
    confirm_playback(player)
    for i in range(queued):
        player.add(track=make_track(f"Queued {i}"), requester=REQUESTER)
    return player


@pytest.mark.parametrize(
    ("tracks", "page_size", "expected"),
    [(0, 10, 1), (1, 10, 1), (10, 10, 1), (11, 10, 2), (25, 10, 3), (5, 0, 1)],
)
def test_the_page_count_never_drops_below_one(tracks: int, page_size: int, expected: int) -> None:
    assert embeds.queue_pages(tracks, page_size) == expected


def test_the_first_page_lists_the_first_tracks(player: AlfredPlayer) -> None:
    embed = embeds.queue(playing(player, 25), title="Queue", page_size=10)

    assert embed.description is not None
    assert "`1.` [Queued 0]" in embed.description
    assert "`10.` [Queued 9]" in embed.description
    assert "<@42>" in embed.description
    assert "YouTube" in embed.description
    assert "Queued 10" not in embed.description


def test_a_later_page_lists_the_tracks_that_page_covers(player: AlfredPlayer) -> None:
    """
    The number and the track have to move together.

    Asserting on the numbering alone passes even when every page renders the same ten tracks,
    which is exactly the bug a paging slice invites - so each is pinned to its title.
    """
    embed = embeds.queue(playing(player, 25), title="Queue", page_size=10, page=1)

    assert embed.description is not None
    assert "`11.` [Queued 10]" in embed.description
    assert "`20.` [Queued 19]" in embed.description
    assert "Queued 0]" not in embed.description


def test_the_footer_counts_pages_only_when_there_is_more_than_one(player: AlfredPlayer) -> None:
    many = embeds.queue(playing(player, 25), title="Queue", page_size=10, page=2)

    assert many.description is not None and "Page 3/3" in many.description


def test_a_single_page_queue_is_not_paginated(player: AlfredPlayer) -> None:
    embed = embeds.queue(playing(player, 4), title="Queue", page_size=10)

    assert embed.description is not None
    assert "Page" not in embed.description
    assert "Total: 5 tracks" in embed.description


def test_a_page_past_the_end_shows_the_last_one(player: AlfredPlayer) -> None:
    embed = embeds.queue(playing(player, 25), title="Queue", page_size=10, page=99)

    assert embed.description is not None and "Page 3/3" in embed.description


def test_a_queue_snapshot_identifies_itself_and_shows_elapsed_total(player: AlfredPlayer) -> None:
    embed = embeds.queue(playing(player, 1), title="Queue", page_size=10, snapshot=True)

    assert embed.description is not None
    assert "Snapshot" in embed.description
    assert "updated <t:" in embed.description
    assert "6:40" in embed.description


def test_the_queue_of_a_player_that_has_gone_says_nothing_is_playing() -> None:
    assert embeds.queue(None, title="Queue").description == (
        "Nothing is playing.\n\nTry `/play` or `/search` to start some music."
    )


def change_entry(categories: list[tuple[str, list[str]]], *, date: str | None = "2026-08-29") -> Entry:
    """An `Entry` with the given category name/items, for the embed builder tests."""
    return Entry(
        version="[2.0.0]",
        date=date,
        categories=tuple(Category(name=name, items=tuple(items)) for name, items in categories),
    )


def test_a_change_log_renders_one_embed_with_a_category_per_field() -> None:
    (embed,) = embeds.changelog_embeds(
        change_entry([("Added", ["Chat search", "Sidebar"])])
    )

    assert embed.title == "🦇 Changelog - 2026-08-29"
    assert [(f.name, f.value) for f in embed.fields] == [("Added", "- Chat search\n- Sidebar")]


def test_an_entry_without_a_date_has_a_plain_title() -> None:
    (embed,) = embeds.changelog_embeds(change_entry([("Added", ["WIP"])], date=None))

    assert embed.title == "🦇 Changelog"


def test_a_change_log_carries_a_footer_that_counts_the_items() -> None:
    (embed,) = embeds.changelog_embeds(
        change_entry([("Added", ["a", "b"]), ("Fixed", ["c"])])
    )

    assert embed.footer is not None and embed.footer.text == "Alfred · 3 updates"


def test_a_change_log_with_no_items_gets_no_update_count() -> None:
    (embed,) = embeds.changelog_embeds(change_entry([], date=None))

    assert embed.footer is not None and embed.footer.text == "Alfred"


def test_the_entry_date_becomes_the_embed_timestamp() -> None:
    (embed,) = embeds.changelog_embeds(change_entry([("Added", ["a"])]))

    assert embed.timestamp is not None and embed.timestamp.year == 2026 and embed.timestamp.month == 8


def test_an_entry_without_a_date_leaves_the_timestamp_unset() -> None:
    (embed,) = embeds.changelog_embeds(change_entry([("Added", ["a"])], date=None))

    assert embed.timestamp is None


def test_a_long_category_is_split_across_part_fields() -> None:
    items = ["x" * (embeds.MAX_FIELD_VALUE + 200)]
    (embed,) = embeds.changelog_embeds(change_entry([("Added", items)]))

    assert len(embed.fields) == 2
    assert embed.fields[0].name == "Added"
    assert embed.fields[1].name == "Added (2)"
    # Nothing is lost across the split.
    assert "".join(f.value for f in embed.fields).count("x") == len(items[0])


def test_many_categories_split_across_several_embeds() -> None:
    categories = [(f"Category {i}", [f"body {i}"]) for i in range(40)]

    embeds_ = embeds.changelog_embeds(change_entry(categories))

    assert len(embeds_) == 2
    assert all(len(e.fields) <= embeds.MAX_FIELDS for e in embeds_)
    assert all(e.title == "🦇 Changelog - 2026-08-29" for e in embeds_)
    assert len(embeds_[0].fields) + len(embeds_[1].fields) == 40


def test_an_empty_entry_still_gets_one_embed() -> None:
    (embed,) = embeds.changelog_embeds(change_entry([], date=None))

    assert embed.title == "🦇 Changelog"
    assert embed.fields == []
