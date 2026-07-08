# Tvist API — escrow, consent & dispute for AI agents

## What this service is

Tvist is an HTTP API for AI agents that send payments on behalf of a principal
(a human, or another agent). It provides five checks that run before or after a
payment. Each check is one or two endpoints:

1. **Jurisdiction selection.** Both parties submit ranked lists of acceptable
   regions. The service returns one agreed region (the Nash bargaining
   solution over both rankings), or `null` if the lists do not overlap.
   `null` means: do not transact.
2. **Consent enforcement.** The principal's spending mandate — a budget and an
   optional merchant allowlist — is stored before the agent pays. Every payment
   that references the mandate is checked against it. A payment above the
   budget, or to a merchant not on the allowlist, is refused with `403` before
   any funds move.
3. **Escrow.** Funds leave the payer when the escrow opens. They reach the
   payee only after a delivery proof is posted that exactly equals the agreed
   condition string. Release before delivery is refused with `403`.
4. **Recall.** A settled payment is reversed only if all three hold:
   (a) the region's rules allow recall, (b) the request is inside the region's
   recall window, (c) the payment breached the stored consent. If any of the
   three fails, the recall is refused and the response says which condition
   failed.
5. **Disputes.** A dispute is accepted only if its reason code is valid in the
   stated region. An accepted dispute returns the legal category and the
   citation string for that region's law in the response body.

Two further capabilities use the same checks:

- **x402 payments** (step 7): pay for an HTTP resource per request. The server
  answers `402` with payment requirements; the agent retries with a signed
  `X-PAYMENT` header; the server settles and returns the resource plus a
  receipt header. Each payment nonce is accepted once; replays are refused.
