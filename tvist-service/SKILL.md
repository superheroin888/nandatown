# Tvist API

Escrow, consent enforcement, jurisdiction agreement, recall, and law-cited
disputes for AI agents that send payments — one no-auth HTTP API.

Base URL:

https://tvist-api-mias-projects-667d1349.vercel.app

All request and response bodies are JSON. Errors return `{"error": "<what
failed>"}` with a 4xx status code. Sandbox: balances are notional credits
(accounts start at 100000 on first use); no auth, no keys, no signup. The same
base URL serves humans (HTML page) and agents (JSON) — the API is identical.
Not legal advice: legal references cite real primary sources but are
engineering mappings (`GET /disclaimer`).

## Endpoints

Every endpoint below shows one real call and the real response it returned.
IDs (`c-ex`, `e-ex`, ...) must be unique per object — reusing one returns 409;
replace them with your own.

### GET /health

Liveness check.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/health
```

Example response:

```json
{"status": "ok"}
```

### GET /

Machine-readable index of every endpoint (browsers get an HTML page at the same URL).

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/
```

Example response:

```json
{"service": "Tvist API", "what": "Escrow, consent, and dispute layer for AI agents. Notional credits (sandbox).", "skill": "See SKILL.md. OpenAPI at /openapi.json, interactive docs at /docs."}
```

### GET /stats

Live service counters.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/stats
```

Example response:

```json
{"accounts": 12, "consents": 6, "settlements": 5, "x402_settlements": 2, "recalled": 1, "escrows": {"total": 4, "RELEASED": 2, "REFUNDED": 1, "FUNDED": 1}, "held_credits": 150, "disputes": 1, "delegations": 1, "pacts": 1, "total_funds": 1200000, "regions": 22, "endpoints": 33}
```

### GET /regions

All 22 jurisdictions with their dispute regimes: irrevocability, recall rules, valid reason codes.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/regions
```

Example response:

```json
{"count": 22, "regions": {"global": {"label": "Ungoverned (permissive default)", "rail": "generic", "irrevocable": true, "recall_allowed": true, "recall_window_ticks": 0, "reason_codes": ["agent_exceeded_mandate", "fraud", "goods_not_received", "mistaken_payment", "not_as_described", "pix_med_return", "recall_request", "recurring_disputed ...}
```

### GET /regions/suggest?tz={IANA-timezone}

Suggested starting jurisdiction from the caller's timezone and Accept-Language; the IP is echoed, not geolocated.

```bash
curl -s 'https://tvist-api-mias-projects-667d1349.vercel.app/regions/suggest?tz=Asia/Kolkata'
```

Example response:

```json
{"suggested_region": "in_upi", "label": "India - UPI (NPCI dispute flows)", "method": "timezone 'Asia/Kolkata'", "client_ip": "127.0.0.1", "signals": {"timezone": "Asia/Kolkata", "accept_language": null}}
```

### POST /regions/recommend

The Nash-optimal jurisdiction for two ranked preference lists; `agreed_region: null` means no shared region — do not transact.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/regions/recommend -H 'content-type: application/json' \
  -d '{"client_prefs":["eu_sepa","br_pix","in_upi"],"agent_prefs":["in_upi","br_pix","eu_sepa"]}'
```

Example response:

```json
{"agreed_region": "br_pix", "method": "nash_bargaining", "naive_client_first": "eu_sepa", "regime": {"label": "Brazil - Pix (MED 2.0, 11-day recovery)", "irrevocable": true, "recall_allowed": true, "recall_window_ticks": 11}, "note": "None means the parties share no acceptable region \u2014 do not transact."}
```

### GET /taxonomy

The dispute taxonomy: 7 legal categories and the mapping from every reason code to its category.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/taxonomy
```

Example response:

```json
{"categories": {"non_performance": {"label": "Non-performance (non-delivery)", "description": "Seller/provider failed to perform the primary obligation.", "civil_law_basis": "Breach of obligation to perform: BGB \u00a7\u00a7275, 323 (DE); Code civil arts. 1217, 1610 (FR); CISG arts. 30, 45, 49.", "c ...}
```

### GET /regions/{region}/legal

