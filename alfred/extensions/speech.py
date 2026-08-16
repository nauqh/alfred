"""Making the bot talk: ``/say``."""

from __future__ import annotations

import hikari
import lavalink
import lightbulb

from alfred import hooks
from alfred import responses
from alfred import service
from alfred.formatting import trim

loader = lightbulb.Loader()

ECHO_LENGTH = 120


@loader.command
class Say(
    lightbulb.SlashCommand,
    name="say",
    description="Say something out loud in the voice channel",
    hooks=[hooks.guild_only, hooks.valid_user_voice],
):
    text = lightbulb.string("text", "What to say")

    @lightbulb.invoke
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
    ) -> None:
        assert ctx.guild_id is not None

        await service.speak(
            bot,
            lavalink_client,
            self.text,
            guild_id=ctx.guild_id,
            requester_id=ctx.user.id,
        )

        await responses.respond(ctx, content=f"> {trim(self.text, ECHO_LENGTH)}")
