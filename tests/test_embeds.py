"""Rendering, tested apart from queueing.

These assertions used to live in `test_service`, against the embed `enqueue` returned. Now
that `enqueue` reports what it queued and this module renders it, the two are testable
separately - and the card can be checked without a player, a client or a load result.
"""

from __future__ import annotations

import pytest

from alfred.dev_log import DevLog
from alfred.dev_log import LogSection
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


def test_the_queue_of_a_player_that_has_gone_says_nothing_is_playing() -> None:
    assert embeds.queue(None, title="Queue").description == "Nothing is playing."


def dev_log(*sections: tuple[str, str]) -> DevLog:
    """A `DevLog` with the given heading/body sections, for the embed builder tests."""
    return DevLog(title="2026-08-29", sections=tuple(LogSection(heading=h, body=b) for h, b in sections))


def test_a_dev_log_renders_one_embed_with_a_field_per_section() -> None:
    (embed,) = embeds.dev_log_embeds(
        dev_log(("Ask Alfred to search", "The top 5 matches, numbered."), ("Sidebar", "The song and artist."))
    )

    assert embed.title == "Alfred dev log - 2026-08-29"
    assert [(f.name, f.value) for f in embed.fields] == [
        ("Ask Alfred to search", "The top 5 matches, numbered."),
        ("Sidebar", "The song and artist."),
    ]


def test_a_dev_log_carries_an_intro_as_the_description() -> None:
    (embed,) = embeds.dev_log_embeds(DevLog(title="2026-08-29", description="A short intro."))

    assert embed.title == "Alfred dev log - 2026-08-29"
    assert embed.description == "A short intro."
    assert embed.fields == []


def test_a_long_section_is_split_across_part_fields() -> None:
    body = "x" * (embeds.MAX_FIELD_VALUE + 200)
    (embed,) = embeds.dev_log_embeds(dev_log(("Long section", body)))

    assert len(embed.fields) == 2
    assert embed.fields[0].name == "Long section"
    assert embed.fields[1].name == "Long section (2)"
    # Nothing is lost across the split.
    assert "".join(f.value for f in embed.fields).count("x") == len(body)


def test_many_sections_split_across_several_embeds() -> None:
    sections = [(f"Section {i}", f"body {i}") for i in range(40)]

    embeds_ = embeds.dev_log_embeds(dev_log(*sections))

    assert len(embeds_) == 2
    assert all(len(e.fields) <= embeds.MAX_FIELDS for e in embeds_)
    assert all(e.title == "Alfred dev log - 2026-08-29" for e in embeds_)
    assert len(embeds_[0].fields) + len(embeds_[1].fields) == 40


def test_an_empty_dev_log_still_gets_one_embed() -> None:
    (embed,) = embeds.dev_log_embeds(DevLog(title="2026-08-29"))

    assert embed.title == "Alfred dev log - 2026-08-29"
    assert embed.fields == []
