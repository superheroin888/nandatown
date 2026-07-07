# GO-LIVE — MIT / NANDA hackathon, both tracks

Everything below is prepared; only the ☐ steps need you (they require your
accounts). Each is one command or one paste.

## Track A — nandatown plugin PR (charter: docs/hackathon/charter.md)

Branch **`hackathon/tvist-payments`** is ready: rebased onto current upstream
main (coexists with the merged escrow/bft/pareto/provenance PRs), plugin +
4 scenarios + 10 discriminating adversarial validators + problem brief 11,
**734 tests green**, ruff/format/pyright clean, deterministic, no new deps.

Charter compliance:
- [x] one problem, one layer (payments); branch name matches `hackathon/<handle>-<theme>`
- [x] plugin + scenario + mandatory adversarial validators (discriminate vs default)
- [x] deterministic (no wall-clock / unseeded RNG); pure-Python, existing deps only
- [x] docstrings with Example:: on every public symbol; PR description prepared
- [x] no out-of-scope file changes (service/pitch binaries are NOT on this branch)
- [x] no re-issued work — differentiation from the merged `escrow` plugin is
      stated up front in the PR body
- ☐ `gh auth login` (once), then: `./tvist-service/deploy/open-nanda-pr.sh`

## Track B — skills page ("build a service agents can use")

- [x] service built + 56 endpoint tests; SKILL.md verified agent-usable end-to-end
- [x] deploy configs: Dockerfile / Procfile / railway.json / render.yaml / fly.toml
- [x] SUBMISSION.md ready to paste (uses <BASE> placeholder)
- ☐ deploy (pick one, from tvist-service/):
      `railway init && railway up`   ·   `fly launch --now`   ·   Render: connect repo
- ☐ `./deploy/set-base-url.sh https://<your-app-url>`  (swaps URLs + smoke-tests)
- ☐ commit the swap, push the repo (or paste text), submit on the NANDA Town
      skills page: SUBMISSION.md content + live links

## While you wait

The sandbox stays live under launchd; current URL:
`grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' ~/Library/Logs/tvist-tunnel.log | tail -1`
