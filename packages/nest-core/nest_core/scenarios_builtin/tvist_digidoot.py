# SPDX-License-Identifier: Apache-2.0
"""DigiDoot use case — a personal AI agent for an Indian citizen, settled via Tvist.

`DigiDoot <https://digidoot.in/#architecture>`_ gives every Indian citizen a
personal AI agent that acts on their behalf over India's Digital Public
Infrastructure (Aadhaar, UPI, DigiLocker) **with explicit consent**. This scenario
shows Tvist as the settlement + dispute endpoint behind DigiDoot's "Service
Providers" layer, exercising the *full* Tvist stack under the Indian regime:

* **Trust Foundation (Identity & Consent) → the intent vault.** Every agent
  payment is bound to a stored consent mandate (a spend budget). A payment within
  the citizen's consent settles; one beyond it is blocked before funds move.
* **Governing region → ``in_upi``.** The citizen and the agent negotiate the
  Indian UPI regime (NPCI dispute flows, 7-tick recovery window) ahead of every
  transaction — the Tvist region base feature.
* **Escrow for service delivery.** A travel booking is escrowed and released only
  on a delivery proof (the ticket); an undelivered service is never released.
* **Recall protects the citizen.** A rogue charge that breaches the consent
  mandate is recalled under the UPI regime — the citizen is made whole.
* **Disputes.** A service failure is filed under a UPI-valid reason code.

One **orchestrator** plays DigiDoot's Service-Provider/MCP layer, owns the
configured ``payments:`` plugin (the Tvist endpoint), and drives each citizen
flow, broadcasting the shared ``tvist:`` trace-line protocol. Under
``payments: tvist`` every citizen is protected (validators PASS); under a generic
ledger there is no consent, no regime, and no escrow (validators FAIL).

Trace-line protocol (``:``-delimited, carried in broadcast bodies):

* ``tvist:region:<flow>:<agreed|none>:<client_opts>:<agent_opts>``
* ``tvist:settle:<flow>:<rail>:<citizen>:<provider>:<amount>:<irrevocable 0|1>``
* ``tvist:mandate:<flow>:<agent>:<within_consent 0|1>:<settled 0|1>``
* ``tvist:escrow:<flow>:<citizen>:<provider>:<amount>:<condition_type>``
* ``tvist:release:<flow>:<delivered 0|1>:<released 0|1>``
* ``tvist:recall:<flow>:<region>:<recall_allowed 0|1>:<intent_valid 0|1>:<reversed 0|1>``
* ``tvist:reason:<flow>:<region>:<reason_code>:<in_taxonomy 0|1>:<accepted 0|1>``
* ``tvist:conservation:<total_system_funds>``

Example::

    agents = tvist_digidoot_factory(config, plugins)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from nest_plugins_reference.payments.tvist import REGIONS

from nest_core.scenario import ScenarioConfig
from nest_core.sim.agent import AgentContext, StateMachineAgent
from nest_core.types import AgentId, Money, PaymentRef

# The DigiDoot jurisdiction: India's UPI regime governs every citizen flow.
INDIA = "in_upi"


@dataclass
class CitizenFlow:
    """One citizen-services flow a DigiDoot agent performs under Tvist.

    ``kind`` is one of ``consent_pay`` / ``consent_block`` (intent-vault consent),
    ``escrow_deliver`` / ``escrow_hold`` (service escrow), ``fraud_recall``
    (citizen protection), or ``service_dispute``. ``within`` says whether the
    payment is inside the citizen's explicit consent budget.

    Example::

        flow = CitizenFlow("welfare", "consent_pay", 300, within=True)
    """

    flow_id: str
    kind: str
    amount: int
    within: bool = True
    reason_code: str = "goods_not_received"
    citizen: AgentId = AgentId("citizen")
    provider: AgentId = AgentId("provider")


class DigiDootOrchestrator(StateMachineAgent):
    """DigiDoot's Service-Provider layer calling the Tvist settlement endpoint.

    Negotiation + settlement + escrow funding happen on ``on_start``; releases,
    recalls, and disputes run on a ``resolve:`` pulse one tick later, so the trace
    order is deterministic.

    Example::

        orch = DigiDootOrchestrator(AgentId("digidoot"), flows)
    """

    def __init__(self, agent_id: AgentId, flows: list[CitizenFlow]) -> None:
        self._id = agent_id
        self._flows = flows
        self._payments: Any = None
        self._is_tvist = False

    async def on_start(self, ctx: AgentContext) -> None:
        """Negotiate the India regime per flow, then settle / fund each one.

        Example::

            await orch.on_start(ctx)
        """
        payments_cls = ctx.plugins.get("payments")
        self._payments = payments_cls() if isinstance(payments_cls, type) else payments_cls
        self._is_tvist = hasattr(self._payments, "recommend_region")
        for flow in self._flows:
            agreed = self._payments.recommend_region([INDIA], [INDIA]) if self._is_tvist else None
            await ctx.broadcast(
                f"tvist:region:{flow.flow_id}:{agreed or 'none'}:{INDIA}:{INDIA}".encode()
            )
            if flow.kind in ("consent_pay", "consent_block"):
                await self._consent_settle(ctx, flow)
            elif flow.kind in ("escrow_deliver", "escrow_hold"):
                await self._open_service_escrow(ctx, flow)
            elif flow.kind in ("fraud_recall", "service_dispute"):
                await self._settle_service(ctx, flow)
        await ctx.schedule(1.0, b"resolve:")

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        """On the resolve pulse, run releases / recalls / disputes + conservation.

        Example::

            await orch.on_message(ctx, orch_id, b"resolve:")
        """
        if not payload.startswith(b"resolve:"):
            return
        for flow in self._flows:
            if flow.kind == "escrow_deliver":
                await self._release_service(ctx, flow, delivered=True)
            elif flow.kind == "escrow_hold":
                await self._release_service(ctx, flow, delivered=False)
            elif flow.kind == "fraud_recall":
                await self._recall(ctx, flow)
            elif flow.kind == "service_dispute":
                await self._dispute(ctx, flow)
        await ctx.broadcast(f"tvist:conservation:{self._total_funds()}".encode())

    # -- consent (intent vault) -------------------------------------------

    async def _consent_settle(self, ctx: AgentContext, flow: CitizenFlow) -> None:
        """Pay a provider only within the citizen's explicit consent budget."""
        ref = PaymentRef(flow.flow_id)
        settled = 0
        if self._is_tvist:
            from nest_plugins_reference.payments.tvist import IntentRecord

            budget = flow.amount if flow.within else flow.amount - 100
            self._payments.store_intent(
                IntentRecord(f"consent-{flow.flow_id}", flow.citizen, budget)
            )
            handle = self._payer_handle(flow.citizen)
            try:
                await handle.settle_a2a(
                    flow.provider,
                    Money(amount=flow.amount),
                    ref,
                    rail=REGIONS[INDIA].rail,
                    region=INDIA,
                    intent_ref=f"consent-{flow.flow_id}",
                )
                settled = 1
            except ValueError:
                settled = 0
        else:
            handle = self._payer_handle(flow.citizen)
            try:
                await handle.pay(flow.provider, Money(amount=flow.amount), ref)
                settled = 1
            except ValueError:
                settled = 0
        if settled:
            await ctx.broadcast(
                f"tvist:settle:{flow.flow_id}:{REGIONS[INDIA].rail}:"
                f"{flow.citizen}:{flow.provider}:{flow.amount}:1".encode()
            )
        await ctx.broadcast(
            f"tvist:mandate:{flow.flow_id}:{flow.citizen}:{int(flow.within)}:{settled}".encode()
        )

    # -- service escrow ----------------------------------------------------

    async def _open_service_escrow(self, ctx: AgentContext, flow: CitizenFlow) -> None:
        """Escrow a service fee (Tvist), or naively pre-pay the provider (generic)."""
        if self._is_tvist:
            from nest_plugins_reference.payments.tvist import ReleaseCondition

            cond = ReleaseCondition(type="delivery_proof", expected="delivered")
            self._payments.open_escrow(
                flow.flow_id,
                flow.citizen,
                flow.provider,
                flow.amount,
                cond,
                rail=REGIONS[INDIA].rail,
                region=INDIA,
            )
            self._payments.fund_escrow(flow.flow_id)
        else:
            handle = self._payer_handle(flow.citizen)
            await handle.pay(flow.provider, Money(amount=flow.amount), PaymentRef(flow.flow_id))
        await ctx.broadcast(
            f"tvist:escrow:{flow.flow_id}:{flow.citizen}:{flow.provider}:"
            f"{flow.amount}:delivery_proof".encode()
        )

    async def _release_service(
        self, ctx: AgentContext, flow: CitizenFlow, *, delivered: bool
    ) -> None:
        """Release the escrow only when the service was delivered."""
        delivered_flag = 0
        released = 0
        if self._is_tvist:
            if delivered:
                self._payments.satisfy_condition(flow.flow_id, "delivered")
                delivered_flag = 1
            try:
                self._payments.release_escrow(flow.flow_id)
                released = 1
            except ValueError:
                released = 0
        else:
            delivered_flag = 1 if delivered else 0
            released = 1  # generic ledger already paid the provider up front
        await ctx.broadcast(f"tvist:release:{flow.flow_id}:{delivered_flag}:{released}".encode())

    # -- citizen-protection recall + dispute ------------------------------

    async def _settle_service(self, ctx: AgentContext, flow: CitizenFlow) -> None:
        """Settle a service payment (irrevocable UPI for recall, reversible for dispute)."""
        ref = PaymentRef(flow.flow_id)
        handle = self._payer_handle(flow.citizen)
        if flow.kind == "fraud_recall" and self._is_tvist:
            await handle.settle_a2a(
                flow.provider,
                Money(amount=flow.amount),
                ref,
                rail=REGIONS[INDIA].rail,
                region=INDIA,
            )
            await ctx.broadcast(
                f"tvist:settle:{flow.flow_id}:{REGIONS[INDIA].rail}:"
                f"{flow.citizen}:{flow.provider}:{flow.amount}:1".encode()
            )
        else:
            await handle.pay(flow.provider, Money(amount=flow.amount), ref)
            irrevocable = 1 if flow.kind == "fraud_recall" else 0
            await ctx.broadcast(
                f"tvist:settle:{flow.flow_id}:{REGIONS[INDIA].rail}:"
                f"{flow.citizen}:{flow.provider}:{flow.amount}:{irrevocable}".encode()
            )

    async def _recall(self, ctx: AgentContext, flow: CitizenFlow) -> None:
        """Recall a rogue charge that breached the citizen's mandate (UPI permits it)."""
        ref = PaymentRef(flow.flow_id)
        recall_allowed = int(REGIONS[INDIA].recall_allowed)
        reversed_ = 0
        if self._is_tvist:
            from nest_plugins_reference.payments.tvist import IntentRecord

            self._payments.store_intent(
                IntentRecord(f"breach-{flow.flow_id}", flow.citizen, flow.amount - 1)
            )
            reversed_ = int(self._payments.recall_a2a(ref, f"breach-{flow.flow_id}", ctx.time))
        else:
            try:
                await self._payments.refund(ref)
                reversed_ = 1
            except ValueError:
                reversed_ = 0
        await ctx.broadcast(
            f"tvist:recall:{flow.flow_id}:{INDIA}:{recall_allowed}:1:{reversed_}".encode()
        )

    async def _dispute(self, ctx: AgentContext, flow: CitizenFlow) -> None:
        """File a service dispute under a UPI-valid reason code."""
        ref = PaymentRef(flow.flow_id)
        in_taxonomy = int(flow.reason_code in REGIONS[INDIA].reason_codes)
        accepted = 0
        if self._is_tvist:
            try:
                self._payments.open_dispute(ref, flow.reason_code, flow.citizen, INDIA)
                accepted = 1
            except ValueError:
                accepted = 0
        else:
            accepted = 1
        await ctx.broadcast(
            f"tvist:reason:{flow.flow_id}:{INDIA}:{flow.reason_code}:{in_taxonomy}:{accepted}".encode()
        )

    # -- helpers -----------------------------------------------------------

    def _payer_handle(self, payer: AgentId) -> Any:
        """A plugin handle whose settlement debits *payer*, over the shared stores."""
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


