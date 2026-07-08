# NANDA Town submission sheet — Tvist API

> **Deadline: Friday, July 10 · 12:00 PM ET.**
> Two places to submit — both prepared field-by-field below:
> **A.** Skills registry: https://nandatown.projectnanda.org/skills
> **B.** Contribution form: https://nandatown.projectnanda.org/onboarding/submit
>
> NANDA Town's own rules: "Must be reachable right now", "The URLs in your
> file have to be real and reachable", "Make sure your links open for anyone",
> and they recommend hosting on Railway / Vercel / Render / Fly.
> The current sandbox URL is a TryCloudflare tunnel and can rotate on restart —
> **deploy permanently first**, then run
> `./deploy/set-base-url.sh https://<permanent-url>` (swaps every URL below and
> smoke-tests the deployment). For a quick test the current tunnel is:
> `grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' ~/Library/Logs/tvist-tunnel.log | tail -1`

---

## A. Skills registry (nandatown.projectnanda.org/skills)

Copy each answer into the matching form field.

**Skill name**

```
Tvist API — escrow, consent & dispute layer for AI agents
```

**One-line description**

```
Escrow, consent enforcement, jurisdiction agreement (Nash bargaining over 22 real payment regimes), rule-gated recall, law-cited disputes, and x402 pay-per-request for AI agents that send payments — one no-auth HTTP API.
```

**Your name/team and email**

```
Maria Lindström · maria.aj.lindstrom@gmail.com
```

**GitHub username**

```
superheroin888
```

**SKILL.md** — pick "Hosted link" and give:

```
https://panels-ntsc-density-genesis.trycloudflare.com/skill.md
```

(Alternatives the form accepts: "GitHub repo" → link to `tvist-service/SKILL.md`
in your fork; or "Paste directly" → paste the contents of `tvist-service/SKILL.md`.)

**Live endpoint URLs (one per line)**

```
https://panels-ntsc-density-genesis.trycloudflare.com/health
https://panels-ntsc-density-genesis.trycloudflare.com/
https://panels-ntsc-density-genesis.trycloudflare.com/skill.md
https://panels-ntsc-density-genesis.trycloudflare.com/regions
https://panels-ntsc-density-genesis.trycloudflare.com/regions/suggest
https://panels-ntsc-density-genesis.trycloudflare.com/regions/recommend
https://panels-ntsc-density-genesis.trycloudflare.com/consent
https://panels-ntsc-density-genesis.trycloudflare.com/pay
https://panels-ntsc-density-genesis.trycloudflare.com/escrow
https://panels-ntsc-density-genesis.trycloudflare.com/recall
https://panels-ntsc-density-genesis.trycloudflare.com/dispute
https://panels-ntsc-density-genesis.trycloudflare.com/taxonomy
https://panels-ntsc-density-genesis.trycloudflare.com/x402/resource/market-report
https://panels-ntsc-density-genesis.trycloudflare.com/openapi.json
```

**Tags (optional)**

```
escrow, payments, disputes, consent, jurisdiction, x402, m2m
```

### A-alt. Register without the form (their documented API)

```bash
BASE=https://panels-ntsc-density-genesis.trycloudflare.com
curl -X POST https://nandatown.projectnanda.org/api/skills \
  -H 'content-type: application/json' \
  -d "{
    \"name\": \"Tvist API — escrow, consent & dispute layer for AI agents\",
    \"source_type\": \"url\",
    \"source_url\": \"$BASE/skill.md\",
    \"endpoints\": \"GET $BASE/health\nGET $BASE/regions\nPOST $BASE/regions/recommend\nPOST $BASE/consent\nPOST $BASE/pay\nPOST $BASE/escrow\nPOST $BASE/recall\nPOST $BASE/dispute\nGET $BASE/x402/resource/market-report\"
  }"
```

---

## B. Contribution form (nandatown.projectnanda.org/onboarding/submit)

**Contributor type**: `Individual`

**Submission type**: `Code` ("A GitHub repo, pull request, or service + SkillMD")
— this submission is both: a plugin PR to the nandatown repo **and** a live
service + SkillMD.

**Project or module name**

