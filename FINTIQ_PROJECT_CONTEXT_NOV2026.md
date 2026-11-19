# Fintiq — Master Project Context Document
## Snapshot: 10 November 2026

> **Purpose:** This document is the authoritative context file for the Fintiq project. If you are a new Claude session, read this file entirely before starting any work. It tells you what the project is, what has been built, what the current state is, what decisions have been made, and what still needs to be done. Do NOT start coding until you have read and understood this document.

---

## 1. What Is Fintiq?

Fintiq is a live, revenue-generating fintech platform at **https://www.fintiq.uk** that provides institutional-grade investment research tools to retail investors. The tagline is **"Your Personal Stock Analyst"**.

It was built entirely by a solo founder (Imran Khakwany, contactfintiq@gmail.com). There is no external engineering team. All tools are live, FCA-compliant, and security-hardened as of November 2026.

**Business model:**
- Free tier: all standalone tools, Alpha Scanner, Market Bulletin, Fintiq Scout, Learn section — unlimited, no login required
- Paid tier 1 (subscription): Deep Dive stock analysis — 1 free per email, then £3.50/month (GBP) or $5.00/month (USD) via Stripe
- Paid tier 2 (credit pack): Catalyst Atlas — Tesla is free, all other tickers cost 10 credits = £2.29 (GBP) / $2.99 (USD) one-off, credits never expire

---

## 2. Tech Stack

### Frontend
- **Technology:** Vanilla HTML5 / CSS3 / JavaScript — zero framework dependencies (no React, no Vue, no build step)
- **Hosting:** Vercel, free tier
- **Repo:** `C:\Users\imran\Desktop\Fintiq\Articles`
- **Live URL:** https://www.fintiq.uk
- **Deploy command:** From `C:\Users\imran\Desktop\Fintiq\Articles` → `git push origin master:main`
- **Important:** Vercel watches the `main` branch. Plain `git push` only updates `master` on GitHub and does NOT trigger Vercel deploy. Always use `git push origin master:main`.
- **PowerShell note:** Use separate commands, not `&&`. Run `git add -A`, then `git commit -m "..."`, then `git push origin master:main` as three separate commands.

### Backend
- **Technology:** Python 3.11 · FastAPI · Uvicorn
- **Hosting:** Railway, service name `fintiq-api`, project `captivating-integrity`
- **Repo:** `C:\Users\imran\Desktop\Fintiq\Articles\fintiq-api`
- **Live URL:** https://api.fintiq.uk (custom domain, SSL auto-managed by Railway)
- **Deploy command:** From `C:\Users\imran\Desktop\Fintiq\Articles\fintiq-api` → `git push origin master:main`
- **Main file:** `main.py` (~8,000 lines) + `catalyst_atlas.py` (separate module for Catalyst Atlas)
- **Persistent volume:** `fintiq-api-volume` mounted at `/data` on Railway
  - `/data/alpha_scanner.db` — Alpha Scanner signals + Scout universe SQLite DB
  - `/data/auth.db` — Auth system SQLite DB (users, otps, sessions, portfolio, entitlements)
- **CORS:** Restricted to fintiq.uk, www.fintiq.uk, app.fintiq.uk, localhost — no wildcard

### Storage
- **SQLite (alpha_scanner.db):** Tables: universe, signals, scout_universe, scout_fundamentals, scout_profiles, scout_news
- **SQLite (auth.db):** Tables: users (email, free_used, subscribed), otps (email, code, expires_at, attempts, locked_until), sessions (token, email, expires_at), portfolio (open/closed/watch), entitlements (email, red_team_used, committee_used, reset_month)
- **Upstash Redis (free tier):** Persistent KV cache. Env vars: `_UPSTASH_URL` = `UPSTASH_REDIS_REST_URL`, `_UPSTASH_TOKEN` = `UPSTASH_REDIS_REST_TOKEN`. Cached keys and TTLs:
  - `fintiq:bulletin` — 25h
  - `fintiq:pair_signals` — 14h (also stored as 12h in some contexts)
  - `fintiq:portfolios` — 25h
  - `fintiq:catalyst:{ticker}` — 12h (Catalyst Atlas results)
  - `fintiq:catalyst_news:{ticker}:{date}` — 30 days (news event labels)

