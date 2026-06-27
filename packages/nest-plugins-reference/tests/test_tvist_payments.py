# SPDX-License-Identifier: Apache-2.0
"""Tests for the Tvist dispute + escrow + intent-vault payments plugin.

Covers the stock ``Payments`` protocol, content-addressed evidence, the v1
evidence gate (friendly fraud is represented, legitimate disputes refund), the
v2 irrevocability gate (no unilateral clawback of a settled A2A payment), escrow
release conditions, agent mandate enforcement, and the conservation-of-funds
invariant under a random operation sequence.
"""

from __future__ import annotations

import random
from typing import Any

import pytest
from nest_core.types import AgentId, Money, PaymentRef, PaymentStatus
from nest_plugins_reference.payments.tvist import (
    DEFAULT_FIGHT_THRESHOLD,
    IntentRecord,
    ReleaseCondition,
    TvistPayments,
    content_hash,
)


def _fresh(initial: int = 10000) -> TvistPayments:
    """A ledger where ``buyer`` holds ``initial`` and everyone else starts at 0."""
    return TvistPayments(
        AgentId("buyer"),
        balances={AgentId("buyer"): initial, AgentId("merchant"): 0, AgentId("payee"): 0},
    )


class TestStockProtocol:
    """The plugin is a drop-in for the stock Payments protocol."""

    @pytest.mark.asyncio
    async def test_pay_then_verify(self) -> None:
        pay = _fresh()
        await pay.pay(AgentId("merchant"), Money(amount=200), PaymentRef("p1"))
        assert pay.balance(AgentId("merchant")) == 200
        assert pay.balance(AgentId("buyer")) == 9800
        assert await pay.verify_payment(PaymentRef("p1")) == PaymentStatus.CONFIRMED

    @pytest.mark.asyncio
    async def test_refund_round_trips(self) -> None:
        pay = _fresh()
        await pay.pay(AgentId("merchant"), Money(amount=200), PaymentRef("p1"))
        await pay.refund(PaymentRef("p1"))
        assert pay.balance(AgentId("buyer")) == 10000
        assert await pay.verify_payment(PaymentRef("p1")) == PaymentStatus.REFUNDED

    @pytest.mark.asyncio
    async def test_pay_insufficient_balance(self) -> None:
        pay = _fresh(initial=100)
        with pytest.raises(ValueError, match="Insufficient balance"):
            await pay.pay(AgentId("merchant"), Money(amount=200), PaymentRef("p1"))

    @pytest.mark.asyncio
    async def test_duplicate_ref(self) -> None:
        pay = _fresh()
        await pay.pay(AgentId("merchant"), Money(amount=10), PaymentRef("p1"))
        with pytest.raises(ValueError, match="Duplicate"):
            await pay.pay(AgentId("merchant"), Money(amount=10), PaymentRef("p1"))


class TestEvidence:
    """Content-addressed evidence: hash is stable and tamper-evident."""

    def test_hash_is_deterministic(self) -> None:
        a = {"kind": "delivery_signed", "carrier": "postnord", "tracking_no": "X1"}
        assert content_hash(a) == content_hash(dict(reversed(list(a.items()))))

    def test_verify_evidence_roundtrip(self) -> None:
        pay = _fresh()
        h = pay.register_evidence({"kind": "delivery_signed", "carrier": "dhl"})
        assert pay.verify_evidence(h)
        assert not pay.verify_evidence("0" * 64)


