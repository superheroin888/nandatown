# Tvist API — a service AI agents can use on their own

Escrow, consent, and dispute layer for AI agents transacting on someone's behalf.
The agent-facing contract is [`SKILL.md`](SKILL.md) — an AI agent needs nothing
else to use it. Notional-credits sandbox; no auth, no keys, no signup.

- **Live demo:** https://panels-ntsc-density-genesis.trycloudflare.com
  (`/health`, `/`, `/docs`, `/openapi.json`) — ephemeral tunnel; deploy your own
  for a permanent URL (below).
- **What it does:** Nash-optimal jurisdiction recommendation over 22 real
  instant/A2A rails · consent (spend-mandate) enforcement · programmable escrow
  (release only on delivery) · region-aware irrevocable recall · dispute-reason
  validation with civil/commercial-law grounding (`/taxonomy`) · native **x402
  on-rail agent payments** (402 challenge → signed `X-PAYMENT` → resource +
  receipt, replay-safe, consent-capped). See [`SKILL.md`](SKILL.md).

## Run locally

```bash
pip install -r requirements.txt
uvicorn app:app --reload
# open http://127.0.0.1:8000/docs
```

## Deploy (permanent URL)

The app is a single `app.py` (FastAPI) with a `Dockerfile`, `Procfile`,
`render.yaml`, `railway.json`, and `fly.toml` — pick one:

```bash
# Railway
railway init && railway up

# Render (or connect the repo in the dashboard; render.yaml is picked up)
render deploys create           # with the Render CLI

# Fly
fly launch --now                # uses fly.toml + Dockerfile

# Docker (any host)
docker build -t tvist-api . && docker run -p 8000:8000 tvist-api
```

Health check path is `/health`. The server binds `$PORT` (defaults to 8000).

## Notes

- State is in-memory, so use a single always-on instance (Railway/Render/Fly
  free tier is fine). For serverless (Vercel functions), swap the in-memory
  `Ledger` for a KV/Redis store — the logic is isolated in `app.py`.
- The dispute/escrow/region logic mirrors the Tvist `payments` plugin shipped in
  this repo (`packages/nest-plugins-reference/.../payments/tvist.py`); this
  service is its standalone, agent-callable front door.
