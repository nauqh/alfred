from __future__ import annotations

import lavalink
import pytest

from alfred.music.player import AlfredPlayer
from tests.conftest import FakeClient
from tests.conftest import make_track


@pytest.mark.asyncio
async def test_stop_resets_everything_and_announces_the_end(player: AlfredPlayer, client: FakeClient) -> None:
    player.current = make_track("current")
    player.queue.append(make_track("upcoming"))
    player.set_loop(AlfredPlayer.LOOP_QUEUE)
    player.set_shuffle(True)

    await player.stop()

    assert player.current is None
    assert player.queue == []
    assert player.loop == AlfredPlayer.LOOP_NONE
    assert player.shuffle is False
    assert any(isinstance(event, lavalink.QueueEndEvent) for event in client.events)


@pytest.mark.asyncio
async def test_stop_resets_state_even_when_the_node_is_unreachable(player: AlfredPlayer) -> None:
    async def explode(*_: object, **__: object) -> None:
        raise lavalink.ClientError("node is gone")

    player.node.update_player = explode  # type: ignore[method-assign]
    player.current = make_track("current")
    player.queue.append(make_track("upcoming"))

    await player.stop()

    assert player.current is None
    assert player.queue == []
