"""Builders for the embeds Alfred posts."""

from __future__ import annotations

import dataclasses

import hikari
import lavalink

from alfred import constants
from alfred.music import sources
from alfred.music.player import AlfredPlayer
from alfred.music.player import get_playlist
from alfred.music.service import Queued
from alfred.ui.formatting import player_bar
from alfred.ui.formatting import track_length

NOW_PLAYING_TITLE = "Now Playing"

# Discord's limits on what a message may carry. They live here because they are facts about
# Discord rather than about any model, and `alfred.chat.completions` clamps model output
# against them - a small model asked for structure will cheerfully write a 3000 character
# field value. Discord rejects the whole message if any one limit is exceeded, and enforces
# the total separately from the per-part limits.
#
# An ordinary message gets less room than an embed description, which is why a plain answer is
# clamped harder than the same text would be inside an embed.
MAX_EMBED_TOTAL = 6000
MAX_MESSAGE = 2000
MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_FIELDS = 25
MAX_FIELD_NAME = 256
MAX_FIELD_VALUE = 1024


@dataclasses.dataclass(frozen=True, slots=True)
class Field:
    """One name/value row of an embed."""

    name: str
    value: str
    inline: bool = False


@dataclasses.dataclass(frozen=True, slots=True)
class Reply:
    """A model answer, and how it should be posted."""

    description: str
    title: str | None = None
    fields: tuple[Field, ...] = ()

    @property
    def is_embed(self) -> bool:
        """
        Whether this answer earns an embed.

        Structure is the signal: the model opts in by giving the answer a title or fields, and
        a bare description is posted as an ordinary message. Nothing asks the model for a
        separate "use an embed" flag, because that is one more thing for a weak model to get
        wrong - and an answer with a title and rows is exactly the answer an embed suits.
        """
        return self.title is not None or bool(self.fields)


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
    name, url = added.playlist.name, added.playlist.url or "#"
    mention = f"<@{added.requester_id}>"

    if added.result_type == "artist":
        description = f"[{(added.author or name).upper()}]({url}) - `{added.count} tracks`\n\n{mention}"
    elif added.author:
        description = f"[{name}]({url}) `{added.count} track(s)`\n{added.author}\n\n{mention}"
    else:
        description = f"Playlist [{name}]({url}) - {added.count} tracks\n\n{mention}"

    return hikari.Embed(
        title=f"{added.result_type.capitalize()} added",
        description=description,
        color=constants.COLOR_ALFRED,
    ).set_thumbnail(added.artwork_url)


def chat_reply(reply: Reply, *, model: str) -> hikari.Embed:
    """
    The embed behind a reply to an @mention.

    Args:
        reply: The parsed model answer.
        model: The OpenRouter model id, shown in the footer so it is obvious which one spoke -
            the free ones vary a lot, and swapping `OPENROUTER_MODEL` is the first thing to try
            when the answers are poor.
    """
    embed = hikari.Embed(
        title=reply.title,
        description=reply.description,
        color=constants.COLOR_ALFRED,
    )

    budget = MAX_EMBED_TOTAL - len(reply.description) - len(reply.title or "") - len(model)
    for field in reply.fields:
        # Discord rejects the whole message when the parts together exceed the total, so fields
        # past the budget are dropped rather than allowed to lose the answer with them.
        cost = len(field.name) + len(field.value)
        if cost > budget:
            break
        budget -= cost
        embed.add_field(name=field.name, value=field.value, inline=field.inline)

    return embed.set_footer(model)


def _current_description(player: AlfredPlayer) -> str:
    """The block describing the current track: title, author, progress, playlist and requester."""
    current = player.current
    assert current is not None

    author_line = f"by **{current.author}**" if current.author else ""
    bar = player_bar(player)

    subtext_parts: list[str] = [f"Requested: <@{current.requester}>"]
    playlist = get_playlist(current)
    if playlist is not None:
        subtext_parts.append(f"|| Playing [{playlist.name}]({playlist.url or '#'})")

    subtext = "-# " + " • ".join(subtext_parts)

    lines = [
        f"### [{current.title}]({current.uri})",
        author_line,
        bar,
        subtext,
    ]
    return "\n".join(line for line in lines if line is not None)
