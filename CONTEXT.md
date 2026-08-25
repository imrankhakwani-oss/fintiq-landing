# Fintiq Project Context — Last updated 24/08/2026

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
Five sections (Section 1 built; 2–5 pending):
1. **Fundamentals** — business overview, historical growth table, TSR, FF4 factor, analyst ratings, AI chat
2. **Valuation** — DCF, Monte Carlo, sensitivity grid, Graham number (TODO)
3. **Technical** — price chart, RSI, MACD, trend classification (TODO)
4. **Catalyst** — earnings date, news, options activity (TODO)
5. **Decision** — thesis challenge, conviction score, PDF report (TODO)

---

## 2. KEY FILE LOCATIONS

| File | Path |
|---|---|
| Streamlit app | `C:\Users\imran\Desktop\Fintiq\fintiq_screener.py` |
| Streamlit deploy repo | `C:\Users\imran\Desktop\fintiq-app` |
| FastAPI main | `C:\Users\imran\Desktop\Fintiq\Articles\fintiq-api\main.py` |
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

### Architecture — Background Task + Polling (built 24/08/2026)
Endpoints that are slow (yfinance fetches for large tickers) use this pattern:
- `GET /fundamentals?ticker=X` — returns `{"status":"processing"}` instantly, starts background thread
- `GET /fundamentals/status?ticker=X` — polls result; returns `{"status":"processing"}` or full data
- In-memory job cache: `_fund_jobs: dict = {}`, TTL 5 minutes
- Background thread: `_run_fundamentals(ticker)` — no Railway timeout pressure

### NaN Sanitisation (added 24/08/2026)
yfinance returns `NaN` floats for missing data. Python's `json.dumps` rejects NaN → FastAPI 500 before CORS headers sent → browser sees CORS error.
Fix: `_clean()` function walks result dict recursively, replaces NaN/Inf with `None`.
Applied right before storing in `_fund_jobs[ticker]`.

### GBp → GBP Currency Conversion (added 24/08/2026)
LSE stocks return `currency = 'GBp'` (pence) from yfinance. All monetary values are in pence.
Fix: `gbp_scale = 0.01` when `currency == 'GBp'`. Applied to:
- `price`, `mc`, `ev`, `fcf_val`, `eps_ttm`, `dps`
- `hi52`, `lo52`, `ma50`, `ma200`
- All revenue/earnings/NOPAT in growth_table (including prior-year values)
- TSR price fields (fy_start_price, fy_end_price, q_start_price, q_end_price, dividends)
- TSR % returns unaffected (ratios, scale cancels)
- `display_currency = 'GBP'` sent to frontend (not raw 'GBp')

### Key Endpoints

| Endpoint | Description |
|---|---|
| `GET /health` | Health check |
| `GET /bulletin` | Daily AI market brief |
| `GET /market-data` | Market indices, macro, FOMC |
| `GET /earnings` | Upcoming earnings for index |
| `GET /fundamentals?ticker=X` | Start or return fundamental data (polling) |
| `GET /fundamentals/status?ticker=X` | Poll for result |
| `POST /fundamentals/chat` | AI chat about a ticker's fundamentals |

### AI Chat — System Prompt Rule (fixed 24/08/2026)
The chat must answer questions from training knowledge when data isn't in the context.
Key instruction: "If the user asks about something not in the data above, answer DIRECTLY from your training knowledge. Start with 'Based on what I know about [company]...' Do NOT refuse, do NOT redirect to external sources — you are the source."

---

## 5. DEEP DIVE PAGE (deep-dive.html)

### Status: Section 1 (Fundamentals) complete as of 24/08/2026

### JS Architecture
- `_session` object holds state: `{ticker, fundamentals: {data, loading}}`
- `startAnalysis()` — resets header, calls `loadFundamentals()`
- `loadFundamentals()` — fetch `/fundamentals`, if processing → `_pollFundamentals(0)`
- `_pollFundamentals(attempt)` — polls `/fundamentals/status` every 2s, max 40 attempts (80s), cancels if ticker switches
- `renderFundamentals(d)` — renders all sections from data
- `loadingEl` / `contentEl` toggle while waiting

### Currency Symbol (JS)
```javascript
const currSym = ov.currency === 'USD' ? '$' : ov.currency === 'GBP' ? '£' : ov.currency === 'EUR' ? '€' : (ov.currency || '$');
```
API now sends 'GBP' (not 'GBp') so `£` maps correctly.

### Company Header Reset
On each new ticker search, header fields reset to placeholders before fetch begins:
`co-name`, `co-meta`, `co-price`, `co-badges`, `analyst-pill-wrap`

### FF4 Commentary
When FF4 data available + AI generates commentary, shown as gold-border card below factor grid.

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

### CRITICAL (verify after deploy)
- [ ] Verify SHELL.L and other .L stocks load correctly with GBp→GBP fix
- [ ] Check AI chat responses for Deep Dive — is it answering from training knowledge?
- [ ] FF4 commentary — verify it appears below the factor grid

### Deep Dive — Sections 2–5 (build order)
- [ ] **Section 2 — Valuation**: DCF, Monte Carlo, sensitivity grid, Graham number
- [ ] **Section 3 — Technical**: price chart, RSI, MACD, trend classification
- [ ] **Section 4 — Catalyst**: earnings date, news, options activity
- [ ] **Section 5 — Decision**: thesis challenge, conviction score, PDF report

### Other
- [ ] Mobile: My Dashboard 3-col grid → single column (task #23)
- [ ] Retire bulletin from app.fintiq.uk (remove/disable bulletin tab in Streamlit)
- [ ] Apply remaining 9 audit fixes to main.py (task #74)
- [ ] Re-enable login/paywall with new protocol
- [ ] Polygon.io news + earnings data feed ($29/mo)

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
