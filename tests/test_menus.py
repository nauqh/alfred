"""The buttons under the now playing view."""

from __future__ import annotations

from typing import Any

import lavalink
import pytest

from alfred.music.player import AlfredPlayer
from alfred.ui.menus import NEXT_LOOP
from alfred.ui.menus import NowPlayingMenu
from alfred.ui.menus import QueuePanelMenu
from tests.conftest import confirm_playback
from tests.conftest import make_track

GUILD_ID = 1
BOT_ID = 500
OWNER_ID = 501
OUTSIDER_ID = 502
VOICE_CHANNEL_ID = 99
OTHER_CHANNEL_ID = 100
ALL_IN_VOICE = {BOT_ID: VOICE_CHANNEL_ID, OWNER_ID: VOICE_CHANNEL_ID, OUTSIDER_ID: VOICE_CHANNEL_ID}


class FakeVoiceState:
    def __init__(self, channel_id: int | None) -> None:
        self.channel_id = channel_id


class FakeCache:
    def __init__(self, states: dict[int, int | None]) -> None:
        self._states = states

    def get_voice_state(self, guild_id: int, user_id: int) -> FakeVoiceState | None:
        if user_id not in self._states:
            return None
        return FakeVoiceState(self._states[user_id])


class FakeMe:
    id = BOT_ID


class FakeBot:
    def __init__(self, states: dict[int, int | None]) -> None:
        self.cache = FakeCache(states)

    def get_me(self) -> FakeMe:
        return FakeMe()


class FakePlayerManager:
    def __init__(self, player: AlfredPlayer | None) -> None:
        self._player = player

    def get(self, guild_id: int) -> AlfredPlayer | None:
        return self._player


class FakeLavalinkClient:
    def __init__(self, player: AlfredPlayer | None) -> None:
        self.player_manager = FakePlayerManager(player)


class FakeUser:
    def __init__(self, user_id: int) -> None:
        self.id = user_id

    @property
    def mention(self) -> str:
        return f"@{self.id}"


class FakeClient:
    """Stands in for the lightbulb client, with the owner ids already resolved."""

    def __init__(self) -> None:
        self._owner_ids = {OWNER_ID}


class FakeComponent:
    """Stands in for the button that was pressed."""

    def __init__(self, label: str) -> None:
        self.label = label


class FakeContext:
    """Stands in for `lightbulb.components.MenuContext`."""

    def __init__(self, user_id: int, *, label: str = "Pause") -> None:
        self.user = FakeUser(user_id)
        self.client = FakeClient()
        self.component = FakeComponent(label)
        self.responses: list[dict[str, Any]] = []
        self.deferred = False
        self.interacting = True
        self.timeouts: list[float] = []

    async def respond(self, content: Any = None, **kwargs: Any) -> None:
        self.responses.append({"content": content, **kwargs})

    async def defer(self, *, ephemeral: bool = False, edit: bool = False) -> None:
        self.deferred = True

    def stop_interacting(self) -> None:
        self.interacting = False

    def set_timeout(self, timeout: float) -> None:
        self.timeouts.append(timeout)


def start_track(player: AlfredPlayer, requester_id: int, title: str = "Some Song") -> AlfredPlayer:
    """Put a track on the player and make it the current one, as the node confirming it would."""
    player.add(track=make_track(title), requester=requester_id)
    player._next = player.queue.pop(0)
    confirm_playback(player)
    return player


@pytest.fixture
def playing_player(player: AlfredPlayer) -> AlfredPlayer:
    return start_track(player, OWNER_ID)


def build_menu(player: AlfredPlayer | None, states: dict[int, int | None]) -> NowPlayingMenu:
    return NowPlayingMenu(FakeBot(states), FakeLavalinkClient(player), GUILD_ID)  # type: ignore[arg-type]


def build_panel(player: AlfredPlayer | None, *, page_size: int = 10) -> QueuePanelMenu:
    return QueuePanelMenu(FakeLavalinkClient(player), GUILD_ID, page_size=page_size)  # type: ignore[arg-type]


