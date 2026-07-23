"""
Fintiq Factor Screener — Production Script
==========================================
Fama-French 4-Factor (Mkt, SMB, HML, MOM) regression on US equities.

Outputs:
  ../Articles/screener-data.json   — full ranked stock list
  ../Articles/screener-meta.json   — summary stats + timestamp

Usage:
  python run_screener.py              # default: 2-year lookback
  python run_screener.py --years 1    # 1-year lookback
  python run_screener.py --years 3    # 3-year lookback

Schedule: run weekly via GitHub Actions or Windows Task Scheduler.
Dependencies: pip install -r requirements.txt
"""

import argparse
import io
import json
import os
import time
import warnings
import zipfile
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import requests
import statsmodels.api as sm
import yfinance as yf

warnings.filterwarnings("ignore")

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36'
}

# ─── CONFIG ──────────────────────────────────────────────────────────────────

OUTPUT_DIR = os.path.join(os.path.dirname(__file__), "..", "Articles")
MIN_TRADING_DAYS = 120          # skip stocks with fewer observations
P_VALUE_GREEN    = 0.05         # 95% confidence → green signal
P_VALUE_AMBER    = 0.15         # 85% confidence → amber signal
BATCH_SIZE       = 50           # tickers per Yahoo Finance batch call
TRADING_DAYS_PER_YEAR = 252

# ─── TICKER LISTS ────────────────────────────────────────────────────────────

def get_sp500_tickers():
    """Fetch S&P 500 constituents from Wikipedia with browser User-Agent."""
    try:
        html = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=HEADERS, timeout=15
        ).text
        tables = pd.read_html(io.StringIO(html), header=0)
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        print(f"  S&P 500: {len(tickers)} tickers")
        return tickers
    except Exception as e:
        print(f"  Warning: could not fetch S&P 500 from Wikipedia ({e}). Using fallback list.")
        return SP500_FALLBACK

def get_nasdaq100_tickers():
    """Fetch NASDAQ 100 constituents from Wikipedia with browser User-Agent."""
    try:
        html = requests.get(
            "https://en.wikipedia.org/wiki/Nasdaq-100",
            headers=HEADERS, timeout=15
        ).text
        tables = pd.read_html(io.StringIO(html), header=0)
        for t in tables:
            if "Ticker" in t.columns:
                tickers = t["Ticker"].str.replace(".", "-", regex=False).tolist()
                print(f"  NASDAQ 100: {len(tickers)} tickers")
                return tickers
        raise ValueError("Ticker column not found")
    except Exception as e:
        print(f"  Warning: could not fetch NASDAQ 100 from Wikipedia ({e}). Using fallback list.")
        return NASDAQ100_FALLBACK

# Dow 30 — stable enough to hardcode
DOW30 = [
    "AAPL","AMGN","AXP","BA","CAT","CRM","CSCO","CVX","DIS","DOW",
    "GS","HD","HON","IBM","INTC","JNJ","JPM","KO","MCD","MMM",
    "MRK","MSFT","NKE","PG","SHW","TRV","UNH","V","VZ","WMT"
]

# Small fallback lists in case Wikipedia scraping fails
SP500_FALLBACK = [
    "AAPL","MSFT","AMZN","NVDA","GOOGL","META","BRK-B","LLY","AVGO","JPM",
    "UNH","XOM","V","TSLA","MA","PG","JNJ","COST","HD","MRK","ABBV","CVX",
    "BAC","KO","PEP","ADBE","WMT","AMD","CRM","MCD","ACN","LIN","TMO","CSCO",
    "ABT","PFE","DHR","TXN","NFLX","AMGN","PM","NEE","RTX","INTC","BMY",
    "UPS","QCOM","HON","IBM","INTU","AMAT","CAT","DE","BA","GS","BLK","AXP",
    "SYK","SBUX","GE","MDLZ","GILD","ADI","REGN","VRTX","C","MS","SPGI",
    "T","CVS","CI","MO","DUK","SO","MMC","ZTS","ELV","CL","EOG","SLB",
    "WBA","HCA","TJX","PLD","ISRG","AON","ETN","MCO","USB","F","GM","COP",
]

