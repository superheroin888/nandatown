# SPDX-License-Identifier: Apache-2.0
"""Tvist API — an escrow, consent, and dispute service for AI agents.

A self-contained HTTP service that lets one AI agent transact safely with another
over notional credits. It answers the questions an agent must resolve *before and
after* it moves value on someone's behalf:

* Which jurisdiction's dispute rules should both parties adhere to? (Nash-optimal
  region recommendation over a global list of real instant/A2A rails.)
* Is this payment within the principal's explicit consent? (intent/consent vault)
* Hold the funds until the service is delivered. (programmable escrow)
* Can this settled payment be recalled? (region-aware, mandate-gated recall)
* Is this dispute reason valid in the agreed region? (dispute taxonomy)

State is an in-memory ledger of **notional credits** — this is a sandbox, not a
bank and not real money. Accounts are created on first use with a starting
balance. Everything is deterministic and self-describing (`GET /` lists the API;
FastAPI serves OpenAPI at `/openapi.json` and docs at `/docs`).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# Region regimes — a global list of real instant / A2A rails
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Regime:
    """The governing dispute rules of one payment region / jurisdiction."""

    label: str
    rail: str
    irrevocable: bool
    recall_allowed: bool
    recall_window_ticks: int
    reason_codes: frozenset[str]
    requires_delivery_for_escrow: bool


_CORE = frozenset({"fraud", "agent_exceeded_mandate", "recall_request"})
_CORE_MISTAKEN = _CORE | {"mistaken_payment"}
_NO_RECALL = frozenset({"agent_exceeded_mandate", "verifiable_intent_mismatch"})
_ALL = frozenset(
    {
        "goods_not_received",
        "not_as_described",
        "fraud",
        "recurring_disputed",
        "agent_exceeded_mandate",
        "verifiable_intent_mismatch",
        "recall_request",
        "mistaken_payment",
        "sepa_recall",
        "pix_med_return",
    }
)

REGIONS: dict[str, Regime] = {
    "global": Regime("Ungoverned (permissive default)", "generic", True, True, 0, _ALL, False),
    "eu_sepa": Regime(
        "EU - SEPA Instant (SCT Inst recall)", "sepa_instant", True, True, 10,
        frozenset({"sepa_recall", "recall_request", "verifiable_intent_mismatch",
                   "agent_exceeded_mandate", "fraud", "not_as_described"}), True,
    ),
    "uk_fps": Regime(
        "UK - Faster Payments (APP reimbursement)", "fps", True, True, 5,
        frozenset({"fraud", "goods_not_received", "not_as_described",
                   "agent_exceeded_mandate", "recall_request"}), True,
    ),
    "nordic": Regime(
        "Nordics - Klarna / BNPL / Swish", "bnpl", False, True, 0,
        frozenset({"goods_not_received", "not_as_described", "fraud", "recurring_disputed"}), False,
    ),
    "ch_twint": Regime("Switzerland - TWINT", "twint", True, True, 5, _CORE, True),
    "br_pix": Regime(
        "Brazil - Pix (MED 2.0, 11-day recovery)", "pix", True, True, 11,
        frozenset({"pix_med_return", "recall_request", "verifiable_intent_mismatch",
                   "agent_exceeded_mandate", "fraud"}), True,
    ),
    "mx_spei": Regime("Mexico - SPEI", "spei", True, False, 0, _NO_RECALL, True),
    "us_fednow": Regime("US - FedNow (no federal recall standard)", "fednow", True, False, 0,
                        _NO_RECALL, True),
    "us_rtp": Regime("US - RTP (TCH, request-for-return)", "rtp", True, False, 0,
                     _NO_RECALL | {"mistaken_payment"}, True),
    "ca_interac": Regime("Canada - Interac / Real-Time Rail", "interac", True, True, 3,
                         _CORE_MISTAKEN, True),
    "in_upi": Regime(
        "India - UPI (NPCI dispute flows)", "upi", True, True, 7,
        frozenset({"fraud", "goods_not_received", "verifiable_intent_mismatch",
                   "agent_exceeded_mandate", "recall_request"}), True,
    ),
    "sg_fast": Regime("Singapore - FAST / PayNow", "fast", True, True, 5, _CORE, True),
    "au_npp": Regime("Australia - NPP / Osko", "npp", True, True, 5, _CORE_MISTAKEN, True),
    "jp_zengin": Regime("Japan - Zengin", "zengin", True, True, 4, _CORE_MISTAKEN, True),
    "hk_fps": Regime("Hong Kong - FPS", "hkfps", True, True, 5, _CORE, True),
    "ae_aani": Regime("UAE - Aani", "aani", True, True, 5, _CORE, True),
    "sa_sarie": Regime("Saudi Arabia - sarie", "sarie", True, True, 5, _CORE, True),
    "za_payshap": Regime("South Africa - PayShap", "payshap", True, False, 0, _NO_RECALL, True),
    "ng_nip": Regime("Nigeria - NIBSS Instant Payments", "nip", True, True, 3, _CORE_MISTAKEN, True),
    "ke_mpesa": Regime("Kenya - M-Pesa / PesaLink", "mpesa", True, True, 2, _CORE_MISTAKEN, True),
    "cn_ibps": Regime("China - IBPS / UnionPay", "ibps", True, False, 0, _NO_RECALL, True),
    "stablecoin_x402": Regime("Stablecoin - Coinbase x402 (no chargeback)", "stablecoin_usdc",
                              True, False, 0, _NO_RECALL, True),
}


def recommend_region(client_prefs: list[str], agent_prefs: list[str]) -> str | None:
    """Nash-bargaining optimal region over the regions both parties accept.

    Ordinal utilities from each ranked list; maximise the Nash product
    u_client*u_agent, tie-broken by maximin fairness, then welfare, then a stable
    id. Returns None when the parties share no acceptable region.
    """
    uc = {r: len(client_prefs) - i for i, r in enumerate(client_prefs)}
    ua = {r: len(agent_prefs) - i for i, r in enumerate(agent_prefs)}
    feasible = [r for r in uc if r in ua and r in REGIONS]
    if not feasible:
        return None
    return min(feasible, key=lambda r: (-(uc[r] * ua[r]), -min(uc[r], ua[r]), -(uc[r] + ua[r]), r))


# ---------------------------------------------------------------------------
# Legal dispute taxonomy — civil & commercial law grounding
# ---------------------------------------------------------------------------
# Every canonical reason code maps to a substantive legal category with its
# civil-law and common-law doctrinal basis. Every jurisdiction carries its real
# legal instruments (statute / scheme rulebook / regulator) with links to the
# official source, so a dispute filed under a region is traceable to the law
# that actually governs it there.

LEGAL_CATEGORIES: dict[str, dict[str, str]] = {
    "non_performance": {
        "label": "Non-performance (non-delivery)",
        "description": "Seller/provider failed to perform the primary obligation.",
        "civil_law_basis": "Breach of obligation to perform: BGB §§275, 323 (DE); "
                           "Code civil arts. 1217, 1610 (FR); CISG arts. 30, 45, 49.",
        "common_law_basis": "Breach of contract; total failure of consideration; "
                            "UCC §2-711 buyer's remedies (US).",
    },
    "non_conformity": {
        "label": "Non-conformity (defective performance)",
        "description": "Delivered, but not as described / not of contractual quality.",
        "civil_law_basis": "Conformity of goods: Directive (EU) 2019/771; CISG art. 35; "
                           "vices cachés, Code civil art. 1641 (FR).",
        "common_law_basis": "Implied terms: Consumer Rights Act 2015 ss. 9–11 (UK); "
                            "UCC §§2-314/2-315 warranties (US).",
    },
    "fraud_unauthorized": {
        "label": "Fraud / unauthorized transaction",
        "description": "Payment procured by deception or executed without authority.",
        "civil_law_basis": "Dol / dolus vitiating consent (Code civil art. 1137); "
                           "PSD2 arts. 64, 73–74 unauthorized-transaction liability.",
        "common_law_basis": "Tort of deceit / fraudulent misrepresentation; "
                            "EFTA + Regulation E, 12 CFR 1005 (US consumer EFT).",
    },
    "agency_mandate": {
        "label": "Agency / mandate (excess of authority)",
        "description": "An agent acted outside the principal's mandate — the core "
                       "agentic-commerce dispute.",
        "civil_law_basis": "Mandate & representation: BGB §§164–181 (falsus procurator "
                           "§177); Code civil arts. 1153–1161, 1984 ff.; CO art. 394 ff. (CH).",
        "common_law_basis": "Actual vs apparent authority, ratification: Restatement "
                            "(Third) of Agency (US); Indian Contract Act 1872 ss. 182–238.",
    },
    "unjust_enrichment": {
        "label": "Mistaken payment (unjust enrichment)",
        "description": "Value transferred without legal ground — wrong payee or amount.",
        "civil_law_basis": "Condictio indebiti: BGB §812; Code civil art. 1302 "
                           "(paiement de l'indu); CO arts. 62 ff. (CH).",
        "common_law_basis": "Restitution for mistaken payment (Barclays Bank v W.J. "
                            "Simms [1980]); unjust enrichment.",
    },
    "procedural_recall": {
        "label": "Procedural recall (scheme remedy)",
        "description": "Rulebook-level return/recovery procedure of the rail itself — "
                       "lex specialis layered over the substantive claim.",
        "civil_law_basis": "Scheme rulebooks as incorporated contract terms: EPC SCT "
                           "Inst Rulebook recall; Pix MED under Resolução BCB 1/2020.",
        "common_law_basis": "Operating rules as binding multilateral contract: Reg J "
                            "subpart C / UCC 4A-211 (US); Pay.UK / TCH rules.",
    },
    "continuing_obligations": {
        "label": "Recurring / continuing obligations",
        "description": "Disputes over subscriptions and repeated charges.",
        "civil_law_basis": "Termination of continuing obligations: BGB §314; consumer "
                           "withdrawal, Directive 2011/83/EU.",
        "common_law_basis": "Cancellation & preauthorized-transfer stops: Reg E, "
                            "12 CFR 1005.10 (US); contract termination at common law.",
    },
}

DISCLAIMER = (
    "Technical demonstration only — a notional-credits sandbox, not a bank, "
    "payment institution, or law firm. Legal references cite real primary "
    "sources but are engineering-grade mappings, not legal advice; obtain "
    "qualified local counsel before relying on them in any jurisdiction."
)


def legal_basis_for(region: str, reason_code: str) -> dict[str, Any] | None:
    """The citation string an agent can quote when filing under a region.

    Picks the operative doctrinal basis by the region's legal tradition
    (civil vs common law); returns None for unknown codes.
    """
    cat = REASON_LEGAL.get(reason_code)
    if cat is None:
        return None
    src = LEGAL_SOURCES.get(region, LEGAL_SOURCES["global"])
    system = str(src["legal_system"])
    civilish = "civil" in system or "Sharia" in system or "transnational" in system
    c = LEGAL_CATEGORIES[cat]
    return {
        "category": cat,
        "label": c["label"],
        "legal_system": system,
        "citation": c["civil_law_basis"] if civilish else c["common_law_basis"],
    }


REASON_LEGAL: dict[str, str] = {
    "goods_not_received": "non_performance",
    "not_as_described": "non_conformity",
    "fraud": "fraud_unauthorized",
    "recurring_disputed": "continuing_obligations",
    "agent_exceeded_mandate": "agency_mandate",
    "verifiable_intent_mismatch": "agency_mandate",
    "recall_request": "procedural_recall",
    "mistaken_payment": "unjust_enrichment",
    "sepa_recall": "procedural_recall",
    "pix_med_return": "procedural_recall",
}

# Per-jurisdiction legal sources: legal system, regulator, and the operative
# instruments (payments law, scheme rulebook, consumer/civil law) with links to
# the official publication source for each country/region.
LEGAL_SOURCES: dict[str, dict[str, Any]] = {
    "global": {
        "legal_system": "transnational (lex mercatoria)",
        "regulator": "none — party autonomy / chosen law",
        "instruments": [
            {"name": "UN Convention on Contracts for the International Sale of Goods (CISG)",
             "citation": "1489 UNTS 3 (1980)", "role": "sales law",
             "url": "https://uncitral.un.org/en/texts/salegoods/conventions/sale_of_goods/cisg"},
            {"name": "UNIDROIT Principles of International Commercial Contracts",
             "citation": "UPICC 2016", "role": "contract law",
             "url": "https://www.unidroit.org/instruments/commercial-contracts/unidroit-principles-2016/"},
            {"name": "UNCITRAL Model Law on Electronic Commerce",
             "citation": "1996", "role": "e-commerce",
             "url": "https://uncitral.un.org/en/texts/ecommerce/modellaw/electronic_commerce"},
        ],
    },
    "eu_sepa": {
        "legal_system": "civil law (EU acquis)",
        "regulator": "ECB / EBA + national competent authorities",
        "instruments": [
            {"name": "Payment Services Directive 2 (PSD2)",
             "citation": "Directive (EU) 2015/2366", "role": "payments law",
             "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32015L2366"},
            {"name": "Instant Payments Regulation",
             "citation": "Regulation (EU) 2024/886", "role": "instant credit transfers",
             "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32024R0886"},
            {"name": "EPC SCT Instant Rulebook (recall procedures)",
             "citation": "EPC 004-16", "role": "scheme rulebook",
             "url": "https://www.europeanpaymentscouncil.eu/document-library/rulebooks/sepa-instant-credit-transfer-rulebook"},
            {"name": "Sale of Goods Directive (conformity)",
             "citation": "Directive (EU) 2019/771", "role": "consumer/commercial law",
             "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32019L0771"},
        ],
    },
    "uk_fps": {
        "legal_system": "common law",
        "regulator": "FCA / Payment Systems Regulator (PSR)",
        "instruments": [
            {"name": "Payment Services Regulations 2017",
             "citation": "SI 2017/752", "role": "payments law",
             "url": "https://www.legislation.gov.uk/uksi/2017/752/contents"},
            {"name": "PSR APP-fraud mandatory reimbursement (FPS)",
             "citation": "PSR Specific Direction 20 (2024)", "role": "scheme remedy",
             "url": "https://www.psr.org.uk/our-work/app-scams/"},
            {"name": "Consumer Rights Act 2015",
             "citation": "c. 15, ss. 9–11", "role": "consumer/commercial law",
             "url": "https://www.legislation.gov.uk/ukpga/2015/15/contents"},
        ],
    },
    "nordic": {
        "legal_system": "civil law (Nordic)",
        "regulator": "Finansinspektionen (SE); ARN for consumer ADR",
        "instruments": [
            {"name": "Betaltjänstlag (Swedish Payment Services Act)",
             "citation": "SFS 2010:751", "role": "payments law",
             "url": "https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/lag-2010751-om-betaltjanster_sfs-2010-751/"},
            {"name": "Konsumentköplag (Consumer Sales Act)",
             "citation": "SFS 2022:260", "role": "consumer/commercial law",
             "url": "https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/konsumentkoplag-2022260_sfs-2022-260/"},
            {"name": "Konsumentkreditlag §29 (connected-credit claims vs BNPL)",
             "citation": "SFS 2010:1846", "role": "BNPL dispute basis",
             "url": "https://www.riksdagen.se/sv/dokument-och-lagar/dokument/svensk-forfattningssamling/konsumentkreditlag-20101846_sfs-2010-1846/"},
        ],
    },
    "ch_twint": {
        "legal_system": "civil law",
        "regulator": "FINMA / SNB oversight",
        "instruments": [
            {"name": "Swiss Code of Obligations (mandate art. 394 ff.; unjust enrichment art. 62 ff.)",
             "citation": "SR 220", "role": "civil/commercial law",
             "url": "https://www.fedlex.admin.ch/eli/cc/27/317_321_377/en"},
            {"name": "TWINT scheme terms (participant rules)",
             "citation": "TWINT AG", "role": "scheme rulebook",
             "url": "https://www.twint.ch/en/legal/"},
        ],
    },
    "br_pix": {
        "legal_system": "civil law",
        "regulator": "Banco Central do Brasil (BCB)",
        "instruments": [
            {"name": "Regulamento do Pix (incl. Mecanismo Especial de Devolução, MED)",
             "citation": "Resolução BCB nº 1/2020 (as amended)", "role": "scheme rulebook + recall",
             "url": "https://www.bcb.gov.br/estabilidadefinanceira/pix"},
            {"name": "Código de Defesa do Consumidor",
             "citation": "Lei nº 8.078/1990", "role": "consumer law",
             "url": "https://www.planalto.gov.br/ccivil_03/leis/l8078compilado.htm"},
            {"name": "Código Civil (contract, mandate arts. 653 ff., enrichment art. 884)",
             "citation": "Lei nº 10.406/2002", "role": "civil/commercial law",
             "url": "https://www.planalto.gov.br/ccivil_03/leis/2002/l10406compilada.htm"},
        ],
    },
    "mx_spei": {
        "legal_system": "civil law",
        "regulator": "Banco de México / CONDUSEF",
        "instruments": [
            {"name": "Circular 14/2017 (SPEI operating rules)",
             "citation": "Banxico Circular 14/2017", "role": "scheme rulebook",
             "url": "https://www.banxico.org.mx/marco-normativo/normativa-emitida-por-el-banco-de-mexico/circular-14-2017/"},
            {"name": "Ley de Protección y Defensa al Usuario de Servicios Financieros",
             "citation": "DOF 18-01-1999 (as amended)", "role": "consumer financial law",
             "url": "https://www.condusef.gob.mx/"},
        ],
    },
    "us_fednow": {
        "legal_system": "common law (UCC)",
        "regulator": "Federal Reserve / CFPB (consumer)",
        "instruments": [
            {"name": "Regulation J, Subpart C (funds transfers through Fedwire/FedNow, "
                     "incorporating UCC Article 4A)",
             "citation": "12 CFR Part 210", "role": "payments law",
             "url": "https://www.ecfr.gov/current/title-12/chapter-II/subchapter-A/part-210"},
            {"name": "FedNow Service Operating Procedures",
             "citation": "FRB Services", "role": "scheme rulebook",
             "url": "https://www.frbservices.org/financial-services/fednow"},
            {"name": "EFTA + Regulation E (consumer EFT error resolution)",
             "citation": "12 CFR Part 1005", "role": "consumer law",
             "url": "https://www.ecfr.gov/current/title-12/chapter-X/part-1005"},
        ],
    },
    "us_rtp": {
        "legal_system": "common law (UCC)",
        "regulator": "OCC/Fed oversight of TCH; CFPB (consumer)",
        "instruments": [
            {"name": "TCH RTP System Operating Rules (request for return of funds)",
             "citation": "The Clearing House", "role": "scheme rulebook",
             "url": "https://www.theclearinghouse.org/payment-systems/rtp/institution"},
            {"name": "UCC Article 4A (funds transfers)",
             "citation": "UCC art. 4A", "role": "payments law",
             "url": "https://www.law.cornell.edu/ucc/4A"},
        ],
    },
    "ca_interac": {
        "legal_system": "common law (Quebec: civil law)",
        "regulator": "Bank of Canada / Payments Canada; FCAC (consumer)",
        "instruments": [
            {"name": "Canadian Payments Act",
             "citation": "R.S.C. 1985, c. C-21", "role": "payments law",
             "url": "https://laws-lois.justice.gc.ca/eng/acts/c-21/"},
            {"name": "Payments Canada rules / Real-Time Rail framework",
             "citation": "Payments Canada", "role": "scheme rulebook",
             "url": "https://www.payments.ca/systems-services/payment-systems"},
        ],
    },
    "in_upi": {
        "legal_system": "common law",
        "regulator": "RBI / NPCI",
        "instruments": [
            {"name": "Payment and Settlement Systems Act, 2007",
             "citation": "Act 51 of 2007", "role": "payments law",
             "url": "https://www.indiacode.nic.in/handle/123456789/2063"},
            {"name": "NPCI UPI Procedural Guidelines + UDIR (online dispute resolution)",
             "citation": "NPCI circulars", "role": "scheme rulebook + ODR",
             "url": "https://www.npci.org.in/what-we-do/upi/circular"},
            {"name": "Indian Contract Act, 1872 (agency, ss. 182–238)",
             "citation": "Act 9 of 1872", "role": "mandate/agency law",
             "url": "https://www.indiacode.nic.in/handle/123456789/2187"},
            {"name": "RBI Integrated Ombudsman Scheme (RB-IOS)",
             "citation": "RBI, 2021", "role": "consumer redress",
             "url": "https://rbi.org.in/Scripts/AboutUsDisplay.aspx?pg=IntegratedOmbudsman.htm"},
        ],
    },
    "sg_fast": {
        "legal_system": "common law",
        "regulator": "MAS",
        "instruments": [
            {"name": "Payment Services Act 2019",
             "citation": "No. 2 of 2019", "role": "payments law",
             "url": "https://sso.agc.gov.sg/Act/PSA2019"},
            {"name": "MAS E-Payments User Protection Guidelines + Shared Responsibility Framework",
             "citation": "MAS Guidelines", "role": "consumer protection / scam losses",
             "url": "https://www.mas.gov.sg/regulation/guidelines/e-payments-user-protection-guidelines"},
        ],
    },
    "au_npp": {
        "legal_system": "common law",
        "regulator": "RBA / ASIC; AFCA for ADR",
        "instruments": [
            {"name": "ePayments Code",
             "citation": "ASIC, 2022 update", "role": "consumer payments code",
             "url": "https://asic.gov.au/regulatory-resources/financial-services/epayments-code/"},
            {"name": "NPP Regulations and Procedures",
             "citation": "NPP Australia", "role": "scheme rulebook",
             "url": "https://nppa.com.au/regulations/"},
            {"name": "Australian Consumer Law (consumer guarantees)",
             "citation": "Sch 2, Competition and Consumer Act 2010", "role": "commercial law",
             "url": "https://www.legislation.gov.au/C2004A00109/latest/text"},
        ],
    },
    "jp_zengin": {
        "legal_system": "civil law",
        "regulator": "FSA / BOJ oversight",
        "instruments": [
            {"name": "Civil Code (mandate arts. 643 ff.; unjust enrichment art. 703)",
             "citation": "Act No. 89 of 1896", "role": "civil law",
             "url": "https://www.japaneselawtranslation.go.jp/en/laws/view/3494"},
            {"name": "Payment Services Act",
             "citation": "Act No. 59 of 2009", "role": "payments law",
             "url": "https://www.japaneselawtranslation.go.jp/en/laws/view/3078"},
            {"name": "Zengin System rules (Japanese Banks' Payment Clearing Network)",
             "citation": "Zengin-Net", "role": "scheme rulebook",
             "url": "https://www.zengin-net.jp/en/"},
        ],
    },
    "hk_fps": {
        "legal_system": "common law",
        "regulator": "HKMA",
        "instruments": [
            {"name": "Payment Systems and Stored Value Facilities Ordinance",
             "citation": "Cap. 584", "role": "payments law",
             "url": "https://www.elegislation.gov.hk/hk/cap584"},
            {"name": "Sale of Goods Ordinance",
             "citation": "Cap. 26", "role": "commercial law",
             "url": "https://www.elegislation.gov.hk/hk/cap26"},
        ],
    },
    "ae_aani": {
        "legal_system": "civil law (with Sharia influence)",
        "regulator": "CBUAE / Al Etihad Payments",
        "instruments": [
            {"name": "Civil Transactions Law (agency/wakala)",
             "citation": "Federal Law No. 5 of 1985", "role": "civil law",
             "url": "https://uaelegislation.gov.ae/en/legislations/1025"},
            {"name": "Retail Payment Services and Card Schemes Regulation",
             "citation": "CBUAE Circular 15/2021", "role": "payments law",
             "url": "https://rulebook.centralbank.ae/en/rulebook/retail-payment-services-and-card-schemes-regulation"},
        ],
    },
    "sa_sarie": {
        "legal_system": "Sharia + codified civil law",
        "regulator": "SAMA",
        "instruments": [
            {"name": "Civil Transactions Law (first Saudi civil code)",
             "citation": "Royal Decree M/191 of 2023", "role": "civil law",
             "url": "https://uqn.gov.sa/"},
            {"name": "Payment Services Provider Regulations",
             "citation": "SAMA, 2020", "role": "payments law",
             "url": "https://www.sama.gov.sa/en-US/Laws/Pages/BankingRulesAndRegulations.aspx"},
        ],
    },
    "za_payshap": {
        "legal_system": "mixed (Roman-Dutch / common law)",
        "regulator": "SARB / PASA",
        "instruments": [
            {"name": "National Payment System Act",
             "citation": "Act 78 of 1998", "role": "payments law",
             "url": "https://www.resbank.co.za/en/home/what-we-do/payments-and-settlements/regulation-oversight-and-supervision"},
            {"name": "Consumer Protection Act",
             "citation": "Act 68 of 2008", "role": "consumer law",
             "url": "https://www.gov.za/documents/consumer-protection-act"},
        ],
    },
    "ng_nip": {
        "legal_system": "common law",
        "regulator": "CBN / NIBSS",
        "instruments": [
            {"name": "CBN Guidelines on Electronic Payments and instant transfers",
             "citation": "CBN circulars", "role": "payments regulation",
             "url": "https://www.cbn.gov.ng/PaymentsSystem/"},
            {"name": "Federal Competition and Consumer Protection Act",
             "citation": "FCCPA 2018", "role": "consumer law",
             "url": "https://fccpc.gov.ng/laws-regulations/"},
        ],
    },
    "ke_mpesa": {
        "legal_system": "common law",
        "regulator": "Central Bank of Kenya",
        "instruments": [
            {"name": "National Payment System Act + NPS Regulations 2014",
             "citation": "No. 39 of 2011", "role": "payments law",
             "url": "https://www.centralbank.go.ke/national-payments-system/"},
            {"name": "Consumer Protection Act",
             "citation": "No. 46 of 2012", "role": "consumer law",
             "url": "http://kenyalaw.org/kl/fileadmin/pdfdownloads/Acts/ConsumerProtectionAct_No46of2012.pdf"},
        ],
    },
    "cn_ibps": {
        "legal_system": "civil law",
        "regulator": "PBOC",
        "instruments": [
            {"name": "PRC Civil Code (contracts book III; mandate ch. 23)",
             "citation": "2020, eff. 2021", "role": "civil law",
             "url": "http://www.npc.gov.cn/englishnpc/c23934/202012/f627aa3a4651475db936899d69419d1e.shtml"},
            {"name": "E-Commerce Law of the PRC",
             "citation": "2018, eff. 2019", "role": "commercial law",
             "url": "http://www.npc.gov.cn/npc/c2/c30834/201908/t20190821_300556.html"},
            {"name": "PBOC payment & clearing rules (IBPS)",
             "citation": "PBOC", "role": "scheme rules",
             "url": "http://www.pbc.gov.cn/en/3688110/3688172/index.html"},
        ],
    },
    "stablecoin_x402": {
        "legal_system": "private ordering (contract) + emerging statute",
        "regulator": "none scheme-level; issuer regimes (e.g. MiCA) apply",
        "instruments": [
            {"name": "UCC Article 12 (controllable electronic records, 2022 amendments)",
             "citation": "ULC 2022 amendments", "role": "digital-asset commercial law",
             "url": "https://www.uniformlaws.org/committees/community-home?CommunityKey=1457c422-ddb7-40b0-8c76-39a1991651ac"},
            {"name": "Markets in Crypto-Assets Regulation (MiCA) — issuer obligations",
             "citation": "Regulation (EU) 2023/1114", "role": "issuer regulation",
             "url": "https://eur-lex.europa.eu/legal-content/EN/TXT/?uri=CELEX:32023R1114"},
            {"name": "x402 protocol specification (settlement terms by reference)",
             "citation": "Coinbase, open spec", "role": "protocol terms",
             "url": "https://github.com/coinbase/x402"},
        ],
    },
}


# ---------------------------------------------------------------------------
# In-memory notional-credits ledger
# ---------------------------------------------------------------------------

START_BALANCE = 100_000


@dataclass
class Consent:
    consent_id: str
    principal: str
    budget: int
    merchant_allowlist: list[str] | None = None


@dataclass
class Escrow:
    escrow_id: str
    payer: str
    payee: str
    amount: int
    region: str
    condition_expected: str
    delivered: bool = False
    status: str = "FUNDED"


@dataclass
class Settlement:
    ref: str
    payer: str
    payee: str
    amount: int
    region: str
    irrevocable: bool
    reversed: bool = False


@dataclass
class Delegation:
    """A machine-to-machine mandate: an agent authorises a sub-agent, capped by
    its own authority — attenuation: a child budget never exceeds its parent's."""

    delegation_id: str
    parent_id: str
    delegator: str
    agent: str
    budget: int
    depth: int


