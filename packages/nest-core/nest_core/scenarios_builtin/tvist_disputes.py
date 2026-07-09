# SPDX-License-Identifier: Apache-2.0
"""Tvist 1.0 scenario — evidence-gated dispute deflection over card / BNPL rails.

A swarm of merchants settles card payments from cardholders; a fraction of those
cardholders then file disputes. Two populations are interleaved:

* **friendly-fraud** disputes — the cardholder *did* receive the goods, and the
  merchant holds a verified ``delivery_signed`` proof (plus a corroborating
  device signal). An evidence-aware issuer represents and **wins** these; the
  reversal must never execute.
* **legitimate** disputes — the goods never arrived and the merchant has nothing
  to cite. The issuer concedes a **refund**.

One **orchestrator** owns a single instance of the configured ``payments:``
plugin and drives the whole pipeline (triage → evidence assembly →
win-probability → represent-or-refund), broadcasting a ``tvist:`` trace-line
protocol the validators read. The discrimination is in the *outcome* line:

* Under ``payments: tvist`` the orchestrator runs the evidence gate
  (:meth:`~nest_plugins_reference.payments.tvist.TvistPayments.resolve_dispute`)
  — friendly fraud is ``represented``, so the validator PASSES.
* Under a generic plugin (e.g. ``prepaid_credits``) the only tool is ``refund``,
  so the naive issuer refunds *every* dispute — friendly fraud is reimbursed and
  the same validator FAILS.

The evidence and win-probability lines are derived from the manifest and emitted
identically under either plugin, so the validator judges the issuer's *decision*
against the evidence it provably had.

Trace-line protocol (``:``-delimited, carried in broadcast bodies):

* ``tvist:settle:<txn>:<rail>:<cardholder>:<merchant>:<amount>``
* ``tvist:evidence:<txn>:<hash8>:<verified 0|1>:<kind>``
* ``tvist:score:<txn>:<win_probability:.6f>:<threshold:.6f>``
* ``tvist:outcome:<txn>:<represented|refunded>:<merchant_won 0|1>``
* ``tvist:conservation:<total_system_funds>``

Example::

    agents = tvist_disputes_factory(config, plugins)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from nest_plugins_reference.payments.tvist import (
    DEFAULT_FIGHT_THRESHOLD,
    EVIDENCE_WEIGHTS,
)

from nest_core.scenario import ScenarioConfig
from nest_core.sim.agent import AgentContext, StateMachineAgent
from nest_core.types import AgentId, Money, PaymentRef


@dataclass
class DisputeTxn:
    """One settled payment and the dispute filed against it.

    ``evidence`` lists ``(kind, artifact)`` pairs the merchant can cite. A
    friendly-fraud txn carries delivery-grade evidence; a legitimate one carries
    none.

    Example::

        txn = DisputeTxn("t0", AgentId("m0"), AgentId("c0"), 200, "fraud",
                         [("delivery_signed", {"ref": "t0"})], friendly_fraud=True)
    """

    txn_id: str
    merchant: AgentId
    cardholder: AgentId
    amount: int
    reason_code: str
    evidence: list[tuple[str, dict[str, Any]]]
    friendly_fraud: bool


def _expected_score(txn: DisputeTxn) -> float:
    """Deterministic win-probability the cited evidence implies (manifest-derived).

    Mirrors the plugin's scoring so the emitted ``tvist:score`` line is identical
    under either payments plugin — the validator compares this against the
    issuer's actual decision.

    Example::

        s = _expected_score(txn)
    """
    return min(1.0, sum(EVIDENCE_WEIGHTS.get(kind, 0.0) for kind, _ in txn.evidence))


class TvistDisputeOrchestrator(StateMachineAgent):
    """Owns the payments plugin and runs the dispute pipeline for every txn.

    Settlement happens on ``on_start``; a ``resolve:`` pulse one tick later runs
    the disputes after all settlements are recorded, so the trace order is
    deterministic regardless of agent scheduling.

    Example::

        orch = TvistDisputeOrchestrator(AgentId("orchestrator"), manifest, threshold=0.65)
    """

    def __init__(
        self,
        agent_id: AgentId,
        manifest: list[DisputeTxn],
        threshold: float,
    ) -> None:
        self._id = agent_id
        self._manifest = manifest
        self._threshold = threshold
        self._payments: Any = None

    async def on_start(self, ctx: AgentContext) -> None:
        """Instantiate the plugin, settle every payment, schedule resolution.

        Example::

            await orch.on_start(ctx)
        """
        payments_cls = ctx.plugins.get("payments")
        self._payments = payments_cls() if isinstance(payments_cls, type) else payments_cls
        for txn in self._manifest:
            await self._settle(txn)
            await ctx.broadcast(
                f"tvist:settle:{txn.txn_id}:card:{txn.cardholder}:"
                f"{txn.merchant}:{txn.amount}".encode()
            )
            for kind, artifact in txn.evidence:
                verified = self._register_evidence(kind, artifact)
                await ctx.broadcast(
                    f"tvist:evidence:{txn.txn_id}:{verified[0]}:{verified[1]}:{kind}".encode()
                )
        await ctx.schedule(1.0, b"resolve:")

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        """On the resolve pulse, adjudicate every dispute and report conservation.

        Example::

            await orch.on_message(ctx, orch_id, b"resolve:")
        """
        if not payload.startswith(b"resolve:"):
            return
        for txn in self._manifest:
            score = _expected_score(txn)
            await ctx.broadcast(
                f"tvist:score:{txn.txn_id}:{score:.6f}:{self._threshold:.6f}".encode()
            )
            outcome, merchant_won = await self._adjudicate(txn, score)
            await ctx.broadcast(
                f"tvist:outcome:{txn.txn_id}:{outcome}:{int(merchant_won)}".encode()
            )
        await ctx.broadcast(f"tvist:conservation:{self._total_funds()}".encode())

    # -- plugin-aware helpers ---------------------------------------------

    async def _settle(self, txn: DisputeTxn) -> None:
        """Record the cardholder→merchant payment on the shared ledger."""
        ref = PaymentRef(txn.txn_id)
        handle = self._payer_handle(txn.cardholder)
        await handle.pay(txn.merchant, Money(amount=txn.amount), ref)

    def _register_evidence(self, kind: str, artifact: dict[str, Any]) -> tuple[str, int]:
        """Register evidence if the plugin supports it; return (hash8, verified).

        A generic plugin cannot store evidence, so verification is asserted from
        the manifest kind (delivery-grade evidence is, by construction, genuine).
        """
        record = {"kind": kind, **artifact}
        if hasattr(self._payments, "register_evidence"):
            h = self._payments.register_evidence(record)
            return h[:8], int(self._payments.verify_evidence(h))
        from nest_plugins_reference.payments.tvist import content_hash

        return content_hash(record)[:8], 1

    async def _adjudicate(self, txn: DisputeTxn, score: float) -> tuple[str, bool]:
        """Resolve one dispute through the configured plugin.

        Tvist runs the evidence gate; a generic plugin can only refund, which is
        exactly the friendly-fraud leak the validator is built to catch.
        """
        ref = PaymentRef(txn.txn_id)
        if hasattr(self._payments, "open_dispute"):
            case = self._payments.open_dispute(ref, txn.reason_code, txn.cardholder)
            hashes = [
                self._payments.register_evidence({"kind": kind, **artifact})
                for kind, artifact in txn.evidence
            ]
            self._payments.assemble_evidence(case.case_id, hashes)
            return self._payments.resolve_dispute(case.case_id, self._threshold)
        await self._payments.refund(ref)
        return "refunded", False

    def _payer_handle(self, payer: AgentId) -> Any:
        """A plugin handle whose ``pay`` debits *payer*, over the shared ledger."""
        cls = cast("type[Any]", type(self._payments))
        shared = self._shared_stores()
        try:
            return cls(payer, initial_balance=0, **shared)
        except TypeError:
            return self._payments

    def _shared_stores(self) -> dict[str, Any]:
        """The ledger dicts shared across payer handles (best-effort by attribute)."""
        stores: dict[str, Any] = {}
        for kw, attr in (("balances", "_balances"), ("payments", "_payments")):
            if hasattr(self._payments, attr):
                stores[kw] = getattr(self._payments, attr)
        return stores

    def _total_funds(self) -> int:
        """Total conserved funds reported by the plugin (balances + holds)."""
        if hasattr(self._payments, "total_funds"):
            total: int = self._payments.total_funds()
            return total
        balances: dict[AgentId, int] = getattr(self._payments, "_balances", {})
        return sum(balances.values())


class _MerchantAgent(StateMachineAgent):
    """An inert roster member representing a merchant in the swarm.

    Example::

        m = _MerchantAgent(AgentId("merchant-0"))
    """

    def __init__(self, agent_id: AgentId) -> None:
        self._id = agent_id

    async def on_start(self, ctx: AgentContext) -> None:
        """No-op; settlements are driven centrally by the orchestrator."""
        return


def _build_manifest(config: ScenarioConfig) -> tuple[list[DisputeTxn], list[AgentId]]:
    """Build a deterministic mix of friendly-fraud and legitimate disputes.

    ``task.config`` keys ``friendly_fraud`` and ``legitimate`` set the population
    sizes (defaults 6 and 6). Friendly-fraud txns carry ``delivery_signed`` +
    ``device_match`` (score 0.70, above threshold); legitimate txns carry no
    evidence (score 0.0).

    Example::

        manifest, merchants = _build_manifest(config)
    """
    cfg = config.task.config
    n_fraud = int(cfg.get("friendly_fraud", 6))
    n_legit = int(cfg.get("legitimate", 6))

    manifest: list[DisputeTxn] = []
    merchants: list[AgentId] = []
    idx = 0
    for i in range(n_fraud):
        merchant = AgentId(f"merchant-{idx}")
        merchants.append(merchant)
        manifest.append(
            DisputeTxn(
                txn_id=f"ff-{i}",
                merchant=merchant,
                cardholder=AgentId(f"cardholder-{idx}"),
                amount=100 + i * 10,
                reason_code="fraud",
                evidence=[
                    ("delivery_signed", {"ref": f"ff-{i}", "carrier": "postnord"}),
                    ("device_match", {"ref": f"ff-{i}"}),
                ],
                friendly_fraud=True,
            )
        )
        idx += 1
    for i in range(n_legit):
        merchant = AgentId(f"merchant-{idx}")
        merchants.append(merchant)
        manifest.append(
            DisputeTxn(
                txn_id=f"legit-{i}",
                merchant=merchant,
                cardholder=AgentId(f"cardholder-{idx}"),
                amount=120 + i * 10,
                reason_code="goods_not_received",
                evidence=[],
                friendly_fraud=False,
            )
        )
        idx += 1
    return manifest, merchants


def tvist_disputes_factory(
    config: ScenarioConfig,
    plugins: dict[str, Any],
) -> dict[AgentId, StateMachineAgent]:
    """Create the orchestrator, merchants, and a seeded shared ledger.

    The cardholders are funded in the shared balances dict so their settlements
    clear; the orchestrator owns the single plugin instance and resolves every
    dispute through it. Runs unchanged under ``payments: tvist`` (gate enforced →
    validator PASSES) and ``payments: prepaid_credits`` (blind refunds →
    validator FAILS).

    Example::

        agents = tvist_disputes_factory(config, plugins)
    """
    manifest, merchants = _build_manifest(config)
    threshold = float(config.task.config.get("threshold", DEFAULT_FIGHT_THRESHOLD))

    balances: dict[AgentId, int] = {}
    for txn in manifest:
        balances[txn.cardholder] = balances.get(txn.cardholder, 0) + txn.amount
        balances.setdefault(txn.merchant, 0)

    payments_cls = plugins.get("payments")
    if isinstance(payments_cls, type):
        try:
            plugins["payments"] = payments_cls(
                AgentId("tvist"), initial_balance=0, balances=balances, payments={}
            )
        except TypeError:
            plugins["payments"] = payments_cls(AgentId("tvist"), initial_balance=0)

    agents: dict[AgentId, StateMachineAgent] = {}
    orchestrator_id = AgentId("orchestrator")
    agents[orchestrator_id] = TvistDisputeOrchestrator(orchestrator_id, manifest, threshold)
    for merchant in merchants:
        agents[merchant] = _MerchantAgent(merchant)
    return agents
