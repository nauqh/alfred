# Deploying to a VPS

Deployment is performed with `docker compose up -d`; the remainder of this
guide covers preparing the machine and its secrets. The stack's runtime
footprint:

| Service | Idle RAM |
|---|---|
| `alfred` (bot) | ~58 MB |
| `alfred-lavalink` (Lavalink node) | ~300-350 MB (JVM, capped at `-Xmx400M`) |
| `alfred-cipher` | ~104 MB |

The node was measured at ~420 MB before the heap was capped. A JVM only
collects garbage as it nears its ceiling, so a ceiling above the machine's real
RAM means it never collects and is eventually killed by the kernel instead. The
cap lives in `docker-compose.yml` and is the first thing to change when moving
to a different size of machine.

## 1. Prepare the machine

Requires SSH access to a Debian/Ubuntu box with root and Docker installed.
Verify `docker ps` responds before continuing.

**Size.** ~510 MB of stack plus ~150 MB for the OS and the Docker daemon, so
**1 GB is the working minimum** and 2 GB is comfortable. 512 MB does not fit,
and fails during `docker compose build` before it ever gets to run. Disk and
bandwidth are not the constraint: the images and build cache come to ~3 GB, and
a playing bot moves ~100 MB an hour counting the fetch in and the stream out.

**IPv4 only.** Discord's gateway, API and voice servers are all IPv4, and the
containers reach each other over Docker's IPv4 bridge. There is nothing to
configure, and enabling IPv6 is worth avoiding: the node will generally prefer
it outbound, and Google treats a datacentre IPv6 block more harshly than the
equivalent IPv4 address, which is the same bot check section 5 exists to solve.

**Swap.** Droplets ship without any. One GB costs nothing on a 25 GB disk and
covers the build, which is the tightest moment the machine will have:

```sh
fallocate -l 1G /swapfile && chmod 600 /swapfile
mkswap /swapfile && swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
```

Nothing should touch it in normal running. If `free -h` shows swap in steady
use, the machine is too small rather than correctly configured.

**Region.** Match the droplet to the voice channel's region, not to where
anyone lives: audio goes from the node to a Discord voice server, and that is
the hop worth keeping short. Pin the region in Discord under Channel Settings,
Overrides, rather than letting it be chosen per session.

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

- Running the node outside Docker: set `CIPHER_URL` to a yt-cipher you run yourself (the
  compose default, `http://yt-cipher:8001`, only resolves on the compose network) and set
  `CIPHER_PASSWORD` to its `API_TOKEN`. Otherwise the node falls back to the shared
  `cipher.kikkia.dev` - rate limited to 10 req/s across everyone using it.
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

One optional variable is worth setting on a real deploy, since it defaults to
off and does not announce its absence: `LOG_DIR=logs` writes `bot.log` and
`track.log` into the mounted `./logs` directory, both rotating at midnight and
keeping ten days. Left unset, the mount in `docker-compose.yml` is inert and
`docker compose logs` is the only record.

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
| `curl -H "Authorization: $LAVALINK_PASSWORD" localhost:2333/v4/stats` | Node uptime, players, memory, CPU |
| `curl -H "Authorization: $LAVALINK_PASSWORD" localhost:2333/v4/info` | Node version, plugins, sources |

The healthcheck authenticates, so `Authorization missing for 127.0.0.1 on GET
/version` every ten seconds is no longer expected noise. Seeing it now means
either something else is probing the node unauthenticated, or `LAVALINK_PASSWORD`
in `.env` has drifted from `server.password` in `lavalink/application.yml` - in
which case the node reports unhealthy and the bot will not start against it.
