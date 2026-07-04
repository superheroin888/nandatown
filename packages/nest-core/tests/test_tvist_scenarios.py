# SPDX-License-Identifier: Apache-2.0
"""End-to-end + adversarial-discrimination tests for the Tvist scenarios.

For both Tvist 2.0 (``tvist_escrow`` — the agentic-commerce headline) and Tvist
1.0 (``tvist_disputes`` — the shared dispute foundation):

1. **Discrimination** — the same scenario booted through the ``tvist`` payments
   plugin MUST pass every validator, and through the ``prepaid_credits`` reference
   plugin MUST fail the adversarial validator(s). This is the charter's bar:
   "a validator catches a class of attacks the default reference plugin would
   fail."
2. **Determinism** — same seed → byte-identical trace.

Everything runs the real ``Simulator`` via ``ScenarioRunner``; nothing past the
plugin boundary is mocked.
"""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from nest_core.plugins import PluginRegistry
from nest_core.runner import ScenarioRunner
from nest_core.scenario import ScenarioConfig
from nest_core.validators import validate_trace

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DISPUTES = _REPO_ROOT / "scenarios" / "tvist_disputes.yaml"
_ESCROW = _REPO_ROOT / "scenarios" / "tvist_escrow.yaml"
_REGION = _REPO_ROOT / "scenarios" / "tvist_region.yaml"
_DIGIDOOT = _REPO_ROOT / "scenarios" / "tvist_digidoot.yaml"


def _run(scenario_path: Path, payments: str, seed: int = 42) -> Path:
    """Boot a scenario with a chosen payments plugin; return the trace path."""
    config = ScenarioConfig.from_yaml(str(scenario_path))
    layers = config.layers.model_copy(update={"payments": payments})
    config = config.model_copy(update={"seed": seed, "layers": layers})
    tmp = tempfile.mkdtemp()
    trace_path = Path(tmp) / f"{config.task.type}_{payments}_{seed}.jsonl"
    output = config.output.model_copy(update={"trace": str(trace_path)})
    config = config.model_copy(update={"output": output})
    runner = ScenarioRunner(config, registry=PluginRegistry())
    asyncio.run(runner.run())
    return trace_path


def _results(trace: Path, scenario_type: str) -> dict[str, bool]:
    return {r.name: r.passed for r in validate_trace(trace, scenario_type)}


# ---------------------------------------------------------------------------
# Tvist 2.0 — irrevocable A2A + escrow + intent vault (the headline)
# ---------------------------------------------------------------------------


def test_escrow_tvist_passes_all_validators() -> None:
    """Under ``payments: tvist`` every escrow / A2A validator passes."""
    results = _results(_run(_ESCROW, "tvist"), "tvist_escrow")
    assert results, "no validators ran"
    assert all(results.values()), f"unexpected failures: {results}"


def test_escrow_baseline_fails_irrevocability_escrow_and_mandate() -> None:
    """``prepaid_credits`` bypasses all three A2A gates; only conservation holds."""
    results = _results(_run(_ESCROW, "prepaid_credits"), "tvist_escrow")
    assert results["tvist_irrevocability"] is False
    assert results["tvist_escrow_conditions"] is False
    assert results["tvist_mandate"] is False
    assert results["tvist_conservation"] is True


def test_escrow_deterministic() -> None:
    """Same seed → byte-identical escrow trace."""
    a = _run(_ESCROW, "tvist", seed=1337).read_bytes()
    b = _run(_ESCROW, "tvist", seed=1337).read_bytes()
    assert a == b


# ---------------------------------------------------------------------------
# Tvist 1.0 — dispute deflection (the shared foundation)
# ---------------------------------------------------------------------------


def test_disputes_tvist_passes_all_validators() -> None:
    """Under ``payments: tvist`` every dispute validator passes."""
    results = _results(_run(_DISPUTES, "tvist"), "tvist_disputes")
    assert results, "no validators ran"
    assert all(results.values()), f"unexpected failures: {results}"


def test_disputes_baseline_leaks_friendly_fraud() -> None:
    """``prepaid_credits`` refunds friendly fraud, so the evidence gate fails."""
    results = _results(_run(_DISPUTES, "prepaid_credits"), "tvist_disputes")
    assert results["tvist_evidence_gated"] is False
    assert results["tvist_no_blind_refund"] is False
    assert results["tvist_conservation"] is True


def test_disputes_deterministic() -> None:
    """Same seed → byte-identical dispute trace."""
    a = _run(_DISPUTES, "tvist", seed=7).read_bytes()
    b = _run(_DISPUTES, "tvist", seed=7).read_bytes()
    assert a == b


# ---------------------------------------------------------------------------
# Tvist region negotiation — the regime is chosen ahead of the transaction
# ---------------------------------------------------------------------------


def test_region_tvist_passes_all_validators() -> None:
    """Under ``payments: tvist`` a region is negotiated and adhered to throughout."""
    results = _results(_run(_REGION, "tvist"), "tvist_region")
    assert results, "no validators ran"
    assert all(results.values()), f"unexpected failures: {results}"


def test_region_baseline_settles_ungoverned_and_breaks_regime() -> None:
    """``prepaid_credits`` cannot negotiate or enforce a regime, so both checks fail."""
    results = _results(_run(_REGION, "prepaid_credits"), "tvist_region")
    assert results["tvist_region_agreed"] is False
    assert results["tvist_region_adherence"] is False
    assert results["tvist_conservation"] is True


def test_region_deterministic() -> None:
    """Same seed → byte-identical region trace."""
    a = _run(_REGION, "tvist", seed=99).read_bytes()
    b = _run(_REGION, "tvist", seed=99).read_bytes()
    assert a == b


# ---------------------------------------------------------------------------
# DigiDoot use case — a personal agent per Indian citizen, settled via Tvist
# ---------------------------------------------------------------------------


def test_digidoot_tvist_protects_every_citizen() -> None:
    """Under ``payments: tvist`` every citizen flow is consent-bound and UPI-governed."""
    results = _results(_run(_DIGIDOOT, "tvist"), "tvist_digidoot")
    assert results, "no validators ran"
    assert all(results.values()), f"unexpected failures: {results}"


def test_digidoot_baseline_breaks_consent_regime_and_escrow() -> None:
    """``prepaid_credits`` has no consent, no regime, no escrow → protections fail."""
    results = _results(_run(_DIGIDOOT, "prepaid_credits"), "tvist_digidoot")
    assert results["tvist_digidoot_consent"] is False
    assert results["tvist_mandate"] is False
    assert results["tvist_escrow_conditions"] is False
    assert results["tvist_conservation"] is True


def test_digidoot_deterministic() -> None:
    """Same seed → byte-identical DigiDoot trace."""
    a = _run(_DIGIDOOT, "tvist", seed=11).read_bytes()
    b = _run(_DIGIDOOT, "tvist", seed=11).read_bytes()
    assert a == b
