"""Running Alfred's own commands from chat.

The model does not decide what is allowed. It proposes an action and the arguments it read
out of the message; everything below decides whether that action runs, and re-applies the same
checks the equivalent slash command applies. A tool call is treated exactly like a request from
the person who sent the message - never as an instruction from the model.

The checks are re-implemented here rather than imported from `alfred.hooks`, because a hook
takes a `lightbulb.Context` and a message listener has none. They must stay in step: the pairs
are asserted in `tests/test_actions.py`.
"""

from __future__ import annotations

import dataclasses
from typing import Final

import hikari
import lavalink
from loguru import logger

from alfred import errors
from alfred.chat.completions import ToolCall
from alfred.music import service
from alfred.music import sources
from alfred.music.player import AlfredPlayer
from alfred.ui import embeds
from alfred.ui.formatting import track_length

PLAY: Final = "play"
NOW_PLAYING: Final = "now_playing"
SHOW_QUEUE: Final = "show_queue"
SKIP: Final = "skip"

# The tools offered to the model. They live here, with the rest of the model contract, and
# `alfred.actions` implements them - the dependency runs one way, because `actions` reaches
# `embeds`, which reaches this module for `Reply`.
#
# The descriptions are prompt text as much as documentation: "only when the user has named
# something" is what stops the model inventing a query for "play some music", which it does
# without it - measured, not assumed.
TOOLS: Final = [
    {
        "type": "function",
        "function": {
            "name": PLAY,
            "description": (
                "Queue a track, playlist or URL and start playing it. Only call this when the "
                "user has actually named a track, artist or link. If they asked for music "
                "without naming anything, do not call this - ask them what they want to hear."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The URL or search term the user named. Never invent one.",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": NOW_PLAYING,
            "description": "Show what is playing right now.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": SHOW_QUEUE,
            "description": "Show the queue - what is playing and what comes next.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": SKIP,
            "description": "Skip the track that is playing and move to the next one.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

TOOL_NAMES: Final = frozenset({PLAY, NOW_PLAYING, SHOW_QUEUE, SKIP})

# The API wants a tool call and its result tied together by id. Only one call is ever in
# flight, and the pair is built and sent in a single request, so a constant does the job.
TOOL_CALL_ID: Final = "alfred-action"

QUEUE_TITLE: Final = "Queue"
QUEUE_PREVIEW_LENGTH: Final = 10


@dataclasses.dataclass(frozen=True, slots=True)
class Result:
    """
    What an action produced.

    Two shapes, because the actions divide in two. One kind *does* something - queueing,
    skipping - and what matters is that it happened, so it carries a `summary` for the model
    to confirm in a sentence. The slash commands post a "Track added" card for these, but in
    chat that card is noise: the now playing view appears on its own when the track starts,
    so the same information would arrive twice.

    The other kind *shows* something, where the embed is the entire answer and there is nothing
    to add in words.
    """

    embed: hikari.Embed | None = None
    summary: str | None = None


@dataclasses.dataclass(frozen=True, slots=True)
class Invocation:
    """Who asked for an action, and where. Assembled from the message, never from the model."""

    bot: hikari.GatewayBot
    lavalink_client: lavalink.Client
    guild_id: int
    channel_id: int
    user_id: hikari.Snowflake


async def run(call: ToolCall, context: Invocation) -> Result:
    """
    Run an action on behalf of the person who sent the message.

    Returns:
        Either an embed to post, or a summary of what happened for the model to confirm.

    Raises:
        AlfredError: If a check fails, or the action cannot be completed. The message is safe
            to show, and the listener posts it as-is.
    """
    if call.name not in TOOL_NAMES:
        # Only reachable if a model invents a tool that was never offered.
        logger.warning("Model asked for an unknown action {!r}", call.name)
        raise errors.AlfredError("I can't do that from chat.")

    logger.info(
        "Running {!r} from chat for user {} on guild {}{}",
        call.name,
        context.user_id,
        context.guild_id,
        f" - query {call.query!r}" if call.name == PLAY else "",
    )

    if call.name == PLAY:
        return await _play(call, context)
    if call.name == NOW_PLAYING:
        return _now_playing(context)
    if call.name == SHOW_QUEUE:
        return _show_queue(context)
    return await _skip(context)


async def _play(call: ToolCall, context: Invocation) -> Result:
    """`/play`, from chat. Checks match `Play`: guild_only, valid_user_voice."""
    query = call.query
    if not query:
        # The prompt tells the model to ask rather than invent a query, and it does. This is
        # the backstop for the call that still arrives empty - asking beats queueing something
        # nobody named.
        raise errors.AlfredError("What would you like me to play? Give me a track, artist or link.")

    _require_user_voice(context)

    result = await service.resolve(context.lavalink_client, query, sources.YOUTUBE)
    # `enqueue` reports what it queued rather than rendering it, so the same value the slash
    # command turns into a card becomes a sentence here. The confirmation names the track that
    # actually resolved rather than what was asked for - "play rick astley" queues something
    # with a real title, and saying it back is how the asker knows the search found the right
    # thing.
    queued = await service.enqueue(
        context.bot,
        context.lavalink_client,
        result,
        guild_id=context.guild_id,
        # The requester is the message author. Nothing the model returns can change who gets
        # credited for a track, or whose voice channel is joined.
        requester_id=context.user_id,
        channel_id=context.channel_id,
        query=query,
        play_next=False,
        loop=False,
        shuffle=True,
    )

    return Result(summary=_queued_summary(queued))


def _queued_summary(queued: service.Queued) -> str:
    """Describe what was added to the queue, for the model to confirm."""
    if queued.is_playlist:
        assert queued.playlist is not None
        return f'Queued the playlist "{queued.playlist.name}" - {queued.count} tracks.'

    track = queued.track
    length = track_length(track)
    author = f" by {track.author}" if track.author else ""
    return f'Queued "{track.title}"{author} ({length}).'


def _now_playing(context: Invocation) -> Result:
    """`/now`, from chat. Checks match `Now`: guild_only, player_playing - no voice check."""
    return Result(embed=embeds.now_playing(_require_playing(context)))


def _show_queue(context: Invocation) -> Result:
    """`/queue`, from chat. Checks match `Queue`: guild_only, player_playing - no voice check."""
    player = _require_playing(context)
    return Result(embed=embeds.queue(player, title=QUEUE_TITLE, preview_length=QUEUE_PREVIEW_LENGTH))


async def _skip(context: Invocation) -> Result:
    """`/skip`, from chat. Checks match `Skip`: guild_only, valid_user_voice, player_playing."""
    _require_user_voice(context)
    player = _require_playing(context)

    skipped = await player.skip()
    if skipped is None:
        return Result(summary="Skipped the current track.")

    # `skip` moves the queue on, so whatever is current now is what the skip landed on.
    following = player.current
    landed = f' Now playing "{following.title}".' if following is not None and following is not skipped else ""
    return Result(summary=f'Skipped "{skipped.title}".{landed}')


def _require_user_voice(context: Invocation) -> None:
    """
    Mirror of `hooks.valid_user_voice`.

    This is what keeps chat from being a way around the voice check: asking Alfred to skip is
    exactly as restricted as running `/skip`, so someone outside the channel cannot reach the
    player by typing at the bot instead.
    """
    me = context.bot.get_me()
    user_channel_id = service.voice_channel_of(context.bot, context.guild_id, context.user_id)
    bot_channel_id = service.voice_channel_of(context.bot, context.guild_id, me.id) if me is not None else None

    if user_channel_id is None:
        raise errors.NotInVoice
    if bot_channel_id is not None and user_channel_id != bot_channel_id:
        raise errors.NotSameVoice


def _require_playing(context: Invocation) -> AlfredPlayer:
    """Mirror of `hooks.player_playing`."""
    player = service.get_player(context.lavalink_client, context.guild_id)
    if player is None or not player.is_playing:
        raise errors.PlayerNotPlaying
    return player
