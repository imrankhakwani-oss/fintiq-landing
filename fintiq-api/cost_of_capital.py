"""
Cost of capital (WACC) and return on invested capital (ROIC) for Alpha Scanner.

Method (agreed 27 Nov 2026), every input from a named public source:
  risk-free rate     = US 10-year Treasury yield (Yahoo ^TNX, cached daily)
  equity risk premium = Damodaran's implied ERP for the S&P 500 (NYU Stern), updated monthly
  beta               = Damodaran industry unlevered beta (Jan 2026, cash-corrected),
                       re-levered for the company's own debt: bL = bu * (1 + (1 - t) * D/E)
  cost of equity     = risk-free + beta * ERP                                (CAPM)
  cost of debt       = risk-free + default spread from a "synthetic rating" based on
                       interest cover (operating profit / interest), Damodaran small-firm
                       table with January 2026 spreads
  tax rate           = 25% when operating profit is positive, 0% for loss-makers
  weights            = market value of equity, book value of debt
  WACC               = clamped to 8%-20% so one odd figure cannot produce a silly number
  ROIC               = operating profit after tax / invested capital,
                       invested capital = equity + debt - cash (average of start and end)
"""
from __future__ import annotations

import os
import re
import time

TAX_RATE = 0.25
WACC_FLOOR, WACC_CAP = 0.08, 0.20
BETA_CAP = 4.0

# Damodaran, "Betas by Sector (US)", January 2026: unlevered beta corrected for cash.
INDUSTRY_BETA = {
    "Advertising": 1.01, "Aerospace/Defense": 0.87, "Air Transport": 0.76, "Apparel": 0.79,
    "Auto & Truck": 1.31, "Auto Parts": 1.13, "Beverage (Alcoholic)": 0.63, "Beverage (Soft)": 0.58,
    "Broadcasting": 0.32, "Building Materials": 0.96, "Business & Consumer Services": 0.81,
    "Cable TV": 0.36, "Chemical (Basic)": 0.64, "Chemical (Specialty)": 0.82,
    "Coal & Related Energy": 1.18, "Computer Services": 0.96, "Computers/Peripherals": 1.32,
    "Construction Supplies": 1.05, "Diversified": 0.84, "Drugs (Biotechnology)": 1.08,
    "Drugs (Pharmaceutical)": 0.92, "Education": 0.72, "Electrical Equipment": 1.19,
    "Electronics (Consumer & Office)": 0.93, "Electronics (General)": 0.94,
    "Engineering/Construction": 1.14, "Entertainment": 0.76, "Environmental & Waste Services": 0.82,
    "Farming/Agriculture": 0.85, "Food Processing": 0.47, "Food Wholesalers": 0.65,
    "Furn/Home Furnishings": 0.65, "Green & Renewable Energy": 0.47, "Healthcare Products": 0.86,
    "Healthcare Support Services": 0.74, "Healthcare Information and Technology": 1.02,
    "Homebuilding": 0.85, "Hospitals/Healthcare Facilities": 0.56, "Hotel/Gaming": 0.88,
    "Household Products": 0.74, "Information Services": 0.76, "Machinery": 0.89,
    "Metals & Mining": 1.01, "Office Equipment & Services": 1.04, "Oil/Gas (Integrated)": 0.28,
    "Oil/Gas (Production and Exploration)": 0.58, "Oil/Gas Distribution": 0.47,
    "Oilfield Svcs/Equip.": 0.79, "Packaging & Container": 0.75, "Paper/Forest Products": 0.77,
    "Power": 0.31, "Precious Metals": 0.83, "Publishing & Newspapers": 0.51, "Recreation": 0.74,
    "Restaurant/Dining": 0.78, "Retail (Automotive)": 0.71, "Retail (Building Supply)": 1.32,
    "Retail (Distributors)": 0.80, "Retail (General)": 0.78, "Retail (Grocery and Food)": 0.85,
    "Retail (Special Lines)": 1.00, "Rubber& Tires": 0.15, "Semiconductor": 1.50,
    "Semiconductor Equip": 1.39, "Shipbuilding & Marine": 0.66, "Shoe": 1.00,
    "Software (Entertainment)": 1.02, "Software (Internet)": 1.59,
    "Software (System & Application)": 1.25, "Steel": 0.94, "Telecom (Wireless)": 0.39,
    "Telecom. Equipment": 0.89, "Telecom. Services": 0.38, "Tobacco": 0.69, "Transportation": 0.71,
    "Transportation (Railroads)": 0.81, "Trucking": 0.87, "Utility (General)": 0.15,
    "Utility (Water)": 0.28, "Total Market (without financials)": 0.90,
}

