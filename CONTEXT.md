# Fintiq Project Context — Last updated 14/09/2026

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

### Product Architecture — Three Layers (agreed 01/09/2026)

**Layer 1 — Information (Free)**
All data sections as-is: Fundamentals, Valuation, Technical, Catalyst, Risk. All static AI commentary REMOVED — no free AI.

**Layer 2 — User Conclusion (Free)**
Thesis capture boxes (scroll-triggered, IntersectionObserver) at bottom of each data section. 2 guided prompts per section. Inputs stored to `window._fintiqSession.explicit_inputs`.

**Layer 3 — AI Copilot (Paid — credits)**
Copilot chat per section (Haiku, ~$0.004/exchange with prompt caching = ~$0.001/exchange with caching savings).
Investment Committee report = Layer 3 premium (Sonnet, ~$0.06/report, one-time).

**Session Object**: `window._fintiqSession` — compiled from all user inputs across sections. Passed as context to Copilot and Committee endpoints. Schema defined in "Session data schema.pdf".

**Credit Pricing (to be finalised):**
- Copilot exchange: ~$0.001 net cost (with caching). Selling price TBD.
- Committee report: ~$0.06 net cost. Selling price TBD.
- Margins: 89-94%.

### Stock Deep Dive (fintiq.uk/deep-dive.html) — Current State (01/09/2026)
Standalone public page. Enter any ticker → instant institutional-grade analysis.
1. **Fundamentals** ✅ — business overview, growth table, TSR, FF4, analyst ratings, AI chat
2. **Valuation** ✅ — DCF, Monte Carlo, sensitivity grid. AI assumptions block REMOVED.
3. **Technical** ✅ — 3-tab charts (Daily/Swing/Long Term, 3yr data). AI commentary REMOVED.
4. **Risk & Position Sizing** ✅ — GBM Monte Carlo, stop loss stress tester, position size calculator
5. **Catalyst Tracker** ✅ — earnings, analyst ratings, short interest, news feed. AI summary REMOVED.
6. **Decision Analysis** ✅ — Conviction Calibrator, framework verdict, thesis textarea, PDF report. AI challenge REMOVED.
7. **Thesis Capture Boxes** ✅ — scroll-triggered at bottom of sections 1-5. 2 prompts each.
8. **window._fintiqSession** ✅ — auto-syncs ticker, direction, thesis, DCF inputs, conviction %, signals, explicit inputs.
9. **AI Copilot** 🔜 — per-section chat paywall (to be built)
10. **Investment Committee Report** 🔜 — premium Sonnet report (to be built)

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
| `POST /fundamentals/chat` | AI chat — section-specialist (Haiku, prompt-cached, returns `contradiction_flags[]`) |
| `POST /session/summarise` | Compress Copilot dialogue → `dialogue_summary` for Committee (Haiku, 300 tokens) |
| `POST /valuation/ai-assumptions` | Bear/Base/Bull scenario generator (Haiku, 1200 tokens) — **kept in API but removed from frontend (moved to Copilot paywall layer)** |
| `GET /technical?ticker=X` | Start or return technical data (polling) |
| `GET /technical/status?ticker=X` | Poll for result |
| `POST /technical/ai-commentary` | Long+Short trade setup AI — **kept in API but removed from frontend (moved to Copilot paywall layer)** |
| `POST /catalyst/ai-summary` | Catalyst AI summary — **kept in API but removed from frontend (moved to Copilot paywall layer)** |
| `POST /decision/ai-challenge` | Thesis challenger — **kept in API but removed from frontend (moved to Copilot paywall layer)** |

### /technical endpoint — what it returns (updated 01/09/2026)
- **ALL bars from 3 years of OHLCV** (`period="3y"`, ~750 bars) — frontend slices by timeframe
- MA50, MA200, RSI(14), MACD(12,26,9), Bollinger Bands(20,2)
- `trend`: STRONG_UPTREND / UPTREND / NEUTRAL / DOWNTREND / STRONG_DOWNTREND
- `momentum`: OVERBOUGHT / BULLISH / NEUTRAL / BEARISH / OVERSOLD
- `key_levels`: support, resistance (from recent lows/highs)
- `options`: pcr, atm_iv, max_pain, put_wall, call_wall, unusual (list)
- `ind_series` simplified: `[sf(v) for v in s]` (no index-matching loop needed since chart == hist)

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

### Section 4 — Risk & Position Sizing (built 26/08/2026)
- `loadRisk()` → `_pollRisk(attempt)` → `renderRisk(d)` then `_renderRisk()`
- `_stopDirection` state variable — 'long' | 'short', toggled via buttons
- `_setStopDirection(dir)` — updates labels, button colours, revalidates stop input
- `_updateStopProb()` — direction-aware: long stop must be below S0, short stop must be above
- `_updatePosSize()` — uses `Math.abs(mc.S0 - stopVal)` as riskPerShare regardless of direction
- Risk Monte Carlo (GBM): separate from valuation MC — simulates 30/60/90d price paths
- `mc.annualisedVol` and `mc.probProfit` are already percentages — do NOT multiply by 100
- AI expander: `id="risk-ai-expander"`, auto-opened via `_openAIExp()`

