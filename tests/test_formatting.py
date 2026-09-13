from __future__ import annotations

import pytest

from alfred.ui.formatting import PROGRESS_BAR_WIDTH
from alfred.ui.formatting import format_time
from alfred.ui.formatting import format_uptime
from alfred.ui.formatting import parse_time
from alfred.ui.formatting import player_bar
from alfred.ui.formatting import progress_bar
from alfred.ui.formatting import progress_line
from alfred.ui.formatting import trim
from tests.conftest import confirm_playback
from tests.conftest import make_track
from tests.conftest import set_position


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
    from alfred.constants import PROGRESS_BAR_EMPTY
    from alfred.constants import PROGRESS_BAR_FILLED

    assert progress_bar(0.0) == PROGRESS_BAR_EMPTY * PROGRESS_BAR_WIDTH
    assert progress_bar(1.0) == PROGRESS_BAR_FILLED * PROGRESS_BAR_WIDTH
    bar = progress_bar(0.5)
    assert bar.count(PROGRESS_BAR_FILLED) == PROGRESS_BAR_WIDTH // 2
    assert bar.count(PROGRESS_BAR_EMPTY) == PROGRESS_BAR_WIDTH - PROGRESS_BAR_WIDTH // 2


@pytest.mark.parametrize("fraction", [-1.0, 0.0, 0.5, 1.0, 2.0])
def test_progress_bar_stays_in_bounds(fraction: float) -> None:
    from alfred.constants import PROGRESS_BAR_EMPTY
    from alfred.constants import PROGRESS_BAR_FILLED

    bar = progress_bar(fraction)

    assert bar.count(PROGRESS_BAR_FILLED) + bar.count(PROGRESS_BAR_EMPTY) == PROGRESS_BAR_WIDTH


def test_progress_line_has_a_fixed_width_and_clamped_playhead() -> None:
    assert len(progress_line(-1.0)) == 18
    assert progress_line(0.0).startswith("●")
    assert progress_line(0.5).count("●") == 1
    assert progress_line(2.0).endswith("●")


def test_player_bar_uses_timestamps_and_a_clamped_playhead(player) -> None:
    player.add(track=make_track("Song"), requester=1)
    player._next = player.queue.pop(0)
    confirm_playback(player)
    set_position(player, 60_000)

    bar = player_bar(player)

    assert bar.startswith("⏸️ 1:00 ")
    assert "●" in bar
    assert bar.endswith(" 3:20")
    assert "[" not in bar


def test_trim_only_shortens_what_is_too_long() -> None:
    assert trim("short", 10) == "short"
    assert trim("a very long title indeed", 10) == "a very ..."
    assert len(trim("a very long title indeed", 10)) == 10
