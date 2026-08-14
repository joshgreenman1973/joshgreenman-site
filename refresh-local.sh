#!/bin/zsh
#
# The local half of the refresh, run daily by launchd
# (~/Library/LaunchAgents/com.josh.joshgreenman-site-refresh.plist).
#
# The GitHub Action handles Vital City and the experiments on its own, but
# Substack answers 403 to GitHub's runners, so the only place the Substack
# archive can actually be read is a normal machine. This run refreshes
# data/substack-cache.json, which the cloud job then reads.
#
# Log: ~/Library/Logs/joshgreenman-site-refresh.log

set -e
export PATH=/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin

REPO=/Users/joshgreenman/Experiments/josh-greenman-site
cd "$REPO"

echo "=== $(date '+%Y-%m-%d %H:%M:%S') ==="

# Take whatever the cloud job committed overnight; keep any local edits.
git pull --rebase --autostash --quiet origin main

python3 build.py

if [ -z "$(git status --porcelain -- index.html data/substack-cache.json)" ]; then
  echo "No change."
  exit 0
fi

git add index.html data/substack-cache.json
git commit -q -m "Refresh latest writing and experiments (local)"
git push -q origin main
echo "Pushed."
