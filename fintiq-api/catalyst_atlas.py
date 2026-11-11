"""
Catalyst Atlas — Fintiq
=======================
Explains why a share price moved and how it has reacted to each kind of
news, in plain English for retail investors.

For any ticker it:
  1. splits every day's move into market, sector/rates and company-specific parts
     (rolling 250-day regression, using only past data);
  2. finds rallies, declines and quiet spells at three time scales;
  3. finds catalysts: earnings (beat / miss from yfinance) and the biggest
     company-specific days, which are labelled from news (Tavily + Claude Haiku);
  4. measures each catalyst's "footprint" from 5 days before to 60 days after;
  5. scores how reliably each kind of catalyst moved the price and whether the
     move stuck;
  6. gives likely price ranges for 1 week, 1 month and 3 months;
  7. writes the summary sentences from templates (no AI), so the wording is
     factual and never a recommendation.

Educational research only. Not financial advice.

Usage inside the Fintiq API (main.py):

    from catalyst_atlas import build_atlas
    @app.get("/catalyst-atlas/{ticker}")
    def catalyst_atlas(ticker: str):
        return build_atlas(ticker, kv_get=_kv_get, kv_set=_kv_set,
                           tavily_search=_tavily_search,
                           anthropic_api_key=ANTHROPIC_API_KEY)
"""
from __future__ import annotations

import json
import math
import re
import time
import datetime as dt
from typing import Callable, Optional

import numpy as np
import pandas as pd

VERSION = "v8"
CACHE_TTL = 12 * 3600          # full result
LABEL_TTL = 30 * 24 * 3600     # news labels for past days rarely change
HAIKU_MODEL = "claude-haiku-4-5-20251001"
SONNET_MODEL = "claude-sonnet-4-6"   # same model the rest of the Fintiq API uses
TICKER_RE = re.compile(r"^[A-Z0-9.\-^=]{1,15}$")

# Equal-weight sector funds, so a giant company (e.g. Tesla in XLY) does not
# dominate its own "sector" factor. Cap-weighted funds are the fallback.
SECTOR_ETF = {
    "Technology": "RSPT", "Consumer Cyclical": "RSPD", "Financial Services": "RSPF",
    "Energy": "RSPG", "Healthcare": "RSPH", "Industrials": "RSPN",
    "Consumer Defensive": "RSPS", "Utilities": "RSPU", "Basic Materials": "RSPM",
    "Real Estate": "RSPR", "Communication Services": "RSPC",
}
SECTOR_ETF_FALLBACK = {
    "RSPT": "XLK", "RSPD": "XLY", "RSPF": "XLF", "RSPG": "XLE", "RSPH": "XLV", "RSPN": "XLI",
    "RSPS": "XLP", "RSPU": "XLU", "RSPM": "XLB", "RSPR": "XLRE", "RSPC": "XLC",
}

NEWS_CATEGORIES = [
    "Earnings & guidance", "Sales & delivery data", "Product & technology",
    "Analyst rating", "Deals & partnerships", "Legal & regulation",
    "Management & leadership", "Politics & policy", "Competition",
    "Customer & industry demand", "Market-wide news", "Unexplained",
]

WINDOW = 250
MIN_WINDOW = 60


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching (yfinance). Kept separate so the analysis can be tested offline.
# ─────────────────────────────────────────────────────────────────────────────
OIL = "BZ=F"   # Brent crude futures


def clean_name(raw: str) -> str:
    """'SHELL PLC ORD EUR0.07' -> 'Shell plc'; 'NVIDIA Corporation' unchanged."""
    import re as _re
    s = str(raw or "").strip()
    s = _re.split(r"\s+(ORD|ORDINARY|SHS|SHARES|ADR|CL\s+[A-Z]|CLASS\s+[A-Z])\b", s, flags=_re.I)[0]
    s = _re.sub(r"\s+[$€£]?\d+(\.\d+)?[PpGg]?$", "", s).strip(" ,-")
    if s.isupper() and len(s) > 4:
        def fix(w):
            if w == "PLC":
                return "plc"
            if len(w) <= 4 and w.isalpha():
                return w                      # BP, HSBC, AG, SA keep capitals
            return "-".join(p.capitalize() for p in w.split("-"))
        s = " ".join(fix(w) for w in s.split())
    return s or str(raw)


def fetch_market_data(ticker: str, period: str = "3y") -> dict:
    import yfinance as yf

    tk = yf.Ticker(ticker)
    info = {}
    try:
        info = tk.get_info() or {}
    except Exception:
        pass
    uk = ticker.endswith(".L")
    name = clean_name(info.get("longName") or info.get("shortName") or ticker)
    sector_name = info.get("sector")
    market = "^FTSE" if uk else "SPY"
    # Energy companies (US or UK) follow the oil price far more than their stock index,
    # so Brent crude is used as their "sector" factor.
    if sector_name == "Energy":
        sector = OIL
    else:
        sector = None if uk else SECTOR_ETF.get(sector_name or "")
    rates = None if uk else "^TNX"

    syms = [s for s in [ticker, market, sector, rates] if s]
    raw = yf.download(syms, period=period, interval="1d", auto_adjust=True,
                      progress=False, threads=True)
    closes = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].rename(columns={"Close": ticker})
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    if sector and (sector not in closes or closes[sector].dropna().shape[0] < 200):
        fb = SECTOR_ETF_FALLBACK.get(sector)
        if not fb:
            sector = None
    if sector and (sector not in closes or closes[sector].dropna().shape[0] < 200):
        try:
            extra = yf.download(fb, period=period, interval="1d", auto_adjust=True, progress=False)["Close"]
            extra.index = pd.to_datetime(extra.index).tz_localize(None)
            closes[fb] = extra.squeeze()
            sector = fb
        except Exception:
            sector = None

    earnings = None
    try:
        earnings = tk.get_earnings_dates(limit=20)
    except Exception:
        try:
            earnings = tk.earnings_dates
        except Exception:
            earnings = None

    iv = None
    try:
        iv = _atm_implied_vol(tk, float(closes[ticker].dropna().iloc[-1]))
    except Exception:
        iv = None

    return {
        "ticker": ticker, "name": name, "sector": sector_name,
        "currency": info.get("currency") or ("GBp" if uk else "USD"),
        "market": market, "sector_etf": sector, "rates": rates,
        "closes": closes, "earnings": earnings, "iv": iv,
    }


