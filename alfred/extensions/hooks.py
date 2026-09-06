"""Command checks, as lightbulb execution hooks.

Each hook raises a `alfred.errors.AlfredError`; the client's error handler turns that into
an ephemeral reply.
"""

from __future__ import annotations

import hikari
import lavalink
import lightbulb

from alfred import errors
from alfred import owner
from alfred.music import service


@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS)
def guild_only(_: lightbulb.ExecutionPipeline, ctx: lightbulb.Context) -> None:
    """Reject the command unless it was invoked in a guild."""
    if ctx.guild_id is None:
        raise errors.GuildOnly


@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS)
def valid_user_voice(
    _: lightbulb.ExecutionPipeline,
    ctx: lightbulb.Context,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
) -> None:
    """Require the caller to be in a voice channel, and in the bot's channel if the bot is in one."""
    if ctx.guild_id is None:
        raise errors.GuildOnly

    me = bot.get_me()
    user_channel_id = service.voice_channel_of(bot, ctx.guild_id, ctx.user.id)
    bot_channel_id = service.voice_channel_of(bot, ctx.guild_id, me.id) if me is not None else None

    if user_channel_id is None:
        raise errors.NotInVoice
    if bot_channel_id is not None and user_channel_id != bot_channel_id:
        raise errors.NotSameVoice


@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS)
def player_connected(
    _: lightbulb.ExecutionPipeline,
    ctx: lightbulb.Context,
    lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
) -> None:
    """Require a player that is connected to voice."""
    if ctx.guild_id is None:
        raise errors.GuildOnly

    player = service.get_player(lavalink_client, ctx.guild_id)
    if player is None or not player.is_connected:
        raise errors.PlayerNotConnected


@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS)
async def may_control(
    _: lightbulb.ExecutionPipeline,
    ctx: lightbulb.Context,
    lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
) -> None:
    """
    Require the caller to be whoever queued the track now playing, or the bot's owner.

    The same rule the now playing buttons apply, so a command and its button cannot disagree.
    The voice rule stays separate - `valid_user_voice` still runs first - so the two checks
    compose the way the buttons compose them.
    """
    if ctx.guild_id is None:
        raise errors.GuildOnly

    player = service.get_player(lavalink_client, ctx.guild_id)
    current = player.current if player is not None else None
    if current is not None and ctx.user.id == current.requester:
        return

    if await owner.is_owner(ctx.client, ctx.user.id):
        return

    raise errors.TrackNotYours


@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS)
def player_playing(
    _: lightbulb.ExecutionPipeline,
    ctx: lightbulb.Context,
    lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
) -> None:
    """Require a player with a track loaded."""
    if ctx.guild_id is None:
        raise errors.GuildOnly

    player = service.get_player(lavalink_client, ctx.guild_id)
    if player is None or not player.is_playing:
        raise errors.PlayerNotPlaying