@dataclass
class Ledger:
    balances: dict[str, int] = field(default_factory=dict)
    consents: dict[str, Consent] = field(default_factory=dict)
    escrows: dict[str, Escrow] = field(default_factory=dict)
    settlements: dict[str, Settlement] = field(default_factory=dict)
    cases: dict[str, dict[str, Any]] = field(default_factory=dict)
    delegations: dict[str, Delegation] = field(default_factory=dict)
    pacts: dict[str, dict[str, Any]] = field(default_factory=dict)

    def balance(self, name: str) -> int:
        return self.balances.setdefault(name, START_BALANCE)

    def debit(self, name: str, amount: int) -> None:
        bal = self.balance(name)
        if bal < amount:
            raise HTTPException(400, f"Insufficient balance: {name} has {bal} < {amount}")
        self.balances[name] = bal - amount

    def credit(self, name: str, amount: int) -> None:
        self.balances[name] = self.balance(name) + amount


LEDGER = Ledger()


def regime(region: str) -> Regime:
    return REGIONS.get(region, REGIONS["global"])


def consent_covers(consent: Consent, amount: int, merchant: str) -> bool:
    if amount > consent.budget:
        return False
    return consent.merchant_allowlist is None or merchant in consent.merchant_allowlist


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

app = FastAPI(
    title="Tvist API",
    version="1.0.0",
    description=(
        "Escrow, consent, and dispute service for AI agents transacting on "
        "irrevocable rails. Notional credits only — a sandbox, not a bank. "
        "Dual-use: the same URL serves humans (HTML homepage, /docs) and "
        "agents (JSON index at /, /openapi.json, /skill.md)."
    ),
)

