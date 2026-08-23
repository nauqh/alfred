from __future__ import annotations

from typing import Any

import hikari
import lavalink
import pytest

from alfred import errors
from alfred.chat import actions
from alfred.chat.completions import ToolCall
from alfred.music import service
from alfred.music.player import AlfredPlayer
from alfred.music.player import PlaylistRef
from tests.conftest import make_track

GUILD = 1
CHANNEL = 50
VOICE = 99
OTHER_VOICE = 100
USER = 7
BOT_USER = 8


class FakeVoiceState:
    def __init__(self, channel_id: int | None) -> None:
        self.channel_id = channel_id


class FakeCache:
    def __init__(self, states: dict[int, int | None]) -> None:
        self._states = states

    def get_voice_state(self, guild_id: int, user_id: int) -> FakeVoiceState | None:
        if user_id not in self._states:
            return None
        return FakeVoiceState(self._states[user_id])


class FakeMe:
    id = BOT_USER


class FakeBot:
    def __init__(self, states: dict[int, int | None]) -> None:
        self.cache = FakeCache(states)

    def get_me(self) -> FakeMe:
        return FakeMe()


class FakePlayerManager:
    def __init__(self, player: AlfredPlayer | None) -> None:
        self._player = player

    def get(self, guild_id: int) -> AlfredPlayer | None:
        return self._player


class FakeLavalink:
    def __init__(self, player: AlfredPlayer | None = None) -> None:
        self.player_manager = FakePlayerManager(player)


class FakeLoadResult:
    """Stands in for `lavalink.LoadResult` - only the parts `_queued_summary` reads."""

    def __init__(self, tracks: list[Any], load_type: Any = lavalink.LoadType.TRACK) -> None:
        self.tracks = tracks
        self.load_type = load_type
        self.playlist_info = None


def invocation(
    *,
    user_voice: int | None = VOICE,
    bot_voice: int | None = VOICE,
    player: AlfredPlayer | None = None,
) -> actions.Invocation:
    """An `Invocation` with the voice topology and player under test."""
    states: dict[int, int | None] = {USER: user_voice, BOT_USER: bot_voice}
    return actions.Invocation(
        bot=FakeBot(states),  # type: ignore[arg-type]
        lavalink_client=FakeLavalink(player),  # type: ignore[arg-type]
        guild_id=GUILD,
        channel_id=CHANNEL,
        user_id=USER,  # type: ignore[arg-type]
    )


def call(name: str, **arguments: Any) -> ToolCall:
    return ToolCall(name=name, arguments=arguments)


# --- the model proposes, the checks decide ------------------------------------------------


async def test_an_unknown_action_is_refused() -> None:
    """A model inventing a tool that was never offered gets nothing."""
    with pytest.raises(errors.AlfredError):
        await actions.run(call("delete_everything"), invocation())


async def test_play_without_a_query_asks_instead_of_guessing() -> None:
    """The backstop for `play` arriving empty - asking beats queueing something nobody named."""
    with pytest.raises(errors.AlfredError, match="What would you like me to play"):
        await actions.run(call(actions.PLAY, query="   "), invocation())


async def test_play_from_outside_a_voice_channel_is_refused() -> None:
    with pytest.raises(errors.NotInVoice):
        await actions.run(call(actions.PLAY, query="a song"), invocation(user_voice=None))


async def test_play_from_a_different_voice_channel_is_refused() -> None:
    """Mirrors `hooks.valid_user_voice`: chat is not a way around the bot's channel."""
    with pytest.raises(errors.NotSameVoice):
        await actions.run(call(actions.PLAY, query="a song"), invocation(user_voice=OTHER_VOICE))


async def test_skip_from_outside_a_voice_channel_is_refused() -> None:
    with pytest.raises(errors.NotInVoice):
        await actions.run(call(actions.SKIP), invocation(user_voice=None))


async def test_skip_with_nothing_playing_is_refused() -> None:
    with pytest.raises(errors.PlayerNotPlaying):
        await actions.run(call(actions.SKIP), invocation(player=None))


@pytest.mark.parametrize("name", [actions.NOW_PLAYING, actions.SHOW_QUEUE])
async def test_reading_the_player_needs_something_playing(name: str) -> None:
    with pytest.raises(errors.PlayerNotPlaying):
        await actions.run(call(name), invocation(player=None))


