"""The queue: seeing it, skipping through it, editing it."""

from __future__ import annotations

import asyncio
import contextlib

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred import constants
from alfred import errors
from alfred.extensions import hooks
from alfred.music import service
from alfred.ui import embeds
from alfred.ui import responses
from alfred.ui.formatting import trim
from alfred.ui.menus import QueuePanelMenu

loader = lightbulb.Loader()

MAX_CHOICES = 25


@loader.command
class Now(
    lightbulb.SlashCommand,
    name="now",
    description="Show the track that is playing now",
    hooks=[hooks.guild_only, hooks.player_playing],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, lavalink_client: lavalink.Client = lightbulb.di.INJECTED) -> None:
        assert ctx.guild_id is not None

        player = service.get_player(lavalink_client, ctx.guild_id)
        if player is None:
            raise errors.PlayerNotPlaying

        await responses.respond(ctx, embed=embeds.now_playing(player))


@loader.command
class Skip(
    lightbulb.SlashCommand,
    name="skip",
    description="Skip the current track",
    hooks=[hooks.guild_only, hooks.valid_user_voice, hooks.player_playing, hooks.may_control],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, lavalink_client: lavalink.Client = lightbulb.di.INJECTED) -> None:
        assert ctx.guild_id is not None

        player = service.get_player(lavalink_client, ctx.guild_id)
        if player is None:
            raise errors.PlayerNotPlaying

        skipped = await player.skip()
        description = (
            f"⏭️ Skipped: [{skipped.title}]({skipped.uri})" if skipped is not None else "⏭️ Skipped the current track"
        )
        await responses.respond(ctx, embed=hikari.Embed(description=description, color=constants.COLOR_ALFRED))


@loader.command
class Queue(
    lightbulb.SlashCommand,
    name="queue",
    description="Show the queue",
    hooks=[hooks.guild_only, hooks.player_playing],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, lavalink_client: lavalink.Client = lightbulb.di.INJECTED) -> None:
        assert ctx.guild_id is not None

        player = service.get_player(lavalink_client, ctx.guild_id)
        if player is None:
            raise errors.PlayerNotPlaying

        # The player controls live on the now playing view, which follows the current track.
        # The only buttons here move this message's window over the queue.
        menu = QueuePanelMenu(lavalink_client, ctx.guild_id, page_size=constants.QUEUE_PAGE_SIZE)

        # A queue that fits on one page has nothing to page through, so it is posted as a
        # plain embed - two permanently greyed-out buttons say only that they do nothing.
        if menu.pages() <= 1:
            await ctx.respond(embed=menu.embed())
            return

        response_id = await ctx.respond(embed=menu.embed(), components=menu)
        await _run_panel(ctx, menu, response_id)


async def _run_panel(ctx: lightbulb.Context, menu: QueuePanelMenu, response_id: hikari.Snowflakeish) -> None:
    """
    Keep the panel's buttons live until nobody has pressed one for a while, then take them off.

    `attach` blocks until the timeout rather than running in the background: it discards the
    menu from the client's registry in a `finally`, which `attach_persistent` never does - see
    the note in `alfred.ui.nowplaying` and the risk recorded in `docs/prd.md`.

    The embed is deliberately left behind. Buttons that no longer answer are worse than none,
    but the page someone stopped on is still a readable snapshot of the queue.
    """
    with contextlib.suppress(asyncio.TimeoutError):
        await menu.attach(ctx.client, timeout=constants.QUEUE_PANEL_TIMEOUT)

    try:
        await ctx.edit_response(response_id, embed=menu.embed(snapshot=True), components=None)
    except (hikari.NotFoundError, hikari.ForbiddenError):
        pass  # Someone deleted the message, or the bot lost the channel. Either way the buttons are gone.
    except hikari.HikariError as e:
        logger.debug("Failed to retire the queue panel's buttons: {}", e)


@lightbulb.di.with_di
async def track_autocomplete(
    ctx: lightbulb.AutocompleteContext[int],
    lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
) -> None:
    """Offer the queued tracks, so ``/remove`` can be pointed at one by index."""
    guild_id = ctx.interaction.guild_id
    player = service.get_player(lavalink_client, guild_id) if guild_id is not None else None

    if player is None or not player.queue:
        await ctx.respond([])
        return

    await ctx.respond(
        [
            hikari.impl.AutocompleteChoiceBuilder(
                name=trim(f"{i + 1}. {trim(track.title, 60)} - {trim(track.author, 20)}", 100),
                value=i + 1,
            )
            for i, track in enumerate(player.queue[:MAX_CHOICES])
        ]
    )


@loader.command
class Remove(
    lightbulb.SlashCommand,
    name="remove",
    description="Remove a track from the queue",
    hooks=[hooks.guild_only, hooks.valid_user_voice, hooks.player_playing],
):
    track = lightbulb.integer("track", "The track number to remove", autocomplete=track_autocomplete, min_value=1)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, lavalink_client: lavalink.Client = lightbulb.di.INJECTED) -> None:
        assert ctx.guild_id is not None

        player = service.get_player(lavalink_client, ctx.guild_id)
        if player is None:
            raise errors.PlayerNotPlaying

        try:
            removed = player.remove(self.track - 1)
        except IndexError:
            raise errors.AlfredError("There is no track at that position in the queue.") from None

        await responses.respond(
            ctx,
            embed=hikari.Embed(
                description=f"Removed: [{removed.title}]({removed.uri})",
                color=constants.COLOR_ALFRED,
            ),
        )
