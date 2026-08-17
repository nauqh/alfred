# Handoff

Working notes for picking this up cold. Not documentation — `docs/` and the code comments
are that. This is the context that would otherwise have to be re-derived.

Last updated: 2026-08-17.

## Where things stand

Alfred plays music, and he talks. Both work.

| | State |
|---|---|
| Play / search / queue / skip | Working |
| `/say` — speak a line aloud | Working |
| `@Alfred <text>` — speak, or `play …` / `skip` | Working |
| Tagging Alfred's **role** instead of his user | Fixed, unconfirmed in a live server |
| Hearing you | Not possible on this bot — see below |
| Understanding loose phrasing | Not built — he string-matches |

## Uncommitted right now

`alfred/extensions/mention.py` and `tests/test_mention.py` — the role-mention fix. 129 tests
pass, ruff clean. Not committed.

## The role-mention fix, and what is still unknown

**The bug**: `on_mention` only checked `user_mentions_ids`. Discord's mention picker starts
offering the bot's *managed role* once the bot has been tagged once, and a role tag lands in
`role_mention_ids` — a different field — so every tag after the first fell through the
"not mentioned" path in silence.

**The fix**: match role mentions too, strip `<@&id>` from the text, and ignore
`@everyone`/`@here` deliberately.

**The genuinely unresolved part**: Discord has never documented whether a mention of a *role
the app holds* qualifies for the MESSAGE_CONTENT exemption the way a mention of the app
itself does. Their own announcement thread punts the question to Developer Support. So the
code does not bet on it — if a message is known to tag the bot but arrives with `content`
blank, that is read as "the text was withheld" and answered with a hint to tag directly.
Correct under either answer.

**Still worth confirming in a live server**: tag the role, see which branch fires. If the
text comes through, the exemption covers role mentions and the hint is dead code worth
keeping anyway. If the hint appears, it does not.

**Do not remove the REST fallback in `_my_role_ids`.** The bot runs without the members
intent. If the member cache turns out not to hold even the bot's own member, dropping the
fallback puts the listener straight back to ignoring every role mention — the original bug.
It is memoised, so it costs at most one request per guild for the life of the process.

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
  Spotify/Deezer via LavaSrc, LavaSearch autocomplete and Flowery TTS — and puts YouTube
  resolution back on the VPS IP, which is exactly the `Sign in to confirm you're not a bot`
  failure that OAuth was adopted to solve.
- **Time-sharing the slot** (listen while idle, hand over to Lavalink to play) works, but the
  bot is deaf while music plays, and every handover is a visible leave-and-rejoin. Rejected:
  "skip" and "pause" by voice are the point, and those are exactly when it cannot hear.
- **A second bot user gets a second slot.** That is the only design that gets hearing without
  losing playback. Alfred would not need changing at all — a separate discord.py process with
  `discord-ext-voice-recv` (real-time per-packet `write()`, speaker attached; pycord's sinks
  buffer until recording stops, so they are the wrong shape for always-on listening).

An ears-bot spike was planned and then abandoned before any code was written. Nothing from it
is in the tree.

## Offered, not built

- **An LLM brain for `mention.py`.** `_handle` currently string-matches: `play …` and exactly
  `skip`/`next`, everything else parroted aloud. So `@Alfred put on some jazz` makes him *say*
  "put on some jazz". Replacing that middle step with Claude tool-use (tools: play / skip /
  say) is contained to one function, needs no second bot and no voice receive, and is the
  single biggest gain available. Roughly ½¢ per mention; needs an Anthropic API key.
  Load the `claude-api` skill before starting — do not write the call from memory.
- Interrupt-and-resume so speech can cut in over music instead of being refused.
- Dockerfile layer split so dependency installs cache separately from source changes.

## Facts worth not re-deriving

- **Flowery TTS requires a User-Agent.** `curl/8`, bare `Lavalink` and an empty UA all get a
  403 with a JSON body. Lavaplayer's default passes, so nothing in the code handles this —
  but it will look baffling when debugging by hand.
- **`audioFormat: ogg_opus` is broken with Flowery.** Served chunked with no `Content-Length`,
  which lavaplayer's Ogg parser cannot read — fails in `OggPacketInputStream.readPageHeader`.
  Use `mp3`, which is LavaSrc's own default.
- **Flowery tracks report `Long.MAX_VALUE` as their duration.** Handled in two places, both
  load-bearing: `formatting.UNKNOWN_DURATION` (else it renders as 106751991167300 days), and
  the guard in `service.speak`, which checks `current.source_name != SPEECH_SOURCE` rather
  than `player.is_playing` — the node treats these tracks as unbounded and leaves `current`
  set after the audio finishes, so gating on `is_playing` let the first spoken line block
  every line after it, permanently.
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
