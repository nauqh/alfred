# Deploying to a VPS

Any provider that hands you root on a Debian or Ubuntu box works the same way —
this has been run on Hostinger and sized on Hetzner. The whole deploy is
`docker compose up -d`; everything before that is getting the machine and the
secrets into place.

## The machine

Sized against what the stack actually uses, idle:

| | |
|---|---|
| `alfred` | ~58 MB |
| `alfred-lavalink` | ~420 MB — the JVM is the whole cost |
| `alfred-cipher` | ~104 MB |

**4 GB is comfortable, 2 GB fits, 1 GB does not**, and 512 MB is not worth
attempting. Hostinger *KVM 1* (1 vCPU / 4 GB) and Hetzner *CX22* (2 vCPU / 4 GB)
both land around €4–5/month. One vCPU is enough: the node passes Opus through
rather than transcoding it, so the CPU only works when a filter is applied.

Pick the region nearest your Discord voice region. Take a **plain Debian 12 or
Ubuntu 24.04 image** — the templates bundling CyberPanel, Plesk or CloudPanel
install a web stack that claims ports 80 and 443 and adds users you did not ask
for.

Add your SSH public key at creation if the provider offers it. Where it does not
and a root password arrives instead — Hostinger works this way — get a key on
before anything else: a box with password login on port 22 starts getting
brute-forced within the hour.

## Firewall

**No inbound ports are needed. None.** The bot opens a websocket *out* to
Discord, and the node talks to the bot over Docker's internal network. Nothing
on the internet needs to reach this machine except your own SSH.

Set this in the provider's panel where there is one — Hetzner *Cloud Firewall*,
Hostinger *VPS → Security → Firewall* — since a rule applied outside the VM
still holds when the VM is misconfigured. Failing that, `ufw` on the box:

| Direction | Rule |
|---|---|
| Inbound | TCP 22, from your IP if it is static — otherwise from anywhere |
| Inbound | nothing else |
| Outbound | allow all |

Be clear-eyed about what this buys: with key-only SSH and nothing else listening,
a firewall allowing only port 22 blocks nothing that was open anyway. It earns
its place later, the day something gets exposed by accident. Confirm what is
actually listening instead of assuming:

```sh
sudo ss -tlnp        # want 22 on 0.0.0.0, 2333 on 127.0.0.1, nothing else public
```

**Add the SSH rule before attaching the rule set.** Hostinger creates every new
firewall with a drop-everything rule already in it, so attaching an empty one
takes SSH with it and costs a panel reset to undo.

`docker-compose.yml` binds the node to `127.0.0.1:2333` for this reason. Do not
change that to `2333:2333` on a public machine: it would expose a Lavalink node
whose password starts life as `youshallnotpass`, and an open node is a
stranger's streaming relay, billed to your bandwidth.

## The box, once

If the provider gave you a root password rather than taking a key, fix that from
your own machine first:

```sh
ssh-copy-id root@<ip>        # then confirm `ssh root@<ip>` needs no password
```

Then, on the server:

```sh
apt update && apt upgrade -y
curl -fsSL https://get.docker.com | sh           # Docker's own installer
systemctl enable docker                          # survives a reboot

adduser alfred                                   # prompts for a password, then Enter through
usermod -aG sudo,docker alfred                   # -aG appends; -G alone would replace
rsync --archive --chown=alfred:alfred ~/.ssh /home/alfred/   # carry the key over
```

`docker` group membership only attaches at login, so log in as `alfred` and check
`docker ps` answers before going on.

Then close the door in `/etc/ssh/sshd_config`:

```
PermitRootLogin no
PasswordAuthentication no
```

`systemctl restart ssh`, and **open a second terminal to confirm you can still
get in** before closing the first. Locking yourself out of a fresh VPS costs a
rebuild.

## The code

```sh
git clone https://github.com/nauqh/alfred.git ~/alfred
```

Nothing secret is in the repository, so a plain clone over HTTPS is enough — no
deploy key, no credentials on the box. `.env` and `lavalink/application.yml` are
both gitignored and so are never in a clone; they get created on the server in
the next step rather than copied up from a laptop.

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
| `LAVALINK_PASSWORD` | Whatever you like, as long as `server.password` in `application.yml` is the same string. The two not matching is the single most common way to end up with a node that starts, a bot that connects, and no audio |