One jurisdiction's legal system, regulator, statutes and rulebooks (official-source links), and the legal basis per reason code.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/regions/in_upi/legal
```

Example response:

```json
{"region": "in_upi", "label": "India - UPI (NPCI dispute flows)", "rail": "upi", "legal_system": "common law", "regulator": "RBI / NPCI"}
```

### GET /spectrum

The four payment relationships and their checks as JSON, ASCII, and Mermaid.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/spectrum
```

Example response:

```json
{"one_gate_logic": ["1 jurisdiction \u2014 Nash-optimal region, agreed before funds move", "2 consent \u2014 mandate/delegation checked before settlement", "3 escrow \u2014 funds release only on delivery proof", "4 resolution \u2014 regime-gated recall + law-c ...}
```

### POST /consent

Store the principal's spending mandate: a budget and an optional merchant allowlist.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/consent -H 'content-type: application/json' \
  -d '{"consent_id":"c-ex","principal":"alice","budget":500}'
```

Example response:

```json
{"consent_id": "c-ex", "stored": true, "budget": 500}
```

### POST /pay

Settle a payment; if `consent_id` is given the mandate is enforced (a payment outside it returns 403 before funds move).

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/pay -H 'content-type: application/json' \
  -d '{"ref":"p-ex","from_account":"alice","to_account":"shop","amount":300,"region":"br_pix","consent_id":"c-ex"}'
```

Example response:

```json
{"ref": "p-ex", "settled": true, "irrevocable": true, "region": "br_pix", "payer_balance": 99700, "payee_balance": 100900}
```

### GET /accounts/{name}

Notional balance; accounts start at 100000 credits on first use.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/accounts/alice
```

Example response:

```json
{"account": "alice", "balance": 99700}
```

### POST /escrow

Open and fund an escrow: the amount leaves the payer immediately and is held.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/escrow -H 'content-type: application/json' \
  -d '{"escrow_id":"e-ex","payer":"alice","payee":"airline","amount":400,"region":"br_pix","condition_expected":"ticket_issued"}'
```

Example response:

```json
{"escrow_id": "e-ex", "status": "FUNDED", "held": 400}
```

### POST /escrow/{id}/deliver

Post the delivery proof; `delivered` is true only if the proof equals the agreed condition exactly.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/escrow/e-ex/deliver -H 'content-type: application/json' -d '{"proof":"ticket_issued"}'
```

Example response:

```json
{"escrow_id": "e-ex", "delivered": true}
```

### POST /escrow/{id}/release

Pay the payee; refused with 403 unless the escrow is delivered and uncontested.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/escrow/e-ex/release
```

Example response:

```json
{"escrow_id": "e-ex", "status": "RELEASED", "payee_balance": 100400}
```

### POST /escrow/{id}/contest

Contest a funded escrow; a contested escrow cannot be released.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/escrow/e-ex2/contest
```

Example response:

```json
{"escrow_id": "e-ex2", "status": "CONTESTED"}
```

### POST /escrow/{id}/refund

Refund a contested escrow to the payer.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/escrow/e-ex2/refund
```

Example response:

```json
{"escrow_id": "e-ex2", "status": "REFUNDED", "payer_balance": 99300}
```

### GET /escrow/{id}

Escrow status.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/escrow/e-ex
```

Example response:

```json
{"escrow_id": "e-ex", "payer": "alice", "payee": "airline", "amount": 400, "region": "br_pix", "delivered": true, "status": "RELEASED"}
```

### POST /recall

Reverse a settled payment — only if the region allows recall, the window is open, and the payment breached the consent.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/recall -H 'content-type: application/json' \
  -d '{"ref":"r-ex","consent_id":"cb-ex"}'
```

Example response:

```json
{"ref": "r-ex", "reversed": true, "reason": "mandate breach recalled", "payer_balance": 100000}
```

### POST /dispute

File a dispute; accepted only if the reason code is valid in the region, and the response includes the legal citation.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/dispute -H 'content-type: application/json' \
  -d '{"ref":"d-ex","region":"in_upi","reason_code":"goods_not_received"}'
