"""What `/say` sends the node, and when it refuses to."""

from __future__ import annotations

import lavalink
import pytest

from alfred import errors
from alfred import service
from alfred.events import LavalinkEventHandler
from alfred.player import AlfredPlayer
from tests.conftest import confirm_playback
from tests.conftest import make_track
from tests.test_service import GUILD_ID
from tests.test_service import REQUESTER_ID
from tests.test_service import FakeLavalinkClient


async def speak(client: FakeLavalinkClient, text: str) -> lavalink.AudioTrack:
    return await service.speak(
        None,  # type: ignore[arg-type] - only needed when the bot has to join voice
        client,  # type: ignore[arg-type]
        text,
        guild_id=GUILD_ID,
        requester_id=REQUESTER_ID,
    )


@pytest.mark.asyncio
async def test_speech_is_sent_to_the_node_as_a_flowery_identifier(player: AlfredPlayer) -> None:
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_track(make_track()))

    await speak(client, "Very good, sir.")

    assert client.queries == ["ftts://Very%20good%2C%20sir."]


@pytest.mark.asyncio
async def test_speech_plays_immediately_rather_than_joining_the_queue(player: AlfredPlayer) -> None:
    track = make_track("Very good, sir.")
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_track(track))

    await speak(client, "Very good, sir.")
    confirm_playback(player)

    assert player.current is track
    # A line spoken over a queue should leave the queue exactly as it found it.
    assert player.queue == []


@pytest.mark.asyncio
async def test_speaking_over_a_track_is_refused(player: AlfredPlayer) -> None:
    # One player per guild and no mixing, so this would cut the music off mid-bar.
    player.add(track=make_track("A Song"), requester=REQUESTER_ID)
    await player.play()
    confirm_playback(player)

    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_track(make_track()))

    with pytest.raises(errors.AlreadyPlaying):
        await speak(client, "Very good, sir.")

    assert client.queries == []


@pytest.mark.asyncio
async def test_speech_is_played_louder_than_music(player: AlfredPlayer) -> None:
    # Flowery's output is well below a normalised track, so speech at the usual volume is hard
    # to make out over a Discord call.
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_track(make_track()))

    await speak(client, "Very good, sir.")

    assert player.node.updates[-1]["volume"] == service.SPEECH_VOLUME
    assert player.volume_before_speech == 100


@pytest.mark.asyncio
async def test_the_volume_goes_back_when_the_line_ends(player: AlfredPlayer) -> None:
    # Otherwise the next song plays at speech volume.
    speech = make_track("Very good, sir.", source="flowery-tts")
    player.volume_before_speech = 100
    player.volume = service.SPEECH_VOLUME

    await LavalinkEventHandler().on_track_end(lavalink.TrackEndEvent(player, speech, "finished"))

    assert player.volume == 100
    assert player.volume_before_speech is None


@pytest.mark.asyncio
async def test_a_song_ending_leaves_the_volume_alone(player: AlfredPlayer) -> None:
    player.volume = 100

    await LavalinkEventHandler().on_track_end(lavalink.TrackEndEvent(player, make_track(), "finished"))

    assert player.volume == 100


@pytest.mark.asyncio
async def test_a_line_of_whitespace_never_reaches_the_node(player: AlfredPlayer) -> None:
    client = FakeLavalinkClient(player=player)

    with pytest.raises(errors.NoResults):
        await speak(client, "  \n  ")

    assert client.queries == []


@pytest.mark.asyncio
async def test_newlines_are_collapsed_rather_than_encoded(player: AlfredPlayer) -> None:
    # Text pasted out of a lyrics page is mostly newlines. Flowery reads them as nothing, so
    # they would only inflate the URL and the length check.
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_track(make_track()))

    await speak(client, "Good\n\n  evening,\tsir")

    assert client.queries == ["ftts://Good%20evening%2C%20sir"]


@pytest.mark.asyncio
async def test_an_essay_is_refused_before_it_becomes_a_url(player: AlfredPlayer) -> None:
    client = FakeLavalinkClient(player=player)

    with pytest.raises(errors.SpeechTooLong):
        await speak(client, "sir " * 100)

    assert client.queries == []


@pytest.mark.asyncio
async def test_a_node_that_cannot_render_the_line_is_reported(player: AlfredPlayer) -> None:
    # What an unreachable Flowery, or the source left disabled in application.yml, looks like.
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.empty())

    with pytest.raises(errors.NoResults):
        await speak(client, "Very good, sir.")