### Section 5 — Catalyst Tracker (built 26/08/2026)
- Background thread: `_run_catalyst(ticker)` — all yfinance calls wrapped in `_safe(fn, timeout)` using `concurrent.futures`
- `_safe()` helper defined at top of `_run_catalyst` — prevents yfinance hanging from blocking the thread
- `_catalyst_jobs[ticker]` — stores `{status:'done', ...all data, ts:time.time()}`
- Polling: `_pollCatalyst(attempt)` — 40 attempts × 2s = 80s timeout, then shows Retry button
- AI summary: `catalyst_ai_summary()` — Haiku, 600 tokens, 5 sections with ▸ headers

### Section 6 — Decision Analysis (updated 01/09/2026)
- `loadDecision()` → `renderDecision()` wrapped in try/catch — surfaces exact error to user
- `_decSignals()` — reads from `_session.fundamentals.data`, `_session.technical.data`, `_session.risk`
  - `td.trend` is an OBJECT `{classification, ...}` — always use `trendObj.classification`
  - `td.momentum` is an OBJECT `{rsi, rsi_signal, macd, macd_signal_val, ...}` — use `.rsi_signal`
  - `mc.annualisedVol` and `mc.probProfit` are already % — no `*100`
- **AI Challenge REMOVED**: `_submitThesis`, `_renderChallenge` deleted. "Challenge My Thesis" button removed. Textarea kept, relabelled "Your Investment Thesis" — feeds `_fintiqSession`
- AI expanders: `.ai-expander` CSS with `_toggleAIExp(id)` / `_openAIExp(id)`
- Section badges: `setStatus(name, 'done')` now hides the badge (`display:none`)

### Section 6 — PDF Report
- Button: `_generateReport()` → `_doGenerateReport()` (wrapped in try/catch with alert)
- Uses Blob URL + always-download approach: `a.download = ticker-fintiq-report.html; a.click()`
- Common PDF bugs fixed:
  - `td.trend?.replace` → `td.trend` is object, use `td.trend?.classification`
  - `td.momentum?.replace` → `td.momentum` is object, use `td.momentum?.rsi_signal`
  - `annualisedVol * 100` and `probProfit * 100` → already %, remove `*100`

### Section 3 — Technical (rebuilt 01/09/2026)
- `loadTechnical()` → `_pollTechnical(attempt)` → `renderTechnical(d)`
- Trend banner: colour-coded (green/red/amber) with trend + momentum badges
- **Three-tab chart system**: Daily (last 60 bars) / Swing (last 252 bars) / Long Term (all ~750 bars)
  - Tab CSS: `.chart-tabs`, `.chart-tab`, `.chart-tab.active`, `.chart-pane`, `.chart-pane.active`
  - Tab switch: `_switchChartTab(name, el)` — toggles active classes
  - Data slicing: `const sl = (arr, n) => arr.slice(Math.max(0, total - n))` applied to all series
  - Each pane: price canvas + RSI canvas + MACD canvas (9 canvases total, `_buildPriceChart`, `_buildRsiChart`, `_buildMacdChart` helpers)
  - Daily: price + volume only (no MAs/BB) — momentum entry focus
  - Swing: price + MA50 + MA200 + Bollinger Bands + S&R levels — position trading view
  - Long Term: price + MA200 only — structural trend view
- Stats grid (4 cards): RSI value, MACD signal, Support, Resistance
- Options dashboard: 6 cards (PCR, ATM IV, Max Pain, Put Wall, Call Wall) + unusual activity table
- AI commentary: **REMOVED** (moved to Copilot paywall layer — `_loadTechCommentary` deleted)

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

### 14/09/2026 — What was completed this session

#### Context
This session was a continuation (context compacted from 07/09 session). The 07/09 fixes were already written to disk but not yet deployed. This session confirmed all fixes were in place and added one additional tweak, then prepared deploy commands.

#### Fixes confirmed in deep-dive.html (carried from 07/09, verified 14/09)

- ✅ **Risk Copilot "going to sleep" — CRITICAL ROOT CAUSE FIXED** — `const _ctrl`, `const _chatTimeout`, `const _thinkingNudge` were declared INSIDE `try {}` block. JavaScript `const`/`let` are block-scoped → NOT accessible in `catch {}`. When backend returned error, `catch` block threw a secondary `ReferenceError` on `clearTimeout(_chatTimeout)`, silently killing error handling. Typing indicator stayed forever, no error shown, button re-enabled but Copilot looked frozen. This bug affected EVERY test run (XYZ, AAPL, SHOP). Fix: hoisted all three `const` declarations OUTSIDE the `try {}` block.

- ✅ **`_loadRiskAI()` was dead code — never called** — Function defined at line ~3437 but never invoked from anywhere in the codebase. Risk auto-AI-summary had never fired across all test runs. Fix: added call from `_renderRisk()` after DOM is ready, with `_aiSummaryFired` flag to prevent repeat calls on horizon tab changes.

- ✅ **Valuation Copilot blind to DCF results / Monte Carlo** — `_vs` only holds slider inputs (revenue growth, WACC, etc.), not computed outputs. `_mcResults` didn't exist. Fix: added `let _mcResults = null` global; stored `{ p10, p50, p90, pAbove, currency }` in `_runMC()` after computation; added `dcf_result` (equity_ps + upside_pct via `_computeDCF`) and `mc_results` to valuation section_data in `sendChat()`.

