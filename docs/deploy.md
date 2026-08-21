# Deploying to a VPS

Deployment is performed with `docker compose up -d`; the remainder of this
guide covers preparing the machine and its secrets. The stack's runtime
footprint:

| Service | Idle RAM |
|---|---|
| `alfred` (bot) | ~58 MB |
| `alfred-lavalink` (Lavalink node) | ~420 MB (JVM) |
| `alfred-cipher` | ~104 MB |

## 1. Prepare the machine

Requires SSH access to a Debian/Ubuntu box with root and Docker installed.
Verify `docker ps` responds before continuing.

## 2. Retrieve the code and configure secrets

```sh
git clone https://github.com/nauqh/alfred.git ~/alfred
cd ~/alfred
cp .env.example .env
cp lavalink/application.yml.example lavalink/application.yml
```

`.env` requires three values:

| Variable | Purpose |
|---|---|
| `DISCORD_TOKEN` | The bot token |
| `CIPHER_PASSWORD` | Any random string - `openssl rand -hex 24`. Read by both the node and yt-cipher; compose will not start without it |
| `LAVALINK_PASSWORD` | Any value, provided it matches `server.password` in `application.yml` |

> Mismatched passwords are the most common cause of a node that starts, a bot
> that connects, and no audio. Keeping both at `youshallnotpass` is acceptable.

`application.yml` is ready to run as-is for a standard deployment. Two
deploy-specific cases:

- Running the node outside Docker: `remoteCipher.url` must not point at the
  shared `cipher.kikkia.dev`.
- Deezer: leave `deezer: false` unless `masterDecryptionKey` **and** `arl` are
  filled in - LavaSrc otherwise refuses to start and the node exits before
  binding a port.

## 3. Start the stack

```sh
mkdir -p lavalink/logs lavalink/plugins logs
sudo chown -R 322:322 lavalink/logs lavalink/plugins    # the node runs as uid 322

docker compose up -d
docker compose ps          # lavalink should be healthy
docker compose logs -f bot
```

Expected startup output:

```
Registered Lavalink node 'default-node' at lavalink:2333
Connected to Lavalink node 'default-node'
started successfully in approx 2 seconds
```

`restart: unless-stopped` combined with `systemctl enable docker` restores the
stack automatically after a reboot.

## 4. Updating

Deploys are manual. The appropriate command depends on what changed:

| Changed | Command |
|---|---|
| Code | `git pull && docker compose up -d --build bot` |
| `.env` | `docker compose up -d` |
| `lavalink/application.yml` | `docker compose restart lavalink` (bind mount) |

Only the bot is built from source; the source is baked into the image at build
time, so `git pull` alone does not affect a running stack. The node and
yt-cipher are pinned images - update them by deliberately editing the tag or
digest in `docker-compose.yml`.

## 5. Configure YouTube auth

The following is expected on the first deploy:

```
Client [TVHTML5_SIMPLY] failed: Sign in to confirm you're not a bot
Client [WEB] failed: This video requires login.
```

VPS IPs fall in published datacentre ranges where almost all traffic is
treated as scraper traffic, so YouTube requests proof of identity. This is not
a configuration error.

- `Must find sig function from script` indicates yt-cipher is not working.
- The lines above are an identity check; no configuration below that line
  helps.

The example ships the `oauth:` block commented out, so a fresh deploy has no
credential yet and hits the check. The remedy is **OAuth** in the `oauth:` block
of `lavalink/application.yml` -
not the poToken most guides recommend first (youtube-source's README states a
poToken "no longer bypasses the bot check for majority of cases"). Use a
burner Google account; termination is a possible outcome.

Uncomment `enabled` alone to begin (no token yet):

```yaml
    oauth:
      enabled: true
```

```sh
docker compose restart lavalink
docker compose logs -f lavalink
```

The node logs a code and a URL. Enter them at `google.com/device`, sign in as
the burner, and the node prints a refresh token. Paste it back:

```yaml
    oauth:
      enabled: true
      refreshToken: "<the token from the log>"
      skipInitialization: true
```

Restart once more - `skipInitialization` prevents the prompt on subsequent
boots. The refresh token belongs in this gitignored file only. When YouTube
breaks again in the future, repeat the device flow.

## 6. Monitoring

| | |
|---|---|
| `docker compose logs -f` | All logs - one line per track, one per command |
| `/stats` in Discord | Node uptime, players, memory, CPU - owner only |
| `/info` in Discord | Node version, plugins, sources |

`Authorization missing for 127.0.0.1 on GET /version` every ten seconds is the
healthcheck, which deliberately omits the password - a 401 still confirms the
node is responding.
