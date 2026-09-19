"""Replying to commands.

Lightbulb v3 has no ``delete_after`` on responses, so the self-cleaning replies that Alfred
uses for player feedback are scheduled here instead.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import hikari
import lightbulb

logger = logging.getLogger(__name__)

_delete_after = 60.0
_pending: set[asyncio.Task[None]] = set()


def configure(delete_after: float) -> None:
    """Set how long self-deleting replies stick around for."""
    global _delete_after
    _delete_after = delete_after


async def respond(ctx: lightbulb.Context, **kwargs: Any) -> None:
    """Reply to a command, and delete the reply after the configured delay."""
    response_id = await ctx.respond(**kwargs)

    if _delete_after <= 0:
        return

    task = asyncio.create_task(_delete_later(ctx, response_id, _delete_after))
    # Tasks are only weakly referenced by the event loop, so hold on until they finish.
    _pending.add(task)
    task.add_done_callback(_pending.discard)


async def _delete_later(ctx: lightbulb.Context, response_id: hikari.Snowflakeish, delay: float) -> None:
    await asyncio.sleep(delay)
    try:
        await ctx.delete_response(response_id)
    except (hikari.NotFoundError, hikari.ForbiddenError):
        pass
    except hikari.HikariError as e:
        logger.debug("Failed to clean up response %s: %s", response_id, e)
