from __future__ import annotations

import pytest

from alfred.formatting import PROGRESS_BAR_WIDTH
from alfred.formatting import UNKNOWN_DURATION
from alfred.formatting import format_time
from alfred.formatting import format_uptime
from alfred.formatting import parse_time
from alfred.formatting import player_bar
from alfred.formatting import progress_bar
from alfred.formatting import track_length
from alfred.formatting import trim
from alfred.player import AlfredPlayer
from tests.conftest import make_track


@pytest.mark.parametrize(
    ("milliseconds", "expected"),
    [
        (0, "0:00"),
        (1_500, "0:01"),
        (61_000, "1:01"),
        (3_600_000, "1:00:00"),
        (3_661_000, "1:01:01"),
        (90_000_000, "1:01:00:00"),
    ],
)
def test_format_time_picks_the_units_the_duration_needs(milliseconds: int, expected: str) -> None:
    assert format_time(milliseconds) == expected


def test_format_time_can_be_held_to_one_unit() -> None:
    assert format_time(90_000_000, "h") == "25:00:00"
    assert format_time(3_661_000, "m") == "61:01"


@pytest.mark.parametrize(
    ("milliseconds", "expected"),
    [
        (0, "0s"),
        (45_000, "45s"),
        (440_000, "7m 20s"),
        (3_661_000, "1h 1m"),
        (183_600_000, "2d 3h"),
    ],
)
def test_format_uptime_keeps_the_two_largest_units(milliseconds: int, expected: str) -> None:
    assert format_uptime(milliseconds) == expected


def test_parse_time_splits_a_duration() -> None:
    assert parse_time(90_061_000) == (1, 1, 1, 1)


def test_progress_bar_marks_where_playback_is() -> None:
    from alfred.constants import EMOJI_RADIO_BUTTON

    assert progress_bar(0.0).startswith(EMOJI_RADIO_BUTTON)
    assert progress_bar(1.0).endswith(EMOJI_RADIO_BUTTON)
    assert progress_bar(0.5).startswith("▬" * (PROGRESS_BAR_WIDTH // 2) + EMOJI_RADIO_BUTTON)


@pytest.mark.parametrize("fraction", [-1.0, 0.0, 0.5, 1.0, 2.0])
def test_progress_bar_stays_in_bounds(fraction: float) -> None:
    bar = progress_bar(fraction)

    assert bar.count("▬") == PROGRESS_BAR_WIDTH - 1


def test_a_track_of_unknown_length_says_so_rather_than_guessing() -> None:
    # Flowery TTS tracks arrive with Lavaplayer's unknown-duration sentinel, which formatted
    # as a real duration reads as 106751991167300 days.
    speech = make_track("Very good, sir.", duration=UNKNOWN_DURATION)

    assert track_length(speech) == "--:--"


def test_a_track_of_unknown_length_gets_the_live_progress_bar(player: AlfredPlayer) -> None:
    # Otherwise `position / duration` is a rounding error away from zero and the marker never
    # moves, which reads as a stuck player.
    player.current = make_track("Very good, sir.", duration=UNKNOWN_DURATION)

    assert "LIVE" in player_bar(player)


def test_trim_only_shortens_what_is_too_long() -> None:
    assert trim("short", 10) == "short"
    assert trim("a very long title indeed", 10) == "a very ..."
    assert len(trim("a very long title indeed", 10)) == 10
