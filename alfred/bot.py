"""Wiring: the hikari bot, the lightbulb client, and the Lavalink client they share."""

from __future__ import annotations

import asyncio
import datetime as dt
import importlib.metadata as _metadata
import subprocess
from pathlib import Path

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred import constants
from alfred import errors
from alfred import log_config
from alfred.chat.client import ChatClient
from alfred.config import Config
from alfred.events import LavalinkEventHandler
from alfred.extensions import CHAT_EXTENSION
from alfred.extensions import EXTENSIONS
from alfred.music import node as music_node
from alfred.music.player import AlfredPlayer
from alfred.ui import embeds
from alfred.ui import responses
from alfred.ui.nowplaying import NowPlayingManager

# GUILD_MESSAGES is what lets `alfred.extensions.chat` see an @mention. MESSAGE_CONTENT is
# deliberately absent and not needed: it is privileged, and Discord exempts messages that
# mention the bot from it - their content arrives populated regardless. The bot is therefore
# blind to the text of every message that is not addressed to it, which is the intent.
INTENTS = hikari.Intents.GUILDS | hikari.Intents.GUILD_VOICE_STATES | hikari.Intents.GUILD_MESSAGES


def _in_git_repo() -> bool:
    """Whether the working tree is a git checkout at all."""
    return (Path(__file__).resolve().parent.parent / ".git").exists()


def _git_commit() -> str | None:
    """The current commit's short hash, or `None` when it cannot be read."""
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as e:
        logger.warning("Could not read the git commit for the startup view: {}", e)
        return None
    return out.stdout.strip() or None


# The embed every meaningful restart posts. The working tree may be a git checkout (dev, VPS)
# but is not obliged to be one - the image runs from a Docker build context that dockerignore
# strips of .git, so the commit line is optional.
_ROBOT_COMMIT_SHA = _git_commit() if _in_git_repo() else None

# Fire-and-forget startup tasks, kept referenced so the event loop does not collect them.
_background_tasks: set[asyncio.Task[None]] = set()


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
    chat_client = ChatClient(config.chat) if config.chat is not None else None

    @client.error_handler
    async def on_error(exc: lightbulb.exceptions.ExecutionPipelineFailedException) -> bool:
        return await handle_command_error(exc)

    @bot.listen(hikari.StartedEvent)
    async def on_started(_: hikari.StartedEvent) -> None:
        nonlocal lavalink_client

        me = bot.get_me()
        assert me is not None, "the bot must know its own user before Lavalink can be set up"

        await bot.update_presence(
            activity=hikari.Activity(
                name=constants.ACTIVITY_NAME,
                type=hikari.ActivityType.LISTENING,
            ),
        )

        lavalink_client = build_lavalink_client(config, me.id)
        lavalink_client.add_event_hooks(LavalinkEventHandler(NowPlayingManager(bot, client, lavalink_client)))

        # Registered before the first command runs, which is the last moment the DI registry
        # is still open for writes.
        client.di.registry_for(lightbulb.di.Contexts.DEFAULT).register_value(lavalink.Client, lavalink_client)
        client.di.registry_for(lightbulb.di.Contexts.DEFAULT).register_value(Config, config)

        await _post_startup_view(bot, config, lavalink_client)

        extensions = EXTENSIONS
        if chat_client is not None:
            await chat_client.start()
            client.di.registry_for(lightbulb.di.Contexts.DEFAULT).register_value(ChatClient, chat_client)
            extensions += CHAT_EXTENSION
            logger.info("Chat replies enabled, answering with {!r}", chat_client.model)

        await client.load_extensions(*extensions)
        await client.start()

    @bot.listen(hikari.StoppingEvent)
    async def on_stopping(_: hikari.StoppingEvent) -> None:
        if lavalink_client is not None:
            await lavalink_client.close()
            logger.info("Closed the Lavalink client")

        if chat_client is not None:
            await chat_client.close()

    return bot


async def _post_startup_view(
    bot: hikari.GatewayBot,
    config: Config,
    lavalink_client: lavalink.Client,
) -> None:
    """
    Post the restart embed to the configured channel, if one is configured.

    The post is deliberately not awaited beyond a best-effort send: the node may still be
    booting when the bot comes up, so its versions load in behind the first embed, and a
    channel that vanished between config and post must not take the bot down.
    """
    if config.startup_channel_id is None:
        return

    started = dt.datetime.now(dt.timezone.utc)
    info = embeds.StartupInfo(
        bot_version=_bot_version(),
        lavalink_version=music_node.node_semver(lavalink_client),
        plugins=music_node.node_plugins(lavalink_client),
        commit=_ROBOT_COMMIT_SHA,
        commit_date=_commit_date(),
        started=started,
    )
    embed = embeds.startup_embed(info)

    try:
        await bot.rest.create_message(config.startup_channel_id, embed=embed)
    except hikari.HikariError as e:
        logger.warning(
            "Failed to post the startup view to channel {}: {}",
            config.startup_channel_id,
            e,
        )
        return

    logger.info("Posted the startup view to channel {}", config.startup_channel_id)
    # Fire-and-forget, matching `alfred.ui.responses`' pattern: keep a reference so the
    # event loop does not collect the task mid-request, and drop it when it finishes.
    task = asyncio.create_task(music_node.refresh_node_info(lavalink_client))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def _bot_version() -> str:
    """The installed package version, read from the metadata, not a constant."""
    try:
        return _metadata.version("alfred")
    except _metadata.PackageNotFoundError:
        return "unknown"


def _commit_date() -> str | None:
    """The current commit's author date, or `None` when it cannot be read."""
    if _ROBOT_COMMIT_SHA is None:
        return None
    try:
        out = subprocess.run(
            ["git", "show", "-s", "--format=%cs", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


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