def _atm_implied_vol(tk, spot: float) -> Optional[float]:
    """At-the-money implied volatility from the first expiry 20+ days out."""
    exps = list(getattr(tk, "options", []) or [])
    today = dt.date.today()
    for e in exps:
        d = dt.date.fromisoformat(e)
        if (d - today).days < 20:
            continue
        ch = tk.option_chain(e)
        vals = []
        for df in (ch.calls, ch.puts):
            df = df[(df["bid"] > 0) & (df["ask"] > 0)]
            if df.empty:
                continue
            row = df.iloc[(df["strike"] - spot).abs().argsort()[:1]]
            v = float(row["impliedVolatility"].iloc[0])
            if 0.05 < v < 3:
                vals.append(v)
        return float(np.mean(vals)) if vals else None
    return None


# ─────────────────────────────────────────────────────────────────────────────
# News labelling for big company-specific days (Tavily + Claude Haiku)
# ─────────────────────────────────────────────────────────────────────────────
def _pub_date(r: dict):
    """Tavily dates come as ISO ('2026-10-23...') or RFC ('Tue, 02 Apr 2024 ...')."""
    p = str(r.get("published_date") or "").strip()
    if not p:
        return None
    try:
        return dt.date.fromisoformat(p[:10])
    except Exception:
        pass
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(p).date()
    except Exception:
        return None


_JUNK = re.compile(r"(stock price|share price|price quote|\bquote\b|stock news|historical prices|"
                   r"stock chart|market cap|investor relations|financials?\s*$)", re.I)


def _is_junk(r: dict, name: str) -> bool:
    """Quote pages and home pages, which never explain a particular day's move."""
    title = str(r.get("title") or "").strip()
    return (not title) or bool(_JUNK.search(title)) or title.lower() == name.lower()


def _search_news(name: str, ticker: str, day: str, move: float, tavily_api_key: str = "",
                 tavily_search: Optional[Callable] = None) -> list:
    """News articles published around one date.
    Several searches are combined, because headlines rarely say "X shares rise on <date>":
      1. news search for the company name only, published day-1 .. day+1
      2. news search for "<name> shares/stock", published day-3 .. day+1
      3. general search with the month and year, if 1-2 found little
    Articles dated inside day-3 .. day+1 are ranked first."""
    import requests
    d = dt.date.fromisoformat(day)
    base = ticker.split(".")[0]
    word = "shares" if ticker.endswith(".L") else "stock"
    win = lambda lo, hi: {"start_date": (d + dt.timedelta(days=lo)).isoformat(),
                          "end_date": (d + dt.timedelta(days=hi)).isoformat()}
    searches = [
        (name, {"topic": "news", **win(-1, 1)}),
        (f"{name} {word} news", {"topic": "news", **win(-3, 1)}),
        (f"{name} ({base}) {word} {'rises' if move > 0 else 'falls'} {d.strftime('%B %Y')}", {"topic": "general"}),
    ]
    found, seen = [], set()

    def in_window(r):
        p = _pub_date(r)
        return None if p is None else -3 <= (p - d).days <= 1

    for k, (query, extra) in enumerate(searches):
        if k == 2 and sum(1 for r in found if in_window(r)) >= 2:
            break
        res = []
        if tavily_api_key:
            try:
                r = requests.post("https://api.tavily.com/search", timeout=15, json={
                    "api_key": tavily_api_key, "query": query, "max_results": 6,
                    "search_depth": "basic", "include_answer": False, **extra})
                if r.status_code == 200:
                    res = r.json().get("results", []) or []
                else:
                    print(f"[catalyst-atlas] tavily {r.status_code} for {ticker} {day}: {r.text[:160]}")
            except Exception as e:
                print(f"[catalyst-atlas] tavily error {ticker} {day}: {e}")
        elif tavily_search and k == 2:
            try:
                res = tavily_search(query, max_results=6) or []
            except Exception as e:
                print(f"[catalyst-atlas] tavily_search error {ticker} {day}: {e}")
        for x in res:
            u = x.get("url") or x.get("title")
            if u and u not in seen and not _is_junk(x, name):
                seen.add(u); found.append(x)
    dated = [r for r in found if in_window(r)]
    if dated:                       # articles from those days exist: use only them
        return dated[:6]
    return [r for r in found if in_window(r) is None][:4]   # otherwise undated items, flagged in the prompt


_QWORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "1st": 1, "2nd": 2, "3rd": 3, "4th": 4}


def _impossible_period(title: str, day: str) -> bool:
    """True if a label talks about results for a period that had not ended on that day,
    e.g. 'Q4 2025 results' on 10 June 2025."""
    d = dt.date.fromisoformat(day)
    s = title or ""
    for q, y in re.findall(r"\bQ([1-4])\s*(?:FY)?\s*'?(20\d\d|\d\d)\b", s, flags=re.I):
        y = int(y) + (2000 if len(y) == 2 else 0)
        if dt.date(y, 3 * int(q), 28) > d:
            return True
    for w, y in re.findall(r"\b(first|second|third|fourth|1st|2nd|3rd|4th)[- ]quarter (20\d\d)\b", s, flags=re.I):
        if dt.date(int(y), 3 * _QWORDS[w.lower()], 28) > d:
            return True
    for y in re.findall(r"\b(?:full[- ]year|annual|FY)\s*(20\d\d)\b", s, flags=re.I):
        if int(y) >= d.year:
            return True
    return False


