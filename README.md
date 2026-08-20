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
touches this process — a Lavalink node does the streaming, the bot only tells it
what to do.

## Features

- Music from **YouTube, Spotify and Deezer**, plus URL playback and playlists
- `/search` with live autocomplete for tracks, artists, albums and playlists via [LavaSearch](https://github.com/topi314/LavaSearch)
- Queue panel with Pause, Skip, Loop and Stop buttons
- The bot posts nothing unprompted — every message is a reply to a command

## Quick start

### Docker

```sh
cp .env.example .env                                           # DISCORD_TOKEN, CIPHER_PASSWORD
cp lavalink/application.yml.example lavalink/application.yml   # then fill in plugin credentials
docker compose up -d
```

Three services start in order: **yt-cipher**, **Lavalink**, then the **bot**.
On Linux, run `chown -R 322:322 lavalink/logs lavalink/plugins` first, or the
node cannot write.

The bot image is a snapshot of the code — after a code change, rebuild with
`docker compose up -d --build bot`.

### Local development (no Docker)

Requires Java 17+ for Lavalink:

```sh
winget install --id Microsoft.OpenJDK.21 -e   # once
.\scripts\lavalink.ps1                        # runs the node
uv run alfred                                 # second terminal, LAVALINK_HOST=127.0.0.1
```

### Before the first run

| | |
|---|---|
| **A cipher server is required** | Without it every YouTube client fails and nothing plays. `docker compose` starts one; see [YouTube needs a cipher server](#youtube-needs-a-cipher-server) |
| **Deezer is off until configured** | LavaSrc refuses to start with `deezer: true` and an empty `masterDecryptionKey`; turn it on in the same edit that fills the credentials in |
| **Spotify degrades instead** | With no credentials it registers fine and fails per request, so `/search` on Spotify returns nothing until `clientId`/`clientSecret` are set. YouTube needs no credentials at all |

## Commands

Eight commands, and `/play` connects to your voice channel on its own — there is
no `/join`.

| Group | Commands | |
|---|---|---|
| **Music** | `/play` `/search` | add a track, playlist or URL to the queue |
| **Queue** | `/queue` `/skip` `/remove` | the panel, move past a track, drop something |
| **Voice** | `/leave` | disconnect and clear |
| **Owner** | `/stats` `/info` | node health, and what the node is running |

| | |
|---|---|
| Loop and shuffle are **options**, not commands | Set once as tracks are queued. Loop is also a button |
| `/search` narrows by source and type | Track, artist, album or playlist |
| `/queue` needs no voice check; its **buttons** do | Reading the queue is open to anyone; acting on the player is restricted to the bot's voice channel |
| There is no `/pause` | Deafening yourself pauses playback when you're the only listener, and undeafening resumes it. The panel's Pause button is the only manual path |
| The bot leaves once it is alone | Nobody left to hear it |

### The panel

`/queue` is the whole player interface: current track, progress, what's next,
and four buttons. Each press redraws that message — never a second one.

| Button | Does | Note |
|---|---|---|
| `Pause` / `Resume` | Toggles playback | Label follows the player |
| `Skip` | Plays the next track | Defers first, so the redraw shows the new track |
| `Loop: off` / `track` / `queue` | Cycles the loop mode | State lives in the label |
| `Stop` | Clears the player | Then takes the buttons off the message |

Buttons go quiet after three minutes without a press (refreshed by every press)
and are then removed; the embed stays as a readable snapshot of the queue.

## YouTube needs a cipher server

YouTube protects its audio URLs with an obfuscated player script that must be
*run* to turn a stream signature into something playable — youtube-source's own
extractor can no longer read it, so every client fails with `Must find sig
function from script`. Upstream's answer is a remote cipher server
([youtube-source#225](https://github.com/lavalink-devs/youtube-source/issues/225)).

[yt-cipher](https://github.com/kikkia/yt-cipher) runs that script and answers
over HTTP. `docker compose up` starts one, `application.yml` points at it, and
`CIPHER_PASSWORD` in `.env` is what the two sides agree on.

| | |
|---|---|
| **Self-hosted by default** | The author's public instance at `cipher.kikkia.dev` is fine for a laptop, but it's shared and rate limited |
| **A cipher server does not fix `sign in to confirm you're not a bot`** | That's YouTube objecting to your IP. The fix is OAuth — see [docs/deploy.md](docs/deploy.md) |

## Configuration

Everything is read from the environment; a `.env` file is loaded if present.
`cp .env.example .env` gives working defaults for everything below — only two
have no default:

| Variable | Meaning |
|---|---|
| `DISCORD_TOKEN` | The bot token |
| `CIPHER_PASSWORD` | Shared between the node and yt-cipher. Any random string |

Two worth knowing:

- `LAVALINK_NODES` — a JSON array of node objects, for more than one node. Partial
  objects fall back to the single-node variables:

  ```sh
  LAVALINK_NODES='[{"name": "primary", "region": "asia"}, {"name": "backup", "host": "10.0.0.4"}]'
  ```

- `DEFAULT_GUILDS` — register commands to named guilds while developing. Guild
  commands appear instantly; global ones take up to an hour to propagate.

## Development

```sh
uv sync --frozen    # install the lock exactly — what the Docker build does
uv add <package>    # add a dependency and update the lock
uv lock --upgrade   # move the lock forward within the floors
```

Checks, both clean:

```sh
uv run pytest
uv run ruff check .
```

The lock is committed and pins everything; `pyproject.toml` carries floors only.
`--frozen` fails the build when the lock has drifted, so a forgotten `uv lock`
breaks the build rather than the deploy.

## Documentation

| | |
|---|---|
| [docs/deploy.md](docs/deploy.md) | Putting it on a VPS: machine, firewall, secrets, OAuth for datacentre IPs |
| [docs/design.md](docs/design.md) | How it's put together |
| [docs/prd.md](docs/prd.md) | Product requirements and acceptance criteria |

## Credits

A rewrite of [bachtran02/MusicCat](https://github.com/bachtran02/MusicCat),
inspired by [Ashema](https://github.com/nauqh/Ashema) in collaboration with [Nauqh](https://github.com/nauqh).