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
  Gate 4  Not in distress: Altman Z >= 1.81 (manufacturers) / Z'' >= 1.10 (others),
                     when computable (AS2_EXCLUDE_DISTRESS, default on).
  Label   "Lower risk": Fintiq quality score >= 7, or 5-6 and rising; cash flow
                     positive; Beneish M < -1.78. Shown, not required.
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

import cost_of_capital as _coc

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
# Backtest 2018-2023 (Finding Alpha, 25 Nov 2026), 3-year returns, $50m-$2bn:
#   rule alone                    426 cases  median +15%  doubled 29%  halved 23%
#   rule, Altman distress removed 258 cases  median +41%  doubled 33%  halved 19%
#   standard Piotroski >= 7 inside the rule: 19 cases, median -20% -> not used as a gate
#   quality check (below) inside the no-distress set: median +21%, halved 16%
#     vs +52% / 20% for the rest -> shown as a lower-risk label, not a filter
EXCLUDE_DISTRESS = os.environ.get("AS2_EXCLUDE_DISTRESS", "1") != "0"
MIN_PIOTROSKI   = _envf("AS2_MIN_PIOTROSKI", 0)      # 0 = gate off
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
    # columns added after the first release (safe to re-run)
    for table, col in (("as2_signals", "industry TEXT"), ("as2_signals", "period_label TEXT"),
                       ("as2_company", "sic_desc TEXT")):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
        except sqlite3.OperationalError:
            pass  # already there
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
    if (row and row["updated"] and row["sic_desc"] is not None
            and row["updated"] > (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()):
        return dict(row)
    sub = _sec_get(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json") or {}
    prof = {"cik": str(cik), "ticker": ticker_for_cik(cik), "name": sub.get("name", ""),
            "sic": int(sub["sic"]) if str(sub.get("sic", "")).isdigit() else None,
            "sic_desc": (sub.get("sicDescription") or "").strip().title(),
            "updated": datetime.now(timezone.utc).isoformat()}
    conn.execute("""INSERT INTO as2_company(cik,ticker,name,sic,sic_desc,updated) VALUES(:cik,:ticker,:name,:sic,:sic_desc,:updated)
                    ON CONFLICT(cik) DO UPDATE SET ticker=excluded.ticker,name=excluded.name,sic=excluded.sic,
                    sic_desc=excluded.sic_desc,updated=excluded.updated""", prof)
    return prof

# Broad sector from the SEC industry (SIC) code, used when Yahoo has no sector.
def sector_from_sic(sic: int | None) -> str:
    if not sic:
        return ""
    for lo, hi, name in ((100, 999, "Agriculture"), (1000, 1499, "Mining & Energy"), (1500, 1799, "Construction"),
                         (2000, 2799, "Consumer & Materials Manufacturing"), (2800, 2899, "Chemicals & Pharma"),
                         (2900, 3299, "Materials"), (3300, 3599, "Industrials"), (3600, 3699, "Technology Hardware"),
                         (3700, 3799, "Transportation Equipment"), (3800, 3999, "Instruments & Other Manufacturing"),
                         (4000, 4799, "Transportation"), (4800, 4899, "Communication Services"),
                         (4900, 4999, "Utilities"), (5000, 5199, "Wholesale"), (5200, 5999, "Retail"),
                         (7000, 7299, "Consumer Services"), (7300, 7399, "Software & Business Services"),
                         (7400, 7999, "Consumer Services"), (8000, 8099, "Healthcare Services"),
                         (8100, 8999, "Professional Services")):
        if lo <= sic <= hi:
            return name
    return ""

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
    # for ROIC and cost of capital
    "int":  ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt"],
    "ltd":  ["LongTermDebt"], "ltdn": ["LongTermDebtNoncurrent"], "ltdc": ["LongTermDebtCurrent"],
    "std":  ["ShortTermBorrowings"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
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

# ── Latest 12 months from quarterly filings (TTM) ────────────────────────────
# Flow items (revenue, profit, cash flow) are summed over the last 12 months:
#   TTM at a quarter end = last full year + this year-to-date - same period last year
# e.g. 12 months to 30 Sep 2026 = FY2025 + Jan-Sep 2026 - Jan-Sep 2025.
# Balance-sheet items (assets, debt, equity) are taken as at that quarter end.
FLOW_KEYS = {"rev", "gp", "cogs", "oi", "ni", "ocf", "sga", "dep", "int"}
SHARE_KEYS = {"sh"}

def _days(a: str, b: str) -> int:
    return (date.fromisoformat(b) - date.fromisoformat(a)).days

def _near(target: str, options, tol: int = 20):
    """Closest date string in options within tol days of target."""
    best = None
    for o in options:
        dd = abs(_days(o, target))
        if dd <= tol and (best is None or dd < abs(_days(best, target))):
            best = o
    return best

def period_figures(facts: dict) -> tuple[list[dict], str] | None:
    """[latest 12 months, the 12 months a year earlier, two years earlier] and a label.
    Falls back to None when quarterly data is too patchy (caller then uses annual)."""
    gaap = (facts or {}).get("facts", {}).get("us-gaap", {})
    series: dict[str, dict] = {}
    for key, names in CONCEPTS.items():
        for name in names:
            units = gaap.get(name, {}).get("units", {})
            arr = units.get("USD") or units.get("shares")
            if not arr:
                continue
            annual, ytd, inst, anyd = {}, {}, {}, {}
            for e in arr:
                if not str(e.get("form", "")).startswith(("10-K", "10-Q")):
                    continue
                end, val = e["end"], e["val"]
                if e.get("start"):
                    n = _days(e["start"], end)
                    if 350 <= n <= 380:
                        annual[end] = val
                    elif 80 <= n <= 300:
                        ytd.setdefault(end, {})[e["start"]] = val
                    if key in SHARE_KEYS and 80 <= n <= 380:
                        anyd.setdefault(end, (n, val))
                        if n < anyd[end][0]:
                            anyd[end] = (n, val)
                else:
                    inst[end] = val
            if annual or ytd or inst:
                series[key] = {"annual": annual, "ytd": ytd, "inst": inst, "anyd": anyd}
                break
    if "rev" not in series or "ni" not in series:
        return None

    def ttm(key: str, end: str):
        s = series.get(key)
        if not s:
            return None
        if key in SHARE_KEYS:
            k = _near(end, s["anyd"], 10)
            return s["anyd"][k][1] if k else None
        if key not in FLOW_KEYS:
            k = _near(end, s["inst"], 10)
            return s["inst"][k] if k else None
        a = _near(end, s["annual"], 10)
        if a:
            return s["annual"][a]
        fy = max((x for x in s["annual"] if x < end), default=None)
        if not fy or _days(fy, end) > 300:
            return None
        cur = _near(end, s["ytd"], 10)
        if not cur:
            return None
        cur_start = _near((date.fromisoformat(fy) + timedelta(days=1)).isoformat(), s["ytd"][cur], 10)
        if not cur_start:
            return None
        prev_end = _near((date.fromisoformat(end) - timedelta(days=365)).isoformat(), s["ytd"], 15)
        prev_fy = max((x for x in s["annual"] if x < fy), default=None)
        if not prev_end or not prev_fy:
            return None
        prev_start = _near((date.fromisoformat(prev_fy) + timedelta(days=1)).isoformat(), s["ytd"][prev_end], 10)
        if not prev_start:
            return None
        return s["annual"][fy] + s["ytd"][cur][cur_start] - s["ytd"][prev_end][prev_start]

    rev = series["rev"]
    ends = sorted(set(rev["annual"]) | set(rev["ytd"]), reverse=True)
    if not ends:
        return None
    e0 = ends[0]
    targets = [e0, (date.fromisoformat(e0) - timedelta(days=365)).isoformat(),
               (date.fromisoformat(e0) - timedelta(days=730)).isoformat()]
    out = []
    for t in targets:
        t = _near(t, ends, 20) or t
        row = {"end": t}
        for key in CONCEPTS:
            try:
                row[key] = ttm(key, t)
            except Exception:
                row[key] = None
        if row.get("gp") is None and row.get("rev") is not None and row.get("cogs") is not None:
            row["gp"] = row["rev"] - row["cogs"]
        out.append(row)
    if any(r.get("rev") is None or r.get("ni") is None for r in out):
        return None
    is_annual = _near(e0, rev["annual"], 10) is not None
    end_txt = date.fromisoformat(e0).strftime("%-d %b %Y")
    label = f"12 months to {end_txt}" + (" (annual report)" if is_annual else " (latest quarters)")
    return out, label

def latest_shares(facts: dict) -> tuple[float, str] | None:
    """Shares outstanding from the latest filing's cover page (dei)."""
    arr = ((facts or {}).get("facts", {}).get("dei", {})
           .get("EntityCommonStockSharesOutstanding", {}).get("units", {}).get("shares"))
    if not arr:
        return None
    end = max(e["end"] for e in arr)
    latest = [e for e in arr if e["end"] == end]
    accn = max(e.get("accn", "") for e in latest)
    total = sum(e["val"] for e in latest if e.get("accn", "") == accn)   # sums share classes
    return (float(total), end) if total > 0 else None

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

def quality_score(v: dict, p: dict) -> int | None:
    """Fintiq quality score (v1 Alpha Scanner's 9-point check): like Piotroski but tests
    liquidity level (current ratio >= 1), debt not rising and dilution <= 2%."""
    if v.get("ta") is None or v.get("ni") is None or not p:
        return None
    roa, roa_p = _d(v.get("ni"), v.get("ta")), _d(p.get("ni"), p.get("ta"))
    cr = _d(v.get("ca"), v.get("cl"))
    gm, gm_p = _d(v.get("gp"), v.get("rev")), _d(p.get("gp"), p.get("rev"))
    at, at_p = _d(v.get("rev"), v.get("ta")), _d(p.get("rev"), p.get("ta"))
    tests = [
        roa is not None and roa > 0,
        (v.get("ocf") or 0) > 0,
        roa is not None and roa_p is not None and roa > roa_p,
        v.get("ocf") is not None and v["ocf"] > v["ni"],
        v.get("debt") is not None and p.get("debt") is not None and v["debt"] <= p["debt"],
        cr is not None and cr >= 1,
        v.get("sh") is not None and p.get("sh") is not None and v["sh"] <= p["sh"] * 1.02,
        gm is not None and gm_p is not None and gm > gm_p,
        at is not None and at_p is not None and at > at_p,
    ]
    return sum(bool(t) for t in tests)

def altman_distress(z: float | None, sic: int | None) -> bool:
    """Distress zone: Z < 1.81 (manufacturers, original Z) or Z'' < 1.10 (others)."""
    if z is None:
        return False
    return z < (1.81 if sic and 2000 <= sic <= 3999 else 1.10)

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
        splits = []
        try:
            sp = yf.Ticker(ticker).splits
            splits = [(d.date().isoformat(), float(r)) for d, r in sp.items() if r and r > 0]
        except Exception:
            pass
        return {"price": last, "high_3y": hi, "vs_high": last / hi if hi else None, "splits": splits}
    except Exception:
        return None

def yahoo_profile(ticker: str) -> dict:
    """Sector and industry as Yahoo labels them (empty if unavailable)."""
    try:
        import yfinance as yf
        info = yf.Ticker(ticker).info or {}
        mc = info.get("marketCap")
        return {"sector": info.get("sector") or "", "industry": info.get("industry") or "",
                "market_cap": float(mc) if mc else None}
    except Exception:
        return {"sector": "", "industry": "", "market_cap": None}

def split_factor_since(splits: list, since: str) -> float:
    """Combined split ratio after a date (2.0 = shares doubled since then; 0.1 = 1-for-10 reverse split)."""
    f = 1.0
    for d, r in splits or []:
        if d > since:
            f *= r
    return f

def _price_on(ticker: str, when: date) -> float | None:
    try:
        import yfinance as yf
        h = yf.Ticker(ticker).history(start=when - timedelta(days=7), end=when + timedelta(days=1), auto_adjust=True)
        return float(h["Close"].dropna().iloc[-1]) if not h.empty else None
    except Exception:
        return None

# ── Scoring one company ──────────────────────────────────────────────────────
# Why a company stopped qualifying (shown on its card when it leaves the list).
CLOSE_LABELS = {
    "turned_worse": "Figures got worse",
    "distress": "Now in the Altman distress zone",
    "price_recovered": "Price recovered above half its 3-year high",
    "now_profitable": "Back to profit (no longer struggling)",
    "out_of_range": "Outside the size or revenue range",
    "out_of_scope": "No longer covered",
    "24_months": "24 months since signal",
}
_last_fail = {"reason": None}

def _fail(reason: str):
    """Record why the company failed; 'data' means we could not tell, so nothing is closed."""
    _last_fail["reason"] = reason
    return None

def close_if_failed(conn, cik: int, reason: str | None) -> bool:
    """Move an active signal off the list when newer figures (or the price) no longer qualify.
    Missing data never closes a signal. Its track record keeps being measured for 24 months."""
    if not reason or reason == "data":
        return False
    row = conn.execute("SELECT id FROM as2_signals WHERE cik=? AND status='active'", (str(cik),)).fetchone()
    if not row:
        return False
    conn.execute("UPDATE as2_signals SET status='closed', closed_at=?, close_reason=? WHERE id=?",
                 (datetime.now(timezone.utc).isoformat(), reason, row["id"]))
    return True

def score_company(conn, cik: int) -> dict | None:
    """Apply gates 1-4. Returns a signal dict if the company passes, else None
    (the reason is left in _last_fail)."""
    _last_fail["reason"] = None
    prof = company_profile(conn, cik)
    tk, sic = prof.get("ticker"), prof.get("sic")
    if not tk:
        return _fail("data")
    if sic and 6000 <= sic <= 6799:
        return _fail("out_of_scope")
    facts = _sec_get(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json")
    if not facts:
        return _fail("data")
    yrs = annual_figures(facts)
    if len(yrs) < 3:
        return _fail("out_of_scope")
    v, p, q = yrs[0], yrs[1], yrs[2]
    period_label = "12 months to " + date.fromisoformat(v["end"]).strftime("%-d %b %Y") + " (annual report)"
    # Prefer the latest 12 months from quarterly filings when they are newer than the last annual report
    try:
        pf = period_figures(facts)
    except Exception:
        pf = None
    if pf and pf[0][0]["end"] > v["end"]:
        (v2, p2, q2), lbl = pf
        accn = v.get("accn")
        v, p, q, period_label = dict(v2, accn=accn), p2, q2, lbl
    if not v.get("rev") or not q.get("rev"):
        return _fail("data")
    if v["rev"] < MIN_REVENUE:
        return _fail("out_of_range")
    om = _d(v.get("oi"), v["rev"])
    struggling = (v.get("ni") or 0) < 0 or (p.get("ni") or 0) < 0 or (om is not None and om < 0.03)
    if not struggling:
        return _fail("now_profitable")
    sig = turnaround_signals(v, p, q)
    if not (sig["S1"] or sig["S3"]):
        return _fail("turned_worse")
    px = price_context(tk)
    if not px or px["vs_high"] is None or px["vs_high"] > MAX_PRICE_VS_HI:
        return _fail("data" if not px or px["vs_high"] is None else "price_recovered")
    # Shares: latest cover-page count from the filing, adjusted for any split since
    # (fixes market values inflated by reverse splits, e.g. GEE Group).
    cover = latest_shares(facts)
    if cover:
        shares = cover[0] * split_factor_since(px.get("splits"), cover[1])
    elif v.get("sh"):
        shares = v["sh"] * split_factor_since(px.get("splits"), v["end"])
    else:
        shares = None
    mcap = px["price"] * shares if shares else None
    # Cross-check with Yahoo's market value. Share counts in filings can miss a share
    # class or lag a share issue (e.g. iHeartMedia). If the two differ by more than
    # half, use Yahoo's figure.
    yp = yahoo_profile(tk)
    mcap_source = "SEC shares x price"
    if yp.get("market_cap") and (not mcap or not (1 / 1.5 <= yp["market_cap"] / mcap <= 1.5)):
        mcap, mcap_source = yp["market_cap"], "Yahoo Finance"
    if not mcap or mcap < MIN_MCAP or mcap > MAX_MCAP:
        return _fail("data" if not mcap else "out_of_range")
    # ROIC and cost of capital (display only; not a rule until backtested)
    cc = _coc.wacc(sic, mcap, _coc.total_debt(v), v.get("oi"), v.get("int"))
    r0, r1, r2 = _coc.roic(v, p), _coc.roic(p, q), _coc.roic(q, None)
    st_n, st_lbl = _coc.stage(r0, r1, cc["wacc"] if cc else None)
    ic0 = _coc.invested_capital(v)
    ep = round((r0 - cc["wacc"]) * ic0) if (r0 is not None and cc and ic0 and ic0 > 0) else None
    f = piotroski(v, p)
    z = altman_z(v, mcap, sic)
    m = beneish_m(v, p)
    if EXCLUDE_DISTRESS and altman_distress(z, sic):
        return _fail("distress")
    if MIN_PIOTROSKI and (f is None or f < MIN_PIOTROSKI):
        return _fail("turned_worse")
    if MAX_BENEISH < 1e8 and m is not None and m > MAX_BENEISH:
        return _fail("turned_worse")
    fq, fq_prev = quality_score(v, p), quality_score(p, q)
    quality_pass = bool((v.get("ocf") or 0) > 0 and fq is not None
                        and (fq >= 7 or (fq in (5, 6) and fq_prev is not None and fq > fq_prev))
                        and (m is None or m < -1.78))
    reasons = [k for k, ok in sig.items() if ok]
    return {
        "id": f"{tk}:{v['end']}", "ticker": tk, "cik": str(cik), "name": prof.get("name") or tk,
        "sic": sic, "fiscal_year_end": v["end"], "filing_accn": v.get("accn"),
        "period_label": period_label,
        "sector": yp["sector"] or sector_from_sic(sic),
        "industry": yp["industry"] or (prof.get("sic_desc") or ""),
        "price": px["price"], "market_cap": mcap, "price_vs_3y_high": px["vs_high"],
        "reasons": reasons,
        "scores": {"market_cap_source": mcap_source, "piotroski": f, "altman_z": None if z is None else round(z, 2),
                   "beneish_m": None if m is None else round(m, 2),
                   "quality_score": fq, "quality_score_prev": fq_prev, "lower_risk": quality_pass},
        "metrics": {"revenue": v.get("rev"), "revenue_prev": p.get("rev"),
                    "gross_margin": _d(v.get("gp"), v["rev"]), "gross_margin_prev": _d(p.get("gp"), p.get("rev")),
                    "operating_margin": om, "net_income": v.get("ni"), "operating_cash_flow": v.get("ocf"),
                    "long_term_debt": v.get("debt"), "long_term_debt_prev": p.get("debt"),
                    "roic": r0, "roic_prev": r1, "roic_prev2": r2, "invested_capital": ic0,
                    "economic_profit": ep, "stage": st_n, "stage_label": st_lbl, "cost_of_capital": cc},
    }

def save_signal(conn, s: dict, iwm_price: float | None):
    """One active signal per company. A newer quarter updates the existing signal
    (its start date and price at signal stay, so the track record is honest);
    the plain-English summary is re-queued when the figures move to a new period."""
    now = datetime.now(timezone.utc).isoformat()
    row = conn.execute("SELECT id, fiscal_year_end FROM as2_signals WHERE ticker=? AND status='active'",
                       (s["ticker"],)).fetchone()
    if row:
        new_period = row["fiscal_year_end"] != s["fiscal_year_end"]
        conn.execute(f"""UPDATE as2_signals SET last_scored=?, market_cap=?, price_vs_3y_high=?,
                        reasons=?, scores=?, metrics=?, sector=?, industry=?, period_label=?,
                        fiscal_year_end=?, filing_accn=?
                        {", explanation=NULL, explained_at=NULL" if new_period else ""} WHERE id=?""",
                     (now, s["market_cap"], s["price_vs_3y_high"], json.dumps(s["reasons"]),
                      json.dumps(s["scores"]), json.dumps(s["metrics"]), s["sector"], s["industry"],
                      s["period_label"], s["fiscal_year_end"], s["filing_accn"], row["id"]))
        return "updated"
    if conn.execute("SELECT 1 FROM as2_signals WHERE id=?", (s["id"],)).fetchone():
        # re-entering after leaving the list on the same figures: a fresh signal with its own track record
        s = dict(s, id=f'{s["id"]}:{date.today():%Y%m%d}')
    conn.execute("""INSERT INTO as2_signals(id,ticker,cik,name,sic,sector,industry,period_label,fiscal_year_end,
                    filing_accn,status,first_seen,last_scored,price_at_signal,iwm_at_signal,market_cap,
                    price_vs_3y_high,reasons,scores,metrics)
                    VALUES(?,?,?,?,?,?,?,?,?,?,'active',?,?,?,?,?,?,?,?,?)""",
                 (s["id"], s["ticker"], s["cik"], s["name"], s["sic"], s["sector"], s["industry"],
                  s["period_label"], s["fiscal_year_end"], s["filing_accn"],
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
        facts = {"ticker": r["ticker"], "company": r["name"],
                 "figures_for": r["period_label"] or ("12 months to " + str(r["fiscal_year_end"])),
                 "sector": r["sector"], "industry": r["industry"],
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
    scored = new = closed = 0
    for cik in ciks:
        try:
            s = score_company(conn, cik)
            scored += 1
            if s and save_signal(conn, s, iwm_price) == "new":
                new += 1
            elif not s and close_if_failed(conn, cik, _last_fail["reason"]):
                closed += 1
            if scored % 25 == 0:
                conn.commit()
        except Exception as e:
            print(f"[Alpha Scanner v2] {cik}: {e}")
    conn.commit()
    explained = explain_queue(conn, anthropic_key)
    tracked = update_track_record(conn)
    _meta_set(conn, "last_daily_run", date.today().isoformat())
    _meta_set(conn, "last_run_summary", json.dumps({"mode": mode, "scored": scored, "new": new, "closed": closed,
                                                     "explained": explained, "tracked": tracked,
                                                     "started": started.isoformat()}))
    conn.commit(); conn.close()
    return {"mode": mode, "companies_scored": scored, "new_signals": new, "signals_closed": closed,
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
            "period_label": r["period_label"], "sector": r["sector"], "industry": r["industry"],
            "market_cap": r["market_cap"], "price_at_signal": r["price_at_signal"],
            "price_vs_3y_high": r["price_vs_3y_high"],
            "reasons": [{"code": c, "label": BOOSTER_LABELS.get(c, c)} for c in reasons],
            "signal_count": len(reasons),
            "scores": json.loads(r["scores"] or "{}"), "metrics": json.loads(r["metrics"] or "{}"),
            "explanation": r["explanation"], "performance": perf, "status": r["status"],
            "closed_at": r["closed_at"], "close_reason": r["close_reason"],
            "close_label": CLOSE_LABELS.get(r["close_reason"] or "", r["close_reason"]),
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
