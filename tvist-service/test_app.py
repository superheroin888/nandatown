# SPDX-License-Identifier: Apache-2.0
"""End-to-end tests for the Tvist API — every endpoint, every error path.

Run: ``pip install -r requirements.txt pytest && pytest test_app.py -v``
"""

from __future__ import annotations

import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client() -> TestClient:
    """A fresh app (fresh in-memory ledger) per test."""
    import app as app_module

    importlib.reload(app_module)
    return TestClient(app_module.app)


# -- discovery ---------------------------------------------------------------


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_root_lists_endpoints(client: TestClient) -> None:
    body = client.get("/").json()
    assert body["service"] == "Tvist API"
    assert "POST /regions/recommend" in body["endpoints"]


def test_root_serves_homepage_to_browsers(client: TestClient) -> None:
    r = client.get("/", headers={"accept": "text/html,application/xhtml+xml"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert "payments made by AI agents" in r.text  # the hero headline
    assert "SKILL.md" in r.text


def test_root_still_json_for_agents(client: TestClient) -> None:
    # curl / agent SDK default Accept (*/*) must keep getting the JSON index.
    r = client.get("/", headers={"accept": "*/*"})
    assert r.headers["content-type"].startswith("application/json")


def test_skill_md_inline_view(client: TestClient) -> None:
    # Default: clickable — renders inline in any browser, same bytes for agents.
    r = client.get("/skill.md")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]
    assert r.headers["content-disposition"] == "inline"
    assert "# Tvist API" in r.text
    assert "/regions/recommend" in r.text


def test_skill_md_download(client: TestClient) -> None:
    # ?download=1: saved as a file with the right name.
    r = client.get("/skill.md?download=1")
    assert r.status_code == 200
    assert "text/markdown" in r.headers["content-type"]
    assert r.headers["content-disposition"] == 'attachment; filename="SKILL.md"'
    assert "# Tvist API" in r.text


def test_readme_md_inline_and_download(client: TestClient) -> None:
    inline = client.get("/readme.md")
    assert inline.status_code == 200
    assert inline.headers["content-disposition"] == "inline"
    assert "SKILL.md" in inline.text
    dl = client.get("/readme.md?download=1")
    assert dl.headers["content-disposition"] == 'attachment; filename="README.md"'


def test_taxonomy_covers_all_codes_and_regions(client: TestClient) -> None:
    t = client.get("/taxonomy").json()
    assert len(t["categories"]) == 7
    # every category cites both traditions
    for c in t["categories"].values():
        assert c["civil_law_basis"] and c["common_law_basis"]
    # all 10 canonical reason codes are categorized
    assert len(t["reason_codes"]) == 10
    for v in t["reason_codes"].values():
        assert v["category"] in t["categories"]
    # every one of the 22 regions is linked, and each of its codes is mapped
    assert len(t["regions"]) == 22
    for r in t["regions"].values():
        assert r["legal_system"]
        for cat in r["reason_codes"].values():
            assert cat in t["categories"]


def test_region_legal_sources_are_official(client: TestClient) -> None:
    # spot-check three legal traditions
    for region, system_hint, instrument_hint in (
        ("br_pix", "civil", "Resolução BCB"),
        ("us_fednow", "common", "12 CFR"),
        ("in_upi", "common", "Payment and Settlement Systems Act"),
    ):
        d = client.get(f"/regions/{region}/legal").json()
        assert system_hint in d["legal_system"]
        assert d["regulator"]
        assert any(instrument_hint in i["citation"] or instrument_hint in i["name"]
                   for i in d["instruments"])
        # every instrument links to a source and states its role
        for i in d["instruments"]:
            assert i["url"].startswith("http") and i["citation"] and i["role"]
        # every accepted reason code carries an operative legal basis
        assert d["reason_code_linkage"]
        for link in d["reason_code_linkage"]:
            assert link["operative_basis"] and link["category"]
    # agentic dispute grounds in agency/mandate law where accepted
    d = client.get("/regions/eu_sepa/legal").json()
    agency = [x for x in d["reason_code_linkage"] if x["reason_code"] == "agent_exceeded_mandate"]
    assert agency and agency[0]["category"] == "agency_mandate"
    assert client.get("/regions/atlantis/legal").status_code == 404


# -- M2M: machine-to-machine agentic commerce ---------------------------------


def test_m2m_delegation_attenuation(client: TestClient) -> None:
    # Root mandate: orchestrator-agent's own spending policy (machine principal).
    client.post("/consent", json={"consent_id": "root", "principal": "orchestrator-agent",
                                  "budget": 1000})
    # Valid attenuated delegation to a sub-agent.
    d = client.post("/m2m/delegate", json={"delegation_id": "d1", "parent_consent_id": "root",
                                           "agent": "shopper-bot", "budget": 300})
    assert d.status_code == 200
    assert d.json()["depth"] == 1 and d.json()["chain"] == ["d1", "root"]
    # Chains compose, still attenuated — and trace all the way to the root mandate.
    d2 = client.post("/m2m/delegate", json={"delegation_id": "d2", "parent_consent_id": "d1",
                                            "agent": "flight-bot", "budget": 200})
    assert d2.json()["depth"] == 2 and d2.json()["chain"] == ["d2", "d1", "root"]
    # A child cannot exceed its parent — 500 > 300 is refused.
    bad = client.post("/m2m/delegate", json={"delegation_id": "d3", "parent_consent_id": "d1",
                                             "agent": "greedy-bot", "budget": 500})
    assert bad.status_code == 403 and "attenuation" in bad.json()["error"]
    # The delegation is enforced by the SAME pay gate as any consent.
    over = client.post("/pay", json={"ref": "m1", "from_account": "flight-bot",
                                     "to_account": "airline", "amount": 250,
                                     "region": "in_upi", "consent_id": "d2"})
    assert over.status_code == 403
    ok = client.post("/pay", json={"ref": "m2", "from_account": "flight-bot",
                                   "to_account": "airline", "amount": 150,
                                   "region": "in_upi", "consent_id": "d2"})
    assert ok.status_code == 200


def test_m2m_handshake_full_trade_no_human(client: TestClient) -> None:
    client.post("/consent", json={"consent_id": "root", "principal": "buyer-agent",
                                  "budget": 800})
    client.post("/m2m/delegate", json={"delegation_id": "dd", "parent_consent_id": "root",
                                       "agent": "buyer-agent", "budget": 500})
    # One call: Nash region + mandate check + funded escrow.
    h = client.post("/m2m/handshake", json={
        "pact_id": "t1", "buyer_agent": "buyer-agent", "seller_agent": "seller-agent",
        "buyer_prefs": ["eu_sepa", "br_pix", "in_upi"],
        "seller_prefs": ["in_upi", "br_pix", "eu_sepa"],
        "amount": 400, "delegation_id": "dd",
    }).json()
    assert h["agreed_region"] == "br_pix"          # Nash compromise, not client-first
    assert h["status"] == "ESCROWED" and h["escrow_id"] == "pact-t1"
    assert client.get("/accounts/buyer-agent").json()["balance"] == 100_000 - 400
    # Seller delivers; funds release — the ordinary escrow endpoints finish it.
    client.post("/escrow/pact-t1/deliver", json={"proof": "delivered"})
    r = client.post("/escrow/pact-t1/release")
    assert r.status_code == 200
    assert client.get("/accounts/seller-agent").json()["balance"] == 100_400
    pact = client.get("/m2m/pact/t1").json()
    assert pact["escrow_status"]["status"] == "RELEASED"


def test_m2m_handshake_refusals(client: TestClient) -> None:
    # No shared region -> no deal.
    r = client.post("/m2m/handshake", json={
        "pact_id": "t2", "buyer_agent": "a", "seller_agent": "b",
        "buyer_prefs": ["br_pix"], "seller_prefs": ["us_fednow"], "amount": 100,
    })
    assert r.status_code == 409 and "no shared region" in r.json()["error"]
    # Over-mandate pact refused before any funds move.
    client.post("/consent", json={"consent_id": "small", "principal": "a", "budget": 50})
    r2 = client.post("/m2m/handshake", json={
        "pact_id": "t3", "buyer_agent": "a", "seller_agent": "b",
        "buyer_prefs": ["in_upi"], "seller_prefs": ["in_upi"],
        "amount": 100, "delegation_id": "small",
    })
    assert r2.status_code == 403
    assert client.get("/accounts/a").json()["balance"] == 100_000
    assert client.get("/m2m/pact/ghost").status_code == 404
    # stats track the M2M surface
    client.post("/m2m/handshake", json={
        "pact_id": "t4", "buyer_agent": "a", "seller_agent": "b",
        "buyer_prefs": ["in_upi"], "seller_prefs": ["in_upi"], "amount": 10,
    })
    s = client.get("/stats").json()
    assert s["pacts"] == 1 and "delegations" in s


# -- x402 on-rail agent payments ---------------------------------------------


def _x402_header(payer: str, value: int, nonce: str, consent_id: str | None = None) -> str:
    import base64
    import json

    payment = {
        "x402Version": 1,
        "scheme": "exact",
        "network": "base-sepolia-sim",
        "payload": {
            "authorization": {"from": payer, "to": "tvist-treasury", "value": value,
                              "validAfter": 0, "validBefore": 9999999999, "nonce": nonce},
            "signature": f"sim-{nonce}",
        },
        "extra": ({"consent_id": consent_id} if consent_id else {}),
    }
    return base64.b64encode(json.dumps(payment).encode()).decode()


def test_x402_challenge_then_pay(client: TestClient) -> None:
    # 1) no header -> 402 with structured requirements
    r = client.get("/x402/resource/market-report")
    assert r.status_code == 402
    body = r.json()
    assert body["x402Version"] == 1
    req = body["accepts"][0]
    assert req["scheme"] == "exact" and req["payTo"] == "tvist-treasury"
    assert req["maxAmountRequired"] == 25
    # 2) retry with a signed X-PAYMENT header -> 200 + resource + receipt header
    h = _x402_header("agent-x", 25, "n-1")
    r2 = client.get("/x402/resource/market-report", headers={"X-PAYMENT": h})
    assert r2.status_code == 200
    assert "highlights" in r2.json()
    import base64
    import json

    receipt = json.loads(base64.b64decode(r2.headers["X-PAYMENT-RESPONSE"]))
    assert receipt["success"] is True and receipt["txHash"].startswith("0x")
    assert receipt["networkId"] == "base-sepolia-sim"
    # settlement recorded as irrevocable stablecoin_x402
    assert client.get("/stats").json()["x402_settlements"] == 1
    assert client.get("/accounts/tvist-treasury").json()["balance"] == 100_025


def test_x402_replay_and_underpayment_rejected(client: TestClient) -> None:
    h = _x402_header("agent-y", 25, "n-replay")
    assert client.get("/x402/resource/market-report", headers={"X-PAYMENT": h}).status_code == 200
    # replaying the same nonce is refused
    r = client.get("/x402/resource/market-report", headers={"X-PAYMENT": h})
    assert r.status_code == 402 and "replay" in r.json()["error"]
    # underpayment is refused
    low = _x402_header("agent-y", 5, "n-low")
    r2 = client.get("/x402/resource/market-report", headers={"X-PAYMENT": low})
    assert r2.status_code == 402 and "underpayment" in r2.json()["error"]


def test_x402_consent_enforced_on_rail(client: TestClient) -> None:
    # The Tvist twist: an agent carrying its principal's consent is capped by it
    # even on the irrevocable x402 rail.
    client.post("/consent", json={"consent_id": "x-cap", "principal": "agent-z", "budget": 10})
    h = _x402_header("agent-z", 25, "n-consent", consent_id="x-cap")
    r = client.get("/x402/resource/market-report", headers={"X-PAYMENT": h})
    assert r.status_code == 402 and "exceeds consent" in r.json()["error"]
    # and the resulting settlement (without consent) cannot be recalled: x402 forbids it
    ok = _x402_header("agent-z", 25, "n-ok")
    assert client.get("/x402/resource/market-report", headers={"X-PAYMENT": ok}).status_code == 200
    client.post("/consent", json={"consent_id": "post-hoc", "principal": "agent-z", "budget": 1})
    rec = client.post("/recall", json={"ref": "x402-n-ok", "consent_id": "post-hoc"}).json()
    assert rec["reversed"] is False and "disallows recall" in rec["reason"]


def test_x402_facilitator_endpoints(client: TestClient) -> None:
    h = _x402_header("agent-f", 15, "n-fac")
    v = client.post("/x402/verify", json={"resource": "dispute-precedents",
                                          "payment_header": h}).json()
    assert v["isValid"] is True and v["payer"] == "agent-f"
    s = client.post("/x402/settle", json={"resource": "dispute-precedents",
                                          "payment_header": h}).json()
    assert s["success"] is True and s["amount"] == 15
    # settle consumed the nonce; verifying again reports the replay
    v2 = client.post("/x402/verify", json={"resource": "dispute-precedents",
                                           "payment_header": h}).json()
    assert v2["isValid"] is False and "replay" in v2["invalidReason"]
    assert client.get("/x402/resource/ghost").status_code == 404


def test_x402_facilitator_accepts_full_resource_path(client: TestClient) -> None:
    # The 402 challenge advertises resource as "/x402/resource/<name>"; the
    # facilitator must accept that form as well as the bare name.
    h = _x402_header("agent-fp", 15, "n-fullpath")
    v = client.post("/x402/verify", json={"resource": "/x402/resource/dispute-precedents",
                                          "payment_header": h}).json()
    assert v["isValid"] is True
    s = client.post("/x402/settle", json={"resource": "/x402/resource/dispute-precedents",
                                          "payment_header": h}).json()
    assert s["success"] is True and s["amount"] == 15


def test_pitch_kit_downloadable(client: TestClient) -> None:
    listing = client.get("/downloads").json()
    assert set(listing["pitch_kit"]) == {"brief-pdf", "summary-pdf",
                                         "summary-docx", "deck-pptx"}
    for slug, meta in listing["pitch_kit"].items():
        r = client.get(meta["url"])
        assert r.status_code == 200, slug
        assert r.headers["content-disposition"] == f'attachment; filename="{meta["file"]}"'
        assert len(r.content) > 1000
    assert client.get("/download/summary-pdf").headers["content-type"] == "application/pdf"
    assert client.get("/download/ghost").status_code == 404
    # surfaced on the human side too
    html = client.get("/", headers={"accept": "text/html"}).text
    assert "/download/brief-pdf" in html and "/download/deck-pptx" in html


def test_homepage_legal_section_wired(client: TestClient) -> None:
    html = client.get("/", headers={"accept": "text/html"}).text
    assert 'id="law"' in html
    assert "fetch('/taxonomy')" in html          # category legend hydrates live
    assert "/legal" in html                      # jurisdiction explorer endpoint
    assert "showLaw()" in html and "demoLegal" in html


def test_homepage_m2m_wired(client: TestClient) -> None:
    html = client.get("/", headers={"accept": "text/html"}).text
    assert "Machine-to-machine trade" in html      # component card
    assert "demoM2M" in html and "atkM2M" in html  # live demos + attacks
    assert "/m2m/handshake" in html and "/m2m/delegate" in html
    # scenario surfaced as pain point 5 and use cases
    assert "Machine-to-machine authority" in html  # pain card
    assert "Agent-swarm procurement" in html       # M2M use case
    assert "Pay-per-call agent APIs" in html       # x402 use case


def test_index_lists_four_trust_scenarios(client: TestClient) -> None:
    sc = client.get("/").json()["scenarios"]
    assert set(sc) == {"human_to_agent", "agent_to_subagent",
                       "agent_to_agent", "agent_to_resource"}
    for v in sc.values():
        assert v["pain"] and v["flow"]


def test_spectrum_endpoint_visualises_for_machines(client: TestClient) -> None:
    sp = client.get("/spectrum").json()
    assert len(sp["one_gate_logic"]) == 4
    assert set(sp["relationships"]) == {"human_to_agent", "agent_to_subagent",
                                        "agent_to_agent", "agent_to_resource"}
    for v in sp["relationships"].values():
        assert v["label"] and v["gate"] and v["flow"]
    assert "ONE GATE LOGIC" in sp["ascii"]         # terminal-renderable
    assert sp["mermaid"].startswith("graph LR")    # diagram-renderable
    assert "not legal advice" in sp["disclaimer"]


def test_homepage_spectrum_wired(client: TestClient) -> None:
    html = client.get("/", headers={"accept": "text/html"}).text
    assert 'id="spectrum"' in html
    assert "ONE GATE LOGIC" in html                # the gate stack in the SVG
    assert "demoDelegate" in html and "demoHandshake" in html   # clickable lanes
    assert 'href="/spectrum"' in html              # links the machine view


def test_homepage_x402_wired(client: TestClient) -> None:
    html = client.get("/", headers={"accept": "text/html"}).text
    assert "x402 on-rail payments" in html       # component card
    assert "demoX402" in html and "atkX402" in html
    assert "X-PAYMENT" in html                   # real header flow in the JS
    assert "/x402/resource/market-report" in html


def test_view_renders_docs_for_humans(client: TestClient) -> None:
    for doc, raw in (("skill", "/skill.md"), ("readme", "/readme.md")):
        r = client.get(f"/view/{doc}")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/html")
        assert f"fetch('{raw}')" in r.text          # renders the real bytes
        assert f'{raw}?download=1' in r.text        # download button present
    assert client.get("/view/ghost").status_code == 404


def test_cors_open_for_browser_agents(client: TestClient) -> None:
    # The playground (and any browser-based agent framework) calls cross-origin.
    r = client.get("/regions", headers={"origin": "https://example.com"})
    assert r.headers.get("access-control-allow-origin") == "*"


def test_regions_suggest(client: TestClient) -> None:
    # timezone signal wins
    r = client.get("/regions/suggest?tz=Europe/Stockholm").json()
    assert r["suggested_region"] == "nordic" and "timezone" in r["method"]
    # unmapped European timezone falls back to the prefix rule
    assert client.get("/regions/suggest?tz=Europe/Madrid").json()["suggested_region"] == "eu_sepa"
    # no timezone -> Accept-Language region subtag
    r = client.get("/regions/suggest", headers={"accept-language": "pt-BR,pt;q=0.9"}).json()
    assert r["suggested_region"] == "br_pix" and "Accept-Language" in r["method"]
    # no usable signal -> global
    r = client.get("/regions/suggest", headers={"accept-language": ""}).json()
    assert r["suggested_region"] == "global" and r["method"] == "default"
    # every response: valid region, ip echoed, no-geolocation note
    valid = set(client.get("/regions").json()["regions"])
    for q in ("?tz=Asia/Kolkata", "?tz=Australia/Sydney", ""):
        d = client.get(f"/regions/suggest{q}").json()
        assert d["suggested_region"] in valid
        assert "client_ip" in d and "no external geolocation" in d["note"]


def test_globe_markers_match_region_registry(client: TestClient) -> None:
    """Every marker on the globe must be a real region key, and every
    geographic region must have a marker — a marker click can therefore only
    load its own region's legal data (the panel fetches /regions/{key}/legal
    with the same key)."""
    import re

    html = client.get("/", headers={"accept": "text/html"}).text
    geo_block = re.search(r"const GEO = \{(.*?)\};", html, re.S).group(1)
    marker_keys = set(re.findall(r"(\w+):\[", geo_block))
    region_keys = set(client.get("/regions").json()["regions"])
    assert marker_keys <= region_keys
    assert region_keys - marker_keys == {"global", "stablecoin_x402"}  # chips, not markers
    # the panel fetch uses the same key the marker carries
    assert "/regions/${k}/legal" in html


def test_homepage_overview_and_map_wired(client: TestClient) -> None:
    html = client.get("/", headers={"accept": "text/html"}).text
    # executive-summary teaser: sourced figures + downloads
    assert "Adobe" in html and "Juniper Research" in html
    assert "/download/brief-pdf" in html and "/download/summary-docx" in html
    # jurisdiction globe: markers for every geographic region + the two chips
    for key in ("eu_sepa", "br_pix", "in_upi", "us_fednow", "cn_ibps", "ke_mpesa"):
        assert key in html
    assert 'id="globe"' in html and "selectRegion" in html and "hlClause" in html
    assert "/regions/${k}/legal" in html  # clauses load live from the API
    assert 'data-k="global"' in html and 'data-k="stablecoin_x402"' in html
    # Nash cooperation modes, all driven by POST /regions/recommend
    assert "runNash" in html and "NASH_MODES" in html
    for mode in ("'1-1'", "'1-n'", "'n-n'"):
        assert mode in html
    # suggested-start chip: click in / click out, driven by GET /regions/suggest
    assert 'id="suggestbox"' in html and "toggleSuggest" in html
    assert "/regions/suggest?tz=" in html
    # "Test the API" buttons run the live self-test, not just an anchor jump
    assert "async function testApi()" in html
    assert html.count('onclick="go(testApi)"') == 2  # nav CTA + hero button
    assert 'onclick="testApi()"' in html             # playground button
    # escrow builder: jurisdiction of choice + full lifecycle, all real calls
    assert 'id="esregion"' in html and 'id="esproof"' in html
    for fn in ("escOpen", "escDeliver", "escRelease", "escContest", "escRefund", "escStatus"):
        assert f'onclick="{fn}()"' in html
    # sandbox identity: nav badge + URL placeholders filled with this origin
    assert ">sandbox</span>" in html
    assert html.count('class="g origin"') >= 4  # hero snippets + BASE line in #api
    assert "location.origin" in html


def test_homepage_has_playground_and_dual_use(client: TestClient) -> None:
    html = client.get("/", headers={"accept": "text/html"}).text
    assert "Dual-use by design" in html
    assert 'id="try"' in html          # live playground section
    assert "runFlow()" in html         # real fetch-driven buttons


def test_homepage_fully_wired_to_endpoints(client: TestClient) -> None:
    """Every section of the page is functional: live pill, metrics, explorer, demos."""
    html = client.get("/", headers={"accept": "text/html"}).text
    assert "fetch('/health')" in html          # live status pill
    assert "fetch('/stats')" in html           # live metrics + stats strip
    assert "fetch('/regions')" in html         # region explorer hydration
    assert "/regions/recommend" in html        # Nash recommender widget
    assert 'id="statbar"' in html              # live stats strip
    assert "verifyGate(" in html               # self-verifying gate table
    assert "demoDigiDoot" in html              # runnable use cases
    assert "demoPrincipal" in html             # runnable personas
    assert "stepRecommend" in html             # clickable flow-chart nodes


def test_homepage_navigation_is_wired(client: TestClient) -> None:
    """Menus are linked and clickable: scrollspy, mobile burger, footer nav, top link."""
    html = client.get("/", headers={"accept": "text/html"}).text
    # sticky nav: clickable logo -> #top anchor, menu container, burger toggle
    assert 'id="top"' in html
    assert 'class="logo" href="#top"' in html
    assert 'id="menu"' in html
    assert "toggleMenu()" in html
    # every nav item points at a real section id on the page
    for sec in ("overview", "pain", "spectrum", "arch", "map", "components", "law",
                "personas", "usecases", "api", "try", "downloads"):
        assert f'href="#{sec}"' in html
        assert f'id="{sec}"' in html
    # scrollspy + back-to-top logic present
    assert "scrollspy" in html or "spy()" in html
    assert 'id="totop"' in html
    # structured footer menu with live-endpoint + deliverable links
    assert 'class="fcols"' in html
    for link in ("/health", "/stats", "/regions", "/skill.md", "/readme.md", "/openapi.json"):
        assert link in html


def test_stats_endpoint(client: TestClient) -> None:
    s = client.get("/stats").json()
    assert s["regions"] == 22
    assert s["endpoints"] >= 15
    assert s["settlements"] == 0
    assert s["total_funds"] == 0  # no accounts touched yet


def test_stats_tracks_activity_and_conserves_funds(client: TestClient) -> None:
    # Create both accounts first so total_funds is fixed, then verify a payment
    # and an escrow move value around without changing the conserved total.
    client.get("/accounts/a")
    client.get("/accounts/b")
    start = client.get("/stats").json()["total_funds"]
    client.post("/pay", json={"ref": "s1", "from_account": "a", "to_account": "b",
                              "amount": 100, "region": "in_upi"})
    client.post("/escrow", json={"escrow_id": "se1", "payer": "a", "payee": "b",
                                 "amount": 50, "region": "in_upi",
                                 "condition_expected": "done"})
    s = client.get("/stats").json()
    assert s["settlements"] == 1
    assert s["escrows"]["total"] == 1
    assert s["held_credits"] == 50
    assert s["total_funds"] == start  # conservation invariant


def test_openapi_served(client: TestClient) -> None:
    spec = client.get("/openapi.json").json()
    assert "/regions/recommend" in spec["paths"]
    assert spec["info"]["title"] == "Tvist API"


def test_regions_count(client: TestClient) -> None:
    body = client.get("/regions").json()
    assert body["count"] == 22
    assert body["regions"]["us_fednow"]["recall_allowed"] is False
    assert "goods_not_received" in body["regions"]["in_upi"]["reason_codes"]


# -- region recommendation (Nash) -------------------------------------------


def test_recommend_nash_beats_client_first(client: TestClient) -> None:
    r = client.post(
        "/regions/recommend",
        json={"client_prefs": ["eu_sepa", "br_pix", "in_upi"], "agent_prefs": ["in_upi", "br_pix", "eu_sepa"]},
    ).json()
    assert r["agreed_region"] == "br_pix"
    assert r["naive_client_first"] == "eu_sepa"
    assert r["regime"]["recall_allowed"] is True


def test_recommend_no_overlap_is_null(client: TestClient) -> None:
    r = client.post(
        "/regions/recommend",
        json={"client_prefs": ["br_pix"], "agent_prefs": ["us_fednow"]},
    ).json()
    assert r["agreed_region"] is None
    assert r["regime"] is None


def test_recommend_mutual_top_pick(client: TestClient) -> None:
    r = client.post(
        "/regions/recommend",
        json={"client_prefs": ["in_upi", "br_pix"], "agent_prefs": ["in_upi", "eu_sepa"]},
    ).json()
    assert r["agreed_region"] == "in_upi"


# -- consent + pay -----------------------------------------------------------


def test_pay_within_consent(client: TestClient) -> None:
    client.post("/consent", json={"consent_id": "c1", "principal": "alice", "budget": 500})
    r = client.post(
        "/pay",
        json={"ref": "p1", "from_account": "alice", "to_account": "shop", "amount": 300,
              "region": "in_upi", "consent_id": "c1"},
    ).json()
    assert r["settled"] is True
    assert r["irrevocable"] is True
    assert client.get("/accounts/alice").json()["balance"] == 99_700
    assert client.get("/accounts/shop").json()["balance"] == 100_300


def test_pay_over_consent_forbidden(client: TestClient) -> None:
    client.post("/consent", json={"consent_id": "c1", "principal": "alice", "budget": 500})
    r = client.post(
        "/pay",
        json={"ref": "p2", "from_account": "alice", "to_account": "shop", "amount": 900,
              "region": "in_upi", "consent_id": "c1"},
    )
    assert r.status_code == 403
    assert "exceeds consent" in r.json()["error"]


def test_pay_allowlist_enforced(client: TestClient) -> None:
    client.post(
        "/consent",
        json={"consent_id": "c2", "principal": "alice", "budget": 500, "merchant_allowlist": ["shop"]},
    )
    ok = client.post(
        "/pay",
        json={"ref": "a1", "from_account": "alice", "to_account": "shop", "amount": 100,
              "region": "global", "consent_id": "c2"},
    )
    assert ok.status_code == 200
    bad = client.post(
        "/pay",
        json={"ref": "a2", "from_account": "alice", "to_account": "stranger", "amount": 100,
              "region": "global", "consent_id": "c2"},
    )
    assert bad.status_code == 403


def test_pay_unknown_consent_404(client: TestClient) -> None:
    r = client.post(
        "/pay",
        json={"ref": "p3", "from_account": "a", "to_account": "b", "amount": 10,
              "region": "global", "consent_id": "nope"},
    )
    assert r.status_code == 404


def test_pay_duplicate_ref_conflict(client: TestClient) -> None:
    body = {"ref": "dup", "from_account": "a", "to_account": "b", "amount": 10, "region": "global"}
    assert client.post("/pay", json=body).status_code == 200
    assert client.post("/pay", json=body).status_code == 409


def test_pay_negative_amount_rejected(client: TestClient) -> None:
    r = client.post(
        "/pay",
        json={"ref": "neg", "from_account": "a", "to_account": "b", "amount": -5, "region": "global"},
    )
    assert r.status_code == 400


def test_pay_insufficient_balance(client: TestClient) -> None:
    r = client.post(
        "/pay",
        json={"ref": "big", "from_account": "a", "to_account": "b", "amount": 999_999, "region": "global"},
    )
    assert r.status_code == 400
    assert "Insufficient" in r.json()["error"]


# -- escrow ------------------------------------------------------------------


def _open_escrow(client: TestClient, eid: str = "e1", amount: int = 400) -> None:
    client.post(
        "/escrow",
        json={"escrow_id": eid, "payer": "alice", "payee": "airline", "amount": amount,
              "region": "in_upi", "condition_expected": "ticket"},
    )


def test_escrow_release_only_after_delivery(client: TestClient) -> None:
    _open_escrow(client)
    assert client.get("/accounts/alice").json()["balance"] == 99_600  # funded
    early = client.post("/escrow/e1/release")
    assert early.status_code == 403
    client.post("/escrow/e1/deliver", json={"proof": "ticket"})
    done = client.post("/escrow/e1/release")
    assert done.status_code == 200
    assert client.get("/accounts/airline").json()["balance"] == 100_400


def test_escrow_wrong_proof_does_not_deliver(client: TestClient) -> None:
    _open_escrow(client)
    r = client.post("/escrow/e1/deliver", json={"proof": "wrong"}).json()
    assert r["delivered"] is False
    assert client.post("/escrow/e1/release").status_code == 403


def test_escrow_contest_blocks_release_then_refund(client: TestClient) -> None:
    _open_escrow(client)
    client.post("/escrow/e1/deliver", json={"proof": "ticket"})
    client.post("/escrow/e1/contest")
    assert client.post("/escrow/e1/release").status_code == 409
    refund = client.post("/escrow/e1/refund")
    assert refund.status_code == 200
    assert client.get("/accounts/alice").json()["balance"] == 100_000  # made whole


def test_escrow_duplicate_id_conflict(client: TestClient) -> None:
    _open_escrow(client)
    dup = client.post(
        "/escrow",
        json={"escrow_id": "e1", "payer": "x", "payee": "y", "amount": 1,
              "region": "global", "condition_expected": "z"},
    )
    assert dup.status_code == 409


def test_escrow_unknown_id_404(client: TestClient) -> None:
    assert client.post("/escrow/ghost/release").status_code == 404
    assert client.get("/escrow/ghost").status_code == 404


def test_escrow_refund_requires_contest(client: TestClient) -> None:
    _open_escrow(client)
    assert client.post("/escrow/e1/refund").status_code == 409  # not contested


# -- recall ------------------------------------------------------------------


def test_recall_refused_on_no_recall_region(client: TestClient) -> None:
    client.post("/pay", json={"ref": "f1", "from_account": "bob", "to_account": "scam",
                              "amount": 300, "region": "us_fednow"})
    client.post("/consent", json={"consent_id": "cb", "principal": "bob", "budget": 100})
    r = client.post("/recall", json={"ref": "f1", "consent_id": "cb"}).json()
    assert r["reversed"] is False
    assert "disallows recall" in r["reason"]


def test_recall_succeeds_on_mandate_breach(client: TestClient) -> None:
    client.post("/pay", json={"ref": "u1", "from_account": "bob", "to_account": "scam",
                              "amount": 300, "region": "in_upi"})
    client.post("/consent", json={"consent_id": "cb", "principal": "bob", "budget": 100})
    r = client.post("/recall", json={"ref": "u1", "consent_id": "cb"}).json()
    assert r["reversed"] is True
    assert client.get("/accounts/bob").json()["balance"] == 100_000  # made whole


def test_recall_refused_without_breach(client: TestClient) -> None:
    client.post("/pay", json={"ref": "u2", "from_account": "bob", "to_account": "shop",
                              "amount": 50, "region": "in_upi"})
    client.post("/consent", json={"consent_id": "cb", "principal": "bob", "budget": 100})
    r = client.post("/recall", json={"ref": "u2", "consent_id": "cb"}).json()
    assert r["reversed"] is False
    assert "no mandate breach" in r["reason"]


def test_recall_unknown_settlement_404(client: TestClient) -> None:
    client.post("/consent", json={"consent_id": "cb", "principal": "bob", "budget": 100})
    assert client.post("/recall", json={"ref": "ghost", "consent_id": "cb"}).status_code == 404


def test_recall_is_idempotent(client: TestClient) -> None:
    client.post("/pay", json={"ref": "u3", "from_account": "bob", "to_account": "scam",
                              "amount": 300, "region": "in_upi"})
    client.post("/consent", json={"consent_id": "cb", "principal": "bob", "budget": 100})
    assert client.post("/recall", json={"ref": "u3", "consent_id": "cb"}).json()["reversed"] is True
    second = client.post("/recall", json={"ref": "u3", "consent_id": "cb"}).json()
    assert second["reversed"] is False  # already reversed, no double credit


# -- dispute -----------------------------------------------------------------


def test_dispute_valid_and_invalid_reason(client: TestClient) -> None:
    ok = client.post("/dispute", json={"ref": "d1", "region": "in_upi", "reason_code": "goods_not_received"})
    assert ok.json()["accepted"] is True
    bad = client.post("/dispute", json={"ref": "d1", "region": "in_upi", "reason_code": "pix_med_return"})
    assert bad.json()["accepted"] is False


def test_dispute_returns_citation_by_legal_tradition(client: TestClient) -> None:
    # Common-law region (India) -> common-law citation string, inline on accept.
    d = client.post("/dispute", json={"ref": "c1", "region": "in_upi",
                                      "reason_code": "goods_not_received"}).json()
    assert d["accepted"] is True
    assert d["legal_basis"]["category"] == "non_performance"
    assert "UCC" in d["legal_basis"]["citation"] or "Breach of contract" in d["legal_basis"]["citation"]
    # Civil-law region (Brazil) -> civil-law citation string.
    d2 = client.post("/dispute", json={"ref": "c2", "region": "br_pix",
                                       "reason_code": "agent_exceeded_mandate"}).json()
    assert d2["legal_basis"]["category"] == "agency_mandate"
    assert "BGB" in d2["legal_basis"]["citation"] or "Code civil" in d2["legal_basis"]["citation"]
    # Rejected filings carry no basis, but always carry the disclaimer.
    d3 = client.post("/dispute", json={"ref": "c3", "region": "in_upi",
                                       "reason_code": "pix_med_return"}).json()
    assert d3["legal_basis"] is None
    for resp in (d, d2, d3):
        assert "not legal advice" in resp["disclaimer"]


def test_disclaimer_everywhere(client: TestClient) -> None:
    # Dedicated endpoint + stamped on legal-flavored responses + agent index.
    assert "not legal advice" in client.get("/disclaimer").json()["disclaimer"]
    assert "not legal advice" in client.get("/").json()["disclaimer"]
    assert "not legal advice" in client.get("/taxonomy").json()["disclaimer"]
    assert "not legal advice" in client.get("/regions/eu_sepa/legal").json()["disclaimer"]
    # And on the human side of the dual-use surface.
    html = client.get("/", headers={"accept": "text/html"}).text
    assert html.count("not legal advice") >= 2      # law section + footer
    assert "/disclaimer" in html


# -- ledger conservation -----------------------------------------------------


def test_ledger_conserves_funds(client: TestClient) -> None:
    import app as app_module

    def total() -> int:
        led = app_module.LEDGER
        held = sum(e.amount for e in led.escrows.values() if e.status in ("FUNDED", "CONTESTED"))
        # touch the accounts we use so they exist at the start balance
        for name in ("alice", "airline", "bob", "scam", "shop"):
            led.balance(name)
        return sum(led.balances.values()) + held

    start = total()
    client.post("/consent", json={"consent_id": "c1", "principal": "alice", "budget": 1000})
    client.post("/pay", json={"ref": "p1", "from_account": "alice", "to_account": "shop",
                              "amount": 300, "region": "in_upi", "consent_id": "c1"})
    _open_escrow(client, "e1", 400)
    client.post("/escrow/e1/deliver", json={"proof": "ticket"})
    client.post("/escrow/e1/release")
    _open_escrow(client, "e2", 250)  # left funded (held)
    client.post("/pay", json={"ref": "u1", "from_account": "bob", "to_account": "scam",
                              "amount": 200, "region": "in_upi"})
    client.post("/consent", json={"consent_id": "cb", "principal": "bob", "budget": 100})
    client.post("/recall", json={"ref": "u1", "consent_id": "cb"})
    assert total() == start
