# Generates assets/Tvist-Executive-Brief.pdf — one page, current verified facts.
# Run: .venv-svc/bin/python tools/make_brief_pdf.py  (from tvist-service/)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUT = "assets/Tvist-Executive-Brief.pdf"
LIVE = "https://tvist-api-mias-projects-667d1349.vercel.app"
REPO = "github.com/superheroin888/tvist-api"

INK = colors.HexColor("#101736")
TEAL = colors.HexColor("#0f766e")
MUT = colors.HexColor("#5a6480")
LINE = colors.HexColor("#c9d1e8")

S = dict(
    brand=ParagraphStyle("brand", fontName="Helvetica-Bold", fontSize=26,
                         textColor=INK, spaceAfter=2),
    tag=ParagraphStyle("tag", fontName="Helvetica-Oblique", fontSize=10.5,
                       textColor=TEAL, spaceAfter=10),
    h=ParagraphStyle("h", fontName="Helvetica-Bold", fontSize=11,
                     textColor=TEAL, spaceBefore=8, spaceAfter=3),
    p=ParagraphStyle("p", fontName="Helvetica", fontSize=9, leading=12.5,
                     textColor=INK),
    mut=ParagraphStyle("mut", fontName="Helvetica", fontSize=7.5, leading=10,
                       textColor=MUT),
    stat=ParagraphStyle("stat", fontName="Helvetica-Bold", fontSize=17,
                        textColor=TEAL, alignment=1),
    statl=ParagraphStyle("statl", fontName="Helvetica", fontSize=7.5,
                         textColor=MUT, alignment=1),
)


def para(text, style):
    return Paragraph(text, S[style])


doc = SimpleDocTemplate(OUT, pagesize=A4, topMargin=14 * mm, bottomMargin=12 * mm,
                        leftMargin=15 * mm, rightMargin=15 * mm,
                        title="tvist.api — Executive Brief", author="Maria Lindström")
el = []
el.append(Paragraph('tvist<font color="#0f766e">.api</font>'
                    '<font size="12" color="#5a6480">&nbsp;&nbsp;Executive brief</font>',
                    S["brand"]))
el.append(para("Escrow, consent enforcement, jurisdiction agreement, recall, and "
               "law-cited disputes for AI agents that send payments — one no-auth "
               "HTTP API.", "tag"))

stats = Table([[para(n, "stat") for n in ("22", "33", "7", "4", "647")],
               [para(x, "statl") for x in ("jurisdictions", "live endpoints",
                                           "legal categories", "trust relationships",
                                           "tests green")]],
              colWidths=[36 * mm] * 5)
stats.setStyle(TableStyle([("BOX", (0, 0), (-1, -1), 0.75, LINE),
                           ("INNERGRID", (0, 0), (-1, 0), 0, colors.white),
                           ("TOPPADDING", (0, 0), (-1, 0), 6),
                           ("BOTTOMPADDING", (0, 1), (-1, 1), 6)]))
el.append(stats)

el.append(para("The problem", "h"))
el.append(para(
    "AI agents now spend money on people's behalf: about 1 in 6 Black Friday 2025 "
    "purchases were AI-assisted; generative-AI retail traffic grew 4,700% year over "
    "year (Adobe Analytics). Juniper Research (2026) names trust the #1 adoption "
    "barrier. The rails agents pay on — Pix, SEPA Instant, FedNow, UPI — settle in "
    "seconds and are final; the ECB puts instant-payment fraud risk at &ldquo;up to 10× "
    "higher&rdquo;. Card disputes were already expensive: 106M at Visa in 2025, 40–80% "
    "friendly fraud, ~$28B/yr merchant chargeback losses. When an agent overpays, pays "
    "the wrong party, or prepays for something that never arrives, there is no recourse "
    "layer — and existing products (card-network dispute suites, agent-payment "
    "protocols, chargeback SaaS, custody) each cover only one piece.", "p"))

el.append(para("The solution — four checks in fixed order around every agent payment", "h"))
el.append(para(
    "<b>1 · Jurisdiction agreed up front:</b> both parties rank the regions they accept; "
    "the service returns the Nash-bargaining optimum over 22 real regimes — or null: no "
    "deal. <b>2 · Consent enforced:</b> the principal's mandate (budget + merchant "
    "allowlist) is stored first; a payment outside it is refused with 403 before funds "
    "move. <b>3 · Escrow, delivery-gated:</b> funds hold until the proof equals the "
    "agreed condition exactly. <b>4 · Recall, rule-gated:</b> reversal only where the "
    "regime allows it, in window, and the mandate was breached. Plus: disputes return "
    "the legal citation inline (7 civil/commercial-law categories, official sources per "
    "jurisdiction); a native x402 pay-per-request rail (402 → signed X-PAYMENT → "
    "receipt, replay-refused); machine-to-machine delegation and one-call agent-to-agent "
    "trade under the same checks.", "p"))

el.append(para("Proof", "h"))
el.append(para(
    "Adversarially validated in MIT/NANDA's Nanda Town rig: 4 swarm scenarios, 10 "
    "validators — every attack passes on a plain ledger and is blocked by Tvist on "
    "identical scenarios; 586 rig tests green. The live service passes 61 endpoint "
    "tests and a 41/41 live sweep on the deployed URL, including stateful escrow, "
    "recall, dispute, m2m, and x402 flows. The dual-use site (humans get an interactive "
    "page, agents get JSON at the same URL) includes a live playground, an interactive "
    "jurisdiction globe with per-region legal clauses, a Nash 1–1/1–n/n–n cooperation "
    "visualizer, an escrow builder, and a one-click 10-check API self-test. Flagship "
    "use case: DigiDoot — a personal AI agent for every Indian citizen — settled via "
    "Tvist on UPI.", "p"))

el.append(Spacer(0, 4 * mm))
el.append(HRFlowable(width="100%", thickness=0.75, color=LINE))
el.append(Spacer(0, 2 * mm))
el.append(para(f"<b>Live:</b> {LIVE} &nbsp;·&nbsp; agent contract: {LIVE}/skill.md "
               f"&nbsp;·&nbsp; source: {REPO}", "p"))
el.append(Spacer(0, 2 * mm))
el.append(para(
    "Technical demonstration only — a notional-credits sandbox, not a bank, payment "
    "institution, or law firm. Legal references cite real primary sources but are "
    "engineering-grade mappings, not legal advice; obtain qualified local counsel "
    "before relying on them in any jurisdiction.", "mut"))

doc.build(el)
print(f"wrote {OUT}")
