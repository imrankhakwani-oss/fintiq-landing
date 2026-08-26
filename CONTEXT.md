# Fintiq Project Context — Last updated 25/08/2026

---

## CRITICAL DEPLOY RULES

**Vercel (fintiq.uk HTML pages):**
```powershell
cd C:\Users\imran\Desktop\Fintiq\Articles
git add .
git commit -m "..."
git push origin HEAD:main   # ← ALWAYS HEAD:main — Production is on main, NOT master
```

**Railway (api.fintiq.uk FastAPI):**
```powershell
cd C:\Users\imran\Desktop\fintiq-api
copy C:\Users\imran\Desktop\Fintiq\Articles\fintiq-api\main.py main.py
git add main.py
git commit -m "..."
git push origin HEAD:main
```

⚠️ RAILWAY DEPLOY NOTE: The working copy is `Articles/fintiq-api/main.py`. The Railway git repo is a SEPARATE directory at `Desktop/fintiq-api/`. The `copy` step is MANDATORY before every Railway deploy — without it, the old code stays live. Never `git add` from inside `Articles/fintiq-api/` — that dir has no `.git`.

**Streamlit app (app.fintiq.uk):**
```powershell
cd C:\Users\imran\Desktop\fintiq-app
Copy-Item "..\Fintiq\fintiq_screener.py" "fintiq_screener.py"
git add fintiq_screener.py
git commit -m "..."
git push
```

---

## 1. PRODUCT VISION

### Core Idea
Fintiq is an **AI-first investment companion** — not a data tool, but a guided analytical journey. The AI acts simultaneously as a pro trader, equity researcher, hedge fund analyst, quantitative analyst, and behavioural finance expert. It educates and challenges the retail investor through a structured process, helping them arrive at their own well-reasoned conclusions.

**The AI never advises. It educates, guides, challenges, and appreciates reasoning.**
Language throughout: "the data suggests…", "historically stocks with this profile…", "one question worth considering…" — never "buy this" or "this will go up."

### The Five-Stage Analytical Journey (Streamlit AI Companion)
1. **Fundamental Screen** — Is this a good business? Quality filters + Fama-French 4-factor model
2. **Valuation** — Is it cheap? DCF, industry-standard methods, valuation matrix, Monte Carlo price range
3. **Technical Analysis** — What does price action say? Entry/exit points, time periods, catalyst signals
4. **Catalyst Identification** — What specific event closes the gap between price and value?
5. **Report** — AI summarises the full journey into a published report (on-screen + downloadable)

### Stock Deep Dive (new HTML page — fintiq.uk/deep-dive.html)
Standalone public page. Enter any ticker → instant institutional-grade analysis.
Five sections:
1. **Fundamentals** ✅ — business overview, historical growth table, TSR, FF4 factor, analyst ratings, AI chat
2. **Valuation** ✅ — DCF (reverse-engineered defaults), Monte Carlo, sensitivity grid, Bear/Base/Bull AI scenarios
3. **Technical** ✅ — 12-month price chart + MA50/MA200/BB/S&R lines, RSI, MACD, options dashboard, AI trade setups (long+short dashboard card)
4. **Risk & Position Sizing** ✅ — Monte Carlo price paths (GBM), stop loss stress tester, position size calculator, volatility comparison, AI summary
5. **Catalyst Tracker** ✅ — earnings banner + surprise history, analyst ratings + changes, short interest/squeeze, news feed, AI catalyst summary (5 sections, ~250 words)
6. **Decision Analysis** — thesis challenge, conviction score, buy/short/hold verdict, PDF report (TODO)

---

## 2. KEY FILE LOCATIONS

| File | Path |
|---|---|
| Streamlit app | `C:\Users\imran\Desktop\Fintiq\fintiq_screener.py` |
| Streamlit deploy repo | `C:\Users\imran\Desktop\fintiq-app` |
| FastAPI main (working copy) | `C:\Users\imran\Desktop\Fintiq\Articles\fintiq-api\main.py` |
| FastAPI deploy repo | `C:\Users\imran\Desktop\fintiq-api` |
| Deep Dive page | `C:\Users\imran\Desktop\Fintiq\Articles\deep-dive.html` |
| Context file (this) | `C:\Users\imran\Desktop\Fintiq\Articles\CONTEXT.md` |

