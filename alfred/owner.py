"""Who owns the bot - resolved once, and shared by every check that needs the answer.

The claim follows `lightbulb.prefab.owner_only`: the application's owner alone, plus any
members of the team that owns it. The ids are cached on the client, so the application is
fetched at most once per run - every caller reads the same answer.
"""

from __future__ import annotations

import hikari
import lightbulb


async def is_owner(client: lightbulb.Client, user_id: hikari.Snowflakeish) -> bool:
    """Whether `user_id` owns the bot's application."""
    if client._owner_ids is None:
        app = await client._ensure_application()
        owner_ids: set[hikari.Snowflakeish] = {app.owner.id}
        if app.team is not None:
            owner_ids.update(app.team.members.keys())
        client._owner_ids = owner_ids
    return user_id in client._owner_ids
