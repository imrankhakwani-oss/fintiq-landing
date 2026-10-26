I need you to secure Fintiq's public price endpoints. Please read all of this before changing anything.

## Background

Fintiq (fintiq.uk) uses Yahoo Finance data in two places that anyone on the internet can call:

1. `GET https://api.fintiq.uk/prices/{ticker}?period=1y` and `GET /pair-signals`. These are in `Articles/fintiq-api/main.py` on Railway and are used by `pairs-trading.html`. The FastAPI CORS settings already allow only Fintiq domains, but CORS only stops other websites' browsers. Scripts, servers and curl ignore it. An outside test returned six months of AAPL prices with no check at all.
2. The Cloudflare Worker in `Articles/fintiq-api/cloudflare-worker.js` (intended for `prices.fintiq.uk`). It sends `Access-Control-Allow-Origin: *`, so any website can use it. Our pages don't currently call it, but it may still be deployed.

## Why this matters

- **Data licensing:** Yahoo Finance data is for personal use only. An open endpoint republishes Yahoo data to anyone, which is redistribution. Fintiq also takes subscriptions through Stripe, so this is a commercial context. This is the most visible breach and the easiest to fix.
- **Reputation and investor due diligence:** a public "free Yahoo proxy" on a Fintiq domain is exactly what a data vendor or investor would find and question.
- **Reliability and cost:** if scrapers find the endpoint, Yahoo may rate-limit or block our server's IP, which would break the Pairs Trading tool and every other yfinance feature (Deep Dive included) for real users. It also uses Railway resources.
- **Security hygiene:** unauthenticated, unlimited endpoints invite abuse.

This is step 1 of a larger plan. Step 2, which is not for this session, is to move from Yahoo (yfinance, the Yahoo proxy, OpenBB with provider="yfinance") to a commercially licensed provider such as FMP. Please don't start that migration now.

## Tasks

### Task 1: Guard the FastAPI routes (`main.py`)

Insert the middleware below immediately after the existing `add_noindex_header` middleware (around line 95). Keep the existing CORSMiddleware as it is.

```python
# ── Guard: /prices and /pair-signals only for Fintiq pages, rate-limited ──────
import time as _time
from collections import defaultdict, deque
from urllib.parse import urlparse
from fastapi import Request
from fastapi.responses import JSONResponse

_GUARDED_PREFIXES = ("/prices/", "/pair-signals")
_FINTIQ_ORIGINS = {"https://fintiq.uk", "https://www.fintiq.uk", "https://app.fintiq.uk",
                   "http://localhost:3000", "http://localhost:8080", "http://127.0.0.1:5500"}
_RATE_LIMIT, _RATE_WINDOW = 60, 600          # 60 requests per 10 minutes per IP
_hits: dict = defaultdict(deque)

def _request_origin(request: Request):
    origin = request.headers.get("origin")
    if origin:
        return origin
    ref = request.headers.get("referer")
    if ref:
        p = urlparse(ref)
        return f"{p.scheme}://{p.netloc}"
    return None

def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")   # Railway sits behind a proxy
    return fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?")

@app.middleware("http")
async def guard_price_routes(request: Request, call_next):
    path = request.url.path
    if request.method != "OPTIONS" and path.startswith(_GUARDED_PREFIXES):
        if _request_origin(request) not in _FINTIQ_ORIGINS:
            return JSONResponse({"detail": "Forbidden"}, status_code=403)
        q, now = _hits[_client_ip(request)], _time.time()
        while q and now - q[0] > _RATE_WINDOW:
            q.popleft()
        if len(q) >= _RATE_LIMIT:
            return JSONResponse({"detail": "Too many requests, try again in a few minutes"}, status_code=429)
        q.append(now)
    return await call_next(request)
```

The same code is saved in `Articles/fintiq-api/fastapi-prices-guard.py`.

Also check:
- Whether any other route returns raw Yahoo price series or option chains without a paywall or origin check. List them for me; don't change them yet.
- That the pages calling `/prices` or `/pair-signals` (at least `pairs-trading.html`) are served from fintiq.uk or www.fintiq.uk, so they send a matching Origin header.
- That `fetch()` calls from our pages don't use `referrerPolicy: 'no-referrer'` (a cross-origin GET sends Origin anyway, but confirm).

### Task 2: Lock down or remove the Cloudflare Worker

A secure version is saved as `Articles/fintiq-api/cloudflare-worker.secure.js`. It:
- allows CORS only for https://fintiq.uk, https://www.fintiq.uk and https://app.fintiq.uk (with `Vary: Origin`)
- returns 403 to requests without a Fintiq Origin or Referer
- validates tickers with `^[A-Z0-9.^=\-]{1,15}$`
- caches responses at Cloudflare's edge for 6 hours (`caches.default`, keyed on ticker and period)

Tell me which option is better:
- **Option A (preferred if unused):** delete the `prices.fintiq.uk` worker in the Cloudflare dashboard.
- **Option B:** deploy the secure version and add a Cloudflare WAF rate-limiting rule of about 60 requests per minute per IP on `prices.fintiq.uk`.

Give me step-by-step dashboard instructions for whichever you recommend.

### Task 3: Test plan (before and after deploy)

Give me exact commands and expected results:

```bash
# Should return 403 (no Origin)
curl -i "https://api.fintiq.uk/prices/AAPL?period=6mo"

# Should return 403 (wrong Origin)
curl -i -H "Origin: https://example.com" "https://api.fintiq.uk/prices/AAPL?period=6mo"

# Should return 200 with prices (Fintiq Origin)
curl -i -H "Origin: https://fintiq.uk" "https://api.fintiq.uk/prices/AAPL?period=6mo"

# Rate limit: 61st request inside 10 minutes should return 429
for i in $(seq 1 61); do curl -s -o /dev/null -w "%{http_code}\n" -H "Origin: https://fintiq.uk" "https://api.fintiq.uk/prices/AAPL?period=6mo"; done | sort | uniq -c
```

Then a manual check: open https://fintiq.uk/pairs-trading.html, load a preset pair and a custom pair, and confirm the charts and Z-scores still work. Also confirm `/health` still returns 200 without an Origin header.

### Task 4: Known limitation (note it in CONTEXT.md)

Origin and Referer headers can be faked, so this stops casual reuse and makes scraping slow but not impossible. The long-term fix is to (a) move to licensed data and (b) have `/prices` return only derived results the tool needs (spread, Z-score, correlation, signals) rather than raw price series. Add a short entry to our context notes recording what changed, the date, and this follow-up.

## Constraints

- Don't remove or loosen the existing CORSMiddleware.
- Don't touch the Deep Dive, Stripe, Anthropic or bulletin code in this session.
- Keep the in-memory rate limiter. Railway runs a single instance. If we ever scale to several instances, move it to Upstash Redis, which we already use for `_kv_set`.
- Show me the full diff of `main.py` before I deploy.
