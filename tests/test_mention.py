"""What Alfred does with a message that mentions him."""

from __future__ import annotations

from typing import Any

import lavalink
import pytest

from alfred.extensions.mention import on_mention
from alfred.player import AlfredPlayer
from tests.conftest import make_track
from tests.test_service import GUILD_ID
from tests.test_service import REQUESTER_ID
from tests.test_service import FakeLavalinkClient

BOT_ID = 42


class FakeMessage:
    def __init__(self, mentions: list[int]) -> None:
        self.user_mentions_ids = mentions
        self.replies: list[Any] = []

    async def respond(self, content: Any = None, *, embed: Any = None, **_: Any) -> None:
        self.replies.append(content if content is not None else embed)


class FakeEvent:
    """Enough of `hikari.GuildMessageCreateEvent` for the listener."""

    def __init__(self, content: str, *, mentions: list[int] | None = None, human: bool = True) -> None:
        self.content = content
        self.is_human = human
        self.guild_id = GUILD_ID
        self.author_id = REQUESTER_ID
        self.author = type("Author", (), {"username": "nauqh"})()
        self.message = FakeMessage(mentions if mentions is not None else [BOT_ID])


class FakeCache:
    def __init__(self, *, in_voice: bool) -> None:
        self._in_voice = in_voice

    def get_voice_state(self, guild_id: int, user_id: int) -> Any:
        return type("State", (), {"channel_id": 99})() if self._in_voice else None


class FakeBot:
    def __init__(self, *, in_voice: bool = True) -> None:
        self.cache = FakeCache(in_voice=in_voice)

    def get_me(self) -> Any:
        return type("Me", (), {"id": BOT_ID})()


async def mention(event: FakeEvent, client: FakeLavalinkClient, *, bot: FakeBot | None = None) -> None:
    await on_mention(event, bot or FakeBot(), client)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_a_mention_is_spoken(player: AlfredPlayer) -> None:
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_track(make_track()))

    await mention(FakeEvent(f"<@{BOT_ID}> good evening"), client)

    assert client.queries == ["ftts://good%20evening"]


@pytest.mark.asyncio
async def test_a_mention_asking_to_play_queues_instead_of_speaking(player: AlfredPlayer) -> None:
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_search([make_track()]))

    await mention(FakeEvent(f"<@{BOT_ID}> play tim em"), client)

    assert client.queries == ["ytsearch:tim em"]


@pytest.mark.asyncio
async def test_asking_to_skip_skips(player: AlfredPlayer) -> None:
    player.add(track=make_track("A Song"), requester=REQUESTER_ID)
    await player.play()
    player.current = player._next
    client = FakeLavalinkClient(player=player)

    event = FakeEvent(f"<@{BOT_ID}> skip")
    await mention(event, client)

    assert event.message.replies == ["Skipped **A Song**"]


@pytest.mark.asyncio
async def test_a_message_that_does_not_mention_the_bot_is_ignored(player: AlfredPlayer) -> None:
    client = FakeLavalinkClient(player=player)

    await mention(FakeEvent("good evening everyone", mentions=[]), client)

    assert client.queries == []


@pytest.mark.asyncio
async def test_another_bot_is_ignored(player: AlfredPlayer) -> None:
    # Otherwise two bots mentioning each other is a loop, spoken aloud.
    client = FakeLavalinkClient(player=player)

    await mention(FakeEvent(f"<@{BOT_ID}> good evening", human=False), client)

    assert client.queries == []


@pytest.mark.asyncio
async def test_a_mention_from_outside_voice_is_ignored(player: AlfredPlayer) -> None:
    # A mention is not a command invocation, and answering every stray one is noise in a
    # channel people are chatting in.
    client = FakeLavalinkClient(player=player)
    event = FakeEvent(f"<@{BOT_ID}> good evening")

    await mention(event, client, bot=FakeBot(in_voice=False))

    assert client.queries == []
    assert event.message.replies == []


@pytest.mark.asyncio
async def test_a_bare_mention_says_nothing(player: AlfredPlayer) -> None:
    client = FakeLavalinkClient(player=player)

    await mention(FakeEvent(f"<@{BOT_ID}>"), client)

    assert client.queries == []


@pytest.mark.asyncio
async def test_a_refusal_is_explained_in_the_channel(player: AlfredPlayer) -> None:
    # Speaking over a track is refused, and a mention has no ephemeral reply to hide it in.
    player.add(track=make_track("A Song"), requester=REQUESTER_ID)
    await player.play()
    player.current = player._next
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_track(make_track()))

    event = FakeEvent(f"<@{BOT_ID}> good evening")
    await mention(event, client)

    assert event.message.replies == ["I can only speak when nothing is playing - pause or stop the track first."]
