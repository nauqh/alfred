"""The buttons under the now playing view.

Built on `lightbulb.components`, which ships with lightbulb 3 - the legacy bot's buttons were
hikari-miru views, and miru is not part of this stack.

The buttons are labelled rather than iconed. State lives in the label (`Loop: track`) instead
of in a swapped emoji, so the control reads the same to someone who has never used the bot.

The menu owns the embed it sits under, so a press can redraw the track and the labels in the
same edit: press Pause and the panel shows a paused bar. Skip is different - the track event
it causes deletes this message and posts the next track's view, so that press only acknowledges
and steps aside.
"""

from __future__ import annotations

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred import constants
from alfred import embeds
from alfred import errors
from alfred import service
from alfred.player import AlfredPlayer

LOOP_LABELS = {
    lavalink.DefaultPlayer.LOOP_NONE: "Loop: off",
    lavalink.DefaultPlayer.LOOP_SINGLE: "Loop: track",
    lavalink.DefaultPlayer.LOOP_QUEUE: "Loop: queue",
}

# LOOP_NONE -> LOOP_SINGLE -> LOOP_QUEUE -> LOOP_NONE.
NEXT_LOOP = {
    lavalink.DefaultPlayer.LOOP_NONE: lavalink.DefaultPlayer.LOOP_SINGLE,
    lavalink.DefaultPlayer.LOOP_SINGLE: lavalink.DefaultPlayer.LOOP_QUEUE,
    lavalink.DefaultPlayer.LOOP_QUEUE: lavalink.DefaultPlayer.LOOP_NONE,
}


class NowPlayingMenu(lightbulb.components.Menu):
    """
    The row of controls under the now playing message.

    One menu belongs to one now playing message - so, to one track. It holds no player state
    of its own: every press looks the player up again, so the buttons act on whatever is
    playing now, and answer with an error once there is nothing.
    """

    def __init__(
        self,
        bot: hikari.GatewayBot,
        lavalink_client: lavalink.Client,
        guild_id: int,
        track_url: str | None = None,
    ) -> None:
        super().__init__()

        self._bot = bot
        self._lavalink = lavalink_client
        self._guild_id = guild_id

        self.pause_button = self.add_interactive_button(
            self._pause_style(),
            self.on_pause,
            label=self._pause_label(),
            emoji=self._pause_emoji(),
        )
        self.skip_button = self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY,
            self.on_skip,
            label="Skip",
            emoji=constants.EMOJI_SKIP,
        )
        self.loop_button = self.add_interactive_button(
            self._loop_style(),
            self.on_loop,
            label=self._loop_label(),
            emoji=self._loop_emoji(),
        )
        if track_url and track_url.startswith(("http://", "https://")):
            self.add_link_button(track_url, label="Link", emoji=constants.EMOJI_LINK)

    def player(self) -> AlfredPlayer | None:
        """The guild's player, or `None` if it has gone away since the view was posted."""
        return service.get_player(self._lavalink, self._guild_id)

    def embed(self) -> hikari.Embed:
        """The panel this menu sits under: the current track and its progress."""
        return embeds.now_playing(self.player())

    def _pause_label(self) -> str:
        player = self.player()
        return "Resume" if player is not None and player.paused else "Pause"

    def _pause_emoji(self) -> str:
        player = self.player()
        return constants.EMOJI_RESUME if player is not None and player.paused else constants.EMOJI_PAUSE

    def _pause_style(self) -> hikari.ButtonStyle:
        player = self.player()
        return hikari.ButtonStyle.SUCCESS if player is not None and player.paused else hikari.ButtonStyle.SECONDARY

    def _loop_label(self) -> str:
        player = self.player()
        return LOOP_LABELS.get(player.loop if player is not None else 0, "Loop: off")

    def _loop_emoji(self) -> str:
        player = self.player()
        if player is not None and player.loop == lavalink.DefaultPlayer.LOOP_SINGLE:
            return constants.EMOJI_LOOP_SINGLE
        return constants.EMOJI_LOOP

    def _loop_style(self) -> hikari.ButtonStyle:
        player = self.player()
        if player is not None and player.loop != lavalink.DefaultPlayer.LOOP_NONE:
            return hikari.ButtonStyle.PRIMARY
        return hikari.ButtonStyle.SECONDARY

    def refresh_labels(self) -> None:
        """Bring the labels, styles and emojis back in step with the player, before the view is edited."""
        self.pause_button.label = self._pause_label()
        self.pause_button.emoji = self._pause_emoji()
        self.pause_button.style = self._pause_style()

        self.loop_button.label = self._loop_label()
        self.loop_button.emoji = self._loop_emoji()
        self.loop_button.style = self._loop_style()

    async def check(self, ctx: lightbulb.components.MenuContext) -> AlfredPlayer | None:
        """
        Resolve the player for a press, once the presser is allowed to make it.

        Only members in the bot's voice channel may press - the same rule the `/skip` and
        `/leave` commands apply, so a button and its command cannot disagree.

        Returns:
            The player, or `None` if the press was rejected and already answered.
        """
        me = self._bot.get_me()
        bot_channel_id = service.voice_channel_of(self._bot, self._guild_id, me.id) if me is not None else None
        user_channel_id = service.voice_channel_of(self._bot, self._guild_id, ctx.user.id)

        if bot_channel_id is None or user_channel_id != bot_channel_id:
            await ctx.respond(errors.NotSameVoice.default_message, ephemeral=True)
            return None

        player = self.player()
        if player is None or not player.is_playing:
            await ctx.respond(errors.PlayerNotPlaying.default_message, ephemeral=True)
            return None

        return player

    async def on_pause(self, ctx: lightbulb.components.MenuContext) -> None:
        player = await self.check(ctx)
        if player is None:
            return

        await player.set_pause(not player.paused)
        logger.info("Playback {} on guild {} by button", "paused" if player.paused else "resumed", self._guild_id)
        await self.redraw(ctx)

    async def on_skip(self, ctx: lightbulb.components.MenuContext) -> None:
        player = await self.check(ctx)
        if player is None:
            return

        # The track end this causes deletes this message and posts the next track's view, so
        # there is nothing to redraw here - only acknowledge and step aside.
        await ctx.defer(edit=True)
        await player.play()
        logger.info("Track skipped on guild {} by button", self._guild_id)
        ctx.stop_interacting()

    async def on_loop(self, ctx: lightbulb.components.MenuContext) -> None:
        player = await self.check(ctx)
        if player is None:
            return

        player.set_loop(NEXT_LOOP.get(player.loop, lavalink.DefaultPlayer.LOOP_NONE))
        await self.redraw(ctx)

    async def redraw(self, ctx: lightbulb.components.MenuContext) -> None:
        """Redraw the view with an embed and labels matching the player."""
        self.refresh_labels()
        await ctx.respond(embed=self.embed(), components=self, edit=True)
