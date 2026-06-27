# Tvist on Nanda Town — the build, layer by layer

> **The pitch → [PITCH.md](PITCH.md).** Tvist is the **escrow + settlement-trust
> layer for agentic commerce**: programmable escrow, a cross-protocol intent
> vault, and irrevocability-aware recall for A2A push payments — the thing
> nobody built across the seven agent-payment protocols and the now-mandatory
> irrevocable rails (Pix, SEPA Instant, FedNow).

> **Scope.** Built into **one** Nanda Town layer — `payments` — and nothing
> else. It's a drop-in for the stock `Payments` protocol; the dispute / escrow /
> intent surface is purely additive. Two scenarios: `tvist_escrow` (the
> agentic-commerce headline) and `tvist_disputes` (the shared dispute
> foundation), each with its own adversarial gates.

This is the layer-by-layer build that backs the pitch: it maps the Tvist
product spec onto the `payments` layer and shows the build step by step and how
to run it.

---

## 0. Where Tvist sits in the 12-layer stack

Nanda Town decomposes an agent stack into 12 layers
([`docs/layers/`](../layers/)). Tvist is about **what happens to a payment
after it settles** — escrow hold/release, A2A recall, dispute mediation — so it
lives in exactly **one** layer: **`payments`** (`quote · pay · verify ·
refund`). We build there and nowhere else.

| Built into | What this submission ships |
|---|---|
| **`payments`** (the only layer touched) | `TvistPayments` plugin (`("payments","tvist")`) — programmable escrow, cross-protocol intent vault, irrevocable A2A recall, and evidence-gated dispute resolution |

Everything is additive on top of the stock `Payments` protocol — the plugin is
a drop-in, so any scenario can adopt it by flipping one line of YAML. The
product spec's other "layers" (content-addressed evidence, a reason-code
taxonomy) are *internal to the payments primitive*, not separate layer
implementations — keeping the submission a single, clean wedge.

---

## 1. The pitch — Tvist 2.0 → `tvist_escrow` (A2A · escrow · agentic commerce)

**Product spec (v2.0, §3–§4).** Push payments (Pix MED 2.0, SEPA Instant) are
irrevocable; the only sanctioned reversal cites a Verifiable-Intent mismatch
(`agent_exceeded_mandate`). `Tvist Escrow` holds funds until a typed condition
(delivery / time / attestation) is met. `Tvist Intent Vault` stores
cross-protocol intent records and adjudicates agent mandates. This is the layer
the seven agent-payment protocols and the now-mandatory irrevocable rails left
unbuilt — see [PITCH.md](PITCH.md).

**Nanda Town port (single `payments` layer).**

- **Plugin:** `settle_a2a` (marks irrevocable; `refund` then refuses it),
  `recall_a2a` (reverses **only** on an intent mismatch), `open_escrow` /
  `fund_escrow` / `satisfy_condition` / `release_escrow` (release gated on the
  condition), `store_intent` / `intent_covers` (mandate enforcement).
- **Scenario:** [`scenarios/tvist_escrow.yaml`](../../scenarios/tvist_escrow.yaml)
  — six flow types, three adversarial: an escrow drain without delivery, a
  unilateral clawback of a settled push payment, and an over-mandate agent
  settlement (plus their legitimate counterparts, including a *justified*
  intent-mismatch recall to prove correct reversals still work).
- **Adversarial validators:** `tvist_irrevocability`, `tvist_escrow_conditions`,
  `tvist_mandate` (+ shared `tvist_conservation`).

**The discrimination.** Under `payments: tvist`, all three gates hold →
**PASS**. Swap to `payments: prepaid_credits` and `refund` claws back the
irrevocable payment, the escrow-less ledger pays out with no delivery, and the
mandate-blind `pay` settles over budget → all three **FAIL**. That is the
charter's bar: *a validator that catches a class of attacks the default
reference plugin would fail.*

---

## 2. Foundation — Tvist 1.0 → `tvist_disputes` (the core v2 extends)

**Product spec (v0.1, §5.2).** A Klarna/card dispute fires; the Evidence Agent
pulls delivery proof; a win-probability model scores it; above the auto-fight
threshold (0.65) Tvist *represents* (fights), below it the issuer concedes a
refund. The wedge is that **friendly fraud** — the 40–80% of disputes where the
cardholder did receive the goods — is rebutted, not refunded. The escrow /
intent / recall primitives above are the same orchestration core applied to
irrevocable rails.

**Nanda Town port.**

- **Plugin:** `open_dispute → assemble_evidence → resolve_dispute`.
  `assemble_evidence` sums per-category weights over the cited, *verified*
  evidence into a deterministic win-probability; `resolve_dispute` represents
  at/above the threshold and refunds below it. Evidence is content-addressed
  (`sha256`), so a citation both names and pins the bytes.
