"""Builders for the embeds Alfred posts."""

from __future__ import annotations

import hikari
import lavalink

from alfred import constants
from alfred import sources
from alfred.formatting import player_bar
from alfred.formatting import track_length
from alfred.player import AlfredPlayer
from alfred.player import get_playlist

NOW_PLAYING_TITLE = "Now Playing"


def track_line(track: lavalink.AudioTrack, *, credit_author: bool = True) -> str:
    """One line describing a track: its linked title, and its length."""
    line = f"[{track.title}]({track.uri}) `{track_length(track)}`"
    if credit_author and track.source_name in sources.CREDITED_SOURCE_NAMES:
        line += f" • {track.author}"
    return line


def track_summary(track: lavalink.AudioTrack) -> str:
    """The multi-line summary used when a track is queued."""
    return f"[{track.title}]({track.uri})\n{track.author} `{track_length(track)}`\n\n<@!{track.requester}>"


def now_playing(player: AlfredPlayer | None) -> hikari.Embed:
    """The embed behind the now playing view: the current track and its progress."""
    current = player.current if player is not None else None
    if current is None:
        return hikari.Embed(
            title=NOW_PLAYING_TITLE,
            description="Nothing is playing.",
            color=constants.COLOR_ALFRED,
        )

    assert player is not None
    embed = hikari.Embed(
        title=NOW_PLAYING_TITLE,
        description=_current_description(player),
        color=constants.COLOR_ALFRED,
    )
    if current.artwork_url:
        embed.set_thumbnail(current.artwork_url)
    return embed


def queue(player: AlfredPlayer, *, title: str, preview_length: int = 0) -> hikari.Embed:
    """
    The embed behind ``/queue``: the current track, then a numbered list of what follows.

    Args:
        player: The player to describe.
        title: The embed title.
        preview_length: How many queued tracks to list.
    """
    current = player.current
    if current is None:
        return hikari.Embed(
            title=title,
            description="Nothing is playing.",
            color=constants.COLOR_ALFRED,
        )

    lines: list[str] = [
        "**Now Playing:**",
        f"[{current.title}]({current.uri}) `{track_length(current)}`"
        + (f" • {current.author}" if current.author else ""),
    ]

    upcoming = list(player.queue[: max(preview_length, 0)])
    if upcoming:
        lines.append("\n**Up next:**")
        for i, track in enumerate(upcoming, start=1):
            lines.append(f"`{i}.` " + track_line(track))

    total_count = len(player.queue) + 1
    lines.append(f"\n-# Total: {total_count} track{'s' if total_count != 1 else ''}")

    return hikari.Embed(
        title=title,
        description="\n".join(lines),
        color=constants.COLOR_ALFRED,
    ).set_thumbnail(current.artwork_url)


def _current_description(player: AlfredPlayer) -> str:
    """The block describing the current track: title, author, progress, playlist and requester."""
    current = player.current
    assert current is not None

    author_line = f"by **{current.author}**" if current.author else ""
    bar = player_bar(player)

    subtext_parts: list[str] = [f"👤 <@{current.requester}>"]
    playlist = get_playlist(current)
    if playlist is not None:
        subtext_parts.append(f"📑 [{playlist.name}]({playlist.url or '#'})")

    subtext = "-# " + " • ".join(subtext_parts)

    lines = [
        f"### [{current.title}]({current.uri})",
        author_line,
        "",
        bar,
        "",
        subtext,
    ]
    return "\n".join(line for line in lines if line is not None and line != "")