# SEC industry code (SIC) ranges -> Damodaran industry. First match wins, so narrow ranges come first.
_SIC_MAP = [
    (1040, 1049, "Precious Metals"), (1000, 1099, "Metals & Mining"), (1200, 1299, "Coal & Related Energy"),
    (1311, 1311, "Oil/Gas (Production and Exploration)"), (1381, 1389, "Oilfield Svcs/Equip."),
    (1300, 1399, "Oil/Gas (Production and Exploration)"), (1400, 1499, "Building Materials"),
    (1520, 1531, "Homebuilding"), (1500, 1799, "Engineering/Construction"),
    (2080, 2085, "Beverage (Alcoholic)"), (2086, 2087, "Beverage (Soft)"), (2000, 2099, "Food Processing"),
    (2100, 2199, "Tobacco"), (2200, 2399, "Apparel"), (2400, 2499, "Paper/Forest Products"),
    (2500, 2599, "Furn/Home Furnishings"), (2650, 2679, "Packaging & Container"),
    (2600, 2699, "Paper/Forest Products"), (2700, 2799, "Publishing & Newspapers"),
    (2800, 2829, "Chemical (Basic)"), (2836, 2836, "Drugs (Biotechnology)"),
    (2830, 2839, "Drugs (Pharmaceutical)"), (2840, 2849, "Household Products"),
    (2850, 2899, "Chemical (Specialty)"), (2900, 2999, "Oil/Gas (Integrated)"),
    (3011, 3011, "Rubber& Tires"), (3000, 3099, "Chemical (Specialty)"), (3100, 3199, "Shoe"),
    (3200, 3299, "Building Materials"), (3310, 3329, "Steel"), (3300, 3399, "Metals & Mining"),
    (3400, 3499, "Machinery"), (3570, 3579, "Computers/Peripherals"), (3500, 3599, "Machinery"),
    (3630, 3639, "Electronics (Consumer & Office)"), (3651, 3652, "Electronics (Consumer & Office)"),
    (3660, 3669, "Telecom. Equipment"), (3674, 3674, "Semiconductor"),
    (3670, 3679, "Electronics (General)"), (3600, 3699, "Electrical Equipment"),
    (3714, 3714, "Auto Parts"), (3710, 3719, "Auto & Truck"), (3720, 3729, "Aerospace/Defense"),
    (3730, 3732, "Shipbuilding & Marine"), (3760, 3769, "Aerospace/Defense"),
    (3790, 3799, "Recreation"), (3700, 3799, "Transportation"),
    (3825, 3825, "Semiconductor Equip"), (3812, 3812, "Aerospace/Defense"),
    (3840, 3851, "Healthcare Products"), (3800, 3899, "Electronics (General)"),
    (3940, 3949, "Recreation"), (3900, 3999, "Diversified"),
    (4011, 4013, "Transportation (Railroads)"), (4100, 4299, "Trucking"),
    (4400, 4499, "Shipbuilding & Marine"), (4500, 4599, "Air Transport"),
    (4600, 4699, "Oil/Gas Distribution"), (4700, 4799, "Transportation"),
    (4812, 4812, "Telecom (Wireless)"), (4830, 4839, "Broadcasting"), (4840, 4849, "Cable TV"),
    (4800, 4899, "Telecom. Services"), (4920, 4925, "Oil/Gas Distribution"),
    (4940, 4941, "Utility (Water)"), (4950, 4959, "Environmental & Waste Services"),
    (4900, 4999, "Power"), (5140, 5149, "Food Wholesalers"), (5000, 5199, "Retail (Distributors)"),
    (5200, 5299, "Retail (Building Supply)"), (5300, 5399, "Retail (General)"),
    (5400, 5499, "Retail (Grocery and Food)"), (5500, 5599, "Retail (Automotive)"),
    (5800, 5899, "Restaurant/Dining"), (5600, 5999, "Retail (Special Lines)"),
    (7000, 7099, "Hotel/Gaming"), (7310, 7319, "Advertising"),
    (7370, 7370, "Software (Internet)"), (7372, 7372, "Software (System & Application)"),
    (7371, 7379, "Computer Services"), (7510, 7519, "Transportation"),
    (7800, 7899, "Entertainment"), (7990, 7999, "Hotel/Gaming"), (7900, 7999, "Recreation"),
    (8060, 8069, "Hospitals/Healthcare Facilities"), (8000, 8099, "Healthcare Support Services"),
    (8200, 8299, "Education"), (8711, 8711, "Engineering/Construction"),
    (7000, 8999, "Business & Consumer Services"),
]

def industry_for_sic(sic: int | None) -> str:
    if sic:
        for lo, hi, name in _SIC_MAP:
            if lo <= sic <= hi:
                return name
    return "Total Market (without financials)"

# Damodaran small-firm (<$5bn) interest-cover thresholds, with his January 2026 default spreads.
_RATINGS = [  # (cover above, rating, spread)
    (12.5, "AAA", 0.0040), (9.5, "AA", 0.0055), (7.5, "A+", 0.0070), (6.0, "A", 0.0078),
    (4.5, "A-", 0.0089), (4.0, "BBB", 0.0111), (3.5, "BB+", 0.0138), (3.0, "BB", 0.0184),
    (2.5, "B+", 0.0275), (2.0, "B", 0.0321), (1.5, "B-", 0.0509), (1.25, "CCC", 0.0885),
    (0.8, "CC", 0.1261), (0.5, "C", 0.1600), (float("-inf"), "D", 0.1900),
]

