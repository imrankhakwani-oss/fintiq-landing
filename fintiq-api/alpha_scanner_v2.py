"""
Alpha Scanner v2 — rules-first turnaround screen for US small caps.

What changed from v1 (see Finding Alpha project, Nov 2026):
  * Fixed, testable rules make every decision. Claude only writes the plain-English
    explanation, under a daily cap, for companies that already passed the rules.
  * A company is re-scored when it files a new 10-K / 10-Q (EDGAR daily index), so
    scoring is same-day and costs nothing; AI spend is capped by AS2_AI_DAILY_CAP.
  * Banks, insurers, lenders, BDCs and REITs (SIC 6000-6799) are excluded: the
    accounting scores used here are not valid for them.
  * Standard Piotroski F-score, Altman Z (market value; Z'' for non-manufacturers)
    and Beneish M-score.
  * Every signal is kept and its return measured at 3/6/12/24 months against IWM,
    so the scanner builds a public track record. Signals close after 24 months,
    never because the price moved.

Rules (backtested on 2018-2023 SEC data, see /alpha-scanner/v2/method):
  Gate 1  Eligible : US filer, non-financial SIC, revenue >= $50m, 3+ years of
                     revenue history, market cap $50m-$2bn.
  Gate 2  Struggling: net loss this year or last, or operating margin < 3%.
  Gate 3  Setup    : price <= 50% of its 3-year high, AND
                     S1 (operating cash flow > 0 while net income < 0) OR
                     S3 (revenue down, gross profit up).
  Gate 4  Quality  : configurable (AS2_MIN_PIOTROSKI, AS2_MIN_ALTMAN,
                     AS2_MAX_BENEISH) — set from the backtest.
  Boosters (shown, counted, not required): S2 margin up on flat revenue,
  S4 operating margin +3 pts, S5 debt cut 15%+, S6 deposits / order book +50%.

Educational research screen only. Not investment advice.
"""
from __future__ import annotations

import json
import math
import os
import sqlite3
import time
from datetime import date, datetime, timedelta, timezone

import requests