class TestRegions:
    """The governing region is negotiated up front and its regime is enforced."""

    def test_negotiate_picks_client_preference_in_agent_set(self) -> None:
        # Client prefers Pix; both accept SEPA and Pix -> client's first wins.
        agreed = TvistPayments.negotiate_region(["br_pix", "eu_sepa"], ["eu_sepa", "br_pix"])
        assert agreed == "br_pix"

    def test_negotiate_no_overlap_returns_none(self) -> None:
        assert TvistPayments.negotiate_region(["br_pix"], ["us_fednow"]) is None

    def test_negotiate_unknown_region_is_skipped(self) -> None:
        assert TvistPayments.negotiate_region(["atlantis", "eu_sepa"], ["eu_sepa"]) == "eu_sepa"

    @pytest.mark.asyncio
    async def test_nordic_settlement_is_reversible(self) -> None:
        pay = _fresh()
        # Nordic BNPL is not irrevocable, so a direct refund is allowed.
        await pay.settle_a2a(AgentId("payee"), Money(amount=100), PaymentRef("n1"), region="nordic")
        await pay.refund(PaymentRef("n1"))
        assert pay.balance(AgentId("payee")) == 0

    @pytest.mark.asyncio
    async def test_fednow_forbids_recall_even_on_mismatch(self) -> None:
        pay = _fresh()
        await pay.settle_a2a(
            AgentId("payee"), Money(amount=300), PaymentRef("f1"), region="us_fednow"
        )
        pay.store_intent(IntentRecord("i1", AgentId("buyer"), budget=100))  # clear mismatch
        # FedNow's regime disallows recall outright — escrow is the only protection.
        assert pay.recall_a2a(PaymentRef("f1"), "i1") is False
        assert pay.balance(AgentId("payee")) == 300

    @pytest.mark.asyncio
    async def test_pix_recall_outside_window_is_refused(self) -> None:
        pay = _fresh()
        await pay.settle_a2a(
            AgentId("payee"), Money(amount=300), PaymentRef("p1"), region="br_pix", at_tick=0.0
        )
        pay.store_intent(IntentRecord("i1", AgentId("buyer"), budget=100))  # mismatch
        # Pix MED 2.0 window is 11 ticks; a recall at tick 50 is too late.
        assert pay.recall_a2a(PaymentRef("p1"), "i1", current_tick=50.0) is False
        # Inside the window the same justified recall lands.
        await pay.settle_a2a(
            AgentId("payee"), Money(amount=120), PaymentRef("p2"), region="br_pix", at_tick=0.0
        )
        assert pay.recall_a2a(PaymentRef("p2"), "i1", current_tick=5.0) is True

    @pytest.mark.asyncio
    async def test_dispute_reason_must_be_in_region_taxonomy(self) -> None:
        pay = _fresh()
        await pay.pay(AgentId("merchant"), Money(amount=100), PaymentRef("d1"))
        # pix_med_return is not a Nordic reason code.
        with pytest.raises(ValueError, match="not accepted in region"):
            pay.open_dispute(PaymentRef("d1"), "pix_med_return", AgentId("buyer"), region="nordic")
        # A Nordic-valid reason is accepted.
        case = pay.open_dispute(
            PaymentRef("d1"), "goods_not_received", AgentId("buyer"), region="nordic"
        )
        assert case.region == "nordic"

    def test_region_requiring_delivery_rejects_bare_timer_escrow(self) -> None:
        pay = _fresh()
        cond = ReleaseCondition(type="time_elapsed", expected="t")
        with pytest.raises(ValueError, match="requires a delivery"):
            pay.open_escrow("e1", AgentId("buyer"), AgentId("payee"), 100, cond, region="br_pix")


class TestV1DisputeGate:
    """v1: representment is gated on verified evidence clearing the fight threshold."""

    @pytest.mark.asyncio
    async def test_friendly_fraud_is_represented_not_refunded(self) -> None:
        # Cardholder received the goods; merchant holds a signed delivery proof
        # plus a device-match signal — together they clear the fight threshold.
        pay = _fresh()
        await pay.pay(AgentId("merchant"), Money(amount=200), PaymentRef("p1"))
        h = pay.register_evidence({"kind": "delivery_signed", "ref": "p1"})
        h2 = pay.register_evidence({"kind": "device_match", "ref": "p1"})
        case = pay.open_dispute(PaymentRef("p1"), "fraud", AgentId("buyer"))
        score = pay.assemble_evidence(case.case_id, [h, h2])
        assert score >= DEFAULT_FIGHT_THRESHOLD  # 0.55 + 0.15 = 0.70
        outcome, merchant_won = pay.resolve_dispute(case.case_id)
        assert outcome == "represented"
        assert merchant_won
        # The friendly-fraud claimant recovered nothing.
        assert pay.balance(AgentId("merchant")) == 200
        assert pay.balance(AgentId("buyer")) == 9800

    @pytest.mark.asyncio
    async def test_legitimate_dispute_refunds(self) -> None:
        # Goods never arrived; merchant has no delivery evidence to represent with.
        pay = _fresh()
        await pay.pay(AgentId("merchant"), Money(amount=200), PaymentRef("p1"))
        case = pay.open_dispute(PaymentRef("p1"), "goods_not_received", AgentId("buyer"))
        pay.assemble_evidence(case.case_id, [])  # nothing to cite
        outcome, merchant_won = pay.resolve_dispute(case.case_id)
        assert outcome == "refunded"
        assert not merchant_won
        assert pay.balance(AgentId("buyer")) == 10000

    @pytest.mark.asyncio
    async def test_unverifiable_evidence_does_not_count(self) -> None:
        pay = _fresh()
        await pay.pay(AgentId("merchant"), Money(amount=200), PaymentRef("p1"))
        case = pay.open_dispute(PaymentRef("p1"), "fraud", AgentId("buyer"))
        # Cite a hash that was never registered — it must not move the score.
        score = pay.assemble_evidence(case.case_id, ["deadbeef" * 8])
        assert score == 0.0
        assert pay.resolve_dispute(case.case_id)[0] == "refunded"


