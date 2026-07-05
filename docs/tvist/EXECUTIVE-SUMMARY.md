# Tvist.ai — Executive Summary

*The settlement-trust layer for agentic commerce: jurisdiction, consent, escrow,
and recall for AI agents that move money.*

---

## The problem

Two shifts collided in 2025–26, and the layer between them was never built:

1. **AI agents now spend money on people's behalf.** ~1 in 6 Black Friday 2025
   purchases were AI-assisted; generative-AI retail traffic grew 4,700% YoY
   (Adobe). Juniper (2026) names **trust as the #1 barrier** to agentic
   commerce — ahead of every technical concern.
2. **The rails they spend on are instant and irrevocable — by regulation.**
   Pix (MED 2.0, mandatory 2026), SEPA Instant (mandatory 2025, 10-second
   finality), FedNow, UPI. The ECB warns instant-payment fraud risk is "up to
   10× higher." Once the money lands, it does not come back like a card
   chargeback.

Meanwhile the dispute economics were already broken on cards: 106M disputes at
Visa alone in 2025 (heading to ~324M by 2028), 40–80% of e-commerce disputes
are *friendly fraud*, and merchants face ~$28B/yr in chargeback losses.

**Net:** when an agent pays the wrong party, exceeds its mandate, or prepays for
a service that never arrives — on a settlement-final rail, across borders where
every rail speaks a different dispute language — there is no recourse layer.
Nobody owns the cross-section.

## Options in the market today — and their gaps

| Player / category | What it solves | What it doesn't |
|---|---|---|
| **Visa AI dispute suite** (6 tools, 2026) | Card dispute automation, network-scale | Card-only, single-network, competes with its own ecosystem |
| **Mastercard** (Mastercom, Ethoca, Verifiable Intent, Agent Pay) | Card disputes as APIs; open-source intent standard | Protocols, not operations: no cross-rail orchestration, no escrow |
| **Amex Agent Purchase Protection** | Liability cover for agent purchases | Closed-loop — works only inside Amex |
| **Agent-payment protocols** (Google AP2, OpenAI ACP, OKX APP, Coinbase x402) | Agent checkout & payment execution | Dispute resolution "future scope" or absent; x402 has no dispute layer at all |
| **Chargeback SaaS** (Chargeflow, etc.) | Card representment automation for merchants | Card rails only; nothing for irrevocable A2A or agent mandates |
| **Escrow / custody providers** (Modulr, Trustly, Currencycloud) | Licensed fund-holding on specific rails | No programmable, dispute-aware, rail-agnostic escrow primitive |

Seven agent-payment protocols, four card networks, ~$50B of manual escrow —
each with its own (or zero) dispute taxonomy. **Everyone built rails and intent
standards. Nobody built the dispute + escrow layer across them.**

## The Tvist.ai solution

A thin **orchestration layer** (not a bank — regulated custody partners hold
funds) with four primitives that fire in order, before and after every agent
transaction:

1. **Jurisdiction, agreed up front.** From a global registry of 22 real
   instant/A2A regimes (Pix, SEPA, FedNow, UPI, FPS, NPP, M-Pesa, stablecoin…),
   client and agent negotiate the governing dispute regime *before funds move* —
   selected as the **Nash bargaining optimum**, the jointly-fairest choice, not
   whatever one side demands. No overlap → no transaction.
2. **Consent, enforced.** The principal's explicit mandate (budget, merchant
   allowlist) lives in an intent vault; a payment outside it is refused *before
   settlement* — not refunded after.
3. **Escrow, delivery-gated.** Funds hold until a typed condition (delivery
   proof / attestation / time) is satisfied; contested holds mediate to refund.
4. **Recall, proof-gated.** A settled payment reverses **only** where the
   agreed regime permits it, inside its window, on evidence of a mandate breach
   — unilateral clawbacks are refused, which is exactly what irrevocable-rail
   rulebooks require.

The result for each party: principals can safely delegate spend; agents can
transact with counterparties they've never met; providers ship against locked
funds; platforms get one dispute taxonomy instead of N.

## Super-high-level architecture

```
        HUMANS (browser, console)        AI AGENTS (curl / SDK / SKILL.md)
                    \                          /
                ONE DUAL-USE API  ·  content-negotiated, self-describing
   ┌────────────────────────────────────────────────────────────────────┐
   │  1. JURISDICTION LAYER   22 regime registry · Nash-optimal select  │
   │  2. TRUST LAYER          consent/intent vault · mandate checks     │
   │  3. VALUE LAYER          conserved ledger · escrow hold/release    │
   │  4. RESOLUTION LAYER     regime-gated recall · dispute taxonomy    │
   └────────────────────────────────────────────────────────────────────┘
                    |                          |
        custody partners (funds)      rails: Pix · SEPA · FedNow · UPI …
```

Every operation is deterministic and conservation-checked (balances + escrow
holds are invariant), so the whole system is auditable by replay.

## Proof, today (not slideware)

- **Adversarially validated protocol.** Tvist ships as a payments-layer plugin
  in MIT/NANDA's Nanda Town agent test rig: 4 swarm scenarios, 10 adversarial
  validators. Every attack (unilateral clawback, escrow drain, over-mandate
  spend, friendly-fraud refund, off-regime dispute) **fails against the default
  ledger and is blocked by Tvist** on identical scenarios. 535 tests green.
- **Live, dual-use service.** The same logic runs as a hosted API + animated
  site with an in-page playground; agents integrate from a single SKILL.md
  (39 endpoint tests green).
- **Flagship use case.** DigiDoot — "a personal AI agent for every Indian
  citizen" — maps 1:1 onto Tvist as its settlement endpoint: Aadhaar-style
  consent → intent vault, UPI → regime, service journeys → escrow/recall.

## The ask / positioning

Tvist is complementary infrastructure: to networks (we operationalize their
intent standards), to custody providers (we're their missing rules engine), and
to agent platforms (we're the trust layer their checkout protocols defer). The
wedge is the cross-section nobody owns — and it compounds: every new rail,
protocol, and jurisdiction added to the registry makes the layer harder to
replicate.