# ── Configuration (override with environment variables) ─────────────────────
def _envf(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default

MIN_MCAP        = _envf("AS2_MIN_MCAP", 50e6)
MAX_MCAP        = _envf("AS2_MAX_MCAP", 2e9)
MIN_REVENUE     = _envf("AS2_MIN_REVENUE", 50e6)
MAX_PRICE_VS_HI = _envf("AS2_MAX_PRICE_VS_HIGH", 0.50)
MIN_PIOTROSKI   = _envf("AS2_MIN_PIOTROSKI", 0)      # 0 = gate off
MIN_ALTMAN      = _envf("AS2_MIN_ALTMAN", -1e9)      # -1e9 = gate off
MAX_BENEISH     = _envf("AS2_MAX_BENEISH", 1e9)      # 1e9 = gate off
AI_DAILY_CAP    = int(_envf("AS2_AI_DAILY_CAP", 30))
TRACK_MONTHS    = (3, 6, 12, 24)
SEC_UA          = os.environ.get("SEC_USER_AGENT", "Fintiq research contactfintiq@gmail.com")

_DB = "/data/alpha_scanner.db" if os.path.isdir("/data") else "/tmp/alpha_scanner.db"

BOOSTER_LABELS = {
    "S1": "Cash beats earnings: operating cash flow positive despite a net loss",
    "S2": "Gross margin up 3+ pts over two years on flat revenue",
    "S3": "Shrink to grow: revenue down, gross profit up",
    "S4": "Operating margin up 3+ pts in a year",
    "S5": "Long-term debt cut by 15% or more",
    "S6": "Customer deposits / order book up 50% or more",
}

# ── Storage ──────────────────────────────────────────────────────────────────
def db() -> sqlite3.Connection:
    conn = sqlite3.connect(_DB)
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS as2_signals (
        id TEXT PRIMARY KEY,            -- ticker:fiscal_year_end
        ticker TEXT, cik TEXT, name TEXT, sic INTEGER, sector TEXT,
        fiscal_year_end TEXT, filing_accn TEXT,
        status TEXT DEFAULT 'active',   -- active | closed
        first_seen TEXT, last_scored TEXT,
        price_at_signal REAL, iwm_at_signal REAL, market_cap REAL,
        price_vs_3y_high REAL,
        reasons TEXT,                   -- JSON list of codes, e.g. ["S1","S5"]
        scores TEXT,                    -- JSON: piotroski, altman_z, beneish_m, ...
        metrics TEXT,                   -- JSON: revenue, margins, cash flow ...
        explanation TEXT, explained_at TEXT,
        closed_at TEXT, close_reason TEXT
    );
    CREATE TABLE IF NOT EXISTS as2_perf (
        signal_id TEXT, months INTEGER, measured_at TEXT,
        price REAL, ret REAL, iwm_ret REAL,
        PRIMARY KEY (signal_id, months)
    );
    CREATE TABLE IF NOT EXISTS as2_company (
        cik TEXT PRIMARY KEY, ticker TEXT, name TEXT, sic INTEGER, updated TEXT
    );
    CREATE TABLE IF NOT EXISTS as2_meta (k TEXT PRIMARY KEY, v TEXT);
    """)
    return conn

def _meta_get(conn, k, default=None):
    r = conn.execute("SELECT v FROM as2_meta WHERE k=?", (k,)).fetchone()
    return r["v"] if r else default

def _meta_set(conn, k, v):
    conn.execute("INSERT INTO as2_meta(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v", (k, str(v)))

# ── SEC helpers ──────────────────────────────────────────────────────────────
_last_sec_call = [0.0]

def _sec_get(url: str, as_json: bool = True):
    """SEC allows ~10 requests/second; stay well under it."""
    wait = 0.15 - (time.time() - _last_sec_call[0])
    if wait > 0:
        time.sleep(wait)
    for attempt in range(3):
        _last_sec_call[0] = time.time()
        r = requests.get(url, timeout=30, headers={"User-Agent": SEC_UA})
        if r.status_code == 200:
            return r.json() if as_json else r.text
        if r.status_code == 404:
            return None
        time.sleep(5 * (attempt + 1))  # 429/5xx back-off
    return None

_ticker_map = {"t": 0, "by_cik": {}}

def ticker_for_cik(cik: int) -> str | None:
    if time.time() - _ticker_map["t"] > 86400:
        data = _sec_get("https://www.sec.gov/files/company_tickers.json") or {}
        m = {}
        for row in data.values():
            m.setdefault(int(row["cik_str"]), row["ticker"])
        _ticker_map.update(t=time.time(), by_cik=m)
    return _ticker_map["by_cik"].get(int(cik))

def company_profile(conn, cik: int) -> dict:
    row = conn.execute("SELECT * FROM as2_company WHERE cik=?", (str(cik),)).fetchone()
    if row and row["updated"] and row["updated"] > (datetime.now(timezone.utc) - timedelta(days=30)).isoformat():
        return dict(row)
    sub = _sec_get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json") or {}
    prof = {"cik": str(cik), "ticker": ticker_for_cik(cik), "name": sub.get("name", ""),
            "sic": int(sub["sic"]) if str(sub.get("sic", "")).isdigit() else None,
            "updated": datetime.now(timezone.utc).isoformat()}
    conn.execute("""INSERT INTO as2_company(cik,ticker,name,sic,updated) VALUES(:cik,:ticker,:name,:sic,:updated)
                    ON CONFLICT(cik) DO UPDATE SET ticker=excluded.ticker,name=excluded.name,sic=excluded.sic,updated=excluded.updated""", prof)
    return prof

def new_filers(since: date, until: date) -> list[tuple[int, str, str]]:
    """CIKs that filed a 10-K or 10-Q between two dates, from EDGAR's daily form index."""
    out = []
    d = since
    while d <= until:
        q = (d.month - 1) // 3 + 1
        url = f"https://www.sec.gov/Archives/edgar/daily-index/{d.year}/QTR{q}/form.{d:%Y%m%d}.idx"
        text = _sec_get(url, as_json=False) if d.weekday() < 5 else None
        for line in (text or "").splitlines():
            form = line[:12].strip()
            if form in ("10-K", "10-K/A", "10-Q", "10-KT"):
                parts = line.split()
                # line: FORM  COMPANY NAME ...  CIK  DATE  FILENAME
                try:
                    cik = int(parts[-3]); out.append((cik, form, parts[-1]))
                except (ValueError, IndexError):
                    pass
        d += timedelta(days=1)
    seen, uniq = set(), []
    for cik, form, fn in out:
        if cik not in seen:
            seen.add(cik); uniq.append((cik, form, fn))
    return uniq

# ── Annual figures from SEC company facts ────────────────────────────────────
CONCEPTS = {
    "rev":  ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
             "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet"],
    "gp":   ["GrossProfit"],
    "cogs": ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold"],
    "oi":   ["OperatingIncomeLoss"],
    "ni":   ["NetIncomeLoss"],
    "ocf":  ["NetCashProvidedByUsedInOperatingActivities"],
    "ta":   ["Assets"], "ca": ["AssetsCurrent"], "cl": ["LiabilitiesCurrent"],
    "tl":   ["Liabilities"], "re": ["RetainedEarningsAccumulatedDeficit"],
    "bv":   ["StockholdersEquity"], "ar": ["AccountsReceivableNetCurrent"],
    "sga":  ["SellingGeneralAndAdministrativeExpense"],
    "dep":  ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization"],
    "debt": ["LongTermDebtNoncurrent", "LongTermDebt"],
    "dem":  ["ContractWithCustomerLiability", "RevenueRemainingPerformanceObligation"],
    "sh":   ["WeightedAverageNumberOfDilutedSharesOutstanding", "WeightedAverageNumberOfSharesOutstandingBasic"],
}

