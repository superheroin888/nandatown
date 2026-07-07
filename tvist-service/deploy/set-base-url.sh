#!/usr/bin/env bash
# After deploying (railway/fly/render), run:  ./set-base-url.sh https://your-app.up.railway.app
# Replaces the base URL across SKILL.md / README.md / SUBMISSION.md and smoke-tests the deployment.
set -euo pipefail
NEW="${1:?usage: set-base-url.sh <new-base-url>}"
NEW="${NEW%/}"
cd "$(dirname "$0")/.."
OLD=$(grep -oE 'https://[a-z0-9.-]+[a-z0-9]' SKILL.md | head -1)
echo "swapping: $OLD -> $NEW"
for f in SKILL.md README.md SUBMISSION.md; do
  sed -i '' "s|$OLD|$NEW|g; s|<BASE>|$NEW|g" "$f"
done
echo "--- smoke test ---"
fail=0
check(){ code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$1" 2>/dev/null || true)
  code="${code:0:3}"; [ -n "$code" ] || code=000
  if [ "$code" = "$2" ]; then echo "ok  $2 $1"; else echo "BAD $code (want $2) $1"; fail=1; fi; }
check "$NEW/health" 200
check "$NEW/skill.md" 200
check "$NEW/spectrum" 200
check "$NEW/taxonomy" 200
check "$NEW/downloads" 200
check "$NEW/download/brief-pdf" 200
check "$NEW/x402/resource/market-report" 402
(curl -s -H 'accept: text/html' --max-time 15 "$NEW/" || true) | grep -q "payments made by AI agents" \
  && echo "ok  homepage" || { echo "BAD homepage"; fail=1; }
[ $fail = 0 ] && echo "ALL GREEN — commit the URL swap, then submit SUBMISSION.md" || exit 1
