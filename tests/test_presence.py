"""The bot's presence: default activity, per-track override, and the 128-char activity cap."""

from __future__ import annotations

import hikari
import pytest

from alfred import constants
from alfred.presence import ACTIVITY_NAME_LIMIT
from alfred.presence import Presence
from tests.conftest import make_track


class FakeBot:
    """Captures the activities it was asked to show."""

    def __init__(self) -> None:
        self.activities: list[hikari.Activity] = []

    async def update_presence(self, activity: hikari.Activity | None = None, **_: object) -> None:
        if activity is not None:
            self.activities.append(activity)


@pytest.fixture
def bot() -> FakeBot:
    return FakeBot()


@pytest.fixture
def presence(bot: FakeBot) -> Presence:
    return Presence(bot)  # type: ignore[arg-type]


def _activity_names(bot: FakeBot) -> list[str]:
    return [activity.name for activity in bot.activities]


@pytest.mark.asyncio
async def test_quiet_sets_the_default_activity(presence: Presence, bot: FakeBot) -> None:
    await presence.quiet()

    assert bot.activities[-1].type is hikari.ActivityType.LISTENING
    assert _activity_names(bot) == [constants.ACTIVITY_NAME]


@pytest.mark.asyncio
async def test_a_track_starting_overshadows_the_default(
    presence: Presence, bot: FakeBot
) -> None:
    await presence.quiet()
    await presence.track_started(make_track("Never Gonna Give You Up"))

    assert _activity_names(bot) == [constants.ACTIVITY_NAME, "Never Gonna Give You Up - Author"]


@pytest.mark.asyncio
async def test_a_track_without_an_author_shows_only_the_title(
    presence: Presence, bot: FakeBot
) -> None:
    track = make_track("Untitled")
    track.author = ""

    await presence.track_started(track)

    assert _activity_names(bot) == ["Untitled"]


@pytest.mark.asyncio
async def test_a_long_title_is_trimmed_to_the_activity_cap(
    presence: Presence, bot: FakeBot
) -> None:
    long_title = "Super " * 100

    await presence.track_started(make_track(long_title))

    shown = bot.activities[-1].name
    assert len(shown) == ACTIVITY_NAME_LIMIT
    assert shown.startswith("Super")


@pytest.mark.asyncio
async def test_going_quiet_reverts_to_the_default_activity(
    presence: Presence, bot: FakeBot
) -> None:
    await presence.track_started(make_track("A Track"))
    await presence.quiet()

    assert _activity_names(bot) == ["A Track - Author", constants.ACTIVITY_NAME]
