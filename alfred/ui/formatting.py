"""Helpers that turn player state into the strings shown in embeds."""

from __future__ import annotations

from typing import TYPE_CHECKING

from alfred.constants import EMOJI_PAUSE
from alfred.constants import EMOJI_RESUME

if TYPE_CHECKING:
    import lavalink

PROGRESS_LINE_WIDTH = 18
PROGRESS_CURSOR = "●"
PROGRESS_LINE_FILLED = "━"
PROGRESS_LINE_EMPTY = "─"


def format_time(milliseconds: int) -> str:
    """Format a duration, using the largest unit that the duration actually needs."""
    seconds = int(milliseconds) // 1000
    hours, remainder = divmod(seconds, 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours:
        return f"{hours}:{minutes:02}:{seconds:02}"
    return f"{minutes}:{seconds:02}"


def progress_line(fraction: float) -> str:
    """Render a compact timestamp-friendly progress line with a visible playhead."""
    fraction = min(max(fraction, 0.0), 1.0)
    cursor = round(fraction * (PROGRESS_LINE_WIDTH - 1))
    return PROGRESS_LINE_FILLED * cursor + PROGRESS_CURSOR + PROGRESS_LINE_EMPTY * (PROGRESS_LINE_WIDTH - cursor - 1)


def player_bar(player: lavalink.DefaultPlayer) -> str:
    """Render timestamps and a playhead that is easy to scan on desktop and mobile."""
    current = player.current
    if current is None:
        return ""

    play_pause = EMOJI_RESUME if player.paused else EMOJI_PAUSE

    if current.is_stream or not current.duration:
        return f"{play_pause} LIVE"

    position = min(max(player.position, 0), current.duration)
    fraction = position / current.duration
    return f"{play_pause} {format_time(position)} {progress_line(fraction)} {format_time(current.duration)}"


def track_length(track: lavalink.AudioTrack) -> str:
    """Format a track's length, or ``LIVE`` for streams."""
    return "LIVE" if track.is_stream else format_time(track.duration)


def trim(text: str, max_len: int) -> str:
    """Shorten ``text`` to ``max_len`` characters, ending with an ellipsis if it was cut."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
