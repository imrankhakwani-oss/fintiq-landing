# Fintiq API — guard for the public /prices and /pair-signals routes
#
# Paste this block into main.py directly after the existing
# `add_noindex_header` middleware (around line 95). It needs no new packages.
#
# What it does:
#   1. Refuses /prices/* and /pair-signals unless the request comes from a
#      Fintiq page (Origin or Referer header). CORS alone only stops other
#      websites' browsers; scripts and servers ignore it.
#   2. Limits each IP to 60 price requests per 10 minutes, which is plenty
#      for a person using the Pairs Trading tool and stops bulk scraping.
#   3. Leaves every other route untouched.

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