def annual_figures(facts: dict) -> list[dict]:
    """Last 4 fiscal years, newest first: [{'end': '2025-12-31', 'rev': .., ...}]."""
    gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    years: dict[str, dict] = {}
    for key, names in CONCEPTS.items():
        for name in names:
            units = gaap.get(name, {}).get("units", {})
            arr = units.get("USD") or units.get("shares")
            if not arr:
                continue
            best = {}
            for e in arr:
                if not str(e.get("form", "")).startswith("10-K"):
                    continue
                if e.get("start"):
                    days = (date.fromisoformat(e["end"]) - date.fromisoformat(e["start"])).days
                    if days < 350 or days > 380:
                        continue
                if e["end"] not in best or e["filed"] > best[e["end"]]["filed"]:
                    best[e["end"]] = e
            if best:
                for end, e in best.items():
                    years.setdefault(end, {"end": end, "accn": e.get("accn")})
                    years[end].setdefault(key, e["val"])
                break  # first concept name that has data wins
    rows = sorted(years.values(), key=lambda r: r["end"], reverse=True)
    # keep fiscal-year ends only (those that have revenue or net income)
    rows = [r for r in rows if r.get("rev") is not None or r.get("ni") is not None]
    for r in rows:
        if r.get("gp") is None and r.get("rev") is not None and r.get("cogs") is not None:
            r["gp"] = r["rev"] - r["cogs"]
    return rows[:4]

# ── Scores ───────────────────────────────────────────────────────────────────
def _d(a, b):
    try:
        return None if a is None or b in (None, 0) else a / b
    except Exception:
        return None

def piotroski(v: dict, p: dict) -> int | None:
    """Standard Piotroski (2000) F-score, 0-9."""
    if v.get("ta") is None or v.get("ni") is None or not p:
        return None
    roa, roa_p = _d(v.get("ni"), v.get("ta")), _d(p.get("ni"), p.get("ta"))
    lev, lev_p = _d(v.get("debt") or 0, v.get("ta")), _d(p.get("debt") or 0, p.get("ta"))
    cr, cr_p = _d(v.get("ca"), v.get("cl")), _d(p.get("ca"), p.get("cl"))
    gm, gm_p = _d(v.get("gp"), v.get("rev")), _d(p.get("gp"), p.get("rev"))
    at, at_p = _d(v.get("rev"), v.get("ta")), _d(p.get("rev"), p.get("ta"))
    tests = [
        roa is not None and roa > 0,
        (v.get("ocf") or 0) > 0,
        roa is not None and roa_p is not None and roa > roa_p,
        v.get("ocf") is not None and v["ocf"] > v["ni"],
        lev is not None and lev_p is not None and lev <= lev_p,
        cr is not None and cr_p is not None and cr > cr_p,
        v.get("sh") is not None and p.get("sh") is not None and v["sh"] <= p["sh"],
        gm is not None and gm_p is not None and gm > gm_p,
        at is not None and at_p is not None and at > at_p,
    ]
    return sum(bool(t) for t in tests)