---

## 3. INFRASTRUCTURE

### Sites
- `fintiq.uk` / `www.fintiq.uk` — Vercel, deploys from `main` branch of Articles repo
- `api.fintiq.uk` — Railway project: `captivating-integrity`, service: `fintiq-api`
- `app.fintiq.uk` — Railway (Streamlit)

### Railway Environment Variables (fintiq-api)
- `ANTHROPIC_API_KEY`
- `FMP_KEY` = `c3gRy6dPp8uETaNIYoFJj83J7hm998bB`
- `REFRESH_TOKEN` = `fintiq-refresh-2026`
- `TAVILY_API_KEY`
- `FRED_API_KEY`

### Railway Timeout
Railway has a **30-second hard request timeout**. FastAPI endpoints that need >30s (e.g. yfinance fetches) must use background task + polling pattern.

---

## 4. FASTAPI — api.fintiq.uk (main.py)

### Architecture — Background Task + Polling
Endpoints that are slow (yfinance fetches) use this pattern:
- `GET /fundamentals?ticker=X` — returns `{"status":"processing"}` instantly, starts background thread
- `GET /fundamentals/status?ticker=X` — polls result
- In-memory job cache: `_fund_jobs: dict = {}`, TTL 5 minutes
- Same pattern used for `/technical` → `_tech_jobs: dict = {}`, TTL 5 minutes

### NaN Sanitisation
yfinance returns `NaN` floats. `_clean()` walks result recursively, replaces NaN/Inf with `None`. Applied before storing in job cache.

### GBp → GBP Currency Conversion
LSE stocks: `currency = 'GBp'` (pence). `gbp_scale = 0.01` applied to all monetary values. `display_currency = 'GBP'` sent to frontend.

### Key Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Health check |
| `GET /bulletin` | Daily AI market brief |
| `GET /market-data` | Market indices, macro, FOMC |
| `GET /earnings` | Upcoming earnings for index |
| `GET /fundamentals?ticker=X` | Start or return fundamental data (polling) |
| `GET /fundamentals/status?ticker=X` | Poll for result |
| `POST /fundamentals/chat` | AI chat (section-aware: fundamentals/valuation/technical) |
| `POST /valuation/ai-assumptions` | Bear/Base/Bull scenario generator (Haiku, 1200 tokens) |
| `GET /technical?ticker=X` | Start or return technical data (polling) |
| `GET /technical/status?ticker=X` | Poll for result |
| `POST /technical/ai-commentary` | Long+Short trade setup AI (Haiku, 1400 tokens) |

### /technical endpoint — what it returns
- 126 bars of OHLCV (6 months)
- MA50, MA200, RSI(14), MACD(12,26,9), Bollinger Bands(20,2)
- `trend`: STRONG_UPTREND / UPTREND / NEUTRAL / DOWNTREND / STRONG_DOWNTREND
- `momentum`: OVERBOUGHT / BULLISH / NEUTRAL / BEARISH / OVERSOLD
- `key_levels`: support, resistance (from recent lows/highs)
- `options`: pcr, atm_iv, max_pain, put_wall, call_wall, unusual (list)

### /technical/ai-commentary — output format
Uses `━━` separators. Sections: TREND & MOMENTUM SUMMARY, LONG TRADE SETUP, SHORT TRADE SETUP, VERDICT.
Each trade setup: ENTRY ZONE, CONFIRMATION NEEDED, STOP LOSS, TARGET 1, TARGET 2, OPTIONS SIGNAL, RISK.

