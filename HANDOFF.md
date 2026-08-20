# Handoff

Working notes for picking this up cold. Not documentation — `docs/` and the code comments
are that. This is the context that would otherwise have to be re-derived.

Last updated: 2026-08-20.

## Where things stand

Alfred plays music. Speech was removed — the whole talking feature set (`/say`, `@Alfred`
mentions, the OpenRouter answerer, Flowery TTS) is out of the tree and the node's
`application.yml` no longer enables `flowerytts`. The bot is back to being a music bot:
8 commands in four extensions.

| | State |
|---|---|
| Play / search / queue / skip / remove / leave | Working |
| `/stats` / `/info` | Working |
| Hearing you | Not possible — see below |
| Speech / mentions / LLM answering | Removed 2026-08-20. `git log` has it all if it ever comes back |

`git revert` will not cleanly bring the speech work back (later non-speech commits touch
the same files); `git log --oneline 5d3dd6e..HEAD` names the speech commits if you ever
want them cherry-picked.

## Voice: what is settled, and why

Alfred **cannot hear**, and no amount of work on this codebase changes that. Established
over several rounds — do not re-litigate without new information:

- Discord gives a bot **one voice connection per guild**.
- Lavalink playback works by handing that connection to the node. Lavalink *is* the voice
  client.
- Voice receive requires the library to own the connection itself —
  `channel.connect(cls=VoiceRecvClient)`. One voice client per guild.
- Both want the same slot. A bot can play through Lavalink **or** hear. Not both.

Consequences that were checked and are not worth rechecking:

- **Rewriting on py-cord does not fix it.** py-cord + Lavalink is fine; py-cord + Lavalink +
  hearing is not. Same one-slot problem.
- **Dropping Lavalink for native audio would work** but loses the YouTube OAuth fix,
  Spotify/Deezer via LavaSrc and LavaSearch autocomplete — and puts YouTube resolution back
  on the VPS IP, which is exactly the `Sign in to confirm you're not a bot` failure that
  OAuth was adopted to solve.
- **Time-sharing the slot** (listen while idle, hand over to Lavalink to play) works, but the
  bot is deaf while music plays, and every handover is a visible leave-and-rejoin. Rejected:
  "skip" and "pause" by voice are the point, and those are exactly when it cannot hear.
- **A second bot user gets a second slot.** That is the only design that gets hearing without
  losing playback. A separate discord.py process with `discord-ext-voice-recv` (real-time
  per-packet `write()`, speaker attached; pycord's sinks buffer until recording stops, so
  they are the wrong shape for always-on listening).

## Facts worth not re-deriving

- **YouTube playback runs through OAuth**, not a poToken. `docs/deploy.md` covers the
  device flow; the refresh token lives in `lavalink/application.yml` (gitignored). A
  `Sign in to confirm you're not a bot` failure usually means the token expired or was
  revoked — rerun the flow.
- **`.env` and `lavalink/application.yml` are gitignored** and never arrive via `git pull`.
  A deploy that "did nothing" is usually this.
- **Local runs do not need Docker**: `scripts/lavalink.ps1` for the node, `uv run alfred` for
  the bot, with `LAVALINK_HOST=127.0.0.1`.

## Constraints to keep

- **Never** add a `Co-Authored-By: Claude` trailer to a commit. Global rule, all projects.
- **CI and the cron deploy were built and then deliberately removed** at the user's request —
  deploying is a documented manual step in `docs/deploy.md`. Do not reintroduce either
  without being asked again.
- `.env` holds the real Discord token. Never commit it, never print its contents; check
  variables exist by count, not by echoing.
- **Lavalink request logging stays off.** It writes Discord voice tokens to disk in plaintext.
- **The node's `127.0.0.1:2333` binding in `docker-compose.yml` is the actual protection**,
  not its password, which is deliberately left at the default. Never bind it publicly.
- **A Google OAuth refresh token for the YouTube burner account was pasted into chat** in an
  earlier session and should be treated as leaked. Revoking it was advised and never
  confirmed: myaccount.google.com → Security → third-party connections → remove the
  youtube-source entry, then rerun the device flow with `skipInitialization` commented out.
  **Check this is done.**

## Working notes

- Keep replies short and concrete. Long explanations get asked to be simpler.
- Explain before building anything sizeable — a plan was rejected mid-edit for going straight
  to code, and rightly.
- Verify rather than assert, and say which is which. Reverting a fix to watch the new test
  fail has caught real problems here and is expected, not ceremony.
- Where a claim decides days of work, check it first. The voice-receive finding landed *after*
  a rewrite had been agreed to, and invalidated it.