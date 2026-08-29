"""What Discord shows under the bot's name.

The default activity is static - "Listening to <landing page>" - set when the bot starts and
shown whenever nothing is playing. While a track plays, the presence shows that track, so
someone glancing at the sidebar sees what is actually on.

The track presence follows the player, not the commands: it is set on track start and cleared
when the queue ends. `AlfredPlayer.stop` dispatches `QueueEndEvent` too, so leaving voice or
the bot being disconnected both clear it through the same event - no separate hooks to forget.
"""

from __future__ import annotations

from typing import Final

import hikari
import lavalink
from loguru import logger

from alfred import constants
from alfred.ui.formatting import trim

# Discord caps an activity name at 128 characters. YouTube titles routinely run longer, so the
# track is trimmed to fit rather than letting the gateway reject the update.
ACTIVITY_NAME_LIMIT: Final = 128


class Presence:
    """Owns the default activity and the per-track override."""

    def __init__(self, bot: hikari.GatewayBot) -> None:
        self._bot = bot

    async def start(self) -> None:
        """Set the default activity - what is shown whenever nothing is playing."""
        await self._set(constants.ACTIVITY_NAME)

    async def track_started(self, track: lavalink.AudioTrack) -> None:
        """Show the track that just started, replacing the default activity."""
        name = trim(track.title, ACTIVITY_NAME_LIMIT)
        if track.author:
            name = trim(f"{track.title} - {track.author}", ACTIVITY_NAME_LIMIT)
        await self._set(name)

    async def quiet(self) -> None:
        """Revert to the default activity - nothing is playing."""
        await self._set(constants.ACTIVITY_NAME)

    async def _set(self, name: str) -> None:
        try:
            await self._bot.update_presence(
                activity=hikari.Activity(name=name, type=hikari.ActivityType.LISTENING),
            )
        except hikari.HikariError as e:
            # The presence is cosmetic - losing it must not take the audio flow down with it.
            logger.warning("Failed to update presence to {!r}: {}", name, e)
