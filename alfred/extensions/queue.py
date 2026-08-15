"""The queue: seeing it, skipping through it, editing it."""

from __future__ import annotations

import asyncio
import contextlib

import hikari
import lavalink
import lightbulb

from alfred import errors
from alfred import hooks
from alfred import responses
from alfred import service
from alfred.formatting import trim
from alfred.menus import MENU_TIMEOUT
from alfred.menus import PlayerMenu

loader = lightbulb.Loader()

MAX_CHOICES = 25


@loader.command
class Skip(
    lightbulb.SlashCommand,
    name="skip",
    description="Skip the current track",
    hooks=[hooks.guild_only, hooks.valid_user_voice, hooks.player_playing],
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
        await responses.respond(ctx, embed=hikari.Embed(description=description))


@loader.command
class Queue(
    lightbulb.SlashCommand,
    name="queue",
    description="Show the queue, with controls for the player",
    hooks=[hooks.guild_only, hooks.player_playing],
):
    @lightbulb.invoke
    async def invoke(
        self,
        ctx: lightbulb.Context,
        client: lightbulb.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
    ) -> None:
        assert ctx.guild_id is not None

        player = service.get_player(lavalink_client, ctx.guild_id)
        if player is None:
            raise errors.PlayerNotPlaying

        menu = PlayerMenu(bot, lavalink_client, ctx.guild_id)
        response = await ctx.respond(embed=menu.embed(), components=menu)

        # This blocks until the last press times the menu out, or a press ends it. The buttons
        # are then taken off the panel, so a dead panel cannot be pressed - the embed is left
        # where it is, still readable as the queue it was when it went quiet.
        with contextlib.suppress(asyncio.TimeoutError):
            await menu.attach(client, timeout=MENU_TIMEOUT)

        with contextlib.suppress(hikari.NotFoundError, hikari.ForbiddenError):
            await ctx.edit_response(response, components=[])


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
                value=i,
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
    track = lightbulb.integer("track", "The track to remove", autocomplete=track_autocomplete, min_value=0)

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, lavalink_client: lavalink.Client = lightbulb.di.INJECTED) -> None:
        assert ctx.guild_id is not None

        player = service.get_player(lavalink_client, ctx.guild_id)
        if player is None:
            raise errors.PlayerNotPlaying

        try:
            removed = player.remove(self.track)
        except IndexError:
            raise errors.AlfredError("There is no track at that position in the queue.") from None

        await responses.respond(
            ctx,
            embed=hikari.Embed(description=f"Removed: [{removed.title}]({removed.uri})"),
        )
