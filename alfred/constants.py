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
EMOJI_PREV_PAGE: Final = "⬅️"
EMOJI_NEXT_PAGE: Final = "➡️"

# The symbols the progress bar draws with - a filled/empty block pill (cyber deck style).
PROGRESS_BAR_FILLED: Final = "▰"
PROGRESS_BAR_EMPTY: Final = "▱"

# The bot's avatar on the landing page, used as the footer icon on embeds.
CHANGELOG_FOOTER_ICON: Final = "https://nauqh.github.io/alfred/alfred_avatar.jpg"

EMOJI_RESUME_PLAYER: Final = "▶️"
EMOJI_PAUSE_PLAYER: Final = "⏸️"

ACTIVITY_NAME: Final = "https://nauqh.github.io/alfred/"

# The queue panel. Both `/queue` and the same view reached by asking Alfred in chat render
# through these, so the two cannot drift into showing different amounts of the same queue.
QUEUE_TITLE: Final = "Queue"
QUEUE_PAGE_SIZE: Final = 10

# How long the queue panel's paging buttons stay live without a press. Unlike the now playing
# view - which lives exactly as long as its track - this panel has no natural end, so it gets
# a timeout and gives its buttons back when it expires.
QUEUE_PANEL_TIMEOUT: Final = 180.0
