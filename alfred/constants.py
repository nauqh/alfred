"""Static values shared across the bot."""

from __future__ import annotations

from typing import Final

import hikari

# Alfred brand accent colors (from landing/ :root { --accent: #3a7582; --highlight: #bce5ec; })
COLOR_ALFRED: Final = hikari.Color(0x3A7582)
COLOR_ALFRED_SOFT: Final = hikari.Color(0xBCE5EC)

# Media Control Emojis (Discord Twemoji vector icons)
EMOJI_PAUSE: Final = "⏸️"
EMOJI_RESUME: Final = "▶️"
EMOJI_SKIP: Final = "⏭️"
EMOJI_LOOP: Final = "🔁"
EMOJI_LOOP_SINGLE: Final = "🔂"
EMOJI_LINK: Final = "🔗"

# The symbols the progress bar draws with - a filled/empty block pill (cyber deck style).
PROGRESS_BAR_FILLED: Final = "▰"
PROGRESS_BAR_EMPTY: Final = "▱"

EMOJI_RESUME_PLAYER: Final = "▶️"
EMOJI_PAUSE_PLAYER: Final = "⏸️"

ACTIVITY_NAME: Final = "https://nauqh.github.io/alfred/"