IN_CHANNEL = {BOT_ID: VOICE_CHANNEL_ID, OWNER_ID: VOICE_CHANNEL_ID, OUTSIDER_ID: OTHER_CHANNEL_ID}


def test_the_row_is_three_labelled_buttons(playing_player: AlfredPlayer) -> None:
    menu = build_menu(playing_player, IN_CHANNEL)

    assert [b.label for b in (menu.pause_button, menu.skip_button, menu.loop_button)] == [
        "Pause",
        "Skip",
        "Loop: off",
    ]
    assert [b.emoji for b in (menu.pause_button, menu.skip_button, menu.loop_button)] == [
        "⏸️",
        "⏭️",
        "🔁",
    ]


def test_the_pause_label_follows_the_player(playing_player: AlfredPlayer) -> None:
    playing_player.paused = True

    assert build_menu(playing_player, IN_CHANNEL).pause_button.label == "Resume"


def test_the_loop_label_follows_the_player(playing_player: AlfredPlayer) -> None:
    playing_player.loop = lavalink.DefaultPlayer.LOOP_QUEUE

    assert build_menu(playing_player, IN_CHANNEL).loop_button.label == "Loop: queue"


def test_loop_cycles_back_to_off() -> None:
    loop = lavalink.DefaultPlayer.LOOP_NONE
    seen = []
    for _ in range(3):
        loop = NEXT_LOOP[loop]
        seen.append(loop)

    assert seen == [
        lavalink.DefaultPlayer.LOOP_SINGLE,
        lavalink.DefaultPlayer.LOOP_QUEUE,
        lavalink.DefaultPlayer.LOOP_NONE,
    ]


@pytest.mark.asyncio
async def test_a_listener_in_the_channel_may_press(playing_player: AlfredPlayer) -> None:
    menu = build_menu(playing_player, IN_CHANNEL)
    ctx = FakeContext(OWNER_ID)

    assert await menu.check(ctx) is playing_player  # type: ignore[arg-type]
    assert ctx.responses == []


@pytest.mark.asyncio
async def test_an_outsider_is_turned_away_with_the_snark(playing_player: AlfredPlayer) -> None:
    # In the bot's channel and at a live player - but the owner queued this track, not them.
    menu = build_menu(playing_player, ALL_IN_VOICE)
    ctx = FakeContext(OUTSIDER_ID, label="Skip")

    assert await menu.check(ctx) is None  # type: ignore[arg-type]
    assert ctx.responses[0]["content"] == f"@{OUTSIDER_ID} Skip con cặc à?"


@pytest.mark.asyncio
async def test_someone_in_no_channel_is_turned_away(playing_player: AlfredPlayer) -> None:
    menu = build_menu(playing_player, {BOT_ID: VOICE_CHANNEL_ID})
    ctx = FakeContext(OUTSIDER_ID, label="Loop: off")

    assert await menu.check(ctx) is None  # type: ignore[arg-type]
    assert ctx.responses[0]["content"] == f"@{OUTSIDER_ID} Loop: off con cặc à?"


@pytest.mark.asyncio
async def test_the_owner_still_needs_the_bots_channel(playing_player: AlfredPlayer) -> None:
    # Ownership admits the press, not the channel: the owner in another voice channel is
    # still answered with the voice rule rather than the snark.
    menu = build_menu(playing_player, {BOT_ID: VOICE_CHANNEL_ID, OWNER_ID: OTHER_CHANNEL_ID})
    ctx = FakeContext(OWNER_ID)

    assert await menu.check(ctx) is None  # type: ignore[arg-type]
    assert "same voice channel" in ctx.responses[0]["content"]