```
Tvist — escrow, consent & dispute layer for AI agents (payments layer)
```

**Your name, team, or company**

```
Maria Lindström
```

**One-paragraph description**

```
An HTTP API for AI agents that send payments on someone's behalf. It provides, in order of use: jurisdiction agreement over 22 real payment regimes (Nash bargaining over both parties' rankings), consent enforcement (payments outside the stored mandate are refused with 403 before funds move), delivery-gated escrow (payee is paid only after the proof matches the agreed condition), rule-gated recall (only where the region allows it and the mandate was breached), disputes with the legal citation returned in the response, an x402 pay-per-request rail (402 → signed X-PAYMENT → receipt, replay-refused), and machine-to-machine trade (budget-bounded delegation + one-call agent-to-agent trade setup). The same logic ships as a `payments` plugin for the nandatown rig with 4 swarm scenarios and 10 adversarial validators that pass on a plain ledger and are blocked by Tvist on identical scenarios. One base URL, no authentication; browsers get an interactive page, agents get JSON at the same URL.
```

**GitHub repo or pull request URL** (required for code)

```
https://github.com/projnanda/nandatown/pull/93
```

(Their guideline "a repo with a SKILL.md at the root is ideal": the SKILL.md is
hosted live at `<base-url>/skill.md` and in-repo at `tvist-service/SKILL.md`.
The full Phase-2 service diff is reviewable at
https://github.com/superheroin888/nandatown/pull/1.)

**Live demo URL** ("Must be reachable right now")

```
https://panels-ntsc-density-genesis.trycloudflare.com
```

**Live endpoints agents can call (one per line)** — same list as section A.

**Tags**: same as section A.

---

## 30-second proof for judges (copy-paste)

```bash
BASE=https://panels-ntsc-density-genesis.trycloudflare.com
# Nash-optimal jurisdiction for two parties who want different things
curl -s -X POST $BASE/regions/recommend -H 'content-type: application/json' \
  -d '{"client_prefs":["eu_sepa","br_pix","in_upi"],"agent_prefs":["in_upi","br_pix","eu_sepa"]}'
# consent cap: 900 vs a 500 mandate -> 403 before funds move
curl -s -X POST $BASE/consent -H 'content-type: application/json' -d '{"consent_id":"c1","principal":"alice","budget":500}'
curl -s -X POST $BASE/pay -H 'content-type: application/json' \
  -d '{"ref":"p2","from_account":"alice","to_account":"shop","amount":900,"region":"br_pix","consent_id":"c1"}'
# escrow: release refused until delivery proof lands
curl -s -X POST $BASE/escrow -H 'content-type: application/json' \
  -d '{"escrow_id":"e1","payer":"alice","payee":"airline","amount":400,"region":"in_upi","condition_expected":"ticket_issued"}'
curl -s -X POST $BASE/escrow/e1/release          # 403
curl -s -X POST $BASE/escrow/e1/deliver -H 'content-type: application/json' -d '{"proof":"ticket_issued"}'
curl -s -X POST $BASE/escrow/e1/release          # RELEASED
# law-grounded dispute: accepted case returns the citation inline
curl -s -X POST $BASE/dispute -H 'content-type: application/json' \
  -d '{"ref":"e1","region":"in_upi","reason_code":"goods_not_received"}'
```

## Scoring-criteria mapping

- **Useful** — five checks a paying agent needs and cannot get from a plain
  transfer call: jurisdiction agreement, consent enforcement, escrow, recall,
  dispute validation; plus x402 pay-per-request.
- **Creative** — jurisdiction chosen by Nash bargaining over 22 real payment
  regimes; every dispute reason code mapped to civil/commercial law with links
  to official sources and the citation returned in the response; the consent
  budget checked even on the irrevocable x402 rail.
- **Easy to set up** — no auth, no keys. The first working call is one curl.
  `GET /` and `GET /openapi.json` describe every endpoint.
- **Agents succeed from SKILL.md alone** — every curl block in SKILL.md runs
  verbatim against the live URL; 61 tests pass (`pytest -q` in
  `tvist-service/`).

Disclaimer: technical demonstration — notional credits, not a bank; legal
citations are not legal advice.