### /valuation/ai-assumptions — output format
Three scenario blocks: BEAR CASE, BASE CASE, BULL CASE.
Each block: SHORT-TERM GROWTH (Yrs 1-3), MID-TERM GROWTH (Yrs 4-7), LONG-TERM GROWTH (Yrs 8-10), TERMINAL GROWTH, WACC, OP MARGIN (%), TAX RATE (%), THESIS (2 sentences).
Ends with: KEY SWING FACTOR (1-2 sentences).

### AI Chat — Section-aware System Prompt
`/fundamentals/chat` accepts `section` field. Rules:
- `technical` section: focus on entry/exit timing, support/resistance, options flow, RSI/MACD/put walls/max pain, BOTH long AND short perspectives
- Always answer from training knowledge when data not in context

---

## 5. DEEP DIVE PAGE (deep-dive.html)

### JS Architecture
- `_session` object: `{ticker, fundamentals: {data}, technical: {data}}`
- `openSection(name)` — triggers load: fundamentals / valuation / technical
- Section loaders follow same pattern: fetch → poll → render

### Section 1 — Fundamentals
- `loadFundamentals()` → `_pollFundamentals(attempt)` → `renderFundamentals(d)`
- NOPAT Margin computed client-side: `op_margin × (1 - tax_rate/100)` using `_fundTaxRate` from `valuation_inputs`

### Section 2 — Valuation
- `renderValuation(d)` — reads `valuation_inputs` from fundamentals data
- `_vs` object holds all DCF inputs + Monte Carlo params
- Monte Carlo: 3 variables — revenue growth (σ=3), WACC (σ=1.5), op margin (σ=2)
- Op margin shock applied uniformly across all 3 phases per scenario
- SD sliders rendered above MC histogram (3-col grid)
- Sensitivity brief: finds break-even WACC and terminal growth vs current price
- MC brief: P10/P50/P90 + % of scenarios above price
- Bear/Base/Bull AI scenarios: fetched from `/valuation/ai-assumptions`, parsed via `━━` separator regex
- "Fintiq AI Analyst" label (not "AI Fundamentals Analyst")

### Section 3 — Technical (built 25/08/2026)
- `loadTechnical()` → `_pollTechnical(attempt)` → `renderTechnical(d)`
- Trend banner: colour-coded (green/red/amber) with trend + momentum badges
- Three Chart.js panels (canvas elements, `_techCharts[]` for cleanup):
  1. Price chart: candlestick-style (close line), MA50 (orange), MA200 (purple), Bollinger Bands (dashed), Volume bars on secondary y-axis `yv`
  2. RSI chart: line with custom inline plugin for 30/70 zones (red/green shading) and 50 dashed midline
  3. MACD chart: histogram bars + signal line + MACD line
- Stats grid (4 cards): RSI value, MACD signal, Support, Resistance
- Options dashboard: 6 cards (PCR, ATM IV, Max Pain, Put Wall, Call Wall) + unusual activity table
- AI commentary: fetched from `/technical/ai-commentary`, parsed via `━━` separator, renders LONG (green badge) and SHORT (red badge) trade setups with all fields
- Chat starters specific to technical section

### Currency Symbol (JS)
```javascript
const currSym = ov.currency === 'USD' ? '$' : ov.currency === 'GBP' ? '£' : ov.currency === 'EUR' ? '€' : (ov.currency || '$');
```

---

## 6. HOME TAB BULLETIN (Streamlit)

- `_make_bulletin(_b_key)` — `@st.cache_data(ttl=14400)`, only called when API key present
- **Three-layer cache**: session_state → `/tmp/fintiq_bulletin_{key}.json` → Claude API
- Cache key: `YYYYMMDD + str(hour // 4)` → max 6 Claude calls/day

---

## 7. LOGIN / PAYWALL — TEMPORARILY DISABLED

- `_check_auth_gate()` returns `True` unconditionally
- Supabase, Stripe integrations remain in code but dormant

---

## 8. AI COMPANION (Streamlit — app.fintiq.uk)

### Stage Machine
```
discovery → confirm → fundamental → valuation → technical → finalise → report
```