def altman_z(v: dict, market_cap: float | None, sic: int | None) -> float | None:
    """Original Z (market value) for manufacturers (SIC 2000-3999), Z'' otherwise."""
    ta, tl = v.get("ta"), v.get("tl")
    if not ta or not tl or ta <= 0 or tl <= 0:
        return None
    if None in (v.get("ca"), v.get("cl"), v.get("re"), v.get("oi")):
        return None
    wc = v["ca"] - v["cl"]
    if sic and 2000 <= sic <= 3999 and market_cap:
        return 1.2*wc/ta + 1.4*v["re"]/ta + 3.3*v["oi"]/ta + 0.6*market_cap/tl + (v.get("rev") or 0)/ta
    if v.get("bv") is None:
        return None
    return 6.56*wc/ta + 3.26*v["re"]/ta + 6.72*v["oi"]/ta + 1.05*v["bv"]/tl

def beneish_m(v: dict, p: dict) -> float | None:
    """Beneish (1999) 8-variable M-score. Above -1.78 = possible earnings manipulation."""
    if not p:
        return None
    dsri = _d(_d(v.get("ar"), v.get("rev")), _d(p.get("ar"), p.get("rev")))
    gmi = _d(_d(p.get("gp"), p.get("rev")), _d(v.get("gp"), v.get("rev")))
    nca = lambda x: (x["ta"] - x["ca"]) if x.get("ta") is not None and x.get("ca") is not None else None
    aqi = _d(_d(nca(v), v.get("ta")), _d(nca(p), p.get("ta")))
    sgi = _d(v.get("rev"), p.get("rev"))
    dep = lambda x: _d(x.get("dep"), (x.get("dep") or 0) + (x.get("ta") or 0))
    depi = _d(dep(p), dep(v))
    sgai = _d(_d(v.get("sga"), v.get("rev")), _d(p.get("sga"), p.get("rev")))
    tata = _d((v["ni"] - v["ocf"]) if v.get("ni") is not None and v.get("ocf") is not None else None, v.get("ta"))
    lvgi = _d(_d(v.get("tl"), v.get("ta")), _d(p.get("tl"), p.get("ta")))
    if None in (dsri, gmi, aqi, sgi, tata):
        return None
    return (-4.84 + 0.920*dsri + 0.528*gmi + 0.404*aqi + 0.892*sgi + 0.115*(depi or 1)
            - 0.172*(sgai or 1) + 4.679*tata - 0.327*(lvgi or 1))

def turnaround_signals(v: dict, p: dict, q: dict) -> dict:
    """S1-S6 from the Finding Alpha research."""
    gm, gm_p, gm_q = _d(v.get("gp"), v.get("rev")), _d(p.get("gp"), p.get("rev")), _d(q.get("gp"), q.get("rev"))
    om, om_p = _d(v.get("oi"), v.get("rev")), _d(p.get("oi"), p.get("rev"))
    cagr = (math.sqrt(v["rev"] / q["rev"]) - 1) if v.get("rev") and q.get("rev") and q["rev"] > 0 and v["rev"] > 0 else None
    return {
        "S1": v.get("ocf") is not None and v.get("ni") is not None and v["ocf"] > 0 and v["ni"] < 0,
        "S2": None not in (gm, gm_p, gm_q, cagr) and gm - gm_q >= 0.03 and gm > gm_p and cagr < 0.05,
        "S3": None not in (v.get("rev"), p.get("rev"), v.get("gp"), p.get("gp")) and v["rev"] < p["rev"] and v["gp"] > p["gp"],
        "S4": om is not None and om_p is not None and om - om_p >= 0.03,
        "S5": (p.get("debt") or 0) > 0 and v.get("debt") is not None and v["debt"] <= 0.85 * p["debt"],
        "S6": (p.get("dem") or 0) > 5e6 and v.get("dem") is not None and v["dem"] >= 1.5 * p["dem"],
    }

