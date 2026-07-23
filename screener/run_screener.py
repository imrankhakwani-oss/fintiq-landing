"""
Fintiq Factor Screener — Production Script
==========================================
Fama-French 4-Factor (Mkt, SMB, HML, MOM) regression on US equities.

Outputs (all three lookbacks in one run):
  ../Articles/screener-data-1y.json   — 1-year lookback
  ../Articles/screener-data-2y.json   — 2-year lookback
  ../Articles/screener-data-3y.json   — 3-year lookback
  ../Articles/screener-meta-1y.json
  ../Articles/screener-meta-2y.json
  ../Articles/screener-meta-3y.json
  ../Articles/screener-data.json      — copy of 2y (backward compat)
  ../Articles/screener-meta.json      — copy of 2y (backward compat)

Usage:
  python run_screener.py              # runs all three lookbacks
  python run_screener.py --years 2    # single lookback (legacy)

Schedule: run weekly via GitHub Actions.
Dependencies: pip install -r requirements.txt
"""

import argparse
import io
import json
import os
import shutil
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

OUTPUT_DIR           = os.path.join(os.path.dirname(__file__), "..", "Articles")
MIN_COVERAGE_RATIO   = 0.80          # require 80% of expected trading days
P_VALUE_GREEN        = 0.05          # 95% confidence → green signal
P_VALUE_AMBER        = 0.15          # 85% confidence → amber signal
BATCH_SIZE           = 50            # tickers per Yahoo Finance batch call
TRADING_DAYS_PER_YEAR = 252
ALPHA_CAP            = 250.0         # exclude stocks with |alpha| > 250%/yr (bad data)

# ─── TICKER LISTS ────────────────────────────────────────────────────────────

def get_sp500():
    """Fetch S&P 500 tickers + company names from Wikipedia."""
    try:
        html = requests.get(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies",
            headers=HEADERS, timeout=15
        ).text
        tables = pd.read_html(io.StringIO(html), header=0)
        df = tables[0]
        tickers = df["Symbol"].str.replace(".", "-", regex=False).tolist()
        # Grab company names from the Security column
        name_col = next((c for c in df.columns if "security" in c.lower() or "company" in c.lower()), None)
        names = {}
        if name_col:
            for _, row in df.iterrows():
                t = str(row["Symbol"]).replace(".", "-")
                names[t] = str(row[name_col])
        print(f"  S&P 500: {len(tickers)} tickers")
        return tickers, names
    except Exception as e:
        print(f"  Warning: S&P 500 Wikipedia failed ({e}). Using fallback.")
        return SP500_FALLBACK, {}

def get_nasdaq100():
    """Fetch NASDAQ 100 tickers + company names from Wikipedia."""
    try:
        html = requests.get(
            "https://en.wikipedia.org/wiki/Nasdaq-100",
            headers=HEADERS, timeout=15
        ).text
        tables = pd.read_html(io.StringIO(html), header=0)
        names = {}
        for t in tables:
            if "Ticker" in t.columns:
                tickers = t["Ticker"].str.replace(".", "-", regex=False).tolist()
                # Try to get company name column
                name_col = next((c for c in t.columns if "company" in c.lower() or "name" in c.lower()), None)
                if name_col:
                    for _, row in t.iterrows():
                        tick = str(row["Ticker"]).replace(".", "-")
                        names[tick] = str(row[name_col])
                print(f"  NASDAQ 100: {len(tickers)} tickers")
                return tickers, names
        raise ValueError("Ticker column not found")
    except Exception as e:
        print(f"  Warning: NASDAQ 100 Wikipedia failed ({e}). Using fallback.")
        return NASDAQ100_FALLBACK, {}

# Dow 30 — stable enough to hardcode
DOW30 = [
    "AAPL","AMGN","AXP","BA","CAT","CRM","CSCO","CVX","DIS","DOW",
    "GS","HD","HON","IBM","INTC","JNJ","JPM","KO","MCD","MMM",
    "MRK","MSFT","NKE","PG","SHW","TRV","UNH","V","VZ","WMT"
]

