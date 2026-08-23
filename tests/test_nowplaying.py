"""The now playing view's lifecycle: posted per track, replaced per track, deleted with the queue."""

from __future__ import annotations

import types
from typing import Any

import pytest

from alfred.music.player import AlfredPlayer
from alfred.ui.nowplaying import NowPlayingManager
from tests.conftest import confirm_playback
from tests.conftest import make_track

TEXT_CHANNEL_ID = 42
GUILD_ID = 1


class FakeMessage:
    def __init__(self, message_id: int) -> None:
        self.id = message_id


class FakeRest:
    """Stands in for `hikari.api.rest.RESTClient`, recording the messages it was told about."""

    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.deleted: list[tuple[int, int]] = []
        self._next_id = 1000

    async def create_message(self, channel: int, **kwargs: Any) -> FakeMessage:
        self.created.append({"channel": channel, **kwargs})
        self._next_id += 1
        return FakeMessage(self._next_id)

    async def delete_message(self, channel: int, message: int) -> None:
        self.deleted.append((channel, message))


class FakeBot:
    def __init__(self) -> None:
        self.rest = FakeRest()


@pytest.fixture
def rest() -> FakeRest:
    return FakeRest()


@pytest.fixture
def manager(rest: FakeRest) -> NowPlayingManager:
    bot = types.SimpleNamespace(rest=rest)
    client = types.SimpleNamespace(_attached_menus=set())
    # The menu reads the player for its labels when built; there is none to find here.
    lavalink_client = types.SimpleNamespace(player_manager=types.SimpleNamespace(get=lambda guild_id: None))
    manager = NowPlayingManager(bot, client, lavalink_client)  # type: ignore[arg-type]
    manager._test_client = client  # so tests can inspect the menu registry
    return manager


@pytest.fixture
def playing_player(player: AlfredPlayer) -> AlfredPlayer:
    player.text_channel_id = TEXT_CHANNEL_ID
    player.add(track=make_track("Some Song"), requester=1)
    player._next = player.queue.pop(0)
    confirm_playback(player)
    return player


@pytest.mark.asyncio
async def test_a_track_posts_a_view_with_buttons(manager: NowPlayingManager, playing_player: AlfredPlayer) -> None:
    await manager.show(playing_player)

    assert len(manager._views) == 1
    created = manager._bot.rest.created[0]
    assert created["channel"] == TEXT_CHANNEL_ID
    assert created["embed"].title == "Now Playing"
    assert "Some Song" in created["embed"].description
    assert created["components"] is not None


@pytest.mark.asyncio
async def test_the_next_track_replaces_the_view(manager: NowPlayingManager, playing_player: AlfredPlayer) -> None:
    await manager.show(playing_player)
    first_message_id = manager._views[GUILD_ID].message_id

    playing_player.add(track=make_track("Next Song"), requester=1)
    playing_player._next = playing_player.queue.pop(0)
    confirm_playback(playing_player)
    await manager.show(playing_player)

    assert manager._bot.rest.deleted == [(TEXT_CHANNEL_ID, first_message_id)]
    assert len(manager._views) == 1
    assert manager._views[GUILD_ID].message_id != first_message_id
    assert "Next Song" in manager._bot.rest.created[1]["embed"].description


@pytest.mark.asyncio
async def test_hide_deletes_the_view_and_stops_its_buttons(
    manager: NowPlayingManager, playing_player: AlfredPlayer
) -> None:
    await manager.show(playing_player)
    message_id = manager._views[GUILD_ID].message_id

    await manager.hide(GUILD_ID)

    assert manager._bot.rest.deleted == [(TEXT_CHANNEL_ID, message_id)]
    assert manager._views == {}


@pytest.mark.asyncio
async def test_hiding_unregisters_the_buttons(manager: NowPlayingManager, playing_player: AlfredPlayer) -> None:
    """Every track posts a view, so a leaked menu registry entry per track would grow without bound."""
    await manager.show(playing_player)
    await manager.hide(GUILD_ID)

    # Let the cancelled button task run its `finally` - it has already been awaited inside
    # `hide`, so this is only checking the registry it cleaned up.
    assert manager._test_client._attached_menus == set()


@pytest.mark.asyncio
async def test_hide_without_a_view_is_a_noop(manager: NowPlayingManager) -> None:
    await manager.hide(GUILD_ID)

    assert manager._bot.rest.deleted == []


@pytest.mark.asyncio
async def test_nothing_is_posted_without_a_channel(manager: NowPlayingManager, player: AlfredPlayer) -> None:
    player.add(track=make_track("Some Song"), requester=1)
    player._next = player.queue.pop(0)
    confirm_playback(player)

    await manager.show(player)

    assert manager._bot.rest.created == []
