"""
Fintiq API — FastAPI backend for fintiq.uk
Serves: /bulletin, /market-data, /earnings, /health
Deployed to: api.fintiq.uk (Railway)
"""
import os, json, time, threading, requests
from datetime import datetime, timedelta
from typing import Optional
from concurrent.futures import ThreadPoolExecutor
import yfinance as yf
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import anthropic

# ── Config ─────────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
FMP_KEY           = os.environ.get("FMP_KEY", "c3gRy6dPp8uETaNIYoFJj83J7hm998bB")
FMP_BASE          = "https://financialmodelingprep.com/api"
REFRESH_TOKEN     = os.environ.get("REFRESH_TOKEN", "fintiq-refresh-2026")
TAVILY_API_KEY    = os.environ.get("TAVILY_API_KEY", "")
FRED_API_KEY      = os.environ.get("FRED_API_KEY", "")
FRED_BASE         = "https://api.stlouisfed.org/fred/series/observations"

# ── FastAPI ────────────────────────────────────────────────────────────────────
app = FastAPI(title="Fintiq API", version="1.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://fintiq.uk","https://www.fintiq.uk","https://app.fintiq.uk",
                   "http://localhost:3000","http://localhost:8080","http://127.0.0.1:5500"],
    allow_credentials=True, allow_methods=["GET","POST"], allow_headers=["*"],
)

# ── Caches ─────────────────────────────────────────────────────────────────────
_bulletin_cache: dict = {}; _bulletin_cached_at: float = 0.0; _BULLETIN_TTL = 6*3600
_bulletin_refreshing: bool = False  # True while background regeneration is in progress
_market_cache:   dict = {}; _market_cached_at:   float = 0.0; _MARKET_TTL   = 30*60
_earnings_cache: dict = {}; _earnings_cached_at: dict  = {};  _EARNINGS_TTL = 24*3600
_earnings_refreshing: dict = {}  # per-index refresh lock

# ── Constants ──────────────────────────────────────────────────────────────────
_FOMC_DATES = [
    "2026-09-17","2026-11-04","2026-12-16",
    "2027-01-27","2027-03-17","2027-05-05","2027-06-16",
    "2027-07-28","2027-09-15","2027-11-03","2027-12-15",
]

_BRIEF_INDICES = [
    ("^GSPC","S&P 500","🇺🇸","US"),("^DJI","Dow Jones","🇺🇸","US"),
    ("^IXIC","Nasdaq","🇺🇸","US"),("^RUT","Russell 2000","🇺🇸","US"),
    ("ES=F","S&P Futures","🇺🇸","Futures"),("NQ=F","Nasdaq Futures","🇺🇸","Futures"),
    ("YM=F","Dow Futures","🇺🇸","Futures"),("^FTSE","FTSE 100","🇬🇧","UK"),
    ("^FTMC","FTSE 250","🇬🇧","UK"),("^GDAXI","DAX","🇩🇪","Europe"),
    ("^FCHI","CAC 40","🇫🇷","Europe"),("^STOXX50E","Euro Stoxx 50","🇪🇺","Europe"),
    ("^N225","Nikkei 225","🇯🇵","Asia"),("000001.SS","Shanghai","🇨🇳","Asia"),
    ("^HSI","Hang Seng","🇭🇰","Asia"),("^AXJO","ASX 200","🇦🇺","Asia"),
    ("^BSESN","Sensex","🇮🇳","Asia"),
]
_BRIEF_INSTRUMENTS = [
    ("^VIX","VIX","Fear Index"),("^VIX9D","VIX9D","9D VIX"),("^VIX3M","VIX3M","3M VIX"),
    ("GC=F","Gold","$/oz"),("BZ=F","Brent Oil","$/bbl"),
    ("CL=F","WTI Oil","$/bbl"),("DX-Y.NYB","Dollar Index","DXY"),
    ("HYG","HYG","High Yield ETF"),("LQD","LQD","IG Credit ETF"),
    ("GBPUSD=X","GBP/USD","FX"),("EURUSD=X","EUR/USD","FX"),
    ("USDJPY=X","USD/JPY","FX"),("^TNX","10Y Treasury","Yield %"),
]
_SECTOR_ETFS = [
    ("XLK","Technology"),("XLF","Financials"),("XLE","Energy"),("XLV","Healthcare"),
    ("XLI","Industrials"),("XLC","Communications"),("XLY","Consumer Disc."),
    ("XLP","Consumer Staples"),("XLB","Materials"),("XLRE","Real Estate"),
]
_MAJOR_MARKET_TICKERS = [
    ("^NDX","NASDAQ 100","us"),("^DJI","Dow Jones","us"),("^GSPC","S&P 500","us"),
    ("^FTSE","FTSE 100","gb"),("^STOXX50E","Euro Stoxx 50","eu"),
    ("000001.SS","Shanghai","cn"),("EEM","MSCI EM","🌐"),("^N225","Nikkei 225","jp"),
]
_INDEX_TICKERS = {
    "sp500": [
        # 1-50
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","BRK-B","LLY","AVGO","TSLA",
        "JPM","V","UNH","XOM","MA","COST","HD","JNJ","NFLX","PG",
        "ABBV","BAC","WMT","CRM","AMD","ORCL","CVX","MRK","ACN","LIN",
        "TMO","PEP","ADBE","MCD","TXN","DHR","CSCO","ABT","GE","QCOM",
        "WFC","UNP","NEE","RTX","INTU","SPGI","AMGN","MS","BLK","SCHW",
        # 51-100
        "AXP","IBM","CAT","NOW","ISRG","DE","GS","UBER","ELV","PLD",
        "AMAT","ADI","LRCX","SYK","GILD","MDLZ","REGN","MMC","CB","VRTX",
        "SO","MU","BMY","TJX","DUK","PNC","USB","CI","BSX","ETN",
        "FI","APH","PANW","KLAC","SNPS","CDNS","CME","EOG","MCO","ITW",
        "WELL","HCA","AON","CTAS","FCX","SHW","NSC","CSX","MMM","PH",
        # 101-150
        "EMR","MCHP","WDAY","KDP","ORLY","MNST","PCAR","PAYX","NXPI","CRWD",
        "EW","ROP","IDXX","VRSK","ADP","CHTR","CMCSA","T","VZ","DIS",
        "EA","CCI","AMT","KO","PM","MO","CL","CMG","YUM","SBUX",
        "BA","LMT","NOC","GD","TDG","CVS","MCK","HUM","C","COF",
        "D","WEC","COP","PSX","VLO","MPC","SLB","OXY","DVN","HAL",
        # 151-200
        "SPG","EQIX","PSA","DLR","O","ZTS","IQV","WAT","MTD","A",
        "BIIB","ILMN","ZBH","MOH","CNC","BKR","AEP","ED","EXC","SRE",
        "AVB","EQR","MAA","EXR","NKE","LULU","TGT","DLTR","DG","ROST",
        "BBY","ENPH","FSLR","AES","GNRC","PWR","CARR","OTIS","TT","JCI",
        "LYB","MOS","CF","NUE","STLD","ALB","RCL","CCL","DAL","UAL",
        # 201-250
        "LUV","AAL","HLT","MAR","MGM","LVS","WYNN","F","GM","LOW",
        "POOL","WSM","ETSY","EBAY","BKNG","EXPE","GPN","FIS","FISV","FTNT",
        "ZBRA","CTSH","IT","EPAM","GDDY","AKAM","NET","ZS","OKTA","MDB",
        "SNOW","DDOG","HUBS","TWLO","HPQ","HPE","DELL","STX","WDC","NTAP",
        "ANET","RF","HBAN","KEY","FITB","CFG","MTB","STT","BK","NDAQ",
    ],
    "nasdaq100": [
        # 1-50
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","GOOG","AVGO","TSLA","COST",
        "NFLX","AMD","ADBE","QCOM","INTU","TXN","AMGN","ISRG","AMAT","MU",
        "LRCX","ADI","REGN","KLAC","MELI","PANW","SNPS","CDNS","CRWD","FTNT",
        "ORLY","MNST","PCAR","CTAS","PAYX","MCHP","WDAY","DXCM","KDP","FAST",
        "NXPI","ROST","ODFL","IDXX","VRSK","ADP","CHTR","EA","ANSS","ON",
        # 51-100
        "KHC","TTWO","EBAY","DLTR","CPRT","GEHC","ALGN","ENPH","CEG","EXC",
        "XEL","CSGP","ABNB","BIIB","ZS","DDOG","TEAM","SIRI","PDD","GILD",
        "VRTX","ARM","LOGI","BKNG","PYPL","ZM","TCOM","DASH","INTC","CSCO",
        "SBUX","ILMN","WBA","NVAX","MRNA","TTD","ROKU","PINS","SNAP","LULU",
        "FANG","HON","MSTR","COIN","HOOD","SOFI","RBLX","LYFT","DKNG","NET",
    ],
    "ftse100": [
        # 1-50
        "SHEL.L","AZN.L","HSBA.L","ULVR.L","DGE.L","BP.L","RIO.L","LLOY.L","GSK.L","BARC.L",
        "VOD.L","REL.L","EXPN.L","WPP.L","PRU.L","LGEN.L","BA.L","AAL.L","BHP.L","IMB.L",
        "MNG.L","ABF.L","CNA.L","SBRY.L","IHG.L","SGE.L","RKT.L","SSE.L","NG.L","GLEN.L",
        "AV.L","STAN.L","NWG.L","BATS.L","TW.L","ITRK.L","AUTO.L","SDR.L","FRES.L","JD.L",
        "MNDI.L","INF.L","WTB.L","CRDA.L","PSON.L","AHT.L","HL.L","WEIR.L","RR.L","IMI.L",
        # 51-100
        "BDEV.L","BWY.L","PSN.L","BLND.L","LAND.L","SGRO.L","SMDS.L","SMWH.L","EMG.L","DPLM.L",
        "FLTR.L","HLN.L","HIK.L","HWDN.L","IAG.L","III.L","KGF.L","LSEG.L","MKS.L","MRW.L",
        "OCDO.L","RS1.L","SVT.L","UTG.L","RTO.L","CPG.L","CRH.L","ENT.L","SKG.L","DCC.L",
        "TSCO.L","BT-A.L","ULVR.L","BRBY.L","ADM.L","ALW.L","ANT.L","ANTO.L","BME.L","BOO.L",
        "CCH.L","CHG.L","COB.L","CTEC.L","DLN.L","GFS.L","GSK.L","HBR.L","HLN.L","HSX.L",
    ],
    "stoxx50": [
        "ASML","MC.PA","OR.PA","TTE.PA","SIE.DE","AIR.PA","ALV.DE","BNP.PA","SAN.PA","SAP",
        "BBVA.MC","ENEL.MI","ABI.BR","KER.PA","DSY.PA","BAS.DE","BAYN.DE","DTE.DE","INGA.AS","STLAM.MI",
        "PHIA.AS","ADS.DE","ENI.MI","ISP.MI","UCG.MI","IBE.MC","SU.PA","BN.PA","MUV2.DE","GLE.PA",
        "RMS.PA","DBK.DE","NOKIA.HE","EL.PA","VOW3.DE","BMW.DE","MBG.DE","AMS.MC","DG.PA","RI.PA",
        "ORA.PA","VIE.PA","ML.PA","ACA.PA","AI.PA","LR.PA","PUB.PA","STM","AXA.PA","MTS.MC",
    ],
}

# ── Helpers ────────────────────────────────────────────────────────────────────
def _get_next_fomc():
    today = datetime.now().date()
    for d in _FOMC_DATES:
        fd = datetime.strptime(d, "%Y-%m-%d").date()
        if fd >= today:
            return (fd - today).days, d
    return None, None

def _fetch_fred(series_id: str, limit: int = 14) -> list:
    """Fetch FRED observations (most-recent first)."""
    if not FRED_API_KEY:
        return []
    try:
        r = requests.get(FRED_BASE, params={
            "series_id": series_id, "limit": limit,
            "sort_order": "desc", "api_key": FRED_API_KEY, "file_type": "json"
        }, timeout=10)
        if r.status_code == 200:
            obs = [o for o in r.json().get("observations", []) if o.get("value") != "."]
            return obs
    except: pass
    return []

def _fetch_cpi_yoy() -> tuple:
    """Returns (current_yoy, [12 monthly yoy values oldest→newest])"""
    obs = _fetch_fred("CPIAUCSL", 25)  # extra buffer
    if len(obs) >= 13:
        try:
            # obs is newest-first; compute YOY for last 12 months
            history = []
            for i in range(min(12, len(obs) - 12)):
                v_now = float(obs[i]["value"]); v_ago = float(obs[i+12]["value"])
                history.append(round((v_now - v_ago) / v_ago * 100, 2))
            history.reverse()  # oldest→newest
            return round(history[-1], 1) if history else None, history
        except: pass
    return None, []

def _fetch_nfp_mom() -> tuple:
    """Returns (current_mom_thousands, [12 monthly deltas oldest→newest])"""
    obs = _fetch_fred("PAYEMS", 14)
    if len(obs) >= 2:
        try:
            vals = [float(o["value"]) for o in obs]
            history = [round(vals[i-1] - vals[i], 0) for i in range(1, min(13, len(vals)))]
            history.reverse()
            return history[-1] if history else None, history
        except: pass
    return None, []

def _fetch_yield_spread() -> tuple:
    """Returns (current_spread, [30 daily values oldest→newest])"""
    obs = _fetch_fred("T10Y2Y", 31)
    if obs:
        try:
            vals = [round(float(o["value"]), 2) for o in obs if o.get("value") != "."]
            vals.reverse()
            return vals[-1] if vals else None, vals[-30:]
        except: pass
    return None, []

def _fetch_fmp_segments(ticker: str, kind: str = "product") -> list:
    """Fetch revenue breakdown by product/segment or geography from FMP.
    kind: 'product' -> /revenue-product-segmentation, 'geographic' -> /revenue-geographic-segmentation
    Returns list of {name, value} dicts for the most recent fiscal year, sorted desc by value.
    """
    try:
        endpoint = "revenue-product-segmentation" if kind == "product" else "revenue-geographic-segmentation"
        r = requests.get(
            f"{FMP_BASE}/v4/{endpoint}?symbol={ticker}&apikey={FMP_KEY}",
            timeout=10,
        )
        if r.status_code != 200:
            return []
        data = r.json()
        if not data or not isinstance(data, list):
            return []
        # FMP returns list of {date: ..., <SegmentName>: value, ...} — take most recent entry
        most_recent = data[0]
        rows = []
        for k, v in most_recent.items():
            if k == "date":
                continue
            try:
                val = float(v)
                if val > 0:
                    rows.append({"name": k, "value": val})
            except (TypeError, ValueError):
                pass
        rows.sort(key=lambda x: x["value"], reverse=True)
        return rows
    except Exception:
        return []


