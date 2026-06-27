# SPDX-License-Identifier: Apache-2.0
"""Tvist region scenario — the governing dispute regime is negotiated up front.

Before any funds move, a client and an agent each bring an ordered list of
regions whose dispute rules they will adhere to (Pix, SEPA Instant, FedNow, UPI,
UK FPS, Nordic — not just the Nordics). They negotiate one mutually-acceptable
region (:meth:`~nest_plugins_reference.payments.tvist.TvistPayments.negotiate_region`)
and the transaction is **bound to that regime**: its recalls and disputes must
then adhere to it.

One **orchestrator** owns the configured ``payments:`` plugin and drives several
flows, broadcasting a ``tvist:`` trace-line protocol the validators read. The
discrimination is, as elsewhere, in what the plugin *lets happen*:

* **agreed-pix** — client and agent overlap on Pix; a justified intent-mismatch
  recall inside Pix's window is honoured.
* **fednow-norecall** — both pick FedNow, whose regime *disallows* recall (no
  federal standard yet). Even a justified mismatch recall must be refused — escrow
  is the only protection there. A generic ``refund`` reverses it anyway.
* **no-overlap** — the option lists do not intersect, so there is *no agreement*
  and the transaction must not proceed. A region-blind ledger settles regardless.
* **wrong-reason** — under a Nordic agreement, a ``pix_med_return`` dispute is
  outside the region's taxonomy and is rejected. A region-blind ledger accepts it.
* **right-reason** — a ``goods_not_received`` dispute *is* in the Nordic taxonomy
  and is accepted (the control: valid disputes still flow).

Region facts (which region allows recall, which reason codes it accepts) are read
from the module-level region registry and emitted into the trace, so the
validator judges the plugin's *decision* against the regime both sides agreed to.

Trace-line protocol (``:``-delimited, carried in broadcast bodies):

* ``tvist:region:<flow>:<agreed|none>:<client_opts>:<agent_opts>`` (opts ``|``-joined)
* ``tvist:settle:<flow>:<rail>:<payer>:<payee>:<amount>:<irrevocable 0|1>``
* ``tvist:recall:<flow>:<region>:<recall_allowed 0|1>:<intent_valid 0|1>:<reversed 0|1>``
* ``tvist:reason:<flow>:<region>:<reason_code>:<in_taxonomy 0|1>:<accepted 0|1>``
* ``tvist:conservation:<total_system_funds>``

Example::

    agents = tvist_region_factory(config, plugins)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from nest_plugins_reference.payments.tvist import REGIONS

from nest_core.scenario import ScenarioConfig
from nest_core.sim.agent import AgentContext, StateMachineAgent
from nest_core.types import AgentId, Money, PaymentRef


@dataclass
class RegionFlow:
    """One negotiated-region flow: a recall or a dispute under an agreed regime.

    ``region`` is the regime the parties are expected to agree on; ``client_opts``
    and ``agent_opts`` are the ordered preference lists fed to the negotiation (a
    ``no-overlap`` flow has disjoint lists so no region is agreed).

    Example::

        flow = RegionFlow("agreed-pix", "recall", "br_pix",
                          ["br_pix", "eu_sepa"], ["eu_sepa", "br_pix"])
    """

    flow_id: str
    kind: str
    region: str
    client_opts: list[str]
    agent_opts: list[str]
    amount: int = 200
    reason_code: str = "agent_exceeded_mandate"
    payer: AgentId = field(default_factory=lambda: AgentId("payer"))
    payee: AgentId = field(default_factory=lambda: AgentId("payee"))


class TvistRegionOrchestrator(StateMachineAgent):
    """Owns the payments plugin and runs every negotiated-region flow.

    Negotiation + settlement happen on ``on_start``; recalls and disputes run on a
    ``resolve:`` pulse one tick later, so trace order is deterministic.

    Example::

        orch = TvistRegionOrchestrator(AgentId("orchestrator"), flows)
    """

    def __init__(self, agent_id: AgentId, flows: list[RegionFlow]) -> None:
        self._id = agent_id
        self._flows = flows
        self._payments: Any = None
        self._is_tvist = False
        self._agreed: dict[str, str | None] = {}

    async def on_start(self, ctx: AgentContext) -> None:
        """Negotiate a region per flow and settle the ones that reach agreement.

        Example::

            await orch.on_start(ctx)
        """
        payments_cls = ctx.plugins.get("payments")
        self._payments = payments_cls() if isinstance(payments_cls, type) else payments_cls
        self._is_tvist = hasattr(self._payments, "negotiate_region")
        for flow in self._flows:
            agreed = (
                self._payments.negotiate_region(flow.client_opts, flow.agent_opts)
                if self._is_tvist
                else None
            )
            self._agreed[flow.flow_id] = agreed
            await ctx.broadcast(
                f"tvist:region:{flow.flow_id}:{agreed or 'none'}:"
                f"{'|'.join(flow.client_opts)}:{'|'.join(flow.agent_opts)}".encode()
            )
            # A region-aware plugin will not transact a no-agreement flow; a
            # region-blind one settles anyway (the violation the validator catches).
            if agreed is None and self._is_tvist:
                continue
            await self._settle(flow)
            irrevocable = int(REGIONS[flow.region].irrevocable) if flow.kind == "recall" else 0
            await ctx.broadcast(
                f"tvist:settle:{flow.flow_id}:{REGIONS[flow.region].rail}:"
                f"{flow.payer}:{flow.payee}:{flow.amount}:{irrevocable}".encode()
            )
        await ctx.schedule(1.0, b"resolve:")

    async def on_message(self, ctx: AgentContext, sender: AgentId, payload: bytes) -> None:
        """On the resolve pulse, run each flow's recall / dispute + conservation.

        Example::

            await orch.on_message(ctx, orch_id, b"resolve:")
        """
        if not payload.startswith(b"resolve:"):
            return
        for flow in self._flows:
            if self._agreed[flow.flow_id] is None and self._is_tvist:
                continue
            if flow.kind == "recall":
                await self._recall(ctx, flow)
            elif flow.kind == "dispute":
                await self._dispute(ctx, flow)
        await ctx.broadcast(f"tvist:conservation:{self._total_funds()}".encode())

    # -- flow steps --------------------------------------------------------

    async def _settle(self, flow: RegionFlow) -> None:
        """Settle the flow's payment (irrevocable A2A for recalls, reversible for disputes)."""
        ref = PaymentRef(flow.flow_id)
        handle = self._payer_handle(flow.payer)
        if flow.kind == "recall" and self._is_tvist:
            await handle.settle_a2a(
                flow.payee,
                Money(amount=flow.amount),
                ref,
                rail=REGIONS[flow.region].rail,
                region=flow.region,
            )
        else:
            await handle.pay(flow.payee, Money(amount=flow.amount), ref)

    async def _recall(self, ctx: AgentContext, flow: RegionFlow) -> None:
        """Attempt a justified (mandate-breach) recall; the regime decides if it lands."""
        ref = PaymentRef(flow.flow_id)
        recall_allowed = int(REGIONS[flow.region].recall_allowed)
        reversed_ = 0
        if self._is_tvist:
            from nest_plugins_reference.payments.tvist import IntentRecord

            self._payments.store_intent(
                IntentRecord(f"intent-{flow.flow_id}", flow.payer, budget=flow.amount - 1)
            )
            reversed_ = int(self._payments.recall_a2a(ref, f"intent-{flow.flow_id}", ctx.time))
        else:
            try:
                await self._payments.refund(ref)
                reversed_ = 1
            except ValueError:
                reversed_ = 0
        await ctx.broadcast(
            f"tvist:recall:{flow.flow_id}:{flow.region}:{recall_allowed}:1:{reversed_}".encode()
        )

    async def _dispute(self, ctx: AgentContext, flow: RegionFlow) -> None:
        """File a dispute; the regime decides whether its reason code is accepted."""
        ref = PaymentRef(flow.flow_id)
        in_taxonomy = int(flow.reason_code in REGIONS[flow.region].reason_codes)
        accepted = 0
        if self._is_tvist:
            try:
                self._payments.open_dispute(ref, flow.reason_code, flow.payer, flow.region)
                accepted = 1
            except ValueError:
                accepted = 0
        else:
            # Region-blind ledger: it has no taxonomy, so it accepts any reason.
            accepted = 1
        await ctx.broadcast(
            f"tvist:reason:{flow.flow_id}:{flow.region}:{flow.reason_code}:"
            f"{in_taxonomy}:{accepted}".encode()
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
        """Total conserved funds reported by the plugin (balances + holds)."""
        if hasattr(self._payments, "total_funds"):
            total: int = self._payments.total_funds()
            return total
        balances: dict[AgentId, int] = getattr(self._payments, "_balances", {})
        return sum(balances.values())


class _PartyAgent(StateMachineAgent):
    """An inert roster member representing a party in the swarm.

    Example::

        p = _PartyAgent(AgentId("payer-0"))
    """

    def __init__(self, agent_id: AgentId) -> None:
        self._id = agent_id

    async def on_start(self, ctx: AgentContext) -> None:
        """No-op; all flows are driven centrally by the orchestrator."""
        return


def _build_flows() -> tuple[list[RegionFlow], list[AgentId]]:
    """Build the fixed set of negotiated-region flows and the party roster.

    Example::

        flows, parties = _build_flows()
    """
    specs = [
        RegionFlow("agreed-pix", "recall", "br_pix", ["br_pix", "eu_sepa"], ["eu_sepa", "br_pix"]),
        RegionFlow("fednow-norecall", "recall", "us_fednow", ["us_fednow"], ["us_fednow"], 220),
        RegionFlow("no-overlap", "recall", "br_pix", ["br_pix"], ["us_fednow"], 240),
        RegionFlow(
            "wrong-reason",
            "dispute",
            "nordic",
            ["nordic"],
            ["nordic"],
            150,
            reason_code="pix_med_return",
        ),
        RegionFlow(
            "right-reason",
            "dispute",
            "nordic",
            ["nordic"],
            ["nordic"],
            160,
            reason_code="goods_not_received",
        ),
    ]
    flows: list[RegionFlow] = []
    parties: list[AgentId] = []
    for i, spec in enumerate(specs):
        payer = AgentId(f"payer-{i}")
        payee = AgentId(f"payee-{i}")
        parties.extend((payer, payee))
        flows.append(
            RegionFlow(
                spec.flow_id,
                spec.kind,
                spec.region,
                spec.client_opts,
                spec.agent_opts,
                spec.amount,
                spec.reason_code,
                payer,
                payee,
            )
        )
    return flows, parties


def tvist_region_factory(
    config: ScenarioConfig,
    plugins: dict[str, Any],
) -> dict[AgentId, StateMachineAgent]:
    """Create the orchestrator, the party swarm, and a seeded shared ledger.

    Runs unchanged under ``payments: tvist`` (a region is negotiated up front and
    every recall / dispute adheres to it → validators PASS) and
    ``payments: prepaid_credits`` (no negotiation, no regime → transactions settle
    ungoverned, FedNow recalls reverse, off-taxonomy reasons are accepted →
    validators FAIL).

    Example::

        agents = tvist_region_factory(config, plugins)
    """
    flows, parties = _build_flows()

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
    agents[orchestrator_id] = TvistRegionOrchestrator(orchestrator_id, flows)
    for party in parties:
        agents[party] = _PartyAgent(party)
    return agents
