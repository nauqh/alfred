"""Rendering, tested apart from queueing.

These assertions used to live in `test_service`, against the embed `enqueue` returned. Now
that `enqueue` reports what it queued and this module renders it, the two are testable
separately - and the card can be checked without a player, a client or a load result.
"""

from __future__ import annotations

import pytest

from alfred.music.player import PlaylistRef
from alfred.music.service import Queued
from alfred.ui import embeds
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
