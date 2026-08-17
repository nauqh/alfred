"""What Alfred does with a message that mentions him."""

from __future__ import annotations

from typing import Any

import hikari
import lavalink
import pytest

from alfred.extensions import mention as mention_module
from alfred.extensions.mention import on_mention
from alfred.player import AlfredPlayer
from tests.conftest import make_track
from tests.test_service import GUILD_ID
from tests.test_service import REQUESTER_ID
from tests.test_service import FakeLavalinkClient

BOT_ID = 42

# The role Discord creates for the bot when it joins, which its mention picker starts
# offering in place of the bot itself.
BOT_ROLE_ID = 7
OTHER_ROLE_ID = 8


class FakeMessage:
    def __init__(self, mentions: list[int], role_mentions: list[int]) -> None:
        self.user_mentions_ids = mentions
        self.role_mention_ids = role_mentions
        self.replies: list[Any] = []

    async def respond(self, content: Any = None, *, embed: Any = None, **_: Any) -> None:
        self.replies.append(content if content is not None else embed)


class FakeEvent:
    """Enough of `hikari.GuildMessageCreateEvent` for the listener."""

    def __init__(
        self,
        content: str | None,
        *,
        mentions: list[int] | None = None,
        role_mentions: list[int] | None = None,
        human: bool = True,
    ) -> None:
        self.content = content
        self.is_human = human
        self.guild_id = GUILD_ID
        self.author_id = REQUESTER_ID
        self.author = type("Author", (), {"username": "nauqh"})()
        self.message = FakeMessage(
            mentions if mentions is not None else [BOT_ID],
            role_mentions or [],
        )


class FakeCache:
    def __init__(self, *, in_voice: bool, my_roles: list[int] | None) -> None:
        self._in_voice = in_voice
        self._my_roles = my_roles

    def get_voice_state(self, guild_id: int, user_id: int) -> Any:
        return type("State", (), {"channel_id": 99})() if self._in_voice else None

    def get_member(self, guild_id: int, user_id: int) -> Any:
        # `None` is what an uncached member looks like, which is a case the listener has to
        # survive - it has no members intent.
        if self._my_roles is None:
            return None
        return type("Member", (), {"role_ids": self._my_roles})()


class FakeRest:
    """The API behind the member cache, for when the cache cannot answer."""

    def __init__(self, my_roles: list[int] | None) -> None:
        self._my_roles = my_roles
        self.calls = 0

    async def fetch_my_member(self, guild_id: int) -> Any:
        self.calls += 1
        if self._my_roles is None:
            raise hikari.NotFoundError("/guilds/x/members/@me", {}, b"", "unknown member")
        return type("Member", (), {"role_ids": self._my_roles})()


# `my_roles=None` has to mean "the bot's member is not cached", so the default needs to be
# something else again.
UNSET: Any = object()


class FakeBot:
    def __init__(
        self,
        *,
        in_voice: bool = True,
        my_roles: list[int] | None = UNSET,
        rest_roles: list[int] | None = UNSET,
    ) -> None:
        self.cache = FakeCache(
            in_voice=in_voice,
            my_roles=[BOT_ROLE_ID] if my_roles is UNSET else my_roles,
        )
        self.rest = FakeRest([BOT_ROLE_ID] if rest_roles is UNSET else rest_roles)

    def get_me(self) -> Any:
        return type("Me", (), {"id": BOT_ID})()


@pytest.fixture(autouse=True)
def _forget_fetched_roles() -> Any:
    """The listener remembers roles it had to fetch, and that must not leak between tests."""
    mention_module._role_ids.clear()
    yield
    mention_module._role_ids.clear()


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
async def test_tagging_the_bots_role_works_like_tagging_the_bot(player: AlfredPlayer) -> None:
    # Discord's picker offers the bot's managed role once the bot has been tagged once, so
    # this is what the *second* tag usually looks like - and it used to be ignored outright.
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_track(make_track()))

    event = FakeEvent(f"<@&{BOT_ROLE_ID}> good evening", mentions=[], role_mentions=[BOT_ROLE_ID])
    await mention(event, client)

    # The role mention is stripped along with the text, rather than read out as `<@&7>`.
    assert client.queries == ["ftts://good%20evening"]