### Key Session State Keys (all prefixed `cp_`)
- `cp_msgs`, `cp_stage`, `cp_ctx`, `cp_data`, `cp_analyses`, `cp_name_map`, `cp_report`

### Key Features
- Geography awareness (UK → .L tickers)
- Dynamic company name → ticker resolution from AI replies
- FF4 Fama-French integration from pre-computed JSON + on-demand regression
- Save/Resume session (JSON download/upload)
- Analyst Playbook (hedge fund question bank)
- Credit clock ($1 budget, shown as credits)
- Model routing (Haiku for simple, Sonnet for complex)
- Prompt caching + conversation summarisation

---

## 9. PENDING TASKS — START HERE NEXT SESSION

### Deep Dive — Section 6 (next to build)
- [ ] **Section 6 — Decision Analysis**: thesis challenge, conviction score, buy/short/hold verdict, PDF report

### Deep Dive — Known issues / polish
- [ ] Valuation section: reverse DCF solver ceiling raised to 150% — verify Tesla now shows implied growth callout
- [ ] Catalyst section: earnings date now uses future-only logic — verify with AAPL post-July earnings
- [ ] Catalyst AI summary: now 250 words with ▸ headers — verify rendering looks clean

### Other
- [ ] Mobile: My Dashboard 3-col grid → single column (task #23)
- [ ] Apply remaining 9 audit fixes to main.py (task #74)
- [ ] Re-enable login/paywall with new protocol
- [ ] Polygon.io news + earnings data feed ($29/mo) — would improve catalyst data quality

---

## 10. 6-STEP FINTIQ METHOD
1. 🔍 Screen — Fundamental + Factor (AI companion stage 1)
2. 💰 Value — DCF + Monte Carlo (AI companion stage 2)
3. 📈 Time — Technical + Catalyst (AI companion stage 3-4)
4. 📐 Size — MPT Optimiser (standalone tool)
5. 🌍 Brief — Daily AI market intelligence (Bulletin)
6. 🎯 Decide — Conviction watchlist + report (AI companion stage 5)

---

## 11. KNOWN BUGS / HISTORY

| Date | Bug | Fix |
|---|---|---|
| 24/08/2026 | `const currSym` declared twice → fatal JS SyntaxError → blank screen | Removed duplicate |
| 24/08/2026 | Railway 30s timeout killing yfinance fetches for AAPL/TSLA/CAT | Background task + polling pattern |
| 24/08/2026 | `ValueError: Out of range float values not JSON compliant: nan` → CORS error | `_clean()` NaN sanitisation |
| 24/08/2026 | UK stocks (SHELL.L) showing prices/financials in pence | `gbp_scale = 0.01` conversion |
| 24/08/2026 | FF4 commentary was dead code (after `return`) | Moved into background task |
| 24/08/2026 | Revenue rows missing £/$ symbol | `${currSym}${r.revenue}` in growthRow |
| 24/08/2026 | AI chat redirecting to external sources instead of answering | System prompt rewritten |
| 24/08/2026 | Vercel deploying to wrong branch (master vs main) | Always `git push origin HEAD:main` |
| 24/08/2026 | NOPAT Margin showing dashes in growth table | Computed client-side: `op_margin × (1 - tax_rate/100)` |
| 25/08/2026 | Railway deploy not picking up new code | Working copy is in Articles/; Railway repo is separate at Desktop/fintiq-api/ — must `copy` before push |
| 25/08/2026 | Section 3: `setBadge is not defined` error on load | Changed to `setStatus('technical', 'done')` |
| 26/08/2026 | Catalyst: `_clean is not defined` — nested function not visible to `_run_catalyst` | Moved `_clean()` to module level |
| 26/08/2026 | Catalyst: earnings date showing past date (e.g. July 30 in August) | Added future-only filter; fallback search in `earnings_dates` |
| 26/08/2026 | Valuation: reverse DCF not working for high-growth stocks (TSLA) | Raised solver ceiling from 80% to 150%; removed premature gPct clamp |
| 26/08/2026 | git index.lock blocking commits | `del .git\index.lock` in PowerShell |
