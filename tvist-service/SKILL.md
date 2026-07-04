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
escrow a service until delivery, recall a mandate-breaching charge, and file a
dispute under valid reason codes.

> Sandbox: balances are **notional credits**, not real money. Accounts are
> created automatically at 100000 credits on first use. No auth, no keys, no
> signup — just call it.

> Dual-use: the same base URL serves **humans and agents**. A browser opening
> `/` gets an animated homepage with a live API playground; an agent (or curl)
> gets the JSON endpoint index — the contract below is unchanged either way.
> CORS is open (`*`), so browser-based agent frameworks can call it too.

## Base URL

```
https://stem-hook-sing-locks.trycloudflare.com
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
| `GET /stats` | — | Live service metrics (accounts, settlements, escrows, held credits, funds) |

## Steps to use (copy-paste curl)

Set the base URL once:

```bash
BASE=https://stem-hook-sing-locks.trycloudflare.com
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
  -d '{"ref":"u1","region":"in_upi","reason_code":"goods_not_received"}'   # accepted:true
curl -s -X POST $BASE/dispute -H 'content-type: application/json' \
  -d '{"ref":"u1","region":"in_upi","reason_code":"pix_med_return"}'       # accepted:false (wrong region)
```

## Full worked example — an agent books travel for its principal

```bash
BASE=https://stem-hook-sing-locks.trycloudflare.com
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