@pytest.mark.asyncio
async def test_whoever_queued_the_track_may_press_it(player: AlfredPlayer) -> None:
    # Not the owner, but this is their track playing, so the panel is theirs to work.
    start_track(player, OUTSIDER_ID)
    menu = build_menu(player, ALL_IN_VOICE)

    assert await menu.check(FakeContext(OUTSIDER_ID)) is player  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_the_claim_covers_the_current_track_only(player: AlfredPlayer) -> None:
    # Queueing something does not buy the panel while somebody else's track is playing.
    start_track(player, OWNER_ID)
    player.add(track=make_track("Theirs, Later"), requester=OUTSIDER_ID)
    ctx = FakeContext(OUTSIDER_ID, label="Skip")

    assert await build_menu(player, ALL_IN_VOICE).check(ctx) is None  # type: ignore[arg-type]
    assert ctx.responses[0]["content"] == f"@{OUTSIDER_ID} Skip con cặc à?"


@pytest.mark.asyncio
async def test_the_requester_still_needs_the_bots_channel(player: AlfredPlayer) -> None:
    start_track(player, OUTSIDER_ID)
    menu = build_menu(player, {BOT_ID: VOICE_CHANNEL_ID, OUTSIDER_ID: OTHER_CHANNEL_ID})
    ctx = FakeContext(OUTSIDER_ID)

    assert await menu.check(ctx) is None  # type: ignore[arg-type]
    assert "same voice channel" in ctx.responses[0]["content"]


@pytest.mark.asyncio
async def test_pressing_when_nothing_plays_is_answered_not_actioned(player: AlfredPlayer) -> None:
    menu = build_menu(player, IN_CHANNEL)
    ctx = FakeContext(OWNER_ID)

    assert await menu.check(ctx) is None  # type: ignore[arg-type]
    assert "Nothing is playing" in ctx.responses[0]["content"]


@pytest.mark.asyncio
async def test_pause_toggles_and_relabels(playing_player: AlfredPlayer, node: Any) -> None:
    menu = build_menu(playing_player, IN_CHANNEL)

    await menu.on_pause(FakeContext(OWNER_ID))  # type: ignore[arg-type]

    assert playing_player.paused is True
    assert menu.pause_button.label == "Resume"
    assert menu.pause_button.emoji == "▶️"


@pytest.mark.asyncio
async def test_loop_advances_and_relabels(playing_player: AlfredPlayer) -> None:
    menu = build_menu(playing_player, IN_CHANNEL)

    await menu.on_loop(FakeContext(OWNER_ID))  # type: ignore[arg-type]

    assert playing_player.loop == lavalink.DefaultPlayer.LOOP_SINGLE
    assert menu.loop_button.label == "Loop: track"
    assert menu.loop_button.emoji == "🔂"


@pytest.mark.asyncio
async def test_an_outsider_cannot_pause(playing_player: AlfredPlayer) -> None:
    menu = build_menu(playing_player, IN_CHANNEL)

    await menu.on_pause(FakeContext(OUTSIDER_ID))  # type: ignore[arg-type]

    assert playing_player.paused is False


def test_the_panel_shows_the_current_track(playing_player: AlfredPlayer) -> None:
    playing_player.add(track=make_track("Up Next"), requester=OWNER_ID)

    embed = build_menu(playing_player, IN_CHANNEL).embed()

    assert embed.title == "Now Playing"
    assert "Some Song" in embed.description
    # The queue's list is `/queue`'s job; the view is only the track it sits under.
    assert "Up Next" not in embed.description


def test_the_panel_says_so_when_there_is_no_player() -> None:
    embed = build_menu(None, IN_CHANNEL).embed()

    assert embed.description == "Nothing is playing."


@pytest.mark.asyncio
async def test_a_press_redraws_the_view_in_place(playing_player: AlfredPlayer) -> None:
    menu = build_menu(playing_player, IN_CHANNEL)
    ctx = FakeContext(OWNER_ID)

    await menu.on_loop(ctx)  # type: ignore[arg-type]

    assert ctx.responses[0]["edit"] is True
    assert ctx.responses[0]["components"] is menu
    assert ctx.responses[0]["embed"].title == "Now Playing"


