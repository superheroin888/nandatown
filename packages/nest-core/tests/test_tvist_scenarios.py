# SPDX-License-Identifier: Apache-2.0
"""End-to-end + adversarial-discrimination tests for the Tvist escrow scenario.

For Tvist 2.0 (``tvist_escrow`` — irrevocable A2A + escrow + intent vault):

1. **Discrimination** — the same scenario booted through the ``tvist`` payments
   plugin MUST pass every validator, and through the ``prepaid_credits`` reference
   plugin MUST fail the three adversarial gates (irrevocability, escrow-condition,
   mandate). This is the charter's bar: "a validator catches a class of attacks
   the default reference plugin would fail."
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
_ESCROW = _REPO_ROOT / "scenarios" / "tvist_escrow.yaml"


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
