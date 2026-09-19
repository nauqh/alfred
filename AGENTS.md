# Repo Working Agreements

Working agreements for any agent in this repo, whichever tool you are: Claude
Code, Codex, Cursor, or something else.

This file is process: how to work, coordinate, and finish. It is deliberately
project-agnostic. The repo's own facts - its domain language, its commands, its
traps, its state of play - live in `CLAUDE.md`, the `README`, and whatever docs
the repo keeps. Read those too; find them before you start, do not assume this
file is all there is.

## Baseline workflow

Start every task by establishing:

1. **Goal and acceptance criteria.** What does done look like, concretely?
2. **Constraints.** Scope, reversibility, anything live that could be touched.
3. **What must be inspected.** The files, the routes, the tests, the real flow
   end to end. Read before you edit; understanding is never the part you skip.
4. **Who else is here.** Read `.agents/status/` (below) before touching a file.
5. **Whether the answer depends on live state.** Model ids, a running server's
   routes, a third-party response shape: verify, do not recall.

If requirements are ambiguous, ask a targeted question before making an
irreversible change. If they are ambiguous and the change is cheap and
reversible, pick the obvious default, do it, and say which default you took.

## Parallel sessions (REQUIRED)

Other agents may be working in this repo at the same time. Status files live in
`.agents/status/`, one per session. They are gitignored: live state, not
history. If the directory is missing, create it.

### Claiming your file

- If the user named your session, use that name.
- Otherwise name it after your task in kebab-case (`refresh-token-endpoint`,
  `checkout-retry`) and create `.agents/status/<name>.md`.
- If that file exists and is not yours, pick another name. Never adopt or
  overwrite someone else's file.
- A file whose `Updated:` is more than a day old is a dead session. You may take
  its name over.

### Protocol

- At the start of a task, read **every** file in `.agents/status/`.
- Before editing a file, check whether another session lists it under `Files:`.
  If it does, **don't edit it**. Tell the user and stop; do not negotiate with
  the other agent through the status files.
- Update your own file when you start a task, when you start touching new files,
  and when you make a decision others need (API shape, renamed function, new env
  var, new migration).
- **When the task is done, delete your status file, by name.** Hand what landed
  and anything the next session needs to the user in your final message, and
  put the durable record in the commit message. A finished task leaves no file
  behind; a file that lingers looks like a live claim on its `Files:`.
- Only ever write to your own status file. Deleting your own file is the one
  exception, and only the exact file you created.

### Format

```markdown
# backend
Tool: Codex
Status: working
Task: Add refresh token endpoint
Files: src/auth/token.ts, src/routes/auth.ts
Notes: /auth/login now returns { accessToken, refreshToken }
Updated: 2026-09-11 14:20
```

`Updated:` is a real timestamp, taken from the clock, not guessed.

`Status:` is one of:

| Status | Meaning | Are its `Files:` claimed? |
| --- | --- | --- |
| `working` | Actively editing right now. | Yes. Do not touch them. |
| `blocked` | Stopped, waiting on the user or on another session. Say what for in `Notes:`. | Yes. The work is unfinished and will resume. |

There is no `done` status: done means the file is deleted. A session that
finishes one task and picks up another deletes its file and starts a fresh one
named after the new task. Waiting on the user to review finished work is still
`blocked`, with `Notes:` saying what is ready.

## Writing style (REQUIRED)

- **No em dashes, no en dashes.** Use a plain hyphen `-`. This holds in code,
  comments, docstrings, commit messages, prompt text, UI copy, and everything
  you write to the user.
- The one exception is a dash that is *data*: a regex character class, or a test
  fixture that exists to match the character. Converting those breaks them.
- Match the density of the file you are in rather than importing your own.
- Prose you were not asked for is debt. A report, a walkthrough or per-phase
  notes the user asked for is not.

## Default autonomy and safety

Read-only exploration needs no permission. Writes are scoped to the repo. The
further a change reaches outside the working tree, the more explicit the ask
needs to be.

### Editing files