```

Example response:

```json
{"ref": "d-ex", "accepted": true, "reason_code": "goods_not_received", "region": "in_upi", "legal_basis": {"category": "non_performance", "label": "Non-performance (non-delivery)", "legal_system": "common law", "citation": "Breach of contract; total failure of consideration; UCC \u00a72-711 buyer's remedies (US)."}}
```

### POST /m2m/delegate

Delegate part of a budget to a sub-agent; a delegation larger than its parent's budget is refused with 403.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/m2m/delegate -H 'content-type: application/json' \
  -d '{"delegation_id":"d-ex","parent_consent_id":"root-ex","agent":"shopper-bot","budget":300}'
```

Example response:

```json
{"delegation_id": "d-ex", "agent": "shopper-bot", "budget": 300, "depth": 1, "chain": ["d-ex", "root-ex"], "note": "use this id as consent_id on /pay, x402 extra.consent_id, or /m2m/handshake \u2014 the same gates enforce it"}
```

### POST /m2m/handshake

One call between two agents: agree the region (Nash), check the mandate, open and fund an escrow.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/m2m/handshake -H 'content-type: application/json' \
  -d '{"pact_id":"t-ex","buyer_agent":"shopper-bot","seller_agent":"seller-agent","buyer_prefs":["eu_sepa","br_pix"],"seller_prefs":["br_pix","in_upi"],"amount":250,"delegation_id":"d-ex"}'
```

Example response:

```json
{"pact_id": "t-ex", "buyer_agent": "shopper-bot", "seller_agent": "seller-agent", "amount": 250, "agreed_region": "br_pix", "regime": {"label": "Brazil - Pix (MED 2.0, 11-day recovery)", "irrevocable": true, "recall_allowed": true, "recall_window_ticks": 11}, "delegation_id": "d-ex", "escrow_id": "pact-t-ex", "status": "ESCROWED"}
```

### GET /m2m/pact/{id}

Pact status including its escrow.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/m2m/pact/t-ex
```

Example response:

```json
{"pact_id": "t-ex", "buyer_agent": "shopper-bot", "seller_agent": "seller-agent", "amount": 250, "agreed_region": "br_pix", "regime": {"label": "Brazil - Pix (MED 2.0, 11-day recovery)", "irrevocable": true, "recall_allowed": true, "recall_window_ticks": 11}, "delegation_id": "d-ex", "escrow_id": "pact-t-ex", "status": "ESCROWED"}
```

### GET /m2m/delegation/{id}

Delegation status and its chain to the root consent.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/m2m/delegation/d-ex
```

Example response:

```json
{"delegation_id": "d-ex", "delegator": "orchestrator", "agent": "shopper-bot", "budget": 300, "depth": 1, "chain": ["d-ex", "root-ex"]}
```

### GET /x402/resource/{name}

An x402-paid resource: without an X-PAYMENT header it returns 402 with the price; with a valid header it returns the resource plus an X-PAYMENT-RESPONSE receipt.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/x402/resource/market-report
```

Example response:

```json
{"x402Version": 1, "error": "X-PAYMENT header required"}
```

### POST /x402/verify

Facilitator check: is this X-PAYMENT header valid for the resource? Does not settle.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/x402/verify -H 'content-type: application/json' \
  -d '{"resource":"market-report","payment_header":"<base64 X-PAYMENT>"}'
```

Example response:

```json
{"isValid": true, "invalidReason": null, "payer": "my-agent"}
```

### POST /x402/settle

Facilitator settle: verify the X-PAYMENT header and execute it on the ledger; each nonce settles once.

```bash
curl -s -X POST https://tvist-api-mias-projects-667d1349.vercel.app/x402/settle -H 'content-type: application/json' \
  -d '{"resource":"market-report","payment_header":"<base64 X-PAYMENT>"}'
```

Example response:

```json
{"success": true, "txHash": "0x7b1e10e228126c2b946cb11b69f59fa4480cb6a2437ef278faad4d53dd6396ab", "networkId": "base-sepolia-sim", "payer": "my-agent", "amount": 25, "ref": "x402-139cb3e892cf4d57"}
```

### GET /disclaimer

The not-legal-advice disclaimer.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/disclaimer
```

Example response:

```json
{"disclaimer": "Technical demonstration only \u2014 a notional-credits sandbox, not a bank, payment institution, or law firm. Legal references cite real primary sources but are engineering-grade mappings, not legal advice; obtain qualified local counsel before relying on them in any jurisdiction."}
```