- **Scenario:** [`scenarios/tvist_disputes.yaml`](../../scenarios/tvist_disputes.yaml)
  — 6 friendly-fraud disputes (merchant holds a verified `delivery_signed`
  proof) interleaved with 6 legitimate ones (no evidence).
- **Adversarial validators:** `tvist_evidence_gated` and `tvist_no_blind_refund`
  — both PASS under `tvist`, FAIL under `prepaid_credits` (which refunds the
  friendly fraud).

---

## 3. Build steps (what landed, in order)

1. **Plugin** —
   [`payments/tvist.py`](../../packages/nest-plugins-reference/nest_plugins_reference/payments/tvist.py):
   `TvistPayments` + `ReleaseCondition`, `TvistEscrow`, `TvistCase`,
   `IntentRecord`, `content_hash`. Registered in
   [`plugins.py`](../../packages/nest-core/nest_core/plugins.py).
2. **Scenarios** —
   [`tvist_escrow.py`](../../packages/nest-core/nest_core/scenarios_builtin/tvist_escrow.py)
   and
   [`tvist_disputes.py`](../../packages/nest-core/nest_core/scenarios_builtin/tvist_disputes.py),
   registered in [`scenarios.py`](../../packages/nest-core/nest_core/scenarios.py).
   A single orchestrator owns the plugin and drives the flows (the
   `receipt_reputation` auditor pattern), emitting a `tvist:` trace-line
   protocol.
3. **Validators** — six adversarial checks added to
   [`validators.py`](../../packages/nest-core/nest_core/validators.py) and
   registered under `tvist_escrow` / `tvist_disputes`.
4. **Tests** — plugin unit + property tests
   ([`test_tvist_payments.py`](../../packages/nest-plugins-reference/tests/test_tvist_payments.py))
   and end-to-end discrimination + determinism tests
   ([`test_tvist_scenarios.py`](../../packages/nest-core/tests/test_tvist_scenarios.py)).
5. **Docs** — the
   [problem brief](../hackathon/problems/12-payments-tvist-escrow-agentic-commerce.md),
   the [pitch](PITCH.md), and this walkthrough.

Determinism is preserved throughout: win-probabilities are a fixed function of
cited evidence, evidence identity is `sha256`, no wall-clock, no RNG in the
plugin. `uv run ruff check . && ruff format --check . && pyright && pytest` all
pass.

---

## 4. Run it

```bash
pip install -e packages/nest-core -e packages/nest-sdk -e packages/nest-plugins-reference -e packages/nest-cli

# Tvist 2.0 — irrevocable A2A + escrow + intent vault (all validators PASS)
nest run scenarios/tvist_escrow.yaml -o ./traces/tvist_escrow.jsonl
python -c "from pathlib import Path; from nest_core.validators import validate_trace; [print(('PASS' if r.passed else 'FAIL'), r.name, '-', r.detail) for r in validate_trace(Path('traces/tvist_escrow.jsonl'),'tvist_escrow')]"

# Tvist 1.0 — evidence-gated dispute deflection (all validators PASS)
nest run scenarios/tvist_disputes.yaml -o ./traces/tvist_disputes.jsonl
python -c "from pathlib import Path; from nest_core.validators import validate_trace; [print(('PASS' if r.passed else 'FAIL'), r.name, '-', r.detail) for r in validate_trace(Path('traces/tvist_disputes.jsonl'),'tvist_disputes')]"
```

To watch the attacks land, edit either YAML and change `payments: tvist` to
`payments: prepaid_credits`, re-run, and re-validate: the adversarial validators
flip to FAIL while conservation still holds — the precise leaks the gates close.

---

## 5. Six-dimension self-assessment (judging rubric)

- **Correctness** — funds conserved (property test under a 200-op random
  sequence); deterministic traces (byte-identical re-run tests).
- **Test rigor** — unit + property + end-to-end + adversarial-discrimination,
  both directions (tvist PASS / baseline FAIL) asserted.
- **API fit** — drop-in `Payments` protocol; the dispute/escrow surface is
  additive; the orchestrator pattern mirrors `receipt_reputation`.
- **Docs** — docstring-per-symbol with `Example::` blocks; this walkthrough;
  the problem brief.
- **Novelty** — the only payments submission that models *disputes* and
  *irrevocability* rather than transfer mechanics.
- **Persona fidelity** — a payments/risk engineer's submission: an explicit
  threat model (friendly fraud, unilateral clawback, escrow drain,
  over-mandate) with a validator per threat.
