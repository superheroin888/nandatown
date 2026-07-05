# Tvist legal dispute taxonomy — civil & commercial law grounding

Every Tvist reason code maps to a substantive category of civil / commercial
law, and every one of the 22 jurisdictions in the region registry carries its
**operative legal instruments** (payments statute, scheme rulebook,
consumer/civil law) with links to the official publication source. This is what
lets an agent *cite the law* when it files a dispute, and lets a human verify
every claim at the primary source.

Live endpoints (see [`tvist-service/SKILL.md`](../../tvist-service/SKILL.md)):

- `GET /taxonomy` — the 7 categories, the reason-code → category map, and the
  per-region linkage.
- `GET /regions/{region}/legal` — a jurisdiction's legal system, regulator,
  instruments (official links), and each accepted code's operative basis.
- Site: the **Legal taxonomy** section (`/#law`) renders both live, with a
  jurisdiction explorer and clickable primary sources.

## The seven categories

| Category | Reason codes | Civil-law basis (representative) | Common-law basis (representative) |
|---|---|---|---|
| Non-performance (non-delivery) | `goods_not_received` | BGB §§275, 323; Code civil arts. 1217, 1610; CISG arts. 30/45/49 | Breach of contract; total failure of consideration; UCC §2-711 |
| Non-conformity (defective performance) | `not_as_described` | Directive (EU) 2019/771; CISG art. 35; Code civil art. 1641 | Consumer Rights Act 2015 ss. 9–11 (UK); UCC §§2-314/315 |
| Fraud / unauthorized | `fraud` | Dol (Code civil art. 1137); PSD2 arts. 64, 73–74 | Tort of deceit; EFTA + Regulation E (12 CFR 1005) |
| Agency / mandate (excess of authority) | `agent_exceeded_mandate`, `verifiable_intent_mismatch` | BGB §§164–181 (falsus procurator §177); Code civil arts. 1153–1161, 1984 ff.; CO art. 394 ff. | Actual/apparent authority, ratification (Restatement (Third) of Agency); Indian Contract Act 1872 ss. 182–238 |
| Unjust enrichment (mistaken payment) | `mistaken_payment` | Condictio indebiti: BGB §812; Code civil art. 1302; CO arts. 62 ff. | Restitution for mistake (*Barclays Bank v W.J. Simms*) |
| Procedural recall (scheme remedy) | `recall_request`, `sepa_recall`, `pix_med_return` | EPC SCT Inst Rulebook; Pix MED (Resolução BCB 1/2020) | Reg J subpart C / UCC 4A; Pay.UK, TCH operating rules |
| Continuing obligations | `recurring_disputed` | BGB §314; Directive 2011/83/EU | Reg E 12 CFR 1005.10 preauthorized-transfer stops |

The **agency/mandate** category is the agentic-commerce core: "did the AI agent
act within the principal's mandate?" is, in law, a question of representation
(civil law: mandat / Auftrag / falsus procurator) or authority (common law:
actual vs apparent authority, ratification). Tvist's intent vault is the
evidentiary record for exactly that question.

## Per-jurisdiction sources (highlights)

| Region | Legal system | Operative instruments (official source) |
|---|---|---|
| `eu_sepa` | civil (EU acquis) | PSD2 (2015/2366), Instant Payments Reg. (2024/886), EPC SCT Inst Rulebook, SGD (2019/771) — eur-lex / EPC |
| `uk_fps` | common law | Payment Services Regs 2017 (SI 2017/752), PSR APP-reimbursement (SD20), CRA 2015 — legislation.gov.uk / PSR |
| `nordic` | civil (Nordic) | Betaltjänstlag 2010:751, Konsumentköplag 2022:260, Konsumentkreditlag 2010:1846 §29 — riksdagen.se |
| `br_pix` | civil | Regulamento do Pix + MED (Res. BCB 1/2020), CDC (Lei 8.078/1990), Código Civil (Lei 10.406/2002) — bcb.gov.br / planalto |
| `us_fednow` / `us_rtp` | common (UCC) | Reg J subpart C (12 CFR 210) incorporating UCC 4A; FedNow operating procedures; Reg E (12 CFR 1005); TCH RTP rules |
| `in_upi` | common law | PSS Act 2007, NPCI UPI guidelines + UDIR, Indian Contract Act 1872 (agency ss. 182–238), RB-IOS — indiacode / npci / rbi |
| `jp_zengin` | civil | Civil Code (mandate 643 ff., enrichment 703), Payment Services Act 2009, Zengin-Net rules |
| `ch_twint` | civil | Swiss CO (SR 220): mandate 394 ff., enrichment 62 ff. — fedlex |
| `au_npp` | common law | ePayments Code (ASIC), NPP Regulations, Australian Consumer Law |
| `sg_fast` | common law | Payment Services Act 2019, MAS E-Payments User Protection Guidelines |
| `ae_aani` / `sa_sarie` | civil + Sharia | UAE Civil Transactions Law (wakala), CBUAE RPSCS Reg.; Saudi Civil Transactions Law 2023, SAMA PSP Regs |
| `stablecoin_x402` | private ordering | UCC Art. 12 (2022), MiCA (EU 2023/1114) for issuers, x402 spec as incorporated terms |

(Full list — all 22, with every instrument, citation, role, and official URL —
lives in the service registry and is served by the endpoints above.)

## How the linkage flows through the solution

1. **Region negotiation** fixes the governing regime → fixes which reason codes
   are available *and which law backs each one*.
2. **Dispute filing** validates the code against the regime's taxonomy; the
   response can carry the `operative_basis` for the citation.
3. **Recall** is the procedural-recall category operationalized: allowed only
   where the scheme rulebook provides it (MED, SCT Inst recall, UPI UDIR) and
   the mandate-breach evidence satisfies the agency/mandate category.
4. **The site** (`/#law`) and **SKILL.md** expose the same registry to humans
   and agents respectively — the dual-use principle applied to the law itself.

> Scope note: this registry is engineering-grade legal mapping for a sandbox —
> citations point to real primary sources, but it is not legal advice, and
> production deployment per jurisdiction requires local counsel review.
