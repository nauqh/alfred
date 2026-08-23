"""Command extensions, loaded by `alfred.bot`."""

from __future__ import annotations

from typing import Final

EXTENSIONS: Final = (
    "alfred.extensions.general",
    "alfred.extensions.play",
    "alfred.extensions.queue",
    "alfred.extensions.admin",
)

CHAT_EXTENSION: Final = ("alfred.extensions.chat",)
"""Loaded on top of `EXTENSIONS` only when `OPENROUTER_API_KEY` is set - see `alfred.bot.build`."""
