"""Wiring: the hikari bot, the lightbulb client, and the Lavalink client they share."""

from __future__ import annotations

from pathlib import Path

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred import changelog
from alfred import errors
from alfred import log_config
from alfred.config import Config
from alfred.events import LavalinkEventHandler
from alfred.extensions import EXTENSIONS
from alfred.music.player import AlfredPlayer
from alfred.presence import Presence
from alfred.ui import embeds
from alfred.ui import responses
from alfred.ui.nowplaying import NowPlayingManager

# Two intents, neither privileged. The bot needs to know what guilds it is in and who is in
# which voice channel; it reads no message content at all, and has no listener that would.
INTENTS = hikari.Intents.GUILDS | hikari.Intents.GUILD_VOICE_STATES


@lightbulb.hook(lightbulb.ExecutionSteps.PRE_INVOKE)
def log_invocation(_: lightbulb.ExecutionPipeline, ctx: lightbulb.Context) -> None:
    """Record every command that makes it past its checks."""
    logger.info(
        "'/{}' invoked by '{}' on guild {}",
        ctx.command_data.qualified_name,
        ctx.user.username,
        ctx.guild_id,
    )


def build(config: Config) -> hikari.GatewayBot:
    """
    Build the bot, and everything hanging off it.

    The Lavalink client can only be created once Discord has told us the bot's own user ID,
    so the rest of the setup happens when the bot reports that it has started.
    """
    # `suppress_optimization_warning` because the choice is deliberate rather than an
    # oversight: the Dockerfile runs `python -O`, and a local run is *meant* to keep its
    # asserts - they narrow types and check this module's own wiring, so development is
    # exactly where they earn their keep.
    bot = hikari.GatewayBot(
        config.token,
        intents=INTENTS,
        banner=None,
        logs=None,
        suppress_optimization_warning=True,
    )
    client = lightbulb.client_from_app(bot, default_enabled_guilds=config.default_guilds, hooks=[log_invocation])

    responses.configure(config.delete_after)
    lavalink_client: lavalink.Client | None = None

    @client.error_handler
    async def on_error(exc: lightbulb.exceptions.ExecutionPipelineFailedException) -> bool:
        return await handle_command_error(exc)

    @bot.listen(hikari.StartedEvent)
    async def on_started(_: hikari.StartedEvent) -> None:
        nonlocal lavalink_client

        me = bot.get_me()
        assert me is not None, "the bot must know its own user before Lavalink can be set up"

        presence = Presence(bot)
        await presence.start()

        lavalink_client = build_lavalink_client(config, me.id)

        lavalink_client.add_event_hooks(LavalinkEventHandler(NowPlayingManager(bot, client, lavalink_client), presence))

        # Registered before the first command runs, which is the last moment the DI registry
        # is still open for writes.
        client.di.registry_for(lightbulb.di.Contexts.DEFAULT).register_value(lavalink.Client, lavalink_client)
        client.di.registry_for(lightbulb.di.Contexts.DEFAULT).register_value(Config, config)

        await _post_changelog(bot, config)

        await client.load_extensions(*EXTENSIONS)
        await client.start()

    @bot.listen(hikari.StoppingEvent)
    async def on_stopping(_: hikari.StoppingEvent) -> None:
        if lavalink_client is not None:
            await lavalink_client.close()
            logger.info("Closed the Lavalink client")

    return bot


async def _post_changelog(bot: hikari.GatewayBot, config: Config) -> None:
    """
    Post the newest change log to the configured channel, if one is configured.

    The post replaces the old restart embed: instead of a card of versions, the channel gets
    the day's change log as an embed - each section is a row on the card, so a deploy tells
    people what actually changed in prose they can read. A missing folder, an unreadable log,
    or a channel that vanished between config and post are all best-effort failures: they are
    logged, and never take the bot down.
    """
    if config.startup_channel_id is None:
        return

    root = Path(__file__).resolve().parent.parent
    log_path = changelog.newest_change_log_path(root)
    if not log_path.is_file():
        logger.info("No {} to post on startup", log_path)
        return

    try:
        content = log_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("Could not read the change log {}: {}", log_path, e)
        return

    entry = changelog.newest_entry(content)
    if entry is None:
        logger.info("No entry to post in {}", log_path)
        return

    for embed in embeds.changelog_embeds(entry):
        try:
            await bot.rest.create_message(config.startup_channel_id, embed=embed)
        except hikari.HikariError as e:
            logger.warning("Failed to post the change log to channel {}: {}", config.startup_channel_id, e)
            return

    logger.info("Posted the newest change log entry {} to channel {}", entry.version, config.startup_channel_id)


def build_lavalink_client(config: Config, user_id: hikari.Snowflake) -> lavalink.Client:
    """Create the Lavalink client and connect it to every configured node."""
    lavalink_client: lavalink.Client = lavalink.Client(user_id=int(user_id), player=AlfredPlayer)

    for node in config.nodes:
        lavalink_client.add_node(
            host=node.host,
            port=node.port,
            password=node.password,
            region=node.region,
            name=node.name,
            ssl=node.ssl,
        )
        logger.info("Registered Lavalink node {!r} at {}:{}", node.name, node.host, node.port)

    return lavalink_client


async def handle_command_error(exc: lightbulb.exceptions.ExecutionPipelineFailedException) -> bool:
    """
    Turn a failed command into an ephemeral reply.

    Returns:
        Whether the failure was handled. Unhandled failures are re-raised by lightbulb and
        end up in the logs.
    """
    context = exc.context
    causes = exc.causes or ([exc.__cause__] if isinstance(exc.__cause__, Exception) else [])
    cause = causes[0] if causes else None

    expected = next((c for c in causes if isinstance(c, errors.AlfredError)), None)
    if expected is not None:
        await _reply(context, expected.message)
        return True

    if any(isinstance(c, lightbulb.prefab.NotOwner) for c in causes):
        await _reply(context, "That command is only for the bot's owner.")
        return True

    logger.opt(exception=cause).error(
        "Command {!r} failed on guild {}",
        context.command_data.qualified_name,
        context.guild_id,
    )
    await _reply(context, "Something went wrong running that command.")
    return True


async def _reply(context: lightbulb.Context, message: str) -> None:
    try:
        await context.respond(message, ephemeral=True)
    except hikari.HikariError as e:
        logger.warning("Failed to report a command error to the user: {}", e)


def run() -> None:
    """Load the configuration and run the bot until it is stopped."""
    # python-dotenv is a hard dependency, so this import cannot fail. `load_dotenv` is a
    # no-op when there is no `.env` to read, which is the case in the Docker image.
    from dotenv import load_dotenv

    load_dotenv()

    config = Config.from_env()
    log_config.configure(config.log_level, config.log_dir)

    build(config).run()
