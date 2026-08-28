"""Talking to the node for status, apart from playback.

Two jobs: the startup view answers in `/stats` style - Lavalink semver and plugin versions -
and a startup post must never hang the bot on a node that is still booting. Both read the
same `/v4/info` payload, so they wrap it once, with a cache and a fallback for when the node
is simply not ready yet.
"""

from __future__ import annotations

import asyncio
from typing import Any

import lavalink
from loguru import logger

# How long a cached answer is trusted. `/v4/info` is stable for the life of a node, so a
# run reads it at most once a minute.
CACHE_SECONDS = 60.0

_cache: dict[str, dict[str, Any]] = {}
# Only one in-flight request at a time; a burst of "what are the versions" calls should not
# fan out to the node.
_last_fetch: asyncio.Task[None] | None = None


def node_semver(client: lavalink.Client) -> str:
    """The Lavalink semver of the first live node, or ``unknown``."""
    info = _best_info(client)
    return str(info.get("version", {}).get("semver", "unknown"))


def node_plugins(client: lavalink.Client) -> str:
    """The node's plugins, as ``name version`` joined - ``none`` when the node is quiet."""
    info = _best_info(client)
    names = [f"{p.get('name')} {p.get('version')}" for p in info.get("plugins") or [] if p.get("name")]
    return ", ".join(names) or "none"


def _best_info(client: lavalink.Client) -> dict[str, Any]:
    """The newest cached info we have, or the first node's, or nothing."""
    if _cache:
        _, info = max(_cache.items(), key=lambda item: item[1].get("_fetched", 0.0))
        return info
    return _empty_info(client)


def _empty_info(client: lavalink.Client) -> dict[str, Any]:
    for node in client.nodes:
        if node.available:
            return {"version": {}, "plugins": [], "_fetched": 0.0}
    return {"version": {}, "plugins": [], "_fetched": 0.0}


async def refresh_node_info(client: lavalink.Client) -> None:
    """
    Fetch and cache every node's `/v4/info`, guarded against overlap.

    Launched from the startup post and never awaited there: the bot starts posting its
    startup view immediately, and the first loader that comes back fills the cache in.
    Failures are logged, not raised - a node still booting is expected, not an error.
    """
    global _last_fetch
    if _last_fetch is not None and not _last_fetch.done():
        return

    async def _fetch_all() -> None:
        for node in client.nodes:
            try:
                info = await node.get_info()
            except lavalink.LavalinkError as e:
                logger.warning("Failed to fetch info from node {!r}: {}", node.name, e)
                continue
            _cache[node.name] = dict(info) | {"_fetched": asyncio.get_event_loop().time()}

    task = asyncio.create_task(_fetch_all())

    # Keep the in-flight task from being garbage collected mid-request.
    _last_fetch = task

    try:
        await task
    except Exception as e:
        logger.error("Node info refresh failed: {}", e)
