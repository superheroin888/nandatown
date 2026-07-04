# Example: DigiDoot — a personal agent for every Indian citizen, settled via Tvist

[DigiDoot](https://digidoot.in/#architecture) gives every Indian citizen a
personal AI agent that acts on their behalf over India's Digital Public
Infrastructure (Aadhaar, UPI, DigiLocker) **with explicit consent**. This example
wires the Tvist payments plugin (`("payments","tvist")`) in as DigiDoot's
**settlement + dispute endpoint** — the thing the "Service Providers" layer calls
when a citizen's agent moves money or files a dispute — and runs a full
citizen-services scenario through it.

## DigiDoot's 6 layers → Tvist endpoints

| DigiDoot layer | Role | Tvist endpoint it calls |
|---|---|---|
| 1. Multi-Channel Access (WhatsApp/SMS/Voice/App) | how the citizen talks to the agent | *(out of scope — UX)* |
| 2. **Trust Foundation — Identity & Consent** | Aadhaar identity, explicit consent | `store_intent` / `intent_covers` — the consent mandate (budget, allowlist) behind every agent payment |
| 3. Agent Orchestration — the Reasoning Brain | the citizen's personal agent | the agent that calls the endpoint on the citizen's behalf |
| 4. **MCP Integration — Universal Protocol Layer** | how services are invoked | Tvist *is* the payments/dispute MCP-style endpoint, governed per region |
| 5. **Service Providers — Public MCP Servers** | welfare, travel, health services | the providers the agent pays / escrows / disputes against |
| 6. Legacy Integration — existing public systems | UPI / NPCI rails | `region="in_upi"` — the Indian regime (recall window, dispute taxonomy) |

The two starred trust layers are exactly Tvist's intent vault and
governing-region base feature; everything below them is the rest of the plugin.

## The endpoint surface DigiDoot uses

Each is a method on the Tvist plugin, called by a DigiDoot service flow:

- **Negotiate the regime up front** — `recommend_region(["in_upi"], ["in_upi"]) → "in_upi"`.
- **Record consent** — `store_intent(IntentRecord(consent_id, citizen, budget))`.
- **Pay within consent** — `settle_a2a(provider, amount, ref, region="in_upi", intent_ref=consent_id)`; a payment beyond the citizen's budget is refused before funds move.
- **Escrow a service** — `open_escrow / fund_escrow / satisfy_condition / release_escrow`; a travel booking releases only on the delivery proof (the ticket).
- **Protect the citizen** — `recall_a2a(ref, breach_intent, tick)`; a rogue charge that breaches the mandate is recalled under UPI's window.
- **Dispute a service** — `open_dispute(ref, "goods_not_received", citizen, region="in_upi")`; only UPI-valid reason codes are accepted.

Every step is deterministic and lands in the trace — DigiDoot's "explainable,
auditable" decisions, for free.

## Run it

```bash
nest run scenarios/tvist_digidoot.yaml -o ./traces/tvist_digidoot.jsonl
python -c "from pathlib import Path; from nest_core.validators import validate_trace; \
[print(('PASS' if r.passed else 'FAIL'), r.name, '-', r.detail) for r in validate_trace(Path('traces/tvist_digidoot.jsonl'),'tvist_digidoot')]"
```

The scenario ([`tvist_digidoot.py`](../../packages/nest-core/nest_core/scenarios_builtin/tvist_digidoot.py))
plays DigiDoot's demonstrated journeys — welfare disbursement, travel booking,
health records — plus a fraud recall, across six citizen flows. Validators:

- `tvist_digidoot_consent` — every settled flow is India-governed *and* within the
  citizen's explicit consent.
- `tvist_mandate` — no agent payment exceeds its consent budget.
- `tvist_escrow_conditions` — an undelivered service is never released.
- `tvist_conservation` — funds are conserved.

Swap `payments: tvist` → `payments: prepaid_credits` in the YAML and the
protections fail: payments exceed consent, flows settle ungoverned, and the
undelivered booking pays out — exactly what a citizen-facing agent must never do,
and what Tvist's logic prevents.