def _fetch_econ_indicator(name: str) -> Optional[dict]:
    try:
        r = requests.get(f"{FMP_BASE}/v4/economic?name={name}&apikey={FMP_KEY}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data and isinstance(data, list):
                return {"value": data[0].get("value"), "date": data[0].get("date")}
    except: pass
    return None

def _fetch_treasury_spread() -> Optional[float]:
    try:
        today = datetime.now().strftime("%Y-%m-%d")
        week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
        r = requests.get(f"{FMP_BASE}/v4/treasury?from={week_ago}&to={today}&apikey={FMP_KEY}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data:
                y10 = data[0].get("year10"); y2 = data[0].get("year2")
                if y10 and y2: return round(y10 - y2, 2)
    except: pass
    return None

def _fetch_market_history(symbol: str) -> list:
    try:
        import math
        hist = yf.Ticker(symbol).history(period="3mo")
        if not hist.empty:
            closes = hist["Close"].tolist()
            step = max(1, len(closes) // 45)
            return [round(float(v), 2) for v in closes[::step]
                    if v is not None and not math.isnan(float(v)) and not math.isinf(float(v))]
    except: pass
    return []

def _safe(v, dec=2):
    """Return rounded float or None — never NaN/Inf."""
    try:
        f = float(v)
        import math
        if math.isnan(f) or math.isinf(f): return None
        return round(f, dec)
    except: return None

def _yf_quick(sym: str) -> dict:
    try:
        fi = yf.Ticker(sym).fast_info
        p = _safe(getattr(fi, "last_price", None))
        prev = _safe(getattr(fi, "previous_close", None))
        pct = _safe((p - prev) / prev * 100) if p and prev and prev != 0 else None
        return {"price": p, "chg_pct": pct}
    except: return {"price": None, "chg_pct": None}

# ── Bulletin data ──────────────────────────────────────────────────────────────
def _fetch_brief_data(tickers):
    out = {}
    for sym in tickers:
        try:
            ti = yf.Ticker(sym).fast_info
            p = getattr(ti,"last_price",None); prev = getattr(ti,"previous_close",None)
            chg = chg_pct = None
            if p and prev and prev != 0: chg = p-prev; chg_pct = chg/prev*100
            out[sym] = {"price":p,"chg":chg,"chg_pct":chg_pct}
        except: out[sym] = {"price":None,"chg":None,"chg_pct":None}
    return out

def _fetch_sector_data():
    out = {}
    for sym,_ in _SECTOR_ETFS:
        try:
            ti = yf.Ticker(sym).fast_info
            p = getattr(ti,"last_price",None); prev = getattr(ti,"previous_close",None)
            out[sym] = (p-prev)/prev*100 if p and prev and prev!=0 else None
        except: out[sym] = None
    return out

def _fetch_econ_calendar():
    today = datetime.now().strftime("%Y-%m-%d")
    end   = (datetime.now()+timedelta(days=5)).strftime("%Y-%m-%d")
    try:
        r = requests.get(f"{FMP_BASE}/v3/economic_calendar?from={today}&to={end}&apikey={FMP_KEY}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            return [e for e in data if e.get("impact") in ("High","Medium")] if data else []
    except: pass
    return []

def _fetch_market_news():
    try:
        r = requests.get(f"{FMP_BASE}/v4/general_news?page=0&apikey={FMP_KEY}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list): return data[:10]
    except: pass
    return []

def _fetch_earnings_today():
    try:
        from datetime import date as _date
        today = _date.today().strftime("%Y-%m-%d")
        r = requests.get(f"{FMP_BASE}/v3/earning_calendar?from={today}&to={today}&apikey={FMP_KEY}", timeout=10)
        if r.status_code == 200:
            data = r.json()
            if isinstance(data, list):
                return sorted(data[:20], key=lambda x: abs(float(x.get("marketCapitalization") or 0)), reverse=True)[:10]
    except: pass
    return []

def _tavily_search(query: str, max_results: int = 5) -> list:
    if not TAVILY_API_KEY: return []
    try:
        r = requests.post("https://api.tavily.com/search",
            json={"api_key":TAVILY_API_KEY,"query":query,"max_results":max_results,
                  "search_depth":"basic","include_answer":False,"include_raw_content":False},
            timeout=10)
        if r.status_code == 200: return r.json().get("results", [])
    except: pass
    return []

def _fetch_web_context(earnings_today: list = None, econ: list = None) -> str:
    if not TAVILY_API_KEY: return "Web search not configured."
    today = datetime.now().strftime("%B %d %Y")
    # Build targeted queries — include specific catalyst tickers if available
    earnings_tickers = " ".join(e.get("symbol","") for e in (earnings_today or [])[:3]) if earnings_today else ""
    econ_event = (econ[0].get("event","") if econ else "") or ""
    queries = [
        f"US stock market macro cross-asset outlook {today}",
        f"Federal Reserve interest rate inflation expectations {today}",
        f"credit markets high yield spreads IG bonds risk appetite {today}",
        f"geopolitical risk energy commodities sector rotation {today}",
        f"institutional hedge fund positioning flows S&P 500 {today}",
    ]
    if earnings_tickers:
        queries.append(f"{earnings_tickers} earnings results analyst reaction {today}")
    if econ_event:
        queries.append(f"{econ_event} economic data market impact {today}")
    sections = []
    for q in queries:
        results = _tavily_search(q, max_results=5)
        if results:
            snippets = [f"• {r.get('title','')}: {r.get('content','').strip()[:400]}" for r in results[:5] if r.get('title')]
            if snippets: sections.append(f"[{q}]\n" + "\n".join(snippets))
    return "\n\n".join(sections) if sections else "No web results retrieved."

# ── FRED 2Y yield helper ───────────────────────────────────────────────────────
def _fetch_2y_yield() -> float | None:
    obs = _fetch_fred("DGS2", 3)
    if obs:
        try: return round(float(obs[0]["value"]), 2)
        except: pass
    return None

# ── Pre-build catalysts from actual data ───────────────────────────────────────
def _build_catalysts(earnings_today: list, econ: list) -> list:
    cats = []
    for e in (earnings_today or [])[:3]:
        sym = e.get("symbol",""); name = e.get("name", sym)
        eps_est = e.get("epsEstimated","?")
        cats.append({"type":"earnings","event":f"{name} ({sym}) reports earnings","impact":f"EPS est {eps_est} — watch guidance and margin commentary"})
    for e in (econ or [])[:3]:
        ev = e.get("event",""); country = e.get("country","")
        est = e.get("estimate","?"); prev = e.get("previous","?")
        if ev:
            cats.append({"type":"macro","event":f"[{country}] {ev}","impact":f"Est: {est} vs prev: {prev}"})
    return cats

# ── Bulletin generation ────────────────────────────────────────────────────────
def _generate_bulletin() -> dict:
    syms = [s for s,_,_,_ in _BRIEF_INDICES] + [s for s,_,_ in _BRIEF_INSTRUMENTS]
    bd = _fetch_brief_data(syms)
    news = _fetch_market_news(); econ = _fetch_econ_calendar()
    sectors = _fetch_sector_data(); earnings_today = _fetch_earnings_today()
    web_context = _fetch_web_context(earnings_today, econ)

    # Fetch 2Y yield for curve context
    yield_2y = _fetch_2y_yield()

    def pct(v): return f"{v:+.2f}%" if v is not None else "n/a"
    def pr(sym): return bd.get(sym, {})

    spx=pr("^GSPC"); vix=pr("^VIX"); gold=pr("GC=F"); brent=pr("BZ=F")
    dxy=pr("DX-Y.NYB"); tnx=pr("^TNX"); gbp=pr("GBPUSD=X"); eur=pr("EURUSD=X")
    jpy=pr("USDJPY=X"); spyf=pr("ES=F"); nqf=pr("NQ=F")
    hyg=pr("HYG"); lqd=pr("LQD")
    vix9d=pr("^VIX9D"); vix3m=pr("^VIX3M")

    # VIX term structure signal
    vix_spot = vix.get("price"); vix9d_val = vix9d.get("price"); vix3m_val = vix3m.get("price")
    vix_term = ""
    if vix9d_val and vix_spot and vix3m_val:
        if float(vix9d_val) > float(vix_spot): vix_term = f" | VIX9D {vix9d_val} > spot {vix_spot} — INVERTED near-term stress"
        else: vix_term = f" | VIX9D {vix9d_val} < spot {vix_spot} < VIX3M {vix3m_val} — contango intact"

    tnx_val = float(tnx.get("price") or 0); y2_val = float(yield_2y or 0)
    curve_spread = round(tnx_val - y2_val, 2) if tnx.get("price") and yield_2y else None

    mkt = (f"S&P 500: {spx.get('price','n/a')} ({pct(spx.get('chg_pct'))})\n"
           f"S&P Futures: {spyf.get('price','n/a')} ({pct(spyf.get('chg_pct'))})\n"
           f"Nasdaq Futures: {nqf.get('price','n/a')} ({pct(nqf.get('chg_pct'))})\n"
           f"VIX: {vix.get('price','n/a')}{vix_term}\n"
           f"Gold: {gold.get('price','n/a')} ({pct(gold.get('chg_pct'))})\n"
           f"Brent: {brent.get('price','n/a')} ({pct(brent.get('chg_pct'))})\n"
           f"DXY: {dxy.get('price','n/a')} ({pct(dxy.get('chg_pct'))})\n"
           f"10Y UST: {tnx.get('price','n/a')}% | 2Y UST: {yield_2y or 'n/a'}% | Curve (10-2Y): {curve_spread if curve_spread is not None else 'n/a'}bps\n"
           f"HYG (HY Credit ETF): {hyg.get('price','n/a')} ({pct(hyg.get('chg_pct'))})\n"
           f"LQD (IG Credit ETF): {lqd.get('price','n/a')} ({pct(lqd.get('chg_pct'))})\n"
           f"GBP/USD: {gbp.get('price','n/a')}\nEUR/USD: {eur.get('price','n/a')}\nUSD/JPY: {jpy.get('price','n/a')}\n")

    region_txt = "\n".join(f"{lbl}: {bd.get(sym,{}).get('price','n/a')} ({pct(bd.get(sym,{}).get('chg_pct'))})"
                           for sym,lbl,_,region in _BRIEF_INDICES if region in ("Asia","Europe","UK"))
    news_txt = "\n".join(f"- {n.get('title','')}" for n in (news or [])[:8] if n.get('title')) or "No news available"
    econ_txt = "\n".join(f"- {e.get('date','')[:16]} [{e.get('country','')}] {e.get('event','')} "
                         f"(est: {e.get('estimate','?')}, prev: {e.get('previous','?')})"
                         for e in (econ or [])[:8]) or "No major events scheduled"
    sector_txt = "  |  ".join(f"{name}: {f'{v:+.1f}%' if v is not None else 'n/a'}"
                               for sym,name in _SECTOR_ETFS for v in [sectors.get(sym)]) or "No sector data"
    earnings_txt = "\n".join(f"- {e.get('symbol','')} ({e.get('name','')}) — EPS est: {e.get('epsEstimated','?')}"
                              for e in (earnings_today or [])) or "No major earnings today"

    # Pre-build catalysts from real data (so AI doesn't hallucinate them)
    import json as _json
    catalysts_prebuilt = _build_catalysts(earnings_today, econ)
    catalysts_json = _json.dumps(catalysts_prebuilt, ensure_ascii=False)

    now = datetime.now(); hour = now.hour
    session = "Pre-Market" if hour<8 else "Morning" if hour<12 else "Midday" if hour<14 else "Close Watch" if hour<16 else "After-Hours"

    prompt = (
        f"You are a Senior Portfolio Manager and Cross-Asset Strategist at a tier-1 hedge fund, writing the {session.upper()} MARKET BULLETIN for active retail investors and everyday traders.\n"
        f"THINKING: Apply full institutional-grade analytical rigour — classify the market regime, analyse cross-asset flows, credit signals, VIX term structure, and yield curve. This is how hedge fund analysts actually read markets.\n"
        f"WRITING: Translate that thinking into plain, clear English that a retail investor can understand and act on. Explain what each signal MEANS for their trades and portfolio. Define any technical concept the first time you use it (e.g. 'HYG — the high-yield bond ETF that signals credit risk appetite'). No jargon without explanation. No filler phrases.\n"
        f"CRITICAL: Classify the current market regime (risk-on / risk-off / transition), explain what it means in plain terms, and anchor ALL analysis to it.\n\n"
        f"LIVE MARKET DATA (reference specific figures throughout):\n{mkt}\n"
        f"SECTOR PERFORMANCE:\n{sector_txt}\n\n"
        f"ASIA / EUROPE OVERNIGHT:\n{region_txt}\n\n"
        f"NEWS HEADLINES:\n{news_txt}\n\n"
        f"ECONOMIC CALENDAR:\n{econ_txt}\n\n"
        f"TODAY'S EARNINGS:\n{earnings_txt}\n\n"
        f"LIVE WEB RESEARCH (cite specific events, data points, and analyst views from here):\n{web_context}\n\n"
        f"PRE-BUILT CATALYSTS (use EXACTLY these in the catalysts array — do NOT add fictional ones):\n{catalysts_json}\n\n"
        "Respond ONLY with valid JSON. No markdown fences, no text outside the JSON object. "
        "NEVER use double-quote characters inside string values — use single quotes or dashes instead. "
        "No newline characters inside string values.\n\n"
        '{{"the_call":{{"headline":"One precise sentence naming the dominant market force and its directional implication — include a specific data point (e.g. index level, VIX, spread).",'
        '"bullets":["Regime: [risk-on/risk-off/transition] and the single clearest signal",'
        '"Futures: exact level and % with directional read",'
        '"Vol/Credit: VIX term structure signal + HYG/LQD direction as risk-appetite proxy",'
        '"Rates: 10Y-2Y curve spread and steepening/flattening implication for equities",'
        '"Catalyst 1: specific event with expected market impact",'
        '"Catalyst 2: second event or data release",'
        '"Key level: one specific S&P 500 support or resistance level to watch"]}},'
        '"risk_radar":[{{"flag":"🔴","title":"4-6 word title","detail":"2-3 sentences with specific price levels or data points."}},'
        '{{"flag":"🟡","title":"...","detail":"..."}},{{"flag":"🟢","title":"...","detail":"..."}},'
        '{{"flag":"🔵","title":"...","detail":"..."}}],'
        '"macro_pulse":"6-8 sentences. Name the market regime explicitly. Explain cross-asset dynamics: credit spreads (HYG/LQD), VIX term structure, yield curve. Identify the dominant macro driver. Reference specific data from web context — no generic observations. End with the primary risk to the current regime.",'
        '"equity_flow":"6-8 sentences. Name specific sectors rotating in/out with ETF performance figures. Growth vs value, quality vs cyclical dynamics. Reference institutional positioning or analyst upgrades/downgrades from web context. Name 1-2 stocks driving key sector narratives.",'
        '"overnight_wires":"3-4 sentences. Specific Asian and European index levels, key drivers, and the transmission mechanism to US session today.",'
        '"trade_ideas":['
        '{{"setup":"Individual stock ticker (e.g. NVDA)","type":"stock","thesis":"Plain English explanation of the opportunity — what catalyst, earnings, or news event makes this timely. Written so a retail investor immediately understands the logic.","entry":"Price level only — SHORT, e.g. $220 or $215-220 (no explanation — put reasons in thesis)","stop":"Price level only — SHORT, e.g. $208","target":"Price level only — SHORT, e.g. $245","risk_reward":"e.g. 1:2.5","risk":"What would invalidate this trade — one sentence"}},'
        '{{"setup":"Individual stock ticker (e.g. AAPL)","type":"stock","thesis":"...","entry":"...","stop":"...","target":"...","risk_reward":"...","risk":"..."}},'
        '{{"setup":"Index or macro instrument (e.g. S&P 500, Gold, GBP/USD)","type":"macro","thesis":"...","entry":"...","stop":"...","target":"...","risk_reward":"...","risk":"..."}},'
        '{{"setup":"Sector ETF or thematic (e.g. XLK, XLE)","type":"sector","thesis":"...","entry":"...","stop":"...","target":"...","risk_reward":"...","risk":"..."}},'
        '{{"setup":"Any — stock, commodity, FX or index","type":"stock or macro","thesis":"...","entry":"...","stop":"...","target":"...","risk_reward":"...","risk":"..."}}],'
        f'"catalysts":{catalysts_json}}}'
    )

    if not ANTHROPIC_API_KEY: raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    for attempt in range(3):
        try:
            resp = client.messages.create(model="claude-sonnet-4-6", max_tokens=6000,
                                          messages=[{"role":"user","content":prompt}])
            raw = next(b.text for b in resp.content if hasattr(b,'text')).strip()
            if raw.startswith("```"):
                lines = raw.split("\n"); raw = "\n".join(lines[1:])
                if raw.rstrip().endswith("```"): raw = raw.rstrip()[:-3].rstrip()
            j_start = raw.find('{')
            if j_start >= 0:
                depth=0; in_str=False; esc=False; j_end=j_start
                for ci,ch in enumerate(raw[j_start:], start=j_start):
                    if esc: esc=False; continue
                    if ch=='\\' and in_str: esc=True; continue
                    if ch=='"': in_str=not in_str
                    elif not in_str:
                        if ch=='{': depth+=1
                        elif ch=='}':
                            depth-=1
                            if depth==0: j_end=ci+1; break
                raw = raw[j_start:j_end]
            parsed = json.loads(raw)
            parsed.update({"fallback":False,"timestamp":now.strftime("%H:%M GMT"),
                           "session":session,"generated_at":now.isoformat(),"web_enhanced":bool(TAVILY_API_KEY)})
            return parsed
        except anthropic.APIStatusError as e:
            if e.status_code==529 and attempt<2: time.sleep(5*(attempt+1)); continue
            raise
        except Exception: raise
    raise RuntimeError("Failed to generate bulletin after 3 attempts")

# ── Market data ────────────────────────────────────────────────────────────────
def _build_market_data() -> dict:
    fomc_days, fomc_date = _get_next_fomc()

    # yfinance quick fetches
    vix   = _yf_quick("^VIX");   tnx = _yf_quick("^TNX")
    dxy   = _yf_quick("DX-Y.NYB"); brent = _yf_quick("BZ=F"); gold = _yf_quick("GC=F")

    # FRED economic data (parallel) — returns (value, history_list)
    cpi = nfp = spread = None
    cpi_hist = nfp_hist = spread_hist = []
    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_cpi    = ex.submit(_fetch_cpi_yoy)
            f_nfp    = ex.submit(_fetch_nfp_mom)
            f_spread = ex.submit(_fetch_yield_spread)
            cpi, cpi_hist       = f_cpi.result(timeout=12)
            nfp, nfp_hist       = f_nfp.result(timeout=12)
            spread, spread_hist = f_spread.result(timeout=12)
    except: pass

    # Sector ETF performance + sparklines (parallel)
    sectors = []
    try:
        with ThreadPoolExecutor(max_workers=10) as ex:
            hist_futs = {ex.submit(_fetch_market_history, sym): (sym, name) for sym, name in _SECTOR_ETFS}
            prices = {sym: _yf_quick(sym) for sym, _ in _SECTOR_ETFS}
            for fut in hist_futs:
                sym, name = hist_futs[fut]
                try: hist = fut.result(timeout=15)
                except: hist = []
                p = prices.get(sym, {})
                sectors.append({"symbol": sym, "name": name, "chg_pct": p.get("chg_pct"), "history": hist})
    except: pass

    # Live market movers — top 5 gainers + top 5 losers across US+UK
    movers = []
    _MOVER_UNIVERSE = [
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","JPM","V","UNH",
        "XOM","MA","COST","HD","NFLX","AMD","AVGO","BAC","WMT","CRM",
        "ABBV","LLY","MRK","QCOM","GE","INTC","MS","GS","AMGN","ADBE",
        "SHEL.L","AZN.L","HSBA.L","ULVR.L","BP.L","RIO.L","GSK.L","BARC.L",
        "LLOY.L","NG.L","GLEN.L","AV.L","NWG.L","BA.L","RR.L","BATS.L",
        "VOD.L","REL.L","EXPN.L","SSE.L",
    ]
    try:
        with ThreadPoolExecutor(max_workers=20) as ex:
            futs = {ex.submit(_yf_quick, sym): sym for sym in _MOVER_UNIVERSE}
            mover_data = []
            for fut in futs:
                sym = futs[fut]
                try:
                    d = fut.result(timeout=10)
                    if d.get("chg_pct") is not None:
                        name = sym.replace(".L","")
                        flag = "🇬🇧" if sym.endswith(".L") else "🇺🇸"
                        mover_data.append({"ticker": sym, "name": name, "flag": flag,
                                           "chg_pct": d["chg_pct"], "price": d.get("price")})
                except: pass
            mover_data.sort(key=lambda x: x["chg_pct"], reverse=True)
            gainers = [dict(m, move=f"+{m['chg_pct']:.2f}%") for m in mover_data[:5]]
            losers  = [dict(m, move=f"{m['chg_pct']:.2f}%")  for m in mover_data[-5:][::-1]]
            movers = gainers + losers
    except: pass

    # Major markets prices + sparklines (parallel)
    markets = []
    try:
        with ThreadPoolExecutor(max_workers=8) as ex:
            hist_futures = {ex.submit(_fetch_market_history, sym): (sym,lbl,flag)
                           for sym,lbl,flag in _MAJOR_MARKET_TICKERS}
            prices = {sym: _yf_quick(sym) for sym,_,_ in _MAJOR_MARKET_TICKERS}
            for fut in hist_futures:
                sym,lbl,flag = hist_futures[fut]
                try: hist = fut.result(timeout=20)
                except: hist = []
                p = prices.get(sym,{})
                markets.append({"symbol":sym,"label":lbl,"flag":flag,
                                 "price":p.get("price"),"chg_pct":p.get("chg_pct"),"history":hist})
    except: pass

    tnx_hist = _fetch_market_history("^TNX")
    vix_hist = _fetch_market_history("^VIX")
    dxy_hist = _fetch_market_history("DX-Y.NYB")
    brent_hist = _fetch_market_history("BZ=F")
    gold_hist  = _fetch_market_history("GC=F")

    return {
        "macro_indicators": {
            "fomc_days": fomc_days, "fomc_date": fomc_date,
            "treasury_10y": tnx.get("price"), "treasury_10y_history": tnx_hist,
            "yield_curve_spread": spread, "yield_curve_history": spread_hist,
            "cpi_yoy": cpi, "cpi_history": cpi_hist,
            "nfp_mom": nfp, "nfp_history": nfp_hist,
            "vix": vix.get("price"), "vix_history": vix_hist,
            "dxy": dxy.get("price"), "dxy_history": dxy_hist,
            "brent": brent.get("price"), "brent_history": brent_hist,
            "gold": gold.get("price"), "gold_history": gold_hist,
        },
        "major_markets": markets,
        "sectors": sectors,
        "movers": movers,
        "generated_at": datetime.now().isoformat(),
    }

# ── Earnings tracker ───────────────────────────────────────────────────────────
def _fetch_single_earnings(symbol: str) -> Optional[dict]:
    """Fetch earnings history via yfinance (FMP v3 deprecated Aug 2025)."""
    try:
        t = yf.Ticker(symbol)
        df = t.earnings_dates  # DataFrame: EPS Estimate, Reported EPS, Surprise(%)
        if df is None or df.empty:
            return None
        quarters = []
        estimates = []
        for idx, row in df.iterrows():
            date_str = str(idx)[:7]
            actual = _safe(row.get("Reported EPS"))
            est    = _safe(row.get("EPS Estimate"))
            surp   = _safe(row.get("Surprise(%)"))
            if actual is not None:
                beat_pct = round(surp, 1) if surp is not None else (
                    round((actual - est) / abs(est) * 100, 1) if est and est != 0 else None
                )
                quarters.append({"date": date_str, "actual": actual, "estimate": est, "beat_pct": beat_pct})
            elif est is not None:
                estimates.append({"date": date_str, "eps_est": est})
            if len(quarters) >= 4 and len(estimates) >= 2:
                break
        if not quarters:
            return None
        return {"symbol": symbol, "quarters": quarters[:4], "estimates": estimates[:2]}
    except:
        return None

def _fetch_index_earnings(index: str) -> list:
    tickers = _INDEX_TICKERS.get(index, [])
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futures = {ex.submit(_fetch_single_earnings, sym): sym for sym in tickers}
        for fut in futures:
            try:
                r = fut.result(timeout=25)
                if r: results.append(r)
            except: pass
    return results

_BULLETIN_CACHE_FILE = "/tmp/fintiq_bulletin_cache.json"
_EARNINGS_CACHE_DIR  = "/tmp/fintiq_earnings"

def _save_earnings_to_disk(index: str, data: list):
    try:
        import os; os.makedirs(_EARNINGS_CACHE_DIR, exist_ok=True)
        with open(f"{_EARNINGS_CACHE_DIR}/{index}.json", "w") as f:
            json.dump({"data": data, "_saved_at": time.time()}, f)
    except Exception: pass

def _load_earnings_from_disk(index: str):
    try:
        with open(f"{_EARNINGS_CACHE_DIR}/{index}.json") as f:
            d = json.load(f)
        saved_at = d.get("_saved_at", 0)
        if time.time() - saved_at < _EARNINGS_TTL:
            return d["data"], saved_at
    except Exception: pass
    return None, 0

def _bg_refresh_earnings(index: str):
    global _earnings_cache, _earnings_cached_at, _earnings_refreshing
    if _earnings_refreshing.get(index): return
    _earnings_refreshing[index] = True
    try:
        data = _fetch_index_earnings(index)
        if data:
            _earnings_cache[index] = data
            _earnings_cached_at[index] = time.time()
            _save_earnings_to_disk(index, data)
    except Exception: pass
    finally:
        _earnings_refreshing[index] = False

def _save_bulletin_to_disk(data: dict):
    """Persist bulletin to /tmp so it survives within the same Railway container."""
    try:
        with open(_BULLETIN_CACHE_FILE, "w") as f:
            json.dump({**data, "_saved_at": time.time()}, f)
    except Exception: pass

def _load_bulletin_from_disk() -> dict | None:
    """Load bulletin from /tmp cache on startup (survives container reruns)."""
    try:
        with open(_BULLETIN_CACHE_FILE) as f:
            d = json.load(f)
        saved_at = d.pop("_saved_at", 0)
        age = time.time() - saved_at
        if age < _BULLETIN_TTL:
            return d, saved_at
    except Exception: pass
    return None, 0

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status":"ok","service":"fintiq-api","time":datetime.now().isoformat(),"web_search":bool(TAVILY_API_KEY)}

def _bg_regenerate():
    """Background thread: regenerate bulletin and update cache. Called when cache is stale."""
    global _bulletin_cache, _bulletin_cached_at, _bulletin_refreshing
    if _bulletin_refreshing: return  # already in progress
    _bulletin_refreshing = True
    try:
        fresh = _generate_bulletin()
        _bulletin_cache = fresh
        _bulletin_cached_at = time.time()
        _save_bulletin_to_disk(fresh)  # persist so /tmp survives Railway reruns
    except Exception:
        pass
    finally:
        _bulletin_refreshing = False

@app.on_event("startup")
async def startup_prewarm():
    """On Railway startup: restore /tmp caches, pre-warm anything missing or stale."""
    global _bulletin_cache, _bulletin_cached_at
    global _earnings_cache, _earnings_cached_at

    # ── Bulletin ──
    disk_data, disk_saved_at = _load_bulletin_from_disk()
    if disk_data:
        _bulletin_cache = disk_data
        _bulletin_cached_at = disk_saved_at
        if time.time() - disk_saved_at >= _BULLETIN_TTL:
            threading.Thread(target=_bg_regenerate, daemon=True).start()
    else:
        threading.Thread(target=_bg_regenerate, daemon=True).start()

    # ── Earnings: restore all 4 indices from disk ──
    for idx in _INDEX_TICKERS:
        data, saved_at = _load_earnings_from_disk(idx)
        if data:
            _earnings_cache[idx] = data
            _earnings_cached_at[idx] = saved_at
            # Stale → background refresh (stagger by 30s to avoid hammering yfinance)
            if time.time() - saved_at >= _EARNINGS_TTL:
                delay = list(_INDEX_TICKERS.keys()).index(idx) * 30
                def _deferred(i=idx, d=delay):
                    time.sleep(d)
                    _bg_refresh_earnings(i)
                threading.Thread(target=_deferred, daemon=True).start()
        else:
            # No disk cache — pre-warm S&P 500 first (most used), others staggered
            delay = list(_INDEX_TICKERS.keys()).index(idx) * 60
            def _deferred_fresh(i=idx, d=delay):
                time.sleep(d)
                _bg_refresh_earnings(i)
            threading.Thread(target=_deferred_fresh, daemon=True).start()

@app.get("/bulletin")
def get_bulletin():
    global _bulletin_cache, _bulletin_cached_at, _bulletin_refreshing
    age = time.time() - _bulletin_cached_at
    has_cache = bool(_bulletin_cache)

    # STALE-WHILE-REVALIDATE: if we have any cached version, return it immediately
    # and kick off a background refresh if cache is stale (or expired)
    if has_cache:
        is_stale = age >= _BULLETIN_TTL
        if is_stale and not _bulletin_refreshing:
            # Fire-and-forget background regeneration
            t = threading.Thread(target=_bg_regenerate, daemon=True)
            t.start()
        return {
            **_bulletin_cache,
            "cached": True,
            "age_minutes": round(age / 60),
            "refreshing": _bulletin_refreshing or (is_stale and not _bulletin_refreshing),
        }

    # No cache at all — startup pre-warm should already be generating
    if _bulletin_refreshing:
        # Generation in progress (started by startup pre-warm) — tell frontend to poll
        raise HTTPException(status_code=202, detail="Bulletin generation in progress")
    # Not generating yet — kick it off, return 202
    t = threading.Thread(target=_bg_regenerate, daemon=True)
    t.start()
    raise HTTPException(status_code=202, detail="Bulletin generation started")

@app.get("/bulletin/status")
def bulletin_status():
    age = time.time() - _bulletin_cached_at
    return {
        "has_cache": bool(_bulletin_cache),
        "age_minutes": round(age / 60) if _bulletin_cache else None,
        "refreshing": _bulletin_refreshing,
        "cached_at": datetime.fromtimestamp(_bulletin_cached_at).isoformat() if _bulletin_cache else None,
    }

@app.post("/bulletin/refresh")
def refresh_bulletin(token: Optional[str] = None):
    global _bulletin_cache, _bulletin_cached_at, _bulletin_refreshing
    if token != REFRESH_TOKEN: raise HTTPException(status_code=401, detail="Invalid refresh token")
    if _bulletin_refreshing:
        return {"status": "already_refreshing"}
    t = threading.Thread(target=_bg_regenerate, daemon=True)
    t.start()
    return {"status": "refresh_started"}

@app.get("/market-data")
def get_market_data():
    global _market_cache, _market_cached_at
    age = time.time() - _market_cached_at
    if _market_cache and age < _MARKET_TTL:
        return {**_market_cache,"cached":True,"age_minutes":round(age/60)}
    try:
        _market_cache = _build_market_data(); _market_cached_at = time.time()
        return {**_market_cache,"cached":False,"age_minutes":0}
    except Exception as e:
        if _market_cache: return {**_market_cache,"cached":True,"stale":True}
        raise HTTPException(status_code=503, detail=str(e))

@app.get("/debug-earnings")
def debug_earnings(symbol: str = "AAPL"):
    """Debug: test yfinance earnings_dates for a single ticker"""
    try:
        result = _fetch_single_earnings(symbol)
        return {"symbol": symbol, "result": result}
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

@app.get("/earnings")
def get_earnings(index: str = "sp500", force: bool = False):
    if index not in _INDEX_TICKERS:
        raise HTTPException(status_code=400, detail=f"Unknown index: {index}")
    global _earnings_cache, _earnings_cached_at

    age = time.time() - _earnings_cached_at.get(index, 0)
    has_cache = bool(_earnings_cache.get(index))

    # STALE-WHILE-REVALIDATE: return cached immediately, refresh in background if stale
    if has_cache and not force:
        is_stale = age >= _EARNINGS_TTL
        if is_stale and not _earnings_refreshing.get(index):
            t = threading.Thread(target=_bg_refresh_earnings, args=(index,), daemon=True)
            t.start()
        return {
            "index": index,
            "data": _earnings_cache[index],
            "cached": True,
            "age_hours": round(age / 3600, 1),
            "refreshing": _earnings_refreshing.get(index, False) or is_stale,
            "count": len(_earnings_cache[index]),
        }

    # No cache — trigger background fetch, return 202 so frontend polls
    if _earnings_refreshing.get(index):
        raise HTTPException(status_code=202, detail=f"Earnings data for {index} loading")
    t = threading.Thread(target=_bg_refresh_earnings, args=(index,), daemon=True)
    t.start()
    raise HTTPException(status_code=202, detail=f"Earnings data for {index} loading")


# ── Deep Dive — Fundamentals ────────────────────────────────────────────────────

def _safe_float(v):
    try: return float(v) if v is not None else None
    except: return None

def _fmt_large(v):
    """Format large numbers: 1.23T, 456.7B, 12.3M"""
    if v is None: return None
    v = float(v)
    if abs(v) >= 1e12: return f"{v/1e12:.2f}T"
    if abs(v) >= 1e9:  return f"{v/1e9:.2f}B"
    if abs(v) >= 1e6:  return f"{v/1e6:.2f}M"
    return f"{v:.2f}"

def _compute_tsr(hist, info, financials, cashflow, balance_sheet, q_financials):
    """Port of _comp_compute_tsr from Streamlit — returns simple/annual/quarterly TSR."""
    import pandas as pd, numpy as np
    res = {'simple': {}, 'annual': [], 'quarterly': [], 'error': None}
    try:
        if hist is None or hist.empty:
            res['error'] = 'No price history'; return res

        def fv(v):
            try: return float(v) if v is not None else None
            except: return None

        h = hist.copy()
        h.index = pd.to_datetime(h.index).tz_localize(None)
        close = h['Close']
        divs  = h['Dividends'] if 'Dividends' in h.columns else pd.Series(0.0, index=h.index)
        p_now = float(close.iloc[-1])
        shares = fv(info.get('sharesOutstanding') or info.get('impliedSharesOutstanding')) or 1e9

        # 1. Simple TSR
        def simple(days, years):
            if len(close) < max(days, 2): return {}
            idx0 = -min(days, len(close)-1)
            p0 = float(close.iloc[idx0])
            if p0 <= 0: return {}
            d  = float(divs.iloc[idx0:].sum())
            pr = (p_now - p0) / p0
            dy = d / p0
            tsr = pr + dy
            date0 = str(close.index[idx0])[:10]
            date1 = str(close.index[-1])[:10]
            if years > 1:
                ann = lambda x: (1+x)**(1/years)-1 if x is not None else None
                return {'tsr': ann(tsr), 'price_return': ann(pr), 'div_yield': dy/years,
                        'cumulative_tsr': tsr, 'open_price': p0, 'close_price': p_now,
                        'dividends': d, 'open_date': date0, 'close_date': date1}
            return {'tsr': tsr, 'price_return': pr, 'div_yield': dy,
                    'open_price': p0, 'close_price': p_now,
                    'dividends': d, 'open_date': date0, 'close_date': date1}

        res['simple'] = {'1y': simple(252,1), '3y': simple(756,3), '5y': simple(1260,5)}

        # 2. Annual Enhanced TSR
        fin = financials; cf = cashflow; bs = balance_sheet
        if fin is not None and not fin.empty and cf is not None and not cf.empty:
            def row(df, *keys):
                for k in keys:
                    if df is not None and k in df.index: return df.loc[k]
                return None

            rev_row  = row(fin, 'Total Revenue', 'Revenue')
            ebit_row = row(fin, 'EBIT', 'Operating Income')
            ni_row   = row(fin, 'Net Income', 'Net Income Common Stockholders')
            fcf_row  = row(cf,  'Free Cash Flow')
            div_row  = row(cf,  'Common Stock Dividend Paid', 'Cash Dividends Paid', 'Dividends Paid')
            debt_row = row(bs,  'Total Debt', 'Long Term Debt And Capital Lease Obligation') if bs is not None else None
            cash_row = row(bs,  'Cash And Cash Equivalents', 'Cash Cash Equivalents And Short Term Investments') if bs is not None else None

            fy_dates = sorted([c for c in fin.columns if hasattr(c, 'year')], reverse=True)

            for fi in range(min(len(fy_dates) - 1, 3)):
                try:
                    dt1, dt0 = fy_dates[fi], fy_dates[fi+1]

                    def price_at(dt):
                        idx = close.index.searchsorted(pd.Timestamp(dt))
                        return float(close.iloc[min(idx, len(close)-1)])

                    p1, p0 = price_at(dt1), price_at(dt0)
                    if p0 <= 0: continue

                    div_yr = float(divs.loc[dt0:dt1].sum()) if not divs.loc[dt0:dt1].empty else 0.0
                    annual_tsr = (p1 - p0 + div_yr) / p0
                    price_ret  = (p1 - p0) / p0
                    div_yield  = div_yr / p0

                    def col(r, dt):
                        try: return fv(r[dt]) if r is not None and dt in r.index else None
                        except: return None

                    rev1  = col(rev_row,  dt1); rev0  = col(rev_row,  dt0)
                    ebit1 = col(ebit_row, dt1); ebit0 = col(ebit_row, dt0)
                    ni1   = col(ni_row,   dt1); ni0   = col(ni_row,   dt0)
                    fcf1  = col(fcf_row,  dt1)
                    debt1 = abs(col(debt_row, dt1) or 0); debt0 = abs(col(debt_row, dt0) or 0)
                    cash1 = abs(col(cash_row, dt1) or 0); cash0 = abs(col(cash_row, dt0) or 0)

                    mcap0 = p0 * shares; mcap1 = p1 * shares
                    ev0   = mcap0 + debt0 - cash0; ev1 = mcap1 + debt1 - cash1
                    ev0ps = ev0 / shares if shares > 0 and ev0 > 0 else None
                    if not ev0ps: continue

                    a = ((rev1 - rev0) / shares / ev0ps) if rev1 and rev0 else None
                    delta_net_debt_ps = ((debt1 - cash1) - (debt0 - cash0)) / shares
                    b = -delta_net_debt_ps / ev0ps
                    om1 = ebit1/rev1 if ebit1 and rev1 and rev1>0 else None
                    om0 = ebit0/rev0 if ebit0 and rev0 and rev0>0 else None
                    d_  = ((om1-om0)*(rev0/shares)/ev0ps) if (om1 is not None and om0 is not None and rev0) else None
                    e_  = (a*(om1-om0)) if (a is not None and om1 is not None and om0 is not None) else None
                    perf = (a or 0)+(b or 0)+(d_ or 0)+(e_ or 0)

                    eps0 = ni0/shares if ni0 else None
                    g    = eps0/ev0ps if eps0 else None
                    fcf_ps = fcf1/shares if fcf1 else None
                    h_   = fcf_ps/ev0ps if fcf_ps and ev0ps else None
                    yield_bucket = (g or 0) + (h_ or 0)
                    val_bucket   = annual_tsr - perf - yield_bucket

                    eps1_tr = ni1/shares if ni1 else None
                    eps0_tr = ni0/shares if ni0 else None
                    pe1 = p1/eps1_tr if eps1_tr and eps1_tr>0 else None
                    pe0 = p0/eps0_tr if eps0_tr and eps0_tr>0 else None
                    eps_g = (ni1-ni0)/abs(ni0) if ni0 and ni1 and ni0!=0 else None
                    pe_ch = (pe1-pe0)/abs(pe0) if pe0 and pe1 else None
                    inter = (eps_g*pe_ch) if eps_g is not None and pe_ch is not None else None

                    res['annual'].append({
                        'year': str(dt1.year) if hasattr(dt1,'year') else str(dt1)[:4],
                        'tsr': annual_tsr, 'price_return': price_ret, 'div_yield': div_yield,
                        'fy_start_date': str(dt0)[:10], 'fy_start_price': p0,
                        'fy_end_date': str(dt1)[:10],   'fy_end_price': p1,
                        'fy_dividends': div_yr,
                        'performance': perf, 'yield_bucket': yield_bucket, 'valuation': val_bucket,
                        'sales_growth_contrib': a, 'invest_drag': b,
                        'margin_change_contrib': d_, 'earnings_yield': g, 'fcf_yield': h_,
                        'eps_growth': eps_g, 'pe_change': pe_ch, 'interaction': inter,
                        'op_margin_start': om0, 'op_margin_end': om1, 'pe_start': pe0, 'pe_end': pe1,
                    })
                except Exception: continue

        # 3. Quarterly TSR
        qfin = q_financials
        if qfin is not None and not qfin.empty:
            def qrow(df, *keys):
                for k in keys:
                    if df is not None and k in df.index: return df.loc[k]
                return None
            q_ni_row = qrow(qfin, 'Net Income', 'Net Income Common Stockholders')
            q_dates  = sorted([c for c in qfin.columns if hasattr(c, 'year')], reverse=True)

            for qi in range(min(len(q_dates)-1, 6)):
                try:
                    qdt1, qdt0 = q_dates[qi], q_dates[qi+1]
                    def qprice(dt):
                        idx = close.index.searchsorted(pd.Timestamp(dt))
                        return float(close.iloc[min(idx, len(close)-1)])
                    qp1, qp0 = qprice(qdt1), qprice(qdt0)
                    if qp0 <= 0: continue
                    qdivs = float(divs.loc[qdt0:qdt1].sum()) if not divs.loc[qdt0:qdt1].empty else 0.0
                    qtsr  = (qp1 - qp0 + qdivs) / qp0
                    qdy   = qdivs / qp0
                    qpr   = (qp1 - qp0) / qp0
                    def qcol(r, dt):
                        try: return fv(r[dt]) if r is not None and dt in r.index else None
                        except: return None
                    qni1 = qcol(q_ni_row, qdt1); qni0 = qcol(q_ni_row, qdt0)
                    qeps1 = qni1/shares if qni1 else None; qeps0 = qni0/shares if qni0 else None
                    qpe1  = qp1/(qeps1*4) if qeps1 and qeps1>0 else None
                    qpe0  = qp0/(qeps0*4) if qeps0 and qeps0>0 else None
                    qeps_g = (qni1-qni0)/abs(qni0) if qni0 and qni1 and qni0!=0 else None
                    qpe_ch = (qpe1-qpe0)/abs(qpe0) if qpe0 and qpe1 else None
                    qinter = (qeps_g*qpe_ch) if qeps_g is not None and qpe_ch is not None else None
                    qm   = qdt1.month if hasattr(qdt1,'month') else 1
                    qlbl = f"Q{(qm-1)//3+1} {qdt1.year if hasattr(qdt1,'year') else ''}"
                    res['quarterly'].append({
                        'period': qlbl, 'tsr': qtsr, 'price_return': qpr, 'div_yield': qdy,
                        'q_start_date': str(qdt0)[:10], 'q_start_price': qp0,
                        'q_end_date': str(qdt1)[:10],   'q_end_price': qp1,
                        'q_dividends': qdivs,
                        'eps_growth': qeps_g, 'pe_change': qpe_ch, 'interaction': qinter,
                        'pe_start': qpe0, 'pe_end': qpe1,
                    })
                except Exception: continue

    except Exception as te:
        res['error'] = str(te)[:200]
    return res


# ── Module-level NaN sanitiser (shared by all background tasks) ────────────────
import math as _math
def _clean(obj):
    if isinstance(obj, float):
        return None if (_math.isnan(obj) or _math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return obj

# ── Fundamentals job cache ─────────────────────────────────────────────────────
# Stores: {ticker: {status: 'processing'|'done'|'error', data: dict|None, ts: float, error: str}}
_fund_jobs: dict = {}
_FUND_TTL = 5 * 60  # 5 min cache


def _run_fundamentals(ticker: str):
    """Run in a background thread. Stores result in _fund_jobs[ticker]."""
    try:
        import pandas as pd
        t = yf.Ticker(ticker)

        def _get_info():
            try: return t.info or {}
            except: return {}
        def _get_hist():
            try: return t.history(period="3y", auto_adjust=True)
            except: return None
        def _get_fin():
            try: return t.financials
            except: return None
        def _get_cf():
            try: return t.cashflow
            except: return None
        def _get_bs():
            try: return t.balance_sheet
            except: return None
        def _get_qfin():
            try: return t.quarterly_financials
            except: return None
        def _get_qbs():
            try: return t.quarterly_balance_sheet
            except: return None
        def _get_qcf():
            try: return t.quarterly_cashflow
            except: return None

        # All 8 fetches run truly in parallel; background thread has no Railway timeout
        _ex = ThreadPoolExecutor(max_workers=8)
        _futs = {
            'info': _ex.submit(_get_info),
            'hist': _ex.submit(_get_hist),
            'fin':  _ex.submit(_get_fin),
            'cf':   _ex.submit(_get_cf),
            'bs':   _ex.submit(_get_bs),
            'qfin': _ex.submit(_get_qfin),
            'qbs':  _ex.submit(_get_qbs),
            'qcf':  _ex.submit(_get_qcf),
        }
        # Wait up to 55s per future (background thread can run as long as needed)
        def _safe(fut, default=None, timeout=55):
            try: return fut.result(timeout=timeout)
            except: return default

        info  = _safe(_futs['info'], {})
        hist  = _safe(_futs['hist'])
        fin   = _safe(_futs['fin'])
        cf    = _safe(_futs['cf'])
        bs    = _safe(_futs['bs'])
        qfin  = _safe(_futs['qfin'])
        qbs   = _safe(_futs['qbs'])
        qcf   = _safe(_futs['qcf'])
        _ex.shutdown(wait=False)

        # Validate
        has_hist = hist is not None and not hist.empty if hist is not None else False
        has_fin  = fin is not None and not fin.empty if fin is not None else False
        if not has_hist and not has_fin:
            _fund_jobs[ticker] = {'status': 'error', 'error': f"Ticker '{ticker}' not found or no data available", 'ts': time.time()}
            return

        hist_1y = hist

        def fv(v):
            try: return float(v) if v is not None else None
            except: return None

        def row(df, *keys):
            for k in keys:
                if df is not None and k in df.index:
                    return df.loc[k]
            return None

        def col_val(df, *keys):
            """Latest column value from financial statement"""
            r = row(df, *keys)
            if r is None: return None
            for c in sorted(r.index, reverse=True):
                v = fv(r[c])
                if v is not None: return v
            return None

        # ── Currency normalisation ──
        # For LSE stocks yfinance sets currency='GBp' (pence).
        # ONLY price-quote fields are in pence; financial statement data and per-share
        # values (EPS, DPS) are already in the reporting currency (GBP or USD).
        # So we divide ONLY: currentPrice, 52w high/low, MA50/MA200, marketCap,
        # enterpriseValue, and analyst target prices — nothing from income/CF/BS.
        raw_currency = info.get('currency', 'USD')
        gbp_price_scale = 0.01 if raw_currency == 'GBp' else 1.0
        display_currency = 'GBP' if raw_currency == 'GBp' else raw_currency

        # ── Current price ──
        price = fv(info.get('currentPrice') or info.get('regularMarketPrice') or
                   info.get('previousClose'))
        if price is None and hist is not None and not hist.empty:
            price = float(hist['Close'].iloc[-1])
        if price: price = round(price * gbp_price_scale, 4)

        # ── Analyst consensus ──
        rec_mean = fv(info.get('recommendationMean'))
        rec_key  = info.get('recommendationKey', '')
        try:
            recs_df  = t.recommendations
            if recs_df is not None and not recs_df.empty:
                last = recs_df.iloc[-1] if 'period' not in recs_df.columns else \
                       recs_df[recs_df['period'] == '0m'].iloc[0] if '0m' in recs_df['period'].values else recs_df.iloc[-1]
                strong_buy = int(last.get('strongBuy', 0))
                buy        = int(last.get('buy', 0))
                hold       = int(last.get('hold', 0))
                sell       = int(last.get('sell', 0))
                strong_sell= int(last.get('strongSell', 0))
            else:
                strong_buy=buy=hold=sell=strong_sell=0
        except:
            strong_buy=buy=hold=sell=strong_sell=0

        # ── Growth table (4 years) ──
        growth_table = []
        rev_row  = row(fin, 'Total Revenue', 'Revenue')
        ebit_row = row(fin, 'EBIT', 'Operating Income')
        ni_row   = row(fin, 'Net Income', 'Net Income Common Stockholders')
        fcf_row_ = row(cf, 'Free Cash Flow')
        shares_out = fv(info.get('sharesOutstanding') or info.get('impliedSharesOutstanding')) or 1e9

        if fin is not None and not fin.empty:
            fy_dates = sorted([c for c in fin.columns if hasattr(c, 'year')], reverse=True)
            for fi in range(min(len(fy_dates), 4)):
                dt = fy_dates[fi]
                def gcol(r):
                    try: return fv(r[dt]) if r is not None and dt in r.index else None
                    except: return None
                rev  = gcol(rev_row); ni   = gcol(ni_row); ebit = gcol(ebit_row)
                fcf_ = gcol(fcf_row_)
                # Financial statement data is already in reporting currency — no GBp scaling
                # Previous year for growth rates
                rev_prev = None; ni_prev = None
                if fi + 1 < len(fy_dates):
                    dt_prev = fy_dates[fi+1]
                    def gcol_p(r):
                        try: return fv(r[dt_prev]) if r is not None and dt_prev in r.index else None
                        except: return None
                    rev_prev = gcol_p(rev_row); ni_prev  = gcol_p(ni_row)

                rev_g  = (rev - rev_prev) / abs(rev_prev) if rev and rev_prev and rev_prev != 0 else None
                nopat  = ebit * 0.75 if ebit else None  # approx NOPAT = EBIT × (1-tax)
                nopat_prev = None
                if fi + 1 < len(fy_dates):
                    ebit_prev_v = None
                    try:
                        dt_prev = fy_dates[fi+1]
                        ebit_prev_v = fv(ebit_row[dt_prev]) if ebit_row is not None and dt_prev in ebit_row.index else None
                    except: pass
                    nopat_prev = ebit_prev_v * 0.75 if ebit_prev_v else None
                nopat_g = (nopat - nopat_prev) / abs(nopat_prev) if nopat and nopat_prev and nopat_prev != 0 else None
                ni_g   = (ni - ni_prev) / abs(ni_prev) if ni and ni_prev and ni_prev != 0 else None
                eps    = ni / shares_out if ni else None
                om     = ebit / rev if ebit and rev and rev > 0 else None
                # ROIC approx: NOPAT / (Total Assets - Current Liabilities)
                roic   = None
                try:
                    ta  = col_val(bs, 'Total Assets')
                    cl  = col_val(bs, 'Current Liabilities', 'Total Current Liabilities')
                    if ta and cl and nopat: roic = nopat / (ta - cl) if (ta - cl) > 0 else None
                except: pass
                # Investment rate = (CapEx + ΔWorkingCapital) / NOPAT
                inv_rate = None
                try:
                    capex = col_val(cf, 'Capital Expenditure', 'Purchase Of Property Plant And Equipment')
                    if capex and nopat and nopat != 0: inv_rate = abs(capex) / nopat
                except: pass

                growth_table.append({
                    'year': str(dt.year) if hasattr(dt,'year') else str(dt)[:4],
                    'revenue': _fmt_large(rev),
                    'revenue_growth': round(rev_g * 100, 1) if rev_g is not None else None,
                    'nopat_growth': round(nopat_g * 100, 1) if nopat_g is not None else None,
                    'eps': round(eps, 2) if eps else None,
                    'eps_growth': round(ni_g * 100, 1) if ni_g is not None else None,
                    'roic': round(roic * 100, 1) if roic is not None else None,
                    'op_margin': round(om * 100, 1) if om is not None else None,
                    'nopat_margin': round(nopat / rev * 100, 1) if nopat and rev and rev > 0 else (round(om * 0.75 * 100, 1) if om is not None else None),
                    'inv_rate': round(inv_rate * 100, 1) if inv_rate is not None else None,
                })

        # ── Options data ──
        options_data = {}
        try:
            exp_dates = t.options
            if exp_dates:
                chain = t.option_chain(exp_dates[0])
                calls = chain.calls; puts = chain.puts
                call_oi = float(calls['openInterest'].sum()) if 'openInterest' in calls.columns else 0
                put_oi  = float(puts['openInterest'].sum())  if 'openInterest' in puts.columns  else 0
                put_call_ratio = round(put_oi / call_oi, 2) if call_oi > 0 else None
                # ATM IV (nearest strike to current price)
                if price:
                    atm_call = calls.iloc[(calls['strike'] - price).abs().argsort()[:1]]
                    iv = float(atm_call['impliedVolatility'].iloc[0]) if 'impliedVolatility' in atm_call.columns else None
                else:
                    iv = None
                options_data = {
                    'expiry_dates': list(exp_dates[:5]),
                    'put_call_ratio': put_call_ratio,
                    'call_oi': int(call_oi),
                    'put_oi': int(put_oi),
                    'atm_iv': round(iv * 100, 1) if iv else None,
                    'total_expirations': len(exp_dates),
                }
        except Exception as oe:
            options_data = {'error': str(oe)[:80]}

        # ── Competitors — parallel fetch with 10s timeout ──
        competitors = []
        _PEER_MAP = {
            'AAPL': ['MSFT','GOOGL','META'], 'MSFT': ['AAPL','GOOGL','AMZN'],
            'GOOGL': ['META','MSFT','AAPL'], 'AMZN': ['MSFT','GOOGL','WMT'],
            'TSLA': ['F','GM','RIVN'], 'META': ['SNAP','GOOGL','PINS'],
            'NVDA': ['AMD','INTC','QCOM'], 'JPM': ['BAC','GS','MS'],
            'NFLX': ['DIS','WBD','PARA'], 'V': ['MA','AXP','PYPL'],
            'AMGN': ['GILD','BIIB','REGN'], 'PFE': ['MRK','JNJ','ABBV'],
            'WMT': ['COST','TGT','AMZN'], 'COST': ['WMT','TGT','BJ'],
            'SHEL.L': ['BP.L','XOM','CVX'], 'BP.L': ['SHEL.L','XOM','CVX'],
            'XOM': ['CVX','SHEL.L','BP.L'], 'BRKB': ['MKL','FFH','AIG'],
            'TSM': ['INTC','ASML','AMAT'],
        }
        peer_tickers = _PEER_MAP.get(ticker, [])

        def _fetch_peer(pt):
            try:
                pi = yf.Ticker(pt).fast_info
                pinfo = yf.Ticker(pt).info or {}
                p_rev_g = fv(pinfo.get('revenueGrowth'))
                p_om    = fv(pinfo.get('operatingMargins'))
                p_roe   = fv(pinfo.get('returnOnEquity'))
                p_cap   = fv(pinfo.get('marketCap'))
                p_fpe   = fv(pinfo.get('forwardPE'))
                # ROIC approx for peer
                p_nopat, p_ic = None, None
                p_ebit = fv(pinfo.get('ebitda'))  # rough proxy
                p_ta   = fv(pinfo.get('totalAssets'))
                p_cl   = fv(pinfo.get('totalCurrentLiabilities'))
                if p_ebit and p_ta and p_cl and (p_ta-p_cl)>0:
                    p_nopat = p_ebit * 0.75
                    p_roic  = round(p_nopat/(p_ta-p_cl)*100,1)
                else: p_roic = None
                return {
                    'ticker': pt,
                    'name': pinfo.get('shortName', pt),
                    'market_cap': _fmt_large(p_cap),
                    'revenue_growth': round(p_rev_g*100,1) if p_rev_g else None,
                    'op_margin': round(p_om*100,1) if p_om else None,
                    'roe': round(p_roe*100,1) if p_roe else None,
                    'roic': p_roic,
                    'forward_pe': round(p_fpe,1) if p_fpe else None,
                }
            except: return None

        if peer_tickers:
            with ThreadPoolExecutor(max_workers=3) as ex:
                results = list(ex.map(_fetch_peer, peer_tickers[:3]))
            competitors = [r for r in results if r]

        # Also compute ROIC for subject ticker (for peer table)
        subj_roic = growth_table[0].get('roic') if growth_table else None
        subj_fpe  = round(fv(info.get('forwardPE')),1) if fv(info.get('forwardPE')) else None

        # ── Valuation inputs (for Section 2 DCF) ──
        _pretax   = col_val(fin, 'Pretax Income', 'Income Before Tax')
        _tax_prov = col_val(fin, 'Tax Provision', 'Income Tax Expense')
        _int_exp  = col_val(fin, 'Interest Expense', 'Net Interest Income')
        _total_debt = fv(info.get('totalDebt'))
        _eff_tax  = abs(_tax_prov) / abs(_pretax) if _pretax and _tax_prov and _pretax != 0 else None
        _eff_tax  = max(0.05, min(0.45, _eff_tax)) if _eff_tax else None  # clamp to sensible range
        _kd_raw   = abs(_int_exp) / _total_debt if _int_exp and _total_debt and _total_debt > 0 else None
        _bvps     = fv(info.get('bookValue'))
        _rev_raw  = fv(info.get('totalRevenue'))

        # ── TSR ──
        tsr_data = _compute_tsr(hist, info, fin, cf, bs, qfin)

        # Scale TSR absolute price fields GBp→GBP (hist['Close'] is in pence for LSE stocks)
        if gbp_price_scale != 1.0 and tsr_data:
            _price_fields = ('open_price','close_price','dividends')
            for _period, _v in tsr_data.get('simple', {}).items():
                if isinstance(_v, dict):
                    for _f in _price_fields:
                        if _f in _v and _v[_f] is not None:
                            _v[_f] = round(_v[_f] * gbp_price_scale, 4)
            for _row in tsr_data.get('annual', []):
                for _f in ('fy_start_price','fy_end_price','fy_dividends'):
                    if _f in _row and _row[_f] is not None:
                        _row[_f] = round(_row[_f] * gbp_price_scale, 4)
            for _row in tsr_data.get('quarterly', []):
                for _f in ('q_start_price','q_end_price','q_dividends'):
                    if _f in _row and _row[_f] is not None:
                        _row[_f] = round(_row[_f] * gbp_price_scale, 4)

        # ── Assemble overview ──
        mc = fv(info.get('marketCap'))
        ev = fv(info.get('enterpriseValue'))
        fcf_val = col_val(cf, 'Free Cash Flow')
        eps_ttm = fv(info.get('trailingEps'))   # already in reporting currency (£/$ per share)
        dps     = fv(info.get('lastDividendValue'))  # already in reporting currency

        # MarketCap and EV from yfinance for GBp stocks are quote-price × shares → in pence
        if gbp_price_scale != 1.0:
            mc = mc * gbp_price_scale if mc is not None else None
            ev = ev * gbp_price_scale if ev is not None else None

        fcf_ps  = fcf_val / shares_out if fcf_val and shares_out else None
        beta    = fv(info.get('beta'))
        wacc    = None  # computed in valuation section
        short_pct = fv(info.get('shortPercentOfFloat'))
        short_ratio = fv(info.get('shortRatio'))

        # 52w range position — price-quote fields, divide GBp→GBP
        hi52 = fv(info.get('fiftyTwoWeekHigh'))
        lo52 = fv(info.get('fiftyTwoWeekLow'))
        if gbp_price_scale != 1.0:
            hi52 = hi52 * gbp_price_scale if hi52 is not None else None
            lo52 = lo52 * gbp_price_scale if lo52 is not None else None
        range_pos = round((price - lo52) / (hi52 - lo52) * 100, 1) if price and hi52 and lo52 and hi52 != lo52 else None

        # MA distances — price-quote fields
        ma50  = fv(info.get('fiftyDayAverage'))
        ma200 = fv(info.get('twoHundredDayAverage'))
        if gbp_price_scale != 1.0:
            ma50  = ma50  * gbp_price_scale if ma50  is not None else None
            ma200 = ma200 * gbp_price_scale if ma200 is not None else None
        vs_ma50  = round((price/ma50 - 1)*100, 1)  if price and ma50  else None
        vs_ma200 = round((price/ma200 - 1)*100, 1) if price and ma200 else None

        # FY end / Quarter end
        fy_end = None; q_end = None
        if fin is not None and not fin.empty:
            fy_dates = sorted([c for c in fin.columns if hasattr(c,'year')], reverse=True)
            if fy_dates: fy_end = str(fy_dates[0])[:10]
        if qfin is not None and not qfin.empty:
            q_dates_all = sorted([c for c in qfin.columns if hasattr(c,'year')], reverse=True)
            if q_dates_all: q_end = str(q_dates_all[0])[:10]

        # FF4 factor (from screener JSON) — field names: signal, alpha, pval, beta, smb, hml, mom
        ff4 = None
        try:
            ff_url = "https://fintiq.uk/screener-data-2y.json"
            ff_resp = requests.get(ff_url, timeout=8)
            if ff_resp.ok:
                ff_raw = ff_resp.json()
                # JSON is either a list or {"stocks": [...]}
                ff_list = ff_raw if isinstance(ff_raw, list) else ff_raw.get('stocks', [])
                ff4 = next((s for s in ff_list if s.get('ticker') == ticker), None)
        except: pass

        # ── FF4 proxy estimate (when OLS data not available) ──
        if not ff4 and hist is not None and not hist.empty:
            try:
                import numpy as np
                _beta   = fv(info.get('beta'))
                _pb     = fv(info.get('priceToBook'))
                _mc_raw = fv(info.get('marketCap'))

                # SMB: large cap → negative (behaves like large), small cap → positive
                if _mc_raw:
                    _mc_b = _mc_raw * gbp_price_scale  # already adjusted for GBp
                    if _mc_b > 10e9:   _smb_est = round(-0.3 - min((_mc_b - 10e9) / 500e9, 0.7), 2)
                    elif _mc_b > 2e9:  _smb_est = 0.1
                    else:              _smb_est = 0.5
                else:
                    _smb_est = None

                # HML: high P/B = growth = negative HML; low P/B = value = positive HML
                if _pb:
                    if _pb > 5:    _hml_est = round(-0.5 - min((_pb - 5) / 20, 0.5), 2)
                    elif _pb > 2:  _hml_est = round(-0.1 - (_pb - 2) / 30, 2)
                    elif _pb > 1:  _hml_est = 0.2
                    else:          _hml_est = 0.6
                else:
                    _hml_est = None

                # MOM: annualised 1yr price momentum
                _close = hist['Close']
                _n_mom = min(252, len(_close) - 1)
                _mom_ret = (_close.iloc[-1] - _close.iloc[-_n_mom]) / _close.iloc[-_n_mom] if _n_mom > 20 else None
                _mom_est = round(_mom_ret * 0.3, 2) if _mom_ret is not None else None  # scaled loading

                # Proxy signal: simple heuristic from beta + momentum
                _sig = 'amber'
                if _beta and _mom_ret is not None:
                    if _mom_ret > 0.15 and _beta < 1.5:  _sig = 'green'
                    elif _mom_ret < -0.1 or (_beta and _beta > 2.0): _sig = 'red'

                ff4 = {
                    'ticker': ticker,
                    'signal': _sig,
                    'alpha': None,   # cannot estimate alpha without OLS
                    'pval': None,
                    'beta': round(_beta, 3) if _beta else None,
                    'smb': _smb_est,
                    'hml': _hml_est,
                    'mom': _mom_est,
                    'estimated': True,   # flag: proxy, not OLS
                }
            except:
                pass

        # ── FF4 AI commentary ──
        if ff4 and not ff4.get('error') and ANTHROPIC_API_KEY:
            try:
                _is_proxy = ff4.get('estimated', False)
                _cli = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

                if _is_proxy:
                    # Proxy path — no alpha/p-value, explain the estimation approach
                    _1yr_ret = None
                    if hist is not None and not hist.empty:
                        _cl = hist['Close']
                        _n = min(252, len(_cl) - 1)
                        if _n > 20:
                            _1yr_ret = round((_cl.iloc[-1] - _cl.iloc[-_n]) / _cl.iloc[-_n] * 100, 1)

                    _ff_prompt = (
                        f"You are explaining estimated Fama-French factor characteristics to a retail investor for {ticker}. "
                        f"IMPORTANT: This is a proxy estimate derived from observable data, NOT an OLS regression. "
                        f"No formal alpha or p-value can be computed. Be explicit about this. "
                        f"\n\nEstimated factor profile: "
                        f"Beta={ff4.get('beta')} (from yfinance — real figure), "
                        f"SMB (size)={ff4.get('smb')} (estimated from market cap), "
                        f"HML (value)={ff4.get('hml')} (estimated from P/B ratio), "
                        f"MOM (momentum)={ff4.get('mom')} (estimated from 1yr price return). "
                        f"1yr actual price return: {(str(_1yr_ret)+'%') if _1yr_ret is not None else 'unavailable'}. "
                        f"Directional signal: {ff4.get('signal')}. "
                        f"\n\nWrite exactly 4 complete sentences in plain prose — no headers, no bullet points, no markdown. "
                        f"Sentence 1: Clearly state this is a proxy estimate (not OLS regression) — explain what that means: "
                        f"we derive factor tilts from observable data (market cap → size, P/B → value, price return → momentum) rather than statistical regression. "
                        f"Sentence 2: Interpret the beta and the estimated factor tilts — what do they say about {ticker}'s risk character? Use the numbers. "
                        f"Sentence 3: What does the directional signal ({ff4.get('signal')}) suggest, and what are the key risks given the factor profile? "
                        f"Sentence 4: Concrete takeaway — what should the investor watch for, and note that for a full OLS-based factor analysis, the stock needs to be in the Fintiq screener universe. "
                        f"Plain prose, real numbers, complete all 4 sentences."
                    )
                    _max_tok = 440
                else:
                    # OLS path — full breakdown with alpha
                    _actual_2yr = None
                    _model_predicted = None
                    if hist is not None and not hist.empty and len(hist) >= 2:
                        _close = hist['Close']
                        _n_days = min(504, len(_close) - 1)
                        _p0 = float(_close.iloc[-_n_days])
                        _p1 = float(_close.iloc[-1])
                        if _p0 > 0:
                            _total_2yr = (_p1 - _p0) / _p0
                            _actual_2yr = round(((1 + _total_2yr) ** 0.5 - 1) * 100, 1)
                    if _actual_2yr is not None and ff4.get('alpha') is not None:
                        _model_predicted = round(_actual_2yr - float(ff4.get('alpha')), 1)

                    _breakdown = ""
                    if _actual_2yr is not None and _model_predicted is not None:
                        _breakdown = (
                            f"Actual 2yr annualised return: {_actual_2yr:+.1f}%/yr. "
                            f"Model predicted: {_model_predicted:+.1f}%/yr (what beta/SMB/HML/MOM exposures explain). "
                            f"Alpha = Actual − Model = {ff4.get('alpha'):+}%/yr. "
                        )
                    _ff_prompt = (
                        f"You are explaining Fama-French 4-factor results to a retail investor for {ticker}. "
                        f"Alpha is the annualised intercept from a 2-year OLS regression of {ticker}'s weekly returns against four risk factors. "
                        f"Model Predicted Return = risk-free rate + (beta × market premium) + (SMB × size premium) + (HML × value premium) + (MOM × momentum premium). "
                        f"Alpha = Actual Return − Model Predicted. It is the return unexplained by known risk factors — genuine stock-specific edge. "
                        f"\n\nNumbers: {_breakdown}"
                        f"Signal={ff4.get('signal')}, Alpha={ff4.get('alpha')}%pa, p-value={ff4.get('pval')}, "
                        f"Beta={ff4.get('beta')}, SMB={ff4.get('smb')}, HML={ff4.get('hml')}, MOM={ff4.get('mom')}. "
                        f"\n\nWrite exactly 4 complete sentences in plain prose — no headers, no bullet points, no markdown bold or asterisks. "
                        f"Sentence 1: Walk through the alpha calculation using the actual numbers (actual return minus model predicted equals alpha). "
                        f"Sentence 2: Interpret the dominant factor loadings and what they reveal about {ticker}'s risk character, using the actual numbers. "
                        f"Sentence 3: Assess statistical reliability using the p-value — is this alpha genuine edge or could it be noise? "
                        f"Sentence 4: Concrete investment takeaway — what should the investor do or watch for given the signal and this alpha/p-value. "
                        f"Plain prose only, real numbers throughout, complete all 4 sentences fully before stopping."
                    )
                    _max_tok = 480

                _ff_resp = _cli.messages.create(
                    model="claude-haiku-4-5-20251001", max_tokens=_max_tok,
                    messages=[{"role":"user","content":_ff_prompt}]
                )
                ff4["commentary"] = _ff_resp.content[0].text.strip()
            except:
                pass

        result = {
            "ticker": ticker,
            "overview": {
                "name": info.get('shortName') or info.get('longName', ticker),
                "sector": info.get('sector',''),
                "industry": info.get('industry',''),
                "country": info.get('country',''),
                "exchange": info.get('exchange',''),
                "market_cap": _fmt_large(mc),
                "enterprise_value": _fmt_large(ev),
                "currency": display_currency,
                "price": round(price,2) if price else None,
                "fy_end": fy_end,
                "q_end": q_end,
                "description": info.get('longBusinessSummary','')[:600] if info.get('longBusinessSummary') else '',
                "website": info.get('website',''),
                "employees": info.get('fullTimeEmployees'),
            },
            "analyst": {
                "target_price": round(fv(info.get('targetMeanPrice')) * gbp_price_scale, 4) if fv(info.get('targetMeanPrice')) else None,
                "target_low":   round(fv(info.get('targetLowPrice'))  * gbp_price_scale, 4) if fv(info.get('targetLowPrice'))  else None,
                "target_high":  round(fv(info.get('targetHighPrice')) * gbp_price_scale, 4) if fv(info.get('targetHighPrice')) else None,
                "recommendation": rec_key,
                "recommendation_mean": rec_mean,
                "strong_buy": strong_buy, "buy": buy, "hold": hold,
                "sell": sell, "strong_sell": strong_sell,
            },
            "quality": {
                "revenue": _fmt_large(fv(info.get('totalRevenue'))),
                "gross_margin": round(fv(info.get('grossMargins'))*100,1) if fv(info.get('grossMargins')) else None,
                "op_margin": round(fv(info.get('operatingMargins'))*100,1) if fv(info.get('operatingMargins')) else None,
                "net_margin": round(fv(info.get('profitMargins'))*100,1) if fv(info.get('profitMargins')) else None,
                "roe": round(fv(info.get('returnOnEquity'))*100,1) if fv(info.get('returnOnEquity')) else None,
                "roa": round(fv(info.get('returnOnAssets'))*100,1) if fv(info.get('returnOnAssets')) else None,
                "roic": growth_table[0].get('roic') if growth_table else None,
                "debt_equity": round(fv(info.get('debtToEquity')),2) if fv(info.get('debtToEquity')) else None,
                "current_ratio": round(fv(info.get('currentRatio')),2) if fv(info.get('currentRatio')) else None,
                "eps_ttm": round(eps_ttm,2) if eps_ttm else None,
                "dps": round(dps,4) if dps else None,
                "fcf": _fmt_large(fcf_val),
                "fcf_per_share": round(fcf_ps,2) if fcf_ps else None,
                "inv_rate": growth_table[0].get('inv_rate') if growth_table else None,
            },
            "multiples": {
                "pe_trailing": round(fv(info.get('trailingPE')),1) if fv(info.get('trailingPE')) else None,
                "pe_forward": round(fv(info.get('forwardPE')),1) if fv(info.get('forwardPE')) else None,
                "ev_ebitda": round(fv(info.get('enterpriseToEbitda')),1) if fv(info.get('enterpriseToEbitda')) else None,
                "price_book": round(fv(info.get('priceToBook')),2) if fv(info.get('priceToBook')) else None,
                "price_sales": round(fv(info.get('priceToSalesTrailing12Months')),2) if fv(info.get('priceToSalesTrailing12Months')) else None,
                "fcf_per_share": round(fcf_ps,2) if fcf_ps else None,
                "div_yield": round(fv(info.get('dividendYield'))*100,2) if fv(info.get('dividendYield')) else None,
                "peg": round(fv(info.get('pegRatio')),2) if fv(info.get('pegRatio')) else None,
            },
            "market": {
                "beta": round(beta,2) if beta else None,
                "price_52w_high": hi52,
                "price_52w_low": lo52,
                "range_position_pct": range_pos,
                "vs_ma50_pct": vs_ma50,
                "vs_ma200_pct": vs_ma200,
                "short_float_pct": round(short_pct*100,1) if short_pct else None,
                "short_ratio_days": round(short_ratio,1) if short_ratio else None,
                "next_earnings": info.get('earningsCallTimestampEnd') or info.get('earningsTimestamp'),
                "next_earnings_str": info.get('earningsTimestampStr',''),
                "avg_volume": info.get('averageVolume'),
                "avg_volume_10d": info.get('averageVolume10days'),
            },
            "options": options_data,
            "growth_table": growth_table,
            "competitors": competitors,
            "subj_roic": subj_roic,
            "subj_fpe": subj_fpe,
            "ff4": ff4,
            "tsr": tsr_data,
            "revenue_segments": _fetch_fmp_segments(ticker, "product"),
            "revenue_geo":      _fetch_fmp_segments(ticker, "geographic"),
            "valuation_inputs": {
                "shares_outstanding": shares_out,
                "ev_raw": round(ev, 0) if ev else None,
                "mc_raw": round(mc, 0) if mc else None,
                "net_debt": round(ev - mc, 0) if ev and mc else None,
                "revenue_raw": _rev_raw,
                "tax_rate": round(_eff_tax * 100, 1) if _eff_tax else None,
                "kd": round(_kd_raw * 100, 1) if _kd_raw else None,
                "total_debt": _total_debt,
                "book_value_ps": round(_bvps, 2) if _bvps else None,
            },
        }
        # Sanitize NaN/Inf floats — Python's json.dumps rejects them and causes 500 errors
        import math
        def _clean(obj):
            if isinstance(obj, float):
                return None if (math.isnan(obj) or math.isinf(obj)) else obj
            if isinstance(obj, dict):
                return {k: _clean(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_clean(v) for v in obj]
            return obj
        result = _clean(result)
        _fund_jobs[ticker] = {'status': 'done', 'data': result, 'ts': time.time()}

    except Exception as e:
        _fund_jobs[ticker] = {'status': 'error', 'error': str(e)[:300], 'ts': time.time()}


@app.get("/fundamentals")
def get_fundamentals(ticker: str):
    """Return fundamentals immediately if cached; else start background job and return processing status."""
    ticker = ticker.strip().upper()
    job = _fund_jobs.get(ticker)

    # Return cached data if fresh
    if job and job['status'] == 'done' and time.time() - job['ts'] < _FUND_TTL:
        return job['data']

    # Return error if job failed
    if job and job['status'] == 'error':
        raise HTTPException(status_code=500, detail=job.get('error', 'Unknown error'))

    # If already processing, say so
    if job and job['status'] == 'processing':
        return {"status": "processing"}

    # Start fresh background job
    _fund_jobs[ticker] = {'status': 'processing', 'data': None, 'ts': time.time()}
    threading.Thread(target=_run_fundamentals, args=(ticker,), daemon=True).start()
    return {"status": "processing"}


@app.get("/fundamentals/status")
def fundamentals_status(ticker: str):
    """Poll this endpoint after receiving status=processing from /fundamentals."""
    ticker = ticker.strip().upper()
    job = _fund_jobs.get(ticker)
    if not job:
        raise HTTPException(status_code=404, detail="No job found — call /fundamentals first")
    if job['status'] == 'processing':
        return {"status": "processing"}
    if job['status'] == 'error':
        raise HTTPException(status_code=500, detail=job.get('error', 'Failed to load data'))
    return job['data']  # Full data dict


@app.post("/fundamentals/chat")
def fundamentals_chat(payload: dict):
    """Fintiq AI Copilot — section-specialist analyst with live data context."""
    import json as _json

    ticker       = payload.get("ticker", "").upper()
    section      = payload.get("section", "fundamentals")
    section_data = payload.get("section_data", {})
    messages     = payload.get("messages", [])
    session_ctx  = payload.get("session_ctx", {})   # cross-section conclusions
    session_id   = payload.get("session_id", "unknown")

    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")
    if not messages:
        raise HTTPException(status_code=400, detail="messages required")

    data_ctx   = _json.dumps(section_data, indent=2)[:6000]
    prior_ctx  = _json.dumps(session_ctx,  indent=2)[:1500] if session_ctx else "No prior sections completed."

    # ── PUSHBACK MANDATE (applies to ALL sections) ──
    pushback_mandate = """
PUSHBACK MANDATE — NON-NEGOTIABLE:
- If the user states a conclusion that contradicts the live data shown above, you MUST name the contradiction explicitly. Do not soften it or imply it — state it directly: "Your thesis says X, but the data shows Y. These are in conflict."
- Do NOT validate conclusions just to avoid friction. A Copilot that agrees with everything is worse than no Copilot.
- If the user's conviction appears high but the data picture is mixed or weak, proactively offer: "You seem confident in this. Would you like me to argue the bear case as hard as possible?"
- You may acknowledge the user's reasoning fairly, but you must not simply capitulate if they push back on your challenge. Intellectual honesty is the product.
"""

    # ── BEHAVIOUR RULES (applies to ALL sections) ──
    behaviour_rules = f"""
WHAT YOU DO:
- Reference live data by name and value when answering
- State when evidence is thin or ambiguous
- Challenge conclusions that contradict the data
- Proactively flag gaps in the user's analysis
- Suggest specific next investigation steps
- Offer the bear case unprompted when conviction is high

WHAT YOU DO NOT DO:
- Answer questions unrelated to {ticker} or this section
- Give a confident buy/sell recommendation
- Agree with the user's thesis to avoid friction
- Explain generic finance concepts unless directly asked
- Repeat what is already visible on the screen
- Make up data that is not in the live context above

FORMAT: Max 4 short paragraphs. Always cite specific numbers. Not financial advice.
"""

    # ── SECTION-SPECIALIST SYSTEM PROMPTS ──
    if section == "fundamentals":
        specialist = f"""You are the Fundamentals Specialist for {ticker}. Your domain: business quality, competitive positioning, revenue model, moat assessment, growth drivers, margin history, ROIC, FCF yield, Fama-French factor scores, analyst consensus.

OPENING MESSAGE INSTRUCTION: If this is the user's first message (the conversation has only one user turn), open your response with a structured Business Quality Snapshot BEFORE answering their question. Format it as follows — be concise, factual, specific to {ticker}:

**Business Quality Snapshot — {ticker}**
• **Moat**: [Type: Brand / Network Effects / Cost Advantage / Switching Costs / Regulatory / IP / None] — [1 sentence rationale]
• **Revenue Model**: [e.g. Subscription SaaS / Product sales / Advertising / Transaction fees / Mixed] — [1 sentence on revenue quality/predictability]
• **Growth Drivers** (top 3): [brief bullet per driver]
• **Factors For**: [top 3 bull points, ≤12 words each]
• **Factors Against**: [top 3 bear points, ≤12 words each]

Then answer the user's actual question. Do not repeat the snapshot in subsequent messages.

You do not discuss valuation multiples or chart patterns — direct those to the relevant sections."""
        scope_note = "If the user asks about DCF or valuation, say: 'That's covered in the Valuation section — open it below.'"

    elif section in ("valuation", "dcf"):
        specialist = f"You are the Valuation Specialist for {ticker}. Your domain: DCF assumptions, implied growth rates, Monte Carlo outputs, WACC inputs, scenario selection (bear/base/bull), and what the user's current slider choices imply about the stock's fair value. The valuation_state field in the data shows the user's live DCF inputs — always reference these specifically."
        scope_note = "If the user asks about technicals or chart patterns, say: 'That's covered in the Technical section.'"

    elif section == "technical":
        specialist = f"You are the Technical Analysis Specialist for {ticker}. Your domain: price structure, trend, RSI, MACD, Bollinger Bands, support/resistance levels, options flow (put/call ratio, max pain, put wall, call wall), and trade setups. Always give both long AND short perspectives. Translate indicator readings into decision-relevant language — not generic descriptions."
        scope_note = "If the user asks about fundamentals or DCF, direct them to those sections."

    elif section == "risk":
        specialist = f"You are the Risk & Position Sizing Specialist for {ticker}. Your domain: GBM price path outputs, stop-loss probability at the user's stated stop, volatility vs peer comparison, Kelly position sizing, and portfolio risk management. If the user has provided a stop-loss price or time horizon, reference those specifically."
        scope_note = "Do not give general investment advice. Focus on sizing, downside quantification, and risk management for this specific position."

    elif section == "catalyst":
        specialist = f"You are the Catalyst Tracker Specialist for {ticker}. Your domain: upcoming earnings dates, analyst rating change history, short interest levels, recent news sentiment, and which specific events are most likely to move the stock in the next 30–90 days."
        scope_note = "If the user asks about valuation or technicals, direct them to those sections."

    elif section in ("decision", "conviction"):
        specialist = f"You are the Conviction & Decision Specialist for {ticker}. Your domain: synthesising all prior section conclusions into a final investment decision framework. You have access to everything the user has concluded across all six sections. Your job is to stress-test the final thesis, surface any remaining contradictions across sections, and help the user arrive at a well-reasoned, defensible conviction score and position size."
        scope_note = "Reference the user's prior section conclusions explicitly. Do not re-explain data already covered — focus on synthesis and decision quality."

    else:
        specialist = f"You are a Senior Equity Analyst specialising in {section} analysis for {ticker}."
        scope_note = ""

    system = f"""{specialist}

ANALYSIS SESSION: {session_id}
STOCK: {ticker}
CURRENT SECTION: {section}

LIVE DATA SNAPSHOT (what is currently displayed on screen — reference these numbers directly, not from memory):
{data_ctx}

USER CONCLUSIONS FROM PRIOR SECTIONS:
{prior_ctx}

{scope_note}

{pushback_mandate}
{behaviour_rules}"""

    # Fix 5: Haiku for routine Copilot exchanges (spec + margin model)
    # Fix 6: Prompt caching — system prompt cached, historical turns cached, only latest turn billed full
    history = messages[-10:]
    cached_history = history[:-1]   # all but last turn — these are stable, cache them
    latest_turn    = history[-1] if history else {"role": "user", "content": ""}

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        system=[{
            "type": "text",
            "text": system,
            "cache_control": {"type": "ephemeral"},   # cache the large system prompt
        }],
        messages=[
            *[{**m, "cache_control": {"type": "ephemeral"}} if i == len(cached_history) - 1 else m
              for i, m in enumerate(cached_history)],
            latest_turn,
        ],
        betas=["prompt-caching-2024-07-31"],
    )
    # Fix 9: run real-time contradiction checks and return flags with reply
    # Frontend can show these inline during the Copilot dialogue
    realtime_flags = []
    compiled_sections = session_ctx.get("sections") if isinstance(session_ctx, dict) else None
    if compiled_sections and isinstance(compiled_sections, dict):
        realtime_flags = _run_contradiction_checks(compiled_sections, section_data.get("overview", {}).get("price"))

    return {
        "reply": resp.content[0].text,
        "input_tokens": resp.usage.input_tokens,
        "output_tokens": resp.usage.output_tokens,
        "cache_read_tokens": getattr(resp.usage, "cache_read_input_tokens", 0),
        "cache_write_tokens": getattr(resp.usage, "cache_creation_input_tokens", 0),
        "contradiction_flags": realtime_flags,
    }


@app.post("/valuation/ai-assumptions")
def valuation_ai_assumptions(payload: dict):
    """AI senior analyst generates its own DCF assumption set with reasoning for the valuation section."""
    ticker   = payload.get("ticker", "").upper()
    fund_ctx = payload.get("fundamentals_summary", {})
    user_vals= payload.get("user_values", {})

    if not ticker or not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=400, detail="ticker and ANTHROPIC_API_KEY required")

    import json as _json
    ctx_str = _json.dumps(fund_ctx, indent=2)[:4000]

    prompt = f"""You are a senior investment banker and equity analyst at a bulge-bracket firm. You are building a DCF model for {ticker}.

FUNDAMENTALS DATA:
{ctx_str}

USER'S CURRENT SLIDER VALUES (for reference):
{_json.dumps(user_vals, indent=2)}

Your task: Generate THREE scenario assumption sets (Bear, Base, Bull) for a McKinsey value-driver DCF. Each scenario should reflect a coherent, internally consistent investment thesis — not just one variable changed in isolation.

Respond in this EXACT format (plain text, no markdown headers):

━━ BASE CASE (most likely outcome) ━━
SHORT-TERM GROWTH (Yrs 1-3): [X]%
MEDIUM-TERM GROWTH (Yrs 4-7): [X]%
LONG-TERM GROWTH (Yrs 8-10): [X]%
OPERATING MARGIN: [X]%
INVESTMENT RATE: [X]% of NOPAT
TERMINAL GROWTH: [X]%
RONIC: [X]%
THESIS: [2 sentences — what must go right, key catalysts, implied valuation vs current price]

━━ BEAR CASE (downside scenario) ━━
SHORT-TERM GROWTH (Yrs 1-3): [X]%
MEDIUM-TERM GROWTH (Yrs 4-7): [X]%
LONG-TERM GROWTH (Yrs 8-10): [X]%
OPERATING MARGIN: [X]%
INVESTMENT RATE: [X]% of NOPAT
TERMINAL GROWTH: [X]%
RONIC: [X]%
THESIS: [2 sentences — what goes wrong, specific risk factors, implied downside]

━━ BULL CASE (upside scenario) ━━
SHORT-TERM GROWTH (Yrs 1-3): [X]%
MEDIUM-TERM GROWTH (Yrs 4-7): [X]%
LONG-TERM GROWTH (Yrs 8-10): [X]%
OPERATING MARGIN: [X]%
INVESTMENT RATE: [X]% of NOPAT
TERMINAL GROWTH: [X]%
RONIC: [X]%
THESIS: [2 sentences — what exceeds expectations, key upside drivers, implied upside]

KEY SWING FACTOR: [1-2 sentences — the single most important variable that differentiates the scenarios]

Use real numbers from the data. Be specific and opinionated — you are a senior analyst, not a hedger. Each scenario should reflect genuinely different business outcomes, not just minor perturbations."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=1200,
        messages=[{"role": "user", "content": prompt}],
    )
    return {"analysis": resp.content[0].text.strip()}


# ════════════════════════════════════════════════════════════
#  SECTION 3 — TECHNICAL ANALYSIS
# ════════════════════════════════════════════════════════════

_tech_jobs: dict = {}
_TECH_TTL = 5 * 60  # 5 min cache


def _run_technical(ticker: str):
    """Background thread — compute indicators + options analytics."""
    try:
        import pandas as pd, numpy as np

        tk = yf.Ticker(ticker)
        hist = tk.history(period="3y")
        if hist is None or hist.empty:
            _tech_jobs[ticker] = {'status': 'error', 'error': f"No price data for {ticker}", 'ts': time.time()}
            return

        closes  = hist['Close'].astype(float)
        highs   = hist['High'].astype(float)
        lows    = hist['Low'].astype(float)
        opens_  = hist['Open'].astype(float)
        volumes = hist['Volume'].astype(float)

        # ── Moving Averages ──
        ma50  = closes.rolling(50).mean()
        ma200 = closes.rolling(200).mean()

        # ── RSI(14) — Wilder's smoothing ──
        delta    = closes.diff()
        gain     = delta.clip(lower=0)
        loss     = (-delta).clip(lower=0)
        avg_gain = gain.ewm(com=13, min_periods=14).mean()
        avg_loss = loss.ewm(com=13, min_periods=14).mean()
        rs  = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        # ── MACD(12,26,9) ──
        ema12       = closes.ewm(span=12, adjust=False).mean()
        ema26       = closes.ewm(span=26, adjust=False).mean()
        macd_line   = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist_s = macd_line - macd_signal

        # ── Bollinger Bands(20,2) ──
        bb_mid  = closes.rolling(20).mean()
        bb_std  = closes.rolling(20).std()
        bb_up   = bb_mid + 2 * bb_std
        bb_low  = bb_mid - 2 * bb_std

        # ── Current snapshot ──
        def sf(x):
            try:
                v = float(x)
                return None if (v != v) else round(v, 4)
            except: return None

        curr   = sf(closes.iloc[-1])
        c_ma50 = sf(ma50.iloc[-1])
        c_ma200= sf(ma200.iloc[-1])
        c_rsi  = sf(rsi.iloc[-1])
        c_macd = sf(macd_line.iloc[-1])
        c_msig = sf(macd_signal.iloc[-1])
        c_mhst = sf(macd_hist_s.iloc[-1])
        p_mhst = sf(macd_hist_s.iloc[-2]) if len(macd_hist_s) > 1 else 0
        c_bbup = sf(bb_up.iloc[-1])
        c_bblo = sf(bb_low.iloc[-1])

        # ── Trend classification ──
        p_ma50  = ((curr - c_ma50)  / c_ma50  * 100) if curr and c_ma50  else None
        p_ma200 = ((curr - c_ma200) / c_ma200 * 100) if curr and c_ma200 else None
        golden  = (c_ma50 > c_ma200) if c_ma50 and c_ma200 else None

        if p_ma50 is not None and p_ma200 is not None:
            if p_ma50 > 0 and p_ma200 > 0 and golden:
                trend_cls = "Uptrend"
            elif p_ma50 < 0 and p_ma200 < 0 and golden is False:
                trend_cls = "Downtrend"
            else:
                trend_cls = "Sideways"
        else:
            trend_cls = "Insufficient data"

        w52h = sf(highs.max())
        w52l = sf(lows.min())
        w52pct = round((curr - w52l) / (w52h - w52l) * 100, 1) if curr and w52h and w52l and w52h != w52l else None

        # ── RSI signal ──
        if c_rsi is not None:
            if   c_rsi < 30: rsi_sig = "Oversold"
            elif c_rsi > 70: rsi_sig = "Overbought"
            elif c_rsi < 45: rsi_sig = "Mildly Oversold"
            elif c_rsi > 55: rsi_sig = "Mildly Overbought"
            else:             rsi_sig = "Neutral"
        else: rsi_sig = None

        # ── MACD crossover ──
        if c_mhst is not None and p_mhst is not None:
            if   c_mhst > 0 and p_mhst <= 0: macd_cross = "Bullish (fresh crossover)"
            elif c_mhst < 0 and p_mhst >= 0: macd_cross = "Bearish (fresh crossover)"
            elif c_mhst > 0:                  macd_cross = "Bullish"
            else:                             macd_cross = "Bearish"
        else: macd_cross = None

        # ── BB signal ──
        if curr and c_bbup and c_bblo:
            if   curr > c_bbup: bb_sig = "Above upper band (overextended)"
            elif curr < c_bblo: bb_sig = "Below lower band (oversold squeeze)"
            else:               bb_sig = "Within bands"
        else: bb_sig = None

        # ── Key levels — support/resistance ──
        recent63 = hist.iloc[-63:]  # 3 months
        r3m_lo = sf(recent63['Low'].min())
        r3m_hi = sf(recent63['High'].max())

        # ── Volume analysis ──
        avg_vol_20 = sf(volumes.rolling(20).mean().iloc[-1])
        curr_vol   = sf(volumes.iloc[-1])
        vol_ratio  = round(curr_vol / avg_vol_20, 2) if curr_vol and avg_vol_20 and avg_vol_20 > 0 else None

        # ── Serialise all bars (up to 3 years) for chart — frontend slices by timeframe ──
        chart = hist
        dates_arr   = [i.strftime('%Y-%m-%d') for i in chart.index]
        c_arr  = [sf(v) for v in chart['Close']]
        o_arr  = [sf(v) for v in chart['Open']]
        h_arr  = [sf(v) for v in chart['High']]
        l_arr  = [sf(v) for v in chart['Low']]
        v_arr  = [int(v) for v in chart['Volume']]

        # Indicator series — same index as hist (chart == hist now)
        def ind_series(s):
            return [sf(v) for v in s]

        ma50_arr  = ind_series(ma50)
        ma200_arr = ind_series(ma200)
        rsi_arr   = ind_series(rsi)
        macd_arr  = ind_series(macd_line)
        msig_arr  = ind_series(macd_signal)
        mhst_arr  = ind_series(macd_hist_s)
        bbup_arr  = ind_series(bb_up)
        bblo_arr  = ind_series(bb_low)

        # ── Options analytics ──
        opts = {}
        try:
            exps = tk.options
            if exps:
                chain = tk.option_chain(exps[0])
                calls = chain.calls.copy()
                puts  = chain.puts.copy()

                # PCR (volume)
                cv = float(calls['volume'].fillna(0).sum())
                pv = float(puts['volume'].fillna(0).sum())
                pcr = round(pv / cv, 2) if cv > 0 else None
                if pcr is not None:
                    if   pcr > 1.3: pcr_sig = "High fear — contrarian bullish"
                    elif pcr > 0.9: pcr_sig = "Moderately bearish sentiment"
                    elif pcr > 0.6: pcr_sig = "Neutral"
                    elif pcr > 0.4: pcr_sig = "Moderately bullish sentiment"
                    else:           pcr_sig = "Low fear — contrarian bearish"
                else: pcr_sig = None

                # ATM IV
                calls2 = calls.copy(); calls2['dist'] = abs(calls2['strike'] - curr)
                atm = calls2.nsmallest(1, 'dist')
                atm_iv = round(float(atm['impliedVolatility'].iloc[0]) * 100, 1) if len(atm) else None

                # Max pain
                all_s = sorted(set(calls['strike'].tolist() + puts['strike'].tolist()))
                mp, mp_val = None, float('inf')
                for s in all_s:
                    cl = ((s - calls['strike']).clip(lower=0) * calls['openInterest'].fillna(0)).sum()
                    pl = ((puts['strike'] - s).clip(lower=0)  * puts['openInterest'].fillna(0)).sum()
                    if cl + pl < mp_val:
                        mp_val = cl + pl; mp = s

                # Put wall / Call wall
                pb = puts[puts['strike'] < curr].copy()
                put_wall = float(pb.loc[pb['openInterest'].idxmax(), 'strike']) if not pb.empty else None

                ca = calls[calls['strike'] > curr].copy()
                call_wall = float(ca.loc[ca['openInterest'].idxmax(), 'strike']) if not ca.empty else None

                # Unusual volume (vol > 2×OI and vol > 200)
                def unusual(df, n=3):
                    mask = (df['volume'].fillna(0) > df['openInterest'].fillna(0) * 2) & (df['volume'].fillna(0) > 200)
                    top = df[mask].nlargest(n, 'volume')
                    return [{'strike': float(r['strike']), 'volume': int(r['volume']), 'oi': int(r['openInterest'])} for _, r in top.iterrows()]

                opts = {
                    'expiry': exps[0],
                    'pcr': pcr, 'pcr_signal': pcr_sig,
                    'atm_iv': atm_iv,
                    'max_pain': float(mp) if mp else None,
                    'put_wall': put_wall,
                    'call_wall': call_wall,
                    'unusual_calls': unusual(calls),
                    'unusual_puts':  unusual(puts),
                }
        except Exception as oe:
            opts = {'error': str(oe)[:200]}

        result = {
            'ticker': ticker,
            'dates':  dates_arr,
            'ohlcv':  {'o': o_arr, 'h': h_arr, 'l': l_arr, 'c': c_arr, 'v': v_arr},
            'ma50':   ma50_arr,
            'ma200':  ma200_arr,
            'bb_up':  bbup_arr,
            'bb_low': bblo_arr,
            'rsi':    rsi_arr,
            'macd':   macd_arr,
            'macd_signal': msig_arr,
            'macd_hist':   mhst_arr,
            'trend': {
                'classification': trend_cls,
                'ma50': c_ma50, 'ma200': c_ma200,
                'pct_vs_ma50': round(p_ma50, 1) if p_ma50 else None,
                'pct_vs_ma200': round(p_ma200, 1) if p_ma200 else None,
                'golden_cross': golden,
                'week52_high': w52h, 'week52_low': w52l, 'week52_pct': w52pct,
                'bb_signal': bb_sig,
            },
            'momentum': {
                'rsi': c_rsi, 'rsi_signal': rsi_sig,
                'macd': c_macd, 'macd_signal_val': c_msig,
                'macd_hist': c_mhst, 'macd_crossover': macd_cross,
            },
            'volume': {
                'current': curr_vol, 'avg_20d': avg_vol_20, 'ratio': vol_ratio,
                'signal': 'High volume' if vol_ratio and vol_ratio > 1.5 else ('Low volume' if vol_ratio and vol_ratio < 0.7 else 'Normal'),
            },
            'key_levels': {
                'support1': c_ma50,   'support1_label': '50-day MA',
                'support2': c_ma200,  'support2_label': '200-day MA',
                'support3': r3m_lo,   'support3_label': '3-month low',
                'resistance1': r3m_hi,'resistance1_label': '3-month high',
                'resistance2': w52h,  'resistance2_label': '52-week high',
            },
            'options': opts,
        }

        # clean NaN/None
        def _clean(obj):
            if isinstance(obj, float) and obj != obj: return None
            if isinstance(obj, dict): return {k: _clean(v) for k, v in obj.items()}
            if isinstance(obj, list): return [_clean(v) for v in obj]
            return obj

        _tech_jobs[ticker] = {'status': 'done', 'data': _clean(result), 'ts': time.time()}

    except Exception as e:
        _tech_jobs[ticker] = {'status': 'error', 'error': str(e)[:300], 'ts': time.time()}


@app.get("/technical")
def get_technical(ticker: str):
    ticker = ticker.strip().upper()
    job = _tech_jobs.get(ticker)
    if job and job['status'] == 'done' and time.time() - job['ts'] < _TECH_TTL:
        return job['data']
    if job and job['status'] == 'error':
        raise HTTPException(status_code=500, detail=job.get('error', 'Unknown error'))
    if job and job['status'] == 'processing':
        return {"status": "processing"}
    _tech_jobs[ticker] = {'status': 'processing', 'data': None, 'ts': time.time()}
    threading.Thread(target=_run_technical, args=(ticker,), daemon=True).start()
    return {"status": "processing"}


@app.post("/technical/ai-commentary")
def technical_ai_commentary(payload: dict):
    """AI senior trader generates long + short trade setups from technical + options data."""
    ticker   = payload.get("ticker", "").upper()
    tech     = payload.get("tech_data", {})
    fund_ctx = payload.get("fundamentals_summary", {})

    if not ticker or not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=400, detail="ticker and ANTHROPIC_API_KEY required")

    import json as _json
    tr  = tech.get('trend', {})
    mom = tech.get('momentum', {})
    kl  = tech.get('key_levels', {})
    vol = tech.get('volume', {})
    opt = tech.get('options', {})
    curr_price = (tech.get('ohlcv', {}).get('c') or [None])[-1]

    prompt = f"""You are an experienced trader helping a retail investor understand what the charts and options market are telling them about {ticker}. Your job is to explain things clearly and simply — like a knowledgeable friend walking them through the data, not a textbook. Use plain English. When you use a technical term, explain it in a bracket straight away. Avoid jargon. Be specific with price levels. Be direct about what the data says.

TICKER: {ticker}
CURRENT PRICE: {curr_price}

TECHNICAL DATA:
- Trend: {tr.get('classification')} | Price vs MA50: {tr.get('pct_vs_ma50')}% | Price vs MA200: {tr.get('pct_vs_ma200')}%
- MA50: {tr.get('ma50')} | MA200: {tr.get('ma200')} | Golden cross: {tr.get('golden_cross')}
- 52-week range: {tr.get('week52_low')} – {tr.get('week52_high')} ({tr.get('week52_pct')}% of range)
- Bollinger Band signal: {tr.get('bb_signal')}
- RSI(14): {mom.get('rsi')} — {mom.get('rsi_signal')}
- MACD: {mom.get('macd')} | Signal: {mom.get('macd_signal_val')} | Histogram: {mom.get('macd_hist')} | {mom.get('macd_crossover')}
- Volume: {vol.get('ratio')}× avg ({vol.get('signal')})

KEY LEVELS:
- Support 1 (MA50): {kl.get('support1')}
- Support 2 (MA200): {kl.get('support2')}
- Support 3 (3-month low): {kl.get('support3')}
- Resistance 1 (3-month high): {kl.get('resistance1')}
- Resistance 2 (52-week high): {kl.get('resistance2')}

OPTIONS FLOW:
- Put/Call Ratio: {opt.get('pcr')} — {opt.get('pcr_signal')}
- ATM Implied Volatility: {opt.get('atm_iv')}%
- Max Pain ({opt.get('expiry')}): {opt.get('max_pain')}
- Put Wall (largest put OI below price): {opt.get('put_wall')}
- Call Wall (largest call OI above price): {opt.get('call_wall')}
- Unusual call activity: {opt.get('unusual_calls')}
- Unusual put activity: {opt.get('unusual_puts')}

FUNDAMENTAL CONTEXT: {_json.dumps(fund_ctx, indent=2)[:1500]}

Output EXACTLY in this format (plain text, no markdown, use the ━━ separators):

━━ WHAT THE CHART IS SAYING ━━
TREND SUMMARY: [2-3 sentences in plain English. Tell the investor what the overall trend looks like — are buyers or sellers in control? Is the stock above or below its key moving averages and what does that mean? Mention the 52-week position in simple terms.]
MOMENTUM: [1-2 sentences explaining RSI and MACD in plain English. For example: "The RSI [a speed gauge for price] is at X, which means the stock is [overbought/oversold/neutral — explain what that means for timing]. The MACD [a trend-following signal] is showing [describe the crossover situation and what to watch for]."]
VOLUME: [1 sentence on what volume is telling us — is there conviction behind the recent move or is it weak?]

━━ WHAT THE OPTIONS MARKET IS SAYING ━━
OPTIONS EXPLANATION: [3-4 sentences explaining the options data in plain, teaching English. Cover: (1) What does the Put/Call Ratio tell us — are investors buying more protection (puts) or more upside (calls)? (2) What does Max Pain mean and how should the investor think about it — this is the price where options sellers win most, so the stock often drifts toward it near expiry. (3) What do the Put Wall and Call Wall mean — these are big clusters of bets that act like magnets or barriers for the price. (4) Is there any unusual activity and what might it signal? End with one sentence on what the options market overall is suggesting about near-term direction.]

━━ LONG TRADE SETUP ━━
ENTRY ZONE: [Specific price range. Explain WHY this is the entry — e.g. "Between $X and $Y, because this is where the MA50 [the 50-day average price, a key support level] sits and the put wall provides a floor"]
WHAT TO WAIT FOR: [In plain English, what signal should the investor see before buying? e.g. "Wait for the stock to hold above $X for two consecutive days, or for the MACD line to cross above the signal line [meaning momentum is turning positive]"]
STOP LOSS: [Specific price. Explain: "If the stock falls below $X, the trade idea is wrong — this is below the [support level]. A stop loss means you automatically exit to protect yourself from a larger loss."]
TARGET 1: [Specific price with plain-English reasoning]
TARGET 2: [Specific price with plain-English reasoning]
RISK/REWARD: [Calculate and state: "You risk $X to potentially make $Y — that's a 1:Z risk/reward ratio" using the entry midpoint, stop, and Target 1]

━━ SHORT TRADE SETUP ━━
ENTRY ZONE: [Specific price range with plain-English reasoning anchored to resistance/call wall]
WHAT TO WAIT FOR: [Plain English signal — what failure pattern or rejection to look for before shorting]
STOP LOSS: [Specific price. Remind them: "Shorting means you profit if the price falls. A stop loss above $X protects you if the stock squeezes higher instead."]
TARGET 1: [Specific price with plain-English reasoning]
TARGET 2: [Specific price with plain-English reasoning]
RISK/REWARD: [Calculate and state the ratio as above]

━━ TRADE DASHBOARD ━━
BIAS: [BULLISH / BEARISH / NEUTRAL — one word, then one sentence on why]
LONG ENTRY: [single price or tight range]
LONG STOP: [single price]
LONG TARGET 1: [single price]
LONG TARGET 2: [single price]
SHORT ENTRY: [single price or tight range]
SHORT STOP: [single price]
SHORT TARGET 1: [single price]
SHORT TARGET 2: [single price]
KEY LEVEL TO WATCH: [The single most important price level right now and why]
OPTIONS VERDICT: [One sentence — what the options market is telling you to expect over the next 2-4 weeks]

Be specific. Be simple. Teach as you go."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        messages=[{"role": "user", "content": prompt}],
    )
    return {"commentary": resp.content[0].text.strip()}


# ══════════════════════════════════════════════════════════════
# SECTION 5 — CATALYST TRACKER
# ══════════════════════════════════════════════════════════════

_catalyst_jobs: dict = {}
_CATALYST_TTL = 5 * 60


def _run_catalyst(ticker: str):
    """Background thread — collect earnings, analyst, short interest, news data."""
    import datetime, requests as _req
    from concurrent.futures import ThreadPoolExecutor, TimeoutError as _FuturesTimeout
    def _safe(fn, timeout=12, default=None):
        """Run fn() with a timeout; return default if it hangs or errors.
        IMPORTANT: shutdown(wait=False) so we don't block on hung yfinance threads."""
        ex = ThreadPoolExecutor(max_workers=1)
        try:
            fut = ex.submit(fn)
            return fut.result(timeout=timeout)
        except Exception:
            return default
        finally:
            ex.shutdown(wait=False)  # never wait for a hung thread
    try:
        tk = yf.Ticker(ticker)
        info = _safe(lambda: tk.info, timeout=20) or {}
        curr_price = info.get('currentPrice') or info.get('regularMarketPrice')

        # ── 1. Earnings ──
        # Try earningsTimestamp first — but validate it's in the future
        earnings_ts = info.get('earningsTimestamp') or info.get('earningsTimestampStart')
        earnings_date = None
        days_to_earnings = None
        now_dt = datetime.datetime.now()
        if earnings_ts:
            try:
                ed = datetime.datetime.fromtimestamp(int(earnings_ts))
                # Only use if it's a future date
                if ed > now_dt:
                    earnings_date = ed.strftime('%Y-%m-%d')
                    days_to_earnings = (ed - now_dt).days
            except Exception:
                pass

        # Fetch earnings_dates ONCE — reused for both future date lookup and surprise history
        _ed_cache = _safe(lambda: tk.earnings_dates, timeout=10)

        # If timestamp was missing/past, look in earnings_dates for next future date
        if not earnings_date:
            try:
                ed_all = _ed_cache
                if ed_all is not None and not ed_all.empty:
                    for idx in ed_all.index:
                        try:
                            idx_dt = idx.to_pydatetime().replace(tzinfo=None)
                        except Exception:
                            try: idx_dt = datetime.datetime.strptime(str(idx)[:10], '%Y-%m-%d')
                            except Exception: continue
                        if idx_dt > now_dt:
                            earnings_date = idx_dt.strftime('%Y-%m-%d')
                            days_to_earnings = (idx_dt - now_dt).days
                            break
            except Exception:
                pass

        # Calendar — EPS + revenue estimates for next quarter
        eps_estimate = None
        rev_estimate_low = None
        rev_estimate_high = None
        rev_estimate_avg = None
        try:
            cal = _safe(lambda: tk.calendar, timeout=10)
            if cal is not None:
                # calendar can be a dict or DataFrame depending on yfinance version
                if isinstance(cal, dict):
                    eps_estimate = cal.get('Earnings Average') or cal.get('EPS Estimate')
                    rev_estimate_avg = cal.get('Revenue Average')
                    rev_estimate_low = cal.get('Revenue Low')
                    rev_estimate_high = cal.get('Revenue High')
                elif hasattr(cal, 'loc'):
                    def _cal(k):
                        try: return float(cal.loc[k].iloc[0])
                        except Exception: return None
                    eps_estimate = _cal('Earnings Average') or _cal('EPS Estimate')
                    rev_estimate_avg = _cal('Revenue Average')
                    rev_estimate_low  = _cal('Revenue Low')
                    rev_estimate_high = _cal('Revenue High')
        except Exception:
            pass

        # Earnings surprise history — last 4 reported quarters (use cached earnings_dates)
        surprises = []
        try:
            ed_df = _ed_cache
            if ed_df is not None and not ed_df.empty:
                past = ed_df[ed_df.get('Reported EPS', ed_df.iloc[:, 1] if ed_df.shape[1] > 1 else ed_df.iloc[:, 0]).notna()].head(4)
                for idx, row in past.iterrows():
                    est = row.get('EPS Estimate') if 'EPS Estimate' in row else None
                    act = row.get('Reported EPS') if 'Reported EPS' in row else None
                    if act is None:
                        continue
                    try:
                        est_f = float(est) if est is not None else None
                        act_f = float(act)
                        surp = round((act_f - est_f) / abs(est_f) * 100, 1) if est_f and est_f != 0 else None
                        surprises.append({
                            'date': str(idx.date()) if hasattr(idx, 'date') else str(idx)[:10],
                            'estimate': round(est_f, 2) if est_f is not None else None,
                            'actual':   round(act_f, 2),
                            'surprise_pct': surp,
                            'beat': act_f > est_f if est_f is not None else None
                        })
                    except Exception:
                        continue
        except Exception:
            pass

        # Analyst estimate revisions (30d change from info fields)
        eps_fwd = info.get('forwardEps')
        eps_ttm = info.get('trailingEps')
        revenue_growth = info.get('revenueGrowth')
        earnings_growth = info.get('earningsGrowth')
        analyst_revisions = {
            'eps_fwd': round(eps_fwd, 2) if eps_fwd else None,
            'eps_ttm': round(eps_ttm, 2) if eps_ttm else None,
            'revenue_growth_yoy': round(revenue_growth * 100, 1) if revenue_growth else None,
            'earnings_growth_yoy': round(earnings_growth * 100, 1) if earnings_growth else None,
        }

        # ── 2. Analyst Ratings ──
        target_mean = info.get('targetMeanPrice')
        target_high = info.get('targetHighPrice')
        target_low  = info.get('targetLowPrice')
        num_analysts = info.get('numberOfAnalystOpinions')
        rec_key  = (info.get('recommendationKey') or '').lower()
        rec_mean = info.get('recommendationMean')  # 1.0=Strong Buy … 5.0=Strong Sell
        target_upside = round((target_mean - curr_price) / curr_price * 100, 1) if target_mean and curr_price else None

        # Recent upgrades/downgrades (last 60 days)
        recent_changes = []
        try:
            upg = _safe(lambda: tk.upgrades_downgrades, timeout=10)
            if upg is not None and not upg.empty:
                upg = upg.reset_index()
                cutoff = datetime.datetime.now() - datetime.timedelta(days=60)
                if 'GradeDate' in upg.columns:
                    upg['GradeDate'] = pd.to_datetime(upg['GradeDate'], errors='coerce')
                    recent = upg[upg['GradeDate'] >= cutoff].head(6)
                    for _, row in recent.iterrows():
                        action = str(row.get('Action', '')).strip()
                        if action.lower() in ('up', 'down', 'init', 'main', 'reit'):
                            label = {'up': 'Upgrade', 'down': 'Downgrade', 'init': 'Initiated', 'main': 'Maintained', 'reit': 'Reiterated'}.get(action.lower(), action)
                            recent_changes.append({
                                'date': str(row['GradeDate'].date()),
                                'firm': str(row.get('Firm', '')),
                                'action': label,
                                'from_grade': str(row.get('FromGrade', '')),
                                'to_grade': str(row.get('ToGrade', ''))
                            })
        except Exception:
            pass

        # ── 3. Short Interest ──
        short_pct_raw = info.get('shortPercentOfFloat')
        short_pct = round(short_pct_raw * 100, 1) if short_pct_raw else None
        short_ratio = info.get('shortRatio')
        shares_short = info.get('sharesShort')
        float_shares = info.get('floatShares')

        squeeze_score = 'LOW'
        squeeze_color = 'green'
        squeeze_signal = 'Low short interest — minimal squeeze risk'
        if short_pct:
            if short_pct > 20:
                squeeze_score = 'HIGH'
                squeeze_color = 'red'
                squeeze_signal = f'{short_pct}% of the float is sold short — very high squeeze potential if a positive catalyst hits'
            elif short_pct > 10:
                squeeze_score = 'MODERATE'
                squeeze_color = 'amber'
                squeeze_signal = f'{short_pct}% of the float is sold short — moderate squeeze risk worth watching'
            else:
                squeeze_signal = f'{short_pct}% of the float is sold short — low squeeze risk'

        # ── 4. News via Tavily ──
        news_items = []
        if TAVILY_API_KEY:
            try:
                company_name = info.get('longName') or ticker
                resp_tv = _req.post('https://api.tavily.com/search', json={
                    'api_key': TAVILY_API_KEY,
                    'query': f'{company_name} {ticker} stock news earnings analyst 2026',
                    'search_depth': 'basic',
                    'max_results': 7,
                    'include_answer': False
                }, timeout=12)
                if resp_tv.ok:
                    for r in resp_tv.json().get('results', []):
                        news_items.append({
                            'title':     r.get('title', ''),
                            'url':       r.get('url', ''),
                            'published': (r.get('published_date') or '')[:10],
                            'snippet':   (r.get('content') or '')[:250]
                        })
            except Exception:
                pass

        result = {
            'status': 'done',
            'ticker': ticker,
            'price': curr_price,
            'earnings': {
                'next_date': earnings_date,
                'days_to': days_to_earnings,
                'eps_estimate': round(eps_estimate, 2) if eps_estimate else None,
                'rev_estimate_avg': int(rev_estimate_avg) if rev_estimate_avg else None,
                'rev_estimate_low': int(rev_estimate_low) if rev_estimate_low else None,
                'rev_estimate_high': int(rev_estimate_high) if rev_estimate_high else None,
                'eps_ttm': round(eps_ttm, 2) if eps_ttm else None,
                'surprise_history': surprises,
                'analyst_revisions': analyst_revisions,
            },
            'analyst': {
                'target_mean':    round(target_mean, 2) if target_mean else None,
                'target_high':    round(target_high, 2) if target_high else None,
                'target_low':     round(target_low, 2) if target_low else None,
                'target_upside':  target_upside,
                'num_analysts':   num_analysts,
                'recommendation': rec_key,
                'recommendation_mean': round(rec_mean, 1) if rec_mean else None,
                'recent_changes': recent_changes,
            },
            'short_interest': {
                'short_pct':      short_pct,
                'days_to_cover':  round(float(short_ratio), 1) if short_ratio else None,
                'squeeze_score':  squeeze_score,
                'squeeze_color':  squeeze_color,
                'squeeze_signal': squeeze_signal,
            },
            'news': news_items,
            'ts': time.time()
        }
        _catalyst_jobs[ticker] = _clean(result)

    except Exception as e:
        _catalyst_jobs[ticker] = {'status': 'error', 'error': str(e), 'ts': time.time()}


@app.get("/catalyst")
def get_catalyst(ticker: str):
    ticker = ticker.upper().strip()
    now = time.time()
    job = _catalyst_jobs.get(ticker)
    if job:
        if job.get('status') == 'done' and now - job.get('ts', 0) < _CATALYST_TTL:
            return job
        if job.get('status') == 'processing' and now - job.get('ts', 0) < 90:
            return {"status": "processing"}
    _catalyst_jobs[ticker] = {'status': 'processing', 'data': None, 'ts': now}
    threading.Thread(target=_run_catalyst, args=(ticker,), daemon=True).start()
    return {"status": "processing"}


@app.get("/catalyst/status")
def get_catalyst_status(ticker: str):
    ticker = ticker.upper().strip()
    job = _catalyst_jobs.get(ticker)
    if not job:
        return {"status": "not_started"}
    return job


@app.post("/catalyst/ai-summary")
def catalyst_ai_summary(payload: dict):
    """AI analyst generates comprehensive catalyst assessment in plain English."""
    ticker   = payload.get("ticker", "").upper()
    cat_data = payload.get("catalyst_data", {})
    fund_ctx = payload.get("fundamentals_summary", {})

    if not ticker or not ANTHROPIC_API_KEY:
        raise HTTPException(status_code=400, detail="ticker required")

    import json as _json
    ea  = cat_data.get('earnings', {})
    an  = cat_data.get('analyst', {})
    si  = cat_data.get('short_interest', {})
    news = cat_data.get('news', [])
    price = cat_data.get('price')

    # Format earnings surprise history
    surp_txt = ''
    for s in ea.get('surprise_history', []):
        beat = '✅ BEAT' if s.get('beat') else ('❌ MISSED' if s.get('beat') is False else '—')
        surp_txt += f"  {s.get('date','')}: Est ${s.get('estimate','?')} → Actual ${s.get('actual','?')} ({'+' if (s.get('surprise_pct') or 0) > 0 else ''}{s.get('surprise_pct','?')}%) {beat}\n"

    # Format recent analyst changes
    changes_txt = ''
    for c in an.get('recent_changes', []):
        changes_txt += f"  {c.get('date','')} | {c.get('firm','')} | {c.get('action','')} | {c.get('from_grade','')} → {c.get('to_grade','')}\n"

    # Format news headlines
    news_txt = ''
    for n in news[:6]:
        news_txt += f"  • {n.get('title','')}\n    {n.get('snippet','')[:120]}\n"

    rec_label = {
        'strongbuy': 'Strong Buy', 'buy': 'Buy', 'hold': 'Hold',
        'underperform': 'Underperform', 'sell': 'Sell'
    }.get((an.get('recommendation') or '').replace(' ','').lower(), an.get('recommendation', 'Unknown'))

    prompt = f"""You are a senior equity analyst. Give a sharp, concise catalyst briefing for {ticker} at ${price}. Plain English only — no jargon without explanation. Be direct and specific.

DATA:
- Next earnings: {ea.get('next_date', 'Unknown')} ({ea.get('days_to', '?')} days away)
- EPS estimate: ${ea.get('eps_estimate', 'N/A')} | Rev estimate: {'{:,.0f}'.format(ea.get('rev_estimate_avg')) if ea.get('rev_estimate_avg') else 'N/A'}
- Beat/miss history (last 4Q): {surp_txt or 'N/A'}
- Rev growth YoY: {ea.get('analyst_revisions', {}).get('revenue_growth_yoy', 'N/A')}% | EPS growth: {ea.get('analyst_revisions', {}).get('earnings_growth_yoy', 'N/A')}%
- Analyst consensus: {rec_label} | Target: ${an.get('target_mean', '?')} ({an.get('target_upside', '?')}% upside) | {an.get('num_analysts', '?')} analysts
- Recent changes: {changes_txt or 'None'}
- Short float: {si.get('short_pct', '?')}% | Days to cover: {si.get('days_to_cover', '?')} | Squeeze: {si.get('squeeze_score', '?')}
- News: {news_txt or 'None'}

Write exactly 5 SHORT sections (2-4 sentences each). Use these exact headers on their own line:

▸ EARNINGS TIMING
Should I enter before or after earnings? State the date, the risk/reward, and what the beat history suggests. Be direct.

▸ ANALYST DIRECTION
Is sentiment improving or stagnating? Focus on direction of change, not just the rating. One or two sentences max on what recent moves signal.

▸ SQUEEZE POTENTIAL
Is short interest meaningful? If <5% float shorted, say it's not a factor. If high, explain what a squeeze means in one sentence.

▸ WHAT'S PRICED IN
Based on news, what concern or theme is the market focused on? If that concern is resolved, the stock re-rates. If it's valid, it's a risk.

▸ VERDICT
One clear recommendation: what's the key event to watch and when. What does the investor do now vs. after earnings. 2 sentences max.

Total length: 200-250 words. No long paragraphs. Specific numbers and dates."""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=600,
        messages=[{"role": "user", "content": prompt}],
    )
    return {"summary": resp.content[0].text.strip()}


# ══════════════════════════════════════════════════════
# SECTION 6 — DECISION ANALYSIS
# ══════════════════════════════════════════════════════

@app.post("/decision/ai-challenge")
async def decision_ai_challenge(payload: dict):
    ticker    = payload.get("ticker", "")
    direction = payload.get("direction", "long")   # 'long' | 'short'
    thesis    = payload.get("thesis", "")
    signals   = payload.get("signals", [])
    fund      = payload.get("fundamentals_summary") or {}
    tech      = payload.get("technical_summary") or {}
    cat       = payload.get("catalyst_summary") or {}
    dcf       = payload.get("dcf_summary") or {}

    sig_txt = "\n".join([f"  {s['label']}: {s['signal'].upper()} — {s['status']} — {s.get('detail','')}" for s in signals])

    # ── Optional: fetch fresh web context via Tavily ──
    web_ctx = ""
    if TAVILY_API_KEY:
        import requests as _req2
        try:
            tv = _req2.post('https://api.tavily.com/search', json={
                'api_key': TAVILY_API_KEY,
                'query': f'{ticker} stock analysis revenue growth segments business outlook 2025 2026',
                'search_depth': 'basic', 'max_results': 4, 'include_answer': True
            }, timeout=8)
            if tv.ok:
                tvj = tv.json()
                if tvj.get('answer'):
                    web_ctx += f"\nWEB RESEARCH SUMMARY: {tvj['answer'][:600]}"
                for r in tvj.get('results', [])[:3]:
                    web_ctx += f"\n• {r.get('title','')}: {(r.get('content',''))[:200]}"
        except Exception:
            pass

    if direction == "long":
        role_desc = "a seasoned short-seller and hedge fund bear analyst"
        opp_role = "BULL"
        instruction = """Challenge this bull thesis with institutional-grade depth. You must:
1. Break down the DCF implied growth rate by business segment — what revenue each segment would need to deliver, and whether that is realistic given current trajectory and market size constraints.
2. Identify the single most dangerous assumption in the thesis and stress-test it with specific numbers.
3. Connect the technical picture, valuation, and fundamental data to show why the risk/reward is unfavourable.
Be brutally specific — cite exact figures from the data provided."""
    else:
        role_desc = "a top-tier long-only fund manager and hedge fund bull analyst"
        opp_role = "BEAR"
        instruction = """Challenge this bear thesis with institutional-grade depth. You must:
1. Break down what the company's key business segments could realistically achieve and how that maps to a credible growth path — use specific segment-level logic.
2. Identify what the bear is most likely wrong about — cite specific data that contradicts their view.
3. Connect catalyst timing, technical setup, and valuation to show why the upside case is underappreciated.
Be specific — cite exact figures from the data provided."""

    prompt = f"""You are {role_desc} reviewing an investment thesis on {ticker}.

INVESTOR'S {direction.upper()} THESIS:
"{thesis}"

QUANTITATIVE CONTEXT:
- DCF fair value: {dcf.get('equity_ps','—')} vs current price {dcf.get('price','—')} — implied revenue growth baked in: {dcf.get('implied_growth','—')}%
- Signals: {sig_txt}
- Fundamentals: Quality={fund.get('quality',{})}, Multiples={fund.get('multiples',{})}
- Technical: Trend={tech.get('trend','—')}, Momentum={tech.get('momentum','—')}
- Catalyst: Next earnings={cat.get('earnings',{}).get('next_date','—')}, Analyst consensus={cat.get('analyst',{}).get('recommendation','—')}, Short squeeze={cat.get('short_interest',{}).get('squeeze_score','—')}
{web_ctx}

{instruction}

Then write a VERDICT paragraph that does two things:
(a) "Your {direction} thesis is correct if..." — state the specific conditions (metrics, events, timeframe) that would validate it.
(b) Give your judgemental probability: "I assign X% probability to this thesis playing out over the next 12 months because..." — be direct, not wishy-washy.

Respond in this EXACT JSON format (no markdown, no extra text):
{{
  "counters": [
    {{"title": "Short counter-argument title", "argument": "3-4 sentences with specific numbers, segment breakdowns, and data references. Connect dots across fundamentals, valuation and technicals."}},
    {{"title": "Short counter-argument title", "argument": "3-4 sentences with specific numbers, segment breakdowns, and data references."}},
    {{"title": "Short counter-argument title", "argument": "3-4 sentences with specific numbers, segment breakdowns, and data references."}}
  ],
  "summary": "Your {direction} thesis is correct if [specific conditions]. I assign [X]% probability to this playing out over 12 months because [specific reasoning connecting valuation, fundamentals, and catalysts]."
}}"""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=1800,
        messages=[{"role": "user", "content": prompt}],
    )
    import json as _json2, re as _re2
    raw = resp.content[0].text.strip()
    # Strip markdown code fences if present
    raw = _re2.sub(r'^```(?:json)?\s*', '', raw)
    raw = _re2.sub(r'\s*```$', '', raw.strip())
    try:
        result = _json2.loads(raw)
    except Exception:
        result = {"counters": [], "summary": raw}
    return result


# ══════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════
# FIX 9 — SHARED CONTRADICTION CHECK FUNCTION
# Called both by /committee/report and returned inline during Copilot chat
# ══════════════════════════════════════════════════════

def _run_contradiction_checks(sections: dict, live_price) -> list:
    """Run 5 deterministic contradiction checks. Returns list of flag strings (empty = no contradictions)."""
    fund = sections.get("fundamentals", {})
    dcf  = sections.get("dcf", {})
    tech = sections.get("technical", {})
    risk = sections.get("risk", {})
    cat  = sections.get("catalyst", {})
    conv = sections.get("conviction", {})
    flags = []

    # 1. Bullish margin outlook in fundamentals thesis but bear/base DCF scenario
    fund_thesis  = (fund.get("thesis_statement") or "").lower()
    dcf_scenario = (dcf.get("explicit_inputs") or {}).get("selected_scenario", "")
    if any(w in fund_thesis for w in ["margin expansion", "margin improvement", "improving margins"]) \
       and dcf_scenario in ("bear", "base"):
        flags.append(f"CONTRADICTION: Fundamentals thesis states margin expansion, but DCF scenario is '{dcf_scenario}'. These imply different margin trajectories.")

    # 2. High DCF implied upside but low valuation conviction score
    dcf_upside = (dcf.get("explicit_inputs") or {}).get("implied_upside_pct")
    val_score  = ((conv.get("explicit_inputs") or {}).get("signal_scores") or {}).get("valuation")
    if dcf_upside is not None and val_score is not None and dcf_upside > 30 and val_score < 5:
        flags.append(f"CONTRADICTION: DCF implies {dcf_upside}% upside but valuation conviction score is {val_score}/10. High upside with low confidence is internally inconsistent.")

    # 3. Short technical direction but strong business quality rating
    tech_dir   = (tech.get("explicit_inputs") or {}).get("direction", "")
    fund_qual  = (fund.get("explicit_inputs") or {}).get("quality_rating", "")
    if tech_dir == "short" and fund_qual == "strong":
        flags.append("CONTRADICTION: Technical direction is SHORT but fundamentals quality rating is STRONG. Shorting a high-quality business requires a specific catalyst — not addressed.")

    # 4. Stop-loss implies >2% portfolio loss at stated position size
    stop_price = (risk.get("explicit_inputs") or {}).get("stop_loss_price")
    pos_size   = (conv.get("explicit_inputs") or {}).get("position_size_pct")
    if stop_price and live_price and pos_size:
        try:
            downside_pct   = abs(float(live_price) - float(stop_price)) / float(live_price)
            portfolio_loss = downside_pct * (float(pos_size) / 100)
            if portfolio_loss > 0.02 and float(pos_size) > 5:
                flags.append(f"CONTRADICTION: Stop at {stop_price} implies {portfolio_loss*100:.1f}% portfolio loss at {pos_size}% position — exceeds 2% portfolio risk rule.")
        except (TypeError, ValueError):
            pass

    # 5. Negative catalyst language but bullish year-1 DCF growth
    cat_thesis     = (cat.get("thesis_statement") or "").lower()
    dcf_yr1_growth = (dcf.get("explicit_inputs") or {}).get("revenue_growth_yr1")
    if any(w in cat_thesis for w in ["negative", "miss", "downgrade", "warning", "risk"]) \
       and dcf_yr1_growth is not None and float(dcf_yr1_growth) > 10:
        flags.append(f"CONTRADICTION: Catalyst flags near-term negative risk, but DCF year-1 revenue growth is {dcf_yr1_growth}%. Short-term headwind not reflected in the model.")

    return flags


# ══════════════════════════════════════════════════════
# FIX 7 — DIALOGUE SUMMARISE ENDPOINT
# Called by frontend when user moves away from a section
# Compresses the Copilot dialogue into a 3-5 sentence summary for the Committee
# ══════════════════════════════════════════════════════

@app.post("/session/summarise")
def summarise_section_dialogue(payload: dict):
    """Compress a section's Copilot dialogue into a dialogue_summary for the Committee."""
    section_name = payload.get("section_name", "unknown")
    ticker       = payload.get("ticker", "").upper()
    messages     = payload.get("messages", [])

    if not messages:
        return {"dialogue_summary": ""}

    transcript = "\n".join([
        f"{m['role'].upper()}: {m['content']}"
        for m in messages[-20:]
    ])

    summary_prompt = f"""You are summarising a research dialogue about the {section_name} section for {ticker}.
The analyst has just finished this section. Compress the key conclusions, explicit inputs provided, and any unresolved questions into 3-5 sentences.
Focus on what changed in the analyst's thinking, not the process. Do not repeat data already in structured section outputs.

DIALOGUE:
{transcript}"""

    resp = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=300,
        messages=[{"role": "user", "content": summary_prompt}],
    )
    return {"dialogue_summary": resp.content[0].text.strip()}


# ══════════════════════════════════════════════════════
# FIX 10 — IN-MEMORY ENTITLEMENT TRACKING
# Red Team and Committee are premium features with per-session limits
# Keyed by session_id (until auth is re-enabled, then switch to user_id)
# ══════════════════════════════════════════════════════

_session_entitlements: dict = {}  # {session_id: {"red_team_remaining": int, "committee_remaining": int}}
_SESSION_RED_TEAM_LIMIT  = 3   # Red Team uses per session
_SESSION_COMMITTEE_LIMIT = 2   # Committee reports per session

def _check_and_deduct_entitlement(session_id: str, key: str, limit: int):
    """Raise 403 if entitlement exhausted, otherwise deduct 1."""
    if not session_id:
        return  # no session_id = unauthenticated, allow for now (pre-auth phase)
    ents = _session_entitlements.setdefault(session_id, {
        "red_team_remaining":  _SESSION_RED_TEAM_LIMIT,
        "committee_remaining": _SESSION_COMMITTEE_LIMIT,
    })
    remaining = ents.get(key, limit)
    if remaining <= 0:
        label = key.replace("_remaining", "").replace("_", " ").title()
        raise HTTPException(status_code=403, detail=f"No {label} uses remaining this session.")
    ents[key] = remaining - 1


# INVESTMENT COMMITTEE REPORT
# ══════════════════════════════════════════════════════

@app.post("/committee/report")
async def committee_report(payload: dict):
    """Fintiq Investment Committee — reviews compiled session, runs pre-checks, produces structured report."""
    import json as _cjson
    import re as _cre

    # Fix 10: entitlement check — 2 Committee reports per session
    session_id = payload.get("session_id", "")
    _check_and_deduct_entitlement(session_id, "committee_remaining", _SESSION_COMMITTEE_LIMIT)

    ticker      = payload.get("ticker", "UNKNOWN")
    live_price  = payload.get("live_price")
    analysis_date = payload.get("analysis_date", "")
    sections    = payload.get("sections", {})
    all_flags   = payload.get("all_flags", [])
    all_conclusions = payload.get("all_conclusions", [])

    fund  = sections.get("fundamentals", {})
    dcf   = sections.get("dcf", {})
    tech  = sections.get("technical", {})
    risk  = sections.get("risk", {})
    cat   = sections.get("catalyst", {})
    conv  = sections.get("conviction", {})

    # ── 5 DETERMINISTIC CONTRADICTION PRE-CHECKS (shared function) ──
    pre_flags = _run_contradiction_checks(sections, live_price)
    pre_flags_text = "\n".join(pre_flags) if pre_flags else "No deterministic contradictions detected in pre-check."

    # ── BUILD COMPILED CONTEXT FOR THE MODEL ──
    def summarise_section(name, sec):
        ei = sec.get("explicit_inputs") or {}
        conclusions = sec.get("conclusions") or []
        thesis = sec.get("thesis_statement") or ""
        dialogue = sec.get("dialogue_summary") or ""
        conc_text = " | ".join([c.get("value","") for c in conclusions[:5]]) if conclusions else ""
        return f"[{name.upper()}] status={sec.get('status','unknown')} thesis='{thesis}' explicit_inputs={_cjson.dumps(ei)} ai_dialogue_summary='{dialogue[:300]}' conclusions='{conc_text[:400]}'"

    compiled_text = "\n".join([
        summarise_section("fundamentals", fund),
        summarise_section("dcf", dcf),
        summarise_section("technical", tech),
        summarise_section("risk", risk),
        summarise_section("catalyst", cat),
        summarise_section("conviction", conv),
    ])

    prompt = f"""You are the chair of a buy-side Investment Committee reviewing a junior analyst's deep-dive on {ticker} (price: {live_price}, date: {analysis_date}).

IMPORTANT: You are reviewing the QUALITY of the analyst's work — not producing a stock opinion. Your report must visibly reference the analyst's own stated conclusions. If this report could have been written without their specific inputs, it is a product failure.

PRE-CHECKS (deterministic contradictions already identified):
{pre_flags_text}

COMPILED ANALYST SESSION:
{compiled_text}

ALL UNRESOLVED FLAGS: {_cjson.dumps(all_flags)[:1000]}

Produce a JSON report with exactly these fields:
{{
  "thesis": "2-3 sentences: the analyst's core investment thesis derived from their stated conclusions across all sections",
  "bull_case": "3-4 sentences: conditions under which this thesis succeeds — drawn from the analyst's own optimistic assumptions, not a generic upside narrative",
  "bear_case": "3-4 sentences: specific failure modes that would break the thesis — prioritised by the probability the analyst's own risk analysis assigned them",
  "contradictions": "Numbered list of internal inconsistencies. Include the pre-check findings above. Each must name the two specific conclusions in tension and why they cannot both be true. If none beyond pre-checks, say so.",
  "missing_evidence": "Specific material factors the analyst did NOT address, each with one sentence on why it matters for this thesis",
  "conditions": "Three structured lists: (1) conditions under which thesis is attractive, (2) conditions that would weaken it, (3) the single condition that would invalidate it entirely",
  "valuation_range": {{"bear": "price or N/A", "base": "price or N/A", "bull": "price or N/A"}},
  "confidence": {{
    "evidence_quality": "High | Medium | Low",
    "assumption_reliability": "High | Medium | Low",
    "unresolved_material_questions": <integer count>,
    "most_significant_unknown": "One sentence naming the single biggest open question"
  }}
}}

Be direct and rigorous. Name contradictions explicitly. The committee is not here to validate the analyst.
Return only the JSON object, no markdown fences."""

    resp = client.messages.create(
        model="claude-sonnet-4-5",
        max_tokens=2500,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = resp.content[0].text.strip()
    raw = _cre.sub(r'^```(?:json)?\s*', '', raw)
    raw = _cre.sub(r'\s*```$', '', raw.strip())
    try:
        result = _cjson.loads(raw)
        # Ensure confidence is always an object, never a number
        if isinstance(result.get("confidence"), (int, float)):
            result["confidence"] = {
                "evidence_quality": "Medium",
                "assumption_reliability": "Medium",
                "unresolved_material_questions": 0,
                "most_significant_unknown": "See missing evidence section above."
            }
        return result
    except Exception:
        return {"thesis": raw, "bull_case": "", "bear_case": "", "contradictions": pre_flags_text,
                "missing_evidence": "", "conditions": "", "valuation_range": {},
                "confidence": {"evidence_quality": None, "assumption_reliability": None,
                               "unresolved_material_questions": None, "most_significant_unknown": None}}

