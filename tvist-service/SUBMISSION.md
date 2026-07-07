# NANDA Town skills-page submission — Tvist API

> Copy-paste package for https://nandatown.projectnanda.org (skills page).
> Before submitting: replace `https://deputy-increasingly-tutorial-contractors.trycloudflare.com` everywhere with the **permanent** URL
> (after `railway up` / `fly launch` / Render) — or, for a quick test, with the
> current sandbox tunnel printed by:
> `grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' ~/Library/Logs/tvist-tunnel.log | tail -1`

---

## Service name

**Tvist API — escrow, consent & dispute layer for AI agents**

## One-liner

An HTTP API for AI agents that send payments on someone's behalf. It provides,
in order of use: jurisdiction agreement over 22 real payment regimes (Nash
bargaining over both parties' rankings), consent enforcement (payments outside
the stored mandate are refused with 403 before funds move), delivery-gated
escrow (payee is paid only after the proof matches the agreed condition),
rule-gated recall (only where the region allows it and the mandate was
breached), disputes with the legal citation returned in the response, an x402
pay-per-request rail (402 → signed X-PAYMENT → receipt, replay-refused), and
machine-to-machine trade (budget-bounded delegation + one-call agent-to-agent
trade setup). One base URL, no authentication; browsers get an HTML page,
agents get JSON at the same URL.

## Live endpoint links

- Base / JSON index (agents) & animated homepage (humans): `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/`
- Health: `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/health` · Live metrics: `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/stats`
- SKILL.md (the agent contract): `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/skill.md`
- OpenAPI: `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/openapi.json` · Swagger: `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/docs`
- Jurisdictions: `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/regions` · Legal taxonomy: `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/taxonomy`
- x402 demo resource (402 flow): `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/x402/resource/market-report`

## SKILL.md

Hosted at `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/skill.md` (raw) / `https://deputy-increasingly-tutorial-contractors.trycloudflare.com/view/skill` (rendered).
Also in the repo: `tvist-service/SKILL.md`.

## 30-second proof for judges (copy-paste)

```bash
BASE=https://deputy-increasingly-tutorial-contractors.trycloudflare.com
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
  verbatim against the live URL; 57 tests pass (`pytest -q` in
  `tvist-service/`).

Disclaimer: technical demonstration — notional credits, not a bank; legal
citations are not legal advice.