# Open CORS: the sandbox is meant to be testable from anywhere — the homepage's
# live playground, agent frameworks in browsers, or third-party tools.
from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-PAYMENT-RESPONSE"],
)


SCENARIOS: dict[str, dict[str, str]] = {
    "human_to_agent": {
        "label": "Human -> Agent",
        "gate": "consent",
        "pain": "an agent overspends the human's mandate on a final rail",
        "flow": "POST /consent -> POST /pay {consent_id} (403 over budget)",
    },
    "agent_to_subagent": {
        "label": "Agent -> Sub-agent",
        "gate": "delegation (attenuated)",
        "pain": "sub-agents exceed their delegator's authority; no chain control",
        "flow": "POST /m2m/delegate (attenuated, chains to root) -> spend via "
                "the delegation_id anywhere a consent_id works",
    },
    "agent_to_agent": {
        "label": "Agent <-> Agent",
        "gate": "handshake (Nash region + escrow)",
        "pain": "two machines with no shared jurisdiction or trust trade blind",
        "flow": "POST /m2m/handshake (Nash region + mandate + funded escrow) -> "
                "/escrow/{id}/deliver -> /release",
    },
    "agent_to_resource": {
        "label": "Agent -> Resource",
        "gate": "x402 (consent-capped, replay-safe)",
        "pain": "pay-per-call APIs on an irrevocable rail; replay + overspend risk",
        "flow": "GET /x402/resource/{name} (402) -> retry with signed X-PAYMENT "
                "(consent-capped, replay-safe)",
    },
}

