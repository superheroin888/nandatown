# Tvist — the escrow & settlement-trust layer for agentic commerce

**Built into one Nanda Town layer: `payments`. Proven under attack, not just specced.**

---

## The one-liner

Agents are starting to spend money on our behalf over **irrevocable** rails.
Tvist is the missing **escrow + dispute layer** that makes that safe — a single
`payments`-layer protocol that holds funds until intent and delivery are
mutually verifiable, and reverses a settled payment **only** on cryptographic
proof an agent exceeded its mandate.

---

## Why now (the wedge)

Two tectonic shifts collided in 2025–26, and nobody built the layer between them:

- **Agentic commerce crossed the chasm.** ~1 in 6 Black Friday 2025 purchases
  were AI-assisted; gen-AI retail traffic up 4,700% YoY (Adobe). Juniper (Apr
  2026): **trust is the #1 barrier** to agentic commerce — ahead of every
  technical concern.
- **A2A push payments became mandatory — and they're irrevocable.** Pix MED 2.0
  (mandatory Feb 2026, 11-day recovery SLA), SEPA Instant (mandatory send Oct
  2025, 10-second finality), FedNow, UPI. The ECB warns instant-payment fraud
  risk is "up to 10× higher." Once the money lands, it does **not** reverse like
  a card chargeback.

Then **seven agent-payment protocols** shipped — Mastercard Agent Pay +
Verifiable Intent, Visa Intelligent Commerce, Amex Agent Purchase Protection,
Google AP2, OpenAI ACP, OKX APP, Coinbase x402 — each with its **own (or zero)**
dispute taxonomy.

> Everyone built the rails. Everyone built intent protocols. **Nobody built the
> dispute + escrow layer across them.** That cross-section is the moat — and it
> is exactly what a payments-layer primitive is for.

---

## What Tvist is

A thin **orchestration layer** (not a bank — we orchestrate regulated custody
partners) with three primitives, all on the `payments` layer:

1. **Programmable escrow.** Hold funds across A2A rails until a typed condition —
   delivery proof, time, or attestation — is satisfied. Release is *refused*
   until then; a contest opens a mediation case.
2. **Cross-protocol intent vault.** Store the Verifiable-Intent / mandate record
   (budget, merchant allowlist) behind any agent payment, indexed canonically
   across MC-VI / AP2 / ACP / x402.
3. **Irrevocability-aware recall.** A settled push payment is reversed **only**
   when a recall cites an intent mismatch (`agent_exceeded_mandate`). No
   unilateral clawback — the thing Pix/SEPA rulebooks exist to prevent.

---

## The proof — we shipped it as a Nanda Town protocol and attacked it

Tvist isn't a slide. It's a working `("payments","tvist")` plugin in the
12-layer stack, exercised by an agentic-commerce scenario with **three live
attacks** and an adversarial validator per attack. The test is *discrimination*:
the same scenario must pass under Tvist and **fail** under the default
`prepaid_credits` ledger.

| Attack (agentic-commerce threat) | Validator | `payments: prepaid_credits` (default) | `payments: tvist` |
|---|---|---|---|
| **Unilateral clawback** of a settled irrevocable A2A payment | `tvist_irrevocability` | ❌ `refund` reverses it | ✅ recall refused without intent mismatch |
| **Escrow drain** — payee takes funds with no delivery | `tvist_escrow_conditions` | ❌ pays out immediately | ✅ release gated on the condition |
| **Over-mandate** agent payment (above its budget) | `tvist_mandate` | ❌ settles regardless | ✅ blocked before funds move |
| Funds conservation | `tvist_conservation` | ✅ | ✅ |

A *justified* recall (the agent genuinely breached mandate) still succeeds — so
Tvist blocks the abuse without breaking the legitimate reversal. Deterministic,
pure-Python, no RNG: same seed → byte-identical trace.

Run it:

```bash
nest run scenarios/tvist_escrow.yaml -o ./traces/tvist_escrow.jsonl
python -c "from pathlib import Path; from nest_core.validators import validate_trace; \
[print(('PASS' if r.passed else 'FAIL'), r.name) for r in validate_trace(Path('traces/tvist_escrow.jsonl'),'tvist_escrow')]"
# flip `payments: tvist` -> `payments: prepaid_credits` and re-run to watch the three gates fail
```

---

## Why this is one layer, on purpose

Tvist is the **`payments` layer** and nothing else. It's a drop-in for the stock
`Payments` protocol (`pay`/`verify`/`refund` still work), and the escrow / intent
/ recall surface is purely additive. That's the whole bet: the dispute+escrow
primitive is a *layer*, not an app — any agent, marketplace, or rail on Nanda
Town's Internet of Agents can compose it without re-onboarding.

---

## Where Tvist fits on NANDA

NANDA is building the Internet of AI Agents — discovery, identity, and the rails
for agents to transact. The moment agents transact with irrevocable money, they
need a **settlement-trust layer**: escrow to hold, intent to authorize, mediation
to unwind. Tvist is that layer, and it plugs into the one slot in the 12-layer
stack where value moves: `payments`.

---

*See [`README.md`](README.md) for the full layer-by-layer build, and
[the problem brief](../hackathon/problems/12-payments-tvist-escrow-agentic-commerce.md)
for the success criteria this submission meets.*