class _CitizenAgent(StateMachineAgent):
    """An inert roster member representing a citizen and their personal agent.

    Example::

        c = _CitizenAgent(AgentId("citizen-0"))
    """

    def __init__(self, agent_id: AgentId) -> None:
        self._id = agent_id

    async def on_start(self, ctx: AgentContext) -> None:
        """No-op; flows are driven centrally by the DigiDoot orchestrator."""
        return


def _build_flows() -> tuple[list[CitizenFlow], list[AgentId]]:
    """Build the DigiDoot citizen-services flows and the citizen/provider roster.

    Mirrors DigiDoot's demonstrated journeys (welfare, travel booking, health
    records) plus a fraud-recall, exercising consent, escrow, recall, and dispute.

    Example::

        flows, roster = _build_flows()
    """
    specs = [
        CitizenFlow("welfare-consent", "consent_pay", 300, within=True),
        CitizenFlow("welfare-overreach", "consent_block", 500, within=False),
        CitizenFlow("travel-booking", "escrow_deliver", 400),
        CitizenFlow("travel-undelivered", "escrow_hold", 350),
        CitizenFlow("rogue-charge", "fraud_recall", 280),
        CitizenFlow("health-records", "service_dispute", 150, reason_code="goods_not_received"),
    ]
    flows: list[CitizenFlow] = []
    roster: list[AgentId] = []
    for i, spec in enumerate(specs):
        citizen = AgentId(f"citizen-{i}")
        provider = AgentId(f"provider-{i}")
        roster.extend((citizen, provider))
        flows.append(
            CitizenFlow(
                spec.flow_id,
                spec.kind,
                spec.amount,
                spec.within,
                spec.reason_code,
                citizen,
                provider,
            )
        )
    return flows, roster


