# SPDX-License-Identifier: Apache-2.0
"""Tvist 2.0 scenario — irrevocable A2A push payments, escrow, and the intent vault.

A swarm of agents transacts over irrevocable rails (Pix, SEPA Instant). One
**orchestrator** owns the configured ``payments:`` plugin and drives six flow
types — three of them adversarial — broadcasting a ``tvist:`` trace-line protocol
the validators read. The discrimination is, as in Tvist 1.0, in what the plugin
*lets happen*:

* **escrow_legit** — open + fund an escrow, satisfy its delivery condition,
  release. Funds reach the payee.
* **escrow_attack** — fund an escrow but never satisfy the condition, then attempt
  release. Tvist refuses; a generic plugin with no escrow pays out immediately —
  a release with no delivery (``tvist_escrow_conditions`` FAILS for the baseline).
* **clawback_attack** — settle an irrevocable A2A payment *within* mandate, then
  the payer attempts a recall with no intent mismatch. Tvist's ``recall_a2a``
  refuses; a generic ``refund`` reverses it — a unilateral clawback of an
  irrevocable payment (``tvist_irrevocability`` FAILS for the baseline).
* **legit_recall** — an agent settles *outside* its mandate; the intent vault
  shows the mismatch and the recall is honoured. Both plugins reverse it; this
  proves a *justified* reversal is still allowed.
* **over_mandate_attack** — an agent attempts a settlement above its mandate
  budget. Tvist refuses before funds move; a mandate-blind plugin settles it
  (``tvist_mandate`` FAILS for the baseline).
* **within_mandate** — an agent settles inside its mandate; honoured by both.

Trace-line protocol (``:``-delimited, carried in broadcast bodies):

* ``tvist:settle:<txn>:<rail>:<payer>:<payee>:<amount>:<irrevocable 0|1>``
* ``tvist:escrow:<eid>:<payer>:<payee>:<amount>:<condition_type>``
* ``tvist:release:<eid>:<condition_met 0|1>:<released 0|1>``
* ``tvist:recall:<txn>:<intent_valid 0|1>:<reversed 0|1>``
* ``tvist:mandate:<txn>:<agent>:<within_mandate 0|1>:<settled 0|1>``
* ``tvist:conservation:<total_system_funds>``

Example::

    agents = tvist_escrow_factory(config, plugins)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from nest_core.scenario import ScenarioConfig
from nest_core.sim.agent import AgentContext, StateMachineAgent
from nest_core.types import AgentId, Money, PaymentRef


@dataclass
class EscrowFlow:
    """One legitimate or adversarial A2A / escrow flow in the manifest.

    Example::

        flow = EscrowFlow("escrow_attack", AgentId("p0"), AgentId("q0"), 300)
    """

    kind: str
    payer: AgentId
    payee: AgentId
    amount: int
    flow_id: str = ""


class TvistEscrowOrchestrator(StateMachineAgent):
    """Owns the payments plugin and runs every A2A / escrow flow.

    Settlements and escrow funding happen on ``on_start``; the contests, releases,
    and recalls run on a ``resolve:`` pulse one tick later, so trace order is
    deterministic.

    Example::

        orch = TvistEscrowOrchestrator(AgentId("orchestrator"), flows)
    """

    def __init__(self, agent_id: AgentId, flows: list[EscrowFlow]) -> None:
        self._id = agent_id
        self._flows = flows
        self._payments: Any = None
        self._is_tvist = False

    async def on_start(self, ctx: AgentContext) -> None:
        """Instantiate the plugin and run the settle/fund phase of every flow.

        Example::

            await orch.on_start(ctx)
        """
        payments_cls = ctx.plugins.get("payments")
        self._payments = payments_cls() if isinstance(payments_cls, type) else payments_cls
        self._is_tvist = hasattr(self._payments, "settle_a2a")
        for flow in self._flows:
            await self._settle_phase(ctx, flow)
        await ctx.schedule(1.0, b"resolve:")

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        """On the resolve pulse, run the contest/release/recall phase + conservation.

        Example::

            await orch.on_message(ctx, orch_id, b"resolve:")
        """
        if not payload.startswith(b"resolve:"):
            return
        for flow in self._flows:
            await self._resolve_phase(ctx, flow)
        await ctx.broadcast(f"tvist:conservation:{self._total_funds()}".encode())

    # -- settle / fund phase ----------------------------------------------

    async def _settle_phase(self, ctx: AgentContext, flow: EscrowFlow) -> None:
        """Open+fund escrows and lay down A2A settlements for one flow."""
        if flow.kind in ("escrow_legit", "escrow_attack"):
            await self._open_escrow(ctx, flow)
        elif flow.kind in ("clawback_attack", "legit_recall"):
            irrevocable = await self._settle_a2a(flow)
            await ctx.broadcast(
                f"tvist:settle:{flow.flow_id}:pix:{flow.payer}:"
                f"{flow.payee}:{flow.amount}:{int(irrevocable)}".encode()
            )

    async def _open_escrow(self, ctx: AgentContext, flow: EscrowFlow) -> None:
        """Open and fund an escrow (Tvist), or naively pre-pay (generic)."""
        if self._is_tvist:
            from nest_plugins_reference.payments.tvist import ReleaseCondition

            cond = ReleaseCondition(type="delivery_proof", expected="delivered_signed")
            self._payments.open_escrow(
                flow.flow_id, flow.payer, flow.payee, flow.amount, cond, rail="pix"
            )
            self._payments.fund_escrow(flow.flow_id)
        else:
            # No escrow primitive: the naive thing is to pay the payee up front.
            handle = self._payer_handle(flow.payer)
            await handle.pay(flow.payee, Money(amount=flow.amount), PaymentRef(flow.flow_id))
        await ctx.broadcast(
            f"tvist:escrow:{flow.flow_id}:{flow.payer}:{flow.payee}:"
            f"{flow.amount}:delivery_proof".encode()
        )

    async def _settle_a2a(self, flow: EscrowFlow) -> bool:
        """Settle an irrevocable push payment; returns whether it is irrevocable."""
        ref = PaymentRef(flow.flow_id)
        handle = self._payer_handle(flow.payer)
        if self._is_tvist:
            await handle.settle_a2a(flow.payee, Money(amount=flow.amount), ref, rail="pix")
            return True
        await handle.pay(flow.payee, Money(amount=flow.amount), ref)
        return True  # the rail is irrevocable regardless of the plugin's awareness

    # -- contest / release / recall phase ---------------------------------

    async def _resolve_phase(self, ctx: AgentContext, flow: EscrowFlow) -> None:
        """Run the second-phase action (and its attack) for one flow."""
        if flow.kind == "escrow_legit":
            await self._release_escrow(ctx, flow, satisfy=True)
        elif flow.kind == "escrow_attack":
            await self._release_escrow(ctx, flow, satisfy=False)
        elif flow.kind == "clawback_attack":
            await self._recall(ctx, flow, mismatch=False)
        elif flow.kind == "legit_recall":
            await self._recall(ctx, flow, mismatch=True)
        elif flow.kind == "over_mandate_attack":
            await self._mandated_settle(ctx, flow, within=False)
        elif flow.kind == "within_mandate":
            await self._mandated_settle(ctx, flow, within=True)

    async def _release_escrow(self, ctx: AgentContext, flow: EscrowFlow, *, satisfy: bool) -> None:
        """Attempt to release; condition is satisfied only for the legit flow."""
        condition_met = 0
        released = 0
        if self._is_tvist:
            if satisfy:
                self._payments.satisfy_condition(flow.flow_id, "delivered_signed")
                condition_met = 1
            try:
                self._payments.release_escrow(flow.flow_id)
                released = 1
            except ValueError:
                released = 0
        else:
            # Generic plugin already paid the payee at open time: a release with no
            # delivery for the attack flow, a (vacuously) satisfied one otherwise.
            condition_met = 1 if satisfy else 0
            released = 1
        await ctx.broadcast(f"tvist:release:{flow.flow_id}:{condition_met}:{released}".encode())

    async def _recall(self, ctx: AgentContext, flow: EscrowFlow, *, mismatch: bool) -> None:
        """Attempt to recall a settled A2A payment; honoured only on a mismatch."""
        intent_valid = int(mismatch)
        reversed_ = 0
        ref = PaymentRef(flow.flow_id)
        if self._is_tvist:
            from nest_plugins_reference.payments.tvist import IntentRecord

            # Record a mandate that the settlement either fits (clawback) or breaches.
            budget = flow.amount - 1 if mismatch else flow.amount
            self._payments.store_intent(
                IntentRecord(f"intent-{flow.flow_id}", flow.payer, budget=budget)
            )
            reversed_ = int(self._payments.recall_a2a(ref, f"intent-{flow.flow_id}"))
        else:
            # Generic plugin: refund reverses any settled payment unconditionally.
            try:
                await self._payments.refund(ref)
                reversed_ = 1
            except ValueError:
                reversed_ = 0
        await ctx.broadcast(f"tvist:recall:{flow.flow_id}:{intent_valid}:{reversed_}".encode())

    async def _mandated_settle(self, ctx: AgentContext, flow: EscrowFlow, *, within: bool) -> None:
        """Settle an agent payment that is inside (within) or above (attack) its mandate."""
        within_mandate = int(within)
        settled = 0
        ref = PaymentRef(flow.flow_id)
        if self._is_tvist:
            from nest_plugins_reference.payments.tvist import IntentRecord

            budget = flow.amount if within else flow.amount - 1
            intent_id = f"mandate-{flow.flow_id}"
            self._payments.store_intent(IntentRecord(intent_id, flow.payer, budget=budget))
            handle = self._payer_handle(flow.payer)
            try:
                await handle.settle_a2a(
                    flow.payee, Money(amount=flow.amount), ref, rail="pix", intent_ref=intent_id
                )
                settled = 1
            except ValueError:
                settled = 0
        else:
            # Mandate-blind plugin: it pays regardless of any budget.
            handle = self._payer_handle(flow.payer)
            try:
                await handle.pay(flow.payee, Money(amount=flow.amount), ref)
                settled = 1
            except ValueError:
                settled = 0
        await ctx.broadcast(
            f"tvist:mandate:{flow.flow_id}:{flow.payer}:{within_mandate}:{settled}".encode()
        )

    # -- helpers -----------------------------------------------------------

    def _payer_handle(self, payer: AgentId) -> Any:
        """A plugin handle whose ``pay``/``settle_a2a`` debits *payer*.

        Shares every ledger store the plugin exposes, so a settlement made through
        the handle is visible to the orchestrator's main instance when it later
        recalls or scores against the same intents and metadata.
        """
        cls = cast("type[Any]", type(self._payments))
        shared: dict[str, Any] = {}
        for kw, attr in (
            ("balances", "_balances"),
            ("payments", "_payments"),
            ("escrows", "_escrows"),
            ("cases", "_cases"),
            ("evidence", "_evidence"),
            ("intents", "_intents"),
            ("settled_meta", "_settled_meta"),
        ):
            if hasattr(self._payments, attr):
                shared[kw] = getattr(self._payments, attr)
        try:
            return cls(payer, initial_balance=0, **shared)
        except TypeError:
            return self._payments

    def _total_funds(self) -> int:
        """Total conserved funds reported by the plugin (balances + escrow holds)."""
        if hasattr(self._payments, "total_funds"):
            total: int = self._payments.total_funds()
            return total
        balances: dict[AgentId, int] = getattr(self._payments, "_balances", {})
        return sum(balances.values())


class _AgentParty(StateMachineAgent):
    """An inert roster member representing a payer/payee in the swarm.

    Example::

        p = _AgentParty(AgentId("payer-0"))
    """

    def __init__(self, agent_id: AgentId) -> None:
        self._id = agent_id

    async def on_start(self, ctx: AgentContext) -> None:
        """No-op; all flows are driven centrally by the orchestrator."""
        return


_FLOW_KINDS = (
    "escrow_legit",
    "escrow_attack",
    "clawback_attack",
    "legit_recall",
    "over_mandate_attack",
    "within_mandate",
)


def _build_flows(config: ScenarioConfig) -> tuple[list[EscrowFlow], list[AgentId]]:
    """Build a deterministic mix of legitimate and adversarial flows.

    ``task.config.per_kind`` (default 2) sets how many of each of the six flow
    types to generate.

    Example::

        flows, parties = _build_flows(config)
    """
    per_kind = int(config.task.config.get("per_kind", 2))
    flows: list[EscrowFlow] = []
    parties: list[AgentId] = []
    idx = 0
    for kind in _FLOW_KINDS:
        for i in range(per_kind):
            payer = AgentId(f"payer-{idx}")
            payee = AgentId(f"payee-{idx}")
            parties.extend((payer, payee))
            flows.append(
                EscrowFlow(
                    kind=kind,
                    payer=payer,
                    payee=payee,
                    amount=200 + i * 25,
                    flow_id=f"{kind}-{i}",
                )
            )
            idx += 1
    return flows, parties


def tvist_escrow_factory(
    config: ScenarioConfig,
    plugins: dict[str, Any],
) -> dict[AgentId, StateMachineAgent]:
    """Create the orchestrator, the party swarm, and a seeded shared ledger.

    Payers are funded so their settlements and escrow funding clear. Runs
    unchanged under ``payments: tvist`` (all gates enforced → validators PASS) and
    ``payments: prepaid_credits`` (irrevocability, escrow-condition, and mandate
    gates all bypassed → those validators FAIL).

    Example::

        agents = tvist_escrow_factory(config, plugins)
    """
    flows, parties = _build_flows(config)

    balances: dict[AgentId, int] = {}
    for flow in flows:
        balances[flow.payer] = balances.get(flow.payer, 0) + flow.amount + 1000
        balances.setdefault(flow.payee, 0)

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
    agents[orchestrator_id] = TvistEscrowOrchestrator(orchestrator_id, flows)
    for party in parties:
        agents[party] = _AgentParty(party)
    return agents