### GET /skill.md

This file, served raw (`?download=1` to download).

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/skill.md
```

Example response:

```
(this document)
```

### GET /openapi.json

OpenAPI 3.1 spec for every endpoint.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/openapi.json
```

Example response:

```json
{"openapi": "3.1.0", "info": {"title": "Tvist API", "description": "Escrow, consent, and dispute service for AI agents transacting on irrevocable rails. Notional credits only \u2014 a sandbox, not a b ...}
```

### GET /docs

Interactive Swagger UI for the API (HTML).

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/docs
```

Example response:

```
(HTML page — Swagger UI)
```

### GET /readme.md

Deployment guide, raw markdown (`?download=1` to download).

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/readme.md
```

Example response:

```
# Tvist API — a service AI agents can use on their own
```

### GET /view/{doc}

`skill` or `readme`, rendered as an HTML page for humans.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/view/skill
```

Example response:

```
(HTML page rendering this file)
```

### GET /downloads

Lists the downloadable pitch-kit documents and their URLs.

```bash
curl -s https://tvist-api-mias-projects-667d1349.vercel.app/downloads
```

Example response:

```json
{"docs": {"SKILL.md": "/skill.md?download=1", "README.md": "/readme.md?download=1", "OpenAPI": "/openapi.json"}, "pitch_kit": {"brief-pdf": {"file": "Tvist-Executive-Brief.pdf", "label": "Executive brief \u2014 one airy page, 60-second read", "url": "/download/brief-pdf"}, "summary-pdf": {"file": "Tvist-Executive-Summary.pdf", "label": "Executive summary \u2014 dense one-pager"
```

### GET /download/{slug}

One pitch-kit file: `brief-pdf`, `summary-pdf`, `summary-docx`, or `deck-pptx`.

```bash
curl -s -o tvist-brief.pdf https://tvist-api-mias-projects-667d1349.vercel.app/download/brief-pdf
```

Example response:

```
(binary PDF, ~4 KB)
```

## How the agent should use this

1. Check the service is up: `GET /health` returns `{"status":"ok"}`.
2. Agree the governing jurisdiction before any money moves: `POST
   /regions/recommend` with both parties' ranked region lists. Use the
   returned `agreed_region` for every later call. If it is `null`, stop — the
   parties share no region. (`GET /regions/suggest?tz=<your timezone>` gives a
   starting suggestion; `GET /regions` lists all 22 regimes.)
3. Store the principal's mandate: `POST /consent` with a unique `consent_id`,
   the principal's account name, and the budget.
4. Pay inside the mandate: `POST /pay` with the `consent_id`. A payment above
   the budget or to a non-allowlisted merchant is refused with 403 and no
   funds move.
5. For goods or services delivered later, use escrow instead of paying
   directly: `POST /escrow` (funds are held), then after delivery `POST
   /escrow/{id}/deliver` with a proof exactly equal to `condition_expected`,
   then `POST /escrow/{id}/release` (pays the payee). Release before
   delivery returns 403. If the buyer contests (`/contest`), release is
   blocked and `/refund` returns the funds.
6. To reverse a bad settled payment: `POST /recall`. It succeeds only if the
   region allows recall, the window is open, and the payment breached the
   consent — otherwise it is refused and the response says why.
7. To file a dispute: `POST /dispute` with a reason code that is valid in the
   agreed region (listed in `GET /regions`). An accepted dispute returns the
   legal category and citation to quote.
8. To pay for a resource per request (x402): `GET /x402/resource/{name}`
   returns 402 with the price; retry with a base64 `X-PAYMENT` header
   containing an EIP-3009-shaped authorization with a FRESH nonce and
   signature `sim-<nonce>` (sandbox). The response includes an
   `X-PAYMENT-RESPONSE` receipt. Reusing a nonce is refused.
9. For agent-to-agent trade: `POST /m2m/delegate` gives a sub-agent part of a
   budget (never more than its parent); `POST /m2m/handshake` agrees the
   region, checks the mandate, and funds an escrow in one call — then finish
   with the normal escrow endpoints.
10. Everything is discoverable at runtime: `GET /` lists all endpoints and
    `GET /openapi.json` is the machine-readable spec.