def tvist_digidoot_factory(
    config: ScenarioConfig,
    plugins: dict[str, Any],
) -> dict[AgentId, StateMachineAgent]:
    """Create the DigiDoot orchestrator, the citizen/provider swarm, and a ledger.

    Runs unchanged under ``payments: tvist`` (every citizen flow is consent-bound,
    India-governed, and escrow-protected → validators PASS) and
    ``payments: prepaid_credits`` (no consent, no regime, no escrow → validators
    FAIL).

    Example::

        agents = tvist_digidoot_factory(config, plugins)
    """
    flows, roster = _build_flows()

    balances: dict[AgentId, int] = {}
    for flow in flows:
        balances[flow.citizen] = balances.get(flow.citizen, 0) + flow.amount + 1000
        balances.setdefault(flow.provider, 0)

    payments_cls = plugins.get("payments")
    if isinstance(payments_cls, type):
        try:
            plugins["payments"] = payments_cls(
                AgentId("tvist"), initial_balance=0, balances=balances, payments={}
            )
        except TypeError:
            plugins["payments"] = payments_cls(AgentId("tvist"), initial_balance=0)

    agents: dict[AgentId, StateMachineAgent] = {}
    orchestrator_id = AgentId("digidoot")
    agents[orchestrator_id] = DigiDootOrchestrator(orchestrator_id, flows)
    for member in roster:
        agents[member] = _CitizenAgent(member)
    return agents
