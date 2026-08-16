"""Alfred's Lavalink player - a `lavalink.DefaultPlayer` that knows where its tracks came from."""

from __future__ import annotations

import asyncio
import dataclasses

import lavalink
from loguru import logger

PLAYLIST_KEY = "alfred.playlist"

# What LavaSrc names its Flowery TTS tracks, and so how a spoken line is told apart from music
# once it comes back as an event.
SPEECH_SOURCE = "flowery-tts"


@dataclasses.dataclass(frozen=True, slots=True)
class PlaylistRef:
    """Where a queued track came from, so ``/queue`` can credit the playlist it belongs to."""

    name: str
    url: str | None = None


def set_playlist(track: lavalink.AudioTrack, playlist: PlaylistRef) -> None:
    """Tag a track with the playlist it was loaded from."""
    track.extra[PLAYLIST_KEY] = playlist


def get_playlist(track: lavalink.AudioTrack) -> PlaylistRef | None:
    """Return the playlist a track was loaded from, if it was loaded from one."""
    playlist = track.extra.get(PLAYLIST_KEY)
    return playlist if isinstance(playlist, PlaylistRef) else None


class AlfredPlayer(lavalink.DefaultPlayer):
    """Adds to the default player a history-aware `stop` that resets rather than merely stopping."""

    #: The volume to put back once a spoken line ends. `alfred.service.speak` raises the volume
    #: for speech and records what it was here; `alfred.events` restores it. `None` means no
    #: line is speaking, so there is nothing owed.
    volume_before_speech: int | None = None

    async def skip(self) -> lavalink.AudioTrack | None:
        """Play the next track, returning the one that was skipped."""
        skipped = self.current
        await self.play()
        return skipped

    def remove(self, index: int) -> lavalink.AudioTrack:
        """
        Remove a track from the queue by index.

        Raises:
            IndexError: If there is no track at that index.
        """
        return self.queue.pop(index)

    async def stop(self) -> None:
        """
        Stop playback and reset the player: queue, loop and shuffle.

        Local state is reset even when the node cannot be reached - this also runs when the bot
        has been disconnected from voice, which is exactly when the node may already be gone.
        """
        try:
            await super().stop()
        except (lavalink.LavalinkError, OSError, asyncio.TimeoutError) as e:
            logger.warning("Failed to stop player on guild {} cleanly: {}", self.guild_id, e)
            self.current = None

        self.queue.clear()
        self.loop = self.LOOP_NONE
        self.shuffle = False

        # `DefaultPlayer.play` dispatches this too when it runs out of queue, so handling must
        # stay idempotent.
        self.client._dispatch_event(lavalink.QueueEndEvent(self))
