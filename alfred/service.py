"""The work behind the commands: connecting to voice, resolving queries and filling the queue."""

from __future__ import annotations

import random
import re
from typing import Any
from urllib.parse import quote

import hikari
import lavalink
from loguru import logger

from alfred import embeds
from alfred import errors
from alfred import sources
from alfred.player import SPEECH_SOURCE
from alfred.player import AlfredPlayer
from alfred.player import PlaylistRef
from alfred.player import set_playlist

URL_RX = re.compile(r"https?://(?:www\.)?.+")

RICH_PLAYLIST_TYPES = ("artist", "album", "playlist")

# LavaSrc's Flowery TTS source. Enabled under `plugins.lavasrc.sources` in application.yml,
# where the voice is set too - nothing about the voice is decided here.
TTS_PREFIX = "ftts://"

# Flowery reads far more than this, but a slash command is not the place to paste an essay,
# and the whole line arrives as one URL.
MAX_SPEECH_LENGTH = 300

# Flowery's output sits well below a normalised music track, so speech at the player's usual
# volume is hard to make out. Lavalink accepts up to 1000, but much past 150 is clipping
# rather than loudness.
SPEECH_VOLUME = 150


def get_player(lavalink_client: lavalink.Client, guild_id: int) -> AlfredPlayer | None:
    """Return the guild's player, if one exists."""
    player = lavalink_client.player_manager.get(guild_id)
    assert player is None or isinstance(player, AlfredPlayer)
    return player


def voice_channel_of(bot: hikari.GatewayBot, guild_id: int, user_id: hikari.Snowflakeish) -> int | None:
    """Return the ID of the voice channel a member is in, or `None` if they are not in one."""
    state = bot.cache.get_voice_state(guild_id, user_id)
    return int(state.channel_id) if state is not None and state.channel_id is not None else None


async def join(
    bot: hikari.GatewayBot,
    lavalink_client: lavalink.Client,
    guild_id: int,
    user_id: hikari.Snowflakeish,
) -> tuple[AlfredPlayer, int]:
    """
    Connect to the voice channel a member is in, creating the guild's player.

    Returns:
        The guild's player, and the ID of the channel joined.

    Raises:
        NotInVoice: If the member is not in a voice channel.
        NoNodesAvailable: If no Lavalink node can host the player.
    """
    channel_id = voice_channel_of(bot, guild_id, user_id)
    if channel_id is None:
        raise errors.NotInVoice

    try:
        player = lavalink_client.player_manager.create(guild_id=guild_id)
    except lavalink.LavalinkError as e:
        logger.error("Failed to create player on guild {}: {}", guild_id, e)
        raise errors.NoNodesAvailable from e

    assert isinstance(player, AlfredPlayer)

    await bot.update_voice_state(guild_id, channel_id, self_deaf=True)
    logger.info("Connected to voice channel {} on guild {}", channel_id, guild_id)

    return player, channel_id


async def resolve(
    lavalink_client: lavalink.Client,
    query: str,
    source: sources.Source = sources.YOUTUBE,
) -> lavalink.LoadResult:
    """
    Look a query up on Lavalink. Bare queries are searched on ``source``; URLs are loaded as-is.

    Raises:
        NoResults: If the query could not be looked up, or matched nothing.
    """
    query = query.strip().strip("<>")
    if not query:
        raise errors.NoResults

    if not URL_RX.match(query):
        query = source.query(query)

    return await _load(lavalink_client, query)


async def _load(lavalink_client: lavalink.Client, identifier: str) -> lavalink.LoadResult:
    """
    Ask the node to load an identifier, exactly as given.

    Raises:
        NoResults: If the node could not be reached, refused the identifier, or matched nothing.
    """
    try:
        result = await lavalink_client.get_tracks(identifier)
    except lavalink.LavalinkError as e:
        logger.error("Track lookup failed for {!r}: {}", identifier, e)
        raise errors.NoResults("Could not reach the audio server - try again in a moment.") from e

    if result.load_type is lavalink.LoadType.ERROR:
        message = result.error.message if result.error is not None else "unknown error"
        logger.warning("Lavalink failed to load {!r}: {}", identifier, message)
        raise errors.NoResults(f"Could not load that query: {message}")

    if result.load_type is lavalink.LoadType.EMPTY or not result.tracks:
        raise errors.NoResults

    return result


