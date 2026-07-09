## What this is

**Tvist — a regime-governed settlement-trust layer on the `payments` layer.**
One problem, one layer. The governing dispute regime is negotiated **before
funds move** (Nash-bargaining selection over a 22-jurisdiction registry), then
four gates fire around every transaction: consent/mandate (with attenuated
delegation), delivery-gated escrow, regime-gated irrevocable recall, and
evidence-gated dispute deflection grounded in a civil/commercial-law taxonomy.
Includes a deterministic x402-style settle (single-use nonce, consent-capped).

**Differentiation from the merged `escrow` plugin (per the no-re-issue rule):**
that plugin is a buyer/seller/arbiter bps-split escrow. Here, escrow is one of
four gates inside a jurisdictional regime — the submission's core is the
negotiated-region primitive, the intent vault, regime-gated recall, and the
legal taxonomy, none of which exist in the tree.

## What ships

- Plugin `("payments","tvist")` — drop-in for the stock `Payments` protocol;
  everything additive. Deterministic: no wall-clock, no RNG; conservation
  invariant (balances + escrow holds) throughout.
- 4 scenarios + YAMLs: `tvist_region`, `tvist_escrow`, `tvist_disputes`,
  `tvist_digidoot` (end-to-end citizen-agent use case).
- 10 adversarial validators — each **PASSes under `tvist` and FAILs under
  `prepaid_credits` on identical scenarios** (region agreement, Nash
  optimality, regime adherence, irrevocability, escrow conditions, mandate,
  evidence gate, no-blind-refund, DigiDoot consent, conservation).
- Problem brief `docs/hackathon/problems/11-payments-tvist-escrow-agentic-commerce.md`,
  docs under `docs/tvist/`, `examples/digidoot/`.

## Reproduce

```bash
uv sync && uv run ruff check . && uv run ruff format --check . \
  && uv run pyright && uv run pytest -v
# discrimination, e.g.:
nest run scenarios/tvist_region.yaml -o ./traces/r.jsonl
python -c "from pathlib import Path; from nest_core.validators import validate_trace; \
[print(('PASS' if r.passed else 'FAIL'), r.name) for r in validate_trace(Path('traces/r.jsonl'),'tvist_region')]"
# flip payments: tvist -> prepaid_credits in the YAML and re-run: gates FAIL.
```

CI state on this branch (rebased onto main, 2026-07-08): ruff ✓ · format ✓ ·
pyright (strict) ✓ · **821 tests passed** · scenario + validator reproduce
block re-verified against the trace.