# ── Prices ───────────────────────────────────────────────────────────────────
def price_context(ticker: str) -> dict | None:
    """Latest price and 3-year high (split-adjusted), via yfinance."""
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(period="3y", interval="1wk", auto_adjust=False)
        if h is None or h.empty:
            return None
        last = float(h["Close"].dropna().iloc[-1])
        hi = float(h["High"].dropna().max())
        return {"price": last, "high_3y": hi, "vs_high": last / hi if hi else None}
    except Exception:
        return None

def _price_on(ticker: str, when: date) -> float | None:
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(start=when - timedelta(days=7), end=when + timedelta(days=1), auto_adjust=True)
        return float(h["Close"].dropna().iloc[-1]) if not h.empty else None
    except Exception:
        return None

# ── Scoring one company ──────────────────────────────────────────────────────
def score_company(conn, cik: int) -> dict | None:
    """Apply gates 1-4. Returns a signal dict if the company passes, else None."""
    prof = company_profile(conn, cik)
    tk, sic = prof.get("ticker"), prof.get("sic")
    if not tk:
        return None
    if sic and 6000 <= sic <= 6799:
        return None                                   # financials excluded
    facts = _sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json")
    yrs = annual_figures(facts)
    if len(yrs) < 3:
        return None                                   # need 3 years of history
    v, p, q = yrs[0], yrs[1], yrs[2]
    if not v.get("rev") or v["rev"] < MIN_REVENUE or not q.get("rev"):
        return None
    om = _d(v.get("oi"), v["rev"])
    struggling = (v.get("ni") or 0) < 0 or (p.get("ni") or 0) < 0 or (om is not None and om < 0.03)
    if not struggling:
        return None
    sig = turnaround_signals(v, p, q)
    if not (sig["S1"] or sig["S3"]):
        return None
    px = price_context(tk)
    if not px or px["vs_high"] is None or px["vs_high"] > MAX_PRICE_VS_HI:
        return None
    mcap = px["price"] * v["sh"] if v.get("sh") else None
    if not mcap or mcap < MIN_MCAP or mcap > MAX_MCAP:
        return None
    f = piotroski(v, p)
    z = altman_z(v, mcap, sic)
    m = beneish_m(v, p)
    if MIN_PIOTROSKI and (f is None or f < MIN_PIOTROSKI):
        return None
    if MIN_ALTMAN > -1e8 and z is not None and z < MIN_ALTMAN:
        return None
    if MAX_BENEISH < 1e8 and m is not None and m > MAX_BENEISH:
        return None
    reasons = [k for k, ok in sig.items() if ok]
    return {
        "id": f"{tk}:{v['end']}", "ticker": tk, "cik": str(cik), "name": prof.get("name") or tk,
        "sic": sic, "fiscal_year_end": v["end"], "filing_accn": v.get("accn"),
        "price": px["price"], "market_cap": mcap, "price_vs_3y_high": px["vs_high"],
        "reasons": reasons,
        "scores": {"piotroski": f, "altman_z": None if z is None else round(z, 2),
                   "beneish_m": None if m is None else round(m, 2)},
        "metrics": {"revenue": v.get("rev"), "revenue_prev": p.get("rev"),
                    "gross_margin": _d(v.get("gp"), v["rev"]), "gross_margin_prev": _d(p.get("gp"), p.get("rev")),
                    "operating_margin": om, "net_income": v.get("ni"), "operating_cash_flow": v.get("ocf"),
                    "long_term_debt": v.get("debt"), "long_term_debt_prev": p.get("debt")},
    }

def save_signal(conn, s: dict, iwm_price: float | None):
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute("SELECT id FROM as2_signals WHERE id=?", (s["id"],)).fetchone()
    if row:
        conn.execute("""UPDATE as2_signals SET last_scored=?, market_cap=?, price_vs_3y_high=?,
                        reasons=?, scores=?, metrics=? WHERE id=?""",
                     (now, s["market_cap"], s["price_vs_3y_high"], json.dumps(s["reasons"]),
                      json.dumps(s["scores"]), json.dumps(s["metrics"]), s["id"]))
        return "updated"
    conn.execute("""INSERT INTO as2_signals(id,ticker,cik,name,sic,fiscal_year_end,filing_accn,status,
                    first_seen,last_scored,price_at_signal,iwm_at_signal,market_cap,price_vs_3y_high,
                    reasons,scores,metrics) VALUES(?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?)""",
                 (s["id"], s["ticker"], s["cik"], s["name"], s["sic"], s["fiscal_year_end"], s["filing_accn"],
                  now, now, s["price"], iwm_price, s["market_cap"], s["price_vs_3y_high"],
                  json.dumps(s["reasons"]), json.dumps(s["scores"]), json.dumps(s["metrics"])))
    return "new"

