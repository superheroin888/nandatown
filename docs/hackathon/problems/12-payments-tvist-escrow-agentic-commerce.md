---
title: Escrow + intent-vault + irrevocable recall for agentic commerce (Tvist)
layer: payments
difficulty: hard
---

# Escrow + intent-vault + irrevocable recall for agentic commerce (Tvist)

## Motivation

The default payments plugin
[`nest_plugins_reference/payments/prepaid_credits.py`](../../../packages/nest-plugins-reference/nest_plugins_reference/payments/prepaid_credits.py)
has exactly one reversal primitive: `refund(ref)`, which moves the full
amount back, unconditionally, forever. That is the wrong model for the rails
agents are starting to transact on.

Two facts make an unconditional `refund` actively dangerous as **agentic
commerce** scales over **account-to-account (A2A)** rails:

1. **Irrevocability.** Push payments — Pix, SEPA Instant, FedNow — are
   settlement-final by regulation (Pix MED 2.0 mandatory Feb 2026; SCT Inst
   mandatory send Oct 2025, 10-second finality). Once they land they cannot
   be unilaterally clawed back; the receiving institution must *affirmatively*
   unwind, and only on proof — e.g. a Verifiable-Intent mismatch showing an
   agent exceeded its mandate. A plugin whose only tool is `refund` lets either
   party reverse a settled push payment at will: the exact failure the
   Pix/SEPA rulebooks exist to prevent.

2. **Agents spending under a mandate.** When an agent transacts on a
   consumer's behalf, "did the user authorise *this*?" becomes the dominant
   dispute. The defence is escrow (hold funds until delivery/attestation/time
   is verifiable) plus an intent vault (the budget/allowlist the agent was
   authorised under). Seven agent-payment protocols shipped in 2025–26 (MC
   Agent Pay + Verifiable Intent, Visa Intelligent Commerce, Amex APP, Google
   AP2, OpenAI ACP, OKX APP, Coinbase x402) — none provides a rail-agnostic,
   dispute-aware escrow primitive. `prepaid_credits` models none of it.

Anyone simulating A2A push payments, agent-mediated commerce, or marketplace
escrow needs a payments layer that knows a settlement-final rail from a
reversible one and an in-mandate payment from an over-mandate one.

## Success criteria

- Ship a payments plugin (suggested name: `tvist`) registered as
  `("payments", "tvist")` in
  [`nest_core/plugins.py`](../../../packages/nest-core/nest_core/plugins.py).
  It satisfies the existing `Payments` protocol from
  [`nest_core/layers/payments.py`](../../../packages/nest-core/nest_core/layers/payments.py)
  — `pay`/`verify_payment`/`refund`/`quote` still work, so it is a drop-in —
  and adds, additively:
  - **Irrevocable A2A:** `settle_a2a` marks a payment irrevocable so `refund`
    refuses it; `recall_a2a` reverses it **only** on a Verifiable-Intent
    mismatch (the agent exceeded its mandate).
  - **Programmable escrow:** `open_escrow` / `fund_escrow` /
    `satisfy_condition` / `release_escrow` hold funds until a typed
    `ReleaseCondition` (delivery / time / attestation) is satisfied; an
    unsatisfied or contested release is refused.
  - **Intent vault:** `store_intent` / `intent_covers` enforce an agent
    mandate (budget, merchant allowlist) at settlement time.
  - **Conservation:** total balances + escrow holds are invariant.
- Ship **adversarial validators** that catch attacks the default plugin
  would wave through, each FAILing under `prepaid_credits` and PASSing under
  `tvist` on the same scenario:
  1. *Unilateral clawback:* a settled irrevocable A2A payment is reversed only
     when a recall cites an intent mismatch.
  2. *Escrow drain:* funds are released only when the release condition is
     satisfied.
  3. *Over-mandate settlement:* an agent payment settles only inside its
     stored mandate.
- Ship `scenarios/tvist_escrow.yaml` with a mix of legitimate and adversarial
  flows (including a *justified* intent-mismatch recall, to prove correct
  reversals still work). Validators pass under `tvist`, fail under
  `prepaid_credits`. Traces are deterministic.

## Suggested approach pointers

- Keep one shared ledger (`balances` + `payments` dicts) like
  `prepaid_credits`, and add side stores for `escrows`, `evidence`,
  `intents`, and per-payment `settled_meta` (the irrevocable flag).
- Content-address evidence (delivery proofs) with sorted-key JSON `sha256` —
  borrow the canonicalisation idea from the `agent_receipts` trust plugin.
- Drive the scenario from one **orchestrator** that owns the configured
  plugin instance (the `receipt_reputation` auditor is the template) and
  branches on capability (`hasattr(plugin, "settle_a2a")`): run the gates
  under `tvist`, fall back to naive `pay`/`refund` under a generic plugin.
  Emit a `:`-delimited `tvist:` trace-line protocol the validators parse.

## Anti-patterns

- Don't make `recall_a2a` a renamed `refund`. A recall must require a
  verifiable-intent mismatch; an unconditional one is the attack.
- Don't ship "escrow" that pays the payee at open time — release must be
  gated on the condition, deterministically.
- Don't decide anything with an unseeded RNG or a wall-clock — Tier 1 is
  deterministic and the validators read the trace.
- Don't hold real funds or model a custody licence; orchestrate a notional
  ledger only (the product is a thin orchestration layer over regulated
  custody partners).

## Out of scope

- Real network settlement (Pix/SEPA wire formats).
- Multi-asset / FX. One notional `credits` currency is sufficient.
- A live cryptographic Verifiable-Intent verifier — model the mandate as a
  stored record with a budget and allowlist.