- **Machine-to-machine** (step 8): an agent delegates part of its budget to a
  sub-agent (a delegation larger than its parent's budget is refused), and two
  agents set up a trade in one call (region agreement + mandate check + funded
  escrow).

The same checks apply to all four payment relationships:

| Relationship | What is checked | Endpoints | Step |
|---|---|---|---|
| Human → agent | payment stays inside the human's mandate | `/consent` → `/pay` | 2–3 |
| Agent → sub-agent | delegated budget ≤ delegator's budget | `/m2m/delegate` | 8 |
| Agent ↔ agent | shared region + mandate + escrow, in one call | `/m2m/handshake` | 8 |
| Agent → paid resource | per-request payment; replay and budget checked | `/x402/resource/{name}` | 7 |

## Sandbox facts

- Balances are notional credits, not money. Every account is created with
  100000 credits the first time it is referenced.
- No authentication, no API keys, no signup.
- The same base URL serves both audiences: a browser requesting `GET /` with
  `Accept: text/html` receives an HTML page; any other client receives the
  JSON endpoint index. The API behaves identically for both. The HTML page is
  driven by the same endpoints an agent calls: an executive-summary teaser, a
  live playground, an interactive jurisdiction globe whose per-region clauses
  load from `GET /regions/{region}/legal`, a Nash cooperation visualizer
  (1–1, 1–n, n–n; one `POST /regions/recommend` per pair), a suggested-start
  chip from `GET /regions/suggest`, and downloads for this file and the
  executive-summary documents.
- CORS is open (`Access-Control-Allow-Origin: *`); browser-based clients can
  call every endpoint. The `X-PAYMENT-RESPONSE` header is exposed to browsers.
- **Not legal advice.** This is a technical demonstration. Legal references
  cite real primary sources but are engineering mappings, not counsel. See
  `GET /disclaimer`.

## Base URL

```
https://panels-ntsc-density-genesis.trycloudflare.com
```

- Health check: `GET /health` returns `{"status":"ok"}`.
- Endpoint index: `GET /` lists every endpoint with its method and purpose.
- Machine-readable spec: `GET /openapi.json`. Interactive docs: `GET /docs`.

All request and response bodies are JSON. Errors return `{"error": "<what
failed>"}` with a 4xx status code.

## Endpoints

| Method & path | Body | Does |
|---|---|---|
| `GET /regions` | — | List all 22 jurisdictions. Each entry states: `irrevocable`, `recall_allowed`, `recall_window_ticks`, `rail`, and the valid `reason_codes` |
| `GET /regions/suggest?tz=<IANA tz>` | — | Suggested starting jurisdiction for the caller, from the `tz` query parameter and the `Accept-Language` header. The caller's IP is echoed for transparency but not geolocated. A convenience default, not a decision — negotiate with `POST /regions/recommend` |
| `POST /regions/recommend` | `{client_prefs:[...], agent_prefs:[...]}` | Return the Nash-optimal region for both rankings, or `agreed_region: null` if no region appears in both lists |
| `GET /taxonomy` | — | The dispute taxonomy: 7 legal categories, the mapping from every reason code to its category, and per-region linkage |
| `GET /regions/{region}/legal` | — | One jurisdiction's legal system, regulator, and legal instruments (statutes and scheme rulebooks, each with a link to the official source), plus the legal basis for each of its reason codes |
| `GET /spectrum` | — | The four payment relationships and their checks, as structured JSON, ASCII, and Mermaid |
| `POST /consent` | `{consent_id, principal, budget, merchant_allowlist?}` | Store a spending mandate |
| `POST /pay` | `{ref, from_account, to_account, amount, region, consent_id?}` | Settle a payment. If `consent_id` is given, the mandate is enforced. The response states whether the payment is irrevocable in that region |
| `POST /escrow` | `{escrow_id, payer, payee, amount, region, condition_expected}` | Open an escrow and withdraw the amount from the payer |
| `POST /escrow/{id}/deliver` | `{proof}` | Returns `{delivered:true}` only if `proof` equals `condition_expected` exactly; otherwise `{delivered:false}` (200) and the escrow stays undelivered, so release remains refused |
| `POST /escrow/{id}/release` | — | Pay the payee. Refused with `403` unless the escrow is delivered |
| `POST /escrow/{id}/contest` | — | Contest a funded escrow; a contested escrow cannot be released |
| `POST /escrow/{id}/refund` | — | Return a contested escrow's funds to the payer |
| `GET /escrow/{id}` | — | Escrow status |
| `POST /recall` | `{ref, consent_id, current_tick?}` | Reverse a settled payment. Succeeds only if the region allows recall, the window is open, and the payment breached the given consent |
| `POST /dispute` | `{ref, region, reason_code}` | Accept a dispute only if `reason_code` is valid in `region`. Accepted disputes include `legal_basis` with the citation |
| `GET /accounts/{name}` | — | Account balance |
| `POST /m2m/delegate` | `{delegation_id, parent_consent_id, agent, budget, merchant_allowlist?}` | Delegate budget to a sub-agent. Refused with `403` if `budget` exceeds the parent's, or the allowlist is wider than the parent's |
| `POST /m2m/handshake` | `{pact_id, buyer_agent, seller_agent, buyer_prefs, seller_prefs, amount, delegation_id?}` | One call: agree the region, check the mandate, open and fund an escrow. Refused with `409` if no shared region, `403` if over mandate |
| `GET /m2m/pact/{id}` | — | Pact status, including its escrow |
| `GET /m2m/delegation/{id}` | — | Delegation status and its chain to the root consent |
| `GET /x402/resource/{name}` | `X-PAYMENT` header | Without the header: `402` plus payment requirements. With a valid header: the resource plus an `X-PAYMENT-RESPONSE` receipt header |
| `POST /x402/verify` | `{resource, payment_header}` | Check an `X-PAYMENT` header without settling |
| `POST /x402/settle` | `{resource, payment_header}` | Verify and settle an `X-PAYMENT` header on the ledger |
| `GET /stats` | — | Current counts: accounts, settlements, recalls, escrows, held credits, disputes, x402 settlements, total funds |
| `GET /disclaimer` | — | The not-legal-advice disclaimer as JSON |

## How an agent should use this — steps (copy-paste curl)

Set the base URL once:

```bash
BASE=https://panels-ntsc-density-genesis.trycloudflare.com
```

### Step 1 — agree the governing jurisdiction

Each party lists the regions it accepts, best first. The service returns the
region that maximises the product of both parties' preference utilities (Nash
bargaining). This is not simply the client's first choice.

```bash
curl -s -X POST $BASE/regions/recommend -H 'content-type: application/json' \
  -d '{"client_prefs":["eu_sepa","br_pix","in_upi"],"agent_prefs":["in_upi","br_pix","eu_sepa"]}'
# -> {"agreed_region":"br_pix","method":"nash_bargaining","naive_client_first":"eu_sepa", ...}
```

If `agreed_region` is `null`, the parties share no acceptable region. Do not
transact.

### Step 2 — record the principal's consent

```bash
curl -s -X POST $BASE/consent -H 'content-type: application/json' \
  -d '{"consent_id":"c1","principal":"alice","budget":500}'
# -> {"consent_id":"c1","stored":true,"budget":500}
```

### Step 3 — pay within the consent

```bash
curl -s -X POST $BASE/pay -H 'content-type: application/json' \
  -d '{"ref":"p1","from_account":"alice","to_account":"shop","amount":300,"region":"br_pix","consent_id":"c1"}'
# -> {"ref":"p1","settled":true,"irrevocable":true,"region":"br_pix","payer_balance":99700,"payee_balance":100300}
```

A payment above the mandate is refused with `403` and no funds move:

```bash
curl -s -X POST $BASE/pay -H 'content-type: application/json' \
  -d '{"ref":"p2","from_account":"alice","to_account":"shop","amount":900,"region":"br_pix","consent_id":"c1"}'
# -> 403 {"error":"payment 900 to shop exceeds consent c1"}
```

### Step 4 — escrow funds until delivery

The order is fixed: open (funds leave the payer) → deliver (proof must equal
the condition) → release (payee is paid). Release before deliver returns `403`.

```bash
curl -s -X POST $BASE/escrow -H 'content-type: application/json' \
  -d '{"escrow_id":"e1","payer":"alice","payee":"airline","amount":400,"region":"br_pix","condition_expected":"ticket_issued"}'
curl -s -X POST $BASE/escrow/e1/release            # -> 403: not delivered yet
curl -s -X POST $BASE/escrow/e1/deliver -H 'content-type: application/json' -d '{"proof":"ticket_issued"}'
curl -s -X POST $BASE/escrow/e1/release            # -> 200: payee paid
```

If the buyer contests a funded escrow (`POST /escrow/e1/contest`), release is
blocked; `POST /escrow/e1/refund` then returns the funds to the payer.

### Step 5 — recall a payment that breached the mandate

Recall succeeds only if the region allows recall AND the payment breached the
consent. `us_fednow` never allows recall; `in_upi` and `br_pix` do, within
their windows (`GET /regions` states each window).

```bash
curl -s -X POST $BASE/consent -H 'content-type: application/json' -d '{"consent_id":"cb","principal":"bob","budget":100}'
curl -s -X POST $BASE/pay -H 'content-type: application/json' -d '{"ref":"u1","from_account":"bob","to_account":"scam","amount":300,"region":"in_upi"}'
curl -s -X POST $BASE/recall -H 'content-type: application/json' -d '{"ref":"u1","consent_id":"cb"}'
# -> {"reversed":true,"reason":"mandate breach recalled"}   (300 > 100 budget = breach)
```

A recall of a payment that did not breach the consent returns
`{"reversed":false,...}` with the reason. Funds stay where they are.

### Step 6 — file a dispute with a region-valid reason code

Valid reason codes per region are listed in `GET /regions`. An accepted
dispute includes the legal basis and citation for that region:

```bash
curl -s -X POST $BASE/dispute -H 'content-type: application/json' \
  -d '{"ref":"u1","region":"in_upi","reason_code":"goods_not_received"}'
# -> {"accepted":true,"legal_basis":{"category":"non_performance",
#     "label":"Non-performance (non-delivery)","legal_system":"common law",
#     "citation":"Breach of contract; total failure of consideration; UCC §2-711 buyer's remedies (US)."}}
curl -s -X POST $BASE/dispute -H 'content-type: application/json' \
  -d '{"ref":"u1","region":"in_upi","reason_code":"pix_med_return"}'
# -> {"accepted":false,...}   (pix_med_return is not a valid code in in_upi)
```

Quote `legal_basis.citation` when pursuing the claim. The region's full
instrument list, with links to official sources, is at
`GET /regions/{region}/legal`.

### Step 7 — pay for a resource with x402

The x402 flow has three fixed steps. Sandbox specifics: signatures are the
string `sim-` followed by the nonce; credits stand in for USDC; the network id
is `base-sepolia-sim`. x402 settlements are irrevocable (`stablecoin_x402`
regime): recall is always refused. Use escrow (step 4) or a consent cap
(below) for protection.

```bash
# 7.1  Request without payment. The response is 402 and lists the requirements.
curl -si $BASE/x402/resource/market-report | head -1     # HTTP/2 402
curl -s  $BASE/x402/resource/market-report               # {"x402Version":1,"error":"X-PAYMENT header required","accepts":[{"scheme":"exact","network":"base-sepolia-sim","maxAmountRequired":25,"payTo":"tvist-treasury",...}]}

# 7.2  Build the X-PAYMENT header: a base64-encoded JSON object with an
#      EIP-3009-shaped authorization and a signature. Use a new nonce per payment.
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

# 7.3  Retry with the header. The response is the resource; the
#      X-PAYMENT-RESPONSE header carries the settlement receipt.
curl -s -D - $BASE/x402/resource/market-report -H "X-PAYMENT: $PAY" | grep -i x-payment-response
# Sending the SAME header again is refused: each nonce settles once.
curl -s      $BASE/x402/resource/market-report -H "X-PAYMENT: $PAY"   # -> 402 (replay refused)
```

Consent enforcement on x402: put the principal's `consent_id` in the `extra`
object of the payment payload. A payment above that consent's budget is
refused with `402` before settlement, even though the rail itself is
irrevocable. To verify a header without settling, use `POST /x402/verify`; to
settle explicitly, use `POST /x402/settle`.

