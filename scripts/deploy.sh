#!/bin/sh
# Rebuild the bot when a new commit lands on main. Installed as a cron entry on the
# VPS - see docs/deploy.md.
#
# Pull-based on purpose. Nothing on the internet needs to reach this machine, and
# GitHub is never handed a key that opens a shell here; the server asks GitHub, not
# the other way round. If GitHub is unreachable the deploy simply does not happen.
set -eu

cd "$(dirname "$0")/.."

git fetch --quiet origin main

have=$(git rev-parse HEAD)
want=$(git rev-parse origin/main)

# Silence is the normal case - this runs every five minutes and almost always has
# nothing to do. Printing anything here would bury the real deploys in the log.
if [ "$have" = "$want" ]; then
    exit 0
fi

echo "--- $(date -Is)  $have -> $want"

# --ff-only: a local edit that has diverged from main should stop the deploy and be
# looked at, not be quietly merged by a cron job at three in the morning.
git merge --ff-only origin/main

# Only the bot is built from source. The node and yt-cipher are pinned images and stay
# up, so playback stops for the bot's restart and nothing longer.
docker compose up -d --build bot