async def speak(
    bot: hikari.GatewayBot,
    lavalink_client: lavalink.Client,
    text: str,
    *,
    guild_id: int,
    requester_id: hikari.Snowflakeish,
) -> lavalink.AudioTrack:
    """
    Say something out loud in the guild's voice channel.

    The speech is a track like any other - LavaSrc's Flowery source turns `ftts://` into audio,
    and the node plays it down the same connection the music uses.

    Raises:
        NoResults: If there is nothing to say, or the node could not render it.
        SpeechTooLong: If the text is longer than Flowery will read in one go.
        AlreadyPlaying: If a track is loaded. One player per guild, and Lavalink cannot mix
            two streams, so speaking now would cut the music off mid-bar.
        NotInVoice: If the bot has to connect, and the requester is not in a voice channel.
    """
    # Collapse the whitespace before measuring: a line pasted out of a lyrics page is mostly
    # newlines, and the length limit should apply to what is actually read out.
    text = " ".join(text.split())
    if not text:
        raise errors.NoResults("There is nothing there to say.")
    if len(text) > MAX_SPEECH_LENGTH:
        raise errors.SpeechTooLong

    player = get_player(lavalink_client, guild_id)
    if player is None or not player.is_connected:
        player, _ = await join(bot, lavalink_client, guild_id, requester_id)

    # Refuse to speak over *music*, not over a previous spoken line. Flowery tracks carry no
    # known duration, so the node treats them as unbounded and `current` can stay set long
    # after the audio has finished - gating on `is_playing` left the first line blocking every
    # line after it, permanently. Replacing one spoken line with the next is what was wanted
    # anyway.
    current = player.current
    if current is not None and current.source_name != SPEECH_SOURCE:
        raise errors.AlreadyPlaying

    result = await _load(lavalink_client, f"{TTS_PREFIX}{quote(text)}")
    track = result.tracks[0]

    # `play(track)` rather than `add` then `play`: speech is not queue material, and playing it
    # directly leaves whatever is queued untouched to resume afterwards. The volume rides along
    # on the same call, so there is no window where the line has started but is still quiet -
    # `alfred.events` puts it back when the line ends.
    player.volume_before_speech = player.volume
    await player.play(track, volume=SPEECH_VOLUME)

    return track


async def enqueue(
    bot: hikari.GatewayBot,
    lavalink_client: lavalink.Client,
    result: lavalink.LoadResult,
    *,
    guild_id: int,
    requester_id: hikari.Snowflakeish,
    query: str | None = None,
    play_next: bool = False,
    loop: bool = False,
    shuffle: bool = True,
) -> hikari.Embed:
    """
    Add a load result to the guild's queue, connecting to voice first if needed.

    Args:
        result: What `resolve` returned.
        guild_id: The guild to queue into.
        requester_id: The member who asked for the tracks.
        query: The original query, used as the playlist link when the result has no richer one.
        play_next: Queue a single track at the front instead of the back.
        loop: Turn on track looping (single result) or queue looping (playlist).
        shuffle: Shuffle a playlist's tracks as they are queued.

    Returns:
        An embed describing what was added.

    Raises:
        NoResults: If the result holds no tracks.
        NotInVoice: If the bot has to connect, and the requester is not in a voice channel.
    """
    if not result.tracks:
        raise errors.NoResults

    player = get_player(lavalink_client, guild_id)
    if player is None or not player.is_connected:
        player, _ = await join(bot, lavalink_client, guild_id, requester_id)

    if result.load_type is lavalink.LoadType.PLAYLIST:
        embed = _add_playlist(player, result, requester_id=requester_id, query=query, shuffle=shuffle)
        if loop:
            player.set_loop(player.LOOP_QUEUE)
    else:
        embed = _add_track(player, result.tracks[0], requester_id=requester_id, play_next=play_next)
        if loop:
            player.set_loop(player.LOOP_SINGLE)

    if not player.is_playing:
        await player.play()

    return embed


def _add_track(
    player: AlfredPlayer,
    track: lavalink.AudioTrack,
    *,
    requester_id: hikari.Snowflakeish,
    play_next: bool,
) -> hikari.Embed:
    player.add(track=track, requester=int(requester_id), index=0 if play_next else None)

    return hikari.Embed(
        title="Track added",
        description=embeds.track_summary(track),
    ).set_thumbnail(track.artwork_url)


def _add_playlist(
    player: AlfredPlayer,
    result: lavalink.LoadResult,
    *,
    requester_id: hikari.Snowflakeish,
    query: str | None,
    shuffle: bool,
) -> hikari.Embed:
    plugin_info: dict[str, Any] = result.plugin_info or {}
    result_type = plugin_info.get("type") if plugin_info.get("type") in RICH_PLAYLIST_TYPES else "playlist"

    name = result.playlist_info.name or plugin_info.get("author") or "Unknown"
    url = plugin_info.get("url") or (query if query and URL_RX.match(query) else None)
    artwork_url = plugin_info.get("artworkUrl")
    author = plugin_info.get("author")

    tracks = list(result.tracks)
    count = len(tracks)
    playlist = PlaylistRef(name=name, url=url)

    # Shuffling as tracks are queued keeps the shuffle stable, rather than re-rolling every skip.
    while tracks:
        track = tracks.pop(random.randrange(len(tracks)) if shuffle else 0)
        set_playlist(track, playlist)
        player.add(track=track, requester=int(requester_id))

    if result_type == "artist":
        description = f"[{(author or name).upper()}]({url or '#'}) - `{count} tracks`\n\n<@{requester_id}>"
    elif author:
        description = f"[{name}]({url or '#'}) `{count} track(s)`\n{author}\n\n<@{requester_id}>"
    else:
        description = f"Playlist [{name}]({url or '#'}) - {count} tracks\n\n<@{requester_id}>"

    return hikari.Embed(title=f"{result_type.capitalize()} added", description=description).set_thumbnail(artwork_url)