@pytest.mark.parametrize("name", [actions.NOW_PLAYING, actions.SHOW_QUEUE])
async def test_reading_the_player_needs_no_voice_check(
    name: str,
    player: AlfredPlayer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`/now` and `/queue` are open to anyone, and the chat path matches that."""
    monkeypatch.setattr(type(player), "is_playing", property(lambda _: True))

    # Not in voice at all, which `play` and `skip` would refuse.
    result = await actions.run(call(name), invocation(user_voice=None, player=player))

    assert isinstance(result.embed, hikari.Embed)
    assert result.summary is None


async def test_skip_from_the_bots_channel_skips(player: AlfredPlayer, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(type(player), "is_playing", property(lambda _: True))
    skipped: list[bool] = []

    async def fake_skip() -> None:
        skipped.append(True)
        return None

    monkeypatch.setattr(player, "skip", fake_skip)

    result = await actions.run(call(actions.SKIP), invocation(player=player))

    assert skipped == [True]
    # A summary for the model to confirm, not the slash command's card.
    assert result.embed is None
    assert result.summary is not None and "Skipped" in result.summary


async def test_queueing_confirms_in_words_rather_than_a_card(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    The slash command's "Track added" embed is dropped on the chat path.

    The now playing view arrives on its own when the track starts, so posting the card here
    would say the same thing twice.
    """

    async def fake_resolve(client: Any, query: str, source: Any) -> FakeLoadResult:
        return FakeLoadResult([make_track("Never Gonna Give You Up")])

    async def fake_enqueue(bot: Any, client: Any, result: Any, **kwargs: Any) -> service.Queued:
        return service.Queued(requester_id=USER, tracks=(make_track("Never Gonna Give You Up"),))

    monkeypatch.setattr(actions.service, "resolve", fake_resolve)
    monkeypatch.setattr(actions.service, "enqueue", fake_enqueue)

    result = await actions.run(call(actions.PLAY, query="rick astley"), invocation())

    assert result.embed is None
    # Names the track that resolved, not the query - that is how the asker knows the search
    # found the right thing.
    assert result.summary is not None
    assert "Never Gonna Give You Up" in result.summary


async def test_a_queued_playlist_is_summarised_by_size(monkeypatch: pytest.MonkeyPatch) -> None:
    class Info:
        name = "Jazz Classics"

    async def fake_resolve(client: Any, query: str, source: Any) -> FakeLoadResult:
        loaded = FakeLoadResult([make_track(f"t{i}") for i in range(40)], lavalink.LoadType.PLAYLIST)
        loaded.playlist_info = Info()  # type: ignore[assignment]
        return loaded

    async def fake_enqueue(bot: Any, client: Any, result: Any, **kwargs: Any) -> service.Queued:
        return service.Queued(
            requester_id=USER,
            tracks=tuple(make_track(f"t{i}") for i in range(40)),
            playlist=PlaylistRef(name="Jazz Classics", url=None),
            result_type="playlist",
        )

    monkeypatch.setattr(actions.service, "resolve", fake_resolve)
    monkeypatch.setattr(actions.service, "enqueue", fake_enqueue)

    result = await actions.run(call(actions.PLAY, query="jazz"), invocation())

    assert result.summary is not None
    assert "Jazz Classics" in result.summary and "40" in result.summary


# --- the model is never the authority -----------------------------------------------------


async def test_the_requester_comes_from_the_message_not_the_model(monkeypatch: pytest.MonkeyPatch) -> None:
    """
    A tool call cannot change who a track is queued as.

    The model returns arguments read out of someone's message; if `requester_id` were taken
    from those, a crafted message could queue tracks as somebody else.
    """
    seen: dict[str, Any] = {}

    async def fake_resolve(client: Any, query: str, source: Any) -> FakeLoadResult:
        return FakeLoadResult([make_track("Resolved Track")])

    async def fake_enqueue(bot: Any, client: Any, result: Any, **kwargs: Any) -> service.Queued:
        seen.update(kwargs)
        return service.Queued(requester_id=kwargs["requester_id"], tracks=(make_track(),))

    monkeypatch.setattr(actions.service, "resolve", fake_resolve)
    monkeypatch.setattr(actions.service, "enqueue", fake_enqueue)

    await actions.run(
        call(actions.PLAY, query="a song", requester_id=999, guild_id=999, user_id=999),
        invocation(),
    )

    assert seen["requester_id"] == USER
    assert seen["guild_id"] == GUILD
    assert seen["channel_id"] == CHANNEL


# --- the tool contract --------------------------------------------------------------------


def test_every_offered_tool_is_implemented() -> None:
    """`TOOL_NAMES` is what `run` dispatches on, so the schemas and the set cannot drift."""
    offered = {tool["function"]["name"] for tool in actions.TOOLS}

    assert offered == set(actions.TOOL_NAMES)


def test_play_is_the_only_tool_taking_an_argument() -> None:
    """Anything else taking arguments would be a new path for the model to put words into."""
    with_arguments = {
        tool["function"]["name"] for tool in actions.TOOLS if tool["function"]["parameters"].get("properties")
    }

    assert with_arguments == {actions.PLAY}
