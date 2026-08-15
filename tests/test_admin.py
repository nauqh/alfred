"""What `/stats` and `/info` render, given what a node actually reports."""

from __future__ import annotations

from typing import Any

import lavalink
import pytest

from alfred.extensions.admin import _date
from alfred.extensions.admin import _node_info
from alfred.extensions.admin import _node_stats

# Trimmed from a live Lavalink 4.2.2, which is the point: the payload is nested, and
# formatting it generically prints dict literals and epoch milliseconds at the operator.
INFO: dict[str, Any] = {
    "version": {"semver": "4.2.2", "major": 4, "minor": 2, "patch": 2},
    "buildTime": 1772839456827,
    "git": {"branch": "HEAD", "commit": "e8503fd", "commitTime": 1772839275000},
    "jvm": "18.0.2.1",
    "lavaplayer": "2.2.6",
    "sourceManagers": ["soundcloud", "spotify", "youtube", "http"],
    "filters": [],
    "plugins": [{"name": "youtube-plugin", "version": "1.18.2"}],
}

STATS: dict[str, Any] = {
    "frameStats": None,
    "players": 2,
    "playingPlayers": 0,
    "uptime": 440_000,
    "memory": {"free": 61_172_864, "used": 62_559_104, "allocated": 123_731_968, "reservable": 2_147_483_648},
    "cpu": {"cores": 8, "systemLoad": 0.04, "lavalinkLoad": 0.0},
}


class FakeNode:
    def __init__(self, stats: dict[str, Any] | None, *, available: bool = True) -> None:
        self.name = "default-node"
        self.region = "eu"
        self.available = available
        self.stats = lavalink.Stats(self, stats) if stats is not None else lavalink.Stats.empty(self)


def test_stats_report_the_numbers_an_operator_reads() -> None:
    body = _node_stats(FakeNode(STATS))  # type: ignore[arg-type]

    assert "**default-node** `eu` - available" in body
    assert "Uptime `7m 20s`" in body
    assert "Players `2` (0 playing)" in body
    assert "Memory `60/118 MB` (51%)" in body
    assert "`4%` system" in body


def test_frame_counters_are_left_out_when_nothing_is_playing() -> None:
    # The node omits frameStats entirely; lavalink.py reports the absence as zeroes, and
    # `0 frames sent` next to `0 playing` reads as a fault rather than as an idle node.
    assert "Frames" not in _node_stats(FakeNode(STATS))  # type: ignore[arg-type]


def test_frame_counters_appear_once_something_is_playing() -> None:
    playing = {**STATS, "playingPlayers": 1, "frameStats": {"sent": 3000, "nulled": 0, "deficit": -3}}

    assert "Frames `3000` sent" in _node_stats(FakeNode(playing))  # type: ignore[arg-type]


def test_a_node_that_has_not_reported_yet_says_so() -> None:
    # `Stats.empty` is what a node carries between connecting and its first frame, a minute
    # later. Its zeroes are placeholders, not measurements.
    body = _node_stats(FakeNode(None))  # type: ignore[arg-type]

    assert "No stats yet" in body
    assert "Memory" not in body


def test_an_unavailable_node_is_named_as_one() -> None:
    assert "unavailable" in _node_stats(FakeNode(STATS, available=False))  # type: ignore[arg-type]


def test_info_is_read_out_field_by_field() -> None:
    body = _node_info("default-node", INFO)

    assert "Lavalink `4.2.2`" in body
    assert "(`e8503fd`, built 2026-03-06)" in body
    assert "youtube-plugin `1.18.2`" in body
    assert "Sources: soundcloud, spotify, youtube, http" in body
    # Nothing rendered as a Python literal.
    assert "{" not in body and "[" not in body


def test_info_survives_a_node_that_reports_less() -> None:
    # Fields have come and gone across Lavalink versions, and an owner-only command that
    # raises KeyError tells the operator nothing about the node they asked about.
    body = _node_info("default-node", {})

    assert "Lavalink `unknown`" in body
    assert "Plugins: none" in body


@pytest.mark.parametrize("value", [None, "1772839456827", 0.5])
def test_a_build_time_that_is_not_a_timestamp_is_not_guessed_at(value: Any) -> None:
    assert _date(value) == "unknown"


def test_a_build_time_is_shown_as_a_date() -> None:
    assert _date(1772839456827) == "2026-03-06"
