"""The work behind the commands: connecting to voice, resolving queries and filling the queue."""

from __future__ import annotations

import dataclasses
import random
import re
from typing import Any

import hikari
import lavalink
from loguru import logger

from alfred import errors
from alfred.music import sources
from alfred.music.player import AlfredPlayer
from alfred.music.player import PlaylistRef
from alfred.music.player import set_playlist

URL_RX = re.compile(r"https?://(?:www\.)?.+")

RICH_PLAYLIST_TYPES = ("artist", "album", "playlist")


@dataclasses.dataclass(frozen=True, slots=True)
class Queued:
    """
    What a call to `enqueue` put in the queue.

    Returned instead of a rendered embed so that `alfred.music` owes nothing to `alfred.ui`.
    Two callers render the same value differently: the slash commands turn it into the "Track
    added" card, and the chat path describes it in a sentence. Neither reading belongs in here.
    """

    requester_id: int
    tracks: tuple[lavalink.AudioTrack, ...]
    playlist: PlaylistRef | None = None
    result_type: str = "track"
    """One of ``track``, ``playlist``, ``album`` or ``artist`` - how the source described it."""
    artwork_url: str | None = None
    author: str | None = None

    @property
    def is_playlist(self) -> bool:
        return self.playlist is not None

    @property
    def track(self) -> lavalink.AudioTrack:
        """The single track that was added. Only meaningful when `is_playlist` is false."""
        return self.tracks[0]

    @property
    def count(self) -> int:
        return len(self.tracks)


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


async def enqueue(
    bot: hikari.GatewayBot,
    lavalink_client: lavalink.Client,
    result: lavalink.LoadResult,
    *,
    guild_id: int,
    requester_id: hikari.Snowflakeish,
    channel_id: int | None = None,
    query: str | None = None,
    play_next: bool = False,
    loop: bool = False,
    shuffle: bool = True,
) -> Queued:
    """
    Add a load result to the guild's queue, connecting to voice first if needed.

    Args:
        result: What `resolve` returned.
        guild_id: The guild to queue into.
        requester_id: The member who asked for the tracks.
        channel_id: The channel the command ran in - where the now playing view is posted.
        query: The original query, used as the playlist link when the result has no richer one.
        play_next: Queue a single track at the front instead of the back.
        loop: Turn on track looping (single result) or queue looping (playlist).
        shuffle: Shuffle a playlist's tracks as they are queued.

    Returns:
        What was added, for the caller to render however it likes.

    Raises:
        NoResults: If the result holds no tracks.
        NotInVoice: If the bot has to connect, and the requester is not in a voice channel.
    """
    if not result.tracks:
        raise errors.NoResults

    player = get_player(lavalink_client, guild_id)
    if player is None or not player.is_connected:
        player, _ = await join(bot, lavalink_client, guild_id, requester_id)

    if channel_id is not None:
        player.text_channel_id = channel_id

    if result.load_type is lavalink.LoadType.PLAYLIST:
        queued = _add_playlist(player, result, requester_id=requester_id, query=query, shuffle=shuffle)
        if loop:
            player.set_loop(player.LOOP_QUEUE)
    else:
        queued = _add_track(player, result.tracks[0], requester_id=requester_id, play_next=play_next)
        if loop:
            player.set_loop(player.LOOP_SINGLE)

    if not player.is_playing:
        await player.play()

    return queued


def _add_track(
    player: AlfredPlayer,
    track: lavalink.AudioTrack,
    *,
    requester_id: hikari.Snowflakeish,
    play_next: bool,
) -> Queued:
    player.add(track=track, requester=int(requester_id), index=0 if play_next else None)

    return Queued(
        requester_id=int(requester_id),
        tracks=(track,),
        artwork_url=track.artwork_url,
        author=track.author or None,
    )


def _add_playlist(
    player: AlfredPlayer,
    result: lavalink.LoadResult,
    *,
    requester_id: hikari.Snowflakeish,
    query: str | None,
    shuffle: bool,
) -> Queued:
    plugin_info: dict[str, Any] = result.plugin_info or {}
    result_type = plugin_info.get("type") if plugin_info.get("type") in RICH_PLAYLIST_TYPES else "playlist"

    name = result.playlist_info.name or plugin_info.get("author") or "Unknown"
    url = plugin_info.get("url") or (query if query and URL_RX.match(query) else None)
    playlist = PlaylistRef(name=name, url=url)

    tracks = list(result.tracks)
    queued = tuple(tracks)

    # Shuffling as tracks are queued keeps the shuffle stable, rather than re-rolling every skip.
    while tracks:
        track = tracks.pop(random.randrange(len(tracks)) if shuffle else 0)
        set_playlist(track, playlist)
        player.add(track=track, requester=int(requester_id))

    return Queued(
        requester_id=int(requester_id),
        tracks=queued,
        playlist=playlist,
        result_type=result_type,
        artwork_url=plugin_info.get("artworkUrl"),
        author=plugin_info.get("author"),
    )