- ✅ **Catalyst "Loading..." forever (recurrence on SHOP)** — After attempt 0, frontend was switching to `/catalyst/status` which returns raw job state with NO restart logic. If job was slow or Railway restarted, frontend got stuck indefinitely. Fix: always poll `/catalyst` (has built-in restart: if `processing > 90s`, job is restarted). Poll limit raised 40 → 60 attempts (80s → 120s total). "Still loading..." progress label shown at attempt 7 (14s). `id="catalyst-loading-label"` added to div.

- ✅ **Session data lost on navigation** — DOMContentLoaded always called `startAnalysis()` re-fetching all data. Fix: `sessionStorage` persistence with `_SS_KEY = 'dd_session_v2'`. `_saveSession()` saves `{ ticker, ts, fundamentals, technical, catalyst, risk, vs, chatHistory }` after each section load and Copilot exchange. `_tryRestoreSession(ticker)` restores on page load if ticker matches and data is <4 hours old. Toast shown on restore.

- ✅ **Committee 120s AbortController** — committee fetch had no timeout (Sonnet can take 60-90s on complex prompts). Fix: `AbortController` with 120s timeout wrapping the committee `fetch()` call.

#### Fixes confirmed in main.py (carried from 07/09, verified 14/09)

- ✅ **Committee max_tokens 3500 → 5000** — JSON output was being cut mid-parse for bull/bear cases (200+ words each). Fix: raised `max_tokens=5000` in `_committee_client.messages.create()`.

- ✅ **Catalyst yfinance timeouts reduced** — `tk.info` timeout 15s → 10s; `tk.earnings_dates` timeout 10s → 8s. Keeps total catalyst job well within 55s wall-clock deadline.

#### Models in use (14/09 state)
| Call | Model | max_tokens | Est. cost |
|---|---|---|---|
| Copilot chat (all sections) | Haiku 4.5 | 1500 | ~$0.004/exchange |
| Valuation AI assumptions | Haiku 4.5 | 1200 | ~$0.003/call |
| Catalyst AI summary | Haiku 4.5 | 600 | ~$0.002/call |
| Committee report | Sonnet 4-6 | 5000 | ~$0.08/report |
| Market Bulletin | Sonnet 4-6 | 6000 | ~$0.12/run, 2×/day |

#### Cost tracking
- Test run 1 (BULL, 03/09): $0.26
- Test run 2 (BMRN, 04/09): $0.12 (partial)
- Test run 3 (XYZ/Block, 07/09): ~$0.13 estimated
- Test run 4 (AAPL, 07/09): $0.12
- Test run 5 (SHOP, 07/09): triggered session compaction

#### Deploy commands — STILL NEEDED (not yet deployed as of 14/09 session end)
```powershell
# Vercel (deep-dive.html — all JS fixes)
cd C:\Users\imran\Desktop\Fintiq\Articles
git add deep-dive.html
git commit -m "Fix: const scoping bug (Risk Copilot); catalyst always poll /catalyst; _loadRiskAI called; _mcResults for Valuation Copilot; sessionStorage persistence; committee 120s timeout"
git push origin HEAD:main

# Railway (main.py — committee max_tokens 5000 + catalyst timeout reduction)
Copy-Item "C:\Users\imran\Desktop\Fintiq\Articles\fintiq-api\main.py" -Destination "C:\Users\imran\Desktop\fintiq-api\main.py" -Force
cd C:\Users\imran\Desktop\fintiq-api
git add main.py
git commit -m "Fix: committee max_tokens 3500→5000; catalyst yf timeouts reduced to 10/8s"
git push origin HEAD:main
```

#### Pending (start here next session)
- [ ] **Run the two deploy commands above FIRST**
- [ ] **Test run 6** (any of MSFT / AAPL / SHOP) — verify:
  - Risk Copilot responds or shows clear error message (no more silent freeze)
  - Catalyst loads within 120s, shows "Still loading…" at 14s mark
  - Valuation Copilot can discuss DCF fair value and MC p10/p50/p90
  - Committee report shows full bull/bear (200+ words, 5 dimensions, no truncation)
  - Navigate away mid-analysis and back — data restores from cache, no re-fetch
  - Risk section shows AI auto-summary (was never firing before)