_SPECTRUM_ASCII = r"""
 human ──(consent)────▶ agent ────────┐
 agent ──(delegate)───▶ sub-agent ────┤    ┌───────────────────────┐
 agent ◀─(handshake)──▶ agent ────────┼───▶│ TVIST — ONE GATE LOGIC │───▶ 22 rails
 agent ──(x402)───────▶ resource ─────┘    │ region · consent ·     │     Pix · SEPA ·
                                           │ escrow · recall/law    │     UPI · x402 …
                                           └───────────────────────┘
"""

_SPECTRUM_MERMAID = (
    "graph LR; H[Human] -->|consent| A[Agent]; "
    "A -->|delegate, attenuated| S[Sub-agent]; "
    "A <-->|handshake: Nash region + escrow| B[Counterparty agent]; "
    "A -->|x402 X-PAYMENT| R[Paid resource]; "
    "A --> G{{Tvist gates: region / consent / escrow / recall+law}}; "
    "S --> G; B --> G; R --> G; G --> RAILS[22 rails: Pix, SEPA, UPI, x402]"
)


@app.get("/spectrum")
def spectrum_view() -> dict[str, Any]:
    """The full trust spectrum, visualised for machines.

    Four relationships — human->agent, agent->sub-agent, agent<->agent,
    agent->resource — all pass through the same four Tvist gates. Returned as
    structured data plus ASCII and Mermaid renderings an agent (or a human on
    a terminal) can display directly. The interactive version lives on the
    homepage at /#spectrum.
    """
    return {
        "one_gate_logic": [
            "1 jurisdiction — Nash-optimal region, agreed before funds move",
            "2 consent — mandate/delegation checked before settlement",
            "3 escrow — funds release only on delivery proof",
            "4 resolution — regime-gated recall + law-cited disputes",
        ],
        "relationships": SCENARIOS,
        "ascii": _SPECTRUM_ASCII,
        "mermaid": _SPECTRUM_MERMAID,
        "try_it": "homepage /#spectrum — every lane is clickable and runs live",
        "disclaimer": DISCLAIMER,
    }


_HERE = Path(__file__).resolve().parent
_HOME = _HERE / "static" / "index.html"


@app.get("/", response_model=None)
def root(request: Request) -> HTMLResponse | dict[str, Any]:
    """Homepage for browsers; self-describing JSON index for agents.

    Content negotiation: a request whose Accept header prefers ``text/html`` (a
    browser) gets the animated homepage; everything else (curl, agent SDKs) gets
    the JSON endpoint index, so the SKILL.md contract is unchanged.
    """
    accept = request.headers.get("accept", "")
    if "text/html" in accept and _HOME.exists():
        return HTMLResponse(_HOME.read_text())
    return _index()


def _md_response(filename: str, download: bool) -> Response:
    """Serve a markdown file: inline (clickable/readable in any browser) by
    default, or as an attachment when ``?download=1`` is passed."""
    path = _HERE / filename
    if not path.exists():
        raise HTTPException(404, f"{filename} not found")
    if download:
        return Response(
            path.read_text(),
            media_type="text/markdown; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    return Response(
        path.read_text(),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": "inline"},
    )


# The pitch-kit artifacts, downloadable from the live service.
PITCH_FILES: dict[str, tuple[str, str, str]] = {
    "brief-pdf": ("Tvist-Executive-Brief.pdf", "application/pdf",
                  "Executive brief — one airy page, 60-second read"),
    "summary-pdf": ("Tvist-Executive-Summary.pdf", "application/pdf",
                    "Executive summary — dense one-pager"),
    "summary-docx": ("Tvist-Executive-Summary.docx",
                     "application/vnd.openxmlformats-officedocument"
                     ".wordprocessingml.document",
                     "Executive summary — full 5-page Word document"),
    "deck-pptx": ("Tvist-Executive-Summary.pptx",
                  "application/vnd.openxmlformats-officedocument"
                  ".presentationml.presentation",
                  "Executive summary — 6-slide presentation deck"),
}


@app.get("/downloads")
def downloads() -> dict[str, Any]:
    """List every downloadable deliverable (docs + pitch kit) with its URL."""
    return {
        "docs": {
            "SKILL.md": "/skill.md?download=1",
            "README.md": "/readme.md?download=1",
            "OpenAPI": "/openapi.json",
        },
        "pitch_kit": {
            slug: {"file": fname, "label": label, "url": f"/download/{slug}"}
            for slug, (fname, _mt, label) in PITCH_FILES.items()
        },
    }


@app.get("/download/{slug}")
def download_file(slug: str) -> Response:
    """Download a pitch-kit artifact (brief-pdf, summary-pdf, summary-docx, deck-pptx)."""
    if slug not in PITCH_FILES:
        raise HTTPException(404, f"unknown download {slug!r}; see GET /downloads")
    fname, media_type, _label = PITCH_FILES[slug]
    path = _HERE / "assets" / fname
    if not path.exists():
        raise HTTPException(404, f"{fname} not found on this deployment")
    return Response(
        path.read_bytes(),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{fname}"'},
    )


@app.get("/skill.md")
def skill_md(download: bool = False) -> Response:
    """The agent-facing SKILL.md — inline view; ``?download=1`` to save it."""
    return _md_response("SKILL.md", download)


@app.get("/readme.md")
def readme_md(download: bool = False) -> Response:
    """The service README — inline view; ``?download=1`` to save it."""
    return _md_response("README.md", download)


_DOCS: dict[str, tuple[str, str]] = {
    "skill": ("SKILL.md", "SKILL.md — the agent contract"),
    "readme": ("README.md", "README — run & deploy"),
}


@app.get("/view/{doc}")
def view_doc(doc: str) -> HTMLResponse:
    """Human-readable rendered markdown viewer for the shipped docs.

    ``/view/skill`` and ``/view/readme`` render the same bytes agents fetch from
    ``/skill.md`` / ``/readme.md`` as styled HTML (client-side renderer) — the
    dual-use principle applied to the docs themselves.
    """
    if doc not in _DOCS:
        raise HTTPException(404, f"unknown doc {doc!r}; try /view/skill or /view/readme")
    filename, title = _DOCS[doc]
    raw = "/" + filename.lower()
    return HTMLResponse(
        _VIEWER_HTML.replace("{{TITLE}}", title)
        .replace("{{RAW}}", raw)
        .replace("{{FNAME}}", filename)
    )


