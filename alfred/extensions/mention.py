"""Talking to Alfred by mentioning him, including from a voice channel's own chat.

Discord's voice channels carry an ordinary text chat, and its messages arrive through the
normal message event. That makes ``@Alfred play something`` the closest thing to speaking to
the bot that is actually available: Lavalink holds the guild's one voice connection and does
not hand back what it hears, so nothing here listens to audio.

The mention is the wake word, and it is also what makes this work without the privileged
MESSAGE_CONTENT intent - Discord sends the text of a message the bot is mentioned in whether
or not the intent is granted.
"""

from __future__ import annotations

import re

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred import errors
from alfred import service

loader = lightbulb.Loader()

PLAY = "play "
SKIP = ("skip", "next")

MENTION_RX = re.compile(r"<@!?(\d+)>")


@loader.listener(hikari.GuildMessageCreateEvent)
async def on_mention(
    event: hikari.GuildMessageCreateEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
) -> None:
    """Act on a message that mentions the bot, speaking it unless it reads as a command."""
    if not event.is_human:
        return

    me = bot.get_me()
    if me is None or me.id not in (event.message.user_mentions_ids or ()):
        return

    request = MENTION_RX.sub("", event.content or "").strip()
    if not request:
        return

    # Everything below either joins the author or talks to them, so a mention from outside a
    # voice channel has nowhere to go. Ignored rather than answered: a mention is not a command
    # invocation, and replying to every stray one is noise in a channel people are chatting in.
    if service.voice_channel_of(bot, event.guild_id, event.author_id) is None:
        return

    logger.info("'{}' asked for {!r} on guild {}", event.author.username, request, event.guild_id)

    try:
        await _handle(event, bot, lavalink_client, request)
    except errors.AlfredError as e:
        await event.message.respond(e.message, reply=True, mentions_reply=False)


async def _handle(
    event: hikari.GuildMessageCreateEvent,
    bot: hikari.GatewayBot,
    lavalink_client: lavalink.Client,
    request: str,
) -> None:
    lowered = request.lower()

    if lowered.startswith(PLAY):
        result = await service.resolve(lavalink_client, request[len(PLAY) :].strip())
        embed = await service.enqueue(
            bot,
            lavalink_client,
            result,
            guild_id=event.guild_id,
            requester_id=event.author_id,
        )
        await event.message.respond(embed=embed, reply=True, mentions_reply=False)
        return

    if lowered in SKIP:
        player = service.get_player(lavalink_client, event.guild_id)
        if player is None or not player.is_playing:
            raise errors.PlayerNotPlaying
        skipped = await player.skip()
        await event.message.respond(f"Skipped **{skipped.title}**" if skipped else "Skipped", reply=True)
        return

    await service.speak(
        bot,
        lavalink_client,
        request,
        guild_id=event.guild_id,
        requester_id=event.author_id,
    )
