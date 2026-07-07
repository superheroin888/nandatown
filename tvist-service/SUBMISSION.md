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

When an AI agent spends money on someone's behalf over instant, irrevocable
rails, Tvist is the missing recourse layer: game-theoretically negotiated
jurisdiction (22 real regimes), consent-capped payments, delivery-gated escrow,
proof-gated recall, law-grounded disputes with inline citations, a native
x402 pay rail, and machine-to-machine trade (attenuated delegation chains +
one-call agent↔agent pacts) — all behind one no-auth, dual-use URL.

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

- **Useful** — the pre/post-transaction checks every spending agent needs:
  jurisdiction, consent, escrow, recall, disputes; plus x402 as the native
  agent pay flow.
- **Creative** — Nash-bargaining jurisdiction selection over 22 real rails;
  disputes grounded in civil/commercial law with official-source links and
  inline citations; the consent cap enforced even on the irrevocable x402 rail.
- **Easy to set up** — no auth, no keys; one curl to a working call; `GET /`
  and `/openapi.json` self-describe everything.
- **Agents succeed from SKILL.md alone** — the worked example in SKILL.md runs
  verbatim (verified end-to-end); 49 endpoint tests green.

Disclaimer: technical demonstration — notional credits, not a bank; legal
citations are not legal advice.
