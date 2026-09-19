# Alfred

![Python](https://img.shields.io/badge/Python-3.13-blue?colorA=363a4f&colorB=8aadf4&style=for-the-badge&logo=python&logoColor=cad3f5)
![hikari](https://img.shields.io/badge/hikari-2.5-blue?colorA=363a4f&colorB=b7bdf8&style=for-the-badge&logo=discord&logoColor=cad3f5)
![lightbulb](https://img.shields.io/badge/lightbulb-3.2-blue?colorA=363a4f&colorB=eed49f&style=for-the-badge&logo=python&logoColor=cad3f5)
![Lavalink](https://img.shields.io/badge/Lavalink-4.2-blue?colorA=363a4f&colorB=8bd5ca&style=for-the-badge&logo=openjdk&logoColor=cad3f5)
![Lavalink.py](https://img.shields.io/badge/Lavalink.py-5.11-blue?colorA=363a4f&colorB=91d7e3&style=for-the-badge&logo=python&logoColor=cad3f5)
![Docker](https://img.shields.io/badge/Docker-compose-blue?colorA=363a4f&colorB=a6da95&style=for-the-badge&logo=docker&logoColor=cad3f5)
![uv](https://img.shields.io/badge/uv-locked-blue?colorA=363a4f&colorB=c6a0f6&style=for-the-badge&logo=uv&logoColor=cad3f5)

A Discord music bot. `/play` joins your voice channel and queues what you asked
for; `/queue` shows what's playing with buttons to control it. Audio never
touches this process - a Lavalink node does the streaming, the bot only tells
it what to do.

## Features

- Music from **YouTube, Spotify and Deezer**, plus URL playback and playlists
- `/search` with live autocomplete for tracks, artists, albums and playlists via [LavaSearch](https://github.com/topi314/LavaSearch)
- Now playing card with Pause, Skip and Loop buttons, and a progress bar that keeps moving
- `/queue` pages through the whole queue, ten tracks at a time
- Nothing is unprompted - every message is a reply to a command, or the now playing card

## Quick start

### Docker

```sh
cp .env.example .env                                           # set DISCORD_TOKEN and CIPHER_PASSWORD
cp lavalink/application.yml.example lavalink/application.yml
docker compose up -d
```

Linux only: run `chown -R 322:322 lavalink/logs lavalink/plugins` before the
first `up`, or the node cannot write its logs.

That starts three services: **yt-cipher**, **Lavalink**, then the **bot**.
After a code change, rebuild the bot with `docker compose up -d --build bot`.

To run this on a VPS, follow [docs/deploy.md](docs/deploy.md) - it covers
machine prep, secrets, updates and YouTube auth.

### Local development (no Docker)

Requires Java 17+ for Lavalink:

```sh
winget install --id Microsoft.OpenJDK.21 -e   # once, Windows
.\scripts\lavalink.ps1                        # runs the node
uv run alfred                                 # second terminal, LAVALINK_HOST=127.0.0.1
```

### Source caveats before first run

| | |
|---|---|
| **Deezer is off until configured** | LavaSrc refuses to start with `deezer: true` and an empty `masterDecryptionKey`; turn it on in the same edit that fills the credentials |
| **Spotify degrades instead** | With no credentials it registers fine and fails per request, so `/search` on Spotify returns nothing until `clientId`/`clientSecret` are set. YouTube needs no credentials at all |

## Commands

Seven commands; `/play` connects to your voice channel on its own - there is
no `/join`.

| Group | Commands | |
|---|---|---|
| **Music** | `/play` `/search` | add a track, playlist or URL to the queue |
| **Queue** | `/now` `/queue` `/skip` `/remove` | the current track, the list, move past a track, drop something |
| **Voice** | `/leave` | disconnect and clear |

| | |
|---|---|
| Loop and shuffle are **options**, not commands | Set once as tracks are queued. Loop is also a button |
| `/search` narrows by source and type | Track, artist, album or playlist |
| `/queue` and `/now` need no voice check | Reading what is playing is open to anyone, including paging through the queue; acting on the player takes the bot's voice channel *and* a claim on the track - whoever queued it, or the bot's owner. `/skip` and the buttons apply the same rule |
| There is no `/pause` | The now playing card's Pause button is the only path |
| The bot leaves when no one is left in the channel | Queue state is irrelevant - it stays even with nothing queued |

### The now playing view

When a track starts, the bot posts a `Now Playing` card where it was queued and
deletes it when the track ends - the next track replaces it with its own. The
card carries the progress bar and the player's buttons; `/queue` is just the
list of what follows.

The bar is re-drawn every 15 seconds, so it shows where the track has actually
reached rather than where it was when the card went up. A paused track and a
live stream are left alone - neither has a bar that moves.

| Button | Does | Note |
|---|---|---|
| `⏸️ Pause` / `▶️ Resume` | Toggles playback | Turns green while paused |
| `⏭️ Skip` | Plays the next track | The card is replaced by the next track's card |
| `🔁 Loop: off` / `track` / `queue` | Cycles the loop mode | Highlights blurple while on |
| `🔗 Link` | Opens the track URL | Native Discord link button |

**Who may press:** the bot's owner, or whoever queued the track that is playing -
and they have to be in the bot's voice channel, the same rule `/skip` applies.
The claim is on the track, not on the queue: once it moves on, so does the right
to control it. Anyone else gets a reply telling them where to go.

The buttons have no timeout. They live exactly as long as the track does, which
is exactly as long as there is anything to control.

### The queue panel

`/queue` shows the current track and the next ten, with `⬅️ Prev` and `➡️ Next`
when there are more. Paging is open to anyone - it only moves your view of the
queue. The numbering keeps counting across pages, so `11.` is the eleventh track
in the queue rather than the first one on page two.

A queue that fits on one page gets no buttons. The ones it does get go quiet
three minutes after the last press and are then removed; the embed stays as a
readable snapshot of the page it was left on.

## YouTube playback needs a cipher server

YouTube protects its audio URLs with an obfuscated player script that must be
*run* to turn a stream signature into something playable - youtube-source's own
extractor can no longer read it, so every client fails with `Must find sig
function from script`. Upstream's answer is a remote cipher server
([youtube-source#225](https://github.com/lavalink-devs/youtube-source/issues/225)).

[yt-cipher](https://github.com/kikkia/yt-cipher) runs that script and answers
over HTTP. `docker compose up` starts one and `application.yml` points at it;
`CIPHER_PASSWORD` in `.env` is what the two sides agree on.

**A cipher server does not fix `sign in to confirm you're not a bot`** - that
is YouTube objecting to the *IP*, normally because the bot runs on a VPS. The
fix is OAuth; see [docs/deploy.md](docs/deploy.md).

## Configuration

Everything is read from the environment; `.env` is loaded if present.
`cp .env.example .env` gives working defaults, so only two variables have no
default: `DISCORD_TOKEN` and `CIPHER_PASSWORD`.

One worth knowing: `DEFAULT_GUILDS` registers commands to named guilds while
developing. Guild commands appear instantly; global ones take up to an hour to
propagate.

Set `LOG_DIR` and the bot also writes `bot.log` and `track.log`, both rotating
at midnight and keeping ten days.

## How it fits together

`alfred.bot` builds the hikari bot, the lightbulb client and the Lavalink client,
and hands the last two to everything else through lightbulb's DI registry. From
there the tree splits three ways, and the split is the point: nothing in `music/`
imports anything in `ui/`.

| | |
|---|---|
| `alfred/music/` | Talking to Lavalink: resolving queries, filling the queue, the player subclass. Returns plain values, never embeds |
| `alfred/ui/` | Everything Discord sees: embeds, buttons, and the now playing view that follows the current track |
| `alfred/extensions/` | The slash commands, and the checks they run first as lightbulb hooks |

Two rules hold the rest together. Player state is never cached - every button
press and every redraw looks the player up again, so a panel left open acts on
what is playing now. And the now playing view is driven by Lavalink's track
events rather than by the commands, so it follows the player however the track
changed.

## Development

```sh
uv sync --frozen    # install the lock exactly - what the Docker build does
uv add <package>    # add a dependency and update the lock
uv lock --upgrade   # move the lock forward within the floors
```

Checks:

```sh
uv run pytest
uv run ruff check .
```

The lock is committed and pins everything; `pyproject.toml` carries floors
only. `--frozen` fails the build when the lock has drifted, so a forgotten
`uv lock` breaks the build rather than the deploy.

## Documentation

| | |
|---|---|
| [docs/deploy.md](docs/deploy.md) | Run it on a VPS: box prep, secrets, updates, YouTube OAuth |
| [HANDOFF.md](HANDOFF.md) | Working notes: what is settled, what not to re-open |

## Credits

A rewrite of [bachtran02/MusicCat](https://github.com/bachtran02/MusicCat),
inspired by [Ashema](https://github.com/nauqh/Ashema) in collaboration with [Nauqh](https://github.com/nauqh).