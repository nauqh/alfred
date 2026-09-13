"""The buttons Alfred posts: the now playing controls, and the queue panel's paging.

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
from alfred import errors
from alfred import owner
from alfred.music import service
from alfred.music.player import AlfredPlayer
from alfred.ui import embeds

QUEUE_PREV_LABEL = "Prev"
QUEUE_NEXT_LABEL = "Next"


def turn_away_message(mention: str, label: str) -> str:
    """The butler's refusal, for a press the presser had no right to make."""
    return (
        f"{mention} I'm afraid the {label} answers only to the one who requested this "
        "track, sir. Might I suggest a polite word with them instead?"
    )


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

        Three gates, in this order. There has to be something playing - the panel outlives
        its track by the moment it takes the track event to arrive. Then the press has to be
        allowed: the owner may press anything, and whoever queued the track that is playing
        may control that track. Anyone else is turned away with a butler's refusal and never
        reaches the voice rule. Last, whoever passed must still be in the bot's voice channel,
        so a button and its command cannot disagree.

        The player is resolved first because the requester is read off the current track, so
        there is nobody to recognise until there is a track.

        Returns:
            The player, or `None` if the press was rejected and already answered.
        """
        player = self.player()
        if player is None or not player.is_playing:
            await ctx.respond(errors.PlayerNotPlaying.default_message, ephemeral=True)
            return None

        if not await self._may_control(ctx, player):
            await ctx.respond(turn_away_message(ctx.user.mention, ctx.component.label))
            return None

        me = self._bot.get_me()
        bot_channel_id = service.voice_channel_of(self._bot, self._guild_id, me.id) if me is not None else None
        user_channel_id = service.voice_channel_of(self._bot, self._guild_id, ctx.user.id)

        if bot_channel_id is None or user_channel_id != bot_channel_id:
            await ctx.respond(errors.NotSameVoice.default_message, ephemeral=True)
            return None

        return player

    async def _may_control(self, ctx: lightbulb.components.MenuContext, player: AlfredPlayer) -> bool:
        """
        Whether this press is allowed at all.

        The requester is checked before the owner because it costs nothing: the track already
        carries the ID of whoever queued it, while the owner list may need fetching the
        application the first time it is asked for.

        The claim only ever covers the track that is playing. Queueing a song does not buy the
        rest of the queue - once it moves on, so does the right to control it.
        """
        current = player.current
        if current is not None and ctx.user.id == current.requester:
            return True
        return await self._is_owner(ctx)

    async def _is_owner(self, ctx: lightbulb.components.MenuContext) -> bool:
        """
        Whether the presser owns the bot's application.

        Delegates to `alfred.owner.is_owner` - the same answer `hooks.may_control` gives the
        slash commands, so a button and its command cannot disagree.
        """
        return await owner.is_owner(ctx.client, ctx.user.id)

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


class QueuePanelMenu(lightbulb.components.Menu):
    """
    The paging buttons under ``/queue``.

    Nothing here acts on the player, so nothing here is restricted: reading what is queued is
    open to anyone, exactly as the command is. A press only moves this message's own window
    over the queue.

    Like `NowPlayingMenu` it keeps no copy of the queue - each press re-renders from the live
    player, so a panel left open shows what is queued now rather than what was queued when it
    was posted. The page is the one piece of state it does own, because it is a property of
    this message rather than of the player.
    """

    def __init__(self, lavalink_client: lavalink.Client, guild_id: int, *, page_size: int) -> None:
        super().__init__()

        self._lavalink = lavalink_client
        self._guild_id = guild_id
        self._page_size = page_size
        self.page = 0

        self.prev_button = self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY,
            self.on_prev,
            label=QUEUE_PREV_LABEL,
            emoji=constants.EMOJI_PREV_PAGE,
            disabled=True,
        )
        self.next_button = self.add_interactive_button(
            hikari.ButtonStyle.SECONDARY,
            self.on_next,
            label=QUEUE_NEXT_LABEL,
            emoji=constants.EMOJI_NEXT_PAGE,
        )
        self.refresh_buttons()

    def player(self) -> AlfredPlayer | None:
        """The guild's player, or `None` if it has gone away since the panel was posted."""
        return service.get_player(self._lavalink, self._guild_id)

    def pages(self) -> int:
        """How many pages the queue currently fills."""
        player = self.player()
        return embeds.queue_pages(len(player.queue) if player is not None else 0, self._page_size)

    def embed(self, *, snapshot: bool = False) -> hikari.Embed:
        """The panel this menu sits under: one page of the queue."""
        return embeds.queue(
            self.player(),
            title=constants.QUEUE_TITLE,
            page_size=self._page_size,
            page=self.page,
            snapshot=snapshot,
        )

    def refresh_buttons(self) -> None:
        """
        Clamp the page to what the queue now holds, and grey out the ends.

        Called before every render, because the queue moves underneath an open panel: tracks
        play out and the last page stops existing, so the page a button was drawn for may be
        past the end by the time it is pressed.
        """
        pages = self.pages()
        self.page = min(max(self.page, 0), pages - 1)

        self.prev_button.disabled = self.page == 0
        self.next_button.disabled = self.page >= pages - 1

    async def on_prev(self, ctx: lightbulb.components.MenuContext) -> None:
        self.page -= 1
        await self.redraw(ctx)

    async def on_next(self, ctx: lightbulb.components.MenuContext) -> None:
        self.page += 1
        await self.redraw(ctx)

    async def redraw(self, ctx: lightbulb.components.MenuContext) -> None:
        """
        Redraw the panel in place, and give the presser a full timeout to read the new page.

        `set_timeout`, not `extend_timeout`: extending *shifts* the existing deadline, so ten
        presses would buy half an hour. The panel should go quiet a fixed while after the last
        press, however many came before it.
        """
        self.refresh_buttons()
        ctx.set_timeout(constants.QUEUE_PANEL_TIMEOUT)
        await ctx.respond(embed=self.embed(), components=self, edit=True)
