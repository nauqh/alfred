"""Handling of the events Lavalink sends about players and nodes."""

from __future__ import annotations

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred import embeds
from alfred.menus import PlayerMenu
from alfred.player import AlfredPlayer
from alfred.player import NowPlayingMessage


class LavalinkEventHandler:
    """
    Keeps the now-playing message in step with the player.

    Register it with `lavalink.Client.add_event_hooks`.
    """

    def __init__(
        self,
        bot: hikari.GatewayBot,
        client: lightbulb.Client,
        lavalink_client: lavalink.Client,
    ) -> None:
        self._bot = bot
        # The menu on the now-playing message is attached to the lightbulb client, which is
        # what routes button presses back to it.
        self._client = client
        self._lavalink = lavalink_client

    @lavalink.listener(lavalink.TrackStartEvent)
    async def on_track_start(self, event: lavalink.TrackStartEvent) -> None:
        player = event.player
        assert isinstance(player, AlfredPlayer)

        logger.bind(track=True).info("{} - {} - {}", event.track.title, event.track.author, event.track.uri)
        logger.info("Track started on guild {}", player.guild_id)

        await self.post_now_playing(player)

    @lavalink.listener(lavalink.QueueEndEvent)
    async def on_queue_end(self, event: lavalink.QueueEndEvent) -> None:
        player = event.player
        assert isinstance(player, AlfredPlayer)

        logger.info("Queue finished on guild {}", player.guild_id)
        await self.clear_now_playing(player)

    @lavalink.listener(lavalink.TrackEndEvent)
    async def on_track_end(self, event: lavalink.TrackEndEvent) -> None:
        logger.debug("Track finished on guild {} ({})", event.player.guild_id, event.reason)

    @lavalink.listener(lavalink.TrackExceptionEvent)
    async def on_track_exception(self, event: lavalink.TrackExceptionEvent) -> None:
        logger.warning(
            "Track {!r} failed on guild {}: {}",
            event.track.title,
            event.player.guild_id,
            event.message,
        )

    @lavalink.listener(lavalink.TrackStuckEvent)
    async def on_track_stuck(self, event: lavalink.TrackStuckEvent) -> None:
        logger.warning(
            "Track {!r} stuck for {}ms on guild {} - skipping",
            event.track.title,
            event.threshold,
            event.player.guild_id,
        )
        await event.player.play()

    @lavalink.listener(lavalink.NodeConnectedEvent)
    async def on_node_connected(self, event: lavalink.NodeConnectedEvent) -> None:
        logger.info("Connected to Lavalink node {!r}", event.node.name)

    @lavalink.listener(lavalink.NodeDisconnectedEvent)
    async def on_node_disconnected(self, event: lavalink.NodeDisconnectedEvent) -> None:
        logger.warning("Disconnected from Lavalink node {!r} (code {}): {}", event.node.name, event.code, event.reason)

    @lavalink.listener(lavalink.WebSocketClosedEvent)
    async def on_websocket_closed(self, event: lavalink.WebSocketClosedEvent) -> None:
        logger.warning(
            "Voice websocket closed on guild {} (code {}): {}",
            event.player.guild_id,
            event.code,
            event.reason,
        )

    async def post_now_playing(self, player: AlfredPlayer) -> None:
        """Replace the guild's now-playing message with one describing the current track."""
        await self.clear_now_playing(player)

        if not player.is_playing or player.announce_channel_id is None:
            return

        channel_id = player.announce_channel_id
        menu = PlayerMenu(self._bot, self._lavalink, player.guild_id)

        try:
            message = await self._bot.rest.create_message(
                channel=channel_id,
                embed=embeds.now_playing(player),
                components=menu,
            )
        except hikari.HikariError as e:
            logger.error("Failed to post player message in channel {}: {}", channel_id, e)
            return

        # No timeout: the buttons stay live for as long as the message does, and the message
        # only outlives the track by the moment it takes to delete it.
        player.menu_handle = menu.attach_persistent(self._client, timeout=None)
        player.now_playing = NowPlayingMessage(channel_id=channel_id, message_id=int(message.id))

    async def clear_now_playing(self, player: AlfredPlayer) -> None:
        """
        Take down the guild's now-playing message, if there is one.

        Safe to call more than once - the reference is dropped before the message is deleted.
        """
        # Stopping the menu first means a press landing during the delete is answered by a
        # menu that no longer routes anywhere, rather than acting on the next track.
        handle, player.menu_handle = player.menu_handle, None
        if handle is not None:
            handle.stop_interacting()

        now_playing, player.now_playing = player.now_playing, None
        if now_playing is None:
            return

        try:
            await self._bot.rest.delete_message(now_playing.channel_id, now_playing.message_id)
        except (hikari.NotFoundError, hikari.ForbiddenError):
            logger.debug("Player message {} was already gone", now_playing.message_id)
        except hikari.HikariError as e:
            logger.error("Failed to delete player message {}: {}", now_playing.message_id, e)
