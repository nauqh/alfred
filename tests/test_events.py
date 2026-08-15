"""The now-playing message lifecycle."""

from __future__ import annotations

import asyncio
import base64
import dataclasses
from typing import Any

import hikari
import lightbulb
import pytest

from alfred.events import LavalinkEventHandler
from alfred.player import AlfredPlayer
from tests.conftest import make_track

# `hikari.GatewayBot` decodes the bot's user ID out of the token's first segment, so the token
# has to have a token's shape. Assembled at runtime to keep secret scanners off its back.
FAKE_TOKEN = ".".join([base64.b64encode(b"123456789012345678").decode(), "a" * 6, "b" * 27])
CHANNEL_ID = 42


@dataclasses.dataclass
class FakeMessage:
    id: int


class FakeRest:
    def __init__(self) -> None:
        self.created: list[dict[str, Any]] = []
        self.deleted: list[tuple[int, int]] = []
        self.fail_create: Exception | None = None

    async def create_message(self, channel: int, **kwargs: Any) -> FakeMessage:
        if self.fail_create is not None:
            raise self.fail_create
        self.created.append({"channel": channel, **kwargs})
        return FakeMessage(id=1000 + len(self.created))

    async def delete_message(self, channel_id: int, message_id: int) -> None:
        self.deleted.append((channel_id, message_id))


@pytest.fixture
def bot() -> Any:
    bot = hikari.GatewayBot(FAKE_TOKEN, banner=None, logs=None, suppress_optimization_warning=True)
    bot._rest = FakeRest()  # type: ignore[assignment]
    return bot


def make_menu_handle() -> lightbulb.components.MenuHandle:
    """
    A real `MenuHandle`, without the interaction listener behind it.

    Deliberately not a stand-in with its own methods: a hand-written double let
    `handle.stop()` - a method `MenuHandle` does not have - through code review and the whole
    test suite, and it only surfaced when the bot ran.
    """
    return lightbulb.components.MenuHandle(task=None, stop_event=asyncio.Event())


class FakePlayerManager:
    def __init__(self, player: AlfredPlayer) -> None:
        self._player = player

    def get(self, guild_id: int) -> AlfredPlayer | None:
        return self._player if guild_id == self._player.guild_id else None


class FakeLavalinkClient:
    """Enough of `lavalink.Client` for the menu to find the guild's player."""

    def __init__(self, player: AlfredPlayer) -> None:
        self.player_manager = FakePlayerManager(player)


@pytest.fixture
def handler(bot: Any, player: AlfredPlayer, monkeypatch: pytest.MonkeyPatch) -> LavalinkEventHandler:
    # The menu needs a running client to attach to, which these tests have no use for - what
    # matters here is that a handle is kept and later stopped.
    monkeypatch.setattr(
        "alfred.events.PlayerMenu.attach_persistent",
        lambda self, client, timeout=None: make_menu_handle(),
    )
    return LavalinkEventHandler(bot, client=object(), lavalink_client=FakeLavalinkClient(player))  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_posting_the_player_message(
    handler: LavalinkEventHandler,
    bot: Any,
    player: AlfredPlayer,
) -> None:
    player.current = make_track("Some Song")
    player.announce_channel_id = CHANNEL_ID

    await handler.post_now_playing(player)

    assert len(bot.rest.created) == 1
    assert bot.rest.created[0]["channel"] == CHANNEL_ID
    assert player.now_playing is not None
    assert player.now_playing.channel_id == CHANNEL_ID


@pytest.mark.asyncio
async def test_nothing_is_posted_without_a_channel_to_post_in(
    handler: LavalinkEventHandler, bot: Any, player: AlfredPlayer
) -> None:
    player.current = make_track()

    await handler.post_now_playing(player)

    assert bot.rest.created == []
    assert player.now_playing is None


@pytest.mark.asyncio
async def test_a_new_track_replaces_the_previous_message(
    handler: LavalinkEventHandler,
    bot: Any,
    player: AlfredPlayer,
) -> None:
    player.current = make_track("first")
    player.announce_channel_id = CHANNEL_ID
    await handler.post_now_playing(player)
    first_message_id = player.now_playing.message_id  # type: ignore[union-attr]

    player.current = make_track("second")
    await handler.post_now_playing(player)

    assert bot.rest.deleted == [(CHANNEL_ID, first_message_id)]
    assert len(bot.rest.created) == 2


@pytest.mark.asyncio
async def test_clearing_deletes_the_message(
    handler: LavalinkEventHandler,
    bot: Any,
    player: AlfredPlayer,
) -> None:
    player.current = make_track()
    player.announce_channel_id = CHANNEL_ID
    await handler.post_now_playing(player)

    await handler.clear_now_playing(player)

    assert player.now_playing is None
    assert len(bot.rest.deleted) == 1


@pytest.mark.asyncio
async def test_clearing_twice_deletes_the_message_once(
    handler: LavalinkEventHandler, bot: Any, player: AlfredPlayer
) -> None:
    player.current = make_track()
    player.announce_channel_id = CHANNEL_ID
    await handler.post_now_playing(player)

    await handler.clear_now_playing(player)
    await handler.clear_now_playing(player)

    assert len(bot.rest.deleted) == 1


@pytest.mark.asyncio
async def test_a_message_that_cannot_be_posted_is_not_recorded(
    handler: LavalinkEventHandler,
    bot: Any,
    player: AlfredPlayer,
) -> None:
    player.current = make_track()
    player.announce_channel_id = CHANNEL_ID
    bot.rest.fail_create = hikari.ForbiddenError(url="", headers={}, raw_body=b"")  # type: ignore[arg-type]

    await handler.post_now_playing(player)

    assert player.now_playing is None
