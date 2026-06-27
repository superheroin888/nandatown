# SPDX-License-Identifier: Apache-2.0
"""Tvist: dispute + escrow + intent-vault payments for cards, BNPL, and A2A rails.

This payments plugin extends the one-shot ``prepaid_credits`` ledger with the
two halves of the Tvist product. The headline is the agentic-commerce extension
(escrow + A2A); evidence-gated dispute deflection is the foundation it shares a
core with.

**Escrow + irrevocable A2A (the agentic-commerce extension).** Push payments
(Pix, SEPA Instant, FedNow, stablecoin) are settlement-final: once
:meth:`settle_a2a` lands, the funds cannot be unilaterally clawed back. The only
sanctioned reversal is a :meth:`recall_a2a` that cites a **Verifiable-Intent
mismatch** — proof from the :class:`IntentRecord` vault that the initiating agent
exceeded its mandate. :meth:`open_escrow` / :meth:`release_escrow` hold funds
until a typed :class:`ReleaseCondition` (delivery / attestation / time) is
satisfied; an unsatisfied release is refused.

**Dispute deflection (the shared foundation).** A reversible card / BNPL payment
can be *disputed*. The naive issuer behaviour a generic ``Payments`` plugin can
offer is "any dispute → ``refund``", which hands a full reversal to every
*friendly-fraud* claimant (the cardholder who actually received the goods). Tvist
instead gates the reversal on **content-addressed evidence**: representment
assembles cited evidence hashes into a deterministic win-probability, and a
refund is only conceded when that probability falls below the auto-fight
threshold. A dispute the merchant can rebut with a verified ``delivery_signed``
proof is *represented and won* — the friendly-fraud reversal never executes.

Every operation conserves funds: the sum of all balances plus all escrow-held
amounts is invariant across the lifetime of the ledger. The plugin is
**deterministic** — win-probabilities are a fixed function of the cited
evidence, evidence identity is ``sha256`` content-addressing. No wall-clock, no
RNG.

It satisfies the stock :class:`~nest_core.layers.payments.Payments` protocol, so
``payments: tvist`` is a drop-in for any scenario; the dispute / escrow / intent
surface is additive. Registered under ``("payments", "tvist")`` in
``nest_core.plugins``.

Example::

    pay = TvistPayments(AgentId("system"), balances={AgentId("buyer"): 1000})
    receipt = await pay.pay(AgentId("merchant"), Money(amount=200), PaymentRef("p1"))
    ev = pay.register_evidence({"kind": "delivery_signed", "carrier": "postnord"})
    case = pay.open_dispute(PaymentRef("p1"), "goods_not_received", AgentId("buyer"))
    pay.assemble_evidence(case.case_id, [ev])
    outcome, merchant_won = pay.resolve_dispute(case.case_id)
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Literal

from nest_core.types import (
    AgentId,
    Money,
    PaymentRef,
    PaymentStatus,
    Quote,
    Receipt,
    ServiceRef,
)

# Auto-fight threshold from the Tvist product spec (§5.2): a case scoring at or
# above this is represented (fought); below it the issuer concedes a refund.
DEFAULT_FIGHT_THRESHOLD = 0.65

# Deterministic win-probability contribution per verified evidence category.
# Strong delivery proof dominates; agentic intent corroboration and device
# signals are supporting. The weights are published as part of the method so a
# score is fully reproducible from the cited evidence alone.
EVIDENCE_WEIGHTS: dict[str, float] = {
    "delivery_signed": 0.55,
    "delivery": 0.40,
    "intent_match": 0.30,
    "device_match": 0.15,
    "customer_history": 0.10,
    "ip_match": 0.10,
}

# Reason codes Tvist's canonical taxonomy maps onto. The first group mirrors
# Klarna RFI / Mastercom message reason codes (v1 card / BNPL); the second is the
# agentic + A2A additions the product spec §3.3 introduces for irrevocable rails.
REASON_CODES: frozenset[str] = frozenset(
    {
        "goods_not_received",
        "not_as_described",
        "fraud",
        "recurring_disputed",
        "agent_exceeded_mandate",
        "verifiable_intent_mismatch",
        "sepa_recall",
        "pix_med_return",
    }
)

ConditionType = Literal["delivery_proof", "time_elapsed", "attestation"]
EscrowStatus = Literal["PENDING_FUNDING", "FUNDED", "RELEASED", "CONTESTED", "REFUNDED"]


def content_hash(artifact: dict[str, Any]) -> str:
    """Return the ``sha256`` content address of an evidence artifact.

    Canonical (sorted-key, compact) JSON makes the hash byte-identical for equal
    artifacts across runs, so a cited hash both *names* and *pins* the exact
    bytes — a tampered artifact no longer matches its citation.

    Example::

        h = content_hash({"kind": "delivery_signed", "tracking_no": "X1"})
    """
    payload = json.dumps(artifact, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


@dataclass
class ReleaseCondition:
    """A typed, first-class condition gating an escrow release.

    Three primitive types from the Tvist 2.0 spec (§4.1): ``delivery_proof`` (a
    carrier state must be reached), ``time_elapsed`` (auto-release at a tick), and
    ``attestation`` (a named party signals satisfaction). ``satisfied`` is flipped
    only by :meth:`TvistPayments.satisfy_condition` against matching proof.

    Example::

        cond = ReleaseCondition(type="delivery_proof", expected="delivered_signed")
    """

    type: ConditionType
    expected: str
    satisfied: bool = False


@dataclass
class TvistEscrow:
    """A programmable hold-and-release record over an A2A rail.

    Funds move payer→held on :meth:`fund_escrow`, held→payee on
    :meth:`release_escrow` (only once ``condition.satisfied``), or held→payer on a
    sustained contest. ``status`` walks ``PENDING_FUNDING → FUNDED →
    RELEASED|CONTESTED|REFUNDED``.

    Example::

        esc = TvistEscrow("e1", AgentId("payer"), AgentId("payee"), 500, cond, "pix")
    """

    escrow_id: str
    payer: AgentId
    payee: AgentId
    amount: int
    condition: ReleaseCondition
    rail: str
    status: EscrowStatus = "PENDING_FUNDING"
    intent_ref: str | None = None


@dataclass
class TvistCase:
    """A dispute case over a settled (reversible) payment.

    Holds the cited evidence hashes and the resulting deterministic
    ``win_probability``. ``outcome`` is one of ``open``, ``represented``,
    ``refunded``, or ``rejected``; ``merchant_won`` records whether the reversal
    was successfully deflected.

    Example::

        case = TvistCase("c1", PaymentRef("p1"), "fraud", AgentId("buyer"))
    """

    case_id: str
    payment_ref: PaymentRef
    reason_code: str
    disputant: AgentId
    evidence_hashes: list[str] = field(default_factory=lambda: list[str]())
    win_probability: float = 0.0
    outcome: Literal["open", "represented", "refunded", "rejected"] = "open"
    merchant_won: bool = False


@dataclass
class IntentRecord:
    """A canonical cross-protocol Verifiable-Intent record (Tvist Intent Vault).

    Captures the mandate an agent was authorised under: a spend ``budget``, an
    optional ``merchant_allowlist``, and the originating ``protocol``. Disputes of
    agent-initiated transactions are adjudicated against this record — a payment
    outside the mandate is an ``agent_exceeded_mandate`` / ``verifiable_intent_
    mismatch``.

    Example::

        rec = IntentRecord("i1", AgentId("agent-7"), budget=300, protocol="mc_vi")
    """

    intent_id: str
    agent_id: AgentId
    budget: int
    protocol: str = "mc_vi"
    merchant_allowlist: tuple[AgentId, ...] | None = None


class TvistPayments:
    """Dispute + escrow + intent-vault payments implementing the ``Payments`` protocol.

    Constructed like ``PrepaidCredits`` (``agent_id``, ``initial_balance``, shared
    ``balances`` / ``payments`` dicts) so it is a drop-in ``payments:`` plugin. The
    dispute, escrow, evidence, and intent-vault stores are additionally shareable
    so a central orchestrator can own one ledger across a whole scenario.

    Example::

        pay = TvistPayments(AgentId("system"), balances={AgentId("b"): 1000})
        await pay.pay(AgentId("m"), Money(amount=200), PaymentRef("p1"))
    """

    def __init__(
        self,
        agent_id: AgentId,
        initial_balance: int = 1000,
        balances: dict[AgentId, int] | None = None,
        payments: dict[PaymentRef, Receipt] | None = None,
        escrows: dict[str, TvistEscrow] | None = None,
        cases: dict[str, TvistCase] | None = None,
        evidence: dict[str, dict[str, Any]] | None = None,
        intents: dict[str, IntentRecord] | None = None,
        settled_meta: dict[PaymentRef, dict[str, Any]] | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._balances = balances if balances is not None else {}
        self._balances.setdefault(agent_id, initial_balance)
        self._payments = payments if payments is not None else {}
        self._escrows = escrows if escrows is not None else {}
        self._cases = cases if cases is not None else {}
        self._evidence = evidence if evidence is not None else {}
        self._intents = intents if intents is not None else {}
        self._settled_meta = settled_meta if settled_meta is not None else {}

    # -- balances ----------------------------------------------------------

    def balance(self, agent: AgentId) -> int:
        """Return an agent's spendable balance (escrow-held funds excluded).

        Example::

            bal = pay.balance(AgentId("buyer"))
        """
        return self._balances.get(agent, 0)

    def total_funds(self) -> int:
        """Return total conserved funds: all balances + all escrow-held amounts.

        This is the conservation invariant the adversarial validator checks — it
        must never change once the ledger is seeded.

        Example::

            assert pay.total_funds() == initial_total
        """
        held = sum(e.amount for e in self._escrows.values() if e.status in ("FUNDED", "CONTESTED"))
        return sum(self._balances.values()) + held

    def _credit(self, agent: AgentId, amount: int) -> None:
        self._balances[agent] = self._balances.get(agent, 0) + amount

    def _debit(self, agent: AgentId, amount: int) -> None:
        bal = self._balances.get(agent, 0)
        if bal < amount:
            msg = f"Insufficient balance: {agent} has {bal} < {amount}"
            raise ValueError(msg)
        self._balances[agent] = bal - amount

    # -- stock Payments protocol ------------------------------------------

    async def quote(self, service: ServiceRef) -> Quote:
        """Return a fixed quote for any service (protocol parity).

        Example::

            q = await pay.quote(ServiceRef("svc"))
        """
        return Quote(service=service, price=Money(amount=10))

    async def pay(self, to: AgentId, amount: Money, ref: PaymentRef) -> Receipt:
        """Execute a one-shot (reversible) payment from this agent to another.

        Example::

            receipt = await pay.pay(AgentId("m"), Money(amount=50), PaymentRef("p1"))
        """
        if amount.amount <= 0:
            msg = f"Payment amount must be positive: {amount.amount}"
            raise ValueError(msg)
        if ref in self._payments:
            msg = f"Duplicate payment reference: {ref}"
            raise ValueError(msg)
        self._debit(self._agent_id, amount.amount)
        self._credit(to, amount.amount)
        receipt = Receipt(ref=ref, payer=self._agent_id, payee=to, amount=amount)
        self._payments[ref] = receipt
        self._settled_meta[ref] = {"rail": "card", "irrevocable": False}
        return receipt

    async def verify_payment(self, ref: PaymentRef) -> PaymentStatus:
        """Return the status of a payment by reference.

        ``REFUNDED`` once reversed, ``CONFIRMED`` while settled, ``FAILED`` if
        unknown.

        Example::

            status = await pay.verify_payment(PaymentRef("p1"))
        """
        if ref not in self._payments:
            return PaymentStatus.FAILED
        if self._settled_meta.get(ref, {}).get("reversed"):
            return PaymentStatus.REFUNDED
        return PaymentStatus.CONFIRMED

    async def refund(self, ref: PaymentRef) -> None:
        """Reverse a *reversible* payment (payee→payer).

        Refuses an irrevocable A2A settlement: the only sanctioned reversal for
        those is :meth:`recall_a2a`. v1 disputes route through
        :meth:`resolve_dispute` (evidence-gated) rather than this unguarded path.

        Example::

            await pay.refund(PaymentRef("p1"))
        """
        receipt = self._payments.get(ref)
        if receipt is None:
            msg = f"Payment not found: {ref}"
            raise ValueError(msg)
        if self._settled_meta.get(ref, {}).get("irrevocable"):
            msg = f"Irrevocable A2A payment cannot be refunded directly: {ref}"
            raise ValueError(msg)
        if self._settled_meta.get(ref, {}).get("reversed"):
            return
        self._debit(receipt.payee, receipt.amount.amount)
        self._credit(receipt.payer, receipt.amount.amount)
        self._settled_meta.setdefault(ref, {})["reversed"] = True

    # -- evidence layer (content-addressed) -------------------------------

    def register_evidence(self, artifact: dict[str, Any]) -> str:
        """Store an evidence artifact and return its ``sha256`` content address.

        Example::

            h = pay.register_evidence({"kind": "delivery_signed", "carrier": "dhl"})
        """
        h = content_hash(artifact)
        self._evidence[h] = artifact
        return h

    def verify_evidence(self, evidence_hash: str) -> bool:
        """Return whether a hash names a stored artifact whose bytes still match.

        Recomputes the content address, so a citation to a mutated artifact fails.

        Example::

            ok = pay.verify_evidence(h)
        """
        artifact = self._evidence.get(evidence_hash)
        if artifact is None:
            return False
        return content_hash(artifact) == evidence_hash

    # -- dispute lifecycle (reversible card / BNPL) -----------------------

    def open_dispute(
        self,
        payment_ref: PaymentRef,
        reason_code: str,
        disputant: AgentId,
    ) -> TvistCase:
        """Open a dispute case against a settled payment.

        Example::

            case = pay.open_dispute(PaymentRef("p1"), "fraud", AgentId("buyer"))
        """
        if payment_ref not in self._payments:
            msg = f"Cannot dispute unknown payment: {payment_ref}"
            raise ValueError(msg)
        if reason_code not in REASON_CODES:
            msg = f"Unknown reason code: {reason_code}"
            raise ValueError(msg)
        case_id = f"case-{payment_ref}"
        case = TvistCase(
            case_id=case_id,
            payment_ref=payment_ref,
            reason_code=reason_code,
            disputant=disputant,
        )
        self._cases[case_id] = case
        return case

    def assemble_evidence(self, case_id: str, evidence_hashes: list[str]) -> float:
        """Cite evidence on a case and return its deterministic win-probability.

        Only artifacts that :meth:`verify_evidence` accepts contribute; each adds
        its category weight (:data:`EVIDENCE_WEIGHTS`). The sum is clamped to
        ``[0, 1]``. With no verified evidence the score is ``0.0`` — the issuer has
        nothing to represent with, so the case will concede a refund.

        Example::

            score = pay.assemble_evidence("case-p1", [h_delivery, h_device])
        """
        case = self._cases[case_id]
        score = 0.0
        for h in evidence_hashes:
            if not self.verify_evidence(h):
                continue
            case.evidence_hashes.append(h)
            kind = str(self._evidence[h].get("kind", ""))
            score += EVIDENCE_WEIGHTS.get(kind, 0.0)
        case.win_probability = min(1.0, score)
        return case.win_probability

    def resolve_dispute(
        self,
        case_id: str,
        threshold: float = DEFAULT_FIGHT_THRESHOLD,
    ) -> tuple[str, bool]:
        """Adjudicate a case: represent (fight) above threshold, else refund.

        Returns ``(outcome, merchant_won)``. Above ``threshold`` the merchant has
        sufficient verified evidence → ``("represented", True)`` and **no reversal
        executes**, so a friendly-fraud claim recovers nothing. Below it the issuer
        concedes → ``("refunded", False)`` and the funds are returned to the
        disputant. This is the evidence gate: a refund is impossible without the
        case's evidence failing to clear the bar.

        Example::

            outcome, won = pay.resolve_dispute("case-p1")
        """
        case = self._cases[case_id]
        if case.win_probability >= threshold:
            case.outcome = "represented"
            case.merchant_won = True
            return "represented", True
        receipt = self._payments[case.payment_ref]
        if not self._settled_meta.get(case.payment_ref, {}).get("reversed"):
            self._debit(receipt.payee, receipt.amount.amount)
            self._credit(receipt.payer, receipt.amount.amount)
            self._settled_meta.setdefault(case.payment_ref, {})["reversed"] = True
        case.outcome = "refunded"
        case.merchant_won = False
        return "refunded", False

    # -- intent vault ------------------------------------------------------

    def store_intent(self, record: IntentRecord) -> str:
        """Store a Verifiable-Intent record in the vault and return its id.

        Example::

            iid = pay.store_intent(IntentRecord("i1", AgentId("agent-7"), budget=300))
        """
        self._intents[record.intent_id] = record
        return record.intent_id

    def intent_covers(self, intent_ref: str, amount: int, merchant: AgentId) -> bool:
        """Return whether a stored mandate authorises ``amount`` to ``merchant``.

        Within mandate iff at or under ``budget`` and (when an allowlist is
        present) the merchant is on it. An unknown intent never covers anything.

        Example::

            ok = pay.intent_covers("i1", 200, AgentId("shop"))
        """
        rec = self._intents.get(intent_ref)
        if rec is None:
            return False
        if amount > rec.budget:
            return False
        return not (rec.merchant_allowlist is not None and merchant not in rec.merchant_allowlist)

    # -- irrevocable A2A ---------------------------------------------------

    async def settle_a2a(
        self,
        to: AgentId,
        amount: Money,
        ref: PaymentRef,
        rail: str = "pix",
        intent_ref: str | None = None,
    ) -> Receipt:
        """Settle an irrevocable push payment, enforcing mandate if intent-bound.

        Marks the payment ``irrevocable`` so :meth:`refund` refuses it — the only
        sanctioned reversal is :meth:`recall_a2a` citing an intent mismatch. If
        ``intent_ref`` is supplied and the mandate does **not** cover the payment,
        the settlement is rejected outright (the over-mandate agent is stopped
        before funds move).

        Example::

            r = await pay.settle_a2a(AgentId("payee"), Money(amount=100),
                                     PaymentRef("a1"), rail="sepa_instant")
        """
        if amount.amount <= 0:
            msg = f"Payment amount must be positive: {amount.amount}"
            raise ValueError(msg)
        if ref in self._payments:
            msg = f"Duplicate payment reference: {ref}"
            raise ValueError(msg)
        if intent_ref is not None and not self.intent_covers(intent_ref, amount.amount, to):
            msg = f"Payment exceeds agent mandate {intent_ref!r}: {amount.amount} to {to}"
            raise ValueError(msg)
        self._debit(self._agent_id, amount.amount)
        self._credit(to, amount.amount)
        receipt = Receipt(ref=ref, payer=self._agent_id, payee=to, amount=amount)
        self._payments[ref] = receipt
        self._settled_meta[ref] = {"rail": rail, "irrevocable": True, "intent_ref": intent_ref}
        return receipt

    def recall_a2a(self, ref: PaymentRef, intent_ref: str) -> bool:
        """Reverse an irrevocable A2A payment **only** on a Verifiable-Intent mismatch.

        The recall succeeds iff the cited intent record exists and does *not* cover
        the settled payment (the agent exceeded its mandate). A recall with no
        mismatch — the unilateral clawback a fraudster wants — is refused and
        returns ``False`` without moving funds. This is the irrevocability gate.

        Example::

            reversed_ = pay.recall_a2a(PaymentRef("a1"), "i1")
        """
        receipt = self._payments.get(ref)
        if receipt is None:
            return False
        meta = self._settled_meta.setdefault(ref, {})
        if meta.get("reversed"):
            return False
        if self.intent_covers(intent_ref, receipt.amount.amount, receipt.payee):
            return False
        self._debit(receipt.payee, receipt.amount.amount)
        self._credit(receipt.payer, receipt.amount.amount)
        meta["reversed"] = True
        return True

    # -- programmable escrow ----------------------------------------------

    def open_escrow(
        self,
        escrow_id: str,
        payer: AgentId,
        payee: AgentId,
        amount: int,
        condition: ReleaseCondition,
        rail: str = "pix",
        intent_ref: str | None = None,
    ) -> TvistEscrow:
        """Open an escrow in ``PENDING_FUNDING``; no funds move until funded.

        Example::

            esc = pay.open_escrow("e1", AgentId("p"), AgentId("q"), 500, cond)
        """
        if amount <= 0:
            msg = f"Escrow amount must be positive: {amount}"
            raise ValueError(msg)
        if escrow_id in self._escrows:
            msg = f"Duplicate escrow id: {escrow_id}"
            raise ValueError(msg)
        esc = TvistEscrow(
            escrow_id=escrow_id,
            payer=payer,
            payee=payee,
            amount=amount,
            condition=condition,
            rail=rail,
            intent_ref=intent_ref,
        )
        self._escrows[escrow_id] = esc
        return esc

    def fund_escrow(self, escrow_id: str) -> None:
        """Move the escrow amount from payer's balance into the hold.

        Example::

            pay.fund_escrow("e1")
        """
        esc = self._escrows[escrow_id]
        if esc.status != "PENDING_FUNDING":
            msg = f"Escrow not fundable in status {esc.status}: {escrow_id}"
            raise ValueError(msg)
        self._debit(esc.payer, esc.amount)
        esc.status = "FUNDED"

    def satisfy_condition(self, escrow_id: str, proof: str) -> bool:
        """Mark the escrow's release condition satisfied iff ``proof`` matches.

        Returns whether the condition is now satisfied. A non-matching proof is a
        no-op — the release will stay blocked.

        Example::

            ok = pay.satisfy_condition("e1", "delivered_signed")
        """
        esc = self._escrows[escrow_id]
        if proof == esc.condition.expected:
            esc.condition.satisfied = True
        return esc.condition.satisfied

    def release_escrow(self, escrow_id: str) -> Receipt:
        """Release held funds to the payee — **only** if the condition is satisfied.

        Refuses an unsatisfied or contested escrow, so a payee cannot drain an
        escrow it never delivered against.

        Example::

            receipt = pay.release_escrow("e1")
        """
        esc = self._escrows[escrow_id]
        if esc.status == "CONTESTED":
            msg = f"Cannot release a contested escrow: {escrow_id}"
            raise ValueError(msg)
        if esc.status != "FUNDED":
            msg = f"Escrow not releasable in status {esc.status}: {escrow_id}"
            raise ValueError(msg)
        if not esc.condition.satisfied:
            msg = f"Release condition not satisfied for escrow: {escrow_id}"
            raise ValueError(msg)
        self._credit(esc.payee, esc.amount)
        esc.status = "RELEASED"
        ref = PaymentRef(f"escrow-{escrow_id}")
        receipt = Receipt(
            ref=ref, payer=esc.payer, payee=esc.payee, amount=Money(amount=esc.amount)
        )
        self._payments[ref] = receipt
        return receipt

    def contest_escrow(self, escrow_id: str, reason_code: str) -> TvistEscrow:
        """Contest a funded escrow, blocking release pending mediation.

        Example::

            pay.contest_escrow("e1", "goods_not_received")
        """
        if reason_code not in REASON_CODES:
            msg = f"Unknown reason code: {reason_code}"
            raise ValueError(msg)
        esc = self._escrows[escrow_id]
        if esc.status != "FUNDED":
            msg = f"Only a funded escrow can be contested: {escrow_id}"
            raise ValueError(msg)
        esc.status = "CONTESTED"
        return esc

    def refund_escrow(self, escrow_id: str) -> None:
        """Return a contested escrow's held funds to the payer (mediation outcome).

        Example::

            pay.refund_escrow("e1")
        """
        esc = self._escrows[escrow_id]
        if esc.status != "CONTESTED":
            msg = f"Only a contested escrow can be refunded: {escrow_id}"
            raise ValueError(msg)
        self._credit(esc.payer, esc.amount)
        esc.status = "REFUNDED"
