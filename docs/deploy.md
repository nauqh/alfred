# Deploying to a VPS

Written against Hetzner Cloud, but nothing here is Hetzner-specific — any
provider that hands you root on a Debian box works the same way. The whole
deploy is `docker compose up -d`; everything before that is getting the machine
and the secrets into place.

## The machine

**CX22** — 2 vCPU, 4 GB RAM, 40 GB NVMe, about €4/month. Sized against what the
stack actually uses, idle:

| | |
|---|---|
| `alfred` | ~58 MB |
| `alfred-lavalink` | ~420 MB — the JVM is the whole cost |
| `alfred-cipher` | ~104 MB |

A 2 GB box fits; 1 GB does not, and 512 MB is not worth attempting. Pick the
region nearest your Discord voice region — Falkenstein or Nuremberg for `eu`,
Ashburn for `us`.

Image: **Debian 12**. Add your SSH public key during creation rather than
letting Hetzner mail you a root password; a box with password login on port 22
starts getting brute-forced within the hour.

## Firewall

**No inbound ports are needed. None.** The bot opens a websocket *out* to
Discord, and the node talks to the bot over Docker's internal network. Nothing
on the internet needs to reach this machine except your own SSH.

In Hetzner's Cloud Firewall (free, and applied outside the VM):

| Direction | Rule |
|---|---|
| Inbound | TCP 22, from your IP if it is static — otherwise from anywhere |
| Inbound | nothing else |
| Outbound | allow all |

`docker-compose.yml` binds the node to `127.0.0.1:2333` for this reason. Do not
change that to `2333:2333` on a public machine: it would expose a Lavalink node
whose password starts life as `youshallnotpass`, and an open node is a
stranger's streaming relay, billed to your bandwidth.

## The box, once

```sh
ssh root@<ip>

adduser alfred && usermod -aG sudo alfred        # stop working as root
rsync --archive --chown=alfred:alfred ~/.ssh /home/alfred/

apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh           # Docker's own installer
usermod -aG docker alfred

systemctl enable docker                          # survives a reboot
```

Then disable root and password SSH in `/etc/ssh/sshd_config`:

```
PermitRootLogin no
PasswordAuthentication no
```

`systemctl restart ssh`, and **open a second terminal to confirm you can still
get in** before closing the first. Locking yourself out of a fresh VPS costs a
rebuild.

## The code

The repository has no remote. Either push it to a **private** GitHub repo and
clone, or copy the directory up:

```sh
# from your machine
rsync -av --exclude .venv --exclude .git --exclude .env . alfred@<ip>:~/alfred/
```

`.env` is excluded deliberately — secrets get created on the server, not copied
around. Same for `lavalink/application.yml`, which is gitignored and so never in
a clone either.

## The secrets

```sh
cd ~/alfred
cp .env.example .env
cp lavalink/application.yml.example lavalink/application.yml
```

`.env` needs three things:

| | |
|---|---|
| `DISCORD_TOKEN` | The bot token |
| `CIPHER_PASSWORD` | Any random string — `openssl rand -hex 24`. The node and yt-cipher both read it, and compose refuses to start without it |
| `LAVALINK_PASSWORD` | Change it from `youshallnotpass`, and set the same value as `server.password` in `application.yml` |

`application.yml` needs two edits before the first start:

| | |
|---|---|
| `remoteCipher.url` | `http://yt-cipher:8001`, with `password: "${CIPHER_PASSWORD}"` — the example ships this way. Do **not** leave it pointing at `cipher.kikkia.dev`: that instance is shared, rate limited to 10 req/s, and sees every player script your node asks about |
| `server.password` | Match `LAVALINK_PASSWORD` in `.env` |

Deezer stays `false` unless you fill in `masterDecryptionKey` and `arl` — LavaSrc
refuses to start otherwise and the node exits before binding a port. Spotify is
safe to leave blank; it degrades per request instead.

## Start it

```sh
mkdir -p lavalink/logs lavalink/plugins logs
sudo chown -R 322:322 lavalink/logs lavalink/plugins    # the node runs as uid 322

docker compose up -d
docker compose ps          # lavalink should reach (healthy)
docker compose logs -f bot
```

You are looking for these three lines:

```
Registered Lavalink node 'default-node' at lavalink:2333
Connected to Lavalink node 'default-node'
started successfully in approx 2 seconds
```

`restart: unless-stopped` plus `systemctl enable docker` means the stack comes
back after a reboot without you.

## Sizing the JVM

`_JAVA_OPTIONS=-Xmx2G` in `docker-compose.yml` is a ceiling, not a reservation —
but on a 2 GB box it invites the kernel's OOM killer. The node uses about 60 MB
of heap with a track playing, so on anything smaller than the CX22:

```yaml
- _JAVA_OPTIONS=-Xmx512m
```

## Updating

```sh
cd ~/alfred && git pull          # or rsync again
docker compose up -d --build bot
```

Only the bot is built from source; the node and yt-cipher are pinned images and
are not rebuilt. To move the node or cipher forward, change the tag or digest in
`docker-compose.yml` deliberately — both are pinned so that a `docker pull` cannot
move them underneath you.

## What to watch

| | |
|---|---|
| `docker compose logs -f` | Everything. The bot logs one line per track and one per command |
| `/stats` in Discord | Node uptime, players, memory, CPU. Owner-only |
| `/info` in Discord | What the node is running: version, plugins, sources |
| `docker stats --no-stream` | Whether the box is actually big enough |

**YouTube breaks on YouTube's schedule, not yours.** When playback stops working
across every track, the fix is upstream: a newer `youtube-plugin` version in
`application.yml`, or a poToken if the message is `sign in to confirm you're not
a bot` — that one is YouTube objecting to the VPS's IP address, which is a
likelier problem on a datacentre IP than it was on your home connection.