_VIEWER_HTML = """<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{TITLE}} · Tvist API</title>
<style>
:root{--bg:#0b1020;--bg2:#101736;--card:#151d3f;--line:#26305e;--teal:#2dd4bf;
--txt:#e6eaf6;--mut:#93a0c4;--mono:ui-monospace,SFMono-Regular,Menlo,monospace}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);
font:16px/1.7 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
a{color:var(--teal);text-decoration:none} a:hover{text-decoration:underline}
.bar{position:sticky;top:0;background:rgba(11,16,32,.9);backdrop-filter:blur(8px);
border-bottom:1px solid var(--line);padding:12px 22px;display:flex;gap:14px;
align-items:center;flex-wrap:wrap}
.bar b{font-size:15px}
.btn{background:var(--card);border:1px solid var(--line);color:var(--txt);
padding:6px 13px;border-radius:8px;font-size:13px;font-weight:600}
.btn:hover{border-color:var(--teal);text-decoration:none}
.btn.solid{background:var(--teal);color:#04241f;border-color:var(--teal)}
main{max-width:860px;margin:0 auto;padding:34px 22px 80px}
h1{font-size:30px;margin:26px 0 10px} h2{font-size:23px;margin:30px 0 8px;
border-bottom:1px solid var(--line);padding-bottom:6px}
h3{font-size:18px;margin:22px 0 6px} p{margin:10px 0;color:#c6cfe8}
pre{background:#0a0f22;border:1px solid var(--line);border-radius:10px;
padding:14px;font:12.5px/1.6 var(--mono);overflow-x:auto;margin:12px 0;color:#c7d2ee}
code{font-family:var(--mono);font-size:13px;background:var(--bg2);
border:1px solid var(--line);padding:1px 6px;border-radius:6px}
pre code{border:none;background:none;padding:0}
blockquote{border-left:3px solid var(--teal);background:var(--bg2);
padding:10px 16px;border-radius:0 10px 10px 0;margin:12px 0;color:var(--mut)}
table{width:100%;border-collapse:collapse;margin:14px 0;font-size:14px}
th,td{text-align:left;padding:8px 10px;border-bottom:1px solid var(--line)}
th{color:var(--mut);font-size:12px;text-transform:uppercase;letter-spacing:.06em}
ul,ol{margin:10px 0 10px 24px;color:#c6cfe8} li{margin:4px 0}
hr{border:none;border-top:1px solid var(--line);margin:22px 0}
</style></head><body>
<div class="bar">
  <a href="/">&larr; tvist<b style="color:var(--teal)">.ai</b></a>
  <b>{{TITLE}}</b>
  <span style="flex:1"></span>
  <a class="btn" href="{{RAW}}">View raw</a>
  <a class="btn solid" href="{{RAW}}?download=1">&#10515; Download {{FNAME}}</a>
</div>
<main id="doc"><p style="color:var(--mut)">loading {{RAW}}&hellip;</p></main>
<script>
const esc=s=>s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
function inline(s){
  s=esc(s);
  s=s.replace(/`([^`]+)`/g,'<code>$1</code>');
  s=s.replace(/\\*\\*([^*]+)\\*\\*/g,'<b>$1</b>');
  s=s.replace(/\\[([^\\]]+)\\]\\(([^)]+)\\)/g,'<a href="$2">$1</a>');
  return s;
}
function render(md){
  const L=md.split('\\n');const out=[];let i=0;
  const para=/^(#{1,4} |```|\\||>|[-*] |\\d+\\. |---+$)/;
  while(i<L.length){
    const l=L[i];
    if(l.startsWith('```')){const c=[];i++;
      while(i<L.length&&!L[i].startsWith('```')){c.push(L[i]);i++}
      i++;out.push('<pre>'+esc(c.join('\\n'))+'</pre>');continue}
    const h=l.match(/^(#{1,4}) (.*)/);
    if(h){out.push('<h'+h[1].length+'>'+inline(h[2])+'</h'+h[1].length+'>');i++;continue}
    if(/^[-*] /.test(l)){const it=[];
      while(i<L.length&&/^[-*] /.test(L[i])){it.push('<li>'+inline(L[i].slice(2))+'</li>');i++}
      out.push('<ul>'+it.join('')+'</ul>');continue}
    if(/^\\d+\\. /.test(l)){const it=[];
      while(i<L.length&&/^\\d+\\. /.test(L[i])){it.push('<li>'+inline(L[i].replace(/^\\d+\\. /,''))+'</li>');i++}
      out.push('<ol>'+it.join('')+'</ol>');continue}
    if(l.startsWith('>')){const q=[];
      while(i<L.length&&L[i].startsWith('>')){q.push(inline(L[i].replace(/^>\\s?/,'')));i++}
      out.push('<blockquote>'+q.join('<br>')+'</blockquote>');continue}
    if(l.startsWith('|')){const rows=[];
      while(i<L.length&&L[i].startsWith('|')){rows.push(L[i]);i++}
      const cells=r=>r.split('|').slice(1,-1).map(c=>c.trim());
      let t='<table>';rows.forEach((r,ri)=>{
        if(ri===1&&/^\\|[\\s:|-]+\\|?$/.test(r))return;
        const tag=ri===0?'th':'td';
        t+='<tr>'+cells(r).map(c=>'<'+tag+'>'+inline(c)+'</'+tag+'>').join('')+'</tr>'});
      out.push(t+'</table>');continue}
    if(/^---+$/.test(l.trim())){out.push('<hr>');i++;continue}
    if(!l.trim()){i++;continue}
    const p=[l];i++;
    while(i<L.length&&L[i].trim()&&!para.test(L[i])){p.push(L[i]);i++}
    out.push('<p>'+inline(p.join(' '))+'</p>');
  }
  return out.join('\\n');
}
fetch('{{RAW}}').then(r=>r.text()).then(md=>{
  document.getElementById('doc').innerHTML=render(md);
}).catch(e=>{document.getElementById('doc').textContent='failed to load: '+e});
</script></body></html>"""