# ── AI explanation, capped per day, queued ───────────────────────────────────
def explain_queue(conn, anthropic_key: str) -> int:
    if not anthropic_key:
        return 0
    today = date.today().isoformat()
    used = int(_meta_get(conn, f"ai_calls:{today}", 0))
    room = max(0, AI_DAILY_CAP - used)
    if room == 0:
        return 0
    rows = conn.execute("""SELECT * FROM as2_signals WHERE status='active' AND explanation IS NULL
                           ORDER BY first_seen ASC LIMIT ?""", (room,)).fetchall()
    if not rows:
        return 0
    import anthropic
    client = anthropic.Anthropic(api_key=anthropic_key)
    done = 0
    for r in rows:
        facts = {"ticker": r["ticker"], "company": r["name"], "fiscal_year_end": r["fiscal_year_end"],
                 "signals": {c: BOOSTER_LABELS[c] for c in json.loads(r["reasons"])},
                 "scores": json.loads(r["scores"]), "metrics": json.loads(r["metrics"]),
                 "price_vs_3_year_high": r["price_vs_3y_high"]}
        prompt = ("Write 3 short plain-English sentences for a retail investor explaining why this US company "
                  "appears on a turnaround research screen, using ONLY the facts below. Say what improved, what "
                  "is still weak, and one thing to check in the next filing. No buy/sell/hold language, no price "
                  "targets, no advice. Facts:\n" + json.dumps(facts, default=str))
        try:
            msg = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=300,
                                         messages=[{"role": "user", "content": prompt}])
            text = msg.content[0].text.strip()
            conn.execute("UPDATE as2_signals SET explanation=?, explained_at=? WHERE id=?",
                         (text, datetime.now(timezone.utc).isoformat(), r["id"]))
            done += 1
        except Exception as e:
            print(f"[Alpha Scanner v2] explanation failed for {r['ticker']}: {e}")
            break
    _meta_set(conn, f"ai_calls:{today}", used + done)
    return done

# ── Track record ─────────────────────────────────────────────────────────────
def update_track_record(conn) -> int:
    """Record returns at 3/6/12/24 months; close signals after 24 months."""
    now = datetime.now(timezone.utc)
    rows = conn.execute("SELECT * FROM as2_signals WHERE price_at_signal IS NOT NULL").fetchall()
    added = 0
    for r in rows:
        first = datetime.fromisoformat(r["first_seen"])
        for mth in TRACK_MONTHS:
            due = first + timedelta(days=round(mth * 30.44))
            if due > now:
                continue
            if conn.execute("SELECT 1 FROM as2_perf WHERE signal_id=? AND months=?", (r["id"], mth)).fetchone():
                continue
            px = _price_on(r["ticker"], due.date())
            iwm = _price_on("IWM", due.date())
            if px is None:
                continue
            ret = px / r["price_at_signal"] - 1
            iwm_ret = (iwm / r["iwm_at_signal"] - 1) if iwm and r["iwm_at_signal"] else None
            conn.execute("INSERT INTO as2_perf VALUES(?,?,?,?,?,?)",
                         (r["id"], mth, now.isoformat(), px, ret, iwm_ret))
            added += 1
        if r["status"] == "active" and now - first > timedelta(days=731):
            conn.execute("UPDATE as2_signals SET status='closed', closed_at=?, close_reason='24_months' WHERE id=?",
                         (now.isoformat(), r["id"]))
    return added

