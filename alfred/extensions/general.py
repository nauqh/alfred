"""Joining and leaving voice, and keeping Lavalink informed about voice state."""

from __future__ import annotations

import logging

import hikari
import lavalink
import lightbulb

from alfred.extensions import hooks
from alfred.music import service
from alfred.ui import responses

logger = logging.getLogger(__name__)

loader = lightbulb.Loader()


@loader.command
class Leave(
    lightbulb.SlashCommand,
    name="leave",
    description="Leave the voice channel, clearing the queue",
    hooks=[hooks.guild_only, hooks.valid_user_voice, hooks.player_connected],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, bot: hikari.GatewayBot = lightbulb.di.INJECTED) -> None:
        assert ctx.guild_id is not None

        # Disconnecting fires a voice state update, which stops and clears the player.
        await bot.update_voice_state(ctx.guild_id, None)
        await responses.respond(ctx, content="Left the voice channel!")


@loader.listener(hikari.VoiceServerUpdateEvent)
async def on_voice_server_update(
    event: hikari.VoiceServerUpdateEvent,
    lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
) -> None:
    """Forward voice server details to Lavalink so it can open its own voice connection."""
    if event.raw_endpoint is None:
        return

    await lavalink_client.voice_update_handler(
        {
            "t": "VOICE_SERVER_UPDATE",
            "d": {
                "guild_id": str(event.guild_id),
                "endpoint": event.raw_endpoint,
                "token": event.token,
            },
        }
    )


@loader.listener(hikari.VoiceStateUpdateEvent)
async def on_voice_state_update(
    event: hikari.VoiceStateUpdateEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
) -> None:
    """Forward the bot's own voice state to Lavalink, then react to what changed in the channel."""
    state = event.state

    await lavalink_client.voice_update_handler(
        {
            "t": "VOICE_STATE_UPDATE",
            "d": {
                "guild_id": str(state.guild_id),
                "user_id": str(state.user_id),
                "channel_id": str(state.channel_id) if state.channel_id is not None else None,
                "session_id": state.session_id,
            },
        }
    )

    await _react_to_voice_state(bot, lavalink_client, event)


async def _react_to_voice_state(
    bot: hikari.GatewayBot,
    lavalink_client: lavalink.Client,
    event: hikari.VoiceStateUpdateEvent,
) -> None:
    """Stop the player when the bot is disconnected, and leave a channel once it is empty."""
    me = bot.get_me()
    if me is None:
        return

    guild_id = event.guild_id
    bot_channel_id = service.voice_channel_of(bot, guild_id, me.id)

    if event.state.user_id == me.id:
        player = service.get_player(lavalink_client, guild_id)
        if bot_channel_id is None and player is not None:
            logger.info("Disconnected from voice on guild %s", guild_id)
            await player.stop()
        return

    if bot_channel_id is None:
        return

    states = bot.cache.get_voice_states_view_for_guild(guild_id)
    if not any(state.channel_id == bot_channel_id and state.user_id != me.id for state in states.values()):
        logger.info("Left empty voice channel on guild %s", guild_id)
        await bot.update_voice_state(guild_id, None)
