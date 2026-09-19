"""The audio sources Alfred can search.

Which of these actually resolve depends on the plugins enabled on the Lavalink node - see
``lavalink/application.yml.example``.
"""

from __future__ import annotations

import dataclasses
from typing import Final


@dataclasses.dataclass(frozen=True, slots=True)
class Source:
    """A search source, and the prefix Lavalink expects for it."""

    display_name: str
    search_prefix: str
    source_name: str

    def query(self, query: str) -> str:
        """Build a Lavalink search query for this source."""
        return f"{self.search_prefix}:{query}"


YOUTUBE: Final = Source("YouTube", "ytsearch", "youtube")
DEEZER: Final = Source("Deezer", "dzsearch", "deezer")
SPOTIFY: Final = Source("Spotify", "spsearch", "spotify")

SEARCHABLE: Final = (SPOTIFY, DEEZER, YOUTUBE)
"""Sources offered by the ``source`` option of ``/search``."""

BY_DISPLAY_NAME: Final = {source.display_name: source for source in SEARCHABLE}

LAVASEARCH_SOURCES: Final = frozenset({SPOTIFY, DEEZER})
"""Sources that the LavaSearch plugin can return rich (artist/album/playlist) results for."""

CREDITED_SOURCE_NAMES: Final = frozenset({DEEZER.source_name, SPOTIFY.source_name})
"""Sources whose track author is worth showing - YouTube's "author" is just the uploader."""