def label_big_days(name: str, ticker: str, days: list, tavily_search: Optional[Callable],
                   anthropic_api_key: str, tavily_api_key: str = "") -> tuple:
    """days: [{"date": "YYYY-MM-DD", "move": -7.2}]
    Returns ({date: {"cat", "title", "src"}}, diagnostics)."""
    diag = {"days": len(days), "with_results": 0, "labelled": 0, "error": None}
    if not days:
        return {}, diag
    if not anthropic_api_key or not (tavily_api_key or tavily_search):
        diag["error"] = "missing ANTHROPIC_API_KEY or Tavily key"
        print(f"[catalyst-atlas] {ticker}: {diag['error']}")
        return {}, diag
    blocks = []
    for d in days:
        res = _search_news(name, ticker, d["date"], d["move"], tavily_api_key, tavily_search)
        if res:
            diag["with_results"] += 1
        diag.setdefault("samples", {})[d["date"]] = [
            f"{_pub_date(r) or '?'} {str(r.get('title',''))[:90]}" for r in res[:4]]
        snippets = " | ".join(
            f"[published {_pub_date(r) or 'DATE UNKNOWN'}] {r.get('title','')}: {str(r.get('content',''))[:400]}"
            for r in res[:6]) or "no articles found"
        blocks.append(f"DATE {d['date']} (company-specific move {d['move']:+.1f}%): {snippets}")

    out = {}
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_api_key)
    for k in range(0, len(blocks), 7):            # small batches: one failure can't wipe everything
        chunk = blocks[k:k + 7]
        prompt = (
            f"You are labelling large daily share-price moves for {name} ({ticker}).\n"
            "For each DATE, name the most likely cause of the move.\n"
            "Use the news snippets first. Each shows its publication date. Use stories published on that date, "
            "the day before, or the day after that are about this company, its industry or the price of what it "
            "sells (e.g. oil for energy companies). Pick the most likely cause of a move of that size and "
            "direction. Ignore stories that are clearly about other dates. Items marked DATE UNKNOWN are weak "
            "evidence: only use one if its text clearly refers to events of that exact date.\n"
            "If the snippets don't explain it but the cause is a widely reported event you are highly "
            "confident about, you may use it and set \"src\" to \"knowledge\".\n"
            "Otherwise use category \"Unexplained\". Never guess.\n"
            f"Allowed categories: {', '.join(NEWS_CATEGORIES)}.\n"
            "Category guide: 'Sales & delivery data' = the company's own sales, deliveries or user numbers; "
            "'Customer & industry demand' = news about customers' spending or demand in its industry "
            "(e.g. a big customer raising its budget); 'Competition' = rivals' products, pricing, market-share "
            "changes or customers building their own alternative; 'Market-wide news' = only when the whole "
            "stock market or a whole sector moved on general news; oil-price news belongs in 'Customer & industry demand' "
            "unless it is about the company itself.\n"
            "Reply with a JSON array only, one object per date: "
            "{\"date\":\"YYYY-MM-DD\",\"category\":\"...\",\"title\":\"plain-English cause, max 12 words\","
            "\"src\":\"news\" or \"knowledge\"}.\n\n" + "\n".join(chunk)
        )
        try:
            resp = client.messages.create(model=HAIKU_MODEL, max_tokens=2000,
                                          messages=[{"role": "user", "content": prompt}])
            text = "".join(getattr(b, "text", "") for b in resp.content)
            arr = json.loads(text[text.find("["): text.rfind("]") + 1])
        except Exception as e:
            diag["error"] = f"{type(e).__name__}: {str(e)[:200]}"
            print(f"[catalyst-atlas] {ticker} labelling batch failed: {diag['error']}")
            continue
        for o in arr:
            if not isinstance(o, dict) or not o.get("date"):
                continue
            cat = o.get("category") if o.get("category") in NEWS_CATEGORIES else "Unexplained"
            title = str(o.get("title") or "")[:90] or "Large company-specific move"
            day = str(o["date"])[:10]
            try:
                if _impossible_period(title, day):
                    cat, title = "Unexplained", "Large company-specific move (no clear news found)"
            except Exception:
                pass
            out[day] = {"cat": cat, "title": title, "src": o.get("src") or "news"}
            if cat != "Unexplained":
                diag["labelled"] += 1
    print(f"[catalyst-atlas] {ticker} labels: {diag}")
    return out, diag