- [ ] 3× full deep-dive test runs to measure real session cost (Sonnet committee now 5000 tokens)
- [ ] Credits/subscription pricing finalisation (deferred)
- [ ] Auth (`require_user` dependency on all AI endpoints) — deferred
- [ ] Credit store + deduction middleware — deferred
- [ ] Server-side session store — deferred
- [ ] Mobile: My Dashboard 3-col grid → single column (task #23)

---

### 07/09/2026 — What was completed this session

#### Test run 3 — Block/XYZ (07/09)
- Fundamentals ✅, Valuation Copilot ✅, Technical Copilot ✅ (partial), Risk Copilot (silent, no response), Catalyst ❌ (still stuck), Committee ✅ (working but shallow bull/bear, [object Object] in conditions, valuation N/A)

#### main.py fixes (07/09)

- ✅ **Company overview truncated at 600 chars** — `description[:600]` → `[:1500]`. Full description now shown.
- ✅ **TSR 3yr/5yr showing "—"** — `_get_hist()` fetched `period="3y"` (756 days). 5yr TSR needs 1260 days → always failed. Fixed: `period="5y"`. Both 3yr and 5yr TSR now computable.
- ✅ **Catalyst "Loading…" forever — ROOT CAUSE FOUND** — `_run_catalyst()` stored result directly via `_clean(result)` with NO `'status': 'done'` key. `get_catalyst()` never matched `status=='done'`, kept restarting the job every poll, returned `"processing"` forever. Fixed: added `'status': 'done'` to result dict before `_clean()`. Compare with `/fundamentals` (wraps in `{'status':'done','data':result}`) and `/technical` (same) — catalyst was the only one missing this.
- ✅ **Copilot responses truncated mid-sentence** — `max_tokens=600` in `/fundamentals/chat`. Raised to `1500`. All sections benefit.
- ✅ **AI cherry-picking data (bias)** — Two causes: (1) 600 token limit forced brevity → AI selected most dramatic points. (2) No data completeness rule. Fixed both: raised max_tokens + added DATA COMPLETENESS & IMPARTIALITY mandate to `pushback_mandate`: must cite complete data series, partial agreement is valid, goal is truth not to prove user wrong.
- ✅ **Bulletin TTL 6h → 12h** — was agreed earlier but never applied. `_BULLETIN_TTL = 6*3600` → `12*3600`. Bulletin now regenerates max 2× per day (~$0.25/day background cost vs $0.50/day before).
- ✅ **Committee prompt overhauled** — model changed from `claude-haiku-4-5-20251001` → `claude-sonnet-4-6` (matches UI badge "Sonnet-powered"). `max_tokens` 2500 → 3500. `dcf_state` param added. New prompt mandates:
  - `thesis`: summary + committee critique of quality/consistency
  - `bull_case` / `bear_case`: 200+ words each, 5-dimension framework (Fundamental / Valuation / Technical / Risk / Catalyst), senior committee chair voice, specific numbers from analyst's session
  - `conditions`: plain prose string (was structured object → caused `[object Object]`)
  - `valuation_range`: explicit instruction to derive bear/base/bull prices from DCF explicit_inputs

#### deep-dive.html fixes (07/09)

- ✅ **sendChat 45s AbortController** — fetch had no timeout; hanging requests showed typing indicator forever with no error. Fixed: `AbortController` with 45s timeout; catch block shows `"Request timed out (45s)"` and re-enables Send button.
- ✅ **Risk auto-AI-summary wrong key** — auto-fire call at `_renderRisk()` sent `fundamentals_data:` key. Backend looks for `section_data:`. AI received `{}`. Fixed: changed key to `section_data: _session.risk?.data || {}`.
- ✅ **[object Object] in Investment Conditions** — `r.conditions` was a structured JSON object; `section()` helper used `${content}` template literal → `[object Object]`. Fixed: defensive render that checks `typeof r.conditions`, renders as key-value pairs if object.
- ✅ **Committee dcf_state payload** — frontend now passes `dcf_state: _vs || {}` in committee compiled payload so AI has DCF slider values to derive valuation range.

#### Models in use (07/09 state)
| Call | Model | max_tokens | Estimated cost |
|---|---|---|---|
| Copilot chat (all sections) | Haiku 4.5 | 1500 | ~$0.004/exchange |
| Valuation AI assumptions | Haiku 4.5 | 1200 | ~$0.003/call |
| Catalyst AI summary | Haiku 4.5 | 600 | ~$0.002/call |
| Committee report | Sonnet 4-6 | 3500 | ~$0.08/report |
| Market Bulletin | Sonnet 4-6 | 6000 | ~$0.12/run, 2×/day |
| Session summarise | Haiku 4.5 | 300 | ~$0.001/call |

#### Cost tracking
- Test run 1 (BULL, 03/09): $0.26
- Test run 2 (BMRN, 04/09): $0.12 (partial)
- Test run 3 (XYZ/Block, 07/09): ~$0.13 estimated (committee was Haiku, now Sonnet next run)
- Bulletin auto-fire (07/09 confusing incident): ~$0.13 (Sonnet bulletin regenerated while testing)

#### Pending (still outstanding — start here next session)
- [ ] **Deploy all changes** — both Railway and Vercel deploys still needed for 07/09 fixes:
  ```powershell
  # Railway
  Copy-Item "C:\Users\imran\Desktop\Fintiq\Articles\fintiq-api\main.py" -Destination "C:\Users\imran\Desktop\fintiq-api\main.py" -Force
  cd C:\Users\imran\Desktop\fintiq-api
  git add main.py
  git commit -m "Fix: catalyst status done; desc 1500; TSR 5y; max_tokens 1500; impartiality; bulletin 12h; committee Sonnet 3500"
  git push origin HEAD:main
  # Vercel
  cd C:\Users\imran\Desktop\Fintiq\Articles
  git add deep-dive.html CONTEXT.md
  git commit -m "Fix: sendChat 45s timeout; Risk auto-summary section_data; conditions [object Object]; dcf_state to committee"
  git push origin HEAD:main
  ```
- [ ] **Run full test deep dive** after deploy — all 6 sections + Copilot on each + Committee. Verify: catalyst loads, Risk Copilot responds, Copilot responses not truncated, Committee has proper bull/bear/valuation range.
- [ ] **3× full test runs on different stocks** to measure real session cost with Sonnet committee
- [ ] Fix 2: Auth (`require_user` dependency) — deferred
- [ ] Fix 3: Credit store + deduction middleware — deferred
- [ ] Fix 4: Server-side session store — deferred
- [ ] Fix 8: Pull `session_ctx` from server store — deferred
- [ ] Mobile: My Dashboard 3-col grid → single column (task #23)

---

### 04/09/2026 — What was completed this session

#### Test runs — observations from BULL (03/09) and BMRN (04/09)
- BULL test run cost: $0.26 (full run, committee failed)
- BMRN test run cost: $0.12 (partial — committee and catalyst not working)

#### main.py fixes (04/09)

- ✅ **FF4 auto-fire removed** — `/fundamentals` endpoint was auto-calling Haiku for Fama-French commentary on every section open. Layer 1 violation. FF4 numbers still returned; Copilot interprets on request.
- ✅ **Committee `async def` → `def`** — async function calling synchronous Anthropic blocked event loop; changed to sync def so FastAPI runs in threadpool.
- ✅ **Committee `NameError: client`** — `committee_report()` used `client.messages.create()` without defining `client` locally. Fixed: added `_committee_client = anthropic.Anthropic(...)` at top of function.
- ✅ **Committee model** — changed from `claude-sonnet-4-5` (deprecated/slow) to `claude-haiku-4-5-20251001`. Wrapped Anthropic call in try/except; errors now surface as HTTP 500 with detail string instead of silent "Failed to fetch".
- ✅ **Catalyst stuck "Loading…" forever** — `_run_catalyst()` background thread hangs on slow yfinance calls (BMRN/pharma stocks particularly affected). Fixed: added 55-second wall-clock deadline `_deadline = time.time() + 55`; all `_safe()` calls respect it. Tavily timeout reduced 12s → 8s. Thread now always completes within 55s with whatever data it has.

#### deep-dive.html fixes (04/09)

- ✅ **Technical Copilot blind** — `section_data` for technical was sending raw OHLCV arrays (750 items × 5 series), eating all 6000-char context limit. AI received only dates, no indicators. Fixed: `_techSummaryForCopilot(d)` helper strips all array fields (`dates`, `ohlcv`, `ma50`, `ma200`, `bb_up`, `bb_low`, `rsi`, `macd`, `macd_signal`, `macd_hist`). Copilot now receives compact: `trend`, `momentum`, `volume`, `key_levels`, `options`.
- ✅ **Technical chart scale** — R1/R2 resistance lines at $80 while BULL price was $8 (pre-reverse-split stale values). Fixed: S/R levels clipped to ±4× current price before charting (`klSafe` object). Levels outside that range silently dropped.
- ✅ **Risk Copilot blind** — `_session.risk = { mc, horizon }` (no `.data` key) but `sendChat` looks for `_session.risk?.data` → got `{}`. Fixed: changed to `_session.risk = { data: { current_price, horizon_days, annualised_vol_pct, atm_iv_pct, p10-p90, probProfit, options } }`.
- ✅ **Valuation Copilot blind** — `section_data` was sending entire `fundamentals.data` blob (huge) + `valuation_state`, but 6000-char truncation cut off `valuation_state` before it appeared. Fixed: now sends compact object only: `{ valuation_inputs, overview (price/sector/currency only), quality, growth, analyst, valuation_state }`.

#### Key architecture notes
- All 6 sections use the same `/fundamentals/chat` endpoint. Tavily fires on every message across all sections.
- `section_data` key in the chat payload is how each section gives the Copilot its live data snapshot. Each section must store data under `_session[section].data` for `sendChat` to pick it up.
- Technical section: strip OHLCV arrays before sending (done via `_techSummaryForCopilot`).
- Risk section: store MC outputs explicitly in `_session.risk.data` (done in `_renderRisk`).

#### Pending (still outstanding)
- [ ] Catalyst section: verify it loads correctly after deadline fix is deployed
- [ ] Run complete test deep dive (all 6 sections + committee) after all fixes deployed
- [ ] CONTEXT.md cost tracking — $0.26 + $0.12 = $0.38 spent on test runs so far

---

### 03/09/2026 — What was completed this session

#### main.py — Copilot fixes (cascading Railway deploy cycle)
- ✅ `client` NameError fixed — `fundamentals_chat()` was using `client` without instantiating. Added `client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)` at top of that function.
- ✅ Removed broken prompt caching — `betas=["prompt-caching-2024-07-31"]` not supported in SDK ≤0.40.0. Reverted to plain `client.messages.create()`.
- ✅ `requirements.txt` bumped `anthropic>=0.34.0` → `>=0.40.0`.
- ✅ `_loadRiskAI()` removed from setTimeout block — was auto-firing AI ($0.07) on every Risk section open. Layer 1 violation. Confirmed no other violations.
- ✅ BULL + fintech peers added to `_PEER_MAP` (BULL, HOOD, IBKR, SOFI, COIN, PYPL, SQ).
- ✅ FMP `/v4/stock_peers` fallback added for unknown tickers.
- ✅ Tavily web search added to ALL Copilot messages (not keyword-gated). Fires on every user message, result appended to system prompt via string concatenation (`system + web_supplement`) — NOT inside f-string (would cause brace conflict from JSON `{}`).
- ✅ f-string brace conflict fixed — `{web_supplement}` removed from f-string, appended via `system=system + web_supplement` in `client.messages.create()`.

#### deep-dive.html — UI fixes
- ✅ Options explanation uses live PCR data instead of hardcoded example values (1.62 / 0.62).

#### Key architecture reminder
- `web_supplement` built BEFORE system f-string; appended AFTER via concatenation — never inside `{}` in f-string.
- Tavily fires on every Copilot message. Result = `\n\nWEB SEARCH RESULTS...` prepended to system prompt.

---

### 02/09/2026 — What was completed this session

#### deep-dive.html — UI fixes (from screenshot audit)
- ✅ Chevron arrows right-aligned — moved `margin-left:auto` from `.section-status` to `.section-chevron`
- ✅ Risk & Position Sizing crash fixed — `_vs` null guard + try/catch wrapper around `_renderRisk()`
- ✅ `const html` → `let html` in `_renderRisk()` — was crashing with "Assignment to constant variable"
- ✅ Duplicate "Your Investment Thesis" textarea removed from Decision Analysis
- ✅ Section order swapped to Data → Copilot → Your View across all 6 sections
- ✅ Stale `dec-thesis-input` references cleaned up — debounce listener now targets `.capture-textarea` class
- ✅ Qualitative Fundamentals (Point 2): Auto-fire AI block rejected (violates Layer 1 = no free AI). Instead:
  - Layer 1: FMP revenue segment + geographic breakdown added to `/fundamentals` endpoint via `_fetch_fmp_segments(ticker, kind)`. Rendered as "Revenue Breakdown" tables with % bars in Fundamentals section.
  - Layer 3: Fundamentals Copilot specialist prompt updated — first message now opens with Business Quality Snapshot (moat, revenue model, growth drivers, factors for/against).
- ✅ `_fmt_rev(v, sym)` helper added for FMP segment revenue formatting

#### main.py — Code audit fixes (from "code audit.pdf", 02/09/2026)
Audit found 1 blocker, 2 cost issues, 7 missing features. Fixes 2/3/4 deferred (auth/credits/session store — pending 3 test runs of full deep dive to assess real cost first).

- ✅ Fix 1: `anthropic_client` → `client` on line 2874 — Committee was crashing NameError on every call (BLOCKER)
- ✅ Fix 5: Copilot model reverted Sonnet → Haiku (`claude-haiku-4-5-20251001`, max_tokens 600) — Sonnet destroys margin model at scale (~15-25× more expensive than spec intends)
- ✅ Fix 6: Prompt caching added to `/fundamentals/chat` — system prompt cached with `cache_control: ephemeral`, historical turns cached. From turn 2+, ~90% input cost saving on cached tokens. `betas=["prompt-caching-2024-07-31"]` required for Haiku.
- ✅ Fix 7: `POST /session/summarise` endpoint added — takes `{section_name, ticker, messages[]}`, returns `{dialogue_summary}` (Haiku, 300 tokens). Frontend calls on section exit; Committee uses summaries not raw transcripts.
- ✅ Fix 9: Contradiction checks extracted into `_run_contradiction_checks(sections, live_price)` shared function. Called by Committee as before. Also now returned in every Copilot response as `contradiction_flags[]` for real-time inline display during dialogue.
- ✅ Fix 10: In-memory entitlement store `_session_entitlements: dict` added. Committee capped at 2 reports per session, returns HTTP 403 when exhausted. Keyed by `session_id` (switches to `user_id` when auth re-enabled).
- ✅ `_fetch_fmp_segments(ticker, kind)` helper added to main.py — calls FMP `/v4/revenue-product-segmentation` and `/v4/revenue-geographic-segmentation`, returns `[{name, value}]` sorted desc.

#### Deferred (conscious decision — run 3 test deep dives first to measure real cost)
- [ ] Fix 2: Auth (`require_user` dependency on all AI endpoints)
- [ ] Fix 3: Credit store + deduction middleware
- [ ] Fix 4: Server-side session store + `PUT /session/{id}/section/{name}` endpoint
- [ ] Fix 8: Pull `session_ctx` from server store instead of frontend payload (depends on Fix 4)

### Other pending (lower priority)
- [ ] **FIRST: Confirm Copilot working** — test on BULL deep dive after 03/09 Railway deploy (f-string fix was deploying at session close)
- [ ] **Vercel deploy** — `git push origin HEAD:main` from Articles folder (options explanation fix + _loadRiskAI removal)
- [ ] 3× full deep-dive test runs (different stocks) to measure actual API cost per session
- [ ] Mobile: My Dashboard 3-col grid → single column (task #23)
- [ ] Page audit — review all fintiq.uk pages (deferred by Imran)
- [ ] Credits/subscription pricing — finalise after test runs
- [ ] Watchlist (Imran has a different approach — wait for brief)
- [ ] Re-enable login/paywall (after auth fixes 2/3/4)

---

## 12. AUDIT FINDINGS — 01/09/2026 (evening)

Both PDFs re-read in full. Code audited against both. Summary of gaps found:

### ✅ Correctly built
- 3-year technical charts with Daily/Swing/Long Term tabs (9 canvases)
- Static AI commentary blocks removed from all 4 sections
- Capture boxes rendering inline before Copilot, correct section order
- `_paywallActive = false` flag controlling all Copilot + Committee gates
- `renderCopilot()` replacing "Fintiq AI Analyst" branding
- `_renderCommitteeCard()` with 6 pillars in Decision section

### ❌ Gaps vs spec

| # | Gap | Where |
|---|---|---|
| 1 | `_syncFintiqSession()` is a flat ad-hoc object — schema requires `sections[6]` array of `SectionState` | deep-dive.html |
| 2 | No `SectionState` per section — no `thesis_statement`, `conclusions[]`, `flags[]`, `dialogue_summary` | deep-dive.html |
| 3 | `explicit_inputs` saves capture box free text — should capture structured UI widget values (sliders, dropdowns, toggles) | deep-dive.html |
| 4 | `sendChat()` saves `chat_conclusions` string — must write `Conclusion[]` objects and `dialogue_summary` to section state | deep-dive.html + main.py |
| 5 | Committee receives raw `_syncFintiqSession()` dump — spec says compiled object only, assembled server-side, never raw transcript | deep-dive.html + main.py |
| 6 | `confidence` output is single integer (0-100) — spec says 4-dimensional breakdown, never a single % (regulatory risk) | main.py + deep-dive.html |
| 7 | Copilot system prompt is one generic hedge fund analyst — spec requires section-specialist persona + 6 required context fields | main.py |
| 8 | No pushback mandate — spec says "if user conclusion contradicts data, name it. Non-negotiable." | main.py |
| 9 | No 5 deterministic contradiction pre-checks before Committee model call | main.py |

### PDFs location (uploads)
- `Session data schema.pdf` — engineering spec, `SectionState` structure, `ExplicitInputs` by section, `Conclusion[]` object, `Flag[]` object, compiled Committee object, 5 contradiction pairs
- `Copilot and investment committee report.pdf` — product spec, design philosophy, 6 context fields required, behaviour rules (THE AI DOES / DOES NOT), Committee report structure (7 sections), 4-dimensional confidence model

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
| 27/08/2026 | WACC/TG sensitivity table: higher TG showing lower value | McKinsey RONIC formula: at low RONIC, higher TG = more reinvestment = lower FCF. Fixed: sensitivity table uses simple Gordon Growth TV = lastFCF*(1+tg)/(wacc-tg). Main DCF unchanged. |
| 27/08/2026 | EV bridge shows different value than Method 1 after slider move | Bridge was static HTML baked at render. Added IDs `bridge-ev`, `bridge-eq`, `bridge-ps` and update them in `_refreshValuation()` |
| 27/08/2026 | MC Bear/Base/Bull values wrong (TSLA: $55/$81/$123 vs DCF $413) | MC was hardcoding `g2=g1*0.65, g3=g1*0.4` ignoring user's phase 2/3 sliders. Fixed to use `vs.g2` and `vs.g3` as means with independent noise |
| 27/08/2026 | Catalyst stuck on "Loading catalyst data..." | `_run_catalyst` yfinance calls blocking indefinitely. Fixed with `_safe(fn, timeout)` using `concurrent.futures.ThreadPoolExecutor` |
| 27/08/2026 | PDF report error: `td.trend?.replace is not a function` | `td.trend` is object `{classification,...}`. In PDF template use `td.trend?.classification` |
| 27/08/2026 | PDF: `td.momentum` showing `[object Object]` | `td.momentum` is object `{rsi, rsi_signal, macd,...}`. Use `td.momentum?.rsi_signal` |
| 27/08/2026 | PDF: Annualised Vol showing 4950%, ProbProfit 3900% | Values already %, PDF template had extra `*100`. Removed. |
| 27/08/2026 | AI Challenge showing shallow analysis, no segment breakdown | Upgraded to Sonnet model (1800 tokens), added Tavily web search pre-fetch, segment-level instructions, verdict with judgemental probability |
| 27/08/2026 | PDF never downloading (popup blocked) | `window.open(blob_url, '_blank')` blocked by browser. Changed to always `a.download = file.html; a.click()` |
| 27/08/2026 | Catalyst `_safe()` blocking indefinitely | `with ThreadPoolExecutor() as ex:` calls `shutdown(wait=True)` on exit — blocks forever on hung yfinance threads. Fixed: `ex.shutdown(wait=False)` in explicit `finally` block |
| 27/08/2026 | Kelly always showing same $1,000 | Hard cap `Math.min(0.10, halfKelly)` — all cases exceed 10%. Removed cap, use `Math.max(0, fullKelly/2)` |
| 27/08/2026 | Kelly showing `undefined%` | `<script>` tags in innerHTML don't execute. Was setting `window._ccProb` via injected script. Fixed: module-level `let _ccProb = 50` set directly as `_ccProb = prob` |
| 27/08/2026 | Kelly not direction-aware | 67% LONG prob baked at render. SHORT thesis for AAPL should be ~33%. `_setDirection()` now re-renders calibrator with `_computeBayesProb(signals, 'short')` |
| 27/08/2026 | Conviction Calibrator explainer not opening | `.ai-exp-body` class wrong (should be `.ai-expander-body`); also inline `style="display:none"` overriding class toggle. Fixed both. |
| 28/08/2026 | "In progress" / "Coming soon" badges cluttering deep-dive.html section headers | Badges hidden (`display:none`); `setStatus()` stubbed to no-op |
| 28/08/2026 | Nav inconsistent across pages; App button still present | All pages updated to: Home \| Market Bulletin \| Stock Deep Dive \| Tools \| Learn. App button removed everywhere. |
| 29/08/2026 | Example output box showed static AAPL numbers — not credible | Replaced with real screenshot `img/deep-dive-preview-3.png` (conviction scorecard) |
| 29/08/2026 | `td.momentum` showing `[object Object]` in Technical signal card | Fixed: `typeof td.momentum === 'object'` check, use `.rsi_signal` property |
| 29/08/2026 | Exchange tag showing raw yfinance code "NMS" | Added `_exchangeName()` mapping function (NMS→NASDAQ, NYQ→NYSE, etc.) applied in 3 places |
| 01/09/2026 | `ind_series` was O(n²) — `list(hist.index).index(d)` in loop over all bars | Simplified to `[sf(v) for v in s]` since `chart == hist` after 3y change |
| 01/09/2026 | `_decAIResult` set by removed `_submitThesis` — still referenced in PDF template | Guarded by ternary (`_decAIResult ? ... : ''`) so `null` safely outputs nothing |
| 01/09/2026 | Duplicate `function setStatus` risk — `_origSetStatus` capture would cause infinite recursion | Avoided by inlining `_syncFintiqSession` and `_injectCaptureBox` calls directly inside original `setStatus` |
| 02/09/2026 | Risk section stuck on "Running simulations…" | `_vs` null if Valuation not opened → silent crash. Fixed: `(_vs && _vs.currSym) \|\| fallback`. Also try/catch around `_renderRisk()` |
| 02/09/2026 | Risk section: "Assignment to constant variable" | `const html = \`...\`` then `html += renderCopilot(...)` — can't reassign const. Fixed: `let html` |
| 02/09/2026 | Committee endpoint crashing NameError on every call | `anthropic_client.messages.create()` — variable is `client` throughout file. Renamed. |
| 02/09/2026 | Auto-fire AI "Business Snapshot" block violated Layer 1 (no free AI) | Removed `/fundamentals/business-snapshot` endpoint and `_loadBusinessSnapshot()`. Replaced with FMP structured segment data (Layer 1) + Copilot opening message (Layer 3). |
| 02/09/2026 | Copilot using Sonnet (~$0.06/exchange) vs spec Haiku (~$0.004/exchange) | Reverted to `claude-haiku-4-5-20251001`. Added prompt caching (90% saving from turn 2+). |
| 03/09/2026 | Copilot "Failed to fetch" — `NameError: client not defined` in `fundamentals_chat()` | Added `client = anthropic.Anthropic(...)` at top of that function |
| 03/09/2026 | `TypeError: Messages.create() got unexpected kwarg 'betas'` — SDK too old for prompt caching betas | Removed `betas=["prompt-caching-2024-07-31"]`, reverted to plain `client.messages.create()` |
| 03/09/2026 | `_loadRiskAI()` auto-firing on every Risk section open — ~$0.07 per load (Layer 1 violation) | Removed call from setTimeout block in deep-dive.html |
| 03/09/2026 | BULL competitors returning empty `[]` | Added BULL + fintech peers to `_PEER_MAP`; added FMP `/v4/stock_peers` fallback |
| 03/09/2026 | `UnboundLocalError: cannot access local variable 'web_supplement'` | Used global `requests`, explicit `except Exception: web_supplement = ""` |
| 03/09/2026 | f-string brace conflict — Tavily JSON results contain `{}` breaking f-string | Removed `{web_supplement}` from f-string; append via `system + web_supplement` concatenation |
| 03/09/2026 | Options explanation showing hardcoded PCR values (1.62 / 0.62) | Replaced with dynamic PCR from live data snapshot |
| 04/09/2026 | FF4 auto-fire Haiku commentary on every fundamentals load | Removed AI call from `/fundamentals` endpoint; Layer 1 violation |
| 04/09/2026 | Committee "Failed to fetch" → changed to "API error 500" | `async def` → `def` so errors surface properly; `_committee_client` added (was NameError) |
| 04/09/2026 | Committee `NameError: name 'client' is not defined` | Added `_committee_client = anthropic.Anthropic(...)` at top of `committee_report()` |
| 04/09/2026 | Technical Copilot says "only date labels, no indicator data" | `_techSummaryForCopilot()` strips OHLCV arrays; Copilot now gets trend/momentum/key_levels/options |
| 04/09/2026 | Technical chart R1/R2 at $80 while price at $8 (stale pre-split values) | S/R levels clipped to ±4× current price (`klSafe`) before charting |
| 04/09/2026 | Risk Copilot sends empty `{}` — `_session.risk` had no `.data` key | `_renderRisk()` now stores `_session.risk = { data: { mc outputs, vol, IV, options } }` |
| 04/09/2026 | Valuation Copilot says "I don't see valuation_state" | Compact payload replaces full fundamentals blob; `valuation_state` now within 6000-char limit |
| 04/09/2026 | Catalyst stuck on "Loading catalyst data…" forever | 55-second wall-clock deadline in `_run_catalyst()`; all `_safe()` calls respect it |
