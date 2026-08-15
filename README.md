# Alfred

A Discord music streaming bot built with [hikari](https://www.hikari-py.dev/),
[lightbulb](https://github.com/tandemdude/hikari-lightbulb) and
[Lavalink](https://github.com/lavalink-devs/Lavalink).

This is a rewrite of the [`legacy-python` branch of bachtran02/MusicCat](https://github.com/bachtran02/MusicCat/tree/legacy-python)
on the current generation of those libraries: hikari 2.5, lightbulb 3.2 and Lavalink.py 5.11.

## Features

* Slash commands, with autocompletion on `/search` and `/remove`.
* `/queue` is the player panel: the current track, what follows it, and a row of buttons -
  pause, skip, loop, stop - for anyone in the bot's voice channel. Nothing is posted
  unprompted; the bot does not follow a queue around a channel with a message per track.
* `/search` looks queries up per source and per type (track, artist, album, playlist) through the
  [LavaSearch](https://github.com/topi314/LavaSearch) plugin.
* When one person is listening, Discord's deafen 🎧 pauses playback and undeafening resumes it.
  This is the only way to pause - there is no `/pause`. The bot leaves once it is alone in the
  channel.
* Sources are whatever the node's plugins provide - see `lavalink/application.yml.example` for the
  YouTube, Spotify and Deezer setup this was written against.

### Commands

Eight.

| Group | Commands                     | |
| ----- | ---------------------------- | --- |
| Music | `/play` `/search`            | add a track, playlist or URL to the queue |
| Queue | `/queue` `/skip` `/remove`   | the player panel, move past a track, drop something |
| Voice | `/leave`                     | disconnect and clear |
| Owner | `/stats` `/info`             | node health |

`/play` connects to your voice channel on its own, so there is no `/join`. Loop and shuffle
are options on `/play` and `/search` rather than commands of their own.

## Running it

### With Docker

```sh
cp .env.example .env                                        # DISCORD_TOKEN, and CIPHER_PASSWORD
cp lavalink/application.yml.example lavalink/application.yml  # then fill in your plugin credentials
docker compose up -d
```

Three services: the bot, a Lavalink node, and **yt-cipher**. That third one is not optional -
see below.

### YouTube needs a cipher server

YouTube protects its audio URLs with an obfuscated JavaScript player that has to be *run* to
turn a stream signature into something playable, and youtube-source's own extractor can no
longer read it. Every client fails with `Must find sig function from script`, search keeps
working, and nothing plays. Upstream's answer on
[youtube-source#225](https://github.com/lavalink-devs/youtube-source/issues/225) is a remote
cipher server rather than a release to wait for.

[yt-cipher](https://github.com/kikkia/yt-cipher) runs that script and answers over HTTP.
`docker compose up` starts one and `application.yml` points at it; set `CIPHER_PASSWORD` in
`.env` and the two sides agree. Running the node on its own instead? Either
`docker compose up yt-cipher`, or point `remoteCipher.url` at the author's public instance -
fine for a laptop, but it is shared and rate limited to 10 req/s.

A cipher server does not help with `sign in to confirm you're not a bot`. That one is YouTube
objecting to your IP, and the fixes are a poToken or OAuth - both covered in
`application.yml.example`.

### Locally, without Docker

Lavalink is a JVM service, so running the whole thing on one machine needs a Java 17+ runtime
instead of the daemon:

```sh
winget install --id Microsoft.OpenJDK.21 -e            # once
cp lavalink/application.yml.example lavalink/application.yml
.\scripts\lavalink.ps1                                 # fetches Lavalink.jar, then runs the node
```

Then, in a second terminal, point the bot at it and start it:

```sh
uv sync
cp .env.example .env    # DISCORD_TOKEN, and LAVALINK_HOST=127.0.0.1
uv run alfred
```

`LAVALINK_HOST=127.0.0.1` is the only difference from the Docker setup, and it cannot break it:
`docker-compose.yml` sets `LAVALINK_HOST=lavalink` in `environment:`, which overrides whatever
`env_file` supplies.

Three things about the node's config are worth knowing before the first run - all are covered by
comments in `application.yml.example`, and the first two are fatal:

* **A cipher server is required for YouTube playback**, as above. On this path either run
  `docker compose up yt-cipher` alongside, or switch `remoteCipher.url` to the public instance.
* **Deezer is off in the example, and has to stay off until it is configured.** LavaSrc refuses
  to start with `deezer: true` and an empty `masterDecryptionKey`, and the node exits before it
  binds a port. Turn it on in the same edit that fills the credentials in.
* **Spotify degrades instead.** With no credentials it registers fine and fails per request, so
  `/search` on Spotify returns nothing until `clientId`/`clientSecret` are filled in. YouTube
  needs no credentials at all.

### Locally, against the Docker node

Dependencies are managed with [uv](https://docs.astral.sh/uv/). `docker compose up lavalink`
runs just the node - it publishes 2333 to the host, so a bot started with `uv run alfred` on the
host can reach it.

```sh
docker compose up lavalink   # the node only
uv run alfred                # the bot, on the host - or: uv run python -m alfred
```

## Dependencies

`uv sync` creates `.venv` from `uv.lock`, on the Python named in `.python-version`.
`uv.lock` is committed and holds the exact version of everything installed. `pyproject.toml`
carries floors only, so:

```sh
uv sync --frozen    # install the lock exactly - what the Docker build does
uv add <package>    # add a dependency and update the lock
uv lock --upgrade   # move the lock forward within the floors
```

Development:

```sh
uv run pytest
uv run ruff check .
```

## Configuration

Everything is read from the environment (a `.env` file is loaded if one is present).

| Variable             | Default            | Meaning                                                        |
| -------------------- | ------------------ | -------------------------------------------------------------- |
| `DISCORD_TOKEN`      | *required*         | The bot token.                                                  |
| `LAVALINK_HOST`      | `lavalink`         | Node hostname.                                                  |
| `LAVALINK_PORT`      | `2333`             | Node port.                                                      |
| `LAVALINK_PASSWORD`  | `youshallnotpass`  | Node password.                                                  |
| `LAVALINK_REGION`    | `eu`               | Region the node is assigned to.                                 |
| `LAVALINK_SSL`       | `false`            | Use `wss`/`https` to reach the node.                            |
| `LAVALINK_NODE_NAME` | `default-node`     | Name the node shows up as in logs and `/stats`.                 |
| `LAVALINK_NODES`     | unset              | JSON array of node objects, for running more than one node.     |
| `DEFAULT_GUILDS`     | unset              | Comma separated guild IDs to register commands in. Global if unset. |
| `DELETE_AFTER`       | `60`               | Seconds before command replies clean themselves up. `0` keeps them. |
| `LOG_LEVEL`          | `INFO`             | Log level for the bot's own loggers.                            |
| `LOG_DIR`            | unset              | Write rotating `bot.log` and `track.log` files here.            |

`LAVALINK_NODES` takes partial objects - anything left out falls back to the single-node
variables above:

```sh
LAVALINK_NODES='[{"name": "eu-1", "region": "eu"}, {"name": "us-1", "host": "10.0.0.4", "region": "us"}]'
```

Registering commands to `DEFAULT_GUILDS` while developing avoids the hour-long propagation delay
that global commands have.

## Documentation

- [`docs/prd.md`](docs/prd.md) — what the bot is for, who operates it, and the
  requirements this release is measured against.
- [`docs/design.md`](docs/design.md) — how it is put together, and why the
  rewrite is shaped differently from the version it replaces.

## Layout

```
alfred/
├── bot.py          entrypoint: hikari bot, lightbulb client, Lavalink client
├── config.py       configuration read from the environment
├── service.py      joining voice, resolving queries, filling the queue
├── player.py       AlfredPlayer - the queue, and where its tracks came from
├── events.py       Lavalink events -> the log
├── hooks.py        command checks
├── search.py       LavaSearch client
├── embeds.py       embed builders
├── menus.py        the buttons under /queue
└── extensions/     the slash commands
```

## Notes on the rewrite

The libraries this was built on all changed shape since the legacy version:

* **lightbulb 2 → 3.** `BotApp`, plugins and the decorator stack are gone. Commands are classes,
  checks are execution hooks, and `bot.d` is replaced by dependency injection - the Lavalink
  client and config are registered on the client's DI registry and injected into commands.
* **hikari-miru is gone.** The buttons it existed for are now `lightbulb.components.Menu`,
  which ships with lightbulb itself. They live under `/queue` rather than under a message
  posted for every track.
* **Lavalink.py 5.1 → 5.11.** `Client._dispatch_event` is synchronous now, `AudioTrack.stream` was
  renamed `is_stream`, nodes take a required region, and `Node.request` is public - so the
  LavaSearch call no longer reaches into `node._transport._request`.
* `delete_after` on responses no longer exists in lightbulb, so self-deleting replies are
  scheduled in `responses.py`.
* Boolean options replaced `choices=['True']` strings parsed with `eval`.
* Loop modes now use Lavalink's own constants (`LOOP_SINGLE = 1`, `LOOP_QUEUE = 2`); the legacy
  player defined them the other way round, so its `/loop track` looped the queue. Loop is now
  the `loop` option on `/play` and `/search`.
* Configuration comes from the environment rather than being hardcoded in `config.py`.

---

Original project by [bachtran02](https://github.com/bachtran02/MusicCat), inspired by
[Ashema](https://github.com/nauqh/Ashema) in collaboration with [Nauqh](https://github.com/nauqh).
