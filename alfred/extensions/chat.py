"""Replying when someone @mentions the bot.

Loaded only when `OPENROUTER_API_KEY` is set - see `alfred.bot.build`. With no key there is no
listener at all, rather than a listener that wakes on every message and then declines to act.
"""

from __future__ import annotations

import re

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred import errors
from alfred.chat import actions
from alfred.chat.client import ChatClient
from alfred.chat.completions import ChatError
from alfred.chat.completions import ToolCall
from alfred.ui import embeds

loader = lightbulb.Loader()

# `<@123>` is the modern mention; `<@!123>` is the nickname form, which Discord stopped sending
# years ago but which older messages in a channel's history still carry.
MENTION = re.compile(r"<@!?(\d+)>")

EMPTY_MENTION_REPLY = "You rang? Ask me something, or try `/play`."
FAILURE_REPLY = "I could not reach my wits just now - try again in a moment."
RATE_LIMITED_REPLY = "I am being rate limited. Give it a minute."

# One reply per channel at a time. The free tier is rate limited hard enough that queueing
# requests just means answering a question nobody is still waiting for, so extra mentions are
# dropped while one is in flight.
_in_flight: set[hikari.Snowflake] = set()


@loader.listener(hikari.GuildMessageCreateEvent)
async def on_message(
    event: hikari.GuildMessageCreateEvent,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    chat_client: ChatClient = lightbulb.di.INJECTED,
    lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
    client: lightbulb.Client = lightbulb.di.INJECTED,
) -> None:
    """Answer a message that mentions the bot, ignoring everything else in the channel."""
    if not event.is_human:
        return

    me = bot.get_me()
    if me is None or not _mentions(event.message, me.id):
        return

    prompt = _strip_mentions(event.content or "")
    if not prompt:
        await _post(event.message, content=EMPTY_MENTION_REPLY)
        return

    if event.channel_id in _in_flight:
        logger.debug("Ignored a mention in channel {} - already answering one", event.channel_id)
        return

    _in_flight.add(event.channel_id)
    try:
        turns = await _turns(bot, event.message, me.id, prompt)
        logger.info(
            "Answering a mention from '{}' on guild {} in channel {}{}",
            event.author.username,
            event.guild_id,
            event.channel_id,
            f" (following a reply chain of {len(turns)} turns)" if len(turns) > 1 else "",
        )
        logger.debug("Asked: {}", prompt)

        async with bot.rest.trigger_typing(event.channel_id):
            reply = await chat_client.complete(turns, actions.TOOLS)
    except ChatError as e:
        logger.warning("Chat reply failed on guild {}: {}", event.guild_id, e)
        # Failures stay plain text. An embed is the bot's answering voice, and a shrug is not
        # an answer - dressing one up in brand colours only makes it look deliberate.
        content = RATE_LIMITED_REPLY if "429" in str(e) else FAILURE_REPLY
        await _post(event.message, content=content)
        return
    finally:
        _in_flight.discard(event.channel_id)

    if isinstance(reply, ToolCall):
        await _run_action(event, reply, turns, bot, lavalink_client, chat_client, client)
        return

    # Whether this is an embed is the model's call, made by giving the answer a title or fields
    # - see `Reply.is_embed`.
    if reply.is_embed:
        await _post(event.message, embed=embeds.chat_reply(reply, model=chat_client.model))
    else:
        await _post(event.message, content=reply.description)


async def _run_action(
    event: hikari.GuildMessageCreateEvent,
    call: ToolCall,
    turns: list[dict[str, str]],
    bot: hikari.GatewayBot,
    lavalink_client: lavalink.Client,
    chat_client: ChatClient,
    client: lightbulb.Client,
) -> None:
    """
    Run an action the model proposed, and say what happened.

    The model chose the action; who it runs as is not up to the model. The invocation is built
    from the message - the author, their guild, their channel - so a tool call can only ever do
    what the person who sent the message could already have done with a slash command.

    An action that *did* something is confirmed in a sentence rather than with the slash
    command's card: the now playing view arrives on its own when the track starts, so posting
    "Track added" here would say the same thing twice. An action that *shows* something posts
    its embed, because that embed is the answer.
    """
    context = actions.Invocation(
        bot=bot,
        lavalink_client=lavalink_client,
        guild_id=event.guild_id,
        channel_id=event.channel_id,
        user_id=event.author.id,
        client=client,
    )

    try:
        result = await actions.run(call, context)
    except errors.AlfredError as e:
        # Carries a message written to be shown - a failed voice check, or a query that matched
        # nothing. The user asked in chat, so they are answered in chat.
        await _post(event.message, content=e.message)
        return
    except Exception:
        logger.exception("Action {!r} failed on guild {}", call.name, event.guild_id)
        await _post(event.message, content=FAILURE_REPLY)
        return

    if result.embed is not None:
        await _post(event.message, embed=result.embed)
        return

    if result.notice is not None:
        # Posted verbatim, not rephrased by the model: the numbered list is what the user
        # picks from, and the follow-up "play 2" reads it back through the reply chain.
        await _post(event.message, content=result.notice)
        return

    assert result.summary is not None, "an action returns an embed, a notice, or a summary"
    async with bot.rest.trigger_typing(event.channel_id):
        confirmation = await chat_client.confirm(turns, call, result.summary)
    await _post(event.message, content=confirmation)


async def _post(message: hikari.Message, **kwargs: object) -> None:
    """Reply in the channel, without pinging the person for their own question."""
    try:
        await message.respond(reply=True, mentions_reply=False, **kwargs)  # type: ignore[arg-type]
    except hikari.HikariError as e:
        logger.warning("Could not post a chat reply in channel {}: {}", message.channel_id, e)


def _mentions(message: hikari.Message, me_id: hikari.Snowflake) -> bool:
    """
    Whether the message mentions the bot directly.

    Role mentions and `@everyone` are deliberately not counted - the bot would otherwise answer
    every announcement in the server.
    """
    mentioned = message.user_mentions_ids
    return bool(mentioned) and me_id in mentioned


def _strip_mentions(content: str) -> str:
    """Remove the mentions from the text, leaving what was actually asked."""
    return MENTION.sub("", content).strip()


async def _turns(
    bot: hikari.GatewayBot,
    message: hikari.Message,
    me_id: hikari.Snowflake,
    prompt: str,
) -> list[dict[str, str]]:
    """
    Build the conversation to send, following the reply chain back one exchange.

    Context comes from the reply chain alone: mentioning the bot cold is always a fresh
    question, and replying to one of its answers carries that answer - and the question it
    answered - along with the new one. Nothing is stored between messages, so a restart loses
    nothing and one person's conversation never leaks into another's.
    """
    parent = message.referenced_message
    if not isinstance(parent, hikari.Message) or parent.author.id != me_id or not parent.content:
        return [{"role": "user", "content": prompt}]

    turns = [{"role": "assistant", "content": parent.content}, {"role": "user", "content": prompt}]

    # Discord only nests `referenced_message` one level, so the question the bot was answering
    # has to be fetched. It is a nicety - without it the model sees its own answer and the new
    # question, which is usually enough - so a failure here just means less context.
    grandparent = parent.message_reference
    if grandparent is not None and grandparent.id is not None:
        try:
            original = await bot.rest.fetch_message(grandparent.channel_id or message.channel_id, grandparent.id)
        except hikari.HikariError as e:
            logger.debug("Could not fetch the message behind a reply: {}", e)
        else:
            if original.content:
                turns.insert(0, {"role": "user", "content": _strip_mentions(original.content)})

    return turns
