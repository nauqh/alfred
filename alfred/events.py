"""Handling of the events Lavalink sends about players and nodes.

Nothing here posts to Discord. The player announces itself through the reply to the command
that queued it, and through `/queue`; the bot does not follow a queue around a channel with a
message per track. What is left is the record of what the node is doing.
"""

from __future__ import annotations

import lavalink
from loguru import logger

# How many times to re-queue a track that failed to load or stalled mid-play, before letting
# the player move on to the next one. YouTube streams die transiently (rate limits, expired
# stream URLs) - re-queueing the same track once keeps the song going instead of skipping.
RETRY_KEY = "alfred.retry_count"
MAX_RETRIES = 1


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
        """
        Log a failed track, and re-queue it once before the player advances past it.

        On `TrackExceptionEvent` the failed track is still the player's current track. Putting
        it back at the front of the queue makes the player's own end-of-track handler (which runs
        right after this on `TrackEndEvent`) pick the same track again, so a transient YouTube
        failure retries the song rather than skipping to the next one. The retry is capped by
        a counter on the track, so a genuinely dead track still moves on.
        """
        track = event.track
        attempts = int(track.extra.get(RETRY_KEY, 0))
        logger.warning(
            "Track {!r} failed on guild {} (attempt {}): {}",
            track.title,
            event.player.guild_id,
            attempts + 1,
            event.message,
        )

        if attempts < MAX_RETRIES:
            track.extra[RETRY_KEY] = attempts + 1
            event.player.queue.insert(0, track)
            logger.info("Retrying {!r} once on guild {}", track.title, event.player.guild_id)

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