class TestV2Irrevocability:
    """v2: settled A2A is irrevocable except on a verifiable-intent mismatch."""

    @pytest.mark.asyncio
    async def test_settled_a2a_refuses_direct_refund(self) -> None:
        pay = _fresh()
        await pay.settle_a2a(AgentId("payee"), Money(amount=300), PaymentRef("a1"), rail="pix")
        with pytest.raises(ValueError, match="Irrevocable"):
            await pay.refund(PaymentRef("a1"))

    @pytest.mark.asyncio
    async def test_recall_without_mismatch_is_refused(self) -> None:
        pay = _fresh()
        pay.store_intent(IntentRecord("i1", AgentId("buyer"), budget=500))
        await pay.settle_a2a(AgentId("payee"), Money(amount=300), PaymentRef("a1"), intent_ref="i1")
        # 300 is within the 500 mandate -> no mismatch -> clawback refused.
        assert pay.recall_a2a(PaymentRef("a1"), "i1") is False
        assert pay.balance(AgentId("payee")) == 300

    @pytest.mark.asyncio
    async def test_recall_on_mandate_breach_succeeds(self) -> None:
        pay = _fresh()
        pay.store_intent(IntentRecord("i1", AgentId("buyer"), budget=100))
        # Agent settles within an unbound flow, then intent shows it exceeded mandate.
        await pay.settle_a2a(AgentId("payee"), Money(amount=300), PaymentRef("a1"))
        assert pay.recall_a2a(PaymentRef("a1"), "i1") is True
        assert pay.balance(AgentId("payee")) == 0
        assert pay.balance(AgentId("buyer")) == 10000

    @pytest.mark.asyncio
    async def test_over_mandate_settlement_blocked(self) -> None:
        pay = _fresh()
        pay.store_intent(IntentRecord("i1", AgentId("buyer"), budget=100))
        with pytest.raises(ValueError, match="exceeds agent mandate"):
            await pay.settle_a2a(
                AgentId("payee"), Money(amount=300), PaymentRef("a1"), intent_ref="i1"
            )


class TestV2Escrow:
    """v2: escrow releases only when its typed condition is satisfied."""

    def test_release_blocked_until_condition_met(self) -> None:
        pay = _fresh()
        cond = ReleaseCondition(type="delivery_proof", expected="delivered_signed")
        pay.open_escrow("e1", AgentId("buyer"), AgentId("payee"), 400, cond)
        pay.fund_escrow("e1")
        assert pay.balance(AgentId("buyer")) == 9600
        with pytest.raises(ValueError, match="condition not satisfied"):
            pay.release_escrow("e1")
        pay.satisfy_condition("e1", "wrong_proof")
        with pytest.raises(ValueError, match="condition not satisfied"):
            pay.release_escrow("e1")
        assert pay.satisfy_condition("e1", "delivered_signed")
        pay.release_escrow("e1")
        assert pay.balance(AgentId("payee")) == 400

    def test_contested_escrow_refunds_payer(self) -> None:
        pay = _fresh()
        cond = ReleaseCondition(type="attestation", expected="work_accepted")
        pay.open_escrow("e1", AgentId("buyer"), AgentId("payee"), 400, cond)
        pay.fund_escrow("e1")
        pay.contest_escrow("e1", "not_as_described")
        with pytest.raises(ValueError, match="contested"):
            pay.release_escrow("e1")
        pay.refund_escrow("e1")
        assert pay.balance(AgentId("buyer")) == 10000


class TestConservation:
    """Total funds (balances + escrow holds) are invariant under any op sequence."""

    @pytest.mark.asyncio
    async def test_conservation_under_random_op_sequence(self) -> None:
        rng = random.Random(1234)
        # The test owns the shared stores so it can drive a random op sequence
        # through public methods without ever reading the plugin's internals.
        agents = [AgentId(f"a{i}") for i in range(5)]
        balances = {a: 1000 for a in agents}
        payments_store: dict[PaymentRef, Any] = {}
        escrows_store: dict[str, Any] = {}
        initial_total = sum(balances.values())

        def handle(owner: AgentId) -> TvistPayments:
            return TvistPayments(
                owner, balances=balances, payments=payments_store, escrows=escrows_store
            )

        pay = handle(AgentId("a0"))
        refundable: list[PaymentRef] = []
        funded_escrows: list[str] = []
        ref_n = 0
        esc_n = 0
        for _ in range(200):
            assert pay.total_funds() == initial_total
            op = rng.randint(0, 4)
            payer, payee = rng.sample(agents, 2)
            amount = rng.randint(1, 50)
            try:
                if op == 0:
                    ref_n += 1
                    ref = PaymentRef(f"r{ref_n}")
                    await handle(payer).pay(payee, Money(amount=amount), ref)
                    refundable.append(ref)
                elif op == 1 and refundable:
                    ref = refundable.pop(rng.randrange(len(refundable)))
                    await pay.refund(ref)
                elif op == 2 and balances[payer] >= amount:
                    esc_n += 1
                    eid = f"e{esc_n}"
                    cond = ReleaseCondition(type="time_elapsed", expected="t")
                    h = handle(payer)
                    h.open_escrow(eid, payer, payee, amount, cond)
                    h.fund_escrow(eid)
                    funded_escrows.append(eid)
                elif op == 3 and funded_escrows:
                    eid = funded_escrows.pop(rng.randrange(len(funded_escrows)))
                    pay.satisfy_condition(eid, "t")
                    pay.release_escrow(eid)
                elif op == 4 and funded_escrows:
                    eid = funded_escrows.pop(rng.randrange(len(funded_escrows)))
                    pay.contest_escrow(eid, "fraud")
                    pay.refund_escrow(eid)
            except ValueError:
                pass
        assert pay.total_funds() == initial_total
