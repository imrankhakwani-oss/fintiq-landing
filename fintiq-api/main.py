"""
Fintiq API — FastAPI backend for fintiq.uk
Serves: /bulletin, /market-data, /earnings, /health
Deployed to: api.fintiq.uk (Railway)
"""
import os, json, time, requests
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
_market_cache:   dict = {}; _market_cached_at:   float = 0.0; _MARKET_TTL   = 30*60
_earnings_cache: dict = {}; _earnings_cached_at: dict  = {};  _EARNINGS_TTL = 12*3600

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
    ("^VIX","VIX","Fear Index"),("GC=F","Gold","$/oz"),("BZ=F","Brent Oil","$/bbl"),
    ("CL=F","WTI Oil","$/bbl"),("DX-Y.NYB","Dollar Index","DXY"),
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
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","LLY","JPM","V","UNH",
        "XOM","TSLA","MA","AVGO","PG","HD","COST","JNJ","NFLX","ABBV",
        "BAC","WMT","CRM","CVX","MRK","AMD","ORCL","ACN","LIN","TMO",
        "PEP","ADBE","MCD","TXN","DHR","CSCO","ABT","GE","INTC","QCOM",
        "WFC","UNP","NEE","RTX","INTU","SPGI","AMGN","MS","BLK","SCHW",
    ],
    "nasdaq100": [
        "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","AVGO","COST","NFLX",
        "AMD","ADBE","QCOM","INTU","TXN","AMGN","ISRG","AMAT","MU","LRCX",
        "ADI","REGN","KLAC","MELI","PANW","SNPS","CDNS","CRWD","FTNT","ABNB",
        "ORLY","MNST","PCAR","CTAS","PAYX","MCHP","WDAY","DXCM","KDP","FAST",
    ],
    "ftse100": [
        "SHEL.L","AZN.L","HSBA.L","ULVR.L","DGE.L","BP.L","RIO.L","LLOY.L","GSK.L","BARC.L",
        "VOD.L","REL.L","EXPN.L","WPP.L","PRU.L","LGEN.L","BA.L","AAL.L","BHP.L","IMB.L",
        "MNG.L","ABF.L","CNA.L","SBRY.L","IHG.L","SGE.L","RKT.L","SSE.L","NG.L","GLEN.L",
    ],
    "stoxx50": [
        "ASML","MC.PA","OR.PA","TTE.PA","SIE.DE","AIR.PA","ALV.DE","BNP.PA","SAN.PA","SAP",
        "IBE.MC","ENEL.MI","ABI.BR","KER.PA","DSY.PA","BAS.DE","BAYN.DE","DTE.DE","ING","INGA.AS",
        "PHIA.AS","ADS.DE","ENI.MI","ISP.MI","UCG.MI","BBVA.MC","SU.PA","DG.PA","MUV2.DE","CS.PA",
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

def _fetch_web_context() -> str:
    if not TAVILY_API_KEY: return "Web search not configured."
    today = datetime.now().strftime("%B %d %Y")
    queries = [
        f"stock market news today {today}",
        f"Federal Reserve monetary policy news {today}",
        f"global economic outlook macro risks {today}",
        f"S&P 500 earnings season analyst outlook {today}",
    ]
    sections = []
    for q in queries:
        results = _tavily_search(q, max_results=4)
        if results:
            snippets = [f"• {r.get('title','')}: {r.get('content','').strip()[:300]}" for r in results[:4] if r.get('title')]
            if snippets: sections.append(f"[{q}]\n" + "\n".join(snippets))
    return "\n\n".join(sections) if sections else "No web results retrieved."

# ── Bulletin generation ────────────────────────────────────────────────────────
def _generate_bulletin() -> dict:
    syms = [s for s,_,_,_ in _BRIEF_INDICES] + [s for s,_,_ in _BRIEF_INSTRUMENTS]
    bd = _fetch_brief_data(syms)
    news = _fetch_market_news(); econ = _fetch_econ_calendar()
    sectors = _fetch_sector_data(); earnings_today = _fetch_earnings_today()
    web_context = _fetch_web_context()

    def pct(v): return f"{v:+.2f}%" if v is not None else "n/a"
    def pr(sym): return bd.get(sym, {})

    spx=pr("^GSPC"); vix=pr("^VIX"); gold=pr("GC=F"); brent=pr("BZ=F")
    dxy=pr("DX-Y.NYB"); tnx=pr("^TNX"); gbp=pr("GBPUSD=X"); eur=pr("EURUSD=X")
    jpy=pr("USDJPY=X"); spyf=pr("ES=F"); nqf=pr("NQ=F")

    mkt = (f"S&P 500: {spx.get('price','n/a')} ({pct(spx.get('chg_pct'))})\n"
           f"S&P Futures: {spyf.get('price','n/a')} ({pct(spyf.get('chg_pct'))})\n"
           f"Nasdaq Futures: {nqf.get('price','n/a')} ({pct(nqf.get('chg_pct'))})\n"
           f"VIX: {vix.get('price','n/a')}\nGold: {gold.get('price','n/a')} ({pct(gold.get('chg_pct'))})\n"
           f"Brent: {brent.get('price','n/a')} ({pct(brent.get('chg_pct'))})\n"
           f"DXY: {dxy.get('price','n/a')} ({pct(dxy.get('chg_pct'))})\n"
           f"10Y UST: {tnx.get('price','n/a')}%\nGBP/USD: {gbp.get('price','n/a')}\n"
           f"EUR/USD: {eur.get('price','n/a')}\nUSD/JPY: {jpy.get('price','n/a')}\n")

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

    now = datetime.now(); hour = now.hour
    session = "Pre-Market" if hour<8 else "Morning" if hour<12 else "Midday" if hour<14 else "Close Watch" if hour<16 else "After-Hours"

    prompt = (
        f"You are a Senior Research Analyst writing the {session.upper()} BULLETIN for a professional trading desk.\n"
        f"Write for a retail investor who wants professional-grade insight in plain English — no jargon, no filler.\n\n"
        f"LIVE MARKET DATA:\n{mkt}\nSECTOR PERFORMANCE:\n{sector_txt}\n\n"
        f"ASIA / EUROPE OVERNIGHT:\n{region_txt}\n\nFMP NEWS HEADLINES:\n{news_txt}\n\n"
        f"UPCOMING ECONOMIC EVENTS:\n{econ_txt}\n\nTODAY'S EARNINGS:\n{earnings_txt}\n\n"
        f"LIVE WEB CONTEXT (use this to add narrative depth and reference real events):\n{web_context}\n\n"
        "Use the live web context to make the bulletin richer and grounded in what is actually happening today. "
        "Respond ONLY with valid JSON. No markdown fences, no text outside JSON object, "
        "NEVER use double-quote characters inside string values — use single quotes or dashes instead, "
        "no newline characters inside string values.\n"
        '{{"the_call":{{"headline":"One bold sentence — the single most important thing today.",'
        '"bullets":["Futures: direction and %","Leading sector: strongest and why",'
        '"Volatility: VIX level in plain English","Bonds: 10Y yield implication",'
        '"Today earnings: key reporters","Economic events: key releases","Watch: one specific level"]}},'
        '"risk_radar":[{{"flag":"🔴","title":"4-6 word title","detail":"2-3 sentences."}},'
        '{{"flag":"🟡","title":"...","detail":"..."}},{{"flag":"🟢","title":"...","detail":"..."}},'
        '{{"flag":"🔵","title":"...","detail":"..."}}],'
        '"macro_pulse":"5-7 sentences on WHY markets are moving. Market regime, cross-asset flows, dominant macro driver. Reference specific news from web context.",'
        '"equity_flow":"5-7 sentences. Sector rotation, style rotation, unusual divergences. Use web context for analyst views.",'
        '"overnight_wires":"2-3 sentences on Asia and Europe overnight and implication for US trading today.",'
        '"trade_ideas":[{{"setup":"Stock or theme","thesis":"Why interesting now — reference a real catalyst","entry":"Price level or trigger","risk":"What could go wrong"}},'
        '{{"setup":"...","thesis":"...","entry":"...","risk":"..."}},{{"setup":"...","thesis":"...","entry":"...","risk":"..."}}]}}'
    )

    if not ANTHROPIC_API_KEY: raise RuntimeError("ANTHROPIC_API_KEY not set")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    for attempt in range(3):
        try:
            resp = client.messages.create(model="claude-haiku-4-5-20251001", max_tokens=4000,
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

    # FMP economic + treasury (parallel)
    cpi = nfp = spread = None
    try:
        with ThreadPoolExecutor(max_workers=3) as ex:
            f_cpi    = ex.submit(_fetch_econ_indicator, "CPI")
            f_nfp    = ex.submit(_fetch_econ_indicator, "nonFarmPayrolls")
            f_spread = ex.submit(_fetch_treasury_spread)
            cpi_r = f_cpi.result(timeout=12); nfp_r = f_nfp.result(timeout=12)
            spread = f_spread.result(timeout=12)
            cpi = cpi_r.get("value") if cpi_r else None
            nfp = nfp_r.get("value") if nfp_r else None
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

    return {
        "macro_indicators": {
            "fomc_days": fomc_days, "fomc_date": fomc_date,
            "treasury_10y": tnx.get("price"), "yield_curve_spread": spread,
            "cpi_yoy": cpi, "nfp_mom": nfp,
            "vix": vix.get("price"), "dxy": dxy.get("price"),
            "brent": brent.get("price"), "gold": gold.get("price"),
        },
        "major_markets": markets,
        "generated_at": datetime.now().isoformat(),
    }

# ── Earnings tracker ───────────────────────────────────────────────────────────
def _fetch_single_earnings(symbol: str) -> Optional[dict]:
    try:
        r = requests.get(f"{FMP_BASE}/v3/earnings-surprises/{symbol}?apikey={FMP_KEY}", timeout=8)
        quarters = []
        if r.status_code == 200:
            for q in (r.json() or [])[:4]:
                actual = q.get("actualEarningResult"); est = q.get("estimatedEarning")
                beat_pct = round((actual-est)/abs(est)*100, 1) if actual is not None and est and est!=0 else None
                quarters.append({"date":q.get("date","")[:7],"actual":actual,"estimate":est,"beat_pct":beat_pct})
        if not quarters: return None

        est_r = requests.get(f"{FMP_BASE}/v3/analyst-estimates/{symbol}?period=quarter&limit=2&apikey={FMP_KEY}", timeout=8)
        estimates = []
        if est_r.status_code == 200:
            for e in (est_r.json() or [])[:2]:
                estimates.append({"date":e.get("date","")[:7],"eps_est":e.get("estimatedEpsAvg")})

        return {"symbol":symbol,"quarters":quarters,"estimates":estimates}
    except: return None

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

# ── Routes ─────────────────────────────────────────────────────────────────────
@app.get("/health")
def health():
    return {"status":"ok","service":"fintiq-api","time":datetime.now().isoformat(),"web_search":bool(TAVILY_API_KEY)}

@app.get("/bulletin")
def get_bulletin():
    global _bulletin_cache, _bulletin_cached_at
    age = time.time() - _bulletin_cached_at
    if _bulletin_cache and age < _BULLETIN_TTL:
        return {**_bulletin_cache,"cached":True,"age_minutes":round(age/60)}
    try:
        _bulletin_cache = _generate_bulletin(); _bulletin_cached_at = time.time()
        return {**_bulletin_cache,"cached":False,"age_minutes":0}
    except Exception as e:
        if _bulletin_cache: return {**_bulletin_cache,"cached":True,"stale":True,"age_minutes":round((time.time()-_bulletin_cached_at)/60)}
        raise HTTPException(status_code=503, detail=f"Bulletin generation failed: {str(e)}")

@app.post("/bulletin/refresh")
def refresh_bulletin(token: Optional[str] = None):
    global _bulletin_cache, _bulletin_cached_at
    if token != REFRESH_TOKEN: raise HTTPException(status_code=401, detail="Invalid refresh token")
    try:
        _bulletin_cache = _generate_bulletin(); _bulletin_cached_at = time.time()
        return {"status":"refreshed","timestamp":_bulletin_cache.get("timestamp")}
    except Exception as e:
        raise HTTPException(status_code=503, detail=str(e))

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
    """Debug: test FMP earnings-surprises for a single ticker"""
    url = f"{FMP_BASE}/v3/earnings-surprises/{symbol}?apikey={FMP_KEY}"
    try:
        r = requests.get(url, timeout=10)
        return {"symbol": symbol, "status": r.status_code, "url": url, "body": r.json()}
    except Exception as e:
        return {"symbol": symbol, "error": str(e)}

@app.get("/earnings")
def get_earnings(index: str = "sp500", force: bool = False):
    if index not in _INDEX_TICKERS:
        raise HTTPException(status_code=400, detail=f"Unknown index: {index}")
    global _earnings_cache, _earnings_cached_at
    age = time.time() - _earnings_cached_at.get(index, 0)
    # Only serve cache if it has data, is fresh, and force=False
    if not force and index in _earnings_cache and _earnings_cache[index] and age < _EARNINGS_TTL:
        return {"index":index,"data":_earnings_cache[index],"cached":True}
    try:
        data = _fetch_index_earnings(index)
        if data:  # only cache non-empty results
            _earnings_cache[index] = data; _earnings_cached_at[index] = time.time()
        return {"index":index,"data":data,"cached":False,"count":len(data)}
    except Exception as e:
        if index in _earnings_cache and _earnings_cache[index]:
            return {"index":index,"data":_earnings_cache[index],"cached":True,"stale":True}
        raise HTTPException(status_code=503, detail=str(e))
