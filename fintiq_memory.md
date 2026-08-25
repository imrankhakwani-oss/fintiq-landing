# Fintiq Project Memory
_Last updated: 21 Aug 2026 (Session 8 — Bulletin migration COMPLETE. FastAPI live on Railway, bulletin.html live on Vercel, api.fintiq.uk DNS configured.)_

---

## 🔴 CRITICAL DEPLOY RULE — NEVER BREAK THIS

**NEVER push `fintiq_screener.py` directly from the Fintiq folder.**
Always copy to `fintiq-app` first:
```powershell
cd C:\Users\imran\Desktop\fintiq-app
Copy-Item "..\Fintiq\fintiq_screener.py" "fintiq_screener.py"
git add fintiq_screener.py
git commit -m "..."
git push
```

---

## Project Overview

- **Live app**: `https://app.fintiq.uk` (Railway / Streamlit) — TO BE RETIRED in Phase 1
- **Landing page**: `https://fintiq.uk` (Vercel, files in `C:\Users\imran\Desktop\Fintiq\Articles\`)
- **Main file**: `C:\Users\imran\Desktop\Fintiq\fintiq_screener.py`
- **Deploy repo**: `C:\Users\imran\Desktop\fintiq-app\`
- **Stack**: Streamlit + Anthropic API + yfinance + reportlab + Supabase + Stripe
- **AI models**: `claude-sonnet-5` (Companion), `claude-haiku-4-5-20251001` (Bulletin + summarisation)

---

## 🗺️ MASTER ROADMAP

### CURRENT STATUS — 21 Aug 2026 (Session 8)
All Streamlit bugs are fixed. Migration to fintiq.uk HTML + FastAPI begins today (Phase 1).

### Phase 1 — Move to fintiq.uk HTML site (retire app.fintiq.uk)
1. **Bulletin page** — `fintiq.uk/bulletin.html` (FastAPI backend on Railway). SEO-optimised.
2. **AI Equity Analyst page** — `fintiq.uk/analyst.html` (FastAPI + WebSocket/SSE for streaming).
3. **Additional tools** (HTML pages):
   - DCF / Monte Carlo calculator
   - Pairs trading tool
   - Portfolio optimiser
   - Journal (trade recording)
   - Watchlist (position tracking)
4. **Switch off app.fintiq.uk** — retire Streamlit once all tools are live
5. **Mobile app** — React Native, Phase 2+

### Architecture target
```
fintiq.uk (HTML/JS)  →  api.fintiq.uk (FastAPI on Railway)  →  Supabase + yfinance + Anthropic
```

---

## Session 8 Changes (21 Aug 2026) — Streamlit Fixes + Phase 1 Bulletin Migration ✅

### Fix 1: Stage transition timing bug — ROOT CAUSE of Gordon Growth (lines 8390–8407)
- **Problem**: Stage only advanced fundamental→valuation AFTER the AI replied (post-reply block). So when user typed "Value this company" from fundamental stage: (a) DCF didn't run, (b) AI got fundamental system prompt, (c) AI improvised its own Gordon Growth DCF.
- **Fix**: Added **early stage advancement block** BEFORE the DCF computation and system prompt build. Keywords like `dcf`, `value this`, `wacc`, `scenarios`, `intrinsic value` etc. immediately flip stage to `valuation` — so McKinsey DCF runs and correct prompt is used before the AI call.
- Same early advancement added for valuation→technical and technical→finalise.

### Fix 2: Financial quality table — expanded to 4 years + 2 tables
- **System prompt** (`_comp_system_prompt` fundamental stage, line ~4643): Changed from single 3-year 6-column table to two tables covering the **4 most recent completed fiscal years** (generic, not hardcoded):
  - Table A: Revenue ($M), Rev Growth %, Op Margin %, EPS, EPS Growth %, ROIC %
  - Table B: NOPAT ($M), FCF ($M), Inv Rate %
  - Definitions of NOPAT, FCF, Inv Rate spelled out so AI computes consistently
- **Playbook Q1** (line ~8749): Updated to explicitly request both tables so the user-facing question matches what the system prompt instructs.

---

## Phase 1 Migration — Bulletin (COMPLETE ✅)

### Architecture
```
fintiq.uk/bulletin.html (Vercel, static HTML)
    ↓ fetch https://api.fintiq.uk/bulletin
api.fintiq.uk (FastAPI on Railway — service: fintiq-api, project: captivating-integrity)
    ↓ yfinance + FMP + Claude Haiku
```

### Files created
- `C:\Users\imran\Desktop\fintiq-api\main.py` — FastAPI app
- `C:\Users\imran\Desktop\fintiq-api\requirements.txt`
- `C:\Users\imran\Desktop\fintiq-api\Procfile`
- `C:\Users\imran\Desktop\Fintiq\Articles\bulletin.html` — live bulletin page

### GitHub repo
`https://github.com/imrankhakwani-oss/fintiq-api` (private)

### Railway service
- Project: `captivating-integrity`
- Service: `fintiq-api`
- Temp URL: `https://fintiq-api-production.up.railway.app`
- Custom domain: `api.fintiq.uk` (DNS added to Namecheap, propagating)
- Environment variables set: `ANTHROPIC_API_KEY`, `FMP_KEY`, `REFRESH_TOKEN`

### DNS records added to Namecheap (fintiq.uk)
| Type | Host | Value |
|---|---|---|
| CNAME | `api` | `kwr1easg.up.railway.app` |
| TXT | `_railway-verify.api` | `railway-verify=7b89da160b396...` |

### API endpoints
- `GET /health` — returns `{"status":"ok"}`
- `GET /bulletin` — returns cached bulletin JSON (6h TTL), generates fresh if stale
- `POST /bulletin/refresh?token=fintiq-refresh-2026` — force regenerate

### Tested and confirmed working
- `/health` ✅ returns 200
- `/bulletin` ✅ returns full JSON with live market data (tested at fintiq-api-production.up.railway.app)
- `bulletin.html` ✅ pushed to Vercel (fintiq-landing repo)

### Pending (after coffee break)
- [ ] Verify `api.fintiq.uk/health` works (DNS propagation ~15 min)
- [ ] Verify `fintiq.uk/bulletin.html` renders correctly in browser
- [ ] Begin AI Equity Analyst migration (FastAPI + SSE streaming)

---

### Fix 3: Italic stripping — extended to underscore italics
- `_fix_reply_fmt` now also strips `_single underscore_` italic markers (Streamlit renders these with broken spacing)
- Protects `__bold__` → converts to `**bold**`
- Lone stray `_` in italic positions stripped (word-boundary underscores preserved)

---

## All Previous Changes — Complete History

### Session 7 (19–20 Aug 2026)

#### A. Playbook replaced — 4 sections, 12 questions
- Section 1 "Business & Quality" (~12 credits): 3 questions
- Section 2 "Valuation" (~8 credits): 3 questions
- Section 3 "Technical & Timing" (~10 credits): 3 questions
- Section 4 "Decision" (~8 credits): 3 questions
- Q1 now explicitly requests 4-year financial quality tables (Table A + B)

#### B. SyntaxError fix (line ~4641)
D/E anomaly string had `"""",` — triple-quote terminated early. Fixed using single quotes inside the string.

#### C. DCF architecture — Python-first (`_run_dcf_full()` at line ~8329)
- New function computes complete 10-year McKinsey DCF with year-by-year rows, TV, equity bridge, 3×3 sensitivity grid, Monte Carlo
- `_comp_system_prompt` receives only the 6-number summary (IV/share, MC P25–P75, upside, TV%, WACC, TGR)
- AI is forbidden from recalculating — interprets only
- Gordon Growth explicitly banned: `"Do NOT use Gordon Growth Model (TV = FCF / (WACC - g)) — FORBIDDEN"`

#### D. `__MAX_TOKENS__` sentinel — history corruption fix
- When `stop_reason == 'max_tokens'`, `_comp_ai` returns `"__MAX_TOKENS__"` sentinel instead of broken text
- Main loop detects sentinel and shows user-friendly message; does NOT add broken content to `cp_msgs`
- History stripping: truncation notices + "continue" user turns stripped before API call

#### E. Credit counter persistence — save/restore fix
- `cp_cost_usd` now saved as `cost_usd` in session save dict and restored on Railway container restart

#### F. Stock card timing fix
- Card now appears at any stage (not gated on `stage == 'fundamental'`)
- Also scans AI reply for tickers if user typed company name in lowercase

#### G. Italic fix (initial pass)
- `_fix_reply_fmt` strips `*single-asterisk*` italics, preserves `**bold**`

### Session 6 (18 Aug 2026) — Stage 0 Guardian Restructure

- Discovery stage: only 2 questions (mandate + horizon), then stock selection
- Finalise stage: full `⚠️ GUARDIAN PROTOCOL` — 5 pre-trade challenges (Risk Budget, Correlated Exposure, Conviction Flip, Adversarial Steelman, Instrument Discipline)
- McKinsey DCF enforced at 4 levels in system prompt

### Session 4–5 (14–17 Aug 2026) — UI Fixes + Critical Bug Fixes

- Fix A: Static greeting replaces API call on page load ($0.015 glitch fixed)
- Fix B: Credit clock — 100 credits = $1.00, never shows dollar amounts
- Fix C: Analyst Playbook redesigned
- Fix 1: False ticker detection — `_skip` blocklist expanded to 100+ terms (SBC, PV, NOPAT, RONIC etc.)
- Fix 2: DataFrame truthiness bug fixed (`if _fw_h_cached is not None`)
- Fix 3: DCF hallucination — `⚠️ DCF EXECUTION RULES` block with 5 hard rules (10-year mandatory, self-check, share count discipline, unit consistency)

### Session 3 (12 Aug 2026) — Cost Optimisation + HF Upgrades

- Prompt caching (90% cheaper after first call)
- Conversation summarisation via Haiku (40–50% input reduction)
- Model routing — simple queries → Haiku (15× cheaper)
- 9 HF analyst upgrades: FCF bridge, WACC×TGR sensitivity, SOTP DCF, trade structuring, epistemic language, etc.

---

## ⚠️ DEPLOY STATUS — Session 8

All Session 7+8 changes are in `C:\Users\imran\Desktop\Fintiq\fintiq_screener.py`.
Commits made this session:
1. `Fix: early stage advancement — valuation DCF runs before AI call (kills Gordon Growth)`
2. `Fix: expand financial quality table (4yr, NOPAT/FCF/InvRate), fix italic/underscore stripping`
3. `Fix: financial quality table uses latest 4 fiscal years generically`
4. `Fix: playbook Q1 now explicitly requests 4-year financial quality tables (A+B)`

Verify all are pushed:
```powershell
cd C:\Users\imran\Desktop\fintiq-app
git log --oneline -5
```

---

## Pending Tasks

### Phase 1 Migration
- [x] FastAPI skeleton on Railway (`api.fintiq.uk`) ✅
- [x] Bulletin page (`fintiq.uk/bulletin.html`) ✅ — live, fetches from api.fintiq.uk
- [ ] Verify `api.fintiq.uk` custom domain live (DNS propagating)
- [ ] AI Equity Analyst page (`fintiq.uk/analyst.html`) — FastAPI + SSE streaming — NEXT
- [ ] Switch off app.fintiq.uk

### Backlog
- [ ] Re-enable login/paywall (design TBD)
- [ ] Polygon.io news + earnings feed ($29/mo)
- [ ] 52-week high momentum screen
- [ ] Task #23: Mobile — My Dashboard 3-col grid → single column (CSS fix)
- [ ] Mobile app — React Native (Phase 2+)

---

## Key Functions Reference

| Function | Location | Purpose |
|---|---|---|
| `get_price_display(v, tk, info)` | ~line 800 | Currency-aware price display — ALWAYS use this |
| `get_currency_symbol(tk)` | nearby | Returns £/$/€ |
| `_comp_summarise_history(msgs, stage, ctx)` | ~line 4298 | Summarise old turns via Haiku |
| `_is_simple_query(msg)` | ~line 4345 | True → route to Haiku (~15× cheaper) |
| `_comp_ai(messages, system, stage)` | ~line 4363 | Claude API call — caching, routing, token tracking |
| `_comp_fetch(tk, ff_years=2)` | ~line 4200 | Fetch yfinance + FF4 data |
| `_comp_system_prompt(stage, ctx, data, analyses)` | ~line 4510 | Stage-specific system prompt (all upgrades live here) |
| `_run_dcf_full(...)` | ~line 8329 | Full 10-year McKinsey DCF — Python computes everything |
| `_comp_detect_ticker(text, existing)` | ~line 5045 | Detects new tickers in AI output — expanded _skip set |
| `_comp_generate_report_pdf(...)` | ~line 4845 | 15-section IB-quality PDF report |
| `_make_bulletin(cache_key)` | ~line 3092 | 12h-cached bulletin (Haiku, 08:00+20:00 GMT) |
| `_fix_reply_fmt(txt)` | ~line 8637 | Strips italics, fixes spacing — applied to every AI reply |

---

## McKinsey DCF — Key Formula

```
TV = NOPAT(yr11) × (1 − g/RONIC) / (WACC − g)
Where:
  NOPAT(yr11) = Yr10 Revenue × (1+g) × long-run margin × (1−tax rate)
  RONIC = 15% default (SaaS/software), 12% (mature/cyclical)
  Reinvestment rate in terminal period = g / RONIC

PV of TV = TV / (1+WACC)^10
EV = PV(FCFs Yr1–10) + PV(TV)
Equity Value = EV + net cash
Intrinsic Value = Equity Value / diluted shares outstanding
```

**Phase structure (10 years, mandatory):**
- Phase 1: Yr1–Yr3 (3 years) — near term
- Phase 2: Yr4–Yr7 (4 years) — mid term
- Phase 3: Yr8–Yr10 (3 years) — long term
- Terminal: Yr11 onwards

Gordon Growth (`TV = FCF / (WACC - g)`) is **FORBIDDEN** at all times.

---

## HF Analyst Rating History

| Session | Stock | Rating | Key gaps |
|---|---|---|---|
| Session 1 | CRM | 7.2/10 | WACC build, EV/EBITDA comps, buyback, FF4 failure, options flow |
| Session 3 | Tesla | 6.5/10 | FCF bridge, SOTP, trade structuring, intake protocol, epistemic language |
| Session 5 | AMD | N/A — hallucination | $19/share vs $514 market; SBC false ticker; ValueError crash |
| **Target** | — | **8.5–9/10** | All gaps addressed in system prompt |

---

## yfinance Notes
- UK `.L` stocks: prices in GBp (pence); display as `£X.XX (Xp)` via `get_price_display()`
- `info['debtToEquity']` can be >100x on negative book equity (buyback-heavy firms) — flag this
- `info['earningsTimestamp']` — Unix timestamp for next earnings
- `info['shortPercentOfFloat']` — decimal (0.066 = 6.6%)
- FF4 data in `data[tk]['ff4']`; `None` if outside pre-screened universe
- Share counts: yfinance returns shares in **millions** (e.g. 1620 = 1.62B shares)

---

## Design System
- Navy: `#081220`, `#0D1F35`, `#0F2640`
- Gold: `#F59E0B`, light: `#FCD34D`
- Text: `#F1F5F9`, muted: `#94A3B8`
- Border: `rgba(245,158,11,0.2)`
- Card bg: `rgba(13,31,53,0.8)`
- Font: 'Segoe UI' / 'Inter', system-ui