@pytest.mark.asyncio
async def test_skip_plays_the_next_track(playing_player: AlfredPlayer) -> None:
    queued = make_track("Up Next")
    playing_player.add(track=queued, requester=OWNER_ID)
    ctx = FakeContext(OWNER_ID)

    await build_menu(playing_player, IN_CHANNEL).on_skip(ctx)  # type: ignore[arg-type]

    # Deferred first, because waiting on the node takes longer than an interaction may go
    # unanswered for. The track events replace the message, so the menu's work ends here.
    assert ctx.deferred is True
    assert playing_player._next is queued
    assert ctx.interacting is False


@pytest.mark.asyncio
async def test_skip_does_not_redraw(playing_player: AlfredPlayer) -> None:
    ctx = FakeContext(OWNER_ID)

    await build_menu(playing_player, IN_CHANNEL).on_skip(ctx)  # type: ignore[arg-type]

    # The view is replaced by the track-start event, not edited by the press.
    assert ctx.responses == []


def queued_panel(player: AlfredPlayer, tracks: int, *, page_size: int = 10) -> QueuePanelMenu:
    """A panel over a player playing one track with ``tracks`` more waiting."""
    start_track(player, OWNER_ID)
    for i in range(tracks):
        player.add(track=make_track(f"Queued {i}"), requester=OWNER_ID)
    return build_panel(player, page_size=page_size)


def test_a_queue_that_fits_on_one_page_offers_no_paging(player: AlfredPlayer) -> None:
    panel = queued_panel(player, tracks=4)

    assert panel.pages() == 1
    assert (panel.prev_button.disabled, panel.next_button.disabled) == (True, True)


def test_the_first_page_can_go_forwards_but_not_back(player: AlfredPlayer) -> None:
    panel = queued_panel(player, tracks=25)

    assert panel.pages() == 3
    assert (panel.prev_button.disabled, panel.next_button.disabled) == (True, False)


@pytest.mark.asyncio
async def test_paging_to_the_end_greys_out_next(player: AlfredPlayer) -> None:
    panel = queued_panel(player, tracks=25)

    await panel.on_next(FakeContext(OUTSIDER_ID))  # type: ignore[arg-type]
    await panel.on_next(FakeContext(OUTSIDER_ID))  # type: ignore[arg-type]

    assert panel.page == 2
    assert (panel.prev_button.disabled, panel.next_button.disabled) == (False, True)


@pytest.mark.asyncio
async def test_anyone_may_page(player: AlfredPlayer) -> None:
    # Reading the queue is open to anyone, exactly as `/queue` is - no voice or owner check.
    panel = queued_panel(player, tracks=25)
    ctx = FakeContext(OUTSIDER_ID)

    await panel.on_next(ctx)  # type: ignore[arg-type]

    assert panel.page == 1
    assert ctx.responses[0]["edit"] is True


@pytest.mark.asyncio
async def test_a_press_redraws_the_panel_and_extends_its_life(player: AlfredPlayer) -> None:
    panel = queued_panel(player, tracks=25)
    ctx = FakeContext(OWNER_ID)

    await panel.on_next(ctx)  # type: ignore[arg-type]

    assert ctx.responses[0]["components"] is panel
    assert "Page 2/3" in ctx.responses[0]["embed"].description
    # Reset, not extended: the panel goes quiet a fixed while after the last press.
    assert ctx.timeouts == [180.0]


def test_a_page_past_the_end_is_clamped_rather_than_rendered_empty(player: AlfredPlayer) -> None:
    # The queue moves under an open panel: what was page 3 may not exist by the next press.
    panel = queued_panel(player, tracks=25)
    panel.page = 2
    del player.queue[10:]

    panel.refresh_buttons()

    assert (panel.page, panel.pages()) == (0, 1)


def test_a_panel_outliving_its_player_says_nothing_is_playing() -> None:
    assert build_panel(None).embed().description == "Nothing is playing."
