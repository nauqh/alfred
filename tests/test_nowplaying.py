"""The now playing view's lifecycle: posted per track, replaced per track, deleted with the queue."""

from __future__ import annotations

import types
from typing import Any

import hikari
import pytest

from alfred.music.player import AlfredPlayer
from alfred.ui.nowplaying import NowPlayingManager
from tests.conftest import confirm_playback
from tests.conftest import make_track
from tests.conftest import set_position

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
        self.edited: list[dict[str, Any]] = []
        self.edit_raises: Exception | None = None
        self._next_id = 1000

    async def create_message(self, channel: int, **kwargs: Any) -> FakeMessage:
        self.created.append({"channel": channel, **kwargs})
        self._next_id += 1
        return FakeMessage(self._next_id)

    async def delete_message(self, channel: int, message: int) -> None:
        self.deleted.append((channel, message))

    async def edit_message(self, channel: int, message: int, **kwargs: Any) -> None:
        if self.edit_raises is not None:
            raise self.edit_raises
        self.edited.append({"channel": channel, "message": message, **kwargs})


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


@pytest.mark.asyncio
async def test_a_refresh_redraws_the_bar_where_playback_has_reached(
    manager: NowPlayingManager, playing_player: AlfredPlayer
) -> None:
    await manager.show(playing_player)
    view = manager._views[GUILD_ID]
    set_position(playing_player, 100_000)

    assert await manager._redraw(playing_player, view.channel_id, view.message_id) is True

    edit = manager._bot.rest.edited[0]
    assert (edit["channel"], edit["message"]) == (TEXT_CHANNEL_ID, view.message_id)
    assert "1:40" in edit["embed"].description
    # The buttons are not re-sent: hikari leaves an unspecified component list alone, and
    # replacing them here would fight the menu for the labels.
    assert "components" not in edit


@pytest.mark.asyncio
async def test_a_paused_player_is_not_redrawn(manager: NowPlayingManager, playing_player: AlfredPlayer) -> None:
    """The bar does not move while paused, so an edit would spend rate limit on the same embed."""
    await manager.show(playing_player)
    view = manager._views[GUILD_ID]
    playing_player.paused = True

    assert await manager._redraw(playing_player, view.channel_id, view.message_id) is True
    assert manager._bot.rest.edited == []


@pytest.mark.asyncio
async def test_a_stream_is_not_redrawn(manager: NowPlayingManager, player: AlfredPlayer) -> None:
    player.text_channel_id = TEXT_CHANNEL_ID
    player.add(track=make_track("A Broadcast", seekable=False), requester=1)
    player._next = player.queue.pop(0)
    confirm_playback(player)
    await manager.show(player)
    view = manager._views[GUILD_ID]

    assert await manager._redraw(player, view.channel_id, view.message_id) is True
    assert manager._bot.rest.edited == []


@pytest.mark.asyncio
async def test_refreshing_stops_when_the_message_is_gone(
    manager: NowPlayingManager, playing_player: AlfredPlayer
) -> None:
    """Someone deleted the view by hand. Every later tick would raise the same error."""
    await manager.show(playing_player)
    view = manager._views[GUILD_ID]
    manager._bot.rest.edit_raises = hikari.NotFoundError(url="", headers={}, raw_body=b"")

    assert await manager._redraw(playing_player, view.channel_id, view.message_id) is False


@pytest.mark.asyncio
async def test_hiding_stops_the_refresh(manager: NowPlayingManager, playing_player: AlfredPlayer) -> None:
    await manager.show(playing_player)
    refresh = manager._views[GUILD_ID].refresh

    await manager.hide(GUILD_ID)

    assert refresh.cancelled()
