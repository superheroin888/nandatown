#!/usr/bin/env bash
# Keep the sandbox tunnel URL in sync across SKILL.md/README/SUBMISSION.md and
# push to GitHub (fork branch + tvist-api repo). Run periodically by launchd
# (ai.tvist.urlsync); exits silently when nothing changed.
set -euo pipefail
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
SVC=/Users/storvdn/nandatown-src/tvist-service
API_REPO="$HOME/tvist-api"
cd "$SVC"

URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$HOME/Library/Logs/tvist-tunnel.log" | tail -1)
[ -n "$URL" ] || exit 0
CUR=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' SKILL.md | head -1)
[ "$URL" = "$CUR" ] && exit 0

# only swap to a URL that is actually serving
code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$URL/health" || true)
[ "$code" = "200" ] || exit 0

echo "$(date '+%F %T') tunnel rotated: $CUR -> $URL"
./deploy/set-base-url.sh "$URL"

cd /Users/storvdn/nandatown-src
git add tvist-service/SKILL.md tvist-service/README.md tvist-service/SUBMISSION.md
if git commit -q -m "submission: sync sandbox URL after tunnel rotation (auto)"; then
  git push fork hackathon/tvist-evidence-escrow
fi

if [ -d "$API_REPO/.git" ]; then
  cp tvist-service/SKILL.md tvist-service/README.md tvist-service/SUBMISSION.md "$API_REPO/"
  cd "$API_REPO"
  git add SKILL.md README.md SUBMISSION.md
  if git commit -q -m "sync sandbox URL after tunnel rotation (auto)"; then
    git push origin main
  fi
fi
echo "$(date '+%F %T') sync complete: $URL"
