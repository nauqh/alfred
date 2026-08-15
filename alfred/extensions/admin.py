"""Owner-only commands for looking at the Lavalink nodes.

`/stats` answers "is it healthy right now"; `/info` answers "what is it running". Both
report on every configured node rather than on the first one, because the reason to have
more than one is that they can differ.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import hikari
import lavalink
import lightbulb
from loguru import logger

from alfred.formatting import format_uptime

loader = lightbulb.Loader()

MEGABYTE = 1024 * 1024


@loader.command
class Stats(
    lightbulb.SlashCommand,
    name="stats",
    description="Show the health of the Lavalink nodes",
    hooks=[lightbulb.prefab.owner_only],
):
    @lightbulb.invoke
    async def invoke(
        self,
        ctx: lightbulb.Context,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
    ) -> None:
        nodes = lavalink_client.node_manager.nodes

        if not nodes:
            await _respond(ctx, "Node stats", "No nodes are configured.")
            return

        sections = [_node_stats(node) for node in nodes]
        sections.append(f"**Bot**\nGuilds `{len(bot.cache.get_guilds_view())}`")

        await _respond(ctx, "Node stats", "\n\n".join(sections))


def _node_stats(node: lavalink.Node) -> str:
    """One node, as three lines: what it is, what it is doing, and what it is costing."""
    header = f"**{node.name}** `{node.region}` - {'available' if node.available else 'unavailable'}"
    stats = node.stats

    # `is_fake` means the node has connected but has not sent a stats frame yet. Lavalink
    # sends one a minute, so this is what a healthy node looks like for its first minute -
    # saying so beats reporting a screenful of zeroes as though they were measurements.
    if stats is None or stats.is_fake:
        return f"{header}\nNo stats yet - the node sends them once a minute."

    used_mb = round(stats.memory_used / MEGABYTE)
    allocated_mb = round(stats.memory_allocated / MEGABYTE)
    percent = round(100 * stats.memory_used / stats.memory_allocated) if stats.memory_allocated else 0

    lines = [
        header,
        f"Uptime `{format_uptime(stats.uptime)}` · Players `{stats.players}` ({stats.playing_players} playing)",
        f"Memory `{used_mb}/{allocated_mb} MB` ({percent}%) · "
        f"CPU `{stats.system_load:.0%}` system, `{stats.lavalink_load:.0%}` node",
    ]

    # Frame counters only exist while something is playing; the node omits them otherwise,
    # and lavalink.py reports the absence as zeroes. Showing `0 frames sent` next to
    # `0 playing` invites the reading that playback is broken.
    if stats.playing_players:
        lines.append(f"Frames `{stats.frames_sent}` sent, `{stats.frames_nulled}` null, `{stats.frames_deficit}` short")

    return "\n".join(lines)


@loader.command
class Info(
    lightbulb.SlashCommand,
    name="info",
    description="Show what the Lavalink nodes are running",
    hooks=[lightbulb.prefab.owner_only],
):
    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, lavalink_client: lavalink.Client = lightbulb.di.INJECTED) -> None:
        nodes = lavalink_client.node_manager.nodes

        if not nodes:
            await _respond(ctx, "Node info", "No nodes are configured.")
            return

        sections = []
        for node in nodes:
            try:
                info = await node.get_info()
            except lavalink.LavalinkError as e:
                logger.warning("Failed to fetch info from node {!r}: {}", node.name, e)
                sections.append(f"**{node.name}**\nUnreachable: {e}")
                continue

            sections.append(_node_info(node.name, dict(info)))

        await _respond(ctx, "Node info", "\n\n".join(sections))


def _node_info(name: str, info: dict[str, Any]) -> str:
    """
    One node's `/v4/info`, as text.

    The payload is nested - `version` and `git` are objects, `plugins` a list of them - so
    it is read out field by field. Formatting it generically prints Python dict literals
    and epoch milliseconds at whoever ran the command.
    """
    version = info.get("version") or {}
    git = info.get("git") or {}

    header = f"**{name}** - Lavalink `{version.get('semver', 'unknown')}`"
    commit = git.get("commit")
    if commit:
        header += f" (`{commit}`, built {_date(info.get('buildTime'))})"

    plugins = ", ".join(f"{p.get('name')} `{p.get('version')}`" for p in info.get("plugins") or [])
    sources = ", ".join(info.get("sourceManagers") or [])
    filters = ", ".join(info.get("filters") or [])

    return "\n".join(
        [
            header,
            f"JVM `{info.get('jvm', '?')}` · Lavaplayer `{info.get('lavaplayer', '?')}`",
            f"Plugins: {plugins or 'none'}",
            f"Sources: {sources or 'none'}",
            f"Filters: {filters or 'none - the bot applies none'}",
        ]
    )


def _date(epoch_millis: Any) -> str:
    """A build timestamp as a date. Lavalink reports it in milliseconds since the epoch."""
    if not isinstance(epoch_millis, int):
        return "unknown"

    return dt.datetime.fromtimestamp(epoch_millis / 1000, tz=dt.timezone.utc).strftime("%Y-%m-%d")


async def _respond(ctx: lightbulb.Context, title: str, body: str) -> None:
    """Answer ephemerally, on every path - node health is not for the channel to read."""
    await ctx.respond(embed=hikari.Embed(title=title, description=body), ephemeral=True)
