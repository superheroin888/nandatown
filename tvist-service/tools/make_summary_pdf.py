# Generates assets/Tvist-Executive-Summary.pdf — two pages, current verified facts.
# Run: .venv-svc/bin/python tools/make_summary_pdf.py  (from tvist-service/)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUT = "assets/Tvist-Executive-Summary.pdf"
LIVE = "https://tvist-api-mias-projects-667d1349.vercel.app"
REPO = "github.com/superheroin888/tvist-api"

INK = colors.HexColor("#101736")
TEAL = colors.HexColor("#0f766e")
MUT = colors.HexColor("#5a6480")
LINE = colors.HexColor("#c9d1e8")
HEADBG = colors.HexColor("#101736")
ALT = colors.HexColor("#f2f5fc")

S = dict(
    brand=ParagraphStyle("brand", fontName="Helvetica-Bold", fontSize=24,
                         textColor=INK, spaceAfter=2),
    tag=ParagraphStyle("tag", fontName="Helvetica-Oblique", fontSize=10,
                       textColor=TEAL, spaceAfter=8),
    h=ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=12,
                     textColor=TEAL, spaceBefore=9, spaceAfter=3),
    p=ParagraphStyle("p", fontName="Helvetica", fontSize=8.8, leading=12,
                     textColor=INK, spaceAfter=3),
    cell=ParagraphStyle("cell", fontName="Helvetica", fontSize=7.8, leading=10,
                        textColor=INK),
    cellh=ParagraphStyle("cellh", fontName="Helvetica-Bold", fontSize=7.8,
                         leading=10, textColor=colors.white),
    mut=ParagraphStyle("mut", fontName="Helvetica", fontSize=7.2, leading=9.5,
                       textColor=MUT),
)


def para(text, style):
    return Paragraph(text, S[style])


def table(head, rows, widths):
    data = [[Paragraph(c, S["cellh"]) for c in head]]
    data += [[Paragraph(c, S["cell"]) for c in row] for row in rows]
    t = Table(data, colWidths=widths, repeatRows=1)
    style = [("BACKGROUND", (0, 0), (-1, 0), HEADBG),
             ("GRID", (0, 0), (-1, -1), 0.5, LINE),
             ("VALIGN", (0, 0), (-1, -1), "TOP"),
             ("TOPPADDING", (0, 0), (-1, -1), 3),
             ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]
    style += [("BACKGROUND", (0, i), (-1, i), ALT) for i in range(2, len(data), 2)]
    t.setStyle(TableStyle(style))
    return t


doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=12 * mm, bottomMargin=11 * mm,
                        leftMargin=14 * mm, rightMargin=14 * mm,
                        title="tvist.api — Executive Summary", author="Maria Lindström")
el = []
el.append(Paragraph('tvist<font color="#0f766e">.api</font>'
                    '<font size="11" color="#5a6480">&nbsp;&nbsp;Executive summary</font>',
                    S["brand"]))
el.append(para("Escrow, consent enforcement, jurisdiction agreement, recall, and "
               "law-cited disputes for AI agents that send payments — one no-auth "
               "HTTP API. 22 jurisdictions · 33 live endpoints · 7 legal categories · "
               "4 trust relationships · 647 tests green.", "tag"))

el.append(para("1 · The problem", "h"))
el.append(para(
    "AI agents now spend money on people's behalf: about 1 in 6 Black Friday 2025 "
    "purchases were AI-assisted; generative-AI retail traffic grew 4,700% year over "
    "year (Adobe Analytics); Juniper Research (2026) names trust the #1 adoption "
    "barrier for agentic commerce. The rails agents pay on are instant and final by "
    "regulation — Pix (MED 2.0), SEPA Instant, FedNow, UPI — and the ECB puts "
    "instant-payment fraud risk at &ldquo;up to 10× higher&rdquo;. Dispute economics "
    "were already broken on cards: 106M disputes at Visa in 2025, 40–80% of e-commerce "
    "disputes classed as friendly fraud, roughly $28B/yr in merchant chargeback "
    "losses. When an agent exceeds its mandate, pays the wrong party, or prepays for "
    "a service that never arrives — on a settlement-final rail, across borders where "
    "every rail has different dispute rules — there is no recourse layer. And as "
    "agents delegate to sub-agents and trade with agents they have never met, the "
    "authority chain has no enforcement.", "p"))

el.append(para("2 · The market today — each product covers one part", "h"))
el.append(table(
    ["Player / category", "What it solves", "What it doesn't"],
    [["Visa AI dispute suite (2026)", "Card dispute automation at network scale",
      "Card-only, single network"],
     ["Mastercard (Mastercom, Ethoca, Agent Pay)", "Card disputes as APIs; intent standard",
      "Protocols, not operations: no cross-rail orchestration, no escrow"],
     ["Amex Agent Purchase Protection", "Liability cover for agent purchases",
      "Closed loop — Amex only"],
     ["Agent-payment protocols (AP2, ACP, OKX APP, x402)", "Agent checkout and payment execution",
      "Dispute resolution absent or &ldquo;future scope&rdquo;"],
     ["Chargeback SaaS", "Card representment for merchants",
      "Nothing for irrevocable A2A or agent mandates"],
     ["Escrow / custody providers", "Licensed fund-holding on specific rails",
      "No programmable, dispute-aware, rail-agnostic escrow"]],
    [52 * mm, 62 * mm, 68 * mm]))