- Make the smallest change that actually solves the problem, **after** reading
  enough to know what it touches. A small diff in the wrong place is a second
  bug, not a win.
- Fix the root cause. Before changing a function, check its other callers: one
  guard in the shared function beats a guard per caller, and patching only the
  path the report names leaves every sibling still broken.
- Patch, don't rewrite. Whole-file rewrites hide the real change in the noise.
- No unrequested abstraction. No interface with one implementation, no config
  for a value that never changes, no scaffolding for later.
- Preserve the surrounding conventions rather than importing your own.

### Live services and remote APIs (REQUIRED)

Assume any configured credential points at something real: production data, a
published account, a paid API.

- **Read-only by default.** Listing, inspecting and diffing need no permission.
- **A write to a live service needs the user to have asked for that specific
  thing.** Publishing, sending, deleting, deploying, uploading: none of these
  are reversible in any way that matters once someone has seen the result.
- Approval for one write is not approval for the next one.
- Where a dry run exists, do that first and show what it would have done.

### Secrets and sensitive data

- Never print secrets. No dumping the environment, no echoing a token, no
  `cat` of a credentials file.
- Never write a secret into a status file, a doc, a test fixture or a commit.
- An exported session cookie is a live login, not a config file. Treat it as a
  credential and delete it once it has been used.
- Use secret values; do not display them. Redact when output must be shown.

### Destructive operations

- **Never delete by glob.** Delete the specific paths you created, by name. A
  filtered `rm` takes the user's files along with yours and gives no warning.
- Before deleting or overwriting anything you did not create, look at it. If
  what you find contradicts how it was described, surface that instead of
  proceeding.
- Say which you are doing before you do it: migrating, or dropping and
  reseeding.

### Git

- **Stage by filename. Never `git add -A`.** It sweeps the user's own
  uncommitted work into your commit.
- Ask before creating a branch. Commit and push only when asked.
- No `Co-Authored-By` or other AI-authorship trailers.
- Commit messages carry the evidence: what was measured, what failed, why the
  obvious alternative was rejected. They are the durable record; this file is
  not.
- The subject line is `type(scope): summary`
  ([Conventional Commits](https://www.conventionalcommits.org)):
  - `type` is one of `feat`, `fix`, `refactor`, `perf`, `test`, `docs`,
    `build`, `ci`, `chore`, `revert`.
  - `scope` is the area touched, one short lowercase word (`api`, `web`,
    `auth`, `logging`). Leave it out, `type: summary`, when no one area fits.
  - `summary` is imperative, lowercase, no trailing period, and the whole
    subject stays under 72 characters: `fix(auth): reject a blank api key`.
  - A breaking change adds `!` before the colon, `feat(api)!: ...`, and says
    what breaks in the body.
  - A blank line, then the body with the evidence above, wrapped at 72.

## Accuracy and verification

Prefer what the system tells you now over what you remember.

- **Ask the running process, not the source.** A route is real when the server
  serves it. A port belongs to whichever process actually holds it, which is not
  always the one you just started. Reading the file proves only what is on disk.
- **Pinned model ids and API versions rot silently**, and a provider's own list
  endpoint will still name ids that fail on use. Verify with a real call.
- For anything version-sensitive or recent, prefer the vendor's current docs
  over recall, and note the date of what you relied on.
- Never report a command you did not run or a result you did not see.

## Definition of done

A task is done when:

- the change is implemented, or the question is answered;
- the repo's checks have been **run**, not merely mentioned: tests, linter,
  typecheck, build, and any schema or migration check. The commands are in
  `CLAUDE.md` or the README; if you cannot find them, ask rather than skip;
- anything with a screen or an endpoint has been driven for real. A green suite
  is not a working screen;
- new warnings and errors are fixed, or explicitly listed as out of scope;
- the impact is stated: what changed, where, and why;
- anything deliberately left out is named as a follow-up;
- your status file is deleted, and the user got the summary of what landed.

If a check failed, say so and show the output. If you skipped one, say that too.
