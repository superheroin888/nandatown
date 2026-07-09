#!/usr/bin/env bash
# Opens the NANDA hackathon PR from the clean branch. Needs: gh auth login (once).
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
BR=hackathon/tvist-payments
gh auth status >/dev/null 2>&1 || gh auth login
gh repo fork projnanda/nandatown --remote --remote-name fork 2>/dev/null || true
git push -u fork "$BR"
# Body is read from the working branch so this script runs from any checkout.
BODY=$(mktemp)
git show hackathon/tvist-evidence-escrow:tvist-service/deploy/nanda-pr-body.md > "$BODY"
gh pr create --repo projnanda/nandatown --base main --head "$(gh api user -q .login):$BR" \
  --title "hackathon/tvist: regime-governed settlement-trust layer (payments)" \
  --body-file "$BODY"
rm -f "$BODY"
