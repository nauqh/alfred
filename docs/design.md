# Design

How the bot is put together, and why the rewrite is shaped differently from the
[`legacy-python`](https://github.com/bachtran02/MusicCat/tree/legacy-python)
branch it replaces. What the product is meant to do is [prd.md](prd.md); the
libraries and their versions are [`pyproject.toml`](../pyproject.toml).

The rule this document is written against: **the legacy bot had no seam between
Discord and Lavalink.** Every command reached through `bot.d.lavalink` into a
player and orchestrated its own joining, loading, queueing and replying -
`extensions/play.py` imported `_play` and `_get_tracks` out of a module called
`library/base.py` that also held the embed-building. There was one global
mutable bag (`bot.d`) and **32 reads of `bot.d.lavalink`** through it. The
rewrite puts exactly one module between the two worlds and makes the dependency
explicit.

## Vocabulary

Small, but the words are load-bearing and two of them were used loosely before.

**Player** - the guild's `AlfredPlayer`: its queue, loop and shuffle state. One
per guild, created on the first join, destroyed by Lavalink. It holds no Discord
message state at all. _Avoid_: session, connection.

**Queue** - the tracks waiting. The currently playing track is **not** in it;
`player.current` is separate, and Lavalink only sets it when the node confirms
the track started.

**Now playing view** - the message the bot posts when a track starts: an embed
describing the current track, with the player's buttons under it. It is the only
thing the bot renders that can be pressed, and it lives exactly as long as its
track: moving to the next track deletes it and posts the next track's view, and
the queue ending deletes it outright. _Avoid_: panel, controller.

The view is the only unprompted message tied to playback. Two others exist and
are both scheduled rather than reactive: the change log posted on restart, and
the Sunday recap. Everything else the bot sends is the reply to a command
someone ran.

**Play history** - the rows in `data/plays.db`: one per track start, with the
user who queued it. Written by `recorder`, read only by the recap. It is not
state the player consults - nothing in playback reads it back. _Avoid_: stats,
analytics.

**Source** - a search backend behind a Lavalink prefix (`ytsearch`, `dzsearch`,
`spsearch`). Not every Source is **playable**: Spotify is mirrored onto another
source by LavaSrc, which is why `Source.playable` exists.

**Load result** - what a query resolved to. One of track, search, playlist,
empty or error. A playlist may carry richer plugin metadata (artist, album)
which changes only how it is described, never how it is queued.

## Shape

```
   ┌──────────────────────────────────────────────┐
   │  Discord                                     │
   │  slash commands · voice state                │
   └───────────────┬──────────────────────────────┘
                   │ gateway (GUILDS, GUILD_VOICE_STATES)
   ┌───────────────▼──────────────────────────────┐
   │  hikari  GatewayBot                          │
   │     └── lightbulb  Client                    │
   │            commands · hooks · DI             │
   ├──────────────────────────────────────────────┤
   │  alfred                                    │
   │     hooks ──► service ──► player             │
   │     menus ──► embeds    events ──► nowplaying │
   └───────────────┬──────────────────────────────┘
                   │ lavalink.py 5.11
   ┌───────────────▼──────────────────────────────┐
   │  Lavalink v4 node                            │
   │     youtube-plugin · LavaSrc · LavaSearch    │
   └───────────────┬──────────────────────────────┘
                   │
        YouTube · Spotify · Deezer · SoundCloud
```

Two processes: the bot and the node. No queue, no worker, no cron - and, until
the weekly recap, no database either. What the recap added is one SQLite file
written through `storage.py` and an `asyncio` task that sleeps until Sunday;
neither is a third process, and both are off unless configured.

Playback state stays in memory and is meant to be. A restart drops the queues,
which is the same behaviour the legacy bot had and has never been a complaint.
What survives a restart is history, not position.

## Layout

```
alfred/
├── alfred/
│   ├── bot.py            entrypoint: hikari bot, lightbulb client, Lavalink client
│   ├── events.py         Lavalink events → the log, and the now playing view
│   ├── config.py         the environment → a frozen Config
│   ├── errors.py         errors that carry a user-facing message
│   ├── constants.py      colours, the media emojis, and the queue panel's shape
│   ├── log_config.py     loguru, and the bridge from the standard library
│   ├── owner.py          who owns the bot, resolved once and cached
│   ├── presence.py       what Discord shows under the bot's name
│   ├── changelog.py      the newest CHANGELOG.md entry, for the restart post
│   ├── storage.py        SQLite play history - the only module that touches disk
│   ├── recorder.py       writing a row as each track starts
│   ├── recap.py          the Sunday task: sleep, read the week, post it
│   │
│   ├── music/            the player, and what fills it
│   │   ├── service.py      join · resolve · enqueue - the one seam
│   │   ├── player.py       AlfredPlayer - the queue, and its tracks' origins
│   │   ├── sources.py      the search sources and their prefixes
│   │   └── search.py       the LavaSearch plugin client
│   │
│   ├── ui/               everything Alfred renders and posts
│   │   ├── embeds.py       embed builders, and Discord's limits
│   │   ├── nowplaying.py   the now playing view's lifecycle
│   │   ├── menus.py        the now playing controls, and the queue panel's paging
│   │   ├── responses.py    replying, and the self-deleting reply
│   │   └── formatting.py   durations, progress bar, trimming
│   │
│   ├── chat/             answering @mentions, and acting on them
│   │   ├── client.py       talking to a model on OpenRouter
│   │   ├── completions.py  turning a raw completion into something postable
│   │   ├── actions.py      running commands from chat, behind the same checks
│   │   └── prompt.py       the persona
│   │
│   └── extensions/       the slash commands, and their checks
│       ├── hooks.py        the command checks
│       └── general · play · queue · admin · chat
├── lavalink/             the node's application.yml
├── data/                 plays.db, written at runtime and gitignored
├── landing/              the GitHub Pages landing page
├── tests/
└── docs/
```

The packages are strictly layered, and nothing points back up:

```
wiring  →  extensions  →  chat  →  ui  →  music  →  errors · config · constants
                                     ↘  recap  →  storage  ←  recorder
```

`music` owes nothing to `ui`, which is why `service.enqueue` returns a **`Queued`**
describing what it added rather than a rendered embed. Two callers read the same
value differently: `/play` renders it as the "Track added" card, and the chat path
describes it in a sentence. `events.py` sits at the top rather than inside `music/`
because it is glue - Lavalink events driving the now playing view - and would
otherwise be the one edge pointing back up. `recorder.py` sits beside it for the
same reason and is deliberately a second handler rather than a branch inside the
first: writing a row and keeping the view in step fail independently, and a
failed write must not cost anyone their now playing card.

## The modules

The ones that matter, each stated as its interface. Everything else is
implementation.

| Module | Interface | What it hides |
|---|---|---|
| `Config` | `from_env() -> Config` | env parsing, the multi-node JSON, every validation error |
| `service` | `join()` · `resolve()` · `enqueue()` | voice connection, query prefixing, five load-result shapes, playlist metadata |
| `AlfredPlayer` | `skip()` · `stop()` · `remove()` | resetting to a clean state even when the node is unreachable |
| `LavalinkEventHandler` | nothing - it consumes events | what the node reports, and restarting a stuck player |
| `NowPlayingManager` | `show(player)` · `hide(guild_id)` | the view's message lifecycle, the menu registry leak, and the bar's refresh |
| `NowPlayingMenu` | `embed()` · three button callbacks | who may press, and keeping the view in step with the player |
| `QueuePanelMenu` | `embed()` · `pages()` · two button callbacks | where a page starts and ends, and a queue that moves under an open panel |
| `search` | `load_search(node, query, types)` | the plugin's REST contract, its 204, its failures |
| `hooks` | four execution hooks | voice-state cache lookups and dependency injection |
| `responses` | `respond(ctx, **kwargs)` | the self-deleting reply lightbulb no longer provides |
| `embeds` | one builder per card, plus `queue_pages` | every embed shape in the bot, and Discord's limits on them |
| `PlayStore` | `record_play()` · `upsert_user()` · `weekly()` · `users()` | SQLite, the schema, the legacy single-table migration, and pruning past 60 days |
| `recap` | `schedule(...)` - an asyncio task | the sleep-until-Sunday arithmetic, the timezone, and a missed week |

There is no DTO layer and no repository. The player *is* the model, and
`lavalink.AudioTrack` is the only track type that crosses a boundary.

`PlayStore` is the single exception to "no persistence", and is deliberately
narrow: it is the only module that opens a file, it returns plain tuples rather
than a row type, and nothing in the playback path reads from it. Remove the
recap and the module has no callers left.

### `service` - the one real seam

Three functions, and every command that touches music goes through them:

- **`join(bot, lavalink_client, guild_id, user_id) -> (player, channel_id)`** -
  finds the caller's voice channel, creates the player, connects deafened.
- **`resolve(lavalink_client, query, source) -> LoadResult`** - strips `<>`,
  prefixes bare queries with the source's search prefix, leaves URLs alone, and
  turns every failure into a `NoResults` carrying something worth showing a user.
- **`enqueue(...) -> Embed`** - joins if needed, adds the tracks, sets loop mode,
  starts playback if idle, and returns the embed describing what happened.

The legacy equivalents were `_join`, `_get_tracks` and `_play` in
`library/base.py`, and the seam leaked in both directions. `_play` took a
`bot` and reached into `bot.d.lavalink` itself; `_get_tracks` smuggled the
playlist URL forward by writing it onto `result.tracks[0].user_data`
(`library/base.py:41`) for `_play` to read back out four lines later. Here the
original query is a parameter, and playlist provenance is attached to every
track as a typed `PlaylistRef` on `track.extra` - which is a plain dict that
always exists, where `user_data` is `None` for any track the server did not tag.

`_join` returned `None` on every path (`library/base.py:14-27`), and the `join`
command then read `player.channel_id` off it (`extensions/bot.py:31`). The
command had been broken for as long as the file existed. `join` now returns
both the player and the channel it joined.

### `AlfredPlayer` - one addition, and one correction

Subclasses `lavalink.DefaultPlayer`. What survives the trims is small: where a
queued track came from, and a `stop()` that resets rather than merely stopping.
The one piece of Discord it knows is `text_channel_id` - the channel of the last
command that queued a track, which is where the now playing view is posted.

**Loop constants are the library's.** The legacy player redefined them
(`library/player.py:10-12`) as `LOOP_QUEUE = 1`, `LOOP_SINGLE = 2` - inverted
against `lavalink.DefaultPlayer`, where `LOOP_SINGLE = 1` and `LOOP_QUEUE = 2`.
Both sets were live in the same process: `/loop track` called `set_loop(1)`
(`extensions/player.py:148`) and its overridden `play()` read that 1 as its own
`LOOP_QUEUE`, appending the current track to the end of the queue. **`/loop
track` looped the queue.** It went unnoticed because a single-track queue makes
the two indistinguishable. The rewrite defines no constants of its own, and loop
is the `loop` option on `/play` and `/search` rather than a command.

The legacy player also **overrode `play()` wholesale** - sixty lines duplicated
out of the library, which had already drifted: the copy still awaited
`client._dispatch_event`, synchronous since lavalink.py 5.x. Nothing overrides
`play()` here.

**`stop()` resets state even when the node is unreachable.** It is called from
the voice-state handler when the bot has just been disconnected - which is
exactly the moment the node may already be gone. The node call is wrapped; the
local reset is not conditional on it.

`stop()` ends by dispatching `QueueEndEvent`. `DefaultPlayer.play` dispatches the
same event when it runs out of queue and *also* calls `stop()` on the way, so the
event can arrive twice for one ending. Nothing hangs off it but a log line, so
that costs nothing - but anything added here must stay idempotent.

### `LavalinkEventHandler` - the view, and a stuck player

Two jobs. `TrackStartEvent` posts the now playing view (`NowPlayingManager.show`,
which first deletes whatever view is up), and `QueueEndEvent` takes it down -
so the view follows the player no matter how the track changed: naturally, by
skip, by stop, or by the retry logic putting a failed track back on. Because
`AlfredPlayer.stop` also dispatches `QueueEndEvent`, leaving voice takes the
view with it, and the handling stays idempotent against the double dispatch.

Every listener also writes a log line; `TrackStuckEvent` additionally calls
`play()` to move past the track the node cannot get through.

An earlier revision of this rewrite posted a now-playing message per track and
deleted it on the next one, and it was cut as an announcement nobody asked for.
It is back - with the player's buttons on it, which is what makes a message per
track worth posting: the view is the control surface, not a notification.

### `NowPlayingMenu` - the buttons under the view

Three interactive buttons and a track link: pause/resume, skip, loop, and an
external link button to the track URL. State lives in the label (`Loop: track`)
and matching emoji (`🔂`). The menu holds no player state - every press
looks the player up again, so it acts on whatever is playing now rather than on
what was playing when the view was posted.

Access is two rules, checked in that order. **Who may press**: the bot's owner,
or whoever queued the track that is playing. The claim is on the track, not on
the queue - once it moves on, so does the right to control it, which is what
stops "I queued something an hour ago" becoming a permanent hold on the panel.
**Where from**: whoever passes must still be in the bot's voice channel, the
rule `/skip` and `/leave` apply. A button and its command cannot disagree.

The player is therefore resolved *before* either rule, which is the opposite of
the obvious order: the requester is read off the current track, so there is
nobody to recognise until there is a track.

Pause and loop redraw the view in place - the same message, a new embed and
labels. Skip does not: the track event it causes deletes this message and posts
the next track's view, so that callback only `defer(edit=True)`s to answer the
interaction in time and then steps aside. Redrawing a message the event handler
is about to delete would be a race the bot loses.

One more thing buttons need that commands do not: **a rejected press must still
be answered.** A `check` that returns without responding shows the user
"interaction failed"; every rejection replies ephemerally.

### `NowPlayingManager` - the view's lifecycle

`show(player)` posts the view into the player's `text_channel_id`, replacing
whatever is up; `hide(guild_id)` deletes it. Both are idempotent, because the
events that drive them are not: `QueueEndEvent` can arrive twice for one ending.

The buttons are attached with **`menu.attach(client, timeout=None)` on a
cancelled-when-done task**, not `attach_persistent`, which matters.
`MenuHandle.__init__` accepts an `_am` argument and then assigns
`self.__am = None`, discarding it (`lightbulb/components/menus.py:579-587`), so
with `timeout=None` a persistent menu is never removed from
`client._attached_menus` - a set consulted on every component interaction,
leaking one entry per track. `attach` discards in a `finally`, so it cannot
leak: `hide` cancels the task and awaits it, and the registry is clean before
the message is deleted. The view gets no timeout at all - it lives exactly as
long as its track, which is exactly as long as there is something to control.

A second task re-draws the embed every `REFRESH_INTERVAL` seconds, because
`player.position` is read when the embed is built and the bar would otherwise
show one moment of the track for the whole track. It edits the embed alone:
hikari leaves an unspecified component list untouched, so the buttons keep the
custom IDs they were posted with and the menu stays the only thing that moves
their labels. A paused player and a stream are skipped rather than drawn - the
bar does not move for either - and a message that has been deleted ends the
loop instead of raising the same error every tick. `hide` cancels this alongside
the buttons.

### `QueuePanelMenu` - paging `/queue`

`/queue` renders one page and offers Prev/Next when there is more than one.
Nothing here touches the player, so nothing here is restricted: reading the
queue is open to anyone, exactly as the command is.

Two things it must get right. The **page count lives in `embeds.queue_pages`**,
next to the slicing it has to agree with - a Next button offering a page the
embed renders empty is worse than no button. And the **queue moves underneath an
open panel**: tracks play out, the last page stops existing, so every render
clamps the page to what is there now rather than trusting what the button was
drawn for.

Unlike the now playing view, this panel has no natural end, so it gets a
timeout, refreshed by each press. When it expires the buttons come off and the
embed stays: a page someone stopped on is still a readable snapshot, but a
button that no longer answers is worse than none. `/queue` blocks on `attach`
for the same registry reason the view does.

### `search` - the LavaSearch client

lavalink.py has no support for the LavaSearch plugin, so `/search` autocomplete
calls `GET /v4/loadsearch` itself. The legacy version reached into
`node._transport._request` (`extensions/play.py:39`); `Node.request` is public in
5.11, so this is now a supported call.

Two shapes have to be handled that the legacy code did not. The plugin answers
**204 No Content** when it has nothing, which lavalink.py surfaces as the boolean
`True` rather than a mapping - so the return is type-checked, not trusted. And a
node that is down must not break autocomplete: every failure returns an empty
result, because a dropped autocomplete is invisible and a raised one is a
traceback per keystroke.

`/search` on YouTube does not use the plugin at all - YouTube has no rich
artist/album results - so it falls back to an ordinary search through `resolve`.

### `hooks` - checks, and where the Lavalink client comes from

Four hooks, all on the `CHECKS` step: `guild_only`, `valid_user_voice`,
`player_connected`, `player_playing`. Each raises a `AlfredError` subclass
carrying its own user-facing message; the client's single error handler replies
with it ephemerally and handles nothing else specially.

They are also where the dependency injection shows. Lightbulb 3 wraps every hook,
invoke method, listener and autocomplete provider with `linkd`'s injector, so a
hook declares what it needs:

```python
@lightbulb.hook(lightbulb.ExecutionSteps.CHECKS)
def player_playing(
    _: lightbulb.ExecutionPipeline,
    ctx: lightbulb.Context,
    lavalink_client: lavalink.Client = lightbulb.di.INJECTED,
) -> None:
```

This replaces `bot.d.lavalink` - an untyped attribute on a global bag, read at
32 sites, with nothing to catch a typo until runtime.

**The registration is ordered against a one-shot window.** `lavalink.Client`
needs the bot's own user id, which does not exist until Discord says so; the DI
registry freezes as soon as the first container is created, which happens on the
first command. Both facts point at the same place, so `StartedEvent` does all of
it in one listener - build the Lavalink client, register it, load the extensions,
then `client.start()`. `client.start` is deliberately **not** subscribed to
`StartedEvent` separately, the way lightbulb's own documentation suggests,
because hikari dispatches listeners concurrently and the order would not hold.

### `responses` - the reply lightbulb stopped providing

Lightbulb 2 had `ctx.respond(..., delete_after=60)`, used on 13 replies.
Lightbulb 3 has no equivalent. `responses.respond` sends the reply, then
schedules the delete on a task held in a module-level set - the event loop keeps
only weak references to tasks, so an unheld one can be collected mid-sleep.
`DELETE_AFTER=0` turns the behaviour off.

## Command surface

9 commands, in four extensions. Every one is a `lightbulb.SlashCommand`
subclass registered on a `Loader`.

The legacy bot had 18. `/restart` with `/seek`, and `/join` because `/play`
connects on its own. `/shuffle` became an option on `/play` and `/search`, set
once at queueing time; `/loop` is an option there too, and a button on the view.
`/stop` went because `/leave` covers it - disconnecting clears the player.
`/now` came back as a command: it shows the current track card on demand, a
convenience that repeats what the now playing view already shows.

`/seek`, `/effects` and `/pause` went last, and unlike the rest they were not
redundant - they are out of scope for what this bot is now. `/seek` and
`/effects` took the equalizer and timescale filters out of the node config with
them.

Two capabilities are gone rather than moved: **stepping backwards through
history** and **seeking within a track**. Pausing has no command, but it is not
gone: it is a button on the panel, and it still happens on its own in the
voice-state handler - when a single listener deafens themselves, playback pauses,
and undeafening resumes it.

```
general    /leave                                 hooks: guild, voice, connected

play       /play    query next loop shuffle       hooks: guild, voice
           /search  query type source + the above hooks: guild, voice
                    query autocompletes; type and source drive LavaSearch

queue      /now                                   hooks: guild, playing
           /queue                                 hooks: guild, playing
           /skip                                  hooks: guild, voice, playing
           /remove  track       autocompletes from the live queue

admin      /stats /info                           hooks: owner only
```

The buttons - pause · skip · loop · link - are not a command: they sit under the
now playing view, which the bot posts when a track starts and deletes when it
ends. Acting on the player is privileged, so `NowPlayingMenu.check` turns away
anyone outside the bot's voice channel.

`/now` shows the track playing now as a full now playing card; it is the one
convenience that repeats what the active view already says, kept because asking
for it is cheap. `/queue` deliberately carries no voice check - reading what is
playing is not a privileged act, and requiring channel membership to answer
"what is this song" was friction with no threat behind it.

`next`, `loop` and `shuffle` are **boolean options**. The legacy versions were
string options constrained to `choices=['True']` and then parsed with
`eval(ctx.options.next)` (`extensions/play.py:93-95`). The choice list kept the
input to one literal, so it was never a live injection - but it is `eval` on an
argument that arrived over the network, and Discord has had a boolean option type
the whole time.

## Configuration

Everything is environment, read once into a frozen `Config` at startup. The
legacy bot hardcoded the node in `bot/config.py` - host, port, password and a
two-node list - so pointing it at a different node was a code change.

| Tier | Contents |
|---|---|
| Required | `DISCORD_TOKEN` (`TOKEN` still accepted, for the legacy `.env`) |
| Node | `LAVALINK_HOST` `_PORT` `_PASSWORD` `_REGION` `_SSL` `_NODE_NAME` |
| Node, plural | `LAVALINK_NODES` - JSON array of partial node objects, each falling back to the singular vars |
| Behaviour | `DEFAULT_GUILDS` · `DELETE_AFTER` · `LOG_LEVEL` · `LOG_DIR` |
| Chat | `OPENROUTER_API_KEY` · `OPENROUTER_MODEL` · `CHAT_MAX_TOKENS` · `CHAT_TEMPERATURE` · `CHAT_TIMEOUT` · `CHAT_SYSTEM_PROMPT` |
| Posting | `STARTUP_CHANNEL_ID` · `RECAP_CHANNEL_ID` · `RECAP_HOUR` · `RECAP_TIMEZONE` |

The last two tiers are **capability switches, not settings**. `Config.chat` and
`Config.recap` are `None` when their key variable is absent, and a `None` there
means the feature is never wired up at all: no OpenRouter key and the message
listener is not registered, so the bot cannot hear ordinary traffic; no recap
channel and neither the Sunday task nor the play-history database is created.
Absence is the off switch, which is why neither has an `ENABLED` flag.

A bad value fails the boot with the variable named, not the first command that
touches it. `LAVALINK_NODES` takes partial objects on purpose: the common
multi-node case differs by name and region only, and repeating the password per
node is how passwords end up disagreeing.

`DEFAULT_GUILDS` registers commands to named guilds instead of globally, which is
the difference between seeing an edited command immediately and waiting out
Discord's global propagation.

The node's own configuration is [`lavalink/application.yml.example`](../lavalink/application.yml.example) -
plugins and sources. Every audio filter is off: the bot applies none since
`/effects` was removed.

## Testing

257 tests, no network, ~2s. Each module is tested through the interface its
callers use.

- `Config` - the environment is a parameter, so every case is a dict.
- `AlfredPlayer` - a fake node recording `update_player` calls, and a fake
  client recording dispatched events.
- `service` - a fake Lavalink client; asserts the queries sent, the queue built,
  and the embeds returned.
- `search` - a fake node returning recorded payloads, the 204, and a raised error.
- `hooks` - run through a real `linkd` container, so the test proves the
  injection works and not merely the logic.
- `menus` - a fake menu context and voice-state cache; asserts who may press,
  what each press does to the player, and that pause and loop redraw the view in
  place while skip defers to the track events.
- `nowplaying` - a fake REST client; asserts a track posts a view with buttons,
  the next track replaces it, and hiding it unregisters the menu rather than
  leaking it.
- `storage` - a real SQLite database under `tmp_path`, since the thing worth
  testing is the SQL. Covers the legacy-schema migration and the 60-day prune.
- `recap` - the schedule arithmetic as a pure function, so every case is a
  date: the Sunday that has already passed rolls a week, and an unknown
  timezone falls back to UTC rather than raising.
- `changelog` - parsing `CHANGELOG.md`, including a file with no released
  entry yet.

Two library behaviours the tests had to model rather than assume, both found by
tests failing for the right reason:

- **`player.current` is set by the node, not by `play()`.** lavalink.py stages
  the track in `player._next` and promotes it when the track-start frame arrives
  (`lavalink/transport.py:315`). `confirm_playback()` in `conftest.py` stands in
  for that frame.
- **`player.position` extrapolates from a monotonic clock**, not the wall clock
  (`lavalink/player.py:145`). A fixture written with `time.time()` produced a
  position tens of years in the past and sent `play_previous` down the wrong
  branch.

The one module with no tests of its own is `extensions/chat.py`, the mention
listener: everything it calls is covered, but the listener is a hikari event
handler and testing it would mean modelling the gateway. The in-flight guard and
the reply-chain walk are code review only, and are marked that way in the PRD.

There is no test that talks to Discord or to a Lavalink node. The offline
ceiling is the command surface: a script builds the client, loads all four
extensions and renders all 9 command builders exactly as Discord would receive
them - names, option types, required flags, autocomplete flags, choice counts -
which catches the whole class of registration errors without a token.

## What the rewrite costs

Measured at the 2.0 cutover, and left at those figures because that is the
comparison being made. The package has grown since: **4,796 lines and 3,160 of
tests as of 2026-09-18**, the difference being the chat package, the weekly
recap and the play history, none of which the legacy bot had in any form.

At cutover the package was **2,064 lines against the legacy `bot/`'s 1,578**,
plus 1,246 lines of tests where there were none. Stated plainly because the direction is the
wrong one for a simplification: the growth is docstrings, type annotations,
`config.py` (146 lines that were previously eight hardcoded ones, and 248 now),
and typed errors. The parts that were genuinely too big got smaller - the copied 56-line
`play()` override is under 30, `library/base.py`'s 105 lines of mixed
orchestration and embed-building split into `service.py` and `embeds.py`, and
`ui.py` went outright along with the player's history, `play_previous` and
`play(index=)` - 119 lines of module and 83 of player, none of which had another
caller. The four buttons that replaced its six are 180 lines, against `ui.py`'s
119 for six.

## Why this stack

Re-examined 2026-08-14, after the port, on the question of whether Lavalink is
still the right audio backend. It is, but not for the reason people usually give.

**The audio server.** Every credible option was checked for whether it is alive:

| | Latest | Last commit | Verdict |
|---|---|---|---|
| **Lavalink** (JVM) | 4.2.2 | 2026-06-08 | Alive. DAVE (E2EE voice) support since 4.2.0 |
| **NodeLink** (Node.js) | - | 2026-06-17 | Alive, but see below |
| **FrequenC** (C) | - | 2024-09-23 | Dead, two years |

NodeLink is the only real contender, and it is genuinely attractive on
resources - its README claims ~24 MB idle against a JVM's hundreds. Two facts
rule it out here. It has **no LavaSearch and no Lavalink plugin system** -
`loadsearch` does not appear anywhere in its source - so `/search`'s
artist/album/playlist autocomplete, the bot's most distinctive feature, would
have to go. And its own client compatibility table lists Lavalink.py at
**"v3 supported? unknown"**, tested only against NodeLink v1 and v2; Wavelink is
the sole Python client marked as supported, and Wavelink is discord.py-only.
Switching would mean losing a feature *and* changing the client library.

**Not using an audio server at all** was considered and is not available to us.
hikari ships `VoiceComponent` and `VoiceConnection` as abstractions with no
implementation behind them - no opus pipeline, no source resolution. Native
playback is a discord.py capability (FFmpeg + `yt-dlp`), and taking it would mean
changing Discord libraries, transcoding on the bot's own CPU, and owning the
YouTube arms race directly instead of consuming someone else's fixes.

**The client.** `lavalink.py` 5.11.0, last commit 2026-06-14. The alternative for
a hikari bot is `hikari-ongaku` 1.0.4, which is hikari-native and would remove
the manual voice-state forwarding in `extensions/general.py`. It was rejected on
cadence: its most recent commit (2026-03-01) is *"Support Lavalink V4.2.0"* -
that is the version of Lavalink released in February, so it tracks the server
rather than leading it, where lavalink.py already carried the DAVE `channelId`
field before it was needed. The ergonomic win is one listener; the cost is
rewriting `player.py`, `service.py` and `events.py`.

**DAVE.** Lavalink 4.2.0 added support for Discord's end-to-end encrypted voice
and requires the client to send a `channelId` in the voice state. lavalink.py
sends it (`lavalink/abc.py:259`), and `extensions/general.py` supplies it. This
was checked rather than assumed, because it is the one upcoming Discord change
that could stop the bot dead.

**The actual risk is YouTube, and it is not a stack decision.** youtube-source's
most recent commit at the time of writing is *"Revert client version upgrade
(apparently older works better…)"* - the arms race, live. Every option above
loses playback the same week when YouTube changes something; the only thing that
varies is who ships the fix. Lavalink's plugin does, faster than the alternatives
and much faster than a bot maintaining `yt-dlp` itself. That, rather than
performance or ergonomics, is the argument for this stack.

## Deliberately absent

`hikari-miru` · `bot.d` · a custom `AutocompleteChoice` class · a copied `play()`
override · private `_transport` access · `eval` on options · hardcoded node
config · application-specific emoji IDs · a queue · a worker · persistence of
playback state across restarts.

"A database" was on that list until the weekly recap, which needed a week of
history and could not get it from memory. What arrived is the smallest thing
that answers the question: one SQLite file, stdlib, no server, no ORM, no
migration tool, and no reader outside the recap. Playback still persists
nothing.

The emoji are the subtlest of those. The legacy bot carried eleven custom emojis
belonging to its own Discord application, and **no other application can render
another's** - a fork would have got blank or rejected buttons with nothing in the
logs to explain it. Three survive, Unicode, for the progress bar in the embed.

`hikari-miru` went because lightbulb 3 ships component menus, and one dependency
that does the job is better than two that overlap. The `AutocompleteChoice`
class (`library/classes/choice.py`, 25 lines re-implementing a hikari builder)
went because `hikari.impl.AutocompleteChoiceBuilder` exists.

## Deferred

Persistence of playback state across restarts, multi-node failover testing, and
`/previous` as a command. None is blocked by anything here; each is out of scope
for a port whose contract was to change the libraries and not the product.

A test CI workflow is **declined rather than deferred**: it was built and
removed at the operator's request, deployment being a deliberate manual step
(`docs/deploy.md`). The one workflow in `.github/` publishes `landing/` to
GitHub Pages and touches neither the tests nor the deploy.

That accepted risk - **nothing in this rewrite having run against Discord or a
live Lavalink node** - is closed: the bot runs on a VPS in production, and
`docs/deploy.md` documents that deployment rather than proposing one.

What has not changed is the shape of the safety net. The offline checks remain
thorough about shape and silent about behaviour, so anything that can only fail
against a real gateway or node still fails in production first. The PRD marks
those requirements `manual` for exactly that reason.