DOW30_NAMES = {
    "AAPL":"Apple Inc.","AMGN":"Amgen Inc.","AXP":"American Express Co.",
    "BA":"Boeing Co.","CAT":"Caterpillar Inc.","CRM":"Salesforce Inc.",
    "CSCO":"Cisco Systems Inc.","CVX":"Chevron Corp.","DIS":"The Walt Disney Co.",
    "DOW":"Dow Inc.","GS":"Goldman Sachs Group","HD":"The Home Depot Inc.",
    "HON":"Honeywell International","IBM":"IBM Corp.","INTC":"Intel Corp.",
    "JNJ":"Johnson & Johnson","JPM":"JPMorgan Chase & Co.","KO":"The Coca-Cola Co.",
    "MCD":"McDonald's Corp.","MMM":"3M Co.","MRK":"Merck & Co.",
    "MSFT":"Microsoft Corp.","NKE":"Nike Inc.","PG":"Procter & Gamble Co.",
    "SHW":"Sherwin-Williams Co.","TRV":"The Travelers Cos.","UNH":"UnitedHealth Group",
    "V":"Visa Inc.","VZ":"Verizon Communications","WMT":"Walmart Inc."
}

SP500_FALLBACK = [
    "AAPL","MSFT","AMZN","NVDA","GOOGL","META","BRK-B","LLY","AVGO","JPM",
    "UNH","XOM","V","TSLA","MA","PG","JNJ","COST","HD","MRK","ABBV","CVX",
    "BAC","KO","PEP","ADBE","WMT","AMD","CRM","MCD","ACN","LIN","TMO","CSCO",
    "ABT","PFE","DHR","TXN","NFLX","AMGN","PM","NEE","RTX","INTC","BMY",
    "UPS","QCOM","HON","IBM","INTU","AMAT","CAT","DE","BA","GS","BLK","AXP",
]

NASDAQ100_FALLBACK = [
    "AAPL","MSFT","AMZN","NVDA","META","GOOGL","GOOG","TSLA","AVGO","ADBE",
    "COST","CSCO","AMD","NFLX","INTC","QCOM","TXN","AMGN","INTU","CMCSA",
    "PEP","TMUS","HON","AMAT","SBUX","MDLZ","ISRG","REGN","VRTX","ADP",
]

# ─── FACTOR DATA ─────────────────────────────────────────────────────────────

def _download_french_zip(url):
    r = requests.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    z = zipfile.ZipFile(io.BytesIO(r.content))
    csv_name = [n for n in z.namelist() if n.upper().endswith('.CSV')][0]
    return z.open(csv_name).read().decode('utf-8', errors='ignore')

def _parse_french_csv(text):
    lines = text.splitlines()
    sep = ','
    for line in lines:
        stripped = line.strip()
        if stripped and stripped[:8].isdigit():
            sep = ',' if ',' in stripped else None
            break
    data_start = None
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped and stripped[:8].isdigit():
            data_start = i
            break
    if data_start is None:
        raise ValueError("Could not find data rows in French CSV")
    header_line = None
    for i in range(data_start - 1, -1, -1):
        stripped = lines[i].strip()
        if stripped:
            header_line = stripped
            break
    if header_line is None:
        raise ValueError("Could not find header row in French CSV")
    col_names = [c.strip() for c in header_line.split(',')] if sep == ',' else header_line.split()
    col_names = [c for c in col_names if c]
    rows = []
    for line in lines[data_start:]:
        stripped = line.strip()
        if not stripped:
            continue
        parts = [p.strip() for p in stripped.split(',')] if sep == ',' else stripped.split()
        if not parts[0].isdigit() or len(parts[0]) != 8:
            break
        rows.append(parts)
    if not rows:
        raise ValueError("No data rows found in French CSV")
    n_cols = min(len(col_names), len(rows[0]) - 1)
    extra = ['_extra'] * (len(rows[0]) - 1 - n_cols)
    df = pd.DataFrame(rows, columns=['Date'] + col_names[:n_cols] + extra)
    df = df[['Date'] + col_names[:n_cols]]
    df['Date'] = pd.to_datetime(df['Date'].str.strip(), format='%Y%m%d')
    df = df.set_index('Date')
    df = df.apply(pd.to_numeric, errors='coerce').dropna()
    return df

