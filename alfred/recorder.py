"""Recording plays as they start, for the weekly recap.

A separate hook from the now playing handler on purpose: `LavalinkEventHandler` keeps the
view in step with the player, and this module only writes a row - so an embedding or
rendering change never touches what is recorded. A play is recorded when a track *starts*,
which is what the user chose: a skip still counts, because the track did play.
"""

from __future__ import annotations

from datetime import datetime
from datetime import timezone

import lavalink
from loguru import logger

from alfred.storage import PlayStore


class PlayRecorder:
    """Writes one row per track start, for the guild the track played in."""

    def __init__(self, store: PlayStore) -> None:
        self._store = store

    @lavalink.listener(lavalink.TrackStartEvent)
    async def on_track_start(self, event: lavalink.TrackStartEvent) -> None:
        track = event.track
        if track.requester is None:
            # No user to credit - a suspended system track, or something lavalink did not
            # tag. Skipping beats writing a row nobody owns.
            logger.debug("Skipping recording for track without a requester: {!r}", track.title)
            return
        try:
            self._store.record_play(
                user_id=track.requester,
                guild_id=event.player.guild_id,
                title=track.title,
                author=track.author or None,
                uri=track.uri,
                duration_ms=int(track.duration) if track.duration else None,
                played_at=datetime.now(timezone.utc),
            )
            logger.debug("Recorded a play of {!r} for user {}", track.title, track.requester)
        except Exception as e:
            # Recording is a side effect - a failing write must never stop playback.
            logger.warning("Failed to record a play: {}", e)