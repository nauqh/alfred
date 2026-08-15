"""Handling of the events Lavalink sends about players and nodes.

Nothing here posts to Discord. The player announces itself through the reply to the command
that queued it, and through `/queue`; the bot does not follow a queue around a channel with a
message per track. What is left is the record of what the node is doing.
"""

from __future__ import annotations

import lavalink
from loguru import logger


class LavalinkEventHandler:
    """
    Logs what the node reports, and keeps a stuck player moving.

    Register it with `lavalink.Client.add_event_hooks`.
    """

    @lavalink.listener(lavalink.TrackStartEvent)
    async def on_track_start(self, event: lavalink.TrackStartEvent) -> None:
        logger.bind(track=True).info("{} - {} - {}", event.track.title, event.track.author, event.track.uri)
        logger.info("Track started on guild {}", event.player.guild_id)

    @lavalink.listener(lavalink.QueueEndEvent)
    async def on_queue_end(self, event: lavalink.QueueEndEvent) -> None:
        logger.info("Queue finished on guild {}", event.player.guild_id)

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