# ─────────────────────────────────────────────────────────────────────────────
# Analysis (pure: no network)
# ─────────────────────────────────────────────────────────────────────────────
def _ols(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    b, *_ = np.linalg.lstsq(X, y, rcond=None)
    return b


def _decompose(r: np.ndarray, rm: np.ndarray, rs: Optional[np.ndarray], dr: Optional[np.ndarray]):
    """Rolling out-of-sample decomposition. Returns market, sector+rates, company parts and betas."""
    n = len(r)
    M = np.zeros(n); S = np.zeros(n); A = np.zeros(n); beta = np.full(n, np.nan)
    for t in range(1, n):
        if t < MIN_WINDOW:
            lo, hi = 1, min(n, 2 * MIN_WINDOW)      # warm-up: in-sample, flagged in method note
        else:
            lo, hi = max(1, t - WINDOW), t
        cols = [np.ones(hi - lo), rm[lo:hi]]
        bs = None
        if rs is not None:
            bs = _ols(rs[lo:hi], np.column_stack([np.ones(hi - lo), rm[lo:hi]]))
            cols.append(rs[lo:hi] - bs[0] - bs[1] * rm[lo:hi])
        if dr is not None:
            cols.append(dr[lo:hi])
        b = _ols(r[lo:hi], np.column_stack(cols))
        beta[t] = b[1]
        m = b[1] * rm[t]
        s = 0.0
        k = 2
        if rs is not None:
            s += b[k] * (rs[t] - bs[0] - bs[1] * rm[t]); k += 1
        if dr is not None:
            s += b[k] * dr[t]
        M[t], S[t] = m, s
        A[t] = r[t] - m - s
    return M, S, A, beta


def _zigzag(c: np.ndarray, th: float) -> list:
    piv, trend, cand = [0], 0, 0
    for i in range(1, len(c)):
        if trend == 0:
            if c[i] / c[0] - 1 >= th: trend, cand = 1, i
            elif c[i] / c[0] - 1 <= -th: trend, cand = -1, i
            continue
        if trend == 1:
            if c[i] > c[cand]: cand = i
            elif c[i] / c[cand] - 1 <= -th: piv.append(cand); trend, cand = -1, i
        else:
            if c[i] < c[cand]: cand = i
            elif c[i] / c[cand] - 1 >= th: piv.append(cand); trend, cand = 1, i
    piv.append(cand)
    if piv[-1] != len(c) - 1:
        piv.append(len(c) - 1)
    out = []
    for a, b in zip(piv, piv[1:]):
        if b > a and (not out or out[-1][1] == a):
            out.append((a, b))
    return out


def _pct(x: float) -> float:
    return 100.0 * (math.exp(x) - 1.0)


def _r(x, d=1):
    if x is None:
        return None
    x = float(x)
    if math.isnan(x) or math.isinf(x):
        return None
    return round(x, d) + 0.0


def _reaction_index(ts, dates: pd.DatetimeIndex) -> Optional[int]:
    """Earnings after ~12:00 New York time move the price the next session."""
    t = pd.Timestamp(ts)
    if t.tzinfo is not None:
        t = t.tz_convert("America/New_York")
    day = pd.Timestamp(t.date())
    after_close = t.hour >= 12
    pos = dates.searchsorted(day, side="right" if after_close else "left")
    return int(pos) if pos < len(dates) else None


def analyse(data: dict, labeler: Optional[Callable] = None, now: Optional[dt.datetime] = None) -> dict:
    ticker = data["ticker"]
    closes: pd.DataFrame = data["closes"].copy()
    closes = closes[closes[ticker].notna()].ffill()
    dates = closes.index
    c = closes[ticker].to_numpy(float)
    n = len(c)
    if n < 150:
        raise ValueError("Not enough price history (need about 7 months).")

    lr = lambda s: np.r_[0.0, np.diff(np.log(s))]
    r = lr(c)
    rm = lr(closes[data["market"]].to_numpy(float))
    rs = lr(closes[data["sector_etf"]].to_numpy(float)) if data.get("sector_etf") in closes else None
    dr = None
    if data.get("rates") in closes:
        dr = np.r_[0.0, np.diff(closes[data["rates"]].to_numpy(float))]
    M, S, A, beta = _decompose(r, rm, rs, dr)
    sd_a = float(np.std(A[1:]))
    vol = float(np.std(r[1:]) * math.sqrt(252))
    D = [d.strftime("%Y-%m-%d") for d in dates]

    # ── events: earnings ──────────────────────────────────────────────────────
    events = []
    next_earnings = None
    now = now or dt.datetime.utcnow()
    ed = data.get("earnings")
    used = set()
    if ed is not None and len(ed):
        for ts, row in ed.iterrows():
            act = row.get("Reported EPS"); est = row.get("EPS Estimate")
            t = pd.Timestamp(ts)
            t_naive = t.tz_convert("UTC").tz_localize(None) if t.tzinfo is not None else t
            if pd.isna(act):
                if t_naive > pd.Timestamp(now) and (next_earnings is None or t_naive < pd.Timestamp(next_earnings["when"])):
                    next_earnings = {"when": t_naive.isoformat(), "date": t_naive.strftime("%Y-%m-%d"),
                                     "eps_est": _r(est, 2) if not pd.isna(est) else None}
                continue
            i = _reaction_index(ts, dates)
            if i is None or i < 1 or i in used:
                continue
            surp = None
            if not pd.isna(est) and est not in (0, None):
                surp = (float(act) - float(est)) / abs(float(est)) * 100
            s = 0 if surp is None or abs(surp) < 1 else (1 if surp > 0 else -1)
            kind = {1: "Earnings beat", -1: "Earnings miss", 0: "Earnings in line"}[s]
            title = (f"Results: EPS {float(act):.2f} vs {float(est):.2f} expected ({surp:+.0f}%)"
                     if surp is not None else f"Results: EPS {float(act):.2f}")
            events.append({"i": i, "kind": kind, "cat": "Earnings", "s": s, "title": title})
            used.update({i - 1, i, i + 1})

    # ── events: biggest company-specific days (not near earnings) ─────────────
    cand = [i for i in range(1, n) if abs(A[i]) > 2.2 * sd_a and i not in used]
    cand = sorted(cand, key=lambda i: -abs(A[i]))[:14]
    big = [{"date": D[i], "move": round(_pct(A[i]), 1), "i": i} for i in sorted(cand)]
    # ── recent news: up to 3 smaller own-moves in the last month (~21 trading days) ─
    # These are labelled too (labels are cached for 30 days), but kept OUT of `events`
    # so the 3-year "how the price reacted after each type of news" stats are unchanged.
    big_i = {b["i"] for b in big}
    rec = [i for i in range(max(1, n - 21), n)
           if i not in used and i not in big_i and abs(A[i]) > 1.0 * sd_a]
    rec = sorted(rec, key=lambda i: -abs(A[i]))[:3]
    recent_days = [{"date": D[i], "move": round(_pct(A[i]), 1), "i": i} for i in sorted(rec)]
    sd_m = float(np.std(rm[1:]))
    mkt_label = "the FTSE 100" if data["market"] == "^FTSE" else "the S&P 500"
    auto = {}
    for b in big + recent_days:
        i = b["i"]
        if abs(rm[i]) > 2.5 * sd_m:   # a huge whole-market day: the "own move" is mostly beta noise
            more = abs(r[i]) > abs(M[i])
            auto[b["date"]] = {"cat": "Market-wide news", "src": "market",
                               "title": (f"Whole market moved {_pct(rm[i]):+.1f}% ({mkt_label}); shares moved "
                                         f"{'more' if more else 'less'} than usual")}
    to_search = [b for b in big + recent_days if b["date"] not in auto]
    labels = dict(auto)
    if labeler and to_search:
        labels.update(labeler(to_search) or {})
    for b in big:
        lab = labels.get(b["date"], {"cat": "Unexplained", "title": "Large company-specific move (no clear news found)"})
        events.append({"i": b["i"], "kind": lab["cat"], "cat": lab["cat"], "s": 1 if A[b["i"]] > 0 else -1,
                       "title": lab["title"], "src": lab.get("src", "news")})
    events.sort(key=lambda e: e["i"])

    # Recent news strip: the big/earnings events of the last month plus the smaller
    # recent days above, newest first (max 4).
    recent_news = [{"date": D[e["i"]], "cat": e["cat"], "title": e["title"], "src": e.get("src", "news"),
                    "own": _r(_pct(A[e["i"]])), "ret": _r(_pct(r[e["i"]])), "big": True}
                   for e in events if e["i"] >= n - 21]
    for b in recent_days:
        lab = labels.get(b["date"], {"cat": "Unexplained", "title": "No clear news found"})
        recent_news.append({"date": b["date"], "cat": lab["cat"], "title": lab["title"],
                            "src": lab.get("src", "news"), "own": _r(_pct(A[b["i"]])),
                            "ret": _r(_pct(r[b["i"]])), "big": False})
    recent_news = sorted(recent_news, key=lambda x: x["date"], reverse=True)[:4]

    def car(i, a, b):
        if i + a < 1 or i + b >= n:
            return None
        return _pct(float(np.sum(A[i + a: i + b + 1])))

    for e in events:
        i = e["i"]
        e.update({"date": D[i], "ret": _r(_pct(r[i])), "pre": _r(car(i, -5, -1)), "d0": _r(car(i, 0, 0)),
                  "d5": _r(car(i, 0, 4)), "d20": _r(car(i, 0, 19)), "d60": _r(car(i, 0, 59)),
                  "path": [_r(car(i, 0, k), 2) for k in range(0, 61)]})

    # ── catalyst scores ───────────────────────────────────────────────────────
    def score(evts, direction):
        """direction: +1/-1 fixed, or 0 = 'did the day-0 move stick' (same sign at +20)."""
        rows = []
        for e in evts:
            want = direction or (1 if (e["d0"] or 0) > 0 else -1)
            rows.append((e, want))
        def rate(key):
            v = [(e[key], w) for e, w in rows if e[key] is not None]
            h = sum(1 for x, w in v if (x > 0) == (w > 0))
            return {"hits": h, "n": len(v), "score": round((h + 1) / (len(v) + 2), 2)}
        avg = lambda key: _r(np.mean([e[key] for e, _ in rows if e[key] is not None])) if rows else None
        paths = [e["path"] for e, _ in rows if e["path"][20] is not None]
        avg_path, lo_path, hi_path = [], [], []
        for k in range(61):
            vals = [p[k] for p in paths if p[k] is not None]
            if len(vals) >= 2:
                avg_path.append(round(float(np.mean(vals)), 2))
                lo_path.append(round(float(np.min(vals)), 2)); hi_path.append(round(float(np.max(vals)), 2))
            else:
                avg_path.append(None); lo_path.append(None); hi_path.append(None)
        return {"day0": rate("d0"), "week": rate("d5"), "month": rate("d20"), "quarter": rate("d60"),
                "avg_day0": avg("d0"), "avg_month": avg("d20"), "avg_abs_day0": _r(np.mean([abs(e["d0"]) for e, _ in rows])) if rows else None,
                "avg_path": avg_path, "lo_path": lo_path, "hi_path": hi_path,
                "dates": [e["date"] for e, _ in rows]}

    groups = []
    eb = [e for e in events if e["kind"] == "Earnings beat"]
    em = [e for e in events if e["kind"] == "Earnings miss"]
    if len(eb) >= 2:
        groups.append({"name": "Earnings beat", "expects": "up", **score(eb, 1)})
    if len(em) >= 2:
        groups.append({"name": "Earnings miss", "expects": "down", **score(em, -1)})
    for cat in NEWS_CATEGORIES:
        ev = [e for e in events if e["cat"] == cat]
        if len(ev) >= 2:
            nm = "Big moves with no clear news" if cat == "Unexplained" else cat
            groups.append({"name": nm, "cat": cat, "expects": "stick", **score(ev, 0)})
    runups = [e for e in events if e["pre"] is not None and e["pre"] > 5]
    if len(runups) >= 3:
        groups.append({"name": "Price ran up 5%+ before the news", "expects": "down", **score(runups, -1)})

    # ── phases ────────────────────────────────────────────────────────────────
    th = {"weeks": max(0.05, 0.2 * vol), "months": max(0.10, 0.42 * vol), "year": max(0.18, 0.75 * vol)}
    phases = {}
    for lens, t in th.items():
        out = []
        for a, b in _zigzag(c, t):
            lt = math.log(c[b] / c[a]); chg = 100 * (c[b] / c[a] - 1)
            k = chg / (100 * lt) if lt else 1.0
            m = float(M[a + 1: b + 1].sum()); s = float(S[a + 1: b + 1].sum()); x = float(A[a + 1: b + 1].sum())
            evs = [e for e in events if a < e["i"] <= b]
            cat = float(sum(A[e["i"]] for e in evs))
            out.append({"a": a, "b": b, "chg": _r(chg), "days": b - a, "mkt": _r(100 * m * k), "sec": _r(100 * s * k),
                        "news": _r(100 * cat * k), "other": _r(100 * (x - cat) * k),
                        "events": [events.index(e) for e in evs]})
        phases[lens] = {"threshold": round(100 * t), "legs": out}

    # quiet spells
    rv = pd.Series(r).rolling(20).std() * math.sqrt(252)
    q = float(rv.quantile(0.35))
    quiet, start = [], None
    for i in range(20, n):
        ok = rv.iloc[i] < q and abs(c[i] / c[i - 19] - 1) < 0.07
        if ok:
            a = i - 19
            if quiet and a <= quiet[-1][1] + 1:
                quiet[-1][1] = i
            else:
                quiet.append([a, i])
    quiet = [qq for qq in quiet if qq[1] - qq[0] >= 18]

    # ── ranges ────────────────────────────────────────────────────────────────
    realized = float(np.std(r[-63:]) * math.sqrt(252))
    iv = data.get("iv")
    sigma, sigma_src = (iv, "options market") if iv else (realized, "recent price swings")
    P = float(c[-1])
    ranges = []
    for label, h in (("1 week", 5), ("1 month", 21), ("3 months", 63)):
        s_ = sigma * math.sqrt(h / 252)
        ranges.append({"label": label, "days": h,
                       "lo70": _r(P * math.exp(-1.036 * s_), 2), "hi70": _r(P * math.exp(1.036 * s_), 2),
                       "lo90": _r(P * math.exp(-1.645 * s_), 2), "hi90": _r(P * math.exp(1.645 * s_), 2)})

    # ── plain-English summary (templates, no AI) ──────────────────────────────
    name = data.get("name") or ticker
    b_now = float(np.nanmean(beta[-20:]))
    month_stock = 100 * (c[-1] / c[max(0, n - 22)] - 1)
    rmkt = closes[data["market"]].to_numpy(float)
    month_mkt = 100 * (rmkt[-1] / rmkt[max(0, n - 22)] - 1)
    month_own = _pct(float(A[max(1, n - 21):].sum()))
    mkt_name = "the FTSE 100" if data["market"] == "^FTSE" else "the US market (S&P 500)"
    leg = phases["months"]["legs"][-1]
    parts = sorted([("the overall market", leg["mkt"]), ("its sector and interest rates", leg["sec"]),
                    ("company news", leg["news"]), ("other buying and selling", leg["other"])],
                   key=lambda p: -abs(p[1] or 0))
    top = parts[0]
    recent = [e for e in events if e["i"] >= n - 21]
    biggest_recent = max(recent, key=lambda e: abs(e["d0"] or 0)) if recent else None
    summary = {
        "headline": (f"{name} is {'up' if month_stock >= 0 else 'down'} {abs(month_stock):.1f}% over the past month, "
                     f"while {mkt_name} " + ("was flat." if abs(month_mkt) < 0.25 else
                                             f"{'rose' if month_mkt >= 0 else 'fell'} {abs(month_mkt):.1f}%.")),
        "own_move": (f"After allowing for the market, the company's own news and trading moved it "
                     f"{'up' if month_own >= 0 else 'down'} about {abs(month_own):.1f}%."),
        "beta": (f"When {mkt_name} moves 1%, {name} has recently tended to move about {b_now:.1f}%."),
        "phase": (f"Since {dates[leg['a']].strftime('%d %b %Y')} the shares are "
                  f"{'up' if leg['chg'] >= 0 else 'down'} {abs(leg['chg']):.1f}%. "
                  f"The biggest driver was {top[0]} ({top[1]:+.1f} points)."),
        "recent_news": (f"Biggest recent news day: {biggest_recent['date']}, {biggest_recent['title']} "
                        f"({biggest_recent['d0']:+.1f}% after allowing for the market).") if biggest_recent else None,
    }

    # coming up
    upcoming = []
    if next_earnings:
        days_to = (pd.Timestamp(next_earnings["date"]) - pd.Timestamp(now.date())).days
        er = [e for e in events if e["cat"] == "Earnings"]
        avg_abs = _r(np.mean([abs(e["ret"]) for e in er])) if er else None
        run5 = _pct(float(A[-5:].sum()))
        upcoming.append({"type": "Earnings", "date": next_earnings["date"], "days": days_to,
                         "eps_est": next_earnings.get("eps_est"), "avg_abs_move": avg_abs,
                         "n_past": len(er), "runup5": _r(run5),
                         "runup_flag": run5 > 5})

    # price change at a glance: last week / month / quarter / year (actual price)
    periods = []
    simple = np.r_[0.0, c[1:] / c[:-1] - 1]
    for label, h in (("Last week", 5), ("Last month", 21), ("Last quarter", 63), ("Last year", 252)):
        if n > h:
            seg = simple[n - h:]
            periods.append({"label": label, "days": h, "total": _r(100 * (c[-1] / c[n - 1 - h] - 1)),
                            "avg_daily": _r(100 * float(np.mean(seg)), 2),
                            "typical_swing": _r(100 * float(np.mean(np.abs(seg))), 2),
                            "up_days": int(np.sum(seg > 0)), "down_days": int(np.sum(seg < 0))})
    # what drives the daily moves over the last year (share of day-to-day ups and downs)
    w = slice(max(1, n - 252), n)
    vm, vs, va = float(np.var(M[w])), float(np.var(S[w])), float(np.var(A[w]))
    tot = (vm + vs + va) or 1.0
    driver_share = {"market": round(100 * vm / tot), "sector": round(100 * vs / tot), "own": round(100 * va / tot)}

    def enc(arr, k=10000):
        return [int(round(float(v) * k)) for v in arr]

    return {
        "version": VERSION, "ticker": ticker, "name": name, "sector": data.get("sector"),
        "currency": data.get("currency"), "market": data["market"], "sector_etf": data.get("sector_etf"),
        "rates": data.get("rates") if data.get("rates") in closes else None,
        "asof": D[-1], "price": _r(P, 2), "vol": _r(100 * vol), "sd_own_day": _r(100 * sd_a, 2),
        "beta_now": _r(b_now, 2), "beta_avg": _r(float(np.nanmean(beta[1:])), 2),
        "summary": summary, "ranges": ranges, "sigma": _r(100 * sigma), "sigma_src": sigma_src,
        "upcoming": upcoming,
        "events": [{k: e[k] for k in ("date", "kind", "cat", "s", "title", "src", "ret", "pre", "d0", "d5", "d20", "d60", "path") if k in e} for e in events],
        "groups": groups, "phases": phases, "quiet": quiet,
        "series": {"dates": D, "close": [round(float(x), 2) for x in c], "own": enc(A), "mkt": enc(M), "sec": enc(S)},
        "recent_news": recent_news,
        "generated": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "periods": periods, "driver_share": driver_share, "market_vol": _r(100 * float(np.std(rm[1:]) * math.sqrt(252))),
        "disclaimer": "Educational research only. Past patterns do not guarantee future results. Not financial advice.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Fintiq Analyst's view: plain-English summary written by Claude from the page's
# own figures only. No buy/sell/hold, no price targets.
# ─────────────────────────────────────────────────────────────────────────────
def _view_facts(res: dict) -> dict:
    pence = res.get("currency") in ("GBp", "GBX", "GBx")
    k = 0.01 if pence else 1.0
    sym = "£" if (pence or res.get("currency") == "GBP") else ("$" if res.get("currency") == "USD" else "")
    money = lambda v: None if v is None else f"{sym}{v * k:,.2f}"
    unit = sym or "£"
    s = res["series"]; d, c = s["dates"], s["close"]
    sector_word = ("the oil price" if res.get("sector_etf") == "BZ=F"
                   else ("its sector and interest rates" if res.get("sector_etf") else "its sector"))
    mkt = "the FTSE 100" if res.get("market") == "^FTSE" else "the US stock market (S&P 500)"
    legs = []
    for lens in ("year", "months"):
        for l in res["phases"][lens]["legs"][-3:]:
            legs.append({"scale": lens, "from": d[l["a"]], "to": d[l["b"]], "change_pct": l["chg"],
                         "parts_pct_points": {"market": l["mkt"], sector_word: l["sec"],
                                              "company_news_days": l["news"], "other_trading": l["other"]}})
    groups = [{"news_type": g["name"], "examples": g["day0"]["n"], "what_counts_as_success": g["expects"],
               "worked_on_day0": f'{g["day0"]["hits"]} of {g["day0"]["n"]}',
               "still_true_after_1_month": f'{g["month"]["hits"]} of {g["month"]["n"]}',
               "avg_own_move_day0_pct": g["avg_day0"], "avg_own_move_after_1_month_pct": g["avg_month"],
               "typical_size_day0_pct": g.get("avg_abs_day0")} for g in res["groups"]]
    ranges = [{"horizon": r["label"],
               "seven_in_ten_price": f'{money(r["lo70"])} to {money(r["hi70"])}',
               "one_in_ten_below": money(r["lo90"]), "one_in_ten_above": money(r["hi90"]),
               f"{unit}1,000_invested_becomes_7_in_10": f'{unit}{1000 * r["lo70"] / res["price"]:,.0f} to {unit}{1000 * r["hi70"] / res["price"]:,.0f}',
               f"{unit}1,000_invested_1_in_10_below": f'{unit}{1000 * r["lo90"] / res["price"]:,.0f}'} for r in res["ranges"]]
    recent = [{"date": e["date"], "type": e["kind"], "what": e["title"], "actual_move_pct": e["ret"],
               "own_move_pct": e["d0"]} for e in res["events"][-8:]]
    return {
        "company": res["name"], "ticker": res["ticker"], "price_now": money(res["price"]), "as_of": res["asof"],
        "price_3y_ago": money(c[0]), "date_3y_ago": d[0], "change_since_pct": round(100 * (c[-1] / c[0] - 1), 1),
        "market_used": mkt, "other_factor_taken_out": sector_word,
        "beta_now": res["beta_now"], "beta_3y_avg": res["beta_avg"],
        "share_of_daily_moves_last_year_pct": {"market": res["driver_share"]["market"],
                                               sector_word: res["driver_share"]["sector"],
                                               "company_own": res["driver_share"]["own"]},
        "yearly_volatility_pct": res["vol"], "market_yearly_volatility_pct": res.get("market_vol"),
        "price_change_by_period": res.get("periods"),
        "phases": legs, "news_patterns": groups, "recent_news_days": recent,
        "news_in_the_last_month": res.get("recent_news"),
        "likely_ranges_from_recent_swings": ranges,
        "next_results": (res["upcoming"][0] if res.get("upcoming") else None),
    }


def analyst_view(res: dict, anthropic_api_key: str) -> Optional[dict]:
    if not anthropic_api_key:
        return None
    facts = _view_facts(res)
    prompt = (
        "You are a senior equity analyst writing for Fintiq, a UK investing education site. Write the "
        "'Fintiq Analyst's view' of this share for someone with savings but no finance background.\n\n"
        "Rules:\n"
        "- Use ONLY the facts in the JSON below. Do not add news, forecasts, opinions about the company's "
        "future, or anything you know from elsewhere.\n"
        "- Never say buy, sell, hold, cheap, expensive, undervalued, a good investment, or give a price target. "
        "Never tell the reader what to do.\n"
        "- Plain British English. Short sentences. No jargon: never write beta, volatility, alpha, catalyst or "
        "abnormal return. Say 'the overall stock market' rather than an index code.\n"
        "- Use the money amounts exactly as given (already in the right currency). Round percentages sensibly.\n"
        "- Explain counts in everyday words, e.g. 'a month later it had beaten the overall market only 4 times "
        "out of 9, close to a coin toss' or 'the move was still there a month later in 6 of 6 cases, so this kind "
        "of news had a lasting effect'.\n"
        "- If a pattern has fewer than 4 examples, say the evidence is thin.\n"
        "- 170 to 260 words in total.\n\n"
        "Reply with JSON only, with these keys, each 1-3 sentences:\n"
        "{\"story\": the share's journey in plain words,\n"
        " \"drivers\": what really moves it day to day, using share_of_daily_moves_last_year_pct and phases,\n"
        " \"news\": how it has reacted to results and other news, and whether reactions lasted,\n"
        " \"swing\": how much it typically moves, compared with the overall market, including the £1,000 example "
        "for 3 months (use the currency shown in the facts),\n"
        " \"coming_up\": the next known event and what usually happens,\n"
        " \"questions\": [three short questions a person should ask themselves before investing]}\n\n"
        "FACTS:\n" + json.dumps(facts, default=str)
    )
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_api_key)
        resp = client.messages.create(model=SONNET_MODEL, max_tokens=1500,
                                      messages=[{"role": "user", "content": prompt}])
        text = "".join(getattr(b, "text", "") for b in resp.content)
        v = json.loads(text[text.find("{"): text.rfind("}") + 1])
    except Exception as e:
        print(f"[catalyst-atlas] analyst view failed for {res.get('ticker')}: {type(e).__name__}: {str(e)[:200]}")
        return None
    banned = re.compile(r"\b(you should|we recommend|i recommend|price target|undervalued|overvalued|"
                        r"good investment|time to (?:buy|sell)|(?:buy|sell|hold) rating)\b|\b(?:buy|sell)\b(?!-off| off)", re.I)
    out = {}
    for key in ("story", "drivers", "news", "swing", "coming_up"):
        val = str(v.get(key) or "").strip()
        if banned.search(val):
            print(f"[catalyst-atlas] analyst view rejected ({key}) for {res.get('ticker')}")
            return None
        out[key] = val
    out["questions"] = [str(q).strip() for q in (v.get("questions") or [])][:3]
    if not out["story"]:
        return None
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Entry point used by the API route
# ─────────────────────────────────────────────────────────────────────────────
def build_atlas(ticker: str, kv_get=None, kv_set=None, tavily_search=None,
                anthropic_api_key: str = "", tavily_api_key: str = "", fetch=fetch_market_data,
                cache_ttl: int = CACHE_TTL) -> dict:
    ticker = (ticker or "").upper().strip()
    if not TICKER_RE.match(ticker):
        raise ValueError("Please enter a valid ticker, for example TSLA or SHEL.L")

    key = f"catalyst_atlas:{VERSION}:{ticker}"
    if kv_get:
        cached, saved_at = kv_get(key)
        ttl = cached.get("_ttl", CACHE_TTL) if isinstance(cached, dict) else CACHE_TTL
        if cached and time.time() - saved_at < ttl:
            return cached

    data = fetch(ticker)
    if data["closes"] is None or ticker not in data["closes"] or data["closes"][ticker].dropna().empty:
        raise ValueError(f"No price history found for {ticker}")

    label_key = f"catalyst_atlas_labels:{VERSION}:{ticker}"
    old_labels = {}
    if kv_get:
        got, _ = kv_get(label_key)
        old_labels = got or {}
    diag_box = {"diag": {"days": 0, "with_results": 0, "labelled": 0, "error": None, "from_cache": 0}}

    def labeler(big_days):
        need = [d for d in big_days if d["date"] not in old_labels]
        diag_box["diag"]["from_cache"] = len(big_days) - len(need)
        new, diag = (label_big_days(data["name"], ticker, need, tavily_search, anthropic_api_key, tavily_api_key)
                     if need else ({}, {"days": 0, "with_results": 0, "labelled": 0, "error": None}))
        diag_box["diag"].update(diag)
        merged = {**old_labels, **new}
        healthy = not diag.get("error") and (not need or diag.get("with_results", 0) > 0)
        if kv_set and new and healthy:          # never store a failed labelling run
            kv_set(label_key, merged, ttl_seconds=LABEL_TTL)
        return merged

    result = analyse(data, labeler=labeler)
    d = diag_box["diag"]
    result["label_diag"] = d
    result["analyst_view"] = analyst_view(result, anthropic_api_key)
    failed = bool(d.get("error")) or (d.get("days", 0) > 0 and d.get("with_results", 0) == 0)
    result["_ttl"] = 3600 if failed else cache_ttl   # retry within an hour if news lookup failed
    result["built_at"] = int(time.time())            # shown on the page as "Updated ..."
    if kv_set:
        kv_set(key, result, ttl_seconds=result["_ttl"])
    return result
