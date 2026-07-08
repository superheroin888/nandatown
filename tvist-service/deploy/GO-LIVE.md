# GO-LIVE — MIT / NANDA hackathon, both tracks

> **Deadline: Friday, July 10 · 12:00 PM ET** (nandatown.projectnanda.org).
> Finale: Saturday, July 11 at MIT Media Lab (optional, in person).

Everything below is prepared; only the ☐ steps need you (they require your
accounts). Each is one command or one paste.

## Track A — nandatown plugin PR (charter: docs/hackathon/charter.md)

Branch **`hackathon/tvist-payments`** is ready: rebased onto upstream main
as of **2026-07-08** (clean rebase, coexists with all merged hackathon PRs
including #41 EMPIC escrow), plugin + 4 scenarios + 10 discriminating
adversarial validators + problem brief 11, **821 tests green at rebase**,
ruff/format/pyright clean, scenario reproduce block re-verified,
deterministic, no new deps.

Charter compliance:
- [x] one problem, one layer (payments); branch name matches `hackathon/<handle>-<theme>`
- [x] plugin + scenario + mandatory adversarial validators (discriminate vs default)
- [x] deterministic (no wall-clock / unseeded RNG); pure-Python, existing deps only
- [x] docstrings with Example:: on every public symbol; PR description prepared
- [x] no out-of-scope file changes (service/pitch binaries are NOT on this branch)
- [x] no re-issued work — differentiation from the merged `escrow` plugin is
      stated up front in the PR body
- ☐ `gh auth login` (once), then: `./tvist-service/deploy/open-nanda-pr.sh`
- ☐ paste the PR URL into SUBMISSION.md section B ("GitHub repo or pull
      request URL"), then submit the contribution form (step 3 below).

## Track B — skills registry + contribution form

NANDA Town requirements (their words): live demo "Must be reachable right
now"; "The URLs in your file have to be real and reachable"; "Make sure your
links open for anyone"; recommended hosts: Railway / Vercel / Render / Fly.
A TryCloudflare tunnel rotates on restart — submit a permanent URL.

- [x] service built — 33 endpoints, 61 endpoint tests green; SKILL.md verified
      agent-usable end-to-end and matches their SkillMD format (name +
      description, base URL, endpoint list, example calls with expected
      responses, step-by-step usage, rules)
- [x] deploy configs: Dockerfile / Procfile / railway.json / render.yaml / fly.toml
- [x] SUBMISSION.md = exact fill-in sheet for both forms (field names verbatim,
      answers prepared), plus their documented no-form API POST alternative
- ☐ 1. log in once, then deploy (both CLIs are already installed):
      Railway (no card needed for trial):
        `railway login`   (browser opens — approve)
        `cd ~/nandatown-src/tvist-service && railway init --name tvist-api && railway up`
      or Fly (asks for payment info on new accounts):
        `fly auth login`
        `cd ~/nandatown-src/tvist-service && fly launch --now --copy-config --yes`
      or Render: connect the repo in the dashboard (render.yaml is picked up)
- ☐ 2. `./deploy/set-base-url.sh https://<permanent-url>`
      (swaps every URL in SKILL.md / README.md / SUBMISSION.md + smoke-tests;
      commit the swap)
- ☐ 3. submit, copying from SUBMISSION.md:
      - skills registry: https://nandatown.projectnanda.org/skills
        (section A — or the API POST in section A-alt)
      - contribution form: https://nandatown.projectnanda.org/onboarding/submit
        (section B; needs the Track-A PR URL for the repo field)

## While you wait

The sandbox stays live under launchd; current URL:
`grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' ~/Library/Logs/tvist-tunnel.log | tail -1`
If it rotates before you deploy permanently, re-run
`./deploy/set-base-url.sh "$(that command)"`.