def _index() -> dict[str, Any]:
    """Self-describing index: what this is and every endpoint an agent can call."""
    return {
        "service": "Tvist API",
        "what": "Escrow, consent, and dispute layer for AI agents. Notional credits (sandbox).",
        "skill": "See SKILL.md. OpenAPI at /openapi.json, interactive docs at /docs.",
        "disclaimer": DISCLAIMER,
        "scenarios": SCENARIOS,
        "endpoints": {
            "GET /health": "liveness",
            "GET /stats": "live service metrics (accounts, settlements, escrows, funds)",
            "GET /disclaimer": "technical-demo / not-legal-advice disclaimer",
            "GET /spectrum": "the four trust relationships + one-gate logic (ascii/mermaid/structured)",
            "GET /downloads": "every downloadable deliverable (docs + pitch kit)",
            "GET /download/{slug}": "pitch kit: brief-pdf | summary-pdf | summary-docx | deck-pptx",
            "GET /skill.md": "agent-facing SKILL.md (inline; ?download=1 for attachment)",
            "GET /readme.md": "service README (inline; ?download=1 for attachment)",
            "GET /view/skill": "SKILL.md rendered as HTML for humans",
            "GET /view/readme": "README rendered as HTML for humans",
            "GET /regions": "list all jurisdictions and their dispute regimes",
            "GET /regions/suggest": "suggested starting jurisdiction from ?tz= and Accept-Language (IP echoed, not geolocated)",
            "POST /regions/recommend": "Nash-optimal region for two parties {client_prefs, agent_prefs}",
            "GET /taxonomy": "civil/commercial-law dispute taxonomy + reason-code linkage",
            "GET /regions/{region}/legal": "a jurisdiction's legal system, regulator, official instruments",
            "POST /consent": "store a spend mandate {consent_id, principal, budget, merchant_allowlist?}",
            "POST /pay": "settle within consent {ref, from_account, to_account, amount, region, consent_id?}",
            "POST /escrow": "open+fund escrow {escrow_id, payer, payee, amount, region, condition_expected}",
            "POST /escrow/{id}/deliver": "mark delivered {proof}",
            "POST /escrow/{id}/release": "release iff delivered",
            "POST /escrow/{id}/contest": "contest a funded escrow",
            "POST /escrow/{id}/refund": "refund a contested escrow to payer",
            "POST /recall": "recall a settled payment {ref, consent_id, current_tick?}",
            "POST /dispute": "file a dispute {ref, region, reason_code}",
            "POST /m2m/delegate": "agent->sub-agent mandate, attenuation enforced {delegation_id, parent_consent_id, agent, budget}",
            "POST /m2m/handshake": "one-call agent-to-agent pact: Nash region + mandate check + auto-escrow",
            "GET /m2m/pact/{id}": "pact + live escrow status",
            "GET /m2m/delegation/{id}": "delegation chain to the root mandate",
            "GET /x402/resource/{name}": "x402 paid resource: 402 challenge, pay via X-PAYMENT header",
            "POST /x402/verify": "facilitator verify {resource, payment_header}",
            "POST /x402/settle": "facilitator settle {resource, payment_header}",
            "GET /accounts/{name}": "balance of a notional account",
            "GET /escrow/{id}": "escrow status",
        },
    }


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness check."""
    return {"status": "ok"}


@app.get("/stats")
def stats() -> dict[str, Any]:
    """Live service metrics — powers the homepage and lets agents observe state.

    ``total_funds`` (balances + escrow holds) is the conservation invariant: it
    only grows when a new account is auto-created, never from payments moving.
    """
    from fastapi.routing import APIRoute

    held = sum(e.amount for e in LEDGER.escrows.values() if e.status in ("FUNDED", "CONTESTED"))
    by_status: dict[str, int] = {}
    for e in LEDGER.escrows.values():
        by_status[e.status] = by_status.get(e.status, 0) + 1
    return {
        "accounts": len(LEDGER.balances),
        "consents": len(LEDGER.consents),
        "settlements": len(LEDGER.settlements),
        "x402_settlements": sum(
            1 for s in LEDGER.settlements.values() if s.region == "stablecoin_x402"
        ),
        "recalled": sum(1 for s in LEDGER.settlements.values() if s.reversed),
        "escrows": {"total": len(LEDGER.escrows), **by_status},
        "held_credits": held,
        "disputes": len(LEDGER.cases),
        "delegations": len(LEDGER.delegations),
        "pacts": len(LEDGER.pacts),
        "total_funds": sum(LEDGER.balances.values()) + held,
        "regions": len(REGIONS),
        "endpoints": len([r for r in app.routes if isinstance(r, APIRoute)]),
    }


@app.get("/regions")
def list_regions() -> dict[str, Any]:
    """List every jurisdiction and its operative dispute regime."""
    return {
        "count": len(REGIONS),
        "regions": {
            key: {
                "label": r.label,
                "rail": r.rail,
                "irrevocable": r.irrevocable,
                "recall_allowed": r.recall_allowed,
                "recall_window_ticks": r.recall_window_ticks,
                "reason_codes": sorted(r.reason_codes),
                "requires_delivery_for_escrow": r.requires_delivery_for_escrow,
            }
            for key, r in REGIONS.items()
        },
    }


# Deterministic signal -> region maps for GET /regions/suggest. Exact IANA
# timezone first, then timezone prefix, then the Accept-Language region subtag.
_TZ_REGION: dict[str, str] = {
    "Europe/Stockholm": "nordic", "Europe/Oslo": "nordic", "Europe/Copenhagen": "nordic",
    "Europe/Helsinki": "nordic", "Europe/Reykjavik": "nordic",
    "Europe/London": "uk_fps", "Europe/Zurich": "ch_twint",
    "America/Sao_Paulo": "br_pix", "America/Manaus": "br_pix", "America/Recife": "br_pix",
    "America/Fortaleza": "br_pix", "America/Belem": "br_pix", "America/Bahia": "br_pix",
    "America/Mexico_City": "mx_spei", "America/Monterrey": "mx_spei", "America/Tijuana": "mx_spei",
    "America/Toronto": "ca_interac", "America/Vancouver": "ca_interac",
    "America/Edmonton": "ca_interac", "America/Winnipeg": "ca_interac",
    "America/Halifax": "ca_interac", "America/St_Johns": "ca_interac",
    "Asia/Kolkata": "in_upi", "Asia/Singapore": "sg_fast", "Asia/Tokyo": "jp_zengin",
    "Asia/Hong_Kong": "hk_fps", "Asia/Dubai": "ae_aani", "Asia/Riyadh": "sa_sarie",
    "Asia/Shanghai": "cn_ibps", "Asia/Urumqi": "cn_ibps",
    "Africa/Johannesburg": "za_payshap", "Africa/Lagos": "ng_nip", "Africa/Nairobi": "ke_mpesa",
}
_TZ_PREFIX_REGION: list[tuple[str, str]] = [
    ("Europe/", "eu_sepa"), ("America/", "us_fednow"), ("Australia/", "au_npp"),
]
_CC_REGION: dict[str, str] = {
    "SE": "nordic", "NO": "nordic", "DK": "nordic", "FI": "nordic", "IS": "nordic",
    "GB": "uk_fps", "CH": "ch_twint", "BR": "br_pix", "MX": "mx_spei",
    "US": "us_fednow", "CA": "ca_interac", "IN": "in_upi", "SG": "sg_fast",
    "AU": "au_npp", "JP": "jp_zengin", "HK": "hk_fps", "AE": "ae_aani",
    "SA": "sa_sarie", "ZA": "za_payshap", "NG": "ng_nip", "KE": "ke_mpesa",
    "CN": "cn_ibps",
    "DE": "eu_sepa", "FR": "eu_sepa", "ES": "eu_sepa", "IT": "eu_sepa", "NL": "eu_sepa",
    "BE": "eu_sepa", "AT": "eu_sepa", "PT": "eu_sepa", "IE": "eu_sepa", "PL": "eu_sepa",
    "GR": "eu_sepa", "CZ": "eu_sepa", "SK": "eu_sepa", "SI": "eu_sepa", "HR": "eu_sepa",
    "RO": "eu_sepa", "BG": "eu_sepa", "HU": "eu_sepa", "LT": "eu_sepa", "LV": "eu_sepa",
    "EE": "eu_sepa", "LU": "eu_sepa", "MT": "eu_sepa", "CY": "eu_sepa",
}


@app.get("/regions/suggest")
def suggest_region(request: Request, tz: str = "") -> dict[str, Any]:
    """Suggest a starting jurisdiction for this caller.

    Deterministic and self-contained. Signals, in order of precedence:
    the caller's IANA timezone (``?tz=`` query parameter — browsers know it via
    ``Intl.DateTimeFormat().resolvedOptions().timeZone``), then the region
    subtag of the ``Accept-Language`` header. The caller's IP is echoed for
    transparency but is NOT geolocated: this sandbox calls no external
    geolocation service. If no signal maps, the suggestion is ``global``.
    The suggestion is an option, not a decision — parties still negotiate via
    ``POST /regions/recommend``.
    """
    fwd = request.headers.get("x-forwarded-for", "")
    client_ip = fwd.split(",")[0].strip() if fwd else (
        request.client.host if request.client else "")
    accept_language = request.headers.get("accept-language", "")
    region: str | None = None
    method = "default"
    if tz:
        region = _TZ_REGION.get(tz)
        if region is None:
            region = next((r for p, r in _TZ_PREFIX_REGION if tz.startswith(p)), None)
        if region is not None:
            method = f"timezone {tz!r}"
    if region is None and accept_language:
        first = accept_language.split(",")[0].strip()
        parts = first.split(";")[0].split("-")
        cc = parts[1].upper() if len(parts) > 1 else ""
        region = _CC_REGION.get(cc)
        if region is not None:
            method = f"Accept-Language region {cc!r}"
    if region is None:
        region = "global"
    return {
        "suggested_region": region,
        "label": REGIONS[region].label,
        "method": method,
        "client_ip": client_ip,
        "signals": {"timezone": tz or None, "accept_language": accept_language or None},
        "note": ("client_ip is echoed for transparency only — no external "
                 "geolocation service is called; the suggestion derives from "
                 "the timezone and Accept-Language signals above"),
        "next_step": "POST /regions/recommend with both parties' ranked preferences",
    }


class RecommendIn(BaseModel):
    client_prefs: list[str] = Field(..., examples=[["eu_sepa", "br_pix", "in_upi"]])
    agent_prefs: list[str] = Field(..., examples=[["in_upi", "br_pix", "eu_sepa"]])


@app.post("/regions/recommend")
def recommend(body: RecommendIn) -> dict[str, Any]:
    """Recommend the game-theoretically optimal region for both parties (Nash bargaining)."""
    agreed = recommend_region(body.client_prefs, body.agent_prefs)
    naive = next((r for r in body.client_prefs if r in set(body.agent_prefs)), None)
    return {
        "agreed_region": agreed,
        "method": "nash_bargaining",
        "naive_client_first": naive,
        "regime": None if agreed is None else {
            "label": REGIONS[agreed].label,
            "irrevocable": REGIONS[agreed].irrevocable,
            "recall_allowed": REGIONS[agreed].recall_allowed,
            "recall_window_ticks": REGIONS[agreed].recall_window_ticks,
        },
        "note": "None means the parties share no acceptable region — do not transact.",
    }


@app.get("/taxonomy")
def taxonomy() -> dict[str, Any]:
    """Full dispute taxonomy grounded in civil & commercial law.

    Returns the legal categories (with civil-law and common-law doctrinal
    bases), the reason-code → category mapping, and per-region linkage: which
    codes each jurisdiction accepts and under which legal category.
    """
    return {
        "categories": LEGAL_CATEGORIES,
        "reason_codes": {
            code: {
                "category": cat,
                "label": LEGAL_CATEGORIES[cat]["label"],
            }
            for code, cat in REASON_LEGAL.items()
        },
        "regions": {
            key: {
                "legal_system": LEGAL_SOURCES[key]["legal_system"],
                "reason_codes": {
                    code: REASON_LEGAL[code] for code in sorted(r.reason_codes)
                },
            }
            for key, r in REGIONS.items()
        },
        "note": "Category bases cite representative instruments; per-region "
                "operative sources are at GET /regions/{region}/legal.",
        "disclaimer": DISCLAIMER,
    }


@app.get("/regions/{region}/legal")
def region_legal(region: str) -> dict[str, Any]:
    """A jurisdiction's dispute law: system, regulator, official instruments,
    and each accepted reason code linked to its civil/commercial-law basis."""
    if region not in REGIONS or region not in LEGAL_SOURCES:
        raise HTTPException(404, f"unknown region {region!r}; see GET /regions")
    r = REGIONS[region]
    src = LEGAL_SOURCES[region]
    system = str(src["legal_system"])
    civilish = "civil" in system or "Sharia" in system or "transnational" in system
    linkage = []
    for code in sorted(r.reason_codes):
        cat = REASON_LEGAL[code]
        c = LEGAL_CATEGORIES[cat]
        linkage.append({
            "reason_code": code,
            "category": cat,
            "label": c["label"],
            "operative_basis": c["civil_law_basis"] if civilish else c["common_law_basis"],
            "other_tradition_basis": c["common_law_basis"] if civilish else c["civil_law_basis"],
        })
    return {
        "region": region,
        "label": r.label,
        "rail": r.rail,
        "legal_system": src["legal_system"],
        "regulator": src["regulator"],
        "instruments": src["instruments"],
        "recall_allowed": r.recall_allowed,
        "recall_window_ticks": r.recall_window_ticks,
        "reason_code_linkage": linkage,
        "disclaimer": DISCLAIMER,
    }


class ConsentIn(BaseModel):
    consent_id: str
    principal: str
    budget: int
    merchant_allowlist: list[str] | None = None


@app.post("/consent")
def store_consent(body: ConsentIn) -> dict[str, Any]:
    """Store an explicit spend mandate the principal authorised for an agent."""
    LEDGER.consents[body.consent_id] = Consent(
        body.consent_id, body.principal, body.budget, body.merchant_allowlist
    )
    return {"consent_id": body.consent_id, "stored": True, "budget": body.budget}


class PayIn(BaseModel):
    ref: str
    from_account: str
    to_account: str
    amount: int
    region: str = "global"
    consent_id: str | None = None


@app.post("/pay")
def pay(body: PayIn) -> dict[str, Any]:
    """Settle a payment; enforce consent (if given) and record region irrevocability."""
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    if body.ref in body_settled():
        raise HTTPException(409, f"duplicate ref {body.ref}")
    if body.consent_id is not None:
        consent = LEDGER.consents.get(body.consent_id)
        if consent is None:
            raise HTTPException(404, f"unknown consent_id {body.consent_id}")
        if not consent_covers(consent, body.amount, body.to_account):
            raise HTTPException(
                403, f"payment {body.amount} to {body.to_account} exceeds consent {body.consent_id}"
            )
    LEDGER.debit(body.from_account, body.amount)
    LEDGER.credit(body.to_account, body.amount)
    irrevocable = regime(body.region).irrevocable
    LEDGER.settlements[body.ref] = Settlement(
        body.ref, body.from_account, body.to_account, body.amount, body.region, irrevocable
    )
    return {
        "ref": body.ref,
        "settled": True,
        "irrevocable": irrevocable,
        "region": body.region,
        "payer_balance": LEDGER.balance(body.from_account),
        "payee_balance": LEDGER.balance(body.to_account),
    }


def body_settled() -> set[str]:
    return set(LEDGER.settlements)


class EscrowIn(BaseModel):
    escrow_id: str
    payer: str
    payee: str
    amount: int
    region: str = "global"
    condition_expected: str = "delivered"


@app.post("/escrow")
def open_escrow(body: EscrowIn) -> dict[str, Any]:
    """Open and fund an escrow: funds leave the payer and are held until delivery."""
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    if body.escrow_id in LEDGER.escrows:
        raise HTTPException(409, f"duplicate escrow_id {body.escrow_id}")
    LEDGER.debit(body.payer, body.amount)
    LEDGER.escrows[body.escrow_id] = Escrow(
        body.escrow_id, body.payer, body.payee, body.amount, body.region, body.condition_expected
    )
    return {"escrow_id": body.escrow_id, "status": "FUNDED", "held": body.amount}


def _get_escrow(escrow_id: str) -> Escrow:
    esc = LEDGER.escrows.get(escrow_id)
    if esc is None:
        raise HTTPException(404, f"unknown escrow {escrow_id}")
    return esc


class DeliverIn(BaseModel):
    proof: str


@app.post("/escrow/{escrow_id}/deliver")
def deliver(escrow_id: str, body: DeliverIn) -> dict[str, Any]:
    """Mark the escrow delivered iff the proof matches the expected condition."""
    esc = _get_escrow(escrow_id)
    if body.proof == esc.condition_expected:
        esc.delivered = True
    return {"escrow_id": escrow_id, "delivered": esc.delivered}


@app.post("/escrow/{escrow_id}/release")
def release(escrow_id: str) -> dict[str, Any]:
    """Release held funds to the payee — only if delivered and not contested."""
    esc = _get_escrow(escrow_id)
    if esc.status == "CONTESTED":
        raise HTTPException(409, "escrow is contested")
    if esc.status != "FUNDED":
        raise HTTPException(409, f"escrow not releasable in status {esc.status}")
    if not esc.delivered:
        raise HTTPException(403, "release condition not satisfied (not delivered)")
    LEDGER.credit(esc.payee, esc.amount)
    esc.status = "RELEASED"
    return {"escrow_id": escrow_id, "status": "RELEASED", "payee_balance": LEDGER.balance(esc.payee)}


@app.post("/escrow/{escrow_id}/contest")
def contest(escrow_id: str) -> dict[str, Any]:
    """Contest a funded escrow, blocking release pending mediation."""
    esc = _get_escrow(escrow_id)
    if esc.status != "FUNDED":
        raise HTTPException(409, f"only a funded escrow can be contested (status {esc.status})")
    esc.status = "CONTESTED"
    return {"escrow_id": escrow_id, "status": "CONTESTED"}


@app.post("/escrow/{escrow_id}/refund")
def refund_escrow(escrow_id: str) -> dict[str, Any]:
    """Refund a contested escrow's held funds to the payer (mediation outcome)."""
    esc = _get_escrow(escrow_id)
    if esc.status != "CONTESTED":
        raise HTTPException(409, f"only a contested escrow can be refunded (status {esc.status})")
    LEDGER.credit(esc.payer, esc.amount)
    esc.status = "REFUNDED"
    return {"escrow_id": escrow_id, "status": "REFUNDED", "payer_balance": LEDGER.balance(esc.payer)}