# ── Runs ─────────────────────────────────────────────────────────────────────
def run(mode: str = "daily", anthropic_key: str = "", ciks: list[int] | None = None) -> dict:
    """
    mode='daily': re-score companies that filed a 10-K/10-Q since the last run.
    mode='full' : re-score every listed company (weekly; free, ~SEC rate-limited).
    """
    conn = db()
    started = datetime.now(timezone.utc)
    if ciks is None:
        if mode == "full":
            ticker_for_cik(0)
            ciks = list(_ticker_map["by_cik"].keys())
        else:
            last = _meta_get(conn, "last_daily_run")
            since = date.fromisoformat(last) if last else date.today() - timedelta(days=7)
            ciks = [c for c, _, _ in new_filers(since, date.today())]
    iwm = price_context("IWM")
    iwm_price = iwm["price"] if iwm else None
    scored = new = 0
    for cik in ciks:
        try:
            s = score_company(conn, cik)
            scored += 1
            if s and save_signal(conn, s, iwm_price) == "new":
                new += 1
            if scored % 25 == 0:
                conn.commit()
        except Exception as e:
            print(f"[Alpha Scanner v2] {cik}: {e}")
    conn.commit()
    explained = explain_queue(conn, anthropic_key)
    tracked = update_track_record(conn)
    _meta_set(conn, "last_daily_run", date.today().isoformat())
    _meta_set(conn, "last_run_summary", json.dumps({"mode": mode, "scored": scored, "new": new,
                                                     "explained": explained, "tracked": tracked,
                                                     "started": started.isoformat()}))
    conn.commit(); conn.close()
    return {"mode": mode, "companies_scored": scored, "new_signals": new,
            "explanations_written": explained, "track_record_points": tracked}

# ── Read models for the API ──────────────────────────────────────────────────
def list_signals(status: str = "active", limit: int = 200) -> dict:
    conn = db()
    rows = conn.execute("SELECT * FROM as2_signals WHERE status=? ORDER BY first_seen DESC LIMIT ?",
                        (status, limit)).fetchall()
    out = []
    for r in rows:
        reasons = json.loads(r["reasons"] or "[]")
        perf = {p["months"]: {"return": p["ret"], "iwm_return": p["iwm_ret"]}
                for p in conn.execute("SELECT * FROM as2_perf WHERE signal_id=?", (r["id"],))}
        out.append({
            "id": r["id"], "ticker": r["ticker"], "name": r["name"], "sic": r["sic"],
            "fiscal_year_end": r["fiscal_year_end"], "first_seen": r["first_seen"],
            "market_cap": r["market_cap"], "price_at_signal": r["price_at_signal"],
            "price_vs_3y_high": r["price_vs_3y_high"],
            "reasons": [{"code": c, "label": BOOSTER_LABELS.get(c, c)} for c in reasons],
            "signal_count": len(reasons),
            "scores": json.loads(r["scores"] or "{}"), "metrics": json.loads(r["metrics"] or "{}"),
            "explanation": r["explanation"], "performance": perf, "status": r["status"],
        })
    out.sort(key=lambda s: (-s["signal_count"], s["price_vs_3y_high"] or 1))
    summary = json.loads(_meta_get(conn, "last_run_summary", "{}") or "{}")
    conn.close()
    return {"signals": out, "total": len(out), "last_run": summary,
            "rules": {"market_cap": [MIN_MCAP, MAX_MCAP], "min_revenue": MIN_REVENUE,
                      "max_price_vs_3y_high": MAX_PRICE_VS_HI}}

def scorecard() -> dict:
    """Average and median returns of every signal ever issued, by horizon, vs IWM."""
    conn = db()
    res = {}
    for mth in TRACK_MONTHS:
        rows = conn.execute("SELECT ret, iwm_ret FROM as2_perf WHERE months=?", (mth,)).fetchall()
        rets = sorted(r["ret"] for r in rows)
        if not rets:
            res[mth] = {"count": 0}
            continue
        n = len(rets)
        med = rets[n // 2] if n % 2 else (rets[n // 2 - 1] + rets[n // 2]) / 2
        beat = sum(1 for r in rows if r["iwm_ret"] is not None and r["ret"] > r["iwm_ret"])
        res[mth] = {"count": n, "median_return": med, "average_return": sum(rets) / n,
                    "share_doubled": sum(1 for x in rets if x >= 1) / n,
                    "share_halved": sum(1 for x in rets if x <= -0.5) / n,
                    "share_beat_iwm": beat / n}
    total = conn.execute("SELECT COUNT(*) FROM as2_signals").fetchone()[0]
    conn.close()
    return {"signals_issued": total, "by_horizon_months": res}
