# Deploying to a VPS

Any provider that hands you root on a Debian or Ubuntu box works the same way —
this has been run on Hostinger. The deploy itself is `docker compose up -d`;
everything before that is getting the machine and the secrets into place.

## The machine

Idle usage, measured:

| | |
|---|---|
| `alfred` | ~58 MB |
| `alfred-lavalink` | ~420 MB — the JVM is the whole cost |
| `alfred-cipher` | ~104 MB |

**4 GB is comfortable, 2 GB fits, 1 GB does not.** Hostinger *KVM 1* is €5/month
and enough. One vCPU is fine — the node passes Opus through rather than
transcoding, so the CPU only works when a filter is applied.

Take a **plain Debian 12 or Ubuntu 24.04 image**. The templates bundling
CyberPanel or Plesk install a web stack that claims ports 80 and 443.

On a 2 GB box, lower the JVM ceiling in `docker-compose.yml` — `-Xmx2G` invites
the OOM killer, and the node uses about 60 MB of heap while playing:

```yaml
- _JAVA_OPTIONS=-Xmx512m
```

## Set up the box

Hostinger hands you a root password rather than taking a key. Fix that first,
from your own machine:

```sh
ssh-copy-id root@<ip>        # then check `ssh root@<ip>` needs no password
```

Then on the server:

```sh
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh           # Docker's own installer
systemctl enable docker                          # survives a reboot

adduser alfred                                   # prompts for a password
usermod -aG sudo,docker alfred                   # -aG appends; -G alone replaces
rsync --archive --chown=alfred:alfred ~/.ssh /home/alfred/   # carry the key over
```

Group membership only attaches at login, so log in as `alfred` and check
`docker ps` answers before going on.

Then close the door in `/etc/ssh/sshd_config`:

```
PermitRootLogin no
PasswordAuthentication no
```

`systemctl restart ssh`, then **open a second terminal and confirm you can still
get in** before closing the first. Locking yourself out costs a rebuild.

## Firewall

**No inbound ports are needed.** The bot opens a websocket *out* to Discord, and
the node talks to it over Docker's internal network. Only your SSH comes in.

With key-only SSH and nothing else listening, a firewall allowing port 22 blocks
nothing that was open anyway — it earns its place the day something gets exposed
by accident. Check what is actually listening:

```sh
sudo ss -tlnp     # want 22 on 0.0.0.0, 2333 on 127.0.0.1, nothing else public
```

If you add one (Hostinger: *VPS → Security → Firewall*), **allow TCP 22 before
attaching it**. New rule sets are created with a drop-everything rule already in
them, so attaching an empty one takes SSH with it.

`docker-compose.yml` binds the node to `127.0.0.1:2333`. Do not change that to
`2333:2333` — it would put a Lavalink node on the public internet, and an open
node is a stranger's streaming relay billed to your bandwidth.

## The code

```sh
git clone https://github.com/nauqh/alfred.git ~/alfred
cd ~/alfred
cp .env.example .env
cp lavalink/application.yml.example lavalink/application.yml
```

Nothing secret is in the repository, so a plain HTTPS clone is enough. `.env` and
`lavalink/application.yml` are gitignored and never arrive in a clone — they get
created here, not copied up from a laptop.

`.env` needs three values:

| | |
|---|---|
| `DISCORD_TOKEN` | The bot token |
| `CIPHER_PASSWORD` | Any random string — `openssl rand -hex 24`. Both the node and yt-cipher read it, and compose refuses to start without it |
| `LAVALINK_PASSWORD` | Anything, as long as `server.password` in `application.yml` is the same string |

Those two not matching is the most common way to end up with a node that starts,
a bot that connects, and no audio. Leaving both at `youshallnotpass` is fine: the
node listens on `127.0.0.1` only, so anyone who could try the password already
has a shell and could read `.env`. The loopback binding is what protects it.

`application.yml` ships ready except for one thing — if you run the node outside
Docker, `remoteCipher.url` must not be left pointing at `cipher.kikkia.dev`. That
instance is shared, rate limited to 10 req/s, and sees every player script your
node asks about.

Deezer stays `false` unless you fill in `masterDecryptionKey` and `arl` — LavaSrc
refuses to start otherwise and the node exits before binding a port.

## Start it

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

## Updating

Deploys are manual. After pushing a commit:

```sh
ssh alfred@<ip>
cd ~/alfred && git pull
docker compose up -d --build bot
```

`git pull` alone changes nothing that runs — the source is baked into the image
at build time, not read off disk, so the container serves the old code until
`--build` replaces it. Config is the other way round:

| Changed | Command |
|---|---|
| Code | `git pull && docker compose up -d --build bot` |
| `.env` | `docker compose up -d` |
| `lavalink/application.yml` | `docker compose restart lavalink` — it is a bind mount |

Only the bot is built from source. The node and yt-cipher are pinned images; move
them forward by editing the tag or digest in `docker-compose.yml` deliberately.

## YouTube on a datacentre IP

Expect this on the first deploy, having never seen it locally:

```
Client [TVHTML5_SIMPLY] failed: Sign in to confirm you're not a bot
Client [WEB] failed: This video requires login.
```

Nothing is misconfigured. A residential IP is shared with people watching YouTube
all day, so YouTube assumes a human. A VPS sits in a published datacentre range
where almost everything is a scraper, so it asks for proof — and the range's
reputation was spent before your machine existed.

Read the log for which failure it is. `Must find sig function from script` is
yt-cipher not working. `Sign in to confirm you're not a bot` and `This video
requires login` are an identity check, and no configuration below that line helps.

The fix is OAuth, in the `oauth:` block of `lavalink/application.yml`. Not the
poToken every guide reaches for first: youtube-source's README now says a poToken
"no longer bypasses the bot check for majority of cases", and the generator those
guides link is deprecated and dies with `timeout waiting for outgoing API request`.

**Use a burner Google account.** Upstream's warning is that a terminated account
is a possible outcome. This borrows an account's standing to pass a check aimed at
scrapers; it does not authenticate your bot.

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
the burner, and the node prints a refresh token. Put it back in the file:

```yaml
    oauth:
      enabled: true
      refreshToken: "<the token from the log>"
      skipInitialization: true
```

Restart once more. `skipInitialization` stops it asking on every start. The
refresh token is a credential for that account — it belongs in this file, which is
gitignored, and nowhere else.

OAuth tokens last far longer than poTokens but not forever. When YouTube breaks
again months from now, redo the device flow before hunting for what changed.

## What to watch

| | |
|---|---|
| `docker compose logs -f` | Everything. One line per track, one per command |
| `/stats` in Discord | Node uptime, players, memory, CPU. Owner-only |
| `/info` in Discord | Node version, plugins, sources |
| `docker stats --no-stream` | Whether the box is big enough |

`Authorization missing for 127.0.0.1 on GET /version` every ten seconds is the
healthcheck, which deliberately sends no password — a 401 still proves the node is
answering, which is all the check needs to know.
