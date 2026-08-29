"""The weekly recap task: when it runs, and what it posts.

Sunday morning, in the configured timezone, the bot posts the week that was: top tracks,
total count, listening time, top listener. A recap is for the moment - if the bot was down
on Sunday, the post is skipped and the next Sunday rolls around; there is no catch-up.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any

from loguru import logger

from alfred.config import RecapConfig
from alfred.storage import PlayStore
from alfred.storage import retention_cutoff
from alfred.ui import embeds

# How long to wait for the schedule math, which needs tzdata - present in the slim image?
# If zoneinfo cannot be built, the task fails softly rather than taking the bot down.
TZ_FALLBACK = timezone.utc


def next_sunday(now: datetime, hour: int, tz: str) -> datetime:
    """
    The next Sunday at `hour` in timezone `tz`, strictly after `now`.

    Sunday is weekday() == 6. Days until the next Sunday is (6 - weekday) % 7, with 0 meaning
    "today" - but a Sunday at or before `hour` has already passed, so that case rolls a week.
    """
    try:
        from zoneinfo import ZoneInfo

        zone = ZoneInfo(tz)
    except Exception:
        zone = TZ_FALLBACK

    local = now.astimezone(zone)
    days = (6 - local.weekday()) % 7
    candidate = local.replace(hour=hour, minute=0, second=0, microsecond=0) + timedelta(days=days)
    if candidate <= local:
        candidate += timedelta(days=7)
    return candidate


async def run_weekly_recap(
    store: PlayStore,
    bot: Any,
    config: RecapConfig,
) -> None:
    """
    Sleep until the next Sunday at `config.hour` in `config.timezone`, then post the recap.

    Restart-safe: the sleep is computed from *now* each time the bot boots, so a restart never
    double-posts. Pruning happens right after each post, so the file never grows forever.
    """
    while True:
        now = datetime.now(timezone.utc)
        target = next_sunday(now, config.hour, config.timezone)
        logger.info("Weekly recap scheduled for {}", target.isoformat())

        try:
            await asyncio.sleep(max(0.0, (target - now).total_seconds()))
        except asyncio.CancelledError:
            logger.info("Weekly recap task cancelled")
            return

        await post_recap(store, bot, config)


async def post_recap(store: PlayStore, bot: Any, config: RecapConfig) -> None:
    """Post the week's recap to the configured channel, then prune old plays."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=7)
    plays = store.weekly(config.guild_id, since)

    embed = embeds.recap_embed(plays, since=since, now=now)
    try:
        await bot.rest.create_message(config.channel_id, embed=embed)
        logger.info("Posted the weekly recap to channel {}", config.channel_id)
    except Exception as e:
        logger.warning("Failed to post the weekly recap: {}", e)

    pruned = store.prune(retention_cutoff(now))
    if pruned:
        logger.info("Pruned {} old play rows", pruned)