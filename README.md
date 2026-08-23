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
- Queue panel with Pause, Skip, Loop and Stop buttons
- **@mention it to ask a question, or to queue something** - "@Alfred play bohemian rhapsody" really queues it. Answered by a free [OpenRouter](https://openrouter.ai) model; off unless a key is set
- The bot posts nothing unprompted - every message is a reply to a command or to a mention

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

Nine commands; `/play` connects to your voice channel on its own - there is
no `/join`.

| Group | Commands | |
|---|---|---|
| **Music** | `/play` `/search` | add a track, playlist or URL to the queue |
| **Queue** | `/now` `/queue` `/skip` `/remove` | the current track, the list, move past a track, drop something |
| **Voice** | `/leave` | disconnect and clear |
| **Owner** | `/stats` `/info` | node health, and what the node is running |

| | |
|---|---|
| Loop and shuffle are **options**, not commands | Set once as tracks are queued. Loop is also a button |
| `/search` narrows by source and type | Track, artist, album or playlist |
| `/queue` and `/now` need no voice check | Reading what is playing is open to anyone; acting on the player is restricted to the bot's voice channel |
| There is no `/pause` | Deafening yourself pauses playback when you are the only listener, and undeafening resumes it. The panel's Pause button is the only manual path |
| The bot leaves when no one is left in the channel | Queue state is irrelevant - it stays even with nothing queued |

### The now playing view

When a track starts, the bot posts a `Now Playing` card where it was queued and
deletes it when the track ends - the next track replaces it with its own. The
card carries the progress bar and the player's buttons; `/queue` is just the
list of what follows.

| Button | Does | Note |
|---|---|---|
| `⏸️ Pause` / `▶️ Resume` | Toggles playback | Turns green while paused |
| `⏭️ Skip` | Plays the next track | The card is replaced by the next track's card |
| `🔁 Loop: off` / `track` / `queue` | Cycles the loop mode | Highlights blurple while on |
| `🔗 Link` | Opens the track URL | Native Discord link button |

Buttons go quiet after three minutes without a press (refreshed by every press)
and are then removed; the embed stays as a readable snapshot of the queue.

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

Two worth knowing:

- `LAVALINK_NODES` - a JSON array of node objects, for more than one node.
  Partial objects fall back to the single-node variables:

  ```sh
  LAVALINK_NODES='[{"name": "primary", "region": "asia"}, {"name": "backup", "host": "10.0.0.4"}]'
  ```

- `DEFAULT_GUILDS` - register commands to named guilds while developing. Guild
  commands appear instantly; global ones take up to an hour to propagate.

### Chat replies

Set `OPENROUTER_API_KEY` ([get one](https://openrouter.ai/keys)) and the bot answers
when someone @mentions it. Leave it blank and the listener is never registered, so the
bot stays deaf to ordinary channel traffic.

It can also *run* four of its commands when asked, through OpenRouter tool calling:

| Ask it | Runs |
|---|---|
| "play never gonna give you up", "play `<url>`" | `/play` |
| "what's playing" | `/now` |
| "show me the queue" | `/queue` |
| "skip this" | `/skip` |

Asked for music without naming anything — "play something" — it asks what you want
rather than picking for you.

| | |
|---|---|
| **The model proposes, it does not decide** | A tool call is treated as a request from whoever sent the message, never as an instruction from the model. `alfred/actions.py` re-applies the same checks the equivalent slash command applies, so asking Alfred to skip is exactly as restricted as running `/skip`. The requester, guild and channel come from the message - nothing the model returns can change who a track is queued as |
| **Checks are duplicated, not shared** | A `lightbulb` hook needs a `Context` and a message listener has none, so `actions.py` mirrors `hooks.py` rather than importing it. `tests/test_actions.py` asserts the pairs stay in step |
| **No privileged intent needed** | Answering mentions needs `GUILD_MESSAGES`, not `MESSAGE_CONTENT` - Discord exempts messages that mention your bot from the content restriction. Nothing to toggle in the developer portal |
| **Free model ids rot** | OpenRouter rotates which models carry a free tier, and a retired id 404s at request time rather than at startup. Current list: [openrouter.ai/models?q=free](https://openrouter.ai/models?q=free). Swap with `OPENROUTER_MODEL` |
| **Prefer a non-reasoning model** | A reasoning model sits thinking for seconds before its first word. Measured across eight questions on 2026-08-23: the default answered in 1.7-5.8s, `nemotron-3.5-lightning` in 5-29s while burning ~1000 thinking tokens a reply. Latency is the thing to check when swapping |
| **Context is the reply chain** | A cold mention is a fresh question. Reply to one of Alfred's answers and that exchange comes with it. Nothing is stored between messages, so a restart loses nothing and one person's conversation never leaks into another's |
| **Reasoning models are muzzled** | Several free models think out loud, and their thinking is `content` unless you say otherwise - one posted its entire *"Here's a thinking process:"* monologue into a channel as the answer. Requests send `reasoning: {"exclude": true}`, and a completion that still opens with a monologue is refused rather than posted |
| **The model picks the format** | Plain text for ordinary answers; an embed when the answer has structure worth laying out. It opts in by returning JSON with a title or fields - structure *is* the signal, so there is no separate flag for a weak model to get wrong. Anything unparseable is posted as the plain answer it looks like, rather than failing the reply |
| **One reply per channel at a time** | Mentions arriving while one is in flight are dropped, not queued - the free tier is rate limited hard enough that a queued answer arrives after everyone has moved on |

Every reply logs one line at `INFO` - model, latency, plain or embed, and token
usage - so a truncated answer is visible as a completion count sitting exactly on
`CHAT_MAX_TOKENS`. `LOG_LEVEL=DEBUG` adds the prompt turns and the raw completion,
which is what explains a reply that came out plain when an embed was wanted.

`CHAT_MAX_TOKENS`, `CHAT_TEMPERATURE` and `CHAT_TIMEOUT` tune the request.
`CHAT_SYSTEM_PROMPT` replaces Alfred's persona *and* its knowledge of its own
commands - the built-in prompt lists them, so an override drops that.

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
| [docs/design.md](docs/design.md) | How it is put together |
| [docs/prd.md](docs/prd.md) | Product requirements and acceptance criteria |

## Credits

A rewrite of [bachtran02/MusicCat](https://github.com/bachtran02/MusicCat),
inspired by [Ashema](https://github.com/nauqh/Ashema) in collaboration with [Nauqh](https://github.com/nauqh).