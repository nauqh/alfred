"""The retry event handler for failed tracks."""

from __future__ import annotations

import lavalink
import pytest

from alfred.events import LavalinkEventHandler
from alfred.events import MAX_RETRIES
from alfred.events import RETRY_KEY
from alfred.player import AlfredPlayer
from tests.conftest import make_track


async def _raise_exception(player: AlfredPlayer, track: lavalink.AudioTrack) -> None:
    event = lavalink.TrackExceptionEvent(
        player=player, track=track, message="boom", severity=lavalink.Severity.SUSPICIOUS,
        cause="boom", cause_stacktrace=""
    )
    await LavalinkEventHandler().on_track_exception(event)


@pytest.mark.asyncio
async def test_first_failure_puts_the_track_back_at_the_front(player: AlfredPlayer) -> None:
    current = make_track("current")
    upcoming = make_track("upcoming")
    player.current = current
    player.queue.append(upcoming)

    await _raise_exception(player, current)

    assert player.queue[0] is current
    assert current.extra[RETRY_KEY] == 1
    assert player.queue[1] is upcoming


@pytest.mark.asyncio
async def test_second_failure_lets_the_player_move_on(player: AlfredPlayer) -> None:
    current = make_track("current")
    upcoming = make_track("upcoming")
    current.extra[RETRY_KEY] = MAX_RETRIES
    player.current = current
    player.queue.append(upcoming)

    await _raise_exception(player, current)

    assert player.queue[0] is upcoming