### Railway Environment Variables (all confirmed live as of Nov 2026)
```
ANTHROPIC_API_KEY       — Claude API key (Haiku + Sonnet)
FMP_KEY                 — Financial Modeling Prep (free tier, 250 calls/day)
FRED_API_KEY            — Federal Reserve Economic Data (free, unlimited)
REFRESH_TOKEN           — fintiq-refresh-2026 (protects admin/cron endpoints)
BREVO_API_KEY           — Brevo HTTP API for OTP email (sender: hello@fintiq.uk)
TAVILY_API_KEY          — Tavily news search (Catalyst Atlas + Bulletin drivers)
UPSTASH_REDIS_REST_URL  — Upstash Redis REST endpoint
UPSTASH_REDIS_REST_TOKEN — Upstash Redis token
STRIPE_SECRET_KEY       — Stripe live secret key
STRIPE_WEBHOOK_SECRET   — Stripe webhook signing secret (whsec_...)
GMAIL_APP_PASSWORD      — (legacy, no longer used for email)
```

**Important:** All credentials are in Railway env vars. There are NO hardcoded credentials in the source code (this was a security fix made in November 2026).

---

## 3. All Live Products & Tools

### 3.1 Core Paid Product — Stock Deep Dive
**URL:** https://www.fintiq.uk/deep-dive.html  
**Gate:** 1 free per email → £3.50/month subscription

Deep Dive is a 7-section AI-powered stock analysis tool for any US or UK ticker:

1. **Business Analysis** — business model, revenue breakdown by segment/geography, moat assessment, risk summary
2. **Valuation** — DCF model (5-year, 3 scenarios: bear/base/bull), intrinsic value range, Monte Carlo sensitivity
3. **Technical Analysis** — RSI, MACD, 50/200-day MAs, trend verdict, support/resistance
4. **Risk & Position Sizing** — Kelly criterion, volatility-adjusted position size, beta, max drawdown
5. **Catalyst Tracker** — summarises recent price catalysts; "Open Catalyst Atlas" button links to Catalyst Atlas for full attribution
6. **Investment Committee** — 4-analyst AI panel (Value, Growth, Technical, Risk) debates the thesis; conviction score 0–100; Red Team plays devil's advocate. 2 uses/month per subscriber.
7. **Trading Journal** — save stocks to Watch/Open/Closed portfolio; R:R bidirectional calculator; connects to Portfolio tools

**AI models used:**
- Claude Haiku: Business Analysis, Valuation, Technical, Risk, Catalyst, Copilot chat, Section summariser
- Claude Sonnet (claude-sonnet-4-6): Investment Committee, Red Team, AI Challenge

**AI cost per session:** ~$0.11–0.15 (Committee Report is 60–70% of this)

**Entitlement limits (per user per month):**
- Committee Report: 2 uses/month (tracked in SQLite entitlements table)
- Red Team: 3 uses/month (tracked in SQLite entitlements table)
- Reset monthly based on `reset_month` field in entitlements table

### 3.2 Second Paid Product — Catalyst Atlas
**URL:** https://www.fintiq.uk/catalyst-atlas.html  
**Engine:** `catalyst_atlas.py` (VERSION = "v8")  
**API endpoint:** `GET /catalyst-atlas/{ticker}`  
**Gate:** Tesla free (auto-refreshes ~every 10h); all others: 10 credits = £2.29 / $2.99 one-off

Catalyst Atlas answers: *"Why did this stock move, and how does it normally respond to each type of news?"*

**How the engine works:**
1. Rolling 250-day OLS regression decomposes every daily price return into:
   - **Market factor:** SPY (US stocks) or ^FTSE (UK stocks)
   - **Sector factor:** Equal-weight sector ETFs (RSPT, RSPD, RSPF, RSPG, RSPH, etc.) or Brent crude (BZ=F) for energy companies
   - **Rates factor:** ^TNX (10Y Treasury yield) — US stocks only
   - **Idiosyncratic residual:** company-specific component
2. Identifies significant company-specific days over 3 years
3. Retrieves contemporaneous news via Tavily; Claude Haiku labels each event into 12 categories:
   - Earnings & guidance | Sales & delivery data | Product & technology | Analyst rating
   - Deals & partnerships | Legal & regulation | Management & leadership | Politics & policy
   - Competition | Customer & industry demand | Market-wide news | Unexplained
4. Measures each catalyst's "footprint": price behaviour from 5 days before to 60 days after
5. Scores how reliably each category moved the price and whether the move was sustained
6. Computes likely price ranges: 1 week, 1 month, 3 months
7. Writes plain-English *Fintiq Analyst's View* using Claude Sonnet

