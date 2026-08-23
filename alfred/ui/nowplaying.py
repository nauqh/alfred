"""The now playing view - a message with the player controls, following the current track.

One message per guild. It is posted when a track starts playing and deleted when the track
ends: moving to the next track replaces the old track's view with the next one's, and the
queue ending removes the view entirely. The view carries all of the player's buttons, so it
lives exactly as long as there is something to control.

Posting happens from the Lavalink track events rather than from the commands, so the view
follows the player no matter how the track changed - skip, stop, a track ending on its own,
or the retry logic putting a failed track back on.
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


@dataclasses.dataclass(slots=True)
class _View:
    """A posted now playing message, and the task keeping its buttons live."""

    channel_id: int
    message_id: int
    buttons: asyncio.Task[None]


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

        self._views[player.guild_id] = _View(player.text_channel_id, message.id, buttons)
        logger.info("Posted the now playing view on guild {}", player.guild_id)

    async def hide(self, guild_id: int) -> None:
        """Delete the guild's now playing view, if one is up."""
        view = self._views.pop(guild_id, None)
        if view is None:
            return

        # Awaiting the cancelled task is what unregisters the menu: `attach` discards it in a
        # `finally`, so the registry is clean before the message goes.
        view.buttons.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await view.buttons

        # NotFound: someone deleted the message by hand. Either way the view is gone.
        with contextlib.suppress(hikari.NotFoundError, hikari.ForbiddenError):
            await self._bot.rest.delete_message(view.channel_id, view.message_id)
        logger.info("Deleted the now playing view on guild {}", guild_id)
