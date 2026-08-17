"""Talking to Alfred by mentioning him, including from a voice channel's own chat.

Discord's voice channels carry an ordinary text chat, and its messages arrive through the
normal message event. That makes ``@Alfred play something`` the closest thing to speaking to
the bot that is actually available: Lavalink holds the guild's one voice connection and does
not hand back what it hears, so nothing here listens to audio.

The mention is the wake word, and it is also what makes this work without the privileged
MESSAGE_CONTENT intent - Discord sends the text of a message the bot is mentioned in whether
or not the intent is granted. That exemption is documented for a mention of the app itself;
whether it extends to a mention of a role the app holds is not, so `on_mention` treats an
unreadable message as a role mention and says how to get through instead of going quiet.
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

# Matches a user mention (`<@1>`, `<@!1>`) and a role one (`<@&1>`) alike - both are stripped
# out of the request, so neither is left to be read aloud.
MENTION_RX = re.compile(r"<@[!&]?(\d+)>")

TAG_ME_DIRECTLY = (
    "I can see you tagged me, but not what you said - pick me from the list rather than my role, "
    "and Discord will pass the message along."
)


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
    if me is None or not await _mentions_me(bot, event, me):
        return

    # Everything below either joins the author or talks to them, so a mention from outside a
    # voice channel has nowhere to go. Ignored rather than answered: a mention is not a command
    # invocation, and replying to every stray one is noise in a channel people are chatting in.
    if service.voice_channel_of(bot, event.guild_id, event.author_id) is None:
        logger.debug("Ignoring mention from '{}': not in a voice channel", event.author.username)
        return

    raw = event.content
    request = MENTION_RX.sub("", raw or "").strip()

    if not request:
        # A bare `@Alfred` leaves the mention itself behind in `content`, so an empty *raw*
        # body means the text was withheld rather than never written. Discord blanks `content`
        # for apps without the MESSAGE_CONTENT intent and exempts messages that mention the
        # app - but it has never said whether a mention of a *role* the app holds counts, and
        # its own answer to the question is to ask support. Rather than bet on it, the case is
        # detected and answered with the one form of tag that is documented to work.
        if not raw:
            logger.info("Tagged on guild {} without a readable message - answering with the hint", event.guild_id)
            await event.message.respond(TAG_ME_DIRECTLY, reply=True, mentions_reply=False)
        return

    logger.info("'{}' asked for {!r} on guild {}", event.author.username, request, event.guild_id)

    try:
        await _handle(event, bot, lavalink_client, request)
    except errors.AlfredError as e:
        await event.message.respond(e.message, reply=True, mentions_reply=False)
    except Exception:
        # A listener that raises is a listener that fails silently: hikari logs the traceback
        # and the channel sees nothing, which is indistinguishable from the bot ignoring you.
        logger.exception("Failed to handle {!r} on guild {}", request, event.guild_id)
        await event.message.respond("Something went wrong handling that.", reply=True, mentions_reply=False)


#: Roles the bot holds, per guild, for when the member cache cannot answer - see `_my_role_ids`.
_role_ids: dict[int, frozenset[int]] = {}


async def _my_role_ids(bot: hikari.GatewayBot, guild_id: int, me: hikari.OwnUser) -> frozenset[int]:
    """
    The roles the bot holds in a guild, empty if they cannot be established.

    The cache is asked first and is normally enough. It is not relied on: the bot runs without
    the members intent, and a member cache that turns out not to hold even the bot's own member
    would put this listener straight back to ignoring role mentions - which is the bug it is
    here to fix. So a miss falls back to the API, and the answer is kept, making this at worst
    one request per guild for the life of the process.
    """
    member = bot.cache.get_member(guild_id, me.id)
    if member is not None:
        return frozenset(member.role_ids)

    remembered = _role_ids.get(guild_id)
    if remembered is not None:
        return remembered

    try:
        fetched = await bot.rest.fetch_my_member(guild_id)
    except hikari.HikariError as e:
        # Not fatal, and not worth a reply: a direct mention still works.
        logger.warning("Could not fetch my roles on guild {}, so role mentions will not register: {}", guild_id, e)
        return frozenset()

    _role_ids[guild_id] = roles = frozenset(fetched.role_ids)
    logger.debug("Fetched my roles on guild {}: {}", guild_id, sorted(roles))
    return roles


async def _mentions_me(bot: hikari.GatewayBot, event: hikari.GuildMessageCreateEvent, me: hikari.OwnUser) -> bool:
    """
    Whether a message tags the bot - as a user, or through a role the bot holds.

    Both count because Discord's mention picker starts offering the bot's managed role once
    the bot has been tagged once, so the second tag is often a role mention that looks
    identical in the channel and arrives in an entirely different field.

    `@everyone` and `@here` deliberately do not count. They tag the bot by any reasonable
    reading, and answering them would mean speaking over every announcement in the server.
    """
    message = event.message

    if me.id in (message.user_mentions_ids or ()):
        return True

    mentioned_roles = message.role_mention_ids or ()
    if not mentioned_roles:
        return False

    mine = await _my_role_ids(bot, event.guild_id, me)
    return any(role_id in mentioned_roles for role_id in mine)


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
