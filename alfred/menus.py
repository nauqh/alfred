"""The buttons under ``/queue``.

Built on `lightbulb.components`, which ships with lightbulb 3 - the legacy bot's buttons were
hikari-miru views, and miru is not part of this stack.

The buttons are labelled rather than iconed. State lives in the label (`Loop: track`) instead
of in a swapped emoji, so the control reads the same to someone who has never used the bot.

The menu owns the embed it sits under, so a press can redraw the queue and the labels in the
same edit: press Skip and the panel shows the track that is playing now.
"""

from __future__ import annotations

import asyncio

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred import embeds
from alfred import errors
from alfred import service

QUEUE_TITLE = "Queue"
QUEUE_PREVIEW_LENGTH = 10

# How long the buttons stay live for. Every accepted press resets it, so a panel someone is
# using stays usable; one nobody touches goes quiet and loses its buttons.
MENU_TIMEOUT = 180.0

# How long a Skip waits for the node to report the next track before redrawing anyway.
TRACK_CHANGE_TIMEOUT = 2.0

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
    The row of controls under a `/queue` panel.

    One menu belongs to one `/queue` invocation. It holds no player state of its own - every
    press looks the player up again, so a panel left open in the channel still acts on
    whatever is playing now, and answers with an error once there is nothing.
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
        """The guild's player, or `None` if it has gone away since the panel was posted."""
        return service.get_player(self._lavalink, self._guild_id)

    def embed(self) -> hikari.Embed:
        """The panel this menu sits under: the current track, and what follows it."""
        player = self.player()
        if player is None:
            return hikari.Embed(title=QUEUE_TITLE, description="Nothing is playing.")

        return embeds.queue(player, title=QUEUE_TITLE, preview_length=QUEUE_PREVIEW_LENGTH)

    def _pause_label(self) -> str:
        player = self.player()
        return "Resume" if player is not None and player.paused else "Pause"

    def _loop_label(self) -> str:
        player = self.player()
        return LOOP_LABELS.get(player.loop if player is not None else 0, "Loop: off")

    def refresh_labels(self) -> None:
        """Bring the labels back in step with the player, before the panel is edited."""
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
        bot_channel_id = service.voice_channel_of(self._bot, self._guild_id, me.id) if me is not None else None
        user_channel_id = service.voice_channel_of(self._bot, self._guild_id, ctx.user.id)

        if bot_channel_id is None or user_channel_id != bot_channel_id:
            await ctx.respond(errors.NotSameVoice.default_message, ephemeral=True)
            return None

        player = self.player()
        if player is None or not player.is_playing:
            await ctx.respond(errors.PlayerNotPlaying.default_message, ephemeral=True)
            return None

        # A panel in use is a panel worth keeping live.
        ctx.set_timeout(MENU_TIMEOUT)
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

        # `play` only asks the node to change track; `player.current` catches up when the node
        # reports the new track back over the websocket. Deferring first buys the time to wait
        # for that, so the redraw shows the track that is playing rather than the one skipped.
        await ctx.defer(edit=True)

        previous = player.current
        await player.play()
        logger.info("Track skipped on guild {} by button", self._guild_id)

        await _wait_for_track_change(player, previous)

        if player.current is None:
            # Nothing was queued behind it, so there is nothing left to control.
            await ctx.respond(embed=self.embed(), components=[], edit=True)
            ctx.stop_interacting()
            return

        await self.redraw(ctx)

    async def on_loop(self, ctx: lightbulb.components.MenuContext) -> None:
        player = await self.check(ctx)
        if player is None:
            return

        player.set_loop(NEXT_LOOP.get(player.loop, lavalink.DefaultPlayer.LOOP_NONE))
        await self.redraw(ctx)

    async def on_stop(self, ctx: lightbulb.components.MenuContext) -> None:
        player = await self.check(ctx)
        if player is None:
            return

        # `stop` clears the queue, so the panel has nothing left to control: it is redrawn
        # once to show that, and then goes dead.
        await player.stop()
        logger.info("Playback stopped on guild {} by button", self._guild_id)

        await ctx.respond(embed=self.embed(), components=[], edit=True)
        ctx.stop_interacting()

    async def redraw(self, ctx: lightbulb.components.MenuContext) -> None:
        """Redraw the panel with an embed and labels matching the player."""
        self.refresh_labels()
        await ctx.respond(embed=self.embed(), components=self, edit=True)


async def _wait_for_track_change(
    player: lavalink.DefaultPlayer,
    previous: lavalink.AudioTrack | None,
    *,
    interval: float = 0.05,
) -> None:
    """
    Wait for the node to report a track other than `previous`, or give up.

    Giving up is not an error: the panel is redrawn either way, and at worst it shows the
    track that was playing a moment ago until the next press.
    """
    loop = asyncio.get_running_loop()
    # Read at call time rather than bound as a default, so tests can shorten the wait.
    deadline = loop.time() + TRACK_CHANGE_TIMEOUT

    while player.current is previous and loop.time() < deadline:
        await asyncio.sleep(interval)
