# Tvist API — escrow, consent & dispute for AI agents

## What it does

When an AI agent pays another party on someone's behalf — booking a service,
paying a vendor, moving money on an instant rail — it needs to do three things a
plain "send money" call can't: **stay within the principal's consent**, **hold
funds until the service is delivered**, and **know whether a bad payment can be
recalled** (many instant rails are irrevocable). Tvist is a single HTTP service
that provides all three, plus it recommends the **jurisdiction** whose dispute
rules both parties should adopt — chosen game-theoretically so neither side is
imposed on.

Use it to: pick a mutually-optimal region, record a spend mandate, pay within it,
escrow a service until delivery, recall a mandate-breaching charge, file a
dispute under valid reason codes, delegate attenuated authority to sub-agents,
and form one-call agent↔agent trade pacts.

One gate logic covers all four trust relationships:

| Relationship | Pain it solves | Flow |
|---|---|---|
| Human → agent | agent overspends the mandate on a final rail | `/consent` → `/pay` (403 over budget) — steps 2–3 |
| Agent → sub-agent | sub-agents exceed their delegator's authority | `/m2m/delegate` (attenuated, chains to root) — step 8 |
| Agent ↔ agent | two machines, no shared jurisdiction, trading blind | `/m2m/handshake` (Nash region + mandate + escrow) — step 8 |
| Agent → resource | pay-per-call APIs; replay + overspend risk | x402: 402 → signed `X-PAYMENT` — step 7 |

> Sandbox: balances are **notional credits**, not real money. Accounts are
> created automatically at 100000 credits on first use. No auth, no keys, no
> signup — just call it.

> Dual-use: the same base URL serves **humans and agents**. A browser opening
> `/` gets an animated homepage with a live API playground; an agent (or curl)
> gets the JSON endpoint index — the contract below is unchanged either way.
> CORS is open (`*`), so browser-based agent frameworks can call it too.

> Disclaimer: **technical demonstration only — not legal advice.** This is a
> notional-credits sandbox, not a bank, payment institution, or law firm. Legal
> references cite real primary sources but are engineering-grade mappings;
> obtain qualified local counsel before relying on them (`GET /disclaimer`).

## Base URL

```
https://organizing-quiz-commentary-enhancing.trycloudflare.com
```

- Health: `GET /health` → `{"status":"ok"}`
- Self-describing index: `GET /` (lists every endpoint)
- Machine-readable spec: `GET /openapi.json` · Interactive docs: `/docs`

All request/response bodies are JSON. Errors return `{"error": "..."}` with a
4xx status.

## Endpoints

