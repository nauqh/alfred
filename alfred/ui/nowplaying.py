"""The now playing view - a message with the player controls, following the current track.

One message per guild. It is posted when a track starts playing and deleted when the track
ends: moving to the next track replaces the old track's view with the next one's, and the
queue ending removes the view entirely. The view carries all of the player's buttons, so it
lives exactly as long as there is something to control.

Posting happens from the Lavalink track events rather than from the commands, so the view
follows the player no matter how the track changed - skip, stop, a track ending on its own,
or the retry logic putting a failed track back on.

While the view is up its progress bar is re-drawn on a timer, because `player.position` is
read once when the embed is built and the bar would otherwise show the same moment of the
track for as long as the track lasts.
"""

from __future__ import annotations

import asyncio
import contextlib
import dataclasses

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred.music.player import AlfredPlayer
from alfred.ui import embeds
from alfred.ui.menus import NowPlayingMenu

# How often the progress bar is re-drawn. The bar is ten blocks wide, so a block is a tenth
# of the track - on a three minute song that is 18 seconds, and refreshing much faster only
# spends rate limit on an identical embed.
REFRESH_INTERVAL = 15.0


@dataclasses.dataclass(slots=True)
class _View:
    """A posted now playing message, and the tasks keeping its buttons live and its bar moving."""

    channel_id: int
    message_id: int
    buttons: asyncio.Task[None]
    refresh: asyncio.Task[None]


class NowPlayingManager:
    """Posts, replaces and deletes the now playing view of every guild."""

    def __init__(self, bot: hikari.GatewayBot, client: lightbulb.Client, lavalink_client: lavalink.Client) -> None:
        self._bot = bot
        self._client = client
        self._lavalink = lavalink_client
        self._views: dict[int, _View] = {}

    async def show(self, player: AlfredPlayer) -> None:
        """Post the view for the player's current track, replacing any view already up."""
        await self.hide(player.guild_id)

        if player.current is None or player.text_channel_id is None:
            return

        track_url = player.current.uri if player.current is not None else None
        menu = NowPlayingMenu(self._bot, self._lavalink, player.guild_id, track_url=track_url)
        # The view lives exactly as long as the track, so the buttons get no timeout: `hide`
        # cancels this when the message goes. `attach` on a task rather than
        # `attach_persistent(timeout=None)`: the persistent handle never discards the menu from
        # the client's registry (lightbulb/components/menus.py - `MenuHandle.__init__` throws
        # the container away), so it would leak one entry per track.
        buttons = asyncio.create_task(menu.attach(self._client, timeout=None))

        try:
            message = await self._bot.rest.create_message(
                player.text_channel_id,
                embed=embeds.now_playing(player),
                components=menu,
            )
        except hikari.HikariError as e:
            buttons.cancel()
            logger.warning("Failed to post the now playing view on guild {}: {}", player.guild_id, e)
            return

        refresh = asyncio.create_task(self._refresh(player, player.text_channel_id, message.id))

        self._views[player.guild_id] = _View(player.text_channel_id, message.id, buttons, refresh)
        logger.info("Posted the now playing view on guild {}", player.guild_id)

    async def _refresh(self, player: AlfredPlayer, channel_id: int, message_id: int) -> None:
        """Re-draw the view's progress bar on a timer, until `hide` cancels this."""
        while True:
            await asyncio.sleep(REFRESH_INTERVAL)
            if not await self._redraw(player, channel_id, message_id):
                return

    async def _redraw(self, player: AlfredPlayer, channel_id: int, message_id: int) -> bool:
        """
        Re-draw the view's bar once.

        Only the embed is edited. The buttons are left out of the call rather than re-sent:
        hikari leaves an unspecified component list alone, so the menu keeps the custom IDs
        it was posted with, and its own redraw stays the only thing that moves the labels.

        Returns:
            Whether it is worth drawing again.
        """
        current = player.current
        # Nothing to redraw: the bar does not move while paused, and a stream has no position
        # to show - `player_bar` draws it as a full bar reading LIVE. Both can change without
        # the track changing, so this is a skipped frame rather than the end of the loop.
        if current is None or current.is_stream or player.paused:
            return True

        try:
            await self._bot.rest.edit_message(channel_id, message_id, embed=embeds.now_playing(player))
        except (hikari.NotFoundError, hikari.ForbiddenError):
            # The message was deleted by hand, or the bot lost the channel. Nothing is left to
            # refresh, and every later tick would raise exactly the same error.
            logger.debug("Stopped refreshing the now playing view on guild {}", player.guild_id)
            return False
        except hikari.HikariError as e:
            # A transient REST failure. The next tick redraws from the player anyway, so a
            # missed frame costs nothing worth retrying for.
            logger.debug("Failed to refresh the now playing view on guild {}: {}", player.guild_id, e)

        return True

    async def hide(self, guild_id: int) -> None:
        """Delete the guild's now playing view, if one is up."""
        view = self._views.pop(guild_id, None)
        if view is None:
            return

        # Awaiting the cancelled task is what unregisters the menu: `attach` discards it in a
        # `finally`, so the registry is clean before the message goes.
        view.refresh.cancel()
        view.buttons.cancel()
        for task in (view.refresh, view.buttons):
            with contextlib.suppress(asyncio.CancelledError):
                await task

        # NotFound: someone deleted the message by hand. Either way the view is gone.
        with contextlib.suppress(hikari.NotFoundError, hikari.ForbiddenError):
            await self._bot.rest.delete_message(view.channel_id, view.message_id)
        logger.info("Deleted the now playing view on guild {}", guild_id)