@pytest.mark.asyncio
async def test_a_role_the_bot_does_not_have_is_ignored(player: AlfredPlayer) -> None:
    client = FakeLavalinkClient(player=player)

    event = FakeEvent(f"<@&{OTHER_ROLE_ID}> good evening", mentions=[], role_mentions=[OTHER_ROLE_ID])
    await mention(event, client)

    assert client.queries == []
    assert event.message.replies == []


@pytest.mark.asyncio
async def test_an_uncached_member_is_fetched_rather_than_giving_up(player: AlfredPlayer) -> None:
    # The bot runs without the members intent. If the member cache turns out not to hold even
    # the bot's own member, falling back to the API is what keeps role mentions working
    # instead of silently ignoring them all over again.
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_track(make_track()))
    bot = FakeBot(my_roles=None)

    event = FakeEvent(f"<@&{BOT_ROLE_ID}> good evening", mentions=[], role_mentions=[BOT_ROLE_ID])
    await mention(event, client, bot=bot)

    assert client.queries == ["ftts://good%20evening"]
    assert bot.rest.calls == 1


@pytest.mark.asyncio
async def test_fetched_roles_are_remembered(player: AlfredPlayer) -> None:
    # Otherwise every role mention in a guild whose member cache is empty is a REST call.
    client = FakeLavalinkClient(player=player, result=lavalink.LoadResult.from_track(make_track()))
    bot = FakeBot(my_roles=None)

    for _ in range(3):
        event = FakeEvent(f"<@&{BOT_ROLE_ID}> good evening", mentions=[], role_mentions=[BOT_ROLE_ID])
        await mention(event, client, bot=bot)

    assert bot.rest.calls == 1


@pytest.mark.asyncio
async def test_a_role_mention_is_ignored_when_the_roles_cannot_be_established(player: AlfredPlayer) -> None:
    # Cache empty and the API refusing too. Guessing would mean answering every role ping in
    # the server, so the mention goes unanswered - a direct mention still works.
    client = FakeLavalinkClient(player=player)

    event = FakeEvent(f"<@&{BOT_ROLE_ID}> good evening", mentions=[], role_mentions=[BOT_ROLE_ID])
    await mention(event, client, bot=FakeBot(my_roles=None, rest_roles=None))

    assert client.queries == []
    assert event.message.replies == []


@pytest.mark.asyncio
async def test_a_tag_with_the_text_withheld_explains_how_to_get_through(player: AlfredPlayer) -> None:
    # Discord blanks `content` for apps without MESSAGE_CONTENT and exempts messages that
    # mention the app - but has never said whether a mention of a role the app holds counts.
    # Going quiet here is indistinguishable from the bot ignoring you, which is the bug.
    client = FakeLavalinkClient(player=player)

    event = FakeEvent("", mentions=[], role_mentions=[BOT_ROLE_ID])
    await mention(event, client)

    assert client.queries == []
    assert event.message.replies == [
        "I can see you tagged me, but not what you said - pick me from the list rather than my role, "
        "and Discord will pass the message along."
    ]


@pytest.mark.asyncio
async def test_a_bare_role_tag_with_readable_content_says_nothing(player: AlfredPlayer) -> None:
    # The mention itself survives in `content`, so this is someone tagging the role and
    # writing nothing - not Discord withholding anything. No hint is owed.
    client = FakeLavalinkClient(player=player)

    event = FakeEvent(f"<@&{BOT_ROLE_ID}>", mentions=[], role_mentions=[BOT_ROLE_ID])
    await mention(event, client)

    assert client.queries == []
    assert event.message.replies == []


@pytest.mark.asyncio
async def test_everyone_is_not_a_mention(player: AlfredPlayer) -> None:
    # `@everyone` tags the bot by any reasonable reading. Acting on it would mean speaking
    # over every announcement in the server.
    client = FakeLavalinkClient(player=player)

    event = FakeEvent("@everyone good evening", mentions=[], role_mentions=[])
    await mention(event, client)

    assert client.queries == []
    assert event.message.replies == []


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
