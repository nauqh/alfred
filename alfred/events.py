"""Handling of the events Lavalink sends about players.

Two jobs: keeping the now playing view in step with the player - a track starting posts the
view, the queue ending removes it - and reporting the tracks that fail or stall. Node and
websocket state is left to lavalink.py, which already logs it into the same stream.
"""

from __future__ import annotations

import logging

import lavalink

from alfred.log_config import track_logger
from alfred.music.player import AlfredPlayer
from alfred.presence import Presence
from alfred.ui.nowplaying import NowPlayingManager

logger = logging.getLogger(__name__)


class LavalinkEventHandler:
    """
    Keeps the now playing view in step with the player.

    Register it with `lavalink.Client.add_event_hooks`.
    """

    def __init__(self, now_playing: NowPlayingManager, presence: Presence) -> None:
        self._now_playing = now_playing
        self._presence = presence

    @lavalink.listener(lavalink.TrackStartEvent)
    async def on_track_start(self, event: lavalink.TrackStartEvent) -> None:
        track_logger.info("%s - %s - %s", event.track.title, event.track.author, event.track.uri)
        logger.info("Track started on guild %s", event.player.guild_id)

        assert isinstance(event.player, AlfredPlayer)
        # `show` replaces whatever view is up, which covers every way a track can start:
        # naturally, by skip, or by a failed track being replaced with the next one.
        await self._now_playing.show(event.player)
        await self._presence.track_started(event.track)

    @lavalink.listener(lavalink.QueueEndEvent)
    async def on_queue_end(self, event: lavalink.QueueEndEvent) -> None:
        logger.info("Queue finished on guild %s", event.player.guild_id)

        # Nothing left to control. `AlfredPlayer.stop` dispatches this too, so the view also
        # goes when the bot leaves voice; handling must stay idempotent.
        await self._now_playing.hide(event.player.guild_id)
        await self._presence.quiet()

    @lavalink.listener(lavalink.TrackExceptionEvent)
    async def on_track_exception(self, event: lavalink.TrackExceptionEvent) -> None:
        """
        Log a failed track, and let the player advance past it.

        The failed track is still the player's current track - the next `TrackEndEvent` (with a
        ``load_failed`` reason) follows immediately and makes lavalink's own handler pull the
        next song off the queue. No replay here, so a dead or dying stream moves forward instead
        of looping back onto itself.
        """
        logger.warning("Track %r failed on guild %s: %s", event.track.title, event.player.guild_id, event.message)

    @lavalink.listener(lavalink.TrackStuckEvent)
    async def on_track_stuck(self, event: lavalink.TrackStuckEvent) -> None:
        """
        Log a stalled track. Advancing is left to lavalink's own handler.

        A stuck track is usually followed by no `TrackEndEvent`, so lavalink's
        `player._handle_event` advances the player itself on `TrackStuckEvent`. Advancing here
        too would fire `play()` twice - skipping two songs, or, with looping on, replaying the
        stuck one - so this hook only reports it.
        """
        logger.warning(
            "Track %r stuck for %sms on guild %s - skipping",
            event.track.title,
            event.threshold,
            event.player.guild_id,
        )