Leaving `LAVALINK_PASSWORD` at `youshallnotpass` is defensible here — the node
listens on `127.0.0.1` only, so the sort of attacker who could try the password
already has a shell and could read `.env`. What protects that port is the loopback
binding, not the string. Which is why the binding is the line to guard.


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
cd ~/alfred && git pull
docker compose up -d --build bot
```

`git pull` alone changes nothing that runs: the source is baked into the image at
build time, not read off disk, so the container keeps serving the old code until
`--build` replaces it. Config is the other way round — `.env` needs only
`docker compose up -d`, and `lavalink/application.yml` is a bind mount, so
`docker compose restart lavalink` is enough.

Only the bot is built from source; the node and yt-cipher are pinned images and
are not rebuilt. To move the node or cipher forward, change the tag or digest in
`docker-compose.yml` deliberately — both are pinned so that a `docker pull` cannot
move them underneath you.

## Deploying on push

`scripts/deploy.sh` rebuilds the bot when a new commit lands on `main`. Install it
as a cron entry, as `alfred`:

```sh
chmod +x ~/alfred/scripts/deploy.sh
crontab -e
```

```cron
*/5 * * * * /usr/bin/flock -n /tmp/alfred-deploy.lock /home/alfred/alfred/scripts/deploy.sh >> /home/alfred/deploy.log 2>&1
```

`flock -n` drops the run rather than queueing it, so a build that outlasts the
five-minute interval is not joined by a second one part-way through.

This is deliberately pull-based. The alternative — GitHub Actions holding an SSH
key and connecting inward on every push — is faster to trigger and means a key
granting a shell on this machine lives in a public repository's secrets. The
server asking GitHub every five minutes needs no inbound port and no stored
credential, and its failure mode is that a deploy is late.

The lag is real: up to five minutes, and no way to trigger it from your laptop
except by waiting or running `scripts/deploy.sh` over SSH yourself.

What it will not do is deploy over a local edit — `git merge --ff-only` stops if
the checkout has diverged, on the grounds that a cron job at three in the morning
is the wrong thing to be resolving a merge.

## CI

`.github/workflows/ci.yml` runs `ruff check` and `pytest` on every push and pull
request. It matters more than usual here: the VPS follows `main` on a timer, so a
red commit on `main` is a broken bot within five minutes rather than whenever
someone next deploys.

## What to watch

| | |
|---|---|
| `docker compose logs -f` | Everything. The bot logs one line per track and one per command |
| `/stats` in Discord | Node uptime, players, memory, CPU. Owner-only |
| `/info` in Discord | What the node is running: version, plugins, sources |
| `docker stats --no-stream` | Whether the box is actually big enough |

**YouTube breaks on YouTube's schedule, not yours.** When playback stops working
across every track, the fix is upstream: usually a newer `youtube-plugin` version
in `application.yml`, sometimes the section below.

## YouTube on a datacentre IP

Expect this on the first deploy, having never seen it locally:

```
Client [TVHTML5_SIMPLY] failed: Sign in to confirm you're not a bot
Client [WEB] failed: This video requires login.
```

Nothing is misconfigured. A residential IP is shared with people watching YouTube
all day, so YouTube assumes a human; a VPS sits in a published datacentre range
where almost everything is a scraper, so it asks for proof. The range's reputation
was spent before the machine existed.

Read the log for which kind of failure it is. `Must find sig function from script`
is yt-cipher not working. `Sign in to confirm you're not a bot` and
`This video requires login` are an identity check, and no amount of configuration
below that line will help.

The fix is a poToken, generated **on the VPS** — the token vouches for a session
on the IP it was issued to:

```sh
docker run --rm quay.io/invidious/youtube-trusted-session-generator
```

Both printed values go in the `pot:` block of `lavalink/application.yml`, then
`docker compose restart lavalink`. No rebuild — the file is a bind mount.

It is not permanent. Tokens expire in days to weeks; regenerate when playback
dies again rather than hunting for a change. If that stops being enough, the
`oauth:` block below it authenticates as a real Google account, which works
across every client and lasts far longer, at the cost that upstream's own warning
is that termination is a possible outcome. Use an account you would not miss.

Beyond those two, the honest options get worse: a residential proxy through
`lavalink.server.httpConfig.proxyHost` is durable but bills per gigabyte, and
audio is measured in gigabytes. SoundCloud needs none of this and is already
enabled.
