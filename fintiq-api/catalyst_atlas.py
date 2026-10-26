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

VERSION = "v1"
CACHE_TTL = 12 * 3600          # full result
LABEL_TTL = 30 * 24 * 3600     # news labels for past days rarely change
HAIKU_MODEL = "claude-haiku-4-5-20251001"
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
    "Management & leadership", "Politics & policy", "Market-wide news",
    "Unexplained",
]

WINDOW = 250
MIN_WINDOW = 60


# ─────────────────────────────────────────────────────────────────────────────
# Data fetching (yfinance). Kept separate so the analysis can be tested offline.
# ─────────────────────────────────────────────────────────────────────────────
def fetch_market_data(ticker: str, period: str = "3y") -> dict:
    import yfinance as yf

    tk = yf.Ticker(ticker)
    info = {}
    try:
        info = tk.get_info() or {}
    except Exception:
        pass
    uk = ticker.endswith(".L")
    name = info.get("shortName") or info.get("longName") or ticker
    sector_name = info.get("sector")
    market = "^FTSE" if uk else "SPY"
    sector = None if uk else SECTOR_ETF.get(sector_name or "")
    rates = None if uk else "^TNX"

    syms = [s for s in [ticker, market, sector, rates] if s]
    raw = yf.download(syms, period=period, interval="1d", auto_adjust=True,
                      progress=False, threads=True)
    closes = raw["Close"] if isinstance(raw.columns, pd.MultiIndex) else raw[["Close"]].rename(columns={"Close": ticker})
    closes.index = pd.to_datetime(closes.index).tz_localize(None)
    if sector and (sector not in closes or closes[sector].dropna().shape[0] < 200):
        fb = SECTOR_ETF_FALLBACK.get(sector)
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
def label_big_days(name: str, ticker: str, days: list, tavily_search: Optional[Callable],
                   anthropic_api_key: str) -> dict:
    """days: [{"date": "YYYY-MM-DD", "move": -7.2}] -> {date: {"cat":..., "title":...}}"""
    if not days or not tavily_search or not anthropic_api_key:
        return {}
    blocks = []
    for d in days:
        human = dt.date.fromisoformat(d["date"]).strftime("%d %B %Y")
        verb = "rose" if d["move"] > 0 else "fell"
        res = tavily_search(f"why {name} ({ticker}) stock {verb} on {human}", max_results=3) or []
        snippets = " | ".join(
            f"{r.get('title','')}: {str(r.get('content',''))[:280]}" for r in res[:3]
        ) or "no results"
        blocks.append(f"DATE {d['date']} (company-specific move {d['move']:+.1f}%): {snippets}")

    prompt = (
        f"You are labelling large daily share-price moves for {name} ({ticker}).\n"
        "For each DATE, use ONLY the news snippets given to name the most likely cause.\n"
        "If the snippets do not clearly explain that date, use category \"Unexplained\".\n"
        f"Allowed categories: {', '.join(NEWS_CATEGORIES)}.\n"
        "Reply with a JSON array only, one object per date: "
        "{\"date\":\"YYYY-MM-DD\",\"category\":\"...\",\"title\":\"plain-English cause, max 12 words\"}.\n\n"
        + "\n".join(blocks)
    )
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=anthropic_api_key)
        resp = client.messages.create(model=HAIKU_MODEL, max_tokens=1500, temperature=0,
                                      messages=[{"role": "user", "content": prompt}])
        text = resp.content[0].text
        arr = json.loads(text[text.find("["): text.rfind("]") + 1])
    except Exception:
        return {}
    out = {}
    for o in arr:
        cat = o.get("category") if o.get("category") in NEWS_CATEGORIES else "Unexplained"
        title = str(o.get("title") or "")[:90]
        if o.get("date"):
            out[o["date"]] = {"cat": cat, "title": title or "Large company-specific move"}
    return out


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
    labels = labeler(big) if (labeler and big) else {}
    for b in big:
        lab = labels.get(b["date"], {"cat": "Unexplained", "title": "Large company-specific move (no clear news found)"})
        events.append({"i": b["i"], "kind": lab["cat"], "cat": lab["cat"], "s": 1 if A[b["i"]] > 0 else -1,
                       "title": lab["title"]})
    events.sort(key=lambda e: e["i"])

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

    def enc(arr, k=10000):
        return [int(round(float(v) * k)) for v in arr]

    return {
        "version": VERSION, "ticker": ticker, "name": name, "sector": data.get("sector"),
        "currency": data.get("currency"), "market": data["market"], "sector_etf": data.get("sector_etf"),
        "asof": D[-1], "price": _r(P, 2), "vol": _r(100 * vol), "sd_own_day": _r(100 * sd_a, 2),
        "beta_now": _r(b_now, 2), "beta_avg": _r(float(np.nanmean(beta[1:])), 2),
        "summary": summary, "ranges": ranges, "sigma": _r(100 * sigma), "sigma_src": sigma_src,
        "upcoming": upcoming,
        "events": [{k: e[k] for k in ("date", "kind", "cat", "s", "title", "ret", "pre", "d0", "d5", "d20", "d60", "path")} for e in events],
        "groups": groups, "phases": phases, "quiet": quiet,
        "series": {"dates": D, "close": [round(float(x), 2) for x in c], "own": enc(A), "mkt": enc(M), "sec": enc(S)},
        "generated": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "disclaimer": "Educational research only. Past patterns do not guarantee future results. Not financial advice.",
    }


# ─────────────────────────────────────────────────────────────────────────────
# Entry point used by the API route
# ─────────────────────────────────────────────────────────────────────────────
def build_atlas(ticker: str, kv_get=None, kv_set=None, tavily_search=None,
                anthropic_api_key: str = "", fetch=fetch_market_data) -> dict:
    ticker = (ticker or "").upper().strip()
    if not TICKER_RE.match(ticker):
        raise ValueError("Please enter a valid ticker, for example TSLA or SHEL.L")

    key = f"catalyst_atlas:{VERSION}:{ticker}"
    if kv_get:
        cached, saved_at = kv_get(key)
        if cached and time.time() - saved_at < CACHE_TTL:
            return cached

    data = fetch(ticker)
    if data["closes"] is None or ticker not in data["closes"] or data["closes"][ticker].dropna().empty:
        raise ValueError(f"No price history found for {ticker}")

    label_key = f"catalyst_atlas_labels:{VERSION}:{ticker}"
    old_labels = {}
    if kv_get:
        got, _ = kv_get(label_key)
        old_labels = got or {}

    def labeler(big_days):
        need = [d for d in big_days if d["date"] not in old_labels]
        new = label_big_days(data["name"], ticker, need, tavily_search, anthropic_api_key) if need else {}
        merged = {**old_labels, **new}
        if kv_set and new:
            kv_set(label_key, merged, ttl_seconds=LABEL_TTL)
        return merged

    result = analyse(data, labeler=labeler)
    if kv_set:
        kv_set(key, result, ttl_seconds=CACHE_TTL)
    return result