@app.get("/escrow/{escrow_id}")
def get_escrow(escrow_id: str) -> dict[str, Any]:
    """Return an escrow's current status."""
    esc = _get_escrow(escrow_id)
    return {
        "escrow_id": esc.escrow_id, "payer": esc.payer, "payee": esc.payee,
        "amount": esc.amount, "region": esc.region, "delivered": esc.delivered,
        "status": esc.status,
    }


class RecallIn(BaseModel):
    ref: str
    consent_id: str
    current_tick: float = 0.0


@app.post("/recall")
def recall(body: RecallIn) -> dict[str, Any]:
    """Recall a settled payment — only if the region allows it, in window, and the mandate was breached."""
    s = LEDGER.settlements.get(body.ref)
    if s is None:
        raise HTTPException(404, f"unknown settlement {body.ref}")
    reg = regime(s.region)
    if s.reversed:
        return {"ref": body.ref, "reversed": False, "reason": "already reversed"}
    if not reg.recall_allowed:
        return {"ref": body.ref, "reversed": False, "reason": f"region {s.region} disallows recall"}
    consent = LEDGER.consents.get(body.consent_id)
    if consent is None:
        raise HTTPException(404, f"unknown consent_id {body.consent_id}")
    # Recall is only justified when the settled payment was OUTSIDE the mandate.
    if consent_covers(consent, s.amount, s.payee):
        return {"ref": body.ref, "reversed": False, "reason": "no mandate breach — clawback refused"}
    LEDGER.debit(s.payee, s.amount)
    LEDGER.credit(s.payer, s.amount)
    s.reversed = True
    return {"ref": body.ref, "reversed": True, "reason": "mandate breach recalled",
            "payer_balance": LEDGER.balance(s.payer)}


class DisputeIn(BaseModel):
    ref: str
    region: str
    reason_code: str


@app.post("/dispute")
def dispute(body: DisputeIn) -> dict[str, Any]:
    """File a dispute; accepted only if the reason code is valid in the region's taxonomy.

    An accepted case returns ``legal_basis`` inline — the civil/commercial-law
    category and the citation string (chosen by the region's legal tradition)
    that the agent can quote when pursuing the claim.
    """
    reg = regime(body.region)
    accepted = body.reason_code in reg.reason_codes
    basis = legal_basis_for(body.region, body.reason_code) if accepted else None
    if accepted:
        LEDGER.cases[body.ref] = {
            "region": body.region,
            "reason_code": body.reason_code,
            "legal_basis": basis,
        }
    return {
        "ref": body.ref,
        "accepted": accepted,
        "reason_code": body.reason_code,
        "region": body.region,
        "legal_basis": basis,
        "valid_reason_codes": sorted(reg.reason_codes),
        "disclaimer": DISCLAIMER,
    }


@app.get("/disclaimer")
def disclaimer() -> dict[str, str]:
    """The service-wide legal disclaimer: technical demo, not legal advice."""
    return {"disclaimer": DISCLAIMER}


# ---------------------------------------------------------------------------
# M2M — machine-to-machine agentic commerce on the same Tvist gates
# ---------------------------------------------------------------------------
# Two primitives make pure agent↔agent trade safe with zero humans in the loop:
#
# * Attenuated delegation chains: an agent acts as principal for sub-agents.
#   Each delegation registers a consent, so EVERY existing gate (/pay, x402,
#   handshake) enforces it unchanged — same Tvist logic, machine principals.
#   Attenuation is hard: a child budget can never exceed its parent's, and an
#   allowlist can only narrow.
# * One-call handshake: two agents form a trade pact — Nash-optimal region,
#   mandate check, and (by default) an atomically funded escrow — then finish
#   the trade with the ordinary /escrow/{id}/deliver + /release endpoints.


class DelegateIn(BaseModel):
    delegation_id: str
    parent_consent_id: str
    agent: str
    budget: int
    merchant_allowlist: list[str] | None = None


def _delegation_chain(delegation_id: str) -> list[str]:
    """Walk a delegation chain up to its root consent (leaf first)."""
    chain: list[str] = []
    cur: str | None = delegation_id
    while cur is not None and len(chain) < 32:
        chain.append(cur)
        d = LEDGER.delegations.get(cur)
        cur = d.parent_id if d else None
    return chain


@app.post("/m2m/delegate")
def m2m_delegate(body: DelegateIn) -> dict[str, Any]:
    """Delegate spending authority from one agent (or consent) to a sub-agent.

    The parent may be a root consent (human or machine principal) or another
    delegation — chains compose. Attenuation is enforced: the child budget must
    not exceed the parent's, and any allowlist may only narrow. The delegation
    itself registers as a consent, so all existing gates enforce it unchanged.
    """
    parent = LEDGER.consents.get(body.parent_consent_id)
    if parent is None:
        raise HTTPException(404, f"unknown parent consent {body.parent_consent_id!r}")
    if body.delegation_id in LEDGER.consents or body.delegation_id in LEDGER.delegations:
        raise HTTPException(409, f"duplicate delegation_id {body.delegation_id!r}")
    if body.budget > parent.budget:
        raise HTTPException(
            403,
            f"attenuation violated: child budget {body.budget} exceeds "
            f"parent budget {parent.budget}",
        )
    if parent.merchant_allowlist is not None:
        child_list = body.merchant_allowlist
        if child_list is None or not set(child_list) <= set(parent.merchant_allowlist):
            raise HTTPException(
                403, "attenuation violated: allowlist may only narrow the parent's"
            )
    parent_delegation = LEDGER.delegations.get(body.parent_consent_id)
    depth = (parent_delegation.depth + 1) if parent_delegation else 1
    LEDGER.delegations[body.delegation_id] = Delegation(
        body.delegation_id, body.parent_consent_id, parent.principal,
        body.agent, body.budget, depth,
    )
    LEDGER.consents[body.delegation_id] = Consent(
        body.delegation_id, body.agent, body.budget, body.merchant_allowlist
    )
    return {
        "delegation_id": body.delegation_id,
        "agent": body.agent,
        "budget": body.budget,
        "depth": depth,
        "chain": _delegation_chain(body.delegation_id),
        "note": "use this id as consent_id on /pay, x402 extra.consent_id, or "
                "/m2m/handshake — the same gates enforce it",
    }


@app.get("/m2m/delegation/{delegation_id}")
def m2m_delegation(delegation_id: str) -> dict[str, Any]:
    """A delegation's details and its full chain up to the root mandate."""
    d = LEDGER.delegations.get(delegation_id)
    if d is None:
        raise HTTPException(404, f"unknown delegation {delegation_id!r}")
    return {
        "delegation_id": d.delegation_id, "delegator": d.delegator,
        "agent": d.agent, "budget": d.budget, "depth": d.depth,
        "chain": _delegation_chain(delegation_id),
    }


class HandshakeIn(BaseModel):
    pact_id: str
    buyer_agent: str
    seller_agent: str
    buyer_prefs: list[str] = Field(..., examples=[["eu_sepa", "br_pix"]])
    seller_prefs: list[str] = Field(..., examples=[["br_pix", "in_upi"]])
    amount: int
    delegation_id: str | None = None
    auto_escrow: bool = True
    condition_expected: str = "delivered"


@app.post("/m2m/handshake")
def m2m_handshake(body: HandshakeIn) -> dict[str, Any]:
    """One-call agent↔agent trade pact — no human in the loop.

    Negotiates the Nash-optimal region from both agents' preferences (no shared
    region → 409, do not transact), enforces the buyer agent's delegated mandate
    if supplied, and by default opens + funds an escrow atomically so the seller
    agent ships against locked funds. Finish with the ordinary
    ``/escrow/pact-{pact_id}/deliver`` and ``/release`` calls.
    """
    if body.pact_id in LEDGER.pacts:
        raise HTTPException(409, f"duplicate pact_id {body.pact_id!r}")
    if body.amount <= 0:
        raise HTTPException(400, "amount must be positive")
    agreed = recommend_region(body.buyer_prefs, body.seller_prefs)
    if agreed is None:
        raise HTTPException(
            409, "no shared region between the agents — do not transact"
        )
    if body.delegation_id is not None:
        consent = LEDGER.consents.get(body.delegation_id)
        if consent is None:
            raise HTTPException(404, f"unknown delegation/consent {body.delegation_id!r}")
        if not consent_covers(consent, body.amount, body.seller_agent):
            raise HTTPException(
                403,
                f"pact amount {body.amount} to {body.seller_agent!r} exceeds "
                f"mandate {body.delegation_id!r}",
            )
    reg = regime(agreed)
    escrow_id = None
    if body.auto_escrow:
        escrow_id = f"pact-{body.pact_id}"
        if escrow_id in LEDGER.escrows:
            raise HTTPException(409, f"duplicate escrow {escrow_id!r}")
        LEDGER.debit(body.buyer_agent, body.amount)
        LEDGER.escrows[escrow_id] = Escrow(
            escrow_id, body.buyer_agent, body.seller_agent, body.amount,
            agreed, body.condition_expected,
        )
    pact = {
        "pact_id": body.pact_id,
        "buyer_agent": body.buyer_agent,
        "seller_agent": body.seller_agent,
        "amount": body.amount,
        "agreed_region": agreed,
        "regime": {
            "label": reg.label, "irrevocable": reg.irrevocable,
            "recall_allowed": reg.recall_allowed,
            "recall_window_ticks": reg.recall_window_ticks,
        },
        "delegation_id": body.delegation_id,
        "escrow_id": escrow_id,
        "status": "ESCROWED" if escrow_id else "AGREED",
        "next_steps": (
            [f"POST /escrow/{escrow_id}/deliver {{proof}}",
             f"POST /escrow/{escrow_id}/release"]
            if escrow_id else
            ["POST /pay (or /escrow) under the agreed region"]
        ),
    }
    LEDGER.pacts[body.pact_id] = pact
    return pact