**Caching:** Results 12h, news event labels 30 days (Upstash Redis)  
**UK shares:** Displayed in pounds (not pence)  
**Deep Dive integration:** "Open Catalyst Atlas" button in the Catalyst Tracker section — users funnelled into credit-pack model from inside the core product  
**AI cost per search:** ~$0.03–0.05 (Haiku news labelling + Sonnet Analyst's View + Tavily news fetch)  
**Payment:** Stripe Checkout using the same webhook as subscriptions (`checkout.session.completed`)

### 3.3 Free Tools (all unlimited, no login required)

| Tool | URL | Description |
|------|-----|-------------|
| **Market Bulletin** | /bulletin.html | Daily AI market brief — S&P, macro, sector heat map, Momentum Spotlight, EPS Tracker, trade ideas. Auto-regenerates 3×/day at 06:30, 13:00, 21:00 UTC via cron-job.org |
| **Alpha Scanner** | /alpha-scanner.html | Reads SEC filings (10-K/10-Q) for 1,100+ micro/small-cap US stocks daily. Piotroski F-Score, Altman Z-Score, Beneish M-Score. Daily cron at 06:00 London time. |
| **Fintiq Scout** | /ai-stock-scanner.html | Natural language stock screener: "profitable AI companies under $50bn" → Claude translates to filter params → screens 900+ stocks → AI-ranked results |
| **Factor Screener** | /factor-screener.html | Fama-French 4-factor model on US, UK, EU stocks. Per-stock factor breakdown and alpha signals. |
| **Portfolio Optimiser** | /portfolio-optimiser.html | Mean-variance optimisation (Markowitz). Efficient frontier. Sharpe/Sortino/Treynor/Jensen's Alpha. 3 Fintiq model portfolios. |
| **Portfolio Monte Carlo** | /portfolio-monte-carlo.html | Correlated multi-asset simulation. 5,000 paths, Cholesky decomposition, monthly contributions, fan chart, up to 20-year horizon. |
| **PriceSpectrum** | /price-spectrum.html | GARCH(1,1) + Student-t + jump-diffusion Monte Carlo for single stock. 6 horizons (1d to 1y). Fan chart. |
| **Pairs Trading** | /pairs-trading.html | 50 preset cointegrated pairs + custom. Z-score, OLS hedge ratio, mean-reversion signals. Plain-English trade instructions with entry/exit prices. |
| **UK Pension Planner (SIPP)** | /sipp-planner.html | SIPP and State Pension planner. Monte Carlo survival probability. Drawdown strategy. |
| **US Pension Planner** | /us-pension-planner.html | 401(k) / IRA planner with Monte Carlo. Social Security integration. |
| **Learn Section** | /learn.html | 28 original research articles: equity valuation, factor investing, pairs trading, retirement planning, etc. |

---

## 4. Authentication System

**Method:** Passwordless email OTP (6-digit code, 10-minute TTL, single-use)

**Flow:**
1. User enters email → `POST /auth/request-otp` → Brevo sends OTP from hello@fintiq.uk
2. User enters code → `POST /auth/verify-otp` → returns raw 32-byte session token
3. Session token stored in browser `localStorage` as `fintiq_session`
4. All gated endpoints validate token via `GET /auth/session` or `Bearer` header

**Security hardening (November 2026):**
- OTP: `secrets.randbelow(900000) + 100000` (not `random.randint` — was a vulnerability)
- OTP rate limiting: 5 requests/email/hour, 20 requests/IP/hour (Upstash Redis INCR/EXPIRE)
- OTP brute force: 5 failed attempts → 15-minute lockout (tracked in `attempts` + `locked_until` columns in otps table)
- Session tokens: stored as SHA-256 hashes in SQLite. Raw token returned to client, only hash stored. Hashed using `hashlib.sha256(token.encode("utf-8")).hexdigest()`.
- Column name: **`token`** (not `token_hash` — do not rename this column; `CREATE TABLE IF NOT EXISTS` does not update existing schema and renaming would break INSERTs)
- Session TTL: 30 days, server-side expiry check on every request

**OTP table schema:**
```sql
CREATE TABLE IF NOT EXISTS otps (
    email TEXT PRIMARY KEY,
    code TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    attempts INTEGER DEFAULT 0,
    locked_until TEXT
)
```

**Sessions table schema:**
```sql
CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,  -- stores SHA-256 hash of raw token
    email TEXT NOT NULL,
    expires_at TEXT NOT NULL
)
```

**Entitlements table:**
```sql
CREATE TABLE IF NOT EXISTS entitlements (
    email TEXT PRIMARY KEY,
    red_team_used INTEGER DEFAULT 0,
    committee_used INTEGER DEFAULT 0,
    reset_month TEXT NOT NULL
)
```

**SQLite migrations note:** `CREATE TABLE IF NOT EXISTS` does NOT update existing schema. New columns must be added via `ALTER TABLE ... ADD COLUMN` in a try/except loop (already done in main.py for `attempts` and `locked_until`).

---

## 5. Stripe Payments

**Stripe account:** Fintiq Ltd  
**Product:** Fintiq Pro Monthly

**Live prices:**
- GBP subscription: `price_1URcWIFSQ5tKKNExDcY6pHie` — £3.50/month
- USD subscription: `price_1URcWIFSQ5tKKNExCAchLzVg` — $5.00/month
- Catalyst Atlas GBP: price set in code — £2.29 for 10 credits
- Catalyst Atlas USD: price set in code — $2.99 for 10 credits

**Stripe Publishable key:** `pk_live_51Trh5LFSQ5tKKNExfhxdheHwtTdhZT3iT8emIw1g3VE3Os0j1Sm8fqbT2fHtndnQFQuaVLdcJ7Hjdi1UgsedKf400NfC2ofqP`

**Webhook:** https://api.fintiq.uk/stripe/webhook  
Webhook name: "exquisite-celebration"  
Listens to: `checkout.session.completed`, `customer.subscription.deleted`, `customer.subscription.paused`

**Security (November 2026):** Stripe webhook signature verification is MANDATORY. The endpoint rejects any request if `STRIPE_WEBHOOK_SECRET` is not set or if the HMAC-SHA256 signature does not match. This was previously conditional (a security vulnerability) — it is now hardcoded as required.

---

## 6. Cron Jobs (all on cron-job.org)

| Job Name | Schedule | URL |
|---|---|---|
| Fintiq Bulletin — UK Open | 06:30 London daily | POST https://api.fintiq.uk/bulletin/refresh?token=fintiq-refresh-2026 |
| Fintiq Bulletin — US Open | 13:00 London daily | POST https://api.fintiq.uk/bulletin/refresh?token=fintiq-refresh-2026 |
| Fintiq Bulletin — US Close | 21:00 London daily | POST https://api.fintiq.uk/bulletin/refresh?token=fintiq-refresh-2026 |
| Alpha Scanner daily | 06:00 London daily | GET https://api.fintiq.uk/alpha-scanner/run?token=fintiq-refresh-2026 |
| Scout news refresh | 07:00 London daily | GET https://api.fintiq.uk/scout/news-refresh?token=fintiq-refresh-2026 |
| Scout weekly fundamentals | Sunday 05:00 | GET https://api.fintiq.uk/scout/weekly-refresh?token=fintiq-refresh-2026 |
| Scout monthly rebuild | 1st of month 04:00 | GET https://api.fintiq.uk/scout/monthly-refresh?token=fintiq-refresh-2026 |

---

## 7. Work Completed — November 2026 Session

### 7.1 FCA Compliance Audit (COMPLETED)
Full review of all pages against s.21 FSMA 2000 (financial promotions). Changes deployed:
- Alpha Scanner: "Buy" → "Opportunity"; disclaimer updated
- Deep Dive: AI Challenge conviction language softened; factor labels updated ("Avoid" → "No Alpha")
- Pairs Trading: "BUY — underpriced" → "Long Signal — spread below mean"; "SELL — overpriced" → "Short Signal — spread above mean"
- Factor Screener: "stocks worth researching further" → "may warrant further independent research"
- Pension Planner: "real probability" → "estimated probability"
- All tools: standardised footer disclaimer — "For research purposes only. Not financial advice or a personal recommendation. Always conduct your own research and consider speaking to a qualified financial adviser before investing."

### 7.2 Security Hardening (COMPLETED & DEPLOYED)
All 8 security fixes applied to `main.py` and deployed to Railway:

1. **Hardcoded credentials removed:** `FMP_KEY` and `REFRESH_TOKEN` now read from env vars only (were hardcoded as fallbacks — huge vulnerability)
2. **Stripe webhook mandatory:** Signature verification is now required; endpoint returns 500 if `STRIPE_WEBHOOK_SECRET` not configured (was previously optional)
3. **OTP cryptographically secure:** Changed from `random.randint` to `secrets.randbelow(900000) + 100000`
4. **OTP console logging removed:** Was printing `[Auth] OTP for {email}: {code}` to Railway logs — anyone with log access could hijack any account
5. **Admin OTP endpoint removed:** `GET /auth/admin/otp` could retrieve any live OTP for any email — deleted entirely
6. **OTP rate limiting added:** `_rate_limit_check()` using Upstash Redis INCR/EXPIRE. Limits: 5/email/hour, 20/IP/hour. Fail-open (if Redis down, rate limiting degrades gracefully)
7. **OTP brute force protection:** 5 failed attempts triggers 15-minute email lockout. `attempts` and `locked_until` columns added to `otps` table via ALTER TABLE migration. `_auth_increment_otp_attempts()` function added.
8. **Session tokens hashed:** SHA-256 hash stored in SQLite instead of raw token. `_hash_token()` function added. `_auth_create_session()` returns raw token to client, stores hash. `_auth_get_session_user()` hashes before lookup. Existing sessions (unhashed) become invalid on deploy → users log out once and re-authenticate (20-second process). No schema migration needed — column name stays as `token`.

**Impact of security changes on users:** Minimal. FMP_KEY/REFRESH_TOKEN already set in Railway env vars. OTP still 6 digits. Rate limiting fail-open. Session hash → one-time logout on deploy. Stripe already has webhook secret.

### 7.3 Technical Information Memorandum (COMPLETED)
**File:** `C:\Users\imran\Desktop\Fintiq\Articles\Fintiq_TIM_November_2026.html`

A 12-section TIM for prospective acquirers and white-label partners. Open in browser and use the "Save / Print PDF" button to generate PDF. Sections:
1. Executive Summary
2. Product Overview (Deep Dive, Catalyst Atlas §2.3, free tool ecosystem)
3. Technical Architecture
4. Backend API Endpoints
5. Data Sources & Coverage
6. Operating Cost Model (fixed ~£25–35/month; variable ~$0.11–0.15/Deep Dive session; ~$0.03–0.05/Catalyst Atlas search)
7. Regulatory Compliance (FCA s.21 FSMA 2000, GDPR)
8. Security (all November 2026 hardening)
9. White-Label Offering (10-day deployment timeline, customisation table)
10. Assets Included
11. Near-Term Roadmap
12. Transaction Structure (acquisition vs white-label)

---

## 8. Agreed Work Order (IN PROGRESS)

Tasks agreed in this session, in order:

| # | Task | Status |
|---|------|--------|
| 1 | FCA Compliance Audit | ✅ DONE |
| 2 | Security Hardening | ✅ DONE |
| 3 | Technical Information Memorandum (TIM) | ✅ DONE |
| 4 | Marketing Plan | ⏳ NEXT |
| 5 | AI Agent Plan (Autopilot tier) | ⏳ PENDING |

---

## 9. Pending Work (Before This Session's Work Order)

From earlier sessions — still outstanding:

### Scout Fixes (deploy pending as of Nov 3, 2026)
- CSV download gate fixed: use `fintiq_session` not `dd_session` in localStorage check
- Yield display fixed: `_pct()` double-multiplication bug
- Sort options added: Div Yield ↓, P/E ↑, Rev Growth ↓
- Metric label: "Yield" → "Div Yield"
- Sort fields: `pe`, `dividend_yield`, `revenue_growth` added to `_make_result`
- Revenue growth capped at -99/+300, data notice added
- SVG candlestick logo added to ai-stock-scanner.html nav
- Enter key submits (was Ctrl+Enter)
- **Status:** These may already be deployed — check by visiting fintiq.uk/ai-stock-scanner.html and testing sort options. If sort select is broken or CSV gate fails, these commits still need to be pushed.

### app.fintiq.uk Noindex
- `app.fintiq.uk` (Streamlit app — legacy) needs `robots.txt` or `X-Robots-Tag: noindex` to prevent Google Search Console from indexing the API subdomain
- API responses already have `X-Robots-Tag: noindex` added in this session

### FMP Enterprise Licence
- FMP enterprise licence application submitted November 2026 — awaiting quote
- When approved, replace yfinance fundamentals in Scout and Deep Dive with FMP structured data
- Need Premium minimum ($69/month) for FTSE coverage

---

## 10. Near-Term Product Roadmap

### Autopilot — Agentic AI Tier (£15/month)
Planned third tier using Claude tool-use API:
- **Portfolio Monitor Agent:** watches saved portfolio for earnings dates, analyst upgrades, insider trades, news catalysts — sends email alerts
- **Research Agent:** given a thesis, autonomously runs Scout + Deep Dive + Factor Screener + Alpha Scanner → ranked shortlist
- **Alert Agent:** price/Z-score/RSI threshold alerts on saved ticker or pair
- **Architecture:** single `/agent` FastAPI endpoint; Claude calls existing Fintiq tools as function calls; results streamed to frontend via SSE
- **Breakeven:** ~6 users at £15/month covers FMP Premium + all fixed costs

### Alpha Scanner Phase 2
- FINRA short interest data
- S-3 registration statement dilution detector
- Going concern language scanner
- Supply chain contagion monitor

### Options Tool
- Options data overlay on Pairs Trading
- IV comparison between both legs, vol pairs trading, put/call skew, term structure

### FMP Integration
- Replace yfinance fundamentals with FMP structured data once enterprise licence confirmed
- Use annual income statements for revenue growth (fix the quarterly YoY inconsistency in Scout)
- Improves reliability for autonomous Autopilot agent decisions

---

## 11. Key Business Decisions & Context

- **Pricing:** £3.50/month (GBP) / $5.00/month (USD) — "one Starbucks coffee" anchor for early traction
- **Free tier philosophy:** All tools free to maximise top-of-funnel; only Deep Dive (subscription) and Catalyst Atlas (credit pack) are gated
- **FCA approach:** Educational research tools, not personal recommendations. All copy reviewed November 2026 to remove any "buy/sell/hold" language.
- **Data sources:** Yahoo Finance (yfinance) for most data — free but Terms of Service risk at scale. FMP enterprise licence pending for commercial deployment. FRED free and explicitly commercial-use permitted. SEC EDGAR free and unlimited.
- **Email:** Brevo HTTP API, sender hello@fintiq.uk, DKIM + DMARC authenticated. Gmail SMTP does NOT work on Railway (blocked ports). Do NOT use Gmail as FROM address.
- **Catalyst Atlas pricing:** Chose credit pack (not subscription) so users don't need to commit monthly just to understand why a stock moved. Tesla free as a marketing hook.

---

## 12. Data Sources

| Source | Usage | Cost | Commercial Risk |
|--------|-------|------|-----------------|
| Yahoo Finance (yfinance) | Prices, fundamentals, earnings for most tools | Free | Medium — ToS restricts commercial use at scale |
| Financial Modeling Prep (FMP) | Revenue segment breakdown, economic indicators | Free tier (250 calls/day); enterprise TBD | Low — enterprise licence pending |
| FRED (St. Louis Fed) | CPI, NFP, PCE, GDP, yield curve | Free, unlimited | None — explicitly commercial |
| SEC EDGAR | 10-K/10-Q filings for Alpha Scanner (1,100+ stocks) | Free, unlimited | None — public data |
| Tavily Search API | News retrieval for Catalyst Atlas + Bulletin drivers | ~$0.001/call variable | Low |
| Brevo | OTP email delivery | Free tier (300/day) | Low |
| Upstash Redis | Persistent cache | Free tier | Low |
| Stripe | Subscription + credit pack payments | 2.9% + 30p/transaction | None |
| Anthropic (Claude API) | Deep Dive, Bulletin, Scout, Catalyst Atlas, Alpha Scanner | Variable — see §6 | Low |

---

## 13. Fintiq Scout — Technical Details

**URL:** /ai-stock-scanner.html  
**Universe:** ~906 stocks — S&P 500 + Nasdaq 100 + DJ30 + FTSE 100 + Euro Stoxx 50 + ~30 major ADRs

**Three-stage scan pipeline:**
1. Claude Haiku translates natural language thesis → filter params JSON (using DATA_CAPABILITIES manifest)
2. Python screens SQLite `scout_fundamentals` table against filter params
3. Claude Haiku picks best 5-8 from screened results and writes plain-English explanations

**Scout database (in `/data/alpha_scanner.db`):**
- `scout_universe`: all 906+ tickers
- `scout_fundamentals`: PE, revenue growth, margins, dividend yield, market cap, etc.
- `scout_profiles`: Claude Haiku-tagged theme scores (AI, defence, energy, healthcare, fintech, EV/renewable, cybersecurity) + geography + dollar sensitivity
- `scout_news`: 14-day rolling window of news keywords per ticker

**Current scout status (Nov 3, 2026):** 806 universe, 778 fundamentals, 762 tagged

**Scout cron jobs:** 3 jobs on cron-job.org (daily news 07:00, weekly fundamentals Sunday 05:00, monthly rebuild 1st of month 04:00)

---

## 14. Market Bulletin — Technical Details

**URL:** /bulletin.html  
**Regeneration:** 3×/day via cron-job.org (06:30, 13:00, 21:00 London time) + POST /bulletin/refresh endpoint (token-protected)

**Bulletin sections (JSON structure):**
- `the_call`: headline, bullets, session label (AM/PM/EOD/ASIA), generated_at
- `market_prices`: 8 tiles (SPX, Nasdaq, DJIA, VIX, 10Y, 2Y, Gold, Brent) with sparklines
- `sentiment`: gauge score, signal chips
- `vix_term`: VIX9D, spot, VIX3M, contango/inversion signal
- `sectors_data`: 10 sector ETF tiles with heat intensity and sparklines
- `mag7`: 7 large-cap tiles with next earnings date
- `event_radar`: 7-day economic calendar chips
- `today_drivers`: Tavily-sourced news labelled by Claude Haiku into Context/Event/Impact framework
- `momentum_spotlight`: 12 stocks with live prices and thesis
- `eps_tracker`: earnings for S&P 500, Nasdaq 100, FTSE 100 — upcoming + recently reported
- `risk_radar`: geopolitical risk flags
- `global_monitors`: UK/Europe/Asia market data
- `macro_calendar`: 45-day economic calendar with FRED previous readings

**Caching:** Upstash Redis (25h TTL); also persisted to Railway `/data` volume as `fintiq_bulletin_cache.json`; browser localStorage cache (25h TTL, key `fintiq_bulletin_v2`)

---

## 15. Alpha Scanner — Technical Details

**URL:** /alpha-scanner.html  
**Universe:** 1,100+ US micro/small-cap stocks that file with SEC  
**Daily cron:** 06:00 London time — reads SEC 10-K/10-Q filings for each stock, runs scoring models, stores signals

**Scoring models:**
- Piotroski F-Score (financial health, 0–9)
- Altman Z-Score (bankruptcy risk)
- Beneish M-Score (earnings manipulation detection)

**Signal labels:** "Opportunity" (not "Buy" — FCA compliance). "Watch", "Monitor".

**AI:** Claude Haiku analyses filing text for language drift (tone changes in management discussion)

---

## 16. Frontend Pages (all live on Vercel)

| Page | URL |
|------|-----|
| Homepage | /index.html |
| Tools | /tools.html |
| Deep Dive | /deep-dive.html |
| Market Bulletin | /bulletin.html |
| Alpha Scanner | /alpha-scanner.html |
| Fintiq Scout | /ai-stock-scanner.html |
| **Catalyst Atlas** | **/catalyst-atlas.html** |
| Factor Screener | /factor-screener.html |
| Portfolio Optimiser | /portfolio-optimiser.html |
| Portfolio Monte Carlo | /portfolio-monte-carlo.html |
| PriceSpectrum | /price-spectrum.html |
| Pairs Trading | /pairs-trading.html |
| UK Pension Planner | /sipp-planner.html |
| US Pension Planner | /us-pension-planner.html |
| Learn | /learn.html |
| Sitemap | /sitemap.xml |
| Robots | /robots.txt |
| + 28 learn articles | /learn/*.html |

**Design system:** Dark theme (#0A1628 navy, #F59E0B amber accent, #0F766E teal); responsive mobile-first; 5-tab mobile bottom nav on all pages (using `<div class="mobile-bottom-nav">` NOT `<nav>` — generic `nav{}` CSS selector causes blank screen on pages that use it); SVG candlestick logo across all pages; Google Analytics G-SFD342RVKK

---

## 17. Backend API — Key Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/bulletin` | GET | Full structured Market Bulletin JSON. Cached 25h. |
| `/bulletin/refresh` | POST | Regenerate bulletin. Protected by REFRESH_TOKEN query param. |
| `/market-data` | GET | Live snapshot: S&P500, Nasdaq, VIX, 10Y/2Y yields, gold, oil, sector ETFs, Mag7. |
| `/prices/{ticker}` | GET | Historical daily closes. Periods: 5d/1mo/3mo/6mo/1y/2y/3y/5y. |
| `/quotes` | GET | Batch live price + % change for up to 20 tickers. |
| `/fundamentals/{ticker}` | GET | Full fundamental data: revenue, margins, P/E, EV/EBITDA, beta, DCF inputs, segment breakdown, earnings history. |
| `/deep-dive/section` | POST | Generates one of 6 Deep Dive analysis sections via Claude AI. |
| `/committee/report` | POST | Full 4-analyst Investment Committee report. 2 uses/month per subscriber. |
| `/red-team` | POST | AI devil's advocate critique. 3 uses/month per subscriber. |
| `/copilot/chat` | POST | Conversational AI analyst in context of current Deep Dive session. |
| `/catalyst-atlas/{ticker}` | GET | Full Catalyst Atlas analysis: attribution decomposition, news-labelled catalysts, footprint scores, price ranges, Analyst's View. Requires Atlas credit or Tesla ticker. Cached 12h. |
| `/alpha-scanner/signals` | GET | All active Alpha Scanner signals from SQLite. Updated daily. |
| `/alpha-scanner/run` | GET | Triggers full Alpha Scanner run. Protected. ~20min. |
| `/pair-signals` | GET | Pre-computed Z-scores, correlations, prices for all 50 preset pairs. Cached 12h. |
| `/optimise` | POST | Portfolio optimisation: efficient frontier, max Sharpe, min vol, Sortino, Treynor, Jensen's Alpha. |
| `/fintiq-portfolios` | GET | 3 pre-computed Fintiq model portfolios. Cached 24h. |
| `/portfolio-monte-carlo` | GET | Correlated multi-asset Monte Carlo. 5,000 paths. Fan chart + horizon percentiles. |
| `/price-spectrum` | GET | GARCH(1,1) + jump-diffusion MC for single stock. Fan chart + 6 horizons. |
| `/factor-screener` | GET | Fama-French 4-factor alpha signals for US/UK/EU universe. |
| `/scout/scan` | POST | Natural language stock screener: thesis → filter params → SQLite screen → AI-ranked results. |
| `/scout/status` | GET | Scout database status (counts, last update, ready flag). |
| `/scout/news-refresh` | GET | Daily news refresh for Scout. Protected by REFRESH_TOKEN. |
| `/scout/weekly-refresh` | GET | Weekly fundamentals refresh for Scout. Protected. |
| `/scout/monthly-refresh` | GET | Monthly full universe rebuild for Scout. Protected. |
| `/auth/request-otp` | POST | Sends 6-digit OTP to email. Rate-limited: 5/email/hour, 20/IP/hour. |
| `/auth/verify-otp` | POST | Verifies OTP, creates 30-day session token. Returns raw token. |
| `/auth/session` | GET | Validates Bearer session token. Returns authenticated status + user. |
| `/auth/use-session` | POST | Gates Deep Dive: marks free session consumed; returns 402 if free used and not subscribed. |
| `/create-checkout-session` | POST | Creates Stripe Checkout session. Returns checkout_url. Supports GBP + USD. |
| `/stripe/webhook` | POST | Receives Stripe events. MANDATORY HMAC-SHA256 verification. Flips subscribed flag. |
| `/portfolio/*` | CRUD | Full portfolio management: Watch/Open/Closed lifecycle, R:R calculation. 6 endpoints. |

---

## 18. Important Technical Gotchas

1. **PowerShell `&&` does NOT work.** Use separate commands on separate lines.
2. **Always push with `git push origin master:main`**, not plain `git push` (which only updates `master` on GitHub and doesn't trigger Vercel/Railway).
3. **Push backend before frontend** when both repos have changes.
4. **SQLite `CREATE TABLE IF NOT EXISTS` does NOT modify existing schema.** To add columns, use `ALTER TABLE ... ADD COLUMN` in a try/except (already done for `attempts`, `locked_until`).
5. **Never rename `sessions.token` column to `token_hash`.** The existing table has `token TEXT PRIMARY KEY NOT NULL`. Renaming would break all INSERTs without a migration.
6. **`_auth_get_otp()` returns a tuple `(code, locked)`, NOT just `str | None`.** Updated in November 2026 — any new code calling this function must unpack both values.
7. **Mobile nav must use `<div class="mobile-bottom-nav">` NOT `<nav>`.** Pages with a generic `nav {}` CSS selector get a blank screen if `<nav>` is used.
8. **Brevo free tier: 300 OTP emails/day.** At scale, upgrade or add fallback provider.
9. **Railway cold starts wipe `/tmp`.** Use `/data` volume for all persistent SQLite databases. Upstash Redis for cache.
10. **X-Robots-Tag: noindex added to all API responses** (November 2026) to prevent Google Search Console from indexing api.fintiq.uk.

---

## 19. Document & Deliverable Status

| Document | Location | Status |
|----------|----------|--------|
| Technical Information Memorandum | `C:\Users\imran\Desktop\Fintiq\Articles\Fintiq_TIM_November_2026.html` | ✅ COMPLETE — open in browser → Print to PDF |
| This context document | `C:\Users\imran\Desktop\Fintiq\Articles\FINTIQ_PROJECT_CONTEXT_NOV2026.md` | ✅ CURRENT AS OF NOV 10, 2026 |
| FCA compliance audit report | Completed in session, deployed to live site | ✅ DEPLOYED |
| Security audit report | Completed in session, deployed to live site | ✅ DEPLOYED |
| Marketing Plan | Not started | ⏳ NEXT |
| AI Agent Plan | Not started | ⏳ AFTER MARKETING PLAN |

---

## 20. Contact & Accounts

- **Founder:** Imran Khakwani
- **Business email:** contactfintiq@gmail.com
- **OTP sender email:** hello@fintiq.uk (Brevo-authenticated)
- **Google Analytics:** G-SFD342RVKK
- **Railway project:** captivating-integrity → service: fintiq-api
- **Vercel project:** Fintiq (auto-deploy from GitHub main)
- **Stripe account:** Fintiq Ltd → product: Fintiq Pro Monthly
- **Brevo account:** hello@fintiq.uk domain, DKIM + DMARC authenticated
- **Upstash account:** Database: fintiq-cache (EU-West-1)
- **cron-job.org:** 7 jobs active (see §6)
- **Google Search Console:** www.fintiq.uk, sitemap submitted

---

*Last updated: 10 November 2026 by Claude (claude-sonnet-4-6) in Cowork session with Imran Khakwani.*  
*To resume work: read this document, then ask the user which item on the work order to tackle next (Marketing Plan or AI Agent Plan).*
