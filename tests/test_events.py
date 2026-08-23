"""The Lavalink event handlers: the retry logic, and the now playing view's triggers."""

from __future__ import annotations

import lavalink
import pytest

from alfred.events import MAX_RETRIES
from alfred.events import RETRY_KEY
from alfred.events import LavalinkEventHandler
from alfred.player import AlfredPlayer
from tests.conftest import make_track


class FakeNowPlaying:
    """Records which views it was asked to show and hide."""

    def __init__(self) -> None:
        self.shown: list[AlfredPlayer] = []
        self.hidden: list[int] = []

    async def show(self, player: AlfredPlayer) -> None:
        self.shown.append(player)

    async def hide(self, guild_id: int) -> None:
        self.hidden.append(guild_id)


@pytest.fixture
def now_playing() -> FakeNowPlaying:
    return FakeNowPlaying()


@pytest.fixture
def handler(now_playing: FakeNowPlaying) -> LavalinkEventHandler:
    return LavalinkEventHandler(now_playing)  # type: ignore[arg-type]


async def _raise_exception(handler: LavalinkEventHandler, player: AlfredPlayer, track: lavalink.AudioTrack) -> None:
    event = lavalink.TrackExceptionEvent(
        player=player,
        track=track,
        message="boom",
        severity=lavalink.Severity.SUSPICIOUS,
        cause="boom",
        cause_stacktrace="",
    )
    await handler.on_track_exception(event)


@pytest.mark.asyncio
async def test_first_failure_puts_the_track_back_at_the_front(
    handler: LavalinkEventHandler, player: AlfredPlayer
) -> None:
    current = make_track("current")
    upcoming = make_track("upcoming")
    player.current = current
    player.queue.append(upcoming)

    await _raise_exception(handler, player, current)

    assert player.queue[0] is current
    assert current.extra[RETRY_KEY] == 1
    assert player.queue[1] is upcoming


@pytest.mark.asyncio
async def test_second_failure_lets_the_player_move_on(handler: LavalinkEventHandler, player: AlfredPlayer) -> None:
    current = make_track("current")
    upcoming = make_track("upcoming")
    current.extra[RETRY_KEY] = MAX_RETRIES
    player.current = current
    player.queue.append(upcoming)

    await _raise_exception(handler, player, current)

    assert player.queue[0] is upcoming


@pytest.mark.asyncio
async def test_a_track_starting_shows_its_view(
    handler: LavalinkEventHandler, now_playing: FakeNowPlaying, player: AlfredPlayer
) -> None:
    track = make_track("current")
    player.current = track

    await handler.on_track_start(lavalink.TrackStartEvent(player=player, track=track))

    assert now_playing.shown == [player]


@pytest.mark.asyncio
async def test_the_queue_ending_takes_the_view_down(
    handler: LavalinkEventHandler, now_playing: FakeNowPlaying, player: AlfredPlayer
) -> None:
    await handler.on_queue_end(lavalink.QueueEndEvent(player=player))

    assert now_playing.hidden == [player.guild_id]