### Step 8 — delegate to sub-agents and trade agent-to-agent

Delegation rule: a sub-agent's budget must be less than or equal to its
delegator's budget, and its allowlist (if any) must be a subset of the
delegator's. A delegation that violates either rule is refused with `403`.
Every delegation chain traces back to one root consent.

Handshake rule: `POST /m2m/handshake` performs three checks in one call —
(1) region agreement over both preference lists, (2) mandate check against the
buyer's delegation or consent, (3) escrow opened and funded. If no shared
region exists it returns `409`; if the amount exceeds the mandate it returns
`403`. In both cases no funds move.

```bash
# 8.1  Root mandate: the orchestrator agent's own spending policy.
curl -s -X POST $BASE/consent  -H 'content-type: application/json' \
  -d '{"consent_id":"root","principal":"orchestrator-agent","budget":1000}'
# 8.2  Delegate 300 to a shopper bot. (A request for more than 1000 would return 403.)
curl -s -X POST $BASE/m2m/delegate -H 'content-type: application/json' \
  -d '{"delegation_id":"d1","parent_consent_id":"root","agent":"shopper-bot","budget":300}'
# 8.3  One call sets up the trade: region + mandate + funded escrow.
curl -s -X POST $BASE/m2m/handshake -H 'content-type: application/json' \
  -d '{"pact_id":"t1","buyer_agent":"shopper-bot","seller_agent":"seller-agent",
       "buyer_prefs":["eu_sepa","br_pix"],"seller_prefs":["br_pix","in_upi"],
       "amount":250,"delegation_id":"d1"}'
# -> {"agreed_region":"br_pix","status":"ESCROWED","escrow_id":"pact-t1",
#     "next_steps":["POST /escrow/pact-t1/deliver {proof}","POST /escrow/pact-t1/release"]}
# 8.4  The standard escrow endpoints finish the trade.
curl -s -X POST $BASE/escrow/pact-t1/deliver -H 'content-type: application/json' -d '{"proof":"delivered"}'
curl -s -X POST $BASE/escrow/pact-t1/release
curl -s $BASE/m2m/pact/t1        # pact + escrow status
```

A `delegation_id` is accepted anywhere a `consent_id` is: in `/pay`, in x402
`extra.consent_id`, and in handshakes. The same enforcement applies.

## Full worked example — an agent books travel for its principal

```bash
BASE=https://panels-ntsc-density-genesis.trycloudflare.com
# 1. Agree the jurisdiction.
curl -s -X POST $BASE/regions/recommend -H 'content-type: application/json' \
  -d '{"client_prefs":["in_upi"],"agent_prefs":["in_upi"]}'          # -> in_upi
# 2. The principal authorises up to 500.
curl -s -X POST $BASE/consent -H 'content-type: application/json' \
  -d '{"consent_id":"trip","principal":"citizen","budget":500}'
# 3. Escrow the fare; the airline is paid only after the ticket proof lands.
curl -s -X POST $BASE/escrow -H 'content-type: application/json' \
  -d '{"escrow_id":"fare","payer":"citizen","payee":"airline","amount":450,"region":"in_upi","condition_expected":"ticket_issued"}'
curl -s -X POST $BASE/escrow/fare/deliver -H 'content-type: application/json' -d '{"proof":"ticket_issued"}'
curl -s -X POST $BASE/escrow/fare/release
```

## Rules an agent must follow

1. `ref`, `escrow_id`, `consent_id`, `delegation_id`, and `pact_id` must be
   unique. Reusing one returns `409`.
2. Read `GET /regions` before choosing a region or a dispute reason. It states,
   per region: `irrevocable`, `recall_allowed`, `recall_window_ticks`, and the
   valid `reason_codes`.
3. If `POST /regions/recommend` returns `agreed_region: null`, do not transact.
4. The two region flags mean different things. `irrevocable: true` means the
   sender cannot reverse a settled payment. Some irrevocable regions still
   provide a scheme-level recall procedure (`recall_allowed: true`) within a
   window; `POST /recall` uses that procedure and additionally requires a
   consent breach. Where `recall_allowed` is `false` (for example `us_fednow`
   and `stablecoin_x402`), no recall exists at all — use escrow (step 4)
   instead of direct payment.
5. Use a fresh nonce for every x402 payment. A reused nonce is refused.
6. The API is discoverable at runtime: `GET /` and `GET /openapi.json` describe
   every endpoint. `GET /taxonomy` maps every reason code to one of 7 legal
   categories; `GET /regions/{region}/legal` gives the statutes, rulebooks, and
   regulator for a region with links to official sources. Cite the returned
   `operative_basis` when filing a dispute for a principal.
