"""Builders for the embeds Alfred posts."""

from __future__ import annotations

import math
from datetime import datetime
from datetime import timezone

import hikari
import lavalink

from alfred import constants
from alfred.music import sources
from alfred.music.player import AlfredPlayer
from alfred.music.player import get_playlist
from alfred.music.service import Queued
from alfred.ui.formatting import format_time
from alfred.ui.formatting import player_bar
from alfred.ui.formatting import track_length
from alfred.ui.formatting import trim

NOW_PLAYING_TITLE = "Now Playing"
TRACK_TITLE_LIMIT = 180
QUEUE_TRACK_TITLE_LIMIT = 80
TRACK_AUTHOR_LIMIT = 80
QUEUE_TITLE_LIMIT = 72


def _source_label(track: lavalink.AudioTrack) -> str:
    """Give the source a short, human-readable label for metadata rows."""
    return {
        "youtube": "YouTube",
        "spotify": "Spotify",
        "deezer": "Deezer",
        "soundcloud": "SoundCloud",
        "http": "Direct link",
    }.get(track.source_name, track.source_name.capitalize() or "Audio")


def track_line(track: lavalink.AudioTrack) -> str:
    """One compact queue line: linked title, length, artist and requester."""
    title = trim(track.title, QUEUE_TRACK_TITLE_LIMIT)
    line = f"[{title}]({track.uri}) `{track_length(track)}`"
    if track.source_name in sources.CREDITED_SOURCE_NAMES and track.author:
        line += f" • {trim(track.author, TRACK_AUTHOR_LIMIT)}"
    if track.requester is not None:
        line += f" · <@{track.requester}>"
    return line


def track_summary(track: lavalink.AudioTrack) -> str:
    """The multi-line summary used when a track is queued."""
    title = trim(track.title, TRACK_TITLE_LIMIT)
    author = trim(track.author, TRACK_AUTHOR_LIMIT) if track.author else "Unknown artist"
    requester = f"<@!{track.requester}>" if track.requester is not None else "Requested by nobody"
    return f"[{title}]({track.uri})\n{author} · {_source_label(track)} `{track_length(track)}`\n\n{requester}"


def now_playing(player: AlfredPlayer | None) -> hikari.Embed:
    """The embed behind the now playing view: the current track and its progress."""
    current = player.current if player is not None else None
    if current is None:
        return hikari.Embed(
            title=NOW_PLAYING_TITLE,
            description="Nothing is playing.\n\nTry `/play` or `/search` to start some music.",
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


def queue_pages(track_count: int, page_size: int) -> int:
    """
    How many pages ``track_count`` queued tracks fill, at ``page_size`` per page.

    Never less than one: a queue with nothing waiting still has a page, the one showing the
    track that is playing. Defined here rather than in the menu because it has to agree with
    how `queue` slices - a Next button that offers a page the embed renders empty is worse
    than no button.
    """
    if page_size <= 0:
        return 1
    return max(1, math.ceil(track_count / page_size))


def queue(
    player: AlfredPlayer | None,
    *,
    title: str,
    page_size: int = 0,
    page: int = 0,
    snapshot: bool = False,
) -> hikari.Embed:
    """
    The embed behind ``/queue``: the current track, then a numbered list of what follows.

    Args:
        player: The player to describe, or `None` if the guild no longer has one - which an
            open panel can outlive, exactly as `now_playing` can.
        title: The embed title.
        page_size: How many queued tracks to list at once.
        page: Which page of the queue to list, counted from zero. Out of range values are
            clamped rather than rejected - the queue moves on while a panel is open, and a
            page that was real when the button was drawn may not be by the time it is pressed.
        snapshot: Mark the result as a static panel after its paging controls expire.
    """
    current = player.current if player is not None else None
    if current is None or player is None:
        return hikari.Embed(
            title=title,
            description="Nothing is playing.\n\nTry `/play` or `/search` to start some music.",
            color=constants.COLOR_ALFRED,
        )

    lines: list[str] = [
        "**Now Playing:**",
        f"[{trim(current.title, TRACK_TITLE_LIMIT)}]({current.uri}) `{track_length(current)}`"
        + (f" • {trim(current.author, TRACK_AUTHOR_LIMIT)}" if current.author else "")
        + f" · {_source_label(current)}",
    ]

    size = max(page_size, 0)
    pages = queue_pages(len(player.queue), size)
    page = min(max(page, 0), pages - 1)
    start = page * size

    upcoming = list(player.queue[start : start + size]) if size else []
    if upcoming:
        lines.append("\n**Up next:**")
        for i, track in enumerate(upcoming, start=start + 1):
            lines.append(f"`{i}.` " + track_line(track))

    total_count = len(player.queue) + 1
    footer = f"\n-# Total: {total_count} track{'s' if total_count != 1 else ''}"
    all_tracks = [current, *player.queue]
    if all(not track.is_stream and track.duration > 0 for track in all_tracks):
        footer += f" · {format_time(sum(track.duration for track in all_tracks))}"
    if pages > 1:
        footer += f" • Page {page + 1}/{pages}"
    if snapshot:
        updated = int(datetime.now(timezone.utc).timestamp())
        footer += f" · Snapshot · updated <t:{updated}:R>"
    lines.append(footer)

    return hikari.Embed(
        title=title,
        description="\n".join(lines),
        color=constants.COLOR_ALFRED,
    ).set_thumbnail(current.artwork_url)


def queued(added: Queued) -> hikari.Embed:
    """
    The card posted when tracks are added to the queue.

    Moved here from `music.service`, which used to build it and return it. Rendering a value
    the music layer produces is this module's job; producing Discord embeds was never the
    music layer's.
    """
    if not added.is_playlist:
        return hikari.Embed(
            title="Track added",
            description=track_summary(added.track),
            color=constants.COLOR_ALFRED,
        ).set_thumbnail(added.artwork_url)

    assert added.playlist is not None
    name, url = trim(added.playlist.name, QUEUE_TITLE_LIMIT), added.playlist.url or "#"
    author = trim(added.author, TRACK_AUTHOR_LIMIT) if added.author else None
    mention = f"<@{added.requester_id}>"

    if added.result_type == "artist":
        description = f"[{(author or name).upper()}]({url}) - `{added.count} tracks`\n\n{mention}"
    elif author:
        description = f"[{name}]({url}) `{added.count} track(s)`\n{author}\n\n{mention}"
    else:
        description = f"Playlist [{name}]({url}) - {added.count} tracks\n\n{mention}"

    return hikari.Embed(
        title=f"{added.result_type.capitalize()} added",
        description=description,
        color=constants.COLOR_ALFRED,
    ).set_thumbnail(added.artwork_url)


def _current_description(player: AlfredPlayer) -> str:
    """The block describing the current track: title, author, progress, playlist and requester."""
    current = player.current
    assert current is not None

    author_line = f"by **{trim(current.author, TRACK_AUTHOR_LIMIT)}**" if current.author else ""
    bar = player_bar(player)

    subtext_parts: list[str] = [f"Requested: <@{current.requester}>", _source_label(current)]
    playlist = get_playlist(current)
    if playlist is not None:
        playlist_name = trim(playlist.name, QUEUE_TITLE_LIMIT)
        subtext_parts.append(f"|| Playing [{playlist_name}]({playlist.url or '#'})")

    subtext = "-# " + " • ".join(subtext_parts)

    lines = [
        f"### [{trim(current.title, TRACK_TITLE_LIMIT)}]({current.uri})",
        author_line,
        bar,
        subtext,
    ]
    return "\n".join(line for line in lines if line is not None)