@app.get("/m2m/pact/{pact_id}")
def m2m_pact(pact_id: str) -> dict[str, Any]:
    """A pact's state, with the live escrow status when one was opened."""
    pact = LEDGER.pacts.get(pact_id)
    if pact is None:
        raise HTTPException(404, f"unknown pact {pact_id!r}")
    out = dict(pact)
    if pact.get("escrow_id"):
        esc = LEDGER.escrows.get(str(pact["escrow_id"]))
        if esc:
            out["escrow_status"] = {"delivered": esc.delivered, "status": esc.status}
    return out


# ---------------------------------------------------------------------------
# x402 — HTTP-native on-rail agent payments (sandbox simulation)
# ---------------------------------------------------------------------------
# Implements the x402 flow (https://github.com/coinbase/x402): a paid resource
# answers HTTP 402 with structured payment requirements; the agent retries with
# a base64 X-PAYMENT header carrying an EIP-3009-shaped authorization; the
# facilitator verifies and settles; the resource is delivered with an
# X-PAYMENT-RESPONSE header. Sandbox: notional credits stand in for USDC on a
# simulated Base network, and signatures are simulated ("sim-<nonce>").
# Additions on top of the base flow: optional consent enforcement
# (extra.consent_id), nonce replay protection, and settlements recorded under
# the irrevocable `stablecoin_x402` regime — escrow, not recall, is the
# protection here.

import base64
import hashlib

X402_VERSION = 1
X402_NETWORK = "base-sepolia-sim"
X402_ASSET = "credits (sandbox USDC stand-in)"
X402_TREASURY = "tvist-treasury"

PAID_RESOURCES: dict[str, dict[str, Any]] = {
    "market-report": {
        "price": 25,
        "description": "Tvist agentic-commerce market snapshot (paid demo resource)",
        "content": {
            "title": "Agentic commerce market snapshot",
            "highlights": [
                "1 in 6 Black Friday 2025 purchases were AI-assisted",
                "trust is the #1 adoption barrier (Juniper 2026)",
                "instant-payment fraud risk up to 10x higher (ECB)",
            ],
        },
    },
    "dispute-precedents": {
        "price": 15,
        "description": "Reason-code -> legal-basis extract from the Tvist taxonomy",
        "content": {
            "agent_exceeded_mandate": "agency/mandate — falsus procurator (BGB §177) / "
                                      "apparent authority (Restatement (Third) of Agency)",
            "mistaken_payment": "unjust enrichment — condictio indebiti (BGB §812) / "
                                "Barclays Bank v W.J. Simms",
        },
    },
}

X402_USED_NONCES: set[str] = set()


def _x402_requirements(name: str) -> dict[str, Any]:
    res = PAID_RESOURCES[name]
    return {
        "scheme": "exact",
        "network": X402_NETWORK,
        "maxAmountRequired": res["price"],
        "resource": f"/x402/resource/{name}",
        "description": res["description"],
        "mimeType": "application/json",
        "payTo": X402_TREASURY,
        "maxTimeoutSeconds": 60,
        "asset": X402_ASSET,
        "extra": {"consent_id": "optional — Tvist enforces the principal's mandate "
                                "on-rail when present"},
    }


def _x402_verify(name: str, header: str) -> tuple[dict[str, Any] | None, str | None]:
    """Verify an X-PAYMENT header against a resource's requirements.

    Returns (payment, None) when valid, else (None, invalid_reason).
    """
    if name not in PAID_RESOURCES:
        return None, f"unknown resource {name!r}"
    try:
        payment = json.loads(base64.b64decode(header))
    except Exception:
        return None, "X-PAYMENT header is not base64-encoded JSON"
    if payment.get("x402Version") != X402_VERSION:
        return None, f"unsupported x402Version (want {X402_VERSION})"
    if payment.get("scheme") != "exact":
        return None, "unsupported scheme (want 'exact')"
    if payment.get("network") != X402_NETWORK:
        return None, f"wrong network (want {X402_NETWORK})"
    auth = (payment.get("payload") or {}).get("authorization") or {}
    sig = (payment.get("payload") or {}).get("signature") or ""
    nonce = str(auth.get("nonce", ""))
    if not nonce:
        return None, "authorization.nonce required"
    if nonce in X402_USED_NONCES:
        return None, "nonce already used (replay rejected)"
    if not str(sig).startswith("sim-"):
        return None, "invalid signature (sandbox expects 'sim-<nonce>')"
    if auth.get("to") != X402_TREASURY:
        return None, f"authorization.to must be {X402_TREASURY!r}"
    price = PAID_RESOURCES[name]["price"]
    try:
        value = int(auth.get("value", 0))
    except (TypeError, ValueError):
        return None, "authorization.value must be an integer"
    if value < price:
        return None, f"underpayment: {value} < required {price}"
    payer = str(auth.get("from", ""))
    if not payer:
        return None, "authorization.from required"
    # Tvist consent gate — if the agent supplies its principal's consent_id,
    # the mandate is enforced even on this irrevocable rail.
    consent_id = (payment.get("extra") or {}).get("consent_id")
    if consent_id:
        consent = LEDGER.consents.get(str(consent_id))
        if consent is None:
            return None, f"unknown consent_id {consent_id!r}"
        if not consent_covers(consent, value, X402_TREASURY):
            return None, f"payment {value} exceeds consent {consent_id!r}"
    if LEDGER.balance(payer) < value:
        return None, f"insufficient balance: {payer}"
    return payment, None


def _x402_settle(name: str, payment: dict[str, Any]) -> dict[str, Any]:
    """Execute a verified x402 payment on the ledger (irrevocable settlement)."""
    auth = payment["payload"]["authorization"]
    payer, value, nonce = str(auth["from"]), int(auth["value"]), str(auth["nonce"])
    LEDGER.debit(payer, value)
    LEDGER.credit(X402_TREASURY, value)
    ref = f"x402-{nonce[:16]}"
    LEDGER.settlements[ref] = Settlement(
        ref, payer, X402_TREASURY, value, "stablecoin_x402", irrevocable=True
    )
    X402_USED_NONCES.add(nonce)
    tx_hash = hashlib.sha256(f"{nonce}:{payer}:{value}".encode()).hexdigest()
    return {"success": True, "txHash": f"0x{tx_hash}", "networkId": X402_NETWORK,
            "payer": payer, "amount": value, "ref": ref}


@app.get("/x402/resource/{name}")
def x402_resource(name: str, request: Request) -> JSONResponse:
    """A paid resource behind the x402 flow.

    Without an ``X-PAYMENT`` header: **402 Payment Required** with the structured
    payment requirements (``accepts``). With a valid header: verifies, settles on
    the ledger, and returns the resource with an ``X-PAYMENT-RESPONSE`` header.
    """
    if name not in PAID_RESOURCES:
        raise HTTPException(404, f"unknown paid resource {name!r}")
    header = request.headers.get("x-payment")
    if not header:
        return JSONResponse(status_code=402, content={
            "x402Version": X402_VERSION,
            "error": "X-PAYMENT header required",
            "accepts": [_x402_requirements(name)],
        })
    payment, reason = _x402_verify(name, header)
    if payment is None:
        return JSONResponse(status_code=402, content={
            "x402Version": X402_VERSION,
            "error": reason,
            "accepts": [_x402_requirements(name)],
        })
    receipt = _x402_settle(name, payment)
    resp_header = base64.b64encode(json.dumps(receipt).encode()).decode()
    return JSONResponse(
        content=PAID_RESOURCES[name]["content"],
        headers={"X-PAYMENT-RESPONSE": resp_header},
    )


class X402FacilitatorIn(BaseModel):
    resource: str
    payment_header: str


def _x402_resource_name(resource: str) -> str:
    """Accept both the bare name and the full path the 402 challenge advertises
    in its ``resource`` field (``/x402/resource/<name>``)."""
    return resource.removeprefix("/x402/resource/")


@app.post("/x402/verify")
def x402_facilitator_verify(body: X402FacilitatorIn) -> dict[str, Any]:
    """Facilitator-style verification: is this X-PAYMENT valid for the resource?"""
    payment, reason = _x402_verify(_x402_resource_name(body.resource), body.payment_header)
    payer = ""
    if payment is not None:
        payer = str(payment["payload"]["authorization"].get("from", ""))
    return {"isValid": payment is not None, "invalidReason": reason, "payer": payer}


@app.post("/x402/settle")
def x402_facilitator_settle(body: X402FacilitatorIn) -> dict[str, Any]:
    """Facilitator-style settlement: verify then execute the payment on-ledger."""
    name = _x402_resource_name(body.resource)
    payment, reason = _x402_verify(name, body.payment_header)
    if payment is None:
        raise HTTPException(402, reason or "invalid payment")
    return _x402_settle(name, payment)


@app.get("/accounts/{name}")
def account(name: str) -> dict[str, Any]:
    """Return a notional account's balance (auto-created at the start balance)."""
    return {"account": name, "balance": LEDGER.balance(name)}


@app.exception_handler(HTTPException)
def _http_exc(_: Any, exc: HTTPException) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
