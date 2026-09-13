"""Helpers that turn player state into the strings shown in embeds."""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Literal

from alfred.constants import EMOJI_PAUSE_PLAYER
from alfred.constants import EMOJI_RESUME_PLAYER
from alfred.constants import PROGRESS_BAR_EMPTY
from alfred.constants import PROGRESS_BAR_FILLED

if TYPE_CHECKING:
    import lavalink

PROGRESS_BAR_WIDTH = 10
PROGRESS_LINE_WIDTH = 18
PROGRESS_CURSOR = "●"
PROGRESS_LINE_FILLED = "━"
PROGRESS_LINE_EMPTY = "─"


def parse_time(milliseconds: int) -> tuple[int, int, int, int]:
    """Split a duration in milliseconds into whole days, hours, minutes and seconds."""
    seconds = int(milliseconds) // 1000
    days, remainder = divmod(seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    return days, hours, minutes, seconds


def format_time(milliseconds: int, unit: Literal["d", "h", "m"] | None = None) -> str:
    """
    Format a duration, using the largest unit that the duration actually needs.

    Args:
        milliseconds: The duration to format.
        unit: Force the largest unit to use, instead of picking it from the duration.
    """
    days, hours, minutes, seconds = parse_time(milliseconds)

    if days and unit in ("d", None):
        return f"{days}:{hours:02}:{minutes:02}:{seconds:02}"
    if (hours or days) and unit in ("d", "h", None):
        return f"{days * 24 + hours}:{minutes:02}:{seconds:02}"
    return f"{(days * 24 + hours) * 60 + minutes}:{seconds:02}"


def format_uptime(milliseconds: int) -> str:
    """
    Format how long something has been running, in the two largest units it needs.

    Deliberately not `format_time`: `0:05:54` reads as a track length, and an uptime is
    read at a glance rather than compared to a second one.
    """
    days, hours, minutes, seconds = parse_time(milliseconds)

    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def progress_bar(fraction: float) -> str:
    """Render a filled/empty block pill, with ``fraction`` of the blocks filled (cyber deck style)."""
    filled = min(max(round(fraction * PROGRESS_BAR_WIDTH), 0), PROGRESS_BAR_WIDTH)
    return PROGRESS_BAR_FILLED * filled + PROGRESS_BAR_EMPTY * (PROGRESS_BAR_WIDTH - filled)


def progress_line(fraction: float) -> str:
    """Render a compact timestamp-friendly progress line with a visible playhead."""
    fraction = min(max(fraction, 0.0), 1.0)
    cursor = round(fraction * (PROGRESS_LINE_WIDTH - 1))
    return (
        PROGRESS_LINE_FILLED * cursor
        + PROGRESS_CURSOR
        + PROGRESS_LINE_EMPTY * (PROGRESS_LINE_WIDTH - cursor - 1)
    )


def player_bar(player: lavalink.DefaultPlayer) -> str:
    """Render timestamps and a playhead that is easy to scan on desktop and mobile."""
    current = player.current
    if current is None:
        return ""

    play_pause = EMOJI_RESUME_PLAYER if player.paused else EMOJI_PAUSE_PLAYER

    if current.is_stream or not current.duration:
        return f"{play_pause} LIVE"

    position = min(max(player.position, 0), current.duration)
    current_time = format_time(position)
    total_time = format_time(current.duration)
    fraction = position / current.duration
    return f"{play_pause} {current_time} {progress_line(fraction)} {total_time}"


def track_length(track: lavalink.AudioTrack) -> str:
    """Format a track's length, or ``LIVE`` for streams."""
    return "LIVE" if track.is_stream else format_time(track.duration)


def trim(text: str, max_len: int) -> str:
    """Shorten ``text`` to ``max_len`` characters, ending with an ellipsis if it was cut."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."
