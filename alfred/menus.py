"""The buttons on the now-playing message.

Built on `lightbulb.components`, which ships with lightbulb 3 - the legacy bot's buttons were
hikari-miru views, and miru is not part of this stack.

The buttons are labelled rather than iconed. State lives in the label (`Loop: track`) instead
of in a swapped emoji, so the control reads the same to someone who has never used the bot.
"""

from __future__ import annotations

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred import errors
from alfred import service

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


class PlayerMenu(lightbulb.components.Menu):
    """
    The row of controls under the now-playing message.

    One menu belongs to one message. `events.LavalinkEventHandler` builds a new one for each
    track and stops the previous one, so a stale message's buttons stop responding rather than
    acting on whatever is playing now.
    """

    def __init__(
        self,
        bot: hikari.GatewayBot,
        lavalink_client: lavalink.Client,
        guild_id: int,
    ) -> None:
        super().__init__()

        self._bot = bot
        self._lavalink = lavalink_client
        self._guild_id = guild_id

        self.pause_button = self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY,
            self.on_pause,
            label=self._pause_label(),
        )
        self.skip_button = self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY,
            self.on_skip,
            label="Skip",
        )
        self.loop_button = self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY,
            self.on_loop,
            label=self._loop_label(),
        )
        self.stop_button = self.add_interactive_button(
            hikari.ButtonStyle.DANGER,
            self.on_stop,
            label="Stop",
        )

    def player(self) -> lavalink.DefaultPlayer | None:
        """The guild's player, or `None` if it has gone away since the message was posted."""
        return service.get_player(self._lavalink, self._guild_id)

    def _pause_label(self) -> str:
        player = self.player()
        return "Resume" if player is not None and player.paused else "Pause"

    def _loop_label(self) -> str:
        player = self.player()
        return LOOP_LABELS.get(player.loop if player is not None else 0, "Loop: off")

    def refresh_labels(self) -> None:
        """Bring the labels back in step with the player, before the message is edited."""
        self.pause_button.label = self._pause_label()
        self.loop_button.label = self._loop_label()

    async def check(self, ctx: lightbulb.components.MenuContext) -> lavalink.DefaultPlayer | None:
        """
        Resolve the player for a press, once the presser is allowed to make it.

        Only members in the bot's voice channel may press - the same rule the `/skip` and
        `/leave` commands apply, so a button and its command cannot disagree.

        Returns:
            The player, or `None` if the press was rejected and already answered.
        """
        me = self._bot.get_me()
        bot_channel_id = (
            service.voice_channel_of(self._bot, self._guild_id, me.id) if me is not None else None
        )
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
        await self._update(ctx)

    async def on_skip(self, ctx: lightbulb.components.MenuContext) -> None:
        player = await self.check(ctx)
        if player is None:
            return

        # The track change posts a new now-playing message with its own menu, and this one is
        # stopped as the old message comes down.
        await player.play()

    async def on_loop(self, ctx: lightbulb.components.MenuContext) -> None:
        player = await self.check(ctx)
        if player is None:
            return

        player.set_loop(NEXT_LOOP.get(player.loop, lavalink.DefaultPlayer.LOOP_NONE))
        await self._update(ctx)

    async def on_stop(self, ctx: lightbulb.components.MenuContext) -> None:
        player = await self.check(ctx)
        if player is None:
            return

        # `stop` clears the queue and dispatches QueueEndEvent, which takes this message -
        # and so these buttons - down.
        await player.stop()

    async def _update(self, ctx: lightbulb.components.MenuContext) -> None:
        """Redraw the message with labels matching the player."""
        self.refresh_labels()
        await ctx.respond(edit=True, components=self)