def get_french_factors(start_date, end_date):
    print("  Downloading Fama-French factor data...")
    BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
    ff3_text = _download_french_zip(BASE + "F-F_Research_Data_Factors_daily_CSV.zip")
    mom_text = _download_french_zip(BASE + "F-F_Momentum_Factor_daily_CSV.zip")
    ff3 = _parse_french_csv(ff3_text)
    mom = _parse_french_csv(mom_text)
    ff3.columns = [c.strip() for c in ff3.columns]
    mom.columns = [c.strip() for c in mom.columns]
    mom_col = [c for c in mom.columns if 'mom' in c.lower()][0]
    mom = mom.rename(columns={mom_col: 'MOM'})
    factors = ff3.join(mom[['MOM']], how='inner')
    factors = factors / 100.0
    factors = factors[(factors.index >= pd.Timestamp(start_date)) &
                      (factors.index <= pd.Timestamp(end_date))]
    print(f"  Factor data: {len(factors)} trading days "
          f"({factors.index[0].date()} to {factors.index[-1].date()})")
    return factors

# ─── PRICE DATA ──────────────────────────────────────────────────────────────

def get_prices_batch(tickers, start_date, end_date):
    try:
        raw = yf.download(
            tickers, start=start_date, end=end_date,
            auto_adjust=True, progress=False, threads=True
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

def run_regression(excess_returns, factors, factor_means, min_obs):
    """
    OLS regression with HC3 robust errors.
    Returns alpha, loadings, p-values, R², plus factor decomposition for display.
    """
    X = factors[["Mkt-RF", "SMB", "HML", "MOM"]].copy()
    X = sm.add_constant(X)
    y = excess_returns

    aligned = pd.concat([y, X], axis=1).dropna()
    if len(aligned) < min_obs:
        return None

    y_clean = aligned.iloc[:, 0]
    X_clean = aligned.iloc[:, 1:]

    try:
        model = sm.OLS(y_clean, X_clean).fit(cov_type="HC3")
        alpha_daily  = model.params["const"]
        alpha_annual = alpha_daily * TRADING_DAYS_PER_YEAR * 100
        pval_alpha   = model.pvalues["const"]

        # Sanity cap — exclude garbage-data stocks
        if abs(alpha_annual) > ALPHA_CAP:
            return None

        beta = float(model.params["Mkt-RF"])
        smb  = float(model.params["SMB"])
        hml  = float(model.params["HML"])
        mom  = float(model.params["MOM"])

        # Factor decomposition (annualised %)
        # Each factor's contribution = loading × mean_factor_return × 252 × 100
        mkt_contrib = beta * factor_means["Mkt-RF"] * TRADING_DAYS_PER_YEAR * 100
        smb_contrib = smb  * factor_means["SMB"]    * TRADING_DAYS_PER_YEAR * 100
        hml_contrib = hml  * factor_means["HML"]    * TRADING_DAYS_PER_YEAR * 100
        mom_contrib = mom  * factor_means["MOM"]    * TRADING_DAYS_PER_YEAR * 100
        rf_annual   = factor_means["RF"]            * TRADING_DAYS_PER_YEAR * 100

        # Actual annualised stock return (excess + RF)
        stock_excess_annual  = float(y_clean.mean()) * TRADING_DAYS_PER_YEAR * 100
        stock_return_annual  = stock_excess_annual + rf_annual

        # Model predicted = RF + factor contributions + alpha
        predicted_excess_annual = mkt_contrib + smb_contrib + hml_contrib + mom_contrib + alpha_annual
        predicted_return_annual = rf_annual + predicted_excess_annual

        return {
            "alpha_daily":        round(alpha_daily, 6),
            "alpha":              round(alpha_annual, 2),
            "pval":               round(float(pval_alpha), 4),
            "tstat":              round(float(model.tvalues["const"]), 3),
            "beta":               round(beta, 3),
            "smb":                round(smb, 3),
            "hml":                round(hml, 3),
            "mom":                round(mom, 3),
            "r_squared":          round(float(model.rsquared), 3),
            "n_obs":              len(aligned),
            # Decomposition fields
            "stock_return":       round(stock_return_annual, 2),
            "rf_annual":          round(rf_annual, 2),
            "mkt_contrib":        round(mkt_contrib, 2),
            "smb_contrib":        round(smb_contrib, 2),
            "hml_contrib":        round(hml_contrib, 2),
            "mom_contrib":        round(mom_contrib, 2),
            "predicted_return":   round(predicted_return_annual, 2),
        }
    except Exception:
        return None

# ─── SIGNAL + INSIGHT ────────────────────────────────────────────────────────

def classify_signal(alpha, pval):
    if alpha > 0 and pval < P_VALUE_GREEN:
        return "green"
    elif alpha > 0 and pval < P_VALUE_AMBER:
        return "amber"
    else:
        return "red"

def dominant_factor(beta, smb, hml, mom):
    factors = {"market": abs(beta - 1), "size (SMB)": abs(smb),
               "value (HML)": abs(hml), "momentum": abs(mom)}
    return max(factors, key=factors.get)

def generate_insight(ticker, alpha, pval, beta, smb, hml, mom, signal, r_squared):
    alpha_str = f"+{alpha:.1f}%" if alpha >= 0 else f"{alpha:.1f}%"
    dom = dominant_factor(beta, smb, hml, mom)
    r2_pct = round(r_squared * 100)
    if signal == "green":
        if mom > 0.6:
            return (f"Strong momentum-driven alpha. The four factors explain {r2_pct}% of returns, "
                    f"but {alpha_str}/yr remains unexplained — genuine outperformance. "
                    f"Momentum is the dominant exposure ({mom:+.2f}). Significant at p={pval:.3f}.")
        elif beta < 0.8:
            return (f"Defensive alpha — low market beta ({beta:.2f}) yet generating {alpha_str}/yr "
                    f"above factor predictions. Rare combination of downside protection and genuine "
                    f"outperformance. Strong signal (p={pval:.3f}).")
        elif smb < -0.3 and hml < -0.2:
            return (f"Large-cap growth alpha of {alpha_str}/yr above what size and value factors predict. "
                    f"Quality business characteristics driving factor-adjusted outperformance. "
                    f"High confidence (p={pval:.3f}).")
        else:
            return (f"Genuine factor-adjusted outperformance of {alpha_str}/yr. "
                    f"Dominant factor: {dom}. Model explains {r2_pct}% of returns — "
                    f"the residual alpha is statistically significant (p={pval:.3f}).")
    elif signal == "amber":
        return (f"Positive alpha of {alpha_str}/yr but below our 95% significance hurdle (p={pval:.3f}). "
                f"May be a real signal — monitor over the next 1–2 quarters. "
                f"Dominant factor: {dom}. Not strong enough to act on alone.")
    else:
        if pval < P_VALUE_GREEN:
            return (f"Significantly negative alpha ({alpha_str}/yr, p={pval:.3f}). "
                    f"Underperforming its factor benchmarks with high statistical confidence. "
                    f"Negative {dom} drag is prominent. Avoid for a factor-based strategy.")
        else:
            return (f"Negative alpha ({alpha_str}/yr) — returns below what the factors predict. "
                    f"Not statistically definitive (p={pval:.3f}), but the direction is clearly negative.")

# ─── MAIN ────────────────────────────────────────────────────────────────────

def main(single_years=None):
    """
    If single_years is set, only run that lookback (legacy --years mode).
    Otherwise run all three: 1, 2, 3 years.
    """
    years_to_run = [single_years] if single_years else [1, 2, 3]
    max_years = max(years_to_run)

    print(f"\n{'='*60}")
    print(f"  Fintiq Factor Screener — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Lookbacks: {years_to_run}")
    print(f"{'='*60}\n")

    end_date   = datetime.today()
    start_date = end_date - timedelta(days=int(max_years * 365.25) + 60)

    # ── 1. Build universe ──────────────────────────────────────────────────
    print("Step 1: Building US equity universe...")
    sp500_tickers, sp500_names  = get_sp500()
    nq100_tickers, nq100_names  = get_nasdaq100()

    sp_set = set(sp500_tickers)
    nq_set = set(nq100_tickers)
    dj_set = set(DOW30)

    all_tickers = list(sp_set | nq_set | dj_set)
    print(f"  Universe: {len(all_tickers)} unique tickers\n")

    # Build name map — priority: S&P 500 Wikipedia > NASDAQ 100 Wikipedia > Dow 30 > ticker
    names = {t: t for t in all_tickers}
    names.update(DOW30_NAMES)
    names.update(nq100_names)
    names.update(sp500_names)  # S&P 500 wins (most reliable)

    # Index membership map
    index_map = {}
    for t in all_tickers:
        idxs = []
        if t in sp_set: idxs.append("sp")
        if t in nq_set: idxs.append("nq")
        if t in dj_set: idxs.append("dj")
        index_map[t] = idxs

    # ── 2. Factor data (download once, slice per lookback) ─────────────────
    print("Step 2: Downloading factor data...")
    factors_all = get_french_factors(start_date, end_date)
    print()

    # ── 3. Price data (download once) ─────────────────────────────────────
    print(f"Step 3: Downloading price data in batches of {BATCH_SIZE}...")
    all_prices = pd.DataFrame()
    batches = [all_tickers[i:i+BATCH_SIZE] for i in range(0, len(all_tickers), BATCH_SIZE)]
    for i, batch in enumerate(batches):
        print(f"  Batch {i+1}/{len(batches)} ({len(batch)} tickers)...")
        prices = get_prices_batch(
            batch,
            start_date.strftime("%Y-%m-%d"),
            end_date.strftime("%Y-%m-%d")
        )
        if not prices.empty:
            all_prices = prices if all_prices.empty else all_prices.join(prices, how="outer")
        time.sleep(1)
    print(f"  Total: {all_prices.shape[1]} tickers × {all_prices.shape[0]} days\n")

    # ── 4. Run for each lookback ───────────────────────────────────────────
    for years in years_to_run:
        run_lookback(
            years, end_date, all_tickers, all_prices,
            factors_all, names, index_map
        )

    print(f"\nAll done.\n")


def run_lookback(years, end_date, all_tickers, all_prices, factors_all, names, index_map):
    """Run regressions and write JSON for a single lookback period."""
    print(f"\n{'─'*60}")
    print(f"  Running {years}-year lookback...")
    print(f"{'─'*60}")

    start_date = end_date - timedelta(days=int(years * 365.25) + 10)
    expected_days = int(years * TRADING_DAYS_PER_YEAR)
    min_obs = int(expected_days * MIN_COVERAGE_RATIO)

    # Slice factors to this lookback window
    factors = factors_all[
        (factors_all.index >= pd.Timestamp(start_date)) &
        (factors_all.index <= pd.Timestamp(end_date))
    ].copy()

    # Pre-compute factor means for decomposition
    factor_means = {
        "Mkt-RF": float(factors["Mkt-RF"].mean()),
        "SMB":    float(factors["SMB"].mean()),
        "HML":    float(factors["HML"].mean()),
        "MOM":    float(factors["MOM"].mean()),
        "RF":     float(factors["RF"].mean()),
    }

    # Slice prices
    prices = all_prices[
        (all_prices.index >= pd.Timestamp(start_date)) &
        (all_prices.index <= pd.Timestamp(end_date))
    ].copy()

    factor_aligned = factors[["Mkt-RF", "SMB", "HML", "MOM", "RF"]].copy()

    results = []
    skipped = 0

    print(f"  Running OLS regressions (min {min_obs} obs = {MIN_COVERAGE_RATIO*100:.0f}% of {expected_days} expected days)...")

    for i, ticker in enumerate(all_tickers):
        if i % 100 == 0:
            print(f"  Progress: {i}/{len(all_tickers)} ({len(results)} ok, {skipped} skipped)")

        if ticker not in prices.columns:
            skipped += 1
            continue

        price_series = prices[ticker].dropna()
        if len(price_series) < min_obs:
            skipped += 1
            continue

        daily_returns = price_series.pct_change().dropna()
        daily_returns.name = "RET"

        rf_series   = factor_aligned["RF"].copy()
        factor_cols = factor_aligned[["Mkt-RF", "SMB", "HML", "MOM"]].copy()

        combined = pd.concat([daily_returns, rf_series, factor_cols], axis=1, join="inner").dropna()
        if len(combined) < min_obs:
            skipped += 1
            continue

        stock_np  = combined["RET"].to_numpy(dtype=float)
        rf_np     = combined["RF"].to_numpy(dtype=float)
        excess_returns = pd.Series(stock_np - rf_np, index=combined.index, dtype=float)
        reg_factors    = combined[["Mkt-RF", "SMB", "HML", "MOM"]].copy()

        reg = run_regression(excess_returns, reg_factors, factor_means, min_obs)
        if reg is None:
            skipped += 1
            continue

        signal  = classify_signal(reg["alpha"], reg["pval"])
        insight = generate_insight(
            ticker, reg["alpha"], reg["pval"],
            reg["beta"], reg["smb"], reg["hml"], reg["mom"],
            signal, reg["r_squared"]
        )

        results.append({
            "ticker":           ticker,
            "name":             names.get(ticker, ticker),
            "alpha":            reg["alpha"],
            "pval":             reg["pval"],
            "tstat":            reg["tstat"],
            "beta":             reg["beta"],
            "smb":              reg["smb"],
            "hml":              reg["hml"],
            "mom":              reg["mom"],
            "r_squared":        reg["r_squared"],
            "n_obs":            reg["n_obs"],
            "signal":           signal,
            "idx":              index_map.get(ticker, []),
            "insight":          insight,
            # Decomposition
            "stock_return":     reg["stock_return"],
            "rf_annual":        reg["rf_annual"],
            "mkt_contrib":      reg["mkt_contrib"],
            "smb_contrib":      reg["smb_contrib"],
            "hml_contrib":      reg["hml_contrib"],
            "mom_contrib":      reg["mom_contrib"],
            "predicted_return": reg["predicted_return"],
        })

    print(f"\n  Completed: {len(results)} stocks, {skipped} skipped")

    # Sort and rank
    results.sort(key=lambda x: x["alpha"], reverse=True)
    for i, r in enumerate(results):
        r["rank"] = i + 1

    # Meta
    green_count  = sum(1 for r in results if r["signal"] == "green")
    amber_count  = sum(1 for r in results if r["signal"] == "amber")
    red_count    = sum(1 for r in results if r["signal"] == "red")
    alphas       = [r["alpha"] for r in results]
    median_alpha = round(float(np.median(alphas)), 2) if alphas else 0.0

    meta = {
        "generated_at":    datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generated_date":  datetime.utcnow().strftime("%d %b %Y"),
        "lookback_years":  years,
        "lookback_days":   expected_days,
        "universe":        "US Equities (S&P 500 + NASDAQ 100 + Dow 30)",
        "universe_count":  len(results),
        "green_count":     green_count,
        "amber_count":     amber_count,
        "red_count":       red_count,
        "median_alpha":    median_alpha,
        "factor_model":    "Fama-French 4-Factor (Mkt · SMB · HML · MOM)",
        "data_source":     "Kenneth French Data Library + Yahoo Finance",
        "alpha_hurdle":    "p < 0.05 (95% confidence) for green; p < 0.15 for amber",
        "min_coverage":    f"{MIN_COVERAGE_RATIO*100:.0f}%",
    }

    # Write files
    suffix = f"-{years}y"
    data_path = os.path.join(OUTPUT_DIR, f"screener-data{suffix}.json")
    meta_path = os.path.join(OUTPUT_DIR, f"screener-meta{suffix}.json")

    with open(data_path, "w", encoding="utf-8") as f:
        json.dump({"stocks": results}, f, ensure_ascii=False, separators=(",", ":"))
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    print(f"  → {data_path.split(os.sep)[-1]} ({os.path.getsize(data_path)//1024} KB, {len(results)} stocks)")
    print(f"  → {meta_path.split(os.sep)[-1]}")

    # 2-year is the default — also write unversioned files for backward compat
    if years == 2:
        shutil.copy(data_path, os.path.join(OUTPUT_DIR, "screener-data.json"))
        shutil.copy(meta_path, os.path.join(OUTPUT_DIR, "screener-meta.json"))
        print(f"  → screener-data.json (copy of 2y, backward compat)")

    # Top 10 summary
    print(f"\n  Top 10 by alpha ({years}yr):")
    for r in results[:10]:
        icon = "🟢" if r["signal"] == "green" else ("🟡" if r["signal"] == "amber" else "🔴")
        print(f"    {icon} {r['ticker']:<8} {'+' if r['alpha']>=0 else ''}{r['alpha']:.1f}%/yr  p={r['pval']:.3f}  {r['name'][:30]}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fintiq Factor Screener")
    parser.add_argument("--years", type=float, default=None,
                        help="Single lookback in years. Omit to run all three (1, 2, 3).")
    args = parser.parse_args()
    main(single_years=args.years)
