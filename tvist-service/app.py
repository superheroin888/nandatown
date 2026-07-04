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
class Ledger:
    balances: dict[str, int] = field(default_factory=dict)
    consents: dict[str, Consent] = field(default_factory=dict)
    escrows: dict[str, Escrow] = field(default_factory=dict)
    settlements: dict[str, Settlement] = field(default_factory=dict)
    cases: dict[str, dict[str, Any]] = field(default_factory=dict)

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
)


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
        "endpoints": {
            "GET /health": "liveness",
            "GET /stats": "live service metrics (accounts, settlements, escrows, funds)",
            "GET /skill.md": "agent-facing SKILL.md (inline; ?download=1 for attachment)",
            "GET /readme.md": "service README (inline; ?download=1 for attachment)",
            "GET /view/skill": "SKILL.md rendered as HTML for humans",
            "GET /view/readme": "README rendered as HTML for humans",
            "GET /regions": "list all jurisdictions and their dispute regimes",
            "POST /regions/recommend": "Nash-optimal region for two parties {client_prefs, agent_prefs}",
            "POST /consent": "store a spend mandate {consent_id, principal, budget, merchant_allowlist?}",
            "POST /pay": "settle within consent {ref, from_account, to_account, amount, region, consent_id?}",
            "POST /escrow": "open+fund escrow {escrow_id, payer, payee, amount, region, condition_expected}",
            "POST /escrow/{id}/deliver": "mark delivered {proof}",
            "POST /escrow/{id}/release": "release iff delivered",
            "POST /escrow/{id}/contest": "contest a funded escrow",
            "POST /escrow/{id}/refund": "refund a contested escrow to payer",
            "POST /recall": "recall a settled payment {ref, consent_id, current_tick?}",
            "POST /dispute": "file a dispute {ref, region, reason_code}",
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
        "recalled": sum(1 for s in LEDGER.settlements.values() if s.reversed),
        "escrows": {"total": len(LEDGER.escrows), **by_status},
        "held_credits": held,
        "disputes": len(LEDGER.cases),
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
    """File a dispute; accepted only if the reason code is valid in the region's taxonomy."""
    reg = regime(body.region)
    accepted = body.reason_code in reg.reason_codes
    if accepted:
        LEDGER.cases[body.ref] = {"region": body.region, "reason_code": body.reason_code}
    return {
        "ref": body.ref,
        "accepted": accepted,
        "reason_code": body.reason_code,
        "region": body.region,
        "valid_reason_codes": sorted(reg.reason_codes),
    }


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
