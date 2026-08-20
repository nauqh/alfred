# Deploying to a VPS

Any Debian or Ubuntu box with root works — this has been run on Hostinger.
The deploy itself is `docker compose up -d`; everything before that is getting
the machine and secrets into place.

## Machine

| Service | Idle RAM |
|---|---|
| `alfred` | ~58 MB |
| `alfred-lavalink` | ~420 MB — the JVM is the whole cost |
| `alfred-cipher` | ~104 MB |

**4 GB is comfortable, 2 GB fits, 1 GB does not.** One vCPU is fine — the node
passes Opus through rather than transcoding. Take a **plain Debian 12 or Ubuntu
24.04 image**; templates bundling CyberPanel/Plesk claim ports 80 and 443.

On a 2 GB box, lower the JVM ceiling in `docker-compose.yml`:

```yaml
- _JAVA_OPTIONS=-Xmx512m
```

## Set up the box

From your machine:

```sh
ssh-copy-id root@<ip>
```

On the server:

```sh
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh
systemctl enable docker

adduser alfred
usermod -aG sudo,docker alfred
rsync --archive --chown=alfred:alfred ~/.ssh /home/alfred/
```

Log out and back in as `alfred` (group membership attaches at login) and confirm
`docker ps` answers. Then in `/etc/ssh/sshd_config`:

```
PermitRootLogin no
PasswordAuthentication no
```

`systemctl restart ssh`, then **confirm you can still get in from a second
terminal** before closing the first.

## Firewall

No inbound ports are needed — the bot opens a websocket *out* to Discord, and
the node talks to it over Docker's internal network. Check what's listening:

```sh
sudo ss -tlnp     # want 22 on 0.0.0.0, 2333 on 127.0.0.1, nothing else public
```

If you add a firewall (Hostinger: *VPS → Security → Firewall*), **allow TCP 22
first** — new rule sets are created with a drop-everything rule already in them.

`docker-compose.yml` binds the node to `127.0.0.1:2333`. Do not change that to
`2333:2333`: an open node is a stranger's streaming relay billed to your
bandwidth. The loopback binding is what protects it, not the password.

## Code

```sh
git clone https://github.com/nauqh/alfred.git ~/alfred
cd ~/alfred
cp .env.example .env
cp lavalink/application.yml.example lavalink/application.yml
```

`.env` and `lavalink/application.yml` are gitignored — they get created here,
never copied up from a laptop. `.env` needs three values:

| | |
|---|---|
| `DISCORD_TOKEN` | The bot token |
| `CIPHER_PASSWORD` | Any random string — `openssl rand -hex 24`. Read by both the node and yt-cipher; compose refuses to start without it |
| `LAVALINK_PASSWORD` | Anything, as long as `server.password` in `application.yml` is the same string |

Those two not matching is the most common way to end up with a node that starts,
a bot that connects, and no audio. Leaving both at `youshallnotpass` is fine.

`application.yml` ships ready except: running the node outside Docker,
`remoteCipher.url` must not point at the shared `cipher.kikkia.dev`. And Deezer
stays `false` unless you fill in `masterDecryptionKey` and `arl` — LavaSrc
refuses to start otherwise and the node exits before binding a port.

## Start

```sh
mkdir -p lavalink/logs lavalink/plugins logs
sudo chown -R 322:322 lavalink/logs lavalink/plugins    # the node runs as uid 322

docker compose up -d
docker compose ps          # lavalink should reach (healthy)
docker compose logs -f bot
```

Looking for:

```
Registered Lavalink node 'default-node' at lavalink:2333
Connected to Lavalink node 'default-node'
started successfully in approx 2 seconds
```

`restart: unless-stopped` plus `systemctl enable docker` brings the stack back
after a reboot without you.

## Update

Deploys are manual. After pushing a commit:

```sh
ssh alfred@<ip>
cd ~/alfred && git pull
docker compose up -d --build bot
```

`git pull` alone changes nothing that runs — the source is baked into the image
at build time. Config is the other way round:

| Changed | Command |
|---|---|
| Code | `git pull && docker compose up -d --build bot` |
| `.env` | `docker compose up -d` |
| `lavalink/application.yml` | `docker compose restart lavalink` — it is a bind mount |

Only the bot is built from source. The node and yt-cipher are pinned images;
move them forward by editing the tag or digest in `docker-compose.yml`
deliberately.

## YouTube on a datacentre IP

Expect this on the first deploy:

```
Client [TVHTML5_SIMPLY] failed: Sign in to confirm you're not a bot
Client [WEB] failed: This video requires login.
```

A VPS sits in a published datacentre range where almost everything is a scraper,
so YouTube asks for proof. Nothing is misconfigured.

Read the log for which failure it is. `Must find sig function from script` is
yt-cipher not working. The lines above are an identity check — no config below
that line helps.

The fix is OAuth in the `oauth:` block of `lavalink/application.yml` — not the
poToken every guide reaches for first: youtube-source's README says a poToken
"no longer bypasses the bot check for majority of cases". **Use a burner Google
account** — a terminated account is a possible outcome.

Uncomment `enabled` on its own, leaving the refresh token out:

```yaml
    oauth:
      enabled: true
```

```sh
docker compose restart lavalink
docker compose logs -f lavalink
```

The node prints a URL and a code. Enter them at `google.com/device`, sign in as
the burner, and the node prints a refresh token. Put it back:

```yaml
    oauth:
      enabled: true
      refreshToken: "<the token from the log>"
      skipInitialization: true
```

Restart once more — `skipInitialization` stops it asking on every start. The
refresh token belongs in this file (gitignored) and nowhere else. When YouTube
breaks again months from now, redo the device flow.

## What to watch

| | |
|---|---|
| `docker compose logs -f` | Everything. One line per track, one per command |
| `/stats` in Discord | Node uptime, players, memory, CPU. Owner-only |
| `/info` in Discord | Node version, plugins, sources |
| `docker stats --no-stream` | Whether the box is big enough |

`Authorization missing for 127.0.0.1 on GET /version` every ten seconds is the
healthcheck, which deliberately sends no password — a 401 still proves the node
is answering.