def synthetic_rating(operating_profit: float | None, interest: float | None) -> tuple[str, float, float | None]:
    """(rating, spread, interest cover). No meaningful interest -> AAA."""
    if not interest or interest <= 0:
        return "AAA", _RATINGS[0][2], None
    cover = (operating_profit or 0) / interest
    for above, rating, spread in _RATINGS:
        if cover > above:
            return rating, spread, cover
    return "D", 0.19, cover

_cache: dict = {}

def risk_free() -> float:
    """US 10-year Treasury yield, cached for a day. Env AS2_RISK_FREE overrides (e.g. 0.05)."""
    if os.environ.get("AS2_RISK_FREE"):
        return float(os.environ["AS2_RISK_FREE"])
    c = _cache.get("rf")
    if c and time.time() - c[1] < 86400:
        return c[0]
    rf = 0.05
    try:
        import yfinance as yf
        h = yf.Ticker("^TNX").history(period="10d")
        if not h.empty:
            v = float(h["Close"].dropna().iloc[-1])
            if 0.5 < v < 15:
                rf = v / 100
    except Exception:
        pass
    _cache["rf"] = (rf, time.time())
    return rf

def equity_risk_premium() -> float:
    """Damodaran's implied ERP, read from his home page weekly. Env AS2_ERP overrides.
    Fallback 4.20% (his figure for 1 October 2026)."""
    if os.environ.get("AS2_ERP"):
        return float(os.environ["AS2_ERP"])
    c = _cache.get("erp")
    if c and time.time() - c[1] < 7 * 86400:
        return c[0]
    erp = 0.042
    try:
        import requests
        t = requests.get("https://pages.stern.nyu.edu/~adamodar/New_Home_Page/home.htm", timeout=15).text
        m = re.search(r"Implied ERP on [^=]{3,40}=\s*([0-9.]+)%", t)
        if m and 2 < float(m.group(1)) < 10:
            erp = float(m.group(1)) / 100
    except Exception:
        pass
    _cache["erp"] = (erp, time.time())
    return erp

def wacc(sic: int | None, market_cap: float | None, total_debt: float | None,
         operating_profit: float | None, interest: float | None) -> dict | None:
    if not market_cap or market_cap <= 0:
        return None
    rf, erp = risk_free(), equity_risk_premium()
    ind = industry_for_sic(sic)
    bu = INDUSTRY_BETA.get(ind, 0.90)
    d = max(total_debt or 0.0, 0.0)
    t = TAX_RATE if (operating_profit or 0) > 0 else 0.0
    beta = min(bu * (1 + (1 - t) * d / market_cap), BETA_CAP)
    ke = rf + beta * erp
    rating, spread, cover = synthetic_rating(operating_profit, interest)
    kd = rf + spread
    we = market_cap / (market_cap + d)
    raw = we * ke + (1 - we) * kd * (1 - t)
    w = min(max(raw, WACC_FLOOR), WACC_CAP)
    return {"wacc": round(w, 4), "wacc_raw": round(raw, 4), "risk_free": round(rf, 4), "erp": round(erp, 4),
            "industry": ind, "beta_unlevered": bu, "beta": round(beta, 2), "cost_of_equity": round(ke, 4),
            "rating": rating, "interest_cover": None if cover is None else round(cover, 2),
            "cost_of_debt": round(kd, 4), "tax_rate": t, "debt_weight": round(1 - we, 3)}

def invested_capital(r: dict) -> float | None:
    """Equity + all borrowings - cash."""
    if r.get("bv") is None:
        return None
    debt = r.get("ltd") if r.get("ltd") is not None else (r.get("ltdn") or 0) + (r.get("ltdc") or 0)
    if not debt and r.get("debt"):
        debt = r["debt"]
    return r["bv"] + (debt or 0) + (r.get("std") or 0) - (r.get("cash") or 0)

def total_debt(r: dict) -> float:
    debt = r.get("ltd") if r.get("ltd") is not None else (r.get("ltdn") or 0) + (r.get("ltdc") or 0)
    if not debt and r.get("debt"):
        debt = r["debt"]
    return (debt or 0) + (r.get("std") or 0)

def roic(cur: dict, prev: dict | None) -> float | None:
    oi = cur.get("oi")
    ic = invested_capital(cur)
    if oi is None or ic is None:
        return None
    nopat = oi * (1 - TAX_RATE) if oi > 0 else oi
    ic_prev = invested_capital(prev) if prev else None
    cap = (ic + ic_prev) / 2 if (ic_prev and ic_prev > 0 and ic > 0) else ic
    return round(nopat / cap, 4) if cap and cap > 0 else None

def stage(roic_now: float | None, roic_prev: float | None, w: float | None) -> tuple[int | None, str]:
    """Value-creation stage (display only; not a rule until tested)."""
    if roic_now is None or w is None:
        return None, "ROIC not meaningful"
    rising = roic_prev is not None and roic_now > roic_prev
    if roic_now < 0:
        return 1, "Stage 1: ROIC negative" + (", improving" if rising else "")
    if roic_now < w:
        return 2, "Stage 2: ROIC positive, below cost of capital" + (", improving" if rising else "")
    return 3, "Stage 3: ROIC above cost of capital"