NASDAQ100_FALLBACK = [
    "AAPL","MSFT","AMZN","NVDA","META","GOOGL","GOOG","TSLA","AVGO","ADBE",
    "COST","CSCO","AMD","NFLX","INTC","QCOM","TXN","AMGN","INTU","CMCSA",
    "PEP","TMUS","HON","AMAT","SBUX","MDLZ","ISRG","REGN","VRTX","ADP",
    "PANW","GILD","LRCX","MU","ADI","KLAC","SNPS","CDNS","MELI","ASML",
    "ABNB","PYPL","ORLY","CTAS","CSX","NXPI","MNST","ROST","PCAR","CEG",
]

# ─── FACTOR DATA ─────────────────────────────────────────────────────────────

def _download_french_zip(url):
    """Download a French Data Library zip and return the CSV text inside."""
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    csv_name = [n for n in z.namelist() if n.upper().endswith('.CSV')][0]
    return z.open(csv_name).read().decode('utf-8', errors='ignore')

def _parse_french_csv(text):
    """
    Parse a French Data Library daily CSV.
    Robust parser: finds the first 8-digit date line, infers header from
    the line immediately before it, reads all data until dates stop.
    Handles both comma-separated and whitespace-separated formats.
    """
    lines = text.splitlines()

    # Detect separator: comma or whitespace
    sep = ','
    for line in lines:
        stripped = line.strip()
        if stripped and stripped[:8].isdigit():
            sep = ',' if ',' in stripped else None  # None = whitespace
            break

    # Find the index of the first data line (8-digit date)
    data_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and stripped[:8].isdigit():
            data_start = i
            break

    if data_start is None:
        raise ValueError("Could not find data rows in French CSV")

    # Header is the last non-empty line before data_start
    header_line = None
    for i in range(data_start - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped:
            header_line = stripped
            break

    if header_line is None:
        raise ValueError("Could not find header row in French CSV")

    # Parse header
    if sep == ',':
        col_names = [c.strip() for c in header_line.split(',') if c.strip()]
    else:
        col_names = header_line.split()

    # Parse data rows
    rows = []
    for line in lines[data_start:]:
        stripped = line.strip()
        if not stripped:
            continue
        if sep == ',':
            parts = [p.strip() for p in stripped.split(',')]
        else:
            parts = stripped.split()
        # Must start with 8-digit date
        if not parts[0].isdigit() or len(parts[0]) != 8:
            break
        rows.append(parts)

    if not rows:
        raise ValueError("No data rows found in French CSV")

    # Build DataFrame — date + as many columns as we have names
    n_cols = min(len(col_names), len(rows[0]) - 1)
    df = pd.DataFrame(rows, columns=['Date'] + col_names[:n_cols] + ['_extra'] * (len(rows[0]) - 1 - n_cols))
    df = df[['Date'] + col_names[:n_cols]]
    df['Date'] = pd.to_datetime(df['Date'].str.strip(), format='%Y%m%d')
    df = df.set_index('Date')
    df = df.apply(pd.to_numeric, errors='coerce').dropna()
    return df

def get_french_factors(start_date, end_date):
    """
    Download Fama-French 3-factor + Momentum daily data directly from
    Kenneth French's website (bypasses pandas-datareader Python 3.14 bug).
    Returns DataFrame with columns: Mkt-RF, SMB, HML, MOM, RF (as decimals).
    """
    print("  Downloading Fama-French factor data (direct from French library)...")
    BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    try:
        ff3_text  = _download_french_zip(BASE + "F-F_Research_Data_Factors_daily_CSV.zip")
        mom_text  = _download_french_zip(BASE + "F-F_Momentum_Factor_daily_CSV.zip")
        ff3  = _parse_french_csv(ff3_text)
        mom  = _parse_french_csv(mom_text)

        # Standardise column names
        ff3.columns = [c.strip() for c in ff3.columns]
        mom.columns = [c.strip() for c in mom.columns]

        # Momentum column is usually 'Mom' or 'Mom   '
        mom_col = [c for c in mom.columns if 'mom' in c.lower()][0]
        mom = mom.rename(columns={mom_col: 'MOM'})

        factors = ff3.join(mom[['MOM']], how='inner')
        factors = factors / 100.0   # % → decimal

        # Filter to requested date range
        factors = factors[(factors.index >= pd.Timestamp(start_date)) &
                          (factors.index <= pd.Timestamp(end_date))]

        print(f"  Factor data: {len(factors)} trading days "
              f"({factors.index[0].date()} to {factors.index[-1].date()})")
        print(f"  Columns: {list(factors.columns)}")
        return factors
    except Exception as e:
        raise RuntimeError(f"Failed to download French factor data: {e}")

# ─── PRICE DATA ──────────────────────────────────────────────────────────────

def get_prices_batch(tickers, start_date, end_date):
    """
    Download adjusted close prices for a batch of tickers via yfinance.
    Returns DataFrame: index=Date, columns=tickers
    """
    try:
        raw = yf.download(
            tickers,
            start=start_date,
            end=end_date,
            auto_adjust=True,
            progress=False,
            threads=True
        )
        if isinstance(raw.columns, pd.MultiIndex):
            prices = raw["Close"]
        else:
            prices = raw[["Close"]] if "Close" in raw.columns else raw
        prices.index = pd.to_datetime(prices.index)
        return prices
    except Exception as e:
        print(f"    Batch download error: {e}")
        return pd.DataFrame()

# ─── REGRESSION ──────────────────────────────────────────────────────────────

def run_regression(excess_returns, factors):
    """
    OLS regression: R_i - RF = alpha + b1*Mkt-RF + b2*SMB + b3*HML + b4*MOM + e
    Returns dict with alpha (annualised), factor loadings, p-values, R-squared.
    """
    X = factors[["Mkt-RF", "SMB", "HML", "MOM"]].copy()
    X = sm.add_constant(X)
    y = excess_returns

    # Align indices
    aligned = pd.concat([y, X], axis=1).dropna()
    if len(aligned) < MIN_TRADING_DAYS:
        return None

    y_clean = aligned.iloc[:, 0]
    X_clean = aligned.iloc[:, 1:]

    try:
        model  = sm.OLS(y_clean, X_clean).fit(cov_type="HC3")  # robust standard errors
        alpha_daily = model.params["const"]
        alpha_annual = alpha_daily * TRADING_DAYS_PER_YEAR * 100  # annualised %
        pval_alpha   = model.pvalues["const"]
        tstat_alpha  = model.tvalues["const"]

        return {
            "alpha_daily":  round(alpha_daily, 6),
            "alpha":        round(alpha_annual, 2),
            "pval":         round(float(pval_alpha), 4),
            "tstat":        round(float(tstat_alpha), 3),
            "beta":         round(float(model.params["Mkt-RF"]), 3),
            "smb":          round(float(model.params["SMB"]), 3),
            "hml":          round(float(model.params["HML"]), 3),
            "mom":          round(float(model.params["MOM"]), 3),
            "r_squared":    round(float(model.rsquared), 3),
            "n_obs":        len(aligned),
        }
    except Exception:
        return None

# ─── SIGNAL + INSIGHT ────────────────────────────────────────────────────────

def classify_signal(alpha, pval):
    if alpha > 0 and pval < P_VALUE_GREEN:
        return "green"
    elif alpha > 0 and pval < P_VALUE_AMBER:
        return "amber"
    elif alpha <= 0 and pval < P_VALUE_GREEN:
        return "red"   # significantly negative
    elif alpha <= 0:
        return "red"   # negative regardless
    else:
        return "amber"

def dominant_factor(beta_excess, smb, hml, mom):
    """Return the label and direction of the largest absolute factor loading."""
    factors = {
        "market beta": abs(beta_excess),
        "size (SMB)":  abs(smb),
        "value (HML)": abs(hml),
        "momentum":    abs(mom),
    }
    return max(factors, key=factors.get)

def generate_insight(ticker, alpha, pval, beta, smb, hml, mom, signal, r_squared):
    """Rule-based plain English interpretation."""
    alpha_str = f"+{alpha:.1f}%" if alpha >= 0 else f"{alpha:.1f}%"
    dom = dominant_factor(beta - 1, smb, hml, mom)
    r2_pct = round(r_squared * 100)

    if signal == "green":
        if mom > 0.6:
            return (f"Strong momentum-driven alpha. The four factors explain {r2_pct}% of this stock's returns, "
                    f"but {alpha_str}/yr remains unexplained — genuine outperformance. "
                    f"Momentum is the dominant exposure ({mom:+.2f}). Statistically significant at p={pval:.3f}.")
        elif smb < -0.3 and hml < -0.2:
            return (f"Large-cap growth alpha. Returns are partly driven by the growth factor, "
                    f"but {alpha_str}/yr sits above and beyond that. Quality business characteristics "
                    f"driving factor-adjusted outperformance. High confidence (p={pval:.3f}).")
        elif beta < 0.8:
            return (f"Defensive alpha — low market beta ({beta:.2f}) yet generating {alpha_str}/yr above factor predictions. "
                    f"Rare combination of downside protection and genuine outperformance. Strong signal (p={pval:.3f}).")
        else:
            return (f"Genuine factor-adjusted outperformance of {alpha_str}/yr. "
                    f"Dominant factor exposure: {dom}. The model explains {r2_pct}% of returns — "
                    f"the residual alpha is statistically significant (p={pval:.3f}).")

    elif signal == "amber":
        return (f"Positive alpha of {alpha_str}/yr but below our 95% significance hurdle (p={pval:.3f}). "
                f"May be a real signal — monitor across the next 1–2 quarters. "
                f"Dominant factor: {dom}. Not a strong enough signal to act on alone.")

    else:  # red
        if pval < P_VALUE_GREEN:
            return (f"Significantly negative alpha ({alpha_str}/yr, p={pval:.3f}). "
                    f"This stock is underperforming its factor benchmarks with high statistical confidence. "
                    f"Negative {dom} drag is prominent. Avoid for a factor-based strategy.")
        else:
            return (f"Negative alpha ({alpha_str}/yr) — returns are below what the factors predict. "
                    f"Signal is not statistically definitive (p={pval:.3f}), but the direction is clearly negative. "
                    f"No factor-adjusted edge here.")

# ─── COMPANY NAMES ───────────────────────────────────────────────────────────

def get_company_names(tickers):
    """Batch fetch long names from yfinance. Falls back to ticker if unavailable."""
    names = {}
    print(f"  Fetching company names for {len(tickers)} tickers...")
    for i in range(0, len(tickers), 100):
        batch = tickers[i:i+100]
        for ticker in batch:
            try:
                info = yf.Ticker(ticker).fast_info
                names[ticker] = getattr(info, "description", None) or ticker
            except Exception:
                names[ticker] = ticker
        time.sleep(0.5)

    # Use a faster bulk approach — just yf.Tickers
    try:
        bulk = yf.Tickers(" ".join(tickers))
        for t in tickers:
            try:
                name = bulk.tickers[t].info.get("longName") or bulk.tickers[t].info.get("shortName") or t
                names[t] = name
            except Exception:
                if t not in names:
                    names[t] = t
    except Exception:
        pass

    return names

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main(years=2):
    print(f"\n{'='*60}")
    print(f"  Fintiq Factor Screener — {years}-year lookback")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}\n")

    end_date   = datetime.today()
    start_date = end_date - timedelta(days=int(years * 365.25) + 30)  # extra buffer for alignment

    # ── 1. Build universe ──────────────────────────────────────────────────
    print("Step 1: Building US equity universe...")
    sp500  = get_sp500_tickers()
    nq100  = get_nasdaq100_tickers()
    dow30  = set(DOW30)

    sp_set = set(sp500)
    nq_set = set(nq100)

    all_tickers = list(sp_set | nq_set | dow30)
    print(f"  Universe: {len(all_tickers)} unique tickers\n")

    # Index membership map
    index_map = {}
    for t in all_tickers:
        idxs = []
        if t in sp_set: idxs.append("sp")
        if t in nq_set: idxs.append("nq")
        if t in dow30:  idxs.append("dj")
        index_map[t] = idxs

    # ── 2. Factor data ─────────────────────────────────────────────────────
    print("Step 2: Downloading factor data...")
    factors = get_french_factors(start_date, end_date)
    print()

    # ── 3. Price data ──────────────────────────────────────────────────────
    print(f"Step 3: Downloading price data in batches of {BATCH_SIZE}...")
    all_prices = pd.DataFrame()
    batches = [all_tickers[i:i+BATCH_SIZE] for i in range(0, len(all_tickers), BATCH_SIZE)]
    for i, batch in enumerate(batches):
        print(f"  Batch {i+1}/{len(batches)} ({len(batch)} tickers)...")
        prices = get_prices_batch(batch, start_date.strftime("%Y-%m-%d"), end_date.strftime("%Y-%m-%d"))
        if not prices.empty:
            all_prices = prices if all_prices.empty else all_prices.join(prices, how="outer")
        time.sleep(1)  # rate limit courtesy pause
    print(f"  Total price series: {all_prices.shape[1]} tickers × {all_prices.shape[0]} days\n")

    # ── 4. Company names ───────────────────────────────────────────────────
    print("Step 4: Fetching company names...")
    # Use a lightweight approach — download once from yfinance info
    names = {}
    try:
        for batch in batches:
            tickers_str = " ".join(batch)
            data = yf.download(batch, period="1d", progress=False, auto_adjust=True)
            # Names aren't in price data — use Tickers object for a sample
        # Fallback: just use ticker as name for speed; enrich later
        for t in all_tickers:
            names[t] = t
        # Quick name lookup for well-known stocks
        NAME_OVERRIDES = {
            "AAPL":"Apple Inc.","MSFT":"Microsoft Corporation","AMZN":"Amazon.com Inc.",
            "NVDA":"NVIDIA Corporation","GOOGL":"Alphabet Inc.","META":"Meta Platforms Inc.",
            "TSLA":"Tesla Inc.","LLY":"Eli Lilly & Co.","V":"Visa Inc.",
            "MA":"Mastercard Inc.","UNH":"UnitedHealth Group","JNJ":"Johnson & Johnson",
            "XOM":"ExxonMobil Corporation","JPM":"JPMorgan Chase & Co.",
            "AVGO":"Broadcom Inc.","PG":"Procter & Gamble","HD":"The Home Depot Inc.",
            "COST":"Costco Wholesale Corp.","MRK":"Merck & Co.","ABBV":"AbbVie Inc.",
            "BAC":"Bank of America Corp.","KO":"The Coca-Cola Company","PEP":"PepsiCo Inc.",
            "ADBE":"Adobe Inc.","WMT":"Walmart Inc.","AMD":"Advanced Micro Devices",
            "CRM":"Salesforce Inc.","MCD":"McDonald's Corporation","ACN":"Accenture plc",
            "TMO":"Thermo Fisher Scientific","CSCO":"Cisco Systems Inc.",
            "ABT":"Abbott Laboratories","PFE":"Pfizer Inc.","DHR":"Danaher Corporation",
            "NFLX":"Netflix Inc.","AMGN":"Amgen Inc.","PM":"Philip Morris International",
            "RTX":"RTX Corporation","INTC":"Intel Corporation","BMY":"Bristol-Myers Squibb",
            "QCOM":"Qualcomm Inc.","HON":"Honeywell International","IBM":"IBM Corporation",
            "INTU":"Intuit Inc.","AMAT":"Applied Materials Inc.","CAT":"Caterpillar Inc.",
            "DE":"Deere & Company","BA":"Boeing Company","GS":"Goldman Sachs Group",
            "BLK":"BlackRock Inc.","AXP":"American Express Company",
            "CVS":"CVS Health Corp.","T":"AT&T Inc.","WBA":"Walgreens Boots Alliance",
            "GOOGL":"Alphabet Inc. Class A","GOOG":"Alphabet Inc. Class C",
            "BRK-B":"Berkshire Hathaway Inc.","SPGI":"S&P Global Inc.",
            "CL":"Colgate-Palmolive","EOG":"EOG Resources","SLB":"Schlumberger Ltd.",
        }
        names.update(NAME_OVERRIDES)
    except Exception as e:
        print(f"  Name lookup error (non-fatal): {e}")
        for t in all_tickers:
            names[t] = t
    print(f"  Names loaded for {len(names)} tickers\n")

    # ── 5. Run regressions ─────────────────────────────────────────────────
    print("Step 5: Running OLS regressions...")
    results = []
    skipped = 0
    factor_aligned = factors[["Mkt-RF", "SMB", "HML", "MOM", "RF"]].copy()

    for i, ticker in enumerate(all_tickers):
        if i % 50 == 0:
            print(f"  Progress: {i}/{len(all_tickers)} ({len(results)} successful, {skipped} skipped)")

        if ticker not in all_prices.columns:
            skipped += 1
            continue

        price_series = all_prices[ticker].dropna()
        if len(price_series) < MIN_TRADING_DAYS:
            skipped += 1
            continue

        # Daily returns
        daily_returns = price_series.pct_change().dropna()
        daily_returns.name = "RET"  # force a safe name to avoid column collisions

        # Separate RF and factors before join
        rf_series      = factor_aligned["RF"].copy()
        factor_cols    = factor_aligned[["Mkt-RF", "SMB", "HML", "MOM"]].copy()

        # Align stock returns with RF and factors on common dates
        combined = pd.concat([daily_returns, rf_series, factor_cols], axis=1, join="inner").dropna()
        if len(combined) < MIN_TRADING_DAYS:
            skipped += 1
            continue

        # Excess return = stock return - risk-free rate (all plain numpy, no ambiguity)
        stock_np  = combined["RET"].to_numpy(dtype=float)
        rf_np     = combined["RF"].to_numpy(dtype=float)
        excess_returns = pd.Series(stock_np - rf_np, index=combined.index, dtype=float)
        reg_factors    = combined[["Mkt-RF", "SMB", "HML", "MOM"]].copy()

        reg = run_regression(excess_returns, reg_factors.copy())
        if reg is None:
            skipped += 1
            continue

        signal = classify_signal(reg["alpha"], reg["pval"])
        insight = generate_insight(
            ticker, reg["alpha"], reg["pval"],
            reg["beta"], reg["smb"], reg["hml"], reg["mom"],
            signal, reg["r_squared"]
        )

        results.append({
            "ticker":    ticker,
            "name":      names.get(ticker, ticker),
            "alpha":     reg["alpha"],
            "pval":      reg["pval"],
            "tstat":     reg["tstat"],
            "beta":      reg["beta"],
            "smb":       reg["smb"],
            "hml":       reg["hml"],
            "mom":       reg["mom"],
            "r_squared": reg["r_squared"],
            "n_obs":     reg["n_obs"],
            "signal":    signal,
            "idx":       index_map.get(ticker, []),
            "insight":   insight,
        })

    print(f"\n  Completed: {len(results)} stocks processed, {skipped} skipped\n")

    # ── 6. Sort and rank ───────────────────────────────────────────────────
    results.sort(key=lambda x: x["alpha"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    # ── 7. Compute meta stats ──────────────────────────────────────────────
    alphas     = [r["alpha"] for r in results]
    green_list = [r for r in results if r["signal"] == "green"]
    amber_list = [r for r in results if r["signal"] == "amber"]
    red_list   = [r for r in results if r["signal"] == "red"]
    median_alpha = round(float(np.median(alphas)), 2) if alphas else 0.0

    meta = {
        "generated_at":    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_date":  datetime.utcnow().strftime("%d %b %Y"),
        "lookback_years":  years,
        "lookback_days":   int(years * TRADING_DAYS_PER_YEAR),
        "universe":        "US Equities (S&P 500 + NASDAQ 100 + Dow 30)",
        "universe_count":  len(results),
        "green_count":     len(green_list),
        "amber_count":     len(amber_list),
        "red_count":       len(red_list),
        "median_alpha":    median_alpha,
        "factor_model":    "Fama-French 4-Factor (Mkt · SMB · HML · MOM)",
        "data_source":     "Kenneth French Data Library + Yahoo Finance",
        "alpha_hurdle":    "p < 0.05 (95% confidence) for green; p < 0.15 for amber",
    }

    # ── 8. Write outputs ───────────────────────────────────────────────────
    print("Step 6: Writing output files...")

    data_path = os.path.join(OUTPUT_DIR, "screener-data.json")
    meta_path = os.path.join(OUTPUT_DIR, "screener-meta.json")

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump({"stocks": results}, f, ensure_ascii=False, separators=(",", ":"))

    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"  screener-data.json → {len(results)} stocks ({os.path.getsize(data_path)//1024} KB)")
    print(f"  screener-meta.json → written")

    # ── 9. Summary ─────────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print(f"  DONE — {len(results)} stocks ranked")
    print(f"  Green signals:  {len(green_list)}")
    print(f"  Amber signals:  {len(amber_list)}")
    print(f"  Red signals:    {len(red_list)}")
    print(f"  Median alpha:   {'+' if median_alpha >= 0 else ''}{median_alpha}% / yr")
    print(f"\n  Top 10 by alpha:")
    for r in results[:10]:
        sig_icon = "🟢" if r["signal"] == "green" else ("🟡" if r["signal"] == "amber" else "🔴")
        print(f"    {sig_icon} {r['ticker']:<8} {'+' if r['alpha']>=0 else ''}{r['alpha']:.1f}%/yr  (p={r['pval']:.3f})")
    print(f"\n  Bottom 5 by alpha:")
    for r in results[-5:]:
        print(f"    🔴 {r['ticker']:<8} {r['alpha']:.1f}%/yr  (p={r['pval']:.3f})")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fintiq Factor Screener")
    parser.add_argument("--years", type=float, default=2,
                        help="Lookback period in years (default: 2)")
    args = parser.parse_args()
    main(years=args.years)