el.append(para("3 · The Tvist solution — four checks in fixed order", "h"))
el.append(para(
    "<b>1 · Jurisdiction, agreed up front.</b> Both parties rank the regions they "
    "accept; the service returns the Nash-bargaining optimum over 22 real regimes "
    "(Pix, SEPA, FedNow, UPI, FPS, NPP, M-Pesa, x402 stablecoin, …) — the product of "
    "both parties' preference scores is maximised, so the pick rewards mutual "
    "acceptability. No shared region → null → no transaction. "
    "<b>2 · Consent, enforced.</b> The principal's mandate — budget and merchant "
    "allowlist — is stored before the agent pays; a payment outside it is refused "
    "with 403 before funds move. "
    "<b>3 · Escrow, delivery-gated.</b> Funds leave the payer at open and reach the "
    "payee only when the posted proof equals the agreed condition exactly; contest "
    "blocks release, refund makes the payer whole. "
    "<b>4 · Recall, rule-gated.</b> A settled payment reverses only where the regime "
    "allows recall, inside its window, on a proven mandate breach.", "p"))
el.append(para(
    "<b>Grounded in law:</b> every dispute reason code maps to one of 7 "
    "civil/commercial-law categories; every jurisdiction lists its statutes, scheme "
    "rulebooks, and regulator with links to official sources; an accepted dispute "
    "returns the citation inline. <b>x402 on-rail:</b> 402 challenge → signed "
    "X-PAYMENT → resource + receipt; each nonce settles once; the consent cap is "
    "checked even on this irrevocable rail. <b>Machine-to-machine:</b> budget-bounded "
    "delegation chains (a sub-agent can never exceed its delegator) and one-call "
    "agent-to-agent pacts: Nash region + mandate check + funded escrow.", "p"))

el.append(para("4 · The four trust relationships, one gate logic", "h"))
el.append(table(
    ["Relationship", "What is checked", "Endpoints"],
    [["Human → agent", "payment stays inside the human's mandate", "/consent → /pay"],
     ["Agent → sub-agent", "delegated budget ≤ delegator's budget", "/m2m/delegate"],
     ["Agent ↔ agent", "shared region + mandate + escrow, one call", "/m2m/handshake"],
     ["Agent → paid resource", "per-request payment; replay + budget checked",
      "/x402/resource/{name}"]],
    [42 * mm, 88 * mm, 52 * mm]))

el.append(para("5 · Proof", "h"))
el.append(para(
    "<b>Adversarially validated:</b> ships as a payments-layer plugin in MIT/NANDA's "
    "Nanda Town rig — 4 swarm scenarios, 10 adversarial validators; every attack "
    "(unilateral clawback, escrow drain, over-mandate spend, friendly-fraud refund, "
    "off-regime dispute) passes against the default ledger and is blocked by Tvist on "
    "identical scenarios; 586 rig tests green. <b>Live service:</b> 33 endpoints, 61 "
    "endpoint tests, and a 41/41 live sweep on the deployed URL including stateful "
    "escrow, recall, dispute, m2m, and x402 flows — 647 tests green project-wide. "
    "<b>Dual-use site:</b> browsers get an interactive page (live playground, "
    "jurisdiction globe with per-region legal clauses, Nash 1–1/1–n/n–n cooperation "
    "visualizer, escrow builder, one-click 10-check API self-test); agents get JSON "
    "and SKILL.md at the same URL — every endpoint documented with one real call and "
    "its real response. <b>Flagship use case:</b> DigiDoot — a personal AI agent for "
    "every Indian citizen — consent → intent vault, UPI → regime, journeys → "
    "escrow/recall.", "p"))

el.append(para("6 · Verify it yourself (60 seconds)", "h"))
el.append(para(
    f'curl -s {LIVE}/health &nbsp;→&nbsp; {{"status":"ok"}}<br/>'
    f"curl -s -X POST {LIVE}/regions/recommend -d "
    "'{&quot;client_prefs&quot;:[&quot;eu_sepa&quot;,&quot;br_pix&quot;],"
    "&quot;agent_prefs&quot;:[&quot;br_pix&quot;,&quot;in_upi&quot;]}' "
    "&nbsp;→&nbsp; agreed_region &quot;br_pix&quot;<br/>"
    f"open {LIVE} &nbsp;→&nbsp; click &ldquo;Test the API&rdquo; — 10 live checks "
    "run in the page.", "p"))

el.append(Spacer(0, 3 * mm))
el.append(HRFlowable(width="100%", thickness=0.75, color=LINE))
el.append(Spacer(0, 1.5 * mm))
el.append(para(f"<b>Live:</b> {LIVE} &nbsp;·&nbsp; agent contract: {LIVE}/skill.md "
               f"&nbsp;·&nbsp; source: {REPO}", "p"))
el.append(para(
    "Technical demonstration only — a notional-credits sandbox, not a bank, payment "
    "institution, or law firm. Legal references cite real primary sources but are "
    "engineering-grade mappings, not legal advice; obtain qualified local counsel "
    "before relying on them in any jurisdiction. Market figures from the named public "
    "sources.", "mut"))

doc.build(el)
print(f"wrote {OUT}")