| Method & path | Body | Does |
|---|---|---|
| `GET /regions` | — | List all 22 jurisdictions and their dispute regimes |
| `POST /regions/recommend` | `{client_prefs:[...], agent_prefs:[...]}` | Nash-optimal region for both parties (or `null` = no deal) |
| `GET /taxonomy` | — | Civil/commercial-law dispute taxonomy: 7 legal categories, reason-code → category mapping, per-region linkage |
| `GET /regions/{region}/legal` | — | A jurisdiction's legal system, regulator, and official legal instruments (statutes, scheme rulebooks, with links to the official source), plus each accepted reason code's operative legal basis |
| `GET /spectrum` | — | The four trust relationships + one-gate logic, as structured data, ASCII, and Mermaid — render it or reason over it |
| `POST /consent` | `{consent_id, principal, budget, merchant_allowlist?}` | Store a spend mandate |
| `POST /pay` | `{ref, from_account, to_account, amount, region, consent_id?}` | Settle; enforces consent; marks irrevocability by region |
| `POST /escrow` | `{escrow_id, payer, payee, amount, region, condition_expected}` | Open + fund escrow (holds payer's funds) |
| `POST /escrow/{id}/deliver` | `{proof}` | Mark delivered iff `proof == condition_expected` |
| `POST /escrow/{id}/release` | — | Release to payee **only if delivered** |
| `POST /escrow/{id}/contest` | — | Contest a funded escrow (blocks release) |
| `POST /escrow/{id}/refund` | — | Refund a contested escrow to the payer |
| `GET /escrow/{id}` | — | Escrow status |
| `POST /recall` | `{ref, consent_id, current_tick?}` | Reverse a settled payment **only** if region allows recall AND the payment breached the mandate |
| `POST /dispute` | `{ref, region, reason_code}` | Accepted only if `reason_code` is valid in that region |
| `GET /accounts/{name}` | — | Notional balance |
| `GET /x402/resource/{name}` | `X-PAYMENT` header | x402 paid resource: returns **402 + payment requirements**; retry with a signed payment header to receive the resource + `X-PAYMENT-RESPONSE` receipt |
| `POST /x402/verify` | `{resource, payment_header}` | Facilitator: is this X-PAYMENT valid? |
| `POST /x402/settle` | `{resource, payment_header}` | Facilitator: verify + settle on the ledger |
| `GET /stats` | — | Live service metrics (accounts, settlements, escrows, held credits, funds, x402 settlements) |

## Steps to use (copy-paste curl)

Set the base URL once:

```bash
BASE=https://organizing-quiz-commentary-enhancing.trycloudflare.com
```

### 1. Agree the governing jurisdiction (game-theoretic)

Each party ranks the regions it accepts. The service returns the Nash-optimal
region — the joint best, not just the client's first pick.

```bash
curl -s -X POST $BASE/regions/recommend -H 'content-type: application/json' \
  -d '{"client_prefs":["eu_sepa","br_pix","in_upi"],"agent_prefs":["in_upi","br_pix","eu_sepa"]}'
# -> {"agreed_region":"br_pix","method":"nash_bargaining","naive_client_first":"eu_sepa", ...}
```

If `agreed_region` is `null`, the parties share no region — do not transact.

### 2. Record the principal's consent (spend mandate)

```bash
curl -s -X POST $BASE/consent -H 'content-type: application/json' \
  -d '{"consent_id":"c1","principal":"alice","budget":500}'
```

### 3. Pay within consent

```bash
curl -s -X POST $BASE/pay -H 'content-type: application/json' \
  -d '{"ref":"p1","from_account":"alice","to_account":"shop","amount":300,"region":"br_pix","consent_id":"c1"}'
# -> {"settled":true,"irrevocable":true,...}
```

A payment above the mandate is refused with `403`:

```bash
curl -s -X POST $BASE/pay -H 'content-type: application/json' \
  -d '{"ref":"p2","from_account":"alice","to_account":"shop","amount":900,"region":"br_pix","consent_id":"c1"}'
# -> {"error":"payment 900 to shop exceeds consent c1"}
```

### 4. Escrow a service until it's delivered

```bash
curl -s -X POST $BASE/escrow -H 'content-type: application/json' \
  -d '{"escrow_id":"e1","payer":"alice","payee":"airline","amount":400,"region":"br_pix","condition_expected":"ticket_issued"}'
curl -s -X POST $BASE/escrow/e1/release            # 403: not delivered yet
curl -s -X POST $BASE/escrow/e1/deliver -H 'content-type: application/json' -d '{"proof":"ticket_issued"}'
curl -s -X POST $BASE/escrow/e1/release            # now releases to the airline
```

### 5. Recall a bad charge (region-aware)

Recall only succeeds where the region permits it AND the payment breached the
mandate. A no-recall rail (e.g. FedNow) refuses; UPI/Pix allow it:

```bash
curl -s -X POST $BASE/consent -H 'content-type: application/json' -d '{"consent_id":"cb","principal":"bob","budget":100}'
curl -s -X POST $BASE/pay -H 'content-type: application/json' -d '{"ref":"u1","from_account":"bob","to_account":"scam","amount":300,"region":"in_upi"}'
curl -s -X POST $BASE/recall -H 'content-type: application/json' -d '{"ref":"u1","consent_id":"cb"}'
# -> {"reversed":true,"reason":"mandate breach recalled"}   (300 > 100 budget = breach)
```

### 6. File a dispute under a valid reason

```bash
curl -s -X POST $BASE/dispute -H 'content-type: application/json' \
  -d '{"ref":"u1","region":"in_upi","reason_code":"goods_not_received"}'
# -> accepted:true + legal_basis inline, e.g.
#    {"category":"non_performance","label":"Non-performance (non-delivery)",
#     "legal_system":"common law","citation":"Breach of contract; total failure
#     of consideration; UCC §2-711 buyer's remedies (US)."}
curl -s -X POST $BASE/dispute -H 'content-type: application/json' \
  -d '{"ref":"u1","region":"in_upi","reason_code":"pix_med_return"}'       # accepted:false (wrong region)
```

Quote the returned `legal_basis.citation` when pursuing the claim; the region's
full instrument list (with official-source links) is at
`GET /regions/{region}/legal`.

### 7. Pay for a resource over the x402 rail (HTTP-native, on-chain style)

x402 is how agents pay per request: ask for the resource, get **402 Payment
Required** with structured requirements, retry with a signed `X-PAYMENT`
header. Sandbox note: signatures are simulated as `sim-<nonce>`; credits stand
in for USDC on `base-sepolia-sim`. x402 settlements are **irrevocable**
(`stablecoin_x402` regime — recall always refused; use escrow or the consent
cap for protection).

```bash
# 1. discover the price — 402 with the requirements
curl -si $BASE/x402/resource/market-report | head -1     # HTTP/2 402
curl -s  $BASE/x402/resource/market-report               # {"accepts":[{"scheme":"exact","payTo":"tvist-treasury","maxAmountRequired":25,...}]}

# 2. build the payment header (EIP-3009-shaped authorization, base64)
PAY=$(python3 -c "
import base64, json, uuid
n = uuid.uuid4().hex
p = {'x402Version': 1, 'scheme': 'exact', 'network': 'base-sepolia-sim',
     'payload': {'authorization': {'from': 'my-agent', 'to': 'tvist-treasury',
                                   'value': 25, 'validAfter': 0,
                                   'validBefore': 9999999999, 'nonce': n},
                 'signature': 'sim-' + n},
     'extra': {}}
print(base64.b64encode(json.dumps(p).encode()).decode())")

# 3. retry with the header — resource + X-PAYMENT-RESPONSE receipt
curl -s -D - $BASE/x402/resource/market-report -H "X-PAYMENT: $PAY" | grep -i x-payment-response
curl -s      $BASE/x402/resource/market-report -H "X-PAYMENT: $PAY"   # (new nonce needed — replays are rejected)
```

Tvist twist: put your principal's `consent_id` in `extra` and the mandate is
enforced **even on this irrevocable rail** — an over-budget x402 payment is
refused with 402 before settlement. Facilitator endpoints `/x402/verify` and
`/x402/settle` are available if you separate verification from delivery.

### 8. Machine-to-machine: delegate to sub-agents, trade agent↔agent

Pure M2M — no human in the loop, same gates. An agent acts as principal for
sub-agents via **attenuated delegation** (a child budget can never exceed its
parent's; allowlists only narrow; chains compose and trace to the root
mandate). A **one-call handshake** then forms an agent↔agent pact: Nash-optimal
region + mandate check + an atomically funded escrow.

```bash
# root mandate = the orchestrator agent's own spending policy
curl -s -X POST $BASE/consent  -H 'content-type: application/json' \
  -d '{"consent_id":"root","principal":"orchestrator-agent","budget":1000}'
# delegate 300 to a shopper bot (500 would be refused: attenuation)
curl -s -X POST $BASE/m2m/delegate -H 'content-type: application/json' \
  -d '{"delegation_id":"d1","parent_consent_id":"root","agent":"shopper-bot","budget":300}'
# one call: two agents agree the Nash region, mandate is checked, escrow funded
curl -s -X POST $BASE/m2m/handshake -H 'content-type: application/json' \
  -d '{"pact_id":"t1","buyer_agent":"shopper-bot","seller_agent":"seller-agent",
       "buyer_prefs":["eu_sepa","br_pix"],"seller_prefs":["br_pix","in_upi"],
       "amount":250,"delegation_id":"d1"}'
# -> {"agreed_region":"br_pix","status":"ESCROWED","escrow_id":"pact-t1",
#     "next_steps":["POST /escrow/pact-t1/deliver {proof}","POST /escrow/pact-t1/release"]}
# the ordinary escrow endpoints finish the trade
curl -s -X POST $BASE/escrow/pact-t1/deliver -H 'content-type: application/json' -d '{"proof":"delivered"}'
curl -s -X POST $BASE/escrow/pact-t1/release
curl -s $BASE/m2m/pact/t1        # pact + live escrow status
```

Refusals an agent must handle: `409` no shared region (do not transact), `403`
attenuation violated or pact amount over mandate — always **before** funds
move. A delegation id works anywhere a `consent_id` does (`/pay`, x402
`extra.consent_id`, handshakes) — the same Tvist logic end to end.

## Full worked example — an agent books travel for its principal

```bash
BASE=https://organizing-quiz-commentary-enhancing.trycloudflare.com
# 1. principal + agent agree a jurisdiction
curl -s -X POST $BASE/regions/recommend -H 'content-type: application/json' \
  -d '{"client_prefs":["in_upi"],"agent_prefs":["in_upi"]}'          # -> in_upi
# 2. principal authorises up to 500
curl -s -X POST $BASE/consent -H 'content-type: application/json' \
  -d '{"consent_id":"trip","principal":"citizen","budget":500}'
# 3. escrow the fare until the ticket is issued
curl -s -X POST $BASE/escrow -H 'content-type: application/json' \
  -d '{"escrow_id":"fare","payer":"citizen","payee":"airline","amount":450,"region":"in_upi","condition_expected":"ticket_issued"}'
curl -s -X POST $BASE/escrow/fare/deliver -H 'content-type: application/json' -d '{"proof":"ticket_issued"}'
curl -s -X POST $BASE/escrow/fare/release                            # airline paid only after delivery
```

## Notes for agents

- Idempotency: `ref` and `escrow_id` must be unique; reusing one returns `409`.
- Discover the API at runtime: `GET /` and `GET /openapi.json` are enough to
  drive every call.
- `GET /regions` tells you, per region: `irrevocable`, `recall_allowed`,
  `recall_window_ticks`, and the valid `reason_codes` — read it before choosing a
  region or a dispute reason.
- Legal grounding: every reason code maps to a civil/commercial-law category
  (`GET /taxonomy` — non-performance, non-conformity, fraud/unauthorized,
  agency/mandate, unjust enrichment, procedural recall, continuing obligations),
  and every jurisdiction lists its operative statutes, scheme rulebooks, and
  regulator with links to the official legal source
  (`GET /regions/{region}/legal`). Cite the `operative_basis` when filing a
  dispute on a principal's behalf.
